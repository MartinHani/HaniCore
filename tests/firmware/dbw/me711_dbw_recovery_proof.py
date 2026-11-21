#!/usr/bin/env python3
r"""Gate: a tuner can always get the throttle back with the engine stopped.

WHY. Testers and the owner's own car (2026-11): dbwEnable on, calibrated, pedal
gauge alive, plate dead. On a page with an uncalibrated pedal or stale TPS
endpoints, enabling latched a fault, and then the calibration that fixed it
changed nothing (AutoCal even PASSED), or refused to run at all. Only a key
cycle or a DTC clear brought it back, and nothing on the screen said so.

Linked image, real AutoCal, spring-and-stop plant, the tester's step orders:
  order 1  enable first, TPS right, AutoCal while it runs: takes over, follows
  order 2  enable first, stale TPS: AutoCal runs, passes, follows
  order 3  enable first, wrong pedal: calibrating the pedal is enough
  order 4  a latched fault, then off -> on with the engine stopped: follows
  order 5  the documented order still works; dbwEnable never set by AutoCal
What must NOT change:
  guard 1  a real pedal fault latches again after the page moved
  guard 2  with the engine turning neither way out clears anything
  guard 3  a bridge fault survives a page change; PID tune still refuses
           (me711_dbw_revision_proof holds the rest of that rule)

Runs on the board under test (HANICORE_BOARD).
--control runs the frozen image from before the fix: orders 1, 2, 3, 4 must fail.
"""
from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402

CONTROL = Path(hcpaths.RAW_EVIDENCE) / "BENCH_20261105_DC" / "control_75324849"
ORDERS = ("order1", "order2", "order3", "order4", "order5", "guard1", "guard2", "guard3")
RUN = 2
FAULT = 3
EN = 1240


def rig():
    import me711_etb_autocal_proof as P
    b = P.Bench()
    orig = b.plant
    b.ped = 0.0

    def plant():
        orig()
        # the rig's pedal (track 1 150..849, track 2 75..424), sampled every step
        b.adc_set(8, int(150 + 699 * b.ped))
        b.adc_set(9, int(75 + 349 * b.ped))
    b.plant = plant

    def wr8(o, v):
        b.r("hc_cfg_mgr_write_u8", o, v, steps=2_000_000)

    def wr16(n, v):
        o = P.AP.off(n)
        wr8(o, v >> 8)
        wr8(o + 1, v & 255)

    def run(ms, rpm=0):
        for _ in range(ms):
            b.step(rpm)

    def follows(tag):
        """Pedal at 50 %: the plate follows it, with the bridge driven."""
        b.ped = 0.5
        run(1500)
        st, act, on = b.r.callb("hc_dbw_state"), b.r("hc_dbw_actual_x10"), b.r.callb("hc_dbw_bridge_on")
        b.ped = 0.0
        run(300)
        ok = st == RUN and on == 1 and act > 200
        print("  [%s] %-46s state %d flt %04X act %d" % (
            "PASS" if ok else "FAIL", tag, st, b.r("hc_dbw_faults"), act), flush=True)
        return ok

    if b.is_dc:
        # as a tuner's page holds them: through the config manager, so writing
        # dbwEnable (RPM_ZERO, one group) does not apply the board default over them
        for n, v in (("CFG_U_DBW_MAX_DUTY_X10", 800), ("CAL_TPS1_MIN", 102), ("CAL_TPS1_MAX", 954),
                     ("CAL_TPS2_MIN", 919), ("CAL_TPS2_MAX", 71), ("CAL_PEDAL1_MIN", 150),
                     ("CAL_PEDAL1_MAX", 849), ("CAL_PEDAL2_MIN", 75), ("CAL_PEDAL2_MAX", 424)):
            wr16(n, v)
        wr8(P.AP.off("CFG_U_TPS_CORR"), 1)
        wr8(P.AP.off("CFG_U_APP_CORR"), 1)
    run(1200)
    return b, wr8, wr16, run, follows


def check(ok, tag, detail=""):
    print("  [%s] %-46s %s" % ("PASS" if ok else "FAIL", tag, detail), flush=True)
    return bool(ok)


