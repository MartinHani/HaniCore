#!/usr/bin/env python3
r"""
me711_vehicle_capture.py - the FIRST-VEHICLE capture: one command, follow the
prompts, keep the evidence.

    py tools\vehicle\me711_vehicle_capture.py                 (KKL on COM3, 57600)
    py tools\vehicle\me711_vehicle_capture.py --port COM4
    py tools\vehicle\me711_vehicle_capture.py --auto --steps baseline,session  (no prompts)
    py tools\vehicle\me711_vehicle_capture.py --no-pedal     (skip the pedal steps)

V1.2 (V92): THE ENGINE PART IS ONE OBSERVED SESSION, NOT A SCRIPT. The car
showed (2026-09-27) that a keyed vehicle does not follow a bench sequence:
the engine starts while the tool is still saying "stop cranking", and the
operator stops it with the KEY, so "leave ignition ON" is impossible. The
session step classifies every sample from what the ECU publishes -

    OFFLINE      no answer (ignition off, or run-on over)
    STOPPED      key on, rpm 0
    CRANKING     0 < rpm < 400 and not coming down from RUNNING
    RUNNING      rpm >= 400 for two samples
    RUNDOWN      was RUNNING, rpm falling below 400
    KEY_OFF      the ECU published KL15 off (run-on)

- and numbers the start ATTEMPTS: STARTED, NO_START, STALL (ran, stopped with
the key still on) or STOPPED_BY_KEY. Crank, stall, key off, key on again and
reconnect can happen in any order and any number of times; ENTER ends it.
Counter deltas are summed ACROSS ECU resets (V1.1 reported last - first,
which read 0 over a key cycle). When a tooth-profile test ('!K', started
from TunerStudio) completes, its 60 bins are read from the extended window
and the slowest crank angle is reported.

WHAT IT IS. An OBSERVATION tool. It speaks the HaniCore runtime protocol that
TunerStudio speaks (hcts.c: the TS envelope - u16 length, payload, CRC32 - over
the KKL, K-line echo stripped) and it sends ONLY these read-only commands:

    S / Q   signature              (layout id is in it)
    V       version text           (build identity)
    O       output-channel window  ("O%2o%2c" - offset, count)
    R       calibration page read  (once, at connect, for the evidence folder)

ALLOWED_CMDS enforces that in code: there is no path in this file that can
write the page, Burn, or start a bench actuator test. Every stimulus comes
from the operator's own hands (pedal, key, starter).

DO NOT RUN TUNERSTUDIO ON THE SAME COM PORT AT THE SAME TIME. Close it first;
open it again when the capture has finished.

SAMPLING (bandwidth-aware; 57600 baud is ~5.7 kB/s and every request is also
echoed back by the K-line):

    FAST  O[0,430)    identity/health, ASIC counters, all sensors, trigger,
                      scheduler, fuel/spark, DBW, pump, relay      every cycle
    AUX   O[724,end)  lambda/CJ120/heaters, run-on, output masks,
                      preset words, ETB calibration, overdwell,
                      control CLT (V90/V91)                       every cycle
    FULL  O[0,end)    everything incl. reset forensics, NVM, pins   every 2 s
    end = the .ini's ochBlockSize (V89 776, V90 780, V91 784): DERIVED, never
    typed - V1.0 hard-coded 764 and so never read anything the block grew by.
    -> about 10 fast samples per second.

The channel map, types and scaling come from the generated TunerStudio .ini
that matches the ECU's signature (auto-selected; --ini to override), so this
tool never re-states an offset by hand. Engineering value = (raw + translate)
x scale - TunerStudio's own order.

SESSION FOLDER (flushed continuously; Ctrl+C and power loss keep what was
written):  <raw evidence folder>\<UTC>\

    metadata.json      identity, ini, port, tool git commit, step timestamps
    frames.jsonl       every request: command, window, round trip, raw hex, error
    decoded.csv        one row per FAST sample: every channel in FAST+AUX,
                       engineering units; EMPTY cell = never received (not 0)
    full.csv           one row per FULL read, every scalar channel
    events.jsonl       operator markers and detected transitions
    page.bin           the calibration page as read at connect
    console.log        everything printed
    summary.txt        measured extrema/events per step (no interpretation)

NOT PHYSICALLY VERIFIED BY THIS TOOL: it reports what the ECU publishes.
"""
from __future__ import annotations

import argparse
import binascii
import csv
import datetime as dt
import hashlib
import json
import math
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TS_DIR = ROOT / "tunerstudio"
TOOL_VERSION = "1.9 (fast block 1136..1223 every row, block tail in AUX)"
RUN_RPM = 400              # at or above for two samples = RUNNING
TL_EXT_OFF = 344           # the tooth profile follows the 344-byte LF record
TL_BINS = 60
BH_EXT_OFF = TL_EXT_OFF + 2 * TL_BINS   # V93: the boot history after it
BH_BYTES, BH_HDR, BH_REC, BH_N = 168, 8, 10, 16
RO_NAMES = {0: "RUN", 1: "HOLD", 2: "RELEASED", 3: "TIMEOUT", 4: "OFF",
            5: "BOOTED-IN-KEYOFF", 255: "unknown"}
WEAK_BATT_V = 7.5          # a starter that stalls the crank below this = battery

ALLOWED_CMDS = frozenset(b"SQVOR")
FAST = (0, 430)
AUX_START = 724      # AUX runs from here to FAST2_START (or the block end)
# V1.5: THE SECOND FAST WINDOW - the DBW step's terms, the sequential state,
# the injection width, the fuel per cycle and the transient film (OCH 950..
# the end of the block). A tip-in is a causal chain - pedal -> throttle
# target/actual -> air -> transient share -> pulse -> lambda - and every link
# must be sampled on the SAME row, not one AUX slice in three.
FAST2_START = 950
# V1.7: THE OCH2 REGION (1024.. the block end: knock per cylinder, VVT) is
# NOT fast - read every row it cost 108 bytes a cycle. Knock counts and
# latched faults hold their value, so it is the LAST AUX slice instead and
# FAST2 ends at the OCH1 region's end.
OCH2_START = 1024
# V1.6: LAMBDA ON EVERY ROW - lambda1X1000, lambda2X1000 and lambdaStatus
# (OCH 734..739, inside AUX) are the last link of that chain; one AUX slice
# in three left them up to two cycles stale beside a fresh pulse width. Six
# bytes, one more request per cycle.
LAM_FAST = (734, 6)
# V1.8: THE V98 FAST BLOCK (hcengctl711.c hc_ec_publish, OCH 1136.. the
# block end): rpm, MAP, TPS, pedal, CLT, IAT, battery, fuel load, measured
# and target lambda, closed-loop trims, pulse width, VE, timing, flags, the
# engine-control state - the tuning core, contiguous, read EVERY row. The
# OCH2 AUX slice now stops where it starts.
FAST3_START = 1136
# V1.9: the fast block is 88 bytes (hc_ec_publish). Until V1.9 this window
# ran to the end of the block, so every channel added after it (ETB
# commissioning numbers, runtime health, ...) was read on EVERY row: 516
# bytes at block 1652 and a 107 ms cycle. The tail is AUX now.
FAST3_END = 1224


                     # V1.3: AUX in rotating slices - V93's block (864)
                     # needed halves to keep a FAST+AUX cycle under 100 ms;
                     # V97's 950-byte block needs thirds (halves = 101 ms);
                     # V1.7: slices 0..2 = 724..950, slice 3 = OCH2 (1024..)
AUX1_SLICES = 3
TAIL_SLICES = 3      # V1.9: slices 4..6 = FAST3_END.. the block end
AUX_SPLIT = AUX1_SLICES + 1 + TAIL_SLICES


