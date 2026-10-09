#!/usr/bin/env python3
r"""me711_trigger_generic_proof.py - the decoder decodes the wheel it is TOLD.

    py tests\firmware\trigger\me711_trigger_generic_proof.py

WHY THIS GATE EXISTS, AND WHY THE OLD ONE COULD NOT HAVE CAUGHT IT.

Until V55 `hctrig_me711.c` held ME711_TEETH 60, ME711_REAL_TEETH 58,
ME711_MIN_GOOD 30 and a four-entry cam reference table, and the gap rule was a
fixed `(candidate >> 1) > neighbour`. `syTeeth`, `syGap`, `trigEdge`,
`trigGapRatio` and `trigMinTeeth` were in the page, in the .ini and validated
per decoder by hc_validation.c, and NO RUNTIME PATH READ ANY OF THEM.

tests/firmware/trigger/me711_trigger_test.py wrote syTeeth and syGap into hc_cfg before every
run and then fed the decoder a 60-2. Both halves were green and neither could
fail: the rig only ever described the geometry the firmware already assumed.
That is the vacuous-proof failure the project rules warn about, in its purest form -
a test that configures a property it never varies.

So this gate varies it. Every case below drives the LINKED IMAGE's own
crank_edge() through a wheel built from the case's own geometry, and asserts
that sync, rpm, the published tooth angle and the decoder's readback of its own
configuration all follow.

THE NEGATIVE CONTROLS ARE THE POINT. In order:

  * 36-1 AT THE OLD FIXED RATIO. Its gap interval is exactly 2.0 tooth periods
    and the pre-V55 rule needs strictly more than 2.0, so with the ratio pinned
    at 2.0 the decoder must NEVER reach sync. This case fails against any
    implementation that ignores trigGapRatio - including every HaniCore build
    up to and including V54.

  * 36-1 SIGNAL INTO A 60-2 CONFIGURATION. A decoder that had its geometry
    compiled in would see a plausible gap and claim position anyway. This one
    must refuse.

  * A FOUR-REFERENCE CAM MUST NOT RESOLVE THE CYCLE. Four equally spaced
    references map onto themselves under a 360 degree shift, so syncState may
    not reach TRG_SYNC_FULL and trigCamResolves must read 0. A single-window
    cam on the same code must reach it.

  * THE 360-DEGREE PHASE CORRECTION. With a single-reference cam, an edge that
    arrives in the wrong half of the cycle must flip trg_phase and count a
    correction - not raise a cam fault.

  * AN EDIT MUST REACH THE DECODER. Changing the wheel in the page and
    re-reading it must move trg_cfg_teeth AND trg_cfg_generation. A decoder
    that latched its geometry at boot passes every other case here and fails
    this one.

  * PHASE LOSS AND RE-ACQUISITION. A cam that STOPS must cost the CYCLE and
    not the CRANK, and a cam that comes back must re-acquire unaided. V55
    raised the missing-cam bits and V56 stopped them being raised for a cam
    nobody described; neither ever demoted trg_state, so the decoder went on
    publishing TRG_SYNC_FULL with a dead cam. hc_drysched_service() was
    already written to withdraw sequential events on the way down and was
    waiting for a signal that never came. The negative control keeps the cam
    ALIVE for the same six revolutions, so a demotion driven by a revolution
    count rather than by the missing cam fails here.

Nothing here is a scheduler test; me711_sched_epoch_proof owns that.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_trigger_test as T                                   # noqa: E402

FAIL = 0
TICKS_PER_S = 1_250_000


def check(name, ok, detail=""):
    global FAIL
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<56} {detail}")
    FAIL += not ok


class Wheel:
    """A missing-tooth crank, fed into the linked decoder edge by edge.

    The edge train is built from the CASE's geometry, never from the
    firmware's: teeth, missing teeth and rpm decide the intervals, and the
    firmware is told the same numbers through the page. A mismatch between the
    two is what the negative controls deliberately create.
    """

    def __init__(self, teeth, gap, rpm, cyl=4, ratio_x10=None, min_teeth=None,
                 cam_refs=0, cam_ref_x10=0, cam_window_x10=300,
                 cam_sync_mode=0, cam_enable=None, cfg_teeth=None,
                 cfg_gap=None, offset_x10=0, plan=False):
        self.teeth, self.gap, self.rpm = teeth, gap, rpm
        # plan=True: also run the angle planner on every captured tooth, as
        # the CC26 level does on the ECU (it is not part of trg_service since
        # 2026-10-06), with the automatic output permissions the main loop's
        # safety service grants. For gates that look at scheduled events.
        self.plan = plan
        self.real = teeth - gap
        # ticks per tooth of the SIGNAL, from the signal's own geometry
        self.p = round(TICKS_PER_S * 60.0 / (rpm * teeth))
        self.x = T.Call()
        T.describe_engine(self.x, cylinders=cyl, strokes=4,
                          teeth=cfg_teeth if cfg_teeth is not None else teeth,
                          gap=cfg_gap if cfg_gap is not None else gap,
                          cam_refs=cam_refs, cam_ref_x10=cam_ref_x10,
                          cam_window_x10=cam_window_x10,
                          cam_sync_mode=cam_sync_mode)
        base = T.sym("hc_cfg") & 0xFFFF
        if ratio_x10 is not None:
            self.x.m.w8(base + T.off("CFG_TRIG_GAP_RATIO_X10"),
                        (ratio_x10 >> 8) & 0xFF)
            self.x.m.w8(base + T.off("CFG_TRIG_GAP_RATIO_X10") + 1,
                        ratio_x10 & 0xFF)
        self.x.m.w8(base + T.off("CFG_TRIG_MIN_TEETH"),
                    min_teeth if min_teeth is not None else 10)
        if cam_enable is None:
            cam_enable = 1 if cam_refs else 0
        self.x.m.w8(base + T.off("CFG_CAM_ENABLE"), cam_enable)
        if offset_x10:
            T.describe_cam(self.x, refs=cam_refs, ref_x10=cam_ref_x10,
                           window_x10=cam_window_x10, sync_mode=cam_sync_mode)
            o = T._uni(self.x, "CFG_U_TRIG_ANGLE_X10")
            self.x.m.w8(T.UNI_BASE + o, (offset_x10 >> 8) & 0xFF)
            self.x.m.w8(T.UNI_BASE + o + 1, offset_x10 & 0xFF)
        self.x.call("trg_init")
        self.x.call("trg_test_geometry")
        self.t = 1000
        self.edge(self.t, service=False)

    def service(self, t=None):
        if t is not None:
            self.x.set_t1(t)
        if self.plan:
            for n in ("hc_ignition_allowed", "hc_injection_allowed"):
                self.x.m.w16(T.sym(n) & 0xFFFF, 1)
            self.x.m.w16(T.sym("hc_cfg_validation") & 0xFFFF, 0)
        self.x.call("trg_service")

    def edge(self, t, service=True):
        self.t = t & 0xFFFF
        self.x.set_t1(self.t)
        self.x.call("trg_test_crank_edge", self.t)
        if self.plan:
            self.x.call("hc_drysched_service", self.t, self.x.u8("trg_state"))
        if service:
            self.service()

    def wait_edge(self, ticks, slices=6):
        old = self.t
        for q in range(1, slices):
            self.service((old + ticks * q // slices) & 0xFFFF)
        self.edge((old + ticks) & 0xFFFF)

    def rev(self, cam_at=None):
        """One crank revolution: real-1 ordinary teeth then the gap.

        cam_at, when given, fires a cam edge on that tooth index of this
        revolution, which is how a cam is placed at a known crank angle
        without the rig needing to know the firmware's angle convention.
        """
        for i in range(self.real - 1):
            self.wait_edge(self.p)
            if cam_at is not None and i == cam_at:
                self.x.call("trg_test_cam_edge", 1)
        self.wait_edge((self.gap + 1) * self.p, 6 * (self.gap + 1))

    def run(self, revs, cam_at=None):
        for _ in range(revs):
            self.rev(cam_at)
        return self

    def u16(self, n):
        return self.x.u16(n)

    def u8(self, n):
        return self.x.u8(n)

    def u32(self, n):
        a = T.sym(n) & 0xFFFF
        return (self.x.m.r16(a) << 16) | self.x.m.r16(a + 2)


def sweep():
    print("-- the same code, five wheels, each described only through the page")
    # (teeth, gap, rpm, tolerated rpm error)
    cases = [(60, 2, 800, 8), (60, 2, 6000, 60), (36, 1, 800, 8),
             (36, 2, 2500, 25), (24, 1, 1200, 12), (12, 1, 600, 12)]
    for teeth, gap, rpm, tol in cases:
        w = Wheel(teeth, gap, rpm).run(5)
        tag = f"{teeth}-{gap} at {rpm} rpm"
        got = w.u16("trg_rpm")
        check(f"{tag}: acquires crank sync", w.u8("trg_state") >= 3,
              f"state={w.u8('trg_state')} rpm={got}")
        check(f"{tag}: rpm within tolerance", abs(got - rpm) <= tol,
              f"got {got}, want {rpm} +/- {tol}")
        # The decoder's own readback of the geometry it resolved.
        check(f"{tag}: publishes the configured wheel",
              w.u16("trg_cfg_teeth") == teeth and w.u16("trg_cfg_gap") == gap,
              f"teeth={w.u16('trg_cfg_teeth')} gap={w.u16('trg_cfg_gap')}")
        check(f"{tag}: one tooth is 360/teeth degrees",
              w.u16("trg_cfg_tooth_x10") == round(3600 / teeth),
              f"toothX10={w.u16('trg_cfg_tooth_x10')}, "
              f"want {round(3600 / teeth)}")
        # Position immediately after the gap is confirmed: tooth one, which is
        # exactly one tooth angle. This is the convention the TDC table and
        # every earlier gate are written against, and it must not drift with
        # the tooth count.
        w.wait_edge(w.p)
        check(f"{tag}: first confirmed tooth is one tooth angle",
              w.u16("trg_engine_deg_x10") % 3600 == round(3600 / teeth),
              f"position={w.u16('trg_engine_deg_x10') / 10:.1f} deg")
        check(f"{tag}: gap ratio is usable on this wheel",
              12 <= w.u16("trg_cfg_ratio_x10") <= (gap + 1) * 10,
              f"ratio={w.u16('trg_cfg_ratio_x10') / 10:.1f}")


def negative_controls():
    print("\n-- negative controls: each must FAIL on a decoder without the fix")

    # 1. THE RATIO GOVERNS THE DECISION, and here is the same signal proving
    #    it both ways with a legal value on each side.
    #
    #    A 36-1's gap is exactly 2.0 tooth periods. Told the wheel has ONE
    #    missing tooth, the decoder holds a ratio below 2.0 and finds it.
    #    Told the SAME signal has TWO, it holds 2.5 - the factory default,
    #    perfectly legal for a two-tooth gap - and 2.0 never exceeds 2.5, so
    #    no candidate is ever raised and no gap is ever counted. Nothing but
    #    the page differs between these two runs.
    w = Wheel(36, 1, 800, cfg_gap=1).run(6)
    check("36-1 read as a 36-1: syncs, on a ratio below 2.0",
          w.u8("trg_state") >= 3 and w.u16("trg_cfg_ratio_x10") < 20
          and abs(w.u16("trg_rpm") - 800) <= 8,
          f"state={w.u8('trg_state')} ratio="
          f"{w.u16('trg_cfg_ratio_x10') / 10:.1f} rpm={w.u16('trg_rpm')}")
    w = Wheel(36, 1, 800, cfg_gap=2, ratio_x10=25).run(6)
    check("the SAME signal read as a 36-2: no gap is ever found",
          w.u8("trg_state") < 3 and w.u16("trg_gaps") == 0
          and w.u16("trg_cfg_ratio_x10") == 25,
          f"state={w.u8('trg_state')} gaps={w.u16('trg_gaps')} "
          f"ratio={w.u16('trg_cfg_ratio_x10') / 10:.1f}")
    # And THAT is what the pre-V55 decoder did to every 36-1: its rule was
    # `(candidate >> 1) > neighbour`, a fixed 2.0, and 2.0 is not more than
    # 2.0. A ratio below 2.0 being in force at all is the thing V54 could not
    # produce.
    #
    # 2. A ratio the wheel cannot use is REPLACED, not obeyed - the decoder
    #    derives one from the geometry rather than sitting deaf. The bound is
    #    strict for the same reason: a ratio of exactly (M+1) can never fire.
    w = Wheel(36, 1, 800, ratio_x10=60).run(6)
    check("an unusable ratio is replaced by one derived from the geometry",
          w.u16("trg_cfg_ratio_x10") == 15 and w.u8("trg_state") >= 3,
          f"ratio={w.u16('trg_cfg_ratio_x10') / 10:.1f} "
          f"state={w.u8('trg_state')}")
    w = Wheel(60, 2, 800, ratio_x10=30).run(6)
    check("a ratio equal to the gap itself is refused, not accepted deaf",
          w.u16("trg_cfg_ratio_x10") == 20 and w.u8("trg_state") >= 3,
          f"ratio={w.u16('trg_cfg_ratio_x10') / 10:.1f} "
          f"state={w.u8('trg_state')}")

    # 2. Right signal, wrong page. The gap is found; the POSITION is not.
    w = Wheel(36, 1, 800, cfg_teeth=60, cfg_gap=2).run(6)
    check("a 36-1 signal decoded as a 60-2 never claims position",
          w.u8("trg_state") < 3,
          f"state={w.u8('trg_state')} loss={w.u16('trg_loss_reason')}")

    # 3. Cam geometry that cannot resolve the cycle must not claim it did.
    #    Four references, the Porsche V8 donor's, 180 degrees apart.
    w = Wheel(60, 2, 800, cam_refs=4, cam_ref_x10=1220, cam_window_x10=300,
              cam_sync_mode=2).run(4, cam_at=18)
    check("four equally spaced cam references do NOT resolve the cycle",
          w.u16("trg_cam_resolves") == 0 and w.u8("trg_state") == 3,
          f"resolves={w.u16('trg_cam_resolves')} state={w.u8('trg_state')}")
    check("the four-reference cam is still WATCHED, not ignored",
          w.u16("trg_cam1_edges") > 0 and (w.u16("trg_cam_error") & 1) == 0,
          f"edges={w.u16('trg_cam1_edges')} err={w.u16('trg_cam_error'):#06x}")

    # 4. One reference does resolve it. The cam is fired on the same tooth of
    #    every revolution, so it lands in ONE half of the cycle - a real
    #    single-window Hall cam turns at half crank speed and does exactly
    #    that. The decoder must find the half that matches and stay there.
    # FOUR revolutions, not two, and that is not padding. The gap is only a
    # CANDIDATE until the following tooth confirms it, so rev 1 ends holding a
    # candidate, rev 2's first tooth confirms it into GAP_SEEN, and rev 3's gap
    # is the first one that can grant SYNC_CRANK. A cam edge offered before
    # that is correctly refused, which is what two revolutions measured.
    w = Wheel(60, 2, 800, cam_refs=1, cam_ref_x10=0, cam_window_x10=1700,
              cam_sync_mode=2).run(4)
    a = w.u16("trg_engine_deg_x10")
    w.x.call("trg_test_cam_edge", 1)
    check("a single cam reference resolves the cycle",
          w.u16("trg_cam_resolves") == 1 and w.u8("trg_state") == 4,
          f"resolves={w.u16('trg_cam_resolves')} state={w.u8('trg_state')} "
          f"at {a / 10:.1f} deg")

    # 5. The 360 degree correction. Put the cam reference where the CURRENT
    #    phase is not, and the decoder must move the phase rather than raise a
    #    fault: that is Bosch's phsok_b acquiring.
    #
    #    The reference is chosen from a FIRST, IDENTICAL run - the decoder is
    #    deterministic, so the second wheel reaches the same angle - because
    #    moving the cam configuration on a synchronised decoder deliberately
    #    resets its position, and a control that resets what it is measuring
    #    measures nothing.
    other = (a + 3600) % 7200
    w2 = Wheel(60, 2, 800, cam_refs=1, cam_ref_x10=other, cam_window_x10=300,
               cam_sync_mode=2).run(4)
    check("the two identical runs really do reach the same angle",
          w2.u16("trg_engine_deg_x10") == a,
          f"{w2.u16('trg_engine_deg_x10')} vs {a}")
    before = w2.u8("trg_phase")
    w2.x.call("trg_test_cam_edge", 1)
    check("a cam edge in the other half CORRECTS the phase, not the health",
          w2.u8("trg_phase") != before and w2.u16("trg_phase_corr") == 1
          and (w2.u16("trg_cam_error") & 1) == 0,
          f"phase {before}->{w2.u8('trg_phase')} "
          f"corr={w2.u16('trg_phase_corr')} "
          f"err={w2.u16('trg_cam_error'):#06x}")

    # 6. A cam edge nowhere near any reference is still a fault.
    w = Wheel(60, 2, 800, cam_refs=1, cam_ref_x10=0, cam_window_x10=50,
              cam_sync_mode=2).run(4)
    while not (900 <= w.u16("trg_engine_deg_x10") % 3600 <= 1100):
        w.wait_edge(w.p)
    w.x.call("trg_test_cam_edge", 1)
    check("an edge outside every window is a named cam fault",
          (w.u16("trg_cam_error") & 1) == 1
          and w.u16("trg_cam_loss_reason") == 6,
          f"err={w.u16('trg_cam_error'):#06x} "
          f"reason={w.u16('trg_cam_loss_reason')}")


    # 7. PHASE LOSS AND UNAIDED RE-ACQUISITION.
    #
    # THIS IS THE SEQUENCE THE PHYSICAL BENCH WILL RUN once the cavity-86
    # driver is repaired, which is what makes that run a confirmation rather
    # than a discovery. Three things have to hold, and the middle one is the
    # one this project got wrong for three releases:
    #
    #   * a resolving cam reaches full cycle sync;
    #   * when the cam STOPS while the crank keeps turning, the CYCLE is given
    #     up and the CRANK is kept. Dropping to 0 would throw away a
    #     360-degree position that was never in doubt and would make a dead
    #     cam stop a running engine; staying at 4 is a lie, and it is what
    #     V55..V63 actually did - measured, ten revolutions after the cam
    #     stopped: state 4, camError 0x0004, and an engine angle nothing had
    #     confirmed since the last edge;
    #   * the cam comes back and the cycle is re-acquired with no help.
    w = Wheel(60, 2, 800, cam_refs=1, cam_ref_x10=0, cam_window_x10=1700,
              cam_sync_mode=2).run(4)
    w.x.call("trg_test_cam_edge", 1)
    check("phase acquired: a single reference reaches full cycle sync",
          w.u8("trg_state") == 4, f"state={w.u8('trg_state')}")

    # The cam stops. The crank does not - six revolutions of clean teeth and
    # not one cam edge: a broken sensor, a broken wire, or the bench BS170.
    w.run(6)
    state, err = w.u8("trg_state"), w.u16("trg_cam_error")
    check("the cam stops and the CYCLE is given up", state < 4,
          f"state={state} camError={err:#06x}")
    check("...but the CRANK is KEPT, not thrown away", state == 3,
          "360-degree position was never in doubt")
    check("...and the decoder names the reason", (err & 4) == 4
          and w.u16("trg_cam_loss_reason") == 7,
          f"camError={err:#06x} reason={w.u16('trg_cam_loss_reason')}")

    # The cam returns. No reconfiguration, no reset, no re-init - just edges.
    w.run(1)
    w.x.call("trg_test_cam_edge", 1)
    check("the cam returns and the cycle is RE-ACQUIRED unaided",
          w.u8("trg_state") == 4, f"state={w.u8('trg_state')}")
    check("...and the live cam fault clears with it",
          (w.u16("trg_cam_error") & 0x0C) == 0,
          f"camError={w.u16('trg_cam_error'):#06x} "
          f"(trg_cam_loss_reason is a LAST-REASON record and stays)")

    # NEGATIVE CONTROL. The demotion must be driven by the MISSING CAM and not
    # by revolutions going by, or an engine whose cam is alive would lose
    # sequential timing on a timer. Same wheel, same number of revolutions,
    # with the cam kept alive.
    w2 = Wheel(60, 2, 800, cam_refs=1, cam_ref_x10=0, cam_window_x10=1700,
               cam_sync_mode=2).run(4)
    w2.x.call("trg_test_cam_edge", 1)
    for _ in range(6):
        w2.run(1)
        w2.x.call("trg_test_cam_edge", 1)
    check("NEGATIVE CONTROL - a LIVE cam holds full sync throughout",
          w2.u8("trg_state") == 4 and (w2.u16("trg_cam_error") & 0x0C) == 0,
          f"state={w2.u8('trg_state')} "
          f"camError={w2.u16('trg_cam_error'):#06x} over 6 revolutions")

def edit_reaches_decoder():
    print("\n-- a configuration edit has to reach the decoder")
    w = Wheel(60, 2, 800).run(3)
    check("the decoder starts on the configured 60-2",
          w.u16("trg_cfg_teeth") == 60 and w.u16("trg_cfg_gap") == 2)
    gen = w.u16("trg_cfg_generation")
    base = T.sym("hc_cfg") & 0xFFFF
    w.x.m.w8(base + T.off("CFG_SY_TEETH"), 0)
    w.x.m.w8(base + T.off("CFG_SY_TEETH") + 1, 36)
    w.x.m.w8(base + T.off("CFG_SY_GAP"), 1)
    w.x.call("trg_test_geometry")
    check("re-reading the page moves the resolved geometry",
          w.u16("trg_cfg_teeth") == 36 and w.u16("trg_cfg_gap") == 1,
          f"teeth={w.u16('trg_cfg_teeth')} gap={w.u16('trg_cfg_gap')}")
    check("and it is COUNTED, so a bench can see that it happened",
          w.u16("trg_cfg_generation") == gen + 1,
          f"generation {gen} -> {w.u16('trg_cfg_generation')}")
    check("the derived tooth angle follows the new wheel",
          w.u16("trg_cfg_tooth_x10") == 100,
          f"toothX10={w.u16('trg_cfg_tooth_x10')}")
    # An identical re-read must NOT count: a generation that ticks on every
    # service call tells a bench nothing.
    w.x.call("trg_test_geometry")
    check("an unchanged page does not count as an edit",
          w.u16("trg_cfg_generation") == gen + 1,
          f"generation={w.u16('trg_cfg_generation')}")


def edge_polarity():
    print("\n-- the capture edge is configuration, and it reaches the SFR")
    w = Wheel(60, 2, 800)
    base = T.sym("hc_cfg") & 0xFFFF
    check("falling is the default and is published as 0",
          w.u16("trg_cfg_crank_edge") == 0)
    w.x.m.w8(base + T.off("CFG_TRIG_EDGE"), 1)
    w.x.call("trg_test_geometry")
    check("selecting rising moves the published capture edge",
          w.u16("trg_cfg_crank_edge") == 1)
    w.x.m.w8(base + T.off("CFG_CAM_EDGE"), 1)
    w.x.call("trg_test_geometry")
    check("the cam edge is independent of the crank edge",
          w.u16("trg_cfg_cam_edge") == 1
          and w.u16("trg_cfg_crank_edge") == 1)


def main():
    print("=== the ME7.1.1 decoder decodes the wheel it is TOLD ===\n")
    sweep()
    negative_controls()
    edit_reaches_decoder()
    edge_polarity()
    print("\nall checks pass" if not FAIL else f"\n{FAIL} failure(s)")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
