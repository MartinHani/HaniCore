#!/usr/bin/env python3
r"""
me711_asic_cs_timing.py - how long the ASIC needs after CS before it can
shift a bit, against how long each master actually waits.

THE FINDING THIS QUANTIFIES. The ASIC does not sit armed waiting for clocks.
Its SSC is DISARMED between frames: the teardown at IROM 0x180E clears SSCEN
and, at 0x1818, clears DP3.8 - so its data output is an INPUT, high-Z. It arms
only inside the CC9 chip-select interrupt (0x18E6), which switches register
banks, calls two helpers, and runs the whole SSC+PEC setup at 0x17B0 before
writing SSCCON = 0x871F. Until that write lands, there is no slave.

The OEM master respects this. Between BCLR P6.4 and the PEC start it copies 96
words, checksums 95, initialises the SSC and then waits for T4 to tick. That is
not decoration - it is the slave's arming window.

HaniCore builds its frame once at init, so the exchange has nothing to do
between asserting CS and firing SSCTIC's request bit: about six instructions.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: E402  (puts every tools/ and tests/ module on sys.path)
ASIC = (ROOT / "bins/ASIC-IROM-7x00005d-from-8D0907551M.bin").read_bytes()
OEM = (hcpaths.OEM_READ).read_bytes()


def ilen(op):
    return 4 if (op & 0x0F) in (2, 3, 4, 5, 6, 7, 0xA) else 2


def count(img, lo, hi, base=0):
    """instructions in a straight-line run [lo,hi)"""
    n, off = 0, lo - base
    while off < hi - base:
        n += 1
        off += ilen(img[off])
    return n


def main():
    print("=" * 72)
    print("A. THE SLAVE'S ARMING PATH  (ASIC IROM, from the CS falling edge)")
    print("=" * 72)
    legs = [
        ("CC9 ISR prologue 0x18E6..0x1902  SCXT x2, 4 pushes, DPP setup",
         count(ASIC, 0x18E6, 0x1902), 2),
        ("  helper 0x113E (stack switch)", count(ASIC, 0x113E, 0x1158), 1),
        ("dispatch 0x1906..0x1916  JB P2.9, 3 MOV, CALLS",
         count(ASIC, 0x1906, 0x191A), 1),
        ("SSC+PEC setup 0x17B0..0x17F8  up to the SSCCON=871F write",
         count(ASIC, 0x17B0, 0x17F8), 1),
        ("  helper 0x7C74 (DPP translate), called twice",
         count(ASIC, 0x7C74, 0x7C8A), 2),
    ]
    tot = 0
    for name, n, mult in legs:
        tot += n * mult
        print(f"  {n:4d} x{mult}  {name}")
    print(f"  ---- {tot:4d} instructions before SSCCON = 0x871F is written")
    print("  plus C166 interrupt entry latency and any higher-priority ISR.")
    for mhz in (20, 40):
        # C166: most instructions are 1 state = 2 CPU clocks; memory and
        # branch instructions cost more, so 2 clocks/instr is a FLOOR.
        us = tot * 2 / mhz
        print(f"    >= {us:6.2f} us at fCPU = {mhz} MHz  (2 clocks/instr floor)")

    print()
    print("=" * 72)
    print("B. WHAT EACH MASTER WAITS, from CS low to the first clock")
    print("=" * 72)
    # OEM: BCLR P6.4 at 0x0BE760 -> CALLS 0x0233A6 (PEC start) at 0x0BE7B4
    straight = count(OEM, 0x0BE762, 0x0BE7B4)
    copy_loop = 8 * 96          # 0x0BE76A..0x0BE77E is 8 instructions x 96
    csum = 95 * 5               # 0x0BEB34, ~5 instructions per word
    print(f"  OEM  0x8BE760 BCLR P6.4  ->  0x8BE7B4 CALLS 0x0233A6")
    print(f"       {straight:5d} straight-line instructions")
    print(f"     + {copy_loop:5d} the 96-word copy loop (8 instr x 96)")
    print(f"     + {csum:5d} the 95-word checksum")
    print(f"     + the SSC init call, then an EXPLICIT wait for T4 to advance")
    oem = straight + copy_loop + csum
    print(f"     = {oem:5d} instructions MINIMUM, excluding both calls' bodies")
    for mhz in (40,):
        print(f"       ~ {oem * 2 / mhz:7.1f} us at {mhz} MHz, plus the T4 tick")

    print()
    print("  HaniCore  asic_begin():  ASIC_CS_LATCH=0 ; ASIC_CS_DIR=1 ;")
    print("            SSCCON|=0x8000 ; SSCRIC=.. ; SSCTIC=..|0x0080")
    hc = 6
    print(f"       {hc:5d} instructions  ~ {hc * 2 / 40:5.2f} us at 40 MHz")

    print()
    print("=" * 72)
    print("C. VERDICT")
    print("=" * 72)
    need = tot * 2 / 40
    have = hc * 2 / 40
    print(f"  slave needs   >= {need:6.2f} us   (optimistic, 40 MHz, 2 clk/instr)")
    print(f"  HaniCore gives   {have:6.2f} us")
    print(f"  shortfall        {need / have:6.1f}x")
    print(f"  OEM gives        {oem * 2 / 40:6.1f} us  = {oem * 2 / 40 / need:.0f}x "
          f"the slave's minimum")
    print()
    print("  At SSCBR=0x13 the master clock is 1.000 MHz: 1 us per bit, 16 us")
    print("  per word. The slave therefore arms somewhere inside the FIRST few")
    print("  words of a 96-word frame - which is exactly where the captured")
    print("  reply stops looking like a frame.")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
