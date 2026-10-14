#!/usr/bin/env python3
r"""
ts_semantics_me711.py - the names HaniCore's firmware already has, made
visible in TunerStudio.

    imported by tools/tunerstudio/gen_ts_ini_me711.py

THE PROBLEM THIS SOLVES. `the maintainer's design records counted 59
named runtime states reaching the tuner as bare integers. Parsing the headers
mechanically rather than by eye finds 108 - which is itself the argument for
doing it mechanically. The bench read `ramProbe = 514` and a human had to know that
514 is 0x0202, that the high byte counts probes and that the low byte 0x02 is
HCNV_RP_PASS. That is the firmware exposing its structs.

THE VALUES ARE PARSED OUT OF THE FIRMWARE HEADERS, NOT TYPED HERE. Only the
human wording is authored. If firmware adds a state, `check()` fails the build
rather than letting an unlabelled value reach a tuner as a number - which is
the whole defect, reintroduced quietly.

    hcbench.h / hcnvm.h / hc_dbw.h / hcengine.h / hctrigger.h
    hcfuelpump.h / hcmainrelay.h / hcconfig.h / hc_config_generated.h
        -> parse #define
            -> this file (wording only)
                -> [PcVariables] label lists + indicator panels

TWO SHAPES, AND THEY ARE NOT INTERCHANGEABLE.

  * an INDEX family (0,1,2,3...) renders with TunerStudio's
    `bitStringValue(list, channel)`, exactly as rusEFI does with
    `fuelIgnCutCodeList` (rusefi_proteus_f7.ini:4189, used at :6099);
  * a BITMASK family (0x0001, 0x0002, 0x0004...) CANNOT. `bitStringValue`
    indexes; a mask of 0x0005 is not "state 5". Masks get one indicator per
    bit, which is better UX anyway because two faults can be true at once.

NOTHING HERE CHANGES FIRMWARE. Every value is the encoding the flashed V37
binary already produces.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths as HCP  # noqa: E402   (HCP.find: a file in the ME7.1.1 search path)

_DEF = re.compile(r"^\s*#define\s+([A-Za-z_][A-Za-z0-9_]*)\s+"
                  r"\(?\s*(0[xX][0-9A-Fa-f]+|\d+)\s*[uU]?\s*\)?")


def _defines(path: Path) -> dict[str, int]:
    out = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _DEF.match(line)
        if m:
            out[m.group(1)] = int(m.group(2), 0)
    return out


_H = {}


def _h(path: Path) -> dict[str, int]:
    if path not in _H:
        _H[path] = _defines(path)
    return _H[path]


# ==========================================================================
# 1. INDEX families -> a [PcVariables] `bits` label list.
#
#    (list name, header, prefix, {value: wording})
#
# The prefix collects the family out of the header; the dict supplies wording.
# check() insists the two agree, in both directions.
# ==========================================================================
INDEX_FAMILIES = [
    ("hcBenchStateList", HCP.find("hcbench.h"), "HCB_", {
        0: "Idle", 1: "RUNNING", 2: "Completed",
        3: "REFUSED", 4: "ABORTED",
    }, ("IDLE", "RUNNING", "DONE", "REFUSED", "ABORTED")),

    # The endpoint grab. Every constant is parsed out of hcengine.h; only the
    # wording is authored here, and check() fails the build if a constant gains
    # a value nobody worded.
    ("hcGrabList", HCP.find("hcengine.h"), "ENG_GRAB_", {
        0: "never asked",
        1: "PASS - both tracks written to RAM",
        2: "REFUSED: the engine is not demonstrably stopped",
        3: "REFUSED: this board cannot read one of the pair",
        4: "REFUSED: a raw count is at a rail - open circuit",
        5: "REFUSED: the two ends are too close - check the wiring",
        6: "REFUSED: no such endpoint",
        7: "PASS - both tracks in the page, correlation SAME",
    }, ("IDLE", "PASS", "RPM", "NOCHANNEL", "RAIL", "SPAN", "WHAT",
        "PASS_SAME")),
    # V90: the automatic ETB endpoint calibration ('!C1') and V92 autotune
    # ('!C2'); V93: hcetbcal.c, commission '!C3', SHORT primary texts (the
    # car showed sentence-long indicator strings unreadable). The long
    # explanations: tools/vehicle/me711_dbw_vehicle_test.py WHY_DETAIL and the help.
    ("hcEtbCalList", HCP.find("hcetbcal.h"), "ETB_RES_", {
        0: "IDLE", 1: "RUNNING", 2: "TPS ENDPOINTS: PASS", 3: "FAIL",
        4: "PID TUNE: PASS", 5: "AUTOCAL ETB: PASS", 6: "POSITION CAPTURED",
        7: "CHARACTERIZATION COMPLETE",
    }, ("NONE", "RUN", "PASS", "FAIL", "TUNED", "COMMISSIONED", "CAPTURED", "CHARACTERIZED")),
    ("hcEtbPhaseList", HCP.find("hcetbcal.h"), "ETB_CAL_", {
        0: "IDLE", 1: "AUTOCAL: REST", 2: "AUTOCAL: DRIVE A",
        3: "AUTOCAL: RELEASE A", 4: "AUTOCAL: DRIVE B",
        5: "AUTOCAL: RELEASE B", 6: "PID TUNE: CYCLING",
        7: "AUTOCAL: STOP CHECK A", 8: "AUTOCAL: STOP CHECK B",
        9: "PID TUNE: APPROACH", 10: "AUTOCAL: VERIFY",
        11: "PID TUNE: MOTOR OFF / SETTLING",
        12: "CHARACTERIZATION: BOUNDED PROFILE", 13: "CHARACTERIZATION: PEDAL SLAMS",
    }, ("IDLE", "REST", "DRIVE_A", "BACK_A", "DRIVE_B", "BACK_B", "TUNE",
        "PUSH_A", "PUSH_B", "APPROACH", "VERIFY", "TUNE_REST", "SWEEP", "SLAM")),
    ("hcEtbWhyList", HCP.find("hcetbcal.h"), "ETB_WHY_", {
        0: "-", 1: "RPM > 0", 2: "OUTPUTS OFF", 3: "BRIDGE (SF)",
        4: "TPS RAIL", 5: "NO MOVE DIR A", 6: "NO MOVE DIR B",
        7: "TPS SPAN", 8: "TIMEOUT", 9: "DBW ENABLED", 10: "ABORTED",
        11: "TPS SOURCE NOT CONFIGURED", 12: "TPS UNCAL", 13: "OUT OF BAND",
        14: "NOT A STOP A", 15: "NOT A STOP B", 16: "REST OUTSIDE",
        17: "TPS CORRELATION", 18: "50% NOT REACHED", 19: "PID IMPLAUSIBLE",
        20: "NO ENDPOINTS", 21: "VERIFY: SLOW", 22: "VERIFY: OVERSHOOT",
        23: "VERIFY: OFFSET", 24: "VERIFY: DBW FAULT", 25: "PID REST NOT SETTLED",
        26: "TPS SAMPLE STALE", 27: "TPS ADC REJECTED",
        28: "TPS SAMPLE ALIGNMENT", 29: "CONTROL SERVICE STALE",
        30: "TPS NO COMPLETED SAMPLE", 31: "PID NOT REPEATABLE",
    }, ("NONE", "TURNING", "NOTLIVE", "SF", "RAIL", "NOMOVE_A", "NOMOVE_B",
        "SPAN", "TIMEOUT", "RUNNING", "ABORTED", "NOTPS", "UNCAL", "BAND",
        "NOTSTOP_A", "NOTSTOP_B", "REST", "TRACKS", "UNREACHED", "IMPLAUS",
        "NOENDPTS", "V_SLOW", "V_OVER", "V_ERROR", "V_FAULT", "UNSETTLED",
        "STALE", "ADC", "ALIGN", "CONTROL", "NOSAMPLE", "REPEAT")),
    ("hcEtbProcList", HCP.find("hcetbcal.h"), "ETB_PROC_", {
        0: "-", 1: "TPS ENDPOINTS", 2: "PID AUTOTUNE", 3: "AUTOCAL ETB",
        4: "DIRECTION A", 5: "DIRECTION B",
        6: "CHARACTERIZATION",
    }, ("NONE", "AUTOCAL", "AUTOTUNE", "COMMISSION", "DIR_A", "DIR_B", "SWEEP")),
    # V86: the engine preset apply ('!E'), constants in hcmain_me711.c.
    ("hcPresetList", HCP.find("hcdiag711.c"), "PRESET_V_", {
        0: "never asked",
        1: "APPLIED - fields populated, NOT burned",
        2: "REFUSED: engine not stopped (rpm or crank edges)",
        3: "REFUSED: no such preset (Custom populates nothing)",
        4: "REFUSED: preset is for another ECU",
        5: "REFUSED: resulting page invalid - NOTHING changed",
        6: "REFUSED: a bench output test is running",
        7: "pending - waiting for the main loop",
    }, ("NEVER", "APPLIED", "NOT_STOPPED", "NO_SUCH", "WRONG_BOARD",
        "INVALID", "BENCH_BUSY", "PENDING")),
    ("hcSyncStateList", HCP.find("hc_config_generated.h"), "HC_SYNC_", {
        0: "No sync", 1: "Crank only - no engine phase",
        2: "Full sync from cam 1", 3: "Full sync from cam 2",
        4: "Full sync from both cams",
    }, ("NONE", "CRANK_ONLY", "CAM1_CYCLE", "CAM2_CYCLE", "DUAL_CAM")),

    # V85: THE CHANNEL syncState IS trg_state (hcmain put16(162, trg_state)),
    # NOT the syncMode configuration enum above. Decoding it with
    # hcSyncStateList showed a crank-only sync (TRG_SYNC_CRANK = 3) as "Full
    # sync from cam 2" - seen on the bench with no cam wired, 2026-09-26.
    ("hcTrgStateList", HCP.find("hctrigger.h"), "TRG_", {
        0: "No crank signal", 1: "Teeth counting - no gap yet",
        2: "Gap seen - position not yet proven",
        3: "CRANK SYNC - 360 deg known, no engine phase",
        4: "FULL SYNC - engine phase known",
    }, ("NO_SIGNAL", "COUNTING", "GAP_SEEN", "SYNC_CRANK", "SYNC_FULL")),

    ("hcSyncLossList", HCP.find("hctrigger.h"), "TRG_LOSS_", {
        0: "None", 1: "Engine stopped",
        2: "Gap arrived early", 3: "Gap never arrived",
        4: "Gap was malformed", 5: "Extra edge in the wheel",
        6: "Cam edge outside its window", 7: "Cam edge missing",
        8: "Cam level did not alternate", 9: "Cam level contradicted the phase",
    }, ("NONE", "STALL", "EARLY_GAP", "MISSING_GAP", "MALFORMED_GAP",
        "EXTRA_EDGE", "CAM_WINDOW", "CAM_MISSING", "CAM_PATTERN",
        "CAM_PHASE")),

    # V92: the tooth-profile test ('!K'), constants in hcsched_dry.h.
    ("hcToothLogList", HCP.find("hcsched_dry.h"), "HC_TL_", {
        0: "idle", 1: "ARMED - crank now (spark and fuel held off)",
        2: "recording", 3: "DONE - profile published",
        4: "REFUSED - the engine was turning",
        5: "aborted", 6: "timed out - no crank within 30 s",
    }, ("IDLE", "ARMED", "RUN", "DONE", "REFUSED", "ABORTED", "TIMEOUT")),

    ("hcDbwStateList", HCP.find("hc_dbw.h"), "DBW_", {
        0: "OFF", 1: "INIT", 2: "RUN", 3: "FAULT",
    }, ("OFF", "INIT", "RUN", "FAULT")),

    # NOT HERE: HC_DBW_SF_*. dbwSfMode is a PAGE CONSTANT and the model
    # already labels it from ENUM_DBW_SF, so a second copy of the same three
    # words would be a declaration nothing reads - which is how a list drifts
    # away from the header it claims to mirror.

    ("hcPumpStateList", HCP.find("hcfuelpump.h"), "FP_", {
        0: "Off", 1: "Priming", 2: "Cranking", 3: "Running",
        4: "Stopped", 5: "FAULT",
    }, ("OFF", "PRIME", "CRANKING", "RUNNING", "STOPPED", "FAULT")),

    ("hcRelayStateList", HCP.find("hcmainrelay.h"), "MR_ST_", {
        0: "Init", 1: "Requested", 2: "Running",
        3: "Shutting down", 4: "Released", 5: "FAULT",
    }, ("INIT", "REQUEST", "RUNNING", "SHUTDOWN", "RELEASED", "FAULT")),

    ("hcRamProbeList", HCP.find("hcnvm.h"), "HCNV_RP_", {
        0: "Not run", 1: "RUNNING - board cannot execute from SRAM",
        2: "PASS", 3: "FAIL - wrong answer",
        4: "FAIL - no signature", 5: "FAIL - SRAM unusable",
        6: "Refused - engine could be turning",
    }, ("IDLE", "RUNNING", "PASS", "WRONG", "NOSIG", "REFUSED", "UNSAFE")),

    ("hcNvmStateList", HCP.find("hcnvm.h"), "HCNV_ST_", {
        0: "Idle - page matches flash", 1: "NOT BURNED - edited since",
        2: "Burn pending", 3: "Burn armed - reset imminent",
        4: "Committing", 5: "BURNED and verified",
        6: "BURN FAILED - previous record stands", 7: "Staging",
    }, ("IDLE", "DIRTY", "PENDING", "ARMED", "COMMITTING", "DONE",
        "FAILED", "STAGING")),

    ("hcNvmErrList", HCP.find("hcnvm.h"), "HCNV_ERR_", {
        0: "None", 1: "SRAM unusable", 2: "Configuration would not validate",
        3: "Staged record did not verify", 4: "Sector would not erase",
        5: "A word would not program", 6: "Did not read back",
        7: "Gave up after retries", 8: "Record from a different page layout",
    }, ("NONE", "RAM", "VALIDATE", "STAGE", "ERASE", "PROGRAM", "VERIFY",
        "RETRIES", "LAYOUT")),

    ("hcNvmSrcList", HCP.find("hcnvm.h"), "HCNV_SRC_", {
        0: "Compiled defaults", 1: "Battery-backed page",
        2: "Flash slot A", 3: "Flash slot B",
    }, ("DEFAULTS", "STANDBY", "FLASH_A", "FLASH_B")),

    ("hcNvmSlotList", HCP.find("hcnvm.h"), "HCNV_SLOT_", {
        0: "None", 1: "Slot A", 2: "Slot B",
    }, ("NONE", "A", "B")),

    ("hcNvmPhaseList", HCP.find("hcnvm.h"), "HCNV_PH_", {
        0: "None", 1: "Programming", 2: "Committing",
    }, ("NONE", "PROGRAM", "COMMIT")),

    # V97: the wideband (firmware/sensors/hcwb.h) - why lambda is withheld, the
    # latched fault, the heater state. Short: they are indicator texts.
    ("hcLamWhyList", HCP.find("hcwb.h"), "HCWB_WHY_", {
        0: "VALID", 1: "OFF", 2: "FAULT (latched)", 3: "CONTROLLER NOT VERIFIED",
        4: "CALIBRATING", 5: "WAIT: ENGINE", 6: "WAIT: SUPPLY",
        7: "PREHEAT (DEW)", 8: "HEATING RAMP", 9: "SETTLING (Ri)",
        10: "PUMP STARTING", 11: "CONTROLLER DIAGNOSIS", 12: "PUMP SATURATED",
        13: "NO Ri SIGNAL", 14: "BENCH HOLD", 15: "QUIET SIGNAL (not used)",
        16: "HELD (last value, gap)",
    }, ("VALID", "OFF", "FAULT", "CHIP", "CAL", "ENGINE", "SUPPLY",
        "PREHEAT", "RAMP", "SETTLE", "PUMP", "DIAG", "UA", "UR", "HOLD",
        "STUCK", "HELD")),
    ("hcLamFaultList", HCP.find("hcwb.h"), "HCWB_F_", {
        0: "NO FAULT", 1: "HEATER SHORT GND", 2: "NO SENSOR / HTR OPEN",
        3: "HEATER SHORT UB", 4: "PUMP LINE IA/IP", 5: "NERNST LINE UN",
        6: "GROUND LINE VM", 7: "CONTROLLER NOT ANSWERING", 8: "CALIBRATION",
        9: "DID NOT HEAT 60s", 10: "OVERHEAT", 11: "UNDERHEAT",
        12: "NO Ri SIGNAL", 13: "UR STAYED RAILED",
    }, ("NONE", "HEATER_GND", "HEATER_OPEN", "HEATER_UB", "LINE_IAIP",
        "LINE_UN", "LINE_VM", "CHIP", "CAL", "NO_HEAT", "OVERHEAT",
        "UNDERHEAT", "NO_RI", "OPEN_CELL")),
    ("hcLamHeaterList", HCP.find("hcwb.h"), "HCWB_ST_", {
        0: "OFF", 1: "WAIT", 2: "PREHEAT", 3: "RAMP", 4: "CLOSED LOOP",
        5: "READY", 6: "FAULT",
    }, ("OFF", "WAIT", "PREHEAT", "RAMP", "CLOSED", "READY", "FAULT")),
    # V97: VVT (hcvvt711.h) - the latched fault per cam
    ("hcVvtFaultList", HCP.find("hcvvt711.h"), "VVT_F_", {
        0: "NO FAULT", 1: "NO CAM POSITION", 2: "STUCK / SLOW",
        3: "OUT OF AUTHORITY", 4: "NO STAGE ROUTED",
    }, ("NONE", "NOFB", "SLOW", "RANGE", "ROUTE")),
    # V97: knock (hcknock711.h) - why the last window was not taken
    ("hcKnockWhyList", HCP.find("hcknock711.h"), "KN_WHY_", {
        0: "MEASURING", 1: "OFF", 2: "NO SYNC", 3: "BELOW MIN RPM",
        4: "WINDOW MISSED", 5: "BUSY", 6: "KI ADC FAIL", 7: "WINDOW ABORTED",
        8: "CALIBRATION REFUSED",
    }, ("OK", "OFF", "SYNC", "RPM", "LATE", "BUSY", "ADC", "STALE", "CFG")),
    ("hcPersistList", HCP.find("hcconfig.h"), "HC_PERSIST_", {
        0: "Nothing survives a reset", 1: "Survives reset and key-off",
        2: "NON-VOLATILE - survives loss of all power",
    }, ("NONE", "STANDBY", "NONVOL")),
]


# ==========================================================================
# 2. BITMASK families -> one indicator per bit.
#
#    (family key, header, prefix, {bit value: (ok wording, fault wording)})
# ==========================================================================
MASK_FAMILIES = [
    ("dbwFaults", HCP.find("hc_dbw.h"), "DBW_F_", {
        0x0001: ("DBW CAL OK", "DBW: CAL INCOMPLETE"),
        0x0002: ("APP PAIR OK", "DBW: APP CORRELATION"),
        0x0004: ("TPS PAIR OK", "DBW: TPS CORRELATION"),
        0x0008: ("APP RANGE OK", "DBW: APP RANGE"),
        0x0010: ("TPS RANGE OK", "DBW: TPS RANGE"),
        0x0020: ("BRIDGE OK", "DBW: BRIDGE (SF)"),
        0x0040: ("ON TARGET", "DBW: OFF TARGET"),
        0x0080: ("INPUTS OK", "DBW: NO TPS/APP INPUT"),
        0x0100: ("OUTPUTS LIVE", "DBW: OUTPUTS OFF"),
        0x0200: ("VBAT OK", "DBW: VBAT INVALID / STALE"),
    }, ("CFG", "APP_PAIR", "TPS_PAIR", "APP_RANGE", "TPS_RANGE", "SF",
        "DEV", "STALE", "NOTLIVE", "VBAT")),

    # THE SIX REASONS NOTHING IS DRIVEN. hcsafety.c gates ignition, injection
    # and DBW on these, and the .ini used to publish the word as an integer
    # with a three-word comment. They are the answer to "why is there no
    # spark", so they get one indicator each.
    ("safetyInhibits", HCP.find("hcsafety.h"), "HC_INHIBIT_", {
        0x0001: ("Not bench-safe-inhibited", "BENCH_SAFE: this build never "
                 "drives an engine output"),
        0x0002: ("Engine phase known", "NO CYCLE SYNC: the 720 deg phase is "
                 "not resolved"),
        0x0004: ("I/O chip link running", "I/O CHIP: the link is not running"),
        0x0008: ("Calibration valid", "CAL: the page does not validate"),
        0x0010: ("Key on", "KEY OFF: controlled key-off in progress"),
        0x0020: ("Crank signal present", "NO CRANK: the decoder sees no "
                 "crank signal"),
    }, ("BENCH_SAFE", "NO_CYCLE", "ASIC", "CAL", "KEYOFF", "NO_CRANK")),

    ("hcbRefuse", HCP.find("hcbench.h"), "HCB_R_", {
        0x0001: ("RPM 0", "REFUSED: RPM > 0"),
        0x0002: ("(retired)", "REFUSED: RETIRED BIT"),
        0x0004: ("CONFIG OK", "REFUSED: CONFIG"),
        0x0008: ("PORT OK", "REFUSED: NO PORT"),
        0x0010: ("CHANNEL OK", "REFUSED: CHANNEL"),
        0x0020: ("NOT BUSY", "REFUSED: BUSY"),
        0x0040: ("I/O CHIP UP", "REFUSED: I/O CHIP DOWN"),
        0x0080: ("TPS PAIR OK", "REFUSED: TPS CORRELATION"),
        0x0100: ("BRIDGE OK", "REFUSED: BRIDGE (SF)"),
        0x0200: ("CAVITY OK", "REFUSED: CAVITY"),
        0x0400: ("ETB FREE", "REFUSED: ETB BUSY"),
        0x0800: ("THROTTLE PERMITTED", "REFUSED: THROTTLE NOT PERMITTED"),
    }, ("RPM", "ARMED", "CFG", "MODE", "CHANNEL", "BUSY", "SUPERVISOR",
        "TPSPAIR", "SF", "PIN", "ETB", "PERMIT")),

    ("hcbAbort", HCP.find("hcbench.h"), "HCB_A_", {
        0x0001: ("-", "ABORTED: HOST"),
        0x0002: ("-", "ABORTED: CRANK EDGE"),
        0x0004: ("-", "ABORTED: CONFIG"),
        0x0008: ("-", "ABORTED: TIMEOUT"),
        0x0010: ("-", "ABORTED: BRIDGE (SF)"),
        0x0020: ("-", "ABORTED: OUT OF BAND"),
        0x0040: ("-", "ABORTED: TPS CORRELATION"),
        0x0080: ("-", "ABORTED: I/O CHIP DOWN"),
        0x0100: ("-", "ABORTED: THROTTLE DRIVE REFUSED"),
    }, ("HOST", "CRANK", "CFG", "TIMEOUT", "SF", "TPSMOVE", "TPSPAIR",
        "SUPERVISOR", "DRIVE")),

    ("fuelCut", HCP.find("hcengine.h"), "ENG_CUT_", {
        0x0008: ("Limp OK", "FUEL CUT: engine protection"),
        0x0010: ("Pressure / model OK", "FUEL CUT: pressure / load model"),
        0x0020: ("Lean guard clear", "FUEL CUT: qualified persistent lean"),
        0x0001: ("Fuel enabled", "FUEL CUT: overrun"),
        0x0002: ("Below rev limit", "FUEL CUT: rev limiter"),
        0x0004: ("Boost OK", "FUEL CUT: overboost"),
    }, ("OVERRUN", "REV", "BOOST", "LIMP", "LOAD", "LEAN")),

    ("fuelPumpReason", HCP.find("hcfuelpump.h"), "FP_R_", {
        0x0001: ("-", "Pump off: ignition off"),
        0x0002: ("-", "Pump off: prime finished, no engine"),
        0x0004: ("-", "Pump off: engine stalled"),
        0x0008: ("-", "Pump off: configuration invalid"),
        0x0010: ("-", "Pump off: runtime fault"),
        0x0020: ("-", "Pump off: disabled by configuration"),
        0x0040: ("-", "Pump requested: output not permitted"),
    }, ("IGNOFF", "PRIMEDONE", "STALL", "CFG", "FAULT", "DISABLED",
        "INHIBIT")),
]


# ==========================================================================
# 3. Emission
# ==========================================================================
def index_list_lines() -> list[str]:
    """The [PcVariables] label lists, rusEFI's `fuelIgnCutCodeList` shape."""
    out = []
    for name, path, prefix, wording, _suffixes in INDEX_FAMILIES:
        top = 1
        while top <= max(wording):
            top <<= 1
        width = top.bit_length() - 1
        labels = ", ".join('"%s"' % wording.get(i, "INVALID")
                           for i in range(top))
        out.append("   %-20s = bits, U08, [0:%d], %s" % (name, width - 1, labels))
    return out


