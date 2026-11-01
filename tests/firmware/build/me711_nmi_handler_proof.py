#!/usr/bin/env python3
"""Execute the linked NMI handler against a real C167 interrupt frame.

hc_nmi_isr (hcmain_me711.c, since 2026-10-28; the V49 snapshot handler is
retired) writes trap 2 and the tick into the reset log in hcconfig.c's
big-endian order and returns. This checks it in the linked image: the two
fields as rst_u16() reads them, the registers and the system stack restored,
RETI back to the interrupted code.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import c167sim as C167  # noqa: E402
import me711_image as IMG  # noqa: E402

MAP_TEXT = IMG.MAP.read_text()
RESET_TRAP = 0x38240A
RESET_TRAP_MS = 0x382440
checks = fails = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global checks, fails
    checks += 1
    fails += not ok
    suffix = ("  " + detail) if detail else ""
    print(("PASS" if ok else "FAIL"), name + suffix)


def symbol(name: str, kind: str) -> int:
    m = re.search(r"^\s*([0-9A-F]{6})H\s+%s\s+%s" %
                  (re.escape(name), kind), MAP_TEXT, re.M)
    if not m:
        raise SystemExit(f"{name} missing from {IMG.MAP.name}")
    return int(m.group(1), 16)


def main() -> int:
    image = IMG.image().read_bytes()
    handler = symbol("hc_nmi_isr", "LABEL")
    tick = symbol("hc_tick_ms", "VAR")
    mem = C167.Mem(image)
    cpu = C167.CPU(mem, handler >> 16, handler & 0xFFFF)

    # State at the instant after C167 hardware entry: IP at [SP], CSP at
    # [SP+2], PSW at [SP+4].
    bank = [0x1100 + i * 0x101 for i in range(16)]
    for i, value in enumerate(bank):
        cpu.sr(i, value)
    interrupted_ip, interrupted_csp, interrupted_psw = 0x1670, 0x008E, 0x0802
    entry_sp = 0xF6EA
    mem.sfr[0xFE12] = entry_sp
    mem.sfr[0xFE14] = 0xF600
    mem.sfr[0xFE16] = 0xF700
    mem.w16(entry_sp + 0, interrupted_ip)
    mem.w16(entry_sp + 2, interrupted_csp)
    mem.w16(entry_sp + 4, interrupted_psw)
    mem.sfr[0xFF10] = 0x0000       # NMI context, ordinary IRQs disabled
    # the data pages as start_me711.a66 sets them (DPP0..2 from the linker)
    for i in range(3):
        m = re.search(r"([0-9A-F]+)H\s+\?C_PAGEDPP%d" % i, MAP_TEXT)
        mem.sfr[0xFE00 + 2 * i] = int(m.group(1), 16) if m else i
    mem.sfr[0xFE06] = 3
    mem.w16(tick, 0x93AF)
    for a in (RESET_TRAP, RESET_TRAP + 1, RESET_TRAP_MS, RESET_TRAP_MS + 1):
        mem.w8(a, 0xEE)            # a stale log: the handler must overwrite it

    def rst_u16(addr: int) -> int:
        """hcconfig.c's rst_u16(): the reset log is BIG-ENDIAN."""
        return (mem.r8(addr) << 8) | mem.r8(addr + 1)

    before = (rst_u16(RESET_TRAP), rst_u16(RESET_TRAP_MS))
    trap = None
    for _ in range(200):
        try:
            cpu.step()
        except C167.Trap as exc:
            trap = str(exc)
            break
        if (cpu.csp, cpu.ip) == (interrupted_csp, interrupted_ip):
            break

    returned = (cpu.csp, cpu.ip) == (interrupted_csp, interrupted_ip)
    check("linked NMI handler executes to RETI", trap is None and returned,
          trap or f"PC={cpu.csp:02X}:{cpu.ip:04X}")
    check("control: the log held something else before the NMI",
          before == (0xEEEE, 0xEEEE))
    check("trap 2 and its time, as hcconfig.c's big-endian reader sees them",
          rst_u16(RESET_TRAP) == 2 and rst_u16(RESET_TRAP_MS) == 0x93AF,
          f"trap={rst_u16(RESET_TRAP):04X} ms={rst_u16(RESET_TRAP_MS):04X}")
    check("RETI restores the system stack and original processor context",
          mem.sfr[0xFE12] == entry_sp + 6
          and mem.sfr[0xFF10] == (interrupted_psw & 0xFFF0)
          and (cpu.csp, cpu.ip) == (interrupted_csp, interrupted_ip),
          f"SP={mem.sfr[0xFE12]:04X} PSW={mem.sfr[0xFF10]:04X} "
          f"PC={cpu.csp:02X}:{cpu.ip:04X}")
    check("every interrupted general register is restored",
          [cpu.gr(i) for i in range(16)] == bank)

    print(f"{checks - fails}/{checks} checks pass")
    return int(bool(fails))


if __name__ == "__main__":
    raise SystemExit(main())
