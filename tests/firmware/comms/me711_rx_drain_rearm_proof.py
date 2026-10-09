#!/usr/bin/env python3
r"""
me711_rx_drain_rearm_proof.py - the K-line drain tick (CC7, compare mode 0 on
T0) must always re-arm into the FUTURE, however late its interrupt ran.

    py tests\firmware\comms\me711_rx_drain_rearm_proof.py

THE HAZARD. hc_cc7_isr() advances CC7 by HC_RXTICK_US and catches up only
when the new value is BEHIND T0 by more than half a timer period:

    if ((unsigned int)(CC7 - T0) > 0x8000u) CC7 = T0 + tick;

A compare event fires when the timer is INCREMENTED TO the compare value
(C167CR UM V3.1 ch. 15, compare modes: "within 8 CPU clock cycles after the
allocated timer is incremented to the compare value"). If the handler ran
exactly one tick period late, the new CC7 EQUALS T0: the difference is 0, the
catch-up does not trigger, T0 has already passed that value, and the next
drain is one full T0 wrap later - 65536 ticks = 52.4 ms. At 115200 baud that
is ~600 received bytes the 1-byte ASC0 buffer cannot hold. The stress rig
measured exactly 52429.6 us between drains under engine + K-line load.
hcdeadline711.c's arm_next() handles the same case with `<= 0`.

WHAT THIS RUNS. The LINKED hc_cc7_isr through a real interrupt frame and
RETI, with T0 stopped at the old CC7 + d for every delay d in 0..250 ticks (a late
handler, behind a crank ISR or a CC25 dispatch). After it returns, CC7 must be
strictly ahead of T0: 1 <= (CC7 - T0) <= 0x7FFF.

VACUITY CONTROL: d = 0 (on time) must give exactly one tick period ahead.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402

import me711_image as PI            # noqa: E402
import me711_trigger_test as P      # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
T0, CC7, T01CON, PSW, SP = 0xFE50, 0xFE8E, 0xFF50, 0xFF10, 0xFE12
FAILS = 0


def check(name, ok, detail=""):
    global FAILS
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))
    FAILS += not ok


def tick_ticks():
    h = (ROOT / "firmware/targets/me711/hctarget.h").read_text()
    us = int(re.search(r"#define\s+HC_RXTICK_US\s+(\d+)", h).group(1))
    tpms = int(re.search(r"#define\s+TGT_TICKS_PER_MS_X10\s+(\d+)", h).group(1))
    return us * tpms // 10000


def run_isr(c, cc7, t0):
    c.m.w16(T01CON, c.m.r16(T01CON) & ~0x0040)     # T0 stopped
    c.m.w16(T0, t0)
    c.m.w16(CC7, cc7)
    a = P.sym("hc_cc7_isr")
    c.m.w16(c.c.cp(), c.stack_top)
    sp = 0xF700
    for w in (0x0800, a >> 16, 0xFFFE):            # PSW, CSP, IP for RETI
        sp -= 2
        c.m.w16(sp, w)
    c.m.sfr[SP] = sp
    c.m.sfr[PSW] = (12 << 12) | 0x0800            # inside a level-12 ISR
    c.c.csp, c.c.ip = a >> 16, a & 0xFFFF
    for _ in range(2000):
        if c.c.ip == 0xFFFE:
            return c.m.r16(CC7)
        c.c.step()
    raise SystemExit("hc_cc7_isr did not return")


def main() -> int:
    print("=== CC7 drain tick always re-arms into the future ===")
    print("  image   %s" % PI.image().name)
    print("  sha256  %s\n" % PI.sha256())
    step = tick_ticks()
    c = P.Call()
    bad = []
    for base in (0x0000, 0x7FF0, 0xFFC0):
        for d in range(0, 251):
            t0 = (base + d) & 0xFFFF                 # matched at base, ran d late
            new = run_isr(c, base, t0)
            ahead = (new - t0) & 0xFFFF
            if not (1 <= ahead <= 0x7FFF):
                bad.append((hex(base), d, ahead))
    check("re-armed CC7 is strictly ahead of T0 for every delay 0..250",
          not bad, "%d stranded, e.g. %s (0 = next drain after a full T0 wrap)"
          % (len(bad), bad[:3]))
    new = run_isr(c, 0x1000, 0x1000)
    check("VACUITY: an on-time drain re-arms one period ahead",
          ((new - 0x1000) & 0xFFFF) == step,
          "CC7 - T0 = %d (tick %d)" % ((new - 0x1000) & 0xFFFF, step))
    print("\n%s" % ("DRAIN RE-ARM IS SAFE" if not FAILS
                    else "DRAIN CAN STALL FOR A FULL T0 WRAP"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
