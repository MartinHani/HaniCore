"""c167sim's memory-to-memory MOV forms against their Keil encodings.

Each case is a few bytes as Keil C166 V7.53 emits them (CODE listings), run
by the simulator; the assertion is on memory, not on the simulator's
internals. The forms here are the ones the simulator once got wrong or did
not have - an instrument defect reads exactly like a firmware bug:
  E8 nm   MOV [Rwn],[Rwm+]     (V94: modelled as a non-existent instruction)
  84 0n   MOV [Rwn],mem         94 0n   MOV mem,[Rwn]     (V97: missing)
  A4 0n   MOVB [Rwn],mem        B4 0n   MOVB mem,[Rwn]    (V97: missing)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import c167sim as S  # noqa: E402

SEG, OFF = 0x81, 0x0000                  # flash 0x810000


def cpu_with(code: bytes):
    image = bytearray(b"\xFF" * 0x100000)
    image[0x10000:0x10000 + len(code)] = code
    m = S.Mem(bytes(image))
    c = S.CPU(m, SEG, OFF)
    for i in range(4):                    # DPP0..3 = pages 0..3 (flat)
        m.sfr[0xFE00 + 2 * i] = i
    return m, c


def run(code: bytes, n: int, setup):
    m, c = cpu_with(code)
    setup(m, c)
    for _ in range(n):
        c.step()
    return m, c


def main() -> int:
    fails = 0

    def check(name, ok):
        nonlocal fails
        print("  %s %s" % ("OK  " if ok else "FAIL", name))
        fails += not ok

    def setup(m, c):
        m.w16(0xF600, 0x1234)             # [R4] source for 94 / B4
        m.w16(0xF620, 0xBEEF)             # mem source for 84
        m.w8(0xF640, 0x5A)                # mem source for A4
    code = bytes([0xE6, 0xF4, 0x00, 0xF6,     # MOV R4,#0F600H
                  0x94, 0x04, 0x10, 0xF6,     # MOV 0F610H,[R4]
                  0xE6, 0xF5, 0x02, 0xF6,     # MOV R5,#0F602H
                  0x84, 0x05, 0x20, 0xF6,     # MOV [R5],0F620H
                  0xB4, 0x04, 0x30, 0xF6,     # MOVB 0F630H,[R4]   (low byte 34)
                  0xE6, 0xF6, 0x04, 0xF6,     # MOV R6,#0F604H
                  0xA4, 0x06, 0x40, 0xF6])    # MOVB [R6],0F640H
    m, c = run(code, 7, setup)
    check("94 MOV mem,[Rwn] copies the word", m.r16(0xF610) == 0x1234)
    check("84 MOV [Rwn],mem copies the word", m.r16(0xF602) == 0xBEEF)
    check("B4 MOVB mem,[Rwn] copies the byte", m.r8(0xF630) == 0x34)
    check("A4 MOVB [Rwn],mem copies the byte", m.r8(0xF604) == 0x5A)
    check("the pointer registers are not modified",
          c.gr(4) == 0xF600 and c.gr(5) == 0xF602 and c.gr(6) == 0xF604)
    check("IP advanced 4 bytes per instruction", c.ip == 28)

    def setup2(m, c):
        m.w16(0xF700, 0x0A0B)
    code2 = bytes([0xE6, 0xF4, 0x00, 0xF7,    # MOV R4,#0F700H
                   0xE6, 0xF6, 0x10, 0xF7,    # MOV R6,#0F710H
                   0xE8, 0x64])               # MOV [R6],[R4+]
    m, c = run(code2, 3, setup2)
    check("E8 MOV [Rwn],[Rwm+] copies and post-increments",
          m.r16(0xF710) == 0x0A0B and c.gr(4) == 0xF702 and c.gr(6) == 0xF710)
    print("PASS: c167sim opcodes" if not fails else "FAIL: %d" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
