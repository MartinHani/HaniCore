#!/usr/bin/env python3
r"""
ts_ini_tracer_proof.py - every map and every curve has a LIVE CURSOR.

    py tests\tunerstudio\ts_ini_tracer_proof.py [--ini <file>] [--control]

WHY (owner, 2026-10-11, on the car): live tracing - the cursor on the
active cell - did not work on most maps. gen_ts_ui_me711.table_lines()
wrote every [CurveEditor] `xBins = <axis>` WITHOUT a channel, so 20 of the 22
curves had no tracer; only the two hand-written WUE curves had one. rusEFI
writes `xBins = cltFuelCorrBins, coolant`.

THE CHECK, for every [TableEditor] xBins / yBins and every [CurveEditor]
xBins of the generated .ini:
  1. a live channel is named after the axis;
  2. the axis is a [Constants] array;
  3. the channel exists in [OutputChannels] - a scalar wholly inside
     ochBlockSize, or an expression whose every output-channel operand is;
  4. the channel's units equal the axis's units (TunerStudio compares DISPLAY
     values: scale/translate may differ, the unit may not).
--control: the frozen pre-fix .ini (raw evidence store,
SEMISEQ_WB_FIX_20261010/image_050CC11E) must FAIL check 1 on its curves.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402

SIZES = {"U08": 1, "S08": 1, "U16": 2, "S16": 2, "U32": 4, "S32": 4, "F32": 4}


def section(txt, name):
    m = re.search(r"^\[%s\]\s*$(.*?)(?=^\[|\Z)" % re.escape(name), txt,
                  re.M | re.S)
    return m.group(1) if m else ""


def parse(txt):
    consts = {}
    for line in section(txt, "Constants").splitlines():
        m = re.match(r'\s*(\w+)\s*=\s*(scalar|bits|array)\s*,\s*\w+\s*,\s*\d+'
                     r'\s*,(?:\s*\[[^\]]*\]\s*,)?\s*"([^"]*)"', line)
        if m:
            consts[m.group(1)] = (m.group(2), m.group(3))
    block = int(re.search(r"^\s*ochBlockSize\s*=\s*(\d+)", txt, re.M).group(1))
    och = {}
    for line in section(txt, "OutputChannels").splitlines():
        line = line.split(";")[0]
        m = re.match(r'\s*(\w+)\s*=\s*(?:scalar|bits)\s*,\s*(\w+)\s*,\s*(\d+)'
                     r'\s*,\s*(?:\[[^\]]*\]\s*,\s*)?"?([^",]*)"?', line)
        if m:
            och[m.group(1)] = ("scalar", int(m.group(3)) + SIZES.get(
                m.group(2), 2), m.group(4).strip())
            continue
        m = re.match(r'\s*(\w+)\s*=\s*\{(.*)\}\s*(?:,\s*"([^"]*)")?', line)
        if m:
            och[m.group(1)] = ("expr", m.group(2), (m.group(3) or "").strip())
    return consts, block, och


def bins(txt):
    """[(where, axis, channel or None)]"""
    out = []
    for sec, keys in (("TableEditor", ("xBins", "yBins")),
                      ("CurveEditor", ("xBins",))):
        cur = None
        for line in section(txt, sec).splitlines():
            m = re.match(r"\s*(?:table|curve)\s*=\s*(\w+)", line)
            if m:
                cur = m.group(1)
            m = re.match(r"\s*(xBins|yBins)\s*=\s*([^\s,;]+)\s*(?:,\s*(\w+))?",
                         line)
            if m and m.group(1) in keys:
                out.append(("%s %s.%s" % (sec, cur, m.group(1)), m.group(2),
                            m.group(3)))
    return out


def judge(ini: Path):
    txt = ini.read_text(encoding="utf-8", errors="replace")
    consts, block, och = parse(txt)
    bad, n = [], 0
    for where, axis, ch in bins(txt):
        n += 1
        if ch is None:
            bad.append("%s: %s has NO live channel" % (where, axis))
            continue
        c = consts.get(axis)
        if c is None or c[0] != "array":
            bad.append("%s: axis %s is not a [Constants] array" % (where, axis))
            continue
        o = och.get(ch)
        if o is None:
            bad.append("%s: channel %s is not an output channel" % (where, ch))
            continue
        if o[0] == "scalar":
            inside, unit = o[1] <= block, o[2]
        else:
            ops = [w for w in re.findall(r"[A-Za-z_]\w*", o[1]) if w in och]
            inside = bool(ops) and all(och[w][0] == "expr" or
                                       och[w][1] <= block for w in ops)
            unit = o[2]
        if not inside:
            bad.append("%s: channel %s lies outside ochBlockSize %d"
                       % (where, ch, block))
        if unit != c[1]:
            bad.append("%s: channel %s is in %r, the axis %s in %r"
                       % (where, ch, unit, axis, c[1]))
    return n, bad


def main() -> int:
    if "--control" in sys.argv:
        ev = Path(os.environ.get("HANICORE_RAW_EVIDENCE",
                                 str(ROOT.parent / "evidence")))
        ini = ev / "SEMISEQ_WB_FIX_20261010" / "image_050CC11E" \
            / "hanicore_me711_v102_dev.ini"
        r = subprocess.run([sys.executable, __file__, "--ini", str(ini)])
        ok = r.returncode != 0
        print("\nCONTROL (pre-fix .ini): %s" % ("FAILS as it must" if ok
                                               else "PASSED - the gate cannot tell"))
        return 0 if ok else 1
    if "--ini" in sys.argv:
        inis = [Path(sys.argv[sys.argv.index("--ini") + 1])]
    else:
        import me711_image as PI
        stem = PI.STEM.replace("HaniCore_ME711_", "me711_").lower()
        inis = [ROOT / "tunerstudio" / ("hanicore_%s.ini" % stem),
                ROOT / "tunerstudio" / ("hanicore_%s_forensic.ini" % stem)]
    fails = 0
    for ini in inis:
        if not ini.exists():
            continue
        n, bad = judge(ini)
        print("=== %s: %d table/curve axes ===" % (ini.name, n))
        for b in bad:
            print("  [FAIL] " + b)
        print("  [%s] every axis has a live channel inside the block, in its "
              "units" % ("PASS" if not bad and n else "FAIL"))
        fails += bool(bad) or not n
    print("RESULT: %s" % ("FAIL" if fails else "PASS"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
