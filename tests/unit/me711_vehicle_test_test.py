#!/usr/bin/env python3
r"""
me711_vehicle_test_test.py - offline tests of tools\vehicle\me711_vehicle_test.py
against a FAKE ECU (no serial port, no hardware).

    py tests\unit\me711_vehicle_test_test.py

The fake speaks what the real ECU speaks (hcts.c envelope + K-line echo,
the VAG/KWP entry of hckline.c, the extended window with the event ring of
hcevlog711.c) closely enough to drive every code path of the tool:

  K1  OBD path answers a direct probe: KLINE PASS, kline.csv, quality soak
  K2  OBD path dead (echo only): "OBD K-LINE CONNECTION FAILED", the prompt,
      then the DIRECT ECU path PASSES in the same session; both recorded
  K3  the KWP stages are named: no init response / IDENTIFY / GOFAST /
      timeout after the transition
  K4  malformed replies (CRC) are counted, not fatal; port reconnect works
  A1  --autocal: direction A/B "STOP REACHED", AutoCal "NOT A STOP A" is
      reported WITH the numbers (moved / limit / distance) and etb_events.csv
  R1  --runtime: fast rows, monotonic timestamps, medium + slow rows, ring
      events decoded with their reason text, a ring overflow REPORTED (lost
      count), a torn record skipped, a K-line dropout recovered and recorded
  M1  V100 multi-rate: fast > medium > slow in rate, every group's channels /
      windows / measured rate in metadata, medium.csv and slow.csv written
  M2  V100 profiles: --profile reduced polls about a quarter as often and
      leaves the EVENT RING period alone; the profile is in metadata
  M3  V100 metadata: the whole engine configuration is reconstructable from
      the session alone (strategies, trigger, cam, lambda + heater policy,
      DBW calibration, VE/ignition axes)
  M4  V100 snapshots: one at session start; an ecuMs WRAP is not a reboot; a
      real rstBootCount change IS, and snapshots both sides
  M5  V100 on-change: a rare state channel that moves lands in onchange.csv
  M6  V100 a channel this .ini does not declare is reported as unavailable,
      not silently dropped
  M7  V100 --full: phase 2 and phase 3 no longer share fast.csv, so no CSV
      is written against a second header
  M8  V100 the K-line PHYSICAL mode is confirmed and recorded in EVERY
      session, including a --runtime-only one
"""
from __future__ import annotations

import binascii
import csv
import queue
import shutil
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_vehicle_capture as VC     # noqa: E402
import me711_vehicle_test as VT        # noqa: E402

# THE .ini OF THE IMAGE UNDER TEST, from the one place that names an image
# (tools/lib/me711_image.py). It was hardcoded to the V99 name, so a version
# bump left this suite testing the channel map of a stale .ini.
import me711_image as IMG                # noqa: E402
INI = hcpaths.TUNERSTUDIO / ("hanicore_%s.ini" % IMG.STEM.replace(
    "HaniCore_ME711_", "me711_").lower())
CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += 0 if ok else 1
    print("  [%s] %-62s %s" % ("PASS" if ok else "FAIL", name, detail))


def env(payload):
    return VT.envelope(payload)


