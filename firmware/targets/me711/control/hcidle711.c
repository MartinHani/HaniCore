/*
 * hcidle711.c - idle speed control on ME7.1.1: the page's coolant
 * curves and the shared core (control/hcidle.c) produce a THROTTLE FLOOR;
 * hc_dbw.c raises its pedal demand to it (want = max(pedal map, floor)).
 *
 * COMPILED MOD167 MEDIUM (FCODE) WITH hcfarbridge.h FIRST (page reads and
 * hc_dbw_pedal_x10 through the far thunks in hcfar_me711.c).
 *
 * Until V97 nothing read CAL_IDLE_*: idle air was the pedal map at 0 %
 * pedal, floored by dbwMinX10. With idleEnable 0 (every preset) the floor
 * is 0 and hc_dbw.c behaves exactly as before.
 */
#include "hcfarbridge.h"
#include "hctarget.h"
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hctrigger.h"
#include "hcengine.h"
#include "hc_dbw.h"
#include "hcidle.h"
#include "hcidle711.h"
#include "hcengctl711.h"   /* anti-lag throttle add */

#define STEP_MS 20u
#define PEDAL_DEFAULT_X10  20u   /* rusEFI idlePidDeactivationTpsThreshold 2 % */
#define START_DEFAULT_MS 1000u

/* the timing state lives in external SRAM: the far modules' XRAM is full */
#define IGNIDLE (*(hcidle_timing_t huge *)(TGT_EXTRAM_BASE + TGT_RAM_IGNIDLE))

hcidle_t     hc_idl;
unsigned int hc_idle_floor_x10;
unsigned int hc_idle_target_rpm;
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

void far hc_idle_init(void)
{
    hcidle_reset(&hc_idl);
    IGNIDLE.closed_ms = 0u;          /* ?C_INIT never runs; SRAM keeps junk */
    IGNIDLE.out_x10 = 0;
    hc_idle_floor_x10 = 0u;
    hc_idle_target_rpm = 0u;
    acc_ms = 0u;
    have_ms = 0u;
}

void far hc_idle_service(unsigned int now_ms)
{
    unsigned int ms;
    unsigned int clt;
    hcidle_cfg_t c;
    hcidle_in_t in;
    unsigned int v;

    acc_ms += elapsed(now_ms);
    if (acc_ms < STEP_MS) return;
    ms = acc_ms;
    acc_ms = 0u;

    c.enabled = (unsigned char)(hc_cal_u8(CAL_IDLE_ENABLE) == 1u);
    c.kp = hc_cal_u16(CAL_IDLE_KP);
    c.ki = hc_cal_u16(CAL_IDLE_KI);
    c.range_x10 = hc_cal_u16(CAL_IDLE_RANGE_X10);
    c.band_rpm = hc_cal_u16(CAL_IDLE_RPM_BAND);
    v = hc_cal_u16(CFG_U_IDLE_PEDAL_X10);
    c.pedal_x10 = v ? v : PEDAL_DEFAULT_X10;
    v = hc_cal_u16(CFG_U_IDLE_START_MS);
    c.start_ms = v ? v : START_DEFAULT_MS;
    c.dash_x10 = hc_cal_u16(CFG_U_IDLE_DASH_X10);
    c.dash_hold_ms = hc_cal_u16(CFG_U_IDLE_DASH_HOLD_MS);
    c.dash_decay_ms = hc_cal_u16(CFG_U_IDLE_DASH_DECAY_MS);

    /* a failed coolant sensor idles as at 0 C - "a safe highish
       idle" (rusEFI IdleController, Sensor::getOrZero(Clt)); the displayed
       -40 C is not a control value. */
    clt = (eng_sensor_err & ENG_ERR_CLT) ? ((unsigned int)((0 + (int)CAL_TEMP_BIAS) * 10)) : eng_clt_dc;
    hc_idle_target_rpm = hc_cal_curve16(CAL_IDLE_TARGET_AX, CAL_IDLE_TARGET_VAL, 8u,
                                        clt);
    in.rpm = trg_rpm;
    in.target_rpm = hc_idle_target_rpm;
    in.base_x10 = hc_cal_curve16(CAL_IDLE_BASE_AX, CAL_IDLE_BASE_VAL, 8u, clt);
    in.pedal_x10 = hc_dbw_pedal_x10();
    in.cranking = eng_cranking;
    hc_idle_floor_x10 = hcidle_step(&hc_idl, &c, &in, ms);
    /* anti-lag opens the throttle by its own amount (rusEFI
       ALSEtbAdd) while it is active - hcengctl711.c decides when. */
    if (HC_EC.als) {
        hc_idle_floor_x10 = (unsigned int)(hc_idle_floor_x10
                            + (unsigned int)(hc_cal_u8(CFG_U_ALS_THROTTLE) * 10u));
    }

    /* idle ignition timing, only while the loop above is CLOSED */
    {
        hcidle_tcfg_t tc;
        tc.enabled = (unsigned char)(hc_cal_u8(CFG_U_IDLE_TIM_EN) == 1u);
        tc.kp_x10 = hc_cal_u16(CFG_U_IDLE_TIM_KP);
        tc.min_x10 = (int)hc_cal_u16(CFG_U_IDLE_TIM_MIN);
        tc.max_x10 = (int)hc_cal_u16(CFG_U_IDLE_TIM_MAX);
        tc.soft_ms = hc_cal_u16(CFG_U_IDLE_TIM_SOFT_MS);
        (void)hcidle_timing_step(&IGNIDLE, &tc,
                                 (unsigned char)(hc_idl.state & HCIDLE_S_CLOSED),
                                 in.rpm, in.target_rpm, ms);
    }
}

int far hc_idle_timing_x10(void)
{
    return IGNIDLE.out_x10;
}
