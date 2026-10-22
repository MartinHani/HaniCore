#!/usr/bin/env python3
r"""me711_aux_proof.py - the auxiliary functions (hcaux711.c, 2026-10-14):
cooling fan, A/C, two programmable outputs, the oil pressure sensor and the
oil pressure protection, on the LINKED image in c167sim.

    py tests\firmware\outputs\me711_aux_proof.py [--control <bins dir>]

The AWT preset page (me711_alphan_start_proof.setup), then hc_aux_service()
and hc_limp_service() called with a running clock and the engine state they
read (trg_rpm, eng_cranking, coolant, throttle, battery, sensor faults). The
OUTPUT is the port: cavity 115 = P7.0, 120 = P7.1 through the CJ920 - ON =
an output at LOW, OFF = released (direction input).

  F  fan: on at fanOnTemp, held to fanOffTemp, off below; a failed coolant
     sensor runs it; off while cranking; fanStoppedOff; released when the
     outputs are not permitted (key off); a moved pin releases the old one.
  A  A/C: request on 87 (switch to ground), compressor relay on 120 only
     after acDelay; cut-outs by rpm, throttle and coolant, each named in
     auxStatus; the fan follows the compressor (fanWithAc); the idle-up
     (throttle and target rpm) only while requested with the engine running.
  G  programmable output 1: rpm above 3000 with 200 rpm hysteresis; a second
     condition (coolant above 80) AND / OR; a failed sensor is never true;
     the on delay; "on below" (battery below 12.0 V).
  O  oil pressure on cavity 29 (main AN0): 2.5 V on a 0.5-4.5 V / 1000 kPa
     sensor reads 500 kPa; 0.1 V is a fault (no reading); the protection
     cuts the fuel after oilPressDelay below the minimum above the check rpm
     (not before), latched to the engine stop; no pressure within 5 s of
     the start cuts; a FAILED sensor never cuts.
  V  the validator: an output on a cavity this build cannot drive (9), two
     functions on one cavity, a request input with no read path (41), an
     oil sensor on a cavity with no analog input (82), an ignition trim
     byte outside 28..228 are refused (an unknown output source is not:
     G6 shows it is never true).

--control <bins dir>: an image without the functions (5248F4C9) must FAIL.
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

P2, P7, DP7 = 0xFFC0, 0xFFD0, 0xFFD2
B115, B120 = 0x0001, 0x0002
INHIBIT_KEYOFF = 0x0010
ENG_CUT_LIMP = 0x0008
ERR_CLT = 0x0001
CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += 0 if ok else 1
    print("  [%s] %-64s %s" % ("PASS" if ok else "FAIL", name, detail))
    return ok


class Aux:
    def __init__(self):
        import me711_config_state_test as T
        import me711_alphan_start_proof as AS
        self.T, self.AS = T, AS
        self.r = AS.setup()
        self.now = 1000
        self.ms_lim = 0
        self.set(rpm=900, clt=85)
        self.w16("hc_safety_inhibits", 0)

    # ---- state ----------------------------------------------------------
    def a(self, name):
        return self.T.sym(name) & 0xFFFF

    def w16(self, name, v):
        self.r.m.w16(self.a(name), v & 0xFFFF)

    def set(self, rpm=None, clt=None, crank=None, tps=None, err=None,
            batt=None):
        if rpm is not None:
            self.w16("trg_rpm", rpm)
            if crank is None:
                crank = 1 if 0 < rpm < 400 else 0
        if crank is not None:
            self.r.m.w8(self.a("eng_cranking"), crank)
        if clt is not None:
            self.w16("eng_clt_dc", 10 * clt + 10000)
        if tps is not None:
            self.w16("eng_tps_x10", tps * 10)
        if err is not None:
            self.w16("eng_sensor_err", err)
        if batt is not None:
            self.w16("eng_batt_dv", batt)

    def page(self, name, v, i=0):
        self.r("hc_cal_set_u8", self.AS.off(name) + i, v)

    def page16(self, name, v):
        o = self.AS.off(name)
        self.r("hc_cal_set_u8", o, (v >> 8) & 0xFF)
        self.r("hc_cal_set_u8", o + 1, v & 0xFF)

    def run(self, ms):
        """hc_aux_service every 20 ms (and the protection every 10 ms)"""
        t = 0
        while t < ms:
            self.now = (self.now + 10) & 0xFFFF
            t += 10
            self.r("hc_limp_service", self.now, steps=2_000_000)
            if t % 20 == 0:
                self.r("hc_aux_service", self.now, steps=2_000_000)

    # ---- observation ----------------------------------------------------
    def pin(self, bit):
        dp = self.r.m.sfr.get(DP7, 0)
        p = self.r.m.sfr.get(P7, 0)
        if not dp & bit:
            return "off"
        return "ON" if not p & bit else "high"

    def status(self):
        a = PI.och_addr(1660)
        return (self.r.m.r8(a) << 8) | self.r.m.r8(a + 1)

    def oil(self):
        a = PI.och_addr(1662)
        return (self.r.m.r8(a) << 8) | self.r.m.r8(a + 1)

    def adc(self, ch, raw):
        self.AS.adc(self.r, ch, raw)
        self.r.publish_samples()

    def cut(self):
        return (self.r.m.r8(self.a("hc_limp")) & 0x04,
                self.r.m.r16(self.a("eng_fuelcut")) & ENG_CUT_LIMP)


def fan(x):
    print("\n--- F: cooling fan (pin 115) ---")
    x.page("CFG_U_PIN_FAN", 115)
    def u16(n):
        o = x.AS.off(n)
        return (x.r.active(o) << 8) | x.r.active(o + 1)
    check("F0 board default: on 95 C, off 90 C (10 * C + 10000)",
          u16("CFG_U_FAN_ON_C") == 10950 and u16("CFG_U_FAN_OFF_C") == 10900,
          "%d / %d" % (u16("CFG_U_FAN_ON_C"), u16("CFG_U_FAN_OFF_C")))
    seq = []
    for c in (100, 92, 89, 92):
        x.set(clt=c)
        x.run(60)
        seq.append(x.pin(B115))
    check("F1 100 C on, 92 C held on, 89 C off, 92 C stays off",
          seq == ["ON", "ON", "off", "off"], str(seq))
    check("F1 auxStatus bit 0 follows (off now)", not x.status() & 1,
          "0x%04X" % x.status())
    x.set(err=ERR_CLT, clt=20)
    x.run(60)
    check("F2 failed coolant sensor: fan ON", x.pin(B115) == "ON")
    x.set(err=0, clt=100, rpm=200, crank=1)
    x.run(60)
    check("F3 cranking: fan off (the battery)", x.pin(B115) == "off")
    x.set(rpm=0, crank=1)
    x.run(60)
    on0 = x.pin(B115)
    x.page("CFG_U_FAN_STOPPED_OFF", 1)
    x.run(60)
    off0 = x.pin(B115)
    x.page("CFG_U_FAN_STOPPED_OFF", 0)
    check("F4 engine stopped, hot: on; with fanStoppedOff: off",
          on0 == "ON" and off0 == "off", "%s / %s" % (on0, off0))
    x.set(rpm=900)
    x.run(60)
    x.w16("hc_safety_inhibits", INHIBIT_KEYOFF)
    x.run(60)
    held = x.pin(B115), bool(x.status() & 0x40)
    x.w16("hc_safety_inhibits", 0)
    x.run(60)
    check("F5 key-off (not permitted): released and HOLD; back after",
          held == ("off", True) and x.pin(B115) == "ON", str(held))
    x.page("CFG_U_PIN_FAN", 120)
    x.run(60)
    check("F6 pin moved 115 -> 120: 115 released, 120 driven",
          x.pin(B115) == "off" and x.pin(B120) == "ON",
          "115 %s, 120 %s" % (x.pin(B115), x.pin(B120)))
    x.page("CFG_U_PIN_FAN", 255)
    x.run(60)
    check("F7 unrouted: both released", x.pin(B115) == "off"
          and x.pin(B120) == "off")


def aircon(x):
    print("\n--- A: A/C (request 87 to ground, relay 120, fan 115) ---")
    x.page("CFG_U_PIN_FAN", 115)
    x.page("CFG_U_FAN_WITH_AC", 1)
    x.page("CFG_U_PIN_AC_REQ", 87)
    x.page("CFG_U_AC_REQ_ACTIVE", 1)
    x.page("CFG_U_PIN_AC_CLUTCH", 120)
    p2 = x.r.m.sfr.get(P2, 0)
    x.r.m.sfr[P2] = p2 | 0x0200                       # released: no request
    x.set(rpm=900, clt=85, tps=5)
    x.run(100)
    idle0 = x.r("hc_aux_idle_up_x10"), x.r("hc_aux_idle_rpm")
    check("A0 no request: relay and fan off, no idle-up",
          x.pin(B120) == "off" and x.pin(B115) == "off" and idle0 == (0, 0),
          str(idle0))
    x.r.m.sfr[P2] = p2 & ~0x0200                      # request
    x.run(200)
    early = x.pin(B120), (x.status() >> 8) & 15
    x.run(400)
    check("A1 relay waits acDelay 0.5 s (why = delay), then ON",
          early == ("off", 5) and x.pin(B120) == "ON", "at 0.2 s %s" % (early,))
    check("A1 fan with the compressor at 85 C", x.pin(B115) == "ON")
    up = x.r("hc_aux_idle_up_x10"), x.r("hc_aux_idle_rpm")
    check("A2 idle-up while requested: +2.0 % throttle, +100 rpm",
          up == (20, 100), str(up))
    whys = {}
    for k, kw in (("tps", dict(tps=85)), ("rpm", dict(tps=5, rpm=7000)),
                  ("stop", dict(rpm=300, crank=0)), ("clt", dict(rpm=900, clt=120))):
        x.set(**kw)
        x.run(60)
        whys[k] = (x.pin(B120), (x.status() >> 8) & 15)
    check("A3 cut-outs: throttle 85 % (3), 7000 rpm (2), 300 rpm (1), "
          "120 C (4)",
          whys == {"tps": ("off", 3), "rpm": ("off", 2), "stop": ("off", 1),
                   "clt": ("off", 4)}, str(whys))
    x.set(clt=85)
    x.run(700)
    back = x.pin(B120)
    x.r.m.sfr[P2] = p2 | 0x0200
    x.run(60)
    gone = x.pin(B120), x.r("hc_aux_idle_up_x10")
    check("A4 back on after the cut-out; request released: off, no idle-up",
          back == "ON" and gone == ("off", 0), "%s / %s" % (back, gone))
    for n, v in (("CFG_U_PIN_FAN", 255), ("CFG_U_PIN_AC_REQ", 255),
                 ("CFG_U_PIN_AC_CLUTCH", 255), ("CFG_U_FAN_WITH_AC", 0)):
        x.page(n, v)
    x.run(60)


def outputs(x):
    print("\n--- G: programmable output 1 on 120 ---")
    x.page("CFG_U_GP1_PIN", 120)
    x.page("CFG_U_GP1_SRC_A", 1)            # rpm
    x.page("CFG_U_GP1_OP_A", 0)             # on above
    x.page16("CFG_U_GP1_THR_A", 3000)
    x.page("CFG_U_GP1_HYST_A", 200)
    seq = []
    for rpm in (3500, 2900, 2700, 2900):
        x.set(rpm=rpm, clt=85)
        x.run(40)
        seq.append(x.pin(B120))
    check("G1 rpm above 3000 / hysteresis 200: 3500 on, 2900 held, 2700 off, "
          "2900 stays off", seq == ["ON", "ON", "off", "off"], str(seq))
    x.page("CFG_U_GP1_SRC_B", 2)            # coolant
    x.page16("CFG_U_GP1_THR_B", 80)
    x.page("CFG_U_GP1_LOGIC", 0)            # AND
    res = []
    for rpm, c in ((3500, 70), (3500, 85), (1000, 85)):
        x.set(rpm=rpm, clt=c)
        x.run(40)
        res.append(x.pin(B120))
    x.page("CFG_U_GP1_LOGIC", 1)            # OR
    x.run(40)
    res.append(x.pin(B120))
    check("G2 AND: 3500 rpm + 70 C off, + 85 C on, 1000 rpm off; OR: on",
          res == ["off", "ON", "off", "ON"], str(res))
    x.set(err=ERR_CLT)
    x.run(40)
    check("G3 the coolant source failed: condition B never true (off)",
          x.pin(B120) == "off")
    x.set(err=0, rpm=1000)
    x.page("CFG_U_GP1_SRC_B", 0)
    x.page("CFG_U_GP1_DELAY", 10)           # 1.0 s
    x.run(100)
    x.set(rpm=3500)
    x.run(600)
    early = x.pin(B120)
    x.run(600)
    check("G4 on delay 1.0 s: off at 0.6 s, on at 1.2 s",
          early == "off" and x.pin(B120) == "ON", early)
    x.page("CFG_U_GP1_DELAY", 0)
    x.page("CFG_U_GP1_SRC_A", 7)            # battery 0.1 V
    x.page("CFG_U_GP1_OP_A", 1)             # on below
    x.page16("CFG_U_GP1_THR_A", 120)
    x.page("CFG_U_GP1_HYST_A", 3)
    seq = []
    for b in (115, 121, 124):
        x.set(batt=b)
        x.run(40)
        seq.append(x.pin(B120))
    check("G5 'on below' 12.0 V, hysteresis 0.3 V: 11.5 on, 12.1 held, "
          "12.4 off", seq == ["ON", "ON", "off"], str(seq))
    check("G5 auxStatus bit 3 = output 1", not x.status() & 0x08)
    x.page("CFG_U_GP1_SRC_A", 12)           # no such source
    x.page("CFG_U_GP1_OP_A", 0)
    x.page16("CFG_U_GP1_THR_A", 0xFFFF)     # -1: anything real is above
    x.run(40)
    check("G6 an unknown source (12) is never true", x.pin(B120) == "off")
    x.page("CFG_U_GP1_PIN", 255)
    x.page("CFG_U_GP1_SRC_A", 0)
    x.run(40)


def oil(x):
    print("\n--- O: oil pressure on 29 (AN0) and its protection ---")
    x.page("CFG_U_PIN_OIL_PRESS", 29)
    x.adc(0, 512)                            # 2.50 V
    x.set(rpm=0)
    x.run(60)
    check("O1 2.5 V on 0.5-4.5 V / 1000 kPa = 500 kPa, valid",
          abs(x.oil() - 500) <= 1 and x.status() & 0x20,
          "%d kPa, status 0x%04X" % (x.oil(), x.status()))
    x.adc(0, 20)                             # 0.1 V: open / short
    x.run(60)
    check("O2 0.1 V: a fault - no reading", x.oil() == 0
          and not x.status() & 0x20, "0x%04X" % x.status())
    x.page16("CFG_U_OILP_MIN_KPA", 150)
    x.page16("CFG_U_OILP_MIN_RPM", 1500)
    x.page("CFG_U_OILP_DELAY", 10)           # 1.0 s
    x.adc(0, 512)
    x.set(rpm=3000)
    x.run(500)
    ok0 = x.cut()
    x.adc(0, 205)                            # 1.0 V = 125 kPa
    x.run(500)
    half = x.cut()
    x.run(700)
    cut = x.cut()
    x.adc(0, 512)
    x.run(200)
    held = x.cut()
    check("O3 below 150 kPa above 1500 rpm: no cut at 0.5 s, cut after "
          "1.0 s, latched", ok0 == (0, 0) and half == (0, 0)
          and cut == (4, ENG_CUT_LIMP) and held == (4, ENG_CUT_LIMP),
          "%s %s %s %s" % (ok0, half, cut, held))
    x.set(rpm=0)
    x.run(100)
    x.set(rpm=3000)
    x.adc(0, 20)                             # dead sensor from the start
    x.run(6500)
    check("O4 a FAILED sensor never cuts (6.5 s running)",
          x.cut() == (0, 0), str(x.cut()))
    x.set(rpm=0)
    x.run(100)
    x.adc(0, 205)                            # valid, never above the minimum
    x.set(rpm=3000)
    x.run(4000)
    early = x.cut()
    x.run(1500)
    check("O5 no pressure within 5 s of the start: cut (not at 4 s)",
          early == (0, 0) and x.cut() == (4, ENG_CUT_LIMP),
          "%s -> %s" % (early, x.cut()))
    x.set(rpm=0)
    x.run(100)
    x.page16("CFG_U_OILP_MIN_KPA", 0)
    x.page("CFG_U_PIN_OIL_PRESS", 255)


def validator(x):
    print("\n--- V: the validator (desired page) ---")
    r, off = x.r, x.AS.off

    def val(**kw):
        for k, v in kw.items():
            r.write(off(k), v)
        return r("hc_validate", 1, steps=40_000_000)

    base = val()
    # the AWT preset keeps its N205 route on 115 (cam 1 solenoid, VVT off):
    # 115 is taken, 120 is free
    v9 = val(CFG_U_PIN_FAN=9)
    v115 = val(CFG_U_PIN_FAN=115)
    v120 = val(CFG_U_PIN_FAN=120)
    two = val(CFG_U_PIN_AC_CLUTCH=120)
    val(CFG_U_PIN_AC_CLUTCH=255, CFG_U_PIN_FAN=255)
    req41 = val(CFG_U_PIN_AC_REQ=41)
    req87 = val(CFG_U_PIN_AC_REQ=87)
    val(CFG_U_PIN_AC_REQ=255)
    oil82 = val(CFG_U_PIN_OIL_PRESS=82)
    oil29 = val(CFG_U_PIN_OIL_PRESS=29)
    val(CFG_U_PIN_OIL_PRESS=255)
    trim0 = val(CFG_U_IGN_TRIM=0)
    trim228 = val(CFG_U_IGN_TRIM=228)
    trim229 = val(CFG_U_IGN_TRIM=229)
    val(CFG_U_IGN_TRIM=128)
    check("V0 the AWT page validates", base == 0, "%04X" % base)
    check("V1 fan on 9 (no drive) refused, on 120 accepted",
          v9 != 0 and v120 == 0, "%04X / %04X" % (v9, v120))
    check("V2 one cavity, two owners refused: fan on the cam 1 solenoid's "
          "115, A/C relay on the fan's 120",
          v115 & 0x0040 and two & 0x0040, "%04X / %04X" % (v115, two))
    check("V3 A/C request on 41 (no read path) refused, 87 accepted",
          req41 != 0 and req87 == 0, "%04X / %04X" % (req41, req87))
    check("V4 oil sensor on 82 (crank, no analog) refused, 29 accepted",
          oil82 != 0 and oil29 == 0, "%04X / %04X" % (oil82, oil29))
    check("V5 trim byte 0 and 229 refused, 228 accepted",
          trim0 != 0 and trim229 != 0 and trim228 == 0,
          "%04X %04X %04X" % (trim0, trim229, trim228))


def main() -> int:
    print("=== auxiliary functions: fan, A/C, outputs, oil pressure ===")
    print("  image", PI.image())
    try:
        x = Aux()
        x.T.sym("hc_aux_service")
    except SystemExit as e:
        check("the image has the auxiliary functions", False, str(e))
        print("\n%d FAIL" % FAILS)
        return 1
    fan(x)
    aircon(x)
    outputs(x)
    oil(x)
    validator(x)
    print("\n%d checks, %s" % (CHECKS, "PASS" if not FAILS else "%d FAIL" % FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
