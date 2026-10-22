#!/usr/bin/env python3
r"""
me711_preset_apply_proof.py - the engine preset ACTUALLY APPLIES, through the
same path TunerStudio's "APPLY ENGINE PRESET" button uses, and it lands whole
or not at all.

    py tests\firmware\config\me711_preset_apply_proof.py            the image under test (V86+)
    py tests\firmware\config\me711_preset_apply_proof.py --control  also run the V85 control

WHY. Real TunerStudio, 2026-09-26, V85: the operator selected "VAG 1.8T DBW
on the Bosch ME7.1.1 board" and NOT ONE ordinary field changed - displacement
0, coil pins NONE, MAP/IAT/CLT NONE, main relay OFF. Three defects in a chain:

  1. hc_preset_apply_engine() was linked and CALLED BY NOTHING. No command
     reached it; enginePreset was an ordinary stored enum.
  2. The selector's labels were indexed by LIST POSITION, and the list is ids
     0,1,2,4,3 - so the 1.8T name sat on value 4, the board-default preset.
  3. Even when called (only ever from a simulator gate), it wrote field by
     field through hc_cfg_mgr_write_u8(): LIVE calibration reached ACTIVE
     before anything had asked whether the resulting page could run.

WHAT THIS RUNS - the linked image in c167sim, no model of it:
  hcts_target_cmd("!E")   exactly what the '!' dispatcher in hcts.c calls
  hc_preset_cmd_service() exactly what the main loop calls next
and reads BOTH images (DESIRED, what TunerStudio reads back; ACTIVE, what the
runtime reads) plus the published verdict words at OCH 764..775.

THE STARTING PAGE is deliberately a different, VALID engine - six cylinders,
36-1, semi-sequential, paired wasted spark, swapped TPS/APP tracks, no
MAP/CLT/IAT/pump/relay - installed in ACTIVE and re-booted, so the proof
starts from a page the firmware itself accepted at boot.

NOT PHYSICALLY VERIFIED. The acceptance is the operator pressing the button in
real TunerStudio 3.3.01 and seeing the fields change.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths as HCP  # noqa: E402

pass  # (bootstrap above)

import me711_config_state_test as T   # noqa: E402  the rig
import me711_image as PI              # noqa: E402

GEN_H = (ROOT / "firmware/generated/hc_config_generated.h").read_text()
CFG_H = (ROOT / "firmware/config/hcconfig.h").read_text()


def off(name):
    for txt in (GEN_H, CFG_H):
        m = re.search(r"#define\s+%s\s+(0x[0-9A-Fa-f]+|\d+)u?\b" % name, txt)
        if m:
            return int(m.group(1), 0)
    raise SystemExit(name + " not found")


PAGE = off("HC_CFG_SIZE")
NONE = off("HC_PIN_NONE")
F = {n: off(n) for n in (
    "CFG_CYLINDERS", "CFG_STROKES", "CFG_TDC_CYL", "CFG_SY_TEETH",
    "CFG_SY_GAP", "CFG_TRIG_GAP_RATIO_X10", "CFG_REV_MAX", "CFG_INJ_CHANNEL",
    "CFG_IGN_CHANNEL", "CFG_MAIN_RELAY_MODE",
    "CFG_U_PIN_INJ", "CFG_U_PIN_IGN", "CFG_U_PIN_CRANK", "CFG_U_PIN_MAP",
    "CFG_U_PIN_CLT", "CFG_U_PIN_IAT", "CFG_U_PIN_TPS1", "CFG_U_PIN_TPS2",
    "CFG_U_PIN_APP1", "CFG_U_PIN_APP2", "CFG_U_PIN_FUEL_PUMP",
    "CFG_U_PIN_MAIN_RELAY", "CFG_U_PIN_OIL_PRESS", "CFG_U_INJ_STRATEGY",
    "CFG_U_IGN_STRATEGY", "CFG_U_SYNC_MODE", "CFG_U_LAM1_SRC",
    "CFG_U_LAM2_SRC", "CFG_U_ENGINE_PRESET", "CAL_DBW_ENABLE", "CAL_DBW_KP",
    "CFG_U_TPS_CORR",
)}

PRESET_18T = 3          # hanicore_presets.py VAG_18T_ME711
REQ = 0xF700            # near scratch for the '!E' bytes: bottom of the
                        # user stack, far below its measured worst case

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-62s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def u16(r, o, active=True):
    f = r.active if active else r.desired
    return (f(o) << 8) | f(o + 1)


def och(r, at):
    a = 0x380000 + 0x2000 + at            # TGT_EXTRAM_BASE + TGT_RAM_OCH
    return (r.m.r8(a) << 8) | r.m.r8(a + 1)


def both(r, o):
    return r.active(o), r.desired(o)


def set_active(r, o, v, width=1):
    if width == 2:
        r("hc_cal_set_u16", o, v)
    else:
        r("hc_cal_set_u8", o, v)


def install_start_page(r):
    """A different, VALID engine, written into ACTIVE, then a fresh
    hc_cfg_mgr_init() so DESIRED is seeded from it and the boot-time
    validation passes judgement on it."""
    six_inj = [96, 97, 88, 89, 112, 113]
    six_ign = [102, 103, 94, 95, 110, 111]
    set_active(r, F["CFG_CYLINDERS"], 6)
    set_active(r, F["CFG_STROKES"], 4)
    for i, a in enumerate((0, 1200, 2400, 3600, 4800, 6000, 0, 0)):
        set_active(r, F["CFG_TDC_CYL"] + 2 * i, a, 2)
    for i in range(12):
        set_active(r, F["CFG_U_PIN_INJ"] + i, six_inj[i] if i < 6 else NONE)
        set_active(r, F["CFG_U_PIN_IGN"] + i, six_ign[i] if i < 6 else NONE)
    for i in range(8):
        set_active(r, F["CFG_INJ_CHANNEL"] + i, i if i < 6 else 0)
        set_active(r, F["CFG_IGN_CHANNEL"] + i, i if i < 6 else 0)
    set_active(r, F["CFG_SY_TEETH"], 36, 2)
    set_active(r, F["CFG_SY_GAP"], 1)
    set_active(r, F["CFG_TRIG_GAP_RATIO_X10"], 15, 2)
    set_active(r, F["CFG_REV_MAX"], 6000, 2)
    set_active(r, off("CFG_REV_LIMIT"), 5800, 2)     # must stay <= revMax
    set_active(r, F["CFG_U_INJ_STRATEGY"], 1)       # semi-sequential
    set_active(r, F["CFG_U_IGN_STRATEGY"], 0)       # wasted paired
    set_active(r, F["CFG_U_SYNC_MODE"], 1)
    for n in ("CFG_U_PIN_MAP", "CFG_U_PIN_CLT", "CFG_U_PIN_IAT",
              "CFG_U_PIN_FUEL_PUMP", "CFG_U_PIN_MAIN_RELAY",
              "CFG_U_PIN_OIL_PRESS"):
        set_active(r, F[n], NONE)
    set_active(r, F["CFG_MAIN_RELAY_MODE"], 0)
    set_active(r, F["CFG_U_PIN_TPS1"], 84)
    set_active(r, F["CFG_U_PIN_TPS2"], 92)
    set_active(r, F["CFG_U_PIN_APP1"], 34)
    set_active(r, F["CFG_U_PIN_APP2"], 35)
    set_active(r, F["CFG_U_TPS_CORR"], 0)
    set_active(r, F["CFG_U_LAM1_SRC"], 0)
    set_active(r, F["CFG_U_LAM2_SRC"], 0)
    set_active(r, F["CFG_U_ENGINE_PRESET"], 0)
    set_active(r, F["CAL_DBW_KP"], 1000, 2)
    r("hc_cfg_mgr_init")


def install_test_fuel(r):
    """TEST-ONLY fuel data for gates that run the engine model on the AWT
    preset. The preset ships no injector or VE calibration (named gaps), so
    a gate sets a round 300 cc/min injector and a synthetic VE that rises
    with throttle and slightly with rpm (15.0 % .. 92.0 %): non-flat in both
    axes, so a transposed lookup still shows. Written to ACTIVE."""
    r("hc_cal_set_u16", off("CFG_U_INJ_FLOW_CCMIN"), 300)
    ve = off("CAL_FUEL_MAP")
    for load in range(16):
        for rpm in range(16):
            r("hc_cal_set_u16", ve + 2 * (load * 16 + rpm),
              150 + 47 * load + 3 * rpm)


def press_apply(r, preset_id=None):
    """What TunerStudio does: write the selection (a 'W'), then send '!E'."""
    if preset_id is not None:
        r.write(F["CFG_U_ENGINE_PRESET"], preset_id)
    r.m.w8(REQ, ord("!"))
    r.m.w8(REQ + 1, ord("E"))
    r("hcts_target_cmd", REQ, 2)


def service(r):
    """One main-loop pass's worth of configuration work. An image WITHOUT the
    V86 service (the V85 control) gets what its own main loop runs instead."""
    try:
        T.sym("hc_preset_cmd_service")
    except SystemExit:
        r("hc_cfg_mgr_service", 0, steps=60_000_000)
        return
    r("hc_preset_cmd_service", steps=60_000_000)


def page(r, active):
    f = r.active if active else r.desired
    return bytes(f(i) for i in range(PAGE))


def main() -> int:
    print("=== HaniCore ME7.1.1 - the engine preset applies, whole or not at all ===")
    print("  image   %s" % PI.image().name)
    print("  sha256  %s\n" % PI.sha256())

    # --------------------------------------------------- the starting page
    r = T.boot()
    install_start_page(r)
    fell = r.g8("hc_cfg_boot_fellback")
    check("the different starting page validates at boot", fell == 0,
          "hc_cfg_boot_fellback = %d" % fell)
    check("  ...6 cylinders, 36-1, no CLT/IAT/MAP routed",
          r.active(F["CFG_CYLINDERS"]) == 6
          and u16(r, F["CFG_SY_TEETH"]) == 36
          and r.active(F["CFG_U_PIN_CLT"]) == NONE
          and r.active(F["CFG_U_PIN_MAP"]) == NONE)
    attempts0 = r("hc_nvm_attempts")
    commits0 = r("hc_nvm_commits")
    # The fields the AWT preset deliberately does NOT set (named gaps:
    # injector, coil and pressure-sensor data, base maps).
    GAP_FIELDS = (("CFG_U_INJ_FLOW_CCMIN", 2), ("CAL_DWELL_BATT_VAL", 16),
                  ("CAL_DEADTIME_VAL", 16), ("CAL_MAP_SENS_GRD", 2),
                  ("CAL_FUEL_MAP", 512), ("CAL_IGN_MAP", 256))
    gap_before = {n: [r.desired(off(n) + i) for i in range(w)]
                  for n, w in GAP_FIELDS}

    # ---------------------------------------------- selecting is not applying
    r.write(F["CFG_U_ENGINE_PRESET"], PRESET_18T)
    r("hc_cfg_mgr_apply_now", 0)
    check("SELECTING the preset alone changes no other field",
          r.desired(F["CFG_U_PIN_CLT"]) == NONE
          and r.desired(F["CFG_CYLINDERS"]) == 6,
          "the V85 symptom, by design now: selection is only a choice")

    # ------------------------------------------------------- press APPLY
    press_apply(r)
    v = och(r, 764)
    check("'!E' is only RECORDED by the command handler", v == (7 | 3 << 8)
          and och(r, 772) == 0x0103,
          "verdict word 0x%04X, pending 0x%04X" % (v, och(r, 772)))
    service(r)
    v = och(r, 764)
    check("the main-loop service APPLIED preset 3", v == (1 | 3 << 8),
          "verdict word 0x%04X, faults 0x%04X" % (v, och(r, 766)))
    check("  ...and asks TunerStudio to re-read the page (OCH 770)",
          och(r, 770) == 1)

    exp = {
        "CFG_U_PIN_CLT": 93, "CFG_U_PIN_IAT": 26, "CFG_U_PIN_MAP": 101,
        "CFG_U_PIN_TPS1": 92, "CFG_U_PIN_TPS2": 84,
        "CFG_U_PIN_APP1": 35, "CFG_U_PIN_APP2": 34,
        "CFG_U_PIN_FUEL_PUMP": 65, "CFG_U_PIN_MAIN_RELAY": 23,
        "CFG_MAIN_RELAY_MODE": 2, "CFG_U_PIN_CRANK": 82,
        # 2026-10-11 CAR: sequential injection + sequential COP ran with
        # camPhaseLevel 1 (hanicore_presets.py: wasted/semi fallback until
        # the cycle is known), cam-1 cycle sync, lambda 1 on-board
        "CFG_U_INJ_STRATEGY": 2, "CFG_U_IGN_STRATEGY": 2,
        "CFG_U_SYNC_MODE": 2, "CFG_U_LAM1_SRC": 1, "CFG_U_LAM2_SRC": 0,
        "CAL_DBW_ENABLE": 0, "CFG_U_ENGINE_PRESET": 3, "CFG_SY_GAP": 2,
    }
    for n, want in exp.items():
        a, d = both(r, F[n])
        check("%s = %d in ACTIVE and DESIRED" % (n, want),
              a == want and d == want, "active %d desired %d" % (a, d))
    inj = [r.active(F["CFG_U_PIN_INJ"] + i) for i in range(4)]
    ign = [r.active(F["CFG_U_PIN_IGN"] + i) for i in range(4)]
    check("injector cavities cyl1..4 = 96/89/97/88", inj == [96, 89, 97, 88],
          str(inj))
    check("coil cavities cyl1..4 = 102/95/103/94", ign == [102, 95, 103, 94],
          str(ign))
    rest = [r.active(F["CFG_U_PIN_INJ"] + i) for i in range(4, 12)] +            [r.active(F["CFG_U_PIN_IGN"] + i) for i in range(4, 12)]
    check("injector/coil slots 5..12 cleared - nothing left from 6 cyl",
          all(x == NONE for x in rest), str(rest[:4]))
    ich = [r.active(F["CFG_INJ_CHANNEL"] + i) for i in range(4)]
    gch = [r.active(F["CFG_IGN_CHANNEL"] + i) for i in range(4)]
    check("injector channel map = 0/3/1/2 (firing 1-3-4-2)", ich == [0, 3, 1, 2],
          str(ich))
    check("ignition channel map = 0/3/1/2", gch == [0, 3, 1, 2], str(gch))
    tdc = [u16(r, F["CFG_TDC_CYL"] + 2 * i) for i in range(4)]
    check("TDC 0/540/180/360 deg", tdc == [0, 5400, 1800, 3600], str(tdc))
    check("60-2 trigger, gap ratio 2.5",
          u16(r, F["CFG_SY_TEETH"]) == 60
          and u16(r, F["CFG_TRIG_GAP_RATIO_X10"]) == 25)
    check("DBW gains are LIVE and landed (kP 5.12)",
          u16(r, F["CAL_DBW_KP"]) == 5120)
    # RESTART_REQUIRED by the config model, exactly as for a typed edit:
    # DESIRED holds the preset, ACTIVE keeps the old until Burn + key cycle.
    cyl_a, cyl_d = both(r, F["CFG_CYLINDERS"])
    rp = r.g8("hc_cfg_restart_pending")
    check("cylinders = 4 in DESIRED; RESTART-required, pending flagged",
          cyl_d == 4 and cyl_a == 6 and rp == 1,
          "desired %d active %d restart_pending %d" % (cyl_d, cyl_a, rp))
    check("revMax = 7500 in DESIRED (RESTART-required)",
          u16(r, F["CFG_REV_MAX"], active=False) == 7500)
    check("displacement 1781 cc in DESIRED (RESTART-required)",
          u16(r, off("CFG_U_DISPLACEMENT_CC"), active=False) == 1781)
    check("injector test pressure 300 kPa; cranking dwell 0 (battery curve)",
          u16(r, off("CFG_U_INJ_REF_KPA")) == 300
          and u16(r, off("CFG_U_CRANK_DWELL_X100")) == 0)
    changed = [n for n, w in GAP_FIELDS
               if [r.desired(off(n) + i) for i in range(w)] != gap_before[n]]
    # 2026-10-10: the stock AWT values are back in the preset (the car
    # cranked with injector flow 0 without them) - APPLY must SET them.
    check("the stock AWT engine data is applied: injector flow 301, dwell, "
          "dead time, pressure sensor, VE and ignition maps",
          len(changed) == len(GAP_FIELDS)
          and u16(r, off("CFG_U_INJ_FLOW_CCMIN")) == 301,
          "changed: %s" % changed)
    check("nothing left dirty - one pass applied every group",
          r.g16("hc_cfg_dirty_groups") == 0,
          "0x%04X" % r.g16("hc_cfg_dirty_groups"))
    check("NO Burn was attempted",
          r("hc_nvm_attempts") == attempts0 and r("hc_nvm_commits") == commits0)
    r("hc_cfg_mgr_validate")
    check("the applied page validates", r.g16("hc_cfg_validation") == 0)

    # ------------------------------ a manual edit afterwards is ordinary
    r.write(F["CFG_U_PIN_FUEL_PUMP"], NONE)
    r("hc_cfg_mgr_apply_now", 0)
    check("a later manual edit applies like any other edit",
          both(r, F["CFG_U_PIN_FUEL_PUMP"]) == (NONE, NONE)
          and r.active(F["CFG_U_ENGINE_PRESET"]) == 3)

    # ----------------------- an INVALID result changes NOTHING, anywhere
    r = T.boot()
    install_start_page(r)
    r.write(F["CFG_U_PIN_OIL_PRESS"], 93)     # valid now: CLT is unrouted
    r("hc_cfg_mgr_apply_now", 0)
    ok_start = r.active(F["CFG_U_PIN_OIL_PRESS"]) == 93
    before_a, before_d = page(r, True), page(r, False)
    press_apply(r, PRESET_18T)
    before_d = bytearray(before_d)
    before_d[F["CFG_U_ENGINE_PRESET"]] = PRESET_18T   # the selection write
    service(r)
    v = och(r, 764)
    check("a preset whose page would not validate is REFUSED",
          ok_start and v == (5 | 3 << 8),
          "verdict 0x%04X faults 0x%04X first bad %d"
          % (v, och(r, 766), och(r, 768)))
    check("  ...naming the conflict (93 = oil pressure AND coolant)",
          (och(r, 766) & T.VAL["HC_VAL_FAULT_PIN_CONFLICT"]) != 0)
    after_a, after_d = page(r, True), page(r, False)
    diff_a = [i for i in range(PAGE) if after_a[i] != before_a[i]]
    diff_d = [i for i in range(PAGE) if after_d[i] != before_d[i]]
    check("  ...ACTIVE is byte-identical (incl. LIVE fields like dbwKp)",
          not diff_a, "%d bytes differ %s" % (len(diff_a), diff_a[:8]))
    check("  ...DESIRED is byte-identical (every staged byte rolled back)",
          not diff_d, "%d bytes differ %s" % (len(diff_d), diff_d[:8]))
    check("  ...and no page refresh was requested", och(r, 770) == 0)

    # ------------------------------------------------ engine turning
    r = T.boot()
    install_start_page(r)
    before_a = page(r, True)
    r.m.w16(T.sym("trg_rpm") & 0xFFFF, 900)
    press_apply(r, PRESET_18T)
    service(r)
    check("refused while the engine turns, ACTIVE untouched",
          och(r, 764) == (2 | 3 << 8) and page(r, True) == before_a,
          "verdict 0x%04X" % och(r, 764))

    # --------------------------------------------- Custom / foreign board
    r = T.boot()
    press_apply(r, 0)
    service(r)
    check("'Custom' is answered, not silently ignored",
          och(r, 764) == 3, "verdict 0x%04X" % och(r, 764))
    r = T.boot()
    r.m.w8(REQ, ord("!")); r.m.w8(REQ + 1, ord("E")); r.m.w8(REQ + 2, 1)
    r("hcts_target_cmd", REQ, 3)
    service(r)
    check("the ME7.5 preset (id 1) is refused as another ECU's",
          och(r, 764) == (4 | 1 << 8), "verdict 0x%04X" % och(r, 764))

    # ------------------------- no runtime path keyed on the preset id
    readers = []
    for f in HCP.sources("me711", "*.c"):
        t = f.read_text(errors="replace")
        if "CFG_U_ENGINE_PRESET" in t:
            readers.append(f.name)
    check("CFG_U_ENGINE_PRESET appears only in the preset/config plumbing",
          set(readers) <= {"hc_presets.c", "hc_config_manager.c",
                           "hcdiag711.c", "hc_config_generated.c"},
          ", ".join(sorted(readers)))
    # The '!E' command handler (hcts_target_cmd's cold half, hcdiag711.c).
    t = HCP.find("hcdiag711.c").read_text()
    uses = [ln for ln in t.splitlines() if "CFG_U_ENGINE_PRESET" in ln]
    check("  ...the '!E' handler reads it only to pick WHICH preset applies",
          len(uses) == 1 and "hc_cfg_mgr_read_u8" in uses[0], uses[0].strip()
          if uses else "")

    print("\n  %d/%d checks passed" % (CHECKS - FAILS, CHECKS))

    if "--control" in sys.argv:
        # THE SAME CHECKS AGAINST THE FROZEN V85 IMAGE, WHICH MUST FAIL: it has
        # no '!E' case and no service, so pressing APPLY populates nothing -
        # the operator's observation, reproduced in the simulator.
        print("\n=== CONTROL: the V85 image must FAIL - it has no apply path ===")
        env = dict(os.environ,
                   HANICORE_ME711_STEM="HaniCore_ME711_v85_vehicle_prep")
        res = subprocess.run([sys.executable, str(Path(__file__))], env=env,
                             capture_output=True, text=True)
        for ln in [x for x in res.stdout.splitlines()
                   if "[FAIL]" in x or "checks passed" in x][:14]:
            print("   " + ln)
        print("  V85 control exit %d - %s" % (
            res.returncode, "FAILS as it must" if res.returncode else
            "PASSED, SO THIS GATE CANNOT TELL THE DIFFERENCE"))
        if res.returncode == 0:
            return 1
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
