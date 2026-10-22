/*
 * hcaux711.c - the auxiliary functions on ME7.1.1: cooling fan, A/C,
 * two programmable outputs, the oil pressure sensor. Read hcaux711.h.
 *
 * FAR (FCODE), MOD167 MEDIUM with DEFINE(HC_FAR_BRIDGE): every NCODE call
 * through a hcfar_me711.c thunk. Called from hc_idle_service() (the A/C
 * idle-up must be known before the idle floor is), so it costs NCODE
 * nothing. 16-bit arithmetic; each 32-bit product is divided with its
 * quotient bounded first (inline DIVLU, no ?C_ helper). Every field it
 * reads is in the universal block (>= HC_CFG_CORE), so the page is read
 * straight from the SRAM (pg8/pg16): hc_cal_u8() with a variable offset
 * expands to ~40 bytes of code each time.
 *
 * References: rusEFI fan_control.cpp (on/off temperatures, with A/C, off
 * when stopped, a failed coolant sensor runs the fan), ac_control.cpp
 * (request, low/high rpm and throttle cut-outs, engage delay, idle bump);
 * Speeduino programmable outputs (two conditions, AND/OR, hysteresis, on
 * delay); rusEFI linear sensor (two-point transfer, open/short window).
 */
#include "hcfarbridge.h"
#include <reg167.h>
#include "hctarget.h"
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hcfarinline.h"
#include "hc_pin_descriptor.h"
#include "hchal.h"
#include "hctrigger.h"
#include "hcengine.h"
#include "hcsafety.h"
#include "hcbench.h"
#include "hcio711.h"
#include "hcfresh711.h"
#include "hcaux711.h"

#define A HC_AUX711
typedef char hc_aux_fits[(sizeof(hc_aux711_t) <= TGT_RAM_AUX_LIMIT) ? 1 : -1];
/* the two programmable outputs are laid out alike, 9 bytes and two
   thresholds apart, and every field read here is past the near mirror
   (hanicore_config_def.py) */
typedef char hc_gp_layout[(CFG_U_GP2_PIN == CFG_U_GP1_PIN + 9u
                           && CFG_U_GP1_SRC_A == CFG_U_GP1_PIN + 1u
                           && CFG_U_GP1_DELAY == CFG_U_GP1_PIN + 8u
                           && CFG_U_GP2_THR_A == CFG_U_GP1_THR_A + 4u
                           && CFG_U_GP1_THR_B == CFG_U_GP1_THR_A + 2u
                           && CFG_U_DWELL_RPM_AX >= HC_CFG_CORE) ? 1 : -1];

extern unsigned int adc_raw[];       /* hcmain_me711.c, the 1 ms tick's   */

#define STEP_MS     20u
#define OCH2B ((unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_OCH2))
#define OIL_MV_MIN  200u             /* below: open or shorted to ground  */
#define OIL_MV_MAX  4800u            /* above: open to the 5 V pull-up    */

/* function bits in A.on, in the order of pin_off[] */
#define F_FAN   0x01u
#define F_AC    0x02u
#define F_GP1   0x04u
#define F_GP2   0x08u

/* an OCH2 word, big-endian (gen_ts_ini_me711.py reads the och(<n>u, )
   calls below as this module's channel offsets) */
static void och(unsigned int at, unsigned int v)
{
    unsigned char huge *p = OCH2B + (at - 1024u);
    p[0] = (unsigned char)(v >> 8);
    p[1] = (unsigned char)v;
}

static unsigned char pg8(unsigned int off)
{
    return HCFB_PAGE[off];
}

static unsigned int pg16(unsigned int off)
{
    return (unsigned int)(((unsigned int)HCFB_PAGE[off] << 8)
                          | HCFB_PAGE[off + 1u]);
}

/* 0.1 degC + bias -> degC */
static int temp_c(unsigned int dc)
{
    return (int)(dc - (unsigned int)(CAL_TEMP_BIAS * 10)) / 10;
}

/* ------------------------------------------------------------- outputs --
 * ON = the pin an output at LOW (the CJ920 stage on), OFF = the inactive
 * level written first, then released. One cavity at a time, constant
 * masks: every port write is a single AND/OR (no read-modify-write that an
 * interrupt could split - P7 also carries the injectors and the throttle
 * bridge), and the mask is already 16 bits wide (the CPLB trap, the project rules
 * section 6). A write happens only when the pin differs. */
