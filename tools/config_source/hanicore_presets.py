#!/usr/bin/env python3
r"""
hanicore_presets.py - engine and component presets, WITH PROVENANCE.

    py tools\config_source\hanicore_presets.py         list them
    py tools\config_source\hanicore_presets.py --gaps  list what was removed

A PRESET IS ONLY A FUNCTION THAT FILLS IN ORDINARY CONFIGURATION FIELDS.
No runtime code may branch on which preset was applied. Every value a preset
writes stays editable afterwards, and every value it writes has to come from
somewhere in this repository.

WHAT WAS REMOVED, AND WHY. The first version of this data shipped:

  * injector dead-time curves [1900, 1720, 1540, 1360, 1180, 1000, 820, 640]
    and [1750, 1580, 1410, 1240, 1070, 900, 730, 560] for two named Bosch part
    numbers, marked VERIFIED. Both are arithmetic sequences - constant -180 and
    constant -170 per step. Injector dead time against battery voltage is not
    linear; a straight line is what you draw when you do not have the data.
  * coil dwell curves for two named VAG part numbers, one of them also a
    perfect arithmetic sequence (-52 per step), marked VERIFIED.
  * MAP sensor transfer functions for three named Bosch part numbers, marked
    VERIFIED, with no datasheet anywhere in the tree.
  * a Bosch V8 preset routing injectors 5..8 to connector pins 15/14/13/12
    and coils 5..8 to 51/52/53/54. Bosch's own connector sheet makes those the
    four LSU lambda-2 wires, and a lambda wire, a lambda wire, the 5 V sensor
    supply and the road-speed input. See tools/config_source/data/me71_connector_121.csv.
  * mainRelayPin 21 and secRelayPin 121 on every preset. Connector pin 21 is
    ZAS2_S, "Zylinderabschaltung 2"; connector pin 121 carries no signal at
    all in Bosch's maximum-scope sheet.

None of that is here now. A preset that cannot prove a number leaves the field
unassigned, and `GAPS` below says so out loud. An empty field is a tuner's
five minutes; a fabricated dead-time curve is a lean cylinder.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field as dc_field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

from hanicore_config_schema import EvidenceClass  # noqa: E402

PIN_NONE = 255


@dataclass
class Value:
    """One preset value and the reason it is allowed to exist."""
    value: object
    evidence: EvidenceClass
    source: str


@dataclass
class Preset:
    ident: int
    key: str
    name: str
    target: str                      # the hardware descriptor it assumes, or ""
    values: dict[str, Value] = dc_field(default_factory=dict)
    gaps: dict[str, str] = dc_field(default_factory=dict)
    board_default: bool = False
    """THE BOARD'S OWN DEFAULT ROUTING, applied to a FRESH page.

    Exactly one preset per `target` may set this. It is the answer to "what
    is this ECU, with nothing configured yet" - and it is the difference
    between a fresh page that validates and one whose crank pin reads 0xFF
    until somebody types 82 into TunerStudio.

    IT IS STILL ONLY A PRESET. Every value it writes stays editable, no
    runtime code branches on it, and it may not contain a number this
    repository cannot source - the rules above do not relax because this one
    is applied automatically. What it buys is that the seed no longer has to
    choose between "invent a pin" and "ship a page that cannot run"."""


V = EvidenceClass.VERIFIED
P = EvidenceClass.PROBABLE

# --------------------------------------------------------------------------
# Sources, written once.
# --------------------------------------------------------------------------
S_IOMAP75 = "ME7.5-archive/HANICORE_ENGINE_IO_MAP.md"
S_HCCFG = "firmware/config/hcconfig.c hc_cfg_defaults() - the shipping " \
          "firmware defaults, themselves sourced from reference/pinouts/Pinout.xlsx " \
          "driver sheets (30344 / 30397)"
S_CONN = "tools/config_source/data/me71_connector_121.csv <- Bosch Steckerb. ME7.1.XLS"
S_PORTMAP = "tools/config_source/data/me711_iomap.csv <- Bosch me7_port.xls, the " \
            "OEM ME7.1.1's own column"
S_TRIGEV = "ME7.1.1 trigger evidence (OEM firmware trigger setup, bench captures)"
S_HCTARGET711 = "firmware/targets/me711/hctarget.h"


ENGINE_PRESETS: list[Preset] = [
    Preset(0, "CUSTOM", "Custom / user defined", "",
           values={},
           gaps={"everything": "By design. Nothing is populated."}),

    Preset(1, "VAG_18T_ME75_AWT", "VAG 1.8T AWT (ME7.5 image only)",
           "ME75_4B0906018DC",
           values={
               # Engine description
               "cylinders": Value(4, V, S_HCCFG),
               "strokes": Value(4, V, S_HCCFG),
               "tdcCylDegX10": Value([0, 5400, 1800, 3600], V,
                                     S_HCCFG + " - awt_tdc[], firing order 1-3-4-2"),
               "cylBank": Value([1, 1, 1, 1], V,
                                "an inline four has one bank; no evidence needed "
                                "beyond the cylinder count"),
               # Crank trigger
               "syTeeth": Value(60, V, S_HCCFG),
               "syGap": Value(2, V, S_HCCFG),
               "trigEdge": Value(0, V, S_HCCFG),
               "trigGapRatioX10": Value(25, V, S_HCCFG),
               "trigMinTeeth": Value(6, V, S_HCCFG),
               "trigTimeoutMs": Value(200, V, S_HCCFG),
               "trigDecoder": Value(1, V,
                                    "60-2 is a missing-tooth wheel; SY_TEETH/SY_GAP "
                                    "in " + S_HCCFG),
               "camEnable": Value(1, V, S_HCCFG),
               # Speeds
               "revMax": Value(7500, V, S_HCCFG),
               "revMin": Value(80, V, S_HCCFG),
               # Legacy channel indices, in CYLINDER order
               "injChannel": Value([0, 3, 1, 2], V,
                                   S_HCCFG + " - awt_chan[]; the board's output "
                                   "channels are numbered in FIRING order"),
               "ignChannel": Value([0, 3, 1, 2], V, S_HCCFG + " - awt_chan[]"),
               # Physical connector pins, in CYLINDER order.
               # EVn/ZUEn are firing-order indices: EV1=N30=cyl1, EV2=N32=cyl3,
               # EV3=N33=cyl4, EV4=N31=cyl2, so cylinder order is 96/89/97/88.
               "injPin": Value([96, 89, 97, 88], V,
                               S_IOMAP75 + " injection table: CJ920 E1..E4 -> "
                               "pins 96/97/88/89 = N30/N32/N33/N31 = cylinders "
                               "1/3/4/2"),
               "ignPin": Value([102, 95, 103, 94], V,
                               S_IOMAP75 + " ignition table: CK110 E1..E4 -> "
                               "pins 102/103/94/95 = N70/N291/N292/N127 = "
                               "cylinders 1/3/4/2"),
               # Sensors
               "pinCrank": Value(82, V, S_IOMAP75 + " G28+ = pin 82 -> P2.15/CC15"),
               "pinCam1": Value(86, V, S_IOMAP75 + " G40 = pin 86 -> P2.8/CC8"),
               "pinMap": Value(101, V, S_IOMAP75 + " G31 charge air = pin 101 -> AN14"),
               "pinClt": Value(93, V, S_IOMAP75 + " G62 = pin 93 -> AN10"),
               "pinTps1": Value(92, V, S_IOMAP75 + " J338 p1 = pin 92 -> AN1"),
               "pinTps2": Value(84, V, S_IOMAP75 + " J338 p4 = pin 84 -> AN3"),
               "pinApp1": Value(35, V, S_IOMAP75 + " G79 = pin 35 -> AN8"),
               "pinApp2": Value(34, V, S_IOMAP75 + " G185 = pin 34 -> AN9"),
               "pinVbat": Value(26, V, S_IOMAP75 + " battery = pin 26 -> AN5"),
               "pinFuelPump": Value(65, V, S_IOMAP75 + " fuel pump relay = pin 65"),
               "pinBoost": Value(104, V, S_IOMAP75 + " LDR/SU = pin 104 -> P7.1"),
               "pinMaf": Value(29, P, S_IOMAP75 + " G70 = pin 29, but WHETHER it "
                                     "is analog AN0 or a frequency on CC17 is "
                                     "unresolved and that document says so"),
               # Correlation: this pair really is opposite, and it is stated.
               "tpsCorrelation": Value(0, V,
                                       S_IOMAP75 + " 'Throttle position 2 ... "
                                       "opposing slope'"),
               "appCorrelation": Value(0, P,
                                       S_IOMAP75 + " 'Two tracks each for "
                                       "throttle and pedal, with opposing "
                                       "slopes' - stated for the pair, measured "
                                       "for the throttle"),
               "stoichAfrX100": Value(1470, V,
                                      "gasoline stoichiometry, a fuel property "
                                      "and not a hardware claim"),
           },
           gaps={
               "pinIat": "G42 intake air is on the CG650 ASIC (PXAN1), not a "
                         "C167 ADC channel. " + S_IOMAP75 + " gives connector "
                         "pin 17 / AN13 as the place to MOVE it to, which is a "
                         "wiring change, not a default.",
               "pinMainRelay": "J271 is driven through the ASIC/KL15 path, not "
                               "a freely assignable CPU pin.",
               "displacementCc": "1781 cc is common knowledge about the engine "
                                 "but is not stated anywhere in this repository, "
                                 "and a preset may not import facts from outside "
                                 "it.",
               "injFlowCcMin / injRefPressureKpa": "no injector part number or "
                                                   "flow figure exists in the tree.",
               "dwell curves / deadtime curves": "no component datasheet in the "
                                                 "tree. The firmware's own "
                                                 "defaults stay in force.",
           }),

    Preset(2, "BOSCH_ME711", "Porsche V8 donor - incomplete, refused",
           "BOSCH_ME711",
           values={
               "cylinders": Value(8, V,
                                  S_HCTARGET711 + " TGT_N_INJ = TGT_N_IGN = 8, "
                                  "and the port map's EV1..EV8 / ZDG1..ZDG8"),
               "strokes": Value(4, V, "four-stroke spark-ignition V8"),
               # Crank trigger - all four numbers are A2L-declared or recovered
               # from exact OEM ME7.1.1 machine code.
               "syTeeth": Value(60, V, S_TRIGEV + " - the A1104F A2L declares "
                                       "SY_TEETH = 60"),
               "syGap": Value(2, V, S_TRIGEV + " - the A1104F A2L declares "
                                    "SY_GAP = 2"),
               "trigEdge": Value(0, V, S_TRIGEV + " - OEM ME7.1.1 CCM3[15:12]=A, "
                                       "CC15IC=007A: negative edge, capture T1"),
               "trigGapRatioX10": Value(20, V,
                                        S_TRIGEV + " - exact OEM ME7.1.1 code at "
                                        "85:8766 recognises the gap as "
                                        "gap > 2 * previous1 AND gap > 2 * "
                                        "previous2, i.e. a ratio of 2.0"),
               "trigDecoder": Value(3, V,
                                    "TRIGDEC_BOSCH_ME711: the recovered "
                                    "two-history rule, not the generic "
                                    "missing-tooth rule"),
               "camEnable": Value(1, V, S_TRIGEV + " - NWDG on CC8 and NWDG2 on "
                                        "CC9 are both captured"),
               "syncMode": Value(1, V,
                                 "SYNC_CRANK_ONLY. " + S_TRIGEV + " is explicit: "
                                 "the four recovered cam falling edges repeat "
                                 "every 180 deg and are invariant under a 360 "
                                 "deg shift, so cycleSync is deliberately never "
                                 "asserted. Claiming cam cycle sync here would "
                                 "be the fabrication this file exists to stop."),
               # Position sensor pins
               "pinCrank": Value(82, P,
                                 S_CONN + " pin 82 = DZG+_S, and " + S_PORTMAP +
                                 " MAIN P2.15/CC15 = KWDG. " + S_TRIGEV +
                                 " rates the connector cavity PROBABLE until "
                                 "continuity is measured on a Bosch board."),
               "pinCam1": Value(86, P, S_CONN + " pin 86 = PHA1_S; " + S_PORTMAP +
                                      " MAIN P2.8/CC8 = NWDG. Cavity PROBABLE "
                                      "per " + S_TRIGEV),
               "pinCam2": Value(87, P, S_CONN + " pin 87 = PHA2_S; " + S_PORTMAP +
                                      " MAIN P2.9/CC9 = NWDG2. Cavity PROBABLE"),
               # Analog inputs that are genuinely on the MAIN CPU here
               "pinTps1": Value(92, P, S_CONN + " pin 92 = IP1_S; " + S_PORTMAP +
                                      " MAIN AN1 = IP1S = Istwertpoti 1 (EGAS)"),
               "pinTps2": Value(84, P, S_CONN + " pin 84 = IP2_S; " + S_PORTMAP +
                                      " MAIN AN3 = IP2S"),
               "pinApp1": Value(35, P, S_CONN + " pin 35 = SP1_S; " + S_PORTMAP +
                                      " MAIN AN8 = SPS1/DKG"),
               "pinApp2": Value(34, P, S_CONN + " pin 34 = SP2_S; " + S_PORTMAP +
                                      " MAIN AN9 = SPS2"),
               "stoichAfrX100": Value(1470, V, "gasoline stoichiometry"),
               # Two banks exist on a V8 and both lambda channels are wired,
               # but WHICH cylinder is on WHICH bank is a firing-order question
               # - see the gaps.
               "lambda1Source": Value(0, V,
                                      "disabled. The LSU controller path is not "
                                      "implemented on this target."),
               "lambda2Source": Value(0, V, "disabled, same reason."),
               # V100: no sensor is claimed by the board default, so the
               # heater policy is OFF - a board default must not drive a
               # heater into a cavity whose sensor nobody has declared.
               "lambdaHeatPolicy": Value(0, V, "LAMBDA_HEAT_OFF - this board "
                                         "default claims no lambda sensor"),
           },
           gaps={
               "injPin / ignPin": "THE BLOCKING GAP. Bosch's connector sheet "
                                  "gives EV1..EV8 on pins 96/97/88/89/112/113/"
                                  "24/23 and ZUE1..ZUE8 on 102/103/94/95/110/"
                                  "111/8/7, and the port map gives their CAPCOM "
                                  "channels - but EVn and ZUEn are FIRING-ORDER "
                                  "indices, not cylinder numbers "
                                  "(docs/PINOUT.md). The target vehicle "
                                  "M48 firing order is not stated anywhere in "
                                  "this repository, and a search of the A1104F "
                                  "A2L found no firing-order table. Without it "
                                  "the cylinder-to-pin map cannot be written "
                                  "down, and writing it down wrong fires fuel "
                                  "and spark into the wrong holes.",
               "tdcCylDegX10": "Same reason. An evenly spaced 0/90/180/.../630 "
                               "is only correct if the cylinder numbering "
                               "happens to follow the firing order, which on a "
                               "cross-plane V8 it does not.",
               "cylBank": "Same reason: bank membership follows the physical "
                          "block, and the repository does not state the "
                          "target vehicle's cylinder numbering.",
               "pinClt / pinIat": "NOT on the main CPU. TMOT is ASIC AN0 and "
                                  "TANS is ASIC AN1 "
                                  "(docs/PINOUT.md); they reach "
                                  "the CPU only inside the SSC frame, whose "
                                  "analog word positions are still unproven. "
                                  "hc_hal_ain_ok() reports them unavailable and "
                                  "that is the honest state.",
               "pinMap": "Connector pin 101 is SRD_S on one ME7.1.1 variant and "
                         "TAGR_S on the other - Bosch's own port map says the "
                         "two ME7.1.1 columns DIFFER on AN14. Not resolvable "
                         "from the tree.",
               "pinBoost": "The boost valve LDR is the PERIPHERAL ASIC's "
                           "P7.2/POUT2 on this ECU, not a main-CPU pin. There "
                           "is no HaniCore write path to it.",
               "pinMainRelay": "The PORSCHE OEM supply has no main-CPU main "
                               "relay - KL30 feeds the ECU, KL15 enables the "
                               "CJ910, and the CJ910's own HR pin is "
                               "NC_4000_16. That is a fact about the DONOR, "
                               "not about HaniCore. CAVITY 21 IS NOT THE "
                               "CANDIDATE - this note used to say it was, and "
                               "_PORSCHE_TRUTH settles 21 as KL15, a power "
                               "input, from three agreeing sources. The "
                               "routable RELAY_OUT cavities on this board are "
                               "4, 5, 46 and 65, and 65 is the fuel pump. "
                               "Which of the rest may carry an external main "
                               "relay is an installation measurement nobody "
                               "has taken. docs/firmware/design/ME711_POWER_AND_RELAY.md 4b.",
               "displacementCc": "not stated in the repository.",
               "revMax / revLimit": "no Bosch-specific figure in the tree; the "
                                    "firmware default stands until a tuner sets "
                                    "one.",
           }),

    # ======================================================================
    # THE BOARD DEFAULT - ROUTING AND BOARD FACTS, AND NO ENGINE AT ALL
    # ======================================================================
    #
    # WHY THIS IS SEPARATE FROM PRESET 2, which is the thing that had to be
    # learned. Preset 2 is the V8 DONOR ENGINE and it legitimately declares
    # cylinders = 8; it also, legitimately, CANNOT declare tdcCylDegX10,
    # because the M48 firing order is in no document in this repository and
    # the project rules forbid inventing one. Seeding preset 2 into a fresh
    # page therefore produced eight cylinders whose TDC angles were all zero,
    # and hc_validate() refused it with FAULT_TDC - "two cylinders at the same
    # angle is a configuration in which one of them never fires", which is
    # exactly right and exactly what should happen.
    #
    # The mistake was asking an ENGINE preset to be a BOARD default. A board
    # default's job is the part that is true of this ECU whatever is bolted to
    # it: which cavity the crank arrives on, which cavity each sensor arrives
    # on, and where the ASIC analog window sits. Engine geometry belongs to
    # whichever engine preset the tuner picks, and hcconfig.c's core defaults
    # already leave a VALID four-cylinder geometry behind - real, distinct TDC
    # angles - so a page seeded with routing alone validates and runs.
    #
    # Nothing here is an engine claim. No cylinder count, no stroke count, no
    # TDC table, no injector or coil routing, no displacement.
    Preset(4, "BOSCH_ME711_BOARD",
           "Board defaults - routing only, no engine",
           "BOSCH_ME711", board_default=True,
           values={
               # The one number this whole milestone turned on.
               "pinCrank": Value(82, P,
                                 S_CONN + " pin 82 = DZG+_S, and " + S_PORTMAP +
                                 " MAIN P2.15/CC15 = KWDG. PHYSICALLY EXERCISED "
                                 "on this ECU: crank sync at 199 and ~1984 rpm "
                                 "with sync loss count 0. The cavity is rated "
                                 "PROBABLE by " + S_TRIGEV + " until continuity "
                                 "is measured - but it is the cavity that works."),
               "pinCam1": Value(86, P, S_CONN + " pin 86 = PHA1_S "
                                       "Phasensignal1 (Nockenwelle); " +
                                       S_PORTMAP + " MAIN P2.8/CC8 = NWDG. NOT "
                                       "physically exercised - no cam is wired "
                                       "to this ECU."),
               "pinCam2": Value(87, P, S_CONN + " pin 87 = PHA2_S; " + S_PORTMAP +
                                      " MAIN P2.9/CC9 = NWDG2. NOT physically "
                                      "exercised."),
               # SYNC_CRANK_ONLY, and it is a SAFE DEFAULT rather than an engine
               # claim: it is the only mode that runs with no cam wired, and the
               # V8 donor's four equally spaced cam references cannot resolve a
               # 720 degree cycle in any case.
               "syncMode": Value(1, V,
                                 "SYNC_CRANK_ONLY - the only sync mode runnable "
                                 "with no cam wired, and the mode V60's real "
                                 "TunerStudio acceptance ran in."),
               "pinTps1": Value(92, P, S_CONN + " pin 92 = IP1_S; " + S_PORTMAP +
                                      " MAIN P5.1/AN1 = IP1S, both ME7.1.1 "
                                      "columns agree"),
               "pinTps2": Value(84, P, S_CONN + " pin 84 = IP2_S; " + S_PORTMAP +
                                      " MAIN P5.3/AN3 = IP2S"),
               "pinApp1": Value(35, P, S_CONN + " pin 35 = SP1_S; " + S_PORTMAP +
                                      " MAIN P5.8/AN8 = SPS1/DKG"),
               "pinApp2": Value(34, P, S_CONN + " pin 34 = SP2_S; " + S_PORTMAP +
                                      " MAIN P5.9/AN9 = SPS2"),
               "pinFuelPump": Value(65, V,
                                    S_CONN + " pin 65 = EKPR, and " + S_PORTMAP +
                                    " row 68 MAIN P2.12/CC12IO = EKP, both "
                                    "ME7.1.1 columns agreeing, into a CJ920 "
                                    "low-side driver. the project rules "
                                    "records cavity 65 as the VERIFIED DEFAULT "
                                    "for the logical FUEL_PUMP."),
               # THE AMBIENT-PRESSURE WINDOW, AND IT IS A MEASUREMENT.
               #
               # Never seeded, so it read 0 - and 0 is not "unset", it is a
               # legal window position four words early. hchal_me711.c picks 4
               # at init and hcmain_me711.c lets the PAGE override it, so every
               # boot pulled the window off the ADDAT block and slot 8 - which
               # the .ini reads as the ambient sender - carried ADC channel 4.
               #
               # MEASURED ON THIS ECU 2026-09-16, both directions, no reflash:
               #   base 0 -> s5500Idx 0x0000, slot 8 = ch 4, raw 1023 -> 1264 hPa
               #   base 4 -> s5500Idx 0xFFFF, slot 8 = ch 8, raw  806 ->  996 hPa
               # 1264 hPa is exactly the figure that was reported as wrong.
               "s5500WindowBase": Value(4, V,
                                        "hchal_me711.c S5500_BASE_DEFAULT, and "
                                        "PHYSICALLY MEASURED on this ECU: base "
                                        "4 is the only position where all "
                                        "sixteen window slots decode as ADDAT "
                                        "channels 0..15, s5500Idx = 0xFFFF. "
                                        "bench measurements"
                                        "01_BARO_ROOT_CAUSE/"),
               # V97: the lamp stage is a board fact (not yet on a meter), so
               # the board default names it and carries the lamp test timing
               # - but leaves the lamp OFF until an engine preset turns it on
               "pinMil": Value(47, P, "me711.pdf W12 sheet: LUES2_PX70 -> CJ920 -> cavity 47 A_S_LUES2/A_S_SPOEKUE/A_S_MIL (SAME-GENERATION); family table 47 = MIL_S"),
               "celEnable": Value(0, V, "off on the bare board"),
               "celTestEnable": Value(1, V, "project decision: ON 3 s, OFF 1 s"),
               "celTestOnMs": Value(3000, V, "project decision: 3.0 s"),
               "celTestGapMs": Value(1000, V, "project decision: 1.0 s"),
               # V97: the OEM's cam-valve PWM frequency - a board fact
               "vvtFreqHz": Value(250, V, "OEM key-on PWM init [BIN 0x8C0D78] "
                                  "PP 0x09C3 at fCPU/64 = 250 Hz"),
           },
           gaps={
               "pinVbat": "NO CONNECTOR CAVITY ON THIS BOARD. This preset "
                   "carried cavity 26, which is correct for the ME7.5 board and "
                   "wrong for the ME7.1.1: me711.pdf draws cavity 26 as "
                   "E_A_TANS into TANS_PXA51, the PERIPHERAL ASIC, while the "
                   "main CPU analog block reads UBAT_PA55 on AN5 - an INTERNAL "
                   "RAIL with no cavity at all. The family workbook lists "
                   "cavity 26 as TAN_S|UBE_S and the descriptor generator "
                   "resolved the UBE variant to AN5, which is the wrong variant "
                   "for this board. Battery sense belongs to the HAL's "
                   "TGT_ADC_BATT_CH and needs no routing field. Caught by "
                   "me711_preset_routing_proof once the ME7.1.1 sheet layer "
                   "landed.",
               "cylinders / strokes / tdcCylDegX10": "DELIBERATELY ABSENT. A "
                   "board default is not an engine. hcconfig.c's core defaults "
                   "leave a valid four-cylinder geometry with real distinct TDC "
                   "angles, and an engine preset or the tuner replaces it. "
                   "Seeding the V8 donor's cylinders = 8 here is what produced "
                   "eight cylinders at TDC 0 and a FAULT_TDC refusal.",
               "injPin / ignPin": "Not board facts - they are per cylinder, and "
                   "the cylinder-to-cavity map needs a firing order. The donor "
                   "V8's is unknown (preset 2's gaps say why); the 1.8T's is in "
                   "preset 3. Note also that only SIX cavities on this board "
                   "carry INJ_OUT - 88, 89, 96, 97, 112, 113 - because EV7 and "
                   "EV8 (cavities 24 and 23) are inside the LOCKED 18..24 "
                   "block, so a fresh eight-cylinder page could not route all "
                   "eight injectors even with a firing order.",
               "pinMap / pinClt / pinIat": "Not routable to this CPU converter. "
                   "TMOT and TANS are on the peripheral ASIC and reach the CPU "
                   "only inside the S5500 frame; and AN14's two ME7.1.1 columns "
                   "disagree (TAGR vs DSS), so no manifold-pressure cavity is "
                   "established either.",
               "pinMainRelay": "Cavity 21 is KL15, a power input. Cavity 23 is "
                   "the real main-relay drive and THE MAIN CPU DOES NOT OWN IT "
                   "- the project rules. Left unset deliberately.",
               "pinBoost": "LDR is the peripheral ASIC P7.2/POUT2, which is "
                   "also the DBW bridge IN1, and the two ME7.1.1 columns "
                   "disagree (LDR vs HYLUE). No HaniCore write path exists.",
           }),

    # V86 NAMING: a preset name describes the ENGINE/VEHICLE, never the ECU -
    # the hardware target is fixed (operator, 2026-09-26). "(AWT)" because the
    # routing below is the AWT harness after its connector adaptation (IAT
    # 85 -> 26, relay drive 21 -> 23) and the firing-order tables are awt_*.
    Preset(3, "VAG_18T_ME711", "VAG 1.8T DBW (AWT)",
           "BOSCH_ME711",
           values={
               # THE FIRST REAL ENGINE. A VW/Audi 1.8T in a Porsche ME7.1.1
               # ECU: the engine description comes from the 1.8T, the pin
               # numbers from Bosch's ME7.1.1 connector sheet, and nothing is
               # imported from outside this repository.
               #
               # WHY THIS PRESET CAN WRITE injPin/ignPin WHEN THE V8 ONE
               # CANNOT: the V8's blocking gap is the M48 firing order, which
               # is not stated anywhere in the tree. The 1.8T's IS - the
               # shipping firmware defaults carry awt_tdc[] and awt_chan[] for
               # firing order 1-3-4-2 - so the cylinder-to-cavity map can be
               # written down without inventing it.
               "cylinders": Value(4, V, S_HCCFG),
               "strokes": Value(4, V, S_HCCFG),
               "tdcCylDegX10": Value([0, 5400, 1800, 3600], V,
                                     S_HCCFG + " - awt_tdc[], firing order "
                                     "1-3-4-2"),
               # V98: the NAMED order computes the TDCs above (rusEFI
               # FO_1_3_4_2 = 1); the angles stay for CUSTOM
               "firingOrder": Value(1, V, "1-3-4-2, VAG inline four"),
               "cylBank": Value([1, 1, 1, 1], V,
                                "an inline four has one bank"),

               # ---- crank trigger: the 1.8T wheel ----------------------
               "syTeeth": Value(60, V, S_HCCFG),
               "syGap": Value(2, V, S_HCCFG),
               "trigEdge": Value(0, V, S_HCCFG),
               "trigGapRatioX10": Value(25, V, S_HCCFG),
               "trigMinTeeth": Value(6, V, S_HCCFG),
               "trigTimeoutMs": Value(200, V, S_HCCFG),
               "trigDecoder": Value(1, V,
                                    "TRIGDEC_MISSING_TOOTH. The wheel is 60-2 "
                                    "and the generic rule describes it. The "
                                    "recovered ME7.1.1 two-history decoder "
                                    "(3) also runs on this board and stays "
                                    "selectable - this is a default, not a "
                                    "restriction."),
               "camEnable": Value(1, V,
                                  "the 1.8T has a cam sensor and this board "
                                  "captures NWDG on CC8"),
               # SYNC_CRANK_ONLY, AND IT USED TO BE SYNC_CAM1_CYCLE (2).
               #
               # A cam cycle mode is where this engine ENDS UP, and it is the
               # case cam cycle sync exists for - an inline four with one cam
               # sensor. But V63 made hc_validate() ask the runtime's question
               # in the runtime's terms: a cam cycle mode now
               # requires camEnable AND an ODD, non-zero CFG_U_CAM_REFS,
               # because an even equally spaced set maps onto itself under a
               # 360-degree shift and resolves nothing.
               #
               # camRefX10 is BLOCKED ON A MEASUREMENT - no cam edge has ever
               # reached this ECU (bench) - so the gap below stands and the number
               # must not be invented.
               #
               # DECLARING MODE 2 ANYWAY MADE THE PRESET UNAPPLIABLE. Measured
               # on V70: applying preset 3 and calling hc_validate() returns
               # 0x0010 FAULT_SYNC naming CFG_U_CAM_REFS - and 12M/3's rule is
               # that "a page hc_validate() refused can never reach a motor,
               # however it is armed". A factory preset for the FIRST ENGINE
               # that cannot be applied is the same defect 12K/3 found when
               # this preset routed the main relay into a power input.
               #
               # the project rules: "an incomplete preset with a named gap is
               # correct". Crank-only is what this configuration can actually
               # run TODAY - both strategies here are batch/wasted, and 12M/2
               # records that neither needs to know which revolution it is in.
               # The cam pin and camEnable stay, so the hardware is still
               # described; only the claim about what is RESOLVED steps back.
               # V97: CYCLE SYNC FROM THE CAM, SEQUENTIAL WITH A FALLBACK. The
               # quick-start wheel's LEVEL at camPhaseAngleX10 decides the half
               # (camPhaseMode 1 below; alternation measured on the car, V92:
               # 194/194). Until the cycle is confirmed the sequential
               # strategies run their fallback (wasted COP + two half pulses),
               # which needs crank sync only - so this page starts exactly as
               # the V91..V96 batch/wasted page did (docs/ARCHITECTURE.md).
               "syncMode": Value(2, P,
                                 "SYNC_CAM1_CYCLE - the quick-start cam on 86 "
                                 "(LEVEL method); docs/firmware/design/ME711_CAM_QUALIFICATION.md"),
               "revMax": Value(7500, V, S_HCCFG),
               "revMin": Value(80, V, S_HCCFG),

               # ---- outputs, in CYLINDER order -------------------------
               # EVn / ZUEn are FIRING-ORDER indices. With 1-3-4-2:
               #   cyl1 = EV1 = cavity 96      cyl2 = EV4 = cavity 89
               #   cyl3 = EV2 = cavity 97      cyl4 = EV3 = cavity 88
               # V86: slots 5..12 are written NONE. A four-cylinder preset
               # applied over a page that routed more must not leave a live
               # fifth injector behind; "no cylinder 5" needs no evidence.
               "injPin": Value([96, 89, 97, 88] + [PIN_NONE] * 8, P,
                               S_CONN + " EV1..EV4 = 96/97/88/89, mapped "
                               "through firing order 1-3-4-2. Cavity numbers "
                               "PROBABLE until continuity is measured on a "
                               "Porsche board - the sheet is a VW ME7.1."),
               "ignPin": Value([102, 95, 103, 94] + [PIN_NONE] * 8, P,
                               S_CONN + " ZUE1..ZUE4 = 102/103/94/95, same "
                               "mapping. NOTE these are 'Zuendendstufe "
                               "extern': the ignition output stages are "
                               "OUTSIDE this ECU, so the cavity carries a "
                               "trigger and not coil current."),
               "injChannel": Value([0, 3, 1, 2], V,
                                   S_HCCFG + " - awt_chan[]; output channels "
                                   "are numbered in FIRING order"),
               "ignChannel": Value([0, 3, 1, 2], V, S_HCCFG + " - awt_chan[]"),

               # ---- position and analog --------------------------------
               "pinCrank": Value(82, P, S_CONN + " pin 82 = DZG+_S; " +
                                 S_PORTMAP + " MAIN P2.15/CC15 = KWDG"),
               "pinCam1": Value(86, P, S_CONN + " pin 86 = PHA1_S; " +
                                S_PORTMAP + " MAIN P2.8/CC8 = NWDG"),
               # V98: the AWT has ONE camshaft sensor (G40, on 86). The
               # board default's second-cam route to 87 is not this
               # engine, and it claimed the one free switch input.
               "pinCam2": Value(255, V, "AWT: one cam sensor (G40) on 86; "
                                "cavity 87 stays free for a switch input"),
               "pinTps1": Value(92, P, S_CONN + " pin 92 = IP1_S; " +
                                S_PORTMAP + " MAIN AN1 = IP1S"),
               "pinTps2": Value(84, P, S_CONN + " pin 84 = IP2_S; " +
                                S_PORTMAP + " MAIN AN3 = IP2S"),
               "pinApp1": Value(35, P, S_CONN + " pin 35 = SP1_S; " +
                                S_PORTMAP + " MAIN AN8 = SPS1/DKG"),
               "pinApp2": Value(34, P, S_CONN + " pin 34 = SP2_S; " +
                                S_PORTMAP + " MAIN AN9 = SPS2"),

               # V77. THE MAP CAVITY IS RESOLVED BY THE ME7.1.1 SHEET, which the
               # gap note below predated. The port map's two columns disagree
               # on AN14; the ME7.1.1 schematic does not.
               "pinMap": Value(101, P,
                               "reference/schematics/ME711/me711.pdf at 330 dpi "
                               ": cavity 101 "
                               "is drawn E_A_PLADE with E_A_DSS(PSR) beneath, "
                               "into DSS_PA514 = MAIN AN14 - a PRESSURE input. "
                               "The AWT harness brings G31 charge pressure on "
                               "cavity 101 (preset 1). WHICH pressure the "
                               "installed sensor measures is the installation's; "
                               "its transfer function is a pressure-sensor "
                               "component preset, not this."),
               # ---- V86: the S5500 temperatures are ROUTED, not left NONE --
               # Cavity 93 E_A_TMOT -> TMOT_PXA50 = ASIC AN0 and cavity 26
               # E_A_TANS -> TANS_PXA51 = ASIC AN1 (the ME7.1.1 schematic, read twice;
               # bench measurements). The
               # HAL has read both since V78, accepting a sample only when the
               # ADC's own channel tag matches. Until V86 the descriptor gave
               # them NO resource, so the validator refused 93/26 and the page
               # had to say NONE while the ECU read them anyway - a routing
               # field that did not describe the routing. The AWT IAT wire
               # moves 85 -> 26 in the connector adaptation (85 is E_A_DSBKV).
               "pinClt": Value(93, P, "me711.pdf: cavity 93 E_A_TMOT -> "
                               "TMOT_PXA50, ASIC AN0 (S5500 window w00, "
                               "tag-checked in hchal_me711.c s5500_sample)"),
               "pinIat": Value(26, P, "me711.pdf: cavity 26 E_A_TANS -> "
                               "TANS_PXA51, ASIC AN1 (w01). AWT harness IAT "
                               "wire moved 85 -> 26"),
               # ---- V86: the execution strategy is PART of the preset -----
               # Until V86 the preset left these to whatever the page held, so
               # applying it over a page set to sequential produced a page the
               # validator refuses (sequential needs a cycle; this preset is
               # crank-only). Both below need NO cycle position.
               # V97: TRUE SEQUENTIAL, REACHED AUTOMATICALLY. Before cycle
               # sync each cylinder gets two half pulses and a wasted spark
               # (the V91..V96 fuel mass per cylinder, per cycle, and the same
               # sparks); once the cam confirms the cycle each cylinder
               # switches at its own twin event. If the camPhaseLevel
               # assignment is inverted the engine stalls seconds after
               # cycleSync: flip camPhaseLevel (operator card).
               "injStrategy": Value(2, P, "INJ_SEQUENTIAL with the batch-like "
                                    "fallback until the cycle is known (V97)"),
               "ignStrategy": Value(2, P, "IGN_SEQUENTIAL_COP with the wasted "
                                    "COP fallback until the cycle is known "
                                    "(V97); one coil per cylinder"),
               "injTimingMode": Value(1, P,
                                    "END of injection (Bosch ME7 KFWEE, "
                                    "rusEFI's usual mode)"),
               "injStartDegX10": Value(4400, P,
                                    "JUDGEMENT: injection ends 440 deg BTDC "
                                    "compression = 80 deg before gas-exchange "
                                    "TDC (closed-valve port injection). The "
                                    "AWT image's KFWEE (72..264 deg KW, "
                                    "reference TDC not decodable here) is "
                                    "consistent if referenced to gas-exchange "
                                    "TDC; tune on the car."),
               # ---- V97: lambda 1 = the on-board CJ120, bank 1 ------------
               # The AWT G39 plugs straight into the bank-1 cavities (70/51/
               # 71/52, heater low side 5 - the project rules, the ME7.5 C2-2 sheet
               # uses the same cavities). The heater drive polarity is
               # PHYSICAL (V93 r2, CJ120 heater diagnosis); the envelope is
               # rusEFI's (dew wait, 2 V preheat, 7->12 V ramp, PI on Ri) and
               # lambda reads 0 unless the sensor is READY. Heating a FITTED
               # sensor is the car's first test (physical qualification is
               # not an implementation blocker). DISPLAY
               # AND LOG ONLY: no fuel path reads lambda.
               "lambda1Source": Value(1, P, "LAMBDA_INTERNAL_LSU - AWT G39 "
                                      "on the bank-1 CJ120 (cavities 70/51/71/"
                                      "52, heater 5)"),
               # V100: LAMBDA_HEAT_IGNITION - the heater runs on key-on so
               # the LSU is a measurement BEFORE the first crank. rusEFI
               # heater_control.cpp GetNextState() permits heating on supply
               # voltage alone; V99 required the engine to be turning, and on
               # this car that meant lambda never became READY at all (~40 s
               # needed, runs were 18..42 s).
               "lambdaHeatPolicy": Value(1, P, "LAMBDA_HEAT_IGNITION - warm "
                                         "the G39 with the key on, as rusEFI "
                                         "does; the car proved the sensor "
                                         "healthy (Ri to 81 ohm) but never "
                                         "ran long enough in one stretch"),
               "lambda1Bank": Value(1, V, "BANK_1 - one bank (inline 4)"),
               "lambda1CylMask": Value(0x000F, V, "cylinders 1..4"),
               "lambda2Source": Value(0, V, "LAMBDA_OFF - one bank"),
               # ---- the two routed auxiliary outputs -------------------
               "pinFuelPump": Value(65, P,
                                    S_CONN + " pin 65 = EKPR; " + S_PORTMAP +
                                    " MAIN P2.12/CC12 = EKP, through a CJ920 "
                                    "0.6 A low-side stage. PROBABLE: polarity "
                                    "and cavity unmeasured. "
                                    "docs/firmware/design/ME711_FUEL_PUMP.md."),

               # ---- V79: the S5500 temperatures and the ASIC's N75 -----
               # THE OEM'S OWN CONVERSIONS, read out of this ECU's code. CLT:
               # [BIN 0x88C97A] CALLS 0x833DB8 on the 20-point word curve at
               # 0x81F9C8 (the default of the two the OEM selects between; the
               # other, 0x81F976, is the switched hot-range pull-up). IAT:
               # [BIN 0x88C5CE] CALLS 0x833D44 on the byte curve at 0x819739,
               # axis = raw >> 2. Values are ME7 byte temperatures, x*0.75-48 C,
               # resampled to 16 points (4 dropped where the curve is densest).
               # PROBABLE for the 1.8T: the OEM calibrated them for ITS sensors
               # on THIS board's pull-ups; the G62/G42 are the same Bosch NTC
               # family. The resistor test (CLT_IAT_TEST.md) confirms.
               # V91: THE CLT CURVE FOR THE PULL-UP THE BOARD ACTUALLY HAS.
               # the ME7.1.1 schematic: TMOT (cavity 93) has R1120 2.61k up / R1121 38.3k
               # down like TANS, PLUS T1120 BSP171 switching R1123||R1124
               # (681||681 = 340 R) onto it, gated by the ASIC's TMOT_UM_PX212.
               # PHYSICAL: open CLT reads 1015 = 1023*38.3/(38.3+0.301) - the
               # 340 R stage is ON (off would read 958, exactly what open TANS
               # reads). The OEM's second curve [BIN 0x81F976] is the one for
               # that state; V88..V90 used the default [BIN 0x81F9C8], so the
               # AWT's G62 at ~15 C (raw 923) read -40 C. Resampled 20 -> 16
               # (dropped 397/607/462/366, max 0.22 C).
               "cltSensAx": Value([182, 238, 284, 337, 428, 533, 680, 751,
                                   783, 812, 866, 908, 942, 967, 996, 1008], P,
                                  "[BIN 0x81F976] OEM CLT curve, switched "
                                  "340 R pull-up ON, raw counts"),
               "cltSensVal": Value([11432, 11300, 11200, 11100, 10950, 10800,
                                    10600, 10500, 10450, 10400, 10300, 10200,
                                    10100, 10000, 9800, 9600], P,
                                   "[BIN 0x81F976] 143.25..-40 C, 10*C+10000"),
               "iatSensAx": Value([28, 48, 64, 92, 116, 148, 192, 244, 308,
                                   372, 432, 572, 664, 744, 864, 900], P,
                                  "[BIN 0x819739] OEM IAT axis (bytes x4)"),
               "iatSensVal": Value([11403, 11200, 11050, 10900, 10803, 10698,
                                    10600, 10503, 10398, 10323, 10248, 10098,
                                    10000, 9902, 9700, 9602], P,
                                   "[BIN 0x819739] 140.25..-39.75 C"),
               "pinBoost": Value(104, P,
                                 "V79: cavity 104 = LDR, ASIC P7.2, driven "
                                 "through the S5500 frame's P7 image "
                                 "(hcio711.c). The AWT N75 is on 104 too - no "
                                 "reroute. Open loop only on ME7.1.1."),
               # ---- the NATIVE main relay (2026-09-25) -------------------
               "pinMainRelay": Value(23, P,
                                     "Porsche service pinout + me711.pdf: "
                                     "cavity 23 = A_S_HR <- CJ910 pin 16, "
                                     "DME main relay terminal 85. "
                                     "CJ911_Product_Info.pdf (sibling): MR is "
                                     "a low-side stage enabled only by EN1 = "
                                     "KL15 and /EN2 = run-on, so it is a "
                                     "HARDWARE function (MAIN_RELAY_HW). The "
                                     "AWT J271 coil wire (AWT cavity 21) must "
                                     "land here - the internal reroute list. "
                                     "PROBABLE: cavity 23 not yet measured."),
               "mainRelayModeCfg": Value(2, V,
                                         "AUTO - the only mode the native "
                                         "stage can honour; hc_validate "
                                         "refuses OFF/ON on it"),
               # ---- ENGINE FACTS ------------------------------------------------
               # Injector, coil, pressure-sensor and base-map data are NOT
               # part of this preset (see gaps): HaniCore ships no calibration
               # taken from an OEM image. A fresh page keeps the injector flow
               # at 0, which delivers no fuel until the fitted injector's data
               # are entered.
               "displacementCc": Value(1781, V,
                   "AWT engine: bore 81.0 mm x stroke 86.4 mm x 4 = 1781 cc"),
               "injRefPressureKpa": Value(300, P,
                   "the AWT fuel pressure regulator: 3.0 bar, manifold-"
                   "referenced. HaniCore's fuel path does not read it yet"),
               # 0 = the dwell-vs-battery curve decides while cranking too.
               "crankingDwellMsX100": Value(0, V,
                   "0 = use the dwell-vs-battery curve while cranking"),
               # ---- LOAD SOURCE: ALPHA-N x INLET PRESSURE -----------------------
               # The AWT's only pressure sensor (cavity 101) measures the
               # pressure BEFORE the throttle, so speed density cannot see
               # throttling. Load is throttle %, and the air is scaled by the
               # measured inlet pressure (ambient, or boost) - Speeduino's
               # alpha-N + multiplyMAP. A failed sensor uses the MAP estimate
               # table (rpm x throttle).
               "loadSource": Value(1, V, "CAL_LOAD_TPS: alpha-N x inlet "
                                   "pressure - the AWT sensor is upstream of "
                                   "the throttle"),
               "fuelRpmAx": Value([500 + 450 * i for i in range(16)], V,
                                  "HaniCore's default rpm grid, set "
                                  "explicitly"),
               "fuelLoadAx": Value([0, 10, 20, 30, 40, 55, 70, 100, 130, 160,
                                    200, 250, 300, 400, 500, 1000], V,
                                   "throttle %, 0.1 %: dense below 10 % where "
                                   "idle and part load live"),
               # V97: EVERY 2-D TABLE BELOW IS [load][rpm] - one LINE per
               # throttle-% row (fuelLoadAx / ignLoadAx / pedalAx), one
               # COLUMN per rpm - exactly as TunerStudio shows it
               # (generate_config.TABLE_ORDER). Until V97 they were written
               # [rpm][load] and TunerStudio displayed them transposed.
               # ---- DBW ------------------------------------------------
               "dbwEnable": Value(0, V,
                                  "DELIBERATELY OFF. The throttle body has "
                                  "never been driven, no calibration below is "
                                  "measured, and a preset must not arm a "
                                  "motor. A tuner turns this on after the "
                                  "bench procedure in "
                                  "docs/firmware/design/ME711_DBW_PATH.md section 4."),
               "stoichAfrX100": Value(1470, V,
                                      "gasoline stoichiometry, a fuel property"),
               # V83: A STARTING POINT FOR THE BOSCH VAG THROTTLE, FROM THE
               # REFERENCE, NOT INVENTED. rusEFI electronic_throttle.cpp
               # setBoschVAGETB() (P 5.12, I 47, D 0.088 at a 500 Hz loop) and
               # the Bosch bias curve (bins 0 1 5 7 14 65 66 100 % -> -15 -15
               # -10 0 19 20 26 28 %, "default position of about 7 % open"),
               # converted to hc_dbw.c's 5 ms raster and 0.1 % units. SOFTWARE
               # REFERENCE IMPLEMENTATION: tune on the body, dbwEnable stays 0.
               "dbwKp": Value(5120, P, "rusEFI setBoschVAGETB pFactor 5.12"),
               "dbwKi": Value(47000, P, "rusEFI setBoschVAGETB iFactor 47 /s"),
               "dbwKd": Value(17600, P, "rusEFI setBoschVAGETB dFactor 0.088 s"),
               "dbwBiasAx": Value([0, 10, 50, 70, 140, 650, 660, 1000], P,
                                  "rusEFI boschBiasBins, 0.1 % units"),
               "dbwBiasVal": Value([850, 850, 900, 1000, 1190, 1200, 1260,
                                    1280], P,
                                   "rusEFI boschBiasValues, +1000 offset, "
                                   "0.1 % duty"),
               # THE GRAB STORES closed -> min AND open -> max, so after it both
               # tracks of both sensors read 0 closed / 1000 open whichever way
               # their voltage runs (hc_dbw_normalise, V83): SAME.
               "tpsCorrelation": Value(1, V, "SAME after a Grab calibration"),
               "appCorrelation": Value(1, V, "SAME after a Grab calibration"),

               # ---- V90: FIRST-START COMPLETENESS (AWT test 2026-09-26) ------
               # A fresh page + APPLY differed from the car's working page in
               # exactly these: the car only had them from an older bench page.
               # After a full-image flash (blank store) APPLY must be enough.
               "trigSource": Value(1, V,
                   "TRIG_SRC_REAL - the vehicle's own crank/cam; 0 is the "
                   "bench generator only (a fresh page's default)"),
               "fuelPumpMode": Value(1, V,
                   "Auto - prime, crank, run, stop with the engine. 0 is "
                   "'never commanded' (a fresh page's default); the AWT pump "
                   "ran in Auto on the car, 2026-09-26"),
               # V92: THE CRANK REFERENCE IS THE EMPIRICAL START VALUE, AND IT
               # IS NOT PROVEN. 2026-09-27: 268.0 cranked ~10 synchronised
               # revolutions with fuel and spark and never fired; 358.0 started
               # the engine within ~4 revolutions twice and idled it. Every
               # geometry reference disagrees with 358 by ~80 deg: rusEFI VAG
               # 90..93, the operator's aftermarket 78, and the car's own
               # cranking tooth-speed ripple (TDC ~55-100
               # deg after the gap-end tooth).
               # 358 is kept because it is the only value that has run the
               # engine; it must be resolved (V92 tooth profile '!K', bench
               # coil-vs-crank capture) BEFORE ANY LOAD OR BOOST - if the
               # geometry references are right it is ~80 deg over-advanced.
               #
               # (V88..V91 text, the geometry chain:) rusEFI VAG 60-2 (vw.cpp setVwAba 93,
               # vw_b6.cpp 90; rusefi_config.txt: globalTriggerAngleOffset =
               # "angle between TDC and the first trigger event, positive =
               # sync point BEFORE TDC"; the 60-2 shape's zero is the first
               # tooth after the gap, trigger_universal.cpp). HaniCore's zero
               # is the same tooth (hctrig_me711.c: the edge ending the gap is
               # physical 0, the next is slot 1 = 6.0 deg) and engine angle =
               # physical + offset with TDC#1 at engine 0, so TDC at physical
               # +92 needs offset -92 = 3600 - 920. Operator's baseline 92.
               # A starting value: the final number is a timing-light
               # calibration with timingModeCfg FIXED (fixedTimingX10 10.0).
               # V97: THE PHYSICAL CONVENTION (docs/ARCHITECTURE.md).
               # trigAngleX10 = where tooth #1 - the first tooth after the
               # gap, the edge that ENDS it - is, in deg after cylinder-1 TDC.
               # The AWT's is -78.0. Evidence: rusEFI's Quick-Start phase with the
               # B6 cam offset -74..-80; the car's compression stalls and
               # tooth ripple put TDC 70..100 deg after tooth #1.
               # THE CAR'S OWN PAGE RAN ON -2.0 (= the old internal 358.0):
               # 76 deg away, which no software coordinate explains
               # (me711_trigger_angle_proof) - it is kept on the car page by
               # the migration and resolved by the tooth profile and the
               # coil-to-cylinder check, not by this preset. -78 fails SAFE:
               # correct, or retarded - never 76 deg over-advanced.
               "trigAngleX10": Value(-780, P,
                   "78.0 deg BTDC: rusEFI Quick-Start/B6 phase -74..-80, "
                   "the car's compression stalls and tooth-speed ripple, "
                   "timing-gun practice on the 1.8T. "
                   "The car page's -2.0 (old 358.0) contradicts it - "
                   "docs/firmware/design/ME711_CRANK_REFERENCE.md"),
               # THE PEDAL, MEASURED ON THIS CAR (VEHICLE_CAPTURE_20260926T
               # 183642Z, sweep): G79 150 released / 849 floored, G185 75 /
               # 424 - both rise, G185 exactly half. Grab refines them.
               "pedal1Min": Value(150, V, "AWT capture 2026-09-26: APP1 released 150"),
               "pedal1Max": Value(849, V, "AWT capture 2026-09-26: APP1 floored 849"),
               "pedal2Min": Value(75, V, "AWT capture 2026-09-26: APP2 released 75"),
               "pedal2Max": Value(424, V, "AWT capture 2026-09-26: APP2 floored 424"),
               # THE THROTTLE BODY, FROM rusEFI's BOSCH VAG ETB. setBoschVAGETB():
               # primary 890 closed -> 70 open (falls), secondary 102 -> 891
               # (rises). The AWT read 155 on cavity 92 and 866 on cavity 84 at
               # the unpowered limp opening (capture above): 92 is the rising
               # track, 84 the falling one - both ~3..7 % open on these
               # endpoints, inside the 10 % pair tolerance. Grab Closed/Open or
               # Auto Calibrate ETB replace them on the car.
               # V92: THE CAR'S OWN BODY, grabbed 2026-09-27 (Grab Closed /
               # Grab Open, both tracks): TPS1 102 -> 954 (852 counts), TPS2
               # 919 -> 71 (848). rusEFI setBoschVAGETB (102/891, 890/70) is
               # the same shape and was the V88..V91 value.
               "tps1Min": Value(102, V, "AWT Grab 2026-09-27 closed (rising track = cavity 92)"),
               "tps1Max": Value(954, V, "AWT Grab 2026-09-27 open"),
               "tps2Min": Value(919, V, "AWT Grab 2026-09-27 closed (falling track = cavity 84)"),
               "tps2Max": Value(71, V, "AWT Grab 2026-09-27 open"),
               # ---- TABLE AXES AND JUDGEMENT MAPS --------------------------------
               # No VE or ignition table is set (see gaps). The axes are
               # HaniCore's own grid; the target-lambda, warm-up and pedal
               # maps below are stated engineering judgement.
               "ignRpmAx": Value([500 + 450 * i for i in range(16)], V,
                   "HaniCore's default rpm grid, = fuelRpmAx"),
               "ignLoadAx": Value([
                      0,  10,  20,  30,  40,  55,  70, 100, 130, 160, 200, 250, 300, 400, 500, 1000,
                   ], V,
                   "throttle %, 0.1 %, = fuelLoadAx (alpha-N)"),
               # V98: the target lambda table has its own axes; the AWT keeps
               # the ones it was written against (= the ignition axes)
               "lambdaRpmAx": Value([500 + 450 * i for i in range(16)], V, "= ignRpmAx (the afrMap columns below)"),
               "lambdaLoadAx": Value([
                      0,  10,  20,  30,  40,  55,  70, 100, 130, 160, 200, 250, 300, 400, 500, 1000,
                   ], V, "= ignLoadAx, throttle %"),
               # THE INLET PRESSURE A FAILED SENSOR IS REPLACED BY (rusEFI
               # mapEstimateTable). This page's load is alpha-N x the
               # pressure BEFORE the throttle, so the board default - a
               # manifold-pressure shape, ~35 kPa at light throttle - would
               # cut the fuel to ~40 % on a sensor fault. Atmospheric is the
               # inlet pressure without boost. Under boost it reads low (lean
               # by the boost ratio); boost control already drops the valve
               # on a pressure fault, leaving only wastegate-spring boost.
               "mapEstimate": Value([100] * 64, V,
                   "atmospheric inlet pressure, kPa; no boost assumed"),
               # V98: closed-loop fuel ON - it acts only while lambda 1
               # reads READY (CJ120 heater closed loop, pump on, DIAG clean)
               # and the engine is warm. Regions [idle, overrun, power,
               # cruise]: overrun 0 (fuel is cut there), power ADDS only.
               "stftEnable": Value(1, P, "rusEFI fuelClosedLoopCorrection"),
               "stftMaxAdd": Value([10, 0, 5, 10], P, "%, conservative"),
               "stftMaxRemove": Value([10, 0, 0, 10], P,
                                      "%, never lean a full-load cell"),
               # V98r2: THE REGION LOADS ARE IN THE FUEL LOAD'S UNITS - here
               # THROTTLE %. The board default's 35 / 85 are rusEFI's kPa
               # (maxOverrunLoad / minPowerLoad): on this alpha-N page every
               # cell below 35 % throttle - all normal driving - was
               # "overrun" (no trim), and 40..85 % under boost, where the
               # lambda map already enriches, could lose 10 % fuel.
               "stftOverrunLoad": Value(2, P, "throttle %: closed = coasting"),
               "stftPowerLoad": Value(40, P, "throttle %: where the lambda "
                                      "map enriches"),
               # V98r2: DFCO ON - rusEFI coastingFuelCutRpmHigh/Low 1500/
               # 1300, TPS 2 %; the driver's intent is the PEDAL once DBW is
               # on (with DBW off the limp throttle sits at ~6 % and DFCO
               # never arms). Warm only (dfcoMinClt 60 C), never with a
               # failed pedal/TPS/coolant sensor (V98 B4).
               "overrunRpm": Value(1500, P, "rusEFI coastingFuelCutRpmHigh"),
               "overrunResume": Value(1300, P, "rusEFI coastingFuelCutRpmLow"),
               "overrunTpsX10": Value(20, P, "rusEFI coastingFuelCutTps 2 %"),
               # V98r2: coolant protection ON at 115 C (fuel cut above the
               # coolant rev limit, 0 = 3000 rpm; a failed sensor is not
               # judged). The AWT thermostat opens ~87 C, the fan ~100 C.
               "cltMaxDegX10": Value(11150, P, "115 C (10*C + 10000)"),
               # V98r2: IDLE CONTROL ON - it acts only through the ETB (a
               # throttle floor: base(CLT) + bounded PI toward target(CLT),
               # docs/ARCHITECTURE.md), so nothing moves while dbwEnable is 0.
               # Base 9..6.5 % / target 1300..800 rpm are the board's
               # defaults; the V91 car idled ~1000 rpm on the 6.4 % limp
               # opening, which brackets them.
               "idleEnable": Value(1, P, "throttle floor + PI, ETB only"),
               "afrMap": Value([
                    147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147,
                    147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147,
                    147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147,
                    147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147,
                    147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147,
                    147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147,
                    147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147,
                    147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147,
                    147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147,
                    147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147,
                    147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147,
                    147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147,
                    147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147, 147,
                    140, 140, 140, 140, 129, 129, 121, 121, 121, 121, 121, 121, 121, 121, 121, 121,
                    140, 140, 140, 140, 129, 129, 121, 121, 121, 121, 121, 121, 121, 121, 121, 121,
                    140, 140, 140, 140, 129, 129, 121, 121, 121, 121, 121, 121, 121, 121, 121, 121,
                   ], V,
                   "lambda 1.00 part throttle; TPS>=40 %: 0.95 <2000, 0.88 "
                   "<3000, 0.82 above (open-loop start, not an optimum)"),
               # V93: IN THE FIELD'S OWN CONVENTION, 10*C + 10000 (the model
               # declares raw 9500..12000 = -50..200 C, and eng_clt_dc is
               # compared against it raw). V92 wrote 700..2200 (10*C + 1000):
               # the lookup always landed on the last cell and warm-up was
               # 100 % on the car at 17 C instead of 122 %.
               "cltEnrAx": Value([
                    9700, 9800, 9900, 10000, 10100, 10200, 10300, 10400, 10500, 10600, 10700, 10800, 10900, 11000, 11100, 11200,
                   ], V, "-30..120 C as 10*C+10000"),
               "cltEnrVal": Value([
                    170, 160, 150, 140, 131, 122, 116, 111, 107, 104, 102, 100, 100, 100, 100, 100,
                   ], V,
                   "warm-up 170 % at -30 C .. 122 % at 20 C .. 100 % at 80 C"),
               # V97: TRANSIENT FUEL - the X-tau wall film + after-start
               # (firmware/engine/hctrans.c), on the same -30..120 C axis. STATED
               # JUDGEMENT, rusEFI-like starting points (wwaeBeta/wwaeTau
               # class values, more film and a slower one when cold); no
               # AWT wall-film calibration is in this repository. Tune with a
               # wideband on tip-ins (docs/ARCHITECTURE.md).
               "transEnable": Value(1, P, "wall film + after-start on"),
               "wwXPct": Value([55, 52, 48, 45, 42, 40, 37, 35, 33, 31, 30,
                                30, 30, 30, 30, 30], P,
                               "JUDGEMENT: 55 % at -30 C -> 30 % from 70 C"),
               "wwTau": Value([100, 85, 70, 60, 50, 40, 32, 26, 22, 19, 17,
                               15, 15, 15, 15, 15], P,
                              "JUDGEMENT: 2.0 s at -30 C -> 0.3 s from 80 C "
                              "(20 ms units)"),
               "asPct": Value([60, 50, 42, 35, 28, 22, 18, 14, 11, 9, 7, 5,
                               4, 4, 4, 4], P,
                              "JUDGEMENT: +60 % at -30 C -> +5 % at 80 C"),
               "asDecayMs": Value(5000, P, "JUDGEMENT: after-start over 5 s"),
               # V97: ignition corrections vs coolant / intake air. No AWT
               # correction map is shipped, so the curves are 0 (off) - never
               # a fabricated number. The IAT
               # axis is a plain -20..120 C grid so the curve is editable.
               "ignCltCorr": Value([0] * 16, V, "0 = off (no AWT map shipped)"),
               "ignIatAx": Value([9800, 10000, 10200, 10400, 10600, 10800,
                                  11000, 11200], V, "-20..120 C as 10*C+10000"),
               "ignIatCorr": Value([0] * 8, V, "0 = off (no extracted AWT map)"),
               # V97: idle ignition timing - rusEFI setDefaultIdleParameters
               # (P 0.1 deg/rpm, +-10 deg, I 0) and canam's 1 s soft entry;
               # OFF like idleEnable (no AWT idle calibration located:
               # docs/ARCHITECTURE.md)
               "idleTimingEnable": Value(0, P, "off until idle control is on"),
               "idleTimingKp": Value(100, P, "rusEFI default 0.1 deg/rpm"),
               "idleTimingMinX10": Value(-100, P, "rusEFI default -10 deg"),
               "idleTimingMaxX10": Value(100, P, "rusEFI default +10 deg"),
               "idleTimingSoftMs": Value(1000, P, "rusEFI canam 1 s"),
               # V97: the dashpot - OFF: rusEFI's adder is in idle-VALVE %,
               # which says nothing about this throttle body; tune on the car
               "idleDashX10": Value(0, P, "off (no AWT dashpot evidence)"),
               "idleDashHoldMs": Value(1000, P, "JUDGEMENT when enabled"),
               "idleDashDecayMs": Value(2000, P, "JUDGEMENT when enabled"),
               # V97: the check-engine lamp on the AWT's own MIL wire - the
               # AWT ME7.5 map puts the MIL lamp on cavity 47 (the harness
               # plugs it onto this ECU's ASIC P7.0 low side)
               "pinMil": Value(47, P, "docs/HANICORE_ENGINE_IO_MAP.md: AWT MIL "
                               "lamp 47; me711.pdf W12 sheet: LUES2_PX70 -> CJ920 -> cavity 47 A_S_LUES2/A_S_SPOEKUE/A_S_MIL (SAME-GENERATION); family table 47 = MIL_S"),
               # V98r2: ON (project decision; the car page already ran
               # it). The lamp bit is still the W12 sheet's (LUES2_PX70 =
               # ASIC P7.0); this binary actuator-tests BOTH P7.0
               # [0x08F8C6] and P7.1 [0x08F6C8]. First key-on at the car:
               # the AWT cluster's MIL must do the 3 s test - if it does
               # not, the bit is P7.1 (hcio711.c ch_bit[], docs/ARCHITECTURE.md).
               "celEnable": Value(1, P, "ON (project decision); lamp bit "
                                  "P7.0 from the W12 sheet - confirm with "
                                  "the key-on test at the car"),
               "celTestEnable": Value(1, V, "project decision: ON 3 s, OFF 1 s"),
               "celTestOnMs": Value(3000, V, "project decision: 3.0 s"),
               "celTestGapMs": Value(1000, V, "project decision: 1.0 s"),
               # V97: VVT OFF (project decision: the AWT preset does not use
               # cam control). The AWT's own N205 (on/off intake cam
               # adjuster) is on cavity 115 = this ECU's POUT0 stage, so the
               # route is recorded - nothing is driven while the mode is Off.
               "vvtMode": Value([0, 0], V, "OFF by instruction"),
               "pinCam1Sol": Value(115, P, "docs/HANICORE_ENGINE_IO_MAP.md: "
                                   "AWT N205 cam adjust valve on 115"),
               "vvtFreqHz": Value(250, V, "OEM 250 Hz [BIN 0x8C0D78]"),
               "knockMode": Value(0, V, "OFF: no knock calibration for this "
                                  "engine is shipped; calibrate window and "
                                  "thresholds from a MONITOR log"),
               "pedalRpmAx": Value([500 + 450 * i for i in range(16)], V, "= ignRpmAx"),
               "pedalAx": Value([
                      0,  50, 100, 150, 200, 250, 300, 400, 500, 600, 700, 800, 850, 900, 950, 1000,
                   ], V, "pedal %, 0.1 %"),
               "pedalMap": Value([
                        8,   8,   8,   8,   8,   8,   8,   8,   8,   8,   8,   8,   8,   8,   8,   8,
                       12,  12,  12,  12,  12,  12,  12,  12,  12,  12,  12,  12,  12,  12,  12,  12,
                       16,  16,  16,  16,  16,  16,  16,  16,  16,  16,  16,  16,  16,  16,  16,  16,
                       21,  21,  21,  21,  21,  21,  21,  21,  21,  21,  21,  21,  21,  21,  21,  21,
                       27,  27,  27,  27,  27,  27,  27,  27,  27,  27,  27,  27,  27,  27,  27,  27,
                       33,  33,  33,  33,  33,  33,  33,  33,  33,  33,  33,  33,  33,  33,  33,  33,
                       40,  40,  40,  40,  40,  40,  40,  40,  40,  40,  40,  40,  40,  40,  40,  40,
                       56,  56,  56,  56,  56,  56,  56,  56,  56,  56,  56,  56,  56,  56,  56,  56,
                       74,  74,  74,  74,  74,  74,  74,  74,  74,  74,  74,  74,  74,  74,  74,  74,
                       94,  94,  94,  94,  94,  94,  94,  94,  94,  94,  94,  94,  94,  94,  94,  94,
                      116, 116, 116, 116, 116, 116, 116, 116, 116, 116, 116, 116, 116, 116, 116, 116,
                      140, 140, 140, 140, 140, 140, 140, 140, 140, 140, 140, 140, 140, 140, 140, 140,
                      153, 153, 153, 153, 153, 153, 153, 153, 153, 153, 153, 153, 153, 153, 153, 153,
                      167, 167, 167, 167, 167, 167, 167, 167, 167, 167, 167, 167, 167, 167, 167, 167,
                      183, 183, 183, 183, 183, 183, 183, 183, 183, 183, 183, 183, 183, 183, 183, 183,
                      200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200,
                   ], V,
                   "4.0 % at a released pedal (idle air; no idle controller "
                   "exists), progressive to 100 %, rpm-independent"),
               # ---- V92: THE QUICK-START CAM, OBSERVED, NOT DECIDING ----
               # bench measurements. LEVEL method: at physical
               # 204 after the gap-end tooth (engine 126.0 with tooth #1 at
               # -78.0; it was 202.0 on the 358 page) the cam pin is LOW in the revolution that holds TDC#1
               # compression per rusEFI's quick-start phase rule (its sync
               # edge ends the W sector that begins at physical 114). syncMode
               # stays CRANK ONLY: the batch/wasted strategies need no phase,
               # and the mapping inherits the unresolved crank offset. The
               # next capture shows camPhaseStatus / camLow/HighWidthX10.
               "camPhaseMode": Value(1, V, "LEVEL - Bosch quick-start wheel"),
               "camPhaseLevel": Value(0, V,
                   "LOW in the TDC#1-compression revolution (rusEFI QS sync, "
                   "sectors W,N,N,W after the edges at physical 114/294)"),
               "camPhaseAngleX10": Value(1260, V,
                   "engine 126.0 = physical 204 after tooth #1 at trigger "
                   "angle -78.0 (mid-sector, 50 deg margin either way); the "
                   "car page's -2.0 needs 202.0 for the same crank point"),
               "camPhaseConfirm": Value(2, V, "two alternating, consistent checks"),
               # V98r2: inside the field's own 2..40 deg (it was never set:
               # 0 made every PATTERN wheel unusable - selecting the Bosch
               # quick-start wheel and Burning was refused). The QS wheel's
               # closest edges are 80 deg apart, so 10 leaves room for noise.
               "camToothTol": Value(10, V, "half of 80 deg minus margin"),
               # the AWT's wheel (the expected setup), read only by the
               # PATTERN method (camPhaseMode 2, which also needs camEdge =
               # the CPU-rising edges and camRefX10 from a car log); the
               # LEVEL method above ignores it
               "cam1Pattern": Value(3, V, "Bosch quick-start (VAG 1.8T 20V)"),
               "cam2Pattern": Value(0, V, "none: the AWT has one cam"),
               # hc_dbw.c cfg_bad() refuses max duty 0 - the V89 page could
               # never have run DBW whatever the enable said.
               # 80 %: the duty limit the bench DBW qualification ran with
               # (autocal, autotune, commissioning, slams). Battery
               # compensation (13.5 V) is the page default.
               "dbwMaxDutyX10": Value(800, P,
                   "80 %: the limit the bench DBW qualification ran with"),
               # MEASURED, not a reference value: at 0 (the value every page
               # carried until now) the integrator winds 3.5 % duty/s on the
               # irreducible one-count position quantum and never settles, so
               # the plate is held by a ramp instead of by the bias curve.
               # bench measurements; hcdefaults711.c says why 2.
               "dbwPwmHz": Value(2000, V,
                   "2 kHz: this board's bridge frequency (the ME7.1.1 port "
                   "initialisation, hctarget.h); the bench DBW qualification "
                   "ran at 2 kHz, 20 kHz starved the plate on the car"),
               "dbwFrictionX10": Value(80, V,
                   "MEASURED on the VAG bench body (2026-10-05, 12.5 V, 2 kHz): "
                   "break-away band 31-40 %; 8.0 % cut hold error 0.35 -> "
                   "0.15 %, kept the integrator off its clamp and did not add "
                   "overshoot; 12.0 % overshot. bench measurements"),
               "dbwDeadbandX10": Value(2, V,
                   "0.2 % of travel: the 0.1 % position quantum plus one count "
                   "of noise, 84 % of the bench run's settled samples"),
               "dbwSfMode": Value(1, P,
                   "Low means faulted: CJ220 SF is open drain pulled to "
                   "VCC_OUT by R8100 (hctarget.h, bosch_cj220.pdf); judged "
                   "only while the bridge is enabled (hc_dbw.c)"),
           },
           gaps={
               # THE PRESET NO LONGER ASKS FOR 720-DEGREE SYNC, AND THIS
               # NOTE IS WHY IT USED TO AND WHAT CHANGED.
               #
               # UPDATED AT V71. Everything below was written against a preset
               # that declared syncMode = SYNC_CAM1_CYCLE, and it correctly
               # predicted what would happen once the validator was fixed:
               # "The fix belongs in the validator and is recorded for the
               # release after V62". V63 made it. From V63 to V70 this preset
               # was therefore REFUSED - measured, 0x0010 FAULT_SYNC naming
               # CFG_U_CAM_REFS - and a page hc_validate() refuses can never
               # arm an output (12M/3). syncMode is now SYNC_CRANK_ONLY, which
               # is what this page can actually run; the gap below is unchanged
               # and is still the thing that blocks the upgrade.
               #
               # syncMode above is SYNC_CAM1_CYCLE, which is right for an
               # inline four with one cam sensor. But the runtime needs
               # GEOMETRY as well as a mode: geometry_read() sets g_sync_bank
               # to 0 whenever CFG_U_CAM_REFS is 0, so cam_edge() never
               # promotes TRG_SYNC_CRANK to TRG_SYNC_FULL and the engine holds
               # at 360-degree sync for ever, silently.
               #
               # hc_validate() DID NOT catch this when the line above was
               # written: it checked only that a cam cycle mode NAMES a cam
               # pin, and has_cycle_position() was a pure function of syncMode,
               # so the configuration validated clean AND was accepted for
               # sequential injection and sequential COP - neither of which can
               # run without a resolved cycle.
               #
               # IT CATCHES IT NOW. V63 added the rule this note asked for
               # (12M/5): a cam cycle mode requires camEnable and an ODD,
               # non-zero CFG_U_CAM_REFS, and the fault NAMES that field rather
               # than the pin so a tuner does not go looking at the wiring.
               # The consequence was that this preset became UNAPPLIABLE from
               # V63 to V70 - measured, rc 0x0010 on CFG_U_CAM_REFS - which is
               # why syncMode above stepped back to SYNC_CRANK_ONLY.
               #
               # AND THE NUMBER CANNOT BE INVENTED. camRefX10 is the engine
               # angle at which this engine's cam edge actually falls, and no
               # cam edge has ever reached this ECU. It is
               # MEASURED, by turning the crank and reading cam1ObservedAngle
               # with camRefs at 0, which is exactly what stage 4a of
               # scratchpad/v62_full_qual.py does.
               "camRefs / camRefX10 / camWindowX10":
                   "NOT USED BY THIS ENGINE (V92). The 2026-09-27 capture shows "
                   "the AWT cam on cavity 86: four equidistant edges per cycle "
                   "at physical 114/294 - the Bosch quick-start wheel, which "
                   "the REFS method can never resolve. The preset uses the "
                   "LEVEL method (camPhase*) instead, observing only.",
               "camPhase* (cycle sync)": "OBSERVED, NOT DECIDING. syncMode "
                   "stays CRANK ONLY; the LEVEL check angle and level follow "
                   "rusEFI's quick-start phase rule and inherit the unresolved "
                   "crank offset. To decide: resolve trigAngleX10, confirm "
                   "on a capture that camPhaseStatus alternates and matches "
                   "(bits 1+2) and camLow/HighWidthX10 show the W/N sectors, "
                   "then syncMode 2 (cam 1 cycle).",
               "pinVbat": "NO CONNECTOR CAVITY ON THIS BOARD. This preset "
                   "carried cavity 26, which is correct for the ME7.5 board and "
                   "wrong for the ME7.1.1: me711.pdf draws cavity 26 as "
                   "E_A_TANS into TANS_PXA51, the PERIPHERAL ASIC, while the "
                   "main CPU analog block reads UBAT_PA55 on AN5 - an INTERNAL "
                   "RAIL with no cavity at all. The family workbook lists "
                   "cavity 26 as TAN_S|UBE_S and the descriptor generator "
                   "resolved the UBE variant to AN5, which is the wrong variant "
                   "for this board. Battery sense belongs to the HAL's "
                   "TGT_ADC_BATT_CH and needs no routing field. Caught by "
                   "me711_preset_routing_proof once the ME7.1.1 sheet layer "
                   "landed.",
               "pinMainRelay (history)": "This preset once routed the main "
                   "relay into cavity 21, which is KL15 - a power input - "
                   "and was refused by hc_validate (me711_preset_routing_"
                   "proof now gates it). Since 2026-09-25 it routes to the "
                   "NATIVE stage, cavity 23 - see the value's note.",
               "displacementCc (history)": "unset until V88; now 1781 from "
                                 "the engine's bore and stroke.",
               "TPS and APP calibration": "CAL_TPS1_MIN/MAX, CAL_TPS2_MIN/MAX, "
                                          "CAL_PEDAL1_MIN/MAX, "
                                          "CAL_PEDAL2_MIN/MAX are properties "
                                          "of the actual throttle body and "
                                          "pedal on the car. They come from a "
                                          "sweep with the parts connected, "
                                          "never from a preset.",
               "tpsCorrelation / appCorrelation (history)": "until V83 left "
                                                  "unset: the ME7.5 pair is "
                                                  "electrically OPPOSITE. "
                                                  "Since V83 the normalisation "
                                                  "carries direction, so a "
                                                  "Grab-calibrated pair is SAME.",
               "dbwMotorDir": "which DVE2 level opens the plate is a property "
                              "of the motor's wiring. MEASURED in "
                              "docs/firmware/design/ME711_DBW_PATH.md stage A, never guessed - "
                              "getting it wrong makes the controller drive "
                              "away from its target.",
               "dbwMaxDutyX10 / dbwRateX10 / dbwDeadbandX10": "controller "
                                 "limits for a specific throttle body; the "
                                 "board defaults stand. The gains and bias "
                                 "curve ARE seeded since V83, from rusEFI's "
                                 "setBoschVAGETB (a reference, not a "
                                 "measurement) - tune them on the body.",
               "injFlowCcMin / deadtimeVal": "INTENTIONALLY NOT SET - "
                                 "enter the fitted injector's rated flow and "
                                 "dead time vs battery voltage from its data "
                                 "sheet or a flow test. Until then the "
                                 "injector flow is 0 on a fresh page and NO "
                                 "fuel is delivered.",
               "dwellBattAx / dwellBattVal": "INTENTIONALLY NOT SET - the "
                                 "coil's dwell vs battery voltage comes from "
                                 "its data sheet; the firmware's generic "
                                 "curve (6.0 ms at 8 V .. 2.4 ms at 16.4 V) "
                                 "applies until then, and the overdwell "
                                 "limit bounds every charge.",
               "mapSensGrd / mapSensOff": "INTENTIONALLY NOT SET - the "
                                 "pressure sensor's transfer function from "
                                 "its data sheet; the firmware default is a "
                                 "generic 2.5 bar sensor.",
               "veTable / ignMap": "INTENTIONALLY NOT SET - HaniCore ships "
                                 "no base maps derived from an OEM "
                                 "calibration. The firmware's generic "
                                 "defaults (flat 80 % VE, 10..24 deg timing, "
                                 "12 deg at full load) are placeholders: "
                                 "calibrate both on the engine before any "
                                 "load.",
               "knock calibration": "INTENTIONALLY NOT SET - knockMode is "
                                 "OFF. Window, gain, band and thresholds are "
                                 "calibrated from a MONITOR log of the engine.",
               "cranking fuel": "ME7.5 start fuel is a start-rk/wall-film "
                                 "model, not a mass-vs-CLT curve; crankPwVal "
                                 "(mg per cylinder per cycle since V98) "
                                 "stays the board default.",
               "closed loop fuel": "STFT is ON, gated by the sensor's own "
                                 "READY state; limits are conservative and "
                                 "the power region never removes fuel. Not "
                                 "yet qualified on the car.",
               "PRESSURE SENSOR LOCATION": "the AWT sensor on 101 measures "
                                 "the pressure BEFORE the throttle. Speed "
                                 "density wants MANIFOLD pressure; at part "
                                 "throttle this reads ~ambient.",
               "pinClt / pinIat (history)": "Left UNROUTED until V86: the "
                                  "descriptor gave cavities 93/26 no resource "
                                  "because they reach the ASIC, not a main-CPU "
                                  "ADC. V86 names that resource (ASIC AN0/AN1) "
                                  "and the preset routes them.",
               "CLT / IAT transfer": "the curves above characterise THIS "
                                  "ECU's input stages (cavity 93 with its "
                                  "switched 340 R pull-up, cavity 26) with the "
                                  "usual VAG/Bosch NTCs; read from this ECU's "
                                  "own flash, confirmed at one point on the car "
                                  "(raw 923 = 15.6 C). Hardware data, not "
                                  "engine calibration.",
               "pinMap": "ROUTED since V77 (101 -> AN14, PROBABLE, from the "
                         "ME7.1.1 sheet). STILL OPEN: no pressure has been "
                         "applied to cavity 101 on this board, and the sensor "
                         "transfer function must match the sensor fitted.",
           }),
]


# --------------------------------------------------------------------------
# Component presets.
#
# EMPTY BY DESIGN, except for CUSTOM. Not one injector, coil or pressure
# sensor datasheet exists in this repository, so not one of them can be shipped
# as a preset. The framework below is complete and the moment a datasheet lands
# in docs/ a preset is a few lines - which is the correct cost, and much lower
# than the cost of a fabricated dead-time curve running an engine lean.
# --------------------------------------------------------------------------
COMPONENT_PRESETS: dict[str, list[Preset]] = {
    "INJECTORS": [
        Preset(0, "CUSTOM", "Custom injector", "",
               gaps={"flow, reference pressure, dead time vs voltage, dead time "
                     "vs differential pressure, short-pulse correction":
                     "Required fields for any injector preset. A part number "
                     "alone is not a dataset."}),
    ],
    "COILS": [
        Preset(0, "CUSTOM", "Custom ignition coil", "",
               gaps={"driver topology, polarity, dwell vs voltage, cranking "
                     "dwell, maximum dwell":
                     "Required fields for any coil preset. Getting polarity or "
                     "topology wrong destroys the coil or the driver."}),
    ],
    "PRESSURE_SENSORS": [
        Preset(0, "CUSTOM", "Custom pressure sensor", "",
               gaps={"absolute or gauge, transfer function, valid voltage "
                     "window, measurement range":
                     "Required fields. A transfer function that is 10 % wrong "
                     "is a boost target that is 10 % wrong."}),
    ],
}


def all_presets() -> list[Preset]:
    out = list(ENGINE_PRESETS)
    for group in COMPONENT_PRESETS.values():
        out.extend(group)
    return out


def main() -> int:
    show_gaps = "--gaps" in sys.argv
    for p in ENGINE_PRESETS:
        print("[%d] %s  (%s)" % (p.ident, p.name, p.target or "target agnostic"))
        for k, v in p.values.items():
            print("      %-18s = %-24s %-10s %s"
                  % (k, v.value, v.evidence.value, v.source[:80]))
        if show_gaps:
            for k, why in p.gaps.items():
                print("      GAP  %-16s %s" % (k, why[:110]))
        print()
    for group, items in COMPONENT_PRESETS.items():
        print("%s: %d preset(s)" % (group, len(items)))
        if show_gaps:
            for p in items:
                for k, why in p.gaps.items():
                    print("      GAP  %s: %s" % (k, why[:110]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
