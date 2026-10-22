#!/usr/bin/env python3
"""me711_code_headroom.py - what is actually left in each CODE class.

NCODE is a single CGROUP and L166 refuses one over 64 KiB, so "free" is
measured against the CLASS RANGE THE LINKER WAS GIVEN and not against any
number written in a comment. That distinction is the whole reason this script
exists: linker_me711.lnp claimed 113664 bytes of NCODE for three releases and
the real ceiling was always 64512 (the maintainer's design notes).

    py tools/analysis/me711_code_headroom.py [map.M66]

Reads the class ranges out of the map's own header line rather than from the
.lnp, so it reports what the LINKER used.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MAP = (ROOT / "firmware/targets/me711"
               / "build/hani_me711.M66")


def parse(map_path: Path):
    text = map_path.read_text(errors="replace")

    # The ">> ..." header the locater echoes back. It is HARD-WRAPPED at about
    # column 118 and the wrap falls mid-token - "(0" / "XF700" - so the lines
    # must be rejoined with no separator before anything is matched. Parsing
    # them line by line silently finds no ranges at all, which is a vacuous
    # PASS rather than an error, so the join is checked below.
    ranges: dict[str, list[tuple[int, int]]] = {}
    echo = "".join(m.group(1) for m in
                   re.finditer(r"^>> ?(.*?)\s*$", text, re.M))
    classes = re.search(r"CLASSES\s*\((.*)\)\s*$", echo)
    if classes:
        for cls, body in re.findall(
                r"([A-Z][A-Z0-9_]*)\s*\(([^)]*)\)", classes.group(1)):
            spans = []
            for lo, hi in re.findall(r"0X([0-9A-F]+)\s*-\s*0X([0-9A-F]+)",
                                     body.upper()):
                spans.append((int(lo, 16), int(hi, 16)))
            if spans:
                ranges.setdefault(cls, []).extend(spans)

    # Located sections: start, end, len, TYPE ... CLASS  NAME
    used: dict[str, list[tuple[int, int, str]]] = {}
    for m in re.finditer(
            r"^([0-9A-F]{6})H\s+([0-9A-F]{6})H\s+([0-9A-F]{6})H\s+"
            r"(CODE|DATA)\s+.*?\s([A-Z][A-Z0-9_]*)\s+(\?\S+)\s*$",
            text, re.M):
        start, end, _ln, _typ, cls, name = m.groups()
        used.setdefault(cls, []).append(
            (int(start, 16), int(end, 16), name))
    return ranges, used


def main() -> int:
    map_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MAP
    if not map_path.exists():
        print(f"no map: {map_path}")
        return 2
    ranges, used = parse(map_path)

    # A map whose header could not be parsed must not report "all clear".
    if "NCODE" not in ranges:
        print("FAIL: no NCODE class range parsed out of the map header")
        return 2
    if "NCODE" not in used:
        print("FAIL: no located NCODE sections found in the map")
        return 2

    print(f"map: {map_path}")
    rc = 0
    for cls in ("ICODE", "NCODE", "FCODE", "NCONST"):
        spans = ranges.get(cls)
        if not spans:
            continue
        cap = sum(hi - lo + 1 for lo, hi in spans)
        secs = sorted(used.get(cls, []))
        occupied = sum(e - s + 1 for s, e, _ in secs)
        top = max((e for _, e, _ in secs), default=None)
        limit = max(hi for _, hi in spans)
        tail = (limit - top) if top is not None else cap
        print(f"\n{cls:7s} "
              f"{'  '.join(f'0x{lo:06X}-0x{hi:06X}' for lo, hi in spans)}")
        print(f"        capacity {cap:6d}   used {occupied:6d}   "
              f"sections {len(secs)}")
        if top is not None:
            print(f"        last section ends 0x{top:06X}  "
                  f"-> {tail} bytes to 0x{limit:06X}")
        if cls in ("NCODE", "FCODE") and top is not None and tail < 0:
            print("        *** OVER THE CLASS LIMIT")
            rc = 1
    # the three largest NCODE sections, because that is the next question
    secs = sorted(used.get("NCODE", []), key=lambda s: s[1] - s[0],
                  reverse=True)[:5]
    if secs:
        print("\nlargest NCODE sections:")
        for s, e, name in secs:
            print(f"   {e - s + 1:6d}  {name}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
