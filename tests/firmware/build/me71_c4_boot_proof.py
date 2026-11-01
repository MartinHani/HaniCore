#!/usr/bin/env python3
r"""
me71_c4_boot_proof.py - the Audi 2.7T ME7.1 C4 image boots: EXECUTE the
mask-ROM boot code against it.

    py tests\firmware\build\me71_c4_boot_proof.py [image]

THE QUESTION. The 2.7T's C167CR-4RM starts from an internal mask ROM (ROMEN
set: flash 0x0000-0x7FFF is never executed - on these images it is not even a
vector table). That ROM checks the ROMSYS records before it jumps through the
entry pointer, and an image it refuses is an ECU only boot mode can revive.
HaniCore's 2.7T build keeps the ECU's own 0x000000-0x01FFFF and recomputes the
entry pointer and the three records (build_hanicore_me711.py --board
vag_me71_c4); this gate runs the ROM over the result.

THE MODEL OF THE ROM. an ME7 boot-sector read is the ME7.5 05.12 boot code (88 % of
the 4B0906018DC's own flash copy). The 2.7T carries the same ROMSYS header
variant (word +4 = 0x5BDC, the 05.xx family - 06.02 images carry 0x5C02) and
the gate PROVES the model fits: the stock 2.7T image the build took its boot
region from must reach its OWN entry under it, and a one-bit change in a
sampled page must not. A model that accepted everything, or nothing, fails
there. Class: EXACT TARGET BINARY (the image) + SAME-FAMILY ROM (the model),
INFERENCE that the 2.7T's mask ROM checks what 05.12 checks - supported by the
stock image passing exactly.

WHY IT CANNOT PASS VACUOUSLY. Two refusal controls (a sampled code word, the
startup record) and the stock-image acceptance; plus the property the store
relies on - a change inside the persistence store is NOT refused, so a
reclaim erase cannot brick the ECU.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402
import c167sim as S  # noqa: E402

IMAGE = ROOT / "bins/hanicore/HaniCore_ME71_27T_v102_dev.bin"
MANIFEST = IMAGE.with_suffix(".json")
ROM = ROOT / "bins/oem/CPU.BIN"
WDTCON_AT_RESET = 0x0002
STEPS = 3_000_000

CHECKS = FAILS = 0


def check(label, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print("%s %s%s" % ("PASS" if ok else "FAIL", label,
                       ("   " + detail) if detail else ""))


def entry_of(img):
    return ((img[0x8002] | img[0x8003] << 8) << 16) | (img[0x8000] | img[0x8001] << 8)


def boots(img, rom):
    """Run the ROM from reset with `img` as the external flash; 'reached'
    when it jumps to the image's own ROMSYS entry."""
    m = S.Mem(img)
    base = m.r8

    def r8(a, _b=base):
        a &= 0xFFFFFF
        return rom[a] if a < 0x8000 else _b(a)
    m.r8 = r8
    cpu = S.CPU(m, 0x00, 0x0000)
    for reg, v in ((0xFE10, 0xFC00), (0xFE12, 0xFC00), (0xFE14, 0xFA00),
                   (0xFE16, 0xFC00), (0xFE00, 0), (0xFE02, 1), (0xFE04, 2),
                   (0xFE06, 3)):
        m.sfr[reg] = v
    cpu.einit_done = False
    m.sfr[0xFF12] = 0xE604                      # SYSCON.ROMEN set
    m.sfr[0xFFAE] = WDTCON_AT_RESET
    target = entry_of(img)
    try:
        for n in range(STEPS):
            if ((cpu.csp << 16) | cpu.ip) == target:
                return "reached", n
            cpu.step()
    except S.Trap as e:
        return "trap %s" % e, 0
    return "step limit", STEPS


def flip(img, off):
    b = bytearray(img)
    b[off] ^= 0x01
    return bytes(b)


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else IMAGE
    if not path.exists():
        print("SKIP: %s not built (build_hanicore_me711.py --board vag_me71_c4)"
              % path.name)
        return 0
    img = path.read_bytes()
    rom = ROM.read_bytes()
    meta = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    donor_path = ROOT / "reference/ME7Sum/bins/4B0907551F.bin"
    print("image  %s  sha256 %s" % (path.name, hashlib.sha256(img).hexdigest()[:16]))
    print("rom    %s  (05.12 model)" % ROM.name)

    # 1 - the model fits this board family
    if donor_path.exists():
        donor = donor_path.read_bytes()
        how, n = boots(donor, rom)
        check("the stock 2.7T image (4B0907551F) reaches its own entry 0x%06X"
              % entry_of(donor), how == "reached", "%s after %d" % (how, n))
        how, _ = boots(flip(donor, 0x40000), rom)
        check("CONTROL: the stock image with a sampled word changed is refused",
              how != "reached", how)
    else:
        print("SKIP stock-image model check: %s missing (reference/ is local)"
              % donor_path)

    # 2 - HaniCore's image boots
    how, n = boots(img, rom)
    check("HaniCore 2.7T image: the ROM hands off to ?C_STARTUP 0x%06X"
          % entry_of(img), how == "reached", "%s after %d instructions" % (how, n))
    if meta.get("entry_cpu"):
        check("the ROMSYS entry IS the linked ?C_STARTUP",
              entry_of(img) == meta["entry_cpu"], "0x%06X" % meta["entry_cpu"])

    # 3 - controls: a change the records cover is refused
    how, _ = boots(flip(img, 0x40000), rom)
    check("CONTROL: a changed word in a sampled code page is refused",
          how != "reached", how)
    how, _ = boots(flip(img, 0x8038), rom)
    check("CONTROL: a wrong startup record (0x8038) is refused",
          how != "reached", how)

    # 4 - the store is outside the records: an erase there cannot brick it
    for off in (0x070000, 0x08FFFE, 0x0FE000):
        how, _ = boots(flip(img, off), rom)
        check("a change inside the persistence store at 0x%06X still boots"
              % off, how == "reached", how)

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
