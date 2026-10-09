#!/usr/bin/env python3
r"""me711_dtc_proof.py - trouble codes and the MIL request on the LINKED IMAGE.

    py tests\firmware\engine\me711_dtc_proof.py

The debounce core (firmware/diagnostics/hcdtc.c) is host-tested with its negative controls
(tests/host/test_hcdtc_host.py). This gate runs the image's hc_dtc_service()
(hcdtc711.c, FCODE) against the flags it maps, through c167sim:

  1  MAP fault with the MAP cavity routed: code 105 active after 1000 ms and
     not one pass before; MIL requested; freeze frame = the moment
  2  the same fault with the MAP cavity UNROUTED: nothing (a sensor the
     configuration does not use is not a trouble code)
  3  pedal fault with DBW off: nothing; with DBW on and the pedal routed: 2120
  4  a crank sync loss (trg_synclost increments): 335 on the next pass
  5  battery fault alone: 560 active, MIL NOT requested (no-MIL class)
  6  '!D' through hcts_target_cmd with the bytes TunerStudio sends: the next
     pass clears the history of healed faults; a present fault re-confirms
  7  engine protection (hclimp711.c): coolant over its limit -> ENG_CUT_LIMP
     above the limp rpm only, P0217 reported, a faulted sensor not judged
  8  that cut reaching the injectors on a synced 60-2 (3000 us -> 0)
  9  the check-engine lamp (hc_cel_service + hcio711.c) at the ASIC image:
     key-on ON 0..2999 ms (TX word 58 bit 0 CLEAR = P7.0 low = lamp on),
     OFF 3000..3999, then the MIL request; a MIL fault later lights it,
     healing puts it out, a key cycle re-runs the test; celEnable 0 (or
     pinMil not 47) drives nothing while celState still shows the logical
     command
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
ENG_CUT_LIMP = 0x0008
HDR = (ROOT / "firmware/config/hcconfig.h").read_text()
GEN = (ROOT / "firmware/generated/hc_config_generated.h").read_text()
ENG_ERR_MAP, ENG_ERR_PEDAL1, ENG_ERR_BATT = 0x0002, 0x0010, 0x0100
S_ACTIVE, S_STORED = 0x02, 0x04
REQ = 0xF700                  # near scratch (me711_preset_apply_proof's)


def off(name):
    m = re.search(r"#define\s+%s\s+(\d+)u?\b" % name, GEN) or \
        re.search(r"#define\s+%s\s+(\d+)u?\b" % name, HDR)
    return int(m.group(1))


def check(name, ok, detail=""):
    global FAIL
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<64} {detail}")
    FAIL += not ok


def pg8(x, name, v):
    x.m.w8(T.UNI_BASE + off(name), v & 0xFF)


def pg16(x, name, v):
    a = T.UNI_BASE + off(name)
    x.m.w8(a, (v >> 8) & 0xFF)                        # the page is big endian
    x.m.w8(a + 1, v & 0xFF)


def ram16(x, name, v):
    x.m.w16(T.sym(name) & 0xFFFF, v & 0xFFFF)


def dtc(x):
    """hc_dtc: p[HCDTC_MAX] x {t_ms u16, st u8, count u8}, then mil,
    n_active, n_stored, pad, ff_code, ff[4]. V97: the state is in external
    SRAM (TGT_RAM_DTC 0x1D00) and HCDTC_MAX is read from hcdtc.h."""
    hdr = (ROOT / "firmware/diagnostics/hcdtc.h").read_text()
    n = int(re.search(r"#define\s+HCDTC_MAX\s+(\d+)u", hdr).group(1))
    a = 0x380000 + 0x1D00
    m = x.m
    b = 4 * n
    return {"mil": m.r8(a + b), "na": m.r8(a + b + 1), "ns": m.r8(a + b + 2),
            "ff_code": m.r16(a + b + 4), "ff_rpm": m.r16(a + b + 6)}


def codes(x, mask):
    out = []
    for k in range(8):
        c = x.call("hc_dtc_code", mask, k)
        if not c:
            break
        out.append(c)
    return out


def passes(x, n):
    """hc_dtc_service() takes the UPTIME (tick_ms) - the rig keeps it"""
    for _ in range(n):
        x.t = (getattr(x, "t", 0) + 100) & 0xFFFF
        x.call("hc_dtc_service", x.t)


def limp(x, ms=10):
    x.lt = (getattr(x, "lt", 0) + ms) & 0xFFFF
    x.call("hc_limp_service", x.lt)


def fresh():
    x = T.Call()
    for n in ("CFG_U_PIN_MAP", "CFG_U_PIN_CLT", "CFG_U_PIN_IAT", "CFG_U_PIN_TPS1",
              "CFG_U_PIN_TPS2", "CFG_U_PIN_APP1", "CFG_U_PIN_APP2"):
        pg8(x, n, 255)                                # unrouted
    pg8(x, "CAL_DBW_ENABLE", 0)
    for n in ("eng_sensor_err", "trg_synclost", "trg_cycle_lost", "asic_timeouts",
              "hc_cfg_validation", "hc_ign_ovd_latch"):
        ram16(x, n, 0)
    x.call("hc_dtc_init")
    x.call("hc_boost_init")
    x.t = 0
    x.call("hc_dtc_service", 0)                       # the clock starts here
    passes(x, 1)
    return x


def cel_run(x, t, key=1, frames=3):
    x.call("hc_cel_service", t, key)
    for _ in range(frames):
        x.call("hc_io_frame")
    st = x.call("hc_cel_state")
    lamp = not (x.call("hc_io_word", 6) & 1)       # active LOW, P7.0
    return st, lamp


def cel_checks():
    print("\n=== check-engine lamp (celState, ASIC P7.0 image) ===")
    for enable, pin, label in ((1, 47, "enabled on 47"),
                               (0, 47, "celEnable 0"),
                               (1, 65, "pinMil 65 (not the lamp stage)")):
        x = fresh()
        x.call("hc_io_init")
        pg8(x, "CFG_U_CEL_ENABLE", enable)
        pg8(x, "CFG_U_PIN_MIL", pin)
        pg8(x, "CFG_U_CEL_TEST_ENABLE", 1)
        pg16(x, "CFG_U_CEL_TEST_ON_MS", 3000)
        pg16(x, "CFG_U_CEL_TEST_GAP_MS", 1000)
        cel_run(x, 0, key=0)
        seq = {t: cel_run(x, t) for t in (10, 2990, 3010, 3990, 4010, 6000)}
        cmd = [(seq[t][0] >> 8) & 1 for t in sorted(seq)]
        lamp = [seq[t][1] for t in sorted(seq)]
        stage = (seq[6000][0] >> 10) & 1
        driven = enable == 1 and pin == 47
        check("CEL %s: command ON,ON,OFF,OFF,MIL(0),MIL(0)" % label,
              cmd == [1, 1, 0, 0, 0, 0], str(cmd))
        check("CEL %s: the pin %s" % (label, "follows it" if driven
                                     else "is never driven"),
              lamp == ([True, True, False, False, False, False] if driven
                       else [False] * 6) and stage == int(driven),
              "lamp %s stage %d" % ([int(v) for v in lamp], stage))
        if not driven:
            continue
        # a MIL fault later: MAP routed + faulted, the debounce confirms it
        pg8(x, "CFG_U_PIN_MAP", 101)
        ram16(x, "trg_rpm", 2500)
        ram16(x, "eng_sensor_err", ENG_ERR_MAP)
        passes(x, 10)
        st, on = cel_run(x, 7000)
        check("CEL: a MIL fault after the test lights it (req + command)",
              on and (st >> 9) & 1 and (st >> 8) & 1 and st & 0xFF == 1,
              "celState 0x%04X" % st)
        ram16(x, "eng_sensor_err", 0)
        passes(x, 110)                              # healed
        st, on = cel_run(x, 7500)
        check("CEL: healed - the MIL request drops and the lamp goes out",
              not on and not (st >> 9) & 1, "celState 0x%04X" % st)
        cel_run(x, 7600, key=0)                     # key cycle in the run-on
        st, on = cel_run(x, 7700)
        check("CEL: a key cycle re-runs the lamp test", on and st & 0xFF == 2,
              "celState 0x%04X" % st)


def main() -> int:
    print("=== trouble codes on the linked image ===")
    x = fresh()
    check("clean: no code, no MIL", codes(x, S_ACTIVE | S_STORED) == [] and dtc(x)["mil"] == 0)

    # 1 MAP, routed
    pg8(x, "CFG_U_PIN_MAP", 101)
    ram16(x, "trg_rpm", 2500)
    ram16(x, "eng_sensor_err", ENG_ERR_MAP)
    passes(x, 9)
    before = codes(x, S_ACTIVE)
    passes(x, 1)
    d = dtc(x)
    check("MAP fault, routed: not at 900 ms, 105 active at 1000 ms, MIL",
          before == [] and codes(x, S_ACTIVE) == [105] and d["mil"] == 1,
          f"{before} -> {codes(x, S_ACTIVE)} mil {d['mil']}")
    check("... freeze frame = the moment (105 at 2500 rpm)",
          d["ff_code"] == 105 and d["ff_rpm"] == 2500, f"{d['ff_code']} @ {d['ff_rpm']}")

    # 2 unrouted
    x = fresh()
    ram16(x, "eng_sensor_err", ENG_ERR_MAP)
    passes(x, 30)
    check("MAP fault, MAP UNROUTED: no code", codes(x, S_ACTIVE | S_STORED) == [])

    # 3 pedal
    x = fresh()
    pg8(x, "CFG_U_PIN_APP1", 34)
    ram16(x, "eng_sensor_err", ENG_ERR_PEDAL1)
    passes(x, 10)
    off_dbw = codes(x, S_ACTIVE)
    pg8(x, "CAL_DBW_ENABLE", 1)
    passes(x, 5)
    check("pedal fault: nothing with DBW off, 2120 with DBW on",
          off_dbw == [] and codes(x, S_ACTIVE) == [2120], f"{off_dbw} -> {codes(x, S_ACTIVE)}")

    # 4 crank event
    x = fresh()
    ram16(x, "trg_synclost", 1)
    passes(x, 1)
    check("crank sync loss: 335 on the next pass", codes(x, S_ACTIVE) == [335],
          f"{codes(x, S_ACTIVE)}")

    # 5 battery, no MIL
    x = fresh()
    ram16(x, "eng_sensor_err", ENG_ERR_BATT)
    passes(x, 50)
    check("battery: 560 active, MIL NOT requested",
          codes(x, S_ACTIVE) == [560] and dtc(x)["mil"] == 0,
          f"{codes(x, S_ACTIVE)} mil {dtc(x)['mil']}")

    # 6 '!D'
    x = fresh()
    pg8(x, "CFG_U_PIN_MAP", 101)
    ram16(x, "trg_synclost", 1)
    ram16(x, "eng_sensor_err", ENG_ERR_MAP)
    passes(x, 12)
    ram16(x, "eng_sensor_err", 0)
    passes(x, 110)                                  # 11 s: both healed
    hist = codes(x, S_STORED)
    act = codes(x, S_ACTIVE)
    x.m.w8(REQ, ord("!"))
    x.m.w8(REQ + 1, ord("D"))
    x.call("hcts_target_cmd", REQ, 2)
    passes(x, 1)
    after = codes(x, S_STORED)
    check("healed faults stay in history until '!D'",
          sorted(hist) == [105, 335] and act == [], f"history {hist}, active {act}")
    check("... '!D' (TunerStudio's bytes) clears them", after == [], f"{after}")
    ram16(x, "eng_sensor_err", ENG_ERR_MAP)
    passes(x, 10)
    check("... and a present fault re-confirms", codes(x, S_ACTIVE) == [105])

    # 7 engine protection (hclimp711.c): coolant limp -> ENG_CUT_LIMP + P0217
    x = fresh()
    x.call("hc_limp_init")
    x.lt = 0
    x.call("hc_limp_service", 0)
    pg16(x, "CFG_U_CLT_MAX_X10", 11150)               # 115.0 C
    pg16(x, "CFG_U_CLT_LIMP_RPM", 0)                  # -> 3000
    ram16(x, "eng_clt_dc", 11200)                     # 120.0 C
    ram16(x, "trg_rpm", 2900)
    limp(x)
    below = x.u16("eng_fuelcut") & ENG_CUT_LIMP
    ram16(x, "trg_rpm", 3100)
    limp(x)
    above = x.u16("eng_fuelcut") & ENG_CUT_LIMP
    passes(x, 1)
    check("coolant 120 C > 115: no cut at 2900, fuel cut at 3100 (limp 3000)",
          not below and above, f"{below} / {above}")
    check("... and the DTC layer reports 217", 217 in codes(x, S_ACTIVE),
          f"{codes(x, S_ACTIVE)}")
    ram16(x, "eng_sensor_err", 0x0001)                # CLT fault: not judged
    limp(x)
    check("... a faulted coolant sensor is not judged",
          not (x.u16("eng_fuelcut") & ENG_CUT_LIMP))

    # 8 the limp cut reaches the injectors, end to end
    w = Wheel(60, 2, 1200, plan=True)
    wx = w.x
    wx.call("hc_limp_init")
    wx.lt = 0
    wx.call("hc_limp_service", 0)
    pg16(wx, "CFG_U_CLT_MAX_X10", 11150)
    pg16(wx, "CFG_U_CLT_LIMP_RPM", 1000)
    ram16(wx, "eng_clt_dc", 9000)                     # cold: no cut
    ram16(wx, "eng_sensor_err", 0)
    ram16(wx, "eng_fuelcut", 0)
    ram16(wx, "eng_ti_us", 3000)
    # V97: the scheduler fuels from the CYCLE's open time (two halves in
    # batch) + dead time per pulse
    ram16(wx, "eng_ti_base_us", 6000)
    ram16(wx, "eng_deadtime_us", 0)
    for _ in range(4):
        w.rev()
    limp(wx)
    base = wx.u16("dry_inj_pulse_us")
    ram16(wx, "eng_clt_dc", 11200)                    # hot: above 1000 rpm
    limp(wx)
    for _ in range(2):
        w.rev()
    cut = wx.u16("dry_inj_pulse_us")
    check("injectors: 3000 us cold, 0 when the coolant limp cuts (synced 60-2)",
          base == 3000 and cut == 0 and wx.u8("trg_state") >= 3,
          f"{base} -> {cut} us, state {wx.u8('trg_state')}")

    cel_checks()
    print(f"\n{'DTC PROOF PASSES' if not FAIL else 'DTC PROOF FAILS'} - {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
