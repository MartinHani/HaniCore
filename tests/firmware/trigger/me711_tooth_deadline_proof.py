#!/usr/bin/env python3
r"""
me711_tooth_deadline_proof.py - the angle->time conversion in the tooth path
must use THE CONFIGURED WHEEL'S TOOTH WIDTH, not a 60-tooth constant.

    py tests\firmware\trigger\me711_tooth_deadline_proof.py

THE PROPERTY

    An event staged `delta` tenths of a degree ahead of the tooth that planned
    it must FIRE `dt * delta / tooth_x10` timer ticks after that tooth, where
    `dt` is the tooth period the decoder delivered and `tooth_x10` is the
    angular width of one tooth on the CONFIGURED wheel.

WHY IT IS A GATE OF ITS OWN. `queue_event()` and `stage_long_horizon()` both
converted angle to time with

    ev_deadline = stamp + (dt * delta) / 60uL;

and **60 is `3600 / 60 teeth`** - the angular width of one tooth on a sixty
tooth wheel, written as a literal inside a scheduler whose entire design is to
outlive the decoder. `hc_plan_tooth_x10()` computes that number from the page
(60 teeth -> 60, 36 -> 100, 24 -> 150, 12 -> 300) and `plan_tooth()` already
passes it to `hc_plan_dur_to_angle_x10()` for the dwell and pulse conversions -
and the deadline arithmetic four lines away used the literal.

**So every scheduled edge on a wheel that is not a 60 lands LATE**, by
`(tooth_x10/60 - 1)` of its own offset: 67 % on a 36-1, 150 % on a 24-1, 400 %
on a 12-1. Same class as the hardcoded 60-2 decoder and the
compiled-in V8 firing order before it: a field that is in the page, in the
`.ini` and in the validator, which one runtime path ignores.

SECTION 1 PROVES THE PREMISE INSTEAD OF ASSUMING IT, AND THAT MATTERED.

The obvious alternative divisor is `w_window`, the angle the crank moved since
the last tooth - and it is WRONG, which only a trace of the real decoder
showed. `hctrig_me711.c`'s `crank_edge()` **does not deliver a tooth on the
long gap interval at all**: it marks the interval a candidate and returns, and
the confirming edge then delivers an angle step of four tooth widths with `dt`
still ONE tooth.

    #56  angle 3420  stamp 24769  dt 417   d(angle)  60
    #57  angle 3660  stamp 26437  dt 417   d(angle) 240   <-- across the gap
    #58  angle 3720  stamp 26854  dt 417   d(angle)  60

Dividing by that 240 window would have fired every event on that tooth FOUR
TIMES TOO EARLY, on the only wheel this ECU has ever run. Section 1 drives the
real decoder on four wheels and requires every delivered `dt` to be one
nominal tooth, so the divisor this gate insists on is grounded in measured
decoder behaviour rather than in a plausible reading of a variable name.

SECTION 2 MEASURES BEHAVIOUR, NOT A STRUCT.

`ev_deadline[]` is `static` and deliberately not published; this gate never
reads it. It feeds clean teeth until exactly ONE event is staged, then advances
the timer ONE TICK AT A TIME through `hc_drysched_time_service()` and records
the tick on which `dry_sched_executed` moves. That is the edge a coil sees.
`delta` comes from `dry_sched_last_angle` - the angle of the event that just
executed - minus the angle of the tooth that staged it, both published.

**It is deliberately NOT `dry_sched_next_angle`, and that cost a wrong number
once.** `next_angle` is whatever `queue_event()` wrote LAST, and a tooth may
stage two events of which one is due immediately - so on a 12-tooth wheel it
named an event that had already fired inside the staging tooth's own service
call, giving delta 0 for an event whose real offset was 160.

CONTROLS, and the 60-tooth row is the important one:

  * **60 teeth must be exact on EVERY image, before and after the fix.** The
    literal and the derived value are the same number there, so if that row
    ever fails the rig is wrong rather than the firmware.
  * 36, 24 and 12 are measured wrong before the fix by exactly `tooth_x10/60`,
    which is the arithmetic and not a coincidence - so the measurement
    identifies the defect rather than merely detecting one.

NOT PHYSICALLY VERIFIED: no coil or injector has been connected to this ECU and
no pin has been observed moving. What is asserted is the tick on which the
compiled scheduler executes an event in a simulator.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import c167sim as S                   # noqa: E402
import me711_image as PI              # noqa: E402
import me711_trigger_test as PT       # noqa: E402

sym = PT.sym

CYCLE_X10 = 7200
RPM = 3000
CYLINDERS = 4
# (total teeth, missing teeth). The gap is what makes the premise interesting:
# it is the only place where the angle step and the tooth period disagree.
WHEELS = ((60, 2), (36, 1), (24, 1), (12, 1))

CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print("  [%s] %-42s %s" % ("PASS" if ok else "FAIL", name, detail))


def u16(c, name):
    return c.m.r16(sym(name) & 0xFFFF)


def tooth_x10(teeth):
    """The same arithmetic hc_plan_tooth_x10() does, restated so the gate does
    not take its expectation from the firmware it is testing."""
    return 3600 // teeth


# ======================================================================
# SECTION 1 - what the REAL decoder hands the scheduler
# ======================================================================

class Wheel(PT.Engine):
    """me711_trigger_test's Engine on an arbitrary wheel.

    Engine hardcodes a V8 on a 60-2 because that is the engine its own
    instruction counts are comparable against. This drives the same linked
    decoder through the same injected crank edges with the wheel named."""

    def __init__(self, teeth, gap, cylinders=CYLINDERS, start=1000):
        self.teeth, self.gap = teeth, gap
        self.x = PT.Call()
        PT.describe_engine(self.x, cylinders=cylinders, teeth=teeth, gap=gap)
        self.x.call("trg_init")
        self.t = start & 0xFFFF
        self.edge(self.t, service=False)

    def rev(self, period):
        for _ in range(self.teeth - self.gap - 1):
            self.wait_edge(period)
        self.wait_edge((self.gap + 1) * period, 18)


def delivered_teeth(teeth, gap, revs=4):
    """Every (angle, stamp, dt) the decoder actually hands hc_drysched_tooth().

    Recorded by watching the program counter reach the function's own entry
    and reading Keil's first three word-argument registers - so it is what the
    callee receives, not what a model of the caller would have sent."""
    entry = sym("hc_drysched_tooth")
    seg, ip = (entry >> 16) & 0xFF, entry & 0xFFFF
    log = []
    orig = S.CPU.step

    def step(self):
        if (self.ip & 0xFFFF) == ip and (self.csp & 0xFF) == seg:
            log.append((self.gr(8) & 0xFFFF, self.gr(9) & 0xFFFF,
                        self.gr(10) & 0xFFFF))
        return orig(self)

    S.CPU.step = step
    try:
        w = Wheel(teeth, gap)
        period = round(75_000_000 / (RPM * teeth))
        for _ in range(revs):
            w.rev(period)
    finally:
        S.CPU.step = orig
    return log, period


def premise(teeth, gap):
    """Does every delivered dt span exactly one tooth, gap included?

    Returns (worst dt error %, the largest angle step seen, n teeth)."""
    log, period = delivered_teeth(teeth, gap)
    if len(log) < teeth:
        return None, None, len(log), period
    # Skip the first two: the decoder has no previous interval to measure
    # against on the first edge, and position is provisional until the gap is
    # confirmed once.
    body = log[2:]
    worst = max(abs(d - period) * 100.0 / period for _a, _s, d in body)
    steps = [(body[i][0] - body[i - 1][0]) % CYCLE_X10
             for i in range(1, len(body))]
    return worst, max(steps), len(log), period


# ======================================================================
# SECTION 2 - when a staged event actually executes
# ======================================================================

def drain(c, stamp, dt):
    # EIGHT TOOTH PERIODS, NOT FOUR. On a 12-tooth wheel the defect under test
    # inflates a deadline to five tooth periods, so a four-period drain LEFT
    # THE EVENT QUEUED - and the next tooth then looked like a clean
    # single-event tooth carrying somebody else's event. That is how a rig
    # measures the wrong thing while reporting a plausible number.
    for t in range(1, 8 * dt + 8):
        c.call("hc_drysched_time_service", (stamp + t) & 0xFFFF)
        if u16(c, "dry_sched_queued") == 0:
            return


def stage_one(teeth):
    """Feed clean teeth until EXACTLY ONE event is staged, then return
    (rig, tooth_angle, stamp, dt) for the tooth that staged it.

    The teeth are fed directly rather than through the decoder, with the shape
    section 1 measured the decoder delivering: the angle steps by one tooth
    width and `dt` is one tooth period."""
    dt = round(75_000_000 / (RPM * teeth))
    c = PT.Call()
    PT.describe_engine(c, cylinders=CYLINDERS, teeth=teeth)
    c.call("hc_drysched_init")
    for name, v in (("eng_adv_x10", 200), ("eng_dwell_x100", 300),
                    ("eng_ti_base_us", 10000), ("eng_deadtime_us", 0)):
        c.m.w16(sym(name) & 0xFFFF, v)

    step = 3600 // teeth
    stamp = 1000
    c.call("hc_drysched_tooth", 0, stamp, dt)
    c.call("hc_drysched_service", stamp, 3)        # seeds the cursors
    for k in range(1, 4 * teeth):
        stamp = (stamp + dt) & 0xFFFF
        angle = (k * step) % CYCLE_X10
        # CATCH-UP IS COUNTED PER TOOTH, NOT SINCE BOOT. walk_kind() issues a
        # catch-up with delta forced to 0 when the offset has stepped over an
        # anchor, and the tooth after seed_cursors() always does - so the
        # counter is already 1 before any ordinary tooth runs. What
        # disqualifies a tooth is the counter MOVING on it; comparing the
        # total to zero rejected every tooth in the run.
        catch = u16(c, "dry_sched_catchup")
        before = u16(c, "dry_sched_queued")
        c.call("hc_drysched_tooth", angle, stamp, dt)
        c.call("hc_drysched_service", stamp, 3)
        q = u16(c, "dry_sched_queued")
        # THE QUEUE MUST HAVE BEEN EMPTY GOING IN. Otherwise "exactly one
        # queued" can be an event staged by an EARLIER tooth, and the delta
        # derived from this tooth's angle belongs to a different tooth.
        if before == 0 and q == 1 and u16(c, "dry_sched_catchup") == catch:
            return c, angle, stamp, dt
        if q != 0:
            drain(c, stamp, dt)
    return None, 0, 0, dt


def fire_tick(c, stamp, dt):
    """Advance the timer one tick at a time and return the offset from `stamp`
    at which the staged event actually executes."""
    before = u16(c, "dry_sched_executed")
    for t in range(0, 8 * dt + 8):
        c.call("hc_drysched_time_service", (stamp + t) & 0xFFFF)
        if u16(c, "dry_sched_executed") != before:
            return t
    return None


def main() -> int:
    print("=== HaniCore ME7.1.1 - a tooth is as wide as the WHEEL says ===\n")
    print("  image      %s" % PI.STEM)
    print("  scenario   %d cylinders, %d rpm\n" % (CYLINDERS, RPM))

    # ---------------- SECTION 1: the premise, from the decoder -------------
    print("  --- what hc_drysched_tooth() is actually given, four "
          "revolutions each ---")
    print("  %-10s %8s %8s %10s %12s"
          % ("wheel", "teeth", "period", "worst dt", "max d(angle)"))
    prem = []
    for teeth, gap in WHEELS:
        worst, step, n, period = premise(teeth, gap)
        prem.append((teeth, gap, worst, step, n, period))
        print("  %-10s %8d %8d %9s %12s"
              % ("%d-%d" % (teeth, gap), n, period,
                 "-" if worst is None else "%.1f%%" % worst,
                 "-" if step is None else step))
    print()
    for teeth, gap, worst, step, n, period in prem:
        # ONE PER CENT. The injected edges are exact and the decoder does not
        # filter dt, so the only scatter is the rig's own rounding.
        check("%d-%d: every delivered dt is ONE tooth" % (teeth, gap),
              worst is not None and worst <= 1.0,
              "worst %s across %d delivered teeth - this is what makes the "
              "tooth width the right divisor"
              % ("-" if worst is None else "%.1f%%" % worst, n))
    gaps = [p for p in prem if p[3] is not None
            and p[3] > tooth_x10(p[0]) + 1]
    check("...while the ANGLE step is not", bool(gaps),
          "largest step seen: %s - the window and the tooth period disagree "
          "across a gap, and it is the PERIOD that dt belongs to"
          % ", ".join("%d-%d:%d" % (p[0], p[1], p[3]) for p in gaps))

    # ---------------- SECTION 2: when the event executes -------------------
    print("\n  --- the tick a staged event executes on ---")
    print("  %-10s %8s %8s %10s %10s"
          % ("wheel", "tooth", "delta", "expected", "measured"))
    rows = []
    for teeth, _gap in WHEELS:
        c, angle, stamp, dt = stage_one(teeth)
        if c is None:
            check("%d teeth: an event was staged" % teeth, False,
                  "no single-event tooth found in four revolutions")
            continue
        tx = tooth_x10(teeth)
        got = fire_tick(c, stamp, dt)
        # AFTER, not before: last_angle names the event that just executed.
        delta = (u16(c, "dry_sched_last_angle") - angle) % CYCLE_X10
        want = (dt * delta) // tx
        rows.append((teeth, tx, delta, want, got))
        print("  %-10d %8d %8d %10s %10s"
              % (teeth, tx, delta, want, "-" if got is None else got))

    print()
    for teeth, tx, delta, want, got in rows:
        # ONE TICK OF SLACK, and only one: the firmware's division truncates
        # and so does the expectation, so they agree exactly unless the
        # conversion itself is different.
        ok = got is not None and abs(got - want) <= 1
        detail = "fires %s ticks after its tooth, wants %d" % (got, want)
        if got is not None and want and got != want:
            detail += "  (%.1f%% late)" % ((got - want) * 100.0 / want)
        check("%2d teeth (%3d x10 per tooth) fires on time" % (teeth, tx),
              ok, detail)

    # ===================== THE CONTROL ON THE CONTROL =====================
    #
    # A rig that always answered "on time" would pass every row above. This
    # says the measurement is a real one: the 60-tooth wheel is the case where
    # the literal 60 and the derived 60 are THE SAME NUMBER, so it must be
    # exact on every image this gate has ever run against - including the ones
    # that fail the rows beside it. If it ever fails, the rig is wrong.
    sixty = [r for r in rows if r[0] == 60]
    check("the 60-tooth row is exact - the rig measures",
          bool(sixty) and sixty[0][4] is not None
          and abs(sixty[0][4] - sixty[0][3]) <= 1,
          "a wheel whose tooth IS 6.0 degrees must agree on any image")

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("TOOTH DEADLINE FAILS - the scheduler is converting angle to "
              "time with a wheel constant it was not given. Every edge on a "
              "non-60-tooth wheel lands late by tooth_x10/60 of its offset.")
        return 1
    print("TOOTH DEADLINE PASSES - every wheel's events fire at the tick its "
          "own tooth width puts them at, and the decoder was asked what a "
          "tooth period means rather than told.")
    print("NOT PHYSICALLY VERIFIED: no coil or injector has been connected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
