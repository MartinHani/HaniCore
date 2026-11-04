#!/usr/bin/env python3
r"""me711_xfn_proof.py - the 2026-11-03 page-extension functions
(firmware/targets/me711/control/hcxfn711.c) on the LINKED IMAGE, c167sim.

    py tests\firmware\engine\me711_xfn_proof.py

Each vector sets page-EXTENSION fields (offsets 4096.., stored at
TGT_RAM_CFGEXT) and the engine state, runs the image's own functions and
checks the result; each feature also runs with its switch at 0 (the
negative control: the old behaviour).

  1  plate off target 30 % > 20 % for 0.5 s -> ENG_CUT_SAFE (fuel) and the
     scheduler's spark cut; not at 0.4 s; latched to the engine stop;
     etbDevCutPct 0 never cuts
  2  throttle-sensor pair fault with the motor on -> the same cut;
     etbPairAction 0 does not
  3  limp mode on manifold pressure: reason latched, throttle capped,
     boost off, P1300 stored
  4  cranking fuel held, then reduced to its floor; first revolutions extra
  5  overrun cut fades out over dfcoCutTime before the hard cut
  6  warm-up lambda is the richer of the table and the curve
  7  knock strength map and the AutoCal endpoint check
  8  idle spark integral bounded by its window; throttle slew by position
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402

import me711_trigger_test as T                       # noqa: E402

FAIL = 0
HDR = (ROOT / "firmware/config/hcconfig.h").read_text()
GEN = (ROOT / "firmware/generated/hc_config_generated.h").read_text()
TGT = (ROOT / "firmware/targets/me711/hctarget.h").read_text()
ENG = (ROOT / "firmware/engine/hcengine.h").read_text()


def cdef(text, name):
    m = re.search(r"#define\s+%s\s+(0x[0-9A-Fa-f]+|\d+)u?L?\b" % name, text)
    return int(m.group(1), 0)


EXT = 0x380000 + cdef(TGT, "TGT_RAM_CFGEXT")
MAIN = cdef(HDR, "HC_CFG_MAIN")
DBW = 0x380000 + cdef(TGT, "TGT_RAM_DBW")
ENG_CUT_SAFE = cdef(ENG, "ENG_CUT_SAFE")
S_STORED = 0x04


def off(name):
    m = re.search(r"#define\s+%s\s+(\d+)u?\b" % name, GEN) or \
        re.search(r"#define\s+%s\s+(\d+)u?\b" % name, HDR)
    return int(m.group(1))


def addr(name):
    o = off(name)
    return (EXT + o - MAIN) if o >= MAIN else (T.UNI_BASE + o)


def check(name, ok, detail=""):
    global FAIL
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<66} {detail}")
    FAIL += not ok


def pg8(x, name, v, i=0):
    x.m.w8(addr(name) + i, v & 0xFF)


def pg16(x, name, v):
    a = addr(name)
    x.m.w8(a, (v >> 8) & 0xFF)
    x.m.w8(a + 1, v & 0xFF)


def ram16(x, name, v):
    x.m.w16(T.sym(name) & 0xFFFF, v & 0xFFFF)


def ram8(x, name, v):
    x.m.w8(T.sym(name) & 0xFFFF, v & 0xFF)


def u8r(v):
    """an unsigned char return: R4's low byte (the high byte is not set)"""
    return v & 0xFF


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def fresh():
    x = T.Call()
    # the whole extension 0 = every function off, as a migrated page
    for i in range(384):
        x.m.w8(EXT + i, 0)
    for n in ("eng_sensor_err", "eng_fuelcut", "trg_rpm"):
        ram16(x, n, 0)
    ram8(x, "eng_cranking", 0)
    x.call("hc_x_init")
    x.t = 0
    return x