def aux_window(ini, part=None):
    """(offset, count) of the AUX read - to the END of this build's block.
    part 0..AUX_SPLIT-1 selects one slice (read on alternate cycles);
    None = the whole window."""
    n = max(0, min(ini.block, FAST2_START) - AUX_START)
    if part is not None and part > AUX1_SLICES:     # V1.9: the block tail
        k, tail = part - AUX1_SLICES - 1, max(0, ini.block - FAST3_END)
        per = -(-tail // TAIL_SLICES)
        per += per & 1
        a = FAST3_END + k * per
        return (a, max(0, min(per, ini.block - a)))
    if part == AUX1_SLICES:             # V1.7: the OCH2 region (V1.8: to
        end = min(ini.block, FAST3_START)   # the fast block)
        return (OCH2_START, max(0, end - OCH2_START))
    if part is None or n == 0:
        return (AUX_START, n)
    per = -(-n // AUX1_SLICES)
    per += per & 1                      # whole U16 channels per slice
    a = AUX_START + part * per
    return (a, max(0, min(per, min(ini.block, FAST2_START) - a)))


def lam_window(ini):
    """(offset, count) of the lambda window - (734, 0) on a build whose
    block does not reach it."""
    return (LAM_FAST[0], LAM_FAST[1] if ini.block >= sum(LAM_FAST) else 0)


def fast2_window(ini):
    """(offset, count) of the second FAST window - (FAST2_START, 0) on a
    build whose block ends before it."""
    return (FAST2_START, max(0, min(ini.block, OCH2_START) - FAST2_START))


def fast3_window(ini):
    """(offset, count) of the V98 fast block - (FAST3_START, 0) on a build
    whose block ends before it."""
    return (FAST3_START, max(0, min(ini.block, FAST3_END) - FAST3_START))
FULL_PERIOD_S = 2.0
PROBE_PERIOD_S = 1.0
OFFLINE_AFTER_FAILS = 3

SIZES = {"U08": 1, "S08": 1, "U16": 2, "S16": 2, "U32": 4, "S32": 4}


def utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# =============================================================== the .ini ===
class Ini:
    """Output channels of one generated HaniCore .ini."""

    def __init__(self, path: Path):
        self.path = path
        txt = path.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'^\s*signature\s*=\s*"([^"]+)"', txt, re.M)
        self.signature = m.group(1) if m else ""
        body = txt.split("[OutputChannels]", 1)[1]
        body = re.split(r"^\[", body, maxsplit=1, flags=re.M)[0]
        self.block = int(re.search(r"^\s*ochBlockSize\s*=\s*(\d+)",
                                   body, re.M).group(1))
        self.scalars = {}           # name -> (type, off, units, scale, translate)
        for m in re.finditer(
                r'^\s*(\w+)\s*=\s*scalar\s*,\s*([US]\d\d)\s*,\s*(\d+)\s*,'
                r'\s*"([^"]*)"\s*,\s*([-+\d.eE]+)\s*,\s*([-+\d.eE]+)', body, re.M):
            self.scalars[m.group(1)] = (m.group(2), int(m.group(3)), m.group(4),
                                        float(m.group(5)), float(m.group(6)))
        self.computed = {}          # name -> python expression
        for m in re.finditer(r"^\s*(\w+)\s*=\s*\{(.*)\}", body, re.M):
            self.computed[m.group(1)] = self._py(m.group(2).strip())
        self.lists = {}
        pc = txt.split("[PcVariables]", 1)
        if len(pc) == 2:
            pcb = re.split(r"^\[", pc[1], maxsplit=1, flags=re.M)[0]
            for m in re.finditer(r'^\s*(\w+)\s*=\s*bits\s*,[^,]+,\s*\[[^\]]*\]\s*,(.*)$',
                                 pcb, re.M):
                self.lists[m.group(1)] = re.findall(r'"([^"]*)"', m.group(2))
        self.order = sorted(self.scalars, key=lambda n: self.scalars[n][1])

    @staticmethod
    def _py(expr: str) -> str:
        e = expr.replace("&&", " and ").replace("||", " or ")
        e = re.sub(r"!(?!=)", " not ", e)
        return e

    def in_window(self, off, cnt):
        return [n for n in self.order
                if off <= self.scalars[n][1]
                and self.scalars[n][1] + SIZES[self.scalars[n][0]] <= off + cnt]

    def decode(self, blob: bytes, off: int) -> dict:
        out = {}
        for n in self.in_window(off, len(blob)):
            typ, o, _u, scale, tr = self.scalars[n]
            w = SIZES[typ]
            raw = int.from_bytes(blob[o - off:o - off + w], "big",
                                 signed=typ[0] == "S")
            out[n] = raw
        return out

    def eng(self, name, raw):
        typ, _o, _u, scale, tr = self.scalars[name]
        if scale == 1.0 and tr == 0.0:
            return raw
        return round((raw + tr) * scale, 4)

    def evaluate(self, raw: dict) -> dict:
        out = {}
        env = dict(raw)
        for n, e in self.computed.items():
            try:
                v = eval(e, {"__builtins__": {}}, env)   # expressions from our own .ini
                if isinstance(v, bool):
                    v = int(v)
                if isinstance(v, (int, float)) and not (isinstance(v, float)
                                                        and math.isnan(v)):
                    out[n] = v
                    env[n] = v
            except Exception:
                pass
        return out


# V1.1: THE CONFIGURATION THE CAR RAN WITH, decoded from page.bin through the
# .ini's own [Constants] - the first AWT visit's page held displacementCc 0 and
# nobody could see it until the page was decoded by hand afterwards.
PAGE_FIELDS = (
    "enginePreset", "cylinders", "displacementCc", "trigSource", "syncMode",
    "trigAngleX10", "trigOffsetX10", "syTeeth", "syGap", "injStrategy",
    "ignStrategy",
    "loadSource", "injFlowCcMin", "fuelPumpMode", "timingModeCfg",
    "fixedTimingX10", "dbwEnable", "dbwMaxDutyX10", "appCorrelation",
    "tpsCorrelation", "pedal1Min", "pedal1Max", "pedal2Min", "pedal2Max",
    "tps1Min", "tps1Max", "tps2Min", "tps2Max", "lambda1Source",
    "pinClt", "pinIat", "pinMap", "pinCrank")
PAGE_ARRAYS = ("injPin", "ignPin", "cltSensAx", "cltSensVal")


def page_config(ini_path: Path, page: bytes) -> dict:
    txt = ini_path.read_text(encoding="utf-8", errors="replace")
    body = txt.split("[Constants]", 1)[1]
    body = re.split(r"^\[", body, maxsplit=1, flags=re.M)[0]
    out = {}
    for line in body.splitlines():
        m = re.match(r"\s*(\w+)\s*=\s*(scalar|bits|array)\s*,\s*([US]\d\d)"
                     r"\s*,\s*(\d+)\s*,(.*)", line)
        if not m:
            continue
        name, kind, typ, off, rest = (m.group(1), m.group(2), m.group(3),
                                      int(m.group(4)), m.group(5))
        w = SIZES[typ]
        if kind == "array" and name in PAGE_ARRAYS:
            dm = re.match(r"\s*\[\s*(\d+)", rest)
            cnt = int(dm.group(1)) if dm else 1
            out[name] = [int.from_bytes(page[off + i * w:off + i * w + w], "big")
                         for i in range(cnt)]
        elif kind != "array" and name in PAGE_FIELDS:
            out[name] = int.from_bytes(page[off:off + w], "big",
                                       signed=typ[0] == "S")
    return out


def pick_ini(signature: str, version: str, override: str | None) -> Path:
    if override:
        return Path(override)
    cands = []
    for p in TS_DIR.glob("hanicore_me711_v*.ini"):
        if p.stem.endswith(("_forensic", "_fallback")):
            continue
        try:
            head = p.read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            continue
        if ('"%s"' % signature) in head:
            cands.append(p)
    if not cands:
        raise SystemExit("no .ini in %s declares signature %r - pass --ini"
                         % (TS_DIR, signature))
    m = re.search(r"\bV(\d+)\b", version or "")
    if m:
        tagged = [p for p in cands if re.search(r"_v%s_" % m.group(1), p.name)]
        if tagged:
            return sorted(tagged)[-1]

    def vnum(p):
        mm = re.search(r"_v(\d+)", p.name)
        return int(mm.group(1)) if mm else -1
    return max(cands, key=vnum)


def build_manifest(version: str):
    """The local build whose manifest carries EXACTLY the version text the ECU
    announced. This is a LOOKUP in this checkout, not a readback: the ECU does
    not publish its own image hash, and a different checkout may hold a
    different build with the same text."""
    if not version:
        return None
    hits = []
    for j in sorted((ROOT / "bins/hanicore").glob("HaniCore_ME711_v*.json")):
        try:
            d = json.loads(j.read_text())
        except Exception:
            continue
        if d.get("version_text") == version:
            hits.append({"manifest": str(j), "stem": j.stem,
                         "build": d.get("build"), "sha256": d.get("sha256")})
    if len(hits) == 1:
        return hits[0]
    return {"ambiguous_or_none": hits} if hits else None


# ========================================================== the transport ===
def envelope(payload: bytes) -> bytes:
    crc = binascii.crc32(payload) & 0xFFFFFFFF
    return len(payload).to_bytes(2, "big") + payload + crc.to_bytes(4, "big")


class SerialTransport:
    def __init__(self, port: str, baud: int):
        import serial
        self.ser = serial.Serial(port, baud, timeout=0.05, write_timeout=1.0)

    def write(self, b: bytes):
        self.ser.reset_input_buffer()
        self.ser.write(b)
        self.ser.flush()

    def read(self, n: int) -> bytes:
        # what has arrived, or wait (<= the 50 ms timeout) for the first byte.
        # read(n) waited the whole timeout whenever fewer than n bytes came -
        # every reply then cost >= 50 ms and rtt_ms measured the host (V91
        # bench: 'W' 62 ms through read(1024), 5.4 ms through this).
        return self.ser.read(max(1, min(n, self.ser.in_waiting)))

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


class Link:
    """One request -> one parsed reply, with the K-line echo removed.

    `allowed` is the command whitelist. THIS logger keeps the read-only set;
    the active commissioning tools (me711_dbw_vehicle_test.py,
    me711_trigger_vehicle_test.py) subclass it with exactly the commands they
    need and nothing else."""

    allowed = ALLOWED_CMDS

    def __init__(self, tr, frames_log, clock=time.monotonic):
        self.tr = tr
        self.flog = frames_log
        self.clock = clock

    def request(self, payload: bytes, timeout_s: float):
        if payload[:1] and payload[0] not in self.allowed:
            raise RuntimeError("command %r is not allowed in this tool" % payload[:1])
        req = envelope(payload)
        t0 = self.clock()
        self.tr.write(req)
        buf = bytearray()
        deadline = t0 + timeout_s
        want = None
        body = None
        err = None
        while self.clock() < deadline:
            part = self.tr.read(1024)
            if part:
                buf.extend(part)
            data = bytes(buf)
            if data.startswith(req):
                data = data[len(req):]
            elif len(data) < len(req) and req.startswith(data):
                continue                      # echo still arriving
            if len(data) >= 2 and want is None:
                want = 2 + ((data[0] << 8) | data[1]) + 4
            if want is not None and len(data) >= want:
                n = (data[0] << 8) | data[1]
                blob = data[2:2 + n]
                crc = int.from_bytes(data[2 + n:6 + n], "big")
                if crc != (binascii.crc32(blob) & 0xFFFFFFFF):
                    err = "crc"
                elif not blob or blob[0] != 0:
                    err = "code 0x%02X" % (blob[0] if blob else -1)
                else:
                    body = blob[1:]
                break
        else:
            err = "timeout (%d bytes)" % len(buf)
        rtt = (self.clock() - t0) * 1000.0
        self.flog.write(json.dumps({
            "t_mono": round(t0, 4), "t_wall": utc(),
            "cmd": payload[:1].decode("latin1"), "req": payload.hex(),
            "rtt_ms": round(rtt, 1), "ok": body is not None, "err": err,
            "rx": bytes(buf).hex() if (body is None or len(buf) <= 64)
            else None, "payload": body.hex() if body is not None else None,
        }) + "\n")
        self.flog.flush()
        return body, err, rtt

    def text(self, cmd: bytes):
        body, err, _ = self.request(cmd, 0.6)
        if body is None:
            return None
        return body.split(b"\0")[0].decode("latin1", "replace").strip()

    def och(self, off: int, cnt: int):
        body, err, rtt = self.request(b"O" + off.to_bytes(2, "big")
                                      + cnt.to_bytes(2, "big"),
                                      0.4 + cnt / 4000.0)
        if body is not None and len(body) != cnt:
            return None, "length %d != %d" % (len(body), cnt), rtt
        return body, err, rtt

    def page_read(self, size=4096, chunk=256):
        out = bytearray()
        for off in range(0, size, chunk):
            body, err, _ = self.request(b"R" + off.to_bytes(2, "big")
                                        + chunk.to_bytes(2, "big"), 1.0)
            if body is None or len(body) != chunk:
                return None
            out.extend(body)
        return bytes(out)


# ============================================================ the steps ===
# (key, marker, prompt, min_s, auto-advance rule, auto-mode seconds)
STEPS = [
    ("baseline", "KEY_ON_BASELINE",
     "Key ON, engine stopped. Do nothing - recording the key-on baseline.",
     6, "timer", 6),
    ("released", "PEDAL_RELEASED",
     "Leave the accelerator COMPLETELY RELEASED. Press ENTER after ~3 s.",
     3, "enter", 4),
    ("full", "PEDAL_FULL",
     "Press the accelerator FULLY and HOLD it. Press ENTER after ~3 s.",
     3, "enter", 4),
    ("release", "PEDAL_RELEASE",
     "RELEASE the accelerator completely. Press ENTER after ~3 s.",
     3, "enter", 4),
    ("sweep", "PEDAL_SWEEP",
     "SLOWLY press the pedal 0 -> 100 % -> 0 (about 5 s each way). "
     "Press ENTER when back at 0.",
     6, "enter", 6),
    ("session", "ENGINE_SESSION",
     "ENGINE SESSION - pedal released. Crank, run, stop with the KEY, key on "
     "again, crank again: anything, in any order. Every state is recorded. "
     "Press ENTER to finish (q aborts).",
     1, "session", 30),
]
PEDAL_STEPS = ("released", "full", "release", "sweep")


# ========================================================== the session ===
class Capture:
    def __init__(self, a, transport=None, stdin_q=None, clock=time.monotonic,
                 sleep=time.sleep, out_root=None):
        self.a = a
        self.clock = clock
        self.sleep = sleep
        base = out_root or (Path(a.out) if a.out else default_evidence_root())
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.dir = Path(base) / ("VEHICLE_CAPTURE_" + stamp)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.console = (self.dir / "console.log").open("a", encoding="utf-8")
        self.frames = (self.dir / "frames.jsonl").open("a", encoding="utf-8")
        self.events = (self.dir / "events.jsonl").open("a", encoding="utf-8")
        self.tr = transport
        self.link = None
        self.ini = None
        self.meta = {"tool": "me711_vehicle_capture.py", "tool_version":
                     TOOL_VERSION, "tool_git": git_commit(),
                     "port": a.port, "baud": a.baud, "started_utc": utc(),
                     "mode": "auto" if a.auto else "interactive",
                     "steps": [], "connects": []}
        self.stdin_q = stdin_q
        self.rows = []              # decoded fast rows, for the summary
        self.latest = {}            # channel -> (value, t_mono)
        self.step = "wait"
        self.online = False
        self.fails = 0
        self.last_full = -1e9
        self.boot_count = None
        self.last_tick = None
        self.saw_keyoff = False
        self.csv = None
        self.csv_cols = None
        self.full_csv = None
        self.full_cols = None
        self.last_status = 0.0
        self.cycle = 0
        self.prev = {}
        # V1.2: the observed vehicle state and the start attempts
        self.vstate = "OFFLINE"
        self.vstate_since = self.clock()
        self.run_count = 0
        self.attempt = 0
        self.attempts = []          # dicts, see vehicle_state()
        self.tl_fetched = None      # (state, teeth) of the last profile read
        self.profiles = []

    # ------------------------------------------------------------ output --
    def say(self, s: str):
        line = "%s  %s" % (utc()[11:23], s)
        print("\r" + " " * 118 + "\r" + line, flush=True)
        self.console.write(line + "\n")
        self.console.flush()

    def event(self, kind: str, **kw):
        rec = {"t_mono": round(self.clock(), 4), "t_wall": utc(),
               "step": self.step, "event": kind}
        rec.update(kw)
        self.events.write(json.dumps(rec) + "\n")
        self.events.flush()
        self.say("EVENT %s %s" % (kind, " ".join("%s=%s" % i for i in kw.items())))

    def write_meta(self):
        (self.dir / "metadata.json").write_text(json.dumps(self.meta, indent=2))

    # ----------------------------------------------------------- connect --
    def ensure_transport(self):
        if self.tr is None:
            # V1.3: --port auto (the default) tries every serial port that is
            # not the bench; the car laptop's KKL was COM2, and the first
            # V92 capture was lost to a COM3 default.
            ports = [self.a.port] if self.a.port != "auto" else auto_ports()
            for p in ports:
                try:
                    tr = SerialTransport(p, self.a.baud)
                except Exception as e:
                    self.say("cannot open %s: %s" % (p, e))
                    continue
                if self.a.port == "auto":
                    probe = Link(tr, self.frames, self.clock).text(b"S")
                    if not probe or "HaniCore" not in probe:
                        tr.close()
                        continue
                self.tr = tr
                self.meta["port"] = p
                self.say("KKL on %s" % p)
                break
            if self.tr is None:
                self.say("no HaniCore answer on %s - retrying (key ON?)"
                         % ",".join(ports))
                self.sleep(2.0)
                return False
        if self.link is None:
            self.link = Link(self.tr, self.frames, self.clock)
        return True

    def try_connect(self) -> bool:
        if not self.ensure_transport():
            return False
        sig = self.link.text(b"S")
        if not sig or "HaniCore" not in sig:
            return False
        ver = self.link.text(b"V") or ""
        if self.ini is None or self.ini.signature != sig:
            try:
                ip = pick_ini(sig, ver, self.a.ini)
                self.ini = Ini(ip)
            except SystemExit as e:
                self.say(str(e))
                return False
            if self.ini.signature != sig:
                self.say("SIGNATURE MISMATCH: ECU %r, .ini %r - pass --ini"
                         % (sig, self.ini.signature))
                self.event("SIGNATURE_MISMATCH", ecu=sig, ini=self.ini.signature)
                return False
        man = build_manifest(ver)
        con = {"t_wall": utc(), "t_mono": round(self.clock(), 3),
               "signature": sig, "version": ver,
               "layout_id": sig.split()[-1] if sig else None,
               "ini": str(self.ini.path), "ini_block": self.ini.block,
               "local_build": man}
        self.meta["connects"].append(con)
        if "identity" not in self.meta:
            self.meta["identity"] = con
        self.write_meta()
        self.online = True
        self.fails = 0
        self.event("ECU_ONLINE", signature=sig, version=ver)
        self.fetch_boothist()
        if not (self.dir / "page.bin").exists():
            page = self.link.page_read()
            if page:
                (self.dir / "page.bin").write_bytes(page)
                self.meta["page_sha256"] = hashlib.sha256(page).hexdigest()
                try:
                    self.meta["page_config"] = page_config(self.ini.path, page)
                except Exception as e:           # evidence first, decode second
                    self.meta["page_config"] = {"error": str(e)}
                self.write_meta()
                pc = self.meta["page_config"]
                # V97: the physical trigger angle (tooth #1, deg ATDC); a
                # V96-or-older .ini names the same slot trigOffsetX10 - the
                # same crank position mod 360
                ang = pc.get("trigAngleX10", pc.get("trigOffsetX10"))
                self.say("config: preset %s, %s cc, trigger angle %s, "
                         "trigSource %s, pump mode %s, DBW enable %s"
                         % (pc.get("enginePreset"), pc.get("displacementCc"),
                            ang, pc.get("trigSource"),
                            pc.get("fuelPumpMode"), pc.get("dbwEnable")))
                self.say("calibration page read: sha256 %s"
                         % self.meta["page_sha256"][:16])
        self.open_csv()
        return True

    def open_csv(self):
        if self.csv is not None:
            return
        fast = (self.ini.in_window(*FAST)
                + self.ini.in_window(*lam_window(self.ini))
                + self.ini.in_window(*fast2_window(self.ini))
                + self.ini.in_window(*fast3_window(self.ini)))
        aux = [n for n in (self.ini.in_window(*aux_window(self.ini))
                           + [c for k in range(AUX1_SLICES, AUX_SPLIT)
                              for c in self.ini.in_window(*aux_window(self.ini, k))])
               if n not in fast]
        comp = sorted(self.ini.computed)
        # V1.4: AUX channels are INTERLEAVED - one slice is fresh per row,
        # the others carry their last value. aux_part names the fresh slice
        # ("" = its read failed), aux_age_s is the age of the OLDEST slice
        # (until V1.3 it was slice 0's age only), and metadata.json
        # "aux_interleave" gives each slice's window, so analysis never
        # correlates a FAST sample with an AUX value from another cycle
        # without knowing it.
        self.csv_cols = (["t_mono", "t_wall", "step", "cycle", "rtt_fast_ms",
                          "rtt_fast2_ms", "rtt_aux_ms", "aux_age_s",
                          "aux_part", "vstate", "attempt"]
                         + fast + aux + comp)
        self.meta["fast2_window"] = list(fast2_window(self.ini))
        self.meta["lambda_window"] = list(lam_window(self.ini))
        self.meta["fast3_window"] = list(fast3_window(self.ini))
        self.meta["aux_interleave"] = {
            "slices": AUX_SPLIT,
            "windows": [list(aux_window(self.ini, k)) for k in range(AUX_SPLIT)],
            "channels": [self.ini.in_window(*aux_window(self.ini, k))
                         for k in range(AUX_SPLIT)],
            "note": "decoded.csv: FAST (offset %d..%d) and FAST2 (offset %d.."
                    "1024; empty rtt_fast2_ms = that read failed and "
                    "its values are the previous row's) are fresh every row, "
                    "and so is the lambda window (734..739, V1.6); "
                    "AUX slice aux_part is fresh, the other slices are the "
                    "last value read, at most aux_age_s old. full.csv rows "
                    "are one coherent read of the whole block."
                    % (FAST[0], FAST[1], FAST2_START)}
        f = (self.dir / "decoded.csv").open("a", newline="", encoding="utf-8")
        self.csv = (f, csv.writer(f))
        self.csv[1].writerow(self.csv_cols)
        self.full_cols = ["t_mono", "t_wall", "step"] + self.ini.order
        g = (self.dir / "full.csv").open("a", newline="", encoding="utf-8")
        self.full_csv = (g, csv.writer(g))
        self.full_csv[1].writerow(self.full_cols)
        (self.dir / "channels.json").write_text(json.dumps(
            {n: {"type": t, "offset": o, "units": u, "scale": s,
                 "translate": tr} for n, (t, o, u, s, tr)
             in self.ini.scalars.items()}, indent=1))

    # ------------------------------------------------------------ sample --
    def sample(self):
        """One cycle. Returns False when the ECU did not answer."""
        now = self.clock()
        blob, err, rtt = self.link.och(*FAST)
        if blob is None:
            self.fails += 1
            if self.online and self.fails >= OFFLINE_AFTER_FAILS:
                self.online = False
                self.event("ECU_OFFLINE" if not self.saw_keyoff
                           else "ECU_OFFLINE_AFTER_KEYOFF",
                           last_error=err, keyoff_seen=self.saw_keyoff)
                self.set_vstate("OFFLINE", now)
            return False
        self.fails = 0
        raw = self.ini.decode(blob, FAST[0])
        # V1.6: ONE failed read ends this cycle's reads. An ECU that has
        # just gone (key-off) times every further request out, and those
        # timeouts do not count towards OFFLINE - each one only delayed the
        # next FAST read that does. A lost window is marked empty on the row.
        alive = True
        f2 = fast2_window(self.ini)
        f2blob, f2rtt = None, None
        if f2[1]:
            f2blob, _f2err, f2rtt = self.link.och(*f2)
            alive = f2blob is not None
            if alive:
                raw.update(self.ini.decode(f2blob, f2[0]))
                for n in self.ini.in_window(*f2):
                    self.latest[n] = (raw[n], now)
        f3 = fast3_window(self.ini)
        if f3[1] and alive:
            f3blob, _f3err, _f3rtt = self.link.och(*f3)
            alive = f3blob is not None
            if alive:
                raw.update(self.ini.decode(f3blob, f3[0]))
                for n in self.ini.in_window(*f3):
                    self.latest[n] = (raw[n], now)
        lw = lam_window(self.ini)
        if lw[1] and alive:
            lblob, _lerr, _lrtt = self.link.och(*lw)
            alive = lblob is not None
            if alive:
                raw.update(self.ini.decode(lblob, lw[0]))
                for n in self.ini.in_window(*lw):
                    self.latest[n] = (raw[n], now)
        part = self.cycle % AUX_SPLIT
        aw = aux_window(self.ini, part)
        ablob, artt = None, None
        if alive and aw[1]:
            ablob, _aerr, artt = self.link.och(*aw)
            alive = ablob is not None
        if ablob is not None:
            raw.update(self.ini.decode(ablob, aw[0]))
            for n in self.ini.in_window(*aw):
                self.latest[n] = (raw[n], now)
        if alive and now - self.last_full >= FULL_PERIOD_S:
            fb, ferr, _ = self.link.och(0, self.ini.block)
            if fb is not None:
                self.last_full = now
                fr = self.ini.decode(fb, 0)
                self.full_csv[1].writerow(
                    [round(now, 4), utc(), self.step]
                    + [self.ini.eng(n, fr[n]) if n in fr else ""
                       for n in self.ini.order])
                self.full_csv[0].flush()
                for n, v in fr.items():
                    if n not in raw:
                        raw[n] = v
                        self.latest[n] = (v, now)
        # carry AUX/FULL values forward for expression evaluation only
        for n, (v, t) in self.latest.items():
            raw.setdefault(n, v)
        comp = self.ini.evaluate(raw)
        self.cycle += 1
        self.detect(raw, comp, now)
        self.vehicle_state(raw, now)
        self.maybe_fetch_profile(raw)
        eng = {n: self.ini.eng(n, v) for n, v in raw.items()
               if n in self.ini.scalars}
        eng.update(comp)
        eng["t"] = now
        eng["step"] = self.step
        eng["vstate"] = self.vstate
        eng["attempt"] = self.attempt
        self.rows.append(eng)
        ages = []
        for k in range(AUX_SPLIT):
            ch = self.ini.in_window(*aux_window(self.ini, k))
            if ch:
                ages.append(now - self.latest[ch[0]][1]
                            if ch[0] in self.latest else None)
        aux_age = ("" if not ages or None in ages else max(ages))
        row = [round(now, 4), utc(), self.step, self.cycle, round(rtt, 1),
               round(f2rtt, 1) if f2blob is not None else "",
               round(artt, 1) if ablob is not None else "",
               round(aux_age, 3) if aux_age != "" else "",
               part if ablob is not None else "",
               self.vstate, self.attempt]
        for n in self.csv_cols[11:]:
            v = eng.get(n, "")
            row.append(v)
        self.csv[1].writerow(row)
        self.csv[0].flush()
        self.status(eng)
        return True

    # ----------------------------------------------------- transitions ---
    def detect(self, raw, comp, now):
        bc = raw.get("rstBootCount")
        tick = raw.get("tickMs")
        if bc is not None:
            if self.boot_count is not None and bc != self.boot_count:
                self.event("ECU_RESET", boot_count_from=self.boot_count,
                           boot_count_to=bc, raw_reset=raw.get("rstRawReset"))
            self.boot_count = bc
        if tick is not None and self.last_tick is not None \
                and tick < self.last_tick and (self.last_tick - tick) > 5000 \
                and bc is None:
            self.event("TICK_WENT_BACKWARDS", was=self.last_tick, now=tick)
        self.last_tick = tick
        ro = raw.get("runOn")
        if ro is not None and (ro >> 8) & 1 and not self.saw_keyoff:
            self.saw_keyoff = True
            self.event("KL15_OFF_SEEN", run_on_state=ro & 0xFF)
        if ro is not None and not (ro >> 8) & 1 and self.saw_keyoff:
            self.saw_keyoff = False
            self.event("KL15_ON_AGAIN")
        # V1.2: syncState is trg_state - hcTrgStateList. V1.1 decoded it with
        # the syncMode list and printed crank sync losses as "cam flips".
        for name, label in (("rpm", None), ("syncState", "hcTrgStateList"),
                            ("dbwState", "hcDbwStateList"),
                            ("fuelPumpState", "hcPumpStateList"),
                            ("mainRelayLife", "hcRelayStateList"),
                            ("syncLossCount", None), ("dbwFaults", None),
                            ("toothCorrections", None),
                            ("cycleSyncAcquired", None),
                            ("cycleSyncLost", None),
                            ("camPhaseCorrections", None),
                            ("toothLogState", None),
                            ("sensorErr", None), ("cfgValidation", None),
                            ("asicTimeouts", None), ("asicCsumErr", None),
                            ("asicSscErr", None), ("lambdaStatus", None),
                            ("safetyInhibits", None)):
            v = raw.get(name)
            if v is None:
                continue
            p = self.prev.get(name)
            if name == "rpm":
                if (p in (None, 0)) and v > 0:
                    self.event("RPM_FIRST_SEEN" if p is not None else
                               "RPM_NONZERO_AT_CONNECT", rpm=v)
                if p not in (None, 0) and v == 0:
                    self.event("RPM_ZERO")
            elif p is not None and v != p:
                txt = ""
                lst = self.ini.lists.get(label) if label else None
                if lst:
                    idx = v & 0xFF
                    txt = lst[idx] if idx < len(lst) else ""
                    if name == "syncState" and v >= 1 and (p or 0) == 0:
                        self.event("SYNC_ACQUIRED", state=v, text=txt)
                self.event("CHANGE", channel=name, was=p, now=v, text=txt)
            self.prev[name] = v

    # ------------------------------------------------- V1.2 vehicle state ---
    def set_vstate(self, st, now):
        if st == self.vstate:
            return
        was = self.vstate
        self.vstate = st
        self.vstate_since = now
        self.event("STATE", was=was, now=st, attempt=self.attempt)
        a = self.attempts[-1] if self.attempts else None
        if st == "CRANKING" and was in ("STOPPED", "OFFLINE", "KEY_OFF"):
            self.attempt += 1
            a = {"n": self.attempt, "t_crank": now, "t_run": None,
                 "t_end": None, "outcome": None, "rows_from": len(self.rows)}
            self.attempts.append(a)
            self.event("ATTEMPT_START", attempt=self.attempt)
        if a is None or a["outcome"]:
            return
        if st == "RUNNING" and a["t_run"] is None:
            a["t_run"] = now
            self.event("ENGINE_RUNNING", attempt=a["n"],
                       crank_to_run_s=round(now - a["t_crank"], 2))
        if st in ("STOPPED", "KEY_OFF", "OFFLINE") and was in (
                "CRANKING", "RUNNING", "RUNDOWN"):
            a["t_end"] = now
            if a["t_run"] is None:
                a["outcome"] = "NO_START"
                # V1.3: tell a starter that stalled on a weak battery from an
                # engine that turned freely and did not fire.
                bv = [r.get("battDv") for r in self.rows[a["rows_from"]:]
                      if r.get("vstate") == "CRANKING"
                      and isinstance(r.get("battDv"), (int, float))]
                a["batt_min_v"] = min(bv) if bv else None
                if a.get("stalls", 0) >= 2 and bv and min(bv) < WEAK_BATT_V:
                    a["outcome"] = "NO_START_WEAK_BATTERY"
            elif st == "STOPPED" and not self.saw_keyoff:
                a["outcome"] = "STALL"
            else:
                a["outcome"] = "STOPPED_BY_KEY"
            a["rows_to"] = len(self.rows)
            self.event("ATTEMPT_END", attempt=a["n"], outcome=a["outcome"],
                       ran_s=round(now - a["t_run"], 2) if a["t_run"] else 0)
        if st == "KEY_OFF" and was == "RUNNING" and not a["outcome"]:
            # the engine usually runs down after the key: the attempt ends
            # when rpm reaches 0 or the ECU goes silent (handled above)
            pass

    def vehicle_state(self, raw, now):
        rpm = raw.get("rpm")
        if rpm is None:
            return
        # V1.3: a CRANK STALL - the decoder counting but no crank edge since
        # the last sample (rpm is only updated at the gap, so it stays at the
        # last revolution's value while the crank stands still: V92 attempts
        # 2/3 showed 184 rpm for 0.4 s with the crank stopped).
        ce = raw.get("crankEdges")
        if (self.vstate == "CRANKING" and ce is not None
                and ce == self.prev.get("_ce") and ce > 0
                and (raw.get("syncState") or 0) >= 1 and self.attempts):
            a = self.attempts[-1]
            if not a.get("outcome"):
                a["stalls"] = a.get("stalls", 0) + 1
                if a["stalls"] in (1, 3, 10):
                    self.event("CRANK_STALL", attempt=a["n"],
                               tooth=raw.get("crankToothIndex"),
                               batt_v=(raw.get("battDv") or 0) / 10.0,
                               stalls=a["stalls"])
        self.prev["_ce"] = ce
        if self.saw_keyoff:
            if rpm == 0:
                self.set_vstate("KEY_OFF", now)
            elif self.vstate in ("RUNNING", "RUNDOWN"):
                self.set_vstate("RUNDOWN", now)
            return
        if rpm == 0:
            self.run_count = 0
            self.set_vstate("STOPPED", now)
        elif rpm >= RUN_RPM:
            self.run_count += 1
            if self.run_count >= 2 or self.vstate == "RUNNING":
                self.set_vstate("RUNNING", now)
        else:
            self.run_count = 0
            if self.vstate in ("RUNNING", "RUNDOWN"):
                self.set_vstate("RUNDOWN", now)
            else:
                self.set_vstate("CRANKING", now)

    def maybe_fetch_profile(self, raw):
        """A finished tooth-profile test: read its 60 bins once."""
        st = raw.get("toothLogState")
        if st is None or (st & 0xFF) != 3:
            return
        key = (st, raw.get("toothLogTeeth"), raw.get("toothLogRevs"))
        if key == self.tl_fetched:
            return
        off = self.ini.block + TL_EXT_OFF
        body, err, _ = self.link.och(off, 2 * TL_BINS)
        if body is None or len(body) != 2 * TL_BINS:
            self.event("TOOTH_PROFILE_READ_FAILED", error=err)
            return
        self.tl_fetched = key
        bins = [int.from_bytes(body[2 * i:2 * i + 2], "big")
                for i in range(TL_BINS)]
        pc = self.meta.get("page_config") or {}
        res = tooth_profile_analysis(bins, pc.get("trigAngleX10",
                                                  pc.get("trigOffsetX10")),
                                     pc.get("cylinders") or 4,
                                     (st >> 8) & 0x3F)
        n = len(self.profiles) + 1
        path = self.dir / ("toothprofile_%d.csv" % n)
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["bin", "engine_deg", "physical_deg", "permille"])
            for row in res["rows"]:
                w.writerow(row)
        res.pop("rows")
        res.update({"n": n, "mode": (st >> 8) & 0x3F,
                    "restored_after_reset": bool(st & 0x4000),
                    "teeth": raw.get("toothLogTeeth"),
                    "revs": raw.get("toothLogRevs"), "file": path.name})
        self.profiles.append(res)
        self.meta["tooth_profiles"] = self.profiles
        self.write_meta()
        self.event("TOOTH_PROFILE", **{k: v for k, v in res.items()
                                       if k != "file"})

    # ------------------------------------------------- V1.3 boot history --
    def fetch_boothist(self):
        """The ECU's battery-backed ring of the last 16 boots (V93+): why
        each previous boot ended - the key-off reset storm's own trail."""
        off = self.ini.block + BH_EXT_OFF
        body, err, _ = self.link.och(off, BH_BYTES)
        if body is None or len(body) != BH_BYTES or body[:2] != b"BH":
            return
        recs = decode_boothist(body)
        n = len(self.meta.setdefault("boot_history", [])) + 1
        self.meta["boot_history"].append({"t_wall": utc(), "records": recs})
        (self.dir / ("boothist_%d.bin" % n)).write_bytes(body)
        self.write_meta()
        storm = [r for r in recs if not r["kl15_at_boot"]]
        self.event("BOOT_HISTORY", records=len(recs),
                   booted_with_key_off=len(storm),
                   last=recs[-1] if recs else None)

    # ------------------------------------------------------------ status --
    def status(self, e):
        if self.clock() - self.last_status < 0.5:
            return
        self.last_status = self.clock()

        def g(n, fmt="%s"):
            v = e.get(n)
            return fmt % v if v not in (None, "") else "--"
        line = ("[%s %s] rpm %s sync %s | APP %s/%s TPS %s/%s tgt %s act %s "
                "dbw %s/%s | MAP %s CLT %s IAT %s Ub %s | L1 %s L2 %s st %s | "
                "ASICto %s" % (
                    self.step, self.vstate, g("rpm"), g("syncState"),
                    g("dbwApp1X10"), g("dbwApp2X10"), g("dbwTps1X10"),
                    g("dbwTps2X10"), g("dbwTargetX10"), g("dbwActualX10"),
                    g("dbwState"), g("dbwFaults"), g("mapKpaX10"),
                    g("cltDc"), g("iatDc"), g("battDv"), g("lambda1X1000"),
                    g("lambda2X1000"), g("lambdaStatus", "%04X"),
                    g("asicTimeouts")))
        print("\r" + line[:118].ljust(118), end="", flush=True)

    # ------------------------------------------------------------- flow ---
    def wait_online(self, why: str, max_s: float | None = None) -> bool:
        t0 = self.clock()
        announced = False
        while not self.online:
            if self.try_connect():
                return True
            if not announced:
                self.say("waiting for HaniCore on %s (%s)..." % (self.a.port, why))
                announced = True
            if max_s is not None and self.clock() - t0 > max_s:
                return False
            if self.poll_stdin() == "q":
                raise KeyboardInterrupt
            self.sleep(PROBE_PERIOD_S)
        return True

    def poll_stdin(self):
        if self.stdin_q is None:
            return None
        try:
            return self.stdin_q.get_nowait().strip().lower() or "enter"
        except queue.Empty:
            return None

    def run_step(self, key, marker, prompt, min_s, rule, auto_s):
        self.step = key
        rec = {"step": key, "marker": marker, "start_wall": utc(),
               "start_mono": round(self.clock(), 3)}
        self.meta["steps"].append(rec)
        self.write_meta()
        self.say("")
        self.say("=== STEP %s ===  %s" % (key.upper(), prompt))
        self.event(marker)
        t0 = self.clock()
        crank_seen = False
        zero_since = None
        self._told_long = False
        while True:
            if not self.online:
                if rule == "offline":
                    self.event("KEYOFF_ECU_SILENT")
                    break
                if rule == "session":
                    # V1.2: ignition off is a normal part of a session. Keep
                    # probing for the ECU and keep listening for ENTER.
                    if self.a.auto and self.clock() - t0 > auto_s:
                        break
                    if self.try_connect():
                        continue
                    c = self.poll_stdin()
                    if c == "q":
                        raise KeyboardInterrupt
                    if c == "enter":
                        break
                    if not getattr(self, "_told_off", False):
                        self._told_off = True
                        self.say("ECU silent (ignition off?) - still recording; "
                                 "turn the key on again to continue, ENTER to "
                                 "finish")
                    self.sleep(PROBE_PERIOD_S)
                    continue
                if not self.wait_online("communication lost during %s" % key,
                                        max_s=self.a.offline_wait):
                    self.event("GAVE_UP_WAITING", step=key)
                    break
            self._told_off = False
            ok = self.sample()
            now = self.clock()
            el = now - t0
            if not ok:
                if rule == "offline" and not self.online:
                    rec["ecu_silent_after_s"] = round(el, 3)
                    break
                self.sleep(0.05)
                continue
            cmd = self.poll_stdin()
            if cmd == "q":
                raise KeyboardInterrupt
            if cmd and cmd.startswith("m "):
                self.event("OPERATOR_NOTE", text=cmd[2:])
            if rule == "session":
                if cmd == "enter" and el > min_s:
                    break
                if self.a.auto and el > auto_s:
                    break
                if (self.vstate == "CRANKING" and not self._told_long
                        and now - self.vstate_since > 10.0):
                    self._told_long = True
                    self.say("cranking for 10 s without a start - rest the "
                             "starter before the next attempt")
                if self.vstate != "CRANKING":
                    self._told_long = False
                continue
            rpm = self.latest_value("rpm")
            if rule == "crank":
                if rpm and not crank_seen:
                    crank_seen = True
                if crank_seen and not rpm:
                    zero_since = zero_since or now
                    if now - zero_since > 1.5:
                        break
                else:
                    zero_since = None
                if el > 5.0 and crank_seen and self.a.auto is False \
                        and not getattr(self, "_told_stop", False):
                    self._told_stop = True
                    self.say(">>> STOP CRANKING NOW <<<")
                if self.a.auto and el > auto_s:
                    break
                if cmd == "enter" and el > min_s:
                    break
                continue
            if self.a.auto:
                if el >= auto_s:
                    break
                continue
            if rule == "timer" and el >= min_s:
                break
            if rule == "enter" and cmd == "enter" and el >= min_s:
                break
            if rule == "offline" and el > self.a.offline_wait:
                self.event("KEYOFF_TIMEOUT_ECU_STILL_TALKING")
                break
        self._told_stop = False
        rec["end_wall"] = utc()
        rec["end_mono"] = round(self.clock(), 3)
        rec["checks"] = self.step_checks(key)
        self.write_meta()

    # ------------------------------------------------ objective checks ---
    def step_checks(self, key):
        """PASS only for an objective, measured property; CHECK when it did
        not hold; INFO for a value the operator must judge. Nothing is called
        PASS on an absent or ambiguous measurement."""
        rows = [r for r in self.rows if r.get("step") == key]
        out = []

        def emit(verdict, text):
            out.append([verdict, text])
            self.say("  %-5s %s" % (verdict, text))

        def vals(n):
            return [r[n] for r in rows if r.get(n, "") != ""]

        def delta(n):
            v = vals(n)
            return counter_delta(v) if len(v) >= 2 else None

        if not rows:
            emit("CHECK", "no samples were received in this step")
            return out
        cv = vals("cfgValidation")
        if cv:
            emit("PASS" if all(v == 0 for v in cv) else "CHECK",
                 "configuration valid (cfgValidation 0) in every sample"
                 if all(v == 0 for v in cv) else
                 "cfgValidation non-zero: %s, first bad offset %s"
                 % (sorted(set(cv)), vals("cfgFirstBadOffset")[-1:]))
        for n in ("asicTimeouts", "asicCsumErr", "asicSscErr"):
            d = delta(n)
            if d is not None:
                emit("PASS" if d == 0 else "CHECK", "%s delta %d" % (n, d))
        se = vals("sensorErr")
        if se:
            bits = 0
            for v in se:
                bits |= int(v)
            emit("PASS" if bits & 0x00C0 == 0 else "CHECK",
                 "APP pair / TPS pair plausibility errors: %s"
                 % ("none" if bits & 0x00C0 == 0 else "0x%04X" % (bits & 0xC0)))
            if bits & ~0x00C0:
                emit("INFO", "other sensorErr bits seen: 0x%04X" % (bits & ~0xC0))
        b = vals("battDv")
        if b:
            emit("INFO", "battery %.1f .. %.1f V" % (min(b), max(b)))
        for n in ("dbwApp1X10", "dbwApp2X10", "dbwTps1X10", "dbwTps2X10",
                  "mapKpaX10", "cltDc", "iatDc"):
            v = vals(n)
            if v:
                emit("INFO", "%s %s .. %s" % (n, min(v), max(v)))
        rpm = vals("rpm")
        if key in ("baseline", "released", "full", "release", "sweep",
                   "precrank"):
            emit("PASS" if rpm and max(rpm) == 0 else "CHECK",
                 "engine stopped (rpm 0 throughout)" if rpm and max(rpm) == 0
                 else "rpm seen: max %s" % (max(rpm) if rpm else "n/a"))
        if key == "session":
            for a in self.attempts:
                emit("INFO", "attempt %d: %s%s" % (
                    a["n"], a["outcome"] or "in progress",
                    (", crank->run %.1f s" % (a["t_run"] - a["t_crank"]))
                    if a["t_run"] else ""))
            for n in ("syncLossCount", "toothCorrections", "cycleSyncLost",
                      "schedulerLate", "schedulerMissed", "schedOverdwell"):
                d = delta(n)
                if d is not None:
                    emit("INFO", "%s delta %d (summed across resets)" % (n, d))
        if key == "crank":
            emit("PASS" if rpm and max(rpm) > 0 else "CHECK",
                 "crank detected, rpm max %s" % (max(rpm) if rpm else "n/a"))
            sy = vals("syncState")
            emit("PASS" if sy and max(sy) >= 1 else "CHECK",
                 "crank sync obtained (syncState >= 1)" if sy and max(sy) >= 1
                 else "NO crank sync during the crank step")
            d = delta("syncLossCount")
            if d is not None:
                emit("INFO", "syncLossCount delta %d" % d)
            for n in ("injPulse", "dwellTime", "sparkAdvance"):
                v = [x for x in vals(n) if x]
                if v:
                    emit("INFO", "%s %s .. %s while cranking" % (n, min(v), max(v)))
        if key == "keyoff":
            ko = any((int(r.get("runOn", 0)) >> 8) & 1 for r in rows
                     if r.get("runOn", "") != "")
            emit("PASS" if ko else "CHECK",
                 "the ECU published KL15 OFF (runOn key-off flag)" if ko
                 else "the ECU never published the key-off flag")
        return out

    def latest_value(self, name):
        return self.rows[-1].get(name) if self.rows else None

    def run(self):
        self.say("HaniCore vehicle capture %s -> %s" % (TOOL_VERSION, self.dir))
        self.say("CLOSE TUNERSTUDIO - it must not use %s at the same time."
                 % self.a.port)
        self.say("This tool only READS. It never writes the calibration and "
                 "never drives an actuator.")
        if not self.a.auto:
            self.say("Connect the KKL. Leave the ignition OFF. Press ENTER, "
                     "then turn the ignition ON.")
            while self.poll_stdin() is None:
                self.sleep(0.1)
        self.wait_online("turn the ignition ON")
        self.event("KEY_ON")
        steps = [s for s in STEPS if s[0] in self.a.steps] \
            if self.a.steps else STEPS
        if getattr(self.a, "no_pedal", False):
            steps = [s for s in steps if s[0] not in PEDAL_STEPS]
        for s in steps:
            self.run_step(*s)
        self.say("capture finished")


