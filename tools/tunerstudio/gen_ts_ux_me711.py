#!/usr/bin/env python3
r"""
gen_ts_ux_me711.py - the USER-FACING TunerStudio interface, authored as
WORKFLOWS, from rusEFI's own generated .ini as the template.

    imported by tools/tunerstudio/gen_ts_ini_me711.py
    py tools\tunerstudio\gen_ts_ux_me711.py         show what it places and what it does not

WHAT THIS REPLACED, AND WHY IT HAD TO BE REPLACED
=================================================
gen_ts_ui_me711.dialog_lines() emitted one dialog per (model category, apply
group) pair and filled it with every field in that pair, in model order. The
menu was then re-labelled to look like rusEFI's. Real TunerStudio 3.3.01 opened
it on 2026-09-05 and the verdict was that "Engine Setup is a long flat field
list, Trigger is another long flat field list, Injector setup is another long
flat field list" - which is exactly what a cross-product of a data model
produces. Renaming the menu did not change what the dialogs ARE.

    A MATURE ECU FEATURE IS A WORKFLOW - configure, calibrate, bench-verify,
    diagnose - NOT A SET OF FIELDS.

So the model still owns WHICH fields exist, their offsets, units, limits and
labels - nothing here retypes any of that, and layout() still refuses to
resolve if the model and hcconfig.h disagree. What this file owns is the SHAPE
a person meets: which panel a field belongs to, what sits next to it, which
live value is shown beside the setting that changes it, and what the sequence
of actions is.

THE TEMPLATE IS rusEFI's, READ FROM THE CHECKOUT, NOT FROM MEMORY
=================================================================
Every structural decision below cites the rusEFI line it copies.
rusEFI firmware/tunerstudio/generated/rusefi_proteus_f7.ini is one of
40 files known to load in real TunerStudio.

  * A SENSOR CALIBRATION IS A SPLIT DIALOG: settings on the left, the live
    readings that prove them on the right.

        dialog = cltSensor, "CLT Sensor", border      (rusEFI 7-)
            panel = clt_thermistor, West
            panel = cltGauges, East

    Copied for CLT, IAT, MAP, BARO, TPS, pedal, battery and throttle. A tuner
    turns a number and watches the effect in the same window; that is the
    entire difference between a calibration workflow and a field.

  * ENDPOINT GRAB IS A BUTTON NEXT TO THE ENDPOINT.

        commandButton = "Grab Closed Throttle voltage", cmd_calibrate_tps_closed
        commandButton = "Grab Idle/Up", cmd_calibrate_pedal_up

    rusEFI puts them inside tpsNum1 / pedalSensorLeft, immediately under the
    min and max fields they write. Where the flashed firmware has no such
    command the button is NOT emitted - an inert button is the defect V37B
    existed to fix - and the panel says in its own text how to do it by hand.

  * BENCH TESTS ARE THEIR OWN TOP-LEVEL THING with an abort on every panel,
    rusEFI's ioTest ("Bench Test & Commands", xAxis, panel per subsystem).

  * INDICATORS LIVE IN indicatorPanels. Bare `indicator =` is legal in
    [FrontPage] and nowhere else; rusEFI's 268 indicator lines obey that
    without exception and real TunerStudio 3.3.01 threw away thirteen of
    HaniCore's for breaking it. tests/tunerstudio/ts_ini_indicator_scope_proof.py is the
    gate.

  * THE DEFAULT DASHBOARD IS EIGHT GAUGES AND A STRIP OF INDICATORS.
    rusEFI's [FrontPage] is RPM, CLT, TPS, MAP, AFR, VBatt, dwell, advance -
    and its indicators are things a driver acts on. HaniCore's were
    tooth index, gap candidate, asicInit, badVecBit and wdtFed.

NOTHING HERE MAY INVENT A CONTROL
=================================
Every `field` name is checked against the model, every `gauge` against the
emitted [GaugeConfigurations], every `commandButton` against
[ControllerCommands], and every panel/dialog reference against what this file
declares. place_report() additionally requires EVERY model field to be placed
somewhere or listed in NOT_SHOWN with a reason, so a hand-authored UI cannot
quietly lose a setting the way a generated one could not.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
sys.path.insert(0, str(ROOT / "tools/config_source"))

import gen_ts_ui_me711 as UI        # noqa: E402  model -> page, tables, curves


# ==========================================================================
# Item constructors. A panel is a list of these; nothing else is legal.
# ==========================================================================
def F(ts, label=None, guard=None):
    """A page CONSTANT. label defaults to the model's own."""
    return ("f", ts, label, guard)


def T(text):
    """An informational line. rusEFI writes these as `field = "..."`;
    a leading '#' renders as a heading and '!' as a warning."""
    return ("t", text)


def N(text):
    """A short note shown IN the window (blue, TunerStudio's '#' line), as
    Speeduino does - never moved to the help page."""
    return ("n", text)


def B():
    return ("t", "")


def G(gauge):
    """A LIVE value. Never a `field` - see gen_ts_ui_me711's honesty rules."""
    return ("g", gauge)


def P(panel, where=None, guard=None):
    return ("p", panel, where, guard)


def C(cmd, label, guard=None):
    return ("c", cmd, label, guard)


def PV(panel, visible):
    """A panel SHOWN only while `visible` holds - rusEFI's
    `panel = x, {1}, { condition }` (rusefi_proteus_f7.ini:8786).
    THE CONDITION MUST BE ON SETTINGS, NEVER ON A LIVE (ECU-sent) CHANNEL:
    TunerStudio does not evaluate a panel's visibility on output channels,
    so such a panel never shows (the 2026-10-12 empty DTC list; rusEFI's
    INIs never do it). ts_ini_ux_contract_proof refuses it."""
    return ("v", panel, visible)


def S(label, options, guard=None):
    """A 'common sensors' dropdown (TunerStudio settingSelector): each option
    writes ordinary page values, in DISPLAY units. options = [(name,
    [(field, value), ...]), ...]. Speeduino's mapCal / rusEFI's cltSensor
    pattern; the values are computed in ts_sensor_presets_me711."""
    return ("s", label, options, guard)


def E(ts, guard=None):
    """Every element of an array, as the per-element scalars the page
    declares. TunerStudio refuses `field` on an array."""
    return ("e", ts, guard)


def BV(alias, guard=None):
    """V98: one bit of a page word as its own switch
    (gen_ts_ui_me711.BIT_VIEWS, rusEFI's `bits, U32, off, [n:n]`)."""
    return ("b", alias, guard)


def IND(expr, off, on, colours=None):
    return ("i", expr, off, on, colours)


def RO(gauge):
    return ("r", gauge)


def LG(gid, title, where, channels):
    """A LIVE GRAPH, rusEFI's own idiom (rusefi_proteus_f7.ini:
    `liveGraph = fuel_computer_1_Graph, "Graph", South` + `graphLine = ch`).
    Only where a trace over time is what a tuner reads - target vs actual
    for a controller - never as decoration. Channels are checked against
    the emitted gauges (a channel without a gauge is not an output channel
    this file knows)."""
    return ("l", gid, title, where, tuple(channels))


# ==========================================================================
# 1. PANELS - the small, single-purpose blocks workflows are built from.
#
#    (id, title, items)  -  title "" is rusEFI's own idiom for a panel that is
#    only ever embedded and should not draw its own frame caption.
# ==========================================================================
PANELS: list[tuple] = []
IND_PANELS: list[tuple] = []
READ_PANELS: list[tuple] = []
# V89 UI: a panel may lay its children out side by side. rusEFI's idiom -
# `dialog = triggerConfiguration, "", xAxis` then one `panel =` per column -
# is how a 1920-wide screen stops being used as a 480-wide one. Kept apart
# from PANELS so every (pid, title, items) consumer is untouched.
PANEL_LAYOUT: dict[str, str] = {}


def panel(pid, title, items, layout=None):
    PANELS.append((pid, title, items))
    if layout:
        PANEL_LAYOUT[pid] = layout
    return pid


def columns(pid, *cols):
    """A title-less xAxis panel whose children are the given panels, each a
    column. A column that is a list of panels becomes its own stacked panel,
    named <pid>C<n>, declared BEFORE the container (rusEFI never forward-
    references a panel, and neither does this file)."""
    items = []
    for n, col in enumerate(cols, 1):
        if isinstance(col, (list, tuple)):
            sub = "%sC%d" % (pid, n)
            panel(sub, "", [c if isinstance(c, tuple) else P(c) for c in col])
            items.append(P(sub))
        else:
            items.append(col if isinstance(col, tuple) else P(col))
    return panel(pid, "", items, layout="xAxis")


def ipanel(pid, cols, items):
    IND_PANELS.append((pid, cols, items))
    return pid


def rpanel(pid, cols, gauges):
    READ_PANELS.append((pid, cols, [RO(g) for g in gauges]))
    return pid


# ==========================================================================
# 0. WHAT THE LINKED IMAGE DOES NOT READ.  (V89 UI, rusEFI alignment pass)
#
# the project rules: "A dead knob is allowed; a silent one is not." On V89 the
# question was asked of the WHOLE page, not only the DBW slots
# (tests/tunerstudio/me711_page_reader_audit.py). Every field below is named by no linked
# module except the page definition, the validator or the default seeder -
# including the rev limiter, idle control, closed-loop boost and the engine
# protections, all of which the previous interface offered as if they ran.
#
# The label says so (" (not used)" / " (checked, not used)") and the panel
# that holds it says why. me711_page_reader_audit.py --check holds this in
# BOTH directions against the image under test: a newly dead field fails, and
# so does a field listed here that the firmware has started to read - the
# label must then go, or the UI lies the other way.
#
# Dead fields that sat inside LIVE workflows (a fixed dwell beside the dwell
# curve, a pull-up beside an OEM transfer curve, per-cylinder channel indices
# beside the cavity routing) moved to Controller / Unused settings - rusEFI's
# own "parking lot" idea - so a live dialog shows only what the engine uses.
# Whole dead FEATURES (idle, closed-loop boost, rev limiter, protections,
# motorsport) stay where a rusEFI user looks for them, labelled.
# ==========================================================================
UNUSED = {
    # --- a whole feature this firmware does not have
    "boostFreqHz": "N75 runs at the 10 ms ASIC frame quantum",
    "lambda1Bank": "closed loop trims every cylinder from its sensor",
    "lambda1AuthPct": "the closed-loop limits are per region (Fuel menu)",
    "lambda1CylMask": "closed loop trims every cylinder from its sensor",
    "lambda2Bank": "closed loop trims every cylinder from its sensor",
    "lambda2AuthPct": "the closed-loop limits are per region (Fuel menu)",
    "lambda2CylMask": "closed loop trims every cylinder from its sensor",
    "pinMapSwitch": "no map switching exists",
    # B6 (V98): pins a dialog showed with no reader and no label
    "pinBaro": "the ambient sensor is on the ECU board (Tools > Barometric sensor)",
    "pinFlex": "no flex fuel input exists",
    "pinGenericAin": "no generic analog input exists yet",
    "pinGenericPwm": "no generic PWM output exists yet",
    "pinGenericOut": "no generic on/off output exists yet",
    "testPin": "the bench command itself selects the output",
    "pinVss": "no vehicle speed input is read",
    "trigDecoder": "selects which validation rules apply; the decoder is "
                   "configured by the wheel fields",
    # --- a dead scalar that sat beside the live thing that replaced it
    "revMin": "not read",
    "simRpm": "there is no trigger simulator in the ME7.1.1 build",
    "injChannel": "outputs are routed by cavity (Fuel > Injector Characteristics)",
    "ignChannel": "outputs are routed by cavity (Ignition hardware)",
    "dwellMsX100": "running dwell is the Ignition / Dwell curve",
    "injDeadtimeUs": "dead time is the curve in Fuel > Injector Characteristics",
    "cltPullupOhm": "the CLT sensor curve maps counts to temperature",
    "iatPullupOhm": "the IAT sensor curve maps counts to temperature",
    "injModeLegacy": "superseded by Injection mode",
    "injectorPreset": "not applied - enter the injector data directly",
    "coilPreset": "not applied",
    "mapSensorPreset": "not applied - enter offset and gradient directly",
    "pwmInvert": "the bridge polarity is a board fact (hctarget.h)",
    "cylBank": "no per-bank strategy reads it",
    "testMode": "the bench command itself selects the mode",
    "testTimeoutMs": "bench timing is clamped in code",
    "iatDefault": "an invalid IAT reads -40 C; each consumer has its own fallback",
    # 2026-10-12: the Bosch setting-range monitor (FR DLR 3.60, hcetbcal.c)
    # replaced the deviation supervisor on this ECU; its times are Bosch's.
    "dbwDevX10": "the Bosch setting-range monitor judges the output limit, "
                 "not a deviation",
    "dbwDevMs": "the Bosch setting-range monitor uses 0.6 s / 5 s",
    # 2026-10-12 (real TunerStudio): an ME7.5 HAL field - on this ECU the IAT
    # input is the routed cavity (pinIat); only a comment named it, and the
    # page reader audit counted that as a read.
    "iatChannel": "the intake air input is chosen by its pin",
}

# Housekeeping the validator or the page manager checks, shown on purpose in
# Controller and identity (which says nothing there changes how the engine
# runs), and the P3 persistence test byte, which exists to be edited.
UNUSED_EXEMPT = {"cfgVersion", "uMagic", "uSchema", "uGeneration", "uCrc",
                 "cfgFlags", "idlePad"}

# Classes the audit reports for a non-RUNTIME field -> the label suffix.
UNUSED_SUFFIX = {"VALIDATED": " (checked, not used)",
                 "NONE": " (not used)", "SEEDED": " (not used)"}
_UNUSED_CLASS: dict[str, str] = {}


def _unused_class(ts):
    """The audit's class for a field, computed once from the linked image.
    Falls back to NONE (the stronger wording) when the audit cannot run -
    the --check gate is what proves the wording, not this."""
    if not _UNUSED_CLASS:
        try:
            import me711_page_reader_audit as _A
            for fts, _m, cls, _w in _A.classify()[0]:
                _UNUSED_CLASS[fts] = cls
        except SystemExit:
            _UNUSED_CLASS["-"] = "NONE"
    return _UNUSED_CLASS.get(ts, "NONE")


# ------------------------------------------------------------------ ENGINE --
# V86: THE PRESET IS A CHOICE PLUS AN ACT, as in rusEFI's "Base Tunes"
# (Controller / Base Tunes, engineTypeDialog). Until V86 this panel offered
# the selector alone, and selecting a preset changed that one byte and
# nothing else.
panel("hcEnginePreset", "Engine base tune", [
    T("#Choose an engine, then press APPLY - choosing alone changes nothing."),
    T("#APPLY (engine stopped) writes the preset into the ordinary settings"),
    T("#and checks the whole configuration; if it would not be valid,"),
    T("#nothing is changed. APPLY does not Burn: review, then Burn."),
    F("enginePreset"),
    C("cmdApplyEnginePreset", "APPLY ENGINE PRESET"),
    T("Every value stays editable afterwards. If a dialog still shows old"),
    T("values, close and reopen it."),
    T("!Cylinder count, displacement and maximum engine speed take effect"),
    T("!after a Burn and a key cycle."),
])


panel("hcEngineFiring", "Odd-fire angles", [
    N("Firing order Custom only: TDC after cylinder 1"),
    E("tdcCylDegX10", "firingOrder == 0"),
])

panel("hcEngineFiringExt", "Cylinders 9..12", [
    T("Used with firing order Custom and more than 8 cylinders."),
    E("tdcCylExtDegX10", "firingOrder == 0"),
])

# -------------------------------------------------------------- PROTECTION --
# rusEFI limitsAndFallback. V93: the rev limiter is a FUEL CUT in the planner
# (hcsched_dry.c, rusEFI rpmHardLimit + cutFuelOnHardLimit): above revLimit
# every injector event is planned undriven, fuel returns 200 rpm below it.
panel("hcLimitsRev", "Rev limiter", [
    T("#Above the rev limit, cut fuel, spark or both - every injection or"),
    T("#spark - until the speed is back below the limit minus the hysteresis."),
    T("#0 = no limiter. Inactive while cranking."),
    F("revLimit"),
    F("revLimitHyst"),
    F("revlimMode"),
    T("#Soft limit: within the hysteresis band below the limit, timing"),
    T("#retard and added fuel ramp in. 0 = off."),
    F("revLimitSoftRetard"),
    F("revLimitSoftFuel"),
])

panel("hcLimitsProtect", "Engine protection", [
    T("#Each protection cuts fuel (Diagnostics > Why is fuel cut? says which)."),
    T("#Coolant over its limit: cut above the coolant rev limit (0 = 3000 rpm);"),
    T("#a failed coolant sensor is not judged. A latched throttle fault (DBW"),
    T("#on): cut above the throttle-fault rev limit (0 = 1500 rpm). Injector"),
    T("#duty over its limits: cut until below 20 %. Flood clear: no fuel"),
    T("#while cranking with the pedal floored (0 = off)."),
    F("cltMaxDegX10"),
    F("cltLimpRpm"),
    F("etbLimpRpm"),
    F("injDutyInstX10"),
    F("injDutySustX10"),
    F("injDutySustMs"),
    F("floodClearX10"),
])

panel("hcLimitsBoost", "Overboost cut", [
    T("#At this pressure fuel is cut and the boost valve closed until the"),
    T("#pressure falls by the hysteresis - also with boost control off (a"),
    T("#stuck wastegate overboosts with the valve closed). 0 = 220 / 15 kPa."),
    T("#Reads the pressure sensor; without a valid reading the valve stays"),
    T("#closed and pressure-loss protection applies."),
    F("boostCutKpa"),
    F("boostCutHyst"),
])

panel("hcProtPressure", "Pressure-loss protection", [
    T("#Cuts fuel under load when the pressure reading is missing or stale."),
    T("#Always active for Speed density and Boosted Alpha-N (which also get"),
    T("#no air without it); switch it on here for the other algorithms."),
    T("#Any pressure loss also closes the boost valve."),
    F("pressureGuardEnable"),
    F("pressureGuardRpm"),
    F("pressureGuardTps"),
])

panel("hcProtLean", "Lean protection", [
    T("#Cuts fuel when measured lambda stays leaner than target by the"),
    T("#margin, under load, for the set time. A cold, faulted or stale"),
    T("#wideband can neither trigger nor release it. Fuel returns once lambda"),
    T("#is back at target with the engine off load for the recovery time."),
    F("leanGuardEnable"),
    F("lambdaPhysicalQualified", None, "leanGuardEnable == 1"),
    F("leanGuardRpm", None, "leanGuardEnable == 1"),
    F("leanGuardTps", None, "leanGuardEnable == 1"),
    F("leanGuardCharge", None, "leanGuardEnable == 1"),
    F("leanGuardDeviation", None, "leanGuardEnable == 1"),
    F("leanGuardPersist", None, "leanGuardEnable == 1"),
    F("leanGuardRecovery", None, "leanGuardEnable == 1"),
    T("!Off by default. Enable only after the wideband reads correctly on"),
    T("!this engine - never test it by running the engine lean."),
])


rpanel("hcReadTrigger", 2, ["rpmGauge", "syncLossCountGauge", "toothCorrectionsGauge", "cycleSyncLostGauge"])

# V92: THE TOOTH PROFILE - a crank-angle reference that needs no timing
# light. hcsched_dry.c sums every synchronised tooth period per 6-degree bin;
# the vehicle logger reads the 60 bins and finds the slowest ones.
panel("hcToothProfile", "Tooth profile / compression TDC", [
    T("#Compression: engine stopped, key on. Press, then crank about 5 s."),
    T("#Spark and fuel are held off until the crank stops (or 30 s); the"),
    T("#slowest teeth are the compression TDCs (HaniCore vehicle logger)."),
    T("#Running: 64 revolutions, outputs untouched."),
    C("cmdToothLogCompression", "Compression profile (no spark/fuel)"),
    C("cmdToothLogRunning", "Running profile"),
    C("cmdToothLogAbort", "Abort"),
    P("hcPanelToothLog"),
])

ipanel("hcPanelToothLog", 1, [
    IND("toothLogResult == 3",
        "{ Tooth profile: bitStringValue(hcToothLogList, toothLogResult)}",
        "Tooth profile DONE - read it with the vehicle logger",
        "white, black, green, black"),
    IND("toothLogResult == 1", "Spark and fuel not held",
        "ARMED - CRANK NOW. SPARK AND FUEL ARE HELD OFF",
        "white, black, yellow, black"),
])


ipanel("hcPanelSeq", 2, [
    IND("cycleSync == 1", "CYCLE: NOT KNOWN (fallback)", "CYCLE: KNOWN",
        "white, black, green, black"),
    IND("seqActive == 1", "SEQUENTIAL: NOT ACTIVE (batch/wasted/fallback)",
        "SEQUENTIAL: ACTIVE", "white, black, green, black"),
])

rpanel("hcReadSeq", 4, ["syncStateGauge", "seqActiveGauge", "seqInjMaskGauge",
                        "injWidthUsGauge", "seqEntersGauge", "seqLeavesGauge",
                        "seqSkipsGauge", "injNoFreeGauge"])

