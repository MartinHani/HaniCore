/*
 * hcxfn711.c - functions added 2026-11-03 after studying another VAG 1.8T
 * standalone (the Ignitron study, .scratch/ignitron-study/STUDY.md, local).
 * That product is a REFERENCE for WHAT a mature VAG standalone does; no
 * text, map or value of it is in here. Every default is HaniCore's own
 * (tools/config_source/hanicore_ext_fields.py, hanicore_presets.py).
 *
 * COMPILED MOD167 MEDIUM (FCODE) WITH hcfarbridge.h FIRST. No module static
 * data (the far modules' XRAM is full): the state is TGT_RAM_XSTATE.
 * Arithmetic: 16-bit, or a 32-bit product / a 32/16 division whose
 * quotient is bounded first - never Keil's ?C_ long helpers.
 *
 * WHAT EACH PART DOES (settings in the page extension; 0 = off):
 *   1 throttle safety  plate off target > etbDevCutPct for etbDevCutTime
 *                      with the throttle in closed loop -> fuel AND spark
 *                      cut to the engine stop; a throttle-sensor pair
 *                      fault -> the same (etbPairAction 1); a start waits
 *                      for oil pressure (oilStartKpa / oilStartMax)
 *   2 idle             the idle spark correction also integrates
 *                      (ignition first), fades out on release; throttle
 *                      correctors step the air when the spark runs out of
 *                      room; one-shot kicks on an rpm drop; a learned
 *                      throttle offset (A/C off / on); anti-stall; an
 *                      overrun throttle cap by rpm; a minimum advance
 *   3 starting         cranking fuel held then reduced; extra fuel for the
 *                      first revolutions; warm-up lambda
 *   4 overrun          the fuel cut fades in and out with an extra on the
 *                      first fuel; a saturated sensor after a cut is not
 *                      trimmed on; closed-loop lean lockout and P part
 *   5 knock            retard by knock strength; a learned retard per
 *                      rpm x load when several cylinders knock together
 *   6 boost            integrator range by rpm; ceilings by IAT / coolant
 *   7 limp mode        lean / pressure / coolant / knock -> throttle cap,
 *                      boost off, reason kept, P1300
 *   8 throttle         gain by position, movement speed by position
 *   9 traction         an rpm rise faster than a car can accelerate ->
 *                      spark cut + retard (no wheel speeds on these ECUs)
 */
#include "hcfarbridge.h"
#include <reg167.h>
#include "hctarget.h"
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hcfarinline.h"
#include "hctrigger.h"
#include "hcengine.h"
#include "hc_dbw.h"
#include "hcidle.h"
#include "hcidle711.h"
#include "hcengctl711.h"
#include "hcaux711.h"
#include "hcio711.h"
#include "hcknock711.h"
#include "hcdeadline711.h"
#include "hcxfn711.h"
#include "hccan711.h"

typedef char hcx_fits[(sizeof(hcx_t) <= TGT_RAM_XSTATE_LIMIT) ? 1 : -1];

#define DIV32U(n, d)  ((unsigned int)((unsigned long)(n) / (unsigned int)(d)))
#define X HCX
#define STEP_MS 10u
#define OCHX(at, v) och_x((unsigned int)(at), (unsigned int)(v))

#define OCH1B ((unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_OCH))

static void och_x(unsigned int at, unsigned int v)
{
    OCH1B[at] = (unsigned char)(v >> 8);
    OCH1B[at + 1u] = (unsigned char)(v & 0xFFu);
}

static unsigned int u8v(unsigned int off) { return hc_cal_u8v(off); }

/* a x b / c with the sign of a; the caller bounds the quotient to 16 bits */
static int smuldiv(int a, unsigned int b, unsigned int c)
{
    unsigned int m = (unsigned int)((a < 0) ? -a : a);
    int q = (int)DIV32U((unsigned long)m * b, c);
    return (a < 0) ? -q : q;
}

/* the magnitude of a long / c, signed; |l| / c must fit 15 bits */
static int ldivs(long l, unsigned int c)
{
    unsigned long m = (unsigned long)((l < 0L) ? -l : l);
    int q = (int)DIV32U(m, c);
    return (l < 0L) ? -q : q;
}

static unsigned int sat_add(unsigned int a, unsigned int b)
{
    return (a > (unsigned int)(0xFFFFu - b)) ? 0xFFFFu : (unsigned int)(a + b);
}

static unsigned int udiff(unsigned int a, unsigned int b)
{
    return (a > b) ? (unsigned int)(a - b) : (unsigned int)(b - a);
}

/* An n-point curve with a u8 axis (x axmul) and u8 values; the value is
   returned x16 (fraction kept). Clamped at both ends, never extrapolated. */
static unsigned int curve8(unsigned int ax, unsigned int val, unsigned char n,
                           unsigned int x, unsigned int axmul)
{
    unsigned char i;
    unsigned int a0, a1, v0, v1, f;

    a0 = (unsigned int)(u8v(ax) * axmul);
    if (x <= a0) return (unsigned int)(u8v(val) << 4);
    for (i = 1u; i < n; i++) {
        a1 = (unsigned int)(u8v(ax + i) * axmul);
        if (x < a1 && a1 > a0) {
            v0 = (unsigned int)(u8v(val + i - 1u) << 4);
            v1 = (unsigned int)(u8v(val + i) << 4);
            f = DIV32U((unsigned long)(unsigned int)(x - a0) * 256u,
                       (unsigned int)(a1 - a0));          /* 0..255 */
            if (v1 >= v0) return (unsigned int)(v0 + DIV32U((unsigned long)(unsigned int)(v1 - v0) * f, 256u));
            return (unsigned int)(v0 - DIV32U((unsigned long)(unsigned int)(v0 - v1) * f, 256u));
        }
        a0 = a1;
    }
    return (unsigned int)(u8v(val + n - 1u) << 4);
}

