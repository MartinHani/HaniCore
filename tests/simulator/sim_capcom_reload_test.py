#!/usr/bin/env python3
r"""sim_capcom_reload_test.py - does c167sim reload a CAPCOM timer from TxREL?

    py tests\simulator\sim_capcom_reload_test.py

WHY THIS EXISTS. [DS] C167CR Derivatives User's Manual V3.1 (2000-03), section
15, The Capture/Compare Units - the chapter that names T0R, T1R, T7R and T8R:

    "When a timer overflows from FFFFH to 0000H it is reloaded with the value
     stored in its respective reload register TxREL."

Unconditional; the CAPCOM timers have no reload-enable bit. c167sim used to
set the timer to 0 on overflow and never read TxREL at all.

That was harmless right up until it was not. Every HaniCore build to V49
reloaded T8 in software inside hc_tick_isr(), so TxREL was 0 and "wrap to
zero" happened to be right. V50 removes that software reload - it is exactly
what made one lost T8 request cost 51.4 ms instead of 1 ms on the real ECU -
and relies on the hardware reload instead. Against the unfixed model, V50's
1 ms tick would have been simulated as a 52.4 ms one and every timing gate
would have reported a phantom regression in firmware that is correct.

That would have been the SIXTH c167sim defect in this project to present as a
firmware bug. This file is the regression that stops it being the seventh.

EVERY CHECK HERE FAILS AGAINST THE PRE-V50 MODEL except the TxREL = 0 case,
which is the backward-compatibility check and must keep passing.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import c167sim as S                       # noqa: E402

FAILS = 0
CHECKS = 0

T8, T8REL, T78CON, T8IC = 0xF052, 0xF056, 0xFF20, 0xF17C
T7, T7REL = 0xF050, 0xF054
T0, T0REL, T01CON, T0IC = 0xFE50, 0xFE54, 0xFF50, 0xFF9C

TICK_RELOAD = 1250                        # TGT_TICK_RELOAD
RELOAD_VALUE = (0 - TICK_RELOAD) & 0xFFFF  # 0xFB1E


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def cpu_with(sfrs):
    """A bare CPU whose only job is to let tick_timers() run."""
    img = bytearray(b"\xFF" * 0x100000)
    # NOPs, so stepping never faults while the timers advance
    img[0xE0000:0xE0000 + 64] = b"\xCC\x00" * 32
    m = S.Mem(bytes(img))
    for i, v in enumerate((0, 1, 2, 3)):
        m.sfr[0xFE00 + 2 * i] = v
    m.sfr[0xFE12] = 0xFC00
    m.sfr[0xFE14] = 0xF600
    m.sfr[0xFE10] = 0xFC00
    c = S.CPU(m, 0x8E, 0x0000)
    for a, v in sfrs.items():
        c._sset(a, v)
    return c


def advance(c, ticks):
    """Advance exactly `ticks` timer ticks, without executing instructions."""
    for _ in range(ticks * c.steps_per_tick):
        c.tick_timers()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=== does c167sim reload CAPCOM timers from TxREL? ===")
    print("")

    # --- 1. T8 reloads from T8REL, it does not wrap to zero --------------
    c = cpu_with({T78CON: 0x4242, T8REL: RELOAD_VALUE, T8: 0xFFFF, T8IC: 0x60})
    advance(c, 1)
    check("T8 overflow reloads from T8REL (not 0)",
          c._sget(T8) == RELOAD_VALUE,
          "T8 = 0x%04X, expected 0x%04X" % (c._sget(T8), RELOAD_VALUE))
    check("the overflow still raises T8IR",
          (c._sget(T8IC) & 0x80) != 0, "T8IC = 0x%04X" % c._sget(T8IC))

    # --- 2. the resulting PERIOD is TGT_TICK_RELOAD ticks ----------------
    # THE POINT OF F1: with no software reload at all, consecutive overflows
    # must be exactly 1250 ticks apart.
    c = cpu_with({T78CON: 0x4242, T8REL: RELOAD_VALUE, T8: RELOAD_VALUE,
                  T8IC: 0x60})
    gaps, last = [], None
    for t in range(1, 4 * TICK_RELOAD + 8):
        c._sset(T8IC, c._sget(T8IC) & ~0x80)      # "the ISR ran"
        advance(c, 1)
        if c._sget(T8IC) & 0x80:
            if last is not None:
                gaps.append(t - last)
            last = t
    check("overflow period without any software reload is %d ticks"
          % TICK_RELOAD,
          len(gaps) >= 2 and all(g == TICK_RELOAD for g in gaps),
          "gaps = %s" % gaps[:4])

    # --- 3. AND IT SURVIVES A LOST REQUEST -------------------------------
    # The V49 failure mode: the request is destroyed, so the ISR never runs,
    # so nothing reloads T8. With the hardware reload the NEXT overflow is
    # still one period away, not a full 65536-tick lap.
    c = cpu_with({T78CON: 0x4242, T8REL: RELOAD_VALUE, T8: RELOAD_VALUE,
                  T8IC: 0x60})
    advance(c, TICK_RELOAD)                        # first overflow
    got_first = (c._sget(T8IC) & 0x80) != 0
    c._sset(T8IC, c._sget(T8IC) & ~0x80)           # DESTROY the request
    n = 0
    while n < 3 * TICK_RELOAD and not (c._sget(T8IC) & 0x80):
        advance(c, 1)
        n += 1
    check("after a DESTROYED request the next overflow is one period away",
          got_first and n == TICK_RELOAD,
          "%d ticks later (a lap would be %d)" % (n, 0x10000))

    # --- 4. backward compatibility: TxREL = 0 still wraps to 0 -----------
    # Every build up to V49 leaves T8REL at 0, so modelling the reload must
    # not change their behaviour at all.
    c = cpu_with({T78CON: 0x4242, T8REL: 0x0000, T8: 0xFFFF, T8IC: 0x60})
    advance(c, 1)
    check("TxREL = 0 still wraps to 0 (pre-V50 builds unaffected)",
          c._sget(T8) == 0, "T8 = 0x%04X" % c._sget(T8))

    # --- 5. the same holds for the other CAPCOM timers -------------------
    c = cpu_with({T78CON: 0x4242, T7REL: 0x1234, T7: 0xFFFF})
    advance(c, 1)
    check("T7 reloads from T7REL", c._sget(T7) == 0x1234,
          "T7 = 0x%04X" % c._sget(T7))
    c = cpu_with({T01CON: 0x0042, T0REL: 0xABCD, T0: 0xFFFF, T0IC: 0x40})
    advance(c, 1)
    check("T0 reloads from T0REL", c._sget(T0) == 0xABCD,
          "T0 = 0x%04X" % c._sget(T0))

    # --- 6. a stopped timer does not advance or reload -------------------
    c = cpu_with({T78CON: 0x0000, T8REL: RELOAD_VALUE, T8: 0xFFFF})
    advance(c, 4)
    check("a stopped T8 neither advances nor reloads",
          c._sget(T8) == 0xFFFF, "T8 = 0x%04X" % c._sget(T8))

    # --- 7. NEGATIVE CONTROL: the pre-V50 model must FAIL checks 1 and 3 --
    #
    # Without this the file proves only that the simulator agrees with itself.
    # Rebind tick_timers to exactly what it used to be - wrap to zero, TxREL
    # never read - and require the two decisive checks to break.
    print("")
    print("  -- negative control: the pre-V50 'wrap to zero' model --")

    def legacy_tick_timers(self):
        self.tacc += 1
        if self.tacc < self.steps_per_tick:
            return
        self.tacc = 0
        for name, (addr, con, runbit) in S.TIMERS.items():
            if not (self._sget(con) & runbit):
                continue
            v = (self._sget(addr) + 1) & 0x1FFFF
            if v > 0xFFFF:
                v = 0                      # <-- the defect
                ic = S.TIMER_OVF_IC.get(name)
                if ic is not None:
                    self._sset(ic, self._sget(ic) | 0x80)
                    self.irq_pending.add(ic)
            self._sset(addr, v)
        self.check_compares()

    modern = S.CPU.tick_timers
    S.CPU.tick_timers = legacy_tick_timers
    try:
        c = cpu_with({T78CON: 0x4242, T8REL: RELOAD_VALUE, T8: 0xFFFF,
                      T8IC: 0x60})
        advance(c, 1)
        legacy_reload_wrong = c._sget(T8) != RELOAD_VALUE

        c = cpu_with({T78CON: 0x4242, T8REL: RELOAD_VALUE, T8: RELOAD_VALUE,
                      T8IC: 0x60})
        advance(c, TICK_RELOAD)
        c._sset(T8IC, c._sget(T8IC) & ~0x80)      # destroy the request
        n = 0
        while n < 0x11000 and not (c._sget(T8IC) & 0x80):
            advance(c, 1)
            n += 1
        legacy_lap = n
    finally:
        S.CPU.tick_timers = modern

    check("pre-V50 model gets the reload WRONG (so check 1 is non-vacuous)",
          legacy_reload_wrong, "it wrapped to 0 instead of 0x%04X"
          % RELOAD_VALUE)
    check("pre-V50 model takes a FULL LAP after a destroyed request",
          legacy_lap == 0x10000,
          "%d ticks = %.1f ms at 1.25 MHz (the real ECU's 51.4 ms failure)"
          % (legacy_lap, legacy_lap / 1250.0))

    print("")
    print("%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    print("sim_capcom_reload_test: %s" % ("PASS" if FAILS == 0 else "FAIL"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
