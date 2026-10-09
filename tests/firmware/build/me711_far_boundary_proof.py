#!/usr/bin/env python3
r"""
me711_far_boundary_proof.py - no call crosses the NCODE/FCODE boundary the
wrong way, in the LINKED image.

    py tests\firmware\build\me711_far_boundary_proof.py

WHY. V81 moved the cold setup modules into FCODE (segment 0x85) through the
thunks in hcfar_me711.c (see hcfarbridge.h). On the C167 a near call (CALLA,
CALLR) or near jump (JMPA, JMPR) stays in the CURRENT code segment, and a
near function returns with RET. So the rules are:

  1. every CALLA/JMPA/CALLR in an FCODE section targets its OWN section
     (a near call out of segment 0x85 lands at the same offset in 0x85 -
     somewhere else entirely - and nothing but this check notices);
  2. every CALLS/JMPS in the image targets the entry of a FAR function -
     one whose body is terminated by RETS, never RET;
  3. no FCODE section calls ?C_LIB_CODE (Keil's long helpers are near).

L166 checks near/far only through declarations (L20). This reads the
instructions the CPU will execute.

NEGATIVE CONTROL: a copy of the image with one thunk CALLS rewritten as a
CALLA must fail rule 1, and a CALLS aimed at a near function must fail
rule 2. A proof that cannot fail proves nothing.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_image as IMG                                    # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
BIN = ROOT / "bins/hanicore" / (IMG.STEM + ".bin")
MAP = BIN.with_suffix(".M66")
RAM_FAR = {0x386000}          # hc_nvm_payload / ramtest, copied to SRAM, far


def sections(mp):
    out = []
    for m in re.finditer(r"^([0-9A-F]{6})H\s+([0-9A-F]{6})H\s+[0-9A-F]{6}H\s+"
                         r"CODE\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+(\w+)\s+(\S+)",
                         mp, re.M):
        out.append((int(m.group(1), 16), int(m.group(2), 16), m.group(3),
                    m.group(4)))
    return sorted(out)


def length(op):
    return 4 if (op & 0x0F) in (2, 3, 4, 5, 6, 7, 0xA) else 2


def walk(img, a0, a1):
    fo, end = a0 - 0x800000, a1 - 0x800000
    while fo <= end:
        op = img[fo]
        yield 0x800000 + fo, op, img[fo:fo + 4]
        fo += length(op)


def first_return(img, entry, a1):
    for pc, op, b in walk(img, entry, a1):
        if op == 0xCB:                    # RET
            return "RET", pc
        if op == 0xDB:                    # RETS
            return "RETS", pc
        if op == 0xFB:                    # RETI
            return "RETI", pc
        if op == 0xEB:                    # RETP
            return "RETP", pc
    return None, None


def check(img, secs):
    fails = []
    by_addr = lambda a: next((s for s in secs if s[0] <= a <= s[1]), None)  # noqa
    ncalls = 0
    for a0, a1, cls, name in secs:
        for pc, op, b in walk(img, a0, a1):
            tgt, kind = None, None
            if op in (0xCA, 0xEA):
                tgt = (pc & 0xFF0000) | b[2] | b[3] << 8
                kind = "CALLA" if op == 0xCA else "JMPA"
            elif op == 0xBB:
                r = b[1] - 256 if b[1] > 127 else b[1]
                tgt, kind = pc + 2 + 2 * r, "CALLR"
            elif op == 0xDA:
                tgt, kind = (b[1] << 16) | b[2] | b[3] << 8, "CALLS"
            if kind is None:
                continue
            if kind in ("CALLA", "JMPA", "CALLR") and cls == "FCODE":
                if not (a0 <= tgt <= a1):
                    fails.append("rule 1: %s at 0x%06X in %s -> 0x%06X"
                                 % (kind, pc, name, tgt))
            if kind == "CALLS":
                ncalls += 1
                if tgt in RAM_FAR:
                    continue
                s = by_addr(tgt)
                if s is None:
                    fails.append("rule 2: CALLS at 0x%06X -> 0x%06X is in no "
                                 "code section" % (pc, tgt))
                    continue
                if s[3] == "?C_LIB_CODE":
                    fails.append("rule 3: CALLS at 0x%06X into ?C_LIB_CODE"
                                 % pc)
                    continue
                ret, rpc = first_return(img, tgt, s[1])
                if ret != "RETS":
                    fails.append("rule 2: CALLS at 0x%06X (%s) -> 0x%06X in %s "
                                 "returns with %s at 0x%06X" % (
                                     pc, name, tgt, s[3], ret, rpc or 0))
    return fails, ncalls


def main() -> int:
    img = bytearray(BIN.read_bytes())
    secs = sections(MAP.read_text(errors="replace"))
    fsecs = [s for s in secs if s[2] == "FCODE"]
    print("image %s\nFCODE sections: %s" % (BIN.name, ", ".join(
        "%s %d B" % (s[3], s[1] - s[0] + 1) for s in fsecs)))
    ok = True

    fails, n = check(img, secs)
    print("shipped image: %d CALLS checked, %d violations" % (n, len(fails)))
    for f in fails[:20]:
        print("   ", f)
    ok &= not fails

    # ---- negative controls on a COPY ---------------------------------------
    thunks = next(s for s in secs if s[3] == "?PR?HCFAR_ME711")
    victim = None
    for a0, a1, cls, name in fsecs:
        for pc, op, b in walk(img, a0, a1):
            t = (b[1] << 16) | b[2] | b[3] << 8
            if op == 0xDA and thunks[0] <= t <= thunks[1]:
                victim = pc
                break
        if victim:
            break
    m1 = bytearray(img)
    fo = victim - 0x800000
    m1[fo], m1[fo + 1] = 0xCA, 0x00               # CALLS seg,x -> CALLA cc_UC,x
    f1, _ = check(m1, secs)
    r1 = any(x.startswith("rule 1") for x in f1)
    print("control 1 (a thunk CALLS at 0x%06X made near): %s"
          % (victim, "FAILS as it must" if r1 else "PASSED - the proof is blind"))
    ok &= r1

    nsec = next(s for s in secs if s[3] == "?PR?HCCONFIG")
    m2 = bytearray(img)
    m2[fo:fo + 4] = bytes([0xDA, nsec[0] >> 16, nsec[0] & 0xFF,
                           (nsec[0] >> 8) & 0xFF])
    f2, _ = check(m2, secs)
    r2 = any(x.startswith("rule 2") for x in f2)
    print("control 2 (CALLS aimed at near HCCONFIG code): %s"
          % ("FAILS as it must" if r2 else "PASSED - the proof is blind"))
    ok &= r2

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
