/*
 * hc_airfuel.h - the air and fuel model, as separable arithmetic.
 *
 * WHY THIS IS A MODULE OF PURE FUNCTIONS.
 *
 * The fuel calculation is where a wrong number does not announce itself: an
 * overflow, a truncation or a swapped scale produces a plausible pulse width
 * and a burnt piston. Every step below is therefore a function with explicit
 * units in its name, callable on its own, so a golden-vector test can compare
 * each one against a high-precision reference instead of only checking the
 * answer at the end. tools/me711_fuel_golden.py does exactly that.
 *
 * WHAT REPLACED WHAT. Before this module, CAL_FUEL_MAP held a byte of PULSE
 * WIDTH - one count was 32 us - and eng_load was raw manifold pressure in
 * 0.1 kPa. There was no volumetric efficiency, no displacement, no injector
 * size and no lambda in the fuel path at all; lambda was computed and only
 * published. That is a table of answers, not a model, and it cannot respond to
 * a fuel pressure sensor, a different injector, or a change of displacement.
 *
 * THE MODEL IS ME7'S, THE UNITS ARE OURS. Bosch's own quantity is `rl`,
 * relative Luftfuellung, quantized at 0.0234375 %/LSB and referenced to the
 * cylinder charge at 0 degC and 1013 hPa. HaniCore uses the same DEFINITION
 * with a decimal quantization - 0.1 % - because a tuner can check 0.1 % by
 * hand and cannot check 0.0234375.
 *
 * NO FLOAT ANYWHERE. Every intermediate is unsigned long, and every function
 * below states the widest input it survives. See the range notes on each.
 */
#ifndef HC_AIRFUEL_H
#define HC_AIRFUEL_H

/* Air density in the cylinder, 0.001 mg/cm3.
 *
 *   rho = MAP / (R_air * T),  R_air = 287.05 J/(kg K)
 *
 * map_x10   manifold pressure, 0.1 kPa      (realistic max 5000 = 500 kPa)
 * t_x10     charge temperature, 0.1 K       (must be non-zero)
 * returns   0.001 mg/cm3, about 1188 at 100 kPa and 20 degC
 *
 * 3484 is 1000/0.28705, folded so the whole thing is one multiply and one
 * divide. Widest case 5000*3484/2200 = 7918, so the result fits 16 bits.
 */
unsigned int hc_af_density_x1000(unsigned int map_x10, unsigned int t_x10);

/* Charge temperature in 0.1 K from the engine's biased 0.1 degC reading.
 * eng_iat_dc is (degC + CAL_TEMP_BIAS) * 10, which is how this firmware
 * carries a signed temperature in an unsigned word. */
unsigned int hc_af_charge_t_x10(unsigned int iat_dc);

/* Cylinder air mass at 100 % volumetric efficiency, 0.01 mg.
 * rho_x1000 from above, vd_cc = swept volume of ONE cylinder in cm3.
 * Widest case 7918*1500/10 = 1 187 700, comfortably inside 32 bits. */
unsigned long hc_af_charge_x100(unsigned int rho_x1000, unsigned int vd_cc);

/* Cylinder air mass with volumetric efficiency applied, 0.01 mg.
 * ve_x10 is 0.1 %, so 1000 is 100.0 %. */
unsigned long hc_af_air_x100(unsigned long charge_x100, unsigned int ve_x10);
/* the VE field's upper limit (CAL_FUEL_MAP, 400.0 %); callers clamp to it,
   which keeps hc_af_air_x100 inside 32 bits */
#define VE_MAX_X10  4000u

/* Relative air charge, 0.1 %. THIS IS HANICORE'S CANONICAL LOAD.
 *
 * 100.0 % is the charge that fills the swept volume at 0 degC and 1013 hPa,
 * where dry air is 1.2929 mg/cm3 - ME7's reference condition, which is why a
 * naturally aspirated engine reads about 92 % at sea level and 20 degC rather
 * than 100 %. That is not an error to be trimmed out; it is the definition.
 */
unsigned int hc_af_rl_x10(unsigned long air_x100, unsigned int vd_cc);

/* Fuel mass for that air mass, 0.01 mg.
 * stoich_x100   14.70 is 1470
 * lambda_x1000  1.000 is 1000; smaller is richer
 * Both are refused if zero - hc_validate() rejects such a page, but this runs
 * on whatever the page says and must not divide by it. */
unsigned long hc_af_fuel_x100(unsigned long air_x100,
                              unsigned int stoich_x100,
                              unsigned int lambda_x1000);

/* Injector mass flow at its RATED pressure, 0.01 mg/ms.
 * cc_min is the usual datasheet number. 745 is petrol at 0.745 g/cm3.
 * 440 cc/min gives 546, i.e. 5.46 mg/ms. */
unsigned int hc_af_flow_x100(unsigned int cc_min);

/* The same injector at a DIFFERENT differential pressure, 0.01 mg/ms.
 *
 *   flow scales with sqrt(dP / dP_ref)
 *
 * An integer square root, bounded at 16 iterations, computed once per fuel
 * update and never inside an interrupt. Returns the reference flow unchanged
 * when either pressure is zero, because a missing fuel-pressure configuration
 * must not silently scale the fuel to nothing. */
unsigned int hc_af_flow_at_dp_x100(unsigned int flow_ref_x100,
                                   unsigned int dp_x10,
                                   unsigned int dp_ref_x10);

/* Effective injector OPEN time for that fuel mass, microseconds.
 * This is ME7's `te`: the time the valve must be open. It is NOT what the
 * driver stage is told - dead time is added afterwards, and never scaled. */
unsigned int hc_af_te_us(unsigned long fuel_x100, unsigned int flow_x100);

/* Bounded integer square root, exported because the golden vectors check it
 * on its own. */
unsigned long hc_af_isqrt(unsigned long v);

#endif /* HC_AIRFUEL_H */
