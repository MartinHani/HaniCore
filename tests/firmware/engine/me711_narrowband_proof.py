#!/usr/bin/env python3
r"""
me711_narrowband_proof.py - the NARROWBAND lambda source (2026-10-27).

    py tests\firmware\engine\me711_narrowband_proof.py
    (HANICORE_BOARD=vag_me71_c4 for the board without CJ120)

The 2.7T board carries no CJ120; its stock sensors are narrowband (the 4F
has two on-board LSU controllers, 4F port plan 2b).
Lambda source 4 reads the bank's lambda pin as a switching sensor and maps it
to a PSEUDO-lambda (hcio711.c lam_nb): 1.000 at 0.45 V, 0.90 at >= 0.80 V
(rich), 1.10 at <= 0.10 V (lean). On a board without CJ120 the bank's
pre-cat heater stage follows the page's heater policy.

CHECKS, run in c167sim against the linked image:
  N1  0.45 V -> 1.000 (+-0.003), 0.30 V -> lean of 1, 0.60 V -> rich of 1
  N2  saturation: 0.10 V and below -> 1.100, 0.80 V and above -> 0.900
  N3  monotonic over the whole 0..1.2 V sweep
  N4  the external analog source (2) still reads its own 0.68..1.36 scale
      from the same pin - the two sources are distinct
  N5  (no-CJ120 boards) heater policy IGNITION drives the bank-1 heater
      stage; policy OFF releases it

WHY IT CANNOT PASS VACUOUSLY: N2 needs two different saturation values at
the two ends, N4 needs a different value from the same pin under another
source, and N5 needs the stage both set and cleared.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402
import hc_board  # noqa: E402
import me711_config_state_test as T  # noqa: E402
import me711_preset_apply_proof as A  # noqa: E402

off = A.off
FAILS = CHECKS = 0
LS1VK_CH = 6                      # AN6, pinLambda1's default (hcfresh711.c)


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    FAILS += not ok
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))


def main() -> int:
    print("=== narrowband lambda source - %s ===" % hc_board.BOARD)
    r = T.boot()
    r("hc_hal_init", steps=5_000_000)
    r("hc_route_service")
    src = off("CFG_U_LAM1_SRC")

    def lam(mv, source=4):
        r("hc_cal_set_u8", src, source)
        raw = int(round(mv * 1023 / 5000.0))
        r.m.w16((T.sym("adc_raw") & 0xFFFF) + 2 * LS1VK_CH, raw)
        r.publish_samples()
        return r("hc_io_lambda", 0)

    a = lam(450)
    check("N1 0.45 V reads lambda 1.000", abs(a - 1000) <= 3, "%d" % a)
    lean, rich = lam(300), lam(600)
    check("N1 0.30 V is lean of 1, 0.60 V rich of 1", lean > 1000 > rich,
          "%d / %d" % (lean, rich))
    lo, hi = lam(100), lam(800)
    check("N2 0.10 V saturates at 1.100, 0.80 V at 0.900",
          lo == 1100 and hi == 900 and lam(20) == 1100 and lam(1100) == 900,
          "%d / %d" % (lo, hi))
    sweep = [lam(mv) for mv in range(0, 1201, 50)]
    check("N3 monotonic over 0..1.2 V",
          all(x >= y for x, y in zip(sweep, sweep[1:])) and sweep[0] > sweep[-1],
          "%s" % sweep[::4])
    ext = lam(450, source=2)
    check("N4 the external analog source keeps its own scale on that pin",
          ext != a and 680 <= ext <= 1360, "%d" % ext)

    if hc_board.IS_C4:   # the only board without CJ120s (the 4F has them)
        pol = off("CFG_U_LAM_HEAT_POLICY")
        r("hc_cal_set_u8", src, 4)
        r("hc_io_init", steps=2_000_000)

        def heater(policy):
            r("hc_cal_set_u8", pol, policy)
            T.key_on(r)           # the frame releases every heater with the key off
            r.publish_samples()   # fresh battery + live ASIC: the frame needs both
            # (ms, ua1, ua2, ur1, ur2, vbatt_dv, running)
            now = r.m.r16(T.sym("hc_tick_ms") & 0xFFFF)   # the frame tests freshness
            # Keil: args 1-5 in R8..R12, 6-7 on the user stack at [R0], [R0+2]
            top = r.stack_top
            r.stack_top = top - 4
            r.m.w16(top - 4, 130)        # vbatt_dv 13.0 V
            r.m.w16(top - 2, 1)          # running
            r("hc_io_lambda_service", now, 0, 0, 0, 0)
            r.stack_top = top
            r("hc_io_frame", steps=2_000_000)
            return r("hc_io_word", 6) & 0x8000      # word 58: P8.7, bank 1

        on = heater(1)      # HC_LAMBDA_HEAT_IGNITION
        offv = heater(0)    # HC_LAMBDA_HEAT_OFF
        check("N5 policy IGNITION drives the bank-1 heater, OFF releases it",
              on != 0 and offv == 0, "on 0x%04X / off 0x%04X" % (on, offv))
    else:
        print("  (heater: this board has CJ120s, their own heater path)")

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    print("NARROWBAND PROOF PASSES" if not FAILS else "NARROWBAND PROOF FAILED")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
