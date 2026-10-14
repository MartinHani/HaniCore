#!/usr/bin/env python3
r"""
hanicore_config_def.py - the HaniCore universal configuration MODEL.

    py tools\config_source\generate_config.py        generate + cross-check
    py tools\config_source\hanicore_config_def.py    show the merged layout

WHAT CHANGED, AND WHY. The first version of this file declared its own
4096-byte page with its own hand-typed offsets - `cylinderCount` at 9, where
the firmware's hcconfig.h has `CFG_CYLINDERS` at 2. Two incompatible layouts
both calling themselves the source of truth is not a source of truth; it is a
way to write a cylinder count into a page-size field. Nothing consumed the new
layout, which is the only reason it never did that on a bench.

THE DIRECTION OF AUTHORITY IS NOW ONE WAY:

    firmware/config/hcconfig.h     the LAYOUT. Offsets, types, counts.
              |                             Baked into every flashed image and
              |                             into the frozen V26 bundle.
              v
    hcconfig_layout.py                      parses it
              v
    this file                               attaches METADATA to each slot by
                                            name: units, scaling, limits,
                                            apply policy, apply group,
                                            SAFETY_CRITICAL, TunerStudio name
              v
    generate_config.py                      emits C + .ini, and FAILS if a
                                            firmware slot has no metadata or a
                                            metadata entry names no slot

So an offset is never typed twice. Adding a field means editing hcconfig.h AND
this file; forgetting either is a build error, not a silent gauge reading the
wrong bytes.

APPLY POLICY AND SAFETY_CRITICAL ARE ORTHOGONAL. `apply` is WHEN a change may
reach the running engine; `safety_critical` is a separate boolean about what
happens if the value is wrong. An oil-pressure shutdown threshold is
LIVE_APPLY and SAFETY_CRITICAL at the same time, and the model has to be able
to say that.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field as dc_field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

from hanicore_config_schema import (  # noqa: E402
    ApplyGroup,
    ApplyPolicy,
    ConfigEnum,
    EvidenceClass,
)
import hcconfig_layout  # noqa: E402

L = ApplyPolicy.LIVE_APPLY
Z = ApplyPolicy.RPM_ZERO_APPLY
R = ApplyPolicy.RESTART_REQUIRED

G = ApplyGroup

# The sentinel every physical-pin field uses for "not assigned".
PIN_NONE = 255


# TUNERSTUDIO HAS ONE NAMESPACE FOR [Constants] AND [OutputChannels].
#
# A name that appears in both is ambiguous: a dialog `field =` must bind a
# page Constant while a `gauge`/`indicator`/`entry` must bind an output
# channel, and TunerStudio then reports `invalid Constant` /
# `EcuParameter not found` and refuses to load the file. That is what stopped
# the V30 and V31 .ini files loading in real TunerStudio 3.3.01 while every
# static gate here was green.
#
# So a SETTING whose name would collide with a runtime channel carries a
# `Cfg` suffix - the convention the V29B .ini used, which is the one .ini
# this project has confirmed loads. `outputsArmedCfg` and `mainRelayModeCfg`
# are those two. tests/tunerstudio/ts_ini_namespace_proof.py fails the build if any new
# collision appears, so this does not have to be remembered.
#
# ==========================================================================
# 1. ENUMS
# ==========================================================================
# V98: THREE NAMED STRATEGIES (docs/ARCHITECTURE.md). Value 1 keeps
# the meaning it always had on this page - VE(rpm, TPS) x the density of the
# MEASURED pressure, Speeduino's alpha-N with multiplyMAP - so no page changes
# strategy by being migrated; value 2 is rusEFI's pure alpha-N
# (alphan_airmass.cpp: 101.325 kPa, 20 C or IAT), which needs no pressure
# sensor at all.
ENUM_LOAD_SOURCE = ConfigEnum("LoadSource", [
    (0, "LOAD_MAP", "Speed density (manifold pressure)"),
    (1, "LOAD_TPS", "Alpha-N + measured pressure"),
    (2, "LOAD_ALPHAN", "Pure Alpha-N (no pressure sensor)"),
], "Load model")

# V98: rusEFI's firing_order_e numbering (controllers/algo/firing_order.h),
# so a rusEFI tune's firingOrder maps 1:1 - except 0, which rusEFI spends on
# a one-cylinder engine and HaniCore on CUSTOM (a single cylinder at TDC 0 is
# the same geometry either way). Converted into TDC angles at apply time
# (hcengctl711.c hc_fo_position), never per tooth.
ENUM_FIRING_ORDER = ConfigEnum("FiringOrder", [
    (0, "FO_CUSTOM", "Custom - TDC angle per cylinder"),
    (8, "FO_1_2", "1-2"),
    (10, "FO_1_2_3", "1-2-3"),
    (24, "FO_1_3_2", "1-3-2"),
    (1, "FO_1_3_4_2", "1-3-4-2 (inline 4)"),
    (2, "FO_1_2_4_3", "1-2-4-3"),
    (3, "FO_1_3_2_4", "1-3-2-4 (flat 4)"),
    (17, "FO_1_4_3_2", "1-4-3-2 (VW air-cooled)"),
    (35, "FO_1_2_3_4", "1-2-3-4"),
    (6, "FO_1_2_4_5_3", "1-2-4-5-3 (inline 5)"),
    (4, "FO_1_5_3_6_2_4", "1-5-3-6-2-4 (inline 6 / VR6)"),
    (30, "FO_1_6_5_4_3_2", "1-6-5-4-3-2"),
    (31, "FO_1_4_5_2_3_6", "1-4-5-2-3-6"),
    (7, "FO_1_4_2_5_3_6", "1-4-2-5-3-6"),
    (9, "FO_1_2_3_4_5_6", "1-2-3-4-5-6 (60 deg V6)"),
    (13, "FO_1_6_3_2_5_4", "1-6-3-2-5-4"),
    (27, "FO_1_4_3_6_2_5", "1-4-3-6-2-5 (VAG V6)"),
    (29, "FO_1_6_2_4_3_5", "1-6-2-4-3-5"),
    (36, "FO_1_6_2_5_3_4", "1-6-2-5-3-4 (Porsche flat 6)"),
    (5, "FO_1_8_4_3_6_5_7_2", "1-8-4-3-6-5-7-2"),
    (11, "FO_1_8_7_2_6_5_4_3", "1-8-7-2-6-5-4-3"),
    (12, "FO_1_5_4_2_6_3_7_8", "1-5-4-2-6-3-7-8"),
    (19, "FO_1_2_7_8_4_5_6_3", "1-2-7-8-4-5-6-3"),
    (20, "FO_1_3_7_2_6_5_4_8", "1-3-7-2-6-5-4-8"),
    (25, "FO_1_2_3_4_5_6_7_8", "1-2-3-4-5-6-7-8"),
    (26, "FO_1_5_4_8_6_3_7_2", "1-5-4-8-6-3-7-2 (Audi V8)"),
    (32, "FO_1_5_4_8_3_7_2_6", "1-5-4-8-3-7-2-6"),
    (28, "FO_1_8_7_3_6_5_4_2", "1-8-7-3-6-5-4-2"),
    (34, "FO_1_8_6_2_7_3_4_5", "1-8-6-2-7-3-4-5"),
    (14, "FO_1_10_9_4_3_6_5_8_7_2", "1-10-9-4-3-6-5-8-7-2 (V10)"),
    (33, "FO_1_6_5_10_2_7_3_8_4_9", "1-6-5-10-2-7-3-8-4-9 (V10)"),
    (15, "FO_1_7_5_11_3_9_6_12_2_8_4_10", "1-7-5-11-3-9-6-12-2-8-4-10 (V12)"),
    (16, "FO_1_7_4_10_2_8_6_12_3_9_5_11", "1-7-4-10-2-8-6-12-3-9-5-11 (V12)"),
    (18, "FO_1_12_5_8_3_10_6_7_2_11_4_9", "1-12-5-8-3-10-6-7-2-11-4-9 (W12)"),
    (23, "FO_1_2_3_4_5_6_7_8_9_10_11_12", "1-2-3-...-12"),
], "Firing order")

# V98: rusEFI's ignOverrideMode / afrOverrideMode (fuel_computer.cpp
# getLoadOverride): which load addresses the ignition and target-lambda
# tables. 0 = the fuel table's own load (rusEFI AFR_None).
ENUM_LOAD_AXIS = ConfigEnum("LoadAxis", [
    (0, "LOADAX_FUEL", "Same as the fuel load"),
    (1, "LOADAX_MAP", "Pressure sensor (kPa)"),
    (2, "LOADAX_TPS", "Throttle position (%)"),
    (3, "LOADAX_FILL", "Cylinder filling (%)"),
], "Table load axis")

ENUM_INJ_PHASE = ConfigEnum("InjPhaseMode", [
    (0, "INJPH_SINGLE", "Single angle"),
    (1, "INJPH_TABLE", "Table (rpm x load)"),
], "Injection timing source")

ENUM_TRIG_EDGE = ConfigEnum("TriggerEdge", [
    (0, "EDGE_FALLING", "Falling"),
    (1, "EDGE_RISING", "Rising"),
], "Capture active edge")

ENUM_TRIG_SOURCE = ConfigEnum("TriggerSource", [
    (0, "TRIG_SRC_BENCH", "Bench generator only"),
    (1, "TRIG_SRC_REAL", "Real crank and cam captures"),
], "Which trigger input may be armed at all")

ENUM_MAIN_RELAY = ConfigEnum("MainRelayMode", [
    (0, "RELAY_OFF", "Off"),
    (1, "RELAY_ON", "On"),
    (2, "RELAY_AUTO", "Auto"),
], "Generic relay operating mode")

ENUM_REVLIM = ConfigEnum("RevLimMode", [
    (0, "REVLIM_SPARK", "Spark cut"),
    (1, "REVLIM_FUEL", "Fuel cut"),
    (2, "REVLIM_BOTH", "Both"),
], "Rev limiter cut mechanism")

ENUM_BOOST_MODE = ConfigEnum("BoostMode", [
    (0, "BOOST_OPEN_LOOP", "Open loop duty only"),
    (1, "BOOST_CLOSED_LOOP", "Closed loop on target"),
], "Boost control strategy")

ENUM_PUMP_MODE = ConfigEnum("FuelPumpMode", [
    (0, "PUMP_OFF", "Off - never commanded"),
    (1, "PUMP_AUTO", "Auto - prime, crank, run, stop with the engine"),
])
ENUM_DBW_BATT = ConfigEnum("DbwBattComp", [
    (0, "DBW_BATT_ON", "On - scale to 13.5 V (Bosch DLRUBSOLL)"),
    (1, "DBW_BATT_OFF", "Off - duty as computed"),
], "Throttle motor battery-voltage compensation")
ENUM_DBW_SF = ConfigEnum("DbwSfMode", [
    (0, "DBW_SF_IGNORE", "Ignore the bridge fault pin"),
    (1, "DBW_SF_LOW_IS_FAULT", "Low means faulted"),
    (2, "DBW_SF_HIGH_IS_FAULT", "High means faulted"),
], "How to read the H-bridge status pin")

# ---- new universal enums --------------------------------------------------
ENUM_INJ_STRATEGY = ConfigEnum("InjStrategy", [
    (0, "INJ_BATCH", "Batch - all injectors together, crank sync is enough"),
    (1, "INJ_SEMI_SEQ", "Semi-sequential - pairs, crank sync is enough"),
    (2, "INJ_SEQUENTIAL", "Sequential - one per cylinder once the cycle is "
                          "known; two halves per cylinder until then"),
], "Fuel injection execution strategy")

# V97: knock control (hcknock711.c, docs/ARCHITECTURE.md)
ENUM_KNOCK_MODE = ConfigEnum("KnockMode", [
    (0, "KNOCK_OFF", "Off"),
    (1, "KNOCK_MONITOR", "Monitor - measure and detect, no retard"),
    (2, "KNOCK_ACTIVE", "Active - detected knock retards the spark"),
], "Knock control")
# The CC195's nine centre frequencies and the band code each one takes on
# BF0..BF3, read from this ECU's binary [BIN 0x09453E, jump table 0x815D42]
# and identical in the AWT's own 4B0906018DC [0x07447A, 0x815CA0].
ENUM_KNOCK_BAND = ConfigEnum("KnockBand", [
    (0, "KNOCK_BAND_5K", "5 kHz"), (1, "KNOCK_BAND_6K", "6 kHz"),
    (2, "KNOCK_BAND_7K", "7 kHz"), (3, "KNOCK_BAND_8K", "8 kHz"),
    (4, "KNOCK_BAND_9K", "9 kHz"), (5, "KNOCK_BAND_10K", "10 kHz"),
    (6, "KNOCK_BAND_12K", "12 kHz"), (7, "KNOCK_BAND_14K", "14 kHz"),
    (8, "KNOCK_BAND_16K", "16 kHz"),
], "CC195 band-pass centre frequency")
# The CC195's seven gains ("7 factors from 2 to 128", bosch_cc195.pdf); the
# OEM steps them by x2 [BIN 0x09528C] through the code table 0x811373
# (0,1,2,3,5,6,7 - the same table in the AWT's binary at 0x81153F).
ENUM_KNOCK_GAIN = ConfigEnum("KnockGain", [
    (0, "KNOCK_GAIN_2", "x2"), (1, "KNOCK_GAIN_4", "x4"),
    (2, "KNOCK_GAIN_8", "x8"), (3, "KNOCK_GAIN_16", "x16"),
    (4, "KNOCK_GAIN_32", "x32"), (5, "KNOCK_GAIN_64", "x64"),
    (6, "KNOCK_GAIN_128", "x128"),
], "CC195 gain step")
ENUM_KNOCK_SENSOR = ConfigEnum("KnockSensor", [
    (0, "KNOCK_SENS_1", "Sensor 1"), (1, "KNOCK_SENS_2", "Sensor 2"),
    (2, "KNOCK_SENS_3", "Sensor 3"), (3, "KNOCK_SENS_4", "Sensor 4"),
], "Knock sensor serving this cylinder")

# V97: VVT (hcvvt711.c + firmware/control/hcvvt.c)
ENUM_VVT_MODE = ConfigEnum("VvtMode", [
    (0, "VVT_OFF", "Off"),
    (1, "VVT_SWITCH", "On/off adjuster - target > 0 = solenoid ON"),
    (2, "VVT_CLOSED", "Closed loop on the measured cam position"),
], "Cam phase control")

ENUM_OFF_ON = ConfigEnum("OffOn", [
    (0, "HC_OFF", "Off"),
    (1, "HC_ON", "On"),
], "Off / on")

ENUM_INJ_TIMING = ConfigEnum("InjTimingMode", [
    (0, "INJ_TIMING_START", "Start of injection"),
    (1, "INJ_TIMING_END", "End of injection"),
], "What the injection angle names")

ENUM_IGN_STRATEGY = ConfigEnum("IgnStrategy", [
    (0, "IGN_WASTED_PAIRED", "Wasted spark, paired coils - crank sync is enough"),
    (1, "IGN_WASTED_COP", "Wasted COP - one coil per cylinder, fired twice per "
                          "cycle, crank sync is enough"),
    (2, "IGN_SEQUENTIAL_COP", "Sequential COP - once per cycle when the cycle "
                              "is known; wasted COP until then"),
    (3, "IGN_DISTRIBUTOR", "Single coil through a distributor"),
], "Ignition execution strategy. NOT the same question as how many coils there "
   "are: wasted COP uses individual coils and still runs crank-only.")

ENUM_SYNC_MODE = ConfigEnum("SyncMode", [
    (0, "SYNC_NONE", "None - bench only, nothing may be driven"),
    (1, "SYNC_CRANK_ONLY", "Crank position only, 360 deg"),
    (2, "SYNC_CAM1_CYCLE", "Crank plus camshaft 1, full 720 deg cycle"),
    (3, "SYNC_CAM2_CYCLE", "Crank plus camshaft 2, full 720 deg cycle"),
    (4, "SYNC_DUAL_CAM", "Crank plus both camshafts"),
], "How much engine position the decoder is configured to establish")

ENUM_CAM_PHASE = ConfigEnum("CamPhaseMethod", [
    (0, "CAMPH_REFS", "Equally spaced reference edges"),
    (1, "CAMPH_LEVEL", "Cam level at one crank angle (Bosch quick-start / single window)"),
    (2, "CAMPH_PATTERN", "Cam wheel pattern (tooth spacing, then angle)"),
], "How the camshaft input decides which revolution of the cycle this is")

# V97: the cam wheel library of firmware/engine/hccam.c (tooth angles from rusEFI's
# decoders, cited there). The numbers are HCCAM_P_* and must stay equal.
ENUM_CAM_PATTERN = ConfigEnum("CamPattern", [
    (0, "CAMPAT_NONE", "None"),
    (1, "CAMPAT_SINGLE", "Single tooth per cycle"),
    (2, "CAMPAT_EQUAL", "Equal teeth, count = camRefs"),
    (3, "CAMPAT_QUICKSTART", "Bosch quick-start (VAG 1.8T 20V)"),
    (4, "CAMPAT_HONDA_K_4P1", "Honda K exhaust 4+1"),
    (5, "CAMPAT_BARRA_3P1", "Ford Barra 3+1"),
    (6, "CAMPAT_TOYOTA_4M1", "Toyota 4-1"),
    (7, "CAMPAT_NISSAN_VQ", "Nissan VQ"),
    (8, "CAMPAT_MIATA_NB", "Mazda Miata NB"),
], "The cam wheel, for camPhaseMode PATTERN")

ENUM_TRIG_DECODER = ConfigEnum("TriggerDecoder", [
    (0, "TRIGDEC_CUSTOM", "Custom / none"),
    (1, "TRIGDEC_MISSING_TOOTH", "Missing tooth wheel (60-2, 36-1, ...)"),
    (2, "TRIGDEC_EVEN_TOOTH", "Evenly spaced teeth, cam supplies the reference"),
    (3, "TRIGDEC_BOSCH_ME711", "Bosch ME7.1.1 60-2, the recovered gap rule"),
], "Crank decoder. Validation rules are PER DECODER - a tooth-count or "
   "gap-ratio rule that belongs to the missing-tooth decoder must not be "
   "enforced against a decoder that has no gap.")

ENUM_TRACK_CORR = ConfigEnum("TrackCorrelation", [
    (0, "TRACK_OPPOSITE", "Opposite after calibration (both min < max)"),
    (1, "TRACK_SAME", "Same after calibration - use with Grab (min = closed)"),
    (2, "TRACK_SCALED", "Same direction, different scale/offset"),
], "Dual-track correlation model for TPS and APP. Do NOT assume opposite: it "
   "is true of the ME7.5 pair and is not a law.")

ENUM_LAMBDA_SRC = ConfigEnum("LambdaSource", [
    (0, "LAMBDA_OFF", "Disabled"),
    (1, "LAMBDA_INTERNAL_LSU", "On-board LSU 4.2 controller"),
    (2, "LAMBDA_EXTERNAL_ANALOG", "External controller, analog 0-5 V"),
    (3, "LAMBDA_CAN", "External controller over CAN"),
], "Wideband controller source")

# V100: WHEN THE LSU HEATER MAY RUN. rusEFI heater_control.cpp
# HeaterControllerBase::GetNextState() takes a HeaterAllow plus the supply
# voltage and nothing else - HeaterAllow::Unknown PERMITS heating and no
# engine-turning term exists in it. V96..V99 required the engine to be
# turning under sync, which on the AWT meant lambda never became READY at
# all (~40 s needed, runs were 18..42 s with
# 3..7 s gaps). IGNITION is the default and the recommended workflow: the
# sensor warms while the key is on, so it is a measurement before the first
# crank, which is what makes it useful for tuning.
ENUM_LAMBDA_HEAT = ConfigEnum("LambdaHeaterPolicy", [
    (0, "LAMBDA_HEAT_OFF", "Disabled - never heat"),
    (1, "LAMBDA_HEAT_IGNITION", "Ignition on - warm before the start"),
    (2, "LAMBDA_HEAT_RUNNING", "Engine running only"),
], "When the wideband heater may run")

ENUM_BANK = ConfigEnum("Bank", [
    (0, "BANK_NONE", "Not assigned"),
    (1, "BANK_1", "Bank 1"),
    (2, "BANK_2", "Bank 2"),
    (3, "BANK_BOTH", "Both banks"),
], "Cylinder bank association")

ENUM_TEST_MODE = ConfigEnum("TestMode", [
    (0, "TEST_NONE", "Off"),
    (1, "TEST_FUEL_PUMP", "Fuel pump relay"),
    (2, "TEST_FAN", "Cooling fan"),
    (3, "TEST_INJECTOR", "One injector"),
    (4, "TEST_COIL", "One ignition coil"),
    (5, "TEST_BOOST", "Boost solenoid"),
    (6, "TEST_VVT", "Cam timing solenoid"),
    (7, "TEST_IDLE", "Idle actuator"),
    (8, "TEST_DBW", "Electronic throttle"),
    (9, "TEST_GENERIC_OUT", "A generic output"),
    (10, "TEST_MAIN_RELAY", "Main relay"),
], "Bench test selection. Every entry is gated on RPM = 0 and on "
   "CFG_OUTPUTS_ARMED; selecting one does not by itself drive anything.")

ALL_ENUMS = [
    ENUM_LOAD_SOURCE, ENUM_TRIG_EDGE, ENUM_TRIG_SOURCE, ENUM_MAIN_RELAY,
    ENUM_REVLIM, ENUM_BOOST_MODE, ENUM_DBW_SF, ENUM_PUMP_MODE,
    ENUM_INJ_STRATEGY,
    ENUM_IGN_STRATEGY, ENUM_SYNC_MODE, ENUM_TRIG_DECODER, ENUM_TRACK_CORR,
    ENUM_LAMBDA_SRC, ENUM_LAMBDA_HEAT, ENUM_BANK, ENUM_TEST_MODE,
    ENUM_CAM_PATTERN,
]

ENUM_FUEL_MODEL = ConfigEnum("FuelModel", [(0,"FUEL_LEGACY","Choose by load model"),(1,"FUEL_ALPHAN","Pure Alpha-N (TPS)"),(2,"FUEL_MANIFOLD","Speed density (manifold pressure)"),(3,"FUEL_CHARGE","Boosted Alpha-N (TPS + charge pressure)")], "Fuel model")
ENUM_PRESSURE_ROLE = ConfigEnum("PressureRole", [(0,"PRESSURE_NONE","None fitted"),(1,"PRESSURE_MANIFOLD","Manifold pressure (after the throttle)"),(2,"PRESSURE_CHARGE","Charge pressure (before the throttle)")], "Where the pressure sensor measures")
ENUM_DENSITY_POLICY = ConfigEnum("DensityPolicy", [(0,"DENSITY_FIXED","Reference pressure - Pure Alpha-N"),(1,"DENSITY_ABSOLUTE","Measured pressure - Speed density / Boosted Alpha-N"),(2,"DENSITY_BLEND","Ambient + boost blend - Boosted Alpha-N")], "Air density pressure")
ENUM_BARO_SOURCE = ConfigEnum("BaroSource", [(0,"BARO_FIXED","Reference pressure (fixed)"),(1,"BARO_STOPPED","Pressure sensor with the engine stopped"),(2,"BARO_DEDICATED","Onboard barometric sensor")], "Ambient pressure source")
ALL_ENUMS += [ENUM_FUEL_MODEL, ENUM_PRESSURE_ROLE, ENUM_DENSITY_POLICY, ENUM_BARO_SOURCE]


# ==========================================================================
# 2. THE METADATA MODEL
# ==========================================================================
@dataclass
class Meta:
    """Metadata for ONE hcconfig.h layout slot. Carries no offset: the offset
    is the firmware's, and duplicating it here is the defect this file exists
    to remove."""
    slot: str                       # the hcconfig.h #define name
    ts: str                         # TunerStudio field name
    label: str
    apply: ApplyPolicy
    group: ApplyGroup
    units: str = ""
    scale: float = 1.0
    translate: float = 0.0
    digits: int = 0
    lo: float = 0
    hi: float = 65535
    safety_critical: bool = False
    enum: ConfigEnum | None = None
    category: str = "General"
    note: str = ""
    is_pin: bool = False            # value is a PHYSICAL ECU pin 1..121 / 255
    pin_needs: int = 0              # PinCap bits the pin must have


@dataclass
class NewField:
    """A universal field that does not exist in hcconfig.h yet. The generator
    lays these out inside CFG_UNIVERSAL_BASE and emits the hcconfig.h block to
    paste in; it never invents an offset for an existing field."""
    slot: str
    ctype: str                      # u8 | u16 | s16
    count: int = 1
    meta: Meta | None = None
    comment: str = ""
    offset: int = 0                 # assigned by layout()


# --------------------------------------------------------------------------
# 2a. Metadata for every slot hcconfig.h already defines.
#
# Units and scaling are TRANSCRIBED FROM hcconfig.h's own comments, which are
# the only place the scaling of a stored count is written down. A Meta's scaling
# means display = raw*scale + translate, lo/hi in RAW counts; generate_config
# .ts_scaling() converts that to TunerStudio's (raw + translate) * scale.
# TEMPERATURES ARE STORED (degC + CAL_TEMP_BIAS) * 10 = 10*degC + 10000 - read
# hcconfig.c and hc_airfuel.c, not the "+1000" in hcconfig.h's one-line
# comment - so they are scale 0.1, translate -1000, and -50..200 C is RAW
# 9500..12000. Until 2026-09-25 they said translate -100 / raw 500..3000 and
# TunerStudio showed the 80 C coolant substitute as 1070 C.
# --------------------------------------------------------------------------
LEGACY: list[Meta] = [
    # ---- schema / engine description ------------------------------------
    Meta("CFG_VERSION", "cfgVersion", "Configuration version", R, G.GENERAL,
         lo=0, hi=255, safety_critical=True, category="Controller",
         note="Firmware writes this. A page whose version does not match the "
              "build must be migrated, not used."),
    Meta("CFG_CYLINDERS", "cylinders", "Cylinder count", R, G.ENGINE_SETUP,
         lo=1, hi=12, safety_critical=True, category="Engine",
         note="RESTART_REQUIRED: the scheduler's per-cylinder slot tables are "
              "sized at init."),
    Meta("CFG_STROKES", "strokes", "Engine cycle (strokes)", R, G.ENGINE_SETUP,
         lo=2, hi=4, safety_critical=True, category="Engine"),
    Meta("CFG_TDC_CYL", "tdcCylDegX10", "Cylinder TDC angle", Z, G.ENGINE_SETUP,
         units="deg", scale=0.1, digits=1, lo=0, hi=7200, safety_critical=True,
         category="Engine",
         note="Engine degrees after cylinder 1's TDC to each cylinder's TDC. "
              "Used only with firing order CUSTOM (odd-fire engines); a named "
              "firing order computes them."),

    # ---- crank trigger ---------------------------------------------------
    Meta("CFG_SY_TEETH", "syTeeth", "Crank wheel teeth", Z, G.TRIGGER_SETUP,
         lo=0, hi=200, safety_critical=True, category="Trigger",
         note="Funktionsrahmen SY_TEETH. Only meaningful for a toothed decoder."),
    Meta("CFG_SY_GAP", "syGap", "Missing teeth", Z, G.TRIGGER_SETUP,
         lo=0, hi=8, safety_critical=True, category="Trigger",
         note="Funktionsrahmen SY_GAP. 0 for a decoder with no gap."),
    Meta("CFG_TRIG_EDGE", "trigEdge", "Crank capture edge", Z, G.TRIGGER_SETUP,
         lo=0, hi=1, safety_critical=True, enum=ENUM_TRIG_EDGE, category="Trigger"),
    Meta("CFG_TRIG_GAP_RATIO_X10", "trigGapRatioX10", "Gap detect ratio", Z,
         G.TRIGGER_SETUP, scale=0.1, digits=1, lo=0, hi=600, safety_critical=True,
         category="Trigger",
         note="Missing-tooth decoder only."),
    Meta("CFG_TRIG_MIN_TEETH", "trigMinTeeth", "Good teeth before sync", Z,
         G.TRIGGER_SETUP, lo=0, hi=255, category="Trigger"),
    Meta("CFG_TRIG_TIMEOUT_MS", "trigTimeoutMs", "Stall timeout", Z,
         G.TRIGGER_SETUP, units="ms", lo=1, hi=255, safety_critical=True,
         category="Trigger"),
    Meta("CFG_CAM_ENABLE", "camEnable", "Camshaft input enabled", Z,
         G.TRIGGER_SETUP, lo=0, hi=1, category="Trigger"),
    Meta("CFG_CAM_EDGE", "camEdge", "Camshaft capture edge", Z, G.TRIGGER_SETUP,
         lo=0, hi=1, enum=ENUM_TRIG_EDGE, category="Trigger"),
    Meta("CFG_TRIG_SOURCE", "trigSource", "Trigger arming source", Z,
         G.TRIGGER_SETUP, lo=0, hi=1, safety_critical=True, enum=ENUM_TRIG_SOURCE,
         category="Trigger",
         note="0 keeps the real captures disarmed. A floating crank input read "
              "as 20000 rpm on the bench and starved the K-line."),
    Meta("CFG_SIM_RPM", "simRpm", "Bench generator speed", L, G.TRIGGER_SETUP,
         units="rpm", lo=0, hi=8000, category="Controller"),

    # ---- speeds and limits ----------------------------------------------
    Meta("CFG_REV_MAX", "revMax", "Scheduler upper bound", R, G.ENGINE_SETUP,
         units="rpm", lo=0, hi=20000, safety_critical=True, category="Engine"),
    Meta("CFG_REV_MIN", "revMin", "Minimum recognised speed", Z, G.ENGINE_SETUP,
         units="rpm", lo=0, hi=2000, category="Engine"),
    Meta("CFG_REV_LIMIT", "revLimit", "Rev limit", L, G.ENGINE_SETUP,
         units="rpm", lo=0, hi=20000, safety_critical=True, category="Safety"),
    Meta("CFG_CRANK_RPM_MAX", "crankRpmMax", "Cranking threshold", L,
         G.ENGINE_SETUP, units="rpm", lo=0, hi=2000, category="Engine"),

    # ---- output routing (legacy channel indices) -------------------------
    Meta("CFG_INJ_CHANNEL", "injChannel", "Injector output channel", Z,
         G.INJECTOR_ROUTING, lo=0, hi=255, safety_critical=True, category="Fuel",
         note="Board output INDEX, 255 = unused. The universal block's "
              "injPin[] carries the physical connector pin for the same "
              "cylinder; the router keeps them consistent."),
    Meta("CFG_IGN_CHANNEL", "ignChannel", "Ignition output channel", Z,
         G.IGNITION_ROUTING, lo=0, hi=255, safety_critical=True,
         category="Ignition"),

    # ---- basic fuel and spark -------------------------------------------
    Meta("CFG_DWELL_MS_X100", "dwellMsX100", "Nominal dwell", L, G.TABLES,
         units="ms", scale=0.01, digits=2, lo=0, hi=1000, safety_critical=True,
         category="Ignition"),
    Meta("CFG_INJ_DEADTIME_US", "injDeadtimeUs", "Injector dead time", L, G.TABLES,
         units="us", lo=0, hi=10000, category="Fuel"),
    Meta("CFG_INJ_START_DEG_X10", "injStartDegX10", "Injection angle (single, deg BTDC)", L,
         G.TABLES, units="deg", scale=0.1, digits=1, lo=0, hi=7200, category="Fuel"),
    Meta("CFG_IGN_ADVANCE_DEG_X10", "ignAdvanceDegX10", "Cranking timing",
         L, G.TABLES, units="deg", scale=0.1, digits=1, lo=0, hi=900,
         safety_critical=True, category="Ignition"),

    # ---- sensor scaling --------------------------------------------------
    Meta("CFG_ADC_BATT_FS_DV", "adcBattFsDv", "Battery ADC full scale", L,
         G.SENSOR_ROUTING, units="V", scale=0.1, digits=1, lo=0, hi=600,
         category="Sensors"),
    Meta("CFG_CLT_PULLUP_OHM", "cltPullupOhm", "Coolant pull-up", L,
         G.SENSOR_ROUTING, units="ohm", lo=0, hi=65535, category="Sensors"),
    Meta("CFG_IAT_PULLUP_OHM", "iatPullupOhm", "Intake air pull-up", L,
         G.SENSOR_ROUTING, units="ohm", lo=0, hi=65535, category="Sensors"),

    # ---- bench and safety ------------------------------------------------
    Meta("CFG_OUTPUTS_ARMED", "outputsArmedCfg", "Retired: no effect", Z,
         G.GENERAL, lo=0, hi=1, safety_critical=True, category="Safety",
         note="RETIRED V84. Used to gate every engine output behind a manual "
              "arm; normal operation is now trigger/scheduler driven and a "
              "bench test's deliberate act is its own bounded command "
              ". Kept in the page so HC_CFG_LAYOUT_ID and every "
              "Burned calibration are unchanged; no firmware path reads it "
              "on ME7.1.1. Not shown in TunerStudio."),
    Meta("CFG_FLAGS", "cfgFlags", "Spare flags", L, G.GENERAL, lo=0, hi=255,
         category="Controller"),
    Meta("CFG_MAIN_RELAY_MODE", "mainRelayModeCfg", "Main relay mode", L, G.RELAY_SETUP,
         lo=0, hi=2, safety_critical=True, enum=ENUM_MAIN_RELAY, category="I/O"),
    Meta("CFG_MAIN_RELAY_GRACE_MS", "mainRelayGraceMs", "Relay feedback grace", L,
         G.RELAY_SETUP, units="ms", lo=0, hi=5000, category="I/O"),

    # ---- fuel table ------------------------------------------------------
    Meta("CAL_FUEL_MAP", "veTable", "Volumetric efficiency", L, G.TABLES,
         units="%", scale=0.1, digits=1, lo=0, hi=4000, category="Fuel",
         note="VE, not pulse width. This table WAS a byte of injection time "
              "at 32 us per count, which made it a table of answers that meant "
              "something different on every engine. It is now true volumetric "
              "efficiency and the fuel comes from an air model - see "
              "docs/ARCHITECTURE.md. A calibration "
              "burned before V30 is NOT valid in this table. V98: ONE "
              "PERCENT PER COUNT, 0..255 % (Speeduino's VE byte) - the 0.5 % "
              "count capped VE at 127.5 %, below a boosted or tuned "
              "engine's. V98r2: U16, 0.1 % PER COUNT, 0..400.0 % "
              "(rusEFI veTable U16 0.1) - at the 1..5 % closed-throttle "
              "cells of an alpha-N table a 1 % step was 20..100 %. Part "
              "of the layout identity (generate_config.VE_UNIT)."),
    Meta("CAL_FUEL_RPM_AX", "fuelRpmAx", "Fuel map RPM axis", L, G.TABLES,
         units="rpm", lo=0, hi=20000, category="Fuel"),
    Meta("CAL_FUEL_LOAD_AX", "fuelLoadAx", "VE table load axis", L, G.TABLES,
         scale=0.1, digits=1, lo=0, hi=6500, category="Fuel",
         note="The fuel load: MAP kPa under speed density, throttle % under "
              "the two alpha-N strategies."),

    # ---- ignition table --------------------------------------------------
    Meta("CAL_IGN_MAP", "ignMap", "Ignition map", L, G.TABLES, units="deg",
         scale=0.5, translate=-20.0, digits=1, lo=0, hi=255, safety_critical=True,
         category="Ignition"),
    Meta("CAL_IGN_RPM_AX", "ignRpmAx", "Ignition RPM axis", L, G.TABLES,
         units="rpm", lo=0, hi=20000, category="Ignition"),
    Meta("CAL_IGN_LOAD_AX", "ignLoadAx", "Ignition load axis", L, G.TABLES,
         scale=0.1, digits=1, lo=0, hi=6500, category="Ignition",
         note="kPa or %, per the ignition table load setting."),

    # ---- mixture target --------------------------------------------------
    Meta("CAL_AFR_MAP", "afrMap", "Target lambda", L, G.TABLES,
         units="lambda", scale=1.0 / 147.0, digits=2, lo=59, hi=220,
         category="Lambda",
         note="V98: lambda x 147 - rusEFI lambdaTable's own scale, and the "
              "same bytes the AFR x 10 table held on gasoline, so no page "
              "changed. On its own rpm / load axes (lambdaRpmAx, "
              "lambdaLoadAx). Lambda no longer depends on the stoichiometric "
              "ratio; AFR = lambda x stoich is a display."),

    # ---- warm-up and cranking -------------------------------------------
    Meta("CAL_CLT_ENR_AX", "cltEnrAx", "Warm-up axis", L, G.TABLES, units="C",
         scale=0.1, translate=-1000.0, digits=1, lo=9500, hi=12000, category="Fuel"),
    Meta("CAL_CLT_ENR_VAL", "cltEnrVal", "Warm-up enrichment", L, G.TABLES,
         units="%", lo=0, hi=255, category="Fuel"),
    Meta("CAL_CRANK_PW_AX", "crankPwAx", "Cranking / priming coolant axis", L, G.TABLES,
         units="C", scale=0.1, translate=-1000.0, digits=1, lo=9500, hi=12000,
         category="Fuel"),
    Meta("CAL_CRANK_PW_VAL", "crankPwVal", "Cranking fuel", L, G.TABLES,
         units="mg", scale=0.1, digits=1, lo=0, hi=20000, category="Fuel",
         note="V98: FUEL MASS per cylinder per cycle while cranking (rusEFI "
              "crankingCycleBaseFuel), through the injector model like "
              "running fuel - not an injector-specific pulse width. A failed "
              "coolant sensor reads the 20 C point."),

    # ---- dwell and dead time vs battery ---------------------------------
    Meta("CAL_DWELL_BATT_AX", "dwellBattAx", "Dwell voltage axis", L, G.TABLES,
         units="V", scale=0.01, digits=2, lo=0, hi=2000, category="Ignition"),
    Meta("CAL_DWELL_BATT_VAL", "dwellBattVal", "Dwell vs voltage", L, G.TABLES,
         units="ms", scale=0.01, digits=2, lo=0, hi=1000, safety_critical=True,
         category="Ignition"),
    Meta("CAL_DEADTIME_VAL", "deadtimeVal", "Dead time vs voltage", L, G.TABLES,
         units="us", lo=0, hi=5000, category="Fuel",
         note="Shares CAL_DWELL_BATT_AX."),

    # ---- coolant sensor --------------------------------------------------
    Meta("CAL_CLT_SENS_AX", "cltSensAx", "Coolant sensor counts", L,
         G.SENSOR_ROUTING, lo=0, hi=1023, category="Sensors"),
    Meta("CAL_CLT_SENS_VAL", "cltSensVal", "Coolant sensor value", L,
         G.SENSOR_ROUTING, units="C", scale=0.1, translate=-1000.0, digits=1,
         # RAW 9500..12000 IS -50..+200 C THROUGH THE BIAS. The bound used to be
         # 65535, which is what a u16 holds and not what a thermistor reads -
         # 6453.5 C through the scale. A limit taken from the TYPE rather than
         # the QUANTITY makes the curve editor's axis useless and lets a typo
         # into a field.
         lo=9500, hi=12000, category="Sensors"),

    # ---- pressure and position sensors -----------------------------------
    Meta("CAL_MAP_SENS_OFF", "mapSensOff", "Pressure at zero counts", L,
         G.SENSOR_ROUTING, units="kPa", scale=0.1, digits=1, lo=0, hi=65535,
         category="Sensors"),
    Meta("CAL_MAP_SENS_GRD", "mapSensGrd", "Pressure gradient per 1000 counts", L,
         G.SENSOR_ROUTING, units="kPa", scale=0.1, digits=1, lo=0, hi=65535,
         category="Sensors"),
    Meta("CAL_TPS1_MIN", "tps1Min", "TPS1 closed counts", Z, G.DBW_SETUP,
         lo=0, hi=1023, safety_critical=True, category="DBW"),
    Meta("CAL_TPS1_MAX", "tps1Max", "TPS1 open counts", Z, G.DBW_SETUP,
         lo=0, hi=1023, safety_critical=True, category="DBW"),
    Meta("CAL_TPS2_MIN", "tps2Min", "TPS2 closed counts", Z, G.DBW_SETUP,
         lo=0, hi=1023, safety_critical=True, category="DBW"),
    Meta("CAL_TPS2_MAX", "tps2Max", "TPS2 open counts", Z, G.DBW_SETUP,
         lo=0, hi=1023, safety_critical=True, category="DBW"),
    Meta("CAL_PEDAL1_MIN", "pedal1Min", "Pedal 1 released counts", Z, G.DBW_SETUP,
         lo=0, hi=1023, safety_critical=True, category="DBW"),
    Meta("CAL_PEDAL1_MAX", "pedal1Max", "Pedal 1 floored counts", Z, G.DBW_SETUP,
         lo=0, hi=1023, safety_critical=True, category="DBW"),
    Meta("CAL_PEDAL2_MIN", "pedal2Min", "Pedal 2 released counts", Z, G.DBW_SETUP,
         lo=0, hi=1023, safety_critical=True, category="DBW"),
    Meta("CAL_PEDAL2_MAX", "pedal2Max", "Pedal 2 floored counts", Z, G.DBW_SETUP,
         lo=0, hi=1023, safety_critical=True, category="DBW"),

    # ---- strategy selectors already in the page --------------------------
    Meta("CAL_LOAD_SOURCE", "loadSource", "Load model", Z,
         G.ENGINE_SETUP, lo=0, hi=2, enum=ENUM_LOAD_SOURCE, category="Engine",
         note="Speed density: VE(rpm, MAP) x density(MAP, intake air) - needs "
              "a true manifold pressure sensor; on a sensor fault the MAP "
              "estimate table stands in. Alpha-N x inlet pressure: VE(rpm, "
              "throttle) x density(measured inlet pressure) - for a pressure "
              "sensor BEFORE the throttle (VAG 1.8T G31). Alpha-N: VE(rpm, "
              "throttle) at 101.3 kPa - no pressure sensor needed."),
    Meta("CAL_INJ_MODE", "injModeLegacy", "Injection mode, old field", Z,
         G.INJECTOR_ROUTING, lo=0, hi=1, safety_critical=True, category="Fuel",
         note="0 batch / 1 sequential. Superseded by injStrategy in the "
              "universal block, which can also say semi-sequential; the "
              "router keeps them consistent."),
    Meta("CAL_FUELPUMP_PRIME_MS", "fuelPumpPrimeMs", "Fuel pump prime", L,
         G.OUTPUT_ROUTING, units="ms", lo=0, hi=5000, category="I/O",
         note="Key-on prime, once per key cycle, in AUTO. This is the time "
              "the pump pin is DRIVEN: the timer starts when the output is "
              "first permitted (page armed, supervision link up). 0 = no "
              "prime. 5000 ms is FP_PRIME_MAX_MS in hcfuelpump.h - the "
              "firmware clamps to it as well, so this range and the "
              "firmware can never disagree in silence."),

    # ---- DBW -------------------------------------------------------------
    Meta("CAL_DBW_ENABLE", "dbwEnable", "Enable electronic throttle", Z,
         G.DBW_SETUP, lo=0, hi=1, safety_critical=True, category="DBW",
         note="RPM_ZERO and defaults to 0. The motor never moves until this is "
              "set deliberately."),
    Meta("CAL_IAT_CHANNEL", "iatChannel", "Intake air ADC channel", Z,
         G.SENSOR_ROUTING, lo=0, hi=255, category="Sensors",
         note="255 = no sensor; the fallback is used and the error bit is set."),
    # V83: DISPLAYED IN rusEFI's UNITS so a gain can be compared with the
    # reference's. hc_dbw.c: duty_x10 = err_x10 * KP / 1000 per step, the
    # integrator adds err_x10 * KI * 5 ms / 1e6 per 5 ms step (= KI/1000 per
    # second), and D = d(err_x10) * KD / 1000 per 5 ms step (= KD * 5e-6 s).
    # Until V83 all three showed raw/100, ten times rusEFI's P and I.
    Meta("CAL_DBW_KP", "dbwKp", "DBW Kp", L, G.DBW_SETUP, units="%/%",
         scale=0.001, digits=3, lo=0, hi=65535, category="DBW"),
    Meta("CAL_DBW_KI", "dbwKi", "DBW Ki", L, G.DBW_SETUP, units="%/%s",
         scale=0.001, digits=3, lo=0, hi=65535, category="DBW"),
    Meta("CAL_DBW_DEV_X10", "dbwDevX10", "DBW allowed deviation", L, G.DBW_SETUP,
         units="%", scale=0.1, digits=1, lo=0, hi=1000, safety_critical=True,
         category="DBW"),
    Meta("CAL_DBW_DEV_MS", "dbwDevMs", "DBW deviation time", L, G.DBW_SETUP,
         units="ms", lo=0, hi=5000, safety_critical=True, category="DBW"),
    Meta("CAL_DBW_LIMP_X10", "dbwLimpX10", "Throttle spring (limp) opening", L,
         G.DBW_SETUP, units="%", scale=0.1, digits=1, lo=0, hi=1000,
         safety_critical=True, category="DBW",
         note="V98: where the return spring holds the plate with the motor "
              "off. With DBW on and BOTH throttle tracks failed, alpha-N "
              "fuels at this opening (the ETB is shut down then) - a limp "
              "home instead of no air."),
    Meta("CAL_DBW_SF_MODE", "dbwSfMode", "H-bridge fault polarity", L, G.DBW_SETUP,
         lo=0, hi=2, safety_critical=True, enum=ENUM_DBW_SF, category="DBW"),
    Meta("CAL_DBW_KD", "dbwKd", "DBW Kd", L, G.DBW_SETUP, units="%s/%",
         scale=0.000005, digits=4, lo=0, hi=65535, category="DBW"),
    Meta("CAL_DBW_MIN_X10", "dbwMinX10", "DBW minimum command", L, G.DBW_SETUP,
         units="%", scale=0.1, digits=1, lo=0, hi=1000, safety_critical=True,
         category="DBW"),
    Meta("CAL_DBW_MAX_X10", "dbwMaxX10", "DBW maximum command", L, G.DBW_SETUP,
         units="%", scale=0.1, digits=1, lo=0, hi=1000, safety_critical=True,
         category="DBW"),
    Meta("CAL_DBW_REVLIM_RPM", "dbwRevlimRpm", "ETB rev limit start", L, G.DBW_SETUP,
         units="rpm", lo=0, hi=20000, category="DBW",
         note="rusEFI etbRevLimitStart: above it the throttle target tapers "
              "to closed across the range. 0 = off."),
    Meta("CAL_DBW_REVLIM_RANGE", "dbwRevlimRange", "ETB rev limit range", L,
         G.DBW_SETUP, units="rpm", lo=0, hi=20000, category="DBW"),
    Meta("CAL_DBW_BIAS_AX", "dbwBiasAx", "DBW bias curve position", L, G.DBW_SETUP,
         units="%", scale=0.1, digits=1, lo=0, hi=1000, category="DBW"),
    # V83: THE FIRMWARE ADDS (stored - 1000) TO A DUTY IN 0.1 % UNITS
    # (hc_dbw.c DBW_BIAS_ZERO), so a stored 1190 is +19.0 %. At scale 1.0 the
    # tuner saw "190 %" and every value they typed was ten times too big.
    Meta("CAL_DBW_BIAS_VAL", "dbwBiasVal", "DBW bias curve duty", L, G.DBW_SETUP,
         units="%", scale=0.1, digits=1, translate=-100.0, lo=0, hi=2000,
         category="DBW",
         note="Signed duty stored with a +1000 bias so the curve can push the "
              "plate shut below the limp-home detent."),
    Meta("CAL_DBW_AUTOCAL_MS", "dbwAutocalMs", "Autocal dwell at each stop", L,
         G.DBW_SETUP, units="ms", lo=0, hi=65535, category="DBW"),
    Meta("CAL_DBW_AUTOCAL_DUTY", "dbwAutocalDuty", "Autocal duty", L, G.DBW_SETUP,
         units="%", scale=0.1, digits=1, lo=0, hi=1000, category="DBW"),
    Meta("CAL_DBW_TUNE_AMP", "dbwTuneAmp", "Autotune relay amplitude", L,
         G.DBW_SETUP, units="%", scale=0.1, digits=1, lo=0, hi=1000, category="DBW"),
    Meta("CAL_PEDAL_MAP", "pedalMap", "Pedal demand map", L, G.TABLES, units="%",
         scale=0.5, digits=1, lo=0, hi=255, category="DBW"),
    Meta("CAL_PEDAL_RPM_AX", "pedalRpmAx", "Pedal map RPM axis", L, G.TABLES,
         units="rpm", lo=0, hi=20000, category="DBW"),
    Meta("CAL_PEDAL_AX", "pedalAx", "Pedal map pedal axis", L, G.TABLES, units="%",
         scale=0.1, digits=1, lo=0, hi=1000, category="DBW"),

    # ---- temperature and ambient ----------------------------------------
    Meta("CAL_IAT_DEFAULT", "iatDefault", "Intake air fallback", L,
         G.SENSOR_ROUTING, units="C", scale=0.1, translate=-1000.0, digits=1,
         lo=9600, hi=11500, category="Sensors"),
    Meta("CAL_IAT_SENS_AX", "iatSensAx", "Intake air sensor counts", L,
         G.SENSOR_ROUTING, lo=0, hi=1023, category="Sensors"),
    Meta("CAL_IAT_SENS_VAL", "iatSensVal", "Intake air sensor value", L,
         G.SENSOR_ROUTING, units="C", scale=0.1, translate=-1000.0, digits=1,
         # RAW 9500..12000 IS -50..+200 C THROUGH THE BIAS. The bound used to be
         # 65535, which is what a u16 holds and not what a thermistor reads -
         # 6453.5 C through the scale. A limit taken from the TYPE rather than
         # the QUANTITY makes the curve editor's axis useless and lets a typo
         # into a field.
         lo=9500, hi=12000, category="Sensors"),
    Meta("CAL_BARO_DEFAULT", "baroDefault", "Barometric fallback", L,
         G.SENSOR_ROUTING, units="kPa", scale=0.1, digits=1, lo=0, hi=65535,
         category="Sensors"),

    # ---- boost -----------------------------------------------------------
    Meta("CAL_BOOST_ENABLE", "boostEnable", "Enable boost control", Z,
         G.OUTPUT_ROUTING, lo=0, hi=1, safety_critical=True, category="Boost"),
    Meta("CAL_BOOST_MODE", "boostMode", "Boost mode", L, G.OUTPUT_ROUTING,
         lo=0, hi=1, enum=ENUM_BOOST_MODE, category="Boost"),
    Meta("CAL_BOOST_DUTY_MAP", "boostDutyMap", "Boost open-loop duty", L, G.TABLES,
         units="%", scale=0.5, digits=1, lo=0, hi=255, category="Boost"),
    Meta("CAL_BOOST_RPM_AX", "boostRpmAx", "Boost duty RPM axis", L, G.TABLES,
         units="rpm", lo=0, hi=20000, category="Boost"),
    Meta("CAL_BOOST_TPS_AX", "boostTpsAx", "Boost duty throttle axis", L, G.TABLES,
         units="%", scale=0.1, digits=1, lo=0, hi=1000, category="Boost"),
    Meta("CAL_BOOST_TGT_MAP", "boostTgtMap", "Boost target", L, G.TABLES,
         units="kPa", lo=0, hi=255, safety_critical=True, category="Boost"),
    Meta("CAL_BOOST_TGT_RPM_AX", "boostTgtRpmAx", "Boost target RPM axis", L,
         G.TABLES, units="rpm", lo=0, hi=20000, category="Boost"),
    Meta("CAL_BOOST_TGT_TPS_AX", "boostTgtTpsAx", "Boost target throttle axis", L,
         G.TABLES, units="%", scale=0.1, digits=1, lo=0, hi=1000, category="Boost"),
    Meta("CAL_BOOST_KP", "boostKp", "Boost Kp", L, G.OUTPUT_ROUTING, scale=0.01,
         digits=2, lo=0, hi=65535, category="Boost"),
    Meta("CAL_BOOST_KI", "boostKi", "Boost Ki", L, G.OUTPUT_ROUTING, scale=0.01,
         digits=2, lo=0, hi=65535, category="Boost"),
    Meta("CAL_BOOST_KD", "boostKd", "Boost Kd", L, G.OUTPUT_ROUTING, scale=0.01,
         digits=2, lo=0, hi=65535, category="Boost"),
    Meta("CAL_BOOST_MIN_RPM", "boostMinRpm", "Boost idle below", L,
         G.OUTPUT_ROUTING, units="rpm", lo=0, hi=20000, category="Boost"),
    Meta("CAL_BOOST_MIN_TPS_X10", "boostMinTpsX10", "Boost idle below throttle", L,
         G.OUTPUT_ROUTING, units="%", scale=0.1, digits=1, lo=0, hi=1000,
         category="Boost"),
    Meta("CAL_BOOST_FREQ_HZ", "boostFreqHz", "Boost valve frequency", Z,
         G.OUTPUT_ROUTING, units="Hz", lo=0, hi=1000, category="Boost"),
    Meta("CAL_BOOST_CUT_KPA", "boostCutKpa", "Overboost cut", L, G.OUTPUT_ROUTING,
         units="kPa", scale=0.1, digits=1, lo=0, hi=65535, safety_critical=True,
         category="Safety"),
    Meta("CAL_BOOST_CUT_HYST", "boostCutHyst", "Overboost resume hysteresis", L,
         G.OUTPUT_ROUTING, units="kPa", scale=0.1, digits=1, lo=0, hi=65535,
         safety_critical=True, category="Safety"),
    Meta("CAL_BOOST_CLT_AX", "boostCltAx", "Boost coolant axis", L, G.TABLES,
         units="C", scale=0.1, translate=-1000.0, digits=1, lo=9500, hi=12000,
         category="Boost"),
    Meta("CAL_BOOST_CLT_MUL", "boostCltMul", "Boost coolant multiplier", L,
         G.TABLES, scale=0.01, digits=2, lo=0, hi=200, category="Boost"),
    Meta("CAL_BOOST_IAT_AX", "boostIatAx", "Boost intake air axis", L, G.TABLES,
         units="C", scale=0.1, translate=-1000.0, digits=1, lo=9500, hi=12000,
         category="Boost"),
    Meta("CAL_BOOST_IAT_MUL", "boostIatMul", "Boost intake air multiplier", L,
         G.TABLES, scale=0.01, digits=2, lo=0, hi=200, category="Boost"),

    # ---- transient fuelling ---------------------------------------------
    Meta("CAL_ACCEL_THRESH_X10", "accelThreshX10", "Accel enrichment threshold", L,
         G.TABLES, units="%/s", scale=0.1, digits=1, lo=0, hi=65535, category="Fuel"),
    Meta("CAL_ACCEL_GAIN", "accelGain", "Accel enrichment gain", L, G.TABLES,
         units="us", lo=0, hi=65535, category="Fuel"),
    Meta("CAL_ACCEL_DECAY_MS", "accelDecayMs", "Accel shot decay", L, G.TABLES,
         units="ms", lo=0, hi=65535, category="Fuel"),
    Meta("CAL_OVERRUN_RPM", "overrunRpm", "Fuel cut above rpm", L, G.TABLES,
         units="rpm", lo=0, hi=20000, category="Fuel"),
    Meta("CAL_OVERRUN_TPS_X10", "overrunTpsX10", "Fuel cut: pedal below", L,
         G.TABLES, units="%", scale=0.1, digits=1, lo=0, hi=1000, category="Fuel"),
    Meta("CAL_OVERRUN_RESUME", "overrunResume", "Fuel back below rpm", L, G.TABLES,
         units="rpm", lo=0, hi=20000, category="Fuel"),

    # ---- rev limiter -----------------------------------------------------
    Meta("CAL_REVLIM_MODE", "revlimMode", "Rev limit cuts", L, G.ENGINE_SETUP,
         lo=0, hi=2, safety_critical=True, enum=ENUM_REVLIM, category="Safety"),
    Meta("CAL_REVLIM_PATTERN", "revlimPattern", "Spark cut: sparks of every 8", L,
         G.ENGINE_SETUP, lo=1, hi=8, safety_critical=True, category="Safety"),

    # ---- idle ------------------------------------------------------------
    Meta("CAL_IDLE_ENABLE", "idleEnable", "Enable idle control", Z,
         G.OUTPUT_ROUTING, lo=0, hi=1, category="Idle"),
    Meta("CAL_IDLE_PAD", "idlePad", "Alignment pad", L, G.GENERAL, lo=0, hi=255,
         category="Controller"),
    Meta("CAL_IDLE_TARGET_AX", "idleTargetAx", "Idle target axis", L, G.TABLES,
         units="C", scale=0.1, translate=-1000.0, digits=1, lo=9500, hi=12000,
         category="Idle"),
    Meta("CAL_IDLE_TARGET_VAL", "idleTargetVal", "Idle target", L, G.TABLES,
         units="rpm", lo=0, hi=5000, category="Idle"),
    Meta("CAL_IDLE_BASE_AX", "idleBaseAx", "Idle base axis", L, G.TABLES,
         units="C", scale=0.1, translate=-1000.0, digits=1, lo=9500, hi=12000,
         category="Idle"),
    Meta("CAL_IDLE_BASE_VAL", "idleBaseVal", "Idle base position", L, G.TABLES,
         units="%", scale=0.1, digits=1, lo=0, hi=1000, category="Idle"),
    Meta("CAL_IDLE_KP", "idleKp", "Idle Kp", L, G.OUTPUT_ROUTING, scale=0.01,
         digits=2, lo=0, hi=65535, category="Idle"),
    Meta("CAL_IDLE_KI", "idleKi", "Idle Ki", L, G.OUTPUT_ROUTING, scale=0.01,
         digits=2, lo=0, hi=65535, category="Idle"),
    Meta("CAL_IDLE_RANGE_X10", "idleRangeX10", "Idle trim authority", L,
         G.OUTPUT_ROUTING, units="%", scale=0.1, digits=1, lo=0, hi=1000,
         category="Idle"),
    Meta("CAL_IDLE_RPM_BAND", "idleRpmBand", "Idle engagement band", L,
         G.OUTPUT_ROUTING, units="rpm", lo=0, hi=5000, category="Idle"),

    # ---- PWM polarity ----------------------------------------------------
    Meta("CAL_PWM_INVERT", "pwmInvert", "PWM unit drives inverted", Z,
         G.OUTPUT_ROUTING, lo=0, hi=1, safety_critical=True, category="I/O",
         note="A wrong value on the BOOST valve means 0 %% commanded is 100 %% "
              "delivered. Scope it; do not guess."),
    Meta("CAL_PWM_PAD", "pwmPad", "Alignment pad", L, G.GENERAL, lo=0, hi=255,
         category="Controller"),
]


# --------------------------------------------------------------------------
# 2b. The universal extension block.
#
# These go INSIDE hcconfig.h's CFG_UNIVERSAL_BASE region and nowhere else, so
# not one existing byte moves and every image already flashed keeps its page.
# generate_config.py emits the hcconfig.h block for them and refuses if the
# block does not fit or does not match what hcconfig.h currently says.
# --------------------------------------------------------------------------
MAX_CYL_UNIVERSAL = 12          # the universal model's ceiling
N_GENERIC = 8                   # generic analog / PWM / on-off channels

_PIN = dict(lo=0, hi=255)


def _pin_meta(slot, ts, label, group, needs, cat, note="", crit=True):
    return Meta(slot, ts, label, Z, group, safety_critical=crit,
                category=cat, note=note, is_pin=True, pin_needs=needs, **_PIN)


# Imported lazily to keep this module importable without the descriptor tools.
from hanicore_config_schema import PinCap  # noqa: E402

UNIVERSAL: list[NewField] = [
    # ---- header ----------------------------------------------------------
    NewField("CFG_U_MAGIC", "u16", 1,
             Meta("CFG_U_MAGIC", "uMagic", "Universal block magic", R, G.GENERAL,
                  lo=0, hi=65535, category="Controller",
                  note="0x4855 'HU'. A page without it has no universal block "
                       "and must be defaulted, not interpreted."),
             "u16 0x4855 'HU' - the universal block marker"),
    NewField("CFG_U_SCHEMA", "u16", 1,
             Meta("CFG_U_SCHEMA", "uSchema", "Universal schema version", R,
                  G.GENERAL, lo=0, hi=65535, safety_critical=True,
                  category="Controller",
                  note="Bumped when this block's layout changes. Migration is "
                       "keyed on it."),
             "u16 universal block schema version"),
    NewField("CFG_U_GENERATION", "u16", 1,
             Meta("CFG_U_GENERATION", "uGeneration", "Desired config revision", L,
                  G.GENERAL, lo=0, hi=65535, category="Controller",
                  note="Incremented by the config manager on every accepted "
                       "write. Lets a host see that its edit landed."),
             "u16 desired-configuration revision counter"),
    NewField("CFG_U_CRC", "u16", 1,
             Meta("CFG_U_CRC", "uCrc", "Universal block CRC", L, G.GENERAL,
                  lo=0, hi=65535, category="Controller"),
             "u16 CRC over the universal block, recomputed on commit"),

    # ---- engine description ---------------------------------------------
    NewField("CFG_U_DISPLACEMENT_CC", "u16", 1,
             Meta("CFG_U_DISPLACEMENT_CC", "displacementCc", "Displacement", R,
                  G.ENGINE_SETUP, units="cc", lo=0, hi=20000, category="Engine"),
             "u16 total displacement, cc"),
    NewField("CFG_U_ENGINE_PRESET", "u8", 1,
             Meta("CFG_U_ENGINE_PRESET", "enginePreset", "Engine preset", Z,
                  G.ENGINE_SETUP, lo=0, hi=255, category="Engine",
                  note="A preset only POPULATES ordinary fields. No runtime "
                       "code may branch on it."),
             "u8 engine preset id, 0 = custom"),
    NewField("CFG_U_INJECTOR_PRESET", "u8", 1,
             Meta("CFG_U_INJECTOR_PRESET", "injectorPreset", "Injector preset", Z,
                  G.INJECTOR_ROUTING, lo=0, hi=255, category="Fuel"),
             "u8 injector component preset id, 0 = custom"),
    NewField("CFG_U_COIL_PRESET", "u8", 1,
             Meta("CFG_U_COIL_PRESET", "coilPreset", "Coil preset", Z,
                  G.IGNITION_ROUTING, lo=0, hi=255, category="Ignition"),
             "u8 coil component preset id, 0 = custom"),
    NewField("CFG_U_MAP_PRESET", "u8", 1,
             Meta("CFG_U_MAP_PRESET", "mapSensorPreset", "Pressure sensor preset", Z,
                  G.SENSOR_ROUTING, lo=0, hi=255, category="Sensors"),
             "u8 pressure sensor preset id, 0 = custom"),
    NewField("CFG_U_CYL_BANK", "u8", MAX_CYL_UNIVERSAL,
             Meta("CFG_U_CYL_BANK", "cylBank", "Cylinder bank", Z, G.ENGINE_SETUP,
                  lo=0, hi=3, enum=ENUM_BANK, category="Engine",
                  note="ONE bank map, shared by lambda, knock, EGT, fuel trim "
                       "and diagnostics."),
             "u8[12] cylinder -> bank, shared by every per-bank subsystem"),
    NewField("CFG_U_TDC_CYL_EXT", "u16", MAX_CYL_UNIVERSAL - 8,
             Meta("CFG_U_TDC_CYL_EXT", "tdcCylExtDegX10", "Cylinder 9..12 TDC", Z,
                  G.ENGINE_SETUP, units="deg", scale=0.1, digits=1, lo=0, hi=7200,
                  safety_critical=True, category="Engine",
                  note="Extends CFG_TDC_CYL, which is 8 wide, to 12 cylinders "
                       "without moving one existing byte."),
             "u16[4] TDC angle for cylinders 9..12, extends CFG_TDC_CYL"),

    # ---- execution strategy ---------------------------------------------
    NewField("CFG_U_INJ_STRATEGY", "u8", 1,
             Meta("CFG_U_INJ_STRATEGY", "injStrategy", "Injection strategy", Z,
                  G.INJECTOR_ROUTING, lo=0, hi=2, safety_critical=True,
                  enum=ENUM_INJ_STRATEGY, category="Fuel"),
             "u8 batch / semi-sequential / sequential"),
    NewField("CFG_U_IGN_STRATEGY", "u8", 1,
             Meta("CFG_U_IGN_STRATEGY", "ignStrategy", "Ignition strategy", Z,
                  G.IGNITION_ROUTING, lo=0, hi=3, safety_critical=True,
                  enum=ENUM_IGN_STRATEGY, category="Ignition",
                  note="Wasted COP uses individual coils and needs NO cycle "
                       "position. Coil topology does not decide this."),
             "u8 wasted paired / wasted COP / sequential COP / distributor"),
    NewField("CFG_U_SYNC_MODE", "u8", 1,
             Meta("CFG_U_SYNC_MODE", "syncMode", "Synchronisation mode", Z,
                  G.TRIGGER_SETUP, lo=0, hi=4, safety_critical=True,
                  enum=ENUM_SYNC_MODE, category="Trigger"),
             "u8 none / crank only / cam1 cycle / cam2 cycle / dual cam"),
    NewField("CFG_U_TRIG_DECODER", "u8", 1,
             Meta("CFG_U_TRIG_DECODER", "trigDecoder", "Crank decoder", Z,
                  G.TRIGGER_SETUP, lo=0, hi=3, safety_critical=True,
                  enum=ENUM_TRIG_DECODER, category="Trigger",
                  note="Selects WHICH validation rules apply. A gap-ratio rule "
                       "is meaningless for a decoder with no gap."),
             "u8 crank decoder selector - validation is per decoder"),

    # ---- WHAT THE DECODER ACTUALLY READS, 2026-09-15, V55 -----------------
    #
    # Until V55 hctrig_me711.c held ME711_TEETH 60, ME711_REAL_TEETH 58, a
    # fixed 2.0 gap ratio, a falling-edge-only capture setup and a cam window
    # table of four references at 122/302/482/662 degrees compiled in - the
    # Porsche V8's geometry, in the runtime, where the project rules say no
    # engine's geometry may live. syTeeth and syGap were already in the page,
    # already in the .ini and already validated per decoder; NOTHING READ THEM.
    # me711_trigger_test even wrote them, which is how a suite can be green
    # about a property it never exercises.
    #
    # These four fields are the rest of what a decoder needs to be generic.
    # The wheel itself (teeth, missing teeth, edge, ratio, minimum teeth)
    # stays where it already is, in hcconfig.h's core block.
    # V97: THE ONE PHYSICAL CRANK REFERENCE (docs/ARCHITECTURE.md).
    # Until V97 this slot was trigOffsetX10, an internal rotation (0..719.9)
    # nobody could read physically - the AWT's "358.0" is tooth #1 at 2.0
    # deg BTDC. The slot, its size and every stored value's MEANING mod 360
    # are unchanged (358.0 ATDC == -2.0 ATDC); the decoder normalises with
    # hc_trig_rotation_x10() and nothing else sees an internal value.
    NewField("CFG_U_TRIG_ANGLE_X10", "s16", 1,
             Meta("CFG_U_TRIG_ANGLE_X10", "trigAngleX10",
                  "Trigger angle (tooth #1, deg ATDC)", Z, G.TRIGGER_SETUP,
                  units="deg", scale=0.1, digits=1, lo=-3599, hi=3599,
                  category="Trigger", safety_critical=True,
                  note="Where tooth #1 is, in crank degrees AFTER cylinder-1 "
                       "TDC; negative = before TDC (the usual case). Tooth "
                       "#1 is the selected edge that ENDS the missing-tooth "
                       "gap - the first tooth after the gap. Speeduino's "
                       "'trigger angle'; rusEFI globalTriggerAngleOffset is "
                       "minus this. Only the value modulo 360 matters. Prove "
                       "it with a timing light at fixed timing, or the "
                       "compression-TDC tooth profile."),
             "s16 crank angle of tooth #1 after cylinder-1 TDC, 0.1 deg"),
    NewField("CFG_U_CAM_REFS", "u8", 1,
             Meta("CFG_U_CAM_REFS", "camRefs",
                  "Cam references per cycle", Z, G.TRIGGER_SETUP,
                  lo=0, hi=8, category="Trigger", safety_critical=True,
                  note="How many edges of the configured polarity the cam "
                       "sensor produces in one 720 degree cycle, equally "
                       "spaced. ONE is the ordinary single-window Hall cam "
                       "and it resolves the cycle. An EVEN count cannot: the "
                       "pattern repeats every 360 degrees, so it proves the "
                       "cam is alive and nothing about which revolution this "
                       "is. The Porsche V8 donor has four."),
             "u8 equally spaced cam reference edges per 720 degrees"),
    NewField("CFG_U_CAM_PAD", "u8", 1,
             Meta("CFG_U_CAM_PAD", "camPad", "Alignment pad", L,
                  G.TRIGGER_SETUP, lo=0, hi=255, category="Trigger"),
             "u8 alignment pad"),
    NewField("CFG_U_CAM_REF_X10", "u16", 1,
             Meta("CFG_U_CAM_REF_X10", "camRefX10",
                  "First cam reference angle", Z, G.TRIGGER_SETUP,
                  units="deg", scale=0.1, digits=1, lo=0, hi=7199,
                  category="Trigger", safety_critical=True,
                  note="Engine angle at which the FIRST cam reference edge "
                       "is expected, in the same 0..720 coordinate the TDC "
                       "table uses. Any further references follow at "
                       "720/count."),
             "u16 engine angle of the first cam reference edge, 0.1 deg"),
    NewField("CFG_U_CAM_WINDOW_X10", "u16", 1,
             Meta("CFG_U_CAM_WINDOW_X10", "camWindowX10",
                  "Cam acceptance window", Z, G.TRIGGER_SETUP,
                  units="deg", scale=0.1, digits=1, lo=10, hi=1800,
                  category="Trigger", safety_critical=True,
                  note="Half-width. An edge further than this from every "
                       "configured reference is not a reference: it raises "
                       "camError and, once the cycle was synchronised, drops "
                       "sync with CAM_WINDOW. It must be wider than the "
                       "tooth the angle is quantised to and narrower than "
                       "half the spacing between references."),
             "u16 cam reference acceptance half-window, 0.1 deg"),

    # ---- physical pin routing -------------------------------------------
    NewField("CFG_U_PIN_CRANK", "u8", 1,
             _pin_meta("CFG_U_PIN_CRANK", "pinCrank", "Crank sensor pin",
                       G.TRIGGER_SETUP, PinCap.VR_IN | PinCap.HALL_IN, "Trigger"),
             "u8 physical connector pin for the crank sensor, 255 = unassigned"),
    NewField("CFG_U_PIN_CAM1", "u8", 1,
             _pin_meta("CFG_U_PIN_CAM1", "pinCam1", "Camshaft 1 pin",
                       G.TRIGGER_SETUP, PinCap.HALL_IN, "Trigger"),
             "u8 physical connector pin for camshaft 1"),
    NewField("CFG_U_PIN_CAM2", "u8", 1,
             _pin_meta("CFG_U_PIN_CAM2", "pinCam2", "Camshaft 2 pin",
                       G.TRIGGER_SETUP, PinCap.HALL_IN, "Trigger"),
             "u8 physical connector pin for camshaft 2"),
    NewField("CFG_U_PIN_INJ", "u8", MAX_CYL_UNIVERSAL,
             _pin_meta("CFG_U_PIN_INJ", "injPin", "Injector pin per cylinder",
                       G.INJECTOR_ROUTING, PinCap.INJ_OUT, "Fuel"),
             "u8[12] physical connector pin driving each cylinder's injector"),
    NewField("CFG_U_PIN_IGN", "u8", MAX_CYL_UNIVERSAL,
             _pin_meta("CFG_U_PIN_IGN", "ignPin", "Ignition pin per cylinder",
                       G.IGNITION_ROUTING, PinCap.IGN_OUT, "Ignition"),
             "u8[12] physical connector pin driving each cylinder's coil"),
    NewField("CFG_U_PIN_MAP", "u8", 1,
             _pin_meta("CFG_U_PIN_MAP", "pinMap", "Pressure sensor pin",
                       G.SENSOR_ROUTING, PinCap.AIN, "Sensors", crit=False),
             "u8 physical connector pin for the manifold pressure sensor"),
    NewField("CFG_U_PIN_BARO", "u8", 1,
             _pin_meta("CFG_U_PIN_BARO", "pinBaro", "Barometric sensor pin",
                       G.SENSOR_ROUTING, PinCap.AIN, "Sensors", crit=False,
                       note="255 = capture barometric pressure from the MAP "
                            "sensor at key-on, which is ordinary practice and "
                            "needs no hardware this board may not have."),
             "u8 physical connector pin for a barometric sensor"),
    NewField("CFG_U_PIN_CLT", "u8", 1,
             _pin_meta("CFG_U_PIN_CLT", "pinClt", "Coolant sensor pin",
                       G.SENSOR_ROUTING, PinCap.AIN, "Sensors", crit=False),
             "u8 physical connector pin for the coolant sensor"),
    NewField("CFG_U_PIN_IAT", "u8", 1,
             _pin_meta("CFG_U_PIN_IAT", "pinIat", "Intake air sensor pin",
                       G.SENSOR_ROUTING, PinCap.AIN, "Sensors", crit=False),
             "u8 physical connector pin for the intake air sensor"),
    NewField("CFG_U_PIN_TPS1", "u8", 1,
             _pin_meta("CFG_U_PIN_TPS1", "pinTps1", "Throttle track 1 pin",
                       G.DBW_SETUP, PinCap.AIN, "DBW"),
             "u8 physical connector pin for throttle position track 1"),
    NewField("CFG_U_PIN_TPS2", "u8", 1,
             _pin_meta("CFG_U_PIN_TPS2", "pinTps2", "Throttle track 2 pin",
                       G.DBW_SETUP, PinCap.AIN, "DBW"),
             "u8 physical connector pin for throttle position track 2"),
    NewField("CFG_U_PIN_APP1", "u8", 1,
             _pin_meta("CFG_U_PIN_APP1", "pinApp1", "Pedal track 1 pin",
                       G.DBW_SETUP, PinCap.AIN, "DBW"),
             "u8 physical connector pin for pedal track 1"),
    NewField("CFG_U_PIN_APP2", "u8", 1,
             _pin_meta("CFG_U_PIN_APP2", "pinApp2", "Pedal track 2 pin",
                       G.DBW_SETUP, PinCap.AIN, "DBW"),
             "u8 physical connector pin for pedal track 2"),
    NewField("CFG_U_PIN_VBAT", "u8", 1,
             _pin_meta("CFG_U_PIN_VBAT", "pinVbat", "Battery sense pin",
                       G.SENSOR_ROUTING, PinCap.AIN, "Sensors", crit=False),
             "u8 physical connector pin for battery voltage sense"),
    NewField("CFG_U_PIN_OIL_PRESS", "u8", 1,
             _pin_meta("CFG_U_PIN_OIL_PRESS", "pinOilPress", "Oil pressure pin",
                       G.SENSOR_ROUTING, PinCap.AIN, "Sensors"),
             "u8 physical connector pin for the oil pressure sensor"),
    NewField("CFG_U_PIN_FUEL_PRESS", "u8", 1,
             _pin_meta("CFG_U_PIN_FUEL_PRESS", "pinFuelPress", "Fuel pressure pin",
                       G.SENSOR_ROUTING, PinCap.AIN, "Sensors", crit=False),
             "u8 physical connector pin for the fuel pressure sensor"),
    NewField("CFG_U_PIN_FLEX", "u8", 1,
             _pin_meta("CFG_U_PIN_FLEX", "pinFlex", "Flex fuel sensor pin",
                       G.SENSOR_ROUTING, PinCap.FREQ_IN, "Sensors", crit=False),
             "u8 physical connector pin for a flex-fuel (frequency) sensor"),
    NewField("CFG_U_PIN_MAF", "u8", 1,
             _pin_meta("CFG_U_PIN_MAF", "pinMaf", "Air mass sensor pin",
                       G.SENSOR_ROUTING, PinCap.AIN | PinCap.FREQ_IN, "Sensors",
                       crit=False),
             "u8 physical connector pin for the air mass meter"),
    NewField("CFG_U_PIN_LAMBDA1", "u8", 1,
             _pin_meta("CFG_U_PIN_LAMBDA1", "pinLambda1", "Lambda 1 input pin",
                       G.SENSOR_ROUTING, PinCap.AIN, "Lambda", crit=False),
             "u8 physical connector pin for lambda 1 when it is external analog"),
    NewField("CFG_U_PIN_LAMBDA2", "u8", 1,
             _pin_meta("CFG_U_PIN_LAMBDA2", "pinLambda2", "Lambda 2 input pin",
                       G.SENSOR_ROUTING, PinCap.AIN, "Lambda", crit=False),
             "u8 physical connector pin for lambda 2 when it is external analog"),
    NewField("CFG_U_PIN_MAIN_RELAY", "u8", 1,
             _pin_meta("CFG_U_PIN_MAIN_RELAY", "pinMainRelay", "Main relay pin",
                       G.RELAY_SETUP, PinCap.RELAY_OUT, "I/O",
                       note="The OEM main relay (ME7.1.1 cavity 23) is driven "
                            "by the supply ASIC and is NOT reachable here. An "
                            "EXTERNAL main relay can be routed to any cavity "
                            "this build can drive; on ME7.1.1 that is only "
                            "cavity 65 today, which is also the fuel pump "
                            "default - two functions cannot share it "
                            "(PIN_CONFLICT). mainRelayBound says whether the "
                            "chosen cavity is drivable."),
             "u8 physical connector pin for the ECU main relay"),
    NewField("CFG_U_PIN_FUEL_PUMP", "u8", 1,
             _pin_meta("CFG_U_PIN_FUEL_PUMP", "pinFuelPump", "Fuel pump relay pin",
                       G.OUTPUT_ROUTING, PinCap.RELAY_OUT, "I/O"),
             "u8 physical connector pin for the fuel pump relay"),
    NewField("CFG_U_PIN_TACHO", "u8", 1,
             _pin_meta("CFG_U_PIN_TACHO", "pinTacho", "Tachometer output pin",
                       G.OUTPUT_ROUTING, PinCap.LOW_SIDE, "I/O", crit=False),
             "u8 physical connector pin for the tachometer output"),
    NewField("CFG_U_PIN_BOOST", "u8", 1,
             _pin_meta("CFG_U_PIN_BOOST", "pinBoost", "Boost solenoid pin",
                       G.OUTPUT_ROUTING, PinCap.PWM_OUT, "Boost"),
             "u8 physical connector pin for the boost control valve"),
    NewField("CFG_U_PIN_CAM1_SOL", "u8", 1,
             _pin_meta("CFG_U_PIN_CAM1_SOL", "pinCam1Sol", "Cam 1 solenoid pin",
                       G.OUTPUT_ROUTING, PinCap.PWM_OUT, "I/O", crit=False),
             "u8 physical connector pin for cam timing solenoid 1"),
    NewField("CFG_U_PIN_CAM2_SOL", "u8", 1,
             _pin_meta("CFG_U_PIN_CAM2_SOL", "pinCam2Sol", "Cam 2 solenoid pin",
                       G.OUTPUT_ROUTING, PinCap.PWM_OUT, "I/O", crit=False),
             "u8 physical connector pin for cam timing solenoid 2"),
    NewField("CFG_U_PIN_GEN_AIN", "u8", N_GENERIC,
             _pin_meta("CFG_U_PIN_GEN_AIN", "pinGenericAin", "Generic analog pin",
                       G.SENSOR_ROUTING, PinCap.AIN, "I/O", crit=False),
             "u8[8] physical connector pins for generic analog inputs"),
    NewField("CFG_U_PIN_GEN_PWM", "u8", N_GENERIC,
             _pin_meta("CFG_U_PIN_GEN_PWM", "pinGenericPwm", "Generic PWM pin",
                       G.OUTPUT_ROUTING, PinCap.PWM_OUT, "I/O"),
             "u8[8] physical connector pins for generic PWM outputs"),
    NewField("CFG_U_PIN_GEN_OUT", "u8", N_GENERIC,
             _pin_meta("CFG_U_PIN_GEN_OUT", "pinGenericOut", "Generic output pin",
                       G.OUTPUT_ROUTING, PinCap.LOW_SIDE, "I/O"),
             "u8[8] physical connector pins for generic on/off outputs"),

    # ---- dual-track correlation -----------------------------------------
    NewField("CFG_U_TPS_CORR", "u8", 1,
             Meta("CFG_U_TPS_CORR", "tpsCorrelation", "TPS track correlation", Z,
                  G.DBW_SETUP, lo=0, hi=2, safety_critical=True,
                  enum=ENUM_TRACK_CORR, category="DBW"),
             "u8 how TPS track 2 relates to track 1"),
    NewField("CFG_U_APP_CORR", "u8", 1,
             Meta("CFG_U_APP_CORR", "appCorrelation", "Pedal track correlation", Z,
                  G.DBW_SETUP, lo=0, hi=2, safety_critical=True,
                  enum=ENUM_TRACK_CORR, category="DBW"),
             "u8 how pedal track 2 relates to track 1"),
    NewField("CFG_U_TPS_TOL_X10", "u16", 1,
             Meta("CFG_U_TPS_TOL_X10", "tpsTolX10", "TPS track tolerance", L,
                  G.DBW_SETUP, units="%", scale=0.1, digits=1, lo=0, hi=1000,
                  safety_critical=True, category="DBW"),
             "u16 permitted TPS track disagreement, 0.1 %"),
    NewField("CFG_U_APP_TOL_X10", "u16", 1,
             Meta("CFG_U_APP_TOL_X10", "appTolX10", "Pedal track tolerance", L,
                  G.DBW_SETUP, units="%", scale=0.1, digits=1, lo=0, hi=1000,
                  safety_critical=True, category="DBW"),
             "u16 permitted pedal track disagreement, 0.1 %"),

    # ---- lambda, first class on both channels ---------------------------
    # The two u16 masks come FIRST so the six u8 selectors that follow leave
    # the block even-aligned. An explicit order beats a pad byte nothing owns.
    NewField("CFG_U_LAM1_CYLMASK", "u16", 1,
             Meta("CFG_U_LAM1_CYLMASK", "lambda1CylMask", "Lambda 1 cylinders", Z,
                  G.SENSOR_ROUTING, lo=0, hi=4095, category="Lambda"),
             "u16 bitmask of cylinders lambda 1 is responsible for"),
    NewField("CFG_U_LAM2_CYLMASK", "u16", 1,
             Meta("CFG_U_LAM2_CYLMASK", "lambda2CylMask", "Lambda 2 cylinders", Z,
                  G.SENSOR_ROUTING, lo=0, hi=4095, category="Lambda"),
             "u16 bitmask of cylinders lambda 2 is responsible for"),
    NewField("CFG_U_LAM1_SRC", "u8", 1,
             Meta("CFG_U_LAM1_SRC", "lambda1Source", "Lambda 1 source", Z,
                  G.SENSOR_ROUTING, lo=0, hi=3, enum=ENUM_LAMBDA_SRC,
                  category="Lambda"),
             "u8 lambda 1 controller source, 0 = disabled"),
    NewField("CFG_U_LAM1_BANK", "u8", 1,
             Meta("CFG_U_LAM1_BANK", "lambda1Bank", "Lambda 1 bank", Z,
                  G.SENSOR_ROUTING, lo=0, hi=3, enum=ENUM_BANK, category="Lambda"),
             "u8 which bank lambda 1 measures"),
    NewField("CFG_U_LAM1_AUTH", "u8", 1,
             Meta("CFG_U_LAM1_AUTH", "lambda1AuthPct", "Lambda 1 trim authority",
                  L, G.SENSOR_ROUTING, units="%", lo=0, hi=50,
                  safety_critical=True, category="Lambda"),
             "u8 closed-loop trim authority for lambda 1, percent"),
    NewField("CFG_U_LAM2_SRC", "u8", 1,
             Meta("CFG_U_LAM2_SRC", "lambda2Source", "Lambda 2 source", Z,
                  G.SENSOR_ROUTING, lo=0, hi=3, enum=ENUM_LAMBDA_SRC,
                  category="Lambda"),
             "u8 lambda 2 controller source, 0 = disabled"),
    NewField("CFG_U_LAM2_BANK", "u8", 1,
             Meta("CFG_U_LAM2_BANK", "lambda2Bank", "Lambda 2 bank", Z,
                  G.SENSOR_ROUTING, lo=0, hi=3, enum=ENUM_BANK, category="Lambda"),
             "u8 which bank lambda 2 measures"),
    NewField("CFG_U_LAM2_AUTH", "u8", 1,
             Meta("CFG_U_LAM2_AUTH", "lambda2AuthPct", "Lambda 2 trim authority",
                  L, G.SENSOR_ROUTING, units="%", lo=0, hi=50,
                  safety_critical=True, category="Lambda"),
             "u8 closed-loop trim authority for lambda 2, percent"),
    NewField("CFG_U_STOICH_X100", "u16", 1,
             Meta("CFG_U_STOICH_X100", "stoichAfrX100", "Fuel stoichiometric ratio",
                  L, G.ENGINE_SETUP, scale=0.01, digits=2, lo=500, hi=2500,
                  safety_critical=True, category="Lambda",
                  note="The ONLY place AFR and lambda are related. Internal "
                       "targets are lambda; AFR is a display conversion."),
             "u16 stoichiometric air/fuel ratio x100, 1470 = 14.70 gasoline"),

    # ---- injector and coil component data -------------------------------
    NewField("CFG_U_INJ_FLOW_CCMIN", "u16", 1,
             Meta("CFG_U_INJ_FLOW_CCMIN", "injFlowCcMin", "Injector flow", Z,
                  G.INJECTOR_ROUTING, units="cc/min", lo=0, hi=5000,
                  category="Fuel"),
             "u16 static flow at the reference pressure, cc/min"),
    NewField("CFG_U_INJ_REF_KPA", "u16", 1,
             Meta("CFG_U_INJ_REF_KPA", "injRefPressureKpa", "Injector test pressure",
                  Z, G.INJECTOR_ROUTING, units="kPa", lo=0, hi=2000,
                  category="Fuel"),
             "u16 differential pressure the flow figure was measured at, kPa"),
    NewField("CFG_U_CRANK_DWELL_X100", "u16", 1,
             Meta("CFG_U_CRANK_DWELL_X100", "crankingDwellMsX100",
                  "Cranking dwell", L, G.IGNITION_ROUTING, units="ms", scale=0.01,
                  digits=2, lo=0, hi=1500, safety_critical=True,
                  category="Ignition"),
             "u16 dwell while cranking, 0.01 ms"),

    # ---- motorsport ------------------------------------------------------
    NewField("CFG_U_MS_ENABLE", "u16", 1,
             Meta("CFG_U_MS_ENABLE", "motorsportEnable", "Motorsport features", Z,
                  G.MOTORSPORT, lo=0, hi=65535, safety_critical=True,
                  category="Motorsport",
                  note="Bit per domain: 0 launch, 1 flat shift, 2 anti-lag, "
                       "3 pit limiter, 10 rotational idle (V98, "
                       "hcengctl711.c). 4..9 are reserved (traction, map "
                       "switch, burnout, boost by gear, nitrous, water/meth "
                       "- not implemented)."),
             "u16 motorsport domain enable bits"),
    NewField("CFG_U_PIN_LAUNCH", "u8", 1,
             _pin_meta("CFG_U_PIN_LAUNCH", "pinLaunch", "Launch switch input",
                       G.MOTORSPORT, PinCap.DIN, "Motorsport"),
             "u8 physical connector pin arming launch control"),
    NewField("CFG_U_PIN_FLATSHIFT", "u8", 1,
             _pin_meta("CFG_U_PIN_FLATSHIFT", "pinFlatShift", "Clutch / flat-shift input",
                       G.MOTORSPORT, PinCap.DIN, "Motorsport"),
             "u8 physical connector pin for the flat-shift switch"),
    NewField("CFG_U_PIN_ANTILAG", "u8", 1,
             _pin_meta("CFG_U_PIN_ANTILAG", "pinAntiLag", "ALS enable input",
                       G.MOTORSPORT, PinCap.DIN, "Motorsport"),
             "u8 physical connector pin arming anti-lag"),
    NewField("CFG_U_PIN_PITLIM", "u8", 1,
             _pin_meta("CFG_U_PIN_PITLIM", "pinPitLimiter", "Pit limiter input",
                       G.MOTORSPORT, PinCap.DIN, "Motorsport"),
             "u8 physical connector pin for the pit-lane switch"),
    NewField("CFG_U_PIN_MAPSWITCH", "u8", 1,
             _pin_meta("CFG_U_PIN_MAPSWITCH", "pinMapSwitch", "Map switch pin",
                       G.MOTORSPORT, PinCap.DIN, "Motorsport", crit=False),
             "u8 physical connector pin for driver-mode selection"),
    NewField("CFG_U_PIN_VSS", "u8", 1,
             _pin_meta("CFG_U_PIN_VSS", "pinVss", "Road speed pin",
                       G.MOTORSPORT, PinCap.FREQ_IN, "Motorsport", crit=False),
             "u8 physical connector pin for the road speed signal"),
    NewField("CFG_U_LAUNCH_RPM", "u16", 1,
             Meta("CFG_U_LAUNCH_RPM", "launchRpm", "Launch: rpm", L,
                  G.MOTORSPORT, units="rpm", lo=0, hi=20000, safety_critical=True,
                  category="Motorsport"),
             "u16 launch control target speed"),
    NewField("CFG_U_LAUNCH_RETARD_X10", "s16", 1,
             Meta("CFG_U_LAUNCH_RETARD_X10", "launchRetardDegX10", "Launch: ignition timing",
                  L, G.MOTORSPORT, units="deg", scale=0.1, digits=1,
                  lo=-900, hi=900, safety_critical=True, category="Motorsport"),
             "s16 launch spark retard, 0.1 deg, signed"),
    NewField("CFG_U_FLATSHIFT_RPM", "u16", 1,
             Meta("CFG_U_FLATSHIFT_RPM", "flatShiftArmRpm", "Flat shift: above rpm", L,
                  G.MOTORSPORT, units="rpm", lo=0, hi=20000, category="Motorsport"),
             "u16 minimum speed at which flat shift arms"),
    NewField("CFG_U_FLATSHIFT_CUT_MS", "u16", 1,
             Meta("CFG_U_FLATSHIFT_CUT_MS", "flatShiftCutMs", "Flat shift: cut time",
                  L, G.MOTORSPORT, units="ms", lo=0, hi=2000,
                  safety_critical=True, category="Motorsport"),
             "u16 how long the shift cut lasts"),
    NewField("CFG_U_ANTILAG_RETARD_X10", "s16", 1,
             Meta("CFG_U_ANTILAG_RETARD_X10", "antiLagRetardDegX10",
                  "Anti-lag: timing change", L, G.MOTORSPORT, units="deg", scale=0.1,
                  digits=1, lo=-900, hi=900, safety_critical=True,
                  category="Motorsport"),
             "s16 anti-lag spark retard, 0.1 deg, signed"),
    NewField("CFG_U_ANTILAG_FUEL_PCT", "u8", 1,
             Meta("CFG_U_ANTILAG_FUEL_PCT", "antiLagFuelPct", "Anti-lag: fuel added",
                  L, G.MOTORSPORT, units="%", lo=0, hi=100, safety_critical=True,
                  category="Motorsport"),
             "u8 anti-lag fuel enrichment, percent"),
    NewField("CFG_U_PITLIM_RPM_PAD", "u8", 1,
             Meta("CFG_U_PITLIM_RPM_PAD", "msPad", "Alignment pad", L, G.GENERAL,
                  lo=0, hi=255, category="Controller"),
             "u8 keeps the next u16 even-aligned"),
    NewField("CFG_U_PITLIM_RPM", "u16", 1,
             Meta("CFG_U_PITLIM_RPM", "pitLimiterRpm", "Pit limiter: rpm", L,
                  G.MOTORSPORT, units="rpm", lo=0, hi=20000, safety_critical=True,
                  category="Motorsport"),
             "u16 pit lane speed limiter"),

    # ---- engine protection ----------------------------------------------
    NewField("CFG_U_OILP_MIN_KPA", "u16", 1,
             Meta("CFG_U_OILP_MIN_KPA", "oilPressMinKpa", "Minimum oil pressure",
                  L, G.GENERAL, units="kPa", lo=0, hi=2000, safety_critical=True,
                  category="Safety",
                  note="LIVE_APPLY and SAFETY_CRITICAL at once - which is why "
                       "the two are separate fields and not one enum."),
             "u16 oil pressure below which the protection policy acts"),
    NewField("CFG_U_OILP_MIN_RPM", "u16", 1,
             Meta("CFG_U_OILP_MIN_RPM", "oilPressMinRpm", "Oil pressure check above",
                  L, G.GENERAL, units="rpm", lo=0, hi=20000, category="Safety"),
             "u16 engine speed above which the oil pressure check is active"),
    NewField("CFG_U_CLT_MAX_X10", "u16", 1,
             Meta("CFG_U_CLT_MAX_X10", "cltMaxDegX10", "Coolant limit", L,
                  G.GENERAL, units="C", scale=0.1, translate=-1000.0, digits=1,
                  lo=0, hi=65535, safety_critical=True, category="Safety"),
             "u16 coolant temperature limit, 0.1 degC + 1000"),

    # ---- bench test ------------------------------------------------------
    NewField("CFG_U_TEST_MODE", "u8", 1,
             Meta("CFG_U_TEST_MODE", "testMode", "Bench test", Z, G.GENERAL,
                  lo=0, hi=10, safety_critical=True, enum=ENUM_TEST_MODE,
                  category="Controller",
                  note="RPM_ZERO. Selecting a test does not drive anything on "
                       "its own: outputsArmed and the RPM gate still apply."),
             "u8 selected bench test"),
    NewField("CFG_U_TEST_PIN", "u8", 1,
             _pin_meta("CFG_U_TEST_PIN", "testPin", "Bench test pin", G.GENERAL,
                       0, "Controller"),
             "u8 physical connector pin the bench test addresses"),
    NewField("CFG_U_TEST_VALUE", "u16", 1,
             Meta("CFG_U_TEST_VALUE", "testValue", "Bench test value", L, G.GENERAL,
                  lo=0, hi=65535, safety_critical=True, category="Controller"),
             "u16 bench test command value - duty, pulse width or state"),
    NewField("CFG_U_TEST_TIMEOUT_MS", "u16", 1,
             Meta("CFG_U_TEST_TIMEOUT_MS", "testTimeoutMs", "Bench test timeout", L,
                  G.GENERAL, units="ms", lo=0, hi=60000, safety_critical=True,
                  category="Controller",
                  note="A bench test that cannot time out is a stuck injector."),
             "u16 bench test self-cancel timeout"),
    # ------------------------------------------------------------------
    # THE S5500 WINDOW, AS AN ORDINARY PAGE FIELD.
    #
    # It is already movable with the '!W' command, and that command is
    # proven to work against the frozen V29 binary offline
    # (me711_s5500_command_proof). On the real ECU on 2026-09-02 the
    # TunerStudio commandButton bound to it transmitted NOTHING, with a
    # correctly parsing .ini and the controller online, and this
    # repository contains no source for the K-line transport plugin that
    # would say why.
    #
    # So the sweep gets a SECOND, INDEPENDENT path that does not use
    # [ControllerCommands] at all: a normal u8 on the calibration page.
    # Changing it is the same 'W' page write TunerStudio performs for
    # every other field on every other dialog - the single most exercised
    # mechanism in the protocol, and one whose read half is already
    # PHYSICALLY VERIFIED on this ECU. A diagnostic that depends on the
    # one mechanism that has failed on hardware is not a diagnostic.
    NewField("CFG_U_S5500_BASE", "u8", 1,
             Meta("CFG_U_S5500_BASE", "s5500WindowBase",
                  "Analog window base word", L, G.GENERAL,
                  lo=0, hi=117, category="Controller",
                  note="The first runtime-frame word the 16-word "
                       "correlation window shows. Editing this field moves "
                       "the window - no button, no ControllerCommand. "
                       "Watch s5500Idx: 0xFFFF means all sixteen words "
                       "decode as ADDAT channels 0..15, which is the "
                       "analog block."),
             "u8 first S5500 runtime-frame word in the correlation window"),
    # ---- the closed-loop throttle -------------------------------------
    #
    # THE HAL OWNS THE BRIDGE; THE PAGE OWNS THE THROTTLE. S8100's pins,
    # EGENFR and SF come from hctarget.h because they are the ECU. Which way
    # the motor turns, how much authority the controller may use, how fast the
    # target may move and how close is close enough all belong to whichever
    # throttle body is bolted on - the first one will be a VAG 1.8T unit - so
    # they are ordinary configuration.
    NewField("CFG_U_DBW_MOTOR_DIR", "u8", 1,
             Meta("CFG_U_DBW_MOTOR_DIR", "dbwMotorDir",
                  "Throttle motor direction", Z, G.DBW_SETUP,
                  lo=0, hi=1, safety_critical=True, category="DBW",
                  note="Which DVE2 level opens the plate. RPM_ZERO and "
                       "safety critical: getting it wrong makes the "
                       "controller drive AWAY from its target, which the "
                       "deviation supervisor then catches and shuts the "
                       "bridge down. MEASURED on the bench, never guessed."),
             "u8 0 = DVE2 low opens, 1 = DVE2 high opens"),
    NewField("CFG_U_FUEL_PUMP_MODE", "u8", 1,
             Meta("CFG_U_FUEL_PUMP_MODE", "fuelPumpMode",
                  "Fuel pump mode", Z, G.OUTPUT_ROUTING,
                  lo=0, hi=1, safety_critical=True, enum=ENUM_PUMP_MODE,
                  category="I/O",
                  note="OFF never commands the pump. AUTO runs the lifecycle: "
                       "one bounded prime per key cycle, on while the engine "
                       "turns, OFF the moment it stops. THERE IS DELIBERATELY "
                       "NO LATCHING 'ON'. A page setting that energises a fuel "
                       "pump indefinitely is the one thing a fuel pump relay "
                       "exists to prevent; the bench mode in hcbench.c is the "
                       "explicit test path and it is bounded, finite and "
                       "gated on RPM zero."),
             "u8 fuel pump logical mode"),
    # V100: WAS `ioPad`, A DECLARED BUT UNREAD ALIGNMENT BYTE. The wideband
    # heater policy takes it over instead of growing the page, because NCODE
    # is a single 64512-byte CGROUP with nothing left (measured: a new field
    # plus its own pad put the image 86 bytes over, L5 on
    # ?PR?HC_CONFIG_GENERATED). Consuming the pad keeps EVERY offset and the
    # page size identical, so the car's Burned calibration still loads and
    # only this one byte changes meaning - it read 0, which is
    # LAMBDA_HEAT_OFF, so a migration must set it deliberately.
    NewField("CFG_U_LAM_HEAT_POLICY", "u8", 1,
             Meta("CFG_U_LAM_HEAT_POLICY", "lambdaHeatPolicy",
                  "Wideband heater", Z, G.GENERAL,
                  lo=0, hi=2, enum=ENUM_LAMBDA_HEAT, category="Lambda",
                  note="When the LSU heater may run. Disabled never heats. "
                       "Ignition-on requires key and qualified ECU supply; "
                       "Running-only additionally requires engine running, "
                       "then grants a finite 30 s tail after an allowed run. "
                       "Choose policy only after measuring actual H+ at the "
                       "sensor during key-on, crank, run and stall. ECU UBAT "
                       "does not prove heater-feed availability. Sensor type, "
                       "loaded polarity, current limits and condensation "
                       "handling remain PHYSICAL QUALIFICATION PENDING. "
                       "rusEFI uses voltage plus explicit heater permission; "
                       "its installation assumptions are not a qualification "
                       "of this ECU or harness."),
             "u8 V100 when the LSU heater may run (rusEFI HeaterAllow)"),
    NewField("CFG_U_MAIN_RELAY_HOLD_MS", "u16", 1,
             Meta("CFG_U_MAIN_RELAY_HOLD_MS", "mainRelayHoldMs",
                  "Main relay release delay", L, G.RELAY_SETUP,
                  units="ms", lo=0, hi=60000, category="I/O",
                  note="In AUTO, how long the relay is held after the ECU "
                       "stops wanting power. This is a RELEASE DELAY, not an "
                       "after-run programme: nothing schedules fans, purge "
                       "or an EEPROM write behind it. Keep it short until "
                       "there is a reason for it to be long."),
             "u16 AUTO release delay after the run request drops"),
    NewField("CFG_U_DBW_MAX_DUTY_X10", "u16", 1,
             Meta("CFG_U_DBW_MAX_DUTY_X10", "dbwMaxDutyX10",
                  "Throttle output authority", L, G.DBW_SETUP,
                  units="%", scale=0.1, digits=1, lo=0, hi=1000,
                  safety_critical=True, category="DBW",
                  note="The ceiling on the H-bridge duty the controller may "
                       "ask for. This is the authority limit, not a "
                       "calibration: a controller that can only ask for 30 % "
                       "cannot slam a plate open however wrong its gains "
                       "are."),
             "u16 maximum H-bridge duty the controller may request, 0.1 %"),
    NewField("CFG_U_DBW_RATE_X10", "u16", 1,
             Meta("CFG_U_DBW_RATE_X10", "dbwRateX10",
                  "Throttle target rate limit", L, G.DBW_SETUP,
                  units="%/s", scale=0.1, digits=1, lo=0, hi=65535,
                  category="DBW",
                  note="How fast the TARGET may move, in 0.1 % of travel per "
                       "second. 0 disables the limit. It bounds how violently "
                       "a pedal step can be handed to the controller."),
             "u16 target slew limit, 0.1 % of travel per second"),
    NewField("CFG_U_DBW_DEADBAND_X10", "u16", 1,
             Meta("CFG_U_DBW_DEADBAND_X10", "dbwDeadbandX10",
                  "Throttle position deadband", L, G.DBW_SETUP,
                  units="%", scale=0.1, digits=1, lo=0, hi=200,
                  category="DBW",
                  note="Position error below this is treated as zero, so the "
                       "controller stops dithering the motor against sensor "
                       "noise at a steady target. It does NOT widen the "
                       "deviation supervisor's window."),
             "u16 position error treated as zero, 0.1 % of travel"),

    # ---- fixed timing, for a timing light ---------------------------------
    #
    # rusEFI's own control, copied because it is the same problem:
    #
    #     timingMode  = bits, U08, [0:0], "dynamic", "fixed"
    #     fixedTiming = scalar, F32, "deg", ...
    #     field = "#Use fixed timing while validating with a timing gun"
    #
    # and in the firmware, IgnitionState::getAdvance():
    #
    #     if (engineConfiguration->timingMode == TM_FIXED) {
    #         // fixed timing is the simple: cranking/running does not
    #         // matter, no corrections!
    #         return engineConfiguration->fixedTiming;
    #     }
    #
    # This is core commissioning, not a convenience. Until a timing light has
    # confirmed that commanded advance IS crank advance, every number in the
    # ignition map is a hypothesis about where the spark actually lands - and
    # the tooth offset, the TDC table and the scheduler's angle maths are all
    # in that chain.
    #
    # HaniCore stores 0.1 degrees in a u16 rather than rusEFI's float degrees,
    # because the page is fixed point everywhere and eng_adv_x10 already is.
    NewField("CFG_U_TIMING_MODE", "u8", 1,
             Meta("CFG_U_TIMING_MODE", "timingModeCfg",
                  "Ignition timing mode", L, G.TABLES,
                  lo=0, hi=1, category="Ignition", safety_critical=True,
                  note="Dynamic uses the ignition map. FIXED holds the angle "
                       "below at every speed and load, ignores cranking and "
                       "applies no correction - it is for checking with a "
                       "timing light that the spark lands where the ECU "
                       "thinks it does, and for nothing else."),
             "u8 0 = dynamic (the map), 1 = FIXED (timing light)"),
    # A DECLARED pad, because the generator refuses an unowned byte: a hole the
    # .ini cannot account for is a byte the layout CRC covers and nothing
    # names.
    NewField("CFG_U_IGN_PAD", "u8", 1,
             Meta("CFG_U_IGN_PAD", "ignPad", "Alignment pad", L, G.TABLES,
                  lo=0, hi=255, category="Ignition"),
             "u8 alignment pad"),
    NewField("CFG_U_FIXED_TIMING_X10", "u16", 1,
             Meta("CFG_U_FIXED_TIMING_X10", "fixedTimingX10",
                  "Fixed ignition advance", L, G.TABLES,
                  units="deg", scale=0.1, digits=1, lo=0, hi=600,
                  category="Ignition", safety_critical=True,
                  note="The angle commanded while the timing mode is FIXED, "
                       "degrees before top dead centre. Only read in that "
                       "mode. The firmware clamps it to the same hard ceiling "
                       "as the map."),
             "u16 the angle FIXED mode commands, 0.1 deg BTDC"),

    # ---- V92: CAM PHASE BY LEVEL, the Bosch quick-start method -------------
    #
    # The AWT's Hall cam is the Bosch "Schnellstart-Geberrad": four edges of
    # one polarity EQUALLY spaced (the ones V91 captured, 180 deg apart - they
    # cannot say which revolution this is) and four of the other polarity
    # UNEVENLY spaced (sectors 140/40/40/140 crank deg). Bosch ME7.5 resolves
    # the cycle by SAMPLING THE PHASE-SENSOR LEVEL at the reference mark and
    # expecting it to alternate every revolution (A2L: B_siph "keine
    # alternierende Phasenpegel PG in den Bezugsmarken", zphfl "Zaehler
    # aequidistante Phasenflanken"). The crank stays authoritative; the cam
    # only chooses the half. The same rule serves any cam whose level differs
    # between the two revolutions at one crank angle - a single-window Hall
    # sensor included.
    NewField("CFG_U_CAM_PHASE_MODE", "u8", 1,
             Meta("CFG_U_CAM_PHASE_MODE", "camPhaseMode",
                  "Cam phase method", Z, G.TRIGGER_SETUP,
                  lo=0, hi=2, enum=ENUM_CAM_PHASE, category="Trigger",
                  safety_critical=True,
                  note="REFS: the cam edges of camEdge polarity are matched "
                       "against camRefs/camRefX10/camWindowX10 (needs an ODD "
                       "count). LEVEL: at camPhaseAngleX10 the decoder reads "
                       "the cam pin and expects camPhaseLevel there (the other "
                       "level 360 deg later); it must alternate every "
                       "revolution. LEVEL also captures both cam edges and "
                       "publishes the measured sector widths. PATTERN (V97): "
                       "each cam's wheel from the library (cam1Pattern / "
                       "cam2Pattern); teeth are identified by their spacing "
                       "in crank degrees, then the half and the VVT deviation "
                       "by their angle; camWindowX10 is the VVT authority, "
                       "camPhaseConfirm the teeth that must agree."),
             "u8 0 = reference edges, 1 = level at a crank angle, 2 = pattern"),
    NewField("CFG_U_CAM_PHASE_LEVEL", "u8", 1,
             Meta("CFG_U_CAM_PHASE_LEVEL", "camPhaseLevel",
                  "Cam level at the phase angle", Z, G.TRIGGER_SETUP,
                  lo=0, hi=1, category="Trigger", safety_critical=True,
                  note="The CPU-pin level (0 low, 1 high) of the cam input "
                       "at camPhaseAngleX10 when the engine really is at that "
                       "angle. The opposite level means the other revolution."),
             "u8 expected cam pin level at the phase angle"),
    NewField("CFG_U_CAM_PHASE_ANGLE_X10", "u16", 1,
             Meta("CFG_U_CAM_PHASE_ANGLE_X10", "camPhaseAngleX10",
                  "Cam phase check angle", Z, G.TRIGGER_SETUP,
                  units="deg", scale=0.1, digits=1, lo=0, hi=7199,
                  category="Trigger", safety_critical=True,
                  note="Engine angle (0..720, the TDC table's coordinate) at "
                       "which the cam level is sampled - degrees after "
                       "cylinder-1 TDC, physical once trigAngleX10 is right. "
                       "Correcting trigAngleX10 moves where an engine angle "
                       "lands on the crank, so re-check this after it. "
                       "Choose a point well inside a sector whose level "
                       "differs between the two revolutions."),
             "u16 engine angle of the cam level check, 0.1 deg"),
    NewField("CFG_U_CAM_PHASE_CONFIRM", "u8", 1,
             Meta("CFG_U_CAM_PHASE_CONFIRM", "camPhaseConfirm",
                  "Cam phase confirmations", Z, G.TRIGGER_SETUP,
                  lo=1, hi=8, category="Trigger", safety_critical=True,
                  note="Consecutive alternating, consistent checks before the "
                       "cycle counts as known (syncState 4)."),
             "u8 consistent checks before full sync"),
    NewField("CFG_U_CAM_PHASE_PAD", "u8", 1,
             Meta("CFG_U_CAM_PHASE_PAD", "camPhasePad", "Alignment pad", L,
                  G.TRIGGER_SETUP, lo=0, hi=255, category="Trigger"),
             "u8 alignment pad"),
    # V97: the cam PATTERN method (firmware/engine/hccam.c). APPENDED - no existing
    # offset moves; the layout id changes (tools/calibration/me711_migrate_calibration.py).
    NewField("CFG_U_CAM1_PATTERN", "u8", 1,
             Meta("CFG_U_CAM1_PATTERN", "cam1Pattern", "Cam 1 wheel", Z,
                  G.TRIGGER_SETUP, lo=0, hi=8, enum=ENUM_CAM_PATTERN,
                  category="Trigger", safety_critical=True,
                  note="The wheel on camshaft input 1 (camPhaseMode "
                       "PATTERN). Its tooth 0 is expected at camRefX10."),
             "u8 cam 1 wheel pattern (HCCAM_P_*)"),
    NewField("CFG_U_CAM2_PATTERN", "u8", 1,
             Meta("CFG_U_CAM2_PATTERN", "cam2Pattern", "Cam 2 wheel", Z,
                  G.TRIGGER_SETUP, lo=0, hi=8, enum=ENUM_CAM_PATTERN,
                  category="Trigger", safety_critical=True,
                  note="The wheel on camshaft input 2. Its tooth 0 is "
                       "expected at cam2RefX10."),
             "u8 cam 2 wheel pattern (HCCAM_P_*)"),
    NewField("CFG_U_CAM2_REF_X10", "u16", 1,
             Meta("CFG_U_CAM2_REF_X10", "cam2RefX10",
                  "Cam 2 tooth 0 angle", Z, G.TRIGGER_SETUP,
                  units="deg", scale=0.1, digits=1, lo=0, hi=7199,
                  category="Trigger", safety_critical=True,
                  note="Engine angle (0..720) of cam 2's tooth 0 at zero "
                       "VVT - what camRefX10 is for cam 1."),
             "u16 engine angle of cam 2 tooth 0, 0.1 deg"),
    NewField("CFG_U_CAM_TOOTH_TOL", "u8", 1,
             Meta("CFG_U_CAM_TOOTH_TOL", "camToothTol",
                  "Cam tooth spacing tolerance", Z, G.TRIGGER_SETUP,
                  units="deg", lo=2, hi=40, category="Trigger",
                  safety_critical=True,
                  note="How far a cam tooth spacing (in crank degrees) may "
                       "differ from the pattern and still name the tooth. "
                       "Less than half the pattern's closest tooth pair."),
             "u8 cam tooth spacing tolerance, whole degrees"),
    NewField("CFG_U_CAM_PAT_PAD", "u8", 1,
             Meta("CFG_U_CAM_PAT_PAD", "camPatPad", "Alignment pad", L,
                  G.TRIGGER_SETUP, lo=0, hi=255, category="Trigger"),
             "u8 alignment pad"),
    # V97: the boost control core (firmware/control/hcldr.c). APPENDED.
    NewField("CFG_U_BOOST_CL_MIN_X10", "u16", 1,
             Meta("CFG_U_BOOST_CL_MIN_X10", "boostClMinKpa",
                  "Closed loop above pressure", L, G.OUTPUT_ROUTING,
                  units="kPa", scale=0.1, digits=1, lo=0, hi=4000,
                  category="Boost",
                  note="Closed-loop boost runs only at or above this manifold "
                       "pressure (rusEFI minimumBoostClosedLoopMap); below it "
                       "the open-loop duty alone, PID reset. 0 = at any "
                       "pressure."),
             "u16 closed-loop boost threshold, 0.1 kPa absolute"),
    NewField("CFG_U_BOOST_I_BAND_X10", "u16", 1,
             Meta("CFG_U_BOOST_I_BAND_X10", "boostIBand",
                  "Integrate within (below target)", L, G.OUTPUT_ROUTING,
                  units="kPa", scale=0.1, digits=1, lo=0, hi=2000,
                  category="Boost",
                  note="The I term does not integrate while the pressure is "
                       "more than this BELOW target (spooling), so a target "
                       "the turbo cannot reach yet does not wind it up. Above "
                       "target it always integrates. 0 = always integrates."),
             "u16 boost I band below target, 0.1 kPa"),
    # V97: idle speed control (firmware/control/hcidle.c). APPENDED.
    NewField("CFG_U_IDLE_PEDAL_X10", "u16", 1,
             Meta("CFG_U_IDLE_PEDAL_X10", "idlePedalX10",
                  "Idle: pedal released below", L, G.OUTPUT_ROUTING,
                  units="%", scale=0.1, digits=1, lo=0, hi=200,
                  category="Idle",
                  note="The idle closed loop runs only while the pedal is at "
                       "or below this (rusEFI idlePidDeactivationTpsThreshold). "
                       "0 = 2.0 %."),
             "u16 idle pedal-released threshold, 0.1 %"),
    NewField("CFG_U_IDLE_START_MS", "u16", 1,
             Meta("CFG_U_IDLE_START_MS", "idleStartMs",
                  "Idle: closed loop after start", L, G.OUTPUT_ROUTING,
                  units="ms", lo=0, hi=20000, category="Idle",
                  note="After cranking ends the throttle holds the base "
                       "position this long before the rpm loop runs (rusEFI's "
                       "post-cranking taper). 0 = 1000 ms."),
             "u16 idle closed-loop delay after cranking, ms"),
    # V97: engine protection (firmware/control/hclimp.c). APPENDED.
    NewField("CFG_U_CLT_LIMP_RPM", "u16", 1,
             Meta("CFG_U_CLT_LIMP_RPM", "cltLimpRpm",
                  "Coolant limit: rev limit", L, G.GENERAL,
                  units="rpm", lo=0, hi=20000, category="Safety",
                  note="Above the coolant limit fuel is cut above this speed (rusEFI cltRevLimitRpm), back 200 rpm below. 0 = 3000."),
             "u16 rev limit while the coolant is over its limit"),
    NewField("CFG_U_ETB_LIMP_RPM", "u16", 1,
             Meta("CFG_U_ETB_LIMP_RPM", "etbLimpRpm",
                  "Throttle fault: rev limit", L, G.GENERAL,
                  units="rpm", lo=0, hi=20000, category="Safety",
                  note="With a latched throttle fault (DBW on) fuel is cut above this speed - the plate is on its limp spring (rusEFI reportEtbJammed). 0 = 1500."),
             "u16 rev limit on a throttle fault"),
    NewField("CFG_U_INJ_DUTY_INST_X10", "u16", 1,
             Meta("CFG_U_INJ_DUTY_INST_X10", "injDutyInstX10",
                  "Injector duty cut at once", L, G.GENERAL,
                  units="%", scale=0.1, digits=1, lo=0, hi=1000, category="Safety",
                  note="Fuel is cut while the requested injector duty is above this, until it falls below 20 % (rusEFI maxInjectorDutyInstant). 0 = off."),
             "u16 instant injector duty limit, 0.1 %"),
    NewField("CFG_U_INJ_DUTY_SUST_X10", "u16", 1,
             Meta("CFG_U_INJ_DUTY_SUST_X10", "injDutySustX10",
                  "Injector duty cut sustained", L, G.GENERAL,
                  units="%", scale=0.1, digits=1, lo=0, hi=1000, category="Safety",
                  note="Fuel is cut when the duty stays above this for injDutySustMs (rusEFI maxInjectorDutySustained). 0 = off."),
             "u16 sustained injector duty limit, 0.1 %"),
    NewField("CFG_U_INJ_DUTY_SUST_MS", "u16", 1,
             Meta("CFG_U_INJ_DUTY_SUST_MS", "injDutySustMs",
                  "Injector duty sustained for", L, G.GENERAL,
                  units="ms", lo=0, hi=20000, category="Safety",
                  note="How long the sustained limit may be exceeded."),
             "u16 sustained injector duty time, ms"),
    NewField("CFG_U_FLOOD_CLEAR_X10", "u16", 1,
             Meta("CFG_U_FLOOD_CLEAR_X10", "floodClearX10",
                  "Flood clear above pedal", L, G.GENERAL,
                  units="%", scale=0.1, digits=1, lo=0, hi=1000, category="Safety",
                  note="Cranking with the pedal (the throttle without DBW) above this injects no fuel (rusEFI isCylinderCleanupEnabled, 90 %). 0 = off."),
             "u16 flood clear threshold, 0.1 %"),
    # V97: DBW, compared with the AWT's own Bosch DLR (tools/
    # an OEM-firmware analysis script (not published)). APPENDED.
    NewField("CFG_U_DBW_FAULT_DEBOUNCE_MS", "u16", 1,
             Meta("CFG_U_DBW_FAULT_DEBOUNCE_MS", "dbwFaultDebounceMs",
                  "Sensor fault confirm time", L, G.DBW_SETUP,
                  units="ms", lo=0, hi=1000, safety_critical=True,
                  category="DBW",
                  note="How long a pedal/TPS range or pair error must "
                       "persist before it latches the throttle off until "
                       "key-off. The bridge is released on the first bad "
                       "sample either way and needs four clean 5 ms steps to "
                       "drive again; this only decides when the fault becomes "
                       "final. Default 50 ms (ten control steps). 0 = latch "
                       "on the first bad sample."),
             "u16 DBW sensor-fault debounce, ms"),
    NewField("CFG_U_DBW_BATT_COMP", "u8", 1,
             Meta("CFG_U_DBW_BATT_COMP", "dbwBattComp",
                  "Battery voltage compensation", L, G.DBW_SETUP,
                  lo=0, hi=1, enum=ENUM_DBW_BATT, category="DBW",
                  note="On: the motor output is scaled by 13.5 V / battery "
                       "so a gain means the same torque at 9 V cranking and "
                       "14 V running (Bosch DLRUBSOLL). Factor limited to "
                       "0.70..1.80."),
             "u8 DBW battery compensation, 0 on"),
    NewField("CFG_U_DBW_PAD", "u8", 1,
             Meta("CFG_U_DBW_PAD", "dbwPad", "Alignment pad", L, G.DBW_SETUP,
                  lo=0, hi=255, category="DBW"),
             "u8 alignment pad"),
    # V97: sequential injection (docs/ARCHITECTURE.md). APPENDED.
    NewField("CFG_U_INJ_TIMING_MODE", "u8", 1,
             Meta("CFG_U_INJ_TIMING_MODE", "injTimingMode",
                  "Injection timing refers to", Z, G.INJECTOR_ROUTING,
                  lo=0, hi=1, enum=ENUM_INJ_TIMING, category="Fuel",
                  note="Start: the injection angle is where the pulse STARTS. "
                       "End: where it ENDS (Bosch KFWEE, rusEFI's usual "
                       "choice) - the end places the fuel relative to the "
                       "intake valve whatever the pulse length. The angle is "
                       "degrees BEFORE the cylinder's compression TDC."),
             "u8 injection timing mode, 0 start 1 end"),
    NewField("CFG_U_SEQ_PAD", "u8", 1,
             Meta("CFG_U_SEQ_PAD", "seqPad", "Alignment pad", L,
                  G.INJECTOR_ROUTING, lo=0, hi=255, category="Fuel"),
             "u8 alignment pad"),
    # V97: transient fuel - the X-tau wall film + after-start (shared/
    # hctrans.c, docs/ARCHITECTURE.md). The curves use the warm-up
    # coolant axis (cltEnrAx). APPENDED.
    NewField("CFG_U_TRANS_ENABLE", "u8", 1,
             Meta("CFG_U_TRANS_ENABLE", "transEnable", "Transient fuel", L,
                  G.TABLES, lo=0, hi=1, enum=ENUM_OFF_ON, category="Fuel",
                  note="On: the wall-film model and after-start correct the "
                       "fuel per cycle (every injection mode). Off: the "
                       "steady model alone."),
             "u8 transient fuel enable"),
    NewField("CFG_U_TRANS_PAD", "u8", 1,
             Meta("CFG_U_TRANS_PAD", "transPad", "Alignment pad", L,
                  G.TABLES, lo=0, hi=255, category="Fuel"),
             "u8 alignment pad"),
    NewField("CFG_U_AS_DECAY_MS", "u16", 1,
             Meta("CFG_U_AS_DECAY_MS", "asDecayMs", "After-start duration", L,
                  G.TABLES, units="s", scale=0.001, digits=1, lo=0, hi=60000,
                  category="Fuel",
                  note="The after-start extra decays linearly to none over "
                       "this time from the moment cranking ends (rusEFI "
                       "postCrankingDurationSec)."),
             "u16 after-start decay, ms"),
    NewField("CFG_U_WW_X_PCT", "u8", 16,
             Meta("CFG_U_WW_X_PCT", "wwXPct", "Wall wetting fraction", L,
                  G.TABLES, units="%", lo=0, hi=90, category="Fuel",
                  note="Of every injection this share lands on the port "
                       "wall (X). More = more extra fuel on a tip-in, less "
                       "on a tip-out. Typical 20..50 %, more when cold."),
             "u8[16] wall-film fraction X vs coolant, %"),
    NewField("CFG_U_WW_TAU_20MS", "u8", 16,
             Meta("CFG_U_WW_TAU_20MS", "wwTau", "Wall film time constant", L,
                  G.TABLES, units="s", scale=0.02, digits=2, lo=1, hi=255,
                  category="Fuel",
                  note="How long the wall film takes to evaporate into the "
                       "cylinder (tau). Longer = the correction lasts longer. "
                       "Typical 0.2..0.6 s warm, 1..3 s cold."),
             "u8[16] wall-film tau vs coolant, 20 ms"),
    NewField("CFG_U_AS_PCT", "u8", 16,
             Meta("CFG_U_AS_PCT", "asPct", "After-start extra fuel", L,
                  G.TABLES, units="%", lo=0, hi=200, category="Fuel",
                  note="Extra fuel the moment cranking ends, decaying over "
                       "the after-start duration (rusEFI postCrankingFactor "
                       "- 1)."),
             "u8[16] after-start extra vs coolant, %"),
    # V97: ignition timing corrections (rusEFI ignitionCltCorr /
    # ignitionIatCorr, 1D here). Added to the table advance while RUNNING
    # (not cranking, not fixed timing). APPENDED.
    NewField("CFG_U_IGN_CLT_CORR", "s16", 16,
             Meta("CFG_U_IGN_CLT_CORR", "ignCltCorr", "CLT timing correction", L,
                  G.TABLES, units="deg", scale=0.1, digits=1, lo=-300, hi=300,
                  category="Ignition",
                  note="Added to the advance at this coolant (warm-up axis). "
                       "+ = more advance, - = retard. 0 everywhere = off."),
             "s16[16] ignition correction vs coolant, 0.1 deg"),
    NewField("CFG_U_IGN_IAT_AX", "u16", 8,
             Meta("CFG_U_IGN_IAT_AX", "ignIatAx", "IAT timing correction axis", L,
                  G.TABLES, units="C", scale=0.1, translate=-1000.0, digits=0,
                  lo=9600, hi=11500, category="Ignition"),
             "u16[8] intake air axis, 10*C + 10000"),
    NewField("CFG_U_IGN_IAT_CORR", "s16", 8,
             Meta("CFG_U_IGN_IAT_CORR", "ignIatCorr", "IAT timing correction", L,
                  G.TABLES, units="deg", scale=0.1, digits=1, lo=-300, hi=300,
                  category="Ignition",
                  note="Added to the advance at this intake air temperature. "
                       "Hot intake air knocks earlier: retard there. 0 = off."),
             "s16[8] ignition correction vs intake air, 0.1 deg"),
    # V97: closed-loop idle ignition timing (rusEFI useIdleTimingPidControl /
    # idleTimingPid P, min, max, idleTimingSoftEntryTime; P only, like
    # rusEFI's default iFactor 0)
    NewField("CFG_U_IDLE_TIM_EN", "u8", 1,
             Meta("CFG_U_IDLE_TIM_EN", "idleTimingEnable",
                  "Closed loop idle ignition timing", L, G.OUTPUT_ROUTING,
                  lo=0, hi=1, enum=ENUM_OFF_ON, category="Idle",
                  note="On: while the idle throttle loop is CLOSED, spark "
                       "advance is added below the target rpm and taken away "
                       "above it - spark answers within a cycle, the throttle "
                       "takes the manifold's time. Needs idle control on."),
             "u8 idle timing enable"),
    NewField("CFG_U_IDLE_TIM_PAD", "u8", 1,
             Meta("CFG_U_IDLE_TIM_PAD", "idleTimingPad", "Alignment pad", L,
                  G.OUTPUT_ROUTING, lo=0, hi=255, category="Idle"),
             "u8 alignment pad"),
    NewField("CFG_U_IDLE_TIM_KP", "u16", 1,
             Meta("CFG_U_IDLE_TIM_KP", "idleTimingKp",
                  "Idle timing proportional gain", L, G.OUTPUT_ROUTING,
                  units="deg/100rpm", scale=0.1, digits=1, lo=0, hi=500,
                  category="Idle",
                  note="Degrees per 100 rpm of error. rusEFI's starting point "
                       "is 10 (0.1 deg/rpm)."),
             "u16 idle timing P, 0.1 deg per 100 rpm"),
    NewField("CFG_U_IDLE_TIM_MIN", "s16", 1,
             Meta("CFG_U_IDLE_TIM_MIN", "idleTimingMinX10",
                  "Idle timing min adjustment (retard)", L, G.OUTPUT_ROUTING,
                  units="deg", scale=0.1, digits=1, lo=-300, hi=0,
                  category="Idle"),
             "s16 idle timing most retard, 0.1 deg"),
    NewField("CFG_U_IDLE_TIM_MAX", "s16", 1,
             Meta("CFG_U_IDLE_TIM_MAX", "idleTimingMaxX10",
                  "Idle timing max adjustment (advance)", L, G.OUTPUT_ROUTING,
                  units="deg", scale=0.1, digits=1, lo=0, hi=300,
                  category="Idle"),
             "s16 idle timing most advance, 0.1 deg"),
    NewField("CFG_U_IDLE_TIM_SOFT_MS", "u16", 1,
             Meta("CFG_U_IDLE_TIM_SOFT_MS", "idleTimingSoftMs",
                  "Idle timing soft entry", L, G.OUTPUT_ROUTING,
                  units="s", scale=0.001, digits=1, lo=0, hi=10000,
                  category="Idle",
                  note="The correction grows from 0 to full over this time "
                       "after the idle loop closes (rusEFI "
                       "idleTimingSoftEntryTime). 0 = at once."),
             "u16 idle timing soft entry, ms"),
    # V97: the dashpot (rusEFI iacByTpsTaper / iacByTpsHoldTime /
    # iacByTpsDecayTime, "Extra Idle Features")
    NewField("CFG_U_IDLE_DASH_X10", "u16", 1,
             Meta("CFG_U_IDLE_DASH_X10", "idleDashX10",
                  "Dashpot coasting-to-idle initial adder", L, G.OUTPUT_ROUTING,
                  units="%", scale=0.1, digits=1, lo=0, hi=200,
                  category="Idle",
                  note="Throttle added to the idle floor after the pedal is "
                       "released: held, then decayed to 0 - a slow pedal "
                       "release that keeps a coasting engine from dipping into "
                       "idle. The idle trim is held meanwhile. 0 = off."),
             "u16 dashpot adder, 0.1 % throttle"),
    NewField("CFG_U_IDLE_DASH_HOLD_MS", "u16", 1,
             Meta("CFG_U_IDLE_DASH_HOLD_MS", "idleDashHoldMs",
                  "Dashpot coasting-to-idle hold time", L, G.OUTPUT_ROUTING,
                  units="s", scale=0.001, digits=1, lo=0, hi=25000,
                  category="Idle"),
             "u16 dashpot hold, ms"),
    NewField("CFG_U_IDLE_DASH_DECAY_MS", "u16", 1,
             Meta("CFG_U_IDLE_DASH_DECAY_MS", "idleDashDecayMs",
                  "Dashpot coasting-to-idle decay time", L, G.OUTPUT_ROUTING,
                  units="s", scale=0.001, digits=1, lo=0, hi=25000,
                  category="Idle"),
             "u16 dashpot decay, ms"),
    # V97: KNOCK CONTROL (hcknock711.c + firmware/control/hcknock.c, docs/ARCHITECTURE.md).
    # The mechanism is Bosch ME7 KR (read from a paired Porsche ME7.1.1
    # sibling A2L + binary) with rusEFI's time-based recovery. APPENDED; every
    # value is live. The board default is OFF.
    # V97: THE CHECK-ENGINE LAMP OUTPUT (hcdtc711.c + firmware/diagnostics/hccel.c). The
    # stage: cavity 47, a CJ920 low side fed from ASIC P7.0 (the ME7.1.1 schematic W12
    # sheet LUES2_PX70 -> 47 "A_S_LUES2 / A_S_SPOEKUE / A_S_MIL"; the family
    # table's MIL_S; the AWT ME7.5 map's MIL lamp on 47). APPENDED.
    NewField("CFG_U_CEL_ENABLE", "u8", 1,
             Meta("CFG_U_CEL_ENABLE", "celEnable", "Check engine lamp output",
                  L, G.OUTPUT_ROUTING, lo=0, hi=1, enum=ENUM_OFF_ON,
                  category="I/O",
                  note="On: the lamp policy (key-on test, then the MIL "
                       "request of the trouble codes) drives the lamp "
                       "cavity. Off: the stage stays off."),
             "u8 check engine lamp output enable"),
    NewField("CFG_U_PIN_MIL", "u8", 1,
             _pin_meta("CFG_U_PIN_MIL", "pinMil", "Check engine lamp pin",
                       G.OUTPUT_ROUTING, PinCap.LOW_SIDE, "I/O", crit=False,
                       note="Only cavity 47 (the ASIC P7.0 low side) can "
                            "drive a lamp on this ECU; any other cavity is "
                            "refused."),
             "u8 physical connector pin for the check engine lamp"),
    NewField("CFG_U_CEL_TEST_ENABLE", "u8", 1,
             Meta("CFG_U_CEL_TEST_ENABLE", "celTestEnable",
                  "Key-on lamp test", L, G.OUTPUT_ROUTING, lo=0, hi=1,
                  enum=ENUM_OFF_ON, category="I/O",
                  note="On: at every key-on the lamp is ON for the test time, "
                       "then OFF for the gap, then shows the MIL request - so "
                       "a stored fault reads ON-OFF-ON."),
             "u8 key-on lamp test enable"),
    NewField("CFG_U_CEL_PAD", "u8", 1,
             Meta("CFG_U_CEL_PAD", "celPad", "Alignment pad", L,
                  G.OUTPUT_ROUTING, lo=0, hi=255, category="I/O"),
             "u8 alignment pad"),
    NewField("CFG_U_CEL_TEST_ON_MS", "u16", 1,
             Meta("CFG_U_CEL_TEST_ON_MS", "celTestOnMs", "Lamp test ON time",
                  L, G.OUTPUT_ROUTING, units="s", scale=0.001, digits=1,
                  lo=0, hi=10000, category="I/O"),
             "u16 lamp test ON, ms"),
    NewField("CFG_U_CEL_TEST_GAP_MS", "u16", 1,
             Meta("CFG_U_CEL_TEST_GAP_MS", "celTestGapMs", "Lamp test OFF gap",
                  L, G.OUTPUT_ROUTING, units="s", scale=0.001, digits=1,
                  lo=0, hi=10000, category="I/O"),
             "u16 lamp test dark gap, ms"),
    NewField("CFG_U_KNOCK_MODE", "u8", 1,
             Meta("CFG_U_KNOCK_MODE", "knockMode", "Knock control", L, G.TABLES,
                  lo=0, hi=2, enum=ENUM_KNOCK_MODE, category="Knock",
                  note="Monitor: every window is measured, knock is detected "
                       "and logged per cylinder, the spark is NOT changed - the "
                       "way to calibrate. Active: a detected knock retards that "
                       "cylinder's spark. Off: the CC195 lines are released."),
             "u8 knock mode, 0 off 1 monitor 2 active"),
    NewField("CFG_U_KNOCK_BAND", "u8", 1,
             Meta("CFG_U_KNOCK_BAND", "knockBand", "Band-pass centre frequency",
                  L, G.TABLES, lo=0, hi=8, enum=ENUM_KNOCK_BAND,
                  category="Knock",
                  note="The CC195 band-pass. The stock VAG 1.8T calibration "
                       "(4B0906018DC) and this Porsche ECU both run 14 kHz."),
             "u8 CC195 band index, 0..8 = 5..16 kHz"),
    NewField("CFG_U_KNOCK_GAIN", "u8", 4,
             Meta("CFG_U_KNOCK_GAIN", "knockGain", "Sensor gain", L, G.TABLES,
                  lo=0, hi=6, enum=ENUM_KNOCK_GAIN, category="Knock",
                  note="Per sensor. Aim for a quiet-engine reference around "
                       "100..500 counts (knock reference): too low and knock "
                       "is lost in the ADC step, too high and the integrator "
                       "saturates at 1023."),
             "u8[4] CC195 gain step per sensor, 0..6 = x2..x128"),
    NewField("CFG_U_KNOCK_SENSOR", "u8", 8,
             Meta("CFG_U_KNOCK_SENSOR", "knockSensor", "Sensor for cylinder", L,
                  G.TABLES, lo=0, hi=3, enum=ENUM_KNOCK_SENSOR,
                  category="Knock",
                  note="Which sensor hears each cylinder (cylinder number = "
                       "the TDC table's). Sensor n is the OEM's select code "
                       "(3, 2, 0, 1 on KSA1/KSA2); its connector cavity is "
                       "PROBABLY 106 / 107 / 31 / 16 (family table)."),
             "u8[8] knock sensor per cylinder, 0..3"),
    NewField("CFG_U_KNOCK_RPM_AX", "u16", 8,
             Meta("CFG_U_KNOCK_RPM_AX", "knockRpmAx", "Knock window rpm axis", L,
                  G.TABLES, units="rpm", lo=0, hi=12000, category="Knock"),
             "u16[8] knock window rpm axis"),
    NewField("CFG_U_KNOCK_WIN_START", "u16", 8,
             Meta("CFG_U_KNOCK_WIN_START", "knockWinStart",
                  "Window start after TDC", L, G.TABLES, units="deg",
                  scale=0.1, digits=1, lo=0, hi=900, category="Knock",
                  note="Where the measurement window OPENS, crank degrees "
                       "after each cylinder's TDC (Bosch KFMAKR)."),
             "u16[8] window start, 0.1 deg ATDC"),
    NewField("CFG_U_KNOCK_WIN_LEN", "u16", 8,
             Meta("CFG_U_KNOCK_WIN_LEN", "knockWinLen", "Window length", L,
                  G.TABLES, units="deg", scale=0.1, digits=1, lo=50, hi=900,
                  category="Knock",
                  note="How long the CC195 integrates (Bosch KEMLN)."),
             "u16[8] window length, 0.1 deg"),
    NewField("CFG_U_KNOCK_KEF_RPM", "u16", 6,
             Meta("CFG_U_KNOCK_KEF_RPM", "knockKefRpm",
                  "Threshold factor rpm axis", L, G.TABLES, units="rpm",
                  lo=0, hi=12000, category="Knock"),
             "u16[6] threshold factor rpm axis, ascending"),
    NewField("CFG_U_KNOCK_KEF", "u8", 6,
             Meta("CFG_U_KNOCK_KEF", "knockKef", "Knock threshold factor", L,
                  G.TABLES, scale=0.0625, digits=2, lo=16, hi=255,
                  category="Knock",
                  note="A window is KNOCK when its integral exceeds the "
                       "cylinder's learned quiet reference times this (Bosch "
                       "KFKEF). Lower = more sensitive. 1.00 minimum."),
             "u8[6] threshold factor x16"),
    NewField("CFG_U_KNOCK_KEF_DYN", "u8", 1,
             Meta("CFG_U_KNOCK_KEF_DYN", "knockKefDyn",
                  "Threshold factor in transients", L, G.TABLES,
                  scale=0.0625, digits=2, lo=16, hi=32, category="Knock",
                  note="Multiplies the threshold while load or speed moves "
                       "fast (Bosch FKENDY / FKELDY)."),
             "u8 dynamics threshold multiplier x16"),
    NewField("CFG_U_KNOCK_TP", "u8", 1,
             Meta("CFG_U_KNOCK_TP", "knockTp", "Reference filter", L, G.TABLES,
                  units="ign", lo=1, hi=32, category="Knock",
                  note="The quiet reference follows each quiet window by 1/n "
                       "(Bosch KRFTP1)."),
             "u8 reference low pass, ignitions"),
    NewField("CFG_U_KNOCK_TP_DYN", "u8", 1,
             Meta("CFG_U_KNOCK_TP_DYN", "knockTpDyn",
                  "Reference filter in transients", L, G.TABLES, units="ign",
                  lo=1, hi=32, category="Knock"),
             "u8 reference low pass in dynamics"),
    NewField("CFG_U_KNOCK_LOAD_MIN", "u8", 1,
             Meta("CFG_U_KNOCK_LOAD_MIN", "knockLoadMin",
                  "Minimum load", L, G.TABLES, units="%", lo=0, hi=200,
                  category="Knock",
                  note="Relative air charge (rl) below which windows are "
                       "measured but not judged (Bosch LKRN)."),
             "u8 knock control minimum rl, %"),
    NewField("CFG_U_KNOCK_RPM_MIN", "u16", 1,
             Meta("CFG_U_KNOCK_RPM_MIN", "knockRpmMin", "Minimum rpm", L,
                  G.TABLES, units="rpm", lo=0, hi=12000, category="Knock",
                  note="Below this no window is taken (Bosch NKRF)."),
             "u16 knock control minimum rpm"),
    NewField("CFG_U_KNOCK_CLT_MIN", "u16", 1,
             Meta("CFG_U_KNOCK_CLT_MIN", "knockCltMin", "Minimum coolant", L,
                  G.TABLES, units="C", scale=0.1, translate=-1000.0, digits=0,
                  lo=9500, hi=12000, category="Knock",
                  note="Below this windows are measured but not judged "
                       "(Bosch TMKR)."),
             "u16 knock control minimum coolant, 10*C + 10000"),
    NewField("CFG_U_KNOCK_REF_INIT", "u16", 1,
             Meta("CFG_U_KNOCK_REF_INIT", "knockRefInit",
                  "Reference start value", L, G.TABLES, units="cnt",
                  lo=0, hi=1023, category="Knock",
                  note="The quiet reference each cylinder starts from, ADC "
                       "counts (Bosch REFINI)."),
             "u16 reference start, counts"),
    NewField("CFG_U_KNOCK_REAPPLY_MS", "u16", 1,
             Meta("CFG_U_KNOCK_REAPPLY_MS", "knockReapplyMs",
                  "Retard recovery time per 0.25 deg", L, G.TABLES,
                  units="ms", lo=1, hi=20000, category="Knock",
                  note="A cylinder quiet for this long gets 0.25 deg back "
                       "(rusEFI knockRetardReapplyRate)."),
             "u16 ms per 0.25 deg recovered"),
    NewField("CFG_U_KNOCK_DIAG_RPM", "u16", 1,
             Meta("CFG_U_KNOCK_DIAG_RPM", "knockDiagRpm",
                  "Sensor diagnosis above", L, G.TABLES, units="rpm",
                  lo=0, hi=12000, category="Knock"),
             "u16 sensor plausibility above this rpm"),
    NewField("CFG_U_KNOCK_REF_MIN", "u16", 1,
             Meta("CFG_U_KNOCK_REF_MIN", "knockRefMin",
                  "Plausible reference minimum", L, G.TABLES, units="cnt",
                  lo=0, hi=1023, category="Knock",
                  note="A reference below this (open sensor, broken line) "
                       "for the diagnosis count latches the SENSOR fault and "
                       "its cylinders take the safety retard."),
             "u16 plausible reference min, counts"),
    NewField("CFG_U_KNOCK_REF_MAX", "u16", 1,
             Meta("CFG_U_KNOCK_REF_MAX", "knockRefMax",
                  "Plausible reference maximum", L, G.TABLES, units="cnt",
                  lo=0, hi=1023, category="Knock"),
             "u16 plausible reference max, counts"),
    NewField("CFG_U_KNOCK_LEARN", "u8", 1,
             Meta("CFG_U_KNOCK_LEARN", "knockLearn", "Settling windows", L,
                  G.TABLES, units="ign", lo=0, hi=255, category="Knock",
                  note="Quiet windows per cylinder learned before knock can "
                       "be detected."),
             "u8 settling ignitions"),
    NewField("CFG_U_KNOCK_STOP_N", "u8", 1,
             Meta("CFG_U_KNOCK_STOP_N", "knockStopN", "At-stop count", L,
                  G.TABLES, lo=0, hi=255, category="Knock",
                  note="Knocks in a row with the retard already at its "
                       "maximum before the cylinder is flagged (Bosch KRA). "
                       "0 = off."),
             "u8 knocks at the ceiling -> at stop"),
    NewField("CFG_U_KNOCK_STEP_Q", "u8", 1,
             Meta("CFG_U_KNOCK_STEP_Q", "knockStepQ", "Retard per knock", L,
                  G.TABLES, units="deg", scale=0.25, digits=2, lo=1, hi=40,
                  category="Knock", note="Bosch KRFKN."),
             "u8 retard per knock, 0.25 deg"),
    NewField("CFG_U_KNOCK_MAX_Q", "u8", 1,
             Meta("CFG_U_KNOCK_MAX_Q", "knockMaxQ", "Maximum retard", L,
                  G.TABLES, units="deg", scale=0.25, digits=2, lo=1, hi=100,
                  category="Knock", note="Bosch KRMXN. 25.0 deg at most."),
             "u8 retard ceiling, 0.25 deg"),
    NewField("CFG_U_KNOCK_SAFE_Q", "u8", 1,
             Meta("CFG_U_KNOCK_SAFE_Q", "knockSafeQ", "Sensor-fault retard", L,
                  G.TABLES, units="deg", scale=0.25, digits=2, lo=0, hi=100,
                  category="Knock",
                  note="Applied to a failed sensor's cylinders (Bosch "
                       "KRDWSN). Active mode only."),
             "u8 sensor fault retard, 0.25 deg"),
    NewField("CFG_U_KNOCK_DIAG_N", "u8", 1,
             Meta("CFG_U_KNOCK_DIAG_N", "knockDiagN", "Diagnosis count", L,
                  G.TABLES, lo=0, hi=255, category="Knock",
                  note="Implausible windows in a row before a sensor fault "
                       "latches. 0 = no diagnosis."),
             "u8 implausible windows before a sensor fault"),
    # V97: CAM PHASE CONTROL (VVT) - hcvvt711.c + firmware/control/hcvvt.c, rusEFI
    # vvt.cpp. Cam b closes on the cam PATTERN core's measured position of
    # cam input b and drives pinCam<b>Sol (115 = POUT0, 120 = POUT1).
    # APPENDED. The board default and every preset: OFF.
    NewField("CFG_U_VVT_MODE", "u8", 2,
             Meta("CFG_U_VVT_MODE", "vvtMode", "VVT control", L, G.TABLES,
                  lo=0, hi=2, enum=ENUM_VVT_MODE, category="VVT",
                  note="Per cam. Closed loop needs camPhaseMode PATTERN on "
                       "that cam input (it measures the cam position). "
                       "On/off: the target table's sign switches the "
                       "solenoid (1.8T 20V style)."),
             "u8[2] VVT mode per cam, 0 off 1 switch 2 closed"),
    NewField("CFG_U_VVT_INVERT", "u8", 2,
             Meta("CFG_U_VVT_INVERT", "vvtInvert",
                  "Solenoid control direction", L, G.TABLES, lo=0, hi=1,
                  enum=ENUM_OFF_ON, category="VVT",
                  note="On: more duty moves the cam AWAY from advance "
                       "(rusEFI invertVvtControl)."),
             "u8[2] VVT direction invert per cam"),
    NewField("CFG_U_VVT_FREQ_HZ", "u16", 1,
             Meta("CFG_U_VVT_FREQ_HZ", "vvtFreqHz", "Solenoid PWM frequency",
                  L, G.TABLES, units="Hz", lo=20, hi=1000, category="VVT",
                  note="Both stages. The OEM ECU runs 250 Hz [BIN 0x8C0D78]."),
             "u16 VVT PWM frequency, Hz"),
    NewField("CFG_U_VVT_MIN_RPM", "u16", 1,
             Meta("CFG_U_VVT_MIN_RPM", "vvtMinRpm", "Do not control below RPM",
                  L, G.TABLES, units="rpm", lo=0, hi=12000, category="VVT"),
             "u16 VVT minimum rpm"),
    NewField("CFG_U_VVT_MIN_CLT", "u16", 1,
             Meta("CFG_U_VVT_MIN_CLT", "vvtMinClt", "Do not control below CLT",
                  L, G.TABLES, units="C", scale=0.1, translate=-1000.0,
                  digits=0, lo=9500, hi=12000, category="VVT"),
             "u16 VVT minimum coolant, 10*C + 10000"),
    NewField("CFG_U_VVT_DELAY_MS", "u16", 1,
             Meta("CFG_U_VVT_DELAY_MS", "vvtDelayMs", "Activation delay", L,
                  G.TABLES, units="s", scale=0.001, digits=1, lo=0, hi=60000,
                  category="VVT", note="Running this long first (oil "
                  "pressure builds)."),
             "u16 VVT activation delay, ms"),
    NewField("CFG_U_VVT_KP", "u16", 2,
             Meta("CFG_U_VVT_KP", "vvtKp", "P factor", L, G.TABLES,
                  scale=0.01, digits=2, lo=0, hi=10000, category="VVT",
                  note="Duty (0.1 %) per 0.1 deg of error, x100, per 20 ms."),
             "u16[2] VVT P per cam, x100"),
    NewField("CFG_U_VVT_KI", "u16", 2,
             Meta("CFG_U_VVT_KI", "vvtKi", "I factor", L, G.TABLES,
                  scale=0.01, digits=2, lo=0, hi=10000, category="VVT"),
             "u16[2] VVT I per cam, x100 per 20 ms step"),
    NewField("CFG_U_VVT_KD", "u16", 2,
             Meta("CFG_U_VVT_KD", "vvtKd", "D factor", L, G.TABLES,
                  scale=0.01, digits=2, lo=0, hi=10000, category="VVT",
                  note="On the measurement, not the error."),
             "u16[2] VVT D per cam, x100"),
    NewField("CFG_U_VVT_DUTY_MIN", "u16", 2,
             Meta("CFG_U_VVT_DUTY_MIN", "vvtDutyMin", "Min duty", L, G.TABLES,
                  units="%", scale=0.1, digits=1, lo=0, hi=1000,
                  category="VVT"),
             "u16[2] VVT closed-loop minimum duty, 0.1 %"),
    NewField("CFG_U_VVT_DUTY_MAX", "u16", 2,
             Meta("CFG_U_VVT_DUTY_MAX", "vvtDutyMax", "Max duty", L, G.TABLES,
                  units="%", scale=0.1, digits=1, lo=0, hi=1000,
                  category="VVT"),
             "u16[2] VVT closed-loop maximum duty, 0.1 %"),
    NewField("CFG_U_VVT_DUTY_ON", "u16", 2,
             Meta("CFG_U_VVT_DUTY_ON", "vvtDutyOn", "On/off: ON duty", L,
                  G.TABLES, units="%", scale=0.1, digits=1, lo=0, hi=1000,
                  category="VVT"),
             "u16[2] VVT switch-mode ON duty, 0.1 %"),
    NewField("CFG_U_VVT_ERR_MAX", "u16", 1,
             Meta("CFG_U_VVT_ERR_MAX", "vvtErrMax", "Fault: error above", L,
                  G.TABLES, units="deg", scale=0.1, digits=1, lo=0, hi=900,
                  category="VVT",
                  note="Closed loop off target by more than this for the "
                       "time below: stuck or slow phaser (P0011 / P0021), "
                       "duty 0 until the engine stops."),
             "u16 VVT tracking fault threshold, 0.1 deg"),
    NewField("CFG_U_VVT_ERR_MS", "u16", 1,
             Meta("CFG_U_VVT_ERR_MS", "vvtErrMs", "Fault: for longer than", L,
                  G.TABLES, units="s", scale=0.001, digits=1, lo=0, hi=60000,
                  category="VVT"),
             "u16 VVT tracking fault time, ms"),
    NewField("CFG_U_VVT_FB_MS", "u16", 1,
             Meta("CFG_U_VVT_FB_MS", "vvtFbMs", "Cam position max age", L,
                  G.TABLES, units="s", scale=0.001, digits=2, lo=0, hi=5000,
                  category="VVT",
                  note="A cam position older than this is not a measurement "
                       "(duty 0); twice this in closed loop is the NO "
                       "FEEDBACK fault."),
             "u16 VVT position freshness, ms"),
    NewField("CFG_U_VVT_RPM_AX", "u16", 8,
             Meta("CFG_U_VVT_RPM_AX", "vvtRpmAx", "VVT rpm axis", L,
                  G.TABLES, units="rpm", lo=0, hi=12000, category="VVT"),
             "u16[8] VVT target rpm axis"),
    NewField("CFG_U_VVT_LOAD_AX", "u16", 8,
             Meta("CFG_U_VVT_LOAD_AX", "vvtLoadAx", "VVT load axis", L,
                  G.TABLES, units="%", scale=0.1, digits=0, lo=0, hi=3000,
                  category="VVT", note="Relative air charge rl."),
             "u16[8] VVT target load axis, 0.1 % rl"),
    NewField("CFG_U_VVT_TARGET1", "s16", 64,
             Meta("CFG_U_VVT_TARGET1", "vvtTarget1", "Cam 1 target", L,
                  G.TABLES, units="deg", scale=0.1, digits=1, lo=-900,
                  hi=900, category="VVT",
                  note="Advance from the cam's zero position; on/off mode: "
                       "> 0 = solenoid ON."),
             "s16[64] cam 1 target, 0.1 deg advance, [rpm][load]"),
    NewField("CFG_U_VVT_TARGET2", "s16", 64,
             Meta("CFG_U_VVT_TARGET2", "vvtTarget2", "Cam 2 target", L,
                  G.TABLES, units="deg", scale=0.1, digits=1, lo=-900,
                  hi=900, category="VVT"),
             "s16[64] cam 2 target, 0.1 deg advance, [rpm][load]"),

    # ======================================================================
    # V98: THE ENGINE MODEL BLOCK (docs/ARCHITECTURE.md). APPENDED -
    # nothing above moves. Runtime: hcengctl711.c (far) unless noted. Every
    # field is 0 = off / neutral on a fresh page unless the config manager
    # seeds it (hc_config_manager.c), and every preset says what it sets.
    # ======================================================================
    NewField("CFG_U_FIRING_ORDER", "u8", 1,
             Meta("CFG_U_FIRING_ORDER", "firingOrder", "Firing order", Z,
                  G.ENGINE_SETUP, lo=0, hi=36, enum=ENUM_FIRING_ORDER,
                  safety_critical=True, category="Engine",
                  note="rusEFI firingOrder. The scheduler places cylinder n's "
                       "TDC at 720 x (its position in this order) / "
                       "cylinders. Custom uses the per-cylinder TDC angles "
                       "(odd-fire engines). The number of cylinders in the "
                       "order must equal the cylinder count."),
             "u8 firing order (rusEFI firing_order_e), 0 = custom TDC angles"),
    NewField("CFG_U_ALPHAN_IAT", "u8", 1,
             Meta("CFG_U_ALPHAN_IAT", "alphaNUseIat",
                  "Use intake air temperature", L,
                  G.ENGINE_SETUP, lo=0, hi=1, enum=ENUM_OFF_ON,
                  category="Fuel",
                  note="rusEFI alphaNUseIat. Off: the air is taken at 20 C. "
                       "On: at the measured intake air temperature (20 C if "
                       "the sensor fails)."),
             "u8 pure alpha-N uses IAT for density"),
    NewField("CFG_U_IGN_LOAD_MODE", "u8", 1,
             Meta("CFG_U_IGN_LOAD_MODE", "ignLoadMode",
                  "Ignition table load", L, G.TABLES, lo=0, hi=3,
                  enum=ENUM_LOAD_AXIS, category="Ignition",
                  note="rusEFI ignOverrideMode. 'Same as the fuel load' "
                       "follows the fuel strategy (MAP for speed density, "
                       "throttle for alpha-N). A failed sensor reads as "
                       "200 kPa / 100 % here (rusEFI: retard rather than "
                       "advance)."),
             "u8 ignition table load source"),
    NewField("CFG_U_LAM_LOAD_MODE", "u8", 1,
             Meta("CFG_U_LAM_LOAD_MODE", "lambdaLoadMode",
                  "Target lambda table load", L, G.TABLES, lo=0, hi=3,
                  enum=ENUM_LOAD_AXIS, category="Lambda",
                  note="rusEFI afrOverrideMode. A failed sensor reads as "
                       "200 kPa / 100 % (rich)."),
             "u8 target lambda table load source"),
    NewField("CFG_U_LAM_RPM_AX", "u16", 16,
             Meta("CFG_U_LAM_RPM_AX", "lambdaRpmAx", "Target lambda rpm axis",
                  L, G.TABLES, units="rpm", lo=0, hi=20000, category="Lambda"),
             "u16[16] target lambda rpm axis"),
    NewField("CFG_U_LAM_LOAD_AX", "u16", 16,
             Meta("CFG_U_LAM_LOAD_AX", "lambdaLoadAx", "Target lambda load axis",
                  L, G.TABLES, scale=0.1, digits=1, lo=0, hi=6500,
                  category="Lambda", note="kPa or %, per lambdaLoadMode."),
             "u16[16] target lambda load axis, 0.1 kPa or 0.1 %"),
    NewField("CFG_U_MAPEST_RPM_AX", "u16", 8,
             Meta("CFG_U_MAPEST_RPM_AX", "mapEstRpmAx", "Pressure estimate rpm axis",
                  L, G.TABLES, units="rpm", lo=0, hi=20000, category="Sensors"),
             "u16[8] MAP estimate rpm axis"),
    NewField("CFG_U_MAPEST_TPS_AX", "u16", 8,
             Meta("CFG_U_MAPEST_TPS_AX", "mapEstTpsAx",
                  "Pressure estimate throttle axis", L, G.TABLES, units="%",
                  scale=0.1, digits=1, lo=0, hi=1000, category="Sensors"),
             "u16[8] MAP estimate throttle axis, 0.1 %"),
    NewField("CFG_U_MAPEST", "u8", 64,
             Meta("CFG_U_MAPEST", "mapEstimate", "Pressure estimate", L, G.TABLES,
                  units="kPa", lo=0, hi=255, category="Sensors",
                  note="rusEFI mapEstimateTable: what the FUEL uses in place "
                       "of the pressure sensor while it has failed (speed "
                       "density and alpha-N x inlet pressure). The displayed "
                       "MAP stays 0 kPa. 0 = no air = no fuel. [throttle]"
                       "[rpm]."),
             "u8[64] MAP estimate, kPa, [tps][rpm]"),
    NewField("CFG_U_PRIME_MG", "u16", 8,
             Meta("CFG_U_PRIME_MG", "primeMgX10", "Priming pulse fuel", L,
                  G.TABLES, units="mg", scale=0.1, digits=1, lo=0, hi=20000,
                  category="Fuel",
                  note="rusEFI primeValues: fuel per injector, all injectors "
                       "together, once at key-on with the engine stopped "
                       "(coolant axis = the cranking axis). Skipped if the "
                       "coolant sensor has failed. 0 everywhere = no prime."),
             "u16[8] priming fuel per injector, 0.1 mg, vs crankPwAx"),
    NewField("CFG_U_PRIME_DELAY", "u8", 1,
             Meta("CFG_U_PRIME_DELAY", "primeDelay", "Priming delay", L,
                  G.TABLES, units="s", scale=0.1, digits=1, lo=0, hi=50,
                  category="Fuel",
                  note="Key-on to the priming pulse (rusEFI primingDelay); "
                       "lets the fuel pump build pressure first."),
             "u8 priming delay after key-on, 0.1 s"),
    NewField("CFG_U_DFCO_DELAY", "u8", 1,
             Meta("CFG_U_DFCO_DELAY", "dfcoDelay", "Fuel cut delay", L,
                  G.TABLES, units="s", scale=0.1, digits=1, lo=0, hi=100,
                  category="Fuel",
                  note="rusEFI dfcoDelay: the conditions must hold this long "
                       "before fuel is cut."),
             "u8 DFCO delay, 0.1 s"),
    NewField("CFG_U_DFCO_MIN_CLT", "u16", 1,
             Meta("CFG_U_DFCO_MIN_CLT", "dfcoMinClt", "Fuel cut: coolant above",
                  L, G.TABLES, units="C", scale=0.1, translate=-1000.0,
                  digits=0, lo=9500, hi=12000, category="Fuel",
                  note="rusEFI coastingFuelCutClt. A failed coolant sensor "
                       "inhibits the cut."),
             "u16 DFCO minimum coolant, 10*C + 10000"),
    NewField("CFG_U_DFCO_MAP_MAX", "u8", 1,
             Meta("CFG_U_DFCO_MAP_MAX", "dfcoMapMax", "Fuel cut: manifold pressure below", L,
                  G.TABLES, units="kPa", lo=0, hi=250, category="Fuel",
                  note="rusEFI coastingFuelCutMap. 0 = no MAP condition (the "
                       "only correct setting for a pressure sensor before "
                       "the throttle)."),
             "u8 DFCO manifold pressure maximum, kPa, 0 = off"),
    NewField("CFG_U_DFCO_RETARD", "u8", 1,
             Meta("CFG_U_DFCO_RETARD", "dfcoRetard", "Fuel cut timing retard",
                  L, G.TABLES, units="deg", lo=0, hi=30, category="Fuel",
                  note="rusEFI dfcoRetardDeg: spark retard while cut, ramped "
                       "out over the time below after fuel returns."),
             "u8 DFCO ignition retard, deg"),
    NewField("CFG_U_DFCO_RAMP", "u8", 1,
             Meta("CFG_U_DFCO_RAMP", "dfcoRamp", "Fuel cut retard ramp-out", L,
                  G.TABLES, units="s", scale=0.1, digits=1, lo=0, hi=50,
                  category="Fuel"),
             "u8 DFCO retard ramp-out, 0.1 s"),
    NewField("CFG_U_STFT_ENABLE", "u8", 1,
             Meta("CFG_U_STFT_ENABLE", "stftEnable", "Closed loop fuel correction",
                  L, G.TABLES, lo=0, hi=1, enum=ENUM_OFF_ON, category="Lambda",
                  note="rusEFI fuelClosedLoopCorrectionEnabled. Trims fuel "
                       "only from a wideband that is READY (heated, "
                       "calibrated, no fault)."),
             "u8 short term fuel trim enable"),
    NewField("CFG_U_STFT_DELAY", "u8", 1,
             Meta("CFG_U_STFT_DELAY", "stftStartDelay", "Startup delay", L,
                  G.TABLES, units="s", lo=0, hi=60, category="Lambda"),
             "u8 STFT delay after start, s"),
    NewField("CFG_U_STFT_DEADBAND", "u8", 1,
             Meta("CFG_U_STFT_DEADBAND", "stftDeadband", "Deadband", L,
                  G.TABLES, units="%", scale=0.1, digits=1, lo=0, hi=100,
                  category="Lambda"),
             "u8 STFT lambda deadband, 0.1 %"),
    NewField("CFG_U_STFT_MIN_CLT", "u16", 1,
             Meta("CFG_U_STFT_MIN_CLT", "stftMinClt", "Minimum coolant", L,
                  G.TABLES, units="C", scale=0.1, translate=-1000.0, digits=0,
                  lo=9500, hi=12000, category="Lambda"),
             "u16 STFT minimum coolant, 10*C + 10000"),
    NewField("CFG_U_STFT_IDLE_RPM", "u16", 1,
             Meta("CFG_U_STFT_IDLE_RPM", "stftIdleRpm", "Idle region below", L,
                  G.TABLES, units="rpm", lo=0, hi=5000, category="Lambda"),
             "u16 STFT idle region rpm"),
    NewField("CFG_U_STFT_OVR_LOAD", "u8", 1,
             Meta("CFG_U_STFT_OVR_LOAD", "stftOverrunLoad",
                  "Overrun region below load", L, G.TABLES, lo=0, hi=255,
                  category="Lambda", note="In the fuel load's units "
                  "(kPa or %)."),
             "u8 STFT overrun region load"),
    NewField("CFG_U_STFT_PWR_LOAD", "u8", 1,
             Meta("CFG_U_STFT_PWR_LOAD", "stftPowerLoad",
                  "Power region above load", L, G.TABLES, lo=0, hi=255,
                  category="Lambda"),
             "u8 STFT power region load"),
    NewField("CFG_U_STFT_LAM_MIN", "u8", 1,
             Meta("CFG_U_STFT_LAM_MIN", "stftLambdaMin", "Learn above lambda",
                  L, G.TABLES, scale=0.01, digits=2, lo=50, hi=150,
                  category="Lambda"),
             "u8 STFT minimum lambda, x100"),
    NewField("CFG_U_STFT_LAM_MAX", "u8", 1,
             Meta("CFG_U_STFT_LAM_MAX", "stftLambdaMax", "Learn below lambda",
                  L, G.TABLES, scale=0.01, digits=2, lo=50, hi=200,
                  category="Lambda"),
             "u8 STFT maximum lambda, x100"),
    NewField("CFG_U_STFT_AFTER_DFCO", "u8", 1,
             Meta("CFG_U_STFT_AFTER_DFCO", "stftAfterDfco",
                  "Hold after fuel cut", L, G.TABLES, units="s", scale=0.1,
                  digits=1, lo=0, hi=100, category="Lambda"),
             "u8 STFT hold after DFCO, 0.1 s"),
    NewField("CFG_U_STFT_AFTER_AE", "u8", 1,
             Meta("CFG_U_STFT_AFTER_AE", "stftAfterAe",
                  "Hold after acceleration enrichment", L, G.TABLES, units="s",
                  scale=0.1, digits=1, lo=0, hi=100, category="Lambda"),
             "u8 STFT hold after AE, 0.1 s"),
    NewField("CFG_U_STFT_ADD", "u8", 4,
             Meta("CFG_U_STFT_ADD", "stftMaxAdd", "Max add", L, G.TABLES,
                  units="%", lo=0, hi=25, category="Lambda",
                  note="Idle / overrun / power / cruise."),
             "u8[4] STFT max add per region, %"),
    NewField("CFG_U_STFT_REMOVE", "u8", 4,
             Meta("CFG_U_STFT_REMOVE", "stftMaxRemove", "Max remove", L,
                  G.TABLES, units="%", lo=0, hi=25, category="Lambda"),
             "u8[4] STFT max remove per region, %"),
    NewField("CFG_U_STFT_TAU", "u8", 4,
             Meta("CFG_U_STFT_TAU", "stftTimeConst", "Time constant", L,
                  G.TABLES, units="s", scale=0.1, digits=1, lo=1, hi=250,
                  category="Lambda"),
             "u8[4] STFT integrator time constant per region, 0.1 s"),
    NewField("CFG_U_REVLIM_HYST", "u8", 1,
             Meta("CFG_U_REVLIM_HYST", "revLimitHyst", "Rev limit hysteresis",
                  L, G.ENGINE_SETUP, units="rpm", scale=10, lo=1, hi=100,
                  category="Safety",
                  note="rusEFI rpmHardLimitHyst. Also the soft-limit window "
                       "below the limit."),
             "u8 rev limit hysteresis, 10 rpm"),
    NewField("CFG_U_REVLIM_SOFT_RETARD", "u8", 1,
             Meta("CFG_U_REVLIM_SOFT_RETARD", "revLimitSoftRetard",
                  "Soft limit timing retard", L, G.ENGINE_SETUP, units="deg",
                  lo=0, hi=30, category="Safety",
                  note="rusEFI rpmSoftLimitTimingRetard: ramps in across the "
                       "hysteresis window up to the limit."),
             "u8 soft rev limit retard, deg"),
    NewField("CFG_U_REVLIM_SOFT_FUEL", "u8", 1,
             Meta("CFG_U_REVLIM_SOFT_FUEL", "revLimitSoftFuel",
                  "Soft limit fuel added", L, G.ENGINE_SETUP, units="%",
                  lo=0, hi=50, category="Safety"),
             "u8 soft rev limit fuel added, %"),
    NewField("CFG_U_MS_SWITCH_INV", "u8", 1,
             Meta("CFG_U_MS_SWITCH_INV", "msSwitchInvert",
                  "Motorsport switch polarity", L, G.MOTORSPORT, lo=0, hi=15,
                  category="Motorsport",
                  note="Bit per input (0 launch, 1 flat shift, 2 anti-lag, 3 "
                       "pit limiter): 0 = active when grounded (the inputs "
                       "have a pull-up), 1 = active when high."),
             "u8 motorsport switch inversion bits"),
    NewField("CFG_U_LAUNCH_TPS", "u8", 1,
             Meta("CFG_U_LAUNCH_TPS", "launchTps", "Launch: pedal above", L,
                  G.MOTORSPORT, units="%", lo=0, hi=100, category="Motorsport"),
             "u8 launch throttle/pedal threshold, %"),
    NewField("CFG_U_LAUNCH_WINDOW", "u8", 1,
             Meta("CFG_U_LAUNCH_WINDOW", "launchWindow", "Launch: window",
                  L, G.MOTORSPORT, units="rpm", scale=10, lo=0, hi=255,
                  category="Motorsport",
                  note="rusEFI launchRpmWindow: the pre-launch band below "
                       "the launch rpm where the cut ramps in."),
             "u8 launch rpm window, 10 rpm"),
    NewField("CFG_U_LAUNCH_CUT_START", "u8", 1,
             Meta("CFG_U_LAUNCH_CUT_START", "launchCutStart",
                  "Launch: initial spark cut", L, G.MOTORSPORT, units="%",
                  lo=0, hi=100, category="Motorsport"),
             "u8 launch initial ignition cut, %"),
    NewField("CFG_U_LAUNCH_CUT_END", "u8", 1,
             Meta("CFG_U_LAUNCH_CUT_END", "launchCutEnd",
                  "Launch: spark cut before launch rpm", L, G.MOTORSPORT,
                  units="%", lo=0, hi=100, category="Motorsport"),
             "u8 launch final ignition cut, %"),
    NewField("CFG_U_LAUNCH_FUEL", "u8", 1,
             Meta("CFG_U_LAUNCH_FUEL", "launchFuelAdd", "Launch: fuel added",
                  L, G.MOTORSPORT, units="%", lo=0, hi=50,
                  category="Motorsport"),
             "u8 launch fuel adder, %"),
    NewField("CFG_U_FLATSHIFT_TPS", "u8", 1,
             Meta("CFG_U_FLATSHIFT_TPS", "flatShiftTps", "Flat shift: pedal above",
                  L, G.MOTORSPORT, units="%", lo=0, hi=100,
                  category="Motorsport"),
             "u8 flat shift pedal threshold, %"),
    NewField("CFG_U_FLATSHIFT_CUT_PCT", "u8", 1,
             Meta("CFG_U_FLATSHIFT_CUT_PCT", "flatShiftCutPct",
                  "Flat shift: spark cut", L, G.MOTORSPORT, units="%", lo=0,
                  hi=100, category="Motorsport"),
             "u8 flat shift ignition cut, %"),
    NewField("CFG_U_ALS_TPS_MAX", "u8", 1,
             Meta("CFG_U_ALS_TPS_MAX", "alsTpsMax", "Anti-lag: pedal below",
                  L, G.MOTORSPORT, units="%", lo=0, hi=100,
                  category="Motorsport"),
             "u8 ALS maximum pedal, %"),
    NewField("CFG_U_FLATSHIFT_TIMING", "s16", 1,
             Meta("CFG_U_FLATSHIFT_TIMING", "flatShiftTimingX10",
                  "Flat shift: ignition timing", L, G.MOTORSPORT, units="deg",
                  scale=0.1, digits=1, lo=-300, hi=300, category="Motorsport",
                  note="Absolute timing during the cut (rusEFI torque "
                       "reduction ignition retard)."),
             "s16 flat shift timing, 0.1 deg"),
    NewField("CFG_U_ALS_RPM_MIN", "u16", 1,
             Meta("CFG_U_ALS_RPM_MIN", "alsRpmMin", "Anti-lag: above rpm", L,
                  G.MOTORSPORT, units="rpm", lo=0, hi=12000,
                  category="Motorsport"),
             "u16 ALS minimum rpm"),
    NewField("CFG_U_ALS_RPM_MAX", "u16", 1,
             Meta("CFG_U_ALS_RPM_MAX", "alsRpmMax", "Anti-lag: below rpm", L,
                  G.MOTORSPORT, units="rpm", lo=0, hi=12000,
                  category="Motorsport"),
             "u16 ALS maximum rpm"),
    NewField("CFG_U_ALS_CLT_MIN", "u16", 1,
             Meta("CFG_U_ALS_CLT_MIN", "alsCltMin", "Anti-lag: coolant above",
                  L, G.MOTORSPORT, units="C", scale=0.1, translate=-1000.0,
                  digits=0, lo=9500, hi=12000, category="Motorsport"),
             "u16 ALS minimum coolant"),
    NewField("CFG_U_ALS_CLT_MAX", "u16", 1,
             Meta("CFG_U_ALS_CLT_MAX", "alsCltMax", "Anti-lag: coolant below",
                  L, G.MOTORSPORT, units="C", scale=0.1, translate=-1000.0,
                  digits=0, lo=9500, hi=12000, category="Motorsport"),
             "u16 ALS maximum coolant"),
    NewField("CFG_U_ALS_CUT_PCT", "u8", 1,
             Meta("CFG_U_ALS_CUT_PCT", "alsCutPct", "Anti-lag: spark cut", L,
                  G.MOTORSPORT, units="%", lo=0, hi=100,
                  category="Motorsport"),
             "u8 ALS ignition cut, %"),
    NewField("CFG_U_ALS_THROTTLE", "u8", 1,
             Meta("CFG_U_ALS_THROTTLE", "alsThrottle", "Anti-lag: throttle open",
                  L, G.MOTORSPORT, units="%", lo=0, hi=50,
                  category="Motorsport",
                  note="Added to the electronic throttle's idle floor while "
                       "anti-lag is active (rusEFI ALSEtbAdd)."),
             "u8 ALS throttle add, %"),
    NewField("CFG_U_ALS_MAX_S", "u8", 1,
             Meta("CFG_U_ALS_MAX_S", "alsMaxTime", "Anti-lag: max duration", L,
                  G.MOTORSPORT, units="s", lo=0, hi=250, category="Motorsport",
                  note="Anti-lag ends after this long in one activation "
                       "(rusEFI ALSMaxDuration). 0 = no limit."),
             "u8 ALS maximum duration, s"),
    NewField("CFG_U_ROTIDLE_CUT", "u8", 1,
             Meta("CFG_U_ROTIDLE_CUT", "rotIdleCut", "Rotational idle: spark cut",
                  L, G.MOTORSPORT, units="%", lo=0, hi=90,
                  category="Motorsport"),
             "u8 rotational idle cut, %"),
    NewField("CFG_U_ROTIDLE_TPS", "u8", 1,
             Meta("CFG_U_ROTIDLE_TPS", "rotIdleTps", "Rotational idle: pedal below",
                  L, G.MOTORSPORT, units="%", lo=0, hi=100,
                  category="Motorsport"),
             "u8 rotational idle maximum pedal, %"),
    NewField("CFG_U_INJ_PHASE_MODE", "u8", 1,
             Meta("CFG_U_INJ_PHASE_MODE", "injPhaseMode", "Injection timing",
                  L, G.TABLES, lo=0, hi=1, enum=ENUM_INJ_PHASE,
                  category="Fuel",
                  note="Single angle = injStartDegX10. Table = rusEFI "
                       "injectionPhase over rpm x fuel load."),
             "u8 injection timing source"),
    NewField("CFG_U_ROTIDLE_RPM", "u16", 1,
             Meta("CFG_U_ROTIDLE_RPM", "rotIdleRpm", "Rotational idle: below rpm",
                  L, G.MOTORSPORT, units="rpm", lo=0, hi=5000,
                  category="Motorsport"),
             "u16 rotational idle maximum rpm"),
    NewField("CFG_U_IDLE_ETB_RANGE", "u8", 1,
             Meta("CFG_U_IDLE_ETB_RANGE", "etbIdleRange",
                  "Idle throttle blend range", L, G.TABLES, units="%", lo=0,
                  hi=100, category="Idle",
                  note="rusEFI etbIdleThrottleRange semantics: the pedal "
                       "range over which the idle position blends into the "
                       "pedal map. 0 = the idle position is a floor."),
             "u8 idle-to-pedal blend range, %"),
    NewField("CFG_U_V98_PAD", "u8", 1,
             Meta("CFG_U_V98_PAD", "v98Pad", "Alignment pad", L, G.GENERAL,
                  lo=0, hi=255, category="Controller"),
             "u8 keeps the next u16 even-aligned"),
    NewField("CFG_U_INJ_PHASE_RPM_AX", "u16", 8,
             Meta("CFG_U_INJ_PHASE_RPM_AX", "injPhaseRpmAx",
                  "Injection timing rpm axis", L, G.TABLES, units="rpm", lo=0,
                  hi=20000, category="Fuel"),
             "u16[8] injection phase rpm axis"),
    NewField("CFG_U_INJ_PHASE_LOAD_AX", "u16", 8,
             Meta("CFG_U_INJ_PHASE_LOAD_AX", "injPhaseLoadAx",
                  "Injection timing load axis", L, G.TABLES, scale=0.1,
                  digits=1, lo=0, hi=6500, category="Fuel"),
             "u16[8] injection phase load axis (fuel load units)"),
    NewField("CFG_U_INJ_PHASE", "u16", 64,
             Meta("CFG_U_INJ_PHASE", "injPhaseTable", "Injection timing",
                  L, G.TABLES, units="deg", scale=0.1, digits=0, lo=0,
                  hi=7199, category="Fuel",
                  note="Degrees before TDC of the cylinder's power stroke "
                       "that the injection starts (or ends, per "
                       "injTimingMode). [load][rpm]."),
             "u16[64] injection phase, 0.1 deg, [load][rpm]"),
]


# ==========================================================================
# 3. LAYOUT RESOLUTION AND CROSS-CHECK
# ==========================================================================
for _slot, _ts, _label, _enum, _hi in [
    ("FUEL_MODEL","fuelModel","Fuel model",ENUM_FUEL_MODEL,3),
    ("PRESSURE_ROLE","pressureRole","Pressure sensor location",ENUM_PRESSURE_ROLE,2),
    ("DENSITY_POLICY","densityPolicy","Air density pressure",ENUM_DENSITY_POLICY,2),
    ("BARO_SOURCE","ambientSource","Ambient pressure source",ENUM_BARO_SOURCE,2),
    ("AMBIENT_CORR","ambientCorrection","Correct for ambient pressure",None,1),
    ("IAT_POLICY","fuelUseIat","Use intake air temperature",None,1),
    ("LEAN_ENABLE","leanGuardEnable","Lean protection",None,1),
    ("LAMBDA_QUALIFIED","lambdaPhysicalQualified","Wideband commissioned for protection",None,1),
    ("PRESSURE_GUARD","pressureGuardEnable","Pressure-loss cut, other fuel algorithms",None,1),
    ("V102_PAD","v102Pad","Alignment pad",None,255),
]:
    UNIVERSAL.append(NewField("CFG_U_"+_slot,"u8",1,Meta("CFG_U_"+_slot,_ts,_label,Z,G.ENGINE_SETUP,lo=0,hi=_hi,enum=_enum,category="Load and protection",safety_critical=True),"V102 independent load/protection policy"))
for _slot, _ts, _label, _units, _lo, _hi, _scale in [
    ("PRESSURE_REF","densityReference","Reference pressure","kPa",500,1200,0.1),
    ("BLEND_START","chargeBlendStart","Boost blend starts at (above ambient)","kPa",0,3000,0.1),
    ("BLEND_FULL","chargeBlendFull","Boost blend complete at (above ambient)","kPa",1,4000,0.1),
    ("BARO_MAX_AGE","ambientMaxAge","Engine-stopped reading valid for","s",1,65535,1),
    ("PRESSURE_TIMEOUT","pressureMaxAge","Pressure reading maximum age","ms",10,1000,1),
    ("GUARD_RPM","pressureGuardRpm","Pressure-loss cut above","rpm",0,20000,1),
    ("GUARD_TPS","pressureGuardTps","Pressure-loss cut above TPS","%",0,1000,0.1),
    ("LEAN_RPM","leanGuardRpm","Lean protection above","rpm",0,20000,1),
    ("LEAN_TPS","leanGuardTps","Lean protection above TPS","%",0,1000,0.1),
    ("LEAN_CHARGE","leanGuardCharge","Lean protection above cylinder filling","%",0,5000,0.1),
    ("LEAN_DEVIATION","leanGuardDeviation","Lean margin over target","lambda",1,1000,0.001),
    ("LEAN_PERSIST","leanGuardPersist","Lean for longer than","ms",1,10000,1),
    ("LEAN_RECOVERY","leanGuardRecovery","Recovery: at target, off load, for","ms",1,30000,1),
]:
    UNIVERSAL.append(NewField("CFG_U_"+_slot,"u16",1,Meta("CFG_U_"+_slot,_ts,_label,Z,G.ENGINE_SETUP,units=_units,lo=_lo,hi=_hi,scale=_scale,digits=1 if _scale==0.1 else 3 if _scale==0.001 else 0,category="Load and protection",safety_critical=True),"V102 explicit units; no second pressure multiplier"))

# APPENDED LAST ON PURPOSE. universal_layout() assigns offsets in list
# order, so a field added anywhere else shifts every field after it; this
# way the only page change is two new bytes at the end and an existing
# calibration migrates by appending a default. The layout id still moves -
# it must, a record from the old layout is a different page - but nothing
# else has to be re-measured.
    # THE BRIDGE SWITCHING FREQUENCY IS A THROTTLE-BODY PROPERTY, not a fact
    # about this ECU: HaniCore has to drive bodies the Porsche never saw. 2 kHz
    # is the OEM ME7.1.1 value (its own port init programs PP2 = 19999 at
    # f_CPU, EXACT TARGET BINARY @0xC0D96) and stays the default; the range is
    # the CJ220's own supply-derated rating (hc_validation.c check_dbw).
UNIVERSAL.append(NewField("CFG_U_DBW_PWM_HZ", "u16", 1,
             Meta("CFG_U_DBW_PWM_HZ", "dbwPwmHz",
                  "Throttle bridge PWM frequency", Z, G.DBW_SETUP,
                  units="Hz", scale=1, digits=0, lo=1000, hi=10000,
                  category="DBW",
                  note="How fast the H-bridge chops the throttle motor. 2000 Hz "
                       "is the OEM value for this ECU and the right starting "
                       "point for an unknown body. The CJ220 is rated 20 kHz "
                       "only above 8 V and 5 kHz at 6-7 V, so above 5000 Hz the "
                       "plate loses some authority while cranking and the "
                       "validator says so. Changing it takes effect with the "
                       "engine stopped; re-run ETB Characterization afterwards, "
                       "because the bias curve is measured at one frequency."),
             "u16 throttle bridge PWM frequency, Hz"))
    # COULOMB FRICTION COMPENSATION - a throttle-body property. The break-away
    # measurement (ETB Characterization) found a +-17 % friction band around
    # a smooth spring line on the VAG body; a feed-forward at the band centre
    # alone left every move to build half a band through P/I (slower opening,
    # holds stranded off target). This signed term, linear inside +-1.5 % of
    # error and zero inside the deadband, removes that:
UNIVERSAL.append(NewField("CFG_U_DBW_FRICTION_X10", "u16", 1,
             Meta("CFG_U_DBW_FRICTION_X10", "dbwFrictionX10",
                  "Throttle friction compensation", Z, G.DBW_SETUP,
                  units="%", scale=0.1, digits=1, lo=0, hi=300,
                  category="DBW",
                  note="Extra motor command in the direction the plate has to "
                       "move, to overcome the throttle's static friction. It "
                       "ramps in over the first 1.5 % of position error and is "
                       "zero inside the deadband, so a held plate is not "
                       "dithered. 0 = off. Start near a quarter of the "
                       "friction band width ETB Characterization measures "
                       "(the VAG body: band 31-40 %, 8.0 % measured best; 12 % "
                       "began to overshoot). Re-run the characterization after "
                       "changing it."),
             "u16 Coulomb friction compensation, 0.1 % duty"))

_SIZE = {"u8": 1, "u16": 2, "s16": 2}


@dataclass
class ResolvedField:
    slot: str
    offset: int
    ctype: str
    count: int
    meta: Meta
    from_firmware: bool

    @property
    def size(self) -> int:
        return _SIZE[self.ctype] * self.count

    @property
    def end(self) -> int:
        return self.offset + self.size


def universal_layout(base: int) -> list[NewField]:
    """Assign offsets to the universal block. u16/s16 are even-aligned, and a
    pad that has to exist is a declared field, never an unowned byte."""
    cursor = base
    for f in UNIVERSAL:
        if _SIZE[f.ctype] == 2 and cursor % 2:
            raise SystemExit(
                "universal block: %s would land on an odd offset (%d). Add a "
                "declared pad field before it - an unowned byte is a hole the "
                ".ini cannot account for." % (f.slot, cursor))
        f.offset = cursor
        cursor += _SIZE[f.ctype] * f.count
    return UNIVERSAL


def universal_size(base: int) -> int:
    universal_layout(base)
    return (UNIVERSAL[-1].offset + _SIZE[UNIVERSAL[-1].ctype] * UNIVERSAL[-1].count
            - base)


def resolve() -> tuple[list[ResolvedField], dict[str, int], list[str]]:
    """Merge hcconfig.h's layout with this file's metadata.

    Returns (fields, hcconfig constants, problems). A non-empty problems list
    is a build failure: it means the firmware and the model disagree."""
    slots, consts = hcconfig_layout.parse()
    by_name = {s.name: s for s in slots}
    meta_by_slot = {m.slot: m for m in LEGACY}
    problems: list[str] = []
    out: list[ResolvedField] = []

    base = by_name.get("CFG_UNIVERSAL_BASE")
    universal_slots = {f.slot for f in UNIVERSAL}

    for s in slots:
        if s.name == "CFG_UNIVERSAL_BASE":
            continue
        m = meta_by_slot.pop(s.name, None)
        if m is None:
            problems.append(
                "hcconfig.h defines %s at %d but the model has no metadata for "
                "it - a page byte TunerStudio cannot see and validation cannot "
                "check" % (s.name, s.offset))
            continue
        out.append(ResolvedField(s.name, s.offset, s.ctype, s.count, m, True))

    for name in sorted(meta_by_slot):
        if name in universal_slots:
            continue
        problems.append(
            "the model has metadata for %s but hcconfig.h defines no such slot"
            % name)

    if base is None:
        problems.append(
            "hcconfig.h has no CFG_UNIVERSAL_BASE - the universal block has "
            "nowhere to live. Add it (see generate_config.py --emit-header).")
    else:
        need = universal_size(base.offset)
        if need > base.size:
            problems.append(
                "the universal block needs %d bytes but CFG_UNIVERSAL_BASE "
                "reserves %d" % (need, base.size))
        for f in universal_layout(base.offset):
            if f.meta is None:
                problems.append("universal field %s has no metadata" % f.slot)
                continue
            out.append(ResolvedField(f.slot, f.offset, f.ctype, f.count,
                                     f.meta, False))

    out.sort(key=lambda f: f.offset)

    # Overlap and alignment across the MERGED model, not just the header.
    owner: dict[int, str] = {}
    for f in out:
        if _SIZE[f.ctype] == 2 and f.offset % 2:
            problems.append("MISALIGNED %s at %d" % (f.slot, f.offset))
        if f.end > consts["HC_CFG_SIZE"]:
            problems.append("PAST END %s ends at %d" % (f.slot, f.end))
        for b in range(f.offset, min(f.end, consts["HC_CFG_SIZE"])):
            if b in owner:
                problems.append("OVERLAP byte %d: %s and %s"
                                % (b, owner[b], f.slot))
            else:
                owner[b] = f.slot

    ts_seen: dict[str, str] = {}
    for f in out:
        if f.meta.ts in ts_seen:
            problems.append("DUPLICATE TunerStudio name %s: %s and %s"
                            % (f.meta.ts, ts_seen[f.meta.ts], f.slot))
        ts_seen[f.meta.ts] = f.slot

    return out, consts, problems


def main() -> int:
    fields, consts, problems = resolve()
    print("merged model: %d fields, page %d bytes"
          % (len(fields), consts["HC_CFG_SIZE"]))
    covered = sum(f.size for f in fields)
    print("bytes described: %d / %d" % (covered, consts["HC_CFG_SIZE"]))
    for p in problems:
        print("PROBLEM: " + p)
    if "--list" in sys.argv:
        for f in fields:
            print("  %-26s %5d %-4s x%-4d %-22s %-14s %s"
                  % (f.slot, f.offset, f.ctype, f.count, f.meta.ts,
                     f.meta.apply.value, "SAFETY" if f.meta.safety_critical else ""))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
