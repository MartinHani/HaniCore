#!/usr/bin/env python3
r"""
ts_ini_control_inventory.py - did a UI re-layout lose, gain or rebind anything?

    py tools\tunerstudio\ts_ini_control_inventory.py <before.ini> <after.ini>

A layout pass moves lines between dialogs and panels; it must not change WHAT
a tuner can reach. This compares, between two generated .ini files:

  * every settable binding: `field = "...", <variable>[, {condition}]` -
    variable AND visibility condition, as a multiset;
  * every commandButton: (command, condition), as a multiset of commands;
  * every live channel shown in a dialog, whether as `gauge =` or
    `readout =` (a gauge widget becoming a compact readout of the SAME gauge
    is a layout change, not a lost value);
  * every indicator expression;
  * every menu entry (dialog id and label);
  * the whole of every section that is NOT [UiDialogs]/[Menu] - page layout,
    output channels, commands, gauges, tables - which a layout pass must not
    touch at all.

Label text and plain text lines are reported but do not fail: rewording is
allowed, rebinding is not. Exit 1 on any lost/changed binding.

    py tools\tunerstudio\ts_ini_control_inventory.py <before.ini> <after.ini> --reorganized-menu

A MENU REORGANISATION (the V89 rusEFI-alignment pass) moves entries between
menus, merges dialogs and embeds curves, so "the menu is identical" and "each
binding occurs as often as before" are the wrong questions. With this flag
the question becomes WHAT A TUNER CAN STILL REACH, walked from [Menu] through
every `panel =` in [UiDialogs]/[UserDefined]:

  * every (variable, condition) binding reachable before is reachable after;
  * every command button, live channel and indicator expression likewise;
  * every curve and table editor reachable before (as a menu entry or as a
    panel embedded in a dialog) is reachable after.

Everything outside [UiDialogs]/[UserDefined]/[Menu] must still be byte-for-
byte identical - that part of the gate does not relax.
"""
from __future__ import annotations

import collections
import re
import sys
from pathlib import Path


def sections(path):
    out = collections.OrderedDict()
    cur = "_head"
    out[cur] = []
    for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        s = raw.strip()
        if s.startswith("[") and s.endswith("]"):
            cur = s
            out.setdefault(cur, [])
            continue
        out[cur].append(raw.rstrip())
    return out


def ui_inventory(lines):
    inv = collections.defaultdict(collections.Counter)
    for raw in lines:
        s = raw.strip()
        m = re.match(r'field\s*=\s*"((?:[^"\\]|\\.)*)"\s*,\s*(\w+)\s*(?:,\s*(\{.*\}))?\s*$', s)
        if m:
            inv["binding"][(m.group(2), (m.group(3) or "").replace(" ", ""))] += 1
            continue
        m = re.match(r'field\s*=\s*"((?:[^"\\]|\\.)*)"\s*$', s)
        if m:
            inv["text"][m.group(1)] += 1
            continue
        m = re.match(r'commandButton\s*=\s*"[^"]*"\s*,\s*(\w+)\s*(?:,\s*(\{.*\}))?', s)
        if m:
            inv["command"][m.group(1)] += 1
            continue
        m = re.match(r'(gauge|readout)\s*=\s*(\w+)', s)
        if m:
            inv["channel"][m.group(2)] += 1
            continue
        m = re.match(r'indicator\s*=\s*(\{[^}]*\})', s)
        if m:
            inv["indicator"][m.group(1).replace(" ", "")] += 1
    return inv


def reachable(secs):
    """What a person can open, walked from [Menu] through `panel =`.

    Returns (inventory of every reached block, reached curve/table ids)."""
    blocks, cur = {}, None
    for raw in secs.get("[UiDialogs]", []) + secs.get("[UserDefined]", []):
        s = raw.strip()
        m = re.match(r"(dialog|indicatorPanel|readoutPanel)\s*=\s*(\w+)", s)
        if m:
            cur = m.group(2)
            blocks[cur] = []
            continue
        if cur is not None:
            blocks[cur].append(raw)
    editors = set()
    for raw in secs.get("[CurveEditor]", []):
        m = re.match(r"\s*curve\s*=\s*(\w+)", raw)
        if m:
            editors.add(m.group(1))
    for raw in secs.get("[TableEditor]", []):
        m = re.match(r"\s*table\s*=\s*(\w+)\s*,\s*(\w+)", raw)
        if m:
            editors |= {m.group(1), m.group(2)}
    work = [m.group(1) for raw in secs.get("[Menu]", [])
            for m in [re.match(r"\s*(?:subMenu|groupChildMenu)\s*=\s*(\w+)",
                               raw)] if m]
    seen, lines = set(), []
    while work:
        n = work.pop()
        if n in seen:
            continue
        seen.add(n)
        for raw in blocks.get(n, []):
            lines.append(raw)
            m = re.match(r"\s*panel\s*=\s*(\w+)", raw)
            if m:
                work.append(m.group(1))
    return ui_inventory(lines), seen & editors


