/*
 * hcigncorr711.c - ignition timing corrections: coolant and intake
 * air, rusEFI's ignitionCltCorr / ignitionIatCorr (1D here). FAR (FCODE),
 * MOD167 MEDIUM with DEFINE(HC_FAR_BRIDGE); page reads through
 * hcfarinline.h. Added to the table advance by eng_service() while running.
 *
 * Interpolation in 16 bits: the values are bounded to +/-30.0 deg by the
 * model, so |v1 - v0| <= 600 and (|v1 - v0| * d) / span is a 32/16 division
 * with a 16-bit quotient (no ?C_ helper; me711_far_boundary_proof reads the
 * image).
 */
#include "hcfarbridge.h"
#include "hctarget.h"
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hcfarinline.h"
#include "hcigncorr711.h"
#include "hcidle711.h"

static int lerp16(unsigned int x0, unsigned int x1, int v0, int v1,
                  unsigned int x)
{
    unsigned int span, d, mag;

    if (x1 <= x0 || x <= x0) {
        return v0;
    }
    if (x >= x1) {
        return v1;
    }
    span = (unsigned int)(x1 - x0);
    d = (unsigned int)(x - x0);
    if (v1 >= v0) {
        mag = (unsigned int)((unsigned long)(unsigned int)(v1 - v0) * d / span);
        return (int)(v0 + (int)mag);
    }
    mag = (unsigned int)((unsigned long)(unsigned int)(v0 - v1) * d / span);
    return (int)(v0 - (int)mag);
}

static int curve(unsigned int ax, unsigned int val, unsigned char n,
                 unsigned int x)
{
    unsigned char i;
    unsigned int a0 = hc_cal_u16(ax), a1;

    if (x <= a0) {
        return (int)hc_cal_u16(val);
    }
    for (i = 1u; i < n; i++) {
        a1 = hc_cal_u16((unsigned int)(ax + 2u * i));
        if (x < a1) {
            return lerp16(a0, a1,
                          (int)hc_cal_u16((unsigned int)(val + 2u * (i - 1u))),
                          (int)hc_cal_u16((unsigned int)(val + 2u * i)), x);
        }
        a0 = a1;
    }
    return (int)hc_cal_u16((unsigned int)(val + 2u * (n - 1u)));
}

static int bound(int v)
{
    return (v > 300) ? 300 : (v < -300) ? -300 : v;
}

int far hc_ign_corr_x10(unsigned int clt_dc, unsigned int iat_dc)
{
    /* 0 = that sensor has failed - its correction is 0 (rusEFI
       getCltTimingCorrection / IAT), never the -40 C display value's cell */
    int c = clt_dc ? bound(curve(CAL_CLT_ENR_AX, CFG_U_IGN_CLT_CORR, CAL_AXIS_N, clt_dc)) : 0;
    int a = iat_dc ? bound(curve(CFG_U_IGN_IAT_AX, CFG_U_IGN_IAT_CORR, 8u, iat_dc)) : 0;
    int i = bound(hc_idle_timing_x10());   /* 0 outside closed-loop idle */
    return (int)(c + a + i);
}
