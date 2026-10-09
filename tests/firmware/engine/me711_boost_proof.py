#!/usr/bin/env python3
r"""me711_boost_proof.py - boost control on the LINKED IMAGE (V97).

    py tests\firmware\engine\me711_boost_proof.py

The decision core (firmware/control/hcldr.c) is host-tested with its negative controls
(tests/host/test_hcldr_host.py). This gate runs what the image actually does:
hc_boost_service() (hcboost711.c, FCODE) reading the page through the far
thunks, the core, the ENG_CUT_BOOST bit - and that bit reaching the
injectors in the scheduler (hcsched_dry.c plan_tooth) on a 60-2 driven
through c167sim.

  1  open loop: duty = the map cell x the CLT multiplier (1.00 when unset)
  2  below the rpm floor: 0
  3  overboost with boost control DISABLED: fuel-cut bit set, valve 0;
     held inside the hysteresis, released below it
  4  MAP fault at an overboost pressure: valve 0 and NO cut (not judged)
  5  closed loop: first step = open + P + I exactly (the far module's
     arithmetic, no ?C_ helper - a wrong helper would not give 492)
  6  the 20 ms raster: two 10 ms passes = one step
  7  the cut reaches the injectors: dry_inj_pulse_us > 0 without it (the
     vacuity guard), 0 with ENG_CUT_BOOST, back after release
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_trigger_test as T                       # noqa: E402
from me711_trigger_generic_proof import Wheel        # noqa: E402

FAIL = 0
HDR = (ROOT / "firmware/config/hcconfig.h").read_text()
GEN = (ROOT / "firmware/generated/hc_config_generated.h").read_text()
ENG_CUT_BOOST, ENG_ERR_MAP = 0x0004, 0x0002


def off(name):
    m = re.search(r"#define\s+%s\s+(\d+)u?\b" % name, HDR) or \
        re.search(r"#define\s+%s\s+(\d+)u?\b" % name, GEN)
    return int(m.group(1))


def check(name, ok, detail=""):
    global FAIL
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<64} {detail}")
    FAIL += not ok


class Page:
    """the SRAM page (offsets >= HC_CFG_CORE live there, big-endian u16)"""
    def __init__(self, x):
        self.m = x.m

    def w8(self, name, v, i=0):
        self.m.w8(T.UNI_BASE + off(name) + i, v & 0xFF)

    def w16(self, name, v, i=0):
        a = T.UNI_BASE + off(name) + 2 * i
        self.m.w8(a, (v >> 8) & 0xFF)
        self.m.w8(a + 1, v & 0xFF)


def ram16(x, name, v):
    x.m.w16(T.sym(name) & 0xFFFF, v & 0xFFFF)


def setup(x, enable=1, mode=0):
    p = Page(x)
    p.w8("CAL_BOOST_ENABLE", enable)
    p.w8("CAL_BOOST_MODE", mode)
    for i in range(16):
        p.w16("CAL_BOOST_RPM_AX", 500 + i * 450, i)
        p.w16("CAL_BOOST_TGT_RPM_AX", 500 + i * 450, i)
        p.w16("CAL_BOOST_TPS_AX", i * 1000 // 15, i)
        p.w16("CAL_BOOST_TGT_TPS_AX", i * 1000 // 15, i)
    for c in range(256):
        p.w8("CAL_BOOST_DUTY_MAP", 60, c)          # 30.0 %
        p.w8("CAL_BOOST_TGT_MAP", 180, c)          # 180 kPa
    for i in range(8):
        p.w16("CAL_BOOST_CLT_AX", 9600 + i * 300, i)
        p.w16("CAL_BOOST_IAT_AX", 9600 + i * 300, i)
        p.w16("CAL_BOOST_CLT_MUL", 0, i)
        p.w16("CAL_BOOST_IAT_MUL", 0, i)
    p.w16("CAL_BOOST_KP", 60)
    p.w16("CAL_BOOST_KI", 4)
    p.w16("CAL_BOOST_KD", 0)
    p.w16("CAL_BOOST_MIN_RPM", 1500)
    p.w16("CAL_BOOST_MIN_TPS_X10", 300)
    p.w16("CAL_BOOST_CUT_KPA", 2200)
    p.w16("CAL_BOOST_CUT_HYST", 150)
    p.w16("CFG_U_BOOST_CL_MIN_X10", 1100)
    p.w16("CFG_U_BOOST_I_BAND_X10", 0)
    ram16(x, "trg_rpm", 3000)
    ram16(x, "eng_tps_x10", 500)
    ram16(x, "eng_map_kpa_x10", 1500)
    ram16(x, "eng_sensor_err", 0)
    ram16(x, "eng_clt_dc", 10900)
    ram16(x, "eng_iat_dc", 10300)
    ram16(x, "eng_fuelcut", 0)
    x.call("hc_boost_init")
    x.t = 0
    x.call("hc_boost_service", 0, 0)                  # the clock starts here
    return p


def step(x, ms=20, keyoff=0):
    """hc_boost_service() takes the UPTIME (tick_ms) - the rig keeps it"""
    x.t = (getattr(x, "t", 0) + ms) & 0xFFFF
    return x.call("hc_boost_service", x.t, keyoff)


def ldr(x):
    """hc_ldr as Keil lays it out: integ100 0..3, last_map 4, have_last 6,
    cut 7, state 8, duty_x10 10, p 12, i 14, d 16, cuts 18 (checked: duty
    must equal the returned value)"""
    a = T.sym("hc_ldr") & 0xFFFF
    m = x.m

    def s16(o):
        v = m.r16(a + o)
        return v - 65536 if v >= 32768 else v
    return {"cut": m.r8(a + 7), "state": m.r8(a + 8), "duty": m.r16(a + 10),
            "p": s16(12), "i": s16(14), "cuts": m.r16(a + 18)}


def main() -> int:
    print("=== boost control on the linked image ===")
    x = T.Call()
    p = setup(x)
    d = step(x)
    L = ldr(x)
    check("open loop: 30.0 % from the map, multipliers unset (1.00)",
          d == 300 and L["duty"] == 300 and L["state"] == 0x10,
          f"duty {d} state 0x{L['state']:02X}")
    for i in range(8):
        p.w16("CAL_BOOST_CLT_MUL", 80, i)
    d = step(x)
    check("... x the CLT multiplier 80 %: 24.0 %", d == 240, f"duty {d}")
    for i in range(8):
        p.w16("CAL_BOOST_CLT_MUL", 0, i)
    ram16(x, "trg_rpm", 1000)
    d = step(x)
    check("below the rpm floor: 0", d == 0 and ldr(x)["state"] == 0x08, f"duty {d}")
    ram16(x, "trg_rpm", 3000)

    # overboost with boost control OFF
    p.w8("CAL_BOOST_ENABLE", 0)
    seq = []
    for kpa in (2199, 2300, 2100, 2051, 2049):
        ram16(x, "eng_map_kpa_x10", kpa)
        dd = step(x)
        seq.append((kpa, bool(x.u16("eng_fuelcut") & ENG_CUT_BOOST), dd))
    want = [(2199, False, 0), (2300, True, 0), (2100, True, 0), (2051, True, 0),
            (2049, False, 0)]
    check("overboost, boost control OFF: cut at 220.0, held to 205.1, released",
          seq == want, str([(k, int(c)) for k, c, _ in seq]))
    check("... one event counted", ldr(x)["cuts"] == 1, f"cuts {ldr(x)['cuts']}")
    p.w8("CAL_BOOST_ENABLE", 1)

    # MAP fault at an overboost pressure
    ram16(x, "eng_map_kpa_x10", 2500)
    ram16(x, "eng_sensor_err", ENG_ERR_MAP)
    d = step(x)
    check("MAP fault at 250 kPa: valve 0, NO fuel cut (not judged on a guess)",
          d == 0 and not (x.u16("eng_fuelcut") & ENG_CUT_BOOST)
          and ldr(x)["state"] == 0x02, f"duty {d} state 0x{ldr(x)['state']:02X}")
    ram16(x, "eng_sensor_err", 0)

    # closed loop, exact first step
    x2 = T.Call()
    setup(x2, mode=1)
    d = step(x2)
    L = ldr(x2)
    check("closed loop, map 150 -> target 180: 300 + P 180 + I 12 = 492",
          d == 492 and L["p"] == 180 and L["i"] == 12 and L["state"] == 0x20,
          f"duty {d} P {L['p']} I {L['i']} state 0x{L['state']:02X}")
    d1 = step(x2, 10)
    i1 = ldr(x2)["i"]
    d2 = step(x2, 10)
    i2 = ldr(x2)["i"]
    check("20 ms raster: the first 10 ms pass holds, the second steps",
          d1 == 492 and i1 == 12 and i2 == 24 and d2 == 504,
          f"{d1}/{i1} then {d2}/{i2}")

    # the cut reaches the injectors
    w = Wheel(60, 2, 1200, plan=True)
    wx = w.x
    setup(wx)
    ram16(wx, "trg_rpm", 1200)
    ram16(wx, "eng_ti_us", 3000)
    # V97: the scheduler fuels from the CYCLE's open time (two halves in
    # batch) + dead time per pulse
    ram16(wx, "eng_ti_base_us", 6000)
    ram16(wx, "eng_deadtime_us", 0)
    for _ in range(4):
        w.rev()
    synced = wx.u8("trg_state")
    base = wx.u16("dry_inj_pulse_us")
    ram16(wx, "eng_map_kpa_x10", 2300)
    step(wx)
    for _ in range(2):
        w.rev()
    cut = wx.u16("dry_inj_pulse_us")
    ram16(wx, "eng_map_kpa_x10", 1500)
    step(wx)
    for _ in range(2):
        w.rev()
    back = wx.u16("dry_inj_pulse_us")
    still = wx.u8("trg_state")
    check("injectors: synced, pulse without the cut (vacuity guard)",
          synced >= 3 and base > 0, f"state {synced}, {base} us")
    check("... 0 with the overboost cut, restored after release, still synced",
          cut == 0 and back == base and still >= 3,
          f"cut {cut} us, back {back} us, state {still}")

    print(f"\n{'BOOST PROOF PASSES' if not FAIL else 'BOOST PROOF FAILS'} - {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
