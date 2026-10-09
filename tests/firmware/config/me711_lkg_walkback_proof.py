#!/usr/bin/env python3
r"""
me711_lkg_walkback_proof.py - a page that cannot RUN must not end the search.

    py tests\firmware\config\me711_lkg_walkback_proof.py

WHAT THIS IS THE OTHER HALF OF. Two different questions get asked about a
stored configuration on this ECU, and until V65 only one of them could make
the boot look further back:

    "are these bytes intact"     nvm_scan(), magic + commit marker + 2x CRC16.
                                 Has fallen to the next-newest record on a CRC
                                 failure since the store became append-only.

    "can this configuration RUN" hc_validate(). V64 started asking it at boot -
                                 and when the answer was no, went straight to
                                 the COMPILED BOARD DEFAULT, skipping every
                                 older generation the store was keeping for
                                 exactly this case.

So one bad Burn cost a tuner their whole calibration. hc_nvm_lkg_walkback()
closes that: on a SEMANTIC failure it loads the next-older record and asks
again, bounded at four, with the board default still underneath as the floor.

HOW IT IS TESTED. Real records are built into real cells of a real image - the
same record() shape me711_nvm_proof.py writes, the same geometry out of
me711_nvm_geometry - and the image is BOOTED. Nothing here calls the walk-back
directly: main() calls it between hc_nvm_boot() and hc_cfg_mgr_init(), and
what this reads afterwards is where the ECU actually ended up.

THE PAYLOADS ARE NOT INVENTED. The good one is read out of a booted ECU's own
calibration page, so it is whatever the board default really is; the bad one
is that same page with the crank moved to cavity 29 - SRD_S/HFM_S on P5.0/AN0,
a real cavity with no capture unit behind it, which is structurally perfect and
semantically dead. A hand-built page would only prove this gate can build a
page hc_validate() dislikes.
"""
from __future__ import annotations

import binascii
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_heartbeat_gap_proof as HB      # noqa: E402
import me711_image as PI                    # noqa: E402
from me711_nvm_geometry import GEO          # noqa: E402

TGT = ROOT / "firmware/targets/me711"
CFG_H = ROOT / "firmware/config/hcconfig.h"
GEN_H = ROOT / "firmware/generated/hc_config_generated.h"

PAYLOAD = 4096
REC_LEN = 4120
DONE = b"DONE"
SENTINEL = 0x0002

CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print("  [%s] %-56s %s" % ("PASS" if ok else "FAIL", name, detail))


def sym(name):
    for m in re.finditer(r"^\s*([0-9A-F]{6})H\s+(\w+)\s",
                         PI.MAP.read_text(errors="replace"), re.M):
        if m.group(2) == name:
            return int(m.group(1), 16)
    raise SystemExit("%s is not in the map - build the target first" % name)


def defn(path, name):
    m = re.search(r"#define\s+%s\s+(\d+)u?" % name,
                  path.read_text(errors="replace"))
    if not m:
        raise SystemExit("%s is not in %s" % (name, path.name))
    return int(m.group(1))


def crc(x):
    return binascii.crc_hqx(x, 0xFFFF)


def hexdefn(path, name):
    m = re.search(r"#define\s+%s\s+(0x[0-9A-Fa-f]+)" % name,
                  path.read_text(errors="replace"))
    if not m:
        raise SystemExit("%s is not in %s" % (name, path.name))
    return int(m.group(1), 16)


# READ OUT OF THE HEADERS, NOT TYPED HERE. cell_scan() rejects a record whose
# layout id, version or length disagree with the firmware's own, and it does
# so BEFORE either CRC - so a wrong constant here produces HCNV_ERR_LAYOUT and
# a store the ECU behaves as though were empty.
#
# WORTH KNOWING, because it is where this gate's first version went wrong:
# me711_nvm_proof.py's record() writes 0x12345678 as the layout id and 1 as
# the version, and every check it makes still passes - because it validates
# the records with its own Python valid(), which tests the magic, the commit
# marker and the two CRCs and never looks at the layout triple. That is fine
# for what that gate asks (the WRITE mechanics: blankness, immutability,
# trace safety) but it means the records it builds are ones THIS ECU WOULD
# REFUSE, and they cannot be reused to test acceptance.
LAYOUT_ID = hexdefn(GEN_H, "HC_CFG_LAYOUT_ID")
VERSION = defn(CFG_H, "HC_CFG_VERSION")
SIZE = defn(CFG_H, "HC_CFG_SIZE")


def record(payload, gen):
    """The record shape hcnvm.c's cell_scan() accepts, constants and all."""
    assert len(payload) == SIZE, len(payload)
    r = bytearray(b"HCN1" + LAYOUT_ID.to_bytes(4, "big")
                  + VERSION.to_bytes(2, "big") + SIZE.to_bytes(2, "big")
                  + gen.to_bytes(4, "big"))
    r += crc(r).to_bytes(2, "big") + payload + crc(payload).to_bytes(2, "big")
    r += DONE
    assert len(r) == REC_LEN, len(r)
    return bytes(r)


