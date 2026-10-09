#!/usr/bin/env python3
r"""
me711_output_arming_proof.py - NORMAL ENGINE OUTPUTS NEED NO USER ARM, AND A
FALLING PERMISSION NEVER STRANDS A DRIVEN COIL OR INJECTOR.

    py tests\firmware\outputs\me711_output_arming_proof.py

the project rules: normal engine operation must not require a user-facing global
"outputs armed" procedure; bench actuator tests are a separate deliberate
facility. Until V84 every engine output - runtime-scheduled events included -
waited for the page byte CFG_OUTPUTS_ARMED (seeded 0).

Executed against the LINKED IMAGE in c167sim, with CFG_OUTPUTS_ARMED left at
its seeded 0 throughout (it is never written by this gate):

  1. engine stopped (no crank)   -> spark/fuel NOT permitted, and an ON from
                                    the hot path drives nothing;
  2. DBW / pump / relay           -> permitted WITHOUT the crank (a throttle
                                    must hold a start position);
  3. crank sync appears           -> spark/fuel permitted with NO arm, and an
                                    ON actually drives the routed pins;
  4. sync LOST before the OFF     -> the OFF still RELEASES the pins. This is
                                    the order the main loop really uses
                                    (hc_safety_service runs before the
                                    scheduler's hc_drysched_cancel()) and it
                                    is the V84 hot-path fix: until V84 the OFF
                                    was discarded once permission had fallen;
  5. key-off                      -> every class inhibited (bit 0x10 is KEYOFF);
  6. refused page                 -> ON refused even with crank; OFF releases;
  7. bench                        -> an explicit '!T' runs with the page byte at
                                    0 and never reports the retired HCB_R_ARMED.

NEGATIVE CONTROL: the frozen V83 image (HANICORE_ME711_STEM override) must FAIL
checks 3 and 7 - it needs the arm - and check 4 when armed by hand.

NOT PHYSICALLY VERIFIED: no coil or injector has been connected to this ECU.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_image as PI                        # noqa: E402
import me711_group_off_release_proof as G       # noqa: E402

HC_OUT_IGN1 = 0
HC_OUT_INJ1 = 8
KEYOFF_BIT = 0x0010

CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))


class Rig(G.Rig):
    """G.Rig boots the image and WRITES CFG_OUTPUTS_ARMED = 1 mid-run. This
    gate must not arm, so the arm step is pushed past the end of the run."""

    def __init__(self, img, arm_by_hand=False):
        steps = 2_500_000
        # G.Rig runs arm_step + settle steps in total and arms at arm_step;
        # "never arm" is an arm step past the end of a 2.5M-step run.
        arm = 1_400_000 if arm_by_hand else 10**12
        super().__init__(img, arm_step=arm, settle=steps - arm)
        self.cfg = G.sym("hc_cfg") & 0xFFFF

    def u16(self, name):
        return self.rig.mem.r16(G.sym(name) & 0xFFFF)

    def armed_byte(self):
        return self.rig.mem.r8(self.cfg + G.gen_off("CFG_OUTPUTS_ARMED"))

    def safety(self, healthy=1, cal=1, crank=1, cycle=0, key_on=1):
        self.call(G.sym("hc_safety_service"),
                  (healthy, cal, crank, cycle, key_on))
        return {k: self.u16(k) for k in ("hc_dbw_allowed",
                                         "hc_ignition_allowed",
                                         "hc_injection_allowed",
                                         "hc_safety_inhibits")}

    def group(self, base, which, on):
        self.call(G.sym("hc_hal_out_group"), (base, which, 1 if on else 0))
        return self.dirs()


def bench_case(stem):
    """The real '!T' path for injector 1, page byte left at 0, in its own
    process (me711_bench_output_proof explains why)."""
    env = dict(os.environ, HANICORE_ME711_STEM=stem)
    r = subprocess.run([sys.executable,
                        str(ROOT / "tests/firmware/outputs/me711_bench_output_proof.py"),
                        "--case", "0,1,cmdTestInj1,4200000"],
                       capture_output=True, text=True, cwd=str(ROOT), env=env)
    for line in (r.stdout or "").splitlines():
        if line.startswith("CASE-RESULT "):
            return json.loads(line[len("CASE-RESULT "):])
    raise SystemExit("bench case produced no result:\n%s%s"
                     % (r.stdout, r.stderr))


def run(stem, control=False):
    img = PI.BINS / (stem + ".bin")
    print("  image   %s%s\n" % (stem, "   (NEGATIVE CONTROL)" if control else ""))
    res = {}

    r = Rig(img)
    check("the page arm byte is 0 and this gate never writes it",
          r.armed_byte() == 0 and not r.armed_written,
          "CFG_OUTPUTS_ARMED = %d" % r.armed_byte())
    r.route()

    # 1 + 2: engine stopped
    f = r.safety(crank=0)
    before = r.dirs()
    after = r.group(HC_OUT_IGN1, 0x00FF, True)
    after = r.group(HC_OUT_INJ1, 0x00FF, True)
    res[1] = (f["hc_ignition_allowed"] == 0 and f["hc_injection_allowed"] == 0
              and after == before)
    check("1 engine stopped: spark/fuel not permitted, ON drives nothing",
          res[1], "ign=%d inj=%d DP %04X/%04X/%04X -> %04X/%04X/%04X"
          % ((f["hc_ignition_allowed"], f["hc_injection_allowed"])
             + before + after))
    res[2] = f["hc_dbw_allowed"] != 0
    check("2 throttle/pump/relay class permitted WITHOUT the crank", res[2],
          "dbw_allowed=%d inhibits=0x%04X"
          % (f["hc_dbw_allowed"], f["hc_safety_inhibits"]))

    # 3: crank sync, no arm
    f = r.safety(crank=1)
    before = r.dirs()
    on = r.group(HC_OUT_IGN1, 0x00FF, True)
    on = r.group(HC_OUT_INJ1, 0x00FF, True)
    moved = tuple(a ^ b for a, b in zip(before, on))
    res[3] = (f["hc_ignition_allowed"] != 0 and f["hc_injection_allowed"] != 0
              and all(moved[i] for i in range(3)))
    check("3 crank sync, NO arm: spark/fuel permitted and pins DRIVE", res[3],
          "ign=%d inj=%d driven DP2/DP7/DP8 %04X/%04X/%04X"
          % ((f["hc_ignition_allowed"], f["hc_injection_allowed"]) + moved))

    # 4: sync lost FIRST, then the scheduler's OFF
    if control:
        # V83 cannot reach step 3 without the arm, so re-run step 3 armed by
        # hand and ask the step-4 question of it.
        r = Rig(img, arm_by_hand=True)
        r.route()
        r.safety(crank=1)
        before = r.dirs()
        r.group(HC_OUT_IGN1, 0x00FF, True)
        on = r.group(HC_OUT_INJ1, 0x00FF, True)
        moved = tuple(a ^ b for a, b in zip(before, on))
    f = r.safety(crank=0)
    r.group(HC_OUT_IGN1, 0x00FF, False)
    off = r.group(HC_OUT_INJ1, 0x00FF, False)
    still = tuple(m & d for m, d in zip(moved, off))
    res[4] = any(moved) and not any(still)
    check("4 sync LOST before the OFF: every driven pin RELEASED", res[4],
          "driven %04X/%04X/%04X, still driven after OFF %04X/%04X/%04X"
          % (moved + still))

    # 5: key-off
    f = r.safety(crank=1, key_on=0)
    res[5] = (f["hc_dbw_allowed"] == 0 and f["hc_ignition_allowed"] == 0
              and (f["hc_safety_inhibits"] & KEYOFF_BIT) != 0)
    check("5 key-off inhibits every class (bit 0x0010 = KEYOFF)", res[5],
          "inhibits=0x%04X" % f["hc_safety_inhibits"])

    # 6: refused page
    r.safety(crank=1)
    vaddr = G.sym("hc_cfg_validation") & 0xFFFF
    r.group(HC_OUT_IGN1, 0x0001, True)
    on = r.dirs()
    r.rig.mem.w16(vaddr, 0x0010)
    r.group(HC_OUT_IGN1, 0x0001, False)
    off = r.dirs()
    b = r.group(HC_OUT_INJ1, 0x0001, True)
    res[6] = (off[0] & 0x0001) == 0 and b == off
    check("6 refused page: ON refused, OFF still releases", res[6],
          "coil1 DP2 %04X -> OFF %04X; inj ON with refused page moved %s"
          % (on[0], off[0], "nothing" if b == off else "PINS"))
    r.rig.mem.w16(vaddr, 0)

    # 7: bench without the page byte
    bc = bench_case(stem)
    res[7] = (bc["refuse"] & 0x0002) == 0 and bc["pulses"] > 0
    check("7 bench '!T' runs with the page byte at 0", res[7],
          "state=%d refuse=0x%04X pulses=%d"
          % (bc["state"], bc["refuse"], bc["pulses"]))
    return res


def main() -> int:
    global CHECKS, FAILS
    if "--as-control" in sys.argv:
        res = run(PI.STEM, control=True)
        print("CONTROL-RESULT " + json.dumps({str(k): bool(v)
                                               for k, v in res.items()}))
        return 0
    print("=== HaniCore ME7.1.1 - no user arm; OFF always releases ===" + chr(10))
    run(PI.STEM)
    print(chr(10) + "%d/%d checks pass on the image under test" % (CHECKS - FAILS,
                                                           CHECKS))
    ctl = os.environ.get("ARMING_CONTROL_STEM",
                         "HaniCore_ME711_v83_first_start")
    print(chr(10) + "  --- negative control: %s (own process, own map) ---" % ctl)
    r = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                        "--as-control"], capture_output=True, text=True,
                       cwd=str(ROOT),
                       env=dict(os.environ, HANICORE_ME711_STEM=ctl))
    cr = None
    for line in (r.stdout or "").splitlines():
        print("    | " + line)
        if line.startswith("CONTROL-RESULT "):
            cr = json.loads(line[len("CONTROL-RESULT "):])
    check("the negative control ran", cr is not None, (r.stderr or "")[-300:])
    if cr is not None:
        for k in ("3", "4", "7"):
            check("control %s FAILS check %s" % (ctl, k), not cr[k])
    print(chr(10) + "%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("OUTPUT ARMING PROOF FAILS")
        return 1
    print("OUTPUT ARMING PROOF PASSES - no user arm for normal operation, "
          "bench runs on its own command, and a fallen permission releases.")
    print("NOT PHYSICALLY VERIFIED: no coil or injector has been connected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
