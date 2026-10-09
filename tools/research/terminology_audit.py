#!/usr/bin/env python3
"""
terminology_audit.py - find Bosch / C167 / developer terms in the text a
TunerStudio user actually sees, and propose standalone-ECU wording.

    python3 tools/research/terminology_audit.py [--md out.md] [--csv out.csv]

Scans: menu labels, dialog titles, field labels (incl. '#'/'!' text rows),
table/curve titles and axis labels, gauge titles and units, front-page
indicator texts, commandButton labels, help text. NOT scanned: channel /
constant NAMES (internal identifiers - TunerStudio shows the gauge TITLE,
not the channel name, except where the generator used the name AS the
title, which is itself reported as RAW-NAME-AS-TITLE).

Each hit has a severity:
  TUNER    appears in a normal tuning workflow (Setup/Fuel/Ignition/...)
  DIAG     appears only under Diagnostics / Controller / Developer menus
The replacement column is the recommended plain-language term (rusEFI's
wording where rusEFI has the same concept).
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import ts_ini  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
HANI_INI = ROOT / "tunerstudio/history/hanicore_me711_v97_dev.ini"

# (regex, category, recommended wording). Word-bounded, case-sensitive where
# the abbreviation is.
TERMS: list[tuple[str, str, str]] = [
    (r"\brl\b|Relative charge|relative air charge|RELATIVE AIR CHARGE", "Bosch",
     "'Cylinder filling %' (rusEFI 'Cyl Filling') or 'Load %'; say what 100 % means"),
    (r"\bKFZW2?\b|\bKFMSNWDK\b|\bKLAF\b|\bKFURL\b|\bKFPRG\b|\bKRKTE\b|\bTVUB\b|\bKFSZT\b|\bKUMSRL\b|\bDSLGRAD\b|\bDSLOFS\b|\bLDRXN\b",
     "Bosch map name", "describe the quantity ('stock ignition map'); keep map names in help/source notes only"),
    (r"\bTMOT\b|\bTANS\b|\bHFM2?\b|\bDSS\b|\bDMTL\b|\bLS[12][VH]K\b|\bUBAT\b|\bUBR\b|\bHOG\b|\bIP[12]S?\b|\bSP[12]S?\b|\bPHA[124]\b|\bNWDG\b|\bKWDG\b|\bDZG\b",
     "Bosch signal", "'Coolant temp', 'Intake air temp', 'MAF', 'Pedal track 1', 'Cam 1', 'Crank'..."),
    (r"\bZUE\d?\b|\bEV\d\b|\bEKP\b|\bN75\b|\bN205\b|\bG39\b|\bG62\b|\bG42\b|\bG79\b|\bG185\b|\bJ271\b",
     "VAG/Bosch part id", "function name first ('Injector 3', 'Boost solenoid'); part number in help only"),
    (r"\bS5500\b|\bASIC\b|\bCJ120\b|\bCJ220\b|\bCJ910\b|\bCJ920\b|\bCK110\b|\bCC195\b|\bUMKOM\b|\bBUK138\b",
     "chip name", "'wideband controller', 'throttle driver', 'ignition driver', 'knock processor'"),
    (r"\bC167\b|\bCAPCOM\b|\bCC\d{1,2}\b|\bP\d\.\d{1,2}\b|\bPOUT\d\b|\bAN\d{1,2}\b|\bSSC\b|\bPEC\d?\b|\bASC0\b|\bT7\b|\bT1\b|\bSFR\b|\bXRAM\b|\bNCODE\b|\bFCODE\b|\bILVL\b",
     "MCU internal", "never in a tuner dialog; use connector cavity numbers ('pin 93 - Coolant temperature')"),
    (r"\bOCH\b|\bLKG\b|\bNVM\b|\bSRAM\b|\bDESIRED\b|\bACTIVE page\b|\blayout id\b|\bCRC16\b|\bwalk-?back\b",
     "firmware internal", "'Calibration storage', 'last good calibration'"),
    (r"\bUR\b|\bUA0?\b|\bRi\b|\bVeff\b|\bIp\b", "wideband internal",
     "'Sensor temperature (Ri)', 'Pump current' - keep in Wideband diagnostics"),
    (r"\bKWP\b|\bGOFAST\b|\b5-baud\b|\bKL15\b|\bKL30\b|\bKl\.?87\b", "protocol/wiring",
     "'Ignition key on', 'Battery', 'K-line connection' (help)"),
    (r"\bdry\b|\bslot\b|\bepoch\b|\bcursor\b|\btick\b", "developer",
     "remove from tuner views"),
    (r"\bEGENFR\b|\bSF\b|\bDVE2?\b|\bED_RST\b|\bNLEN_FR\b", "Bosch net name",
     "'Throttle driver enable', 'Throttle driver fault'"),
    (r"\bAPP\b", "jargon", "'Pedal' (project rule)"),
    (r"\bV\d{2}\b(?![\w.])", "release narrative", "no release numbers in tuner text"),
]

TUNER_MENUS = {"&Setup", "&Fuel", "&Ignition", "&Cranking", "&Idle", "&Advanced", "&Sensors"}


def strings(ini: ts_ini.Ini):
    """Yield (where, text, is_tuner) for every user-visible string."""
    menu_of: dict[str, str] = {}
    for m in ini.menus():
        menu_of.setdefault(m["target"], m["menu"])
        yield (f"menu {m['menu']}", m["label"], m["menu"] in TUNER_MENUS)
    dialogs = ini.dialogs()
    # propagate menu membership through panels
    parent: dict[str, str] = {}
    for name, d in dialogs.items():
        for ch in d["children"]:
            if ch["key"] == "panel" and ch["args"]:
                parent.setdefault(ch["args"][0], name)

    def top(name, depth=0):
        if name in menu_of:
            return menu_of[name]
        if name in parent and depth < 10:
            return top(parent[name], depth + 1)
        return None

    for name, d in dialogs.items():
        mt = top(name)
        tuner = mt in TUNER_MENUS
        if d["title"]:
            yield (f"dialog {name}", d["title"], tuner)
        for ch in d["children"]:
            k, a = ch["key"], ch["args"]
            if k in ("field", "commandButton", "displayOnlyField") and a:
                yield (f"{k} in {name}", ts_ini.unq(a[0]), tuner)
            elif k in ("indicator",) and len(a) > 2:
                yield (f"indicator in {name}", ts_ini.unq(a[1]) + " / " + ts_ini.unq(a[2]), tuner)
    for t in ini.tables().values():
        mt = top(t["name"]) or top(t["name"] + "Edit") or top(t["name"] + "TblEdit")
        yield ("table", t["title"], True)
    for c in ini.curves().values():
        yield ("curve", c["title"], True)
    for g in ini.gauges():
        yield (f"gauge {g['name']}", g["title"], False)
        if g["title"] == g["channel"]:
            yield (f"gauge {g['name']}", "RAW-NAME-AS-TITLE:" + g["title"], False)
    for e in ini.sec("FrontPage"):
        if e.key == "indicator" and len(e.args) > 2:
            yield ("frontpage indicator", ts_ini.unq(e.args[1]) + " / " + ts_ini.unq(e.args[2]), True)
    for e in ini.entries:
        if e.key == "text" and e.args:
            yield ("help text", ts_ini.unq(e.args[0]), False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ini", default=str(HANI_INI))
    ap.add_argument("--md")
    ap.add_argument("--csv")
    ns = ap.parse_args()
    ini = ts_ini.load(ns.ini)
    hits = []
    raw_titles = 0
    for where, text, tuner in strings(ini):
        if text.startswith("RAW-NAME-AS-TITLE:"):
            raw_titles += 1
            continue
        for rx, cat, rep in TERMS:
            for m in re.finditer(rx, text):
                hits.append({"severity": "TUNER" if tuner else "DIAG", "category": cat,
                             "term": m.group(0), "where": where, "text": text[:140],
                             "recommend": rep})
    if ns.csv:
        with open(ns.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(hits[0]))
            w.writeheader(); w.writerows(hits)
    by = Counter((h["severity"], h["category"]) for h in hits)
    terms = defaultdict(Counter)
    for h in hits:
        terms[(h["severity"], h["category"])][h["term"]] += 1
    md = ["| severity | category | hits | most frequent terms | recommendation |",
          "|---|---|---|---|---|"]
    rec = {c: r for _, c, r in TERMS}
    for (sev, cat), n in sorted(by.items(), key=lambda kv: (kv[0][0] != "TUNER", -kv[1])):
        top = ", ".join(f"`{t}`×{c}" for t, c in terms[(sev, cat)].most_common(6))
        md.append(f"| {sev} | {cat} | {n} | {top} | {rec[cat]} |")
    md.append("")
    md.append(f"Gauges whose TITLE is the raw channel name: **{raw_titles}** "
              f"of {len(ini.gauges())} (e.g. `warmupPct`, `airMgX10`, `lambda1X1000`).")
    md.append("")
    md.append("Examples in TUNER workflows:")
    md.append("")
    seen = set()
    for h in hits:
        if h["severity"] == "TUNER" and (h["category"], h["term"]) not in seen:
            seen.add((h["category"], h["term"]))
            md.append(f"* `{h['term']}` in {h['where']}: \"{h['text']}\"")
            if len(seen) > 40:
                break
    text = "\n".join(md) + "\n"
    if ns.md:
        Path(ns.md).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