panel("hcInjectorPins", "Injector outputs", [
    T("#The cavity that drives each CYLINDER's injector. The firing order"),
    T("#(Base engine) is separate: do not rearrange pins to match it."),
    T("!Injector 7 is cavity 24 and injector 8 cavity 19. Cavity 23 is the"),
    T("!main relay stage, not an injector."),
    E("injPin", "cylinders"),
])

# rusEFI puts the injector test in the injection-hardware dialog itself
# (injectionSettingsEast / testInjectors). The firmware's bench invariants
# are unchanged: rpm 0 and no crank edge, a valid page, the supervision link,
# a clamped pulse, a finite count, automatic release and ABORT.
_BENCH_NOTE = [
    T("#Engine stopped only. Ten bounded pulses, then it releases itself."),
    T("#A refused test says why: Controller / Bench state and refusals."),
]

panel("hcTestInjectors", "Injector test", _BENCH_NOTE + [
    C("cmdTestAbort", "ABORT"),
] + [C("cmdTestInj%d" % n, "Injector #%d" % n,
       None if n == 1 else "cylinders >= %d" % n) for n in range(1, 9)] + [
    P("hcPanelBenchState"),
])

panel("hcFuelEnrich", "Acceleration enrichment", [
    T("#A shot of fuel proportional to how fast the plate is opening,"),
    T("#decaying away. Scaled by the warm-up factor."),
    F("accelThreshX10"),
    F("accelGain"),
    F("accelDecayMs"),
])

panel("hcFuelOverrun", "Deceleration fuel cutoff (DFCO)", [
    T("#Cuts every injector on overrun: pedal (or throttle without DBW)"),
    T("#released, above the cut rpm, coolant warm, after the delay. Fuel"),
    T("#returns below the resume rpm or when the pedal is pressed. A failed"),
    T("#pedal, throttle, coolant or pressure sensor never cuts fuel."),
    T("#0 rpm = off. The pressure limit applies only to a manifold sensor."),
    F("overrunRpm"),
    F("overrunResume"),
    F("overrunTpsX10"),
    F("dfcoDelay"),
    F("dfcoMinClt"),
    F("dfcoMapMax"),
    T("#Timing retard while cut, ramped out after (soft re-entry)."),
    F("dfcoRetard"),
    F("dfcoRamp"),
])

rpanel("hcReadFuel", 2, ["RPMValueGauge", "fuelLoadGauge",
                         "mapControlGauge", "veValueGauge",
                         "targetLambdaGauge", "lambdaValueGauge",
                         "stftBank1Gauge", "fuelCorrectionGauge",
                         "airMassGauge", "injectorPulseWidthGauge"])


rpanel("hcReadStft", 2, ["stftBank1Gauge", "stftBank2Gauge",
                         "lambdaValueGauge", "lambda2ValueGauge",
                         "targetLambdaGauge", "stftStateLoGauge",
                         "stftRegionGauge", "RPMValueGauge"])

ipanel("hcPanelStft", 1, [
    IND("stftStateLo == 8", "{ Closed loop: bitStringValue(hcStftList, stftStateLo)}",
        "CLOSED LOOP CORRECTING", "white, black, green, black"),
])


# ---------------------------------------------------------------- IGNITION --
# 2026-10-11: spark mode and fixed timing are in hcSparkMain / hcSparkLocked
# (Speeduino "Spark Settings"), next to the window that uses them.

panel("hcIgnitionPins", "Ignition outputs", [
    T("#Physical connector cavities, one per cylinder number."),
    E("ignPin", "cylinders"),
])

panel("hcTestCoils", "Spark test", _BENCH_NOTE + [
    C("cmdTestAbort", "ABORT"),
] + [C("cmdTestCoil%d" % n, "Spark #%d" % n,
       None if n == 1 else "cylinders >= %d" % n) for n in range(1, 9)] + [
    P("hcPanelBenchState"),
])

# V98r2: the fast-block channels (the timing-light check reads these), not
# the raw-block duplicates and unranged scheduler internals.
rpanel("hcReadSpark", 2, ["RPMValueGauge", "ignitionTimingGauge",
                          "ignTableTimingGauge", "ignCorrectionGauge",
                          "coilDwellGauge", "VBattGauge"])

# ----------------------------------------------------------------- SENSORS --
# rusEFI cltSensor: settings West, gauges East. HaniCore's calibration is a
# counts->temperature CURVE, so the curve itself sits in the middle - the way
# rusEFI embeds cltFuelCorrCurve, fan1PwmCurve and 29 others in dialogs.
# 2026-10-11 (owner): PICK THE SENSOR, as Speeduino / rusEFI do. Every
# choice is a curve COMPUTED FOR THIS BOARD'S INPUT (ts_sensor_presets_me711:
# 2.61 k + the 340 R stage the board holds on, 38.3 k pull-down; checked
# against the ECU's own curve within ~1 C). The curve below stays editable.
import ts_sensor_presets_me711 as _SENS    # noqa: E402


def _temp_options(which, ax_name, val_name):
    out = []
    for label, ax, val in _SENS.temperature_options(which):
        sets = [("%s%d" % (ax_name, i + 1), a) for i, a in enumerate(ax)]
        sets += [("%s%d" % (val_name, i + 1), v) for i, v in enumerate(val)]
        out.append((label, sets))
    return out


panel("hcSensorClt", "Coolant temperature sensor", [
    T("#The curve maps raw ADC counts to temperature; the default is this"),
    T("#ECU's own OEM curve. An invalid input displays -40 C and sets the"),
    T("#coolant fault (P0115); fuel, ignition and idle then use their own"),
    T("#safe fallback values."),
    F("pinClt"),
    S("Common coolant sensors", _temp_options("clt", "cltSensAx",
                                              "cltSensVal")),
    T("Pick your sensor; the curve is filled for this ECU."),
    T("#This input's 340 R pull-up suits Bosch-type sensors: high-resistance"),
    T("#sensors (Ford, Chrysler) read coarsely below about 20 C."),
    P("hcPanelCltValid"),
])

ipanel("hcPanelCltValid", 1, [
    IND("cltError", "CLT OK", "CLT FAULT - reads -40 C",
        "white, black, red, black"),
])

panel("hcSensorIat", "Intake air temperature sensor", [
    T("#A raw-count to temperature curve, like coolant. An invalid input"),
    T("#displays -40 C and sets the intake air fault; the fuel model then"),
    T("#uses 0 C and the timing correction 0."),
    T("!AWT harness: the IAT signal must be moved to cavity 26."),
    F("pinIat"),
    S("Common air temperature sensors", _temp_options("iat", "iatSensAx",
                                                      "iatSensVal")),
    T("Pick your sensor; the curve is filled for this ECU."),
])

panel("hcSensorMap", "Pressure sensor", [
    T("#One external pressure sensor, manifold (MAP) or charge pressure."),
    T("#Where it measures is set in Fuel > Fuel model (Pressure sensor"),
    T("#location). Linear transfer: kPa = offset + counts x gradient / 1000,"),
    T("#5 V = 1024 counts."),
    T("!VAG 1.8T (AWT): cavity 101 is CHARGE pressure, before the throttle."),
    F("pinMap"),
    S("Common pressure sensors",
      [(lab, [("mapSensOff", _SENS.pressure_fields(p0, p5)[0]),
              ("mapSensGrd", _SENS.pressure_fields(p0, p5)[1])])
       for lab, p0, p5, _src in _SENS.PRESSURE_SENSORS]),
    F("mapSensOff", "Pressure at 0 V (0 counts)"),
    F("mapSensGrd", "Pressure rise per 1000 counts"),
    F("pressureMaxAge"),
])

panel("hcSensorBaro", "Ambient pressure", [
    T("#The ambient (barometric) pressure is ALWAYS the onboard sensor: on"),
    T("#the ECU board, read every 10 ms, with this ECU's own factory"),
    T("#calibration, valid 400..1200 hPa. Pure Alpha-N uses it for the air"),
    T("#density, Boosted Alpha-N for the blend and the boost gauge."),
    F("ambientMaxAge"),
    B(),
    T("#A missing or out-of-range reading holds the last good one for the"),
    T("#time above; only a sensor that never read valid uses the fault"),
    T("#value in Fuel > Fuel model (shown as AMBIENT FALLBACK)."),
])

panel("hcSensorBattery", "Battery", [
    T("#Full scale is the battery voltage that reads 1023 counts, i.e. the"),
    T("#divider ratio times the ADC reference."),
    F("adcBattFsDv"),
    F("pinVbat"),
])

panel("hcSensorMisc", "Mass air flow input", [
    F("pinMaf"),
    T("Optional and read for diagnostics only: the fuel model does not use"),
    T("a MAF, and an absent or failed one never affects fuelling."),
])

# 2026-10-12 (real TunerStudio, 2560 px screen): a gauge column EAST of the
# curve was clipped - the dialog opened narrower than its content (horizontal
# scrollbar, "Clt raw asi..."), and still did with the settings WEST of the
# curve: settings on top, the curve in the middle, the gauges in a row under it.
rpanel("hcReadClt", 3, ["coolantGauge", "cltCtrlDcGauge", "cltRawAsicGauge"])
rpanel("hcReadIat", 2, ["intakeGauge", "iatRawAsicGauge"])
rpanel("hcReadMap", 2, ["mapKpaX10Gauge", "engLoadGauge", "rlX10Gauge"])
rpanel("hcReadBaro", 2, ["ambientUsedGauge", "ambientPressureGauge"])

rpanel("hcReadBattery", 2, ["battDvGauge", "batteryGauge", "adc05_UBATGauge"])
rpanel("hcReadNvm", 2, ["nvmGenerationGauge", "nvmCommitsGauge",
                        "nvmAttemptsGauge", "ramProbeSeedGauge",
                        "ramProbeResultGauge"])
# The wideband state beside the wideband setup (it was only in Diagnostics).
# V97: both banks the same, left column bank 1, right column bank 2.
rpanel("hcReadLambda", 2, ["lambda1X1000Gauge", "lambda2X1000Gauge", "heater1StateGauge", "heater2StateGauge"])

# V97: per bank, in words - why lambda is withheld, the latched fault, the
# heater, and whether the CJ120 answers (rusEFI's wideband status texts).
ipanel("hcPanelLambda", 2, [
    IND("lam1Why == 0", "{ B1: bitStringValue(hcLamWhyList, lam1Why)}",
        "B1: LAMBDA VALID", "white, black, green, black"),
    # Passive variation is advisory; validity comes from acquisition/lifecycle.
    IND("lamDyn & 1", "B1: QUIET (ADVISORY)", "B1: VARIATION OBSERVED",
        "white, black, green, black"),
    IND("lamDyn & 2", "B2: QUIET (ADVISORY)", "B2: VARIATION OBSERVED",
        "white, black, green, black"),
    IND("lam2Why == 0", "{ B2: bitStringValue(hcLamWhyList, lam2Why)}",
        "B2: LAMBDA VALID", "white, black, green, black"),
    IND("lam1Fault != 0", "B1: NO FAULT",
        "{ B1: bitStringValue(hcLamFaultList, lam1Fault)}",
        "white, black, red, black"),
    IND("lam2Fault != 0", "B2: NO FAULT",
        "{ B2: bitStringValue(hcLamFaultList, lam2Fault)}",
        "white, black, red, black"),
    IND("heater1State >= 2 && heater1State <= 5",
        "{ B1 HEATER: bitStringValue(hcLamHeaterList, heater1State)}",
        "{ B1 HEATER: bitStringValue(hcLamHeaterList, heater1State)}",
        "white, black, yellow, black"),
    IND("heater2State >= 2 && heater2State <= 5",
        "{ B2 HEATER: bitStringValue(hcLamHeaterList, heater2State)}",
        "{ B2 HEATER: bitStringValue(hcLamHeaterList, heater2State)}",
        "white, black, yellow, black"),
    IND("cj1Ok == 1", "CONTROLLER 1: NOT VERIFIED", "Controller 1: answering",
        "white, black, green, black"),
    IND("cj2Ok == 1", "CONTROLLER 2: NOT VERIFIED", "Controller 2: answering",
        "white, black, green, black"),
])
rpanel("hcReadLambdaLink", 2, ["cj1ErrGauge", "cj2ErrGauge",
                               "cj1TmoGauge", "cj2TmoGauge",
                               "asicSampleAgeMsGauge", "tpsSampleAgeMsGauge",
                               "lamAcqFlagsGauge", "lamAckModesGauge"])
panel("hcLambdaRight", "", [
    P("hcPanelLambda"),
    P("hcReadLambda"),
])

# ------------------------------------------------------------------ LAMBDA --
panel("hcLambdaStrategy", "Wideband O2 (on-board controllers)", [
    T("#Two Bosch LSU controllers on the ECU board. Measured lambda feeds"),
    T("#closed loop fuel correction and VE Analyze only while the sensor is"),
    T("#READY (heated, pump current on, calibration clean). Lambda 0 means"),
    T("#'no measurement', never 'rich'."),
    T("#Bank 1: cavities 70/51/71/52, heater 5 (an AWT LSU plugs straight in)."),
    F("lambda1Source"),
    F("pinLambda1"),
    B(),
    T("#Heater: check that the sensor's heater feed (H+) is live before"),
    T("#choosing. Disabled never heats; 'ignition on' needs key on; 'engine"),
    T("#running' also needs a running engine and keeps 30 s after a stop."),
    F("lambdaHeatPolicy"),
    T("!Heating a fitted sensor is not yet vehicle-qualified on this ECU."),
    B(),
    F("lambda2Source"),
    F("pinLambda2"),
])

# --------------------------------------------------------------- THROTTLE --
# rusEFI etbDialog: "Base ETB settings", "ETB Jam detection", PID, and the
# ETB bench test in the SAME dialog. TPS and pedal calibration are Sensors.
panel("hcEtbBase", "Base ETB settings", [
    T("#Enable only after AutoCal ETB has passed and the pedal is"),
    T("#calibrated (Tools > Calibrate pedal sensor)."),
    F("dbwEnable"),
    F("dbwMinX10", None, "dbwEnable == 1"),
    F("dbwMaxX10", None, "dbwEnable == 1"),
    F("dbwRateX10", None, "dbwEnable == 1"),
    F("dbwDeadbandX10", None, "dbwEnable == 1"),
    F("dbwFrictionX10"),
    F("dbwMaxDutyX10", None, "dbwEnable == 1"),
    F("dbwMotorDir", None, "dbwEnable == 1"),
    F("dbwBattComp"),
    # NOT gated on dbwEnable: the commissioning procedures own the bridge with
    # dbwEnable 0, so the frequency has to be settable before the throttle is
    # ever enabled - and it is a property of the body, not of this ECU.
    F("dbwPwmHz"),
    T("#2000 Hz is this ECU's factory value. Re-run ETB Characterization"),
    T("#after changing it: the bias curve is valid only at the frequency it"),
    T("#was measured at."),
])

panel("hcEtbPid", "PID settings", [
    T("#Units %/%, %/%/s and %.s/% - or let PID Autotune find them."),
    F("dbwKp"),
    F("dbwKi"),
    F("dbwKd"),
    T("Feed-forward: ETB > Characterization details and bias curve."),
])

panel("hcEtbSafety", "ETB jam / deviation detection", [
    T("#Stuck plate (Bosch): output at its limit 0.6 s = fuel cut above"),
    T("#the limp rpm, 5 s = throttle fault. Bridge flag: stage restarted."),
    T("#A pedal/TPS range or pair error must persist this long before it"),
    T("#latches (the output is held meanwhile). Key-on clears a latch."),
    F("dbwFaultDebounceMs"),
    F("dbwSfMode"),
    T("#Both throttle tracks failed (DBW on): the motor is off and the fuel"),
    T("#model assumes this spring opening."),
    F("dbwLimpX10"),
    T("#Throttle rev limit: above the start the target tapers to closed."),
    F("dbwRevlimRpm"),
    F("dbwRevlimRange"),
])

panel("hcEtbNudge", "ETB bench test", [
    T("#Engine stopped, throttle tracks agreeing, driver fault-free - or it"),
    T("#refuses. Three nudges of at most 50 ms; it stops on a bridge fault,"),
    T("#the plate leaving a fixed band, or the tracks disagreeing. Watch"),
    T("#which way the plate moves."),
    C("cmdTestAbort", "ABORT"),
    C("cmdTestDbwA", "Throttle bridge, direction A"),
    C("cmdTestDbwB", "Throttle bridge, direction B"),
    P("hcPanelBenchState"),
    T("#A refused test lights the reason below - every unmet one at once."),
    P("hcPanelBenchRefuse"),
])

panel("hcEtbTpsCal", "TPS calibration", [
    T("#Closed goes in MIN and open in MAX, not sorted: on a Bosch/VAG body"),
    T("#the first track falls as the plate opens, so min > max is correct."),
    F("pinTps1"),
    F("tps1Min"),
    F("tps1Max"),
    F("pinTps2"),
    F("tps2Min"),
    F("tps2Max"),
    B(),
    T("#Hold the plate at the stop and press. Both tracks are captured"),
    T("#together, in RAM - Burn to keep them."),
    C("cmdGrabTpsClosed", "Grab Closed Throttle"),
    C("cmdGrabTpsOpen", "Grab Fully Opened Throttle"),
    B(),
    T("#Each track reads 0 % closed and 100 % open whichever way its voltage"),
    T("#runs, so after both Grabs the correlation is Same."),
    F("tpsCorrelation"),
    F("tpsTolX10"),
])

panel("hcEtbAppCal", "Pedal position sensor", [
    T("#Released goes in MIN, floored in MAX, as for the throttle. Each Grab"),
    T("#reads both tracks and sets the correlation to Same (a VAG pedal's"),
    T("#second track reads about half of the first)."),
    F("pinApp1"),
    F("pedal1Min"),
    F("pedal1Max"),
    F("pinApp2"),
    F("pedal2Min"),
    F("pedal2Max"),
    B(),
    T("#Release the pedal completely, then Grab Released. Press it fully,"),
    T("#hold it, then Grab Full Pedal. In RAM - Burn to keep."),
    C("cmdGrabAppRest", "Grab Released"),
    C("cmdGrabAppFull", "Grab Full Pedal"),
    B(),
    F("appCorrelation"),
    F("appTolX10"),
])

# V93: THE ONE COMMISSIONING AREA. rusEFI splits autocal (TPS) and autotune
# (ETB); for commissioning they are one act, so this dialog runs both in
# order ('!C3': AutoCal -> validate -> PID autotune -> validate) and keeps
# each one separately callable. Status texts are SHORT (the car test showed
# long sentences unreadable in the indicator width); the explanations are
# in the help topic and in tools/vehicle/me711_dbw_vehicle_test.py's output.
# V97 (2026-09-30): ONE throttle workflow. The buttons live ONLY in the main
# dialog (Advanced > Electronic Throttle Body); this is its diagnostics page
# - the run's status, phase-by-phase values and the AutoCal settings.
panel("hcEtbCommission", "ETB AutoCal results", [
    T("#Run it from Advanced > Electronic Throttle Body (AutoCal ETB)."),
    T("#AutoCal ETB = TPS endpoints -> PID autotune -> verify: the closed"),
    T("#loop steps 20-60-20-4-15 %; each must settle within 2 % in 350 ms,"),
    T("#overshoot < 5 %, hold within 1.5 %."),
    P("hcPanelEtbCal"),
    B(),
    T("#AutoCal settings"),
    F("dbwAutocalDuty"),
    F("dbwAutocalMs"),
    F("dbwTuneAmp"),
])

rpanel("hcReadEtbCal", 3, ["etbCalRest1Gauge", "etbCalA1Gauge",
                           "etbCalB1Gauge", "etbCalRest2Gauge",
                           "etbCalA2Gauge", "etbCalB2Gauge",
                           "etbCalDetailGauge", "etbDriveDutyX10Gauge",
                           "etbPhaseMsGauge",
                           # Bounded capture diagnostics
                           "etbHold1Gauge", "etbStopDispGauge", "etbHoldMsGauge"])

# V92 rusEFI's ETB autotune (relay / Astrom-Hagglund); V93 live telemetry.
# rusEFI etbDialogRight: etbTps1Calib ("First step: calibrate TPS") and
# etbAutotune ("Second step: calibrate PID") sit INSIDE the ETB dialog.
# HaniCore's one button runs both and then verifies the closed loop.
panel("hcEtbAutotune", "AutoCal ETB", [
    T("#Engine OFF, key ON, hands and feet off. DBW stays disabled."),
    T("#AutoCal ETB: TPS endpoints -> PID autotune -> verify, in one go."),
    T("#Results go to RAM only - review, then Burn to keep them."),
    C("cmdEtbCommission", "AutoCal ETB"),
    C("cmdEtbAutoCal", "Calibrate TPS endpoints"),
    C("cmdEtbAutoTune", "PID Autotune"),
    C("cmdEtbAutoCalAbort", "Abort"),
    P("hcPanelEtbCal"),
    T("Details of a run: Advanced > ETB AutoCal / Diagnostics."),
])

