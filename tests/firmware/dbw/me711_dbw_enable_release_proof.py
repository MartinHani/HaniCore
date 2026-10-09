#!/usr/bin/env python3
r"""
me711_dbw_enable_release_proof.py - a completed bounded bench command leaves
the throttle bridge RELEASED, and four real images prove the check can tell.

    py tests\firmware\dbw\me711_dbw_enable_release_proof.py

THE PROPERTY, and it is the one 12M/1 wrote down:

    After a bounded bench throttle command completes, EGENFR (P2.11) and both
    bridge legs (P7.2 DVE1, P7.7 DVE2) are back to HIGH IMPEDANCE - direction
    bit CLEAR - unless an explicitly armed closed-loop DBW mode owns them.

A direction bit is the only honest resting state here, because the ACTIVE
POLARITY OF THE S8100 IS INFERRED AND UNMEASURED. A driven level is a guess
about a part whose truth table is not in this repository; a released pin is
not a guess about anything.

WHY THIS EXISTS AS A GATE OF ITS OWN. The property was true on V62 and false
from V63 to V65, and `me711_dbw_bench_proof` went red for it across three
releases without anyone reading the red. It is asserted here on its own, in one
short gate, against every image that has ever held it or broken it - so the
next time it breaks, the failure names the property instead of arriving inside
thirty-three other failures.

THE REGRESSION IT CATCHES, both halves of it:

  1. `hc_hal_out(HC_OUT_THR_EN, 0)` - the call whose entire job is to DISABLE
     the bridge - set the direction to OUTPUT unconditionally, so "off" left
     the pin DRIVEN rather than released;
  2. `hc_dbw_service()` called `hc_dbw_shutdown()` on every main-loop pass
     while unarmed, so even a correct bench teardown was overwritten by the
     next pass of a controller that owned nothing.

THE NEGATIVE CONTROLS ARE REAL FROZEN IMAGES, NOT MUTATIONS. V63, V64 and V65
must FAIL this check and V62 must PASS it. A gate that only ever sees the fixed
image cannot tell you it is measuring the fix rather than measuring nothing -
and this project has shipped six gates that were green against the wrong image.

NOT PHYSICALLY VERIFIED: no throttle motor has been connected to this ECU. What
is asserted here is the state of three direction bits in a simulator, which is
the strongest claim available until a bridge is on the bench.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

BOP = ROOT / "tests/firmware/outputs/me711_bench_output_proof.py"
TGT = ROOT / "firmware/targets/me711/hctarget.h"
BINS = ROOT / "bins/hanicore"

# The image under test, and every image that has ever held or broken the
# property. `expect` is whether the bridge must come back RELEASED.
IMAGES = [
    ("V62 real routing", "HaniCore_ME711_v62_real_routing", True,
     "flashed and physically qualified. NOT the image in the ECU: a 1 MiB bootmode readback on 2026-09-18 matched V63 byte for byte"),
    ("V63 engine backend", "HaniCore_ME711_v63_engine_backend", False,
     "the release that broke it: the port write moved into the HAL"),
    ("V64 hot path", "HaniCore_ME711_v64_hot_path", False, "frozen"),
    ("V65 code space", "HaniCore_ME711_v65_code_space", False,
     "superseded, never flashed"),
    ("V66 dbw release", "HaniCore_ME711_v66_dbw_release", True,
     "repaired the THROTTLE half of V63's release regression"),
    ("V67 output release", "HaniCore_ME711_v67_output_release", True,
     "repaired the generic half too"),
    ("V68 tooth window", "HaniCore_ME711_v68_tooth_window", True,
     "the scheduler's angle-to-time fix"),
    ("V69 seed burst", "HaniCore_ME711_v69_seed_burst", True,
     "the seeding transient removed"),
    ("V70 group release", "HaniCore_ME711_v70_group_release", True,
     "the THIRD place V63's regression lived - hc_hal_out_group() - repaired"),
    ("V74 bench candidate", "HaniCore_ME711_v74_bench_candidate", True,
     "THE CANDIDATE INTENDED TO REPLACE V63 IN THE ECU. V63 is what is "
     "physically in there, and it is one of the rows above that must FAIL - "
     "so this gate spans exactly the regression the flash exists to remove"),
]

CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print("  [%s] %-50s %s" % ("PASS" if ok else "FAIL", name, detail))


def bit(name):
    m = re.search(r"#define\s+%s\s+(\d+)" % name,
                  TGT.read_text(errors="replace"))
    if not m:
        raise SystemExit("%s missing from hctarget.h" % name)
    return int(m.group(1))


def nudge(stem):
    """Run a bounded DBW bench command on `stem` to completion and return the
    port DIRECTION registers afterwards.

    Driven through me711_bench_output_proof's own --case entry so the rig, the
    command bytes (taken from the .ini) and the run length are identical to the
    gate that first caught this - one rig, not two models of it."""
    env = dict(os.environ)
    env["HANICORE_ME711_STEM"] = stem
    r = subprocess.run(
        [sys.executable, str(BOP), "--case", "1,1,cmdTestDbwA,4200000"],
        capture_output=True, text=True, cwd=str(ROOT), env=env)
    for line in (r.stdout or "").splitlines():
        if line.startswith("CASE-RESULT "):
            return json.loads(line[len("CASE-RESULT "):])
    raise SystemExit("no result for %s:\n%s%s" % (stem, r.stdout, r.stderr))


def main() -> int:
    en = 1 << bit("TGT_DBW_EN_PORT_BIT")
    legs = (1 << bit("TGT_DBW_PWM_PORT_BIT")) | (1 << bit("TGT_DBW_DIR_PORT_BIT"))

    print("=== HaniCore ME7.1.1 - the bench releases the throttle bridge ===\n")
    print("  EGENFR  P2.%d   mask DP2 0x%04X" % (bit("TGT_DBW_EN_PORT_BIT"), en))
    print("  legs    P7.%d/P7.%d  mask DP7 0x%04X\n"
          % (bit("TGT_DBW_PWM_PORT_BIT"), bit("TGT_DBW_DIR_PORT_BIT"), legs))

    missing = [s for _, s, _, _ in IMAGES if not (BINS / (s + ".bin")).exists()]
    if missing:
        print("  cannot run - these images are absent: %s" % ", ".join(missing))
        return 2

    held, broke = [], []
    for label, stem, expect, why in IMAGES:
        r = nudge(stem)
        dp2, dp7, _dp8 = r["dp"]
        released = (dp2 & en) == 0 and (dp7 & legs) == 0
        detail = ("DP2=0x%04X DP7=0x%04X  %s"
                  % (dp2, dp7, "RELEASED" if released else "STILL DRIVEN"))
        check("%-18s must %s" % (label,
                                 "RELEASE" if expect else "still be BROKEN"),
              released == expect, detail + "  (%s)" % why)
        (held if released else broke).append(label)

    # ===================== THE CONTROL ON THE CONTROL =====================
    #
    # Everything above could be satisfied by a check that always returns the
    # same answer. These two say the measurement DISCRIMINATES: at least one
    # real image holds the property and at least one real image does not, and
    # both sets were produced by the same rig, the same command bytes and the
    # same run length.
    check("the check SEES the property held", bool(held),
          "released on: %s" % ", ".join(held))
    check("...and SEES it broken, on frozen images", bool(broke),
          "still driven on: %s" % ", ".join(broke))

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("DBW ENABLE RELEASE FAILS - either a bounded bench command is "
              "leaving the bridge driven, or this gate has stopped being able "
              "to tell. Both are stop conditions.")
        return 1
    print("DBW ENABLE RELEASE PASSES - the bridge comes back high-impedance "
          "after a bounded bench command, and three frozen images prove the "
          "check can tell when it does not.")
    print("NOT PHYSICALLY VERIFIED: no throttle motor has been connected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
