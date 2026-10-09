#!/usr/bin/env python3
r"""
me711_alphan_start_proof.py - the AWT first start does NOT need a manifold
pressure sensor. Run the linked image's own eng_service() in c167sim.

    py tests\firmware\engine\me711_alphan_start_proof.py

WHY. The stock AWT pressure sensor on cavity 101 is DSL = pvdkdsl_w, pressure
BEFORE the throttle (A2L), so speed density on it cannot see throttling. The
"VAG 1.8T DBW (AWT)" preset therefore selects load source THROTTLE - rusEFI's
LM_ALPHA_N concept (VE by rpm x TPS, VE = cylinder filling relative to ideal;
ignition/AFR follow the same load) - with a VE table solved from the stock ME7
throttle model (hanicore_presets.py, V89 block).

WHAT THIS RUNS, against the image under test:
  1. the preset through the real '!E' path (hcts_target_cmd + service);
  2. TPS endpoints written as the Grab would, the routing bound;
  3. eng_service() at cranking, idle and part load with the pressure
     before the throttle VALID (~100 kPa - the density term);
  4. the pressure forced INVALID: it READS 0 kPa (the fault value), and
     V98 fuels from the MAP ESTIMATE table (rusEFI mapEstimateTable; the
     AWT's is 100 kPa off boost) - the same fuel as a valid ~100 kPa, never
     zero and never displayed (me711_sensor_fallback_proof owns the rule);
     cranking fuels from the cranking mass curve;
  5. the speed-density path (load source MAP) to prove it is untouched.

NOT PHYSICALLY VERIFIED. c167sim executes the firmware; the engine is not
simulated - the fuel request is checked against the model it came from.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_config_state_test as T     # noqa: E402
import me711_preset_apply_proof as A    # noqa: E402  press_apply/service/off
import me711_image as PI                # noqa: E402

off = A.off
TPS1_CH, TPS2_CH, BATT_CH, MAP_CH = 1, 3, 5, 14   # hctarget.h TGT_ADC_*_CH, AN14
TPS_MIN, TPS_MAX = 100, 900                       # a Grab-like calibration
FAILS = CHECKS = 0
WIN = 0x380000 + 0x7100                 # TGT_EXTRAM_BASE + TGT_RAM_S5500WIN
CLT_WARM, IAT_RAW = 533, 541            # AWT curve: 80.0 C; ~13 C


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    FAILS += not ok
    print("  [%s] %-60s %s" % ("PASS" if ok else "FAIL", name, detail))


def w16page(r, o, v):
    r.write(o, (v >> 8) & 0xFF)
    r.write(o + 1, v & 0xFF)


def adc(r, ch, v):
    r.m.w16((T.sym("adc_raw") & 0xFFFF) + 2 * ch, v)


def tps_raw(pct):
    return int(round(TPS_MIN + (TPS_MAX - TPS_MIN) * pct / 100.0))


def window(r, ch, raw):
    """An ASIC-tagged S5500 sample (CLT AN0 / IAT AN1), as the fallback
    proof writes it. V97: an ABSENT coolant sensor reads -40 C (cold-start
    enrichment), so this gate feeds a WARM, valid one - it tests the alpha-N
    air model, not the warm-up curve."""
    i = 4 + ch - r.g8("hc_s5500_base")
    r.m.w16(WIN + 2 * i, ((ch & 0xF) << 12) | (raw & 0x3FF))


def run(r, rpm, tps_pct, map_raw, passes=160):   # >= 5 time constants of filt() + accel decay
    window(r, 0, CLT_WARM)
    window(r, 1, IAT_RAW)
    r.m.w16(T.sym("hc_s5500_snaps") & 0xFFFF, 100)
    adc(r, TPS1_CH, tps_raw(tps_pct))
    adc(r, TPS2_CH, tps_raw(tps_pct))
    adc(r, MAP_CH, map_raw)
    r.m.w16(T.sym("trg_rpm") & 0xFFFF, rpm)
    for _ in range(passes):
        r("eng_service", steps=3_000_000)
    return dict(ti=r.g16("eng_ti_base_us"), load=r.g16("eng_load"),
                air=r.g16("eng_air_mg_x10"), mapk=r.g16("eng_map_kpa_x10"),
                err=r.g16("eng_sensor_err"), crank=r.g8("eng_cranking"))


def setup():
    r = T.boot()
    r.publish_on_service = True     # sensors as accepted samples (T.Rig)
    A.press_apply(r, A.PRESET_18T)
    A.service(r)
    r("hc_hal_init", steps=5_000_000)   # the S5500 window path (CLT/IAT)
    v = A.och(r, 764)
    check("the AWT preset applied through '!E'", v == 0x0301, "0x%04X" % v)
    check("  ...load source = THROTTLE (alpha-N)",
          r.active(off("CAL_LOAD_SOURCE")) == 1)
    for o in (off("CAL_TPS1_MIN"), off("CAL_TPS2_MIN")):
        w16page(r, o, TPS_MIN)
    for o in (off("CAL_TPS1_MAX"), off("CAL_TPS2_MAX")):
        w16page(r, o, TPS_MAX)
    r("hc_cfg_mgr_apply_now", 0)
    fs = u16a(r, off("CFG_ADC_BATT_FS_DV"))
    adc(r, BATT_CH, int(135 * 1023 / fs) if fs else 600)   # ~13.5 V
    r("hc_route_service")
    # KEY CYCLE. displacementCc is RESTART-required: APPLY puts 1781 in
    # DESIRED, and it reaches the runtime after Burn + key-off/on - the
    # operator's step 5. Emulated here by writing ACTIVE, which is what the
    # boot does with the burned page.
    d = off("CFG_U_DISPLACEMENT_CC")
    check("  ...displacement 1781 staged in DESIRED, restart pending",
          (r.desired(d) << 8 | r.desired(d + 1)) == 1781
          and r.g8("hc_cfg_restart_pending") == 1)
    r("hc_cal_set_u16", d, 1781)
    A.install_test_fuel(r)
    r("eng_init")
    return r


def u16a(r, o):
    return (r.active(o) << 8) | r.active(o + 1)


def main() -> int:
    print("=== HaniCore ME7.1.1 - AWT first start without manifold pressure ===")
    print("  image   %s\n  sha256  %s\n" % (PI.image().name, PI.sha256()))
    r = setup()
    ERR_MAP = 0x0002

    # ---------------------------------------------------- cranking
    c = run(r, 250, 0, 0)
    check("cranking at 250 rpm, pressure INVALID: the cranking table fuels",
          c["crank"] == 1 and c["ti"] > 0 and (c["err"] & ERR_MAP),
          "ti %d us, cranking %d, err 0x%04X" % (c["ti"], c["crank"], c["err"]))

    # ---------------------------------------------------- idle / low TPS
    res = {}
    for rpm in (900, 2000):
        for tps in (0, 2, 4, 10, 30):
            res[(rpm, tps)] = run(r, rpm, tps, 378)   # 99.9 kPa, valid
    i2 = res[(900, 2)]
    check("idle 900 rpm / 2 % TPS, pressure ~100 kPa: running fuel > 0",
          i2["crank"] == 0 and i2["ti"] > 0 and not (i2["err"] & ERR_MAP),
          "ti %d us, load %d (0.1 %%), air %.1f mg, p %.1f kPa"
          % (i2["ti"], i2["load"], i2["air"] / 10, i2["mapk"] / 10))
    # the model it came from: rl 17.5 % at 800 rpm/2 %, ~15 % at 950 rpm ->
    # ~85-100 mg/cyl, 1.4-2.2 ms at 301 cc/min (plus warm-up if CLT is cold)
    check("  ...and it is an IDLE-SIZED request (0.8..4.0 ms)",
          800 <= i2["ti"] <= 4000, "%d us" % i2["ti"])
    check("  ...the load IS the throttle (eng_load 0.1 % == 20)",
          abs(i2["load"] - 20) <= 1, str(i2["load"]))
    for rpm in (900, 2000):
        tis = [res[(rpm, t)]["ti"] for t in (0, 2, 4, 10, 30)]
        check("fuel rises with TPS at %d rpm (0/2/4/10/30 %%)" % rpm,
              all(a < b for a, b in zip(tis, tis[1:])), str(tis))
    # (A check that a small throttle fuels less per cycle at 2000 than at 900
    # rpm asserted the stock AWT VE table's throttle-limited shape. The
    # preset no longer ships that table; the VE lookup itself is
    # me711_table_order_proof.)
    check("closed throttle still fuels (leak air), not zero",
          res[(900, 0)]["ti"] > 0, "%d us" % res[(900, 0)]["ti"])

    # ------------------------- pressure INVALID: 0 kPa, no running fuel
    bad = run(r, 900, 2, 0)
    good = res[(900, 2)]
    # the air the same cell gives at exactly 100 kPa (the sensor transfer is
    # the page's, so raw 400 is not necessarily 100 kPa)
    want = good["air"] * 1000 // max(1, good["mapk"])
    check("pressure INVALID at idle: reads 0 kPa, fuels from the 100 kPa "
          "estimate (V98)",
          (bad["err"] & ERR_MAP) and bad["mapk"] == 0 and bad["crank"] == 0
          and abs(bad["air"] - want) <= max(3, want // 50),
          "air %.1f mg (valid %.1f kPa: %.1f mg -> %.1f mg at 100 kPa), "
          "ti %d us, p %.1f kPa"
          % (bad["air"] / 10, good["mapk"] / 10, good["air"] / 10, want / 10,
             bad["ti"], bad["mapk"] / 10))
    boost = run(r, 2000, 30, 530)          # ~140 kPa before the throttle
    check("pressure before throttle 140 kPa scales the charge up (boost)",
          boost["ti"] > res[(2000, 30)]["ti"] * 1.25,
          "%d vs %d us" % (boost["ti"], res[(2000, 30)]["ti"]))

    # ------------------------------ speed density untouched (MAP load)
    r.write(off("CAL_LOAD_SOURCE"), 0)
    r("hc_cfg_mgr_apply_now", 0)
    sd_lo = run(r, 2000, 30, 150)          # ~40 kPa
    sd_hi = run(r, 2000, 30, 378)          # ~100 kPa
    check("speed density (load MAP) still follows manifold pressure",
          r.active(off("CAL_LOAD_SOURCE")) == 0
          and 0 < sd_lo["ti"] < sd_hi["ti"],
          "40 kPa %d us < 100 kPa %d us" % (sd_lo["ti"], sd_hi["ti"]))

    print("\n  %d/%d checks passed" % (CHECKS - FAILS, CHECKS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
