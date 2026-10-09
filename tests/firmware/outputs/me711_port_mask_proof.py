#!/usr/bin/env python3
r"""
me711_port_mask_proof.py - an output write touches only its own port bits.

    py tests\firmware\outputs\me711_port_mask_proof.py              the image me711_image names
    py tests\firmware\outputs\me711_port_mask_proof.py --control    the scanner's mutation control

THE DEFECT. Keil C166 compiles ~x for an `unsigned char` x as CPLB - a
complement of the LOW byte only - so `P2 &= (unsigned int)~physical` became
`AND P2, 0x00xx`. Every coil ON edge cleared the P2.8..P2.15 latches and every
coil OFF edge cleared DP2.8..DP2.15, releasing the fuel pump (P2.12) and the
throttle-bridge enable (P2.11) at the first spark. In the simulator it also
overwrote the cam input P2.8, which is how the K-line + transient run found it
(the cam level stopped alternating, the cycle was withdrawn, events merged).

P1  the linked image has no CPLB whose register then ANDs a port or
    direction register (P2/P3/P6/P7/P8, their DP/ODP registers)
P2  hc_hal_deadline_ports(), coil ON and OFF, executed in the image: only
    the coil bit changes in P2/DP2; the other bits of both bytes survive
P3  the same for an injector edge on P7/P8
P4  and for the bench pulse path (hc_deadline_bench_port_f), which writes
    the port through a pointer
--control: the scanner flags a CPLB -> AND P2 sequence planted in a copy of
the image (so P1 cannot pass by finding nothing to look at).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402
import c166_disasm as D               # noqa: E402
import me711_image as PI              # noqa: E402
import me711_trigger_test as PT       # noqa: E402

PORTS = {"P2", "DP2", "ODP2", "P3", "DP3", "ODP3", "P6", "DP6", "ODP6",
         "P7", "DP7", "ODP7", "P8", "DP8", "ODP8"}
P2, DP2, P7, DP7, P8, DP8 = 0xFFC0, 0xFFC2, 0xFFD0, 0xFFD2, 0xFFD4, 0xFFD6
FAILS = 0


def check(name, ok, detail=""):
    global FAILS
    FAILS += not ok
    print("  [%s] %-62s %s" % ("PASS" if ok else "FAIL", name, detail))


def scan(img: bytes):
    """Every CPLB RLn whose low-byte complement reaches a 16-bit AND within
    six instructions - directly, or through a zero-extension (MOVBZ) into
    another register - whatever the AND's target (a named port register or
    an indirect store through a pointer). In C that is `~(u8)` used as a
    word mask, which always clears the upper byte."""
    hits = []
    for fo in range(0, len(img) - 1, 2):
        if img[fo] != 0xB1 or img[fo + 1] & 0x0F:
            continue
        lines = D.disassemble(img, fo, 7, 0x80 | (fo >> 16))
        lines = lines.splitlines() if isinstance(lines, str) else [str(x) for x in lines]
        m = re.search(r"CPLB\s+RL(\d+)", lines[0])
        if not m:
            continue
        regs = {"R" + m.group(1)}
        for l in lines[1:]:
            if " MOVBZ " in l:
                # decoded from the bytes: C0 sd = MOVBZ Rd, (byte reg s).
                # c166_disasm prints these two nibbles the wrong way round.
                at = int(l.split()[0], 16)
                src, dst = img[at + 1] >> 4, img[at + 1] & 15
                if src % 2 == 0 and "R%d" % (src // 2) in regs:
                    regs.add("R%d" % dst)
            a = re.search(r"\bAND\s+([\w\[\]+#]+),\s*(R\d+)\b", l)
            if a and a.group(2) in regs:
                hits.append("0x%06X %s" % (0x800000 + fo, a.group(1)))
                break
    return hits


def deadline_ports(c, base, physical, on):
    c.m.w16(PT.sym("hc_cfg_validation") & 0xFFFF, 0)
    c.m.w16(PT.sym("hc_ignition_allowed") & 0xFFFF, 1)
    c.m.w16(PT.sym("hc_injection_allowed") & 0xFFFF, 1)
    return c.call("hc_hal_deadline_ports", base, 1, physical, on)


def main() -> int:
    img = PI.image().read_bytes()
    print("=== port writes keep the other bits - %s ===" % PI.image().name)
    print("  sha256 %s\n" % PI.sha256())
    if "--control" in sys.argv:
        planted = bytearray(img)
        at = 0x48000                          # B1 80 CPLB RL4 ; 64 F4 C0 FF AND P2,R4
        planted[at:at + 6] = bytes([0xB1, 0x80, 0x64, 0xF4, 0xC0, 0xFF])
        hits = scan(bytes(planted))
        ok = any(h.startswith("0x%06X" % (0x800000 + at)) for h in hits)
        print("CONTROL: the planted CPLB -> AND P2 is %s" % ("found" if ok else "MISSED"))
        return 0 if ok else 1

    hits = scan(img)
    check("P1 no byte complement feeds a word AND on a port register",
          not hits, ", ".join(hits) or "none in %d KiB" % (len(img) // 1024))

    c = PT.Call()
    seed = 0xDA5B                          # P2.8/9/11/12/14/15 and low bits set
    for on in (1, 0):
        c.m.sfr[P2], c.m.sfr[DP2] = seed, seed ^ 0x00FF
        deadline_ports(c, 0, 0x01, on)     # coil 1 = P2.0
        got = (c.m.sfr[P2], c.m.sfr[DP2])
        want = ((seed & ~1, (seed ^ 0x00FF) | 1) if on
                else (seed | 1, (seed ^ 0x00FF) & ~1))
        check("P2 coil 1 %s: only P2.0 / DP2.0 change" % ("ON" if on else "OFF"),
              got == want, "P2 %04X DP2 %04X, want %04X %04X" % (got + want))
    for on in (1, 0):
        for r in (P7, DP7, P8, DP8):
            c.m.sfr[r] = seed
        deadline_ports(c, 8, 0x09, on)     # P7.4 (bit 0) and P8.3 (bit 3)
        got = tuple(c.m.sfr[r] for r in (P7, DP7, P8, DP8))
        want = ((seed & ~0x10, seed | 0x10, seed & ~0x08, seed | 0x08) if on
                else (seed | 0x10, seed & ~0x10, seed | 0x08, seed & ~0x08))
        check("P3 injector %s: only P7.4 / P8.3 change" % ("ON" if on else "OFF"),
              got == want, "P7 %04X DP7 %04X P8 %04X DP8 %04X" % got)
    # P4: the bench pulse path (hc_deadline_bench_port_f), IGN = P2/DP2
    try:
        PT.sym("hc_deadline_bench_port_f")
        have = True
    except SystemExit:
        have = False
    if have:
        for on in (1, 0):
            c.m.sfr[P2], c.m.sfr[DP2] = seed, seed ^ 0x00FF
            c.call("hc_deadline_bench_port_f", 6, 0x01, on)    # HC_DL_BENCH_IGN
            got = (c.m.sfr[P2], c.m.sfr[DP2])
            want = ((seed & ~1, (seed ^ 0x00FF) | 1) if on
                    else (seed | 1, (seed ^ 0x00FF) & ~1))
            check("P4 bench pulse %s: only P2.0 / DP2.0 change" % ("ON" if on else "OFF"),
                  got == want, "P2 %04X DP2 %04X, want %04X %04X" % (got + want))
    print("\n%s" % ("PORT MASK PROOF PASSES" if not FAILS else "PORT MASK PROOF FAILS"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
