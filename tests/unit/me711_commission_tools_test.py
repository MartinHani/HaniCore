#!/usr/bin/env python3
r"""
me711_commission_tools_test.py - the two ACTIVE vehicle tools, offline.

    py tests\unit\me711_commission_tools_test.py

me711_dbw_vehicle_test.py and me711_trigger_vehicle_test.py against a fake
ECU that speaks the envelope protocol and runs a scripted '!C' / '!K'
procedure, one step per output-channel read. What is proved is the TOOLS'
behaviour: they refuse without authorisation, refuse a turning engine, send
exactly the commands they declare and nothing that writes or burns, follow
the procedure to its published result, report PASS/FAIL with the reason,
abort on Ctrl-C, and leave a complete evidence folder. The firmware side of
the procedures is me711_etb_autocal_proof (linked image).
"""
from __future__ import annotations

import binascii
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_image as PI                 # noqa: E402
import me711_vehicle_capture as VC       # noqa: E402
import me711_commission as MC            # noqa: E402
import me711_dbw_vehicle_test as DBW     # noqa: E402
import me711_trigger_vehicle_test as TRG  # noqa: E402
import me711_heater_drive_test as HTR    # noqa: E402

INI = ROOT / "tunerstudio" / ("hanicore_me711_%s.ini"
                                        % PI.STEM.replace("HaniCore_ME711_", "").lower())
CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += 0 if ok else 1
    print("  [%s] %-64s %s" % ("PASS" if ok else "FAIL", name, detail))


def constants(ini_path):
    txt = ini_path.read_text(encoding="utf-8", errors="replace")
    body = txt.split("[Constants]", 1)[1]
    body = re.split(r"^\[", body, maxsplit=1, flags=re.M)[0]
    out = {}
    for m in re.finditer(r"^\s*(\w+)\s*=\s*(?:scalar|bits)\s*,\s*([US]\d\d)\s*,"
                         r"\s*(\d+)", body, re.M):
        out[m.group(1)] = (m.group(2), int(m.group(3)))
    return out


