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
 *
 * THE IDLE AIR VALVE (2026-10-31, cable throttle; rusEFI idle solenoid +
 * secondary solenoid): with idleActuator 1/2 the same position is a valve
 * duty on the main CPU's POUT0/POUT1 (the cavities hcvvt711.c uses), and
 * "pedal released" is the TPS - the validator refuses a valve while DBW is
 * enabled, so hc_dbw.c never applies this position to a throttle too.
 */
#include "hcfarbridge.h"
#include <reg167.h>
#include "hctarget.h"
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hctrigger.h"
#include "hcengine.h"
#include "hc_dbw.h"
#include "hcidle.h"
#include "hcidle711.h"
#include "hcengctl711.h"   /* anti-lag throttle add */
#include "hcaux711.h"      /* fan, A/C (idle-up), outputs, oil pressure */
#include "hcsafety.h"
#include "hcbench.h"
#include "hcxfn711.h"     /* 2026-11-03: ignition-first idle, kicks, adaptation */

#define STEP_MS 20u
#define PEDAL_DEFAULT_X10  20u   /* rusEFI idlePidDeactivationTpsThreshold 2 % */
#define START_DEFAULT_MS 1000u
#define IDLE_TRIM_MAX_X10 100u   /* +-10 % of throttle travel, whatever the page */
#define VALVE_DEFAULT_HZ 200u    /* rusEFI idle.solenoidFrequency */

/* the timing state and the valve's units live in external SRAM: the far
   modules' XRAM is full */
typedef struct {
    hcidle_timing_t tim;
    unsigned char   drv;         /* bit0 POUT0, bit1 POUT1: the valve drives it */
    unsigned char   pad;
    int             out_x;       /* the idle spark correction in force (P + I,
                                    faded) - hcxfn711.c, 2026-11-03 */
} hc_idle711_t;
typedef char hc_idle711_fits[(sizeof(hc_idle711_t) <= TGT_RAM_IGNIDLE_LIMIT) ? 1 : -1];
#define IDLE711 (*(hc_idle711_t huge *)(TGT_EXTRAM_BASE + TGT_RAM_IGNIDLE))
#define IGNIDLE IDLE711.tim

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

/* ------------------------------------------------- the idle air valve -- */
/* POUT0 / POUT1 exactly as hcvvt711.c drives them: fCPU/64, the stage ON
   while PT < PW (the CJ920 inverts; latch 0); released = input, stage off.
   A 3-wire valve's second coil runs on the other unit with the SAME period
   and duty and its latch 1 - the pin is POUT XOR latch, so it is the exact
   complement, both timers started together. Constant masks: every port
   write is one bit instruction. */
static void unit_off(unsigned char u)
{
    if (u) {
        PWMCON1 &= (unsigned int)~0x0002u;   /* the pin is the latch again */
        DP7 &= (unsigned int)~0x0002u;       /* released: stage OFF        */
        P7 &= (unsigned int)~0x0002u;        /* latch back to 0            */
        PWMCON0 &= (unsigned int)~0x0022u;   /* timer stopped              */
    } else {
        PWMCON1 &= (unsigned int)~0x0001u;
        DP7 &= (unsigned int)~0x0001u;
        P7 &= (unsigned int)~0x0001u;
        PWMCON0 &= (unsigned int)~0x0011u;
    }
}

static unsigned char unit_of(unsigned char cav)
{
    return (cav == TGT_POUT0_CAV) ? 0u : (cav == TGT_POUT1_CAV) ? 1u : 0xFFu;
}

static void valve_service(unsigned int duty_x10)
{
    unsigned char act = hc_cal_u8(CFG_U_IDLE_ACTUATOR);
    unsigned char want = 0u, inv = 0u, u;
    unsigned int f, pp, pw;

    /* the ALWAYS set (page valid, S5500 link, key on - as the fuel pump and
       hcaux711.c); a bench test owns the outputs while it runs */
    if ((hc_safety_inhibits & HC_INHIBIT_ALWAYS) == 0u && hcb_state != HCB_RUNNING
        && (act == 1u || act == 2u)) {
        u = unit_of(hc_cal_u8(CFG_U_PIN_IDLE_VALVE));
        if (u != 0xFFu) want = (unsigned char)(1u << u);
        if (act == 2u) {
            u = unit_of(hc_cal_u8(CFG_U_PIN_IDLE_VALVE2));
            if (u != 0xFFu && !(want & (1u << u))) {
                inv = (unsigned char)(1u << u);
                want |= inv;
            }
        }
    }
    /* a change of units restarts both together (the 3-wire pair stays in
       phase); nothing more owned is released */
    if (want != IDLE711.drv) {
        if (IDLE711.drv & 1u) unit_off(0u);
        if (IDLE711.drv & 2u) unit_off(1u);
        IDLE711.drv = 0u;
    }
    if (want == 0u) return;

    f = (unsigned int)(hc_cal_u8(CFG_U_IDLE_VALVE_FREQ) * 10u);
    if (f == 0u) f = VALVE_DEFAULT_HZ;
    if (f < 20u) f = 20u;
    if (f > 1000u) f = 1000u;
    /* fCPU/64 counts per period: 3125 x 10 at 200 Hz / 40 MHz */
    pp = (unsigned int)(((unsigned int)(TGT_PWM_SLOW_HZ / 10uL) / f) * 10u);
    if (duty_x10 > 1000u) duty_x10 = 1000u;
    pw = (unsigned int)((unsigned long)duty_x10 * pp / 1000u);
    if (want & 1u) { PP0 = (unsigned int)(pp - 1u); PW0 = pw; }
    if (want & 2u) { PP1 = (unsigned int)(pp - 1u); PW1 = pw; }
    if (IDLE711.drv == 0u) {
        if (want & 1u) { if (inv & 1u) P7 |= 0x0001u; else P7 &= (unsigned int)~0x0001u; PT0 = 0u; }
        if (want & 2u) { if (inv & 2u) P7 |= 0x0002u; else P7 &= (unsigned int)~0x0002u; PT1 = 0u; }
        PWMCON0 |= (unsigned int)(want | (want << 4));   /* run, fCPU/64 */
        PWMCON1 |= (unsigned int)want;                   /* POUTx drives */
        DP7 |= (unsigned int)want;
        IDLE711.drv = want;
    }
}

