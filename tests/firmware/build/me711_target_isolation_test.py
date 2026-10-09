#!/usr/bin/env python3
r"""
me711_target_isolation_test.py - a configuration for one board must not be
applied to another, and must fail cleanly when it is tried.

    py tests\firmware\build\me711_target_isolation_test.py

WHY THIS MATTERS MORE THAN IT SOUNDS.

The whole point of the universal configuration is that a connector pin number
is the unit a tuner works in. That only works while the pin number is attached
to a BOARD: pin 96 is injector 1 on the Bosch ME7.1.1 and something else
entirely on the VAG ME7.5, and the two descriptors already disagree about most
of the connector. A preset that names pin numbers is therefore meaningless
without a target, and applying one to the wrong board would route injectors and
coils by number onto whatever those numbers happen to be over there.

The preset table carries a target_id for exactly this reason. This file checks
that the check is real, that a refusal is CLEAN - nothing half-written - and
that the two descriptors genuinely disagree, because if they agreed there would
be nothing to protect.

The image under test is the ME7.1.1, so its own preset must apply and the
ME7.5 one must be refused. The reverse direction is checked against the model,
since only one target is linked into any image.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools/config_source"))

import me711_config_state_test as C   # noqa: E402
import me711_image as PI              # noqa: E402
import hw_descriptors as HW           # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths as HCP  # noqa: E402

SHARED = ROOT / "firmware"

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def target_ids():
    out = {}
    for f in HCP.GENERATED.glob("hc_pin_desc_*.c"):
        m = re.search(r"hc_pin_target_id\s*=\s*(0x[0-9A-Fa-f]+)",
                      f.read_text(errors="replace"))
        if m:
            out[f.stem.replace("hc_pin_desc_", "")] = int(m.group(1), 16)
    return out


def presets():
    """(id, n_items, target_id) from the generated table."""
    txt = (SHARED / "generated/hc_presets.c").read_text(errors="replace")
    body = txt[txt.index("const hc_preset_t hc_engine_presets[]"):]
    body = body[:body.index("};")]
    out = []
    # THE ROW GAINED A FIELD AT V61 AND THIS PATTERN PINNED THE OLD ARITY.
    #
    # hc_preset_t grew `board_default`, so every row became five fields and
    # this regex - which required the row to END after the target id - matched
    # NOTHING. The gate then reported "0 distinct bound targets" and failed,
    # which reads exactly like "no preset is bound to a board" and is the
    # opposite of the truth. Trailing fields are now tolerated and the four
    # this check actually uses are still pinned by position.
    for m in re.finditer(r"\{\s*(\d+)u,\s*(\w+|0),\s*(\d+)u,"
                         r"\s*(0x[0-9A-Fa-f]+|0)u?,\s*(\d+)u\s*\}", body):
        out.append((int(m.group(1)), m.group(2), int(m.group(3)),
                    int(m.group(4), 0), int(m.group(5))))
    return out


def boot():
    r = C.Rig()
    r("hc_cfg_init")
    r("hc_cfg_mgr_init")
    return r


def snapshot(r, n=512):
    """The whole universal block, so a partial write cannot hide.

    AND IT NOW READS EVERY BYTE, WHICH IS WHAT THIS DOCSTRING ALWAYS CLAIMED.
    It sampled every EIGHTH byte, and that was invisible while a preset moved
    every pin field off 0xFF - some sample always moved with it. V61's board
    default pre-seeds those fields, so preset 2's only remaining universal-block
    change is `trigDecoder` at offset 2539 - and 2539 is not a multiple of 8
    from the block base, so the stride stepped straight over it and the gate
    reported a working preset as "changes nothing".

    A sampling stride cannot catch a partial write either, which is the other
    thing this function is for. Reading all 512 bytes costs a few seconds and
    removes both blind spots."""
    base = C.UNI_BASE
    return bytes(r.callb("hc_cfg_mgr_read_u8", base + i) for i in range(n))



# THE BUDGET FOLLOWS THE PRESET, BECAUSE A LITERAL ONE WENT MARGINAL.
# The rig's call ran on a flat 400 000 steps. MEASURED on V93 r2: the AWT
# preset (id 3) - the V92 stock base maps made it the largest - needs 710 513
# steps to stage, validate and apply; the Porsche V8 donor 105 499 (refused on
# content); the board default 146 927. The gate then reported "did not return
# within 400000 steps", which reads like a hung firmware and is a budget. So
# it is sized from the preset's own item count, with room to grow.
def apply_preset(r, pid, n_items):
    budget = 400_000 + 4_000 * max(n_items, 0)
    return r("hc_preset_apply_engine", pid, 0, steps=budget) & 0xFF

def main() -> int:
    print("=== HaniCore - one board's configuration must not reach another ===\n")
    print("  image   %s" % PI.image().name)
    print("  sha256  %s\n" % PI.sha256())

    ids = target_ids()
    print("  target ids from the linked descriptors:")
    for k, v in sorted(ids.items()):
        print("    %-24s 0x%04X" % (k, v))
    check("the two boards have DIFFERENT target ids",
          len(set(ids.values())) == len(ids) and len(ids) >= 2,
          ", ".join("0x%04X" % v for v in sorted(ids.values())))

    ps = presets()
    print("\n  engine presets in the generated table:")
    for pid, items, n, tid, _bd in ps:
        print("    id %d  %2d items  target 0x%04X %s"
              % (pid, n, tid, "(any board)" if tid == 0 else ""))
    check("at least one preset is bound to each board",
          len({t for _i, _x, _n, t, _b in ps if t}) >= 2,
          "%d distinct bound targets" % len({t for _i, _x, _n, t, _b in ps if t}))

    this_target = None
    m = re.search(r"hc_pin_target_id\s*=\s*(0x[0-9A-Fa-f]+)",
                  (SHARED / "generated/hc_pin_desc_bosch_me711.c").read_text(
                      errors="replace"))
    this_target = int(m.group(1), 16)
    print("\n  the LINKED descriptor in this image is 0x%04X\n" % this_target)

    # ------------------------------------------------- the foreign preset
    for pid, _items, n, tid, _bd in ps:
        if tid == 0 or tid == this_target or n == 0:
            continue
        r = boot()
        before = snapshot(r)
        rc = apply_preset(r, pid, n)
        after = snapshot(r)
        check("preset %d (target 0x%04X) is REFUSED on this board" % (pid, tid),
              rc == 2, "return code %d, and 2 is 'wrong board'" % rc)
        check("  ...and the refusal wrote NOTHING", before == after,
              "%d sampled bytes unchanged - a half-applied preset would be "
              "worse than none" % len(before))

    # WHICH PRESET IS THE BOARD DEFAULT, read out of the generated table.
    # The fifth field of each row is `board_default`; taking it from the source
    # rather than naming an id here means a new board default cannot silently
    # fall outside the rule below.
    board_default_id = next((i for i, _x, _n, _t, bd in ps if bd), None)

    # ------------------------------------------------- the native preset
    for pid, _items, n, tid, _bd in ps:
        if tid != this_target or n == 0:
            continue
        r = boot()
        before = snapshot(r)
        rc = apply_preset(r, pid, n)
        after = snapshot(r)
        # V86: hc_preset_apply_engine() VALIDATES THE WHOLE RESULT FIRST, so
        # a native preset is either applied (0) or refused on its CONTENT (4,
        # HC_PRESET_PAGE_INVALID) - never as another board's (2). Preset 2,
        # the Porsche V8 donor, is the documented content refusal
        # (me711_preset_validates_proof: CFG_TDC_CYL, M48 firing order), and
        # a content refusal must change NOTHING.
        check("preset %d (target 0x%04X) is NOT refused as another board's"
              % (pid, tid), rc in (0, 4), "return code %d" % rc)
        if rc == 4:
            check("  ...its content refusal (PAGE_INVALID) wrote NOTHING",
                  before == after, "the V86 transaction rolled back")
            continue
        # THE BOARD DEFAULT IS THE ONE PRESET THAT MUST BE A NO-OP HERE.
        #
        # seed_universal_defaults() applies it to every fresh page, so applying
        # it again to a freshly booted page changes nothing BY CONSTRUCTION.
        # That is the definition of a board default, not a defective preset,
        # and requiring it to move a byte would be requiring the seed not to
        # work. Every OTHER preset still has to change something.
        if pid == board_default_id:
            check("  ...and re-applying the BOARD DEFAULT is a no-op",
                  before == after,
                  "it is what the fresh page was already seeded from")
        else:
            check("  ...and it actually changed the configuration",
                  before != after,
                  "a preset that applies cleanly but changes nothing is not a "
                  "preset")

    # ------------------------------------------- an id nobody defined
    r = boot()
    before = snapshot(r)
    rc = r.callb("hc_preset_apply_engine", 200, 0)
    check("an undefined preset id is refused", rc == 1,
          "return code %d, and 1 is 'no such preset'" % rc)
    check("  ...and it wrote nothing either", snapshot(r) == before, "")

    # ------------------------------- the descriptors really do disagree
    #
    # If both boards agreed about every pin there would be nothing to protect,
    # and this whole mechanism would be ceremony.
    me711 = HW.DESCRIPTORS["BOSCH_ME711"]()
    me75 = HW.DESCRIPTORS["ME75_4B0906018DC"]()
    a = {p.number: p.capabilities for p in me711.pins}
    b = {p.number: p.capabilities for p in me75.pins}
    differ = [n for n in a if n in b and a[n] != b[n]]
    both = [n for n in a if n in b and a[n] and b[n]]
    check("the two descriptors disagree about most of the connector",
          len(differ) > 60, "%d of 121 pins have different capabilities"
          % len(differ))

    # and a concrete one, so the number above is not the whole argument
    conc = [n for n in both if a[n] != b[n]][:4]
    for n in conc:
        print("      pin %3d  ME7.1.1 caps 0x%04X   ME7.5 caps 0x%04X"
              % (n, a[n], b[n]))
    check("and at least one pin is capable on BOTH boards but differently",
          any(a[n] and b[n] and a[n] != b[n] for n in both),
          "which is the dangerous case: a plausible pin number that means "
          "something else")

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("TARGET ISOLATION FAILED - a configuration for one board can "
              "reach another.")
        return 1
    print("TARGET ISOLATION PASSES - a foreign preset is refused cleanly, and\n"
          "the two boards genuinely disagree about what a pin number means.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
