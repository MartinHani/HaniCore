#!/usr/bin/env python3
r"""
me711_vehicle_test.py - THE HaniCore vehicle diagnostic / flight recorder.

    py tools\vehicle\me711_vehicle_test.py      THE GUIDED VEHICLE TEST (2026-10-10):
                                    one session that walks you through every
                                    system the engine needs, records all of
                                    it, and ends with PASS / WARN / FAIL per
                                    system (report.md, summary.txt):
        0 PREFLIGHT  identity, config, battery, CLT/IAT, MAP vs baro, pedal /
                     TPS at rest, trouble codes, wideband warm-up, boot history
        1 K-LINE     OBD (VAG 5-baud / KWP) first, else move the KKL to pin 43
        2 PEDAL      released / full / slow sweep / fast stabs
        3 THROTTLE   engine off: direction A/B, AutoCal, optional autotune
        4 START      crank -> sync -> cam -> running, battery dip, sync losses
        5 IDLE       60 s: EVERY injector channel opens, coils, scheduler,
                     rpm stability, wideband stays valid, mixture, warm-up
        6 DRIVE      DBW on (RAM only, engine stopped to apply): slow ramp,
                     5 fast tip-ins (cause of any stumble named), overrun
                     fuel cut, blip, 2500 rpm hold
        7 STRATEGY   optional: batch / semi-seq / sequential, cam level 0/1
        8 KEY-OFF    run-on, hot restart
        9 REPORT     + the automatic log analysis
      --phase <name> runs one phase; --resume <folder> continues a session.
      Every actuating step needs your ENTER after a safety line; Ctrl+C or
      a failure sends '!X' and restores every RAM value it changed. FULLY
      AUTOMATIC (2026-10-11): it asks only for physical actions. A PASSED
      throttle calibration (phase 3) is BURNED at once (engine off); a
      PASSED drive test (phase 6) keeps the electronic throttle ON and is
      burned at the end after you stop the engine; everything else (the
      strategy / cam-level experiments) is put back. Every Burn is verified
      by reading the page back.
    py tools\vehicle\me711_vehicle_test.py --recorder   the plain recorder
                                    (K-line + record everything until ENTER)
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
# 2026-10-11: THE RESET WITNESS follows the event ring (916 B) and the runtime
# health record (64 B): 32 big-endian words live + 32 of the boot before
# (hcrtmon711.c). Older images answer nothing there.
EXT_WITNESS = EXT_RING + 916 + 64
WT_FIELDS = ("magic", "seq", "uptime_ms", "rpm", "batt_dv", "etb_status",
             "asic_run_ok", "asic_csum_err", "asic_timeouts",
             "umkom_mismatch", "umkom_health_expect", "umkom_last_rx",
             "s5500_gap_max_ms", "nvm_state_trg", "main_pass_max_T",
             "wdt_gap_max_ms", "cc25_beat_age_max_ms", "rt_fault",
             "user_stack_hwm", "sys_stack_hwm", "svc_dbw_T", "svc_comms_T",
             # 2026-10-13: the S5500 runtime raster, start to start (T = 0.8 us)
             "s5500_per_max_T", "s5500_per_min_T", "s5500_n_gt10_5ms",
             "s5500_n_gt11ms", "s5500_n_gt12ms", "s5500_n_gt15ms",
             "s5500_n_lt9_5ms", "s5500_prev_start_T", "stall_cfg", "stall_last")
EV_HDR, EV_REC = 16, 10
# 2026-10-15: THE K-LINE CAPTURE follows the witness (hckwp_me711.c): 256
# raw bytes, C167 LITTLE-endian words - magic 'KC' 0x4B43, state (0 armed /
# 1 recording / 2 done), trigger tick, samples, UART bytes while recording,
# triggers since boot, link state, spare - then one bit a millisecond from
# byte 16, 1 = line high, bit 0 of byte 16 first.
EXT_KLCAP = EXT_WITNESS + 128


def decode_klcap(b: bytes) -> dict:
    """The ECU's capture of the first low run it heard on the K-line."""
    if len(b) < 16 or int.from_bytes(b[0:2], "little") != 0x4B43:
        return {"present": False}
    w = [int.from_bytes(b[i:i + 2], "little") for i in range(0, 16, 2)]
    n = min(w[3], (len(b) - 16) * 8)
    lv = [(b[16 + (i >> 3)] >> (i & 7)) & 1 for i in range(n)]
    runs = []
    for v in lv:
        if runs and runs[-1][0] == v:
            runs[-1][1] += 1
        else:
            runs.append([v, 1])
    out = {"present": True, "state": ("armed, nothing heard", "recording",
                                      "done")[w[1]] if w[1] < 3 else w[1],
           "trigger_ms": w[2], "samples": n, "uart_bytes": w[4],
           "triggers": w[5], "link_state": w[6],
           "runs": " ".join("%s%d" % ("H" if v else "L", c)
                            for v, c in runs[:60])}
    # the sample at index 0 is the THIRD low millisecond: a 5-baud start
    # bit began ~3 ms earlier; bit i is centred 100 + 200 i ms after it
    if n >= 1900 and runs and runs[0][0] == 0 and runs[0][1] >= 140:
        def at(ms):
            k = ms - 3
            return lv[k] if 0 <= k < n else None
        bits = [at(100 + 200 * i) for i in range(1, 10)]
        if None not in bits:
            byte = sum(bit << i for i, bit in enumerate(bits[:8]))
            out["five_baud"] = {"byte": "0x%02X" % byte,
                                "stop_bit_high": bool(bits[8])}
    return out


def kline_forensics(ecu, sess) -> dict:
    """What the ECU itself recorded about the K-line since boot: link and
    KWP counters (OCH 842..849) and the capture. Read after every connect -
    an OBD attempt that failed is visible here once the KKL is on pin 43
    (the owner keeps the key on while moving it, so the RAM survives)."""
    out = {}
    body, _err, _ = ecu.link.och(842, 8)
    if body:
        ls, ks, kc, ld = (int.from_bytes(body[i:i + 2], "big")
                          for i in (0, 2, 4, 6))
        out["counters"] = {
            "rate": ("57600", "115200", "124800", "10400")[ls & 3],
            "locked": bool(ls & 0x10), "rate_changes": ls >> 8,
            "kwp_phase": ks & 15, "five_baud_stage": (ks >> 4) & 7,
            "good_inits": ks >> 8, "failed_inits": kc >> 8,
            "foreign_addresses": kc & 255, "rate_evidence_events": ld & 255,
            "sessions_ended_by_bad_frames": ld >> 8}
    body, _err, _ = ecu.link.och(ecu.block + EXT_KLCAP, 256)
    if body:
        (sess.dir / "kline_capture.bin").write_bytes(bytes(body))
        out["capture"] = decode_klcap(bytes(body))
    sess.meta["ecu_kline"] = out
    sess.save_meta()
    c, k = out.get("counters"), out.get("capture", {})
    if c:
        sess.say("ECU K-LINE: %s%s, %d rate changes | KWP good inits %d, "
                 "failed %d, foreign addresses %d | rate-evidence events %d"
                 % (c["rate"], " locked" if c["locked"] else "",
                    c["rate_changes"], c["good_inits"], c["failed_inits"],
                    c["foreign_addresses"], c["rate_evidence_events"]))
    if k.get("present"):
        sess.say("ECU K-LINE CAPTURE: %s, %d ms, %d UART bytes, %d triggers"
                 "%s" % (k["state"], k["samples"], k["uart_bytes"],
                         k["triggers"],
                         (" | 5-baud byte %s (stop bit %s)"
                          % (k["five_baud"]["byte"],
                             "ok" if k["five_baud"]["stop_bit_high"]
                             else "LOW")) if "five_baud" in k else ""))
        if k["samples"]:
            sess.say("  line (ms): " + k["runs"][:200])
    return out

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
        inj1RequestedUs inj1DeliveredUs inj2RequestedUs inj2DeliveredUs
        inj3RequestedUs inj3DeliveredUs inj4RequestedUs inj4DeliveredUs
        inj5RequestedUs inj5DeliveredUs inj6RequestedUs inj6DeliveredUs
        inj7RequestedUs inj7DeliveredUs inj8RequestedUs inj8DeliveredUs
        runOn runOnMs nvmState nvmGeneration nvmCommits
        dtcActive1 dtcActive2 dtcActive3 dtcActive4 rstBootCount
        cfgDirtyGroups cfgApplyRefused
        idleFloorX10 idleTrimX10 idleTargetRpm idleState idleTarget
        boostState boostCmdX10 boostReqX10 boostTargetX10 boostDuty boostCuts
        motorsportState revLimitNow fuelPumpState fuelPumpReason
        dtcMil dtcActiveN celState cjErr cjTmo
        knockState knockWindows knockLate knockStale knockSelFault knockCount
        knockFlags vvt1State vvt1Err vvt2State vvt2Err switchRaw
        dtcStoredMask0 dtcStoredMask1 dtcActiveMask0 dtcActiveMask1
        dtcStoredN
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
    dtcStoredMask0 dtcStoredMask1 dtcActiveMask0 dtcActiveMask1
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
             256: "outputs not live", 512: "motor supply",
             1024: "saturated > 0.6 s (limp request)"}
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

    def wakeup(self):
        """ISO 14230 fast init: 25 ms break, 25 ms idle, at 10400. The ECU
        times the low run itself (accepts 20..30 ms) - a busy wait, not a
        sleep, because Windows sleeps in 15 ms steps."""
        self.set_baud(10400)
        t0 = time.perf_counter()
        self.ser.break_condition = True
        while time.perf_counter() - t0 < 0.025:
            pass
        self.ser.break_condition = False
        t1 = time.perf_counter()
        while time.perf_counter() - t1 < 0.025:
            pass
        self.reset_input()

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