/* The same over a u16 axis (temperatures, 10 C + 10000). */
static unsigned int curve16ax(unsigned int ax, unsigned int val,
                              unsigned char n, unsigned int x)
{
    unsigned char i;
    unsigned int a0, a1, v0, v1, f;

    a0 = hc_cal_u16v(ax);
    if (x <= a0) return (unsigned int)(u8v(val) << 4);
    for (i = 1u; i < n; i++) {
        a1 = hc_cal_u16v((unsigned int)(ax + 2u * i));
        if (x < a1 && a1 > a0) {
            v0 = (unsigned int)(u8v(val + i - 1u) << 4);
            v1 = (unsigned int)(u8v(val + i) << 4);
            f = (unsigned int)(a1 - a0) > 0xFFu
              ? DIV32U((unsigned long)(unsigned int)(x - a0) * 256u, (unsigned int)(a1 - a0))
              : (unsigned int)(((unsigned int)(x - a0) * 256u) / (unsigned int)(a1 - a0));
            if (v1 >= v0) return (unsigned int)(v0 + DIV32U((unsigned long)(unsigned int)(v1 - v0) * f, 256u));
            return (unsigned int)(v0 - DIV32U((unsigned long)(unsigned int)(v0 - v1) * f, 256u));
        }
        a0 = a1;
    }
    return (unsigned int)(u8v(val + n - 1u) << 4);
}

static unsigned char any_set(unsigned int off, unsigned char n)
{
    unsigned char i;
    for (i = 0u; i < n; i++) if (u8v(off + i) != 0u) return 1u;
    return 0u;
}

static unsigned char clt_ok(void)
{
    return (unsigned char)((eng_sensor_err & ENG_ERR_CLT) == 0u);
}

/* ================================================================ life == */
void far hc_x_init(void)
{
    unsigned char i;
    unsigned char huge *p = (unsigned char huge *)&X;
    unsigned char keep = (unsigned char)(unsigned int)&((hcx_t *)0)->kad_ms;

    if (X.magic != HCX_MAGIC) {
        X.idle_adapt[0] = 0;
        X.idle_adapt[1] = 0;
        for (i = 0u; i < 16u; i++) X.kad[i] = 0u;
        X.magic = HCX_MAGIC;
    }
    /* everything after the kept part starts at 0 (?C_INIT never runs and
       the SRAM is battery-backed) */
    for (i = keep; i < (unsigned char)sizeof(hcx_t); i++) {
        p[i] = 0u;
    }
    X.crank_pct = 100u;
    X.dfco_pm = 1000u;
    X.fuel_pm = 1000u;
}

void far hc_x_clear(void)
{
    unsigned char i;
    for (i = 0u; i < 16u; i++) X.kad[i] = 0u;
    if (trg_rpm == 0u) X.limp_why = 0u;
}

void far hc_x_idle_adapt_clear(void)
{
    X.idle_adapt[0] = 0;
    X.idle_adapt[1] = 0;
}

unsigned char far hc_x_cut_why(void) { return X.cut_why; }
unsigned char far hc_x_limp_why(void) { return X.limp_why; }

/* ======================================================== 1 + 7: safety == */
static unsigned char nret_over(unsigned char q)
{
    return hc_knock_ncyl(q);
}

