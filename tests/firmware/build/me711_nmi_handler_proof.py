#!/usr/bin/env python3
"""Execute the linked V49 NMI handler against a real C167 interrupt frame.

The static V49 gate checks opcode shape and store ordering.  This proof checks
the part that text cannot settle: the C167 hardware-frame offsets, register
bank capture, balanced system stack and RETI restoration in the final image.
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
LF = 0x386900
RESET_TRAP = 0x38240A
RESET_TRAP_MS = 0x382440
VALID, ARMED, STARTED, COMPLETE, FROZEN = 0x8000, 1, 4, 8, 0x40
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
    handler = symbol("hc_v02", "LABEL")
    tick = symbol("hc_tick_ms", "VAR")
    asic = symbol("hc_asic_state", "VAR")
    mem = C167.Mem(image)
    cpu = C167.CPU(mem, handler >> 16, handler & 0xFFFF)

    # State at the instant after C167 hardware entry.  The hardware has pushed
    # PSW, CSP and IP, leaving IP at [SP], CSP at [SP+2] and PSW at [SP+4].
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

    # A valid armed record and distinct boundary values make accidental zero
    # captures visible.  Native retained words are little endian in SRAM.
    header = [0x4843, 0x4C46, 0x0049, 344, VALID | ARMED]
    for i, value in enumerate(header):
        mem.w16(LF + i * 2, value)
    mem.w16(LF + 24 * 2, 0x0037)   # command sequence
    mem.w16(0x386874, 0x0701)      # owner/admission packed word
    mem.w16(0x386804, 0x0400)      # CB state/phase packed word
    mem.w16(0x386812, 0x2C00)      # big-endian CB_POS=44 as native word
    mem.w16(tick, 0x93AF)
    mem.w8(asic, 7)
    fast_active = symbol("hc_lf_fast_active", "VAR")
    mem.w8(fast_active, 1)

    trap = None
    for _ in range(800):
        try:
            cpu.step()
        except C167.Trap as exc:
            trap = str(exc)
            break
        if (cpu.csp, cpu.ip) == (interrupted_csp, interrupted_ip):
            break

    words = [mem.r16(LF + 2 * i) for i in range(172)]
    returned = (cpu.csp, cpu.ip) == (interrupted_csp, interrupted_ip)
    check("linked NMI handler executes to RETI", trap is None and returned,
          trap or f"PC={cpu.csp:02X}:{cpu.ip:04X}")
    check("start and completion markers bracket a complete snapshot",
          words[96] == 0x4E31 and words[97] == 0x4E32
          and words[4] & (STARTED | COMPLETE | FROZEN)
          == STARTED | COMPLETE | FROZEN)
    check("hardware interrupt-frame offsets capture IP, CSP and PSW",
          words[104:107] == [interrupted_ip, interrupted_csp, interrupted_psw],
          "got=" + ",".join(f"{x:04X}" for x in words[104:107]))
    check("all sixteen interrupted general registers are captured exactly",
          words[126:142] == bank)
    check("RETI restores the system stack and original processor context",
          mem.sfr[0xFE12] == entry_sp + 6
          and mem.sfr[0xFF10] == (interrupted_psw & 0xFFF0)
          and cpu.c == ((interrupted_psw >> 1) & 1)
          and (cpu.csp, cpu.ip) == (interrupted_csp, interrupted_ip),
          f"SP={mem.sfr[0xFE12]:04X} PSW={mem.sfr[0xFF10]:04X} "
          f"PC={cpu.csp:02X}:{cpu.ip:04X}")
    check("handler restores its R1-R4 scratch registers",
          [cpu.gr(i) for i in range(1, 5)] == bank[1:5])
    check("first NMI disables subsequent ISR fast stamps",
          mem.r8(fast_active) == 0)
    check("snapshot captures transaction position, runtime state and command",
          words[122:126] == [0x0701, 0x0400, 0x2C00, 7]
          and words[143] == 0x0037,
          "got=" + ",".join(f"{x:04X}" for x in words[122:126])
          + f",cmd={words[143]:04X}")
    # READ THEM THE WAY THE FIRMWARE READS THEM, NOT THE WAY THEY WERE WRITTEN.
    #
    # hcconfig.c's rst_u16() is RAM[off] << 8 | RAM[off + 1] - the reset log is
    # BIG-ENDIAN - while a C166 MOV stores a word little-endian. An earlier
    # version of this check used mem.r16() and so modelled both halves of the
    # interface from the same assumption: it happily confirmed a native store
    # that would have made rstPreviousTrap read 0x0200 instead of 2 and the
    # trap timestamp byte-swapped, destroying comparability with the V48
    # PHYSICAL numbers (trap 2 at 37807 ms) this whole build exists to extend.
    def rst_u16(addr: int) -> int:
        return (mem.r8(addr) << 8) | mem.r8(addr + 1)

    check("RESETDIAG fields are readable by hcconfig.c's own big-endian reader",
          rst_u16(RESET_TRAP) == 2 and rst_u16(RESET_TRAP_MS) == 0x93AF,
          f"rst_u16 trap={rst_u16(RESET_TRAP):04X} "
          f"ms={rst_u16(RESET_TRAP_MS):04X} "
          f"(raw native {mem.r16(RESET_TRAP):04X}/"
          f"{mem.r16(RESET_TRAP_MS):04X}) snapTick={words[142]:04X}")
    check("and the retained snapshot keeps the tick in NATIVE order",
          words[142] == 0x93AF)

    print(f"{checks - fails}/{checks} checks pass")
    return int(bool(fails))


if __name__ == "__main__":
    raise SystemExit(main())
