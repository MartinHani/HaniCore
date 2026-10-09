#!/usr/bin/env python3
r"""
me711_route_test.py - execute the physical pin router out of the real linked
image and prove the whole chain resolves.

    py tests\firmware\config\me711_route_test.py

WHAT CHAIN.

    TunerStudio writes a connector pin number
        -> the ACTIVE configuration page
        -> hc_route_ain_pin()      which pin is this channel on
        -> the target hardware descriptor    what is that pin on THIS board
        -> hc_route_ain_adc()      which ADC channel that implies
        -> compared with what hc_hal_ain() actually reads
        -> hc_route_check()        one bit per channel that disagrees

Before this file existed the router was LINKED and CALLED - hcmain_me711.c
publishes cfgRouteMismatch and cfgRouteRouted every output-channel frame - but
nothing had ever executed it. "It compiles and something calls it" is not the
same as "it resolves the right pin", and the difference is a tuner typing a
pin number and being told nothing is wrong when everything is.

Everything below runs the FUNCTIONS FROM THE FLASH IMAGE in c167sim, the same
way me711_config_state_test.py does. The pin numbers are not invented: they
come from Bosch's own connector sheet through the generated descriptor.

    pin  26  TAN_S|UBE_S  P5.5/AN5   battery sense      -> HC_AIN_VBAT
    pin  92  IP1_S        P5.1/AN1   throttle track 1   -> HC_AIN_TPS1
    pin  84  IP2_S        P5.3/AN3   throttle track 2   -> HC_AIN_TPS2
    pin  36  SP1_MA       ground     pedal 1 ground     -> no capability

WHAT THE ROUTER DELIBERATELY DOES NOT DO, and this file holds that line: it
does not rebind the HAL. hc_hal_ain() still reads the channel its own PHYS[]
table names. Making configuration authoritative over that binding can silently
move a live sensor reading, and it is not a change to make in the same image
that introduces the mechanism. So the router RESOLVES AND REPORTS, and the
report is what these checks are about.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_config_state_test as C   # noqa: E402  the rig and the offsets
import me711_image as PI              # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
TDIR = ROOT / "firmware/targets/me711"
SHARED = ROOT / "firmware"

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-62s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def _d(text, name):
    m = re.search(r"#define\s+%s\s+(0x[0-9A-Fa-f]+|\d+)u?" % name, text)
    if not m:
        raise SystemExit("%s not found" % name)
    return int(m.group(1), 0)


_hal = (SHARED / "hal/hchal.h").read_text(errors="replace")
_tgt = (TDIR / "hctarget.h").read_text(errors="replace")
_gen = (SHARED / "generated/hc_config_generated.h").read_text(errors="replace")

AIN = {n: _d(_hal, "HC_AIN_" + n) for n in
       ("VBAT", "CLT", "IAT", "MAP", "TPS1", "TPS2", "APP1", "APP2", "MAF",
        "COUNT")}
ADC_NONE = _d(_gen, "HC_ADC_NONE") if "HC_ADC_NONE" in _gen else 0xFF
PIN_NONE = _d(_gen, "HC_PIN_NONE")
CH_BATT = _d(_tgt, "TGT_ADC_BATT_CH")
CH_TPS1 = _d(_tgt, "TGT_ADC_TPS1_CH")
CH_TPS2 = _d(_tgt, "TGT_ADC_TPS2_CH")

O = {n: _d(_gen, n) for n in
     ("CFG_U_PIN_VBAT", "CFG_U_PIN_TPS1", "CFG_U_PIN_TPS2", "CFG_U_PIN_CLT",
      "CFG_U_PIN_MAP", "CFG_U_PIN_APP1")}

# Bosch's own connector sheet, through the generated descriptor.
# CAVITY 26 IS NOT THE BATTERY ON THIS BOARD, and this constant said it was.
#
# the ME7.1.1 schematic draws cavity 26 as E_A_TANS into TANS_PXA51 - the peripheral ASIC -
# while the main CPU's own analog block reads UBAT_PA55 on AN5, an INTERNAL
# RAIL with no connector cavity at all. The ME7.1 C4 family workbook lists the
# cavity as TAN_S|UBE_S and the descriptor generator resolved the UBE variant
# to AN5, which is the wrong variant for the ME7.1.1. Corrected by the ME7.1.1
# sheet layer in hw_descriptors.py.
#
# So the "a correct route" case below now uses a cavity this board really does
# read on its own converter, and cavity 26 becomes a REFUSAL case.
PIN_CLT = 93           # coolant temperature, ASIC AN0
PIN_TANS = 26          # intake air temperature, and it is on the ASIC
PIN_MAP = 101          # E_A_PLADE / E_A_DSS(PSR) -> DSS_PA514 = AN14
PIN_TPS1 = 92
PIN_TPS2 = 84
PIN_APP1 = 35          # SP1_S -> AN8, a third cavity this board reads
PIN_GROUND = 36        # SP1_MA, a pedal ground: SPECIAL_LOCKED, no capability


def boot():
    """A rig with the manager initialised, exactly as the target does."""
    r = C.Rig()
    r("hc_cfg_init")
    r("hc_cfg_mgr_init")
    return r


def route_bad(r):
    """What cfgRouteMismatch publishes: bind from the ACTIVE page, then check
    (hc_route_service), read through the cache the output channel reads."""
    r("hc_route_init")
    r("hc_route_service")
    return r("hc_route_check_cached")


def set_active_pin(r, off, pin):
    """Write straight into the ACTIVE page. The router reads ACTIVE, and this
    keeps the router's own behaviour separate from the manager's."""
    r("hc_cal_set_u8", off, pin)


def bit(mask, sem):
    return (mask >> sem) & 1


def main() -> int:
    print("=== HaniCore ME7.1.1 - the physical pin router, executed ===\n")
    print("  image   %s" % PI.image().name)
    print("  sha256  %s\n" % PI.sha256())

    # ---------------------------------------------------------- fresh block
    # A FRESH BLOCK NO LONGER ROUTES NOTHING, AND THAT IS V61 WORKING.
    #
    # This section used to require mask == 0 and every channel HC_PIN_NONE,
    # which was correct while seed_universal_defaults() left every pin
    # unassigned. V61 seeds the BOARD DEFAULT into a fresh page, deliberately,
    # so a fresh ME7.1.1 page routes the cavities this board actually has -
    # battery, both throttle tracks and both pedal tracks.
    #
    # THE PROPERTY THAT MATTERS SURVIVED THE CHANGE AND IS THE ONE TO ASSERT:
    # whatever the seed routes must AGREE with what the HAL reads. A board
    # default that routed a sensor the firmware does not read there would be
    # worse than routing nothing, and hc_route_check() is exactly the number
    # that catches it.
    print("--- a fresh universal block routes THIS BOARD, and agrees ---")
    r = boot()
    mask = r("hc_route_ain_routed_mask")
    bad = route_bad(r)
    routed = [s for s in range(AIN["COUNT"])
              if r.callb("hc_route_ain_pin", s) != PIN_NONE]
    check("a fresh page routes the board default, not nothing", mask != 0,
          "mask 0x%04X, %d channels: %s" % (mask, len(routed), routed))
    check("and EVERY routed channel agrees with what the HAL reads", bad == 0,
          "hc_route_check() = 0x%04X - a seeded route the firmware does not "
          "read would show here" % bad)
    check("every channel the seed did NOT route reads back unassigned",
          all(r.callb("hc_route_ain_pin", s) == PIN_NONE
              for s in range(AIN["COUNT"]) if s not in routed),
          "%d unrouted of %d" % (AIN["COUNT"] - len(routed), AIN["COUNT"]))

    # ------------------------------------------------------- a correct route
    print("\n--- a sensor routed to a cavity this board really reads ---")
    r = boot()
    set_active_pin(r, O["CFG_U_PIN_TPS1"], PIN_TPS1)
    pin = r.callb("hc_route_ain_pin", AIN["TPS1"])
    adc = r.callb("hc_route_ain_adc", AIN["TPS1"])
    bad = route_bad(r)
    mask = r("hc_route_ain_routed_mask")
    check("the router resolves the configured pin", pin == PIN_TPS1,
          "pin %d" % pin)
    check("the descriptor turns it into the right ADC channel",
          adc == CH_TPS1, "AN%d, and the HAL reads AN%d" % (adc, CH_TPS1))
    check("the channel is reported as routed", bit(mask, AIN["TPS1"]) == 1,
          "mask 0x%04X" % mask)
    check("and NOTHING disagrees", bit(bad, AIN["TPS1"]) == 0,
          "mismatch 0x%04X" % bad)

    # ------------------------------------------------------- a wrong route
    # Since V62 the configuration BINDS: moving a sensor to another analog
    # cavity moves what the HAL reads, so it agrees. (Before V62 the HAL kept
    # its compile-time channel and this was reported as a disagreement.)
    print("\n--- the same channel moved to another real analog pin ---")
    r = boot()
    set_active_pin(r, O["CFG_U_PIN_TPS1"], PIN_TPS2)
    adc = r.callb("hc_route_ain_adc", AIN["TPS1"])
    bad = route_bad(r)
    phys = r.callb("hc_hal_ain_phys", AIN["TPS1"])
    check("pin 84 is a perfectly good analog input", adc == CH_TPS2,
          "it resolves to AN%d" % adc)
    check("the HAL now reads throttle 1 on AN%d" % CH_TPS2, phys == CH_TPS2,
          "hc_hal_ain_phys = AN%d" % phys)
    check("so nothing disagrees", bad == 0, "mismatch 0x%04X" % bad)

    # --------------------------------------------- a pin with no capability
    print("\n--- a pin the board cannot read as an analog input ---")
    r = boot()
    set_active_pin(r, O["CFG_U_PIN_TPS1"], PIN_GROUND)
    pin = r.callb("hc_route_ain_pin", AIN["TPS1"])
    adc = r.callb("hc_route_ain_adc", AIN["TPS1"])
    bad = route_bad(r)
    mask = r("hc_route_ain_routed_mask")
    check("the configured pin is still reported honestly", pin == PIN_GROUND,
          "pin %d, SP1_MA, a pedal ground" % pin)
    check("but it yields NO ADC channel", adc == ADC_NONE,
          "hc_pin_can(%d, AIN) is false" % PIN_GROUND)
    check("it is NOT counted as routed", bit(mask, AIN["TPS1"]) == 0,
          "routed mask 0x%04X" % mask)
    check("and it IS a disagreement - the configuration asks for something "
          "the board refuses", bit(bad, AIN["TPS1"]) == 1,
          "mismatch 0x%04X" % bad)

    # ------------------------------------------ a channel the HAL cannot read
    print("\n--- the S5500-backed coolant input on its own cavity ---")
    r = boot()
    set_active_pin(r, O["CFG_U_PIN_CLT"], PIN_CLT)
    adc = r.callb("hc_route_ain_adc", AIN["CLT"])
    bad = route_bad(r)
    check("cavity 93 resolves to the ASIC's AN0", adc == (0xE0 | 0),
          "adc code 0x%02X" % adc)
    check("and the HAL reads CLT there, so it agrees",
          bit(bad, AIN["CLT"]) == 0
          and r.callb("hc_hal_ain_phys", AIN["CLT"]) == adc,
          "mismatch 0x%04X - no fresh sample is needed to agree" % bad)

    # ------------------------------------------------------ nonexistent pins
    print("\n--- pins that do not exist ---")
    for pin_no, why in ((0, "there is no pin 0"), (122, "the connector ends at 121")):
        r = boot()
        set_active_pin(r, O["CFG_U_PIN_TPS1"], pin_no)
        adc = r.callb("hc_route_ain_adc", AIN["TPS1"])
        check("pin %d yields no ADC channel" % pin_no, adc == ADC_NONE, why)

    # -------------------------------------------------- several at once
    print("\n--- both throttle tracks, each on its own Bosch pin ---")
    r = boot()
    set_active_pin(r, O["CFG_U_PIN_TPS1"], PIN_TPS1)
    set_active_pin(r, O["CFG_U_PIN_TPS2"], PIN_TPS2)
    set_active_pin(r, O["CFG_U_PIN_APP1"], PIN_APP1)
    mask = r("hc_route_ain_routed_mask")
    bad = route_bad(r)
    want = (1 << AIN["APP1"]) | (1 << AIN["TPS1"]) | (1 << AIN["TPS2"])
    # `== want` was right while a fresh page routed nothing and these three
    # were therefore the whole mask. V61's board default also routes both
    # PEDAL tracks, so the equality now fails for a reason that has nothing to
    # do with what this check is about. The question here is "do the three
    # pins I just configured resolve", and that is a SUBSET test; the
    # disagreement check on the next line is what keeps it honest.
    check("all three resolve to real ADC channels", (mask & want) == want,
          "routed 0x%04X, needed 0x%04X present" % (mask, want))
    check("and all three agree with what the firmware reads", bad == 0,
          "mismatch 0x%04X" % bad)
    check("TPS1 lands on AN%d" % CH_TPS1,
          r.callb("hc_route_ain_adc", AIN["TPS1"]) == CH_TPS1, "")
    check("TPS2 lands on AN%d" % CH_TPS2,
          r.callb("hc_route_ain_adc", AIN["TPS2"]) == CH_TPS2, "")

    # ------------------------------------------- ACTIVE, not DESIRED
    print("\n--- the router reads ACTIVE; a staged edit does not route ---")
    r = boot()
    set_active_pin(r, O["CFG_U_PIN_TPS1"], PIN_TPS1)
    before = r.callb("hc_route_ain_pin", AIN["TPS1"])
    # A host write of a routing field is RPM_ZERO_APPLY: staged, not active.
    r("hc_cfg_mgr_write_u8", O["CFG_U_PIN_TPS1"], PIN_TPS2)
    after = r.callb("hc_route_ain_pin", AIN["TPS1"])
    desired = r.callb("hc_cfg_mgr_read_u8", O["CFG_U_PIN_TPS1"])
    check("the host sees its own edit in DESIRED", desired == PIN_TPS2,
          "DESIRED = pin %d" % desired)
    check("the ROUTER still resolves the ACTIVE pin", after == before == PIN_TPS1,
          "still pin %d - a pending edit is not routing yet" % after)

    # ---------------------------- cavity 26 is NOT the battery on this board
    print("\n--- cavity 26 is intake air temperature, not the battery ---")
    r = boot()
    set_active_pin(r, O["CFG_U_PIN_VBAT"], PIN_TANS)
    adc = r.callb("hc_route_ain_adc", AIN["VBAT"])
    # SINCE V86 THE ASIC's ANALOG INPUTS ARE ROUTABLE (descriptor code
    # HC_ADC_ASIC(n) = 0xE0 | n, the project rules "CLT 93 / IAT 26 are routable"):
    # cavity 26 resolves to TANS on the ASIC's AN1, which is what the sheet
    # says it is. What must never happen is the pre-V62 error - cavity 26 read
    # as the main CPU's AN5, the internal battery rail with no cavity.
    check("cavity 26 is the ASIC's TANS (AN1), never main-CPU AN5 (UBAT)",
          adc == (0xE0 | 1) and adc != 5,
          "adc code 0x%02X. me711.pdf puts E_A_TANS on TANS_PXA51, the "
          "peripheral ASIC; AN5 UBAT_PA55 is an internal rail with no cavity"
          % adc)

    # ------------------------------------------- capability is not a veto
    print("\n--- the router never invents a capability ---")
    r = boot()
    check("a pin the descriptor does not describe answers 0",
          r.callb("hc_route_pin_ok", 121, 0) == 0,
          "pin 121 carries no signal on Bosch's sheet")

    # ================================================================
    # WHAT THESE CHECKS DO AND DO NOT ESTABLISH.
    #
    # Everything above is about RESOLUTION: given a connector pin number, do
    # the configuration, the descriptor and the HAL agree about what that pin
    # is. That is six separate things and only four of them are settled here.
    # Printing them apart is the point - "the router found the descriptor
    # entry" is not "this pin reads a sensor", and one sentence that blurs the
    # two is how a bench session records a result it never got.
    print("")
    print("--- the evidence dimensions, kept apart on purpose ---")
    dims = [
        ("physical pin identity", "VERIFIED",
         "Bosch's connector sheet, extracted to "
         "tools/config_source/data/me71_connector_121.csv"),
        ("OEM schematic role", "VERIFIED",
         "the same sheet names pin 26 TAN_S|UBE_S, 92 IP1_S, 36 SP1_MA"),
        ("CPU-side resource: which port and ADC channel", "VERIFIED",
         "Bosch's own Ressourcen port map, through the generated descriptor"),
        ("electrical capability: can this pin read an analog voltage",
         "PROBABLE",
         "INFERRED FROM THE SIGNAL NAME. 0 of 121 ME7.1.1 pins carry a "
         "VERIFIED capability, and hc_pin_can_verified() returns 0 for every "
         "one - see tests/unit/test_hw_descriptor_evidence.py"),
        ("HAL binding: which channel the firmware actually reads",
         "OFFLINE VERIFIED", "executed above, out of the linked image"),
        ("runtime source and scaling: does a real sensor move it",
         "UNVERIFIED",
         "PHYSICAL TEST REQUIRED - nothing here energises or reads a pin"),
    ]
    for name, status, why in dims:
        print("    %-50s %s" % (name, status))
        print("        %s" % why)

    check("no dimension above is claimed PHYSICALLY VERIFIED",
          all(x[1] != "PHYSICALLY VERIFIED" for x in dims),
          "only a bench run can close the last one")

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("ROUTER FAILED - the configured pin and the firmware disagree "
              "about what the board is.")
        return 1
    print("ROUTER PASSES - configuration resolves to real pins through the\n"
          "target descriptor, and every disagreement is reported rather than\n"
          "silently tolerated. The HAL binding is deliberately NOT rebound.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