static void safety_step(unsigned int ms)
{
    unsigned char why = (unsigned char)(X.cut_why & (HCX_CUT_DEV | HCX_CUT_PAIR));
    unsigned char dbw_run = (unsigned char)(hc_cal_u8(CAL_DBW_ENABLE) == 1u
                                            && hc_dbw_state() == DBW_RUN);
    unsigned char lim = (unsigned char)u8v(CFG_U_ETB_DEVCUT_PCT);
    unsigned char on = (unsigned char)u8v(CFG_U_LIMP_ON);
    unsigned int t;

    if (trg_rpm == 0u) {
        /* THE CUT IS LATCHED TO THE ENGINE STOP: a stopped engine is the
           driver's restart. A latched throttle fault keeps the bridge off
           after the restart; the pair cut then re-arms below. */
        why = 0u;
        X.dev_ms = 0u;
        X.limp_why = 0u;
        X.lean_ms = X.map_ms = X.clt_ms = 0u;
    }
    /* plate off target (independent of the throttle fault monitor) */
    if (lim != 0u && dbw_run && trg_rpm != 0u
        && udiff(hc_dbw_target_x10(), hc_dbw_actual_x10())
           > (unsigned int)(lim * 10u)) {
        X.dev_ms = sat_add(X.dev_ms, ms);
        if (X.dev_ms >= (unsigned int)(u8v(CFG_U_ETB_DEVCUT_T) * 10u)
            && u8v(CFG_U_ETB_DEVCUT_T) != 0u) {
            why |= HCX_CUT_DEV;
        }
    } else {
        X.dev_ms = 0u;
    }
    /* a throttle-sensor pair fault with the throttle on the motor */
    if (u8v(CFG_U_ETB_PAIR_ACTION) == 1u && hc_cal_u8(CAL_DBW_ENABLE) == 1u
        && trg_rpm != 0u && (hc_dbw_faults() & DBW_F_TPS_PAIR)) {
        why |= HCX_CUT_PAIR;
    }
    /* the start waits for oil pressure (not latched) */
    if (eng_cranking && u8v(CFG_U_OILSTART_KPA) != 0u && hc_aux_oil_ok()
        && hc_aux_oil_kpa() < (unsigned int)(u8v(CFG_U_OILSTART_KPA) * 10u)
        && X.crank_ms < (unsigned int)(u8v(CFG_U_OILSTART_MAX) * 100u)) {
        why |= HCX_CUT_OIL;
    }
    /* a CAN airbag crash (comms/hccan711.c, latched until the next boot) */
    if (hc_can_crash()) {
        why |= HCX_CUT_CRASH;
    }
    X.cut_why = why;

    /* ---- limp mode: each check latched to the engine stop ---- */
    if (on != 0u && trg_rpm != 0u && !eng_cranking) {
        unsigned int lam = hc_io_lambda(0u);
        unsigned int tgt = HC_EC.lambda_x1000;
        if ((on & 1u) && lam != 0u && u8v(CFG_U_LIMP_LEAN) != 0u
            && eng_tps_x10 >= (unsigned int)(u8v(CFG_U_LIMP_LEAN_TPS) * 10u)
            && lam > (unsigned int)(tgt + u8v(CFG_U_LIMP_LEAN) * 10u)) {
            X.lean_ms = sat_add(X.lean_ms, ms);
            if (X.lean_ms >= (unsigned int)(u8v(CFG_U_LIMP_LEAN_T) * 100u))
                X.limp_why |= HCX_LIMP_LEAN;
        } else {
            X.lean_ms = 0u;
        }
        t = (unsigned int)(u8v(CFG_U_LIMP_MAP) * 20u);
        if ((on & 2u) && t != 0u && !(eng_sensor_err & ENG_ERR_MAP)
            && eng_map_kpa_x10 > t) {
            X.map_ms = sat_add(X.map_ms, ms);
            if (X.map_ms >= (unsigned int)(u8v(CFG_U_LIMP_MAP_T) * 100u))
                X.limp_why |= HCX_LIMP_MAP;
        } else {
            X.map_ms = 0u;
        }
        t = hc_cal_u16(CFG_U_LIMP_CLT);
        if ((on & 4u) && t != 0u && clt_ok() && eng_clt_dc > t) {
            X.clt_ms = sat_add(X.clt_ms, ms);
            if (X.clt_ms >= 1000u) X.limp_why |= HCX_LIMP_CLT;
        } else {
            X.clt_ms = 0u;
        }
        if ((on & 8u) && u8v(CFG_U_LIMP_KNOCK) != 0u
            && nret_over((unsigned char)u8v(CFG_U_LIMP_KNOCK))
               >= (unsigned char)(u8v(CFG_U_LIMP_KNOCK_CYL) ? u8v(CFG_U_LIMP_KNOCK_CYL) : 1u)) {
            X.limp_why |= HCX_LIMP_KNOCK;
        }
    }
    if (on == 0u) X.limp_why = 0u;
    if (X.limp_why) X.cut_why |= HCX_CUT_LIMP;

    eng_fuelcut = (unsigned int)((eng_fuelcut & ~ENG_CUT_SAFE)
        | ((X.cut_why & (HCX_CUT_DEV | HCX_CUT_PAIR | HCX_CUT_OIL | HCX_CUT_CRASH))
           ? ENG_CUT_SAFE : 0u));
    if (eng_fuelcut & ENG_CUT_SAFE) hc_deadline_fuel_cut();
}

/* ================================================= 9: traction (rpm rate) */
static void traction_step(unsigned int ms)
{
    unsigned int r = trg_rpm;
    int d;

    X.rate_ms = sat_add(X.rate_ms, ms);
    if (X.rate_ms >= 50u) {
        /* rpm/s over the last >= 50 ms, then a 1:2 filter */
        d = (int)(r - X.last_rpm);
        if (d > 3000) d = 3000;
        if (d < -3000) d = -3000;
        d = smuldiv(d, 1000u, X.rate_ms);
        X.rpm_rate = (int)((X.rpm_rate + d) / 2);
        X.last_rpm = r;
        X.rate_ms = 0u;
    }
    if ((hc_cal_u16(CFG_U_MS_ENABLE) & 0x0010u) && u8v(CFG_U_TC_RATE) != 0u
        && r != 0u && !eng_cranking
        && X.rpm_rate > (int)(u8v(CFG_U_TC_RATE) * 100u)) {
        X.tc_ms = 300u;                     /* held, then released */
    } else if (X.tc_ms > ms) {
        X.tc_ms = (unsigned int)(X.tc_ms - ms);
    } else {
        X.tc_ms = 0u;
    }
    X.tc = (unsigned char)(X.tc_ms != 0u);
}

unsigned char far hc_x_tc_skip(void)
{
    unsigned char p = (unsigned char)u8v(CFG_U_TC_CUT);
    if (!X.tc || p == 0u) return 0u;
    return (unsigned char)DIV32U((unsigned long)(unsigned int)p * 255u, 100u);
}