def svc(x, ms_total, step=10):
    for _ in range(ms_total // step):
        x.t = (x.t + step) & 0xFFFF
        x.call("hc_x_service", x.t)


def dbw_run(x, tgt, act, flt=0):
    """hc_dbw_state_t at TGT_RAM_DBW: st u8 @0, flt u16 @2, tgt @4, act @6"""
    x.m.w8(DBW + 0, 2)                    # DBW_RUN
    x.m.w16(DBW + 2, flt)
    x.m.w16(DBW + 4, tgt)
    x.m.w16(DBW + 6, act)


def cut(x):
    return bool(x.u16("eng_fuelcut") & ENG_CUT_SAFE)


def main() -> int:
    print("=== HaniCore ME7.1.1 - page-extension functions (hcxfn711.c) ===\n")

    # 1 ------------------------------------------------------------------
    print("--- 1 plate off target ---")
    for pct, label in ((20, "etbDevCutPct 20"), (0, "etbDevCutPct 0 (control)")):
        x = fresh()
        pg8(x, "CAL_DBW_ENABLE", 1)
        pg8(x, "CFG_U_ETB_DEVCUT_PCT", pct)
        pg8(x, "CFG_U_ETB_DEVCUT_T", 50)
        ram16(x, "trg_rpm", 2000)
        dbw_run(x, 500, 200)              # 30 % off target
        svc(x, 20)
        svc(x, 380)
        early = cut(x)
        svc(x, 150)
        late = cut(x)
        if pct:
            check("30 % off: no cut at 0.4 s, fuel cut after 0.5 s",
                  not early and late, f"{early} / {late}")
            check("... reason bit 'plate off target'", u8r(x.call("hc_x_cut_why")) & 1)
            x.call("hc_drysched_overdwell_service", 0)
            x.call("hc_drysched_overdwell_service", 0x2000)
            check("... and the scheduler cuts the SPARK too",
                  x.u8("dry_rev_spark_cut") == 1)
            dbw_run(x, 500, 495)          # back on target
            svc(x, 200)
            check("... latched while the engine turns", cut(x))
            ram16(x, "trg_rpm", 0)
            svc(x, 20)
            check("... released at the engine stop", not cut(x))
        else:
            check("control: etbDevCutPct 0 never cuts", not early and not late)

    # 2 ------------------------------------------------------------------
    print("--- 2 throttle-sensor pair fault ---")
    for act, label in ((1, "cut"), (0, "control")):
        x = fresh()
        pg8(x, "CAL_DBW_ENABLE", 1)
        pg8(x, "CFG_U_ETB_PAIR_ACTION", act)
        ram16(x, "trg_rpm", 1500)
        dbw_run(x, 100, 100, flt=0x0004)  # DBW_F_TPS_PAIR latched
        x.m.w8(DBW + 0, 3)                # DBW_FAULT
        svc(x, 30)
        if act:
            check("pair fault, etbPairAction 1: fuel+spark cut", cut(x)
                  and u8r(x.call("hc_x_cut_why")) & 2)
        else:
            check("control: etbPairAction 0 leaves it to the limp rpm", not cut(x))

    # 3 ------------------------------------------------------------------
    print("--- 3 limp mode ---")
    x = fresh()
    pg8(x, "CFG_U_LIMP_ON", 2)
    pg8(x, "CFG_U_LIMP_MAP", 100)         # 200 kPa
    pg8(x, "CFG_U_LIMP_MAP_T", 10)        # 1.0 s
    pg8(x, "CFG_U_LIMP_THR", 30)
    ram16(x, "trg_rpm", 4000)
    ram16(x, "eng_map_kpa_x10", 2100)
    svc(x, 900)
    early = u8r(x.call("hc_x_limp_why"))
    svc(x, 200)
    why = u8r(x.call("hc_x_limp_why"))
    check("210 kPa > 200 for 1.0 s -> limp (pressure), not at 0.9 s",
          early == 0 and why & 2, f"{early} -> {why}")
    check("... throttle capped at 30 %", x.call("hc_x_dbw_want", 800) == 300,
          f"{x.call('hc_x_dbw_want', 800)}")
    check("... boost off", u8r(x.call("hc_x_boost_off")) == 1)
    ram16(x, "eng_map_kpa_x10", 1000)
    svc(x, 200)
    check("... latched after the pressure falls", u8r(x.call("hc_x_limp_why")) & 2)
    x2 = fresh()
    ram16(x2, "trg_rpm", 4000)
    ram16(x2, "eng_map_kpa_x10", 2100)
    svc(x2, 1500)
    check("control: limpEnable 0 never limps, never caps",
          u8r(x2.call("hc_x_limp_why")) == 0 and x2.call("hc_x_dbw_want", 800) == 800)
    # P1300 through the DTC service
    for n in ("CFG_U_PIN_MAP", "CFG_U_PIN_CLT", "CFG_U_PIN_IAT", "CFG_U_PIN_TPS1",
              "CFG_U_PIN_TPS2", "CFG_U_PIN_APP1", "CFG_U_PIN_APP2"):
        pg8(x, n, 255)
    for n in ("trg_synclost", "trg_cycle_lost", "hc_asic_run_timeout",
              "hc_cfg_validation"):
        ram16(x, n, 0)
    x.call("hc_dtc_init")
    t = 0
    for _ in range(3):
        t += 100
        x.call("hc_dtc_service", t)
    stored = [x.call("hc_dtc_code", S_STORED, k) for k in range(6)]
    check("... P1300 stored", 1300 in stored, f"{[c for c in stored if c]}")

    # 4 ------------------------------------------------------------------
    print("--- 4 cranking fuel ---")
    x = fresh()
    pg8(x, "CFG_U_CRANK_HOLD", 10)        # 1.0 s
    pg8(x, "CFG_U_CRANK_DECAY", 10)       # 1.0 s
    pg8(x, "CFG_U_CRANK_FLOOR", 50)
    pg8(x, "CFG_U_FIRST_REVS_ADD", 25)
    pg8(x, "CFG_U_FIRST_REVS_N", 2)
    ram8(x, "eng_cranking", 1)
    x.call("hc_x_pre", 200, 10)           # 200 rpm: 0.033 rev per 10 ms
    first = x.call("hc_x_crank_fuel", 1000)
    for _ in range(100):                  # 1.0 s, ~3.3 revolutions
        x.call("hc_x_pre", 200, 10)
    held = x.call("hc_x_crank_fuel", 1000)
    for _ in range(50):
        x.call("hc_x_pre", 200, 10)
    half = x.call("hc_x_crank_fuel", 1000)
    for _ in range(60):
        x.call("hc_x_pre", 200, 10)
    floor = x.call("hc_x_crank_fuel", 1000)
    check("first revolutions +25 %", first == 1250, f"{first}")
    check("held at 100 % until the hold ends", held == 1000, f"{held}")
    check("half way down the decay ~75 %", 730 <= half <= 770, f"{half}")
    check("then the floor, 50 %", floor == 500, f"{floor}")
    x2 = fresh()
    ram8(x2, "eng_cranking", 1)
    for _ in range(300):
        x2.call("hc_x_pre", 200, 10)
    check("control: all 0 -> the table as it is",
          x2.call("hc_x_crank_fuel", 1000) == 1000)

    # 5 ------------------------------------------------------------------
    print("--- 5 overrun fade ---")
    x = fresh()
    pg8(x, "CFG_U_DFCO_CUT_T", 20)        # 0.20 s
    hard = [u8r(x.call("hc_x_dfco", 1, 20)) for _ in range(12)]
    check("fuel fades 1000 -> 0 over 0.2 s, then the hard cut",
          hard[:9] == [0] * 9 and hard[-1] == 1, f"{hard}")
    x2 = fresh()
    check("control: dfcoCutTime 0 = hard cut at once",
          u8r(x2.call("hc_x_dfco", 1, 20)) == 1)

    # 6 ------------------------------------------------------------------
    print("--- 6 warm-up lambda ---")
    x = fresh()
    pg8(x, "CFG_U_WU_LAM_ON", 1)
    for i, (c, v) in enumerate(zip([9800, 10000, 10200, 10400, 10600, 10700],
                                   [30, 34, 40, 48, 56, 60])):
        a = addr("CFG_U_WU_LAM_CLT") + 2 * i
        x.m.w8(a, c >> 8)
        x.m.w8(a + 1, c & 0xFF)
        pg8(x, "CFG_U_WU_LAM_VAL", v, i)
    ram16(x, "eng_clt_dc", 10000)         # 0 C
    x.call("hc_x_pre", 0, 10)
    check("0 C: lambda 0.870 against a table 1.000",
          x.call("hc_x_lambda", 1000) == 870, f"{x.call('hc_x_lambda', 1000)}")
    check("... and a richer table wins", x.call("hc_x_lambda", 800) == 800)
    pg8(x, "CFG_U_WU_LAM_ON", 0)
    x.call("hc_x_pre", 0, 10)
    check("control: off -> the table", x.call("hc_x_lambda", 1000) == 1000)

    # 7 ------------------------------------------------------------------
    print("--- 7 knock strength, AutoCal endpoints ---")
    x = fresh()
    pg8(x, "CFG_U_KAMP_ON", 1)
    for i, v in enumerate([20, 35, 50, 65]):
        pg8(x, "CFG_U_KAMP_RPM_AX", v, i)
    for i, v in enumerate([15, 20, 30, 40]):
        pg8(x, "CFG_U_KAMP_AX", v, i)
    for i in range(16):
        pg8(x, "CFG_U_KAMP_MAP", 4 + i, i)
    q = u8r(x.call("hc_x_knock_q", 48, 3600))  # strength 3.0, rpm row 1 -> cell 2*4+1
    check("strength 3.0 at 3600 rpm -> map cell [2][1]", q == 4 + 9, f"{q}")
    pg8(x, "CFG_U_KAMP_ON", 0)
    check("control: off -> 0 (the fixed step)", u8r(x.call("hc_x_knock_q", 48, 3600)) == 0)
    for i, v in enumerate([25, 233, 225, 17]):
        pg8(x, "CFG_U_TPS_EXP", v, i)
    pg8(x, "CFG_U_TPS_EXP_TOL", 25)
    ok = u8r(x.call("hc_x_etbcal_check", 102, 954, 919, 71))
    bad = u8r(x.call("hc_x_etbcal_check", 920, 67, 106, 958))
    check("AWT body endpoints pass, the swapped track is refused (index 1)",
          ok == 0 and bad == 1, f"{ok} / {bad}")
    pg8(x, "CFG_U_TPS_EXP_TOL", 0)
    check("control: tolerance 0 = no check",
          u8r(x.call("hc_x_etbcal_check", 920, 67, 106, 958)) == 0)

    # 8 ------------------------------------------------------------------
    print("--- 8 idle spark integral, throttle slew ---")
    x = fresh()
    pg16(x, "CFG_U_IDLE_TIM_MIN", 0x10000 - 100)   # -10 deg
    pg16(x, "CFG_U_IDLE_TIM_MAX", 100)             # +10 deg
    pg8(x, "CFG_U_IDLE_IGN_KI", 10)
    ram16(x, "trg_rpm", 800)
    outs = [s16(x.call("hc_x_idle_timing", 0, 1, 900, 20)) for _ in range(600)]
    check("100 rpm low: the integral advances, bounded at +10 deg",
          outs[10] > 0 and max(outs) == 100, f"{outs[10]} .. {max(outs)}")
    pg8(x, "CFG_U_IDLE_IGN_KI", 0)
    x.call("hc_x_idle_timing", 0, 0, 900, 20)
    check("control: Ki 0 -> the P part alone",
          s16(x.call("hc_x_idle_timing", 0, 1, 900, 20)) == 0)
    for i, v in enumerate([3, 10, 50, 100]):
        pg8(x, "CFG_U_DBWS_AX", v, i)
    for i, v in enumerate([10, 30, 60, 60]):
        pg8(x, "CFG_U_DBWS_CLOSE", v, i)
    n = x.call("hc_x_dbw_slew", 30, 0, 5)
    check("closing near the stop: 1 %/10 ms -> 0.5 % per 5 ms step",
          n == 25, f"30 -> {n}")
    check("control: opening has no limit", x.call("hc_x_dbw_slew", 30, 500, 5) == 500)

    print()
    print("PAGE-EXTENSION FUNCTIONS PROOF %s - %d failed"
          % ("PASSES" if not FAIL else "FAILS", FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
