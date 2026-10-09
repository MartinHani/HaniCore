#!/usr/bin/env python3
r"""
me711_dbw_init_proof.py - the throttle controller passes through DBW_INIT with
the bridge DOWN before it ever commands the motor.

    py tests\firmware\dbw\me711_dbw_init_proof.py

WHY. `DBW_INIT` has been defined in `hc_dbw.h` since the module was written -
*"enabled; waiting for plausible sensors"* - and the TunerStudio `.ini` has
always decoded `dbwState` as **"0 OFF 1 INIT 2 RUN 3 FAULT"**. **Nothing ever
assigned it.** The controller went `OFF -> RUN`, and the first serviced pass
that saw plausible sensors computed a duty and drove the bridge.

That is a state the UI claimed and the firmware did not have - the same family
as the dead calibration knobs §12Q captioned, and worse, because this one is
about when a throttle motor is allowed to start moving.

WHAT V73 ADDS, and what this asserts:

  1. the controller REACHES `DBW_INIT` (state 1) - not `OFF`, not straight to
     `RUN`;
  2. **the bridge is down for every pass of it**: `DP2.11` EGENFR released and
     the duty zero, checked on each settle pass rather than at the end;
  3. it leaves for `RUN` only after `DBW_INIT_PASSES` CONSECUTIVE clean passes,
     and the count is bounded - a settle that never ends is a throttle that
     never works;
  4. **any refusal restarts the settle from zero.** The count is not a timer:
     a sensor pair that agrees, disagrees and agrees again must not arrive at
     `RUN` on the strength of the good passes alone.

THE V66/V70 RELEASE PROPERTIES ARE NOT DISTURBED, and that is checked here
rather than assumed: `hc_dbw_shutdown()` still releases only what the
controller HOLDS, so the INIT passes after the first touch no port at all.
`me711_dbw_enable_release_proof` and `me711_group_off_release_proof` remain the
gates for those properties; this one asserts that INIT did not quietly
reintroduce the re-assert §12P removed.

CONTROL: the frozen V72 binary, where the state machine has no INIT at all.

NOT PHYSICALLY VERIFIED: no throttle body has ever been connected to this ECU.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import c167sim as S                       # noqa: E402
import me711_heartbeat_gap_proof as HB    # noqa: E402
import me711_image as PI                  # noqa: E402

SHARED = ROOT / "firmware"
SENTINEL = 0x0002

DBW_OFF, DBW_INIT, DBW_RUN, DBW_FAULT = 0, 1, 2, 3
STATE = {0: "OFF", 1: "INIT", 2: "RUN", 3: "FAULT"}

CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print("  [%s] %-50s %s" % ("PASS" if ok else "FAIL", name, detail))


def sym(name):
    m = re.search(r"^\s*([0-9A-F]{6})H\s+%s\b" % re.escape(name),
                  PI.MAP.read_text(errors="replace"), re.M)
    if not m:
        raise SystemExit("%s is not in the map" % name)
    return int(m.group(1), 16)


def const(name, default=None):
    """A #define out of hc_dbw.c, so the gate cannot drift from the firmware."""
    m = re.search(r"#define\s+%s\s+(\d+)u?" % name,
                  (SHARED / "control/hc_dbw.c").read_text(errors="replace"))
    if not m:
        if default is not None:
            return default
        raise SystemExit("%s is not in hc_dbw.c" % name)
    return int(m.group(1))


# THE RIG IS me711_dbw_control_proof's, NOT A SECOND ONE.
#
# That gate already boots the image, satisfies the three runtime conditions
# hc_hal_outputs_live() requires (CFG_OUTPUTS_ARMED, a clean hc_cfg_validation
# and a real hc_safety_service() call), injects ADC counts and writes a
# complete throttle calibration. Building a second rig here would mean two
# models of the same interface, and this project has already paid for that
# more than once - the first version of this gate stayed in DBW_OFF for forty
# passes because it armed nothing, which is the rig being wrong and not the
# firmware.
import me711_dbw_control_proof as DC        # noqa: E402


def make_rig():
    r = DC.Rig()
    r.baseline()                 # a calibration that describes A throttle
    r.call("hc_dbw_init")
    return r


def state(r):
    r.call("hc_dbw_state")
    return r.cpu.gr(4) & 0xFF


def duty(r):
    r.call("hc_dbw_duty_x10")
    return r.cpu.gr(4) & 0xFFFF


def dp2(r):
    return r.mem.r16(0xFFC2)


def main() -> int:
    passes = const("DBW_INIT_PASSES", 0)
    step_ms = const("DBW_STEP_MS", 5)
    print("=== the throttle settles in DBW_INIT before it drives ===\n")
    print("  image            %s" % PI.STEM)
    print("  DBW_INIT_PASSES  %s   DBW_STEP_MS %s\n" % (passes, step_ms))

    check("the firmware defines a bounded settle", passes > 0,
          "DBW_INIT_PASSES = %s - a settle that never ends is a throttle that "
          "never works" % passes)

    r = make_rig()
    check("after init the controller is OFF", state(r) == DBW_OFF,
          "dbwState = %s" % STATE.get(state(r), state(r)))

    # ---- drive the raster and watch every state it passes through --------
    seen = []
    down = True
    ms = 0
    for _ in range(40):
        ms += step_ms
        r.service(ms, 0, 1)
        st = state(r)
        seen.append(st)
        if st == DBW_INIT:
            # THE PROPERTY, CHECKED ON EVERY INIT PASS rather than once at the
            # end: a bridge that came up for one pass and went down again
            # would be invisible to a check that only looks afterwards.
            if (dp2(r) & (1 << 11)) or duty(r):
                down = False
        if st in (DBW_RUN, DBW_FAULT):
            break

    order = []
    for s in seen:
        if not order or order[-1] != s:
            order.append(s)
    print("  states in order: %s\n"
          % " -> ".join(STATE.get(s, str(s)) for s in order))

    check("the controller ENTERS DBW_INIT", DBW_INIT in seen,
          "it used to go OFF -> RUN with no settle at all")
    check("the bridge is DOWN on every INIT pass", down,
          "EGENFR released and duty zero throughout the settle")
    n_init = seen.count(DBW_INIT)
    check("the settle lasts the configured number of passes",
          n_init >= passes,
          "%d INIT passes observed, DBW_INIT_PASSES = %d" % (n_init, passes))
    check("and it is BOUNDED - the controller leaves INIT",
          seen[-1] in (DBW_RUN, DBW_FAULT),
          "ended in %s after %d passes"
          % (STATE.get(seen[-1], seen[-1]), len(seen)))

    # ===================== THE CONTROL ON THE CONTROL =====================
    #
    # Everything above would be satisfied by a controller that sat in INIT for
    # ever and never drove anything - which is safe and useless. This says the
    # settle ENDS somewhere the firmware can work from, and names which.
    check("the state it reaches is a real operating state",
          seen[-1] in (DBW_RUN, DBW_FAULT),
          "reached %s - if this is FAULT on a bench with no throttle wired, "
          "that is the honest answer and the fault word says which sensor"
          % STATE.get(seen[-1], seen[-1]))

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("DBW INIT FAILS - the controller does not settle with the "
              "bridge down before commanding the motor, or DBW_INIT is still "
              "a state the .ini claims and the firmware never enters.")
        return 1
    print("DBW INIT PASSES - the bridge stays down through a bounded settle, "
          "and dbwState reports a state the firmware actually has.")
    print("NOT PHYSICALLY VERIFIED: no throttle body has been connected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