/* ======================================================= the main loop == */
static void publish(void)
{
    OCHX(496u, X.cut_why);
    OCHX(498u, X.limp_why);
    OCHX(500u, (unsigned int)X.ign_out);
    OCHX(502u, (unsigned int)X.corr_x100);
    OCHX(504u, X.kick_x10);
    OCHX(506u, (unsigned int)X.idle_adapt[0]);
    OCHX(508u, (unsigned int)X.idle_adapt[1]);
    OCHX(510u, X.stall_x10);
    OCHX(512u, X.crank_pct);
    OCHX(514u, X.fuel_pm);
    OCHX(516u, (unsigned int)(X.o2sat[0] | (X.o2sat[1] << 1)));
    OCHX(518u, (unsigned int)(X.kad[X.kad_cell & 15u] * 25u / 10u));
    OCHX(520u, X.tc);
    OCHX(522u, (unsigned int)X.rpm_rate);
    OCHX(524u, X.blim_x10);
    OCHX(526u, X.dev_ms);
    OCHX(528u, X.wu_lam);
    OCHX(530u, X.stft_act_ms);
    OCHX(532u, X.kstr);
}

void far hc_x_service(unsigned int now_ms)
{
    unsigned int ms;
    unsigned char i;

    ms = X.have_ms ? (unsigned int)(now_ms - X.last_ms) : 0u;
    X.last_ms = now_ms;
    X.have_ms = 1u;
    X.acc_ms = sat_add(X.acc_ms, ms);
    if (X.acc_ms < STEP_MS) return;
    ms = X.acc_ms;
    X.acc_ms = 0u;
    if (ms > 200u) ms = 200u;

    safety_step(ms);
    traction_step(ms);

    /* knock adaptation gives back KADAPT_DECAY (0.1 deg/min) */
    if (u8v(CFG_U_KADAPT_DECAY) != 0u && trg_rpm != 0u) {
        /* centiseconds per 0.25 deg at raw x 0.1 deg/min */
        unsigned int per = (unsigned int)(15000u / u8v(CFG_U_KADAPT_DECAY));
        X.kad_ms = sat_add(X.kad_ms, (unsigned int)(ms / 10u));
        if (X.kad_ms >= per) {
            X.kad_ms = 0u;
            for (i = 0u; i < 16u; i++) if (X.kad[i]) X.kad[i]--;
        }
    }
    publish();
}

/* ============================================ the runtime pass (hc_ec_pre) */
void far hc_x_pre(unsigned int rpm, unsigned int dt_ms)
{
    /* cranking clock and revolutions since sync */
    /* the clock runs only while the engine TURNS under cranking:
       eng_cranking is also 1 at standstill with the key on (bench
       2026-11-03: the hold had expired before the first tooth) */
    if (rpm == 0u) {
        X.crank_ms = 0u;
        X.revs_x100 = 0u;
    } else if (eng_cranking) {
        X.crank_ms = sat_add(X.crank_ms, dt_ms);
        /* rpm x ms / 600 = revolutions x 100 */
        X.revs_x100 = sat_add(X.revs_x100,
                              DIV32U((unsigned long)(unsigned int)rpm * dt_ms, 600u));
    }
    /* closed loop active this long (lean lockout) */
    X.stft_act_ms = (HC_EC.stft_state == EC_STFT_ACTIVE)
                  ? sat_add(X.stft_act_ms, dt_ms) : 0u;
    /* the fuel-cut fade back in (restore), see hc_x_dfco() */
    if (!X.dfco_was) {
        X.rest_ms = sat_add(X.rest_ms, dt_ms);
    }
    /* the overrun-cut fade and restore as one factor */
    {
        unsigned int rt = (unsigned int)(u8v(CFG_U_DFCO_REST_T) * 10u);
        unsigned int pm = X.dfco_pm;
        if (!X.dfco_was && rt != 0u && X.rest_ms < rt) {
            unsigned int add = (unsigned int)(u8v(CFG_U_DFCO_REST_ADD) * 10u);
            unsigned int f = DIV32U((unsigned long)(unsigned int)X.rest_ms * 1000u, rt);
            /* fuel ramps 0 -> 100 % with the extra decaying to 0 */
            pm = (unsigned int)(f + DIV32U((unsigned long)(unsigned int)add * (unsigned int)(1000u - f), 1000u));
        } else if (!X.dfco_was) {
            pm = 1000u;
        }
        X.fuel_pm = pm;
    }
    /* warm-up lambda */
    X.wu_lam = 0u;
    if (u8v(CFG_U_WU_LAM_ON) == 1u && clt_ok()) {
        unsigned int v16 = curve16ax(CFG_U_WU_LAM_CLT, CFG_U_WU_LAM_VAL, 6u,
                                     eng_clt_dc);
        /* raw x 0.005 + 0.700 -> x1000: raw x 5 + 700 */
        X.wu_lam = (unsigned int)(700u + DIV32U((unsigned long)(unsigned int)v16 * 5u, 16u));
    }
}