static void out_set(unsigned char cav, unsigned char on)
{
    if (cav == TGT_AUX_CAV0) {
        if (on) {
            if ((DP7 & 0x0001u) && !(P7 & 0x0001u)) return;
            PWMCON1 &= 0xFFFEu;              /* the latch drives the pin */
            P7 &= 0xFFFEu;
            DP7 |= 0x0001u;
        } else if (DP7 & 0x0001u) {
            P7 |= 0x0001u;
            DP7 &= 0xFFFEu;
        }
    } else {
        if (on) {
            if ((DP7 & 0x0002u) && !(P7 & 0x0002u)) return;
            PWMCON1 &= 0xFFFDu;
            P7 &= 0xFFFDu;
            DP7 |= 0x0002u;
        } else if (DP7 & 0x0002u) {
            P7 |= 0x0002u;
            DP7 &= 0xFFFDu;
        }
    }
}

/* ------------------------------------------- oil and rail pressure -- */
/* A linear pressure sensor on a routed analog pin: lo_mv -> 0, hi_mv ->
   full kPa. Sets `routed` when a pin is configured and `ok` when the
   reading is valid now (fresh, inside OIL_MV_MIN..OIL_MV_MAX). */
static unsigned int pin_kpa(unsigned char p, unsigned int lo,
                            unsigned int hi, unsigned int full,
                            unsigned int routed, unsigned int ok)
{
    unsigned char ch;
    unsigned int raw = 0xFFFFu, mv;

    if (HC_PIN_IS_UNASSIGNED(p)) return 0u;
    A.status |= routed;
    ch = hc_pin_adc_channel(p);
    if (HC_ADC_IS_ASIC(ch)) {
        raw = hc_fresh_asic_an((unsigned char)(ch & 0x0Fu));
    } else if (ch < (unsigned char)TGT_ADC_CH_COUNT
               && (MAIN_LIVE & (unsigned int)(1u << ch))) {
        raw = adc_raw[ch];
    }
    if (raw > 1023u) return 0u;                    /* no fresh sample  */
    mv = (unsigned int)(((unsigned long)raw * 5000u) / 1023u);
    if (hi <= lo || mv < OIL_MV_MIN || mv > OIL_MV_MAX) return 0u;
    A.status |= ok;
    if (mv <= lo) return 0u;
    if (mv >= hi) return full;
    /* quotient < the full-scale pressure: bounded, inline DIVLU */
    return (unsigned int)(((unsigned long)(mv - lo) * full)
                          / (unsigned int)(hi - lo));
}

/* --------------------------------------------- programmable outputs -- */
/* the source's value in its own units; 0x7FFF = not readable now */
#define NO_VALUE 0x7FFF

static int src_val(unsigned char s)
{
    unsigned int e = eng_sensor_err;
    unsigned int v;

    switch (s) {
    case 1u:  return (int)(trg_rpm > 32000u ? 32000u : trg_rpm);
    case 2u:  return (e & ENG_ERR_CLT) ? NO_VALUE : temp_c(eng_clt_dc);
    case 3u:  return (e & ENG_ERR_IAT) ? NO_VALUE : temp_c(eng_iat_dc);
    case 4u:  return (e & ENG_ERR_TPS1) ? NO_VALUE : (int)(eng_tps_x10 / 10u);
    case 5u:  return (e & ENG_ERR_PEDAL1) ? NO_VALUE : (int)(eng_pedal_x10 / 10u);
    case 6u:  return (e & ENG_ERR_MAP) ? NO_VALUE : (int)(eng_map_kpa_x10 / 10u);
    case 7u:  return (int)eng_batt_dv;
    case 8u:  v = hc_io_lambda(0u);
              return v ? (int)(v / 10u) : NO_VALUE;
    case 9u:  return (int)eng_adv_x10 / 10;
    case 10u: return (int)(A.run_s > 32000u ? 32000u : A.run_s);
    case 11u: return (A.status & AUX_S_OIL_OK) ? (int)A.oil_kpa : NO_VALUE;
    default:  return NO_VALUE;         /* not used: never true            */
    }
}

/* one condition (source at o, comparison o+1, hysteresis o+2, threshold
   at thr) with its hysteresis memory `was` */
static unsigned char cond(unsigned int o, unsigned int thr, unsigned char was)
{
    int v = src_val(pg8(o));
    int t = (int)pg16(thr);
    int h = (int)pg8(o + 2u);

    if (v == NO_VALUE) return 0u;
    if (t > 32000) t = 32000;
    if (t < -32000) t = -32000;
    if (pg8(o + 1u) != 0u) {                     /* on below: mirror   */
        v = -v;
        t = -t;
    }
    if (v > t) return 1u;
    if (v < (int)(t - h)) return 0u;
    return was;
}

