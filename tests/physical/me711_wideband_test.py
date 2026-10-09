#!/usr/bin/env python3
r"""
me711_wideband_test.py - the onboard CJ120 / LSU 4.2 wideband, qualified in
one pass. Close TunerStudio first. Three modes:

    py tests\physical\me711_wideband_test.py --modes --i-authorize-cj120-modes
        ENGINE OFF, key on (bench or car). Holds BOTH CJ120s in each
        INIT_REG1 mode for 1.5 s with the V96 bench command '!T 5 8..13' and
        records UR (ASIC AN12/13), UA (AN6/AN4), DIAG and the read-back:
          8 0x88 cold   9 RA   10 LA   11 PA (0xC8)   12 CAL 0x9C   13 0x90
        Proves the register's bits on THIS board: RA must move UR onto the
        82.5 ohm reference, LA must put UA at the pump zero (0.285..0.315
        VCC). Heater stays OFF throughout. Page values (lambda sources,
        testValue) are written to RAM and restored; nothing is burned.

    py tests\physical\me711_wideband_test.py --auto --seconds 20
        READ-ONLY. Watches the automatic sequence after key-on: calibration
        (lamMode 0x9C), the calibration values, the heater state and any
        fault. With no sensor on the bench it must end in fault 2 (heater
        open / no sensor) with the heater never driven. The lambda sources
        must already be "on-board" in the page (this mode writes nothing).

    py tests\physical\me711_wideband_test.py --vehicle --seconds 300 [--banks 1|2|1,2]
        READ-ONLY, engine running on the car: the warm-up record - battery,
        heater state / effective voltage / duty, Ri, UR, UA, pump current,
        lambda and its validity, DIAG, faults - at the link's full rate, and
        the time from engine start to PREHEAT, RAMP, CLOSED and READY. It
        never writes; lambda must be enabled in the page by the operator.
        V97: a VERDICT per bank. A FITTED bank (--banks, default 1 = the
        AWT's one pre-cat LSU) passes only if: calibration OK, no fault,
        READY within 90 s of the engine running, lambda valid >= 90 % of the
        time after READY, Ri at READY within +-15 % of 82.5 ohm, heater
        Veff never above 12.0 V, every valid lambda inside 0.70..1.60. An
        UNFITTED bank must show "no sensor" (fault 2) with its heater never
        driven. Each FAIL names the first rule it broke.

    py tests\physical\me711_wideband_test.py --selftest
        OFFLINE: the verdict rules against synthetic records (a good
        warm-up, no sensor, a latched fault, never READY, an overdriven
        heater, an unfitted bank that was heated).

Evidence: <raw evidence folder>\<MODE>_<UTC>\ - samples.csv,
result.json, summary.txt, events.jsonl, frames.jsonl, console.log,
metadata.json. Lambda is display-only in the firmware: nothing here enables
fuel correction.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_commission as MC             # noqa: E402

TOOL_VERSION = "1.1 (V97)"
HCB_TEST_ASIC = 5
MODES = {8: ("COLD", 0x88), 9: ("RA", 0x98), 10: ("LA", 0x8C),
         11: ("PA", 0xC8), 12: ("CAL", 0x9C), 13: ("V95 0x90", 0x90)}
STATES = ["OFF", "WAIT", "PREHEAT", "RAMP", "CLOSED", "READY", "FAULT"]
FAULTS = ["-", "heater short GND", "heater open / no sensor",
          "heater short UB", "IA/IP line", "UN line", "VM line", "chip",
          "calibration", "did not heat", "overheat", "underheat",
          "no Ri signal"]
FIELDS = ["rpm", "syncState", "battDv", "runOn", "lambdaStatus",
          "lambda1X1000", "lambda2X1000", "cj120Diag", "cj120Ident",
          "cj120Reg1", "heaterDuty", "adc06_LS1VK", "adc04_LS2VK",
          "lam1RiX10", "lam2RiX10", "lam1UaZero", "lam2UaZero", "lam1UrCal",
          "lam2UrCal", "lamFault", "lam1UrRaw", "lam2UrRaw", "lamVeff",
          "lamMode", "hcbState", "hcbRefuse"]
OPTIONAL = ["lam1IpUa", "lam2IpUa"]      # V97: the raw pump current


def const(ini_path, name):
    import re
    txt = ini_path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^\s*%s\s*=\s*(?:scalar|bits)\s*,\s*(U08|U16)\s*,\s*(\d+)"
                  % name, txt, re.M)
    return (1 if m.group(1) == "U08" else 2, int(m.group(2)))


def bank(v, b):
    """One bank's view of a telemetry sample."""
    st = v["lambdaStatus"]
    sh = 2 + 3 * b
    return {
        "state": STATES[min((st >> sh) & 7, 6)],
        "valid": (st >> b) & 1, "chip": (st >> (8 + b)) & 1,
        "ready": (st >> (10 + b)) & 1, "pump": (st >> (12 + b)) & 1,
        "cal_ok": (st >> (14 + b)) & 1,
        "lambda": (v["lambda2X1000"] if b else v["lambda1X1000"]),
        "diag": (v["cj120Diag"] >> (8 * b)) & 0xFF,
        "reg1": (v["cj120Reg1"] >> (8 * b)) & 0xFF,
        "mode": (v["lamMode"] >> (8 * b)) & 0xFF,
        "ua": v["adc04_LS2VK"] if b else v["adc06_LS1VK"],
        "ur": v["lam2UrRaw"] if b else v["lam1UrRaw"],
        "ri": v["lam2RiX10"] if b else v["lam1RiX10"],
        "ua0": v["lam2UaZero"] if b else v["lam1UaZero"],
        "urc": v["lam2UrCal"] if b else v["lam1UrCal"],
        "fault": (v["lamFault"] >> (8 * b)) & 0xFF,
        "veff": ((v["lamVeff"] >> (8 * b)) & 0xFF) / 10.0,
        "duty": (v["heaterDuty"] >> (8 * b)) & 0xFF,
        "ip": v.get("lam2IpUa" if b else "lam1IpUa"),
    }


