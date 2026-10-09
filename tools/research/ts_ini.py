#!/usr/bin/env python3
"""
ts_ini.py - a small, dependency-free TunerStudio .ini reader for research tools.

It is NOT the project's contract checker (tests/tunerstudio/ts_ini_ui_contract.py and
friends are). It exists so tools/research/* can inventory and compare two
.ini files - rusEFI's generated Proteus file and HaniCore's generated file -
mechanically and reproducibly.

What it understands (enough for inventory, not for TunerStudio emulation):

  * sections `[Name]`; `[UiDialogs]` is treated as `[UserDefined]` (TS alias)
  * `#define NAME = ...` list macros; `#if/#else/#endif` - every branch is
    kept (research wants to see what CAN appear, not one build's choice)
  * `key = v1, v2, {expr}, "str"` - split on top-level commas, respecting
    quotes and braces
  * Constants: scalar/bits/array/string with page, type, offset
  * OutputChannels: stored channels (type/offset) and computed `{expr}`
  * GaugeConfigurations with gaugeCategory
  * Datalog entries, FrontPage, Menu (menu/subMenu/groupMenu/groupChildMenu
    with enable/visible expressions), dialogs with their children,
    TableEditor/CurveEditor, SettingContextHelp, ControllerCommands,
    VeAnalyze, WueAnalyze, BurstMode, LoggerDefinition, Tools, EventTriggers
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

ALIASES = {"UiDialogs": "UserDefined"}


def split_top(s: str) -> list[str]:
    """Split on commas that are not inside quotes, braces or brackets."""
    out, cur, depth, q = [], [], 0, False
    i = 0
    while i < len(s):
        c = s[i]
        if q:
            cur.append(c)
            if c == "\\" and i + 1 < len(s):
                cur.append(s[i + 1]); i += 2; continue
            if c == '"':
                q = False
        elif c == '"':
            q = True; cur.append(c)
        elif c in "{[(":
            depth += 1; cur.append(c)
        elif c in "}])":
            depth -= 1; cur.append(c)
        elif c == "," and depth == 0:
            out.append("".join(cur).strip()); cur = []
        else:
            cur.append(c)
        i += 1
    tail = "".join(cur).strip()
    if tail or out:
        out.append(tail)
    return out


def strip_comment(line: str) -> str:
    """Remove a trailing ';' comment that is outside quotes/braces."""
    q, depth = False, 0
    for i, c in enumerate(line):
        if c == '"':
            q = not q
        elif not q and c == "{":
            depth += 1
        elif not q and c == "}":
            depth -= 1
        elif c == ";" and not q and depth <= 0:
            return line[:i]
    return line


def unq(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


def expr(s: str | None) -> str | None:
    if s is None:
        return None
    s = s.strip()
    if s.startswith("{") and s.endswith("}"):
        return s[1:-1].strip()
    return s or None


@dataclass
class Entry:
    section: str
    key: str
    args: list[str]
    line: int
    raw: str
    ctx: dict = field(default_factory=dict)   # dialog / menu / category context


@dataclass
class Ini:
    path: Path
    entries: list[Entry] = field(default_factory=list)
    defines: dict[str, list[str]] = field(default_factory=dict)
    sections: list[str] = field(default_factory=list)
    comments_by_line: dict[int, str] = field(default_factory=dict)

    # ---- convenience views -------------------------------------------
    def sec(self, name: str) -> list[Entry]:
        return [e for e in self.entries if e.section == name]

    def constants(self) -> dict[str, dict]:
        out = {}
        page = 1
        for e in self.sec("Constants"):
            if e.key == "page":
                page = int(e.args[0]) if e.args and e.args[0].isdigit() else page
                continue
            if not e.args:
                continue
            kind = e.args[0]
            if kind not in ("scalar", "bits", "array", "string"):
                continue
            d = {"name": e.key, "kind": kind, "page": page, "line": e.line,
                 "type": e.args[1] if len(e.args) > 1 else None}
            try:
                d["offset"] = int(e.args[2], 0)
            except (IndexError, ValueError):
                d["offset"] = None
            if kind == "bits":
                d["options"] = [unq(a) for a in e.args[4:]]
                d["bitspec"] = e.args[3] if len(e.args) > 3 else None
            elif kind == "scalar":
                d["units"] = unq(e.args[3]) if len(e.args) > 3 else ""
                d["scale"] = e.args[4] if len(e.args) > 4 else None
                d["translate"] = e.args[5] if len(e.args) > 5 else None
            elif kind == "array":
                d["shape"] = e.args[3] if len(e.args) > 3 else None
                d["units"] = unq(e.args[4]) if len(e.args) > 4 else ""
            d["comment"] = self.comments_by_line.get(e.line, "")
            out[e.key] = d
        return out

    def output_channels(self) -> dict[str, dict]:
        out = {}
        for e in self.sec("OutputChannels"):
            if e.key in ("ochGetCommand", "ochBlockSize") or not e.args:
                continue
            a0 = e.args[0]
            if a0 in ("scalar", "bits", "array"):
                d = {"name": e.key, "computed": False, "kind": a0,
                     "type": e.args[1] if len(e.args) > 1 else None,
                     "offset": e.args[2] if len(e.args) > 2 else None,
                     "units": unq(e.args[3]) if len(e.args) > 3 and a0 == "scalar" else "",
                     "scale": e.args[4] if len(e.args) > 4 and a0 == "scalar" else None,
                     "translate": e.args[5] if len(e.args) > 5 and a0 == "scalar" else None}
                if a0 == "bits":
                    d["bitspec"] = e.args[3] if len(e.args) > 3 else None
            elif a0.startswith("{"):
                d = {"name": e.key, "computed": True, "expr": expr(a0),
                     "units": unq(e.args[1]) if len(e.args) > 1 else ""}
            else:
                continue
            d["line"] = e.line
            d["comment"] = self.comments_by_line.get(e.line, "")
            out[e.key] = d
        return out

    def gauges(self) -> list[dict]:
        out = []
        for e in self.sec("GaugeConfigurations"):
            if e.key == "gaugeCategory" or len(e.args) < 3:
                continue
            out.append({"name": e.key, "channel": e.args[0], "title": unq(e.args[1]),
                        "units": unq(e.args[2]), "category": e.ctx.get("category"),
                        "line": e.line})
        return out

    def dialogs(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for e in self.sec("UserDefined"):
            dname = e.ctx.get("dialog")
            if e.key == "dialog":
                out[e.args[0]] = {"name": e.args[0],
                                  "title": unq(e.args[1]) if len(e.args) > 1 else "",
                                  "layout": e.args[2] if len(e.args) > 2 else "",
                                  "children": [], "line": e.line}
            elif dname and dname in out:
                out[dname]["children"].append(
                    {"key": e.key, "args": e.args, "line": e.line})
        return out

    def menus(self) -> list[dict]:
        """Flat list: every menu item with its top-level menu and group."""
        out = []
        top = group = None
        for e in self.sec("Menu"):
            if e.key == "menu":
                top = unq(e.args[0]); group = None
            elif e.key == "groupMenu":
                group = unq(e.args[0])
            elif e.key in ("subMenu", "groupChildMenu"):
                if e.key == "subMenu":
                    group = None
                a = list(e.args)
                # rusEFI's own file has `subMenu = dcMotorActuatorHw  "label", { 1 }`
                # (a missing comma); split the fused first argument.
                if '"' in a[0]:
                    t0, lab = a[0].split('"', 1)
                    a = [t0.strip(), '"' + lab] + a[1:]
                target = a[0]
                label = unq(a[1]) if len(a) > 1 else ""
                rest = a[2:]
                exprs = [expr(x) for x in rest if x.strip().startswith("{")]
                out.append({"menu": top, "group": group, "target": target,
                            "label": label,
                            "enable": exprs[0] if len(exprs) > 0 else None,
                            "visible": exprs[1] if len(exprs) > 1 else None,
                            "line": e.line})
        return out

    def tables(self) -> dict[str, dict]:
        out, cur = {}, None
        for e in self.sec("TableEditor"):
            if e.key == "table":
                cur = e.args[0]
                out[cur] = {"name": cur, "map3d": e.args[1] if len(e.args) > 1 else None,
                            "title": unq(e.args[2]) if len(e.args) > 2 else "",
                            "line": e.line}
            elif cur and e.key in ("xBins", "yBins", "zBins", "topicHelp", "xyLabels",
                                   "gridHeight", "upDownLabel"):
                out[cur][e.key] = e.args
        return out

    def curves(self) -> dict[str, dict]:
        out, cur = {}, None
        for e in self.sec("CurveEditor"):
            if e.key == "curve":
                cur = e.args[0]
                out[cur] = {"name": cur, "title": unq(e.args[1]) if len(e.args) > 1 else "",
                            "line": e.line}
            elif cur and e.key in ("xBins", "yBins", "columnLabel", "xAxis", "yAxis",
                                   "topicHelp", "lineLabel"):
                out[cur].setdefault(e.key, []).append(e.args)
        return out

    def datalog(self) -> list[dict]:
        out = []
        for e in self.sec("Datalog"):
            if e.key != "entry" or len(e.args) < 2:
                continue
            out.append({"channel": e.args[0], "label": unq(e.args[1]),
                        "type": e.args[2] if len(e.args) > 2 else None,
                        "format": unq(e.args[3]) if len(e.args) > 3 else None,
                        "cond": expr(e.args[4]) if len(e.args) > 4 else None,
                        "line": e.line})
        return out

    def context_help(self) -> dict[str, str]:
        return {e.key: unq(e.args[0]) for e in self.sec("SettingContextHelp") if e.args}


_KV = re.compile(r"^\s*([A-Za-z_#][\w.#]*)\s*=\s*(.*)$")
_DEF = re.compile(r"^\s*#define\s+(\w+)\s*=\s*(.*)$")


def load(path: str | Path) -> Ini:
    p = Path(path)
    ini = Ini(p)
    sect = "_preamble"
    ctx: dict = {}
    for ln, raw in enumerate(p.read_text(encoding="latin-1").splitlines(), 1):
        line = raw.rstrip()
        s = line.strip()
        if not s or s.startswith(";"):
            continue
        if s.startswith("[") and "]" in s and "=" not in s.split("]")[0]:
            name = s[1:s.index("]")]
            sect = ALIASES.get(name, name)
            ini.sections.append(name)
            ctx = {}
            continue
        m = _DEF.match(s)
        if m:
            ini.defines[m.group(1)] = [unq(x) for x in split_top(strip_comment(m.group(2)))]
            continue
        if s.startswith("#"):
            continue          # #if/#else/#endif/#set/#unset: keep every branch
        body = strip_comment(s)
        comment = s[len(body):].lstrip(";").strip()
        m = _KV.match(body)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        args = split_top(val) if val else []
        if sect == "GaugeConfigurations" and key == "gaugeCategory":
            ctx["category"] = unq(args[0]) if args else None
        if sect == "UserDefined" and key == "dialog":
            ctx["dialog"] = args[0] if args else None
        e = Entry(sect, key, args, ln, raw, dict(ctx))
        ini.entries.append(e)
        if comment:
            ini.comments_by_line[ln] = comment
    return ini


def expand_define(ini: Ini, args: list[str]) -> list[str]:
    """`bits` option lists may be `$macro`; expand them."""
    out = []
    for a in args:
        a2 = a.strip()
        if a2.startswith("$") and a2[1:] in ini.defines:
            out.extend(ini.defines[a2[1:]])
        else:
            out.append(unq(a2))
    return out
