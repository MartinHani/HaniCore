#!/usr/bin/env python3
r"""
ts_dash_proof.py - the generated Gauge Cluster must describe THIS .ini.

    py tests\tunerstudio\ts_dash_proof.py [--ini path] [--dash path]

TWO ARTEFACTS THAT MUST AGREE, AND NOTHING THAT MAKES THEM. That defect has
cost this project four incidents and a .dash beside
an .ini is exactly its shape: the dashboard names output channels by string,
and nothing in TunerStudio complains when one of them stops existing - the
gauge simply sits at zero forever.

So this gate loads BOTH and requires:

  1. the .dash is well-formed XML and carries the template's font/bezel/needle
     image blobs, because a cluster without them renders as empty rectangles;
  2. its <versionInfo firmwareSignature> is the .ini's signature;
  3. every Gauge's <OutputChannel> is a channel the .ini declares - scalar or
     expression - and its Title/Units/Min/Max match that channel's own
     [GaugeConfigurations] line;
  4. there is one Gauge per [FrontPage] gaugeN and one Indicator per
     [FrontPage] indicator, in that order;
  5. every Indicator's <OutputChannel> decodes back to an expression over
     channels the .ini declares. TunerStudio stores `x != 0` as `xNOTEQ0_OC`,
     so this is where a typo hides: the name resolves to nothing and the
     indicator is permanently off, which looks exactly like "no fault".

MUTATION TESTED, five ways, plus a control.
"""
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import gen_hanicore_dash as DASH        # noqa: E402

DEFAULT_INI = ROOT / "tunerstudio/hanicore_me711.ini"
DEFAULT_DASH = ROOT / "tunerstudio/HaniCore.dash"

COMP = re.compile(r'<dashComp type="([^"]+)">(.*?)</dashComp>', re.S)


def tag_text(body, tag):
    m = (re.search(r"<%s [^>]*>(.*?)</%s>" % (tag, tag), body, re.S)
         or re.search(r"<%s>(.*?)</%s>" % (tag, tag), body, re.S))
    return m.group(1).strip() if m else ""


def ini_channels(path: Path):
    """Every name [OutputChannels] declares, scalar or expression."""
    names = set()
    sec = None
    for raw in path.read_text(errors="replace").splitlines():
        m = re.match(r"^\s*\[(\w+)\]", raw)
        if m:
            sec = m.group(1)
            continue
        if sec != "OutputChannels":
            continue
        body = raw.split(";", 1)[0].strip()
        m = re.match(r"^([A-Za-z_]\w*)\s*=", body)
        if m:
            names.add(m.group(1))
    return names


def decode_indicator_names(encoded: str):
    """Undo DashboardFactory.encodeIndicatorChannel() far enough to name the
    channels involved. `fuelCutNOTEQ0_OC` -> {'fuelCut'}."""
    s = encoded
    if s.endswith("_OC"):
        s = s[:-3]
    for word in ("NOTEQ", "GTE", "LTE", "EQ", "GT", "LT"):
        s = s.replace(word, " ")
    return {tok for tok in re.findall(r"[A-Za-z_]\w*", s)}


def check(ini_path: Path, dash_text: str, verbose=True):
    problems = []
    front_g, front_i, gauges, signature = DASH.read_ini(ini_path)
    chans = ini_channels(ini_path)

    try:
        ET.fromstring(dash_text)
    except ET.ParseError as e:
        problems.append("XML  the dashboard does not parse: %s" % e)
        return problems, {}

    for need in ("FRADM.TTF", "BezelgreyNarrow.png",
                 "fatNeedleRedShadowed2.png"):
        if ('fileName="%s"' % need) not in dash_text:
            problems.append("ASSET  the template image %s is missing - a "
                            "cluster without its bezel and needle renders as "
                            "empty rectangles" % need)

    m = re.search(r'firmwareSignature="([^"]*)"', dash_text)
    if not m:
        problems.append("SIG  no firmwareSignature in the dashboard")
    elif m.group(1) != signature:
        problems.append("SIG  dashboard says %r, the .ini says %r"
                        % (m.group(1), signature))

    comps = COMP.findall(dash_text)
    dg = [b for t, b in comps if t == "Gauge"]
    di = [b for t, b in comps if t == "Indicator"]

    if len(dg) != len(front_g):
        problems.append("COUNT  %d dashboard gauges, %d [FrontPage] gauges"
                        % (len(dg), len(front_g)))
    if len(di) != len(front_i):
        problems.append("COUNT  %d dashboard indicators, %d [FrontPage] "
                        "indicators" % (len(di), len(front_i)))

    for i, body in enumerate(dg):
        oc = tag_text(body, "OutputChannel")
        if oc not in chans:
            problems.append("GAUGE  gauge %d drives %r, which [OutputChannels] "
                            "does not declare - it would sit at zero forever"
                            % (i + 1, oc))
            continue
        if i < len(front_g):
            g = gauges.get(front_g[i])
            if not g:
                problems.append("GAUGE  [FrontPage] gauge%d names %s, which "
                                "has no [GaugeConfigurations] line"
                                % (i + 1, front_g[i]))
                continue
            if g[0] != oc:
                problems.append("GAUGE  gauge %d drives %r but [FrontPage] "
                                "gauge%d is %s, whose channel is %r"
                                % (i + 1, oc, i + 1, front_g[i], g[0]))
            want_t = g[1].strip('"')
            if tag_text(body, "Title") != DASH.xml_escape(want_t):
                problems.append("GAUGE  gauge %d title %r, the .ini says %r"
                                % (i + 1, tag_text(body, "Title"), want_t))
            for tag, idx in (("Min", 3), ("Max", 4)):
                want = DASH._num(g[idx])
                got = tag_text(body, tag)
                try:
                    if abs(float(got) - want) > 1e-6:
                        raise ValueError
                except ValueError:
                    problems.append("GAUGE  gauge %d %s is %r, the .ini says "
                                    "%s" % (i + 1, tag, got, want))

    for i, body in enumerate(di):
        oc = tag_text(body, "OutputChannel")
        if not oc:
            problems.append("IND  indicator %d has no OutputChannel" % (i + 1))
            continue
        names = decode_indicator_names(oc)
        unknown = sorted(n for n in names
                         if not n.isdigit() and n not in chans)
        if unknown:
            problems.append("IND  indicator %d is bound to %r, and %s is not "
                            "an output channel - the light is permanently "
                            "off, which looks exactly like 'no fault'"
                            % (i + 1, oc, ", ".join(unknown)))
        if i < len(front_i):
            want = DASH.encode_indicator_channel(front_i[i][0])
            if oc != want:
                problems.append("IND  indicator %d is %r, the .ini's own "
                                "expression encodes to %r" % (i + 1, oc, want))

    stats = {"gauges": len(dg), "indicators": len(di),
             "channels": len(chans), "signature": signature}
    if verbose:
        print("    %(gauges)d gauges, %(indicators)d indicators, "
              "%(channels)d channels, signature %(signature)r" % stats)
    return problems, stats


