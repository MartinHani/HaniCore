"""ts_dtc_me711.py - the trouble-code set the TunerStudio files show.

THE CODE SET AND ITS ORDER are parsed from hcdtc711.c's own defs[] table -
never retyped - and every code must have a description here or the generator
stops. The order matters: bit i of the dtcStoredMask/dtcActiveMask channels
(hcio711.c) is defs[i].

Its own module (2026-10-11) because both generators need it:
gen_ts_ini_me711 (the code lists, the channels) and gen_ts_ux_me711 (one
dialog row per code). gen_ts_ini_me711 re-exports every name.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DTC_TEXT = {
    11: "Camshaft 1 timing (VVT)",
    21: "Camshaft 2 timing (VVT)",
    105: "Manifold absolute pressure sensor",
    110: "Intake air temperature sensor",
    115: "Coolant temperature sensor",
    120: "Throttle position sensor 1",
    130: "O2 sensor bank 1",
    150: "O2 sensor bank 2",
    190: "Fuel rail pressure sensor",
    217: "Engine over temperature",
    220: "Throttle position sensor 2",
    234: "Overboost",
    325: "Knock sensor 1",
    330: "Knock sensor 2",
    335: "Crankshaft position - sync lost",
    340: "Camshaft position - phase lost",
    351: "Ignition coil - over-dwell",
    560: "System voltage",
    602: "ECU configuration invalid",
    606: "ECU internal link",
    2100: "Throttle motor circuit",
    2110: "Throttle fault - rpm limited",
    2119: "Throttle actuator performance",
    2120: "Pedal sensor 1",
    2125: "Pedal sensor 2",
    2135: "Throttle position 1/2 mismatch",
    2138: "Pedal sensor 1/2 mismatch",
}

_DTC_C = (ROOT / "firmware/targets/me711/diagnostics/hcdtc711.c"
          ).read_text(encoding="utf-8", errors="replace")
_DTC_DEFS = re.search(r"static const hcdtc_def_t defs\[P_N\] = \{(.*?)\n\};",
                      _DTC_C, re.S)
if not _DTC_DEFS:
    raise SystemExit("hcdtc711.c: defs[P_N] table not found")
DTC_CODES = [int(m.group(1)) for m in
             re.finditer(r"^\s*\{\s*(\d+)u,", _DTC_DEFS.group(1), re.M)]
_undescribed = sorted(set(DTC_CODES) - set(DTC_TEXT))
if _undescribed or len(DTC_CODES) < 20:
    raise SystemExit("hcdtc711.c codes without a description in DTC_TEXT: %s"
                     % _undescribed)
if len(DTC_CODES) > 32:
    raise SystemExit("hcdtc711.c has %d paths; the masks carry 32"
                     % len(DTC_CODES))
DTC_ORDER = sorted(DTC_TEXT)        # list index = position + 1; 0 = none

# 2026-10-15 (owner): every row also says WHAT TO CHECK, and - where the ECU
# latches a reason - WHAT THE ECU ITSELF SAW (a live channel through its
# list). Short: TunerStudio sizes the row by its longest text.
DTC_CAUSE = {
    11: "phaser stuck / no cam signal",
    21: "phaser stuck / no cam signal",
    105: "sensor, connector or 5 V supply",
    110: "sensor open / short, cavity 26",
    115: "sensor open / short, cavity 93",
    120: "TPS 1 wiring or throttle body",
    130: "wideband sensor, wiring or heater",
    150: "wideband sensor, wiring or heater",
    190: "rail sensor, its pin or 5 V supply",
    217: "coolant hot: cooling system",
    220: "TPS 2 wiring or throttle body",
    234: "boost over the cut: N75 / wastegate",
    325: "knock sensor 1 wiring / torque",
    330: "knock sensor 2 wiring / torque",
    335: "crank sensor, gap or wiring noise",
    340: "cam sensor or its wiring",
    351: "coil or its wiring (no spark)",
    560: "battery / charging / ECU feed",
    602: "a setting is invalid: see Controller",
    606: "ECU internal (I/O chip link)",
    2100: "throttle motor / wiring (CJ220)",
    2110: "a throttle fault limited the rpm",
    2119: "throttle sticks or motor weak",
    2120: "pedal track 1 wiring",
    2125: "pedal track 2 wiring",
    2135: "TPS 1/2 disagree: calibrate / wiring",
    2138: "pedal 1/2 disagree: Grab / wiring",
}
_uncaused = sorted(set(DTC_CODES) - set(DTC_CAUSE))
if _uncaused:
    raise SystemExit("hcdtc711.c codes without a probable cause in "
                     "DTC_CAUSE: %s" % _uncaused)

# code -> (list, channel): the ECU's own latched reason, shown while stored
DTC_REASON = {
    11: ("hcVvtFaultList", "vvt1Fault"),
    21: ("hcVvtFaultList", "vvt2Fault"),
    130: ("hcLamFaultList", "lam1Fault"),
    150: ("hcLamFaultList", "lam2Fault"),
    325: ("hcDtcKnockList", "dtcKnockWhy"),
    330: ("hcDtcKnockList", "dtcKnockWhy"),
    335: ("hcSyncLossList", "syncLossReason"),
    340: ("hcSyncLossList", "camSyncLossReason"),
    351: ("hcDtcCoilList", "dtcCoilWhy"),
    2100: ("hcDtcDbwList", "dtcDbwWhy"),
    2110: ("hcDtcDbwList", "dtcDbwWhy"),
    2119: ("hcDtcDbwList", "dtcDbwWhy"),
}

# The derived channels behind them: the FIRST latched bit of a mask, as an
# index into its list (TunerStudio shows one label per channel).
_DBW_BITS = ((0x0020, "bridge fault pin: motor / wiring"),
             (0x0040, "plate off target too long"),
             (0x0400, "controller saturated (DLR)"),
             (0x0004, "throttle tracks disagree"),
             (0x0010, "throttle track out of range"),
             (0x0002, "pedal tracks disagree"),
             (0x0008, "pedal track out of range"),
             (0x0080, "no throttle / pedal input"),
             (0x0200, "motor supply invalid"),
             (0x0100, "outputs not live"),
             (0x0001, "throttle calibration incomplete"))


def _first(channel, bits):
    expr = "0"
    for i in range(len(bits), 0, -1):
        expr = "(%s & %d) ? %d : (%s)" % (channel, bits[i - 1], i, expr)
    return "{ %s }" % expr


DTC_DERIVED = [
    ("dtcDbwWhy", _first("dbwFaults", [b for b, _ in _DBW_BITS]),
     "the first latched throttle fault (hcDtcDbwList)"),
    ("dtcCoilWhy", _first("schedOverdwellLatch", [1 << i for i in range(8)]),
     "the first coil the over-dwell watch holds off (hcDtcCoilList)"),
    ("dtcKnockWhy", _first("knockSelFault", [0x100 << i for i in range(4)]),
     "the first knock sensor whose diagnosis latched (hcDtcKnockList)"),
]
DTC_LISTS = [
    ("hcDtcDbwList", ["-"] + [t for _, t in _DBW_BITS]),
    ("hcDtcCoilList", ["-"] + ["coil %d held off" % (i + 1)
                               for i in range(8)]),
    ("hcDtcKnockList", ["-"] + ["sensor %d signal out of range" % (i + 1)
                                for i in range(4)]),
]


def list_line(name, labels):
    top = 2
    while top < len(labels):
        top <<= 1
    labels = list(labels) + ["INVALID"] * (top - len(labels))
    return "   %-20s = bits, U08, [0:%d], %s" % (
        name, top.bit_length() - 2, ", ".join('"%s"' % x for x in labels))
DTC_PATHS = DTC_CODES               # hcdtc711.c defs[] order = mask bit
DTC_UNKNOWN = len(DTC_ORDER) + 1