# ------------------------------------------------------------ the verdict --
READY_LIMIT_S = 90.0
RI_BAND = (82.5 * 0.85, 82.5 * 1.15)
LAMBDA_PLAUSIBLE = (700, 1600)
VEFF_MAX = 12.0


def verdict(ts, xs, rpms, fitted):
    """PASS/FAIL for one bank: ts seconds, xs bank() views, rpms. Pure."""
    if not xs:
        return "FAIL", "no telemetry"
    fault = [x["fault"] for x in xs if x["fault"]]
    duty_max = max(x["duty"] for x in xs)
    if not fitted:
        if fault and fault[-1] == 2 and duty_max == 0:
            return "PASS", "not fitted: 'no sensor' (fault 2), heater never driven"
        if duty_max:
            return "FAIL", "not fitted but its heater was driven (duty %d %%)" % duty_max
        return "FAIL", "not fitted but no 'no sensor' fault (fault %s)" % (
            fault[-1] if fault else 0)
    if not any(x["cal_ok"] for x in xs):
        return "FAIL", "calibration never OK (UA0 %s, URcal %s)" % (
            xs[-1]["ua0"], xs[-1]["urc"])
    if fault:
        return "FAIL", "fault %d (%s)" % (fault[0], FAULTS[fault[0]]
                                          if fault[0] < len(FAULTS) else "?")
    veff = max(x["veff"] for x in xs)
    if veff > VEFF_MAX + 0.05:
        return "FAIL", "heater Veff %.1f V above %.1f V" % (veff, VEFF_MAX)
    t_run = next((t for t, r in zip(ts, rpms) if r > 0), None)
    if t_run is None:
        return "FAIL", "the engine never ran"
    i_ready = next((i for i, x in enumerate(xs) if x["state"] == "READY"), None)
    if i_ready is None:
        return "FAIL", "never READY (last state %s)" % xs[-1]["state"]
    if ts[i_ready] - t_run > READY_LIMIT_S:
        return "FAIL", "READY after %.0f s (limit %.0f s)" % (
            ts[i_ready] - t_run, READY_LIMIT_S)
    ri = xs[i_ready]["ri"] / 10.0
    if not RI_BAND[0] <= ri <= RI_BAND[1]:
        return "FAIL", "Ri %.1f ohm at READY outside %.1f..%.1f" % (
            ri, RI_BAND[0], RI_BAND[1])
    after = xs[i_ready:]
    frac = sum(x["valid"] for x in after) / len(after)
    if frac < 0.90:
        return "FAIL", "lambda valid only %.0f %% of the time after READY" % (
            100 * frac)
    bad = [x["lambda"] for x in after if x["valid"]
           and not LAMBDA_PLAUSIBLE[0] <= x["lambda"] <= LAMBDA_PLAUSIBLE[1]]
    if bad:
        return "FAIL", "valid lambda %d outside %d..%d" % (
            bad[0], LAMBDA_PLAUSIBLE[0], LAMBDA_PLAUSIBLE[1])
    return "PASS", "READY %.0f s after start, Ri %.1f ohm, valid %.0f %%, Veff max %.1f V" % (
        ts[i_ready] - t_run, ri, 100 * frac, veff)