class FakeEcu:
    """One fake ECU behind one fake KKL. `mode`: 'ok' (answers), 'dead'
    (echo only), 'kwp' (needs the 5-baud entry first), and KWP faults."""

    def __init__(self, mode="ok", kwp_fault=None, crc_every=0):
        ini = VC.Ini(INI)
        self.ini = ini
        self.block = ini.block
        self.mode = mode
        self.kwp_fault = kwp_fault
        self.crc_every = crc_every
        self.n_reply = 0
        self.baud = 115200
        self.ecu_rate = 115200 if mode == "ok" else 57600
        self.rx = bytearray()
        self.kwp_stage = 0
        self.och = bytearray(self.block + VT.EXT_RING + 16 + 90 * 10)
        self.page = bytes(4096)
        self.sig = ini.signature
        self.etb = None              # (sub, reads left)
        self.drop = 0                # replies to drop (dropout)
        self.seq = 0
        self.ms = 1000
        hdr = self.block + VT.EXT_RING
        self.och[hdr:hdr + 2] = b"HE"
        self.och[hdr + 2:hdr + 4] = (1).to_bytes(2, "big")
        self.och[hdr + 6:hdr + 8] = (90).to_bytes(2, "big")
        self.och[hdr + 8:hdr + 10] = (10).to_bytes(2, "big")
        self.set("RPMValue", 0)
        self.set("ecuMs", self.ms)

    # ---- the OCH image ----
    def set(self, name, v):
        typ, off = self.ini.scalars[name][0], self.ini.scalars[name][1]
        w = VC.SIZES[typ]
        self.och[off:off + w] = int(v & ((1 << (8 * w)) - 1)).to_bytes(w, "big")

    def event(self, typ, arg, v1, v2, torn=False):
        base = self.block + VT.EXT_RING
        i = self.seq % 90
        r = base + 16 + i * 10
        seq = 0xFFFF if torn else self.seq
        self.och[r:r + 10] = (seq.to_bytes(2, "big") + self.ms.to_bytes(2, "big")
                              + bytes([typ, arg]) + v1.to_bytes(2, "big")
                              + v2.to_bytes(2, "big"))
        self.seq += 1
        self.och[base + 4:base + 6] = (self.seq & 0xFFFF).to_bytes(2, "big")

    # ---- the port interface the tool uses ----
    def set_baud(self, b):
        self.baud = b

    def reset_input(self):
        self.rx.clear()

    def close(self):
        pass

    def read(self, n, timeout):
        out = bytes(self.rx[:n])
        del self.rx[:n]
        return out

    def five_baud(self, addr):
        self.baud = 10400
        self.rx.clear()
        if self.mode in ("kwp", "ok") and self.kwp_fault != "noinit" \
                and addr == 0x01:
            self.rx += b"\x55\xEF\x8F"
            self.kwp_stage = 1

    def write(self, data: bytes):
        self.rx += data                       # the K-line echo
        if self.mode == "dead":
            return
        if self.kwp_stage and self.baud == 10400:
            self.kwp(data)
            return
        if self.baud != self.ecu_rate:
            if self.mode == "ok":
                self.ecu_rate = self.baud     # the ECU follows the host
            return
        self.ts(data)

    def kwp(self, data):
        if data == b"\x70":
            self.rx += b"\xFE"
            return
        svc = data[3:3 + (data[0] & 0x3F)]

        def reply(d):
            f = bytes([0x80 | len(d), 0xF1, 0x01]) + d
            self.rx += f + bytes([sum(f) & 0xFF])
        if svc[:1] == b"\x81":
            reply(b"\xC1\xEF\x8F")
        elif svc[:1] == b"\xB0":
            if self.kwp_fault == "identify":
                reply(b"\x7F\xB0\x11")
            else:
                reply(b"\xF0" + self.sig.encode())
        elif svc[:1] == b"\xB1":
            if self.kwp_fault == "gofast":
                return
            reply(b"\xF1")
            if self.kwp_fault != "after":
                self.ecu_rate = {1: 10400, 2: 57600, 3: 124800,
                                 4: 115200}[svc[1]]
            else:
                self.ecu_rate = 1        # never answers again
            self.kwp_stage = 0

    def ts(self, data):
        if len(data) < 7:
            return
        n = (data[0] << 8) | data[1]
        p = bytes(data[2:2 + n])
        if self.drop:
            self.drop -= 1
            return
        c = p[:1]
        if c in (b"S", b"Q"):
            body = self.sig.encode() + b"\0"
        elif c == b"V":
            body = IMG.metadata()["version_text"].encode() + b"\0"
        elif c == b"O":
            off = int.from_bytes(p[1:3], "big")
            cnt = int.from_bytes(p[3:5], "big")
            self.tick(off <= 776 < off + cnt)
            body = bytes(self.och[off:off + cnt])
        elif c == b"R":
            off = int.from_bytes(p[1:3], "big")
            cnt = int.from_bytes(p[3:5], "big")
            body = self.page[off:off + cnt]
        elif c == b"!":
            if p[1:2] == b"C":
                self.etb = (p[2], 6)
            body = b""
        else:
            body = b""
        blob = b"\x00" + body
        self.n_reply += 1
        crc = binascii.crc32(blob) & 0xFFFFFFFF
        if self.crc_every and self.n_reply % self.crc_every == 0:
            crc ^= 1
        self.rx += len(blob).to_bytes(2, "big") + blob + crc.to_bytes(4, "big")

    def tick(self, status_read=False):
        self.ms = (self.ms + 20) & 0xFFFF
        self.set("ecuMs", self.ms)
        if self.etb and status_read:      # one procedure step per status read
            sub, left = self.etb
            if left > 3:
                self.set("etbCalStatus", 1 | (2 << 4))      # RUN, DRIVE A
            elif left > 0:
                self.set("etbCalStatus", 1 | (7 << 4))      # RUN, CHECK STOP A
            else:
                if sub in (4, 5):
                    self.set("etbCalStatus", 6)             # STOP REACHED
                    self.set("etbCalA1" if sub == 4 else "etbCalB1",
                             973 if sub == 4 else 72)
                elif sub == 3:
                    self.set("etbCalStatus", 3 | (14 << 8))  # FAIL NOT A STOP A
                    self.set("etbStopMoved", 145)
                    self.set("etbStopLimit", 108)
                    self.set("etbStopDisp", 650)
                else:
                    self.set("etbCalStatus", 2 if sub == 1 else 4)
                self.etb = None
                return
            self.etb = (sub, left - 1)


