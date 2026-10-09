#!/usr/bin/env python3
r"""
ts_gauges_me711.py - what a TUNER sees of the output channels: gauge titles,
ranges, the gauge picker's categories and the default datalog. Imported by
tools/tunerstudio/gen_ts_ini_me711.py (the generator owns offsets and scales; this file
owns presentation only, and invents no channel).

WHY (docs/TUNERSTUDIO.md, bug B8): until V98 646 of 718
gauges were titled with the raw channel name over 0..65535 and sat in ONE
category, so TunerStudio's right-click gauge picker was a 646-entry list.
rusEFI groups its 344 gauges in 32 categories with plain titles.

THE FAST BLOCK (OCH 1136..1199, hcengctl711.c hc_ec_publish) carries the
tuning core contiguously so a datalog is ONE read on the K-line. Its channels
have the plain names; the older channels with the same quantity at their
historical offsets stay for the vehicle logger and the diagnostics dialogs and
are filed under "Developer / Raw block" in the picker (FAST_TWINS).
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------
# Plain titles and ranges for the channels a tuner uses.
#   name: (title, units, lo, hi, loDanger, loWarn, hiWarn, hiDanger, digits)
# --------------------------------------------------------------------------
GAUGE_META = {
    "asicSampleAgeMs": ("ASIC frame age (65535 = unavailable)", "ms", 0, 65535, 0, 0, 50, 51, 0),
    "tpsSampleAgeMs": ("Oldest throttle sample (65535 = unavailable)", "ms", 0, 65535, 0, 0, 100, 101, 0),
    "lamAcqFlags": ("Lambda acquisition flags (last step)", "bits", 0, 255, 0, 0, 255, 255, 0),
    "lamAckModes": ("CJ acknowledged modes (B2:B1)", "code", 0, 65535, 0, 0, 65535, 65535, 0),
    # ---- the fast block
    "RPMValue": ("RPM", "rpm", 0, 8000, 0, 0, 6500, 7000, 0),
    "MAPValue": ("Pressure input (AWT: charge pressure)", "kPa", 0, 260, 0, 0, 200, 230, 1),
    "TPSValue": ("Throttle position", "%", 0, 100, 0, 0, 100, 100, 1),
    "pedalPosition": ("Pedal position", "%", 0, 100, 0, 0, 100, 100, 1),
    "coolant": ("Coolant temp", "C", -40, 140, -40, -15, 100, 110, 1),
    "intake": ("Intake air temp", "C", -40, 140, -40, -15, 60, 80, 1),
    "VBatt": ("Battery", "V", 8, 18, 8, 11, 15, 16, 1),
    "fuelLoad": ("Fuel load (VE table axis)", "", 0, 260, 0, 0, 260, 260, 1),
    "lambdaValue": ("Lambda (measured, bank 1)", "", 0.6, 1.4, 0.6, 0.7, 1.15, 1.25, 3),
    "targetLambda": ("Target lambda", "", 0.6, 1.4, 0.6, 0.7, 1.15, 1.25, 3),
    "stftBank1": ("Fuel trim (STFT) bank 1", "%", -25, 25, -25, -15, 15, 25, 1),
    "injectorPulseWidth": ("Injector pulse width", "ms", 0, 25, 0, 0, 18, 22, 2),
    "veValue": ("VE", "%", 0, 130, 0, 0, 130, 130, 1),
    "ignitionTiming": ("Ignition timing", "deg", -30, 60, -30, -20, 45, 55, 1),
    "coilDwell": ("Coil dwell", "ms", 0, 10, 0, 0, 6, 8, 2),
    "warmupEnrich": ("Warm-up enrichment", "%", 90, 200, 90, 90, 170, 190, 0),
    "aeFuelUs": ("Acceleration enrichment", "us", 0, 5000, 0, 0, 4000, 5000, 0),
    "knockRetardMax": ("Knock retard (max cylinder)", "deg", 0, 15, 0, 0, 5, 10, 1),
    "etbTarget": ("ETB target", "%", 0, 100, 0, 0, 100, 100, 1),
    "etbActual": ("ETB position", "%", 0, 100, 0, 0, 100, 100, 1),
    "idleTarget": ("Idle target RPM", "rpm", 0, 2000, 0, 0, 2000, 2000, 0),
    "boostTarget": ("Boost target", "kPa", 0, 260, 0, 0, 200, 230, 1),
    "boostDuty": ("Boost solenoid duty", "%", 0, 100, 0, 0, 90, 95, 1),
    "fuelCutFlags": ("Fuel cut reasons", "", 0, 255, 0, 0, 255, 255, 0),
    "sensorFlags": ("Sensor fault bits", "", 0, 1023, 0, 0, 1023, 1023, 0),
    "syncSeq": ("Sync / sequential word", "", 0, 1023, 0, 0, 1023, 1023, 0),
    "airMass": ("Cylinder air mass", "mg", 0, 1500, 0, 0, 1500, 1500, 1),
    "lambda2Value": ("Lambda (measured, bank 2)", "", 0.6, 1.4, 0.6, 0.7, 1.15, 1.25, 3),
    "mapControl": ("Pressure the fuel uses", "kPa", 0, 260, 0, 0, 200, 230, 1),
    "ignCorrection": ("Ignition correction (CLT/IAT/idle)", "deg", -20, 20, -20, -10, 10, 20, 1),
    "injectorDuty": ("Injector duty", "%", 0, 100, 0, 0, 80, 90, 1),
    # ---- engine-control state
    "stftState": ("Closed loop state", "", 0, 4095, 0, 0, 4095, 4095, 0),
    "stftBank2": ("Fuel trim (STFT) bank 2", "%", -25, 25, -25, -15, 15, 25, 1),
    "motorsportState": ("Motorsport state", "", 0, 65535, 0, 0, 65535, 65535, 0),
    "revLimitNow": ("Rev limit in force", "rpm", 0, 9000, 0, 0, 9000, 9000, 0),
    "ignTableTiming": ("Ignition table timing", "deg", -30, 60, -30, -20, 45, 55, 1),
    "targetAfr": ("Target AFR", "AFR", 10, 20, 10, 11, 15.5, 16.5, 1),
    "primeState": ("Priming state", "", 0, 65535, 0, 0, 65535, 65535, 0),
    "injPhase": ("Injection timing", "deg", 0, 720, 0, 0, 720, 720, 0),
    "fuelCorrection": ("Fuel multiplier (trim, launch, soft limit)", "%", 50, 200, 50, 70, 130, 150, 1),
    "ignLoad": ("Ignition table load", "", 0, 260, 0, 0, 260, 260, 1),
    "lambdaLoad": ("Target lambda table load", "", 0, 260, 0, 0, 260, 260, 1),
    "toothLogStatus": ("Tooth logger status", "", 0, 65535, 0, 0, 65535, 65535, 0),
    # ---- older channels a tuner still reads by name
    "syncState": ("Sync state", "", 0, 4, 0, 0, 4, 4, 0),
    "crankSync": ("Crank sync", "", 0, 1, 0, 0, 1, 1, 0),
    "cycleSync": ("Phase (cam) sync", "", 0, 1, 0, 0, 1, 1, 0),
    "seqActive": ("Sequential active", "", 0, 1, 0, 0, 1, 1, 0),
    "dbwFaults": ("ETB fault bits", "", 0, 511, 0, 0, 511, 511, 0),
    # V99: the stop test's decision (AutoCal NOT A STOP A/B)
    "etbHold1": ("Capture: TPS 1", "cnt", 0, 1023, 0, 0, 1023, 1023, 0),
    "etbPush1": ("TPS1 age at calibration failure", "ms", 0, 65535, 0, 0, 100, 65535, 0),
    "etbStopMoved": ("TPS qualification nibbles", "", 0, 68, 0, 0, 1, 68, 0),
    "etbStopLimit": ("TPS2 age at calibration failure", "ms", 0, 65535, 0, 0, 100, 65535, 0),
    "etbStopDisp": ("Capture: distance from rest", "cnt", 0, 1023, 0, 0, 1023, 1023, 0),
    "etbHoldMs": ("Capture: drive duration", "ms", 0, 2500, 0, 0, 2500, 2500, 0),
    "lamSpan2": ("Lambda 2 signal span (5 s)", "cnt", 0, 255, 0, 0, 255, 255, 0),
    "sparkSkips": ("Sparks skipped by a cut", "", 0, 65535, 0, 0, 65535, 65535, 0),
    "dtcMil": ("CEL requested", "", 0, 1, 0, 0, 1, 1, 0),
}

# Old offset -> the fast-block channel with the same quantity.
FAST_TWINS = {
    "rpm": "RPMValue", "mapKpaX10": "MAPValue", "tpsX10": "TPSValue",
    "cltDc": "coolant", "iatDc": "intake", "battDv": "VBatt",
    "veLoadX10": "fuelLoad", "lambda1X1000": "lambdaValue",
    "lambdaTarget": "targetLambda", "injTiUs": "injectorPulseWidth",
    "advX10": "ignitionTiming", "dwellX100": "coilDwell",
    "warmupPct": "warmupEnrich", "dbwTargetX10": "etbTarget",
    "dbwActualX10": "etbActual", "boostTargetX10": "boostTarget",
    "boostReqX10": "boostDuty", "fuelCut": "fuelCutFlags",
    "sensorErr": "sensorFlags", "airMgX10": "airMass",
    "lambda2X1000": "lambda2Value", "ignCorrX10": "ignCorrection",
    "injDutyX10": "injectorDuty", "idleTargetRpm": "idleTarget",
    "knockRetardX10": "knockRetardMax",
}

# --------------------------------------------------------------------------
# The picker's categories, in menu order. Ordered rules; the FIRST match wins.
# Developer categories come last in the picker but FIRST in the rules, so a
# forensic counter can never land among the tuner's gauges.
# (category, regex on the channel name)
# --------------------------------------------------------------------------
CATEGORY_ORDER = [
    "Engine", "Fuel", "Ignition", "Lambda / closed loop", "Trigger / sync",
    "Sensors", "Throttle / pedal (ETB)", "Idle", "Boost", "Knock", "VVT",
    "Motorsport", "Protection / DTC", "Outputs / relays",
    "Calibration / Burn", "Communications",
    "Developer / Raw block", "Developer / Scheduler", "Developer / Bench",
    "Developer / ASIC", "Developer / Forensics", "Developer / Other",
]

CATEGORY_RULES = [
    ("Developer / Forensics",
     r"^(bf|rst|lf)[A-Z]|^live[A-Z]|^ramProbe|^nvmFail|^nvmPoll|^nvmProg|"
     r"^nvmRetries|^nvmCommit(Last|Fail)?Stage|^bootStage$|^tickMs$|"
     r"^loopCount$|^frames$|^calTicks$|^ramBad$|^probeBad$|^badVec$|"
     r"^firstVec$|^lastVec$|^s0rTrap$|^stackPeak$|^releaseId$|^targetId$|"
     r"^halAinMask$|^halOutCalls$|^outDriveCalls$|^stalls$|^powerNl$|"
     r"^lkgSteps$|^status$"),
    ("Developer / ASIC",
     r"^asic|^s5500|^adc\d\d_|^cj(\d)?(Err|Tmo|Ok|Diag|120Xfers|120Reg1|"
     r"120Ident|120Diag)|^cjErr$|^cjTmo$|^asicImg|^asicOutMask|Raw(Asic)?$|"
     r"UrRaw$|^heater\dSenseRaw$|^lamMode$|^lamVeff$|^lam\dUaZero$|"
     r"^lam\dUrCal$|^o2Pre"),
    ("Developer / Bench",
     r"^hcb|^grab|^outputPins$|^crankIsr|^crankNoise|PinLevel$|PinOn$|"
     r"^ignOnMask$|^injOnMask$|^etb(Cal|Tune|Drive|Proc|Phase|Vfy)|"
     r"^etbDriv|^etbFail|^etbEndpoints|^etbOperator|^tps\dRaw$|"
     r"^tps\dVoltage$|^app\dRaw$|^app\dVoltage$"),
    ("Developer / Scheduler",
     r"^sched|^nextIgnSlot$|^nextInjSlot$|^scheduled|^triggerCaptureArmed$|"
     r"^outputAuthority$|^safetyInhibits$|^dwellTime$|^sparkAdvance$|"
     r"^injPulse$|^seq(InjMask|Skips|Enters|Leaves)$|^injNoFree$|"
     r"^crankPeriod$|^lastToothPeriod$|^crankGap|^crankPhase$|"
     r"^enginePositionDeg$|^stallState$|^trigCfg|^trigCam|^toothLog|"
     r"^cam\dTooth$|^cam\dWindow$|^cam\dRaw$|^camWindow|^camPhase|^camPat|"
     r"^camLow|^camHigh|^cam\dObserved"),
    ("Communications", r"^rx|^link|^kwp"),
    ("Calibration / Burn", r"^nvm|^cfg|^preset|^cfgSource$"),
    ("VVT", r"^vvt"),
    ("Motorsport", r"^motorsport|^launch|^flat|^als|^rotIdle|^pit"),
    ("Knock", r"^knock"),
    ("Boost", r"^boost"),
    ("Idle", r"^idle"),
    ("Throttle / pedal (ETB)", r"^dbw|^etb|^tps|^app\d|^pedal"),
    ("Lambda / closed loop",
     r"^lam|^lambda|^heater|^stft|^targetLambda$|^targetAfr$|^afr"),
    ("Trigger / sync",
     r"^crank|^cam|^cycleSync|^trig|^sync|^noSync$|^toothCorrections$|"
     r"^RPMValue$|^rpm$"),
    ("Ignition", r"^ign|^adv|^dwell|^coilDwell$|^knockRetardMax$"),
    ("Fuel",
     r"^inj|^fuel|^warmup|^trans|^wall|^afterStart|^seq|^air|^ve|^engLoad|"
     r"^rlX10$|^ae|^prime|^mapControl$|^lambdaLoad$"),
    ("Protection / DTC", r"^dtc|^limp|^cel|^sensor|^revLimit"),
    ("Outputs / relays",
     r"^mainRelay|^fuelPump|^runOn|^keyOff$|^kl15Status$|^relayFeedV$"),
    ("Sensors",
     r"^clt|^iat|^map|^MAP|^batt|^battery$|^VBatt$|^ambient|^baro|^coolant$|"
     r"^intake$|^TPSValue$|^pedalPosition$"),
    ("Engine", r"^engineFlags$|^flag"),
]


def category(name: str) -> str:
    if name in FAST_TWINS:
        return "Developer / Raw block"
    for cat, rx in CATEGORY_RULES:
        if re.search(rx, name):
            return cat
    return "Developer / Other"


_SUFFIX = re.compile(r"(X10|X100|X1000|Dc|Us|Ms|Pm|Kpa)$")


def humanize(name: str) -> str:
    """Readable title for a channel without an explicit one: camelCase
    split, the fixed-point suffix dropped ("crankToothIndex" -> "Crank tooth
    index"). Used only where GAUGE_META has no entry - mostly developer
    channels."""
    base = _SUFFIX.sub("", name) or name
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", base).replace("_", " ")
    words = words.strip()
    return words[:1].upper() + words[1:].lower() if words else name


# --------------------------------------------------------------------------
# The DEFAULT DATALOG: the tuning core first (all in the fast block, so a log
# is one contiguous read), then the few state words a log analysis needs.
# Developer / forensic channels are NOT logged by default (the vehicle logger
# tools/vehicle/me711_vehicle_capture.py reads those itself).
#   (channel, column title, format)  - format "int" or "%.Nf"
# --------------------------------------------------------------------------
DATALOG = [
    ("RPMValue", "RPM", "int"),
    ("MAPValue", "MAP", "%.1f"),
    ("mapControl", "MAP used by fuel", "%.1f"),
    ("TPSValue", "TPS", "%.1f"),
    ("pedalPosition", "Pedal", "%.1f"),
    ("coolant", "CLT", "%.1f"),
    ("intake", "IAT", "%.1f"),
    ("VBatt", "Battery", "%.1f"),
    ("fuelLoad", "Fuel load", "%.1f"),
    ("veValue", "VE", "%.1f"),
    ("airMass", "Air mass", "%.1f"),
    ("lambdaValue", "Lambda", "%.3f"),
    ("lambda2Value", "Lambda 2", "%.3f"),
    ("targetLambda", "Target lambda", "%.3f"),
    ("stftBank1", "STFT", "%.1f"),
    ("fuelCorrection", "Fuel mult", "%.1f"),
    ("injectorPulseWidth", "PW", "%.2f"),
    ("injectorDuty", "Inj duty", "%.1f"),
    ("warmupEnrich", "WUE", "int"),
    ("aeFuelUs", "AE", "int"),
    ("ignitionTiming", "Timing", "%.1f"),
    ("ignTableTiming", "Timing (table)", "%.1f"),
    ("ignCorrection", "Timing corr", "%.1f"),
    ("knockRetardMax", "Knock retard", "%.1f"),
    ("coilDwell", "Dwell", "%.2f"),
    ("etbTarget", "ETB target", "%.1f"),
    ("etbActual", "ETB actual", "%.1f"),
    ("idleTarget", "Idle target", "int"),
    ("boostTarget", "Boost target", "%.1f"),
    ("boostDuty", "Boost duty", "%.1f"),
    ("engineFlags", "Engine flags", "int"),
    ("fuelCutFlags", "Fuel cut", "int"),
    ("sensorFlags", "Sensor faults", "int"),
    ("syncSeq", "Sync/seq", "int"),
    ("stftState", "CL state", "int"),
    ("motorsportState", "Motorsport", "int"),
    ("revLimitNow", "Rev limit", "int"),
    ("injPhase", "Inj timing", "%.1f"),
    ("dtcMil", "CEL", "int"),
    ("dbwFaults", "ETB faults", "int"),
]

# Characterization channels retain their firmware names in saved logs.
DATALOG += [(name, name, "%.3f") for name in (
    "dbwTargetX10", "dbwActualX10", "dbwInteg", "dbwTermP", "dbwTermD", "dbwTermFf",
    "dbwBattFactor", "sweepSignedDuty", "sweepFindings", "sweepRms", "sweepSaturation",
    "sweepRequested", "sweepSegment", "sweepBoundRms", "sweepBoundSat",
    "sweepVbatMin", "sweepVbatMax", "sweepSlamSettle", "sweepSlamOver", "sweepSlamSteady",
    "sweepPairWorst", "etbCalStatus", "etbProc", "etbPush1", "etbStopLimit", "etbStopMoved",
    "tpsSampleAgeMs", "dbwTps1X10", "dbwTps2X10", "dbwState", "battDv",
)]

DATALOG += [(n,n,"%.3f") for n in ("sweepTarget","sweepActual","sweepMotor","sweepP","sweepI","sweepD","sweepFf")]