# the live values a throttle setup is judged by, in one place
# 2026-10-12 (real TunerStudio): the fast-block channels, not the "(raw
# block)" duplicates; no bare "Dbw state" number (the status lines say it).
rpanel("hcReadEtbLive", 2, ["TPSValueGauge", "tps2X10Gauge",
                            "pedalX10Gauge", "pedal2X10Gauge",
                            "etbTargetGauge", "etbActualGauge",
                            "dbwDutyX10Gauge"])

rpanel("hcReadEtbTune", 3, ["etbTuneCyclesGauge", "etbTuneAmpLiveX10Gauge",
                            "etbTuneTuLiveMsGauge", "etbTuneKpGauge",
                            "etbTuneKiGauge", "etbTuneKdGauge",
                            "etbTuneAmpX10Gauge", "etbTuneTuMsGauge",
                            "etbCalDetailGauge"])

rpanel("hcReadEtbBridge", 3, ["tps1RawGauge", "tps2RawGauge",
                              "dbwSfLevelGauge", "dbwStateGauge",
                              "dbwFaultsGauge", "battDvGauge"])

rpanel("hcReadEtbVerify", 4, ["etbVfySettleMsGauge", "etbVfyOverX10Gauge",
                              "etbVfyErrX10Gauge", "etbVfyStepGauge"])

panel("hcEtbCommissionRight", "", [
    T("#Controller terms: P, I, D, feed-forward, sum, battery factor"),
    P("hcReadDbwTerms"),
    T("#Verify (worst of five steps): settle ms, overshoot, offset, step"),
    P("hcReadEtbVerify"),
    LG("hcEtbVerifyGraph", "Throttle: target vs actual", "South",
       ["dbwTargetX10", "dbwActualX10", "dbwDutyX10"]),
    T("#Endpoints (raw counts): rest, end A, end B per track; detail"),
    P("hcReadEtbCal"),
    T("#PID autotune: cycles, live amplitude / Tu, candidate then final gains"),
    P("hcReadEtbTune"),
    T("#Bridge and tracks"),
    P("hcReadEtbBridge"),
])

# SHORT primary texts: what runs, which phase, PASS / FAIL + short reason.
ipanel("hcPanelEtbCal", 1, [
    IND("etbCalResult == 1", "ETB: IDLE",
        "{ bitStringValue(hcEtbPhaseList, etbCalPhase)}",
        "white, black, yellow, black"),
    IND("etbCalResult == 5", "AUTOCAL ETB: -",
        "AUTOCAL ETB: PASS", "white, black, green, black"),
    IND("etbCalResult == 2", "TPS ENDPOINTS: -",
        "TPS ENDPOINTS: PASS", "white, black, green, black"),
    IND("etbCalResult == 4", "PID TUNE: -",
        "PID TUNE: PASS", "white, black, green, black"),
    IND("etbCalResult == 3", "NO FAILURE",
        "{ FAIL: bitStringValue(hcEtbWhyList, etbCalWhy)}",
        "white, black, red, black"),
    IND("etbCalResult == 3 && etbFailPhase > 0", "-",
        "{ IN: bitStringValue(hcEtbPhaseList, etbFailPhase)}",
        "white, black, red, black"),
    IND("etbCalResult == 3 && etbEndpointsOk == 1", "-",
        "ENDPOINTS OK (RAM), PID FAIL", "white, black, yellow, black"),
    IND("etbCalResult == 4 && etbCalDetail >= 32768", "-",
        "KI LIMITED (PAGE MAX)", "white, black, yellow, black"),
    IND("etbCalResult == 5 && etbCalDetail >= 32768", "-",
        "KI LIMITED (PAGE MAX)", "white, black, yellow, black"),
    IND("etbCalResult == 2 || etbCalResult == 4 || etbCalResult == 5", "-",
        "BURN TO KEEP", "white, black, yellow, black"),
])

rpanel("hcReadThrottle", 2, ["dbwStateGauge", "dbwErrorX10Gauge",
                             "dbwTargetX10Gauge", "dbwActualX10Gauge",
                             "dbwDutyX10Gauge", "dbwSfLevelGauge"])
# V97: WHY the duty is what it is - rusEFI's etb PID readouts (P/I/D terms,
# feed-forward) plus the battery factor and the sensor-fault debounce.
rpanel("hcReadDbwTerms", 4, ["dbwTermPGauge", "dbwIntegGauge",
                             "dbwTermDGauge", "dbwTermFfGauge",
                             "dbwOutRawGauge", "dbwBattFactorGauge",
                             "dbwPendFaultsGauge", "dbwFaultClearsGauge"])
rpanel("hcReadTps", 2, ["tpsX10Gauge", "tps2X10Gauge", "tps1RawGauge", "tps2RawGauge"])
rpanel("hcReadApp", 2, ["pedalX10Gauge", "pedal2X10Gauge", "app1RawGauge", "app2RawGauge"])


rpanel("hcReadIdle", 2, ["rpmGauge", "idleTargetRpmGauge",
                         "idleFloorX10Gauge", "idleTrimX10Gauge"])

ipanel("hcIdleState", 2, [
    IND("idleClosedLoop", "Idle loop open", "IDLE CLOSED LOOP",
        "white, black, green, black"),
    IND("idleDashpot", "No dashpot", "DASHPOT (release)",
        "white, black, yellow, black"),
    IND("idleTrimHeld", "Trim free", "TRIM HELD (pedal/coast)",
        "white, black, yellow, black"),
    IND("idleTrimLimit", "Trim in range", "TRIM AT LIMIT",
        "white, black, red, black"),
])


rpanel("hcReadIdleTiming", 2, ["rpmGauge", "idleTargetRpmGauge",
                               "idleTimingX10Gauge", "ignCorrX10Gauge"])


rpanel("hcReadBoost", 2, ["boostTargetX10Gauge", "boostReqX10Gauge",
                          "mapKpaX10Gauge", "boostOpenX10Gauge",
                          "boostPX10Gauge", "boostIX10Gauge",
                          "boostDX10Gauge", "boostMode_Gauge",
                          "boostFuelCutGauge", "boostCutsGauge"])

# ----------------------------------------------------------------- OUTPUTS --
# rusEFI outputsDialog: "Main relay output" and "Fuel Pump", each with its
# own Test button, beside the other outputs. One dialog, not three.
panel("hcOutMainRelay", "Main relay output", [
    T("#Auto requests the main relay whenever the ECU runs. Cavity 23 is"),
    T("#the ECU's own relay stage: it closes with the key and holds for the"),
    T("#release delay after key-off; only Auto is valid there. Another relay"),
    T("#cavity (65) is a low-side sink: coil from switched +12 V to the pin."),
    F("mainRelayModeCfg"),
    F("pinMainRelay"),
    F("mainRelayGraceMs"),
    F("mainRelayHoldMs"),
    T("The test drives cavity 65 only; on 23 the relay follows the key."),
    C("cmdTestRelay", "Test Main Relay"),
    P("hcPanelRelay"),
])


panel("hcOutMisc", "Cam solenoid outputs", [
    F("pinCam1Sol"),
    F("pinCam2Sol"),
    B(),
    T("#Test: three 250 Hz bursts at 50 %, engine stopped."),
    C("cmdTestAbort", "ABORT"),
    C("cmdTestVvt1", "Test cam solenoid, cavity 115"),
    C("cmdTestVvt2", "Test cam solenoid, cavity 120"),
    P("hcPanelBenchState"),
])

# ------------------------------------------------------------- MOTORSPORT --
# V98: rusEFI launch_control / shift_torque_reduction / antilag_system /
# rotational idle. Every function OFF by default; each needs its switch
# (cavity 86/87 when no cam uses it) or, without one, its pedal condition.
panel("hcMsLaunch", "Launch control", [
    T("#Standing start: held at the launch rpm by a spark cut that ramps"),
    T("#in across the window below it, timing set to the launch value"),
    T("#(0 = unchanged), fuel added. Needs the launch input ON and the"),
    T("#pedal above the threshold; no input selected = never armed."),
    BV("launchEnable"),
    F("pinLaunch", None, "launchEnable == 1"),
    BV("launchSwitchHigh", "launchEnable == 1 && pinLaunch != 255"),
    F("launchRpm", None, "launchEnable == 1"),
    F("launchWindow", None, "launchEnable == 1"),
    F("launchTps", None, "launchEnable == 1"),
    F("launchCutStart", None, "launchEnable == 1"),
    F("launchCutEnd", None, "launchEnable == 1"),
    F("launchRetardDegX10", None, "launchEnable == 1"),
    F("launchFuelAdd", None, "launchEnable == 1"),
])

panel("hcMsFlat", "Flat shift", [
    T("#Shift without lifting: switch (clutch) pressed above the rpm with"),
    T("#the pedal above the threshold -> spark cut + timing for the cut time."),
    BV("flatShiftEnable"),
    F("pinFlatShift", None, "flatShiftEnable == 1"),
    BV("flatShiftSwitchHigh", "flatShiftEnable == 1 && pinFlatShift != 255"),
    F("flatShiftArmRpm", None, "flatShiftEnable == 1"),
    F("flatShiftTps", None, "flatShiftEnable == 1"),
    F("flatShiftCutMs", None, "flatShiftEnable == 1"),
    F("flatShiftCutPct", None, "flatShiftEnable == 1"),
    F("flatShiftTimingX10", None, "flatShiftEnable == 1"),
])

panel("hcMsAls", "Anti-lag", [
    T("!Anti-lag burns fuel in the exhaust: turbo, manifold and catalyst"),
    T("!damage. Track use only, bounded by time, rpm and coolant."),
    BV("antiLagEnable"),
    F("pinAntiLag", None, "antiLagEnable == 1"),
    BV("antiLagSwitchHigh", "antiLagEnable == 1 && pinAntiLag != 255"),
    F("alsRpmMin", None, "antiLagEnable == 1"),
    F("alsRpmMax", None, "antiLagEnable == 1"),
    F("alsTpsMax", None, "antiLagEnable == 1"),
    F("alsCltMin", None, "antiLagEnable == 1"),
    F("alsCltMax", None, "antiLagEnable == 1"),
    F("alsMaxTime", None, "antiLagEnable == 1"),
    F("antiLagRetardDegX10", None, "antiLagEnable == 1"),
    F("antiLagFuelPct", None, "antiLagEnable == 1"),
    F("alsCutPct", None, "antiLagEnable == 1"),
    F("alsThrottle", None, "antiLagEnable == 1"),
])

panel("hcMsPit", "Pit limiter / rotational idle", [
    T("#Pit limiter: with its switch active the rev limit drops to the pit"),
    T("#rpm (the rev limiter's cut and hysteresis)."),
    BV("pitLimiterEnable"),
    F("pinPitLimiter", None, "pitLimiterEnable == 1"),
    BV("pitSwitchHigh", "pitLimiterEnable == 1 && pinPitLimiter != 255"),
    F("pitLimiterRpm", None, "pitLimiterEnable == 1"),
    B(),
    T("#Rotational idle: a spark cut at idle (pedal released, below the"),
    T("#rpm) - the motorsport idle sound. Off for road use."),
    BV("rotIdleEnable"),
    F("rotIdleRpm", None, "rotIdleEnable == 1"),
    F("rotIdleTps", None, "rotIdleEnable == 1"),
    F("rotIdleCut", None, "rotIdleEnable == 1"),
])

rpanel("hcReadMs", 2, ["RPMValueGauge", "pedalPositionGauge",
                       "sparkCutPctGauge", "revLimitNowGauge",
                       "ignitionTimingGauge", "fuelCorrectionGauge"])

# V98r2: COMMISSIONING - every switch input's raw pin level (switchRaw, bit
# order = hw_descriptors.SWITCH_INPUTS) and each function's debounced,
# polarity-applied state (motorsportState bits 12..15). Toggle a wire and
# watch both.
import hw_descriptors as _HW            # noqa: E402
ipanel("hcPanelSwitchRaw", 2, [
    IND("(switchRaw & %d) > 0" % (1 << i), "%d %s: low" % (c, _HW.SWITCH_INPUTS[c][2]
                                                         .replace(" input", "")),
        "%d %s: HIGH" % (c, _HW.SWITCH_INPUTS[c][2].replace(" input", "")),
        "white, black, green, black")         # a level, not a fault
    for i, c in enumerate(_HW.SWITCH_INPUTS)
] + [
    IND("(switchRaw & 32768) > 0", "Switch inputs readable",
        "SWITCH INPUTS UNREADABLE (board link down)", "white, black, red, black"),
    IND("(motorsportState & 4096) > 0", "Launch input off", "LAUNCH INPUT ON"),
    IND("(motorsportState & 8192) > 0", "Flat shift input off",
        "FLAT SHIFT INPUT ON"),
    IND("(motorsportState & 16384) > 0", "Anti-lag input off",
        "ANTI-LAG INPUT ON"),
    IND("(motorsportState & 32768) > 0", "Pit limiter input off",
        "PIT LIMITER INPUT ON"),
])

panel("hcMotorsport", "", [
    N("Switch inputs: pick the cavity; each entry names its polarity."),
])

# ------------------------------------------------------------- CONTROLLER --
panel("hcCtrlIdent", "Controller", [
    T("Identity and housekeeping. Nothing here changes how the engine runs."),
    F("cfgVersion"),
    F("uMagic"),
    F("uSchema"),
    F("uGeneration"),
    F("uCrc"),
    F("cfgFlags"),
])

panel("hcCtrlS5500", "I/O chip analog window", [
    T("#Developer use only. Which 16 words of the I/O chip frame the ECU"),
    T("#reads as analog inputs. Must be 4 for normal operation (coolant,"),
    T("#intake air, ambient pressure and wideband all depend on it)."),
    T("#s5500Idx = 65535: all sixteen words carry their own channel."),
    F("s5500WindowBase"),
])

panel("hcNvmTest", "Persistence test byte", [
    T("#A byte nothing in the engine reads: change it, Burn, power-cycle"),
    T("#the ECU and read it back to check calibration storage."),
    F("idlePad", "Persistence test byte"),
])

panel("hcCtrlBenchValues", "Bench test parameters", [
    T("#The pulse the bench tests ask for. The firmware clamps it, so no"),
    T("#value here can energise an output continuously."),
    F("testValue"),
])

# Controller / Unused settings - the dead scalars that sat inside live
# workflows. Each label ends "(not used)"; the gate holds that true.
panel("hcUnusedEngine", "Engine and trigger", [
    F("revMin"),
    F("simRpm"),
    F("trigDecoder"),
    E("cylBank", "cylinders"),
    F("dbwDevX10"),
    F("dbwDevMs"),
])

panel("hcUnusedFuel", "Fuel and sensors", [
    F("injectorPreset"),
    F("injDeadtimeUs"),
    F("injModeLegacy"),
    F("mapSensorPreset"),
    F("cltPullupOhm"),
    F("iatPullupOhm"),
    F("iatDefault"),
    F("iatChannel"),
    F("boostFreqHz"),
    F("lambda1Bank"),
    F("lambda1CylMask"),
    F("lambda1AuthPct"),
    F("lambda2Bank"),
    F("lambda2CylMask"),
    F("lambda2AuthPct"),
])

panel("hcUnusedIgn", "Ignition, throttle, bench", [
    F("coilPreset"),
    F("dwellMsX100"),
    F("pwmInvert", None, "dbwEnable == 1"),
    F("testMode"),
    F("testTimeoutMs"),
])

panel("hcUnusedChannels", "Per-cylinder channel indices", [
    T("Outputs are routed by CAVITY (Injection / Ignition hardware)."),
    E("injChannel", "cylinders"),
    E("ignChannel", "cylinders"),
])


# ==========================================================================
# 2. INDICATOR PANELS.
#
# ONE INDICATOR PER BIT for a bitmask - bitStringValue() INDEXES a list, and a
# mask of 0x0005 is not "state 5". Two faults can be true at once, which a
# single decoded string cannot show.
# ==========================================================================
GREEN = "white, black, green, black"
RED = "white, black, red, black"
YELLOW = "white, black, yellow, black"

# V98r2: the throttle-keyed table axis warnings (hc_validation.h
# HC_WARN_VE/IGN/LAM_AXIS in cfgWarnings) - beside the fuel strategy and in
# the status overview. NOT inside the table editors: an indicator there
# rendered as a full-width white banner above the grid (real TunerStudio).
ipanel("hcPanelTableAxes", 1, [
    IND("(cfgWarnings & 1024) != 0", "VE load axis fits the fuel model",
        "VE LOAD AXIS OUTSIDE 0..100 % THROTTLE", RED),
    IND("(cfgWarnings & 2048) != 0", "Ignition load axis fits",
        "IGNITION LOAD AXIS OUTSIDE 0..100 % THROTTLE", RED),
    IND("(cfgWarnings & 4096) != 0", "Lambda load axis fits",
        "LAMBDA LOAD AXIS OUTSIDE 0..100 % THROTTLE", RED),
])

ipanel("hcPanelOverview", 2, [
    IND("crankSync", "NO CRANK SYNC", "Crank synchronized", GREEN),
    IND("cfgValidation != 0 && cfgFirstBadSlot < 1024",
        "Configuration accepted",
        "{ REFUSED: bitStringValue(hcCfgFieldList, cfgFirstBadSlot)}", RED),
    IND("cycleSync", "ENGINE PHASE UNKNOWN", "Engine phase known", GREEN),
    IND("sensorsValid", "SENSOR FAULT PRESENT", "All sensors valid", GREEN),
    IND("dbwFaults == 0", "THROTTLE FAULT", "Throttle OK", GREEN),
    IND("fuelCut == 0", "FUEL CUT ACTIVE", "Fuel enabled", GREEN),
    IND("outputsPermitted", "OUTPUTS INHIBITED", "Outputs permitted", GREEN),
    IND("nvmNonVolatile", "TUNE NOT IN FLASH", "Tune stored in flash", GREEN),
    IND("nvmErrorFree", "PERSISTENCE ERROR", "Storage OK", GREEN),
])

ipanel("hcPanelTrigger", 2, [
    IND("crankSync", "NO CRANK SYNC", "Crank synchronized", GREEN),
    IND("cycleSync", "ENGINE PHASE UNKNOWN", "Engine phase known", GREEN),
    IND("camError", "Cam OK", "CAM FAULT", RED),
    IND("noSync", "Sync held", "NO SYNC", RED),
    IND("crankGapPending", "No gap candidate", "GAP CANDIDATE", YELLOW),
    IND("syncState != 0", "NO SYNC AT ALL",
        "{ Sync: bitStringValue(hcTrgStateList, syncState)}", GREEN),
    IND("syncLossReason == 0",
        "{ Last loss: bitStringValue(hcSyncLossList, syncLossReason)}",
        "No sync loss recorded", GREEN),
])

ipanel("hcPanelPreset", 1, [
    IND("presetVerdict == 1",
        "{ Last preset: bitStringValue(hcPresetList, presetVerdict)}",
        "Last preset APPLIED - review the fields, then Burn", GREEN),
    IND("nvmNotBurned", "Page matches flash",
        "CHANGES ARE LIVE BUT NOT BURNED", YELLOW),
])

ipanel("hcPanelGrab", 1, [
    IND("(grabVerdict == 1) || (grabVerdict == 7)",
        "{ Last grab: bitStringValue(hcGrabList, grabVerdict)}",
        "{ Last grab: bitStringValue(hcGrabList, grabVerdict)}", GREEN),
    IND("nvmNotBurned", "Page matches flash",
        "GRABBED VALUES ARE LIVE BUT NOT BURNED", YELLOW),
])

ipanel("hcPanelBaro", 1, [
    IND("(tickMs & 512) != 0",
        "{ In use: bitStringValue(hcAmbientSrcList, ambientProvenance)}",
        "{ In use: bitStringValue(hcAmbientSrcList, ambientProvenance)}",
        "white, black, white, black"),
    IND("ambientFallback", "Selected source valid",
        "FALLBACK: reference pressure in use", YELLOW),
    IND("baroPlausible", "ONBOARD SENSOR AT A RAIL - no measurement",
        "Onboard sensor in range", GREEN),
    IND("baroWindowOk", "I/O CHIP WINDOW MOVED - sensor not readable",
        "Onboard sensor readable", GREEN),
])

# What the fuel model is, in words, beside the settings that make it. The
# three cfg* channels are expressions over the PAGE (gen_ts_ini_me711
# DERIVED_CH, Speeduino's `strokeMultipler = { twoStroke == 1 ? 1 : 2 }`);
# the clock is the repaint trigger (the hcEtbCharacterizeDiagnosis idiom).
ipanel("hcPanelLoadSummary", 1, [
    IND("(tickMs & 512) != 0", label, label, "white, black, white, black")
    for label in (
        "{ Fuel model: bitStringValue(hcFuelModelList, cfgFuelModel)}",
        "{ VE table axis: bitStringValue(hcLoadAxisList, cfgVeAxisKind)}",
        "{ Air density from: bitStringValue(hcDensityList, cfgDensityKind)}",
    )
])

