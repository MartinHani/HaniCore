#!/usr/bin/env python3
r"""
me71_27t_preset_apply_proof.py - on the Audi 2.7T image, APPLY ENGINE PRESET
("Audi 2.7T biturbo V6", id 6) through the bytes TunerStudio sends lands the
whole preset as one transaction, and a Porsche-board preset cannot.

    py tests\firmware\config\me71_27t_preset_apply_proof.py

The same path the Porsche gate me711_preset_apply_proof drives: a 'W' of
enginePreset, then '!E' through hcts_target_cmd, then the main-loop service
hc_preset_cmd_service() - executed out of HaniCore_ME71_27T_v102_dev.bin in c167sim.

WHY IT CANNOT PASS VACUOUSLY. The starting page is a different valid engine
(the Porsche gate's 6-cylinder 36-1 page with NO CLT/IAT/MAP), so every
expected value must be WRITTEN by the apply; the control presses APPLY on the
AWT preset (id 3), which this image does not carry, and requires a refusal
with the page unchanged.

NOT PHYSICALLY VERIFIED - simulator only.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["HANICORE_BOARD"] = "vag_me71_c4"   # this gate IS about the 2.7T image, whatever board the run names
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402
import me711_image as PI  # noqa: E402
import me711_config_state_test as T  # noqa: E402
import me711_preset_apply_proof as A  # noqa: E402

PRESET_27T = 6
CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))


def main() -> int:
    if not PI.image().exists():
        print("SKIP: %s not built" % PI.image().name)
        return 0
    print("=== Audi 2.7T: the engine preset applies through '!E' ===")
    print("  image   %s\n" % PI.image().name)
    F, off, u16, och, both = A.F, A.off, A.u16, A.och, A.both

    r = T.boot()
    A.install_start_page(r)
    check("the 6-cylinder 36-1 starting page validates",
          r.g8("hc_cfg_boot_fellback") == 0)
    att0 = r("hc_nvm_attempts")
    A.press_apply(r, PRESET_27T)
    A.service(r)
    v = och(r, 764)
    check("the service APPLIED preset 6", v == (1 | PRESET_27T << 8),
          "verdict 0x%04X faults 0x%04X" % (v, och(r, 766)))
    exp = {"CFG_U_PIN_CRANK": 82, "CFG_U_PIN_CLT": 93, "CFG_U_PIN_IAT": 85,
           "CFG_U_PIN_MAP": 101, "CFG_U_PIN_TPS1": 92, "CFG_U_PIN_TPS2": 84,
           "CFG_U_PIN_APP1": 35, "CFG_U_PIN_APP2": 34,
           "CFG_U_PIN_FUEL_PUMP": 65, "CFG_U_INJ_STRATEGY": 0,
           "CFG_U_IGN_STRATEGY": 1, "CFG_U_SYNC_MODE": 1, "CFG_U_LAM1_SRC": 2,
           "CFG_U_LAM2_SRC": 0, "CAL_DBW_ENABLE": 0, "CFG_SY_GAP": 2,
           "CFG_U_ENGINE_PRESET": PRESET_27T}
    for n, want in exp.items():
        a, d = both(r, F[n])
        check("%s = %d (desired)" % (n, want), d == want,
              "active %d desired %d" % (a, d))
    check("pinLambda1 = 100 (spare 0-5 V input)",
          r.desired(off("CFG_U_PIN_LAMBDA1")) == 100)
    inj = [r.desired(F["CFG_U_PIN_INJ"] + i) for i in range(6)]
    ign = [r.desired(F["CFG_U_PIN_IGN"] + i) for i in range(6)]
    check("injectors cyl1..6 = 96/112/88/97/113/89", inj == [96, 112, 88, 97, 113, 89], str(inj))
    check("coils cyl1..6 = 102/110/94/103/111/95", ign == [102, 110, 94, 103, 111, 95], str(ign))
    tdc = [u16(r, F["CFG_TDC_CYL"] + 2 * i, active=False) for i in range(6)]
    check("TDC 0/480/240/120/600/360 deg (1-4-3-6-2-5)",
          tdc == [0, 4800, 2400, 1200, 6000, 3600], str(tdc))
    check("firing order FO_1_4_3_6_2_5",
          r.desired(off("CFG_U_FIRING_ORDER")) == 27)
    check("6 cylinders, 2671 cc, 308 cc/min, rev limit 6000 (desired)",
          r.desired(F["CFG_CYLINDERS"]) == 6
          and u16(r, off("CFG_U_DISPLACEMENT_CC"), active=False) == 2671
          and u16(r, off("CFG_U_INJ_FLOW_CCMIN"), active=False) == 308
          and u16(r, off("CFG_REV_LIMIT"), active=False) == 6000)
    check("trigger angle -78.0", u16(r, off("CFG_U_TRIG_ANGLE_X10"), active=False)
          == (-780 & 0xFFFF))
    check("NO Burn attempted", r("hc_nvm_attempts") == att0)
    r("hc_cfg_mgr_validate")
    check("the applied page validates", r.g16("hc_cfg_validation") == 0,
          "0x%04X" % r.g16("hc_cfg_validation"))

    # control: the AWT preset is another board's - refused, nothing written
    r = T.boot()
    A.install_start_page(r)
    before = A.page(r, False)
    A.press_apply(r, 3)
    A.service(r)
    v = och(r, 764)
    after = bytearray(A.page(r, False))
    after[F["CFG_U_ENGINE_PRESET"]] = before[F["CFG_U_ENGINE_PRESET"]]
    check("CONTROL: '!E' on the AWT preset is REFUSED on this board",
          (v & 0xFF) != 1, "verdict 0x%04X" % v)
    check("CONTROL: ...and the page is unchanged", bytes(after) == before)

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