def auto_ports() -> list:
    """Serial ports that could be the KKL - an RP2040 USB device (VID 2E8A)
    excluded: it speaks text and must never receive a TunerStudio frame."""
    try:
        from serial.tools import list_ports
        out = [p.device for p in list_ports.comports()
               if getattr(p, "vid", None) != 0x2E8A
               and "pico" not in (p.description or "").lower()]
        return out or ["COM3", "COM2"]
    except Exception:
        return ["COM3", "COM2"]


def decode_boothist(body: bytes) -> list:
    """The V93 boot-history ring, oldest first. Each record describes one
    boot: the reset that ENDED the previous boot (WDTCON raw flags: 0x3C a
    power-on, 0x1C a long hardware reset with power kept, 0x02 the
    watchdog), how long that boot lived and how far it got, its last run-on
    state and lowest battery, and KL15 at the start of THIS boot."""
    head, count = body[2], body[3]
    out = []
    for k in range(count):
        i = (head - count + k) % BH_N
        r = body[BH_HDR + i * BH_REC:BH_HDR + (i + 1) * BH_REC]
        raw = (r[2] << 8) | r[3]
        out.append({
            "boot": (r[0] << 8) | r[1], "raw_reset": raw,
            "reset_kind": ("power-on" if raw & 0x20 else
                           "long hardware reset" if raw & 0x10 else
                           "short hardware reset" if raw & 0x08 else
                           "software reset" if raw & 0x04 else
                           "watchdog" if raw & 0x02 else "?")
            if raw != 0xFFFF else "unknown",
            "prev_uptime_ms": (r[4] << 8) | r[5], "prev_stage": r[6],
            "prev_runon": RO_NAMES.get(r[7], r[7]),
            "prev_min_batt_v": None if r[8] == 0xFF else r[8] / 10.0,
            "kl15_at_boot": bool(r[9] & 1),
            "prev_last_kl15": bool(r[9] & 2),
            "prev_held_power": bool(r[9] & 4),
        })
    return out