ipanel("hcPanelLoadState", 1, [
    IND("cfgValidation != 0 && cfgFirstBadSlot < 1024",
        "Configuration accepted",
        "{ REFUSED: bitStringValue(hcCfgFieldList, cfgFirstBadSlot)}", RED),
    IND("(loadFlags & 1) != 0", "Fuel model settings consistent",
        "FUEL MODEL SETTINGS INVALID - fuel cut", RED),
    IND("(loadFlags & 2) != 0", "Fuel model pressure valid",
        "PRESSURE READING LOST", RED),
    IND("ambientFallback", "Ambient source valid",
        "AMBIENT: REFERENCE FALLBACK", YELLOW),
    IND("iatDensityFallback", "Intake temperature used",
        "INTAKE TEMPERATURE: FALLBACK", YELLOW),
])

ipanel("hcPanelSensors", 2, None)          # filled from SENSOR_BITS
ipanel("hcPanelFuelCut", 1, None)          # filled from the fault decoder
ipanel("hcPanelInhibits", 1, None)         # hcsafety.h, one bit per reason
ipanel("hcPanelBenchRefuse", 1, None)
ipanel("hcPanelBenchAbort", 1, None)
ipanel("hcPanelDbwFaults", 2, None)

ipanel("hcPanelThrottleState", 1, [
    IND("dbwState == 2", "{ DBW: bitStringValue(hcDbwStateList, dbwState)}",
        "Throttle closed loop", YELLOW),
    IND("tpsPairError", "TPS tracks agree", "TPS MISMATCH", RED),
    IND("appPairError", "Pedal tracks agree", "PEDAL MISMATCH", RED),
    IND("tps1Error", "TPS1 OK", "TPS1 FAULT", RED),
    IND("tps2Error", "TPS2 OK", "TPS2 FAULT", RED),
    IND("app1Error", "PEDAL1 OK", "PEDAL1 FAULT", RED),
    IND("app2Error", "PEDAL2 OK", "PEDAL2 FAULT", RED),
])

ipanel("hcPanelNvm", 2, [
    IND("nvmNonVolatile", "TUNE NOT IN FLASH", "Tune in flash", GREEN),
    IND("nvmNotBurned", "Page matches flash", "EDITED SINCE LAST BURN", YELLOW),
    IND("nvmBurnPending", "No burn pending", "BURN PENDING", YELLOW),
    IND("nvmBurnFailed", "Last burn OK", "LAST BURN FAILED", RED),
    # V98r2: WHY - the first refused setting, in words
    IND("cfgValidation != 0 && cfgFirstBadSlot < 1024",
        "Configuration accepted",
        "{ REFUSED: bitStringValue(hcCfgFieldList, cfgFirstBadSlot)}", RED),
    IND("nvmOnDefaults", "Stored tune loaded",
        "RUNNING ON COMPILED DEFAULTS", RED),
    IND("nvmErrorFree", "PERSISTENCE ERROR", "No persistence error", GREEN),
    IND("nvmStateLo == 5",
        "{ Storage: bitStringValue(hcNvmStateList, nvmStateLo)}",
        "Calibration BURNED to flash", GREEN),
    IND("nvmErrLo == 0", "{ Error: bitStringValue(hcNvmErrList, nvmErrLo)}",
        "No persistence error", GREEN),
    IND("nvmSrcLo == 2", "{ Source: bitStringValue(hcNvmSrcList, nvmSrcLo)}",
        "Running from a flash record", GREEN),
    IND("nvmSlot == 1", "{ Slot: bitStringValue(hcNvmSlotList, nvmSlot)}",
        "Active record: slot A", GREEN),
    IND("nvmClass == 2", "{ Class: bitStringValue(hcPersistList, nvmClass)}",
        "NON-VOLATILE", GREEN),
    IND("nvmPhase == 0", "{ Phase: bitStringValue(hcNvmPhaseList, nvmPhase)}",
        "No commit in progress", GREEN),
])

ipanel("hcPanelRamProbe", 1, [
    IND("ramProbeVerdict == 2",
        "{ Probe: bitStringValue(hcRamProbeList, ramProbeVerdict)}",
        "External SRAM execution: PASS", GREEN),
])

ipanel("hcPanelBenchState", 1, [
    IND("hcbState == 0", "{ Bench: bitStringValue(hcBenchStateList, hcbState)}",
        "Bench idle", GREEN),
    # 2026-10-12 (real TunerStudio): the texts were swapped - every NORMAL
    # build (benchSafe 0) read "BENCH-SAFE BUILD: NO OUTPUTS".
    IND("benchSafe", "Output backends present", "BENCH-SAFE BUILD: NO OUTPUTS",
        RED),
])

ipanel("hcPanelPlatform", 2, [
    IND("asicRunning", "I/O CHIP NOT RUNNING", "I/O chip running", GREEN),
    IND("asicError", "I/O chip OK", "I/O CHIP ERROR", RED),
    IND("tickRunning", "TICK STOPPED", "Tick running", GREEN),
    IND("rxTickRunning", "RX TICK STOPPED", "RX tick running", GREEN),
    IND("wdtFed", "WATCHDOG NOT FED", "Watchdog fed", GREEN),
    IND("badVecBit", "No spurious vectors", "SPURIOUS INTERRUPT", RED),
    IND("ramBadBit", "RAM OK", "RAM FAULT", RED),
    IND("rxLoss", "Serial OK", "SERIAL LOSS", RED),
    IND("setupFault", "Setup OK", "SETUP FAULT", RED),
    IND("baroWindowOk", "I/O CHIP WINDOW MOVED", "I/O chip window at word 4",
        YELLOW),
    IND("mainRelayWindowOk", "RELAY WINDOW MOVED",
        "Relay window at word 11", YELLOW),
])

# V84 retired the user arm: outputPins bit 3 is "the relay's automatic
# permission is not met" (page invalid, supervision link down), not "not armed".
ipanel("hcPanelRelay", 1, [
    IND("mainRelayBound", "RELAY CAVITY NOT DRIVABLE",
        "Relay cavity drivable", GREEN),
    IND("mainRelayPinOn", "Relay pin released", "RELAY PIN DRIVEN", GREEN),
    IND("mainRelayInhibited", "Relay permitted", "RELAY REFUSED PERMISSION",
        YELLOW),
    IND("mainRelayFbValid", "RELAY FEEDBACK UNAVAILABLE",
        "Relay feedback valid", GREEN),
    IND("mainRelayMismatch", "Commanded and measured agree",
        "RELAY MISMATCH", RED),
])

ipanel("hcPanelPump", 1, [
    IND("fuelPumpPinOn", "Fuel pump pin released", "FUEL PUMP PIN DRIVEN",
        GREEN),
])


# ==========================================================================
# 3. WORKFLOWS - the dialogs a menu actually opens.
#
#    rusEFI's split-dialog idiom: settings West, the live readings that prove
#    them East (`border`); several panels side by side (`xAxis`).
# ==========================================================================
WORKFLOWS: list[tuple] = []


def dialog(did, title, items, layout=None, help_topic=None):
    WORKFLOWS.append((did, title, items, layout, help_topic))
    return did


# ------------------------------------------------------------------ SETUP --
# rusEFI engineChars ("Vehicle Information" / "Base engine"): cylinders,
# displacement, firing order, fuel strategy.
dialog("hcSetupEngine", "Engine constants", [
    P("hcEngineWest", "West"),
    P("hcEngineFiring", "East"),
    P("hcEngineFiringExt", "South", "cylinders > 8"),
], layout="border", help_topic="hcHelpFiringOrder")


# Speeduino's protection status lights, in the window that sets them
ipanel("hcProtLights", 3, [
    IND("flagRevLimit", "REV LIMIT OFF", "REV LIMIT", RED),
    IND("(limpCut & 1) > 0", "COOLANT PROTECT OFF", "COOLANT PROTECT", RED),
    IND("(limpCut & 2) > 0", "THROTTLE LIMP OFF", "THROTTLE LIMP", RED),
    IND("(limpCut & 8) > 0", "INJ DUTY PROTECT OFF", "INJ DUTY PROTECT", RED),
    IND("(limpCut & 16) > 0", "FLOOD CLEAR OFF", "FLOOD CLEAR", YELLOW),
    IND("(limpCut & 4) > 0", "OIL PROTECT OFF", "OIL PRESSURE CUT", RED),
    IND("flagBoostCut", "BOOST CUT OFF", "BOOST CUT", RED),
])


# rusEFI triggerConfiguration: primary | cams, xAxis. 2026-10-11: settings
# only (Speeduino's Trigger Settings); the live check is its own entry.
dialog("hcSetupTrigger", "Trigger settings", [
    P("hcTriggerWheel"),
    P("hcTriggerSync"),
], help_topic="hcHelpTrigger")

panel("hcSetupTriggerLive", "", [
    P("hcReadTrigger"),
    P("hcPanelTrigger"),
])

dialog("hcTriggerLiveDlg", "Trigger live check and tooth profile", [
    P("hcSetupTriggerLive", "West"),
    P("hcToothProfile", "East"),
], layout="border", help_topic="hcHelpTrigger")

dialog("hcSensorBatteryDlg", "Battery", [
    P("hcSensorBattery", "West"),
    P("hcReadBattery", "East"),
], layout="border")

# V97: rusEFI malfunctionDialog "Check Engine Settings": output, test button
panel("hcOutCel", "Check engine lamp", [
    T("#Cavity 47 is a low-side stage: lamp from switched +12 V to the pin."),
    T("#At key-on: on for the test time, off for the gap, then it shows the"),
    T("#trouble codes (a stored fault reads on-off-on)."),
    F("celEnable"),
    F("pinMil", None, "celEnable == 1"),
    F("celTestEnable", None, "celEnable == 1"),
    F("celTestOnMs", None, "celEnable == 1 && celTestEnable == 1"),
    F("celTestGapMs", None, "celEnable == 1 && celTestEnable == 1"),
    T("Test: three bounded pulses on cavity 47, engine stopped."),
    C("cmdTestCel", "Test Check Engine"),
    P("hcPanelCel"),
])

ipanel("hcPanelCel", 1, [
    IND("(celState & 256) > 0", "LAMP OFF", "LAMP ON",
        "white, black, yellow, black"),
    IND("(celState & 512) > 0", "NO MIL REQUEST", "MIL REQUESTED",
        "white, black, red, black"),
    IND("(celState & 1024) > 0", "LAMP STAGE NOT DRIVEN",
        "LAMP STAGE DRIVEN (47)", "white, black, green, black"),
])

# rusEFI outputsDialog: every output with its own test, in one place.
# rusEFI outputsDialogLeft / outputsDialogRight: two columns, not five.
panel("hcOutColLeft", "", [
    P("hcOutMainRelay"),
])
panel("hcOutColRight", "", [
    P("hcOutCel"),
    P("hcOutMisc"),
])
dialog("hcSetupOutputs", "Outputs", [
    P("hcOutColLeft"),
    P("hcOutColRight"),
], layout="xAxis", help_topic="hcHelpRouting")


dialog("hcFuelInjector", "Injector characteristics", [
    P("hcInjectorHw"),
    P("hcInjOpenTime"),
    P("hcInjectorStrategy"),
], layout="yAxis", help_topic="hcHelpInjMode")

# 2026-10-11 (owner, Speeduino "VE Table"): each main table with the
# options that decide what it means right under it.
# Speeduino's VE Table window: the table, the one option that decides what
# its numbers mean. Owner 2026-10-12: no "legacy" wording anywhere.
panel("hcVeLegacy", "Load model", [
    T("Used only when Fuel algorithm is \"Choose by load model\"."),
    F("loadSource", "Load model", "fuelModel == 0"),
    F("alphaNUseIat", "Use intake air temperature",
      "fuelModel == 0 && loadSource == 2"),
])
panel("hcVeOptions", "", [
    F("fuelModel", "Fuel algorithm"),
    P("hcVeLegacy"),
])
dialog("hcVeDlg", "VE table", [
    P("veTableTbl", "North"),
    P("hcVeOptions", "South"),
], layout="border")

panel("hcIgnTblOptions", "", [
    F("ignLoadMode", "Ignition table load"),
    F("timingModeCfg", "Fixed / locked timing"),
    F("fixedTimingX10", "Fixed angle", "timingModeCfg == 1"),
])
dialog("hcIgnTblDlg", "Ignition advance table", [
    P("ignMapTbl", "North"),
    P("hcIgnTblOptions", "South"),
], layout="border")

panel("hcLambdaTblOptions", "", [
    F("lambdaLoadMode", "Target lambda table load"),
    F("stoichAfrX100"),
])
dialog("hcLambdaTblDlg", "Target lambda table", [
    P("afrMapTbl", "North"),
    P("hcLambdaTblOptions", "South"),
], layout="border")

panel("hcInjTimingTblOptions", "", [
    F("injTimingMode"),
    F("injPhaseMode"),
    F("injStartDegX10", None, "injPhaseMode == 0"),
])
dialog("hcInjTimingTblDlg", "Injection timing table", [
    P("injPhaseTbl", "North"),
    P("hcInjTimingTblOptions", "South"),
], layout="border")



# V97: TRANSIENT FUEL (firmware/engine/hctrans.c) - rusEFI's wall-wetting AE, on the
# fuel per cycle. Settings and the live causal chain west, the two film
# curves east; after-start has its own curve entry in the Fuel menu too.
panel("hcTransSettings", "Transient fuel", [
    T("#The wall film: of every injection a share X lands on the port wall"),
    T("#and evaporates into the cylinder over tau. The ECU injects more on a"),
    T("#tip-in and less on a tip-out so the CYLINDER gets what the model"),
    T("#wants - in every injection mode. After a fuel cut the wall has dried"),
    T("#and the re-entry is compensated automatically."),
    F("transEnable"),
    F("asDecayMs", None, "transEnable == 1"),
    T("Leave Acceleration enrichment (TPS shot) at gain 0 with this on."),
])

rpanel("hcReadTrans", 3, ["transBaseUsGauge", "transWantUsGauge",
                          "injCycleUsGauge", "transCorrUsGauge",
                          "wallFilmUsGauge", "afterStartPmGauge",
                          "injWidthUsGauge", "tpsX10Gauge", "rpmGauge"])

# 2026-10-11 (owner, Speeduino "Acceleration Enrichment"): ONE window - the
# enrichment curves on top, the live graph, the settings, the deceleration
# fuel cut at the bottom.
columns("hcTransCurves", "wwXCurve", "wwTauCurve")

panel("hcAccelGraph", "", [
    LG("hcTransGraph", "Tip-in: throttle, film share, fuel", "Center",
       ["tpsX10", "transCorrUs", "injCycleUs"]),
])

columns("hcAccelSettings", "hcTransSettings", "hcFuelEnrich")

dialog("hcAccelDlg", "Acceleration enrichment", [
    P("hcTransCurves", "North", "transEnable == 1"),
    P("hcAccelGraph", "Center"),
    P("hcAccelSettings", "West"),
    P("hcFuelOverrun", "South"),
], layout="border", help_topic="hcHelpTransient")


dialog("hcCrankingDlg", "Cranking settings", [
    P("hcCranking"),
    P("hcCrankFuel"),
    P("hcCrankTiming"),
], layout="yAxis")


dialog("hcAseDlg", "After-start enrichment (ASE)", [
    P("hcAse"),
])

dialog("hcStftDlg", "Closed loop fuel correction", [
    P("hcStft", "West"),
    P("hcStftRight", "East"),
], layout="border", help_topic="hcHelpLambda")


dialog("hcIgnitionHw", "Spark settings", [
    P("hcSparkMain"),
    P("hcSparkLocked"),
], layout="yAxis", help_topic="hcHelpIgnition")

dialog("hcIgnOutDlg", "Ignition outputs", [
    P("hcIgnitionPins"),
    P("hcTestCoils"),
], layout="xAxis", help_topic="hcHelpIgnition")


dialog("hcDwellDlg", "Dwell settings", [
    P("hcDwell"),
])

# --------------------------------------------------------------- SENSORS ---
dialog("hcSensorCltDlg", "CLT sensor", [
    P("hcSensorClt", "North"),
    P("cltSensCurve", "Center"),
    P("hcReadClt", "South"),
], layout="border", help_topic="hcHelpThermistor")

dialog("hcSensorIatDlg", "IAT sensor", [
    P("hcSensorIat", "North"),
    P("iatSensCurve", "Center"),
    P("hcReadIat", "South"),
], layout="border", help_topic="hcHelpThermistor")

dialog("hcSensorMapDlg", "Pressure sensor (MAP / charge pressure)", [
    P("hcSensorMap", "West"),
    P("hcReadMap", "East"),
], layout="border", help_topic="hcHelpPressure")

dialog("hcSensorBaroDlg", "Ambient pressure", [
    P("hcSensorBaroLeft", "West"),
    P("hcReadBaro", "East"),
], layout="border", help_topic="hcHelpBaro")

panel("hcSensorBaroLeft", "", [
    P("hcSensorBaro"),
    P("hcPanelBaro"),
])

dialog("hcSensorMiscDlg", "Mass air flow input", [
    P("hcSensorMisc"),
], help_topic="hcHelpRouting")

dialog("hcSensorLambdaDlg", "Wideband O2 sensors", [
    P("hcLambdaStrategy", "West"),
    P("hcLambdaRight", "East"),
], layout="border", help_topic="hcHelpLambda")

# V97 (2026-09-30): Sensors > TPS is a DIAGNOSTICS page - raw counts,
# voltages, both tracks' %, validity and faults. Calibrating the throttle is
# ONE workflow in Advanced > Electronic Throttle Body; a second place with
# the same buttons made the tuner jump between windows.
ipanel("hcPanelTpsDiag", 1, [
    IND("tps1Error", "TPS1 OK", "TPS1 FAULT", RED),
    IND("tps2Error", "TPS2 OK", "TPS2 FAULT", RED),
    IND("tpsPairError", "TPS tracks agree", "TPS MISMATCH", RED),
])

panel("hcEtbTpsDiag", "TPS", [
    T("#Live values only. Pins, endpoints and AutoCal are in"),
    T("#Advanced > Electronic Throttle Body."),
    P("hcPanelTpsDiag"),
    P("hcReadTps"),
])

# 2026-10-11 (owner: "sensor calibrations under Tools, like Speeduino"):
# Tools > Calibrate TPS is THE place for the endpoints and the Grabs, with
# the live tracks beside them. AutoCal (the motor finds the stops) stays in
# the ETB window; nothing appears in two places.
columns("hcEtbTpsCalCols",
        "hcEtbTpsCal",
        ["hcPanelGrab", "hcPanelThrottleState"])

dialog("hcEtbTpsCalDlg", "Calibrate TPS", [
    P("hcEtbTpsCalCols", "West"),
    P("hcEtbTpsDiag", "East"),
], layout="border", help_topic="hcHelpTpsCal")

panel("hcEtbCharacterizeControls", "ETB characterization", [
    T("!Engine off only. Keep clear of the throttle; no pedal is needed."),
    T("#Holds and ramps from 2 to 90 %, pedal-map slams and ramps, then"),
    T("#break-away tests at 5..80 %: the friction band and its midpoint."),
    T("#It changes no calibration; every exit switches the bridge off."),
    C("cmdEtbCharacterize", "Run ETB Characterization"),
    C("cmdEtbAutoCalAbort", "Abort"),
    C("cmdEtbSaveBias", "Save Measured Bias / Feedforward", "sweepBiasState == 1 && etbCalResult == 7"),
    P("hcEtbCharacterizeDiagnosis"),
    IND("etbProcKind == 6 && etbCalResult == 1", "IDLE", "CHARACTERIZATION RUNNING"),
    IND("etbProcKind == 6 && etbCalResult == 7", "-", "CHARACTERIZATION COMPLETE"),
    IND("etbProcKind == 6 && etbCalResult == 3", "-", "{ STOPPED: bitStringValue(hcEtbWhyList, etbCalWhy)}"),
    IND("(sweepFindings & 1) != 0", "Authority: no finding", "OUTPUT AUTHORITY candidate"),
    IND("(sweepFindings & 2) != 0", "Bias: no finding", "FEEDFORWARD/BIAS candidate: investigate before PID"),
    IND("(sweepFindings & 4) != 0", "P: no finding", "LIKELY PID P: slow with spare authority"),
    IND("(sweepFindings & 64) != 0", "TPS: no finding", "TPS/SENSOR fault"),
    IND("(sweepFindings & 128) != 0", "Rate limit: not observed", "TARGET RATE LIMIT active during pedal slam"),
    IND("(sweepFindings & 256) != 0", "-", "INCONCLUSIVE: inspect traces / analyze log"),
    IND("etbCalResult == 7 && sweepFindings == 0", "-", "GOOD within this profile; inspect traces"),
    N("Save writes the bias curve to RAM - then Burn."),
])
# TunerStudio accepts indicators only inside an indicatorPanel.
_controls = PANELS[-1][2]
_findings = [it for it in _controls if it[0] == "i"]
_controls[:] = [it for it in _controls if it[0] != "i"]
# Native TS 3.3.01 Indicator.setValue() repaints only on boolean transitions.
# A constant-true condition freezes dynamic text at page-open values. Drive
# repaint from the ECU clock; identical labels/colours prevent visual blinking.
_diagnosis_text = [
    "{ Overall result: bitStringValue(hcEtbCalList, etbCalResult)}",
    "{ Likely issue: bitStringValue(hcSweepIssueList, sweepPrimary)}",
    "{ Secondary issue: bitStringValue(hcSweepIssueList, sweepSecondary)}",
    "{ Recommended next action: bitStringValue(hcSweepActionList, sweepAction)}",
    "{ Feed-forward proposal: bitStringValue(hcSweepBiasList, sweepBiasState)}",
]
ipanel("hcEtbCharacterizeDiagnosis", 1, [
    *[IND("(tickMs & 512) != 0", label, label,
          "white, black, white, black") for label in _diagnosis_text],
    IND("sweepBiasState == 2", "", "CALIBRATION MODIFIED IN RAM - REVIEW / BURN REQUIRED"),
])
rpanel("hcEtbBiasCompare", 4, [g for j in range(8) for g in
    (f"sweepBiasAxis{j}Gauge",f"sweepBiasCurrent{j}Gauge",
     f"sweepBiasProposedAxis{j}Gauge",f"sweepBiasProposed{j}Gauge")]+[
    "sweepIntegralPreviousGauge","sweepIntegralMeanGauge","sweepBiasSamplesGauge",
    # A partial update is only honest if the tuner can see HOW partial it is:
    # Save leaves every point outside this range at its current value.
    "sweepBiasValidMinGauge","sweepBiasValidMaxGauge","sweepBiasQualifiedGauge"])
