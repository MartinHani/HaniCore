#!/usr/bin/env python3
r"""
me711_vehicle_test.py - THE HaniCore vehicle diagnostic / flight recorder.

    py tools\vehicle\me711_vehicle_test.py --port COM2 --kline      link qualification
    py tools\vehicle\me711_vehicle_test.py --port COM2 --autocal    ETB direction / AutoCal
    py tools\vehicle\me711_vehicle_test.py --port COM2 --runtime    engine flight recorder
    py tools\vehicle\me711_vehicle_test.py --port COM2 --runtime --reduced   quarter rate
    py tools\vehicle\me711_vehicle_test.py --port COM2 --full       all three, in that order

    options: --baud 115200 (default)  --out <dir>  --duration <s> (runtime)
             --profile max (default) | reduced   the LOGGER LOAD profile (below)
             --direct (the KKL is already on the ECU's own K-line, not OBD)
             --no-prompt (never wait for ENTER; for scripted use)

Close TunerStudio first: one program per COM port.

WHY (the first V98r2 car session, 2026-10-02): the OBD K-line did not connect
(the KKL had to go on the ECU's own K-line), AutoCal failed "NOT A STOP A",
the engine died on a sharp throttle "as if the ignition were cut", lambda read
~1.04 whatever the fuel - and no log said why. This tool records what the
firmware DECIDED, with timestamps, in one session folder:

    <raw evidence folder>\<YYYY-MM-DD_HHMMSS>_vehicle_test\
        metadata.json   firmware identity, layout, port/baud, mode, the
                        LOGGING PROFILE with every group's channels, windows
                        and MEASURED rate, the operator-confirmed K-line
                        physical mode, and the page's whole engine
                        configuration (CONFIG_FIELDS / CONFIG_ARRAYS:
                        strategies, trigger, cam, lambda sources and heater
                        policy, DBW calibration, VE/ignition axes)
        summary.txt     per phase PASS / FAIL / WARNING and the reasons
        kline.csv       every exchange: path, stage, baud, latency, error
        fast.csv        the FAST group (the V100 channel list), every cycle
        medium.csv      the MEDIUM group (default every 0.5 s)
        slow.csv        the WHOLE output-channel block (default every 2.0 s)
        onchange.csv    one row per CHANGE of a rare state/config channel
        snapshots.csv   the whole block at session start, at every reconnect
                        and after every ECU reboot, with the reason
        autocal.csv     phase 2's own sample stream (V100: it used to share
                        fast.csv, and a later --full runtime phase then wrote
                        its own rows against phase 2's header)
        events.csv      the firmware's EVENT RING (hcevlog711.c), decoded
        trigger_events.csv / ignition_events.csv / injection_events.csv /
        etb_events.csv / etb_ring_events.csv / lambda_events.csv / faults.csv
                        the same events split by subject
        page.bin        the calibration page as read at connect
        page_boot<N>.bin  re-read after a reboot, written only if it differs
    Only the files a mode produces are written; everything is flushed as it
    is written, so a later phase failing (or Ctrl+C) loses nothing.

MAXIMUM OBSERVABILITY, NOT MAXIMUM BUS TRAFFIC (V100). The V99 recorder read
three hand-typed windows (160 B) as fast as the link allowed plus the whole
block twice a second. The rate was never the problem; the SELECTION was.
After the first car night half of what the diagnosis needed had never been on
a fast row, and the channels that settled a question sat in the 0.5 s stream.
V100 declares each group by CHANNEL NAME and derives its byte windows from
the .ini (`windows()`), coalescing windows less than GROUP_GAP bytes apart
because at 115200 one extra EXCHANGE costs about as much as 40 extra bytes
(V93 link timing: 4.5 ms + 0.12 ms/byte):

    FAST    GROUPS["fast"]   every cycle. Everything needed to reconstruct
                             dynamic behaviour: trigger/sync/cam/phase and
                             their error counters, the whole scheduler block
                             (executed/late/missed/maxLatency/cancelled),
                             requested timing, the ignition and injection
                             output masks, overdwell/skip/cancel counters,
                             injection width and strategy state, VE and load
                             with its source, throttle/pedal/ETB target,
                             actual, duty, direction and faults, fuel and
                             spark cuts, protection flags, battery.
    MEDIUM  GROUPS["medium"] every MEDIUM_S. Fuel corrections, warm-up,
                             after-start, cranking, ignition corrections,
                             published lambda, STFT, lambda validity, the raw
                             ADC channels, temperatures, MAP/baro, the
                             load-model internals, DBW deviation terms,
                             idle/boost/knock/VVT state machines.
    SLOW    the whole block  every SLOW_S. EVERY channel the firmware
                             publishes, so nothing is unrecorded: the
                             complete wideband chain (raw UA/UR, Ri, pump
                             current, heater duty and effective voltage,
                             lamWhy), CJ120 identity/status/errors/transfers,
                             reset/trap/vector/stack, the K-line counters,
                             NVM and config state, validation warnings,
                             scheduler aggregates, ASIC status.
    ON_CHANGE                the rare state/config channels, written to
                             onchange.csv on every CHANGE - so they are
                             caught at the moment they move without costing
                             fast bandwidth.
    SNAPSHOT                 the whole block (and the page, if it changed) at
                             start, at every reconnect and after every reboot.
    RING                     every RING_S, and the PROFILE DOES NOT CHANGE IT:
                             the firmware's own event ring is the only
                             high-resolution record that exists, and starving
                             it is exactly how events are lost.

D3 - DOES THE LOGGER MAKE THE SCHEDULER WORSE? `--profile reduced` keeps
every group and the ring but runs the polled streams at about a quarter rate.
Two runtime captures at the same engine condition, one `--profile max` and
one `--profile reduced`, are what answer it. The profile and the MEASURED
rates are in metadata.json, and
`me711_log_analyze.py --compare <A> <B>` prints the comparison.

THE PHASES (--full runs 1 -> 2 -> 3):
  1 K-LINE   passive listen (another module talking?), direct probe at the
             baud, then the VAG/KWP cold init (5-baud 0x01, sync/keybytes,
             StartCommunication, IDENTIFY, GOFAST) - the first failing STAGE
             is recorded. If the OBD path fails it says so and waits for the
             KKL to go on the ECU's own K-line, then tests that path in the
             same session. Connected: latency, a read-rate soak, malformed
             replies, a port reconnect and an optional key-cycle reconnect.
  2 AUTOCAL  engine stopped: direction A and B to their stops ('!C4'/'!C5'),
             "Calibrate TPS endpoints" ('!C1'), "PID Autotune" ('!C2') and
             "AutoCal ETB" ('!C3'), each logged at ~30 rows/s with the
             decision numbers (hold/push/limit/moved). It WRITES endpoints and
             gains to the RAM page exactly as the TunerStudio buttons do -
             nothing is burned. No pedal test: the pedal is qualified.
  3 RUNTIME  key-on -> crank -> sync -> run -> stop, until ENTER/Ctrl+C or
             --duration: fast + slow + the event ring (sync, phase, cuts and
             their reasons, overdwell, limiter, ETB, lambda state/dynamics,
             link errors). K-line drops are retried and recorded.

Run tools\vehicle\me711_log_analyze.py <session folder> for the automatic analysis
(this tool runs it at the end), and
tools\vehicle\me711_log_analyze.py --compare <session A> <session B> for the
scheduler-load comparison between two runtime captures.
"""
from __future__ import annotations

import argparse
import binascii
import csv
import datetime as dt
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_vehicle_capture as VC        # noqa: E402  (Ini, pick_ini, ...)

TOOL_VERSION = "2.0 (V100 multi-rate)"
RATE_CODE = {10400: 0x01, 57600: 0x02, 124800: 0x03, 115200: 0x04}
EXT_RING = 344 + 120 + 168        # the ring follows LF, tooth profile, boots
EV_HDR, EV_REC = 16, 10

# ======================================================= V100: the groups ==
# Declared by CHANNEL NAME; `windows()` derives the byte windows from the
# .ini, so no offset is ever typed here and a channel that moves in a later
# layout follows its name. A name the .ini does not declare is recorded in
# metadata as unavailable (`missing`) and simply not read - which is what
# makes this list safe to keep ahead of the firmware.
GROUP_GAP = 48        # merge two windows less than this many bytes apart
PAGE_SNAP_MIN_S = 10.0   # a snapshot re-reads the page at most this often

GROUPS = {
    # ---- FAST: what reconstructing dynamic engine behaviour needs --------
    "fast": """
        rpm RPMValue syncState crankSync cycleSync crankPhase crankToothIndex
        crankGapDetected crankGapPending crankRevolutions crankNoiseEdges
        lastToothPeriod crankPeriod enginePositionDeg stallState
        syncLossCount syncLossReason cycleSyncAcquired cycleSyncLost
        toothCorrections camError camSyncLossReason cam1Raw cam2Raw
        cam1Tooth cam2Tooth cam1Window cam2Window camWindowOkCount
        camPhaseStatus camPhaseNoAlt camPhaseCorrections
        advX10 ignitionTiming ignTableTiming sparkAdvance dwellX100 coilDwell
        ignOnMask injOnMask outDriveCalls outputAuthority safetyInhibits
        schedulerQueued schedulerExecuted schedulerCancelled schedulerLate
        schedulerMissed schedulerMaxLatency schedulerPending schedulerStatus
        schedulerCatchup schedulerCaptureOverflow schedulerNextAngle
        schedulerLastAngle schedOverdwell schedOverdwellLatch sparkSkips
        nextIgnSlot nextInjSlot scheduledDwellStart scheduledSpark
        scheduledInjStart scheduledInjEnd syncSeq
        injTiUs injectorPulseWidth injWidthUs injDutyX10 injectorDuty
        injPhase seqActive seqInjMask seqSkips seqEnters seqLeaves
        veValue engLoad fuelLoad ignLoad airMass rlX10 airMgX10 lambdaTarget
        tpsX10 tps2X10 TPSValue pedalX10 pedal2X10 pedalPosition
        etbTarget etbActual dbwState dbwFaults dbwPendFaults dbwTargetX10
        dbwActualX10 dbwErrorX10 dbwDutyX10 dbwInteg dbwOutRaw
        dbwApp1X10 dbwApp2X10 dbwTps1X10 dbwTps2X10 dbwSfLevel
        fuelCut fuelCutFlags limpCut sensorErr sensorFlags engineFlags
        VBatt ecuMs evSeq evRingSize lamDyn tpsSampleAgeMs asicSampleAgeMs
        etbCalStatus etbHold1 etbPush1 etbStopLimit etbStopMoved etbStopDisp
    """.split(),
    # ---- MEDIUM: everything that settles in tenths of a second ----------
    "medium": """
        adc00_HFM adc01_TPS1 adc02_IPV adc03_TPS2 adc04_LS2VK adc05_UBAT
        adc06_LS1VK adc07_LS1HK adc08_PEDAL1 adc09_PEDAL2 adc10_LS2HK
        adc11_AUX11 adc12_DMTL adc13_HFM2 adc14_DSS adc15_KNOCK
        battDv cltDc iatDc mapKpaX10 mapControl coolant intake cltCtrlDc
        warmupPct warmupEnrich afterStartPm primeState aeFuelUs fuelCorrection
        transWantUs transCorrUs transBaseUs wallFilmUs wallAlphaPm
        injCycleUs injDeadUs injNoFree
        ignCorrX10 ignCorrection idleTimingX10 knockRetardX10 knockRetardMax
        lambdaValue lambda2Value targetLambda targetAfr afrX10 lambdaLoad
        lambda1X1000 lambda2X1000 lambdaStatus lamWhy lamSpan2 lamFault
        lamAcqFlags lamAckModes
        stftBank1 stftBank2 stftState
        veLoadX10 dbwTermP dbwTermD dbwTermFf dbwBattFactor dbwPendMs
        dbwSteps etbVfySettleMs etbVfyOverX10 etbVfyErrX10 etbVfyStep
        dbwFaultClears etbProc etbDrive etbPhaseMs
        idleFloorX10 idleTrimX10 idleTargetRpm idleState idleTarget
        boostState boostCmdX10 boostReqX10 boostTargetX10 boostDuty boostCuts
        motorsportState revLimitNow fuelPumpState fuelPumpReason
        dtcMil dtcActiveN celState cjErr cjTmo
        knockState knockWindows knockLate knockStale knockSelFault knockCount
        knockFlags vvt1State vvt1Err vvt2State vvt2Err switchRaw
    """.split(),
}

