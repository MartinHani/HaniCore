#!/usr/bin/env python3
r"""
me711_dbw_audit_proof.py - the V97 DBW audit changes, executed in the linked
image (c167sim), through the controller's own accessors.

    py tests\firmware\dbw\me711_dbw_audit_proof.py            the image me711_image names
    py tests\firmware\dbw\me711_dbw_audit_proof.py --control  V96 frozen: must FAIL

WHAT CHANGED (the maintainer's design notes "V97 audit"; each compared with the
AWT's own Bosch DLR, an OEM-firmware analysis script (not published)):

  A  BATTERY COMPENSATION   duty = (P+I+D+FF) x 13.5 V / battery, factor held
                            to 0.70..1.80; dbwBattComp 1 = off.
  B  SENSOR DEBOUNCE        a TPS/APP range or pair error inside
                            dbwFaultDebounceMs disables the bridge immediately (no latch) and is forgotten when it clears; one
                            that lasts latches; 0 = latch on the first sample.
  C  CFG IS LIVE            a page that does not describe a throttle refuses
                            (OFF, bit CFG) and runs again once fixed - no
                            reboot (V96 latched it).
  D  KEY-ON CLEARS          a latched fault clears on a key-on edge with the
                            engine stopped, not with rpm, not without an edge.
  E  COMMISSION OVERRIDE    hc_dbw_override() runs the closed loop to a set
                            target with dbwEnable 0 and no usable pedal;
                            0xFFFF hands it back (OFF).
  F  DEFAULT CONFIRM TIME   a fresh page carries 50 ms: one bad sample and a
                            40 ms burst release the bridge without latching;
                            a lasting fault latches at 50..60 ms.

--control runs HaniCore_ME711_v96_wideband: it latches a one-sample glitch
and has none of A/D/E, so it must fail.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

CONTROL_STEM = "HaniCore_ME711_v96_wideband"
if "--control" in sys.argv:
    env = dict(os.environ, HANICORE_ME711_STEM=CONTROL_STEM)
    r = subprocess.run([sys.executable, __file__], env=env)
    ok = r.returncode != 0
    print("\nCONTROL (%s): %s" % (CONTROL_STEM,
          "FAILS as it must" if ok else "PASSED - the gate cannot tell"))
    raise SystemExit(0 if ok else 1)

import me711_dbw_control_proof as DC      # noqa: E402

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    FAILS += 0 if ok else 1
    print("  [%s] %-62s %s" % ("PASS" if ok else "FAIL", name, detail))


def term(r, name):
    return r.call("hc_dbw_term", (DC.hdr_int(DC.DBW_H, "DBW_T_" + name),))


def sgn(v):
    return v - 0x10000 if v & 0x8000 else v


def batt(r, dv):
    r.mem.w16(DC.sym("eng_batt_dv") & 0xFFFF, dv)
    fs = r.call("cfg_u16", (62,))
    r.set_adc(5, (dv * 1023 + fs - 1) // fs)


def run_to(r, t, n):
    for _ in range(n):
        r.service(t)
        t += 10
    return t


def vector_a(r):
    print("\n-- A battery compensation --")
    r.baseline()
    r.set8("CFG_U_DBW_BATT_COMP", 0)
    r.pedal(320)
    r.plate(300)
    t = run_to(r, 10_000, 8)
    for dv, want in ((135, 1000), (90, 1500), (60, 1800), (180, 750)):
        batt(r, dv)
        r.service(t); t += 10
        vf = term(r, "VFAC")
        out = sgn(term(r, "OUT"))
        duty = r.s()["duty"]
        exp = min(800, abs(out) * vf // 1000)
        check("%.1f V: factor %.3f, duty = |PID+FF| x factor" % (dv / 10, want / 1000),
              vf == want and abs(duty - exp) <= 1,
              "factor %d out %d duty %d want %d" % (vf, out, duty, exp))
    r.set8("CFG_U_DBW_BATT_COMP", 1)
    batt(r, 90)
    r.service(t); t += 10
    vf = term(r, "VFAC")
    out = sgn(term(r, "OUT"))
    duty = r.s()["duty"]
    check("dbwBattComp Off: factor 1.000, duty = |PID+FF|",
          vf == 1000 and abs(duty - min(800, abs(out))) <= 1,
          "factor %d out %d duty %d" % (vf, out, duty))


def vector_b(r):
    print("\n-- B sensor-fault debounce --")
    r.baseline()
    batt(r, 135)
    r.set16("CFG_U_DBW_FAULT_DEBOUNCE_MS", 140)
    r.pedal(400)
    r.plate(380)
    t = run_to(r, 20_000, 10)
    s0 = r.s()
    check("baseline RUN", s0["state"] == DC.ST["RUN"], str(s0["state"]))
    # TPS2 disagrees by 30 % for 100 ms
    good2 = 100 + 380 * 800 // 1000
    r.set_adc(DC.ADC_TPS2, good2 + 240)
    for _ in range(10):
        r.service(t); t += 10
    pend = term(r, "PEND")
    s = r.s()
    check("100 ms glitch: INIT, no latch, motor OFF, pending bit shown",
          s["state"] == DC.ST["INIT"] and s["faults"] == 0 and s["on"] == 0
          and pend == DC.F["TPS_PAIR"],
          "state %d faults 0x%X on %d pend 0x%X" % (s["state"], s["faults"],
                                                     s["on"], pend))
    duties = set()
    r.set_adc(DC.ADC_TPS2, good2 + 240)
    for _ in range(3):
        r.service(t); t += 10
        duties.add(r.s()["duty"])
    check("while pending the output stays OFF", duties == {0},
          str(sorted(duties)))
    r.set_adc(DC.ADC_TPS2, good2)
    t = run_to(r, t, 6)
    s = r.s()
    check("glitch gone: pending cleared, RUN continues",
          s["state"] == DC.ST["RUN"] and term(r, "PEND") == 0
          and s["faults"] == 0, "state %d" % s["state"])
    # a lasting fault latches at the debounce, not before
    r.set_adc(DC.ADC_TPS2, good2 + 240)
    t0 = t
    latched_at = None
    for _ in range(25):
        r.service(t)
        if latched_at is None and r.s()["state"] == DC.ST["FAULT"]:
            latched_at = t - t0
        t += 10
    s = r.s()
    check("lasting pair error latches TPS_PAIR at 140..150 ms, bridge off",
          latched_at is not None and 140 <= latched_at <= 150
          and s["faults"] & DC.F["TPS_PAIR"] and s["on"] == 0,
          "latched after %s ms faults 0x%X" % (latched_at, s["faults"]))
    # debounce 0 = the first bad sample (V96 behaviour, kept selectable)
    r.baseline()
    r.set16("CFG_U_DBW_FAULT_DEBOUNCE_MS", 0)
    r.pedal(400)
    r.plate(380)
    t = run_to(r, 40_000, 10)
    r.set_adc(DC.ADC_TPS2, good2 + 240)
    r.service(t)
    s = r.s()
    check("dbwFaultDebounceMs 0: the first bad sample latches",
          s["state"] == DC.ST["FAULT"] and s["faults"] & DC.F["TPS_PAIR"],
          "state %d faults 0x%X" % (s["state"], s["faults"]))


def vector_c(r):
    print("\n-- C configuration refusal is live --")
    r.baseline()
    r.pedal(300)
    r.plate(300)
    t = run_to(r, 50_000, 10)
    r.set16("CAL_TPS1_MAX", 110)          # span 10 counts: not a sensor
    t = run_to(r, t, 2)
    s = r.s()
    check("span too small: OFF with CFG, bridge down",
          s["state"] == DC.ST["OFF"] and s["faults"] & DC.F["CFG"]
          and s["on"] == 0, "state %d faults 0x%X" % (s["state"], s["faults"]))
    r.set16("CAL_TPS1_MAX", 900)
    t = run_to(r, t, 10)
    s = r.s()
    check("fixed: RUN again, CFG bit gone, no reboot",
          s["state"] == DC.ST["RUN"] and not s["faults"] & DC.F["CFG"],
          "state %d faults 0x%X" % (s["state"], s["faults"]))


def vector_d(r):
    print("\n-- D key-on clears a latched fault --")
    r.baseline()
    r.set16("CFG_U_DBW_FAULT_DEBOUNCE_MS", 0)
    r.pedal(300)
    r.plate(300)
    t = run_to(r, 60_000, 10)
    r.set_adc(DC.ADC_TPS2, 900)
    t = run_to(r, t, 2)
    r.plate(300)
    c0 = term(r, "CLEARS")
    r.call("hc_dbw_key", (1, 0))
    t = run_to(r, t, 5)
    s1 = r.s()
    r.call("hc_dbw_key", (0, 0))
    r.call("hc_dbw_key", (1, 800))
    t = run_to(r, t, 5)
    s2 = r.s()
    check("no edge / key-on with rpm: stays latched",
          s1["state"] == DC.ST["FAULT"] and s2["state"] == DC.ST["FAULT"],
          "%d %d" % (s1["state"], s2["state"]))
    r.call("hc_dbw_key", (0, 0))
    r.call("hc_dbw_key", (1, 0))
    s3 = r.s()
    t = run_to(r, t, 10)
    s4 = r.s()
    check("key-on edge, engine stopped: cleared, counted, back to RUN",
          s3["faults"] == 0 and term(r, "CLEARS") == c0 + 1
          and s4["state"] == DC.ST["RUN"],
          "faults 0x%X clears %d state %d" % (s3["faults"], term(r, "CLEARS"),
                                              s4["state"]))


def vector_e(r):
    print("\n-- E commissioning override --")
    r.baseline()
    r.set8("CAL_DBW_ENABLE", 0)
    r.set_adc(DC.ADC_APP1, 900)            # pedal pair disagrees
    r.set_adc(DC.ADC_APP2, 100)
    r.plate(200)
    t = run_to(r, 70_000, 3)
    check("dbwEnable 0: OFF", r.s()["state"] == DC.ST["OFF"])
    r.call("hc_dbw_override", (400,))
    t = run_to(r, t, 10)
    s = r.s()
    check("override 40 %: RUN to target 40.0 %, pedal ignored",
          s["state"] == DC.ST["RUN"] and s["target"] == 400 and s["faults"] == 0,
          "state %d target %d faults 0x%X" % (s["state"], s["target"],
                                              s["faults"]))
    r.call("hc_dbw_override", (0xFFFF,))
    t = run_to(r, t, 2)
    s = r.s()
    check("override released: OFF, bridge down",
          s["state"] == DC.ST["OFF"] and s["on"] == 0, str(s["state"]))


def vector_f(r, default_ms):
    print("\n-- F default sensor-fault confirm time --")
    check("a fresh page carries dbwFaultDebounceMs 50", default_ms == 50,
          "%s ms" % default_ms)
    r.baseline()                       # leaves the debounce at the default
    r.set16("CFG_U_DBW_FAULT_DEBOUNCE_MS", default_ms)
    batt(r, 135)
    r.pedal(400)
    r.plate(380)
    t = run_to(r, 70_000, 20)
    good2 = 100 + 380 * 800 // 1000
    for n_bad in (1, 4):               # one 10 ms service, then 40 ms
        r.set_adc(DC.ADC_TPS2, good2 + 240)
        off = []
        for _ in range(n_bad):
            r.service(t); t += 10
            off.append(r.s()["on"] == 0)
        r.set_adc(DC.ADC_TPS2, good2)
        t = run_to(r, t, 8)
        s = r.s()
        check("%d ms bad pair: bridge off at once, no latch, RUN again" % (10 * n_bad),
              all(off) and s["state"] == DC.ST["RUN"] and s["faults"] == 0,
              "off %s state %d faults 0x%X" % (off, s["state"], s["faults"]))
    r.set_adc(DC.ADC_TPS2, good2 + 240)
    t0, latched_at = t, None
    for _ in range(12):
        r.service(t)
        if latched_at is None and r.s()["state"] == DC.ST["FAULT"]:
            latched_at = t - t0
        t += 10
    s = r.s()
    check("a lasting pair error latches TPS_PAIR at 50..60 ms, bridge off",
          latched_at is not None and 50 <= latched_at <= 60
          and s["faults"] & DC.F["TPS_PAIR"] and s["on"] == 0,
          "latched after %s ms faults 0x%X" % (latched_at, s["faults"]))


def main() -> int:
    import me711_image as PI
    print("=== V97 DBW audit changes - %s ===" % PI.STEM)
    r = DC.Rig()
    a = r.page_addr(DC.gen_off("CFG_U_DBW_FAULT_DEBOUNCE_MS"))
    default_ms = (r.mem.r8(a) << 8) | r.mem.r8(a + 1)
    try:
        vector_f(r, default_ms)
    except SystemExit as e:
        check("vector_f could not run", False, str(e))
    for v in (vector_a, vector_b, vector_c, vector_d, vector_e):
        try:
            v(r)
        except SystemExit as e:
            check(v.__name__ + " could not run", False, str(e))
    print("\n%d checks, %d failed" % (CHECKS, FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
