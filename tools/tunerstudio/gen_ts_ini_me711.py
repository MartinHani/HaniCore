#!/usr/bin/env python3
r"""
gen_ts_ini_me711.py - generate the TunerStudio .ini for the Bosch ME7.1.1
bench-safe image, from the firmware's own headers.

    py tools\tunerstudio\gen_ts_ini_me711.py

Nothing here is retyped from the firmware. The signature, the baud, the block
size and the page size come out of hctarget.h and hcconfig.h, and every channel
offset is CROSS-CHECKED against the put16() calls in hcmain_me711.c - so an
offset that moves in the firmware and not here is a build error rather than a
gauge that quietly reads the wrong number.

That check is not paranoia. On the ME7.5 target a .ini that had drifted by two
bytes is exactly how a value gets written into the wrong field.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
ROOT = Path(__file__).resolve().parents[2]
TDIR = ROOT / "firmware/targets/me711"
SHARED = ROOT / "firmware"
OUT = ROOT / "tunerstudio/hanicore_me711.ini"

# Bases for the S5500 correlation-window sweep.
#
# THE FIRST TWO ARE PREDICTIONS, not a scan. an OEM-firmware analysis script (not published)
# correlates the OEM's own RX unpack table against Porsche's A2L and puts the
# whole raw-acquisition block in runtime frame words 7-25:
#
#     throttle pot 1/2      words  7-11
#     boost pressure        words 10-12
#     ambient pressure      words 12-16
#     air mass 1/2          words 15-18
#     pedal pot 1/2         words 17-19
#     COOLANT A/D wtmot_w   words 21-23     <- the one that matters
#     battery A/D           words 22-25
#
# A window at base 12 covers words 12-27 and contains every coolant candidate;
# base 8 covers 8-23 and catches the throttle and pressure end. Those two are
# worth trying FIRST, and either confirms or refutes the correlation in one
# reading. The remaining bases are the old blind scan, kept as the fallback
# for when the prediction is wrong - which is a real possibility, because the
# correlation is PROBABLE and not proven.
#
# Base 4 stays in the list because that is where the STARTUP reply's analog
# block was PROVEN to sit on hardware in the V9 run (2026-08-28, tenth
# hardware). The runtime reply is a different frame and that is the point.
S5500_SWEEP = (12, 8, 4, 20, 28, 36, 52, 68, 84, 100)

# Seeds for the external-SRAM execution probe. Four is enough to make a
# coincidence implausible and few enough to fit one dialog.
RAM_PROBE_SEEDS = (0x11, 0x5A, 0xA5, 0xEE)

# The HC_TEST_* values the bench buttons send. READ FROM THE GENERATED HEADER,
# because a mode number typed here and a mode number in the firmware are
# exactly the two-artefacts-that-must-agree problem this project keeps paying
# for.
_gen_h = (ROOT / "firmware/generated/hc_config_generated.h").read_text(
    errors="replace")


def _test_mode(name):
    m = re.search(r"#define\s+HC_TEST_%s\s+(\d+)u" % name, _gen_h)
    if not m:
        raise SystemExit("HC_TEST_%s is not in hc_config_generated.h" % name)
    return int(m.group(1))


TEST_INJECTOR = _test_mode("INJECTOR")
TEST_COIL = _test_mode("COIL")
TEST_FUEL_PUMP = _test_mode("FUEL_PUMP")
TEST_DBW = _test_mode("DBW")
TEST_MAIN_RELAY = _test_mode("MAIN_RELAY")
TEST_VVT = _test_mode("VVT")
TEST_BOOST = _test_mode("BOOST")   # the ASIC-image stages (hcbench.c)
# The versioned copy is named from THE IMAGE UNDER TEST, not from a literal.
# This line said "v28_trigger_comm" while the build produced v29, which is the
# same class of drift that once had six gates auditing a stale binary and
# passing. tools/lib/me711_image.py is the single place a version is written down.
import me711_image as _PI  # noqa: E402
import gen_ts_ui_me711 as UI  # noqa: E402  the model-driven settings UI
import ts_semantics_me711 as SEM  # noqa: E402  firmware state names
import gen_ts_ux_me711 as UX  # noqa: E402  the rusEFI-shaped workflows
import me711_ambient_pressure as AMB  # noqa: E402  the BARO chain
OUT_VERSIONED = ROOT / ("tunerstudio/hanicore_%s.ini"
                        % _PI.STEM.replace("HaniCore_ME711_", "me711_").lower())
OUT_FALLBACK = OUT_VERSIONED.with_name(OUT_VERSIONED.stem
                                       + "_userdefined_fallback.ini")
OUT_FORENSIC = OUT_VERSIONED.with_name(OUT_VERSIONED.stem + "_forensic.ini")

tgt = (TDIR / "hctarget.h").read_text(errors="replace")
main_c = (TDIR / "system/hcmain_me711.c").read_text(errors="replace")
main_c += "\n" + (TDIR / "diagnostics/hcdiag711.c").read_text(errors="replace")
cfg_h = (SHARED / "config/hcconfig.h").read_text(errors="replace")
hcts_h = (SHARED / "comms/hcts.h").read_text(errors="replace")


def d(text, name):
    m = re.search(r"#define\s+%s\s+(0x[0-9A-Fa-f]+|\d+)" % name, text)
    if not m:
        raise SystemExit(f"{name} not found")
    return int(m.group(1), 0)


SIGNATURE = re.search(r'#define TGT_SIGNATURE\s+"([^"]+)"', tgt).group(1)
# DERIVED, NEVER TYPED. TunerStudio must outwait the firmware's own live-Burn
# deadline or it reports a failure for a Burn that is still running and will
# succeed - and the two numbers are in different files, which is exactly the
# shape of drift the project rules "two artefacts that must agree" rule is about.
# One third on top of the deadline, rounded up to the next whole second.
LIVE_BURN_DEADLINE_MS = int(re.search(
    r"#define\s+TGT_LIVE_BURN_DEADLINE_MS\s+(\d+)", tgt).group(1))
BLOCK_READ_TIMEOUT_MS = -(-(LIVE_BURN_DEADLINE_MS * 4 // 3) // 1000) * 1000
VERSIONTXT = re.search(r'#define TGT_VERSIONTXT\s+"([^"]+)"', tgt).group(1)
OCH_SIZE = d(tgt, "TGT_OCH_SIZE")
# The forensic view covers the ordinary block AND the whole live-Burn
# record. Both halves are the target header's to say - see the comment
# on TGT_OCH_READ_SIZE for what a literal cost here.
OCH_READ_SIZE = OCH_SIZE + 344
BAUD = d(tgt, "TGT_BAUD")
PAGE_SIZE = d(cfg_h, "HC_CFG_SIZE")
BLOCKING = d(hcts_h, "BLOCKING")

# TunerStudio hardcodes 'Q' (and 'F') as its OWN blind multi-port scan probe -
# see rusEFI firmware/console/binary/tunerstudio.cpp,
# handlePlainCommand(). A project's queryCommand must be a DIFFERENT letter,
# or every real handshake reply reads to TunerStudio's client as just another
# scan answer and it never leaves scan mode - real hardware trace, V23:
# F/Q/F/Q forever, 'V'/'P'/'R' never once attempted. The known-good ME7.5
# reference uses "S" for exactly this reason. hcts.c answers 'S' and 'Q'
# identically (`case 'S': case 'Q':` in both handle_plain() and handle()), so
# changing this costs no firmware behaviour.
import ts_gauges_me711 as GM   # noqa: E402  V98: gauge titles / categories / datalog

QUERY_CMD = "S"
if QUERY_CMD == "Q":
    raise SystemExit("QUERY_CMD must not be 'Q' - see the comment above; "
                      "this exact regression looped TunerStudio forever on "
                      "real Bosch hardware (V23)")

# (offset, name, kind, units, description). "kind" is U16 unless noted.
CH = [
    (0,   "status",       "U16", "",     "the status word - see the indicators"),
    (2,   "bootStage",    "U16", "",     "how far the last boot got: 11 = the main loop"),
    (4,   "tickMs",       "U16", "ms",   "the 1 ms system tick, free running"),
    (6,   "loopCount",    "U16", "",     "main-loop passes"),
    (8,   "frames",       "U16", "",     "telemetry refreshes"),
    (10,  "calTicks",     "U16", "tick", "MEASURED T7 ticks per transmitted byte - must read about 220"),
    (12,  "cfgSource",    "U16", "",     "0 defaults, 1 battery SRAM, 3 flash"),
    (14,  "ramBad",       "U16", "",     "external SRAM probe failures - must be 0"),
    (16,  "rxBytes",      "U16", "",     "serial bytes the parser consumed"),
    (18,  "rxReqs",       "U16", "",     "complete requests received"),
    (20,  "rxResync",     "U16", "",     "requests abandoned mid-frame - a lost byte"),
    (22,  "rxHwOvr",      "U16", "",     "the HARDWARE threw a byte away. This is the number"),
    (24,  "rxFrameErr",   "U16", "",     "framing errors - the WIRE, not the timing"),
    (26,  "rxOvf",        "U16", "",     "the ring filled: the MAIN LOOP fell behind"),
    (28,  "rxEchoLost",   "U16", "",     "a transmitted byte never echoed back"),
    (30,  "rxTicks",      "U16", "",     "serial drain ticks served"),
    (32,  "rxIrqOk",      "U16", "",     "1 if the ASC0 receive interrupt came up (expected 0 here)"),
    (34,  "rxTickOk",     "U16", "",     "1 if the CAPCOM drain tick came up - this is the real path"),
    (36,  "s0rTrap",      "U16", "",     "trap the receive interrupt fired on, 0 = never"),
    (38,  "probeBad",     "U16", "",     "interrupts the boot probe saw it could not name"),
    (40,  "badVec",       "U16", "",     "interrupts nobody asked for - must be 0"),
    (42,  "firstVec",     "U16", "",     "trap number of the first of them"),
    (44,  "lastVec",      "U16", "",     "trap number of the most recent"),
    (46,  "asicState",    "U16", "",     "active hcasicstart state: 0 idle 1 sscInit 2 tx1 3 wait1 4 tx2 5 wait2 6 runTx 7 runWait"),
    (48,  "asicAlive",    "U16", "",     "active state machine accepted a startup/runtime frame in the last 100 ms"),
    (50,  "asicTx",       "U16", "",     "active startup+runtime exchanges started"),
    (52,  "asicRx",       "U16", "",     "active startup+runtime exchanges completed"),
    (54,  "asicStartOk",  "U16", "",     "active 96-word startup frames accepted"),
    (56,  "asicRunOk",    "U16", "",     "active 118-word runtime frames accepted"),
    (58,  "asicCsumOk",   "U16", "",     "active startup+runtime checksums that matched"),
    (60,  "asicCsumErr",  "U16", "",     "active startup+runtime checksums that did not"),
    (62,  "asicClassErr", "U16", "",     "active retry counter; name retained for offset compatibility"),
    (64,  "asicTimeouts", "U16", "",     "active startup+runtime exchanges that timed out"),
    (66,  "asicSscErr",   "U16", "",     "active SSC error interrupts seen"),
    (68,  "asicLastClass","U16", "",     "the reply class byte last seen"),
    (70,  "asicLastCsum", "U16", "",     "what the last frame summed to"),
    (72,  "asicWantCsum", "U16", "",     "what its checksum word claimed"),
    (74,  "asicWord0",    "U16", "",     "raw frame word 0 - deliberately unnamed"),
    (76,  "asicWord1",    "U16", "",     "raw frame word 1"),
    (78,  "asicWord2",    "U16", "",     "raw frame word 2"),
    (80,  "asicWord3",    "U16", "",     "raw frame word 3"),
    (82,  "cfgWrites",    "U16", "",     "TunerStudio page value writes"),
    (84,  "cfgBurns",     "U16", "",     "burns"),
    (86,  "cfgFaults",    "U16", "",     "why the setup is not a runnable engine"),
    (88,  "cfgStable",    "U16", "",     "1 while the page is quiet"),
    (90,  "battery",      "U16", "V",    "battery volts from AN5, packed as centivolts"),
    (92,  "stalls",       "U16", "",     "deliberate main-loop stalls executed"),
    (94,  "targetId",     "U16", "",     "0x0711 - which board this firmware is for"),
]
# ===================== the V20 HaniCore runtime block =====================
# Everything above is the PLATFORM (boot, serial, supervision). These are the
# common HaniCore engine runtime actually running on this ECU: the same
# hcengine.c the ME7.5 board compiles, reading this board's sensors through
# the HAL, while not one output can be energised.
RUNTIME_CH = [
    (128, "battDv",      "V",    "battery, 0.1 V - the engine layer's own value"),
    (130, "cltDc",       "C",    "coolant AS MEASURED (V91): S5500 AN0 (cavity 93) through cltSensAx/Val, shown whether or not it is plausible - sensorErr bit 0 (CLT lamp) says when it is not, and cltCtrlDc is what the models then use. 0 raw = no tagged ASIC sample"),
    # V91: 780..783, the 4 bytes TGT_OCH_SIZE grew by (782 reserved).
    (780, "cltCtrlDc",   "C",    "coolant, the same measurement as cltDc (-40 C while invalid). V98: each function applies its OWN fallback on a fault (warm-up 100 %, cranking 20 C, idle 0 C, film 90 C)"),
    (132, "iatDc",       "C",    "intake air AS MEASURED: S5500 AN1 (cavity 26); -40 C while invalid (sensorErr bit 9) - the fuel then takes 0 C, the timing correction 0 (V98, per consumer)"),
    (134, "mapKpaX10",   "kPa",  "pressure AS MEASURED from the routed cavity (VAG 1.8T: 101, charge pressure BEFORE the throttle); 0 kPa while invalid (mapError) - the fuel then uses the MAP estimate table (mapControl)"),
    (136, "tpsX10",      "%",    "throttle position, track 1"),
    (138, "tps2X10",     "%",    "throttle position, track 2"),
    (140, "pedalX10",    "%",    "accelerator pedal, track 1"),
    (142, "pedal2X10",   "%",    "accelerator pedal, track 2"),
    (144, "engLoad",     "",     "the fuel load: MAP kPa (speed density) or throttle % (alpha-N), 0.1 units"),
    (146, "injTiUs",     "us",   "injector pulse width the fuel model asks for, incl. dead time, per cycle before splitting"),
    (148, "advX10",      "deg",  "commanded ignition advance, 0.1 deg BTDC, SIGNED (negative = after TDC)"),
    (150, "dwellX100",   "ms",   "dwell from the battery curve, 0.01 ms"),
    (152, "sensorErr",   "",     "one bit per sensor - see the indicators"),
    (154, "afrX10",      "",     "the target lambda table's cell: lambda x 147 (= AFR x 10 on gasoline)"),
    (156, "warmupPct",   "%",    "warm-up enrichment, 100 = none"),
    (158, "fuelCut",     "",     "1 overrun, 2 rev limit, 4 overboost"),
    (160, "rpm",         "rpm",  "0 on a stationary bench: no crank capture is armed - see hctrig_me711.c"),
    (162, "syncState",   "",     "0 no signal 1 counting 2 gap 3 crank sync 4 full"),
    (164, "halAinMask",  "",     "bit per HAL channel: 1 = this board really has it"),
    (166, "halOutCalls", "",     "output requests the engine logic made (counter)"),
    (168, "s5500Base",   "",     "first frame word of the S5500 correlation window"),
    (170, "s5500Idx",    "",     "bit i = window word i decodes as ADDAT channel i. 0xFFFF = the V9 signature"),
    (172, "s5500Snaps",  "",     "window snapshots taken"),
    (174, "s5500Plaus",  "",     "snapshots where ALL 16 indices matched"),
]
CH += [(o, n, "S16" if n == "advX10" else "U16", u, d_)
       for (o, n, u, d_) in RUNTIME_CH]
for i in range(16):
    CH.append((176 + 2 * i, "s5500w%02d" % i, "U16", "",
               "S5500 runtime-frame word (base + %d), raw. Sweep the base with "
               "'!W' and watch s5500Idx" % i))

# V21 main-power-relay development telemetry. The Bosch HAL is intentionally
# unbound, so command can follow the TS mode while bound/feedbackValid remain
# zero and mismatch remains informational/clear.
CH += [
    (208, "mainRelayMode",     "U16", "",  "0 OFF, 1 ON, 2 AUTO"),
    (210, "mainRelayCommand",  "U16", "",  "logical request; not proof of electrical actuation"),
    (212, "mainRelayFbV",      "U16", "V", "feedback voltage, 0.1 V; zero while unavailable"),
    (214, "mainRelayFbState",  "U16", "",  "feedback logical state when valid"),
    (216, "mainRelayMismatch", "U16", "",  "informational only, after grace interval"),
    (218, "mainRelayBound",    "U16", "",  "1 = the CONFIGURED cavity is a CPU output this build drives (V75); 2 = the NATIVE main-relay stage (cavity 23, CJ910 MR), which follows KL15 in hardware and is never written (V78); 0 = unassigned or unreachable"),
    (220, "mainRelayFbValid",  "U16", "",  "1 only when feedback voltage/state is trustworthy"),
]

# V27 position, dual-cam and counting-only scheduler telemetry. crankPeriod is
# U32 because one revolution at 80 rpm is 937,500 T1 ticks.
CH += [
    (222,"crankPeriod","U32","tick","gap-to-gap T1 period, 0.8 us/tick"),
    (226,"lastToothPeriod","U16","tick","raw last valid edge period"),
    (228,"crankToothIndex","U16","","0 is first edge after the 60-2 gap"),
    (230,"crankGapMetric","U16","x0.1","gap / mean prior two periods, x10"),
    (232,"crankGapDetected","U16","","current edge was reference interval"),
    (234,"crankSync","U16","","360-degree position proven"),
    (236,"cycleSync","U16","","1 = the 720-degree phase is known (syncState 4). Only a cam cycle sync mode can grant it"),
    (238,"crankEdges","U16","","crank captures"),
    (240,"crankGaps","U16","","reference intervals"),
    (242,"syncLossCount","U16","","CRANK sync withdrawals since boot. An engine stop is NOT counted (V77); a +/-1 tooth correction is NOT counted (V92, toothCorrections); a cam problem is NOT counted (V92, cycleSyncLost)"),
    (244,"syncLossReason","U16","","last crank loss: 0 none,1 stall,2 early gap,3 missing gap,4 malformed,5 extra edge"),
    (246,"enginePositionDeg","U16","deg","position, 0.1 degree over 720"),
    (248,"stallState","U16","","no valid edge inside timeout"),
    (250,"crankNoiseEdges","U16","","too-early captures rejected"),
    (252,"crankIsrTicks","U16","tick","latest CC15 ISR runtime"),
    (254,"crankIsrMax","U16","tick","maximum CC15 ISR runtime"),
    (256,"crankIsrHeadroom","U16","tick","period minus ISR runtime"),
    (258,"crankPhase","U16","","alternating half, not cycle proof"),
    (260,"crankRevolutions","U16","","position-agreeing revolutions"),
    (262,"cam1Raw","U16","","P2.8 sampled on falling edge"),
    (264,"cam2Raw","U16","","P2.9 sampled on falling edge"),
    (266,"cam1Edges","U16","","NWDG1 captures"),
    (268,"cam2Edges","U16","","NWDG2 captures"),
    (270,"cam1Tooth","U16","","last NWDG1 tooth"),
    (272,"cam2Tooth","U16","","last NWDG2 tooth"),
    (274,"cam1Window","U16","","WNWRPS window 0..3, 65535 invalid"),
    (276,"cam2Window","U16","","WNWRPS2 window 0..3, 65535 invalid"),
    (278,"camError","U16","","window/missing bit mask"),
    (280,"camSyncLossReason","U16","","explicit cam reason"),
    (282,"camWindowOkCount","U16","","calibrated window matches"),
    (284,"schedulerQueued","U16","","current dry event depth"),
    (286,"schedulerExecuted","U16","","dry deadlines consumed"),
    (288,"schedulerCancelled","U16","","events cancelled with sync"),
    (290,"schedulerLate","U16","","late dry deadlines"),
    (292,"schedulerMissed","U16","","queue full or >tooth late"),
    (294,"schedulerMaxLatency","U16","tick","worst dry lateness"),
    (296,"schedulerNextAngle","U16","deg","next angle, 0.1 degree"),
    (298,"schedulerLastAngle","U16","deg","last angle, 0.1 degree"),
    (300,"schedulerCaptureOverflow","U16","","ISR/task ring overflow"),
    (302,"nextIgnSlot","U16","","logical firing slot, not cylinder map"),
    (304,"nextInjSlot","U16","","logical firing slot, not cylinder map"),
    (306,"sparkAdvance","S16","deg","the advance the scheduler is placing, 0.1 degree, signed"),
    (308,"dwellTime","U16","ms","dry dwell, 0.01 ms"),
    (310,"injPulse","U16","us","dry pulse width"),
    (312,"scheduledDwellStart","U16","deg","dry angle, 0.1 degree"),
    (314,"scheduledSpark","U16","deg","dry angle, 0.1 degree"),
    (316,"scheduledInjStart","U16","deg","dry angle, 0.1 degree"),
    (318,"scheduledInjEnd","U16","deg","dry angle, 0.1 degree"),
    (320,"outputAuthority","U16","","bit0 all/bit1 DBW-pump-relay/bit2 IGN/bit3 INJ allowed"),
    (322,"safetyInhibits","U16","","BENCH_SAFE/no-cycle-sync/ASIC bits"),
    (324,"crankGapPending","U16","","one-sided long interval awaiting successor"),
    (326,"cam1ObservedAngle","U16","deg","last cam 1 falling edge, 0.1 degree"),
    (328,"cam2ObservedAngle","U16","deg","last cam 2 falling edge, 0.1 degree"),
    (330,"schedulerPending","U16","","long-horizon software event count"),
    (332,"schedulerStatus","U16","","bit0 angle epoch, bit1 near armed, bit2 synced"),
    (334,"triggerCaptureArmed","U16","","CC15/CC8/CC9 and T1 runtime ownership"),

    # ---- the universal configuration's own state ------------------------
    # 336..354, the 32 bytes TGT_OCH_SIZE was grown by. They are NOT in
    # 176..206: that range is the S5500 runtime-frame window, written in a
    # loop, and putting them there silently aliased ten channels onto it.
    (336,"cfgDirtyGroups","U16","","apply groups staged, waiting for RPM = 0"),
    (338,"cfgValidation","U16","","HC_VAL_* over the DESIRED page; 0 = runnable"),
    (340,"cfgWarnings","U16","","HC_WARN_*; advisory, never blocks an apply"),
    (342,"cfgDesiredRev","U16","","host edits accepted into DESIRED"),
    (344,"cfgActiveRev","U16","","apply-group transactions committed to ACTIVE"),
    (346,"cfgApplyRefused","U16","","transactions validation refused"),
    (348,"cfgStateBits","U16","","b0 restart pending, b1 migrated this boot, "
                                 "b2..3 persistence class (0 none, 1 standby, "
                                 "2 non-volatile)"),
    (350,"cfgRouteMismatch","U16","","bit per HC_AIN_* whose configured pin "
                                     "disagrees with the channel read"),
    (352,"cfgRouteRouted","U16","","bit per HC_AIN_* routed to a readable pin"),
    (354,"cfgFirstBadOffset","U16","","page offset of the first validation "
                                      "failure, 0xFFFF = none"),
    (356,"lambdaTarget","U16","lambda","THE canonical fuel target. AFR is the "
                                       "stored form and a display conversion; "
                                       "lambda is what the engine is about"),
    (358,"rlX10","U16","%","RELATIVE AIR CHARGE - HaniCore's canonical load, "
                           "0.1 %. 100 % is the cylinder charge at 0 degC and "
                           "1013 hPa, which is ME7's own reference, so a "
                           "naturally aspirated engine reads about 92 % at sea "
                           "level rather than 100 %"),
    (360,"airMgX10","U16","mg","cylinder air mass per intake event, 0.1 mg - "
                               "the quantity the fuel is actually computed "
                               "from, published so a bench can see WHY the "
                               "pulse width is what it is"),
    (362,"schedulerCatchup","U16","","events the angle scheduler had to "
                                     "issue immediately because the advance "
                                     "or dwell angle moved further between "
                                     "two teeth than the crank did"),
    # ---- the bench output qualifier ------------------------------------
    # THE ONLY PATH IN THIS IMAGE THAT CAN DRIVE AN ENGINE OUTPUT, and these
    # four say exactly what it is doing and why it refused when it did.
    (364,"hcbState","U16","","0 idle 1 RUNNING 2 done 3 refused 4 aborted"),
    (366,"hcbRefuse","U16","","why the last request was refused: 1 rpm/crank, "
                              "2 outputs not armed, 4 invalid page, 8 no "
                              "proven port for that mode, 16 channel out of "
                              "range, 32 busy, 64 supervision link down. "
                              "EVERY unmet reason is set at once"),
    (368,"hcbModeCh","U16","","high byte the HC_TEST_* mode, low byte the "
                              "1-based channel"),
    (370,"hcbPortBit","U16","","high byte the CPU PORT driven (2, 7 or 8), "
                               "low byte the bit. Reported so a scope trace "
                               "can be tied to a pin rather than to a name"),
    (372,"hcbWidthUs","U16","us","the CLAMPED pulse width, MICROSECOND modes "
                                 "(injector, coil, DBW). Reads 0 in the "
                                 "millisecond modes - the two units never "
                                 "share a field"),
    (374,"hcbWidthMs","U16","ms","the CLAMPED energisation, MILLISECOND modes "
                                 "(fuel pump relay). Reads 0 otherwise"),
    (376,"hcbConnPin","U16","","the ECU CONNECTOR CAVITY this run drives, "
                               "where one is known: 65 for the fuel pump "
                               "relay, 117 for the throttle bridge. 0 means "
                               "the cavity is not established for that mode"),
    (378,"hcbAbort","U16","","why the last run stopped early: 1 host !X, "
                             "2 crank edge, 4 page went invalid, 8 timeout, "
                             "16 bridge fault pin, 32 throttle moved past the "
                             "band, 64 the TPS tracks stopped agreeing, "
                             "128 the S5500 supervision link stopped "
                             "mid-run"),
    (380,"hcbPulses","U16","","completed pulses of the current or last run"),
    (382,"hcbRuns","U16","","runs that actually started, ever"),
    (384,"hcbTpsStart","U16","cnt","DBW only: TPS1 raw counts sampled BEFORE "
                                   "the bridge was enabled - the reference "
                                   "the runaway guard measures against"),
    (386,"hcbTpsNow","U16","cnt","DBW only: TPS1 raw counts on the last "
                                 "service pass"),
    (388,"hcbSfLevel","U16","","DBW only: the raw S8100 SF pin (P3.15). It is "
                               "open drain with a pull-up, so 0 is the "
                               "asserted level - but CAL_DBW_SF_MODE decides "
                               "what counts as a fault"),
    # ---- the fuel pump lifecycle ---------------------------------------
    (390,"fuelPumpState","U16","","low byte 0 OFF 1 PRIME 2 CRANKING 3 RUNNING "
                                  "4 STOPPED 5 FAULT; bit 8 is the request "
                                  "made of the HAL; bits 9..15 the CONFIGURED "
                                  "connector cavity. One word, so state, "
                                  "request and destination can never be read "
                                  "from different passes"),
    (392,"fuelPumpReason","U16","","why the pump is not commanded on: "
                                   "1 ignition off, 2 the bounded prime "
                                   "finished, 4 the engine stopped, 8 invalid "
                                   "page, 16 runtime fault, 32 prime disabled, "
                                   "64 requested ON but the output is not "
                                   "permitted (not armed, link down, page "
                                   "refused)"),
    (394,"fuelPumpRuns","U16","","OFF->ON transitions, ever"),
    (396,"fuelPumpPrimeLeft","U16","ms","milliseconds left of the prime; "
                                        "0 outside PRIME"),
    # ---- the power path ------------------------------------------------
    # ---- the closed-loop throttle --------------------------------------
    (400,"dbwState","U16","","low byte 0 OFF 1 INIT 2 RUN 3 FAULT; bit 8 the "
                             "EGENFR bridge enable as commanded; bit 9 the "
                             "direction leg"),
    (402,"dbwFaults","U16","","latched: 1 calibration, 2 pedal pair, "
                              "4 throttle pair, 8 pedal out of range, "
                              "16 throttle out of range, 32 bridge fault pin, "
                              "64 off target too long, 128 no backing sensor, "
                              "256 outputs not live. Only init() clears it"),
    (404,"dbwPedalX10","U16","%","normalised driver demand, 0.1 % of travel"),
    (406,"dbwTargetX10","U16","%","the rate-limited throttle target"),
    (408,"dbwActualX10","U16","%","the plate, from TPS track 1"),
    (410,"dbwErrorX10","S16","%","target - actual, AFTER the deadband"),
    (412,"dbwDutyX10","U16","%","what was asked of the H-bridge"),
    (414,"dbwInteg","S16","","the integrator. Watch it for windup while "
                            "tuning; it is zeroed whenever the bridge is "
                            "not driving"),
    (416,"dbwApp1X10","U16","%","pedal track 1, normalised"),
    (418,"dbwApp2X10","U16","%","pedal track 2, normalised"),
    (420,"dbwTps1X10","U16","%","throttle track 1, normalised"),
    (422,"dbwTps2X10","U16","%","throttle track 2, normalised"),
    (424,"dbwSteps","U16","","control steps executed, ever. It must climb at "
                            "about 200/s; a frozen count means the raster is "
                            "not running"),
    (426,"dbwSfLevel","U16","","the raw S8100 SF pin, whatever the configured "
                              "polarity. Measure the polarity with this"),
    (428,"mainRelayLife","U16","","low byte 0 INIT 1 REQUEST 2 RUNNING "
                                  "3 SHUTDOWN 4 RELEASED 5 FAULT; high byte "
                                  "the CONFIGURED connector cavity, 255 = "
                                  "unassigned"),
    (430,"nvmState","U16","","NON-VOLATILE CALIBRATION. Low byte is the state: "
                             "0 IDLE (page matches what was last burned), "
                             "1 NOT BURNED (edited since), 2 BURN PENDING "
                             "(requested; waiting for RPM 0 and a safe ECU), "
                             "3 ARMED (the commit reset is imminent), "
                             "4 COMMITTING, 5 BURNED (in flash and verified), "
                             "6 BURN FAILED (the PREVIOUS record still "
                             "stands), 7 STAGING (building the record, a "
                             "chunk per pass - it never survives a reset). "
                             "High byte is the commit phase: "
                             "0 none 1 program 2 commit (no runtime erase)"),
    (432,"nvmError","U16","","Low byte: 0 none, 1 SRAM unusable, 2 the "
                             "configuration would not validate, 3 the staged "
                             "record did not verify, 4 retired erase error, "
                             "5 a word would not program, 6 it did not "
                             "read back, 7 too many interrupted attempts, "
                             "8 a record written by a DIFFERENT page layout, "
                             "9 append-only store full. "
                             "High byte: which slot is active, 0 none 1 A 2 B"),
    (434,"nvmSource","U16","","Low byte: where THIS boot's calibration came "
                              "from - 0 compiled defaults, 1 the "
                              "battery-backed page, 2 flash slot A, 3 flash "
                              "slot B. High byte is the persistence class: "
                              "0 nothing survives a reset, 1 STANDBY (survives "
                              "a reset and the key, NOT a disconnected "
                              "battery), 2 NON-VOLATILE"),
    (436,"nvmGeneration","U16","","low word of the active flash record's "
                                  "generation counter; it increments once per "
                                  "committed burn"),
    (438,"nvmCommits","U16","","successful flash commits since this ECU last "
                               "lost standby power"),
    (440,"nvmAttempts","U16","","attempt count for the current program-only "
                                "commit. A partially programmed cell is never "
                                "retried; a later Burn uses the next blank cell"),
    (442,"veLoadX10","U16","","THE LOAD THE VE LOOKUP ACTUALLY USED - TPS or "
                              "MAP, whichever CAL_LOAD_SOURCE selects, in the "
                              "same 0.1 units as the fuel load axis. It exists "
                              "so the VE table's cursor lands on the cell the "
                              "firmware really read, in either load mode"),
    (444,"ramProbe","U16","","THE EXTERNAL-SRAM EXECUTION PROBE. Low byte: "
                             "0 never run, 1 RUNNING (it was called and has "
                             "not come back - if you can read this after a "
                             "reset, this board CANNOT execute from 0x386000 "
                             "and the flash writer must not be used), 2 PASS, "
                             "3 returned but computed the wrong answer, "
                             "4 returned without its signature, 5 the SRAM is "
                             "unusable, 6 refused because the engine could be "
                             "turning. High byte: probes attempted"),
    (446,"ramProbeSeed","U16","","the seed the last probe used. It is mixed "
                                 "from a host byte and the tick, so a stale or "
                                 "hardcoded answer cannot pass"),
    (448,"ramProbeResult","U16","","what the routine running in external SRAM "
                                   "computed from that seed"),
    (450,"grabResult","U16","","THE ENDPOINT GRAB'S VERDICT. Low byte: 0 never "
                               "asked, 1 PASS, 2 the engine is not "
                               "demonstrably stopped, 3 this board cannot read "
                               "one of the pair, 4 a raw count is at a rail - "
                               "an open input reads a clean, stable, wrong "
                               "number, 5 the two ends are too close together "
                               "(check the wiring), 6 no such endpoint, 7 PASS "
                               "- both tracks in the page, correlation SAME "
                               "(V90). High "
                               "byte: which endpoint was asked for"),
    (452,"grabCount","U16","","grabs attempted since power-up"),
    # V86: THE ENGINE PRESET APPLY ('!E'), owned by hcmain_me711.c
    # hc_preset_cmd_service() - see the table above it there.
    (764,"presetResult","U16","","ENGINE PRESET APPLY verdict. Low byte "
                                 "PRESET_V_* (hcPresetList), high byte the "
                                 "preset id that was asked for"),
    (766,"presetFaults","U16","","hc_validate() mask of the page the last "
                                 "preset would have produced; 0 = clean. "
                                 "A refused preset changed NOTHING"),
    (768,"presetBadOffset","U16","","page offset of the first field that "
                                    "refused the last preset (0 = none)"),
    (770,"presetPageRefresh","U16","","1 for 2.5 s after a preset applied: "
                                      "[EventTriggers] makes TunerStudio "
                                      "re-read the page (rusEFI's "
                                      "triggerPageRefreshFlag)"),
    (772,"presetPending","U16","","0x0100 | id while an apply request waits "
                                  "for the main loop, else 0"),
    (774,"presetAtMs","U16","ms","tick of the last successful preset apply"),
    # V90: 776..779, the 4 bytes TGT_OCH_SIZE grew by.
    (776,"etbCalStatus","U16","","ETB ENDPOINT CALIBRATION ('!C1') / PID "
                                 "AUTOTUNE ('!C2'): bits 0..3 result "
                                 "(hcEtbCalList), bits 4..7 phase, bits 8..15 "
                                 "the reason it stopped (V93 layout)"),
    (778,"schedOverdwell","U16","","coils the hard maximum-dwell watch had to "
                                   "release (1.5 x dwell, 4..20 ms). 0 is right: "
                                   "anything else means a spark event went "
                                   "missing"),
    (782,"schedOverdwellLatch","U16","","V91: bit per coil the maximum-dwell "
                                        "watch released and now holds OFF until "
                                        "the next sync loss / engine stop. 0 is "
                                        "right"),
    # V92: 784..807, the 24 bytes TGT_OCH_SIZE grew by.
    (784,"toothLogState","U16","","TOOTH PROFILE TEST ('!K'): low byte "
                                  "hcToothLogList, high byte the mode (1 "
                                  "compression - spark and fuel held off, 2 "
                                  "running). The 60-bin profile is in the "
                                  "extended window, read by the vehicle logger"),
    (786,"toothLogRevs","U16","","synchronised revolutions in the profile"),
    (788,"toothLogTeeth","U16","","tooth periods summed into the profile"),
    (790,"toothCorrections","U16","","reference marks accepted with a +/-1 "
                                     "tooth correction instead of a crank sync "
                                     "loss (Bosch Zahnkorrektur). Also in "
                                     "syncCorrections. A second one in a row "
                                     "IS a loss"),
    (792,"cycleSyncAcquired","U16","","times the 720-degree phase became known "
                                      "(syncState 3 -> 4)"),
    (794,"cycleSyncLost","U16","","times the 720-degree phase was withdrawn "
                                  "(4 -> 3). The crank position is KEPT - a cam "
                                  "can never cause a crank sync loss (V92)"),
    (796,"camPhaseNoAlt","U16","","cam-level checks that did NOT alternate "
                                  "from the previous revolution (Bosch "
                                  "B_siph). Rising = wrong check angle, wrong "
                                  "wheel or a dead cam"),
    (798,"camPhaseStatus","U16","","bit 0 last cam level at the check tooth, "
                                   "bit 1 it matched the half the decoder "
                                   "believes, bit 2 it alternated, bit 3 "
                                   "checked since sync; bits 8..15 consistent "
                                   "checks in a row"),
    (800,"camLowWidthX10","U16","deg","last cam pin-LOW sector, 0.1 crank deg "
                                      "(LEVEL method, both edges captured; "
                                      "quantised to the last tooth)"),
    (802,"camHighWidthX10","U16","deg","last cam pin-HIGH sector, 0.1 crank deg"),
    (804,"camPhaseCorrections","U16","","times the cam moved the guessed half "
                                        "by 360 deg (a correction - no position "
                                        "was lost)"),
    (806,"etbCalRest1","U16","","ETB calibration: TPS1 raw at rest (limp) "
                                "before driving"),
    (808,"etbCalA1","U16","","ETB calibration: TPS1 raw at end A (read after "
                             "the stop test)"),
    (810,"etbCalB1","U16","","ETB calibration: TPS1 raw at end B"),
    (812,"etbCalA2","U16","","ETB calibration: TPS2 raw at end A"),
    (814,"etbCalB2","U16","","ETB calibration: TPS2 raw at end B"),
    (816,"etbCalRest2","U16","","ETB calibration: TPS2 raw at rest"),
    (818,"etbTuneAmpX10","U16","%","ETB autotune: FINAL relay amplitude of "
                                   "the plate (mean of 16 cycles), 0.1 %"),
    (820,"etbTuneTuMs","U16","ms","ETB autotune: FINAL oscillation period "
                                  "(mean of 16 cycles, ultimate period Tu)"),
    # V93: 822..839 - what the procedure is doing NOW (hcetbcal.c ETBV_*).
    (822,"etbCalDetail","U16","","ETB: the number behind the result - counts "
                                 "the plate moved under the stop test, the "
                                 "failing span/position/amplitude, 0 = none"),
    (824,"etbTuneCycles","U16","","ETB autotune: relay cycles completed (8 "
                                  "warm-up + 16 measured)"),
    (826,"etbTuneKp","U16","","ETB autotune: candidate Kp from the last cycle, "
                              "then the FINAL value written to RAM (page "
                              "units, dbwKp)"),
    (828,"etbTuneKi","U16","","ETB autotune: candidate / final Ki (dbwKi units)"),
    (830,"etbTuneKd","U16","","ETB autotune: candidate / final Kd (dbwKd units)"),
    (832,"etbTuneAmpLiveX10","U16","%","ETB autotune: last cycle's plate "
                                       "amplitude, 0.1 %"),
    (834,"etbTuneTuLiveMs","U16","ms","ETB autotune: last cycle's period"),
    (836,"etbDrive","U16","","ETB procedure drive: bit 15 bridge driven, bit 14 "
                             "direction leg, bits 0..9 duty 0.1 %"),
    (838,"etbPhaseMs","U16","ms","ETB procedure: time in the current phase"),
    (840,"etbProc","U16","","ETB procedure: bits 0..3 which (hcEtbProcList), "
                            "4..7 the phase it FAILED in, bit 8 endpoints "
                            "passed in this run (handed to RAM), bit 9 the "
                            "operator aborted"),
    (842,"linkState","U16","","serial link: bits 0..1 rate (0 57600, 1 115200, "
                              "2 124800, 3 other = 10400 KWP), bit 4 locked "
                              "on a CRC-valid request, bits 8..15 rate "
                              "changes since boot"),
    (844,"kwpState","U16","","KWP vehicle entry: bits 0..3 KWP state (0 idle, "
                             "1..5 handshake, 6 session, 7 handed to "
                             "TunerStudio), 4..6 5-baud decoder stage, 8..15 "
                             "good inits"),
    (846,"kwpCounts","U16","","KWP: bits 8..15 failed inits, 0..7 5-baud "
                              "addresses that were not ours"),
    (848,"linkDiag","U16","","link diagnosis (V95): bits 0..7 rate-evidence "
                             "events (framing error, bad CRC, a byte no "
                             "request starts with; one per burst), 8..15 KWP "
                             "sessions ended by a run of bad frames"),
    (850,"lam1RiX10","U16","ohm","V96 bank 1 LSU Ri from the CJ120 UR against "
                                 "the board's 82.5 ohm reference, 0.1 ohm; 0 "
                                 "= not measurable, 6000 = open / cold"),
    (852,"lam2RiX10","U16","ohm","V96 bank 2 LSU Ri, 0.1 ohm"),
    (854,"lam1UaZero","U16","","V96 bank 1 calibration: UA with LA = 1 (the "
                               "Ip = 0 point), raw; datasheet 291..322"),
    (856,"lam2UaZero","U16","","V96 bank 2 UA zero, raw"),
    (858,"lam1UrCal","U16","","V96 bank 1 calibration: UR with RA = 1 (the "
                              "82.5 ohm reference), raw"),
    (860,"lam2UrCal","U16","","V96 bank 2 UR reference, raw"),
    (862,"lamFault","U16","","V96 latched wideband fault, low byte bank 1, "
                             "high byte bank 2 (hcLamFaultList): 1 heater "
                             "short GND 2 heater open / no sensor 3 heater "
                             "short UB 4 IA/IP 5 UN 6 VM 7 chip 8 calibration "
                             "9 did not heat 10 overheat 11 underheat 12 no "
                             "Ri signal"),
    (864,"lam1UrRaw","U16","","V96 bank 1 UR live (ASIC AN12), raw; 65535 = "
                              "the ADC did not tag the slot"),
    (866,"lam2UrRaw","U16","","V96 bank 2 UR live (ASIC AN13), raw"),
    (868,"lamVeff","U16","","V96 heater effective voltage, 0.1 V: low byte "
                            "bank 1, high byte bank 2"),
    (870,"lamMode","U16","","V96 CJ120 INIT_REG1 requested: low byte chip 1, "
                            "high byte chip 2 (0x88 cold, 0xC8 pump on, 0x9C "
                            "calibration)"),
    (872,"lam1IpUa","S16","uA","V97 bank 1 LSU pump current, the RAW "
                               "measurement (+ lean, - rich): published once "
                               "the pump zero is calibrated, whether or not "
                               "lambda is valid - never a lambda"),
    (874,"lam2IpUa","S16","uA","V97 bank 2 LSU pump current, raw"),
    (876,"cam1Pat","U16","","V97 cam 1 PATTERN (camPhaseMode 2): low byte "
                            "the last edge (0 learning, 1 this half, 2 the "
                            "other half, 3 alive - cannot tell the half, 4 no "
                            "tooth matches, 5 a tooth outside the VVT "
                            "authority, 6 noise), high byte the tooth (255 "
                            "none)"),
    (878,"cam2Pat","U16","","V97 cam 2 PATTERN, as cam1Pat"),
    (880,"cam1DevX10","S16","deg","V97 cam 1 last identified tooth: measured "
                                  "minus nominal angle"),
    (882,"cam2DevX10","S16","deg","V97 cam 2 last identified tooth: measured "
                                  "minus nominal"),
    (884,"cam1VvtX10","S16","deg","V97 cam 1 tooth 0 measured minus nominal - "
                                  "the cam position a VVT controller closes on"),
    (886,"cam2VvtX10","S16","deg","V97 cam 2 tooth 0 measured minus nominal"),
    (888,"camPatErrors","U16","","V97 pattern errors (no tooth / outside the "
                                 "authority), low byte cam 1, high byte cam 2, "
                                 "saturating at 255"),
    (890,"camPatFixes","U16","","V97 bits 0-3 cam 1 half moves, 4-7 cam 1 "
                                "glitches removed + missing edges restored, "
                                "8-11 / 12-15 the same for cam 2 (saturating 15)"),
    (892,"boostTargetX10","U16","kPa","V97 boost target from the closed-loop "
                                      "target table, 0.1 kPa absolute"),
    (894,"boostState","U16","","V97 boost control: low byte 1 overboost cut, 2 "
                               "no valid pressure (valve 0), 4 disabled or "
                               "key-off, 8 below the rpm/TPS floor, 16 open "
                               "loop, 32 closed loop, 64 output saturated; "
                               "high byte 1 = the overboost FUEL cut is on"),
    (896,"boostPX10","S16","%","V97 boost closed loop P part, 0.1 %"),
    (898,"boostIX10","S16","%","V97 boost closed loop I part, 0.1 %"),
    (900,"boostDX10","S16","%","V97 boost closed loop D part (on the pressure), 0.1 %"),
    (902,"boostOpenX10","U16","%","V97 boost open-loop duty incl. CLT/IAT "
                                  "multipliers, 0.1 %"),
    (904,"boostCuts","U16","","V97 overboost cut events since power-up"),
    (906,"idleFloorX10","U16","%","V97 idle throttle floor (base by coolant + "
                                  "the rpm trim) the ETB demand never goes "
                                  "below; 0 = idle control off, 0.1 %"),
    (908,"idleTrimX10","S16","%","V97 idle rpm trim (P + held I), bounded by "
                                 "idleRangeX10, 0.1 %"),
    (910,"idleTargetRpm","U16","rpm","V97 idle target from the coolant curve"),
    (912,"idleState","U16","","V97 idle: 1 off, 2 engine stopped, 4 cranking "
                              "/ post-start wait, 8 pedal pressed (trim held), "
                              "16 above target + band (trim held), 32 closed "
                              "loop, +64 at the authority limit, 128 dashpot "
                              "after a release (trim held)"),
    (914,"dtcMil","U16","","V97 1 = the MIL is requested (an active trouble "
                           "code of the MIL class). No lamp is driven yet: "
                           "cavity 47 is unmeasured (docs/firmware/design/ME711_DTC.md)"),
    (916,"dtcActiveN","U16","","V97 trouble codes active now"),
    (918,"dtcStoredN","U16","","V97 trouble codes confirmed since the last "
                               "clear (history)"),
    (920,"dtcActive1","U16","","V97 first active code as decimal digits: "
                               "105 = P0105, 2135 = P2135; 0 = none"),
    (922,"dtcActive2","U16","","V97 second active code"),
    (924,"dtcActive3","U16","","V97 third active code"),
    (926,"dtcActive4","U16","","V97 fourth active code"),
    (928,"dtcStored1","U16","","V97 first stored code (history)"),
    (930,"dtcStored2","U16","","V97 second stored code"),
    (932,"dtcStored3","U16","","V97 third stored code"),
    (934,"dtcStored4","U16","","V97 fourth stored code"),
    (936,"dtcFfCode","U16","","V97 freeze frame: the FIRST code confirmed "
                              "since the clear"),
    (938,"dtcFfRpm","U16","rpm","V97 freeze frame: rpm"),
    (940,"dtcFfClt","U16","C","V97 freeze frame: coolant (control value)"),
    (942,"dtcFfMap","U16","kPa","V97 freeze frame: manifold pressure"),
    (944,"dtcFfTps","U16","%","V97 freeze frame: throttle"),
    (946,"limpCut","U16","","V97 engine protection fuel cut, bits: 1 coolant "
                            "rev limit, 2 throttle-fault rev limit, 4 oil "
                            "pressure, 8 injector duty, 16 flood clear"),
    (948,"injDutyX10","U16","%","V97 injector duty the fuel model requests, "
                                "0.1 %"),
    # V97: the DBW step's terms and the commissioning verify (950..973).
    (950,"dbwTermP","S16","%","DBW proportional term, duty %"),
    (952,"dbwTermD","S16","%","DBW derivative term, duty %"),
    (954,"dbwTermFf","S16","%","DBW feed-forward from the bias curve, duty %"),
    (956,"dbwOutRaw","S16","%","DBW P + I + D + feed-forward BEFORE battery "
                               "compensation and the duty limit"),
    (958,"dbwBattFactor","U16","","DBW battery compensation factor, 13.5 V / "
                                  "battery (1.000 = none)"),
    (960,"dbwPendFaults","U16","","DBW sensor faults being confirmed (same "
                                  "bits as dbwFaults); the output is HELD "
                                  "meanwhile"),
    (962,"dbwPendMs","U16","ms","how long they have been pending"),
    (964,"etbVfySettleMs","U16","ms","ETB commission verify: worst time to "
                                      "settle within 2 %"),
    (966,"etbVfyOverX10","U16","%","ETB commission verify: worst overshoot"),
    (968,"etbVfyErrX10","U16","%","ETB commission verify: worst steady "
                                   "error (mean of the last 100 ms)"),
    (970,"etbVfyStep","U16","","ETB commission verify: step reached 1..5, "
                               "+256 when all five passed"),
    (972,"dbwFaultClears","U16","","latched DBW faults cleared by a key-on "
                                    "or a valid calibration"),
    # V97: sequential with fallback (docs/ARCHITECTURE.md), fuel/cycle
    (974,"seqActive","U16","","1 = at least one cylinder is in TRUE sequential "
                             "(one whole pulse / one spark per cycle); 0 = the "
                             "fallback (two halves, wasted COP) or not sequential"),
    (976,"seqInjMask","U16","","injector outputs in sequential, bit per output"),
    (978,"seqSkips","U16","","fallback twin events dropped (ignition + fuel)"),
    (980,"seqEnters","U16","","per-cylinder switches fallback -> sequential"),
    (982,"seqLeaves","U16","","per-cylinder switches sequential -> fallback"),
    (984,"injWidthUs","U16","us","the last injection's own width incl. dead time"),
    (986,"injNoFree","U16","","injections refused: no event slot for the close"),
    (988,"injCycleUs","U16","us","injector open time per cylinder per CYCLE, "
                                 "before splitting and dead time"),
    (990,"injDeadUs","U16","us","injector dead time added to every pulse"),
    # V97: transient fuel (firmware/engine/hctrans.c) - pedal -> throttle -> air ->
    # this -> injector: a tip-in as a causal chain in one log
    (992,"transWantUs","U16","us","fuel per cycle the steady model wants "
                                  "including after-start (open time)"),
    (994,"transCorrUs","S16","us","the wall film's share: delivered - wanted "
                                  "(+ on a tip-in, - on a tip-out)"),
    (996,"wallFilmUs","U16","us","fuel on the port wall (open-time units)"),
    (998,"wallAlphaPm","U16","","wall film evaporating per cycle, per mille"),
    (1000,"afterStartPm","U16","","after-start extra now, per mille"),
    (1002,"transBaseUs","U16","us","fuel per cycle before after-start and film"),
    (1004,"celState","U16","","V97 check-engine lamp: bits 0..7 mode (0 off, "
                          "1 MIL on, 2 key-on test ON, 3 test gap), bit 8 lamp "
                          "command, bit 9 MIL requested, bit 10 the lamp stage "
                          "(cavity 47, ASIC P7.0) is enabled and routed"),
    (1008,"idleTimingX10","S16","deg","V97 closed-loop idle ignition timing "
                                       "(part of ignCorrX10); 0 outside idle"),
    # V97: KNOCK (hcknock711.c, OCH2 region at 1024..): the chain per
    # cylinder - window -> integrator -> reference -> level -> retard
    (1024,"knockState","U16","","knock: low byte mode (0 off 1 monitor 2 "
                         "active), high byte why the last window was not "
                         "taken (hcKnockWhyList)"),
    (1026,"knockWindows","U16","","knock windows armed (wrapping)"),
    (1028,"knockSamples","U16","","knock windows sampled (KI read)"),
    (1030,"knockLate","U16","","knock arm attempts with every opening "
                         "already past (window not taken)"),
    (1032,"knockStale","U16","","knock windows that never closed (sync lost) "
                         "- aborted"),
    (1034,"knockAdcFail","U16","","KI (AN15) conversions that did not "
                         "complete"),
    (1036,"knockLast","U16","","low byte the last window's cylinder "
                         "(0-based), high byte a calibration refusal "
                         "(hcknock_check code, 0 = none)"),
    (1038,"knockLastIkr","U16","cnt","the last window's integrator KI, raw"),
    (1040,"knockWinStartX10","U16","deg","window start after TDC in force"),
    (1042,"knockWinLenX10","U16","deg","window length in force"),
    (1044,"knockCodes","U16","","low byte CC195 band code on BF0..3, high "
                         "byte gain code on G0..G2"),
    (1046,"knockSelFault","U16","","bits 0..7 sensor-select code on "
                         "KSA1/KSA2, 8..11 sensor fault latched (bit per "
                         "sensor), 12..15 that sensor was too loud"),
    (1048,"knockCount","U16","","knocks detected, all cylinders (wrapping)"),
    (1050,"knockRetardX10","U16","deg","knock retard reaching the spark now "
                         "(the most any ignition slot has; 0 in monitor)"),
    (1052,"knockFlags","U16","","bits 0..7 cylinder at stop (retard at "
                         "maximum does not cure it), bit 8 last window "
                         "judged (rpm/load/coolant), bit 9 CC195 lines driven"),
    (1054,"knockIkr1","U16","cnt","cylinder 1: last integrator KI, raw"),
    (1056,"knockIkr2","U16","cnt","cylinder 2: last integrator KI, raw"),
    (1058,"knockIkr3","U16","cnt","cylinder 3: last integrator KI, raw"),
    (1060,"knockIkr4","U16","cnt","cylinder 4: last integrator KI, raw"),
    (1062,"knockIkr5","U16","cnt","cylinder 5: last integrator KI, raw"),
    (1064,"knockIkr6","U16","cnt","cylinder 6: last integrator KI, raw"),
    (1066,"knockIkr7","U16","cnt","cylinder 7: last integrator KI, raw"),
    (1068,"knockIkr8","U16","cnt","cylinder 8: last integrator KI, raw"),
    (1070,"knockRef1","U16","cnt","cylinder 1: learned quiet reference"),
    (1072,"knockRef2","U16","cnt","cylinder 2: learned quiet reference"),
    (1074,"knockRef3","U16","cnt","cylinder 3: learned quiet reference"),
    (1076,"knockRef4","U16","cnt","cylinder 4: learned quiet reference"),
    (1078,"knockRef5","U16","cnt","cylinder 5: learned quiet reference"),
    (1080,"knockRef6","U16","cnt","cylinder 6: learned quiet reference"),
    (1082,"knockRef7","U16","cnt","cylinder 7: learned quiet reference"),
    (1084,"knockRef8","U16","cnt","cylinder 8: learned quiet reference"),
    (1086,"knockLevel1","U08","","cylinder 1: last KI / reference"),
    (1087,"knockLevel2","U08","","cylinder 2: last KI / reference"),
    (1088,"knockLevel3","U08","","cylinder 3: last KI / reference"),
    (1089,"knockLevel4","U08","","cylinder 4: last KI / reference"),
    (1090,"knockLevel5","U08","","cylinder 5: last KI / reference"),
    (1091,"knockLevel6","U08","","cylinder 6: last KI / reference"),
    (1092,"knockLevel7","U08","","cylinder 7: last KI / reference"),
    (1093,"knockLevel8","U08","","cylinder 8: last KI / reference"),
    (1094,"knockRet1","U08","deg","cylinder 1: knock retard (strategy, before mode)"),
    (1095,"knockRet2","U08","deg","cylinder 2: knock retard (strategy, before mode)"),
    (1096,"knockRet3","U08","deg","cylinder 3: knock retard (strategy, before mode)"),
    (1097,"knockRet4","U08","deg","cylinder 4: knock retard (strategy, before mode)"),
    (1098,"knockRet5","U08","deg","cylinder 5: knock retard (strategy, before mode)"),
    (1099,"knockRet6","U08","deg","cylinder 6: knock retard (strategy, before mode)"),
    (1100,"knockRet7","U08","deg","cylinder 7: knock retard (strategy, before mode)"),
    (1101,"knockRet8","U08","deg","cylinder 8: knock retard (strategy, before mode)"),
    (1102,"knockCnt1","U08","","cylinder 1: knocks detected (saturating)"),
    (1103,"knockCnt2","U08","","cylinder 2: knocks detected (saturating)"),
    (1104,"knockCnt3","U08","","cylinder 3: knocks detected (saturating)"),
    (1105,"knockCnt4","U08","","cylinder 4: knocks detected (saturating)"),
    (1106,"knockCnt5","U08","","cylinder 5: knocks detected (saturating)"),
    (1107,"knockCnt6","U08","","cylinder 6: knocks detected (saturating)"),
    (1108,"knockCnt7","U08","","cylinder 7: knocks detected (saturating)"),
    (1109,"knockCnt8","U08","","cylinder 8: knocks detected (saturating)"),
    (1110,"knockWinUs","U16","us","the last window as the hardware ran "
                         "it (T7 between the MF edges)"),
    (1112,"vvt1Target","S16","deg","V97 cam 1 VVT target, advance"),
    (1114,"vvt1Pos","S16","deg","V97 cam 1 measured position, advance "
                         "(0 when not a measurement)"),
    (1116,"vvt1Err","S16","deg","V97 cam 1 control error"),
    (1118,"vvt1Duty","U16","%","V97 cam 1 solenoid duty"),
    (1120,"vvt1State","U16","","V97 cam 1: bits 0..7 core state (1 off, 2 "
                         "waiting rpm/CLT/delay, 4 no position, 8 on/off, 16 "
                         "closed loop, 32 saturated), bits 8..14 latched fault "
                         "(hcVvtFaultList), bit 15 the PWM unit runs"),
    (1122,"vvt2Target","S16","deg","V97 cam 2 VVT target, advance"),
    (1124,"vvt2Pos","S16","deg","V97 cam 2 measured position, advance "
                         "(0 when not a measurement)"),
    (1126,"vvt2Err","S16","deg","V97 cam 2 control error"),
    (1128,"vvt2Duty","U16","%","V97 cam 2 solenoid duty"),
    (1130,"vvt2State","U16","","V97 cam 2: bits 0..7 core state (1 off, 2 "
                         "waiting rpm/CLT/delay, 4 no position, 8 on/off, 16 "
                         "closed loop, 32 saturated), bits 8..14 latched fault "
                         "(hcVvtFaultList), bit 15 the PWM unit runs"),
    (1010,"lamWhy","U16","","V97 WHY each bank's lambda is not a "
                         "measurement (hcLamWhyList): low byte bank 1, high "
                         "byte bank 2; 0 = valid. Not latched - every row says "
                         "what withheld it"),
    (1012,"cjErr","U16","","V97 CJ120 exchanges refused (INIT_REG1 read-back "
                         "wrong, IDENT not a CJ120, no answer): low byte chip "
                         "1, high byte chip 2, saturated at 255"),
    (1014,"cjTmo","U16","","V97 CJ120 SSC exchanges that never completed "
                         "(bounded 64 us per byte): low byte chip 1, high "
                         "byte chip 2, saturated at 255; 0 on a healthy SSC"),
    (1016,"asicSampleAgeMs","U16","ms","Accepted ASIC transport snapshot age; 65535 unavailable. Does not certify internal peripheral ADC completion."),
    (1018,"tpsSampleAgeMs","U16","ms","Maximum age of the two independent TPS acquisitions; 65535 unavailable."),
    (1020,"lamAcqFlags","U16","","Last lambda step: bits 0/1 bank 1 UA/UR qualified, 2/3 bank 2 UA/UR qualified, 4/5 settling boundary passed, 6/7 chip verified. ASIC provenance remains transport-derived."),
    (1022,"lamAckModes","U16","","Acknowledged INIT_REG1: bank 1 low byte, bank 2 high byte; 0x88 sensor Ri with pump off, 0xC8 sensor Ri with pump on, 0x9C calibration reference."),
    (1006,"ignCorrX10","S16","deg","V97 CLT + IAT timing correction added to "
                                    "the table advance (advX10 is the result)"),
    (454,"nvmFailWord","U16","","THE PROGRAMMER'S DIARY. The record word index "
                                "that would not take, 65535 when none has. "
                                "The record is 2060 words: 0..8 header, "
                                "9..2056 the calibration page, 2057 its CRC, "
                                "2058..2059 the DONE marker"),
    (456,"nvmFailExp","U16","","the datum that word was given"),
    (458,"nvmFailGot","U16","","the FIRST read the poll gave up on. 65535 here "
                               "AND in nvmFailGot2 means the device was "
                               "answering with erased array data - it never "
                               "started. Anything else is status"),
    (460,"nvmFailGot2","U16","","the second read of that same address. It "
                                "differing from the first is DQ6 toggling, "
                                "which means an embedded algorithm was still "
                                "running"),
    (462,"nvmProgFlags","U16","","low byte: bit 0 the device itself reported a "
                                 "failure (DQ5), bit 1 two reads of one "
                                 "address disagreed, bit 2 a word read back "
                                 "right and then read back wrong, bit 3 the "
                                 "device was not settled at a chunk entry, "
                                 "bit 4 A RE-ISSUED COMMAND SEQUENCE DID TAKE, "
                                 "bit 5 every attempt on one word failed, "
                                 "bit 6 the retry target had an unexpected "
                                 "0 bit and was refused (never retried). "
                                 "High byte: the most attempts any one word "
                                 "needed"),
    (464,"nvmRetries","U16","","HOW OFTEN THIS HARDWARE REFUSED A PROGRAM "
                               "COMMAND during the last commit. 0 means the "
                               "device took every one of 2060 words first "
                               "time. This is the measurement two failed "
                               "bench Burns could not produce"),
    (466,"nvmPollMin","U16","","the SHORTEST word-program poll of the last "
                               "commit, in T7 ticks of 0.8 us. A normal word "
                               "is 11 us, about 14 ticks. Near ZERO would mean "
                               "the poll matches on status that happens to "
                               "look like the datum"),
    (468,"nvmPollMax","U16","","the longest, same units. The AM29F800BB's "
                               "final datasheet maximum is 500 us, 625 ticks"),
    (470,"nvmCommitStage","U16","","V45 retained current forensic stage"),
    (472,"nvmCommitLastStage","U16","","V45 retained highest forensic stage"),
    (474,"nvmCommitFailStage","U16","","V45 retained stage snapshot at terminal NVM failure"),
    # DERIVED, NEVER TYPED. This comment carried the literal "0x4439 (V49)"
    # through the V50 rename and me711_identity_proof caught it: an .ini that
    # documents a different build from the firmware it is paired with is the
    # same class of defect as the V29 image that called itself V28.
    (476,"releaseId","U16","","deterministic firmware release ID 0x%04X (%s),"
     " not a Git commit identifier"
     % (d(tgt, "TGT_RELEASE_ID"),
        next((w for w in VERSIONTXT.split() if re.fullmatch(r"V\d+", w)),
             "unversioned"))),
    (398,"powerNl","U16","","bit 0: this CPU is driving NLEN_FR (P3.12) HIGH. "
                            "bits 4 and 8: what the S5600 74ACT00 turns that "
                            "into at the CJ910's NL input for each of the "
                            "ASIC's two NLEN_AS states, 0 and 1. NL LOW is "
                            "run-on requested and needs BOTH processors"),
]

# V45 retained one-Burn reset forensics and the existing RESETDIAG_V2 log.
# All are U16 on the wire: byte fields are zero-extended by update_live().
CH += [
    (478,"bfVersionLength","U16","","retained record version high byte, length low byte"),
    (480,"bfSequence","U16","","retained record update sequence"),
    (482,"bfChecksum","U16","","retained record additive checksum"),
    (484,"bfFlags","U16","","V49 forensic lifecycle flags: armed/staged/NMI/recovered/durable/frozen/valid"),
    (486,"bfBootEpoch","U16","","battery-backed startup epoch"),
    (488,"bfBurnEpoch","U16","","B commands seen by retained record"),
    (490,"bfHctsInitCount","U16","","hcts_init calls since retained record creation"),
    (492,"bfHctsInitBootEpoch","U16","","boot epoch of latest hcts_init"),
    (494,"bfCfgBurnsBeforeInit","U16","","cfgBurns captured before hcts_init zeroed it"),
    (496,"bfCfgWritesBeforeInit","U16","","cfgWrites captured before hcts_init zeroed it"),
    (498,"bfRawResetCause","U16","","raw reset cause captured at earliest V45 startup point"),
    (500,"bfCurrentBootStage","U16","","current startup stage retained"),
    (502,"bfPreviousBootStage","U16","","previous startup stage frozen by RESETDIAG"),
    (504,"bfPreviousTrap","U16","","previous trap/vector low byte"),
    (506,"bfPreviousTrapMs","U16","ms","previous trap timestamp"),
    (508,"bfPreviousUptime","U16","ms","previous retained uptime"),
    (510,"bfPreviousLoop","U16","","previous retained main-loop count"),
    (512,"bfPreviousWdtServices","U16","","previous watchdog service count"),
    (514,"bfNvmState","U16","","NVM state snapshot"),
    (516,"bfNvmPhase","U16","","NVM phase snapshot"),
    (518,"bfNvmResult","U16","","control-block result snapshot"),
    (520,"bfNvmCell","U16","","target flash cell snapshot"),
    (522,"bfNvmPos","U16","","control-block word cursor snapshot"),
    (524,"bfNvmAttempts","U16","","control-block attempt count snapshot"),
    (526,"bfNvmError","U16","","control-block error snapshot"),
    (528,"bfWriterResult","U16","","result immediately after SRAM writer return"),
    (530,"bfNvmRetries","U16","","program command reissues snapshot"),
    (532,"bfFailWord","U16","","writer diary failing word"),
    (534,"bfFailExp","U16","","writer diary expected datum"),
    (536,"bfFailGot","U16","","writer diary first readback"),
    (538,"bfFailGot2","U16","","writer diary second readback"),
    (540,"bfPollMin","U16","tick","shortest writer poll, T7 ticks"),
    (542,"bfPollMax","U16","tick","longest writer poll, T7 ticks"),
    (544,"bfCurrentStage","U16","","V45 current forensic stage"),
    (546,"bfLastStage","U16","","V45 highest forensic stage"),
    (548,"bfFailStage","U16","","V45 last stage frozen at terminal NVM failure"),
    (550,"bfFailureReason","U16","","terminal NVM failure reason"),
    (552,"rstBootCount","U16","","existing RESETDIAG retained boot count"),
    (554,"rstRawReset","U16","","existing RESETDIAG current raw reset flags"),
    (556,"rstCurrentStage","U16","","existing RESETDIAG current boot stage"),
    (558,"rstPreviousStage","U16","","existing RESETDIAG previous boot stage"),
    (560,"rstPreviousUptime","U16","ms","existing RESETDIAG previous uptime"),
    (562,"rstPreviousLoop","U16","","existing RESETDIAG previous loop count"),
    (564,"rstPreviousFirstVector","U16","","existing RESETDIAG previous first vector"),
    (566,"rstPreviousLastVector","U16","","existing RESETDIAG previous last vector"),
    (568,"rstPreviousTrap","U16","","existing RESETDIAG previous trap/vector"),
    (570,"rstPreviousTrapMs","U16","ms","existing RESETDIAG previous trap timestamp"),
    (572,"rstPreviousWdtServices","U16","","existing RESETDIAG previous watchdog services"),
    (574,"rstPreviousMarker","U16","","existing RESETDIAG previous startup marker"),
    (576,"rstPreviousTarget0","U16","","previous ASIC context: state/reinits"),
    (578,"rstPreviousTarget1","U16","","previous ASIC context: TX/RX"),
    (580,"rstPreviousTarget2","U16","","previous ASIC context: SSC/vector"),
    (582,"rstPreviousTarget3","U16","","previous ASIC context: PEC endpoints"),
    (584,"rstPreviousTarget4","U16","","previous ASIC context: reply word 0"),
    (586,"rstCurrentTrap","U16","","existing RESETDIAG current trap/vector"),
    (588,"rstCurrentTrapMs","U16","ms","existing RESETDIAG current trap timestamp"),
    (590,"rstCurrentWdtServices","U16","","existing RESETDIAG current watchdog services"),
    (592,"rstCurrentMarker","U16","","existing RESETDIAG current startup marker"),
    (594,"rstCurrentTarget0","U16","","current ASIC context: state/reinits"),
    (596,"rstCurrentTarget1","U16","","current ASIC context: TX/RX"),
    (598,"rstCurrentTarget2","U16","","current ASIC context: SSC/vector"),
    (600,"rstCurrentTarget3","U16","","current ASIC context: PEC endpoints"),
    (602,"rstCurrentTarget4","U16","","current ASIC context: reply word 0"),
    (604,"bfMagicHi","U16","","V49 active forensic record magic word 0: 0x4843"),
    (606,"bfMagicLo","U16","","V49 active forensic record magic word 1: 0x4C46"),
    (608,"bfRecordPresent","U16","","1 when the V49 forensic header/version/length/valid flag agree"),
    (610,"outputPins","U16","","V75 CPU-port READBACK: 1 fuel pump pin driven active, 2 main relay pin driven active, 4 fuel pump output permitted, 8 main relay requested but refused permission. V77: 16/32/64 live level of the CC15/CC8/CC9 capture pins. V78: 128 KL15_STAT (P6.2). Not proof of the driver stage"),
    (612,"liveOwner","U16","","V49 owner: 0 none, 1 NVM word window"),
    (614,"liveAdmission","U16","","V49 admission: 1 ready, 2 engine, 3 ASIC, 4 PEC, 5 deadline"),
    (616,"livePauseReason","U16","","V49 pause/reject subreason"),
    (618,"liveWindowsOk","U16","","admitted one-word flash windows"),
    (620,"liveWindowsRejected","U16","","rejected one-word flash windows"),
    (622,"liveDeadlineMs","U16","ms","remaining standard-B deadline"),
    (624,"livePredictedMs","U16","ms","physical word-time prediction only"),
    (626,"liveHorizonUs","U16","us","current crank event horizon"),
    (628,"liveWriterEntries","U16","","SRAM writer entries"),
    (630,"liveWriterSuccess","U16","","verified SRAM writer words"),
    (632,"liveWriterFail","U16","","writer failures"),
    (634,"liveMask","U16","","IC source mask bitmap for last word"),
    (636,"livePendingBefore","U16","","IC pending bitmap before word"),
    (638,"livePendingAfter","U16","","IC pending bitmap after restore"),
    (640,"liveVectorViolations","U16","","must remain zero"),
    (642,"livePec0Remaining","U16","word","PEC0 terminal margin"),
    (644,"livePec4Remaining","U16","word","PEC4 terminal margin"),
    (646,"liveSscCon","U16","","SSC status/control"),
    (648,"liveAsicState","U16","","ASIC ownership state"),
    (650,"liveAsicAgeMs","U16","ms","age since last accepted ASIC frame"),
    (652,"liveRpm","U16","rpm","RPM at last qualification refresh"),
    (654,"liveWordsTotal","U16","word","record words total"),
    (656,"liveWordsCompleted","U16","word","record words completed"),
    (658,"liveWordsRemaining","U16","word","record words remaining"),
    (660,"liveCurrentWord","U16","word","current/last programmed word"),
    (662,"liveMaxPollTicks","U16","tick","maximum observed AM29 poll"),
    (664,"liveAsicDenied","U16","","ASIC ownership denials"),
    (666,"liveAsicOverdue","U16","","ASIC runtime timeout count"),
    (668,"liveSscErrors","U16","","SSC error-vector count"),
    (670,"liveWriterFlags","U16","","writer DQ/settle/retry flags"),
    (672,"liveAttempts","U16","","current commit attempts"),
    (674,"liveGeneration","U16","","active generation"),
    (676,"liveCommits","U16","","successful commits"),
    (678,"liveBurnError","U16","","terminal burn error"),
    # ---- V53, the reclaim ------------------------------------------------
    (680,"nvmFreeCells","U16","","blank cells the last store scan found, of "
                                 "nvmCellsTotal. The reclaim starts when this "
                                 "falls to one sector's worth, so it is never "
                                 "on a Burn's critical path"),
    (682,"nvmCellsTotal","U16","","cells in the append-only store"),
    (684,"nvmEraseState","U16","","Low byte: 0 idle, 1 RUNNING (a sector is "
                                  "suspended mid-erase), 2 done, 3 failed. "
                                  "High byte: the store sector being erased, "
                                  "255 for none"),
    (686,"nvmEraseSlices","U16","","suspend/resume cycles spent on the erase "
                                   "in progress. THE NUMBER TO WATCH: the "
                                   "datasheet bounds the suspend latency but "
                                   "not the resume-to-suspend interval, so if "
                                   "a sliced erase cannot converge on this "
                                   "part, this climbs and nvmReclaims never "
                                   "moves"),
    (688,"nvmEraseMs","U16","","wall time the last COMPLETED reclaim took, ms"),
    (690,"nvmReclaims","U16","","sectors successfully reclaimed since this ECU "
                                "last lost standby power"),
    (692,"nvmEraseFails","U16","","reclaims abandoned - bounded rather than "
                                  "retried forever. The store keeps using the "
                                  "cells it still has"),
    (694,"nvmEraseTries","U16","","Low byte: attempts on the sector being "
                                  "reclaimed. High byte: how many sectors hold "
                                  "something the scan refused"),

    # ---- V55, the decoder's own idea of the wheel -------------------------
    # 696..721, the 26 bytes TGT_OCH_SIZE was grown by. These are READBACK of
    # configuration, not state, and that is exactly why they are worth the
    # block: a bench that can only see syncState cannot tell a wrong signal
    # from a wrong page. Before V55 there was nothing to read back - the
    # geometry was three #defines inside hctrig_me711.c.
    (696,"trigCfgTeeth","U16","","teeth on a complete wheel, AS THE DECODER "
                                 "RESOLVED IT. Disagreeing with syTeeth means "
                                 "the page failed a range check and the "
                                 "decoder fell back"),
    (698,"trigCfgGap","U16","","missing teeth in force"),
    (700,"trigCfgRatio","U16","","gap detection ratio in force, x10. Derived "
                                 "from the geometry when the page's value "
                                 "cannot work on this wheel: a 36-1 gap is "
                                 "2.0 tooth periods exactly, so a 2.0 ratio "
                                 "never fires"),
    (702,"trigCfgMinTeeth","U16","","good teeth required before crank sync"),
    (704,"trigCfgToothX10","U16","deg","one tooth, 0.1 crank degrees"),
    (706,"trigCfgAngleX10","S16","deg","V97: the trigger angle IN FORCE - tooth #1 "
                                     "(the edge ending the gap) in deg after "
                                     "cylinder-1 TDC, negative = before TDC"),
    (708,"trigCfgCamRefs","U16","","cam reference edges per 720 degrees"),
    (710,"trigCfgCamRefX10","U16","deg","first cam reference, 0.1 deg. 65535 "
                                       "when no cam geometry is configured"),
    (712,"trigCfgCamWindowX10","U16","deg","cam acceptance half-window"),
    (714,"trigCfgCrankEdge","U16","","0 falling, 1 rising - what CC15 is "
                                     "actually programmed for"),
    (716,"trigCfgCamEdge","U16","","0 falling, 1 rising - CC8 and CC9"),
    (718,"trigCamResolves","U16","","1 = the configured cam geometry can "
                                    "decide WHICH revolution this is, so "
                                    "syncState may reach 4. An EVEN number of "
                                    "equally spaced references cannot: the "
                                    "pattern repeats every 360 degrees. Zero "
                                    "here with a live cam is not a fault"),
    (722,"trigCfgCaptureMap","U16","","WHICH CAPTURE CHANNEL ENDED UP DOING "
                                      "WHAT - three nibbles low to high: "
                                      "CC15, CC8, CC9; 0 unused, 1 crank, "
                                      "2 cam1, 3 cam2. The Porsche default "
                                      "resolves to 0x0321. This is how a "
                                      "bench tells 'the page says cavity 86' "
                                      "from 'the hardware captures cavity 86'"),
    # V63 - THE OUTPUT CENSUS, because hc_hal_out() now moves a pin as well as
    # counting. A bench needs to tell "the scheduler asked for coil 3" from
    # "coil 3 moved", and these are the asking half.
    (724,"ignOnMask","U16","","bit i = coil i+1 is commanded ON right now. "
     "The SCHEDULER's request, not a measurement of the pin - a coil whose "
     "cavity is unrouted, or whose class is inhibited, shows here and moves "
     "nothing"),
    (726,"injOnMask","U16","","bit i = injector i+1 is commanded ON right now. "
     "Same meaning as ignOnMask"),
    (728,"outDriveCalls","U16","","hc_hal_out/out_duty calls since boot. Zero "
     "with an engine turning means nothing is asking, which is a different "
     "fault from asking and not reaching the pin"),
    # V65 - THE TWO NUMBERS A SIMULATOR CANNOT SUPPLY.
    (730,"stackPeak","U16","bytes","deepest the 256-byte USER stack has been, "
     "measured by the firmware itself from where its 0x5A5A fill stops. The "
     "simulator says 176 on a workload that runs no trigger, injection or "
     "ignition path; THIS is the real engine's answer. 256 means it reached "
     "the bottom and the next push lands on the SYSTEM stack's interrupt "
     "return addresses - see hcsafety.h"),
    (732,"lkgSteps","U16","","generations the boot had to walk BACK through "
     "before finding a stored calibration that validates. 0 is the ordinary "
     "case. Anything else means a newer burn is intact but describes an ECU "
     "that cannot run, and an older one is being used instead"),
    (720,"trigCfgGeneration","U16","","times the decoder re-read the geometry "
                                      "at RPM zero. THE CHANNEL A BENCH "
                                      "PROCEDURE WATCHES: an edit that has "
                                      "not reached the decoder is a number "
                                      "that did not move"),
    # V79 - hcio711.c writes these straight into the block.
    (734,"lambda1X1000","U16","lambda","bank 1 wideband (CJ120 #1, AN6). 0 = NOT VALID - the valid bit says why"),
    (736,"lambda2X1000","U16","lambda","bank 2 wideband (CJ120 #2, AN4). 0 = NOT VALID"),
    (738,"lambdaStatus","U16","","V96: bit0/1 lambda1/2 valid; bits2-4/5-7 heater1/2 state (0 off 1 wait 2 preheat 3 ramp 4 closed loop 5 ready 6 fault); bit8/9 CJ120 1/2 verified (IDENT + mode); bit10/11 bank 1/2 READY; bit12/13 pump current ON (PA verified); bit14/15 calibration OK (pump zero + Ri reference)"),
    (740,"cj120Diag","U16","","CJ120 DIAG register, low byte chip 1, high byte chip 2. 0xFF = no failure"),
    (742,"cj120Ident","U16","","CJ120 IDENT register, low byte chip 1, high byte chip 2"),
    (744,"heaterDuty","U16","%","lambda heater duty, low byte bank 1, high byte bank 2, percent"),
    (746,"boostReqX10","U16","%","N75 duty REQUESTED by boost control (open or closed loop), 0.1 %"),
    (748,"asicOutMask","U16","","ASIC outputs ON in the last frame: bit0 N75/LDR 1 EVAP 2..5 heaters; bit6 N75 commanded; bit7 bench test running; bit15 NLEN_AS image"),
    (750,"runOn","U16","","low byte run-on state (0 RUN 1 HOLD 2 RELEASED 3 TIMEOUT 4 not configured); high byte flags (1 key-off, 2 run-on asserted)"),
    (752,"runOnMs","U16","ms","time since KL15 dropped"),
    (754,"asicImgP7P8","U16","","runtime TX word 58 as sent: the ASIC's P7 (low) / P8 (high) image; a CLEAR bit is a stage ON"),
    (756,"cj120Xfers","U16","","CJ120 SSC transactions performed"),
    (758,"boostCmdX10","U16","%","N75 duty COMMANDED to the ASIC LDR stage after permission, 0.1 %"),
    (760,"cj120Reg1","U16","","INIT_REG1 acknowledged, low byte bank 1, high byte bank 2: 0x88 COLD, 0x9C CAL, 0xC8 PUMP; a requested mode is not a fresh sample"),
    (762,"runOnCount","U16","","key-off events seen since boot"),
]

# ======================== V98: THE FAST BLOCK + THE ENGINE-CONTROL STATE ===
# hcengctl711.c hc_ec_publish(). 1136..1199 is the TUNING CORE, contiguous so
# a TunerStudio datalog / dashboard is ONE K-line read
# (docs/TUNERSTUDIO.md.4 phase 2); the names are the plain
# ones (ts_gauges_me711 files the older copies at their historical offsets
# under Developer / Raw block).
CH += [
    (1134, "cfgFirstBadSlot", "U16", "", "V98r2: the first refused field as its slot index (hcCfgFieldList), 65535 = none"),
    (1132, "switchRaw", "U16", "", "V98r2: raw level of each switch input, bit i = hw_descriptors.SWITCH_INPUTS order (86 87 38 39 40 55 56 57 75 76) reads HIGH; bit 15 = an input is unreadable (ASIC link down)"),
    (1136, "RPMValue", "U16", "rpm", "engine speed"),
    (1138, "MAPValue", "U16", "kPa", "pressure AS MEASURED (0 = sensor fault)"),
    (1140, "TPSValue", "U16", "%", "throttle position, track 1"),
    (1142, "pedalPosition", "U16", "%", "pedal (the ETB's normalised demand with DBW on)"),
    (1144, "coolant", "U16", "C", "coolant AS MEASURED (-40 C = sensor fault)"),
    (1146, "intake", "U16", "C", "intake air AS MEASURED (-40 C = sensor fault)"),
    (1148, "VBatt", "U16", "V", "battery"),
    (1150, "fuelLoad", "U16", "", "the VE table's load: MAP kPa (speed density) or throttle % (alpha-N)"),
    (1152, "lambdaValue", "U16", "lambda", "measured lambda bank 1; 0 = not a measurement"),
    (1154, "targetLambda", "U16", "lambda", "target lambda"),
    (1156, "stftBank1", "S16", "%", "closed-loop fuel trim bank 1 (+ = adding fuel)"),
    (1158, "injectorPulseWidth", "U16", "ms", "injector pulse width incl. dead time"),
    (1160, "veValue", "U16", "%", "VE looked up"),
    (1162, "ignitionTiming", "S16", "deg", "commanded timing, BTDC (negative = ATDC)"),
    (1164, "coilDwell", "U16", "ms", "dwell"),
    (1166, "engineFlags", "U16", "", "1 running 2 cranking 4 after-start 8 warm-up 16 transient (AE / wall film) 32 DFCO 64 lambda 1 valid 128 lambda 2 valid 256 closed loop correcting 512 any fuel cut 1024 launch 2048 flat shift 4096 anti-lag 8192 rev limit 16384 MAP estimate in use 32768 VE table being written"),
    (1168, "warmupEnrich", "U16", "%", "warm-up enrichment (100 = none)"),
    (1170, "aeFuelUs", "U16", "us", "TPS acceleration enrichment shot"),
    (1172, "knockRetardMax", "U16", "deg", "the largest knock retard any cylinder carries"),
    (1174, "etbTarget", "U16", "%", "electronic throttle target"),
    (1176, "etbActual", "U16", "%", "electronic throttle position"),
    (1178, "idleTarget", "U16", "rpm", "idle target"),
    (1180, "boostTarget", "U16", "kPa", "boost target (closed loop table)"),
    (1182, "boostDuty", "U16", "%", "boost solenoid duty requested"),
    (1184, "fuelCutFlags", "U16", "", "1 DFCO 2 rev limit 4 overboost 8 engine protection"),
    (1186, "sensorFlags", "U16", "", "sensor fault bits (as sensorErr)"),
    (1188, "syncSeq", "U16", "", "low byte sync state (4 = phase known), high byte 1 = sequential active"),
    (1190, "airMass", "U16", "mg", "cylinder air mass"),
    (1192, "lambda2Value", "U16", "lambda", "measured lambda bank 2; 0 = not a measurement"),
    (1194, "mapControl", "U16", "kPa", "the pressure the FUEL uses: measured, or the MAP estimate on a sensor fault"),
    (1196, "ignCorrection", "S16", "deg", "CLT + IAT + idle timing correction"),
    (1198, "injectorDuty", "U16", "%", "injector duty"),
    (1200, "stftState", "U16", "", "low byte closed-loop state (hcStftList), high byte region 0 idle 1 overrun 2 power 3 cruise"),
    (1202, "stftBank2", "S16", "%", "closed-loop fuel trim bank 2"),
    (1204, "motorsportState", "U16", "", "bits 0..7 spark cut ratio /255, 8..9 launch (1 pre, 2 launch), 10 rotational idle, 11 pit limiter, 12..15 switch inputs active (launch, flat shift, anti-lag, pit)"),
    (1206, "revLimitNow", "U16", "rpm", "the hard rev limit in force (pit limiter included)"),
    (1208, "ignTableTiming", "S16", "deg", "the ignition table (or cranking) timing before corrections"),
    (1210, "targetAfr", "U16", "AFR", "target AFR = target lambda x stoichiometric ratio"),
    (1212, "primeState", "U16", "", "priming: low byte 0 waiting 1 done 2 pulse open, high byte key cycles since the engine ran"),
    (1214, "injPhase", "U16", "deg", "injection angle in force (degrees before the cylinder's TDC)"),
    (1216, "fuelCorrection", "U16", "%", "fuel multiplier from closed loop, soft limit, launch, anti-lag (100 = none)"),
    (1218, "ignLoad", "U16", "", "the ignition table's load"),
    (1220, "lambdaLoad", "U16", "", "the target lambda table's load"),
    (1222, "toothLogStatus", "U16", "", "tooth logger: bit 0 buffer ready, bits 1..2 mode (1 composite, 2 tooth), high byte records / 8"),
    # V99: the vehicle-test telemetry (hcevlog711.c och_set) - WHY the ETB
    # stop test decided what it did, the lambda dynamics, the event ring
    (1224, "etbHold1", "U16", "cnt", "TPS1 raw 40 ms mean at bounded capture; does not certify physical stop contact"),
    (1226, "etbPush1", "U16", "ms", "Captured TPS1 age; frozen at calibration failure"),
    (1228, "etbStopLimit", "U16", "ms", "Captured TPS2 age; frozen at calibration failure"),
    (1230, "etbStopMoved", "S16", "", "TPS qualification nibbles: 0 OK, 1 no source, 2 never, 3 stale, 4 rejected"),
    (1232, "etbHoldMs", "U16", "ms", "Actual bounded capture duration, clamped 300..1500 ms"),
    (1234, "etbStopDisp", "U16", "cnt", "TPS1 distance from spring rest at capture"),
    (1236, "lamDyn", "U16", "", "Passive activity only: bit 0/1 bank 1/2 variation observed, bit 2/3 sustained low variation, bit 4/5 watched; high byte bank 1 UA span of last 5 s window. Does not gate validity or trim and cannot certify sensor response."),
    (1238, "lamSpan2", "U16", "cnt", "V99 bank 2 UA span of the last 5 s window"),
    (1240, "sparkSkips", "U16", "", "V99 sparks skipped by a cut ratio (rev limiter spark cut, launch, flat shift, anti-lag, rotational idle)"),
    (1242, "evSeq", "U16", "", "V99 the event ring's next sequence number (records are read by the vehicle test tool)"),
    (1244, "ecuMs", "U16", "ms", "V99 the ECU uptime clock (wraps at 65.5 s) - the time base of the event ring records"),
    (1246, "evRingSize", "U16", "", "V99 records in the event ring"),
]

ADC_NAMES = ["HFM", "TPS1", "IPV", "TPS2", "LS2VK", "UBAT", "LS1VK",
             "LS1HK", "PEDAL1", "PEDAL2", "LS2HK", "AUX11", "DMTL", "HFM2",
             "DSS", "KNOCK"]
# V102: separate event intentions, queue admission and commanded GPIO edges.
for _i,_n in enumerate(["dlPlannedDwell","dlPlannedSpark","dlPlannedOpen","dlPlannedClose","dlExecutedDwell","dlExecutedSpark","dlExecutedOpen","dlExecutedClose","dlArmed","dlSuppressed","dlCancelled","dlClipped","dlRejected","dlLate","dlMaxLateTicks","dlReason","dlRequestedTick","dlCompareTick","dlCommandTick"]):
    CH.append((1248+2*_i,_n,"U16","ticks" if _i>=14 and _i!=15 else "","CC25 command telemetry; ticks are 0.8 us. Internal timestamps are not physical trace measurements."))
for _b in range(8):
    for _i,_n in enumerate(["FuelUs","DeadUs","RequestedUs","ScheduledUs","DeliveredUs","Owner","Flags"]):
        CH.append((1286+14*_b+2*_i,"inj%d%s"%(_b+1,_n),"U16","us" if _i<5 else "","Last request/admission/command interval for this channel. Flags: 1 ON, 2 clipped, 4 truncated, 8 OFF guard, 16 requested overflow, 32 last request refused. Owner is a ticket, not cylinder phase."))
# hcload711.c hc_load_publish(): the fuel model's state, 25 words, in order.
_LOAD_UNITS = {"pressureMeasured": "kPa", "pressureAge": "ms",
               "ambientUsed": "kPa", "ambientAgeSeconds": "s",
               "densityPressure": "kPa", "densityTemperature": "K",
               "loadSampleMs": "ms", "loadElapsedMs": "ms",
               "ambientStoppedMs": "ms", "ambientRemainderMs": "ms",
               "leanPersistMs": "ms", "leanRecoveryMs": "ms",
               "leanMeasurement": "lambda"}
for _i,_n in enumerate(["loadModelNow","pressureRoleNow","densityPolicyNow","pressureMeasured","pressureAge","pressureValid","ambientUsed","ambientProvenance","ambientValid","ambientAgeSeconds","densityPressure","densityRatio","chargeBlendWeight","densityTemperature","veAxisInput","loadFlags","loadSampleMs","loadElapsedMs","ambientStoppedMs","ambientRemainderMs","leanPersistMs","leanRecoveryMs","leanLatched","leanEligible","leanMeasurement"]):
    CH.append((1398+2*_i,_n,"U16",_LOAD_UNITS.get(_n,""),"Fuel model state: ambient source in use 0 reference / 1 engine-stopped reading / 2 onboard sensor; flags 1 invalid model 2 pressure lost 4 ambient fallback 8 IAT fallback 16 task gap."))
CH += [(1448,"baseFuelMass","U16","mg","Uncorrected model fuel mass, saturates at 655.35 mg"),(1450,"dlGeneration","U16","","Terminal at 65535 until boot"),(1452,"dlCommandMasks","U16","","Low byte ignition ON; high byte injector ON"),(1454,"dlReservedMasks","U16","","Low byte ignition reservations; high byte injector reservations"),(1456,"dlQueueCount","U16","","Hardware deadline node count")]
for _b in range(8):
    CH.append((1458+8*_b,"inj%dAcceptedFullUs"%(_b+1),"U32","us","Full last accepted width; narrow ScheduledUs saturates at 65535"))
    CH.append((1462+8*_b,"inj%dDeliveredFullUs"%(_b+1),"U32","us","Full last delivered command interval; independent physical verification pending"))
for i, nm in enumerate(ADC_NAMES):
    CH.append((96 + 2 * i, "adc%02d_%s" % (i, nm), "U16", "cnt",
               "raw AN%d count - Bosch's ME7.1.1 port map says %s" % (i, nm)))

# Display conversions only. They do not alter the 208-byte wire block. The
# scale is part of the firmware variable's contract (the X10/X100 suffixes),
# not a guessed sensor calibration.
SCALE = {
    90: 0.01, 128: 0.1, 130: 0.1, 132: 0.1, 134: 0.1, 780: 0.1,
    136: 0.1, 138: 0.1, 140: 0.1, 142: 0.1,
    # 144 engLoad, 358 rlX10, 404 dbwPedalX10 - all three are 0.1-unit values
    # and all three used to be declared `scale 1` with a `%` unit, so a gauge
    # read 1000 where the tuner meant 100.0 %. They are also the TRACING
    # channels the table editor uses for its cursor, and a tracer whose scale
    # does not match its axis puts the cursor in the wrong cell.
    144: 0.1, 358: 0.1, 404: 0.1,
    # 442 veLoadX10 - the load the VE lookup ACTUALLY used, so the cursor on
    # the VE table is right whichever CAL_LOAD_SOURCE is selected.
    442: 0.1,
    148: 0.1, 150: 0.01, 154: 0.1, 212: 0.1,
    230: 0.1, 246: 0.1, 296: 0.1, 298: 0.1, 306: 0.1,
    326: 0.1, 328: 0.1,
    308: 0.01, 312: 0.1, 314: 0.1, 316: 0.1, 318: 0.1,
}
SCALE.update({1404:0.1,1410:0.1,1418:0.1,1420:0.001,1422:0.001,1424:0.1,1426:0.1,1446:0.001,1448:0.01})
CH += [
    (1522, "sweepSignedDuty", "S16", "%", "Signed achieved motor command; positive opens"),
    (1524, "sweepFindings", "U16", "", "Candidate flags: authority1 bias2 P4 I8 D16 mechanical32 TPS64 rate128 inconclusive256"),
    (1526, "sweepRms", "U16", "%", "Current section RMS error; fixed-point approximation"),
    (1528, "sweepSaturation", "U16", "%", "Current section samples at configured duty ceiling"),
]
SCALE.update({1522: 0.1, 1526: 0.1, 1528: 0.1})
CH += [(1530, "sweepBiasState", "U16", "", "Measured bias eligibility / save refusal reason")]
for j in range(8):
    CH += [(1532+2*j, f"sweepBiasProposed{j}", "U16", "%", "Proposed steady holding bias; RAM only after Save"),
           (1548+2*j, f"sweepBiasCurrent{j}", "U16", "%", "Current calibration bias"),
           (1564+2*j, f"sweepBiasAxis{j}", "U16", "%", "Current bias curve position")]
    SCALE.update({1532+2*j:0.1,1548+2*j:0.1,1564+2*j:0.1})
CH += [(1580,"sweepBiasSamples","U16","","Fresh steady holding samples"),
       (1582,"sweepIntegralPrevious","U16","%","Previous run mean absolute holding integral"),
       (1584,"sweepIntegralMean","U16","%","This run mean absolute holding integral"),
       (1586,"sweepBiasChanged","U16","","Number of proposed curve values changed"),
       # THE SUPPORTED RANGE OF A PARTIAL UPDATE. Save never writes outside
       # valid min..max, and never bridges an excluded interior position, so
       # these say exactly which part of the curve the measurement earned.
       (1588,"sweepBiasValidMin","U16","%","Lowest position the measurement supports; Save changes nothing below it"),
       (1590,"sweepBiasValidMax","U16","%","Highest position the measurement supports; Save changes nothing above it"),
       (1592,"sweepBiasExcluded","U16","","Bit per measurement position rejected by a confidence gate"),
       (1594,"sweepBiasExcludedWhy","U16","","First rejection reason among the excluded positions"),
       (1596,"sweepBiasQualified","U16","","Settled samples behind the supported range"),
       # Read back from the HAL, not from the page: this says the configured
       # frequency REACHED the bridge, which is what makes dbwPwmHz not a
       # dead knob.
       (1598,"dbwPwmAppliedHz","U16","Hz","Bridge PWM frequency the hardware is actually switching at")]
SCALE.update({1582:0.1,1584:0.1,1588:0.1,1590:0.1})
# THE FRICTION BAND per measurement position (5/10/20/40/60/80 %): the
# break-away midpoint is the feed-forward candidate, the width is the band
# itself, the spread is the worst trial-to-trial difference of one edge.
FRIC_POS = (5, 10, 20, 40, 60, 80)
for j, pos in enumerate(FRIC_POS):
    CH += [(1600+2*j, f"fricMid{j}", "U16", "%", f"Break-away band midpoint at {pos} %: feed-forward candidate"),
           (1612+2*j, f"fricWidth{j}", "S16", "%", f"Friction band width at {pos} % (opening minus closing break-away)"),
           (1624+2*j, f"fricSpread{j}", "U16", "%", f"Worst trial-to-trial spread of one break-away edge at {pos} %")]
    SCALE.update({1600+2*j: 0.1, 1612+2*j: 0.1, 1624+2*j: 0.1})
# Save writes the AXIS too: a point at every supported measurement position.
for j in range(8):
    CH += [(1636+2*j, f"sweepBiasProposedAxis{j}", "U16", "%", "Proposed bias curve position; RAM only after Save")]
    SCALE[1636+2*j] = 0.1

# (raw + translate) * scale, TunerStudio's order: raw is 10*degC + 10000.
TRANSLATE = {130: -10000.0, 132: -10000.0, 780: -10000.0}   # V91: 780 cltCtrlDc
for j in range(8):
    TRANSLATE.update({1532+2*j:-1000.0,1548+2*j:-1000.0})
for j in range(6):
    TRANSLATE[1600+2*j] = -1000.0
TRANSLATE[940] = -10000.0   # V97 DTC freeze-frame coolant
SCALE.update({734: 0.001, 736: 0.001, 746: 0.1, 758: 0.1})
SCALE.update({850: 0.1, 852: 0.1})   # V96 Ri in ohm
SCALE.update({880: 0.1, 882: 0.1, 884: 0.1, 886: 0.1})   # V97 cam, degrees
SCALE.update({892: 0.1, 896: 0.1, 898: 0.1, 900: 0.1, 902: 0.1})   # V97 boost
SCALE.update({906: 0.1, 908: 0.1})   # V97 idle
SCALE.update({706: 0.1})   # V97 trigger angle in force
SCALE.update({940: 0.1, 942: 0.1, 944: 0.1})   # V97 DTC freeze frame
SCALE.update({948: 0.1})   # V97 injector duty
SCALE.update({950: 0.1, 952: 0.1, 954: 0.1, 956: 0.1, 958: 0.001,
              966: 0.1, 968: 0.1})   # V97 DBW terms, commissioning verify
SCALE.update({1006: 0.1, 1008: 0.1})   # V97 ignition correction, idle timing
SCALE.update({1040: 0.1, 1042: 0.1, 1050: 0.1, 1110: 0.8})   # V97 knock
SCALE.update({1112: 0.1, 1114: 0.1, 1116: 0.1, 1118: 0.1,
              1122: 0.1, 1124: 0.1, 1126: 0.1, 1128: 0.1})   # V97 VVT
SCALE.update({1086: 0.0625, 1087: 0.0625, 1088: 0.0625, 1089: 0.0625, 1090: 0.0625, 1091: 0.0625, 1092: 0.0625, 1093: 0.0625})
SCALE.update({1094: 0.25, 1095: 0.25, 1096: 0.25, 1097: 0.25, 1098: 0.25, 1099: 0.25, 1100: 0.25, 1101: 0.25})
# V98 (bugs B1/B2, the maintainer's design records): the firmware publishes
# lambdaTarget x1000 and these as x10 - declared scale 1 until V98, so the
# target lambda read 1000 and the ETB target 523 for 52.3 %. One physical
# value, one representation; tools/research/och_scale_audit.py holds it.
SCALE.update({356: 0.001, 360: 0.1,
              406: 0.1, 408: 0.1, 410: 0.1, 412: 0.1,
              416: 0.1, 418: 0.1, 420: 0.1, 422: 0.1,
              700: 0.1, 704: 0.1, 710: 0.1, 712: 0.1,
              800: 0.1, 802: 0.1, 818: 0.1, 832: 0.1})
# V98: the fast block and the engine-control state
SCALE.update({1138: 0.1, 1140: 0.1, 1142: 0.1, 1144: 0.1, 1146: 0.1,
              1148: 0.1, 1150: 0.1, 1152: 0.001, 1154: 0.001, 1156: 0.1,
              1158: 0.001, 1160: 0.1, 1162: 0.1, 1164: 0.01, 1172: 0.1,
              1174: 0.1, 1176: 0.1, 1180: 0.1, 1182: 0.1, 1190: 0.1,
              1192: 0.001, 1194: 0.1, 1196: 0.1, 1198: 0.1, 1202: 0.1,
              1208: 0.1, 1210: 0.1, 1214: 0.1, 1216: 0.1, 1218: 0.1,
              1220: 0.1})
TRANSLATE[1144] = -10000.0
TRANSLATE[1146] = -10000.0

# ======================================================= AMBIENT PRESSURE ===
#
# THE OLD EXPRESSION WAS BUILT ON AN A2L READ AGAINST A BINARY IT IS NOT A MAP
# OF, and that is the whole of the +22 % the bench measured on 2026-09-05: BARO
# showed 1.22 bar with the local pressure at 1000.6 hPa.
#
# It said DSUGRAD = 6080 and DSUOFS = 7040 "at OEM ME7.1.1 0x8299AE". Both
# numbers really are at that address in this ECU's own image - but the address
# came from `the A1104F A2L`, which declares
# EPK "41/1/ME7.1.1/4/A1104F//44HE/DstH0/100304/", and THAT STRING IS NOT AT
# 0x810005 IN THE IMAGE THIS ECU RUNS. Two calibrations with 13 % of their
# calibration region in common; in our binary those two words are cells fifteen
# and sixteen of a strictly rising ramp - an axis for something else entirely.
#
# THE ECU IDENTIFIES ITSELF, in its own flash: Bosch 0261207696 at 0x8183F3,
# Porsche software 022906032BT at 0x81840F, Bosch software 1037371766 at
# 0x8183FD.
#
# tests/firmware/engine/me711_ambient_pressure.py derives the replacement and holds the general
# rule that would have stopped it: AN A2L ADDRESS MAY BE READ FROM A BINARY
# ONLY IF THAT BINARY CARRIES THE A2L'S OWN EPK AT THE A2L'S OWN ADDR_EPK.
#
# What is published now is THIS ECU's own DSU calibration, located by the
# code that reads it (me711_ambient_pressure.target_transfer: DSUGRAD 16192
# @0x81EE12, DSUOFS 0 @0x81EE14) - the same transfer the firmware applies
# when Ambient source is "Onboard barometric sensor" (hcload711.c). The
# 2026-09-05 near-full-scale reading came from the unaligned window; every
# capture since reads s5500Idx 0xFFFF and a plausible ambient pressure.
_AMB = AMB.transfer()
_AMB_EXPR, _AMB_NOTE = AMB.ini_expression(_AMB)

DERIVED_CH = [
    # ---- STAGE A: THE PACKED WORDS, TAKEN APART.
    # hcmain_me711.c:639-641,666 publishes two meanings per 16-bit word. The
    # bench read `ramProbe = 514` and a human had to know that 0x0202 is
    # "2 probes attempted, verdict PASS". These are the same numbers, split, so
    # bitStringValue() can name them. NO OFFSET IS CONSUMED - an expression
    # channel is computed by TunerStudio, so the OCH BLOCK IS UNCHANGED.
    ("ramProbeVerdict", "{ ramProbe & 255 }", "",
     "SRAM probe verdict - the low byte, HCNV_RP_*"),
    ("ramProbeCount", "{ (ramProbe >> 8) & 255 }", "",
     "how many probes have been attempted"),
    ("nvmStateLo", "{ nvmState & 255 }", "",
     "persistence state - the low byte, HCNV_ST_*"),
    ("nvmPhase", "{ (nvmState >> 8) & 255 }", "",
     "commit phase - the high byte, HCNV_PH_*"),
    ("nvmErrLo", "{ nvmError & 255 }", "",
     "persistence error - the low byte, HCNV_ERR_*. 0 is OK even when the "
     "whole word reads 256"),
    ("nvmSlot", "{ (nvmError >> 8) & 255 }", "",
     "which sector contains the active cell - high byte, HCNV_SLOT_*"),
    ("nvmSrcLo", "{ nvmSource & 255 }", "",
     "where this boot's calibration came from - HCNV_SRC_*"),
    ("nvmClass", "{ (nvmSource >> 8) & 255 }", "",
     "persistence class - HC_PERSIST_*. 2 means it survives loss of power"),
    ("grabVerdict", "{ grabResult & 255 }", "",
     "the endpoint grab's verdict - the low byte, ENG_GRAB_*"),
    ("grabWhat", "{ (grabResult >> 8) & 255 }", "",
     "which endpoint the last grab was asked for"),
    ("toothLogResult", "{ toothLogState & 255 }", "",
     "tooth profile test state - HC_TL_*"),
    ("etbCalResult", "{ etbCalStatus & 15 }", "",
     "ETB calibration / autotune result - ETB_RES_*"),
    ("etbCalPhase", "{ (etbCalStatus >> 4) & 15 }", "",
     "ETB calibration / autotune phase - ETB_CAL_*"),
    ("etbCalWhy", "{ (etbCalStatus >> 8) & 255 }", "",
     "why the ETB calibration / autotune stopped - ETB_WHY_*"),
    ("linkRate", "{ linkState & 3 }", "",
     "serial rate the ECU is at: 0 57600, 1 115200, 2 124800"),
    ("linkLocked", "{ (linkState >> 4) & 1 }", "",
     "1 once a CRC-valid request arrived at this rate"),
    ("linkSwitches", "{ (linkState >> 8) & 255 }", "",
     "serial rate changes since boot (mod 256)"),
    ("kwpPhase", "{ kwpState & 15 }", "",
     "KWP state: 0 idle, 1..5 handshake, 6 session, 7 handed to TunerStudio"),
    ("kwpInits", "{ (kwpState >> 8) & 255 }", "",
     "successful 5-baud inits since boot (mod 256)"),
    ("etbProcKind", "{ etbProc & 15 }", "",
     "which ETB procedure ran - ETB_PROC_*"),
    ("etbFailPhase", "{ (etbProc >> 4) & 15 }", "",
     "the ETB phase a failure happened in - ETB_CAL_*"),
    ("etbEndpointsOk", "{ (etbProc >> 8) & 1 }", "",
     "1: the endpoint calibration passed in this run (in RAM)"),
    ("etbOperatorAbort", "{ (etbProc >> 9) & 1 }", "",
     "1: the last run was aborted by the operator"),
    ("etbDriving", "{ (etbDrive >> 15) & 1 }", "",
     "1 while an ETB procedure drives the bridge"),
    ("etbDriveDir", "{ (etbDrive >> 14) & 1 }", "",
     "direction leg an ETB procedure is driving"),
    ("etbDriveDutyX10", "{ etbDrive & 1023 }", "%",
     "duty an ETB procedure is driving, 0.1 %"),
    ("presetVerdict", "{ presetResult & 255 }", "",
     "the engine preset apply verdict - the low byte, PRESET_V_*"),
    ("presetWhich", "{ (presetResult >> 8) & 255 }", "",
     "which preset id the last apply was asked for"),
    ("nvmErrorFree", "{ (nvmError & 255) == 0 }", "",
     "1 when there is no persistence error, whatever the slot byte says"),
    ("mainRelayFeedbackRaw", "{ s5500w14 & 1023 }", "cnt",
     "V82: ASIC AN14 HR - the main-relay line, cavity 23. Window w14 carries "
     "ADC tag 14 (bench 2026-09-25: w00..w15 = tags 0..15 in port-map order). "
     "Until V81 this read w07, which is UBR_A. 80 counts with nothing on 23: "
     "only meaningful with a relay coil connected"),
    ("mainRelayFeedbackVoltage", "{ mainRelayFeedbackRaw * 0.027825 }", "V",
     "HR at the UBR_A scale - the HR divider is NOT known to match; raw is "
     "the measurement"),
    ("mainRelayWindowOk", "{ s5500Base == 4 && ((s5500w14 >> 12) & 15) == 14 }", "",
     "1 when window w14 is the ASIC's AN14 by its own ADC tag"),
    ("heater1SenseRaw", "{ s5500w12 & 1023 }", "cnt",
     "V82: ASIC AN12 U_LS1HVK - bank 1 lambda heater output voltage (tag 12). "
     "1011 with no heater connected"),
    ("heater2SenseRaw", "{ s5500w13 & 1023 }", "cnt",
     "V82: ASIC AN13 U_LS2HVK - bank 2 heater output voltage (tag 13)"),
    ("fuelPumpLife", "{ fuelPumpState & 255 }", "",
     "0 OFF 1 PRIME 2 CRANKING 3 RUNNING 4 STOPPED 5 FAULT"),
    ("fuelPumpRequest", "{ (fuelPumpState >> 8) & 1 }", "",
     "1 when the lifecycle requests the pump ON"),
    ("fuelPumpPinOn", "{ outputPins & 1 }", "",
     "1 when the pump's CPU pin is driven at the active level"),
    ("fuelPumpPermitted", "{ (outputPins >> 2) & 1 }", "",
     "1 when the HAL permits the pump output"),
    ("mainRelayPinOn", "{ (outputPins >> 1) & 1 }", "",
     "1 when the main relay's CPU pin is driven at the active level"),
    ("mainRelayInhibited", "{ (outputPins >> 3) & 1 }", "",
     "1 when the relay is requested ON and bound but not permitted"),
    ("crankPinLevel", "{ (outputPins >> 4) & 1 }", "",
     "V77 live level of P2.15 (CC15, crank path from cavity 82), read now"),
    ("cam1PinLevel", "{ (outputPins >> 5) & 1 }", "",
     "V77 live level of P2.8 (CC8, cam 1 path from cavity 86), read now"),
    ("cam2PinLevel", "{ (outputPins >> 6) & 1 }", "",
     "V77 live level of P2.9 (CC9, cam 2 path from cavity 87), read now"),
    ("cltRawAsic", "{ s5500w00 & 1023 }", "cnt",
     "V78 S5500 AN0 / TMOT raw (cavity 93) - valid while (s5500w00 >> 12) == 0"),
    ("iatRawAsic", "{ s5500w01 & 1023 }", "cnt",
     "V78 S5500 AN1 / TANS raw (cavity 26) - valid while (s5500w01 >> 12) == 1"),
    ("o2Pre1Volts", "{ adc06_LS1VK * 0.0048876 }", "V",
     "MAIN AN6 LS1VK, bank-1 pre-cat wideband: the CJ120 UA output. 1.50 V = "
     "zero pump current. NOT A LAMBDA - the LSU heater is an ASIC output"),
    ("o2Pre2Volts", "{ adc04_LS2VK * 0.0048876 }", "V",
     "MAIN AN4 LS2VK, bank-2 pre-cat wideband UA - same caveat"),
    ("relayFeedV", "{ (s5500w07 & 1023) * 0.027825 }", "V",
     "relay-switched supply UBR_A = ASIC AN7 (Bosch port map), identified "
     "by the ADC's own tag 7 in window w07 (V82 bench). Stays at 12.24 V "
     "through KL15-off and run-on on this bench because cavity 3 is fed from "
     "KL30 here; the scale 0.027825 V/count is the A2L sibling wubr_w"),
    ("lambda1Valid", "{ lambdaStatus & 1 }", "", "bank 1 lambda is a measurement"),
    # V97: the idle state word as readable flags (never a raw number)
    ("idleClosedLoop", "{ (idleState & 32) > 0 }", "", "idle rpm loop closed"),
    ("idleDashpot", "{ (idleState & 128) > 0 }", "", "dashpot after a release"),
    ("idleTrimLimit", "{ (idleState & 64) > 0 }", "", "idle trim at its authority"),
    ("idleTrimHeld", "{ (idleState & 24) > 0 }", "", "pedal pressed or coasting: trim held"),
    ("lambda2Valid", "{ (lambdaStatus >> 1) & 1 }", "", "bank 2 lambda is a measurement"),
    ("lambda1Pump", "{ (lambdaStatus >> 12) & 1 }", "", "V96 bank 1 CJ120 pump current ON (PA verified) - only once the sensor is at temperature"),
    ("lambda2Pump", "{ (lambdaStatus >> 13) & 1 }", "", "V96 bank 2 pump current ON"),
    ("lambda1CalOk", "{ (lambdaStatus >> 14) & 1 }", "", "V96 bank 1 calibration (pump zero + Ri reference) in spec"),
    ("lambda2CalOk", "{ (lambdaStatus >> 15) & 1 }", "", "V96 bank 2 calibration in spec"),
    ("heater1State", "{ (lambdaStatus >> 2) & 7 }", "", "V96: 0 off 1 wait 2 preheat 3 ramp 4 closed loop 5 ready 6 fault"),
    ("heater2State", "{ (lambdaStatus >> 5) & 7 }", "", "V96: 0 off 1 wait 2 preheat 3 ramp 4 closed loop 5 ready 6 fault"),
    ("lambda1State", "{ (lambdaStatus & 1) ? 4 : ((((lambdaStatus >> 2) & 7) == 6) ? 5 : ((((lambdaStatus >> 2) & 7) >= 4) ? 3 : ((((lambdaStatus >> 2) & 7) >= 2) ? 2 : ((lambdaStatus & 256) ? 1 : 0)))) }", "", "V96: 0 OFF (source not internal / not polled) 1 INITIALIZING (CJ120 verified, calibrating or heater waiting - engine not running) 2 HEATING (preheat or ramp) 3 WARMING (closed loop on Ri, not yet stable) 4 READY (lambda is a measurement) 5 FAULT (lam1Fault says which)"),
    ("lambda2State", "{ (lambdaStatus & 2) ? 4 : ((((lambdaStatus >> 5) & 7) == 6) ? 5 : ((((lambdaStatus >> 5) & 7) >= 4) ? 3 : ((((lambdaStatus >> 5) & 7) >= 2) ? 2 : ((lambdaStatus & 512) ? 1 : 0)))) }", "", "V96 bank 2: as lambda1State"),
    ("lam1Fault", "{ lamFault & 255 }", "", "V96 bank 1 latched fault: 0 none 1 heater short GND 2 heater open / no sensor 3 heater short UB 4 IA/IP 5 UN 6 VM 7 chip 8 calibration 9 did not heat 10 overheat 11 underheat 12 no Ri signal"),
    ("lam2Fault", "{ (lamFault >> 8) & 255 }", "", "V96 bank 2 latched fault, as lam1Fault"),
    ("vvt1Fault", "{ (vvt1State >> 8) & 127 }", "", "V97 cam 1 VVT fault (hcVvtFaultList)"),
    ("vvt2Fault", "{ (vvt2State >> 8) & 127 }", "", "V97 cam 2 VVT fault"),
    ("vvt1Closed", "{ (vvt1State & 16) > 0 }", "", "V97 cam 1 closed loop"),
    ("vvt2Closed", "{ (vvt2State & 16) > 0 }", "", "V97 cam 2 closed loop"),
    ("knockModeNow", "{ knockState & 255 }", "", "V97 knock: 0 off 1 monitor 2 active"),
    ("knockWhy", "{ (knockState >> 8) & 255 }", "", "V97 knock: why the last window was not taken (hcKnockWhyList)"),
    ("knockLastCyl", "{ (knockLast & 255) + 1 }", "", "V97 knock: the last window's cylinder, 1-based"),
    ("knockCfgErr", "{ (knockLast >> 8) & 255 }", "", "V97 knock: calibration refusal code, 0 = none"),
    ("knockSens1Fault", "{ (knockSelFault >> 8) & 1 }", "", "V97 knock sensor 1 fault latched"),
    ("knockSens2Fault", "{ (knockSelFault >> 9) & 1 }", "", "V97 knock sensor 2 fault latched"),
    ("knockSens3Fault", "{ (knockSelFault >> 10) & 1 }", "", "V97 knock sensor 3 fault latched"),
    ("knockSens4Fault", "{ (knockSelFault >> 11) & 1 }", "", "V97 knock sensor 4 fault latched"),
    ("lam1Why", "{ lamWhy & 255 }", "", "V97 bank 1: why lambda is withheld (hcLamWhyList), 0 = valid"),
    ("lam2Why", "{ (lamWhy >> 8) & 255 }", "", "V97 bank 2: why lambda is withheld"),
    ("cj1Err", "{ cjErr & 255 }", "", "V97 CJ120 #1 exchanges refused"),
    ("cj2Err", "{ (cjErr >> 8) & 255 }", "", "V97 CJ120 #2 exchanges refused"),
    ("cj1Tmo", "{ cjTmo & 255 }", "", "V97 CJ120 #1 SSC exchanges that never completed"),
    ("cj2Tmo", "{ (cjTmo >> 8) & 255 }", "", "V97 CJ120 #2 SSC exchanges that never completed"),
    ("cj1Ok", "{ (lambdaStatus >> 8) & 1 }", "", "V97 CJ120 #1 verified (IDENT + INIT_REG1 read back)"),
    ("cj2Ok", "{ (lambdaStatus >> 9) & 1 }", "", "V97 CJ120 #2 verified"),
    ("lam1Veff", "{ (lamVeff & 255) * 0.1 }", "V", "V96 bank 1 heater effective voltage"),
    ("lam2Veff", "{ ((lamVeff >> 8) & 255) * 0.1 }", "V", "V96 bank 2 heater effective voltage"),
    ("cj1Diag", "{ cj120Diag & 255 }", "", "CJ120 #1 DIAG, 255 = no failure"),
    ("cj2Diag", "{ (cj120Diag >> 8) & 255 }", "", "V97: CJ120 #2 DIAG, 255 = no failure"),
    ("cam1PatClass", "{ cam1Pat & 255 }", "", "V97 cam 1: 0 learning 1 this half 2 other half 3 alive 4 no tooth 5 outside authority 6 noise"),
    ("cam1PatTooth", "{ (cam1Pat >> 8) & 255 }", "", "V97 cam 1 tooth identified, 255 none"),
    ("cam2PatClass", "{ cam2Pat & 255 }", "", "V97 cam 2, as cam1PatClass"),
    ("cam2PatTooth", "{ (cam2Pat >> 8) & 255 }", "", "V97 cam 2 tooth identified, 255 none"),
    ("boostMode_", "{ boostState & 255 }", "", "V97 boost: 1 cut 2 no pressure 4 off 8 below floor 16 open 32 closed (+64 saturated)"),
    ("boostFuelCut", "{ (boostState >> 8) & 1 }", "", "V97 1 = overboost fuel cut on"),
    ("heater1Duty", "{ heaterDuty & 255 }", "%", "V97: bank 1 LSU heater duty"),
    ("heater2Duty", "{ (heaterDuty >> 8) & 255 }", "%", "V97: bank 2 LSU heater duty"),
    ("runOnState", "{ runOn & 255 }", "", "0 RUN 1 HOLD 2 RELEASED 3 TIMEOUT 4 not configured 5 booted during key-off - power not held (V93)"),
    ("keyOff", "{ (runOn >> 8) & 1 }", "", "KL15 is off: every output held safe"),
    ("runOnAsserted", "{ (runOn >> 9) & 1 }", "", "NLEN_FR LOW: the CJ910 is being asked to stay up"),
    ("kl15Status", "{ (outputPins >> 7) & 1 }", "",
     "V78 KL15_STAT, P6.2 - the CJ910's own ignition signal; the native "
     "main-relay stage on cavity 23 follows it"),
    ("baroRaw",   "{ s5500w08 & 1023 }", "cnt",
     "onboard ambient sensor raw (I/O chip AN8); valid while s5500Base = 4"),
    ("ambientVoltage", "{ baroRaw * %.10f }" % _AMB["volts_per_count"], "V",
     "onboard ambient sensor voltage, 5/1024 V/count"),
    ("ambientPressure", _AMB_EXPR, "hPa", _AMB_NOTE),
    ("ambientPressureBar", "{ ambientPressure * 0.001 }", "bar",
     "ambientPressure converted hPa -> bar"),
    # A RAIL IS NOT A READING - BUT IT DOES NOT SAY WHICH FAULT IT IS. Near
    # full scale means the SOURCE BEING READ is near full scale, and that is
    # all. Read s5500Idx bit 8 to find out whether the source is even the right
    # frame word. eng_service() applies the same band to every other channel,
    # ADC_PLAUS_LO/HI = 10/1013.
    ("baroPlausible", "{ baroRaw > 10 && baroRaw < 1013 }", "",
     "0 when the ambient raw is at a rail. Which fault that is - an unaligned "
     "S5500 window reading the wrong word, or ASIC AN8 itself - is s5500Idx "
     "bit 8"),
    ("baroWindowOk", "{ s5500Base == 4 }", "",
     "1 when baroRaw points at runtime frame word 12"),
    # The fuel model in words (Fuel > Fuel model, Setup > Base engine): the
    # CONFIGURATION, as expressions over the page - Speeduino's
    # `strokeMultipler = { twoStroke == 1 ? 1 : 2 }`. Indices into
    # hcFuelModelList / hcLoadAxisList / hcDensityList.
    ("cfgFuelModel", "{ fuelModel }", "",
     "configured fuel model (hcFuelModelList)"),
    ("cfgVeAxisKind",
     "{ (fuelModel == 2 || (fuelModel == 0 && loadSource == 0)) ? "
     "(pressureRole == 1 ? 4 : (pressureRole == 2 ? 5 : 1)) : 2 }", "",
     "what the VE table is looked up on (hcLoadAxisList)"),
    ("cfgDensityKind",
     "{ fuelModel == 2 ? 0 : (fuelModel == 3 ? (densityPolicy == 2 ? 5 : 1) "
     ": (fuelModel == 1 ? (ambientCorrection == 1 ? 4 : 3) "
     ": (loadSource == 2 ? 3 : (pressureRole == 1 ? 0 "
     ": (pressureRole == 2 ? 1 : 2))))) }", "",
     "which pressure sets the air density (hcDensityList)"),
    ("ambientFallback", "{ (loadFlags & 4) != 0 && ambientSource != 0 }", "",
     "the selected ambient source has no valid reading: reference in use"),
    ("iatDensityFallback",
     "{ (loadFlags & 8) != 0 && fuelModel != 0 && fuelUseIat == 1 }", "",
     "intake temperature selected for density but not valid: 20 C in use"),
    ("nvmNotBurned", "{ (nvmState & 255) == 1 }", "",
     "the page has been edited since the last Burn"),
    ("nvmBurnPending", "{ (nvmState & 255) == 2 || (nvmState & 255) == 3 }", "",
     "a Burn was requested and the flash commit has not happened yet"),
    ("nvmBurned", "{ (nvmState & 255) == 5 }", "",
     "the last Burn reached flash and verified"),
    ("nvmBurnFailed", "{ (nvmState & 255) == 6 }", "",
     "the last Burn gave up; the PREVIOUS flash record still stands"),
    ("nvmNonVolatile", "{ (nvmSource >> 8) == 2 }", "",
     "there is a committed calibration record in the flash device"),
    ("nvmOnDefaults", "{ (nvmSource & 255) == 0 }", "",
     "this boot came up on the COMPILED-IN calibration"),
    ("asicRxFrames", "{ asicRx }", "",
     "active ASIC startup+runtime frames completed"),
    ("asicBadFrames", "{ asicCsumErr + asicTimeouts + asicSscErr }", "",
     "active checksum, timeout and SSC failures"),
    ("tps1Raw", "{ adc01_TPS1 & 1023 }", "cnt", "MAIN AN1 TPS track 1 raw"),
    ("tps1Voltage", "{ tps1Raw * 0.0048828125 }", "V", "MAIN AN1 TPS track 1 voltage"),
    ("tps2Raw", "{ adc03_TPS2 & 1023 }", "cnt", "MAIN AN3 TPS track 2 raw"),
    ("tps2Voltage", "{ tps2Raw * 0.0048828125 }", "V", "MAIN AN3 TPS track 2 voltage"),
    ("app1Raw", "{ adc08_PEDAL1 & 1023 }", "cnt", "MAIN AN8 pedal track 1 raw"),
    ("app1Voltage", "{ app1Raw * 0.0048828125 }", "V", "MAIN AN8 pedal track 1 voltage"),
    ("app2Raw", "{ adc09_PEDAL2 & 1023 }", "cnt", "MAIN AN9 pedal track 2 raw"),
    ("app2Voltage", "{ app2Raw * 0.0048828125 }", "V", "MAIN AN9 pedal track 2 voltage"),
    ("noSync", "{ syncState == 0 }", "",
     "expected on the stationary BENCH_SAFE image"),
    # V98: the engine-control layer, decoded (hcengctl711.h EC_F_*)
    ("toothLogReady", "{ toothLogStatus & 1 }", "",
     "the tooth logger buffer is ready to read"),
    ("egoCorrForVeAnalyze", "{ 100 + stftBank1 }", "%",
     "closed-loop correction in force, 100 = none (Tune Analyze)"),
    ("flagRunning", "{ (engineFlags & 1) > 0 }", "", "engine running"),
    ("flagAse", "{ (engineFlags & 4) > 0 }", "", "after-start enrichment"),
    ("flagWarmup", "{ (engineFlags & 8) > 0 }", "", "warm-up enrichment"),
    ("flagTransient", "{ (engineFlags & 16) > 0 }", "",
     "acceleration enrichment / wall film transient"),
    ("flagDfco", "{ (engineFlags & 32) > 0 }", "", "deceleration fuel cut"),
    ("flagStft", "{ (engineFlags & 256) > 0 }", "", "closed loop correcting"),
    ("flagFuelCut", "{ (engineFlags & 512) > 0 }", "", "a fuel cut is active"),
    ("flagLaunch", "{ (engineFlags & 1024) > 0 }", "", "launch control active"),
    ("flagFlatShift", "{ (engineFlags & 2048) > 0 }", "", "flat shift active"),
    ("flagAls", "{ (engineFlags & 4096) > 0 }", "", "anti-lag active"),
    ("flagRevLimit", "{ (engineFlags & 8192) > 0 }", "", "rev limiter acting"),
    ("flagMapEst", "{ (engineFlags & 16384) > 0 }", "",
     "the fuel is using the MAP estimate (sensor fault)"),
    ("flagVeTune", "{ (engineFlags & 32768) > 0 }", "",
     "VE table written in the last 20 s - closed loop held"),
    ("stftStateLo", "{ stftState & 255 }", "", "closed loop state"),
    ("stftRegion", "{ (stftState >> 8) & 255 }", "", "closed loop region"),
    ("sparkCutPct", "{ (motorsportState & 255) * 100 / 255 }", "%",
     "spark events skipped by launch / flat shift / anti-lag / rotational idle"),
    ("primeStateLo", "{ primeState & 255 }", "", "priming state"),
]

# ============ WHY THE BURN WAS REFUSED, IN WORDS RATHER THAN A MASK ========
#
# A refused Burn cannot say so in its response code: TunerStudio ends the
# session on EVERY response code with bit 7 set, all eleven of them, and
# accepts anything with bit 7 clear without looking at it. That was read out of
# TunerStudioMS.jar, class J/f, on 2026-09-16 after 0x83 - and then 0x84 -
# both turned out to be session-fatal. See hcts.h.
#
# So the reply acknowledges the request and THESE are the verdict. The tuner
# has to be able to act on them, which means naming the rule that failed, not
# publishing cfgValidation as a decimal number and hoping.
#
# The bits are read out of hc_validation.h, so a new rule appears here by
# being added THERE. A hand-written copy is the "two artefacts that must
# agree" defect this project has paid for four times.
_VAL_H = (ROOT / "firmware/config/hc_validation.h").read_text(
    errors="replace")
_VAL_WHY = {
    "SCHEMA": "the page version or universal magic is not this firmware's",
    "CYLINDERS": "the cylinder count is out of range",
    "TDC": "a TDC angle is out of range or duplicated",
    "TRIGGER": "the wheel geometry cannot be decoded",
    "SYNC": "the strategy needs a position the trigger cannot give it - "
            "a sync mode above None with no crank pin lands here",
    "PIN_CAP": "a pin cannot do what has been asked of it",
    "PIN_CONFLICT": "one pin, two exclusive owners",
    "REV": "the speed limits are inconsistent",
    "DBW": "the throttle cannot be driven safely",
    "AXIS": "a table axis is not monotonic",
    "LAMBDA": "the lambda channels are inconsistent",
    "STRATEGY": "the output count does not match the cylinder count",
    "TARGET": "a pin does not exist on THIS ECU",
    "NOT_STOPPED": "returned by an APPLY, never by validation itself",
}
CFG_FAULT_CH = []
for _m in re.finditer(r"^#define\s+HC_VAL_FAULT_(\w+)\s+0x([0-9A-Fa-f]{4})u",
                      _VAL_H, re.M):
    _tag, _mask = _m.group(1), int(_m.group(2), 16)
    _name = "cfgFault" + "".join(w.capitalize() for w in _tag.split("_"))
    CFG_FAULT_CH.append((_name, _tag, _mask))
    DERIVED_CH.append(
        (_name, "{ (cfgValidation & %d) != 0 }" % _mask, "",
         "HC_VAL_FAULT_%s - %s" % (_tag, _VAL_WHY.get(_tag, "see "
                                                      "hc_validation.h"))))
if not CFG_FAULT_CH:
    raise SystemExit("no HC_VAL_FAULT_* found in hc_validation.h")

# ==========================================================================
# V97: TROUBLE CODES AS A READABLE LIST. The firmware publishes each code as
# decimal digits (dtcActive1 = 105). The CODE SET is parsed from hcdtc711.c's
# own defs[] table - never retyped - and every code must have a description
# here or the generator stops. dtcA1Idx.. map a code to its position in
# hcDtcList, so a dialog row reads "P0105 - MAP sensor" (bitStringValue).
# ==========================================================================
DTC_TEXT = {
    11: "Camshaft 1 timing (VVT)",
    21: "Camshaft 2 timing (VVT)",
    105: "Manifold absolute pressure sensor",
    110: "Intake air temperature sensor",
    115: "Coolant temperature sensor",
    120: "Throttle position sensor 1",
    130: "O2 sensor bank 1",
    150: "O2 sensor bank 2",
    217: "Engine over temperature",
    220: "Throttle position sensor 2",
    234: "Overboost",
    325: "Knock sensor 1",
    330: "Knock sensor 2",
    335: "Crankshaft position - sync lost",
    340: "Camshaft position - phase lost",
    351: "Ignition coil - over-dwell",
    560: "System voltage",
    602: "ECU configuration invalid",
    606: "ECU internal link",
    2100: "Throttle motor circuit",
    2110: "Throttle fault - rpm limited",
    2119: "Throttle actuator performance",
    2120: "Pedal sensor 1",
    2125: "Pedal sensor 2",
    2135: "Throttle position 1/2 mismatch",
    2138: "Pedal sensor 1/2 mismatch",
}
_DTC_C = (ROOT / "firmware/targets/me711/diagnostics/hcdtc711.c"
          ).read_text(encoding="utf-8", errors="replace")
_DTC_DEFS = re.search(r"static const hcdtc_def_t defs\[P_N\] = \{(.*?)\n\};",
                      _DTC_C, re.S)
if not _DTC_DEFS:
    raise SystemExit("hcdtc711.c: defs[P_N] table not found")
DTC_CODES = [int(m.group(1)) for m in
             re.finditer(r"^\s*\{\s*(\d+)u,", _DTC_DEFS.group(1), re.M)]
_undescribed = sorted(set(DTC_CODES) - set(DTC_TEXT))
if _undescribed or len(DTC_CODES) < 20:
    raise SystemExit("hcdtc711.c codes without a description in DTC_TEXT: %s"
                     % _undescribed)
DTC_ORDER = sorted(DTC_TEXT)        # list index = position + 1; 0 = none
DTC_UNKNOWN = len(DTC_ORDER) + 1


def dtc_list_line():
    top = 1
    while top <= DTC_UNKNOWN:
        top <<= 1
    labels = ["-"] + ["P%04d - %s" % (c, DTC_TEXT[c]) for c in DTC_ORDER]
    labels.append("Unknown code - see Diagnostics")
    labels += ["INVALID"] * (top - len(labels))
    return "   %-20s = bits, U08, [0:%d], %s" % (
        "hcDtcList", top.bit_length() - 2,
        ", ".join('"%s"' % x for x in labels))


def dtc_list_top():
    top = 1
    while top <= DTC_UNKNOWN:
        top <<= 1
    return top


DTC_STATUS = ["Stored", "Active + Stored", "Stored (freeze frame)",
              "Active + Stored (freeze frame)"]


def dtc_row_list_line():
    """V98 (real TunerStudio): one row = ONE indicator reading
    "Status  |  Pxxxx - description" - two indicators side by side split the
    row in halves and shrank the code text to unreadable. Index =
    status * top + code position (the dtcS<n>Row channels)."""
    top = dtc_list_top()
    assert 4 * top <= 256, "hcDtcRowList needs more than 8 bits"
    codes = ["P%04d - %s" % (c, DTC_TEXT[c]) for c in DTC_ORDER]
    codes.append("Unknown code - see Diagnostics")
    labels = []
    for st in DTC_STATUS:
        row = ["-"] + ["%s  |  %s" % (st, c) for c in codes]
        labels += row + ["INVALID"] * (top - len(row))
    return "   %-20s = bits, U08, [0:%d], %s" % (
        "hcDtcRowList", (4 * top).bit_length() - 2,
        ", ".join('"%s"' % x for x in labels))


def cfg_field_list_line():
    """V98r2: slot index -> the setting's tuner label, in hc_cfg_slots order
    (hc_config_generated.c), so a refused Burn names the setting."""
    gen = (ROOT / "firmware/generated/hc_config_generated.c").read_text(
        errors="replace")
    body = gen.split("hc_cfg_slots[HC_CFG_SLOT_COUNT] = {", 1)[1].split("};", 1)[0]
    names = re.findall(r"\}\s*,?\s*/\*\s*(\w+)\s*\*/", body)
    fields, _c, _p = UI.MODEL.resolve()
    lab = {f.meta.ts: f.meta.label.replace('"', "'") for f in fields}
    labels = [lab.get(n, n) for n in names]
    bits = max(1, (len(labels) - 1).bit_length())
    labels += ["INVALID"] * ((1 << bits) - len(labels))
    return "   %-20s = bits, U16, [0:%d], %s" % (
        "hcCfgFieldList", bits - 1, ", ".join('"%s"' % x for x in labels))


def _dtc_index_expr(ch):
    e = str(DTC_UNKNOWN)
    for i in range(len(DTC_ORDER), 0, -1):
        e = "%s == %d ? %d : (%s)" % (ch, DTC_ORDER[i - 1], i, e)
    return "{ %s == 0 ? 0 : (%s) }" % (ch, e)


DTC_SLOTS = [("dtcActive%d" % i, "dtcA%dIdx" % i) for i in range(1, 5)] + \
            [("dtcStored%d" % i, "dtcS%dIdx" % i) for i in range(1, 5)]
for _ch, _ix in DTC_SLOTS:
    DERIVED_CH.append((_ix, _dtc_index_expr(_ch), "",
                       "%s as a position in hcDtcList" % _ch))
# V98: ONE LIST, ONE ROW PER CODE. hcdtc.c sets ACTIVE and STORED together
# and a clear wipes both, so every active code is also a stored one: the
# rows are the stored slots, each with a status - DTC_STATUS: 0 Stored,
# 1 Active + Stored, +2 when it is the freeze-frame code.
DERIVED_CH.append(("dtcFfIdx", _dtc_index_expr("dtcFfCode"), "",
                   "the freeze frame's code as a position in hcDtcList"))
for _i in range(1, 5):
    _s = "dtcStored%d" % _i
    DERIVED_CH.append((
        "dtcS%dSt" % _i,
        "{ ((%s != 0) && (%s == dtcActive1 || %s == dtcActive2 || "
        "%s == dtcActive3 || %s == dtcActive4) ? 1 : 0) + "
        "((%s != 0) && (%s == dtcFfCode) ? 2 : 0) }"
        % ((_s,) * 7), "",
        "stored row %d: 0 stored, 1 active + stored, +2 freeze frame" % _i))
    DERIVED_CH.append((
        "dtcS%dRow" % _i, "{ dtcS%dSt * %d + dtcS%dIdx }"
        % (_i, dtc_list_top(), _i), "",
        "stored row %d as a position in hcDtcRowList" % _i))

# V97: the 2-D table y-axis title follows the load source (rusEFI
# `xyLabels = "RPM", {bitStringValue(veAxisLabels, veOverrideMode)}`).
# V98: one list indexed like ENUM_LOAD_AXIS (hcengctl711.c hc_ec_ign_load):
# the fuel load is MAP kPa (speed density) or throttle % (alpha-N).
LOAD_AXIS_LISTS = [
    # 0..3 = ENUM_LOAD_AXIS; 4/5 name the pressure by where it is measured
    ("hcLoadAxisList", ["Fuel load", "Pressure sensor (kPa)",
                        "Throttle position (%)", "Cylinder filling (%)",
                        "Manifold pressure (kPa)", "Charge pressure (kPa)"]),
    ("hcFuelModelList", ["Legacy compatibility", "Pure Alpha-N (TPS)",
                         "Speed density (manifold pressure)",
                         "Boosted Alpha-N (TPS + charge pressure)"]),
    ("hcDensityList", ["Measured manifold pressure",
                       "Measured charge pressure",
                       "Measured pressure sensor",
                       "Reference pressure", "Ambient pressure",
                       "Ambient + boost blend"]),
    ("hcAmbientSrcList", ["Reference pressure", "Engine-stopped reading",
                          "Onboard barometric sensor"]),
    # V98: hcengctl711.h EC_STFT_* (the closed-loop state's low byte)
    ("hcStftList", ["Off", "Engine not running", "Startup delay",
                    "Coolant cold / sensor fault", "No valid lambda",
                    "Hold after fuel cut", "Hold after enrichment",
                    "Hold after other cut", "Correcting",
                    "VE table being written",
                    "Activity hold (not used)"]),
]

SENSOR_LABEL = {
    "cltError": "Coolant temperature", "mapError": "Pressure sensor",
    "tps1Error": "Throttle track 1", "tps2Error": "Throttle track 2",
    "app1Error": "Pedal track 1", "app2Error": "Pedal track 2",
    "tpsPairError": "Throttle tracks agree", "appPairError": "Pedal tracks agree",
    "vbatError": "Battery voltage", "iatError": "Intake air temperature",
}

SENSOR_BITS = [
    (0x0001, "cltError"), (0x0002, "mapError"),
    (0x0004, "tps1Error"), (0x0008, "tps2Error"),
    (0x0010, "app1Error"), (0x0020, "app2Error"),
    (0x0040, "tpsPairError"), (0x0080, "appPairError"),
    (0x0100, "vbatError"), (0x0200, "iatError"),
]

STATUS_BITS = [
    (0,  "outputsArmed",  "RETIRED V84 - never set on ME7.1.1; see outputsPermitted"),
    (1,  "benchSafe",     "a HANICORE_BENCH_SAFE build: no output backends (never set by a normal build)"),
    (2,  "tickRunning",   "the 1 ms tick moved at boot"),
    (3,  "rxTickRunning", "the serial drain tick is armed"),
    (4,  "asicInit",      "SSC configured"),
    (5,  "asicStarted",   "a startup frame was accepted"),
    (6,  "asicRunning",   "runtime frames are flowing"),
    (7,  "asicError",     "checksum, reply class or timeout"),
    (8,  "setupFault",    "the page does not describe a runnable engine"),
    (9,  "ramBadBit",     "the external SRAM probe failed"),
    (10, "rxLoss",        "a serial byte was lost"),
    (11, "badVecBit",     "an interrupt nobody asked for"),
    (12, "tuneStored",    "the page came from the battery-backed SRAM"),
    (13, "wdtFed",        "the on-chip watchdog is being serviced"),
]


# The diagnostics dialogs. Named channels only - a dialog that shows
# everything shows nothing.
# ==========================================================================
# CONTEXTUAL HELP - only where a person can make a dangerous or confusing
# mistake. rusEFI carries 18 help topics against HaniCore's 0. These are the
# places this project has actually been bitten, or where the hardware is
# genuinely unforgiving.
#
#   (help id, title, [paragraphs])
# ==========================================================================
DERIVED_CH += [("inj%dRequestedFullUs"%b, "{ inj%dFuelUs + inj%dDeadUs }"%(b,b), "us", "Full electrical request from fuel-only width plus dead time; no second fuel correction") for b in range(1,9)]

HELP_TOPICS = [
    # V89 UI (rusEFI pass): every topic re-read against the project rules. Burn is
    # resetless and physically qualified, the user arm is retired (V84), and
    # seven topics dialogs named had never been declared at all.
    ("hcHelpFiringOrder", "Firing order and TDC", [
        "Choose the engine's firing order from the list: the ECU places each "
        "cylinder's top dead centre (TDC) from it, for an even-firing "
        "four-stroke. For an odd-firing engine choose Custom and enter each "
        "cylinder's TDC in crank degrees after cylinder 1.",
        "Injector and coil pins stay assigned per cylinder (Injection / "
        "Ignition hardware): never rearrange pins to match the firing order.",
        "A wrong order fires into a closing valve. Check it with a timing "
        "light (Ignition > Ignition hardware, fixed timing) before loading "
        "the engine.",
    ]),
    ("hcHelpTrigger", "Trigger setup", [
        "Teeth is the number of teeth the wheel WOULD have if none were "
        "missing. Gap is how many are missing. A 60-2 wheel is 60 and 2.",
        "Edge selects which capture edge the tooth is counted on. Getting it "
        "wrong shifts every ignition and injection event by a tooth width.",
        "Trigger source decides whether the real crank and cam inputs are "
        "used, or only the bench generator.",
        "Crank sync alone is enough for batch or semi-sequential fuel and "
        "wasted spark.",
        "Trigger angle is WHERE TOOTH #1 IS, in crank degrees after "
        "cylinder-1 TDC: negative = before TDC. Tooth #1 is the first tooth "
        "after the missing-tooth gap - the edge that ends the gap. A 60-2 "
        "whose first tooth after the gap passes the sensor 78 deg before "
        "TDC is -78.0 (13 teeth x 6 deg). Coming from Speeduino: its trigger "
        "angle means the same; from rusEFI: its trigger angle offset is the "
        "same number with the sign flipped (+78 there = -78 here).",
        "It is a measured number. Set fixed timing (Ignition > Ignition "
        "hardware), aim a timing light at cylinder 1 and change the trigger "
        "angle until the light shows the fixed angle - or run the tooth "
        "profile, which needs no light. Every other angle (TDC table, spark, "
        "injection, cam check angle, knock windows) is in degrees after "
        "cylinder 1 TDC and moves with it: re-check the cam check angle "
        "after a correction.",
        "VAG 1.8T (AWT) base tune: -78.0.",
    ]),
    ("hcHelpInjMode", "Injection mode", [
        "Batch and semi-sequential fire injectors in groups and need only "
        "crank sync. Sequential fires each cylinder on its own cycle and "
        "needs engine phase - a cam input that resolves the cycle.",
        "The validator refuses a sequential strategy whose cycle cannot be "
        "resolved, so the page will not apply rather than run blind.",
        "Dead time comes from the curve in this dialog (against battery); "
        "it is added after the flow calculation and never scaled by it.",
    ]),
    ("hcHelpDbw", "Electronic throttle", [
        "On undervoltage, over-temperature or over-current the throttle "
        "driver switches off and pulls its fault line LOW - hence the default "
        "fault polarity 'LOW is a fault'.",
        "The two pedal tracks and the two throttle tracks must agree within "
        "their tolerance before the controller will close the loop. That is "
        "the plausibility check, and it is not optional.",
        "The throttle target is the ETB pedal target map (rpm x pedal), "
        "never below the idle controller's floor, clamped to the minimum and "
        "maximum position.",
        "Set it up in this dialog: AutoCal ETB = TPS endpoints, PID "
        "autotune, then verify - the real closed loop steps 20-60-20-4-15 %; "
        "each must settle within 2 % in 350 ms, overshoot under 5 % and hold "
        "within 1.5 % (AUTOCAL ETB: PASS). Calibrate TPS endpoints captures "
        "the endpoints; PID Autotune tunes and verifies using the stored "
        "endpoints. The Grab buttons and the bounded bench "
        "test remain the manual ways.",
        "Battery compensation (on by default) scales the motor output by "
        "13.5 V / battery, so the gains mean the same torque at 9 V cranking "
        "and 14 V running.",
        "A pedal or throttle sensor error must persist for the confirm time "
        "(default 50 ms) before it latches; meanwhile the last output is "
        "held. A latched fault clears at the next key-on with the engine "
        "stopped. AutoCal keeps latched faults.",
        "The bridge PWM frequency is set in this dialog; 2 kHz is this ECU's "
        "factory value. Much higher frequencies lose motor torque.",
    ]),
    ("hcHelpTransient", "Transient fuel", [
        "The wall film (X-tau wall-wetting model): of every "
        "injection a share X lands on the port wall, and the film gives a "
        "share Tc/(tau+Tc) of itself to the cylinder each cycle. The ECU "
        "injects (want - film share) / (1 - X), so the CYLINDER receives "
        "what the fuel model wants: more on a tip-in while the film fills, "
        "less on a tip-out while it drains. In steady running it adds "
        "nothing.",
        "It works on the fuel per CYCLE, so batch, semi-sequential and "
        "sequential get the same correction. During a fuel cut nothing is "
        "injected and the film dries; the re-entry automatically injects "
        "the film's rebuild.",
        "Tuning: a lean spike on a tip-in (lambda log) = more X or more tau "
        "at that coolant; rich = less. The live values beside the settings "
        "show the film's share and the fuel on the wall.",
        "After-start: extra fuel the moment cranking ends, decaying linearly "
        "over the after-start duration.",
        "The VAG 1.8T base values are starting points: tune with a wideband.",
    ]),
    ("hcHelpEtbCommission", "ETB AutoCal", [
        "AutoCal ETB runs the TPS endpoint calibration and, only if it "
        "passes, the PID autotune and a verify, and reports one result. "
        "Calibrate TPS endpoints captures endpoints. PID Autotune tunes and "
        "verifies using the stored endpoints. Response tests may repeat with "
        "adjusted candidate gains; only verified gains are published. Nothing "
        "is burned and DBW is never enabled: after a PASS review the values "
        "and Burn.",
        "AutoCal captures both throttle tracks while driving the plate in "
        "each direction for a bounded time (AutoCal dwell 300..1500 ms, "
        "AutoCal duty 20..60 %). Both spans must reach 100 counts, the "
        "spring rest must lie between the ends and agree between tracks. "
        "Direction A/B reports POSITION CAPTURED, not physical stop contact. "
        "A stationary position alone cannot distinguish a stop from insufficient "
        "motor torque. Confirm full travel, spring return, current and bridge "
        "voltage on the actual throttle body before accepting calibration.",
        "PID autotune: brings the plate to 50 % (50% NOT REACHED if it cannot "
        "within 1.5 s), then a +/- relay amplitude for 8 + 16 cycles (15 s "
        "at most). OUT OF BAND: the plate left 20..80 %. PID IMPLAUSIBLE: "
        "amplitude outside 0.5..30 % or period outside 20..1000 ms. KI "
        "LIMITED: the rule asked for more integral gain than the page field "
        "holds; the field maximum (lower) is written. PID Autotune only needs "
        "stored endpoints (NO ENDPOINTS otherwise).",
        "Every run stops at once on RPM > 0, OUTPUTS OFF (configuration, I/O "
        "chip link or key), BRIDGE fault, TPS at a rail or Abort. IN: names "
        "the phase a failure happened in. Combined AutoCal keeps endpoint and "
        "PID results private until verification passes; a failure publishes "
        "neither.",
        "For a detailed record of every phase, log the run with the HaniCore "
        "vehicle tool.",
    ]),
    ("hcHelpBench", "Bench tests", [
        "Every bench test requires the engine stopped (rpm 0 and no crank "
        "signal), a valid configuration and the I/O chip link. It drives one "
        "output with a pulse and duration limited by the firmware, a finite "
        "number of times, then releases it. ABORT stops it at once.",
        "There is no arming switch: the test button is the deliberate act. A "
        "refused test says which condition failed (Controller > Bench state "
        "and refusals) - it never silently does nothing.",
        "On a new installation treat the first test of each injector, coil "
        "and throttle output as a measurement: one channel, nothing else "
        "connected, then the next.",
    ]),
    ("hcHelpBurn", "Burn and calibration storage", [
        "Editing a value changes RAM immediately and the engine uses it at "
        "once. It is NOT permanent until you Burn - an unburned edit may "
        "outlive a key-off in battery-backed RAM, but never rely on that.",
        "Burn takes a SNAPSHOT at the instant you press it and writes it to "
        "the ECU's own flash as a new record. The session stays connected; "
        "a Burn does not reset the ECU.",
        "Burn with the engine stopped or cranking: the connection pauses for "
        "a few seconds while flash is written, then resumes by itself. Above "
        "about 500 rpm on a 60-2 wheel there is no time to program flash "
        "between teeth: the Burn is refused, the old record stays valid and "
        "your edits stay live - stop the engine and Burn again. Diagnostics > "
        "Calibration storage says why.",
        "A record is valid only when its last word is written; until then "
        "the previous record is the one the ECU boots from.",
    ]),
    ("hcHelpSensors", "Sensor setup", [
        "Coolant and intake-air are a curve from raw ADC counts to "
        "temperature (this ECU's own OEM curve by default). Place a point "
        "by reading the live counts with the sensor at a known temperature.",
        "A sensor in fault displays its fault value - coolant and intake air "
        "-40 C, pressure 0 kPa - lights its FAULT lamp and sets its trouble "
        "code. The engine does not run on the displayed value: each function "
        "uses its own fallback (a failed coolant sensor gives no warm-up "
        "enrichment; under Legacy compatibility a failed pressure sensor "
        "fuels from the pressure estimate table - see Fuel > Fuel model help "
        "for the other models). Diagnostics > Why? > Which sensor failed? "
        "says which.",
    ]),
    ("hcHelpThermistor", "Temperature sensors", [
        "The curve maps raw ADC counts to temperature. Counts beyond either "
        "end of the curve are open or short circuit: the sensor then "
        "displays -40 C, its FAULT lamp lights, and fuel, ignition and idle "
        "use their own fallback values.",
        "Coolant is cavity 93 and intake air cavity 26 on this ECU. On an AWT "
        "harness the IAT wire (AWT cavity 85) must be moved to cavity 26: "
        "Porsche cavity 85 is a pressure input and cannot read an NTC.",
    ]),
    ("hcHelpPressure", "Fuel model and pressure sensor", [
        "The fuel model decides what the VE table is looked up on and which "
        "pressure sets the air density. Pure Alpha-N: throttle; the reference "
        "pressure, optionally corrected for ambient. Speed density: manifold "
        "pressure for both. Boosted Alpha-N: throttle for VE; the charge "
        "pressure before the throttle for density, measured or as an ambient "
        "+ boost blend. Legacy compatibility runs HaniCore's original models "
        "so existing calibrations behave exactly as before.",
        "Pressure sensor location must match the hardware. VAG 1.8T (AWT): "
        "cavity 101 measures charge pressure before the throttle, not "
        "manifold pressure. A location that does not fit the model is "
        "refused (Speed density needs a manifold sensor, Boosted Alpha-N a "
        "charge-pressure sensor).",
        "Transfer: kPa x10 = offset + counts x gradient / 1000, from the "
        "sensor's data sheet.",
        "Pressure enters the air density once - there is no second pressure "
        "multiplier. A lost pressure reading closes the boost valve. Speed "
        "density and Boosted Alpha-N have no pressure estimate: without the "
        "reading they deliver no fuel (Setup > Limits and protection adds the "
        "cut under load). Legacy compatibility fuels from the pressure "
        "estimate table instead.",
        "Changing the model does not rescale the VE table: retune it.",
    ]),
    ("hcHelpBaro", "Ambient pressure", [
        "Ambient (barometric) pressure is used by Pure Alpha-N's ambient "
        "correction and by the Boosted Alpha-N ambient + boost blend. The "
        "other models do not use it.",
        "Onboard barometric sensor: the ECU's own sensor on the circuit "
        "board, converted with this ECU's factory calibration and accepted "
        "between 400 and 1200 hPa. A missing or out-of-range reading falls "
        "back to the reference pressure.",
        "Pressure sensor with the engine stopped: after 1 s at rest the "
        "pressure sensor reads ambient; the value is kept for the set time "
        "and never learnt from running boost.",
        "Reference pressure: the fixed value set in Fuel > Fuel model. The "
        "panel shows which source is in use and whether it fell back.",
    ]),
    ("hcHelpTpsCal", "Throttle position sensor", [
        "This page only reads the two tracks. The throttle is set up in "
        "Advanced / Electronic Throttle Body: AutoCal ETB finds both ends by "
        "driving the plate; or hold the plate closed and press Grab Closed "
        "Throttle, hold it fully open and press Grab Fully Opened Throttle. "
        "Both tracks are written together, to RAM - Burn to keep them.",
        "MIN is the closed reading and MAX the open reading, NOT sorted: a "
        "VAG body's first track falls as the plate opens, and the direction "
        "is part of the calibration.",
        "Then move the plate slowly by hand: the two tracks must agree over "
        "the whole travel, or the throttle will never enter closed loop.",
    ]),
    ("hcHelpAppCal", "Pedal position sensor", [
        "Pedal released: Grab Released. Pedal floored and held: Grab Full "
        "Pedal. Both tracks together, in RAM - Burn to keep them.",
        "A VAG pedal's second track reads about half the first; with "
        "correlation SAME both still normalise to 0..100 % and are compared.",
    ]),
    ("hcHelpVvt", "Cam phase control (VVT)", [
        "Each cam drives its solenoid on cavity 115 or 120 (low-side PWM with "
        "a freewheel diode) from its target table (rpm x cylinder filling, "
        "degrees of advance).",
        "Closed loop measures the cam: the cam phase method must be Pattern "
        "for that cam input (Setup > Trigger), and the position is the "
        "identified tooth's deviation from its nominal angle. A position "
        "older than the maximum age is not a measurement: duty 0, PID reset.",
        "ON/OFF (1.8T 20V-style adjusters): a target > 0 switches the "
        "solenoid ON at the on/off duty; no position needed.",
        "Direction: if more duty RETARDS the cam, set it inverted.",
        "Faults (duty 0 = the phaser's rest position, latched until the "
        "engine stops, P0011 / P0021): no position in closed loop, off "
        "target by more than the limit for the time (stuck or slow "
        "phaser), the tooth outside the pattern's VVT authority, or "
        "enabled without a stage routed.",
        "Start with the bench burst: a scope on 115 / 120 shows frequency, "
        "polarity and duty. Not yet measured on this ECU.",
    ]),
    ("hcHelpKnock", "Knock control", [
        "The knock processor on the board integrates each knock sensor's "
        "band-passed signal over a crank-angle window after each cylinder's "
        "TDC; the integral (ADC counts) is compared with that cylinder's "
        "learned quiet reference times the threshold factor.",
        "START IN MONITOR. It measures and detects exactly like Active but "
        "never changes the spark. Log a drive: each cylinder's level (KI / "
        "reference) should sit near 1.0 when quiet; a real knock is a spike "
        "well above the threshold factor. Lower the factor if audible knock "
        "is missed, raise it if quiet windows are flagged.",
        "Gain: aim for a quiet reference of roughly 100..500 counts. Too low "
        "and knock is lost in one ADC step; 1023 is saturation.",
        "Sensor for cylinder: the sensor that hears it best (the nearer one). "
        "A cylinder whose reference is much lower than its neighbours' is "
        "probably on the wrong sensor.",
        "Active: each knock retards THAT cylinder by the step, up to the "
        "maximum; a quiet cylinder gets 0.25 deg back per recovery time. A "
        "sensor fault (reference outside the plausible range for the "
        "diagnosis count) gives its cylinders the sensor-fault retard.",
        "Until the cam has identified the cycle the retard is applied to the "
        "cylinder AND its 360-degree twin (the window cannot tell them apart).",
        "Not yet measured on hardware: check each sensor's signal with a "
        "tapped sensor and a log in Monitor before using Active.",
    ]),
    ("hcHelpLambda", "Wideband lambda", [
        "Two onboard Bosch LSU wideband controllers. A VAG 1.8T (AWT) sensor "
        "plugs into bank 1 (cavities 70, 51, 71, 52; heater low side 5).",
        "Measured lambda feeds closed loop fuel correction (Fuel > Closed "
        "loop fuel correction) and VE Analyze only while the sensor is READY: "
        "heated to temperature, pump current on, calibration and diagnosis "
        "clean. Lambda 0 means 'not a measurement', never 'rich', and closed "
        "loop then drops that bank's trim.",
        "The heater drive is proven on the bench; heating a fitted sensor is "
        "the first vehicle qualification step.",
    ]),
    ("hcHelpIgnition", "Ignition hardware", [
        "Coil outputs drive coils with built-in igniters: about 5 V during "
        "dwell, spark on the falling edge. Probe them through a divider, not "
        "a pull-up.",
        "Wasted spark needs only crank sync; coil-on-plug sequential needs "
        "the cam. Running dwell is the Ignition / Dwell curve; cranking "
        "dwell and cranking advance are in Cranking settings.",
        "Validate with FIXED timing and a timing light before trusting the "
        "table; the commanded advance is limited to -30..60 deg BTDC.",
    ]),
    ("hcHelpRouting", "Hardware routing", [
        "Every pin field is a PHYSICAL CONNECTOR CAVITY of the ME7.1.1 "
        "121-pin connector. Each list offers only cavities whose driver "
        "stage can do the job, and the validator refuses a conflicting or "
        "impossible assignment - the page then does not apply.",
        "Cavity 21 is the ignition (KL15) power input, 23 the main relay "
        "stage, 18 and 22 internal wideband chip selects, 4 and 5 the "
        "wideband heater low sides. None of them is a general-purpose output.",
        "A VAG 1.8T (AWT) harness needs terminal moves in its connector "
        "before this ECU is fitted (ignition feed, relay feed, relay drive, "
        "intake air temperature) - see docs/PINOUT.md; never plug it onto an "
        "unmodified harness.",
    ]),
]


DIAG_DIALOGS = [
    ("hcDiagDeadline", "Actuator deadlines",
     ["Planned and armed count logical edges; executed counts GPIO commands, not combustion.",
      "Tick = 0.8 us. Requested, compare and command are last samples, not a scope trace.",
      "Planned = publication intentions; armed = admitted logical edges; executed = GPIO command nodes, which may group channels.",
      "Independent coil max release and injector closing execute while the task is paused."],
     ["dlPlannedDwell","dlExecutedDwell","dlPlannedSpark","dlExecutedSpark","dlPlannedOpen","dlExecutedOpen","dlPlannedClose","dlExecutedClose","dlArmed","dlSuppressed","dlCancelled","dlClipped","dlRejected","dlLate","dlMaxLateTicks","dlReason","dlRequestedTick","dlCompareTick","dlCommandTick","dlGeneration","dlQueueCount","dlCommandMasks","dlReservedMasks"]),
    ("hcDiagInjectorPulses", "Injector pulse ownership",
     ["Requested fuel + dead time = electrical request. Accepted width may be clipped.",
      "Overlap is refused; minimum commanded OFF separation is 100 us.",
      "Delivered is the internal GPIO command interval. Verify valve opening on the bench."],
     ["inj%d%s"%(b,n) for b in range(1,9) for n in ("FuelUs","DeadUs","RequestedFullUs","AcceptedFullUs","DeliveredFullUs","Owner","Flags")]),
    ("hcDiagLoadPolicy", "Fuel model and air density",
     ["Air = density x cylinder volume x VE; density = pressure / (R x temperature).",
      "Fuel = air / (stoichiometric ratio x target lambda). The density ratio is for reference only.",
      "Ambient source in use: 0 reference, 1 engine-stopped reading, 2 onboard sensor.",
      "Flags: 1 invalid model, 2 pressure lost, 4 ambient fallback, 8 intake temperature fallback."],
     ["loadModelNow","pressureRoleNow","densityPolicyNow","veValue","veAxisInput","pressureMeasured","pressureValid","pressureAge","ambientUsed","ambientProvenance","ambientValid","ambientAgeSeconds","densityPressure","densityRatio","chargeBlendWeight","densityTemperature","airMgX10","baseFuelMass","loadFlags","leanMeasurement","leanEligible","leanPersistMs","leanLatched","leanRecoveryMs"]),
    ("hcDiagRuntime", "Engine runtime",
     ["What the engine layer currently believes, pass by pass.",
      "halOutCalls counts the output requests the engine layer made."],
     ["rpm", "syncState", "rlX10", "airMgX10", "mapKpaX10", "cltDc", "iatDc",
      "battDv", "lambdaTarget", "afrX10", "injTiUs", "advX10", "dwellX100",
      "warmupPct", "fuelCut", "engLoad", "halOutCalls"]),
    ("hcDiagTrigger", "Trigger and sync",
     ["The decoder, the position layer and the angle scheduler.",
      "schedulerNeedSync says what the CONFIGURED strategies require."],
     ["crankSync", "cycleSync", "crankToothIndex", "crankGapDetected",
      "crankGapPending", "crankGapMetric", "crankEdges", "crankGaps",
      "syncLossCount", "syncLossReason", "enginePositionDeg", "crankPhase",
      "crankRevolutions", "cam1Edges", "cam2Edges", "crankPinLevel",
      "cam1PinLevel", "cam2PinLevel", "cam1Window",
      "cam2Window", "camError", "crankIsrMax", "crankIsrHeadroom",
      "schedulerQueued", "schedulerExecuted", "schedulerCancelled",
      "schedulerLate", "schedulerMissed", "schedulerMaxLatency",
      "schedulerCatchup", "schedulerPending", "schedulerStatus",
      "scheduledDwellStart", "scheduledSpark", "scheduledInjStart",
      "scheduledInjEnd", "nextIgnSlot", "nextInjSlot"]),
    ("hcDiagThrottle", "Throttle, pedal and relays",
     ["The whole throttle chain, to see why a duty is what it is.",
      "dbwSteps climbs at about 200/s; a frozen count means the 5 ms",
      "throttle control is not running.",
      "",
      "dbwFaults latches: 1 calibration, 2 pedal pair, 4 throttle pair,",
      "8 pedal range, 16 throttle range, 32 bridge fault, 64 off target",
      "too long, 128 no backing sensor, 256 outputs not live.",
      "",
      "mainRelayLife: low byte the lifecycle state, high byte the",
      "configured cavity. fuelPumpState carries state, request and cavity.",
      "outputPins is the port read back: 1 pump pin on, 2 relay pin on,",
      "4 pump permitted, 8 relay refused, 16/32/64 crank / cam 1 / cam 2",
      "input levels."],
     ["dbwState", "dbwFaults", "dbwSteps", "dbwPedalX10", "dbwTargetX10",
      "dbwActualX10", "dbwErrorX10", "dbwDutyX10", "dbwInteg",
      "dbwTermP", "dbwTermD", "dbwTermFf", "dbwOutRaw", "dbwBattFactor",
      "dbwPendFaults", "dbwPendMs", "dbwFaultClears",
      "dbwApp1X10", "dbwApp2X10", "dbwTps1X10", "dbwTps2X10", "dbwSfLevel",
      "mainRelayLife", "mainRelayMode", "mainRelayCommand", "mainRelayBound",
      "kl15Status", "fuelPumpState", "fuelPumpReason", "fuelPumpRuns",
      "fuelPumpPrimeLeft", "outputPins"]),
    ("hcDiagPersist", "Calibration storage - Burn and flash",
     ["WHAT A BURN MEANS HERE. Ordinary edits change RAM only and take",
      "effect immediately; NO flash is written for a table cell or a",
      "slider. Burn takes a SNAPSHOT of the page as it is at that moment",
      "and writes it to this ECU's own flash as a new record. Anything",
      "edited afterwards is NOT part of that Burn.",
      "",
      "Burn A, then edit to B without burning: A is what is permanent.",
      "Burn A, edit to B, Burn again: B is what is permanent.",
      "",
      "A BURN KEEPS THE SESSION - no reset, no reconnect. TunerStudio",
      "pauses for a few seconds while flash is written, then resumes.",
      "It works with the engine stopped or cranking. Above about 500 rpm",
      "on a 60-2 there is no time between teeth to program flash: the Burn",
      "is REFUSED (livePauseReason 3), the previous record stays valid and",
      "the edits stay live - stop the engine and Burn again.",
      "A reset, a disconnect or an NVM error during a Burn is a STOP",
      "condition, not normal behaviour.",
      "",
      "nvmSource low byte: 2 or 3 = a committed FLASH record (slot A/B),",
      "1 = STANDBY (battery-backed RAM only), 0 = compiled defaults."],
     ["nvmState", "nvmError", "nvmSource", "nvmGeneration", "nvmCommits",
      "nvmAttempts", "nvmFailWord", "nvmFailExp", "nvmFailGot",
      "nvmFailGot2", "nvmProgFlags", "nvmRetries", "nvmPollMin",
      "nvmPollMax", "nvmCommitStage", "nvmCommitLastStage",
      "nvmCommitFailStage", "releaseId", "cfgSource", "cfgStateBits",
      "cfgBurns", "cfgWrites", "ramBad"]),
    ("hcDiagBurnReset", "Burn forensics: reset log",
     ["Developer record of the last Burn and the last reset, kept across",
      "resets. Record it before burning, resetting or power-cycling again.",
      "Stages and flags are defined in the calibration-storage and boot",
      "code (hcnvm.c, hcmain_me711.c)."],
     ["bfBurnEpoch", "bfBootEpoch", "bfFlags", "bfCurrentStage",
      "bfLastStage", "bfFailStage", "bfFailureReason", "bfNvmState",
      "bfNvmPhase", "bfNvmResult", "bfNvmCell", "bfNvmPos",
      "bfNvmAttempts", "bfWriterResult", "bfNvmRetries", "bfNvmError",
      "bfFailWord", "bfFailExp", "bfFailGot", "bfFailGot2", "bfPollMin",
      "bfPollMax", "bfHctsInitCount", "bfCfgBurnsBeforeInit",
      "bfCfgWritesBeforeInit", "bfRawResetCause", "rstPreviousStage",
      "rstPreviousTrap", "rstPreviousTrapMs", "rstPreviousWdtServices",
      "rstPreviousTarget0", "rstPreviousTarget1", "rstPreviousTarget2",
      "rstPreviousTarget3", "rstPreviousTarget4", "bfRecordPresent"]),
    ("hcDiagLiveBurn", "Burn forensics: live Burn",
     ["Developer view of a Burn in progress: admission windows, flash writer,",
      "interrupt and I/O chip safety. To exercise it, edit the persistence",
      "test byte and press Burn; closing this dialog does not Burn.",
      "Status: READY / PROGRAMMING / PAUSED / REJECTED / DURABLE SUCCESS / FAILED."],
     ["releaseId", "nvmState", "liveBurnError", "liveGeneration", "liveCommits",
      "liveAttempts", "nvmSlot", "liveWordsTotal", "liveWordsCompleted",
      "liveWordsRemaining", "liveCurrentWord", "liveOwner", "liveAdmission",
      "livePauseReason", "liveWindowsOk", "liveWindowsRejected", "liveDeadlineMs",
      "livePredictedMs", "liveHorizonUs", "liveWriterEntries", "liveWriterSuccess",
      "liveWriterFail", "liveMaxPollTicks", "liveMask", "livePendingBefore",
      "livePendingAfter", "liveVectorViolations", "liveAsicState", "liveAsicAgeMs",
      "livePec0Remaining", "livePec4Remaining", "liveSscCon", "liveAsicDenied",
      "liveAsicOverdue", "liveSscErrors", "liveRpm"]),
    ("hcDiagRamProbe", "External SRAM execution probe",
     ["Developer check that this board can run code from external RAM,",
      "which the flash writer (Burn) relies on. It writes no flash, drives",
      "no pin and changes no calibration; the engine must be stopped.",
      "",
      "Each button copies a small routine with a loop and a branch into",
      "the writer's RAM region, calls it and checks the answer.",
      "",
      "ramProbe low byte: 0 never run, 2 PASS, 3 wrong answer, 4 no",
      "signature, 5 RAM unusable, 6 refused (engine turning).",
      "A result stuck at 1 (running) after a reset means this board",
      "cannot run code from external RAM: do not Burn.",
      "",
      "Use two different seeds."],
     ["ramProbe", "ramProbeSeed", "ramProbeResult", "ramBad"]),
    ("hcDiagNativeIo", "Wideband, boost valve and key-off",
     ["Lambda reads 0 whenever it is not a measurement; lam1Why / lam2Why",
      "say why (0 = valid). The boost valve (cavity 104) and the wideband",
      "heaters are switched through the I/O chip every 10 ms."],
     ["lambda1X1000", "lambda1Valid", "heater1State", "heaterDuty",
      "cj1Diag", "cj120Reg1", "cj120Ident", "cj120Xfers", "o2Pre1Volts",
      "lambda2X1000", "lambda2Valid", "heater2State",
      "lam1RiX10", "lam1Fault", "lam1Veff", "lam1UaZero", "lam1UrCal",
      "lam1UrRaw", "lambda1Pump", "lambda1CalOk", "lamMode",
      "lam2RiX10", "lam2Fault", "lam2Veff", "lam2UaZero", "lam2UrCal",
      "lam2UrRaw", "lambda2Pump", "lambda2CalOk",
      "lam1IpUa", "lam2IpUa", "heater1Duty", "heater2Duty", "cj2Diag",
      "lam1Why", "lam2Why", "cj1Err", "cj2Err", "cj1Tmo", "cj2Tmo",
      "boostReqX10", "boostCmdX10", "boostTargetX10", "boostState",
      "boostPX10", "boostIX10", "boostDX10", "boostOpenX10", "boostCuts",
      "asicOutMask", "asicImgP7P8",
      "kl15Status", "runOnState", "keyOff", "runOnAsserted", "runOnMs",
      "runOnCount", "mainRelayBound", "relayFeedV"]),
    # hcDiagDtc: V97 (2026-09-30) moved to gen_ts_ux_me711 - a readable
    # P-code list instead of eight raw integers.
    ("hcDiagSensors", "Sensors and inputs",
     ["halAinMask has one bit per analog input: 1 means this board really",
      "reads it. A dark bit means 'no source', not a fault."],
     ["halAinMask", "sensorErr", "cfgRouteRouted", "cfgRouteMismatch",
      "tpsX10", "tps2X10", "pedalX10", "pedal2X10", "baroRaw",
      "ambientVoltage", "ambientPressure", "tps1Voltage", "tps2Voltage",
      "app1Voltage", "app2Voltage", "s5500Base", "s5500Idx",
      "cltDc", "cltRawAsic", "iatDc", "iatRawAsic", "mapKpaX10",
      "adc14_DSS", "o2Pre1Volts", "o2Pre2Volts", "kl15Status"]),
    ("hcDiagPlatform", "Communication and ECU link",
     ["Boot, serial link and I/O chip link. rxHwOvr and rxOvf count",
      "bytes that were actually lost."],
     ["bootStage", "tickMs", "loopCount", "frames", "calTicks", "cfgSource",
      "ramBad", "rxBytes", "rxReqs", "rxResync", "rxHwOvr", "rxFrameErr",
      "rxOvf", "rxEchoLost", "linkRate", "linkLocked", "linkSwitches",
      "kwpPhase", "kwpInits", "kwpCounts",
      "badVec", "asicState", "asicRunOk",
      "asicCsumErr", "asicTimeouts", "asicSscErr", "cfgWrites", "cfgBurns",
      "cfgFaults", "cfgValidation", "cfgWarnings", "cfgDirtyGroups",
      "cfgDesiredRev", "cfgActiveRev", "cfgApplyRefused", "cfgStateBits",
      "cfgFirstBadOffset", "mainRelayMode", "mainRelayCommand",
      "mainRelayBound", "mainRelayFbValid", "mainRelayMismatch"]),
]


def crosscheck():
    """Every put16() offset in the firmware must appear here, and vice versa."""
    fw = set()
    for m in re.finditer(r"put16\(\s*(\d+)\s*,", main_c):
        fw.add(int(m.group(1)))
    # V79: the far module hcio711.c writes its own words (it cannot call
    # put16 - a near routine), with och16(<offset>u, ...).
    io_c = (TDIR / "asic/hcio711.c").read_text(errors="replace")
    dl_c = (TDIR / "engine/hcdeadline_plan711.c").read_text(errors="replace")
    load_c = (TDIR / "engine/hcload711.c").read_text(errors="replace")
    # Compact bounded serializers, checked against their actual loop forms.
    for source, writer in ((dl_c,"diag_put"),(load_c,"put")):
        compact = re.sub(r"\s+","",source)
        for m in re.finditer(r"for\(i=0;i<(\d+)u;i\+\+\)"+writer+r"\(\(unsignedint\)\((\d+)u\+2u\*i\)",compact):
            fw |= {int(m[2])+2*i for i in range(int(m[1]))}
        for m in re.finditer(r"\b"+writer+r"\((\d+)u,",source): fw.add(int(m[1]))
    compact = re.sub(r"\s+","",dl_c)
    if "for(b=0;b<8u;b++)" in compact:
        for m in re.finditer(r"diag_put\(\(unsignedint\)\((\d+)u\+8u\*b\)",compact):
            fw |= {int(m[1])+8*b for b in range(8)}
    if "for(b=0;b<8u;b++)" in compact and "for(i=0;i<6u;i++)diag_put((unsignedint)(1286u+14u*b+2u*i),p[i]);" in compact and "diag_put((unsignedint)(1298u+14u*b),D.inj[b].flags);" in compact:
        fw |= {1286+14*b+2*i for b in range(8) for i in range(7)}
    for m in re.finditer(r"och16\(\s*(\d+)u?\s*,", io_c):
        fw.add(int(m.group(1)))
    # Derive the bias/diagnosis window from the loop itself. A literal match on
    # one exact loop form went stale the moment an index was appended (the
    # supported-range words 63..67): the firmware published 1530..1597 while
    # this said 1588, and the build's own ochBlockSize check caught it.
    m = re.search(r"for\(j=(\d+)u;j<=(\d+)u;j\+\+\)\s*och16\((\d+)u\+2u\*\(j-\1u\)"
                  r",hc_etbcal_value\(j\)\);", io_c)
    if m:
        lo, hi, base = int(m[1]), int(m[2]), int(m[3])
        fw |= {base + 2 * (j - lo) for j in range(lo, hi + 1)}
    for m in re.finditer(r"put32\(\s*(\d+)\s*,", main_c):
        base = int(m.group(1))
        fw |= {base, base + 2}
    # V97: the knock driver writes the OCH2 region (1024..) itself: o16 /
    # o8 with literal offsets, and one loop over the eight cylinders.
    kn_c = (TDIR / "engine/hcknock711.c").read_text(errors="replace")
    for m in re.finditer(r"\bo16\(\s*(\d+)u\s*,", kn_c):
        fw.add(int(m.group(1)))
    for m in re.finditer(r"\bo16\(\(unsigned int\)\((\d+)u \+ 2u \* i\)",
                         kn_c):
        fw |= {int(m.group(1)) + 2 * i for i in range(8)}
    for m in re.finditer(r"\bo8\(\(unsigned int\)\((\d+)u \+ i\)", kn_c):
        fw |= {int(m.group(1)) + i for i in range(8)}
    # V98: the engine-control layer (hcengctl711.c) - och(<offset>u, ...)
    ec_c = (TDIR / "engine/hcengctl711.c").read_text(errors="replace")
    for m in re.finditer(r"\boch\(\s*(\d+)u\s*,", ec_c):
        fw.add(int(m.group(1)))
    # V99: the event ring / vehicle-test telemetry (hcevlog711.c)
    ev_c = (TDIR / "diagnostics/hcevlog711.c").read_text(errors="replace")
    for m in re.finditer(r"\boch_set\(\s*(\d+)u\s*,", ev_c):
        fw.add(int(m.group(1)))
    # V97: the VVT module, one block of five words per cam
    vv_c = (TDIR / "control/hcvvt711.c").read_text(errors="replace")
    for m in re.finditer(r"\bo16\(\(unsigned int\)\((\d+)u \+ 10u \* b\)",
                         vv_c):
        fw |= {int(m.group(1)), int(m.group(1)) + 10}
    # Channels emitted from a `for` loop rather than one call per offset.
    # Generalised from a single hardcoded base to ANY base: the V20 runtime
    # block adds a second such loop (the S5500 correlation window at 176), and
    # a crosscheck that only knew about the first would have reported the
    # second as ".ini offsets not in the firmware" - i.e. it would have failed
    # on correct code, which is the fastest way to teach somebody to ignore it.
    for m in re.finditer(r"put16\(\(unsigned int\)\((\d+) \+ 2 \* i\)",
                         main_c):
        base = int(m.group(1))
        fw |= {base + 2 * i for i in range(16)}
    # V45 emits its retained-record OCH block through two checked source maps
    # in update_forensics_live(), avoiding 63 duplicated call sites.  The
    # maps are the executable offset contract; insist on both the call and
    # every contiguous word it owns rather than pretending direct literals are
    # the only auditable form of a firmware writer.
    # The publication is sliced: part 0 writes the burn-forensics map
    # (480..551), part 1 the reset-log map (552..603). Both must be called.
    if "update_forensics_live();" in main_c or (
            "update_forensics_live(0u);" in main_c
            and "update_forensics_live(1u);" in main_c):
        fw |= set(range(480, 604, 2))
    ini = set()
    for o, _name, kind, *_rest in CH:
        ini.add(o)
        if kind == "U32":
            ini.add(o + 2)
    missing = sorted(fw - ini)
    extra = sorted(ini - fw)
    if missing or extra:
        print("  offsets in the firmware but not the .ini:", missing)
        print("  offsets in the .ini but not the firmware:", extra)
        raise SystemExit("channel offsets have drifted - fix one or the other")
    top = max(ini) + 2
    if top > OCH_SIZE:
        raise SystemExit(f"channels run to {top} but TGT_OCH_SIZE is {OCH_SIZE}")

    # Derived expressions are hand-authored even though the file is
    # generated. Catch misspelled channel names here; otherwise TunerStudio
    # quietly loads a broken expression (exactly what happened when the first
    # APP/TPS voltage views used Bosch net names instead of the emitted names).
    known = {name for _off, name, *_rest in CH}
    # A derived channel may also read a scalar PAGE constant - the cfg*
    # fuel-model descriptions do (Speeduino's own idiom, `strokeMultipler =
    # { twoStroke == 1 ? 1 : 2 }`). Arrays are not addressable this way.
    known |= {f.meta.ts for f in UI.MODEL.resolve()[0] if f.count == 1}
    for name, expression, _units, _desc in DERIVED_CH:
        refs = set(re.findall(r"[A-Za-z_]\w*", expression))
        missing_refs = sorted(refs - known)
        if missing_refs:
            raise SystemExit(f"derived channel {name} has unknown refs: "
                             f"{missing_refs}")
        known.add(name)
    return top


# Development-history tags (V45, V97, V98r2, ...) in channel descriptions say
# WHEN something changed, which is the release record's job, not the
# project file's. The descriptions keep them in this source; the generated
# [OutputChannels] comments do not.
_VER = r"V\d{2,3}[a-z]?\d?"


def public_comment(c: str) -> str:
    c = c.strip()
    c = re.sub(r"\s*Until " + _VER + r"[^.]*\.", "", c)
    c = re.sub(r"\s*\(" + _VER + r"(?: layout)?\)", "", c)
    c = re.sub(r"\(" + _VER + r"[,:]?\s+", "(", c)
    c = re.sub(r"(^|[.;]\s+)" + _VER + r":?\s+", r"\1", c)
    c = re.sub(r"\bRETIRED " + _VER, "RETIRED", c)
    c = re.sub(r"\b" + _VER + r"\s+(?=[a-z])", "", c)
    c = re.sub(r"\s{2,}", " ", c)
    for a, b in ((" :", ":"), (" ;", ";"), (" ,", ","), ("( ", "("),
                 (" )", ")")):
        c = c.replace(a, b)
    c = re.sub(r"(\. )([a-z])", lambda m: m.group(1) + m.group(2).upper(), c)
    return c.strip()


def public_och_comments(lines):
    out, sec = [], None
    for ln in lines:
        if ln.startswith("["):
            sec = ln.strip()
        if sec == "[OutputChannels]" and ";" in ln and not ln.lstrip().startswith(";"):
            head, _sep, tail = ln.partition(";")
            ln = head + "; " + public_comment(tail)
        out.append(ln)
    return out


# THE USER PROJECT LEAVES OUT THE DEVELOPER PAGES. These open firmware
# internals - the I/O chip window, the external-RAM probe, the Burn forensic
# records, the executor's command telemetry, the page's own housekeeping
# words - that no tuner or installer needs. They stay in the forensic project
# (OUT_FORENSIC), which is the same file with the extended channel block.
DEV_ONLY = ("hcBench", "hcCtrlS5500Dlg", "hcS5500", "hcDiagRamProbe",
            "hcDiagLiveBurn", "hcDiagBurnReset", "hcDiagDeadline",
            "hcDiagInjectorPulses", "hcCtrlDlg")


def user_project(lines, dev_only=DEV_ONLY):
    """`lines` minus the developer menu entries and every [UiDialogs] block
    only they reach. Blocks the developer pages share with user pages stay."""
    blk_re = re.compile(r"^ {3}(dialog|indicatorPanel|readoutPanel|help)\s*=\s*(\w+)")
    menu_re = re.compile(r"^\s*(?:subMenu|groupChildMenu)\s*=\s*(\w+)")
    sec, blocks, cur = None, {}, None
    for i, ln in enumerate(lines):
        if ln.startswith("["):
            sec, cur = ln.strip(), None
            continue
        if sec != "[UiDialogs]":
            continue
        m = blk_re.match(ln)
        if m:
            cur = m.group(2)
            blocks[cur] = {"kind": m.group(1), "start": i, "end": i + 1,
                           "kids": set()}
            continue
        if cur:
            blocks[cur]["end"] = i + 1
            m = re.match(r"^\s*panel\s*=\s*(\w+)", ln)
            if m:
                blocks[cur]["kids"].add(m.group(1))
    refs = [m.group(1) for ln in lines for m in [menu_re.match(ln)] if m]

    def reach(roots):
        seen, work = set(), list(roots)
        while work:
            b = work.pop()
            if b not in seen:
                seen.add(b)
                work.extend(blocks.get(b, {}).get("kids", ()))
        return seen
    full = reach(refs)
    user = reach(r for r in refs if r not in dev_only)
    drop = {b for b in full - user
            if b in blocks and blocks[b]["kind"] != "help"}
    missing = set(dev_only) - full
    if missing:
        raise SystemExit("DEV_ONLY names pages the menu does not reach: %s"
                         % sorted(missing))
    gone = set()
    for b in drop:
        gone.update(range(blocks[b]["start"], blocks[b]["end"]))
    out = []
    for i, ln in enumerate(lines):
        if i in gone:
            continue
        m = menu_re.match(ln)
        if m and m.group(1) in dev_only:
            continue
        out.append(ln)
    # A group whose children all left, and separators that now separate
    # nothing, go too.
    res = []
    for i, ln in enumerate(out):
        s = ln.strip()
        if s.startswith("groupMenu"):
            nxt = out[i + 1].strip() if i + 1 < len(out) else ""
            if not nxt.startswith("groupChildMenu"):
                continue
        res.append(ln)
    out, res = res, []
    for i, ln in enumerate(out):
        s = ln.strip()
        if s == "subMenu = std_separator":
            prev = res[-1].strip() if res else ""
            nxt = out[i + 1].strip() if i + 1 < len(out) else ""
            if (prev.startswith("menu =") or prev == "subMenu = std_separator"
                    or nxt.startswith("menu =") or not nxt):
                continue
        res.append(ln)
    # The commands only those pages' buttons send go with them.
    btn = re.compile(r'^\s*commandButton\s*=\s*"[^"]*"\s*,\s*(\w+)')
    pressed = lambda ls: {m.group(1) for ln in ls for m in [btn.match(ln)] if m}
    gone_cmds = pressed(lines) - pressed(res)
    out, sec = [], None
    for ln in res:
        if ln.startswith("["):
            sec = ln.strip()
        m = re.match(r"^(\w+)\s*=", ln)
        if sec == "[ControllerCommands]" and m and m.group(1) in gone_cmds:
            continue
        out.append(ln)
    return out


def label(text: str) -> str:
    """A dialog line that is text only.

    It exists so that the generator CANNOT emit an unterminated string, which
    is exactly what reached hardware: TunerStudio read the missing closing
    quote as a string running on into the following lines and the whole dialog
    stopped working. A quote inside the text would do the same thing, so it is
    refused here rather than escaped - no label in this file needs one."""
    if '"' in text:
        raise SystemExit("dialog label must not contain a quote: %r" % text)
    return '      field = "%s"' % text


DERIVED_CH += [
    ("sweepPrimary", "{ (sweepFindings & 64) != 0 ? 1 : (sweepFindings & 1) != 0 ? 2 : sweepBiasState == 6 ? 3 : (sweepFindings & 2) != 0 ? 4 : (sweepFindings & 4) != 0 ? 5 : (sweepFindings & 256) != 0 ? 8 : (sweepFindings & 128) != 0 ? 9 : 0 }", "", "Primary on-ECU finding priority"),
    ("sweepSecondary", "{ sweepPrimary != 4 && (sweepFindings & 2) != 0 ? 4 : sweepPrimary != 8 && (sweepFindings & 256) != 0 ? 8 : sweepPrimary != 9 && (sweepFindings & 128) != 0 ? 9 : 0 }", "", "Secondary characterization finding"),
    # THE ACTION FOLLOWS THE PROPOSAL'S ACTUAL STATE: it never says "Save"
    # while the Save is refused (that contradiction reached the bench).
    ("sweepAction", "{ sweepBiasState == 2 ? 10 : sweepPrimary == 1 ? 1 : sweepPrimary == 2 ? 2 : sweepBiasState == 1 ? 4 : (sweepPrimary == 3 || sweepPrimary == 4) && sweepBiasState >= 4 ? 11 : sweepPrimary }", "", "Recommended next action"),
    ("sweepTarget", "{ etbCalRest1 * 0.1 }", "%", "Characterization effective target"),
    ("sweepActual", "{ etbCalA1 * 0.1 }", "%", "Characterization actual TPS"),
    ("sweepMotor", "{ (etbCalB1 > 32767 ? etbCalB1 - 65536 : etbCalB1) * 0.1 }", "%", "Characterization signed motor duty"),
    ("sweepP", "{ (etbCalA2 > 32767 ? etbCalA2 - 65536 : etbCalA2) * 0.1 }", "%", "Characterization P contribution"),
    ("sweepI", "{ (etbCalB2 > 32767 ? etbCalB2 - 65536 : etbCalB2) * 0.1 }", "%", "Characterization I contribution"),
    ("sweepD", "{ (etbCalRest2 > 32767 ? etbCalRest2 - 65536 : etbCalRest2) * 0.1 }", "%", "Characterization D contribution"),
    ("sweepFf", "{ (etbDrive > 32767 ? etbDrive - 65536 : etbDrive) * 0.1 }", "%", "Characterization bias contribution"),
    ("sweepIntegral", "{ dbwInteg * 0.1 }", "%", "Integral duty contribution in engineering units"),
    ("sweepRequested", "{ etbCalDetail * 0.1 }", "%", "Production mapped/clamped target before rate limiter during sweep"),
    ("sweepSegment", "{ etbPhaseMs }", "", "1..37 bounded characterization, 38..59 driver demand"),
    ("sweepBoundRms", "{ etbTuneAmpX10 }", "%", "Bounded section RMS; frozen before pedal slams"),
    ("sweepBoundSat", "{ etbTuneTuMs * 0.1 }", "%", "Bounded section saturation"),
    ("sweepVbatMin", "{ etbTuneAmpLiveX10 }", "V", "Minimum fresh measured VBAT"),
    ("sweepVbatMax", "{ etbTuneTuLiveMs * 0.1 }", "V", "Maximum fresh measured VBAT"),
    ("sweepSlamSettle", "{ etbTuneKp }", "ms", "Pedal slam worst settle"),
    ("sweepSlamOver", "{ etbTuneKi * 0.1 }", "%", "Pedal slam worst overshoot"),
    ("sweepSlamSteady", "{ etbTuneKd * 0.1 }", "%", "Pedal slam worst steady error"),
    ("sweepPairWorst", "{ etbTuneCycles * 0.1 }", "%", "Worst coherent normalized TPS pair disagreement"),
]

def main() -> int:
    top = crosscheck()
    ui_fields, ui_by_ts, _ui_consts = UI.layout()
    L = []
    w = L.append

    w("; hanicore_me711.ini - GENERATED by tools/tunerstudio/gen_ts_ini_me711.py.")
    w("; Do not edit by hand: every offset is cross-checked against the")
    w("; firmware's own put16() calls, and an edit here would be silently lost.")
    w(";")
    w("; Engine firmware for the Bosch ME7.1.1: this page drives injectors,")
    w("; coils, the throttle and the pump.")
    w(";")
    # V97: THE 2-D TABLE ORDER, declared so me711_migrate_calibration.py can
    # tell a [load][rpm] page from an older [rpm][load] one (it transposes).
    w("; tableOrder = %s" % UI.GEN.TABLE_ORDER)
    w("")
    # QUERYCOMMAND MUST NOT BE "Q". Real-hardware K-line tracing of V23 (which
    # DID already carry messageEnvelopeFormat, below) showed TunerStudio
    # completing a byte-perfect, CRC-valid enveloped 'Q' exchange - correct
    # length, correct content, correct zlib CRC32, verified against the same
    # no-null-terminator convention the known-working ME7.5 reference uses
    # for its own enveloped 'S' reply (tools/ts_bridge.log, both targets'
    # shared hcts.c) - and then STILL waiting ~1.5 s and restarting from 'F'
    # forever, never once sending 'V'/'P'/'R'. The known-good ME7.5 trace, by
    # contrast, sends F once, then S/V/P/R exactly once each before settling
    # into continuous O/R polling - no loop.
    #
    # The one remaining difference is the LETTER: ME7.5's queryCommand is
    # "S"; this generator emitted "Q". rusEFI's own protocol reference
    # (rusEFI firmware/console/binary/tunerstudio.cpp,
    # handlePlainCommand()) documents 'Q' as a SEPARATE, TunerStudio-
    # HARDCODED byte used for blind multi-port ECU scanning - independent of
    # whatever a project's own .ini declares as queryCommand. Declaring the
    # project's queryCommand as "Q" too means every real handshake reply
    # looks, to TunerStudio's own client-side state machine, like just
    # another scan probe answering - so it never registers "connected, now
    # run the project's command sequence" and keeps scanning (F, Q, F, Q...)
    # forever. hcts.c already answers 'S' and 'Q' identically in both the
    # plain and CRC-enveloped paths (see handle_plain()/handle(), both
    # `case 'S': case 'Q':`), so this costs no firmware change at all.
    w("[MegaTune]")
    w("   MTversion      = 2.25")
    w('   queryCommand   = "%s"' % QUERY_CMD)
    w('   signature      = "%s"' % SIGNATURE)
    w("")
    w("[TunerStudio]")
    w("   iniSpecVersion = 3.30")
    w('   queryCommand   = "%s"' % QUERY_CMD)
    w('   versionInfo    = "V"')
    w('   signature      = "%s"' % SIGNATURE)
    # V97: CELSIUS BY DEFAULT. TunerStudio 3.3.01 defaults this flag to TRUE
    # (G.F field `an`, set by `useLegacyFTempUnits`); with it true and no
    # CELSIUS setting in the file, every dashboard gauge whose units end in
    # "C" is relabelled deg F on load (dashboard.aa.b(): setUnits(... "F")) -
    # the value stays Celsius, only the label lies, on every new project.
    # rusEFI ships the same line for the same reason.
    w("   useLegacyFTempUnits = false")
    # V98: A K-LINE ECU, NOT USB. TunerStudio reads only the byte ranges the
    # active gauges and the datalog name, merging ranges closer than this
    # (rusEFI #5927: 1000 is for USB, a small value for slow links). The
    # datalog's tuning core is contiguous (the fast block, 1136..1199), so a
    # log is one read. docs/TUNERSTUDIO.md.
    w("   maxUnusedRuntimeRange = 32")
    w("   defaultRuntimeRecordPerSec = 25")
    w("")
    w("[Constants]")
    # messageEnvelopeFormat is what selects the CRC envelope protocol at all -
    # see tunerstudio/hanicore_dc_0512.ini, the KNOWN-WORKING ME7.5
    # reference this generator was diffed against. It was missing entirely
    # before V23; V23's real-hardware trace confirms TunerStudio DOES pick it
    # up correctly (it sends a byte-perfect CRC-enveloped query), so this half
    # of the original diagnosis was necessary but - as that same trace showed
    # - not sufficient on its own. See queryCommand above for the rest of it.
    w("   messageEnvelopeFormat = msEnvelope_1.0")
    w("")
    w("   endianness     = big")
    w("   nPages         = 1")
    w("   pageSize       = %d" % PAGE_SIZE)
    # A plain fixed 2-byte page id, exactly like the ME7.5 reference -
    # NOT "\$tsCanId\x50". That macro is TunerStudio's CAN-multiplexing
    # template: it substitutes a live CAN-bus ID byte into every page
    # command, which has no meaning on a plain K-line serial link and was
    # never something hcts.c's parser was written to expect.
    w("   pageIdentifier = \"\\x00\\x00\"")
    w("   pageReadCommand = \"R%2o%2c\"")
    w("   burnCommand     = \"B\"")
    w("   pageActivate    = \"P\"")
    w("   pageValueWrite  = \"W%2o%v\"")
    w("   pageActivationDelay = 100")
    # THE BURN REPLY IS DELIBERATELY DEFERRED, SO THIS IS NOT A FREE NUMBER.
    #
    # 1500 ms was under the Burn's own wall time and real TunerStudio 3.3.01
    # said so on 2026-09-13: "Burn Page 0 failed" - while the ECU went on to
    # commit the record correctly and the change survived a restart. TS had
    # simply stopped waiting.
    #
    # MEASURED on this ECU: send -> complete TS_OK envelope = 3.07 s, because
    # hcts_defer_response() holds the reply until the DONE marker has been read
    # back out of the device, the store rescanned and the live source
    # reselected. TS_OK means "it is in flash and this ECU is ready for your
    # next request", and that guarantee is the whole point of V40.
    #
    # The firmware's own ceiling is TGT_LIVE_BURN_DEADLINE_MS - 6000 ms since
    # V56, read out of hctarget.h below rather than repeated here - plus that
    # verify tail, so the client must be willing to wait past it or it can
    # report a failure for a Burn that succeeded. THE NUMBER IS DERIVED FROM
    # THE FIRMWARE'S DEADLINE, because a hand-copied one is how the V48 .ini
    # came to be carrying 1500 ms against a firmware that may legitimately take
    # 5.1 s at 500 rpm.
    #
    # rusEFI's corpus uses 3000 in 39 of its 40 generated files and calls it
    # "Milliseconds general timeout" - ample for a writer that does not defer
    # its reply, and still short for ours. This is a deliberate, documented
    # deviation from the corpus for a concrete reason, per the project rules.
    # It is a GENERAL timeout, so the cost is that a dead link takes 8 s rather
    # than 1.5 s to report - acceptable on a bench tool, and far better than
    # telling a tuner their Burn failed when it did not.
    w("   blockReadTimeout    = %d" % BLOCK_READ_TIMEOUT_MS)
    w("   interWriteDelay     = 10")
    w("   blockingFactor      = %d" % BLOCKING)
    w("")
    w("page = 1")
    # EVERY FIELD THE MODEL KNOWS ABOUT, and not one offset typed here.
    #
    # This used to expose five: cfgVersion, cylinders, outputsArmedCfg and the
    # two main-relay words, on the argument that "a bench-safe .ini should not
    # offer knobs the firmware cannot act on". That argument stopped being true
    # when the universal configuration landed - the firmware acts on all 207 of
    # them, hc_validation.c checks them, and the apply-policy machinery decides
    # when each one reaches the running engine. What was left was an ECU whose
    # VE table, spark map, trigger pattern, injector flow, pin routing and both
    # lambda channels could not be reached from TunerStudio at all.
    #
    # The offsets come from hcconfig.h through the model, which REFUSES to
    # resolve if the two disagree - see tools/tunerstudio/gen_ts_ui_me711.py.
    for line in UI.page_lines(ui_fields):
        w(line)
    w("")
    w("[OutputChannels]")
    w("   ochGetCommand  = \"O%2o%2c\"")
    w("   ochBlockSize   = %d" % OCH_SIZE)
    w("")
    for off, name, kind, units, desc in CH:
        scale = SCALE.get(off, 1)
        translate = TRANSLATE.get(off, 0)
        w('   %-16s = scalar, %s,  %3d, "%s", %s, %s    ; %s'
          % (name, kind, off, units, scale, translate, desc))
    w("")
    for name, expression, units, desc in DERIVED_CH:
        w('   %-16s = %-32s ; %s [%s]' %
          (name, expression, desc, units or "dimensionless"))
    for mask, name in SENSOR_BITS:
        w('   %-16s = { (sensorErr & %d) > 0 }' % (name, mask))
    w('   sensorsValid     = { sensorErr == 0 }')
    w("")
    for bit, name, desc in STATUS_BITS:
        w('   %-16s = { (status & %d) > 0 }   ; %s' % (name, 1 << bit, desc))
    # V84: there is no user arm. What a tuner needs to see is whether the
    # platform currently PERMITS outputs - outputAuthority bit 1 is
    # hc_dbw_allowed, i.e. the ALWAYS set clear (S5500 link, valid page, key
    # on, not BENCH_SAFE). Spark and fuel additionally need crank sync, which
    # crankSync already shows.
    w('   %-16s = { (outputAuthority & 2) > 0 }   ; %s'
      % ("outputsPermitted", "link up, page valid, key on (V84: no user arm)"))
    w("")
    # ================================================= [PcVariables] =======
    # THE NAMES THE FIRMWARE ALREADY HAS. rusEFI's shape exactly -
    # rusefi_proteus_f7.ini:4189 declares `fuelIgnCutCodeList = bits, U08,
    # [0:7], "None", ...` here and uses it at :6099 through
    # bitStringValue(list, channel). HaniCore used [PcVariables] zero times and
    # bitStringValue zero times before Stage A, which is why 111 named states
    # reached the tuner as bare integers.
    #
    # EVERY VALUE IS PARSED OUT OF THE FIRMWARE HEADER. Only the wording is
    # authored, and ts_semantics_me711.check() fails the build if a constant
    # gains a value nobody worded - see tools/tunerstudio/ts_semantics_me711.py.
    w("[PcVariables]")
    for line in SEM.index_list_lines():
        w(line)
    for name, values in (
        ("hcSweepIssueList", ["No issue within profile", "TPS / sensor", "Output authority", "Mechanical / hysteresis", "Feedforward / bias", "Likely P response", "Integral recovery", "Derivative / noise", "Inconclusive response", "Target rate limit"]),
        ("hcSweepActionList", ["Review traces; rerun after any change", "Restore healthy TPS before further tests", "Check bridge, supply and duty limits", "Inspect spring/friction; do not fit hysteresis", "Review proposed feed-forward; Save to RAM and rerun", "Review P only after bias/authority checks", "Review holding bias and integral recovery", "Inspect TPS noise and derivative traces", "Inspect error and controller terms", "Review target slew before changing PID", "Rerun now; compare; Burn only if it improved", "Proposal refused - see reason; do not Save"]),
        ("hcSweepBiasList", ["No complete run", "READY - review current/proposed values", "SAVED TO RAM - REVIEW / BURN REQUIRED", "Run in progress", "REFUSED - sensor / output fault or abort", "REFUSED - a position lacks its break-away trials", "REFUSED - opening edge not above closing edge", "REFUSED - no break-away within duty authority", "REFUSED - calibration changed; rerun", "REFUSED - unsupported correction / no change", "REFUSED - calibration validation failed", "REFUSED - position would not settle", "REFUSED - break-away not repeatable", "REFUSED - plate moved against the ramp"]),
    ):
        labels = values + ["INVALID"] * (16-len(values))
        w("   " + name + " = bits, U08, [0:3], " + ", ".join('"'+v+'"' for v in labels))
    w(dtc_list_line())
    w(dtc_row_list_line())
    w(cfg_field_list_line())
    for _name, _labels in LOAD_AXIS_LISTS:
        top = 1
        while (1 << top) < len(_labels):
            top += 1
        pad = _labels + ["INVALID"] * ((1 << top) - len(_labels))
        w("   %-20s = bits, U08, [0:%d], %s"
          % (_name, top - 1, ", ".join('"%s"' % x for x in pad)))
    # V98: WUE Analyze's working arrays (rusEFI / Speeduino), TunerStudio-only
    w('   wueAnalRecommend = array, U08, [16], "%", 1, 0, 0, 255, 0')
    w('   wueAfrTargetOffset = array, S16, [16], "lambda", 0.001, 0, -0.2, 0.2, 3')
    w("")
    w("[GaugeConfigurations]")
    curated = set()
    # V98 (bug B8): every gauge goes into a CATEGORY of the right-click
    # picker (ts_gauges_me711.CATEGORY_ORDER) with a plain title; the lists
    # below and GM.GAUGE_META give titles and ranges, everything else gets a
    # humanised title and its scale's range.
    gspec = {}
    for name, title, units, lo, hi in [
        ("bootStage", "Boot stage", "", 0, 12),
        ("tickMs", "System tick", "ms", 0, 65535),
        ("calTicks", "T7 ticks/byte", "tick", 0, 1300),
        ("battery", "Battery", "V", 0, 17),
        ("ambientPressure", "Onboard baro sensor", "hPa", 300, 1300),
        ("ambientPressureBar", "Onboard baro sensor", "bar", 0, 2),
        ("baroRaw", "Onboard baro sensor raw", "cnt", 0, 1023),
        ("ambientVoltage", "Onboard baro sensor voltage", "V", 0, 5),
        ("ambientUsed", "Ambient pressure used", "kPa", 0, 130),
        ("ambientAgeSeconds", "Ambient reading age", "s", 0, 3600),
        ("pressureMeasured", "Pressure sensor", "kPa", 0, 400),
        ("densityPressure", "Air density pressure", "kPa", 0, 400),
        ("densityTemperature", "Air density temperature", "K", 230, 400),
        ("densityRatio", "Density vs reference", "", 0, 4),
        ("chargeBlendWeight", "Boost blend weight", "", 0, 1),
        ("veAxisInput", "VE table axis value", "", 0, 400),
        ("leanMeasurement", "Lean protection lambda", "lambda", 0, 2),
        ("app1Voltage", "Pedal 1 voltage", "V", 0, 5),
        ("app2Voltage", "Pedal 2 voltage", "V", 0, 5),
        ("app1Raw", "Pedal 1 raw", "cnt", 0, 1023),
        ("app2Raw", "Pedal 2 raw", "cnt", 0, 1023),
        ("tps1Raw", "TPS1 raw", "cnt", 0, 1023),
        ("tps2Raw", "TPS2 raw", "cnt", 0, 1023),
        ("tps1Voltage", "TPS1 Voltage", "V", 0, 5),
        ("tps2Voltage", "TPS2 Voltage", "V", 0, 5),
        ("tpsX10", "Throttle 1", "%", 0, 100),
        ("tps2X10", "Throttle 2", "%", 0, 100),
        ("pedalX10", "Pedal 1", "%", 0, 100),
        ("pedal2X10", "Pedal 2", "%", 0, 100),
        ("adc00_HFM", "MAF 1 raw", "cnt", 0, 1023),
        ("adc13_HFM2", "MAF 2 raw", "cnt", 0, 1023),
        ("rpm", "Engine speed", "rpm", 0, 8000),
        # ---------------------------------------------------------------
        # THE EIGHT FRONT-PAGE CHANNELS, WITH rusEFI's OWN BANDS.
        #
        # These used to fall through to the "all channels" bucket below,
        # which derives a range from the channel's declared SCALE alone:
        # coolant came out -100..6553 C, battery 0..6553 V, dwell 0..655 ms.
        # A gauge like that is unreadable on a cluster and misleading in a
        # tooltip, and the .dash generator inherits whatever is here.
        #
        # Sources, all rusefi_proteus_f7.ini [GaugeConfigurations]:
        #   CLTGauge   -40..140 C, warn 95, danger 110      (line 5819)
        #   IATGauge   -40..140 C                            (line 5820)
        #   MAPGauge   0..300 kPa, warn 200                  (line 5831)
        #   afr1Gauge  10..19.4, warn 15, danger 16          (line 5822)
        #   VBattGauge 8..21 V, low warn 10, high warn 17    (line 5830)
        #   dwellGauge 0..10 ms, warn 6, danger 8            (line 5907)
        #   correctedIgnAdvGauge -100..100 deg               (line 5906)
        #   TPSGauge   0..100 %                              (line 5964)
        #   baroPressureGauge 0..130 kPa                     (line 5837)
        # ---------------------------------------------------------------
        ("asicState", "ASIC state", "", 0, 6),
        ("asicRunOk", "ASIC runtime frames", "", 0, 1000),
        ("asicRxFrames", "ASIC RX frames", "", 0, 1000),
        ("asicBadFrames", "ASIC bad frames", "", 0, 1000),
        ("asicTimeouts", "ASIC timeouts", "", 0, 1000),
        ("asicSscErr", "ASIC SSC errors", "", 0, 1000),
        ("sensorErr", "Sensor error mask", "", 0, 1023),
        ("badVec", "Stray interrupts", "", 0, 100),
        ("rxHwOvr", "RX register overruns", "", 0, 100),
        ("mainRelayFeedbackVoltage", "Main relay feedback", "V", 0, 29),
        ("mainRelayFeedbackRaw", "Main relay feedback raw", "cnt", 0, 1023),
        ("mainRelayCommand", "Main relay command", "", 0, 1),
        ("crankSync", "Crank Sync", "", 0, 1),
        ("cycleSync", "Cycle Sync", "", 0, 1),
        ("crankToothIndex", "Tooth Index", "", 0, 60),
        # V97: signed, tooth #1 in deg after cylinder-1 TDC (Speeduino's
        # TrigAng range; rusEFI's globalTriggerAngleOffset is minus it)
        ("trigCfgAngleX10", "Trigger angle (tooth #1 ATDC)", "deg", -360, 360),
        ("crankGapPending", "Gap Candidate", "", 0, 1),
        ("syncLossCount", "Sync Loss Count", "", 0, 100),
        ("syncLossReason", "Sync Loss Reason", "", 0, 7),
        ("schedulerQueued", "Near Events", "", 0, 16),
        # The S5500 sweep's own readouts. They are OUTPUT CHANNELS, so the
        # dialog shows them with `gauge =` and never with `field =`.
        ("s5500Base", "S5500 window base", "word", 0, 117),
        ("s5500Idx", "S5500 decode index", "", 0, 65535),
        ("s5500Snaps", "S5500 snapshots", "", 0, 65535),
        ("s5500Plaus", "S5500 all-16 plausible", "", 0, 65535),
    ]:
        gspec[name] = (title, units, lo, hi, lo, lo, hi, hi, 0, 0)
    # The banded ones, where a warning colour is worth having and the decimal
    # places matter. Same tuple as above plus (loDanger, loWarn, hiWarn,
    # hiDanger, valueDigits, labelDigits).
    for name, title, units, lo, hi, ld, lw, hw, hd, vd, lbd in [
        ("cltDc", "Coolant temp", "C", -40, 140, -40, -15, 95, 110, 1, 0),
        ("iatDc", "Intake air temp", "C", -40, 140, -40, -15, 95, 110, 1, 0),
        ("mapKpaX10", "MAP", "kPa", 0, 300, 0, 0, 200, 250, 1, 0),
        ("afrX10", "Target AFR", "", 10, 20, 10, 12, 15, 16, 1, 1),
        ("battDv", "Battery", "V", 8, 21, 8, 10, 17, 19, 1, 1),
        ("dwellX100", "Dwell", "ms", 0, 10, 0, 0, 6, 8, 2, 1),
        ("advX10", "Timing: ignition", "deg", -20, 60, -20, -10, 45, 55, 1, 0),
        ("lambdaTarget", "Target lambda", "", 0.6, 1.4, 0.6, 0.7, 1.1, 1.2,
         3, 2),
        ("rlX10", "Relative charge", "%", 0, 250, 0, 0, 200, 230, 1, 0),
        ("engLoad", "Engine load", "", 0, 250, 0, 0, 200, 230, 1, 0),
        ("injTiUs", "Injector pulse", "us", 0, 25000, 0, 0, 18000, 22000,
         0, 0),
        ("sweepTarget", "Sweep target", "%", 0, 100, 0, 0, 100, 100, 1, 1),
        ("sweepActual", "Sweep actual", "%", 0, 100, 0, 0, 100, 100, 1, 1),
        ("sweepMotor", "Signed motor duty", "%", -100, 100, -100, -100, 100, 100, 1, 1),
        ("sweepP", "Sweep P", "%", -100, 100, -100, -100, 100, 100, 1, 1),
        ("sweepI", "Sweep I", "%", -100, 100, -100, -100, 100, 100, 1, 1),
        ("sweepD", "Sweep D", "%", -100, 100, -100, -100, 100, 100, 1, 1),
        ("sweepFf", "Sweep bias", "%", -100, 100, -100, -100, 100, 100, 1, 1),
        ("sweepIntegral", "Integral duty", "%", -100, 100, -100, -100, 100, 100, 1, 1),
        ("sweepSignedDuty", "Signed motor duty", "%", -100, 100, -100, -100, 100, 100, 1, 1),
        ("sweepRms", "Section RMS", "%", 0, 100, 0, 0, 100, 100, 1, 1),
        ("sweepSaturation", "Section saturation", "%", 0, 100, 0, 0, 100, 100, 1, 1),
        ("sweepRequested", "Requested target", "%", 0, 100, 0, 0, 100, 100, 1, 1),
        ("sweepSegment", "Sweep segment", "", 0, 42, 0, 0, 42, 42, 1, 1),
        ("sweepBoundRms", "Bounded RMS", "%", 0, 100, 0, 0, 100, 100, 1, 1),
        ("sweepBoundSat", "Bounded saturation", "%", 0, 100, 0, 0, 100, 100, 1, 1),
        ("sweepVbatMin", "VBAT minimum", "V", 0, 20, 0, 0, 20, 20, 1, 1),
        ("sweepVbatMax", "VBAT maximum", "V", 0, 20, 0, 0, 20, 20, 1, 1),
        ("sweepSlamSettle", "Slam settle", "ms", 0, 800, 0, 0, 800, 800, 1, 1),
        ("sweepSlamOver", "Slam overshoot", "%", 0, 100, 0, 0, 100, 100, 1, 1),
        ("sweepSlamSteady", "Slam steady error", "%", 0, 100, 0, 0, 100, 100, 1, 1),
        ("sweepPairWorst", "Worst TPS pair error", "%", 0, 20, 0, 0, 20, 20, 1, 1),
        ("dbwTargetX10", "Throttle target", "%", 0, 100, 0, 0, 100, 100, 1, 0),
        ("dbwActualX10", "Throttle actual", "%", 0, 100, 0, 0, 100, 100, 1, 0),
        ("dbwDutyX10", "Throttle duty", "%", -100, 100, -100, -95, 95, 100,
         1, 0),
        ("dbwErrorX10", "Throttle error", "%", -100, 100, -50, -20, 20, 50,
         1, 0),
        # V97: the DBW step's terms, the battery factor, the verify grades
        ("dbwTermP", "ETB P term", "%", -100, 100, -100, -80, 80, 100, 1, 0),
        ("dbwTermD", "ETB D term", "%", -100, 100, -100, -80, 80, 100, 1, 0),
        ("dbwTermFf", "ETB feed-forward", "%", -50, 50, -50, -40, 40, 50,
         1, 0),
        ("dbwOutRaw", "ETB PID+FF sum", "%", -150, 150, -150, -100, 100, 150,
         1, 0),
        ("dbwBattFactor", "ETB battery factor", "", 0.5, 2.0, 0.5, 0.7, 1.6,
         1.8, 3, 1),
        ("etbVfySettleMs", "Verify settle", "ms", 0, 500, 0, 0, 350, 400,
         0, 0),
        ("etbVfyOverX10", "Verify overshoot", "%", 0, 20, 0, 0, 5, 8, 1, 0),
        ("etbVfyErrX10", "Verify offset", "%", 0, 10, 0, 0, 1.5, 3, 1, 1),
        # V97: the raw LSU 4.2 pump current, -1.85 .. +1.19 mA
        ("lam1IpUa", "Bank 1 pump current", "uA", -2000, 1500, -2000, -1850,
         1190, 1500, 0, 0),
        ("lam2IpUa", "Bank 2 pump current", "uA", -2000, 1500, -2000, -1850,
         1190, 1500, 0, 0),
    ]:
        gspec[name] = (title, units, lo, hi, ld, lw, hw, hd, vd, lbd)
    for j in range(8):
        for name,title,lo,hi in ((f"sweepBiasAxis{j}", f"Point {j+1} position",0,100),
                                (f"sweepBiasProposedAxis{j}", f"Point {j+1} proposed position",0,100),
                                (f"sweepBiasCurrent{j}",f"Point {j+1} current bias",-100,100),
                                (f"sweepBiasProposed{j}",f"Point {j+1} proposed bias",-100,100)):
            gspec[name]=(title,"%",lo,hi,lo,lo,hi,hi,1,1)
    for j, pos in enumerate(FRIC_POS):
        gspec[f"fricMid{j}"] = (f"{pos} % band midpoint", "%", -100, 100, -100, -100, 100, 100, 1, 1)
        gspec[f"fricWidth{j}"] = (f"{pos} % band width", "%", 0, 60, 0, 0, 60, 60, 1, 1)
        gspec[f"fricSpread{j}"] = (f"{pos} % edge spread", "%", 0, 10, 0, 0, 4, 6, 1, 1)
    for name,title,units,hi in (("sweepIntegralPrevious","Previous holding I","%",100),
                                ("sweepIntegralMean","This run holding I","%",100),
                                ("sweepBiasSamples","Steady fresh samples","",1000),
                                ("sweepBiasValidMin","Supported from","%",100),
                                ("sweepBiasValidMax","Supported to","%",100),
                                ("sweepBiasQualified","Supported-range samples","",1000),
                                ("sweepBiasExcluded","Excluded positions (bits)","",255)):
        gspec[name]=(title,units,0,hi,0,0,hi,hi,1,1)
    for name, (title, units, lo, hi, ld, lw, hw, hd, vd) in GM.GAUGE_META.items():
        gspec[name] = (title, units, lo, hi, ld, lw, hw, hd, vd, vd)
    # V98: an older channel of the SAME quantity takes its fast twin's title
    # and range (until V98 "Inj duty" spanned 0..6553 % and lambda 0..65)
    for old, new in GM.FAST_TWINS.items():
        gspec[old] = gspec[new]
    # A GAUGE FOR EVERY REMAINING OUTPUT CHANNEL.
    #
    # A dialog shows a live value with `gauge = <name>`, never with `field =`
    # - that distinction is what broke the S5500 sweep on real hardware. So
    # every channel a diagnostics dialog might want has to HAVE a gauge, and
    # curating 180 of them by hand is how one gets forgotten. The curated
    # entries above keep their real ranges and titles; the rest get an honest
    # default derived from the channel's own declared scale.
    def _num(v):
        return ("%d" % v) if float(v) == int(v) else ("%g" % v)

    for off, name, kind, units, desc in CH:
        if name in gspec:
            continue
        scale = SCALE.get(off, 1)
        tr = TRANSLATE.get(off, 0)
        if kind.startswith("S"):
            lo, hi = int(-32768 * scale), int(32767 * scale) or 1
        elif kind == "U08":
            lo, hi = 0, int(255 * scale) or 1
        else:
            lo, hi = int((0 + tr) * scale), int((65535 + tr) * scale) or 1
        dig = 3 if scale == 0.001 else (2 if scale == 0.01 else
                                        (1 if scale != 1 else 0))
        gspec[name] = (GM.humanize(name), units, lo, hi, lo, lo, hi, hi,
                       dig, dig)
    for name, expression, units, desc in DERIVED_CH:
        if name in gspec:
            continue
        gspec[name] = (GM.humanize(name), units, 0, 1023, 0, 0, 1023, 1023,
                       0, 0)
    by_cat = {}
    for name in gspec:
        title = gspec[name][0]
        if name in GM.FAST_TWINS:
            title = "%s (raw block)" % title
        by_cat.setdefault(GM.category(name), []).append(
            (name,) + (title,) + gspec[name][1:])
    for cat in GM.CATEGORY_ORDER:
        if cat not in by_cat:
            continue
        w('   gaugeCategory = "%s"' % cat)
        for (name, title, units, lo, hi, ld, lw, hw, hd, vd, lbd) in \
                sorted(by_cat.pop(cat), key=lambda r: r[1].lower()):
            w('   %sGauge = %s, "%s", "%s", %s, %s, %s, %s, %s, %s, %d, %d'
              % (name, name, title.replace('"', "'"), units, _num(lo),
                 _num(hi), _num(ld), _num(lw), _num(hw), _num(hd), vd, lbd))
            curated.add(name)
    if by_cat:
        raise SystemExit("gauges with no category: %s" % sorted(by_cat))
    w("")
    # The set of gauge IDENTIFIERS the file now declares. gen_ts_ux_me711
    # checks every `gauge =` and every `readout =` it emits against this,
    # so a panel cannot name a gauge that does not exist.
    curated_gauges = {"%sGauge" % n for n in curated}
    # ================================================ THE DEFAULT DASHBOARD ==
    #
    # AUTHORED IN gen_ts_ux_me711.FRONT_GAUGES / FRONT_INDICATORS, from
    # rusEFI's own [FrontPage] (rusefi_proteus_f7.ini:6070-6141). What used to
    # be here was eight TRIGGER-DEVELOPMENT gauges - tooth index, gap
    # candidate, sync loss reason, scheduler queue depth - over a wall of 41
    # indicators including asicInit, badVecBit, wdtFed and rxTickRunning, and
    # it was the first screen every user met.
    #
    # None of it is lost: every one of those channels still has its gauge and
    # its dialog under Diagnostics. What changed is that the DEFAULT screen now
    # answers a tuner's questions instead of the firmware author's.
    _front, _fp = UX.front_page_lines(curated_gauges)
    if _fp:
        raise SystemExit("the front page does not resolve: "
                         + "; ".join(_fp))
    for _line in _front:
        w(_line)
    # V98: THE DEFAULT DATALOG IS THE TUNING SET (ts_gauges_me711.DATALOG),
    # almost all of it the contiguous fast block - not the 728 channels it
    # was, which made every log poll the whole 1.1 KB block (~9 rows/s at
    # 115200). Developer channels stay channels: the gauges and the vehicle
    # logger (tools/vehicle/me711_vehicle_capture.py) read them.
    w("[Datalog]")
    _known = {n for _o, n, *_r in CH} | {n for n, *_r in DERIVED_CH}
    for name, title, fmt in GM.DATALOG:
        if name not in _known:
            raise SystemExit("datalog names %s, which is no channel" % name)
        if fmt == "int":
            w('   entry = %s, "%s", int, "%%d"' % (name, title))
        else:
            w('   entry = %s, "%s", float, "%s"' % (name, title, fmt))
    w("")
    # ============================================ V98: TUNE ANALYZE LIVE ====
    # rusEFI / Speeduino [VeAnalyze] (docs/TUNERSTUDIO.md):
    # the VE table, the target lambda table (stored as lambda x 147, shown as
    # lambda), the MEASURED lambda, the closed-loop correction in force (so a
    # trimmed sample is not double counted) and Speeduino's flag filters on
    # engineFlags - after-start 4, warm-up 8, transient 16, cuts 32|512.
    # NO LIVE activeCondition (V98, real TunerStudio 2026-10-01): with
    # `{ lambda1Valid }` there TunerStudio re-evaluated the condition when
    # the user switched analyzers and, with no valid lambda (the bench, a
    # cold sensor), found NO active map and greyed the VE tab for good. The
    # condition is a PAGE setting, as rusEFI's (useLambdaOnInterface) - here
    # "a lambda sensor is configured"; it also keeps rusEFI's field count
    # (ts_ini_grammar_proof). Lambda validity is a FILTER on the samples
    # (lambdaInvalid below), never the analyzer's availability.
    # ts_ini_ux_contract_proof holds this.
    w("[VeAnalyze]")
    w("   veAnalyzeMap = veTableTbl, afrMapTbl, lambdaValue, egoCorrForVeAnalyze, { lambda1Source != 0 }")
    w("   lambdaTargetTables = afrMapTbl, afrTSCustom")
    for f in ("std_xAxisMin", "std_xAxisMax", "std_yAxisMin", "std_yAxisMax",
              "std_DeadLambda"):
        w("   filter = %s" % f)
    w('   filter = lambdaInvalid, "Lambda not a measurement", lambda1Valid, =, 0, , false')
    w('   filter = minCltFilter, "Minimum CLT", coolant, <, 70, , true')
    w('   filter = lowRpmFilter, "Minimum RPM", RPMValue, <, 500, , true')
    w('   filter = aseFilter, "After-start enrichment", engineFlags, &, 4, , false')
    w('   filter = warmupFilter, "Warm-up enrichment", engineFlags, &, 8, , false')
    w('   filter = transFilter, "Acceleration / wall film transient", engineFlags, &, 16, , false')
    w('   filter = cutFilter, "Fuel cut (DFCO, limiter, protection)", engineFlags, &, 544, , false')
    w('   filter = mapEstFilter, "MAP estimate in use", engineFlags, &, 16384, , false')
    # V98r2: rusEFI's VBatt filter - below 12 V the dead-time curve's error
    # lands in the VE cell
    w('   filter = lowBattFilter, "Battery below", VBatt, <, 12, , true')
    w("   filter = std_Custom")
    w("")
    # rusEFI / Speeduino [WueAnalyze]: the warm-up curve (with a second line
    # for the recommendation), the lambda table, measured lambda, coolant,
    # the warm-up % in force (100-based, like Speeduino) and the correction.
    w("[WueAnalyze]")
    w("   wueAnalyzeMap = wueAnalyzerCurve, wueAfrTargetOffsetCurve, afrMapTbl, lambdaValue, coolant, warmupEnrich, egoCorrForVeAnalyze, { lambda1Source != 0 }")
    w("   lambdaTargetTables = afrMapTbl, afrTSCustom")
    w("   option = disableLiveUpdates")
    w("   option = burnOnSend")
    w("   filter = std_DeadLambda")
    w('   filter = lambdaInvalid, "Lambda not a measurement", lambda1Valid, =, 0, , false')
    w('   filter = aseFilter, "After-start enrichment", engineFlags, &, 4, , false')
    w('   filter = transFilter, "Acceleration / wall film transient", engineFlags, &, 16, , false')
    w('   filter = cutFilter, "Fuel cut", engineFlags, &, 544, , false')
    w('   filter = highThrottle, "High throttle", TPSValue, >, 15, , true')
    w('   filter = lowRpm, "Low RPM", RPMValue, <, 300, , false')
    w("   filter = std_Custom")
    w("")
    # rusEFI [Tools]: TunerStudio's own table generators (restored V98r2 -
    # they belong to the workflow). TunerStudio cannot make a tool
    # conditional, so the guard is the firmware: hc_validation warns
    # (cfgWarnings HC_WARN_VE/IGN/LAM_AXIS, shown beside the fuel strategy
    # and in Status overview) when a throttle-keyed axis leaves 0..100 % -
    # under the alpha-N strategies generate with a THROTTLE axis 0..100;
    # me711_log_analyze tune_check names dead rows and saturated cells.
    w("[Tools]")
    w('   addTool = veTableGenerator, "VE Table Generator", veTableTbl')
    w('   addTool = afrTableGenerator, "AFR Table Generator", afrMapTbl')
    w("")
    # ======================================== V98: HIGH SPEED LOGGERS =======
    # rusEFI's composite / primary-tooth loggers ('l' 1 / 7 on, 2 off, 3
    # read; hcts.c, hctrig_me711.c): 8-byte records in rusEFI's own wire
    # order, the time in T1 counts of 0.8 us (scaled here). An empty read is
    # TS_OK with no data - never an error code on this link.
    w("[LoggerDefinition]")
    _rec = [
        ("refTime", "RefTime", 0, 32, "0.0008", "ms"),
        ("priLevel", "PriLevel", 32, 1, "1", "Flag"),
        ("secLevel", "SecLevel", 33, 1, "1", "Flag"),
        ("trigger", "Trigger", 34, 1, "1", "Flag"),
        ("sync", "Sync", 35, 1, "1", "Flag"),
        ("tdc", "TDC", 36, 1, "1", "Flag"),
        ("cam1", "Cam 1", 33, 1, "1", "Flag"),
        ("cam2", "Cam 2", 37, 1, "1", "Flag"),
    ] + [("coil%d" % (i + 1), "Coil %d" % (i + 1), 40 + i, 1, "1", "Flag")
         for i in range(8)] + \
        [("inj%d" % (i + 1), "Inj %d" % (i + 1), 48 + i, 1, "1", "Flag")
         for i in range(8)]
    for lid, title, kind, start, fields in (
            ("compositeLogger", "Composite Logger", "composite", "\\x01",
             _rec),
            ("toothLogger", "Primary Tooth Time Logger", "tooth", "\\x07",
             _rec[:2])):
        w('   loggerDef = %s, "%s", %s' % (lid, title, kind))
        w('      startCommand = "l%s"' % start)
        w('      stopCommand = "l\\x02"')
        w('      dataReadCommand = "l\\x03"')
        w("      dataReadTimeout = 10000")
        w("      dataReadyCondition = { toothLogReady }")
        w("      continuousRead = true")
        w("      recordDef = 0, 0, 8")
        for nm, hdr, sb, nb, sc, un in fields:
            w('      recordField = %s, "%s", %d, %d, %s, "%s"'
              % (nm, hdr, sb, nb, sc, un))
        w('      calcField = toothTime, "ToothTime", "ms", { time - pastValue(time, 1) }')
        w('      calcField = time, "Time", "ms", { refTime }')
        w("")
    # EVERY COMMAND HERE MUST EXIST IN hcts_target_cmd(), and
    # tests/unit/test_ts_commands.py checks both directions. '!Z' and '!z' used to
    # be offered as "Stop/Start the alive text": they toggled `alive_on`, a
    # flag nothing had read since V23 removed banner(). A button that does
    # nothing is worse than a missing one, because a bench operator uses it to
    # rule something out. They are gone.
    for line in UI.table_lines(ui_by_ts):
        w(line)
    # V98: WUE Analyze's two curves (rusEFI wueAnalyzer_warmup_curve /
    # wueAfrTargetOffsetCurve): the live warm-up curve beside TunerStudio's
    # recommendation, and the lambda offset vs coolant.
    w('   curve = wueAnalyzerCurve, "Warm-up enrichment (WUE Analyze)"')
    w('      columnLabel = "Coolant", "Current WUE", "Coolant", "Recommended"')
    w("      xAxis = -40, 120, 9")
    w("      yAxis = 90, 250, 9")
    w("      xBins = cltEnrAx, coolant")
    w("      yBins = cltEnrVal")
    w("      yBins = wueAnalRecommend")
    w('      lineLabel = "Warm-up enrichment"')
    w('      lineLabel = "Recommended"')
    w("")
    w('   curve = wueAfrTargetOffsetCurve, "Lambda target offset vs coolant"')
    w('      columnLabel = "Coolant", "Lambda offset"')
    w("      xAxis = -40, 120, 9")
    w("      yAxis = -0.2, 0.2, 5")
    w("      xBins = cltEnrAx, coolant")
    w("      yBins = wueAfrTargetOffset")
    w("")
    w("[ControllerCommands]")
    # ONE PLAIN CHARACTER, THEN ESCAPES ONLY. This is not a style choice, it is
    # the rule real TunerStudio 3.3.01 actually implements, and V37 shipped
    # against a guess about it.
    #
    # V37's four SRAM-probe buttons were pressed on the bench. TunerStudio's own
    # serial debug showed it transmitting
    #
    #     00 02 21 11 A7 F6 27 EE        payload 21 11
    #
    # for `cmdRamProbe17 = "!M"`. The 'M' (0x4D) never reached the wire.
    # TunerStudio takes the FIRST literal character as the command byte and from
    # then on honours only escapes and $substitutions; a SECOND consecutive
    # plain character is dropped silently. hcts_target_cmd() therefore switched
    # on 0x11, matched no case, and returned TS_OK - a valid framed reply for a
    # command that did nothing, which is exactly what the bench saw.
    #
    # The corpus agrees without a single exception. Across 4553 [ControllerCommands]
    # literals in the 40 GENERATED rusEFI .ini files under
    # rusEFI firmware/tunerstudio/generated/ - files that are known to
    # load - the longest run of consecutive plain characters is ONE, every time.
    # The shapes are LXXXX (4313), LXXVX (160) and LXXVV (80). Two adjacent plain
    # characters occur ZERO times. Only the pre-substitution
    # `tunerstudio.template.ini` appears to break it, and there the second "run"
    # is an unexpanded @@TOKEN@@, not a character TunerStudio ever sees.
    #
    # So every subcommand letter is spelled as a hex escape. The BYTES ON THE
    # WIRE ARE UNCHANGED - '!' + 0x4D + seed is what hcmain_me711.c's
    # hcts_target_cmd() has always parsed as p[0]/p[1]/p[2] - which is why this
    # is an .ini fix and needs no new firmware.
    def cmd(name, letter, *args):
        """`!<letter><args...>` spelled the one way TunerStudio parses correctly."""
        esc = "".join(r"\x%02x" % b for b in (ord(letter),) + args)
        w('%-14s = "!%s"' % (name, esc))

    cmd("cmdAsicRestart", "A")
    # Standard page Burn, not a private diagnostic command.
    w('cmdLiveBurn    = "B"')
    # THE EXTERNAL-SRAM EXECUTION PROBE. Four buttons, four different seeds:
    # the answer depends on the seed, so pressing a second one and getting a
    # second correct answer rules out a fluke. The firmware mixes the byte
    # with the tick as well, so no two runs use the same seed anyway.
    #
    # IT WRITES NO FLASH. It is the one thing that should be run before this
    # ECU is asked to erase a sector, because hc_nvm_payload() executes from
    # external SRAM and nothing has ever proven this board can do that.
    for seed in RAM_PROBE_SEEDS:
        cmd("cmdRamProbe%d" % seed, "M", seed)
    # THE ENDPOINT GRAB. rusEFI's cmd_calibrate_tps_closed / _open /
    # cmd_calibrate_pedal_up / _down, and the same act: put the plate or the
    # pedal where you want it and tell the ECU that this is where it is.
    #
    # RAM ONLY. It writes the live calibration page and never flash, so after
    # a grab the tune is modified and unburned exactly as if the number had
    # been typed - the "Unsaved changes" light says so, and an explicit Burn is
    # still the only thing that makes it permanent.
    #
    # NO OUTPUT IS DRIVEN. This reads two analog channels. It is not a bench
    # command and it does not go through hcbench.c.
    for _nm, _what in (("cmdGrabTpsClosed", 1), ("cmdGrabTpsOpen", 2),
                       ("cmdGrabAppRest", 3), ("cmdGrabAppFull", 4)):
        cmd(_nm, "G", _what)
    # V90: AUTO CALIBRATE ETB - hc_dbw.c drives the plate to both stops with a
    # bounded duty and writes both tracks' endpoints. No pedal, no dbwEnable.
    cmd("cmdEtbAutoCal", "C", 1)
    cmd("cmdEtbAutoCalAbort", "C", 0)
    # V92: the rusEFI relay autotune (hc_dbw.c tune_step()).
    cmd("cmdEtbAutoTune", "C", 2)
    cmd("cmdEtbCommission", "C", 3)
    cmd("cmdEtbCharacterize", "C", 6)
    cmd("cmdEtbSaveBias", "C", 7)
    # V92: THE TOOTH PROFILE ('!K'). 1 = compression profile, spark and fuel
    # HELD OFF (engine must be stopped at the request), 2 = running profile,
    # 0 = abort. See hcsched_dry.h.
    cmd("cmdToothLogCompression", "K", 1)
    cmd("cmdToothLogRunning", "K", 2)
    cmd("cmdToothLogAbort", "K", 0)
    # V97: CLEAR TROUBLE CODES ('!D', OBD mode 04) - hcdtc711.c
    cmd("cmdDtcClear", "D")
    # '!W' moves the S5500 correlation window. This is the ONE diagnostic that
    # can close the runtime-frame analog mapping WITHOUT another flash: sweep
    # the base, watch s5500Idx, and the window that decodes as sixteen
    # consecutive ADDAT channels is the analog block. Seven buttons cover all
    # 118 words of the runtime frame in 16-word steps.
    for base in S5500_SWEEP:
        cmd("cmdS5500Win%d" % base, "W", base)
    # THE BENCH OUTPUT COMMANDS. One channel per button, deliberately: there is
    # no "all injectors" command in the firmware and there must never be one.
    # Pressing a button does NOT by itself drive anything - hcbench.c evaluates
    # every invariant first and publishes which ones failed.
    for ch in range(1, 9):
        cmd("cmdTestInj%d" % ch, "T", TEST_INJECTOR, ch)
    for ch in range(1, 9):
        cmd("cmdTestCoil%d" % ch, "T", TEST_COIL, ch)
    # THE FUEL PUMP RELAY. EKP is P2.12 - Bosch's own port sheet, both
    # ME7.1.1 columns - through a CJ920 low-side driver to connector cavity
    # 65. One channel, timed in MILLISECONDS, three energisations.
    cmd("cmdTestPump", "T", TEST_FUEL_PUMP, 1)
    # THE LOGICAL MAIN RELAY, on whatever cavity it is routed to.
    # Bounded and finite: three energisations of at most a second,
    # then it stops. Refused unless the configured cavity is
    # assigned, RELAY_OUT capable, and one this build can reach.
    cmd("cmdTestRelay", "T", TEST_MAIN_RELAY, 1)
    # THE THROTTLE BRIDGE, V99: rusEFI's ETB bench test made a stop test -
    # direction A / B at the autocal duty until the plate SETTLES at its stop
    # (hcetbcal.c '!C4' / '!C5'), then released; the position is reported.
    # V83..V98 nudged a leg for <= 50 ms and the 150-count runaway guard
    # aborted the first nudge that moved a real throttle (the car, 2026-10-02:
    # "direction A only moves briefly once").
    # V82: THE CAM SOLENOID STAGES - MAIN POUT0 -> cavity 115 (KNWS1) and
    # POUT1 -> cavity 120 (KNWS2), CJ920 low-side with a freewheel diode.
    # Three bursts of the OEM 250 Hz PWM at 50 %, each at most a second.
    # V97: THE CHECK-ENGINE LAMP STAGE, cavity 47 (ASIC P7.0) - the ASIC
    # test mode's channel 14: three bounded pulses, engine stopped.
    cmd("cmdTestCel", "T", TEST_BOOST, 14)
    cmd("cmdTestVvt1", "T", TEST_VVT, 1)
    cmd("cmdTestVvt2", "T", TEST_VVT, 2)
    cmd("cmdTestDbwA", "C", 4)
    cmd("cmdTestDbwB", "C", 5)
    cmd("cmdTestAbort", "X")
    # V86: APPLY THE ENGINE PRESET SELECTED IN enginePreset. rusEFI's "Base
    # Tunes" button: selecting a preset is only a choice, this is the act.
    # No id byte - the firmware reads the selection TunerStudio already wrote.
    cmd("cmdApplyEnginePreset", "E")
    w("")
    # V86: AN ECU-SIDE PAGE CHANGE MUST REACH TUNERSTUDIO'S COPY. rusEFI
    # raises triggerPageRefreshFlag for a second after applying a preset and
    # declares `triggeredPageRefresh = <page>, { flag }` here (every generated
    # rusEFI .ini under rusEFI firmware/tunerstudio/generated/).
    w("[EventTriggers]")
    w("   triggeredPageRefresh = 1, { presetPageRefresh }")
    w("")
    w("[UiDialogs]")
    # ================== THE SECTION NAME IS A DELIBERATE DEVIATION =========
    #
    # rusEFI still emits [UserDefined], so the 40-file corpus cannot prove
    # [UiDialogs] loads. Two other sources can, and both are stronger than the
    # corpus for this one question: TunerStudio 3.3.01 names the replacement
    # ITSELF while loading the V37C file -
    #
    #     Loading Depricated ini section [UserDefined], use [UiDialogs]
    #
    # - and rusEFI .junie/ts-help-topic.md documents both spellings
    # as valid places to declare an entity. The release ships a [UserDefined]
    # fallback beside the primary .ini so a T0 failure costs one file swap.
    # tests/tunerstudio/ts_ini_indicator_scope_proof.py is the gate.
    #
    # ================== AND THE DIALOGS ARE NOW WORKFLOWS ==================
    #
    # What was here: UI.dialog_lines() - one dialog per (model category, apply
    # group) pair, filled with every field in that pair in model order, and a
    # menu re-labelled to look like rusEFI's. Real TunerStudio 3.3.01 opened it
    # on 2026-09-05 and the verdict was "Engine Setup is a long flat field
    # list; Trigger is another long flat field list". Renaming a menu does not
    # change what a dialog IS.
    #
    # gen_ts_ux_me711 now owns the shape - which panel a field belongs to, what
    # sits beside it, which live value proves the setting that changes it - and
    # the model still owns every offset, unit, limit and label. place_report()
    # there refuses to build if a model field is in no panel, so the hand
    # authoring cannot quietly lose a setting.
    _ux_problems, _n_placed, _n_ed, _n_tot = UX.place_report()
    if _ux_problems:
        raise SystemExit("the workflow UI does not resolve: "
                         + "; ".join(_ux_problems))

    # The mask decoders are built from the firmware's own headers, so they are
    # handed to the UX module rather than written down there twice.
    _dynamic = {
        "hcPanelSensors": ['      indicator = { %s }, "%s OK", "%s FAULT", '
                           'white, black, red, black'
                           % (nm, SENSOR_LABEL[nm], SENSOR_LABEL[nm].upper())
                           for _mask, nm in SENSOR_BITS],
        "hcPanelFuelCut": SEM.fault_indicators("fuelCut", "fuelCut"),
        "hcPanelInhibits": SEM.fault_indicators("safetyInhibits",
                                                "safetyInhibits"),
        "hcPanelDbwFaults": SEM.fault_indicators("dbwFaults", "dbwFaults"),
        "hcPanelBenchRefuse": SEM.fault_indicators("hcbRefuse", "hcbRefuse"),
        "hcPanelBenchAbort": SEM.fault_indicators("hcbAbort", "hcbAbort",
                                                  only_bad=True),
    }
    _ux_body, _ux_bad = UX.emit(ui_by_ts, curated_gauges, None, _dynamic)
    if _ux_bad:
        raise SystemExit("the workflow UI names things that do not exist: "
                         + "; ".join(_ux_bad))
    for _line in _ux_body:
        w(_line)

    # The 2D cell editor for every map, and its 3D view beside it. See
    # UI.table_dialog_lines(): the menu used to name only the map3d id, so a
    # tuner could look at a surface and never type in a cell.
    for line in UI.table_dialog_lines():
        w(line)
    # TWO REAL DEFECTS LIVED HERE AND A BENCH FOUND THEM, 2026-09-02.
    #
    # 1. AN UNTERMINATED STRING. One label line was emitted as
    #        field = "me711_s5500_static_map puts coolant at word 21-23 and
    #    with no closing quote. TunerStudio logged "open-ended String" and the
    #    rest of the dialog parsed as the inside of that string. label() below
    #    now refuses a quote it did not close, so the generator cannot emit one.
    #
    # 2. OUTPUT CHANNELS USED AS `field`. `field = "label", name` binds an
    #    EcuParameter - a CONSTANT on the settings page. s5500Base, s5500Idx,
    #    s5500Snaps and s5500Plaus are OutputChannels, so TunerStudio reported
    #    "invalid Constant" on load and "EcuParameter not found" when the
    #    dialog opened. A live output channel is shown with `gauge =`, against
    #    a gauge defined in [GaugeConfigurations] - which is what
    #    rusEFI .../rusefi_cypress.ini does everywhere.
    #
    # THE BUTTONS NEVER SENT ANYTHING because of those two, not because the
    # firmware lacks the command: hcts.c's `case '!'` and hcts_target_cmd()
    # have handled '!W' since V20, and tests/unit/test_ts_commands.py checks both
    # directions. tests/unit/test_ts_ini_ui_contract.py is the gate that would have
    # caught this before it reached hardware.
    w('   dialog = hcBench, "I/O chip link restart"')
    w(label("Developer use: restarts the I/O chip link (wideband, analog"))
    w(label("inputs, boost valve, heaters) without a reset. Engine stopped."))
    w('      commandButton = "Restart the I/O chip link", cmdAsicRestart')
    w("")
    # V89 UI: FOUR COLUMNS, NOT ONE. The rules, the channel buttons, the
    # auxiliary outputs and the live state side by side - it was ~150 text
    # rows in one column (tools/tunerstudio/ts_ini_layout_audit.py). ABORT is repeated at
    # the top of every column that carries a test button, so it is always in
    # view; it is the same unconditional command.
    w('   dialog = hcOutputTestRules, ""')
    for line in [
        "#Each test drives ONE output for a short, bounded time.",
        "",
        "It runs only when all of these hold:",
        "   the engine is stopped (no crank signal, rpm 0)",
        "   the configuration is valid",
        "   the I/O chip link is running",
        "",
        "The pulse is the bench test value, limited by the firmware to",
        "20 ms for an injector and 4 ms for a coil. Ten pulses, 200 ms",
        "apart. A crank signal, an invalid configuration or ABORT stops",
        "it at once.",
        "",
        "!On a new installation the first test of each output is a",
        "!measurement: nothing else connected, a scope or test lamp on",
        "!the pin, one channel at a time.",
        "",
        "A refused test lists every reason (Bench state and refusals).",
        "",
    ]:
        w(label(line))
    # The parameters live in their own panel, so the same controls appear
    # identically wherever they are reached from. V84: no arming switch - the
    # button below IS the deliberate act, with the invariants above.
    w('      panel = hcCtrlBenchValues')
    w("")
    w('   dialog = hcOutputTestChannels, ""')
    w('      commandButton = "ABORT", cmdTestAbort')
    w(label(""))
    for ch in range(1, 9):
        w('      commandButton = "Injector %d", cmdTestInj%d' % (ch, ch))
    w(label(""))
    for ch in range(1, 9):
        w('      commandButton = "Coil %d", cmdTestCoil%d' % (ch, ch))
    w("")
    w('   dialog = hcOutputTestAux, ""')
    w('      commandButton = "ABORT", cmdTestAbort')
    w(label(""))
    for line in [
        "# Fuel pump relay - cavity 65, low-side: relay coil from",
        "# switched +12 V to cavity 65. Timed in milliseconds.",
    ]:
        w(label(line))
    w('      commandButton = "Fuel pump relay", cmdTestPump')
    w(label(""))
    for line in [
        "# Main relay - the configured cavity. Only a CPU-driven cavity",
        "# (65) can be tested; cavity 23 follows the key in hardware, so",
        "# the test is refused there by design.",
        "! Cavity 21 is the ignition (KL15) input, never a relay output.",
        "Three pulses of up to 1 s, then it stops.",
    ]:
        w(label(line))
    w('      commandButton = "Main relay (configured cavity)", cmdTestRelay')
    w(label(""))
    # Each explanation now sits directly above ITS buttons (until V89 the
    # throttle text was followed by the cam buttons).
    for line in [
        "# Throttle motor - cavities 117 / 118.",
        "! Engine stopped, throttle tracks agreeing and no bridge fault,",
        "! or it refuses. Three nudges of at most 50 ms; it stops on a",
        "! bridge fault, the plate leaving a fixed band, or the tracks",
        "! disagreeing.",
    ]:
        w(label(line))
    w('      commandButton = "Throttle bridge, direction A", cmdTestDbwA')
    w('      commandButton = "Throttle bridge, direction B", cmdTestDbwB')
    w(label(""))
    for line in [
        "# Cam solenoids - cavities 115 and 120.",
        "! Three 250 Hz bursts at 50 % duty, each as long as the test",
        "! value (ms, limited by the firmware).",
    ]:
        w(label(line))
    w('      commandButton = "Cam solenoid, cavity 115", cmdTestVvt1')
    w('      commandButton = "Cam solenoid, cavity 120", cmdTestVvt2')
    w("")
    w('   readoutPanel = hcOutputTestLive, 2')
    for g in ("hcbState", "hcbRefuse", "hcbAbort", "hcbModeCh", "hcbPortBit",
              "hcbConnPin", "hcbWidthUs", "hcbWidthMs", "hcbPulses",
              "hcbTpsStart", "hcbTpsNow", "hcbSfLevel", "rpm",
              "syncState", "cfgValidation"):
        w('      readout = %sGauge' % g)
    w("")
    w('   dialog = hcOutputTest, "Bench test - one channel at a time", xAxis')
    for pid in ("hcOutputTestRules", "hcOutputTestChannels", "hcOutputTestAux",
                "hcOutputTestLive"):
        w('      panel = %s' % pid)
    w("")
    # V89 UI: the explanation beside the controls and the result.
    w('   dialog = hcS5500Help, ""')
    for line in [
        "#Developer use only. Moves the 16-word analog window over the",
        "#I/O chip frame to locate the analog block.",
        "",
        "Normal operation needs base 4. After each move read s5500Idx:",
        "0xFFFF means all sixteen words carry their own channel number.",
        "",
        "Type the base in the field, or use the buttons.",
    ]:
        w(label(line))
    w("")
    w('   readoutPanel = hcS5500Live, 2')
    for g in ("s5500Base", "s5500Idx", "s5500Snaps", "s5500Plaus"):
        w('      readout = %sGauge' % g)
    w("")
    w('   dialog = hcS5500Controls, ""')
    w('      field = "Analog window base word", s5500WindowBase')
    w(label(""))
    for base in S5500_SWEEP:
        w('      commandButton = "window at word %d", cmdS5500Win%d'
          % (base, base))
    w(label(""))
    w('      panel = hcS5500Live')
    w("")
    w('   dialog = hcS5500, "I/O chip analog window sweep", xAxis')
    w('      panel = hcS5500Help')
    w('      panel = hcS5500Controls')
    w("")
    # ------------------------------------------------ diagnostics dialogs
    # USEFUL ENGINE-RUNTIME STATE, not debug garbage. Every entry below is a
    # gauge over a real output channel; ts_ini_ui_contract.py refuses a name
    # that is not one.
    # (channel, [PcVariables] list, the value that means OK, the OK wording)
    # An indicator's TRUE caption is the good news; the FALSE caption is the
    # decoded state. So a healthy ECU reads "PASS", and an unhealthy one reads
    # the actual reason rather than a number.
    DIALOG_VERDICTS = {
        "hcDiagRamProbe": [
            ("ramProbeVerdict", "hcRamProbeList", 2, "SRAM probe: PASS"),
        ],
        "hcDiagPersist": [
            ("nvmStateLo", "hcNvmStateList", 5, "Calibration BURNED to flash"),
            ("nvmErrLo", "hcNvmErrList", 0, "No persistence error"),
            ("nvmSrcLo", "hcNvmSrcList", 2, "Running from flash slot A"),
            ("nvmSlot", "hcNvmSlotList", 1, "Active record: slot A"),
            ("nvmClass", "hcPersistList", 2, "NON-VOLATILE"),
            ("nvmPhase", "hcNvmPhaseList", 0, "No commit in progress"),
        ],
        "hcDiagThrottle": [
            ("dbwState", "hcDbwStateList", 2, "Throttle closed loop"),
            ("fuelPumpState", "hcPumpStateList", 3, "Fuel pump running"),
            ("mainRelayMode", "hcRelayStateList", 2, "Main relay running"),
        ],
        "hcDiagTrigger": [
            ("syncState", "hcTrgStateList", 4, "Full sync - engine phase known"),
            ("syncLossReason", "hcSyncLossList", 0, "No sync loss recorded"),
        ],
    }

    # DECLARED BEFORE ANYTHING REFERENCES THEM. In all 40 rusEFI
    # generated .ini files, a `panel =` NEVER names a panel declared
    # later in the file - zero forward references out of 40. Follow the
    # corpus rather than hoping the parser is forgiving.

    # ------------------------------------------------------- READOUT PANELS --
    #
    # rusEFI carries 10 readout panels against HaniCore's 0. A readout panel is
    # a compact block of live NUMBERS beside the indicators that say whether
    # they are healthy - `readoutPanel = <id>, <cols>` then `readout =
    # <gaugeName>`, referencing a gauge from [GaugeConfigurations]
    # (rusefi_proteus_f7.ini:10371).
    #
    # THE FUEL ONE IS THE POINT. the project rules fix the load path -
    # MAP and charge temperature to density to VE to rl to target lambda to
    # fuel mass to te to deadtime to pulse width - and until now a tuner could
    # see the pulse width and none of the working that produced it. Showing the
    # chain in order is the difference between a model and a black box.
    # The readout panels moved to gen_ts_ux_me711: they are shared by the
    # tuning workflows and by these diagnostics dialogs, and a panel declared
    # in two places is two panels.
    # V45 is intentionally a compact, five-column investigation screen rather
    # than a wall of analog clocks.  It fits the one-Burn post-mortem on a
    # normal 1080p display without changing any OCH type or scaling.
    FORENSIC_PANELS = [
        ("hcBfBurn", 3, ("bfBurnEpoch", "bfFlags", "bfCurrentStage",
                          "bfLastStage", "bfFailStage", "bfFailureReason")),
        ("hcBfBoot", 3, ("bfBootEpoch", "bfHctsInitCount", "bfHctsInitBootEpoch",
                          "bfCfgBurnsBeforeInit", "bfCfgWritesBeforeInit",
                          "bfRawResetCause", "rstPreviousStage", "rstPreviousTrap",
                          "rstPreviousTrapMs", "rstPreviousWdtServices")),
        ("hcBfNvm", 3, ("bfNvmState", "bfNvmPhase", "bfNvmResult", "bfNvmCell",
                         "bfNvmPos", "bfNvmAttempts", "bfNvmRetries", "bfNvmError")),
        ("hcBfWriter", 3, ("bfWriterResult", "bfFailWord", "bfFailExp",
                            "bfFailGot", "bfFailGot2", "bfPollMin", "bfPollMax")),
        ("hcBfResetLog", 3, ("rstPreviousUptime", "rstPreviousLoop",
                              "rstPreviousFirstVector", "rstPreviousLastVector",
                              "rstPreviousTarget0", "rstPreviousTarget1",
                              "rstPreviousTarget2", "rstPreviousTarget3",
                              "rstPreviousTarget4", "bfRecordPresent")),
    ]
    for pid, cols, names in FORENSIC_PANELS:
        w('   readoutPanel = %s, %d' % (pid, cols))
        for n in names:
            w('      readout = %sGauge' % n)
        w("")

    # The physical live-Burn screen must remain a compact multi-column bench
    # card.  These groups preserve the V47 UI that produced the decisive
    # 22-word capture; no OCH layout or scaling changes here.
    w('   indicatorPanel = hcLiveBurnStatus, 3')
    w('      indicator = { nvmStateLo == 5 && liveBurnError == 0 }, { Status: bitStringValue(hcNvmStateList, nvmStateLo)}, "DURABLE SUCCESS", white, black, green, black')
    w('      indicator = { liveVectorViolations == 0 }, "VECTOR SAFETY VIOLATION", "VECTOR SAFETY: 0", white, red, green, black')
    w('      indicator = { liveAsicOverdue == 0 }, "ASIC OVERDUE", "ASIC OVERDUE: 0", white, red, green, black')
    w("")
    LIVE_PANELS = [
        ("hcLiveBurnResult", 6, ("releaseId", "nvmStateLo", "liveBurnError",
          "liveGeneration", "liveCommits", "liveAttempts", "nvmSlot", "bfNvmCell",
          "liveWordsTotal", "liveWordsCompleted", "liveWordsRemaining", "liveCurrentWord")),
        ("hcLiveAdmissionOwner", 7, ("liveOwner", "liveAdmission", "livePauseReason",
          "liveDeadlineMs", "livePredictedMs", "liveWindowsOk", "liveWindowsRejected")),
        ("hcLiveWriter", 6, ("liveWriterEntries", "liveWriterSuccess", "liveWriterFail",
          "bfWriterResult", "bfFailWord", "bfFailExp", "bfFailGot", "bfFailGot2",
          "bfPollMin", "bfPollMax", "liveMaxPollTicks", "liveWriterFlags")),
        ("hcLiveVectorSafety", 6, ("liveVectorViolations", "liveMask",
          "livePendingBefore", "livePendingAfter", "schedulerCaptureOverflow")),
        ("hcLiveAsicSscPec", 6, ("liveAsicState", "liveAsicAgeMs", "liveSscCon",
          "liveSscErrors", "livePec0Remaining", "livePec4Remaining", "liveAsicDenied",
          "liveAsicOverdue")),
        ("hcLiveEngineKline", 6, ("liveRpm", "liveHorizonUs", "liveAdmission",
          "liveWindowsRejected", "rxHwOvr", "rxFrameErr")),
    ]
    for pid, cols, names in LIVE_PANELS:
        w('   readoutPanel = %s, %d' % (pid, cols))
        for n in names:
            w('      readout = %sGauge' % n)
        w("")

    # ============================================= V89 UI: WIDTH, NOT HEIGHT
    #
    # Until V89 each dialog here was ONE COLUMN: the caption, then one full
    # gauge widget per channel - "Trigger and sync" was ~40 dials stacked,
    # ~195 text rows on tools/tunerstudio/ts_ini_layout_audit.py, scrolling on a 1080p
    # screen at every glance. Now every dialog is rusEFI's xAxis idiom
    # (`dialog = triggerConfiguration, "", xAxis` + panels):
    #   <did>Info   the caption and the decoded verdicts, and anything the
    #               dialog DOES (command buttons);
    #   <did>Live   the channels as a compact `readoutPanel` grid - the same
    #               gauges, as numbers, as V45's forensic screen already does.
    # A long caption gets a column of its own. The live values are the same
    # [GaugeConfigurations] entries as before; ts_ini_control_inventory.py
    # proves nothing was lost or rebound.
    def readout_cols(n):
        return 2 if n <= 8 else (3 if n <= 18 else 4)

    for did, title, caption, names in DIAG_DIALOGS:
        verdicts = DIALOG_VERDICTS.get(did, ())
        if did == "hcDiagPersist":
            # DECLARED BEFORE THE DIALOG THAT NAMES IT - in all 40 rusEFI
            # generated files a `panel =` never forward-references.
            w('   indicatorPanel = hcCfgFaultPanel, 2')
            for _n, _tag, _mask in CFG_FAULT_CH:
                w('      indicator = { %s == 0 }, "%s ok", "%s", '
                  'white, black, red, black' % (_n, _tag, _tag))
            w("")
        # EVERY ONE OF THESE WAS THROWN AWAY BY REAL TUNERSTUDIO 3.3.01 when
        # they were bare `indicator =` lines in a dialog (V37C, thirteen
        # warnings) - so the verdicts live in their own indicatorPanel.
        if verdicts:
            w('   indicatorPanel = %sVerdict, 1' % did)
            for chan, lst, ok_val, ok_text in verdicts:
                w('      indicator = { %s == %d }, '
                  '{ %s: bitStringValue(%s, %s)}, "%s", '
                  'white, black, green, black'
                  % (chan, ok_val, lst[2:].replace("List", ""), lst, chan,
                     ok_text))
            w("")
        if did in ("hcDiagLiveBurn", "hcDiagBurnReset"):
            # Already the compact multi-column bench cards that produced the
            # V47 capture and the V45 post-mortem. Unchanged.
            w('   dialog = %s, "%s"' % (did, title))
            for line in caption:
                w('      field = "%s"' % line)
            if caption:
                w('      field = ""')
            if verdicts:
                w('      panel = %sVerdict' % did)
            if did == "hcDiagLiveBurn":
                w('      panel = hcLiveBurnStatus')
                w('      field = "Persistence test byte (P3)", idlePad')
                w('      commandButton = "Burn P3 / calibration", cmdLiveBurn')
                w('      field = "Closing this dialog does not Burn."')
                for panel_label, pid in (("BURN / RESULT", "hcLiveBurnResult"),
                                         ("ADMISSION / OWNER", "hcLiveAdmissionOwner"),
                                         ("WRITER", "hcLiveWriter"),
                                         ("VECTOR / INTERRUPT SAFETY", "hcLiveVectorSafety"),
                                         ("ASIC / SSC / PEC", "hcLiveAsicSscPec"),
                                         ("ENGINE / K-LINE", "hcLiveEngineKline")):
                    w('      field = "%s"' % panel_label)
                    w('      panel = %s' % pid)
            else:
                for pid, _cols, _names in FORENSIC_PANELS:
                    w('      panel = %s' % pid)
            w("")
            continue

        live = list(names)
        if did == "hcDiagPersist":
            live.append("cfgFirstBadOffset")
        w('   readoutPanel = %sLive, %d' % (did, readout_cols(len(live))))
        for n in live:
            w('      readout = %sGauge' % n)
        w("")

        long_caption = len(caption) > 14
        # Column 1: the caption (and, when it is short, the verdict and the
        # buttons under it).
        w('   dialog = %sInfo, ""' % did)
        for line in caption:
            w('      field = "%s"' % line)
        if not long_caption:
            if caption and verdicts:
                w('      field = ""')
            if verdicts:
                w('      panel = %sVerdict' % did)
        w("")
        cols = ["%sInfo" % did]
        # Column 2 when the caption is long: what the dialog decides and does.
        state_items = []
        if long_caption and verdicts:
            state_items.append('      panel = %sVerdict' % did)
        if did == "hcDiagRamProbe":
            state_items.append('      field = ""')
            for seed in RAM_PROBE_SEEDS:
                state_items.append('      commandButton = "Probe SRAM, seed 0x%02X", '
                                   'cmdRamProbe%d' % (seed, seed))
        if did == "hcDiagPersist":
            # WHY A BURN WAS REFUSED, BESIDE THE PERSISTENCE STATE THAT SAYS
            # IT WAS - on 2026-09-16 nvmErrLo alone was not enough to find an
            # unassigned crank pin.
            state_items += [
                '      field = ""',
                '      field = "WHY A BURN WAS REFUSED - these are the rules the"',
                '      field = "DESIRED page failed. cfgFirstBadOffset is the"',
                '      field = "page offset of the FIRST one."',
                '      panel = hcCfgFaultPanel',
                '      panel = hcReadNvm',
                # THE P3 TEST BYTE LIVES WITH THE PERSISTENCE IT TESTS.
                '      panel = hcNvmTest',
            ]
        if state_items:
            w('   dialog = %sState, ""' % did)
            for line in state_items:
                w(line)
            w("")
            cols.append("%sState" % did)
        cols.append("%sLive" % did)
        w('   dialog = %s, "%s", xAxis' % (did, title))
        for c in cols:
            w('      panel = %s' % c)
        w("")

    # ============================ STAGE A: PANELS THAT ANSWER A QUESTION ====
    #
    # the maintainer's design records measured 58 indicatorPanels in rusEFI
    # against 0 in HaniCore, beside 161 gauges against rusEFI's 91. That is the
    # measurable form of "the firmware exposes its structs": the working is
    # published and the conclusion is withheld.
    #
    # Every indicator below reads a channel the flashed V37 binary already
    # produces. A bitmask gets ONE INDICATOR PER BIT rather than
    # bitStringValue(), because bitStringValue indexes and a mask of 0x0005 is
    # not "state 5" - and because two faults can be true at once, which a
    # single decoded string cannot show.
    # The indicator panels and the "Why?" dialogs moved to gen_ts_ux_me711.
    # They are the answer-shaped half of the UI and they belong beside the
    # workflows that reference them, not beside the diagnostics dumps.

    w('   readoutPanel = hcBenchStateLive, 2')
    for nm in ("hcbState", "hcbRefuse", "hcbAbort", "hcbModeCh"):
        w('      readout = %sGauge' % nm)
    w("")
    w('   dialog = hcBenchStateVerdicts, ""')
    w('      panel = hcPanelBenchState')
    w('      panel = hcPanelBenchAbort')
    w('      panel = hcBenchStateLive')
    w("")
    w('   dialog = hcBenchStateCols, "", xAxis')
    w('      panel = hcBenchStateVerdicts')
    w('      panel = hcPanelBenchRefuse')
    w("")
    w('   dialog = hcBenchState, "Bench state and refusals"')
    w('      topicHelp = "hcHelpBench"')
    w('      field = "A bench command that is refused says WHY. It is never a '
      'silent no-op."')
    w('      field = ""')
    # THE STATE INDICATOR IS IN A PANEL, NOT LOOSE IN THE DIALOG.
    # Real TunerStudio 3.3.01 IGNORED this one, and twelve more like it, in
    # the V37C file - `indicator` outside an indicatorPanel is dropped with a
    # warning nobody was reading. hcPanelBenchState is declared by the UX
    # module; ts_ini_indicator_scope_proof.py is the gate.
    # V89 UI: the verdict panels and the raw words side by side.
    w('      panel = hcBenchStateCols')
    w("")

    # ------------------------------------------------------ contextual help --
    # `help = <id>, "Title"` then indented `text = ...`, declared in
    # [UserDefined] and referenced by `topicHelp = "<id>"` inside a dialog.
    # Corpus: rusefi_proteus_f7.ini:9239-9243. Help goes where a person can
    # make a DANGEROUS or CONFUSING mistake, not on everything.
    for hid, title, body in HELP_TOPICS:
        w('   help = %s, "%s"' % (hid, title))
        for para in body:
            w('      text = "%s"' % para.replace('"', "'"))
        w("")

    # ==================================================== THE MAIN SCREEN ===
    #
    # THE MENU IS AUTHORED IN gen_ts_ux_me711.MENU, from rusEFI's own [Menu]
    # (rusefi_proteus_f7.ini:7167-). What was here built the tree from
    # `ui_plan` - the config model's (category, apply group) cross-product -
    # and then re-labelled the entries. That is why every dialog behind it was
    # a flat field list: the menu was a rename of a data structure.
    #
    # Bench and Diagnostics are appended HERE rather than in the UX module,
    # because their dialogs are declared in this file (they name command
    # buttons, and a button may only name a command [ControllerCommands]
    # actually carries).
    #
    # Each map appears twice on purpose: the editable cell grid FIRST, which is
    # how a map is tuned, and the 3D surface after it, which is how a map is
    # looked at. V35 shipped only the second.
    # V89 UI (rusEFI pass). rusEFI's &Controller holds Base Tunes, the bench
    # test and the controller internals; its &View holds live module state.
    # HaniCore follows that: Base Tunes and the bench test move under
    # Controller, the developer forensics (V45/V49 Burn forensics, the SRAM
    # probe, the S5500 window) go into a Controller group of their own, and
    # Diagnostics keeps what a TUNER asks - grouped by question, not struct.
    DIAG_MENU = [
        ("hcDiagDtc", "Trouble codes (DTC)"),
        ("hcDiagTrigger", "Trigger and sync"),
        ("hcFuelComputer", "Fuel computer"),
        ("hcSparkState", "Ignition state"),
        ("hcDiagRuntime", "Engine runtime"),
        ("hcDiagThrottle", "Throttle, pedal and relays"),
        ("hcDiagSensors", "Sensors and inputs"),
        ("hcDiagNativeIo", "Wideband, boost valve and key-off"),
        ("hcDiagPersist", "Calibration storage (Burn)"),
        ("hcDiagPlatform", "Communication and ECU link"),
        ("hcDiagLoadPolicy", "Fuel model and air density"),
    ]
    DEV_MENU = [
        ("hcBench", "I/O chip link restart"),
        ("hcCtrlS5500Dlg", "I/O chip analog window"),
        ("hcS5500", "I/O chip analog window sweep"),
        ("hcDiagRamProbe", "External RAM execution probe"),
        ("hcDiagLiveBurn", "Burn forensics: live Burn"),
        ("hcDiagBurnReset", "Burn forensics: reset log"),
    ]

    def diag_entries():
        """PRESENTATION ORDER ONLY. Anything DIAG_DIALOGS declares that
        neither list mentions is APPENDED to Diagnostics with its own title
        rather than silently dropped - V37 shipped a hardcoded list of six
        beside a table of seven, and the SRAM probe nobody could open was the
        seventh."""
        named = {did for did, _lbl in DIAG_MENU + DEV_MENU}
        known = {did for did, _t, _c, _n in DIAG_DIALOGS}
        stale = sorted(named - known - {"hcFuelComputer", "hcSparkState",
                                        "hcBench", "hcS5500",
                                        "hcCtrlS5500Dlg", "hcDiagDtc"})
        if stale:
            raise SystemExit("DIAG_MENU/DEV_MENU name dialogs that "
                             "DIAG_DIALOGS does not declare: %s" % stale)
        return DIAG_MENU + [(did, title)
                            for did, title, _c, _n in DIAG_DIALOGS
                            if did not in named]

    TAIL = [
        ("&Controller", [
            ("hcBaseTunes", "Base Tunes"),
            ("hcOutputTest", "Bench test"),
            ("hcBenchState", "Bench state and refusals"),
            UX.SEP,
            ("hcCtrlDlg", "Controller and identity"),
            ("hcUnusedSettings", "Unused settings"),
            ("hcUnusedIo", "Unused pin assignments"),
            UX.SEP,
            ("GROUP", "Developer diagnostics", DEV_MENU),
        ]),
        ("&Diagnostics", [
            ("hcStatusOverview", "Status overview"),
            UX.SEP,
            ("GROUP", "Why?", [
                ("hcWhyNoSync", "Why is there no sync?"),
                ("hcWhyNoSpark", "Why is there no spark?"),
                ("hcWhyFuelCut", "Why is fuel cut?"),
                ("hcWhyThrottle", "Why is the throttle disabled?"),
                ("hcWhichSensor", "Which sensor failed?"),
            ]),
            UX.SEP,
        ] + diag_entries()),
        # rusEFI's own spelling (`menu = "Help"`), which TunerStudio merges.
        ("Help", [
            ("hcHelpInfo", "HaniCore setup order"),
        ]),
    ]

    # WHAT THE MENU IS ALLOWED TO NAME comes from the emitted text so far, not
    # from a plan - V37's unreachable dialog is why this file asks the OUTPUT.
    declared_ids = set(re.findall(
        r"^\s{0,4}(?:dialog|curve|table)\s*=\s*(\w+)\s*,",
        chr(10).join(L), re.M))
    # The table editors declare `<tid>Map`; the editable-grid and 3D-view
    # dialogs are declared by UI.table_dialog_lines() and are already in there.

    w("[Menu]")
    w('   menuDialog = main')
    menu_lines, menu_bad, seen_ids = UX.emit_menu(TAIL, declared_ids)
    if menu_bad:
        raise SystemExit("the menu does not resolve: " + "; ".join(menu_bad))
    for _line in menu_lines:
        w(_line)

    # AND NOTHING ANYWHERE ELSE MAY GO MISSING EITHER. The check above reads
    # `ui_plan` - the dialogs the MODEL produced - so it was structurally blind
    # to DIAG_DIALOGS, to the bench dialogs and to every other hand-written
    # block in this file. That is exactly how V37 shipped `hcDiagRamProbe`
    # unreachable with 47/47 gates green.
    #
    # So the last thing this generator does is read back ITS OWN OUTPUT and
    # require every declared dialog to be reachable from a top-level menu,
    # directly or through a `panel`. It asks the question of the emitted text,
    # not of the plan, which is the only form of the question that cannot be
    # answered by a table that has drifted from what was written.
    decl, refs, panels = {}, set(), {}
    cur = None
    for ln in L:
        m = re.match(r"^\s{0,4}(dialog|curve|table)\s*=\s*(\w+)\s*,", ln)
        if m:
            cur = m.group(2)
            decl[cur] = m.group(1)
            panels.setdefault(cur, set())
            continue
        m = re.match(r"^\s*panel\s*=\s*(\w+)", ln)
        if m and cur:
            panels[cur].add(m.group(1))
            continue
        m = re.match(r"^\s*(?:subMenu|groupChildMenu)\s*=\s*(\w+)", ln)
        if m:
            refs.add(m.group(1))

    # `std_*` are TunerStudio's OWN built-in menu entries, not ours to declare.
    # rusEFI uses std_separator 30 times and std_ms3SdConsole once in the file
    # this corpus is taken from; a generator that required them to be declared
    # would refuse the corpus itself.
    refs = {r for r in refs if not r.startswith("std_")}
    dangling = sorted(r for r in refs if r not in decl)
    if dangling:
        raise SystemExit("menu entries name things this file never declares: "
                         "%s" % dangling)

    reach, work = set(), [r for r in refs]
    while work:
        did = work.pop()
        if did in reach:
            continue
        reach.add(did)
        work.extend(panels.get(did, ()))

    orphans = sorted(d for d, kind in decl.items()
                     if kind == "dialog" and d not in reach)
    if orphans:
        raise SystemExit(
            "THESE DIALOGS ARE DECLARED AND REACHABLE FROM NO MENU: "
            "%s. "
            "A dialog nobody can open is a feature that does not exist - see "
            "hcDiagRamProbe in V37." % orphans)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Whitespace at a line end has no TunerStudio meaning and makes a release
    # diff noisy; normalize it here so the versioned generated contract is
    # reproducible as well as syntactically valid.
    L = public_och_comments([line.rstrip() for line in L])
    L_dev = L
    L = user_project(L_dev)
    OUT.write_text("\n".join(L) + "\n", encoding="ascii", newline="\n")
    OUT_VERSIONED.write_text("\n".join(L) + "\n", encoding="ascii", newline="\n")
    print(f"wrote {OUT}")
    print(f"wrote {OUT_VERSIONED}")

    # Post-event view.  Ordinary polling keeps the block the firmware
    # publishes; only this explicitly loaded companion requests the bounded
    # read-only extension above it.
    #
    # THE BASE IS TGT_OCH_SIZE AND IT WAS HARDCODED 680 UNTIL V58.
    # send_och() serves every offset at or above TGT_OCH_SIZE from
    # hc_lf_export_byte(off - TGT_OCH_SIZE), so the live-Burn record starts
    # exactly where the ordinary block ends. 680 was TGT_OCH_SIZE at V48; V55
    # grew it to 722 and this literal did not move, so every lf* channel in
    # the shipped forensic .ini named a word TWENTY-ONE EARLIER than the one
    # it printed - lfCursor read the "HC" magic, and it took a bench session
    # to notice. Derived now, and the one number that can move is the one the
    # firmware already declares.
    forensic_names = {
        0: "lfMagic0", 1: "lfMagic1", 2: "lfVersion", 3: "lfLength",
        4: "lfFlags", 5: "lfEpoch", 6: "lfResetRaw", 7: "lfRequestMs",
        8: "lfBaseWindows", 9: "lfBaseEntries", 10: "lfBaseSuccess",
        11: "lfBaseFail", 12: "lfReleaseId", 13: "lfRecovery",
        14: "lfBootId", 15: "lfIntegrity", 16: "lfStageMs",
        17: "lfFirstWriterMs", 18: "lfAdmitMs", 19: "lfAdmitT7",
        20: "lfWindowSeq", 21: "lfCursor", 22: "lfWriterEntry",
        23: "lfWriterReturn", 24: "lfCommandSeq", 25: "lfVerifySeq",
        26: "lfCommandT7", 27: "lfVerifyT7", 28: "lfReturnT7",
        29: "lfRestoreT7", 30: "lfSaveCC7IC", 31: "lfSaveT8IC",
        32: "lfSaveSSCTIC", 33: "lfSaveSSCRIC", 34: "lfSaveSSCEIC",
        35: "lfDuringCC7IC", 36: "lfDuringT8IC", 37: "lfDuringSSCTIC",
        38: "lfDuringSSCRIC", 39: "lfDuringSSCEIC", 40: "lfLostLast",
        41: "lfLostOr", 42: "lfFirstLostPos", 43: "lfFirstLostT7",
        44: "lfEntrySSCON", 45: "lfEntryPECC0", 46: "lfEntryPECC4",
        47: "lfEntryPort", 48: "lfEntryT8REL", 49: "lfEntryT8",
        50: "lfEntryT0", 51: "lfEntryCC7", 52: "lfMaxWindowT7",
        53: "lfLastWindowT7", 54: "lfAdmission", 55: "lfBoundaryMark",
        96: "lfNmiStarted", 97: "lfNmiComplete", 98: "lfNmiTFR",
        99: "lfNmiT7", 100: "lfNmiWDT", 101: "lfNmiWDTCON",
        102: "lfNmiSP", 103: "lfNmiCP", 104: "lfNmiIP",
        105: "lfNmiCSP", 106: "lfNmiOldPSW", 107: "lfNmiPSW",
        108: "lfNmiP3", 109: "lfNmiP6", 110: "lfNmiCC7IC",
        111: "lfNmiT8IC", 112: "lfNmiSSCTIC", 113: "lfNmiSSCRIC",
        114: "lfNmiSSCEIC", 115: "lfNmiSSCON", 116: "lfNmiT8REL",
        117: "lfNmiT8", 118: "lfNmiT0", 119: "lfNmiCC7",
        120: "lfNmiPECC0", 121: "lfNmiPECC4", 122: "lfNmiOwnerRaw",
        123: "lfNmiCbStateRaw", 124: "lfNmiCbPosRaw", 125: "lfNmiAsicState",
        142: "lfNmiTickMs", 143: "lfNmiCommandSeq",
        144: "lfAsicLastLaunchMs", 145: "lfAsicLastDoneMs",
        146: "lfAsicMaxGapMs", 147: "lfAsicLastGapMs",
        148: "lfAsicSeq", 149: "lfAsicSlot", 150: "lfFirstAnomaly",
        151: "lfSscIsrT7", 152: "lfSscIsrCount", 153: "lfSscIsrPec",
        154: "lfTickLastT7", 155: "lfTickLastGap", 156: "lfTickMaxGap",
        157: "lfWriterResult",
    }
    forensic = []
    for line in L_dev:
        if line.strip().startswith("ochBlockSize"):
            forensic.append("   ochBlockSize   = %d" % OCH_READ_SIZE)
            for i in range(172):
                name = forensic_names.get(i, "lfWord%03d" % i)
                forensic.append('   %-16s = scalar, U16, %4d, "", 1, 0'
                                 % (name, OCH_SIZE + i * 2))
        else:
            forensic.append(line)
    OUT_FORENSIC.write_text("\n".join(forensic) + "\n",
                            encoding="ascii", newline="\n")
    print(f"wrote {OUT_FORENSIC}  (post-event 1024-byte read-only view)")

    # ============================ THE [UserDefined] FALLBACK ===============
    #
    # [UiDialogs] is the section TunerStudio 3.3.01 asks for by name while it
    # loads a file using [UserDefined], and rusEFI's own .junie/ts-help-topic.md
    # documents both spellings. But the 40-file corpus uses only [UserDefined],
    # so nothing in this repository PROVES [UiDialogs] loads, and the project
    # rule is not to emit a shape no known-good file uses.
    #
    # Shipping both settles it in one bench minute instead of one release
    # cycle: open the primary, and if TunerStudio refuses the section, open the
    # fallback. DERIVED, never hand-edited - the whole diff is the section
    # header, and OUT_FALLBACK is written from the same list of lines.
    fb_lines = [("[UserDefined]" if ln.strip() == "[UiDialogs]" else ln)
                for ln in L]
    n_swapped = sum(1 for a, b in zip(L, fb_lines) if a != b)
    if n_swapped != 1:
        raise SystemExit("the fallback differs from the primary in %d lines, "
                         "and it must differ in exactly one" % n_swapped)
    OUT_FALLBACK.write_text("\n".join(line.rstrip() for line in fb_lines) + "\n", encoding="ascii", newline="\n")
    print(f"wrote {OUT_FALLBACK}  ([UserDefined] fallback, 1 line differs)")
    print(f"  signature   {SIGNATURE!r}")
    print(f"  baud        {BAUD} (set it in the TunerStudio project)")
    print(f"  page        {PAGE_SIZE} bytes")
    print(f"  channels    {len(CH)}, block {OCH_SIZE} bytes, "
          f"highest offset {max(o + (4 if t == 'U32' else 2) for o,n,t,u,c in CH) - 1}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
