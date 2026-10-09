#!/usr/bin/env python3
r"""
me711_dbw_deviation_proof.py - the ETB deviation supervisor on a SHARP target
step, on the LINKED image (c167sim), with the ETB proof's spring plant.

    py tests\firmware\dbw\me711_dbw_deviation_proof.py            the image me711_image names
    py tests\firmware\dbw\me711_dbw_deviation_proof.py --control  V98r2 (9BF22D32, the car
                                                     image): must FAIL

THE CAR (2026-10-02, V98r2): "the engine starts and runs; when the throttle
is opened more sharply and the rpm rises, it begins dying as if the ignition
were being cut". With DBW on, V83..V98 latched DBW_F_DEV whenever the plate
was more than dbwDevX10 (AWT 15 %) from the RAW target for dbwDevMs (AWT
200 ms) - a sharp pedal step on a plate that needs longer than that to
arrive. The latch drops the bridge (the plate falls to the limp opening) and
hclimp.c cuts the FUEL above etbLimpRpm (0 = 1500 rpm) until the next key-on.
rusEFI's jam detector is 10 % for etbJamTimeout (default OFF, 1 s).

CASES (the AWT page values: 15 %, 200 ms)
  D1  healthy body, 10 -> 65 % step: no fault, the plate arrives.
  D2  a SLUGGISH bridge (45 % of the commanded torque - the car's AutoCal
      showed a weak drive) travelling steadily toward 65 %: V99 no fault
      and the plate arrives; V98r2 latches DBW_F_DEV (the reproduction).
  D3  a STUCK plate: the error does not shrink - V99 still latches DBW_F_DEV
      within dbwDevMs (+ one 10 ms step).
NOT PHYSICALLY VERIFIED: the AWT body's real step response is the car's.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

CONTROL_STEM = "HaniCore_ME711_v98_dev"
if "--control" in sys.argv:
    env = dict(os.environ, HANICORE_ME711_STEM=CONTROL_STEM)
    r = subprocess.run([sys.executable, __file__], env=env)
    ok = r.returncode != 0
    print("\nCONTROL (%s, V98r2): %s" % (CONTROL_STEM,
          "FAILS as it must" if ok else "PASSED - the gate cannot tell"))
    raise SystemExit(0 if ok else 1)

import me711_config_state_test as T      # noqa: E402
import me711_etb_autocal_proof as E      # noqa: E402

DEV_BIT = 0x0040
CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += 0 if ok else 1
    print("  [%s] %-60s %s" % ("PASS" if ok else "FAIL", name, detail))
    return ok


def commissioned(strength=1.0):
    """A body commissioned by '!C3' (endpoints + gains ACTIVE), then the
    page's deviation window set to the AWT's own 15 % / 200 ms."""
    b = E.Bench()
    res, _ph, why = b.run(arg=3)
    assert res == 5, "commission failed: result %d why %d" % (res, why)
    for _ in range(40):
        b.step()                          # let the hand-off become ACTIVE
    b.r("hc_cal_set_u16", T.d(T._cfg, "CAL_DBW_DEV_X10"), 150)
    b.r("hc_cal_set_u16", T.d(T._cfg, "CAL_DBW_DEV_MS"), 200)
    b.k = strength
    return b


def step_test(b, start, target, ms, stuck_after=None):
    """Hold `start`, then step to `target`; -> (fault ms or None, end act)"""
    b.r("hc_dbw_override", start)
    for _ in range(600):
        b.step()
    if stuck_after is not None:
        b.stuck = True
    b.r("hc_dbw_override", target)
    t_fault = None
    for i in range(ms):
        b.step()
        if t_fault is None and b.r("hc_dbw_faults") & DEV_BIT:
            t_fault = i
    act = b.r("hc_dbw_actual_x10")
    b.r("hc_dbw_override", 0xFFFF)
    return t_fault, act


def main() -> int:
    import me711_image as PI
    print("=== ETB deviation supervisor on a sharp step - %s ===" % PI.STEM)
    b = commissioned(1.0)
    t, act = step_test(b, 100, 650, 1000)
    check("D1 healthy body 10 -> 65 %: no deviation fault, arrives",
          t is None and abs(act - 650) <= 30,
          "fault at %s ms, actual %d.%d %%" % (t, act // 10, act % 10))

    b = commissioned(0.45)
    t, act = step_test(b, 100, 650, 1500)
    check("D2 sluggish bridge travelling to 65 %: no fault, arrives",
          t is None and abs(act - 650) <= 40,
          "fault at %s ms (V98r2 latches here), actual %d.%d %%"
          % (t, act // 10, act % 10))

    b = commissioned(1.0)
    t, act = step_test(b, 100, 650, 1000, stuck_after=0)
    check("D3 stuck plate: DBW_F_DEV still latches within 200 + 10 ms",
          t is not None and t <= 215,
          "fault at %s ms, actual %d.%d %%" % (t, act // 10, act % 10))
    print("\n%d checks, %d failed" % (CHECKS, FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
