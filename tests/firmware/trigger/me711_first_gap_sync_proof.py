#!/usr/bin/env python3
r"""
me711_first_gap_sync_proof.py - crank sync on the FIRST confirmed gap.

    py tests\firmware\trigger\me711_first_gap_sync_proof.py

2026-10-15. Until now the decoder took the position at the SECOND gap, one
revolution after the first (340-430 ms of every AWT start on 2026-10-14).
rusEFI (TriggerDecoderBase: "if this was the first sync point ... we're
synchronized") and Speeduino take the first gap; so does this image, once
trigMinTeeth good teeth have been seen before it. The tooth count is still
checked at every later gap.

The LINKED decoder in c167sim (me711_trigger_test.Engine), a 4-cylinder
crank-only 60-2 at cranking speed (150 rpm), gap ratio 2.5, 6 teeth:

  F1  20 teeth before the gap: CRANK SYNC on the first gap's successor, at
      the right angle, with an rpm (from this revolution's teeth) at once;
  F2  a gap after only 3 teeth (< trigMinTeeth): no sync there - the next
      gap grants it;
  F3  compression ripple (+/-50 % tooth period at two cycles per revolution,
      a 4-cylinder against the starter): no false gap, sync on the first
      real one, kept for three revolutions;
  F4  a noise spike long enough to pass as a gap: it IS taken (the same
      bounded risk rusEFI and Speeduino accept), and the real gap that
      follows withdraws it (EARLY_GAP) and the position is correct one
      revolution later.

CONTROL: the 2026-10-14 car image (5248F4C9) must FAIL F1 - it waited for
the second gap.
"""
from __future__ import annotations

import math
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402

CONTROL = (ROOT.parents[0] / "evidence" / "CAR_20261013_RESETS"
           / "CAR_KIT_20261014_5248F4C9" / "bins" / "hanicore")
FAILS = 0
P150 = round(1_250_000 / 150)          # T1 ticks per tooth at 150 rpm


def check(name, ok, detail=""):
    global FAILS
    print("  [%s] %-62s %s" % ("PASS" if ok else "FAIL", name, detail))
    FAILS += not ok


def engine(min_teeth=6, ratio_x10=25):
    import me711_trigger_test as T
    e = T.Engine.__new__(T.Engine)
    e.x = T.Call()
    T.describe_engine(e.x, cylinders=4, strokes=4, cam_refs=0,
                      tdc=[0, 1800, 3600, 5400])
    base = T.sym("hc_cfg") & 0xFFFF
    e.x.m.w8(base + T.off("CFG_TRIG_GAP_RATIO_X10"), ratio_x10 >> 8)
    e.x.m.w8(base + T.off("CFG_TRIG_GAP_RATIO_X10") + 1, ratio_x10 & 0xFF)
    e.x.m.w8(base + T.off("CFG_TRIG_MIN_TEETH"), min_teeth)
    e.x.call("trg_init")
    e.t = 1000
    e.edge(e.t, service=False)
    return e


def state(e):
    return e.x.u8("trg_state")


def angle(e):
    return e.x.u16("trg_engine_deg_x10") % 3600


def run(e, intervals):
    for d in intervals:
        e.wait_edge(int(d), 4)


def ripple(n, a=0.5, phase=0.3):
    """n tooth periods with the 4-cylinder compression ripple: two speed
    cycles per revolution, one tooth = 6 degrees."""
    return [P150 * (1 + a * math.sin(2 * math.pi * 2 * k / 60 + phase))
            for k in range(n)]


