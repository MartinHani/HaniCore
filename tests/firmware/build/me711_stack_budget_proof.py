#!/usr/bin/env python3
r"""me711_stack_budget_proof.py - the STATIC worst-case stack bound fits, with margin.

    py tests\firmware\build\me711_stack_budget_proof.py [--control]

The 2026-10-06 runtime audit overflowed the
256-byte user stack into interrupt return frames under engine + TunerStudio
load: a measured high-water mark only covers the paths a workload happened to
take. This gate bounds EVERY path: tools/analysis/me711_stack_static.py walks
the linked image (frames, call graph, one handler per interrupt level nested
on top of the deepest main-loop chain) and this gate requires

  S1  user stack   worst case <= 85 % of ?C_USERSTACK (map)
  S2  system stack worst case <= 85 % of STKUN - STKOV (start_me711.a66)
  S3  no recursion and no indirect call on any counted path (the bound would
      not hold)
  S4  the user-stack guard band (hcsafety.h HC_STK_GUARD_LO..HI) is below the
      stack and no map section overlaps it
  S5  every enabled interrupt level is counted (the level table comes from
      hctarget.h, the same defines the firmware programs)

85 % leaves 15 % for what a linear sweep cannot see (a compiler-generated
frame the sweep misreads). The margin policy is in
the maintainer's design notes.

--control: the same image against the pre-2026-10-06 stacks (256-byte user
stack, system stack 0xF606..0xF700) must FAIL S1/S2 - the gate can fail.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402

import me711_image as PI          # noqa: E402
import me711_stack_static as SS   # noqa: E402

LIMIT = 0.85
SAFETY_H = hcpaths.ROOT / "firmware/targets/me711/system/hcsafety.h"


def checks(sizes=None):
    out = SS.analyse(sizes=sizes)
    res = []
    u, us = out["user_worst"], out["user_size"]
    s, ss = out["sys_worst"], out["sys_size"]
    res.append(("S1 user stack worst %d of %d B (%.0f %%, limit %.0f %%)" % (u, us, 100.0 * u / us, 100 * LIMIT),
                u <= LIMIT * us))
    res.append(("S2 system stack worst %d of %d B (%.0f %%, limit %.0f %%)" % (s, ss, 100.0 * s / ss, 100 * LIMIT),
                s <= LIMIT * ss))
    res.append(("S3 no recursion / indirect call: %s" % (out["problems"] or "none"), not out["problems"]))
    h = SAFETY_H.read_text(errors="replace")
    glo = int(re.search(r"#define\s+HC_STK_GUARD_LO\s+(0x[0-9A-Fa-f]+)", h).group(1), 16)
    ghi = int(re.search(r"#define\s+HC_STK_GUARD_HI\s+(0x[0-9A-Fa-f]+)", h).group(1), 16)
    mp = PI.MAP.read_text(errors="replace")
    bot = int(re.search(r"^\s*([0-9A-F]{6})H\s+\?C_USRSTKBOT", mp, re.M).group(1), 16)
    hits = [m.group(0).strip() for m in re.finditer(
        r"^([0-9A-F]{6})H\s+([0-9A-F]{6})H\s+[0-9A-F]{6}H\s+DATA.*$", mp, re.M)
        if int(m.group(1), 16) < ghi and int(m.group(2), 16) >= glo]
    res.append(("S4 guard 0x%04X..0x%04X directly below the user stack (0x%04X), %d map section(s) inside"
                % (glo, ghi - 1, bot, len(hits)), ghi == bot and not hits))
    lv = SS.handler_levels()
    want = {v for k, v in lv.items() if k != 0x02}
    got = {int(k) for k in out["levels"]} - {16}
    res.append(("S5 levels counted %s, enabled %s" % (sorted(got), sorted(want)), want <= got))
    return res, out


def main():
    control = "--control" in sys.argv
    if control:
        res, out = checks(sizes=(256, 0xF700 - 0xF606))
        bad = [n for n, ok in res[:2] if not ok]
        for n, ok in res[:2]:
            print("  [%s] %s" % ("PASS" if ok else "FAIL", n))
        if len(bad) == 2:
            print("CONTROL OK: the pre-2026-10-06 stacks fail S1 and S2")
            return 0
        print("CONTROL BROKEN: the old stacks pass - the gate cannot fail")
        return 1
    res, out = checks()
    print("main chain: " + " -> ".join(out["main_chain"][:8]))
    for L, v in out["levels"].items():
        print("  ILVL %-2s user %3d B, system %3d B  %s" % (L, v["user"], v["sys"], v["handler"]))
    nf = 0
    for n, ok in res:
        print("  [%s] %s" % ("PASS" if ok else "FAIL", n))
        nf += not ok
    print("%d/%d checks pass" % (len(res) - nf, len(res)))
    return 1 if nf else 0


if __name__ == "__main__":
    sys.exit(main())