/* ================================================================ 2 idle == */
int far hc_x_idle_timing(int p_x10, unsigned char closed, unsigned int target,
                         unsigned int ms)
{
    int mn = (int)hc_cal_u16(CFG_U_IDLE_TIM_MIN);
    int mx = (int)hc_cal_u16(CFG_U_IDLE_TIM_MAX);
    unsigned int ki = u8v(CFG_U_IDLE_IGN_KI);
    int out;

    if (closed) {
        if (ki != 0u && trg_rpm != 0u) {
            /* d(i) = ki x err/100 x ms, 0.1 deg x1000: ki 0.1 deg/s per 100 rpm */
            /* 0.1 deg x10000 per step: ki x err/10 x ms */
            unsigned int e = (target > trg_rpm) ? (unsigned int)(target - trg_rpm)
                                                : (unsigned int)(trg_rpm - target);
            int k;
            if (e > 500u) e = 500u;
            k = (int)(ki * (e / 10u));                       /* <= 12750 */
            if (target < trg_rpm) k = -k;
            X.ign_i += (long)k * (int)ms;
        }
        /* the integral never carries the sum past the window */
        {
            long hi = (long)(int)(mx - p_x10) * (int)10000;
            long lo = (long)(int)(mn - p_x10) * (int)10000;
            if (X.ign_i > hi) X.ign_i = hi;
            if (X.ign_i < lo) X.ign_i = lo;
        }
        out = (int)(p_x10 + ldivs(X.ign_i, 10000u));
        X.ign_from = out;
        X.fade_ms = 0u;
    } else {
        unsigned int ft = (unsigned int)(u8v(CFG_U_IDLE_IGN_FADE) * 10u);
        X.ign_i = 0L;
        X.fade_ms = sat_add(X.fade_ms, ms);
        if (ft == 0u || X.fade_ms >= ft || X.ign_from == 0) {
            out = 0;
            X.ign_from = 0;
        } else {
            unsigned int left = (unsigned int)(ft - X.fade_ms);
            int a = X.ign_from;
            unsigned int m = (unsigned int)(a < 0 ? -a : a);
            int v = (int)DIV32U((unsigned long)(unsigned int)m * left, ft);
            out = (a < 0) ? -v : v;
        }
        if (p_x10 != 0) out = p_x10;     /* the core still drives it (soft entry) */
    }
    if (out > mx) out = mx;
    if (out < mn) out = mn;
    X.closed_last = closed;
    X.ign_out = out;
    return out;
}

unsigned int far hc_x_idle_air(unsigned int floor_x10, unsigned int target,
                               unsigned char released, unsigned char closed,
                               unsigned int ms)
{
    unsigned int rpm = trg_rpm;
    unsigned char ac = (unsigned char)(hc_aux_idle_up_x10() != 0u
                                       || hc_aux_idle_rpm() != 0u);
    long v;
    unsigned char i;

    if (rpm == 0u || eng_cranking) {
        X.corr_x100 = 0;
        X.kick_x10 = 0u;
        X.kick_done = 0u;
        X.stall_x10 = 0u;
        return floor_x10;
    }
    /* ---- throttle correctors: the spark has used its window ---- */
    {
        unsigned int thr = u8v(CFG_U_IDLE_CORR_THR);
        int mn = (int)hc_cal_u16(CFG_U_IDLE_TIM_MIN);
        int mx = (int)hc_cal_u16(CFG_U_IDLE_TIM_MAX);
        int cmax = (int)(u8v(CFG_U_IDLE_CORR_MAX) * 10u);      /* 0.01 % */
        if (thr != 0u && closed) {
            X.corr_ms = sat_add(X.corr_ms, ms);
            if (X.corr_ms >= (unsigned int)(u8v(CFG_U_IDLE_CORR_PER) * 10u)) {
                int st = (int)u8v(CFG_U_IDLE_CORR_STEP);
                X.corr_ms = 0u;
                /* at the advance end: the engine wants air */
                if (mx > 0 && (long)(int)X.ign_out * (int)100 >= (long)(int)mx * (int)thr) {
                    X.corr_x100 = (int)(X.corr_x100 + st);
                } else if (mn < 0 && (long)(int)X.ign_out * (int)100 <= (long)(int)mn * (int)thr) {
                    X.corr_x100 = (int)(X.corr_x100 - st);
                }
                if (X.corr_x100 > cmax) X.corr_x100 = cmax;
                if (X.corr_x100 < -cmax) X.corr_x100 = -cmax;
            }
        } else if (thr == 0u) {
            X.corr_x100 = 0;
        }
    }
    /* ---- one-shot kicks on an rpm drop, taken back above target ---- */
    if (rpm >= (unsigned int)(target + u8v(CFG_U_IDLE_KICK_RESET) * 10u)) {
        X.kick_x10 = 0u;
        X.kick_done = 0u;
    } else if (released && rpm < target) {
        unsigned int drop = (unsigned int)(target - rpm);
        unsigned char m = 1u;
        for (i = 0u; i < 3u; i++) {
            unsigned int d = (unsigned int)(u8v(CFG_U_IDLE_KICK_DROP + i) * 10u);
            if (d != 0u && drop >= d && !(X.kick_done & m)) {
                X.kick_done |= m;
                X.kick_x10 = (unsigned int)(X.kick_x10 + u8v(CFG_U_IDLE_KICK_STEP + i));
            }
            m = (unsigned char)(m << 1);
        }
    }
    /* ---- adaptation: warm, settled, closed: learn the trim + corrector ---- */
    {
        unsigned int rate = u8v(CFG_U_IDLE_ADAPT_RATE);           /* 0.01 %/s */
        int amax = (int)(u8v(CFG_U_IDLE_ADAPT_MAX) * 10u);        /* 0.01 %   */
        int want = (int)(hc_idl.trim_x10 * 10 + X.corr_x100);
        if (rate != 0u && closed && released && clt_ok()
            && eng_clt_dc >= hc_cal_u16(CFG_U_IDLE_ADAPT_CLT)
            && udiff(rpm, target) < 50u) {
            X.adapt_ms = sat_add(X.adapt_ms, ms);
            if (X.adapt_ms >= 1000u) {
                int cur = X.idle_adapt[ac];
                X.adapt_ms = 0u;
                if (want > 0 && cur < amax) cur = (int)(cur + (int)rate);
                else if (want < 0 && cur > -amax) cur = (int)(cur - (int)rate);
                if (cur > amax) cur = amax;
                if (cur < -amax) cur = -amax;
                X.idle_adapt[ac] = cur;
            }
        }
        if (amax == 0) X.idle_adapt[ac] = 0;
    }
    /* ---- anti-stall ---- */
    X.stall_x10 = 0u;
    if (u8v(CFG_U_STALL_RPM) != 0u) {
        unsigned int lim = (unsigned int)(u8v(CFG_U_STALL_RPM) * 10u);
        if (target > lim && rpm < (unsigned int)(target - lim)) {
            unsigned int s = (unsigned int)(target - lim - rpm);
            unsigned int add, mx;
            if (s > 2000u) s = 2000u;
            add = DIV32U((unsigned long)(unsigned int)s * u8v(CFG_U_STALL_GAIN), 100u);
            mx = u8v(CFG_U_STALL_MAX);
            X.stall_x10 = (add > mx) ? mx : add;
        }
    }
    v = (long)floor_x10 + (long)(X.corr_x100 / 10) + (long)(X.idle_adapt[ac] / 10)
      + (long)X.kick_x10 + (long)X.stall_x10;
    if (v < 0L) v = 0L;
    if (v > 1000L) v = 1000L;
    /* ---- the overrun cap: pedal released, well above idle ---- */
    if (released && any_set(CFG_U_DBWO_MAX, 4u)
        && rpm > (unsigned int)(target + 300u)) {
        unsigned int cap = DIV32U((unsigned long)(unsigned int)curve8(CFG_U_DBWO_RPM_AX, CFG_U_DBWO_MAX,
                                                        4u, rpm, 100u), 16u);
        if (cap != 0u && (unsigned int)v > cap) v = (long)cap;
    }
    return (unsigned int)v;
}

