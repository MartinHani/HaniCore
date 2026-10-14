#!/usr/bin/env python3
r"""
me711_tipin_fill_proof.py - a quick throttle step on the LINKED image with the
running engine (c167sim stress rig, AWT preset page, 60-2 crank + cam).

    py tests\firmware\engine\me711_tipin_fill_proof.py
    py tests\firmware\engine\me711_tipin_fill_proof.py --control   the
        2026-10-11 car image (EF8582E6): must FAIL

THE CAR (2026-10-11, s4 218.8 s, logged): a quick press at 1465 rpm took the
alpha-N load from 5 % to 30..55 % in one 0.15 s sample; the ignition table's
full-load cells gave 9 -> 3 deg advance into a manifold that had not filled,
the injector pulse quadrupled at once and rpm fell to 1236 - "it feels like a
spark cut". No cut, no reset (verified on ecuMs / rstBootCount).

THE REFERENCE - FR "Audi R4-5V T 132kW ME7.1" BGSRM 17.10: the stock ECU's
load is the intake-manifold model, KISRM = zkorr / (z * Vs/VH) per segment
(0.1023 for the FR's 4-cylinder example): ~0.23 s at 1300 rpm.

CASES (throttle 5 % -> 50 % at 1300 rpm, the engine load and the advance;
100 ms = inside the car log's 0.15 s sample that showed the jump; the FR
model gives 5 + 45 * (1 - exp(-0.1 / 0.226)) = 21 % there):
  F1 100 ms after the step the load is still below 30 % (no jump)
  F2 100 ms after the step the advance is still >= the steady full-load
     advance + 3 deg (it follows the filling, it has not collapsed)
  F3 the load reaches 50 % within 1 %: after 1.2 s (it is a lag, not a cap)
  F4 and the advance is then the table's own full-load value (+-1 deg):
     steady state unchanged
(First version sampled at 20 ms with an absolute 15 deg: the 2026-10-11
image's own TPS filter had not moved yet at 20 ms and the new 12 deg idle
cells are below 15 deg - its control passed, it could not tell.)
SIMULATOR ONLY: the engine does not answer the throttle (rpm is the rig's).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402

CONTROL_BINS = ROOT.parent / "evidence" / "OVERNIGHT_20261011" / "image_final"
if "--control" in sys.argv:
    env = dict(os.environ, HANICORE_ME711_BINS=str(CONTROL_BINS))
    r = subprocess.run([sys.executable, __file__], env=env)
    ok = r.returncode != 0
    print("\nCONTROL (EF8582E6, the 2026-10-11 car image): %s"
          % ("FAILS as it must" if ok else "PASSED - the gate cannot tell"))
    raise SystemExit(0 if ok else 1)

import me711_runtime_stress as M          # noqa: E402

FAILS = 0


def check(name, ok, detail=""):
    global FAILS
    FAILS += 0 if ok else 1
    print("  [%s] %-62s %s" % ("PASS" if ok else "FAIL", name, detail))


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def main() -> int:
    print("=== quick throttle step at 1300 rpm - %s ===" % M.PI.image())
    s = M.Stress(M.build_awt_page(), ts=False)
    s.throttle = 0.05
    s.boot()
    rpm = 1300
    M.segment(s, "crank 250", 300_000, lambda t: 250, 250, [])
    M.segment(s, "ramp", 300_000, M.ramp(250, rpm, 0.3), rpm, [])
    M.segment(s, "hold", 1_000_000, lambda t: rpm, rpm, [])
    load0 = s.r16("eng_load")
    adv0 = s.r16("eng_adv_x10")
    s.throttle = 0.50
    trace = []
    for i in range(120):                       # 1.2 s in 10 ms
        s.run_us(10_000, lambda t: rpm)
        trace.append((s.r16("eng_load"), s16(s.r16("eng_adv_x10"))))
    l100, a100 = trace[9]
    lend, aend = trace[-1]
    print("  before: load %.1f %% adv %.1f" % (load0 / 10, s16(adv0) / 10))
    for i in (1, 4, 9, 14, 19, 29, 49):
        print("  +%4d ms  load %5.1f %%  adv %5.1f" % ((i + 1) * 10,
              trace[i][0] / 10, trace[i][1] / 10))
    print("  +1200 ms  load %5.1f %%  adv %5.1f" % (lend / 10, aend / 10))
    check("F1 100 ms after the step the load has not jumped (< 30 %)",
          l100 < 300, "%.1f %%" % (l100 / 10))
    check("F2 100 ms after the step the advance >= full-load + 3 deg",
          a100 >= aend + 30, "%.1f deg (full load %.1f)" % (a100 / 10, aend / 10))
    check("F3 the load reaches the throttle (50 % within 1 %) by 1.2 s",
          abs(lend - 500) <= 10, "%.1f %%" % (lend / 10))
    # the table's own value at (1300 rpm, 50 %): AWT preset ignMap row 50 %
    check("F4 the steady advance is the table's full-load value (+-1 deg)",
          abs(aend - 35) <= 10, "%.1f deg (table 3.5)" % (aend / 10))
    print("\nPASS" if not FAILS else "\n%d FAIL" % FAILS)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
