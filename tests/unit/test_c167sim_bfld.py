"""c167sim must decode BFLDL and BFLDH with their own immediate order.

BFLDL op1,#mask,#data is encoded 0A QQ mask data, BFLDH op1,#mask,#data is
encoded 1A QQ data mask. The bytes below are what Keil C166 V7.53 emits for
_bfld_() (compiler listing), so they are the hardware's encoding, not ours.
Until 2026-10-08 the simulator read both as mask, data: HC_ATOMIC_ENTER's
BFLDH PSW,#0F0H,#0D0H then raised ILVL 11 to 15 instead of 13.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import c167sim as S  # noqa: E402

PSW, P2 = 0xFF10, 0xFFC0


def _run(code, psw, p2=0xFFFF):
    img = bytearray(b"\xFF" * 0x100000)
    img[0x040000:0x040000 + len(code)] = code
    m = S.Mem(bytes(img))
    c = S.CPU(m, 0x84, 0x0000)
    m.sfr[PSW] = psw
    m.sfr[P2] = p2
    c.step()
    return m


def test_bfldh_psw_raises_any_level_to_13():
    for level in range(16):
        if level >= 13:
            continue
        m = _run(bytes.fromhex("1A88D0F0"), (level << 12) | 0x0800)
        assert m.sfr[PSW] >> 12 == 13, (level, hex(m.sfr[PSW]))
        assert m.sfr[PSW] & 0x0800, "IEN must be untouched"


def test_bfldl_and_bfldh_operand_order():
    assert _run(bytes.fromhex("0AE0F030"), 0, 0xFFFF).sfr[P2] == 0xFF3F
    assert _run(bytes.fromhex("1AE0050F"), 0, 0xFFFF).sfr[P2] == 0xF5FF


if __name__ == "__main__":
    test_bfldh_psw_raises_any_level_to_13()
    test_bfldl_and_bfldh_operand_order()
    print("PASS")
