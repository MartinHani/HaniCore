#!/usr/bin/env python3
r"""
me711_armed_off_release_proof.py - an output commanded OFF while its class is
still ARMED must be RELEASED, not left driven.

    py tests\firmware\outputs\me711_armed_off_release_proof.py

THE TRANSITION NOTHING ELSE TESTS.

`me711_dbw_enable_release_proof` covers the throttle bridge after a bounded
BENCH command. This covers the other half, and it is the one that happens in
normal running: **the RUNTIME turning an output off while arming stays up.**

A fuel pump ending its bounded prime, a cam solenoid released mid-run, boost
backing off - none of those withdraw arming, so none of them reach
`hc_hal_outputs_safe()`, which is the only routine in the image that returns a
pin to high impedance.

WHY THAT MATTERS, in the HAL's own words (the comment above
`hc_hal_outputs_safe()`):

    "A resting LEVEL would therefore be a guess, and a wrong guess is an
     injector held open by a parked ECU. A resting DIRECTION is not a guess."
    "WHAT IS STILL NOT PROVEN, and must not be claimed: which way round each
     stage is."

`hc_hal_out(sem, 0)` on the cold path ends with `port_set_dir(port, bitno, 1u)`
- driven, on a level derived from `#define OUT_ACTIVE_HIGH 1u`, a compile-time
constant. **If any of those stages is actually active-low, "off" drives it ON.**

WHY `me711_fuel_pump_proof` DOES NOT ALREADY COVER THIS. It asserts "the pin is
an INPUT again at the end" and passes - but its run ENDS with arming withdrawn,
and withdrawal calls `hc_hal_outputs_safe()`, which sweeps every output back to
INPUT. It is measuring the safe-state sweep, not the pump's own off path. This
gate keeps arming UP across the off transition so the sweep cannot mask it.

HOW IT DRIVES THE FIRMWARE. The page is armed PART-WAY THROUGH THE RUN, exactly
as a tuner would and exactly as `me711_bench_output_proof` does - poking it
before boot is overwritten by `hc_cfg_init()`. Then the REAL compiled
`hc_fuelpump_service()` is called in the linked image through its own argument
registers, the same way `me711_fuel_pump_proof` does it.

MEASURED ACROSS FIVE IMAGES, AND IT CORRECTED THE FIRST CLAIM MADE ABOUT IT.
This gate was written believing the defect predated V63 and was separate from
the throttle regression. IT IS NOT. It is THE SAME V63 REGRESSION IN A SECOND
PLACE - V63 moved output driving into the HAL, and the HAL's OFF path leaves
pins driven:

    V62  AE8F2F96   DP2 = 0x0000   RELEASED   <- the property held here
    V63  6C8A6F5B   DP2 = 0x1800   bits 11 AND 12 stuck
    V64  E87BE233   DP2 = 0x1800
    V65  872F0F8C   DP2 = 0x1800
    V66  B84200FE   DP2 = 0x1000   bit 11 freed by the V66 throttle fix;
                                   bit 12, the generic path, remains

Bit 11 is EGENFR, bit 12 is EKP. V66 repaired the first and left the second,
which is why this gate is RED on the current image and why its red is precise
rather than general. Re-measure with HANICORE_ME711_STEM if that is ever in
doubt; the run is about two minutes per image.

IT IS COMMITTED RED ON PURPOSE, to the same standard near_ram_hazard_proof and
me711_stack_proof are held to: an honest red that names a real property beats a
green suite that never asks the question.
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
TGT_H = ROOT / "firmware/targets/me711/hctarget.h"

SENTINEL = 0x0002
TRG_NO_SIGNAL = 0

CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print("  [%s] %-52s %s" % ("PASS" if ok else "FAIL", name, detail))


def sym(name):
    m = re.search(r"^\s*([0-9A-F]{6})H\s+%s\b" % re.escape(name),
                  PI.MAP.read_text(errors="replace"), re.M)
    if not m:
        raise SystemExit("%s is not in the map" % name)
    return int(m.group(1), 16)


def gen_off(name):
    """Page offsets live in TWO headers - the generated universal block and
    hcconfig.h's hand-written core - and CFG_OUTPUTS_ARMED is in the second.
    Same two-file lookup me711_bench_output_proof.cfg_off() does."""
    for f in (GEN_H, SHARED / "config/hcconfig.h"):
        m = re.search(r"#define\s+%s\s+(\d+)u?" % name,
                      f.read_text(errors="replace"))
        if m:
            return int(m.group(1))
    raise SystemExit("%s is in neither hc_config_generated.h nor hcconfig.h"
                     % name)


def tgt_int(name):
    m = re.search(r"#define\s+%s\s+(\d+)" % name,
                  TGT_H.read_text(errors="replace"))
    if not m:
        raise SystemExit("%s is not in hctarget.h" % name)
    return int(m.group(1))


class Rig:
    """Boot, arm the page mid-run, then drive the real fuel-pump service."""

    def __init__(self, img, arm_step=1_400_000, settle=1_100_000):
        self.rig = HB.Rig(img, HB.ENTRY_CURRENT, HB.TICK_CURRENT, echo=False)
        self.cpu = self.rig.cpu
        cfg = sym("hc_cfg") & 0xFFFF

        # ARMED PART-WAY THROUGH, not before boot: hc_cfg_init() would
        # overwrite a pre-boot poke. Same idiom as me711_bench_output_proof.
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

    def dp2(self):
        return self.rig.mem.r16(0xFFC2)

    def pump(self, ms, ign, rpm):
        self.call(sym("hc_fuelpump_service"),
                  (ms, ign, rpm, TRG_NO_SIGNAL, 0))
        return self.call(sym("hc_fuelpump_command")) & 0xFF


def main() -> int:
    ekp = tgt_int("TGT_EKP_PORT_BIT")
    mask = 1 << ekp

    print("=== HaniCore ME7.1.1 - an armed output that is commanded OFF is "
          "RELEASED ===\n")
    print("  image   %s" % PI.IMG.name)
    print("  EKP     P2.%d, DP2 mask 0x%04X\n" % (ekp, mask))

    r = Rig(PI.image())
    check("the page was armed during the run", r.armed_written,
          "CFG_OUTPUTS_ARMED written mid-boot, as a tuner would")

    r.call(sym("hc_fuelpump_init"))
    r.call(sym("hc_cal_set_u8"), (gen_off("CFG_U_FUEL_PUMP_MODE"), 1))  # AUTO

    # ---- key on: the bounded prime commands the pump ON -----------------
    cmd_on = r.pump(1000, 1, 0)
    dp_on = r.dp2()
    check("POSITIVE CONTROL: key on commands the pump", cmd_on == 1,
          "hc_fuelpump_command() = %d" % cmd_on)
    check("...and the pin is DRIVEN while it is on",
          (dp_on & mask) != 0,
          "DP2 = 0x%04X, bit %d set" % (dp_on, ekp))

    # ---- the prime expires. ARMING IS NOT WITHDRAWN. --------------------
    #
    # Advance well past any bounded prime with the key still on and no engine.
    # Nothing here touches CFG_OUTPUTS_ARMED, so hc_hal_outputs_safe() is
    # never called and cannot mask the result.
    cmd_off = 1
    for ms in range(2000, 40000, 1000):
        cmd_off = r.pump(ms, 1, 0)
        if cmd_off == 0:
            break
    dp_off = r.dp2()

    check("the prime ends on its own and the pump is commanded OFF",
          cmd_off == 0, "hc_fuelpump_command() = %d" % cmd_off)

    # ================= THE PROPERTY THIS GATE EXISTS FOR =================
    check("AN OUTPUT COMMANDED OFF WHILE ARMED IS RELEASED",
          (dp_off & mask) == 0,
          "DP2 = 0x%04X, bit %d %s - high-Z is the only resting state that is "
          "not a guess about an unmeasured stage"
          % (dp_off, ekp, "CLEAR" if (dp_off & mask) == 0 else "STILL SET"))

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("ARMED-OFF RELEASE FAILS - an output turned off by the RUNTIME "
              "is left driven on a compile-time polarity guess. See "
              "bench measurements")
        return 1
    print("ARMED-OFF RELEASE PASSES - the runtime releases what it turns off, "
          "without needing arming to be withdrawn.")
    print("NOT PHYSICALLY VERIFIED: no fuel pump has been connected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
