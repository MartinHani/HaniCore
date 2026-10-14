#!/usr/bin/env python3
r"""me711_dbw_pedal_skew_proof.py - a FAST pedal press must not drop the throttle.

    py tests\firmware\engine\me711_dbw_pedal_skew_proof.py [--control <bins dir>]

THE DEFECT (AWT car, 2026-10-10: "the engine wants to cut out on a fast pedal
press, a slow one is fine", DBW on). The main ADC converts one channel per
millisecond, round robin, so each pedal track is refreshed every 16 ms, AN8
(pedal 1) one millisecond before AN9 (pedal 2). For one millisecond in every
sixteen, pedal 1 is fresh and pedal 2 is 15 ms old. hc_dbw.c compared the two
LATEST samples, so a pedal moving faster than ~0.7 %/ms (0 -> 100 % in about
140 ms) disagreed by more than the 10 % pair tolerance, and sensor_fault()
drops the bridge on the FIRST suspect pair (the debounce only delays the
latch): the plate fell to its spring for at least four control steps while
the driver was asking for more air. TPS had the same problem and was fixed
with a time-aligned pair (hcfresh711.c hc_fresh_tps_pair); the pedal was not.

THE FIX: the pedal pair is time-aligned the same way (hc_fresh_app_pair):
the newer track is interpolated back to the older track's sample time from
its own previous sample.

Simulator (linked image in c167sim, the runtime-stress rig: real main loop,
1 ms tick ADC, DBW on with a first-order plate plant), engine stopped:
  A  six fast stabs 5 -> 95 % in 60 ms and back: DBW stays in RUN, the bridge
     is never dropped, no pair fault pending or latched;
  B  slow presses (600 ms): the same (sanity);
  C  a REAL disagreement - pedal 2 reads 25 % off - is still refused and
     latched (APP_PAIR): the fix aligns time, it does not widen anything.
--control points the rig at an older image: A must FAIL there.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if "--control" in sys.argv:
    os.environ["HANICORE_ME711_BINS"] = sys.argv[sys.argv.index("--control") + 1]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402
import me711_runtime_stress as RS  # noqa: E402

DBW_ST, DBW_FLT = 0x387300, 0x387302
ST_NAME = {0: "OFF", 1: "INIT", 2: "RUN", 3: "FAULT"}
APP_PAIR = 0x0002
FAILS = 0


def check(name, ok, detail=""):
    global FAILS
    FAILS += 0 if ok else 1
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))


class Rig(RS.Stress):
    """Pedal as a function of simulated time; optional pedal-2 offset."""
    pedal_fn = None
    app2_offset = 0.0

    def adc_value(self, ch):
        if self.pedal_fn is not None:
            self.pedal = self.pedal_fn(self.t1_ext / RS.TICKS_PER_S)
        v = super().adc_value(ch)
        if ch == 9 and self.app2_offset:
            v = int(v + self.app2_offset * 349)
        return v


def watch(s, us, step_us=250):
    """Run `us`, sampling the DBW state; return (states seen, drops, flt)."""
    seen, drops = set(), 0
    last = s.mem.r8(DBW_ST)
    t = 0
    while t < us:
        s.run_us(step_us)
        t += step_us
        st = s.mem.r8(DBW_ST)
        seen.add(st)
        if last == 2 and st != 2:
            drops += 1
        last = st
    return seen, drops, s.mem.r16(DBW_FLT)


def stabs(t0, period, rise, n, lo=0.05, hi=0.95):
    def f(t):
        x = t - t0
        if x < 0 or x >= n * period:
            return lo
        x %= period
        half = period / 2
        if x < rise:
            return lo + (hi - lo) * x / rise
        if x < half:
            return hi
        if x < half + rise:
            return hi - (hi - lo) * (x - half) / rise
        return lo
    return f


def main() -> int:
    print("=== DBW pedal pair under a fast press (simulator) ===")
    print("  image", RS.PI.image(), RS.PI.sha256()[:8] if hasattr(RS.PI, "sha256") else "")
    s = Rig(RS.build_awt_page(dbw=True), ts=False)
    s.dbw_plant = True
    s.pedal = 0.05
    s.boot()
    seen, drops, flt = watch(s, 300_000)
    check("DBW reaches RUN at rest", s.mem.r8(DBW_ST) == 2,
          "state %s flt 0x%04X" % (ST_NAME.get(s.mem.r8(DBW_ST)), flt))

    t0 = s.t1_ext / RS.TICKS_PER_S + 0.05
    s.pedal_fn = stabs(t0, 0.5, 0.060, 6)
    seen, drops, flt = watch(s, 3_150_000)
    check("A fast stabs (60 ms 5->95 %): never leaves RUN", drops == 0 and seen == {2},
          "drops %d states %s flt 0x%04X" % (drops, sorted(ST_NAME.get(x) for x in seen), flt))
    check("A ... and no pedal pair fault latched", (flt & APP_PAIR) == 0, "flt 0x%04X" % flt)

    t0 = s.t1_ext / RS.TICKS_PER_S + 0.05
    s.pedal_fn = stabs(t0, 2.0, 0.600, 2)
    seen, drops, flt = watch(s, 4_100_000)
    check("B slow presses (600 ms): never leaves RUN", drops == 0 and seen == {2},
          "drops %d flt 0x%04X" % (drops, flt))

    s.pedal_fn = None
    s.pedal = 0.30
    s.app2_offset = 0.25
    seen, drops, flt = watch(s, 600_000)
    check("C a real 25 % pedal disagreement is still latched (APP_PAIR)",
          (flt & APP_PAIR) != 0 and s.mem.r8(DBW_ST) != 2,
          "state %s flt 0x%04X" % (ST_NAME.get(s.mem.r8(DBW_ST)), flt))
    print("\nPASS" if not FAILS else "\n%d FAIL" % FAILS)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
