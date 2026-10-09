#!/usr/bin/env python3
"""Execute V27's linked decoder/scheduler against realistic Bosch 60-2."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import c167sim as S  # noqa: E402
import me711_image as PI
import me711_dpp as _dpp  # noqa: E402

MAP = PI.MAP.read_text(errors="replace")
CFG = (ROOT / "firmware/config/hcconfig.h").read_text()
FAIL = 0


def sym(name):
    m = re.search(r"^\s*([0-9A-F]{6})H\s+%s\b" % re.escape(name), MAP, re.M)
    if not m:
        raise SystemExit(f"symbol missing: {name}")
    return int(m.group(1), 16)


def off(name):
    return int(re.search(r"#define\s+%s\s+(\d+)" % name, CFG).group(1))


def check(name, ok, detail=""):
    global FAIL
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<49} {detail}")
    FAIL += not ok


def user_stack_size():
    """?C_USRSTKBOT's reservation, from the startup SOURCE the linker read."""
    src = (ROOT / "firmware/targets/me711/system/start_me711.a66").read_text(errors="replace")
    m = re.search(r"\?C_USRSTKBOT:\s+DSB\s+([0-9A-Fa-f]+)H", src)
    if not m:
        raise SystemExit("?C_USRSTKBOT DSB not found in start_me711.a66")
    return int(m.group(1), 16)


def _near_segments():
    """Every near-data segment in the linked map, as (lo, hi, name)."""
    out = []
    for line in PI.MAP.read_text(errors="replace").splitlines():
        m = re.match(r"\s*([0-9A-F]{6})H\s+([0-9A-F]{6})H\s+[0-9A-F]{6}H\s+"
                     r"DATA\s+.*?(\?ND0\?\S+|\?C_USERSTACK)", line)
        if m:
            out.append((int(m.group(1), 16) & 0xFFFF,
                        int(m.group(2), 16) & 0xFFFF, m.group(3)))
    return out


def _assert_stack_clear(top):
    """The rig's stack must not overlap anything but ?C_USERSTACK.

    A harness that writes over the module it is measuring produces failures
    that look like defects in the firmware, and this one did - twice.
    """
    for lo, hi, name in _near_segments():
        if name == "?C_USERSTACK":
            continue
        if lo < top <= hi + 1:
            raise SystemExit(
                "rig stack top 0x%04X is inside %s (0x%04X-0x%04X). "
                "The harness would write its call frames over the code under "
                "test. Fix the derivation, not the segment." % (top, name, lo, hi))


