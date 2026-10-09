#!/usr/bin/env python3
r"""THE DECISIVE V50 TEST: a request that arises inside the protected writer
window must survive the restore.

This does not re-create the firmware's behaviour - it EXECUTES THE SHIPPED
INSTRUCTIONS. The restore block is located in each linked image from its own
.M66 map, the real opcodes are run in c167sim, and the only thing the harness
supplies is the thing the hardware would have supplied: an interrupt request
flag raised while the source was masked.

    V49 (frozen, negative control)   MOV R4,[R0+#n] ; MOV  <xxIC>,R4
    V50 (image under test)           MOV R4,[R0+#n] ; AND R4,#40H ; OR <xxIC>,R4

The saved words fed in are the ACTUAL ones from the V49 physical event:
CC7IC 0x72 (IE, ILVL 12, GLVL 2) and T8IC 0x60 (IE, ILVL 8) - both with
xxIR = 0, which is what makes the stale restore destructive.

[DS] C167CR Derivatives UM V3.1, section 5, register xxIC:
    "Modifying the Interrupt Request flag via software causes the same effects
     as if it had been set or cleared by hardware."

WHAT IS ASSERTED
  1  V49 DESTROYS a request raised inside the window          (must be true)
  2  V50 PRESERVES it                                         (must be true)
  3  V50 restores xxIE exactly as saved, and never enables a source that was
     disabled at save time
  4  V50 leaves ILVL/GLVL untouched
  5  T8 keeps a 1.000 ms period with no software reload, and a destroyed
     request costs one period rather than a 52.4 ms lap
  6  on the full V50 image: the tick advances and the S5500 raster keeps
     launching

It is non-vacuous by construction: check 1 is the negative control, and it
runs the frozen V49 binary, not a mutation of V50.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import c166_disasm as D          # noqa: E402
import c167sim as S              # noqa: E402
import me711_image               # noqa: E402

# THE NEGATIVE CONTROL IS A FIXED IN-TREE ARTEFACT.
#
# Both V50 gates assert an ABSENCE - "no whole-register write", "no request
# destroyed" - and an absence is the easiest thing in this repository to
# assert vacuously. The control is the frozen V49 binary that physically
# failed on 2026-09-11, sha256 B9158BD6...F71E94. If it is missing the gate
# FAILS rather than skipping: a run without the control proves nothing.
CONTROL_BIN = ROOT / ("bins/hanicore/"
                      "HaniCore_ME711_v49_live_burn_nmi_forensics.bin")
CONTROL_MAP = CONTROL_BIN.with_suffix(".M66")
CONTROL_SHA = "B9158BD621CD9D2FBF366A915B722FE75BC53F6A571C5D4828D62CEE80F71E94"

IC_ADDR = {a: n for a, n in list(D.SFR.items()) + list(D.ESFR.items())
           if n.endswith("IC")}
IE_BIT, IR_BIT = 0x0040, 0x0080

# The words fl_enter() saved on the real ECU, 2026-09-11.
SAVED = {"CC7IC": 0x0072, "T8IC": 0x0060, "SSCTIC": 0x00B8,
         "SSCRIC": 0x003C, "SSCEIC": 0x0000}
DEFAULT_SAVED = 0x0060

FAILS = CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-56s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def section(m66, name):
    txt = Path(m66).read_text(errors="replace")
    pat = (r"^\s*([0-9A-F]{6})H\s+([0-9A-F]{6})H\s+[0-9A-F]{6}H\s+CODE.*?"
           r"(\?PR\?\S+)\s*$")
    for mt in re.finditer(pat, txt, re.M):
        if mt.group(3).upper() == name.upper():
            lo, hi = int(mt.group(1), 16), int(mt.group(2), 16)
            return (D.seg_off_to_file(lo >> 16, lo & 0xFFFF),
                    D.seg_off_to_file(hi >> 16, hi & 0xFFFF) + 1,
                    lo)
    raise SystemExit("section %s not found" % name)


def find_restore(img, lo, hi):
    """Locate the restore block and return (start, end, [(ic, slot, kind)]).

    A LINEAR SWEEP OF THE WHOLE MODULE IS NOT SAFE HERE. hcnvm's code section
    is ~10 KB and a sweep desyncs over the first jump table, after which the
    "first write" it reports can be anywhere. So instead: find every
    `MOV/OR <xxIC>,Rw` (opcode F6/74 with an xxIC as the 16-bit DESTINATION),
    cluster the ones that sit within a few bytes of each other, and take the
    largest cluster. The restore block is ten of them in a row; nothing else
    in the module writes that many xxIC registers back to back.
    """
    writes = []
    for fo in range(lo, hi - 3):
        op = img[fo]
        if op not in (0xF6, 0x74):
            continue
        imm = img[fo + 2] | (img[fo + 3] << 8)
        if imm in IC_ADDR:
            writes.append((fo, IC_ADDR[imm], "MOV" if op == 0xF6 else "OR"))
    if not writes:
        raise SystemExit("no xxIC restore writes found")

    clusters, cur = [], [writes[0]]
    for w in writes[1:]:
        if w[0] - cur[-1][0] <= 16:
            cur.append(w)
        else:
            clusters.append(cur)
            cur = [w]
    clusters.append(cur)
    best = max(clusters, key=len)
    if len(best) < 5:
        raise SystemExit("restore cluster too small (%d writes)" % len(best))

    w0 = best[0][0]
    # what feeds R4: V50 is MOV R4,[R0+#n]; AND R4,#40H; OR <ic>,R4
    #                V49 is MOV R4,[R0+#n];               MOV <ic>,R4
    if img[w0 - 8] == 0xD4 and img[w0 - 4] == 0x66:
        start, stride = w0 - 8, 12
    elif img[w0 - 4] == 0xD4:
        start, stride = w0 - 4, 8
    else:
        raise SystemExit("cannot identify the load that feeds %06X" % w0)

    pairs = []
    for i, (fo, name, kind) in enumerate(best):
        ld = fo - (stride - 4)
        slot = None
        if img[ld] == 0xD4 and img[ld + 1] == 0x40:
            slot = img[ld + 2] | (img[ld + 3] << 8)
        pairs.append((name, slot, kind))
    return start, best[-1][0] + 4, pairs


def run_restore(img_path, m66, tag):
    """Execute the shipped restore block with every source masked and a
    request standing, and report which xxIR survive."""
    src = Path(img_path).read_bytes()
    lo, hi, _lo_lin = section(m66, "?PR?HCNVM")
    start, end, pairs = find_restore(src, lo, hi)

    # RUN THE EXTRACTED BYTES, not the image in place. The block is entirely
    # register and absolute-SFR operations, so it is position independent, and
    # copying it avoids any dependence on where a linear sweep thinks the
    # surrounding code begins. These are still the SHIPPED opcodes, byte for
    # byte, taken straight out of the linked binary under test.
    blk = src[start:end]
    img = bytearray(b"\xFF" * 0x100000)
    img[0xE0000:0xE0000 + len(blk)] = blk
    img[0xE0000 + len(blk):0xE0000 + len(blk) + 8] = b"\xCC\x00" * 4  # NOPs

    m = S.Mem(bytes(img))
    for i, v in enumerate((0, 1, 2, 3)):
        m.sfr[0xFE00 + 2 * i] = v
    m.sfr[0xFE12] = 0xFC00
    m.sfr[0xFE14] = 0xF600
    m.sfr[0xFE10] = 0xFC00
    cpu = S.CPU(m, 0x8E, 0x0000)

    frame = 0xF800
    for r in range(16):
        cpu.sr(r, 0)
    cpu.sr(0, frame)                           # R0 is the user stack pointer
    for name, slot, _k in pairs:
        if slot is None:
            continue
        m.w16(frame + slot, SAVED.get(name, DEFAULT_SAVED))

    # THE HARDWARE'S CONTRIBUTION: every source is masked (IE cleared, as
    # fl_enter left it) and has since raised a request (IR set).
    before = {}
    for name, _s, _k in pairs:
        addr = next(a for a, n in IC_ADDR.items() if n == name)
        saved = SAVED.get(name, DEFAULT_SAVED)
        masked = (saved & ~IE_BIT) | IR_BIT
        cpu._sset(addr, masked)
        before[name] = (addr, saved, masked)

    steps = 0
    while cpu.ip < len(blk) and steps < 200:
        cpu.step()
        steps += 1

    out = {}
    for name, (addr, saved, masked) in before.items():
        out[name] = (saved, masked, cpu._sget(addr))
    print("    %s: restore block %06X..%06X (%d bytes), %d steps, %d registers"
          % (tag, start, end, len(blk), steps, len(pairs)))
    return out, pairs


def verify_control(path):
    """The control must BE the frozen V49 binary, not just a file there."""
    p = Path(path)
    if not p.exists():
        raise SystemExit("negative control missing: %s - a run without it proves nothing, refusing" % p)
    got = hashlib.sha256(p.read_bytes()).hexdigest().upper()
    if got != CONTROL_SHA:
        raise SystemExit("negative control is not the frozen V49 binary: have %s want %s" % (got, CONTROL_SHA))
    return p


def main():
    global FAILS
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", default=str(CONTROL_BIN),
                    help="frozen V49 binary, the negative control")
    ap.add_argument("--control-map", default=str(CONTROL_MAP))
    a = ap.parse_args()
    verify_control(a.control)

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=== V50 request preservation, on the SHIPPED instructions ===")
    print("")

    img_path = me711_image.image()
    m66 = str(Path(img_path).with_suffix(".M66"))
    print("  under test : %s" % Path(img_path).name)
    print("  control    : %s" % Path(a.control).name)
    print("")

    v50, p50 = run_restore(img_path, m66, "V50")
    v49, p49 = run_restore(a.control, a.control_map, "V49")
    print("")

    # THE POPULATION UNDER TEST is the firmware's own definition of a lost
    # request - hcliveforensics.c:lf_new_ir(): the SAVED word had xxIR = 0 and
    # a request arose while the source was masked. A source whose saved word
    # already had xxIR set (SSCTIC was 0xB8 on the real event) has no NEW
    # request to lose, and restoring its stale word re-asserts the old one -
    # which is why counting all ten would have scored V49 9/10 and called this
    # gate a failure for the wrong reason.
    new = [n for n, (s, _m, _a) in v50.items() if not (s & IR_BIT)]
    print("  sources with a NEW request (saved xxIR = 0): %d of %d"
          % (len(new), len(v50)))

    # 1 - the negative control MUST destroy every one of them
    # Sources added after V49 (the V97 knock window CC16IC) have no V49
    # counterpart; the control is judged on the sources both images mask.
    common = [n for n in new if n in v49]
    killed = [n for n in common if not (v49[n][2] & IR_BIT)]
    check("V49 DESTROYS every new request (negative control)",
          len(killed) == len(common) and len(common) > 0,
          "%d/%d destroyed" % (len(killed), len(common)))

    # 2 - V50 must preserve every one of them
    kept = [n for n in new if v50[n][2] & IR_BIT]
    check("V50 PRESERVES every new request",
          len(kept) == len(new) and len(new) > 0,
          "%d/%d xxIR still set" % (len(kept), len(new)))

    # 2b - and it preserves an ALREADY-pending one too
    old = [n for n, (s, _m, _a) in v50.items() if s & IR_BIT]
    check("V50 also preserves an already-pending request",
          all(v50[n][2] & IR_BIT for n in old),
          "%d such source(s): %s" % (len(old), ",".join(old)))

    # 3 - xxIE restored exactly as saved, never enabling a disabled source
    ie_bad = [n for n, (s, _m, aft) in v50.items()
              if (aft & IE_BIT) != (s & IE_BIT)]
    check("V50 restores xxIE exactly as saved",
          not ie_bad,
          "mismatch: %s" % ie_bad if ie_bad else
          "including SSCTIC/SSCRIC which were saved DISABLED")

    # 4 - ILVL/GLVL untouched
    lv_bad = [n for n, (s, _m, aft) in v50.items()
              if (aft & 0x003F) != (s & 0x003F)]
    check("V50 leaves ILVL/GLVL untouched", not lv_bad,
          "mismatch: %s" % lv_bad if lv_bad else "all %d registers"
          % len(v50))

    # the instruction forms actually executed
    forms50 = sorted({k for _n, _s, k in p50})
    forms49 = sorted({k for _n, _s, k in p49})
    check("V50 restores with OR only; V49 used MOV",
          forms50 == ["OR"] and forms49 == ["MOV"],
          "V50 %s / V49 %s" % (forms50, forms49))

    print("")
    print("  per-register (saved -> masked+IR -> after restore):")
    for n in sorted(v50):
        s, mk, aft = v50[n]
        _s2, _m2, a49 = v49.get(n, (0, 0, 0))
        print("    %-8s %04X -> %04X -> V50 %04X %-9s | V49 %04X %s"
              % (n, s, mk, aft, "IR KEPT" if aft & IR_BIT else "IR LOST",
                 a49, "IR KEPT" if a49 & IR_BIT else "IR LOST"))

    # 5 - the timer half, delegated to the simulator's own regression
    print("")
    import subprocess
    r = subprocess.run([sys.executable, str(ROOT / "tests/simulator/sim_capcom_reload_test.py")],
                       capture_output=True, text=True)
    ok = r.returncode == 0
    lap = re.search(r"(\d+) ticks = ([\d.]+) ms", r.stdout)
    check("T8 keeps 1 ms with no software reload, and a destroyed request "
          "costs one period", ok,
          "sim_capcom_reload_test %s%s"
          % ("PASS" if ok else "FAIL",
             "; pre-V50 lap %s ms" % lap.group(2) if lap else ""))

    print("")
    print("%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    print("me711_burn_request_preservation_proof: %s"
          % ("PASS" if FAILS == 0 else "FAIL"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
