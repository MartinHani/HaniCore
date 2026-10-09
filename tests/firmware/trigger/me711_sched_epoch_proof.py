#!/usr/bin/env python3
r"""
me711_sched_epoch_proof.py - the angle accumulator must survive its own wrap.

    py tests\firmware\trigger\me711_sched_epoch_proof.py

WHAT THIS IS ABOUT.

hcsched_dry.c keeps `angle_epoch`, an unbounded accumulator of tenths of a
crank degree since sync. At 7500 rpm it gains 450 000 counts a second, so a
32-bit accumulator reaches its end in 2 h 39 min. At idle it takes about a day.
An endurance run or a long dyno session gets there.

TWO DEFECTS LIVED AT THAT BOUNDARY, and this file exists because neither of
them announces itself:

  1. plan_epoch[i] is angle_epoch plus a horizon of at most 7200. Near the end
     the plan wrapped to a small number while the epoch was still huge, so the
     ordering test `plan_epoch[i] < angle_epoch` read "already past" and
     CANCELLED the event. At 7500 rpm that is roughly 16 ms of dropped
     ignition and injection events - a misfire once every few hours.

  2. Worse, and permanent: ev_angle is plan_epoch % 7200, and 2^32 is not a
     whole number of 720-degree cycles. 2^32 mod 7200 = 1696, so after a wrap
     every scheduled angle was wrong by 169.6 DEGREES until the next resync.

A defect that needs two hours of running to appear cannot be reached by
simulating teeth one at a time, so the module exposes
hc_drysched_test_set_epoch(hi, lo). Everything below then runs the REAL
staging and due cores out of the linked image.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_image as PI          # noqa: E402
import me711_trigger_test as PT   # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "firmware/targets/me711/engine/hcsched_dry.c"

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-60s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def wrap_constant():
    """DRY_EPOCH_WRAP from the source, not retyped here."""
    m = re.search(r"#define\s+DRY_EPOCH_WRAP\s+\((\d+)uL\s*\*\s*(\d+)uL\)",
                  SRC.read_text(errors="replace"))
    if not m:
        raise SystemExit("DRY_EPOCH_WRAP not found in hcsched_dry.c")
    return int(m.group(1)) * int(m.group(2))


def rig():
    c = PT.Call()
    c.call("hc_drysched_init")
    return c


def epoch(c):
    return (c.call("hc_drysched_test_epoch_hi") << 16) \
        | c.call("hc_drysched_test_epoch_lo")


def set_epoch(c, v):
    c.call("hc_drysched_test_set_epoch", (v >> 16) & 0xFFFF, v & 0xFFFF)


def main() -> int:
    print("=== HaniCore ME7.1.1 - the angle epoch across its wrap ===\n")
    print("  image   %s" % PI.image().name)
    print("  sha256  %s" % PI.sha256())
    WRAP = wrap_constant()
    print("  DRY_EPOCH_WRAP = %d  (%d x 7200, %s)\n"
          % (WRAP, WRAP // 7200,
             "a whole number of cycles" if WRAP % 7200 == 0
             else "NOT CYCLE ALIGNED"))

    # -------------------------------------------------- the constant itself
    check("the rebase point is a whole number of 720-degree cycles",
          WRAP % 7200 == 0,
          "%d mod 7200 = %d - if this were not 0 the modulo would shift"
          % (WRAP, WRAP % 7200))
    check("and it leaves headroom below 2^32 for the 7200-count horizon",
          WRAP + 7200 < 2 ** 32,
          "%d + 7200 < %d" % (WRAP, 2 ** 32))

    # ------------------------------------------------ the hook works at all
    c = rig()
    c.call("hc_drysched_test_anchor", 1000)
    set_epoch(c, 0x12345678)
    check("the epoch test hook round-trips a 32-bit value",
          epoch(c) == 0x12345678, "0x%08X" % epoch(c))

    # ------------------------------------------ the rebase actually happens
    c = rig()
    c.call("hc_drysched_test_anchor", 0)
    before_rebases = c.u16("dry_sched_rebases")
    set_epoch(c, WRAP - 60)
    e0 = epoch(c)
    # one ordinary tooth of 6.0 degrees takes it over the line
    c.call("hc_drysched_test_advance", 60, 0xF200, 2000)
    e1 = epoch(c)
    check("crossing the rebase point is counted",
          c.u16("dry_sched_rebases") == before_rebases + 1,
          "dry_sched_rebases %d -> %d"
          % (before_rebases, c.u16("dry_sched_rebases")))
    check("and the accumulator comes back down",
          e1 < e0 and e1 < WRAP,
          "0x%08X -> 0x%08X" % (e0, e1))
    check("the crank angle is PRESERVED across the rebase",
          (e1 % 7200) == ((e0 + 60) % 7200),
          "epoch%%7200 %d before, %d after - a shift here is a wrong firing "
          "angle" % ((e0 + 60) % 7200, e1 % 7200))

    # --------------------------------- an event straddling the rebase point
    #
    # THE DEFECT ITSELF. Schedule an event 60 counts ahead while the epoch is
    # 30 counts below the rebase point, so the plan is on the far side of it.
    # The old code cancelled exactly this event.
    c = rig()
    c.call("hc_drysched_test_anchor", 0)
    set_epoch(c, WRAP - 30)
    # A dwell reserves its independent ending. An unowned spark is now
    # correctly refused, so use a legitimate pulse to exercise angle staging.
    accepted = c.call("hc_drysched_schedule_after", 60, 1, 1)
    missed0 = c.u16("dry_sched_missed")
    pending0 = c.u16("dry_sched_pending")
    check("an event is accepted just below the rebase point", accepted == 1,
          "pending=%d" % pending0)

    stamp, dt = 0xF200, 2000
    c.set_t1(stamp)
    c.call("hc_drysched_test_advance", 60, stamp, dt)
    check("crossing the rebase does NOT cancel it as already-past",
          c.u16("dry_sched_missed") == missed0,
          "missed %d -> %d" % (missed0, c.u16("dry_sched_missed")))
    check("and it is still live",
          c.u16("dry_sched_pending") + c.u16("dry_sched_queued") > 0,
          "pending=%d queued=%d"
          % (c.u16("dry_sched_pending"), c.u16("dry_sched_queued")))

    # -------------------------- and it still fires at the right crank angle
    c = rig()
    c.call("hc_drysched_test_anchor", 0)
    set_epoch(c, WRAP - 30)
    c.call("hc_drysched_schedule_after", 60, 1, 1)
    for k in range(4):
        c.set_t1((stamp + dt * (k + 1)) & 0xFFFF)
        c.call("hc_drysched_test_advance", (60 * (k + 1)) % 7200,
               (stamp + dt * (k + 1)) & 0xFFFF, dt)
    got = c.u16("dry_sched_next_angle")
    want = (WRAP - 30 + 60) % 7200
    check("the staged angle is the true crank angle, not one shifted by the "
          "wrap", got == want,
          "next_angle %d, expected %d (a 2^32 wrap would shift it by 1696)"
          % (got, want))

    # ------------------------------------------- the arithmetic, on the host
    #
    # Why the ordering test had to change, shown rather than asserted.
    print("\n--- the two predicates, on the numbers that used to break ---")
    epoch32 = 2 ** 32 - 3000          # near the old wrap
    plan32 = (epoch32 + 7200) % (2 ** 32)   # a legitimate 720-degree horizon
    old = plan32 < epoch32
    # The C is 32-bit modular; Python's integers are not, so mask first and
    # only then read the result as signed - which is exactly what the C does.
    diff = (plan32 - epoch32) & 0xFFFFFFFF
    new = (diff - 2 ** 32) if diff >= 2 ** 31 else diff
    check("the OLD predicate calls a future event already-past", old is True,
          "plan 0x%08X < epoch 0x%08X" % (plan32, epoch32))
    check("the SIGNED difference gets it right", new > 0,
          "ahead = %+d counts, which is the real horizon" % new)
    check("and the old modulo shifted the angle by 169.6 degrees",
          (plan32 % 7200) != ((epoch32 + 7200) % 7200),
          "%d vs %d" % (plan32 % 7200, (epoch32 + 7200) % 7200))

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("THE ANGLE ACCUMULATOR DOES NOT SURVIVE ITS WRAP.")
        return 1
    print("EPOCH PROOF PASSES - the accumulator rebases on a cycle boundary,\n"
          "events that straddle it are kept, and the crank angle is preserved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