void far hc_idle_init(void)
{
    hcidle_reset(&hc_idl);
    IGNIDLE.closed_ms = 0u;          /* ?C_INIT never runs; SRAM keeps junk */
    IGNIDLE.out_x10 = 0;
    IDLE711.drv = 0u;                /* hc_hal_init() released every output */
    IDLE711.out_x = 0;
    hc_idle_floor_x10 = 0u;
    hc_idle_target_rpm = 0u;
    acc_ms = 0u;
    have_ms = 0u;
    hc_aux_init();
}

void far hc_idle_service(unsigned int now_ms)
{
    unsigned int ms;
    unsigned int clt;
    hcidle_cfg_t c;
    hcidle_in_t in;
    unsigned int v;

    /* the auxiliary functions first: the A/C idle-up is an input here */
    hc_aux_service(now_ms);
    acc_ms += elapsed(now_ms);
    if (acc_ms < STEP_MS) return;
    ms = acc_ms;
    acc_ms = 0u;

    c.enabled = (unsigned char)(hc_cal_u8(CAL_IDLE_ENABLE) == 1u);
    c.kp = hc_cal_u16(CAL_IDLE_KP);
    c.ki = hc_cal_u16(CAL_IDLE_KI);
    c.range_x10 = hc_cal_u16(CAL_IDLE_RANGE_X10);
    /* THE TRIM NEVER MOVES THE THROTTLE MORE THAN IDLE_TRIM_MAX_X10 of its
       travel (2026-10-15, car): hc_dbw.c applies the idle position x
       etbIdleRange %, so the authority is capped in throttle terms. The
       morning's page (authority 100 %, etbIdleRange 100) let the trim open
       the throttle fully with the pedal released. */
    {
        unsigned int rng = hc_cal_u8(CFG_U_IDLE_ETB_RANGE);
        unsigned int cap;
        if (rng == 0u || rng > 100u) rng = 100u;
        cap = (unsigned int)(IDLE_TRIM_MAX_X10 * 100u / rng);
        if (c.range_x10 > cap) c.range_x10 = cap;
    }
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
                                        clt)
                       + hc_aux_idle_rpm();        /* A/C requested */
    in.rpm = trg_rpm;
    in.target_rpm = hc_idle_target_rpm;
    in.base_x10 = hc_cal_curve16(CAL_IDLE_BASE_AX, CAL_IDLE_BASE_VAL, 8u, clt);
    /* a cable throttle has no pedal sensor: the TPS says released (as
       hclimp711.c) */
    in.pedal_x10 = (hc_cal_u8(CAL_DBW_ENABLE) != 0u) ? hc_dbw_pedal_x10()
                                                     : eng_tps_x10;
    in.cranking = eng_cranking;
    hc_idle_floor_x10 = hcidle_step(&hc_idl, &c, &in, ms);
    /* 2026-11-03 (hcxfn711.c): throttle correctors when the idle spark
       has used its window, one-shot kicks, the learned offset, anti-stall
       and the overrun cap - each 0 = off */
    if (c.enabled) {
        hc_idle_floor_x10 = hc_x_idle_air(hc_idle_floor_x10, in.target_rpm,
                                          (unsigned char)(in.pedal_x10 <= c.pedal_x10),
                                          (unsigned char)((hc_idl.state & HCIDLE_S_CLOSED) != 0u),
                                          ms);
    }
    /* anti-lag opens the throttle by its own amount (rusEFI
       ALSEtbAdd) while it is active - hcengctl711.c decides when. */
    if (HC_EC.als) {
        hc_idle_floor_x10 = (unsigned int)(hc_idle_floor_x10
                            + (unsigned int)(hc_cal_u8(CFG_U_ALS_THROTTLE) * 10u));
    }
    /* the A/C compressor's load (rusEFI acIdleExtraOffset), whether or not
       closed-loop idle is enabled */
    hc_idle_floor_x10 = (unsigned int)(hc_idle_floor_x10 + hc_aux_idle_up_x10());
    valve_service(hc_idle_floor_x10);

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
        /* ignition first: + the integral, faded out on release */
        IDLE711.out_x = tc.enabled
            ? hc_x_idle_timing(IGNIDLE.out_x10,
                               (unsigned char)((hc_idl.state & HCIDLE_S_CLOSED) != 0u),
                               in.target_rpm, ms)
            : 0;
    }
}

int far hc_idle_timing_x10(void)
{
    return IDLE711.out_x;
}
