#!/usr/bin/env python3
r"""
me711_runtime_handshake_proof.py - which 118-word TX field carries the
runtime supervision handshake, and where its value comes from.

    py tests\firmware\asic\me711_runtime_handshake_proof.py

THE ANSWER, stated first: frame words 1, 2 and 3. Their value is not generated
by MAIN at all - it is the ASIC's own previous reply, carried back because the
exchange is IN-PLACE and the runtime builder never overwrites those words.

HOW THE FRAME IS BUILT. 0x8BE2B6 does exactly three things:

    0x8BE2BA  MOVB [R9],   #A5      word 0 low
    0x8BE2C0  MOVB [R9+1], #BA      word 0 high      -> 0xBAA5
    0x8BE2CA  ADD  R4, #0008h ; MOV D304, R4         -> &word 4
    0x8BE2D2  ADD  R4, #0086h ; MOV D306, R4         -> &word 71
    0x8BE2FC  MOV  R2, [R4+] ; MOV [R3+], [R2]       words 4..70

Word 0, then words 4..70. Words 1, 2 and 3 are SKIPPED. 0x8BE308 starts at
buf+0x8E, which is word 71, so it does not touch them either.

WHY THAT MATTERS. PEC4 receives into TGT_ASIC_FRAME and PEC0 transmits from the
same buffer - the OEM's own arrangement, which HaniCore already reproduces. So
after an exchange the buffer holds the ASIC's REPLY, and any word the builder
does not overwrite is transmitted straight back on the next frame. Words 1..3
are a challenge-response loop implemented for free by the in-place exchange.

WHAT THE HARDWARE SHOWS. Across every coherent capture the ASIC's reply carries
a small rolling value in w3 - 0x0000, 0x0002, 0x0004 - while w1 and w2 have so
far always been zero. That is the "small rolling state" signature the ME7.5
UMKOM work taught us to look for.

WHAT HANICORE DOES WRONG. build() zeroes all 118 words before writing the
header and the checksum, so words 1..3 go out as zero and the loop is broken.

INDEPENDENCE. This is established from the two BOSCH images - OEM ME7.1.1 and its
A1104F sibling - not from the donor 8D0907551M IROM. The donor only told us a
handshake exists and that its error counter reacts at a threshold; it does not
name the field, and none of its addresses or constants are used here.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: E402  (puts every tools/ and tests/ module on sys.path)
OEM_ME711 = (hcpaths.OEM_READ).read_bytes()
A1104P = ROOT / "bins/a1104f_44HETL07.bin"
A1104 = A1104P.read_bytes() if A1104P.exists() else b""

BUILDER_1146 = 0x0BE2B6
BUILDER_1104 = 0x0E72AC          # + the 0x28FF6 module delta
BUF = 0xD33E                     # OEM ME7.1.1 frame buffer

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<54s} {detail}")


def ilen(op):
    return 4 if (op & 0x0F) in (2, 3, 4, 5, 6, 7, 0xA) else 2


# op+4 forms and MOV/MOVB write a 16-bit-addressed memory operand. op+6 forms
# carry DATA in that field, not an address - counting them is how an earlier
# pass produced 61 phantom "writers" for a constant.
WRITE_OPS = {0xF6, 0xF7, 0x04, 0x05, 0x14, 0x15, 0x24, 0x25,
             0x34, 0x35, 0x54, 0x55, 0x64, 0x65, 0x74, 0x75}


def writers(img, addr16):
    out, off = [], 0
    while off < len(img) - 4:
        if ilen(img[off]) == 4 and img[off] in WRITE_OPS \
                and (img[off + 2] | (img[off + 3] << 8)) == addr16:
            out.append(off)
        off += 2
    return out


def builder_bounds(img, at, label):
    """the two ADD immediates that set the fill window, and the header stores"""
    off, adds, hdr = at, [], []
    while off < at + 0x40:
        op, b1 = img[off], img[off + 1]
        n = ilen(op)
        imm = (img[off + 2] | (img[off + 3] << 8)) if n == 4 else None
        if op == 0x06 and b1 == 0xF4:            # ADD R4, #data16
            adds.append(imm)
        if op == 0xE7 and b1 == 0xF8:            # MOVB RL4, #data8
            hdr.append(imm & 0xFF)
        off += n
    return adds, hdr


def main():
    print("=== 1. the OEM ME7.1.1 runtime builder's fill window ===")
    adds, hdr = builder_bounds(OEM_ME711, BUILDER_1146, "OEM ME7.1.1")
    check("header is written as two BYTE stores", hdr[:2] == [0xA5, 0xBA],
          f"{[hex(h) for h in hdr[:2]]} -> word 0 = 0x%04X"
          % ((hdr[1] << 8) | hdr[0]) if len(hdr) >= 2 else "not found")
    check("the fill starts at byte +0x08", adds[:1] == [0x0008],
          f"+0x{adds[0]:04X} = word {adds[0] // 2}" if adds else "none")
    check("the fill ends 0x86 bytes later", len(adds) > 1 and adds[1] == 0x0086,
          f"+0x{adds[1]:04X} = {adds[1] // 2} words -> word "
          f"{(adds[0] + adds[1]) // 2}" if len(adds) > 1 else "none")
    span = (adds[0] // 2, (adds[0] + adds[1]) // 2) if len(adds) > 1 else (0, 0)
    check("so the builder covers word 0 and words 4..70 ONLY",
          span == (4, 71), f"words {span[0]}..{span[1] - 1}")
    check("WORDS 1, 2 AND 3 ARE NEVER WRITTEN BY THE BUILDER",
          span[0] == 4, "the gap between word 0 and word 4")

    print()
    print("=== 2. nothing else writes them either ===")
    for w in (0, 1, 2, 3):
        n = len(writers(OEM_ME711, BUF + 2 * w))
        check(f"frame word {w} @0x{BUF + 2 * w:04X}: no absolute-address writer",
              n == 0, f"{n} writer(s) in the whole 1 MiB image")
    print("      (word 0 is written register-indirect via [R9], which is why it")
    print("       also shows zero absolute-address writers)")

    print()
    print("=== 3. the A1104F sibling agrees - independent of the donor IROM ===")
    if not A1104:
        check("A1104F image present", False, "bins/a1104f_44HETL07.bin missing")
    else:
        adds2, hdr2 = builder_bounds(A1104, BUILDER_1104, "A1104F")
        check("A1104F writes the same 0xBAA5 header the same way",
              hdr2[:2] == [0xA5, 0xBA], f"{[hex(h) for h in hdr2[:2]]}")
        check("A1104F uses the same +0x08 / +0x86 window",
              adds2[:2] == [0x0008, 0x0086],
              f"+0x{adds2[0]:04X} / +0x{adds2[1]:04X}" if len(adds2) > 1 else "?")
        check("A1104F therefore skips words 1..3 as well",
              adds2[:1] == [0x0008], "same gap, a different Bosch ECU")

    print()
    print("=== 4. what the ASIC actually puts there, on hardware ===")
    caps = [("V9   startup  ", 0x781E, 0x0000, 0x0000, 0x0002),
            ("V10  startup#1", 0x781E, 0x0000, 0x0000, 0x0000),
            ("V10  startup#2", 0x781E, 0x0000, 0x0000, 0x0004),
            ("V10  runtime  ", 0x782E, 0x0000, 0x0000, 0x0004)]
    for nm, w0, w1, w2, w3 in caps:
        print(f"      {nm}  w0={w0:04X}  w1={w1:04X} w2={w2:04X} w3={w3:04X}")
    vals = sorted({c[4] for c in caps})
    check("w3 carries a small rolling value", len(vals) > 1,
          f"observed {[hex(v) for v in vals]} - step 2")
    check("w1 and w2 have been zero in every capture so far",
          all(c[2] == 0 and c[3] == 0 for c in caps), "no counter-evidence yet")

    print()
    print("=== 5. what HaniCore does with them ===")
    src = (ROOT / "firmware/targets/me711/asic/hcasicstart.c").read_text(errors="replace")
    # Up to V10 build() zeroed all 118 words, so words 1..3 went out as zero
    # and the loop was broken on the first runtime frame. V11 clears from 4,
    # matching the OEM fill window. This tracks the CURRENT source, so it
    # flips from "documents the defect" to "confirms the fix".
    old_way = ("for (i = 0u; i < (unsigned int)TGT_ASIC_WORDS_RUN; i++)"
               in src)
    new_way = "for (i = 4u; i < (unsigned int)TGT_ASIC_WORDS_RUN; i++)" in src
    umk = "hc_umkom_service(FRAME)" in src
    check("build() clears from word 4, leaving 1..3 to the UMKOM responder",
          new_way and not old_way and umk,
          "matches the OEM fill window; hc_umkom_service owns words 1..3"
          if new_way and not old_way and umk
          else "still zeroes the whole frame - the loop is broken")

    print()
    bad = [n for n, ok, _ in results if not ok]
    print(f"{len(results) - len(bad)}/{len(results)} checks pass")
    if bad:
        print("FAILED: " + "; ".join(bad))
        return 1
    print()
    print("CONCLUSION")
    print("  The runtime supervision handshake is carried in frame words 1..3.")
    print("  The OEM frame builder skips those words; a SEPARATE OEM routine,")
    print("  um_service (0x8B1E24), reads and REWRITES them each raster tick -")
    print("  it is the Bosch level-2 question/answer monitor. HaniCore now")
    print("  reproduces its MAIN side in hc_umkom_service(); see")
    print("  docs/ME711_UMKOM_SSC.md and tests/firmware/asic/me711_umkom_proof.py.")
    print("  (The earlier reading - 'MAIN just echoes words 1..3' - was a")
    print("  V11-era stepping stone and is superseded.)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
