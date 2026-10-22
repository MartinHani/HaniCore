#!/usr/bin/env python3
r"""me711_resource_budget_proof.py - every memory class keeps its growth reserve.

    py tests\firmware\build\me711_resource_budget_proof.py [--control]

The linker is happy with one byte left; a project that adds features is not.
This gate reads the class ranges from linker_me711.lnp and the located
sections from the LINKED map, and requires each class to keep a reserve
(the maintainer's design notes, "Resource margins"):

  NCODE   >= 3072 B   near code, one 64 KB CGROUP (also the build's own floor)
  FCODE   >= 2048 B   far code, SA6 + SA8 + SA9
  NCONST  >= 1024 B   near constants
  HCONST  >= 1024 B   huge constants (the preset tables)

RAM has its own gates: near RAM and XRAM in near_ram_hazard_proof (>= 192 B,
>= 64 B), both stacks in me711_stack_budget_proof (static bound <= 85 %),
measured stacks and timing in me711_runtime_stress_proof.

--control: the same image with one 4 KB feature charged to every class must
FAIL - a gate that cannot fail proves nothing.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402

import me711_image as PI   # noqa: E402

LNP = hcpaths.ROOT / "firmware/targets/me711/linker_me711.lnp"
FLOORS = {"NCODE": 3072, "FCODE": 2048, "NCONST": 1024, "HCONST": 1024}


def class_ranges():
    t = LNP.read_text(errors="replace")
    out = {}
    for name in FLOORS:
        m = re.search(r"^\s*%s\s*\(([^)]*)\)" % name, t, re.M)
        rs = []
        for part in (m.group(1).split(",") if m else []):
            r = re.match(r"\s*0x([0-9A-Fa-f]+)\s*-\s*0x([0-9A-Fa-f]+)\s*$", part)
            if r:
                rs.append((int(r.group(1), 16), int(r.group(2), 16)))
        out[name] = rs
    return out


def used_by_class():
    mp = PI.MAP.read_text(errors="replace")
    used = {k: 0 for k in FLOORS}
    for m in re.finditer(r"^([0-9A-F]{6})H\s+([0-9A-F]{6})H\s+([0-9A-F]{6})H\s+\w+\s.*?\s(\w+)\s+(\S+)\s*$",
                         mp, re.M):
        cls = m.group(4)
        if cls in used:
            used[cls] += int(m.group(3), 16)
    return used


def main() -> int:
    control = "--control" in sys.argv
    rs, used = class_ranges(), used_by_class()
    fails = 0
    ranges=[(lo,hi,cls) for cls,parts in rs.items() for lo,hi in parts]
    disjoint=all(hi<lo2 or hi2<lo for i,(lo,hi,cls) in enumerate(ranges)
                 for lo2,hi2,cls2 in ranges[i+1:])
    import me711_nvm_geometry as G   # the store base, from hctarget.h
    store=G.Geometry().base
    resident=all(0x830000<=lo<=hi<store for lo,hi,cls in ranges)
    ok=disjoint and resident
    fails+=not ok
    print("  [%s] code/constant reservations are disjoint and precede the store"%('PASS' if ok else 'FAIL'))
    for cls, floor in FLOORS.items():
        size = sum(hi - lo + 1 for lo, hi in rs[cls])
        free = size - used[cls] - (4096 if control else 0)
        ok = bool(rs[cls]) and free >= floor
        fails += not ok
        print("  [%s] %-7s %6d of %6d B used, %6d free (reserve %d)"
              % ("PASS" if ok else "FAIL", cls, used[cls], size, free, floor))
    if control:
        if fails:
            print("CONTROL OK: a 4 KB feature breaks %d reserve(s)" % fails)
            return 0
        print("CONTROL BROKEN: the reserves cannot fail")
        return 1
    print("%d/%d reserves hold" % (len(FLOORS)+1 - fails, len(FLOORS)+1))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
