#!/usr/bin/env python3
r"""me711_idle_valve_proof.py - the idle air valve (cable throttle) on the
LINKED IMAGE (2026-10-31).

    py tests\firmware\engine\me711_idle_valve_proof.py

hcidle711.c drives the idle controller's position as a valve duty on the main
CPU's PWM units (POUT0 / POUT1: cavities 115 / 120 on the Porsche and the 4F,
114 / 104 on the 2.7T and the ME7.5) when idleActuator selects a valve. As in
me711_vvt_proof, c167sim does not make the waveform: the gate reads the
registers the unit runs from (PWMCON0/1, PPx, PWx, DP7, P7 from reg167.h).

  A1  Electronic throttle (0): neither unit touched
  A2  2-wire valve on POUT0, engine stopped: the base position (6.5 %) is the
      duty at 200 Hz (idleValveFreq 0), pin driven, latch 0; POUT1 untouched
  A3  idleValveFreq 10 (100 Hz) reaches the period
  A4  DBW off: "pedal released" is the TPS - 50 % TPS holds the trim
  A5  3-wire valve: both units, the same period and duty, the second unit's
      latch 1 (pin = POUT XOR latch = the complement)
  A6  the ALWAYS permission falls -> both released
  A7  the route moves POUT0 -> POUT1 -> POUT0 released; actuator 0 -> released
  V   hc_validate() (executed): a valve with DBW enabled, a pin that is not a
      PWM unit, a 3-wire valve on one pin - refused; a valid valve and the
      old page (actuator 0, the former pad bytes 0) - accepted
  G   the TPS Grab with one track (DBW off): PASS, track 1 written; with DBW
      on the same single track is refused (NOCHANNEL)
The images before 2026-10-31 have no idleActuator: A2, A5, V and G fail there.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths as HCP  # noqa: E402  (puts every tools/ and tests/ module on sys.path)

import hc_board                            # noqa: E402
import me711_dbw_control_proof as D        # noqa: E402
import me711_config_state_test as T        # noqa: E402

_REG = HCP.REG167.read_text(errors="replace")
FAIL = 0


def sfr(n):
    return int(re.search(r"^\s*sfr\s+%s\s*=\s*(0x[0-9A-Fa-f]+);" % n,
                         _REG, re.M).group(1), 16)


PWMCON0, PWMCON1 = sfr("PWMCON0"), sfr("PWMCON1")
PP0, PP1, PW0, PW1 = sfr("PP0"), sfr("PP1"), sfr("PW0"), sfr("PW1")
DP7, P7 = sfr("DP7"), sfr("P7")
P0, P1 = (114, 104) if hc_board.IS_C4 else (115, 120)
CPS = 375000 if hc_board.IS_C4 else 625000      # fCPU / 64


def period(f):
    """the firmware's counts per period, as hcvvt711.c rounds: (CPS/10/f)*10"""
    return (CPS // 10 // f) * 10


def check(name, ok, detail=""):
    global FAIL
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<66} {detail}")
    FAIL += not ok
    return ok


def unit(r, u):
    m = r.mem
    b = 1 << u
    return {"run": bool(m.r16(PWMCON0) & b),
            "pin": bool(m.r16(PWMCON1) & b) and bool(m.r16(DP7) & b),
            "latch": int(bool(m.r16(P7) & b)),
            "pp": m.r16(PP1 if u else PP0), "pw": m.r16(PW1 if u else PW0)}


def released(r, u):
    s = unit(r, u)
    return not s["run"] and not s["pin"]


def setup(r):
    r.set8("CAL_DBW_ENABLE", 0)
    for i in range(8):
        ax = (-20 + 20 * i + 100) * 10
        for name, val in (("CAL_IDLE_TARGET_AX", ax), ("CAL_IDLE_BASE_AX", ax),
                          ("CAL_IDLE_TARGET_VAL", 800), ("CAL_IDLE_BASE_VAL", 65)):
            a = r.page_addr(D.gen_off(name) + 2 * i)
            r.mem.w8(a, (val >> 8) & 0xFF)
            r.mem.w8(a + 1, val & 0xFF)
    r.set8("CAL_IDLE_ENABLE", 1)
    r.set16("CAL_IDLE_KP", 20)
    r.set16("CAL_IDLE_KI", 50)
    r.set16("CAL_IDLE_RANGE_X10", 50)
    r.set16("CAL_IDLE_RPM_BAND", 400)
    r.set16("CFG_U_IDLE_PEDAL_X10", 0)
    r.set16("CFG_U_IDLE_START_MS", 0)
    r.set8("CFG_U_IDLE_ACTUATOR", 0)
    r.set8("CFG_U_PIN_IDLE_VALVE", P0)
    r.set8("CFG_U_PIN_IDLE_VALVE2", P1)
    r.set8("CFG_U_IDLE_VALVE_FREQ", 0)
    for a, v in ((PWMCON0, 0), (PWMCON1, 0), (DP7, 0), (P7, 0)):
        r.mem.w16(a, v)
    r.mem.w16(D.sym("eng_clt_dc") & 0xFFFF, 1800)      # 80.0 C
    r.mem.w16(D.sym("trg_rpm") & 0xFFFF, 0)
    r.mem.w8(D.sym("eng_cranking") & 0xFFFF, 0)
    r.mem.w16(D.sym("eng_tps_x10") & 0xFFFF, 0)
    r.call("hc_idle_init")
    r.t = 0
    r.call("hc_idle_service", (0,))


