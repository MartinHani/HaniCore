#!/usr/bin/env python3
r"""
gen_hanicore_dash.py - build a TunerStudio .dash Gauge Cluster for HaniCore.

    py tools\tunerstudio\gen_hanicore_dash.py [--ini path] [--out path]

THIS IS A PORT OF rusEFI'S OWN DASHBOARD GENERATOR, NOT A DESIGN.

    rusEFI java_console/io/src/main/java/com/rusefi/ts/
        DashboardFactory.java
    rusEFI java_console/io/src/main/resources/com/rusefi/ts/
        dashboard_template.dash

rusEFI does not hand-draw dashboards either. It ships one 500 KB template
carrying the font, the bezel image and the needle image as base64 blobs, then
REGENERATES every `<dashComp>` from the .ini's own [FrontPage] and
[GaugeConfigurations]. Everything else in the file - colours, sweep angle,
needle smoothing, history - is inherited by cloning the template's first gauge
and first indicator as prototypes.

So this file does what that Java class does, against HaniCore's .ini:

  * the first <dashComp type="Gauge"> and the first <dashComp type="Indicator">
    are lifted out as prototypes and every other dashComp is deleted;
  * one gauge is emitted per [FrontPage] gaugeN, with Title, Units,
    OutputChannel, the six value providers and the four numeric limits taken
    from that gauge's [GaugeConfigurations] line;
  * one indicator is emitted per [FrontPage] indicator, with the two captions,
    the four colours, and - this is the part nobody would guess - the
    expression encoded the way TunerStudio writes it as a ValueProvider name:
    `x != 0` becomes `xNOTEQ0_OC`. DashboardFactory.encodeIndicatorChannel()
    is the authority for that mapping and it is reproduced exactly;
  * the geometry is DashboardFactory's: gauges in a 4-wide grid whose height
    is what is left above the indicator strip, indicators 0.0803 wide and
    0.028 high filling from the bottom up.

WHAT IS DELIBERATELY NOT COPIED. Nothing. Where this file and the Java differ,
the Java is right and this file is a bug.

WHY IT MATTERS. TunerStudio's default cluster comes from [FrontPage], which
this repository now controls - but a .dash is what a user can open, rearrange
and keep, and it is what the release can hand them so they do not have to
rebuild eight gauges by hand. `docs/TUNERSTUDIO.md` says how the
release makes it active.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

TEMPLATE = (ROOT / "reference/rusefi/java_console/io/src/main/resources"
            / "com/rusefi/ts/dashboard_template.dash")

# DashboardFactory.java, the layout constants block. Copied, not chosen.
INDICATOR_WIDTH = 0.0803
INDICATOR_HEIGHT = 0.028
INDICATOR_BOTTOM_Y = 0.9675
INDICATORS_PER_ROW = max(1, int(1.0 / INDICATOR_WIDTH))
GAUGE_START_Y = 0.005
GAUGE_STRIP_GAP = 0.005

GAUGE_BLOCK = re.compile(r"[ \t]*<dashComp type=\"Gauge\">.*?</dashComp>\s*\n",
                         re.S)
IND_BLOCK = re.compile(r"[ \t]*<dashComp type=\"Indicator\">.*?</dashComp>\s*\n",
                       re.S)

COLOURS = {
    "white": 0xFFFFFFFF, "black": 0xFF000000, "red": 0xFFFF0000,
    "green": 0xFF00FF00, "blue": 0xFF0000FF, "yellow": 0xFFFFFF00,
    "cyan": 0xFF00FFFF, "magenta": 0xFFFF00FF, "orange": 0xFFFFA500,
    "gray": 0xFF808080, "grey": 0xFF808080,
}


# ============================================================== the .ini ====
def split_args(rhs: str):
    """Top-level commas only - not inside quotes, braces or parentheses.
    Same splitter ts_ini_grammar_proof uses, same reason."""
    args, cur, q, depth = [], "", False, 0
    for ch in rhs:
        if ch == '"':
            q = not q
        if not q:
            if ch in "{(":
                depth += 1
            elif ch in "})":
                depth -= 1
            elif ch == "," and depth == 0:
                args.append(cur.strip())
                cur = ""
                continue
        cur += ch
    if cur.strip():
        args.append(cur.strip())
    return args


def read_ini(path: Path):
    """(front_gauges, front_indicators, gauge_defs, signature)."""
    front_g, front_i, gauges = [], [], {}
    signature = ""
    sec = None
    for raw in path.read_text(errors="replace").splitlines():
        m = re.match(r"^\s*\[(\w+)\]", raw)
        if m:
            sec = m.group(1)
            continue
        body = raw.split(";", 1)[0].strip()
        if not body or "=" not in body:
            continue
        lhs, rhs = body.split("=", 1)
        lhs, rhs = lhs.strip(), rhs.strip()

        if sec == "TunerStudio" and lhs == "signature":
            signature = rhs.strip('"')
        elif sec == "GaugeConfigurations" and lhs != "gaugeCategory":
            a = split_args(rhs)
            if len(a) >= 10:
                gauges[lhs] = a
        elif sec == "FrontPage":
            if re.fullmatch(r"gauge\d+", lhs):
                front_g.append(rhs)
            elif lhs == "indicator":
                front_i.append(split_args(rhs))
    return front_g, front_i, gauges, signature


# =========================================================== the XML bits ===
def xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def strip_braces(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("{") and s.endswith("}"):
        s = s[1:-1].strip()
    return s


def set_text(block, tag, typ, value):
    return re.sub(r"<%s type=\"%s\">[^<]*</%s>" % (tag, typ, tag),
                  lambda _m: "<%s type=\"%s\">%s</%s>" % (tag, typ, value, tag),
                  block, count=1)


def set_double(block, tag, value):
    return re.sub(r"<%s type=\"double\">[^<]*</%s>" % (tag, tag),
                  lambda _m: "<%s type=\"double\">%s</%s>" % (tag, value, tag),
                  block, count=1)


def set_int(block, tag, value):
    return re.sub(r"<%s type=\"int\">[^<]*</%s>" % (tag, tag),
                  lambda _m: "<%s type=\"int\">%d</%s>" % (tag, value, tag),
                  block, count=1)


def set_colour(block, tag, name, fallback):
    argb = COLOURS.get((name or "").strip().lower(), fallback)
    a, r, g, b = (argb >> 24) & 255, (argb >> 16) & 255, (argb >> 8) & 255, \
        argb & 255
    # Java writes a signed int; Python's & 0xFFFFFFFF is unsigned, so convert.
    signed = argb - (1 << 32) if argb >= (1 << 31) else argb
    rep = ('<%s alpha="%d" blue="%d" green="%d" red="%d" type="Color">%d</%s>'
           % (tag, a, b, g, r, signed, tag))
    return re.sub(r"<%s[^>]*type=\"Color\">[^<]*</%s>" % (tag, tag),
                  lambda _m: rep, block, count=1)


def encode_indicator_channel(raw: str) -> str:
    """DashboardFactory.encodeIndicatorChannel(), reproduced exactly.

    TunerStudio stores an indicator's source as a ValueProvider NAME, so a
    comparison has to be spelled out: `x != 0` -> `xNOTEQ0_OC`. A raw
    expression does not resolve and the indicator sits dead on the cluster."""
    s = re.sub(r"\s+", "", strip_braces(raw))
    if not s:
        return ""
    for op, word in (("!=", "NOTEQ"), ("==", "EQ"), (">=", "GTE"),
                     ("<=", "LTE"), (">", "GT"), ("<", "LT")):
        if op in s:
            return s.replace(op, word) + "_OC"
    return s


def format_indicator_label(raw: str) -> str:
    """A plain caption passes through; a { expression } is respaced the way
    TunerStudio itself writes it back."""
    s = raw
    if len(s) >= 2 and s[0] == "{" and s[-1] == "}":
        s = s[1:-1].replace("(", "( ").replace(")", " )").replace(",", " , ")
    return s.strip('"') if s.startswith('"') and s.endswith('"') else s


def _num(v, default=0.0):
    try:
        return float(strip_braces(v))
    except (TypeError, ValueError):
        return default


# ============================================================== the build ===
def build(ini_path: Path, out_path: Path, title: str):
    if not TEMPLATE.exists():
        raise SystemExit("the rusEFI dashboard template is not in this "
                         "checkout: %s" % TEMPLATE)
    front_g, front_i, gauges, signature = read_ini(ini_path)
    if not front_g:
        raise SystemExit("%s has no [FrontPage] gauges" % ini_path)

    xml = TEMPLATE.read_text(encoding="utf-8", errors="replace")
    xml = re.sub(r'firmwareSignature="[^"]*"',
                 lambda _m: 'firmwareSignature="%s"' % xml_escape(signature),
                 xml, count=1)
    xml = re.sub(r'writeDate="[^"]*"',
                 lambda _m: 'writeDate="%s"'
                 % datetime.now(timezone.utc).strftime("%a %b %d %H:%M:%S UTC %Y"),
                 xml, count=1)

    gm = GAUGE_BLOCK.search(xml)
    im = IND_BLOCK.search(xml)
    if not gm or not im:
        raise SystemExit("the template has no gauge/indicator prototype")
    gauge_proto, ind_proto = gm.group(), im.group()

    xml = GAUGE_BLOCK.sub("", xml)
    xml = IND_BLOCK.sub("", xml)

    rows = max(1, -(-len(front_i) // INDICATORS_PER_ROW))
    out = []
    problems = []

    strip_top = INDICATOR_BOTTOM_Y - (rows - 1) * INDICATOR_HEIGHT
    gauge_h = (strip_top - GAUGE_STRIP_GAP - GAUGE_START_Y) / 2.0

    for i, gname in enumerate(front_g):
        g = gauges.get(gname)
        if not g:
            problems.append("[FrontPage] gauge%d names %s, which has no "
                            "[GaugeConfigurations] line" % (i + 1, gname))
            continue
        #  name = channel, "title", "units", lo, hi, loDanger, loWarn,
        #                                    hiWarn, hiDanger, vd, ld
        chan = g[0]
        gtitle = g[1].strip('"')
        units = g[2].strip('"')
        lo, hi = _num(g[3]), _num(g[4])
        lo_d, lo_w, hi_w, hi_d = _num(g[5]), _num(g[6]), _num(g[7]), _num(g[8])
        vd = int(_num(g[9])) if len(g) > 9 else 0
        ld = int(_num(g[10])) if len(g) > 10 else 0

        b = gauge_proto
        b = set_text(b, "Title", "String", xml_escape(gtitle))
        b = set_text(b, "Units", "String", xml_escape(units))
        b = set_text(b, "OutputChannel", "String", xml_escape(chan))
        for tag, val in (("MaxVP", hi), ("MinVP", lo), ("HighCriticalVP", hi_d),
                         ("HighWarningVP", hi_w), ("LowCriticalVP", lo_d),
                         ("LowWarningVP", lo_w)):
            b = set_text(b, tag, "ValueProvider", "%s" % val)
        for tag, val in (("Max", hi), ("DefaultMax", hi), ("Min", lo),
                         ("DefaultMin", lo), ("HighCritical", hi_d),
                         ("HighWarning", hi_w), ("LowCritical", lo_d),
                         ("LowWarning", lo_w)):
            b = set_double(b, tag, val)
        b = set_int(b, "ValueDigits", vd)
        b = set_int(b, "LabelDigits", ld)
        b = set_double(b, "RelativeX", 0.0015 + (i % 4) * 0.25)
        b = set_double(b, "RelativeY", GAUGE_START_Y + (i // 4) * gauge_h)
        b = set_double(b, "RelativeWidth", 0.247)
        b = set_double(b, "RelativeHeight", gauge_h)
        b = re.sub(r'<EcuConfigurationName type="String">[^<]*'
                   r'</EcuConfigurationName>',
                   '<EcuConfigurationName type="String"/>', b)
        b = b.replace('<LongClickAction type="String">null</LongClickAction>',
                      '<LongClickAction type="String"/>')
        b = b.replace('<ShortClickAction type="String">null</ShortClickAction>',
                      '<ShortClickAction type="String"/>')
        out.append(b)

    for i, ind in enumerate(front_i):
        if len(ind) < 3:
            problems.append("[FrontPage] indicator %d has %d fields"
                            % (i + 1, len(ind)))
            continue
        expr, off, on = ind[0], ind[1], ind[2]
        off_bg = ind[3] if len(ind) > 3 else "white"
        off_fg = ind[4] if len(ind) > 4 else "black"
        on_bg = ind[5] if len(ind) > 5 else "green"
        on_fg = ind[6] if len(ind) > 6 else "black"

        row, col = i // INDICATORS_PER_ROW, i % INDICATORS_PER_ROW
        b = ind_proto
        b = set_text(b, "OffText", "String",
                     xml_escape(format_indicator_label(off)))
        b = set_text(b, "OnText", "String",
                     xml_escape(format_indicator_label(on)))
        b = set_text(b, "OutputChannel", "String",
                     xml_escape(encode_indicator_channel(expr)))
        b = set_colour(b, "OffBackgroundColor", off_bg, 0xFFFFFFFF)
        b = set_colour(b, "OffTextColor", off_fg, 0xFF000000)
        b = set_colour(b, "OnBackgroundColor", on_bg, 0xFF00FF00)
        b = set_colour(b, "OnTextColor", on_fg, 0xFF000000)
        b = set_double(b, "RelativeX", col * INDICATOR_WIDTH)
        b = set_double(b, "RelativeY",
                       INDICATOR_BOTTOM_Y - (rows - 1 - row) * INDICATOR_HEIGHT)
        b = set_double(b, "RelativeWidth", INDICATOR_WIDTH)
        b = set_double(b, "RelativeHeight", INDICATOR_HEIGHT)
        b = re.sub(r'<EcuConfigurationName type="String">[^<]*'
                   r'</EcuConfigurationName>',
                   '<EcuConfigurationName type="String"/>', b)
        out.append(b)

    if problems:
        raise SystemExit("the dashboard does not resolve:\n  "
                         + "\n  ".join(problems))

    xml = xml.replace("</gaugeCluster>", "".join(out) + "    </gaugeCluster>")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(xml, encoding="utf-8", newline="\n")
    return len(front_g), len(front_i), rows, signature


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--ini", default=str(ROOT / "tunerstudio"
                                         / "hanicore_me711.ini"))
    ap.add_argument("--out", default=str(ROOT / "tunerstudio"
                                         / "HaniCore.dash"))
    ap.add_argument("--title", default="HaniCore")
    a = ap.parse_args(argv)
    ng, ni, rows, sig = build(Path(a.ini), Path(a.out), a.title)
    print("wrote %s" % a.out)
    print("  %d gauges, %d indicators in %d row(s)" % (ng, ni, rows))
    print("  signature %r" % sig)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