def default_evidence_root() -> Path:
    here = Path(__file__).resolve().parent
    for p in here.parents:
        # the workspace root holds evidence\ beside archive\ (and worktrees\,
        # which may be empty or absent since the 2026-09-26 normalization).
        # It is never the git repository itself: the repo also has evidence        # (curated, tracked) and archive\, and a copy run from
        # release\<pkg>\ found it first (V91 bench, 2026-09-27).
        if (p / ".git").exists():
            continue
        if (p / "evidence").is_dir() and ((p / "archive").is_dir()
                                          or (p / "worktrees").is_dir()):
            return p / "evidence"
    # a copy outside the workspace (e.g. on the car laptop): beside itself
    return here / "VEHICLE_EVIDENCE"


def git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                              capture_output=True, text=True,
                              timeout=5).stdout.strip() or None
    except Exception:
        return None


def counter_delta(values):
    """Increments of an ECU counter over a series that may span resets.

    Counters restart at 0 on every boot and saturate at 65535. A drop is a
    reset: everything counted before it is kept and the new value is what
    was counted since. V1.1 returned last - first, which read 0 whenever a
    step contained a key cycle (2026-09-27: syncLossCount 0->3 reported as
    'delta 0')."""
    total, prev = 0, None
    for v in values:
        v = int(v)
        if prev is not None:
            total += (v - prev) if v >= prev else v
        prev = v
    return total


