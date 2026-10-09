"""c167sim must resume a preempted handler at ITS level (C167CR UM 5.2: the
pushed PSW includes ILVL and RETI restores it).

Until 2026-10-07 the simulator pushed the PSW without ILVL, so every RETI
returned to level 0: a preempted handler could be re-entered by its own
source on its own register bank (the planner "crashed" at 5000+ rpm) and
nests the CPU cannot make inflated the 2026-10-06 audit's stack figure.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import c167sim as S  # noqa: E402

CC15IC, PSW = 0xFF96, 0xFF10


def _cpu(level):
    img = bytearray(b"\xFF" * 0x100000)
    img[0x020000 + 0x1F * 4:0x020000 + 0x1F * 4 + 2] = b"\xFB\x88"   # vector: RETI
    img[0x040000:0x040010] = b"\xCC\x00" * 8                          # 84:0000 NOPs
    m = S.Mem(bytes(img))
    c = S.CPU(m, 0x84, 0x0000)
    m.sfr[PSW] = (level << 12) | 0x0800                               # ILVL, IEN
    m.sfr[CC15IC] = 0x80 | 0x40 | (12 << 2)                           # IR IE ILVL12
    m.ic_write_epoch += 1
    return c, m


def test_reti_restores_the_preempted_level():
    c, m = _cpu(9)
    c.step()                                  # takes CC15 (12) and runs its RETI
    assert c.irq_taken == 1
    assert (m.sfr[PSW] >> 12) == 9, "RETI resumed at level %d, not 9" % (m.sfr[PSW] >> 12)
    assert m.sfr[PSW] & 0x0800


def test_a_level_not_above_the_current_one_is_not_taken():
    c, m = _cpu(12)
    c.step()
    assert c.irq_taken == 0
