r"""
sim_compare_toggle_test.py - CAPCOM COMPARE MODE 1 toggles its port pin.

    py tests\simulator\sim_compare_toggle_test.py

WHY (2026-10-11). The tacho output (cavity 37, hcroutes711.c) runs CC13 in
compare mode 1 (CCMOD 101), in which the hardware toggles P2.13 on every
match. `c167sim` raised the request and left the pin alone, so a gate could
not see the waveform at all - "no tacho" would have looked like a firmware
defect, the simulator-gap class the project rules list. Modelled: CC13 is a
CAPCOM channel (CCM3 nibble 1, CC13 at 0xFE9A, CC13IC at 0xFF92), mode 5
toggles P2.n on each match, also while the previous request still stands;
modes 4 (compare mode 0) and 6 leave the pin alone.

Checks (SFRs poked directly, no image):
  1. mode 5 on T1: one toggle of P2.13 per match, logged in cc_toggles;
  2. a second match with the request still standing toggles again;
  3. mode 4: the request rises, the pin does not move;
  4. other P2 bits are untouched by a toggle.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402

import c167sim as S                       # noqa: E402

FAILS = 0
P2, T1, T1CON_RUN = 0xFFC0, 0xFE52, None


def check(name, ok, detail=""):
    global FAILS
    FAILS += not ok
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))


def rig(mode):
    m = S.Mem(bytes(0x100000))
    c = S.CPU(m, 0, 0)
    t1addr, t1con, runbit = S.TIMERS["T1"]
    c._sset(t1con, c._sget(t1con) | runbit)       # T1 running
    reg, shift = c.CCM_OF[13]
    c._sset(reg, (c._sget(reg) & ~(0xF << shift)) | ((0x08 | mode) << shift))
    c._sset(P2, 0x2001)                           # P2.13 high, P2.0 high
    c._sset(t1addr, 100)
    return c, t1addr


def run_to(c, t1addr, value):
    while c._sget(t1addr) != value:
        c.tick_timers()


def main() -> int:
    print("=== c167sim: CAPCOM compare mode 1 drives the pin ===")
    c, t1 = rig(5)
    ccx, ccic, _ = S.CC_CHAN[13]
    c._sset(ccx, 120)
    run_to(c, t1, 121)
    check("1 mode 5: P2.13 toggled once at the match, logged",
          (c._sget(P2) & 0x2000) == 0 and len(c.cc_toggles) == 1
          and c.cc_toggles[0][0] == 13, "P2 0x%04X toggles %s" % (c._sget(P2), c.cc_toggles))
    c._sset(ccx, 140)                              # request still standing
    run_to(c, t1, 141)
    check("2 a second match toggles again with the request standing",
          (c._sget(P2) & 0x2000) != 0 and len(c.cc_toggles) == 2
          and (c._sget(ccic) & 0x80), "P2 0x%04X" % c._sget(P2))
    check("4 other P2 bits untouched", (c._sget(P2) & 0x0001) == 1)
    c, t1 = rig(4)
    c._sset(ccx, 120)
    run_to(c, t1, 121)
    check("3 mode 4: request raised, pin unchanged",
          (c._sget(ccic) & 0x80) and (c._sget(P2) & 0x2000) and not c.cc_toggles)
    print("\nPASS" if not FAILS else "\n%d FAIL" % FAILS)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
