#!/usr/bin/env python3
r"""
me75_dc_monitor_line_proof.py - nothing but the monitor responder may touch
P2.5 (the ME7.5 DC's 68HC05 monitor line): EXECUTE the linked image.

    set HANICORE_BOARD=vag_me75_dc
    py tests\firmware\asic\me75_dc_monitor_line_proof.py
    py tests\firmware\asic\me75_dc_monitor_line_proof.py --control <old.bin>

THE DEFECT (bench 4B0906018DC, 2026-11-04). After a short power-off (page
restored from battery SRAM) the boot reached its output init at 59 ms, inside
the first monitor answer (P2.5 driven LOW 59..64 ms). hc_deadline_cancel()
released "every coil" with the Porsche's masks - P2 |= 0xFF, DP2 &= ~0xFF -
and so the monitor line: the monitor raised NMI and reset the CPU every
~116 ms, for ever. A cold boot reaches that code between an answer and a
question, so it ran. c167sim never showed it: in the simulator the line is
released at that moment too.

THE CHECK. At the start of boot stage 6 (hc_hal_init .. hcts_rx_learn) the
gate puts P2.5 where an answer has it - output, latch LOW - and at the end
of stage 6 requires both unchanged. The monitor responder does not change
P2.5 inside that window in this model (its next TX slot is later), so any
change is the firmware's.

WHY IT CANNOT PASS VACUOUSLY: --control runs the same check on an image
built before the fix (release 85146906 / 2F247AE9) and must see P2.5
released; stage 6 must actually be entered and left.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

os.environ.setdefault("HANICORE_BOARD", "vag_me75_dc")
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402
import me711_boot_test as B  # noqa: E402

P2, DP2, BIT = 0xFFC0, 0xFFC2, 0x0020
BOOT_TIMERS, BOOT_PROBE = 6, 7            # hctarget.h BOOT_*


def run(img: Path):
    h = B.Harness(img, echo=True)
    m = h.mem
    rd = lambda a: m.r8(a) | (m.r8(a + 1) << 8)          # noqa: E731
    wr = lambda a, v: (m.w8(a, v & 0xFF), m.w8(a + 1, v >> 8))  # noqa: E731
    for _ in range(4000):                 # to stage 6 (~400k steps)
        h.run(200)
        if h.sym_u16("boot_stage") >= BOOT_TIMERS:
            break
    if h.sym_u16("boot_stage") != BOOT_TIMERS:
        return None, "stage 6 never entered (stage %d)" % h.sym_u16("boot_stage")
    wr(DP2, rd(DP2) | BIT)                # an answer in progress:
    wr(P2, rd(P2) & ~BIT)                 # driven, LOW
    for _ in range(2000):
        h.run(50)
        if h.sym_u16("boot_stage") != BOOT_TIMERS:
            break
    if h.sym_u16("boot_stage") < BOOT_PROBE:
        return None, "stage 6 never left (stage %d)" % h.sym_u16("boot_stage")
    d, p = rd(DP2) & BIT, rd(P2) & BIT
    return (d != 0 and p == 0), "after stage 6: DP2.5=%d P2.5=%d" % (d != 0, p != 0)


def main() -> int:
    ctl = "--control" in sys.argv
    img = Path(sys.argv[sys.argv.index("--control") + 1]) if ctl else B.IMG
    if not img.exists():
        print("SKIP: %s not built" % img.name)
        return 0
    print("=== ME7.5 DC: P2.5 belongs to the monitor responder ===")
    print("  image  %s%s\n" % (img.name, "  (CONTROL: must fail)" if ctl else ""))
    ok, detail = run(img)
    if ok is None:
        print("  [FAIL] %s" % detail)
        return 1
    if ctl:
        print("  [%s] the control releases the monitor line          %s"
              % ("PASS" if not ok else "FAIL", detail))
        return 0 if not ok else 1
    print("  [%s] stage 6 leaves an answer on P2.5 untouched       %s"
          % ("PASS" if ok else "FAIL", detail))
    print("\nME75 DC MONITOR LINE PROOF %s" % ("PASSES" if ok else "FAILS"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