# One row per measurement position: band midpoint (the proposal's source),
# band width (friction) and the worst edge spread (repeatability).
rpanel("hcEtbFrictionBand", 3, [g for j in range(6) for g in
    (f"fricMid{j}Gauge", f"fricWidth{j}Gauge", f"fricSpread{j}Gauge")])
rpanel("hcEtbCharacterizeResults", 3, [
    "sweepSegmentGauge", "sweepRmsGauge", "sweepSaturationGauge",
    "etbVfySettleMsGauge", "etbVfyOverX10Gauge", "etbVfyErrX10Gauge",
    "sweepBoundRmsGauge", "sweepBoundSatGauge", "sweepPairWorstGauge",
    "sweepSlamSettleGauge", "sweepSlamOverGauge", "sweepSlamSteadyGauge",
    "sweepVbatMinGauge", "sweepVbatMaxGauge", "dbwBattFactorGauge",
])
panel("hcEtbCharacterizeMotion", "", [LG("hcEtbSweepMotion", "ETB motion and signed duty", "South",
    ["sweepRequested", "sweepTarget", "sweepActual", "sweepMotor"] )])
panel("hcEtbCharacterizeTerms", "", [LG("hcEtbSweepTerms", "ETB controller contributions", "South",
    ["sweepP", "sweepI", "sweepD", "sweepFf", "battDv"] )])
# 2026-10-11 (owner: windows too big): the run, its findings and the
# motion graph here; the bias/friction tables and the controller-terms
# graph in their own dialog beside it in the menu.
# 2026-10-11 round 2 (owner: "why so many Point position values ... what
# should a tuner do with that data"): the tuner's window is Run / Abort /
# Save, the state, the verdict and the motion graph. The measurement data
# (proposed points, friction band, controller terms, run statistics) is the
# DEVELOPER window - in the forensic project only (gen_ts_ini DEV_ONLY).
ipanel("hcEtbCharFindings", 1, _findings)

dialog("hcEtbCharacterizeDlg", "ETB characterization", [
    P("hcEtbCharacterizeControls", "West"),
    P("hcEtbCharacterizeMotion", "South"),
], layout="border")

columns("hcEtbCharDetailCols", "hcEtbBiasCompare", "hcEtbFrictionBand",
        ["hcEtbCharacterizeResults", "hcEtbCharFindings"])

dialog("hcEtbCharDetailDlg", "ETB characterization raw data (developer)", [
    P("hcEtbCharDetailCols", "North"),
    P("hcEtbCharacterizeTerms", "South"),
], layout="border")

dialog("hcEtbCommissionDlg", "ETB AutoCal results", [
    P("hcEtbCommission", "West"),
    P("hcEtbCommissionRight", "East"),
], layout="border", help_topic="hcHelpEtbCommission")

dialog("hcEtbAppCalDlg", "Pedal position sensor", [
    P("hcEtbAppLeft", "West"),
    P("hcReadApp", "East"),
], layout="border", help_topic="hcHelpAppCal")

columns("hcEtbAppLeft",
        "hcEtbAppCal",
        ["hcPanelGrab", "hcPanelThrottleState"])

# -------------------------------------------------------------- ADVANCED ---
# rusEFI etbDialog, "Electronic Throttle Body actuator".
dialog("hcEtbMain", "Electronic Throttle Body", [
    P("hcEtbLeft", "West"),
    P("hcEtbRight", "East"),
    P("hcEtbGraph", "South"),
], layout="border", help_topic="hcHelpDbw")

# 2026-10-11 (owner: "too much on the tuner front end, I have to scroll
# every window on the laptop"): TWO columns - the settings a tuner uses
# West, the AutoCal buttons and the live values East. The TPS endpoint
# calibration, the jam/limp/rev limits and the bench nudge share ONE more
# dialog; the throttle is ONE group in Advanced (owner: "too many ETB
# options in Advanced") - every field stays reachable.
columns("hcEtbLeft",
        ["hcEtbBase", "hcEtbPid"])

columns("hcEtbRight",
        ["hcEtbAutotune", "hcReadEtbLive"])

columns("hcEtbSetupCols",
        "hcEtbSafety",
        "hcEtbNudge")

dialog("hcEtbSetupDlg", "ETB limits and bench test", [
    P("hcEtbSetupCols"),
], help_topic="hcHelpDbw")


panel("hcEtbGraph", "", [
    LG("hcEtbLiveGraph", "Throttle: target vs actual", "South",
       ["etbTarget", "etbActual", "dbwDutyX10", "pedalPosition"]),
])

dialog("hcBoostDlg", "Boost control options", [
    P("hcBoostBase"),
    P("hcBoostPid", None, "boostEnable == 1"),
], layout="xAxis")

# 2026-10-11 (owner: "simplify"): Speeduino's "Launch Control / Flat
# shift" window; anti-lag and the pit limiter are their own window.
columns("hcMotorsportCols", "hcMsLaunch", ["hcMsFlat", "hcMotorsport"])
columns("hcAlsCols", "hcMsAls", "hcMsPit")

dialog("hcAlsDlg", "Anti-lag, pit limiter, rotational idle", [
    P("hcAlsCols"),
])

dialog("hcMotorsportDlg", "Launch control / flat shift", [
    P("hcMotorsportCols"),
])

# ------------------------------------------------------------------ KNOCK --
# rusEFI softwareKnock: "Sense" (with the cylinder -> sensor mapping) and
# "Response" West, the threshold curve Center; HaniCore adds the CC195's
# own knobs (band, gain per sensor, window curves) and the live chain East.
# 2026-10-11 (owner: "the knock window is massive, can't read anything"):
# Speeduino's Knock Settings arrangement - "Settings" West, "Detection and
# Response" East, the status lights under them. The sensor calibration (gains,
# diagnosis, the window and threshold curves) and the live numbers
# are their own "advanced" window, opened only to calibrate.
panel("hcKnockSense", "Settings", [
    F("knockMode", "Knock mode"),
    F("knockBand", "Band-pass frequency", "knockMode > 0"),
    N("Monitor only logs. Active retards the knocking cylinder."),
])
panel("hcKnockGains", "Sensor gains", [
    E("knockGain", "knockMode > 0"),
])
panel("hcKnockMap", "Sensor for each cylinder", [
    E("knockSensor", "knockMode > 0"),
])
panel("hcKnockResponse", "Detection and response", [
    F("knockStepQ", None, "knockMode > 0"),
    F("knockMaxQ", None, "knockMode > 0"),
    F("knockReapplyMs", None, "knockMode > 0"),
    F("knockSafeQ", None, "knockMode > 0"),
    F("knockRpmMin", None, "knockMode > 0"),
    F("knockLoadMin", None, "knockMode > 0"),
    F("knockCltMin", None, "knockMode > 0"),
])
panel("hcKnockReference", "Reference and diagnosis", [
    F("knockRefInit", None, "knockMode > 0"),
    F("knockLearn", None, "knockMode > 0"),
    F("knockTp", None, "knockMode > 0"),
    F("knockTpDyn", None, "knockMode > 0"),
    F("knockKefDyn", None, "knockMode > 0"),
    F("knockDiagRpm", None, "knockMode > 0"),
    F("knockRefMin", None, "knockMode > 0"),
    F("knockRefMax", None, "knockMode > 0"),
    F("knockDiagN", None, "knockMode > 0"),
    F("knockStopN", None, "knockMode > 0"),
])
ipanel("hcPanelKnock", 2, [
    IND("knockWhy == 0 && knockModeNow > 0",
        "{ KNOCK: bitStringValue(hcKnockWhyList, knockWhy)}",
        "KNOCK: MEASURING", "white, black, green, black"),
    IND("knockRetardX10 > 0", "NO KNOCK RETARD", "KNOCK RETARD ACTIVE",
        "white, black, red, black"),
    IND("knockSens1Fault == 1", "SENSOR 1 OK", "SENSOR 1 FAULT",
        "white, black, red, black"),
    IND("knockSens2Fault == 1", "SENSOR 2 OK", "SENSOR 2 FAULT",
        "white, black, red, black"),
    IND("knockCfgErr > 0", "CALIBRATION OK", "CALIBRATION REFUSED",
        "white, black, red, black"),
    IND("(knockFlags & 255) > 0", "NO CYLINDER AT STOP", "CYLINDER AT STOP",
        "white, black, red, black"),
])
rpanel("hcReadKnock", 2, ["knockLastCylGauge", "knockRetardX10Gauge",
                          "knockCountGauge", "knockWindowsGauge"])
rpanel("hcReadKnockCyl", 4,
       ["knockLevel%dGauge" % (i + 1) for i in range(4)]
       + ["knockRet%dGauge" % (i + 1) for i in range(4)]
       + ["knockLevel%dGauge" % (i + 5) for i in range(4)]
       + ["knockRet%dGauge" % (i + 5) for i in range(4)])
panel("hcKnockLeft", "", [
    P("hcKnockSense"),
    P("hcKnockMap"),
])
dialog("hcKnockDlg", "Knock settings", [
    P("hcKnockLeft", "West"),
    P("hcKnockResponse", "East"),
    P("hcPanelKnock", "South"),
], layout="border", help_topic="hcHelpKnock")

# the calibration window: gains, diagnosis, the curves, and the
# live numbers the calibration is judged by
panel("hcKnockAdvLeft", "", [
    P("hcKnockGains"),
    P("hcKnockReference"),
])
columns("hcKnockAdvCurves", "knockWinStartCurve", "knockWinLenCurve",
        "knockKefCurve")
panel("hcKnockAdvLive", "", [
    P("hcReadKnock"),
    N("Per cylinder: knock level and retard"),
    P("hcReadKnockCyl"),
])
dialog("hcKnockAdvDlg", "Knock sensor calibration (advanced)", [
    P("hcKnockAdvLeft", "West"),
    P("hcKnockAdvCurves", "North"),
    P("hcKnockAdvLive", "East"),
], layout="border", help_topic="hcHelpKnock")

# -------------------------------------------------------------------- VVT --
# rusEFI Advanced: "VVT outputs and PID" (vvtPidDialog: Configuration West,
# the PIDs Center) and "VVT intake / exhaust target" (table + status).
panel("hcVvtConfig", "Configuration", [
    T("#Closed loop needs the Pattern cam phase method on that cam input"),
    T("#(Setup > Trigger). On/off: a positive target switches the solenoid."),
    T("#A fault drops the duty to 0 (the phaser's rest position)."),
    E("vvtMode"),
    F("pinCam1Sol", None, "vvtMode1 > 0"),
    F("pinCam2Sol", None, "vvtMode2 > 0"),
    E("vvtInvert"),
    F("vvtFreqHz"),
    F("vvtDelayMs"),
    F("vvtMinRpm"),
    F("vvtMinClt"),
    F("vvtFbMs"),
    F("vvtErrMax"),
    F("vvtErrMs"),
    T("Bench: three 250 Hz bursts at 50 %, engine stopped."),
    C("cmdTestVvt1", "Bench cavity 115"),
    C("cmdTestVvt2", "Bench cavity 120"),
])
panel("hcVvtPid", "PID", [
    E("vvtKp"),
    E("vvtKi"),
    E("vvtKd"),
    E("vvtDutyMin"),
    E("vvtDutyMax"),
    E("vvtDutyOn"),
])
ipanel("hcPanelVvt", 2, [
    IND("vvt1Closed == 1", "CAM 1 NOT CLOSED LOOP", "CAM 1 CLOSED LOOP",
        "white, black, green, black"),
    IND("vvt2Closed == 1", "CAM 2 NOT CLOSED LOOP", "CAM 2 CLOSED LOOP",
        "white, black, green, black"),
    IND("vvt1Fault > 0", "CAM 1 NO FAULT",
        "{ CAM 1: bitStringValue(hcVvtFaultList, vvt1Fault)}",
        "white, black, red, black"),
    IND("vvt2Fault > 0", "CAM 2 NO FAULT",
        "{ CAM 2: bitStringValue(hcVvtFaultList, vvt2Fault)}",
        "white, black, red, black"),
])
rpanel("hcReadVvt", 2, ["vvt1TargetGauge", "vvt2TargetGauge",
                        "vvt1PosGauge", "vvt2PosGauge",
                        "vvt1ErrGauge", "vvt2ErrGauge",
                        "vvt1DutyGauge", "vvt2DutyGauge"])
panel("hcVvtRight", "", [
    P("hcPanelVvt"),
])
dialog("hcVvtDlg", "VVT outputs and PID", [
    P("hcVvtConfig", "West"),
    P("hcVvtPid", "Center"),
    P("hcVvtRight", "East"),
], layout="border", help_topic="hcHelpVvt")

dialog("hcIdleDlg", "Idle control",
       [P("hcIdleBase"), P("hcIdleCurves"), P("hcIdleState")],
       layout="xAxis")
dialog("hcIdleTimingDlg", "Idle advance",
       [P("hcIdleTiming"), P("idleTargetCurve")], layout="xAxis")

# 2026-10-11: the settings windows are Speeduino-style (settings only);
# the live values that sat beside them are here, one window to keep open
# while tuning (Diagnostics > Live tuning values).
rpanel("hcReadLiveEssentials", 3, [
    "RPMValueGauge", "mapControlGauge", "TPSValueGauge",
    "lambdaValueGauge", "targetLambdaGauge", "stftBank1Gauge",
    "veValueGauge", "injectorPulseWidthGauge", "injectorDutyGauge",
    "ignitionTimingGauge", "ignCorrX10Gauge", "afterStartPmGauge",
    "idleTargetRpmGauge", "idleTrimX10Gauge", "idleTimingX10Gauge"])

dialog("hcDiagLive", "Live tuning values", [
    P("hcReadLiveEssentials"),
])

rpanel("hcDevTrimmed", 2, ["crankSyncGauge", "cycleSyncGauge", "crankToothIndexGauge", "crankEdgesGauge", "camPhaseNoAltGauge", "camLowWidthX10Gauge", "camHighWidthX10Gauge", "trigCfgAngleX10Gauge", "cam1PatClassGauge", "cam2PatClassGauge", "cam1VvtX10Gauge", "cam2VvtX10Gauge", "tps1VoltageGauge", "tps2VoltageGauge", "dbwTps1X10Gauge", "dbwTps2X10Gauge", "app1VoltageGauge", "app2VoltageGauge", "dbwApp1X10Gauge", "dbwApp2X10Gauge", "lambda1StateGauge", "lambda2StateGauge", "lambda1ValidGauge", "lambda2ValidGauge", "heater1DutyGauge", "heater2DutyGauge", "lam1RiX10Gauge", "lam2RiX10Gauge", "lam1IpUaGauge", "lam2IpUaGauge", "lam1FaultGauge", "lam2FaultGauge", "cj1DiagGauge", "cj2DiagGauge", "ambientVoltageGauge", "baroRawGauge", "ambientAgeSecondsGauge", "knockLastIkrGauge", "knockWinStartX10Gauge", "knockWinLenX10Gauge", "knockSamplesGauge", "knockLateGauge", "knockStaleGauge", "knockWinUsGauge", "knockAdcFailGauge", "knockRef1Gauge", "knockRef2Gauge", "knockRef3Gauge", "knockRef4Gauge", "knockRef5Gauge", "knockRef6Gauge", "knockRef7Gauge", "knockRef8Gauge", "knockCnt1Gauge", "knockCnt2Gauge", "knockCnt3Gauge", "knockCnt4Gauge", "knockCnt5Gauge", "knockCnt6Gauge", "knockCnt7Gauge", "knockCnt8Gauge"])

# EVERY number box the user windows no longer show, for debugging - the
# developer (forensic) project only (gen_ts_ini_me711 DEV_ONLY).
columns("hcDevLiveCols",
        ["hcReadFuel", "hcReadSeq", "hcReadTrans", "hcReadSpark"],
        ["hcReadIdle", "hcReadIdleTiming", "hcReadStft", "hcReadVvt"],
        ["hcReadBoost", "hcReadMs", "hcReadLoadModel", "hcReadLambdaLink"],
        ["hcDevTrimmed", "hcPanelSwitchRaw", "hcPanelLoadState"])

dialog("hcDevLiveAll", "All live values (developer)", [
    P("hcDevLiveCols"),
])

# ------------------------------------------------------------ CONTROLLER ---
# rusEFI engineTypeDialog, "Base Tunes" - under Controller, as there.
dialog("hcBaseTunes", "Base Tunes", [
    P("hcEnginePreset"),
    P("hcPanelPreset"),
])

dialog("hcCtrlDlg", "Controller and identity", [P("hcCtrlIdent")])
dialog("hcCtrlS5500Dlg", "I/O chip analog window", [
    P("hcCtrlS5500"),
])

panel("hcUnusedInfo", "", [
    T("#Settings stored in the calibration that this firmware does not use."),
    T("#Editing one changes nothing; they are kept so stored calibrations"),
    T("#stay compatible."),
])

# Three columns, not five: explanation + engine | fuel | ignition + channels.
columns("hcUnusedCols",
        ["hcUnusedInfo", "hcUnusedEngine"],
        "hcUnusedFuel",
        ["hcUnusedIgn", "hcUnusedChannels"])

dialog("hcUnusedSettings", "Stored settings this firmware does not use", [
    P("hcUnusedCols"),
])

# V98r2: the pin assignments with no runtime path, out of the live Sensors /
# Outputs / Motorsport dialogs (a tuner must not wire to a cavity that
# nothing reads or drives).
panel("hcUnusedIn", "Inputs", [
    F("pinFlex"),
    F("pinBaro"),
    F("pinVss"),
    F("pinMapSwitch"),
    E("pinGenericAin"),
])
panel("hcUnusedPwm", "PWM outputs", [
    E("pinGenericPwm"),
])
panel("hcUnusedOut", "On/off outputs, bench", [
    E("pinGenericOut"),
    F("testPin"),
])
columns("hcUnusedIoCols", "hcUnusedIn", "hcUnusedPwm", "hcUnusedOut")
dialog("hcUnusedIo", "Stored pin assignments with no runtime path", [
    P("hcUnusedIoCols"),
])

# ------------------------------------------------------------- DIAGNOSIS ---
dialog("hcStatusOverview", "Status overview", [
    P("hcPanelOverview"),
])

dialog("hcWhyNoSync", "Why is there no sync?", [
    P("hcPanelTrigger"),
    P("hcReadTrigger"),
])

dialog("hcWhyFuelCut", "Why is fuel cut?", [
    T("#Two things stop fuel: a cut decided by the engine model, and an"),
    T("#inhibit that stops every output at once."),
    P("hcPanelFuelCut"),
    P("hcPanelInhibits"),
    P("hcReadFuel"),
])

# V89 UI (rusEFI pass): this dialog said BENCH_SAFE was set and no coil could
# fire. HANICORE_BENCH_SAFE has been commented out of hctarget.h since V63 and
# V85 measured spark permitted under crank sync - the text was the opposite of
# the truth, on the dialog a person opens when deciding whether a coil is live.
columns("hcWhyNoSparkCols",
        [T("#Spark runs automatically - there is no arming switch. It needs"),
         T("#crank sync, a valid configuration and the I/O chip link; each"),
         T("#inhibit below stops it on its own. The table, dwell and timing"),
         T("#mode then decide what is commanded."),
         B(),
         T("!On a new installation test each coil first (Controller > Bench"),
         T("!test, one at a time, engine stopped)."),
         B(),
         P("hcPanelInhibits")],
        ["hcPanelTrigger", "hcReadSpark"])

