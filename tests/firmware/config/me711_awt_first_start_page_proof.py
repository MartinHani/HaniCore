#!/usr/bin/env python3
r"""
me711_awt_first_start_page_proof.py - APPLY, Grab, Burn and restart leave the
AWT page the car needs, read back through the paths TunerStudio uses.

    py tests\firmware\config\me711_awt_first_start_page_proof.py            the current image
    py tests\firmware\config\me711_awt_first_start_page_proof.py --control  + the V89 control

THE DEFECTS (first AWT vehicle test, 2026-09-26):

  * APPLY put displacementCc 1781 in DESIRED (RESTART_REQUIRED); the Burn
    validated DESIRED but persisted ACTIVE, so after the key cycle both read 0
    - alpha-N with zero swept volume, no running fuel. The car's page had
    enginePreset 3 and displacement 0.
  * A fresh page + APPLY left trigSource 0 ("bench generator only") and
    fuelPumpMode 0 ("never commanded"): the car only had them from an older
    bench page. After a full-image flash the store is blank.
  * The pedal Grab buttons "did nothing": eng_calib_grab() wrote ACTIVE only
    and TunerStudio reads DESIRED.

WHAT THIS RUNS, on the LINKED image in c167sim:

  1. a fresh page (hc_cfg_init + hc_cfg_mgr_init, no SRAM content);
  2. APPLY preset 3 the way TunerStudio does it - enginePreset written, then
     the '!E' bytes into hcts_target_cmd(), then the main-loop service;
  3. pedal and throttle Grabs as the '!G' bytes TunerStudio sends, with the
     ADC readings the AWT gave (released 150/75, floored 849/424), and one
     refused grab (a rail) that must say so;
  4. the Burn's commit - the function the linked hcnvm stage step calls - with
     the engine stopped;
  5. a restart on the same battery-backed memory;
  6. EVERY value of the generated preset 3 compared in ACTIVE and DESIRED,
     the grabbed endpoints, and the first-start-critical list by name.

NEGATIVE CONTROL: the frozen V89 image must fail (displacement after restart,
trigSource/fuelPumpMode, grabs not in DESIRED).

NOT PHYSICALLY VERIFIED: the real flash store and TunerStudio are the bench
step - tests/physical/me711_awt_bench_qualify.py does the same comparison on the ECU.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

CONTROL_STEM = "HaniCore_ME711_v89_alphan_awt"
PRESETS_C = ROOT / "firmware/generated/hc_presets.c"
CHECKS = FAILS = 0

# name, offset, width, value - the list the car cannot start without
CRITICAL = [
    ("cylinders", 2, 1, 4), ("strokes", 3, 1, 4),
    ("syTeeth", 20, 2, 60), ("syGap", 22, 1, 2),
    ("trigSource", 72, 1, 1), ("syncMode", 2538, 1, 2),   # V97: cam 1 cycle
    # V97: the PHYSICAL trigger angle - tooth #1 (the first tooth after the
    # gap) 78.0 deg BTDC, stored as the s16 -780 = 0xFCF4, carried whole
    # through APPLY, Burn and restart. (The car's own page keeps the -2.0 =
    # old 358.0 it ran on - docs/ARCHITECTURE.md.)
    ("trigDecoder", 2539, 1, 1), ("trigAngleX10", 2540, 2, 0xFCF4),
    # 2026-10-11 car: sequential + sequential COP ran with camPhaseLevel 1
    # (wasted / semi fallback until the cycle is known) - the preset since
    ("injStrategy", 2536, 1, 2), ("ignStrategy", 2537, 1, 2),
    ("displacementCc", 2510, 2, 1781),
    ("injFlowCcMin", 2638, 2, 301),     # 2026-10-10: the car cranked with 0 = no fuel
    ("loadSource", 1236, 1, 1), ("fuelPumpMode", 2680, 1, 1),
    ("pinFuelPump", 2591, 1, 65), ("pinCrank", 2548, 1, 82),
    ("pinClt", 2577, 1, 93), ("pinIat", 2578, 1, 26),
    ("lambda1Source", 2630, 1, 1),     # V97: on-board CJ120, display/log only
    ("dbwEnable", 1240, 1, 0),
    ("dbwMaxDutyX10", 2684, 2, 800),   # V97: Bosch DLRPIDMAX
    ("appCorrelation", 2621, 1, 1),
    ("tpsCorrelation", 2620, 1, 1),
]
INJ_PINS = (2551, [96, 89, 97, 88])
IGN_PINS = (2563, [102, 95, 103, 94])


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += 0 if ok else 1
    print("  [%s] %-60s %s" % ("PASS" if ok else "FAIL", name, detail))
    return ok


def preset_items(ident_name="items_vag_18t_me711"):
    txt = PRESETS_C.read_text(errors="replace")
    # 2026-10-11: the compiled table is byte runs (runs_<key>[]); every value
    # is listed just above it as an ITEM comment in the old row format. The
    # listing is cross-checked against the runs here, so it cannot drift.
    runs_name = ident_name.replace("items_", "runs_", 1)
    head, rest = re.split(r"static const unsigned char (?:HC_PRESET_MEM )?%s\[\] = \{"
                          % runs_name, txt, maxsplit=1)
    listing = (head[head.rindex("/* VAG 1.8T DBW (AWT) */"):]
               if ident_name == "items_vag_18t_me711" else head)
    items = [(int(o), int(v), int(w), c.strip())
             for o, v, w, c in re.findall(
                 r"/\* ITEM \{\s*(\d+)u,\s*(\d+)u,\s*(\d)u\s*\}([^*]*)\*/", listing)]
    body = re.sub(r"/\*.*?\*/", "", rest.split("};", 1)[0])
    data = [int(x, 0) for x in re.findall(r"(0x[0-9A-F]+|\d+)u", body)]
    page = {}
    k = 0
    while k < len(data):
        off, n = (data[k] << 8) | data[k + 1], data[k + 2]
        for i in range(n):
            page[off + i] = data[k + 3 + i]
        k += 3 + n
    for o, v, w, c in items:
        got = page.get(o) if w == 1 else ((page.get(o, -1) << 8) | page.get(o + 1, -1))
        assert got == v, "ITEM listing and runs disagree at %d (%s): %r vs %r" % (o, c, got, v)
    return items


def main_one(stem):
    os.environ["HANICORE_ME711_STEM"] = stem
    import me711_config_state_test as T
    import me711_preset_apply_proof as AP
    print("=== AWT first-start page - %s ===" % stem)
    r = T.boot()

    def u(o, w, active=True):
        f = r.active if active else r.desired
        return f(o) if w == 1 else (f(o) << 8) | f(o + 1)

    # ---- 2. APPLY, as TunerStudio sends it --------------------------------
    AP.press_apply(r, 3)
    AP.service(r)
    verdict = AP.och(r, 764) & 0xFF
    check("APPLY preset 3 through '!E' is accepted", verdict == 1,
          "verdict %d" % verdict)

    # ---- 3. Grabs through the same command TunerStudio sends --------------
    # The HAL's channel tables are filled in code by hc_hal_init() (no
    # ?C_INIT); without it every semantic reads adc_raw[0].
    r("hc_hal_init", steps=5_000_000)
    r("hc_route_service", steps=5_000_000)
    adc = T.sym("adc_raw") & 0xFFFF

    def set_adc(ch, v):
        r.m.w16(adc + 2 * ch, v)

    def grab(what):
        r.publish_samples()        # the pedal/TPS values as accepted samples
        r.m.w8(AP.REQ, ord("!"))
        r.m.w8(AP.REQ + 1, ord("G"))
        r.m.w8(AP.REQ + 2, what)
        r("hcts_target_cmd", AP.REQ, 3)
        return AP.och(r, 450)

    set_adc(8, 1020); set_adc(9, 76)
    res = grab(3)
    check("a grab at a rail is REFUSED and says so (verdict 4)",
          res & 0xFF == 4, "grabResult 0x%04X" % res)
    # NOT the preset's own 150/849/75/424, so a write cannot be mistaken
    # for the value that was already there.
    set_adc(8, 152); set_adc(9, 76)
    res = grab(3)
    ok_rest = res & 0xFF in (1, 7)
    set_adc(8, 846); set_adc(9, 423)
    res2 = grab(4)
    check("Grab pedal released / floored accepted",
          ok_rest and res2 & 0xFF in (1, 7),
          "grabResult 0x%04X / 0x%04X" % (res, res2))
    check("grab verdict names SAME correlation (7)", res2 & 0xFF == 7,
          "verdict %d" % (res2 & 0xFF))
    check("grabbed pedal endpoints are in DESIRED (what TS reads)",
          (u(1228, 2, False), u(1230, 2, False), u(1232, 2, False),
           u(1234, 2, False)) == (152, 846, 76, 423),
          "desired %s" % [u(o, 2, False) for o in (1228, 1230, 1232, 1234)])
    check("TunerStudio is told to re-read the page (OCH 770)",
          AP.och(r, 770) == 1, "presetPageRefresh %d" % AP.och(r, 770))
    set_adc(1, 101); set_adc(3, 892)          # TPS closed (rising/falling)
    t1 = grab(1)
    set_adc(1, 890); set_adc(3, 71)           # TPS fully open
    t2 = grab(2)
    check("Grab throttle closed / open accepted, both tracks in DESIRED",
          t1 & 0xFF in (1, 7) and t2 & 0xFF in (1, 7)
          and (u(1220, 2, False), u(1222, 2, False), u(1224, 2, False),
               u(1226, 2, False)) == (101, 890, 892, 71),
          "verdicts %d/%d desired %s" % (t1 & 0xFF, t2 & 0xFF,
          [u(o, 2, False) for o in (1220, 1222, 1224, 1226)]))

    # ---- 4. the Burn's commit, engine stopped -----------------------------
    try:
        T.sym("hc_cfg_mgr_commit_burn")
        rc = r("hc_cfg_mgr_commit_burn", 1, steps=60_000_000)
        how = "hc_cfg_mgr_commit_burn(stopped)"
    except SystemExit:
        rc = r("hc_cfg_mgr_commit", steps=60_000_000)
        how = "hc_cfg_mgr_commit() (pre-V90)"
    check("Burn commit validates clean", rc == 0, "%s -> 0x%04X" % (how, rc))

    # ---- 5. restart on the same memory ------------------------------------
    r("hc_cfg_init", steps=60_000_000)
    r("hc_cfg_mgr_init", steps=60_000_000)

    # ---- 6. every value --------------------------------------------------
    items = preset_items()
    grabbed = {1220, 1221, 1222, 1223, 1224, 1225, 1226, 1227,
               1228, 1229, 1230, 1231, 1232, 1233, 1234, 1235}
    bad = []
    for o, v, w, name in items:
        if o in grabbed:
            continue
        a, d = u(o, w), u(o, w, False)
        if a != v or d != v:
            bad.append("%s@%d want %d active %d desired %d" % (name, o, v, a, d))
    check("after restart, EVERY preset-3 value in ACTIVE and DESIRED",
          not bad, ("%d items" % len(items)) if not bad
          else "%d wrong: %s" % (len(bad), "; ".join(bad[:6])))
    for name, o, w, v in CRITICAL:
        a = u(o, w)
        check("restart: %-16s = %d" % (name, v), a == v, "active %d" % a)
    for label, (base, pins) in (("injPin", INJ_PINS), ("ignPin", IGN_PINS)):
        got = [u(base + i, 1) for i in range(4)]
        check("restart: %s = %s" % (label, pins), got == pins, "active %s" % got)
    got = [u(o, 2) for o in (1228, 1230, 1232, 1234)]
    check("restart: grabbed pedal endpoints persisted", got == [152, 846, 76, 423],
          "active %s" % got)
    return FAILS


def main() -> int:
    if "--one" in sys.argv:
        f = main_one(sys.argv[sys.argv.index("--one") + 1])
        print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
        return 1 if f else 0
    import me711_image as PI
    rc = subprocess.call([sys.executable, __file__, "--one", PI.STEM])
    if "--control" not in sys.argv:
        return rc
    print()
    rcc = subprocess.call([sys.executable, __file__, "--one", CONTROL_STEM])
    ok = rc == 0 and rcc != 0
    print("\nCONTROL: V89 %s" % ("FAILS, as it must" if rcc else "PASSES - gate blind"))
    print("AWT FIRST-START PAGE PROOF %s" % ("PASSES" if ok else "FAILS"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
