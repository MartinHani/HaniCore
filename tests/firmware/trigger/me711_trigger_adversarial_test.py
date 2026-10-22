#!/usr/bin/env python3
"""Hostile linked-image checks which do not reuse decoder math as an oracle.

The normal trigger suite proves clean behavior.  These cases deliberately
exercise boundaries recovered independently from the OEM ME7.1.1 disassembly and
from modulo-16-bit timer arithmetic.  HANICORE_ME711_STEM selects the frozen
or corrected checkpoint through me711_image.py.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_image as PI
import me711_trigger_test as PT

# THE INTERRUPT-CONTROL BYTES ARE DERIVED, NOT TYPED.
#
# These used to be the literals 0x0072 / 0x006A / 0x0069, and V58 moved the
# crank capture off the drain tick's group priority - two enabled sources may
# not share an (ILVL, GLVL) pair, see hctarget.h - so the literal for CC15IC
# became 0x0073 and this gate failed for the right reason on a correct change.
# A hardcoded expectation for a value the target header owns tests the typist,
# so it is read from the header the firmware compiles against. The SHAPE is
# still pinned: xxIE set, the named level, the named group.
#
# AGAINST A FROZEN BINARY THIS READS THE CURRENT HEADER, which is the
# trap validate_me711_image's EXTS control already documents. Point it at
# an old image with HANICORE_ME711_STEM and a header that has moved since
# will fail it - correctly, because the pair is no longer being checked
# against the constants that image was built from. me711_irq_priority_proof
# owns the invariant that does not go stale: the pairs must be DISTINCT.
def _tgt_ic(ilvl_name, glvl_name, glvl_default):
    hdr = (Path(__file__).resolve().parents[3]
           / "firmware/targets/me711/hctarget.h"
           ).read_text(errors="replace")

    def d(name, default=None):
        m = re.search(r"^#define\s+" + re.escape(name) + r"\s+(\d+)", hdr, re.M)
        if m:
            return int(m.group(1))
        if default is None:
            raise SystemExit("%s is not defined in hctarget.h" % name)
        return default

    return 0x40 | (d(ilvl_name) << 2) | d(glvl_name, glvl_default)


IC_CRANK = _tgt_ic("TGT_ILVL_CRANK", "TGT_GLVL_CRANK", 2)
IC_CAM = _tgt_ic("TGT_ILVL_CAM", "__none__", 2)
IC_CAM2 = _tgt_ic("TGT_ILVL_CAM", "__none__", 1)
IC_SERIAL = _tgt_ic("TGT_ILVL_SERIAL", "TGT_GLVL_SERIAL", 2)



FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAIL
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<58} {detail}")
    FAIL += not ok


def write16(call: PT.Call, name: str, value: int) -> None:
    call.m.w16(PT.sym(name) & 0xFFFF, value & 0xFFFF)


def early_gap_case() -> tuple[PT.Engine, int, int, int]:
    """Inject one isolated 3x interval well before the real wheel gap."""
    e, _, period = PT.stable_case(800)
    for _ in range(10):
        e.wait_edge(period)
    before_phase = e.x.u8("trg_phase")
    before_tooth = e.x.u16("trg_tooth")
    before_sync = e.x.u8("trg_state")
    e.wait_edge(3 * period, 18)
    return e, before_phase, before_tooth, before_sync


def scheduler_half_range_case() -> tuple[PT.Call, int, int, int]:
    """Queue an event 17 degrees ahead at 80 rpm.

    Independent oracle: one degree is 15625/6 = 2604.17 T1 ticks at 80 rpm,
    therefore 17 degrees is 44270 ticks.  A raw 16-bit signed-delta due test
    mistakes any deadline over 32767 ticks away for an overdue event.
    """
    c = PT.Call()
    # The scheduler reads the engine from hc_cfg now; a bare rig describes
    # none, so it would correctly plan nothing and this case would prove
    # nothing about the half-range bug it exists for.
    PT.describe_engine(c)
    c.call("hc_drysched_init")
    write16(c, "eng_adv_x10", 10)       # fire 0 -> spark 359.0 deg
    write16(c, "eng_dwell_x100", 0)
    write16(c, "eng_ti_us", 0)
    write16(c, "eng_ti_base_us", 0)     # V97: the scheduler's fuel input
    start = 3420                         # 342.0 deg, first tooth after the gap
    stamp = 1000
    dt = 15625                           # exact normal period at 80 rpm

    # THE PRECEDING TOOTH IS NOW REQUIRED, and injecting it is more faithful
    # rather than less. The staging window used to be the literal
    # `((angle % 3600) == 3420) ? 180 : 60` - a 60-2 wheel's gap position,
    # compiled in - so a rig could hand the scheduler ONE tooth at 342.0 deg
    # and receive the 18-degree window. The window is now the step the decoder
    # actually took, which is decoder-independent and correct for any wheel,
    # and a single isolated tooth has no step to measure.
    #
    # So the gap is presented the way an engine presents it: the tooth before
    # it at 324.0 deg, then this one 18 degrees later. dt stays the NORMAL
    # period across both, which is what the decoder itself publishes -
    # trg_tooth_dt is documented as the last CLEAN tooth period precisely
    # because the gap interval spans three tooth positions.
    c.call("hc_drysched_tooth", 3240, (stamp - 3 * dt) & 0xFFFF, dt)
    c.call("hc_drysched_tooth", start, stamp, dt)
    c.set_t1(stamp)                     # the caller's `now` IS T1 (see below)
    c.call("hc_drysched_service", stamp, 3)
    return c, c.u16("dry_sched_queued"), c.u16("dry_sched_executed"), 44270


_GEN = (PT.ROOT / "firmware/generated/hc_config_generated.h").read_text(
    errors="replace")


def _d(name: str, text: str) -> int:
    m = re.search(r"#define\s+%s\s+(0x[0-9A-Fa-f]+|\d+)" % re.escape(name), text)
    if not m:
        raise SystemExit("missing #define: " + name)
    return int(m.group(1), 0)


_TGT = (PT.ROOT / "firmware/targets/me711/hctarget.h").read_text(errors="replace")
_CFGH = (PT.ROOT / "firmware/config/hcconfig.h").read_text(
    errors="replace")

# Where hc_cal_u8() actually reads a universal-block byte from.
CAL_RAM = (_d("TGT_EXTRAM_BASE", _TGT) + _d("TGT_RAM_CFG", _TGT)
           + _d("HC_CFG_HDR_LEN", _CFGH))


def uoff(name: str) -> int:
    """A UNIVERSAL-block offset, out of the generated header.

    PT.off() reads hcconfig.h, which does not carry the CFG_U_* fields - they
    are laid out by the config generator. Never retyped: the whole point of
    HC_CFG_LAYOUT_ID is that these move."""
    m = re.search(r"#define\s+%s\s+(\d+)u" % re.escape(name), _GEN)
    if not m:
        raise SystemExit("offset missing from hc_config_generated.h: " + name)
    return int(m.group(1))


def timer_ownership_case(source: int, cam: int = 1) -> PT.Call:
    """Run the linked trigger initializer with controlled shared-timer SFRs.

    `cam` is new at V55 and it is not a convenience: the cam captures are armed
    SEPARATELY from the crank now, and both halves of that are checked below.
    Before V55 asking for the crank armed CC8 and CC9 too, and a floating
    capture input with no sensor on it is the measured cause of 20000 rpm with
    syncState stuck at 1 and an ECU that stopped answering TunerStudio.
    """
    c = PT.Call()
    base = PT.sym("hc_cfg") & 0xFFFF
    c.m.w8(base + PT.off("CFG_REV_MAX"), 7500 >> 8)
    c.m.w8(base + PT.off("CFG_REV_MAX") + 1, 7500 & 0xFF)
    c.m.w8(base + PT.off("CFG_TRIG_TIMEOUT_MS"), 200)
    c.m.w8(base + PT.off("CFG_TRIG_SOURCE"), source)
    c.m.w8(base + PT.off("CFG_CAM_ENABLE"), cam)
    # THE ROUTING HAS TO BE SUPPLIED NOW, and it did not before V62.
    #
    # Until V62 trigger_hw() armed CC15 as the crank and CC8/CC9 as the cams
    # unconditionally, so this case never had to say WHICH cavity it meant. V62
    # arms the channel the configured cavity resolves to, so a page with no
    # crank pin arms NOTHING - which is correct, and is exactly what this case
    # started reporting as a firmware failure.
    #
    # This function writes the calibration page directly rather than booting
    # hc_cfg_mgr_init(), so the board default never runs and the universal
    # block is raw memory. It has to name the three cavities itself.
    #
    # AND THE UNIVERSAL BLOCK IS NOT IN `hc_cfg`. hc_cal_u8() serves offsets
    # below HC_CFG_CORE out of the near array and everything above it out of
    # the battery-backed page in EXTERNAL SRAM, at TGT_EXTRAM_BASE +
    # TGT_RAM_CFG + HC_CFG_HDR_LEN. Writing the near array for a CFG_U_* field
    # writes somebody else's bytes and the decoder never sees it.
    for slot, cav in (("CFG_U_PIN_CRANK", 82),
                      ("CFG_U_PIN_CAM1", 86),
                      ("CFG_U_PIN_CAM2", 87)):
        c.m.w8(CAL_RAM + uoff(slot), cav)
    # Preserve the unrelated T0/CCM fields while proving that trigger-off
    # withdraws every T1/capture claim and trigger-on installs only its fields.
    c.m.w16(0xFF50, 0x4242)  # T01CON: T1 running, T0 baseline
    c.m.w16(0xFF56, 0xBEEF)  # CCM2: CC8/9 are the low byte
    c.m.w16(0xFF58, 0xABCD)  # CCM3: CC15 is the high nibble
    c.m.w16(0xFF88, 0xFFFF)  # CC8IC
    c.m.w16(0xFF8A, 0xFFFF)  # CC9IC
    c.m.w16(0xFF96, 0xFFFF)  # CC15IC
    c.call("trg_init")
    return c


def staged_future_case(rpm: int, delta_x10: int, start: int = 1000) -> tuple[bool, str]:
    """Exercise one long-horizon plan through the real staging and due cores."""
    c = PT.Call()
    PT.describe_engine(c)
    c.call("hc_drysched_init")
    c.call("hc_drysched_test_anchor", start)
    accepted = c.call("hc_drysched_schedule_after", delta_x10, 2, 1)
    stamp = 0xF200
    dt = round(1_250_000 / rpm)
    c.call("hc_drysched_test_advance", start, stamp, dt)
    c.call("hc_drysched_time_service", stamp)
    if accepted != 1 or c.u16("dry_sched_executed") != 0:
        return False, f"accept={accepted} early={c.u16('dry_sched_executed')}"

    angle = start
    remain = delta_x10
    while remain >= 60:
        angle = (angle + 60) % 7200
        stamp = (stamp + dt) & 0xFFFF
        remain -= 60
        c.call("hc_drysched_test_advance", angle, stamp, dt)
        if remain and c.u16("dry_sched_executed") != 0:
            return False, f"executed with {remain / 10:.1f} deg remaining"

    # The final software stage is the preceding tooth. A multiple-of-six
    # target is due exactly at its capture; otherwise it is a bounded offset.
    if remain:
        due = dt * remain // 60
        if due:
            c.call("hc_drysched_time_service", (stamp + due - 1) & 0xFFFF)
            if c.u16("dry_sched_executed") != 0:
                return False, f"executed one tick early; due={due}"
        c.call("hc_drysched_time_service", (stamp + due) & 0xFFFF)
    else:
        c.call("hc_drysched_time_service", stamp)
    ok = c.u16("dry_sched_executed") == 1 and c.u16("dry_sched_missed") == 0
    return ok, (f"dt={dt} staged_remainder={remain / 10:.1f} "
                f"executed={c.u16('dry_sched_executed')}")



# The universal block lives in the battery-backed external SRAM, above
# HC_CFG_CORE, so hc_cal_u8() reads it through TGT_EXTRAM_BASE + TGT_RAM_CFG +
# HC_CFG_HDR_LEN rather than out of hc_cfg[]. Writing it here is what lets a
# host rig choose an execution STRATEGY - and the strategy is what decides how
# much engine position the runtime must have before it may schedule anything.
UBLOCK = 0x380000 + 12
CFG_U_INJ_STRATEGY, CFG_U_IGN_STRATEGY = 2536, 2537


def strategy_sync_case(inj: int, ign: int, sync: int, rpm: int = 3000):
    """Run twenty teeth at a given sync level under a given strategy pair."""
    c = PT.Call()
    PT.describe_engine(c, cylinders=8)
    c.m.w8(UBLOCK + CFG_U_INJ_STRATEGY, inj)
    c.m.w8(UBLOCK + CFG_U_IGN_STRATEGY, ign)
    c.call("hc_drysched_init")
    for name, v in (("eng_adv_x10", 200), ("eng_dwell_x100", 300),
                    ("eng_ti_base_us", 10000), ("eng_deadtime_us", 0)):
        c.m.w16(PT.sym(name) & 0xFFFF, v)
    stamp = 1000
    dt = round(1_250_000 / rpm)
    for k in range(20):
        c.call("hc_drysched_tooth", (k * 60) % 7200, stamp, dt)
        stamp = (stamp + dt) & 0xFFFF
        # THE CLOCK IS T1. hc_drysched_service(now) is handed T1 by its caller,
        # and since V92 it re-reads T1 after draining the capture ring (a
        # tooth captured after the caller's `now` fired 13 % of the AWT's
        # events up to a tooth early).
        # This rig used to pass time only as the argument with T1 standing at
        # 0, i.e. a clock that runs backwards once the ring is drained.
        c.set_t1(stamp)
        c.call("hc_drysched_service", stamp, sync)
    return c.u16("dry_sched_need_sync"), c.u16("dry_sched_executed")


def main() -> int:
    print("=== Bosch V27 adversarial linked-image checks ===")
    print(f"image  {PI.image().name}")
    print(f"sha256 {hashlib.sha256(PI.image().read_bytes()).hexdigest().upper()}\n")

    e, phase, tooth, sync = early_gap_case()
    check("single isolated 3x interval cannot retain sync while rephasing",
          not (sync >= 3 and e.x.u8("trg_state") >= 3
               and (e.x.u8("trg_phase") != phase or e.x.u16("trg_tooth") == 0)),
          (f"before state/phase/tooth={sync}/{phase}/{tooth}; after="
           f"{e.x.u8('trg_state')}/{e.x.u8('trg_phase')}/{e.x.u16('trg_tooth')}"))
    period = round(1_250_000 / 800)
    e.wait_edge(period)
    check("confirmed out-of-position 3x interval withdraws crank sync",
          e.x.u8("trg_state") < 3 and e.x.u16("trg_loss_reason") == 2,
          f"state={e.x.u8('trg_state')} reason={e.x.u16('trg_loss_reason')}")

    c, queued, executed, oracle = scheduler_half_range_case()
    check("80-rpm event 17 degrees ahead is not executed at queue time",
          queued > 0 and executed == 0,
          f"independent deadline delta={oracle} ticks queued={queued} executed={executed}")

    # ---------------------------------------------------------------------
    # SEQUENTIAL EXECUTION MUST NOT RUN ON CRANK POSITION ALONE.
    #
    # The scheduler used to require TRG_SYNC_CRANK and nothing more, whatever
    # the page said, so a sequentially-injected engine would have been
    # scheduled on 360-degree position - putting every second cycle's fuel into
    # the exhaust stroke. hc_validation.c refuses that CONFIGURATION, but
    # validation covers what a tuner types, not what happens when a cam signal
    # disappears while the engine is running.
    #
    # AND THE RULE IS NOT "COP NEEDS A CAM". Wasted COP fires one coil per
    # cylinder twice per cycle and runs on crank alone, which is a real way to
    # start an engine whose cam signal is not trusted yet. Getting that wrong
    # in the safe direction is still getting it wrong.
    HC_INJ_BATCH, HC_INJ_SEQ = 0, 2
    HC_IGN_PAIRED, HC_IGN_WCOP, HC_IGN_SCOP = 0, 1, 2
    TRG_SYNC_CRANK, TRG_SYNC_FULL = 3, 4

    for label, inj, ign, want in (
            ("batch + wasted paired", HC_INJ_BATCH, HC_IGN_PAIRED, TRG_SYNC_CRANK),
            ("batch + wasted COP", HC_INJ_BATCH, HC_IGN_WCOP, TRG_SYNC_CRANK),
            ("sequential + seq COP", HC_INJ_SEQ, HC_IGN_SCOP, TRG_SYNC_FULL),
            ("sequential + wasted COP", HC_INJ_SEQ, HC_IGN_WCOP, TRG_SYNC_FULL)):
        need, crank_exec = strategy_sync_case(inj, ign, TRG_SYNC_CRANK)
        _, full_exec = strategy_sync_case(inj, ign, TRG_SYNC_FULL)
        check(f"{label}: needs {'cam' if want == TRG_SYNC_FULL else 'crank only'}",
              need == want, f"dry_sched_need_sync={need}")
        if want == TRG_SYNC_FULL:
            # V97: A SEQUENTIAL STRATEGY RUNS ITS FALLBACK ON CRANK ONLY -
            # two half pulses per cylinder and a wasted spark, both right on
            # either revolution (the maintainer's design notes). It no longer
            # schedules nothing: that stalled an engine whose cam glitched.
            # What must NOT happen - fuel into the wrong stroke as a whole
            # sequential pulse - is proven per pin by
            # me711_sequential_proof.py (S1: two halves, S2..S3 mass per
            # intake through acquisition and loss).
            check(f"{label}: runs its FALLBACK on crank-only sync (V97)",
                  crank_exec > 0, f"executed={crank_exec}")
        else:
            check(f"{label}: runs on crank-only sync, no cam needed",
                  crank_exec > 0, f"executed={crank_exec}")
        check(f"{label}: runs with full cycle sync",
              full_exec > 0, f"executed={full_exec}")

    off = timer_ownership_case(0)
    check("triggerSource=off stops T1 and clears CC8/9/15 capture",
          off.m.r16(0xFF50) == 0x0042
          and off.m.r16(0xFF56) == 0xBE00
          and off.m.r16(0xFF58) == 0x0BCD
          and off.m.r16(0xFF88) == 0
          and off.m.r16(0xFF8A) == 0
          and off.m.r16(0xFF96) == 0
          and off.u8("hc_hal_trig_armed") == 0,
          (f"T01={off.m.r16(0xFF50):04X} CCM2={off.m.r16(0xFF56):04X} "
           f"CCM3={off.m.r16(0xFF58):04X} armed={off.u8('hc_hal_trig_armed')}"))

    on = timer_ownership_case(1, cam=1)
    check("triggerSource=real exclusively starts T1 and arms captures",
          on.m.r16(0xFF50) == 0x4242
          and on.m.r16(0xFF56) == 0xBEAA
          and on.m.r16(0xFF58) == 0xABCD
          and on.m.r16(0xFF88) == IC_CAM
          and on.m.r16(0xFF8A) == IC_CAM2
          and on.m.r16(0xFF96) == IC_CRANK
          and on.u8("hc_hal_trig_armed") == 1,
          (f"T01={on.m.r16(0xFF50):04X} CCM2={on.m.r16(0xFF56):04X} "
           f"CCM3={on.m.r16(0xFF58):04X} IC={on.m.r16(0xFF96):04X}/"
           f"{on.m.r16(0xFF88):04X}/{on.m.r16(0xFF8A):04X}"))

    # V55: THE CAM IS ARMED SEPARATELY, AND THAT IS A SAFETY PROPERTY.
    # With no cam sensor connected a floating CC8/CC9 generates captures; that
    # is the measured reason CFG_TRIG_SOURCE exists at all, and until V55 it
    # protected the crank input and not the two cam inputs beside it. So
    # camEnable=0 must leave CC8IC, CC9IC and CCM2's low byte alone while the
    # crank arms normally - and camEnable=1 must still arm all three, which is
    # the check above.
    nocam = timer_ownership_case(1, cam=0)
    check("camEnable=0 arms the crank and leaves BOTH cam captures cold",
          nocam.m.r16(0xFF50) == 0x4242
          and nocam.m.r16(0xFF56) == 0xBE00
          and nocam.m.r16(0xFF58) == 0xABCD
          and nocam.m.r16(0xFF88) == 0
          and nocam.m.r16(0xFF8A) == 0
          and nocam.m.r16(0xFF96) == IC_CRANK
          and nocam.u8("hc_hal_trig_armed") == 1,
          (f"T01={nocam.m.r16(0xFF50):04X} CCM2={nocam.m.r16(0xFF56):04X} "
           f"CC15IC={nocam.m.r16(0xFF96):04X} "
           f"CC8IC={nocam.m.r16(0xFF88):04X} CC9IC={nocam.m.r16(0xFF8A):04X}"))

    for rpm in (80, 100, 150, 800, 2000, 6000, 8000):
        ok, detail = staged_future_case(rpm, 170)
        check(f"{rpm}-rpm staged 17-degree future event never executes early",
              ok, detail)
    for angle_x10 in (10, 50, 170, 300, 900, 1800, 3590):
        ok, detail = staged_future_case(80, angle_x10)
        check(f"80-rpm future horizon {angle_x10 / 10:g} degrees", ok, detail)
    for start, delta in ((7190, 10), (7170, 50), (7000, 300), (65000 % 7200, 3590)):
        ok, detail = staged_future_case(80, delta, start)
        check(f"720-degree angle wrap start={start / 10:g} delta={delta / 10:g}",
              ok, detail)

    # All cam inputs are permuted across both revolutions.  Falling edges may
    # update diagnostics, but the linked state must never reach FULL (4).
    cam, _, period = PT.stable_case(800)
    for rev in range(2):
        for tooth_idx in range(58):
            if tooth_idx in (0, 10, 20, 30, 40, 50):
                for bank in (1, 2, 2, 1):
                    cam.x.call("trg_test_cam_edge", bank)
            cam.wait_edge(period)
        cam.wait_edge(3 * period, 18)
    check("arbitrary/bouncing dual-cam permutations cannot assert 720 sync",
          cam.x.u8("trg_state") != 4,
          f"state={cam.x.u8('trg_state')} cam_edges={cam.x.u16('trg_cam_edges')}")

    # Timer-count oracle is derived directly from 1.25 MHz and 60 nominal
    # positions/revolution, not from firmware constants/functions.
    for rpm, expected in ((80, 15625), (100, 12500), (150, 8333),
                          (800, 1562), (1000, 1250), (2000, 625),
                          (4000, 312), (6000, 208), (7000, 179), (8000, 156)):
        got = round(1_250_000 / rpm)
        check(f"independent nominal tooth count oracle at {rpm} rpm",
              got == expected, f"ticks={got}")

    print(f"\n{FAIL} adversarial failure(s)")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
