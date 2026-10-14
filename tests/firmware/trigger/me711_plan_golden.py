#!/usr/bin/env python3
r"""
me711_plan_golden.py - the cylinder event geometry against an independent
reference, executed out of the linked image.

    py tests\firmware\trigger\me711_plan_golden.py

WHY THIS EXISTS.

Until this work the Bosch dry scheduler computed its event angles like this:

    for (i = 0; i < 8u; i++) {
        unsigned int fire = (unsigned int)(i * 900u);
        unsigned int inj_end = sub720(fire, 3600u);

Eight cylinders, 90 degrees apart, a 720 degree cycle, one event each, and
injection ending 360 degrees before TDC. A Cayenne V8 with sequential
ignition, compiled into a firmware whose stated premise is that the engine is
configuration - and every one of those numbers was already in the universal
page. hc_plan.c replaces it, and this file is what stops the replacement from
being a different set of assumptions with better comments.

THREE THINGS ARE CHECKED, and the third is the one that matters most.

1. THE ARITHMETIC, against ordinary Python doing the same job independently.
   Not a transcription of the C: if it were, the two would agree about the
   same mistake.

2. THE OLD BEHAVIOUR IS REPRODUCED EXACTLY. Configure a V8 four-stroke with an
   empty TDC table and sequential COP, and hc_plan must produce precisely the
   angles the hardcoded loop produced - 0, 90, 180 ... 630 degrees. A
   generalisation that cannot reproduce the special case it replaces has
   changed behaviour rather than generalised it, and the ONE engine this
   firmware is about to be tested on is that special case.

3. EVERY STRATEGY PRODUCES THE RIGHT NUMBER OF EVENTS PER OUTPUT PER CYCLE.
   This is where the design can be wrong in a way no single angle reveals: a
   wasted-COP coil needs two firings a cycle and a wasted-PAIRED coil also
   needs two, but they get them by different mechanisms - a repeat in the
   first case, the paired cylinder's own event in the second. Applying both
   would double every spark; applying neither would halve it. So the events
   are ENUMERATED, per slot, and counted.

Everything runs in c167sim against the real linked image, so this is evidence
about the code that will be flashed rather than about the source.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_config_state_test as C   # noqa: E402  the Rig
import me711_image as PI              # noqa: E402

FAILS = 0
CHECKS = 0

REV = 3600                            # one crank revolution, 0.1 deg

# The strategy enums, read from the generated header rather than retyped -
# a copy here is a copy that can drift.
ROOT = Path(__file__).resolve().parents[3]
_GEN = (ROOT / "firmware/generated/hc_config_generated.h").read_text(
    errors="replace")


def enum(name: str) -> int:
    import re
    m = re.search(r"#define\s+%s\s+(\d+)u" % name, _GEN)
    if not m:
        raise SystemExit("enum %s not found in hc_config_generated.h" % name)
    return int(m.group(1))


INJ_BATCH = enum("HC_INJ_BATCH")
INJ_SEMI = enum("HC_INJ_SEMI_SEQ")
INJ_SEQ = enum("HC_INJ_SEQUENTIAL")
IGN_PAIRED = enum("HC_IGN_WASTED_PAIRED")
IGN_WCOP = enum("HC_IGN_WASTED_COP")
IGN_SCOP = enum("HC_IGN_SEQUENTIAL_COP")
IGN_DIST = enum("HC_IGN_DISTRIBUTOR")


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


class Plan(C.Rig):
    """The Rig, plus the 32-bit ARGUMENT convention.

    hc_plan_dur_to_angle_x10() takes an `unsigned long` first, which Keil C166
    passes as a register pair - R8 low, R9 high - with the remaining 16-bit
    arguments following. The same convention me711_fuel_golden.py established
    for hc_af_*; it is repeated here rather than imported so this gate does not
    fail because the fuel one moved.
    """

    def u16a(self, fn, lo32, *rest):
        self(fn, lo32 & 0xFFFF, (lo32 >> 16) & 0xFFFF, *rest)
        return self.c.gr(4) & 0xFFFF


# ------------------------------------------------------------- references --
def ref_cycle(strokes):
    return 2 * REV if strokes == 4 else REV


def ref_sub(a, b, cycle):
    if cycle == 0:
        return 0
    a %= cycle
    b %= cycle
    return a - b if a >= b else a + cycle - b


def ref_even_tdc(cyl, cylinders, cycle):
    if cylinders == 0:
        return 0
    return (cyl % cylinders) * cycle // cylinders


def ref_dur_to_angle(ticks, tooth_dt, tooth_x10, cycle):
    if tooth_dt == 0 or tooth_x10 == 0:
        return 0
    a = ticks * tooth_x10 // tooth_dt
    if cycle and a > cycle:
        a = cycle
    return min(a, 65535)


def ref_ign_slot(cyl, n, strategy):
    if n == 0:
        return 0
    cyl %= n
    half = max(n // 2, 1)
    if strategy == IGN_PAIRED:
        return cyl % half + 1
    if strategy == IGN_DIST:
        return 1
    return cyl + 1


def ref_inj_slot(cyl, n, strategy):
    if n == 0:
        return 0
    cyl %= n
    half = max(n // 2, 1)
    if strategy == INJ_BATCH:
        return 0
    # SEMI-SEQ: every injector its own output (2026-10-10 - the pair
    # model drove half the injectors on the AWT car).
    return cyl + 1


# ------------------------------------------------------------------- main --
def main() -> int:
    print("=== HaniCore - cylinder event geometry against a reference ===\n")
    print("  image   %s" % PI.image().name)
    print("  sha256  %s\n" % PI.sha256())

    r = Plan()

    # -------------------------------------------------------- cycle length
    print("--- cycle length ---")
    for strokes in (0, 1, 2, 4, 5, 255):
        got = r("hc_plan_cycle_x10", strokes)
        want = ref_cycle(strokes)
        check("%3d strokes -> %d deg" % (strokes, want // 10),
              got == want, "got %d" % got)

    # ------------------------------------------------------ modular subtract
    print("\n--- angle subtraction, wrapped into the cycle ---")
    cases = [(0, 100, 7200), (7100, 200, 7200), (3600, 3600, 7200),
             (100, 7300, 7200), (9000, 100, 7200), (0, 0, 3600),
             (500, 900, 3600), (1, 2, 0)]
    for a, b, cyc in cases:
        got = r("hc_plan_sub_x10", a, b, cyc)
        want = ref_sub(a, b, cyc)
        check("(%d - %d) mod %d = %d" % (a, b, cyc, want),
              got == want, "got %d" % got)

    # --------------------------------------------------------- even spacing
    #
    # THE SPECIAL CASE THIS REPLACED. The hardcoded loop used i*900 for a V8
    # on a 720 degree cycle. If this row does not reproduce 0, 900, 1800 ...
    # 6300 exactly, the generalisation has changed the behaviour of the one
    # engine that is about to be bench tested.
    print("\n--- even TDC spacing, and the V8 the old loop had compiled in ---")
    v8 = [r("hc_plan_even_tdc_x10", i, 8, 7200) for i in range(8)]
    check("a V8 on a four-stroke reproduces the old i*900 exactly",
          v8 == [i * 900 for i in range(8)], "%s" % v8)
    for n in (1, 2, 3, 4, 5, 6, 8, 10, 12):
        got = [r("hc_plan_even_tdc_x10", i, n, 7200) for i in range(n)]
        want = [ref_even_tdc(i, n, 7200) for i in range(n)]
        check("%2d cylinders, four-stroke" % n, got == want,
              "%s%s" % (got[:6], " ..." if n > 6 else ""))
    check("zero cylinders returns 0 rather than dividing",
          r("hc_plan_even_tdc_x10", 3, 0, 7200) == 0)

    # ------------------------------------------------------ tooth spacing
    print("\n--- tenths of a degree per tooth ---")
    for teeth, want in ((60, 60), (36, 100), (24, 150), (12, 300),
                        (0, 0), (4000, 0)):
        got = r("hc_plan_tooth_x10", teeth)
        check("%4d teeth -> %d" % (teeth, want), got == want, "got %d" % got)

    # -------------------------------------------------- duration to angle
    #
    # A ratio, so the timer frequency cancels. 3 ms of dwell at 1.25 MHz is
    # 3750 ticks; a tooth of 6.0 degrees taking 1250 ticks is 200 rpm-ish, so
    # the dwell spans 18 degrees.
    print("\n--- duration to crank angle ---")
    dur = [(3750, 1250, 60, 7200), (3750, 125, 60, 7200),
           (0, 1250, 60, 7200), (1000, 0, 60, 7200),
           (1000, 1250, 0, 7200), (100000, 100, 60, 7200)]
    for ticks, dt, tooth, cyc in dur:
        got = r.u16a("hc_plan_dur_to_angle_x10", ticks, dt, tooth, cyc)
        want = ref_dur_to_angle(ticks, dt, tooth, cyc)
        check("%6d ticks / %4d per tooth of %d -> %d" % (ticks, dt, tooth, want),
              got == want, "got %d" % got)

    # ------------------------------------------ V97: pairs by firing order
    #
    # hc_plan_pair_lead(tdc, cyl, n): the cylinder whose output a paired
    # strategy uses for `cyl` - the one at firing position (pos(cyl) mod n/2).
    # The TDC table is written into adc_raw (a public near array this rig
    # never reads) and passed by its near address.
    print("\n--- V97: pairing by firing order (hc_plan_pair_lead) ---")
    scratch = C.sym("adc_raw") & 0xFFFF

    def ref_lead(tdc, c):
        n = len(tdc)
        pos = lambda k: sum(1 for j in range(n)
                            if tdc[j] < tdc[k] or (tdc[j] == tdc[k] and j < k))
        want = pos(c) % max(1, n // 2)
        return next(j for j in range(n) if pos(j) == want)

    def lead(tdc):
        for i, v in enumerate(tdc):
            r.m.w16(scratch + 2 * i, v)
        return [r("hc_plan_pair_lead", scratch, i, len(tdc))
                for i in range(len(tdc))]

    awt = [0, 5400, 1800, 3600]                     # 1-3-4-2
    check("AWT 1-3-4-2: pairs 1/4 on cylinder 1, 3/2 on cylinder 3",
          lead(awt) == [0, 2, 2, 0], "%s" % lead(awt))
    fo = [1, 3, 7, 2, 6, 5, 4, 8]                   # Porsche V8 firing order
    v8t = [0] * 8
    for k, cyl in enumerate(fo):
        v8t[cyl - 1] = k * 900
    got = lead(v8t)
    check("V8 1-3-7-2-6-5-4-8: every pair 360 deg apart",
          all((v8t[got[i]] - v8t[i]) % 3600 == 0 for i in range(8))
          and got == [ref_lead(v8t, i) for i in range(8)], "%s" % got)
    import random
    rnd = random.Random(97)
    bad = []
    for _ in range(40):
        n = rnd.choice((2, 4, 6, 8))
        order = list(range(n))
        rnd.shuffle(order)
        tdc = [0] * n
        for k, c in enumerate(order):
            tdc[c] = k * (7200 // n)
        g = lead(tdc)
        if g != [ref_lead(tdc, i) for i in range(n)] or not all(
                (tdc[g[i]] - tdc[i]) % 3600 == 0 for i in range(n)):
            bad.append((tdc, g))
    check("40 random firing orders: lead = reference, pairs 360 apart",
          not bad, "%s" % bad[:1])

    # ----------------------------------------------------- slot assignment
    print("\n--- cylinder to logical output ---")
    for n in (1, 2, 3, 4, 5, 6, 8, 10, 12):
        for strat, nm in ((IGN_SCOP, "seq COP"), (IGN_WCOP, "wasted COP"),
                          (IGN_PAIRED, "wasted paired"), (IGN_DIST, "distrib")):
            got = [r("hc_plan_ign_slot", i, n, strat) for i in range(n)]
            want = [ref_ign_slot(i, n, strat) for i in range(n)]
            check("ign %-14s %2d cyl" % (nm, n), got == want, "%s" % got)
    for n in (1, 2, 3, 4, 5, 6, 8, 10, 12):
        for strat, nm in ((INJ_SEQ, "sequential"), (INJ_SEMI, "semi-seq"),
                          (INJ_BATCH, "batch")):
            got = [r("hc_plan_inj_slot", i, n, strat) for i in range(n)]
            want = [ref_inj_slot(i, n, strat) for i in range(n)]
            check("inj %-14s %2d cyl" % (nm, n), got == want, "%s" % got)

    # ---------------------------------------------------- sync requirement
    #
    # The runtime must not be stricter than hc_validation.c, which already told
    # the tuner the configuration was legal. Wasted COP is the case people get
    # wrong: individual coils, no cam needed.
    print("\n--- which strategies need to know the revolution ---")
    want_cycle = {
        (INJ_BATCH, IGN_PAIRED): 0, (INJ_BATCH, IGN_WCOP): 0,
        (INJ_BATCH, IGN_DIST): 0, (INJ_BATCH, IGN_SCOP): 1,
        (INJ_SEMI, IGN_PAIRED): 0, (INJ_SEMI, IGN_WCOP): 0,
        (INJ_SEMI, IGN_DIST): 0, (INJ_SEMI, IGN_SCOP): 1,
        (INJ_SEQ, IGN_PAIRED): 1, (INJ_SEQ, IGN_WCOP): 1,
        (INJ_SEQ, IGN_DIST): 1, (INJ_SEQ, IGN_SCOP): 1,
    }
    names = {INJ_BATCH: "batch", INJ_SEMI: "semi-seq", INJ_SEQ: "sequential",
             IGN_PAIRED: "wasted paired", IGN_WCOP: "wasted COP",
             IGN_DIST: "distributor", IGN_SCOP: "seq COP"}
    for (inj, ign), want in sorted(want_cycle.items()):
        got = r("hc_plan_needs_cycle", inj, ign)
        check("%-10s + %-14s -> %s" % (names[inj], names[ign],
                                       "cam" if want else "crank only"),
              got == want, "got %d" % got)
    check("wasted COP does NOT need a cam - COP is not the question",
          r("hc_plan_needs_cycle", INJ_BATCH, IGN_WCOP) == 0)

    # ------------------------------------- events per output, per cycle ---
    #
    # THE CHECK THE DESIGN CAN ACTUALLY FAIL. Every output must fire the right
    # number of times per 720 degrees, and the two wasted modes reach that
    # number by different mechanisms: WASTED_COP by a repeat, WASTED_PAIRED by
    # the paired cylinder's own event. Doing both doubles every spark; doing
    # neither halves it. Enumerating is the only way to see which.
    print("\n--- events per output per cycle, enumerated ---")

    def enumerate_ign(n, strat, strokes=4, tdc=None):
        cyc = ref_cycle(strokes)
        walk = r("hc_plan_ign_cyls", n)
        rep = r("hc_plan_ign_repeats", strat, strokes)
        out = {}
        for i in range(walk):
            base = tdc[i] if tdc else ref_even_tdc(i, n, cyc)
            slot = r("hc_plan_ign_slot", i, n, strat)
            for k in range(rep):
                a = r("hc_plan_repeat_x10", base, k, cyc)
                out.setdefault(slot, []).append(a)
        return out

    def enumerate_inj(n, strat, strokes=4):
        cyc = ref_cycle(strokes)
        walk = r("hc_plan_inj_cyls", n, strat)
        rep = r("hc_plan_inj_repeats", strat, strokes)
        out = {}
        for i in range(walk):
            base = ref_even_tdc(i, n, cyc)
            slot = r("hc_plan_inj_slot", i, n, strat)
            for k in range(rep):
                out.setdefault(slot, []).append(
                    r("hc_plan_repeat_x10", base, k, cyc))
        return out

    for n in (4, 6, 8, 12):
        ev = enumerate_ign(n, IGN_SCOP)
        check("seq COP, %2d cyl: %d coils, 1 spark each per cycle" % (n, n),
              len(ev) == n and all(len(v) == 1 for v in ev.values()),
              "%d slots" % len(ev))

        ev = enumerate_ign(n, IGN_WCOP)
        ok = len(ev) == n and all(len(v) == 2 for v in ev.values())
        spaced = all(abs(sorted(v)[1] - sorted(v)[0]) == REV
                     for v in ev.values())
        check("wasted COP, %2d cyl: %d coils, 2 sparks 360 apart" % (n, n),
              ok and spaced, "%d slots, spacing %s" % (len(ev), "ok" if spaced
                                                       else "WRONG"))

        ev = enumerate_ign(n, IGN_PAIRED)
        ok = len(ev) == n // 2 and all(len(v) == 2 for v in ev.values())
        spaced = all(abs(sorted(v)[1] - sorted(v)[0]) == REV
                     for v in ev.values())
        check("wasted paired, %2d cyl: %d coils, 2 sparks 360 apart"
              % (n, n // 2), ok and spaced,
              "%d slots, spacing %s" % (len(ev), "ok" if spaced else "WRONG"))

        ev = enumerate_ign(n, IGN_DIST)
        check("distributor, %2d cyl: 1 coil, %d sparks per cycle" % (n, n),
              len(ev) == 1 and len(ev[1]) == n, "%d slots" % len(ev))

        ev = enumerate_inj(n, INJ_SEQ)
        check("sequential inj, %2d cyl: %d injectors, 1 pulse each" % (n, n),
              len(ev) == n and all(len(v) == 1 for v in ev.values()),
              "%d slots" % len(ev))

        ev = enumerate_inj(n, INJ_SEMI)
        spaced = all(abs(sorted(v)[1] - sorted(v)[0]) == REV
                     for v in ev.values())
        check("semi-seq inj, %2d cyl: %d injectors, 2 pulses each, 360 apart"
              % (n, n),
              len(ev) == n and spaced
              and all(len(v) == 2 for v in ev.values()),
              "%d slots" % len(ev))

        ev = enumerate_inj(n, INJ_BATCH)
        check("batch inj, %2d cyl: ONE bank, 2 pulses a cycle" % n,
              list(ev) == [0] and len(ev[0]) == 2,
              "%s" % ev)

    # A two-stroke has no exhaust TDC to waste a spark at, so every repeat
    # count collapses and wasted COP becomes one spark per revolution.
    ev = enumerate_ign(4, IGN_WCOP, strokes=2)
    check("two-stroke: wasted COP collapses to one spark per cycle",
          all(len(v) == 1 for v in ev.values()), "%s" % ev)
    ev = enumerate_inj(4, INJ_BATCH, strokes=2)
    check("two-stroke: batch collapses to one bank pulse per cycle",
          list(ev) == [0] and len(ev[0]) == 1, "%s" % ev)

    # ------------------------------------------- an UNEVEN firing engine ---
    #
    # The reason the pair supplies the second event instead of a "+360". A
    # 90-degree V-twin fires at 0 and 270 degrees on a 720 cycle. Wasted
    # paired must place its two sparks at THOSE angles, not 360 apart.
    print("\n--- an uneven-firing engine, where +360 would be wrong ---")
    tdc = [0, 2700]
    ev = enumerate_ign(2, IGN_PAIRED, tdc=tdc)
    check("90-degree V-twin, wasted paired: one coil at both real TDCs",
          len(ev) == 1 and sorted(ev[1]) == [0, 2700], "%s" % ev)

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("PLAN GOLDEN FAILS - the event geometry does not match.")
        return 1
    print("PLAN GOLDEN PASSES - the geometry is the configuration's, "
          "and it still reproduces the V8 it replaced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