/* ============================================================ 3 starting == */
unsigned int far hc_x_crank_fuel(unsigned int mg_x10)
{
    unsigned int pct = 100u;
    unsigned int hold = (unsigned int)(u8v(CFG_U_CRANK_HOLD) * 100u);
    unsigned int dec = (unsigned int)(u8v(CFG_U_CRANK_DECAY) * 100u);
    unsigned int flo = u8v(CFG_U_CRANK_FLOOR);
    unsigned long m;

    if (hold != 0u && X.crank_ms > hold) {
        unsigned int t = (unsigned int)(X.crank_ms - hold);
        if (flo < 10u || flo > 100u) flo = 100u;
        if (dec == 0u || t >= dec) {
            pct = flo;
        } else {
            pct = (unsigned int)(100u - DIV32U((unsigned long)(unsigned int)(100u - flo) * t, dec));
        }
    }
    if (u8v(CFG_U_FIRST_REVS_ADD) != 0u
        && X.revs_x100 < (unsigned int)(u8v(CFG_U_FIRST_REVS_N) * 100u)) {
        pct = (unsigned int)(pct + u8v(CFG_U_FIRST_REVS_ADD));
    }
    X.crank_pct = pct;
    if (pct > 300u) pct = 300u;
    m = (unsigned long)(unsigned int)mg_x10 * pct;
    if (m > 6553500uL) m = 6553500uL;
    return DIV32U(m, 100u);
}

unsigned int far hc_x_lambda(unsigned int lam_x1000)
{
    if (X.wu_lam != 0u && X.wu_lam < lam_x1000) return X.wu_lam;
    return lam_x1000;
}

/* ============================================================ 4 overrun == */
unsigned char far hc_x_dfco(unsigned char want, unsigned int dt_ms)
{
    unsigned int ct = (unsigned int)(u8v(CFG_U_DFCO_CUT_T) * 10u);

    if (want) {
        if (!X.dfco_was) X.dfco_pm = 1000u;   /* the cut begins */
        X.dfco_was = 1u;
        X.rest_ms = 0u;
        if (ct == 0u) {
            X.dfco_pm = 0u;
        } else {
            unsigned int step = DIV32U((unsigned long)(unsigned int)(dt_ms > ct ? ct : dt_ms) * 1000u, ct);
            X.dfco_pm = (X.dfco_pm > step) ? (unsigned int)(X.dfco_pm - step) : 0u;
        }
        X.fuel_pm = X.dfco_pm;
        X.dfco_hard = (unsigned char)(X.dfco_pm == 0u);
    } else {
        if (X.dfco_was) {
            /* the cut ends: restore from where the fade got to */
            X.rest_ms = X.dfco_hard ? 0u : 0xFFFFu;
            X.dfco_pm = 1000u;
        }
        X.dfco_was = 0u;
        X.dfco_hard = 0u;
    }
    return X.dfco_hard;
}

unsigned int far hc_x_fuel_pm(void)
{
    return X.fuel_pm;
}

