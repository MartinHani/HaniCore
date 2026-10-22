#!/usr/bin/env python3
r"""
me711_owned_boot.py - HaniCore's own boot region (file 0x000000-0x01FFFF), so
an image needs no byte of the OEM boot block.

What the reset path actually needs from this region was measured, not assumed:
the OEM boot block was executed from reset in c167sim (both ROMEN states) and
every flash byte it fetched or read was recorded. Up to the handoff it reads
only:

  * the ROMSYS header fields at 0x8000-0x8003, 0x8008-0x8017, 0x8020-0x803F
    (entry pointer, record pointers, the two sampled-page ranges, two sums);
  * the first and last word of every 8 KiB page in the two sampled ranges,
    word[0xFFFE], word[0x10000], word[0x1FFFE] and the parameter-page record
    the header points at;
  * with ROMEN clear, nothing but its own code, two table bytes and the entry
    pointer - no checksum at all.

Removing each OEM byte in turn and re-running the boot path shows that,
besides the header and the sums, it needs exactly three marker words
(MARKERS below). No OEM code or calibration byte is needed.

Which of the two ROMEN cases this board is in is NOT measured (see
the maintainer's design notes). This region is written to work in both:

  ROMEN set   - the boot code is the CPU's internal mask ROM. Flash
                0x0000-0x7FFF is never executed; the mask ROM checks the ROMSYS
                header and the sums below, then jumps to ?C_STARTUP.
  ROMEN clear - the CPU fetches the reset vector from flash 0x000000. Slot 0
                jumps to the prologue below, every other slot forwards to
                HaniCore's table at seg82:N*4 (the same forwarding the OEM
                table used for 105 of its 128 slots), and the prologue ends in
                ?C_STARTUP.

Everything here is generated from HaniCore constants. The register values in
the prologue are the board's clock/reset configuration (the same values the
OEM reset path writes); the code around them is HaniCore's.
"""
from __future__ import annotations

REGION_LEN = 0x20000
HEADER = 0x8000
PAGE = 0x2000
PROLOGUE = 0x0200            # inside SA0, after the 128-slot table
VECTOR_SEG = 0x82            # HaniCore's second-level table, seg82:N*4
PARAMPAGE_RECORD_CPU = 0x81E572   # header+0x10: where the param-page sum lives

# Sector format markers the ROMEN-set boot path requires (found by removing
# each byte of the OEM region in turn and executing the boot path): without
# them it stays in its own loader. End-of-sector 0x3CC3 at 0x00FFFE and
# 0x01FFFE, start-of-parameter-page 0x5A5A at 0x010000.
MARKERS = ((0x00FFFE, 0x3CC3), (0x010000, 0x5A5A), (0x01FFFE, 0x3CC3))


def _jmps(seg: int, off: int) -> bytes:
    return bytes((0xFA, seg & 0xFF, off & 0xFF, (off >> 8) & 0xFF))


def prologue(startup: int) -> bytes:
    """ROMEN-clear reset path. Runs on the register bank at 0xFC00,
    touches no stack and no external RAM. The listing is checked by
    tests/firmware/build/me711_owned_boot_proof.py, which disassembles and
    executes it."""
    code = [
        # Reset cause first: HaniCore's reset log reads T0 as the WDTCON value
        # at reset (the OEM path made the same copy), before anything that
        # could change WDTCON.
        b"\xF2\x28\xAE\xFF",        # MOV   T0, WDTCON
        b"\xE6\x08\x00\xFC",        # MOV   CP, #0FC00h   (the reset value, stated)
        b"\xA7\x58\xA7\xA7",        # SRVWDT
        # Clock and reset configuration of this board: RSTCON 0xE300 with
        # bit 8 released afterwards, SYSCON2 0x0500 then 0x0400 (EXTR #2).
        b"\xE6\xF4\x00\xE3",        # MOV   R4, #0E300h
        b"\xE6\xF5\xE0\xF1",        # MOV   R5, #0F1E0h    RSTCON
        b"\xB8\x45",                # MOV   [R5], R4
        b"\xD1\x90",                # EXTR  #2
        b"\xE6\xE8\x00\x05",        # MOV   SYSCON2, #0500h
        b"\xE6\xE8\x00\x04",        # MOV   SYSCON2, #0400h
        b"\xE6\xF4\xE0\xF1",        # MOV   R4, #0F1E0h
        b"\xA8\x54",                # MOV   R5, [R4]
        b"\x66\xF5\xFF\xFE",        # AND   R5, #0FEFFh
        b"\xB8\x54",                # MOV   [R4], R5
        b"\xA7\x58\xA7\xA7",        # SRVWDT
        # Zero the on-chip RAM the application expects zeroed (the startup
        # does not run ?C_INIT): XRAM 0xE000-0xE7FF and IRAM 0xF200-0xFDFF
        # except this register bank at 0xFC00-0xFC1F. Stores pre-decrement.
        b"\xE0\x00",                # MOV   R0, #0
    ]
    for top, bottom in ((0xE800, 0xE000), (0xFC00, 0xF200), (0xFE00, 0xFC20)):
        code += [
            b"\xE6\xF1" + top.to_bytes(2, "little"),      # MOV R1, #top
            b"\x88\x01",                                  # MOV [-R1], R0
            b"\x46\xF1" + bottom.to_bytes(2, "little"),   # CMP R1, #bottom
            b"\xED\xFC",                                  # JMPR cc_UGT, -4 words
            b"\xA7\x58\xA7\xA7",                          # SRVWDT
        ]
    code.append(_jmps(startup >> 16, startup & 0xFFFF))  # JMPS ?C_STARTUP
    return b"".join(code)


def compose(img: bytearray, startup: int, r1_limit: int, r2_start: int,
            r2_limit: int) -> None:
    """Write the whole boot region into `img` (file offsets 0..0x1FFFF).
    The sums are NOT written here: the caller computes them over the final
    image, because they sample HaniCore's code pages too."""
    img[0:REGION_LEN] = b"\xFF" * REGION_LEN
    img[0:4] = _jmps(0x00, PROLOGUE)
    for slot in range(1, 128):
        img[slot * 4:slot * 4 + 4] = _jmps(VECTOR_SEG, slot * 4)
    for off, word in MARKERS:
        img[off:off + 2] = word.to_bytes(2, "little")
    p = prologue(startup)
    img[PROLOGUE:PROLOGUE + len(p)] = p

    def put32(off, v):
        img[off:off + 4] = (v & 0xFFFFFFFF).to_bytes(4, "little")
    put32(HEADER + 0x00, ((startup >> 16) << 16) | (startup & 0xFFFF))
    put32(HEADER + 0x08, 0x20)                    # descriptor table offset
    put32(HEADER + 0x0C, 0x38)                    # sum list offset
    put32(HEADER + 0x10, PARAMPAGE_RECORD_CPU)
    put32(HEADER + 0x14, r2_limit)
    put32(HEADER + 0x30, r1_limit)                # table+0x10
    put32(HEADER + 0x34, r2_start)                # table+0x14
    # Parameter-page record: word[0x10000] + word[0x1FFFE] (the two markers).
    rec = PARAMPAGE_RECORD_CPU - 0x800000
    pp = (int.from_bytes(img[0x10000:0x10002], "little")
          + int.from_bytes(img[0x1FFFE:0x20000], "little"))
    put32(rec, pp)
