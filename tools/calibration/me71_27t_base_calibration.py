#!/usr/bin/env python3
r"""
me71_27t_base_calibration.py - the Audi 2.7T biturbo base calibration for the
"Audi 2.7T biturbo" preset, DERIVED from a stock 2.7T image, every
conversion written down.

    py tools\calibration\me71_27t_base_calibration.py           print
    py tools\calibration\me71_27t_base_calibration.py --check   compare with the preset
    py tools\calibration\me71_27t_base_calibration.py --json

SOURCES.
  * ME7Sum bins/8D0907551M-0002.bin - stock Audi S4 B5 2.7T
    (EPK "ME7.1/5/6005.01", 1998-2002 APB/AGB family). The map ADDRESSES come
    from nefmoto/S4_B5_ME71_8D0907551M/8D0907551M-20190711.xdf
    (github.com/sostisoft/ecu-definitions, VAG/Audi_S4_B5_ME7.1, fetched
    2026-10-24). That XDF has no EPK; it is proven to fit THIS file by the
    values it yields (NMAX 6800 rpm, TVUB axis 7..18 V, KFZW axes 440..6520
    rpm / 9.75..191 %, KFMSNWDK monotonic) and by KLAF, which this tool
    reads at 0x14766 because it is byte-identical (all 501 points) to the
    AWT's A2L-addressed KLAF. THIRD-PARTY XDF + EXACT ENGINE-FAMILY BINARY.
  * The SCALES are the Bosch ones of the X505P A2L, as in
    me711_awt_base_calibration.py - NOT the XDF's printed equations, which
    are rounded to six decimals (KFURL "0.000005" for 0.3/65536 is 9 % off,
    KUMSRL "0.000008" for 0.002/256 2 %).
  * The owner's test ECU 4B0907551F (A6 C5 2.7T, SW 6010.01) carries the
    SAME intake-air curve (0x1918F, 20 points, byte-identical to 551M's
    0x19305), and its board (Bosch BOM 345;02 V6T) has TMOT = 2.61 k up /
    38.3 k down with NO switched pull-up (R1123/R1124/T1120 absent), so the
    coolant input uses the same curve.

WHAT IS STOCK DATA:
  injector  KRKTE raw 880 (AWT 945 at 213.4 g/min for the same 445 cc
            cylinder, me711_awt_base_calibration) -> Qstat 229.2 g/min
            -> 307.6 cc/min petrol at 3 bar (HaniCore 0.745 g/cc)
  dead time TVUB (1/375 ms) 2.000/1.008/0.800/0.704/0.608 ms at
            7.04/10.07/12.04/14.08/17.88 V
  dwell     KFSZT (0.1 ms) at 480 rpm - the longest column; HaniCore's dwell
            is battery-only
  pressure  DSLGRAD 541 hPa/V, DSLOFS -16.4 hPa - identical to the AWT
  VE        the stock throttle model (KFMSNWDK, KLAF, KFURL/KFPRG row 0,
            KUMSRL), solved exactly as the AWT one (FR BGMSZS/BGSRM),
            MSLG 3.0 kg/h (the X505P value - PROBABLE, as for the AWT)
  ignition  min(KFZW, KFZW2) on rl, -2 deg above 100 % rl; above the stock
            axis end (191 %) the last row is held, a further -3 deg by 220 %

WHAT IS JUDGEMENT: the mixture target and warm-up are the AWT preset's rule
(same 5-valve 81 x 86.4 mm cylinder, same boost class).
NOT PHYSICALLY VERIFIED: nothing here has run on a 2.7T.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402
import xdf_read  # noqa: E402
import me711_awt_base_calibration as AWT  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "reference/ME7Sum/bins/8D0907551M-0002.bin"
XDF = ROOT / "reference/nefmoto/S4_B5_ME71_8D0907551M/8D0907551M-20190711.xdf"
KLAF_AT = 0x14766              # = the AWT's KLAF, every byte (checked below)
AWT_KLAF_AT = 0x1529C
AWT_KRKTE_RAW, AWT_QSTAT_GMIN = 945, 213.4
PETROL_G_CC = 0.745

DWELL_AX = [598, 803, 1000, 1197, 1302, 1401, 1598, 1795]   # 0.01 V = KFSZT's
IGN_RPM = AWT.IGN_RPM
IGN_RL = [10, 15, 20, 27, 35, 45, 55, 65, 80, 100, 120, 140, 160, 180, 200, 220]
RL_RETARD_END = 220.0


def _items():
    it = xdf_read.read(XDF, BIN)

    def one(name, i=0):
        v = it[name][i]
        if "unreadable" in v.kind:
            raise SystemExit("%s: %s" % (name, v.kind))
        return v
    return one


def model():
    """The stock throttle model in physical units (AWT tool's dict)."""
    b = BIN.read_bytes()
    awt = AWT.BIN.read_bytes()
    if b[KLAF_AT:KLAF_AT + 1002] != awt[AWT_KLAF_AT:AWT_KLAF_AT + 1002]:
        raise SystemExit("KLAF at 0x%X is not the AWT's" % KLAF_AT)
    one = _items()
    ms, url, prg = one("KFMSNWDK"), one("KFURL"), one("KFPRG")
    um = one("KUMSRL")
    # rows = wdk (y), columns = n (x) in this XDF; raw values, Bosch scales
    return dict(
        wdk=[v for v in ms.y],                     # 100/65536 % (XDF exact)
        n=[v for v in ms.x],
        ms=[[r * 0.1 for r in row] for row in ms.raw],
        un=[v for v in url.x], fups=[r * 0.3 / 65536 for r in url.raw[0]],
        pn=[v for v in prg.x], pirg=[r * 0.0390625 for r in prg.raw[0]],
        klaf=[int.from_bytes(b[KLAF_AT + 2 * i:KLAF_AT + 2 * i + 2], "little")
              / 65536.0 for i in range(501)],
        kumsrl=um.raw * 0.002 / 256)


def ve_table(rpm_ax, load_ax):
    m = model()
    return [int(round(AWT.ve_model(r, t / 10.0, m=m)[0] * 10))
            for t in load_ax for r in rpm_ax]


def build():
    one = _items()
    krkte = one("KRKTE").raw
    qstat = AWT_QSTAT_GMIN * AWT_KRKTE_RAW / krkte
    tv = one("TVUB")
    tv_v, tv_ms = tv.x, [r / 375.0 for r in tv.raw[0]]
    sz = one("KFSZT")
    sz_v = sz.y
    sz_ms = [row[0] * 0.1 for row in sz.raw]       # the 480 rpm column
    if [int(round(v * 100)) for v in sz_v] != DWELL_AX:
        raise SystemExit("KFSZT voltage axis moved: %s" % sz_v)
    dead = [int(round(AWT.interp1(v / 100.0, tv_v, tv_ms) * 1000)) for v in DWELL_AX]
    dwell = [min(1000, int(round(ms * 100))) for ms in sz_ms]
    g = one("DSLGRAD", 1).z
    o = one("DSLOFS").z
    nmax = one("NMAX").z
    # ignition: min(KFZW, KFZW2), rows rpm x cols rl
    k1, k2 = one("KFZW"), one("KFZW2")
    n_ax, rl_ax = k1.y, k1.x
    kmin = [[min(a * 0.75, c * 0.75) for a, c in zip(r1, r2)]
            for r1, r2 in zip(k1.raw, k2.raw)]
    ign = []
    for rl in IGN_RL:
        for rpm in IGN_RPM:
            adv = AWT.interp2(rpm, min(rl, rl_ax[-1]), n_ax, rl_ax, kmin)
            if rl > 100.0:
                adv -= 2.0
            if rl > rl_ax[-1]:
                adv -= 3.0 * (rl - rl_ax[-1]) / (RL_RETARD_END - rl_ax[-1])
            adv = max(-15.0, min(45.0, adv))
            ign.append(int(round(adv / 0.5)) + 40)    # 0.5 deg, -20 offset
    return {
        "_qstat_gmin": round(qstat, 1),
        "injFlowCcMin": int(round(qstat / PETROL_G_CC)),
        "deadtimeVal": dead, "dwellBattAx": DWELL_AX, "dwellBattVal": dwell,
        "_dsl": (g, o), "_nmax": nmax,
        "ignRpmAx": IGN_RPM, "ignLoadAx": [v * 10 for v in IGN_RL],
        "ignMap": ign,
    }


def _preset():
    import hanicore_presets as HP
    return [e for e in HP.ENGINE_PRESETS if e.key == "AUDI_27T_ME71"][0]


def main():
    t = build()
    p = _preset().values if "--check" in sys.argv else None
    if p is not None:
        t["veTable"] = ve_table(p["fuelRpmAx"].value, p["fuelLoadAx"].value)
        keys = ("injFlowCcMin", "deadtimeVal", "dwellBattAx", "dwellBattVal",
                "ignRpmAx", "ignLoadAx", "ignMap", "veTable")
        bad = [k for k in keys
               if k not in p or (list(p[k].value) if isinstance(p[k].value, list)
                                 else p[k].value) != t[k]]
        print("preset matches the derivation" if not bad
              else "preset DIFFERS in: %s" % bad)
        return 1 if bad else 0
    if "--json" in sys.argv:
        import hanicore_presets as HP
        awt = [e for e in HP.ENGINE_PRESETS if e.key == "VAG_18T_ME711"][0].values
        t["veTable"] = ve_table(awt["fuelRpmAx"].value, awt["fuelLoadAx"].value)
        print(json.dumps({k: v for k, v in t.items() if not k.startswith("_")}))
        return 0
    print("Qstat %.1f g/min -> %d cc/min; DSLGRAD/OFS %s; NMAX %s"
          % (t["_qstat_gmin"], t["injFlowCcMin"], t["_dsl"], t["_nmax"]))
    print("dead time us", t["deadtimeVal"], " dwell 0.01 ms", t["dwellBattVal"])
    print("advance (deg) rows rl %, columns rpm", IGN_RPM)
    for i, rl in enumerate(IGN_RL):
        print("%5.0f " % rl + " ".join("%5.1f" % ((v - 40) * 0.5)
                                       for v in t["ignMap"][i * 16:(i + 1) * 16]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
