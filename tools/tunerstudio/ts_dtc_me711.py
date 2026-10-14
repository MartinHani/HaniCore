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
DTC_PATHS = DTC_CODES               # hcdtc711.c defs[] order = mask bit
DTC_UNKNOWN = len(DTC_ORDER) + 1
