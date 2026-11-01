#!/usr/bin/env python3
r"""
me71_c4_umkom_proof.py - the Audi 2.7T image answers the S5500's runtime
supervision (frame words 1..3) EXACTLY as the stock 2.7T ECU does.

    py tests\firmware\asic\me71_c4_umkom_proof.py

THE QUESTION. On the Porsche, me711_umkom_proof runs HaniCore's
hc_umkom_service beside the Porsche OEM's own um_service. The 2.7T's OEM code
is a sibling with DIFFERENT constants (its accumulator ladder starts at
0x5A3E where the Porsche's starts at 0x131C, and it divides by 0x1212), so the
Porsche proof says nothing about the 2.7T. This gate executes the 2.7T's OWN
routines out of the owner's test ECU image, ME7Sum bins/
4B0907551F.bin (EXACT TARGET BINARY):

    um_service 0x871DE0  (frame buffer 0xE42E, state 0x80AC..0x80C6)
    um_advance 0x8720B8  (the CCMx SRST checks + accumulator step)
    um_init    0x872144

located by instruction-for-instruction correspondence with the Porsche's
0x8B1E24 / 0x8B20FC / 0x8B2188 (same code shape, state block moved by +0x1C).

CHECKS
  A  HaniCore TX word 1 == the 2.7T OEM's on the modelled S5500 stream
  B  ... and on RANDOM word-1 streams (every nibble pattern), so the
     equivalence does not rest on the S5500 model
  C  the 2.7T OEM never SRSTs on the modelled stream (the model fits it)
  D  HaniCore's health counter stays below the OEM's SRST threshold (13)

WHY IT CANNOT PASS VACUOUSLY: on the random streams the 2.7T OEM resets on
roughly a quarter of the ticks (an invalid question SRSTs it), so it is
discriminating, and HaniCore must match it on every other tick. A reset tick
is excluded because the real ECU sends nothing after SRST.

FINDING (2026-10-24): executed, the Porsche and the 2.7T OEM routines give
the SAME word 1 on every stream tried, the different ladder constants
notwithstanding - the static reading in ME71_27T_PORT_PLAN.md (the answer is
FR[q] on both) holds by execution. The gate prints that comparison.

NOT PHYSICALLY VERIFIED: c167sim, no ASIC silicon.
"""
from __future__ import annotations

import os
import random
import sys
from pathlib import Path

os.environ.setdefault("HANICORE_BOARD", "vag_me71_c4")
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402
import me711_umkom_proof as U  # noqa: E402

C4_OEM = ROOT / "reference/ME7Sum/bins/4B0907551F.bin"
C4_SVC, C4_ADV, C4_INIT = (0x87, 0x1DE0), (0x87, 0x20B8), (0x87, 0x2144)
C4_FRAME = 0xE42E
C4_ERRC = 0x3800AE                   # Porsche 0x8092
C4_DPP = (0x0204, 0x0205, 0x00E0, 0x0003)
P_SIG = bytes.fromhex("2804E6FD3ED3E6FC3ED3")   # Porsche um_service head
C4_SIG = bytes.fromhex("2804E6FD2EE4E6FC2EE4")  # 2.7T um_service head


def run_oem(img, svc, adv, init, frame, errc, dpp, stream):
    c = U.new_cpu(img, dpp)
    U.call(c, *init)
    tx, srst = [], []
    for w1, _p in stream:
        c.m.w16(frame + 0, 0x782E)
        c.m.w16(frame + 2, w1)
        c.m.w16(frame + 4, 0)
        c.m.w16(frame + 6, 0)
        r = U.call(c, *svc)
        srst.append(r == "SRST")
        if r == "SRST":
            c.m.w8(errc, 11)
        elif r != "ok":
            return None, r
        tx.append(c.m.r16(frame + 2))
        U.call(c, *adv)
    return tx, srst


def main() -> int:
    if not U.HANI.exists():
        print("SKIP: %s not built" % U.HANI.name)
        return 0
    if not C4_OEM.exists():
        print("SKIP: %s missing (reference/ is local)" % C4_OEM)
        return 0
    U.patch_mem()
    oem = C4_OEM.read_bytes()
    fails = 0

    def check(name, ok, detail=""):
        nonlocal fails
        fails += not ok
        print("  [%s] %-60s %s" % ("PASS" if ok else "FAIL", name, detail))

    print("=== Audi 2.7T: HaniCore's UMKOM responder vs 4B0907551F um_service ===")
    print("  image  %s\n" % U.HANI.name)
    off = 0x71DE0
    check("the 2.7T OEM routine is where this gate says",
          oem[off:off + len(C4_SIG)] == C4_SIG
          and U.OEM.read_bytes()[0xB1E24:0xB1E24 + len(P_SIG)] == P_SIG)

    st, s = U.stimulus(640, seed=0xAA)
    htx, hr, hmax = U.run_hani(st)
    otx, osrst = run_oem(C4_OEM, C4_SVC, C4_ADV, C4_INIT, C4_FRAME, C4_ERRC,
                         C4_DPP, st)
    if htx is None or otx is None:
        check("both responders execute", False, "%s / %s" % (hr, osrst))
        return 1
    mism = sum(a != b for a, b in zip(htx, otx))
    check("A  TX word 1 == 2.7T OEM, modelled S5500, 640 ticks", mism == 0,
          "%d mismatches" % mism)
    check("C  the 2.7T OEM never SRSTs on the modelled stream", not any(osrst),
          "%d SRST" % sum(osrst))
    check("D  HaniCore health stays below 13", hmax < 13, "max %d" % hmax)

    rnd = random.Random(0x27)
    # A random word 1 is mostly an INVALID question: the OEM then SRSTs - the
    # real ECU resets and sends nothing - while the gate resumes it. Compare
    # every tick on which the OEM itself stays running.
    total = compared = resets = 0
    for k in range(4):
        stream = [(rnd.randrange(256), True) for _ in range(300)]
        h, _r, _m = U.run_hani(stream)
        o, _s = run_oem(C4_OEM, C4_SVC, C4_ADV, C4_INIT, C4_FRAME, C4_ERRC,
                        C4_DPP, stream)
        if h is None or o is None:
            total = -1
            break
        total += sum(a != b for a, b, x in zip(h, o, _s) if not x)
        compared += sum(not x for x in _s)
        resets += sum(_s)
    check("B  TX word 1 == 2.7T OEM on random streams (non-reset ticks)",
          total == 0 and compared > 900,
          "%d mismatches in %d ticks (%d OEM resets excluded)"
          % (total, compared, resets))

    # control: the Porsche OEM must not be the same machine on these inputs
    p_tx, _ = run_oem(U.OEM, U.OEM_UM_SVC, U.OEM_UM_ADV, U.OEM_UM_INIT,
                      U.OEM_FRAME, U.OEM_8092, U.OEM_DPP, stream)
    diff = None if p_tx is None else sum(a != b for a, b in zip(p_tx, o))
    print("  (control) Porsche OEM vs 2.7T OEM on the last random stream: "
          "%s differing words" % diff)
    print("\n%s" % ("C4 UMKOM PROOF PASSES" if not fails else
                    "C4 UMKOM PROOF FAILED (%d)" % fails))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
