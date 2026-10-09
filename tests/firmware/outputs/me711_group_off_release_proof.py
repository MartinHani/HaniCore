#!/usr/bin/env python3
r"""
me711_group_off_release_proof.py - A COIL OR INJECTOR COMMANDED OFF IS
RELEASED, not left driven on a compile-time polarity guess.

    py tests\firmware\outputs\me711_group_off_release_proof.py

THE THIRD PLACE V63's RELEASE REGRESSION LIVES, and the most dangerous one.

V66 repaired `HC_OUT_THR_EN`/`HC_OUT_THR_DIR`. V67 repaired the generic cavity
branch, which serves `CAMSOL1/2`, `FUELPUMP` and `BOOST`. **Neither touched
`hc_hal_out_group()`** - the hot path the angle scheduler drives every coil and
every injector through - and both of its branches end the same way:

```c
/* one slot */            if (hi) { P2 |= mb; } else { P2 &= ~mb; }
                          DP2 |= mb;                 /* <- even when on == 0 */

/* the batch */           if (p2s | p2c) { P2 = (P2 | p2s) & ~p2c;
                                           DP2 |= (p2s | p2c); }
```

`DP2 |= ...` is unconditional, so **a coil or injector turned OFF stays a
DRIVEN OUTPUT** at a level derived from `#define OUT_ACTIVE_HIGH 1u`, a
compile-time constant. the project rules are explicit about why that is not
acceptable:

> *"A resting LEVEL would therefore be a guess, and a wrong guess is an
> injector held open by a parked ECU. A resting DIRECTION is not a guess."*
> *"WHAT IS STILL NOT PROVEN, and must not be claimed: which way round each
> stage is."*

WHY NO EXISTING GATE SEES IT.

* `me711_armed_off_release_proof` drives the real `hc_fuelpump_service()`, and
  the fuel pump goes through the GENERIC branch - the one V67 fixed. It never
  touches the group path.
* `me711_output_safety_test` ends with `DP2=0000 DP7=0000 DP8=0000`, but its
  run finishes with arming WITHDRAWN, and withdrawal calls
  `hc_hal_outputs_safe()`, which sweeps every output back to INPUT. It is
  measuring the safe-state sweep, exactly as §12P/5 describes.

**THE CASE THAT MATTERS IS NOT A COIL BETWEEN SPARKS.** Between two sparks
"off" lasts milliseconds and a driven inactive level is ordinary. The hazard is
`hc_drysched_cancel()` -> `ev_all_off()`, which is what runs when SYNC IS LOST:
it drives every coil and every injector off and, today, leaves all sixteen pins
DRIVEN on a guess, indefinitely, with arming still up. That is §12N/7's
property - *"a lost sync must WITHDRAW pending events"* - undone one layer
below the scheduler.

HOW IT IS MEASURED. The page is armed PART-WAY THROUGH THE RUN, as a tuner
would and as `me711_bench_output_proof` does, because a pre-boot poke is
overwritten by `hc_cfg_init()`. The permissions are then granted directly - the
gate is asking about the HAL, not about the permission layer, which
`me711_safety_test` covers. Then the real compiled `hc_hal_out_group()` is
called ON and OFF and the DIRECTION registers are read either side.

**THE EXPECTED MASK IS NOT ASSUMED.** It is whatever the ON call actually
drove - so a routing change cannot make this gate vacuous, and a call that
drives nothing at all fails the positive control instead of passing the
property.

NOT PHYSICALLY VERIFIED: no coil or injector has been connected to this ECU.
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
GEN_H = SHARED / "generated/hc_config_generated.h"

SENTINEL = 0x0002
HC_OUT_IGN1 = 0
HC_OUT_INJ1 = 8

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


def gen_off(name):
    for f in (GEN_H, SHARED / "config/hcconfig.h"):
        m = re.search(r"#define\s+%s\s+(\d+)u?" % name,
                      f.read_text(errors="replace"))
        if m:
            return int(m.group(1))
    raise SystemExit("%s is in neither config header" % name)


class Rig:
    """Boot, arm the page mid-run, then drive the HAL directly."""

    def __init__(self, img, arm_step=1_400_000, settle=1_100_000):
        self.rig = HB.Rig(img, HB.ENTRY_CURRENT, HB.TICK_CURRENT, echo=False)
        self.cpu = self.rig.cpu
        cfg = sym("hc_cfg") & 0xFFFF

        done = [False]
        orig = S.CPU.step

        def step(s_):
            if not done[0] and s_.steps >= arm_step:
                done[0] = True
                self.rig.mem.w8(cfg + gen_off("CFG_OUTPUTS_ARMED"), 1)
            return orig(s_)

        S.CPU.step = step
        try:
            self.rig.run(arm_step + settle)
        finally:
            S.CPU.step = orig
        self.armed_written = done[0]

    def call(self, addr, args=()):
        cpu = self.cpu
        saved = (cpu.csp, cpu.ip, cpu.m.sfr[0xFE12], cpu.ext)
        cpu.ext = None
        cpu.push(SENTINEL)
        cpu.csp = (addr >> 16) & 0xFF
        cpu.ip = addr & 0xFFFF
        for i, v in enumerate(args):
            cpu.sr(8 + i, v & 0xFFFF)
        for _ in range(400_000):
            if (cpu.ip & 0xFFFF) == SENTINEL:
                break
            cpu.step()
        else:
            raise SystemExit("call to 0x%06X did not return" % addr)
        out = cpu.gr(4) & 0xFFFF
        cpu.csp, cpu.ip, cpu.m.sfr[0xFE12], cpu.ext = saved
        return out

    def dirs(self):
        # DP2 0xFFC2, DP7 0xFFD2, DP8 0xFFD6 - the DIRECTION registers, which
        # is the whole subject. The first version of this read 0xFFD0 and
        # 0xFFD2, which are P7's LATCH and DP7, so it reported the injectors'
        # output LEVEL falling as though it were the direction being released.
        # fuel_test.py carries a note about the same two addresses being
        # confused once before; me711_bench_output_proof has them right.
        return (self.rig.mem.r16(0xFFC2),      # DP2
                self.rig.mem.r16(0xFFD2),      # DP7
                self.rig.mem.r16(0xFFD6))      # DP8

    def route(self):
        """Route every coil and injector to its own cavity, then make the HAL
        notice.

        THE BOARD DEFAULT ROUTES NO COILS AND NO INJECTORS - 12K/5b: it
        "claims no engine at all". So a rig that only arms the page drives
        NOTHING, out_route[] stays OUT_UNROUTED for all sixteen slots, and
        every release check passes vacuously. That is what the first run of
        this gate did, and its positive control is what said so.

        The cavities are this board's own, from 12M/1: ZUE1..ZUE7 on
        102/103/94/95/110/111/8 and EV1..EV8 on 96/97/88/89/112/113/24/19.
        V85: ZUE8 on cavity 7 (P2.7) is routable too - CC7, the serial drain,
        is in compare mode 0, which leaves the pin alone (C167 UM)."""
        ign = (102, 103, 94, 95, 110, 111, 8, 7)     # V85: + ZUE8
        inj = (96, 97, 88, 89, 112, 113, 24, 19)
        # THROUGH hc_cal_set_u8(), NOT BY POKING hc_cfg. The UNIVERSAL block is
        # not simply hc_cfg + offset - a direct write to
        # hc_cfg + CFG_U_PIN_IGN read back as 40 rather than the 102 it was
        # given, while the same idiom works for the CORE byte
        # CFG_OUTPUTS_ARMED. Using the firmware's own accessor removes the
        # question, and it is what me711_armed_off_release_proof already does.
        setter = sym("hc_cal_set_u8")
        for i, cav in enumerate(ign):
            self.call(setter, (gen_off("CFG_U_PIN_IGN") + i, cav))
        for i, cav in enumerate(inj):
            self.call(setter, (gen_off("CFG_U_PIN_INJ") + i, cav))
        # out_armed and out_route[] are both cached against hc_cfg_active_rev,
        # which is how the firmware itself decides when to re-read. Bump it and
        # let hc_hal_outputs_live() refresh the arm cache.
        rev = sym("hc_cfg_active_rev") & 0xFFFF
        self.rig.mem.w16(rev, (self.rig.mem.r16(rev) + 1) & 0xFFFF)
        self.call(sym("hc_hal_outputs_live"))

    def permit(self):
        """Grant the two class permissions and clear the validation word.

        This gate is about the HAL's own release behaviour. Whether the
        permission layer grants correctly is me711_safety_test's subject, and
        duplicating it here would only mean two places to disagree."""
        self.rig.mem.w16(sym("hc_ignition_allowed") & 0xFFFF, 1)
        self.rig.mem.w16(sym("hc_injection_allowed") & 0xFFFF, 1)
        self.rig.mem.w16(sym("hc_cfg_validation") & 0xFFFF, 0)


def drive(r, base, which, on):
    # PERMISSIONS ONLY. Routing is done ONCE when the rig is built - re-running
    # it between the ON and the OFF call puts calibration writes and a
    # re-resolve in the middle of the transition under test, which is not
    # something the firmware ever does and which was measured changing the
    # answer on P7.
    r.permit()
    if on and OWNED_ON:
        # Since the deadline executor, engine ON enters ONLY through
        # hc_hal_deadline_ports() from the CC25 compare interrupt, with the
        # physical mask the routes resolved; hc_hal_out_group() and
        # hc_hal_deadline_out() refuse ON. Drive ON the way CC25 does.
        r.call(sym("hc_hal_out_group"), (base, which, 0))  # resolves routes
        tab = sym("hc_hal_actuator_route") & 0xFFFF
        first = 0 if base == HC_OUT_IGN1 else 8
        physical = 0
        for i in range(8):
            if which >> i & 1:
                physical |= r.rig.mem.r8(tab + first + i)
        r.call(sym("hc_hal_deadline_ports"), (base, which, physical, 1))
    else:
        r.call(sym("hc_hal_out_group"), (base, which, 1 if on else 0))
    return r.dirs()


def owned_on():
    try:
        sym("hc_hal_deadline_ports")
        sym("hc_hal_actuator_route")
        return True
    except SystemExit:
        return False


OWNED_ON = None


def case(label, base, which):
    r = Rig(PI.image())
    check("%s: the page was armed during the run" % label, r.armed_written,
          "CFG_OUTPUTS_ARMED written mid-boot, as a tuner would")
    r.permit()
    r.route()

    before = r.dirs()
    if OWNED_ON:
        r.call(sym("hc_hal_out_group"), (base, which, 1))
        check("%s: the group path REFUSES ON (CC25 owns engine ON)" % label,
              r.dirs() == before, "DP2/DP7/DP8 %04X/%04X/%04X" % r.dirs())
    on = drive(r, base, which, True)
    moved = tuple((a ^ b) for a, b in zip(before, on))
    check("POSITIVE CONTROL: %s ON drives something" % label,
          any(moved),
          "DP2/DP7/DP8 %04X/%04X/%04X -> %04X/%04X/%04X"
          % (before + on))

    off = drive(r, base, which, False)
    still = tuple((m & d) for m, d in zip(moved, off))
    check("%s COMMANDED OFF IS RELEASED" % label, not any(still),
          "of the bits ON drove (%04X/%04X/%04X), still DRIVEN after OFF: "
          "%04X/%04X/%04X" % (moved + still))
    return moved, still


def main() -> int:
    print("=== HaniCore ME7.1.1 - a coil or injector commanded OFF is "
          "RELEASED ===\n")
    print("  image   %s\n" % PI.STEM)
    global OWNED_ON
    OWNED_ON = owned_on()

    print("  --- every coil, through the batch branch ---")
    ign = case("coils", HC_OUT_IGN1, 0x00FF)
    print("\n  --- every injector, through the batch branch ---")
    inj = case("injectors", HC_OUT_INJ1, 0x00FF)
    print("\n  --- ONE coil, through the single-slot branch ---")
    one = case("coil 1", HC_OUT_IGN1, 0x0001)

    # ===================== THE CONTROL ON THE CONTROL =====================
    #
    # All three rows above would be satisfied by a rig whose ON call drove
    # nothing - "no bits driven" trivially implies "no bits still driven".
    # The positive controls inside each case guard that, and this states the
    # same thing once more across the set, so a routing regression that
    # unrouted every class shows up as a FAILURE rather than a green run.
    print()
    check("the rig drove real pins in every case",
          any(ign[0]) and any(inj[0]) and any(one[0]),
          "coils %04X/%04X/%04X, injectors %04X/%04X/%04X, one coil "
          "%04X/%04X/%04X" % (ign[0] + inj[0] + one[0]))

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("GROUP OFF RELEASE FAILS - hc_hal_out_group() leaves a coil or "
              "injector DRIVEN after commanding it off, on a level derived "
              "from the compile-time OUT_ACTIVE_HIGH. This is the same shape "
              "as the V63 regression the release-path fixes repaired in two "
              "other places.")
        return 1
    print("GROUP OFF RELEASE PASSES - the hot path releases what it turns "
          "off, without needing arming to be withdrawn.")
    print("NOT PHYSICALLY VERIFIED: no coil or injector has been connected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
