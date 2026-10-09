#!/usr/bin/env python3
"""Source-and-map shape checks on the two RELOCATED flash routines.

WHAT THIS GATE IS, AND WHAT IT IS NOT. It reads the C and the linker map. It
cannot see bus cycles, and the project rules record exactly what that costs: this file
"grepped the C for CALL and passed V40 happily" while V40 was issuing a fifth
write cycle per word that killed a bench Burn. The gate that MEASURES is
tests/firmware/persistence/me711_flash_bus_proof.py, which executes the linked image against a
modelled AM29F800BB. This one catches the coarse structural mistakes early and
cheaply, and it is kept for that and nothing more.

V53 SPLIT THE ROUTINE IN TWO. hc_nvm_payload() programs and hc_nvm_eraser()
erases, they SHARE one relocation slot, and the properties differ:

    the writer must contain NO erase command at all
    the eraser is the ONLY place an erase command may appear

so the old single "program-only" question is now asked of each separately.
"""
from __future__ import annotations
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_image as PI          # one place names the image under test
from me711_nvm_geometry import GEO  # noqa: F401  (kept for future geometry use)

SRC = (ROOT / "firmware/targets/me711/nvm/hcnvm.c").read_text()
HDR = (ROOT / "firmware/targets/me711/hctarget.h").read_text()
MAP = PI.MAP.read_text()
checks = fails = 0


def check(s, ok):
    global checks, fails
    checks += 1
    fails += not ok
    print(("PASS" if ok else "FAIL"), s)


def sym(n):
    m = re.search(r"^\s*([0-9A-F]{6})H\s+" + n + r"\s+LABEL", MAP, re.M)
    return int(m.group(1), 16) if m else 0


def body_of(name):
    return SRC[SRC.index(f"void far {name}(void)"):
               SRC.index(f"void far {name}_end(void)")]


def main():
    # THE SLOT SIZE IS DERIVED, NOT WRITTEN DOWN AGAIN. It was the literal 1024
    # until V53; the two routines now share the whole TGT_RAM_FLASHRT
    # reservation because only one is ever loaded at a time.
    m = re.search(r"#define\s+TGT_RAM_FLASHRT_LIMIT\s+(0x[0-9A-Fa-f]+)", HDR)
    slot = int(m.group(1), 16)

    pw, ew = sym("hc_nvm_payload"), sym("hc_nvm_payload_end")
    pe, ee = sym("hc_nvm_eraser"), sym("hc_nvm_eraser_end")
    wbody = body_of("hc_nvm_payload")
    ebody = body_of("hc_nvm_eraser")

    check(f"linked RAM writer fits the shared {slot}-byte relocation slot",
          0 < ew - pw <= slot)
    check(f"linked RAM eraser fits the shared {slot}-byte relocation slot",
          0 < ee - pe <= slot)

    check("writer is explicitly PROGRAM-only",
          all(x not in wbody for x in ("FL_ERASE", "FL_SECTOR", "CB_DOERASE")))
    check("eraser is the ONLY routine that issues an erase",
          "FL_ERASE_SECTOR" in ebody
          and SRC.count("FL_ERASE_SECTOR") == 2)      # the #define and this use

    # NOT A GREP OF THE SOURCE. The first version of this check searched the C
    # text for "CALL", which meant it was reading COMMENTS: the eraser failed it
    # because a comment says "would be a CALL to ?C_LMUL", and the writer passed
    # only because its comments happen not to spell the word. That is the same
    # class of mistake as grepping for an erase and calling it proof.
    #
    # So decode the LINKED IMAGE instead, linearly, with the C166 length rule
    # (4 bytes when the opcode's low nibble is in {2,3,4,5,6,7,A}, else 2), and
    # look for real call opcodes: CALLA CA, CALLI AB, CALLR BB, CALLS DA,
    # PCALL E2, TRAP 9B.
    img = PI.image().read_bytes()
    LONG = {2, 3, 4, 5, 6, 7, 0xA}
    CALL_OPS = {0xCA: "CALLA", 0xAB: "CALLI", 0xBB: "CALLR",
                0xDA: "CALLS", 0xE2: "PCALL", 0x9B: "TRAP"}

    def call_sites(lo_cpu, hi_cpu):
        lo, hi = lo_cpu - 0x800000, hi_cpu - 0x800000
        out, i = [], lo
        while i < hi:
            op = img[i]
            if op in CALL_OPS:
                out.append((0x800000 + i, CALL_OPS[op]))
            i += 4 if (op & 0x0F) in LONG else 2
        return out

    for nm, b, lo, hi in (("writer", wbody, pw, ew), ("eraser", ebody, pe, ee)):
        sites = call_sites(lo, hi)
        check(f"{nm} emits no call in the LINKED IMAGE", not sites)
        for a, k in sites[:6]:
            print(f"        {k} at 0x{a:06X}")
        check(f"every {nm} busy poll services the watchdog",
              b.count("__asm { SRVWDT }") >= 1)
        check(f"{nm} never resets the CPU",
              "__asm { SRST }" not in b)

    check("writer's data source is SRAM staging, not flash const data",
          "SRAMW(NVM_STAGE)" in wbody and "crc_tab" not in wbody)
    check("writer explicitly restores read-array and returns",
          "FL_RESET" in wbody)

    # THE ERASER'S RETURN IS THE DANGEROUS ONE. A far return is an instruction
    # fetch from the device it just left busy, so it may only return after the
    # part is readable again: either the erase finished (DQ7 true, the device
    # puts itself back in read-array mode) or it was SUSPENDED and the 20 us
    # datasheet latency waited out.
    check("eraser suspends before returning from an unfinished erase",
          "FL_ERASE_SUSPEND" in ebody
          and "HCNV_ERASE_SUSPEND_US" in ebody)
    check("eraser bounds its slice from a precomputed tick count",
          "ER_SLICETK" in ebody and "US_TO_TICKS(HCNV_ERASE_SLICE_US)" in ebody)

    print("%d/%d checks pass" % (checks - fails, checks))
    return int(bool(fails))


if __name__ == "__main__":
    raise SystemExit(main())
