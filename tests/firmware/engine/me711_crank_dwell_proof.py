#!/usr/bin/env python3
r"""
me711_crank_dwell_proof.py - the "Cranking dwell" field reaches the coil.

    py tests\firmware\engine\me711_crank_dwell_proof.py

THE DEFECT (V77). crankingDwellMsX100 is a page field at CFG_U_CRANK_DWELL_X100
(2642), seeded to 4.00 ms by hc_config_manager.c and shown to the tuner as
"Cranking dwell". No linked module read it: eng_service() took dwell from the
battery-voltage curve alone, whatever was typed there. rusEFI's semantics are
what the field promises - while cranking, a non-zero value replaces the curve -
and that is what hcengine.c now does.

WHAT THIS RUNS. The linked image's own hc_cfg_init(), eng_init() and
eng_service() in c167sim, with the page value set through hc_cal_set_u16():

  1. stopped (rpm 0 = cranking), value 450   -> eng_dwell_x100 == 450
  2. stopped, value 0                         -> the battery curve's value
  3. running (rpm 3000), value 450            -> the battery curve's value

NEGATIVE CONTROL: the frozen V76 image fails check 1 (its dwell is the curve
whatever the field holds):

    set HANICORE_ME711_STEM=HaniCore_ME711_v76_ekp_polarity

NOT PHYSICALLY VERIFIED. No coil is connected; this is the engine model only.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_config_state_test as T       # noqa: E402  the rig
import me711_image as PI                  # noqa: E402

CRANK_DWELL = 2642                        # CFG_U_CRANK_DWELL_X100
STEPS = 4_000_000
CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += 0 if ok else 1
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))


def run(rpm, value):
    r = T.boot()
    r("eng_init", steps=STEPS)
    r("hc_cal_set_u16", CRANK_DWELL, value)
    r.m.w16(T.sym("trg_rpm") & 0xFFFF, rpm)
    for _ in range(3):                      # hysteresis settles in one pass
        r("eng_service", steps=STEPS)
    return r.g8("eng_cranking"), r.g16("eng_dwell_x100")


def main() -> int:
    print("=== cranking dwell reaches eng_dwell_x100 ===\n  image %s\n" % PI.STEM)
    cr1, d1 = run(0, 450)
    cr2, curve = run(0, 0)
    cr3, d3 = run(3000, 450)
    print("  rpm 0 / 450 -> cranking %d dwell %d;  rpm 0 / 0 -> %d %d;  "
          "rpm 3000 / 450 -> %d %d\n" % (cr1, d1, cr2, curve, cr3, d3))
    check("stopped counts as cranking", cr1 == 1, "eng_cranking=%d" % cr1)
    check("cranking with 4.50 ms configured dwells 4.50 ms", d1 == 450,
          "eng_dwell_x100=%d" % d1)
    # V91 audit: this used to read `d1 != curve or curve == 450`, which a
    # LITERAL zero (curve == 0) also passed. Zero must give the SAME non-zero
    # dwell the running engine gets from the battery curve at this voltage.
    check("zero keeps the battery curve - a real dwell, not 0",
          cr2 == 1 and curve >= 100 and curve == d3,
          "curve=%d running=%d" % (curve, d3))
    check("running ignores the cranking value", cr3 == 0 and d3 == curve,
          "cranking=%d dwell=%d curve=%d" % (cr3, d3, curve))
    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
