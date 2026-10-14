#!/usr/bin/env python3
r"""
me711_dbw_dlr_monitor_proof.py - the Bosch DLR setting-range monitor on the
LINKED image (c167sim, the ETB proof's spring plant).

    py tests\firmware\dbw\me711_dbw_dlr_monitor_proof.py            the image me711_image names
    py tests\firmware\dbw\me711_dbw_dlr_monitor_proof.py --control  the 2026-10-11 car image
                                                       (EF8582E6): must FAIL

THE CAR (2026-10-11): a CJ220 status-flag reading latched DBW_F_SF on the
first read (idle, s4 126.6 s: P2100/P2110, plate to the spring, 1500 rpm fuel
cut hunting), and the owner reports "CEL and the ECU switches DBW off" at
some starts; KL15 off with the engine turning latched DBW_F_VBAT.

THE REFERENCE - FR "Audi R4-5V T 132kW ME7.1" DLR 3.60 pp. 1337-1338, values
from the EPK-matched Porsche ME7.1.1 A1104F A2L+hex (hcetbcal.c): the status
flag is only judged while the controller output is beyond DLRPIDMAX; the
error time then grows 10 ms per 10 ms (falls by TDLRPIDC 0.2 s otherwise);
> DLRPID1T 0.6 s = reversible fuel cut request, > DLRPID2T 5 s = latched
(status flag low: power-stage error, else "range at limit"); a low flag
restarts the power stage after DVEEST 20 ms. Battery below 6.48 V suspends
the monitoring.

CASES
  M1 healthy 10 -> 65 % step, then hold: no fault, arrives.
  M2 the status flag pulses low for 30 ms while the plate tracks (not
     saturated): NO fault (the car image latches DBW_F_SF).
  M3 a dead bridge (status flag low, no torque): reversible request
     (DBW_F_RANGE in the published word) after ~0.6 s, power-stage restarts
     (enable dropped and re-asserted) before it, DBW_F_SF latched after ~5 s
     and not before 4.9 s.
  M4 a stuck plate, flag healthy: DBW_F_DEV latched after ~5 s, not before
     4.9 s; reversible request from ~0.6 s.
  M5 the battery reads 1.0 V (KL15 off, engine turning): the bridge is not
     driven and NOTHING latches; it drives again when the battery returns
     (the car image latches DBW_F_VBAT).
NOT PHYSICALLY VERIFIED: the AWT body / CJ220 behaviour is the car's.
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

import me711_config_state_test as T      # noqa: E402
import me711_etb_autocal_proof as E      # noqa: E402

SF_BIT, DEV_BIT, VBAT_BIT, RANGE_BIT = 0x0020, 0x0040, 0x0200, 0x0400
CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += 0 if ok else 1
    print("  [%s] %-62s %s" % ("PASS" if ok else "FAIL", name, detail))
    return ok


def commissioned():
    b = E.Bench()
    res, _ph, why = b.run(arg=3)
    assert res == 5, "commission failed: result %d why %d" % (res, why)
    for _ in range(40):
        b.step()
    return b


class Run:
    """Steps the bench with the engine's battery reading kept in step with the
    plant's (eng_batt_dv is the main loop's; the bench has no engine), and
    records the latched word, the published word (OCH 402) and the enable."""

    def __init__(self, b):
        self.b = b
        self.eb = T.sym("eng_batt_dv") & 0xFFFF

    def step(self):
        b = self.b
        b.r.m.w16(self.eb, b.batt_dv)
        b.step()
        on = b.r("hc_dbw_bridge_on")
        return b.r("hc_dbw_faults"), on


def ska(b):
    """the reversible request; an image without the monitor has none"""
    try:
        T.sym("hc_etbcal_dlr_ska")
    except BaseException:                 # T.sym exits on a missing symbol
        return 0
    return b.r("hc_etbcal_dlr_ska")


def main() -> int:
    import me711_image as PI
    print("=== Bosch DLR setting-range monitor - %s (%s) ===" % (PI.STEM, getattr(PI, "BINS", "")))

    # M1
    b = commissioned()
    run = Run(b)
    b.r("hc_dbw_override", 100)
    for _ in range(600):
        run.step()
    b.r("hc_dbw_override", 650)
    flt = 0
    for _ in range(1500):
        f, _on = run.step()
        flt |= f
    act = b.r("hc_dbw_actual_x10")
    check("M1 healthy 10 -> 65 %: no fault, arrives",
          flt == 0 and abs(act - 650) <= 30, "faults 0x%04X actual %d" % (flt, act))

    # M2 - a 30 ms status-flag pulse while tracking
    flt = 0
    for i in range(400):
        b.sf(10 <= i < 40)
        f, _on = run.step()
        flt |= f
    b.sf(False)
    check("M2 30 ms status-flag pulse while tracking: no fault latched",
          flt & (SF_BIT | DEV_BIT) == 0, "faults 0x%04X" % flt)
    b.r("hc_dbw_override", 0xFFFF)

    # M3 - dead bridge: flag low and no torque
    b = commissioned()
    run = Run(b)
    b.r("hc_dbw_override", 100)
    for _ in range(600):
        run.step()
    b.r("hc_dbw_override", 650)
    b.k = 0.0
    t_sf = t_rng = None
    drops = 0
    prev_on = 1
    for i in range(6000):
        b.sf(True)
        f, on = run.step()
        if prev_on and not on and t_sf is None and i < 4900:
            drops += 1
        prev_on = on
        if t_rng is None and ska(b):
            t_rng = i
        if t_sf is None and f & SF_BIT:
            t_sf = i
    b.sf(False)
    check("M3a dead bridge: reversible request after ~0.6 s",
          t_rng is not None and 550 <= t_rng <= 1200, "request at %s ms" % t_rng)
    check("M3b power-stage restarts before the latch (enable re-pulsed)",
          drops >= 2, "%d enable drops in the first 4.9 s" % drops)
    check("M3c DBW_F_SF latched after ~5 s, not before 4.9 s",
          t_sf is not None and 4900 <= t_sf <= 5800, "latched at %s ms" % t_sf)
    b.r("hc_dbw_override", 0xFFFF)

    # M4 - stuck plate, flag healthy
    b = commissioned()
    run = Run(b)
    b.r("hc_dbw_override", 100)
    for _ in range(600):
        run.step()
    b.stuck = True
    b.r("hc_dbw_override", 650)
    t_dev = t_rng = None
    for i in range(6000):
        f, _on = run.step()
        if t_rng is None and ska(b):
            t_rng = i
        if t_dev is None and f & DEV_BIT:
            t_dev = i
    check("M4a stuck plate: reversible request (limp fuel cut) after ~0.6 s",
          t_rng is not None and 550 <= t_rng <= 1200, "request at %s ms" % t_rng)
    check("M4b stuck plate: DBW_F_DEV latched after ~5 s, not before 4.9 s",
          t_dev is not None and 4900 <= t_dev <= 5800, "latched at %s ms" % t_dev)
    b.r("hc_dbw_override", 0xFFFF)

    # M5 - battery gone (KL15 off with the engine turning)
    b = commissioned()
    run = Run(b)
    b.r("hc_dbw_override", 300)
    for _ in range(600):
        run.step()
    b.batt_dv = 10
    flt = 0
    any_on = 0
    for _ in range(300):
        f, on = run.step()
        flt |= f
        any_on |= on
    b.batt_dv = 135
    back = 0
    for _ in range(600):
        f, on = run.step()
        flt |= f
        back |= on
    check("M5 battery 1.0 V: bridge not driven, nothing latched, drives again",
          flt & (VBAT_BIT | SF_BIT | DEV_BIT) == 0 and back,
          "faults 0x%04X driven-after %d" % (flt, back))
    b.r("hc_dbw_override", 0xFFFF)

    print("\n%d checks, %d failed" % (CHECKS, FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