def idle(r, n=1):
    for _ in range(n):
        r.t = (r.t + 20) & 0xFFFF
        r.call("hc_idle_service", (r.t,))
    return r.mem.r16(D.sym("hc_idle_floor_x10") & 0xFFFF)


def valve_checks():
    print("-- the valve on the image's PWM units (%d / %d) --" % (P0, P1))
    r = D.Rig()
    r.baseline()
    setup(r)
    inh = r.mem.r16(D.sym("hc_safety_inhibits") & 0xFFFF)

    idle(r, 3)
    check("A1 electronic throttle: neither unit touched",
          released(r, 0) and released(r, 1), "%s %s" % (unit(r, 0), unit(r, 1)))

    r.set8("CFG_U_IDLE_ACTUATOR", 1)
    f = idle(r, 2)
    pp = period(200)
    u0 = unit(r, 0)
    check("A2 2-wire on %d, stopped: base 6.5 %% at 200 Hz, latch 0" % P0,
          f == 65 and u0["run"] and u0["pin"] and u0["latch"] == 0
          and u0["pp"] == pp - 1 and u0["pw"] == 65 * pp // 1000,
          "pos %d %s" % (f, u0))
    check("A2 ... POUT1 (%d) untouched" % P1, released(r, 1), str(unit(r, 1)))

    r.set8("CFG_U_IDLE_VALVE_FREQ", 10)
    idle(r)
    pp = period(100)
    check("A3 idleValveFreq 10 -> 100 Hz period",
          unit(r, 0)["pp"] == pp - 1 and unit(r, 0)["pw"] == 65 * pp // 1000,
          str(unit(r, 0)))

    r.mem.w16(D.sym("trg_rpm") & 0xFFFF, 700)
    idle(r, 52)                                    # past the 1000 ms hold
    closed = r.mem.r8((D.sym("hc_idl") & 0xFFFF) + 17)
    r.mem.w16(D.sym("eng_tps_x10") & 0xFFFF, 500)
    idle(r)
    pressed = r.mem.r8((D.sym("hc_idl") & 0xFFFF) + 17)
    r.mem.w16(D.sym("eng_tps_x10") & 0xFFFF, 0)
    check("A4 DBW off: closed loop at TPS 0, 'pedal pressed' at TPS 50 %",
          closed & 0x20 and pressed & 0x08 and not pressed & 0x20,
          "state 0x%02X -> 0x%02X" % (closed, pressed))

    r.mem.w16(D.sym("trg_rpm") & 0xFFFF, 0)
    r.set8("CFG_U_IDLE_ACTUATOR", 2)
    r.set8("CFG_U_IDLE_VALVE_FREQ", 0)
    idle(r, 2)
    a, b = unit(r, 0), unit(r, 1)
    pp = period(200)
    check("A5 3-wire: both units, same period and duty",
          a["run"] and b["run"] and a["pin"] and b["pin"]
          and a["pp"] == b["pp"] == pp - 1 and a["pw"] == b["pw"] == 65 * pp // 1000,
          "%s %s" % (a, b))
    check("A5 ... the closing coil's latch 1 (its pin is the complement)",
          a["latch"] == 0 and b["latch"] == 1, "latch %d / %d" % (a["latch"], b["latch"]))

    r.mem.w16(D.sym("hc_safety_inhibits") & 0xFFFF, 0xFFFF)   # every inhibit
    idle(r)
    check("A6 the ALWAYS permission falls -> both released, latches 0",
          released(r, 0) and released(r, 1)
          and unit(r, 0)["latch"] == unit(r, 1)["latch"] == 0,
          "%s %s" % (unit(r, 0), unit(r, 1)))
    r.mem.w16(D.sym("hc_safety_inhibits") & 0xFFFF, inh)

    r.set8("CFG_U_IDLE_ACTUATOR", 1)
    idle(r)
    ran = unit(r, 0)["run"]
    r.set8("CFG_U_PIN_IDLE_VALVE", P1)
    idle(r)
    check("A7 the route moves %d -> %d: POUT1 runs, POUT0 released" % (P0, P1),
          ran and unit(r, 1)["run"] and unit(r, 1)["latch"] == 0 and released(r, 0),
          "%s %s" % (unit(r, 0), unit(r, 1)))
    r.set8("CFG_U_IDLE_ACTUATOR", 0)
    idle(r)
    check("A7 actuator back to the throttle: released",
          released(r, 0) and released(r, 1), "%s %s" % (unit(r, 0), unit(r, 1)))
    return r


