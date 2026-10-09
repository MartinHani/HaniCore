/*
 * hctrans711.c - transient fuel on ME7.1.1. The model is shared/
 * hctrans.c (host-tested against a wall-film plant); this file reads its
 * calibration from the page and gives it a time base.
 *
 * FAR (FCODE), compiled MOD167 MEDIUM with DEFINE(HC_FAR_BRIDGE): page reads
 * through hcfarinline.h (call-free), no ?C_ helper.
 *
 * THE TIME BASE IS T1 (1.25 MHz, hctarget.h TGT_TICKS_PER_MS_X10), read here:
 * eng_service() calls this every main-loop pass (worst gap ~9 ms, far inside
 * T1's 52 ms wrap) and the remainder below a millisecond is carried, so the
 * film is stepped by the time that really passed.
 */
#include "hcfarbridge.h"
#include <reg167.h>
#include "hctarget.h"
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hcfarinline.h"
#include "hctrigger.h"
#include "hcengine.h"
#include "hctrans711.h"

#define T1_PER_MS  ((unsigned int)(TGT_TICKS_PER_MS_X10 / 10uL))   /* 1250 */

typedef char hc_trans_fits[(sizeof(hc_trans711_t) <= TGT_RAM_TRANS_LIMIT)
                           ? 1 : -1];
#define t_last (HC_TRANS711.t_last)
#define t_rem  (HC_TRANS711.t_rem)

void far hc_trans_init(void)
{
    hctrans_reset(&hc_trans);
    t_last = T1;
    t_rem = 0u;
}

/* A u8 curve on the warm-up coolant axis (cltEnrAx), interpolated. */
static unsigned char curve8(unsigned int val_off, unsigned int clt)
{
    unsigned char i;
    unsigned int a0, a1;

    a0 = hc_cal_u16(CAL_CLT_ENR_AX);
    if (clt <= a0) {
        return hc_cal_u8(val_off);
    }
    for (i = 1u; i < CAL_AXIS_N; i++) {
        a1 = hc_cal_u16((unsigned int)(CAL_CLT_ENR_AX + 2u * i));
        if (clt < a1) {
            return hctrans_lerp8(a0, a1, hc_cal_u8((unsigned int)(val_off + i - 1u)),
                                 hc_cal_u8((unsigned int)(val_off + i)), clt);
        }
        a0 = a1;
    }
    return hc_cal_u8((unsigned int)(val_off + CAL_AXIS_N - 1u));
}

unsigned char far hc_trans_warmup(unsigned int clt_dc)
{
    unsigned char v = curve8(CAL_CLT_ENR_VAL, clt_dc);
    return (unsigned char)(v == 0u ? 100u : v);
}

unsigned int far hc_trans_fuel(unsigned int base_us, unsigned char cranking,
                               unsigned char cut)
{
    hctrans_in_t in;
    unsigned int now = T1;
    unsigned int d = (unsigned int)(now - t_last) + t_rem;
    unsigned int ms = (unsigned int)(d / T1_PER_MS);

    t_last = now;
    t_rem = (unsigned int)(d - ms * T1_PER_MS);
    if (ms > 200u) {
        ms = 200u;
    }
    if (hc_cal_u8(CFG_U_TRANS_ENABLE) == 0u) {
        hctrans_reset(&hc_trans);
        hc_trans.base = base_us;
        hc_trans.want = base_us;
        hc_trans.out = cut ? 0u : base_us;
        return hc_trans.out;
    }
    in.base_us = base_us;
    in.rpm = trg_rpm;
    in.dt_ms = ms;
    in.cranking = cranking;
    in.cut = cut;
    /* per-consumer fallbacks for a failed coolant sensor - the wall
       film as at 90 C (rusEFI wall_fuel.cpp computeTau/Beta), after-start
       as at 0 C (rusEFI getPostCrankingFuelCorrection, getOrZero) */
    {
        unsigned char bad = (unsigned char)((eng_sensor_err & ENG_ERR_CLT) != 0u);
        unsigned int c_film = bad ? (unsigned int)((90 + (int)CAL_TEMP_BIAS) * 10)
                                  : eng_clt_dc;
        unsigned int c_as = bad ? (unsigned int)((0 + (int)CAL_TEMP_BIAS) * 10)
                                : eng_clt_dc;
        in.x_pm = (unsigned int)(curve8(CFG_U_WW_X_PCT, c_film) * 10u);
        in.tau_ms = (unsigned int)(curve8(CFG_U_WW_TAU_20MS, c_film) * 20u);
        in.as_pm = (unsigned int)(curve8(CFG_U_AS_PCT, c_as) * 10u);
    }
    in.as_decay_ms = hc_cal_u16(CFG_U_AS_DECAY_MS);
    return hctrans_step(&hc_trans, &in);
}
