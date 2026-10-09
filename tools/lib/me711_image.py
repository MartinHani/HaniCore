#!/usr/bin/env python3
r"""
me711_image.py - ONE place that names the Bosch image under test.

WHY THIS FILE EXISTS, and it is not tidiness.

Every Bosch gate used to hardcode its own copy of the image path. When the
build's output was renamed from `..._umkom_responder_v19.bin` to
`..._runtime_v20.bin`, SIX tools kept loading V19 - and they kept PASSING,
because a V19 binary really does pass a V19 audit. Two of them reported 22/22
and 23/23 against an image that was not the one that had just been built.

`me711_umkom_proof.py` is the only one that failed, and it failed for an
instructive reason: it resolves symbol addresses from the freshly-linked
`.M66` map but loaded the stale `.bin`, so it called V20's `hc_umkom_service`
address inside V19's code and read an unmapped address. A mismatch that
crashes is lucky; a mismatch that quietly passes is the dangerous one.

That is the same failure mode `me711_umkom_proof._sym()` already documents
one level down ("this proof cannot drift out of sync with the build the way
hardcoded addresses did across V14..V19"). The image path needed the same
treatment.

So: the path is declared HERE, once. `image()` also cross-checks the binary
against the build manifest the builder writes beside it, so a gate can never
again audit an image that a different build produced.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# HANICORE_ME711_BINS points a long run at a SNAPSHOT of the image, map and
# manifest, so a rebuild during a 20-minute simulation cannot hand it a map
# from one link and bytes from another (2026-10-06).
BINS = Path(os.environ.get("HANICORE_ME711_BINS", str(ROOT / "bins/hanicore")))

# THE CURRENT BOSCH OEM ME7.1.1 DEVELOPMENT IMAGE. Bumping a version is this line
# and the matching OUT_BIN/OUT_HEX/OUT_MANIFEST in
# tools/build/build_hanicore_me711.py - nothing else.
# V62 IS FROZEN. It was flashed, physically qualified and released as
# AE8F2F96CDB7BB36DF4446202C08EFDE2A8202350C622EA99053292916B81A19, and its
# release directory and evidence are not to be regenerated. The DEFAULT is the
# development image, for exactly the reason the V29 note below gives: a V63
# build living in a file named v62 is how six gates once audited a stale
# binary. Point a gate at the frozen one with HANICORE_ME711_STEM when that is
# genuinely what is wanted.
STEM = os.environ.get("HANICORE_ME711_STEM",
                      "HaniCore_ME711_v102_dev")

# STEM -> the build name its manifest carries.
#
# EVERY IMAGE UP TO V28 KEEPS ITS "A1146" FILENAME, and that is deliberate.
# Those files are historical evidence - several were flashed to an ECU and the
# bench result is recorded against that exact name - so the porsche -> bosch
# rename does not reach them. It reached this table instead, which pointed
# every historical stem at a file that does not exist and made it impossible
# to run any gate against any previous image. V29 is the first build named
# under the new scheme because it is the first one created under it.
EXPECTED_BUILD = {
    "HaniCore_ME711_A1146_runtime_v20": "RUNTIME_V20",
    "HaniCore_ME711_A1146_mainrelay_v21": "MAIN_RELAY_V21",
    "HaniCore_ME711_A1146_mainrelay_v22": "MAIN_RELAY_V22",
    "HaniCore_ME711_A1146_mainrelay_v23": "MAIN_RELAY_V23",
    "HaniCore_ME711_A1146_mainrelay_v24": "MAIN_RELAY_V24",
    "HaniCore_ME711_A1146_mainrelay_v25": "MAIN_RELAY_V25",
    "HaniCore_ME711_A1146_mainrelay_v26": "MAIN_RELAY_V26",
    "HaniCore_ME711_A1146_v27_trigger_bench": "V27_TRIGGER_BENCH",
    "HaniCore_ME711_A1146_v27a_trigger_audit_fix": "V27A_TRIGGER_AUDIT_FIX",
    "HaniCore_ME711_A1146_v28_trigger_comm": "V28_TRIGGER_COMM",
    # V29 is FROZEN as the physical-test candidate. It stays in the
    # registry so a gate can still be pointed at it with
    # HANICORE_ME711_STEM, but the default is the development image -
    # a V30 build living in a file named v29 is exactly the kind of
    # trap that had six gates auditing a stale binary once before.
    "HaniCore_ME711_v29_universal_config": "V29_UNIVERSAL_CONFIG",
    "HaniCore_ME711_v30_dev_engine": "V30_DEV_ENGINE",
    "HaniCore_ME711_v31_power_fuel_dbw": "V31_POWER_FUEL_DBW",
    "HaniCore_ME711_v32_ts_namespace": "V32_TS_NAMESPACE",
    "HaniCore_ME711_v33_dbw_closed_loop": "V33_DBW_CLOSED_LOOP",
    "HaniCore_ME711_v34_relay_bench": "V34_RELAY_BENCH",
    "HaniCore_ME711_v35_burn_persistence": "V35_BURN_PERSISTENCE",
    "HaniCore_ME711_v36_burn_bounded": "V36_BURN_BOUNDED",
    "HaniCore_ME711_v37_ram_probe": "V37_RAM_PROBE",
    "HaniCore_ME711_v38_commissioning": "V38_COMMISSIONING",
    "HaniCore_ME711_v40_resetless_burn": "V40_RESETLESS_BURN",
    "HaniCore_ME711_v41_resetless_burn_fix": "V41_RESETLESS_BURN_FIX",
    "HaniCore_ME711_v42_resetless_burn_robust": "V42_RESETLESS_BURN_ROBUST",
    "HaniCore_ME711_v43_resetless_burn_robust": "V43_RESETLESS_BURN_ROBUST",
    "HaniCore_ME711_v44_resetless_burn_robust": "V44_RESETLESS_BURN_ROBUST",
    "HaniCore_ME711_v45_burn_reset_forensics": "V45_BURN_RESET_FORENSICS",
    "HaniCore_ME711_v47_live_burn_hybrid_qual": "V47_LIVE_BURN_HYBRID_QUAL",
    "HaniCore_ME711_v48_live_burn_call_clobber_fix": "V48_LIVE_BURN_CALL_CLOBBER_FIX",
    "HaniCore_ME711_v49_live_burn_nmi_forensics": "V49_LIVE_BURN_NMI_FORENSICS",
    "HaniCore_ME711_v50_ir_preserving_mask": "V50_IR_PRESERVING_MASK",
    "HaniCore_ME711_v51_ssc_frame_phase": "V51_SSC_FRAME_PHASE",
    "HaniCore_ME711_v52_yield_services_wdt": "V52_YIELD_SERVICES_WDT",
    "HaniCore_ME711_v53_store_above_bootsum": "V53_STORE_ABOVE_BOOTSUM",
    "HaniCore_ME711_v54_flash_fault_exit": "V54_FLASH_FAULT_EXIT",
    "HaniCore_ME711_v55_generic_trigger": "V55_GENERIC_TRIGGER",
    "HaniCore_ME711_v56_cam_absent_burn_fix": "V56_CAM_ABSENT_BURN_FIX",
    "HaniCore_ME711_v57_burn_session_fix": "V57_BURN_SESSION_FIX",
    "HaniCore_ME711_v58_crank_glvl_collision": "V58_CRANK_GLVL_COLLISION",
    "HaniCore_ME711_v59_forensic_window": "V59_FORENSIC_WINDOW",
    "HaniCore_ME711_v60_burn_refusal": "V60_BURN_REFUSAL",
    "HaniCore_ME711_v61_board_defaults": "V61_BOARD_DEFAULTS",
    "HaniCore_ME711_v62_real_routing": "V62_REAL_ROUTING",
    "HaniCore_ME711_v63_engine_backend": "V63_ENGINE_BACKEND",
    # V64 IS FROZEN at E87BE233BFFDF26FFA1CE2164F8080B4408F1BD06F990F59098DA0
    # 865485AC98. It stays here so a gate can be pointed at it with
    # HANICORE_ME711_STEM - me711_plan_cost_proof's before/after and the
    # vector diary's negative control both want it - but it is no longer the
    # default, because a V65 build living in a file named v64 is the exact
    # trap the V29 note above describes.
    "HaniCore_ME711_v64_hot_path": "V64_HOT_PATH",
    "HaniCore_ME711_v65_code_space": "V65_CODE_SPACE",
    # V66. V65 is SUPERSEDED and was never flashed: it carries the V63 DBW
    # enable-persistence regression that me711_dbw_bench_proof has been red
    # for since V63. It stays in this table only so a gate can be pointed at
    # it as a control.
    "HaniCore_ME711_v66_dbw_release": "V66_DBW_RELEASE",
    # V67. The generic half of V63's release regression, which V66 left: the
    # cold path drove CAMSOL/FUELPUMP/BOOST to an inactive level and kept them
    # OUTPUTS. me711_armed_off_release_proof goes 4/5 -> 5/5 here and DP2
    # returns to V62's 0x0000. It is V66 that must FAIL that gate, not this.
    "HaniCore_ME711_v67_output_release": "V67_OUTPUT_RELEASE",
    # V68. The tooth path converted angle to time with the literal 60 -
    # the tooth width of a SIXTY TOOTH WHEEL - so every scheduled edge on
    # any other wheel fired late by tooth_x10/60 of its offset. Kept as
    # the control for me711_tooth_deadline_proof: V67 must FAIL it on 36,
    # 24 and 12 teeth and PASS it on 60.
    "HaniCore_ME711_v68_tooth_window": "V68_TOOTH_WINDOW",
    # V69. seed_cursors() left every cursor on an anchor the NEXT tooth
    # had already passed, so the tooth after sync acquisition issued
    # three catch-ups at once. That burst is the whole difference
    # between the worst tooth of a revolution and the steady one.
    "HaniCore_ME711_v69_seed_burst": "V69_SEED_BURST",
    # V70. hc_hal_out_group() - the hot path every coil and injector is
    # driven through - ended both its branches with an unconditional
    # DPx |=, so sixteen pins stayed DRIVEN after being commanded off.
    # The third place V63's release regression lives. Kept as the
    # control for me711_group_off_release_proof, which V69 must FAIL.
    "HaniCore_ME711_v70_group_release": "V70_GROUP_RELEASE",
    # V71. The VAG 1.8T preset - the FIRST ENGINE - declared a cam cycle
    # sync mode it had no geometry for, so from V63 it was REFUSED by
    # hc_validate() and could never arm an output. Kept as the control
    # for me711_preset_validates_proof, which V70 must FAIL.
    "HaniCore_ME711_v71_preset_runnable": "V71_PRESET_RUNNABLE",
    # V72. The build now REFUSES stale generated sources - and the first
    # thing it caught was V71 itself: the committed hc_presets.c had
    # preset 2's syncMode as 1 where hanicore_presets.py says 2, so V71's
    # binary did not correspond to its own committed config source.
    "HaniCore_ME711_v72_build_integrity": "V72_BUILD_INTEGRITY",
    # V73. DBW_INIT existed in hc_dbw.h and in the .ini's dbwState
    # decode from the day the module was written, and NOTHING EVER
    # ASSIGNED IT - the controller went OFF -> RUN and the first pass
    # with plausible sensors commanded the motor. Kept as the control
    # for me711_dbw_init_proof, which V72 must FAIL.
    "HaniCore_ME711_v73_dbw_init": "V73_DBW_INIT",
    # V74. THE FIRST POST-V63 CANDIDATE INTENDED FOR THE BENCH ECU.
    # Everything accumulated since V63: the three output-release fixes
    # (12P throttle, 12Q generic, 12T coils/injectors), DBW_INIT, the
    # LKG walk-back, dead-cam demotion, the generic decoder, Hall-crank
    # routing, the V68/V69/V70 scheduler work, build-integrity
    # protection, and six dead DBW knobs no longer exposed as fields.
    "HaniCore_ME711_v74_bench_candidate": "V74_BENCH_CANDIDATE",
    # V75. THE MAIN RELAY AND THE FUEL PUMP STOP LATCHING FAULT AT BOOT, the
    # relay drives its configured cavity, and an OFF always releases the pin.
    "HaniCore_ME711_v75_relay_pump": "V75_RELAY_PUMP",
    # V76. THE EKP STAGE IS ACTIVE-LOW, MEASURED with a logic analyzer on
    # cavity 65: V75 drove it HIGH for ON (cavity open) and LOW for 13-14 us
    # on every release (cavity sinking). Per-stage level in the HAL + bench.
    "HaniCore_ME711_v76_ekp_polarity": "V76_EKP_POLARITY",
    # V77. Engine position on the bench: a stall is not a sync loss, the
    # capture inputs' live levels are published, and cold modules' near data
    # moves into the on-chip XRAM the startup already enables.
    "HaniCore_ME711_v77_engine_position": "V77_ENGINE_POSITION",
    # V78. The Porsche-native I/O: MAIN_RELAY routes to the CJ910's own MR
    # stage (cavity 23, a hardware function), KL15_STAT is published, the
    # CJ120 chip selects are driven deselected, and TunerStudio shows
    # temperatures and the ignition map in the units the firmware uses.
    "HaniCore_ME711_v78_native_io": "V78_NATIVE_IO",
    # V79. The ASIC's output ports as the OEM sends them (N75, EVAP, heaters,
    # NLEN_AS), controlled key-off through run-on, the CJ120s on the shared
    # SSC, LSU 4.2 lambda, the OEM CLT/IAT curves, DBW armed at runtime.
    "HaniCore_ME711_v79_asic_runon": "V79_ASIC_RUNON",
    # V80. V79 measured on the ECU: keep-alive requested on KL15-fall is too
    # late, so it is PRE-ARMED while the native relay is routed; and a LIVE
    # write now unblocks a refused staged transaction.
    "HaniCore_ME711_v80_runon": "V80_RUNON",
    # V81. NCODE was full (2 bytes). The cold setup modules - validation,
    # the config manager, the bench qualifier, analog routing - are FAR code
    # in FCODE, reached from NCODE through far thunks (hcfarbridge.h).
    "HaniCore_ME711_v81_far_cold": "V81_FAR_COLD",
    # V82. CJ120 IDENT is checked and INIT_REG1 re-verified; lambda is
    # withheld until the pump current has been seen away from zero (a
    # missing sensor reads exactly zero); the cam solenoid stages (115/120,
    # MAIN POUT0/POUT1) get a bounded bench mode at the OEM 250 Hz.
    "HaniCore_ME711_v82_asic_io": "V82_ASIC_IO",
    # V83. The config apply's critical section raises ILVL to 13 instead of
    # clearing IEN (IEN = 0 stops PEC and overran the S5500 frame); the
    # validator's claim list is static (user stack 184 -> ~40 B lighter); the
    # throttle bridge is driven per the CJ220 truth table (EGENFR active low,
    # mode-0 PWM, IN1 latch follows IN2); DBW normalisation carries direction.
    "HaniCore_ME711_v83_first_start": "V83_FIRST_START",
    # V84. No user-facing output arm: CFG_OUTPUTS_ARMED is a retired page
    # byte (layout unchanged); hcsafety's bit 0x10 is KEY-OFF. Normal engine
    # outputs follow the crank/scheduler, bench tests their own bounded
    # command. And the hot/group output path now releases on OFF whatever
    # the permission (it used to discard an OFF after the permission fell).
    "HaniCore_ME711_v84_no_user_arm": "V84_NO_USER_ARM",
    # V85. V84 + DBW: the first RUN step seeds the rate limiter from the
    # plate and suppresses the derivative kick; LSU heater: rusEFI envelope
    # (ramp 7 -> 12 V at 0.4 V/s, then HOLD the nominal 7.5 V - V79..V84
    # held 12 V); descriptor: the wideband block from the ME7.1.1 schematic's hidden
    # lower half (70/51/71/52, 13/12/14/15, heaters 5/4) locked.
    "HaniCore_ME711_v85_vehicle_prep": "V85_VEHICLE_PREP",
    # V86. V85 + the engine preset actually applies: '!E' -> one validated
    # transaction (undo log, whole-page check, no Burn); TunerStudio re-reads
    # the page via [EventTriggers]; enginePreset labels indexed by id (V85
    # showed the 1.8T name on the board-default id); CLT 93 / IAT 26 routable
    # as ASIC AN0/AN1; 1.8T preset adds CLT/IAT, batch, wasted COP, lambda off.
    "HaniCore_ME711_v86_preset_apply": "V86_PRESET_APPLY",
    # V87. V86 + the preset OCH words 764..775 cleared at boot. V86 left them
    # as battery-backed SRAM found them (bench ECU read presetResult 0xFF03 at
    # power-up), and a stale 772 PENDING word applied a preset at boot -
    # me711_preset_gap_proof BOOT, which V86 FAILS. V86 is frozen (flashed).
    "HaniCore_ME711_v87_preset_apply": "V87_PRESET_APPLY",
    # V88. V87 + the 1.8T preset carries the STOCK AWT calibration read out of
    # the stock 4B0906018DC ME7.5 binary: displacement 1781 (KUMSRL-checked),
    # injector 301 cc/min equivalent (KRKTE via FR RKTI), dead time (TVUB),
    # dwell (KFSZT), pressure sensor 541 hPa/V (DSLGRAD/DSLOFS). Firmware
    # changed only in the generated preset table and the version text.
    "HaniCore_ME711_v88_stock_awt": "V88_STOCK_AWT",
    # V89. V88 + the AWT preset selects load source THROTTLE with a VE table
    # solved from the stock ME7 throttle model (the AWT pressure sensor is
    # upstream of the throttle); preset n_items 16-bit; undo log 0x0A00.
    "HaniCore_ME711_v89_alphan_awt": "V89_ALPHAN_AWT",
    # V90. The first AWT vehicle test's blockers: the 60-2 gap step (every
    # spark after the first lost, coils held ON), a hard 1.5x maximum dwell,
    # the planner run from the serial yield (50 ms latency), Burn persisting
    # restart-required values (displacement 0), grabs reaching DESIRED, APP/TPS
    # plausibility honouring the configured correlation, CLT cold end, and a
    # complete AWT preset (trigger source, pump mode, 92 deg reference, pedal,
    # throttle body, DBW limits).
    "HaniCore_ME711_v90_first_start_awt": "V90_FIRST_START_AWT",
    # V91. V90 + the AWT coolant input: the Porsche board holds TMOT's
    # switched 340 R pull-up ON (bench open reads 1015 = the FET-on model;
    # off would be 958 like TANS), so the AWT preset takes the OEM curve for
    # that state [BIN 0x81F976]; the car's raw 923 is ~15 C, not -40 C.
    # Measured and control CLT published separately (no displayed 80 C).
    "HaniCore_ME711_v91_first_start_clt": "V91_FIRST_START_CLT",
    # V92. First-run fixes from the 2026-09-27 AWT start: batch fuel x0.5,
    # stale-now early execution, tooth correction instead of sync loss,
    # Quick-Start cam phase by level sampling, tooth log, DBW/wideband work.
    "HaniCore_ME711_v92_awt_runtime": "V92_AWT_RUNTIME",
    # V93: V92 + the second-vehicle-session work: ETB bridge at the OEM 2 kHz,
    # ETB endpoint calibration by stop confirmation, autotune telemetry, the
    # compression profile surviving a reset, boot history, commissioning tools.
    "HaniCore_ME711_v93_awt_commission": "V93_AWT_COMMISSION",
    # V94 (research/kwp-vehicle-mode): V93 r2 + the link work - pipelined
    # echo accounting, then 124800 with fallback. Not a car candidate yet.
    "HaniCore_ME711_v94_link": "V94_LINK",
    # V95 (research/kwp-vehicle-mode): V94 + the two bench findings - a host
    # at 115200 is followed (bytes no request starts with are rate evidence,
    # one per burst), and an abandoned KWP session ends on a run of bad frames
    # instead of being kept alive by them. linkDiag OCH 848.
    "HaniCore_ME711_v95_link": "V95_LINK",
    # V96 (master): V95 LINK + the output-route safety fix (cavities 18/22 -
    # the CJ120 chip selects - locked, reserved CPU pins, HAL-bound output
    # validation, NOT_ON_MAIN_CPU unroutable), the wideband rework (CJ120
    # mode control: calibration RA+LA, pump only when hot; Ri closed-loop
    # heater; lambda validity), GOFAST 115200. OCH block 872.
    "HaniCore_ME711_v96_wideband": "V96_WIDEBAND",
    # V97 (master, DEVELOPMENT - not frozen): V96 + the post-V96 backlog:
    # both wideband banks through the shared hcwb_pair_step (host-tested),
    # the raw pump current per bank (OCH 872/874, block 876), the warm-sensor
    # fast path and UR saturation = open; later the trigger framework etc.
    "HaniCore_ME711_v97_dev": "V97_DEV",
    # V98 (master, DEVELOPMENT - not frozen): the standalone-ECU pass of
    # 2026-10-01 - load strategies + MAP estimate, per-consumer sensor
    # fallbacks, signed spark, firing order, lambda table axes, DFCO, closed
    # loop, rev limiter modes, launch/flat shift/anti-lag/rotational idle,
    # priming, injection phase table, the TunerStudio fast block, Tune
    # Analyze and the tooth logger. The V97 dev image (e5ed195, E3D11C66)
    # is its negative control.
    "HaniCore_ME711_v98_dev": "V98_DEV",
    # V99 (master, DEVELOPMENT - not frozen): the vehicle diagnostics pass
    # of 2026-10-02 after the first V98r2 car session - ETB stop test and
    # direction-to-stop tests, non-latching overdwell, lambda dynamics gate,
    # the event ring. V98r2 (9BF22D32, the car image) is its control.
    "HaniCore_ME711_v99_dev": "V99_DEV",
    # V100 (master, DEVELOPMENT - not frozen): the pass that followed the
    # first AWT car night - the lambda heater POLICY and its afterrun, the
    # open-cell discriminator, the ETB AutoCal reference refusal, the
    # main-loop scheduler yield, the Alpha-N load-axis re-bin and the
    # multi-rate vehicle logger/analyser.
    # V100_CHANGES.md. V99 dev is its control.
    "HaniCore_ME711_v100_dev": "V100_DEV",
    "HaniCore_ME711_v101_dev": "V101_DEV",
    "HaniCore_ME711_v102_dev": "V102_DEV",
}.get(STEM)
if EXPECTED_BUILD is None:
    raise SystemExit(f"unknown HANICORE_ME711_STEM {STEM!r}")

# ============================ HOW LONG THIS IMAGE TAKES TO REACH ITS RUNTIME ==
#
# In SIMULATOR STEPS, and it lives here for the same reason the stem does:
# there is one place a fact about the image under test is written down.
#
# Half the gates in this tree inject a TunerStudio request at a fixed step and
# then run for a fixed number more. Those constants were 750 000 and 1 200 000,
# chosen when boot reached the runtime well inside them. V39's append-only
# calibration store changed that: hc_nvm_boot() scans sixteen 8 KiB cells
# before the supervision link is brought up, and a BLANK cell has its whole
# 8188-byte body read because "usable as a target" means "completely erased".
# That is 1 187 437 instructions, so this image's first hc_asic_start_service
# entry is at step 2 482 756 - measured by tests/firmware/build/me711_boot_cost_proof.py,
# which is the gate that OWNS the number and reports both halves of it.
#
# A gate that injects before that is talking to an ECU which is still booting,
# and the honest report - "no valid envelope in the transmitted stream" - reads
# exactly like a broken firmware. Four gates failed that way at once.
#
# Too large only costs simulator time - and it costs it in every gate that
# uses it, ~14 rig runs in the service-gap proof alone - while too small
# silently tests nothing. 3 000 000 is 21 % clear of the measured 2 482 756
# and every gate here adds its own run window on top.
BOOT_STEPS = 3_000_000

IMG = BINS / f"{STEM}.bin"
HEX = BINS / f"{STEM}.hex"
MANIFEST = BINS / f"{STEM}.json"

# The exact linked map archived with the frozen image. Never point a frozen
# gate at the mutable target build directory: the next development link may
# legitimately replace that directory while V20 remains the flash candidate.
MAP = BINS / f"{STEM}.M66"

# The hardware-confirmed rollback floor. Immutable; never a test target unless
# a gate explicitly asks for it by name.
V19 = BINS / "HaniCore_ME711_A1146_umkom_responder_v19.bin"
V19_SHA = ("F98157D15883641F05BAF5D3C65862F5048692FFD22A33AA7ADF16332EB7DA6F")


def image(check_manifest: bool = True) -> Path:
    """The image under test, verified against its own build manifest.

    Raises rather than returning a stale or mismatched file: a gate that
    audits the wrong binary is worse than a gate that does not run.
    """
    if not IMG.exists():
        raise SystemExit(
            f"{IMG.name} is missing - run "
            f"`py tools\\build\\build_hanicore_me711.py` first")
    if check_manifest and MANIFEST.exists():
        want = json.loads(MANIFEST.read_text()).get("sha256", "")
        got = hashlib.sha256(IMG.read_bytes()).hexdigest()
        if want and got.lower() != want.lower():
            raise SystemExit(
                f"{IMG.name} does not match {MANIFEST.name}\n"
                f"  manifest {want}\n  file     {got}\n"
                f"the image and its manifest are from different builds")
    return IMG


def sha256(path: Path | None = None) -> str:
    return hashlib.sha256((path or IMG).read_bytes()).hexdigest().upper()


def metadata() -> dict:
    return json.loads(MANIFEST.read_text())


if __name__ == "__main__":
    p = image()
    print(f"image    {p}")
    print(f"sha256   {sha256(p)}")
    print(f"map      {MAP}")
    print(f"rollback {V19.name}  {V19_SHA}")


# ---------------------------------------------------------------------------
# WHERE A TEST RIG MAY PUT ITS OWN STACK, and why this lives here.
#
# The host rigs execute functions out of the linked image by pointing R0 -
# Keil's software stack pointer - somewhere in near RAM and calling. If that
# somewhere is not inside ?C_USERSTACK, the harness writes its own call frames
# over the module it is measuring, and the corruption is then reported as a
# defect in the firmware.
#
# THIS HAS HAPPENED THREE TIMES:
#
#   1. me711_trigger_test used a literal 0xF9F0, which landed in
#      ?ND0?HCSCHED_DRY. Fixed by deriving the base from the map - and adding
#      a literal 0x200 for the size.
#   2. That 0x200 outlived the stack it described. The ME7.1.1 user stack was
#      cut from 512 to 256 bytes after being MEASURED at 26, so the rig started
#      R0 at 0xF900 - 256 bytes inside HCSCHED_DRY's statics. Nothing showed
#      until plan_tooth began calling hc_plan_*, which deepened the call chain
#      enough to reach cap_angle[] and zero the capture ring mid-plan. The
#      symptom was an event executing with a zero delta: a perfect imitation of
#      a scheduler bug.
#   3. me711_config_state_test still had the ORIGINAL 0xF9F0, and hc_cfg is at
#      0xF98C. The harness had been writing its call frames over the first
#      hundred bytes of the configuration page - which is the very thing that
#      gate exists to test - and passing 76 of 77 checks anyway. CFG_CYLINDERS
#      is at offset 2, and it read back 251.
#
# Three occurrences of one mistake is a missing function, so here it is. The
# size comes from the same DSB the linker read, the base from the map, and the
# result is CHECKED against every near segment rather than trusted.
START = (ROOT / "firmware/targets/me711/system/start_me711.a66")


def user_stack_size() -> int:
    """?C_USRSTKBOT's reservation, from the startup SOURCE."""
    import re
    m = re.search(r"\?C_USRSTKBOT:\s+DSB\s+([0-9A-Fa-f]+)H",
                  START.read_text(errors="replace"))
    if not m:
        raise SystemExit("?C_USRSTKBOT DSB not found in %s" % START)
    return int(m.group(1), 16)


