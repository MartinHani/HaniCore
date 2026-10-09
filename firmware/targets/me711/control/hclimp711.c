/*
 * hclimp711.c - engine protection on ME7.1.1: the shared decision
 * core (control/hclimp.c) fed from this image's values; every protection is
 * a FUEL cut through its own bit of the shared cut word (ENG_CUT_LIMP).
 * FCODE, hcfarbridge.h first.
 *
 *   coolant    cltMaxDegX10 (0 = off) -> fuel cut above cltLimpRpm
 *              (0 = 3000); a coolant sensor fault is not judged
 *   ETB fault  a latched throttle fault with DBW on -> fuel cut above
 *              etbLimpRpm (0 = 1500, rusEFI reportEtbJammed): the plate is
 *              on its limp spring
 *   duty       injDutyInstX10 / injDutySustX10 for injDutySustMs (0 = off)
 *   flood      floodClearX10 (0 = off): no fuel while cranking with the
 *              pedal (throttle without DBW) above it
 *   oil        NOT fed: this image has no oil pressure input (the core
 *              supports it - host-tested - and oilPressMinKpa stays
 *              labelled "not used" until an input exists)
 */
#include "hcfarbridge.h"
#include "hctarget.h"
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hctrigger.h"
#include "hcengine.h"
#include "hc_dbw.h"
#include "hclimp.h"
#include "hclimp711.h"
#include "hcdeadline711.h"
extern unsigned char dry_seq_active;   /* hcsched_dry.h: true sequential */

#define STEP_MS 10u
#define ETB_FAULTS (DBW_F_APP_PAIR | DBW_F_TPS_PAIR | DBW_F_APP_RANGE \
                    | DBW_F_TPS_RANGE | DBW_F_SF | DBW_F_DEV | DBW_F_STALE)

hclimp_t     hc_limp;
unsigned int hc_limp_duty_x10;
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

void far hc_limp_init(void)
{
    hclimp_reset(&hc_limp);
    hc_limp_duty_x10 = 0u;
    acc_ms = 0u;
    have_ms = 0u;
}

/* injector duty, 0.1 %: the injector's open time per 720 deg / 720 deg.
   V97: eng_ti_base_us is the CYCLE's open time (hcengine.c); the dead time
   is paid once per pulse - twice per cycle in batch, semi-sequential and the
   sequential fallback, once in true sequential (dry_seq_active). t*rpm is an
   inline MULU; the quotient is bounded before each (inline) DIVLU. */
static unsigned int inj_duty_x10(void)
{
    unsigned int dt = eng_deadtime_us;
    unsigned long t = (unsigned long)eng_ti_base_us
                    + (unsigned long)(dry_seq_active ? dt : (unsigned int)(dt * 2u));
    unsigned long prod;
    unsigned int d;

    if (t > 60000uL) t = 60000uL;
    prod = (unsigned long)(unsigned int)t * trg_rpm;          /* us x rpm */
    /* duty_x10 = t * rpm / 120000 (x10 % of the 720 deg period) */
    if (prod >= 120000000uL) return 1000u;
    d = (unsigned int)((unsigned int)(prod / 2000u) / 60u);
    return d > 1000u ? 1000u : d;
}

void far hc_limp_service(unsigned int now_ms)
{
    unsigned int ms;
    hclimp_cfg_t c;
    hclimp_in_t in;
    unsigned int v;
    unsigned char dbw_on;

    acc_ms += elapsed(now_ms);
    if (acc_ms < STEP_MS) return;
    ms = acc_ms;
    acc_ms = 0u;

    v = hc_cal_u16(CFG_U_CLT_MAX_X10);
    c.clt_max_x10 = v ? (int)((long)v - (long)CAL_TEMP_BIAS * 10L) : 0;
    v = hc_cal_u16(CFG_U_CLT_LIMP_RPM);
    c.clt_rpm = v ? v : 3000u;
    v = hc_cal_u16(CFG_U_ETB_LIMP_RPM);
    c.etb_rpm = v ? v : 1500u;
    c.oil_min_kpa = 0u;                          /* no oil input: off   */
    c.oil_rpm = 0u;
    c.oil_ms = 0u;
    c.oil_start_ms = 0u;
    c.duty_inst_x10 = hc_cal_u16(CFG_U_INJ_DUTY_INST_X10);
    c.duty_sust_x10 = hc_cal_u16(CFG_U_INJ_DUTY_SUST_X10);
    c.duty_sust_ms = hc_cal_u16(CFG_U_INJ_DUTY_SUST_MS);
    c.flood_x10 = hc_cal_u16(CFG_U_FLOOD_CLEAR_X10);

    dbw_on = (unsigned char)(hc_cal_u8(CAL_DBW_ENABLE) == 1u);
    hc_limp_duty_x10 = inj_duty_x10();
    in.rpm = trg_rpm;
    in.cranking = eng_cranking;
    in.clt_x10 = (int)((long)eng_clt_dc - (long)CAL_TEMP_BIAS * 10L);
    in.clt_ok = (unsigned char)((eng_sensor_err & ENG_ERR_CLT) == 0u);
    in.oil_kpa = 0u;
    in.oil_ok = 0u;
    in.etb_fault = (unsigned char)(dbw_on && (hc_dbw_faults() & ETB_FAULTS) != 0u);
    in.duty_x10 = hc_limp_duty_x10;
    in.pedal_x10 = dbw_on ? hc_dbw_pedal_x10() : eng_tps_x10;
    (void)hclimp_step(&hc_limp, &c, &in, ms);

    eng_fuelcut = (unsigned int)((eng_fuelcut & ~ENG_CUT_LIMP)
                                 | (hc_limp.cut ? ENG_CUT_LIMP : 0u));
    if(hc_limp.cut) hc_deadline_fuel_cut();
}
