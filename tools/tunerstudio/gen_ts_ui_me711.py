#!/usr/bin/env python3
r"""
gen_ts_ui_me711.py - the TunerStudio SETTINGS interface, generated from the
configuration model.

    imported by tools/tunerstudio/gen_ts_ini_me711.py

WHAT THIS REPLACED. The .ini exposed FIVE of the page's 207 configured fields:
cfgVersion, cylinders, outputsArmedCfg, mainRelayModeCfg, mainRelayGraceMs.
Everything else - the VE table, the spark map, the injector flow, every trigger
parameter, every pin route, both lambda channels, all of DBW - existed in the
firmware, was validated by hc_validation.c, was written down in the model with
units and limits, and COULD NOT BE REACHED FROM TUNERSTUDIO. That is a
diagnostics tool, not a standalone ECU interface.

NOT ONE OFFSET IS TYPED HERE. Everything comes from
tools/config_source/hanicore_config_def.py's resolve(), which merges
hcconfig.h's own layout with the model's metadata and REFUSES to resolve if the
two disagree. So the direction of authority is unchanged:

    hcconfig.h (offsets, types, counts)
        -> hcconfig_layout.py
        -> hanicore_config_def.py (units, scale, limits, enums, category)
        -> this file (which dialog it appears on, and what it is called)

The one thing this file DOES author is the shape of the interface: which
category owns a field, what the table and curve editors are, and the menu.
Those are presentation choices and they are checked, not assumed - every name
used below must resolve to a real model field, or `layout()` raises.

HONESTY RULES, and they are enforced by the checks at the bottom:

  * NO DEAD BUTTONS. A commandButton may only name a command that exists in
    [ControllerCommands], and tests/unit/test_ts_commands.py requires every one of
    those to exist in hcts_target_cmd(). tests/tunerstudio/ts_ini_ui_contract.py checks the
    first half; that gate exists because a dialog full of buttons that sent
    nothing reached real hardware on 2026-09-02.
  * NO FAKE WIZARDS. Where a subsystem is not implemented in the firmware yet,
    the dialog says so in its own text rather than looking finished.
  * A LIVE VALUE IS A GAUGE, NEVER A `field`. `field = "x", name` binds a page
    CONSTANT; an output channel there makes TunerStudio report
    "invalid Constant" at load time and silently break the whole dialog.
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/config_source"))

import hanicore_config_def as MODEL          # noqa: E402
import generate_config as GEN                # noqa: E402

TS_TYPE = GEN.TS_TYPE


# ==========================================================================
# 1. The page: every field the model knows about.
# ==========================================================================
# ARRAYS A DIALOG HAS TO SHOW, ELEMENT BY ELEMENT.
#
# TunerStudio will not take `field = "label", someArray` - it asks for
# `array1D` instead. But `array1D` appears in NO .ini in this repository that
# is known to load, so emitting it would be guessing at a shape, which is
# exactly how the [TableEditor] failure of 2026-09-03 happened.
#
# rusEFI does not use it either. It declares each element as its own scalar -
# `injectionPins1` .. `injectionPins8` - and shows them with ordinary `field`
# lines guarded on the cylinder count. That shape is in the corpus 8000 times,
# so that is the shape used here: the array declaration stays for anything that
# wants the whole block, and a scalar alias per element is added beside it for
# the dialog to name.
ELEMENT_FIELDS = {
    "tdcCylDegX10": ("Cylinder %d TDC", "cylinders"),
    "cylBank": ("Cylinder %d bank", "cylinders"),
    "injChannel": ("Cylinder %d injector channel", "cylinders"),
    "injPin": ("Cylinder %d injector", "cylinders"),
    "ignChannel": ("Cylinder %d coil channel", "cylinders"),
    "ignPin": ("Cylinder %d coil", "cylinders"),
    "tdcCylExtDegX10": ("Cylinder %d TDC", None),
    "pinGenericPwm": ("Generic PWM %d pin", None),
    "pinGenericOut": ("Generic output %d pin", None),
    "pinGenericAin": ("Generic analog %d pin", None),
    # V97 knock: one gain per sensor, one sensor per cylinder (rusEFI
    # knockBankCyl1..12)
    "knockGain": ("Sensor %d gain", None),
    "knockSensor": ("Cylinder %d sensor", "cylinders"),
    # 2026-10-14: per-cylinder ignition trim (rusEFI ignition trims)
    "ignTrim": ("Cylinder %d", "cylinders"),
    # V97 VVT: per cam (rusEFI vvtMode1/2, auxPid1/2)
    "vvtMode": ("Cam %d control", None),
    "vvtInvert": ("Cam %d direction", None),
    "vvtKp": ("Cam %d P", None),
    "vvtKi": ("Cam %d I", None),
    "vvtKd": ("Cam %d D", None),
    "vvtDutyMin": ("Cam %d min duty", None),
    "vvtDutyMax": ("Cam %d max duty", None),
    "vvtDutyOn": ("Cam %d on/off duty", None),
    # V98: closed-loop fuel, one value per rusEFI region
    "stftMaxAdd": (["Idle: max add", "Overrun: max add", "Power: max add",
                    "Cruise: max add"], None),
    "stftMaxRemove": (["Idle: max remove", "Overrun: max remove",
                       "Power: max remove", "Cruise: max remove"], None),
    "stftTimeConst": (["Idle: time constant", "Overrun: time constant",
                       "Power: time constant", "Cruise: time constant"], None),
    # 2026-10-11: the temperature curves per point, so the 'Common sensors'
    # pickers (settingSelector writes scalars) can fill them
    "cltSensAx": ("Coolant curve point %d counts", None),
    "cltSensVal": ("Coolant curve point %d temperature", None),
    "iatSensAx": ("Air curve point %d counts", None),
    "iatSensVal": ("Air curve point %d temperature", None),
}

# V98: SEVERAL TUNERSTUDIO FIELDS OVER ONE PAGE WORD - rusEFI's own idiom
# (`bits, U32, off, [n:n]` per flag). The page keeps one u16/u8 with its
# documented bits; each view is a switch a tuner reads by name.
#   alias: (page field, bit, label, labels)
_POL = ["Active low (closed to ground = on)", "Active high (open = on)"]
BIT_VIEWS = {
    "launchEnable": ("motorsportEnable", 0, "Launch control", ["Off", "On"]),
    "flatShiftEnable": ("motorsportEnable", 1, "Flat shift", ["Off", "On"]),
    "antiLagEnable": ("motorsportEnable", 2, "Anti-lag", ["Off", "On"]),
    "pitLimiterEnable": ("motorsportEnable", 3, "Pit limiter", ["Off", "On"]),
    "rotIdleEnable": ("motorsportEnable", 10, "Rotational idle",
                      ["Off", "On"]),
    # polarity: the inputs have a pull-up, so a switch to ground is the
    # normal wiring (Active low); Active high = a normally-closed switch
    # that OPENS to activate
    "launchSwitchHigh": ("msSwitchInvert", 0, "Launch input polarity", _POL),
    "flatShiftSwitchHigh": ("msSwitchInvert", 1, "Clutch input polarity",
                            _POL),
    "antiLagSwitchHigh": ("msSwitchInvert", 2, "ALS input polarity", _POL),
    "pitSwitchHigh": ("msSwitchInvert", 3, "Pit limiter input polarity",
                      _POL),
}


def bit_view_lines(fields) -> list[str]:
    by = {f.meta.ts: f for f in fields}
    out = []
    for alias, (ts, bit, _label, labels) in BIT_VIEWS.items():
        f = by[ts]
        out.append('   %-22s = bits,   %s, %4d, [%d:%d], %s'
                   % (alias, TS_TYPE[f.ctype], f.offset, bit, bit,
                      ", ".join('"%s"' % x for x in labels)))
    return out


def element_label(fmt, n, base=1):
    """A per-element label: a format with %d, or one label per element."""
    return fmt[n - base] if isinstance(fmt, list) else fmt % n

_TS_WIDTH = {"U08": 1, "S08": 1, "U16": 2, "S16": 2, "U32": 4, "S32": 4}


def element_alias_lines(fields) -> list[str]:
    """One scalar Constant per element of every array a dialog shows."""
    out = []
    for f in fields:
        m = f.meta
        if f.count <= 1 or m.ts not in ELEMENT_FIELDS:
            continue
        t = TS_TYPE[f.ctype]
        w = _TS_WIDTH[t]
        base = 1 if m.ts != "tdcCylExtDegX10" else 9
        for i in range(f.count):
            nm = "%s%d" % (m.ts, base + i)
            if m.is_pin:
                # injPin1..12 and ignPin1..12 are the per-cylinder aliases the
                # dialogs actually bind to - section 14's "rusEFI declares each
                # element as its own scalar". They are pins too, and they were
                # the largest block of raw-number fields in the whole .ini.
                out.append('   %-22s = bits,   %s, %4d, [0:7], %s'
                           % (nm, t, f.offset + i * w,
                              GEN._pin_labels(m.pin_needs, m.ts)))
            elif m.enum is not None:
                # V97: an enum per element is a dropdown per element
                out.append('   %-22s = bits,   %s, %4d, [0:%d], %s'
                           % (nm, t, f.offset + i * w, GEN._bits_for(m.enum),
                              GEN._enum_labels(m.enum)))
            else:
                out.append('   %-22s = scalar, %s, %4d, "%s", %s, %s, %s, %s, %d'
                           % ((nm, t, f.offset + i * w, m.units)
                              + GEN.ts_scaling(m) + (m.digits,)))
    return out


# ==========================================================================
# 1a. STAGE A - SEMANTIC SELECTORS FOR PAGE CONSTANTS, INI-ONLY.
#
# `bits` at the same offset and the same width as the `scalar` it replaces, so
# the PAGE LAYOUT IS BYTE-IDENTICAL and the frozen V37 binary is untouched.
# TunerStudio maps the integer the firmware already stores; nothing is encoded
# differently.  This is deliberately NOT done by adding `enum=` to the model,
# because that regenerates hc_config_generated.h and would change firmware
# source - see the maintainer's design notes, Stage A.
#
# EVERY LABEL BELOW IS SOURCED, and the source is named. Where the firmware
# says a field is a COUNT rather than a mode it stays a scalar: CAL_REVLIM_
# PATTERN is "events cut out of 8, 1..8" (hcconfig.h:436), so it is a number
# and a dropdown would be a lie.
#
# BLOCKED, DELIBERATELY: every pin/cavity field. Their labels would have to
# come from build/generated/hc_hw_descriptor_bosch_me711.csv, which inherits an
# ME7.1 C4 connector and is wrong for cavities 18..24 - it calls the Porsche
# main-relay drive "EV8". A friendly wrong label is worse than a raw integer,
# because a tuner has no reason to distrust it. See the maintainer's design notes
# section 8.7.
# ==========================================================================
OFF_ON = ["Off", "On"]

STAGE_A_SELECTORS = {
    # ---- enables: 0/1, from the model's own lo/hi ----
    "camEnable":       (OFF_ON, "hctrig_me711.c"),
    "idleEnable":      (OFF_ON, "hcconfig.h"),
    "boostEnable":     (OFF_ON, "hcconfig.h"),
    "dbwEnable":       (OFF_ON, "hc_dbw.c"),
    # rusEFI's own wording, from its generated .ini:
    #     timingMode = bits, U08, 482, [0:0], "dynamic", "fixed"
    # A safety-relevant mode shown as 0 or 1 is exactly the magic-number
    # problem section 6 of the gap matrix is about - and this one holds ONE
    # ignition angle at every speed when it is set.
    "timingModeCfg":   (["Dynamic (the ignition map)",
                         "FIXED (timing light only)"], "hcengine.c"),
    "pwmInvert":       (["Active high", "Active low (inverted)"], "hcconfig.h"),
    "outputsArmedCfg": (["Retired (0)", "Retired (1)"], "hcsafety.h V84"),

    # ---- modes, each read out of the firmware that consumes them ----
    # hcconfig.h:254  CAL_INJ_MODE  "u8  0 = batch, 1 = sequential"
    "injModeLegacy":   (["Batch", "Sequential"], "hcconfig.h:254"),
    # hc_dbw.c motor polarity
    "dbwMotorDir":     (["Normal", "Reversed"], "hc_dbw.c"),
    # hcconfig.h engine cycle. 2 and 4 are the only valid values, so the gaps
    # are labelled INVALID rather than left to look selectable.
    "strokes":         (["INVALID", "INVALID", "Two-stroke", "INVALID",
                         "Four-stroke", "INVALID", "INVALID", "INVALID"],
                        "hcconfig.h"),
}


def _preset_selectors():
    """Preset names come from the generator that WRITES them, never typed.

    All three component lists hold exactly one entry, CUSTOM. A one-entry
    dropdown is the honest rendering; inventing injector or coil part names to
    make it look fuller is what the project rules forbid in as many words.
    """
    import hanicore_presets as P
    out = {}
    # V86: INDEXED BY PRESET ID, NOT BY LIST POSITION. The list is ids
    # 0,1,2,4,3, so up to V85 the label "VAG 1.8T DBW ..." sat at VALUE 4 -
    # the board-default preset's id - and the 1.8T preset's own id 3 was
    # labelled as the board default. A preset for another ECU is "INVALID"
    # (TunerStudio hides those): it can only ever be refused on this board.
    ids = {p.ident: p for p in P.ENGINE_PRESETS}
    eng = []
    for i in range(max(ids) + 1):
        p = ids.get(i)
        if p is None or (p.target and p.target != "BOSCH_ME711"):
            eng.append("INVALID")
        else:
            eng.append(p.name)
    out["enginePreset"] = (eng, "hanicore_presets.ENGINE_PRESETS")
    for ts, key in (("injectorPreset", "INJECTORS"),
                    ("coilPreset", "COILS"),
                    ("mapSensorPreset", "PRESSURE_SENSORS")):
        names = [c.name for c in P.COMPONENT_PRESETS[key]]
        out[ts] = (names, "hanicore_presets.COMPONENT_PRESETS[%r]" % key)
    return out


STAGE_A_SELECTORS.update(_preset_selectors())


def _selector_line(m, ctype, offset, labels):
    """A `bits` line occupying exactly the bytes the scalar occupied."""
    n = 1
    while (1 << n) < len(labels):
        n += 1
    full = [labels[i] if i < len(labels) else "INVALID"
            for i in range(1 << n)]
    return ('   %-22s = bits,   %s, %4d, [0:%d], %s'
            % (m.ts, ctype, offset, n - 1,
               ", ".join('"%s"' % x for x in full)))


def page_lines(fields) -> list[str]:
    out = []
    for f in fields:
        m = f.meta
        t = TS_TYPE[f.ctype]
        if f.count > 1:
            shape = SHAPE.get(m.ts, "[%d]" % f.count)
            out.append('   %-22s = array,  %s, %4d, %-9s "%s", %s, %s, %s, %s, %d'
                       % ((m.ts, t, f.offset, shape + ",", m.units)
                          + GEN.ts_scaling(m) + (m.digits,)))
        elif m.is_pin:
            # A CAPABILITY-FILTERED DROPDOWN, not a number to type. The labels
            # come from the same hardware descriptor hc_validate() and the V62
            # runtime router use, so the list cannot offer a cavity the ECU
            # would refuse. Stored encoding unchanged.
            out.append('   %-22s = bits,   %s, %4d, [0:7], %s'
                       % (m.ts, t, f.offset, GEN._pin_labels(m.pin_needs, m.ts)))
        elif m.enum is not None:
            out.append('   %-22s = bits,   %s, %4d, [0:%d], %s'
                       % (m.ts, t, f.offset, GEN._bits_for(m.enum),
                          GEN._enum_labels(m.enum)))
        elif m.ts in STAGE_A_SELECTORS:
            out.append(_selector_line(m, t, f.offset,
                                      STAGE_A_SELECTORS[m.ts][0]))
        else:
            out.append('   %-22s = scalar, %s, %4d, "%s", %s, %s, %s, %s, %d'
                       % ((m.ts, t, f.offset, m.units)
                          + GEN.ts_scaling(m) + (m.digits,)))
    out += element_alias_lines(fields)
    out += bit_view_lines(fields)
    return out


# A 256-entry map is 16 x 16. Stated once, here, and checked against the
# model's own count in layout().
SHAPE = {
    "vvtTarget1": "[8x8]", "vvtTarget2": "[8x8]",
    "mapEstimate": "[8x8]", "injPhaseTable": "[8x8]",
    "veTable": "[16x16]", "ignMap": "[16x16]", "afrMap": "[16x16]",
    "pedalMap": "[16x16]", "boostDutyMap": "[16x16]",
    "boostTgtMap": "[16x16]",
}


# ==========================================================================
# 2. Table and curve editors.
#
# THE AXES ARE THE FIRMWARE'S, not a guess. hcengine.c calls
#     hc_cal_map(CAL_FUEL_MAP, CAL_FUEL_RPM_AX, CAL_FUEL_LOAD_AX, ...)
#     hc_cal_map(CAL_IGN_MAP,  CAL_IGN_RPM_AX,  CAL_IGN_LOAD_AX,  ...)
#     hc_cal_map(CAL_AFR_MAP,  CAL_IGN_RPM_AX,  CAL_IGN_LOAD_AX,  ...)
# so the lambda-target map is on the IGNITION axes, which is exactly the sort
# of thing a hand-written .ini gets wrong and a tuner never finds out about.
# ==========================================================================
#
# AND EVERY AXIS CARRIES ITS TRACING OUTPUT CHANNEL, which is not decoration:
# `xBins = <axis constant>` ALONE IS WHAT MADE V34 FAIL TO LOAD in real
# TunerStudio 3.3.01 on 2026-09-03 -
#
#     Invalid Ini entry in Loading Tables
#     Error in [TableEditor] Section, I don't know how to handle this line.
#
# TunerStudio's table parser wants the axis constant AND the runtime channel
# whose value moves the cursor. In 636 axis lines across rusEFI's own generated
# .ini files - which do load - the count is never one. tools/
# ts_ini_grammar_proof.py is the gate that now knows that.
#
# THE TRACER MUST ALSO BE IN THE AXIS'S UNITS, or the cursor lands on the wrong
# cell, which is a quieter lie than not loading at all. Every axis below is
# u16 with scale 0.1, so every tracer is a 0.1-unit channel scaled the same
# way - see the SCALE table in gen_ts_ini_me711.py.
#
#   (table id, z field, x field, x tracer, y field, y tracer, title)
#
# V97: STORAGE IS [load][rpm] (generate_config.TABLE_ORDER): TunerStudio's
# index for `[NxM]` is y * N + x, so with xBins = rpm and yBins = load a row
# on screen is one load. Every z field here is stored that way.
TABLES = [
    # V97: VVT targets (rusEFI vvtTable1 / vvtTable2), [rpm][load]
    ("vvtTarget1Tbl",  "vvtTarget1",   "vvtRpmAx",      "RPMValue",
     "vvtLoadAx",     "rlX10",
     "Cam 1 (intake) VVT target"),
    ("vvtTarget2Tbl",  "vvtTarget2",   "vvtRpmAx",      "RPMValue",
     "vvtLoadAx",     "rlX10",
     "Cam 2 (exhaust) VVT target"),
    # The VE table's y is whatever the firmware passed to the lookup - TPS or
    # MAP, per CAL_LOAD_SOURCE - so it gets its own channel rather than a guess
    # that is right in only one load mode.
    ("veTableTbl",     "veTable",      "fuelRpmAx",     "RPMValue",
     "fuelLoadAx",    "fuelLoad",
     "VE - volumetric efficiency"),
    # V98: each table's OWN load (rusEFI getLoadOverride): the ignition table
    # with ignLoad, the target lambda table on ITS OWN axes with lambdaLoad -
    # until V98 it borrowed the ignition axes.
    ("ignMapTbl",      "ignMap",       "ignRpmAx",      "RPMValue",
     "ignLoadAx",     "ignLoad",
     "Ignition timing"),
    ("afrMapTbl",      "afrMap",       "lambdaRpmAx",   "RPMValue",
     "lambdaLoadAx",  "lambdaLoad",
     "Target lambda"),
    # hc_dbw.c indexes the pedal map with D.pedal, published as dbwPedalX10.
    ("pedalMapTbl",    "pedalMap",     "pedalRpmAx",    "RPMValue",
     "pedalAx",       "dbwPedalX10",
     "Throttle target vs pedal"),
    # V98: rusEFI mapEstimateTable - the fuel's pressure while the sensor has
    # failed (rpm x throttle).
    ("mapEstimateTbl", "mapEstimate",  "mapEstRpmAx",   "RPMValue",
     "mapEstTpsAx",   "TPSValue",
     "Pressure estimate (sensor fault)"),
    # V98: rusEFI injectionPhase - the injection angle by rpm x fuel load.
    ("injPhaseTbl",    "injPhaseTable", "injPhaseRpmAx", "RPMValue",
     "injPhaseLoadAx", "fuelLoad",
     "Injection timing"),
    # The boost controller is NOT linked on this target, so these two have no
    # runtime lookup to trace. The axes are rpm and throttle, so the honest
    # tracers are rpm and the throttle channel: the cursor then shows where the
    # engine is on the map, which is true whether or not anything reads it.
    ("boostDutyTbl",   "boostDutyMap", "boostRpmAx",    "RPMValue",
     "boostTpsAx",    "TPSValue",
     "Boost base wastegate duty"),
    ("boostTgtTbl",    "boostTgtMap",  "boostTgtRpmAx", "RPMValue",
     "boostTgtTpsAx", "TPSValue",
     "Boost target"),
]

#   (curve id, x field, y field, title, x label, y label)
CURVES = [
    ("cltEnrCurve",   "cltEnrAx",     "cltEnrVal",
     "Warm-up enrichment", "Coolant", "Enrichment %"),
    # V97: transient fuel (firmware/engine/hctrans.c), on the warm-up coolant axis
    ("wwXCurve",      "cltEnrAx",     "wwXPct",
     "Wall wetting fraction (X)", "Coolant", "% on the wall"),
    ("wwTauCurve",    "cltEnrAx",     "wwTau",
     "Wall film time constant (tau)", "Coolant", "s"),
    ("asCurve",       "cltEnrAx",     "asPct",
     "After-start extra fuel", "Coolant", "%"),
    # V97: ignition corrections (rusEFI ignitionCltCorr / ignitionIatCorr)
    ("ignCltCorrCurve", "cltEnrAx",   "ignCltCorr",
     "CLT timing correction", "Coolant", "deg"),
    ("ignIatCorrCurve", "ignIatAx",   "ignIatCorr",
     "IAT timing correction", "Intake air", "deg"),
    # 2026-10-16: timing by boost above ambient (Link / Haltech boost trim)
    ("ignBoostCorrCurve", "ignBoostAx", "ignBoostCorr",
     "Boost timing correction", "Boost above ambient", "deg"),
    # V97: knock (rusEFI knockThresholdCurve / window start + duration)
    ("knockKefCurve", "knockKefRpm", "knockKef",
     "Knock threshold factor", "RPM", "x reference"),
    ("knockWinStartCurve", "knockRpmAx", "knockWinStart",
     "Knock window start", "RPM", "deg ATDC"),
    ("knockWinLenCurve", "knockRpmAx", "knockWinLen",
     "Knock window length", "RPM", "deg"),
    ("crankPwCurve",  "crankPwAx",    "crankPwVal",
     "Cranking fuel", "Coolant", "mg / cylinder / cycle"),
    # V98: rusEFI primeValues - the key-on priming pulse, on the same axis
    ("primeCurve",    "crankPwAx",    "primeMgX10",
     "Priming pulse fuel", "Coolant", "mg per injector"),
    ("dwellBattCurve", "dwellBattAx", "dwellBattVal",
     "Dwell vs battery", "Battery", "Dwell"),
    # 2026-10-14: a factor on the battery dwell (rusEFI sparkDwellRpmBins,
    # Speeduino dwell map)
    ("dwellRpmCurve", "dwellRpmAx", "dwellRpmPct",
     "Dwell by rpm", "RPM", "% of battery dwell"),
    # SAME AXIS as the dwell curve - hcconfig.h says so in as many words:
    # "CAL_DEADTIME_VAL  u16[8]  deadtime us, same axis".
    ("deadtimeCurve", "dwellBattAx",  "deadtimeVal",
     "Injector deadtime vs battery", "Battery", "Deadtime us"),
    ("cltSensCurve",  "cltSensAx",    "cltSensVal",
     "Coolant sensor", "ADC counts", "Temperature"),
    ("iatSensCurve",  "iatSensAx",    "iatSensVal",
     "Intake air sensor", "ADC counts", "Temperature"),
    ("idleTargetCurve", "idleTargetAx", "idleTargetVal",
     "Idle target rpm vs coolant", "Coolant", "Target rpm"),
    ("idleBaseCurve", "idleBaseAx",   "idleBaseVal",
     "Idle base authority vs coolant", "Coolant", "Authority"),
    ("dbwBiasCurve",  "dbwBiasAx",    "dbwBiasVal",
     "Throttle feed-forward bias", "Throttle %", "Duty"),
    ("boostCltCurve", "boostCltAx",   "boostCltMul",
     "Boost coolant multiplier", "Coolant", "Multiplier"),
    ("boostIatCurve", "boostIatAx",   "boostIatMul",
     "Boost intake-air multiplier", "Intake air", "Multiplier"),
]


def table_dialog_lines() -> list[str]:
    """THE 2D CELL EDITOR IS THE PRIMARY VIEW OF EVERY MAP.

    A menu entry that names the map3d id opens the 3D surface and NOTHING
    else, which is what V35 shipped: every map was a picture a tuner could
    look at and not a grid a tuner could type in. Naming the TABLE id in a
    panel gives the ordinary editable cell grid. That is how rusEFI does it -

        dialog = veTableDialog, ""      panel = veTableTbl
        dialog = veTableDialog3D, ""    panel = veTableMap, South

    - and both shapes are in the corpus ts_ini_grammar_proof checks against.
    The 3D view stays, as a second entry beside the grid rather than instead
    of it.

    These go INSIDE the one [UserDefined] section; a second section header
    would be a second place for dialogs to live."""
    out = []
    # 2026-10-11 (owner, Speeduino screenshots): NO separate 3D entries.
    # TunerStudio's table editor carries its own "3D View" box (top right
    # of the grid), which is how Speeduino shows every map; a second menu
    # line per map was clutter.
    try:                # tables a workflow window embeds with its options
        import gen_ts_ux_me711 as _UX
        embedded = set(getattr(_UX, "EMBEDDED_TABLES", ()))
    except ImportError:
        embedded = set()
    for tid, _z, _x, _xt, _y, _yt, title in TABLES:
        if tid in embedded:
            continue
        out.append('   dialog = %sEdit, "%s"' % (tid, title))
        out.append('      panel = %s' % tid)
        out.append("")
    return out


# V97: the axis titles a tuner reads (rusEFI xyLabels). A string in braces
# is a TunerStudio expression - the VE/ignition/AFR y axis says what the
# load source makes it (gen_ts_ini_me711.LOAD_AXIS_LISTS).
# hcLoadAxisList (gen_ts_ini_me711.LOAD_AXIS_LISTS) = Fuel load / Pressure
# sensor / Throttle position / Cylinder filling / Manifold pressure / Charge
# pressure. The fuel load is a PRESSURE for Speed density (the new model, or
# the legacy model on its MAP strategy) and the THROTTLE otherwise; a
# pressure is named by where Fuel > Fuel model says the sensor measures.
# Until 2026-10-09 these keyed on loadSource alone, so Speed density selected
# in the fuel model still titled the VE axis "Throttle position".
_PRESS = "(pressureRole == 1 ? 4 : (pressureRole == 2 ? 5 : 1))"
_FUEL = ("((fuelModel == 2 || (fuelModel == 0 && loadSource == 0)) ? %s : 2)"
         % _PRESS)
TABLE_Y_LABEL = {
    "veTableTbl": "{bitStringValue(hcLoadAxisList, %s)}" % _FUEL,
    "ignMapTbl": "{bitStringValue(hcLoadAxisList, ignLoadMode == 0 ? %s : (ignLoadMode == 1 ? %s : ignLoadMode))}" % (_FUEL, _PRESS),
    "afrMapTbl": "{bitStringValue(hcLoadAxisList, lambdaLoadMode == 0 ? %s : (lambdaLoadMode == 1 ? %s : lambdaLoadMode))}" % (_FUEL, _PRESS),
    "pedalMapTbl": "Pedal position (%)",
    "boostDutyTbl": "Throttle position (%)",
    "boostTgtTbl": "Throttle position (%)",
    "vvtTarget1Tbl": "Cylinder filling (%)",
    "vvtTarget2Tbl": "Cylinder filling (%)",
    "mapEstimateTbl": "Throttle position (%)",
    "injPhaseTbl": "{bitStringValue(hcLoadAxisList, %s)}" % _FUEL,
}


# THE LIVE CURSOR OF EVERY CURVE (owner, 2026-10-11). `xBins = <axis>` with
# no channel draws a curve TunerStudio cannot trace: 20 of 22 curves had no
# cursor on the car. rusEFI writes `xBins = cltFuelCorrBins, coolant`. Each
# channel is in the SAME display units as its axis (scale/translate checked
# against the generated .ini: C/C, V/V, rpm/rpm, %/%, ADC counts/counts);
# ts_ini_tracer_proof re-checks that every curve and table names an existing
# output channel inside the block with the axis's unit.
CURVE_TRACER = {
    "cltEnrAx": "coolant", "crankPwAx": "coolant", "idleTargetAx": "coolant",
    "idleBaseAx": "coolant", "boostCltAx": "coolant",
    "ignIatAx": "intake", "boostIatAx": "intake",
    "dwellBattAx": "VBatt",                       # dwell AND dead time
    "knockKefRpm": "RPMValue", "knockRpmAx": "RPMValue",
    "dwellRpmAx": "RPMValue",
    "cltSensAx": "cltRawAsic", "iatSensAx": "iatRawAsic",   # raw ADC counts
    "dbwBiasAx": "etbActual",                     # throttle plate, %
    "ignBoostAx": "boostAboveAmbient",            # charge/MAP - ambient, kPa
}


def table_lines(by_ts) -> list[str]:
    out = ["[TableEditor]"]
    for tid, z, x, xt, y, yt, title in TABLES:
        out.append('   table = %s, %sMap, "%s", 1' % (tid, tid, title))
        ylab = TABLE_Y_LABEL[tid]
        out.append('      xyLabels = "RPM", %s'
                   % (ylab if ylab.startswith("{") else '"%s"' % ylab))
        out.append('      xBins = %s, %s' % (x, xt))
        out.append('      yBins = %s, %s' % (y, yt))
        out.append('      zBins = %s' % z)
        out.append("")
    out.append("[CurveEditor]")
    for cid, x, y, title, xl, yl in CURVES:
        fx, fy = by_ts[x], by_ts[y]
        out.append('   curve = %s, "%s"' % (cid, title))
        out.append('      columnLabel = "%s", "%s"' % (xl, yl))
        # A CURVE AXIS IS IN DISPLAY UNITS. rusEFI writes `xAxis = -40, 120, 9`
        # for a coolant axis - degrees, what the tuner sees. These were emitted
        # straight from the model's RAW lo/hi, so the coolant sensor curve ran
        # its y axis to 65535 while every point on it was `raw * 0.1 - 100` and
        # sat in the bottom one percent. Eleven curves, all of them.
        def _disp(meta, v):
            return meta.scale * v + meta.translate

        out.append('      xAxis = %s, %s, %d'
                   % (GEN._num(_disp(fx.meta, fx.meta.lo)),
                      GEN._num(_disp(fx.meta, fx.meta.hi)), 9))
        out.append('      yAxis = %s, %s, %d'
                   % (GEN._num(_disp(fy.meta, fy.meta.lo)),
                      GEN._num(_disp(fy.meta, fy.meta.hi)), 9))
        if x not in CURVE_TRACER:
            raise SystemExit("curve %s: axis %s has no live channel in "
                             "CURVE_TRACER - every curve must trace" % (cid, x))
        out.append('      xBins = %s, %s' % (x, CURVE_TRACER[x]))
        out.append('      yBins = %s' % y)
        out.append("")
    return out


# ==========================================================================
# 3. The dialogs.
#
# One dialog per (category, group) pair the model actually contains, plus the
# hand-authored ones that are not settings at all - diagnostics and the bench
# controller. Fields that belong to a table or a curve are NOT repeated as raw
# arrays: an editor is how a tuner touches a map.
# ==========================================================================
GROUP_TITLE = {
    "GENERAL": "General",
    "ENGINE_SETUP": "Engine setup",
    "TRIGGER_SETUP": "Trigger",
    "TABLES": "Tables and curves",
    "SENSOR_ROUTING": "Sensors and pins",
    "OUTPUT_ROUTING": "Outputs",
    "INJECTOR_ROUTING": "Injectors",
    "IGNITION_ROUTING": "Coils",
    "RELAY_SETUP": "Relay",
    "DBW_SETUP": "Throttle",
    "MOTORSPORT": "Motorsport",
}

# Categories in menu order. Anything the model gains later that is not listed
# lands in "Other", which layout() reports rather than silently dropping.
CATEGORY_ORDER = ["Engine", "Trigger", "Sensors", "Fuel", "Load and protection", "Ignition", "Knock",
                  "VVT", "Idle",
                  "DBW", "Lambda", "Boost", "Motorsport", "Safety", "I/O",
                  "Controller"]

# Where the firmware is not finished, the dialog says so IN THE DIALOG. These
# are the honest labels; they are not decoration, they are the difference
# between a UI a tuner can trust and one that lies by omission.
# V98: every caveat that stood here (boost "not linked", motorsport
# "interfaces only", lambda "no closed loop", DBW "not bound") described a
# firmware that no longer exists. What is not PHYSICALLY qualified is said
# in each workflow dialog (gen_ts_ux_me711) - implementation and
# qualification are separate statements.
CAVEAT: dict[str, str] = {}


def dialogs(fields):
    """(category -> [(dialog id, title, [field names])]), in model order."""
    in_editor = {z for _t, z, _x, _xt, _y, _yt, _ti in TABLES}
    in_editor |= {x for _t, _z, x, _xt, _y, _yt, _ti in TABLES}
    in_editor |= {y for _t, _z, _x, _xt, y, _yt, _ti in TABLES}
    for _c, x, y, *_ in CURVES:
        in_editor.add(x)
        in_editor.add(y)

    out = {}
    for f in fields:
        cat = f.meta.category
        grp = getattr(f.meta.group, "name", str(f.meta.group))
        if f.meta.ts in in_editor:
            continue
        out.setdefault(cat, {}).setdefault(grp, []).append(f)
    return out


def dialog_id(cat: str, grp: str) -> str:
    safe = cat.replace("/", "").replace(" ", "")
    return "hc%s%s" % (safe, grp.title().replace("_", ""))


def dialog_lines(fields) -> tuple[list[str], list[tuple]]:
    """The [UserDefined] body, and the (category, [(id, title)]) menu plan."""
    grouped = dialogs(fields)
    out, plan = [], []

    for cat in CATEGORY_ORDER + sorted(set(grouped) - set(CATEGORY_ORDER)):
        if cat not in grouped:
            continue
        entries = []
        for grp in sorted(grouped[cat]):
            did = dialog_id(cat, grp)
            title = "%s - %s" % (cat, GROUP_TITLE.get(grp, grp.title()))
            out.append('   dialog = %s, "%s"' % (did, title))
            if cat in CAVEAT:
                for line in _wrap(CAVEAT[cat]):
                    out.append('      field = "%s"' % line)
                out.append('      field = ""')
            for f in grouped[cat][grp]:
                lbl = f.meta.label.replace('"', "'")
                if f.meta.is_pin:
                    lbl = "%s (ECU pin 1..121, 255 = none)" % lbl
                if f.count > 1 and f.meta.ts in ELEMENT_FIELDS:
                    # ELEMENT BY ELEMENT - TunerStudio refuses `field` on an
                    # array and asks for array1D, a shape no .ini in this
                    # repository that loads has ever used. See ELEMENT_FIELDS.
                    fmt, guard = ELEMENT_FIELDS[f.meta.ts]
                    base = 1 if f.meta.ts != "tdcCylExtDegX10" else 9
                    for i in range(f.count):
                        n = base + i
                        line = '      field = "%s", %s%d' % (element_label(fmt, n, base),
                                                             f.meta.ts, n)
                        if guard:
                            line += ", { %s >= %d }" % (guard, n)
                        out.append(line)
                    continue
                out.append('      field = "%s", %s' % (lbl, f.meta.ts))
            out.append("")
            entries.append((did, GROUP_TITLE.get(grp, grp.title())))

        for tid, z, _x, _xt, _y, _yt, ti in TABLES:
            if _cat_of(fields, z) == cat:
                entries.append((tid + "Map", ti))
        for cid, _x, y, ti, _xl, _yl in CURVES:
            if _cat_of(fields, y) == cat:
                entries.append((cid, ti))
        plan.append((cat, entries))
    return out, plan


def _cat_of(fields, ts):
    for f in fields:
        if f.meta.ts == ts:
            return f.meta.category
    return None


def _wrap(text, width=64):
    words, line, out = text.split(), "", []
    for wd in words:
        if len(line) + len(wd) + 1 > width:
            out.append(line)
            line = wd
        else:
            line = (line + " " + wd).strip()
    if line:
        out.append(line)
    return out


# ==========================================================================
# 4. Checks. This module authors presentation, so what it authors is verified.
# ==========================================================================
def layout():
    fields, consts, problems = MODEL.resolve()
    if problems:
        raise SystemExit("the configuration model does not resolve:\n  "
                         + "\n  ".join(problems))
    by_ts = {f.meta.ts: f for f in fields}

    for name, shape in SHAPE.items():
        if name not in by_ts:
            raise SystemExit("SHAPE names %s, which is not a model field" % name)
        rows, cols = (int(x) for x in shape.strip("[]").split("x"))
        if rows * cols != by_ts[name].count:
            raise SystemExit("%s is %s in the .ini but %d bytes in the model"
                             % (name, shape, by_ts[name].count))

    for tid, z, x, _xt, y, _yt, _t in TABLES:
        for n in (z, x, y):
            if n not in by_ts:
                raise SystemExit("table %s names %s, which does not exist"
                                 % (tid, n))
        if by_ts[z].count != by_ts[x].count * by_ts[y].count:
            raise SystemExit(
                "table %s: %s holds %d cells but its axes are %d x %d"
                % (tid, z, by_ts[z].count, by_ts[x].count, by_ts[y].count))

    for cid, x, y, _t, _xl, _yl in CURVES:
        for n in (x, y):
            if n not in by_ts:
                raise SystemExit("curve %s names %s, which does not exist"
                                 % (cid, n))
        if by_ts[x].count != by_ts[y].count:
            raise SystemExit("curve %s: %s has %d points, %s has %d"
                             % (cid, x, by_ts[x].count, y, by_ts[y].count))

    unknown = sorted({f.meta.category for f in fields} - set(CATEGORY_ORDER))
    if unknown:
        raise SystemExit("the model has categories this UI does not place: %s"
                         % unknown)
    return fields, by_ts, consts


if __name__ == "__main__":
    fs, by, _c = layout()
    print("%d fields, %d tables, %d curves" % (len(fs), len(TABLES), len(CURVES)))
    body, plan = dialog_lines(fs)
    for cat, entries in plan:
        print("  %-12s %d entries" % (cat, len(entries)))