class Call:
    def __init__(self):
        self.m = S.Mem(PI.image().read_bytes())
        self.m._cbank = bytearray(0x10000)
        self.c = S.CPU(self.m, 0, 0)
        # DPP1 WAS A LITERAL, AND IT WAS THE V52 CONST PAGE.
        # tools/lib/me711_dpp.py reads it from the map, as the startup does.
        _dpp.apply(self.m)
        self.m.sfr[0xFE10] = 0xFC00
        # R0 is Keil's software-stack pointer, and it grows DOWN from the top of
        # ?C_USERSTACK. THE SIZE IS READ FROM THE STARTUP SOURCE, not assumed.
        #
        # THIS HAS NOW BITTEN TWICE, the same way both times: the rig's stack
        # top landed inside ?ND0?HCSCHED_DRY, so the harness wrote its own call
        # frames over the module under test and then reported the corruption as
        # a scheduler failure.
        #
        #   first time   a literal 0xF9F0, fixed by deriving the base from the
        #                linked map and adding 0x200
        #   this time    the 0x200 was itself a literal. The ME7.1.1 user stack
        #                was cut from 512 to 256 bytes after it was MEASURED at
        #                26, so ?C_USERSTACK is 0xF700-0xF7FF and the rig was
        #                starting R0 at 0xF900 - a full 256 bytes inside
        #                HCSCHED_DRY's statics. Nothing showed until plan_tooth
        #                started calling hc_plan_*, which deepened the call
        #                chain enough to reach cap_angle[] and zero the capture
        #                ring mid-plan. The symptom was an event executing with
        #                a zero delta, which looks exactly like a scheduler bug.
        #
        # So: no literal. The size comes from the same DSB the linker used, and
        # the result is CHECKED against the map's near-data segments below, so a
        # third recurrence fails loudly instead of silently.
        # the IMAGE's reservation (map), not today's startup source: a snapshot
        # of another commit may have another stack (me711_image.user_stack_top)
        self.stack_top = PI.user_stack_top()
        _assert_stack_clear(self.stack_top)
        self.m.w16(0xFC00, self.stack_top)
        self.max_steps = 0

    def call(self, fn, *args):
        saved_geometry_psw = None
        if getattr(self,'deadline_clock',False):
            # Explicit-clock geometry fixtures must not also advance T1 per
            # instruction after trigger_hw starts it: that double-counts time
            # and can turn a small backward reset into a full 16-bit lap.
            self.m.w16(0xFF50,self.m.r16(0xFF50)&~0x4000)
            self.m.w16(0xFF20,self.m.r16(0xFF20)&~0x0040)
            # Interrupts execute only in advance_deadlines(), where the
            # explicit timer can progress. A pending 16-tick rearm guard
            # must not spin forever against a frozen clock during an API.
            saved_geometry_psw = self.m.r16(0xFF10)
            self.m.w16(0xFF10,saved_geometry_psw & ~0x0800)
        a = sym(fn)
        self.m.w16(self.c.cp(), self.stack_top)
        self.m.sfr[0xFE14], self.m.sfr[0xFE16] = 0xF200, 0xFE00
        sp = 0xF700
        for w in (a >> 16, 0xFFFE):
            sp = (sp - 2) & 0xFFFF
            self.m.w16(sp, w)
        self.m.sfr[0xFE12] = sp
        for i, v in enumerate(args):
            self.c.sr(8 + i, v & 0xFFFF)
        self.c.csp, self.c.ip = a >> 16, a & 0xFFFF
        before = self.c.steps
        for _ in range(80000):
            if self.c.ip == 0xFFFE:
                if getattr(self,'deadline_clock',False):
                    self.m.w16(0xFF50,self.m.r16(0xFF50)&~0x4000)
                    self.m.w16(0xFF20,self.m.r16(0xFF20)&~0x0040)
                    self.m.w16(0xFF10,saved_geometry_psw)
                used = self.c.steps - before
                if fn == "trg_test_crank_edge":
                    self.max_steps = max(self.max_steps, used)
                return self.c.gr(4) & 0xFFFF
            self.c.step()
        raise SystemExit(f"{fn} did not return")

    def u16(self, name):
        return self.m.r16(sym(name) & 0xFFFF)

    def u8(self, name):
        return self.m.r8(sym(name) & 0xFFFF)

    def set_t1(self, t):
        if getattr(self, 'deadline_clock', False):
            self.advance_deadlines((t-self.m.r16(0xFE52))&0xffff)
            return
        self.m.w16(0xFE52, t & 0xFFFF)

    def enable_deadlines(self):
        """Geometry fixtures use an explicit clock, actual CC25 vector/RETI.

        These tests grade planning/phase, not instruction WCET. The dedicated
        deadline proof runs free-running timers and measures command latency.
        Frozen polling candidates retain their original fixture semantics.
        """
        if 'hc_cc25_isr' not in MAP: return
        self.call('hc_hal_init')
        self.deadline_clock=True
        self.m.w16(0xFF10,0x0800)

    def advance_deadlines(self, ticks):
        remaining=ticks
        for _ in range(128):
            cmp=self.m.r16(0xFE72)
            distance=(cmp-self.m.r16(0xF050))&0xffff
            enabled=bool(self.m.r16(0xF172)&0x40)
            pending=bool(self.m.r16(0xF172)&0x80)
            if not enabled or (not pending and (not remaining or distance>remaining)):
                self.m.w16(0xF050,(self.m.r16(0xF050)+remaining)&0xffff)
                self.m.w16(0xFE52,(self.m.r16(0xFE52)+remaining)&0xffff)
                return
            advance=0 if pending else distance
            if not advance and not pending: advance=65536
            if advance>remaining: return
            remaining-=advance
            self.m.w16(0xF050,(self.m.r16(0xF050)+advance)&0xffff)
            self.m.w16(0xFE52,(self.m.r16(0xFE52)+advance)&0xffff)
            self.m.w16(0xF172,self.m.r16(0xF172)|0x80)
            self.m.w8(0xE800,0x0D);self.m.w8(0xE801,0xFF)
            self.c.csp=0;self.c.ip=0xE800
            self.m.w16(self.c.cp(),self.stack_top);self.m.w16(0xFE12,0xF700)
            before=self.c.irq_count.get(0x39,0)
            for _ in range(12000):
                self.c.step()
                if self.c.irq_count.get(0x39,0)>before and self.c.csp==0 and self.c.ip==0xE800: break
            else: raise AssertionError('CC25 fixture interrupt did not return')
            # Rearm's 16-tick guard can request imminent work in software.
            # Explicit-clock fixtures advance that guard rather than spinning
            # on a frozen counter. Count those ticks in the same elapsed span.
            if self.m.r16(0xF172)&0x80 and remaining:
                guard=min(16,remaining);remaining-=guard
                self.m.w16(0xF050,(self.m.r16(0xF050)+guard)&0xffff)
                self.m.w16(0xFE52,(self.m.r16(0xFE52)+guard)&0xffff)
            elif not remaining: return
        raise AssertionError('too many compare checkpoints in one clock advance')


