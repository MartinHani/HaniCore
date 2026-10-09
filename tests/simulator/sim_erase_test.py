#!/usr/bin/env python3
r"""
sim_erase_test.py - the simulator's own test for the V53 sector-erase model.

THE SIMULATOR NEEDS ITS OWN TESTS. Five defects in c167sim have presented as
firmware bugs in this project - MOV not setting N/Z, Rig.run() uninstalling its
own memory hooks, and three more - and each cost a day or more because the
firmware was searched first. A new device model is exactly where the sixth
would come from, so it is tested here before any gate relies on it.

What must be true of the model, and every one of these is a property of the
real Am29F800B that the reclaim depends on:

  1. an erase does not finish instantly, and until it does the WHOLE device
     answers with status - that is why the eraser runs from SRAM;
  2. the sector is PRE-PROGRAMMED to 0x00 before it is erased, so an erase cut
     short leaves it neither blank nor valid;
  3. Erase Suspend hands back a readable device for every sector except the one
     being erased - that is the whole mechanism keeping the raster alive;
  4. a suspended erase makes NO progress;
  5. Erase Resume continues it, and it completes to 0xFF;
  6. an abandoned erase leaves 0x00, which is what the firmware must recover
     from by erasing again.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import c167sim as S

CHECKS = FAILS = 0
SEC = 0x060000          # store sector 0, file offset
CPU_SEC = 0x860000


def check(label, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print(f"{'PASS' if ok else 'FAIL'} {label}" + (f"   {detail}" if detail else ""))


def mem():
    img = bytearray(b"\xFF" * 0x100000)
    # something recognisable in the sector and in a neighbour
    img[SEC:SEC + 16] = b"HCN1RECORDBYTES!"
    img[SEC + 0x10000:SEC + 0x10010] = b"NEIGHBOURSECTOR!"
    return S.Mem(bytes(img))


def erase_cmd(m, addr):
    m.w16(0x80AAAA, 0xAA)
    m.w16(0x800554, 0x55)
    m.w16(0x80AAAA, 0x80)
    m.w16(0x80AAAA, 0xAA)
    m.w16(0x800554, 0x55)
    m.w16(addr, 0x30)


def main():
    # 1 / 2 --------------------------------------------------------------
    m = mem()
    erase_cmd(m, CPU_SEC)
    check("an erase command starts an erase rather than completing one",
          m.fl_erase_sector is not None and m.fl_erase_left > 0,
          f"{m.fl_erase_left} polls of work")
    check("the sector is pre-programmed to 0x00, not blanked",
          all(m.flash[SEC + i] == 0x00 for i in range(32)))
    check("while running, EVERY sector answers with status",
          m.r16(CPU_SEC + 0x10000) == 0x0000,
          "a neighbour read returns status, so code cannot be fetched")

    # 3 ------------------------------------------------------------------
    m.w16(CPU_SEC, 0xB0)
    check("Erase Suspend is accepted", m.fl_suspended and m.fl_erase_suspends == 1)
    check("suspended: a NON-erasing sector reads real data",
          bytes(m.flash[SEC + 0x10000:SEC + 0x10010]) == b"NEIGHBOURSECTOR!"
          and m.r16(CPU_SEC + 0x10000) == 0x454E,        # 'NE' little-endian
          "this is what lets the CPU keep executing")
    check("suspended: the ERASING sector still answers with status",
          m.r16(CPU_SEC) == 0x0000)

    # 4 ------------------------------------------------------------------
    left = m.fl_erase_left
    for _ in range(500):
        m.r16(CPU_SEC)
        m.r16(CPU_SEC + 0x10000)
    check("a suspended erase makes NO progress",
          m.fl_erase_left == left, f"{left} polls still outstanding")

    # 5 ------------------------------------------------------------------
    m.w16(CPU_SEC, 0x30)
    check("Erase Resume is accepted",
          not m.fl_suspended and m.fl_erase_resumes == 1)
    spins = 0
    while m.fl_erase_sector is not None and spins < 100000:
        m.r16(CPU_SEC)
        spins += 1
    check("a resumed erase completes", m.fl_erase_sector is None,
          f"{spins} further polls")
    check("and the sector is then genuinely blank",
          all(b == 0xFF for b in m.flash[SEC:SEC + 0x10000]))
    check("exactly one completion was counted", m.fl_erase_completed == 1)

    # 6 ------------------------------------------------------------------
    m2 = mem()
    erase_cmd(m2, CPU_SEC)
    for _ in range(10):
        m2.r16(CPU_SEC)
    m2.w16(CPU_SEC, 0xB0)          # suspended and then simply abandoned
    check("an abandoned erase leaves the sector NOT blank",
          not all(b == 0xFF for b in m2.flash[SEC:SEC + 0x100]),
          "which is the state the reclaim has to recover from")
    check("and NOT a valid record either",
          bytes(m2.flash[SEC:SEC + 4]) != b"HCN1")

    # a second erase of the same sector must still work
    m2.fl_suspended = False
    m2.fl_erase_sector = None
    erase_cmd(m2, CPU_SEC)
    spins = 0
    while m2.fl_erase_sector is not None and spins < 100000:
        m2.r16(CPU_SEC)
        spins += 1
    check("re-erasing an abandoned sector succeeds",
          m2.fl_erase_sector is None
          and all(b == 0xFF for b in m2.flash[SEC:SEC + 0x1000]))

    print(f"\n{CHECKS - FAILS}/{CHECKS} checks pass")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
