#!/usr/bin/env python3
r"""
me711_trigger_scheduler_proof.py - the V92 decoder/scheduler changes, on the LINKED
image in c167sim.

    py tests\firmware\trigger\me711_trigger_scheduler_proof.py              the image me711_image names
    py tests\firmware\trigger\me711_trigger_scheduler_proof.py --control    also run frozen V91 (must fail)

WHAT THE 2026-09-27 AWT SESSION SHOWED:

  F2  every crank sync loss while cranking was ONE missing crank edge; V91
      dropped sync and withdrew fuel and spark for a revolution each time.
  F3  13 % of executed events fired immediately (EARLY) because `now` was
      sampled before the capture ring was drained; schedulerLate counted
      every polled event.
  F8  the AWT cam is a Bosch quick-start wheel; the edges V91 captured are
      the equidistant set and cannot resolve the cycle.

WHAT IS CHECKED (AWT geometry: 4 cyl, 60-2, TDC#1 at physical 78 deg, offset
282.0, wasted COP + batch):

  A  crank-only: sync, no loss, no cam decision (state never 4)
  B  one missing edge -> toothCorrections 1, syncLossCount 0, still synced
  C  one extra edge   -> toothCorrections 1, syncLossCount 0
  D  missing edges in two consecutive revolutions -> a real crank loss
  E  LEVEL cam, crank-only mode: level alternates, match reported, no half
     moved, state stays 3, sector widths W/N measured
  F  LEVEL cam, cycle mode: full sync acquired from the CORRECT half and
     from the WRONG half (one correction), crank never lost
  G  720-degree continuity: after acquisition TDC#1 compression is engine 0
     at physical 78 of the revolution the wheel says (rusEFI mapping)
  H  wasted COP across a phase move: every coil sparks every revolution
  I  stuck cam after acquisition -> cycle lost, crank KEPT, recovery
  J  stale-now: an event planned from a tooth newer than `now` is not
     executed early

NOT PHYSICALLY VERIFIED. The quick-start sector geometry is rusEFI's
configureQuickStartSenderWheel() anchored on the observed AWT edges at
physical 114/294; the real sector widths are what LEVEL mode publishes on the
next vehicle session (camLowWidthX10 / camHighWidthX10).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

CONTROL_STEM = "HaniCore_ME711_v91_first_start_clt"
P2 = 0xFFC0
CAM_BIT = 0x0100            # P2.8 = NWDG1 = cavity 86
OFFSET_X10 = 2820           # TDC#1 at physical 78 deg
TDC_PHYS = 78
PHASE_ANGLE_X10 = 1260      # rev X physical 204 -> engine 126.0 deg
RPM = 900
CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += 0 if ok else 1
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))
    return ok


def gen_h():
    return (ROOT / "firmware/generated/hc_config_generated.h").read_text()


def uoff(name, h=None):
    m = re.search(r"#define\s+%s\s+(\d+)u" % name, h or gen_h())
    return int(m.group(1)) if m else None


def cam_low(c):
    """Quick-start CPU level, physical cycle angle c (rev X = 0..359): the
    equidistant (captured) edges at 114/294 each begin a LOW sector; the
    sectors are W,N,N,W = 140,40,40,140 (rusEFI shape, image, AWT edges)."""
    c %= 720
    return (114 <= c < 254) or (294 <= c < 334) or (474 <= c < 514) \
        or (654 <= c < 720) or (0 <= c < 74)


class Rig:
    def __init__(self, PT, sync_mode=1, cam_level=True, phase_x=0):
        self.PT = PT
        self.x = x = PT.Call()
        PT.describe_engine(x, cylinders=4, teeth=60, gap=2, soi_x10=3600,
                           tdc=[0, 5400, 1800, 3600], cam_refs=0)
        base = PT.sym("hc_cfg") & 0xFFFF
        x.m.w8(base + PT.off("CFG_CAM_ENABLE"), 1 if cam_level else 0)
        h = gen_h()
        u = 0x380000 + 12

        def w8(o, v):
            x.m.w8(u + o, v & 0xFF)

        def w16(o, v):
            w8(o, v >> 8)
            w8(o + 1, v)
        w8(uoff("CFG_U_INJ_STRATEGY", h), 0)
        w8(uoff("CFG_U_IGN_STRATEGY", h), 1)
        w8(uoff("CFG_U_SYNC_MODE", h), sync_mode)
        w16(uoff("CFG_U_TRIG_ANGLE_X10", h), OFFSET_X10)
        w8(uoff("CFG_U_PIN_CRANK", h), 82)
        w8(uoff("CFG_U_PIN_CAM1", h), 86)
        w8(uoff("CFG_U_PIN_CAM2", h), 255)
        pi, pg = uoff("CFG_U_PIN_INJ", h), uoff("CFG_U_PIN_IGN", h)
        for i, v in enumerate([96, 89, 97, 88] + [255] * 8):
            w8(pi + i, v)
        for i, v in enumerate([102, 95, 103, 94] + [255] * 8):
            w8(pg + i, v)
        self.has_level = uoff("CFG_U_CAM_PHASE_MODE", h) is not None
        if self.has_level:
            w8(uoff("CFG_U_CAM_PHASE_MODE", h), 1 if cam_level else 0)
            w8(uoff("CFG_U_CAM_PHASE_LEVEL", h), 0)
            w16(uoff("CFG_U_CAM_PHASE_ANGLE_X10", h), PHASE_ANGLE_X10)
            w8(uoff("CFG_U_CAM_PHASE_CONFIRM", h), 2)
        x.call("trg_init")
        x.call("trg_test_geometry")
        x.enable_deadlines()
        self.t = 1000
        self.c = phase_x          # physical cycle angle of the next tooth
        self.p = round(1_250_000 / RPM)
        self.cam = None
        self.log = []             # (clock, ign mask, engine deg, phys cycle)
        self.clock = 0
        self.stuck = None

    def u16(self, n):
        if n in ("trg_state", "trg_phase"):
            return self.x.m.r8(self.PT.sym(n) & 0xFFFF)
        return self.x.m.r16(self.PT.sym(n) & 0xFFFF)

    def model(self):
        """What the main loop's engine model would hold: 10 deg, 3 ms, 4 ms."""
        for n, v in (("eng_adv_x10", 100), ("eng_dwell_x100", 300),
                     ("eng_ti_base_us", 8000), ("eng_deadtime_us", 0)):
            self.x.m.w16(self.PT.sym(n) & 0xFFFF, v)
        for n in ('hc_ignition_allowed','hc_injection_allowed'):
            self.x.m.w16(self.PT.sym(n)&0xffff,1)
        self.x.m.w16(self.PT.sym('hc_cfg_validation')&0xffff,0)

    def to_gap(self):
        """Advance teeth until the next one is the last before the gap, then
        cross it - realigns rev() after a partial revolution."""
        while self.c % 360 != 342:
            self.tooth()
        self.service_to(3 * self.p)
        self.c = (self.c + 18) % 720
        self.edge()

    def set_cam(self, c):
        low = cam_low(c) if self.stuck is None else self.stuck
        v = self.x.m.sfr.get(P2, 0)
        self.x.m.sfr[P2] = (v & ~CAM_BIT) if low else (v | CAM_BIT)
        return low

    def service_to(self, ticks):
        n = max(2, ticks // 600)
        t0, c0 = self.t, self.clock
        for q in range(1, n):
            self.x.set_t1((t0 + ticks * q // n) & 0xFFFF)
            self.clock = c0 + ticks * q // n
            self.model()
            self.x.call("trg_service")
            self.log.append((self.clock, self.x.call("hc_hal_out_mask_ign"),
                             self.u16("trg_engine_deg_x10"), None))
        self.t = (t0 + ticks) & 0xFFFF
        self.clock = c0 + ticks

    def plan(self):
        """THE PLANNER IS AN INTERRUPT LEVEL since 2026-10-06 (CC26, requested
        by the crank ISR; hcsched_dry.c hc_plan_isr). This function-call rig
        runs it the way the CPU would - right after the edge that requested
        it. On an older image the request is never set and this does nothing
        (trg_service still plans there)."""
        m = self.x.m
        ic = m.r16(0xF174)
        if ic & 0x80:
            m.w16(0xF174, ic & ~0x80)
            self.x.call("hc_drysched_service", self.t & 0xFFFF,
                        self.u16("trg_state"))

    def edge(self):
        """The tooth at physical cycle angle self.c."""
        # the cam may have changed level since the last tooth: emit its edges
        low = self.set_cam(self.c)
        if self.cam is not None and low != self.cam:
            self.x.call("trg_test_cam_edge", 1)
        self.cam = low
        self.x.set_t1(self.t)
        self.x.call("trg_test_crank_edge", self.t)
        self.x.set_t1(self.t)
        self.model()
        self.x.call("trg_service")
        self.plan()

    def tooth(self, skip=False, extra=False):
        """Advance one tooth (6 deg); skip = that edge never arrives."""
        self.service_to(self.p)
        self.c = (self.c + 6) % 720
        if not skip:
            self.edge()
        if extra:
            self.service_to(self.p // 3)
            self.x.set_t1(self.t)
            self.x.call("trg_test_crank_edge", self.t)
            self.x.call("trg_service")
            self.plan()

    def rev(self, skip_at=None, extra_at=None):
        """One revolution starting just after the gap-end tooth. Teeth are at
        physical 6..342 (57 teeth), then the gap (three periods) to 360."""
        for k in range(1, 58):
            self.tooth(skip=(k == skip_at), extra=(k == extra_at))
        # the gap: physical 342 -> 360
        self.service_to(3 * self.p)
        self.c = (self.c + 18) % 720
        self.edge()

    def start(self, revs=3):
        # first edge at physical 0 of the chosen revolution
        self.edge()
        for _ in range(revs):
            self.rev()


def run_all(PT, label):
    print("\n=== %s ===" % label)
    r = Rig(PT, sync_mode=1, cam_level=False)
    r.start(4)
    check("A crank-only: crank sync", r.u16("trg_state") == 3,
          "state %d" % r.u16("trg_state"))
    check("A crank-only: no crank loss", r.u16("trg_synclost") == 0)

    # B: one missing edge mid-revolution
    r.rev(skip_at=20)
    r.rev()
    tc = r.u16("trg_tooth_corr") if "trg_tooth_corr" in PT.MAP else 0
    check("B one missing edge: no crank sync loss", r.u16("trg_synclost") == 0,
          "syncLossCount %d" % r.u16("trg_synclost"))
    check("B one missing edge: counted as a tooth correction", tc == 1,
          "toothCorrections %d" % tc)
    check("B one missing edge: still crank-synchronised",
          r.u16("trg_state") >= 3, "state %d" % r.u16("trg_state"))

    # C: one extra edge
    r2 = Rig(PT, sync_mode=1, cam_level=False)
    r2.start(3)
    r2.rev(extra_at=30)
    r2.rev()
    tc2 = r2.u16("trg_tooth_corr") if "trg_tooth_corr" in PT.MAP else 0
    check("C one extra edge: no crank sync loss", r2.u16("trg_synclost") == 0,
          "syncLossCount %d" % r2.u16("trg_synclost"))
    check("C one extra edge: counted as a tooth correction", tc2 == 1,
          "toothCorrections %d" % tc2)

    # D: missing edges in two consecutive revolutions is a real loss
    r3 = Rig(PT, sync_mode=1, cam_level=False)
    r3.start(3)
    r3.rev(skip_at=20)
    r3.rev(skip_at=20)
    r3.rev()          # the second disagreement is judged on the next rev's first tooth
    check("D two consecutive: a real crank sync loss",
          r3.u16("trg_synclost") >= 1, "syncLossCount %d" % r3.u16("trg_synclost"))
    r3.rev(); r3.rev(); r3.rev()
    check("D recovery: crank sync regained", r3.u16("trg_state") >= 3,
          "state %d" % r3.u16("trg_state"))

    # J: stale now - every tooth of two revolutions is captured 400 ticks
    # AFTER the `now` the scheduler service is handed (the ISR fired between
    # trg_service() reading T1 and the ring being drained, as on the car).
    r6 = Rig(PT, sync_mode=1, cam_level=False)
    r6.start(3)
    x = r6.x
    early = 0
    for _ in range(2):
        for k in range(58):
            gap = (k == 57)
            r6.service_to((3 if gap else 1) * r6.p - 400)
            now = r6.t
            stamp = (now + 400) & 0xFFFF
            r6.c = (r6.c + (18 if gap else 6)) % 720
            x.set_t1(stamp)
            x.call("trg_test_crank_edge", stamp)
            r6.model()
            x.call("hc_drysched_service", now, 3)
            r6.t = stamp
            r6.clock += 400
    late = r6.u16("dry_sched_max_latency")
    check("J stale now: no event fired early with a wrapped latency",
          late < 30000, "schedulerMaxLatency %d, executed %d"
          % (late, r6.u16("dry_sched_executed")))

    if "trg_ph_status" not in PT.MAP:
        check("E..I LEVEL cam method present", False, "no trg_ph_status symbol")
        return

    # E: LEVEL observe (crank-only)
    r4 = Rig(PT, sync_mode=1, cam_level=True)
    r4.start(6)
    st = r4.u16("trg_ph_status")
    check("E observe: level alternates every revolution", st & 0x4 != 0,
          "status 0x%04X noalt %d" % (st, r4.u16("trg_ph_noalt")))
    check("E observe: no non-alternating check", r4.u16("trg_ph_noalt") == 0)
    check("E observe: the half was NOT moved (crank-only)",
          r4.u16("trg_phase_corr") == 0)
    check("E observe: state stays crank sync (3)", r4.u16("trg_state") == 3)
    lo, hi = r4.u16("trg_cam_lo_w_x10"), r4.u16("trg_cam_hi_w_x10")
    check("E widths measured (LOW sector W or N)",
          lo in range(360, 450) or lo in range(1360, 1450),
          "lo %.1f hi %.1f deg" % (lo / 10, hi / 10))

    # F/G: LEVEL decides - both starting halves
    for start_c, name in ((0, "starting in rev X"), (360, "starting in rev Y")):
        r5 = Rig(PT, sync_mode=2, cam_level=True, phase_x=start_c)
        r5.start(6)
        check("F %s: full sync acquired" % name, r5.u16("trg_state") == 4,
              "state %d acq %d corr %d" % (r5.u16("trg_state"),
                                           r5.u16("trg_cycle_acq"),
                                           r5.u16("trg_phase_corr")))
        check("F %s: crank never lost" % name, r5.u16("trg_synclost") == 0)
        check("F %s: at most one half correction" % name,
              r5.u16("trg_phase_corr") <= 1)
        # G: find the tooth at physical 84 of rev X and read the engine angle
        while r5.c % 720 != 84:
            r5.tooth()
        eng = r5.u16("trg_engine_deg_x10")
        check("G %s: rev X phys 84 is engine 6.0 (TDC#1 comp at 78)" % name,
              eng == 60, "engine %.1f" % (eng / 10))

        # H: wasted COP - once sparking, no coil may go more than 1.5
        # revolutions without a spark (a lost spark across the phase move)
        rel = [[], [], [], []]
        prev = 0
        for clk, m, _, _ in r5.log:
            for b in range(4):
                if prev & (1 << b) and not m & (1 << b):
                    rel[b].append(clk)
            prev = m
        rev_t = 60 * r5.p
        worst = max((max(b - a for a, b in zip(r, r[1:])) if len(r) > 1
                     else 10 * rev_t) for r in rel)
        check("H %s: no coil missed a spark (max gap < 1.5 rev)" % name,
              all(len(r) >= 3 for r in rel) and worst < 1.5 * rev_t,
              "sparks %s, worst gap %.2f rev" % ([len(r) for r in rel],
                                                 worst / rev_t))

        if start_c == 0:
            # I: stuck cam
            r5.to_gap()
            r5.stuck = True
            r5.rev(); r5.rev()
            check("I stuck cam: cycle withdrawn (state 3)",
                  r5.u16("trg_state") == 3, "state %d" % r5.u16("trg_state"))
            check("I stuck cam: counted as cycle loss, NOT crank loss",
                  r5.u16("trg_cycle_lost") >= 1 and r5.u16("trg_synclost") == 0,
                  "cycleLost %d crankLost %d noalt %d"
                  % (r5.u16("trg_cycle_lost"), r5.u16("trg_synclost"),
                     r5.u16("trg_ph_noalt")))
            r5.stuck = None
            r5.rev(); r5.rev(); r5.rev()
            check("I recovery: full sync regained", r5.u16("trg_state") == 4,
                  "state %d" % r5.u16("trg_state"))



def main():
    import me711_trigger_test as PT
    run_all(PT, os.environ.get("HANICORE_ME711_STEM", "current image"))
    if "--control" in sys.argv:
        env = dict(os.environ, HANICORE_ME711_STEM=CONTROL_STEM)
        r = subprocess.run([sys.executable, __file__, "--child"], env=env,
                           capture_output=True, text=True)
        out = r.stdout
        nfail = out.count("[FAIL]")
        print(out)
        global CHECKS, FAILS
        CHECKS += 1
        if nfail == 0:
            FAILS += 1
            print("  [FAIL] control: V91 passed - the proof cannot fail")
        else:
            print("  [PASS] control: V91 fails %d check(s), as it must" % nfail)
    print("\n%d checks, %d failed" % (CHECKS, FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    if "--child" in sys.argv:
        import me711_trigger_test as PT
        run_all(PT, "CONTROL " + os.environ.get("HANICORE_ME711_STEM", ""))
        sys.exit(0)
    sys.exit(main())
