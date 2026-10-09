#!/usr/bin/env python3
r"""
me711_crank_period_atomic_proof.py - trg_service() must never compute the
engine speed from a TORN trg_crank_period.

    py tests\firmware\trigger\me711_crank_period_atomic_proof.py

THE HAZARD. trg_crank_period is 32 bits on a 16-bit core. The crank ISR
(ILVL 12) writes it once per revolution, at the gap; trg_service() runs in
the main loop and computes trg_rpm = 75000000 / trg_crank_period. If the ISR
lands between the task's two word loads, the task divides a value that was
never a period: low word of one revolution, high word of the next. That only
differs from either real value when the high word changes - a period that
crosses 65536 T1 ticks (1144 rpm on a 60-2, and every multiple below it while
cranking) - and then the result is wild: 0x1_0005 -> 0x0_FFF0 read as
0x0_0005 is trg_rpm 57792 for one pass, which the rev limiter, the RPM_ZERO
gates and the protections all read.

WHAT THIS RUNS. The LINKED trg_service() in c167sim, single-stepped. At every
instruction where a level-12 request would be ACCEPTED (PSW.ILVL < 12), the
crank ISR's store is simulated - both words, as the ISR writes them - once
per run, for every instruction index in turn, in both boundary directions.
trg_rpm afterwards must be the speed of the old period or of the new one.

VACUITY CONTROL. The same sweep with the ILVL test removed (a store allowed
even inside a raised section) must produce a torn value, or the injection
cannot reach the load pair and the gate proves nothing.

NOT PHYSICALLY VERIFIED: the race window is two instructions per revolution
crossing; this asserts what the compiled code does when the ISR lands there.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402

import me711_image as PI            # noqa: E402
import me711_trigger_test as P      # noqa: E402

FAILS = 0


def check(name, ok, detail=""):
    global FAILS
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))
    FAILS += not ok


def rpm_of(period):
    return (75000000 // period) & 0xFFFF


def fixture():
    c = P.Call()
    c.call("trg_init")
    c.call("trg_service")            # settle geometry / stall bookkeeping
    return c


def run_once(c, old, new, inject_at, honour_ilvl=True):
    """trg_service() with the ISR store injected before instruction
    `inject_at` (if accepted there). Returns (trg_rpm, injected, steps)."""
    per = P.sym("trg_crank_period") & 0xFFFF
    c.m.w8(P.sym("trg_state") & 0xFFFF, 3)
    c.m.w16(per, old & 0xFFFF)
    c.m.w16(per + 2, old >> 16)
    # the same tooth count as the last call -> no stall, no restart
    a = P.sym("trg_service")
    c.m.w16(c.c.cp(), c.stack_top)
    sp = 0xF700
    for w in (a >> 16, 0xFFFE):
        sp -= 2
        c.m.w16(sp, w)
    c.m.sfr[0xFE12] = sp
    c.m.sfr[0xFF10] = 0x0800          # task level, IEN
    c.c.csp, c.c.ip = a >> 16, a & 0xFFFF
    injected = False
    for k in range(20000):
        if c.c.ip == 0xFFFE:
            return c.m.r16(P.sym("trg_rpm") & 0xFFFF), injected, k
        if k == inject_at and not injected:
            if not honour_ilvl or (c.m.sfr.get(0xFF10, 0) >> 12) < 12:
                c.m.w16(per, new & 0xFFFF)          # the ISR: low word
                c.m.w16(per + 2, new >> 16)         # then high word
                injected = True
        c.c.step()
    raise SystemExit("trg_service did not return")


def sweep(old, new, honour_ilvl):
    c = fixture()
    _rpm, _inj, n = run_once(c, old, old, -1)
    good = {rpm_of(old), rpm_of(new)}
    torn = []
    for k in range(n + 1):
        c = fixture()
        rpm, injected, _ = run_once(c, old, new, k, honour_ilvl)
        if injected and rpm not in good:
            torn.append((k, rpm))
    return n, good, torn


def main() -> int:
    print("=== trg_crank_period: no torn speed in trg_service() ===")
    print("  image   %s" % PI.image().name)
    print("  sha256  %s\n" % PI.sha256())
    for old, new in ((0x00010005, 0x0000FFF0), (0x0000FFF0, 0x00010005)):
        n, good, torn = sweep(old, new, True)
        check("0x%05X -> 0x%05X at every accepting instruction" % (old, new),
              not torn, "%d instructions; allowed rpm %s; torn %s"
              % (n, sorted(good), torn[:4]))
    n, good, torn = sweep(0x00010005, 0x0000FFF0, False)
    check("VACUITY: an unmasked injection DOES reach the load pair",
          bool(torn), "torn %s" % torn[:2])
    print("\n%s" % ("CRANK PERIOD READ IS ATOMIC" if not FAILS
                    else "CRANK PERIOD CAN BE TORN"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