unsigned char far hc_x_o2_sat(unsigned char bank, unsigned int lam,
                              unsigned int dt_ms)
{
    unsigned int sat = u8v(CFG_U_O2SAT_LAM);
    unsigned int rec;
    bank &= 1u;
    if (sat == 0u) {
        X.o2sat[bank] = 0u;
        return 0u;
    }
    sat = (unsigned int)(1000u + sat * 10u);
    rec = (unsigned int)(1000u + u8v(CFG_U_O2SAT_REC) * 10u);
    if (!X.o2sat[bank]) {
        /* only right after an overrun cut, below the throttle limit */
        if (HC_EC.since_dfco_ms < 5000u && lam > sat
            && eng_tps_x10 < (unsigned int)(u8v(CFG_U_O2SAT_TPS) * 10u)) {
            X.o2sat[bank] = 1u;
            X.o2rec_ms[bank] = 0u;
        }
    } else if (lam != 0u && lam < rec) {
        X.o2rec_ms[bank] = sat_add(X.o2rec_ms[bank], dt_ms);
        if (X.o2rec_ms[bank] >= (unsigned int)(u8v(CFG_U_O2SAT_T) * 100u))
            X.o2sat[bank] = 0u;
    } else {
        X.o2rec_ms[bank] = 0u;
    }
    return X.o2sat[bank];
}

unsigned char far hc_x_stft_lean_locked(void)
{
    unsigned int t = (unsigned int)(u8v(CFG_U_STFT_LEAN_LOCK) * 100u);
    return (unsigned char)(t != 0u && X.stft_act_ms < t);
}

/* P part, per mille of fuel: err_pm (lambda error per mille, + = lean) x
   Kp (0.01 %/%). */
int far hc_x_stft_p(unsigned char region, int err_pm)
{
    int kp = (int)u8v((unsigned int)(CFG_U_STFT_KP + (region & 3u)));
    if (kp == 0) return 0;
    if (err_pm > 300) err_pm = 300;
    if (err_pm < -300) err_pm = -300;
    if (err_pm < 0 && hc_x_stft_lean_locked()) return 0;
    return smuldiv(err_pm, (unsigned int)kp, 100u);
}

/* ============================================================== 5 knock == */
unsigned char far hc_x_knock_q(unsigned char level16, unsigned int rpm)
{
    unsigned char a, r, i;
    unsigned int lv;

    /* strength = window / quiet reference, x10 (level16 is x16) */
    lv = (unsigned int)(((unsigned int)level16 * 10u) >> 4);
    X.kstr = (unsigned char)((lv > 255u) ? 255u : lv);
    if (u8v(CFG_U_KAMP_ON) != 1u) return 0u;
    a = 0u;
    for (i = 0u; i < 4u; i++) if (lv >= u8v(CFG_U_KAMP_AX + i)) a = i;
    r = 0u;
    for (i = 0u; i < 4u; i++) if (rpm >= (unsigned int)(u8v(CFG_U_KAMP_RPM_AX + i) * 100u)) r = i;
    return (unsigned char)u8v((unsigned int)(CFG_U_KAMP_MAP + a * 4u + r));
}

static unsigned char kad_index(void)
{
    unsigned char r = 0u, l = 0u, i;
    unsigned int load = (unsigned int)(eng_rl_x10 / 10u);
    for (i = 0u; i < 4u; i++) if (trg_rpm >= (unsigned int)(u8v(CFG_U_KAMP_RPM_AX + i) * 100u)) r = i;
    for (i = 0u; i < 4u; i++) if (load >= (unsigned int)(u8v(CFG_U_KADAPT_LOAD_AX + i) * 2u)) l = i;
    return (unsigned char)(l * 4u + r);
}

void far hc_x_knock_learn(unsigned char q, unsigned char ncyl)
{
    unsigned char c, mx, add;
    unsigned int n;

    if (u8v(CFG_U_KADAPT_MODE) == 0u || !clt_ok()) return;
    if (ncyl < (unsigned char)(u8v(CFG_U_KADAPT_CYL) ? u8v(CFG_U_KADAPT_CYL) : 1u)) return;
    c = kad_index();
    X.kad_cell = c;
    add = (unsigned char)DIV32U((unsigned long)(unsigned int)q * u8v(CFG_U_KADAPT_ATTACK) + 50u, 100u);
    if (add == 0u) add = 1u;
    mx = (unsigned char)u8v(CFG_U_KADAPT_MAX);
    n = (unsigned int)(X.kad[c] + add);
    X.kad[c] = (unsigned char)((n > mx) ? mx : n);
    X.kad_ms = 0u;
}

/* =============================================================== spark == */
int far hc_x_spark(int a)
{
    /* the learned knock retard (learn+apply), all cylinders */
    if (u8v(CFG_U_KADAPT_MODE) == 2u) {
        unsigned char c = kad_index();
        X.kad_cell = c;
        a = (int)(a - (int)((X.kad[c] * 5u) >> 1));      /* q -> 0.1 deg */
    }
    if (X.tc) {
        a = (int)(a - (int)(u8v(CFG_U_TC_RETARD) * 10u));
    }
    /* the minimum advance - not under anti-lag / launch / flat shift, which
       retard on purpose */
    if (!HC_EC.als && !HC_EC.launch && !HC_EC.flat && trg_rpm != 0u
        && any_set(CFG_U_MINADV_VAL, 4u)) {
        int m = (int)(DIV32U((unsigned long)(unsigned int)curve8(CFG_U_MINADV_RPM_AX, CFG_U_MINADV_VAL,
                                                   4u, trg_rpm, 50u) * 5u, 16u)) - 200;
        if (a < m) a = m;
    }
    return a;
}

