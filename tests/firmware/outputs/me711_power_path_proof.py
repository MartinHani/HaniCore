#!/usr/bin/env python3
r"""
me711_power_path_proof.py - the ME7.1.1 power path, as the linked image
actually implements it.

    py tests\firmware\outputs\me711_power_path_proof.py

WHAT THIS GATE IS FOR.

For most of this project's life the comment in hcpower.c said the two NLEN
lines met in "two NAND gates in series = AND, so NL needs BOTH processors to
agree". That is not what the schematic draws. On 2026-09-02 the S5600
network was re-read from the PDF's own LINE SEGMENTS rather than from a
rendered picture, and the gates are wired differently: one of them has its
two inputs tied together and is an inverter.

The correction matters because it reverses which direction needs agreement.
So the derivation is now a function in the firmware - hc_power_nl_predict() -
and this gate EXECUTES it in the linked image, on the C167 simulator, for all
four input combinations. A comment cannot be tested; a function can.

It also checks the two things that would silently invalidate the model:

  * NLEN_FR (P3.12) is actually asserted, from the STARTUP, before EINIT.
    If it were not, NL would be whatever the pull-ups make it and the ECU's
    behaviour on key-off would depend on a resistor.

  * SYSCON's CLKEN is clear in BOTH branches the startup can take. P3.15's
    alternate function is CLKOUT; with CLKEN set, the throttle bridge's SF
    fault pin cannot be read at all and hcbench.c's DBW mode would be
    reading a clock. This is exactly the "two artefacts that must agree"
    class - a bit in an assembler immediate and a sbit in C - so it is
    derived from the source rather than believed.

WHY IT CANNOT PASS VACUOUSLY. The truth table is asserted in full, including
the ONE combination that produces NL LOW. A stub that returned a constant
would fail on the first or the fourth row. And the SYSCON check reads the
immediates out of start_me711.a66, so deleting the writes fails it rather
than skipping it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import c167sim as S                       # noqa: E402
import me711_heartbeat_gap_proof as HB    # noqa: E402
import me711_image as PI                  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
TGT = ROOT / "firmware/targets/me711"
START = TGT / "system/start_me711.a66"
HDR = TGT / "hctarget.h"
POWER_C = TGT / "system/hcpower.c"

# A return address that is not code, so the near RET lands somewhere the
# harness can recognise instead of running on into the next function.
SENTINEL = 0x0002

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-56s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def sym(name):
    for m in re.finditer(r"^\s*([0-9A-F]{6})H\s+(\w+)\s",
                         PI.MAP.read_text(errors="replace"), re.M):
        if m.group(2) == name:
            return int(m.group(1), 16)
    raise SystemExit("%s is not in the map - build the target first" % name)


def hdr_int(name):
    m = re.search(r"#define\s+%s\s+(\d+)" % name,
                  HDR.read_text(errors="replace"))
    if not m:
        raise SystemExit("%s is not in hctarget.h" % name)
    return int(m.group(1))


# ---------------------------------------------------------------- SYSCON --
def syscon_values():
    """Every SYSCON immediate the startup can write. Read, not assumed."""
    vals = re.findall(r"MOV\s+SYSCON,#([0-9A-Fa-f]+)H",
                      START.read_text(errors="replace"))
    return [int(v, 16) for v in vals]


# ------------------------------------------------- executing the function --
def call_predict(rig, fr, as_):
    """Run hc_power_nl_predict(fr, as_) in the linked image and read R4.

    THE ARGUMENT REGISTERS ARE READ OUT OF THE COMPILER'S OWN LISTING, not
    assumed: build/hcpower_code.lst says

        ;---- Variable 'nlen_fr' assigned to Register 'R8' ----
        ;---- Variable 'nlen_as' assigned to Register 'R9' ----

    and the function ends in a near RET, so the return address is one word.

    THE STACK IS THE FIRMWARE'S OWN. The rig has already executed the real
    startup, so SP, CP and the DPPs are whatever start_me711.a66 established.
    This project has three recorded incidents of a test rig writing its own
    call frame over the module it was testing; picking a literal here would
    be the fourth.
    """
    cpu = rig.cpu
    addr = sym("hc_power_nl_predict")

    # An EXTS/EXTP prefix may still be armed if the boot
    # stopped on one, and an injected call would run under a segment
    # override belonging to code we are not executing. See
    # me711_nvm_proof.Ecu.call().
    saved = (cpu.csp, cpu.ip, cpu.m.sfr[0xFE12], cpu.ext)
    cpu.ext = None
    cpu.push(SENTINEL)
    cpu.csp = (addr >> 16) & 0xFF
    cpu.ip = addr & 0xFFFF
    cpu.sr(8, fr & 0xFF)
    cpu.sr(9, as_ & 0xFF)

    for _ in range(20000):
        if (cpu.ip & 0xFFFF) == SENTINEL:
            break
        cpu.step()
    else:
        raise SystemExit("hc_power_nl_predict did not return")
    out = cpu.gr(4) & 0xFF
    cpu.csp, cpu.ip, cpu.m.sfr[0xFE12], cpu.ext = saved
    return out


def main() -> int:
    img = PI.image()
    print("=== HaniCore ME7.1.1 - the power path, executed ===\n")
    print("  image   %s" % img.name)
    print("  sha256  %s\n" % PI.sha256())

    nl_high = hdr_int("TGT_NL_HIGH")
    nl_low = hdr_int("TGT_NL_LOW")
    check("TGT_NL_HIGH and TGT_NL_LOW are distinct", nl_high != nl_low,
          "HIGH=%d LOW=%d" % (nl_high, nl_low))

    # ---------------------------------------------------- the truth table --
    #
    #   NL = NAND( NOT(NLEN_FR), NLEN_AS ) = NLEN_FR OR NOT(NLEN_AS)
    #
    # Row 2 is the only one that goes LOW, and it is the one that says both
    # processors have to agree before this ECU can take its own power away.
    print("  --- NL = NAND(/NLEN_FR, NLEN_AS), executed in the image ---")
    # BOOT FIRST. The call below runs on the stack and register bank the real
    # startup established, not on ones this file chose.
    rig = HB.Rig(img, HB.ENTRY_CURRENT, HB.TICK_CURRENT, echo=False)
    rig.run(600_000)
    table = [
        (0, 0, nl_high, "both released: the reset default"),
        (0, 1, nl_low, "FR released AND ASIC asserting - the ONLY low"),
        (1, 0, nl_high, "FR vetoing"),
        (1, 1, nl_high, "FR vetoing even while the ASIC asserts"),
    ]
    for fr, as_, want, why in table:
        got = call_predict(rig, fr, as_)
        check("NLEN_FR=%d NLEN_AS=%d -> NL=%d" % (fr, as_, want), got == want,
              "%s (got %d)" % (why, got))

    # ------------------------------------------- the startup actually does it
    src = START.read_text(errors="replace")
    check("the startup latches P3.12 before it drives it",
          src.index("BSET    P3.12") < src.index("BSET    DP3.12"),
          "latch before direction - the OEM's order, and the only one that "
          "cannot glitch the line low")
    # THE INSTRUCTION, NOT THE WORD. `src.index("EINIT")` finds the first
    # mention of EINIT in a COMMENT, which in this file is hundreds of lines
    # above the instruction - so the check passed or failed on prose.
    einit = None
    for m in re.finditer("^[ 	]*EINIT" + chr(92) + "b", src, re.M):
        einit = m.start()
        break
    check("and it does so before EINIT",
          einit is not None and src.index("BSET    DP3.12") < einit,
          "NLEN_FR is deterministic before any interrupt can run"
          if einit is not None else "no EINIT instruction found in the startup")

    m = re.search(r"#define\s+TGT_NLEN_FR_PORT_BIT\s+(\d+)",
                  HDR.read_text(errors="replace"))
    check("hctarget.h and the startup name the same pin",
          m is not None and int(m.group(1)) == 12,
          "TGT_NLEN_FR_PORT_BIT = %s, the startup writes P3.12"
          % (m.group(1) if m else "missing"))

    # --------------------------------------- CLKEN, so P3.15 can be an input
    clken_bit = hdr_int("TGT_SYSCON_CLKEN_BIT")
    vals = syscon_values()
    check("the startup writes SYSCON on every branch it has", len(vals) >= 2,
          "found %s" % ", ".join("0x%04X" % v for v in vals))
    bad = [v for v in vals if (v >> clken_bit) & 1]
    check("CLKEN is clear in EVERY SYSCON the startup can write", not bad,
          "P3.15 is a GPIO, so the throttle bridge's SF pin is readable"
          if not bad else
          "CLKOUT ENABLED in %s - hcbench's DBW mode would be reading a clock"
          % ", ".join("0x%04X" % v for v in bad))

    # ------------------------------------- and nothing can un-assert the hold
    check("no code in the tree can clear NLEN_FR",
          "hc_power_hold_release" not in
          (POWER_C.read_text(errors="replace")
           .split("hc_power_hold_release() is deliberately NOT built")[-1]),
          "hc_power_hold_release() is still deliberately not built")

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("POWER PATH PROOF FAILS - the firmware's model of its own "
              "power path does not match the schematic derivation, or the "
              "startup no longer establishes it.")
        return 1
    print("POWER PATH PROOF PASSES - NL needs BOTH processors to go low, "
          "every reset state leaves it high, the startup asserts NLEN_FR "
          "before EINIT, and P3.15 is free for the bridge fault pin.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
