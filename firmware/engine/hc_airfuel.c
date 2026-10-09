/*
 * hc_airfuel.c - the air and fuel model. Read hc_airfuel.h first.
 *
 * Every function here is pure: same inputs, same answer, no globals, no
 * configuration reads. That is what makes the golden-vector test able to
 * compare each step against a high-precision reference rather than only
 * checking the pulse width at the end.
 */
#include "hcconfig.h"
#include "hc_airfuel.h"

/* Air at 0 degC and 1013.25 hPa is 1.2929 mg/cm3. ME7's `rl` is referenced to
   exactly this, which is why 100 % relative charge is NOT what an engine
   breathes at sea level on a warm day. 129 is that density in the 0.01 mg
   units the charge calculation carries. */
#define RHO_REF_X100    129u

/* 1000 / 0.28705, so density is one multiply and one divide. */
#define R_AIR_RECIP     3484u

/* Petrol density, 0.745 g/cm3, scaled so cc/min becomes 0.01 mg/ms:
     mg/ms = cc_min * 0.745 * 1000 / 60000 = cc_min * 745 / 60000
     0.01 mg/ms = cc_min * 745 / 600                                        */
#define FUEL_RHO_NUM    745u
#define FUEL_RHO_DEN    600u

/* Below this the arithmetic stops meaning anything and a divide would trap. */
#define T_X10_MIN       1000u      /* 100 K - colder than any real intake   */


unsigned int hc_af_charge_t_x10(unsigned int iat_dc)
{
    /* eng_iat_dc is (degC + CAL_TEMP_BIAS) * 10. Kelvin is degC + 273.15, so
       0.1 K = iat_dc - CAL_TEMP_BIAS*10 + 2732. Done in one signed step so an
       intake below freezing does not wrap on the way through. */
    long c_x10 = (long)iat_dc - ((long)CAL_TEMP_BIAS * 10L);
    long k_x10 = c_x10 + 2732L;

    if (k_x10 < (long)T_X10_MIN) {
        k_x10 = (long)T_X10_MIN;
    }
    if (k_x10 > 65535L) {
        k_x10 = 65535L;
    }
    return (unsigned int)k_x10;
}


unsigned int hc_af_density_x1000(unsigned int map_x10, unsigned int t_x10)
{
    unsigned long d;

    if (t_x10 < T_X10_MIN) {
        t_x10 = T_X10_MIN;
    }
    /* 5000 * 3484 = 17 420 000: well inside 32 bits before the divide. */
    d = ((unsigned long)map_x10 * (unsigned long)R_AIR_RECIP)
        / (unsigned long)t_x10;
    if (d > 65535uL) {
        d = 65535uL;
    }
    return (unsigned int)d;
}


unsigned long hc_af_charge_x100(unsigned int rho_x1000, unsigned int vd_cc)
{
    /* rho is 0.001 mg/cm3 and we want 0.01 mg, so multiply by volume and
       divide by 10. 7918 * 1500 / 10 = 1 187 700. */
    return ((unsigned long)rho_x1000 * (unsigned long)vd_cc) / 10uL;
}


unsigned long hc_af_air_x100(unsigned long charge_x100, unsigned int ve_x10)
{
    /* 1 187 700 * 2000 would be 2.4e9 - inside 32 bits, but only just, so the
       divide is folded in rather than left to a later step. */
    /* VE reaches 400.0 % (ve_x10 4000, VE_MAX_X10). Above 1.0e6
       the product would pass 32 bits - take the 0.1 mg step out first. */
    if (charge_x100 > 1000000uL) {
        return ((charge_x100 / 10uL) * (unsigned long)ve_x10) / 100uL;
    }
    return (charge_x100 * (unsigned long)ve_x10) / 1000uL;
}


unsigned int hc_af_rl_x10(unsigned long air_x100, unsigned int vd_cc)
{
    unsigned long ref = (unsigned long)vd_cc * (unsigned long)RHO_REF_X100;
    unsigned long rl;

    if (ref == 0uL) {
        return 0u;              /* no displacement configured: no load */
    }
    /* air_x100 realistically peaks near 2.4e6; times 1000 is 2.4e9, which
       fits, but a wild configuration could push it further, so the divide is
       done against a value that cannot be zero and the result is clamped. */
    if (air_x100 > 4000000uL) {
        air_x100 = 4000000uL;
    }
    rl = (air_x100 * 1000uL) / ref;
    if (rl > 65535uL) {
        rl = 65535uL;
    }
    return (unsigned int)rl;
}


