"""ts_sensor_presets_me711.py - the 'Common sensors' choices of the
TunerStudio calibration windows (2026-10-11, owner: pick the sensor, do not
type a curve - as Speeduino and rusEFI do).

TunerStudio's settingSelector writes ordinary page values, so every choice is
COMPUTED HERE for THIS board's input circuit and written as the values the
firmware already reads. Nothing in the firmware changes.

PRESSURE (cavity 101, main-CPU AN14): kPa = mapSensOff + counts x
mapSensGrd / 1000 (hcengine.c), 5 V = 1024 counts. CHECKED against the stock
AWT calibration [EXACT TARGET BINARY 4B0906018DC: DSLGRAD 541.0 hPa/V,
DSLOFS -16.4 hPa] -> 264.2 kPa per 1000 counts = the preset's own 2642.
Each sensor below is given by its datasheet transfer function; offset =
kPa at 0 V, gradient = (kPa at 5 V - kPa at 0 V) x 1000 / 1024. The offset
field is unsigned: a sensor with a negative 0 V intercept is not offered.

TEMPERATURE (CLT cavity 93 = ASIC AN0, IAT cavity 26 = ASIC AN1), the ME7.1.1 schematic:
  IAT: R1120-type 2.61 k pull-up, 38.3 k pull-down;
  CLT: the same PLUS a 340 R stage (681 || 681) the board holds ON
       (PHYSICAL: an open CLT reads 1015 = 1023 x 38.3 / (38.3 + 0.301)).
  counts = 1023 x Reff / (Reff + Rpu), Reff = Rntc || 38.3 k.
CHECKED against this ECU's own curves [EXACT TARGET BINARY 0x81F976 CLT,
0x819739 IAT] with the Bosch NTC (0 C 5896, 50 C 834, 100 C 187 ohm):
CLT 20 C -> 906 counts (ECU 908 = 20 C), 80 C -> 528 (ECU 533 = 80 C),
100 C -> 391 (ECU ~101 C); IAT 20 C -> 484 (ECU 19.3 C). Agreement within
~1-2 C, the flat cold end within a few counts.
The Bosch / VAG choice is the ECU's OWN curve (exact, not computed).
Other sensors: a Steinhart-Hart fit through three published (C, ohm) points.

PROVENANCE (the maintainer's design notes class F): the sensor numbers are
physical facts - datasheet transfer functions and published resistance
points (the same points circulate in Speeduino's and rusEFI's sensor lists,
which were used to cross-check them). No text is copied from either project.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "config_source"))

ADC_FULL = 1023.0
R_PULLDOWN = 38300.0
R_PU_IAT = 2610.0
R_PU_CLT = 1.0 / (1.0 / 2610.0 + 1.0 / 340.5)     # 2.61 k || (681 || 681)

# ---------------------------------------------------------------- pressure
# (label, kPa at 0 V, kPa at 5 V, source). Ratiometric 5 V supply.
def _lin(a, b):
    """Vout = Vs x (a x P - b)  ->  P(0 V) = b / a, P(5 V) = (1 + b) / a"""
    return b / a, (1.0 + b) / a


PRESSURE_SENSORS = [
    # the stock AWT sensor, from the stock ECU's own constants (see above):
    # -1.64 kPa at 0 V (the unsigned offset field holds 0, as the preset)
    ("VAG 1.8T AWT stock (from the stock ECU calibration)", -1.64,
     -1.64 + 54.1 * 5.0, "EXACT TARGET BINARY 4B0906018DC DSLGRAD/DSLOFS"),
]
for _label, _ab, _src in (
        ("NXP MPX4250A / MPXA4250A (2.5 bar)", (0.004, 0.04),
         "NXP MPX4250A datasheet: Vout = Vs (0.004 P - 0.04)"),
        ("NXP MPX4115A (1.15 bar)", (0.009, 0.095),
         "NXP MPX4115 datasheet: Vout = Vs (0.009 P - 0.095)"),
        ("NXP MPX4100A (1.05 bar)", (0.01059, 0.1518),
         "NXP MPX4100A datasheet: Vout = Vs (0.01059 P - 0.1518)"),
        ("NXP MPXH6300A / GM 3-bar (3 bar)", (0.00318, 0.00353),
         "NXP MPXH6300A datasheet: Vout = Vs (0.00318 P - 0.00353)"),
        ("NXP MPXH6400A (4 bar)", (0.002421, 0.00842),
         "NXP MPXH6400A datasheet: Vout = Vs (0.002421 P - 0.00842)")):
    _p0, _p5 = _lin(*_ab)
    PRESSURE_SENSORS.append((_label, _p0, _p5, _src))


def pressure_fields(p0, p5):
    """-> (mapSensOff kPa, mapSensGrd kPa per 1000 counts), display units"""
    off = max(0.0, p0)
    grd = (p5 - p0) * 1000.0 / 1024.0
    return round(off, 1), round(grd, 1)


# ------------------------------------------------------------- thermistors
# (label, [(C, ohm) x 3], source)
THERMISTORS = [
    ("GM", [(-40, 100700), (30, 2238), (99, 177)],
     "GM coolant/air sensor published table"),
    ("Ford", [(0, 94000), (50, 11000), (98, 2370)],
     "Ford ECT/ACT published table"),
    ("Toyota", [(-40, 101890), (30, 2268), (99, 156)],
     "Toyota ECT published table"),
    ("Mitsubishi", [(-40, 100490), (30, 1875), (99, 125)],
     "Mitsubishi ECT published table"),
    ("Mazda Miata NA", [(-20, 16150), (40, 1150), (80, 330)],
     "Mazda NA ECT published table"),
    ("Mazda Miata NB", [(-10, 9000), (20, 2500), (80, 320)],
     "Mazda NB ECT published table"),
    ("Chrysler (1985 on)", [(5.5, 24500), (30.5, 8100), (88.3, 850)],
     "Chrysler ECT published table"),
    ("BMW E30 325i", [(-10, 9300), (20, 2500), (80, 335)],
     "BMW M20 coolant sensor published table"),
]

# the temperatures the computed curves are tabulated at (16 = CAL_AXIS_N);
# hotter -> lower resistance -> FEWER counts, so the counts axis ascends
CURVE_TEMPS = [150, 130, 115, 100, 90, 80, 70, 60, 50, 40, 30, 20, 10, 0,
               -20, -40]


def steinhart(points):
    """Steinhart-Hart through three (C, ohm) points -> R(T) in ohm."""
    (t1, r1), (t2, r2), (t3, r3) = points
    l1, l2, l3 = math.log(r1), math.log(r2), math.log(r3)
    y1, y2, y3 = (1.0 / (t1 + 273.15), 1.0 / (t2 + 273.15),
                  1.0 / (t3 + 273.15))
    g2 = (y2 - y1) / (l2 - l1)
    g3 = (y3 - y1) / (l3 - l1)
    c = (g3 - g2) / (l3 - l2) / (l1 + l2 + l3)
    b = g2 - c * (l1 * l1 + l1 * l2 + l2 * l2)
    a = y1 - (b + l1 * l1 * c) * l1

    def inv_t(lnr):
        return a + b * lnr + c * lnr ** 3

    def r_of_t(tc):
        # 1/T rises as R rises (an NTC): bisection on ln R, 1 ohm..100 Mohm
        y = 1.0 / (tc + 273.15)
        lo, hi = 0.0, math.log(1e8)
        if not (inv_t(lo) <= y <= inv_t(hi)):
            raise SystemExit("Steinhart fit does not reach %.1f C" % tc)
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if inv_t(mid) < y:
                lo = mid
            else:
                hi = mid
        return math.exp(0.5 * (lo + hi))
    return r_of_t


def counts(r_ntc, r_pu):
    reff = 1.0 / (1.0 / r_ntc + 1.0 / R_PULLDOWN)
    return ADC_FULL * reff / (reff + r_pu)


def thermistor_curve(points, r_pu):
    """-> (counts axis [16] ascending, deg C [16]) for this board's input"""
    r_of_t = steinhart(points)
    ax, val = [], []
    for tc in CURVE_TEMPS:
        ax.append(int(round(counts(r_of_t(tc), r_pu))))
        val.append(float(tc))
    for i in range(1, len(ax)):              # strictly ascending (cold end)
        if ax[i] <= ax[i - 1]:
            ax[i] = ax[i - 1] + 1
    if ax[-1] > 1023:
        raise SystemExit("thermistor curve runs past the ADC: %s" % ax)
    return ax, val


