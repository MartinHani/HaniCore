/*
 * hcboost711.c - boost control on ME7.1.1: the page's tables, the
 * shared decision core (control/hcldr.c) and the overboost fuel cut.
 *
 * COMPILED MOD167 MEDIUM (FCODE) WITH hcfarbridge.h FIRST: the page reads
 * (hc_cal_*) go through the far thunks in hcfar_me711.c. The valve itself is
 * driven by the caller (hcmain_me711.c, near: hc_hal_out_duty), so no HAL
 * thunk is needed. Engine values are read from their globals.
 *
 * Until V97 the main loop computed open-loop duty only, in NCODE, and the
 * overboost limit only zeroed the valve: ENG_CUT_BOOST existed and nothing
 * on this board set or applied it. Now overboost is a FUEL CUT (rusEFI
 * boostCutPressure), judged whether or not boost control is enabled, and
 * closed loop (boostMode 1) runs the PID the page always carried.
 */
#include "hcfarbridge.h"
#include "hctarget.h"
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hctrigger.h"
#include "hcengine.h"
#include "hcldr.h"
#include "hcboost711.h"
#include "hcdeadline711.h"
#include "hcload711.h"

#define STEP_MS 20u                 /* the gains are per 20 ms step */

hcldr_t      hc_ldr;
unsigned int hc_ldr_target_x10;
unsigned int hc_ldr_open_x10;
static unsigned int acc_ms;
/* THE MAIN LOOP PASSES tick_ms - THE UPTIME, not an elapsed time (every
   service here takes now_ms, like hc_fuelpump_service()). V97 first passed
   it as elapsed ms: the controllers stepped on every pass with a huge dt,
   which me711_boot_test caught as a 34 % slower main loop. */
static unsigned int last_ms;
static unsigned char have_ms;

static unsigned int elapsed(unsigned int now_ms)
{
    unsigned int d = have_ms ? (unsigned int)(now_ms - last_ms) : 0u;
    last_ms = now_ms;
    have_ms = 1u;
    return d;
}

void far hc_boost_init(void)
{
    hcldr_reset(&hc_ldr);
    hc_ldr_target_x10 = 0u;
    hc_ldr_open_x10 = 0u;
    acc_ms = 0u;
    have_ms = 0u;
}

/* v x m %, m = 0 meaning 100 % (an unset curve). v is clamped to 1275 (a u8
   cell x5) and m to 500 %, so the quotient is <= 6375: unsigned x unsigned
   -> MULU and (unsigned)(ulong / 100) -> DIVLU, both inline (no ?C_ helper
   in far code - the project rules). */
static unsigned int mul100(unsigned int v, unsigned int m)
{
    if (m == 0u) return v;
    if (v > 1275u) v = 1275u;
    if (m > 500u) m = 500u;
    return (unsigned int)(((unsigned long)v * m) / 100u);
}

