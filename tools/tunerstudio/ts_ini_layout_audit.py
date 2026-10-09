#!/usr/bin/env python3
r"""
ts_ini_layout_audit.py - how tall and how wide is every dialog a menu opens?

    py tools\tunerstudio\ts_ini_layout_audit.py [ini]            report, worst first
    py tools\tunerstudio\ts_ini_layout_audit.py [ini] --max-rows 40   also FAIL above it

WHY. HaniCore's dialogs were generated one panel under the next, and real
TunerStudio showed "Trigger and sync" as ~40 full-size gauge widgets in one
column: scrolling on a 1920x1080 screen for every glance. A layout is a tree
(yAxis stacks, xAxis and border place side by side), so its size can be
ESTIMATED from the .ini alone - which makes "less scrolling" a number a gate
can hold rather than an impression.

THE ESTIMATE, in text rows (~23 px) and columns (~1 field panel, ~380 px):
  field / text line / commandButton ..... 1 row
  gauge widget inside a dialog .......... 5 rows (a dial or bar is ~110 px)
  readoutPanel / indicatorPanel of n, c . ceil(n/c) rows, c/2 columns
  yAxis (default) ....................... rows add, width = widest child
  xAxis ................................. rows = tallest child, widths add
  border ................................ West|Center|East side by side,
                                          North/South added on top
A 1080p screen leaves ~38 rows inside a dialog after the title, menu and
task bar; beyond that TunerStudio scrolls.

It is an estimate of the TREE, not a screenshot. It says which dialogs are
built wrong; real TunerStudio is still the acceptance.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INI = ROOT / "tunerstudio/hanicore_me711.ini"
SCREEN_ROWS = 38


def parse(path: Path):
    txt = path.read_text(encoding="utf-8", errors="replace").splitlines()
    sec = None
    dialogs, cur = {}, None
    menu = []
    for raw in txt:
        s = raw.split(";", 1)[0].strip() if not raw.strip().startswith(
            ("field", "text")) else raw.strip()
        if s.startswith("[") and s.endswith("]"):
            sec = s
            cur = None
            continue
        if sec in ("[UiDialogs]", "[UserDefined]"):
            m = re.match(r'(dialog|indicatorPanel|readoutPanel)\s*=\s*(\w+)'
                         r'\s*(?:,\s*"?([^",]*)"?)?\s*(?:,\s*(\w+))?', s)
            if m:
                kind, name = m.group(1), m.group(2)
                layout = "yAxis"
                cols = 1
                if kind == "dialog":
                    layout = (m.group(4) or "yAxis")
                else:
                    try:
                        cols = int((m.group(3) or "1").strip())
                    except ValueError:
                        cols = 1
                cur = dict(kind=kind, name=name, layout=layout, cols=cols,
                           items=[])
                dialogs[name] = cur
                continue
            if cur is None:
                continue
            m = re.match(r'(field|gauge|panel|commandButton|indicator|readout|'
                         r'liveGraph|slider)\s*=\s*(.*)$', s)
            if m:
                cur["items"].append((m.group(1), m.group(2)))
        elif sec == "[Menu]":
            m = re.match(r'(?:subMenu|groupChildMenu)\s*=\s*(\w+)\s*,\s*"([^"]*)"', s)
            if m and m.group(1) != "std_separator":
                menu.append((m.group(1), m.group(2)))
    return dialogs, menu


def size(dialogs, name, depth=0):
    """(rows, cols) of a dialog or panel."""
    d = dialogs.get(name)
    if d is None or depth > 12:
        return (0, 0)                     # a table/curve editor: its own window
    if d["kind"] in ("readoutPanel", "indicatorPanel"):
        n = sum(1 for k, _ in d["items"] if k in ("readout", "indicator"))
        c = max(1, d["cols"])
        return (math.ceil(n / c), max(1, c / 2))
    kids = []                              # (rows, cols, placement)
    for k, v in d["items"]:
        if k == "panel":
            parts = [p.strip() for p in v.split(",")]
            place = parts[1] if len(parts) > 1 and parts[1] in (
                "North", "South", "East", "West", "Center") else None
            r, c = size(dialogs, parts[0], depth + 1)
            kids.append((r, c, place))
        elif k == "gauge":
            kids.append((5, 1, None))
        elif k in ("field", "commandButton", "slider"):
            kids.append((1, 1, None))
        elif k in ("indicator", "readout"):
            kids.append((1, 0.5, None))
        elif k == "liveGraph":
            kids.append((8, 2, None))
    if not kids:
        return (0, 0)
    lay = d["layout"]
    if lay == "xAxis":
        return (max(r for r, _c, _p in kids), sum(c for _r, c, _p in kids))
    if lay == "border":
        side = [k for k in kids if k[2] in ("West", "East", "Center", None)]
        ns = [k for k in kids if k[2] in ("North", "South")]
        rows = max((r for r, _c, _p in side), default=0) + sum(r for r, _c, _p in ns)
        cols = max(sum(c for _r, c, _p in side),
                   max((c for _r, c, _p in ns), default=0))
        return (rows, cols)
    return (sum(r for r, _c, _p in kids), max(c for _r, c, _p in kids))


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    ini = Path(args[0]) if args else DEFAULT_INI
    max_rows = None
    if "--max-rows" in sys.argv:
        max_rows = int(sys.argv[sys.argv.index("--max-rows") + 1])
    dialogs, menu = parse(ini)
    rows = []
    for did, label in menu:
        if did not in dialogs:
            continue
        r, c = size(dialogs, did)
        rows.append((r, c, did, label))
    rows.sort(reverse=True)
    print("%-5s %-5s %-24s %s" % ("rows", "cols", "dialog", "menu label"))
    for r, c, did, label in rows:
        flag = "  SCROLLS" if r > SCREEN_ROWS else ""
        print("%5d %5.1f %-24s %s%s" % (r, c, did, label, flag))
    over = [x for x in rows if x[0] > SCREEN_ROWS]
    wide = [x for x in rows if x[1] > 4.5]
    print("\n%d menu dialogs; %d taller than %d rows; %d wider than ~1900 px"
          % (len(rows), len(over), SCREEN_ROWS, len(wide)))
    if max_rows is not None:
        bad = [x for x in rows if x[0] > max_rows]
        if bad:
            print("FAIL: %d dialog(s) above %d rows: %s" % (
                len(bad), max_rows, ", ".join(b[2] for b in bad)))
            return 1
        print("PASS: every menu dialog within %d rows" % max_rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
