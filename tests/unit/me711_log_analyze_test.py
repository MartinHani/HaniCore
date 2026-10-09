#!/usr/bin/env python3
"""me711_log_analyze_test.py - the post-log analysis on synthetic captures:
a clean run must produce no finding; each injected event must produce its
finding at the right time (and nothing is written back to any calibration).

    py tests\\unit\\me711_log_analyze_test.py
"""
from __future__ import annotations

import csv
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_log_analyze as A          # noqa: E402

COLS = ["t_mono", "rpm", "syncLossCount", "syncLossReason", "cycleSyncLost",
        "seqEnters", "seqLeaves", "seqInjMask", "dbwState", "dbwTargetX10",
        "dbwActualX10", "dbwDutyX10", "dbwFaults", "dbwPendFaults",
        "injDutyX10", "transWantUs", "transCorrUs", "lambda1X1000",
        "lambdaStatus", "tpsX10", "advX10", "schedOverdwell", "schedulerLate",
        "schedulerMissed", "schedulerMaxLatency", "fuelCut", "dtcMil",
        "sensorErr", "engLoad", "lambdaTarget"]
CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += 0 if ok else 1
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))


def base_row(i):
    return {"t_mono": i * 0.1, "rpm": 900, "syncLossCount": 0,
            "syncLossReason": 0, "cycleSyncLost": 0, "seqEnters": 4,
            "seqLeaves": 0, "seqInjMask": 15, "dbwState": 2,
            "dbwTargetX10": 5.0, "dbwActualX10": 5.1, "dbwDutyX10": 18.0,
            "dbwFaults": 0, "dbwPendFaults": 0, "injDutyX10": 8.0,
            "transWantUs": 3000, "transCorrUs": 0, "lambda1X1000": 1.0,
            "lambdaStatus": 1, "tpsX10": 5.0, "advX10": 12.0,
            "schedOverdwell": 0, "schedulerLate": 0, "schedulerMissed": 0,
            "schedulerMaxLatency": 300, "fuelCut": 0, "dtcMil": 0,
            "sensorErr": 0, "engLoad": 5.0, "lambdaTarget": 1.0}