def main() -> int:
    control = "--control-run" in sys.argv
    print("=== first-gap crank sync ===")

    # F1 ------------------------------------------------------------------
    e = engine()
    run(e, [P150] * 20)
    st_before = state(e)
    run(e, [3 * P150, P150])           # the gap and the tooth that confirms it
    e.service()
    rpm = e.x.u16("trg_rpm")
    check("F1 no position before the gap", st_before < 3, "state %d" % st_before)
    check("F1 CRANK SYNC on the first gap (20 teeth seen)", state(e) >= 3,
          "state %d" % state(e))
    check("F1 at the right angle (tooth #1 confirmed = 6.0 deg)",
          state(e) >= 3 and angle(e) == 60, "%.1f deg" % (angle(e) / 10))
    check("F1 an rpm at once (150 +/- 15 %)", 127 <= rpm <= 173, "%d rpm" % rpm)
    run(e, [P150] * 56 + [3 * P150, P150])
    e.service()
    check("F1 the next gap agrees: sync kept, no loss, whole-rev rpm",
          state(e) >= 3 and e.x.u16("trg_synclost") == 0
          and e.x.u16("trg_tooth_corr") == 0
          and abs(e.x.u16("trg_rpm") - 150) <= 3,
          "state %d lost %d corr %d rpm %d" % (
              state(e), e.x.u16("trg_synclost"), e.x.u16("trg_tooth_corr"),
              e.x.u16("trg_rpm")))
    if control:
        return 1 if FAILS else 0

    # F2 ------------------------------------------------------------------
    e = engine()
    run(e, [P150] * 3 + [3 * P150, P150])
    st1 = state(e)
    run(e, [P150] * 56 + [3 * P150, P150])
    check("F2 a gap after 3 teeth (< 6) grants nothing",
          st1 == 2, "state %d" % st1)
    check("F2 the next gap grants it, at the right angle",
          state(e) >= 3 and angle(e) == 60,
          "state %d, %.1f deg" % (state(e), angle(e) / 10))

    # F3 ------------------------------------------------------------------
    e = engine()
    rp = ripple(400)
    run(e, rp[:25])
    st_pre = state(e)
    # per revolution: the gap, the tooth that confirms it, 56 more teeth
    seq = [3 * rp[25], rp[26]] + rp[27:83] + [3 * rp[83], rp[84]] \
        + rp[85:141] + [3 * rp[141], rp[142]] + rp[143:199] \
        + [3 * rp[199], rp[200]]
    run(e, seq[:2])
    st_first = state(e)
    run(e, seq[2:])
    check("F3 +/-50 % compression ripple: no false gap before the real one",
          st_pre < 2, "state %d after 25 rippled teeth" % st_pre)
    check("F3 sync on the first real gap", st_first >= 3, "state %d" % st_first)
    check("F3 kept for three revolutions, no loss, no correction",
          state(e) >= 3 and e.x.u16("trg_synclost") == 0
          and e.x.u16("trg_tooth_corr") == 0 and angle(e) == 60,
          "state %d lost %d %.1f deg" % (state(e), e.x.u16("trg_synclost"),
                                         angle(e) / 10))

    # F4 ------------------------------------------------------------------
    e = engine()
    run(e, [P150] * 10 + [2.8 * P150, P150])      # a spike passes as a gap
    st_false = state(e)
    run(e, [P150] * 17 + [3 * P150, P150])         # the REAL gap
    st_real, why = state(e), e.x.u16("trg_loss_reason")
    run(e, [P150] * 56 + [3 * P150, P150])
    check("F4 a spike that passes the ratio is taken (bounded, as rusEFI)",
          st_false >= 3, "state %d" % st_false)
    check("F4 the real gap withdraws it (EARLY_GAP)",
          st_real < 3 and why == 2, "state %d reason %d" % (st_real, why))
    check("F4 one revolution later the position is right",
          state(e) >= 3 and angle(e) == 60,
          "state %d, %.1f deg" % (state(e), angle(e) / 10))

    # CONTROL -------------------------------------------------------------
    print("\n  --- control: the car image 5248F4C9 (second-gap sync) ---")
    if not (CONTROL / "HaniCore_ME711_v102_dev.bin").exists():
        check("the control image is present", False, str(CONTROL))
    else:
        env = dict(os.environ, HANICORE_ME711_BINS=str(CONTROL))
        r = subprocess.run([sys.executable, __file__, "--control-run"],
                           env=env, capture_output=True, text=True)
        out = r.stdout
        check("CONTROL: the car image FAILS F1 (no sync on the first gap)",
              r.returncode != 0 and "[FAIL] F1 CRANK SYNC on the first gap"
              in out, "rc %d" % r.returncode)
    print("\n%s" % ("FIRST-GAP SYNC PROOF PASSES" if not FAILS
                    else "%d check(s) FAILED" % FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