# Rare state/config channels: written to onchange.csv whenever they MOVE, so
# they need no polling bandwidth to be caught at the moment they move. They
# are compared on the SLOW row, which carries the whole block.
ON_CHANGE = """
    status bootStage cfgSource ramBad s0rTrap probeBad badVec firstVec lastVec
    asicState asicClassErr asicCsumErr asicTimeouts asicSscErr
    cfgValidation cfgWarnings cfgDesiredRev cfgActiveRev cfgApplyRefused
    cfgStateBits cfgRouteMismatch cfgFirstBadOffset cfgFirstBadSlot
    cfgDirtyGroups cfgFaults
    nvmState nvmError nvmSource nvmGeneration nvmCommits nvmFailWord
    nvmProgFlags nvmEraseState nvmReclaims nvmFreeCells lkgSteps
    rstBootCount rstRawReset rstCurrentTrap rstPreviousTrap stackPeak
    releaseId targetId outputPins mainRelayMode mainRelayCommand
    mainRelayFbState mainRelayMismatch mainRelayBound runOn runOnCount
    fuelPumpState fuelPumpReason powerNl
    trigCfgTeeth trigCfgGap trigCfgRatio trigCfgMinTeeth trigCfgToothX10
    trigCfgAngleX10 trigCfgCamRefs trigCfgCamRefX10 trigCfgCamWindowX10
    trigCfgCrankEdge trigCfgCamEdge trigCamResolves trigCfgGeneration
    trigCfgCaptureMap triggerCaptureArmed
    lambdaStatus lamWhy lamFault lamMode lamVeff cj120Ident cj120Reg1
    cj120Diag cjErr cjTmo
    dbwState dbwFaults dbwPendFaults etbProc etbCalStatus
    limpCut fuelCut fuelCutFlags sensorErr sensorFlags
    dtcMil dtcActive1 dtcActive2 dtcActive3 dtcActive4 celState switchRaw
    knockSelFault knockCodes vvt1State vvt2State toothLogState presetResult
    linkState kwpState linkDiag seqActive stftState primeState
""".split()

# ---------------------------------------------------- the logging profiles --
# A period of 0 means "as often as the link allows".  The RING period is the
# same in both profiles on purpose (see the docstring).
PROFILES = {
    "max": {"fast": 0.0, "medium": 0.5, "slow": 2.0, "ring": 0.2},
    # about a quarter of the polled rate measured in the V99 car sessions
    # (9.4 Hz fast, 1.8 Hz slow) with the ring untouched - the D3 contrast.
    "reduced": {"fast": 0.4, "medium": 2.0, "slow": 8.0, "ring": 0.2},
}


def windows(ini, names, block, gap=GROUP_GAP):
    """(windows, missing): the byte windows that cover `names`, coalesced.

    An extra exchange costs about 40 bytes of wire time at 115200, so two
    windows closer than `gap` are merged rather than read separately."""
    spans, missing = [], []
    for n in names:
        s = ini.scalars.get(n)
        if s is None:
            missing.append(n)
            continue
        off, end = s[1], s[1] + VC.SIZES[s[0]]
        if end <= block:
            spans.append((off, end))
        else:
            missing.append(n)
    spans.sort()
    out = []
    for a, b in spans:
        if out and a - out[-1][1] <= gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b - a) for a, b in out], missing

# ------------------------------------------------- the firmware's words ---
EV_NAMES = {1: "BOOT", 2: "SYNC", 3: "SYNC_LOSS", 4: "CYCLE", 5: "PHASE_CORR",
            6: "ENGINE", 7: "FLAGS", 8: "FUELCUT", 9: "OVERDWELL",
            10: "SPARK_SKIP", 11: "SCHED_MISSED", 12: "SEQ", 13: "ETB",
            14: "DBW", 15: "LAMBDA", 16: "LIMP", 17: "LAMDYN", 18: "KLINE"}
# V100: the ring split by SUBJECT, so a question has one file to open. `etb`
# is spelled `etb_ring` because `etb_events.csv` is phase 2's own procedure
# log; `faults` is the one file without the `_events` suffix (V99 name kept).
EV_FILE = {"SYNC": "trigger", "SYNC_LOSS": "trigger", "CYCLE": "trigger",
           "PHASE_CORR": "trigger", "ENGINE": "trigger",
           "SEQ": "injection",
           "FLAGS": "ignition", "OVERDWELL": "ignition",
           "SPARK_SKIP": "ignition", "SCHED_MISSED": "ignition",
           "BOOT": "faults", "FUELCUT": "faults", "LIMP": "faults",
           "ETB": "etb_ring", "DBW": "etb_ring",
           "LAMBDA": "lambda", "LAMDYN": "lambda", "KLINE": "kline_ring"}
SYNC_STATE = {0: "NO SIGNAL", 1: "COUNTING", 2: "GAP SEEN", 3: "CRANK SYNC",
              4: "FULL 720 SYNC"}
LOSS = {0: "-", 1: "stall", 2: "early gap", 3: "missing gap",
        4: "malformed gap", 5: "extra edge", 6: "cam window", 7: "cam missing",
        8: "cam level did not alternate", 9: "cam level contradicted the half"}
FUEL_CUT = {1: "overrun (DFCO)", 2: "rev limiter", 4: "overboost",
            8: "engine protection"}
LIMP = {1: "coolant rev limit", 2: "THROTTLE FAULT rev limit (1500 rpm)",
        4: "oil pressure", 8: "injector duty", 16: "flood clear"}
FLAGS = {32: "DFCO", 512: "fuel cut", 1024: "launch", 2048: "flat shift",
         4096: "anti-lag", 8192: "REV LIMIT", 16384: "MAP estimate"}
DBW_STATE = {0: "OFF", 1: "INIT", 2: "RUN", 3: "FAULT"}
DBW_FAULT = {1: "calibration", 2: "pedal pair", 4: "throttle pair",
             8: "pedal range", 16: "throttle range", 32: "bridge SF",
             64: "OFF TARGET TOO LONG", 128: "no sensor source",
             256: "outputs not live"}
KLINE_CTR = {0: "resync", 1: "hw overrun", 2: "framing", 3: "ring overflow",
             4: "echo lost"}
ENGINE = {0: "STOPPED", 1: "CRANKING", 2: "RUNNING"}


def bits(v, table):
    return ", ".join(n for b, n in table.items() if v & b) or "none"


def utc():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def envelope(payload: bytes) -> bytes:
    return (len(payload).to_bytes(2, "big") + payload
            + (binascii.crc32(payload) & 0xFFFFFFFF).to_bytes(4, "big"))


# ================================================================ the port ==
class SerialPort:
    """The KKL. Every method the tool needs and nothing else, so a test can
    replace it (tests/unit/me711_vehicle_test_test.py FakeEcu)."""

    def __init__(self, name: str, baud: int):
        import serial
        self.name = name
        self.ser = serial.Serial(name, baud, timeout=0.002, write_timeout=2.0)

    @property
    def baud(self):
        return self.ser.baudrate

    def set_baud(self, b):
        self.ser.baudrate = b

    def write(self, data: bytes):
        self.ser.write(data)

    def read(self, n: int, timeout: float) -> bytes:
        got = bytearray()
        end = time.perf_counter() + timeout
        while len(got) < n and time.perf_counter() < end:
            part = self.ser.read(max(1, min(self.ser.in_waiting, n - len(got))))
            if part:
                got.extend(part)
        return bytes(got)

    def reset_input(self):
        self.ser.reset_input_buffer()

    def five_baud(self, addr: int):
        """The ISO 9141 / KWP2000 5-baud address: 10 bits of 200 ms."""
        self.set_baud(10400)
        bitsq = [0] + [(addr >> i) & 1 for i in range(8)] + [1]
        t = time.perf_counter()
        for i, b in enumerate(bitsq):
            self.ser.break_condition = (b == 0)
            t_next = t + (i + 1) * 0.2
            while time.perf_counter() < t_next:
                time.sleep(0.001)
        self.ser.break_condition = False
        self.reset_input()

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