def main_reorganized(a, b) -> int:
    sa, sb = sections(a), sections(b)
    fails = 0
    for sec in sorted(set(sa) | set(sb)):
        if sec in ("[UiDialogs]", "[UserDefined]", "[Menu]"):
            continue
        if sa.get(sec) != sb.get(sec):
            print("FAIL  section %s changed" % sec)
            fails += 1
    if not fails:
        print("PASS  every non-UI section is identical (page, channels, "
              "commands, gauges, tables, curves)")
    (ia, ea), (ib, eb) = reachable(sa), reachable(sb)
    for kind, what in (("binding", "settable binding (variable, condition)"),
                       ("command", "command button"),
                       ("channel", "live channel"),
                       ("indicator", "indicator expression")):
        lost = set(ia[kind]) - set(ib[kind])
        if lost:
            print("FAIL  %d %s(s) reachable before, not after: %s"
                  % (len(lost), what, sorted(lost)[:10]))
            fails += 1
        else:
            print("PASS  all %d reachable %ss still reachable (%d now)"
                  % (len(set(ia[kind])), what, len(set(ib[kind]))))
    lost = ea - eb
    if lost:
        print("FAIL  curve/table editor(s) no longer reachable: %s"
              % sorted(lost))
        fails += 1
    else:
        print("PASS  all %d reachable curve/table editors still reachable"
              % len(ea))
    print("\n%s" % ("CONTROL INVENTORY PRESERVED (menu reorganised)"
                    if not fails else
                    "CONTROL INVENTORY CHANGED - %d problem(s)" % fails))
    return 1 if fails else 0


def main() -> int:
    if "--reorganized-menu" in sys.argv:
        args = [x for x in sys.argv[1:] if x != "--reorganized-menu"]
        return main_reorganized(args[0], args[1])
    a, b = sys.argv[1], sys.argv[2]
    sa, sb = sections(a), sections(b)
    fails = 0

    # 1. Everything outside the UI must be byte-identical.
    for sec in sorted(set(sa) | set(sb)):
        if sec in ("[UiDialogs]", "[UserDefined]", "[Menu]"):
            continue
        if sa.get(sec) != sb.get(sec):
            print("FAIL  section %s changed" % sec)
            fails += 1
    if not fails:
        print("PASS  every non-UI section is identical (page, channels, "
              "commands, gauges, tables, curves)")

    ua = ui_inventory(sa.get("[UiDialogs]", []) + sa.get("[UserDefined]", []))
    ub = ui_inventory(sb.get("[UiDialogs]", []) + sb.get("[UserDefined]", []))

    # 2. Bindings: same variable + same visibility condition, same count.
    lost = ua["binding"] - ub["binding"]
    gained = ub["binding"] - ua["binding"]
    if lost:
        print("FAIL  %d settable binding(s) lost or rebound: %s"
              % (sum(lost.values()), sorted(lost)[:12]))
        fails += 1
    else:
        print("PASS  all %d settable bindings present with their conditions"
              % sum(ua["binding"].values()))
    if gained:
        print("INFO  %d binding(s) added: %s" % (sum(gained.values()),
                                                sorted(gained)[:12]))

    # 3. Commands: every command still reachable (count may grow - e.g. an
    #    ABORT repeated beside each button column).
    lost = set(ua["command"]) - set(ub["command"])
    if lost:
        print("FAIL  command(s) no longer on any button: %s" % sorted(lost))
        fails += 1
    else:
        print("PASS  all %d commands still on a button" % len(ua["command"]))
    more = {c: (ua["command"][c], ub["command"][c]) for c in ub["command"]
            if ub["command"][c] != ua["command"].get(c, 0)}
    if more:
        print("INFO  button count changed: %s" % more)

    # 4. Live channels: gauge or readout, the set must be kept.
    lost = set(ua["channel"]) - set(ub["channel"])
    if lost:
        print("FAIL  live value(s) no longer shown anywhere: %s" % sorted(lost))
        fails += 1
    else:
        print("PASS  all %d live channels still shown (gauge or readout)"
              % len(ua["channel"]))

    # 5. Indicators.
    lost = ua["indicator"] - ub["indicator"]
    if lost:
        print("FAIL  indicator(s) lost: %s" % sorted(lost)[:8])
        fails += 1
    else:
        print("PASS  all %d indicators present" % sum(ua["indicator"].values()))

    # 6. Menu.
    ma = [l.strip() for l in sa.get("[Menu]", []) if "Menu" in l]
    mb = [l.strip() for l in sb.get("[Menu]", []) if "Menu" in l]
    if ma != mb:
        print("FAIL  menu changed")
        fails += 1
    else:
        print("PASS  menu identical (%d entries)" % len(ma))

    # 7. Text: informational only.
    tl = ua["text"] - ub["text"]
    if tl:
        print("INFO  %d text line(s) differ (rewording/relocation allowed)"
              % sum(tl.values()))
    print("\n%s" % ("CONTROL INVENTORY PRESERVED" if not fails else
                    "CONTROL INVENTORY CHANGED - %d problem(s)" % fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
