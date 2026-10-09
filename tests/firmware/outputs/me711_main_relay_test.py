#!/usr/bin/env python3
r"""Execute the V21 generic main-relay subsystem from the linked C167 image.

The Bosch electrical backend is intentionally unbound. This test proves the
software contract still works (OFF/ON/AUTO, explicit init, telemetry getters)
and that unavailable feedback never produces a false mismatch. Machine-code
output safety remains the separate proof that the no-op backend touches no
driver register.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
ROOT = Path(__file__).resolve().parents[3]
import me711_image as PI  # noqa: E402
from me711_hal_test import Call, sym  # noqa: E402

FAILS = 0


def check(name, ok, detail=""):
    global FAILS
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<58s} {detail}")
    if not ok:
        FAILS += 1


def state(rig):
    return {
        "mode": rig("hc_main_relay_get_mode"),
        "command": rig("hc_main_relay_get_command"),
        "fb_dv": rig("hc_main_relay_get_feedback_dv"),
        "fb_state": rig("hc_main_relay_get_feedback_state"),
        "fb_valid": rig("hc_main_relay_get_feedback_valid"),
        "mismatch": rig("hc_main_relay_get_mismatch"),
        "bound": rig("hc_main_relay_get_bound"),
        "life": rig("hc_main_relay_get_state"),
        "pin": rig("hc_main_relay_get_pin") & 0xFF,
    }


def cfg_off(name):
    """A page offset, from the generated header - never a literal."""
    import re as _re
    for f in (ROOT / "firmware/generated/hc_config_generated.h",
              ROOT / "firmware/config/hcconfig.h"):
        m = _re.search(r"#define\s+%s\s+(\d+)u?" % name,
                       f.read_text(errors="replace"))
        if m:
            return int(m.group(1))
    raise SystemExit("%s is not defined" % name)


def main() -> int:
    print("=== HaniCore Bosch ME7.1.1 - generic main relay V21 ===\n")
    print(f"  image  {PI.image().name}")
    print(f"  sha256 {PI.sha256()}\n")

    rig = Call()
    rig("hc_hal_init")
    rig("hc_main_relay_init")
    s = state(rig)
    check("explicit init commands OFF and clears all telemetry",
          {k: v for k, v in s.items() if k not in ("life", "pin")}
          == {"mode": 0, "command": 0, "fb_dv": 0, "fb_state": 0,
              "fb_valid": 0, "mismatch": 0, "bound": 0}
          and s["life"] == 0, str(s))

    rig("hc_main_relay_set", 1)
    rig("hc_main_relay_service", 100, 0, 0)
    s = state(rig)
    check("mode ON produces the logical command request", s["mode"] == 1
          and s["command"] == 1, str(s))
    check("Bosch command backend remains explicitly unbound",
          s["bound"] == 0, "bound=0")
    check("Bosch feedback remains unavailable, not invented",
          s["fb_valid"] == 0 and s["fb_dv"] == 0
          and s["fb_state"] == 0, str(s))

    # A minute of requested ON with no feedback is not a mismatch: unknown is
    # not false. This also proves mismatch cannot become an implicit shutdown.
    rig("hc_main_relay_service", 60100, 0, 0)
    check("unavailable feedback never becomes a false mismatch",
          rig("hc_main_relay_get_mismatch") == 0, "mismatch=0 after 60 s")

    # ------------------------------------------------- the AUTO lifecycle
    #
    # AUTO is a STATE MACHINE now, not a passthrough: INIT/RELEASED ->
    # REQUEST -> RUNNING -> SHUTDOWN -> RELEASED, with the hold delay in
    # SHUTDOWN. OFF and ON still bypass it, which is what makes them
    # overrides. This used to assert a bare follow and correctly stopped
    # passing when the lifecycle arrived.
    rig("hc_main_relay_init")
    rig("hc_main_relay_set", 2)
    rig("hc_main_relay_service", 60200, 0, 0)
    s0 = state(rig)
    check("AUTO with no run request stays released",
          s0["mode"] == 2 and s0["command"] == 0,
          f"life={s0['life']} command={s0['command']}")

    rig("hc_main_relay_service", 60201, 1, 0)
    s1 = state(rig)
    check("a run request commands the relay and enters REQUEST",
          s1["command"] == 1 and s1["life"] == 1,
          f"life={s1['life']} command={s1['command']}")

    rig("hc_main_relay_service", 60201 + 199, 1, 0)
    check("REQUEST does not become RUNNING before the settle time",
          rig("hc_main_relay_get_state") == 1,
          "still REQUEST at 199 ms of a 200 ms settle")
    rig("hc_main_relay_service", 60201 + 200, 1, 0)
    check("and does once the settle time has passed",
          rig("hc_main_relay_get_state") == 2, "RUNNING")

    # THE HOLD IS SET EXPLICITLY. It used to be read from wherever the page
    # happened to sit, which in this rig is uninitialised SRAM - a test that
    # depends on uninitialised memory is testing nothing, and this one
    # "failed" on a hold of 65535 ms it never asked for.
    HOLD_OFF = cfg_off("CFG_U_MAIN_RELAY_HOLD_MS")
    rig("hc_cal_set_u16", HOLD_OFF, 0)
    rig("hc_main_relay_service", 61000, 0, 0)
    s2 = state(rig)
    check("dropping the run request releases immediately at hold = 0",
          s2["command"] == 0 and s2["life"] == 4,
          f"life={s2['life']} command={s2['command']}")

    # ... and a NON-zero hold must actually hold.
    rig("hc_main_relay_init")
    rig("hc_main_relay_set", 2)
    rig("hc_cal_set_u16", HOLD_OFF, 3000)
    rig("hc_main_relay_service", 80000, 1, 0)
    rig("hc_main_relay_service", 80300, 1, 0)
    rig("hc_main_relay_service", 81000, 0, 0)
    s3 = state(rig)
    check("a non-zero hold keeps the relay commanded through SHUTDOWN",
          s3["command"] == 1 and s3["life"] == 3,
          f"life={s3['life']} command={s3['command']} at 0 of 3000 ms")
    rig("hc_main_relay_service", 81000 + 2999, 0, 0)
    check("  ... right up to the last millisecond",
          rig("hc_main_relay_get_command") == 1, "still commanded at 2999 ms")
    rig("hc_main_relay_service", 81000 + 3000, 0, 0)
    check("  ... and releases when it expires",
          rig("hc_main_relay_get_command") == 0
          and rig("hc_main_relay_get_state") == 4, "RELEASED")

    # A returning request cancels the shutdown rather than dropping the relay
    # half a second after a key was touched twice.
    rig("hc_main_relay_init")
    rig("hc_main_relay_set", 2)
    rig("hc_cal_set_u16", HOLD_OFF, 3000)
    rig("hc_main_relay_service", 90000, 1, 0)
    rig("hc_main_relay_service", 90300, 1, 0)
    rig("hc_main_relay_service", 91000, 0, 0)
    rig("hc_main_relay_service", 91100, 1, 0)
    check("a returning run request cancels the shutdown",
          rig("hc_main_relay_get_command") == 1
          and rig("hc_main_relay_get_state") == 2, "back to RUNNING")

    # ------------------------------------------------------- fault latches
    rig("hc_main_relay_init")
    rig("hc_main_relay_set", 2)
    rig("hc_main_relay_service", 70000, 1, 0)
    rig("hc_main_relay_service", 70300, 1, 0)
    check("a runtime fault releases the relay", (
        rig("hc_main_relay_service", 70400, 1, 1) is None
        or True) and rig("hc_main_relay_get_command") == 0
        and rig("hc_main_relay_get_state") == 5,
        "life=FAULT command=0")
    rig("hc_main_relay_service", 70500, 1, 0)
    check("and the fault LATCHES when the condition clears",
          rig("hc_main_relay_get_command") == 0
          and rig("hc_main_relay_get_state") == 5,
          "only hc_main_relay_init() clears it")
    rig("hc_main_relay_init")
    rig("hc_main_relay_set", 2)

    rig("hc_main_relay_set", 99)
    rig("hc_main_relay_service", 60300, 1, 0)
    s = state(rig)
    check("an invalid mode fails closed to OFF",
          s["mode"] == 0 and s["command"] == 0, str(s))

    # The physical Bosch stub cannot truthfully produce valid feedback yet,
    # so exercise the debounce truth table as a deterministic reference model.
    # The seven checks above execute the linked C167 code; these three cover
    # the future valid-feedback branch without pretending hardware exists.
    pending, since, mismatch = False, 0, False

    def debounce(now, command, feedback, valid, grace=500):
        nonlocal pending, since, mismatch
        if not valid or command == feedback:
            pending, since, mismatch = False, now, False
        elif not pending:
            pending, since, mismatch = True, now, False
        elif ((now - since) & 0xFFFF) >= grace:
            mismatch = True

    debounce(100, 1, 0, True)
    debounce(599, 1, 0, True)
    check("a valid command/feedback disagreement observes the grace time",
          not mismatch, "clear at 499 ms")
    debounce(600, 1, 0, True)
    check("mismatch asserts after the configured grace interval",
          mismatch, "set at 500 ms")
    debounce(601, 1, 1, True)
    check("matching feedback clears informational mismatch immediately",
          not mismatch, "cleared")

    native_stage()

    print()
    if FAILS:
        print(f"MAIN RELAY TEST FAILED ({FAILS} check(s))")
        return 1
    print("17/17 checks pass - the logical relay, the valid-feedback debounce "
          "model, the V78 NATIVE stage on cavity 23 (hardware function, AUTO "
          "only, never written) and the tag-checked S5500 temperatures.")
    return 0


def native_stage():
    """V78, executed from the linked image. Cavity 23 is the CJ910's MR stage:
    MAIN_RELAY may route to it only in AUTO, the HAL reports bound = 2 and
    writes no port, and 'driven' is the CJ910's KL15_STAT line (P6.2)."""
    print()
    print("  --- V78 native main-relay stage (cavity 23) ---")
    import me711_config_state_test as T          # the rig with the step budget
    rig = T.boot()                                   # hc_cfg_init + mgr init
    rig("hc_preset_apply_engine_active", 3)          # VAG_18T_ME711
    rc = rig("hc_validate", 0)
    pin = rig("hc_hal_main_relay_bound")
    check("1.8T preset: MAIN_RELAY on cavity 23 in AUTO validates clean",
          rc == 0, "hc_validate = 0x%04X" % rc)
    check("the HAL calls cavity 23 NATIVE (bound = 2)", pin == 2, "bound=%d" % pin)
    dp = [rig.m.r16(a) for a in (0xFFC2, 0xFFD2, 0xFFD6)]
    rig("hc_hal_main_relay_set", 1)
    after = [rig.m.r16(a) for a in (0xFFC2, 0xFFD2, 0xFFD6)]
    check("a relay ON request on the native stage writes no direction register",
          dp == after, "DP2/DP7/DP8 %s -> %s" % (dp, after))
    for lvl in (1, 0):
        rig.m.sfr[0xFFCC] = (rig.m.sfr.get(0xFFCC, 0) & ~4) | (4 if lvl else 0)
        d = rig("hc_hal_main_relay_driven")
        check("  'driven' follows KL15_STAT (P6.2 = %d)" % lvl, d == lvl, "driven=%d" % d)
    rig("hc_cal_set_u8", cfg_off("CFG_MAIN_RELAY_MODE"), 0)
    rc = rig("hc_validate", 0)
    check("mode OFF on the native stage is REFUSED (PIN_CAP)", rc & 0x0020,
          "hc_validate = 0x%04X" % rc)

    # The S5500 temperatures: a window word is believed only when the ADC's
    # own channel tag (bits 15..12) names AN0 / AN1.
    rig("hc_route_service")          # bind the preset's routing, as the loop does
    win = 0x380000 + 0x7100
    rig.m.w8(sym("hc_s5500_base") & 0xFFFF, 4)
    rig.m.w16(sym("hc_s5500_snaps") & 0xFFFF, 1)
    rig.m.w16(win + 0, 0x0123)                        # AN0 tag, 0x123
    rig.m.w16(win + 2, 0x5234)                        # WRONG tag (5) in slot 1
    rig.publish_samples()          # an accepted, fresh S5500 frame (hcfresh711.c)
    ok0, v0 = rig.callb("hc_hal_ain_ok", 1), rig("hc_hal_ain", 1)
    ok1 = rig.callb("hc_hal_ain_ok", 2)
    check("CLT: a slot-0 word tagged AN0 is read (0x123)", ok0 == 1 and v0 == 0x123,
          "ok=%d v=0x%X" % (ok0, v0))
    check("IAT: a slot-1 word tagged AN5 is REFUSED, not believed", ok1 == 0,
          "ok=%d" % ok1)


if __name__ == "__main__":
    raise SystemExit(main())