def tooth_profile_analysis(bins, offset_x10, cylinders, mode):
    """The 60 per-mille bins of a '!K' profile -> the slowest crank angle.

    Bins are ENGINE angle / 6 (mod 360); physical = engine - trigger angle
    (tooth #1 deg ATDC, signed; a V96 trigOffsetX10 is the same mod 360). The
    fitted harmonic is the firing order's: cylinders/2 per revolution on a
    four-stroke. Returns rows for the CSV and the physical angle where the
    crank is slowest (compression TDC is at or just after it while
    cranking with spark and fuel off)."""
    off = ((offset_x10 or 0) / 10.0) % 360.0
    k = max(1, int(cylinders) // 2)
    rows, pts = [], []
    for b, v in enumerate(bins):
        eng = b * 6 + (off % 6)
        phys = (eng - off) % 360.0
        rows.append([b, round(eng, 1), round(phys, 1), v])
        if v:
            pts.append((phys, v))
    if len(pts) < 10:
        return {"rows": rows, "slowest_phys": float("nan"), "amplitude": 0.0,
                "tdc_note": "too few bins"}
    m = sum(v for _, v in pts) / len(pts)
    c = sum((v - m) * math.cos(math.radians(k * p)) for p, v in pts) * 2 / len(pts)
    s = sum((v - m) * math.sin(math.radians(k * p)) for p, v in pts) * 2 / len(pts)
    ph = (math.degrees(math.atan2(s, c)) / k) % (360.0 / k)
    note = ("TDC candidates (every %d deg) at physical ~%s; trigger angle "
            "(tooth #1 deg ATDC) for TDC#1 at one of them = %s (current %.1f)"
            % (360 // k,
               ", ".join("%.0f" % ((ph + 7.5 + i * 360.0 / k) % 360)
                         for i in range(k)),
               ", ".join("%.1f" % (((180.0 - (ph + 7.5 + i * 360.0 / k)) % 360)
                                   - 180.0) for i in range(k)),
               ((off + 180.0) % 360.0) - 180.0))
    return {"rows": rows, "slowest_phys": round(ph, 1),
            "amplitude": round(math.hypot(c, s), 1), "tdc_note": note}


# ============================================================ the summary ===
def summarize(cap: Capture) -> str:
    rows = cap.rows
    L = ["HaniCore vehicle capture summary", "=" * 60,
         "session   %s" % cap.dir, "generated %s" % utc()]
    ident = cap.meta.get("identity") or {}
    L += ["ECU       %s" % ident.get("version"),
          "signature %s" % ident.get("signature"),
          "ini       %s" % ident.get("ini"),
          "local build %s" % json.dumps(ident.get("local_build")),
          "page sha256 %s" % cap.meta.get("page_sha256"),
          "connects  %d, fast samples %d" % (len(cap.meta["connects"]),
                                             len(rows)), ""]
    pc = cap.meta.get("page_config") or {}
    if pc:
        L.append("--- configuration in the ECU at connect (page.bin) ---")
        for k in PAGE_FIELDS + PAGE_ARRAYS:
            if k in pc:
                L.append("  %-16s %s" % (k, pc[k]))
        L.append("")
    if not rows:
        L.append("NO SAMPLES WERE RECEIVED.")
        return "\n".join(L)

    for r in rows:                       # packed words: state in the low byte
        if r.get("fuelPumpState", "") != "":
            r["fuelPumpStateLo"] = int(r["fuelPumpState"]) & 0xFF

    def col(name, step=None):
        return [r[name] for r in rows if name in r and r[name] != ""
                and (step is None or r["step"] == step)]

    def rng(name, step=None, fmt="%.1f"):
        v = col(name, step)
        if not v:
            return "not received"
        return ("min " + fmt + "  max " + fmt + "  n %d") % (min(v), max(v), len(v))

    def delta(name, step=None):
        v = col(name, step)
        return counter_delta(v) if len(v) >= 2 else "n/a"

    steps = [s["step"] for s in cap.meta["steps"]]
    for st in ["wait"] + steps:
        n = len(col("rpm", st))
        if not n:
            continue
        L.append("--- step %s (%d samples) ---" % (st, n))
        for name in ("battDv", "battery", "rpm", "syncState", "mapKpaX10",
                     "cltDc", "cltCtrlDc", "cltRawAsic", "iatDc", "iatRawAsic",
                     "app1Raw", "app2Raw", "pedalX10", "pedal2X10",
                     "tps1Raw", "tps2Raw", "tpsX10", "tps2X10",
                     "dbwApp1X10", "dbwApp2X10",
                     "dbwTps1X10", "dbwTps2X10", "dbwTargetX10",
                     "dbwActualX10", "dbwState", "dbwFaults", "etbCalStatus",
                     "injPulse", "injTiUs", "dwellTime", "sparkAdvance",
                     "ignOnMask", "injOnMask", "outputAuthority",
                     "safetyInhibits", "schedulerMaxLatency",
                     "fuelPumpStateLo", "lambda1X1000", "lambda2X1000",
                     "sensorErr", "cfgValidation", "nvmState", "nvmSource"):
            if col(name, st):
                L.append("  %-14s %s" % (name, rng(name, st)))
        for name in ("asicTimeouts", "asicCsumErr", "asicSscErr",
                     "syncLossCount", "toothCorrections", "cycleSyncAcquired",
                     "cycleSyncLost", "camPhaseCorrections", "camPhaseNoAlt",
                     "crankEdges", "crankGaps",
                     "crankNoiseEdges", "schedulerExecuted", "schedulerLate",
                     "schedulerMissed", "schedulerCatchup", "schedOverdwell"):
            if col(name, st):
                L.append("  %-14s delta %s" % (name, delta(name, st)))
    L.append("")
    # V1.2: the start attempts, each over its own rows
    for a in cap.attempts:
        rr = rows[a["rows_from"]:a.get("rows_to", len(rows))]
        run = [r for r in rr if r.get("vstate") == "RUNNING"]
        crk = [r for r in rr if r.get("vstate") == "CRANKING"]
        L.append("--- attempt %d: %s ---" % (a["n"], a["outcome"] or "open"))
        if a["t_run"]:
            L.append("  crank -> running   %.2f s" % (a["t_run"] - a["t_crank"]))
        if crk:
            cr_ = [r["rpm"] for r in crk if r.get("rpm") not in (None, "")]
            b_ = [r["battDv"] for r in crk if r.get("battDv") not in (None, "")]
            if cr_:
                L.append("  cranking rpm       min %d max %d" % (min(cr_), max(cr_)))
            if b_:
                L.append("  battery cranking   min %.1f V" % min(b_))
        if a.get("stalls"):
            L.append("  crank stalls       %d samples with the crank standing "
                     "still (starter could not turn it over compression)"
                     % a["stalls"])
        if a["outcome"] == "NO_START_WEAK_BATTERY":
            L.append("  VERDICT            weak battery: the starter stalled at "
                     "compression; not an ECU no-start")
        if run:
            rp = [r["rpm"] for r in run if r.get("rpm") not in (None, "")]
            if rp:
                m_ = sum(rp) / len(rp)
                sd = (sum((x - m_) ** 2 for x in rp) / len(rp)) ** 0.5
                L.append("  running rpm        mean %.0f sd %.0f (%.1f %%) "
                         "min %d max %d over %d samples"
                         % (m_, sd, 100 * sd / m_ if m_ else 0, min(rp),
                            max(rp), len(rp)))
        for n in ("syncLossCount", "toothCorrections", "cycleSyncAcquired",
                  "cycleSyncLost", "schedulerExecuted", "schedulerLate",
                  "schedulerMissed", "schedOverdwell"):
            v = [r[n] for r in rr if r.get(n) not in (None, "")]
            if len(v) >= 2:
                L.append("  %-18s delta %d" % (n, counter_delta(v)))
        for n in ("camLowWidthX10", "camHighWidthX10"):
            v = sorted(set(r[n] for r in rr if r.get(n) not in (None, "", 0)))
            if v:
                L.append("  %-18s seen %s" % (n, v[:8]))
    for p in cap.profiles:
        L.append("--- tooth profile %d (mode %s, %s teeth, %s revs) ---"
                 % (p["n"], p["mode"], p["teeth"], p["revs"]))
        L.append("  slowest crank position  physical %.0f deg after the "
                 "gap-end tooth (fit amplitude %.1f per mille)"
                 % (p["slowest_phys"], p["amplitude"]))
        if p["mode"] == 1:
            L.append("  compression TDC is typically 0..15 deg after the "
                     "slowest point while cranking: %s" % p["tdc_note"])
    L.append("")
    # APP / TPS pair agreement where both tracks were present
    for a_, b_ in (("dbwApp1X10", "dbwApp2X10"), ("dbwTps1X10", "dbwTps2X10")):
        pa = [(r[a_], r[b_]) for r in rows if a_ in r and b_ in r]
        if pa:
            d = [abs(x - y) for x, y in pa]
            L.append("pair %s/%s: max |difference| %.1f, mean %.1f (raw units "
                     "of the channel; tracks may legitimately be mirrored - "
                     "compare with the calibration direction)"
                     % (a_, b_, max(d), sum(d) / len(d)))
    # crank
    cr = col("rpm", "crank")
    if cr:
        nz = [v for v in cr if v]
        L.append("crank rpm (non-zero samples): %s" % (
            "min %d mean %.0f max %d" % (min(nz), sum(nz) / len(nz), max(nz))
            if nz else "NO RPM SEEN DURING THE CRANK STEP"))
        b = col("battDv", "crank")
        if b:
            L.append("battery min during crank: %.1f V" % min(b))
    ev = []
    try:
        for ln in (cap.dir / "events.jsonl").read_text().splitlines():
            ev.append(json.loads(ln))
    except Exception:
        pass

    def first(kind):
        for e in ev:
            if e["event"] == kind:
                return e
        return None
    cs, rf, sy = (first("CRANK_START") or first("ATTEMPT_START")), \
        first("RPM_FIRST_SEEN"), first("SYNC_ACQUIRED")
    if cs and rf:
        L.append("crank start -> rpm seen: %.2f s" % (rf["t_mono"] - cs["t_mono"]))
    if cs and sy:
        L.append("crank start -> sync:     %.2f s" % (sy["t_mono"] - cs["t_mono"]))
    ko, off = first("KL15_OFF_SEEN"), (first("ECU_OFFLINE_AFTER_KEYOFF")
                                       or first("KEYOFF_ECU_SILENT"))
    if ko and off:
        L.append("KL15 off seen -> ECU silent: %.2f s (run-on)"
                 % (off["t_mono"] - ko["t_mono"]))
    for kind in ("ECU_RESET", "ECU_OFFLINE", "SIGNATURE_MISMATCH",
                 "GAVE_UP_WAITING"):
        n = sum(1 for e in ev if e["event"] == kind)
        if n:
            L.append("%s x %d" % (kind, n))
    bh = cap.meta.get("boot_history") or []
    if bh:
        recs = bh[-1]["records"]
        L.append("")
        L.append("--- boot history (the ECU's own ring, last %d boots) ---"
                 % len(recs))
        for r in recs:
            L.append("  boot %5d  %-20s prev lived %5d ms stage %3d runon %-16s "
                     "min %s V  KL15 at boot %s%s" % (
                         r["boot"], r["reset_kind"], r["prev_uptime_ms"],
                         r["prev_stage"], r["prev_runon"],
                         r["prev_min_batt_v"], "ON " if r["kl15_at_boot"]
                         else "OFF", "  (held power)" if r["prev_held_power"]
                         else ""))
        off = [r for r in recs if not r["kl15_at_boot"]]
        if off:
            L.append("  %d boot(s) started with KL15 OFF - a reset during/after "
                     "key-off (V93 never re-holds power on such a boot)"
                     % len(off))
    L += ["", "Values are what the ECU published; nothing here is a physical "
          "measurement of the car. decoded.csv: empty cell = not received."]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--port", default="auto",
                    help="COMx, or auto (default): every port but the rig")
    ap.add_argument("--baud", type=int, default=57600)
    ap.add_argument("--ini", default=None, help="override the auto-selected .ini")
    ap.add_argument("--out", default=None, help="evidence root (default "
                    "<HaniCore>\\evidence)")
    ap.add_argument("--auto", action="store_true",
                    help="no prompts: each step runs for its auto time")
    ap.add_argument("--steps", default=None,
                    help="comma list of: " + ",".join(s[0] for s in STEPS))
    ap.add_argument("--offline-wait", type=float, default=60.0,
                    help="seconds to wait for a lost ECU / key-off silence")
    ap.add_argument("--no-pedal", action="store_true",
                    help="skip the pedal steps (released/full/release/sweep)")
    a = ap.parse_args(argv)
    a.steps = a.steps.split(",") if a.steps else None
    q = queue.Queue()
    if not a.auto:
        def reader():
            for line in sys.stdin:
                q.put(line)
        threading.Thread(target=reader, daemon=True).start()
    cap = Capture(a, stdin_q=q)
    rc = 0
    try:
        cap.run()
    except KeyboardInterrupt:
        cap.say("interrupted - writing the summary")
        cap.event("INTERRUPTED")
        rc = 130
    finally:
        cap.meta["ended_utc"] = utc()
        cap.write_meta()
        s = summarize(cap)
        (cap.dir / "summary.txt").write_text(s, encoding="utf-8")
        print()
        print(s)
        for f in (cap.csv, cap.full_csv):
            if f:
                f[0].close()
        for f in (cap.console, cap.frames, cap.events):
            f.close()
        if cap.tr is not None:
            cap.tr.close()
    print("\nSession folder: %s" % cap.dir)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
