#!/usr/bin/env python3
r"""
me711_table_order_proof.py - the cell TunerStudio SHOWS is the cell the
firmware USES, and the AWT tables mean what their axes say.

    py tests\firmware\config\me711_table_order_proof.py            the current image
    py tests\firmware\config\me711_table_order_proof.py --control  + the V96 control

THE DEFECT (real TunerStudio, 2026-09-30): the AWT VE row labelled 100 %
throttle held ~0.5 % VE and the 0 % row ~9 %; the ignition 100 % row held
~40 deg. The data was right - hc_cal_map() read [rpm][load] - but
TunerStudio indexes an `[16x16]` array with xBins = rpm, yBins = load as
y * 16 + x, i.e. [load][rpm] (rusEFI veTable[VE_LOAD_COUNT][VE_RPM_COUNT];
its non-square ignitionIatCorrTable [4x8] = [LOAD 8][TEMP 4] proves the
order). Every 16x16 table was shown TRANSPOSED: the "100 % row" was the
6800 rpm row. V97 stores [load][rpm] (generate_config.TABLE_ORDER).

WHAT THIS RUNS - the LINKED image in c167sim over the applied AWT preset,
against the GENERATED .ini (the TunerStudio side):

  A. RUNTIME == DISPLAY. For VE, ignition, target AFR and the pedal map,
     at EVERY grid point: hc_cal_map(z, x axis, y axis, x[i], y[j]) - the
     function the engine calls - must return the byte TunerStudio shows in
     row j, column i, located with the .ini's own offsets and index
     y * nx + x.
  B. THE AXES MEAN WHAT THEY SAY (the AWT alpha-N preset, as displayed):
     VE never falls as the throttle row rises, at every rpm; the WOT row's
     advance is below the closed-throttle row's at every rpm; idle cells
     (<= 5 % throttle, <= 1000 rpm) are usable (VE > 0, advance 0..30 deg).
  C. THE ENGINE AGREES: eng_service() at 3000 rpm, throttle 5 % vs 60 %:
     cylinder air mass rises, ignition advance falls.
  MUTATION: the same page with the VE rows REVERSED must fail B and C.
  NEGATIVE CONTROL: V96 (frozen, [rpm][load]) must fail A.
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

# T1 ticks per ms, from hctarget.h (hcengctl711.c's T1_PER_MS), never typed.
T1_PER_MS = int(re.search(
    r"#define\s+TGT_TICKS_PER_MS_X10\s+(\d+)",
    (Path(__file__).resolve().parents[3] / "firmware/targets/me711/hctarget.h")
    .read_text(errors="replace")).group(1)) // 10

CONTROL_STEM = "HaniCore_ME711_v96_wideband"
# the CURRENT generated file. V98r2: this named the V97 one, and passed
# only while no table offset had moved.
INI = ROOT / "tunerstudio/hanicore_me711.ini"
CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += 0 if ok else 1
    print("  [%s] %-62s %s" % ("PASS" if ok else "FAIL", name, detail))


def ini_tables(text):
    """{table id: (z, x, y)} from [TableEditor], and {name: (off, dims)}."""
    consts = {}
    for m in re.finditer(r"^\s*(\w+)\s*=\s*array,\s*\w+,\s*(\d+),\s*\[(\d+)(?:x(\d+))?\]",
                         text, re.M):
        dims = (int(m.group(3)),) + ((int(m.group(4)),) if m.group(4) else ())
        consts[m.group(1)] = (int(m.group(2)), dims)
    tabs = {}
    for m in re.finditer(r"^\s*table\s*=\s*(\w+),.*?\n\s*(?:xyLabels.*\n\s*)?"
                         r"xBins\s*=\s*(\w+).*\n\s*yBins\s*=\s*(\w+).*\n\s*"
                         r"zBins\s*=\s*(\w+)", text, re.M):
        tabs[m.group(1)] = (m.group(4), m.group(2), m.group(3))
    return tabs, consts


def ve_monotonic(ve):
    """VE as displayed ([row = throttle][col = rpm]) never falls up a column."""
    bad = [(c, r) for c in range(16) for r in range(15)
           if ve[(r + 1) * 16 + c] < ve[r * 16 + c]]
    return not bad, bad


def main_one(stem):
    os.environ["HANICORE_ME711_STEM"] = stem
    import me711_config_state_test as T
    import me711_preset_apply_proof as AP
    print("=== table order - %s ===" % stem)
    text = INI.read_text(encoding="utf-8", errors="replace")
    tabs, consts = ini_tables(text)
    check("the .ini declares the table order", "; tableOrder = load-major" in text)
    r = T.boot()
    r.publish_on_service = True     # sensors as accepted samples (T.Rig)
    AP.press_apply(r, 3)
    AP.service(r)
    AP.install_test_fuel(r)
    r("hc_cal_set_u16", T.d(T._gen, "CFG_U_DISPLACEMENT_CC"), 1781)

    def u16(off):
        return r("hc_cal_u16", off) & 0xFFFF

    # ------------------------------------------ A. runtime == display ----
    for tid in ("veTableTbl", "ignMapTbl", "afrMapTbl", "pedalMapTbl"):
        z, x, y = tabs[tid]
        (zo, zd), (xo, _xd), (yo, _yd) = consts[z], consts[x], consts[y]
        nx, ny = zd
        xs = [u16(xo + 2 * i) for i in range(nx)]
        ys = [u16(yo + 2 * j) for j in range(ny)]
        bad = []
        wide = z == "veTable"            # V98r2: u16 cells, hc_cal_map16
        for j in range(ny):
            for i in range(nx):
                k = j * nx + i
                if wide:                                     # TunerStudio
                    shown = (r.active(zo + 2 * k) << 8) | r.active(zo + 2 * k + 1)
                    used = r("hc_cal_map16", zo, xo, yo, xs[i], ys[j]) & 0xFFFF
                else:
                    shown = r.active(zo + k)
                    used = r.callb("hc_cal_map", zo, xo, yo, xs[i], ys[j])
                if shown != used:
                    bad.append((i, j, shown, used))
        check("%s: runtime lookup == displayed cell at all %d points"
              % (z, nx * ny), not bad,
              "first mismatch col %d row %d: shown %d, used %d" % bad[0]
              if bad else "row = %s, column = %s" % (y, x))

    # ------------------------------------ B. the axes mean what they say --
    zo = consts["veTable"][0]
    ve = [(r.active(zo + 2 * k) << 8) | r.active(zo + 2 * k + 1)
          for k in range(256)]                     # V98r2: u16, 0.1 %
    io = consts["ignMap"][0]
    ign = [r.active(io + k) for k in range(256)]
    mono, bad = ve_monotonic(ve)
    check("VE never falls as the throttle row rises (every rpm column)",
          mono, "first fall at col/row %s" % (bad[:1],) if bad else
          "0 %%: %.1f..%.1f %%, 100 %%: %.1f..%.1f %% VE"
          % (ve[0] / 10, ve[15] / 10, ve[240] / 10, ve[255] / 10))

    def adv(c):
        return (c - 40) * 0.5

    wot_lt = all(adv(ign[15 * 16 + c]) <= adv(ign[c]) for c in range(16))
    check("ignition: the WOT row's advance <= the closed row's, every rpm",
          wot_lt, "closed %.1f..%.1f deg, WOT %.1f..%.1f deg"
          % (adv(ign[0]), adv(ign[15]), adv(ign[240]), adv(ign[255])))
    iax = [u16(consts["fuelLoadAx"][0] + 2 * j) for j in range(16)]
    rax = [u16(consts["fuelRpmAx"][0] + 2 * i) for i in range(16)]
    idle = [(j, i) for j in range(16) for i in range(16)
            if iax[j] <= 50 and rax[i] <= 1000]
    check("idle cells (<= 5 %% throttle, <= 1000 rpm) usable: VE > 0, "
          "advance 0..30 deg (%d cells)" % len(idle),
          idle and all(ve[j * 16 + i] > 0 for j, i in idle)
          and all(0 <= adv(ign[j * 16 + i]) <= 30 for j, i in idle))

    # ----------------------------------------------- C. the engine agrees --
    adc = T.sym("adc_raw") & 0xFFFF

    def run(tps_pct, rpm=3000):
        t1 = 102 + int(852 * tps_pct / 100)          # AWT preset TPS1 102->954
        t2 = 919 - int(848 * tps_pct / 100)          # TPS2 919->71
        for ch, v in ((1, t1), (3, t2), (8, 150), (9, 75), (5, 646), (14, 400)):
            r.m.w16(adc + 2 * ch, v)
        r.m.w16(T.sym("trg_rpm") & 0xFFFF, rpm)
        # 2026-10-12: TIME PASSES. The load fills the manifold (FR BGSRM,
        # hcengctl711.c hc_ec_load_lag) by the T1 time between engine
        # passes; back-to-back calls with no time between them left the
        # load at its old value and this read a half-filled state. 2 ms per
        # pass, 0.5 s in all = ~10 time constants at 3000 rpm.
        for _ in range(250):
            r.m.w16(0xFE52, (r.m.r16(0xFE52) + 2 * T1_PER_MS) & 0xFFFF)
            r("eng_service", steps=5_000_000)
        return (r.g16("eng_tps_x10"), r.g16("eng_air_mg_x10"),
                r.g16("eng_adv_x10"))

    r("hc_hal_init", steps=5_000_000)
    r("eng_init", steps=5_000_000)
    r("hc_route_service", steps=5_000_000)
    lo, hi = run(5), run(60)
    check("3000 rpm, throttle 5 -> 60 %: modelled air mass RISES",
          hi[1] > lo[1] > 0, "tps %.1f %%: %.1f mg, tps %.1f %%: %.1f mg"
          % (lo[0] / 10, lo[1] / 10, hi[0] / 10, hi[1] / 10))
    check("...and ignition advance FALLS",
          hi[2] < lo[2], "%.1f -> %.1f deg" % (lo[2] / 10, hi[2] / 10))

    # --------------------------------------------------------- MUTATION --
    rev = [ve[(15 - (k // 16)) * 16 + (k % 16)] for k in range(256)]
    check("MUTATION rows reversed: the monotonic check REFUSES it",
          not ve_monotonic(rev)[0])
    for k in range(256):
        r("hc_cal_set_u16", zo + 2 * k, rev[k])
    mlo, mhi = run(5), run(60)
    check("MUTATION rows reversed: the engine air check REFUSES it",
          not (mhi[1] > mlo[1] > 0), "%.1f mg -> %.1f mg"
          % (mlo[1] / 10, mhi[1] / 10))
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
    print()
    print("CONTROL: %s %s" % (CONTROL_STEM, "FAILS, as it must" if rcc
                                              else "PASSES - gate blind"))
    print("TABLE ORDER PROOF %s" % ("PASSES" if ok else "FAILS"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