dialog("hcWhyNoSpark", "Why is there no spark?", [
    P("hcWhyNoSparkCols"),
])

# V98 (real TunerStudio review, 2026-10-01): ONE DIAGNOSTIC LIST - Status |
# Code - Description, one row per code. V97 showed an ACTIVE column and a
# STORED column, every code twice in giant boxes. hcdtc.c sets ACTIVE and
# STORED together and a clear wipes both, so the rows are the four STORED
# slots, each with its status (dtcS<n>St: Active + Stored in red, Stored in
# yellow, the freeze-frame code marked), ONE indicator per row so the
# code text gets the full width (hcDtcRowList). The raw dtcActive1.. / dtcStored1..
# words stay channels for the logger.
# 2026-10-11 (owner: "more than ~5 codes are not visible"): ONE ROW PER
# CODE the firmware can set, shown only while that code is stored - every
# stored code, not the first four. Bit i of dtcStoredMask/dtcActiveMask =
# path i of hcdtc711.c defs[] (gen_ts_ini_me711.DTC_PATHS); red = active
# now, yellow = stored only.
import ts_dtc_me711 as _GI          # noqa: E402  (the code set and its text)
# 2026-10-12 (owner, real TunerStudio: "why are there no DTCs?"): the rows
# were panels SHOWN ON A LIVE CHANNEL ({ dtcStoredMask0 bit }), and
# TunerStudio does not evaluate a dialog panel's visibility on output
# channels - nothing ever appeared, not even "No trouble codes". None of
# rusEFI's 40 generated INIs does it (indicators and command buttons ARE
# evaluated live). So the list is ALWAYS VISIBLE: one row per code, two
# indicators - the code (highlighted while stored) and ACTIVE NOW (red).
# A bit is tested with & and a literal mask: rusEFI's INIs use no >>.
_DTC_BOARD = []
for _i, _code in enumerate(_GI.DTC_PATHS):
    _w, _b = ("Mask0", _i) if _i < 16 else ("Mask1", _i - 16)
    _bit = 1 << _b
    _txt = "P%04d - %s" % (_code, _GI.DTC_TEXT[_code])
    _DTC_BOARD.append(IND("(dtcStored%s & %d) != 0" % (_w, _bit), _txt, _txt,
                          "white, black, yellow, black"))
    _DTC_BOARD.append(IND("(dtcActive%s & %d) != 0" % (_w, _bit), "-",
                          "ACTIVE NOW", "white, black, red, white"))
    # 2026-10-15 (owner): the third column - what to check; while the code
    # is stored, what the ECU itself latched (its reason channel), if any
    _cause = "Check: " + _GI.DTC_CAUSE[_code]
    _why = _GI.DTC_REASON.get(_code)
    _DTC_BOARD.append(IND(
        "(dtcStored%s & %d) != 0" % (_w, _bit), _cause,
        ("{ ECU: bitStringValue(%s, %s)}" % _why) if _why else _cause,
        "white, black, yellow, black"))
ipanel("hcDtcBoard", 3, _DTC_BOARD)

ipanel("hcDtcNone", 1, [
    IND("dtcStoredN == 0",
        "Codes stored - highlighted below (red = present now)",
        "No trouble codes", "yellow, black, green, black")])
ipanel("hcDtcLamp", 1, [
    IND("dtcMil", "CEL OFF", "CEL ON", RED)])
ipanel("hcDtcFfCode", 1, [
    IND("dtcFfCode != 0", "No freeze frame",
        "{ bitStringValue(hcDtcList, dtcFfIdx)}",
        "white, black, white, black")])

panel("hcDtcList", "Trouble codes", [
    P("hcDtcNone"),
    P("hcDtcBoard")])
rpanel("hcReadDtcFf", 4, ["dtcFfRpmGauge", "dtcFfCltShownGauge",
                          "dtcFfMapGauge", "dtcFfTpsGauge"])
panel("hcDtcSide", "", [
    P("hcDtcLamp"),
    C("cmdDtcClear", "Clear trouble codes"),
    T("A fault still present comes back after a clear."),
    B(),
    T("#Freeze frame - the first code confirmed:"),
    P("hcDtcFfCode"),
    P("hcReadDtcFf"),
])

# The list on top, the freeze frame below with its four values in ONE row:
# that row sets the dialog's width, and the list rows get all of it (beside
# the freeze frame, TunerStudio 3.3.01 shrank the code text to fit).
dialog("hcDiagDtc", "Trouble codes (DTC)", [
    P("hcDtcList", "Center"),
    P("hcDtcSide", "South"),
], layout="border")

dialog("hcWhichSensor", "Which sensor failed?", [
    P("hcPanelSensors"),
])

dialog("hcWhyThrottle", "Why is the throttle disabled?", [
    P("hcPanelThrottleState"),
    P("hcPanelDbwFaults"),
    P("hcReadThrottle"),
])

# rusEFI's fuel_computer / ignition_state dialogs: the WORKING, in the order
# the firmware computes it.
dialog("hcFuelComputer", "Fuel computer", [
    T("#In calculation order: VE table (rpm x VE axis) and air density"),
    T("#(pressure, temperature) -> air mass -> target lambda -> fuel mass"),
    T("#-> corrections (warm-up, closed loop, wall film) -> opening time"),
    T("#+ dead time."),
    P("hcReadFuel"),
    P("hcPanelFuelCut"),
])

dialog("hcSparkState", "Ignition state", [
    P("hcReadSpark"),
])

# ------------------------------------------------------------------ HELP ---
# rusEFI Help / "rusEFI Info". HaniCore's is the commissioning order, with the
# menu path of every step - and the three things this firmware does NOT do
# that a first start must not assume.
panel("hcHelpSteps", "Setup order", [
    T("#1  Controller > Base Tunes: choose the engine, APPLY (engine stopped),"),
    T("#   review, Burn, then cycle the key."),
    T("#2  Fuel > Fuel model: check the model and where the pressure sensor"),
    T("#   measures."),
    T("#3  Advanced > Electronic Throttle Body: AutoCal ETB. Tools > Pedal"),
    T("#   position sensor: Grab both ends; the two tracks must agree. Burn."),
    T("#4  Sensors: coolant, intake air, pressure, ambient and battery read"),
    T("#   plausibly (Diagnostics > Why? > Which sensor failed?)."),
    T("#5  Setup > Trigger: crank - sync must come and stay"),
    T("#   (Diagnostics > Why? > Why is there no sync?)."),
    T("#6  Controller > Bench test, engine stopped, one channel at a time:"),
    T("#   fuel pump, each injector, each coil, the throttle."),
    T("#7  Advanced > Electronic Throttle Body: enable only after 3 and 6."),
    T("#8  Ignition > Ignition hardware: fixed timing, check with a timing"),
    T("#   light, correct the trigger angle (Setup > Trigger), back to dynamic."),
    B(),
    T("#Burn works with the engine stopped or cranking; the connection pauses"),
    T("#for a few seconds and resumes. Above about 500 rpm it is refused and"),
    T("#the edits stay live - stop the engine and Burn again."),
    B(),
    T("!Not in this firmware: oil-pressure protection, long-term fuel trim,"),
    T("!MAF-based fuelling. Implemented but not yet vehicle-qualified: rev"),
    T("!limiter, idle control, closed-loop lambda, boost control, knock, VVT,"),
    T("!launch / flat shift / anti-lag and lean protection."),
])

dialog("hcHelpInfo", "HaniCore - setup order", [
    P("hcHelpSteps"),
])


# ==========================================================================
# 4. THE MENU - rusEFI's own top level and order:
#
#   Setup / Fuel / Ignition / Cranking / Idle / Advanced / Sensors /
#   Controller / Help (tunerstudio.template.ini, top_level_menu.ini)
#
# and the same homes for the same things: TPS and pedal under Sensors, the
# ETB actuator under Advanced, Outputs and Battery under Setup, Base Tunes and
# the bench test under Controller. HaniCore's differences, each for a reason:
#   * Diagnostics replaces rusEFI's &View - the same idea (live module state)
#     grouped by the question a tuner asks rather than by C struct name, with
#     developer forensics moved to Controller / Developer diagnostics;
#   * CAN-bus is absent - HaniCore has no CAN feature.
# Controller, Diagnostics and Help are appended by the generator, because
# their dialogs are declared there (the command buttons must be checked
# against the [ControllerCommands] block that same file emits).
#
# A `(dialog, label)` pair here; a `("GROUP", label, [children])` for a
# groupMenu; "SEP" for rusEFI's std_separator.
# ==========================================================================

# ==========================================================================
# SPEEDUINO WINDOWS (owner, 2026-10-11: "make everything as Speeduino does on
# the user interface"). Each window below is Speeduino's window of the same
# job (speeduino-*/reference/speeduino.ini), field by field in its
# order, with its box titles; a Speeduino line HaniCore has no setting for
# is left out. The MENUS stay HaniCore's (owner). redialog() replaces a
# window by its id, so menu entries and help topics keep working. No text
# is copied (the maintainer's design notes class F).
# ==========================================================================
def redialog(did, title, items, layout=None, help_topic=None):
    for i, d in enumerate(WORKFLOWS):
        if d[0] == did:
            WORKFLOWS[i] = (did, title, items, layout, help_topic)
            return did
    return dialog(did, title, items, layout, help_topic)


# ---- Engine Constants ------------------------------------------------------
rpanel("swReadReqFuel", 1, ["requiredFuelGauge"])
panel("swReqFuel", "Calculate Required Fuel", [
    P("swReadReqFuel"),
    F("displacementCc", "Engine displacement"),
    F("cylinders", "Number of cylinders"),
    N("Required fuel: injector time per cylinder at VE 100 %"),
    N("Injector flow: Fuel > Injector Characteristics"),
])
panel("swEngine", "", [
    F("fuelModel", "Control algorithm"),
    F("strokes", "Engine stroke"),
    F("firingOrder", "Engine type / firing order"),
])
panel("swBoard", "HaniCore board", [
    T("!This is a critical setting!"),
    T("Outputs fire wrong if the layout does not match the wiring"),
    F("stoichAfrX100", "Stoichiometric ratio"),
    F("injStrategy", "Injector layout"),
    F("pressureRole", "MAP sensor location"),
    F("revMax", "Maximum engine speed"),
])
panel("swEngineWest", "", [
    P("swReqFuel"),
    P("swEngine"),
    P("swBoard"),
])
redialog("hcSetupEngine", "Engine Constants", [
    P("swEngineWest", "West"),
    P("hcEngineFiring", "East"),
    P("hcEngineFiringExt", "South", "cylinders > 8"),
], layout="border", help_topic="hcHelpFiringOrder")

# ---- Injector Characteristics ---------------------------------------------
panel("swInjOpen", "Injector opening time", [
    P("deadtimeCurve"),
])
panel("swInjAngle", "Injector close angles", [
    F("injStrategy", "Injection mode"),
    F("injTimingMode", "Angle refers to"),
    F("injPhaseMode", "Injection angle from"),
    F("injStartDegX10", "Injection angle", "injPhaseMode == 0"),
    N("The angle table: Fuel > Injection timing table"),
])
# 2026-10-15: rusEFI's injector pressure compensation (injector dialog:
# injectorCompensationMode, fuelReferencePressure). Owner 2026-10-15: the
# WHOLE injector configuration in one window - flow and its compensation
# together (rusEFI injChars), then dead time, angles, outputs and the test.
panel("swInjPress", "Injector flow and fuel pressure", [
    F("injFlowCcMin", "Injector flow"),
    F("injPressMode", "Pressure compensation"),
    F("injRefPressureKpa", "Injector flow measured at", "injPressMode != 0"),
    F("fuelRegKpa", "Regulator pressure",
      "injPressMode == 1 || injPressMode == 2"),
    F("pinFuelPress", "Rail pressure sensor", "injPressMode == 3"),
    F("fuelSensorKpa", "Sensor pressure at 4.5 V", "injPressMode == 3"),
])
panel("swInjWest", "", [
    P("swInjPress"),
    P("swInjOpen"),
])
panel("swInjEast", "", [
    P("swInjAngle"),
    P("hcInjectorPins"),
    P("hcTestInjectors"),
])
redialog("hcFuelInjector", "Injector Characteristics", [
    P("swInjWest"),
    P("swInjEast"),
], layout="xAxis", help_topic="hcHelpInjMode")

# ---- Trigger Settings -------------------------------------------------------
panel("swTrigger", "Trigger Settings", [
    F("syncMode", "Trigger pattern"),
    F("syTeeth", "Primary base teeth"),
    F("syGap", "Missing teeth"),
    F("trigAngleX10", "Trigger angle (deg)"),
    T("This number represents the angle ATDC when"),
    T("tooth #1 passes the primary sensor."),
    B(),
    F("trigMinTeeth", "Teeth before sync"),
    T("Note: good teeth required before the injectors and"),
    T("coils are fired"),
    F("trigEdge", "Trigger edge"),
    F("camEnable", "Secondary trigger"),
    F("camEdge", "Secondary trigger edge", "camEnable == 1"),
    F("camPhaseLevel", "Level for 1st phase",
      "camEnable == 1 && camPhaseMode == 1"),
    F("camPhaseMode", "Secondary trigger type", "camEnable == 1"),
    F("camPhaseAngleX10", "Level check angle",
      "camEnable == 1 && camPhaseMode == 1"),
    F("cam1Pattern", "Cam 1 wheel", "camEnable == 1 && camPhaseMode == 2"),
    F("cam2Pattern", "Cam 2 wheel", "camEnable == 1 && camPhaseMode == 2"),
    F("cam2RefX10", "Cam 2 tooth 0 angle",
      "camEnable == 1 && camPhaseMode == 2"),
    F("camToothTol", "Cam tooth tolerance",
      "camEnable == 1 && camPhaseMode == 2"),
    F("camRefs", "Cam references per cycle",
      "camEnable == 1 && camPhaseMode == 0"),
    F("camRefX10", "First cam reference angle",
      "camEnable == 1 && camPhaseMode == 0"),
    F("camWindowX10", "Cam acceptance window", "camEnable == 1"),
    F("camPhaseConfirm", "Phase confirmations",
      "camEnable == 1 && camPhaseMode != 0"),
    F("trigGapRatioX10", "Trigger filter (gap ratio)"),
    F("trigTimeoutMs", "Stall timeout"),
    F("trigSource", "Trigger arming source"),
    F("pinCrank", "Crank sensor pin"),
    F("pinCam1", "Cam 1 pin", "camEnable == 1"),
    F("pinCam2", "Cam 2 pin", "camEnable == 1"),
])
redialog("hcSetupTrigger", "Trigger Settings", [
    P("swTrigger"),
], help_topic="hcHelpTrigger")

# ---- Engine Protection (Speeduino's group of windows) ----------------------
redialog("swProtCommon", "Common Engine Protection", [
    P("hcLimitsProtect"),
    P("hcProtLights"),
], layout="yAxis")
redialog("swProtRev", "Rev Limiters", [P("hcLimitsRev")])
redialog("swProtBoost", "Boost Cut", [P("hcLimitsBoost")])
redialog("swProtAfr", "AFR Protection", [P("hcProtLean")])
redialog("swProtPressure", "Pressure-loss Protection", [P("hcProtPressure")])
redialog("swProtOilDlg", "Oil Pressure Protection", [P("swProtOil")])

# ---- AFR/O2 --------------------------------------------------------------
panel("swEgo", "", [
    F("lambda1Source", "Sensor type"),
    N("Please calibrate your O2 sensor in the Tools menu"),
    F("stftEnable", "Closed loop correction"),
    F("stftLambdaMin", "Only correct above lambda", "stftEnable == 1"),
    F("stftLambdaMax", "and correct below lambda", "stftEnable == 1"),
    F("stftMinClt", "Active above coolant", "stftEnable == 1"),
    F("stftStartDelay", "EGO delay after start", "stftEnable == 1"),
    F("stftDeadband", "Deadband", "stftEnable == 1"),
    F("stftAfterDfco", "Hold after fuel cut", "stftEnable == 1"),
    F("stftAfterAe", "Hold after acceleration enrichment", "stftEnable == 1"),
])
panel("swEgoRegions", "Controller authority by region", [
    F("stftIdleRpm", "Idle below", "stftEnable == 1"),
    F("stftOverrunLoad", "Overrun below load", "stftEnable == 1"),
    F("stftPowerLoad", "Power above load", "stftEnable == 1"),
    E("stftMaxAdd", "stftEnable == 1"),
    E("stftMaxRemove", "stftEnable == 1"),
    E("stftTimeConst", "stftEnable == 1"),
])
redialog("hcStftDlg", "AFR/O2", [
    P("swEgo"),
    P("swEgoRegions"),
], layout="xAxis", help_topic="hcHelpLambda")

# ---- Spark Settings / Dwell -----------------------------------------------
panel("swSpark", "Spark Settings", [
    F("ignLoadMode", "Ignition load source"),
    F("ignStrategy", "Spark output mode"),
    F("ignAdvanceDegX10", "Cranking advance angle"),
])
panel("swSparkLocked", "Locked timing", [
    F("timingModeCfg", "Enabled fixed/locked timing"),
    F("fixedTimingX10", "Fixed angle", "timingModeCfg == 1"),
    N("Note: during cranking the cranking advance angle above applies"),
])
redialog("hcIgnitionHw", "Spark Settings", [
    P("swSpark"),
    P("swSparkLocked"),
], layout="yAxis", help_topic="hcHelpIgnition")
panel("swDwell", "Dwell Settings", [
    F("crankingDwellMsX100", "Cranking dwell"),
    T("0 = the running dwell curves below apply"),
    N("Running dwell, against battery voltage:"),
    P("dwellBattCurve"),
])
panel("swDwellRpm", "Dwell Compensation by rpm", [
    N("Multiplies the battery dwell; 100 % = no change"),
    P("dwellRpmCurve"),
])
redialog("hcDwellDlg", "Dwell Settings", [P("swDwell"), P("swDwellRpm")],
         layout="xAxis")

# ---- Sequential spark trims (rusEFI cylinder ignition trims) ---------------
panel("swIgnTrim", "Ignition trim per cylinder (deg, + = advance)", [
    E("ignTrim"),
    N("Cylinder numbers, not firing order. Not applied in fixed timing."),
])
redialog("hcIgnTrimDlg", "Sequential spark trims", [P("swIgnTrim")])

# ---- Cranking Settings / ASE ----------------------------------------------
panel("swCrankOpts", "", [
    F("crankRpmMax", "Cranking RPM (max)"),
    F("floodClearX10", "Flood clear level"),
    F("fuelPumpPrimeMs", "Fuel pump prime duration"),
    F("primeDelay", "Injectors priming delay"),
])
panel("swCrankEnrich", "Cranking Enrichment", [
    P("crankPwCurve"),
    N("Note"),
    T("Values are fuel mass per cylinder per cycle by coolant."),
])
panel("swCrankTiming", "Cranking Timing", [
    F("ignAdvanceDegX10", "Cranking advance angle"),
])
redialog("hcCrankingDlg", "Cranking Settings", [
    P("swCrankOpts", "North"),
    P("swCrankEnrich", "Center"),
    P("swCrankTiming", "South"),
], layout="border")
panel("swAseAmount", "Enrichment amount (%)", [
    T("Defines the fuel enrichment percentage after start."),
    T("This is needed to keep the engine running after start."),
    P("asCurve"),
])
panel("swAseTime", "Duration (s)", [
    T("How long the enrichment takes to fade out after start."),
    F("asDecayMs", "Transition time to disable", "transEnable == 1"),
])
redialog("hcAseDlg", "Afterstart Enrichment (ASE)", [
    N("Runs with transient fuel on (Fuel > Acceleration Enrichment)"),
    P("swAseAmount"),
    P("swAseTime"),
], layout="yAxis")

# ---- Idle Control / Idle Advance -------------------------------------------
panel("swIdle", "Idle Settings", [
    F("idleEnable", "Idle control type"),
    F("idleStartMs", "Crank to run taper", "idleEnable == 1"),
])
panel("swIdleCl", "Closed loop Idle", [
    F("idleKp", "P", "idleEnable == 1"),
    F("idleKi", "I", "idleEnable == 1"),
    F("idleRangeX10", "Trim authority (never more than 10 % throttle)", "idleEnable == 1"),
    F("idleRpmBand", "Active up to target +", "idleEnable == 1"),
    F("idlePedalX10", "Active below pedal", "idleEnable == 1"),
    F("etbIdleRange", "Idle throttle range (100 = position is throttle %)", "idleEnable == 1"),
])
panel("swIdleDash", "Dashpot", [
    F("idleDashX10", "Dashpot adder", "idleEnable == 1"),
    F("idleDashHoldMs", "Dashpot hold time",
      "idleEnable == 1 && idleDashX10 > 0"),
    F("idleDashDecayMs", "Dashpot decay time",
      "idleEnable == 1 && idleDashX10 > 0"),
])
redialog("hcIdleDlg", "Idle Settings", [
    P("swIdle"),
    P("swIdleCl"),
    P("swIdleDash"),
    P("hcIdleState"),
], layout="yAxis")
panel("swIdleAdv", "Idle Advance Settings", [
    F("idleTimingEnable", "Idle advance mode"),
    F("idleTimingKp", "Advance per rpm error", "idleTimingEnable == 1"),
    F("idleTimingMinX10", "Most retard", "idleTimingEnable == 1"),
    F("idleTimingMaxX10", "Most advance", "idleTimingEnable == 1"),
    F("idleTimingSoftMs", "Delay before idle control starts",
      "idleTimingEnable == 1"),
])
redialog("hcIdleTimingDlg", "Idle Advance Settings", [
    P("swIdleAdv"),
    P("idleTargetCurve"),
], layout="xAxis")

