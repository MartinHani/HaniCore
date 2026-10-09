#!/usr/bin/env python3
r"""
me711_fuel_golden.py - the fixed-point air/fuel model against a float
reference, step by step, executed out of the linked image.

    py tests\firmware\engine\me711_fuel_golden.py

WHY STEP BY STEP.

A fuel calculation that is wrong at the end tells you almost nothing about
where. Worse, two errors can cancel: the model this replaces had no VE, no
displacement and no injector size at all, and it "worked" because a tuner had
put the answers straight into the table. So each function in hc_airfuel.c is
called on its own, with its own reference, and the tolerance for each is stated
as a quantization argument rather than a number that happened to pass.

WHAT THE REFERENCE IS. Ordinary double-precision Python implementing the same
physics from hc_airfuel.h's comments - ideal gas, ME7's 0 degC reference
density, petrol at 0.745 g/cm3. It is NOT a copy of the fixed-point code; if it
were, the two would agree about the same mistake.

THE WORKED CASE, which is also in the architecture document:
4.5 L V8, 100.0 kPa, 20.0 degC, VE 100.0 %, lambda 1.000, stoich 14.70,
440 cc/min -> rho 1.188 mg/cm3, air 667.6 mg, rl 92.1 %, fuel 45.4 mg,
te 8318 us.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_config_state_test as C   # noqa: E402  the Rig and the offsets
import me711_image as PI              # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
SHARED = ROOT / "firmware"

FAILS = 0
CHECKS = 0

R_AIR = 287.05
RHO_REF = 1.2929          # air at 0 degC, 1013.25 hPa, mg/cm3 - ME7's datum
FUEL_RHO = 0.745          # petrol, g/cm3


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-56s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def temp_bias():
    m = re.search(r"#define\s+CAL_TEMP_BIAS\s+(\d+)",
                  (SHARED / "config/hcconfig.h").read_text(errors="replace"))
    return int(m.group(1))


BIAS = temp_bias()


class Fuel(C.Rig):
    """The Rig, plus the 32-bit return convention.

    Keil C166 returns a long in R4/R5. Which half is which is not something to
    assume: the first check below calls a function whose answer is known and
    larger than 16 bits, and fails loudly if the halves are the other way
    round rather than silently reporting a wrong number.
    """

    def u32(self, fn, *args):
        self(fn, *args)
        lo = self.c.gr(4) & 0xFFFF
        hi = self.c.gr(5) & 0xFFFF
        return (hi << 16) | lo

    def u32a(self, fn, lo32, *rest):
        """Call with a 32-bit first argument (R8 low, R9 high) followed by
        16-bit arguments, and read a 32-bit return."""
        return self.u32(fn, lo32 & 0xFFFF, (lo32 >> 16) & 0xFFFF, *rest)

    def u16a(self, fn, lo32, *rest):
        """The same call, but the function returns `unsigned int` - 16 bits in
        R4, with R5 left holding whatever it held. Reading R5 anyway is how the
        first version of this test reported an open time of 4 294 910 076 us,
        which is the kind of number that at least announces itself."""
        return self.u32a(fn, lo32, *rest) & 0xFFFF


# ---------------------------------------------------------------- references
def ref_t_x10(iat_dc):
    return (iat_dc / 10.0 - BIAS) + 273.15


def ref_rho(map_x10, t_k):
    return (map_x10 / 10.0) * 1000.0 / (R_AIR * t_k) * 1000.0  # mg/cm3 *1000


def ref_air_mg(map_x10, t_k, vd_cc, ve_x10):
    rho = (map_x10 / 10.0) * 1000.0 / (R_AIR * t_k)     # kg/m3 == mg/cm3
    return rho * vd_cc * (ve_x10 / 1000.0)


def ref_rl_pct(air_mg, vd_cc):
    return air_mg / (vd_cc * RHO_REF) * 100.0


def ref_fuel_mg(air_mg, stoich_x100, lambda_x1000):
    return air_mg / ((stoich_x100 / 100.0) * (lambda_x1000 / 1000.0))


def ref_flow_mg_ms(cc_min):
    return cc_min * FUEL_RHO * 1000.0 / 60000.0


def main() -> int:
    print("=== HaniCore - the air/fuel model against a float reference ===\n")
    print("  image   %s" % PI.image().name)
    print("  sha256  %s\n" % PI.sha256())

    r = Fuel()

    # ---------------------------------------------- the return convention
    # 4.5 L V8 at 100 kPa: charge_x100 is about 66 700, which needs 17 bits.
    # If the halves were swapped this would read as something absurd.
    rho = r("hc_af_density_x1000", 1000, 2932)
    charge = r.u32("hc_af_charge_x100", rho, 562)
    check("a 32-bit return comes back as one number, not two halves",
          50000 < charge < 90000,
          "charge_x100 = %d (about 667 mg)" % charge)

    # -------------------------------------------------------- temperature
    print("\n--- charge temperature ---")
    for c_deg in (-30, 0, 20, 60, 120):
        iat_dc = int((c_deg + BIAS) * 10)
        got = r("hc_af_charge_t_x10", iat_dc)
        want = ref_t_x10(iat_dc) * 10.0
        check("%+4d degC -> %.1f K" % (c_deg, want / 10.0),
              abs(got - want) <= 1.0, "got %.1f K" % (got / 10.0))

    # ------------------------------------------------------------ density
    print("\n--- air density, 0.001 mg/cm3 ---")
    for map_x10, iat_c in ((1000, 20), (1000, -20), (300, 20), (2500, 50)):
        t_x10 = r("hc_af_charge_t_x10", int((iat_c + BIAS) * 10))
        got = r("hc_af_density_x1000", map_x10, t_x10)
        want = ref_rho(map_x10, t_x10 / 10.0)
        err = abs(got - want) / want * 100.0
        check("%.0f kPa at %+d degC -> %.0f" % (map_x10 / 10.0, iat_c, want),
              err < 0.5, "got %d, %.2f%% from the reference" % (got, err))

    # -------------------------------------------------- air mass and load
    print("\n--- cylinder air mass and relative charge ---")
    cases = [
        ("4.5 L V8, 100 kPa, 20 C, VE 100", 562, 1000, 20, 1000),
        ("same, VE 85",                     562, 1000, 20,  850),
        ("same at 30 kPa idle",             562,  300, 20, 1000),
        ("boosted 250 kPa, 50 C, VE 105",   562, 2500, 50, 1050),
        ("1.8 L four, 100 kPa, 20 C",       450, 1000, 20, 1000),
    ]
    for label, vd, map_x10, iat_c, ve_x10 in cases:
        t_x10 = r("hc_af_charge_t_x10", int((iat_c + BIAS) * 10))
        rho = r("hc_af_density_x1000", map_x10, t_x10)
        charge = r.u32("hc_af_charge_x100", rho, vd)
        air = r.u32a("hc_af_air_x100", charge, ve_x10)
        rl = r.u16a("hc_af_rl_x10", air, vd)

        want_air = ref_air_mg(map_x10, t_x10 / 10.0, vd, ve_x10)
        want_rl = ref_rl_pct(want_air, vd)
        e_air = abs(air / 100.0 - want_air) / want_air * 100.0
        e_rl = abs(rl / 10.0 - want_rl)
        check("%-34s air %.1f mg" % (label, want_air),
              e_air < 0.6, "got %.1f mg, %.2f%% out" % (air / 100.0, e_air))
        check("%-34s rl  %.1f %%" % ("", want_rl),
              e_rl < 0.5, "got %.1f %%" % (rl / 10.0))

    # ---------------------------------------------------------- fuel mass
    print("\n--- fuel mass ---")
    for air_mg, stoich, lam in ((667.6, 1470, 1000), (667.6, 1470, 850),
                                (667.6, 1470, 1150), (200.0, 906, 1000)):
        air_x100 = int(round(air_mg * 100))
        got = r.u32a("hc_af_fuel_x100", air_x100, stoich, lam)
        want = ref_fuel_mg(air_mg, stoich, lam)
        err = abs(got / 100.0 - want) / want * 100.0
        check("%.0f mg air, stoich %.2f, lambda %.3f -> %.2f mg"
              % (air_mg, stoich / 100.0, lam / 1000.0, want),
              err < 0.5, "got %.2f mg" % (got / 100.0))

    # --------------------------------------------------------- injector
    print("\n--- injector flow and open time ---")
    for cc in (220, 440, 630, 1000):
        got = r("hc_af_flow_x100", cc)
        want = ref_flow_mg_ms(cc) * 100.0
        err = abs(got - want) / want * 100.0
        check("%4d cc/min -> %.2f mg/ms" % (cc, want / 100.0),
              err < 0.5, "got %.2f mg/ms" % (got / 100.0))

    for fuel_mg, cc in ((45.4, 440), (2.0, 440), (120.0, 630)):
        flow = r("hc_af_flow_x100", cc)
        got = r.u16a("hc_af_te_us", int(round(fuel_mg * 100)), flow)
        want = fuel_mg / (flow / 100.0) * 1000.0
        err = abs(got - want) / want * 100.0
        check("%.1f mg through %d cc/min -> %.0f us" % (fuel_mg, cc, want),
              err < 0.5, "got %d us" % got)

    # ------------------------------------------------- pressure correction
    print("\n--- injector flow at a different differential pressure ---")
    base = r("hc_af_flow_x100", 440)
    for dp_x10, ref_x10, factor in ((3000, 3000, 1.0), (4000, 3000, None),
                                    (1500, 3000, None)):
        got = r("hc_af_flow_at_dp_x100", base, dp_x10, ref_x10)
        want = base * ((dp_x10 / ref_x10) ** 0.5)
        err = abs(got - want) / want * 100.0
        check("%.0f kPa against a %.0f kPa rating -> x%.3f"
              % (dp_x10 / 10.0, ref_x10 / 10.0, (dp_x10 / ref_x10) ** 0.5),
              err < 1.0, "got %.2f mg/ms, %.2f%% out" % (got / 100.0, err))
    check("a missing pressure configuration leaves the flow ALONE",
          r("hc_af_flow_at_dp_x100", base, 0, 3000) == base
          and r("hc_af_flow_at_dp_x100", base, 3000, 0) == base,
          "scaling fuel because a sensor is absent would be invisible")

    # --------------------------------------------------------- boundaries
    print("\n--- boundaries and refusals ---")
    check("stoich of zero yields NO fuel, not a divide",
          r.u32a("hc_af_fuel_x100", 66760, 0, 1000) == 0, "")
    check("lambda of zero yields NO fuel",
          r.u32a("hc_af_fuel_x100", 66760, 1470, 0) == 0, "")
    check("an injector that passes nothing yields no open time",
          r.u16a("hc_af_te_us", 4540, 0) == 0, "")
    check("no displacement means no load, not a divide",
          r.u16a("hc_af_rl_x10", 66760, 0) == 0, "")
    check("a freezing intake does not wrap the temperature",
          r("hc_af_charge_t_x10", int((-40 + BIAS) * 10)) > 2000,
          "%.1f K at -40 degC" % (r("hc_af_charge_t_x10",
                                    int((-40 + BIAS) * 10)) / 10.0))
    big = r.u32("hc_af_charge_x100",
                r("hc_af_density_x1000", 5000, 2200), 1500)
    check("the widest realistic engine does not overflow the charge step",
          0 < big < 2000000, "charge_x100 = %d at 500 kPa, -50 C, 1.5 L/cyl"
          % big)

    # ------------------------------------------------------ the whole chain
    print("\n--- the worked case end to end ---")
    t_x10 = r("hc_af_charge_t_x10", int((20 + BIAS) * 10))
    rho = r("hc_af_density_x1000", 1000, t_x10)
    charge = r.u32("hc_af_charge_x100", rho, 562)
    air = r.u32a("hc_af_air_x100", charge, 1000)
    rl = r.u16a("hc_af_rl_x10", air, 562)
    fuel = r.u32a("hc_af_fuel_x100", air, 1470, 1000)
    flow = r("hc_af_flow_x100", 440)
    te = r.u16a("hc_af_te_us", fuel, flow)
    print("    rho %.3f mg/cm3   air %.1f mg   rl %.1f %%   fuel %.2f mg"
          % (rho / 1000.0, air / 100.0, rl / 10.0, fuel / 100.0))
    print("    flow %.2f mg/ms   te %d us" % (flow / 100.0, te))
    check("the documented worked case still holds",
          abs(rl / 10.0 - 92.1) < 0.6 and abs(te - 8318) < 60,
          "rl %.1f %% (want 92.1), te %d us (want 8318)" % (rl / 10.0, te))
    check("and rl is NOT 100 %% at sea level, which is the ME7 definition",
          85.0 < rl / 10.0 < 96.0,
          "100 %% is referenced to 0 degC, not to ambient")

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("THE FIXED-POINT MODEL DISAGREES WITH THE PHYSICS.")
        return 1
    print("FUEL GOLDEN VECTORS PASS - every step matches the reference.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