/* ============================================================== 6 boost == */
unsigned int far hc_x_boost_target(unsigned int tgt_x10)
{
    unsigned int lim = 0xFFFFu, v;

    if (!(eng_sensor_err & ENG_ERR_IAT) && any_set(CFG_U_BLIM_IAT, 4u)) {
        v = DIV32U((unsigned long)(unsigned int)curve16ax(CFG_U_BLIM_IAT_AX, CFG_U_BLIM_IAT, 4u,
                                            eng_iat_dc) * 20u, 16u);
        if (v != 0u && v < lim) lim = v;
    }
    if (clt_ok() && any_set(CFG_U_BLIM_CLT, 4u)) {
        v = DIV32U((unsigned long)(unsigned int)curve16ax(CFG_U_BLIM_CLT_AX, CFG_U_BLIM_CLT, 4u,
                                            eng_clt_dc) * 20u, 16u);
        if (v != 0u && v < lim) lim = v;
    }
    X.blim_x10 = (lim == 0xFFFFu) ? 0u : lim;
    return (tgt_x10 > lim) ? lim : tgt_x10;
}

unsigned char far hc_x_boost_off(void)
{
    return (unsigned char)(X.limp_why != 0u);
}

void far hc_x_boost_ilim(long *integ100)
{
    long lo, hi;
    if (!any_set(CFG_U_BI_MIN, 6u) && !any_set(CFG_U_BI_MAX, 6u)) return;
    /* % -> duty x10 x100 */
    lo = -((long)(int)DIV32U((unsigned long)(unsigned int)curve8(CFG_U_BI_RPM_AX, CFG_U_BI_MIN, 6u,
                                                  trg_rpm, 100u) * 10u, 16u) * (int)100);
    hi = (long)(int)DIV32U((unsigned long)(unsigned int)curve8(CFG_U_BI_RPM_AX, CFG_U_BI_MAX, 6u,
                                                 trg_rpm, 100u) * 10u, 16u) * (int)100;
    if (*integ100 > hi) *integ100 = hi;
    if (*integ100 < lo) *integ100 = lo;
}

/* =========================================================== 8 throttle == */
unsigned int far hc_x_dbw_want(unsigned int want_x10)
{
    unsigned int cap;
    if (X.limp_why == 0u) return want_x10;
    cap = (unsigned int)(u8v(CFG_U_LIMP_THR) * 10u);
    if (cap == 0u) return want_x10;
    return (want_x10 > cap) ? cap : want_x10;
}

unsigned int far hc_x_dbw_slew(unsigned int prev_x10, unsigned int next_x10,
                               unsigned int step_ms)
{
    unsigned int lim, off;
    if (next_x10 == prev_x10) return next_x10;
    off = (next_x10 > prev_x10) ? CFG_U_DBWS_OPEN : CFG_U_DBWS_CLOSE;
    if (!any_set(off, 4u)) return next_x10;
    /* raw 0.1 %/10 ms -> 0.1 % per step: raw x step / 10 (x16 curve) */
    lim = DIV32U((unsigned long)(unsigned int)curve8(CFG_U_DBWS_AX, off, 4u,
                                       (unsigned int)(prev_x10 / 10u), 1u) * step_ms, 160u);
    if (lim == 0u) lim = 1u;
    if (next_x10 > prev_x10) {
        return (unsigned int)(next_x10 - prev_x10) > lim ? (unsigned int)(prev_x10 + lim) : next_x10;
    }
    return (unsigned int)(prev_x10 - next_x10) > lim ? (unsigned int)(prev_x10 - lim) : next_x10;
}

unsigned int far hc_x_dbw_gain(unsigned int pos_x10)
{
    unsigned int g;
    if (!any_set(CFG_U_DBWG_PCT, 4u)) return 100u;
    g = (unsigned int)(curve8(CFG_U_DBWG_AX, CFG_U_DBWG_PCT, 4u,
                              (unsigned int)(pos_x10 / 10u), 1u) >> 4);
    return (g == 0u) ? 100u : g;
}

/* AutoCal plausibility: 0 = every endpoint within the tolerance of what
   this body's sensors read, else 1..4 = the first one that is not. counts
   (10-bit, 5 V) vs 0.02 V: V x50 = counts x 250 / 1023. */
unsigned char far hc_x_etbcal_check(unsigned int t1c, unsigned int t1o,
                                    unsigned int t2c, unsigned int t2o)
{
    unsigned int tol = u8v(CFG_U_TPS_EXP_TOL);
    unsigned int m[4];
    unsigned char i;
    if (tol == 0u) return 0u;
    m[0] = t1c; m[1] = t1o; m[2] = t2c; m[3] = t2o;
    for (i = 0u; i < 4u; i++) {
        unsigned int e = u8v(CFG_U_TPS_EXP + i);
        unsigned int v;
        if (e == 0u) continue;                      /* not known: no check */
        if (m[i] > 1023u) m[i] = 1023u;
        v = DIV32U((unsigned long)(unsigned int)m[i] * 250u + 511u, 1023u);   /* 0.02 V */
        if (udiff(v, e) > tol) return (unsigned char)(i + 1u);
    }
    return 0u;
}