def validate_checks():
    print("\n-- hc_validate() executed --")
    CAP = T.VAL["HC_VAL_FAULT_PIN_CAP"]
    CONF = T.VAL["HC_VAL_FAULT_PIN_CONFLICT"]

    def off(name):
        return D.gen_off(name)

    def val(v8):
        rr = T.boot()
        for slot, v in v8.items():
            rr("hc_cal_set_u8", off(slot), v)
        return rr("hc_validate", T.VAL["HC_VAL_SRC_ACTIVE"])

    base = {"CAL_DBW_ENABLE": 0, "CFG_U_PIN_IDLE_VALVE": P0,
            "CFG_U_PIN_IDLE_VALVE2": P1}
    rc0 = val(dict(base, CFG_U_IDLE_ACTUATOR=0, CFG_U_PIN_IDLE_VALVE=0,
                   CFG_U_PIN_IDLE_VALVE2=0))
    check("V accepted: the old page (actuator 0, the former pads 0)",
          not rc0 & (CAP | CONF), "rc 0x%04X" % rc0)
    rc = val(dict(base, CFG_U_IDLE_ACTUATOR=1))
    check("V accepted: 2-wire valve on %d, DBW off" % P0,
          not rc & (CAP | CONF), "rc 0x%04X" % rc)
    rc = val(dict(base, CFG_U_IDLE_ACTUATOR=2))
    check("V accepted: 3-wire valve on %d + %d" % (P0, P1),
          not rc & (CAP | CONF), "rc 0x%04X" % rc)
    for label, v in (("a valve with DBW enabled", dict(base, CFG_U_IDLE_ACTUATOR=1,
                                                         CAL_DBW_ENABLE=1)),
                     ("a valve on 65 (no PWM unit)", dict(base, CFG_U_IDLE_ACTUATOR=1,
                                                          CFG_U_PIN_IDLE_VALVE=65)),
                     ("a 3-wire valve on one pin", dict(base, CFG_U_IDLE_ACTUATOR=2,
                                                       CFG_U_PIN_IDLE_VALVE2=P0)),
                     ("actuator 3", dict(base, CFG_U_IDLE_ACTUATOR=3))):
        rc = val(v)
        check("V refused: %s" % label, bool(rc & (CAP | CONF)), "rc 0x%04X" % rc)
    rc = val(dict(base, CFG_U_IDLE_ACTUATOR=1, CFG_U_PIN_CAM1_SOL=P0))
    check("V refused: the valve and a cam solenoid on %d (one owner)" % P0,
          bool(rc & CONF), "rc 0x%04X" % rc)


def grab_checks(r):
    print("\n-- the TPS Grab with one track --")
    r.stale.add(D.ADC_TPS2)
    r.set8("CAL_DBW_ENABLE", 0)
    t = 20_000
    for _ in range(20):                        # TPS2 stops publishing
        r.service(t)
        t += 10
    tps2_ok = r.call("hc_hal_ain_ok", (5,)) & 0xFF
    r.set_adc(D.ADC_TPS1, 321)
    r.service(t)
    r.set16("CAL_TPS1_MIN", 0)
    r.set16("CAL_TPS2_MIN", 777)
    v = r.call("eng_calib_grab", (1,)) & 0xFF
    t1 = (r.mem.r8(r.page_addr(D.gen_off("CAL_TPS1_MIN"))) << 8) | \
        r.mem.r8(r.page_addr(D.gen_off("CAL_TPS1_MIN")) + 1)
    t2 = (r.mem.r8(r.page_addr(D.gen_off("CAL_TPS2_MIN"))) << 8) | \
        r.mem.r8(r.page_addr(D.gen_off("CAL_TPS2_MIN")) + 1)
    check("G DBW off, TPS2 absent: Grab closed PASS, track 1 = 321, track 2 kept",
          not tps2_ok and v == 1 and t1 == 321 and t2 == 777,
          "tps2_ok %d verdict %d tps1 %d tps2 %d" % (tps2_ok, v, t1, t2))
    r.set8("CAL_DBW_ENABLE", 1)
    v = r.call("eng_calib_grab", (1,)) & 0xFF
    check("G DBW on, the same single track: refused (NOCHANNEL)", v == 3,
          "verdict %d" % v)


def main() -> int:
    print("=== the idle air valve on the linked image ===")
    r = valve_checks()
    validate_checks()
    grab_checks(r)
    print(f"\n{'IDLE VALVE PROOF PASSES' if not FAIL else 'IDLE VALVE PROOF FAILS'}"
          f" - {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