class FakeECU:
    def __init__(self, ini, mode="pass"):
        self.ini = ini
        self.k = constants(ini.path)
        self.mode = mode
        self.vals = {"rpm": 0, "syncState": 0, "battDv": 128, "cfgValidation": 0,
                     "outputAuthority": 0x3, "safetyInhibits": 0x22, "runOn": 0,
                     "adc01_TPS1": 157, "adc03_TPS2": 863, "adc08_PEDAL1": 150,
                     "adc09_PEDAL2": 75, "dbwState": 0, "dbwFaults": 0,
                     "etbCalStatus": 0, "toothLogState": 0,
                     "trigCfgAngleX10": -20}
        self.page = bytearray(4096)
        for n, v in (("tps1Min", 102), ("tps1Max", 954), ("tps2Min", 919),
                     ("tps2Max", 71), ("dbwKp", 5120), ("dbwKi", 47000),
                     ("dbwKd", 17600), ("cylinders", 4), ("syTeeth", 60),
                     ("syGap", 2), ("trigAngleX10", -20)):
            self.setp(n, v)
        self.ext = bytearray(344 + 120 + 168)
        self.proc = None
        self.step = 0
        self.sent = []
        self.out = b""
        self.interrupt_at = None
        self.reads = 0

    def setp(self, name, v):
        typ, o = self.k[name]
        w = VC.SIZES[typ]
        self.page[o:o + w] = int(v).to_bytes(w, "big", signed=typ[0] == "S")

    def blob(self, off, cnt):
        b = bytearray(self.ini.block)
        for n, v in self.vals.items():
            if n in self.ini.scalars:
                typ, o, *_ = self.ini.scalars[n]
                w = VC.SIZES[typ]
                b[o:o + w] = int(v).to_bytes(w, "big", signed=typ[0] == "S")
        full = bytes(b) + bytes(self.ext)
        return full[off:off + cnt]

    # ------------------------------------------------ the procedures ---
    def advance(self):
        if self.proc is None:
            return
        self.step += 1
        s = self.step
        if self.proc == "cal":
            ph = [1] * 2 + [2] * 6 + [7] * 2 + [3] * 3 + [4] * 6 + [8] * 2 + [5] * 3
            if s <= len(ph):
                p = ph[s - 1]
                self.vals["etbCalStatus"] = 1 | (p << 4)
                self.vals["adc01_TPS1"] = {1: 157, 2: 102, 7: 102, 3: 157,
                                           4: 954, 8: 954, 5: 157}[p]
                self.vals["etbDrive"] = (0x8000 | 500) if p in (2, 4) else 0
                if self.mode == "nomove" and p == 2:
                    # ETB_WHY_NOMOVE_A in ETB_CAL_DRIVE_A (the stop check,
                    # phases 7/8, is no longer entered by the firmware)
                    self.vals["etbCalDetail"] = 3
                    self.vals["etbCalStatus"] = 3 | (5 << 8)
                    self.vals["etbProc"] = self.pkind | (2 << 4)
                    self.proc = None
                if self.mode == "turning" and p == 4:
                    self.vals["etbCalStatus"] = 3 | (1 << 8)
                    self.vals["etbProc"] = self.pkind | (4 << 4)
                    self.proc = None
            else:
                # the firmware chains INSIDE evaluate(): no AUTOCAL PASS is
                # ever published in the middle of a commission run
                self.vals["etbCalStatus"] = (2 if self.pkind != 3
                                             else 1 | (9 << 4))
                self.vals.update({"etbCalRest1": 157, "etbCalA1": 102,
                                  "etbCalB1": 954, "etbCalA2": 919,
                                  "etbCalB2": 71, "etbCalRest2": 863})
                self.setp("tps1Min", 102)
                self.setp("tps1Max", 954)
                self.setp("tpsCorrelation", 1)
                self.setp("tps2Min", 918)       # a changed value, to diff
                self.vals["etbProc"] = self.pkind | 0x100
                if self.pkind == 3:              # commission: chain on
                    self.proc, self.step = "tune", 0
                else:
                    self.proc = None
        elif self.proc == "tune":
            if self.mode == "tunefail" and s == 12:
                self.vals["etbCalStatus"] = 3 | (13 << 8)
                self.vals["etbProc"] = (self.vals.get("etbProc", 0) & 0x100) \
                    | self.pkind | (6 << 4)
                self.proc = None
                return
            if s < 30:
                self.vals["etbCalStatus"] = 1 | ((9 if s < 4 else 6) << 4)
                self.vals["etbTuneCycles"] = max(0, s - 4)
                self.vals["adc01_TPS1"] = 500 + (20 if s % 2 else -20)
                self.vals["etbTuneKp"] = 14000 + s
            else:
                self.vals["etbCalStatus"] = 5 if self.pkind == 3 else 4
                self.vals["etbTuneAmpX10"] = 12
                self.vals["etbTuneTuMs"] = 40
                self.setp("dbwKp", 14854)
                self.setp("dbwKi", 65535)
                self.setp("dbwKd", 27163)
                self.vals["etbCalDetail"] = 0x8002
                self.proc = None
        elif self.proc == "heat":
            # 3 pulses: ON for reads 1..10, 21..30, 41..50 of this test
            on = (s % 20) <= 10 and s <= 50
            self.vals["hcbPulses"] = min(3, s // 20 + (1 if s % 20 > 10 else 0))
            d1 = 0xFF if (on and self.tch == 5) else 0x7F   # 11 vs 01
            self.vals["cj120Diag"] = d1 | (0x7F << 8)
            if s > 60:
                self.vals["hcbState"] = 2
                self.proc = None
        elif self.proc == "k":
            if s < 3:
                return
            if s < 30:
                self.vals.update({"toothLogState": 2 | (1 << 8), "rpm": 180,
                                  "syncState": 3, "toothLogRevs": s - 3,
                                  "toothLogTeeth": (s - 3) * 58})
            else:
                self.vals.update({"toothLogState": 3 | (1 << 8), "rpm": 0,
                                  "syncState": 0,
                                  "safetyInhibits": 0x22})
                self.put_profile()
                self.proc = None

    def put_profile(self, tdc_phys=84.0, lobe_only=None):
        """lobe_only: the ONE compression TDC left with a pair's plugs out
        (once per revolution), plus a small twice-per-rev residue."""
        import math
        off = 358.0
        for b in range(60):
            eng = b * 6 + (off % 6)
            phys = (eng - off) % 360
            if lobe_only is None:
                v = int(1000 + 120 * math.cos(math.radians(2 * (phys - (tdc_phys - 7.5)))))
            else:
                v = int(1000 + 110 * math.cos(math.radians(phys - (lobe_only - 7.5)))
                        + 25 * math.cos(math.radians(2 * (phys - (lobe_only - 7.5)))))
            if b in (58, 59):
                v = 0
            self.ext[344 + 2 * b:344 + 2 * b + 2] = v.to_bytes(2, "big")

    # ------------------------------------------------ the wire ---
    def write(self, req):
        n = (req[0] << 8) | req[1]
        pl = req[2:2 + n]
        self.sent.append(pl)
        self.out = req
        cmd = pl[:1]
        body = b""
        if cmd in (b"S", b"Q"):
            body = self.ini.signature.encode() + b"\0"
        elif cmd == b"V":
            body = b"HaniCore V93 AWT COMMISSION / Bosch ME7.1.1\0"
        elif cmd == b"O":
            self.reads += 1
            if self.interrupt_at and self.reads == self.interrupt_at:
                raise KeyboardInterrupt
            if int.from_bytes(pl[1:3], "big") < 200:
                self.advance()
            body = self.blob(int.from_bytes(pl[1:3], "big"),
                             int.from_bytes(pl[3:5], "big"))
        elif cmd == b"W":
            o = int.from_bytes(pl[1:3], "big")
            self.page[o:o + len(pl) - 3] = pl[3:]
            body = b""
        elif cmd == b"R":
            o, c = int.from_bytes(pl[1:3], "big"), int.from_bytes(pl[3:5], "big")
            body = bytes(self.page[o:o + c])
        elif cmd == b"!":
            if pl == b"!C\x01":
                self.proc, self.step, self.pkind = "cal", 0, 1
                self.vals["etbProc"] = 1
            elif pl == b"!C\x02":
                self.proc, self.step, self.pkind = "tune", 0, 2
                self.vals["etbProc"] = 2
            elif pl == b"!C\x03":
                self.proc, self.step, self.pkind = "cal", 0, 3
                self.vals["etbProc"] = 3
            elif pl == b"!C\x00":
                self.proc = None
                self.vals["etbCalStatus"] = 3 | (10 << 8)
                self.vals["etbProc"] = (self.vals.get("etbProc", 0) & 0x10F) \
                    | 0x200 | (2 << 4)
            elif pl == b"!K\x01":
                if self.vals["rpm"] == 0:
                    self.vals["toothLogState"] = 1 | (1 << 8)
                    if self.mode != "noinhibit":
                        self.vals["safetyInhibits"] |= 0x40
                    self.proc, self.step = "k", 0
            elif pl[:3] == b"!T\x05":
                self.proc, self.step, self.tch = "heat", 0, pl[3]
                self.vals["hcbState"], self.vals["hcbPulses"] = 1, 0
            elif pl == b"!X":
                self.proc = None
                self.vals["hcbState"] = 4
            elif pl == b"!K\x00":
                self.proc = None
                self.vals["toothLogState"] = 5 | (1 << 8)
                self.vals["safetyInhibits"] &= ~0x40
        else:
            return
        blob = b"\0" + body
        self.out += (len(blob).to_bytes(2, "big") + blob
                     + (binascii.crc32(blob) & 0xFFFFFFFF).to_bytes(4, "big"))

    def read(self, n):
        r, self.out = self.out[:n], self.out[n:]
        return r

    def close(self):
        pass


def run(tool, argv, ecu, tmp):
    VC.SerialTransport = lambda port, baud: ecu
    MC.VC.SerialTransport = VC.SerialTransport
    rc = tool.main(argv + ["--port", "FAKE", "--ini", str(INI),
                           "--evidence", str(tmp)])
    dirs = sorted(Path(tmp).iterdir())
    return rc, dirs[-1] if dirs else None


def cmds(ecu):
    return [p for p in ecu.sent if p[:1] == b"!"]


def main() -> int:
    print("=== active vehicle tools, offline - %s ===" % INI.name)
    ini = VC.Ini(INI)
    tmp = Path(tempfile.mkdtemp(prefix="commission_test_"))
    try:
        # ------------------------------------------------------ DBW tool
        e = FakeECU(ini)
        rc = DBW.main(["--autocal", "--port", "FAKE", "--ini", str(INI),
                       "--evidence", str(tmp / "a")])
        check("DBW: --autocal without --i-authorize-throttle-movement refused",
              rc == 2 and not e.sent, "rc %d" % rc)

        e = FakeECU(ini)
        e.vals["rpm"] = 850
        rc, d = run(DBW, ["--autocal", "--i-authorize-throttle-movement"], e,
                    tmp / "b")
        check("DBW: engine turning -> PREFLIGHT FAILED, nothing commanded",
              rc == 1 and not cmds(e)
              and "PREFLIGHT FAILED" in (d / "summary.txt").read_text(), "")

        e = FakeECU(ini)
        rc, d = run(DBW, ["--autocal", "--i-authorize-throttle-movement"], e,
                    tmp / "c")
        s = (d / "summary.txt").read_text()
        check("DBW --autocal: AUTOCAL: PASS, endpoints, 'BURN to keep'",
              rc == 0 and "AUTOCAL: PASS" in s and "BURN" in s.upper()
              and "stored closed/open" in s, "")
        check("DBW --autocal: exactly one '!C\x01'; nothing writes or burns",
              cmds(e) == [b"!C\x01"]
              and not any(p[:1] in (b"W", b"B", b"C") for p in e.sent),
              str(cmds(e)))
        rows = (d / "autocal.csv").read_text().splitlines()
        check("DBW --autocal: CSV logs every phase (>= 20 rows, phases 1..8)",
              len(rows) > 20 and all(("," + str(p) + ",") in "".join(rows)
                                     for p in (1, 2, 7, 3, 4, 8, 5)),
              "%d rows" % len(rows))
        check("DBW --autocal: before/after pages saved, the change listed",
              (d / "before_page.bin").exists() and (d / "after_page.bin").exists()
              and "tps2Min: 919 -> 918" in s, "")
        check("DBW: evidence folder complete",
              all((d / f).exists() for f in ("metadata.json", "events.jsonl",
                                             "frames.jsonl", "console.log")))

        e = FakeECU(ini)
        rc, d = run(DBW, ["--all", "--i-authorize-throttle-movement"], e,
                    tmp / "c2")
        s = (d / "summary.txt").read_text()
        check("DBW --all: one '!C\x03', ETB COMMISSIONING: PASS, both stages",
              rc == 0 and cmds(e) == [b"!C\x03"]
              and "ETB COMMISSIONING: PASS" in s and "stored closed/open" in s
              and "now Kp 14854" in s and "KI LIMITED" in s
              and "BURN" in s.upper(), "")

        e = FakeECU(ini, mode="tunefail")
        rc, d = run(DBW, ["--all", "--i-authorize-throttle-movement"], e,
                    tmp / "c3")
        s = (d / "summary.txt").read_text()
        check("DBW --all, PID fails: ENDPOINTS OK kept, commissioning incomplete",
              rc == 1 and "ENDPOINTS OK, COMMISSIONING INCOMPLETE" in s
              and "reason: OUT OF BAND" in s and "stored closed/open" in s
              and "tps2Min: 919 -> 918" in s and "BURN" in s.upper(),
              s.splitlines()[4][:70] if len(s.splitlines()) > 4 else s)

        e = FakeECU(ini, mode="nomove")
        rc, d = run(DBW, ["--all", "--i-authorize-throttle-movement"], e,
                    tmp / "d")
        s = (d / "summary.txt").read_text()
        check("DBW --all, AutoCal fails: stage + short reason + detail, no change",
              rc == 1 and "ETB COMMISSIONING: FAIL" in s
              and "failed stage: AUTOCAL: DRIVE A" in s
              and "reason: NO MOVE DIR A" in s and "bridge or motor wiring" in s
              and "NOTHING WAS CHANGED" in s, " | ".join(s.splitlines()[4:8])[:300])

        e = FakeECU(ini, mode="turning")
        rc, d = run(DBW, ["--autocal", "--i-authorize-throttle-movement"], e,
                    tmp / "d2")
        s = (d / "summary.txt").read_text()
        check("DBW: ECU-side abort is reported as ECU SAFETY ABORT (RPM > 0)",
              rc == 1 and "reason: RPM > 0" in s and "ECU SAFETY ABORT" in s, "")

        e = FakeECU(ini)
        rc, d = run(DBW, ["--autotune", "--i-authorize-throttle-movement"], e,
                    tmp / "e")
        s = (d / "summary.txt").read_text()
        check("DBW --autotune: PID PASS, stored-before vs now PID, limited Ki",
              rc == 0 and "PID AUTOTUNE: PASS" in s
              and "stored before Kp 5120" in s and "now Kp 14854" in s
              and "KI LIMITED" in s and cmds(e) == [b"!C\x02"], "")

        e = FakeECU(ini)
        e.setp("tps2Min", 500)
        e.setp("tps2Max", 520)
        rc, d = run(DBW, ["--autotune", "--i-authorize-throttle-movement"], e,
                    tmp / "e2")
        s = (d / "summary.txt").read_text()
        check("DBW --autotune without valid endpoints: NOT RUN, NO ENDPOINTS",
              rc == 1 and "reason: NO ENDPOINTS" in s and not cmds(e), "")

        e = FakeECU(ini)
        e.interrupt_at = 12
        rc, d = run(DBW, ["--autocal", "--i-authorize-throttle-movement"], e,
                    tmp / "f")
        s = (d / "summary.txt").read_text()
        check("DBW: Ctrl-C sends ABORT and is reported as OPERATOR ABORT",
              cmds(e) == [b"!C\x01", b"!C\x00"] and "OPERATOR ABORT" in s,
              str(cmds(e)))

        e = FakeECU(ini)
        e.interrupt_at = 3
        rc, d = run(DBW, ["--all", "--i-authorize-throttle-movement"], e,
                    tmp / "f2")
        s = (d / "summary.txt").read_text()
        check("DBW: Ctrl-C during observe ends the run - nothing commanded",
              not [c for c in cmds(e) if c != b"!C\x00"]
              and "STOPPED BY THE OPERATOR" in s, str(cmds(e)))

        # -------------------------------------------------- trigger tool
        e = FakeECU(ini)
        rc, d = run(TRG, ["--yes"], e, tmp / "g")
        s = (d / "summary.txt").read_text()
        check("TRIGGER: full compression test -> RESULT with offset + confidence",
              rc == 0 and "RESULT: compression profile" in s
              and "trigAngleX10 implied" in s and "CONFIDENCE" in s,
              "")
        m = re.search(r"trigAngleX10 implied\s+(-?\d+)", s)
        check("TRIGGER: a profile slowest before TDC 84 deg -> trigger angle ~-84.0",
              m is not None and abs(int(m.group(1)) + 840) <= 60,
              m.group(1) if m else "-")
        check("TRIGGER: sent only '!K\\x01' (arm); nothing writes the page",
              cmds(e) == [b"!K\x01"]
              and not any(p[:1] in (b"W", b"B") for p in e.sent), str(cmds(e)))
        check("TRIGGER: raw profile and decoded CSV saved",
              (d / "profile_raw.bin").exists() and (d / "profile.csv").exists())

        e = FakeECU(ini, mode="noinhibit")
        rc, d = run(TRG, ["--yes"], e, tmp / "h")
        s = (d / "summary.txt").read_text()
        check("TRIGGER: no spark/fuel inhibit reported -> test cancelled",
              rc == 1 and "did not report spark/fuel inhibited" in s
              and b"!K\x00" in cmds(e), "")

        e = FakeECU(ini)
        e.vals["rpm"] = 900
        rc, d = run(TRG, ["--yes"], e, tmp / "i")
        check("TRIGGER: engine turning -> preflight refuses, nothing armed",
              rc == 1 and not cmds(e), "")

        e = FakeECU(ini)
        e.vals["toothLogState"] = 3 | (1 << 8) | 0x4000
        e.vals["toothLogRevs"], e.vals["toothLogTeeth"] = 12, 700
        e.put_profile()
        rc, d = run(TRG, ["--fetch-only"], e, tmp / "j")
        s = (d / "summary.txt").read_text()
        check("TRIGGER: --fetch-only reads a profile restored after a reset",
              rc == 0 and "RESULT: compression profile" in s and not cmds(e), "")
        # plugs 1+4 out: only the 2/3 lobe (TDC at 258 if TDC#1 is at 78)
        for lobe, plugs, want in ((258.0, "1,4", -780), (78.0, "1,4", 1020),
                                  (78.0, "2,3", -780)):
            e = FakeECU(ini)
            e.vals["toothLogState"] = 3 | (1 << 8) | 0x4000
            e.vals["toothLogRevs"], e.vals["toothLogTeeth"] = 12, 700
            e.put_profile(lobe_only=lobe)
            rc, d = run(TRG, ["--fetch-only", "--plugs-out", plugs], e,
                        tmp / ("j_%s_%d" % (plugs.replace(",", ""), lobe)))
            s = (d / "summary.txt").read_text()
            m = re.search(r"-> trigAngleX10 (-?\d+) \(no geometry", s)
            check("TRIGGER --plugs-out %s, lobe TDC %.0f -> trigAngle %.1f"
                  % (plugs, lobe, want / 10.0),
                  rc == 0 and m is not None and abs(int(m.group(1)) - want) <= 30
                  and "PAIR CONFIDENCE: HIGH" in s,
                  m.group(1) if m else s[-200:])
        e = FakeECU(ini)
        e.vals["toothLogState"] = 3 | (1 << 8) | 0x4000
        e.vals["toothLogRevs"], e.vals["toothLogTeeth"] = 12, 700
        e.put_profile()
        rc, d = run(TRG, ["--fetch-only", "--plugs-out", "1,2"], e, tmp / "j_12")
        s = (d / "summary.txt").read_text()
        check("TRIGGER --plugs-out 1,2 (one of each pair): says it cannot decide",
              "NO PAIR DECISION" in s and "both pairs equal" in s, "")
        # -------------------------------------------------- heater tool
        e = FakeECU(ini)
        rc = HTR.main(["--port", "FAKE", "--ini", str(INI),
                       "--evidence", str(tmp / "k0")])
        check("HEATER: without --i-authorize-heater-pulses refused", rc == 2, "")
        e = FakeECU(ini)
        e.vals.update({"cj120Diag": 0x7F7F, "lambdaStatus": 0x0300,
                       "cj120Ident": 0x1A1A})
        before = bytes(e.page)
        rc, d = run(HTR, ["--i-authorize-heater-pulses"], e, tmp / "k")
        s = (d / "summary.txt").read_text()
        check("HEATER: names the candidate that moves chip 1 (ASIC PWM1)",
              rc == 0 and "BANK 1 HEATER GATE: driven by ASIC PWM1" in s,
              s.splitlines()[0])
        check("HEATER: bank 2 reported as not driven by any candidate",
              "BANK 2 HEATER GATE: no candidate" in s, "")
        check("HEATER: all six candidates pulsed, abort sent, page restored",
              sum(1 for p in cmds(e) if p[:3] == b"!T\x05") == 6
              and b"!X" in cmds(e) and bytes(e.page) == before,
              str([p.hex() for p in cmds(e)]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d checks, %d failed" % (CHECKS, FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
