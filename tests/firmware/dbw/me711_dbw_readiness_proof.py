#!/usr/bin/env python3
r"""me711_dbw_readiness_proof.py - DBW does not judge a sensor it has not heard.

    py tests\firmware\dbw\me711_dbw_readiness_proof.py [--control]
        [--groups startup,order,loss,asic,warm]

Each group starts with a fresh rig; groups can run in separate processes
against one HANICORE_ME711_BINS image/map/manifest snapshot.

Runtime audit 2026-10-06, finding P1-5: the S5500 link
came up before the ADC round robin had sampled the pedal and both throttle
tracks, hc_dbw found "no fresh source" 33 ms into boot and latched DBW_F_STALE
until a key cycle - with dbwEnable a limp fuel cut above 1500 rpm on a healthy
car. hc_dbw.c now holds DBW_INIT, bridge off, for up to DBW_READY_MS (1000 ms)
after an init or a key-on fault clear until every track has been fresh and
paired; after that, staleness latches as before.

The linked image runs in c167sim (tools/analysis/me711_runtime_stress.py: AWT
page with dbwEnable 1, throttle plant, pedal 25 %):

  R1 cold boot: RUN, no fault bit, no key cycle needed
  R2 main ADC silent for the first 400 ms after power-on: no latch, RUN, clean
  R3 main ADC silent for 1.6 s: DBW_F_STALE latches once the window has
     ended (not before), the bridge enable (EGENFR, DP2.11) is never driven
  R4 a key cycle (KL15, P6.2) with the ADC back clears R3: RUN, clean
  R5 throttle tracks that disagree from power-on: DBW_F_TPS_PAIR (the real
     fault, not hidden as staleness), the bridge never enabled
  R6 throttle before pedal: both pedal tracks unsampled for the first 400 ms
     (their conversions refused by tag) - no latch, RUN, clean
  R7 pedal before throttle: both throttle tracks unsampled for 400 ms - same
  R8 the pedal disappears while running: DBW_F_STALE and the bridge enable
     released within 150 ms (fresh window 100 ms + round robin + one step)
  R9 the throttle tracks disappear while running: the same
  R10 late S5500 (no valid frame for the first 600 ms): no sensor fault,
     RUN, the bridge never enabled before the link is up
  R11 one TPS channel missing from power-on: no enable, bounded STALE
  R12 warm restart with retained RAM and stale DBW fault/readiness state:
      startup reinitialises it, bridge off until all new samples qualify

--control: R2 with the ADC silent for 1.5 s (past the window) must fail R2.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402

import me711_runtime_stress as R    # noqa: E402
import me711_image as PI            # noqa: E402

DBW_ST, DBW_FLT = 0x387300, 0x387302      # hc_dbw D.st / D.flt (SRAM)
F_STALE, F_TPS_PAIR = 0x0080, 0x0004
DP2, P6 = 0xFFC2, 0xFFCC
NEVER = 10 ** 15
_AWT_PAGE = None


def rig(tps2_bad=False):
    global _AWT_PAGE
    if _AWT_PAGE is None:
        _AWT_PAGE = R.build_awt_page()
    s = R.Stress(_AWT_PAGE, ts=False)
    s.dbw_plant = True
    s.pedal = 0.25
    if tps2_bad:
        base = s.adc_value

        def adc(ch):
            v = base(ch)
            return 500 if ch == 3 else v       # TPS2 parked mid-span: no pairing
        s.adc_value = adc
    s.t1_last = s.mem.r16(R.T1)
    return s


def warm_restart(previous):
    """Reset CPU/SFRs while retaining all modelled writable RAM.

    The startup code runs again; DBW SRAM is deliberately not zeroed by the
    fixture, so the linked init must invalidate the previous readiness state.
    """
    s = rig()
    for region in ("xram", "iram", "lram"):
        getattr(s.mem, region)[:] = getattr(previous.mem, region)
    return s


def run(s, ms, hold_adc=False):
    """ms of engine-stopped time in 1 ms chunks; returns (first ms the STALE bit
    was seen or None, EGENFR driven at any sample)."""
    first, drove = None, False
    for i in range(ms):
        if hold_adc:
            s.adc_t0 = NEVER                     # the conversion never completes
        elif s.adc_t0 == NEVER:
            s.adc_t0 = None
        s.run_us(1000)
        if first is None and s.mem.r16(DBW_FLT) & F_STALE:
            first = i
        drove |= bool(s.mem.sfr.get(DP2, 0) & 0x0800)
    return first, drove


def run_mute(s, ms, chans):
    s.adc_mute = set(chans)
    r = run(s, ms)
    s.adc_mute = set()
    return r


def loss(s, chans, ms=300):
    """Mute `chans` on a running DBW: ms to STALE and to the bridge enable
    released (DP2.11 back to input), or None."""
    s.adc_mute = set(chans)
    t_st = t_rel = None
    for i in range(ms):
        s.run_us(1000)
        if t_st is None and s.mem.r16(DBW_FLT) & F_STALE:
            t_st = i + 1
        if t_rel is None and not (s.mem.sfr.get(DP2, 0) & 0x0800):
            t_rel = i + 1
    s.adc_mute = set()
    return t_st, t_rel


def st(s):
    return s.mem.r8(DBW_ST), s.mem.r16(DBW_FLT)


class Checks(list):
    def append(self, item):
        super().append(item)
        name, ok = item
        print("  [%s] %s" % ("PASS" if ok else "FAIL", name), flush=True)


def main():
    control = "--control" in sys.argv
    groups = (set(sys.argv[sys.argv.index("--groups") + 1].split(","))
              if "--groups" in sys.argv else {"startup", "order", "loss", "asic", "warm"})
    unknown = groups - {"startup", "order", "loss", "asic", "warm"}
    if unknown:
        raise SystemExit("unknown DBW groups: %s" % sorted(unknown))
    if control:
        groups = {"startup"}
    res = Checks()
    print("image %s\nsha256 %s" % (PI.image().name, PI.sha256()), flush=True)
    if not control and "startup" in groups:
        s = rig()
        run(s, 1200)
        a, f = st(s)
        res.append(("R1 cold boot: state %d (2 = RUN), faults 0x%04X" % (a, f), a == 2 and f == 0))

    if "startup" in groups:
        s = rig()
        hold = 1500 if control else 400
        t_st, drove_early = run(s, hold, hold_adc=True)
        t2, _ = run(s, 1200 - hold if not control else 600)
        a, f = st(s)
        res.append(("R2 ADC silent %d ms after power-on: STALE %s, state %d, faults 0x%04X"
                    % (hold, "never" if t_st is None and t2 is None else "latched", a, f),
                    t_st is None and t2 is None and a == 2 and f == 0 and not drove_early))
        if control:
            ok = res[-1][1]
            if ok:
                print("CONTROL BROKEN: an ADC silent past the window does not fail R2")
                return 1
            print("CONTROL OK: R2 fails when the ADC stays silent past the window")
            return 0

        s = rig()
        t_st, drove = run(s, 1600, hold_adc=True)
        a, f = st(s)
        res.append(("R3 ADC silent 1.6 s: STALE latched at %s ms (window 1000 ms), EGENFR driven: %s"
                    % (t_st, drove), t_st is not None and t_st >= 900 and a == 3
                    and (f & F_STALE) and not drove))
        s.mem.sfr[P6] = s.mem.sfr.get(P6, 0) & ~0x0004
        run(s, 30)
        s.mem.sfr[P6] = s.mem.sfr.get(P6, 0) | 0x0004
        run(s, 600)
        a, f = st(s)
        res.append(("R4 key cycle with the ADC back: state %d, faults 0x%04X" % (a, f), a == 2 and f == 0))

    if "order" in groups:
        s = rig(tps2_bad=True)
        _, drove = run(s, 1500)
        a, f = st(s)
        res.append(("R5 throttle tracks disagree: state %d, faults 0x%04X (TPS_PAIR %s, STALE %s), EGENFR driven: %s"
                    % (a, f, bool(f & F_TPS_PAIR), bool(f & F_STALE), drove),
                    a == 3 and bool(f & F_TPS_PAIR) and not (f & F_STALE) and not drove))

        for name, chans in (("R6 throttle before pedal", (8, 9)), ("R7 pedal before throttle", (1, 3))):
            s = rig()
            t_a, drove_early = run_mute(s, 400, chans)
            t_b, _ = run(s, 800)
            a, f = st(s)
            res.append(("%s (400 ms): STALE %s, state %d, faults 0x%04X"
                        % (name, "never" if t_a is None and t_b is None else "latched", a, f),
                        t_a is None and t_b is None and a == 2 and f == 0 and not drove_early))

    if "loss" in groups:
        for name, chans in (("R8 pedal lost while running", (8, 9)), ("R9 throttle lost while running", (1, 3))):
            s = rig()
            run(s, 1200)
            a0, _ = st(s)
            drove0 = bool(s.mem.sfr.get(DP2, 0) & 0x0800)
            t_st, t_rel = loss(s, chans)
            a, f = st(s)
            res.append(("%s: was state %d, bridge %s; STALE after %s ms, bridge released after %s ms, faults 0x%04X"
                        % (name, a0, "on" if drove0 else "off", t_st, t_rel, f),
                        a0 == 2 and drove0 and a == 3 and bool(f & F_STALE)
                        and t_st is not None and t_st <= 150
                        and t_rel is not None and t_rel <= 150))

    if "asic" in groups:
        s = rig()
        s.rig.asic_mute = True
        _, drove_early = run(s, 600)
        # A zero frame has a valid zero checksum. Check the actual injected
        # startup frame before interpreting link-readiness evidence.
        frame = [s.mem.r16(R.HB.FRAMEA + 2 * i) for i in range(R.HB.WORDS_START)]
        invalid = (sum(frame[:-1]) & 0xFFFF) != frame[-1]
        s.rig.asic_mute = False
        t_b, _ = run(s, 900)
        a, f = st(s)
        res.append(("R10 S5500 silent 600 ms after power-on: bridge before the link %s, state %d, faults 0x%04X"
                    % ("DRIVEN" if drove_early else "off", a, f),
                    invalid and not drove_early and a == 2 and f == 0))

    if "warm" in groups:
        s = rig()
        t_st, drove = run_mute(s, 1600, (3,))
        a, f = st(s)
        res.append(("R11 TPS2 never arrives: STALE after %s ms, bridge %s, faults 0x%04X"
                    % (t_st, "DRIVEN" if drove else "off", f),
                    t_st is not None and t_st >= 900 and a == 3 and bool(f & F_STALE) and not drove))

        # Carry the faulted controller and all old sensor samples across reset.
        s = warm_restart(s)
        t_st, drove_early = run_mute(s, 400, (1, 3))
        t_b, _ = run(s, 800)
        a, f = st(s)
        res.append(("R12 warm reset with retained fault/sample RAM: bridge before new TPS %s, state %d, faults 0x%04X"
                    % ("DRIVEN" if drove_early else "off", a, f),
                    t_st is None and t_b is None and not drove_early and a == 2 and f == 0))

    nf = sum(not ok for _n, ok in res)
    print("%d/%d checks pass" % (len(res) - nf, len(res)))
    return 1 if nf else 0


if __name__ == "__main__":
    sys.exit(main())