class Boot:
    """Boot one image and read what the configuration layer settled on."""

    def __init__(self, img_bytes=None, steps=1_400_000):
        if img_bytes is None:
            path = PI.image()
        else:
            tmp = tempfile.NamedTemporaryFile(suffix=".bin", delete=False)
            tmp.write(img_bytes)
            tmp.close()
            path = Path(tmp.name)
        self.r = HB.Rig(path, HB.ENTRY_CURRENT, HB.TICK_CURRENT, echo=False)
        self.r.run(steps)
        self.cpu, self.mem = self.r.cpu, self.r.mem
        h = (TGT / "hctarget.h").read_text(errors="replace")
        self.extram = int(re.search(
            r"#define\s+TGT_EXTRAM_BASE\s+(0x[0-9A-Fa-f]+)", h).group(1), 16)
        self.ramcfg = int(re.search(
            r"#define\s+TGT_RAM_CFG\s+(0x[0-9A-Fa-f]+)", h).group(1), 16)
        self.core = defn(CFG_H, "HC_CFG_CORE")
        self.hdr = defn(CFG_H, "HC_CFG_HDR_LEN")

    def call(self, name, args=()):
        cpu = self.cpu
        addr = sym(name)
        saved = (cpu.csp, cpu.ip, cpu.m.sfr[0xFE12], cpu.ext)
        cpu.ext = None
        cpu.push(SENTINEL)
        cpu.csp = (addr >> 16) & 0xFF
        cpu.ip = addr & 0xFFFF
        for i, v in enumerate(args):
            cpu.sr(8 + i, v & 0xFFFF)
        for _ in range(3_000_000):
            if (cpu.ip & 0xFFFF) == SENTINEL:
                break
            cpu.step()
        else:
            raise SystemExit("%s did not return" % name)
        out = cpu.gr(4) & 0xFFFF
        cpu.csp, cpu.ip, cpu.m.sfr[0xFE12], cpu.ext = saved
        return out

    def addr(self, off):
        return ((sym("hc_cfg") & 0xFFFF) + off if off < self.core
                else self.extram + self.ramcfg + self.hdr + off)

    def get8(self, off):
        return self.mem.r8(self.addr(off))

    def page(self, n=PAYLOAD):
        return bytes(self.get8(i) for i in range(n))

    def u8(self, name):
        return self.mem.r8(sym(name) & 0xFFFF)


def place(img, cells):
    """cells: {cell_index: record bytes or None}. None leaves the cell blank."""
    f = bytearray(img)
    for idx, rec in cells.items():
        a = GEO.addr(idx)
        if rec is None:
            f[a:a + REC_LEN] = b"\xff" * REC_LEN
        else:
            f[a:a + len(rec)] = rec
    return bytes(f)


