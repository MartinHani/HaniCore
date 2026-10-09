#!/usr/bin/env python3
r"""me711_keil_shift_scan.py - no module may contain a register shifted by
itself.

    py tests\firmware\build\me711_keil_shift_scan.py

WHY (V97). Keil C166 V7.53 compiled, in hcsched_dry.c inj_start(),

    sm = (s == 0) ? 0 : (unsigned int)(1u << ((s - 1u) & 15u));

as  SUB R5,#1 / AND R5,#15 / MOV R4,#1 / MOV R5,R4 / SHL R5,R5  - the shift
count overwritten by the constant before the shift - so the result was
always 2 and every cylinder of a sequential engine switched mode on the
first cylinder's twin (me711_sequential_proof S2 caught it on the linked
image). `SHL Rn,Rn` shifts a value by its own low bits, which C never asks
for in this firmware, so any occurrence is this defect until proven
otherwise.

This compiles every module exactly as build_me711.bat does, with CODE, and
fails on any SHL/SHR/ASHR/ROL/ROR whose two operands are the same register.
Source-echo lines in the listing are ignored (only code lines are read).
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

D = Path(__file__).resolve().parents[3] / "firmware/targets/me711"
KEIL = Path(r"C:\Keil\C166\BIN\C166.EXE")


def main() -> int:
    if not KEIL.exists():
        print("SKIP: Keil C166 not found")
        return 0
    bat = (D / "build_me711.bat").read_text(encoding="utf-8")
    tmp = tempfile.mkdtemp()
    # Expand the script's own `set NAME=value` lines, so this scan compiles
    # each unit with exactly the include path the build uses.
    env = {}
    for line in bat.splitlines():
        m = re.match(r"\s*set\s+(\w+)=(.*)$", line)
        if m:
            env[m.group(1)] = re.sub(r"%(\w+)%", lambda v: env.get(v.group(1), v.group(0)), m.group(2).strip())
    hits, n = [], 0
    for line in bat.splitlines():
        if "C166.EXE" not in line:
            continue
        args = line.split('C166.EXE"', 1)[1].strip()
        args = re.sub(r"%(\w+)%", lambda v: env.get(v.group(1), v.group(0)), args)
        obj = os.path.join(tmp, "x.obj")
        args = re.sub(r"OBJECT\([^)]*\)", lambda m: "OBJECT(%s)" % obj, args)
        m = re.search(r"PRINT\(build.([^)]*)\)", args)
        lst = os.path.join(tmp, m.group(1) if m else "x.lst")
        args = re.sub(r"PRINT\([^)]*\)", lambda mm: "PRINT(%s)" % lst, args)
        subprocess.run('"%s" %s CODE' % (KEIL, args), shell=True, cwd=str(D),
                       capture_output=True)
        n += 1
        if not os.path.exists(lst):
            hits.append((line.strip()[:60], "NO LISTING"))
            continue
        for ln in open(lst, errors="replace"):
            if not re.match(r"\s*[0-9A-F]{4} [0-9A-F]+\s", ln):
                continue                       # code lines only
            mm = re.search(r"\b(SHL|SHR|ASHR|ROL|ROR)\s+(R\d+),(R\d+)", ln)
            if mm and mm.group(2) == mm.group(3):
                hits.append((os.path.basename(lst), ln.strip()))
    print("%d modules compiled with code listings" % n)
    for h in hits:
        print("  FAIL", h)
    print("RESULT: %s (%d self-shift(s))" % ("PASS" if not hits else "FAIL",
                                            len(hits)))
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
