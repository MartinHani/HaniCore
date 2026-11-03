#!/usr/bin/env python3
r"""
me75_bfb_clock_proof.py - the A4 B7 BFB ME7.5 (0261208524) runs at 32 MHz, and
the image says so everywhere it must.

    py tests\firmware\build\me75_bfb_clock_proof.py [image] [stock read]

WHY THIS GATE EXISTS. The BFB was built as "the 18T's hardware" (24 MHz). On
the bench it was silent and reset ~9 times a second: its CPU clock is 32 MHz
and its bus timing is slower than the 18T's. Nothing in the other gates
noticed, because they all test the image against the header it was built
from. This one compares against the ECU's OWN stock read.

CHECKS
  header   hctarget.h's BFB block: fCPU 32 MHz; the K-line S0BG gives 10400
           baud; T1 = fCPU/32 is 1.000 MHz so 1 ms = 1000 ticks and the 1 ms
           tick reload is 1000
  stock    the stock read's own S0BG for its 10400 K-line (beside S0CON
           0x80D1) implies ~32 MHz; its two startup stages write one BUSCON1
           and BUSCON2
  image    the loader and the app startup write the SAME BUSCON1 / BUSCON2 as
           the stock, and the app writes the 32 MHz S0BG default (not 24 MHz's)
Class: EXACT TARGET BINARY (the stock read) for the stock facts; a header read
for the rest. Skips what it has no file for.
"""
from __future__ import annotations

import glob
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HDR = ROOT / "firmware/targets/me711/hctarget.h"
CHECKS = FAILS = 0


def check(label, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print("%s %s%s" % ("PASS" if ok else "FAIL", label, ("   " + detail) if detail else ""))


def bfb_block(text):
    i = text.index("#if TGT_BOARD_VAG_ME75_BFB\n#undef  TGT_ID") if "#if TGT_BOARD_VAG_ME75_BFB\n#undef  TGT_ID" in text \
        else text.index("#if TGT_BOARD_VAG_ME75_BFB\r\n#undef  TGT_ID")
    return text[i:]


def define(block, name):
    m = re.search(r"#define\s+%s\s+(\S+)" % name, block)
    return m.group(1) if m else None


def num(s):
    s = s.rstrip("uUlL")
    return int(s, 0)


def imm_writes(img, lo, hi, reg8):
    """`MOV <sfr>,#imm16` (E6 reg8 lo hi) in img[lo:hi]."""
    return [(i, img[i + 2] | img[i + 3] << 8) for i in range(lo, hi - 3)
            if img[i] == 0xE6 and img[i + 1] == reg8]


def main():
    text = HDR.read_text(errors="replace")
    blk = bfb_block(text)
    fcpu = num(define(blk, "TGT_FCPU_HZ"))
    s0bg = num(define(blk, "TGT_S0BG_10400"))
    tpm = num(define(blk, "TGT_TICKS_PER_MS_X10"))
    rel = num(define(blk, "TGT_TICK_RELOAD"))
    check("BFB fCPU is 32 MHz", fcpu == 32_000_000, "%d" % fcpu)
    baud = fcpu / (32 * (s0bg + 1))
    check("BFB S0BG 0x%02X gives the 10400 baud K-line" % s0bg, abs(baud / 10400 - 1) < 0.01,
          "%.0f baud" % baud)
    t1 = fcpu / 32
    check("T1 = fCPU/32 = 1.000 MHz -> TICKS_PER_MS_X10 = 10000", tpm == int(t1 / 1000 * 10) == 10000,
          "%d" % tpm)
    check("1 ms tick reload = 1000 T8 ticks", rel == int(t1 / 1000), "%d" % rel)

    found = sorted(glob.glob(str(ROOT / "bins/release/HaniCore_BFB_8E0909518AQ_*.bin")))
    img_p = Path(sys.argv[1]) if len(sys.argv) > 1 else (Path(found[-1]) if found else None)
    stock_p = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "reference/bfb/8E0909518AQ.bin"
    if not stock_p.exists():
        print("SKIP stock checks: %s missing" % stock_p)
    else:
        st = stock_p.read_bytes()
        # the K-line init: S0BG 0x5F written right beside S0CON 0x80D1 (stock 0x0397C4)
        pairs = [(a, v) for a, v in imm_writes(st, 0x8000, len(st), 0x5A) if v == 0x5F]
        check("stock writes S0BG = 0x5F for its K-line (fCPU %.1f MHz)" %
              (10400 * 32 * 0x60 / 1e6), bool(pairs), "at %s" % [hex(a) for a, _ in pairs[:3]])
        b1 = {v for _a, v in imm_writes(st, 0x0DC00, 0x0DC20, 0x8A)}
        b1 |= {v for _a, v in imm_writes(st, 0xAD0C0, 0xAD0E0, 0x8A)}
        b2 = {v for _a, v in imm_writes(st, 0x0DC00, 0x0DC20, 0x8B)}
        b2 |= {v for _a, v in imm_writes(st, 0xAD0C0, 0xAD0E0, 0x8B)}
        check("stock BUSCON1 is one value (both stages)", len(b1) == 1, str([hex(x) for x in b1]))
        check("stock BUSCON2 is one value (both stages)", len(b2) == 1, str([hex(x) for x in b2]))
        if img_p and img_p.exists():
            img = img_p.read_bytes()
            ld1 = {v for _a, v in imm_writes(img, 0x20200, 0x20300, 0x8A)}
            ap1 = {v for _a, v in imm_writes(img, 0x40200, 0x40400, 0x8A)}
            ap2 = {v for _a, v in imm_writes(img, 0x40200, 0x40400, 0x8B)}
            check("loader writes the stock BUSCON1", ld1 == b1, "%s vs %s" % (
                [hex(x) for x in ld1], [hex(x) for x in b1]))
            check("app startup writes the stock BUSCON1", ap1 == b1)
            check("app startup writes the stock BUSCON2", ap2 == b2)
            dflt = num(define(blk, "TGT_S0BG"))
            sb = {v for _a, v in imm_writes(img, 0x40000, 0x80000, 0x5A)}
            check("the app writes the 32 MHz default S0BG 0x%02X (57600 baud)" % dflt, dflt in sb,
                  "S0BG immediates: %s" % sorted(hex(x) for x in sb))
            check("the 24 MHz default S0BG 0x0C is not written", 0x0C not in sb)
        else:
            print("SKIP image checks: no BFB image under bins/release")
    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
