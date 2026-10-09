#!/usr/bin/env python3
"""
och_scale_audit.py - does each output channel's declared TunerStudio scale
match the fixed-point unit the firmware actually writes there?

    python3 tools/research/och_scale_audit.py [--md out.md]

HaniCore names its fixed-point quantities by suffix (`_x10` = 0.1 units,
`_x100`, `_x1000`, `_dv` = 0.1 V, `_dc` = 0.1 degC + bias, `X10` in a
channel name ...). The firmware publishes a value with
`put16(offset, expr)` (hcmain_me711.c) or `och16(offset, expr)` (hcio711.c
and the other far telemetry blocks). This tool pairs every such call with
the [OutputChannels] declaration at the same offset and flags:

  SCALE   the expression's suffix implies a decimal scale the .ini does not
          declare (e.g. eng_lambda_x1000() at 356 declared scale 1)
  NAME    the channel NAME carries a suffix (X10/X100/X1000/Dv/Dc) whose
          scale the declaration contradicts

Heuristic by design - an expression that is a bare counter says nothing.
It found lambdaTarget (OCH 356): published x1000, declared scale 1, so
TunerStudio, the vehicle logger (which decodes with the .ini scale) and
me711_log_analyze.py's VE-evidence ratio all see ~1000 for lambda 1.0.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import ts_ini  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths as HCP  # noqa: E402

TGT = ROOT / "firmware/targets/me711"
HANI_INI = ROOT / "tunerstudio/history/hanicore_me711_v97_dev.ini"

SUFFIX_SCALE = [  # (regex on identifier, implied scale)
    (r"_x1000\b|X1000\b", 0.001),
    (r"_x100\b|X100\b", 0.01),
    (r"_x10\b|X10\b", 0.1),
    (r"_dv\b|Dv\b", 0.1),
    (r"_dc\b|Dc\b", 0.1),
]


def implied(text: str) -> float | None:
    for rx, sc in SUFFIX_SCALE:
        if re.search(rx, text):
            return sc
    return None


def writers() -> dict[int, list[tuple[str, str, int]]]:
    out: dict[int, list[tuple[str, str, int]]] = {}
    for p in HCP.target_sources("*.c"):
        lines = p.read_text(errors="replace").splitlines()
        for i, line in enumerate(lines, 1):
            m = re.search(r"\b(?:put16|och16)\s*\(\s*(\d+)u?\s*,\s*(.+)$", line)
            if not m:
                continue
            expr = m.group(2)
            # join a continuation line or two
            j = i
            while expr.count("(") > expr.count(")") and j < len(lines) and j < i + 3:
                expr += " " + lines[j].strip()
                j += 1
            expr = re.sub(r"\)\s*;.*$", ")", expr).rstrip(";").strip()
            out.setdefault(int(m.group(1)), []).append((p.name, expr, i))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ini", default=str(HANI_INI))
    ap.add_argument("--md")
    ns = ap.parse_args()
    ini = ts_ini.load(ns.ini)
    och = ini.output_channels()
    by_off: dict[int, dict] = {}
    for c in och.values():
        if c["computed"] or c.get("kind") != "scalar":
            continue
        try:
            by_off.setdefault(int(c["offset"]), c)
        except (TypeError, ValueError):
            pass
    W = writers()
    rows = []
    for off, ws in sorted(W.items()):
        c = by_off.get(off)
        if not c:
            continue
        try:
            declared = float(c["scale"]) if c["scale"] is not None else 1.0
        except ValueError:
            declared = None
        for fname, expr, line in ws:
            # a multiply/divide in the expression rescales - skip those
            if re.search(r"[*/]\s*\d", expr):
                continue
            imp = implied(expr)
            if imp is not None and declared is not None and abs(imp - declared) > 1e-9:
                rows.append(("SCALE", off, c["name"], declared, imp, f"{fname}:{line}", expr))
        nimp = implied(c["name"])
        if nimp is not None and declared is not None and abs(nimp - declared) > 1e-9 \
                and not c["name"].endswith("Raw"):
            rows.append(("NAME", off, c["name"], declared, nimp, "", ""))
    md = ["| kind | OCH | channel | declared scale | implied scale | writer | expression |",
          "|---|---|---|---|---|---|---|"]
    for k, off, n, d, i, w, e in rows:
        md.append(f"| {k} | {off} | `{n}` | {d:g} | {i:g} | {w} | `{e[:60]}` |")
    text = "\n".join(md) + "\n"
    print(text)
    if ns.md:
        Path(ns.md).write_text(text, encoding="utf-8")
    return 1 if rows else 0


if __name__ == "__main__":
    sys.exit(main())
