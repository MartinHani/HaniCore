#!/usr/bin/env python3
r"""
me711_engine_control_proof.py - the V98 engine-control layer (hcengctl711.c and
hcengine.c runtime_tail), executed in c167sim from the LINKED image over the
applied VAG 1.8T AWT preset.

    py tests\firmware\engine\me711_engine_control_proof.py            the image under test
    py tests\firmware\engine\me711_engine_control_proof.py --control  + V97 dev, which must FAIL

WHAT IT PROVES (each a rusEFI semantic, the maintainer's design records):
  1. NAMED FIRING ORDER: hc_fo_position(1-3-4-2) places cylinders 1..4 at
     positions 0, 3, 1, 2 - the table the scheduler's geometry uses.
  2. TARGET LAMBDA: the AWT cell 147 is lambda 1.000 (targetLambda, OCH
     1154), on the lambda table's OWN axes.
  3. SIGNED TIMING: an ignition cell below the 20-degree offset gives
     timing AFTER TDC (eng_adv_x10 < 0), not a wrapped 6553 degrees.
  4. CRANKING FUEL IS A MASS: the cranking pulse halves when the injector
     flow doubles (V97's microsecond table did not move).
  5. DFCO NEEDS VALID INPUTS: pedal released above the cut rpm, warm ->
     fuel cut; the same with BOTH throttle tracks failed -> NO cut (bug B4:
     a failed TPS read 0 % and cut the fuel).
  6. PURE ALPHA-N IS INDEPENDENT OF MAP: load source 2, the pressure
     sensor failed -> the same air as with it valid.
  7. CLOSED LOOP (STFT): lambda 0.10 above the target trims fuel UP to
     the region's limit, 0.10 below trims it DOWN, a dead sensor (0)
     drops the trim to 0 (never trims from a sensor that is not READY).
  8. INJECTION TIMING: mode 0 places the single angle, mode 1 the rpm x
     load table (rusEFI injectionPhase) - the value the scheduler reads.
  9. VE ABOVE 127.5 %: one count = 1 %, a 150 % table is 150.0 % at the
     runtime and doubles the air of a 75 % table (V97 capped at 127.5 %).

NOT PHYSICALLY VERIFIED. The engine is not simulated; each check compares
the firmware against the rule it implements.
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
CHECKS = FAILS = 0
ERR_TPS = 0x0004 | 0x0008               # hcengine.h ENG_ERR_TPS1 | TPS2


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += 0 if ok else 1
    print("  [%s] %-64s %s" % ("PASS" if ok else "FAIL", name, detail))


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def och(r, at):
    """An OCH word, at the address hctarget.h gives (me711_image.och_addr)."""
    import me711_image as _PI
    a = _PI.och_addr(at)
    return (r.m.r8(a) << 8) | r.m.r8(a + 1)


def main_one(stem):
    os.environ["HANICORE_ME711_STEM"] = stem
    import me711_config_state_test as T
    import me711_alphan_start_proof as AS
    import me711_preset_apply_proof as AP
    off = AS.off
    print("=== V98 engine control - %s ===" % stem)
    r = AS.setup()

    def has(name):
        try:
            T.sym(name)
            return True
        except SystemExit:
            return False

    def tick(r_, rpm, tps, map_raw, passes):
        """eng_service passes with T1 advanced 40 ms each (the time base of
        the engine-control layer and the transient model; 16 bits at 1250
        ticks/ms wrap at 52 ms) - the sim does not run T1 by itself."""
        AS.window(r_, 0, AS.CLT_WARM)
        AS.window(r_, 1, AS.IAT_RAW)
        r_.m.w16(T.sym("hc_s5500_snaps") & 0xFFFF, 100)
        AS.adc(r_, AS.TPS1_CH, AS.tps_raw(tps) if tps is not None else 1023)
        AS.adc(r_, AS.TPS2_CH, AS.tps_raw(tps) if tps is not None else 1023)
        AS.adc(r_, AS.MAP_CH, map_raw)
        r_.m.w16(T.sym("trg_rpm") & 0xFFFF, rpm)
        for _ in range(passes):
            r_.m.sfr[0xFE52] = (r_.m.sfr.get(0xFE52, 0) + 50000) & 0xFFFF
            r_("eng_service", steps=3_000_000)
        return dict(ti=r_.g16("eng_ti_base_us"), air=r_.g16("eng_air_mg_x10"),
                    err=r_.g16("eng_sensor_err"), cut=r_.g16("eng_fuelcut"),
                    adv=s16(r_.g16("eng_adv_x10")), crank=r_.g8("eng_cranking"))

    # ---------------------------------------------------- 1 firing order
    if has("hc_fo_position"):
        pos = [r.callb("hc_fo_position", 1, c, 4) for c in range(4)]
    else:
        pos = None
    check("1-3-4-2 places cylinders 1..4 at positions 0, 3, 1, 2",
          pos == [0, 3, 1, 2], str(pos))

    # ---------------------------------------------------- 2 target lambda
    run = tick(r, 2000, 30, 378, 60)
    if has("hc_ec_publish"):
        r("hc_ec_publish", 0)
        lam_t = och(r, 1154)
    else:
        lam_t = None
    check("target lambda cell 147 = lambda 1.000 (OCH 1154)",
          lam_t == 1000, str(lam_t))

    # ---------------------------------------------------- 3 signed timing
    ign = off("CAL_IGN_MAP")
    saved = [r.active(ign + i) for i in range(256)]
    for i in range(256):
        r("hc_cal_set_u8", ign + i, 30)          # (30 - 40) x 0.5 = -5.0 deg
    run = tick(r, 2000, 30, 378, 20)
    check("ignition cell 30 = -5.0 deg: timing AFTER TDC, signed",
          -60 <= run["adv"] <= -40, "eng_adv_x10 %d" % run["adv"])
    for i in range(256):
        r("hc_cal_set_u8", ign + i, saved[i])

    # ---------------------------------------------------- 4 cranking mass
    flow_o = off("CFG_U_INJ_FLOW_CCMIN")
    flow = (r.active(flow_o) << 8) | r.active(flow_o + 1)
    c1 = tick(r, 250, 0, 378, 20)
    r("hc_cal_set_u16", flow_o, flow * 2)
    c2 = tick(r, 250, 0, 378, 20)
    r("hc_cal_set_u16", flow_o, flow)
    check("cranking: the pulse halves when the injector flow doubles (mass)",
          c1["crank"] == 1 and c1["ti"] > 0
          and abs(c2["ti"] * 2 - c1["ti"]) <= c1["ti"] // 200,
          "%d cc/min %d us, %d cc/min %d us" % (flow, c1["ti"], flow * 2,
                                                c2["ti"]))

    # ---------------------------------------------------- 5 DFCO validity
    r("hc_cal_set_u16", off("CAL_OVERRUN_RPM"), 1800)
    r("hc_cal_set_u16", off("CAL_OVERRUN_RESUME"), 1400)
    r("hc_cal_set_u16", off("CAL_OVERRUN_TPS_X10"), 20)
    # rusEFI/Speeduino: no DFCO during after-start - let it decay first
    tick(r, 3000, 30, 378, 200)                # running, pedal pressed
    d_ok = tick(r, 3000, 0, 378, 60)           # released: cut after delay
    check("DFCO: released above the cut rpm, warm -> fuel cut",
          bool(d_ok["cut"] & 1), "cut 0x%04X" % d_ok["cut"])
    d_bad = tick(r, 3000, None, 378, 60)       # both throttle tracks failed
    check("DFCO: BOTH throttle tracks failed -> NO fuel cut (bug B4)",
          not (d_bad["cut"] & 1) and (d_bad["err"] & ERR_TPS) == ERR_TPS,
          "cut 0x%04X, err 0x%04X" % (d_bad["cut"], d_bad["err"]))
    # The pressure ceiling only means "coasting" on a MANIFOLD sensor. With a
    # pre-throttle (charge) sensor under Boosted Alpha-N it must not block
    # DFCO, whatever the legacy load source byte holds; a manifold sensor
    # above the ceiling must.
    def dfco_with(model, role, policy):
        for n, v in (("CFG_U_FUEL_MODEL", model), ("CFG_U_PRESSURE_ROLE", role),
                     ("CFG_U_DENSITY_POLICY", policy), ("CAL_LOAD_SOURCE", 0),
                     ("CFG_U_DFCO_MAP_MAX", 50)):
            r("hc_cal_set_u8", off(n), v)
        tick(r, 3000, 30, 378, 200)
        return tick(r, 3000, 0, 378, 60)
    saved_m = [r.active(off(n)) for n in ("CFG_U_FUEL_MODEL", "CFG_U_PRESSURE_ROLE",
               "CFG_U_DENSITY_POLICY", "CAL_LOAD_SOURCE", "CFG_U_DFCO_MAP_MAX")]
    if has("hc_load_select"):
        d_ch = dfco_with(3, 2, 1)
        d_mf = dfco_with(2, 1, 1)
    else:
        d_ch = d_mf = {"cut": 0}
    check("DFCO: a charge-pressure sensor never blocks overrun cut",
          bool(d_ch["cut"] & 1), "cut 0x%04X" % d_ch["cut"])
    check("DFCO: a manifold sensor above the ceiling does",
          not (d_mf["cut"] & 1), "cut 0x%04X" % d_mf["cut"])
    for n, v in zip(("CFG_U_FUEL_MODEL", "CFG_U_PRESSURE_ROLE",
                     "CFG_U_DENSITY_POLICY", "CAL_LOAD_SOURCE",
                     "CFG_U_DFCO_MAP_MAX"), saved_m):
        r("hc_cal_set_u8", off(n), v)
    r("hc_cal_set_u16", off("CAL_OVERRUN_RPM"), 0)

    # ---------------------------------------------------- 6 pure alpha-N
    r("hc_cal_set_u8", off("CAL_LOAD_SOURCE"), 2)
    tick(r, 2000, 30, 378, 160)                # the filters settle
    a_ok = tick(r, 2000, 30, 378, 20)
    a_bad = tick(r, 2000, 30, 1023, 20)
    check("pure alpha-N: a failed pressure sensor leaves the air unchanged",
          a_ok["air"] > 0 and (a_bad["err"] & 0x0002)
          and a_bad["air"] == a_ok["air"],
          "air %.1f / %.1f mg, err 0x%04X" % (a_ok["air"] / 10,
                                               a_bad["air"] / 10, a_bad["err"]))
    r("hc_cal_set_u8", off("CAL_LOAD_SOURCE"), 1)

    # ---------------------------------------------------- 9 VE range + step
    # real TunerStudio 2026-10-01: the VE byte stopped at 127.5 % (0.5 % a
    # count); V98 made it 1 % a count, a 20..100 % step at the 1..5 %
    # closed-throttle cells of the AWT alpha-N table. V98r2: u16, 0.1 % a
    # count - 7.5 %, 85.0 %, 150.0 % and the 400.0 % limit reach the
    # runtime exactly, and the air scales with VE.
    vt = off("CAL_FUEL_MAP")
    saved_ve = [r.active(vt + i) for i in range(512)]

    def ve_all(raw):
        for i in range(256):
            r("hc_cal_set_u16", vt + 2 * i, raw)
    ve_all(1500)
    # MAP recovers from step 6's fault: the filter steps once per tick()
    # call (one S5500 snapshot each), not once per pass
    for _ in range(40):
        tick(r, 2000, 30, 378, 2)
    v150 = tick(r, 2000, 30, 378, 20)
    ve150 = r.g16("eng_ve_x10") if has("eng_ve_x10") else None
    got = {}
    for raw in (75, 850, 750, 4000, 9999):
        ve_all(raw)
        got[raw] = (tick(r, 2000, 30, 378, 20)["air"],
                    r.g16("eng_ve_x10") if has("eng_ve_x10") else None)
    for i in range(512):
        r("hc_cal_set_u8", vt + i, saved_ve[i])
    check("VE 150.0 % (raw 1500): runtime VE 150.0 %, air 2x the 75.0 % table",
          ve150 == 1500 and got[750][0] > 0
          and abs(v150["air"] - 2 * got[750][0]) <= 2,
          "eng_ve_x10 %s, air %.1f / %.1f mg" % (ve150, v150["air"] / 10,
                                                 got[750][0] / 10))
    check("VE 7.5 % / 85.0 % / 400.0 % reach the runtime at 0.1 %; a raw "
          "cell past the field limit is clamped to 400.0 %",
          [got[k][1] for k in (75, 850, 4000, 9999)] == [75, 850, 4000, 4000]
          and abs(got[75][0] * 20 - v150["air"]) <= 20,
          "eng_ve_x10 %s, air at 7.5 %% %.1f mg"
          % ([got[k][1] for k in (75, 850, 4000, 9999)], got[75][0] / 10))

    # ---------------------------------------------------- 8 injection timing
    # the angle the scheduler places (me711_sequential_proof models it):
    # mode 0 the single angle, mode 1 the rpm x load table (rusEFI
    # injectionPhase)
    if has("dry_inj_phase_x10"):
        so = off("CFG_INJ_START_DEG_X10")
        single = (r.active(so) << 8) | r.active(so + 1)
        r("hc_cal_set_u8", off("CFG_U_INJ_PHASE_MODE"), 0)
        tick(r, 2000, 30, 378, 3)
        ph0 = r.g16("dry_inj_phase_x10")
        tb = off("CFG_U_INJ_PHASE")
        for i in range(64):
            r("hc_cal_set_u16", tb + 2 * i, 3000)
        r("hc_cal_set_u8", off("CFG_U_INJ_PHASE_MODE"), 1)
        tick(r, 2000, 30, 378, 3)
        ph1 = r.g16("dry_inj_phase_x10")
        r("hc_cal_set_u8", off("CFG_U_INJ_PHASE_MODE"), 0)
    else:
        single = ph0 = ph1 = None
    check("injection angle: single %s -> %s; table 300.0 deg -> %s"
          % (single, ph0, ph1), ph0 == single and ph1 == 3000)

    # ---------------------------------------------------- 7 closed loop
    # wb[0].lambda: the address hc_io_lambda itself reads (MOV R4,[R4+#a])
    import me711_image as PI
    img = PI.image().read_bytes()
    a = T.sym("hc_io_lambda") - 0x800000
    code = img[a:a + 48]

    def first(op):
        """the first `op Rd(=R4/RL4),[Rw+#data16]` - any base register
        (2026-10-12: Keil indexes wb[] through R5 since the valid check;
        the gate looked only for the R4 form and its closed-loop part was
        skipped)"""
        for k in range(len(code) - 3):
            if code[k] == op and (code[k + 1] >> 4) in (4, 8):
                return code[k + 2] | code[k + 3] << 8
        return None

    def phys(near):                            # DPPn page + offset
        return (r.m.sfr.get(0xFE00 + 2 * (near >> 14), 0) * 0x4000
                + (near & 0x3FFF))
    near = first(0xD4)                         # MOV  R4,[Rw+#wb.lambda]
    vnear = first(0xF4)                        # MOVB RL4,[Rw+#wb.valid]
    lam_addr = phys(near) if near is not None else None
    probe = None
    if lam_addr is not None:
        if vnear is not None:
            r.m.w8(phys(vnear), 1)             # hc_io_lambda needs valid == 1
        r.m.w16(lam_addr, 1234)
        probe = r("hc_io_lambda", 0)
    check("the lambda the closed loop reads is addressable (wb[0].lambda)",
          probe == 1234, "0x%04X -> %s" % (lam_addr or 0, probe))
    if probe == 1234:
        for o, v in (("CFG_U_STFT_ENABLE", 1), ("CFG_U_STFT_DELAY", 0),
                     ("CFG_U_STFT_AFTER_DFCO", 0), ("CFG_U_STFT_AFTER_AE", 0),
                     ("CFG_U_STFT_OVR_LOAD", 5)):       # 20 % = cruise
            r("hc_cal_set_u8", off(o), v)
        cruise = 3                                   # [idle, ovr, pwr, cruise]
        lim = r.active(off("CFG_U_STFT_ADD") + cruise)
        limr = r.active(off("CFG_U_STFT_REMOVE") + cruise)
        # 20 % throttle: the AWT target is lambda 1.00 there (0.82..0.88
        # from 40 %) - lean and rich are judged against the PUBLISHED target
        tick(r, 2500, 20, 378, 100)
        r.m.w16(lam_addr, 0)
        base = tick(r, 2500, 20, 378, 40)
        r("hc_ec_publish", 0)
        tgt = och(r, 1154)
        r.m.w16(lam_addr, tgt + 100)                  # lean: add fuel
        lean = tick(r, 2500, 20, 378, 120)
        r("hc_ec_publish", 0)
        t_lean = s16(och(r, 1156))
        check("STFT: lambda target + 0.10 -> trim UP to the region limit",
              abs(t_lean - lim * 10) <= 2 and lean["ti"] > base["ti"],
              "target %.3f, trim %+.1f %% (limit %d %%), ti %d -> %d us"
              % (tgt / 1000, t_lean / 10, lim, base["ti"], lean["ti"]))
        r.m.w16(lam_addr, 0)                          # sensor not READY
        tick(r, 2500, 20, 378, 5)
        r("hc_ec_publish", 0)
        t_dead = s16(och(r, 1156))
        check("STFT: a sensor that is not a measurement drops the trim to 0",
              t_dead == 0, "trim %+.1f %%" % (t_dead / 10))
        r.m.w16(lam_addr, tgt - 100)                  # rich: remove fuel
        tick(r, 2500, 20, 378, 120)
        r("hc_ec_publish", 0)
        t_rich = s16(och(r, 1156))
        stw = och(r, 1200)
        check("STFT: lambda target - 0.10 -> trim DOWN to the region limit",
              abs(t_rich + limr * 10) <= 2,
              "trim %+.1f %% (limit -%d %%), state %d region %d, cut 0x%04X"
              % (t_rich / 10, limr, stw & 255, stw >> 8, r.g16("eng_fuelcut")))

    # ------------------------------------------- 10 injector pressure (2026-10-15)
    # rusEFI injectorCompensationMode: the flow scales with sqrt(pressure
    # across the injector / its test pressure); none = as rated.
    if has("hc_aux_fuel_kpa"):
        if lam_addr is not None:
            r.m.w16(lam_addr, 0)                      # no closed-loop trim
        mo, ro = off("CFG_U_INJ_PRESS_MODE"), off("CFG_U_FUEL_REG_KPA")
        r("hc_cal_set_u16", off("CFG_U_INJ_REF_KPA"), 300)

        def ti_at(mode, reg):
            r("hc_cal_set_u8", mo, mode)
            r("hc_cal_set_u16", ro, reg)
            return tick(r, 2500, 20, 378, 30)["ti"]
        t0 = ti_at(0, 330)
        t1 = ti_at(1, 330)
        t2 = ti_at(1, 270)
        t3 = ti_at(3, 330)
        r("hc_cal_set_u8", mo, 1)
        r("hc_cal_set_u16", ro, 300)
        q1, q2, q3 = t1 / t0, t2 / t0, t3 / t0
        check("inj pressure: none -> as rated; regulator 330/300 kPa -> "
              "x sqrt(300/330) = 0.953",
              abs(q1 - 0.9535) <= 0.01, "ti %d -> %d us (x%.4f)" % (t0, t1, q1))
        check("inj pressure: regulator 270/300 kPa -> x sqrt(300/270) = 1.054",
              abs(q2 - 1.0541) <= 0.01, "ti %d -> %d us (x%.4f)" % (t0, t2, q2))
        check("inj pressure: sensed rail, no sensor -> the fixed-rail value "
              "(charge sensor: manifold = ambient)",
              abs(q3 - q1) <= 0.005, "x%.4f vs x%.4f" % (q3, q1))
    else:
        check("inj pressure compensation present (hc_aux_fuel_kpa)", False)
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
    print("\nCONTROL: %s %s" % (CONTROL_STEM, "FAILS, as it must" if rcc
                                              else "PASSES - gate blind"))
    print("V98 ENGINE PROOF %s" % ("PASSES" if ok else "FAILS"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
