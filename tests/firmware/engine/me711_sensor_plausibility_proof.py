#!/usr/bin/env python3
r"""
me711_sensor_plausibility_proof.py - CLT past its curve is a fault, and the
pedal/throttle pair lamps follow the configured correlation.

    py tests\firmware\engine\me711_sensor_plausibility_proof.py            the current image
    py tests\firmware\engine\me711_sensor_plausibility_proof.py --control  + the V89 control

THE DEFECTS (first AWT vehicle test, 2026-09-26):

  * CLT read raw 923 on ASIC AN0 and showed -40 C. V91 ROOT CAUSE: the
    board holds TMOT's switched 340 R pull-up ON (bench open 1015 = the
    FET-on model; TANS, which has no switch, opens at 958), and the preset
    used the OEM curve for the OFF state. With the OEM ON-state curve
    [BIN 0x81F976] raw 923 is ~15.6 C. And the measurement is published even
    when invalid (no displayed 80 C substitute). V97 (2026-09-30): an
    invalid CLT reads -40 C for display AND control
    (me711_sensor_fallback_proof.py owns that rule).
  * The PEDAL PLAUSIBILITY lamp (sensorErr 0x80) assumed opposing tracks
    whatever appCorrelation said. The VAG G185 rises with G79 at half its
    amplitude - SAME after calibration - so the lamp was red except around
    50 % pedal.

WHAT THIS RUNS: the LINKED image's eng_service() in c167sim over the applied
AWT preset (hc_cfg_init, hc_cfg_mgr_init, APPLY 3, hc_hal_init), with the
S5500 window word for ASIC AN0 and the main ADC channels set from this test:

  * CLT raw 923 (the car) -> VALID, measured ~15.6 C, control = measured;
  * CLT raw 1015 (bench open) -> fault; displayed and control both -40 C;
  * pedal at the AWT's measured pairs (150/75, 493/245, 664/332, 849/424)
    with the preset calibration -> ENG_ERR_PED_DIFF clear at every point;
  * a broken second track (APP2 stuck at 75 with APP1 floored) -> bit SET;
  * the throttle pair at the car's rest reading (155/866) -> no TPS_DIFF.

NEGATIVE CONTROL: V90 (frozen) reads CLT 923 as a fault with no measurement published.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

CONTROL_STEM = "HaniCore_ME711_v90_first_start_awt"
ERR_CLT, ERR_TPS_DIFF, ERR_PED_DIFF = 0x0001, 0x0040, 0x0080
WIN = 0x380000 + 0x7100            # TGT_EXTRAM_BASE + TGT_RAM_S5500WIN
CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += 0 if ok else 1
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))


def main_one(stem):
    os.environ["HANICORE_ME711_STEM"] = stem
    import me711_config_state_test as T
    import me711_preset_apply_proof as AP
    print("=== sensor plausibility - %s ===" % stem)
    r = T.boot()
    r.publish_on_service = True     # sensors as accepted samples (T.Rig)
    AP.press_apply(r, 3)
    AP.service(r)
    r("hc_hal_init", steps=5_000_000)
    r("eng_init", steps=5_000_000)
    r("hc_route_service", steps=5_000_000)
    adc = T.sym("adc_raw") & 0xFFFF
    base = r.g8("hc_s5500_base")
    r.m.w16(T.sym("hc_s5500_snaps") & 0xFFFF, 100)

    def win(ch, raw):
        i = 4 + ch - base
        r.m.w16(WIN + 2 * i, ((ch & 0xF) << 12) | (raw & 0x3FF))

    def state(clt=923, iat=541, app=(150, 75), tps=(155, 866), passes=400):
        win(0, clt)
        win(1, iat)
        for ch, v in ((8, app[0]), (9, app[1]), (1, tps[0]), (3, tps[1]),
                      (5, 646)):
            r.m.w16(adc + 2 * ch, v)
        for _ in range(passes):          # the filters settle
            r("eng_service", steps=5_000_000)
        try:
            meas = r.g16("eng_clt_meas_dc")
        except SystemExit:
            meas = None
        return r.g16("eng_sensor_err"), r.g16("eng_clt_dc"), meas

    def degc(dc):
        return None if dc is None else (dc - 10000) / 10.0

    err, dc, meas = state(clt=923)
    check("CLT raw 923 (the car) is VALID",
          not err & ERR_CLT, "err 0x%04X" % err)
    check("...and reads 13..18 C (ambient was 10..15 C, IAT 13.5 C)",
          meas is not None and 13.0 <= degc(meas) <= 18.0,
          "measured %s C" % (degc(meas) if meas is not None else "n/a"))
    check("...and the models use the same value",
          meas is not None and abs(degc(dc) - degc(meas)) < 0.5,
          "control %.1f C" % degc(dc))
    err, dc, meas = state(clt=1015)
    check("CLT raw 1015 (bench open) is a fault", bool(err & ERR_CLT),
          "err 0x%04X" % err)
    check("...control reads -40 C (V97), not the old 80 C substitute",
          abs(degc(dc) + 40.0) < 0.05, "control %.1f C" % degc(dc))
    check("...and the displayed value is the same -40 C",
          meas is not None and abs(degc(meas) + 40.0) < 0.05,
          "measured %s C" % (degc(meas) if meas is not None else "n/a"))

    bad = []
    for a1, a2 in ((150, 75), (250, 125), (493, 245), (664, 332),
                   (768, 384), (849, 424)):
        err, _, _ = state(app=(a1, a2))
        if err & ERR_PED_DIFF:
            bad.append((a1, a2))
    check("AWT pedal pairs agree across travel (SAME)", not bad,
          "flagged at %s" % bad if bad else "150/75 .. 849/424 all clear")
    err, _, _ = state(app=(849, 75))
    check("APP2 stuck at rest with APP1 floored IS flagged",
          bool(err & ERR_PED_DIFF), "err 0x%04X" % err)
    err, _, _ = state(tps=(155, 866))
    check("throttle at the car's rest reading (155/866) agrees",
          not err & ERR_TPS_DIFF, "err 0x%04X" % err)
    err, _, _ = state(tps=(155, 155))
    check("throttle tracks that both rise to 155 ARE flagged",
          bool(err & ERR_TPS_DIFF), "err 0x%04X" % err)
    return FAILS


def main() -> int:
    if "--one" in sys.argv:
        f = main_one(sys.argv[sys.argv.index("--one") + 1])
        print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
        return 1 if f else 0
    import me711_image as PI
    rc = subprocess.call([sys.executable, __file__, "--one", PI.STEM])
    if "--control" not in sys.argv:
        return rc
    print()
    rcc = subprocess.call([sys.executable, __file__, "--one", CONTROL_STEM])
    ok = rc == 0 and rcc != 0
    print()
    print("CONTROL: %s %s" % (CONTROL_STEM, "FAILS, as it must" if rcc
                                              else "PASSES - gate blind"))
    print("SENSOR PLAUSIBILITY PROOF %s" % ("PASSES" if ok else "FAILS"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
