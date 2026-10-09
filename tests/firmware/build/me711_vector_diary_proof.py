#!/usr/bin/env python3
r"""me711_vector_diary_proof.py - the trap diary survived losing its call.

    py tests\firmware\build\me711_vector_diary_proof.py

WHAT CHANGED AND WHY IT NEEDED A GATE.

V55 needed 3.6 KiB of code that did not exist. NCODE on this target is a single
CGROUP and L166 refuses one over 64 KiB, so the real ceiling is 0x84FFFF - not
the 0x85BFFF linker_me711.lnp used to claim - and there were 2.9 KiB left.

The 5.6 KiB that paid for it came from hcvec_me711.c. Each of its 117
unclaimed-trap catch-alls called hc_rst_vector_at() in hcconfig.c, and a Keil
C166 `interrupt` function that calls into ANOTHER MODULE must assume the worst
about the register bank and saves all of it: 74 bytes per handler instead of
26. The module's own header had warned about exactly this since the ME7.5
target hit it first. The handlers now write the same two reset-diary words
themselves and the call never leaves the module.

TWO THINGS HAVE TO STAY TRUE, and a size win is worth nothing if either broke:

  1. THE DIARY STILL GETS WRITTEN, from inside the handler, with the tick. That
     is not decoration - the second Bosch hardware run recorded an NMI and lost
     the moment it happened, because the 10 ms progress raster never got
     another turn once the reset was on its way. So this gate ENTERS a
     catch-all in the linked image through a real interrupt frame, lets it
     RETI, and reads the external SRAM back.

  2. THE HANDLERS ARE ACTUALLY SMALL AGAIN. Measured from the linked map, and
     measured the same way against the FROZEN V54 MAP as a negative control -
     a gate that cannot see the defect it was written for is not a gate. V54's
     handlers must come out over the threshold and V55's under it.

The receive path is checked too, in both directions: while hc_s0r_learn is set
the handler is carrying serial traffic and must NOT touch the diary.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_trigger_test as T                                   # noqa: E402
import me711_image as PI                                         # noqa: E402

FAIL = 0

TGT = (ROOT / "firmware/targets/me711/hctarget.h").read_text(errors="replace")
CFGH = (ROOT / "firmware/config/hcconfig.h").read_text(errors="replace")


def hexdef(txt, name):
    m = re.search(r"#define\s+%s\s+0x([0-9A-Fa-f]+)" % name, txt)
    if not m:
        raise SystemExit("missing %s" % name)
    return int(m.group(1), 16)


def decdef(txt, name):
    m = re.search(r"#define\s+%s\s+(\d+)u?\b" % name, txt)
    if not m:
        raise SystemExit("missing %s" % name)
    return int(m.group(1))


EXTRAM = hexdef(TGT, "TGT_EXTRAM_BASE")
RAM_CFG = hexdef(TGT, "TGT_RAM_CFG")
RSTLOG = hexdef(TGT, "TGT_RAM_RSTLOG")
RST_TRAP = decdef(CFGH, "RST_TRAP")
RST_TRAP_MS = decdef(CFGH, "RST_TRAP_MS")
DIARY = EXTRAM + RAM_CFG + RSTLOG

# The handler under test: an ordinary unclaimed trap - not the NMI, not a
# capture, not the serial receive, not one the firmware claims - so it is a
# catch-all and nothing else in the image references it. 0x30 until V97 made
# it the knock window (CC16); since 2026-10-06 the catch-alls are the
# assembly stubs of generated/hcvecstub_me711.a66 (tools/build/gen_vector_probe.py).
VECTOR = 0x31


def check(name, ok, detail=""):
    global FAIL
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<54} {detail}")
    FAIL += not ok


def map_sym(map_text, name):
    m = re.search(r"^\s*([0-9A-F]{6})H\s+%s\b" % re.escape(name),
                  map_text, re.M)
    return int(m.group(1), 16) if m else None


def handler_bytes(map_path):
    """The size of ONE catch-all, from the linked map.

    Two consecutive generated handlers are emitted in source order and nothing
    is placed between them, so the difference of their entry addresses IS the
    size of the first. Measuring it this way needs no disassembly and no
    assumption about the prologue the compiler chose - which is the thing under
    test.
    """
    txt = Path(map_path).read_text(errors="replace")
    pairs = []
    for a, b in (("hc_v31", "hc_v32"), ("hc_v40", "hc_v41"),
                 ("hc_v60", "hc_v61")):
        lo, hi = map_sym(txt, a), map_sym(txt, b)
        if lo is not None and hi is not None and hi > lo:
            pairs.append(hi - lo)
    if not pairs:
        raise SystemExit("no adjacent catch-all pair in %s" % map_path)
    return max(pairs)


def enter_isr(x, addr, sentinel=0xFFFE, saved_psw=0, saved_csp=None):
    """Enter an `interrupt` function the way the CPU does, and let it RETI.

    The C167 pushes PSW, then CSP, then IP. RETI pops them back in that order,
    so a sentinel IP on top of a frame we built ourselves is what stops the
    run - the same trick the ordinary call rig uses, one frame deeper.
    """
    x.m.w16(x.c.cp(), x.stack_top)
    x.m.sfr[0xFE14], x.m.sfr[0xFE16] = 0xF200, 0xFE00
    sp = 0xF700
    for w in (saved_psw, addr >> 16 if saved_csp is None else saved_csp, sentinel):     # PSW, CSP, IP
        sp = (sp - 2) & 0xFFFF
        x.m.w16(sp, w)
    x.m.sfr[0xFE12] = sp
    x.c.csp, x.c.ip = addr >> 16, addr & 0xFFFF
    before = x.c.steps
    for _ in range(20000):
        if x.c.ip == sentinel:
            return x.c.steps - before
        x.c.step()
    raise SystemExit("catch-all 0x%02X did not return" % VECTOR)


def diary_u16(x, off):
    a = DIARY + off
    return (x.m.r8(a) << 8) | x.m.r8(a + 1)


def wipe(x):
    for i in range(4):
        x.m.w8(DIARY + RST_TRAP + i, 0)
        x.m.w8(DIARY + RST_TRAP_MS + i, 0)


def main():
    print("=== the unclaimed-trap diary, entered through a real frame ===\n")
    addr = T.sym("hc_v%02X" % VECTOR)

    # ---- 1. the diary is written, from inside the handler ------------------
    x = T.Call()
    x.m.w16(T.sym("hc_tick_ms") & 0xFFFF, 0x1234)
    x.m.w8(T.sym("hc_s0r_learn") & 0xFFFF, 0)
    x.m.w8(T.sym("hc_s0r_trap") & 0xFFFF, 0xFF)   # not this vector
    x.m.w16(T.sym("hc_badvec") & 0xFFFF, 0)
    x.m.w16(T.sym("hc_firstvec") & 0xFFFF, 0)
    x.m.w16(T.sym("hc_lastvec") & 0xFFFF, 0)
    wipe(x)
    steps = enter_isr(x, addr)

    check("the catch-all entered and returned through RETI", steps > 0,
          f"{steps} emulated instructions")
    check("the trap number reached the diary",
          diary_u16(x, RST_TRAP) == VECTOR,
          f"RST_TRAP={diary_u16(x, RST_TRAP):#06x}, want {VECTOR:#06x}")
    check("and it is TIMESTAMPED with the millisecond tick",
          diary_u16(x, RST_TRAP_MS) == 0x1234,
          f"RST_TRAP_MS={diary_u16(x, RST_TRAP_MS):#06x}")
    check("the published counters moved with it",
          x.m.r16(T.sym("hc_badvec") & 0xFFFF) == 1
          and x.m.r16(T.sym("hc_firstvec") & 0xFFFF) == VECTOR
          and x.m.r16(T.sym("hc_lastvec") & 0xFFFF) == VECTOR,
          f"bad={x.m.r16(T.sym('hc_badvec') & 0xFFFF)} "
          f"first={x.m.r16(T.sym('hc_firstvec') & 0xFFFF)} "
          f"last={x.m.r16(T.sym('hc_lastvec') & 0xFFFF)}")

    # Exercise every linked assembly entry with a distinct register pattern.
    # A different interrupted code segment detects near/far frame confusion;
    # nonzero flags and priority detect a RETI that only restores part of PSW.
    asm = (ROOT / "firmware/targets/me711/generated/hcvecstub_me711.a66").read_text()
    vectors = sorted({int(v, 16) for v in re.findall(r"PUBLIC\s+hc_v([0-9A-F]{2})", asm)} | {0x7F})
    contract_errors = []
    for vector in vectors:
        z = T.Call()
        z.m.w16(T.sym("hc_tick_ms") & 0xFFFF, 0x2468)
        z.m.w8(T.sym("hc_s0r_learn") & 0xFFFF, 0)
        z.m.w8(T.sym("hc_s0r_trap") & 0xFFFF, 0xFF)
        z.m.w16(T.sym("hc_badvec") & 0xFFFF, 0)
        wipe(z)
        cp = z.c.cp()
        registers = [z.stack_top] + [((vector * 257 + r * 0x123) & 0xFFFF) for r in range(1, 16)]
        for r, value in enumerate(registers):
            z.m.w16(cp + 2 * r, value)
        special = {0xFE0C: 0xA55A, 0xFE0E: 0x5AA5, 0xFF0E: 0x0012}
        for a, value in special.items():
            z.m.w16(a, value)
        enter_isr(z, T.sym("hc_v%02X" % vector), saved_psw=0xA90B, saved_csp=0x83)
        z.c.psw_compose()
        ok = ([z.m.r16(cp + 2 * r) for r in range(16)] == registers
              and all(z.m.r16(a) == value for a, value in special.items())
              and z.m.sfr[0xFE12] == 0xF700 and z.c.cp() == cp
              and z.c.csp == 0x83 and z.m.sfr[z.c.PSW_ADDR] == 0xA90B
              and diary_u16(z, RST_TRAP) == vector
              and diary_u16(z, RST_TRAP_MS) == 0x2468)
        if not ok:
            contract_errors.append(hex(vector))
    check("every compact stub preserves the full interrupted context",
          bool(vectors) and not contract_errors,
          "%d entries; failures %s" % (len(vectors), contract_errors or "none"))

    # ---- 2. control: it writes the diary for THIS reason, not always -------
    y = T.Call()
    y.m.w16(T.sym("hc_tick_ms") & 0xFFFF, 0x5678)
    y.m.w8(T.sym("hc_s0r_learn") & 0xFFFF, 1)     # the receive-probe path
    y.m.w8(T.sym("hc_s0r_trap") & 0xFFFF, 0)
    y.m.w16(T.sym("hc_badvec") & 0xFFFF, 0)
    wipe(y)
    enter_isr(y, addr)
    check("while LEARNING the serial vector, the diary is untouched",
          diary_u16(y, RST_TRAP) == 0 and diary_u16(y, RST_TRAP_MS) == 0
          and y.m.r16(T.sym("hc_badvec") & 0xFFFF) == 0,
          f"trap={diary_u16(y, RST_TRAP):#06x} "
          f"bad={y.m.r16(T.sym('hc_badvec') & 0xFFFF)}")
    check("and the probe learned which vector carried the byte",
          y.m.r8(T.sym("hc_s0r_trap") & 0xFFFF) == VECTOR,
          f"s0rTrap={y.m.r8(T.sym('hc_s0r_trap') & 0xFFFF):#04x}")

    # ---- 3. the size, and a negative control that must see the old one ----
    now = handler_bytes(PI.MAP)
    LIMIT = 48
    check("a catch-all is small again", now <= LIMIT,
          f"{now} bytes per handler, limit {LIMIT}")

    v54 = ROOT / "bins/hanicore/HaniCore_ME711_v54_flash_fault_exit.M66"
    if v54.exists():
        was = handler_bytes(v54)
        check("NEGATIVE CONTROL: the frozen V54 map fails this same measure",
              was > LIMIT,
              f"V54 was {was} bytes per handler - {117 * (was - now)} bytes "
              f"of SA7 recovered across 117 handlers")
    else:
        check("NEGATIVE CONTROL: the frozen V54 map is present", False,
              "no V54 map to measure against")

    print("\nall checks pass" if not FAIL else f"\n{FAIL} failure(s)")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
