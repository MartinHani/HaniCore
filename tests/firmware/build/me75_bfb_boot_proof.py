#!/usr/bin/env python3
r"""
me75_bfb_boot_proof.py - the A4 B7 BFB ME7.5 image passes the mask-ROM check.

    py tests\firmware\build\me75_bfb_boot_proof.py [image] [stock read] [rom]

Runs the C167CR's mask ROM (bins/oem/CPU.BIN) from reset over the image with
c167sim and asks whether it hands off to the image's own ROMSYS entry - the
method of me71_c4_boot_proof.py. The model is proven first: the ECU's OWN stock
read (variant 0x5C02) must reach its own entry, and a changed word in its
header / startup record must not. Offline simulation. With bins/oem/ME75_BFB_IROM.bin (this ECU's own ROM, read through
boot mode) it runs the real ROM; without it, the 18T's CPU.BIN is only a stand-in.
"""
from __future__ import annotations

import glob
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
spec = importlib.util.spec_from_file_location(
    "c4", ROOT / "tests/firmware/build/me71_c4_boot_proof.py")
c4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c4)
c4.STEPS = 300_000

CHECKS = FAILS = 0


def check(label, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print("%s %s%s" % ("PASS" if ok else "FAIL", label, ("   " + detail) if detail else ""))


def main():
    found = sorted(glob.glob(str(ROOT / "bins/release/HaniCore_BFB_8E0909518AQ_*.bin")))
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else (Path(found[-1]) if found else None)
    # THIS ECU'S OWN internal ROM (read through boot mode, 2026-11-02) when we have it;
    # the 2.7T/18T CPU.BIN is a different ROM (31 348 of 32 768 bytes differ)
    own = ROOT / "bins/oem/ME75_BFB_IROM.bin"
    rom_p = Path(sys.argv[3]) if len(sys.argv) > 3 else (own if own.exists() else ROOT / "bins/oem/CPU.BIN")
    stock_p = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "reference/bfb/8E0909518AQ.bin"
    if path is None or not path.exists() or not rom_p.exists():
        print("SKIP: BFB image or bins/oem/CPU.BIN missing")
        return 0
    rom, img = rom_p.read_bytes(), path.read_bytes()
    if stock_p.exists():
        st = stock_p.read_bytes()
        how, n = c4.boots(st, rom)
        check("the stock BFB read reaches its own entry 0x%06X" % c4.entry_of(st),
              how == "reached", "%s after %d" % (how, n))
        check("its ROMSYS variant is 0x5C02", st[0x8004:0x8006] == b"\x02\x5C")
        check("CONTROL: stock with the startup record changed is refused",
              c4.boots(c4.flip(st, 0x8038), rom)[0] != "reached")
        check("CONTROL: stock with the entry pointer changed is refused",
              c4.boots(c4.flip(st, 0x8000), rom)[0] != "reached")
    else:
        print("SKIP stock-read model check: %s missing" % stock_p)
    check("the image carries variant 0x5C02", img[0x8004:0x8006] == b"\x02\x5C")
    how, n = c4.boots(img, rom)
    check("HaniCore BFB image: ROM hands off to 0x%06X" % c4.entry_of(img),
          how == "reached", "%s after %d" % (how, n))
    check("CONTROL: a wrong startup record (0x8038) is refused",
          c4.boots(c4.flip(img, 0x8038), rom)[0] != "reached")
    check("CONTROL: a wrong entry pointer (0x8000) is refused",
          c4.boots(c4.flip(img, 0x8000), rom)[0] != "reached")
    check("CONTROL: a wrong parameter-page marker (0x10000) is refused",
          c4.boots(c4.flip(img, 0x10000), rom)[0] != "reached")
    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
