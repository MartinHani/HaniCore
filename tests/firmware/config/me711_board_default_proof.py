#!/usr/bin/env python3
r"""
me711_board_default_proof.py - a FRESH page on this board comes up runnable.

    py tests\firmware\config\me711_board_default_proof.py

THE CLAIM, AND IT IS NARROW: after hc_cfg_init() + hc_cfg_mgr_init() on an ECU
with no stored record, the ACTIVE calibration page names a crank input, names
the S5500 window, and PASSES hc_validate(). Nobody has to know that 82 is the
crank cavity on a Porsche ME7.1.1 before the ECU will turn.

Everything here is EXECUTED out of the linked flash image in c167sim, using
me711_config_state_test.py's rig, so it measures the image rather than the
source. That makes it a SIMULATOR PROOF AGAINST THE LINKED IMAGE - not a
physical one. Flashing it and reading the page back over K-line is what
upgrades this, and this file does not claim to have done that.

WHY THE PAGE WAS NOT RUNNABLE BEFORE
====================================
seed_universal_defaults() set every physical-pin field to HC_PIN_NONE and
stopped there, on the principle that "nothing here invents a pin". The
principle is right and the outcome was not: hc_validate() refuses any syncMode
above NONE whose crank pin is unassigned, so a defaulted ECU could not run
until an operator typed 82 into TunerStudio - and V60's real-TunerStudio
acceptance run is exactly that, a person typing 82.

The seed now applies the preset marked `board_default` for THIS image's
descriptor. That is not a relaxation of the principle: every value in it
carries a source string in tools/config_source/hanicore_presets.py, and
me711_preset_routing_proof fails the build if any of them names a cavity whose
circuit cannot do the job.

AND ONE OF THOSE VALUES IS A BUG FIX WITH A MEASUREMENT BEHIND IT
=================================================================
`s5500WindowBase` was never seeded, so it read 0. hchal_me711.c picks
S5500_BASE_DEFAULT = 4 at init and hcmain_me711.c then lets the PAGE override
it - deliberately, so a bench can sweep the frame with no reflash - so every
boot silently pulled the correlation window four words off the ADDAT block.
Window slot 8, which the .ini reads as the ambient-pressure sender, carried ADC
channel 4 instead: a railed 1023 counts, which the published transfer function
turns into 1263.8 hPa. That is the "BARO reads about 1264 hPa" report, exactly.

Measured on the ECU 2026-09-16, both directions, no reflash:

    base 0 -> s5500Idx 0x0000, slot 8 = ch 4, raw 1023 -> 1263.8 hPa
    base 4 -> s5500Idx 0xFFFF, slot 8 = ch 8, raw  806 ->  995.7 hPa

THE NEGATIVE CONTROL IS THE RELEASE THAT HAD THE DEFECT
=======================================================
Every check below is re-run against the frozen V60 binary, where the seed did
NOT apply a board default. V60 must fail exactly the checks V61 passes - an
unassigned crank pin, a zero window base, and a refused validation. A gate that
only ever sees the fixed image cannot tell "the fix works" from "the harness
reads a constant", and this project has shipped that mistake more than once.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_config_state_test as T   # noqa: E402  the rig, the offsets, VAL
import me711_image as PI              # noqa: E402

FAILS = 0
CHECKS = 0

CONTROL = (Path(__file__).resolve().parents[3]
           / "release/Porsche_ME711_V60_BURN_REFUSAL"
           / "HaniCore_ME711_v60_burn_refusal.bin")


def ck(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def faults(rc):
    return "|".join(n for n, v in sorted(T.VAL.items())
                    if v and n.startswith("HC_VAL_FAULT") and (rc & v) == v)


def off(name):
    """A universal-block offset out of the generated header, never retyped."""
    return T.d(T._gen, name)


# The values the board default is required to establish. Each one is a claim
# with provenance in hanicore_presets.py; this table is what the ECU must
# actually hold, read back out of the ACTIVE page.
# NOTE ON WHAT IS *NOT* HERE: pinVbat.
#
# V61 seeded cavity 26 as the battery sense. the ME7.1.1 schematic draws cavity 26 as
# E_A_TANS into TANS_PXA51 - the peripheral ASIC - while the main CPU's own
# analog block reads UBAT_PA55 on AN5, an INTERNAL RAIL with no connector
# cavity at all. Battery sense therefore has no routing field on this board and
# belongs to the HAL's TGT_ADC_BATT_CH. me711_preset_routing_proof is what
# caught it, once the ME7.1.1 sheet layer landed.
WANT = [
    ("CFG_U_PIN_CRANK",     82, "cavity 82 DZG+_S, the proven VR crank input"),
    ("CFG_U_PIN_CAM1",      86, "cavity 86 PHA1_S, Phasensignal 1"),
    ("CFG_U_PIN_CAM2",      87, "cavity 87 PHA2_S, Phasensignal 2"),
    ("CFG_U_SYNC_MODE",      1, "SYNC_CRANK_ONLY - a V8's four cam refs cannot "
                                "resolve the cycle"),
    ("CFG_U_PIN_TPS1",      92, "cavity 92 IP1_S -> AN1"),
    ("CFG_U_PIN_TPS2",      84, "cavity 84 IP2_S -> AN3"),
    ("CFG_U_PIN_APP1",      35, "cavity 35 SP1_S -> AN8"),
    ("CFG_U_PIN_APP2",      34, "cavity 34 SP2_S -> AN9"),
    ("CFG_U_PIN_FUEL_PUMP", 65, "cavity 65 EKPR, the project's verified "
                                "default"),
    ("CFG_U_S5500_BASE",     4, "the ADDAT block - THE BARO FIX"),
]


class using_image:
    """Point the rig at ANOTHER linked image, with ITS OWN symbol map.

    THE MAP IS THE POINT. me711_config_state_test's rig calls firmware
    functions by address, resolved out of the map of the CURRENT build. Running
    the frozen V60 binary against V61's map would call whatever happens to live
    at V61's addresses - not a control, just noise that would probably still
    print PASS. So the image, the map, the symbol cache and the stack top all
    move together, and the manifest check is disabled because the control has
    a different sha by construction."""

    def __init__(self, img: Path):
        self.img = img
        self.map = img.with_suffix(".M66")

    def __enter__(self):
        if not self.map.exists():
            raise SystemExit("no map beside the control image: %s" % self.map)
        self.saved = (PI.IMG, PI.MAP, PI.MANIFEST, T.MAP_FILE, T._SYMS)
        PI.IMG, PI.MAP = self.img, self.map
        PI.MANIFEST = self.map.with_name("__no_manifest__.json")
        T.MAP_FILE, T._SYMS = self.map, None
        return self

    def __exit__(self, *exc):
        PI.IMG, PI.MAP, PI.MANIFEST, T.MAP_FILE, T._SYMS = self.saved
        return False


def read_fresh():
    """Boot a fresh page out of whichever image is selected, read it back."""
    r = T.boot()
    got = {n: r.active(off(n)) for n, _v, _w in WANT}
    rc = r("hc_validate", T.VAL["HC_VAL_SRC_ACTIVE"])
    return got, rc


def main():
    print("=== a fresh page on this board comes up runnable ===\n")
    print("  image under test : %s" % PI.image().name)
    print("  negative control : %s\n" % CONTROL.name)

    got, rc = read_fresh()

    for name, want, why in WANT:
        ck("%-22s = %3d" % (name, want), got[name] == want,
           "%s (read %d)" % (why, got[name]))

    ck("a fresh page PASSES hc_validate()", rc == T.VAL["HC_VAL_OK"],
       "rc = 0x%04X%s" % (rc, "" if rc == T.VAL["HC_VAL_OK"]
                          else " - " + faults(rc)))
    ck("...and specifically raises no SYNC fault",
       not (rc & T.VAL["HC_VAL_FAULT_SYNC"]),
       "the crank pin is what this used to trip on")
    ck("...and no PIN_CAP fault",
       not (rc & T.VAL["HC_VAL_FAULT_PIN_CAP"]),
       "every seeded cavity can do the job it was given")

    # ---- THE NEGATIVE CONTROL -------------------------------------------
    print("\n  --- the frozen V60 binary, which had no board default ---")
    if not CONTROL.exists():
        print("  NEGATIVE CONTROL NOT RUN: the frozen V60 release is not in this "
              "tree (maintainer's record); the checks above still ran")
    else:
        try:
            with using_image(CONTROL):
                cgot, crc = read_fresh()
        except SystemExit as e:
            ck(False, "the control image boots in the rig", str(e))
        else:
            ck("V60 leaves the crank pin UNASSIGNED",
               cgot["CFG_U_PIN_CRANK"] == T.PIN_NONE,
               "read %d - this is the defect" % cgot["CFG_U_PIN_CRANK"])
            ck("V60 leaves the S5500 window at 0",
               cgot["CFG_U_S5500_BASE"] == 0,
               "read %d - and 0 is what made BARO 1264 hPa"
               % cgot["CFG_U_S5500_BASE"])
            # AND V60's FRESH PAGE VALIDATES - WHICH IS NOT A CONTRADICTION.
            #
            # This check originally required a SYNC fault and got rc = 0x0000.
            # The reason is the first rule in hc_validate()'s sync section: a
            # page whose syncMode is NONE returns 0 immediately, because "a
            # bench configuration is a perfectly valid configuration". V60's
            # seed left syncMode at NONE *and* the crank pin unassigned, so the
            # page is consistent - it simply describes no engine at all.
            #
            # So the difference the board default makes is not valid vs
            # invalid. It is INERT vs RUNNABLE, and the sharp control is what
            # happens when the operator does the one thing V60's acceptance
            # run required them to do: select a sync mode. On V60 that page is
            # REFUSED until they also find and type 82.
            ck("V60's fresh page validates only because it is INERT",
               crc == T.VAL["HC_VAL_OK"]
               and cgot["CFG_U_SYNC_MODE"] == 0,
               "rc = 0x%04X, syncMode = %d - no engine is described"
               % (crc, cgot["CFG_U_SYNC_MODE"]))
            with using_image(CONTROL):
                r = T.boot()
                r("hc_cfg_mgr_write_u8", off("CFG_U_SYNC_MODE"), 1)
                r("hc_cfg_mgr_apply_now")
                crc2 = r("hc_validate", T.VAL["HC_VAL_SRC_DESIRED"])
            ck("...and selecting a sync mode on V60 is REFUSED for SYNC",
               bool(crc2 & T.VAL["HC_VAL_FAULT_SYNC"]),
               "rc = 0x%04X - this is what made an operator type 82" % crc2)

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("\nBOARD DEFAULT PROOF FAILS.")
        print("If the CONTROL checks failed, this gate has stopped being able")
        print("to tell a fixed image from a broken one - fix that first.")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