def main() -> int:
    PIN_CRANK = defn(GEN_H, "CFG_U_PIN_CRANK")
    base = PI.image().read_bytes()

    print("=== HaniCore ME7.1.1 - the LKG generation walk-back ===\n")
    print("  image   %s" % PI.IMG.name)
    print("  store   %d cells, first at file 0x%06X\n"
          % (GEO.cells, GEO.addr(0)))

    # ---------------------------------------- the two payloads, both REAL
    clean = Boot()
    good = clean.page()
    base_crank = clean.get8(PIN_CRANK)
    check("a clean boot produces a page that VALIDATES",
          clean.call("hc_validate", (0,)) == 0,
          "pinCrank = %d, and this page is the GOOD payload" % base_crank)

    bad = bytearray(good)
    bad[PIN_CRANK] = 29
    bad = bytes(bad)
    check("the GOOD and BAD payloads differ in exactly one byte",
          sum(1 for a, b in zip(good, bad) if a != b) == 1,
          "offset %d (pinCrank): %d -> 29" % (PIN_CRANK, base_crank))

    # ------------------------------------------------- 1. newest is valid
    img = place(base, {0: record(good, 10)})
    b = Boot(img)
    check("newest record VALID: it is used, no walk-back",
          b.u8("hc_cfg_boot_fellback") == 0
          and b.call("hc_nvm_lkg_steps") == 0,
          "fellback=%d steps=%d crank=%d"
          % (b.u8("hc_cfg_boot_fellback"), b.call("hc_nvm_lkg_steps"),
             b.get8(PIN_CRANK)))

    # ------------------------- 2. newest is semantically dead, older is good
    img = place(base, {0: record(good, 10), 1: record(bad, 11)})
    b = Boot(img)
    steps = b.call("hc_nvm_lkg_steps")
    fell = b.u8("hc_cfg_boot_fellback")
    crank = b.get8(PIN_CRANK)
    check("newest SEMANTICALLY INVALID: it walks back one generation",
          steps == 1 and fell == 0,
          "steps=%d fellback=%d" % (steps, fell))
    check("...and the OLDER stored calibration is what runs",
          crank == base_crank,
          "pinCrank = %d, not 29 and not a reseeded default" % crank)
    check("...and what it landed on validates",
          b.call("hc_validate", (0,)) == 0, "hc_validate = 0")

    # ------------------- 3. two bad generations deep, a good one underneath
    img = place(base, {0: record(good, 10), 1: record(bad, 11),
                       2: record(bad, 12)})
    b = Boot(img)
    steps = b.call("hc_nvm_lkg_steps")
    check("TWO bad generations: it keeps walking back",
          steps == 2 and b.u8("hc_cfg_boot_fellback") == 0,
          "steps=%d fellback=%d crank=%d"
          % (steps, b.u8("hc_cfg_boot_fellback"), b.get8(PIN_CRANK)))

    # ----------------------------------- 4. nothing in the store validates
    img = place(base, {0: record(bad, 10), 1: record(bad, 11)})
    b = Boot(img)
    fell = b.u8("hc_cfg_boot_fellback")
    crank = b.get8(PIN_CRANK)
    check("NO valid generation: it falls to the board default",
          fell == 1, "hc_cfg_boot_fellback = %d" % fell)
    check("...and the floor it lands on is RUNNABLE",
          crank == base_crank and b.call("hc_validate", (0,)) == 0,
          "pinCrank = %d, hc_validate = 0 - V61's doing" % crank)

    # --------------------------------------- 5. a torn newest record
    #
    # DONE never written: the commit marker is absent, so nvm_scan() does not
    # see a record there at all and the older one is simply the newest.
    torn = bytearray(record(bad, 11))
    torn[-4:] = b"\xff\xff\xff\xff"
    img = place(base, {0: record(good, 10), 1: bytes(torn)})
    b = Boot(img)
    check("a TORN newest record is not a generation at all",
          b.u8("hc_cfg_boot_fellback") == 0
          and b.call("hc_nvm_lkg_steps") == 0
          and b.get8(PIN_CRANK) == base_crank,
          "steps=%d - the CRC layer never offered it"
          % b.call("hc_nvm_lkg_steps"))

    # --------------------------------------- 6. a CRC-broken newest record
    #
    # Header and commit marker intact, payload corrupted. This is the case
    # nvm_scan() has always handled; it must still be handled, and WITHOUT
    # the semantic walk-back being needed.
    broken = bytearray(record(good, 11))
    broken[18 + 100] ^= 0xFF          # one payload byte, CRC now wrong
    img = place(base, {0: record(good, 10), 1: bytes(broken)})
    b = Boot(img)
    check("a CRC-BROKEN newest record still falls to the next-newest",
          b.u8("hc_cfg_boot_fellback") == 0
          and b.get8(PIN_CRANK) == base_crank,
          "steps=%d (0 expected - the CRC layer resolved it)"
          % b.call("hc_nvm_lkg_steps"))

    # ------------------------------------------- 7. generation ORDER decides
    #
    # The good record is in the HIGHER-numbered cell but carries the OLDER
    # generation. If selection went by cell index rather than generation this
    # would pick the good one and the test would pass for the wrong reason,
    # so the bad record is the newest by generation and must be tried first.
    img = place(base, {0: record(bad, 20), 1: record(good, 9)})
    b = Boot(img)
    check("the walk-back follows GENERATION, not cell order",
          b.call("hc_nvm_lkg_steps") == 1
          and b.u8("hc_cfg_boot_fellback") == 0
          and b.get8(PIN_CRANK) == base_crank,
          "steps=%d crank=%d - gen 20 (cell 0) refused, gen 9 (cell 1) used"
          % (b.call("hc_nvm_lkg_steps"), b.get8(PIN_CRANK)))

    # ============================ NEGATIVE CONTROL =========================
    #
    # Every check above would also pass if hc_cfg_mgr_init() simply reseeded
    # the board default every time - the board default has the same pinCrank
    # as the good payload, because the good payload IS a booted default. So
    # the walk-back has to be shown moving a byte that the default does NOT
    # supply. A spare calibration byte carries a marker through the record
    # and out the other side; if it survives, the page really came from the
    # store rather than from seed_universal_defaults().
    MARK_OFF = PAYLOAD - 3
    marked = bytearray(good)
    marked[MARK_OFF] = 0xA7
    marked = bytes(marked)
    img = place(base, {0: record(marked, 10), 1: record(bad, 11)})
    b = Boot(img)
    got = b.get8(MARK_OFF)
    check("NEGATIVE CONTROL: the page really came from the STORE",
          got == 0xA7 and b.call("hc_nvm_lkg_steps") == 1,
          "marker byte at %d reads 0x%02X, want 0xA7 - a reseeded default "
          "would not carry it" % (MARK_OFF, got))

    img = place(base, {0: record(bad, 10), 1: record(bad, 11)})
    b = Boot(img)
    check("...and it is ABSENT when the floor was used instead",
          b.get8(MARK_OFF) != 0xA7 and b.u8("hc_cfg_boot_fellback") == 1,
          "marker reads 0x%02X - so the check above discriminates"
          % b.get8(MARK_OFF))

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("LKG WALK-BACK FAILS.")
        return 1
    print("LKG WALK-BACK PASSES - a semantically dead newest record no longer "
          "costs a tuner every older generation the store was keeping.")
    print("NOT PHYSICALLY VERIFIED: no ECU has been booted onto a damaged "
          "store on the bench.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
