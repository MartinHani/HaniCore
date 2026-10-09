#!/usr/bin/env python3
r"""
me711_heater_drive_test.py - WHICH output drives the LSU heater FET, in one
12-second pass, engine off. For the car (G39 fitted) or the bench (nothing
fitted); the answer is the same.

    py me711_heater_drive_test.py --i-authorize-heater-pulses

Close TunerStudio first. Key ON, engine OFF.

WHY: the Porsche OEM drives its LSU heaters with the peripheral ASIC's own
PWM units (routine 0x88F3BC writes PW1/PW2), the W12 sheet says port bits
P8.7/P7.4, and HaniCore V79..V92 toggled the port bits - the heater never
heated.

HOW: the CJ120 watches each heater FET (DIAHG = gate, DIAHD = drain, through
6.81 kOhm) and reports it in DIAG bits 7..6. The tool enables both CJ120s in
RAM (lambda1Source/lambda2Source = on-board), sets the bench pulse to 1 s,
records a baseline, then pulses each candidate three times (1 s on, 1 s off)
with the V93 bench command '!T 5 ch':
    ch 2  ASIC P8.7 port-image bit     ch 3  ASIC P7.4 port-image bit
    ch 4..7  ASIC PWM0..PWM3 (OEM period, 100 %)
A candidate that reaches a heater gate moves that chip's DIAG heater bits
while it pulses. The page values are restored at the end; nothing is burned.

WITH A SENSOR FITTED a heater that IS driven gets 3 x 1 s of battery
voltage - harmless for a dry sensor on a stopped, cold engine.

EVIDENCE: VEHICLE_EVIDENCE\HEATER_DRIVE_TEST_<UTC>\ - samples.csv,
result.json, summary.txt, events.jsonl, frames.jsonl, console.log.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_commission as MC             # noqa: E402

TOOL_VERSION = "1.0 (V93)"
ALLOWED = b"SQVORW!"        # W: three RAM page fields, restored at the end
FIELDS = ["rpm", "syncState", "battDv", "cfgValidation", "runOn",
          "cj120Diag", "cj120Ident", "lambdaStatus", "asicOutMask",
          "hcbState", "hcbRefuse", "hcbPulses"]
CANDIDATES = {2: "ASIC P8.7 port-image bit", 3: "ASIC P7.4 port-image bit",
              4: "ASIC PWM0", 5: "ASIC PWM1", 6: "ASIC PWM2", 7: "ASIC PWM3"}
HCB_TEST_ASIC = 5


def const(ini_path, name):
    import re
    txt = ini_path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^\s*%s\s*=\s*(?:scalar|bits)\s*,\s*(U08|U16)\s*,\s*(\d+)"
                  % name, txt, re.M)
    return (1 if m.group(1) == "U08" else 2, int(m.group(2)))


class HeaterTest:
    def __init__(self, a, sess):
        self.a, self.s = a, sess
        self.link, self.ini, self.sig, self.ver = MC.connect(
            a.port, a.ini, sess, ALLOWED)
        if "V93" not in self.ver and not a.any_version:
            raise SystemExit("the '!T 5 2..7' candidates exist from V93 on - "
                             "this ECU is %r" % self.ver)
        self.rd = MC.Reader(self.link, self.ini, FIELDS)

    def write(self, name, value):
        w, off = const(self.ini.path, name)
        data = value.to_bytes(w, "big")
        body, err, _ = self.link.request(b"W" + off.to_bytes(2, "big") + data,
                                         1.0)
        self.s.event("PAGE_WRITE", name=name, value=value, ok=body is not None)
        return body is not None

    def read(self, name):
        w, off = const(self.ini.path, name)
        body, err, _ = self.link.request(b"R" + off.to_bytes(2, "big")
                                         + w.to_bytes(2, "big"), 1.0)
        return int.from_bytes(body, "big") if body and len(body) == w else None

    def sample(self):
        for _ in range(3):
            v = self.rd.read()
            if v is not None:
                return v
        return None

    def run(self):
        s = self.s
        v = self.sample()
        if v is None:
            return ["NO TELEMETRY"]
        if v["rpm"] != 0 or v["syncState"] != 0:
            return ["REFUSED: the engine is turning"]
        if (v.get("runOn", 0) >> 8) & 1:
            return ["REFUSED: key off"]
        orig = {n: self.read(n) for n in ("lambda1Source", "lambda2Source",
                                          "testValue")}
        s.meta["original_page_values"] = orig
        rows_all = []
        result = {}
        f = (s.dir / "samples.csv").open("w", newline="", encoding="utf-8")
        w = csv.writer(f)
        w.writerow(["t", "stage", "diag1", "diag2", "hbits1", "hbits2",
                    "ident", "lambdaStatus", "asicOutMask", "hcbState",
                    "hcbRefuse", "hcbPulses"])
        t0 = time.monotonic()

        def grab(stage, secs):
            end = time.monotonic() + secs
            rows = []
            while time.monotonic() < end:
                x = self.sample()
                if x is None:
                    continue
                d1, d2 = x["cj120Diag"] & 0xFF, (x["cj120Diag"] >> 8) & 0xFF
                r = {"stage": stage, "d1": d1, "d2": d2, "h1": (d1 >> 6) & 3,
                     "h2": (d2 >> 6) & 3, "refuse": x["hcbRefuse"],
                     "state": x["hcbState"], "pulses": x["hcbPulses"]}
                rows.append(r)
                w.writerow([round(time.monotonic() - t0, 3), stage, "0x%02X" % d1,
                            "0x%02X" % d2, r["h1"], r["h2"],
                            "0x%04X" % x["cj120Ident"], "0x%04X" % x["lambdaStatus"],
                            "0x%04X" % x["asicOutMask"], x["hcbState"],
                            x["hcbRefuse"], x["hcbPulses"]])
            rows_all.extend(rows)
            return rows

        try:
            self.write("lambda1Source", 1)
            self.write("lambda2Source", 1)
            self.write("testValue", 1000)
            grab("cj120 start", 3.0)
            base = grab("baseline", 3.0)
            x = self.sample() or {}
            chips = (x.get("lambdaStatus", 0) >> 8) & 3
            s.say("CJ120s verified: chip1 %s chip2 %s (ident 0x%04X)"
                  % (bool(chips & 1), bool(chips & 2), x.get("cj120Ident", 0)))
            b1, b2 = {r["h1"] for r in base}, {r["h2"] for r in base}
            s.say("baseline heater bits: chip1 %s chip2 %s" % (sorted(b1),
                                                               sorted(b2)))
            for ch, name in CANDIDATES.items():
                self.link.command(bytes([ord("T"), HCB_TEST_ASIC, ch]))
                rows = grab("ch%d" % ch, 6.5)
                grab("ch%d after" % ch, 1.0)
                m1 = {r["h1"] for r in rows} - b1
                m2 = {r["h2"] for r in rows} - b2
                refuse = sorted({r["refuse"] for r in rows})
                result[ch] = {"candidate": name, "chip1_moved": bool(m1),
                              "chip2_moved": bool(m2),
                              "chip1_bits": sorted({r["h1"] for r in rows}),
                              "chip2_bits": sorted({r["h2"] for r in rows}),
                              "pulses": max((r["pulses"] for r in rows),
                                            default=0),
                              "refuse": refuse}
                s.say("  ch%d %-26s chip1 %s  chip2 %s  pulses %d%s" % (
                    ch, name, "MOVED" if m1 else "-", "MOVED" if m2 else "-",
                    result[ch]["pulses"],
                    ("  REFUSED 0x%X" % refuse[-1]) if refuse and refuse[-1]
                    else ""))
        except KeyboardInterrupt:
            s.say("Ctrl-C")
        finally:
            self.link.command(b"X")                  # abort any pulse
            for n, val in orig.items():
                if val is not None:
                    self.write(n, val)
            f.close()
        s.meta["result"] = result
        (s.dir / "result.json").write_text(json.dumps(result, indent=1))
        lines = []
        for chip, key in ((1, "chip1_moved"), (2, "chip2_moved")):
            who = [result[c]["candidate"] for c in result if result[c][key]]
            if len(who) == 1:
                lines.append("BANK %d HEATER GATE: driven by %s" % (chip, who[0]))
            elif not who:
                lines.append("BANK %d HEATER GATE: no candidate moved the "
                             "CJ120's heater diagnosis" % chip)
            else:
                lines.append("BANK %d HEATER GATE: AMBIGUOUS - %s" % (chip,
                                                                     ", ".join(who)))
        lines.append("Page values restored (lambda sources, testValue). "
                     "Nothing burned.")
        return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", default="auto")
    ap.add_argument("--ini", default=None)
    ap.add_argument("--i-authorize-heater-pulses", action="store_true",
                    dest="auth")
    ap.add_argument("--any-version", action="store_true")
    ap.add_argument("--evidence", default=None)
    a = ap.parse_args(argv)
    if not a.auth:
        print("REFUSED: add --i-authorize-heater-pulses (engine off; each "
              "candidate output is pulsed 3 x 1 s)")
        return 2
    sess = MC.Session("HEATER_DRIVE_TEST",
                      Path(a.evidence) if a.evidence else None, argv)
    sess.meta["tool_version"] = TOOL_VERSION
    sess.say("HaniCore heater drive test %s -> %s" % (TOOL_VERSION, sess.dir))
    try:
        t = HeaterTest(a, sess)
        lines = t.run()
        (sess.dir / "summary.txt").write_text("\n".join(lines) + "\n",
                                              encoding="utf-8")
        sess.say("\n" + "\n".join(lines) + "\n\nEvidence: %s" % sess.dir)
    finally:
        sess.close()
    return 0 if lines and lines[0].startswith("BANK 1 HEATER GATE: driven") else 1


if __name__ == "__main__":
    raise SystemExit(main())