def one(which: str) -> int:
    b, wr8, wr16, run, follows = rig()
    res = []
    if which == "order1":
        wr8(EN, 1)
        run(800)
        res.append(follows("enabled, TPS right"))
        out = b.run()
        res.append(check(out[0] == 2, "AutoCal with the throttle running", str(out)))
        run(500)
        res.append(follows("after AutoCal"))
    if which == "order2":
        wr16("CAL_TPS2_MIN", 600)
        wr16("CAL_TPS2_MAX", 400)
        run(400)
        wr8(EN, 1)
        run(800)
        res.append(check(b.r.callb("hc_dbw_state") == FAULT, "stale TPS latches", "flt %04X" % b.r("hc_dbw_faults")))
        out = b.run()
        res.append(check(out[0] == 2, "AutoCal runs despite the TPS fault", str(out)))
        run(800)
        res.append(follows("after AutoCal, no key cycle"))
    if which == "order3":
        wr16("CAL_PEDAL2_MIN", 300)
        wr16("CAL_PEDAL2_MAX", 800)
        run(400)
        wr8(EN, 1)
        run(800)
        res.append(check(b.r.callb("hc_dbw_state") == FAULT, "wrong pedal latches", "flt %04X" % b.r("hc_dbw_faults")))
        wr16("CAL_PEDAL2_MIN", 75)
        wr16("CAL_PEDAL2_MAX", 424)
        run(800)
        res.append(follows("pedal calibrated, no key cycle"))
    if which == "order4":
        wr8(EN, 1)
        run(800)
        b.r("hc_dbw_shutdown", 128)           # a stale-sample latch, not page related
        run(200)
        res.append(check(b.r.callb("hc_dbw_state") == FAULT, "latched", "flt %04X" % b.r("hc_dbw_faults")))
        wr8(EN, 0)
        run(300)
        res.append(check(b.r("hc_dbw_faults") & 128, "still latched while off", "flt %04X" % b.r("hc_dbw_faults")))
        wr8(EN, 1)
        run(800)
        res.append(follows("off -> on with the engine stopped"))
    if which == "order5":
        out = b.run()
        res.append(check(out[0] == 2, "AutoCal, enable off", str(out)))
        run(500)
        res.append(check(b.r.active(EN) == 0 and b.r.desired(EN) == 0, "AutoCal does not enable"))
        wr8(EN, 1)
        run(800)
        res.append(follows("documented order"))
    if which == "guard1":
        wr16("CAL_PEDAL2_MIN", 300)
        wr16("CAL_PEDAL2_MAX", 800)
        run(400)
        wr8(EN, 1)
        run(800)
        wr16("CAL_DBW_KP", 5000)              # a page change that does not fix it
        run(800)
        res.append(check(b.r.callb("hc_dbw_state") == FAULT and b.r("hc_dbw_faults") & 8,
                         "a real pedal fault latches again", "flt %04X" % b.r("hc_dbw_faults")))
        res.append(check(b.r.callb("hc_dbw_bridge_on") == 0, "bridge stayed down"))
    if which == "guard2":
        wr8(EN, 1)
        run(800)
        b.r("hc_dbw_shutdown", 8)             # a pedal range latch
        run(100)
        wr16("CAL_DBW_KP", 5000)
        run(300, rpm=1200)
        res.append(check(b.r.callb("hc_dbw_state") == FAULT, "page change, engine turning: latched",
                         "flt %04X" % b.r("hc_dbw_faults")))
        wr8(EN, 0)
        run(100, rpm=1200)
        wr8(EN, 1)
        run(300, rpm=1200)
        res.append(check(b.r.callb("hc_dbw_state") == FAULT, "off -> on, engine turning: latched",
                         "flt %04X" % b.r("hc_dbw_faults")))
        res.append(check(b.r.callb("hc_dbw_bridge_on") == 0, "bridge stayed down"))
    if which == "guard3":
        wr8(EN, 1)
        run(800)
        b.r("hc_dbw_shutdown", 128)
        run(100)
        wr16("CAL_DBW_KP", 5000)
        run(300)
        res.append(check(b.r.callb("hc_dbw_state") == FAULT and b.r("hc_dbw_faults") & 128,
                         "a non-sensor latch survives a page change", "flt %04X" % b.r("hc_dbw_faults")))
        b.r("hc_dbw_shutdown", 16)
        run(50)
        out = b.run(arg=2, max_ms=800)
        res.append(check(all(not on for _, _, on, _ in b.log) or out[0] != 2,
                         "PID tune still refuses on a TPS fault", str(out)))
    return 0 if res and all(res) else 1


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--one":
        return one(sys.argv[2])
    control = "--control" in sys.argv
    env = dict(os.environ)
    if control:
        if not CONTROL.is_dir():
            print("SKIP: no frozen control image at %s" % CONTROL)
            return 0
        # the frozen image is a Porsche build; hc_dbw.c and hcetbcal.c are shared
        env["HANICORE_BOARD"] = "porsche_me711"
        env["HANICORE_ME711_BINS"] = str(CONTROL)

    def job(o):
        p = subprocess.run([sys.executable, __file__, "--one", o], env=env,
                           capture_output=True, text=True, timeout=1500)
        return o, p.returncode, p.stdout + p.stderr[-400:]

    with ThreadPoolExecutor(len(ORDERS)) as ex:
        out = list(ex.map(job, ORDERS))
    rc = {}
    for o, code, text in out:
        print("--- %s: %s" % (o, "pass" if code == 0 else "FAIL"))
        print(text.rstrip())
        rc[o] = code
    if control:
        must = ("order1", "order2", "order3", "order4")
        ok = all(rc[o] != 0 for o in must)
        print("\nCONTROL (image before the fix): orders 1-4 fail: %s" % ok)
        return 0 if ok else 1
    ok = all(c == 0 for c in rc.values())
    print("\nme711_dbw_recovery_proof: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
