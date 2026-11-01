#!/usr/bin/env python3
r"""
me711_4f_umkom_proof.py - the Audi 4F image answers the S5500's runtime
supervision (frame words 1..3) EXACTLY as the stock 4F ECU does.

    py tests\firmware\asic\me711_4f_umkom_proof.py

THE QUESTION. A wrong answer to the S5500's level-2 question/answer monitor
makes it reset MAIN (SWRST_SM) within a few frames. me711_umkom_proof runs
HaniCore's hc_umkom_service beside the PORSCHE's um_service; the 4F carries
its own copy, so that proof says nothing about the 4F until the 4F's own
routine is executed. This gate executes it out of a tester's stock read,
bins/4f_v8/4F0910560.bin (EXACT TARGET BINARY):

    um_service 0x8D39B2  (frame buffer 0xD152, state 0x8098..0x80B2)
    um_advance 0x8D3C8A
    um_init    0x8D3D16

located by instruction-for-instruction correspondence with the Porsche's
0x8B1E24 / 0x8B20FC / 0x8B2188 (same code shape, state block moved by +8),
DPP0..3 = 0x0204 / 0x0205 / 0x00E0 / 0x0003 (the 4F's own startup values).

CHECKS
  A  HaniCore TX word 1 == the 4F OEM's on the modelled S5500 stream
  B  ... and on RANDOM word-1 streams (non-reset ticks)
  C  the 4F OEM never SRSTs on the modelled stream (the model fits it)
  D  HaniCore's health counter stays below the OEM's SRST threshold (13)
  E  CONTROL: the OEM run with a wrong frame address disagrees

WHY IT CANNOT PASS VACUOUSLY: on the random streams the 4F OEM resets on
about a quarter of the ticks (an invalid question SRSTs it), so it
discriminates, and E shows the comparison can fail.

NOT PHYSICALLY VERIFIED: c167sim, no ASIC silicon.
"""
from __future__ import annotations

import os
import random
import sys
from pathlib import Path

os.environ.setdefault("HANICORE_BOARD", "audi_4f_v8")
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402
import me711_umkom_proof as U  # noqa: E402
import me71_c4_umkom_proof as C4  # noqa: E402  (run_oem: the OEM driver loop)

F_OEM = ROOT / "bins/4f_v8/4F0910560.bin"
F_SVC, F_ADV, F_INIT = (0x8D, 0x39B2), (0x8D, 0x3C8A), (0x8D, 0x3D16)
F_FRAME = 0xD152
F_ERRC = 0x38009A                    # Porsche 0x380092
F_DPP = (0x0204, 0x0205, 0x00E0, 0x0003)
F_SIG = bytes.fromhex("2804E6FD52D1E6FC52D1")   # 4F um_service head


def main() -> int:
    if os.environ["HANICORE_BOARD"] != "audi_4f_v8":
        print("SKIP: the 4F image's gate (HANICORE_BOARD=%s)"
              % os.environ["HANICORE_BOARD"])
        return 0
    if not U.HANI.exists():
        print("SKIP: %s not built" % U.HANI.name)
        return 0
    if not F_OEM.exists():
        print("SKIP: %s missing (bins/ is local)" % F_OEM)
        return 0
    U.patch_mem()
    fails = 0

    def check(name, ok, detail=""):
        nonlocal fails
        fails += not ok
        print("  [%s] %-60s %s" % ("PASS" if ok else "FAIL", name, detail))

    print("=== Audi 4F: HaniCore's UMKOM responder vs 4F0910560 um_service ===")
    print("  image  %s\n" % U.HANI.name)
    oem = F_OEM.read_bytes()
    check("the 4F OEM routine is where this gate says",
          oem[0xD39B2:0xD39B2 + len(F_SIG)] == F_SIG)

    st, _s = U.stimulus(640, seed=0xAA)
    htx, hr, hmax = U.run_hani(st)
    otx, osrst = C4.run_oem(F_OEM, F_SVC, F_ADV, F_INIT, F_FRAME, F_ERRC,
                            F_DPP, st)
    if htx is None or otx is None:
        check("both responders execute", False, "%s / %s" % (hr, osrst))
        return 1
    mism = sum(a != b for a, b in zip(htx, otx))
    check("A  TX word 1 == 4F OEM, modelled S5500, 640 ticks", mism == 0,
          "%d mismatches" % mism)
    check("C  the 4F OEM never SRSTs on the modelled stream", not any(osrst),
          "%d SRST" % sum(osrst))
    check("D  HaniCore health stays below 13", hmax < 13, "max %d" % hmax)

    rnd = random.Random(0x4F)
    total = compared = resets = 0
    for _k in range(4):
        stream = [(rnd.randrange(256), True) for _ in range(300)]
        h, _r, _m = U.run_hani(stream)
        o, x = C4.run_oem(F_OEM, F_SVC, F_ADV, F_INIT, F_FRAME, F_ERRC,
                          F_DPP, stream)
        if h is None or o is None:
            total = -1
            break
        total += sum(a != b for a, b, z in zip(h, o, x) if not z)
        compared += sum(not z for z in x)
        resets += sum(x)
    check("B  TX word 1 == 4F OEM on random streams (non-reset ticks)",
          total == 0 and compared > 900,
          "%d mismatches in %d ticks (%d OEM resets excluded)"
          % (total, compared, resets))

    wrong, _ = C4.run_oem(F_OEM, F_SVC, F_ADV, F_INIT, F_FRAME + 2, F_ERRC,
                          F_DPP, st)
    diff = None if wrong is None else sum(a != b for a, b in zip(htx, wrong))
    check("E  CONTROL: a wrong frame address disagrees", bool(diff),
          "%s differing words" % diff)

    print("\n%s" % ("4F UMKOM PROOF PASSES" if not fails else
                    "4F UMKOM PROOF FAILED (%d)" % fails))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
