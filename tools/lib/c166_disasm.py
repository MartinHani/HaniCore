#!/usr/bin/env python3
r"""
c166_disasm.py  -  a linear C166/C167 disassembler for the ME7.5 image.

IDA's export left segments 0x82-0x8A (file 0x20000+) as raw `db` - exactly
where the live OS runs. This tool decodes any region of the binary with
addresses so we can study the real code as ground truth.

Length rule (the key to a sync-safe linear sweep): on the C166 the instruction
length depends ONLY on the opcode's low nibble:
    4 bytes  if (opcode & 0x0F) in {2,3,4,5,6,7,A}
    2 bytes  otherwise
(The protected instructions EINIT/SRVWDT/DISWDT/IDLE/PWRDN/SRST sit in the
4-byte columns 5/7; RET/RETS/RETI/CALLR/NOP/JMPR/BSET/BCLR in 2-byte columns.)
This was validated by re-disassembling the reset/startup block that IDA decoded
and diffing the mnemonic stream (see --validate).

Address model (verified against the reset vector / startup):
  file offset F  <->  IDA logical 0x800000+F.
  Code runs with CSP either 0 (low 64 KB) or 0x80-0x8F.
  seg 0 or 0x80 : file = offset                       (low 64 KB, dual-mapped)
  seg 0x81-0x8F : file = (seg-0x80)*0x10000 + offset

Usage:
  py tools\lib\c166_disasm.py 0x76CC 60          # 60 instrs from file 0x76CC
  py tools\lib\c166_disasm.py 0xA6AB4 80
  py tools\lib\c166_disasm.py --seg 0x83 0xE260 40   # seg:offset form
  py tools\lib\c166_disasm.py --image bins\hanicore\patched.bin 0x3E874 8
  py tools\lib\c166_disasm.py --validate         # sanity check vs known startup
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths as HCP  # noqa: E402

# This ECU's own OEM read (local, not in the repository - see bins/README.md).
BIN = HCP.OEM_READ

# ---- SFR / register naming --------------------------------------------------
#
# THE C167 SHORT REGISTER ENCODING IS CONTEXT DEPENDENT. The same 8-bit `rr`
# field resolves into SFR space (0xFE00 + 2*rr) normally, and into ESFR space
# (0xF000 + 2*rr) while an EXTR prefix is in force. A disassembler that ignores
# the prefix prints confident nonsense: under EXTR the encoding that looks like
# `T1` is really `T7`, and there is nothing in the rendered text to warn you.
#
# This file used to do exactly that, and it also carried a hand-typed table in
# which 0xFE52 was labelled "T7" - 0xFE52 is T1; T7 lives at 0xF050 in ESFR
# space. Both faults are fixed here, and the names are now generated from the
# toolchain's reg167.h (the one the build includes) so they cannot drift or be mistyped again.
_REG_H = HCP.REG167        # the Keil installation's header, which the build uses


def _load_regs():
    sfr, esfr, bits = {}, {}, {}
    try:
        text = _REG_H.read_text(errors="replace")
    except OSError:
        return sfr, esfr, bits
    import re as _re
    for m in _re.finditer(r"^sfr\s+(\w+)\s*=\s*0x([0-9A-Fa-f]+)\s*;", text, _re.M):
        name, addr = m.group(1), int(m.group(2), 16)
        (esfr if addr < 0xFE00 else sfr)[addr] = name
    for m in _re.finditer(r"^sbit\s+(\w+)\s*=\s*(\w+)\s*\^\s*(\d+)\s*;", text, _re.M):
        name, parent, bit = m.group(1), m.group(2), int(m.group(3))
        for table in (sfr, esfr):
            for addr, nm in table.items():
                if nm == parent:
                    bits[(addr, bit)] = name
    return sfr, esfr, bits


SFR, ESFR, BIT_SFR = _load_regs()


# Set by decode() for the instruction being decoded. A module global rather
# than an argument only because decode() names registers from about forty
# places; it is written in exactly one place and read in one.
_ESFR_ACTIVE = False


def regname(rr, byte=False, esfr=None):
    """Resolve a short register field.

    `esfr` MUST reflect whether an EXTR prefix is currently in force. Getting it
    wrong silently renames every SFR in the window.
    """
    if esfr is None:
        esfr = _ESFR_ACTIVE
    if rr >= 0xF0:
        n = rr - 0xF0
        if byte:
            return ("RL%d" % (n // 2)) if n % 2 == 0 else ("RH%d" % (n // 2))
        return "R%d" % n
    if esfr:
        addr = 0xF000 + 2 * rr
        return ESFR.get(addr, "esfr_%04X" % addr)
    addr = 0xFE00 + 2 * rr
    return SFR.get(addr, "mem_%04X" % addr)


def memname(m):
    if 0xFD00 <= m <= 0xFFFF:
        return SFR.get(m, "M:%04X" % m)
    return "%04X" % m

def bitoffname(off, bit):
    if off >= 0x80:
        addr = 0xFF00 + 2 * (off - 0x80)
    else:
        addr = 0xFD00 + 2 * off
    nm = BIT_SFR.get((addr, bit))
    base = SFR.get(addr, "M:%04X" % addr)
    return nm if nm else "%s.%d" % (base, bit)

# ---- arithmetic group (rows 0-7) -------------------------------------------
ARITH = {0: "ADD", 1: "ADDC", 2: "SUB", 3: "SUBC", 4: "CMP", 5: "XOR", 6: "AND", 7: "OR"}
CC = {0: "cc_UC", 1: "cc_NET", 2: "cc_Z", 3: "cc_NZ", 4: "cc_V", 5: "cc_NV",
      6: "cc_N", 7: "cc_NN", 8: "cc_C", 9: "cc_NC", 0xA: "cc_SGT", 0xB: "cc_SLE",
      0xC: "cc_SLT", 0xD: "cc_SGE", 0xE: "cc_UGT", 0xF: "cc_ULE"}
COLA = {0: "BFLDL", 1: "BFLDH", 2: "BCMP", 3: "BMOVN", 4: "BMOV", 5: "BOR", 6: "BAND", 7: "BXOR"}
COLB = {0: "MUL", 1: "MULU", 2: "PRIOR", 4: "DIV", 5: "DIVU", 6: "DIVL", 7: "DIVLU"}
COLC = {0: "ROL", 1: "ROL", 2: "ROR", 3: "ROR", 4: "SHL", 5: "SHL", 6: "SHR", 7: "SHR"}

def is4(op):
    return (op & 0x0F) in (2, 3, 4, 5, 6, 7, 0xA)

def seg_off_to_file(seg, off):
    if seg in (0, 0x80):
        return off & 0xFFFF
    return (seg - 0x80) * 0x10000 + (off & 0xFFFF)

def imm16(b, o):
    return b[o] | (b[o + 1] << 8)

# ---- main decoder -----------------------------------------------------------
def decode(b, fo, esfr=False):
    """Return (length, text) for the instruction at file offset fo.

    `esfr` says whether an EXTR prefix is in force for THIS instruction. The
    caller is responsible for tracking the window - see disassemble().
    """
    global _ESFR_ACTIVE
    _ESFR_ACTIVE = esfr
    op = b[fo]
    n = 4 if is4(op) else 2
    b1 = b[fo + 1] if fo + 1 < len(b) else 0
    lo = b[fo + 2] if fo + 2 < len(b) else 0
    hi = b[fo + 3] if fo + 3 < len(b) else 0
    col = op & 0x0F
    row = op >> 4

    # arithmetic rows 0-7
    if row <= 7 and col <= 9:
        m = ARITH[row]
        byte = (col % 2 == 1)
        if byte:
            m += "B"
        c = col & 0xE
        if c == 0:   # reg,reg
            return n, "%-6s %s, %s" % (m, regname(0xF0 + (b1 >> 4), byte), regname(0xF0 + (b1 & 0xF), byte))
        if c == 2:   # reg, mem
            return n, "%-6s %s, %s" % (m, regname(b1, byte), memname(imm16(b, fo + 2)))
        if c == 4:   # mem, reg
            return n, "%-6s %s, %s" % (m, memname(imm16(b, fo + 2)), regname(b1, byte))
        if c == 6:   # reg, #data
            return n, "%-6s %s, #%04Xh" % (m, regname(b1, byte), imm16(b, fo + 2))
        if c == 8:
            # THE SHORT 4-BIT OPERAND, AND ITS THREE MODES ARE NOT ONE MODE.
            # byte 2 is nnnn:mmmm; mmmm selects 0iii = #data3, 10ii = [Rwi],
            # 11ii = [Rwi+].  This branch used to render every one of them as
            # [Rwi], so the firmware's own "ADD R1,#2" pointer walk printed as
            # "ADD R1,[R2]" and "CMP R2,#0" as "CMP R2,[R0]".  Ground truth is
            # A166 itself: ADD R1,#2 assembles to 08 12 and ADD R1,[R2] to
            # 08 1A.  Lengths are equal, so no scan ever desynchronised - but
            # a project whose rule is READ THE COMPILER'S OWN ASSEMBLY cannot
            # keep a disassembler that renames the operand.
            lo4 = b1 & 0xF
            dst = regname(0xF0 + (b1 >> 4), byte)
            if lo4 & 0x8:
                src = "[%s%s]" % (regname(0xF0 + (lo4 & 3)),
                                  "+" if lo4 & 0x4 else "")
            else:
                src = "#%Xh" % (lo4 & 7)
            return n, "%-6s %s, %s" % (m, dst, src)
    if row <= 7 and col == 0xA:   # bit-field / bit-bit ops
        return n, "%-6s bitoff_%02X, #%02Xh, #%02Xh" % (COLA[row], b1, lo, hi)
    if row <= 7 and col == 0xB:
        return n, "%-6s R%d, R%d" % (COLB.get(row, "?"), b1 >> 4, b1 & 0xF)
    if row <= 7 and col == 0xC:
        if row % 2:  # shift by immediate: Rn=b1&0xF, count=b1>>4
            return n, "%-6s R%d, #%Xh" % (COLC[row], b1 & 0xF, b1 >> 4)
        return n, "%-6s R%d, R%d" % (COLC[row], b1 >> 4, b1 & 0xF)
    if col == 0xD:   # JMPR cc, rel
        rel = b1 - 256 if b1 > 127 else b1
        tgt = fo + n + 2 * rel
        return n, "%-6s %s, 0x%06X" % ("JMPR", CC[row], tgt)
    if col == 0xE:   # BCLR
        return n, "%-6s %s" % ("BCLR", bitoffname(b1, row))
    if col == 0xF:   # BSET
        return n, "%-6s %s" % ("BSET", bitoffname(b1, row))

    # rows 8-F explicit
    if op in (0x80, 0x90, 0xA0, 0xB0):
        mm = {0x80: "CMPI1", 0x90: "CMPI2", 0xA0: "CMPD1", 0xB0: "CMPD2"}[op]
        return n, "%-6s R%d, #%Xh" % (mm, b1 >> 4, b1 & 0xF)
    if op in (0x82, 0x92, 0xA2, 0xB2):
        mm = {0x82: "CMPI1", 0x92: "CMPI2", 0xA2: "CMPD1", 0xB2: "CMPD2"}[op]
        return n, "%-6s %s, %s" % (mm, regname(b1), memname(imm16(b, fo + 2)))
    if op in (0x86, 0x96, 0xA6, 0xB6):
        mm = {0x86: "CMPI1", 0x96: "CMPI2", 0xA6: "CMPD1", 0xB6: "CMPD2"}[op]
        return n, "%-6s %s, #%04Xh" % (mm, regname(b1), imm16(b, fo + 2))
    if op == 0x91: return n, "%-6s R%d" % ("CPL", b1 >> 4)
    if op == 0xB1: return n, "%-6s %s" % ("CPLB", regname(0xF0 + (b1 >> 4), True))
    if op == 0x88: return n, "%-6s [-R%d], R%d" % ("MOV", b1 & 0xF, b1 >> 4)
    if op == 0x89: return n, "%-6s [-R%d], %s" % ("MOVB", b1 & 0xF, regname(0xF0 + (b1 >> 4), True))
    if op == 0x98: return n, "%-6s R%d, [R%d+]" % ("MOV", b1 >> 4, b1 & 0xF)
    if op == 0x99: return n, "%-6s %s, [R%d+]" % ("MOVB", regname(0xF0 + (b1 >> 4), True), b1 & 0xF)
    if op == 0xA8: return n, "%-6s R%d, [R%d]" % ("MOV", b1 >> 4, b1 & 0xF)
    if op == 0xA9: return n, "%-6s %s, [R%d]" % ("MOVB", regname(0xF0 + (b1 >> 4), True), b1 & 0xF)
    if op == 0xB8: return n, "%-6s [R%d], R%d" % ("MOV", b1 & 0xF, b1 >> 4)
    if op == 0xB9: return n, "%-6s [R%d], %s" % ("MOVB", b1 & 0xF, regname(0xF0 + (b1 >> 4), True))
    if op == 0xC8: return n, "%-6s [R%d], [R%d]" % ("MOV", b1 >> 4, b1 & 0xF)
    if op == 0xD8: return n, "%-6s [R%d+], [R%d]" % ("MOV", b1 >> 4, b1 & 0xF)
    if op == 0xE8: return n, "%-6s [R%d], [R%d+]" % ("MOV", b1 >> 4, b1 & 0xF)
    if op == 0xC4: return n, "%-6s [R%d+#%04Xh], R%d" % ("MOV", b1 & 0xF, imm16(b, fo + 2), b1 >> 4)
    if op == 0xD4: return n, "%-6s R%d, [R%d+#%04Xh]" % ("MOV", b1 >> 4, b1 & 0xF, imm16(b, fo + 2))
    if op == 0xE4: return n, "%-6s [R%d+#%04Xh], %s" % ("MOVB", b1 & 0xF, imm16(b, fo + 2), regname(0xF0 + (b1 >> 4), True))
    if op == 0xF4: return n, "%-6s %s, [R%d+#%04Xh]" % ("MOVB", regname(0xF0 + (b1 >> 4), True), b1 & 0xF, imm16(b, fo + 2))
    if op == 0x84: return n, "%-6s [R%d], %s" % ("MOV", b1 & 0xF, memname(imm16(b, fo + 2)))
    if op == 0x94: return n, "%-6s %s, [R%d]" % ("MOV", memname(imm16(b, fo + 2)), b1 & 0xF)
    if op == 0xF0: return n, "%-6s R%d, R%d" % ("MOV", b1 >> 4, b1 & 0xF)
    if op == 0xF1: return n, "%-6s %s, %s" % ("MOVB", regname(0xF0 + (b1 >> 4), True), regname(0xF0 + (b1 & 0xF), True))
    if op == 0xE0: return n, "%-6s R%d, #%Xh" % ("MOV", b1 & 0xF, b1 >> 4)
    if op == 0xE1: return n, "%-6s %s, #%Xh" % ("MOVB", regname(0xF0 + (b1 & 0xF), True), b1 >> 4)
    if op == 0xE6: return n, "%-6s %s, #%04Xh" % ("MOV", regname(b1), imm16(b, fo + 2))
    if op == 0xE7: return n, "%-6s %s, #%02Xh" % ("MOVB", regname(b1, True), lo)
    if op == 0xF2: return n, "%-6s %s, %s" % ("MOV", regname(b1), memname(imm16(b, fo + 2)))
    if op == 0xF6: return n, "%-6s %s, %s" % ("MOV", memname(imm16(b, fo + 2)), regname(b1))
    if op == 0xF3: return n, "%-6s %s, %s" % ("MOVB", regname(b1, True), memname(imm16(b, fo + 2)))
    if op == 0xF7: return n, "%-6s %s, %s" % ("MOVB", memname(imm16(b, fo + 2)), regname(b1, True))
    if op == 0xC0: return n, "%-6s R%d, %s" % ("MOVBZ", b1 >> 4, regname(0xF0 + (b1 & 0xF), True))
    if op == 0xD0: return n, "%-6s R%d, %s" % ("MOVBS", b1 >> 4, regname(0xF0 + (b1 & 0xF), True))
    if op == 0xC2: return n, "%-6s %s, %s" % ("MOVBZ", regname(b1), memname(imm16(b, fo + 2)))
    if op == 0xD2: return n, "%-6s %s, %s" % ("MOVBS", regname(b1), memname(imm16(b, fo + 2)))
    if op == 0xC5: return n, "%-6s %s, %s" % ("MOVBZ", memname(imm16(b, fo + 2)), regname(b1, True))
    if op == 0xD5: return n, "%-6s %s, %s" % ("MOVBS", memname(imm16(b, fo + 2)), regname(b1, True))
    if op == 0xC6: return n, "%-6s %s, #%04Xh" % ("SCXT", regname(b1), imm16(b, fo + 2))
    if op == 0xD6: return n, "%-6s %s, %s" % ("SCXT", regname(b1), memname(imm16(b, fo + 2)))
    if op in (0x8A, 0x9A, 0xAA, 0xBA):
        mm = {0x8A: "JB", 0x9A: "JNB", 0xAA: "JBC", 0xBA: "JNBS"}[op]
        rel = lo - 256 if lo > 127 else lo
        tgt = fo + n + 2 * rel
        return n, "%-6s %s, 0x%06X" % (mm, bitoffname(b1, hi >> 4), tgt)
    if op == 0xCA:  # CALLA cc, caddr
        return n, "%-6s %s, 0x%06X" % (
            "CALLA", CC[b1 >> 4], seg_off_to_file(_cur_seg, imm16(b, fo + 2)))
    if op == 0xEA:  # JMPA cc, caddr
        return n, "%-6s %s, 0x%06X" % ("JMPA", CC[b1 >> 4], seg_off_to_file(_cur_seg, imm16(b, fo + 2)))
    if op == 0xDA:  # CALLS seg, caddr
        return n, "%-6s 0x%02X, 0x%06X" % ("CALLS", b1, seg_off_to_file(b1, imm16(b, fo + 2)))
    if op == 0xFA:  # JMPS seg, caddr
        return n, "%-6s 0x%02X, 0x%06X" % ("JMPS", b1, seg_off_to_file(b1, imm16(b, fo + 2)))
    if op == 0xBB:  # CALLR rel
        rel = b1 - 256 if b1 > 127 else b1
        return n, "%-6s 0x%06X" % ("CALLR", fo + n + 2 * rel)
    if op == 0x9B: return n, "%-6s #%02Xh" % ("TRAP", b1 >> 1)
    if op == 0xAB: return n, "%-6s %s, [R%d]" % ("CALLI", CC[b1 >> 4], b1 & 0xF)
    if op == 0x9C:
        rel = b1  # JMPI cc,[Rwn]
        return n, "%-6s %s, [R%d]" % ("JMPI", CC[b1 >> 4], b1 & 0xF)
    if op == 0xCB: return n, "RET"
    if op == 0xDB: return n, "RETS"
    if op == 0xFB: return n, "RETI"
    if op == 0xEB: return n, "%-6s R%d" % ("RETP", b1 & 0xF)
    if op == 0xEC: return n, "%-6s R%d" % ("PUSH", b1 & 0xF) if b1 >= 0xF0 or True else ("PUSH", regname(b1))
    if op == 0xEC: return n, "%-6s %s" % ("PUSH", regname(b1))
    if op == 0xFC: return n, "%-6s %s" % ("POP", regname(b1))
    if op == 0xCC: return n, "NOP"
    if op == 0xCD: return n, "?cd"
    if op == 0xD1:
        b1x = b[fo + 1]
        irang = (b1x >> 4) & 3
        atomic = (b1x & 0xC0) == 0
        return n, ("%-6s #%d" % ("ATOMIC" if atomic else "EXTR", irang + 1))
    if op == 0xD7:
        return n, "%-6s #%04Xh, #%d" % ("EXTP/S", imm16(b, fo + 2), ((b1 >> 4) & 3) + 1)
    if op == 0xDC:
        return n, "%-6s R%d, #%d" % ("EXTP/S", b1 & 0xF, ((b1 >> 4) & 3) + 1)
    if op == 0x87: return n, "IDLE"
    if op == 0x97: return n, "PWRDN"
    if op == 0xA5: return n, "DISWDT"
    if op == 0xA7: return n, "SRVWDT"
    if op == 0xB5: return n, "EINIT"
    if op == 0xB7: return n, "SRST"
    # fallback
    raw = " ".join("%02X" % b[fo + i] for i in range(n))
    return n, "DB     %s   ; op %02X" % (raw, op)


_cur_seg = 0x80  # segment context for relative caddr decoding


def disassemble(b, start_fo, count, seg):
    global _cur_seg
    _cur_seg = seg
    fo = start_fo
    out = []
    # EXTR window. The prefix says how many FOLLOWING instructions resolve
    # short register fields into ESFR space. Tracking it is not optional: the
    # same encoding names a different register inside the window, and the
    # rendered text gives no hint which one it was.
    esfr_left = 0
    for _ in range(count):
        if fo >= len(b):
            break
        n, txt = decode(b, fo, esfr=esfr_left > 0)
        if esfr_left:
            esfr_left -= 1
            txt += "        ; ESFR"
        if b[fo] == 0xD1 and (b[fo + 1] & 0xC0) != 0:      # EXTR, not ATOMIC
            esfr_left = ((b[fo + 1] >> 4) & 3) + 1
        raw = " ".join("%02X" % b[fo + i] for i in range(n))
        log = fo + 0x800000
        out.append("0x%06X (seg%02X:%04X) %-12s  %s" % (fo, (log >> 16) & 0xFF, log & 0xFFFF, raw, txt))
        fo += n
    return "\n".join(out)


def validate(b):
    # Disassemble the startup at 0x76CC; eyeball against IDA's known decode.
    print("=== VALIDATION: file 0x76CC (IDA decoded this; mnemonics must match) ===")
    print(disassemble(b, 0x76CC, 30, 0x80))
    print("\n  Expected (IDA): mov CP,#0F740h ; mov BUSCON0,#48Ch ; jnb ROMEN,.. ;")
    print("                  mov SYSCON,#0E644h ; jmpr ; mov SYSCON,#0E244h ; ...")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("start", nargs="?", help="file offset (hex ok) or, with --seg, the in-seg offset")
    ap.add_argument("count", nargs="?", type=lambda x: int(x, 0), default=40)
    ap.add_argument("--seg", type=lambda x: int(x, 0), default=None, help="segment (0x80-0x8A); start is then in-seg offset")
    ap.add_argument("--image", type=Path, default=BIN, help="binary image to disassemble (default: bench original)")
    ap.add_argument("--validate", action="store_true")
    a = ap.parse_args()
    b = a.image.read_bytes()
    if a.validate:
        validate(b)
        return
    if a.start is None:
        ap.error("need start offset (or --validate)")
    if a.seg is not None:
        fo = seg_off_to_file(a.seg, int(a.start, 0))
        seg = a.seg
    else:
        fo = int(a.start, 0)
        seg = ((fo + 0x800000) >> 16) & 0xFF
    print(disassemble(b, fo, a.count, seg))


if __name__ == "__main__":
    main()
