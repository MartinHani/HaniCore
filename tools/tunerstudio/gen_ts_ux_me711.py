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
    `panel = x, {1}, { condition }` (rusefi_proteus_f7.ini:8786). The
    trouble-code list uses it so an empty slot is not a row."""
    return ("v", panel, visible)


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
    "oilPressMinKpa": "no oil pressure input exists yet",
    "oilPressMinRpm": "no oil pressure input exists yet",
    "boostFreqHz": "N75 runs at the 10 ms ASIC frame quantum",
    "lambda1Bank": "closed loop trims every cylinder from its sensor",
    "lambda1AuthPct": "the closed-loop limits are per region (Fuel menu)",
    "lambda1CylMask": "closed loop trims every cylinder from its sensor",
    "lambda2Bank": "closed loop trims every cylinder from its sensor",
    "lambda2AuthPct": "the closed-loop limits are per region (Fuel menu)",
    "lambda2CylMask": "closed loop trims every cylinder from its sensor",
    "pinMapSwitch": "no map switching exists",
    # B6 (V98): pins a dialog showed with no reader and no label
    "pinBaro": "the baro is the board's own sensor (ASIC w08)",
    "pinOilPress": "no oil pressure input path exists",
    "pinFuelPress": "no fuel pressure input path exists",
    "pinFlex": "no flex fuel input exists",
    "pinGenericAin": "no generic analog input exists yet",
    "pinGenericPwm": "no generic PWM output exists yet",
    "pinGenericOut": "no generic on/off output exists yet",
    "pinTacho": "no tachometer output path exists yet",
    "testPin": "the bench command itself selects the output",
    "pinVss": "no vehicle speed input is read",
    "trigDecoder": "selects which validation rules apply; the decoder is "
                   "configured by the wheel fields",
    # --- a dead scalar that sat beside the live thing that replaced it
    "revMin": "not read",
    "simRpm": "there is no trigger simulator in the ME7.1.1 build",
    "injChannel": "outputs are routed by cavity (Injection hardware)",
    "ignChannel": "outputs are routed by cavity (Ignition hardware)",
    "dwellMsX100": "running dwell is the Ignition / Dwell curve",
    "injDeadtimeUs": "dead time is the curve in Injection configuration",
    "cltPullupOhm": "the CLT sensor curve maps counts to temperature",
    "iatPullupOhm": "the IAT sensor curve maps counts to temperature",
    "injModeLegacy": "superseded by Injection mode",
    "injectorPreset": "not applied - enter the injector data directly",
    "coilPreset": "not applied",
    "mapSensorPreset": "not applied - enter offset and gradient directly",
    "injRefPressureKpa": "no fuel-pressure compensation",
    "pwmInvert": "the bridge polarity is a board fact (hctarget.h)",
    "cylBank": "no per-bank strategy reads it",
    "testMode": "the bench command itself selects the mode",
    "testTimeoutMs": "bench timing is clamped in code",
    "iatDefault": "an invalid IAT reads -40 C, fixed (V97)",
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
    T("#Choosing below CHANGES NOTHING by itself. Choose, then press APPLY:"),
    T("#the ECU writes the preset's values into the ordinary fields (engine"),
    T("#stopped only), checks the whole page, and refuses the lot if the"),
    T("#result would not validate. It does NOT Burn - review, then Burn."),
    F("enginePreset"),
    C("cmdApplyEnginePreset", "APPLY ENGINE PRESET"),
    T("If the fields do not update within a few seconds, close and reopen"),
    T("the dialog (or reconnect): the ECU asks TunerStudio to re-read."),
    T("Every value stays editable afterwards; nothing runs 'as a preset'."),
    T("!Cylinders, displacement and max engine speed take effect after a"),
    T("!Burn and a key cycle."),
])

# rusEFI engineChars: cylinders, displacement, firing order, FUEL STRATEGY.
panel("hcEngineBasics", "Engine", [
    T("#Geometry the whole fuel and spark model is derived from."),
    F("cylinders"),
    F("strokes"),
    F("displacementCc"),
    B(),
    T("#Fuel strategy (rusEFI fuelAlgorithm). Speed density: VE by rpm x"),
    T("#MAP, air from MAP and intake temperature. Alpha-N: VE by rpm x"),
    T("#throttle; 'x inlet pressure' multiplies by the measured pressure"),
    T("#(a sensor BEFORE the throttle, e.g. the AWT's), 'no pressure"),
    T("#sensor' assumes 101.3 kPa - pure alpha-N, MAP faults cannot touch it."),
    F("loadSource", "Legacy V101 load source", "fuelModel == 0"),
    F("alphaNUseIat", None, "fuelModel == 0 && loadSource == 2"),
    P("hcPanelTableAxes"),
    T("#TunerStudio's VE Table Generator (VE table > Tools) models MAP"),
    T("#(kPa) load only: use it with speed density, not with alpha-N."),
    T("A failed pressure sensor fuels from the pressure estimate table (Fuel"),
    T("menu, rpm x throttle): MANIFOLD pressure under speed density, INLET"),
    T("(boost) pressure under alpha-N x inlet pressure. Gauges show 0 = FAULT."),
    B(),
    T("#Which load the ignition and target lambda tables use."),
    F("ignLoadMode"),
    F("lambdaLoadMode"),
    B(),
    T("#The highest speed the decoder and scheduler are sized for. It is a"),
    T("#noise ceiling, NOT a rev limiter (see Limits and fallbacks)."),
    F("revMax"),
    T("A complete engine setup is loaded from Controller / Base Tunes."),
])

panel("hcEngineFiring", "Firing order", [
    T("#A named order computes each cylinder's TDC (4-stroke, even fire)."),
    T("#VAG 1.8T: 1-3-4-2. CUSTOM: enter the TDC angles below (odd fire)."),
    T("#Wiring is separate: Injection / Ignition hardware assign each"),
    T("#CYLINDER its cavity - never rearrange pins to match the order."),
    F("firingOrder"),
    T("#TDC of each cylinder, degrees after cylinder 1 (CUSTOM only):"),
    E("tdcCylDegX10", "firingOrder == 0"),
])

panel("hcEngineFiringExt", "Cylinders 9..12", [
    T("Only read with firing order CUSTOM and more than 8 cylinders."),
    E("tdcCylExtDegX10", "firingOrder == 0"),
])

# -------------------------------------------------------------- PROTECTION --
# rusEFI limitsAndFallback. V93: the rev limiter is a FUEL CUT in the planner
# (hcsched_dry.c, rusEFI rpmHardLimit + cutFuelOnHardLimit): above revLimit
# every injector event is planned undriven, fuel returns 200 rpm below it.
panel("hcLimitsRev", "Rev limiter", [
    T("#Hard limit: above the rev limit cut FUEL, SPARK or both, back below"),
    T("#limit - hysteresis. Spark cut skips the given sparks of every 8 (8 ="),
    T("#all). 0 = no limiter. Not while cranking."),
    F("revLimit"),
    F("revLimitHyst"),
    F("revlimMode"),
    F("revlimPattern", None, "revlimMode != 1"),
    T("#Soft limit (rusEFI): over the hysteresis band BELOW the limit, timing"),
    T("#retard and fuel added ramp in. 0 = off."),
    F("revLimitSoftRetard"),
    F("revLimitSoftFuel"),
    T("Not physically qualified on the car."),
])

panel("hcLimitsProtect", "Engine protection", [
    T("#Each protection is a FUEL CUT (limpCut shows which), after rusEFI's"),
    T("#limp manager. Coolant above its limit: fuel cut above the coolant rev"),
    T("#limit (0 = 3000 rpm), 200 rpm hysteresis; a faulted sensor is not"),
    T("#judged. A latched throttle fault (DBW on): fuel cut above 1500 rpm"),
    T("#(etbLimpRpm). Injector duty over its limits: cut until below 20 %."),
    T("#Flood clear: no fuel while cranking with the pedal floored. 0 = off."),
    F("cltMaxDegX10"),
    F("cltLimpRpm"),
    F("etbLimpRpm"),
    F("injDutyInstX10"),
    F("injDutySustX10"),
    F("injDutySustMs"),
    F("floodClearX10"),
])

panel("hcLimitsBoost", "Boost cut", [
    T("#At this pressure FUEL is cut and the boost solenoid forced OFF, until"),
    T("#the pressure falls below it by the hysteresis - whether or not boost"),
    T("#control is enabled (a stuck wastegate overboosts with the valve off)."),
    T("#0 = 220 kPa / 15 kPa. It needs a valid MAP reading: a MAP fault gives"),
    T("#valve 0 and no cut."),
    F("boostCutKpa"),
    F("boostCutHyst"),
])


# ----------------------------------------------------------------- TRIGGER --
# rusEFI triggerConfiguration: "Primary Trigger" beside "Cam Inputs", xAxis.
panel("hcTriggerWheel", "Primary trigger", [
    T("#A complete wheel's tooth count and how many are missing: a 60-2 is"),
    T("#60 and 2. The decoder reads these, and trigCfgTeeth / trigCfgGap on"),
    T("#the right show what it actually resolved."),
    F("syTeeth"),
    F("syGap"),
    F("trigEdge"),
    T("#Trigger angle: where tooth #1 - the edge that ENDS the gap - is, in"),
    T("#crank degrees after cylinder-1 TDC. Negative = before TDC, e.g. a"),
    T("#tooth 78 deg BTDC is -78.0. Same meaning as Speeduino's trigger"),
    T("#angle; rusEFI's trigger angle offset is the same number, sign flipped."),
    T("#Every other angle (TDC table, spark, injection, cam, knock) is in"),
    T("#degrees after cylinder-1 TDC and follows this one."),
    T("!Check it: FIXED timing + a timing light, or the tooth profile."),
    T("!AWT preset -78.0; a car page on -2.0 (old 358.0) is 76 deg off: Help."),
    F("trigAngleX10"),
    F("pinCrank"),
])

panel("hcTriggerSync", "Synchronisation", [
    F("syncMode"),
    F("trigSource"),
    F("trigGapRatioX10"),
    F("trigMinTeeth"),
    F("trigTimeoutMs"),
])

panel("hcTriggerCam", "Cam inputs", [
    T("#camRefs is how many edges of the chosen polarity the cam gives in"),
    T("#one 720 degree cycle. ONE (a single-window Hall cam) resolves the"),
    T("#cycle, so sequential fuel and COP become possible. An EVEN count never"),
    T("#can, and the firmware will not claim cycle sync from one."),
    F("camEnable"),
    F("camEdge", None, "camEnable == 1"),
    F("camRefs", None, "camEnable == 1"),
    F("camRefX10", None, "camEnable == 1"),
    F("camWindowX10", None, "camEnable == 1"),
    T("#LEVEL: the Bosch quick-start wheel (1.8T, VR6). The cam LEVEL is read"),
    T("#at one crank angle and must alternate every revolution; its sectors"),
    T("#(both edges captured) show on the right. Engine angle: move it with"),
    T("#the crank offset."),
    F("camPhaseMode", None, "camEnable == 1"),
    F("camPhaseAngleX10", None, "camEnable == 1 && camPhaseMode == 1"),
    F("camPhaseLevel", None, "camEnable == 1 && camPhaseMode == 1"),
    F("camPhaseConfirm", None, "camEnable == 1 && camPhaseMode != 0"),
    T("#PATTERN: each cam's wheel from the library. Teeth are named by"),
    T("#their spacing in crank degrees, then the half and the VVT deviation by"),
    T("#their angle; camWindowX10 is the VVT authority."),
    F("cam1Pattern", None, "camEnable == 1 && camPhaseMode == 2"),
    F("cam2Pattern", None, "camEnable == 1 && camPhaseMode == 2"),
    F("cam2RefX10", None, "camEnable == 1 && camPhaseMode == 2"),
    F("camToothTol", None, "camEnable == 1 && camPhaseMode == 2"),
    F("pinCam1", None, "camEnable == 1"),
    F("pinCam2", None, "camEnable == 1"),
])

rpanel("hcReadTrigger", 2, ["rpmGauge", "crankSyncGauge", "cycleSyncGauge",
                            "crankToothIndexGauge", "syncLossCountGauge",
                            "crankEdgesGauge", "toothCorrectionsGauge",
                            "cycleSyncLostGauge", "camPhaseNoAltGauge",
                            "camLowWidthX10Gauge", "camHighWidthX10Gauge",
                            "trigCfgAngleX10Gauge",
                            "cam1PatClassGauge", "cam2PatClassGauge",
                            "cam1VvtX10Gauge", "cam2VvtX10Gauge"])

# V92: THE TOOTH PROFILE - a crank-angle reference that needs no timing
# light. hcsched_dry.c sums every synchronised tooth period per 6-degree bin;
# the vehicle logger reads the 60 bins and finds the slowest ones.
panel("hcToothProfile", "Tooth profile / compression TDC", [
    T("#COMPRESSION: engine stopped, key on. Press, then crank ~5 s. Spark"),
    T("#and fuel are HELD OFF until the crank stops (or 30 s). The slowest"),
    T("#teeth are the compression TDCs - read them with the vehicle logger."),
    T("#RUNNING: 64 revolutions, outputs untouched."),
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

# -------------------------------------------------------------------- FUEL --
# rusEFI injectorConfig: "Injection" + "Injector Settings" + "Fuel
# characteristics".
panel("hcInjectorHw", "Injector settings", [
    T("#Flow turns the model's fuel mass into an opening time; the dead time"),
    T("#(curve, centre) is added afterwards and never scaled by it."),
    F("injFlowCcMin"),
    B(),
    T("#Fuel characteristics"),
    F("stoichAfrX100"),
])

# V97: rusEFI injectionSettings ("Injection mode", "Injection timing control
# mode", injection phase) with the sequential state beside it.
panel("hcInjectorStrategy", "Injection", [
    T("#Sequential runs two half pulses per cylinder until the cam confirms"),
    T("#the cycle, then one whole pulse - switched per cylinder with the same"),
    T("#fuel per intake. Batch/semi-sequential need only crank sync."),
    F("injStrategy"),
    F("injTimingMode"),
    F("injPhaseMode"),
    F("injStartDegX10", None, "injPhaseMode == 0"),
    T("Angle = degrees BEFORE the cylinder's compression TDC; 360 = its"),
    T("gas-exchange TDC. End of injection ~400..460 = closed-valve."),
    T("Table: Fuel / Injection timing (rpm x fuel load)."),
    P("hcPanelSeq"),
    P("hcReadSeq"),
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
    T("!Cavity 19 is injector 8 and 24 injector 7 - NOT cavity 23, which is the"),
    T("!main relay stage. Cavity 20 is unnamed on the ME7.1.1 sheet."),
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
    T("#rusEFI DFCO: cuts every injector with the pedal (throttle without"),
    T("#DBW) released, above the cut rpm, below the MAP limit, the coolant"),
    T("#warm - after the delay. Fuel returns below the resume rpm or on"),
    T("#pedal. A FAILED pedal/TPS, coolant or (speed density) MAP sensor"),
    T("#never cuts fuel. 0 rpm = off."),
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

# V98: rusEFI fuelClosedLoopCorrection - short-term trim, per region.
panel("hcStft", "Closed loop fuel correction", [
    T("#Short-term trim (rusEFI STFT): measured vs target lambda, integrated"),
    T("#with the region's time constant and limited to its add / remove."),
    T("#Only with the sensor READY, running, warm, after the start delay,"),
    T("#outside the deadband, and held after a fuel cut or an enrichment."),
    T("#Bank 2 trims from lambda 2 when it is fitted. Off = trim 0."),
    F("stftEnable"),
    F("stftStartDelay", None, "stftEnable == 1"),
    F("stftMinClt", None, "stftEnable == 1"),
    F("stftDeadband", None, "stftEnable == 1"),
    F("stftLambdaMin", None, "stftEnable == 1"),
    F("stftLambdaMax", None, "stftEnable == 1"),
    F("stftAfterDfco", None, "stftEnable == 1"),
    F("stftAfterAe", None, "stftEnable == 1"),
    T("#Regions: idle below the rpm, overrun below / power above the load,"),
    T("#cruise otherwise."),
    F("stftIdleRpm", None, "stftEnable == 1"),
    F("stftOverrunLoad", None, "stftEnable == 1"),
    F("stftPowerLoad", None, "stftEnable == 1"),
    E("stftMaxAdd", "stftEnable == 1"),
    E("stftMaxRemove", "stftEnable == 1"),
    E("stftTimeConst", "stftEnable == 1"),
])

rpanel("hcReadStft", 2, ["stftBank1Gauge", "stftBank2Gauge",
                         "lambdaValueGauge", "lambda2ValueGauge",
                         "targetLambdaGauge", "stftStateLoGauge",
                         "stftRegionGauge", "RPMValueGauge"])

ipanel("hcPanelStft", 1, [
    IND("stftStateLo == 8", "{ Closed loop: bitStringValue(hcStftList, stftStateLo)}",
        "CLOSED LOOP CORRECTING", "white, black, green, black"),
])

panel("hcStftRight", "", [
    P("hcPanelStft"),
    P("hcReadStft"),
    LG("hcStftGraph", "Lambda: target vs measured, trim", "South",
       ["targetLambda", "lambdaValue", "stftBank1"]),
])

# ---------------------------------------------------------------- IGNITION --
# rusEFI ignitionSettings: "Spark / Mode / ... Timing Mode / Fixed Timing"
# beside "Ignition Outputs". Fixed timing lives HERE, as in rusEFI.
panel("hcIgnitionBasics", "Ignition", [
    T("#Running dwell is the Ignition / Dwell curve (against battery)."),
    F("ignStrategy"),
    B(),
    T("#USE FIXED TIMING WHILE VALIDATING WITH A TIMING GUN. Fixed holds ONE"),
    T("#angle at every speed and load, ignores cranking and applies no"),
    T("#correction, so the light sees exactly what the ECU commanded. Until it"),
    T("#has been done, the trigger angle and every cell of the map are"),
    T("#hypotheses. Correct the Trigger angle in Setup / Trigger (AWT: -78)."),
    F("timingModeCfg"),
    F("fixedTimingX10", None, "timingModeCfg == 1"),
    T("!Commanded advance is clamped to -30.0 (after TDC) .. 60.0 deg BTDC."),
])

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
panel("hcSensorClt", "CLT sensor", [
    T("#The curve maps RAW ADC COUNTS to temperature. The AWT preset uses this"),
    T("#ECU's own OEM curve for its switched 340 R pull-up (the state the board"),
    T("#is in). An invalid input reads -40 C - on the gauge AND in the fuel"),
    T("#and ignition models - and sets CLT FAULT (P0115)."),
    F("pinClt"),
    P("hcPanelCltValid"),
])

ipanel("hcPanelCltValid", 1, [
    IND("cltError", "CLT OK", "CLT FAULT - reads -40 C",
        "white, black, red, black"),
])

panel("hcSensorIat", "IAT sensor", [
    T("#Same shape as coolant: a raw-count to temperature curve."),
    T("!AWT harness: the IAT signal must be moved to cavity 26."),
    T("#An invalid input reads -40 C (display and models) and sets IAT FAULT."),
    F("pinIat"),
    F("iatChannel"),
])

panel("hcSensorMap", "Pressure sensor (AWT: charge pressure)", [
    T("#A LINEAR transfer function, in the sensor's own terms:"),
    T("#    kPa x10  =  offset  +  counts * gradient / 1000"),
    T("#so a 4 bar sensor reading 0.5 V at 0 kPa and 4.5 V at 400 kPa has"),
    T("#gradient (4000-0)*1000/(921-102) and offset -gradient*102/1000."),
    T("!AWT: the sensor on cavity 101 reads BEFORE the throttle (boost), not"),
    T("!manifold pressure - which is why the AWT base tune runs alpha-N."),
    F("pinMap"),
    F("mapSensOff"),
    F("mapSensGrd"),
])

panel("hcSensorBaro", "Baro sensor", [
    T("#Fuel / Ambient source controls the ambient value used by new fuel policies."),
    T("#The legacy startup display seed is stored below; it does not correct fuel."),
    F("baroDefault", "Legacy startup display seed"),
    B(),
    T("#Ambient pressure on the right is the ECU's OWN altitude sensor, on"),
    T("#the board (its read path is proven on the bench). It is NOT"),
    T("#what the engine model uses, and its transfer function is an estimate"),
    T("#from a sibling calibration: read it as approximate."),
    T("!Near 0 or 1023 raw counts the input is at a rail: not a measurement."),
])

panel("hcSensorBattery", "Battery", [
    T("#Full scale is the battery voltage that reads 1023 counts, i.e. the"),
    T("#divider ratio times the ADC reference."),
    F("adcBattFsDv"),
    F("pinVbat"),
])

panel("hcSensorMisc", "Aux analog inputs", [
    T("#Physical connector cavity."),
    F("pinMaf"),
    T("A MAF is OPTIONAL: an absent or failed one never inhibits"),
    T("speed-density operation."),
])

rpanel("hcReadClt", 1, ["cltDcGauge", "cltCtrlDcGauge", "cltRawAsicGauge"])
rpanel("hcReadIat", 1, ["iatDcGauge"])
rpanel("hcReadMap", 2, ["mapKpaX10Gauge", "engLoadGauge", "rlX10Gauge"])
rpanel("hcReadBaro", 2, ["ambientPressureGauge", "ambientVoltageGauge",
                         "baroRawGauge", "mapKpaX10Gauge"])

rpanel("hcReadBattery", 2, ["battDvGauge", "batteryGauge", "adc05_UBATGauge"])
rpanel("hcReadNvm", 2, ["nvmGenerationGauge", "nvmCommitsGauge",
                        "nvmAttemptsGauge", "ramProbeSeedGauge",
                        "ramProbeResultGauge"])
# The wideband state beside the wideband setup (it was only in Diagnostics).
# V97: both banks the same, left column bank 1, right column bank 2.
rpanel("hcReadLambda", 2, ["lambda1X1000Gauge", "lambda2X1000Gauge",
                           "lambda1StateGauge", "lambda2StateGauge",
                           "lambda1ValidGauge", "lambda2ValidGauge",
                           "heater1StateGauge", "heater2StateGauge",
                           "heater1DutyGauge", "heater2DutyGauge",
                           "lam1RiX10Gauge", "lam2RiX10Gauge",
                           "lam1IpUaGauge", "lam2IpUaGauge",
                           "lam1FaultGauge", "lam2FaultGauge",
                           "cj1DiagGauge", "cj2DiagGauge"])

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
    IND("cj1Ok == 1", "CJ120 #1: NOT VERIFIED", "CJ120 #1: ANSWERING",
        "white, black, green, black"),
    IND("cj2Ok == 1", "CJ120 #2: NOT VERIFIED", "CJ120 #2: ANSWERING",
        "white, black, green, black"),
])
rpanel("hcReadLambdaLink", 2, ["cj1ErrGauge", "cj2ErrGauge",
                               "cj1TmoGauge", "cj2TmoGauge",
                               "asicSampleAgeMsGauge", "tpsSampleAgeMsGauge",
                               "lamAcqFlagsGauge", "lamAckModesGauge"])
panel("hcLambdaRight", "", [
    P("hcPanelLambda"),
    P("hcReadLambda"),
    P("hcReadLambdaLink"),
])

# ------------------------------------------------------------------ LAMBDA --
panel("hcLambdaStrategy", "Wideband O2 (on-board controllers)", [
    T("#Measured lambda feeds the closed loop fuel correction (Fuel menu)"),
    T("#and VE Analyze - only while READY."),
    T("!Heater permission follows the selected policy. Preheat and ramp"),
    T("!lead to closed loop only with qualified sensor-mode measurements"),
    T("!on the sensor's internal resistance against an 82.5 ohm reference. Pump"),
    T("!current only when hot. Heating a FITTED sensor is not yet qualified."),
    T("!Lambda reads 0 = NOT a measurement. 0 OFF 1 INIT 2 HEATING 3 WARMING"),
    T("!4 READY 5 FAULT (lam1Fault: 2 = heater open / no sensor)."),
    T("#Family mapping: bank 1 cavities 70/51/71/52, heater 5. Verify the harness."),
    F("lambda1Source"),
    F("pinLambda1"),
    B(),
    T("#HEATER POLICY: measure actual H+ at the sensor before choosing."),
    T("!ECU battery voltage does not prove the heater feed is present."),
    T("!Disabled never heats. Ignition on requires key and qualified supply."),
    T("!Engine running only also requires a running engine; an allowed run"),
    T("!grants one finite 30 s tail. Key-off or Disabled cancels permission."),
    T("!Sensor type, loaded PWM polarity, current and condensation handling"),
    T("!are PHYSICAL QUALIFICATION PENDING. Readiness has no promised time."),
    F("lambdaHeatPolicy"),
    B(),
    F("lambda2Source"),
    F("pinLambda2"),
])

# --------------------------------------------------------------- THROTTLE --
# rusEFI etbDialog: "Base ETB settings", "ETB Jam detection", PID, and the
# ETB bench test in the SAME dialog. TPS and pedal calibration are Sensors.
panel("hcEtbBase", "Base ETB settings", [
    T("#Enable only after AutoCal ETB has passed and the pedal is"),
    T("#calibrated (Sensors > Pedal position sensor)."),
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
    T("#2000 Hz is this ECU's OEM value. Re-run ETB Characterization after"),
    T("#changing it: the bias curve is only valid at the frequency it was"),
    T("#measured at."),
    T("!No limp-home position and no DBW rev taper exist, so neither has a"),
    T("!control here (their page bytes are reserved; ts_ini_dead_knob_proof)."),
])

panel("hcEtbPid", "PID settings", [
    T("#rusEFI units: %/% , %/%/s, %.s/% - or run the PID autotune below."),
    F("dbwKp"),
    F("dbwKi"),
    F("dbwKd"),
    T("Feed-forward: Advanced / ETB bias curve."),
])

panel("hcEtbSafety", "ETB jam / deviation detection", [
    T("#Deviation for a duration is what makes a stuck plate a fault rather"),
    T("#than a permanent large error the integrator chases."),
    F("dbwDevX10"),
    F("dbwDevMs"),
    T("#A pedal/TPS range or pair error must persist this long before it"),
    T("#latches (the output is held meanwhile). Key-on clears a latch."),
    F("dbwFaultDebounceMs"),
    F("dbwSfMode"),
    T("#Both TPS tracks failed with DBW on: alpha-N fuels at the spring"),
    T("#opening (the motor is off then)."),
    F("dbwLimpX10"),
    T("#rusEFI ETB rev limit: above the start the target tapers to closed."),
    F("dbwRevlimRpm"),
    F("dbwRevlimRange"),
])

panel("hcEtbNudge", "ETB bench test", [
    T("#rusEFI's 'Bench Test ETB'. RPM 0, TPS tracks agreeing, driver fault-free,"),
    T("#or it refuses. Three nudges of at most 50 ms, not a stroke; it aborts"),
    T("#on a bridge fault, on the plate leaving a compiled-in band, or on the"),
    T("#tracks disagreeing. Watch which way the plate moves."),
    C("cmdTestAbort", "ABORT"),
    C("cmdTestDbwA", "Throttle bridge, direction A"),
    C("cmdTestDbwB", "Throttle bridge, direction B"),
    P("hcPanelBenchState"),
    T("#A refused test lights the reason below - every unmet one at once."),
    P("hcPanelBenchRefuse"),
])

panel("hcEtbTpsCal", "TPS calibration", [
    T("#CLOSED goes in MIN and OPEN in MAX, in that order and NOT sorted: on"),
    T("#a Bosch/VAG body the first track FALLS as the plate opens, so a"),
    T("#correct calibration can have min > max. The direction is the data."),
    F("pinTps1"),
    F("tps1Min"),
    F("tps1Max"),
    F("pinTps2"),
    F("tps2Min"),
    F("tps2Max"),
    B(),
    T("#Hold the plate at the stop and press. Both tracks together, to RAM"),
    T("#only - the tune is then modified and unburned; Burn to keep it."),
    C("cmdGrabTpsClosed", "Grab Closed Throttle"),
    C("cmdGrabTpsOpen", "Grab Fully Opened Throttle"),
    B(),
    T("#Each track reads 0 % closed and 100 % open whichever way its voltage"),
    T("#runs, so after both Grabs the pair is SAME even on a VAG body."),
    F("tpsCorrelation"),
    F("tpsTolX10"),
])

panel("hcEtbAppCal", "Pedal position sensor", [
    T("#Released goes in MIN, floored in MAX, same rule as the throttle."),
    T("#Each Grab reads BOTH tracks at once and sets correlation SAME: a VAG"),
    T("#pedal track 2 reading half of track 1 still gives the same 0..100 %."),
    F("pinApp1"),
    F("pedal1Min"),
    F("pedal1Max"),
    F("pinApp2"),
    F("pedal2Min"),
    F("pedal2Max"),
    B(),
    T("#Release the pedal COMPLETELY, then Grab Released."),
    T("#Press the pedal FULLY and hold it, then Grab Full Pedal."),
    T("#Both tracks together, to RAM only - Burn to keep."),
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
panel("hcEtbCommission", "ETB AutoCal / Diagnostics", [
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
rpanel("hcReadEtbLive", 2, ["tpsX10Gauge", "tps2X10Gauge",
                            "pedalX10Gauge", "pedal2X10Gauge",
                            "dbwTargetX10Gauge", "dbwActualX10Gauge",
                            "dbwDutyX10Gauge", "dbwStateGauge"])

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
rpanel("hcReadTps", 2, ["tps1RawGauge", "tps2RawGauge",
                        "tps1VoltageGauge", "tps2VoltageGauge",
                        "tpsX10Gauge", "tps2X10Gauge",
                        "dbwTps1X10Gauge", "dbwTps2X10Gauge"])
rpanel("hcReadApp", 2, ["app1RawGauge", "app2RawGauge",
                        "app1VoltageGauge", "app2VoltageGauge",
                        "pedalX10Gauge", "pedal2X10Gauge",
                        "dbwApp1X10Gauge", "dbwApp2X10Gauge"])

# -------------------------------------------------------------------- IDLE --
panel("hcIdleBase", "Idle settings", [
    T("#Idle through the electronic throttle: a FLOOR under the ETB demand ="),
    T("#the base position by coolant + a PI trim toward the target rpm by"),
    T("#coolant, bounded by the trim authority. The loop runs only with the"),
    T("#pedal released, after the post-start delay, and below target + band;"),
    T("#otherwise the trim is HELD (reset only when the engine stops)."),
    T("#Off: the ETB pedal map at 0 % pedal and the minimum ETB position alone."),
    F("idleEnable"),
    F("idleKp", None, "idleEnable == 1"),
    F("idleKi", None, "idleEnable == 1"),
    F("idleRangeX10", None, "idleEnable == 1"),
    F("idleRpmBand", None, "idleEnable == 1"),
    F("idlePedalX10", None, "idleEnable == 1"),
    F("idleStartMs", None, "idleEnable == 1"),
    T("#Pedal blend (rusEFI etbIdleThrottleRange): the idle opening is"),
    T("#ADDED to the pedal map, which is compressed into what remains, so"),
    T("#the pedal stays progressive. 0 = the larger of the two."),
    F("etbIdleRange", None, "idleEnable == 1"),
    # V97: rusEFI "Extra Idle Features" - the dashpot
    T("#Dashpot: after a pedal release the floor carries the adder for the"),
    T("#hold time, then decays it to 0 (the trim is held meanwhile)."),
    F("idleDashX10", "Dashpot coasting-to-idle Initial idle Adder",
      "idleEnable == 1"),
    F("idleDashHoldMs", "Dashpot coasting-to-idle Hold time",
      "idleEnable == 1 && idleDashX10 > 0"),
    F("idleDashDecayMs", "Dashpot coasting-to-idle Decay time",
      "idleEnable == 1 && idleDashX10 > 0"),
])

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

# V97: rusEFI idleTimingPidCorrDialog, "Closed-loop Ignition idle timing"
panel("hcIdleTiming", "Closed-loop Ignition idle timing", [
    T("#Spark advance is added below the idle target and taken away above"),
    T("#it while the idle throttle loop is CLOSED (not while cranking, not"),
    T("#with the pedal pressed, not coasting). Spark answers within a cycle;"),
    T("#the throttle needs the manifold's time. Gain is degrees per 100 rpm"),
    T("#away from target: rusEFI's starting point is 10 (0.1 deg/rpm)."),
    T("#Proportional only: the throttle trim already integrates the error."),
    F("idleTimingEnable"),
    F("idleTimingKp", None, "idleTimingEnable == 1"),
    F("idleTimingMinX10", None, "idleTimingEnable == 1"),
    F("idleTimingMaxX10", None, "idleTimingEnable == 1"),
    F("idleTimingSoftMs", None, "idleTimingEnable == 1"),
])

rpanel("hcReadIdleTiming", 2, ["rpmGauge", "idleTargetRpmGauge",
                               "idleTimingX10Gauge", "ignCorrX10Gauge"])

# ------------------------------------------------------------------- BOOST --
panel("hcBoostBase", "Boost control options", [
    T("#Open loop (mode 0): the base duty map (rpm x TPS) x the CLT and IAT"),
    T("#multipliers. Closed loop (mode 1): that duty + a PID on the manifold"),
    T("#pressure toward the target table, every 20 ms. Sent through the I/O chip"),
    T("#to cavity 104 at the 10 ms frame quantum. ZERO below the rpm / TPS"),
    T("#floor, at the boost cut (Setup / Limits), on a MAP fault, at key-off."),
    F("boostEnable"),
    F("boostMode", None, "boostEnable == 1"),
    F("boostMinRpm", None, "boostEnable == 1"),
    F("boostMinTpsX10", None, "boostEnable == 1"),
    F("pinBoost", None, "boostEnable == 1"),
])

panel("hcBoostPid", "Boost PID", [
    T("#Closed loop (boostMode 1). Gains per 20 ms step, duty 0.1 % per"),
    T("#0.1 kPa of error. D acts on the pressure, not the error. The I term"),
    T("#waits until the pressure is within the band BELOW target (spooling)"),
    T("#and never integrates into a saturated output."),
    F("boostKp", None, "boostMode == 1"),
    F("boostKi", None, "boostMode == 1"),
    F("boostKd", None, "boostMode == 1"),
    F("boostClMinKpa", None, "boostMode == 1"),
    F("boostIBand", None, "boostMode == 1"),
])

rpanel("hcReadBoost", 2, ["boostTargetX10Gauge", "boostReqX10Gauge",
                          "mapKpaX10Gauge", "boostOpenX10Gauge",
                          "boostPX10Gauge", "boostIX10Gauge",
                          "boostDX10Gauge", "boostMode_Gauge",
                          "boostFuelCutGauge", "boostCutsGauge"])

# ----------------------------------------------------------------- OUTPUTS --
# rusEFI outputsDialog: "Main relay output" and "Fuel Pump", each with its
# own Test button, beside the other outputs. One dialog, not three.
panel("hcOutMainRelay", "Main relay output", [
    T("#The logical MAIN_RELAY. AUTO requests it whenever the ECU runs."),
    T("#Cavity 23 is the ECU's OWN relay stage: it closes with the key in"),
    T("#hardware and run-on (hold time below) is kept through its keep-alive"),
    T("#input, so on 23 only AUTO is valid and no port is written"),
    T("#(mainRelayBound = 2). The AWT base tune uses 23."),
    T("#Any other relay-class cavity is driven by the CPU (bound = 1); 65 is"),
    T("#a LOW-SIDE SINK: wire the coil from switched +12 V to the cavity."),
    F("mainRelayModeCfg"),
    F("pinMainRelay"),
    F("mainRelayGraceMs"),
    F("mainRelayHoldMs"),
    T("The bench test drives a CPU-driven cavity (65) only; on 23 it is"),
    T("refused - the relay already follows the key."),
    C("cmdTestRelay", "Test Main Relay"),
    P("hcPanelRelay"),
])

panel("hcOutFuelPump", "Fuel pump", [
    T("#AUTO: one prime per key cycle (max 5 s), ON while the crank turns,"),
    T("#OFF when the decoder declares a stall. No latching ON exists."),
    T("#Cavity 65 is a LOW-SIDE SINK (measured active-LOW on the bench): relay"),
    T("#coil from switched +12 V to cavity 65. It is open when OFF, unpowered"),
    T("#or in reset, so no inverted mode is offered."),
    F("fuelPumpMode"),
    F("pinFuelPump"),
    F("fuelPumpPrimeMs"),
    C("cmdTestPump", "Test Fuel Pump"),
    P("hcPanelPump"),
])

panel("hcOutMisc", "Cam solenoid outputs", [
    T("#Physical connector cavities, 255 = not assigned."),
    F("pinCam1Sol"),
    F("pinCam2Sol"),
    B(),
    T("#Cam solenoid stages: three 250 Hz bursts at 50 %, engine stopped."),
    C("cmdTestAbort", "ABORT"),
    C("cmdTestVvt1", "Test cam solenoid, cavity 115"),
    C("cmdTestVvt2", "Test cam solenoid, cavity 120"),
    P("hcPanelBenchState"),
])

# ------------------------------------------------------------- MOTORSPORT --
# V98: rusEFI launch_control / shift_torque_reduction / antilag_system /
# rotational idle. Every function OFF by default; each needs its switch
# (cavity 86/87 when no cam uses it) or, without one, its pedal condition.
_MS_NOTE = T("Switch inputs: the OEM switch cavities 38/39/40/55/56/57/75/76 "
             "(wire to +12 V) or the cam inputs 86/87 (to ground, only if no "
             "cam uses them); each dropdown entry names its polarity. Not "
             "physically qualified.")

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
    _MS_NOTE,
    P("hcReadMs"),
    T("#Inputs: the pin level (left) and each function's state after"),
    T("#polarity and a 10 ms debounce."),
    P("hcPanelSwitchRaw"),
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

panel("hcCtrlS5500", "S5500 correlation window", [
    T("#The sixteen-word window into the supervision frame. Editing this"),
    T("#field MOVES the window - an ordinary page write. The engine needs"),
    T("#base 4: the window then IS the ASIC's analog port map (w00 CLT,"),
    T("#w01 IAT, w08 altitude, w12/w13 CJ120 Ri). Developer use only."),
    T("#s5500Idx = 65535 means all sixteen decode as ADDAT channels 0..15."),
    F("s5500WindowBase"),
])

panel("hcNvmTest", "Persistence test byte", [
    T("#THE P3 TEST FIELD. An alignment pad inside the persistent page that"),
    T("#nothing in the runtime reads - so it can be changed, burned and"),
    T("#power-cycled without changing how the engine behaves."),
    T("Procedure: change it, Burn, power-cycle the ECU, read it back."),
    F("idlePad", "Persistence test byte (P3)"),
])

panel("hcCtrlBenchValues", "Bench test parameters", [
    T("#What the bench commands ask for. Every one is CLAMPED IN FIRMWARE"),
    T("#afterwards - a page cannot be edited into a continuous energisation."),
    F("testValue"),
])

# Controller / Unused settings - the dead scalars that sat inside live
# workflows. Each label ends "(not used)"; the gate holds that true.
panel("hcUnusedEngine", "Engine and trigger", [
    F("revMin"),
    F("simRpm"),
    F("trigDecoder"),
    F("oilPressMinKpa"),
    F("oilPressMinRpm"),
    E("cylBank", "cylinders"),
])

panel("hcUnusedFuel", "Fuel and sensors", [
    F("injectorPreset"),
    F("injRefPressureKpa"),
    F("injDeadtimeUs"),
    F("injModeLegacy"),
    F("mapSensorPreset"),
    F("cltPullupOhm"),
    F("iatPullupOhm"),
    F("iatDefault"),
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
    IND("(cfgWarnings & 1024) != 0", "VE load axis fits the load source",
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
    IND("baroPlausible", "AMBIENT INPUT AT A RAIL - not a measurement",
        "Ambient input inside its span", GREEN),
    IND("baroWindowOk", "S5500 WINDOW MOVED - baroRaw is a different word",
        "Ambient raw is frame word 12", GREEN),
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
    IND("benchSafe", "BENCH-SAFE BUILD: NO OUTPUTS", "Output backends present",
        GREEN),
])

ipanel("hcPanelPlatform", 2, [
    IND("asicRunning", "ASIC NOT RUNNING", "ASIC running", GREEN),
    IND("asicError", "ASIC OK", "ASIC ERROR", RED),
    IND("tickRunning", "TICK STOPPED", "Tick running", GREEN),
    IND("rxTickRunning", "RX TICK STOPPED", "RX tick running", GREEN),
    IND("wdtFed", "WATCHDOG NOT FED", "Watchdog fed", GREEN),
    IND("badVecBit", "No spurious vectors", "SPURIOUS INTERRUPT", RED),
    IND("ramBadBit", "RAM OK", "RAM FAULT", RED),
    IND("rxLoss", "Serial OK", "SERIAL LOSS", RED),
    IND("setupFault", "Setup OK", "SETUP FAULT", RED),
    IND("baroWindowOk", "BARO WINDOW MOVED", "Baro window at word 12", YELLOW),
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
dialog("hcSetupEngine", "Base engine", [
    P("hcEngineBasics"),
    P("hcEngineFiring"),
    P("hcEngineFiringExt", None, "cylinders > 8"),
], layout="xAxis", help_topic="hcHelpFiringOrder")

columns("hcSetupLimitsCols",
        ["hcLimitsRev", "hcLimitsProtect"],
        "hcLimitsBoost")

dialog("hcSetupLimits", "Limits and fallbacks", [
    P("hcSetupLimitsCols"),
])

# rusEFI triggerConfiguration: primary | cams, xAxis; the sync state beside it.
columns("hcTriggerWheelCol",
        "hcTriggerWheel",
        ["hcTriggerSync", "hcTriggerCam"])

dialog("hcSetupTrigger", "Trigger", [
    P("hcTriggerWheelCol", "West"),
    P("hcSetupTriggerLive", "East"),
], layout="border", help_topic="hcHelpTrigger")

panel("hcSetupTriggerLive", "", [
    P("hcReadTrigger"),
    P("hcPanelTrigger"),
    P("hcToothProfile"),
])

dialog("hcSensorBatteryDlg", "Battery", [
    P("hcSensorBattery", "West"),
    P("hcReadBattery", "East"),
], layout="border")

# V97: rusEFI malfunctionDialog "Check Engine Settings": output, test button
panel("hcOutCel", "Check Engine Settings", [
    T("#Cavity 47: a low-side stage - lamp from switched +12 V"),
    T("#to the cavity. At key-on: ON for the test time, OFF for the gap, then"),
    T("#the trouble codes' MIL request (a stored fault reads ON-OFF-ON)."),
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
dialog("hcSetupOutputs", "Outputs", [
    P("hcOutMainRelay"),
    P("hcOutFuelPump"),
    P("hcOutCel"),
    P("hcOutMisc"),
], layout="xAxis", help_topic="hcHelpRouting")

# ------------------------------------------------------------------ FUEL ---
# rusEFI groupMenu "Injector Setup": Injection configuration | Injection
# hardware. The dead time curve sits in the configuration it belongs to.
panel("hcInjCfgLeft", "", [
    P("hcInjectorStrategy"),
    P("hcInjectorHw"),
])

dialog("hcFuelInjector", "Injection configuration", [
    P("hcInjCfgLeft", "West"),
    P("deadtimeCurve", "Center"),
    P("hcReadFuel", "East"),
], layout="border", help_topic="hcHelpInjMode")

dialog("hcFuelInjHw", "Injection hardware", [
    P("hcInjectorPins"),
    P("hcTestInjectors"),
], layout="xAxis", help_topic="hcHelpRouting")

dialog("hcFuelCorrections", "Acceleration enrichment", [
    P("hcFuelEnrich", "West"),
    P("hcReadFuel", "East"),
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

panel("hcTransLeft", "", [
    P("hcTransSettings"),
    P("hcReadTrans"),
    LG("hcTransGraph", "Tip-in: throttle, film share, fuel", "South",
       ["tpsX10", "transCorrUs", "injCycleUs"]),
])

panel("hcTransCurves", "", [
    P("wwXCurve", None, "transEnable == 1"),
    P("wwTauCurve", None, "transEnable == 1"),
])

dialog("hcFuelTransient", "Transient fuel (wall film, after-start)", [
    P("hcTransLeft", "West"),
    P("hcTransCurves", "East"),
], layout="border", help_topic="hcHelpTransient")

dialog("hcFuelDfco", "Deceleration fuel cutoff (DFCO)", [
    P("hcFuelOverrun", "West"),
    P("hcReadFuel", "East"),
], layout="border")

# -------------------------------------------------------------- CRANKING ---
# rusEFI crankingDialog: cranking rpm, fuel, ignition (fixed cranking advance,
# cranking dwell) - and here the cranking fuel curve, embedded.
panel("hcCranking", "Cranking settings", [
    T("#What the engine gets while the starter turns it: the numbers that"),
    T("#make an engine CATCH are not the numbers that make it RUN."),
    F("crankRpmMax"),
    B(),
    T("#Ignition"),
    F("ignAdvanceDegX10"),
    # 0 is a SENTINEL (hcengine.c eng_service, rusEFI's semantics): the dwell
    # curve decides while cranking too. Proven on the car, 2026-09-26: with
    # 0 the cranking dwell was KFSZT(battery): 4.4..5.75 ms at 9.9..9.3 V
    # turning, 7.68 ms at 8.2 V in the starter inrush.
    F("crankingDwellMsX100", label="Cranking dwell (0 = battery curve)"),
    T("0 = the Ignition / Dwell curve (dwell vs battery) decides - NOT zero"),
    T("dwell. Any other value replaces the curve while cranking."),
    B(),
    T("#Fuel: MASS per cylinder per cycle against coolant (curve), through"),
    T("#the injector model like running fuel (rusEFI cranking base fuel)."),
    T("#A failed coolant sensor uses the 20 C point."),
    B(),
    T("#Priming: one pulse on every injector at key-on, engine stopped,"),
    T("#after the delay (rusEFI). Mass against coolant (curve); 0 = none."),
    T("#Repeated key-ons without a start prime less (flooding guard)."),
    F("primeDelay"),
])

panel("hcCrankingCurves", "", [
    P("crankPwCurve"),
    P("primeCurve"),
])

dialog("hcCrankingDlg", "Cranking settings", [
    P("hcCranking", "West"),
    P("hcCrankingCurves", "Center"),
    P("hcReadFuel", "East"),
], layout="border")

dialog("hcStftDlg", "Closed loop fuel correction", [
    P("hcStft", "West"),
    P("hcStftRight", "East"),
], layout="border", help_topic="hcHelpLambda")

# -------------------------------------------------------------- IGNITION ---
dialog("hcIgnitionHw", "Ignition hardware", [
    P("hcIgnitionBasics"),
    P("hcIgnitionPins"),
    P("hcTestCoils"),
    P("hcReadSpark"),
], layout="xAxis", help_topic="hcHelpIgnition")

# --------------------------------------------------------------- SENSORS ---
dialog("hcSensorCltDlg", "CLT sensor", [
    P("hcSensorClt", "West"),
    P("cltSensCurve", "Center"),
    P("hcReadClt", "East"),
], layout="border", help_topic="hcHelpThermistor")

dialog("hcSensorIatDlg", "IAT sensor", [
    P("hcSensorIat", "West"),
    P("iatSensCurve", "Center"),
    P("hcReadIat", "East"),
], layout="border", help_topic="hcHelpThermistor")

dialog("hcSensorMapDlg", "Pressure input (AWT: charge)", [
    P("hcSensorMap", "West"),
    P("hcReadMap", "East"),
], layout="border", help_topic="hcHelpPressure")

dialog("hcSensorBaroDlg", "Baro sensor", [
    P("hcSensorBaroLeft", "West"),
    P("hcReadBaro", "East"),
], layout="border", help_topic="hcHelpBaro")

panel("hcSensorBaroLeft", "", [
    P("hcSensorBaro"),
    P("hcPanelBaro"),
])

dialog("hcSensorMiscDlg", "Aux analog inputs", [
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
    T("#Read-only. Pins, endpoints and AutoCal are in"),
    T("#Advanced > Electronic Throttle Body."),
    P("hcPanelTpsDiag"),
    P("hcReadTps"),
])

dialog("hcEtbTpsCalDlg", "TPS (diagnostics)", [
    P("hcEtbTpsDiag"),
], help_topic="hcHelpTpsCal")

panel("hcEtbCharacterizeControls", "ETB / Diagnostics", [
    T("!ENGINE OFF ONLY. Keep clear of the throttle; no pedal is needed."),
    T("2-90% holds and ramps, driver-demand slams/ramps through the pedal map,"),
    T("then break-away edges at 5-80%: the friction band and its midpoint."),
    T("Characterization leaves calibration/PID unchanged. Every exit leaves bridge OFF."),
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
    T("Voltage compensation: NOT JUDGED FROM SINGLE RUN."),
    T("Save a data log for per-segment metrics and comparison at other voltages."),
    T("Save changes RAM only. Review the proposal and Burn explicitly. PID, TPS and VBAT remain unchanged."),
    T("After Save, rerun immediately; compare holding integral, error, saturation and motion traces."),
    P("hcEtbBiasCompare"),
    P("hcEtbFrictionBand"),
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
    "{ Save updates ONLY the supported range - see Supported from / Supported to}",
    "{ Positions rejected by a confidence gate: bitStringValue(hcSweepBiasList, sweepBiasExcludedWhy)}",
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
dialog("hcEtbCharacterizeDlg", "ETB / Diagnostics / Characterization", [
    P("hcEtbCharacterizeControls", "West"), P("hcEtbCharacterizeResults", "East"),
    P("hcEtbCharacterizeMotion", "South"), P("hcEtbCharacterizeTerms", "Center"),
], layout="border")

dialog("hcEtbCommissionDlg", "ETB AutoCal / Diagnostics", [
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

# V97: the ONE throttle workflow - base settings, TPS calibration and the
# motor-direction bench test West; AutoCal ETB, status, live TPS/pedal and
# PID East. Pedal calibration stays under Sensors (a different sensor).
columns("hcEtbLeft",
        ["hcEtbBase", "hcEtbSafety"],
        ["hcEtbTpsCal", "hcPanelGrab", "hcPanelThrottleState"])

# V98r2: four columns of at most 28 rows and the graph below - one column
# was 42 rows and TunerStudio clipped it.
columns("hcEtbRight",
        ["hcEtbAutotune", "hcEtbPid"],
        ["hcReadEtbLive", "hcEtbNudge"])

panel("hcEtbGraph", "", [
    LG("hcEtbLiveGraph", "Throttle: target vs actual", "South",
       ["dbwTargetX10", "dbwActualX10", "dbwDutyX10", "pedalX10"]),
])

dialog("hcBoostDlg", "Boost control options", [
    P("hcBoostBase"),
    P("hcBoostPid", None, "boostEnable == 1"),
    P("hcReadBoost"),
], layout="xAxis")

columns("hcMotorsportCols", ["hcMsLaunch", "hcMsFlat"],
        ["hcMsAls"], ["hcMsPit", "hcMotorsport"])

dialog("hcMotorsportDlg", "Launch, flat shift, anti-lag", [
    P("hcMotorsportCols"),
])

# ------------------------------------------------------------------ KNOCK --
# rusEFI softwareKnock: "Sense" (with the cylinder -> sensor mapping) and
# "Response" West, the threshold curve Center; HaniCore adds the CC195's
# own knobs (band, gain per sensor, window curves) and the live chain East.
panel("hcKnockSense", "Sense", [
    T("!Monitor measures, detects and logs per cylinder without touching the"),
    T("!spark - calibrate there first. Active retards the knocking cylinder."),
    F("knockMode"),
    F("knockBand", None, "knockMode > 0"),
    E("knockGain", "knockMode > 0"),
    P("knockWinStartCurve", None, "knockMode > 0"),
    P("knockWinLenCurve", None, "knockMode > 0"),
])
panel("hcKnockMap", "Select the nearest sensor for each cylinder", [
    E("knockSensor", "knockMode > 0"),
])
panel("hcKnockResponse", "Response", [
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
rpanel("hcReadKnock", 2, ["knockLastCylGauge", "knockLastIkrGauge",
                          "knockRetardX10Gauge", "knockCountGauge",
                          "knockWinStartX10Gauge", "knockWinLenX10Gauge",
                          "knockWindowsGauge", "knockSamplesGauge",
                          "knockLateGauge", "knockStaleGauge",
                          "knockWinUsGauge", "knockAdcFailGauge"])
rpanel("hcReadKnockCyl", 4,
       ["knockLevel%dGauge" % (i + 1) for i in range(4)]
       + ["knockRet%dGauge" % (i + 1) for i in range(4)]
       + ["knockRef%dGauge" % (i + 1) for i in range(4)]
       + ["knockCnt%dGauge" % (i + 1) for i in range(4)]
       + ["knockLevel%dGauge" % (i + 5) for i in range(4)]
       + ["knockRet%dGauge" % (i + 5) for i in range(4)]
       + ["knockRef%dGauge" % (i + 5) for i in range(4)]
       + ["knockCnt%dGauge" % (i + 5) for i in range(4)])
panel("hcKnockLeft", "", [
    P("hcKnockSense"),
    P("hcKnockMap"),
    P("hcKnockResponse"),
    P("hcKnockReference"),
])
panel("hcKnockRight", "", [
    P("hcPanelKnock"),
    P("hcReadKnock"),
    T("#Per cylinder: level (KI / reference), retard, reference, knocks"),
    P("hcReadKnockCyl"),
])
dialog("hcKnockDlg", "Knock Control", [
    P("hcKnockLeft", "West"),
    P("knockKefCurve", "Center"),
    P("hcKnockRight", "East"),
], layout="border", help_topic="hcHelpKnock")

# -------------------------------------------------------------------- VVT --
# rusEFI Advanced: "VVT outputs and PID" (vvtPidDialog: Configuration West,
# the PIDs Center) and "VVT intake / exhaust target" (table + status).
panel("hcVvtConfig", "Configuration", [
    T("!Closed loop needs camPhaseMode PATTERN on that cam input: it closes"),
    T("!on the pattern core's measured tooth-0 position. On/off: the target"),
    T("!table's sign switches the solenoid. Faults drop the duty to 0."),
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
    P("hcReadVvt"),
])
dialog("hcVvtDlg", "VVT Configuration & PID", [
    P("hcVvtConfig", "West"),
    P("hcVvtPid", "Center"),
    P("hcVvtRight", "East"),
], layout="border", help_topic="hcHelpVvt")

# ------------------------------------------------------------------ IDLE ---
dialog("hcIdleDlg", "Idle settings",
       [P("hcIdleBase"), P("hcReadIdle"), P("hcIdleState")], layout="xAxis")
dialog("hcIdleTimingDlg", "Closed-loop Ignition idle timing",
       [P("hcIdleTiming"), P("hcReadIdleTiming")], layout="xAxis")

# ------------------------------------------------------------ CONTROLLER ---
# rusEFI engineTypeDialog, "Base Tunes" - under Controller, as there.
dialog("hcBaseTunes", "Base Tunes", [
    P("hcEnginePreset"),
    P("hcPanelPreset"),
])

dialog("hcCtrlDlg", "Controller and identity", [P("hcCtrlIdent")])
dialog("hcCtrlS5500Dlg", "S5500 correlation window", [
    P("hcCtrlS5500"),
])

panel("hcUnusedInfo", "", [
    T("#Page fields no linked module reads, taken out of the live dialogs so"),
    T("#those show only what the engine uses. Editing one changes nothing."),
    T("#They keep their page bytes, so layout and signature do not move."),
    T("#tests/tunerstudio/me711_page_reader_audit.py checks this list against the image."),
    T("Implemented features that are not yet physically qualified keep"),
    T("their own menus and say so there."),
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
    F("pinOilPress"),
    F("pinFuelPress"),
    F("pinFlex"),
    F("pinBaro"),
    F("pinVss"),
    F("pinMapSwitch"),
    E("pinGenericAin"),
])
panel("hcUnusedPwm", "PWM outputs", [
    F("pinTacho"),
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
    T("#Two different things can stop fuel: a CUT decided by the engine"),
    T("#model, and an INHIBIT that stops every output at once."),
    P("hcPanelFuelCut"),
    P("hcPanelInhibits"),
    P("hcReadFuel"),
])

# V89 UI (rusEFI pass): this dialog said BENCH_SAFE was set and no coil could
# fire. HANICORE_BENCH_SAFE has been commented out of hctarget.h since V63 and
# V85 measured spark permitted under crank sync - the text was the opposite of
# the truth, on the dialog a person opens when deciding whether a coil is live.
columns("hcWhyNoSparkCols",
        [T("#Coils ARE driven by the engine runtime - there is no user arm."),
         T("#Spark needs crank position (crank sync), a valid page and the"),
         T("#supervision link; each inhibit below stops it on its own."),
         T("#Then the map, dwell and timing mode decide what is commanded."),
         B(),
         T("!Coil outputs are NOT physically qualified yet: the first spark on"),
         T("!a new installation is a first-actuation test (Controller / Bench"),
         T("!test, one coil at a time, engine stopped)."),
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
_DTC_ROWS = []
for _i in range(1, 5):
    _pid = "hcDtcRow%d" % _i
    ipanel(_pid, 1, [
        IND("(dtcS%dSt & 1) == 1" % _i,
            "{ bitStringValue(hcDtcRowList, dtcS%dRow)}" % _i,
            "{ bitStringValue(hcDtcRowList, dtcS%dRow)}" % _i,
            "yellow, black, red, white")])
    _DTC_ROWS.append((_pid, "dtcStored%d != 0" % _i))

ipanel("hcDtcNone", 1, [
    IND("dtcStoredN == 0", "-", "No trouble codes", GREEN)])
ipanel("hcDtcMore", 1, [
    IND("dtcStoredN > 4", "-",
        "More codes stored than shown - clear, then read again",
        "white, black, yellow, black")])
ipanel("hcDtcLamp", 1, [
    IND("dtcMil", "CEL OFF", "CEL ON", RED)])
ipanel("hcDtcFfCode", 1, [
    IND("dtcFfCode != 0", "No freeze frame",
        "{ bitStringValue(hcDtcList, dtcFfIdx)}",
        "white, black, white, black")])

panel("hcDtcList", "Trouble codes", [
    T("#Status  |  Code - Description"),
    PV("hcDtcNone", "dtcStoredN == 0")]
    + [PV(p, v) for p, v in _DTC_ROWS]
    + [PV("hcDtcMore", "dtcStoredN > 4")])
rpanel("hcReadDtcFf", 4, ["dtcFfRpmGauge", "dtcFfCltGauge",
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
    T("#The chain, in the order the firmware computes it: fuel load (MAP,"),
    T("#or throttle under alpha-N) + charge temperature -> air density ->"),
    T("#VE -> air mass -> target lambda -> fuel mass -> corrections (warm-"),
    T("#up, closed loop, wall film) -> opening time + dead time."),
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
    T("#1  Controller / Base Tunes: choose the engine, APPLY (engine stopped),"),
    T("#   review, Burn, then cycle the key."),
    T("#2  Advanced / Electronic Throttle Body: AutoCal ETB. Sensors / Pedal"),
    T("#   position sensor: Grab both ends, check the two"),
    T("#   tracks agree while moving, Burn."),
    T("#3  Sensors: CLT, IAT, MAP, Baro, Battery read plausibly"),
    T("#   (Diagnostics / Why? / Which sensor failed?)."),
    T("#4  Setup / Trigger: crank - crank sync must come and stay"),
    T("#   (Diagnostics / Why? / Why is there no sync?)."),
    T("#5  Controller / Bench test, engine stopped, ONE channel at a time:"),
    T("#   fuel pump, each injector, each coil, the throttle nudge."),
    T("#6  Advanced / Electronic Throttle Body: enable only after 2 and 5."),
    T("#7  Ignition / Ignition hardware: FIXED timing, check with a timing"),
    T("#   light, correct the Trigger angle in Setup / Trigger, back to DYNAMIC."),
    B(),
    T("#BURN: works with the engine stopped or cranking. Above about 500 rpm"),
    T("#it is refused (Diagnostics / Calibration storage says why) and the"),
    T("#edits stay live in RAM - stop the engine and Burn again."),
    B(),
    T("!NOT IN THIS FIRMWARE: oil-pressure protection (no oil input),"),
    T("!long-term fuel trim, MAF fuelling. Fields no module reads live in"),
    T("!Controller / Unused settings. Rev limiter, idle control, closed-loop"),
    T("!lambda and boost, launch / flat shift / anti-lag are implemented but"),
    T("!NOT physically qualified - qualify each before relying on it."),
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
SEP = ("SEP", None)
NOT_USED = " (not used)"

panel("hcLoadPolicyPanel", "Fuel model and density", [
    T("#Legacy preserves V101 CAL_LOAD_SOURCE, including its fault estimate."),
    T("#Pure Alpha-N: TPS x RPM; reference density; optional qualified ambient and IAT."),
    T("#Manifold SD: manifold MAP x RPM; measured manifold density once."),
    T("#Charge Alpha-N: TPS x RPM; continuous upstream density or BARO-relative blend."),
    T("#AWT cavity 101 is CHARGE PRESSURE before the throttle. It is not manifold MAP."),
    T("#Changing the model does not convert VE axes or retune table cells."),
    F("fuelModel"),F("pressureRole"),F("densityPolicy",None,"fuelModel != 0"),
    F("densityReference"),F("ambientCorrection",None,"fuelModel == 1"),F("fuelUseIat",None,"fuelModel != 0"),
    F("chargeBlendStart",None,"fuelModel == 3 && densityPolicy == 2"),
    F("chargeBlendFull",None,"fuelModel == 3 && densityPolicy == 2"),
    T("#Gauge = max(charge-BARO,0). w = clamp((gauge-start)/(full-start),0..1)."),
    T("#P effective = BARO + gauge x w. rho=P effective/(R x T); air=rho x volume x VE."),
    T("#Fuel=air/(stoich x lambda). The displayed ratio is diagnostic: no second multiplier."),
])
panel("hcLoadAmbientPanel", "Ambient provenance", [
    F("ambientSource"),F("ambientMaxAge"),F("pressureMaxAge"),
    T("#Fixed fallback uses densityReference; it is not a measured ambient pressure."),
    T("#Stopped capture needs a valid physical pressure role, 1 s fully stopped,"),
    T("#and 50..120 kPa. Its lease expires; running charge pressure is never captured."),
    T("#A dedicated barometric sensor transfer is not implemented yet."),
    T("#It falls back explicitly. No guessed barometric transfer can change fueling."),
])
panel("hcLoadProtectionPanel", "Fuel protection", [
    T("#New pressure-dependent models cut fuel on lost authoritative pressure under load."),
    F("pressureGuardEnable"),F("pressureGuardRpm"),F("pressureGuardTps"),
    T("#Legacy guard is optional. Boost valve authority is inhibited on pressure loss in all modes."),
    F("leanGuardEnable"),F("lambdaPhysicalQualified"),F("leanGuardRpm"),F("leanGuardTps"),
    F("leanGuardCharge"),F("leanGuardDeviation"),F("leanGuardPersist"),F("leanGuardRecovery"),
    T("#Lean guard is disabled by default. Enable only after physical lambda commissioning."),
    T("#Cold, stale, faulted or unqualified lambda cannot trigger or release the guard."),
    T("#Recovery requires unloaded valid lambda at or richer than target for the recovery time."),
    T("#Never commission by deliberately making the engine lean; inject simulated signals."),
])
dialog("hcLoadPolicies", "Fuel model, pressure role and density",[P("hcLoadPolicyPanel")])
dialog("hcLoadAmbient", "Ambient source and freshness",[P("hcLoadAmbientPanel")])
dialog("hcLoadProtection", "Pressure loss and lean protection",[P("hcLoadProtectionPanel")])

MENU = [
    ("&Setup", [
        ("hcSetupEngine", "Base engine"),
        ("hcSetupLimits", "Limits and fallbacks"),
        ("hcSetupTrigger", "Trigger"),
        SEP,
        ("hcSensorBatteryDlg", "Battery"),
        SEP,
        ("hcSetupOutputs", "Outputs"),
    ]),

    ("&Fuel", [
        ("hcLoadPolicies", "Fuel model, pressure role and density"),
        ("hcLoadAmbient", "Ambient source and freshness"),
        ("hcLoadProtection", "Pressure loss and lean protection"),
        ("veTableTblEdit", "VE"),
        ("veTableTbl3D", "VE 3D view"),
        ("GROUP", "Injector Setup", [
            ("hcFuelInjector", "Injection configuration"),
            ("hcFuelInjHw", "Injection hardware"),
        ]),
        SEP,
        ("afrMapTblEdit", "Target lambda"),
        ("afrMapTbl3D", "Target lambda 3D view"),
        ("hcStftDlg", "Closed loop fuel correction"),
        ("cltEnrCurve", "Warmup enrichment"),
        ("hcFuelDfco", "Deceleration fuel cutoff (DFCO)"),
        ("injPhaseTblEdit", "Injection timing"),
        ("injPhaseTbl3D", "Injection timing 3D view"),
        ("mapEstimateTblEdit", "Pressure estimate (sensor fault)"),
        ("mapEstimateTbl3D", "Pressure estimate 3D view"),
        SEP,
        # rusEFI: groupMenu "TPS Acceleration Enrichment / Wall Wetting AE"
        ("GROUP", "Acceleration Enrichment / Wall Wetting AE", [
            ("hcFuelTransient", "Wall wetting AE (transient fuel)"),
            ("hcFuelCorrections", "TPS acceleration enrichment"),
        ]),
    ]),

    ("&Ignition", [
        ("ignMapTblEdit", "Ignition timing"),
        ("ignMapTbl3D", "Ignition timing 3D view"),
        ("ignCltCorrCurve", "CLT timing correction"),
        ("ignIatCorrCurve", "IAT timing correction"),
        ("dwellBattCurve", "Dwell"),
        SEP,
        ("hcIgnitionHw", "Ignition hardware"),
        SEP,
        ("hcKnockDlg", "Knock Control"),
    ]),

    ("&Cranking", [
        ("hcCrankingDlg", "Cranking settings"),
        ("asCurve", "After-start enrichment"),
    ]),

    ("&Idle", [
        ("hcIdleDlg", "Idle settings"),
        ("idleTargetCurve", "Idle target RPM from CLT"),
        ("idleBaseCurve", "Idle position from CLT"),
        SEP,
        ("hcIdleTimingDlg", "Closed-loop Ignition idle timing"),
    ]),

    ("&Advanced", [
        ("hcMotorsportDlg", "Launch / flat shift / anti-lag / pit limiter"),
        SEP,
        ("hcVvtDlg", "VVT outputs and PID"),
        ("vvtTarget1TblEdit", "VVT cam 1 (intake) target"),
        ("vvtTarget1Tbl3D", "VVT cam 1 target 3D"),
        ("vvtTarget2TblEdit", "VVT cam 2 (exhaust) target"),
        ("vvtTarget2Tbl3D", "VVT cam 2 target 3D"),
        SEP,
        ("GROUP", "Boost Control", [
            ("hcBoostDlg", "Boost control options"),
            ("boostDutyTblEdit", "Boost control open loop base duty"),
            ("boostDutyTbl3D", "Boost control open loop base duty 3D"),
            ("boostTgtTblEdit", "Boost control target"),
            ("boostTgtTbl3D", "Boost control target 3D"),
            ("boostCltCurve", "CLT boost duty multiplier"),
            ("boostIatCurve", "IAT boost duty multiplier"),
        ]),
        SEP,
        ("hcEtbMain", "Electronic Throttle Body"),
        ("dbwBiasCurve", "ETB bias curve (feed forward)"),
        ("pedalMapTblEdit", "ETB pedal target"),
        ("pedalMapTbl3D", "ETB pedal target 3D view"),
        ("hcEtbCommissionDlg", "ETB AutoCal / Diagnostics"),
        ("hcEtbCharacterizeDlg", "ETB / Diagnostics / Characterization"),
    ]),

    ("&Sensors", [
        ("hcSensorCltDlg", "CLT sensor"),
        ("hcSensorIatDlg", "IAT sensor"),
        SEP,
        ("hcEtbTpsCalDlg", "TPS (diagnostics)"),
        ("hcEtbAppCalDlg", "Pedal position sensor"),
        SEP,
        ("hcSensorMapDlg", "Pressure input (AWT: charge)"),
        ("hcSensorBaroDlg", "Baro sensor"),
        SEP,
        ("hcSensorLambdaDlg", "Wideband O2 sensors"),
        SEP,
        ("hcSensorMiscDlg", "Aux analog inputs"),
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
    "v102Pad": "alignment only",
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
        | {p[0] for p in READ_PANELS} | {c[0] for c in UI.CURVES}
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


def _emit_items(out, items, by_ts, indent="      "):
    for it in items:
        kind = it[0]
        if kind == "t":
            out.append('%sfield = "%s"' % (indent, it[1].replace('"', "'")))
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

    for pid, title, items in PANELS:
        head = '   dialog = %s, "%s"' % (pid, title)
        if PANEL_LAYOUT.get(pid):
            head += ", " + PANEL_LAYOUT[pid]
        out.append(head)
        _emit_items(out, items, by_ts)
        out.append("")

    for did, title, items, layout, help_topic in WORKFLOWS:
        head = '   dialog = %s, "%s"' % (did, title)
        if layout:
            head += ", " + layout
        out.append(head)
        if help_topic:
            out.append('      topicHelp = "%s"' % help_topic)
        _emit_items(out, items, by_ts)
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
FRONT_GAUGES = [
    "RPMValueGauge",       # rusEFI RPMGauge
    "coolantGauge",        # rusEFI CLTGauge
    "TPSValueGauge",       # rusEFI TPSGauge
    "MAPValueGauge",       # rusEFI MAPGauge
    "afrX10Gauge",         # rusEFI afr1Gauge - the TARGET, until a sensor is real
    "VBattGauge",          # rusEFI VBattGauge
    "coilDwellGauge",      # rusEFI dwellGauge
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
FRONT_INDICATORS = [
    ("setupFault", "CONFIG OK", "CONFIG ERROR", RED),
    ("nvmNotBurned", "TUNE SAVED", "BURN PENDING", YELLOW),
    ("crankSync", "NO CRANK SYNC", "CRANK SYNC", GREEN),
    ("cycleSync", "NO PHASE SYNC", "PHASE SYNC", GREEN),
    # THE POLARITY IS THE EXPRESSION'S, NOT THE WISH'S. TunerStudio shows the
    # SECOND caption when the expression is TRUE. rusEFI writes the cut
    # indicators as `{ fuelCutReason != 0 }, "Injection OK", "Fuel cut"` for
    # exactly this reason, and writing `== 0` with the captions in that order
    # lights "FUEL CUT" on a healthy engine.
    ("fuelCut != 0", "FUEL OK", "FUEL CUT", YELLOW),
    ("dbwFaults != 0", "DBW OK", "DBW FAULT", YELLOW),
    # V97: the MIL request (rusEFI's check-engine line). The DTC framework
    # owns it - a stored code alone does not light it (docs/ARCHITECTURE.md).
    ("dtcMil", "CEL", "CEL", RED),
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
    ("mapError", "MAP OK", "MAP FAULT", RED),
    ("vbatError", "BATT OK", "BATT FAULT", RED),
    ("tps1Error", "TPS1 OK", "TPS1 FAULT", RED),
    ("tps2Error", "TPS2 OK", "TPS2 FAULT", RED),
    ("tpsPairError", "TPS OK", "TPS MISMATCH", RED),
    ("app1Error", "PEDAL1 OK", "PEDAL1 FAULT", RED),
    ("app2Error", "PEDAL2 OK", "PEDAL2 FAULT", RED),
    ("appPairError", "PEDAL OK", "PEDAL MISMATCH", RED),
    ("hcbState == 1", "BENCH IDLE", "BENCH TEST", YELLOW),
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
