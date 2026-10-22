#!/usr/bin/env python3
"""me711_store.py - read the ME7.1.1 calibration store out of a flash dump.

The record selection hcnvm.c cell_scan() makes (magic, layout identity,
version, length, header and payload CRC16, DONE marker; newest generation
wins), for tools and gates that work from a bootmode readback. Moved out of
tools/flash/me711_restore_calibration.py on 2026-10-06 unchanged.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_v101_compat as V102  # noqa: E402

GEN_H = ROOT / "firmware/generated/hc_config_generated.h"
CFG_H = ROOT / "firmware/config/hcconfig.h"
STORE = 0x070000                 # TGT_FLASH_CFG_A 0x870000, file offset
CELLS, CELL, OFF = 72, 0x2000, 2  # TGT_FLASH_CELLS, _PAGE, _CELL_OFF
PAGE = 4096
TAB = [0x0000, 0x1021, 0x2042, 0x3063, 0x4084, 0x50A5, 0x60C6, 0x70E7,
       0x8108, 0x9129, 0xA14A, 0xB16B, 0xC18C, 0xD1AD, 0xE1CE, 0xF1EF]


def crc(b: bytes) -> int:
    """hcnvm.c crc_block(): nibble-table CRC16-CCITT, seed 0xFFFF."""
    c = 0xFFFF
    for x in b:
        for nib in (x >> 4, x & 15):
            c = ((c << 4) & 0xFFFF) ^ TAB[((c >> 12) ^ nib) & 15]
    return c


def hdr(path: Path, name: str, base: int) -> int:
    m = re.search(r"#define\s+%s\s+(0x[0-9A-Fa-f]+|\d+)" % name,
                  path.read_text(errors="replace"))
    if not m:
        raise SystemExit("%s is not in %s" % (name, path.name))
    return int(m.group(1).rstrip("uUlL"), base if m.group(1)[:2] != "0x" else 16)


def newest_record(dump: bytes, layout: int, version: int):
    """The record cell_scan() would select, or a reason there is none."""
    best, seen = None, []
    for cell in range(CELLS):
        a = STORE + cell * CELL + OFF
        r = dump[a:a + 18 + PAGE + 6]
        if all(x == 0xFF for x in r):
            continue
        be = lambda o, n: int.from_bytes(r[o:o + n], "big")   # noqa: E731
        payload=bytes(r[18:18+PAGE])
        identity_ok=(V102.known_identity(be(4,4),payload) if layout==V102.LAYOUT else be(4,4)==layout)
        ok = (r[:4] == b"HCN1" and identity_ok and be(8, 2) == version
              and be(10, 2) == PAGE and be(16, 2) == crc(r[:16])
              and be(18 + PAGE, 2) == crc(r[18:18 + PAGE])
              and r[18 + PAGE + 2:18 + PAGE + 6] == b"DONE")
        seen.append(dict(cell=cell, gen=be(12, 4), layout="%08X" % be(4, 4),
                         valid=ok))
        if ok and (best is None or be(12, 4) > best[1]):
            best = (cell, be(12, 4), bytes(r[18:18 + PAGE]))
    return best, seen
