#!/usr/bin/env python3
r"""
me711_preset_validates_proof.py - a factory preset a tuner can select must be
one hc_validate() ACCEPTS, or it must say why not.

    py tests\firmware\config\me711_preset_validates_proof.py

WHY. `me711_preset_routing_proof` checks that every pin a preset names is
electrically capable on that preset's own board. It says nothing about whether
the resulting PAGE is one the firmware will accept - and a page `hc_validate()`
refuses **can never arm an output, however it is armed**.

**THE VAG 1.8T PRESET - THE FIRST ENGINE THIS ECU WILL RUN - WAS REFUSED FROM
V63 TO V70 AND NOTHING SAID SO.** It declared `syncMode = SYNC_CAM1_CYCLE`
with `camRefs` at 0, which is a named and deliberate gap: `camRefX10` is the
engine angle at which this engine's cam edge falls, no cam edge has ever
reached this ECU, and §4 forbids inventing the number. V63 then made
`hc_validate()` ask the runtime's question in the runtime's terms - a cam cycle
mode needs `camEnable` and an ODD, non-zero `CFG_U_CAM_REFS` (§12M/5) - and the
preset became unappliable. Measured on V70: `rc = 0x0010`, first bad offset
2542 = `CFG_U_CAM_REFS`.

The preset's own gap note had predicted it, in those words: *"The fix belongs
in the validator and is recorded for the release after V62."* The fix landed;
the preset was not revisited.

WHAT THIS GATE ASSERTS

  1. every engine preset for THIS board either validates clean, or is on the
     REFUSED list below with the field it is refused on;
  2. that list is exactly right - a preset that starts validating must be
     REMOVED from it, and a preset that stops validating must be added or
     fixed.

So it fires in both directions, which is the point: a preset silently becoming
unappliable is what happened, and a preset silently becoming appliable would
mean a documented gap had been filled without the note being updated.

**REFUSED IS NOT ALWAYS WRONG.** Preset 2 is the Porsche V8 DONOR description,
and §12K/2 records why it cannot be applied: it legitimately declares eight
cylinders and legitimately CANNOT declare `tdcCylDegX10`, because the M48
firing order is in no document in this repository. *"Two cylinders at the same
angle is a configuration in which one of them never fires"*, so the refusal is
the validator working. What would be wrong is that refusal being a surprise.

NOT PHYSICALLY VERIFIED: this runs `hc_cfg_init()`, `hc_preset_apply_engine_active()`
and `hc_validate()` out of the linked image in a simulator. No page has been
written to an ECU.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths as HCP  # noqa: E402

pass  # (bootstrap above)

import me711_config_state_test as T       # noqa: E402  the rig and VAL
import me711_image as PI                  # noqa: E402

SHARED = ROOT / "firmware"
# hc_val_first_bad_offset is resolved from THIS image's map on every run.
# It was a typed constant, 0xFD84, and the variable moved away from it before
# V76 - so the refusal field this gate printed was whatever word happened to
# sit there (0 -> "CFG_VERSION"), and the check failed on a gate defect while
# the firmware's own report was right. V77 moved it again, into the XRAM.
FIRST_BAD_SYM = "hc_val_first_bad_offset"

# Presets this board offers, and what each must do. A preset that is REFUSED
# names the field it is refused on, so the entry is a claim about WHY and not
# just a licence to fail.
EXPECT = {
    # (2: the Porsche V8 donor - removed 2026-10-31, owner)
    3: ("VAG_18T_ME711 - VAG 1.8T DBW, THE FIRST ENGINE", None, ""),
    4: ("BOSCH_ME711_BOARD - the board default", None, ""),
    8: ("AUDI_27T_ME711 - Audi 2.7T biturbo V6 (Porsche board)", None, ""),
}
# 2026-10-24: the 2.7T image carries ITS presets only (hc_presets.c
# HC_PRESET_C4); HANICORE_BOARD=vag_me71_c4 asks this gate about them.
import hc_board  # noqa: E402
if hc_board.IS_C4:
    EXPECT = {
        5: ("VAG_ME71_C4_BOARD - the board default", None, ""),
        6: ("AUDI_27T_ME71 - Audi 2.7T biturbo V6", None, ""),
        9: ("VAG_18T_ME71_C4 - VAG 1.8T DBW (2.7T board)", None, ""),
    }
# The ME7.5 DC builds on the C4 branch but is ITS OWN target (descriptor
# 0x03C2): its native preset is the 1.8T AWT, and the 2.7T's two are another
# board's - refused by hc_preset_apply_engine() (rc 2), not validated here.
if hc_board.IS_DC:
    EXPECT = {
        1: ("VAG_18T_ME75_AWT - VAG 1.8T DBW (ME7.5 board)", None, ""),
        7: ("ME75_DC_BOARD - the board default", None, ""),
    }

CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print("  [%s] %-52s %s" % ("PASS" if ok else "FAIL", name, detail))


def offset_names():
    out = {}
    for f in ("hc_config_generated.h", "hcconfig.h"):
        txt = HCP.find(f).read_text(errors="replace")
        for m in re.finditer(r"#define\s+(CFG_[A-Z0-9_]+)\s+(\d+)u?", txt):
            out.setdefault(int(m.group(2)), m.group(1))
    return out


def main() -> int:
    print("=== every preset a tuner can pick is one the firmware accepts ===\n")
    print("  image  %s\n" % PI.STEM)

    names = offset_names()
    print("  %-4s %-44s %-9s %s" % ("id", "preset", "verdict", "first bad"))
    got = {}
    for pid in sorted(EXPECT):
        r = T.boot()
        r("hc_preset_apply_engine_active", pid)
        rc = r("hc_validate", T.VAL["HC_VAL_SRC_ACTIVE"]) & 0xFFFF
        off = r.g16(FIRST_BAD_SYM)
        got[pid] = (rc, off)
        print("  %-4d %-44s %-9s %s"
              % (pid, EXPECT[pid][0][:44], "REFUSED" if rc else "accepted",
                 names.get(off, "-") if rc else "-"))

    print()
    for pid, (label, want_bad, why) in sorted(EXPECT.items()):
        rc, off = got[pid]
        field = names.get(off, "0x%04X" % off)
        if want_bad is None:
            check("preset %d is APPLIABLE" % pid, rc == 0,
                  "%s - refused 0x%04X on %s" % (label[:40], rc, field)
                  if rc else label[:60])
        else:
            check("preset %d is refused, on the field it should be" % pid,
                  rc != 0 and field == want_bad,
                  "expected %s, got %s (rc 0x%04X). %s"
                  % (want_bad, field if rc else "ACCEPTED", rc, why))

    # ===================== THE CONTROL ON THE CONTROL =====================
    #
    # Every row above would be satisfied by a rig whose preset apply did
    # nothing at all: the board default validates clean on a fresh page even
    # if no preset were applied, and a preset that writes nothing cannot be
    # refused. This says the apply DOES something - preset 2 and the board
    # default must reach DIFFERENT verdicts, which they can only do if the
    # values actually landed.
    if hc_board.IS_DC:
        r = T.boot()
        before = bytes(r.active(i) for i in range(4096))
        rc = r("hc_preset_apply_engine_active", 1) & 0xFF
        after = bytes(r.active(i) for i in range(4096))
        other = r("hc_preset_apply_engine_active", 6) & 0xFF
        check("the preset apply actually changes the page",
              rc == 0 and before != after,
              "%d bytes changed (apply rc %d)"
              % (sum(a != b for a, b in zip(before, after)), rc))
        # since 2026-10-31 the DC image does not even carry it (hc_presets.c
        # HC_PRESET_DC): 1 'no such preset', stronger than 2 'wrong board'
        check("CONTROL: the 2.7T preset is refused as another board's",
              other in (1, 2), "apply(6) rc %d (1 = not in this image, "
              "2 = wrong board)" % other)
    elif hc_board.IS_C4:
        # no refused preset to compare on this board: read the page itself
        r = T.boot()
        before = r.active(T.O["CFG_CYLINDERS"])
        rc = r("hc_preset_apply_engine_active", 6) & 0xFF
        after = r.active(T.O["CFG_CYLINDERS"])
        other = r("hc_preset_apply_engine_active", 3) & 0xFF
        check("the preset apply actually changes the page",
              rc == 0 and after == 6 and before != 6,
              "cylinders %d -> %d (apply rc %d)" % (before, after, rc))
        check("CONTROL: a Porsche-board preset is not in this image",
              other != 0, "apply(3) rc %d" % other)
    else:
        # 2026-10-31: the V8 donor (the refused preset this compared) is
        # gone - read the page itself, as on the C4
        r = T.boot()
        before = r.active(T.O["CFG_CYLINDERS"])
        rc = r("hc_preset_apply_engine_active", 8) & 0xFF
        after = r.active(T.O["CFG_CYLINDERS"])
        other = r("hc_preset_apply_engine_active", 6) & 0xFF
        check("the preset apply actually changes the page",
              rc == 0 and after == 6 and before != 6,
              "cylinders %d -> %d (apply rc %d)" % (before, after, rc))
        check("CONTROL: a 2.7T-board preset is not in this image",
              other != 0, "apply(6) rc %d" % other)

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("PRESET VALIDATION FAILS - a preset a tuner can select produces "
              "a page hc_validate() refuses, and a refused page can never arm "
              "an output. Either fix the preset or record the refusal here "
              "with the field and the reason.")
        return 1
    print("PRESET VALIDATION PASSES - every selectable preset either applies "
          "clean or is refused on a field this file names and explains.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