def selftest() -> int:
    def x(state, **k):
        d = {"state": state, "valid": 0, "fault": 0, "duty": 0, "veff": 0.0,
             "cal_ok": 1, "ri": 60000, "lambda": 0, "ua0": 307, "urc": 187}
        d.update(k)
        return d
    good = ([x("WAIT")] * 5 + [x("PREHEAT", duty=3, veff=2.0)] * 15
            + [x("RAMP", duty=40, veff=9.0)] * 10
            + [x("CLOSED", duty=30, veff=7.5, ri=950)] * 4
            + [x("READY", duty=30, veff=7.5, ri=830, valid=1, lambda_=0)] * 0
            + [dict(x("READY", duty=30, veff=7.5, ri=830, valid=1), **{"lambda": 1010})] * 30)
    ts = [float(i) for i in range(len(good))]
    rpm = [0] * 3 + [900] * (len(good) - 3)
    cases = [
        ("good warm-up", good, True, "PASS"),
        ("no sensor, unfitted", [x("WAIT")] * 5 + [x("FAULT", fault=2)] * 20, False, "PASS"),
        ("no sensor but fitted", [x("WAIT")] * 5 + [x("FAULT", fault=2)] * 20, True, "FAIL"),
        ("latched overheat", good[:40] + [x("FAULT", fault=10)] * 10, True, "FAIL"),
        ("never READY", good[:34], True, "FAIL"),
        ("overdriven heater", [dict(g, veff=12.6) if g["state"] == "RAMP" else g for g in good], True, "FAIL"),
        ("unfitted bank heated", [x("WAIT")] * 5 + [x("PREHEAT", duty=3)] + [x("FAULT", fault=2)] * 5, False, "FAIL"),
        ("implausible lambda", good[:-1] + [dict(good[-1], **{"lambda": 2000})], True, "FAIL"),
        ("calibration never OK", [dict(g, cal_ok=0) for g in good], True, "FAIL"),
    ]
    bad = 0
    for name, xs, fitted, want in cases:
        got, why = verdict(ts[:len(xs)], xs, rpm[:len(xs)], fitted)
        ok = got == want
        bad += not ok
        print("  %-24s %s %s  (%s)" % (name, got, "OK" if ok else "WRONG", why))
    print("SELFTEST %s" % ("PASS" if not bad else "FAIL"))
    return 1 if bad else 0


