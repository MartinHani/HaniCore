#!/usr/bin/env python3
r"""
ts_ini_scaling_proof.py - does TunerStudio SHOW the number the firmware MEANS?

    py tests\tunerstudio\ts_ini_scaling_proof.py [ini]

TunerStudio computes  user = (raw + translate) * scale   (Speeduino's own ini,
Speeduino .../speeduino.ini lines 193-194). Until V78 the
generator emitted translates written as raw*scale + translate: the ignition
map showed 10 degrees more advance than the ECU fires and coolant read 1070 C.

Each row below is a RAW value whose meaning is fixed by FIRMWARE code (cited),
decoded through the .ini exactly as TunerStudio does, and compared with what
the firmware means by it. A generator change that breaks any of them fails
here, before a tuner ever sees it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_image as PI   # noqa: E402

# (name, raw, meaning, tolerance, firmware source of the meaning)
CASES = [
    ("cltDc", 10800, 80.0, 0.05, "hcengine.c substitute (80 + CAL_TEMP_BIAS) * 10"),
    ("iatDc", 10200, 20.0, 0.05, "hcengine.c init (20 + CAL_TEMP_BIAS) * 10"),
    ("iatDefault", 10200, 20.0, 0.05, "hcconfig.c:420 default"),
    ("cltSensVal", 9600, -40.0, 0.05, "10*degC + 10000"),
    ("ignMap", 40, 0.0, 0.01, "hcengine.c:78 (cell - 40) * 0.5 deg"),
    ("ignMap", 80, 20.0, 0.01, "hcengine.c:78 (cell - 40) * 0.5 deg"),
    ("mapKpaX10", 1000, 100.0, 0.01, "0.1 kPa"),
    ("tpsX10", 500, 50.0, 0.01, "0.1 %"),
    ("dwellMsX100", 300, 3.0, 0.001, "0.01 ms"),
    ("fixedTimingX10", 100, 10.0, 0.01, "0.1 deg"),
    ("lambda1X1000", 1000, 1.0, 0.0005, "hcio711.c lambda x1000"),
    ("boostCmdX10", 500, 50.0, 0.01, "hcio711.c duty 0.1 %"),
    ("stoichAfrX100", 1470, 14.7, 0.001, "0.01 AFR"),
    ("rpm", 3000, 3000.0, 0.5, "rpm"),
]


def fields(text):
    out = {}
    for m in re.finditer(
            r"^\s*(\w+)\s*=\s*(scalar|array)\s*,\s*[US]\d\d\s*,\s*\d+\s*,"
            r"\s*(?:\[[^\]]*\]\s*,)?\s*\"([^\"]*)\"\s*,\s*([-\d.eE]+)\s*,"
            r"\s*([-\d.eE]+)", text, re.M):
        out.setdefault(m.group(1), (m.group(3), float(m.group(4)),
                                    float(m.group(5))))
    return out


def main() -> int:
    ini = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        ROOT / "tunerstudio" /
        ("hanicore_%s.ini" % PI.STEM.replace("HaniCore_ME711_", "me711_").lower()))
    f = fields(ini.read_text(errors="replace"))
    print("=== TunerStudio scaling against firmware meaning ===")
    print("  ini %s\n" % ini.name)
    bad = 0
    for name, raw, want, tol, why in CASES:
        if name not in f:
            print("  [FAIL] %-15s not in the .ini" % name)
            bad += 1
            continue
        units, scale, tr = f[name]
        got = (raw + tr) * scale
        ok = abs(got - want) <= tol
        bad += 0 if ok else 1
        print("  [%s] %-15s raw %6d -> %9.3f %-4s (firmware: %g)  %s"
              % ("PASS" if ok else "FAIL", name, raw, got, units, want, why))
    print()
    if bad:
        print("SCALING PROOF FAILS (%d)" % bad)
        return 1
    print("SCALING PROOF PASSES - %d firmware meanings shown correctly."
          % len(CASES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
