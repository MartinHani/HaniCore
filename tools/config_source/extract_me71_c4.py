#!/usr/bin/env python3
r"""
extract_me71_c4.py - the Audi 2.7T ME7.1 "C4" board's connector and port map,
out of Bosch's own workbooks, into the two CSVs hw_descriptors.py reads.

    py tools\config_source\extract_me71_c4.py

SOURCES (local, reference/ is not published - the CSVs are the committed copy):

  the ME7.1.1 schematic set sheet SSB - despite its folder, a
      VW-group ME7 VARIANT MATRIX: one row per 121-pin connector function, one
      column per board variant. Column 140 is "ME7.1 V6 2,7l 5V T", C4-Muster,
      Stueckliste 345;02 ("wie 345;01 DSBKV, FA-Step, SMD082, CF160") - the
      2.7T board. Its BOM is the ME7.1.1 schematic set sheet
      "345;02 V6T". An "x" is fitted, "o" optional, "-" not fitted.
  the ME7.1.1 schematic set sheets FR (main CPU) column 13
      "Belegung ME7.1" (H. Jordan, 13.10.97) and ASIC column 17 "Belegung
      ME7.1 C4 (VW)" (Jordan, 08.09.97).

Class: SAME-GENERATION BOSCH SCHEMATIC data, variant-exact by BOM number.
Not a measurement of any one ECU.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SSB = ROOT / "reference/schematics/ME75/Vari_ME75X.xls"
PORT = ROOT / "reference/schematics/ME71/me7_port.xls"
OUT_CONN = ROOT / "tools/config_source/data/me71_c4_connector.csv"
OUT_PORT = ROOT / "tools/config_source/data/me71_c4_iomap.csv"

SSB_COL = 140              # "ME7.1 V6 2,7l 5V T", 345;02
SSB_HEADER_ROW = 7
PORT_FR_COL = 13           # "Belegung ME7.1"
PORT_ASIC_COL = 17         # "Belegung ME7.1 C4 (VW)"


def clean(v) -> str:
    return " ".join(str(v).replace("\n", " ").split())


def main() -> int:
    import xlrd
    b = xlrd.open_workbook(str(SSB))
    s = b.sheet_by_name("SSB")
    head = clean(s.cell_value(SSB_HEADER_ROW, SSB_COL))
    bom = clean(s.cell_value(9, SSB_COL))
    if "2,7l" not in head or "345;02" not in bom:
        raise SystemExit("SSB column %d is %r / %r - not the 2.7T 345;02 column"
                         % (SSB_COL, head, bom))
    rows = []
    for r in range(48, s.nrows):
        fit = clean(s.cell_value(r, SSB_COL)).lower()
        cav = clean(s.cell_value(r, 1)).replace(".0", "")
        if fit not in ("x", "o") or not cav or cav.startswith("int"):
            continue
        for c in cav.replace(",", " ").split():
            if c.isdigit():
                rows.append({"cavity": int(c), "fitted": fit,
                             "rb_name": clean(s.cell_value(r, 4)),
                             "vw_name": clean(s.cell_value(r, 5)),
                             "function": clean(s.cell_value(r, 0)),
                             "ssb_row": r})
    rows.sort(key=lambda x: (x["cavity"], x["ssb_row"]))
    OUT_CONN.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CONN.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, ["cavity", "fitted", "rb_name", "vw_name",
                                "function", "ssb_row"])
        w.writeheader()
        w.writerows(rows)
    print("wrote %s (%d rows, column %d %r)" % (OUT_CONN, len(rows), SSB_COL, head))

    p = xlrd.open_workbook(str(PORT))
    out = []
    for sheet, col, proc in (("FR", PORT_FR_COL, "MAIN CPU"),
                             ("ASIC", PORT_ASIC_COL, "ASIC")):
        sh = p.sheet_by_name(sheet)
        title = clean(sh.cell_value(6, col))
        if "ME7.1" not in title or "7.1.1" in title:
            raise SystemExit("%s column %d is %r" % (sheet, col, title))
        for r in range(7, sh.nrows):
            pin = clean(sh.cell_value(r, 4)).replace(".0", "")
            sig = clean(sh.cell_value(r, col))
            if not pin.isdigit() or not sig:
                continue
            out.append({"processor": proc, "cpu_pin": int(pin),
                        "peripheral_fn": clean(sh.cell_value(r, 0)),
                        "module": clean(sh.cell_value(r, 3)),
                        "me71_signal": sig, "column": title})
    with OUT_PORT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, ["processor", "cpu_pin", "peripheral_fn",
                                "module", "me71_signal", "column"])
        w.writeheader()
        w.writerows(out)
    print("wrote %s (%d rows)" % (OUT_PORT, len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
