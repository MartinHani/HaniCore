#!/usr/bin/env python3
r"""
me711_owned_boot_proof.py - the HaniCore-owned boot region (file 0x000000-
0x01FFFF, tools/build/me711_owned_boot.py) boots, in both ROMEN cases, and
contains nothing but what the generator writes.

    py tests\firmware\build\me711_owned_boot_proof.py

Image under test: the default build, bins/hanicore/<stem>.bin
(`py tools\build\build_hanicore_me711.py`).

  1. COMPOSITION. Regenerating the region from the image's own entry pointer
     reproduces every byte of 0x000000-0x01FFFF except the two sum records the
     build computes over the whole image. So the region carries no OEM byte.
  2. ROMEN CLEAR. c167sim starts at the CPU reset address 00:0000 on the image
     itself, with garbage in on-chip RAM and a known WDTCON: it must reach
     ?C_STARTUP with T0 == WDTCON and the RAM zeroed, then reach main().
  3. ROMEN SET (needs this ECU's own OEM read, else SKIP). The internal mask
     ROM is modelled by the OEM flash copy of the boot code, mapped over CPU
     segment 0x0000-0x7FFF; everything at 0x800000+ is the HaniCore image.
     That code checks the ROMSYS header and sums and must hand off to
     ?C_STARTUP. The same model is what me711_bootsum_coverage_proof relies on
     and what the persistence work qualified on hardware.

WHY IT CANNOT PASS VACUOUSLY: two mutation controls. A sampled code word
changed in the image (sums now wrong) must NOT hand off in case 3, and a
broken reset slot must NOT reach ?C_STARTUP in case 2.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths as HCP  # noqa: E402  (puts every tools/ and tests/ module on sys.path)

import c167sim as S                                    # noqa: E402
import me711_image as PI                               # noqa: E402
import me711_owned_boot as OWNED                       # noqa: E402

IMAGE = PI.image()
DONOR = HCP.OEM_READ
WDTCON_AT_RESET = 0x0004          # a recognisable reset-flag pattern
CHECKS = FAILS = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print(f"{'PASS' if ok else 'FAIL'} {label}" + (f"   {detail}" if detail else ""))


def entry_of(img: bytes) -> int:
    return ((img[0x8002] | img[0x8003] << 8) << 16) | (img[0x8000] | img[0x8001] << 8)


def run_to(m: S.Mem, seg: int, off: int, romen: bool, target: int,
           limit: int = 400_000):
    cpu = S.CPU(m, seg, off)
    # c167sim starts in the state the boot path leaves; this is a RESET, so
    # put back the C167 reset values the boot path itself starts from.
    for reg, v in ((0xFE10, 0xFC00), (0xFE12, 0xFC00), (0xFE14, 0xFA00),
                   (0xFE16, 0xFC00), (0xFE00, 0), (0xFE02, 1), (0xFE04, 2),
                   (0xFE06, 3)):
        m.sfr[reg] = v
    cpu.einit_done = False
    m.sfr[0xFF12] = 0xE604 if romen else 0xE204       # SYSCON.ROMEN
    m.sfr[0xFFAE] = WDTCON_AT_RESET
    try:
        for n in range(limit):
            if ((cpu.csp << 16) | cpu.ip) == target:
                return cpu, n, "reached"
            cpu.step()
    except S.Trap as e:
        return cpu, n, f"trap: {e}"
    return cpu, limit, "step limit"


def main() -> int:
    if not IMAGE.exists():
        print(f"FAIL image not built: {IMAGE} (py tools\\build\\build_hanicore_me711.py)")
        return 1
    img = IMAGE.read_bytes()
    startup = entry_of(img)
    print(f"image {IMAGE.name}  ?C_STARTUP 0x{startup:06X}")

    # ---- 1. composition --------------------------------------------------
    ref = bytearray(img)
    tbl = int.from_bytes(img[0x8008:0x800C], "little") + 0x8000
    OWNED.compose(ref, startup,
                  int.from_bytes(img[tbl + 0x10:tbl + 0x14], "little"),
                  int.from_bytes(img[tbl + 0x14:tbl + 0x18], "little"),
                  int.from_bytes(img[0x8014:0x8018], "little"))
    diff = [o for o in range(OWNED.REGION_LEN) if ref[o] != img[o]
            and not (0x8038 <= o < 0x8040)]
    check("boot region == generator output (sum records excepted)", not diff,
          f"{len(diff)} differing bytes" + (f", first 0x{diff[0]:06X}" if diff else ""))
    if DONOR.exists():
        d = DONOR.read_bytes()
        same = sum(1 for o in range(OWNED.REGION_LEN)
                   if img[o] != 0xFF and img[o] == d[o])
        print(f"     info: {same} non-blank bytes coincide with the OEM read "
              "(single JMPS/MOV encodings and header pointers)")

    # ---- 2. ROMEN clear: the CPU runs the flash reset vector --------------
    m = S.Mem(img)
    for a in list(range(0xE000, 0xE800)) + list(range(0xF200, 0xFC00)) \
            + list(range(0xFC20, 0xFE00)):
        m.w8(a, 0xA5)
    cpu, n, how = run_to(m, 0x00, 0x0000, False, startup)
    check("ROMEN clear: reset 00:0000 reaches ?C_STARTUP", how == "reached",
          f"{how} after {n} instructions")
    t0 = cpu.m.r16(0xFE50)
    check("ROMEN clear: T0 holds WDTCON at reset", t0 == WDTCON_AT_RESET,
          f"T0=0x{t0:04X}")
    dirty = [a for a in list(range(0xE000, 0xE800)) + list(range(0xF200, 0xFC00))
             + list(range(0xFC20, 0xFE00)) if m.r8(a) != 0]
    check("ROMEN clear: XRAM and IRAM zeroed", not dirty,
          f"{len(dirty)} non-zero bytes")
    main_addr = PI.symbol("main") if hasattr(PI, "symbol") else None
    if main_addr is None:
        import re
        mp = IMAGE.with_suffix(".M66").read_text(errors="replace")
        mm = re.search(r"^\s*([0-9A-F]{6})H\s+main\s", mp, re.M)
        main_addr = int(mm.group(1), 16) if mm else None
    if main_addr is not None:
        c2 = cpu
        reached = False
        try:
            for _ in range(200_000):
                if ((c2.csp << 16) | c2.ip) == main_addr:
                    reached = True
                    break
                c2.step()
        except S.Trap as e:
            print(f"     trap on the way to main: {e}")
        check("ROMEN clear: the startup reaches main()", reached,
              f"main 0x{main_addr:06X}")

    bad = bytearray(img)
    bad[0:4] = b"\xFA\x00\x00\x03"          # slot 0 into blank flash
    _, _, how = run_to(S.Mem(bytes(bad)), 0x00, 0x0000, False, startup, 50_000)
    check("CONTROL: broken reset slot does not reach ?C_STARTUP",
          how != "reached", how)

    # ---- 3. ROMEN set: mask ROM modelled by the OEM boot code --------------
    if not DONOR.exists():
        print(f"SKIP ROMEN-set model: no OEM read at {DONOR} (bins/README.md)")
    else:
        rom = DONOR.read_bytes()[:0x8000]

        def masked(image: bytes) -> S.Mem:
            mm = S.Mem(image)
            base = mm.r8

            def r8(a, _b=base):
                a &= 0xFFFFFF
                if a < 0x8000:
                    return rom[a]
                return _b(a)
            mm.r8 = r8
            return mm

        _, n, how = run_to(masked(img), 0x00, 0x0000, True, startup, 3_000_000)
        check("ROMEN set: mask-ROM model hands off to ?C_STARTUP",
              how == "reached", f"{how} after {n} instructions")
        bad = bytearray(img)
        bad[0x40000] ^= 0x01                    # first word of a sampled code page
        _, _, how = run_to(masked(bytes(bad)), 0x00, 0x0000, True, startup,
                           3_000_000)
        check("CONTROL: a changed sampled word is refused (no handoff)",
              how != "reached", how)

    print(f"\n{CHECKS - FAILS}/{CHECKS} checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
