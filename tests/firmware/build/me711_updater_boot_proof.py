#!/usr/bin/env python3
r"""
me711_updater_boot_proof.py - the REAL --updater image boots THROUGH the
resident loader to its own run loop, in c167sim.

    py tests\firmware\build\me711_updater_boot_proof.py [--board <board>]

me711_loader_proof.py already proves the loader's decision, copy and
power-cut recovery with a SYNTHETIC app. This proves the other half: that
the --updater build wires the real boot region, the embedded loader and the
real application together, so an untouched, sealed app boots in < 1 ms with
no flash write.

The image under test is bins/hanicore/<board stem>_updater.bin
(`py tools\build\build_hanicore_me711.py --board <b> --updater`), with its
.json manifest and .M66 map beside it.

  STATIC (the build's wiring)
    U1  the ROMSYS entry and the reset slot both jump to the LOADER (0x820200)
    U2  first-level slots 1..127 forward to seg 0x83 (the app table in SA6)
    U3  the 32-byte app header at 0x030200 is valid and names the real
        ?C_STARTUP; SA5 holds the loader bin byte for byte
    U4  the boot checksum covers SA0..SA5 (the loader) but NOT the app (SA6)

  DYNAMIC (c167sim, from the CPU reset address)
    U5  ROMEN clear: reset 00:0000 -> the loader entry -> the real ?C_STARTUP
        -> main(), with no flash write
    U6  ROMEN set (mask-ROM model): the mask ROM checks the sums and hands off
        through the loader to ?C_STARTUP
    U7  CONTROL: a broken app seal -> the loader stops, ?C_STARTUP NOT reached
    U8  CONTROL: a wrong board code -> the loader stops, ?C_STARTUP NOT reached
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))

# c167sim reads the board's memory model (the C167CR's 0xF200-0xF5FF hole) from
# HANICORE_BOARD at IMPORT time, so resolve the board and set it FIRST.
BOARD = os.environ.get("HANICORE_BOARD", "vag_me71_c4")
if "--board" in sys.argv:
    BOARD = sys.argv[sys.argv.index("--board") + 1]
os.environ["HANICORE_BOARD"] = BOARD

import hcpaths as HCP  # noqa: F401,E402
import c167sim as S  # noqa: E402
STEMS = {"porsche_me711": "HaniCore_ME711_v102_dev",
         "vag_me71_c4": "HaniCore_ME71_27T_v102_dev",
         "audi_4f_v8": "HaniCore_ME711_4F_v102_dev",
         "vag_me75_dc": "HaniCore_ME75_DC_v102_dev"}
BOARD_CODE = {"porsche_me711": 1, "vag_me71_c4": 2,
              "audi_4f_v8": 3, "vag_me75_dc": 4}
# The register bank the first-level boot code leaves at handoff. The C167CR
# mask ROM hands off with CP at 0xF740 (start_me711.a66: it clears the IRAM
# from 0xF880 UP and only then switches CP to ?C_MAINREGISTERS, so 0xF740 must
# survive the clear); the C167CS resets with CP at 0xFC00. Modelling it wrong
# lets the IRAM clear overwrite the live register bank.
RESET_CP = {"vag_me71_c4": 0xF740, "vag_me75_dc": 0xF740}.get(BOARD, 0xFC00)
IMAGE = ROOT / "bins/hanicore" / (STEMS[BOARD] + "_updater.bin")
LOADER = ROOT / "bins/hanicore" / f"HaniCore_loader_{BOARD}.bin"
MASKROM = ROOT / "bins/oem/CPU.BIN"     # the 05.xx first-level model (build uses it)
LOADER_ENTRY = 0x820200
APP_VEC_SEG = 0x83
HDR_FILE = 0x030200
WDTCON_AT_RESET = 0x0004
CHECKS = FAILS = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print(f"{'PASS' if ok else 'FAIL'} {label}" + (f"   {detail}" if detail else ""))


def jmps(seg: int, off: int) -> bytes:
    return bytes((0xFA, seg & 0xFF, off & 0xFF, (off >> 8) & 0xFF))


def u16(b, o):
    return b[o] | (b[o + 1] << 8)


def map_symbol(name: str):
    mp = IMAGE.with_suffix(".M66").read_text(errors="replace")
    m = re.search(rf"^\s*([0-9A-F]{{6}})H\s+{re.escape(name)}\b", mp, re.M)
    return int(m.group(1), 16) if m else None


def run_to(m: S.Mem, target: int, romen: bool, limit: int = 3_000_000,
           watch=None):
    """From the CPU reset address. Returns (cpu, steps, how, saw) where `saw`
    is the set of watched PCs that were passed through."""
    cpu = S.CPU(m, 0x00, 0x0000)
    for reg, v in ((0xFE10, RESET_CP), (0xFE12, 0xFC00), (0xFE14, 0xFA00),
                   (0xFE16, 0xFC00), (0xFE00, 0), (0xFE02, 1), (0xFE04, 2),
                   (0xFE06, 3)):
        m.sfr[reg] = v
    cpu.einit_done = False
    m.sfr[0xFF12] = 0xE604 if romen else 0xE204       # SYSCON.ROMEN
    m.sfr[0xFFAE] = WDTCON_AT_RESET
    saw = set()
    watch = watch or set()
    try:
        for n in range(limit):
            pc = (cpu.csp << 16) | cpu.ip
            if pc in watch:
                saw.add(pc)
            if pc == target:
                return cpu, n, "reached", saw
            cpu.step()
    except S.Trap as e:
        return cpu, n, f"trap: {e}", saw
    return cpu, limit, "step limit", saw


def continue_to(cpu: S.CPU, target: int, limit: int = 2_000_000):
    try:
        for _ in range(limit):
            if ((cpu.csp << 16) | cpu.ip) == target:
                return True, ""
            cpu.step()
    except S.Trap as e:
        return False, f"trap: {e}"
    return False, "step limit"


def main() -> int:
    if not IMAGE.exists():
        print(f"SKIP: {IMAGE.name} not built "
              f"(py tools\\build\\build_hanicore_me711.py --board {BOARD} --updater)")
        return 0
    if not LOADER.exists():
        print(f"SKIP: {LOADER.name} not built (tools/build/build_loader.py)")
        return 0
    img = IMAGE.read_bytes()
    loader = LOADER.read_bytes()
    manifest = json.loads(IMAGE.with_suffix(".json").read_text())
    startup = manifest["entry_cpu"]                 # the app's real ?C_STARTUP
    code = BOARD_CODE[BOARD]
    print(f"=== --updater boot chain, executed - {BOARD} (board code {code}) ===")
    print(f"image {IMAGE.name}  loader 0x{LOADER_ENTRY:06X}  ?C_STARTUP 0x{startup:06X}\n")

    # ---- U1/U2/U3/U4 static wiring --------------------------------------
    rom_entry = (u16(img, 0x8002) << 16) | u16(img, 0x8000)
    check("U1 ROMSYS entry jumps to the loader",
          rom_entry == LOADER_ENTRY, f"0x{rom_entry:06X}")
    # Slot 0 is a direct JMPS on the 05.xx mask-ROM boards; on the Porsche
    # family (no mask-ROM header) it enters HaniCore's ROMEN-clear prologue,
    # whose last instruction jumps to the startup - so the prologue must be
    # exactly prologue(loader entry) (me711_owned_boot.py), byte for byte.
    import me711_owned_boot as OB
    pro = OB.prologue(LOADER_ENTRY)
    direct = img[0:4] == jmps(LOADER_ENTRY >> 16, LOADER_ENTRY & 0xFFFF)
    via_pro = (img[0:4] == jmps(0x00, OB.PROLOGUE)
               and img[OB.PROLOGUE:OB.PROLOGUE + len(pro)] == pro)
    check("U1 reset slot 0 jumps to the loader",
          direct or via_pro,
          img[0:4].hex() + (" (via the prologue)" if via_pro else ""))
    bad_slots = [n for n in range(1, 128)
                 if img[n * 4:n * 4 + 4] != jmps(APP_VEC_SEG, n * 4)]
    check("U2 slots 1..127 forward to the app table seg 0x83",
          not bad_slots, f"{len(bad_slots)} wrong" if bad_slots else "127 ok")

    h = HDR_FILE
    hdr_ok = (u16(img, h) == 0x4348 and u16(img, h + 2) == 0x5041
              and u16(img, h + 4) == code and u16(img, h + 30) == 0x5AA5)
    hdr_entry = (u16(img, h + 8) << 16) | u16(img, h + 6)
    check("U3 app header valid (HCAP, board, seal) and names ?C_STARTUP",
          hdr_ok and hdr_entry == startup,
          f"entry 0x{hdr_entry:06X}, len 0x{u16(img, h+12) << 16 | u16(img, h+10):X}")
    check("U3 SA5 holds the loader bin byte for byte",
          img[0x020000:0x030000] == loader, "")

    # the bootsum header: second range limit is SA5's top, not the app's
    r2_limit = int.from_bytes(img[0x8014:0x8018], "little")
    check("U4 boot checksum stops at SA5 (0x82FFFF); the app is outside it",
          r2_limit == 0x0082FFFF, f"0x{r2_limit:06X}")

    # ---- U5 ROMEN clear: reset -> loader -> ?C_STARTUP -> main() ---------
    main_addr = map_symbol("main")
    m = S.Mem(img)
    # garbage in the on-chip RAM, so "reaches ?C_STARTUP with RAM clean" is not
    # vacuous; skip the C167CR hole (0xF200-0xF5FF is unmapped on the 2.7T/DC)
    for a in (list(range(0xE000, 0xE800)) + list(range(0xF200, 0xFC00))
              + list(range(0xFC20, 0xFE00))):
        try:
            m.w8(a, 0xA5)
        except S.Trap:
            pass
    w0 = len(m.flash_writes)
    cpu, n, how, saw = run_to(m, startup, romen=False, watch={LOADER_ENTRY})
    check("U5 ROMEN clear: reset reaches ?C_STARTUP through the loader",
          how == "reached" and LOADER_ENTRY in saw,
          f"{how} after {n} instr, loader {'seen' if LOADER_ENTRY in saw else 'MISSED'}")
    check("U5 no flash write on the normal boot",
          len(m.flash_writes) == w0, f"{len(m.flash_writes) - w0} writes")
    if main_addr is not None and how == "reached":
        ok, why = continue_to(cpu, main_addr)
        check("U5 the startup reaches main()", ok, f"main 0x{main_addr:06X} {why}")

    # ---- U6 ROMEN set: the mask-ROM model hands off through the loader ---
    if not MASKROM.exists():
        print(f"SKIP U6 ROMEN-set model: no {MASKROM} (bins/README.md)")
    else:
        rom = MASKROM.read_bytes()[:0x8000]

        def masked(image: bytes) -> S.Mem:
            mm = S.Mem(image)
            base = mm.r8

            def r8(a, _b=base):
                a &= 0xFFFFFF
                return rom[a] if a < 0x8000 else _b(a)
            mm.r8 = r8
            return mm

        _, n, how, saw = run_to(masked(img), startup, romen=True,
                                watch={LOADER_ENTRY})
        check("U6 ROMEN set: mask ROM hands off through the loader to ?C_STARTUP",
              how == "reached" and LOADER_ENTRY in saw,
              f"{how} after {n} instr")

    # ---- U7/U8 controls: a bad app must NOT reach the app ----------------
    bad = bytearray(img)
    bad[HDR_FILE + 30] = 0x00                        # break the app seal
    _, _, how, _ = run_to(S.Mem(bytes(bad)), startup, romen=False, limit=400_000)
    check("U7 CONTROL: a broken app seal does not reach ?C_STARTUP",
          how != "reached", how)

    bad = bytearray(img)
    bad[HDR_FILE + 4] = (code % 4) + 1               # wrong board code
    _, _, how, _ = run_to(S.Mem(bytes(bad)), startup, romen=False, limit=400_000)
    check("U8 CONTROL: a wrong board code does not reach ?C_STARTUP",
          how != "reached", how)

    print(f"\n{CHECKS - FAILS}/{CHECKS} checks passed")
    if FAILS:
        print("UPDATER BOOT PROOF FAILS")
        return 1
    print("UPDATER BOOT PROOF PASSES - the real image boots through the real loader.")
    print("NOT PHYSICALLY VERIFIED: no --updater image has run on an ECU.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