COLS = ["t", "stage", "rpm", "battDv"] + [
    "%s%d" % (k, b + 1) for b in range(2)
    for k in ("state", "valid", "chip", "pump", "cal_ok", "lambda", "diag",
              "reg1", "mode", "ua", "ur", "ri", "ua0", "urc", "fault",
              "veff", "duty", "ip")]


class Tool:
    def __init__(self, a, sess, allowed):
        self.a, self.s = a, sess
        self.link, self.ini, self.sig, self.ver = MC.connect(
            a.port, a.ini, sess, allowed)
        missing = [f for f in FIELDS if f not in self.ini.scalars
                   and f not in getattr(self.ini, "computed", {})]
        if missing:
            raise SystemExit("this ECU's .ini has no %s - V96 or later is "
                             "needed (ECU %r)" % (missing, self.ver))
        self.fields = FIELDS + [f for f in OPTIONAL if f in self.ini.scalars]
        self.rd = MC.Reader(self.link, self.ini, self.fields)
        self.times = []
        self.f = (sess.dir / "samples.csv").open("w", newline="",
                                                 encoding="utf-8")
        self.w = csv.writer(self.f)
        self.w.writerow(COLS)
        self.t0 = time.monotonic()

    def sample(self, stage):
        for _ in range(3):
            v = self.rd.read()
            if v is not None:
                row = [round(time.monotonic() - self.t0, 3), stage, v["rpm"],
                       v["battDv"]]
                for b in range(2):
                    x = bank(v, b)
                    row += [x[k] for k in ("state", "valid", "chip", "pump",
                                           "cal_ok", "lambda", "diag", "reg1",
                                           "mode", "ua", "ur", "ri", "ua0",
                                           "urc", "fault", "veff", "duty",
                                           "ip")]
                self.w.writerow(row)
                return v
        return None

    def grab(self, stage, secs):
        end = time.monotonic() + secs
        out = []
        while time.monotonic() < end:
            v = self.sample(stage)
            if v is not None:
                out.append(v)
                self.times.append(time.monotonic() - self.t0)
        return out

    def write(self, name, value):
        w, off = const(self.ini.path, name)
        body, err, _ = self.link.request(b"W" + off.to_bytes(2, "big")
                                         + value.to_bytes(w, "big"), 1.0)
        self.s.event("PAGE_WRITE", name=name, value=value, ok=body is not None)
        return body is not None

    def read(self, name):
        w, off = const(self.ini.path, name)
        body, err, _ = self.link.request(b"R" + off.to_bytes(2, "big")
                                         + w.to_bytes(2, "big"), 1.0)
        return int.from_bytes(body, "big") if body and len(body) == w else None

    # ------------------------------------------------------------- --modes
    def modes(self):
        s = self.s
        v = self.sample("start")
        if v is None:
            return ["NO TELEMETRY"], {}
        if v["rpm"] != 0 or v["syncState"] != 0:
            return ["REFUSED: the engine is turning"], {}
        orig = {n: self.read(n) for n in ("lambda1Source", "lambda2Source",
                                          "testValue")}
        s.meta["original_page_values"] = orig
        res = {}
        try:
            self.write("lambda1Source", 1)
            self.write("lambda2Source", 1)
            self.write("testValue", 1500)
            self.grab("cj120 start", 4.0)
            for ch, (name, want) in MODES.items():
                self.link.command(bytes([ord("T"), HCB_TEST_ASIC, ch]))
                time.sleep(0.45)                     # write + verify + settle
                rows = self.grab("mode %s" % name, 0.9)
                time.sleep(0.4)
                per = []
                for b in range(2):
                    xs = [bank(r, b) for r in rows]
                    ur = [x["ur"] for x in xs if x["ur"] != 0xFFFF]
                    per.append({
                        "reg1": sorted({x["reg1"] for x in xs}),
                        "mode_req": sorted({x["mode"] for x in xs}),
                        "ur_median": statistics.median(ur) if ur else None,
                        "ur_samples": len(ur),
                        "ua_median": statistics.median([x["ua"] for x in xs])
                        if xs else None,
                        "diag": sorted({x["diag"] for x in xs}),
                        "duty": max((x["duty"] for x in xs), default=None)})
                res[name] = {"want": want, "banks": per,
                             "refuse": sorted({r["hcbRefuse"] for r in rows})}
                s.say("  %-9s want 0x%02X | chip1 reg1 %s UR %s UA %s DIAG %s"
                      " | chip2 reg1 %s UR %s UA %s DIAG %s" % (
                          name, want,
                          ["0x%02X" % r for r in per[0]["reg1"]],
                          per[0]["ur_median"], per[0]["ua_median"],
                          ["0x%02X" % d for d in per[0]["diag"]],
                          ["0x%02X" % r for r in per[1]["reg1"]],
                          per[1]["ur_median"], per[1]["ua_median"],
                          ["0x%02X" % d for d in per[1]["diag"]]))
        finally:
            self.link.command(b"X")
            for n, val in orig.items():
                if val is not None:
                    self.write(n, val)
        lines = []
        for b in range(2):
            def med(m, k):
                return (res.get(m) or {}).get("banks", [{}] * 2)[b].get(k)
            held = all(res[m]["want"] in res[m]["banks"][b]["reg1"]
                       for m in res)
            ra, cold = med("RA", "ur_median"), med("COLD", "ur_median")
            la = med("LA", "ua_median")
            duty = max((res[m]["banks"][b]["duty"] or 0) for m in res)
            lines.append("CHIP %d: every mode held (read-back) %s" % (
                b + 1, "YES" if held else "NO"))
            lines.append("CHIP %d: RA moves UR: RA=1 %s vs RA=0 %s -> %s" % (
                b + 1, ra, cold, "YES" if (ra is not None and cold is not None
                                          and abs(ra - cold) >= 20) else "NO"))
            lines.append("CHIP %d: LA pump zero UA %s (datasheet 291..322) -> %s"
                         % (b + 1, la, "IN SPEC" if la is not None
                            and 291 <= la <= 322 else "OUT OF SPEC"))
            lines.append("CHIP %d: heater duty during the holds: %s%%" % (
                b + 1, duty))
        lines.append("Page values restored (lambda sources, testValue). "
                     "Nothing burned.")
        return lines, res

    # ------------------------------------------------------ --auto / --vehicle
    def watch(self, secs, stage):
        rows = self.grab(stage, secs)
        if not rows:
            return ["NO TELEMETRY"], {}
        res = {}
        lines = []
        for b in range(2):
            xs = [bank(r, b) for r in rows]
            t_of = {}
            t_run = None
            for i, (r, x) in enumerate(zip(rows, xs)):
                t = i
                if t_run is None and r["rpm"] > 0:
                    t_run = i
                t_of.setdefault(x["state"], i)
            last = xs[-1]
            modes = []
            for x in xs:
                if not modes or modes[-1] != x["mode"]:
                    modes.append(x["mode"])
            dt = (rows and secs / max(1, len(rows))) or 0
            res["bank%d" % (b + 1)] = {
                "states_seen": sorted(t_of, key=t_of.get),
                "first_seen_s": {k: round(v * dt, 2) for k, v in t_of.items()},
                "engine_running_s": None if t_run is None else round(t_run * dt, 2),
                "modes": ["0x%02X" % m for m in modes],
                "ua0": last["ua0"], "urc": last["urc"], "cal_ok": last["cal_ok"],
                "final_state": last["state"],
                "fault": FAULTS[last["fault"]] if last["fault"] < len(FAULTS)
                else last["fault"],
                "valid_fraction": round(sum(x["valid"] for x in xs) / len(xs), 3),
                "lambda_last": last["lambda"], "ri_last": last["ri"] / 10.0,
                "veff_max": max(x["veff"] for x in xs),
            }
            r = res["bank%d" % (b + 1)]
            if stage == "vehicle":
                fitted = (b + 1) in self.a.banks_set
                r["fitted"] = fitted
                r["verdict"], r["why"] = verdict(self.times[-len(rows):], xs,
                                                 [q["rpm"] for q in rows], fitted)
                lines.append("BANK %d %s: %s - %s" % (
                    b + 1, "fitted" if fitted else "not fitted",
                    r["verdict"], r["why"]))
            lines.append("BANK %d: states %s | modes %s | cal UA0 %s URcal %s "
                         "(ok %s) | final %s | fault %s | valid %.0f%% | "
                         "Veff max %.1f V" % (
                             b + 1, "->".join(r["states_seen"]),
                             "->".join(r["modes"]), r["ua0"], r["urc"],
                             r["cal_ok"], r["final_state"], r["fault"],
                             100 * r["valid_fraction"], r["veff_max"]))
        return lines, res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--modes", action="store_true")
    g.add_argument("--auto", action="store_true")
    g.add_argument("--vehicle", action="store_true")
    g.add_argument("--selftest", action="store_true")
    ap.add_argument("--banks", default="1",
                    help="--vehicle: the banks with an LSU fitted, e.g. 1 or 1,2")
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--port", default="auto")
    ap.add_argument("--ini", default=None)
    ap.add_argument("--evidence", default=None)
    ap.add_argument("--i-authorize-cj120-modes", action="store_true",
                    dest="auth")
    ap.add_argument("--enable-in-ram", action="store_true",
                    help="--auto only: set both lambda sources to on-board "
                         "in RAM for the run and restore them (never burned)")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    a.banks_set = {int(x) for x in a.banks.split(",") if x.strip()}
    if a.modes and not a.auth:
        print("REFUSED: --modes holds both CJ120s in six register modes "
              "(engine off, heater off); add --i-authorize-cj120-modes")
        return 2
    kind = "WIDEBAND_" + ("MODES" if a.modes else "AUTO" if a.auto
                          else "VEHICLE")
    # --auto and --vehicle may only READ: 'S','Q','V','O' (no W, no '!')
    allowed = b"SQVORW!" if a.modes else (b"SQVORW" if (a.auto and a.enable_in_ram)
                                          else b"SQVO")
    sess = MC.Session(kind, Path(a.evidence) if a.evidence else None, argv)
    sess.meta["tool_version"] = TOOL_VERSION
    sess.say("HaniCore wideband test %s -> %s" % (TOOL_VERSION, sess.dir))
    lines, res = ["NOT RUN"], {}
    try:
        t = Tool(a, sess, allowed)
        if a.modes:
            lines, res = t.modes()
        elif a.auto and a.enable_in_ram:
            orig = {n: t.read(n) for n in ("lambda1Source", "lambda2Source")}
            sess.meta["original_page_values"] = orig
            try:
                t.write("lambda1Source", 1)
                t.write("lambda2Source", 1)
                lines, res = t.watch(a.seconds, "auto")
            finally:
                for n, val in orig.items():
                    if val is not None:
                        t.write(n, val)
            lines.append("Lambda sources restored %s. Nothing burned." % orig)
        else:
            lines, res = t.watch(a.seconds, "vehicle" if a.vehicle else "auto")
        t.f.close()
    finally:
        sess.meta["result"] = res
        (sess.dir / "result.json").write_text(json.dumps(res, indent=1,
                                                         default=str))
        (sess.dir / "summary.txt").write_text("\n".join(lines) + "\n",
                                              encoding="utf-8")
        sess.say("\n" + "\n".join(lines) + "\n\nEvidence: %s" % sess.dir)
        sess.close()
    if a.vehicle and any(" FAIL - " in ln for ln in lines):
        return 1
    return 0 if lines and not lines[0].startswith(("NO ", "REFUSED")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