# The universal block lives in the EXTERNAL SRAM, twelve header bytes in, and
# c167sim models that region - the "harness does not model external SRAM"
# remark below predates the model and is only true of hc_cfg_init()'s probe.
UNI_BASE = 0x380000 + 12


def _uni(call, off):
    return int(re.search(r"#define\s+%s\s+(\d+)u" % off,
                         (ROOT / "firmware/generated/hc_config_generated.h").read_text()).group(1))


def describe_cam(call, refs=4, ref_x10=1220, window_x10=90, sync_mode=1):
    """Write the cam geometry the decoder reads, and make it re-read it.

    THIS IS WHAT V54 HAD NO WAY TO SAY. The four references at 122/302/482/662
    degrees and their 9.0 degree window were a const array inside
    hctrig_me711.c, so a rig could not describe a different cam and could not
    notice that it was testing the Porsche V8's. Defaults here reproduce that
    array exactly, so every check written against it stays comparable.
    """
    def w8(o, v):
        call.m.w8(UNI_BASE + o, v & 0xFF)

    def w16(o, v):
        w8(o, (v >> 8) & 0xFF)
        w8(o + 1, v & 0xFF)

    w8(_uni(call, "CFG_U_CAM_REFS"), refs)
    w16(_uni(call, "CFG_U_CAM_REF_X10"), ref_x10)
    w16(_uni(call, "CFG_U_CAM_WINDOW_X10"), window_x10)
    w8(_uni(call, "CFG_U_SYNC_MODE"), sync_mode)
    w16(_uni(call, "CFG_U_TRIG_ANGLE_X10"), 0)
    call.call("trg_test_geometry")