def oem_curve(key):
    """The ECU's own curve as the AWT preset carries it (EXACT TARGET
    BINARY): -> (counts axis, deg C)."""
    import hanicore_presets as HP
    p = [x for x in HP.all_presets() if x.ident == 3][0]
    ax = list(p.values[key + "Ax"].value)
    val = [(v - 10000) / 10.0 for v in p.values[key + "Val"].value]
    return ax, val


def temperature_options(which):
    """[(label, axis[16], degC[16])] for 'clt' or 'iat'"""
    r_pu = R_PU_CLT if which == "clt" else R_PU_IAT
    ax, val = oem_curve("cltSens" if which == "clt" else "iatSens")
    out = [("Bosch NTC - VAG G62/G42, Porsche (this ECU's own curve)",
            ax, val)]
    for label, pts, _src in THERMISTORS:
        a, v = thermistor_curve(pts, r_pu)
        out.append((label, a, v))
    return out


if __name__ == "__main__":
    for lab, p0, p5, src in PRESSURE_SENSORS:
        print("%-55s 0V %7.2f 5V %7.2f -> off/grd %s" % (
            lab, p0, p5, pressure_fields(p0, p5)))
    # self-check: the Bosch NTC through the model against the ECU's curves
    bosch = steinhart([(0, 5896), (50, 834), (100, 187)])
    for which, r_pu in (("cltSens", R_PU_CLT), ("iatSens", R_PU_IAT)):
        ax, val = oem_curve(which)
        worst = 0.0
        for tc in (20, 40, 60, 80, 90, 100):
            c = counts(bosch(tc), r_pu)
            for i in range(1, len(ax)):
                if ax[i - 1] <= c <= ax[i]:
                    f = (c - ax[i - 1]) / (ax[i] - ax[i - 1])
                    t_ecu = val[i - 1] + f * (val[i] - val[i - 1])
                    worst = max(worst, abs(t_ecu - tc))
        print("%s: Bosch NTC model vs the ECU's own curve, worst %.1f C "
              "(20..100 C)" % (which, worst))
    for which in ("clt", "iat"):
        for lab, a, v in temperature_options(which):
            print(which, lab[:30], a)
