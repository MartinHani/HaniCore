#!/usr/bin/env python3
r"""
me711_sensor_fallback_proof.py - an invalid CLT / IAT / MAP is DISPLAYED as
one fault value, and each CONSUMER applies its OWN documented fallback.

    py tests\firmware\engine\me711_sensor_fallback_proof.py            the current image
    py tests\firmware\engine\me711_sensor_fallback_proof.py --control  + the V97 control

THE RULE (V98, rusEFI per-consumer semantics; hcengine.h):
    DISPLAY / measured value: CLT -40 C, IAT -40 C, MAP 0 kPa + fault bit
    (unchanged: the gauge never shows a substitute).
    CONTROL, per consumer (each rusEFI's own):
      warm-up enrichment   failed CLT -> 1.0 (getCltFuelCorrection)
      charge temperature   failed IAT -> 0 C (getTCharge: dense, rich side)
      fuel pressure        failed MAP -> the MAP estimate table
                           (mapEstimateTable); pure alpha-N never reads it
V97 drove EVERY consumer with the display value: a failed coolant sensor
enriched like -40 C (170 % on a warm engine), a failed IAT computed air at
-40 C (+25 %), a failed MAP meant no air and no fuel at all.

WHAT THIS RUNS: the LINKED image's eng_service() in c167sim over the applied
AWT preset (hc_cfg_init, hc_cfg_mgr_init, APPLY 3, hc_hal_init) - the
sensor inputs set through the S5500 window (CLT AN0 = cavity 93, IAT AN1 =
cavity 26) and the main ADC (MAP AN14 = cavity 101). For each sensor:

    raw -> fault bit -> DISPLAYED value -> the consumer's fallback

  CLT open (raw 1015): ENG_ERR_CLT; OCH 130 and 780 read -40.0 C; warm-up
      enrichment 100 % (no enrichment), not the curve's coldest point.
  IAT open (raw 1020): ENG_ERR_IAT; OCH 132 reads -40.0 C; the cylinder air
      rises by T_valid / 273.15 K against a valid reading (0 C charge).
  MAP at a rail (raw 1023 / 0): ENG_ERR_MAP; OCH 134 reads 0 kPa; the air
      scales to the MAP estimate (100 kPa) - neither 0 nor the display.
  And a VALID reading of each still reads through (no fault bit).

NEGATIVE CONTROL: V97 dev (E3D11C66) - the display value everywhere - must
FAIL. Pure alpha-N's independence of MAP: me711_engine_control_proof.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

CONTROL_STEM = "HaniCore_ME711_v97_dev"
ERR_CLT, ERR_MAP, ERR_IAT = 0x0001, 0x0002, 0x0200
FAULT_TEMP_DC = (-40 + 1000) * 10       # ENG_FAULT_TEMP_DC, 10*C + 10000
WIN = 0x380000 + 0x7100                 # TGT_EXTRAM_BASE + TGT_RAM_S5500WIN
MAP_AN = 14                             # cavity 101 = main CPU AN14
CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += 0 if ok else 1
    print("  [%s] %-62s %s" % ("PASS" if ok else "FAIL", name, detail))


def degc(dc):
    return (dc - 10000) / 10.0


def main_one(stem):
    os.environ["HANICORE_ME711_STEM"] = stem
    import me711_config_state_test as T
    import me711_preset_apply_proof as AP
    print("=== sensor fallbacks - %s ===" % stem)
    r = T.boot()
    r.publish_on_service = True     # sensors as accepted samples (T.Rig)
    AP.press_apply(r, 3)
    AP.service(r)
    r("hc_hal_init", steps=5_000_000)
    r("eng_init", steps=5_000_000)
    r("hc_route_service", steps=5_000_000)
    # displacementCc is RESTART_REQUIRED: APPLY stages it and only a Burn
    # promotes it. Without it every air mass is 0 and the
    # density / no-air checks below would pass on nothing - put the AWT's
    # 1781 cc into ACTIVE directly.
    r("hc_cal_set_u16", T.d(T._gen, "CFG_U_DISPLACEMENT_CC"), 1781)
    adc = T.sym("adc_raw") & 0xFFFF
    base = r.g8("hc_s5500_base")
    r.m.w16(T.sym("hc_s5500_snaps") & 0xFFFF, 100)

    def win(ch, raw):
        i = 4 + ch - base
        r.m.w16(WIN + 2 * i, ((ch & 0xF) << 12) | (raw & 0x3FF))

    def g(name):
        try:
            return r.g16(name)
        except SystemExit:
            return None

    def state(clt=923, iat=541, map_raw=400, passes=300):
        win(0, clt)
        win(1, iat)
        for ch, v in ((8, 150), (9, 75), (1, 155), (3, 866), (5, 646),
                      (MAP_AN, map_raw)):
            r.m.w16(adc + 2 * ch, v)
        for _ in range(passes):          # the filters settle
            r("eng_service", steps=5_000_000)
        return {k: g(k) for k in ("eng_sensor_err", "eng_clt_dc",
                                  "eng_clt_meas_dc", "eng_iat_dc",
                                  "eng_map_kpa_x10", "eng_air_mg_x10",
                                  "eng_rl_x10", "eng_warmup_pct")}

    ok = state()
    check("baseline: the model computes air (the checks below are not "
          "vacuous)", (ok["eng_air_mg_x10"] or 0) > 0,
          "air %.1f mg" % ((ok["eng_air_mg_x10"] or 0) / 10))
    check("baseline: CLT, IAT and MAP all valid",
          not ok["eng_sensor_err"] & (ERR_CLT | ERR_IAT | ERR_MAP),
          "err 0x%04X, CLT %.1f C, IAT %.1f C, MAP %.1f kPa"
          % (ok["eng_sensor_err"], degc(ok["eng_clt_dc"]),
             degc(ok["eng_iat_dc"]), ok["eng_map_kpa_x10"] / 10.0))

    # ------------------------------------------------------------ coolant --
    s = state(clt=1015)
    check("CLT open (1015): CLT fault bit set", bool(s["eng_sensor_err"] & ERR_CLT),
          "err 0x%04X" % s["eng_sensor_err"])
    check("...DISPLAYED coolant (OCH 130) = -40.0 C",
          s["eng_clt_meas_dc"] == FAULT_TEMP_DC,
          "%s C" % (degc(s["eng_clt_meas_dc"]) if s["eng_clt_meas_dc"] is not None
                    else "n/a"))
    check("...CONTROL coolant (OCH 780, every model) = -40.0 C",
          s["eng_clt_dc"] == FAULT_TEMP_DC, "%.1f C" % degc(s["eng_clt_dc"]))
    check("...not the old 80 C warm-engine substitute",
          abs(degc(s["eng_clt_dc"]) - 80.0) > 1.0)
    check("...warm-up uses NO enrichment on a failed sensor (rusEFI "
          "getCltFuelCorrection = 1.0), not the -40 C point",
          s["eng_warmup_pct"] == 100 and (ok["eng_warmup_pct"] or 0) > 100,
          "warm-up %s %% (valid ~15 C: %s %%)"
          % (s["eng_warmup_pct"], ok["eng_warmup_pct"]))

    # --------------------------------------------------------- intake air --
    s = state(iat=1020)
    check("IAT open (1020): IAT fault bit set", bool(s["eng_sensor_err"] & ERR_IAT),
          "err 0x%04X" % s["eng_sensor_err"])
    check("...DISPLAYED = CONTROL intake air (OCH 132) = -40.0 C",
          s["eng_iat_dc"] == FAULT_TEMP_DC, "%.1f C" % degc(s["eng_iat_dc"]))
    check("...not the old 20 C / iatDefault substitute",
          abs(degc(s["eng_iat_dc"]) - 20.0) > 1.0)
    want = ok["eng_air_mg_x10"] * (273.15 + degc(ok["eng_iat_dc"])) / 273.15
    check("...the charge model uses 0 C (rusEFI getTCharge): air x T/273 K",
          ok["eng_air_mg_x10"] > 0
          and abs(s["eng_air_mg_x10"] - want) <= max(3, want * 0.02),
          "air %.1f mg (valid %.1f C: %.1f mg, expected %.1f)"
          % (s["eng_air_mg_x10"] / 10, degc(ok["eng_iat_dc"]),
             ok["eng_air_mg_x10"] / 10, want / 10))

    # ----------------------------------------------------------- manifold --
    for raw in (1023, 0):
        s = state(map_raw=raw)
        check("MAP at a rail (%d): MAP fault bit set" % raw,
              bool(s["eng_sensor_err"] & ERR_MAP), "err 0x%04X" % s["eng_sensor_err"])
        check("...DISPLAYED = CONTROL MAP (OCH 134) = 0 kPa",
              s["eng_map_kpa_x10"] == 0, "%.1f kPa" % (s["eng_map_kpa_x10"] / 10))
        # the AWT preset: alpha-N x inlet pressure. The fuel's pressure is
        # the MAP ESTIMATE table (100 kPa at the first rpm column) - the
        # air scales by estimate / measured, never to 0 and never shown.
        want = ok["eng_air_mg_x10"] * 1000.0 / ok["eng_map_kpa_x10"]
        check("...the FUEL uses the MAP estimate (100 kPa): air x 100 / p",
              abs(s["eng_air_mg_x10"] - want) <= max(3, want * 0.02),
              "air %d (valid %d at %.1f kPa, expected %.0f)"
              % (s["eng_air_mg_x10"], ok["eng_air_mg_x10"],
                 ok["eng_map_kpa_x10"] / 10, want))

    # ------------------------------------------------- recovery, both ways --
    s = state()
    check("all three valid again: no fault bit, real values back",
          not s["eng_sensor_err"] & (ERR_CLT | ERR_IAT | ERR_MAP)
          and s["eng_map_kpa_x10"] > 0 and s["eng_clt_dc"] != FAULT_TEMP_DC,
          "err 0x%04X" % s["eng_sensor_err"])
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
    print("SENSOR FALLBACK PROOF %s" % ("PASSES" if ok else "FAILS"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