def describe_engine(call, cylinders=8, strokes=4, teeth=60, gap=2,
                    soi_x10=3600, tdc=None, cam_refs=4, cam_ref_x10=1220,
                    cam_window_x10=90, cam_sync_mode=1):
    """Write an engine into hc_cfg on a bare Call rig.

    SHARED, because two suites need the same engine and one of them did not
    know it needed one at all. hcsched_dry.c used to have eight cylinders 90
    degrees apart compiled into its planning loop, so a rig that wrote nothing
    to hc_cfg still received a V8 schedule; now the scheduler reads the page
    and correctly plans nothing for an engine nobody described. Every rig that
    exercises the scheduler therefore has to say what it is testing - which it
    should always have done, because a test that inherits its engine from a
    constant inside the code under test cannot notice that constant changing.

    These rigs poke hc_cfg directly rather than calling hc_cfg_init(), which
    probes the external SRAM this harness does not model.

    The default is a V8 on a 60-2 wheel: deliberately the engine the hardcoded
    loop assumed, so instruction counts and event counts stay comparable with
    every earlier run of these suites.
    """
    base = sym("hc_cfg") & 0xFFFF

    def w16(o, v):
        call.m.w8(base + o, (v >> 8) & 0xFF)
        call.m.w8(base + o + 1, v & 0xFF)

    w16(off("CFG_REV_MAX"), 7500)
    call.m.w8(base + off("CFG_TRIG_TIMEOUT_MS"), 200)
    call.m.w8(base + off("CFG_TRIG_SOURCE"), 0)

    call.m.w8(base + off("CFG_CYLINDERS"), cylinders)
    call.m.w8(base + off("CFG_STROKES"), strokes)
    w16(off("CFG_SY_TEETH"), teeth)
    call.m.w8(base + off("CFG_SY_GAP"), gap)
    w16(off("CFG_INJ_START_DEG_X10"), soi_x10)
    # DESCRIBING A CAM MEANS ENABLING ITS INPUT. camEnable is a CORE byte and
    # describe_engine() never wrote it, so every rig here ran with the cam
    # switched off while writing cam geometry beside it - and from V56 the
    # decoder reads camEnable to decide whether this engine has a cam at all.
    call.m.w8(base + off("CFG_CAM_ENABLE"), 1 if cam_refs else 0)
    describe_cam(call, refs=cam_refs, ref_x10=cam_ref_x10,
                 window_x10=cam_window_x10, sync_mode=cam_sync_mode)
    cycle = 7200 if strokes == 4 else 3600
    if tdc is None:
        tdc = [i * cycle // cylinders for i in range(cylinders)]
    for i in range(8):
        w16(off("CFG_TDC_CYL") + 2 * i, tdc[i] if i < len(tdc) else 0)
    return call


class Engine:
    """The decoder and the scheduler, driven by injected crank edges.

    THE ENGINE IS NOW DESCRIBED HERE, and it used not to need to be.

    hcsched_dry.c read no configuration at all: eight cylinders 90 degrees
    apart on a 720 degree cycle were compiled into its planning loop, so a rig
    that wrote nothing to hc_cfg still got a V8 schedule. Now the scheduler
    reads CFG_CYLINDERS, CFG_STROKES and the TDC table, and this rig never runs
    hc_cfg_init() - it pokes hc_cfg directly, because hc_cfg_init() probes the
    external SRAM. So the page reads as zeros, the scheduler correctly refuses
    to plan events for an engine nobody has described, and every "scheduler
    executes" check went to zero.

    That is the gate working. The fix is for the test to SAY which engine it is
    testing, which it should always have done: a test that inherits its engine
    from a constant in the code under test cannot detect that constant changing.

    A V8 on a 60-2 wheel, sequential COP, sequential injection - deliberately
    the same engine the hardcoded loop assumed, so the instruction counts and
    event counts below stay comparable with every earlier run of this suite.
    """

    CYLINDERS = 8
    STROKES = 4

    def __init__(self, start=1000, cam_sync_mode=1):
        self.x = Call()
        describe_engine(self.x, cylinders=self.CYLINDERS, strokes=self.STROKES,
                        cam_sync_mode=cam_sync_mode)
        self.x.call("trg_init")
        self.t = start & 0xFFFF
        self.edge(self.t, service=False)

    def service(self, t=None):
        if t is not None:
            self.x.set_t1(t)
        self.x.call("trg_service")

    def edge(self, t, service=True):
        self.t = t & 0xFFFF
        self.x.set_t1(self.t)
        self.x.call("trg_test_crank_edge", self.t)
        if service:
            self.service()

    def wait_edge(self, ticks, slices=6):
        old = self.t
        for q in range(1, slices):
            self.service((old + ticks * q // slices) & 0xFFFF)
        self.edge((old + ticks) & 0xFFFF)

    def rev(self, period):
        for _ in range(57):
            self.wait_edge(period)
        self.wait_edge(3 * period, 18)


def stable_case(rpm, start=1000):
    e = Engine(start)
    p = round(1_250_000 / rpm)
    for _ in range(4):
        e.rev(p)
    got = e.x.u16("trg_rpm")
    return e, got, p


def main():
    print("=== Bosch ME7.1.1 V27 trigger/scheduler instruction-level suite ===\n")
    angle = Call()
    check("zero reference offset preserves physical angle",
        angle.call("trg_engine_angle_x10", 600, 0, 0) == 600)
    check("positive reference offset advances engine angle",
        angle.call("trg_engine_angle_x10", 600, 0, 150) == 750)
    check("negative reference offset retards engine angle",
        angle.call("trg_engine_angle_x10", 600, 0, -150) == 450)
    check("positive reference offset wraps physical revolution",
        angle.call("trg_engine_angle_x10", 3500, 0, 200) == 100)
    check("negative reference offset wraps physical revolution",
        angle.call("trg_engine_angle_x10", 100, 0, -200) == 3500)
    check("physical 360-degree boundary normalises before phase",
        angle.call("trg_engine_angle_x10", 3600, 0, 0) == 0)
    check("cycle-half selection preserves 720-degree phase",
        angle.call("trg_engine_angle_x10", 3500, 1, 200) == 3700)
    # 7100, NOT 7000, AND THE FIRMWARE WAS NEVER WRONG ABOUT IT.
    #
    # Two checks above, the SAME physical angle and the SAME offset with phase
    # 0 is asserted to give 3500: 10.0 degrees minus 20.0 wraps to 350.0. Phase
    # 1 adds a whole revolution, so it is 710.0 degrees. The 7000 that stood
    # here was a typo, and it survived because this gate has been SKIPPED since
    # V47 - hcsched_dry.c's planner was compiled out by TGT_LIVE_BURN_HYBRID_QUAL
    # and the suite skipped the whole file rather than the scheduler checks in
    # it. Eight gate-runs of "green" over V47..V54 contained no run of this
    # line at all.
    check("fixed 10-degree BTDC coordinate rotates only globally",
        angle.call("trg_engine_angle_x10", 100, 1, -200) == 7100)

    for rpm in (80, 150, 800, 2000, 6000):
        e, got, p = stable_case(rpm)
        check(f"{rpm} rpm 60-2 acquires crank sync", e.x.u8("trg_state") >= 3,
              f"rpm={got}, period={p}")
        check(f"{rpm} rpm accuracy", abs(got - rpm) <= max(1, rpm // 100),
              f"got {got}")
        check(f"{rpm} rpm scheduler executes", e.x.u16("dry_sched_executed") > 0,
              f"events={e.x.u16('dry_sched_executed')}")
        check(f"{rpm} rpm capture ring bounded", e.x.u16("dry_sched_capture_overflow") == 0)
        check(f"{rpm} rpm gap remains candidate until successor",
              e.x.u16("trg_gap_pending") == 1
              and e.x.u16("trg_engine_deg_x10") % 3600 == 3480,
              f"position={e.x.u16('trg_engine_deg_x10') / 10:.1f} deg")
        e.wait_edge(p)
        check(f"{rpm} rpm successor confirms tooth one",
              e.x.u16("trg_gap_pending") == 0
              and e.x.u16("trg_engine_deg_x10") % 3600 == 60,
              f"position={e.x.u16('trg_engine_deg_x10') / 10:.1f} deg")
        check(f"{rpm} rpm has no missed dry events", e.x.u16("dry_sched_missed") == 0,
              f"missed={e.x.u16('dry_sched_missed')}")

    wrap, got, _ = stable_case(800, 65000)
    check("T1 rollover preserves sync and RPM", wrap.x.u8("trg_state") >= 3
          and abs(got - 800) <= 2, f"rpm={got}")

    noise, _, p = stable_case(800)
    noise.wait_edge(p)
    tooth = noise.x.u16("trg_tooth")
    base = noise.t
    noise.x.call("trg_test_crank_edge", (base + 10) & 0xFFFF)
    check("single noise pulse rejected without position move",
          noise.x.u16("trg_noise_edges") == 1 and noise.x.u16("trg_tooth") == tooth)
    for q in (12, 14, 16, 18):
        noise.x.call("trg_test_crank_edge", (base + q) & 0xFFFF)
    check("repeated early noise remains bounded", noise.x.u16("trg_noise_edges") >= 5
          and noise.x.u8("trg_state") >= 3)

    bad, _, p = stable_case(800)
    bad.wait_edge(p)
    bad.wait_edge(p)
    bad.wait_edge(6 * p, 12)
    bad.wait_edge(p)                    # OEM-style following-neighbour confirm
    check("out-of-position long interval withdraws sync explicitly", bad.x.u8("trg_state") < 3
          and bad.x.u16("trg_loss_reason") == 2,
          f"reason={bad.x.u16('trg_loss_reason')}")
    for _ in range(3):
        bad.rev(p)
    check("loss is followed by deterministic reacquisition", bad.x.u8("trg_state") >= 3)

    # V92: ONE missing edge at a confirmed gap is a TOOTH CORRECTION (Bosch
    # B_fbm/CORTINC; the AWT lost crank sync four times while cranking on
    # 2026-09-27, each one missing edge).
    # Two in consecutive revolutions are still a loss. Before V92 the first
    # disagreement already dropped sync, so this case never needed the edge
    # that CONFIRMS the second gap; a gap is judged on its successor.
    one, _, p = stable_case(800)
    one.wait_edge(p)
    one.wait_edge(2 * p)
    for _ in range(54):
        one.wait_edge(p)
    one.wait_edge(3 * p, 18)
    one.wait_edge(p)
    if re.search(r"^\s*[0-9A-F]{6}H\s+trg_tooth_corr\b", MAP, re.M):
        check("one missing edge is a tooth correction, crank sync kept",
              one.x.u8("trg_state") >= 3 and one.x.u16("trg_synclost") == 0
              and one.x.u16("trg_tooth_corr") == 1,
              f"state={one.x.u8('trg_state')} lost={one.x.u16('trg_synclost')} "
              f"corr={one.x.u16('trg_tooth_corr')}")

    skipped, _, p = stable_case(800)
    for _ in range(2):
        skipped.wait_edge(p)
        skipped.wait_edge(2 * p)        # one physical tooth did not arrive
        for _ in range(54):
            skipped.wait_edge(p)
        skipped.wait_edge(3 * p, 18)
    skipped.wait_edge(p)                # confirms the second gap
    check("repeated missing edge causes named sync loss",
          skipped.x.u16("trg_loss_reason") in (2, 3)
          and skipped.x.u16("trg_synclost") > 0,
          f"reason={skipped.x.u16('trg_loss_reason')}")

    cam, _, p = stable_case(800)
    while not (1200 <= (cam.x.u16("trg_engine_deg_x10") % 1800) <= 1240):
        cam.wait_edge(p)
    cam.x.call("trg_test_cam_edge", 1)
    cam.x.call("trg_test_cam_edge", 2)
    check("both cam banks accept exact calibrated windows",
          cam.x.u16("trg_cam1_window") != 0xFFFF
          and cam.x.u16("trg_cam2_window") != 0xFFFF)
    check("falling edges alone never claim false 720 sync", cam.x.u8("trg_state") == 3)

    wrong, _, _ = stable_case(800)
    wrong.x.call("trg_test_cam_edge", 1)
    check("wrong cam window is rejected", bool(wrong.x.u16("trg_cam_error") & 1))

    # A DUAL-CAM ENGINE, SAID SO IN THE PAGE. From V56 a cam bank is only
    # reported missing when the configuration states the engine has it -
    # g_sync_bank, which HC_SYNC_DUAL_CAM (4) sets for both banks. With the
    # previous CRANK_ONLY fixture this check was asserting that a cam nobody
    # had described was absent, which is the defect that blocked every live
    # Burn on the bench once the crank actually turned.
    missing = Engine(cam_sync_mode=4)
    for _ in range(9):
        missing.rev(round(1_250_000 / 800))
    check("missing dual cams become explicit faults",
          (missing.x.u16("trg_cam_error") & 12) == 12,
          f"mask=0x{missing.x.u16('trg_cam_error'):04X}")

    stall, _, _ = stable_case(800)
    for _ in range(30):
        stall.service((stall.t + 10000) & 0xFFFF)
        stall.t = (stall.t + 10000) & 0xFFFF
    check("stall timeout cancels position with named reason",
          stall.x.u8("trg_state") == 0 and stall.x.u16("trg_loss_reason") == 1)

    accel = Engine()
    periods = [round(1_250_000 / r) for r in (150, 250, 400, 800, 1200, 2000, 3500, 6000)]
    last = periods[0]
    for p in periods:
        # Change speed across the revolution.  The old test jumped as much as
        # 71% in one tooth exactly after the marker, which is not crankshaft
        # acceleration and specifically defeats the OEM two-sided check.
        for tooth_i in range(57):
            q = last + (p - last) * (tooth_i + 1) // 58
            accel.wait_edge(q)
        accel.wait_edge(3 * p, 18)
        last = p
    check("acceleration sweep retains/reacquires sync", accel.x.u8("trg_state") >= 3)
    for p in reversed(periods):
        for tooth_i in range(57):
            q = last + (p - last) * (tooth_i + 1) // 58
            accel.wait_edge(q)
        accel.wait_edge(3 * p, 18)
        last = p
    check("deceleration sweep retains/reacquires sync", accel.x.u8("trg_state") >= 3)
    check("compiled crank core has a measured finite bound", accel.x.max_steps < 2500,
          f"worst {accel.x.max_steps} emulated instructions")

    print(f"\nall checks pass" if not FAIL else f"\n{FAIL} failure(s)")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
