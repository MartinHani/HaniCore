#!/usr/bin/env python3
r"""
ts_ini_dead_knob_proof.py - a settable control that nothing reads must say so.

    py tests\tunerstudio\ts_ini_dead_knob_proof.py

WHY. `dbwRevlimRpm` is a real `[Constants]` entry at a real page offset with a
real dialog field labelled **"DBW taper start"**, range 0..20000 rpm. A tuner
can set it to 6500, Burn it, and **nothing anywhere will taper** - no linked
module reads `CAL_DBW_REVLIM_RANGE` or `CAL_DBW_REVLIM_RPM`. The same was true
of `dbwLimpX10`, which is worse: a limp-home position is exactly the number
somebody trusts in a failure.

the project rules settle the principle for presets and it applies here unchanged:

    "an incomplete preset with a named gap is correct; a complete one built on
     invented numbers is how somebody ends up tuning against a fiction."

**A dead knob is allowed. A SILENT dead knob is not.** The repository already
had the right pattern - the autocal panel says its values are "stored,
validated and ready for the automatic sequence once the nudge has a physical
result" - and three other knobs simply never got the sentence.

WHAT THIS GATE ASSERTS

  1. the set of DBW calibration slots that NO linked module reads is exactly
     the set this file records as known-dead;
  2. every one of those has a **NOT IMPLEMENTED** caption in the panel that
     exposes it, or is in the explicitly-captioned autocal group.

So it fires in BOTH directions, which is the point:

  * a NEW dead knob appears        -> unknown slot, FAIL, caption it
  * a dead knob gets IMPLEMENTED   -> it leaves the set, FAIL, DELETE the
                                      caption so the UI stops lying the other
                                      way

WHAT IT DELIBERATELY DOES NOT DO: decide whether a knob should be implemented
or removed. That is a product decision. This only refuses to let the UI and the
firmware disagree in silence.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths as HCP  # noqa: E402

SHARED = ROOT / "firmware"
TGT = ROOT / "firmware/targets/me711"
UX = ROOT / "tools/tunerstudio/gen_ts_ux_me711.py"
# The GENERATED file as well as the generator: a field could be emitted
# from somewhere else entirely and the generator would look clean.
INI = ROOT / "tunerstudio/hanicore_me711.ini"
GEN_H = SHARED / "generated/hc_config_generated.h"

# The modules the ME7.1.1 image LINKS. hcconfig.c is excluded on purpose: it is
# the page DEFINITION, so every slot appears there and counting it would make
# every knob look alive. That exclusion is the whole trick of this gate.
LINKED = sorted(
    [p for p in HCP.portable_sources("*.c")
     if p.stem in {"hc_dbw", "hcengine", "hc_validation", "hc_airfuel",
                   "hc_plan", "hcfuelpump", "hcmainrelay", "hc_config_manager",
                   "hc_route", "hc_presets", "hc_pin_descriptor"}]
    + HCP.target_sources("*.c"))

# Known-dead, each with the caption that must exist while it stays dead.
# Known-dead slot -> the TunerStudio knob name that must NOT be a field.
KNOWN_DEAD = {
    # V93: CAL_DBW_TUNE_AMP left this set - hcetbcal.c / hc_dbw_gains() read
    # it as the autotune relay amplitude.
    # V98: CAL_DBW_REVLIM_RPM / _RANGE (the ETB rev limit) and
    # CAL_DBW_LIMP_X10 (the failed-TPS fuel opening, hcengine.c) left it -
    # hcengctl711.c / hc_dbw.c read them.
}

CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print("  [%s] %-54s %s" % ("PASS" if ok else "FAIL", name, detail))


def main() -> int:
    print("=== HaniCore ME7.1.1 - no SILENT dead knobs ===\n")

    slots = sorted(set(re.findall(r"CAL_DBW_[A-Z0-9_]+",
                                  GEN_H.read_text(errors="replace"))))
    check("the DBW calibration slots were found", len(slots) >= 10,
          "%d slots in hc_config_generated.h" % len(slots))

    bodies = {p.name: p.read_text(errors="replace") for p in LINKED}
    check("the linked modules were found", len(bodies) >= 10,
          "%d modules, hcconfig.c deliberately excluded" % len(bodies))

    dead = []
    for s in slots:
        if not any(s in b for b in bodies.values()):
            dead.append(s)

    print("\n  slots no linked module reads: %s\n"
          % (", ".join(dead) if dead else "none"))

    check("the dead set is exactly what is recorded",
          set(dead) == set(KNOWN_DEAD),
          "unexpected: %s | no longer dead: %s"
          % (sorted(set(dead) - set(KNOWN_DEAD)) or "-",
             sorted(set(KNOWN_DEAD) - set(dead)) or "-"))

    # ================= NOT EXPOSED AT ALL, NOT MERELY CAPTIONED =========
    #
    # V67 captioned these six "NOT IMPLEMENTED" and left them settable, on the
    # argument that a named gap is honest. IT IS NOT ENOUGH. A caption is read
    # once; a field is used. `dbwRevlimRpm` was a real control labelled "DBW
    # taper start", range 0..20000 rpm, that a tuner could set to 6500 and
    # Burn with nothing anywhere tapering - and `dbwLimpX10` was worse,
    # because a limp-home position is exactly the number somebody trusts in a
    # failure.
    #
    # So the property is now the stronger one: **a calibration slot no linked
    # module reads MUST NOT BE A SETTABLE FIELD.** The panels say in words
    # that the feature does not exist, and the page bytes stay reserved, so
    # THE LAYOUT DOES NOT MOVE and no .ini regenerated for this signature is
    # invalidated.
    #
    # It still fires in both directions: implement one and its `field =` comes
    # back, and this gate then requires it to leave the dead set.
    ux = UX.read_text(errors="replace")
    ini = INI.read_text(errors="replace") if INI.exists() else ""
    for slot in sorted(set(dead) & set(KNOWN_DEAD)):
        knob = KNOWN_DEAD[slot]
        in_ux = ('F("%s"' % knob) in ux
        in_ini = bool(re.search(r"^\s*field\s*=.*\b%s\b" % re.escape(knob),
                                ini, re.M))
        check("%s is NOT a settable field" % slot,
              not in_ux and not in_ini,
              "%s: generator field=%s, .ini field=%s"
              % (knob, in_ux, in_ini))

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("DEAD KNOB PROOF FAILS - the UI and the firmware disagree in "
              "silence. Either caption the knob or implement it; do not leave "
              "a settable control that does nothing and says nothing.")
        return 1
    print("DEAD KNOB PROOF PASSES - every DBW knob nothing reads says so where "
          "a tuner will see it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