# ==========================================================================
# Mutations.
# ==========================================================================
def mutations(text):
    def first_gauge_channel(t):
        return re.sub(r'(<dashComp type="Gauge">.*?<OutputChannel '
                      r'type="String">)[^<]*(</OutputChannel>)',
                      r"\1notAChannel\2", t, count=1, flags=re.S)

    def first_gauge_max(t):
        return re.sub(r'(<dashComp type="Gauge">.*?<Max type="double">)[^<]*'
                      r'(</Max>)', r"\g<1>1234.5\g<2>", t, count=1, flags=re.S)

    def first_ind_channel(t):
        i = t.index('<dashComp type="Indicator">')
        head, tail = t[:i], t[i:]
        tail = re.sub(r'(<OutputChannel type="String">)[^<]*(</OutputChannel>)',
                      r"\1fuelCutNOTEQ9_OC\2", tail, count=1)
        return head + tail

    def drop_a_gauge(t):
        return re.sub(r'[ \t]*<dashComp type="Gauge">.*?</dashComp>\s*\n', "",
                      t, count=1, flags=re.S)

    def wrong_signature(t):
        return re.sub(r'firmwareSignature="[^"]*"',
                      'firmwareSignature="something else"', t, count=1)

    def drop_the_needle(t):
        return t.replace('fileName="fatNeedleRedShadowed2.png"',
                         'fileName="gone.png"', 1)

    return [
        ("a gauge bound to a channel that does not exist", first_gauge_channel),
        ("a gauge range that disagrees with the .ini", first_gauge_max),
        ("an indicator encoded against a value nothing produces",
         first_ind_channel),
        ("one gauge missing from the cluster", drop_a_gauge),
        ("a dashboard built for a different firmware signature",
         wrong_signature),
        ("the needle image gone", drop_the_needle),
    ]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--ini", default=str(DEFAULT_INI))
    ap.add_argument("--dash", default=str(DEFAULT_DASH))
    ap.add_argument("--no-mutate", action="store_true")
    a = ap.parse_args(argv)

    ini = Path(a.ini)
    dash = Path(a.dash)
    if not dash.exists():
        print("no dashboard at %s - run tools\\tunerstudio\\gen_hanicore_dash.py" % dash)
        return 1
    text = dash.read_text(encoding="utf-8", errors="replace")

    print("=== HaniCore dashboard proof ===\n")
    print("  ini   %s" % ini.name)
    print("  dash  %s" % dash.name)
    probs, _stats = check(ini, text)
    for p in probs:
        print("     [FAIL] " + p)
    ok = not probs
    if ok:
        print("     [PASS] every gauge and indicator resolves against the .ini")

    if not a.no_mutate:
        print("\n  --- mutations: each defect must be CAUGHT ---")
        for name, fn in mutations(text):
            mut = fn(text)
            if mut == text:
                print("      [FAIL] %-52s the mutation did not apply" % name)
                ok = False
                continue
            found, _ = check(ini, mut, verbose=False)
            new = [p for p in found if p not in probs]
            if new:
                print("      [PASS] caught: %-44s %s" % (name, new[0][:60]))
            else:
                print("      [FAIL] NOT CAUGHT: %s" % name)
                ok = False

    print("\n%s" % ("DASH PROOF PASSES - the cluster and the .ini describe the "
                    "same ECU.\nIt does NOT prove TunerStudio renders it; only "
                    "a human with\nTunerStudio open can do that."
                    if ok else "DASH PROOF FAILS."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
