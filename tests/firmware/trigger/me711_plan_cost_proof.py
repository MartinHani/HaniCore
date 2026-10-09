#!/usr/bin/env python3
r"""
me711_plan_cost_proof.py - what one tooth of scheduling actually costs, and
how that compares with the time a tooth actually takes.

    py tests\firmware\trigger\me711_plan_cost_proof.py

WHY THIS EXISTS.

Everything the angle scheduler does happens between two teeth. At 12000 rpm on
a 60-tooth wheel two teeth are 133 microseconds apart; at this part's measured
~10 MIPS that is about 833 instructions, TOTAL, shared with the S5500
supervision raster, the TunerStudio server and eng_service(). A scheduler that
does not fit inside that is a scheduler with a maximum engine speed, whatever
its feature list says.

Nobody had measured it, and when somebody did the answer was that IT DID NOT
FIT:

    the hardcoded-V8 planner, before any configurability   1679 instructions
    the first configuration-driven version                 2351
    after hoisting the modular reductions                  1788
    ------------------------------------------------------------------
    the pre-resolved cycle plan (current)                   851

A V8 was inside its own tooth period only below about 5500 rpm. That is a real
limit on a real engine, and it was ARCHITECTURAL: plan_tooth() re-planned the
WHOLE 720-degree cycle on EVERY tooth - every cylinder, every repeat, four
angles each, a slot-mapping call apiece - and discarded everything outside one
tooth window. O(cylinders) of work, 7500 times a second, to place at most a
couple of events.

WHAT CHANGED, and why it is not a special case for a Porsche V8.

An event angle splits into a part that is configuration and a part that is
state:

    event angle = ANCHOR - OFFSET

The ANCHOR is a cylinder's TDC plus one revolution per repeat, together with
the logical slot that cylinder's strategy maps it to. That is pure
configuration, so hcsched_dry.c now builds it ONCE, at the configuration
boundary, into two angle-sorted lists.

The OFFSET is shared by every event of one KIND across the whole engine -
advance, advance plus dwell angle, injection angle, injection angle minus pulse
angle. FOUR numbers per tooth, not four per cylinder.

The lists are sorted and the crank only advances, so the next event of each
kind is the one a cursor points at. The tooth path is four modular adds, four
modular subtracts and four compares, plus one cursor step per event that
actually fires. That is O(1) amortised.

WHAT THIS GATE NOW CHECKS, and all three are PASS/FAIL:

 1. THE BUDGET. Every cylinder count the configuration allows must plan one
    tooth inside one tooth period at the target speed, with margin. This used
    to be a printed paragraph rather than a check, deliberately, because a gate
    that is red for a known architectural item gets learned and ignored. The
    item is fixed, so it is a check.

 2. THE SHAPE. The cost must be essentially INDEPENDENT of cylinder count. A
    cost that grows per cylinder means the per-cylinder search came back.

 3. NO REGRESSION past the hardcoded V8 this replaced.

WHY IT CANNOT PASS VACUOUSLY. Every number is produced by EXECUTING
hc_drysched_service() out of the linked image across a whole revolution of
injected teeth and taking the worst pass - not by reading source. The verdict
is derived from that measurement and the tooth period, so the reported ceiling
rpm is a measured quantity: if the planner got slower the ceiling would drop
below the target and check 1 would fail. tests/unit/test_plan_cost_gate.py mutates
the measurement to prove exactly that.

WHAT THIS IS NOT: a worst-case proof. It is the worst pass over one revolution
of clean, evenly spaced teeth with a plausible advance, dwell and pulse width.
A gap tooth, a sync loss or a configuration change in the same pass are not
represented, and the tooth INTERRUPT's own cost is me711_isr_budget's subject,
not this one's.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_image as PI              # noqa: E402
import me711_trigger_test as PT       # noqa: E402

# The part's measured throughput, from the same figure me711_ts_gap_proof.py
# uses when it converts instructions to milliseconds (11260 instructions =
# 1.13 ms). Not a datasheet number: a ratio this repo already established.
MIPS = 10.0

# The speed the scheduler must fit at, and the margin demanded there. 7500 rpm
# is the configuration's own CFG_REV_MAX default for this engine; 25 % is the
# share of a tooth left for the capture interrupt, the S5500 raster, the
# TunerStudio server and eng_service, which all live in the same tooth.
# ================================ THE SPEED THIS ECU MUST ACTUALLY SUPPORT ==
#
# RAISED FROM 7500 TO 12000 ON 2026-09-17, and the old number was never a
# requirement - it was the speed the first V8 donor happened to rev to, and it
# quietly became the design target. HaniCore is a universal standalone ECU;
# 7500 rpm excludes most of what people put a standalone ECU on.
#
# THE ARITHMETIC, so the next person can re-derive it rather than trust it:
#
#     12000 rpm / 60            = 200 revolutions per second
#     x 60 teeth                = 12000 teeth per second
#     1 / 12000                 = 83.3 us between teeth
#     x 10 MIPS                 = 833 instructions, TOTAL
#
# and 833 is the whole tooth, shared with the S5500 raster, the K-line, the
# ADC, the capture ISR itself and every other thing the main loop owes. The
# scheduler's share is MAX_SHARE of it.
#
# DESIGNING TO 833 WOULD BE DESIGNING TO THE CLIFF. At 100 % of a tooth the
# engine stops working the instant anything else needs a cycle, and the things
# that need cycles - a Burn, a supervision frame, a TunerStudio page read -
# are exactly the things that happen while an engine is running. The 75 %
# share is the margin, and it is unchanged from when the target was 7500:
# what moved is the speed, not the discipline.
TARGET_RPM = 12000
TARGET_TEETH = 60
MAX_SHARE = 0.75

# The predecessor. This is the hardcoded-V8 planner's measured cost, taken by
# checking out hcsched_dry.c at aa5cb51, rebuilding, and running exactly the
# loop below. It is recorded here because the file it came from no longer
# exists, and a bound with no provenance is a bound nobody can re-derive.
BASELINE_V8 = 1679
BASELINE_SRC = "hcsched_dry.c at aa5cb51, rebuilt and measured 2026-09-02"

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-54s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def tooth_us(rpm: int, teeth: int = TARGET_TEETH) -> float:
    """Microseconds between teeth. rev/s = rpm/60, teeth/s = that * teeth."""
    return 1e6 / (rpm / 60.0 * teeth)


def budget(rpm: int, teeth: int = TARGET_TEETH) -> float:
    """The WHOLE tooth: every instruction the CPU can retire between two
    teeth, shared by everything the machine owes."""
    return tooth_us(rpm, teeth) * MIPS


def allowance(rpm: int, teeth: int = TARGET_TEETH) -> float:
    """THE SCHEDULER'S SHARE OF IT, and the number a change is measured
    against.

    These two were being printed as if they were interchangeable - "worst 1431
    of 833 available ... (limit 75%)" - which reads as though 833 were the
    thing to beat. It is not, and neither was the "ceiling" printed beside it:
    that was rpm * budget / worst, the speed at which the scheduler would
    consume 100 % of every tooth, computed under a discipline that says 75 %.
    A report that needs the reader to do the arithmetic is a report that will
    eventually be quoted without it."""
    return budget(rpm, teeth) * MAX_SHARE


def measure_both(cylinders: int, rpm: int, teeth: int = TARGET_TEETH):
    """(worst tooth, worst STEADY-STATE tooth) over one revolution.

    TWO NUMBERS, BECAUSE THEY ARE TWO DIFFERENT ENGINEERING QUANTITIES AND THE
    PROJECT HAS BEEN DESIGNING AGAINST THE WRONG ONE.

    Tooth #1 is the first tooth after `seed_cursors()`, and it is the most
    expensive of the revolution by a wide margin - measured on V68, 6
    cylinders at 12000 rpm, **1364 against a steady-state worst of 780**. It
    recurs on every sync ACQUISITION, so it is real and the gate keeps failing
    on it: sync can be lost and re-acquired at speed.

    But it is not the tooth the engine spends its life on, and the difference
    is the difference between 218 % of the allowance and 125 % of it. A
    redesign sized against 1364 is sized against a transient. Both are printed
    for that reason, and `me711_plan_profile.py --steady --top N` attributes
    the steady one instruction by instruction.
    """
    worst = steady = 0
    for k, used in _revolution(cylinders, rpm, teeth):
        worst = max(worst, used)
        if k > 1:
            steady = max(steady, used)
    return worst, steady


def measure(cylinders: int, rpm: int, teeth: int = TARGET_TEETH) -> int:
    """Worst hc_drysched_service() cost over one revolution of clean teeth."""
    return measure_both(cylinders, rpm, teeth)[0]


def planning_fixture(cylinders, teeth=TARGET_TEETH):
    c = PT.Call()
    PT.describe_engine(c, cylinders=cylinders, teeth=teeth)
    c.call("hc_drysched_init")
    c.enable_deadlines()
    c.m.w8(PT.sym('trg_state')&0xffff,3)
    # Concrete board routes; charging no pin under-reports backend work.
    for offset, values in ((2551,[96,97,88,89,112,113,24,19]),
                           (2563,[102,103,94,95,110,111,8,7])):
        for i, value in enumerate(values+[255]*4): c.m.w8(0x38000c+offset+i,value)
    # V84: MEASURE WITH THE OUTPUTS LIVE. Until V84 this rig never granted the
    # class permissions (and never set the V63..V83 page arm), so every
    # hc_hal_out_group() call returned at the permission check and NOT ONE
    # port write was ever in the measured tooth - the gate priced a scheduler
    # that drives nothing. Measured 2026-09-26 with outputs live and routes
    # resolved outside the revolution: armed V83 661/672/683/706 for 4/6/8/12
    # cylinders, V84 659/669/681/703. The per-routed-slot group write is real
    # work and it is now in the number. The arm byte is written for images
    # that still read it; V84+ ignore it.
    for name in ("hc_ignition_allowed", "hc_injection_allowed"):
        c.m.w16(PT.sym(name) & 0xFFFF, 1)
    c.m.w16(PT.sym("hc_cfg_validation") & 0xFFFF, 0)
    c.m.w8((PT.sym("hc_cfg") & 0xFFFF) + 68, 1)          # CFG_OUTPUTS_ARMED
    rev = PT.sym("hc_cfg_active_rev") & 0xFFFF
    c.m.w16(rev, (c.m.r16(rev) + 7) & 0xFFFF)
    c.call("hc_hal_outputs_live")                        # refresh a V83 arm cache
    c.call("hc_hal_out_group", 0, 0, 0)                  # resolve routes OUTSIDE
    c.call("hc_hal_out_group", 8, 0, 0)                  # the measured revolution
    # A plausible operating point: 20 degrees advance, 3.0 ms dwell, 5 ms pulse.
    for name, v in (("eng_adv_x10", 200), ("eng_dwell_x100", 300),
                    ("eng_ti_base_us", 10000), ("eng_deadtime_us", 0)):
        c.m.w16(PT.sym(name) & 0xFFFF, v)
    return c


def _revolution(cylinders: int, rpm: int, teeth: int = TARGET_TEETH):
    """Yield (tooth index, instructions) for one revolution of clean teeth."""
    dt = round(1_250_000 / rpm)
    c = planning_fixture(cylinders, teeth)
    step = 3600 // teeth
    c.set_t1(1000)
    c.call("hc_drysched_tooth", 0, 1000, dt)
    c.call("hc_drysched_service", 1000, 3)      # prime: cache + first angle
    stamp = 1000
    for k in range(1, teeth):
        stamp = (stamp + dt) & 0xFFFF
        c.set_t1(stamp)
        c.call("hc_drysched_tooth", (k * step) % 7200, stamp, dt)
        before = c.c.steps
        c.call("hc_drysched_service", stamp, 3)
        yield k, c.c.steps - before


def rows_at(rpm: int):
    return [(cyl, measure(cyl, rpm)) for cyl in (4, 6, 8, 12)]


def rows_both_at(rpm: int):
    return [(cyl,) + measure_both(cyl, rpm) for cyl in (4, 6, 8, 12)]


def verdict(rows, rpm: int = TARGET_RPM):
    """The three checks, over already-measured rows. Separated from main() so
    tests/unit/test_plan_cost_gate.py can feed it mutated numbers and prove each one
    is capable of failing."""
    out = []
    b = budget(rpm)
    a = allowance(rpm)
    worst = max(g for _, g in rows)
    out.append(("every cylinder count plans one tooth inside the "
                "scheduler's share at %d rpm" % rpm,
                worst <= a,
                "worst %d of %.0f allowed (%.0f%% of the %.0f-instruction "
                "tooth at %d%% share); sustainable to %d rpm"
                % (worst, a, worst * 100.0 / a, b, MAX_SHARE * 100.0,
                   int(rpm * a / worst))))

    # THE COST IS O(1) IN CYLINDER COUNT, AND THE OLD CHECK COULD NOT SEE IT.
    #
    # It fitted a straight line - max |g - g(4)| / (c - 4) - through numbers
    # that are not on a line. Measured at 12000 rpm on the V65 image:
    #
    #      3 cyl 1358   4 cyl 1112   5 cyl 1112   6 cyl 1358
    #      8 cyl 1112  10 cyl 1112  12 cyl 1358
    #
    # TWO VALUES, and which one an engine gets is decided by where its TDCs
    # fall on the tooth grid, not by how many it has: 8 cylinders cost exactly
    # what 4 cost, 12 cost exactly what 6 cost. The slope through (4, 1112) and
    # (6, 1358) is 123 "instructions per extra cylinder", which the gate then
    # reported as an O(n) planner - while the same rows contain two doublings
    # that cost ZERO. The planner has been O(1) in cylinder count since it
    # became cursor-based; the check was fitting alignment noise.
    #
    # So the property is stated the way the architecture states it: DOUBLING
    # THE CYLINDER COUNT MUST NOT COST ANYTHING. That still goes red for the
    # per-cylinder planner this replaced, where 8 cost 1814 against 4's 1262 -
    # tests/unit/test_plan_cost_gate.py feeds it exactly those numbers.
    per = dict(rows)
    doublings = [(c, 2 * c) for c in (4, 6) if c in per and 2 * c in per]
    worst_pair, worst_delta = None, 0
    for lo, hi in doublings:
        d = per[hi] - per[lo]
        if worst_pair is None or d > worst_delta:
            worst_pair, worst_delta = (lo, hi), d
    out.append(("doubling the cylinder count costs nothing",
                worst_delta <= 8,
                "%d -> %d cylinders: %+d instructions (%s)"
                % (worst_pair[0], worst_pair[1], worst_delta,
                   ", ".join("%dc=%d" % (c, g) for c, g in sorted(rows)))))

    v8 = dict(rows)[8]
    out.append(("no regression past the hardcoded V8 it replaced",
                v8 <= BASELINE_V8,
                "%d vs %d baseline = %.2fx  (%s)"
                % (v8, BASELINE_V8, v8 / BASELINE_V8, BASELINE_SRC)))
    return out


def main() -> int:
    print("=== HaniCore - what one tooth of scheduling costs ===\n")
    print("  image   %s" % PI.image().name)
    print("  sha256  %s\n" % PI.sha256())

    print("  At %g MIPS, a 60-tooth wheel. The TOOTH is the whole budget;"
          % MIPS)
    print("  the SCHEDULER'S SHARE of it is %.0f%% and that is the number to "
          "beat:" % (MAX_SHARE * 100.0))
    print("      %5s  %9s  %12s  %12s" % ("rpm", "us/tooth", "tooth", "share"))
    for rpm in (800, 3000, 6000, 7500, 12000):
        print("      %5d  %8.1f   %7.0f instr  %7.0f instr"
              % (rpm, tooth_us(rpm), budget(rpm), allowance(rpm)))
    print("")

    both = rows_both_at(TARGET_RPM)
    rows = [(c, w) for c, w, _s in both]
    a = allowance(TARGET_RPM)
    print("  --- worst hc_drysched_service(), one revolution of clean teeth ---")
    print("  WORST is the tooth after seed_cursors(), which recurs on every "
          "sync ACQUISITION\n  and is what the check below uses. STEADY is the "
          "worst of the rest - the tooth\n  the engine spends its life on. "
          "Designing against WORST is designing against a\n  transient; "
          "designing against STEADY alone would ignore a tooth that really "
          "happens.\n")
    print("      %-14s %8s %8s   %8s %8s" % ("", "WORST", "of share",
                                             "STEADY", "of share"))
    for cyl, got, steady in both:
        print("      %2d cylinders   %8d %7.0f%%   %8d %7.0f%%"
              % (cyl, got, got * 100.0 / a, steady, steady * 100.0 / a))
    ws = max(s for _c, _w, s in both)
    print("\n      at %d rpm, allowance %.0f: sustainable to %d rpm on the "
          "worst tooth,\n      %d rpm on the steady-state one"
          % (TARGET_RPM, a, int(TARGET_RPM * a / max(w for _c, w, _s in both)),
             int(TARGET_RPM * a / ws)))
    print("")

    for name, ok, detail in verdict(rows):
        check(name, ok, detail)

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("PLAN COST FAILS - the tooth path no longer fits the tooth. "
              "Read the header: the fix is never to make the scheduler less "
              "configurable, it is to move configuration work to the apply "
              "boundary.")
        return 1
    print("PLAN COST PROOF PASSES - the tooth path fits the tooth at %d rpm "
          "on a %d-tooth wheel, for 4 to 12 cylinders."
          % (TARGET_RPM, TARGET_TEETH))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