static unsigned char gp_step(unsigned char n, unsigned int ms)
{
    unsigned int o = (unsigned int)(CFG_U_GP1_PIN + 9u * n);
    unsigned int thr = (unsigned int)(CFG_U_GP1_THR_A + 4u * n);
    unsigned char c = A.cond[n], a = 0u, b = 0u, on = 0u;
    unsigned int t;

    if (pg8(o + 1u) != 0u) {                     /* condition A in use  */
        on = a = cond(o + 1u, thr, (unsigned char)(c & 1u));
        if (pg8(o + 4u) != 0u) {                 /* and B               */
            b = cond(o + 4u, thr + 2u, (unsigned char)((c >> 1) & 1u));
            on = (pg8(o + 7u) == 0u) ? (unsigned char)(a & b)
                                     : (unsigned char)(a | b);
        }
    }
    A.cond[n] = (unsigned char)(a | (b << 1));
    t = A.gp_ms[n];
    if (!on) {
        t = 0u;
    } else if (t < 60000u) {
        t = (unsigned int)(t + ms);
    }
    A.gp_ms[n] = t;
    return (unsigned char)(on && t >= (unsigned int)(pg8(o + 8u) * 100u));
}

/* ------------------------------------------------------------- service -- */
void far hc_aux_init(void)
{
    unsigned int i;
    unsigned char huge *p = (unsigned char huge *)&A;
    for (i = 0u; i < (unsigned int)sizeof(hc_aux711_t); i++) {
        p[i] = 0u;                    /* ?C_INIT never runs; SRAM keeps junk */
    }
}

/* the A/C request counts for the idle only with the engine running */
static unsigned char ac_req_running(void)
{
    return (unsigned char)((A.status & AUX_S_AC_REQ) && trg_rpm != 0u
                           && !eng_cranking);
}

unsigned int far hc_aux_idle_up_x10(void)
{
    return ac_req_running() ? (unsigned int)pg8(CFG_U_AC_IDLE_UP_X10) : 0u;
}

unsigned int far hc_aux_idle_rpm(void)
{
    return ac_req_running() ? (unsigned int)(pg8(CFG_U_AC_IDLE_RPM) * 10u) : 0u;
}

unsigned int far hc_aux_oil_kpa(void) { return A.oil_kpa; }
unsigned int far hc_aux_fuel_kpa(void) { return A.fuel_kpa; }
unsigned char far hc_aux_fuel_ok(void)
{
    return (unsigned char)((A.status & AUX_S_FUEL_OK) != 0u);
}
unsigned char far hc_aux_oil_ok(void)
{
    return (unsigned char)((A.status & AUX_S_OIL_OK) != 0u);
}

static const unsigned int pin_off[4] = {
    CFG_U_PIN_FAN, CFG_U_PIN_AC_CLUTCH, CFG_U_GP1_PIN, CFG_U_GP2_PIN
};

