"""c167sim must model the overflow flag in the signed conditions.

The C166 signed branches test N xor V (cc_SLT, cc_SGE) and Z or (N xor V)
(cc_SLE, cc_SGT). Until 2026-10-14 the simulator kept no V and read N alone,
so a compare whose subtraction overflows 16 bits went the wrong way:
CMP R6,#8300H (-32000) with R6 = 3000 gives 0x88B8 - N and V both set - and
cc_SGE is TRUE on the CPU. hcaux711.c clamps its thresholds to +-32000 with
exactly that compare (me711_aux_proof G1 read 3000 rpm as -32000).
The encodings are Keil C166 V7.53's own (hcaux711.lst): 46F6xxxx CMP R6,#d16,
DD02 JMPR cc_SGE,+2.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import c167sim as S  # noqa: E402


def _cmp_branch(r6, imm, cc):
    """CMP R6,#imm ; JMPR cc,+2 words -> did it branch? (taken: IP 0x000A)"""
    code = bytes.fromhex("46F6") + imm.to_bytes(2, "little") \
        + bytes([(cc << 4) | 0x0D, 0x02]) + bytes.fromhex("CC00CC00")
    img = bytearray(b"\xFF" * 0x100000)
    img[0x040000:0x040000 + len(code)] = code
    m = S.Mem(bytes(img))
    c = S.CPU(m, 0x84, 0x0000)
    m.sfr[0xFE10] = 0xFC00                      # CP
    c.sr(6, r6)
    c.step()
    c.step()
    return c.ip == 0x000A


def signed(v):
    return v - 0x10000 if v & 0x8000 else v


def test_signed_conditions_with_overflow():
    SGT, SLE, SLT, SGE = 0xA, 0xB, 0xC, 0xD
    for a in (3000, -3000, 32000, -32000, 0, 1, -1, 0x7FFF, -0x8000):
        for b in (-32000, 32000, 0, 1, -1, 0x7FFF, -0x8000, 3000):
            x, y = a & 0xFFFF, b & 0xFFFF
            want = {SGT: a > b, SLE: a <= b, SLT: a < b, SGE: a >= b}
            for cc, w in want.items():
                got = _cmp_branch(x, y, cc)
                assert got == w, (a, b, hex(cc), got)


def test_the_hcaux711_clamp():
    # 3000 >= -32000: cc_SGE must branch (skip the clamp)
    assert _cmp_branch(3000, 0x8300, 0xD)


if __name__ == "__main__":
    test_signed_conditions_with_overflow()
    test_the_hcaux711_clamp()
    print("PASS")
