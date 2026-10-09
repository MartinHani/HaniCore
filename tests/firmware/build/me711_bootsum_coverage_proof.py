#!/usr/bin/env python3
r"""
me711_bootsum_coverage_proof.py - EXECUTE the Bosch boot block and record which
addresses its program-page checksum actually samples.

WHY THIS GATE EXISTS
--------------------
V53 moved the calibration store above the bootrom's program-page record so a
reclaim erase can no longer brick the ECU. That is safe if and only if one
thing is true of the SILICON, not of our model of it:

    the boot block never reads a word inside the store,
    and it still reads every word of the HaniCore code sector.

Every other gate in this tree answers that from a Python reimplementation of
the ranges. This one does not model the ranges at all. It loads the image into
c167sim, sets the strap-pin boot-mode byte to the normal-application 0xAA,
runs the REAL descriptor loader at 0x70E2 and the REAL summing loops at
0x729E, and records every flash word the loops read.

The ranges come out of the image's own ROMSYS header, read by the image's own
boot code:

    header+0x08 -> far pointer, +0x808000 -> descriptor table (header+0x20)
    table +0x10 -> E25A:E25C   loop 1 LIMIT   (loop 1 START is hardcoded
                                               0x800000 at boot block 0x7304)
    table +0x14 -> E25E:E260   (&~1)+2 = loop 2 START
    header+0x14 ->             loop 2 LIMIT, read at 0x72D2 and nowhere else

WHY IT CANNOT PASS VACUOUSLY
----------------------------
Three mutation controls run every time. Each one moves header+0x14 and the gate
requires the MEASURED coverage to move with it. If the harness were not really
executing the boot block - or were quietly falling back on a model - a mutation
would change nothing and the control would fail.

the project rules, "two artefacts that must agree, and nothing that makes them": here
the second artefact is the ECU's own boot code, and this is the thing that
makes them agree.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import c167sim as S                                    # noqa: E402
import me711_image as PI                               # noqa: E402
from me711_nvm_geometry import GEO                     # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "build", ROOT / "tools/build/build_hanicore_me711.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)

LOADER_ENTRY = 0x70E2       # fills E24A..E260 out of the ROMSYS header
LOADER_RETS  = 0x729C
SUM_ENTRY    = 0x729E       # the two summing loops
SUM_DONE     = 0x7382       # first instruction after loop 2
BODY1        = (0x730C, 0x733C)
BODY2        = (0x734C, 0x7380)

CHECKS = FAILS = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print(f"{'PASS' if ok else 'FAIL'} {label}" + (f"   {detail}" if detail else ""))


def sampled_words(image: bytes) -> list:
    """Every flash word the REAL checksum loops read, in order."""
    m = S.Mem(image)
    m.w8(0xE2BA, 0xAA)                       # strap-pin mode: normal application

    c = S.CPU(m, 0x80, LOADER_ENTRY)
    c.m.sfr[0xFE12] = 0xF6FE                 # room for the trailing POP DPP0
    c.m.w16(0xF6FE, 0x0000)
    for _ in range(500000):
        if c.csp == 0x80 and c.ip == LOADER_RETS:
            break
        c.step()
    else:
        raise SystemExit("boot-block descriptor loader did not return")

    hits = []
    real = m.r16
    cpu = {}

    def hooked(a):
        v = real(a)
        cur = cpu.get("c")
        if cur is not None and cur.csp == 0x80 and (
                BODY1[0] <= cur.ip <= BODY1[1] or BODY2[0] <= cur.ip <= BODY2[1]):
            if 0x80 <= (a >> 16) <= 0x8F:
                hits.append(a & 0x0FFFFF)
        return v

    m.r16 = hooked
    c2 = S.CPU(m, 0x80, SUM_ENTRY)
    cpu["c"] = c2
    for _ in range(5000000):
        if c2.csp == 0x80 and c2.ip == SUM_DONE:
            break
        c2.step()
    else:
        m.r16 = real
        raise SystemExit("boot-block summing loops did not terminate")
    m.r16 = real
    return hits


def mutate(img: bytes, off: int, val: int) -> bytes:
    b = bytearray(img)
    b[off:off + 4] = val.to_bytes(4, "little")
    return bytes(b)


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else PI.image()
    img = path.read_bytes()
    print(f"image  {path.name}")
    print(f"store  0x{GEO.file_base:06X}-"
          f"0x{GEO.file_base + GEO.sectors * GEO.sector_size - 1:06X}  "
          f"({GEO.cells} cells)")
    print(f"code   0x{GEO.code_base - 0x800000:06X}-"
          f"0x{GEO.code_base - 0x800000 + 0xFFFF:06X}\n")

    words = sampled_words(img)
    store_lo = GEO.file_base
    store_hi = GEO.file_base + GEO.sectors * GEO.sector_size - 1
    code_lo = GEO.code_base - 0x800000
    code_hi = code_lo + GEO.code_size - 1

    # 1 - the property the whole relayout exists for
    inside = [a for a in words if store_lo <= a <= store_hi]
    check("the boot block reads NO word inside the persistence store",
          not inside,
          f"{len(words)} words sampled, 0 in store"
          if not inside else f"{len(inside)} in store, first 0x{inside[0]:06X}")

    # 2 - and it has not stopped protecting the firmware
    want = set()
    for base in range(code_lo, code_hi + 1, build.PAGE):
        want.add(base)
        want.add(base + build.PAGE - 2)
    got = set(words)
    check("every sampled word of the code sector IS read",
          want <= got,
          f"{len(want)} words across {(code_hi + 1 - code_lo)//build.PAGE} pages")

    # 3 - the builder's derived page list is what the silicon walks
    model = set()
    for base in build.bootsum_pages(img):
        model.add(base)
        model.add(base + build.PAGE - 2)
    check("build.bootsum_pages() matches what the boot block executed",
          model == got,
          f"{len(model)} modelled, {len(got)} measured"
          + ("" if model == got else f", symmetric difference {len(model ^ got)}"))

    # 4 - the stored record is the sum of exactly those words
    total = 0
    for a in words:
        total += int.from_bytes(img[a:a + 2], "little")
    stored = int.from_bytes(img[0x803C:0x8040], "little")
    check("the stored ROMSYS record equals the sum of the measured words",
          (total & 0xFFFFFFFF) == stored,
          f"0x{stored:08X}")

    # ---- mutation controls ------------------------------------------------
    # A gate that cannot fail is not a gate. Move the coverage field and the
    # MEASURED set must move with it; if it does not, this harness is not
    # really executing the boot block.
    print()
    base_n = len(set(words))
    for limit, expect_top in ((0x0083FFFF, 0x03E000),
                              (0x0085FFFF, 0x05E000),
                              (0x008FFFFF, 0x0FE000)):
        mu = mutate(img, 0x8014, limit)
        w = sampled_words(mu)
        top = max(a for a in w if (a & 0x1FFF) == 0)
        ok = top == expect_top
        check(f"control: header+0x14 = 0x{limit:08X} moves the top page to "
              f"0x{expect_top:06X}", ok, f"measured 0x{top:06X}, {len(set(w))} words")
        if limit == 0x008FFFFF:
            check("control: the OEM-width record DOES reach into the store",
                  any(store_lo <= a <= store_hi for a in w),
                  "so the exclusion above is a real property, not an artefact")

    print(f"\n{CHECKS - FAILS}/{CHECKS} checks pass")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
