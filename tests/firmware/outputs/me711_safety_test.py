#!/usr/bin/env python3
"""Execute the central permission layer and prove it grants and denies correctly.

WHAT THIS GATE USED TO SAY, AND WHY IT CHANGED.

Until V63 it asserted one thing: that HANICORE_BENCH_SAFE was absolute, so
"all five prerequisites healthy" still denied every output. That was true and
worth pinning while the board had no output back end at all - but it meant the
only case the gate could ever exercise was the deny-everything case. It could
not tell a permission layer that works from one that returns 0 unconditionally.

V63 built the back end, withdrew the compile-time veto, and split the inhibits
per class. So the gate now tests what it could not before:

  * that all five prerequisites together actually GRANT;
  * that each prerequisite, removed ON ITS OWN, denies the right classes -
    which is the negative control the old version had no room for;
  * that the class split is real, because a throttle is a POSITION and must
    be allowed to hold one before the crank is synchronised, while a coil is
    an ANGLE and must not fire until it is.

The last one is the V63 behaviour change and it is the reason a throttle can
now help start an engine instead of waiting for the engine to start first.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
from me711_trigger_test import Call

NAMES = ("hc_outputs_allowed", "hc_dbw_allowed",
         "hc_ignition_allowed", "hc_injection_allowed")

CHECKS = 0
FAILS = 0


def ck(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print("  [%s] %-56s %s" % ("PASS" if ok else "FAIL", name, detail))


def flags(c):
    return {n: c.u16(n) for n in NAMES}


def service(c, healthy=1, cal=1, crank=1, cycle=1, arm=1):
    c.call("hc_safety_service", healthy, cal, crank, cycle, arm)
    return flags(c), c.u16("hc_safety_inhibits")


def main():
    c = Call()
    c.call("hc_safety_init")
    f = flags(c)
    ck("init denies every output subsystem", all(v == 0 for v in f.values()),
       str(f))

    # ------------------------------------------------- the positive case
    f, mask = service(c)
    ck("all five prerequisites together GRANT every class",
       all(v != 0 for v in f.values()), "inhibits=0x%04X" % mask)
    ck("...and no inhibit is left standing", mask == 0, "0x%04X" % mask)
    ck("the BENCH_SAFE veto is withdrawn, and deliberately so",
       (mask & 0x0001) == 0,
       "bit 0 clear - the back end exists, so the compile-time veto is off")

    # --------------------------------------- each prerequisite, on its own
    for label, kw, want_dbw, want_angle in (
            ("ASIC unhealthy", {"healthy": 0}, 0, 0),
            ("calibration bad", {"cal": 0}, 0, 0),
            ("not explicitly armed", {"arm": 0}, 0, 0),
            ("no crank sync", {"crank": 0}, 1, 0),
            ("no 720 cycle", {"cycle": 0}, 1, 1)):
        f, mask = service(c, **kw)
        ok = ((f["hc_dbw_allowed"] != 0) == bool(want_dbw)
              and (f["hc_ignition_allowed"] != 0) == bool(want_angle)
              and (f["hc_injection_allowed"] != 0) == bool(want_angle))
        ck("%-22s -> dbw=%d spark/fuel=%d" % (label, want_dbw, want_angle), ok,
           "dbw=%d ign=%d inj=%d inhibits=0x%04X"
           % (f["hc_dbw_allowed"] != 0, f["hc_ignition_allowed"] != 0,
              f["hc_injection_allowed"] != 0, mask))

    # THE CLASS SPLIT IS THE POINT, so assert it as its own claim rather than
    # leaving it implied by the table above.
    f, _ = service(c, crank=0)
    ck("a throttle may hold a position with the engine STOPPED",
       f["hc_dbw_allowed"] != 0 and f["hc_ignition_allowed"] == 0,
       "this is what lets DBW help START an engine")

    # The umbrella answer stays strict: it is what a bench and the .ini read.
    f, _ = service(c, cycle=0)
    ck("the umbrella hc_outputs_allowed stays STRICT",
       f["hc_outputs_allowed"] == 0,
       "every inhibit must be clear for the umbrella, cycle included")

    # ------------------------------------------------------ all reasons named
    f, mask = service(c, 0, 0, 0, 0, 0)
    ck("nothing is allowed when nothing is satisfied",
       all(v == 0 for v in f.values()), str(f))
    ck("every failed prerequisite is named", (mask & 0x3E) == 0x3E,
       "mask=0x%04X - NO_CYCLE|ASIC|CAL|NOT_ARMED|NO_CRANK" % mask)

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        return 1
    print("SAFETY PROOF PASSES - the permission layer grants only on all "
          "prerequisites, denies on each one alone, and separates a position "
          "from an angle.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