# ---- Accessories: Fuel pump / Tacho / Boost --------------------------------
redialog("swFuelPumpDlg", "Fuel pump", [
    F("pinFuelPump", "Fuel pump pin"),
    F("fuelPumpPrimeMs", "Fuel pump prime duration"),
    F("fuelPumpMode", "Fuel pump mode"),
    C("cmdTestPump", "Test fuel pump"),
    P("hcPanelPump"),
])
redialog("swTachoDlg", "Tacho", [
    F("pinTacho", "Output pin"),
    F("tachoScale", "Output scale (100 = exact, 0 = 100)"),
    C("cmdTachoTest", "Test: 3000 rpm for 6 s (engine stopped)"),
])

# ---- Accessories: thermo fan / A/C / programmable outputs / pressures -----
# (2026-10-14, hcaux711.c). Outputs: cavity 115 or 120 only - the CPU's
# spare low sides, also the cam solenoid stages.
panel("swFan", "Thermo Fan", [
    F("pinFan", "Fan output pin"),
    F("fanOnTemp", "Fan temperature SP (on)", "pinFan != 255"),
    F("fanOffTemp", "Fan off temperature", "pinFan != 255"),
    F("fanWithAc", "Fan on with the A/C compressor", "pinFan != 255"),
    F("fanStoppedOff", "Fan off when the engine is stopped", "pinFan != 255"),
    N("Output: cavity 115 or 120. A failed coolant sensor runs the fan."),
])
ipanel("swFanState", 2, [
    IND("(auxStatus & 1) > 0", "FAN OFF", "FAN ON"),
    IND("(auxStatus & 64) > 0", "OUTPUTS PERMITTED", "OUTPUTS HELD"),
])
redialog("swFanDlg", "Thermo Fan", [P("swFan"), P("swFanState")])
panel("swAc", "Air Conditioning Control", [
    F("pinAcRequest", "A/C request input"),
    F("acRequestActive", "A/C request is active when", "pinAcRequest != 255"),
    F("pinAcClutch", "A/C compressor output pin", "pinAcRequest != 255"),
    F("acDelay", "Compressor delay after request", "pinAcRequest != 255"),
    F("acIdleUpX10", "Idle up: throttle added", "pinAcRequest != 255"),
    F("acIdleRpm", "Idle up: target rpm added", "pinAcRequest != 255"),
    F("acMinRpm", "Compressor off below rpm", "pinAcRequest != 255"),
    F("acMaxRpm", "Compressor off above rpm (0 = none)", "pinAcRequest != 255"),
    F("acMaxTps", "Compressor off above throttle (0 = none)", "pinAcRequest != 255"),
    F("acMaxClt", "Compressor off above coolant", "pinAcRequest != 255"),
])
ipanel("swAcState", 1, [
    IND("(auxStatus & 2) > 0", "A/C NOT REQUESTED", "A/C REQUESTED"),
    IND("(auxStatus & 4) > 0", "COMPRESSOR OFF", "COMPRESSOR ON"),
    IND("((auxStatus >> 8) & 15) == 1", "-", "OFF: ENGINE NOT RUNNING"),
    IND("((auxStatus >> 8) & 15) == 2", "-", "OFF: RPM"),
    IND("((auxStatus >> 8) & 15) == 3", "-", "OFF: THROTTLE"),
    IND("((auxStatus >> 8) & 15) == 4", "-", "OFF: COOLANT"),
    IND("((auxStatus >> 8) & 15) == 5", "-", "WAITING: DELAY"),
])
redialog("swAcDlg", "Air Conditioning Control", [P("swAc"), P("swAcState")],
         layout="xAxis")
for _n in (1, 2):
    _on = "pinGp%d != 255" % _n
    _b = "pinGp%d != 255 && gp%dSrcB != 0" % (_n, _n)
    panel("swPrgOut%d" % _n, "Output %d" % _n, [
        F("pinGp%d" % _n, "Output pin"),
        F("gp%dSrcA" % _n, "Condition A: source", _on),
        F("gp%dOpA" % _n, "Condition A", _on),
        F("gp%dThrA" % _n, "Condition A: threshold", _on),
        F("gp%dHystA" % _n, "Condition A: hysteresis", _on),
        F("gp%dSrcB" % _n, "Condition B: source (Not used = A only)", _on),
        F("gp%dOpB" % _n, "Condition B", _b),
        F("gp%dThrB" % _n, "Condition B: threshold", _b),
        F("gp%dHystB" % _n, "Condition B: hysteresis", _b),
        F("gp%dLogic" % _n, "Combine", _b),
        F("gp%dDelay" % _n, "On delay", _on),
    ])
ipanel("swPrgOutState", 2, [
    IND("(auxStatus & 8) > 0", "OUTPUT 1 OFF", "OUTPUT 1 ON"),
    IND("(auxStatus & 16) > 0", "OUTPUT 2 OFF", "OUTPUT 2 ON"),
])
panel("swPrgOutCols", "", [P("swPrgOut1"), P("swPrgOut2")], layout="xAxis")
redialog("swPrgOutDlg", "Programmable outputs", [
    P("swPrgOutCols"), P("swPrgOutState"),
], layout="yAxis", help_topic="hcHelpPrgOut")
panel("swPressures", "Fuel/Oil pressure", [
    F("pinOilPress", "Oil pressure sensor pin"),
    F("oilSensLoMv", "Sensor voltage at 0 kPa", "pinOilPress != 255"),
    F("oilSensHiMv", "Sensor voltage at full scale", "pinOilPress != 255"),
    F("oilSensHiKpa", "Full scale pressure", "pinOilPress != 255"),
    N("Any analog input this ECU reads. Below 0.2 V or above 4.8 V is a fault."),
])
ipanel("swOilState", 1, [
    IND("(auxStatus & 32) > 0", "OIL PRESSURE: NO VALID READING", "OIL PRESSURE: VALID"),
])
redialog("swPressureDlg", "Fuel/Oil pressure", [P("swPressures"), P("swOilState")])
panel("swProtOil", "Oil Pressure Protection", [
    F("oilPressMinKpa", "Minimum oil pressure (0 = off)", "pinOilPress != 255"),
    F("oilPressMinRpm", "Check above rpm", "pinOilPress != 255"),
    F("oilPressDelay", "Low pressure for", "pinOilPress != 255"),
    N("Fuel cut until the engine stops; also if no pressure within 5 s of the start"),
])
panel("swBoost", "Boost Control", [
    F("boostEnable", "Boost control enabled"),
    F("boostMode", "Boost control type", "boostEnable == 1"),
    F("pinBoost", "Boost output pin", "boostEnable == 1"),
    F("boostMinRpm", "Active above rpm", "boostEnable == 1"),
    F("boostMinTpsX10", "Active above throttle", "boostEnable == 1"),
    P("hcLimitsBoost"),
    T("Closed loop settings"),
    F("boostClMinKpa", "Closed loop above pressure",
      "boostEnable == 1 && boostMode == 1"),
    F("boostIBand", "Integrate within", "boostEnable == 1 && boostMode == 1"),
    F("boostKp", "P", "boostEnable == 1 && boostMode == 1"),
    F("boostKi", "I", "boostEnable == 1 && boostMode == 1"),
    F("boostKd", "D", "boostEnable == 1 && boostMode == 1"),
])
redialog("hcBoostDlg", "Boost Control", [P("swBoost")])
redialog("swBoostLoadDlg", "Boost Targets/Duty", [
    F("boostMode", "Mode"),
    P("swBoostTgt"),
    P("swBoostDuty"),
], layout="yAxis")
panel("swBoostTgt", "Boost target table (closed loop)", [P("boostTgtTbl")])
panel("swBoostDuty", "Base duty table (open loop)", [P("boostDutyTbl")])


SEP = ("SEP", None)
NOT_USED = " (not used)"
# tables shown INSIDE a window (with their options), not as a bare grid:
# gen_ts_ui_me711.table_dialog_lines() emits no separate grid dialog
EMBEDDED_TABLES = {"boostTgtTbl", "boostDutyTbl", "veTableTbl", "ignMapTbl", "afrMapTbl", "injPhaseTbl"}

# THE FUEL MODEL: one dialog that owns every setting deciding how air is
# estimated - the model, the legacy variant, where the pressure sensor
# measures, which pressure the air density uses, and the table loads - with
# what is configured and what runs, in words, beside it. Theory and formulas
# live in the maintainer's design notes, not here.
panel("hcLoadPolicyPanel", "Fuel model", [
    T("#Air per cylinder = air density x cylinder volume x VE, with the VE"),
    T("#table looked up on rpm and the VE table axis."),
    F("fuelModel"),
    F("loadSource", None, "fuelModel == 0"),
    F("alphaNUseIat", None, "fuelModel == 0 && loadSource == 2"),
    B(),
    T("#Pressure sensor and air density"),
    F("pressureRole"),
    F("densityPolicy", None, "fuelModel != 0"),
    F("densityReference", None, "fuelModel != 0"),
    F("fuelUseIat", None, "fuelModel != 0"),
    F("chargeBlendStart", None, "fuelModel == 3 && densityPolicy == 2"),
    F("chargeBlendFull", None, "fuelModel == 3 && densityPolicy == 2"),
    B(),
    T("#Ignition and target lambda table loads"),
    F("ignLoadMode"),
    F("lambdaLoadMode"),
    P("hcPanelTableAxes"),
])

rpanel("hcReadLoadModel", 2, ["veValueGauge", "veAxisInputGauge",
                              "densityPressureGauge", "densityTemperatureGauge",
                              "ambientUsedGauge", "pressureMeasuredGauge",
                              "airMgX10Gauge", "baseFuelMassGauge"])

panel("hcLoadModelInfo", "", [
    P("hcPanelLoadSummary"),
    T("#Pure Alpha-N: VE by throttle; density from the reference pressure,"),
    T("#  optionally corrected for ambient. No pressure sensor needed."),
    T("#Speed density: VE by manifold pressure; density from the same"),
    T("#  measured manifold pressure. Needs a manifold (MAP) sensor."),
    T("#Boosted Alpha-N: VE by throttle; density from the charge pressure"),
    T("#  before the throttle - measured, or ambient + boost blend. For"),
    T("#  engines whose only sensor is before the throttle (VAG 1.8T AWT)."),
    T("#Choose by load model: Load model picks Speed density, Alpha-N +"),
    T("#  measured pressure or Pure Alpha-N; existing tunes run unchanged."),
    T("!Changing the model does not rescale the VE table - retune it."),
])

dialog("hcLoadPolicies", "Fuel model", [
    P("hcLoadPolicyPanel", "West"),
    P("hcLoadModelInfo", "East"),
], layout="border", help_topic="hcHelpPressure")

MENU = [
    ("&Setup", [
        ("hcSetupEngine", "Engine Constants"),
        ("hcSetupTrigger", "Trigger Setup"),
        ("hcTriggerLiveDlg", "Trigger live check"),
        SEP,
        ("hcSetupOutputs", "Outputs"),
        SEP,
        ("GROUP", "Engine Protection", [
            ("swProtCommon", "Common Engine Protection"),
            ("swProtRev", "Rev Limiters"),
            ("swProtBoost", "Boost Cut"),
            ("swProtAfr", "AFR Protection"),
            ("swProtPressure", "Pressure-loss Protection"),
            ("swProtOilDlg", "Oil Pressure Protection"),
        ]),
    ]),

    ("&Fuel", [
        ("hcLoadPolicies", "Fuel model"),
        ("hcFuelInjector", "Injector Characteristics"),
        ("hcVeDlg", "VE Table"),
        ("hcLambdaTblDlg", "Lambda Target Table"),
        ("hcInjTimingTblDlg", "Injection timing table"),
        SEP,
        ("hcAccelDlg", "Acceleration Enrichment"),
        ("hcStftDlg", "AFR/O2"),
        SEP,
        ("mapEstimateTblEdit", "Pressure estimate (sensor fault)"),
    ]),

    ("&Ignition", [
        ("hcIgnitionHw", "Spark Settings"),
        ("hcIgnTblDlg", "Spark Table"),
        ("hcDwellDlg", "Dwell settings"),
        ("hcIgnTrimDlg", "Sequential spark trims"),
        ("ignIatCorrCurve", "IAT Retard"),
        ("ignBoostCorrCurve", "Boost Retard"),
        ("ignCltCorrCurve", "Cold Advance"),
        SEP,
        ("hcIgnOutDlg", "Ignition outputs"),
        SEP,
        ("hcKnockDlg", "Knock Settings"),
        ("hcKnockAdvDlg", "Knock sensor calibration (advanced)"),
    ]),

    ("&Cranking", [
        ("hcCrankingDlg", "Cranking Settings"),
        ("primeCurve", "Priming Pulsewidth"),
        ("cltEnrCurve", "Warmup Enrichment"),
        ("hcAseDlg", "Afterstart Enrichment (ASE)"),
    ]),

    ("&Idle", [
        ("hcIdleDlg", "Idle Control"),
        ("idleTargetCurve", "Idle - RPM targets"),
        ("idleBaseCurve", "Idle - throttle position"),
        SEP,
        ("hcIdleTimingDlg", "Idle Advance Settings"),
    ]),

    ("&Advanced", [
        ("hcMotorsportDlg", "Launch Control / Flat Shift"),
        ("swFuelPumpDlg", "Fuel Pump"),
        ("hcAlsDlg", "Anti-lag / pit limiter"),
        SEP,
        ("GROUP", "VVT", [
            ("hcVvtDlg", "VVT outputs and PID"),
            ("vvtTarget1TblEdit", "VVT cam 1 (intake) target"),
            ("vvtTarget2TblEdit", "VVT cam 2 (exhaust) target"),
        ]),
        SEP,
        ("hcBoostDlg", "Boost Control"),
        ("swBoostLoadDlg", "Boost Targets/Duty"),
        ("boostCltCurve", "Boost duty by coolant"),
        ("boostIatCurve", "Boost duty by intake air"),
        SEP,
        ("swTachoDlg", "Tacho Output"),
        ("swFanDlg", "Thermo Fan"),
        ("swAcDlg", "Air Conditioning Control"),
        ("swPrgOutDlg", "Programmable outputs"),
        ("swPressureDlg", "Fuel/Oil pressure"),
        SEP,
        ("GROUP", "Electronic throttle (ETB)", [
            ("hcEtbMain", "Electronic Throttle Body"),
            ("pedalMapTblEdit", "Pedal target"),
            ("hcEtbSetupDlg", "Limits and bench test"),
            ("hcEtbCommissionDlg", "AutoCal results"),
            ("hcEtbCharacterizeDlg", "Characterization"),
            ("dbwBiasCurve", "Bias curve (feed forward)"),
            ("hcEtbCharDetailDlg", "Characterization raw data (developer)"),
        ]),
    ]),

    # 2026-10-11 (owner): the sensor calibrations in TunerStudio's OWN Tools
    # menu, as Speeduino does (speeduino.ini: menuDialog = main, menu =
    # "Tools", "Calibrate TPS" ... "Calibrate AFR Sensor"); TunerStudio merges
    # a menu called "Tools" into its own. rusEFI has a top-level Sensors
    # menu instead - the owner chose Speeduino's arrangement.
    ("Tools", [
        ("hcEtbTpsCalDlg", "Calibrate TPS"),
        ("hcEtbAppCalDlg", "Calibrate pedal sensor"),
        ("hcSensorMapDlg", "Calibrate pressure sensor (MAP)"),
        ("hcSensorBaroDlg", "Barometric sensor (onboard)"),
        ("hcSensorCltDlg", "Calibrate coolant temperature sensor"),
        ("hcSensorIatDlg", "Calibrate intake air temperature sensor"),
        ("hcSensorLambdaDlg", "Calibrate AFR sensor (wideband)"),
        ("hcSensorBatteryDlg", "Calibrate voltage reading"),
        ("hcSensorMiscDlg", "MAF input"),
    ]),
]

# Controller, Diagnostics and Help are appended by the generator, because
# their dialogs are declared there (the command buttons must be checked
# against the
# [ControllerCommands] block that same file emits).


# ==========================================================================
# 5. PLACEMENT COMPLETENESS.
#
# A hand-authored UI can silently lose a setting. A generated one could not.
# So this is a HARD CHECK: every model field is in a panel, in a table, in a
# curve, or named here with a reason.
# ==========================================================================
NOT_SHOWN = {
    # 2026-10-16 (owner): the ambient is always the onboard sensor - the
    # firmware reads neither field any more (layout kept)
    "ambientSource": "retired: the onboard sensor is always the ambient",
    "ambientCorrection": "retired: Pure Alpha-N always uses the onboard ambient",
    "v102Pad": "alignment only",
    "pad77": "alignment only",
    # Seeds the ambient value for the first main-loop pass after power-up;
    # from then on the Ambient pressure source decides (hcload711.c). Not a
    # setting a tuner should meet.
    "baroDefault": "power-up seed only - Tools > Barometric sensor "
                   "chooses the ambient source",
    "transPad": "alignment byte after transEnable",
    "idleTimingPad": "alignment byte after idleTimingEnable",
    "seqPad": "alignment byte after injTimingMode",
    "celPad": "alignment byte after celTestEnable",
    "dbwPad": "alignment byte after dbwBattComp",
    # idlePad is NOT here, and that is deliberate - see hcNvmTest. It is the
    # byte the maintainer's design records has the operator edit, Burn
    # and power-cycle, so a .ini that hides it makes P3 impossible to perform.
    "ignPad": "alignment pad - no runtime path reads it",
    # V84: the manual output arm is RETIRED. The byte stays in
    # the page for layout-id stability; showing it would be a dead knob.
    "outputsArmedCfg": "retired V84 - no firmware path reads it on ME7.1.1",
    "revlimPattern": "retired 2026-10-14 - the spark cut skips every spark",
    "pwmPad": "alignment pad - no runtime path reads it",
    "msPad": "alignment pad - no runtime path reads it",
    "camPad": "alignment pad - no runtime path reads it",
    "camPhasePad": "alignment pad - no runtime path reads it",
    "camPatPad": "alignment pad - no runtime path reads it",

    # SIX DBW CALIBRATIONS NO LINKED MODULE READS. V67 captioned them "NOT
    # IMPLEMENTED" and left them settable; V74 removes the CONTROL, because a
    # caption is read once and a field is used. The page bytes stay reserved,
    # so HC_CFG_LAYOUT_ID and TGT_SIGNATURE do not move and no existing .ini is
    # invalidated - only the field= lines are gone, and the panels say in words
    # that the feature does not exist.
    #
    # ts_ini_dead_knob_proof holds this from the other side: it recomputes
    # which CAL_DBW_* slots no linked module reads and requires the set to be
    # exactly these six AND none of them to be a settable field. Implement one
    # and it leaves that set, and the gate then makes you put its field back.
    "v98Pad": "alignment pad - no runtime path reads it",
}


def _field_names(items):
    """Every model field name an item list binds, recursively through P()."""
    out = set()
    for it in items:
        if it[0] in ("f", "e"):
            out.add(it[1])
        elif it[0] == "b":
            out.add(UI.BIT_VIEWS[it[1]][0])
    return out


def placed_fields():
    out = set()
    for _pid, _t, items in PANELS:
        out |= _field_names(items)
    for _d, _t, items, _l, _h in WORKFLOWS:
        out |= _field_names(items)
    return out


def editor_fields():
    out = set()
    for t in UI.TABLES:
        out |= {t[1], t[2], t[4]}
    for c in UI.CURVES:
        out |= {c[1], c[2]}
    return out


