#!/usr/bin/env python3
r"""me711_ign_trim_dwell_proof.py - per-cylinder ignition trim and dwell by
rpm (2026-10-14) in the LINKED image (c167sim).

    py tests\firmware\engine\me711_ign_trim_dwell_proof.py [--control <bins dir>]

THE TRIM (rusEFI ignition trims, Speeduino sequential spark trims). The
scheduler can only DELAY a slot's event (hcknock711.c slot_ret[]), so a
signed trim is split: hc_ec_spark() advances every cylinder by the largest
trim (hc_ign_trim_off_x10) and slot_retard() retards each slot by the
largest minus its own.
  T1 on the sequential COP rig (me711_knock_proof.KnockRig, knock OFF, the
     advance held constant like the main loop would): trims +4.0 / 0 /
     -2.0 / 0 deg (cylinders 1..4) move the sparks AT THE COIL PINS later by
     0 / 4 / 6 / 4 deg against an untrimmed run (+-1.2 deg: the rig samples
     the pins at 1.2 deg steps, so 4.0 reads 4.8);
  T2 the global part: hc_ign_trim_off_x10() = +4.0 deg, and hc_ec_spark()
     (AWT page, running) returns 4.0 deg more than with no trims - so each
     cylinder ends at table + its own trim;
  T3 fixed-timing mode: no trim at all (offset 0, sparks as untrimmed).
THE DWELL (rusEFI sparkDwellRpmBins, Speeduino dwell map): the battery
curve's dwell times the rpm factor, through eng_service() - one store.
  D1 factor 100 % everywhere: eng_dwell_x100 is the battery curve's value;
  D2 factor 100/100/80/60/50/50 % at 1000..8000 rpm: at 3500 rpm 70 %
     (interpolated), at 9000 rpm 50 % (held);
  D3 cranking with a cranking dwell set: that value, factor ignored.
--control <bins dir>: an image without them (5248F4C9) must FAIL.
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
import me711_image as PI  # noqa: E402

CHECKS = FAILS = 0
TRIMS = (168, 128, 108, 128)          # +4.0, 0, -2.0, 0 deg
EXPECT_LATER = (0.0, 4.0, 6.0, 4.0)   # 4.0 - trim


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += 0 if ok else 1
    print("  [%s] %-64s %s" % ("PASS" if ok else "FAIL", name, detail))
    return ok


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def trim_rig():
    import me711_knock_proof as K
    print("\n--- T: the trim at the coil pins (sequential COP rig) ---")

    def run(trims, fixed=0):
        r = K.KnockRig(mode=0)
        for i, t in enumerate(trims):
            r.w8("CFG_U_IGN_TRIM", t, i)
        r.w8("CFG_U_TIMING_MODE", fixed)
        r.start(12)
        sp = {c: K.spark_phys(r, c, r.cum - 1440) for c in range(4)}
        return r, sp

    ref, s_ref = run((128,) * 4)
    tr, s_tr = run(TRIMS)
    moves = []
    for c in range(4):
        if s_ref[c] and s_tr[c]:
            moves.append(round(s_tr[c][-1] - s_ref[c][-1], 2))
        else:
            moves.append(None)
    check("T1 sparks later by 0 / 4 / 6 / 4 deg at the pins (+-1.2)",
          all(m is not None and abs(m - e) <= 1.2
              for m, e in zip(moves, EXPECT_LATER)), "moved %s" % moves)
    off = s16(tr.x.call("hc_ign_trim_off_x10"))
    check("T2 the global part: hc_ign_trim_off_x10 = +4.0 deg", off == 40,
          "%d" % off)
    fx, s_fx = run(TRIMS, fixed=1)
    same = all(s_fx[c] and s_ref[c]
               and abs(s_fx[c][-1] - s_ref[c][-1]) < 0.6 for c in range(4))
    off_fx = s16(fx.x.call("hc_ign_trim_off_x10"))
    check("T3 fixed timing: no trim (offset 0, sparks as untrimmed)",
          same and off_fx == 0, "offset %d" % off_fx)


def engine_side():
    import me711_config_state_test as T
    import me711_alphan_start_proof as AS
    print("\n--- T2 / D: hc_ec_spark and the dwell, AWT page ---")
    r = AS.setup()
    off = AS.off

    def page(name, v, i=0):
        r("hc_cal_set_u8", off(name) + i, v)

    def set_rpm(rpm):
        r.m.w16(T.sym("trg_rpm") & 0xFFFF, rpm)

    # T2: the trims as the knock module sees them need the scheduler's
    # geometry; the AWT page's (cylinder i on slot i+1) is installed here
    kn = 0x380000 + 0x1A00                 # TGT_RAM_KNOCK: slot_ret[9], geom_n
    if r.m.r8(kn + 9) == 0:
        r.m.w8(kn + 9, 4)
    set_rpm(2500)

    def spark():
        v = 0
        for _ in range(4):                 # let the rate limit settle
            v = s16(r("hc_ec_spark", 150, 0, steps=2_000_000))
        return v
    a0 = spark()
    for i, t in enumerate(TRIMS):
        page("CFG_U_IGN_TRIM", t, i)
    a1 = spark()
    for i in range(4):
        page("CFG_U_IGN_TRIM", 128, i)
    check("T2 hc_ec_spark: +4.0 deg with the trims (each cylinder: table + "
          "own trim after its slot retard)", a1 - a0 == 40,
          "%d -> %d" % (a0, a1))

    def dwell(rpm):
        set_rpm(rpm)
        r("eng_service", steps=6_000_000)
        return r.g16("eng_dwell_x100"), r.g8("eng_cranking")
    d100, cr = dwell(3500)
    batt = r("hc_cal_curve16", off("CAL_DWELL_BATT_AX"), off("CAL_DWELL_BATT_VAL"),
             8, r.g16("eng_batt_dv") * 10)        # at the battery eng_service read
    check("D1 factor 100 %: the battery curve's dwell", d100 == batt and cr == 0,
          "%d vs battery %d (cranking %d)" % (d100, batt, cr))
    for i, p in enumerate((100, 100, 80, 60, 50, 50)):
        r("hc_cal_set_u8", off("CFG_U_DWELL_RPM_PCT") + 2 * i, 0)
        r("hc_cal_set_u8", off("CFG_U_DWELL_RPM_PCT") + 2 * i + 1, p)
    d35, _ = dwell(3500)
    d90, _ = dwell(9000)
    check("D2 3500 rpm: 70 % (interpolated 80..60), 9000 rpm: 50 % (held)",
          abs(d35 - batt * 70 // 100) <= 1 and abs(d90 - batt // 2) <= 1,
          "%d / %d of %d" % (d35, d90, batt))
    cd = off("CFG_U_CRANK_DWELL_X100")
    r("hc_cal_set_u8", cd, 400 >> 8)
    r("hc_cal_set_u8", cd + 1, 400 & 0xFF)
    dc, cr = dwell(200)
    check("D3 cranking with a cranking dwell: that value (4.00 ms)",
          dc == 400 and cr == 1, "%d (cranking %d)" % (dc, cr))


def main() -> int:
    print("=== per-cylinder ignition trim and dwell by rpm ===")
    print("  image", PI.image())
    try:
        import me711_config_state_test as T
        T.sym("hc_ign_trim_off_x10")
    except SystemExit as e:
        check("the image has the trim and the dwell factor", False, str(e))
        print("\n%d FAIL" % FAILS)
        return 1
    trim_rig()
    engine_side()
    print("\n%d checks, %s" % (CHECKS, "PASS" if not FAILS else "%d FAIL" % FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