def near_segments() -> list:
    """Every near-data segment in the linked map, as (lo, hi, name)."""
    import re
    out = []
    for line in MAP.read_text(errors="replace").splitlines():
        m = re.match(r"\s*([0-9A-F]{6})H\s+([0-9A-F]{6})H\s+[0-9A-F]{6}H\s+"
                     r"DATA\s+.*?(\?ND0\?\S+|\?C_USERSTACK)", line)
        if m:
            out.append((int(m.group(1), 16) & 0xFFFF,
                        int(m.group(2), 16) & 0xFFFF, m.group(3)))
    return out


def user_stack_top() -> int:
    """The value a rig should load into R0, verified not to overlap anything."""
    import re
    m = re.search(r"^\s+([0-9A-F]{6})H\s+\?C_USRSTKBOT\s",
                  MAP.read_text(errors="replace"), re.M)
    if not m:
        raise SystemExit("?C_USRSTKBOT not found in %s" % MAP.name)
    size = next((hi + 1 - lo for lo, hi, name in near_segments()
                 if name == "?C_USERSTACK"), None) or user_stack_size()
    # the map's reservation: the IMAGE's stack (a snapshot of another commit
    # may not match today's start_me711.a66)
    top = ((int(m.group(1), 16) & 0xFFFF) + size) & 0xFFFF
    assert_stack_clear(top)
    return top


def assert_stack_clear(top: int) -> int:
    """Refuse a rig stack that overlaps anything but ?C_USERSTACK."""
    for lo, hi, name in near_segments():
        if name == "?C_USERSTACK":
            continue
        if lo < top <= hi + 1:
            raise SystemExit(
                "rig stack top 0x%04X is inside %s (0x%04X-0x%04X). The "
                "harness would write its call frames over the code under test. "
                "Fix the derivation, not the segment." % (top, name, lo, hi))
    return top


def och_addr(at: int) -> int:
    """Battery-backed SRAM address of output-channel byte `at`: 0..1023 in
    TGT_RAM_OCH, 1024.. in TGT_RAM_OCH2 (both from hctarget.h - the OCH2
    region has moved before, and a typed literal then reads the wrong RAM)."""
    import re as _re
    h = (ROOT / "firmware/targets/me711/hctarget.h").read_text(errors="replace")

    def d(n):
        return int(_re.search(r"#define\s+%s\s+(0x[0-9A-Fa-f]+)" % n, h).group(1), 16)
    base = d("TGT_EXTRAM_BASE")
    return base + (d("TGT_RAM_OCH") + at if at < 1024 else d("TGT_RAM_OCH2") + at - 1024)
