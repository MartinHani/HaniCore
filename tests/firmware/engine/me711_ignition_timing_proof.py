#!/usr/bin/env python3
r"""
me711_ignition_timing_proof.py - the advance ceiling and the fixed-timing mode,
executed from the LINKED IMAGE.

    py tests\firmware\engine\me711_ignition_timing_proof.py

TWO THINGS ARE PROVED HERE, AND BOTH ARE ABOUT WHAT A BAD PAGE CAN COMMAND.

1. THE CEILING. CAL_IGN_MAP stores one byte per cell and hcengine.c decodes it
   as (cell - 40) * 0.5 degrees, so the map can carry retard as well as
   advance. THAT ENCODING REACHES 107.5 DEGREES BTDC AT CELL 255, and nothing
   stopped it - not a corrupt record, not an uninitialised page, not a
   mis-scaled import. The .ini's field limits are no defence: they constrain
   what a tuner can TYPE and say nothing about what a byte in the page can
   HOLD, and the page is what the runtime reads.

   So there is a compiled-in ceiling of 60.0 degrees, and this gate drives a
   255 into every cell of the real map and requires the real firmware to
   answer 600, not 1075.

2. FIXED TIMING. rusEFI's timingMode/fixedTiming, ported because it is the same
   problem: a timing light has to see ONE angle, or the measurement says
   nothing about the tooth offset it was meant to check. rusEFI's
   IgnitionState::getAdvance() returns fixedTiming before it looks at cranking
   or at any correction, and so does this - which is the part worth testing,
   because "fixed except while cranking" is a mode that silently lies at
   exactly the speed a timing light is used.

WHY IT CANNOT PASS VACUOUSLY. Every check is run against the FIRMWARE'S OWN
COMPILED CODE through the C167 simulator, with the page written from this test.
A control case proves the dynamic path still reads the map, and the two
mutations at the bottom show that a missing clamp and a missing mode branch
both fail.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
ROOT = Path(__file__).resolve().parents[3]

import me711_image as PI                      # noqa: E402
from me711_hal_test import sym                # noqa: E402
# THE RIG COMES FROM me711_config_state_test, NOT FROM me711_hal_test.
#
# me711_hal_test.Call hardcodes a user stack at 0xF9F0 and allows 60000 steps.
# Both are wrong for this gate: hc_cfg_init() needs far more than 60000, and a
# literal stack address is the defect me711_image.user_stack_top() exists for -
# a harness that writes its own call frames over the configuration page it is
# testing passed 76 of 77 checks while CFG_CYLINDERS read back 251.
from me711_config_state_test import Rig       # noqa: E402

FAILS = 0
GEN_H = ROOT / "firmware/generated/hc_config_generated.h"
CFG_H = ROOT / "firmware/config/hcconfig.h"
ENG_C = ROOT / "firmware/engine/hcengine.c"


def check(name, ok, detail=""):
    global FAILS
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def off(name):
    """A page offset, from the generated header - never a literal."""
    for f in (GEN_H, CFG_H):
        m = re.search(r"#define\s+%s\s+(\d+)u?" % name, f.read_text(errors="replace"))
        if m:
            return int(m.group(1))
    raise SystemExit("no such config offset: %s" % name)


def ceiling_from_source():
    """The clamp the firmware declares, read out of hcengine.c rather than
    typed here - the two-artefacts rule applies to a test as much as to a
    gauge."""
    m = re.search(r"#define\s+IGN_ADV_MAX_X10\s+(\d+)u",
                  ENG_C.read_text(errors="replace"))
    if not m:
        raise SystemExit("hcengine.c declares no IGN_ADV_MAX_X10 - the clamp "
                         "this gate exists for is not in the firmware")
    return int(m.group(1))


class Engine:
    """The engine layer, driven from its own page, in the linked image."""

    def __init__(self):
        self.rig = Rig()
        self.rig.publish_on_service = True     # sensors as accepted samples
        self.rig("hc_hal_init")
        self.rig("hc_cfg_init")
        self.rig("hc_cfg_mgr_init")
        self.rig("eng_init")

    def set8(self, offset, value):
        self.rig("hc_cal_set_u8", offset, value & 0xFF)

    def set16(self, offset, value):
        self.rig("hc_cal_set_u16", offset, value & 0xFFFF)

    def get8(self, offset):
        return self.rig.callb("hc_cal_u8", offset)

    def get16(self, offset):
        return self.rig("hc_cal_u16", offset)

    def fill_ign_map(self, value):
        """THE WHOLE MAP, because hc_cal_map() interpolates and a single cell
        would leave the answer depending on where the axes happen to land."""
        base = off("CAL_IGN_MAP")
        for i in range(256):
            self.set8(base + i, value)

    def set_rpm(self, rpm):
        """THE DECODER'S OWN GLOBAL, written directly.

        eng_service() reads trg_rpm at entry, and the cranking flag has
        hysteresis - it clears only above crankRpmMax + 100 - so the caller
        has to say what the engine is doing before asking what the ignition
        would command. At rpm 0 the answer is always the cranking angle, which
        is correct and is why the first version of this gate 'failed'."""
        self.rig.m.w16(sym("trg_rpm") & 0xFFFF, rpm & 0xFFFF)

    def sensors(self):
        """V98: VALID coolant and intake readings (S5500 window AN0/AN1, as
        me711_alphan_start_proof feeds them). A failed sensor's correction
        is 0 (rusEFI ignition_state.cpp: `if (!clt) return 0`), so the
        correction checks need sensors that read."""
        win = 0x380000 + 0x7100
        base = self.rig.m.r8(sym("hc_s5500_base") & 0xFFFF)
        for ch, raw in ((0, 533), (1, 541)):      # ~80 C, ~13 C
            i = 4 + ch - base
            self.rig.m.w16(win + 2 * i, ((ch & 0xF) << 12) | (raw & 0x3FF))
        self.rig.m.w16(sym("hc_s5500_snaps") & 0xFFFF, 100)

    def advance(self, rpm=None):
        self.sensors()
        if rpm is not None:
            self.set_rpm(rpm)
        # Twice: the first pass clears the cranking flag, the second reads the
        # map with it clear. The hysteresis is deliberate (a bare threshold
        # chatters at exactly the speed a starting engine hovers around).
        # V98: then enough passes for hc_ec_spark's advance-step limiter
        # (+10.0 deg per pass towards advance - the scheduler's cursor walks
        # forward only) to reach any angle in the -30..60 range.
        for _ in range(11):
            self.rig("eng_service", steps=2000000)
        v = self.rig.m.r16(sym("eng_adv_x10") & 0xFFFF)
        return v - 0x10000 if v & 0x8000 else v       # V98: signed

    def cranking(self):
        return self.rig.m.r8(sym("eng_cranking") & 0xFFFF) & 0xFF


def main() -> int:
    global FAILS
    print("=== HaniCore ME7.1.1 - ignition ceiling and fixed timing ===\n")
    print("  image   %s" % PI.image().name)
    print("  sha256  %s\n" % PI.sha256())

    ceiling = ceiling_from_source()
    print("  the firmware's declared ceiling is %d (%.1f deg BTDC)\n"
          % (ceiling, ceiling / 10.0))

    e = Engine()

    # ---------------------------------------------------------------- 1 ----
    # The raw encoding, so the number this gate is about is not assumed.
    worst = (255 - 40) * 5
    check("cell 255 decodes to an absurd angle without a clamp",
          worst == 1075, "(255 - 40) * 5 = %d = %.1f deg BTDC" % (worst, worst / 10.0))
    check("and the ceiling is below it", ceiling < worst,
          "%d < %d" % (ceiling, worst))

    # ---------------------------------------------------------------- 2 ----
    # THE ENGINE HAS TO BE RUNNING FOR THE MAP TO BE READ AT ALL. At rpm 0 the
    # cranking angle wins, which is correct and is checked separately below.
    RUN_RPM = 3000
    e.set8(off("CFG_U_TIMING_MODE"), 0)          # dynamic - read the map
    e.fill_ign_map(255)
    got = e.advance(RUN_RPM)
    check("the engine reads as running at %d rpm" % RUN_RPM,
          e.cranking() == 0, "eng_cranking = %d" % e.cranking())
    check("a map full of 0xFF is clamped, not obeyed", got == ceiling,
          "eng_adv_x10 = %d, wanted %d (the encoding reaches %d)"
          % (got, ceiling, worst))

    # ---------------------------------------------------------------- 3 ----
    # The dynamic path still WORKS - a clamp that clamps everything is not a
    # clamp, it is a constant.
    for cell in (40, 60, 100, 40 + 120, 255):
        e.fill_ign_map(cell)
        got = e.advance(RUN_RPM)
        expect = max(min((cell - 40) * 5, ceiling), -300)
        check("cell %3d still reads the map" % cell, got == expect,
              "eng_adv_x10 = %d, wanted %d" % (got, expect))

    # ---------------------------------------------------------------- 4 ----
    # V98: a cell below the offset is timing AFTER TDC - signed, legal
    # (rusEFI), and never a wrap to 6553.6 degrees.
    e.fill_ign_map(0)
    check("cell 0 = -20.0 deg: after TDC, signed, not wrapped",
          e.advance(RUN_RPM) == -200, "eng_adv_x10 = %d" % e.advance(RUN_RPM))

    # ---------------------------------------------------------------- 5 ----
    # FIXED TIMING. rusEFI returns it before cranking and before corrections.
    e.set8(off("CFG_U_TIMING_MODE"), 1)
    e.fill_ign_map(255)                      # the map says 107.5; ignore it
    for deg_x10 in (0, 50, 100, 250, 355):
        e.set16(off("CFG_U_FIXED_TIMING_X10"), deg_x10)
        got = e.advance(RUN_RPM)
        check("fixed timing commands %5.1f deg" % (deg_x10 / 10.0),
              got == deg_x10, "eng_adv_x10 = %d" % got)

    # ---------------------------------------------------------------- 6 ----
    # And the ceiling still applies to the fixed angle, because a page word is
    # a page word.
    e.set16(off("CFG_U_FIXED_TIMING_X10"), 65535)
    check("a corrupt fixed angle is clamped too",
          e.advance(RUN_RPM) == ceiling, "eng_adv_x10 = %d" % e.advance())

    # ---------------------------------------------------------------- 7 ----
    # THE MODE MUST OUTRANK CRANKING. "Fixed except while cranking" is a mode
    # that lies at exactly the speed a timing light is used at.
    e.set16(off("CFG_U_FIXED_TIMING_X10"), 150)
    e.set16(off("CFG_IGN_ADVANCE_DEG_X10"), 90)   # the cranking angle
    got = e.advance(0)
    check("the engine reads as cranking at rpm 0", e.cranking() == 1,
          "eng_cranking = %d" % e.cranking())
    check("fixed timing outranks the cranking angle", got == 150,
          "eng_adv_x10 = %d; the cranking angle is 90, so the dynamic path "
          "would have used it" % got)

    # ---------------------------------------------------------------- 8 ----
    # Back to dynamic, and the cranking angle returns. This is the control for
    # check 7: it shows the cranking path really was reachable.
    e.set8(off("CFG_U_TIMING_MODE"), 0)
    e.fill_ign_map(40 + 20)                       # 10.0 deg from the map
    got = e.advance(0)
    check("dynamic uses the cranking angle at rpm 0, not the map", got == 90,
          "eng_adv_x10 = %d, and the map says 100" % got)

    # ---------------------------------------------------------------- 8b ---
    # And the cranking angle is clamped too - it is a page word like any other.
    e.set16(off("CFG_IGN_ADVANCE_DEG_X10"), 65535)
    check("a corrupt cranking angle is clamped", e.advance(0) == ceiling,
          "eng_adv_x10 = %d" % e.advance(0))
    e.set16(off("CFG_IGN_ADVANCE_DEG_X10"), 100)

    # ---------------------------------------------------------------- 9 ----
    # The default the firmware seeds must be DYNAMIC. A page that defaulted to
    # fixed would hold one angle at every speed the first time an engine
    # turned.
    fresh = Engine()
    check("a freshly seeded page is in DYNAMIC mode",
          fresh.get8(off("CFG_U_TIMING_MODE")) == 0,
          "%d" % fresh.get8(off("CFG_U_TIMING_MODE")))
    check("and its fixed angle is a sane 10.0 deg",
          fresh.get16(off("CFG_U_FIXED_TIMING_X10")) == 100,
          "%d" % fresh.get16(off("CFG_U_FIXED_TIMING_X10")))

    # ---------------------------------------------------------------- 10 ---
    # V97: THE CLT / IAT TIMING CORRECTIONS (hcigncorr711.c, rusEFI
    # ignitionCltCorr / ignitionIatCorr). Added while RUNNING only - fixed
    # timing is one angle and cranking has its own - and the sum is floored
    # at 0 and still under the ceiling.
    clt_ax, iat_ax = off("CAL_CLT_ENR_AX"), off("CFG_U_IGN_IAT_AX")
    clt_c, iat_c = off("CFG_U_IGN_CLT_CORR"), off("CFG_U_IGN_IAT_CORR")

    def curves(clt, iat):
        for i in range(16):
            e.set16(clt_ax + 2 * i, 9700 + 100 * i)
            e.set16(clt_c + 2 * i, clt[i] if isinstance(clt, list) else clt)
        for i in range(8):
            e.set16(iat_ax + 2 * i, 9800 + 200 * i)
            e.set16(iat_c + 2 * i, iat[i] if isinstance(iat, list) else iat)

    def s16(v):
        return v - 0x10000 if v & 0x8000 else v

    def corr(clt_dc, iat_dc):
        return s16(e.rig("hc_ign_corr_x10", clt_dc, iat_dc))

    e.set8(off("CFG_U_TIMING_MODE"), 0)
    e.set16(off("CFG_IGN_ADVANCE_DEG_X10"), 100)
    e.fill_ign_map(40 + 20)                       # 10.0 deg from the map
    curves(0, 0)
    got = e.advance(RUN_RPM)
    check("corrections 0: the map angle unchanged (control)", got == 100,
          "eng_adv_x10 = %d" % got)
    curves(-50, 20)                               # -5.0 CLT, +2.0 IAT
    got = e.advance(RUN_RPM)
    pub = s16(e.rig.m.r16(sym("eng_ign_corr_x10") & 0xFFFF))
    check("running: 10.0 - 5.0 (CLT) + 2.0 (IAT) = 7.0 deg", got == 70,
          "eng_adv_x10 = %d, eng_ign_corr_x10 = %d" % (got, pub))
    check("the correction is published (eng_ign_corr_x10 -> OCH 1006)",
          pub == -30, "%d" % pub)
    got = e.advance(0)
    check("cranking: the correction is NOT applied (cranking angle 10.0)",
          e.cranking() == 1 and got == 100, "eng_adv_x10 = %d" % got)
    e.set8(off("CFG_U_TIMING_MODE"), 1)
    e.set16(off("CFG_U_FIXED_TIMING_X10"), 150)
    got = e.advance(RUN_RPM)
    check("fixed timing: the correction is NOT applied", got == 150,
          "eng_adv_x10 = %d" % got)
    e.set8(off("CFG_U_TIMING_MODE"), 0)
    curves(-300, -300)
    got = e.advance(RUN_RPM)
    # V98: timing is SIGNED (after TDC is legal, rusEFI) and bounded at
    # -30.0 deg: 10 - 30 - 30 = -50 -> -30.0, never a wrap to 6553
    check("a retard past TDC is signed (ATDC) and bounded at -30.0 deg",
          got == -300, "eng_adv_x10 = %d" % got)
    e.fill_ign_map(40 + 2 * 60)                   # 60.0 deg = the ceiling
    curves(300, 300)
    got = e.advance(RUN_RPM)
    check("an advance past the ceiling is clamped", got == ceiling,
          "eng_adv_x10 = %d" % got)
    curves([10 * i for i in range(16)], [-10 * i for i in range(8)])
    check("CLT interpolates (15 C = half-way 40..50 = 45; IAT at its first "
          "point, 0)", corr(10150, 9800) == 45, "%d" % corr(10150, 9800))
    check("IAT interpolates DOWNWARD (5 C = half-way -1.0..-2.0 = -1.5)",
          corr(9700, 10100) == -15, "%d" % corr(9700, 10100))
    check("beyond the axes: the end values (150 + -70 = 80; 0 + 0)",
          corr(12000, 12000) == 80 and corr(0, 0) == 0,
          "%d / %d" % (corr(12000, 12000), corr(0, 0)))
    curves(1000, 0)                               # a page the model refuses
    check("a term is bounded to +30.0 deg whatever the page holds",
          corr(10500, 10500) == 300, "%d" % corr(10500, 10500))
    curves(0, -1000)
    check("... and to -30.0 deg", corr(10500, 10500) == -300,
          "%d" % corr(10500, 10500))
    curves(0, 0)

    print("\n%s" % ("IGNITION TIMING PROOF PASSES - no page, however corrupt, "
                    "can command more\nthan %.1f degrees, and fixed timing is "
                    "one angle at every speed.\nNOT PHYSICALLY VERIFIED: no "
                    "timing light has been on this engine."
                    % (ceiling / 10.0)
                    if not FAILS else
                    "IGNITION TIMING PROOF FAILS - %d check(s)." % FAILS))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
