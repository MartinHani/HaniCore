#!/usr/bin/env python3
r"""
me711_4f_boot_proof.py - the Audi 4F image boots: EXECUTE the mask-ROM boot
code against it (me71_c4_boot_proof's method, on the 4F's own boot region).

    py tests\firmware\build\me711_4f_boot_proof.py [image]

The 4F's CPU starts from a mask ROM (ROMEN set; flash 0x0000 holds CALLS
stubs, not vectors) that checks the ROMSYS records before it jumps through
the entry pointer. HaniCore's 4F build keeps the ECU's own 0x000000-0x01FFFF
and recomputes only the entry and the records (build_hanicore_me711.py
--board audi_4f_v8). The 4F's ROM (header variant 0x5B00) is not available;
an ME7 boot-sector read (05.12) stands in, and the gate PROVES it fits this board:
the stock 4F read must reach its OWN entry under it and a one-bit change in a
sampled page must not. Class: EXACT TARGET BINARY (the image) + SAME-FAMILY
ROM (the model), INFERENCE that the 4F's ROM checks what 05.12 checks -
supported by the stock 4F image passing exactly. The bench decides.

WHY IT CANNOT PASS VACUOUSLY: the stock acceptance, two refusal controls
(a sampled code word, the startup record), and the store property - a change
inside the persistence store is NOT refused, so a reclaim cannot brick it.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402
import me71_c4_boot_proof as B  # noqa: E402  (boots(): the ROM runner)

IMAGE = ROOT / "bins/hanicore/HaniCore_ME711_4F_v102_dev.bin"
STOCK = ROOT / "bins/4f_v8/4F0910560.bin"


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else IMAGE
    if not path.exists():
        print("SKIP: %s not built (build_hanicore_me711.py --board audi_4f_v8)"
              % path.name)
        return 0
    if not STOCK.exists():
        print("SKIP: %s missing (bins/ is local)" % STOCK)
        return 0
    img, stock, rom = path.read_bytes(), STOCK.read_bytes(), B.ROM.read_bytes()
    man = path.with_suffix(".json")
    meta = json.loads(man.read_text()) if man.exists() else {}
    print("image  %s  sha256 %s" % (path.name, hashlib.sha256(img).hexdigest()[:16]))
    print("rom    %s  (05.12 model)" % B.ROM.name)
    ck = B.check

    how, n = B.boots(stock, rom)
    ck("the stock 4F image (4F0910560) reaches its own entry 0x%06X"
       % B.entry_of(stock), how == "reached", "%s after %d" % (how, n))
    how, _ = B.boots(B.flip(stock, 0x40000), rom)
    ck("CONTROL: the stock image with a sampled word changed is refused",
       how != "reached", how)
    if meta.get("boot_region", "oem_boot_contract") == "oem_boot_contract":
        ck("the image keeps the 4F's boot region but entry, record end and sums",
           [i for i in range(0x20000) if img[i] != stock[i]]
           == [0x8000, 0x8001, 0x8002, 0x8016, 0x8038, 0x8039, 0x803C, 0x803D, 0x803E],
           "differing offsets checked against the 9 the build writes")
    else:
        # HaniCore's region (the default): only the ROMSYS scheme is the 4F's
        same = [i for i in range(0x8000, 0x8040) if img[i] != stock[i]]
        ck("own boot region: the 4F's ROMSYS scheme, our entry and records",
           img[0x8004:0x8006] == stock[0x8004:0x8006]
           and img[0x8008:0x8010] == stock[0x8008:0x8010]
           and img[0x8020:0x8030] == stock[0x8020:0x8030],
           "%d header bytes rewritten" % len(same))

    how, n = B.boots(img, rom)
    ck("HaniCore 4F image: the ROM hands off to ?C_STARTUP 0x%06X"
       % B.entry_of(img), how == "reached", "%s after %d instructions" % (how, n))
    if meta.get("entry_cpu"):
        ck("the ROMSYS entry IS the linked ?C_STARTUP",
           B.entry_of(img) == meta["entry_cpu"], "0x%06X" % meta["entry_cpu"])
    how, _ = B.boots(B.flip(img, 0x40000), rom)
    ck("CONTROL: a changed word in a sampled code page is refused",
       how != "reached", how)
    how, _ = B.boots(B.flip(img, 0x8038), rom)
    ck("CONTROL: a wrong startup record (0x8038) is refused",
       how != "reached", how)
    for off in (0x070000, 0x08FFFE, 0x0FE000):
        how, _ = B.boots(B.flip(img, off), rom)
        ck("a change inside the persistence store at 0x%06X still boots" % off,
           how == "reached", how)

    print("\n%d/%d checks pass" % (B.CHECKS - B.FAILS, B.CHECKS))
    return 1 if B.FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
