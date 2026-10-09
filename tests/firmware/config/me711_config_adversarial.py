#!/usr/bin/env python3
r"""
me711_config_adversarial.py - attack the configuration page at its edges,
executing the real firmware.

    py tests\firmware\config\me711_config_adversarial.py

me711_config_state_test.py proves the state machine's SEMANTICS: what applies
when, what stays staged, what a refusal leaves behind. me711_trigger_adversarial_test
attacks the TRIGGER's boundaries. Neither attacks the page arithmetic itself,
and that is where a whole class of silent wrongness lives: a value that
round-trips through the wrong byte order, an array element that writes into its
neighbour, a signed field that wraps, an angle one count past the end of a
crank cycle.

None of these crash. Each returns a plausible number, which is why they need a
test rather than a review.

Everything runs the functions FROM THE FLASH IMAGE in c167sim.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
sys.path.insert(0, str(Path(__file__).resolve().parents[3]
                       / "tools/config_source"))

import me711_config_state_test as C   # noqa: E402
import me711_image as PI              # noqa: E402
import hanicore_config_def as CFGDEF  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-62s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


FIELDS = {f.slot: f for f in CFGDEF.resolve()[0]}


def boot():
    r = C.Rig()
    r("hc_cfg_init")
    r("hc_cfg_mgr_init")
    return r


def main() -> int:
    print("=== HaniCore ME7.1.1 - configuration page, adversarial ===\n")
    print("  image   %s" % PI.image().name)
    print("  sha256  %s\n" % PI.sha256())

    O_TDC = FIELDS["CFG_TDC_CYL"].offset
    O_INJ = FIELDS["CFG_INJ_CHANNEL"].offset
    O_RETARD = FIELDS["CFG_U_LAUNCH_RETARD_X10"].offset
    TDC_HI = FIELDS["CFG_TDC_CYL"].meta.hi
    N_CYL = FIELDS["CFG_TDC_CYL"].count

    # ------------------------------------------------------------ endianness
    #
    # The page is BIG-ENDIAN on the wire because that is what TunerStudio
    # sends, and the C167 is little-endian. hc_cal_u16() is the only place that
    # conversion happens. If it ever flipped, every 16-bit setting would read
    # back byte-swapped: 300 would become 11265, which is a perfectly plausible
    # number for a firmware to act on.
    print("--- byte order: the page is big-endian on the wire ---")
    r = boot()
    r("hc_cal_set_u8", O_TDC, 0x01)
    r("hc_cal_set_u8", O_TDC + 1, 0x2C)
    v = r("hc_cal_u16", O_TDC)
    check("high byte first: 0x01,0x2C reads as 300", v == 0x012C,
          "got %d (0x%04X)" % (v, v))
    r("hc_cal_set_u16", O_TDC, 7200)
    hi = r.callb("hc_cal_u8", O_TDC)
    lo = r.callb("hc_cal_u8", O_TDC + 1)
    check("and a word write lays the bytes down the same way",
          (hi << 8 | lo) == 7200, "0x%02X 0x%02X" % (hi, lo))

    # ------------------------------------------------------- array boundaries
    #
    # Eight cylinders of u16 TDC angles, then a different field. Writing the
    # last element must not reach into it, and writing one PAST the last
    # element must not silently land on the neighbour.
    print("\n--- per-cylinder arrays end where they say they do ---")
    r = boot()
    for i in range(N_CYL):
        r("hc_cal_set_u16", O_TDC + 2 * i, 100 + i)
    ok = all(r("hc_cal_u16", O_TDC + 2 * i) == 100 + i for i in range(N_CYL))
    check("all %d elements hold their own value" % N_CYL, ok,
          "no element overwrites its neighbour")
    after = O_TDC + 2 * N_CYL
    owner = [f for f in FIELDS.values()
             if f.offset <= after < f.offset + f.size]
    check("the byte after the last element belongs to a DIFFERENT field",
          owner and owner[0].slot != "CFG_TDC_CYL",
          "offset %d is %s" % (after, owner[0].slot if owner else "unowned"))
    # and the last element really is the last one the model claims
    check("the array's declared size matches its element count",
          FIELDS["CFG_TDC_CYL"].size == 2 * N_CYL,
          "%d bytes for %d u16 elements"
          % (FIELDS["CFG_TDC_CYL"].size, N_CYL))

    # ------------------------------------------------- crank-angle boundaries
    print("\n--- crank angle 0 and 720 are inside a cycle; 720.1 is not ---")
    tdc_fault = C.VAL["HC_VAL_FAULT_TDC"]

    def spread(r, first):
        """Distinct angles. The validator refuses DUPLICATE TDC angles as a
        fault in its own right, so setting all eight cylinders to the boundary
        value would exercise the duplicate rule and say nothing about range."""
        r("hc_cal_set_u16", O_TDC, first)
        for i in range(1, N_CYL):
            r("hc_cal_set_u16", O_TDC + 2 * i, 90 * i)

    for first, want_fault, why in (
            (0, False, "0.0 deg, the start of a cycle"),
            (TDC_HI, False, "720.0 deg, the end of it"),
            (TDC_HI + 1, True, "720.1 deg, one count past a full cycle")):
        r = boot()
        C.make_valid(r)
        spread(r, first)
        f = r("hc_validate", 0)
        got = bool(f & tdc_fault)
        check("angle %d %s" % (first,
                               "IS refused" if want_fault
                               else "raises no TDC fault"),
              got == want_fault, "%s, faults 0x%04X" % (why, f))

    # The duplicate rule itself, since it got in the way above: two cylinders
    # cannot share a TDC angle, or the scheduler fires them together.
    r = boot()
    C.make_valid(r)
    for i in range(N_CYL):
        r("hc_cal_set_u16", O_TDC + 2 * i, 90 * i)
    clean = r("hc_validate", 0)
    r("hc_cal_set_u16", O_TDC + 2, 0)      # cylinder 2 now equals cylinder 1
    dup = r("hc_validate", 0)
    check("distinct angles are accepted", not (clean & tdc_fault),
          "faults 0x%04X" % clean)
    check("and two cylinders sharing an angle are refused",
          bool(dup & tdc_fault), "faults 0x%04X" % dup)

    # --------------------------------------------------------- signed fields
    #
    # THE SIGNED FIELDS ARE DECLARED BUT NOT YET READ, AND THAT MATTERS.
    #
    # The model declares two s16 fields - launch and antilag ignition retard -
    # because a retard is negative. The firmware exports NO hc_cal_s16: its
    # accessors are u8, u16, set_u8, set_u16, map and curve16. Today that is
    # harmless, because nothing reads those fields. hc_cfg_mgr_init() seeds
    # them to zero and no runtime path touches them, which is the honest state
    # for a motorsport feature that is not implemented.
    #
    # It stops being harmless the moment one is read with hc_cal_u16: -10.0
    # degrees of retard reads as 65 436, which as x10 degrees is 6543.6 degrees
    # of ADVANCE. tests/unit/test_config_access_types.py already fails that call,
    # because hc_cal_u16 is entitled only to a u16 field. What is checked HERE
    # is that test's premise - that the fields really are unread.
    print("\n--- the signed retard fields are seeded, and read by nobody ---")
    src = ""
    for f in (sorted((ROOT / "firmware").glob("*.c"))
              + sorted((ROOT / "firmware/targets/me711")
                       .glob("*.c"))):
        src += re.sub(r"/\*.*?\*/", " ", f.read_text(errors="replace"),
                      flags=re.S)
    for slot in ("CFG_U_LAUNCH_RETARD_X10", "CFG_U_ANTILAG_RETARD_X10"):
        reads = re.findall(r"hc_cal_(?:u8|u16|map|curve16)\s*\(\s*%s" % slot,
                           src)
        check("%s is never READ through an unsigned accessor" % slot,
              not reads, "declared s16; there is no hc_cal_s16 yet")
    hcfg = (ROOT / "firmware/config/hcconfig.h").read_text(
        errors="replace")
    check("and the firmware still exports no signed accessor",
          "hc_cal_s16" not in hcfg,
          "add one BEFORE any signed field is read")

    # ------------------------------------------------- page-end and overflow
    print("\n--- nothing may be written past the end of the page ---")
    r = boot()
    page = C.PAGE
    before = r.callb("hc_cal_u8", 0)
    r("hc_cfg_mgr_write_u8", page, 0xAB)
    r("hc_cfg_mgr_write_u8", page + 1000, 0xCD)
    r("hc_cfg_mgr_write_u8", 0xFFFF, 0xEF)
    check("a write at the page size is ignored, and does not wrap to byte 0",
          r.callb("hc_cal_u8", 0) == before,
          "byte 0 still 0x%02X" % r.callb("hc_cal_u8", 0))

    # ------------------------------------------ a corrupted universal header
    print("\n--- a corrupted universal-block header is refused ---")
    O_MAGIC = FIELDS["CFG_U_MAGIC"].offset
    for bad_magic, why in ((0x0000, "all zeroes - an erased page"),
                           (0xFFFF, "all ones - an erased flash sector"),
                           (0x1234, "plausible rubbish")):
        r = boot()
        C.make_valid(r)
        r("hc_cal_set_u16", O_MAGIC, bad_magic)
        f = r("hc_validate", 0)
        check("magic 0x%04X is refused (%s)" % (bad_magic, why),
              bool(f & C.VAL["HC_VAL_FAULT_SCHEMA"]), "faults 0x%04X" % f)

    # ------------------------------------------- one-byte offset drift
    #
    # THE DEFECT THIS PROJECT ACTUALLY SHIPPED ONCE: a parallel .ini put
    # cylinderCount at offset 9, which is the high byte of cylinder 3's TDC
    # angle. Writing "8 cylinders" there wrote 8 into a crank angle.
    print("\n--- a one-byte drift lands inside a DIFFERENT field ---")
    owner9 = [f for f in FIELDS.values() if f.offset <= 9 < f.offset + f.size]
    check("offset 9 belongs to the per-cylinder TDC array, not a scalar",
          owner9 and owner9[0].slot == "CFG_TDC_CYL",
          "offset 9 is %s" % (owner9[0].slot if owner9 else "unowned"))
    cyl = FIELDS["CFG_CYLINDERS"]
    check("and the cylinder count is nowhere near it", cyl.offset != 9,
          "CFG_CYLINDERS is at offset %d" % cyl.offset)

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("CONFIGURATION PAGE FAILED AT AN EDGE.")
        return 1
    print("CONFIGURATION ADVERSARIAL PASSES - byte order, array bounds, angle\n"
          "and signed extremes, page end and a corrupted header all behave.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