class Args:
    def __init__(self, out, **kw):
        self.port = "FAKE"
        self.baud = 115200
        self.out = str(out)
        self.ini = None
        self.duration = None
        self.kline = self.autocal = self.runtime = False
        self.direct = False
        self.no_prompt = True
        self.analyze = False
        self.quiet = True
        self.profile = "max"
        self.reduced = False
        for k, v in kw.items():
            setattr(self, k, v)


class Answers:
    """stdin for the tool's prompts; on_get runs before each answer."""

    def __init__(self, answers, on_get=None):
        self.a = list(answers)
        self.on_get = on_get

    def get(self):
        if self.on_get:
            self.on_get()
        return self.a.pop(0) if self.a else ""


def read_csv(p):
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="hc_vt_"))
    try:
        # K1 -------------------------------------------------------------
        print("K1 OBD path answers")
        ecu = FakeEcu("ok")
        out = tmp / "k1"
        rc = VT.run(Args(out, kline=True), open_port=lambda b: ecu,
                    stdin_q=Answers(["s"]))
        summ = (out / "summary.txt").read_text()
        check("K1 rc 0, KLINE PASS on the OBD path", rc == 0
              and "KLINE    PASS     OBD path" in summ, summ.splitlines()[-3:])
        rows = read_csv(out / "kline.csv")
        check("K1 kline.csv has the passive listen + probes",
              any(r["stage"] == "passive listen" for r in rows)
              and any(r["stage"] == "direct probe" for r in rows), len(rows))
        check("K1 the soak measured a read rate", "rows/s" in summ)

        # K2 -------------------------------------------------------------
        print("K2 OBD path dead, then the direct ECU path")
        ecu = FakeEcu("dead")

        # V100: the cable is moved when the operator answers the "connect the
        # KKL" prompt - NOT when they answer the physical-connection question
        # that now precedes it. The fixture fires on_get for every prompt, so
        # the first one must not already connect the ECU or the OBD attempt
        # would succeed and the fallback this case exists to test never runs.
        prompts = []

        def connect_direct():
            prompts.append(1)
            if len(prompts) >= 2:
                ecu.mode = "ok"
        out = tmp / "k2"
        a = Args(out, kline=True, no_prompt=False)
        # V100: the FIRST answer is the physical-connection confirmation
        # ("" = keep OBD); only the SECOND one is the "I moved the KKL"
        # Enter, which is what may make the direct path answer. The tool asks
        # about the cable because V99 inferred it from a flag and then
        # recorded "OBD path PASS" over wiring that had never carried OBD
        #.
        rc = VT.run(a, open_port=lambda b: ecu,
                    stdin_q=Answers(["", "", "s"], on_get=connect_direct))
        con = (out / "console.log").read_text()
        summ = (out / "summary.txt").read_text()
        check("K2 asks which connection is physically in place",
              "Where is the KKL plugged in RIGHT NOW?" in con)
        check("K2 says OBD K-LINE CONNECTION FAILED and asks for the KKL",
              "OBD K-LINE CONNECTION FAILED" in con
              and "Connect the KKL directly to the ECU K-line" in con)
        check("K2 OBD FAIL (stage NO INIT RESPONSE) and DIRECT ECU PASS, one "
              "session", "OBD path: stage NO INIT RESPONSE" in summ
              and "DIRECT ECU path:" in summ and rc == 0, summ.splitlines()[-4:])
        # V100: and the move is RECORDED, with the physical mode it ended in
        import json as _j
        md = _j.loads((out / "metadata.json").read_text())
        ph = md["phases"]["kline"]["physical"]
        check("K2 records the OBD -> DIRECT ECU cable move",
              ph["mode"] == "DIRECT ECU"
              and any(t["from"] == "OBD" and t["to"] == "DIRECT ECU"
                      for t in ph["transitions"]), ph)

        # K3 -------------------------------------------------------------
        print("K3 the KWP stages")
        for fault, want in (("noinit", "NO INIT RESPONSE"),
                            ("identify", "IDENTIFY FAILED"),
                            ("gofast", "GOFAST FAILED"),
                            ("after", "TIMEOUT AFTER TRANSITION")):
            ecu = FakeEcu("kwp", kwp_fault=fault)
            out = tmp / ("k3_" + fault)
            rc = VT.run(Args(out, kline=True), open_port=lambda b, e=ecu: e,
                        stdin_q=Answers([]))
            summ = (out / "summary.txt").read_text()
            check("K3 %-10s -> stage %s" % (fault, want),
                  rc == 2 and ("stage %s" % want) in summ,
                  [l for l in summ.splitlines() if "KLINE" in l][:1])
        ecu = FakeEcu("kwp")
        out = tmp / "k3_ok"
        rc = VT.run(Args(out, kline=True), open_port=lambda b: ecu,
                    stdin_q=Answers(["s"]))
        summ = (out / "summary.txt").read_text()
        check("K3 KWP entry -> GOFAST 115200 -> PASS", rc == 0
              and "KWP 5-baud -> GOFAST 115200" in summ)

        # K4 -------------------------------------------------------------
        print("K4 malformed replies, reconnect")
        ecu = FakeEcu("ok", crc_every=7)
        out = tmp / "k4"
        rc = VT.run(Args(out, kline=True), open_port=lambda b: ecu,
                    stdin_q=Answers(["s"]))
        meta = (out / "metadata.json").read_text()
        import json
        q = json.loads(meta)["phases"]["kline"]["quality"]
        check("K4 CRC errors counted in the soak, not fatal",
              q["soak"]["crc_errors"] >= 10 and rc == 0, q["soak"])
        check("K4 port reconnect OK", q["reconnect"]["ok"], q["reconnect"])

        # A1 -------------------------------------------------------------
        print("A1 --autocal")
        ecu = FakeEcu("ok")
        out = tmp / "a1"
        rc = VT.run(Args(out, autocal=True), open_port=lambda b: ecu,
                    stdin_q=Answers([]))
        summ = (out / "summary.txt").read_text()
        check("A1 direction A and B: POSITION CAPTURED",
              summ.count("POSITION CAPTURED") >= 2, summ.count("POSITION CAPTURED"))
        check("A1 AutoCal NOT A STOP A explained with the numbers",
              "NOT A STOP A" in summ and "moved TPS1 145 counts, limit 108"
              in summ and "legacy inferred-stop refusal" in summ
              and "SPRING EQUILIBRIUM" not in summ)
        ev = read_csv(out / "etb_events.csv")
        check("A1 etb_events.csv: legacy phase explicitly identified, results retained",
              any("LEGACY STOP CHECK A" in r["phase"] for r in ev)
              and any(r["event"].startswith("RESULT") for r in ev), len(ev))

        # R1 -------------------------------------------------------------
        print("R1 --runtime")
        ecu = FakeEcu("ok")
        ecu.set("RPMValue", 850)
        ecu.set("engineFlags", 1)
        for i in range(3):                 # history before the session
            ecu.event(6, 2, 850, 135)
        out = tmp / "r1"

        def inject():
            import time
            time.sleep(0.4)
            ecu.event(2, 3, 180, (2 << 8) | 0)       # crank sync
            ecu.event(8, 0, 1600, 8)                 # fuel cut: protection
            ecu.event(16, 0, 1600, 2)                # limp: throttle fault
            ecu.event(14, 3, 1500, 64)               # DBW FAULT off target
            ecu.event(9, 0, 3000, 1, torn=True)      # torn record
            time.sleep(0.3)
            for _ in range(120):                     # overflow the ring
                ecu.event(10, 0, 4000, 7)
            # V100: eight dropped replies - a fast read gives up after two
            # attempts on its FIRST window and the recorder reconnects after
            # three consecutive failures, so six is the minimum and eight has
            # margin. V99 used twelve, which spent ~5 s in request timeouts
            # and made the rest of the case depend on when they landed.
            ecu.drop = 8
            ecu.set("cfgWarnings", 0x0040)           # an ON_CHANGE channel
        th = threading.Thread(target=inject)
        th.start()
        rc = VT.run(Args(out, runtime=True, duration=4.0),
                    open_port=lambda b: ecu, stdin_q=Answers([]))
        th.join()
        fast = read_csv(out / "fast.csv")
        ts = [float(r["t"]) for r in fast]
        check("R1 fast rows written, timestamps monotonic",
              len(fast) > 20 and all(b >= a for a, b in zip(ts, ts[1:])),
              "%d rows" % len(fast))
        med, slow = read_csv(out / "medium.csv"), read_csv(out / "slow.csv")
        check("R1 medium and slow rows written", len(med) >= 2
              and len(slow) >= 2, "medium %d, slow %d" % (len(med), len(slow)))
        evs = read_csv(out / "events.csv")
        texts = " | ".join(r["text"] for r in evs)
        check("R1 ring events decoded with reasons (limp, DBW fault, sync)",
              "THROTTLE FAULT rev limit" in texts
              and "OFF TARGET TOO LONG" in texts and "CRANK ACQUIRED" in texts,
              len(evs))
        con = (out / "console.log").read_text()
        check("R1 ring overflow REPORTED with a lost count",
              "RING OVERFLOW" in con and "records lost" in con)
        meta = json.loads((out / "metadata.json").read_text())
        rt = meta["phases"]["runtime"]
        check("R1 torn record skipped and counted", rt.get("ring_torn", 0) >= 1,
              rt.get("ring_torn"))
        check("R1 K-line dropout recovered and recorded",
              rt["drops"] >= 1 and rt["reconnects"] >= 1
              and "KLINE: RECONNECTED" in con,
              (rt["drops"], rt["reconnects"]))
        check("R1 ring split by subject: trigger / injection / etb / lambda / "
              "faults", all((out / n).exists() for n in (
                  "trigger_events.csv", "etb_ring_events.csv", "faults.csv")))

        # M1 -------------------------------------------------------------
        print("M1 V100 multi-rate groups")
        g = rt["groups"]
        check("M1 fast > medium > slow in measured rate",
              g["fast"]["rows_per_s"] > g["medium"]["rows_per_s"]
              > g["slow"]["rows_per_s"],
              {n: g[n]["rows_per_s"] for n in g})
        check("M1 every group reports channels, windows, bytes and rtt",
              all(g[n]["exchanges_per_row"] >= 1 and g[n]["bytes_per_row"] > 0
                  and g[n]["channels"] for n in ("fast", "medium", "slow")),
              {n: (g[n]["channels"], g[n]["exchanges_per_row"],
                   g[n]["bytes_per_row"]) for n in g})
        check("M1 SLOW is the WHOLE block, so no channel is unrecorded",
              g["slow"]["windows"] == [[0, ecu.block]]
              and g["slow"]["channels"] == "whole block", g["slow"]["windows"])
        check("M1 FAST carries the scheduler, trigger, masks, cuts and ETB "
              "together on one row",
              all(k in fast[0] for k in (
                  "schedulerExecuted", "schedulerLate", "schedulerMissed",
                  "schedulerMaxLatency", "syncState", "toothCorrections",
                  "camPhaseCorrections", "ignOnMask", "injOnMask",
                  "schedOverdwell", "sparkSkips", "veValue", "engLoad",
                  "etbTarget", "etbActual", "dbwDutyX10", "dbwFaults",
                  "fuelCut", "limpCut", "VBatt")),
              [k for k in ("schedulerLate", "ignOnMask", "limpCut", "VBatt")
               if k not in fast[0]])
        check("M1 MEDIUM carries the lambda chain, corrections and raw ADCs",
              all(k in med[0] for k in (
                  "lambdaValue", "lamWhy", "lamFault", "lam1RiX10",
                  "lam1IpUa", "lamVeff", "heaterDuty", "stftBank1",
                  "warmupEnrich", "fuelCorrection", "adc02_IPV",
                  "coolant", "intake", "knockState", "vvt1State")),
              [k for k in ("lam1RiX10", "lamVeff", "adc02_IPV")
               if k not in med[0]])

        # M2 -------------------------------------------------------------
        print("M2 V100 --profile reduced")
        ecu2 = FakeEcu("ok")
        ecu2.set("RPMValue", 850)
        ecu2.set("engineFlags", 1)
        out2 = tmp / "m2"
        VT.run(Args(out2, runtime=True, duration=2.0, profile="reduced"),
               open_port=lambda b: ecu2, stdin_q=Answers([]))
        m2 = json.loads((out2 / "metadata.json").read_text())
        r2 = m2["phases"]["runtime"]
        check("M2 --reduced is the operator's shorthand for --profile reduced",
              VT.parse(["--port", "COM2", "--runtime", "--reduced"]).profile
              == "reduced"
              and VT.parse(["--port", "COM2", "--full"]).profile == "max")
        check("M2 the profile is recorded in metadata",
              m2["logging_profile"] == "reduced"
              and r2["profile"] == "reduced", m2["logging_profile"])
        check("M2 reduced polls about a quarter as often",
              0 < r2["groups"]["fast"]["rows_per_s"] <= 3.0
              and r2["rates_configured_s"]["fast"] == 0.4,
              r2["groups"]["fast"]["rows_per_s"])
        check("M2 the EVENT RING period is NOT reduced",
              r2["rates_configured_s"]["ring"]
              == rt["rates_configured_s"]["ring"] == 0.2,
              r2["rates_configured_s"])

        # M3 -------------------------------------------------------------
        print("M3 V100 the configuration is in the session")
        cfg = meta["engine_config"]
        want = ("firingOrder", "injStrategy", "ignStrategy", "syncMode",
                "camPhaseMode", "camPhaseLevel", "cam1Pattern", "trigAngleX10",
                "syTeeth", "syGap", "loadSource", "lambda1Source",
                "lambda2Source", "lambdaHeatPolicy", "dbwEnable", "dbwKp",
                "dbwDevX10", "dbwDevMs", "dbwAutocalDuty", "tps1Min",
                "tps1Max", "etbLimpRpm", "injFlowCcMin", "revLimit",
                "fuelLoadAx", "fuelRpmAx", "ignLoadAx", "ignRpmAx")
        check("M3 every configuration fact needed to read the log back",
              all(k in cfg for k in want), [k for k in want if k not in cfg])
        check("M3 the VE axes are the real 16-bin arrays",
              len(cfg["fuelLoadAx"]) == 16 and len(cfg["fuelRpmAx"]) == 16,
              (len(cfg.get("fuelLoadAx", [])), len(cfg.get("fuelRpmAx", []))))
        check("M3 a bits field carries BOTH its label and its raw index",
              "_loadSource" in cfg and isinstance(cfg["loadSource"], str),
              (cfg.get("loadSource"), cfg.get("_loadSource")))
        check("M3 the logging rates and the K-line mode are in metadata too",
              meta["rates_configured_s"]["fast"] == 0.0
              and meta["kline_physical"]["mode"] in ("OBD", "DIRECT ECU"),
              meta.get("kline_physical"))

        # M4 -------------------------------------------------------------
        print("M4 V100 snapshots, and a wrap is not a reboot")
        snaps = read_csv(out / "snapshots.csv")
        check("M4 a snapshot at session start, with its reason",
              any(r["reason"] == "session start" for r in snaps), len(snaps))
        check("M4 the whole block is in the snapshot row",
              snaps and "rstBootCount" in snaps[0] and "nvmGeneration"
              in snaps[0] and "lam1RiX10" in snaps[0])
        check("M4 an ecuMs WRAP is not reported as a reboot",
              rt.get("uptime_wraps", 0) >= 1 and rt["reboots"] == 0,
              (rt.get("uptime_wraps"), rt["reboots"]))
        check("M4 a reconnect is snapshotted too (it may be a power cycle)",
              any(r["reason"] == "reconnect" for r in snaps),
              [r["reason"] for r in snaps])
        # a REAL reboot, on its own ECU so nothing else can absorb it
        ecu5 = FakeEcu("ok")
        ecu5.set("RPMValue", 850)
        ecu5.set("engineFlags", 1)
        out5 = tmp / "m4b"

        def reboot():
            import time
            time.sleep(0.6)
            ecu5.set("rstBootCount", 7)
        th5 = threading.Thread(target=reboot)
        th5.start()
        VT.run(Args(out5, runtime=True, duration=3.0),
               open_port=lambda b: ecu5, stdin_q=Answers([]))
        th5.join()
        r5 = json.loads((out5 / "metadata.json").read_text())["phases"]["runtime"]
        s5 = read_csv(out5 / "snapshots.csv")
        check("M4 a real rstBootCount change IS a reboot, and is snapshotted",
              r5["reboots"] >= 1
              and any(r["reason"] == "reboot" for r in s5)
              and "ECU REBOOTED" in (out5 / "console.log").read_text(),
              (r5["reboots"], [r["reason"] for r in s5]))

        # M5 -------------------------------------------------------------
        print("M5 V100 on-change capture")
        oc = read_csv(out / "onchange.csv")
        check("M5 a rare state channel that moved is in onchange.csv",
              any(r["channel"] == "cfgWarnings" and r["to"] == "64"
                  for r in oc) and rt["onchange"] >= 1,
              [(r["channel"], r["from"], r["to"]) for r in oc][:6])

        # M6 -------------------------------------------------------------
        print("M6 V100 an undeclared channel is reported, not dropped")
        ini = VC.Ini(INI)
        w, missing = VT.windows(ini, ["rpm", "notAChannelAtAll", "veValue"],
                                ini.block)
        check("M6 windows() names what the .ini does not declare",
              missing == ["notAChannelAtAll"] and w, (w, missing))
        check("M6 every declared FAST/MEDIUM channel exists in this .ini",
              not VT.windows(ini, VT.GROUPS["fast"], ini.block)[1]
              and not VT.windows(ini, VT.GROUPS["medium"], ini.block)[1],
              (VT.windows(ini, VT.GROUPS["fast"], ini.block)[1],
               VT.windows(ini, VT.GROUPS["medium"], ini.block)[1]))

        # M7 -------------------------------------------------------------
        print("M7 V100 --full: phase 2 and phase 3 do not share fast.csv")
        ecu3 = FakeEcu("ok")
        out3 = tmp / "m7"
        VT.run(Args(out3, autocal=True, runtime=True, duration=1.0),
               open_port=lambda b: ecu3, stdin_q=Answers([]))
        m3 = json.loads((out3 / "metadata.json").read_text())
        f3 = read_csv(out3 / "fast.csv")
        a3 = read_csv(out3 / "autocal.csv")
        check("M7 autocal.csv holds phase 2, fast.csv holds phase 3",
              a3 and f3 and "test" in a3[0] and "test" not in f3[0]
              and "wall" in f3[0], (list(a3[0])[:3], list(f3[0])[:3]))
        check("M7 no CSV was written against a second header",
              "csv_header_conflict" not in m3,
              m3.get("csv_header_conflict"))
        check("M7 every fast row has the same number of columns as the header",
              all(None not in r.values() for r in f3), len(f3))

        # M8 -------------------------------------------------------------
        print("M8 V100 the physical K-line mode in a --runtime-only session")
        con = (out / "console.log").read_text()
        check("M8 the physical mode is stated even without phase 1",
              "K-LINE PHYSICAL:" in con
              and meta["kline_physical"]["software_path_attempted"]
              in ("OBD", "DIRECT ECU"), meta["kline_physical"])
        ecu4 = FakeEcu("ok")
        out4 = tmp / "m8"
        # the remembered mode is the DEFAULT the question offers; 'd' takes
        # the other one, whichever that is in this evidence tree
        remembered = (tmp / VT.Kline.STATE).read_text(encoding="utf-8").strip()
        other = "OBD" if remembered == "DIRECT ECU" else "DIRECT ECU"
        VT.run(Args(out4, runtime=True, duration=0.5, no_prompt=False),
               open_port=lambda b: ecu4, stdin_q=Answers(["d"]))
        m4 = json.loads((out4 / "metadata.json").read_text())
        check("M8 the operator's answer overrides the remembered mode, is "
              "CONFIRMED and the change is recorded as a transition",
              m4["kline_physical"]["mode"] == other
              and m4["kline_physical"]["confirmed"]
              and any(t["from"] == remembered and t["to"] == other
                      for t in m4["kline_physical"]["transitions"]),
              (remembered, m4["kline_physical"]))
        check("M8 and it is REMEMBERED for the next session in this tree",
              (tmp / VT.Kline.STATE).read_text(encoding="utf-8").strip()
              == other)

        # M9 -------------------------------------------------------------
        # The one check neither tool can make on its own: a session this
        # recorder really wrote must be readable by the real analyser.
        print("M9 V100 the recorder's own output goes through the analyser")
        import me711_log_analyze as LA
        rc = LA.main([str(out)])
        an = json.loads((out / "analysis.json").read_text())
        S = an.get("subjects") or {}
        check("M9 the analyser reads a real multi-rate session",
              rc == 0 and an["rows"] > 20
              and S["logging"]["groups"]["fast"]["rows_per_s"] > 0
              and S["logging"]["groups"]["slow"]["channels"] == "whole block",
              (an["rows"], (S.get("logging") or {}).get("profile")))
        check("M9 it reads the configuration, the K-line mode and the "
              "scheduler out of that session",
              S["config"]["cylinders"] is not None
              and S["kline"]["physical_mode"] in ("OBD", "DIRECT ECU")
              and "scheduler" in S, list(S))
        check("M9 --compare runs over two recorder-written sessions",
              LA.compare([str(out), str(out2)], out=str(tmp)) == 0
              and (tmp / "scheduler_compare.md").exists())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d checks, %d failed" % (CHECKS, FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