# =========================================================== the session ==
class Session:
    """The folder, the console, the CSV writers - one per run."""

    def __init__(self, out: Path, quiet=False, resume=False):
        self.dir = out
        out.mkdir(parents=True, exist_ok=True)
        self.t0 = time.monotonic()
        self.quiet = quiet
        self.resume = resume
        self._w = {}
        self._f = {}
        self._hdr = {}
        self.summary = []
        self.meta = {"tool": "me711_vehicle_test", "tool_version": TOOL_VERSION,
                     "started_utc": utc(), "phases": {}}
        if resume and (out / "metadata.json").exists():
            # --resume: the earlier part of THIS session stays the record
            try:
                self.meta = json.loads((out / "metadata.json").read_text())
            except Exception:
                pass
            self.meta.setdefault("phases", {})
            self.meta.setdefault("resumed_utc", []).append(utc())
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
            p = self.dir / (name + ".csv")
            append = self.resume and p.exists() and p.stat().st_size > 0
            f = open(p, "a" if append else "w", newline="", encoding="utf-8")
            w = csv.writer(f)
            if not append:
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
        # every timeout here was sized for 57600+; at 10400 (the vehicle
        # K-line's fallback) the same bytes take 5.5 times longer
        timeout *= max(1.0, 57600.0 / float(self.p.baud or 57600))
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

    # THE OBD SWEEP (2026-10-15, owner: "try everything possible with OBD").
    # Every entry the ECU implements, slowest-to-arm first, three rounds; once
    # an entry reaches IDENTIFY, every fast rate in turn - each with a fresh
    # init, each proven by data reads - and 10400 if none holds. Every byte
    # on the line goes to kline_bytes.csv.
    ENTRIES = (("5-baud", "5baud", 0.3), ("5-baud (2 s idle)", "5baud", 2.0),
               ("fast init", "fast", 0.3))
    FAST_RATES = (115200, 124800, 57600)

    def raw(self, link, stage, tx, rx):
        self.s.row("kline_bytes", ["t", "path", "stage", "baud", "tx", "rx"],
                   [self.s.t(), link.path, stage, link.p.baud,
                    (tx or b"").hex(), (rx or b"").hex()])

    def enter(self, link, kind="5baud", idle=0.3):
        """The vehicle entry up to IDENTIFY. -> (stage, why, r); stage
        "IDENTIFIED" when the ECU named itself."""
        p = link.p
        r = {"entry": "5-baud" if kind == "5baud" else "fast init",
             "idle_s": idle}
        time.sleep(idle)                       # W5: the bus idle before
        if kind == "5baud":
            link.stage = "kwp 5-baud init"
            p.five_baud(0x01)
            sync = p.read(3, 0.8)
            self.raw(link, "5-baud 0x01 -> sync", b"\x01", sync)
            r["sync"] = sync.hex()
            if not sync:
                return "NO INIT RESPONSE", "no sync byte after the 5-baud " \
                                           "address 0x01", r
            if sync != b"\x55\xEF\x8F":
                return "BAD KEYBYTES", "sync/keybytes %s (want 55ef8f)" \
                    % sync.hex(), r
            link.stage = "kwp keybyte complement"
            p.write(b"\x70")
            echo = p.read(1, 0.3)
            fe = p.read(1, 0.3)
            self.raw(link, "keybyte complement", b"\x70", echo + fe)
            r["complement"] = fe.hex()
            if fe != b"\xFE":
                return "NO COMPLEMENT", "ECU complement %r (want fe), echo " \
                    "%r" % (fe.hex(), echo.hex()), r
        else:
            # ISO 14230 FAST INIT (2026-10-13, ME711_OBD_KLINE.md 6.2): the
            # tester asserts the wake-up, so it does not need the quiet line
            # the 5-baud byte needs
            link.stage = "kwp fast init"
            p.wakeup()
            self.raw(link, "fast init wake-up", b"", b"")
        d = self.kwp_req(link, b"\x81", "kwp StartCommunication")
        if not d or d[0] != 0xC1:
            if kind == "fast":
                return "NO INIT RESPONSE", "no answer to a fast init", r
            return "STARTCOMM FAILED", "StartCommunication reply %r" % (
                d.hex() if d is not None else None), r
        d = self.kwp_req(link, b"\xB0HC", "kwp IDENTIFY")
        if not d or d[0] != 0xF0:
            return "IDENTIFY FAILED", "IDENTIFY reply %r" % (
                d.hex() if d is not None else None), r
        r["identify"] = d[1:].decode("latin1", "replace")
        return "IDENTIFIED", "", r

    def kwp_req(self, link, data, stage, timeout=0.5):
        p = link.p
        link.stage = stage
        f = bytes([0x80 | len(data), 0x01, 0xF1]) + data
        f += bytes([sum(f) & 0xFF])
        t0 = time.perf_counter()
        p.write(f)
        e = p.read(len(f), 0.3)
        h = p.read(1, timeout)
        if not h:
            self.raw(link, stage, f, e)
            link.log(stage, False, "timeout (echo %s)" % ("ok" if e == f
                                                           else e.hex()),
                     (time.perf_counter() - t0) * 1e3, len(e))
            return None
        n = h[0] & 0x3F
        rest = p.read(2 + n + 1, 0.3)
        fr = h + rest
        self.raw(link, stage, f, e + fr)
        ok = len(fr) == 3 + n + 1 and (sum(fr[:-1]) & 0xFF) == fr[-1]
        link.log(stage, ok, None if ok else "bad frame %s" % fr.hex(),
                 (time.perf_counter() - t0) * 1e3, len(fr))
        return fr[3:3 + n] if ok else b""

    def proven(self, link, reads=10):
        """A rate holds when the ECU answers a probe AND data reads at it."""
        n, sig = self.direct_probe(link, 6)
        if not n:
            return None
        link.stage = "rate proof"
        good = sum(link.och(0, 64, retries=0)[0] is not None
                   for _ in range(reads))
        return sig if good >= reads - 1 else None

    def gofast(self, link, rate, r):
        """GOFAST `rate` after IDENTIFY. -> (stage, why, rate_used)"""
        d = self.kwp_req(link, bytes([0xB1, RATE_CODE.get(rate, 0x02)]),
                         "kwp GOFAST %d" % rate)
        if not d or d[0] != 0xF1:
            return "GOFAST FAILED", "GOFAST %d reply %r" % (
                rate, d.hex() if d is not None else None), None
        link.p.set_baud(rate)
        link.stage = "after GOFAST %d" % rate
        sig = self.proven(link)
        if sig:
            r["signature"] = sig
            return "OK", "", rate
        if rate == 10400:
            return "TIMEOUT AFTER TRANSITION", "no data at 10400", None
        # the line does not carry `rate`: the ECU goes back to 10400 by
        # itself after 2 s without a valid request (and stays LOCKED there)
        link.stage = "10400 fallback"
        time.sleep(2.3)
        link.p.set_baud(10400)
        sig = self.proven(link, 4)
        if sig:
            r["signature"] = sig
            return "FALLBACK", "%d does not hold, 10400 does" % rate, 10400
        return "TIMEOUT AFTER TRANSITION", ("no CRC-valid reply at %d after "
                                            "GOFAST, nor at 10400" % rate), None

    def kwp(self, link, rate):
        """One entry (5-baud, else fast init) and GOFAST `rate` (the direct
        path and the key-cycle test). -> (stage, why, r)"""
        stage, why, r = self.enter(link, "5baud", 0.0)
        if stage == "NO INIT RESPONSE":
            stage, why, r = self.enter(link, "fast", 0.0)
        if stage != "IDENTIFIED":
            return stage, why, r
        stage, why, used = self.gofast(link, rate, r)
        if stage == "FALLBACK":
            self.s.say("KLINE: %s - logging at 10400 (slow)" % why)
            stage = "OK"
        r["rate_used"] = used or rate
        return stage, why, r

    def sweep(self, link):
        """The OBD path: every entry, every rate. -> (stage, why, r, tries)"""
        tries = []
        last = ("NO INIT RESPONSE", "nothing tried", {})
        for rnd in range(1, 4):
            for label, kind, idle in self.ENTRIES:
                stage, why, r = self.enter(link, kind, idle)
                tries.append({"round": rnd, "entry": label, "stage": stage,
                              "detail": why, "sync": r.get("sync")})
                self.s.say("KLINE: OBD round %d, %s: %s%s" % (
                    rnd, label, stage, (" - " + why) if why else ""))
                last = (stage, why, r)
                if stage != "IDENTIFIED":
                    continue
                # the entry works: the rate is the question now
                fell_back = False
                for i, rate in enumerate(self.FAST_RATES):
                    if i:
                        stage, why, r = self.enter(link, kind, 0.5)
                        if stage != "IDENTIFIED":
                            tries.append({"rate": rate, "stage": stage,
                                          "detail": why})
                            continue
                    stage, why, used = self.gofast(link, rate, r)
                    tries.append({"entry": label, "rate": rate,
                                  "stage": stage, "detail": why})
                    self.s.say("KLINE: OBD %s GOFAST %d: %s%s" % (
                        label, rate, stage, (" - " + why) if why else ""))
                    if stage == "OK":
                        r["rate_used"] = rate
                        return "OK", "", r, tries
                    fell_back |= stage == "FALLBACK"
                    last = (stage, why, r)
                if fell_back:
                    # no fast rate holds: 10400 does - a fresh entry, stay
                    stage, why, r = self.enter(link, kind, 0.5)
                    if stage == "IDENTIFIED":
                        stage, why, used = self.gofast(link, 10400, r)
                        tries.append({"entry": label, "rate": 10400,
                                      "stage": stage, "detail": why})
                        if stage == "OK":
                            r["rate_used"] = 10400
                            self.s.say("KLINE: no fast rate holds on this "
                                       "line - logging at 10400 (slow)")
                            return "OK", "", r, tries
                    last = (stage, why, r)
                return last + (tries,)    # the init works, the rates do not
        return last + (tries,)

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
        if path != "OBD":
            n, sig = self.direct_probe(link)
            if n:
                res.update(stage="OK", how="direct %d baud" % self.baud,
                           attempts=n, signature=sig)
                return link, res
            res["direct_probe"] = "no reply at %d baud" % self.baud
            self.s.say("KLINE: %s path - no reply to a direct probe at %d; "
                       "trying the VAG/KWP cold init" % (path, self.baud))
            for att in range(1, 3):
                stage, why, r = self.kwp(link, self.baud)
                res.update(kwp=r, stage=stage, detail=why, kwp_attempts=att)
                if stage == "OK":
                    res["how"] = "KWP %s -> %d" % (r.get("entry", "5-baud"),
                                                   r.get("rate_used",
                                                         self.baud))
                    return link, res
                time.sleep(0.4)
            port.close()
            return None, res
        # THE OBD PATH: no TunerStudio probes first - through the instrument
        # cluster the car's 115200 probes only ever arrived as framing errors
        # (5 sessions) - straight to the vehicle entry, as a VAG tester does.
        stage, why, r, tries = self.sweep(link)
        res.update(kwp=r, stage=stage, detail=why, sweep=tries)
        if stage == "OK":
            res["how"] = "KWP %s -> %d" % (r.get("entry", "5-baud"),
                                           r.get("rate_used", 0))
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

    def run(self, block_hint=1248, quality=True, keycycle=True):
        out = {}
        # 2026-10-11 car: both OBD attempts ran with the ECU UNPOWERED (its
        # boot history puts the first boot in the car a minute later); only
        # the KKL - fed from OBD pin 16 - echoed. Nothing on the K-line can
        # tell "ignition off" from "wrong wire", so ask first.
        self.ask("Ignition ON (engine off): the ECU must be powered for the "
                 "K-line test. Press Enter when it is on")
        link, r1 = self.attempt(self.first_path)
        out[self.first_path] = r1
        if link is None and self.first_path == "OBD":
            self.s.say("")
            self.s.say("OBD: the ECU did not answer (stage: %s%s)" % (
                r1["stage"], (" - " + r1["detail"]) if r1.get("detail") else ""))
            # 2026-10-13 car: the operator HAD the ignition on and the cable
            # verified - a hint that blames them is wrong. State the facts.
            self.s.say("     The KKL's own echo came back (the cable reaches the "
                       "OBD port); the ECU did not answer the 5-baud address "
                       "or fast init.")
            if self.ask("Press Enter to try OBD again (s + Enter: skip)",
                        allow_skip=True):
                link, r1b = self.attempt("OBD")
                out["OBD (retry)"] = r1b
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
            if keycycle:
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

    def boot_history(self, tag):
        """The ECU's own ring of the last 16 boots (why each boot ended, KL15,
        minimum battery): at session start and end, so a reset during a
        crank is on record even when the link dropped (2026-10-10 car)."""
        body, err, _ = self.link.och(self.block + VC.BH_EXT_OFF, VC.BH_BYTES)
        if body is None or len(body) != VC.BH_BYTES or body[:2] != b"BH":
            self.s.say("BOOT HISTORY (%s): not readable - %s" % (tag, err))
            return
        (self.s.dir / ("boothist_%s.bin" % tag)).write_bytes(body)
        recs = VC.decode_boothist(body)
        self.s.meta.setdefault("boot_history", {})[tag] = recs
        self.s.save_meta()
        self.s.say("BOOT HISTORY (%s): %d boots recorded" % (tag, len(recs)))
        return recs

    def witness_live(self):
        """The LIVE half of the reset witness (hcrtmon711.c updates it all
        the time): S5500 frame counters and worst gap, monitoring
        mismatches, worst main-loop pass, watchdog gap, stack peaks. Logged
        every slow cycle (witness.csv), so the minutes BEFORE a reset show
        their trend, not only the last state. None when unreadable."""
        try:
            body, _err, _ = self.link.och(self.block + EXT_WITNESS, 128)
        except Exception:                 # a fake link in a unit test
            return None
        if body is None or len(body) != 128:
            return None
        w = [(body[i] << 8) | body[i + 1] for i in range(0, 64, 2)]
        d = dict(zip(WT_FIELDS, w[:len(WT_FIELDS)]))
        return d if d.get("magic") == 0x5257 else None

    def reset_witness(self, tag):
        """What the ECU saw last before its previous reset (hcrtmon711.c):
        battery, rpm, the S5500 frame counters and worst gap, the monitoring
        mismatches, the worst main-loop pass. Read at session start and after
        every reboot; printed when the boot before left one."""
        try:
            body, err, _ = self.link.och(self.block + EXT_WITNESS, 128)
        except Exception as ex:           # a fake link in a unit test
            body, err = None, str(ex)
        if body is None or len(body) != 128:
            self.s.say("RESET WITNESS (%s): not readable - %s" % (tag, err))
            return None
        w = [(body[i] << 8) | body[i + 1] for i in range(0, 128, 2)]
        live = dict(zip(WT_FIELDS, w[:len(WT_FIELDS)]))
        prev = dict(zip(WT_FIELDS, w[32:32 + len(WT_FIELDS)]))
        (self.s.dir / ("reset_witness_%s.bin" % tag)).write_bytes(bytes(body))
        self.s.meta.setdefault("reset_witness", {})[tag] = {"live": live,
                                                            "prev": prev}
        self.s.save_meta()
        if prev.get("magic") == 0x5257:
            self.s.say(
                "RESET WITNESS (%s) - the last state BEFORE this boot: uptime "
                "%d ms (16-bit: modulo 65.5 s), %d rpm, battery %.1f V, S5500 frames ok %d / checksum "
                "errors %d / timeouts %d, worst S5500 gap %d ms, monitoring "
                "mismatches %d (health/expect 0x%04X), worst main-loop pass "
                "%.1f ms, watchdog gap %d ms, ETB status 0x%04X; S5500 "
                "period %.2f..%.2f ms, >10.5 ms %d, >11 ms %d, >12 ms %d, "
                ">15 ms %d, <9.5 ms %d"
                % (tag, prev["uptime_ms"], prev["rpm"], prev["batt_dv"] / 10.0,
                   prev["asic_run_ok"], prev["asic_csum_err"],
                   prev["asic_timeouts"], prev["s5500_gap_max_ms"],
                   prev["umkom_mismatch"], prev["umkom_health_expect"],
                   prev["main_pass_max_T"] * 0.0008, prev["wdt_gap_max_ms"],
                   prev["etb_status"], prev["s5500_per_min_T"] * 0.0008,
                   prev["s5500_per_max_T"] * 0.0008, prev["s5500_n_gt10_5ms"],
                   prev["s5500_n_gt11ms"], prev["s5500_n_gt12ms"],
                   prev["s5500_n_gt15ms"], prev["s5500_n_lt9_5ms"]))
        else:
            self.s.say("RESET WITNESS (%s): no record of the boot before" % tag)
        return prev

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

    # ---- 2026-10-10 guided session: named page fields in RAM -------------
    # Through the firmware's own TunerStudio path ('R' read, 'W' write ->
    # hcts_cfg_write -> the config manager), exactly as a TunerStudio edit.
    # NEVER a Burn: nothing here sends 'B'.
    def constants(self):
        """name -> (kind, signed, width, offset, lo_bit, hi_bit, count)"""
        if getattr(self, "_consts", None) is None:
            import re
            txt = self.ini_path.read_text(encoding="utf-8", errors="replace")
            body = txt.split("[Constants]", 1)[1].split("\n[", 1)[0]
            out = {}
            for line in body.splitlines():
                m = re.match(r"\s*(\w+)\s*=\s*(scalar|bits|array)\s*,\s*([US])"
                             r"(\d\d)\s*,\s*(\d+)\s*,(.*)", line)
                if not m:
                    continue
                kind, sgn, w = m.group(2), m.group(3) == "S", int(m.group(4)) // 8
                off, rest = int(m.group(5)), m.group(6)
                lo = hi = None
                cnt = 1
                if kind == "bits":
                    bm = re.match(r"\s*\[(\d+):(\d+)\]", rest)
                    lo, hi = int(bm.group(1)), int(bm.group(2))
                elif kind == "array":
                    am = re.match(r"\s*\[\s*(\d+)(?:\s*x\s*(\d+))?\s*\]", rest)
                    cnt = int(am.group(1)) * int(am.group(2) or 1)
                out[m.group(1)] = (kind, sgn, w, off, lo, hi, cnt)
            self._consts = out
        return self._consts

    def read_field(self, name):
        kind, sgn, w, off, lo, hi, _n = self.constants()[name]
        body, err, _ = self.link.request(b"R" + off.to_bytes(2, "big")
                                         + w.to_bytes(2, "big"), 1.0, 2)
        if body is None or len(body) != w:
            return None
        v = int.from_bytes(body, "big", signed=sgn)
        if kind == "bits":
            v = (v >> lo) & ((1 << (hi - lo + 1)) - 1)
        return v

    def write_field(self, name, value):
        """-> the value read back (None if the link failed)."""
        kind, sgn, w, off, lo, hi, _n = self.constants()[name]
        if kind == "bits":
            body, err, _ = self.link.request(b"R" + off.to_bytes(2, "big")
                                             + w.to_bytes(2, "big"), 1.0, 2)
            if body is None or len(body) != w:
                return None
            raw = int.from_bytes(body, "big")
            mask = ((1 << (hi - lo + 1)) - 1) << lo
            raw = (raw & ~mask) | ((int(value) << lo) & mask)
            data = raw.to_bytes(w, "big")
        else:
            data = int(value).to_bytes(w, "big", signed=sgn)
        self.write_bytes(off, data)
        return self.read_field(name)

    def write_bytes(self, off, data):
        for i in range(0, len(data), 32):
            body, err, _ = self.link.request(b"W" + (off + i).to_bytes(2, "big")
                                             + data[i:i + 32], 1.0, 2)
            if body is None:
                return False
        return True

    def field_at(self, off):
        """The page field (name or name[i]) that holds byte `off`."""
        for name, (kind, _s, w, o, _lo, _hi, cnt) in self.constants().items():
            if o <= off < o + w * cnt:
                return name if cnt == 1 else "%s[%d]" % (name, (off - o) // w)
        return "page byte %d" % off

    def scalar(self, name):
        """One output channel, read on its own (None if absent/unreadable)."""
        s = self.ini.scalars.get(name)
        if not s:
            return None
        v, _err, _ms = self.window(s[1], VC.SIZES[s[0]])
        return None if v is None else v.get(name)


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
        out["ok"] = ok
        why_txt = ""
        if not ok and "NOT A STOP" in out["why"]:
            why_txt = (" - the push moved TPS1 %s counts, limit %s (distance "
                       "from rest %s): refused as not a stop; these values "
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
                 duration=None, profile="max", rates=None, guided=False):
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
        # 2026-10-10 GUIDED SESSION: one recorder for every phase. Each row
        # also carries the phase and the operator's step marker, and - when
        # `keep` is a list - the MERGED latest values of every group are kept
        # in memory so the phase can judge what it just recorded. `stop_when`
        # (a callable) ends a recording on a condition or the operator's
        # ENTER; the session-start snapshot is taken once.
        self.guided = guided
        self.phase = ""
        self.marker = ""
        self.keep = None
        self.keep_events = None
        self.latest = {}
        self.stop_when = None
        self.started = False
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
        self.on_reboot = None     # the guided session re-applies RAM tests
        self.ko = None            # the key-off being followed (keyoff_*)
        self.keyoffs = []

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
        if reason == "reboot":
            self.e.reset_witness("reboot_%d" % self.stats["reboots"])
            if self.on_reboot is not None:
                self.on_reboot()
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

    # ------------------------------------------- THE KEY-OFF CHECK (9a) ----
    # 2026-10-15, owner: the recorder checks every key-off by itself, no
    # prompts: how long run-on held the ECU up, whether a pending Burn
    # finished, whether the ECU came back with a reboot and why (its own
    # boot history), and how long the hot restart took. One verdict each.
    RO = {0: "RUN", 1: "HOLD", 2: "RELEASED", 3: "TIMEOUT",
          4: "not configured", 5: "booted during key-off"}

    def keyoff_feed(self, row):
        ro = row.get("runOn")
        if ro is None:
            return
        ro = int(ro)
        off, st = (ro >> 8) & 1, ro & 255
        ko = self.ko
        if off and (ko is None or ko.get("done")):
            nst = int(row.get("nvmState") or 0) & 0xFF
            self.ko = ko = {
                "t_off": self.s.t(), "rpm": self.latest.get("RPMValue"),
                "nvm_state": nst, "gen": row.get("nvmGeneration"),
                "commits": row.get("nvmCommits"), "states": [],
                "boot": self.boot}
            self.s.say("KEY-OFF: seen at %.1f s (rpm %s)%s" % (
                ko["t_off"], ko["rpm"],
                " - a Burn is PENDING" if nst == 2 else ""))
        if ko is None or ko.get("done") or "t_drop" in ko:
            return
        name = self.RO.get(st, st)
        if not ko["states"] or ko["states"][-1] != name:
            ko["states"].append(name)
        ko["run_on_ms"] = row.get("runOnMs")
        ko["gen_now"] = row.get("nvmGeneration")
        ko["nvm_state_now"] = int(row.get("nvmState") or 0) & 0xFF
        if not off:
            ko["back_on_s"] = round(self.s.t() - ko["t_off"], 1)
            if self.boot is not None and ko.get("boot") is not None                     and self.boot != ko["boot"]:
                # 2026-10-15 car: this row came from a NEW boot - the ECU
                # powered down during the key-off, it did not stay up
                ko["powered_down"] = True
                self.s.say("KEY-OFF: the key came back ON after %.1f s - the "
                           "ECU had POWERED DOWN (boot #%s -> #%s, run-on %s)"
                           % (ko["back_on_s"], ko["boot"], self.boot,
                              " > ".join(ko["states"])))
                self.keyoff_close("powered down, key back on")
                return
            self.s.say("KEY-OFF: the key came back ON after %.1f s - the ECU "
                       "stayed up (run-on %s)" % (ko["back_on_s"],
                                                   " > ".join(ko["states"])))
            self.keyoff_close("key back on before power-down")

    def keyoff_link_lost(self):
        ko = self.ko
        if ko and not ko.get("done") and "t_drop" not in ko:
            ko["t_drop"] = self.s.t()
            ko["run_on_s"] = round(ko["t_drop"] - ko["t_off"], 1)
            self.s.say("KEY-OFF: the ECU went quiet %.1f s after the key-off "
                       "(run-on %s)" % (ko["run_on_s"],
                                         " > ".join(ko["states"]) or "?"))

    def keyoff_link_back(self, entry):
        ko = self.ko
        if not ko or ko.get("done") or "t_drop" not in ko:
            return
        ko["t_back"] = self.s.t()
        ko["down_s"] = round(ko["t_back"] - ko["t_drop"], 1)
        if entry:
            ko["gen_after"] = entry.get("nvm_generation")
            ko["boot_after"] = entry.get("boot_count")
        recs = None
        try:
            recs = self.e.boot_history("keyoff_%d" % (len(self.keyoffs) + 1))
        except Exception:
            pass
        if recs:
            last = recs[-1]
            ko["reboot"] = {k: last.get(k) for k in (
                "reset_kind", "raw_reset", "prev_uptime_ms", "prev_runon",
                "prev_min_batt_v", "kl15_at_boot", "prev_held_power")}
        rb = ko.get("reboot") or {}
        self.s.say("KEY-OFF: the ECU is back after %.1f s down - boot #%s, "
                   "reset %s, previous run-on %s" % (
                       ko["down_s"], ko.get("boot_after"),
                       rb.get("reset_kind", "?"), rb.get("prev_runon", "?")))
        ko["waiting_restart"] = True

    def keyoff_engine(self, state):
        ko = self.ko
        if not ko or not ko.get("waiting_restart"):
            return
        if state == "CRANKING" and "t_crank" not in ko:
            ko["t_crank"] = self.s.t()
        elif state == "RUNNING":
            ko["t_run"] = self.s.t()
            ko["hot_restart_s"] = round(
                ko["t_run"] - ko.get("t_crank", ko["t_run"]), 2)
            self.s.say("HOT RESTART: running %.2f s after cranking began"
                       % ko["hot_restart_s"])
            self.keyoff_close("hot restart")

    def keyoff_close(self, how):
        ko = self.ko
        if not ko or ko.get("done"):
            return
        ko["done"] = True
        ko["how"] = how
        held = "HOLD" in ko["states"] or (ko.get("run_on_s") or 0) >= 1.0
        burn = ""
        ok = True
        if ko["nvm_state"] == 2:
            g0 = ko.get("gen")
            g1 = ko.get("gen_after", ko.get("gen_now"))
            fin = g0 is not None and g1 is not None and g1 != g0
            burn = "; the pending Burn %s" % ("FINISHED (gen %s -> %s)"
                                              % (g0, g1) if fin
                                              else "did NOT finish")
            ok &= fin
        rb = ko.get("reboot") or {}
        txt = ("run-on %s%s%s%s%s" % (
            " > ".join(ko["states"]) or "not seen",
            (", ECU down after %.1f s" % ko["run_on_s"])
            if "run_on_s" in ko else "",
            burn,
            ("; came back: %s, previous run-on %s" % (
                rb.get("reset_kind"), rb.get("prev_runon"))) if rb else "",
            ("; hot restart %.2f s" % ko["hot_restart_s"])
            if "hot_restart_s" in ko else
            (" (key back on, %.1f s%s)" % (
                ko["back_on_s"],
                ", the ECU had powered down" if ko.get("powered_down")
                else "")
             if "back_on_s" in ko else "")))
        ok &= held or "back_on_s" in ko
        ko["verdict"] = "PASS" if ok else "WARNING"
        ko["text"] = txt
        self.s.verdict("KEYOFF", ko["verdict"], txt)
        self.keyoffs.append({k: v for k, v in ko.items()
                             if k != "waiting_restart"})
        self.stats["keyoffs"] = self.keyoffs

    def reconnect(self):
        link = self.e.link
        self.keyoff_link_lost()
        self.stats["drops"] += 1
        t0 = time.monotonic()
        self.s.say("KLINE: DROPOUT - reconnecting")
        link.stage = "runtime reconnect"
        # 2026-10-15 car: over OBD the entry IS the way back (the ECU drops a
        # silent tester's rate after 1.5 s) - re-enter after 1 s, then every
        # 2.5 s; a direct cable keeps the old 5 s
        obd = link.path == "OBD"
        t_kwp = t0 + (1.0 if obd else 5.0)
        while not self._stopped():
            body, err, ms = link.exchange(b"S", 0.4)
            if body is None and self.kwp and time.monotonic() >= t_kwp:
                # an ECU that restarted behind an OBD path that needs the
                # VAG/KWP entry
                t_kwp = time.monotonic() + (2.5 if obd else 5.0)
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
                self.keyoff_link_back(self.snapshot("reconnect"))
                return True
            time.sleep(0.2)
        return False

    def _stopped(self):
        if self.stop.is_set():
            return True
        if self.stop_when is not None and self.stop_when():
            self.stop.set()
            return True
        return False

    def _lead(self):
        lead = [("wall", utc())]
        if self.guided:
            lead += [("phase", self.phase), ("marker", self.marker)]
        return lead

    def _keep(self, row, t, group):
        self.latest.update(row)
        if self.keep is not None and group == "fast":
            k = dict(self.latest)
            k["_t"], k["_m"] = t, self.marker
            self.keep.append(k)

    def run(self):
        e, s = self.e, self.s
        t_end = time.monotonic() + self.duration if self.duration else None
        t_ring = 0.0
        fails = 0
        fast, med, slow = self.g["fast"], self.g["medium"], self.g["slow"]
        if not self.started:
            s.say("RUNTIME: profile %s - fast %s, medium %.2f s, slow %.2f s, "
                  "ring %.2f s" % (self.profile,
                                   "as fast as the link allows"
                                   if not fast.period else "%.2f s" % fast.period,
                                   med.period, slow.period, self.rates["ring"]))
            s.say("RUNTIME: fast %d channels in %d exchange(s) / %d B; medium "
                  "%d in %d / %d B; slow the whole %d-byte block"
                  % (len(fast.names) - len(fast.missing), len(fast.win),
                     fast.bytes, len(med.names) - len(med.missing),
                     len(med.win), med.bytes, e.block))
            for g in (fast, med):
                if g.missing:
                    s.say("RUNTIME: %s - %d channel(s) this .ini does not "
                          "declare, not read: %s" % (g.name, len(g.missing),
                                                     ", ".join(g.missing[:8])))
            self.snapshot("session start")
            self.started = True
        if not self.guided:
            s.say("RUNTIME: recording - key-on, crank, run, stop: anything. "
                  "Press ENTER (or Ctrl+C) to finish.")
        e.link.stage = "runtime"
        t_rate = time.monotonic()
        n_rate = 0
        while not self._stopped():
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
            t = fast.write(row, lead=self._lead())
            self.stats["fast_rows"] = fast.rows
            self._keep(row, t, "fast")
            self.note_changes(row, t)
            n_rate += 1
            if "ecuMs" in row and self.ring:
                self.ring.ms_ref = (int(row["ecuMs"]), t)
            self.check_reboot(row)
            # 2026-10-15 car: runOn is in the fast block too - a key-off the
            # ECU powers down from within one medium period was missed
            self.keyoff_feed(row)
            st = self.engine_state(row)
            if st != self.state:
                s.say("ENGINE: %s (rpm %s)" % (st, row.get("RPMValue")))
                self.state = st
                self.keyoff_engine(st)
            now = time.monotonic()
            if med.due(now):
                v, _err = med.read()
                if v:
                    tm = med.write(v, lead=self._lead()[1:])
                    self._keep(v, tm, "medium")
                    self.note_changes(v, tm)
                    self.keyoff_feed(v)
                    self.stats["medium_rows"] = med.rows
                now = time.monotonic()
            if slow.due(now):
                v, _err = slow.read()
                if v:
                    tl = slow.write(v, lead=self._lead()[1:])
                    self._keep(v, tl, "slow")
                    self.note_changes(v, tl)
                    self.stats["slow_rows"] = slow.rows
                    b = v.get("rstBootCount")
                    if b is not None and self.boot is not None and b != self.boot:
                        self.stats["reboots"] += 1
                        s.say("ECU REBOOTED during the session: boot #%s -> "
                              "#%s" % (self.boot, b))
                        self.snapshot("reboot")
                    self.boot = b if b is not None else self.boot
                wl = e.witness_live() if hasattr(e, "witness_live") else None
                if wl:
                    s.row("witness", ["t"] + list(WT_FIELDS),
                          [s.t()] + [wl.get(k) for k in WT_FIELDS])
                    self.stats["witness_rows"] = \
                        self.stats.get("witness_rows", 0) + 1
                now = time.monotonic()
            if self.ring and now - t_ring >= self.rates["ring"]:
                t_ring = now
                evs = self.ring.poll()
                for ev in evs:
                    s.say(ev["text"])
                    if self.keep_events is not None:
                        ev["_t"], ev["_m"] = s.t(), self.marker
                        self.keep_events.append(ev)
                self.ring.write(evs)
                self.stats["events"] += len(evs)
            if now - t_rate >= 10.0 and not self.guided:
                s.say("RUNTIME: %.1f fast rows/s (rtt %.0f ms), %d medium, "
                      "%d slow, %d events" % (
                          n_rate / (now - t_rate), row.get("_rtt_ms", 0),
                          med.rows, slow.rows, self.stats["events"]))
                t_rate, n_rate = now, 0
        if self.ko and not self.ko.get("done") and "t_drop" in self.ko:
            self.keyoff_close("session ended before a restart")
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


# ======================================== THE GUIDED SESSION (2026-10-10) ===
# The owner's brief: ONE guided session that walks through testing and
# logging every system the engine needs to start, run and drive, and says at
# the end what works and what does not. It REUSES the classes above: Kline
# (link), Ecu (identity, page, fields), Ring (event ring), Autocal (ETB) and
# Runtime (the multi-rate recorder - every phase records through it, with the
# phase and the step marker on every row, into the same CSVs).
#
# SAFETY: every step that drives anything prints the safety condition and
# waits for ENTER; every page field the session writes goes into a ledger
# with its ORIGINAL value; Ctrl+C or any failure sends '!X' and restores the
# page to its session-start state (except what the operator chose to keep);
# NOTHING IS EVER BURNED - at the end every RAM change is listed and the
# operator chooses keep or revert.
#
# dbwEnable, injStrategy, ignStrategy and camPhaseLevel are RPM_ZERO_APPLY
# fields (hanicore_config_def.py): written to DESIRED, applied only while
# the engine is STOPPED. So the session stops the engine, writes, waits for
# cfgDirtyGroups to read 0 (applied), and only then restarts.

GUIDED_PHASES = ("kline", "preflight", "pedal", "dbw", "start", "idle",
                 "drive", "strategy", "keyoff", "report")
PHASE_NO = {"preflight": 0, "kline": 1, "pedal": 2, "dbw": 3, "start": 4,
            "idle": 5, "drive": 6, "strategy": 7, "keyoff": 8, "report": 9}
PHASE_TITLE = {
    "kline": "K-LINE CONNECTION", "preflight": "PREFLIGHT (key on, engine off)",
    "pedal": "PEDAL AND THROTTLE SENSORS", "dbw": "ELECTRONIC THROTTLE, ENGINE OFF",
    "start": "ENGINE START", "idle": "IDLE (60 s, throttle on limp spring)",
    "drive": "ELECTRONIC THROTTLE ON, ENGINE RUNNING",
    "strategy": "INJECTION / CAM STRATEGY COMPARISON (automatic, ~10 min)",
    "keyoff": "KEY-OFF, RUN-ON, HOT RESTART", "report": "REPORT"}
SAFETY = ("SAFETY: gear in NEUTRAL (or P), handbrake ON, nobody near the "
          "engine bay or the throttle body.")
LAM_WHY_SHORT = {0: "valid", 1: "off", 2: "latched fault",
                 3: "controller not answering", 4: "calibrating",
                 5: "waiting for the engine", 6: "supply", 7: "preheat",
                 8: "heating", 9: "settling", 10: "pump check",
                 11: "controller diagnosis", 12: "pump saturated",
                 13: "Ri signal missing", 14: "bench hold",
                 15: "signal stuck", 16: "HELD (last value)"}


def _v(row, *names):
    for n in names:
        v = row.get(n)
        if v is not None:
            return v
    return None


def _rpm(row):
    return float(_v(row, "RPMValue", "rpm") or 0)


def _running(row):
    return bool(int(_v(row, "engineFlags") or 0) & 1) or _rpm(row) >= 400


def _why1(row):
    w = _v(row, "lamWhy")
    return None if w is None else int(w) & 255


def _mean(v):
    return sum(v) / len(v) if v else None


def _sd(v):
    if len(v) < 2:
        return 0.0
    m = _mean(v)
    return (sum((x - m) ** 2 for x in v) / (len(v) - 1)) ** 0.5


def image_identity(version, manifest=None):
    """The ECU's 'V' text names its build (" build XXXXXXXX", the source
    hash the build writes, 2026-10-11). -> (status, text): PASS when it is
    the build this kit / checkout carries (bins/hanicore manifest), FAIL on
    a mismatch or an image that does not say."""
    import re
    if manifest is None:
        try:
            import me711_image as _PI
            manifest = _PI.metadata() if _PI.MANIFEST.exists() else {}
        except Exception:
            manifest = {}
    m = re.search(r"build ([0-9A-F]{8})", version or "")
    ecu = m.group(1) if m else None
    want = manifest.get("build_id")
    sha = (manifest.get("sha256") or "?")[:8].upper()
    if not want:
        return "WARN", ("ECU says %r; this kit has no build id to compare "
                        "with" % version)
    if ecu is None:
        return "FAIL", ("the ECU does not name its build (%r) - it is NOT the "
                        "kit's image %s (build %s); flash the kit's image"
                        % (version, sha, want))
    if ecu != want:
        return "FAIL", ("the ECU runs build %s, this kit is for build %s "
                        "(image %s) - flash the kit's image" % (ecu, want, sha))
    return "PASS", "build %s = this kit's image %s (%s)" % (ecu, sha, version)


def routed(cfg, key):
    """1-based output channels a page routes (pin != 255), cylinders only."""
    n = int(cfg.get("cylinders") or 0)
    pins = cfg.get(key) or []
    return [i + 1 for i in range(min(n, 8, len(pins)))
            if pins[i] is not None and int(pins[i]) != 255]


def check_injectors(rows, cfg):
    """EVERY routed injector channel must open while the engine runs - the
    check the 2026-10-10 semi-sequential bug (channels 2 and 4 dead for the
    whole run) needed and nothing had."""
    run = [r for r in rows if _running(r)
           and not int(_v(r, "fuelCutFlags", "fuelCut") or 0)]
    chans = routed(cfg, "injPin")
    if not run:
        return "FAIL", "the engine was not running - no injector evidence", {}
    per, dead, missing = {}, [], []
    for c in chans:
        vals = [r.get("inj%dDeliveredUs" % c) for r in run]
        vals = [float(x) for x in vals if x is not None]
        if not vals:
            missing.append(c)
            continue
        live = sum(1 for x in vals if x > 0) / len(vals)
        per[c] = {"open_fraction": round(live, 2),
                  "mean_us": round(_mean(vals))}
        if live < 0.5:
            dead.append(c)
    pins = cfg.get("injPin") or []
    if dead:
        return "FAIL", ("injector channel(s) %s NEVER (or rarely) opened "
                        "while running (cavity %s) - those cylinders get no "
                        "fuel; this is the semi-sequential bug class"
                        % (", ".join(map(str, dead)),
                           ", ".join(str(int(pins[c - 1])) for c in dead))), per
    if missing or not per:
        return "WARN", ("per-channel injector telemetry missing for %s"
                        % (missing or chans)), per
    means = sorted(p["mean_us"] for p in per.values())
    med = means[len(means) // 2] or 1
    odd = [c for c, p in per.items() if p["mean_us"] < 0.7 * med
           or p["mean_us"] > 1.3 * med]
    if odd:
        return "WARN", ("all %d injectors open, but channel(s) %s differ by "
                        "more than 30 %% from the others (%s)"
                        % (len(per), odd, {c: p["mean_us"] for c, p in
                                           per.items()})), per
    return "PASS", ("all %d routed injectors open (mean pulse %s us)"
                    % (len(per), med)), per


def check_coils(rows, cfg):
    run = [r for r in rows if _running(r)]
    seen = 0
    for r in run:
        seen |= int(_v(r, "ignOnMask") or 0)
    chans = routed(cfg, "ignPin")
    if int(cfg.get("_ignStrategy") or 0) == 0:     # wasted paired: leads only
        return "PASS", ("coil outputs seen charging: %s (paired coils: only "
                        "the pair leads fire)" % [b + 1 for b in range(8)
                                                  if seen >> b & 1]), seen
    miss = [c for c in chans if not seen >> (c - 1) & 1]
    if not run:
        return "FAIL", "the engine was not running", seen
    if miss:
        return "WARN", ("coil output(s) %s never SEEN charging in %d samples "
                        "(sampled, not a proof of a dead coil - check the "
                        "misfire / rpm stability result)" % (miss, len(run))), seen
    return "PASS", "every routed coil (%s) seen charging" % chans, seen


def check_scheduler(rows):
    run = [r for r in rows if _running(r)]
    if len(run) < 2:
        return "WARN", "too little running data", {}
    d = {}
    for n in ("schedulerLate", "schedulerMissed", "schedOverdwell"):
        a, b = _v(run[0], n), _v(run[-1], n)
        d[n] = (int(b) - int(a)) & 0xFFFF if a is not None and b is not None else None
    if d.get("schedOverdwell"):
        return "FAIL", ("%d coil(s) had to be released by the overdwell "
                        "watch - a spark event was missing" % d["schedOverdwell"]), d
    if d.get("schedulerMissed") or d.get("schedulerLate"):
        return "WARN", ("scheduler: %s late, %s missed events while running"
                        % (d.get("schedulerLate"), d.get("schedulerMissed"))), d
    return "PASS", "scheduler: 0 late, 0 missed, 0 overdwell", d


def check_rpm(rows):
    run = [r for r in rows if _running(r)]
    rpms = [_rpm(r) for r in run]
    if not rpms:
        return "FAIL", "the engine did not run", {}
    first = rows.index(run[0])
    stalled = any(_rpm(r) < 100 for r in rows[first:])
    m, sd = _mean(rpms), _sd(rpms)
    pct = 100.0 * sd / m if m else 0.0
    info = {"mean": round(m), "sd_pct": round(pct, 1), "stalled": stalled}
    if stalled:
        return "FAIL", "the engine STALLED (mean %d rpm before)" % m, info
    st = "PASS" if pct <= 5 else ("WARN" if pct <= 10 else "FAIL")
    return st, ("rpm %d, unsteadiness %.1f %% (sd/mean; <= 5 good, > 10 rough)"
                % (m, pct)), info


def check_wideband(rows, cfg):
    if int(cfg.get("_lambda1Source") or 0) == 0 and not any(
            _why1(r) not in (None, 1) for r in rows):
        return "SKIP", "no on-board wideband configured", {}
    whys = [(r.get("_t"), _why1(r), r.get("cjTmo")) for r in rows]
    valid_at = [t for t, w, _c in whys if w == 0]
    held = sum(1 for (_a, w0, _b), (_c, w1, _d) in zip(whys, whys[1:])
               if w1 == 16 and w0 != 16)
    drops = []
    seen = False
    for (t0, w0, c0), (t1, w1, c1) in zip(whys, whys[1:]):
        if w0 == 0:
            seen = True
        if seen and w0 in (0, 16) and w1 not in (0, 16, None):
            tmo = (c0 is not None and c1 is not None
                   and (int(c1) & 255) != (int(c0) & 255))
            drops.append({"t": t1, "why": LAM_WHY_SHORT.get(w1, w1),
                          "cj120_timeout": tmo})
    info = {"valid_rows": len(valid_at), "dropouts": drops, "held": held}
    if not valid_at:
        last = whys[-1][1] if whys else None
        txt = LAM_WHY_SHORT.get(last, last)
        st = "WARN" if last in (7, 8, 9, 10) else "FAIL"
        return st, "lambda never became a measurement (now: %s)" % txt, info
    tail = ("; %d short gap(s) carried by the HOLD (last value shown, not "
            "used for fuel)" % held) if held else ""
    if not drops:
        return "PASS", "lambda valid and STAYED valid%s" % tail, info
    reasons = ", ".join("%s%s" % (d["why"], " (CJ120 timeout)"
                                  if d["cj120_timeout"] else "")
                        for d in drops[:4])
    st = "WARN" if len(drops) <= 2 else "FAIL"
    return st, ("lambda DROPPED OUT %d time(s): %s%s"
                % (len(drops), reasons, tail)), info


def check_lambda_target(rows):
    pts = [(float(r["lambdaValue"]), float(_v(r, "targetLambda", "lambdaTarget")))
           for r in rows if _running(r) and r.get("lambdaValue")
           and _v(r, "targetLambda", "lambdaTarget")]
    if not pts:
        return "WARN", "no fresh lambda while running - mixture not judged", {}
    m = _mean([a for a, _b in pts])
    tg = _mean([b for _a, b in pts])
    stft = [float(r["stftBank1"]) for r in rows if r.get("stftBank1") is not None]
    info = {"lambda": round(m, 3), "target": round(tg, 3),
            "stft_pct": round(_mean(stft), 1) if stft else None}
    d = m - tg
    st = "PASS" if abs(d) <= 0.05 else ("WARN" if abs(d) <= 0.15 else "FAIL")
    word = "LEAN" if d > 0 else "RICH"
    return st, ("lambda %.3f vs target %.3f (%s by %.3f)%s"
                % (m, tg, word, abs(d), "" if not stft else
                   ", trim %+.1f %%" % _mean(stft))), info


def check_warmup(rows):
    c = [float(r["coolant"]) for r in rows if r.get("coolant") is not None]
    if not c:
        return "WARN", "no coolant reading", {}
    if any(abs(x + 40.0) < 0.05 for x in c):
        return "FAIL", "coolant sensor FAULT (reads -40 C)", {}
    st = "PASS" if c[-1] >= c[0] - 0.5 or c[-1] >= 80 else "WARN"
    return st, "coolant %.1f -> %.1f C" % (c[0], c[-1]), {"from": c[0], "to": c[-1]}


def analyze_tipin(rows, events, t0):
    """One fast tip-in: what happened in the 3 s after the pedal went down,
    and the most likely cause, from the data."""
    pre = [r for r in rows if t0 - 0.6 <= r["_t"] < t0]
    win = [r for r in rows if t0 <= r["_t"] <= t0 + 3.0]
    if not win:
        return {"status": "WARN", "cause": "no data after the tip-in"}
    rpm0 = sorted(_rpm(r) for r in pre)[len(pre) // 2] if pre else _rpm(win[0])
    early = [r for r in win if r["_t"] <= t0 + 1.5]
    rmin = min(_rpm(r) for r in early)
    stall = any(_rpm(r) < 100 for r in win)
    lam = [float(r["lambdaValue"]) for r in win if r.get("lambdaValue")]
    cuts = {"fuelCutFlags": 0, "limpCut": 0, "dbwFaults": 0, "engineFlags": 0}
    for r in win:
        for k in cuts:
            cuts[k] |= int(_v(r, k) or 0)
    sk = [int(r["sparkSkips"]) for r in win if r.get("sparkSkips") is not None]
    skips = (sk[-1] - sk[0]) & 0xFFFF if len(sk) > 1 else 0
    tg = [(r["_t"], float(r.get("dbwTargetX10") or 0),
           float(r.get("dbwActualX10") or 0)) for r in win]
    err = max((abs(a - b) for _t, a, b in tg), default=0.0)
    lag = None
    if tg:
        top = max(a for _t, a, _b in tg)
        for t, a, b in tg:
            if top >= 10 and b >= top - 5:
                lag = round(t - t0, 2)
                break
    timing = [float(r["ignitionTiming"]) for r in win
              if r.get("ignitionTiming") is not None]
    ae = max((float(r.get("aeFuelUs") or 0) for r in win), default=0)
    film = max((float(r.get("wallFilmUs") or 0) for r in win), default=0)
    evs = [e for e in events if e.get("_t") is not None
           and t0 - 0.5 <= e["_t"] <= t0 + 3.5]
    etypes = {e["type"] for e in evs}
    dfco_on_pedal = bool(cuts["engineFlags"] & 32)
    # THE BRIDGE DROPPED (2026-10-11): DBW leaving RUN without a latched
    # fault - a pedal/TPS pair judged suspect for one step drops the bridge
    # and the plate falls to its spring for >= 4 control steps. The AWT's
    # "cut-out on a fast pedal press" (2026-10-10) was this; the fast rows
    # and the ring each see it only when they sample it.
    dst = [int(_v(r, "dbwState") or 0) & 0xFF for r in pre + win]
    was_run = any(x == 2 for x in dst[:max(1, len(pre))])
    drops = sum(1 for a, b in zip(dst, dst[1:]) if a == 2 and b in (1, 3))
    ring_drop = any(e["type"] == "DBW" and ("INIT" in e["text"]
                                            or "FAULT" in e["text"])
                    for e in evs)
    pend = 0
    for r in win:
        pend |= int(_v(r, "dbwPendFaults") or 0)
    cause = None
    if "SYNC_LOSS" in etypes or any("LOST" in e["text"] for e in evs
                                     if e["type"] == "SYNC"):
        cause = "crank sync was LOST (trigger signal)"
    elif cuts["limpCut"]:
        cause = "engine PROTECTION fuel cut: %s" % bits(cuts["limpCut"], LIMP)
        if cuts["dbwFaults"]:
            cause += " - caused by a throttle fault: %s" % bits(
                cuts["dbwFaults"], DBW_FAULT)
    elif cuts["fuelCutFlags"] & ~1 or (cuts["fuelCutFlags"] & 1
                                       and dfco_on_pedal):
        cause = "FUEL CUT: %s%s" % (bits(cuts["fuelCutFlags"], FUEL_CUT),
                                    " while the pedal was pressed"
                                    if cuts["fuelCutFlags"] & 1 else "")
    elif cuts["dbwFaults"]:
        cause = "throttle fault: %s" % bits(cuts["dbwFaults"], DBW_FAULT)
    elif was_run and (drops or ring_drop or pend):
        cause = ("the THROTTLE BRIDGE DROPPED (DBW left RUN%s) - the plate "
                 "fell to its spring; suspect sensor pair: %s"
                 % (" %d time(s)" % drops if drops else "",
                    bits(pend, DBW_FAULT) if pend else "not sampled"))
    elif skips:
        cause = "SPARK cut (%d sparks skipped)" % skips
    elif lam and min(lam) < 0.75:
        cause = ("RICH bog: lambda fell to %.2f - too much transient fuel "
                 "(acceleration enrichment %d us, wall film %d us)"
                 % (min(lam), ae, film))
    elif lam and max(lam) > 1.25:
        cause = ("LEAN stumble: lambda rose to %.2f - not enough transient "
                 "fuel (acceleration enrichment %d us)" % (max(lam), ae))
    elif lag is not None and lag > 0.3:
        cause = "the throttle followed SLOWLY (%.2f s to reach its target)" % lag
    elif rpm0 - rmin > 150:
        cause = ("an rpm drop with no recorded cut - check ignition timing "
                 "(%s..%s deg) and misfire" % (min(timing) if timing else "?",
                                               max(timing) if timing else "?"))
    dip = rpm0 - rmin
    if stall:
        st = "FAIL"
    elif cause and ("CUT" in cause or "LOST" in cause or "fault" in cause
                    or "DROPPED" in cause):
        st = "FAIL"
    elif dip > 200 or cause:
        st = "WARN"
    else:
        st = "PASS"
    return {"status": st, "rpm_before": round(rpm0), "rpm_min": round(rmin),
            "dip": round(dip), "stall": stall,
            "lambda_min": round(min(lam), 3) if lam else None,
            "lambda_max": round(max(lam), 3) if lam else None,
            "cuts": {k: bits(v, {"fuelCutFlags": FUEL_CUT, "limpCut": LIMP,
                                 "dbwFaults": DBW_FAULT,
                                 "engineFlags": FLAGS}[k])
                     for k, v in cuts.items() if v},
            "throttle_err_max": round(err, 1), "throttle_lag_s": lag,
            "dbw_drops": drops, "dbw_pend": bits(pend, DBW_FAULT) if pend else "",
            "timing": [min(timing), max(timing)] if timing else None,
            "ae_us": ae, "wallfilm_us": film,
            "events": [e["text"] for e in evs][:8],
            "cause": cause or "none - the engine took it"}


class Guided:
    """The guided all-in-one session. One instance per run()."""

    def __init__(self, a, sess, kl, link, ecu, ring, ask, choose, stdin_q,
                 resume_state=None):
        self.a, self.s, self.kl, self.link = a, sess, kl, link
        self.e, self.ring, self.ask, self.choose = ecu, ring, ask, choose
        self.q = stdin_q
        self.scale = float(getattr(a, "time_scale", 1.0) or 1.0)
        self.cfg = sess.meta.get("engine_config", {})
        self.rt = Runtime(ecu, sess, ring, threading.Event(), None,
                          profile=getattr(a, "profile", "max"), guided=True)
        self.rt.kwp = kl.kwp if kl else None
        self.rt.on_reboot = self._reapply
        # 2026-10-11: RECORD WHILE A PROMPT WAITS. The car's crank in phase
        # 6 (and the ECU reset during it) and the cam-level-0 crank happened
        # while the tool sat at "press ENTER" and nothing was recorded. With
        # a real keyboard queue the prompt now runs the ordinary recorder
        # until a line is typed.
        self._ask_plain = ask
        if (stdin_q is not None and hasattr(stdin_q, "empty")
                and not hasattr(stdin_q, "answer")
                and not getattr(a, "no_prompt", False)):
            self.ask = self._ask_recording
        st = resume_state or {}
        self.done = list(st.get("done", []))
        self.results = list(st.get("results", []))
        self.ledger = dict(st.get("ledger", {}))
        self.kept = set(st.get("kept", []))
        self.info = dict(st.get("info", {}))
        p0 = sess.dir / "page_session_start.bin"
        if p0.exists():
            self.page0 = p0.read_bytes()
        else:
            self.page0 = ecu.page
            if self.page0:
                p0.write_bytes(self.page0)

    # ---------------------------------------------------------- plumbing --
    def _ask_recording(self, prompt, allow_skip=False):
        self.s.say(">>> " + prompt)
        self.record("prompt", 7200.0, until=lambda _r: not self.q.empty(),
                    enter_stops=False)
        line = self.q.get()
        if allow_skip and line.strip().lower().startswith("s"):
            self.s.say("    skipped")
            return False
        return True

    def _reapply(self):
        """An ECU reset throws away every unburned RAM change (by design:
        only a Burn re-seals the page). Put this session's test settings
        back and SAY so - 2026-10-11 the phase 6 dbwEnable vanished in a
        reset and the drive test ran with the throttle on its spring."""
        for name, ent in sorted(self.ledger.items()):
            if ent.get("now") is None or ent.get("now") == ent.get("original"):
                continue
            cur = self.e.read_field(name)
            if cur != ent["now"]:
                back = self.e.write_field(name, ent["now"])
                self.s.say("RAM: the reset discarded %s - written again: %s "
                           "-> %s" % (name, cur, back))

    def save_state(self):
        (self.s.dir / "guided_state.json").write_text(json.dumps({
            "done": self.done, "results": self.results, "ledger": self.ledger,
            "kept": sorted(self.kept), "info": self.info}, indent=1,
            default=str), encoding="utf-8")

    def verdict(self, system, status, reason, phase=None):
        self.results.append({"phase": phase or self.cur, "system": system,
                             "status": status, "reason": reason})
        self.s.verdict(system, status, reason)
        self.save_state()

    def banner(self, name):
        self.cur = name
        self.s.say("")
        self.s.say("=" * 64)
        self.s.say("PHASE %d: %s" % (PHASE_NO[name], PHASE_TITLE[name]))
        self.s.say("=" * 64)

    def tell(self, *lines):
        for ln in lines:
            self.s.say("    " + ln)

    def enter_pressed(self):
        g = getattr(self.q, "get_nowait", None)
        if g is None:
            return False
        try:
            g()
            return True
        except queue.Empty:
            return False

    def record(self, marker, seconds, until=None, enter_stops=True):
        """Record every group + the ring for `seconds` (scaled), until
        `until(latest)` or the operator's ENTER. -> (rows, events)"""
        rt = self.rt
        rt.phase, rt.marker = self.cur, marker
        rows, evs = [], []
        rt.keep, rt.keep_events = rows, evs
        rt.stop = threading.Event()
        rt.duration = max(0.05, seconds * self.scale)
        rt.stop_when = (lambda: (until is not None and until(rt.latest))
                        or (enter_stops and self.enter_pressed()))
        try:
            rt.run()
        finally:
            rt.keep = rt.keep_events = rt.stop_when = None
        return rows, evs

    def now(self):
        """One merged reading of every group (fast + medium + slow)."""
        row = {}
        for g in ("slow", "medium", "fast"):
            v, _err = self.rt.g[g].read()
            if v:
                row.update(v)
        row["_t"] = self.s.t()
        return row

    def safe_go(self, what):
        self.s.say("")
        self.s.say(">>> " + SAFETY)
        return self.ask("%s - press ENTER to start (s + ENTER skips)" % what,
                        allow_skip=True)

    # ------------------------------------------------- RAM page changes --
    def set_field(self, name, value, why):
        cur = self.e.read_field(name)
        if cur is None:
            return False
        if name not in self.ledger:
            self.ledger[name] = {"original": cur}
        back = self.e.write_field(name, value)
        self.ledger[name].update(now=back, why=why)
        self.s.row("ram_changes", ["t", "phase", "field", "was", "wrote",
                                   "read_back", "why"],
                   [self.s.t(), self.cur, name, cur, value, back, why])
        self.s.say("RAM: %s %s -> %s (%s) - not burned" % (name, cur, back, why))
        self.save_state()
        return back == value

    def burn(self, why):
        """BURN the RAM page to flash - only with the engine STOPPED (owner,
        2026-10-11: the logger burns what passed). Verified: the Burn's
        reply, nvmCommits moving where the image publishes it, and the page
        read back equal to the RAM page before the Burn."""
        if _rpm(self.now()) != 0:
            self.s.say("BURN refused by the tool: the engine is running")
            return False
        before = self.e.link.page()
        c0 = self.e.scalar("nvmCommits")
        body, err, _ms = self.link.request(b"B", 12.0, 0)
        t_end = time.monotonic() + max(0.3, 4.0 * self.scale)
        c1 = c0
        while time.monotonic() < t_end:
            c1 = self.e.scalar("nvmCommits")
            if c0 is None or c1 != c0:
                break
            time.sleep(min(0.2, self.scale))
        after = self.e.link.page()
        ok = (body is not None and (c0 is None or c1 != c0)
              and before is not None and after == before)
        self.s.row("burns", ["t", "phase", "why", "reply", "commits_before",
                             "commits_after", "page_equal", "ok"],
                   [self.s.t(), self.cur, why, "OK" if body is not None
                    else err, c0, c1, int(after == before), int(ok)])
        self.s.say("BURN (%s): %s" % (why, "OK - in flash" if ok else
                                      "FAILED (%s)" % (err or "not verified")))
        self.info.setdefault("burns", []).append({"why": why, "ok": ok})
        if ok:
            self.page0 = after       # the burned page is the new baseline
            (self.s.dir / "page_session_start.bin").write_bytes(after)
            for d in self.ledger.values():
                d["original"] = d.get("now", d["original"])
            self.kept = set()
            self.save_state()
        return ok

    def wait_applied(self, seconds=6.0):
        """RPM_ZERO fields reach the runtime only with the engine stopped:
        cfgDirtyGroups == 0 means the staged groups were applied."""
        t_end = time.monotonic() + max(0.3, seconds * self.scale)
        while time.monotonic() < t_end:
            d = self.e.scalar("cfgDirtyGroups")
            if d == 0:
                return True
            time.sleep(0.1)
        return False

    def page_diff(self):
        """[(offset, old, new)] page bytes that differ from the session start."""
        cur = self.e.link.page()
        if not cur or not self.page0:
            return None, cur
        return [(i, a, b) for i, (a, b) in enumerate(zip(self.page0, cur))
                if a != b], cur

    def revert(self, diffs, keep=()):
        """Write the session-start bytes back, run by run, except `keep`."""
        runs, cur = [], None
        for off, old, _new in diffs:
            if off in keep:
                continue
            if cur and off == cur[0] + len(cur[1]):
                cur[1].append(old)
            else:
                cur = [off, bytearray([old])]
                runs.append(cur)
        ok = all(self.e.write_bytes(o, bytes(b)) for o, b in runs)
        for name, d in self.ledger.items():
            d["now"] = d["original"]
        self.save_state()
        return ok, len(runs)

    def abort(self, why):
        """Ctrl+C or a failure: release everything, put the page back."""
        self.s.say("")
        self.s.say("SAFETY STOP (%s): releasing every output ('!X') and "
                   "restoring the page this session changed" % why)
        try:
            self.e.link.command(b"!X")
        except Exception:
            pass
        try:
            diffs, _cur = self.page_diff()
            if diffs is None:
                raise RuntimeError("page not readable")
            ok, n = self.revert(diffs, keep=self.kept)
            self.s.say("RESTORED %d changed region(s) to the session-start "
                       "values%s" % (n, "" if ok else " - SOME WRITES FAILED"))
            if any(n_ in self.ledger for n_ in ("dbwEnable", "injStrategy",
                                                  "ignStrategy", "camPhaseLevel")):
                self.s.say("NOTE: throttle / strategy fields take effect only "
                           "with the ENGINE STOPPED - stop it now.")
        except Exception as ex:
            self.s.say("COULD NOT RESTORE (%s). Fields to put back by hand in "
                       "TunerStudio: %s" % (ex, {k: v["original"] for k, v in
                                                 self.ledger.items()}))

    # ------------------------------------------------------- the phases --
    def ph_kline(self):
        res = self.s.meta["phases"].get("kline", {})
        first = res.get(self.kl.first_path, {}) if self.kl else {}
        ok_path = [p for p in ("OBD", "DIRECT ECU")
                   if res.get(p, {}).get("stage") == "OK"]
        q = res.get("quality") or {}
        soak = q.get("soak") or {}
        txt = "connected over %s (%s)" % (ok_path[0] if ok_path else "?",
                                          (res.get(ok_path[0]) or {}).get("how")
                                          if ok_path else first.get("stage"))
        if "OBD" in res and res["OBD"].get("stage") != "OK":
            txt += "; the car's OBD K-line FAILED at stage %s" % res["OBD"].get("stage")
        if soak:
            txt += "; link quality %d/100 reads (%s rows/s)" % (
                soak.get("good", 0), soak.get("rows_per_s"))
        st = "PASS" if ok_path and soak.get("good", 100) >= 98 else (
            "WARN" if ok_path else "FAIL")
        if ok_path and ok_path[0] == "DIRECT ECU" and "OBD" in res:
            st = "WARN" if st == "PASS" else st
        self.verdict("K-line", st, txt)

    def ph_preflight(self):
        self.tell("Key ON, engine OFF. Do not touch the pedal.")
        self.ask("Press ENTER when the key is ON and the engine is OFF")
        ident = self.s.meta.get("identity", {})
        st, txt = image_identity(ident.get("version") or "")
        if st == "FAIL":
            self.s.say("!" * 64)
            self.s.say("!!! WRONG IMAGE: %s" % txt)
            self.s.say("!" * 64)
        self.verdict("ECU identity", st, txt)
        c = self.cfg
        self.tell("ENGINE CONFIG: %s cyl, firing order %s, injection %s, "
                  "ignition %s, sync %s, injectors %s cc/min, trigger angle %s"
                  % (c.get("cylinders"), c.get("firingOrder"),
                     c.get("injStrategy"), c.get("ignStrategy"),
                     c.get("syncMode"), c.get("injFlowCcMin"),
                     c.get("trigAngleX10")))
        rows, _ev = self.record("preflight", 10.0, enter_stops=False)
        r = self.now()
        rows.append(r)
        vb = float(_v(r, "VBatt", "battDv") or 0)
        self.verdict("Battery", "PASS" if 11.8 <= vb <= 15.0 else (
            "WARN" if vb >= 11.0 else "FAIL"), "%.1f V (engine off)" % vb)
        for name, ch in (("Coolant sensor", "coolant"), ("Intake air sensor",
                                                         "intake")):
            v = r.get(ch)
            if v is None:
                self.verdict(name, "WARN", "not readable")
            elif abs(float(v) + 40.0) < 0.05:
                self.verdict(name, "FAIL", "reads -40 C = SENSOR FAULT "
                             "(open / short / not wired)")
            else:
                self.verdict(name, "PASS" if -30 <= float(v) <= 120 else "WARN",
                             "%.1f C" % float(v))
        mapk = r.get("mapKpaX10")
        w08 = r.get("s5500w08")
        baro = (int(w08) & 1023) * 1.235352 / 10.0 if w08 is not None else None
        if mapk is None:
            self.verdict("Pressure sensor", "WARN", "not readable")
        elif baro is None or not 70 <= baro <= 110:
            self.verdict("Pressure sensor", "WARN", "%.1f kPa (onboard "
                         "barometer not readable for a comparison)" % mapk)
        else:
            d = abs(float(mapk) - baro)
            self.verdict("Pressure sensor", "PASS" if d <= 5 else (
                "WARN" if d <= 10 else "FAIL"),
                "%.1f kPa vs onboard barometer %.1f kPa (engine off: should "
                "agree)" % (mapk, baro))
        p1, p2 = float(r.get("dbwApp1X10") or 0), float(r.get("dbwApp2X10") or 0)
        t1, t2 = float(r.get("dbwTps1X10") or 0), float(r.get("dbwTps2X10") or 0)
        f = int(r.get("dbwFaults") or 0)
        st = "PASS" if p1 <= 5 and p2 <= 5 and abs(p1 - p2) <= 3 and abs(
            t1 - t2) <= 5 and not f else "FAIL"
        self.verdict("Pedal/TPS at rest", st,
                     "pedal %.1f / %.1f %%, throttle %.1f / %.1f %%, faults %s"
                     % (p1, p2, t1, t2, bits(f, DBW_FAULT)))
        codes = [int(r.get("dtcActive%d" % i) or 0) for i in range(1, 5)]
        codes = ["P%04d" % c for c in codes if c]
        self.verdict("Trouble codes", "WARN" if codes else "PASS",
                     ("active: %s" % ", ".join(codes)) if codes else "none active")
        whys = [_why1(x) for x in rows if _why1(x) is not None]
        w = whys[-1] if whys else None
        if int(self.cfg.get("_lambda1Source") or 0) == 0:
            self.verdict("Wideband warm-up", "SKIP", "no on-board wideband")
        else:
            self.verdict("Wideband warm-up",
                         "FAIL" if w in (2, 3) else (
                             "WARN" if w in (5, 6, None) else "PASS"),
                         "now: %s" % LAM_WHY_SHORT.get(w, w))
        bh = (self.s.meta.get("boot_history") or {}).get("start") or []
        bad = [b for b in bh[-4:] if b.get("reset_kind") not in
               ("power-on", "unknown")]
        self.verdict("Boot history", "WARN" if bad else "PASS",
                     "%d boots recorded; last ended by %s%s" % (
                         len(bh), bh[-1].get("reset_kind") if bh else "?",
                         ("; recent unexpected resets: %s" % [b["reset_kind"]
                                                             for b in bad])
                         if bad else ""))

    def ph_pedal(self):
        self.tell("Key ON, engine OFF. You will move the ACCELERATOR PEDAL.")
        out = {}
        steps = (("released", "Foot OFF the pedal", 3.0),
                 ("full", "Press the pedal FULLY DOWN and hold it", 3.0),
                 ("sweep", "SLOWLY press the pedal from released to full and "
                           "back (about 5 s each way)", 12.0),
                 ("stabs", "Stab the pedal FAST several times", 8.0))
        allrows = []
        for mk, txt, sec in steps:
            if not self.ask("PEDAL: %s - press ENTER, then do it (recording "
                            "%.0f s)" % (txt, sec), allow_skip=True):
                continue
            rows, _ev = self.record("pedal:" + mk, sec, enter_stops=False)
            out[mk] = rows
            allrows += rows

        def p(r, k):
            return float(r.get(k) or 0)
        probs = []
        # 2026-10-11: THE ENGINE'S PEDAL CHANNELS (pedalX10 / pedal2X10),
        # always computed. dbwApp1X10/2X10 are the DBW controller's and read 0
        # while DBW is off - the car's "full pedal reads only 0 %".
        P1, P2 = "pedalX10", "pedal2X10"
        rel = out.get("released") or []
        if rel and max(max(p(r, P1), p(r, P2)) for r in rel) > 5:
            probs.append("released pedal reads above 5 %")
        full = out.get("full") or []
        if full:
            top = max(min(p(r, P1), p(r, P2)) for r in full)
            if top < 80:
                probs.append("full pedal reads only %.0f %%" % top)
        if allrows:
            diff = max(abs(p(r, P1) - p(r, P2)) for r in allrows)
            if diff > 5:
                probs.append("the two pedal tracks disagree by up to %.1f %%"
                             % diff)
            # A DROPOUT is one track falling while the other does not; a
            # quick press moves both together (the car's "JUMPED 58 %" was a
            # sweep faster than the 5 Hz rows).
            drop = [abs((p(b, P1) - p(a, P1)) - (p(b, P2) - p(a, P2)))
                    for a, b in zip(allrows, allrows[1:])]
            if drop and max(drop) > 25:
                probs.append("one pedal track dropped %.0f %% against the "
                             "other between two samples" % max(drop))
            fl = 0
            for r in allrows:
                fl |= int(r.get("dbwFaults") or 0) | int(r.get("dbwPendFaults") or 0)
            if fl & (2 | 8):
                probs.append("pedal fault: %s" % bits(fl, DBW_FAULT))
        if not allrows:
            self.verdict("Pedal", "SKIP", "operator skipped")
        else:
            self.verdict("Pedal", "FAIL" if probs else "PASS",
                         "; ".join(probs) or "both tracks agree, full range, "
                         "no dropouts, no fault")

    def ph_dbw(self):
        if not self.safe_go("THROTTLE TEST, ENGINE OFF: the throttle plate "
                            "WILL MOVE to both stops. Hands clear"):
            self.verdict("Throttle, engine off", "SKIP", "operator skipped")
            return
        ac = Autocal(self.e, self.s, self.ring, lambda *x, **k: True)
        res = []
        # 2026-10-11: THE ECU REFUSES EVERY THROTTLE TEST WHILE DBW RUNS
        # ("DBW ENABLED"). The tool switches it off in RAM for the tests and
        # back on after them; the gains a tuner set (or characterized in
        # TunerStudio) are KEPT - the PID autotune runs only with --autotune.
        was_on = self.e.read_field("dbwEnable") == 1
        if was_on:
            self.set_field("dbwEnable", 0, "phase 3 throttle tests need the "
                           "bridge free")
            self.wait_applied()
        tests = [t for t in ETB_TESTS if t[0] != 2
                 and (t[0] != 3 or getattr(self.a, "autotune", False))]
        for sub, label, lim in tests:
            # FULLY AUTOMATIC (owner, 2026-10-11): direction A/B and the TPS
            # endpoints decide; then the full commissioning ('!C3': AutoCal,
            # PID autotune, verify) runs - if IT fails, only what it wrote is
            # put back and the endpoint calibration still stands.
            pre = self.e.link.page() if sub == 3 else None
            r = ac.one(sub, label, lim * max(self.scale, 0.05)
                       if self.scale < 1 else lim)
            if sub == 3:
                r["optional"] = True
                if not r.get("ok") and pre:
                    now = self.e.link.page() or b""
                    back = [(i, a, b) for i, (a, b) in enumerate(zip(pre, now))
                            if a != b]
                    if back:
                        self.revert(back)
                    self.s.say("full commissioning (autotune) did not pass: "
                               "its %d changed byte(s) put back; the preset "
                               "PID gains stay" % len(back))
            res.append(r)
            time.sleep(min(1.0, self.scale))
        bad = [r for r in res if not r.get("ok") and not r.get("optional")]
        self.info["dbw_ok"] = not bad and bool(res)
        if was_on:
            self.set_field("dbwEnable", 1, "phase 3 done: DBW back on")
            self.ledger.pop("dbwEnable", None)   # the page's own value again
        self.verdict("Throttle, engine off", "PASS" if not bad and res else (
            "FAIL" if bad else "SKIP"),
            "; ".join("%s: %s%s" % (r["label"], r.get("result"),
                                    (" - " + r["why"]) if r.get("why") else "")
                      for r in res))
        diffs, _cur = self.page_diff()
        if diffs:
            names = sorted({self.e.field_at(o) for o, _a, _b in diffs})
            self.tell("The throttle tests wrote into the RAM page: %s"
                      % ", ".join(names[:12]))
            # decided by the result, not asked: a PASSED calibration is
            # BURNED (engine stopped - phase 3 runs key ON, engine OFF); a
            # failed one is put back and nothing is burned
            if not self.info["dbw_ok"]:
                okw, n = self.revert(diffs)
                self.s.say("calibration did not pass: REVERTED %d "
                           "region(s), nothing burned" % n)
            else:
                self.kept |= {o for o, _a, _b in diffs}
                self.save_state()
                self.burn("throttle calibration passed (phase 3)")

    def _engine_runs_for(self, seconds):
        state = {"t": None}

        def cond(latest):
            if _running(latest):
                state["t"] = state["t"] or time.monotonic()
                return time.monotonic() - state["t"] >= seconds * self.scale
            state["t"] = None
            return False
        return cond

    # THE COMPOSITE LOGGER (2026-10-11): rusEFI's high-speed logger, the
    # one TunerStudio shows. 'l\x01' arms it (the buffer restarts), 'l\x03'
    # returns the 200 records once the buffer is full - or what there is once
    # the engine stopped - and 'l\x02' stops it. Each 8-byte record is one
    # crank or cam edge: injector and coil output masks at that edge, the
    # crank / cam levels, crank sync and a 0.8 us time. At the crank it
    # shows the first 200 edges (gap, cam, first sparks); at idle where every
    # coil and injector fires against the crank and cam - the data a remote
    # diagnosis of phase, trigger or misfire needs.
    def tooth_arm(self):
        body, _err, _ms = self.link.request(b"l\x01", 0.6, 1)
        return body is not None

    def tooth_read(self, tag, wait=3.0):
        data = None
        end = time.monotonic() + max(0.05, wait * self.scale)
        while time.monotonic() < end:
            body, _err, _ms = self.link.request(b"l\x03", 1.5, 0)
            if body:
                data = body
                break
            time.sleep(min(0.1, 0.1 * self.scale))
        self.link.request(b"l\x02", 0.6, 1)
        if not data:
            self.s.say("composite logger %s: no data (buffer not full)" % tag)
            self.info.setdefault("toothlog", {})[tag] = 0
            return 0
        (self.s.dir / ("toothlog_%s.bin" % tag)).write_bytes(data)
        lines = ["i,t_ms,dt_ms,crank,cam1,cam2,is_cam,sync,inj_mask,ign_mask"]
        t0 = prev = None
        for i in range(len(data) // 8):
            r = data[8 * i:8 * i + 8]
            t = int.from_bytes(r[4:8], "big") * 0.0008
            t0 = t if t0 is None else t0
            fl = r[3]
            lines.append("%d,%.3f,%.3f,%d,%d,%d,%d,%d,0x%02X,0x%02X" % (
                i, t - t0, 0.0 if prev is None else t - prev, fl & 1,
                (fl >> 1) & 1, (fl >> 5) & 1, (fl >> 2) & 1, (fl >> 3) & 1,
                r[1], r[2]))
            prev = t
        (self.s.dir / ("toothlog_%s.csv" % tag)).write_text(
            "\n".join(lines) + "\n", encoding="utf-8")
        self.s.say("composite logger %s: %d edges -> toothlog_%s.csv"
                   % (tag, len(data) // 8, tag))
        self.info.setdefault("toothlog", {})[tag] = len(data) // 8
        return len(data) // 8

    def ph_start(self):
        self.tell("START THE ENGINE NOW: crank until it runs (max 10 s per "
                  "attempt). Recording starts when you press ENTER.")
        if not self.safe_go("ENGINE START"):
            self.verdict("Engine start", "SKIP", "operator skipped")
            return
        b0 = self.e.scalar("rstBootCount")
        armed = self.tooth_arm()
        rows, evs = self.record("start", 40.0, until=self._engine_runs_for(5.0))
        if armed:
            self.tooth_read("crank", 1.0)
        crank = [r for r in rows if _rpm(r) > 0]
        if not crank:
            self.verdict("Engine start", "FAIL", "no crank signal seen at all")
            return
        t_c = crank[0]["_t"]
        sync = next((r["_t"] for r in rows if int(r.get("syncState") or 0) >= 3),
                    None)
        full = next((r["_t"] for r in rows if int(r.get("syncState") or 0) >= 4),
                    None)
        run = next((r["_t"] for r in rows if _running(r)), None)
        crpm = [_rpm(r) for r in crank if not _running(r)]
        vmin = min((float(_v(r, "VBatt", "battDv") or 99) for r in crank),
                   default=None)
        loss = [e for e in evs if e["type"] == "SYNC_LOSS"]
        b1 = self.e.scalar("rstBootCount")
        info = {"crank_to_sync_s": None if sync is None else round(sync - t_c, 2),
                "crank_to_cam_s": None if full is None else round(full - t_c, 2),
                "crank_to_run_s": None if run is None else round(run - t_c, 2),
                "cranking_rpm": round(_mean(crpm)) if crpm else None,
                "battery_min_v": vmin, "sync_losses": len(loss)}
        self.info["start"] = info
        if b0 is not None and b1 is not None and b1 != b0:
            self.verdict("Engine start", "FAIL", "the ECU RESET during the "
                         "crank (battery min %.1f V)" % (vmin or 0))
            return
        if run is None:
            self.verdict("Engine start", "FAIL", "did not start: crank sync %s, "
                         "cam phase %s, cranking %s rpm, battery min %s V"
                         % ("yes" if sync else "NO", "yes" if full else "no",
                            info["cranking_rpm"], vmin))
            return
        st = "PASS" if run - t_c <= 5 else "WARN"
        if vmin is not None and vmin < 8.5:
            st = "WARN"
        self.verdict("Engine start", st,
                     "running %.1f s after the first crank tooth (sync %s s, "
                     "cam %s s), cranking %s rpm, battery dipped to %.1f V, "
                     "%d sync loss(es)" % (run - t_c, info["crank_to_sync_s"],
                                           info["crank_to_cam_s"],
                                           info["cranking_rpm"], vmin or 0,
                                           len(loss)))

    def idle_checks(self, rows, label=""):
        lc = 0
        df = 0
        for x in rows:
            lc |= int(x.get("limpCut") or 0)
            df |= int(x.get("dbwFaults") or 0)
        limp = ("%s, throttle faults %s" % (bits(lc, LIMP), bits(df, DBW_FAULT))
                if lc else "")
        for name, fn in (("Injectors", lambda: check_injectors(rows, self.cfg)),
                         ("Ignition", lambda: check_coils(rows, self.cfg)),
                         ("Scheduler", lambda: check_scheduler(rows)),
                         ("Idle stability", lambda: check_rpm(rows)),
                         ("Wideband", lambda: check_wideband(rows, self.cfg)),
                         ("Mixture", lambda: check_lambda_target(rows)),
                         ("Warm-up", lambda: check_warmup(rows))):
            st, txt, info = fn()
            self.info.setdefault("idle" + label, {})[name] = info
            if limp and name in ("Idle stability", "Mixture"):
                txt += (" - NOT A CALIBRATION RESULT: the throttle-fault limp "
                        "fuel cut was cycling (%s)" % limp)
            self.verdict(name + label, st, txt)

    def ph_idle(self):
        self.tell("Let the engine IDLE. Do NOT touch the pedal. 60 s.")
        if not self.ask("Press ENTER when the engine is idling", allow_skip=True):
            self.verdict("Idle", "SKIP", "operator skipped")
            return
        rows, _evs = self.record("idle", 60.0)
        self.idle_checks(rows)
        if self.tooth_arm():
            self.tooth_read("idle", 3.0)

    def ph_drive(self):
        if not self.info.get("dbw_ok"):
            self.verdict("Throttle, driving", "SKIP", "throttle not "
                         "commissioned OK in this session (phase 3) - the "
                         "drive test needs it; nothing was switched on")
            return
        was = self.e.read_field("dbwEnable")
        if was != 1:
            self.tell("The electronic throttle must be switched ON. The ECU "
                      "applies that only with the ENGINE STOPPED.")
            if not self.ask("STOP THE ENGINE (key stays ON), then press ENTER",
                            allow_skip=True):
                self.verdict("Throttle, driving", "SKIP", "operator skipped")
                return
            self.record("wait:stopped", 15.0,
                        until=lambda r: _rpm(r) == 0, enter_stops=False)
            self.tell("Switching the electronic throttle ON (RAM). It is "
                      "BURNED at the end only if this drive test passes.")
            if not self.set_field("dbwEnable", 1, "phase 6 drive test") or \
                    not self.wait_applied():
                self.verdict("Throttle, driving", "FAIL", "dbwEnable could not "
                             "be applied (cfgDirtyGroups never cleared)")
                return
            r = self.now()
            if int(r.get("dbwState") or 0) & 0xFF == 3:
                self.verdict("Throttle, driving", "FAIL", "the throttle went "
                             "to FAULT on enable: %s"
                             % bits(int(r.get("dbwFaults") or 0), DBW_FAULT))
                self.abort("throttle fault on enable")
                return
            self.ask("START THE ENGINE, let it idle, then press ENTER")
            self.record("wait:running", 30.0, until=self._engine_runs_for(3.0))
        r = self.now()
        if int(r.get("dbwState") or 0) & 0xFF != 2:
            self.verdict("Throttle, driving", "FAIL", "the electronic throttle "
                         "is NOT running (state %s, faults %s) - nothing to "
                         "drive; the pedal does nothing"
                         % (int(r.get("dbwState") or 0) & 0xFF,
                            bits(int(r.get("dbwFaults") or 0), DBW_FAULT)))
            return
        steps = [("slow_ramp", "SLOWLY raise to ~3000 rpm and back to idle "
                  "(about 10 s)", 20.0)]
        steps += [("tipin_%d" % i, "FAST tip-in %d of 5: from idle, press the "
                   "pedal QUICKLY to about half, hold 1 s, release" % i, 6.0)
                  for i in range(1, 6)]
        steps += [("tipout", "Rev to ~3000 rpm, then release the pedal FULLY "
                   "and let it fall to idle (fuel cut on overrun)", 10.0),
                  ("blip", "One quick blip to ~3000 rpm", 5.0),
                  ("hold2500", "Hold ~2500 rpm steady", 12.0)]
        tips, allrows = [], []
        for mk, txt, sec in steps:
            if not self.ask("%s - press ENTER, then do it (%.0f s)"
                            % (txt, sec), allow_skip=True):
                continue
            rows, evs = self.record("drive:" + mk, sec, enter_stops=False)
            allrows += rows
            if mk.startswith("tipin"):
                pd = [float(r.get("dbwApp1X10") or 0) for r in rows]
                p0 = _mean(pd[:max(1, len(pd) // 6)]) or 0
                t0 = next((r["_t"] for r in rows
                           if float(r.get("dbwApp1X10") or 0) >= p0 + 15), None)
                if t0 is None:
                    tips.append({"step": mk, "status": "WARN",
                                 "cause": "no pedal step seen"})
                    continue
                a = analyze_tipin(rows, evs, t0)
                a["step"] = mk
                tips.append(a)
                self.s.say("%s: %s - rpm %s -> %s, lambda %s..%s, cause: %s"
                           % (mk, a["status"], a.get("rpm_before"),
                              a.get("rpm_min"), a.get("lambda_min"),
                              a.get("lambda_max"), a["cause"]))
            if mk == "tipout":
                dfco = any(int(_v(r, "fuelCutFlags") or 0) & 1 for r in rows)
                stall = any(_rpm(r) < 100 for r in rows)
                self.verdict("Overrun fuel cut (DFCO)",
                             "FAIL" if stall else ("PASS" if dfco else "WARN"),
                             "stalled after the overrun" if stall else (
                                 "fuel cut on overrun and fuel back at idle"
                                 if dfco else "no overrun fuel cut seen "
                                 "(conditions not met or disabled)"))
        self.info["tipins"] = tips
        if tips:
            worst = ("FAIL" if any(t["status"] == "FAIL" for t in tips) else
                     "WARN" if any(t["status"] == "WARN" for t in tips)
                     else "PASS")
            causes = sorted({t["cause"] for t in tips if t["status"] != "PASS"})
            self.verdict("Tip-in response", worst,
                         "%d tip-ins: %s%s" % (
                             len(tips), ", ".join(t["status"] for t in tips),
                             (" - most likely: " + "; ".join(causes))
                             if causes else ""))
        if allrows:
            st, txt, _i = check_rpm([r for r in allrows if _running(r)])
            f = 0
            for r in allrows:
                f |= int(r.get("dbwFaults") or 0)
            self.verdict("Throttle, driving", "FAIL" if f else "PASS",
                         "throttle faults: %s" % bits(f, DBW_FAULT))

    def _run_strategy(self, label, fields, seconds=30.0):
        self.ask("STOP THE ENGINE (key ON) for '%s', then press ENTER" % label)
        self.record("wait:stopped", 15.0, until=lambda r: _rpm(r) == 0,
                    enter_stops=False)
        for n, v in fields.items():
            self.set_field(n, v, "phase 7 %s" % label)
        applied = self.wait_applied()
        ref = self.e.scalar("cfgApplyRefused")
        if not applied:
            return {"label": label, "started": False,
                    "why": "not applied (validation refused? cfgApplyRefused %s)"
                           % ref}
        seq = label.startswith("sequential")
        self.ask("START THE ENGINE ('%s'), let it idle, ENTER when it runs or "
                 "if it will not start%s" % (label, (
                     " - crank AT MOST 5 s: with the WRONG cam level it "
                     "fires on the overlap TDC and will not run; that is "
                     "the answer, not a fault") if seq else ""))
        wrows, _w = self.record("wait:running", 20.0,
                                until=self._engine_runs_for(5.0))
        # did the cam give the cycle at all while it tried? (syncState 4)
        cyc = any(int(r.get("syncState") or 0) >= 4 for r in wrows)
        if not _running(self.rt.latest):
            return {"label": label, "started": False, "why": "did not start",
                    "cycle_seen": cyc, "seq_pct": 0.0}
        rows, _e = self.record("strategy:" + label, seconds, enter_stops=False)
        rst, rtxt, rinfo = check_rpm(rows)
        ist, itxt, _ii = check_injectors(rows, self.cfg)
        lam = [float(r["lambdaValue"]) for r in rows if r.get("lambdaValue")]
        # 2026-10-11: what was REALLY running - a sequential page without
        # the cycle runs the semi-sequential / wasted fallback and proves
        # nothing about the cam level
        sq = [1 if int(r.get("seqActive") or 0) else 0 for r in rows]
        return {"label": label, "started": True, "rpm_sd_pct": rinfo.get("sd_pct"),
                "stalled": rinfo.get("stalled"), "injectors": ist,
                "injectors_text": itxt,
                "lambda": round(_mean(lam), 3) if lam else None,
                "cycle_seen": cyc or any(int(r.get("syncState") or 0) >= 4
                                         for r in rows),
                "seq_pct": round(100.0 * sum(sq) / len(sq), 1) if sq else 0.0}

    def ph_strategy(self):
        # runs by itself when the engine started in phase 4 (owner,
        # 2026-10-11: the tool decides, the operator only acts)
        st = [r for r in self.results if r["system"] == "Engine start"]
        if not st or st[-1]["status"] not in ("PASS", "WARN"):
            self.verdict("Strategy comparison", "SKIP", "the engine did not "
                         "start cleanly in phase 4")
            return
        self.tell("STRATEGY COMPARISON (about 10 min): the tool changes the "
                  "injection / ignition strategy itself; you only stop and "
                  "start the engine when asked.")
        cands = [("batch", {"injStrategy": 0, "ignStrategy": 1}),
                 ("semi-sequential", {"injStrategy": 1, "ignStrategy": 1})]
        if int(self.cfg.get("_syncMode") or 0) >= 2:
            cands += [("sequential, cam level 0", {"injStrategy": 2,
                                                   "ignStrategy": 2,
                                                   "camPhaseLevel": 0}),
                      ("sequential, cam level 1", {"injStrategy": 2,
                                                   "ignStrategy": 2,
                                                   "camPhaseLevel": 1})]
        else:
            self.tell("This page syncs on the crank only - sequential needs "
                      "the cam (syncMode): sequential runs skipped.")
        res = [self._run_strategy(lbl, f) for lbl, f in cands]
        self.info["strategies"] = res
        for r in res:
            self.s.say("STRATEGY %-26s %s" % (r["label"], r if not r.get(
                "started") else "rpm sd %s %%, injectors %s, lambda %s" % (
                    r["rpm_sd_pct"], r["injectors"], r["lambda"])))
        good = [r for r in res if r.get("started") and not r.get("stalled")
                and r.get("injectors") != "FAIL"]
        best = min(good, key=lambda r: r["rpm_sd_pct"]) if good else None
        txt = "; ".join("%s: %s" % (r["label"], ("rpm sd %s %%" % r["rpm_sd_pct"])
                                    if r.get("started") else r.get("why"))
                        for r in res)
        cam = [r for r in res if r["label"].startswith("sequential")]
        if len(cam) == 2:
            # A RUN COUNTS FOR THE CAM LEVEL ONLY IF IT WAS TRULY SEQUENTIAL
            # (seqActive on most rows). Without the cycle both levels run the
            # same fallback and "both ran" says nothing (2026-10-11).
            ok = [r for r in cam if r in good and r.get("seq_pct", 0) >= 80]
            if not any(r.get("cycle_seen") for r in cam):
                txt += (" - CAM LEVEL: INCONCLUSIVE - the cam never gave the "
                        "720 deg cycle (syncState never 4): check the cam "
                        "sensor on 86 and camPhaseStatus before judging")
            elif len(ok) == 1:
                txt += " - CAM LEVEL: '%s' is right (the other did not run " \
                       "properly)" % ok[0]["label"]
            elif len(ok) == 2:
                txt += (" - CAM LEVEL: INCONCLUSIVE - both levels ran truly "
                        "sequential, which the wheel cannot do; log both again")
            else:
                txt += (" - CAM LEVEL: INCONCLUSIVE - neither level ran "
                        "truly sequential (seqActive %s %%)"
                        % [r.get("seq_pct") for r in cam])
        self.verdict("Strategy comparison", "PASS" if best else "FAIL",
                     ("smoothest: %s - %s" % (best["label"], txt)) if best
                     else "no strategy ran cleanly - %s" % txt)
        # back to what the page had before this phase
        self.ask("STOP THE ENGINE once more (the original strategies go back), "
                 "then press ENTER")
        self.record("wait:stopped", 15.0, until=lambda r: _rpm(r) == 0,
                    enter_stops=False)
        for n in ("injStrategy", "ignStrategy", "camPhaseLevel"):
            d = self.ledger.get(n)
            if d and d.get("now") != d["original"]:
                self.set_field(n, d["original"], "phase 7 restore")
        self.wait_applied()

    def ph_keyoff(self):
        self.tell("Engine running or idling. You will turn the KEY OFF, wait, "
                  "then ON and START again (hot restart).")
        if not self.ask("Turn the KEY OFF now and press ENTER (s skips)",
                        allow_skip=True):
            self.verdict("Key-off / restart", "SKIP", "operator skipped")
            return
        rows, _e = self.record("keyoff", 25.0, enter_stops=False)
        ro = [int(r.get("runOn") or 0) & 0xFF for r in rows]
        hold = any(x == 1 for x in ro)
        self.ask("Turn the KEY ON and START the engine, ENTER when it runs")
        t0 = time.monotonic()
        rows2, _e2 = self.record("restart", 30.0,
                                 until=self._engine_runs_for(3.0))
        crank = [r for r in rows2 if _rpm(r) > 0]
        run = next((r for r in rows2 if _running(r)), None)
        drops = self.rt.stats.get("drops", 0)
        txt = ("run-on %s; link dropped %d time(s) and came back; hot restart "
               "%s" % ("seen (relay held after key-off)" if hold else
                       "NOT seen in the recording",
                       drops, ("running %.1f s after cranking"
                               % (run["_t"] - crank[0]["_t"]))
                       if run and crank else "did NOT run"))
        st = "PASS" if run and hold else ("WARN" if run else "FAIL")
        self.verdict("Key-off / restart", st, txt)
        _ = t0

    def ph_report(self):
        order = ("K-line", "ECU identity", "Battery", "Coolant sensor",
                 "Intake air sensor", "Pressure sensor", "Pedal/TPS at rest",
                 "Pedal", "Trouble codes", "Boot history", "Wideband warm-up",
                 "Throttle, engine off", "Engine start", "Injectors",
                 "Ignition", "Scheduler", "Idle stability", "Wideband",
                 "Mixture", "Warm-up", "Throttle, driving", "Tip-in response",
                 "Overrun fuel cut (DFCO)", "Strategy comparison",
                 "Key-off / restart")
        last = {}
        for r in self.results:
            last[r["system"]] = r
        rank = {k: i for i, k in enumerate(order)}
        rows = sorted(last.values(), key=lambda r: rank.get(r["system"], 99))
        md = ["# HaniCore guided vehicle test - %s" % self.s.dir.name, "",
              "| system | result | why |", "|---|---|---|"]
        for r in rows:
            md.append("| %s | **%s** | %s |" % (r["system"], r["status"],
                                                r["reason"].replace("|", "/")))
        bad = [r for r in rows if r["status"] == "FAIL"]
        warn = [r for r in rows if r["status"] == "WARN"]
        md += ["", "## Does NOT work (%d)" % len(bad)] + [
            "* %s - %s" % (r["system"], r["reason"]) for r in bad]
        md += ["", "## Needs a look (%d)" % len(warn)] + [
            "* %s - %s" % (r["system"], r["reason"]) for r in warn]
        tips = self.info.get("tipins") or []
        if tips:
            md += ["", "## Tip-ins", "", "| step | result | rpm | lambda | "
                   "cuts | cause |", "|---|---|---|---|---|---|"]
            for t in tips:
                md.append("| %s | %s | %s -> %s | %s..%s | %s | %s |" % (
                    t.get("step"), t["status"], t.get("rpm_before"),
                    t.get("rpm_min"), t.get("lambda_min"), t.get("lambda_max"),
                    "; ".join("%s: %s" % kv for kv in (t.get("cuts") or {}).items())
                    or "-", t["cause"]))
        md += ["", "RAM changes made by this session (never burned): %s"
               % ({k: v for k, v in self.ledger.items()} or "none")]
        (self.s.dir / "report.md").write_text("\n".join(md) + "\n",
                                              encoding="utf-8")
        self.s.say("")
        self.s.say("RESULT, system by system:")
        for r in rows:
            self.s.say("  %-26s %-5s %s" % (r["system"], r["status"],
                                            r["reason"][:110]))
        self.s.say("report: %s" % (self.s.dir / "report.md"))

    def finish_ram(self):
        """Every RAM change, listed; the passed results burned, the rest put back."""
        diffs, _cur = self.page_diff()
        if diffs is None:
            self.s.say("RAM: the page could not be read back - check it in "
                       "TunerStudio; nothing was burned")
            return
        if not diffs:
            self.s.say("RAM: no page value differs from the session start")
            return
        names = {}
        for off, a, b in diffs:
            names.setdefault(self.e.field_at(off), []).append(off)
        self.s.say("")
        self.s.say("RAM CHANGES SINCE THE LAST BURN:")
        for n in sorted(names):
            d = self.ledger.get(n)
            self.s.say("  %-28s %s" % (n, ("was %s, now %s (%s)" % (
                d["original"], d.get("now"), d.get("why"))) if d else
                "changed by a calibration (%d byte(s))%s" % (
                    len(names[n]), " - KEPT in phase 3"
                    if all(o in self.kept for o in names[n]) else "")))
        # DECIDED, NOT ASKED (owner, 2026-10-11): the strategy / cam-level
        # experiments go back; the ELECTRONIC THROTTLE stays ON when the
        # drive test passed (phase 6 PASS, no tip-in FAIL) and is then
        # BURNED with the engine stopped; anything else goes back too.
        res = {r["system"]: r["status"] for r in self.results}
        keep = set(self.kept)
        dbw_keep = (res.get("Throttle, driving") == "PASS"
                    and res.get("Tip-in response") != "FAIL")
        if dbw_keep:
            _k, _s, w, off, _lo, _hi, _n = self.e.constants()["dbwEnable"]
            keep |= set(range(off, off + w))
        ok, n = self.revert(diffs, keep=keep)
        self.s.say("PUT BACK %d region(s)%s (test-only changes)." % (
            n, "" if ok else " - SOME WRITES FAILED"))
        left = [o for o, _a, _b in diffs if o in keep]
        if not left:
            self.info["ram_end"] = "reverted"
            self.s.say("Nothing left to burn: the ECU keeps its burned page.")
            self.save_state()
            return
        self.s.say("TO BURN: %s" % ", ".join(sorted({self.e.field_at(o)
                                                     for o in left})))
        self.ask("STOP THE ENGINE (key stays ON) so the result can be burned, "
                 "then press ENTER", allow_skip=False)
        self.record("wait:stopped", 15.0, until=lambda r: _rpm(r) == 0,
                    enter_stops=False)
        okb = self.burn("drive test passed: electronic throttle ON"
                        if dbw_keep else "calibration")
        self.info["ram_end"] = "burned" if okb else "burn FAILED - RAM only"
        self.save_state()

    def run(self, only=None):
        phases = [p for p in GUIDED_PHASES if p != "report"
                  and (only is None or p == only)]
        try:
            for p in phases:
                if p in self.done and only is None:
                    self.s.say("(phase %s already done - resumed session)" % p)
                    continue
                self.banner(p)
                getattr(self, "ph_" + p)()
                self.done.append(p)
                self.save_state()
            # every RAM change listed, keep or revert - BEFORE the report,
            # so the report says what the page was left with
            self.finish_ram()
            if only is None or only == "report":
                self.banner("report")
                self.ph_report()
        except KeyboardInterrupt:
            self.abort("Ctrl+C")
            raise
        except Exception as ex:
            self.s.say("FAILURE in phase %s: %r" % (getattr(self, "cur", "?"), ex))
            self.abort("failure: %s" % ex)
            raise


# ================================================================ main ====
def default_out() -> Path:
    base = ROOT.parent / "evidence"
    if not base.is_dir():
        base = ROOT / "evidence_local"
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return base / "vehicle_tests" / ("%s_vehicle_test" % stamp)


def _line(stdin_q, prompt):
    """One operator answer. A test's scripted operator may see the prompt
    (answer(prompt)) - it acts like the human who reads it."""
    if stdin_q is None:
        return input()
    if hasattr(stdin_q, "answer"):
        return stdin_q.answer(prompt)
    return stdin_q.get()


def make_ask(no_prompt: bool, sess: Session, stdin_q):
    def ask(prompt, allow_skip=False):
        sess.say(">>> " + prompt)
        if no_prompt:
            sess.say("    (--no-prompt: continuing)")
            return True
        line = _line(stdin_q, prompt)
        if allow_skip and line.strip().lower().startswith("s"):
            sess.say("    skipped")
            return False
        return True
    return ask


def make_choose(no_prompt: bool, sess: Session, stdin_q):
    """A question with a default: -> the answer (lower case) or `default`."""
    def choose(prompt, default):
        sess.say(">>> " + prompt)
        if no_prompt:
            sess.say("    (--no-prompt: %s)" % default)
            return default
        line = _line(stdin_q, prompt).strip().lower()
        sess.say("    answer: %s" % (line or default))
        return line or default
    return choose


def stdin_pump():
    """ONE reader of the keyboard for the whole guided session, so ENTER can
    both answer a question and end a recording without two threads racing
    for the same line."""
    q = queue.Queue()

    def pump():
        while True:
            try:
                q.put(input())
            except (EOFError, KeyboardInterrupt):
                return
    threading.Thread(target=pump, daemon=True).start()
    return q


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
    guided = getattr(a, "guided", False)
    resume = getattr(a, "resume", None)
    if resume:
        a.out = resume
    out = Path(a.out) if a.out else default_out()
    sess = Session(out, quiet=a.quiet, resume=bool(resume))
    profile = getattr(a, "profile", "max")
    if guided and stdin_q is None and not a.no_prompt:
        stdin_q = stdin_pump()
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
        phase = getattr(a, "phase", None)
        if guided:
            # phase 1 is the connection itself: OBD (VAG/KWP) first, then the
            # KKL moved to ECU pin 43; link quality, no key-cycle (phase 8)
            q = not resume and phase in (None, "kline")
            sess.say("=== CONNECTING (phase 1, K-LINE) ===")
            link, res = kl.run(quality=q, keycycle=False)
            sess.meta["phases"]["kline"] = res
            sess.save_meta()
        elif a.kline:
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
        ecu.boot_history("start")
        ecu.reset_witness("start")
        try:
            kline_forensics(ecu, sess)
        except Exception as e:          # an older image: nothing there
            sess.say("ECU K-LINE: not readable (%s)" % e)
        ring = Ring(ecu, sess)
        evs = ring.poll(first=True)
        ring.write(evs)
        if evs:
            sess.say("EVENTS: %d records already in the ring (incl. before "
                     "this session)" % len(evs))
        # -------------------------------------- THE GUIDED SESSION (default)
        if guided:
            st = None
            sp = sess.dir / "guided_state.json"
            if resume and sp.exists():
                st = json.loads(sp.read_text(encoding="utf-8"))
                for r in st.get("results", []):
                    sess.summary.append((r["system"], r["status"], r["reason"]))
            g = Guided(a, sess, kl, link, ecu, ring,
                       make_ask(a.no_prompt, sess, stdin_q),
                       make_choose(a.no_prompt, sess, stdin_q), stdin_q, st)
            g.run(only=phase)
            sess.meta["phases"]["guided"] = {"results": g.results,
                                             "info": g.info,
                                             "ram_ledger": g.ledger}
            sess.save_meta()
        # --------------------------------------------------- 2. AUTOCAL
        if a.autocal:
            sess.say("=== PHASE 2: ETB / AUTOCAL DIAGNOSTICS ===")
            r = Autocal(ecu, sess, ring, ask).run()
            sess.meta["phases"]["autocal"] = r
            sess.save_meta()
        # --------------------------------------------------- 3. RUNTIME
        if a.runtime:
            sess.say("=== PHASE 3: ENGINE RUNTIME FLIGHT RECORDER ===")
            rt = Runtime(ecu, sess, ring, stop_evt, a.duration,
                         profile=profile)
            if stdin_q is None and not a.no_prompt and a.duration is None:
                sess.say(">>> RECORDING. Type a word + ENTER to mark a moment "
                         "(e.g. 'stumble'); ENTER alone stops.")

                def wait_enter():
                    while True:
                        try:
                            line = input().strip()
                        except EOFError:
                            return
                        if not line:
                            stop_evt.set()
                            return
                        rt.marker = line
                        sess.say("MARKER: %s" % line)
                threading.Thread(target=wait_enter, daemon=True).start()
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
            if link is not None and "ecu" in locals():
                ecu.boot_history("end")
                pg = link.page()
                if pg:
                    (sess.dir / "page_end.bin").write_bytes(pg)
        except Exception as ex:
            sess.say("end-of-session reads failed: %s" % ex)
        try:
            if link is not None:
                link.p.close()
        except Exception:
            pass
        sess.close()
    if a.analyze and (a.runtime or a.autocal or guided):
        try:
            import me711_log_analyze as LA
            LA.main([str(out)])
        except Exception as ex:     # the recording is the product
            print("analysis failed: %s" % ex)
    print("\nSESSION FOLDER: %s" % out)
    z = zip_session(out)
    if z:
        print("SESSION ZIP (bring this back): %s" % z)
    return rc


def zip_session(folder):
    """ONE file to bring back (2026-10-11): <folder>.zip beside the folder,
    every file in it. Written last; a failure only prints - the folder is
    the record."""
    import zipfile
    try:
        folder = Path(folder)
        if not folder.is_dir():
            return None
        dst = folder.with_suffix(".zip")
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(folder.rglob("*")):
                if f.is_file():
                    z.write(f, Path(folder.name) / f.relative_to(folder))
        return str(dst)
    except Exception as ex:
        print("session zip failed: %s" % ex)
        return None


def parse(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="auto",
                    help="the KKL's COM port; 'auto' (default) picks the USB "
                         "serial adapter")
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
    ap.add_argument("--autotune", action="store_true",
                    help="phase 3 also runs the PID autotune ('!C3'); by "
                         "default the page's gains are kept")
    ap.add_argument("--no-analyze", dest="analyze", action="store_false")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--phase", choices=GUIDED_PHASES,
                    help="run ONE phase of the guided session")
    ap.add_argument("--resume", metavar="SESSION_FOLDER",
                    help="continue a guided session in that folder")
    ap.add_argument("--recorder", action="store_true",
                    help="the flight recorder (THE DEFAULT since 2026-10-14)")
    ap.add_argument("--guided", action="store_true",
                    help="the guided walkthrough (pedal, throttle, start, "
                         "idle, tip-ins, key-off) - only when one of those "
                         "systems is being investigated")
    ap.add_argument("--time-scale", dest="time_scale", type=float,
                    default=1.0, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.reduced:
        a.profile = "reduced"
    if a.full:
        a.kline = a.autocal = a.runtime = True
    # THE DEFAULT IS THE RECORDER (owner, 2026-10-14): "why should I press
    # the pedal again and again to log when we already know that part works".
    # Connect (OBD first, automatically), then record the engine's runtime
    # variables until ENTER; type a word + ENTER to drop a marker. The guided
    # walkthrough is --guided (or --phase / --resume).
    a.guided = bool(a.guided or a.phase or a.resume)
    if not a.guided and not (a.kline or a.autocal or a.runtime):
        a.recorder = True
    if a.recorder:
        a.runtime = True
    return a


def pick_port(want: str) -> str:
    """'auto': the one USB-serial adapter that is not the bench rig."""
    if want.lower() != "auto":
        return want
    from serial.tools import list_ports
    ports = list(list_ports.comports())
    kkl = [p for p in ports if any(k in (p.description or "") + (p.manufacturer or "")
                                   for k in ("FTDI", "USB Serial Port", "CH340",
                                             "Prolific", "KKL", "CP210"))]
    pick = kkl or [p for p in ports if "USB" in (p.description or "")]
    if not pick:
        raise SystemExit("no USB serial adapter found (%s) - plug the KKL in "
                         "or pass --port COMx" % ", ".join(p.device for p in ports))
    if len(pick) > 1:
        print("several adapters: %s - using %s (pass --port to choose)"
              % (", ".join(p.device for p in pick), pick[0].device))
    print("KKL port: %s (%s)" % (pick[0].device, pick[0].description))
    return pick[0].device


def main(argv=None) -> int:
    try:
        import serial  # noqa: F401
    except ImportError:
        raise SystemExit("pyserial is not installed for this Python:\n"
                         "    py -m pip install pyserial\n"
                         "(the 2026-10-10 car session lost three captures "
                         "to 'No module named serial')")
    a = parse(argv)
    a.port = pick_port(a.port)
    return run(a)


if __name__ == "__main__":
    raise SystemExit(main())
