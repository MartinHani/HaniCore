#!/usr/bin/env python3
r"""
me711_log_analyze.py - summarise a vehicle capture into evidence.

    py tools\vehicle\me711_log_analyze.py <VEHICLE_CAPTURE_... folder> [--out DIR]
    py tools\vehicle\me711_log_analyze.py <..._vehicle_test session folder>
    py tools\vehicle\me711_log_analyze.py --compare <session A> <session B>

V100: the multi-rate session layout (fast.csv + medium.csv + slow.csv +
onchange.csv + snapshots.csv + the split ring files) is merged into one row
stream, and the per-subject checks below run against the session's OWN
metadata - the configuration decoded from its page, the logging profile and
the operator-confirmed K-line physical mode - so a check that the
configuration makes meaningless does not run at all. `--compare` prints the
scheduler-load comparison the D3 question needs (profile, measured rates,
schedulerExecuted / Late / Missed / MaxLatency and the two ratios, per rpm
band), which is why the next car test takes two captures.

V99: A me711_vehicle_test.py SESSION (fast.csv + slow.csv + events.csv +
kline.csv + etb_events.csv) is recognised by its metadata. The fast rows,
with the slow channels carried forward, go through every check below, and
the session checks add what only the firmware's EVENT RING can say:
  sync / phase losses with their reason and rpm; fuel and spark cuts with
  their CAUSE chain (an ETB fault -> engine protection -> the 1500 rpm fuel
  cut is reported as ONE finding); overdwell auto-fires and latches; the
  ETB procedures' results with the stop-test numbers; lambda STUCK / not
  proven (the firmware's dynamics check) AND an independent check that the
  fuel command changed >= 25 % while lambda stayed within 0.02 (window
  3 s, valid lambda, running, no cut); sequential ignition order against the
  page's firing order (the fast rows' last spark slot); a stall within 5 s
  of sequential ignition switching on (the signature of an inverted cam
  level assignment); K-line dropouts, retries and protocol errors.

Reads decoded.csv (engineering units, one row per logger cycle) and
metadata.json from tools/vehicle/me711_vehicle_capture.py and writes analysis.json
(machine-readable) and analysis.md (human) into the capture folder. It flags
what a first look at a car log has to answer - and changes NOTHING: no
calibration is proposed as a number, only where to look and why.

FRESHNESS: FAST and FAST2 channels are fresh on every row; AUX channels are
fresh on one row in three (metadata "aux_interleave"). A finding built on an
AUX channel says so ("aux").

Checks (each a list of events with time, values and a sentence):
  crank sync lost / cycle sync lost / sequential entered and left
  DBW: |target - actual| > 5 % for 0.2 s while in closed loop; duty at
       >= 95 % for 0.3 s; latched faults (decoded); sensor faults pending
  injector duty > 85 % (warn) / > 95 % (critical)
  lambda: invalid while running (per bank, with the dominant lamWhy
       reason), latched wideband faults, CJ120 SSC timeouts, a valid lambda
       flat to 0.005 for 20 s while the throttle moved (open pump line);
       after a tip-in (TPS rising > 50 %/s) a
       lean spike (> 1.10) or rich dip (< 0.85) within 0.6 s
  transient share |transCorrUs| > 60 % of the want
  spark advance outside -10..45 deg; overdwell releases; scheduler late /
       missed counts rising; max latency > 1 ms
  fuel cuts by reason; engine protection; MIL request; sensor error bits
  rpm discontinuities (> 1500 rpm between two rows above 500 rpm)
  VE evidence: measured / target lambda per 500 rpm x 10 % load cell over
       rows steady for 1 s (valid lambda, no cut); cells off by >= 3 % are
       findings, every cell is in analysis.json "ve_cells"
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

DBW_FAULT_BITS = {0x0001: "calibration", 0x0002: "pedal pair",
                  0x0004: "throttle pair", 0x0008: "pedal range",
                  0x0010: "throttle range", 0x0020: "bridge SF",
                  0x0040: "off target too long", 0x0080: "no sensor source",
                  0x0100: "outputs not live"}
CUT_BITS = {1: "overrun (DFCO)", 2: "rev limiter", 4: "overboost",
            8: "engine protection"}
AUX_START, FAST2_START, OCH2_START = 724, 950, 1024
# V97: the wideband's own words (firmware/sensors/hcwb.h via ts_semantics_me711)
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
    import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
    import ts_semantics_me711 as _SEM
    _FAM = {f[0]: f[3] for f in _SEM.INDEX_FAMILIES}
    LAM_WHY = _FAM.get("hcLamWhyList", {})
    LAM_FAULT = _FAM.get("hcLamFaultList", {})
    KNOCK_WHY = _FAM.get("hcKnockWhyList", {})
    VVT_FAULT = _FAM.get("hcVvtFaultList", {})
except Exception:            # the analyser must run from a copied folder too
    LAM_WHY, LAM_FAULT, KNOCK_WHY, VVT_FAULT = {}, {}, {}, {}


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def bits_text(v, table):
    v = int(v or 0)
    return ", ".join(n for b, n in table.items() if v & b) or "-"


class Log:
    def __init__(self, folder: Path):
        self.dir = folder
        self.meta = json.loads((folder / "metadata.json").read_text()) \
            if (folder / "metadata.json").exists() else {}
        with (folder / "decoded.csv").open(newline="", encoding="utf-8") as f:
            self.rows = [_analog_names(r) for r in csv.DictReader(f)
                         if r.get("t_mono") not in (None, "", "t_mono")]
        self.t = [num(r["t_mono"]) or 0.0 for r in self.rows]
        chan = {}
        p = folder / "channels.json"
        if p.exists():
            chan = json.loads(p.read_text())
        self.aux = {n for n, c in chan.items()
                    if AUX_START <= c.get("offset", 0) < FAST2_START
                    or c.get("offset", 0) >= OCH2_START}

    def col(self, name):
        return [num(r.get(name)) for r in self.rows]

    def has(self, name):
        return bool(self.rows) and name in self.rows[0]


def rising(values):
    """indices where a counter increased"""
    out, prev = [], None
    for i, v in enumerate(values):
        if v is not None and prev is not None and v > prev:
            out.append(i)
        if v is not None:
            prev = v
    return out


def spans(cond, t, min_s):
    """(start, end) index pairs where cond holds for >= min_s"""
    out, s = [], None
    for i, c in enumerate(cond):
        if c and s is None:
            s = i
        if (not c or i == len(cond) - 1) and s is not None:
            e = i if c else i - 1
            if t[e] - t[s] >= min_s:
                out.append((s, e))
            s = None
    return out


def analyse(log: Log) -> dict:
    t, R = log.t, log.rows
    F = {}

    def add(key, i, text, **vals):
        F.setdefault(key, []).append(dict(t=round(t[i], 3), text=text,
                                          **{k: v for k, v in vals.items()}))

    rpm = log.col("rpm")
    running = [(v or 0) >= 400 for v in rpm]
    for i in rising(log.col("syncLossCount")):
        add("crank_sync_lost", i, "crank sync lost (reason %s)"
            % R[i].get("syncLossReason", "?"), rpm=rpm[i])
    for i in rising(log.col("cycleSyncLost")):
        add("cycle_sync_lost", i, "cycle (720 deg) sync withdrawn - the "
            "sequential cylinders return to the fallback", rpm=rpm[i])
    for i in rising(log.col("seqEnters")):
        add("seq_enter", i, "cylinder(s) entered true sequential",
            mask=R[i].get("seqInjMask"), rpm=rpm[i])
    for i in rising(log.col("seqLeaves")):
        add("seq_leave", i, "cylinder(s) left sequential (fallback)",
            mask=R[i].get("seqInjMask"), rpm=rpm[i])

    # ---- DBW
    st, tg, ac, du = (log.col("dbwState"), log.col("dbwTargetX10"),
                      log.col("dbwActualX10"), log.col("dbwDutyX10"))
    if log.has("dbwTargetX10"):
        err = [(s == 2 and a is not None and b is not None
                and abs(a - b) > 5.0) for s, a, b in zip(st, tg, ac)]
        for s, e in spans(err, t, 0.2):
            add("dbw_tracking", s, "throttle off target by > 5 %% for %.2f s "
                "(closed loop)" % (t[e] - t[s]), target=tg[s], actual=ac[s],
                duty=du[s])
        sat = [(d is not None and abs(d) >= 95.0) for d in du]
        for s, e in spans(sat, t, 0.3):
            add("dbw_saturated", s, "throttle motor at >= 95 %% duty for "
                "%.2f s - no authority left" % (t[e] - t[s]), duty=du[s])
        prev = 0
        for i, v in enumerate(log.col("dbwFaults")):
            v = int(v or 0)
            if v and v != prev:
                add("dbw_fault", i, "DBW fault: " + bits_text(v, DBW_FAULT_BITS),
                    bits=v)
            prev = v
        for i, v in enumerate(log.col("dbwPendFaults")):
            if v and (i == 0 or not log.col("dbwPendFaults")[i - 1]):
                add("dbw_pending", i, "sensor fault pending (output held): "
                    + bits_text(v, DBW_FAULT_BITS), bits=int(v))

    # ---- fuel
    duty = log.col("injDutyX10")
    for i, d in enumerate(duty):
        if d is not None and d > 95.0:
            add("inj_duty_critical", i, "injector duty %.0f %% > 95 %%" % d)
        elif d is not None and d > 85.0:
            add("inj_duty_high", i, "injector duty %.0f %% > 85 %%" % d)
    want, corr = log.col("transWantUs"), log.col("transCorrUs")
    for i, (w, c) in enumerate(zip(want, corr)):
        # only fuel ADDED by the film model: a large NEGATIVE share is the
        # film giving fuel back on a pedal release, which is correct
        if w and c is not None and c > 0.6 * w and running[i]:
            add("transient_large", i, "wall-film share %.0f us is > 60 %% of "
                "the want (%.0f us) - check X / tau" % (c, w))

    # ---- lambda: validity per bank, and WHY (V97 lamWhy), faults, link
    lam = log.col("lambda1X1000")
    lst = log.col("lambdaStatus")
    tps = log.col("tpsX10")
    why = log.col("lamWhy")
    for b in (0, 1):
        def bw(i, b=b):
            return None if why[i] is None else (int(why[i]) >> (8 * b)) & 255
        if log.has("lamWhy"):
            # a bank whose source is not on-board says OFF (1): not judged.
            # 2026-10-10: HELD (16) is reported on its own below - a last
            # value carried through a CJ120 gap is neither live nor a dropout
            inval = [running[i] and bw(i) not in (None, 0, 1, 16)
                     for i in range(len(R))]
            held = [running[i] and bw(i) == 16 for i in range(len(R))]
            hs = spans(held, t, 0.0)
            if hs:
                add("lambda_held", hs[0][0], "bank %d lambda HELD (last value "
                    "through a CJ120 acquisition gap) %d time(s), %.1f s in "
                    "all - NOT a live reading; the closed loop and VE/WUE "
                    "Analyze ignored it" % (b + 1, len(hs),
                                            sum(t[e] - t[s] for s, e in hs)),
                    bank=b + 1, count=len(hs))
        elif b == 0:
            inval = [running[i] and not (int(lst[i] or 0) & 1)
                     for i in range(len(R))]
        else:
            continue
        for s, e in spans(inval, t, 2.0):
            rs = [bw(i) for i in range(s, e + 1) if bw(i) is not None]
            top = max(set(rs), key=rs.count) if rs else None
            add("lambda_invalid", s, "bank %d lambda not valid for %.1f s "
                "while running%s" % (b + 1, t[e] - t[s],
                                     "" if top is None else " - mostly %s"
                                     % LAM_WHY.get(top, str(top))),
                bank=b + 1, why=top)
    prev = [0, 0]
    for i, v in enumerate(log.col("lamFault")):
        v = int(v or 0)
        for b in (0, 1):
            f = (v >> (8 * b)) & 255
            if f and f != prev[b]:
                add("lambda_fault", i, "bank %d wideband fault %d: %s "
                    "(latched to key-off)" % (b + 1, f,
                                              LAM_FAULT.get(f, "?")),
                    bank=b + 1, fault=f)
            prev[b] = f
    for i in rising(log.col("cjTmo")):
        add("cj120_ssc_timeout", i, "a CJ120 SSC exchange never completed "
            "(cjTmo 0x%04X) - the SSC itself, not a sensor" % int(R[i]["cjTmo"]))
    # an OPEN pump line reads lambda ~1.00 with DIAG clean (not detectable
    # on the board): valid, flat to 0.005 for 20 s while the throttle moved
    val = [(lam[i] is not None and lam[i] > 0 and running[i])
           for i in range(len(R))]
    for s, e in spans(val, t, 20.0):
        ls = [lam[i] for i in range(s, e + 1)]
        ts = [tps[i] for i in range(s, e + 1) if tps[i] is not None]
        if ts and max(ls) - min(ls) <= 0.005 and max(ts) - min(ts) >= 10.0:
            add("lambda_flat", s, "bank 1 lambda %.3f flat for %.0f s while "
                "the throttle moved %.0f %% - an open pump line (IP) reads "
                "exactly this" % (ls[0], t[e] - t[s], max(ts) - min(ts)))
    for i in range(1, len(R)):
        if tps[i] is None or tps[i - 1] is None or t[i] <= t[i - 1]:
            continue
        rate = (tps[i] - tps[i - 1]) / (t[i] - t[i - 1])
        if rate > 50.0 and running[i]:
            win = [(lam[j], j) for j in range(i, len(R))
                   if t[j] - t[i] <= 0.6 and lam[j]]
            if win:
                hi, j = max(win)
                lo, k = min(win)
                if hi > 1.10:
                    add("tipin_lean", i, "tip-in %.0f %%/s: lambda %.2f within "
                        "%.2f s - lean spike" % (rate, hi, t[j] - t[i]),
                        tps_rate=round(rate), lam=hi)
                if lo < 0.85:
                    add("tipin_rich", i, "tip-in %.0f %%/s: lambda %.2f - rich"
                        % (rate, lo), tps_rate=round(rate), lam=lo)

    # ---- knock (V97): per-cylinder detections, retard, sensor faults, why
    #      windows were not taken, and each cylinder's level for tuning
    kstate = log.col("knockState")
    if log.has("knockState"):
        mode = [None if v is None else int(v) & 255 for v in kstate]
        why = [None if v is None else (int(v) >> 8) & 255 for v in kstate]
        for c in range(8):
            for i in rising(log.col("knockCnt%d" % (c + 1))):
                add("knock", i, "cylinder %d knocked (level %.2f x reference, "
                    "rpm %s, retard now %.2f deg)"
                    % (c + 1, num(R[i].get("knockLevel%d" % (c + 1))) or 0,
                       R[i].get("rpm"), num(R[i].get("knockRet%d" % (c + 1))) or 0),
                    cyl=c + 1, rpm=rpm[i])
        kret = log.col("knockRetardX10")
        for s, e in spans([(v or 0) > 0 for v in kret], t, 0.5):
            add("knock_retard", s, "knock retard on the spark for %.1f s (max "
                "%.1f deg)" % (t[e] - t[s], max(kret[s:e + 1])))
        prev = 0
        for i, v in enumerate(log.col("knockSelFault")):
            f = (int(v or 0) >> 8) & 15
            if f and f != prev:
                add("knock_sensor_fault", i, "knock sensor fault latched: "
                    "sensors %s (P0325/P0330)"
                    % [b + 1 for b in range(4) if f >> b & 1], bits=f)
            prev = f
        idle_w = [running[i] and mode[i] and why[i] not in (None, 0)
                  for i in range(len(R))]
        for s, e in spans(idle_w, t, 2.0):
            ws = [why[i] for i in range(s, e + 1) if why[i]]
            top = max(set(ws), key=ws.count) if ws else None
            add("knock_not_measuring", s, "knock on but no window for %.1f s "
                "- mostly %s" % (t[e] - t[s], KNOCK_WHY.get(top, str(top))),
                why=top)
        cyl = []
        for c in range(8):
            lv = [v for v in log.col("knockLevel%d" % (c + 1)) if v]
            rf = [v for v in log.col("knockRef%d" % (c + 1)) if v]
            if lv:
                cyl.append({"cyl": c + 1, "level_mean": round(sum(lv) / len(lv), 3),
                            "level_max": round(max(lv), 3),
                            "ref_mean": round(sum(rf) / len(rf), 1) if rf else None,
                            "rows": len(lv)})
        if cyl:
            F["_knock_cyl"] = cyl

    # ---- VVT (V97): faults and tracking
    for b in (1, 2):
        st = log.col("vvt%dState" % b)
        if not log.has("vvt%dState" % b):
            continue
        prev = 0
        for i, v in enumerate(st):
            f = (int(v or 0) >> 8) & 127
            if f and f != prev:
                add("vvt_fault", i, "cam %d VVT fault %d: %s (P00%d1)"
                    % (b, f, VVT_FAULT.get(f, "?"), b), cam=b, fault=f)
            prev = f
        err = log.col("vvt%dErr" % b)
        off = [((int(st[i] or 0) & 16) != 0) and err[i] is not None
               and abs(err[i]) > 5.0 for i in range(len(R))]
        for s, e in spans(off, t, 1.0):
            add("vvt_tracking", s, "cam %d off target by > 5 deg for %.1f s "
                "(closed loop)" % (b, t[e] - t[s]), cam=b)

    # ---- ignition and scheduler
    for i, a in enumerate(log.col("advX10")):
        if a is not None and running[i] and (a < -10.0 or a > 45.0):
            add("spark_advance", i, "advance %.1f deg outside -10..45" % a)
    for i in rising(log.col("schedOverdwell")):
        add("overdwell", i, "a coil was released by the max-dwell watch "
            "(a spark nobody scheduled)")
    for name in ("schedulerLate", "schedulerMissed"):
        idx = rising(log.col(name))
        if idx:
            add("scheduler_" + name[9:].lower(), idx[0], "%s rose %d time(s) "
                "during the log" % (name, len(idx)))
    ml = [v for v in log.col("schedulerMaxLatency") if v is not None]
    if ml and max(ml) > 1250:
        add("scheduler_latency", 0, "max event latency %.1f ms > 1 ms"
            % (max(ml) / 1250.0))

    # ---- cuts, protection, faults
    prev = 0
    for i, v in enumerate(log.col("fuelCut")):
        v = int(v or 0)
        if v != prev and v:
            add("fuel_cut", i, "fuel cut: " + bits_text(v, CUT_BITS), bits=v)
        prev = v
    for i in rising(log.col("dtcMil")):
        add("mil", i, "MIL requested (a MIL-class trouble code is active)")
    # celState (V97): bits 0..7 mode, bit 8 the lamp command, bit 9 the MIL
    # request, bit 10 the stage enabled and routed. The key-on test (modes
    # 2/3) is not a fault; a lamp command outside it without a request is.
    cel = log.col("celState")
    prev = 0
    for i, v in enumerate(cel):
        v = int(v or 0)
        lamp, req, mode = (v >> 8) & 1, (v >> 9) & 1, v & 255
        if req and not (prev >> 9) & 1 and not (v >> 10) & 1:
            add("cel_not_driven", i, "MIL requested but the lamp stage is "
                "not enabled/routed (celEnable 0 or pinMil unset)")
        if lamp and not req and mode not in (2, 3):
            add("cel_mismatch", i, "lamp commanded ON with no MIL request "
                "outside the key-on test (celState 0x%04X)" % v, bits=v)
        prev = v
    prev = 0
    for i, v in enumerate(log.col("sensorErr")):
        v = int(v or 0)
        if v != prev:
            add("sensor_error", i, "sensor error bits 0x%04X" % v, bits=v)
        prev = v
    for i in range(1, len(R)):
        a, b = rpm[i - 1], rpm[i]
        if a and b and max(a, b) > 500 and abs(a - b) > 1500:
            add("rpm_jump", i, "rpm %.0f -> %.0f between two rows" % (a, b))

    # ---- VE evidence: measured / target lambda in STEADY cells ----------
    # A cell = 500 rpm x 10 % load (engLoad: TPS % on alpha-N, rl % on
    # speed density). A row counts only when lambda is valid, the engine is
    # running, no cut is active and rpm (+/-100) and load (+/-2 %) have been
    # steady for the last STEADY_S (the sensor and the film settle). The
    # ratio is WHAT THE ENGINE GOT / WHAT IT WAS ASKED FOR: 1.05 = 5 % lean
    # = that cell's VE reads 5 % low. Evidence only - never applied.
    STEADY_S = 1.0
    load = log.col("engLoad")
    tgt = log.col("lambdaTarget")
    # logs written through a pre-V98 .ini carry lambdaTarget x1000 (it was
    # declared scale 1 - bug B1): a target above 5 is that, not a lambda
    tgt = [None if v is None else (v / 1000.0 if v > 5 else v) for v in tgt]
    cut = log.col("fuelCut")
    # V98: with closed loop on, the measured lambda already carries the trim
    # - what the VE table alone would have given is measured x (1 + trim)
    trim = log.col("stftBank1") if log.has("stftBank1") else [0.0] * len(R)
    cells = {}
    anchor = 0
    for i in range(len(R)):
        ok = (running[i] and lam[i] and tgt[i] and load[i] is not None
              and (int(lst[i] or 0) & 1) and not int(cut[i] or 0))
        if not ok:
            anchor = i + 1
            continue
        while anchor < i and (abs((rpm[anchor] or 0) - (rpm[i] or 0)) > 100
                              or abs((load[anchor] or 0) - load[i]) > 2.0):
            anchor += 1
        if t[i] - t[anchor] < STEADY_S:
            continue
        key = (int((rpm[i] or 0) // 500) * 500, int(load[i] // 10) * 10)
        c = cells.setdefault(key, [0, 0.0])
        c[0] += 1
        c[1] += lam[i] / tgt[i] * (1.0 + (trim[i] or 0.0) / 100.0)
    # measured/target > 1 = lean = more air than the model says = the VE
    # there is LOW by that ratio; ve_evidence_pct is that difference.
    ve = [{"rpm_from": k[0], "load_from": k[1], "rows": n,
           "measured_over_target": round(s / n, 3),
           "ve_evidence_pct": round((s / n - 1.0) * 100.0, 1)}
          for k, (n, s) in sorted(cells.items()) if n >= 5]
    F["_ve_cells"] = ve
    ve = [c for c in ve if abs(c["ve_evidence_pct"]) >= 3.0]
    if ve:
        F["ve_evidence"] = [
            {"t": 0.0, "text": "rpm %d.. load %d..: lambda measured/target "
             "%.3f over %d steady rows - the VE there reads %.1f %% %s"
             % (c["rpm_from"], c["load_from"], c["measured_over_target"],
                c["rows"], abs(c["ve_evidence_pct"]),
                "LOW (lean)" if c["ve_evidence_pct"] > 0 else "HIGH (rich)"),
             **c} for c in ve]

    # ---- V98 closed loop: a trim parked at its limit is a VE cell that is
    # wrong by more than the loop may correct
    if log.has("stftBank1"):
        st = log.col("stftState")
        trims = log.col("stftBank1")
        at_lim = [running[i] and v is not None and abs(v) >= 9.5
                  and st[i] is not None and (int(st[i]) & 255) == 8
                  for i, v in enumerate(trims)]
        for s, e in spans(at_lim, t, 1.0):
            add("stft_at_limit", s, "closed-loop trim %+.1f %% held for %.1f s "
                "- correct the VE (or the injector data) there"
                % (trims[s], t[e] - t[s]), rpm=rpm[s])

    for k, v in F.items():
        if any(n in log.aux for n in ("lambda1X1000", "lambdaStatus")) \
                and k.startswith(("lambda", "tipin")):
            for e in v:
                e["aux"] = True
    return F


def tune_check(page: bytes, ini_text: str) -> list:
    """V98r2: what TunerStudio's VE Table Generator got wrong on the car page
    (2026-10-02) - checked on the page the car ran with. The VE load axis is
    in the load source's units: THROTTLE % under the two alpha-N strategies
    (0..100 %; a row past 100 % is never reached, a first row of 10 % or more
    clamps idle into a part-load row), kPa under speed density (past the
    pressure sensor's full scale is never reached). Saturated cells sit at
    the field's limit. Findings only - nothing is changed."""
    pass  # (bootstrap above)
    import me711_migrate_calibration as M
    c = M.parse_ini(ini_text)
    if "veTable" not in c or "fuelLoadAx" not in c or "loadSource" not in c:
        return []

    def raw(name, i=0):
        k = c[name]
        return M._get(page, k.off + i * k.width, k.width, M.TYPES[k.typ][1])
    ls = c["loadSource"]
    lo, hi = ls.bits
    src = (raw("loadSource") >> lo) & ((1 << (hi - lo + 1)) - 1)
    ax = [raw("fuelLoadAx", i) * c["fuelLoadAx"].scale for i in range(16)]
    ve = c["veTable"]
    cells = [raw("veTable", i) for i in range(ve.count)]
    out = []
    if src in (1, 2):                    # throttle %
        dead = [round(a, 1) for a in ax if a > 100.0]
        if dead:
            out.append("VE load axis is THROTTLE %% (%s) but %d row(s) sit "
                       "above 100 %%: %s - never reached"
                       % (ls.labels[src], len(dead), dead))
        if ax[0] >= 10.0:
            out.append("VE load axis starts at %.1f %% throttle: idle "
                       "(2..5 %%) reads that row" % ax[0])
    elif src == 0 and "mapSensOff" in c and "mapSensGrd" in c:
        full = (raw("mapSensOff") + raw("mapSensGrd") * 1023 / 1000.0) * 0.1
        dead = [round(a, 1) for a in ax if a > full + 1.0]
        if dead:
            out.append("VE load axis (kPa) passes the pressure sensor's full "
                       "scale %.0f kPa: %s never reached" % (full, dead))
    top = int(ve.hi / ve.scale) if ve.hi else None
    sat = sum(1 for v in cells if top is not None and v >= top)
    if sat:
        out.append("%d VE cell(s) at the field limit %.1f %% (saturated)"
                   % (sat, ve.hi))
    return out


# ===================================================== V99: sessions ===
def is_session(folder: Path) -> bool:
    m = folder / "metadata.json"
    if not m.exists():
        return False
    try:
        return json.loads(m.read_text()).get("tool") == "me711_vehicle_test"
    except Exception:
        return False


def _analog_names(row):
    # V100 recorded AN2 under a false supply-reference name. Preserve the
    # historical file; give its physical channel the V101 name on reading.
    if "adc02_IPV" not in row and "adc02_TPSREF" in row:
        row["adc02_IPV"] = row["adc02_TPSREF"]
    return row


def _csv(path: Path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [_analog_names(r) for r in csv.DictReader(f)]


class SessionLog(Log):
    """fast.csv rows (t) with the MEDIUM and SLOW channels carried forward,
    under the names the capture checks use (rpm, syncState ...).

    V100: medium.csv joined the pair. The slower a channel's group, the
    staler its value on a given row - `self.group` says which group each
    channel came from so a finding can state it (`stale_group`)."""

    ALIAS = {"rpm": "RPMValue"}
    SLOWER = ("medium", "slow")

    def __init__(self, folder: Path):
        self.dir = folder
        self.meta = json.loads((folder / "metadata.json").read_text())
        fast = _csv(folder / "fast.csv")
        self.group = {}
        for k in (fast[0] if fast else {}):
            self.group[k] = "fast"
        slower = []           # (t, row, group), oldest first
        for g in self.SLOWER:
            for r in _csv(folder / (g + ".csv")):
                slower.append((num(r.get("t")) or 0.0, r, g))
                for k in r:
                    self.group.setdefault(k, g)
        slower.sort(key=lambda x: x[0])
        self.rows = []
        j, cur = 0, {}
        for r in fast:
            t = num(r.get("t")) or 0.0
            while j < len(slower) and slower[j][0] <= t:
                cur = dict(cur)
                cur.update({k: v for k, v in slower[j][1].items()
                            if v not in (None, "") and k != "t"})
                j += 1
            row = dict(cur)
            row.update({k: v for k, v in r.items() if v not in (None, "")})
            for a, b in self.ALIAS.items():
                if b in row:
                    row[a] = row[b]
            row["t_mono"] = r.get("t")
            self.rows.append(row)
        if not fast:
            # a session with no fast rows (--kline / --autocal only) still has
            # a slow stream worth checking
            for t, r, g in slower:
                row = dict(r)
                for a, b in self.ALIAS.items():
                    if b in row:
                        row[a] = row[b]
                row["t_mono"] = r.get("t")
                self.rows.append(row)
        self.t = [num(r["t_mono"]) or 0.0 for r in self.rows]
        self.aux = set()

    # ---- the session's own configuration, as metadata records it ----------
    def cfg(self, name, default=None):
        return (self.meta.get("engine_config") or {}).get(name, default)

    def cfg_text(self, name):
        return str(self.cfg(name) or "")

    def profile(self):
        rt = (self.meta.get("phases") or {}).get("runtime") or {}
        return rt.get("profile") or self.meta.get("logging_profile") or "?"

    def span(self, name):
        """(first, last, max, rise) of a monotonic counter, resets summed."""
        vals = [v for v in self.col(name) if v is not None]
        if not vals:
            return None
        rise = 0.0
        for a, b in zip(vals, vals[1:]):
            if b >= a:
                rise += b - a
        return {"first": vals[0], "last": vals[-1], "max": max(vals),
                "rise": rise, "rows": len(vals)}


def firing_order(meta) -> list:
    fo = str((meta.get("engine_config") or {}).get("firingOrder", ""))
    digits = [int(x) for x in fo.split(" ")[0].split("-") if x.isdigit()]
    return digits


def analyse_session(folder: Path, log: Log) -> dict:
    F = {}

    def add(key, t, text, **vals):
        F.setdefault(key, []).append(dict(t=t if t is not None else -1.0,
                                          text=text, **vals))

    ev = _csv(folder / "events.csv")
    last_dbw_fault = None
    # V100: STALE RING RECORDS ARE NOT THIS SESSION'S EVENTS.
    #
    # The ECU event ring is battery-backed and is NOT cleared between
    # sessions, so a session's events.csv begins with whatever the previous
    # run left behind. Those records have no host timestamp (the reader
    # writes t_host empty, which prints as t=-1.00) and an ecu_ms from the
    # PREVIOUS power-on. V99 reported them as current-session findings: the
    # 01:28:15 session's analysis lists an ETB fault and a
    # "PROTECTION: THROTTLE FAULT rev limit @ 2301 rpm" that in fact happened
    # in the 01:13:56 session, while fuelCut was 0 in all 696 of its own rows
    #.
    #
    # The discriminator is the ring SEQUENCE NUMBER, not ecu_ms: ecu_ms
    # restarts at every power-on, and a previous session that ran LONGER
    # leaves records whose ecu_ms is larger than this session's first (the
    # 01:28:15 session's stale records are seq 137..226 at ecu_ms 42163,
    # while its own first timestamped record is seq 227 at ecu_ms 10293 -
    # an ecu_ms test gets that exactly backwards). seq is monotonic across
    # power cycles, so a record with NO host timestamp and a seq below the
    # first seq the reader timestamped was already sitting in the ring when
    # the reader attached.
    _seqs = [num(e.get("seq")) for e in ev if num(e.get("t_host")) is not None]
    _first_seq = min([s for s in _seqs if s is not None], default=None)
    stale_n = 0
    for e in ev:
        typ, text = e.get("type"), e.get("text", "")
        t = num(e.get("t_host"))
        v2 = int(num(e.get("v2")) or 0)
        if t is None and _first_seq is not None:
            s = num(e.get("seq"))
            if s is not None and s < _first_seq:
                stale_n += 1
                F.setdefault("_stale_ring_event", []).append(
                    dict(t=0.0, text="PREVIOUS SESSION (ring seq %d < this "
                         "session's first %d): %s" % (s, _first_seq, text)))
                continue
        if typ == "SYNC_LOSS" or (typ == "SYNC" and "LOST" in text):
            add("sync_lost", t, text)
        elif typ == "CYCLE" and e.get("arg") == "0":
            add("phase_lost", t, text)
        elif typ == "DBW" and v2:
            last_dbw_fault = (t, text)
            add("etb_fault", t, text)
        elif typ == "LIMP" and v2:
            why = ""
            if v2 & 2 and last_dbw_fault:
                why = (" <- caused by the ETB fault at t=%s (%s): a latched "
                       "throttle fault cuts the fuel above etbLimpRpm (0 = "
                       "1500 rpm) until the next key-on" % last_dbw_fault)
            add("protection_fuel_cut", t, text + why)
        elif typ == "FUELCUT" and v2 & 0x0E:
            add("fuel_cut", t, text)
        elif typ == "FLAGS" and v2 & (8192 | 1024 | 2048 | 4096):
            add("spark_or_limiter", t, text)
        elif typ == "SPARK_SKIP":
            add("spark_cut", t, text)
        elif typ == "OVERDWELL":
            add("overdwell", t, text)
        elif typ == "SCHED_MISSED":
            add("scheduler_missed", t, text)
        elif typ == "LAMDYN" and ("STUCK" in text or "NOT proven" in text):
            add("lambda_dynamics", t, text)
        elif typ == "KLINE":
            # V100: RECONCILE AGAINST THE AUTHORITATIVE COUNTER, do not just
            # repeat the ring text. V99's analysis of the 00:28:13 session
            # listed 54 "ECU framing counter = 284 ... 356" findings while
            # that session's own rxFrameErr channel never exceeded 2 over
            # 41 063 requests - a reported fault that the log's own
            # authoritative counters contradict
            #. The slow block carries the real
            # values; a ring record that disagrees with them is a reporting
            # defect and is labelled as one rather than asserted as a count.
            _auth = {0: "rxResync", 1: "rxHwOvr", 2: "rxFrameErr",
                     3: "rxOvf", 4: "rxEchoLost"}.get(
                         int(num(e.get("arg")) or -1))
            _top = None
            if _auth:
                _vals = [v for v in log.col(_auth) if v is not None]
                _top = max(_vals) if _vals else None
            if _top is not None and v2 > _top:
                add("ecu_link_errors", t, "%s  <- UNRECONCILED: the ring says "
                    "%d but this session's %s channel never exceeded %d, so "
                    "the ring value is not a count of this session's errors"
                    % (text, v2, _auth, int(_top)))
            else:
                add("ecu_link_errors", t, text)
        elif typ == "BOOT":
            add("ecu_boot", t, text)

    # sequential ON then a stall within 5 s: the inverted-phase signature
    seq_on = [num(e.get("t_host")) for e in ev
              if e.get("type") == "SEQ" and e.get("arg") not in ("0", None)]
    stops = [num(e.get("t_host")) for e in ev
             if e.get("type") == "ENGINE" and e.get("arg") == "0"]
    for ts in seq_on:
        if ts is None:
            continue
        for tp in stops:
            if tp is not None and 0 <= tp - ts <= 5.0:
                add("sequential_stall", ts, "the engine stopped %.1f s after "
                    "sequential operation began - the signature of an INVERTED "
                    "cam phase assignment (sparks at overlap TDC): verify "
                    "camPhaseLevel (docs/firmware/design/ME711_CAM_QUALIFICATION.md step 5)"
                    % (tp - ts))

    # ETB procedures
    for r in _csv(folder / "etb_events.csv"):
        if r.get("event", "").startswith("RESULT") and "FAIL" in r["event"]:
            add("etb_procedure_failed", num(r.get("t")),
                "%s: %s (push moved %s counts, limit %s, distance from rest "
                "%s)" % (r.get("test"), r["event"][7:], r.get("moved"),
                         r.get("limit"), r.get("disp")))

    # lambda vs fuel command, independently of the firmware's check
    R, t = log.rows, log.t
    lam, pw = log.col("lambdaValue"), log.col("injectorPulseWidth")
    fl = [int(v or 0) for v in log.col("engineFlags")]
    i0 = 0
    for i in range(len(R)):
        while i0 < i and t[i] - t[i0] > 3.0:
            i0 += 1
        if t[i] - t[i0] < 2.5 or i % 10:
            continue
        seg = range(i0, i + 1)
        ls = [lam[k] for k in seg if lam[k] and lam[k] > 0 and fl[k] & 1
              and not fl[k] & (32 | 512)]
        ps = [pw[k] for k in seg if pw[k] and fl[k] & 1
              and not fl[k] & (32 | 512)]
        if len(ls) < 10 or len(ps) < 10 or min(ps) <= 0:
            continue
        if max(ps) / min(ps) >= 1.25 and max(ls) - min(ls) < 0.02:
            prev = F.get("lambda_static", [])
            if prev and t[i] - prev[-1]["t"] < 3.0:
                continue
            add("lambda_static", round(t[i], 2),
                "fuel pulse %.2f..%.2f ms (x%.2f) in 3 s while lambda stayed "
                "%.3f..%.3f - advisory response suspicion, not a validity "
                "decision; fuel demand and exhaust transport may differ. Check "
                "lamDyn / lamWhy, the UA channel (adc04 vs adc06) and the "
                "sensor" % (min(ps), max(ps), max(ps) / min(ps), min(ls),
                            max(ls)))

    # sequential ignition order (the last spark's slot, sampled)
    #
    # V100: ONLY WHERE THE FIRING ORDER MEANS ANYTHING. Under wasted COP each
    # coil fires twice per cycle and the companion pair (1+4, 2+3 on a
    # 1-3-4-2) fires TOGETHER, 360 deg apart, so consecutive sampled sparks
    # are not expected to walk the firing order at all. V99 ran this test on
    # the AWT's wasted-COP sessions anyway and reported "766 sequential
    # sparks sampled, 41 out of order" plus five "not the firing order"
    # findings - none of which were evidence of anything
    #. An analysis that is not valid for the
    # session's configuration must not run.
    fo = firing_order(log.meta)
    ign = str((log.meta.get("engine_config") or {}).get("ignStrategy") or "")
    # Suppress only what the configuration RULES OUT. A session that declares
    # wasted COP cannot walk a firing order; a session that declares nothing
    # is still checked, because an analysis is not made invalid by missing
    # metadata - it is only made invalid by metadata that contradicts it.
    ruled_out = "wasted" in ign.lower()
    if fo and ruled_out:
        F.setdefault("_seq_order_skipped", []).append(
            dict(t=0.0, text="firing-order check SKIPPED: ignition strategy "
                 "is %r, where companion cylinders fire together 360 deg "
                 "apart and consecutive sparks do not follow the firing "
                 "order" % ign))
    if fo and not ruled_out:
        slot, sang, seq = (log.col("nextIgnSlot"), log.col("scheduledSpark"),
                           log.col("syncSeq"))
        rpmc = log.col("rpm")
        order = []
        last = None
        for k in range(len(R)):
            if seq[k] is None or int(seq[k]) >> 8 != 1:
                continue
            if slot[k] is None or sang[k] is None:
                continue
            key = (int(slot[k]) & 0x0F, sang[k])
            if key != last and 1 <= key[0] <= len(fo):
                order.append((t[k], key[0], rpmc[k] or 0))
                last = key
        pos = {c: i for i, c in enumerate(fo)}
        bad = judged = 0
        for (ta, a, _ra), (tb, b, rb) in zip(order, order[1:]):
            if a not in pos or b not in pos:
                continue
            # judged only where at most ONE spark can lie between the two
            # samples (sparks/s = cylinders x rpm / 120): a slower sample
            # pair may legitimately skip cylinders
            if (tb - ta) * len(fo) * rb / 120.0 > 1.2:
                continue
            judged += 1
            step = (pos[b] - pos[a]) % len(fo)
            if step != 1:
                bad += 1
                if bad <= 5:
                    add("sequential_order", tb, "spark on cylinder %d followed "
                        "cylinder %d - not the firing order %s" % (
                            b, a, "-".join(map(str, fo))))
        if order:
            F.setdefault("_seq_order_checked", []).append(
                dict(t=order[0][0], text="%d sequential sparks sampled, %d "
                     "pairs judged (<= 1 spark apart), %d out of order"
                     % (len(order), judged, bad)))

    if stale_n:
        F.setdefault("_stale_ring_summary", []).append(
            dict(t=0.0, text="%d ring record(s) predate this session and were "
                 "NOT counted as current events (the ECU ring is not cleared "
                 "between sessions)" % stale_n))

    # K-line
    kl = _csv(folder / "kline.csv")
    drops = [r for r in kl if r.get("stage") == "runtime dropout"]
    for r in drops:
        add("kline_dropout", num(r.get("t")), "link down %s" % r.get("error"))
    errs = [r for r in kl if r.get("ok") == "0"
            and r.get("stage") in ("runtime", "read soak")]
    if errs:
        kinds = {}
        for r in errs:
            k = (r.get("error") or "?").split(":")[0]
            kinds[k] = kinds.get(k, 0) + 1
        add("kline_errors", num(errs[0].get("t")), "%d failed exchanges while "
            "recording: %s" % (len(errs), kinds))
    return F


# ============================================= V100: by subject, by config ==
TICKS_PER_MS = 1250.0      # TGT_TICKS_PER_MS_X10 12500 -> 0.8 us a tick
LAT_BOUND_MS = 1.0         # the project rules: the documented polled bound
LAT_V99_MS = 2.11          # the worst the V99 car sessions measured (B2)
IDLE_PW_NORM_MS = 3.5      # CARTEST_ANALYSIS B6: a 1.8T idle norm 2.5..3.5
# hcsched_dry.c hc_plan_out(): HC_PLAN_SLOT_ALL becomes ONE call,
# hc_hal_out_group(base, 0x00FF) - every slot of the class at once. So
# 0xff is a legitimate mask for a strategy that fires the class as one
# group (batch injection, and the key-on priming pulse), and it is NOT a
# per-cylinder mask. An unrouted slot in it drives nothing.
ALL_SLOTS = 0xFF


def _delta(sp):
    return None if not sp else sp["rise"]


def analyse_v100(folder: Path, log) -> tuple:
    """The per-subject checks, each one valid only where the session's own
    configuration says it is. Returns (findings, summary)."""
    F, S = {}, {}
    t, R = log.t, log.rows
    rpm = log.col("rpm")
    running = [(v or 0) >= 400 for v in rpm]
    run_rows = [i for i in range(len(R)) if running[i]]

    def add(key, i, text, **vals):
        ti = round(t[i], 3) if 0 <= i < len(t) else 0.0
        F.setdefault(key, []).append(dict(t=ti, text=text, **vals))

    def note(key, text, **vals):
        F.setdefault(key, []).append(dict(t=0.0, text=text, **vals))

    # ------------------------------------------------------------ TRIGGER --
    trig = {n: log.span(n) for n in (
        "syncLossCount", "toothCorrections", "camError", "camPhaseCorrections",
        "cycleSyncAcquired", "cycleSyncLost", "camPhaseNoAlt",
        "crankNoiseEdges", "crankGaps", "crankRevolutions")}
    S["trigger"] = {k: (v and {"max": v["max"], "rise": v["rise"]})
                    for k, v in trig.items()}
    for name, key, what in (
            ("syncLossCount", "trigger_sync_loss", "crank sync was lost"),
            ("toothCorrections", "trigger_tooth_correction",
             "a +/-1-tooth disagreement was corrected at a confirmed gap "
             "(Bosch B_fbm; two in consecutive revolutions is a loss)"),
            ("camError", "trigger_cam_error", "the cam decoder rejected an "
             "edge"),
            ("camPhaseCorrections", "trigger_phase_correction",
             "the cam moved the engine half by 360 deg"),
            ("cycleSyncLost", "trigger_phase_loss", "720 deg cycle sync was "
             "withdrawn - sequential cylinders fall back"),
            ("camPhaseNoAlt", "trigger_cam_no_alternate",
             "the cam level did not alternate between halves")):
        d = _delta(trig[name])
        if d:
            note(key, "%s %d time(s) during the session (%s)"
                 % (what, int(d), name), count=int(d))
    # a state that fell without the ring saying why
    # Only while the engine is TURNING on both sides of the step: losing
    # sync at rpm 0 is the engine stopping, which is not a trigger defect
    # (every V99 key-off produced one of these).
    sy = log.col("syncState")
    for i in range(1, len(R)):
        a, b = sy[i - 1], sy[i]
        if a is None or b is None or b >= a or a < 3:
            continue
        if not (running[i] and running[i - 1]):
            continue
        add("trigger_state_drop", i, "syncState %s -> %s with the engine at "
            "%s rpm - check trigger_events.csv for the reason at this time"
            % (int(a), int(b), rpm[i]), rpm=rpm[i])

    # ---------------------------------------------------------- SCHEDULER --
    ex, late = log.span("schedulerExecuted"), log.span("schedulerLate")
    miss, canc = log.span("schedulerMissed"), log.span("schedulerCancelled")
    lat = [v for v in log.col("schedulerMaxLatency") if v is not None]
    sch = {"executed": _delta(ex), "late": _delta(late),
           "missed": _delta(miss), "cancelled": _delta(canc),
           "max_latency_ticks": max(lat) if lat else None,
           "max_latency_ms": round(max(lat) / TICKS_PER_MS, 3) if lat else None,
           "overdwell": _delta(log.span("schedOverdwell")),
           "spark_skips": _delta(log.span("sparkSkips")),
           "capture_overflow": _delta(log.span("schedulerCaptureOverflow")),
           "profile": log.profile() if hasattr(log, "profile") else None}
    if sch["executed"]:
        sch["late_per_executed"] = round(sch["late"] / sch["executed"], 5) \
            if sch["late"] is not None else None
        sch["missed_per_executed"] = round(sch["missed"] / sch["executed"], 5) \
            if sch["missed"] is not None else None
    # per rpm band, so lateness can be read against engine speed
    bands = {}
    prev = {}
    for i in run_rows:
        b = int((rpm[i] or 0) // 500) * 500
        d = bands.setdefault(b, {"rows": 0, "executed": 0.0, "late": 0.0,
                                 "missed": 0.0, "max_latency_ticks": 0})
        d["rows"] += 1
        for k, ch in (("executed", "schedulerExecuted"),
                      ("late", "schedulerLate"), ("missed", "schedulerMissed")):
            v = num(R[i].get(ch))
            if v is not None:
                p = prev.get(ch)
                if p is not None and v >= p:
                    d[k] += v - p
                prev[ch] = v
        ml = num(R[i].get("schedulerMaxLatency"))
        if ml is not None:
            d["max_latency_ticks"] = max(d["max_latency_ticks"], ml)
    for b, d in bands.items():
        d["late_per_executed"] = (round(d["late"] / d["executed"], 5)
                                  if d["executed"] else None)
        d["max_latency_ms"] = round(d["max_latency_ticks"] / TICKS_PER_MS, 3)
    sch["by_rpm_band"] = {str(k): bands[k] for k in sorted(bands)}
    S["scheduler"] = sch
    if sch["max_latency_ms"]:
        ms = sch["max_latency_ms"]
        if ms > LAT_BOUND_MS:
            note("scheduler_latency", "max event latency %.2f ms is over the "
                 "documented polled bound of %.1f ms. The V99 "
                 "car sessions measured %.2f ms, so this run is %s"
                 % (ms, LAT_BOUND_MS, LAT_V99_MS,
                    "no better" if ms >= LAT_V99_MS * 0.95
                    else "better than V99 but still over the bound"),
                 ms=ms)
    if sch.get("late_per_executed"):
        note("scheduler_late_ratio", "%d of %d executed events were more than "
             "0.25 ms late (%.2f %%)" % (sch["late"], sch["executed"],
                                         100.0 * sch["late_per_executed"]),
             ratio=sch["late_per_executed"])
    if sch.get("missed_per_executed"):
        note("scheduler_missed_ratio", "%d of %d executed events were MISSED "
             "(%.2f %%)" % (sch["missed"], sch["executed"],
                            100.0 * sch["missed_per_executed"]),
             ratio=sch["missed_per_executed"])
    if sch["capture_overflow"]:
        note("scheduler_capture_overflow", "the trigger capture ring "
             "overflowed %d time(s) - teeth reached the planner in a burst"
             % int(sch["capture_overflow"]))

    # ----------------------------------------------------------- IGNITION --
    ign_s = log.cfg_text("ignStrategy") if hasattr(log, "cfg_text") else ""
    cyls = int(log.cfg("cylinders") or 0) if hasattr(log, "cfg") else 0
    adv = [v for i, v in enumerate(log.col("ignitionTiming") or [])
           if running[i] and v is not None]
    if not adv:
        adv = [v for i, v in enumerate(log.col("advX10")) if running[i]
               and v is not None]
    if adv:
        adv.sort()
        S["ignition"] = {"requested_deg": {
            "min": adv[0], "median": adv[len(adv) // 2], "max": adv[-1],
            "rows": len(adv)}, "strategy": ign_s}
    if sch["overdwell"]:
        note("ignition_overdwell", "the max-dwell watch released a coil %d "
             "time(s): a spark nobody scheduled (schedOverdwell). Three in a "
             "row without a normal spark latch that coil"
             % int(sch["overdwell"]))
    lch = [v for v in log.col("schedOverdwellLatch") if v]
    if lch:
        note("ignition_overdwell_latch", "a coil was LATCHED off by the "
             "overdwell watch (schedOverdwellLatch max %d) - it stays latched "
             "until a cancel" % int(max(lch)))
    if sch["spark_skips"]:
        note("ignition_spark_cut", "%d spark(s) were skipped (sparkSkips) - "
             "rev limiter pattern, launch/flat shift or a cut"
             % int(sch["spark_skips"]))
    # output masks against what the configuration can produce
    # THE MASK CHECKS ONLY APPLY WHILE THE ENGINE RUNS, and ALL_SLOTS is
    # never a per-cylinder mask. Both rules come from real V99 data: a first
    # version of this check reported the AWT's batch pulses (injOnMask 0xff,
    # which is what HC_PLAN_SLOT_ALL means) and its key-on priming samples as
    # "a bit above the configured 4 cylinders". Neither was a defect, and a
    # check that cannot tell them apart is worse than no check.
    if cyls and run_rows:
        full = (1 << cyls) - 1
        for ch, key, what in (("ignOnMask", "ignition_mask_outside_config",
                               "ignition"),
                              ("injOnMask", "injection_mask_outside_config",
                               "injection")):
            col = log.col(ch)
            bad = sorted({int(col[i]) for i in run_rows
                          if col[i] is not None and int(col[i]) & ~full
                          and int(col[i]) != ALL_SLOTS})
            if bad:
                note(key, "%s output mask(s) %s drive a bit above the "
                     "configured %d cylinders (mask %#x)"
                     % (what, [hex(v) for v in bad[:6]], cyls, full),
                     masks=[hex(v) for v in bad[:16]])
        igc = log.col("ignOnMask")
        masks = sorted({int(igc[i]) for i in run_rows if igc[i] is not None})
        S.setdefault("ignition", {})["ign_masks_seen"] = [hex(m) for m in
                                                          masks[:32]]
        inj_s = log.cfg_text("injStrategy")
        if inj_s.lower().startswith("batch"):
            # batch fires the class as ONE group, so the only masks it can
            # produce are 0 and ALL_SLOTS - not a per-cylinder mask
            ijc = log.col("injOnMask")
            odd = sorted({int(ijc[i]) for i in run_rows
                          if ijc[i] is not None
                          and int(ijc[i]) not in (0, ALL_SLOTS)})
            if odd:
                note("injection_batch_mask", "the strategy is %r, which fires "
                     "every injector as one group (HC_PLAN_SLOT_ALL -> mask "
                     "%#x), but injOnMask took the value(s) %s"
                     % (inj_s, ALL_SLOTS, [hex(v) for v in odd[:6]]))
        elif "wasted" in ign_s.lower() and "cop" not in ign_s.lower():
            # paired coils: a bit is only ever driven with its companion
            pairs = {i: (i + cyls // 2) % cyls for i in range(cyls)}
            lone = sorted({int(igc[i]) for i in run_rows
                           if igc[i] is not None and int(igc[i])
                           and any((int(igc[i]) >> b & 1)
                                   and not (int(igc[i]) >> pairs[b] & 1)
                                   for b in range(cyls))})
            if lone:
                note("ignition_pair_mask", "the strategy is %r (paired coils) "
                     "but mask(s) %s drive a coil without its companion"
                     % (ign_s, [hex(v) for v in lone[:6]]))

    # --------------------------------------------------------------- FUEL --
    ax = log.cfg("fuelLoadAx") if hasattr(log, "cfg") else None
    load = log.col("engLoad")
    pw = log.col("injectorPulseWidth")
    ve = log.col("veValue")
    fuel = {"load_axis": ax, "load_source": log.cfg_text("loadSource")}
    if ax and any(v is not None for v in load):
        lo, hi = min(ax), max(ax)
        vals = [v for i, v in enumerate(load) if running[i] and v is not None]
        if vals:
            below = sum(1 for v in vals if v <= lo)
            above = sum(1 for v in vals if v >= hi)
            fuel["load_rows"] = len(vals)
            fuel["clamped_low_pct"] = round(100.0 * below / len(vals), 1)
            fuel["clamped_high_pct"] = round(100.0 * above / len(vals), 1)
            fuel["load_min"] = min(vals)
            fuel["load_max"] = max(vals)
            if below * 2 >= len(vals):
                note("fuel_axis_clamped_low", "%.0f %% of the running rows sit "
                     "AT OR BELOW the first VE load bin (%.1f) - measured load "
                     "%.1f..%.1f. Every one of those rows reads row 0, so the "
                     "whole range below %.1f shares one VE number and cannot "
                     "be calibrated apart"
                     % (fuel["clamped_low_pct"], lo, min(vals), max(vals), lo),
                     first_bin=lo)
            if above:
                note("fuel_axis_clamped_high", "%.0f %% of the running rows "
                     "sit AT OR ABOVE the last VE load bin (%.1f)"
                     % (fuel["clamped_high_pct"], hi), last_bin=hi)
    idle = [i for i in run_rows if (rpm[i] or 0) < 1200
            and (num(R[i].get("TPSValue")) or num(R[i].get("tpsX10")) or 0) < 10]
    if idle:
        ip = sorted(v for v in (pw[i] for i in idle) if v)
        iv = sorted(v for v in (ve[i] for i in idle) if v is not None)
        if ip:
            fuel["idle_pw_ms_median"] = ip[len(ip) // 2]
            fuel["idle_rows"] = len(ip)
            if ip[len(ip) // 2] > IDLE_PW_NORM_MS * 1.4:
                note("fuel_rich_idle", "idle injector pulse median %.2f ms "
                     "against a ~2.5..3.5 ms norm for this engine "
                     "(CARTEST_ANALYSIS B6) over %d rows - open-loop "
                     "over-fuelling unless lambda proves otherwise"
                     % (ip[len(ip) // 2], len(ip)), pw=ip[len(ip) // 2])
        if iv:
            fuel["idle_ve_median"] = iv[len(iv) // 2]
    for name, key, what in (
            ("warmupEnrich", "fuel_warmup", "warm-up enrichment"),
            ("warmupPct", "fuel_warmup", "warm-up enrichment"),
            ("afterStartPm", "fuel_afterstart", "after-start enrichment"),
            ("fuelCorrection", "fuel_correction", "the total fuel correction")):
        vals = [v for i, v in enumerate(log.col(name)) if running[i]
                and v is not None]
        if not vals:
            continue
        fuel[name] = {"min": min(vals), "max": max(vals)}
        if name in ("warmupEnrich", "warmupPct") and max(vals) > 115.0:
            note(key, "%s reached %.0f %% while running - that multiplies "
                 "every pulse" % (what, max(vals)), pct=max(vals))
        if name == "fuelCorrection" and min(vals) == max(vals) == 100.0:
            note("fuel_correction_inert", "fuelCorrection was exactly 100 %% "
                 "in every running row: NO correction path was active, so "
                 "nothing could have trimmed the mixture")
    S["fuel"] = fuel

    # ------------------------------------------------------------- LAMBDA --
    lam = {"source": log.cfg_text("lambda1Source"),
           "heat_policy": log.cfg_text("lambdaHeatPolicy"),
           "stft_enabled": log.cfg_text("stftEnable")}
    chain = [("raw UR", "lam1UrRaw"), ("heater duty", "heaterDuty"),
             ("effective heater V", "lamVeff"), ("Ri", "lam1RiX10"),
             ("pump current", "lam1IpUa"), ("READY/status", "lambdaStatus"),
             ("published lambda", "lambdaValue")]
    broke = None
    for what, ch in chain:
        vals = [v for v in log.col(ch) if v is not None]
        lam[ch] = ({"min": min(vals), "max": max(vals), "rows": len(vals)}
                   if vals else None)
        moved = bool(vals) and (max(vals) != min(vals) or
                                (ch == "lambdaValue" and max(vals) > 0))
        if broke is None and vals and not moved and ch != "lam1UrRaw":
            broke = (what, ch, vals[0])
    pub = [v for v in log.col("lambdaValue") if v is not None]
    if pub and max(pub) <= 0.0:
        where = (" - the chain stops at %s, which never left %s"
                 % (broke[0], broke[2])) if broke else ""
        note("lambda_never_published", "lambda was 0 in every row: the sensor "
             "never became a measurement%s. The heater policy on this page: "
             "%s" % (where, repr(lam["heat_policy"]) if lam["heat_policy"]
                     else "this firmware's page has no lambdaHeatPolicy "
                          "field (pre-V100)"))
    ri = [v for v in log.col("lam1RiX10") if v is not None]
    if ri and min(ri) >= 6000.0:
        note("lambda_ri_sentinel", "Ri stayed at the 6000 ohm sentinel in "
             "every row: hcwb_ri_x10() returns it for UR at the rail, which a "
             "cold cell and an open cell can share. Fault 13 "
             "(OPEN_CELL) means UR never came off its rail despite commanded "
             "heating. It does not distinguish an open cell from missing "
             "actual H+, absent heating current or another thermal failure; "
             "measure heater feed and current before assigning the cause")
    elif ri:
        lam["ri_min_ohm"] = min(ri)
    hd = [v for v in log.col("heaterDuty") if v is not None]
    if hd:
        lam["heater_duty_max"] = max(hd)
        stopped = [i for i in range(len(R)) if not running[i]]
        heat_stopped = any((log.col("heaterDuty")[i] or 0) > 0
                           for i in stopped)
        lam["heated_with_engine_stopped"] = heat_stopped
        pol = lam["heat_policy"].lower()
        if pol.startswith("ignition") and stopped and not heat_stopped:
            note("lambda_heat_policy", "the policy is %r but the heater was "
                 "never driven in %d row(s) with the engine stopped - an "
                 "ignition-on warm-up did not happen"
                 % (lam["heat_policy"], len(stopped)))
        if pol.startswith("engine running") and heat_stopped:
            note("lambda_heat_policy", "the policy is %r yet the heater ran "
                 "with the engine stopped" % lam["heat_policy"])
        if pol.startswith("disabled"):
            note("lambda_heat_disabled", "lambdaHeatPolicy is %r on this "
                 "page: the sensor is never heated, so lambda cannot publish"
                 % lam["heat_policy"])
    st = log.col("stftState")
    tr = log.col("stftBank1")
    if lam["stft_enabled"].lower() == "on" and any(v is not None for v in tr):
        active = [i for i in run_rows if st[i] is not None
                  and (int(st[i]) & 255) in (2, 4, 8)]
        moved = [v for v in tr if v]
        lam["closed_loop_rows"] = len(active)
        lam["stft_moved"] = bool(moved)
        if not moved:
            note("lambda_closed_loop_never_active", "closed-loop fuel is "
                 "enabled but stftBank1 never left 0: the loop never acted, "
                 "so every mixture number in this log is open loop")
    prev = None
    for i, v in enumerate(log.col("lamWhy")):
        if v is None:
            continue
        w = int(v) & 255
        if prev is not None and w != prev:
            add("lambda_why_change", i, "bank 1 lambda reason %s -> %s"
                % (LAM_WHY.get(prev, prev), LAM_WHY.get(w, w)), why=w)
        prev = w
    S["lambda"] = lam

    # ---------------------------------------------------------------- ETB --
    etb = {"dbw_enabled": log.cfg_text("dbwEnable"),
           "dev_pct": log.cfg("dbwDevX10"), "dev_ms": log.cfg("dbwDevMs"),
           "limp_rpm": log.cfg("etbLimpRpm"),
           "tps1_min": log.cfg("tps1Min"), "tps1_max": log.cfg("tps1Max")}
    tg, ac = log.col("dbwTargetX10"), log.col("dbwActualX10")
    dev = [abs(a - b) for a, b in zip(tg, ac) if a is not None and b is not None]
    if dev:
        dev.sort()
        etb["deviation_pct"] = {"median": dev[len(dev) // 2], "max": dev[-1]}
    fl = [int(v) for v in log.col("dbwFaults") if v]
    if fl:
        etb["faults_seen"] = sorted({bits_text(v, DBW_FAULT_BITS) for v in fl})
        lim = [int(v) for v in log.col("limpCut") if v]
        if lim:
            note("etb_fault_cut_fuel", "a latched throttle fault (%s) was "
                 "present and engine protection cut the fuel (limpCut %s): "
                 "above etbLimpRpm (%s, 0 = 1500 rpm) that cut holds until "
                 "the next key-on"
                 % (", ".join(etb["faults_seen"]),
                    sorted({hex(v) for v in lim}), etb["limp_rpm"]))
    # AN2 is the LM2904 amplified primary track, gain 1+31.6/10.
    # ADC clipping is expected above ~246 TPS1 counts. It is diagnostic,
    # never a supply measurement, position divisor or independent track.
    etb["autocal_measurement_channels"] = ["adc02_IPV", "adc01_TPS1",
                                           "adc03_TPS2"]
    etb["autocal_measurement_note"] = (
        "AN1 and AN3 are independent opposing tracks; AN2 is amplified TPS1 "
        "(gain 4.16), expected to clip. Host-side residuals include scan skew; "
        "they do not establish torque, stop contact or supply voltage.")
    ac = _csv(folder / "autocal.csv")
    trip = [(num(r.get("adc02_IPV")), num(r.get("adc01_TPS1")),
             num(r.get("adc03_TPS2"))) for r in (ac or R)]
    trip = [x for x in trip if all(v is not None for v in x)]
    if trip:
        residual = sorted(abs(x[0] - min(1023, 4.16*x[1])) for x in trip)
        pair = [x[1]+x[2] for x in trip]
        etb["amplified_tps1"] = {
            "gain": 4.16, "rows": len(trip),
            "clipped_rows": sum(x[0] >= 1020 for x in trip),
            "residual_median_counts": round(residual[len(residual)//2], 2),
            "residual_max_counts": round(residual[-1], 2),
            "raw_pair_sum_span": [min(pair), max(pair)]}
        note("etb_amplified_track", etb["autocal_measurement_note"],
             **etb["amplified_tps1"])
    S["etb"] = etb

    # -------------------------------------------------------------- K-LINE --
    kl = {}
    phys = log.meta.get("kline_physical") or (
        ((log.meta.get("phases") or {}).get("kline") or {}).get("physical")) or {}
    kl["physical_mode"] = phys.get("mode")
    kl["physical_source"] = phys.get("source")
    kl["physical_confirmed"] = bool(phys.get("confirmed")) or \
        phys.get("source") == "operator confirmed"
    kl["transitions"] = phys.get("transitions") or []
    kl["software_paths_attempted"] = sorted(
        k for k in ((log.meta.get("phases") or {}).get("kline") or {})
        if k in ("OBD", "DIRECT ECU"))
    if not kl["physical_confirmed"]:
        note("kline_mode_unconfirmed", "the K-line PHYSICAL connection was "
             "not confirmed by the operator in this session (source %r), so "
             "the path label %r is a guess. An init or test command "
             "succeeding does not prove the vehicle OBD K-line carried it"
             % (kl["physical_source"], kl["physical_mode"]))
    for tr2 in kl["transitions"]:
        note("kline_cable_moved", "the KKL was moved %s -> %s during this "
             "session (%s)" % (tr2.get("from"), tr2.get("to"),
                               tr2.get("why")))
    auth = {}
    for ch in ("rxResync", "rxHwOvr", "rxFrameErr", "rxOvf", "rxEchoLost",
               "rxReqs", "rxBytes"):
        sp = log.span(ch)
        if sp:
            auth[ch] = {"max": sp["max"], "rise": sp["rise"]}
    kl["authoritative_counters"] = auth
    bad = {k: v for k, v in auth.items()
           if k.startswith("rx") and k not in ("rxReqs", "rxBytes")
           and v["max"]}
    if bad and auth.get("rxReqs"):
        note("kline_transport", "the ECU's own transport counters over %d "
             "requests: %s. These are the authoritative numbers; a ring "
             "record that disagrees with them is a reporting defect, not a "
             "transport failure"
             % (auth["rxReqs"]["max"],
                ", ".join("%s %d" % (k, v["max"]) for k, v in
                          sorted(bad.items()))))
    S["kline"] = kl

    # ----------------------------------------------- the logging profile ---
    rt = (log.meta.get("phases") or {}).get("runtime") or {}
    S["logging"] = {"profile": rt.get("profile")
                    or log.meta.get("logging_profile"),
                    "rates_configured_s": rt.get("rates_configured_s")
                    or log.meta.get("rates_configured_s"),
                    "groups": {n: {k: g.get(k) for k in
                                   ("period_s", "rows", "rows_per_s",
                                    "bytes_per_row", "exchanges_per_row",
                                    "channels", "missing", "mean_rtt_ms")}
                               for n, g in (rt.get("groups") or {}).items()},
                    "reboots": rt.get("reboots"),
                    "snapshots": rt.get("snapshots"),
                    "onchange": rt.get("onchange")}
    for g, d in (rt.get("groups") or {}).items():
        if d.get("missing"):
            note("logger_channels_unavailable", "the %s group asked for %d "
                 "channel(s) this .ini does not declare, so they are NOT in "
                 "this session: %s" % (g, len(d["missing"]),
                                       ", ".join(d["missing"][:10])))
    # on-change and snapshots are evidence, not findings
    oc = _csv(folder / "onchange.csv")
    if oc:
        S["onchange"] = [{"t": num(r.get("t")), "channel": r.get("channel"),
                          "from": r.get("from"), "to": r.get("to")}
                         for r in oc]
    S["snapshots"] = rt.get("snapshot_log") or []
    if rt.get("reboots"):
        note("ecu_rebooted", "the ECU rebooted %d time(s) during this "
             "session - counters restart there, and snapshots.csv holds the "
             "state read on each side" % rt["reboots"])

    # ================================================ 2026-10-12 RULES ===
    # The owner's car problems of 2026-10-11, each as an automatic check.
    tps = log.col("TPSValue")
    adv = log.col("ignitionTiming")
    load = log.col("engLoad")
    lam = log.col("lambdaValue")
    cut = log.col("fuelCut")
    skips = log.col("sparkSkips")
    dbws = log.col("dbwState")
    dbwf = log.col("dbwFaults")
    flags = log.col("engineFlags")

    # ---- QUICK PRESS: throttle +15 % within 0.2 s while running, then an
    #      rpm dip > 80 rpm within 0.6 s (the "spark cut" feeling)
    i = 0
    tipins = []
    while i < len(R):
        if running[i] and tps[i] is not None:
            j = i
            while j + 1 < len(R) and t[j + 1] - t[i] <= 0.2:
                j += 1
            if tps[j] is not None and tps[j] - tps[i] >= 15:
                r0 = rpm[i] or 0
                k, low, kmin = j, r0, j
                while k + 1 < len(R) and t[k + 1] - t[i] <= 0.8:
                    k += 1
                    if rpm[k] is not None and rpm[k] < low:
                        low, kmin = rpm[k], k
                rec = dict(t_press=round(t[i], 2), rpm=r0, tps_from=tps[i],
                           tps_to=tps[j], rpm_low=low,
                           dip=round(r0 - low),
                           adv_at_dip=adv[kmin], load_at_dip=load[kmin],
                           lambda_at_dip=lam[kmin],
                           fuel_cut=cut[kmin], spark_skips=skips[kmin],
                           dbw_state=(int(dbws[kmin]) & 255)
                           if dbws[kmin] is not None else None)
                tipins.append(rec)
                if r0 - low > 80:
                    add("tipin_stumble", kmin, "quick press %.0f -> %.0f %% at "
                        "%d rpm: rpm fell to %d (-%d) within 0.8 s; at the dip "
                        "advance %s deg, load %s %%, lambda %s, fuel cut %s, "
                        "spark skips %s"
                        % (tps[i], tps[j], r0, low, r0 - low, adv[kmin],
                           load[kmin], lam[kmin], cut[kmin], skips[kmin]),
                        **rec)
                i = j + 1
                continue
        i += 1
    S["tip_ins"] = tipins

    # ---- IDLE: throttle closed, engine running > 20 s after start
    idle_rpm, idle_adv, idle_tgt = [], [], []
    tgt = log.col("idleTargetRpm")
    for i in run_rows:
        if (tps[i] or 0) <= 6 and (rpm[i] or 0) < 2500:
            idle_rpm.append(rpm[i])
            if adv[i] is not None:
                idle_adv.append(adv[i])
            if tgt[i]:
                idle_tgt.append(tgt[i])

    def _med(v):
        v = sorted(x for x in v if x is not None)
        return v[len(v) // 2] if v else None
    S["idle"] = {"rows": len(idle_rpm), "rpm_median": _med(idle_rpm),
                 "target_median": _med(idle_tgt),
                 "advance_median": _med(idle_adv)}
    if idle_rpm and idle_tgt and _med(idle_rpm) > _med(idle_tgt) + 250:
        note("idle_high", "idle runs at %s rpm against a target of %s - the "
             "idle loop holds above target + band (Idle Control: band, trim "
             "authority; the spring/minimum opening may be too high)"
             % (_med(idle_rpm), _med(idle_tgt)))
    if idle_adv and _med(idle_adv) > 20:
        note("idle_advance_high", "idle ignition advance %s deg - expected "
             "about 10-15 deg (Spark Table idle cells)" % _med(idle_adv))

    # ---- THROTTLE: the Bosch setting-range monitor and latched faults
    prev = 0
    for i in range(len(R)):
        f = int(dbwf[i] or 0)
        if f & 0x400 and not prev & 0x400:
            add("dbw_range_request", i, "throttle setting-range limp request "
                "(output saturated > 0.6 s, FR DLR) at %s rpm - fuel is cut "
                "above the throttle-limp rpm while it lasts" % rpm[i],
                faults=f)
        for bit, name in ((0x20, "BRIDGE STATUS FLAG"),
                          (0x40, "SETTING RANGE (5 s)")):
            if f & bit and not prev & bit:
                add("dbw_fault_latched", i, "throttle fault latched: %s "
                    "(faults 0x%04X) - the bridge is off until key-off"
                    % (name, f), faults=f)
        prev = f

    # ---- RESETS: the live witness trend before each reboot
    wit = _csv(folder / "witness.csv")
    if wit:
        def wv(r, k):
            return num(r.get(k))
        S["witness"] = {
            "rows": len(wit),
            "s5500_gap_max_ms": max((wv(r, "s5500_gap_max_ms") or 0)
                                    for r in wit),
            "asic_csum_err_last": wv(wit[-1], "asic_csum_err"),
            "asic_timeouts_last": wv(wit[-1], "asic_timeouts"),
            "umkom_mismatch_last": wv(wit[-1], "umkom_mismatch"),
            "main_pass_max_T": max((wv(r, "main_pass_max_T") or 0)
                                   for r in wit)}
        for a, b in zip(wit, wit[1:]):
            ua, ub = wv(a, "uptime_ms") or 0, wv(b, "uptime_ms") or 0
            # THE UPTIME IS 16 BITS AND WRAPS EVERY 65.5 s (2026-10-14: six
            # "ECU reset" findings in a session that had none while running).
            # A reset is a jump AWAY from where the host clock says the
            # uptime should be now, not merely a smaller number.
            dt = ((num(b.get("t")) or 0.0) - (num(a.get("t")) or 0.0)) * 1000.0
            off = (ub - (ua + dt)) % 65536.0
            if min(off, 65536.0 - off) < 2000.0:
                continue
            if ub + 500 < ua or ub < dt - 2000.0:
                ti = num(a.get("t")) or 0.0
                F.setdefault("reset_witness", []).append(dict(
                    t=ti, text="ECU rebooted (a key cycle or a reset - the BOOT event names the cause) after %s ms uptime (16-bit, modulo 65.5 s): last live "
                    "witness %.1f V, %s rpm, S5500 checksum errors %s, "
                    "timeouts %s, worst S5500 gap %s ms, monitoring "
                    "mismatches %s, worst main-loop pass %s T"
                    % (wv(a, "uptime_ms"), (wv(a, "batt_dv") or 0) / 10.0,
                       wv(a, "rpm"), wv(a, "asic_csum_err"),
                       wv(a, "asic_timeouts"), wv(a, "s5500_gap_max_ms"),
                       wv(a, "umkom_mismatch"), wv(a, "main_pass_max_T"))))

    # ---- BURN: completed and failed flash writes
    com, err = log.col("nvmCommits"), log.col("nvmError")
    pc = pe = None
    for i in range(len(R)):
        if com[i] is not None and pc is not None and com[i] > pc:
            add("burn_done", i, "a Burn reached flash at %s rpm" % rpm[i])
        if err[i] and int(err[i]) & 255 and err[i] != pe:
            low = int(err[i]) & 255
            why = {1: "external SRAM probe failed",
                   2: "the page does not describe a runnable engine",
                   3: "the staged record did not verify",
                   4: "a flash sector would not erase",
                   5: "a flash word would not program",
                   6: "programmed but did not read back",
                   7: "too many interrupted attempts",
                   8: "record from another page layout",
                   9: "every flash cell is used",
                   10: "DEADLINE - no flash window while the engine turned "
                       "(fixed 2026-10-12: a Burn while running waits for the "
                       "engine stop)"}.get(low, "unknown")
            add("burn_error", i, "Burn error 0x%04X (%s) - the tune was NOT "
                "written to flash" % (int(err[i]), why), code=err[i])
        pc = com[i] if com[i] is not None else pc
        pe = err[i]

    S["config"] = log.meta.get("engine_config") or {}
    return F, S


# ===================================================== V100: --compare =====
COMPARE_KEYS = ("executed", "late", "missed", "max_latency_ms",
                "late_per_executed", "missed_per_executed")


def compare(folders, out=None) -> int:
    """The D3 answer: the same scheduler numbers from two (or more) sessions,
    with the logging profile and the MEASURED rate beside them, so the
    question "does logging make the scheduler worse" is read off a table
    instead of assumed."""
    rows = []
    for f in folders:
        folder = Path(f)
        log = SessionLog(folder)
        _F, S = analyse_v100(folder, log)
        sch, lg = S["scheduler"], S["logging"]
        fastg = (lg.get("groups") or {}).get("fast") or {}
        rpmv = [v for v in log.col("rpm") if v is not None]
        rows.append({"session": folder.name, "profile": lg.get("profile"),
                     "fast_rows_per_s": fastg.get("rows_per_s"),
                     "fast_period_s": fastg.get("period_s"),
                     "rpm_min": min([v for v in rpmv if v >= 400], default=None),
                     "rpm_max": max(rpmv) if rpmv else None,
                     "running_rows": sum(1 for v in rpmv if v >= 400),
                     **{k: sch.get(k) for k in COMPARE_KEYS},
                     "by_rpm_band": sch.get("by_rpm_band", {})})
    lines = ["# Scheduler load comparison (D3)", "",
             "Does logger / K-line activity materially worsen scheduler "
             "lateness? The numbers, not an assumption.", "",
             "| session | profile | fast rows/s | rpm | executed | late | "
             "missed | Late/Exec | Missed/Exec | max latency |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append("| %s | %s | %s | %s..%s | %s | %s | %s | %s | %s | %s ms |"
                     % (r["session"], r["profile"], r["fast_rows_per_s"],
                        r["rpm_min"], r["rpm_max"], r["executed"], r["late"],
                        r["missed"], r["late_per_executed"],
                        r["missed_per_executed"], r["max_latency_ms"]))
    lines.append("")
    bands = sorted({b for r in rows for b in r["by_rpm_band"]}, key=int)
    if bands:
        lines += ["## Late per executed event, by rpm band", "",
                  "| rpm from | " + " | ".join(r["session"] for r in rows)
                  + " |", "|---" * (len(rows) + 1) + "|"]
        for b in bands:
            lines.append("| %s | %s |" % (b, " | ".join(
                str((r["by_rpm_band"].get(b) or {}).get("late_per_executed"))
                for r in rows)))
        lines.append("")
    if len(rows) == 2:
        a, b = rows
        for k in ("late_per_executed", "missed_per_executed",
                  "max_latency_ms"):
            x, y = a.get(k), b.get(k)
            if not x or y is None:
                continue
            lines.append("* **%s**: %s -> %s (%+.1f %%) between profile %r "
                         "and %r" % (k, x, y, 100.0 * (y - x) / x,
                                     a["profile"], b["profile"]))
        if a["profile"] == b["profile"]:
            lines.append("")
            lines.append("> Both sessions used the SAME logging profile, so "
                         "this pair cannot answer D3. Take one capture with "
                         "`--profile max` and one with `--profile reduced` "
                         "at the same engine condition.")
    txt = "\n".join(lines) + "\n"
    print(txt)
    if out:
        p = Path(out)
        p.mkdir(parents=True, exist_ok=True)
        (p / "scheduler_compare.md").write_text(txt, encoding="utf-8")
        (p / "scheduler_compare.json").write_text(json.dumps(rows, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("capture", nargs="?")
    ap.add_argument("--out")
    ap.add_argument("--compare", nargs="+", metavar="SESSION",
                    help="two or more session folders: print the scheduler / "
                         "logging-load comparison (D3) instead of analysing")
    a = ap.parse_args(argv)
    if a.compare:
        return compare(a.compare, a.out)
    if not a.capture:
        ap.error("give a capture folder, or --compare A B")
    folder = Path(a.capture)
    session = is_session(folder)
    log = SessionLog(folder) if session else Log(folder)
    F = analyse(log) if log.rows else {}
    subjects = {}
    if session:
        for k, v in analyse_session(folder, log).items():
            F.setdefault(k, []).extend(v)
        vF, subjects = analyse_v100(folder, log)
        # the V100 scheduler checks compute the same thing from the same
        # channels with the ratios and the rpm bands, so the capture-era
        # one-liners would only duplicate them in the report
        for k in ("scheduler_latency", "scheduler_late", "scheduler_missed",
                  "overdwell"):
            F.pop(k, None)
        for k, v in vF.items():
            F.setdefault(k, []).extend(v)
    ini_path = Path(log.meta.get("ini") or
                    (log.meta.get("identity") or {}).get("ini") or "")
    if (folder / "page.bin").exists() and ini_path.is_file():
        tc = tune_check((folder / "page.bin").read_bytes(),
                        ini_path.read_text(encoding="utf-8", errors="replace"))
        if tc:
            F["tune_check"] = [{"t": 0.0, "text": t} for t in tc]
    ve_cells = F.pop("_ve_cells", [])
    knock_cyl = F.pop("_knock_cyl", [])
    rpm = [v for v in log.col("rpm") if v is not None]
    run_s = sum(1 for v in rpm if v >= 400) * (
        (log.t[-1] - log.t[0]) / max(1, len(log.t) - 1)) if log.t else 0
    summary = {
        "capture": str(folder), "rows": len(log.rows),
        "duration_s": round(log.t[-1] - log.t[0], 1) if log.t else 0,
        "running_s": round(run_s, 1), "rpm_max": max(rpm) if rpm else None,
        "signature": (log.meta.get("identity") or {}).get("signature")
        if isinstance(log.meta.get("identity"), dict) else log.meta.get("identity"),
        "page_sha256": log.meta.get("page_sha256"),
        "tool_version": log.meta.get("tool_version"),
        "tool_git": log.meta.get("tool_git"),
        "counts": {k: len(v) for k, v in sorted(F.items())},
        "ve_cells": ve_cells,
        "knock_cylinders": knock_cyl,
        "subjects": subjects,
        "findings": F,
    }
    out = Path(a.out) if a.out else folder
    out.mkdir(parents=True, exist_ok=True)
    (out / "analysis.json").write_text(json.dumps(summary, indent=1))
    lines = ["# Capture analysis", "",
             "* capture: `%s`" % folder.name,
             "* %d rows, %.1f s, running %.1f s, rpm max %s" % (
                 summary["rows"], summary["duration_s"], summary["running_s"],
                 summary["rpm_max"]),
             "* firmware signature: %s; page sha256: %s" % (
                 summary["signature"], (summary["page_sha256"] or "-")[:16]),
             "* logger %s (git %s)" % (summary["tool_version"],
                                       summary["tool_git"]),
             "", "Evidence only - nothing here changes the calibration.", ""]
    if subjects:
        lg = subjects.get("logging") or {}
        kl = subjects.get("kline") or {}
        cfg = subjects.get("config") or {}
        lines += ["## This session's own terms", "",
                  "* logging profile: **%s**, rates %s" % (
                      lg.get("profile"), lg.get("rates_configured_s")),
                  "* measured: " + ", ".join(
                      "%s %s rows/s (%s ch, %s B, %s exchange(s))"
                      % (n, d.get("rows_per_s"), d.get("channels"),
                         d.get("bytes_per_row"), d.get("exchanges_per_row"))
                      for n, d in sorted((lg.get("groups") or {}).items())),
                  "* K-line PHYSICAL: **%s** (%s)%s; software path(s) "
                  "attempted: %s" % (
                      kl.get("physical_mode"), kl.get("physical_source"),
                      "" if kl.get("physical_confirmed")
                      else " **NOT CONFIRMED**",
                      ", ".join(kl.get("software_paths_attempted") or []) or
                      "-"),
                  "* configuration: %s, %s, %s, load %s, sync %s, "
                  "trigAngle %s deg, DBW %s, lambda 1 %s, heater policy %s" % (
                      cfg.get("firingOrder"), cfg.get("injStrategy"),
                      cfg.get("ignStrategy"), cfg.get("loadSource"),
                      cfg.get("syncMode"), cfg.get("trigAngleX10"),
                      cfg.get("dbwEnable"), cfg.get("lambda1Source"),
                      cfg.get("lambdaHeatPolicy")),
                  ""]
        sch = subjects.get("scheduler") or {}
        if sch.get("executed"):
            lines += ["## Scheduler", "",
                      "| executed | late | missed | Late/Exec | Missed/Exec "
                      "| max latency |", "|---|---|---|---|---|---|",
                      "| %s | %s | %s | %s | %s | %s ms |" % (
                          sch["executed"], sch["late"], sch["missed"],
                          sch.get("late_per_executed"),
                          sch.get("missed_per_executed"),
                          sch.get("max_latency_ms")), ""]
            band = sch.get("by_rpm_band") or {}
            if band:
                lines += ["| rpm from | rows | executed | late | Late/Exec | "
                          "max latency |", "|---|---|---|---|---|---|"]
                for b in sorted(band, key=int):
                    d = band[b]
                    lines.append("| %s | %s | %.0f | %.0f | %s | %s ms |" % (
                        b, d["rows"], d["executed"], d["late"],
                        d.get("late_per_executed"), d.get("max_latency_ms")))
                lines.append("")
        oc = subjects.get("onchange") or []
        if oc:
            lines += ["## State / configuration changes caught on change (%d)"
                      % len(oc), ""]
            for e in oc[:20]:
                lines.append("* t=%.2f s: %s %s -> %s" % (
                    e["t"] or 0.0, e["channel"], e["from"], e["to"]))
            if len(oc) > 20:
                lines.append("* ... %d more in analysis.json" % (len(oc) - 20))
            lines.append("")
    if ve_cells:
        lines += ["## VE evidence, every steady cell (measured / target lambda)",
                  "", "| rpm from | load from | rows | ratio | VE reads |",
                  "|---|---|---|---|---|"]
        for c in ve_cells:
            lines.append("| %d | %d | %d | %.3f | %+.1f %% |" % (
                c["rpm_from"], c["load_from"], c["rows"],
                c["measured_over_target"], -c["ve_evidence_pct"]))
        lines.append("")
    if knock_cyl:
        lines += ["## Knock level per cylinder (KI / reference; tune from this)",
                  "", "| cyl | rows | level mean | level max | reference mean |",
                  "|---|---|---|---|---|"]
        for c in knock_cyl:
            lines.append("| %d | %d | %.3f | %.3f | %s |" % (
                c["cyl"], c["rows"], c["level_mean"], c["level_max"],
                c["ref_mean"]))
        lines.append("")
    if not F:
        lines.append("No findings.")
    for k in sorted(F):
        v = F[k]
        lines.append("## %s (%d)" % (k, len(v)))
        for e in v[:8]:
            lines.append("* t=%.2f s: %s%s" % (e["t"], e["text"],
                                               " (AUX channel)" if e.get("aux") else ""))
        if len(v) > 8:
            lines.append("* ... %d more in analysis.json" % (len(v) - 8))
        lines.append("")
    (out / "analysis.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:60]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
