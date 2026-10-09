#!/usr/bin/env python3
r"""
extract_me71_connector.py - derive the ME7.1 121-pin connector map from Bosch's
OWN documents, into a machine-readable CSV.

    py tools\config_source\extract_me71_connector.py

Sources, both shipped in this repo and both Bosch's:

  the ME7.1.1 schematic set ME7.1.XLS
      "Steckerbelegung ME7.1 und mit 121 pol. SKE-Stecker / Maximalumfang",
      K3/EEV2-Ss, last revision 27.01.97. The sheet is a PICTURE of the
      connector: each cell holds one or more signal short-names on their own
      lines and the pin NUMBER on the last line. That is why this file parses
      cells rather than columns.

  the ME7.1.1 schematic set
      "Ein- und Ausgaenge des C167CR" - Bosch's own expansion of every short
      name used above. Nothing in this file invents a meaning.

WHY THIS EXISTS. The first Project 2A pin table was hand-typed, applied ONE
121-pin capability list to BOTH the ME7.5 and the ME7.1.1 target, and asserted
electrical roles for pins that Bosch's own sheet assigns to something else -
connector pin 21 is ZAS2_S, "Zylinderabschaltung 2", not a main relay. A pin
table that a human types is a pin table that drifts; this one is extracted, and
the test that consumes it fails if the spreadsheet and the CSV disagree.

EVIDENCE. This workbook is a **VW/Audi ME7.1 maximum-scope** connector, not a
target harness drawing, and the maintainer's design records already says
so about connector pin 43. Every row it produces is therefore PROBABLE for the
OEM ME7.1.1 unless some other source in this repo raises it. Raising a row is a
deliberate act and lives in hw_descriptors.py, not here.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

try:
    import xlrd
except ImportError:  # pragma: no cover - environment guard
    raise SystemExit("needs xlrd (<= 2.x reads .xls):  py -m pip install xlrd")

ROOT = Path(__file__).resolve().parents[2]
CONNECTOR = ROOT / "reference/schematics/ME71/Steckerb. ME7.1.XLS"
ABBREV = ROOT / "reference/schematics/ME71/pin_kuerzel_tC_ME7.xls"
OUT = ROOT / "tools/config_source/data/me71_connector_121.csv"

# Rows of the sheet that carry connector cells. Everything else is the title
# block or the revision history, and is skipped by the "last line is a number"
# rule anyway; the range only keeps the parse honest about what it read.
MAX_PIN = 121


def _cells(sheet):
    for r in range(sheet.nrows):
        for c in range(sheet.ncols):
            v = sheet.cell_value(r, c)
            if isinstance(v, float) and v == int(v):
                v = int(v)
            s = str(v).strip()
            if s:
                yield r, c, s


def read_abbreviations() -> dict[str, str]:
    """Bosch's own short-name -> meaning table."""
    book = xlrd.open_workbook(str(ABBREV))
    sheet = book.sheet_by_index(0)
    out: dict[str, str] = {}
    for r in range(sheet.nrows):
        key = str(sheet.cell_value(r, 0)).strip()
        val = str(sheet.cell_value(r, 1)).strip().replace("\n", " ")
        if not key or not val:
            continue
        if key.lower().startswith(("ein-und", "eing", "ausg")):
            continue
        # "ETH / ETR" and "SU/SRU" name two signals on one row.
        for part in re.split(r"\s*/\s*", key):
            part = part.strip()
            if part:
                out.setdefault(part, val)
    return out


def read_connector() -> dict[int, list[str]]:
    """pin number -> the signal short-names Bosch prints on that pin."""
    book = xlrd.open_workbook(str(CONNECTOR))
    sheet = book.sheet_by_index(0)
    pins: dict[int, list[str]] = {}
    for _r, _c, text in _cells(sheet):
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if not lines:
            continue
        if not re.fullmatch(r"\d{1,3}", lines[-1]):
            continue
        pin = int(lines[-1])
        if not 1 <= pin <= MAX_PIN:
            continue
        signals = lines[:-1]
        # A cell that is only a number is a pin Bosch left unassigned.
        pins.setdefault(pin, [])
        for s in signals:
            if s not in pins[pin]:
                pins[pin].append(s)
    return pins


def strip_suffix(sig: str) -> str:
    """'LS2VK_H' -> 'LS2VK'. The trailing _S/_MA/_H/_IP/_IA/_SCH/_SEN/_UV are
    Bosch's wire-role suffixes (Signal, Masse, Heizung, ...), not part of the
    short name the abbreviation sheet lists."""
    return re.sub(r"_(S|MA|H|SCH|SEN|UV|M)$", "", sig)


def main() -> int:
    abbrev = read_abbreviations()
    pins = read_connector()

    missing = [p for p in range(1, MAX_PIN + 1) if p not in pins]
    rows = []
    for pin in range(1, MAX_PIN + 1):
        sigs = pins.get(pin, [])
        meanings = []
        for s in sigs:
            base = strip_suffix(s)
            # Bosch writes the same short name three ways across the two
            # sheets: 'IP1_S' on the connector, 'IP1S' in the abbreviation
            # list. Try the printed name, the wire-role-stripped name, and the
            # underscore-free name - and nothing else, so a miss stays a miss.
            m = (abbrev.get(s)
                 or abbrev.get(base)
                 or abbrev.get(s.replace("_", ""))
                 or abbrev.get(base.replace("_", "")))
            if m is None:
                # numbered variants: LS1VK_IP -> LSUIP1 is not mechanical, so a
                # miss is reported rather than guessed at.
                m = ""
            meanings.append(m)
        rows.append(
            {
                "pin": pin,
                "signals": "|".join(sigs),
                "assigned": "yes" if sigs else "no",
                "bosch_meaning": " | ".join(m for m in meanings if m),
            }
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=["pin", "signals", "assigned", "bosch_meaning"])
        wr.writeheader()
        wr.writerows(rows)

    assigned = sum(1 for r in rows if r["assigned"] == "yes")
    print(f"wrote {OUT}")
    print(f"  pins present in the sheet : {len(pins)}")
    print(f"  pins with a signal name   : {assigned}")
    print(f"  pins the sheet never shows: {len(missing)}  {missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