unsigned long hc_af_fuel_x100(unsigned long air_x100,
                              unsigned int stoich_x100,
                              unsigned int lambda_x1000)
{
    unsigned long a;

    if (stoich_x100 == 0u || lambda_x1000 == 0u) {
        /* hc_validate() refuses a page containing either, but this runs on
           whatever the page actually says. Returning zero fuel is the safe
           direction: an engine that will not start is recoverable, one that
           floods on a divide-by-zero is not. */
        return 0uL;
    }
    /* Two divides rather than one, so the intermediate never exceeds 32 bits:
       air 2.4e6 * 100 = 2.4e8, then / stoich, then * 1000 stays bounded. */
    a = (air_x100 * 100uL) / (unsigned long)stoich_x100;
    return (a * 1000uL) / (unsigned long)lambda_x1000;
}


unsigned int hc_af_flow_x100(unsigned int cc_min)
{
    unsigned long f = ((unsigned long)cc_min * (unsigned long)FUEL_RHO_NUM)
                      / (unsigned long)FUEL_RHO_DEN;
    if (f > 65535uL) {
        f = 65535uL;
    }
    return (unsigned int)f;
}


unsigned long hc_af_isqrt(unsigned long v)
{
    /* Bit-by-bit integer square root. Bounded at 16 iterations, no division,
       no loop whose length depends on the value. */
    unsigned long rem = 0uL, root = 0uL;
    unsigned char i;

    for (i = 0u; i < 16u; i++) {
        root <<= 1;
        rem = (rem << 2) | ((v >> 30) & 3uL);
        v <<= 2;
        if (root < rem) {
            root++;
            rem -= root;
            root++;
        }
    }
    return root >> 1;
}


unsigned int hc_af_flow_at_dp_x100(unsigned int flow_ref_x100,
                                   unsigned int dp_x10,
                                   unsigned int dp_ref_x10)
{
    unsigned long ratio, f;

    if (dp_x10 == 0u || dp_ref_x10 == 0u) {
        /* No fuel-pressure configuration, or none measured. Use the rated
           flow unchanged: silently scaling the fuel because a sensor is
           absent is exactly the kind of invisible wrongness this module
           exists to avoid. */
        return flow_ref_x100;
    }
    /* sqrt(dp/dp_ref) in fixed point: work in 1/65536 of the ratio, take the
       root, and the root of 65536 is 256 - so the scale comes back out by a
       shift rather than another divide. */
    ratio = ((unsigned long)dp_x10 << 16) / (unsigned long)dp_ref_x10;
    if (ratio > 0x00FFFFFFuL) {
        ratio = 0x00FFFFFFuL;          /* 256x pressure: absurd, but bounded */
    }
    f = ((unsigned long)flow_ref_x100 * hc_af_isqrt(ratio)) >> 8;
    if (f > 65535uL) {
        f = 65535uL;
    }
    return (unsigned int)f;
}


unsigned int hc_af_te_us(unsigned long fuel_x100, unsigned int flow_x100)
{
    unsigned long t;

    if (flow_x100 == 0u) {
        return 0u;              /* an injector that passes nothing */
    }
    /* fuel_x100 is 0.01 mg and flow is 0.01 mg/ms, so the quotient is ms;
       times 1000 gives microseconds. The multiply is done first because the
       quotient would otherwise truncate to whole milliseconds. A realistic
       fuel_x100 is under 30 000 (300 mg), so 3e7 is the widest intermediate. */
    if (fuel_x100 > 200000uL) {
        fuel_x100 = 200000uL;   /* 2 g in one shot: bounded, not believed */
    }
    t = (fuel_x100 * 1000uL) / (unsigned long)flow_x100;
    if (t > 65535uL) {
        t = 65535uL;
    }
    return (unsigned int)t;
}