unsigned int far hc_boost_service(unsigned int now_ms, unsigned char keyoff)
{
    hcldr_cfg_t c;
    hcldr_in_t in;
    unsigned int open;

    acc_ms += elapsed(now_ms);
    /* Revocation runs on every call, before the 20 ms controller cadence.
       A cached nonzero duty must not survive loss of pressure authority. */
    if (keyoff || (eng_sensor_err & ENG_ERR_MAP)
        || (eng_fuelcut & (ENG_CUT_LOAD | ENG_CUT_LEAN))
        || (hc_cal_u8(CFG_U_FUEL_MODEL) && (!HC_LOAD.role || !HC_LOAD.pressure_ok))) {
        hc_ldr.duty_x10 = 0u;
        hc_ldr.integ100 = 0L;
        hc_ldr.p_x10 = hc_ldr.i_x10 = hc_ldr.d_x10 = 0;
        hc_ldr.have_last = 0u;
        hc_ldr.state = (eng_sensor_err & ENG_ERR_MAP)
            || (hc_cal_u8(CFG_U_FUEL_MODEL) && !HC_LOAD.pressure_ok)
            ? HCLDR_S_SENSOR : HCLDR_S_OFF;
        return 0u;
    }
    if (acc_ms < STEP_MS) return hc_ldr.duty_x10;
    acc_ms = (acc_ms >= 2u * STEP_MS) ? 0u : (unsigned int)(acc_ms - STEP_MS);

    c.closed = (unsigned char)(hc_cal_u8(CAL_BOOST_MODE) == HC_BOOST_CLOSED_LOOP);
    c.min_rpm = hc_cal_u16(CAL_BOOST_MIN_RPM);
    c.min_tps_x10 = hc_cal_u16(CAL_BOOST_MIN_TPS_X10);
    c.cl_min_map_x10 = hc_cal_u16(CFG_U_BOOST_CL_MIN_X10);
    c.kp = hc_cal_u16(CAL_BOOST_KP);
    c.ki = hc_cal_u16(CAL_BOOST_KI);
    c.kd = hc_cal_u16(CAL_BOOST_KD);
    c.i_band_x10 = hc_cal_u16(CFG_U_BOOST_I_BAND_X10);
    c.cut_x10 = hc_cal_u16(CAL_BOOST_CUT_KPA);
    c.hyst_x10 = hc_cal_u16(CAL_BOOST_CUT_HYST);

    /* open loop: the duty map (u8, 0.5 %) with the CLT and IAT multipliers
       (percent, 0 = 1.00), clamped by the core */
    open = (unsigned int)hc_cal_map(CAL_BOOST_DUTY_MAP, CAL_BOOST_RPM_AX,
                                    CAL_BOOST_TPS_AX, trg_rpm, eng_tps_x10) * 5u;
    /* a failed sensor's multiplier is not applied (rusEFI
       getBoostTemperatureCorrection() returns nothing) - never the -40 C
       display value's cell. */
    if (!(eng_sensor_err & ENG_ERR_CLT)) {
        open = mul100(open, hc_cal_curve16(CAL_BOOST_CLT_AX, CAL_BOOST_CLT_MUL, 8u, eng_clt_dc));
    }
    if (!(eng_sensor_err & ENG_ERR_IAT)) {
        open = mul100(open, hc_cal_curve16(CAL_BOOST_IAT_AX, CAL_BOOST_IAT_MUL, 8u, eng_iat_dc));
    }
    hc_ldr_open_x10 = open;
    hc_ldr_target_x10 = (unsigned int)hc_cal_map(CAL_BOOST_TGT_MAP, CAL_BOOST_TGT_RPM_AX,
                                                 CAL_BOOST_TGT_TPS_AX, trg_rpm,
                                                 eng_tps_x10) * 10u;

    in.rpm = trg_rpm;
    in.tps_x10 = eng_tps_x10;
    in.map_x10 = eng_map_kpa_x10;
    in.map_ok = (unsigned char)((eng_sensor_err & ENG_ERR_MAP) == 0u);
    in.enabled = (unsigned char)(hc_cal_u8(CAL_BOOST_ENABLE) == 1u
        && !(eng_fuelcut & (ENG_CUT_LOAD|ENG_CUT_LEAN))
        && (hc_cal_u8(CFG_U_FUEL_MODEL)==0u || hc_cal_u8(CFG_U_PRESSURE_ROLE)!=0u));
    in.keyoff = keyoff;
    in.open_x10 = open;
    in.target_x10 = hc_ldr_target_x10;
    (void)hcldr_step(&hc_ldr, &c, &in);

    /* this module's own bit of the shared cut word (see hcengine.c) */
    eng_fuelcut = (unsigned int)((eng_fuelcut & ~ENG_CUT_BOOST)
                                 | (hc_ldr.cut ? ENG_CUT_BOOST : 0u));
    if(hc_ldr.cut) hc_deadline_fuel_cut();
    return hc_ldr.duty_x10;
}