def place_report():
    fields, by_ts, _consts = UI.layout()
    have = placed_fields()
    ed = editor_fields()
    problems = []

    for f in fields:
        ts = f.meta.ts
        if ts in have or ts in ed or ts in NOT_SHOWN:
            continue
        problems.append("model field %s (%s / %s) is in no panel, no editor "
                        "and no NOT_SHOWN entry" % (ts, f.meta.category,
                                                    f.meta.label))

    for ts in sorted(have):
        if ts not in by_ts:
            problems.append("panel names %s, which is not a model field" % ts)

    for ts in sorted(UNUSED):
        if ts not in by_ts:
            problems.append("UNUSED names %s, which is not a model field" % ts)
        if ts in NOT_SHOWN:
            problems.append("%s is both UNUSED and NOT_SHOWN" % ts)

    for ts in sorted(NOT_SHOWN):
        if ts not in by_ts:
            problems.append("NOT_SHOWN names %s, which is not a model field"
                            % ts)
        if ts in have:
            problems.append("%s is both placed and in NOT_SHOWN" % ts)

    # Every P() must name a panel that exists.
    known = {p[0] for p in PANELS} | {p[0] for p in IND_PANELS} \
        | {p[0] for p in READ_PANELS} | {c[0] for c in UI.CURVES} \
        | {t[0] for t in UI.TABLES}
    for src, items in ([(p[0], p[2]) for p in PANELS]
                       + [(d[0], d[2]) for d in WORKFLOWS]):
        for it in items:
            if it[0] == "p" and it[1] not in known:
                problems.append("%s references panel %s, which is not declared"
                                % (src, it[1]))

    # Every array field placed with E() must be one the page emits per-element
    # aliases for, or TunerStudio gets `field` on an array and asks for
    # array1D - the shape no .ini in this repository that loads has ever used.
    for _pid, _t, items in PANELS:
        for it in items:
            if it[0] == "e" and it[1] not in UI.ELEMENT_FIELDS:
                problems.append("E(%s) has no per-element alias in "
                                "gen_ts_ui_me711.ELEMENT_FIELDS" % it[1])
    return problems, len(have), len(ed), len(fields)


# ==========================================================================
# 6. EMISSION.
#
# Everything below turns the declarations above into [UiDialogs] text. The
# generator passes in what only IT knows - which gauges it emitted, which
# commands it emitted, and the dynamically built indicator lists - so a panel
# can never name a gauge or a button that does not exist.
# ==========================================================================
def _unused_suffix(ts):
    if ts not in UNUSED:
        return ""
    return UNUSED_SUFFIX.get(_unused_class(ts), " (not used)")


def _label(by_ts, ts, override):
    if override:
        return override + _unused_suffix(ts)
    return _label_base(by_ts, ts) + _unused_suffix(ts)


def _label_base(by_ts, ts):
    m = by_ts[ts].meta
    lbl = m.label.replace('"', "'")
    if m.is_pin:
        # WAS "(cavity 1..121, 255 = none)", which told the tuner to type a
        # number into a field that is now a capability-filtered dropdown. The
        # list already names every cavity this board can use for the job, so
        # the instruction is not just redundant, it is wrong.
        lbl = "%s (cavity)" % lbl
    return lbl


def _q(s):
    return s if s.startswith("{") else '"%s"' % s


# 2026-10-11 COMPACT DIALOGS (owner: every window needs zooming on a
# laptop). A run of "#" note lines - two or more, or one longer than 50
# characters - is not drawn in the dialog: it goes into the dialog's help
# topic (TunerStudio's "?" button), generated per dialog when it has none.
# Short one-line headings stay. Nothing is lost: gen_ts_ini_me711 writes
# NOTE_TOPICS with the other help topics.
COMPACT_NOTES = True
NOTE_TOPICS: dict = {}          # topic id -> (title, [paragraphs])
_PANEL_NOTES: dict = {}         # panel id -> [paragraphs]


def _split_notes(items):
    """-> (items without the long note runs, [paragraphs])"""
    if not COMPACT_NOTES:
        return list(items), []
    out, paras, run = [], [], []

    def flush():
        if not run:
            return
        texts = [t[1][1:].strip() for t in run]
        if len(run) >= 2 or len(texts[0]) > 50:
            paras.append(" ".join(texts))
        else:
            out.extend(run)
        del run[:]
    for it in items:
        if it[0] == "t" and it[1].startswith("#"):
            run.append(it)
            continue
        flush()
        out.append(it)
    flush()
    return out, paras


def _dialog_notes(items, seen=None):
    """the note paragraphs of a dialog: its own and every panel it embeds"""
    seen = set() if seen is None else seen
    paras = []
    for it in items:
        if it[0] == "p" and it[1] not in seen:
            seen.add(it[1])
            paras += _PANEL_NOTES.get(it[1], [])
            sub = _PANEL_ITEMS.get(it[1])
            if sub:
                paras += _dialog_notes(sub, seen)
    return paras


_PANEL_ITEMS: dict = {}


def _num(v):
    """a settingOption value: integer when it is one"""
    return ("%d" % v) if float(v).is_integer() else ("%.2f" % v).rstrip("0")


def _emit_items(out, items, by_ts, indent="      "):
    for it in items:
        kind = it[0]
        if kind == "t":
            out.append('%sfield = "%s"' % (indent, it[1].replace('"', "'")))
        elif kind == "n":
            out.append('%sfield = "#%s"' % (indent, it[1].replace('"', "'")))
        elif kind == "f":
            ts, override, guard = it[1], it[2], it[3]
            line = '%sfield = "%s", %s' % (indent, _label(by_ts, ts, override),
                                           ts)
            if guard:
                line += ", { %s }" % guard
            out.append(line)
        elif kind == "b":
            alias, guard = it[1], it[2]
            line = '%sfield = "%s", %s' % (indent, UI.BIT_VIEWS[alias][2],
                                           alias)
            if guard:
                line += ", { %s }" % guard
            out.append(line)
        elif kind == "e":
            ts, guard = it[1], it[2]
            f = by_ts[ts]
            fmt, cyl_guard = UI.ELEMENT_FIELDS[ts]
            base = 1 if ts != "tdcCylExtDegX10" else 9
            for i in range(f.count):
                n = base + i
                line = '%sfield = "%s", %s%d' % (
                    indent, UI.element_label(fmt, n, base) + _unused_suffix(ts),
                    ts, n)
                g = guard or cyl_guard
                if g == "cylinders":
                    line += ", { cylinders >= %d }" % n
                elif g and cyl_guard == "cylinders":
                    line += ", { (%s) && cylinders >= %d }" % (g, n)
                elif g:
                    line += ", { %s }" % g
                out.append(line)
        elif kind == "s":
            label, options, guard = it[1], it[2], it[3]
            line = '%ssettingSelector = "%s"' % (indent, label)
            if guard:
                line += ", { %s }" % guard
            out.append(line)
            for name, sets in options:
                out.append('%s   settingOption = "%s", %s' % (
                    indent, name.replace('"', "'"),
                    ", ".join("%s=%s" % (f, _num(v)) for f, v in sets)))
        elif kind == "g":
            out.append("%sgauge = %s" % (indent, it[1]))
        elif kind == "r":
            out.append("%sreadout = %s" % (indent, it[1]))
        elif kind == "l":
            gid, title, where, chans = it[1], it[2], it[3], it[4]
            out.append('%sliveGraph = %s, "%s", %s' % (indent, gid, title,
                                                        where))
            for ch in chans:
                out.append("%s   graphLine = %s" % (indent, ch))
        elif kind == "p":
            pid, where, guard = it[1], it[2], it[3]
            line = "%spanel = %s" % (indent, pid)
            if where:
                line += ", " + where
            elif guard:
                line += ", Center"
            if guard:
                line += ", { %s }" % guard
            out.append(line)
        elif kind == "v":
            out.append("%spanel = %s, {1}, { %s }" % (indent, it[1], it[2]))
        elif kind == "c":
            cmd, lbl, guard = it[1], it[2], it[3]
            line = '%scommandButton = "%s", %s' % (indent, lbl, cmd)
            if guard:
                line += ", { %s }" % guard
            out.append(line)
        elif kind == "i":
            expr, off, on, col = it[1], it[2], it[3], it[4]
            line = "%sindicator = { %s }, %s, %s" % (indent, expr, _q(off),
                                                     _q(on))
            if col:
                line += ", " + col
            out.append(line)
        else:
            raise SystemExit("unknown UX item %r" % (it,))


def emit(by_ts, gauges, commands, dynamic):
    """The whole [UiDialogs] body this module owns, as lines.

    `dynamic` maps an indicator-panel id whose content is None to ready-made
    `indicator = ...` lines - the mask decoders, which ts_semantics_me711
    builds from the firmware's own headers and which must not be retyped."""
    out = []
    problems = []

    # Indicator panels first: rusEFI declares them before the dialogs that
    # embed them, and a reader follows the file top to bottom.
    for pid, cols, items in IND_PANELS:
        out.append("   indicatorPanel = %s, %d" % (pid, cols))
        if items is None:
            lines = dynamic.get(pid)
            if lines is None:
                problems.append("indicatorPanel %s has no static content and "
                                "the generator supplied none" % pid)
                lines = []
            out.extend(lines)
        else:
            _emit_items(out, items, by_ts)
        out.append("")

    for pid, cols, items in READ_PANELS:
        out.append("   readoutPanel = %s, %d" % (pid, cols))
        _emit_items(out, items, by_ts)
        out.append("")

    NOTE_TOPICS.clear()
    _PANEL_NOTES.clear()
    _PANEL_ITEMS.clear()
    for pid, title, items in PANELS:
        _PANEL_ITEMS[pid] = items
    for pid, title, items in PANELS:
        head = '   dialog = %s, "%s"' % (pid, title)
        if PANEL_LAYOUT.get(pid):
            head += ", " + PANEL_LAYOUT[pid]
        out.append(head)
        kept, paras = _split_notes(items)
        _PANEL_NOTES[pid] = paras
        _emit_items(out, kept, by_ts)
        out.append("")

    for did, title, items, layout, help_topic in WORKFLOWS:
        head = '   dialog = %s, "%s"' % (did, title)
        if layout:
            head += ", " + layout
        out.append(head)
        kept, paras = _split_notes(items)
        paras += _dialog_notes(items)
        if paras and not help_topic:
            help_topic = "hcNotes_" + did
        if paras:
            t0, p0 = NOTE_TOPICS.get(help_topic, (title, []))
            NOTE_TOPICS[help_topic] = (t0, p0 + [p for p in paras
                                                 if p not in p0])
        if help_topic:
            out.append('      topicHelp = "%s"' % help_topic)
        _emit_items(out, kept, by_ts)
        out.append("")

    # The honesty checks, run on what was ACTUALLY emitted rather than on the
    # plan that produced it - V37's unreachable dialog is why.
    for line in out:
        m = line.strip()
        if m.startswith("gauge = ") or m.startswith("readout = "):
            g = m.split("=", 1)[1].strip()
            if gauges is not None and g not in gauges:
                problems.append("%s names a gauge that is not in "
                                "[GaugeConfigurations]" % m)
        if m.startswith("graphLine = "):
            g = m.split("=", 1)[1].strip() + "Gauge"
            if gauges is not None and g not in gauges:
                problems.append("%s names a channel with no gauge / not an "
                                "output channel" % m)
        if m.startswith("commandButton = "):
            c = m.split(",")[-1].strip().split("{")[0].strip().rstrip(",")
            if commands is not None and c and c not in commands:
                problems.append("%s names a command that is not in "
                                "[ControllerCommands]" % m)
    return out, problems


def emit_menu(extra_tail, declared):
    """[Menu] lines. `extra_tail` is (label, entries) appended after MENU -
    Bench and Diagnostics, whose dialogs the generator declares itself."""
    out = []
    seen = set()
    problems = []

    def entry(kw, did, title, depth):
        if did in seen:
            problems.append("%s is in the menu twice - a dialog reachable "
                            "from two places is a menu that lies about where "
                            "a setting lives" % did)
            return
        if declared is not None and did not in declared                 and not did.startswith("std_"):
            problems.append("menu names %s, which no dialog, table or curve "
                            "declares" % did)
            return
        seen.add(did)
        out.append('%s%s = %s, "%s"' % (" " * depth, kw, did, title))

    for label, entries in list(MENU) + list(extra_tail):
        out.append('      menu = "%s"' % label)
        for e in entries:
            if e[0] == "SEP":
                out.append("         subMenu = std_separator")
            elif e[0] == "GROUP":
                out.append('         groupMenu = "%s"' % e[1])
                for cdid, ctitle in e[2]:
                    entry("groupChildMenu", cdid, ctitle, 12)
            else:
                entry("subMenu", e[0], e[1], 9)
    return out, problems, seen


# ==========================================================================
# 7. THE DEFAULT DASHBOARD.
#
# rusEFI's [FrontPage] is eight gauges - RPM, CLT, TPS, MAP, AFR, VBatt, dwell,
# ignition advance (rusefi_proteus_f7.ini:6076-6083) - and a strip of
# indicators a DRIVER acts on.
#
# HaniCore's was RPM, crank sync, cycle sync, tooth index, gap candidate, sync
# loss count, sync loss reason and scheduler queue depth, followed by 41
# indicators including asicInit, asicStarted, badVecBit, wdtFed and
# rxTickRunning. That is a trigger-development screen, and it was the default
# one every user met. All of it still exists, under Diagnostics.
#
# THE EIGHT ARE rusEFI's EIGHT, mapped to HaniCore's channels one for one.
# ==========================================================================
# V98 (real TunerStudio): the FAST-BLOCK channels (ts_gauges_me711.FAST_TWINS)
# - the old-offset twins are titled "(raw block)" and cost the fast poll.
# 2026-10-11 round 2 (owner: Speeduino's default screen): Speeduino's eight -
# engine speed, throttle, pulse width, duty / MAP, inlet air, coolant,
# mixture (measured lambda: HaniCore has no AFR channel).
FRONT_GAUGES = [
    "RPMValueGauge",
    "TPSValueGauge",
    "injectorPulseWidthGauge",
    "injectorDutyGauge",
    "MAPValueGauge",
    "intakeGauge",
    "coolantGauge",
    "lambdaValueGauge",
]
_OLD_FRONT_GAUGES = [
    "RPMValueGauge",       # rusEFI RPMGauge
    "coolantGauge",        # rusEFI CLTGauge
    "TPSValueGauge",       # rusEFI TPSGauge
    "MAPValueGauge",       # rusEFI MAPGauge
    # 2026-10-11 (owner: the car test must SEE the essentials): the measured
    # lambda beside its target and the injector duty replace the target AFR,
    # battery and dwell - the battery has its own BATT FAULT lamp below,
    # dwell is under Ignition. rusEFI's slots 5..7 (afr1, VBatt, dwell)
    # assume a working wideband and a known fuel system; this car has neither
    # proven yet.
    "lambdaValueGauge",    # rusEFI lambdaGauge (0 = withheld, see LAMBDA lamp)
    "targetLambdaGauge",   # rusEFI targetLambdaGauge
    "injectorDutyGauge",   # rusEFI injectorDutyCycleGauge
    "ignitionTimingGauge",  # rusEFI correctedIgnAdvGauge
]

# rusEFI's own front-page ordering: the critical-error line first (TunerStudio
# LOOKS for it), then unsaved changes, then what stops an engine, then what
# merely informs. EVERY ONE IS SOMETHING A PERSON DOES SOMETHING ABOUT.
#
# V97: SHORT LABELS, READ AT A GLANCE. No fallback
# values, no firmware state names, no sentences - the detail is in the
# settings dialog, Diagnostics and help. The supervisor (ASIC link) line
# and the bench-safe bit moved to Diagnostics; noSync duplicated crankSync;
# the non-volatile / pending-staging lines are Diagnostics > Calibration
# storage.
#
# 2026-10-11 (owner, Speeduino's default screen): WHAT THE ENGINE IS DOING
# comes first - Running, Cranking, ASE, WUE, Accel, DFCO, closed loop,
# idle, the limiters and protections - each "X OFF" / "X", lit while it
# acts; the faults follow. Every expression is a published state bit
# (engineFlags, seqActive, idleState, limpCut, fuelCut, knockRetardMax),
# through named flag channels: the .dash encodes a bare `&` wrongly.
FRONT_INDICATORS = [
    ("flagRunning", "NOT RUNNING", "RUNNING", GREEN),
    ("flagCranking", "NOT CRANKING", "CRANKING", GREEN),
    ("crankSync", "NO CRANK SYNC", "CRANK SYNC", GREEN),
    ("cycleSync", "NO PHASE SYNC", "PHASE SYNC", GREEN),
    ("seqActive != 0", "BATCH / WASTED", "SEQUENTIAL", GREEN),
    ("flagAse", "ASE OFF", "ASE", GREEN),
    ("flagWarmup", "WUE OFF", "WUE", GREEN),
    ("flagTransient", "ACCEL OFF", "ACCEL ENRICH", GREEN),
    ("flagDfco", "DFCO OFF", "DFCO", GREEN),
    ("flagStft", "OPEN LOOP", "CLOSED LOOP", GREEN),
    ("flagIdleCtrl", "IDLE CTRL OFF", "IDLE CONTROL", GREEN),
    ("flagRevLimit", "REV LIMIT OFF", "REV LIMIT", RED),
    ("limpCut != 0", "PROTECT OFF", "ENGINE PROTECT", RED),
    ("flagBoostCut", "BOOST CUT OFF", "BOOST CUT", RED),
    ("knockRetardMax > 0", "KNOCK OFF", "KNOCK RETARD", YELLOW),
    ("flagLaunch", "LAUNCH OFF", "LAUNCH", YELLOW),
    ("flagFlatShift", "FLAT SHIFT OFF", "FLAT SHIFT", YELLOW),
    ("flagMapEst", "MAP MEASURED", "MAP ESTIMATE", YELLOW),
    ("setupFault", "CONFIG OK", "CONFIG ERROR", RED),
    ("nvmNotBurned", "TUNE SAVED", "BURN PENDING", YELLOW),
    # THE POLARITY IS THE EXPRESSION'S, NOT THE WISH'S. TunerStudio shows the
    # SECOND caption when the expression is TRUE. rusEFI writes the cut
    # indicators as `{ fuelCutReason != 0 }, "Injection OK", "Fuel cut"` for
    # exactly this reason, and writing `== 0` with the captions in that order
    # lights "FUEL CUT" on a healthy engine.
    ("fuelCut != 0", "FUEL OK", "FUEL CUT", YELLOW),
    ("dbwFaults != 0", "DBW OK", "DBW FAULT", YELLOW),
    # V97: the MIL request (rusEFI's check-engine line). The DTC framework
    # owns it - a stored code alone does not light it (the maintainer's design notes).
    ("dtcMil", "CEL", "CEL", RED),
    # bank 1 lambda is a fresh measurement (lam1Why 0); the reason it is
    # not is the "Lam why" gauge / Diagnostics > Wideband
    ("flagLambdaOk", "LAMBDA WAIT", "LAMBDA OK", GREEN),
    ("sensorsValid", "SENSOR FAULT", "SENSORS OK", GREEN),
    ("outputsPermitted", "OUTPUTS BLOCKED", "OUTPUTS OK", GREEN),
    # V75: these two were `mainRelayMode == 2` - lit for AUTO whether or not
    # anything was requested - and `fuelPumpState == 3`, which can never be
    # true once a cavity is routed, because the word also carries the request
    # in bit 8 and the cavity in bits 9..15. They now show the PIN.
    ("mainRelayPinOn", "MAIN RELAY", "MAIN RELAY", GREEN),
    ("fuelPumpPinOn", "FUEL PUMP", "FUEL PUMP", GREEN),
    ("nvmBurnFailed", "BURN OK", "BURN FAILED", RED),
    ("nvmOnDefaults", "TUNE LOADED", "DEFAULT TUNE", RED),
    ("cltError", "CLT OK", "CLT FAULT", RED),
    ("iatError", "IAT OK", "IAT FAULT", RED),
    ("mapError", "PRESSURE OK", "PRESSURE FAULT", RED),
    ("vbatError", "BATT OK", "BATT FAULT", RED),
    ("tps1Error", "TPS1 OK", "TPS1 FAULT", RED),
    ("tps2Error", "TPS2 OK", "TPS2 FAULT", RED),
    ("tpsPairError", "TPS OK", "TPS MISMATCH", RED),
    ("app1Error", "PEDAL1 OK", "PEDAL1 FAULT", RED),
    ("app2Error", "PEDAL2 OK", "PEDAL2 FAULT", RED),
    ("appPairError", "PEDAL OK", "PEDAL MISMATCH", RED),
    ("flagBenchTest", "BENCH IDLE", "BENCH TEST", YELLOW),
]


def front_page_lines(gauges):
    out = ["[FrontPage]", ""]
    problems = []
    for i, g in enumerate(FRONT_GAUGES, 1):
        if gauges is not None and g not in gauges:
            problems.append("front page names gauge %s, which does not exist"
                            % g)
        out.append("   gauge%d = %s" % (i, g))
    out.append("")
    for expr, off, on, col in FRONT_INDICATORS:
        out.append("   indicator = { %s }, %s, %s, %s"
                   % (expr, _q(off), _q(on), col))
    out.append("")
    return out, problems


if __name__ == "__main__":
    probs, nplaced, ned, ntotal = place_report()
    print("%d model fields: %d in panels, %d in editors, %d not shown"
          % (ntotal, nplaced, ned, len(NOT_SHOWN)))
    print("%d panels, %d indicator panels, %d readout panels, %d dialogs"
          % (len(PANELS), len(IND_PANELS), len(READ_PANELS), len(WORKFLOWS)))
    for p in probs:
        print("  PROBLEM: " + p)
    raise SystemExit(1 if probs else 0)