# =========================================================== the session ==
class Session:
    """The folder, the console, the CSV writers - one per run."""

    def __init__(self, out: Path, quiet=False):
        self.dir = out
        out.mkdir(parents=True, exist_ok=True)
        self.t0 = time.monotonic()
        self.quiet = quiet
        self._w = {}
        self._f = {}
        self._hdr = {}
        self.summary = []
        self.meta = {"tool": "me711_vehicle_test", "tool_version": TOOL_VERSION,
                     "started_utc": utc(), "phases": {}}
        self._con = open(out / "console.log", "a", encoding="utf-8")

    def t(self):
        return round(time.monotonic() - self.t0, 4)

    def say(self, s=""):
        line = "[%8.2f] %s" % (self.t(), s) if s else ""
        if not self.quiet:
            print(line, flush=True)
        self._con.write(line + "\n")
        self._con.flush()

    def writer(self, name, header):
        if name not in self._w:
            f = open(self.dir / (name + ".csv"), "w", newline="",
                     encoding="utf-8")
            w = csv.writer(f)
            w.writerow(header)
            self._f[name], self._w[name] = f, w
            self._hdr[name] = list(header)
        elif self._hdr.get(name) != list(header):
            # V100: two producers wrote fast.csv with DIFFERENT headers (phase
            # 2 opened it, phase 3 then wrote its own values against phase 2's
            # columns), so a --full session's fast.csv was silently shifted.
            # The producers are separate files now; this says so if it recurs.
            k = "csv_header_conflict"
            self.meta.setdefault(k, []).append(name)
            self.say("INTERNAL: %s.csv written with a second header - the "
                     "columns of those rows do not match" % name)
            self._hdr[name] = list(header)
        return self._w[name]

    def row(self, name, header, values):
        w = self.writer(name, header)
        w.writerow(values)
        self._f[name].flush()

    def save_meta(self):
        (self.dir / "metadata.json").write_text(json.dumps(self.meta, indent=1,
                                                           default=str))

    def verdict(self, phase, status, text):
        self.summary.append((phase, status, text))
        self.say("%s: %s - %s" % (phase, status, text))
        self.write_summary()

    def write_summary(self):
        lines = ["HaniCore vehicle test %s" % self.dir.name,
                 "tool %s, started %s" % (TOOL_VERSION, self.meta["started_utc"]),
                 ""]
        ident = self.meta.get("identity") or {}
        if ident:
            lines += ["firmware: %s" % ident.get("version"),
                      "signature: %s" % ident.get("signature"),
                      "image: %s" % (ident.get("build") or {}).get("sha256"), ""]
        for ph, st, tx in self.summary:
            lines.append("%-8s %-8s %s" % (ph, st, tx))
        (self.dir / "summary.txt").write_text("\n".join(lines) + "\n",
                                              encoding="utf-8")

    def close(self):
        for f in self._f.values():
            f.close()
        self.save_meta()
        self.write_summary()
        self._con.close()


# ================================================================ the link ==
class Link:
    """TunerStudio-protocol exchanges over the K-line: echo stripped, every
    exchange logged to kline.csv with its path/stage, latency and error."""

    def __init__(self, port, sess: Session, path="?"):
        self.p = port
        self.s = sess
        self.path = path
        self.stage = "-"
        self.stats = {"ok": 0, "err": 0, "retries": 0, "crc": 0, "timeout": 0,
                      "code": 0, "noecho": 0}

    def log(self, cmd, ok, err, ms, nbytes, attempt=1):
        self.s.row("kline", ["t", "path", "stage", "baud", "cmd", "ok", "error",
                             "latency_ms", "bytes", "attempt"],
                   [self.s.t(), self.path, self.stage, self.p.baud, cmd,
                    int(ok), err or "", round(ms, 2), nbytes, attempt])

    def exchange(self, payload: bytes, timeout=0.5, attempt=1):
        req = envelope(payload)
        self.p.reset_input()
        t0 = time.perf_counter()
        self.p.write(req)
        buf = bytearray()
        end = t0 + timeout
        need = None
        body, err = None, None
        while time.perf_counter() < end:
            part = self.p.read(4096, 0.005)
            if part:
                buf.extend(part)
            data = bytes(buf)
            if data.startswith(req):
                data = data[len(req):]
            elif len(data) < len(req) and req.startswith(data):
                continue
            if len(data) >= 2 and need is None:
                need = 2 + ((data[0] << 8) | data[1]) + 4
            if need is not None and len(data) >= need:
                n = (data[0] << 8) | data[1]
                blob = data[2:2 + n]
                crc = int.from_bytes(data[2 + n:6 + n], "big")
                if crc != (binascii.crc32(blob) & 0xFFFFFFFF):
                    err = "crc"
                elif not blob or blob[0] != 0:
                    err = "code 0x%02X" % (blob[0] if blob else 0xFF)
                else:
                    body = blob[1:]
                break
        else:
            if not buf:
                err = "timeout: no bytes"
            elif bytes(buf) == req:
                err = "timeout: echo only, no reply"
            else:
                err = "timeout: %d bytes" % len(buf)
        ms = (time.perf_counter() - t0) * 1000.0
        if body is None:
            self.stats["err"] += 1
            k = "crc" if err == "crc" else ("code" if err.startswith("code")
                                            else "timeout")
            self.stats[k] += 1
        else:
            self.stats["ok"] += 1
        self.log(payload[:1].decode("latin1"), body is not None, err, ms,
                 len(buf), attempt)
        return body, err, ms

    def request(self, payload, timeout=0.5, retries=2):
        for a in range(1, retries + 2):
            body, err, ms = self.exchange(payload, timeout, a)
            if body is not None:
                return body, None, ms
            self.stats["retries"] += 1
        return None, err, ms

    def text(self, cmd: bytes, tries=1):
        body, err, _ = self.request(cmd, 0.6, tries - 1)
        if body is None:
            return None
        return body.split(b"\0")[0].decode("latin1", "replace").strip()

    def och(self, off, cnt, retries=1):
        body, err, ms = self.request(b"O" + off.to_bytes(2, "big")
                                     + cnt.to_bytes(2, "big"),
                                     0.3 + cnt / 5000.0, retries)
        if body is not None and len(body) != cnt:
            return None, "length %d != %d" % (len(body), cnt), ms
        return body, err, ms

    def page(self, size=4096, chunk=256):
        out = bytearray()
        for off in range(0, size, chunk):
            body, err, _ = self.request(b"R" + off.to_bytes(2, "big")
                                        + chunk.to_bytes(2, "big"), 1.0, 2)
            if body is None or len(body) != chunk:
                return None
            out.extend(body)
        return bytes(out)

    def command(self, payload: bytes):
        """A ControllerCommand ('!...'), as TunerStudio sends it."""
        body, err, _ = self.request(payload, 0.6, 2)
        return body is not None