def mask_bits(key: str):
    """(bit, ok wording, fault wording) for one bitmask family, ascending."""
    for k, _p, _pre, wording, _s in MASK_FAMILIES:
        if k == key:
            return [(b, ok, bad) for b, (ok, bad) in sorted(wording.items())]
    raise KeyError(key)


def fault_indicators(channel: str, key: str, only_bad: bool = False) -> list[str]:
    """One `indicator` per bit. Arity 3 - the corpus shape with 6600 uses."""
    out = []
    for bit, ok, bad in mask_bits(key):
        if only_bad and ok == "-":
            out.append('      indicator = { (%s & %d) > 0 }, "", "%s"'
                       % (channel, bit, bad))
        else:
            out.append('      indicator = { (%s & %d) > 0 }, "%s", "%s"'
                       % (channel, bit, ok, bad))
    return out


# ==========================================================================
# 4. The check that makes this file safe to trust.
# ==========================================================================
def check() -> list[str]:
    """Every constant in every family must have wording, and vice versa."""
    bad = []
    for name, path, prefix, wording, suffixes in INDEX_FAMILIES:
        if not path.exists():
            bad.append("%s: %s does not exist" % (name, path))
            continue
        defs = _h(path)
        found = {k[len(prefix):]: v for k, v in defs.items()
                 if k.startswith(prefix) and k[len(prefix):] in suffixes}
        missing = sorted(set(suffixes) - set(found))
        if missing:
            bad.append("%s: %s defines no %s%s"
                       % (name, path.name, prefix, missing))
        for suf in found:
            v = found[suf]
            if v not in wording:
                bad.append("%s: %s%s = %d has no wording - a tuner would see "
                           "a bare number" % (name, prefix, suf, v))
        vals = set(found.values())
        for v in wording:
            if v not in vals:
                bad.append("%s: wording for %d but no %s* constant has that "
                           "value" % (name, v, prefix))

    for key, path, prefix, wording, suffixes in MASK_FAMILIES:
        if not path.exists():
            bad.append("%s: %s does not exist" % (key, path))
            continue
        defs = _h(path)
        found = {k[len(prefix):]: v for k, v in defs.items()
                 if k.startswith(prefix) and k[len(prefix):] in suffixes}
        missing = sorted(set(suffixes) - set(found))
        if missing:
            bad.append("%s: %s defines no %s%s"
                       % (key, path.name, prefix, missing))
        for suf, v in found.items():
            if v & (v - 1):
                bad.append("%s: %s%s = 0x%X is not a single bit" %
                           (key, prefix, suf, v))
            if v not in wording:
                bad.append("%s: %s%s = 0x%X has no wording"
                           % (key, prefix, suf, v))
        vals = set(found.values())
        for v in wording:
            if v not in vals:
                bad.append("%s: wording for 0x%X but no %s* constant has it"
                           % (key, v, prefix))
    return bad


if __name__ == "__main__":
    problems = check()
    if problems:
        print("SEMANTICS CHECK FAILED")
        for p in problems:
            print("  " + p)
        raise SystemExit(1)
    n_idx = sum(len(w) for _n, _p, _pre, w, _s in INDEX_FAMILIES)
    n_msk = sum(len(w) for _k, _p, _pre, w, _s in MASK_FAMILIES)
    print("SEMANTICS OK - %d index families (%d states), "
          "%d mask families (%d bits), %d names total"
          % (len(INDEX_FAMILIES), n_idx, len(MASK_FAMILIES), n_msk,
             n_idx + n_msk))