def write(rows, d: Path):
    d.mkdir(parents=True, exist_ok=True)
    with (d / "decoded.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, COLS)
        w.writeheader()
        w.writerows(rows)
    (d / "metadata.json").write_text(json.dumps(
        {"identity": {"signature": "rusEFI HaniCore ME711 TEST"},
         "page_sha256": "ab" * 32, "tool_version": "1.5"}))


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    clean = [base_row(i) for i in range(200)]
    write(clean, tmp / "clean")
    A.main([str(tmp / "clean")])
    s = json.loads((tmp / "clean" / "analysis.json").read_text())
    check("a clean 20 s idle log: no finding", not s["findings"],
          str(s["counts"]))

    rows = [base_row(i) for i in range(300)]
    for r in rows[50:]:
        r["syncLossCount"] = 1                       # t 5.0
    for r in rows[80:]:
        r["cycleSyncLost"] = 1; r["seqLeaves"] = 4   # t 8.0
    for r in rows[100:110]:
        r["dbwActualX10"] = 15.0                     # 1 s off target
    for r in rows[120:130]:
        r["dbwDutyX10"] = 99.0                       # saturated 1 s
    rows[140]["dbwFaults"] = 0x0004
    rows[150]["injDutyX10"] = 97.0
    rows[160]["tpsX10"] = 5.0
    rows[161]["tpsX10"] = 40.0                       # 350 %/s
    rows[163]["lambda1X1000"] = 1.25                 # lean 0.2 s later
    rows[170]["transCorrUs"] = 2500                  # 83 % of 3000
    rows[180]["advX10"] = 52.0
    rows[190]["schedOverdwell"] = 1
    for r in rows[191:]:
        r["schedOverdwell"] = 1
    rows[200]["fuelCut"] = 2
    for r in rows[220:250]:
        r["lambdaStatus"] = 0                        # 3 s invalid
    rows[260]["rpm"] = 3000                          # 900 -> 3000 jump
    for r in rows[270:300]:                          # 3 s steady, 5 % lean
        r["rpm"] = 2000; r["engLoad"] = 30.0; r["lambda1X1000"] = 1.05
    write(rows, tmp / "events")
    A.main([str(tmp / "events")])
    s = json.loads((tmp / "events" / "analysis.json").read_text())
    F = s["findings"]
    want = {"crank_sync_lost": 5.0, "cycle_sync_lost": 8.0, "seq_leave": 8.0,
            "dbw_tracking": 10.0, "dbw_saturated": 12.0, "dbw_fault": 14.0,
            "inj_duty_critical": 15.0, "tipin_lean": 16.1,
            "transient_large": 17.0, "spark_advance": 18.0, "overdwell": 19.0,
            "fuel_cut": 20.0, "lambda_invalid": 22.0, "rpm_jump": 26.0}
    for k, tt in want.items():
        got = F.get(k, [])
        check("%-18s flagged at t=%.1f" % (k, tt),
              any(abs(e["t"] - tt) < 0.15 for e in got),
              str([e["t"] for e in got][:4]))
    ve = [c for c in s.get("ve_cells", []) if c["rpm_from"] == 2000
          and c["load_from"] == 30]
    check("VE evidence: the steady 2000 rpm / 30 % cell reads 5 % lean",
          ve and abs(ve[0]["ve_evidence_pct"] - 5.0) < 0.2
          and ve[0]["rows"] >= 15, str(ve))
    check("VE evidence: the clean idle cell is in the table, not a finding",
          any(c["rpm_from"] == 500 for c in s.get("ve_cells", []))
          and not any(e.get("rpm_from") == 500
                      for e in F.get("ve_evidence", [])))
    check("the DBW fault is decoded by name",
          any("throttle pair" in e["text"] for e in F.get("dbw_fault", [])))
    # V97: the wideband per bank - why, faults, the SSC, a flat lambda
    WCOLS = COLS + ["lamWhy", "lamFault", "cjTmo"]
    rows = [base_row(i) for i in range(400)]
    for r in rows:
        r.update(lamWhy=0x0100, lamFault=0, cjTmo=0)   # bank 2 off
    for r in rows[30:60]:
        r["lamWhy"] = 0x0108; r["lambdaStatus"] = 0     # bank 1 heating 3 s
    for r in rows[70:]:
        r["lamFault"] = 0x0200                          # bank 2 fault 2
    rows[90]["cjTmo"] = 3
    for r in rows[90:]:
        r["cjTmo"] = 3
    for i, r in enumerate(rows[150:400]):              # 25 s flat 1.000
        r["tpsX10"] = 5.0 + (i % 50)
    d = tmp / "wideband"
    d.mkdir(parents=True, exist_ok=True)
    with (d / "decoded.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, WCOLS)
        w.writeheader()
        w.writerows(rows)
    (d / "metadata.json").write_text("{}")
    A.main([str(d)])
    F = json.loads((d / "analysis.json").read_text())["findings"]
    li = F.get("lambda_invalid", [])
    check("wideband: bank 1 invalid 3 s named by its reason (RAMP)",
          any(e["t"] == 3.0 and e.get("bank") == 1 and e.get("why") == 8
              and "RAMP" in e["text"] for e in li), str(li))
    check("wideband: a bank whose source is off is not judged",
          not any(e.get("bank") == 2 for e in li))
    check("wideband: bank 2 latched fault decoded by name",
          any(e["t"] == 7.0 and e.get("bank") == 2 and "NO SENSOR"
              in e["text"] for e in F.get("lambda_fault", [])),
          str(F.get("lambda_fault")))
    check("wideband: a CJ120 SSC timeout is flagged",
          any(e["t"] == 9.0 for e in F.get("cj120_ssc_timeout", [])))
    check("wideband: a lambda flat to 0.005 while the throttle moved",
          bool(F.get("lambda_flat")), str(F.get("lambda_flat", ""))[:80])
    # V97: knock and VVT
    KCOLS = COLS + ["knockState", "knockRetardX10", "knockSelFault",
                    "vvt1State", "vvt1Err", "celState"] + [
        "knock%s%d" % (k, c) for k in ("Cnt", "Level", "Ret", "Ref")
        for c in range(1, 5)]
    rows = [base_row(i) for i in range(300)]
    for r in rows:
        r.update(knockState=1, knockRetardX10=0, knockSelFault=0,
                 vvt1State=0x10, vvt1Err=0.5)
        for c in range(1, 5):
            r.update(**{"knockCnt%d" % c: 0, "knockLevel%d" % c: 1.0,
                        "knockRet%d" % c: 0, "knockRef%d" % c: 200})
    for r in rows[50:]:
        r["knockCnt3"] = 1                           # t 5.0 cylinder 3
    for r in rows[50:60]:
        r["knockRetardX10"] = 2.2                    # 1 s of retard
    for r in rows[80:]:
        r["knockSelFault"] = 0x0200                  # t 8.0 sensor 2
    for r in rows[100:130]:
        r["knockState"] = 1 | (4 << 8)               # 3 s windows missed
    for r in rows[150:]:
        r["vvt1State"] = 0x10 | (2 << 8)             # t 15.0 stuck
    for r in rows[200:220]:
        r["vvt1State"] = 0x10; r["vvt1Err"] = 9.0    # 2 s off target
    for i, r in enumerate(rows):                     # key-on test ON/gap,
        r["celState"] = 0x0102 if i < 30 else (0x0003 if i < 40 else 0)
    for r in rows[240:]:
        r["celState"] = 0x0301                       # t 24 MIL, stage off
    d = tmp / "knockvvt"
    d.mkdir(parents=True, exist_ok=True)
    with (d / "decoded.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, KCOLS)
        w.writeheader()
        w.writerows(rows)
    (d / "metadata.json").write_text("{}")
    A.main([str(d)])
    SUM = json.loads((d / "analysis.json").read_text())
    F = SUM["findings"]
    check("knock: cylinder 3's detection at t=5.0",
          any(e["t"] == 5.0 and e.get("cyl") == 3 for e in F.get("knock", [])),
          str(F.get("knock"))[:80])
    check("knock: the retard span is flagged",
          any(e["t"] == 5.0 for e in F.get("knock_retard", [])))
    check("knock: sensor 2 fault decoded",
          any("[2]" in e["text"] for e in F.get("knock_sensor_fault", [])))
    check("knock: 3 s without windows named by the reason",
          any("WINDOW MISSED" in e["text"]
              for e in F.get("knock_not_measuring", [])),
          str(F.get("knock_not_measuring"))[:80])
    check("knock: per-cylinder level table for tuning",
          len(SUM.get("knock_cylinders", [])) == 4
          and "_knock_cyl" not in F)
    check("vvt: the stuck fault named, P0011",
          any("STUCK" in e["text"] and "P0011" in e["text"]
              for e in F.get("vvt_fault", [])), str(F.get("vvt_fault"))[:80])
    check("vvt: 2 s off target flagged",
          any(e["t"] == 20.0 for e in F.get("vvt_tracking", [])))
    check("cel: the key-on lamp test is not a finding",
          not F.get("cel_mismatch"), str(F.get("cel_mismatch"))[:80])
    check("cel: a MIL request with no lamp stage is flagged at t=24",
          any(e["t"] == 24.0 for e in F.get("cel_not_driven", [])))
    check("analysis.md written beside the capture",
          (tmp / "events" / "analysis.md").exists())
    # V98r2 tune check: the car page's VE Table Generator signature (load
    # axis 15..160 on an alpha-N page, cells at the limit) vs a clean page
    import me711_migrate_calibration as M
    ini_text = (hcpaths.TUNERSTUDIO / "hanicore_me711.ini").read_text(errors="replace")
    c = M.parse_ini(ini_text)
    pg = bytearray(4096)
    lo = c["loadSource"].bits[0]
    M._put(pg, c["loadSource"].off, 1, 1 << lo)              # alpha-N x p
    for i, v in enumerate([150 + 100 * i for i in range(16)]):  # 15..165 %
        M._put(pg, c["fuelLoadAx"].off + 2 * i, 2, v)
    top = int(c["veTable"].hi / c["veTable"].scale)
    for i in range(10):
        M._put(pg, c["veTable"].off + 2 * i, c["veTable"].width, top)
    bad = A.tune_check(bytes(pg), ini_text)
    for i in range(16):
        M._put(pg, c["fuelLoadAx"].off + 2 * i, 2, 60 * i)       # 0..90 %
    for i in range(10):
        M._put(pg, c["veTable"].off + 2 * i, c["veTable"].width, 800)
    good = A.tune_check(bytes(pg), ini_text)
    check("tune check: rows past 100 %, a 15 % first row and 10 saturated "
          "cells named; a 0..90 % axis is clean",
          len(bad) == 3 and "10 VE cell" in bad[2] and not good,
          "%s | %s" % (bad, good))
    session_checks()
    v100_checks()
    print("\n%d checks, %d failed" % (CHECKS, FAILS))
    return 1 if FAILS else 0


def wcsv(path: Path, rows: list):
    """rows[0] is the header dict's key order; every row a dict."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows(rows)


V100_CFG = {
    "firingOrder": "1-3-4-2 (inline 4)", "cylinders": 4,
    "injStrategy": "Batch - all injectors together, crank sync is enough",
    "_injStrategy": 0,
    "ignStrategy": "Wasted COP - one coil per cylinder, two halves",
    "_ignStrategy": 1,
    "syncMode": "Crank position only, 360 deg", "camPhaseMode": "Cam LEVEL",
    "camPhaseLevel": 0, "cam1Pattern": "Bosch quick-start",
    "trigAngleX10": -78.0, "syTeeth": 60, "syGap": 2,
    "loadSource": "Alpha-N x inlet pressure", "_loadSource": 1,
    "lambda1Source": "On-board LSU 4.2 controller", "_lambda1Source": 1,
    "lambda2Source": "Disabled",
    "lambdaHeatPolicy": "Ignition on - warm before the start",
    "_lambdaHeatPolicy": 1, "stftEnable": "On", "dbwEnable": "On",
    "dbwDevX10": 1.5, "dbwDevMs": 200.0, "etbLimpRpm": 0,
    "dbwKp": 0.08, "dbwAutocalDuty": 50.0, "dbwAutocalMs": 1000,
    "tps1Min": 157, "tps1Max": 973, "injFlowCcMin": 219, "revLimit": 6800,
    "fuelLoadAx": [15, 25, 30, 35, 45, 55, 65, 75, 85, 95, 100, 120, 140,
                   160, 180, 200],
    "fuelRpmAx": [500 * (i + 1) for i in range(16)],
    "ignLoadAx": [15 + 10 * i for i in range(16)],
    "ignRpmAx": [500 * (i + 1) for i in range(16)],
}


def v100_session(d: Path, bad=True, profile="max"):
    """A V100 multi-rate session folder. `bad` injects, in one capture, every
    defect class the V100 subject checks exist to name; `bad=False` is the
    negative control - the same shape, a healthy car."""
    N = 200
    fast = []
    for i in range(N):
        t = round(i * 0.05, 3)
        on = i >= 20                           # the first second is key-on only
        r = {"t": t, "wall": "-", "RPMValue": 900 if on else 0,
             "engineFlags": 1 if on else 0,
             "syncState": 4 if on else 0,
             "syncLossCount": 0, "toothCorrections": 0,
             "camPhaseCorrections": 0, "cycleSyncLost": 0, "camError": 0,
             "camPhaseNoAlt": 0, "crankNoiseEdges": 0,
             "schedulerExecuted": 100 * i, "schedulerLate": 0,
             "schedulerMissed": 0, "schedulerCancelled": 0,
             "schedulerMaxLatency": 300, "schedulerCaptureOverflow": 0,
             "schedOverdwell": 0, "schedOverdwellLatch": 0, "sparkSkips": 0,
             "ignOnMask": 0x3 if on else 0,
             # BATCH fires every injector as one group, so the mask the
             # firmware really writes is 0x00FF (HC_PLAN_SLOT_ALL), and the
             # key-on priming pulse writes the same thing. Neither is a
             # per-cylinder mask and neither may be read as one.
             "injOnMask": 0xFF if on else (0xFF if 5 <= i < 10 else 0),
             "primeState": 0 if on else (2 if 5 <= i < 10 else 1),
             "ignitionTiming": 10.0 if on else 0.0,
             "veValue": 50.0, "engLoad": 4.0 if bad else 40.0,
             "injectorPulseWidth": (7.27 if bad else 3.1) if on else 0.0,
             "TPSValue": 4.0 if bad else 40.0, "tpsX10": 4.0 if bad else 40.0,
             "pedalPosition": 0.0, "etbTarget": 5.0, "etbActual": 5.1,
             "dbwState": 2 if on else 1, "dbwTargetX10": 5.0,
             "dbwActualX10": 5.1, "dbwDutyX10": 18.0, "dbwFaults": 0,
             "dbwPendFaults": 0, "fuelCut": 0, "fuelCutFlags": 0,
             "limpCut": 0, "sensorErr": 0, "VBatt": 13.5, "ecuMs": i * 50,
             "nextIgnSlot": 1, "scheduledSpark": 100, "syncSeq": 0,
             "injDutyX10": 8.0, "advX10": 10.0 if on else 0.0}
        if bad:
            r["schedulerLate"] = 2 * i
            r["schedulerMissed"] = i // 10
            r["schedulerMaxLatency"] = 2642          # 2.11 ms, the V99 worst
            if i >= 100:
                r["toothCorrections"] = 3
            if i >= 120:
                r["camPhaseCorrections"] = 1
            if i == 90:
                r["ignOnMask"] = 0x10                # a 5th cylinder's bit
            if i == 95:
                r["injOnMask"] = 0x3                 # not all, under BATCH
            if i >= 130:
                r["schedOverdwell"] = 2
            if i >= 140:
                r["sparkSkips"] = 5
            if i >= 151:
                r["syncState"] = 1
                r["syncLossCount"] = 1
                r["cycleSyncLost"] = 1
            if i >= 170:
                r["syncLossCount"] = 2
            if i >= 160:
                r["dbwFaults"] = 0x0040              # off target too long
            if i >= 161:
                r["limpCut"] = 2                     # throttle-fault rev limit
        fast.append(r)
    wcsv(d / "fast.csv", fast)

    med = []
    for k in range(20):
        heat = 0.0 if bad else 45.0
        med.append({
            "t": round(k * 0.5, 3), "_rtt_ms": 56.0,
            "lambdaValue": 0.0 if bad else 0.98,
            "lambda2Value": 0.0, "targetLambda": 1.0,
            "lam1UrRaw": 1010 if bad else 185,
            "lam1RiX10": 6000.0 if bad else 81.2,
            "lam1IpUa": 0 if bad else -1292,
            "lamVeff": 0.0 if bad else 7.5, "heaterDuty": heat,
            "lambdaStatus": 0 if bad else 1,
            "lamWhy": (8 if k < 10 else 9) if bad else 0,
            "lamFault": 0, "lamDyn": 0 if bad else 1,
            "stftBank1": 0.0 if bad else 2.5, "stftBank2": 0.0,
            "stftState": 0 if bad else 8,
            "warmupEnrich": 120.0 if bad else 100.0,
            "warmupPct": 120.0 if bad else 100.0,
            "afterStartPm": 0.0, "fuelCorrection": 100.0 if bad else 104.0,
            "adc02_IPV": 416 if bad else 653,
            "adc01_TPS1": 157, "adc03_TPS2": 864, "adc05_UBAT": 700,
            "coolant": 85.0, "intake": 25.0, "mapKpaX10": 40.0,
            "knockState": 1, "vvt1State": 0, "vvt2State": 0,
            "idleState": 0, "boostState": 0, "cjErr": 0, "cjTmo": 0,
            "dbwTermP": 0.5, "dbwPendMs": 0.0, "celState": 0, "dtcMil": 0})
    wcsv(d / "medium.csv", med)

    slow = []
    for k in range(5):
        slow.append({"t": round(k * 2.0, 3), "rxReqs": 1000 * (k + 1),
                     "rxBytes": 57000 * (k + 1),
                     "rxFrameErr": 2 if bad else 0,
                     "rxHwOvr": 5 if bad else 0, "rxResync": 1 if bad else 0,
                     "rxOvf": 0, "rxEchoLost": 1 if bad else 0,
                     "rstBootCount": 1, "cfgWarnings": 0x40 if bad else 0,
                     "cfgValidation": 0, "nvmGeneration": 4, "nvmSource": 2,
                     "stackPeak": 180, "asicTimeouts": 0, "badVec": 0,
                     "lkgSteps": 0, "trigCfgTeeth": 60, "trigCfgGap": 2,
                     "trigCfgAngleX10": -78.0, "cj120Ident": 0x33,
                     "cj120Reg1": 0xC8, "lamMode": 3, "runOn": 0})
    wcsv(d / "slow.csv", slow)

    if bad:
        wcsv(d / "onchange.csv", [{"t": 2.0, "channel": "cfgWarnings",
                                   "from": 0, "to": 64}])
    groups = {
        "fast": {"period_s": 0.0, "windows": [[136, 28]], "bytes_per_row": 468,
                 "exchanges_per_row": 5, "channels": 123,
                 "missing": ["etbRef"] if bad else [], "rows": N,
                 "rows_per_s": 20.0 if profile == "max" else 5.0,
                 "mean_rtt_ms": 50.0},
        "medium": {"period_s": 0.5, "windows": [[96, 62]],
                   "bytes_per_row": 506, "exchanges_per_row": 5,
                   "channels": 105, "missing": [], "rows": 20,
                   "rows_per_s": 2.0, "mean_rtt_ms": 56.0},
        "slow": {"period_s": 2.0, "windows": [[0, 1248]],
                 "bytes_per_row": 1248, "exchanges_per_row": 1,
                 "channels": "whole block", "missing": [], "rows": 5,
                 "rows_per_s": 0.5, "mean_rtt_ms": 150.0}}
    (d / "metadata.json").write_text(json.dumps({
        "tool": "me711_vehicle_test", "tool_version": "2.0 (V100 multi-rate)",
        "logging_profile": profile,
        "rates_configured_s": {"fast": 0.0 if profile == "max" else 0.4,
                               "medium": 0.5, "slow": 2.0, "ring": 0.2},
        "identity": {"signature": "rusEFI HaniCore ME711 332F8D11",
                     "och_block": 1248},
        "kline_physical": {"mode": "DIRECT ECU",
                           "source": "operator confirmed",
                           "software_path_attempted": "DIRECT ECU",
                           "confirmed": True,
                           "transitions": [{"t": 1.0, "from": "OBD",
                                            "to": "DIRECT ECU",
                                            "why": "operator moved the KKL "
                                                   "to cavity 43"}] if bad
                           else []},
        "engine_config": dict(V100_CFG),
        "phases": {"kline": {"DIRECT ECU": {"stage": "OK"}},
                   "runtime": {"profile": profile, "groups": groups,
                               "rates_configured_s":
                                   {"fast": 0.0 if profile == "max" else 0.4,
                                    "medium": 0.5, "slow": 2.0, "ring": 0.2},
                               "reboots": 1 if bad else 0,
                               "snapshots": 3, "onchange": 1 if bad else 0,
                               "snapshot_log": [{"t": 0.0,
                                                 "reason": "session start",
                                                 "boot_count": 1}]}}}))
    with (d / "events.csv").open("w", newline="") as f:
        csv.writer(f).writerows(
            [["t_host", "ecu_ms", "seq", "type", "arg", "v1", "v2", "text"]])
    return d


def v100_checks():
    """V100: the multi-rate layout, every subject check, and the negative
    control - the same session shape with a healthy car must stay quiet."""
    tmp = Path(tempfile.mkdtemp(prefix="hc_v100_"))
    bad = v100_session(tmp / "bad", bad=True)
    A.main([str(bad)])
    an = json.loads((bad / "analysis.json").read_text())
    F, S = an["findings"], an["subjects"]

    check("V100 medium.csv is merged into the row stream",
          S["lambda"]["heat_policy"].startswith("Ignition on")
          and S["fuel"]["warmupEnrich"]["max"] == 120.0,
          str(S["fuel"].get("warmupEnrich")))
    # ---- trigger
    for k in ("trigger_sync_loss", "trigger_tooth_correction",
              "trigger_phase_correction", "trigger_phase_loss",
              "trigger_state_drop"):
        check("V100 trigger: %s" % k, bool(F.get(k)),
              (F.get(k) or [{}])[0].get("text", "")[:70])
    # ---- scheduler
    sch = S["scheduler"]
    check("V100 scheduler: Late/Executed and Missed/Executed computed",
          abs(sch["late_per_executed"] - 0.02) < 1e-6
          and sch["missed_per_executed"] > 0,
          (sch["late_per_executed"], sch["missed_per_executed"]))
    check("V100 scheduler: max latency in ms, against the documented bound",
          abs(sch["max_latency_ms"] - 2.114) < 0.01
          and bool(F.get("scheduler_latency"))
          and "documented polled bound" in F["scheduler_latency"][0]["text"],
          sch["max_latency_ms"])
    check("V100 scheduler: rpm correlation, per 500 rpm band",
          "500" in sch["by_rpm_band"]
          and sch["by_rpm_band"]["500"]["late_per_executed"] is not None,
          list(sch["by_rpm_band"]))
    check("V100 scheduler: the late and missed ratios are findings",
          bool(F.get("scheduler_late_ratio"))
          and bool(F.get("scheduler_missed_ratio")))
    # ---- ignition
    check("V100 ignition: requested timing summarised",
          S["ignition"]["requested_deg"]["median"] == 10.0,
          S["ignition"]["requested_deg"])
    for k in ("ignition_overdwell", "ignition_spark_cut",
              "ignition_mask_outside_config"):
        check("V100 ignition: %s" % k, bool(F.get(k)),
              (F.get(k) or [{}])[0].get("text", "")[:70])
    check("V100 ignition: a BATCH injOnMask that is neither 0 nor all "
          "cylinders", bool(F.get("injection_batch_mask")),
          (F.get("injection_batch_mask") or [{}])[0].get("text", "")[:80])
    check("V100 ignition: the slot-ALL mask 0xff (batch, and the key-on "
          "priming pulse) is NOT read as a cylinder mask",
          not F.get("injection_mask_outside_config")
          and F["injection_batch_mask"][0]["text"].endswith("['0x3']"),
          (F.get("injection_mask_outside_config"),
           F["injection_batch_mask"][0]["text"][-30:]))
    check("V100 ignition: the firing-order walk is SKIPPED under wasted COP",
          bool(F.get("_seq_order_skipped")) and not F.get("sequential_order"),
          (F.get("_seq_order_skipped") or [{}])[0].get("text", "")[:60])
    # ---- fuel
    check("V100 fuel: the load axis clamps idle into row 0",
          bool(F.get("fuel_axis_clamped_low"))
          and S["fuel"]["clamped_low_pct"] > 90.0,
          S["fuel"].get("clamped_low_pct"))
    check("V100 fuel: a rich idle pulse width is named with its norm",
          bool(F.get("fuel_rich_idle"))
          and "2.5..3.5" in F["fuel_rich_idle"][0]["text"],
          S["fuel"].get("idle_pw_ms_median"))
    check("V100 fuel: warm-up enrichment and an inert correction path",
          bool(F.get("fuel_warmup")) and bool(F.get("fuel_correction_inert")))
    # ---- lambda
    check("V100 lambda: the raw -> heater -> Ri -> Ip -> READY -> published "
          "chain is reported", all(S["lambda"].get(c) for c in
                                   ("lam1UrRaw", "lam1RiX10", "lambdaStatus")),
          {c: S["lambda"].get(c) for c in ("lam1UrRaw", "lam1RiX10")})
    check("V100 lambda: never published, and where the chain stops",
          bool(F.get("lambda_never_published"))
          and "chain stops at" in F["lambda_never_published"][0]["text"],
          (F.get("lambda_never_published") or [{}])[0].get("text", "")[:110])
    check("V100 lambda: Ri at the sentinel names the open/cold ambiguity",
          bool(F.get("lambda_ri_sentinel"))
          and "OPEN_CELL" in F["lambda_ri_sentinel"][0]["text"])
    check("V100 lambda: the heater policy was not honoured",
          bool(F.get("lambda_heat_policy")),
          (F.get("lambda_heat_policy") or [{}])[0].get("text", "")[:80])
    check("V100 lambda: closed loop never became active",
          bool(F.get("lambda_closed_loop_never_active")))
    check("V100 lambda: the fault/reason transitions are listed",
          bool(F.get("lambda_why_change")),
          (F.get("lambda_why_change") or [{}])[0].get("text", ""))
    # ---- ETB
    check("V101 ETB: AN2 is amplified TPS1, never a supply reference",
          not F.get("etb_reference_moved")
          and "tps_reference_counts" not in S["etb"]
          and "autocal_ratiometric" not in S["etb"])
    check("V101 ETB: the fault -> protection -> fuel cut chain",
          bool(F.get("etb_fault_cut_fuel")))
    check("V101 ETB: both independent tracks and diagnostic IPV are named",
          S["etb"]["autocal_measurement_channels"]
          == ["adc02_IPV", "adc01_TPS1", "adc03_TPS2"]
          and "scan skew" in S["etb"]["autocal_measurement_note"])
    ab = tmp / "autocal"
    v100_session(ab, bad=True)
    wcsv(ab / "autocal.csv", [
        {"t": round(i * 0.03, 3), "test": "AUTOCAL ETB (full)",
         # Historical V100 column spelling is accepted without reviving
         # its false interpretation. A complementary TPS2 is independent.
         "adc02_TPSREF": min(1023, round(4.16*(157+7*i))),
         "adc01_TPS1": 157+7*i, "adc03_TPS2": 864-7*i}
        for i in range(60)])
    A.main([str(ab)])
    ae = json.loads((ab / "analysis.json").read_text())
    r = ae["subjects"]["etb"]["amplified_tps1"]
    check("V101 ETB: historical alias, normal clipping, opposing tracks",
          r["clipped_rows"] > 0 and r["residual_max_counts"] <= 0.5
          and r["raw_pair_sum_span"] == [1021, 1021]
          and "etb_autocal_reference_model" not in ae["findings"], r)
    # ---- K-line
    kl = S["kline"]
    check("V100 K-line: the PHYSICAL mode and the software path are separate "
          "facts", kl["physical_mode"] == "DIRECT ECU"
          and kl["physical_confirmed"]
          and kl["software_paths_attempted"] == ["DIRECT ECU"], kl)
    check("V100 K-line: a confirmed mode raises no unconfirmed warning",
          not F.get("kline_mode_unconfirmed"))
    check("V100 K-line: the cable move is reported", bool(F.get(
        "kline_cable_moved")))
    check("V100 K-line: the AUTHORITATIVE counters, not a ring number",
          bool(F.get("kline_transport"))
          and "authoritative" in F["kline_transport"][0]["text"]
          and kl["authoritative_counters"]["rxFrameErr"]["max"] == 2,
          kl["authoritative_counters"].get("rxFrameErr"))
    # ---- the logger's own terms
    check("V100 logging: the profile, rates and per-group measurements",
          S["logging"]["profile"] == "max"
          and S["logging"]["groups"]["fast"]["rows_per_s"] == 20.0
          and S["logging"]["groups"]["slow"]["channels"] == "whole block",
          S["logging"]["groups"]["fast"])
    check("V100 logging: an unavailable channel is a finding, not a silence",
          bool(F.get("logger_channels_unavailable"))
          and "etbRef" in F["logger_channels_unavailable"][0]["text"])
    check("V100 logging: the reboot and the on-change records are surfaced",
          bool(F.get("ecu_rebooted")) and S["onchange"]
          and S["onchange"][0]["channel"] == "cfgWarnings", S.get("onchange"))
    check("V100 the session's configuration is in analysis.json",
          S["config"]["trigAngleX10"] == -78.0
          and S["config"]["fuelLoadAx"][0] == 15)
    md = (bad / "analysis.md").read_text(encoding="utf-8")
    check("V100 analysis.md states the session's own terms and the scheduler",
          "This session's own terms" in md and "## Scheduler" in md
          and "DIRECT ECU" in md, md.count("##"))

    # ---- the negative control
    good = v100_session(tmp / "good", bad=False)
    A.main([str(good)])
    gf = json.loads((good / "analysis.json").read_text())["findings"]
    quiet = ("trigger_sync_loss", "trigger_tooth_correction",
             "trigger_phase_correction", "trigger_phase_loss",
             "trigger_state_drop", "scheduler_latency",
             "scheduler_late_ratio", "scheduler_missed_ratio",
             "ignition_overdwell", "ignition_spark_cut",
             "ignition_mask_outside_config", "injection_batch_mask",
             "fuel_axis_clamped_low", "fuel_rich_idle", "fuel_warmup",
             "fuel_correction_inert", "lambda_never_published",
             "lambda_ri_sentinel", "lambda_heat_policy",
             "lambda_closed_loop_never_active", "etb_reference_moved",
             "etb_fault_cut_fuel", "kline_mode_unconfirmed",
             "kline_cable_moved", "logger_channels_unavailable",
             "ecu_rebooted")
    noisy = [k for k in quiet if gf.get(k)]
    check("V100 negative control: a healthy session raises none of the %d "
          "subject findings" % len(quiet), not noisy, noisy)

    # ---- the D3 comparison
    red = v100_session(tmp / "reduced", bad=True, profile="reduced")
    rc = A.compare([str(bad), str(red)], out=str(tmp))
    cmpmd = (tmp / "scheduler_compare.md").read_text(encoding="utf-8")
    check("V100 --compare: both profiles, both rates and both ratios in one "
          "table", rc == 0 and "| max |" in cmpmd and "| reduced |" in cmpmd
          and "late_per_executed" in cmpmd, cmpmd.count("|"))
    rc = A.compare([str(bad), str(bad)], out=None)
    check("V100 --compare refuses to answer D3 from two sessions on the SAME "
          "profile", rc == 0)


def session_checks():
    """V99 BACKWARD COMPATIBILITY: a V99 me711_vehicle_test.py session folder
    (fast.csv + events.csv + etb_events.csv + kline.csv, no medium.csv and no
    V100 metadata) must still analyse, with the V100 fixes intact."""
    d = Path(tempfile.mkdtemp(prefix="hc_sess_"))
    (d / "metadata.json").write_text(json.dumps({
        "tool": "me711_vehicle_test",
        "engine_config": {"firingOrder": "1-3-4-2 (inline 4)"},
        "identity": {"signature": "rusEFI HaniCore ME711 8482315E"}}))
    hdr = ["t", "RPMValue", "lambdaValue", "injectorPulseWidth",
           "engineFlags", "syncSeq", "nextIgnSlot", "scheduledSpark"]
    order = [1, 3, 4, 2, 1, 3, 4, 2, 1, 4, 3, 2]        # one bad step 1 -> 4 -> 3
    with (d / "fast.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(hdr)
        for i in range(400):
            t = i * 0.02
            pw = 2.0 if t < 4.0 else 6.0              # VE tripled at 4 s
            lam = 1.04 + (0.002 if i % 2 else 0.0)    # stuck ~1.04
            sl = order[i % len(order)] if i < 12 else order[i % 4]
            w.writerow([t, 900, lam, pw, 1, (1 << 8) | 4, sl, 100 + i])
    ev = [["t_host", "ecu_ms", "seq", "type", "arg", "v1", "v2", "text"],
          [1.0, 0, 1, "DBW", 3, 1800, 64,
           "ETB CONTROL: FAULT, faults OFF TARGET TOO LONG"],
          [1.01, 0, 2, "LIMP", 0, 1800, 2,
           "PROTECTION: THROTTLE FAULT rev limit (1500 rpm) @ 1800 rpm"],
          [1.02, 0, 3, "FUELCUT", 0, 1800, 8,
           "FUEL CUT -> engine protection @ 1800 rpm"],
          [2.0, 0, 4, "SYNC_LOSS", 3, 2500, 1,
           "SYNC: CRANK LOST #1 - missing gap @ 2500 rpm"],
          [5.0, 0, 5, "SEQ", 1, 900, 10, "SEQUENTIAL: ON"],
          [7.0, 0, 6, "ENGINE", 0, 0, 120, "ENGINE: STOPPED"],
          [7.5, 0, 7, "LAMDYN", 16, 900, 2,
           "LAMBDA: bank 1 dynamics NOT proven (span 2 counts)"]]
    with (d / "events.csv").open("w", newline="") as f:
        csv.writer(f).writerows(ev)
    with (d / "etb_events.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "test", "event", "phase", "tps1", "tps2", "drive",
                    "hold1", "push1", "moved", "limit", "disp", "hold_ms",
                    "detail"])
        w.writerow([3.0, "AUTOCAL ETB (full)", "RESULT FAIL NOT A STOP A", "",
                    0, 0, 0, 700, 845, 145, 108, 650, 1000, 145])
    with (d / "kline.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "path", "stage", "baud", "cmd", "ok", "error",
                    "latency_ms", "bytes", "attempt"])
        w.writerow([6.0, "DIRECT ECU", "runtime dropout", 115200, "-", 1,
                    "down 1.20 s", 1200, 0, 1])
        w.writerow([5.9, "DIRECT ECU", "runtime", 115200, "O", 0,
                    "timeout: no bytes", 300, 0, 1])
    rc = A.main([str(d)])
    an = json.loads((d / "analysis.json").read_text())["findings"]
    pfc = an.get("protection_fuel_cut", [{}])[0].get("text", "")
    check("session: ETB fault -> protection fuel cut reported as ONE chain",
          rc == 0 and "caused by the ETB fault" in pfc, pfc[:90])
    check("session: sync loss with its reason",
          "missing gap" in an.get("sync_lost", [{}])[0].get("text", ""))
    check("session: lambda static while the fuel tripled",
          bool(an.get("lambda_static")),
          (an.get("lambda_static") or [{}])[0].get("text", "")[:80])
    check("session: firmware 'dynamics not proven' surfaced",
          bool(an.get("lambda_dynamics")))
    check("session: sequential order violation found (1-4-3)",
          bool(an.get("sequential_order")),
          (an.get("sequential_order") or [{}])[0].get("text"))
    check("session: stall right after sequential ON = inverted phase hint",
          bool(an.get("sequential_stall")))
    check("session: ETB NOT A STOP with the numbers",
          "moved 145" in (an.get("etb_procedure_failed") or [{}])[0]
          .get("text", ""))
    check("session: K-line dropout + errors",
          bool(an.get("kline_dropout")) and bool(an.get("kline_errors")))


if __name__ == "__main__":
    sys.exit(main())
