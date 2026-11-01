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

SECTION 2 MEASURES WHAT THE PLANNER HANDS THE EXECUTOR.

Since the 2026-10-07 executor the polled path this section used to drive
(`hc_drysched_time_service()`, `dry_sched_last_angle`) is an empty
compatibility stub, and the section found no event at all. Every edge now
leaves the planner through ONE call, `hc_deadline_publish(generation, stamp,
ahead, type, ...)`: the CC25 executor fires it at `stamp + ahead` and does no
angle arithmetic of its own. So the gate records that call's arguments at its
entry - what the callee receives (R9 stamp, R10:R11 ahead, R12 type) - while
clean teeth are fed through `hc_drysched_tooth()` / `hc_drysched_service()`,
and turns each deadline back into the angle it implies with the WHEEL'S tooth:

    implied = angle(stamp's tooth) + ahead * tooth_x10 / dt

That must be the angle the configuration puts the event at - every spark at
TDC - advance, every injector start at the start-of-injection angle, every
dwell start at the spark minus the dwell's angle - on every wheel, for every
event the planner publishes (not one hand-picked event). The clock is the
board's own (`me711_heartbeat_gap_proof.TPMS`), so the same gate measures the
2.7T's 0.75 MHz timer.

CONTROLS:

  * **60 teeth must be exact on EVERY image.** The literal and the derived
    tooth width are the same number there, so if that row fails the rig is
    wrong rather than the firmware.
  * **The rig can tell.** The same deadlines decoded with the 60-tooth
    literal must miss by more than a degree on 36, 24 and 12 - otherwise the
    published events sit too close to their teeth for the measurement to see
    the defect class it exists for.

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
import me711_plan_cost_proof as C     # noqa: E402  (planning_fixture)
import me711_heartbeat_gap_proof as HB  # noqa: E402

TPS = HB.TPMS * 100                   # this board's T1 ticks per second

sym = PT.sym

CYCLE_X10 = 7200
RPM = 3000
CYLINDERS = 4
TDC = [0, 5400, 1800, 3600]           # 1-3-4-2, x10 degrees after TDC 1
ADV, DWELL_MS, SOI = 200, 3.0, 3600   # planning_fixture's operating point
# how far the implied angle may sit from the configured one: the firmware's
# truncating division and the dwell's own angle rounding, a few hundredths
# of a degree; one tenth leaves room and is far below a tooth
TOL_X10 = 1.0
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
        period = round(TPS * 60 / (RPM * teeth))
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

def published(teeth, revs=3):
    """Every (type, implied angle x10 with the wheel's tooth, implied angle
    with the 60-tooth literal, delta x10) the planner publishes over `revs`
    revolutions of clean teeth on a `teeth`-tooth wheel."""
    dt = round(TPS * 60 / (RPM * teeth))
    c = C.planning_fixture(CYLINDERS, teeth)
    PT.describe_engine(c, cylinders=CYLINDERS, teeth=teeth, tdc=TDC,
                       soi_x10=SOI, cam_refs=0)
    c.call("hc_drysched_init")
    entry = sym("hc_deadline_publish")
    seg, ip = (entry >> 16) & 0xFF, entry & 0xFFFF
    log = []
    orig = S.CPU.step

    def step(self):
        if (self.ip & 0xFFFF) == ip and (self.csp & 0xFF) == seg:
            log.append((self.gr(9) & 0xFFFF,
                        (self.gr(10) & 0xFFFF) | ((self.gr(11) & 0xFFFF) << 16),
                        self.gr(12) & 0xFF))
        return orig(self)

    S.CPU.step = step
    angle_at = {}
    try:
        stamp, step_x = 1000, 3600 // teeth
        for k in range(revs * teeth):
            stamp = (stamp + dt) & 0xFFFF
            angle = (k * step_x) % CYCLE_X10
            angle_at[stamp] = angle
            c.set_t1(stamp)
            c.call("hc_drysched_tooth", angle, stamp, dt)
            c.call("hc_drysched_service", stamp, 3)
    finally:
        S.CPU.step = orig
    tx = tooth_x10(teeth)
    out = []
    for st, ahead, typ in log:
        if st not in angle_at:          # a catch-up publishes from T1 now
            continue
        a0 = angle_at[st]
        out.append((typ, (a0 + ahead * tx / dt) % 3600,
                    (a0 + ahead * 60 / dt) % 3600, ahead * tx / dt))
    return out, dt


def wanted(typ):
    """Where the configuration puts an event of `typ`, mod 360 degrees
    (crank sync: wasted spark and batch fire every revolution)."""
    spark = sorted({(t - ADV) % 3600 for t in TDC})
    if typ == 2:
        return spark
    if typ == 1:                          # dwell start = spark - dwell angle
        da = DWELL_MS * RPM * 3600 / 60000.0
        return [(x - da) % 3600 for x in spark]
    if typ == 3:
        return [SOI % 3600]
    return None


def miss(typ, angle):
    w = wanted(typ)
    return None if w is None else min(min(abs(angle - x), 3600 - abs(angle - x))
                                      for x in w)


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

    # ---------------- SECTION 2: where each published event lands ---------
    print("\n  --- every event published, decoded with the wheel's tooth ---")
    print("  %-8s %6s %7s %9s %10s %12s"
          % ("wheel", "dt", "events", "max delta", "worst miss", "60-literal"))
    rows = []
    for teeth, _gap in WHEELS:
        ev, dt = published(teeth)
        known = [(t, a, a60, d) for t, a, a60, d in ev if wanted(t) is not None]
        worst = max((miss(t, a) for t, a, _a60, _d in known), default=None)
        lit = max((miss(t, a60) for t, _a, a60, _d in known), default=None)
        far = max((d for *_x, d in known), default=0)
        rows.append((teeth, len(known), worst, lit, far))
        print("  %-8d %6d %7d %9.0f %10s %12s"
              % (teeth, dt, len(known), far,
                 "-" if worst is None else "%.2f" % (worst / 10.0),
                 "-" if lit is None else "%.2f" % (lit / 10.0)))
    print("  (angles in degrees; '60-literal' = the same deadlines read with "
          "a 60-tooth width)\n")
    for teeth, n, worst, _lit, far in rows:
        check("%2d teeth: every spark/dwell/injection at its angle" % teeth,
              n >= 6 and worst is not None and worst <= TOL_X10,
              "%d events, worst %.2f deg from the configured angle, up to "
              "%.0f deg ahead of the tooth" % (n, (worst or 0) / 10.0, far / 10.0))

    # ===================== THE CONTROLS ON THE MEASUREMENT =================
    sixty = [r for r in rows if r[0] == 60]
    check("the 60-tooth row is exact - the rig measures",
          bool(sixty) and sixty[0][2] is not None and sixty[0][2] <= TOL_X10
          and sixty[0][3] <= TOL_X10,
          "a wheel whose tooth IS 6.0 degrees must agree either way")
    other = [r for r in rows if r[0] != 60]
    check("the rig can tell: the 60-tooth literal misses on 36/24/12",
          bool(other) and all(r[3] is not None and r[3] > 10 for r in other),
          ", ".join("%d: %.1f deg" % (r[0], (r[3] or 0) / 10.0) for r in other))

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("TOOTH DEADLINE FAILS - an event is not published at the time "
              "its own wheel's tooth width puts it at.")
        return 1
    print("TOOTH DEADLINE PASSES - every wheel's events are published at the "
          "tick its own tooth width puts them at, and the decoder was asked "
          "what a tooth period means rather than told.")
    print("NOT PHYSICALLY VERIFIED: no coil or injector has been connected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
