#!/usr/bin/env python3
r"""
me711_sequential_proof.py - true sequential injection and sequential COP, with
their fallback, on the LINKED image (c167sim), measured at the output pins.

    py tests\firmware\trigger\me711_sequential_proof.py            the image me711_image names
    py tests\firmware\trigger\me711_sequential_proof.py --control  V96 frozen: must FAIL

THE ENGINE is the AWT's: 4 cylinders, 1-3-4-2 (TDC 0/540/180/360 engine), a
60-2 crank with tooth #1 78 deg BTDC, and the Bosch quick-start cam on 86
decided by its LEVEL at 126.0 deg engine (me711_trigger_scheduler_proof's rig, whose
cam model is rusEFI's quick-start shape anchored on the car's edges). The rig
knows the PHYSICAL truth: cylinder 1's compression TDC is at physical cycle
angle 78, cylinder 3's at 258, 4's at 438, 2's at 618 - so every pin event is
graded against the engine, not against the firmware's own coordinates.

WHAT IS CHECKED (docs/ARCHITECTURE.md):
  S1 crank-only page, sequential strategies: the FALLBACK - each injector two
     half pulses per cycle, each coil a spark at its compression TDC and one
     360 later; mass per intake = the cycle's.
  S2 cycle mode from four starting phases: the fallback until the cycle is
     confirmed, then each cylinder switches at its own twin; EVERY intake
     window (twin + own event) carries the cycle's mass through the switch;
     afterwards one whole pulse per cylinder per cycle and no exhaust-stroke
     spark; every spark within 2 deg of (TDC - advance); no overdwell.
  S3 cam stuck after sync: the cycle is withdrawn, crank kept, each cylinder
     returns to the fallback at its twin - mass conserved; cam back: re-enters.
  S4 end-of-injection timing: the pulse ENDS at (TDC - angle) +/- 3 deg.
  S5 dead time is added per pulse (fallback 2 x, sequential 1 x).
  S6 a fuel cut opens no injector.
  S7 pairing by firing order: wasted-paired COILS serve cylinders 360 deg
     apart (1/4 on cylinder 1's output, 3/2 on 3's); semi-sequential
     INJECTION does not pair outputs - every injector fires at its own TDC
     and 360 later (2026-10-10: the pair model left injectors 2 and 4 dead
     on the AWT car, and this gate asserted it).
  S10 (2026-10-10) EVERY ROUTED INJECTOR, EVERY STRATEGY: batch,
     semi-sequential (with and without a cam), sequential fallback and
     sequential with cycle sync - each of the four injector channels opens
     in every whole cycle and carries the cycle's mass (+/-5 %), with the
     strategy's pulse count. Semi-sequential pulses start at the cylinder's
     own TDC - angle (or 360 later).
  S8 (V99, the first car session: "sequential ignition does not start the
     engine; wasted does") the ORDER, spelled out: after the cycle is known,
     6 whole cycles of sparks in time order are exactly cylinders 1-3-4-2,
     each on ITS coil cavity (1 -> 102, 3 -> 103, 4 -> 94, 2 -> 95), at its
     own compression TDC - advance, one per cycle, none duplicated, none
     skipped.
  S9 (V99) the SAME cam signal with camPhaseLevel INVERTED: the decoder
     acquires just as confidently (a level check cannot tell) and EVERY
     sequential spark lands on the overlap TDC, 360 deg from compression -
     an engine that cranks, syncs and never fires. That is the car's symptom
     with the code chain proven right: the assignment, not the scheduler.

--control: the frozen V96 image required full sync for a sequential page
and cancelled on its loss - it must fail S1..S3.
--control-semiseq: the 2026-10-10 car image 323FFF9F (frozen in the raw
evidence store, SEMISEQ_WB_FIX_20261010/control_323FFF9F) drove only the
pair leads' injectors - it must fail S7 and S10.
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

CONTROL_STEM = "HaniCore_ME711_v96_wideband"
if "--control-semiseq" in sys.argv:
    ev = Path(os.environ.get("HANICORE_RAW_EVIDENCE",
                             str(ROOT.parent / "evidence")))
    bins = ev / "SEMISEQ_WB_FIX_20261010" / "control_323FFF9F"
    if not (bins / "HaniCore_ME711_v102_dev.bin").exists():
        raise SystemExit("control image missing: %s" % bins)
    env = dict(os.environ, HANICORE_ME711_STEM="HaniCore_ME711_v102_dev",
               HANICORE_ME711_BINS=str(bins), HC_SEQ_ONLY="s7,s10,s11")
    r = subprocess.run([sys.executable, __file__], env=env)
    ok = r.returncode != 0
    print("\nCONTROL (323FFF9F, semi-seq pair model): %s" %
          ("FAILS as it must" if ok else "PASSED - the gate cannot tell"))
    raise SystemExit(0 if ok else 1)
if "--control" in sys.argv:
    env = dict(os.environ, HANICORE_ME711_STEM=CONTROL_STEM)
    r = subprocess.run([sys.executable, __file__], env=env)
    ok = r.returncode != 0
    print("\nCONTROL (%s): %s" % (CONTROL_STEM,
          "FAILS as it must" if ok else "PASSED - the gate cannot tell"))
    raise SystemExit(0 if ok else 1)

import me711_trigger_test as PT          # noqa: E402
import me711_trigger_scheduler_proof as V      # noqa: E402

TI_US = 12000          # the cylinder's open time per CYCLE
ADV_X10, DWELL_X100 = 100, 300
TDC_C = {0: 78.0, 2: 258.0, 3: 438.0, 1: 618.0}   # slot bit -> physical TDC
CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += 0 if ok else 1
    print("  [%s] %-60s %s" % ("PASS" if ok else "FAIL", name, detail))
    return ok


def adiff(a, b, m=720.0):
    d = (a - b) % m
    return min(d, m - d)


class SeqRig(V.Rig):
    def __init__(self, sync_mode=2, phase_x=0, inj=2, ign=2, eoi=False,
                 angle_x10=5400, dead=0, cut=0, rpm=None, ti=TI_US):
        super().__init__(PT, sync_mode=sync_mode, cam_level=True,
                         phase_x=phase_x)
        if rpm:
            self.p = round(1_250_000 / rpm)     # T1 ticks per tooth
        self.ti = ti
        h = V.gen_h()
        u = 0x380000 + 12
        x = self.x
        x.m.w8(u + V.uoff("CFG_U_INJ_STRATEGY", h), inj)
        x.m.w8(u + V.uoff("CFG_U_IGN_STRATEGY", h), ign)
        o = V.uoff("CFG_U_INJ_TIMING_MODE", h)
        if o is not None:
            x.m.w8(u + o, 1 if eoi else 0)
        base = PT.sym("hc_cfg") & 0xFFFF
        so = PT.off("CFG_INJ_START_DEG_X10")
        x.m.w8(base + so, angle_x10 >> 8)
        x.m.w8(base + so + 1, angle_x10 & 0xFF)
        x.call("trg_init")
        x.call("trg_test_geometry")
        self.dead, self.cut = dead, cut
        self.angle_x10 = angle_x10
        self.cum = float(phase_x)
        self.rows = []       # (clock, ign, inj, phys, state)

    def model(self):
        m = self.x.m
        for n, v in (("eng_adv_x10", ADV_X10), ("eng_dwell_x100", DWELL_X100),
                     ("eng_ti_base_us", self.ti),
                     ("eng_deadtime_us", self.dead),
                     ("eng_fuelcut", self.cut)):
            m.w16(PT.sym(n) & 0xFFFF, v)
        # V98: the injection angle the scheduler places is the engine-control
        # layer's (hcengctl711.c hc_ec_post: the single angle, or the
        # injection timing table) - modelled here like every eng_* output;
        # me711_engine_control_proof checks the mapping itself.
        if _has("dry_inj_phase_x10"):
            m.w16(PT.sym("dry_inj_phase_x10") & 0xFFFF, self.angle_x10)
        for n in ("hc_ignition_allowed", "hc_injection_allowed"):
            m.w16(PT.sym(n) & 0xFFFF, 1)
        m.w16(PT.sym("hc_cfg_validation") & 0xFFFF, 0)

    def service_to(self, ticks):
        n = max(2, ticks // 150)
        t0, c0, a0 = self.t, self.clock, self.cum
        span = 6.0 * ticks / self.p
        for q in range(1, n):
            self.x.set_t1((t0 + ticks * q // n) & 0xFFFF)
            self.clock = c0 + ticks * q // n
            self.model()
            self.x.call("trg_service")
            self.rows.append((self.clock, self.x.call("hc_hal_out_mask_ign"),
                              self.x.call("hc_hal_out_mask_inj"),
                              a0 + span * q / n,
                              self.x.m.r8(PT.sym("trg_state") & 0xFFFF)))
        self.t = (t0 + ticks) & 0xFFFF
        self.clock = c0 + ticks
        self.cum = a0 + span

    def runrevs(self, n):
        for _ in range(n):
            self.rev()

    def u(self, name):
        return self.x.m.r16(PT.sym(name) & 0xFFFF)

    # ---- the pins ---------------------------------------------------------
    def pulses(self):
        """bit -> [(start phys, end phys, width us)]"""
        out = {b: [] for b in range(4)}
        on = {}
        prev = 0
        for clock, _ig, ij, ph, _st in self.rows:
            for b in range(4):
                m = 1 << b
                if ij & m and not prev & m:
                    on[b] = (clock, ph)
                if prev & m and not ij & m and b in on:
                    c0, p0 = on.pop(b)
                    out[b].append((p0, ph, (clock - c0) / 1.25))
            prev = ij
        return out

    def sparks(self):
        out = {b: [] for b in range(4)}
        prev = 0
        for _c, ig, _ij, ph, st in self.rows:
            for b in range(4):
                m = 1 << b
                if prev & m and not ig & m:
                    out[b].append((ph, st))
            prev = ig
        return out

    def first_full(self):
        for _c, _ig, _ij, ph, st in self.rows:
            if st >= 4:
                return ph
        return None


def windows(pl, bit, angle_x10, eoi):
    """Intake windows: each OWN event with the twin 360 before it. Returns
    [(own phys, total us, n pulses)] for every own pulse that has a whole
    window behind it."""
    tdc = TDC_C[bit]
    own_start = (tdc - angle_x10 / 10.0) % 720.0
    res = []
    ps = pl[bit]
    for i, (s, e, w) in enumerate(ps):
        ref = (e if eoi else s)
        if adiff(ref % 720.0, own_start) > 20.0:
            continue                             # a twin
        lo = ref - 720.0 + 20.0
        if lo < ps[0][0] - 1.0:
            continue                             # no whole window yet
        tot, n = 0.0, 0
        for s2, e2, w2 in ps:
            r2 = e2 if eoi else s2
            if lo < r2 <= ref + 1.0:
                tot += w2
                n += 1
        res.append((ref, tot, n))
    return res


def grade_mass(r, label, angle_x10=5400, eoi=False, tol=0.05, need_whole=True):
    pl = r.pulses()
    worst, bad = 0.0, []
    counts = set()
    for b in range(4):
        for ref, tot, n in windows(pl, b, angle_x10, eoi):
            err = abs(tot - TI_US) / TI_US
            counts.add(n)
            if err > worst:
                worst = err
            if err > tol:
                bad.append("cyl-bit %d @%.0f: %.0f us in %d" % (b, ref, tot, n))
    nwin = sum(len(windows(pl, b, angle_x10, eoi)) for b in range(4))
    check("%s: every intake window carries the cycle's mass (+/-%d %%)"
          % (label, tol * 100), nwin >= 8 and not bad,
          "%d windows, worst %.1f %%, pulses/window %s %s"
          % (nwin, worst * 100, sorted(counts), "; ".join(bad[:3])))
    return pl


def s1():
    print("\n-- S1 crank-only page, sequential strategies: the fallback --")
    r = SeqRig(sync_mode=1)
    r.start(8)
    pl = grade_mass(r, "S1")
    tail = [p for b in range(4) for p in pl[b] if p[0] > r.cum - 720.0]
    widths = sorted({round(w / 100) * 100 for _s, _e, w in tail})
    check("S1: two half pulses per cylinder per cycle",
          len(tail) >= 7 and all(abs(w - TI_US / 2) < TI_US * 0.05
                                 for _s, _e, w in tail),
          "last cycle %d pulses, widths %s" % (len(tail), widths))
    sp = r.sparks()
    twin = sum(1 for b in range(4) for ph, _st in sp[b]
               if adiff((ph - (TDC_C[b] - ADV_X10 / 10) - 360) % 720, 0) < 3)
    own = sum(1 for b in range(4) for ph, _st in sp[b]
              if adiff((ph - (TDC_C[b] - ADV_X10 / 10)) % 720, 0) < 3)
    check("S1: wasted COP - a spark at compression AND 360 later",
          own >= 12 and twin >= 12, "own %d twin %d" % (own, twin))
    check("S1: never 'sequential' without the cycle",
          r.x.m.r8(PT.sym("dry_seq_active") & 0xFFFF) == 0
          if _has("dry_seq_active") else False)


def _has(name):
    try:
        PT.sym(name)
        return True
    except SystemExit:
        return False


def s2():
    print("\n-- S2 cycle mode: fallback -> sequential, both starting halves x "
          "two injection angles --")
    # The cycle is decided at the level-check tooth, a fixed crank position;
    # which cylinders are between their twin and their own event at that
    # moment depends on the injection angle - so the angle moves the
    # transition across the cylinders (the rig starts on a gap, either half).
    for phase, ang in ((0, 5400), (360, 5400), (0, 1500), (360, 1500)):
        r = SeqRig(sync_mode=2, phase_x=phase, angle_x10=ang)
        r.start(10)
        ff = r.first_full()
        pl = grade_mass(r, "S2 half %d angle %d" % (phase, ang // 10),
                        angle_x10=ang)
        tail = [p for b in range(4) for p in pl[b] if p[0] > r.cum - 720.0]
        check("S2 phase %d: then ONE whole pulse per cylinder per cycle" % phase,
              ff is not None and len(tail) == 4
              and all(abs(w - TI_US) < TI_US * 0.05 for _s, _e, w in tail),
              "full sync at %s, last cycle %s" % (
                  None if ff is None else round(ff),
                  [round(w) for _s, _e, w in tail]))
        sp = r.sparks()
        late = [(b, ph) for b in range(4) for ph, st in sp[b]
                if ff is not None and ph > ff + 720.0]
        errs = [adiff((ph - (TDC_C[b] - ADV_X10 / 10)) % 720, 0)
                for b, ph in late]
        check("S2 phase %d: sequential COP - one spark per cycle at "
              "TDC - adv (+/-2 deg), none on exhaust" % phase,
              len(late) >= 8 and max(errs) <= 2.0,
              "%d sparks, worst %.1f deg" % (len(late),
                                            max(errs) if errs else -1))
        check("S2 phase %d: every cylinder switched once, no overdwell"
              % phase,
              r.u("dry_seq_enters") == 4 and r.u("dry_sched_overdwell") == 0,
              "enters %d overdwell %d" % (r.u("dry_seq_enters"),
                                          r.u("dry_sched_overdwell")))


def s3():
    print("\n-- S3 cam stuck after sync, then back --")
    r = SeqRig(sync_mode=2, phase_x=0)
    r.start(8)
    s_ok = r.x.m.r8(PT.sym("trg_state") & 0xFFFF)
    r.stuck = True
    r.runrevs(6)
    s_lost = r.x.m.r8(PT.sym("trg_state") & 0xFFFF)
    leaves = r.u("dry_seq_leaves")
    r.stuck = None
    r.runrevs(8)
    s_back = r.x.m.r8(PT.sym("trg_state") & 0xFFFF)
    check("S3: cycle 4 -> withdrawn to crank 3 -> back to 4",
          (s_ok, s_lost, s_back) == (4, 3, 4), str((s_ok, s_lost, s_back)))
    check("S3: each cylinder left sequential once and re-entered",
          leaves == 4 and r.u("dry_seq_enters") == 8,
          "leaves %d enters %d" % (leaves, r.u("dry_seq_enters")))
    grade_mass(r, "S3 through loss and regain")


def s4():
    print("\n-- S4 end-of-injection timing --")
    r = SeqRig(sync_mode=2, eoi=True, angle_x10=4400)
    r.start(12)
    pl = r.pulses()
    tail = [(b, e) for b in range(4) for s, e, w in pl[b] if s > r.cum - 720.0]
    errs = [adiff(e % 720.0, (TDC_C[b] - 440.0) % 720.0) for b, e in tail]
    check("S4: in sequence, each pulse ENDS at TDC - 440.0 (+/-3 deg)",
          len(tail) == 4 and max(errs) <= 3.0,
          "worst %.1f deg" % (max(errs) if errs else -1))
    grade_mass(r, "S4 (end timing)", angle_x10=4400, eoi=True)


def s5():
    print("\n-- S5 dead time per pulse --")
    for mode, label, want in ((1, "fallback", TI_US / 2 + 800),
                              (2, "sequential", TI_US + 800)):
        r = SeqRig(sync_mode=mode, dead=800)
        r.start(12)
        pl = r.pulses()
        tail = [w for b in range(4) for s, e, w in pl[b] if s > r.cum - 720.0]
        check("S5 %s: each pulse = its share + 0.8 ms dead time" % label,
              tail and all(abs(w - want) < want * 0.05 for w in tail),
              "%s want %.0f" % ([round(w) for w in tail], want))


def s6():
    print("\n-- S6 a fuel cut --")
    m = re.search(r"#define\s+ENG_CUT_OVERRUN\s+(0x[0-9A-Fa-f]+)",
                  (ROOT / "firmware/engine/hcengine.h").read_text())
    r = SeqRig(sync_mode=2, cut=int(m.group(1), 16))
    r.start(6)
    pl = r.pulses()
    check("S6: overrun cut - no injector opens",
          sum(len(v) for v in pl.values()) == 0,
          "%d pulses" % sum(len(v) for v in pl.values()))


def s7():
    print("\n-- S7 pairing by firing order (coils only) --")
    r = SeqRig(sync_mode=1, inj=1, ign=0)       # semi-seq + wasted paired
    r.start(6)
    pl, sp = r.pulses(), r.sparks()
    used_inj = sorted(b for b in range(4) if pl[b])
    used_ign = sorted(b for b in range(4) if sp[b])
    # cyl1 (bit0) serves 1/4 at 78 and 438; cyl3 (bit2) serves 3/2 at 258/618
    ok_ign = all(adiff(((ph + ADV_X10 / 10) - TDC_C[0]) % 360, 0) < 3
                 for ph, _ in sp[0]) and \
        all(adiff(((ph + ADV_X10 / 10) - TDC_C[2]) % 360, 0) < 3
            for ph, _ in sp[2])
    check("S7: wasted-paired drives the coils of cyl 1 and 3 only",
          used_ign == [0, 2], "ign bits %s" % used_ign)
    check("S7: semi-seq drives EVERY injector (not the pair leads only)",
          used_inj == [0, 1, 2, 3], "inj bits %s" % used_inj)
    check("S7: pair 1/4 sparks at 78/438, pair 3/2 at 258/618 (-adv)",
          ok_ign and len(sp[0]) >= 3 and len(sp[2]) >= 3,
          "cyl1 out %d sparks, cyl3 out %d" % (len(sp[0]), len(sp[2])))


def cycle_mass(pl, cum, cycles=3):
    """bit -> [(open us, pulses)] in each of the last `cycles` whole 720-deg
    windows (ending well behind the newest edge, so no pulse is cut)."""
    end = cum - 90.0
    out = {}
    for b in range(4):
        out[b] = []
        for k in range(cycles, 0, -1):
            lo, hi = end - 720.0 * k, end - 720.0 * (k - 1)
            ws = [w for s, _e, w in pl[b] if lo <= s < hi]
            out[b].append((sum(ws), len(ws)))
    return out


def s10():
    print("\n-- S10 every routed injector opens every cycle with the "
          "cycle's mass, every strategy --")
    cases = (("batch", 1, 0, 1, 2),
             ("semi-sequential, crank only", 1, 1, 1, 2),
             ("semi-sequential, cam present", 2, 1, 1, 2),
             ("sequential fallback, crank only", 1, 2, 1, 2),
             ("sequential, cycle sync", 2, 2, 2, 1))
    for label, sync, inj, ign, npulse in cases:
        r = SeqRig(sync_mode=sync, inj=inj, ign=ign)
        r.start(12)
        pl = r.pulses()
        cm = cycle_mass(pl, r.cum)
        dead = [b for b in range(4) if any(n == 0 for _t, n in cm[b])]
        bad = ["inj%d %s" % (b + 1, [(round(t), n) for t, n in cm[b]])
               for b in range(4)
               if any(abs(t - TI_US) > TI_US * 0.05 or n != npulse
                      for t, n in cm[b])]
        check("S10 %s: all 4 injectors open every cycle" % label,
              not dead, "dead channels %s" % [b + 1 for b in dead])
        check("S10 %s: each = %d us/cycle in %d pulse(s) (+/-5 %%)"
              % (label, TI_US, npulse), not bad, "; ".join(bad[:4]))
        if inj == 1:
            ang = r.angle_x10 / 10.0
            errs = [adiff((s - (TDC_C[b] - ang)) % 360.0, 0)
                    for b in range(4) for s, _e, _w in pl[b]]
            check("S10 %s: each pulse starts at its own TDC - %.0f "
                  "(or 360 later), +/-3 deg" % (label, ang),
                  bool(errs) and max(errs) <= 3.0,
                  "%d pulses, worst %.1f deg" % (len(errs),
                                                 max(errs) if errs else -1))


CAVITY = {0: 102, 1: 95, 2: 103, 3: 94}      # slot bit -> AWT coil cavity
CYL_OF_BIT = {0: 1, 1: 2, 2: 3, 3: 4}


def s8():
    print("\n-- S8 sequential COP: the firing order, cycle after cycle --")
    for phase in (0, 360):
        r = SeqRig(sync_mode=2, phase_x=phase, inj=0, ign=2)
        r.start(24)
        ff = r.first_full()
        sp = r.sparks()
        ev = sorted((ph, b) for b in range(4) for ph, st in sp[b]
                    if ff is not None and ph > ff + 720.0)
        cyls = [CYL_OF_BIT[b] for _ph, b in ev]
        want = [1, 3, 4, 2]
        k = cyls.index(1) if 1 in cyls else 0
        seq = cyls[k:k + 24]
        cyc = len(seq) // 4
        ok_order = cyc >= 6 and seq[:cyc * 4] == want * cyc
        errs = [adiff((ph - (TDC_C[b] - ADV_X10 / 10)) % 720, 0)
                for ph, b in ev]
        check("S8 start half %d: 6+ cycles exactly 1-3-4-2, one spark per "
              "cylinder per cycle" % phase, ok_order,
              "order %s" % "-".join(map(str, seq[:12])))
        check("S8 start half %d: each on its coil (102/103/94/95) at its own "
              "compression TDC - adv (+/-2 deg)" % phase,
              bool(errs) and max(errs) <= 2.0
              and all(CAVITY[b] in (102, 95, 103, 94) for _p, b in ev),
              "%d sparks, worst %.1f deg; cyl->cav %s" % (
                  len(ev), max(errs) if errs else -1,
                  {CYL_OF_BIT[b]: CAVITY[b] for b in range(4)}))


def s9():
    print("\n-- S9 the same cam signal, camPhaseLevel inverted --")
    h = V.gen_h()
    r = SeqRig(sync_mode=2, phase_x=0, inj=0, ign=2)
    r.x.m.w8(0x380000 + 12 + V.uoff("CFG_U_CAM_PHASE_LEVEL", h), 1)
    r.x.call("trg_init")
    r.x.call("trg_test_geometry")
    r.start(12)
    ff = r.first_full()
    sp = r.sparks()
    ev = [(ph, b) for b in range(4) for ph, st in sp[b]
          if ff is not None and ph > ff + 720.0]
    off = [adiff((ph - (TDC_C[b] - ADV_X10 / 10)) % 720, 0) for ph, b in ev]
    check("S9 inverted level: still acquires the cycle (a level check "
          "cannot tell)", ff is not None, "full sync at %s" % ff)
    check("S9 inverted level: EVERY sequential spark at the overlap TDC "
          "(360 deg off) - the no-start", bool(off)
          and min(off) >= 358.0, "%d sparks, nearest to compression %.1f "
          "deg" % (len(off), min(off) if off else -1))


def s11():
    print("\n-- S11 a long pulse at high rpm: limited by the OUTPUT's own "
          "interval (360 deg), not half of it --")
    # 4000 rpm: 360 deg = 15 ms. 24 ms per cycle = two 12 ms pulses per
    # output: legal (80 % duty). The 323FFF9F..7FA7FF76 code divided the
    # per-output interval by the repeat count again and clipped every
    # non-sequential pulse at 180 deg = 7.5 ms (50 % duty).
    ti, want = 24000, 12000
    for label, inj in (("batch", 0), ("semi-sequential", 1),
                       ("sequential fallback (crank only)", 2)):
        r = SeqRig(sync_mode=1, inj=inj, ign=1, rpm=4000, ti=ti)
        r.start(16)
        pl = r.pulses()
        # a 12 ms pulse spans ~290 deg here: grade a whole cycle that ENDS
        # 400 deg before the last edge, so every pulse in it has closed
        tail = [round(w) for b in range(4) for s, _e, w in pl[b]
                if r.cum - 1120.0 < s <= r.cum - 400.0]
        check("S11 %s, 4000 rpm: each pulse the full %d us (+/-5 %%), not "
              "clipped at 180 deg" % (label, want),
              len(tail) >= 8 and all(abs(w - want) < want * 0.05
                                     for w in tail),
              "%d pulses %s" % (len(tail), sorted(set(tail))[:6]))


def main() -> int:
    import me711_image as PI
    print("=== sequential fuel + ignition with fallback - %s ===" % PI.STEM)
    only = [s for s in os.environ.get("HC_SEQ_ONLY", "").split(",") if s]
    for f in (s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11):
        if only and f.__name__ not in only:
            continue
        try:
            f()
        except SystemExit as e:
            check(f.__name__ + " could not run", False, str(e))
    print("\n%d checks, %d failed" % (CHECKS, FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
