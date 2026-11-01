#!/usr/bin/env python3
r"""
ts_field_help_me711.py - the [SettingContextHelp] section: one help text per
page field, shown by the tuning app's "?" button beside every setting.

    py tools\tuning\ts_field_help_me711.py [--show]     print the texts

Imported by tools/tuning/gen_ts_ini_me711.py, which emits the section right
after [Constants] (the order rusEFI's generated files use; LibreTune attaches a
help line only to a constant it has already read).

WHERE A TEXT COMES FROM, in this order:

  1. HELP below - written for the tuner, for the fields where the model's note
     is missing or speaks to a developer;
  2. the model's Meta.note (tools/config_source/hanicore_config_def.py),
     cleaned: release tags, source/reference names, register and chip names
     are removed, field names become the labels a tuner sees, and a sentence
     that still carries a forbidden term (tools/research/terminology_audit.py
     TERMS, the same list the terminology gate uses) is dropped;
  3. otherwise the field's label, its choices (dropdowns) or its pin role.

Every text then gets the generated facts: units and range (in the units the
tuning app shows), when a change takes effect (live / when the engine stops /
after a restart), a safety line for safety-critical fields, and "not used" for
the fields the image does not read (gen_ts_ux_me711.UNUSED).

INI RULES: the text is one quoted line - no '"' (it would end the string) and
no line break; ';' is legal inside the quotes but avoided anyway.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import hanicore_config_def as MODEL  # noqa: E402
import gen_ts_ui_me711 as UI         # noqa: E402
import gen_ts_ux_me711 as UX         # noqa: E402
from terminology_audit import TERMS  # noqa: E402

R_, Z_, L_ = (MODEL.ApplyPolicy.RESTART_REQUIRED,
              MODEL.ApplyPolicy.RPM_ZERO_APPLY,
              MODEL.ApplyPolicy.LIVE_APPLY)

APPLY_TEXT = {
    L_: "Takes effect at once, also with the engine running.",
    Z_: "Takes effect when the engine stops (0 rpm); while it runs the old "
        "value stays in use.",
    R_: "Takes effect after Burn and an ECU restart (ignition off and on).",
}
SAFETY_TEXT = "Safety-relevant: a wrong value can stop or damage the engine."
UNUSED_TEXT = "Not used by this firmware: changing it has no effect."
RETIRED_TEXT = ("No longer used - kept only so saved tunes stay compatible. "
                "Changing it has no effect.")

# --------------------------------------------------------------------------
# 1. Tuner-language texts. Plain words, the quantity and its direction; no
#    chip, register, source-file or reference-project names.
# --------------------------------------------------------------------------
HELP: dict[str, str] = {
    # ---- engine and trigger
    "cylinders": "Number of cylinders. Sets how many injector and coil "
                 "outputs are scheduled and how the firing order is spread "
                 "over the cycle.",
    "strokes": "Engine cycle. Four-stroke for every car engine.",
    "displacementCc": "Total engine displacement. The fuel model uses it to "
                      "turn air mass into fuel per cylinder.",
    "syTeeth": "Number of teeth the crank wheel WOULD have with no gap "
               "(a 60-2 wheel: 60).",
    "syGap": "Number of missing teeth in the crank wheel gap (a 60-2 wheel: "
             "2). 0 for a wheel without a gap.",
    "trigEdge": "Which edge of the crank sensor signal is a tooth. If rpm "
                "reads but sync is lost or the timing moves with rpm, try "
                "the other edge.",
    "trigGapRatioX10": "How much longer the gap must be than a normal tooth "
                       "spacing to be recognised as the gap (a 60-2 wheel: "
                       "about 2 to 3). Missing-tooth wheels only.",
    "trigTimeoutMs": "With no crank tooth for this long the engine counts as "
                     "stopped: sync is dropped and the outputs stop.",
    "trigSource": "Arms the crank and cam inputs. Off keeps the engine "
                  "position inputs ignored (for bench work with no sensor "
                  "connected - a floating input can read as a huge rpm).",
    "camEnable": "Read the camshaft sensor. Needed for sequential injection "
                 "and coil-on-plug spark; not needed for wasted spark and "
                 "batch or semi-sequential fuel.",
    "camEdge": "Which edge of the cam sensor signal counts.",
    "revMax": "Highest speed the scheduler is set up for. Keep it above the "
              "rev limit; it does not limit the engine itself.",
    "revMin": "Lowest speed treated as a running engine.",
    "revLimit": "Hard rev limit: above it the cut selected under Rev limit "
                "cuts is applied, back on below the limit minus the "
                "hysteresis.",
    "crankRpmMax": "Below this speed the engine counts as cranking: cranking "
                   "fuel, cranking timing and cranking dwell are used.",
    "syncMode": "How much engine position the ECU establishes: crank only "
                "(360 degrees, enough for wasted spark and batch fuel) or "
                "crank plus cam (full 720 degree cycle, needed for "
                "sequential fuel and coil-on-plug).",
    "pinCrank": "Connector pin of the crank position sensor.",
    "pinCam1": "Connector pin of camshaft sensor 1.",
    "pinCam2": "Connector pin of camshaft sensor 2.",
    "tdcCylDegX10": "Each cylinder's top dead centre in engine degrees after "
                    "cylinder 1's. Used only with firing order Custom "
                    "(odd-fire engines); a named firing order computes them.",
    "trigAngleX10": "Where the first tooth after the gap is, in crank "
                    "degrees after cylinder 1 top dead centre (negative = "
                    "before, the usual case). Check it with a timing light "
                    "in Fixed timing mode: if the light shows less advance "
                    "than commanded, make this value more negative.",
    "camPhaseConfirm": "Number of consecutive, consistent cam checks before "
                       "the engine cycle counts as known.",
    "camPhaseLevel": "The level of the cam input at the check angle when the "
                     "engine really is at that angle (low or high). The "
                     "opposite level means the other crank revolution.",
    # ---- fuel
    "veTable": "Volumetric efficiency (VE) in %: how well the cylinder "
               "fills at this rpm and load. The fuel is computed from the "
               "air this gives, the target lambda and the injector flow - "
               "more VE = more fuel.",
    "fuelRpmAx": "The rpm breakpoints of the VE table.",
    "fuelLoadAx": "The load breakpoints of the VE table: manifold pressure "
                  "(kPa) in speed density, throttle % in the alpha-N modes.",
    "injFlowCcMin": "Injector flow at the test pressure, cc/min (from the "
                    "injector data sheet or a flow test).",
    "injRefPressureKpa": "The fuel pressure at which the injector flow above "
                         "was measured.",
    "injStrategy": "How the injectors fire: batch (all together), "
                   "semi-sequential (in pairs) or sequential (one per "
                   "cylinder, needs the cam sensor).",
    "injPin": "Connector pin of this cylinder's injector.",
    "injStartDegX10": "The injection angle used when the injection timing "
                      "mode is a single angle (degrees before top dead "
                      "centre).",
    "cltEnrAx": "Coolant temperature breakpoints of the warm-up curves.",
    "cltEnrVal": "Extra fuel while the engine is cold, % on top of the "
                 "normal fuel. 0 when warm.",
    "crankPwAx": "Coolant temperature breakpoints of the cranking and "
                 "priming fuel curves.",
    "crankPwVal": "Fuel mass per cylinder per cycle while cranking, by "
                  "coolant temperature. A failed coolant sensor uses the "
                  "20 C point.",
    "accelThreshX10": "Acceleration enrichment starts when the throttle "
                      "opens faster than this.",
    "accelGain": "Extra injector time per unit of throttle speed above the "
                 "threshold.",
    "accelDecayMs": "How long the acceleration extra fuel takes to fade "
                    "away.",
    "overrunRpm": "Fuel cut on overrun is allowed above this speed.",
    "overrunTpsX10": "Fuel cut on overrun only while the pedal is below "
                     "this.",
    "overrunResume": "Fuel returns when the speed falls below this.",
    "afrMap": "Target lambda by rpm and load (1.00 = stoichiometric, below "
              "1 = rich). The fuel is computed to reach it; closed-loop "
              "trim corrects towards it when enabled.",
    "lambdaRpmAx": "The rpm breakpoints of the target lambda table.",
    "stoichAfrX100": "The fuel's stoichiometric air-fuel ratio (gasoline "
                     "14.7, E85 about 9.8). Used only to show AFR; all "
                     "targets are lambda.",
    "dfcoRamp": "After fuel returns from a cut, the retard is taken out "
                "over this time.",
    "injPhaseRpmAx": "The rpm breakpoints of the injection timing table.",
    "injPhaseLoadAx": "The load breakpoints of the injection timing table.",
    "deadtimeVal": "Injector dead time (opening delay) by battery voltage, "
                   "microseconds. From the injector data sheet. On the same "
                   "voltage axis as the dwell curve.",
    "fuelModel": "Which fuel calculation is used.",
    "pressureRole": "Where the pressure sensor measures: in the manifold "
                    "after the throttle, or in the intake before it.",
    "densityPolicy": "Which pressure the air density in the fuel "
                     "calculation is taken from.",
    "fuelUseIat": "On: the air density uses the measured intake air "
                  "temperature. Off: 20 C.",
    # ---- ignition
    "ignMap": "Ignition advance in degrees before top dead centre by rpm "
              "and load. More advance = more torque up to knock; retard if "
              "the engine knocks.",
    "ignRpmAx": "The rpm breakpoints of the ignition table.",
    "ignLoadAx": "The load breakpoints of the ignition table: kPa or %, "
                 "per the ignition load setting.",
    "ignAdvanceDegX10": "Ignition advance while cranking, degrees before top "
                        "dead centre.",
    "ignPin": "Connector pin of this cylinder's coil.",
    "dwellBattAx": "Battery voltage breakpoints of the dwell curve.",
    "dwellBattVal": "Coil charge time (dwell) by battery voltage. Too short "
                    "= weak spark, too long = hot coils and driver.",
    "crankingDwellMsX100": "Dwell while cranking. 0 = use the battery "
                           "curve.",
    "dwellRpmAx": "rpm breakpoints of the dwell-by-rpm curve.",
    "ignIatAx": "Intake air temperature breakpoints of the timing "
                "correction.",
    "ignCltCorr": "Advance added at this coolant temperature (+ = more "
                  "advance, - = retard). 0 everywhere = off.",
    "ignBoostAx": "Boost (pressure above ambient) breakpoints of the boost "
                  "timing correction.",
    "ignBoostCorr": "Advance added at this boost: usually a retard (-) as "
                    "boost rises. 0 everywhere = off. Zero while the "
                    "pressure sensor has failed.",
    "ignStrategy": "How the coils fire. Wasted spark needs only the crank "
                   "position; sequential (one coil per cylinder per cycle) "
                   "needs the cam sensor.",
    "timingModeCfg": "Dynamic uses the ignition table. Fixed holds the "
                     "angle below at every speed and load - only for "
                     "checking the trigger angle with a timing light.",
    "fixedTimingX10": "The angle held in Fixed timing mode, degrees before "
                      "top dead centre.",
    "firingOrder": "The engine's firing order. Custom uses the per-cylinder "
                   "TDC angles (odd-fire engines). The order must have as "
                   "many cylinders as the cylinder count.",
    # ---- sensors
    "cltSensAx": "The sensor readings (ADC counts) of the coolant sensor "
                 "curve. Easiest set with Tools > Common sensors.",
    "cltSensVal": "Coolant temperature at each reading. Easiest set with "
                  "Tools > Common sensors.",
    "iatSensAx": "The sensor readings (ADC counts) of the intake air sensor "
                 "curve. Easiest set with Tools > Common sensors.",
    "iatSensVal": "Intake air temperature at each reading. Easiest set "
                  "with Tools > Common sensors.",
    "mapSensOff": "Pressure the sensor reports at 0 V (from its data "
                  "sheet; Tools > Common sensors fills it).",
    "mapSensGrd": "Pressure change per 1000 ADC counts (from its data "
                  "sheet; Tools > Common sensors fills it).",
    "baroDefault": "Ambient pressure used when the onboard sensor fails.",
    "adcBattFsDv": "Battery voltage at full ADC scale (input divider "
                   "calibration).",
    "pinMap": "Connector pin of the manifold pressure sensor.",
    "pinClt": "Connector pin of the coolant temperature sensor.",
    "pinIat": "Connector pin of the intake air temperature sensor.",
    "pinVbat": "Connector pin the battery voltage is measured on.",
    "pinOilPress": "Connector pin of the oil pressure sensor.",
    "pinFuelPress": "Connector pin of the fuel pressure sensor.",
    "pinMaf": "Connector pin of the air mass sensor.",
    "pinLambda1": "Connector pin of the lambda 1 input.",
    "pinLambda2": "Connector pin of the lambda 2 input.",
    "lambda1Source": "Where lambda 1 comes from: the onboard wideband, a "
                     "narrowband sensor, or none.",
    "lambda2Source": "Where lambda 2 comes from: the onboard wideband, a "
                     "narrowband sensor, or none.",
    "oilSensLoMv": "Sensor voltage at 0 kPa oil pressure.",
    "oilSensHiMv": "Sensor voltage at full-scale oil pressure.",
    "oilSensHiKpa": "Oil pressure at the full-scale voltage.",
    "mapEstRpmAx": "rpm breakpoints of the pressure estimate table.",
    "mapEstTpsAx": "Throttle breakpoints of the pressure estimate table.",
    "mapEstimate": "The pressure the fuel calculation uses instead of the "
                   "sensor while the pressure sensor has failed, by rpm and "
                   "throttle. The displayed pressure stays 0 kPa. 0 = no "
                   "fuel.",
    # ---- throttle (electronic throttle body)
    "dbwEnable": "Turns the electronic throttle control on. The throttle "
                 "motor never moves until this is on. Calibrate the TPS and "
                 "run AutoCal first.",
    "dbwKp": "Proportional gain of the throttle position loop. AutoCal / "
             "PID Autotune fill it.",
    "dbwKi": "Integral gain of the throttle position loop. AutoCal / PID "
             "Autotune fill it.",
    "dbwKd": "Derivative gain of the throttle position loop. AutoCal / PID "
             "Autotune fill it.",
    "dbwMinX10": "Lowest motor command the controller may output "
                 "(negative = drive the plate shut).",
    "dbwMaxX10": "Highest motor command the controller may output.",
    "dbwMaxDutyX10": "Throttle output authority: the highest motor duty the "
                     "controller may ever use. 0 = the throttle motor is "
                     "never driven (AutoCal refuses with OUTPUT AUTHORITY "
                     "0 %). Start low and raise it once the plate follows.",
    "dbwMotorDir": "Which motor direction opens the plate. Wrong = the "
                   "controller drives away from its target and the throttle "
                   "shuts down with a fault. AutoCal measures it.",
    "dbwSfMode": "How the throttle driver's fault signal is read.",
    "dbwAutocalMs": "AutoCal: how long the plate is held at each end stop "
                    "while the position is measured.",
    "dbwAutocalDuty": "AutoCal: motor duty used to push the plate against "
                      "each end stop.",
    "dbwTuneAmp": "PID Autotune: how hard the motor is driven back and "
                  "forth while the throttle response is measured. Raise it "
                  "if autotune reports no oscillation.",
    "dbwBiasAx": "Throttle positions of the feed-forward bias curve.",
    "dbwBiasVal": "Motor duty that holds the plate at this position against "
                  "its spring (negative = pull it shut below the limp-home "
                  "position). AutoCal measures it.",
    "dbwRevlimRange": "Above the throttle rev limit the target closes over "
                      "this rpm range.",
    "pedalMap": "Throttle opening wanted for each pedal position and rpm. "
                "Keep the pedal-released row at 0 so idle control owns the "
                "throttle there.",
    "pedalRpmAx": "rpm breakpoints of the pedal map.",
    "pedalAx": "Pedal breakpoints of the pedal map.",
    "tps1Min": "Throttle track 1 reading with the plate closed. Calibrate "
               "TPS / AutoCal measure it.",
    "tps1Max": "Throttle track 1 reading with the plate fully open. "
               "Calibrate TPS / AutoCal measure it.",
    "tps2Min": "Throttle track 2 reading with the plate closed.",
    "tps2Max": "Throttle track 2 reading with the plate fully open.",
    "pedal1Min": "Pedal track 1 reading with the pedal released (Grab it).",
    "pedal1Max": "Pedal track 1 reading with the pedal floored (Grab it).",
    "pedal2Min": "Pedal track 2 reading with the pedal released (Grab it).",
    "pedal2Max": "Pedal track 2 reading with the pedal floored (Grab it).",
    "tpsCorrelation": "How the two throttle tracks relate after "
                      "calibration. The Grab buttons set it.",
    "appCorrelation": "How the two pedal tracks relate after calibration. "
                      "The Grab buttons set it.",
    "tpsTolX10": "How far the two throttle tracks may disagree before it is "
                 "a fault.",
    "appTolX10": "How far the two pedal tracks may disagree before it is a "
                 "fault.",
    "pinTps1": "Connector pin of throttle position track 1.",
    "pinTps2": "Connector pin of throttle position track 2.",
    "pinApp1": "Connector pin of pedal position track 1.",
    "pinApp2": "Connector pin of pedal position track 2.",
    "dbwMotorPolarity": "Which motor direction opens the plate.",
    "dbwPwmHz": "How fast the throttle motor output is switched. 2000 Hz is "
                "the stock value for this ECU and the right start for an "
                "unknown throttle body.",
    "dbwFaultDebounceMs": "How long a pedal or throttle sensor fault must "
                          "last before the throttle is shut off until the "
                          "next key-on.",
    "dbwBattComp": "On: the motor output is corrected for battery voltage, "
                   "so the gains mean the same at 9 V cranking as at 14 V "
                   "running.",
    "dbwLimpX10": "Where the return spring holds the plate with the motor "
                  "off. With both throttle tracks failed, alpha-N fuels at "
                  "this opening (limp home).",
    "dbwRateX10": "How fast the throttle TARGET may move. 0 = no limit.",
    "dbwDeadbandX10": "Position errors smaller than this are ignored, so "
                      "the motor does not buzz against sensor noise.",
    "dbwFrictionX10": "Extra motor command in the direction the plate must "
                      "move, to overcome static friction. 0 = off.",
    "dbwRevlimRpm": "Throttle rev limit: above it the throttle target "
                    "closes across the range below. 0 = off.",
    # ---- idle
    "idleEnable": "Turns closed-loop idle control on.",
    "idleTargetAx": "Coolant breakpoints of the idle target curve.",
    "idleTargetVal": "Idle speed wanted at this coolant temperature.",
    "idleBaseAx": "Coolant breakpoints of the idle base position curve.",
    "idleBaseVal": "Throttle (or idle valve) opening at idle before the rpm "
                   "loop corrects it.",
    "idleKp": "Proportional gain of the idle speed loop.",
    "idleKi": "Integral gain of the idle speed loop.",
    "idleRangeX10": "How far the idle loop may move the opening from the "
                    "base position.",
    "idleRpmBand": "The idle loop takes over within this many rpm of the "
                   "target.",
    "idleTimingMinX10": "Largest retard idle timing control may apply.",
    "idleTimingMaxX10": "Largest advance idle timing control may apply.",
    "idleDashHoldMs": "Dashpot: how long the extra opening is held after "
                      "the pedal is released.",
    "idleDashDecayMs": "Dashpot: how long the extra opening then takes to "
                       "fade away.",
    "pinIdleValve": "Connector pin of the idle air valve. Read only when an "
                    "idle air valve is selected.",
    # ---- boost
    "boostEnable": "Turns boost control on.",
    "boostMode": "Open loop (duty table only) or closed loop (duty table "
                 "plus correction towards the boost target).",
    "boostDutyMap": "Wastegate valve duty by rpm and throttle (open-loop "
                    "base).",
    "boostTgtMap": "Boost pressure wanted by rpm and throttle.",
    "boostRpmAx": "rpm breakpoints of the boost duty table.",
    "boostTpsAx": "Throttle breakpoints of the boost duty table.",
    "boostTgtRpmAx": "rpm breakpoints of the boost target table.",
    "boostTgtTpsAx": "Throttle breakpoints of the boost target table.",
    "boostKp": "Proportional gain of the closed-loop boost control.",
    "boostKi": "Integral gain of the closed-loop boost control.",
    "boostKd": "Derivative gain of the closed-loop boost control.",
    "boostMinRpm": "Below this speed the boost valve is not driven.",
    "boostMinTpsX10": "Below this throttle the boost valve is not driven.",
    "boostFreqHz": "Switching frequency of the boost valve.",
    "boostCutKpa": "Overboost: fuel/spark cut above this manifold pressure.",
    "boostCutHyst": "Overboost: the cut ends this far below the limit.",
    "boostCltAx": "Coolant breakpoints of the boost multiplier.",
    "boostCltMul": "Boost target multiplier at this coolant temperature.",
    "boostIatAx": "Intake air breakpoints of the boost multiplier.",
    "boostIatMul": "Boost target multiplier at this intake air "
                   "temperature.",
    "pinBoost": "Connector pin of the boost (wastegate) valve.",
    # ---- protections and limits
    "revlimMode": "What the rev limiter cuts: spark, fuel or both.",
    "cltMaxDegX10": "Coolant over-temperature limit: above it the speed is "
                    "limited (see the coolant limit rpm).",
    "oilPressMinKpa": "Fuel is cut when the oil pressure stays below this "
                      "above the check rpm.",
    "oilPressMinRpm": "The oil pressure check runs only above this speed.",
    "revLimitHyst": "The rev limit cut ends this far below the limit; also "
                    "the soft-limit window below it.",
    "revLimitSoftRetard": "Timing retard ramped in across the window just "
                          "below the rev limit.",
    "revLimitSoftFuel": "Fuel added across the window just below the rev "
                        "limit.",
    # ---- outputs and relays
    "fuelPumpMode": "Off never runs the pump. Auto primes once at key-on, "
                    "runs while the engine turns and stops as soon as it "
                    "stops. There is deliberately no permanent On.",
    "fuelPumpPrimeMs": "How long the pump runs at key-on to build pressure. "
                       "0 = no prime.",
    "pinFuelPump": "Connector pin of the fuel pump relay.",
    "mainRelayModeCfg": "Main relay control: off, on, or automatic.",
    "mainRelayGraceMs": "How long the relay feedback may be missing before "
                        "it counts as a fault.",
    "mainRelayHoldMs": "In Auto, how long the relay stays on after the ECU "
                       "no longer needs power.",
    "pinTacho": "Connector pin of the rev counter output.",
    "pinCam1Sol": "Connector pin of the cam 1 (VVT) solenoid.",
    "pinCam2Sol": "Connector pin of the cam 2 (VVT) solenoid.",
    "pinFan": "Connector pin of the radiator fan relay.",
    "fanOnTemp": "The fan switches on at this coolant temperature.",
    "fanOffTemp": "The fan switches off below this coolant temperature.",
    "pinAcRequest": "Connector pin of the A/C request switch.",
    "pinAcClutch": "Connector pin of the A/C compressor relay.",
    "acRequestActive": "Whether the A/C request is active when the input is "
                       "grounded or when it is high.",
    "acIdleUpX10": "Extra idle opening while the A/C runs.",
    "acIdleRpm": "Extra idle speed while the A/C runs.",
    "acMinRpm": "The A/C compressor is held off below this speed.",
    "acMaxRpm": "The A/C compressor is switched off above this speed.",
    "acMaxTps": "The A/C compressor is switched off above this throttle.",
    "acMaxClt": "The A/C compressor is switched off above this coolant "
                "temperature.",
    "acDelay": "Delay between the A/C request and the compressor switching "
               "on (the idle opens first).",
    "celEnable": "On: the check engine lamp shows the key-on test and the "
                 "stored trouble codes.",
    "pinMil": "Connector pin of the check engine lamp.",
    "celTestOnMs": "Key-on lamp test: time the lamp is on.",
    "celTestGapMs": "Key-on lamp test: time the lamp is off before it shows "
                    "the fault state.",
    "pwmInvert": "Output polarity of the PWM stage.",
    # ---- lambda and closed loop
    "lambdaHeatPolicy": "When the wideband sensor heater may run: never, "
                        "from ignition on, or only with the engine running.",
    "stftEnable": "Turns closed-loop fuel trim from the wideband on. It "
                  "trims only while the wideband is ready (heated, no "
                  "fault).",
    "stftStartDelay": "Closed-loop trim starts this long after the engine "
                      "starts.",
    "stftDeadband": "Lambda errors smaller than this are not corrected.",
    "stftMinClt": "Closed-loop trim runs only above this coolant "
                  "temperature.",
    "stftIdleRpm": "Below this speed the idle region's trim limits apply.",
    "stftPowerLoad": "Above this load the power region's trim limits apply.",
    "stftOverrunLoad": "Below this load the overrun region's limits apply "
                       "(in the fuel load's units).",
    "stftLambdaMin": "Trim learns only above this measured lambda.",
    "stftLambdaMax": "Trim learns only below this measured lambda.",
    "stftAfterDfco": "Trim holds this long after a fuel cut ends.",
    "stftAfterAe": "Trim holds this long after acceleration enrichment.",
    "stftMaxAdd": "Largest fuel the trim may add in this region.",
    "stftMaxRemove": "Largest fuel the trim may remove in this region.",
    "stftTimeConst": "How fast the trim reacts. Longer = calmer.",
    # ---- knock
    "knockMode": "Off, Monitor (knock is detected and logged per cylinder, "
                 "timing unchanged - for calibration) or Active (a knocking "
                 "cylinder's timing is retarded).",
    "knockBand": "The knock detection frequency. 1.8T and this ECU's stock "
                 "setting: 14 kHz.",
    "knockGain": "Knock sensor amplification. Aim for a quiet-engine "
                 "reference of about 100 to 500 counts.",
    "knockSensor": "Which knock sensor hears this cylinder.",
    "knockWinStart": "Where the knock measuring window opens, crank degrees "
                     "after the cylinder's top dead centre.",
    "knockWinLen": "How long the knock measuring window stays open.",
    "knockRpmAx": "rpm breakpoints of the knock window curves.",
    "knockKefRpm": "rpm breakpoints of the threshold factor curve.",
    "knockKef": "A window counts as knock when it is louder than the "
                "cylinder's learned quiet level times this factor. Lower = "
                "more sensitive. 1.00 minimum.",
    "knockKefDyn": "Threshold multiplier while load or speed changes "
                   "fast.",
    "knockTp": "How fast the learned quiet level follows quiet windows.",
    "knockTpDyn": "The same, while load or speed changes fast.",
    "knockLoadMin": "Below this load windows are measured but not judged.",
    "knockRpmMin": "Below this speed no knock window is taken.",
    "knockCltMin": "Below this coolant temperature windows are measured but "
                   "not judged.",
    "knockRefInit": "The quiet level each cylinder starts from.",
    "knockReapplyMs": "A cylinder quiet for this long gets 0.25 degree of "
                      "its retard back.",
    "knockRefMin": "A quiet level below this means an open sensor or wire: "
                   "a sensor fault, and its cylinders take the safety "
                   "retard.",
    "knockRefMax": "A quiet level above this is implausible (sensor "
                   "fault).",
    "knockLearn": "Quiet windows learned per cylinder before knock can be "
                  "detected.",
    "knockStopN": "Knocks in a row with the retard already at its maximum "
                  "before the cylinder is flagged. 0 = off.",
    "knockStepQ": "Timing retard taken per detected knock.",
    "knockMaxQ": "Largest knock retard per cylinder.",
    "knockSafeQ": "Retard applied to the cylinders of a failed knock "
                  "sensor (Active mode only).",
    "knockDiagN": "Implausible windows in a row before a sensor fault is "
                  "set. 0 = no diagnosis.",
    "knockDiagRpm": "The knock sensor diagnosis runs only above this "
                    "speed.",
    # ---- VVT
    "vvtMode": "Cam control mode. Closed loop measures the cam position "
               "(needs a cam pattern on that input); on/off switches the "
               "solenoid by the target table's sign.",
    "vvtInvert": "On: more duty moves the cam away from advance.",
    "vvtFreqHz": "Switching frequency of the cam solenoids (stock 250 Hz).",
    "vvtDelayMs": "Cam control starts this long after the engine starts "
                  "(oil pressure builds first).",
    "vvtMinRpm": "No cam control below this speed.",
    "vvtMinClt": "No cam control below this coolant temperature.",
    "vvtKp": "Proportional gain of the cam position loop.",
    "vvtKi": "Integral gain of the cam position loop.",
    "vvtKd": "Derivative gain of the cam position loop (on the measured "
             "position).",
    "vvtDutyMin": "Lowest solenoid duty in closed loop.",
    "vvtDutyMax": "Highest solenoid duty in closed loop.",
    "vvtDutyOn": "On/off mode: the solenoid duty when on.",
    "vvtErrMax": "A cam further than this from its target for the fault "
                 "time is a stuck or slow phaser: duty 0 until the engine "
                 "stops.",
    "vvtErrMs": "How long the cam may be off target before the fault.",
    "vvtFbMs": "A cam position older than this is not used (duty 0).",
    "vvtRpmAx": "rpm breakpoints of the cam target tables.",
    "vvtLoadAx": "Load breakpoints (cylinder filling %) of the cam target "
                 "tables.",
    "vvtTarget1": "Cam 1 advance wanted, degrees from its zero position. "
                  "On/off mode: above 0 = solenoid on.",
    "vvtTarget2": "Cam 2 advance wanted, degrees from its zero position. "
                  "On/off mode: above 0 = solenoid on.",
    # ---- motorsport
    "launchRpm": "Launch control holds the engine at this speed.",
    "launchRetardDegX10": "Ignition timing while launch control is active.",
    "launchTps": "Launch control is active only above this pedal.",
    "launchCutStart": "Spark cut at the start of the launch window.",
    "launchCutEnd": "Spark cut just before the launch rpm.",
    "launchFuelAdd": "Extra fuel while launch control is active.",
    "launchWindow": "The band below the launch rpm in which the cut ramps "
                    "in.",
    "flatShiftArmRpm": "Flat shift is armed above this speed.",
    "flatShiftCutMs": "How long the flat shift cut lasts.",
    "flatShiftTps": "Flat shift is armed only above this pedal.",
    "flatShiftCutPct": "Spark cut during a flat shift.",
    "flatShiftTimingX10": "Ignition timing during a flat shift cut.",
    "antiLagRetardDegX10": "Ignition timing change while anti-lag is "
                           "active.",
    "antiLagFuelPct": "Extra fuel while anti-lag is active.",
    "alsTpsMax": "Anti-lag is active only below this pedal.",
    "alsRpmMin": "Anti-lag is active only above this speed.",
    "alsRpmMax": "Anti-lag is active only below this speed.",
    "alsCltMin": "Anti-lag is active only above this coolant temperature.",
    "alsCltMax": "Anti-lag is active only below this coolant temperature.",
    "alsCutPct": "Spark cut while anti-lag is active.",
    "alsThrottle": "Extra throttle opening while anti-lag is active.",
    "alsMaxTime": "Anti-lag ends after this long in one activation. 0 = no "
                  "limit.",
    "pitLimiterRpm": "Speed held while the pit limiter is active.",
    "rotIdleCut": "Rotational idle: spark cut.",
    "rotIdleTps": "Rotational idle is active only below this pedal.",
    "rotIdleRpm": "Rotational idle is active only below this speed.",
    "pinLaunch": "Connector pin of the launch control switch.",
    "pinFlatShift": "Connector pin of the clutch / flat shift switch.",
    "pinAntiLag": "Connector pin of the anti-lag switch.",
    "pinPitLimiter": "Connector pin of the pit limiter switch.",
    "motorsportEnable": "Motorsport functions switched on (one per bit).",
    "msSwitchInvert": "Input polarity per motorsport switch.",
    # ---- load model and protection
    "leanGuardEnable": "Lean protection: cut fuel/power when the measured "
                       "lambda stays leaner than the target by the margin "
                       "below.",
    "lambdaPhysicalQualified": "Confirms the wideband has been checked on "
                               "this engine and may be trusted for lean "
                               "protection.",
    "pressureGuardEnable": "Cut when the pressure reading is lost under "
                           "load, for the fuel modes that need it.",
    "densityReference": "Ambient pressure used if the onboard sensor "
                        "fails.",
    "chargeBlendStart": "Boost (above ambient) where the air density starts "
                        "to blend to the charge pressure.",
    "chargeBlendFull": "Boost (above ambient) where the blend is complete.",
    "ambientMaxAge": "After an onboard pressure sensor fault, its last good "
                     "reading is held this long.",
    "pressureMaxAge": "A pressure reading older than this is not used.",
    "pressureGuardRpm": "The pressure-loss cut is active only above this "
                        "speed.",
    "pressureGuardTps": "The pressure-loss cut is active only above this "
                        "throttle.",
    "leanGuardRpm": "Lean protection is active only above this speed.",
    "leanGuardTps": "Lean protection is active only above this throttle.",
    "leanGuardCharge": "Lean protection is active only above this cylinder "
                       "filling.",
    "leanGuardDeviation": "How much leaner than the target counts as lean.",
    "leanGuardPersist": "How long the engine must be lean before the cut.",
    "leanGuardRecovery": "After a cut, how long the engine must be at "
                         "target and off load before power returns.",
    # ---- general purpose outputs
    "pinGp1": "Connector pin of general purpose output 1.",
    "pinGp2": "Connector pin of general purpose output 2.",
    "gp1Logic": "Whether output 1 needs condition A only, A and B, or A or "
                "B.",
    "gp2Logic": "Whether output 2 needs condition A only, A and B, or A or "
                "B.",
    "gp1Delay": "Output 1 switches on only after its conditions have held "
                "this long.",
    "gp2Delay": "Output 2 switches on only after its conditions have held "
                "this long.",
    # ---- controller / housekeeping
    "cfgVersion": "Version of the settings layout. Set by the firmware - "
                  "do not change.",
    "uMagic": "Settings block marker. Set by the firmware - do not change.",
    "uSchema": "Settings block version. Set by the firmware - do not "
               "change.",
    "uGeneration": "Counts accepted setting changes. Set by the firmware.",
    "uCrc": "Settings checksum. Set by the firmware.",
    "enginePreset": "Applying a base tune fills ordinary settings with its "
                    "values; nothing depends on the preset afterwards. Burn "
                    "and restart the ECU after applying one.",
    "tachoScale": "Corrects the rev counter output: a counter reading 10 % "
                  "high wants 91. 0 = 100 %.",
    "testValue": "Value used by the bench output test.",
    "injChannel": "Old per-cylinder injector output number, replaced by "
                  "the injector pins.",
    "ignChannel": "Old per-cylinder coil output number, replaced by the "
                  "coil pins.",
    "injModeLegacy": "Old batch / sequential switch, replaced by Injection "
                     "strategy.",
    "iatChannel": "Old intake air input number, replaced by the intake air "
                  "sensor pin.",
    "cylBank": "Which bank each cylinder belongs to.",
    "trigDecoder": "Crank wheel type, used to check that the wheel settings "
                   "make sense together.",
    "camRefs": "How many cam sensor edges (of the chosen polarity) come in "
               "one 720 degree cycle, equally spaced. 1 is the ordinary "
               "single-window cam and tells the two crank revolutions "
               "apart. An even count cannot: the pattern repeats every 360 "
               "degrees.",
    "pinBaro": "Connector pin of an external barometric sensor. NONE = the "
               "ambient pressure is measured on the ECU board.",
    "testMode": "Bench test mode. Selecting a test does not drive anything "
                "on its own.",
    "testTimeoutMs": "A bench test switches itself off after this time.",
    "s5500WindowBase": "Diagnostics: which part of the output driver's "
                       "status frame the diagnostic window shows.",
    "injPhaseMode": "Injection timing from one fixed angle, or from the "
                    "injection timing table (rpm x fuel load).",
    "injPhaseTable": "Injection angle in degrees before top dead centre of "
                     "the power stroke, by rpm and fuel load: where the "
                     "pulse starts (or ends, per the injection timing "
                     "setting).",
    "dfcoMinClt": "Fuel cut on overrun only above this coolant temperature. "
                  "A failed coolant sensor stops the cut.",
    "dfcoMapMax": "Fuel cut on overrun only below this manifold pressure. "
                  "0 = no pressure condition (the only right setting for a "
                  "pressure sensor before the throttle).",
    "lambdaLoadAx": "The load breakpoints of the target lambda table: kPa "
                    "or %, per the target lambda load setting.",
    "lambdaLoadMode": "Which load the target lambda table uses. A failed "
                      "sensor reads as 200 kPa / 100 % (rich).",
    "idleTimingKp": "Degrees of spark per 100 rpm of idle speed error. "
                    "10 is a good start.",
    "loadSource": "How the engine load for the fuel is found. Speed "
                  "density: VE by rpm and manifold pressure, needs a true "
                  "manifold pressure sensor (on a sensor fault the pressure "
                  "estimate table stands in). Alpha-N + measured pressure: "
                  "VE by rpm and throttle, times the measured inlet "
                  "pressure - for a pressure sensor BEFORE the throttle "
                  "(stock 1.8T). Pure alpha-N: VE by rpm and throttle at "
                  "101.3 kPa, no pressure sensor needed.",
    "tdcCylExtDegX10": "Top dead centre of cylinders 9 to 12, in engine "
                       "degrees after cylinder 1's. Firing order Custom "
                       "only.",
}

# Prefixes for the generic fallbacks of fields with no text at all.
_PAD = re.compile(r"(^|[a-z])Pad\d*$|^pad\d+$|Pad$")

# --------------------------------------------------------------------------
# 2. Cleaning the model notes.
# --------------------------------------------------------------------------
_REF_PAREN = re.compile(
    r"\s*\((?:[^()]*?)(?:rusEFI|Bosch|Speeduino|BIN 0x|\w+\.[ch]\b|family "
    r"table|V\d{2}\b|OEM's|FR )[^()]*\)")
_LEAD = re.compile(r"^(?:V\d{2,3}:\s*|(?:RPM_ZERO|RESTART_REQUIRED|"
                   r"LIVE_APPLY)\b[.:]?\s*(?:and\s+)?|rusEFI [\w.]+[:.]?\s*)")
_DROP = re.compile(
    r"rusEFI|Speeduino|Bosch|Funktionsrahmen|\b[A-Z]{2,}_[A-Z0-9_]+\b|"
    r"0x[0-9A-Fa-f]+|\bhc\w+\.[ch]\b|docs/|\bpage\b|layout|HAL|ADDAT|"
    r"syncState|\bCPU\b|scheduler|decoder's|\bbit \d|\bOEM\b|\b[A-Z]{3,}\d|"
    r"\binit\b|router|universal block|firmware writes")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9'(])")


def _labels():
    fields, _c, _p = MODEL.resolve()
    return {f.meta.ts: f.meta.label for f in fields}


def clean_note(note: str, labels: dict[str, str]) -> str:
    """The model note in tuner language, or '' when nothing usable is left."""
    text = " ".join(note.split()).replace("%%", "%")
    text = _REF_PAREN.sub("", text)
    out = []
    for s in _SENT.split(text):
        s = _LEAD.sub("", s.strip()).strip()
        if not s:
            continue
        # a field name a tuner never sees becomes the label they do see
        def sub(m):
            w = m.group(0)
            return "'%s'" % labels[w] if w in labels else w
        s = re.sub(r"\b[a-z][a-z0-9]*[A-Z][A-Za-z0-9]*\b", sub, s)
        if _DROP.search(s) or any(re.search(rx, s) for rx, _c, _r in TERMS):
            continue
        # a lone identifier sentence ("Missing-tooth decoder only." stays)
        if re.fullmatch(r"[\w'.]+\.?", s) and "'" not in s:
            continue
        first = s.split()[0]
        if not any(c.isupper() for c in first[1:]):
            s = s[0].upper() + s[1:]
        out.append(s)
    return " ".join(out).strip()


# --------------------------------------------------------------------------
# 3. Generated facts.
# --------------------------------------------------------------------------
def _fmt(v: float, digits: int) -> str:
    s = ("%." + str(max(digits, 0)) + "f") % v
    return s


def range_text(m) -> str:
    if m.is_pin or m.enum is not None or m.ts in UI.STAGE_A_SELECTORS:
        return ""
    s = float(m.scale) if m.scale else 1.0
    lo = m.lo * s + m.translate
    hi = m.hi * s + m.translate
    if lo > hi:
        lo, hi = hi, lo
    u = (" " + m.units) if m.units else ""
    return "Range %s to %s%s." % (_fmt(lo, m.digits), _fmt(hi, m.digits), u)


def choices_text(m) -> str:
    if m.enum is not None:
        opts = [lbl for _v, _i, lbl in m.enum.options]
    elif m.ts in UI.STAGE_A_SELECTORS:
        opts = [x for x in UI.STAGE_A_SELECTORS[m.ts][0] if x != "INVALID"]
    else:
        return ""
    if len(opts) > 8:
        return ""
    return "Choices: %s." % ", ".join(o.split(" - ")[0] for o in opts)


def _base_text(m, labels) -> str:
    ts = m.ts
    if ts in HELP:
        return HELP[ts]
    if m.note.lstrip().upper().startswith("RETIRED"):
        return RETIRED_TEXT
    t = clean_note(m.note, labels) if m.note else ""
    if t:
        return t
    if m.is_pin:
        return "Connector pin for: %s. NONE = not connected." % m.label
    if m.enum is not None and m.enum.description:
        d = m.enum.description
        if not any(re.search(rx, d) for rx, _c, _r in TERMS) \
                and not _DROP.search(d):
            return "%s: %s." % (m.label, d[0].lower() + d[1:].rstrip("."))
    return "%s." % m.label


def help_for_meta(m, labels, prefix: str = "") -> str:
    if _PAD.search(m.ts):
        return "Spare byte that keeps the settings aligned. Not used."
    parts = [(prefix + ": " if prefix else "") + _base_text(m, labels)]
    if m.ts in UX.UNUSED:
        parts.append(UNUSED_TEXT)
    else:
        for extra in (choices_text(m), range_text(m)):
            if extra:
                parts.append(extra)
        parts.append(APPLY_TEXT[m.apply])
        if m.safety_critical:
            parts.append(SAFETY_TEXT)
    text = " ".join(p for p in parts if p)
    text = text.replace('"', "'").replace(";", ",")
    return " ".join(text.split())


def help_lines(fields, constant_names) -> list[str]:
    """One `name = "text"` line per declared Constant that is a page field,
    a per-element alias or a bit view of one."""
    labels = {f.meta.ts: f.meta.label for f in fields}
    by_ts = {f.meta.ts: f for f in fields}
    out, missing = [], []
    for name in constant_names:
        if name in by_ts:
            out.append((name, help_for_meta(by_ts[name].meta, labels)))
            continue
        if name in UI.BIT_VIEWS:
            base, _bit, lbl, opts = UI.BIT_VIEWS[name]
            m = by_ts[base].meta
            txt = "%s. Choices: %s. %s" % (lbl, ", ".join(opts),
                                           APPLY_TEXT[m.apply])
            out.append((name, txt.replace('"', "'")))
            continue
        bases = [b for b in UI.ELEMENT_FIELDS
                 if b in by_ts and name.startswith(b)
                 and name[len(b):].isdigit()]
        if bases:
            base = max(bases, key=len)
            n = int(name[len(base):])
            fmt = UI.ELEMENT_FIELDS[base][0]
            first = 9 if base == "tdcCylExtDegX10" else 1
            try:
                pre = UI.element_label(fmt, n, first)
            except IndexError:
                pre = "%s %d" % (by_ts[base].meta.label, n)
            out.append((name, help_for_meta(by_ts[base].meta, labels, pre)))
            continue
        missing.append(name)
    lines = ['   %-22s = "%s"' % (n, t) for n, t in out]
    return lines, missing


def constant_names(page_lines) -> list[str]:
    names = []
    for ln in page_lines:
        m = re.match(r"\s*(\w+)\s*=\s*(scalar|bits|array|string)\b", ln)
        if m:
            names.append(m.group(1))
    return names


def section(fields, page_lines) -> list[str]:
    lines, missing = help_lines(fields, constant_names(page_lines))
    bad = [ln.split("=")[0].strip() + ": " + m.group(0)
           for ln in lines for rx, _c, _r in TERMS
           for m in [re.search(rx, ln.split("=", 1)[1])] if m]
    if bad:
        raise SystemExit("[SettingContextHelp]: tuner text carries "
                         "forbidden terms: %s" % "; ".join(bad))
    if missing:
        raise SystemExit("[SettingContextHelp]: no help source for %s"
                         % ", ".join(missing))
    return lines


if __name__ == "__main__":
    fs, _by, _c = UI.layout()
    for ln in section(fs, UI.page_lines(fs)):
        print(ln)