void far hc_aux_service(unsigned int now_ms)
{
    unsigned int ms, why = AUX_AC_WHY_NONE, rpm = trg_rpm, st = 0u, t, mx;
    unsigned char run, on = 0u, p, l, i, cav, want, routed, ok, drv;
    unsigned int clt = eng_clt_dc;    /* the page's own unit: 10 * C + 10000 */
    unsigned char clt_bad = (unsigned char)((eng_sensor_err & ENG_ERR_CLT) != 0u);

    ms = A.have_ms ? (unsigned int)(now_ms - A.last_ms) : 0u;
    A.last_ms = now_ms;
    A.have_ms = 1u;
    if (ms > 1000u) ms = 1000u;
    ms = (unsigned int)(A.acc_ms + ms);
    if (ms < STEP_MS) {
        A.acc_ms = ms;
        return;
    }
    A.acc_ms = 0u;

    run = (unsigned char)(rpm != 0u && !eng_cranking);
    t = A.run_ms;
    if (run) {
        t = (unsigned int)(t + ms);
        while (t >= 1000u) {
            t = (unsigned int)(t - 1000u);
            if (A.run_s != 0xFFFFu) A.run_s++;
        }
    } else {
        t = 0u;
        A.run_s = 0u;
    }
    A.run_ms = t;
    A.status = 0u;
    A.oil_kpa = pin_kpa(pg8(CFG_U_PIN_OIL_PRESS), pg16(CFG_U_OILP_LO_MV),
                        pg16(CFG_U_OILP_HI_MV), pg16(CFG_U_OILP_HI_KPA),
                        AUX_S_OIL_ROUTED, AUX_S_OIL_OK);
    /* the rail pressure sensor: read only when the compensation uses it
       (2026-10-15), a ratiometric 0.5..4.5 V part */
    A.fuel_kpa = (pg8(CFG_U_INJ_PRESS_MODE) == 3u)
        ? pin_kpa(pg8(CFG_U_PIN_FUEL_PRESS), 500u, 4500u,
                  pg16(CFG_U_FUEL_SENS_KPA), AUX_S_FUEL_ROUTED, AUX_S_FUEL_OK)
        : 0u;
    st = A.status;

    /* ---- A/C ------------------------------------------------------- */
    p = pg8(CFG_U_PIN_AC_REQ);
    if (!HC_PIN_IS_UNASSIGNED(p)) {
        l = hc_hal_din(p);
        if (l <= 1u && l == (unsigned char)(pg8(CFG_U_AC_REQ_ACTIVE) == 0u)) {
            st |= AUX_S_AC_REQ;
        }
    }
    t = A.ac_ms;
    if ((st & AUX_S_AC_REQ) && run) {
        if (t < 60000u) t = (unsigned int)(t + ms);
    } else {
        t = 0u;
    }
    A.ac_ms = t;
    if (st & AUX_S_AC_REQ) {
        l = pg8(CFG_U_AC_MAX_RPM);
        mx = pg16(CFG_U_AC_MAX_CLT);
        if (!run || rpm < (unsigned int)(pg8(CFG_U_AC_MIN_RPM) * 10u)) {
            why = AUX_AC_WHY_STOP;
        } else if (l != 0u && rpm > (unsigned int)(l * 50u)) {
            why = AUX_AC_WHY_RPM;
        } else if (pg8(CFG_U_AC_MAX_TPS) != 0u
                   && eng_tps_x10 > (unsigned int)(pg8(CFG_U_AC_MAX_TPS) * 10u)) {
            why = AUX_AC_WHY_TPS;
        } else if (clt_bad || (mx != 0u && clt >= mx)) {
            why = AUX_AC_WHY_CLT;
        } else if (t < (unsigned int)(pg8(CFG_U_AC_DELAY) * 100u)) {
            why = AUX_AC_WHY_DELAY;
        } else {
            on |= F_AC;
        }
    }

    /* ---- cooling fan ---------------------------------------------- */
    if (!HC_PIN_IS_UNASSIGNED(pg8(CFG_U_PIN_FAN))) {
        if ((rpm != 0u && eng_cranking)
            || (rpm == 0u && pg8(CFG_U_FAN_STOPPED_OFF) != 0u)) {
            /* off: cranking needs the battery; stopped, if asked */
        } else if (((on & F_AC) && pg8(CFG_U_FAN_WITH_AC) != 0u) || clt_bad
                   || clt >= pg16(CFG_U_FAN_ON_C)
                   || ((A.on & F_FAN) && clt > pg16(CFG_U_FAN_OFF_C))) {
            on |= F_FAN;
        }
    }
    A.status = st;                     /* the oil and A/C bits for gp_step */

    /* ---- programmable outputs -------------------------------------- */
    if (gp_step(0u, ms)) on |= F_GP1;
    if (gp_step(1u, ms)) on |= F_GP2;
    A.on = on;

    /* ---- the pins --------------------------------------------------- */
    ok = (unsigned char)((hc_safety_inhibits & HC_INHIBIT_ALWAYS) == 0u
                         && hcb_state != HCB_RUNNING);
    if (!ok) st |= AUX_S_HOLD;
    drv = A.drv;
    for (i = 0u; i < 2u; i++) {
        cav = (unsigned char)(i ? TGT_AUX_CAV1 : TGT_AUX_CAV0);
        routed = 0u;
        want = 0u;
        for (l = 0u; l < 4u; l++) {
            if (pg8(pin_off[l]) == cav) {
                routed = 1u;
                if (on & (unsigned char)(1u << l)) want = 1u;
            }
        }
        if (routed && ok) {
            out_set(cav, want);
            drv |= (unsigned char)(1u << i);
        } else if (drv & (unsigned char)(1u << i)) {
            out_set(cav, 0u);                  /* moved away or no permit */
            drv &= (unsigned char)~(1u << i);
        }
    }
    A.drv = drv;

    st |= (unsigned int)(((unsigned int)(on & F_FAN) ? AUX_S_FAN : 0u)
                       | ((unsigned int)(on & F_AC) ? AUX_S_AC_ON : 0u)
                       | ((unsigned int)on & (F_GP1 | F_GP2)) << 1
                       | (why << AUX_AC_WHY_SHIFT));
    A.status = st;
    och(1660u, st);                    /* auxStatus   */
    och(1662u, A.oil_kpa);             /* oilPressKpa */
}
