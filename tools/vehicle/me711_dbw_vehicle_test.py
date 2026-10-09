#!/usr/bin/env python3
r"""
me711_dbw_vehicle_test.py - ETB commissioning on the car, in one pass, logged.

    py me711_dbw_vehicle_test.py --observe
    py me711_dbw_vehicle_test.py --autocal  --i-authorize-throttle-movement
    py me711_dbw_vehicle_test.py --autotune --i-authorize-throttle-movement
    py me711_dbw_vehicle_test.py --all      --i-authorize-throttle-movement

Close TunerStudio first (same COM port). Key ON, engine OFF, hands and feet
off the throttle and pedal.

WHAT IT DOES
  --observe   20 s of pedal/TPS/bridge telemetry, nothing commanded.
  --all       COMMISSION ETB ('!C3', firmware hcetbcal.c): observe 5 s,
              endpoint AutoCal -> validate -> PID autotune (only if AutoCal
              passed) -> validate, ONE result. If AutoCal passes and the PID
              autotune fails, the endpoints are KEPT (RAM) and the result is
              "ENDPOINTS OK, COMMISSIONING INCOMPLETE".
  --autocal   endpoint AutoCal only ('!C1'): 50 % toward each stop for 1 s,
              a +20 % stop test, release. TPS closed/open + motor direction.
  --autotune  PID autotune only ('!C2'), with the STORED endpoints (refused
              if there are none): relay around 50 %, 8 + 16 cycles, rusEFI's
              rule -> Kp/Ki/Kd. For re-tuning without re-calibrating.

It NEVER burns and NEVER enables DBW: after a PASS, open TunerStudio,
review, and Burn if you want to keep the values.

BEFORE ANY MOVEMENT it proves: the ECU identity and a matching .ini, engine
stopped (rpm 0, no crank edges), configuration valid, both TPS tracks off
the rails, closed-loop DBW not running, outputs permitted with the key on,
no ETB procedure already running, battery >= --battery-min (11.0 V).
Ctrl-C at any time sends the abort command; the firmware releases the
bridge on every exit anyway.

EVIDENCE: VEHICLE_EVIDENCE\DBW_VEHICLE_TEST_<UTC>\ beside this tool (in the
workspace: <HaniCore>\evidence\) - metadata.json, before_page.bin,
after_page.bin, observe.csv, autocal.csv, autotune.csv, events.jsonl,
frames.jsonl, console.log, summary.txt.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_commission as MC             # noqa: E402

TOOL_VERSION = "1.1 (V93)"
ALLOWED = b"SQVOR!"          # read-only protocol + the '!C' commands below
RES = {0: "never run", 1: "RUNNING", 2: "PASS (endpoints)", 3: "FAIL",
       4: "PASS (PID)"}
FIELDS = [
    "rpm", "syncState", "battDv", "cfgValidation", "outputAuthority",
    "safetyInhibits", "runOn", "adc01_TPS1", "adc03_TPS2", "adc08_PEDAL1",
    "adc09_PEDAL2", "dbwState", "dbwFaults", "dbwDutyX10", "dbwSfLevel",
    "dbwTps1X10", "dbwTps2X10", "dbwTargetX10", "dbwActualX10",
    "etbCalStatus", "etbCalRest1", "etbCalA1", "etbCalB1", "etbCalA2",
    "etbCalB2", "etbCalRest2", "etbTuneAmpX10", "etbTuneTuMs", "etbCalDetail",
    "etbTuneCycles", "etbTuneKp", "etbTuneKi", "etbTuneKd",
    "etbTuneAmpLiveX10", "etbTuneTuLiveMs", "etbDrive", "etbPhaseMs",
    "etbProc",
]
# The long explanation behind each SHORT reason the ECU publishes (the UI
# shows only the short one - the car test showed sentence-long indicator
# strings unreadable).
WHY_DETAIL = {
    1: "the engine turned during the procedure (rpm > 0)",
    2: "outputs not permitted: page invalid, S5500 link down or key off",
    3: "the CJ220 H-bridge pulled its fault pin (SF) while driving",
    4: "a TPS track read at an ADC rail - open or shorted wiring",
    5: "direction A never moved the plate - bridge or motor wiring",
    6: "direction B never moved the plate - bridge or motor wiring",
    7: "a TPS track's closed-open span was below 100 counts (rusEFI 0.5 V)",
    8: "the procedure's time limit was reached",
    9: "closed-loop DBW is running - set dbwEnable Off first",
    10: "aborted by the operator",
    11: "a TPS track has no input on this board",
    12: "TPS 1 did not normalise with the calibration in use",
    13: "the plate left the 20..80 % band during the autotune relay",
    14: "end A moved under +20 % more torque: it was a spring equilibrium, "
        "not a stop - the bridge is not delivering the commanded torque",
    15: "end B moved under +20 % more torque: it was a spring equilibrium, "
        "not a stop - the bridge is not delivering the commanded torque",
    16: "the unpowered rest position is not between the two ends",
    17: "TPS2's rest position fraction differs from TPS1's by more than 10 %",
    18: "the plate never reached 50 % within 1.5 s (weak drive or bias)",
    19: "autotune amplitude outside 0.5..30 % or period outside 20..1000 ms",
    20: "no valid stored endpoints - run Commission ETB or AutoCal first",
}
SAFETY_WHY = {1, 2, 3, 4, 8, 11}      # the ECU stopped it for safety
CSV_COLS = [
    "t", "phase", "phase_text", "result", "why", "tps1_raw", "tps2_raw",
    "tps1_norm_x10", "tps2_norm_x10", "tps1_vel_cps", "driving", "dir",
    "duty_x10", "phase_ms", "detail", "sf_level", "dbw_state", "dbw_faults",
    "batt_v", "rpm", "cycles", "amp_live_x10", "tu_live_ms", "kp", "ki", "kd",
    "app1_raw", "app2_raw",
]


def norm(raw, lo, hi):
    """hc_dbw_normalise: 0 closed .. 1000 open, either direction."""
    if lo is None or hi is None or abs(hi - lo) < 32:
        return None
    if hi >= lo:
        return round((raw - lo) * 1000 / (hi - lo))
    return round((lo - raw) * 1000 / (lo - hi))


class DbwTest:
    def __init__(self, a, sess: MC.Session):
        self.a, self.s = a, sess
        self.link, self.ini, self.sig, self.ver = MC.connect(
            a.port, a.ini, sess, ALLOWED)
        if "etbCalDetail" not in self.ini.scalars:
            raise SystemExit("this ECU/.ini predates the V93 ETB procedure "
                             "(no etbCalDetail channel) - flash V93 first")
        self.rd = MC.Reader(self.link, self.ini, FIELDS)
        self.lists = self.ini.lists
        self.page = None
        self.cal = {}

    # ------------------------------------------------------------ helpers
    def sample(self):
        for _ in range(3):
            v = self.rd.read()
            if v is not None:
                return v
        return None

    def txt(self, lst, i):
        names = self.lists.get(lst, [])
        return names[i] if 0 <= i < len(names) else str(i)

    def status(self, v):
        s = v.get("etbCalStatus", 0)
        return s & 15, (s >> 4) & 15, (s >> 8) & 255

    def read_page(self, name):
        pg = self.link.page_read()
        if pg is None:
            self.s.say("  (page read failed)")
            return None
        (self.s.dir / name).write_bytes(pg)
        cfg = MC.VC.page_config(self.ini.path, pg)
        self.cal = {k: cfg.get(k) for k in ("tps1Min", "tps1Max", "tps2Min",
                                            "tps2Max", "dbwEnable")}
        import re
        txt = self.ini.path.read_text(encoding="utf-8", errors="replace")
        for n in ("dbwKp", "dbwKi", "dbwKd", "dbwMotorDir", "tpsCorrelation",
                  "dbwAutocalDuty", "dbwAutocalMs", "dbwTuneAmp"):
            m = re.search(r"^\s*%s\s*=\s*(?:scalar|bits)\s*,\s*(U\d\d)\s*,\s*(\d+)"
                          % n, txt, re.M)
            if m:
                w = 1 if m.group(1) == "U08" else 2
                o = int(m.group(2))
                self.cal[n] = int.from_bytes(pg[o:o + w], "big")
        return pg

    # ---------------------------------------------------------- preflight
    def preflight(self, moving: bool) -> bool:
        s = self.s
        v = self.sample()
        if v is None:
            s.say("PREFLIGHT: no telemetry")
            return False
        checks = []

        def c(ok, text):
            checks.append((ok, text))
            s.say("  [%s] %s" % ("OK  " if ok else "STOP", text))

        s.say("PREFLIGHT")
        c(v["rpm"] == 0 and v["syncState"] == 0,
          "engine stopped (rpm %d, syncState %d)" % (v["rpm"], v["syncState"]))
        c(v["cfgValidation"] == 0, "configuration valid (cfgValidation %d)"
          % v["cfgValidation"])
        t1, t2 = v["adc01_TPS1"] & 1023, v["adc03_TPS2"] & 1023
        c(10 <= t1 <= 1013 and 10 <= t2 <= 1013,
          "both TPS tracks off the rails (TPS1 %d, TPS2 %d counts)" % (t1, t2))
        st = v["dbwState"] & 0xFF
        c(st not in (1, 2), "closed-loop DBW not owning the bridge "
          "(dbwState %d%s)" % (st, " - set dbwEnable Off" if st in (1, 2) else ""))
        _res, ph, _why = self.status(v)
        c(ph == 0, "no ETB procedure already running (phase %d)" % ph)
        keyoff = (v.get("runOn", 0) >> 8) & 1
        c(not keyoff and (v["outputAuthority"] & 2) != 0,
          "key on, throttle outputs permitted (authority 0x%X)"
          % v["outputAuthority"])
        b = v["battDv"] / 10.0
        c(b >= self.a.battery_min, "battery %.1f V >= %.1f V" %
          (b, self.a.battery_min))
        if b < 12.0:
            s.say("  note: battery below 12.0 V - a weak supply weakens the "
                  "bridge; charge or connect a charger for the best result")
        if v["dbwFaults"]:
            s.say("  note: dbwFaults 0x%04X latched (does not block the "
                  "procedure; cleared at the next key cycle)" % v["dbwFaults"])
        ok = all(k for k, _ in checks)
        s.meta["steps"].append({"step": "preflight", "moving": moving,
                                "ok": ok, "checks": checks})
        s.event("PREFLIGHT", ok=ok)
        return ok

    # ------------------------------------------------------------ observe
    def observe(self, seconds):
        self.s.say("\nOBSERVE %d s - nothing is commanded. Move the pedal if "
                   "you like; the throttle stays where the spring holds it."
                   % seconds)
        rows = self.run_capture("observe.csv", None, seconds, stop_on_result=False)
        if rows:
            t1 = [r["tps1_raw"] for r in rows]
            a1 = [r["app1_raw"] for r in rows]
            self.s.say("  TPS1 raw %d..%d, APP1 raw %d..%d over %d samples"
                       % (min(t1), max(t1), min(a1), max(a1), len(rows)))

    # ------------------------------------------------------ capture loop
    def row(self, v, t, prev):
        res, ph, why = self.status(v)
        t1, t2 = v["adc01_TPS1"] & 1023, v["adc03_TPS2"] & 1023
        vel = ""
        if prev is not None and t > prev[0]:
            vel = round((t1 - prev[1]) / (t - prev[0]))
        drv = v.get("etbDrive", 0)
        return {
            "t": round(t, 3), "phase": ph,
            "phase_text": self.txt("hcEtbPhaseList", ph), "result": res,
            "why": why, "tps1_raw": t1, "tps2_raw": t2,
            "tps1_norm_x10": norm(t1, self.cal.get("tps1Min"),
                                  self.cal.get("tps1Max")),
            "tps2_norm_x10": norm(t2, self.cal.get("tps2Min"),
                                  self.cal.get("tps2Max")),
            "tps1_vel_cps": vel, "driving": (drv >> 15) & 1,
            "dir": (drv >> 14) & 1, "duty_x10": drv & 1023,
            "phase_ms": v.get("etbPhaseMs", 0), "detail": v.get("etbCalDetail", 0),
            "sf_level": v.get("dbwSfLevel", 0), "dbw_state": v["dbwState"],
            "dbw_faults": v["dbwFaults"], "batt_v": v["battDv"] / 10.0,
            "rpm": v["rpm"], "cycles": v.get("etbTuneCycles", 0),
            "amp_live_x10": v.get("etbTuneAmpLiveX10", 0),
            "tu_live_ms": v.get("etbTuneTuLiveMs", 0),
            "kp": v.get("etbTuneKp", 0), "ki": v.get("etbTuneKi", 0),
            "kd": v.get("etbTuneKd", 0),
            "app1_raw": v["adc08_PEDAL1"] & 1023,
            "app2_raw": v["adc09_PEDAL2"] & 1023,
        }

    def run_capture(self, name, command, max_s, stop_on_result=True,
                    post_s=1.0, terminal=(2, 3, 4, 5)):
        s = self.s
        f = (s.dir / name).open("w", newline="", encoding="utf-8")
        w = csv.DictWriter(f, fieldnames=CSV_COLS)
        w.writeheader()
        rows, prev, last_ph, done_at = [], None, None, None
        t0 = time.monotonic()
        if command is not None:
            if not self.link.command(command):
                s.say("  the command did not get TS_OK - nothing started")
                f.close()
                return rows
            s.event("COMMAND", cmd=command.hex())
        try:
            while True:
                t = time.monotonic() - t0
                v = self.sample()
                if v is None:
                    s.say("  telemetry lost")
                    s.event("TELEMETRY_LOST", t=round(t, 2))
                    break
                r = self.row(v, t, prev)
                w.writerow(r)
                rows.append(r)
                prev = (t, r["tps1_raw"])
                if r["phase"] != last_ph:
                    s.say("  %6.2f s  phase %-44s TPS1 %4d TPS2 %4d"
                          % (t, r["phase_text"], r["tps1_raw"], r["tps2_raw"]))
                    s.event("PHASE", t=round(t, 3), phase=r["phase"],
                            text=r["phase_text"])
                    last_ph = r["phase"]
                if (stop_on_result and done_at is None and t > 0.3
                        and r["result"] in terminal and r["phase"] == 0):
                    done_at = t
                if done_at is not None and t - done_at >= post_s:
                    break
                if t >= max_s:
                    if stop_on_result:
                        s.say("  tool time limit %.0f s - sending abort" % max_s)
                        self.link.command(b"C\x00")
                    break
        except KeyboardInterrupt:
            s.say("  Ctrl-C - sending ABORT; the run ends here")
            self.link.command(b"C\x00")
            s.event("ABORT_SENT")
            self.stop_all = True
        f.close()
        return rows

    # ------------------------------------------------------ the procedures
    def run_proc(self, kind: str) -> str:
        """kind: 'commission' ('!C3'), 'autocal' ('!C1'), 'autotune' ('!C2').
        Returns the short verdict (PASS / ... / FAIL ...)."""
        s = self.s
        arg, csvname, what = {
            "commission": (b"C\x03", "commission.csv", "ETB COMMISSIONING"),
            "autocal": (b"C\x01", "autocal.csv", "AUTOCAL"),
            "autotune": (b"C\x02", "autotune.csv", "PID AUTOTUNE"),
        }[kind]
        s.say("\n%s - the throttle WILL move. Hands off." % what)
        before = self.read_page("before_page.bin")
        old = dict(self.cal)
        if kind == "autotune" and (old.get("tps1Min") is None
                                   or abs((old.get("tps1Max") or 0)
                                          - (old.get("tps1Min") or 0)) < 100
                                   or abs((old.get("tps2Max") or 0)
                                          - (old.get("tps2Min") or 0)) < 100):
            s.say("  refused here: no valid stored endpoints - run --all or "
                  "--autocal first")
            self.summary += ["PID AUTOTUNE: NOT RUN", "reason: NO ENDPOINTS",
                             "detail: %s" % WHY_DETAIL[20]]
            return "NOT RUN"
        # commission: an intermediate AUTOCAL PASS is not the end of it
        rows = self.run_capture(csvname, arg, 25.0,
                                terminal=(3, 5) if kind == "commission"
                                else (2, 3, 4, 5))
        if not rows:
            self.summary.append("%s: NOT STARTED (no TS_OK)" % what)
            return "NOT STARTED"
        v = self.sample() or {}
        res, why = v.get("etbCalStatus", 0) & 15, (v.get("etbCalStatus", 0) >> 8) & 255
        proc = v.get("etbProc", 0)
        failph, calok, oper = (proc >> 4) & 15, (proc >> 8) & 1, (proc >> 9) & 1
        after = self.read_page("after_page.bin")
        changes = MC.page_diff(self.ini.path, before, after) \
            if before and after else []
        phases = []
        for r in rows:
            if not phases or phases[-1] != r["phase_text"]:
                phases.append(r["phase_text"])
        L = []
        if res in (2, 4, 5):
            L.append("%s: PASS" % what)
        elif res == 3 and kind == "commission" and calok:
            L.append("%s: FAIL - ENDPOINTS OK, COMMISSIONING INCOMPLETE" % what)
        else:
            L.append("%s: FAIL" % what)
        if res == 3:
            L.append("failed stage: %s" % self.txt("hcEtbPhaseList", failph))
            L.append("reason: %s" % self.txt("hcEtbWhyList", why))
            L.append("detail: %s (etbCalDetail %s)" % (WHY_DETAIL.get(why, "-"),
                                                       v.get("etbCalDetail")))
            L.append("stopped by: %s" % ("OPERATOR ABORT" if oper or why == 10
                                         else "ECU SAFETY ABORT"
                                         if why in SAFETY_WHY
                                         else "procedure check"))
        L.append("phases seen: %s" % " > ".join(phases))
        if kind in ("commission", "autocal"):
            L.append("endpoints  rest TPS1 %s TPS2 %s | end A %s/%s | end B %s/%s"
                     % (v.get("etbCalRest1"), v.get("etbCalRest2"),
                        v.get("etbCalA1"), v.get("etbCalA2"),
                        v.get("etbCalB1"), v.get("etbCalB2")))
            if res in (2, 5) or calok:
                L.append("stored closed/open  TPS1 %s/%s  TPS2 %s/%s (were "
                         "%s/%s, %s/%s); motor direction %s" % (
                             self.cal.get("tps1Min"), self.cal.get("tps1Max"),
                             self.cal.get("tps2Min"), self.cal.get("tps2Max"),
                             old.get("tps1Min"), old.get("tps1Max"),
                             old.get("tps2Min"), old.get("tps2Max"),
                             "Normal (leg 0 opens)"
                             if self.cal.get("dbwMotorDir") == 0
                             else "Reversed (leg 1 opens)"))
        if kind in ("commission", "autotune") and (res in (4, 5) or
                                                   any(r["cycles"] for r in rows)):
            L.append("autotune  cycles %s, amplitude %.1f %%, Tu %s ms (means); "
                     "last cycle %.1f %% / %s ms" % (
                         max(r["cycles"] for r in rows),
                         (v.get("etbTuneAmpX10") or 0) / 10.0, v.get("etbTuneTuMs"),
                         rows[-1]["amp_live_x10"] / 10.0, rows[-1]["tu_live_ms"]))
            cands = sorted({(r["kp"], r["ki"], r["kd"]) for r in rows if r["kp"]})
            L.append("candidate gains seen: %d distinct (all in the CSV)"
                     % len(cands))
            L.append("PID  stored before Kp %s Ki %s Kd %s  ->  now Kp %s Ki %s Kd %s"
                     % (old.get("dbwKp"), old.get("dbwKi"), old.get("dbwKd"),
                        self.cal.get("dbwKp"), self.cal.get("dbwKi"),
                        self.cal.get("dbwKd")))
            if res in (4, 5) and (v.get("etbCalDetail") or 0) & 0x8000:
                L.append("NOTE: KI LIMITED - a gain hit its page maximum "
                         "(mask %d: 1 Kp 2 Ki 4 Kd), lower than the rule"
                         % (v["etbCalDetail"] & 7))
        L.append("page changes (RAM): %s" % (", ".join(changes) or "none"))
        for ln in L:
            s.say("  " + ln)
        s.meta["steps"].append({"step": kind, "result": res, "why": why,
                                "etbProc": proc, "changes": changes,
                                "summary": L})
        self.summary.extend(L)
        return L[0].split(": ", 1)[1]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="auto", help="COMx, default: find it")
    ap.add_argument("--ini", default=None, help="the .ini (default: the one "
                    "matching the ECU's signature and version)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--observe", action="store_true")
    g.add_argument("--autocal", action="store_true")
    g.add_argument("--autotune", action="store_true")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--i-authorize-throttle-movement", action="store_true",
                    dest="auth", help="required for --autocal/--autotune/--all")
    ap.add_argument("--battery-min", type=float, default=11.0)
    ap.add_argument("--seconds", type=int, default=20, help="--observe length")
    ap.add_argument("--evidence", default=None, help="evidence root folder")
    a = ap.parse_args(argv)
    moving = not a.observe
    if moving and not a.auth:
        print("REFUSED: --autocal/--autotune/--all move the throttle. Add "
              "--i-authorize-throttle-movement to confirm the engine is OFF "
              "and nobody's hands are near the throttle.")
        return 2
    sess = MC.Session("DBW_VEHICLE_TEST",
                      Path(a.evidence) if a.evidence else None, argv)
    sess.meta["tool_version"] = TOOL_VERSION
    sess.say("HaniCore DBW vehicle test %s -> %s" % (TOOL_VERSION, sess.dir))
    rc = 1
    try:
        t = DbwTest(a, sess)
        t.summary = []
        t.read_page("start_page.bin")
        try:
            pre_ok = t.preflight(moving)
        except KeyboardInterrupt:
            pre_ok = None
        if pre_ok is None:
            t.summary.append("STOPPED BY THE OPERATOR (Ctrl-C) - nothing was "
                             "commanded")
        elif not pre_ok:
            t.summary.append("PREFLIGHT FAILED - nothing was commanded")
            sess.say("\nPREFLIGHT FAILED - nothing was commanded.")
        else:
            ok = True
            t.stop_all = False
            if a.observe or a.all:
                t.observe(a.seconds if a.observe else 5)
            verdict = None
            if t.stop_all:
                t.summary.append("STOPPED BY THE OPERATOR (Ctrl-C) - nothing "
                                 "was commanded")
                verdict = "ABORTED"
            elif a.all:
                verdict = t.run_proc("commission")
            elif a.autocal:
                verdict = t.run_proc("autocal")
            elif a.autotune:
                verdict = t.run_proc("autotune")
            if moving:
                ok = verdict == "PASS"
                changed = any(ln.startswith("page changes (RAM):")
                              and not ln.endswith("none") for ln in t.summary)
                t.summary.append("VALUES ARE IN RAM ONLY - open TunerStudio, "
                                 "review, and BURN to keep them. DBW was NOT "
                                 "enabled." if changed else
                                 "NOTHING WAS CHANGED.")
            rc = 0 if ok else 1
        (sess.dir / "summary.txt").write_text(
            "HaniCore DBW vehicle test %s\n%s\n%s / %s\n\n%s\n" % (
                TOOL_VERSION, sess.dir, t.ver, t.sig, "\n".join(t.summary)),
            encoding="utf-8")
        sess.say("\n" + "\n".join(t.summary))
        sess.say("\nEvidence: %s" % sess.dir)
    finally:
        sess.close()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
