#!/usr/bin/env python3
r"""
me711_native_io_proof.py - execute V79's far module (hcio711.c) out of the LINKED
image in c167sim and check what it does, not what its comments say.

    py tests\firmware\asic\me711_native_io_proof.py

  A  the ASIC port images start at the OEM's own idle values, except the
     pre-cat heater gates P7.4/P8.7, which rest CLEAR (V93: measured active
     HIGH)
  B  frame-synchronous duty: 0 % never, 50 % exactly half the frames, 100 %
     always - and a stage ON is a CLEAR bit (active LOW); a pre-cat heater
     ON is a SET bit
  C  hc_io_all_off() returns every managed output to the idle image
  D  run-on: KL15 low with the native relay -> NLEN_FR (P3.12) LOW at once,
     key-off flagged after the debounce, HELD while persistence is busy,
     RELEASED (P3.12 HIGH) once it is idle; the 15 s ceiling forces a release;
     KL15 back cancels; not configured -> P3.12 never moves
  E  LSU 4.2: the binary's integer conversion against the rusEFI fit
     (GetPhiLsu42) at points across the range, within 0.005 lambda
  F  the bench pulse refuses a post-cat heater, accepts a pre-cat one
     (V93 drive experiment) and times three pulses on N75

NOT PHYSICAL. No ASIC, no CJ120, no pin: the frame words and the P3 latch.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_config_state_test as T      # noqa: E402  the rig with a step budget
import me711_image as PI                 # noqa: E402

P3, DP3 = 0xFFC4, 0xFFC6
FAILS = 0
IDLE = [0x00FF, 0x0000, 0x3DCF, 0x0069, 0x6301, 0x00F0, 0x7FEF]
LDR, TEV, LSH2VK, LSH1HK, LSH1VK = 0, 1, 2, 3, 5
HOLD, RELEASED, TIMEOUT, OFF = 1, 2, 3, 4


def check(name, ok, detail=""):
    global FAILS
    print("  [%s] %-60s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def p312(r):
    return (r.m.sfr.get(P3, 0) >> 12) & 1


def phi42(ip_ma):
    if ip_ma > 1.19:
        return 0.5
    if ip_ma < -1.85:
        return 1 / 0.7
    g = -0.23505 if ip_ma < 0 else -0.41441
    return g * ip_ma + 0.99153


def main() -> int:
    print("=== V79 hcio711.c from the linked image ===")
    print("  image %s  sha256 %s\n" % (PI.image().name, PI.sha256()))
    r = T.boot()
    r("hc_io_init")
    words = [r("hc_io_word", i) for i in range(7)]
    check("A  idle images: OEM's [BIN 0x8B17B0], heater gates CLEAR",
          words == IDLE,
          " ".join("%04X" % w for w in words))

    def frames(n):
        on = 0
        for _ in range(n):
            r("hc_io_frame")
            if not (r("hc_io_word", 6) & 0x0004):
                on += 1
        return on
    r("hc_io_duty", LDR, 0)
    check("B  N75 at 0 %: never ON", frames(20) == 0)
    r("hc_io_duty", LDR, 500)
    n = frames(20)
    check("B  N75 at 50 %: exactly 10 of 20 frames ON (bit 2 CLEAR)", n == 10,
          "%d/20" % n)
    r("hc_io_duty", LDR, 1000)
    check("B  N75 at 100 %: every frame ON", frames(20) == 20)
    r("hc_io_duty", LDR, 0)
    # A pre-cat heater drives only while the wideband lifecycle permits it
    # (key on, CJ120 verified and settled, fresh battery and ASIC samples,
    # heat policy not Off). None of that holds here, so a raw 100 % duty is
    # RELEASED - gate LOW, duty cleared. The bit mapping itself (P8.7 = bit
    # 15, active HIGH) is proven by the bench pulse in F.
    r("hc_io_duty", LSH1VK, 1000)
    r("hc_io_frame")
    w = r("hc_io_word", 6)
    check("B  heater LSH1VK without lifecycle permission: released, word 58 idle",
          w == IDLE[6], "word58=%04X" % w)
    r("hc_io_duty", LSH2VK, 1000)
    r("hc_io_frame")
    w = r("hc_io_word", 6)
    check("B  heater LSH2VK without lifecycle permission: released, word 58 idle",
          w == IDLE[6], "word58=%04X" % w)
    r("hc_io_duty", LSH1VK, 1000)
    r("hc_io_duty", LDR, 1000)
    r("hc_io_all_off")
    r("hc_io_frame")
    check("C  all_off: word 58 back to the idle image",
          r("hc_io_word", 6) == IDLE[6], "%04X" % r("hc_io_word", 6))

    # ------------------------------------------------------------- run-on
    r.m.sfr[P3] = r.m.sfr.get(P3, 0) | 0x1000
    r.m.sfr[DP3] = r.m.sfr.get(DP3, 0) | 0x1000
    f = 0xFF & r("hc_io_runon_service", 1000, 1, 1, 0, 0)
    check("D  KL15 on + native relay: keep-alive PRE-ARMED (P3.12 LOW)",
          f == 0 and p312(r) == 0, "P3.12=%d" % p312(r))
    f = 0xFF & r("hc_io_runon_service", 1001, 0, 1, 1, 0)
    check("D  KL15 drop: NLEN_FR LOW at once, run-on asserted",
          p312(r) == 0 and (f & 2) != 0, "flags=%X P3.12=%d" % (f, p312(r)))
    check("D  ... key-off NOT yet flagged inside the 20 ms debounce",
          (f & 1) == 0)
    f = 0xFF & r("hc_io_runon_service", 1030, 0, 1, 1, 0)
    check("D  after 29 ms: key-off flagged, still holding", f == 3,
          "flags=%X" % f)
    f = 0xFF & r("hc_io_runon_service", 1500, 0, 1, 1, 0)
    check("D  persistence BUSY at 499 ms: still holding, P3.12 LOW",
          f == 3 and p312(r) == 0)
    f = 0xFF & r("hc_io_runon_service", 1600, 0, 1, 0, 2000)
    check("D  store idle but min hold 2000 ms not reached: holding",
          f == 3 and p312(r) == 0)
    f = 0xFF & r("hc_io_runon_service", 3100, 0, 1, 0, 2000)
    check("D  idle and hold met: RELEASED, veto restored (P3.12 HIGH)",
          (f & 2) == 0 and p312(r) == 1, "flags=%X" % f)
    r("hc_io_runon_service", 3200, 1, 1, 0, 0)
    r("hc_io_runon_service", 5000, 0, 1, 1, 0)
    f = 0xFF & r("hc_io_runon_service", 19999, 0, 1, 1, 0)
    check("D  busy for ever: still holding at 14999 ms", (f & 2) != 0)
    f = 0xFF & r("hc_io_runon_service", 20001, 0, 1, 1, 0)
    check("D  ... released by the 15 s ceiling (P3.12 HIGH)",
          (f & 2) == 0 and p312(r) == 1, "flags=%X" % f)
    f = 0xFF & r("hc_io_runon_service", 20100, 1, 1, 0, 0)
    check("D  KL15 back: RUN, no flags, keep-alive re-armed",
          f == 0 and p312(r) == 0)
    f = 0xFF & r("hc_io_runon_service", 20200, 0, 0, 1, 0)
    check("D  not configured: veto (P3.12 HIGH), key-off flagged, no hold",
          (f & 2) == 0 and p312(r) == 1)
    f = 0xFF & r("hc_io_runon_service", 20250, 1, 0, 0, 0)
    check("D  KL15 on, not configured: veto held", f == 0 and p312(r) == 1)
    r("hc_io_runon_service", 20300, 1, 0, 0, 0)

    # --------------------------------------------------------------- LSU
    worst = 0.0
    for raw in range(200, 520, 8):
        ua = raw * 5.0 / 1023
        ip = (ua - 1.5) / (8 * 61.9) * 1000
        ref = max(0.7, min(2.0, 1 / phi42(ip)))
        got = r("hc_io_lambda_calc", raw) / 1000.0
        worst = max(worst, abs(got - ref))
    check("E  LSU 4.2 integer conversion within 0.005 of the rusEFI fit",
          worst <= 0.005, "worst %.4f" % worst)
    ref308 = 1 / phi42((308 * 5.0 / 1023 - 1.5) / (8 * 61.9) * 1000)
    check("E  1.505 V (raw 308, no sensor) = the fit at Ip~0, lambda ~1.01",
          abs(r("hc_io_lambda_calc", 308) / 1000.0 - ref308) <= 0.005,
          "%d vs %.4f" % (r("hc_io_lambda_calc", 308), ref308))

    # -------------------------------------------------------------- bench
    check("F  a post-cat heater bench pulse is REFUSED",
          (0xFF & r("hc_io_test_start", LSH1HK, 500, 0)) == 0)
    # the bench heater pulse needs the key on (KL15 status, P6.2)
    r.m.sfr[0xFFCC] = r.m.sfr.get(0xFFCC, 0) | (1 << 2)
    tick = T.sym("hc_tick_ms") & 0xFFFF
    r.m.w16(tick, 10000)
    okh = (0xFF & r("hc_io_test_start", LSH1VK, 200, 0)) == 1
    hon = hoff = 0
    for step in range(0, 4000, 10):
        r.m.w16(tick, 10000 + step)        # the frame times the pulse on it
        r("hc_io_test_service", 10000 + step)
        r("hc_io_frame")
        if r("hc_io_word", 6) & 0x8000:
            hon += 1
        else:
            hoff += 1
    check("F  pre-cat heater pulse: 3 x 200 ms gate HIGH, LOW otherwise",
          okh and 57 <= hon <= 63, "%d frames HIGH, %d LOW" % (hon, hoff))
    r("hc_io_all_off")
    ok = (0xFF & r("hc_io_test_start", LDR, 200, 0)) == 1
    ms, on_frames, t = 30000, 0, []
    for step in range(0, 4000, 10):
        r("hc_io_test_service", ms + step)
        r("hc_io_frame")
        if not (r("hc_io_word", 6) & 0x0004):
            on_frames += 1
    check("F  N75 bench: 3 x 200 ms ON = 60 frames of 10 ms",
          ok and 57 <= on_frames <= 63, "%d frames" % on_frames)

    # ------------------------------------------ G: the refused-apply unblock
    # Measured on the ECU (V79, 2026-09-25): pinMainRelay = 23 written with
    # the mode still OFF is refused; writing mode AUTO (a LIVE field) must
    # unblock the staged transaction so it applies.
    import me711_config_state_test as CS
    g = CS.boot()
    off_pin = CS.O["CFG_U_PIN_MAIN_RELAY"] if "CFG_U_PIN_MAIN_RELAY" in CS.O         else 2590
    g("hc_cfg_mgr_write_u8", off_pin, 23)
    g("hc_cfg_mgr_service", 0)
    b1 = g("hc_hal_main_relay_bound") & 0xFF
    g("hc_cfg_mgr_write_u8", 73, 2)            # CFG_MAIN_RELAY_MODE = AUTO
    g("hc_cfg_mgr_service", 0)
    b2 = g("hc_hal_main_relay_bound") & 0xFF
    check("G  pin 23 with mode OFF is refused (bound stays 0)", b1 == 0,
          "bound=%d" % b1)
    check("G  ...and a LIVE mode=AUTO write unblocks it: bound = 2", b2 == 2,
          "bound=%d" % b2)

    # --------------------------------- H (V81): the ASIC's PWM words 59..66
    # The ASIC loads PP0..3 / PW0..3 from these every frame; 0 there is FULL
    # ON if PWMCON1 enables an output. They must carry the OEM's forced-OFF
    # pair (PP 0xFFFE, PW 0xFFFF) - see hcio711.h.
    try:
        pw = [r("hc_io_pwm_word", i) & 0xFFFF for i in range(8)]
    except BaseException as e:                           # noqa: BLE001
        pw = "absent from this image: %r" % e
    check("H  PP0..PP3 = 0xFFFE and PW0..PW3 = 0xFFFF (never 0 = ON)",
          pw == [0xFFFE] * 4 + [0xFFFF] * 4,
          " ".join("%04X" % w for w in pw) if isinstance(pw, list) else pw)

    # ------------------------------------ I (V81): CLT / IAT OEM curves
    # The OEM curves [BIN 0x81F9C8 CLT, 0x819739 IAT], as seeded into the
    # 1.8T preset, through the firmware's OWN interpolator. Values are
    # 0.1 degC + 10000 (CAL_TEMP_BIAS whole degrees).
    CLT_AX = [27, 43, 68, 112, 145, 187, 310, 392, 483, 581, 676, 720, 760,
              796, 854, 909]
    CLT_V = [11400, 11200, 11000, 10800, 10700, 10600, 10400, 10300, 10200,
             10100, 10000, 9950, 9900, 9850, 9750, 9600]
    IAT_AX = [28, 48, 64, 92, 116, 148, 192, 244, 308, 372, 432, 572, 664,
              744, 864, 900]
    IAT_V = [11403, 11200, 11050, 10900, 10803, 10698, 10600, 10503, 10398,
             10323, 10248, 10098, 10000, 9902, 9700, 9602]
    for name, AX, VAL, ax, vv in (("CLT", 1152, 1184, CLT_AX, CLT_V),
                                  ("IAT", 1254, 1286, IAT_AX, IAT_V)):
        for i in range(16):
            r("hc_cal_set_u16", AX + 2 * i, ax[i])
            r("hc_cal_set_u16", VAL + 2 * i, vv[i])
        cv = lambda raw: r("hc_cal_curve16", AX, VAL, 16, raw) & 0xFFFF  # noqa
        exact = all(cv(ax[i]) == vv[i] for i in range(16))
        check("I  %s: every OEM axis point returns its own value" % name, exact)
        worst = 0
        for i in range(15):
            mid = (ax[i] + ax[i + 1]) // 2
            ref = vv[i] + (vv[i + 1] - vv[i]) * (mid - ax[i]) / (ax[i + 1] - ax[i])
            worst = max(worst, abs(cv(mid) - ref))
        check("I  %s: midpoints interpolate (<= 2 counts = 0.2 degC, integer)" % name,
              worst <= 2.0, "worst %.2f" % worst)
        check("I  %s: below the first point clamps (hot end)" % name,
              cv(0) == vv[0] and cv(ax[0] - 5) == vv[0])
        check("I  %s: above the last point clamps (cold end)" % name,
              cv(1023) == vv[-1])
        mono = all(cv(x) >= cv(x + 7) for x in range(ax[0], ax[-1] - 7, 7))
        check("I  %s: temperature never rises as the count rises" % name, mono)
        for label, raw, degc in (("hot", 112 if name == "CLT" else 92, None),
                                 ("ambient", 581 if name == "CLT" else 432, None)):
            print("       %s %-8s raw %4d -> %.1f degC" % (
                name, label, raw, (cv(raw) - 10000) / 10.0))

    print()
    if FAILS:
        print("V79 IO PROOF FAILED (%d)" % FAILS)
        return 1
    print("V79 IO PROOF PASSES - executed from the linked image; nothing "
          "here is a pin.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
