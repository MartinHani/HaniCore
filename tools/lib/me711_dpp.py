#!/usr/bin/env python3
r"""
me711_dpp.py - the DPP page registers, DERIVED from the linked image.

WHY THIS EXISTS.

A rig that executes a Keil SMALL function has to set DPP0..DPP3 before it can
read any `const`, because that is how the compiler addresses them. Five gates
did it like this:

    for i, v in enumerate((0x0000, 0x023B, 0x0003, 0x0003)):
        self.m.sfr[0xFE00 + 2 * i] = v

`0x023B` is a page number - 0x023B * 0x4000 = 0x8EC000 - and it was correct for
exactly as long as NCONST lived in SA17. V53 moved the code sector to SA7+SA8,
so NCONST is at 0x85C000 and the linker now emits `?C_PAGEDPP1 = 0x0217`.

THE FAILURE WAS NOT SUBTLE AND IT DID NOT LOOK LIKE A LAYOUT PROBLEM. Every
const read came back garbage, so the HAL reported `0 available, 16 not`, the
router resolved `pin 255`, the config state machine saw every injector pin as
255, and `me711_umkom_proof` produced 248 TX mismatches. Four gates accusing the
firmware of four different things, all because a page register was a literal.

The values are in the map, which is where the STARTUP gets them from too -
`start_me711.a66` does `MOV DPP0,#?C_PAGEDPP0` and so on, with a comment
saying they "come from the LINKER, not from Bosch: they have to describe where
HaniCore's own data actually is". So a gate should ask the same source.

DPP3 is 3, the SFR page, and that one really is a constant.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_image as PI          # noqa: E402  names the image ONCE


def page_dpps(map_path: Path | None = None) -> tuple:
    """(DPP0, DPP1, DPP2, DPP3) for the image under test."""
    text = (map_path or PI.MAP).read_text(errors="replace")
    out = []
    for n in range(3):
        m = re.search(rf"^\s*([0-9A-F]{{6}})H\s+\?C_PAGEDPP{n}\b", text, re.M)
        if not m:
            raise SystemExit(
                f"?C_PAGEDPP{n} is not in {(map_path or PI.MAP).name} - a rig "
                "cannot set the data page registers without it, and hardcoding "
                "them is what this module exists to stop")
        out.append(int(m.group(1), 16))
    out.append(0x0003)            # DPP3: the SFR page, genuinely fixed
    return tuple(out)


def apply(mem, map_path: Path | None = None) -> tuple:
    """Write them into a c167sim Mem's SFR space and return what was written."""
    dpps = page_dpps(map_path)
    for i, v in enumerate(dpps):
        mem.sfr[0xFE00 + 2 * i] = v
    return dpps


if __name__ == "__main__":
    d = page_dpps()
    print(f"{PI.MAP.name}")
    for i, v in enumerate(d):
        print(f"  DPP{i} = 0x{v:04X}   page base 0x{v * 0x4000:06X}")
