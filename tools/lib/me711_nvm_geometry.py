#!/usr/bin/env python3
r"""
me711_nvm_geometry.py - ONE place that knows the shape of the calibration store.

WHY THIS EXISTS, and it is the rule this repository already learned four times.

tests/firmware/persistence/me711_nvm_proof.py opened with

    CELL0, PAGE, CELLS, OFF, BODY, ... = 0x40000, 0x2000, 16, 2, 0x1ffc, ...

and a private addr() that knew there were two sectors eight cells apart. None
of that came from the firmware; it was a hand-kept copy of hctarget.h. When V53
moved the store to SA9..SA18 and gave it eighty cells, the gate went on
checking the OLD geometry against the NEW image and reported 39 failures that
were all its own - and had the change been subtler it would instead have gone
on PASSING while testing addresses the firmware no longer uses.

That is "two artefacts that must agree, and nothing that makes them", which
the project rules record as having cost four incidents. So the geometry is PARSED out
of hctarget.h, which is where the firmware reads it from, and every gate that
needs it imports this.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HDR = ROOT / "firmware/targets/me711/hctarget.h"


def _defs(text: str) -> dict:
    out = {}
    for m in re.finditer(r"^#define\s+(TGT_\w+)\s+(0x[0-9A-Fa-f]+|\d+)[uU]?[lL]?",
                         text, re.M):
        out[m.group(1)] = int(m.group(2), 0)
    return out


class Geometry:
    def __init__(self, header: Path | None = None):
        text = (header or HDR).read_text(encoding="utf-8", errors="surrogateescape")
        d = _defs(text)
        self.base = d["TGT_FLASH_CFG_A"]                 # CPU address
        self.sectors = d["TGT_FLASH_SECTORS"]
        self.cell_pages = d["TGT_FLASH_CELL_PAGES"]
        self.off = d["TGT_FLASH_CELL_OFF"]
        self.body = d["TGT_FLASH_CELL_BODY"]
        self.sector_size = d["TGT_FLASH_SECTOR_SIZE"]
        self.page = d["TGT_FLASH_PAGE"]
        self.code_base = d["TGT_CODE_BASE"]
        self.code_size = d["TGT_CODE_SIZE"]
        self.cells = self.sectors * self.cell_pages
        self.file_base = self.base - 0x800000

    # -- addressing, mirroring CELL_ADDR/CELL_SEG in hcnvm.c ----------------
    def sector_of(self, cell: int) -> int:
        return cell // self.cell_pages

    def sector_file_base(self, sector: int) -> int:
        return self.file_base + sector * self.sector_size

    def addr(self, cell: int) -> int:
        """File offset of cell `cell`'s BODY."""
        return (self.sector_file_base(self.sector_of(cell))
                + (cell % self.cell_pages) * self.page + self.off)

    def page_base(self, cell: int) -> int:
        """File offset of the 8 KiB page the cell lives in."""
        return self.addr(cell) - self.off

    def cells_of_sector(self, sector: int) -> range:
        lo = sector * self.cell_pages
        return range(lo, lo + self.cell_pages)

    def __repr__(self) -> str:
        return (f"<store 0x{self.base:06X}+{self.sectors} sectors, "
                f"{self.cells} cells, body {self.body} B>")


GEO = Geometry()

if __name__ == "__main__":
    g = GEO
    print(g)
    print(f"  code region      0x{g.code_base:06X}-0x{g.code_base + g.code_size - 1:06X}")
    print(f"  store file range 0x{g.file_base:06X}-"
          f"0x{g.file_base + g.sectors * g.sector_size - 1:06X}")
    for c in (0, 1, 7, 8, 9, g.cells - 1):
        print(f"  cell {c:3d}  sector {g.sector_of(c)}  body file 0x{g.addr(c):06X}"
              f"  page 0x{g.page_base(c):06X}")