# ======================================================= 1. the K-line ===
class Kline:
    """Phase 1. -> (link or None, result dict)."""

    # V100: THE PHYSICAL CONNECTION IS NOT THE SOFTWARE PATH.
    #
    # V99 set first_path from the --direct FLAG alone. During the 2026-10-02
    # car session the OBD attempt failed, the operator physically moved the
    # KKL to ECU cavity 43 as the script asked, and never moved it back - so
    # every LATER session, run without --direct, probed over a cable that was
    # still on cavity 43 and recorded "OBD path PASS". The vehicle OBD K-line
    # in fact connected ZERO times that night
    # (corrected 2026-10-03).
    #
    # So the physical mode is now operator-confirmed, remembered beside the
    # session folders (one evidence tree, one memory - a fresh tree starts
    # clean), and reported separately from the software path that was
    # attempted. Nothing may claim OBD unless a human says the cable is on
    # OBD in THIS session.
    STATE = ".me711_kline_physical"

    def __init__(self, sess, open_port, baud, ask, direct=False,
                 confirm=None, state_dir=None):
        self.s, self.open_port, self.baud, self.ask = sess, open_port, baud, ask
        self.confirm = confirm
        self.state = (Path(state_dir) / self.STATE) if state_dir else None
        self.phys_src = "--direct flag" if direct else None
        self.phys = "DIRECT ECU" if direct else self._remembered()
        self.transitions = []
        self.first_path = self.phys

    def _remembered(self):
        """The last operator-confirmed mode, or OBD if nothing is known."""
        try:
            v = self.state.read_text(encoding="utf-8").strip()
        except Exception:
            v = ""
        if v in ("OBD", "DIRECT ECU"):
            self.phys_src = "remembered from the last session"
            return v
        self.phys_src = "assumed (nothing remembered)"
        return "OBD"

    def _remember(self, mode):
        self.phys = mode
        try:
            if self.state:
                self.state.write_text(mode, encoding="utf-8")
        except Exception:
            pass

    def confirm_physical(self):
        """Ask the operator what the KKL is actually plugged into."""
        if self.phys_src == "--direct flag":
            self.s.say("KLINE: physical connection DIRECT ECU (--direct)")
            return
        if self.confirm is None:
            self.s.say("KLINE: physical connection %s - %s (NOT CONFIRMED)"
                       % (self.phys, self.phys_src))
            return
        m = self.confirm(self.phys)
        self.phys_src = "operator confirmed"
        if m != self.phys:
            self.transitions.append({"t": self.s.t(), "from": self.phys,
                                     "to": m, "why": "operator confirmed"})
        self._remember(m)
        self.first_path = m
        self.s.say("KLINE: physical connection %s (operator confirmed)" % m)

    def listen(self, port, label, seconds=1.0):
        port.reset_input()
        got = port.read(4096, seconds)
        self.s.row("kline", ["t", "path", "stage", "baud", "cmd", "ok", "error",
                             "latency_ms", "bytes", "attempt"],
                   [self.s.t(), label, "passive listen", port.baud, "-",
                    int(not got), ("%d bytes heard: %s" % (len(got),
                                                          got[:24].hex()))
                    if got else "", seconds * 1000, len(got), 1])
        return got

    def direct_probe(self, link, tries=8):
        link.stage = "direct probe"
        for n in range(1, tries + 1):
            body, err, ms = link.exchange(b"S", 0.35, n)
            if body is not None:
                return n, body.split(b"\0")[0].decode("latin1", "replace")
            time.sleep(0.05)
        return None, None

    def kwp(self, link, rate):
        """The VAG/KWP2000 vehicle entry. -> (stage reached, failure text)"""
        p = link.p
        r = {"rate": rate}
        link.stage = "kwp 5-baud init"
        p.five_baud(0x01)
        sync = p.read(3, 0.8)
        r["sync"] = sync.hex()
        if not sync:
            return "NO INIT RESPONSE", "no sync byte after the 5-baud address 0x01", r
        if sync != b"\x55\xEF\x8F":
            return "BAD KEYBYTES", "sync/keybytes %s (want 55ef8f)" % sync.hex(), r
        link.stage = "kwp keybyte complement"
        p.write(b"\x70")
        echo = p.read(1, 0.3)
        fe = p.read(1, 0.3)
        r["complement"] = fe.hex()
        if fe != b"\xFE":
            return "NO COMPLEMENT", "ECU complement %r (want fe), echo %r" % (
                fe.hex(), echo.hex()), r

        def kwp_req(data, stage, timeout=0.5):
            link.stage = stage
            f = bytes([0x80 | len(data), 0x01, 0xF1]) + data
            f += bytes([sum(f) & 0xFF])
            t0 = time.perf_counter()
            p.write(f)
            e = p.read(len(f), 0.3)
            h = p.read(1, timeout)
            if not h:
                link.log(stage, False, "timeout (echo %s)" % ("ok" if e == f
                                                               else e.hex()),
                         (time.perf_counter() - t0) * 1e3, len(e))
                return None
            n = h[0] & 0x3F
            rest = p.read(2 + n + 1, 0.3)
            fr = h + rest
            ok = len(fr) == 3 + n + 1 and (sum(fr[:-1]) & 0xFF) == fr[-1]
            link.log(stage, ok, None if ok else "bad frame %s" % fr.hex(),
                     (time.perf_counter() - t0) * 1e3, len(fr))
            return fr[3:3 + n] if ok else b""

        d = kwp_req(b"\x81", "kwp StartCommunication")
        if not d or d[0] != 0xC1:
            return "STARTCOMM FAILED", "StartCommunication reply %r" % (
                d.hex() if d is not None else None), r
        d = kwp_req(b"\xB0HC", "kwp IDENTIFY")
        if not d or d[0] != 0xF0:
            return "IDENTIFY FAILED", "IDENTIFY reply %r" % (
                d.hex() if d is not None else None), r
        r["identify"] = d[1:].decode("latin1", "replace")
        d = kwp_req(bytes([0xB1, RATE_CODE.get(rate, 0x02)]), "kwp GOFAST")
        if not d or d[0] != 0xF1:
            return "GOFAST FAILED", "GOFAST reply %r" % (
                d.hex() if d is not None else None), r
        p.set_baud(rate)
        link.stage = "after GOFAST"
        n, sig = self.direct_probe(link, 6)
        if not n:
            return "TIMEOUT AFTER TRANSITION", ("no CRC-valid reply at %d after "
                                                "GOFAST" % rate), r
        r["signature"] = sig
        return "OK", "", r

    def attempt(self, path):
        """One physical path. -> (link or None, dict)."""
        res = {"path": path, "stage": "PORT", "detail": ""}
        try:
            port = self.open_port(self.baud)
        except Exception as e:
            res.update(stage="PORT OPEN FAILED", detail=str(e))
            return None, res
        link = Link(port, self.s, path)
        heard = self.listen(port, path, 1.0)
        res["bus_activity_bytes"] = len(heard)
        if heard:
            self.s.say("KLINE: %s path - %d bytes heard on an idle bus "
                       "(another module is talking?)" % (path, len(heard)))
        n, sig = self.direct_probe(link)
        if n:
            res.update(stage="OK", how="direct %d baud" % self.baud,
                       attempts=n, signature=sig)
            return link, res
        res["direct_probe"] = "no reply at %d baud" % self.baud
        self.s.say("KLINE: %s path - no reply to a direct probe at %d; "
                   "trying the VAG/KWP cold init" % (path, self.baud))
        stage, why, r = self.kwp(link, self.baud)
        res.update(kwp=r, stage=stage, detail=why)
        if stage == "OK":
            res["how"] = "KWP 5-baud -> GOFAST %d" % self.baud
            return link, res
        port.close()
        return None, res

    def quality(self, link: Link, block: int, fast=(1136, 112)):
        """Latency, read-rate soak, malformed replies, reconnect."""
        q = {}
        link.stage = "latency"
        lat = []
        for _ in range(20):
            body, err, ms = link.exchange(b"S", 0.4)
            if body is not None:
                lat.append(ms)
        lat.sort()
        q["latency_ms"] = {"n": len(lat), "min": lat[0] if lat else None,
                           "median": lat[len(lat) // 2] if lat else None,
                           "max": lat[-1] if lat else None}
        link.stage = "read soak"
        off, cnt = fast if fast[0] + fast[1] <= block else (0, min(112, block))
        st0 = dict(link.stats)
        t0 = time.perf_counter()
        good = 0
        for _ in range(100):
            body, err, ms = link.och(off, cnt, retries=0)
            good += body is not None
        el = time.perf_counter() - t0
        q["soak"] = {"reads": 100, "good": good, "rows_per_s": round(good / el, 1),
                     "bytes_per_read": cnt,
                     "crc_errors": link.stats["crc"] - st0["crc"],
                     "timeouts": link.stats["timeout"] - st0["timeout"],
                     "error_codes": link.stats["code"] - st0["code"]}
        link.stage = "reconnect"
        port = link.p
        b = port.baud
        port.close()
        t0 = time.perf_counter()
        try:
            link.p = self.open_port(b)
            n, sig = self.direct_probe(link, 8)
        except Exception:
            n = None
        q["reconnect"] = {"ok": bool(n), "attempts": n,
                          "ms": round((time.perf_counter() - t0) * 1e3, 1)}
        return q

    def keycycle(self, link: Link):
        if not self.ask("Key-cycle reconnect test: turn ignition OFF now and "
                        "press Enter (s + Enter skips)", allow_skip=True):
            return {"skipped": True}
        link.stage = "key off"
        body, err, _ = link.exchange(b"S", 0.5)
        off_answer = body is not None
        if not self.ask("Turn ignition ON now and press Enter", allow_skip=False):
            return {"skipped": True}
        link.stage = "key on reconnect"
        t0 = time.perf_counter()
        n, sig = None, None
        for _ in range(10):
            n, sig = self.direct_probe(link, 6)
            if n:
                break
        how = "direct"
        if not n:
            stage, why, r = self.kwp(link, link.p.baud)
            n = 1 if stage == "OK" else None
            how = "kwp: %s %s" % (stage, why)
        return {"answered_with_key_off": off_answer, "ok": bool(n), "how": how,
                "ms": round((time.perf_counter() - t0) * 1e3, 1)}

    def run(self, block_hint=1248, quality=True):
        out = {}
        link, r1 = self.attempt(self.first_path)
        out[self.first_path] = r1
        if link is None:
            if self.first_path == "OBD":
                self.s.say("")
                self.s.say("OBD K-LINE CONNECTION FAILED (stage: %s%s)" % (
                    r1["stage"], (" - " + r1["detail"]) if r1.get("detail") else ""))
                self.s.say("")
                if self.ask("Connect the KKL directly to the ECU K-line "
                            "(cavity 43), then press Enter to continue",
                            allow_skip=True):
                    # V100: the cable physically moved - record it, and
                    # REMEMBER it, so the next session does not silently
                    # call this same wiring "OBD" again.
                    self.transitions.append(
                        {"t": self.s.t(), "from": "OBD", "to": "DIRECT ECU",
                         "why": "OBD failed; operator moved the KKL to "
                                "cavity 43"})
                    self._remember("DIRECT ECU")
                    self.phys_src = "operator moved it during this session"
                    link, r2 = self.attempt("DIRECT ECU")
                    out["DIRECT ECU"] = r2
        for path, r in out.items():
            st = "PASS" if r["stage"] == "OK" else "FAIL"
            self.s.say("KLINE: %s path %s%s" % (
                path, st, "" if st == "PASS" else " - stage %s: %s"
                % (r["stage"], r.get("detail", ""))))
        # V100: what the CABLE was, beside what the software attempted
        out["physical"] = {"mode": self.phys, "source": self.phys_src,
                           "transitions": self.transitions}
        self.s.say("KLINE: physical path %s (%s)%s"
                   % (self.phys, self.phys_src,
                      "" if self.phys_src == "operator confirmed"
                      else " - TREAT THE PATH LABEL WITH CARE"))
        if link is not None and quality:
            out["quality"] = self.quality(link, block_hint)
            out["keycycle"] = self.keycycle(link)
        return link, out


# ============================================================ helpers ====
# V100: THE SESSION MUST CARRY THE CONFIGURATION IT RAN WITH, so that nothing
# afterwards depends on a TunerStudio screenshot or on what the operator
# remembers. Every field listed here is decoded from page.bin through the
# .ini's own [Constants] and lands in metadata.json "engine_config"; a `bits`
# field is stored both as its label and (under "_name") as its raw index, so
# an analyser can test it without matching prose.
CONFIG_FIELDS = (
    # identity / engine
    "enginePreset", "cylinders", "displacementCc", "firingOrder",
    # fuel and ignition strategy
    "injStrategy", "ignStrategy", "injTimingMode", "timingModeCfg",
    "fixedTimingX10", "injFlowCcMin", "dwellMsX100", "revLimit", "revlimMode",
    "loadSource", "ignLoadSource", "alphaNUseIat", "stftEnable",
    # trigger, sync and cam
    "trigSource", "trigAngleX10", "syTeeth", "syGap", "syncMode",
    "camPhaseMode", "camPhaseLevel", "camPhaseAngleX10", "cam1Pattern",
    "cam2Pattern", "trigCfgCaptureMap",
    # lambda
    "lambda1Source", "lambda2Source", "lambdaHeatPolicy",
    # throttle / DBW
    "dbwEnable", "dbwMotorDir", "dbwMaxDutyX10", "dbwDevX10", "dbwDevMs",
    "dbwKp", "dbwKi", "dbwKd", "dbwLimpX10", "etbLimpRpm",
    "dbwAutocalDuty", "dbwAutocalMs",
    "tps1Min", "tps1Max", "tps2Min", "tps2Max",
    "pedal1Min", "pedal1Max", "pedal2Min", "pedal2Max",
    "appCorrelation", "tpsCorrelation",
    # the rest of the runtime configuration
    "idleEnable", "boostEnable", "knockMode", "celEnable", "fuelPumpMode",
    "mainRelayHoldMs", "pinClt", "pinIat", "pinMap", "pinCrank",
)
CONFIG_ARRAYS = ("fuelLoadAx", "fuelRpmAx", "ignLoadAx", "ignRpmAx",
                 "injPin", "ignPin")


class Ecu:
    """What the connected ECU says about itself, and the channel map."""

    def __init__(self, link: Link, sess: Session, ini_override=None):
        self.link, self.s = link, sess
        self.sig = link.text(b"S", 3) or ""
        self.version = link.text(b"V", 3) or ""
        self.ini_path = VC.pick_ini(self.sig, self.version, ini_override)
        self.ini = VC.Ini(self.ini_path)
        self.block = self.ini.block
        self.ring_base = self.block + EXT_RING
        self.lists = self._lists()
        sess.meta["identity"] = {
            "signature": self.sig, "version": self.version,
            "layout": self.sig.split()[-1] if self.sig else None,
            "ini": str(self.ini_path), "och_block": self.block,
            "build": VC.build_manifest(self.version)}
        self.page = link.page()
        if self.page:
            (sess.dir / "page.bin").write_bytes(self.page)
            sess.meta["engine_config"] = self.page_config()
        sess.save_meta()

    def _lists(self):
        txt = self.ini_path.read_text(encoding="utf-8", errors="replace")
        out = {}
        import re
        for m in re.finditer(r'^\s*(hc\w+List)\s*=\s*bits\s*,[^,]+,\s*\[[^\]]*\]'
                             r'\s*,(.*)$', txt, re.M):
            out[m.group(1)] = re.findall(r'"([^"]*)"', m.group(2))
        return out

    def label(self, lst, i):
        v = self.lists.get(lst, [])
        return v[i] if 0 <= i < len(v) else str(i)

    def page_config(self, page=None):
        import re
        page = self.page if page is None else page
        txt = self.ini_path.read_text(encoding="utf-8", errors="replace")
        body = txt.split("[Constants]", 1)[1]
        out = {}
        for line in body.splitlines():
            m = re.match(r"\s*(\w+)\s*=\s*(scalar|bits|array)\s*,\s*([US]\d\d)"
                         r"\s*,\s*(\d+)\s*,(.*)", line)
            if not m:
                continue
            name, kind, typ, off, rest = (m.group(1), m.group(2), m.group(3),
                                          int(m.group(4)), m.group(5))
            if name not in (CONFIG_ARRAYS if kind == "array"
                            else CONFIG_FIELDS):
                continue
            w = VC.SIZES[typ]
            if kind == "array":
                dm = re.match(r"\s*\[\s*(\d+)(?:\s*x\s*(\d+))?\s*\]\s*,(.*)",
                              rest)
                if not dm:
                    continue
                cnt = int(dm.group(1)) * int(dm.group(2) or 1)
                sm = re.search(r'"[^"]*"\s*,\s*([-+\d.eE]+)\s*,'
                               r'\s*([-+\d.eE]+)', dm.group(3))
                sc, tr = ((float(sm.group(1)), float(sm.group(2))) if sm
                          else (1.0, 0.0))
                out[name] = [round((int.from_bytes(
                    page[off + i * w:off + (i + 1) * w], "big",
                    signed=typ[0] == "S") + tr) * sc, 4) for i in range(cnt)]
                continue
            raw = int.from_bytes(page[off:off + w], "big",
                                 signed=typ[0] == "S")
            if kind == "bits":
                bm = re.match(r"\s*\[(\d+):(\d+)\]\s*,(.*)", rest)
                if bm:
                    lo, hi = int(bm.group(1)), int(bm.group(2))
                    v = (raw >> lo) & ((1 << (hi - lo + 1)) - 1)
                    labels = re.findall(r'"([^"]*)"', bm.group(3))
                    out[name] = labels[v] if v < len(labels) else v
                    out["_" + name] = v
                    continue
            sm = re.match(r'\s*"[^"]*"\s*,\s*([-+\d.eE]+)\s*,\s*([-+\d.eE]+)', rest)
            if sm:
                sc, tr = float(sm.group(1)), float(sm.group(2))
                out[name] = round((raw + tr) * sc, 4)
            else:
                out[name] = raw
        return out

    def window(self, off, cnt):
        body, err, ms = self.link.och(off, cnt)
        if body is None:
            return None, err, ms
        raw = self.ini.decode(body, off)
        eng = {n: self.ini.eng(n, v) for n, v in raw.items()}
        return eng, None, ms


class Ring:
    """The firmware's event ring (hcevlog711.c): read, check, decode."""

    def __init__(self, ecu: Ecu, sess: Session):
        self.e, self.s = ecu, sess
        self.next = None
        self.n = None
        self.lost = 0
        self.torn = 0
        self.ms_ref = None        # (ecu ms, host t) of the latest fast row

    def poll(self, first=False):
        hdr, err, _ = self.e.link.och(self.e.ring_base, EV_HDR)
        if hdr is None:
            return []
        if hdr[0:2] != b"HE":
            return []
        head = int.from_bytes(hdr[4:6], "big")
        n = int.from_bytes(hdr[6:8], "big")
        if not n or n > 200:
            return []
        self.n = n
        if self.next is None:
            # first read: the history the ring still holds (incl. before the
            # session - a stall's events survive the ECU reset)
            self.next = (head - n) & 0xFFFF if head >= n else 0
        want = (head - self.next) & 0xFFFF
        if want == 0:
            return []
        if want > n:
            lost = want - n
            self.lost += lost
            self.s.say("EVENTS: RING OVERFLOW - %d records lost (read slower "
                       "than the firmware wrote)" % lost)
            self.next = (head - n) & 0xFFFF
            want = n
        out = []
        seq = self.next
        while want:
            i = seq % n
            k = min(want, n - i, 40)
            body, err, _ = self.e.link.och(self.e.ring_base + EV_HDR + i * EV_REC,
                                           k * EV_REC)
            if body is None:
                break
            for j in range(k):
                r = body[j * EV_REC:(j + 1) * EV_REC]
                rs = int.from_bytes(r[0:2], "big")
                if rs != ((seq + j) & 0xFFFF):
                    self.torn += 1
                    continue
                out.append(self.decode(r))
            seq = (seq + k) & 0xFFFF
            want -= k
        self.next = seq
        return out

    def host_t(self, ms):
        if not self.ms_ref:
            return None
        ref_ms, ref_t = self.ms_ref
        d = (ref_ms - ms) & 0xFFFF
        if d > 60000:
            return None
        return round(ref_t - d / 1000.0, 3)

    def decode(self, r):
        seq = int.from_bytes(r[0:2], "big")
        ms = int.from_bytes(r[2:4], "big")
        typ, arg = r[4], r[5]
        v1 = int.from_bytes(r[6:8], "big")
        v2 = int.from_bytes(r[8:10], "big")
        name = EV_NAMES.get(typ, "TYPE%d" % typ)
        return {"seq": seq, "ecu_ms": ms, "t_host": self.host_t(ms),
                "type": name, "arg": arg, "v1": v1, "v2": v2,
                "text": self.text(name, arg, v1, v2)}

    def text(self, name, arg, v1, v2):
        e = self.e
        if name == "BOOT":
            return "ECU BOOT #%d (raw reset 0x%04X)" % (v1, v2)
        if name == "SYNC":
            old = (v2 >> 8) & 0xFF
            s = "SYNC: %s (was %s)" % (SYNC_STATE.get(arg, arg),
                                       SYNC_STATE.get(old, old))
            if arg < old:
                s += " - LOST, reason %s" % LOSS.get(v2 & 0xFF, v2 & 0xFF)
            if arg == 3 and old < 3:
                s = "SYNC: CRANK ACQUIRED"
            if arg == 4:
                s = "SYNC: PHASE ACQUIRED (720 deg)"
            return s + " @ %d rpm" % v1
        if name == "SYNC_LOSS":
            return "SYNC: CRANK LOST #%d - %s @ %d rpm" % (v2, LOSS.get(arg, arg), v1)
        if name == "CYCLE":
            return ("SYNC: PHASE ACQUIRED #%d @ %d rpm" % (v2, v1) if arg
                    else "SYNC: PHASE LOST - %s @ %d rpm" % (LOSS.get(v2, v2), v1))
        if name == "PHASE_CORR":
            return "SYNC: cam moved the half by 360 deg (#%d) @ %d rpm" % (v2, v1)
        if name == "SEQ":
            return "SEQUENTIAL: %s (twin skips %d) @ %d rpm" % (
                "ON" if arg else "OFF (fallback)", v2, v1)
        if name == "ENGINE":
            return "ENGINE: %s (battery %.1f V) @ %d rpm" % (
                ENGINE.get(arg, arg), v2 / 10.0, v1)
        if name == "FLAGS":
            return "FLAGS: %s @ %d rpm" % (bits(v2, FLAGS), v1)
        if name == "FUELCUT":
            return ("FUEL CUT -> %s @ %d rpm" % (bits(v2, FUEL_CUT), v1)
                    if v2 else "FUEL CUT cleared @ %d rpm" % v1)
        if name == "LIMP":
            return ("PROTECTION: %s @ %d rpm" % (bits(v2, LIMP), v1)
                    if v2 else "PROTECTION cleared @ %d rpm" % v1)
        if name == "OVERDWELL":
            return "IGNITION: OVERDWELL auto-fire #%d, latched coils 0x%02X @ %d rpm" % (
                v2, arg, v1)
        if name == "SPARK_SKIP":
            return "IGNITION: SPARK CUT active (skips %d) @ %d rpm" % (v2, v1)
        if name == "SCHED_MISSED":
            return "SCHEDULER: missed events %d @ %d rpm" % (v2, v1)
        if name == "ETB":
            res, ph, why = v1 & 0xF, (v1 >> 4) & 0xF, (v1 >> 8) & 0xFF
            s = "ETB: %s" % e.label("hcEtbPhaseList", ph)
            if res not in (0, 1):
                s = "ETB: %s" % e.label("hcEtbCalList", res)
                if why:
                    s += " - %s" % e.label("hcEtbWhyList", why)
                s += " (detail %d)" % v2
            return s
        if name == "DBW":
            return "ETB CONTROL: %s, faults %s" % (DBW_STATE.get(arg, arg),
                                                   bits(v2, DBW_FAULT))
        if name == "LAMBDA":
            return "LAMBDA: status 0x%04X, bank 1 %s, bank 2 %s" % (
                v1, e.label("hcLamWhyList", v2 & 0xFF),
                e.label("hcLamWhyList", (v2 >> 8) & 0xFF))
        if name == "LAMDYN":
            parts = []
            if arg & 1:
                parts.append("bank 1 variation observed (advisory)")
            if arg & 4:
                parts.append("bank 1 sustained low variation (advisory)")
            if arg & 16 and not arg & 5:
                parts.append("bank 1 no variation observed (advisory)")
            return "LAMBDA: %s (span %d counts)" % (", ".join(parts) or "-", v2)
        if name == "KLINE":
            return "KLINE: ECU %s counter = %d" % (KLINE_CTR.get(arg, arg), v2)
        return "%s arg %d v1 %d v2 %d" % (name, arg, v1, v2)

    def write(self, events):
        hdr = ["t_host", "ecu_ms", "seq", "type", "arg", "v1", "v2", "text"]
        for ev in events:
            vals = [ev["t_host"], ev["ecu_ms"], ev["seq"], ev["type"], ev["arg"],
                    ev["v1"], ev["v2"], ev["text"]]
            self.s.row("events", hdr, vals)
            f = EV_FILE.get(ev["type"], "faults")
            self.s.row("faults" if f == "faults" else f + "_events", hdr, vals)


# ===================================================== 2. ETB / AutoCal ===
ETB_WINDOWS = ((96, 32), (400, 30), (776, 66), (950, 24), (1224, 24))
ETB_TESTS = (
    (4, "DIRECTION A", 15.0),
    (5, "DIRECTION B", 15.0),
    (1, "CALIBRATE TPS ENDPOINTS", 20.0),
    (2, "PID AUTOTUNE", 25.0),
    (3, "AUTOCAL ETB (full)", 45.0),
)


class Autocal:
    def __init__(self, ecu: Ecu, sess: Session, ring: Ring, ask):
        self.e, self.s, self.ring, self.ask = ecu, sess, ring, ask

    def sample(self):
        row = {}
        rtt = 0.0
        for off, cnt in ETB_WINDOWS:
            if off + cnt > self.e.block:
                continue
            v, err, ms = self.e.window(off, cnt)
            rtt += ms
            if v is None:
                return None, err
            row.update(v)
        row["_rtt_ms"] = round(rtt, 1)
        return row, None

    def one(self, sub, label, limit_s):
        e = self.e
        r0, _ = self.sample()
        if r0 and r0.get("rpm", 0):
            self.s.verdict("AUTOCAL", "FAIL", "%s refused here: the engine is "
                           "turning (rpm %s)" % (label, r0.get("rpm")))
            return {"label": label, "result": "ENGINE TURNING"}
        self.s.say("ETB: %s - start" % label)
        if not e.link.command(b"!C" + bytes([sub])):
            return {"label": label, "result": "COMMAND NOT ACCEPTED"}
        t_end = time.monotonic() + limit_s
        last_ph = None
        seen_run = False
        res = None
        hdr = None
        rows = 0
        while time.monotonic() < t_end:
            row, err = self.sample()
            if row is None:
                continue
            rows += 1
            st = int(row.get("etbCalStatus", 0))
            r, ph, why = st & 0xF, (st >> 4) & 0xF, (st >> 8) & 0xFF
            if hdr is None:
                hdr = ["t", "test"] + sorted(row)
            # V100: autocal.csv, NOT fast.csv - under --full the runtime phase
            # then wrote its own rows against this header (columns shifted).
            self.s.row("autocal", hdr,
                       [self.s.t(), label] + [row.get(k) for k in hdr[2:]])
            if ph != last_ph:
                self.s.say("ETB: %s" % e.label("hcEtbPhaseList", ph))
                self.s.row("etb_events", ["t", "test", "event", "phase",
                                          "tps1", "tps2", "drive", "hold1",
                                          "push1", "moved", "limit", "disp",
                                          "hold_ms", "detail"],
                           [self.s.t(), label, "phase",
                            e.label("hcEtbPhaseList", ph),
                            row.get("adc01_TPS1"), row.get("adc03_TPS2"),
                            row.get("etbDrive"), row.get("etbHold1"),
                            row.get("etbPush1"), row.get("etbStopMoved"),
                            row.get("etbStopLimit"), row.get("etbStopDisp"),
                            row.get("etbHoldMs"), row.get("etbCalDetail")])
                last_ph = ph
            if r == 1:
                seen_run = True
            if seen_run and r not in (0, 1) and ph == 0:
                res = (r, why, row)
                break
            if not seen_run and r not in (0, 1) and ph == 0 and rows > 3:
                res = (r, why, row)       # refused at once (e.g. DBW enabled)
                break
            if self.ring:
                self.ring.write(self.ring.poll())
        if res is None:
            e.link.command(b"!C\x00")
            return {"label": label, "result": "TIMEOUT (aborted by the tool)",
                    "rows": rows}
        r, why, row = res
        out = {"label": label, "rows": rows,
               "result": e.label("hcEtbCalList", r),
               "why": e.label("hcEtbWhyList", why) if why else "",
               "a1": row.get("etbCalA1"), "b1": row.get("etbCalB1"),
               "rest1": row.get("etbCalRest1"), "hold1": row.get("etbHold1"),
               "push1": row.get("etbPush1"), "moved": row.get("etbStopMoved"),
               "limit": row.get("etbStopLimit"), "disp": row.get("etbStopDisp"),
               "hold_ms": row.get("etbHoldMs"), "detail": row.get("etbCalDetail"),
               "kp": row.get("etbTuneKp"), "ki": row.get("etbTuneKi"),
               "kd": row.get("etbTuneKd")}
        self.s.row("etb_events", ["t", "test", "event", "phase", "tps1", "tps2",
                                  "drive", "hold1", "push1", "moved", "limit",
                                  "disp", "hold_ms", "detail"],
                   [self.s.t(), label, "RESULT %s %s" % (out["result"], out["why"]),
                    "", row.get("adc01_TPS1"), row.get("adc03_TPS2"),
                    row.get("etbDrive"), out["hold1"], out["push1"],
                    out["moved"], out["limit"], out["disp"], out["hold_ms"],
                    out["detail"]])
        ok = r in (2, 4, 5, 6)
        why_txt = ""
        if not ok and "NOT A STOP" in out["why"]:
            why_txt = (" - the push moved TPS1 %s counts, limit %s (distance "
                       "from rest %s): legacy inferred-stop refusal; these values "
                       "do not establish physical torque or stop contact" % (
                           out["moved"], out["limit"], out["disp"]))
        self.s.verdict("AUTOCAL", "PASS" if ok else "FAIL", "%s: %s%s%s" % (
            label, out["result"], (" - " + out["why"]) if out["why"] else "",
            why_txt))
        return out

    def run(self):
        if not self.ask("ETB TESTS: engine OFF, ignition ON, hands clear of "
                        "the throttle body. The throttle WILL move to both "
                        "stops. Press Enter to start (s + Enter skips)",
                        allow_skip=True):
            self.s.verdict("AUTOCAL", "SKIPPED", "operator skipped")
            return {}
        out = []
        for sub, label, lim in ETB_TESTS:
            out.append(self.one(sub, label, lim))
            time.sleep(1.0)
        self.s.say("ETB: endpoints / gains a PASS wrote are in the RAM page - "
                   "Burn in TunerStudio to keep them")
        return {"tests": out}


# ================================================= 3. runtime recorder ====
class Group:
    """One named channel group: its windows, its period and its own CSV.

    V100. The group is declared by channel NAME (GROUPS above); the windows
    are derived from the .ini here, once, at connect. `names=None` means the
    WHOLE output-channel block - which is what the SLOW group is, so that no
    channel the firmware publishes goes unrecorded."""

    def __init__(self, ecu: Ecu, sess: Session, name, names, period):
        self.e, self.s, self.name, self.period = ecu, sess, name, period
        if names is None:
            self.win, self.missing, self.names = [(0, ecu.block)], [], None
        else:
            self.win, self.missing = windows(ecu.ini, names, ecu.block)
            self.names = names
        self.bytes = sum(c for _, c in self.win)
        self.hdr = None
        self.rows = 0
        self.rtt_sum = 0.0
        self.t_last = -1e9
        self.t_first = None

    def due(self, now):
        return now - self.t_last >= self.period

    def read(self):
        row, rtt = {}, 0.0
        for off, cnt in self.win:
            v, err, ms = self.e.window(off, cnt)
            rtt += ms
            if v is None:
                return None, err
            row.update(v)
        row["_rtt_ms"] = round(rtt, 1)
        self.rtt_sum += rtt
        return row, None

    def write(self, row, lead=()):
        t = self.s.t()
        if self.hdr is None:
            self.hdr = ["t"] + [k for k, _ in lead] + sorted(row)
        vals = [t] + [v for _, v in lead] + [row.get(k)
                                             for k in self.hdr[1 + len(lead):]]
        self.s.row(self.name, self.hdr, vals)
        self.rows += 1
        if self.t_first is None:
            self.t_first = t
        self.t_last = time.monotonic()
        return t

    def report(self, dur):
        """What metadata.json says about this group."""
        return {"period_s": self.period, "windows": self.win,
                "bytes_per_row": self.bytes, "exchanges_per_row": len(self.win),
                "channels": (len(self.names) - len(self.missing)
                             if self.names is not None else "whole block"),
                "missing": self.missing, "rows": self.rows,
                "rows_per_s": round(self.rows / dur, 2) if dur > 0 else None,
                "mean_rtt_ms": (round(self.rtt_sum / self.rows, 1)
                                if self.rows else None)}


class Watch:
    """V100: the rare state/config channels, reported on CHANGE.

    A value that moves once an hour should not pay for a fast-poll slot; it
    should be caught the moment it moves. Fed from the SLOW row, which is the
    whole block, so every channel in ON_CHANGE is covered whether or not it
    is in any polled group."""

    HDR = ["t", "channel", "from", "to"]

    def __init__(self, sess: Session, names=ON_CHANGE):
        self.s = sess
        self.names = names
        self.prev = {}
        self.n = 0

    def feed(self, row, t=None):
        out = []
        for n in self.names:
            if n not in row:
                continue
            v = row[n]
            if n in self.prev and self.prev[n] != v:
                self.s.row("onchange", self.HDR,
                           [t if t is not None else self.s.t(), n,
                            self.prev[n], v])
                self.n += 1
                out.append((n, self.prev[n], v))
            self.prev[n] = v
        return out


class Runtime:
    def __init__(self, ecu: Ecu, sess: Session, ring: Ring, stop_evt,
                 duration=None, profile="max", rates=None):
        self.e, self.s, self.ring = ecu, sess, ring
        self.stop = stop_evt
        self.duration = duration
        self.profile = profile
        r = dict(PROFILES[profile])
        r.update(rates or {})
        self.rates = r
        self.g = {n: Group(ecu, sess, n, GROUPS.get(n), r[n])
                  for n in ("fast", "medium", "slow")}
        self.watch = Watch(sess)
        self.state = None
        self.boot = None          # rstBootCount, from the snapshot/slow row
        self.ecu_ms = None
        self.page_sha = None
        self.t_page = -1e9
        self.snaps = []
        self.stats = {"fast_rows": 0, "medium_rows": 0, "slow_rows": 0,
                      "drops": 0, "reconnects": 0, "events": 0, "drop_s": 0.0,
                      "onchange": 0, "snapshots": 0, "reboots": 0}
        self.kwp = None           # Kline.kwp, when the link needed it

    # -------------------------------------------------------- snapshots ----
    def snapshot(self, reason):
        """The whole block (and the page, if it changed) with its reason.

        V100 §3: at session start, at every reconnect and after every ECU
        reboot, so a session can always be read back against the exact
        configuration and state it was taken under."""
        import hashlib
        row, err = self.g["slow"].read()
        if row is None:
            self.s.say("SNAPSHOT (%s): the block could not be read - %s"
                       % (reason, err))
            return None
        t = self.s.t()
        hdr = ["t", "reason"] + sorted(row)
        self.s.row("snapshots", hdr, [t, reason] + [row.get(k)
                                                    for k in hdr[2:]])
        self.watch.feed(row, t)
        entry = {"t": t, "utc": utc(), "reason": reason,
                 "boot_count": row.get("rstBootCount"),
                 "ecu_ms": row.get("ecuMs"),
                 "nvm_generation": row.get("nvmGeneration"),
                 "nvm_source": row.get("nvmSource"),
                 "cfg_validation": row.get("cfgValidation"),
                 "cfg_warnings": row.get("cfgWarnings"),
                 "cfg_active_rev": row.get("cfgActiveRev")}
        now = time.monotonic()
        page = (self.e.link.page()
                if now - self.t_page >= PAGE_SNAP_MIN_S else None)
        if page:
            self.t_page = now
            sha = hashlib.sha256(page).hexdigest()
            entry["page_sha256"] = sha
            if self.page_sha is None:
                self.page_sha = sha
            elif sha != self.page_sha:
                name = "page_%s.bin" % reason.replace(" ", "_")
                (self.s.dir / name).write_bytes(page)
                entry["page_changed_to"] = name
                entry["engine_config"] = self.e.page_config(page)
                self.s.say("SNAPSHOT (%s): THE CALIBRATION PAGE CHANGED "
                           "(%s) - written to %s" % (reason, sha[:16], name))
        self.snaps.append(entry)
        self.stats["snapshots"] += 1
        self.boot = row.get("rstBootCount", self.boot)
        self.s.say("SNAPSHOT (%s): boot #%s, nvm gen %s, cfg validation %s, "
                   "warnings %s" % (reason, entry["boot_count"],
                                    entry["nvm_generation"],
                                    entry["cfg_validation"],
                                    entry["cfg_warnings"]))
        return entry

    def boot_count(self):
        """rstBootCount alone - two bytes, so a candidate reboot can be
        TESTED before a whole-block snapshot is spent on it."""
        s = self.e.ini.scalars.get("rstBootCount")
        if not s:
            return None
        v, err, _ms = self.e.window(s[1], VC.SIZES[s[0]])
        return None if v is None else v.get("rstBootCount")

    def check_reboot(self, row):
        """An ECU that restarted mid-session.

        ecuMs is a 16-bit uptime that WRAPS every 65.5 s, so a step back is
        only a candidate: rstBootCount is what tells a wrap from a restart,
        and it is read on its own (2 bytes) rather than by snapshotting
        1248 bytes once a minute for a wrap that is not a reboot."""
        ms = row.get("ecuMs")
        if ms is None:
            return False
        prev, self.ecu_ms = self.ecu_ms, ms
        if prev is None or ms >= prev or (prev - ms) < 2000:
            return False
        now = self.boot_count()
        if now is None or self.boot is None or now == self.boot:
            self.stats["uptime_wraps"] = self.stats.get("uptime_wraps", 0) + 1
            return False
        self.stats["reboots"] += 1
        self.s.say("ECU REBOOTED during the session: boot #%s -> #%s"
                   % (self.boot, now))
        self.boot = now
        self.snapshot("reboot")
        return True

    def note_changes(self, row, t=None):
        """V100 on-change: fed from EVERY group, so a state that is in the
        fast group is caught on the next fast row rather than waiting for the
        slow one, while a channel only the whole-block read carries is still
        covered. Watch.feed() ignores a name the row does not hold."""
        for n, a, b in self.watch.feed(row, t):
            self.s.say("STATE: %s %s -> %s" % (n, a, b))
        self.stats["onchange"] = self.watch.n

    def engine_state(self, row):
        rpm = row.get("RPMValue", row.get("rpm", 0)) or 0
        fl = int(row.get("engineFlags", 0) or 0)
        return "RUNNING" if fl & 1 else ("CRANKING" if fl & 2 or rpm else
                                         "STOPPED")

    def reconnect(self):
        link = self.e.link
        self.stats["drops"] += 1
        t0 = time.monotonic()
        self.s.say("KLINE: DROPOUT - reconnecting")
        link.stage = "runtime reconnect"
        t_kwp = t0 + 5.0
        while not self.stop.is_set():
            body, err, ms = link.exchange(b"S", 0.4)
            if body is None and self.kwp and time.monotonic() >= t_kwp:
                # an ECU that restarted behind an OBD path that needs the
                # VAG/KWP entry: try it every 5 s
                t_kwp = time.monotonic() + 5.0
                stage, why, _r = self.kwp(link, link.p.baud)
                self.s.say("KLINE: reconnect via KWP: %s %s" % (stage, why))
                if stage == "OK":
                    body = b"ok"
            if body is not None:
                self.stats["reconnects"] += 1
                d = time.monotonic() - t0
                self.stats["drop_s"] += d
                self.s.say("KLINE: RECONNECTED after %.1f s" % d)
                self.s.row("kline", ["t", "path", "stage", "baud", "cmd", "ok",
                                     "error", "latency_ms", "bytes", "attempt"],
                           [self.s.t(), link.path, "runtime dropout",
                            link.p.baud, "-", 1, "down %.2f s" % d, d * 1000,
                            0, 1])
                # V100 §3: a reconnect may be an ECU power cycle, so the
                # configuration and the counters are re-read, not assumed.
                self.snapshot("reconnect")
                return True
            time.sleep(0.2)
        return False

    def run(self):
        e, s = self.e, self.s
        t_end = time.monotonic() + self.duration if self.duration else None
        t_ring = 0.0
        fails = 0
        fast, med, slow = self.g["fast"], self.g["medium"], self.g["slow"]
        s.say("RUNTIME: profile %s - fast %s, medium %.2f s, slow %.2f s, "
              "ring %.2f s" % (self.profile,
                               "as fast as the link allows"
                               if not fast.period else "%.2f s" % fast.period,
                               med.period, slow.period, self.rates["ring"]))
        s.say("RUNTIME: fast %d channels in %d exchange(s) / %d B; medium %d "
              "in %d / %d B; slow the whole %d-byte block"
              % (len(fast.names) - len(fast.missing), len(fast.win),
                 fast.bytes, len(med.names) - len(med.missing), len(med.win),
                 med.bytes, e.block))
        for g in (fast, med):
            if g.missing:
                s.say("RUNTIME: %s - %d channel(s) this .ini does not "
                      "declare, not read: %s" % (g.name, len(g.missing),
                                                 ", ".join(g.missing[:8])))
        self.snapshot("session start")
        s.say("RUNTIME: recording - key-on, crank, run, stop: anything. "
              "Press ENTER (or Ctrl+C) to finish.")
        e.link.stage = "runtime"
        t_rate = time.monotonic()
        n_rate = 0
        while not self.stop.is_set():
            now = time.monotonic()
            if t_end and now >= t_end:
                break
            if not fast.due(now):
                time.sleep(min(0.01, max(0.0, fast.period
                                         - (now - fast.t_last))))
                continue
            row, err = fast.read()
            if row is None:
                fails += 1
                if fails >= 3:
                    if not self.reconnect():
                        break
                    fails = 0
                continue
            fails = 0
            t = fast.write(row, lead=[("wall", utc())])
            self.stats["fast_rows"] = fast.rows
            self.note_changes(row, t)
            n_rate += 1
            if "ecuMs" in row and self.ring:
                self.ring.ms_ref = (int(row["ecuMs"]), t)
            self.check_reboot(row)
            st = self.engine_state(row)
            if st != self.state:
                s.say("ENGINE: %s (rpm %s)" % (st, row.get("RPMValue")))
                self.state = st
            now = time.monotonic()
            if med.due(now):
                v, _err = med.read()
                if v:
                    self.note_changes(v, med.write(v))
                    self.stats["medium_rows"] = med.rows
                now = time.monotonic()
            if slow.due(now):
                v, _err = slow.read()
                if v:
                    self.note_changes(v, slow.write(v))
                    self.stats["slow_rows"] = slow.rows
                    b = v.get("rstBootCount")
                    if b is not None and self.boot is not None and b != self.boot:
                        self.stats["reboots"] += 1
                        s.say("ECU REBOOTED during the session: boot #%s -> "
                              "#%s" % (self.boot, b))
                        self.snapshot("reboot")
                    self.boot = b if b is not None else self.boot
                now = time.monotonic()
            if self.ring and now - t_ring >= self.rates["ring"]:
                t_ring = now
                evs = self.ring.poll()
                for ev in evs:
                    s.say(ev["text"])
                self.ring.write(evs)
                self.stats["events"] += len(evs)
            if now - t_rate >= 10.0:
                s.say("RUNTIME: %.1f fast rows/s (rtt %.0f ms), %d medium, "
                      "%d slow, %d events" % (
                          n_rate / (now - t_rate), row.get("_rtt_ms", 0),
                          med.rows, slow.rows, self.stats["events"]))
                t_rate, n_rate = now, 0
        if self.ring:
            evs = self.ring.poll()
            self.ring.write(evs)
            self.stats["events"] += len(evs)
            self.stats["ring_lost"] = self.ring.lost
            self.stats["ring_torn"] = self.ring.torn
        dur = max(1e-6, s.t() - (fast.t_first or 0.0))
        self.stats["profile"] = self.profile
        self.stats["rates_configured_s"] = self.rates
        self.stats["groups"] = {n: g.report(dur) for n, g in self.g.items()}
        self.stats["snapshot_log"] = self.snaps
        self.stats["duration_s"] = round(dur, 2)
        return self.stats


# ================================================================ main ====
def default_out() -> Path:
    base = ROOT.parent / "evidence"
    if not base.is_dir():
        base = ROOT / "evidence_local"
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return base / "vehicle_tests" / ("%s_vehicle_test" % stamp)


def make_ask(no_prompt: bool, sess: Session, stdin_q):
    def ask(prompt, allow_skip=False):
        sess.say(">>> " + prompt)
        if no_prompt:
            sess.say("    (--no-prompt: continuing)")
            return True
        line = stdin_q.get() if stdin_q else input()
        if allow_skip and line.strip().lower().startswith("s"):
            sess.say("    skipped")
            return False
        return True
    return ask


def make_confirm_physical(no_prompt, sess, stdin_q):
    """V100: ask the operator what the KKL is PHYSICALLY plugged into.

    The software path and the cable are different facts. V99 inferred the
    cable from a command-line flag, so a session run after the operator had
    moved the KKL to ECU cavity 43 - and left it there - recorded "OBD path
    PASS" over wiring that had never carried OBD at all
   . With --no-prompt nothing is confirmed and
    the remembered mode is kept, which is why run() labels an unconfirmed
    mode as such instead of asserting it.
    """
    if no_prompt:
        return None

    def confirm(default):
        other = "DIRECT ECU" if default == "OBD" else "OBD"
        sess.say(">>> Where is the KKL plugged in RIGHT NOW?")
        sess.say("      [Enter] = %s        d = %s" % (default, other))
        line = (stdin_q.get() if stdin_q else input()).strip().lower()
        return other if line.startswith("d") else default

    return confirm


def run(a, open_port=None, stdin_q=None) -> int:
    out = Path(a.out) if a.out else default_out()
    sess = Session(out, quiet=a.quiet)
    profile = getattr(a, "profile", "max")
    sess.meta.update({"port": a.port, "baud": a.baud,
                      "mode": [m for m in ("kline", "autocal", "runtime")
                               if getattr(a, m)],
                      "logging_profile": profile,
                      "rates_configured_s": PROFILES[profile],
                      "args": vars(a) if not isinstance(a, dict) else a})
    sess.save_meta()
    sess.say("HaniCore vehicle test %s -> %s" % (TOOL_VERSION, out))
    sess.say("LOGGING PROFILE: %s - %s" % (
        profile, ", ".join("%s %s" % (k, "max" if not v else "%.2f s" % v)
                           for k, v in PROFILES[profile].items())))
    if open_port is None:
        def open_port(baud, _n=a.port):
            return SerialPort(_n, baud)
    ask = make_ask(a.no_prompt, sess, stdin_q)
    rc = 0
    link = None
    stop_evt = threading.Event()
    try:
        # ---------------------------------------------------- 1. K-LINE
        kl = Kline(sess, open_port, a.baud, ask, direct=a.direct,
                   confirm=make_confirm_physical(a.no_prompt, sess, stdin_q),
                   state_dir=sess.dir.parent)
        # V100 §4: the CABLE is confirmed in EVERY session, not only when
        # phase 1 runs. A --runtime-only session used to inherit whatever the
        # software path happened to be called, which is how V99 came to label
        # ECU-cavity-43 wiring "OBD".
        kl.confirm_physical()
        if a.kline:
            sess.say("=== PHASE 1: K-LINE QUALIFICATION ===")
            link, res = kl.run()
            sess.meta["phases"]["kline"] = res
            sess.save_meta()
            first = res.get(kl.first_path, {})
            if first.get("stage") == "OK":
                sess.verdict("KLINE", "PASS", "%s path: %s" % (
                    kl.first_path, first.get("how")))
            else:
                sess.verdict("KLINE", "FAIL", "%s path: stage %s - %s" % (
                    kl.first_path, first.get("stage"), first.get("detail", "")))
                d = res.get("DIRECT ECU")
                if d:
                    sess.verdict("KLINE", "PASS" if d["stage"] == "OK" else "FAIL",
                                 "DIRECT ECU path: %s" % (d.get("how") or
                                                          "stage %s - %s" % (
                                                              d["stage"],
                                                              d.get("detail"))))
            q = res.get("quality")
            if q:
                soak = q["soak"]
                st = "PASS" if soak["good"] >= 98 else (
                    "WARNING" if soak["good"] >= 80 else "FAIL")
                sess.verdict("KLINE", st, "read soak %d/100 at %s rows/s "
                             "(%d B), latency median %s ms, crc %d, timeouts %d;"
                             " port reconnect %s in %s ms" % (
                                 soak["good"], soak["rows_per_s"],
                                 soak["bytes_per_read"],
                                 q["latency_ms"]["median"] and
                                 round(q["latency_ms"]["median"], 1),
                                 soak["crc_errors"], soak["timeouts"],
                                 "OK" if q["reconnect"]["ok"] else "FAILED",
                                 q["reconnect"]["ms"]))
                kc = q and res.get("keycycle")
                if kc and not kc.get("skipped"):
                    sess.verdict("KLINE", "PASS" if kc["ok"] else "FAIL",
                                 "key-cycle reconnect %s in %s ms (%s)" % (
                                     "OK" if kc["ok"] else "FAILED", kc["ms"],
                                     kc["how"]))
        else:
            link, res = kl.run(quality=False)
            sess.meta["phases"]["kline"] = res
            if link is None:
                sess.verdict("KLINE", "FAIL", "no connection: %s" % res)
        # V100 §4: the physical mode is a session-level fact, kept separate
        # from the software path that was attempted, and never inferred from
        # an init/test command succeeding.
        sess.meta["kline_physical"] = {
            "mode": kl.phys, "source": kl.phys_src,
            "transitions": kl.transitions,
            "software_path_attempted": kl.first_path,
            "confirmed": kl.phys_src == "operator confirmed"
            or kl.phys_src == "operator moved it during this session"}
        sess.save_meta()
        if link is None:
            sess.say("No ECU connection - nothing else can run.")
            return 2
        ecu = Ecu(link, sess, a.ini)
        sess.say("ECU: %s | %s | ini %s" % (ecu.version, ecu.sig,
                                            ecu.ini_path.name))
        sess.say("K-LINE PHYSICAL: %s (%s)%s" % (
            kl.phys, kl.phys_src,
            "" if sess.meta["kline_physical"]["confirmed"]
            else " - NOT CONFIRMED, treat the path label with care"))
        cfg = sess.meta.get("engine_config", {})
        if cfg:
            sess.say("CONFIG: firing order %s | injection %s | ignition %s | "
                     "sync %s | load %s | DBW %s | lambda heat %s | trigAngle "
                     "%s deg" % (
                         cfg.get("firingOrder"), cfg.get("injStrategy"),
                         cfg.get("ignStrategy"), cfg.get("syncMode"),
                         cfg.get("loadSource"), cfg.get("dbwEnable"),
                         cfg.get("lambdaHeatPolicy"), cfg.get("trigAngleX10")))
        ring = Ring(ecu, sess)
        evs = ring.poll(first=True)
        ring.write(evs)
        if evs:
            sess.say("EVENTS: %d records already in the ring (incl. before "
                     "this session)" % len(evs))
        # --------------------------------------------------- 2. AUTOCAL
        if a.autocal:
            sess.say("=== PHASE 2: ETB / AUTOCAL DIAGNOSTICS ===")
            r = Autocal(ecu, sess, ring, ask).run()
            sess.meta["phases"]["autocal"] = r
            sess.save_meta()
        # --------------------------------------------------- 3. RUNTIME
        if a.runtime:
            sess.say("=== PHASE 3: ENGINE RUNTIME FLIGHT RECORDER ===")
            if stdin_q is None and not a.no_prompt and a.duration is None:
                def wait_enter():
                    try:
                        input()
                    except EOFError:
                        return
                    stop_evt.set()
                threading.Thread(target=wait_enter, daemon=True).start()
            rt = Runtime(ecu, sess, ring, stop_evt, a.duration,
                         profile=profile)
            rt.kwp = kl.kwp
            st = rt.run()
            sess.meta["phases"]["runtime"] = st
            sess.save_meta()
            g = st["groups"]
            sess.verdict("RUNTIME", "PASS" if st["fast_rows"] else "FAIL",
                         "profile %s: %d fast rows (%s/s), %d medium, %d "
                         "slow, %d events, %d on-change, %d snapshots, %d "
                         "reboots, %d link dropouts (%.1f s down), ring lost "
                         "%s" % (
                             st["profile"], st["fast_rows"],
                             g["fast"]["rows_per_s"], st["medium_rows"],
                             st["slow_rows"], st["events"], st["onchange"],
                             st["snapshots"], st["reboots"], st["drops"],
                             st["drop_s"], st.get("ring_lost", 0)))
    except KeyboardInterrupt:
        sess.say("interrupted - everything recorded so far is kept")
        rc = 130
    finally:
        try:
            if link is not None:
                link.p.close()
        except Exception:
            pass
        sess.close()
    if a.analyze and (a.runtime or a.autocal):
        try:
            import me711_log_analyze as LA
            LA.main([str(out)])
        except Exception as ex:     # the recording is the product
            print("analysis failed: %s" % ex)
    print("\nSESSION FOLDER: %s" % out)
    return rc


def parse(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--out")
    ap.add_argument("--ini")
    ap.add_argument("--duration", type=float)
    ap.add_argument("--kline", action="store_true")
    ap.add_argument("--autocal", action="store_true")
    ap.add_argument("--runtime", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--profile", choices=sorted(PROFILES), default="max",
                    help="logger load: 'max' = maximum observability "
                         "(default), 'reduced' = about a quarter of the "
                         "polled rate with the event ring untouched (D3)")
    ap.add_argument("--reduced", action="store_true",
                    help="shorthand for --profile reduced")
    ap.add_argument("--direct", action="store_true",
                    help="the KKL is on the ECU's own K-line (not OBD)")
    ap.add_argument("--no-prompt", action="store_true")
    ap.add_argument("--no-analyze", dest="analyze", action="store_false")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    if a.reduced:
        a.profile = "reduced"
    if a.full:
        a.kline = a.autocal = a.runtime = True
    if not (a.kline or a.autocal or a.runtime):
        ap.error("choose --kline, --autocal, --runtime or --full")
    return a


def main(argv=None) -> int:
    return run(parse(argv))


if __name__ == "__main__":
    raise SystemExit(main())
