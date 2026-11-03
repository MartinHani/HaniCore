#!/usr/bin/env python3
r"""
build_loader.py - assemble and link the update loader (firmware/loader/
hcloader.a66) for one board; write its SA5 image.

    py tools\build\build_loader.py [--board porsche_me711|vag_me71_c4|audi_4f_v8|vag_me75_dc|vag_me75_bfb]

Output: bins/hanicore/HaniCore_loader_<board>.bin - 64 KiB, file offset 0 =
CPU 0x820000 (SA5): the 128-slot forwarding table (JMPS 83:N*4, the app's
vector table at the start of SA6) and the loader from 0x820200 - plus .M66 /
.json (entry, size, sha256). The board defaults to HANICORE_BOARD, as every
tool does. .scratch/firmware-update/spec.md.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: E402  (HANICORE_KEIL_C166, like every other tool)
KEIL = hcpaths.KEIL / "BIN"
SRC = ROOT / "firmware/loader/hcloader.a66"
BLD = ROOT / "firmware/loader/build"
SA5 = 0x820000
LOADER_AT = 0x820200
APP_VEC_SEG = 0x83
SETS = {"porsche_me711": "", "audi_4f_v8": ",BOARD_4F",
        "vag_me71_c4": ",BOARD_C4", "vag_me75_dc": ",BOARD_C4,BOARD_DC",
        "vag_me75_bfb": ",BOARD_C4,BOARD_DC,BOARD_BFB"}


def run(cmd, cwd):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    out = (p.stdout or "") + (p.stderr or "")
    return p.returncode, out


def parse_hex(path: Path) -> dict:
    data, ext = {}, 0
    for ln in path.read_text().splitlines():
        if not ln.startswith(":"):
            continue
        b = bytes.fromhex(ln[1:])
        n, addr, typ = b[0], (b[1] << 8) | b[2], b[3]
        if typ == 0:
            for i in range(n):
                data[ext + addr + i] = b[4 + i]
        elif typ == 2:
            ext = ((b[4] << 8) | b[5]) << 4
        elif typ == 4:
            ext = ((b[4] << 8) | b[5]) << 16
        elif typ == 1:
            break
    return data


def build(board: str) -> Path:
    BLD.mkdir(parents=True, exist_ok=True)
    obj, abs_, hexf = (BLD / f"hcloader_{board}.obj", BLD / f"hcloader_{board}.abs",
                       BLD / f"hcloader_{board}.hex")
    rc, out = run([str(KEIL / "A166.EXE"), str(SRC), f"SET(SMALL{SETS[board]})",
                   f"OBJECT({obj})", f"PRINT({BLD / f'hcloader_{board}.lst'})"], BLD)
    if rc > 1 or "ERROR" in out.upper().replace("0 ERROR", ""):
        raise SystemExit("A166 failed:\n" + out)
    rc, out = run([str(KEIL / "L166.EXE"), str(obj), "TO", str(abs_),
                   f"CLASSES(LCODE(0x{LOADER_AT:06X}-0x82FFFF))", "NOVECTAB",
                   f"PRINT({BLD / f'hcloader_{board}.M66'})"], BLD)
    if rc > 1:
        raise SystemExit("L166 failed:\n" + out)
    rc, out = run([str(KEIL / "OH166.EXE"), str(abs_), "H167",
                   f"RANGE(0x{LOADER_AT:06X}-0x82FFFF)"], BLD)
    hexf = abs_.with_suffix(".H86")
    if rc > 1:
        raise SystemExit("OH166 failed:\n" + out)
    # OH166 RANGE output is relative to the range start (the main build's
    # HEX_BASE does the same)
    data = {LOADER_AT + a: v for a, v in parse_hex(hexf).items()}
    img = bytearray(b"\xFF" * 0x10000)
    for slot in range(128):                       # forward to the app's table
        img[slot * 4:slot * 4 + 4] = bytes((0xFA, APP_VEC_SEG, (slot * 4) & 0xFF,
                                            (slot * 4) >> 8))
    for a, v in data.items():
        if not (LOADER_AT <= a <= 0x82FFFF):
            raise SystemExit(f"loader byte at 0x{a:06X} outside 0x{LOADER_AT:06X}-0x82FFFF")
        img[a - SA5] = v
    mtxt = (BLD / f"hcloader_{board}.M66").read_text(errors="replace")
    m = re.search(r"([0-9A-F]{6})H\s+HCL_ENTRY", mtxt)
    entry = int(m.group(1), 16) if m else LOADER_AT
    out_bin = ROOT / "bins/hanicore" / f"HaniCore_loader_{board}.bin"
    out_bin.parent.mkdir(parents=True, exist_ok=True)   # a fresh clone has no bins/
    out_bin.write_bytes(bytes(img))
    (out_bin.with_suffix(".M66")).write_text(mtxt)
    meta = {"board": board, "entry": entry, "base": SA5,
            "loader_bytes": len(data), "sha256": hashlib.sha256(img).hexdigest().upper(),
            "source_sha256": hashlib.sha256(SRC.read_bytes()).hexdigest().upper()}
    out_bin.with_suffix(".json").write_text(json.dumps(meta, indent=1))
    print(f"loader {board}: {len(data)} bytes at 0x{LOADER_AT:06X}, entry 0x{entry:06X}"
          f" -> {out_bin.name}")
    return out_bin


if __name__ == "__main__":
    b = os.environ.get("HANICORE_BOARD", "porsche_me711")
    if "--board" in sys.argv:
        b = sys.argv[sys.argv.index("--board") + 1]
    if b not in SETS:
        raise SystemExit(f"--board {b!r}: one of {', '.join(SETS)}")
    build(b)
