/* Bounded ETB commissioning. AN1/AN3 are the independent opposing tracks;
 * AN2/IPV is amplified TPS1 and is telemetry only. Endpoint capture uses
 * fixed duration/duty, not a derivative/torque inference of physical stops.
 * Mechanical travel and spring-return qualification remain bench work.
 * Candidates stay private through combined commissioning; only a complete
 * successful procedure publishes configuration. Every exit releases.
 */
#include "hcfarbridge.h"
#include <reg167.h>
#include "hctarget.h"
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hchal.h"
#include "hchal_me711.h"    /* hc_hal_dbw_pwm_* (through the far bridge) */
#include "hc_dbw.h"
#include "hc_dbw_state.h"
#include "hcetbcal.h"
#include "hcfresh711.h"
#include "hctrigger.h"
#define HC_SWEEP_PTR huge
#include "hc_etb_sweep.h"
#include "hc_etb_bias.h"
#include "hc_config_manager.h"
#include "hcengine.h"
#include "hcts.h"
#include "hcnvm.h"
#define B (*(hc_bias_t huge *)(TGT_EXTRAM_BASE + TGT_RAM_ETBBIAS))
typedef char bias_fits[(sizeof(hc_bias_t)<=TGT_RAM_ETBBIAS_LIMIT)?1:-1];

#define ETB_STEP_MS        5u
#define ETB_REST_MS      400u      /* let a preceding bench pulse return */
#define ETB_BACK_MS      400u
#define ETB_DUTY_MIN     200u
#define ETB_DUTY_MAX     600u
#define ETB_DUTY_DEFAULT 500u      /* rusEFI motor->set(0.5f)               */
#define ETB_HOLD_MIN     300u
#define ETB_HOLD_MAX    1500u
#define ETB_HOLD_DEFAULT 1000u     /* rusEFI hasElapsedMs(1000)             */
#define ETB_AVG_N          8u      /* 8 x 5 ms = one 40 ms mean         */
#define ETB_MOVED_MIN      6u
#define ETB_SPAN_MIN     100u      /* rusEFI 0.5 V of 5 V                   */
#define ETB_TRACK_TOL      5u      /* 1/50 units: 10 % of travel            */
#define ETB_RUN_MAX     8000u      /* the holds may extend            */
#define ETB_ADC_LO        10u
#define ETB_ADC_HI      1013u
#define AT_TARGET_X10    500u
#define AT_AMP_MIN        50u
#define AT_AMP_MAX       300u
#define AT_AMP_DEFAULT   200u      /* rusEFI autotuneAmplitude = 20         */
#define AT_WARM            8u
#define AT_MEASURE        16u
#define AT_BAND_LO       200u
#define AT_BAND_HI       800u
#define AT_APPROACH_MS  1500u
#define AT_RUN_MS      15000u
#define AT_TU_CLAMP     2000u
#define AT_A_MIN           5u      /* 0.5 %                                 */
#define AT_A_MAX         300u      /* 30 %                                  */
#define AT_TU_MIN         20u
#define AT_TU_MAX       1000u
#define DBW_BIAS_ZERO   1000u

#define VFY_SETTLE_MS    200u      /* minimum approach before qualification */
#define VFY_STEP_MS      500u
#define VFY_STEPS          5u
#define VFY_BAND          20u      /* +/-2 % = settled                        */
#define VFY_SETTLE_MAX   350u      /* ms                                      */
#define VFY_OVER_MAX      50u      /* 5 % of travel                           */
#define VFY_ERR_MAX       15u      /* 1.5 % mean over the last 100 ms         */
#define VFY_TAIL_MS      100u
#define VFY_RETRIES        3u      /* bounded candidate damping, never faults */
#define VFY_RUN_MAX    22000u
static const unsigned int vfy_tgt[VFY_STEPS] = { 200u, 600u, 200u, 40u, 150u };

typedef struct {
    unsigned char ph, req, res, why, newcal, newtune, on, dir;
    unsigned char proc, failph, calok, oper;   /* the commissioning run */
    unsigned int  duty;
    unsigned int  t0, tph, step;
    unsigned int  rest1, rest2;
    unsigned int  e1[2], e2[2];      /* track 1/2 at end A, end B            */
    unsigned int  s1[2];             /* track 1 where each drive started     */
    unsigned int  h1, h2;            /* track 1/2 at the end of the hold     */
    unsigned int  out[5];
    unsigned int  detail;
    /* autotune */
    unsigned char above, ready;
    unsigned int  cycles, tcyc, pmin, pmax;
    unsigned int  sum_a, sum_t;
    unsigned int  a_x10, tu_ms, a_live, tu_live;
    unsigned int  k[3];
    /* V97 verify */
    unsigned char vstep, vset;
    unsigned int  vt0, vprev, vsettle, vover, verr, vsum, vn;
    unsigned int  w_settle, w_over, w_err;
    /* the 40 ms means and the stop decision's numbers */
    unsigned int  bs1, bs2, avg1, avg2, prev1;
    unsigned char bn, bvalid;
    unsigned int  p1, lim, disp, hold_ms;
    int           moved;
    /* the measurement behind the decision, published so that a log of
       a failure says what the converter actually saw and not only the
       verdict (the car's own raw data refutes
       the verdict its summary printed). */
    unsigned int  ipv;              /* IPV raw, the amplified TPS1     */
    hc_sweep_t sweep;
    unsigned int  raw1, raw2;       /* both tracks, uncorrected             */
} hc_etbcal_t;

#define E  (*(hc_etbcal_t huge *)(TGT_EXTRAM_BASE + TGT_RAM_ETBCAL))
typedef char hc_etbcal_fits[(sizeof(hc_etbcal_t) <= TGT_RAM_ETBCAL_LIMIT)
                            ? 1 : -1];

static unsigned int udiff(unsigned int a, unsigned int b)
{
    return (unsigned int)((a > b) ? (a - b) : (b - a));
}


static unsigned char sweep_guard(unsigned int rpm, unsigned char armed);
static void finish(unsigned char res, unsigned char why);

static void release(void)
{
    hc_dbw_override(0xFFFFu);          /* the verify ends here too */
    hc_dbw_shutdown(0u);
    /* THE STATE MUST SAY WHAT THE BRIDGE DOES. A procedure that ran the
       closed loop (verify, characterization) left D.st at DBW_RUN with the
       bridge released, and hcfresh711.c then judged the pedal freshness of
       a "running" throttle and latched DBW_F_STALE after every successful
       commission (me711_dbw_deviation_proof, sim: no pedal samples). Normal
       DBW re-enters through INIT like after any release. */
    if (D.st == DBW_RUN || D.st == DBW_INIT) D.st = DBW_OFF;
    E.on = 0u;
    E.duty = 0u;
}

unsigned char far hc_etbcal_supervise(unsigned char why)
{
    if (E.ph == ETB_CAL_IDLE) return 0u;
    if (why == ETB_WHY_NONE && (E.ph == ETB_CAL_SWEEP || E.ph == ETB_CAL_SLAM
                                || E.ph == ETB_CAL_FRICTION))
        why = sweep_guard(trg_rpm, (unsigned char)hc_hal_out_class_live(HC_OUT_THR_EN));
    if (why == ETB_WHY_NONE) {
        extern unsigned int hc_tick_ms;
        if ((unsigned int)(hc_tick_ms - E.step) <= 100u) return 0u;
        why = ETB_WHY_CONTROL;
        hc_dbw_shutdown(DBW_F_STALE);
    }
    /* finish is defined below; the ordinary service consumes this abort.
       Release synchronously here so serial work cannot extend motor drive. */
    finish(ETB_RES_FAIL, why);
    E.req = 0u;
    return 1u;
}

static void finish(unsigned char res, unsigned char why);

static void drive(unsigned char dir, unsigned int duty)
{
    hc_dbw_drive(dir, duty);
    E.on = hc_dbw_bridge_on();
    E.dir = dir;
    E.duty = hc_dbw_duty_x10();
    if (!E.on) finish(ETB_RES_FAIL, ETB_WHY_V_FAULT);
}

static void start(unsigned char tune, unsigned int now_ms);
static void phase(unsigned char ph, unsigned int now_ms);

static void verify_begin(unsigned int now_ms)
{
    release();
    hc_dbw_calibration_begin(now_ms);
    E.ready = 0u;                    /* motor OFF until the release wait ends */
    E.vstep = 0u; E.vset = 0u;
    E.w_settle = 0u; E.w_over = 0u; E.w_err = 0u;
    phase(ETB_CAL_VERIFY, now_ms);
}

static void finish(unsigned char res, unsigned char why)
{
    if(E.proc==ETB_PROC_SWEEP) {
        B.integral_after=B.samples ? (unsigned int)(B.integral_sum/B.samples) : 0u;
        if(res!=ETB_RES_CHARACTERIZED) B.state=BIAS_FAULT;
        else if(B.revision!=hc_cfg_desired_rev) B.state=BIAS_CHANGED;
        else if(hc_dbw_faults() || (eng_sensor_err & (ENG_ERR_TPS1|ENG_ERR_TPS2|ENG_ERR_TPS_DIFF))) B.state=BIAS_FAULT;
        else B.state=bias_propose(&B);
    }
    if (E.proc == ETB_PROC_SWEEP && res == ETB_RES_FAIL) {
        E.detail |= SWEEP_INCONCLUSIVE;
        if (why == ETB_WHY_TRACKS || why == ETB_WHY_RAIL || why == ETB_WHY_STALE
            || why == ETB_WHY_ALIGN || why == ETB_WHY_ADC || why == ETB_WHY_NOSAMPLE
            || why == ETB_WHY_CONTROL) E.detail |= SWEEP_TPS;
    }
    E.p1 = hc_hal_ain_age(HC_AIN_TPS1);
    E.lim = hc_hal_ain_age(HC_AIN_TPS2);
    E.moved = (int)(hc_fresh_reason(HC_AIN_TPS1)
                | (hc_fresh_reason(HC_AIN_TPS2) << 4));
    release();                        /* every exit, no exception */
    if (res == ETB_RES_FAIL) {
        if (why == ETB_WHY_SF) hc_dbw_shutdown(DBW_F_SF);
        else if (why == ETB_WHY_NOTPS || why == ETB_WHY_STALE
                 || why == ETB_WHY_ADC || why == ETB_WHY_NOSAMPLE
                 || why == ETB_WHY_ALIGN || why == ETB_WHY_CONTROL)
            hc_dbw_shutdown(DBW_F_STALE);
        else if (why == ETB_WHY_RAIL || why == ETB_WHY_UNCAL)
            hc_dbw_shutdown(DBW_F_TPS_RANGE);
        else if (why == ETB_WHY_TRACKS) hc_dbw_shutdown(DBW_F_TPS_PAIR);
    }
    if (res == ETB_RES_FAIL) {
        E.newcal = 0u; E.newtune = 0u; E.calok = 0u;
        E.failph = E.ph;
        E.oper = (unsigned char)(why == ETB_WHY_ABORTED);
    }
    E.ph = ETB_CAL_IDLE;
    E.req = 0u;
    E.ready = 0u;
    E.res = res;
    E.why = why;
}

static void phase(unsigned char ph, unsigned int now_ms)
{
    E.ph = ph;
    E.tph = now_ms;
    E.bs1 = 0u; E.bs2 = 0u; E.bn = 0u; E.bvalid = 0u;   /* new means */
}

/* one sample into the running 40 ms means of both tracks. */
static void sample(unsigned int r1, unsigned int r2)
{
    E.bs1 = (unsigned int)(E.bs1 + r1);
    E.bs2 = (unsigned int)(E.bs2 + r2);
    if (++E.bn >= ETB_AVG_N) {
        E.prev1 = E.avg1;
        E.avg1 = (unsigned int)(E.bs1 >> 3);
        E.avg2 = (unsigned int)(E.bs2 >> 3);
        E.bs1 = 0u; E.bs2 = 0u; E.bn = 0u;
        if (E.bvalid < 255u) E.bvalid++;
    }
}

void far hc_etbcal_init(void)
{
    E.ph = ETB_CAL_IDLE; E.req = 0u; E.res = ETB_RES_NONE; E.why = ETB_WHY_NONE;
    E.newcal = 0u; E.newtune = 0u; E.on = 0u; E.dir = 0u; E.duty = 0u;
    E.t0 = 0u; E.tph = 0u; E.step = 0u;
    E.rest1 = 0u; E.rest2 = 0u;
    E.e1[0] = 0u; E.e1[1] = 0u; E.e2[0] = 0u; E.e2[1] = 0u;
    E.s1[0] = 0u; E.s1[1] = 0u; E.h1 = 0u; E.h2 = 0u; E.detail = 0u;
    E.ready = 0u;
    E.above = 0u; E.cycles = 0u; E.tcyc = 0u; E.pmin = 1000u; E.pmax = 0u;
    E.sum_a = 0u; E.sum_t = 0u; E.a_x10 = 0u; E.tu_ms = 0u;
    E.a_live = 0u; E.tu_live = 0u; E.k[0] = 0u; E.k[1] = 0u; E.k[2] = 0u;
    E.proc = ETB_PROC_NONE; E.failph = 0u; E.calok = 0u; E.oper = 0u;
    E.vstep = 0u; E.vset = 0u; E.vt0 = 0u; E.vprev = 0u; E.vsettle = 0u;
    E.vover = 0u; E.verr = 0u; E.vsum = 0u; E.vn = 0u;
    E.w_settle = 0u; E.w_over = 0u; E.w_err = 0u;
    E.bs1 = 0u; E.bs2 = 0u; E.avg1 = 0u; E.avg2 = 0u; E.prev1 = 0u;
    E.bn = 0u; E.bvalid = 0u;
    E.p1 = 0u; E.lim = 0u; E.disp = 0u; E.hold_ms = 0u; E.moved = 0;
    E.ipv = 0u; E.raw1 = 0u; E.raw2 = 0u;
    sweep_begin(&E.sweep, 0u); E.sweep.inhibit = 0u;
    B.integral_after=0u; bias_begin(&B,0u); B.state=BIAS_EMPTY;
}

/* E.req: 1 autocal, 2 autotune, 4 commission, 3 abort, 5/6 the
   direction A/B stop test. */
void far hc_etbcal_request(unsigned char what)
{
    if (what == 7u) { B.pending=1u; return; }
    if (what > 7u) return;
    if (what == 0u && E.ph != ETB_CAL_IDLE) {
        finish(ETB_RES_FAIL, ETB_WHY_ABORTED); E.req = 0u; return;
    }
    E.req = (unsigned char)((what == 6u) ? 7u : (what == 1u) ? 1u : (what == 2u) ? 2u
                            : (what == 3u) ? 4u : (what == 4u) ? 5u
                            : (what == 5u) ? 6u : 3u);
}

unsigned int far hc_etbcal_proc(void)
{
    return (unsigned int)((E.proc & 0x0Fu) | ((E.failph & 0x0Fu) << 4)
                          | (E.calok ? 0x0100u : 0u)
                          | (E.oper ? 0x0200u : 0u));
}

static unsigned int cal_duty(void)
{
    unsigned int d = hc_cal_u16(CAL_DBW_AUTOCAL_DUTY);
    if (d == 0u) d = ETB_DUTY_DEFAULT;
    if (d < ETB_DUTY_MIN) d = ETB_DUTY_MIN;
    if (d > ETB_DUTY_MAX) d = ETB_DUTY_MAX;
    return d;
}

static unsigned int cal_hold(void)
{
    unsigned int h = hc_cal_u16(CAL_DBW_AUTOCAL_MS);
    if (h == 0u) h = ETB_HOLD_DEFAULT;
    if (h < ETB_HOLD_MIN) h = ETB_HOLD_MIN;
    if (h > ETB_HOLD_MAX) h = ETB_HOLD_MAX;
    return h;
}

static unsigned int tune_amp(void)
{
    unsigned int a = hc_cal_u16(CAL_DBW_TUNE_AMP);
    if (a == 0u) a = AT_AMP_DEFAULT;
    if (a < AT_AMP_MIN) a = AT_AMP_MIN;
    if (a > AT_AMP_MAX) a = AT_AMP_MAX;
    return a;
}

/* 0..50: where `v` sits between `closed` and `open`, 2 % per unit. */
static unsigned int frac50(unsigned int v, unsigned int closed,
                           unsigned int open)
{
    unsigned int span = udiff(open, closed);
    unsigned int d = udiff(v, closed);
    if (span == 0u) return 0u;
    if (d > span) d = span;
    return (unsigned int)((d * 50u) / span);
}

static void evaluate(void)
{
    unsigned char k;
    unsigned int f1, f2;

    if (udiff(E.e1[0], E.e1[1]) < ETB_SPAN_MIN
        || udiff(E.e2[0], E.e2[1]) < ETB_SPAN_MIN) {
        E.detail = udiff(E.e1[0], E.e1[1]);
        finish(ETB_RES_FAIL,
               (udiff(E.e1[0], E.s1[0]) < ETB_MOVED_MIN) ? ETB_WHY_NOMOVE_A
               : (udiff(E.e1[1], E.s1[1]) < ETB_MOVED_MIN) ? ETB_WHY_NOMOVE_B
               : ETB_WHY_SPAN);
        return;
    }
    /* The rest must lie between the two ends (a limp opening, or at the
       closed stop); anything else means an end was not an end. */
    if ((E.rest1 + 5u < E.e1[0] && E.rest1 + 5u < E.e1[1])
        || (E.rest1 > E.e1[0] + 5u && E.rest1 > E.e1[1] + 5u)
        || (E.rest2 + 5u < E.e2[0] && E.rest2 + 5u < E.e2[1])
        || (E.rest2 > E.e2[0] + 5u && E.rest2 > E.e2[1] + 5u)) {
        E.detail = E.rest1;
        finish(ETB_RES_FAIL, ETB_WHY_REST);
        return;
    }
    /* The closed end is the one nearer the unpowered rest position. */
    k = (unsigned char)(udiff(E.e1[1], E.rest1) < udiff(E.e1[0], E.rest1));
    /* Both tracks must put the rest at the same fraction of travel. */
    f1 = frac50(E.rest1, E.e1[k], E.e1[!k]);
    f2 = frac50(E.rest2, E.e2[k], E.e2[!k]);
    if (udiff(f1, f2) > ETB_TRACK_TOL) {
        E.detail = (unsigned int)((f1 << 8) | f2);
        finish(ETB_RES_FAIL, ETB_WHY_TRACKS);
        return;
    }
    E.out[0] = E.e1[k];
    E.out[1] = E.e1[!k];
    E.out[2] = E.e2[k];
    E.out[3] = E.e2[!k];
    /* k == 1: end B was closed, so leg 0 (end A) OPENED -> Normal (0). */
    E.out[4] = (unsigned int)(k ? 0u : 1u);
    E.detail = 0u;
    E.newcal = (unsigned char)(E.proc != ETB_PROC_COMMISSION);
    if ((E.e1[1] > E.e1[0]) == (E.e2[1] > E.e2[0])) {
        E.newcal = 0u;
        finish(ETB_RES_FAIL, ETB_WHY_TRACKS);
        return;
    }
    E.calok = 1u;
    if (E.proc == ETB_PROC_COMMISSION) {
        /* V93 COMMISSION: the endpoints passed every check, so continue
           straight into the PID autotune. It normalises with the endpoints
           just measured (E.out), not the page, so it does not wait for the
           config manager to apply them; if the autotune then fails, the
           candidates remain private until verification passes. */
        release();
        start(1u, E.step);
        return;
    }
    finish(ETB_RES_PASS, ETB_WHY_NONE);
}

static void cal_step(unsigned int now_ms, unsigned int r1, unsigned int r2)
{
    unsigned int el = (unsigned int)(now_ms - E.tph);
    unsigned char k = (unsigned char)(E.ph == ETB_CAL_DRIVE_B
                                      || E.ph == ETB_CAL_PUSH_B);

    sample(r1, r2);
    switch (E.ph) {
    case ETB_CAL_REST:
        if (el >= ETB_REST_MS) {
            /* the rest is a 40 ms mean too (REST_MS is 50) */
            E.rest1 = E.bvalid ? E.avg1 : r1;
            E.rest2 = E.bvalid ? E.avg2 : r2;
            k = (unsigned char)(E.proc == ETB_PROC_DIR_B);
            E.s1[k] = E.rest1;
            phase(k ? ETB_CAL_DRIVE_B : ETB_CAL_DRIVE_A, now_ms);
            drive(k, cal_duty());
        }
        return;

    case ETB_CAL_DRIVE_A:
    case ETB_CAL_DRIVE_B:
        if (el < cal_hold()) return;
        if (E.bvalid == 0u) {
            finish(ETB_RES_FAIL, hc_fresh_tps_why());
            return;
        }
        E.h1 = E.e1[k] = E.avg1;
        E.h2 = E.e2[k] = E.avg2;
        E.hold_ms = el;
        E.disp = udiff(E.h1, E.rest1);
        release();
        /* A direction may already be at its endpoint, especially CLOSED.
           rusEFI judges the span BETWEEN the two driven endpoints, not
           displacement from spring rest on each leg. A bench direction is
           just a bounded capture, including an already-closed plate. */
        if (E.proc == ETB_PROC_DIR_A || E.proc == ETB_PROC_DIR_B) {
            /* A bounded position capture, never a physical stop verdict. */
            finish(ETB_RES_CAPTURED, ETB_WHY_NONE);
            return;
        }
        phase(k ? ETB_CAL_BACK_B : ETB_CAL_BACK_A, now_ms);
        return;

    case ETB_CAL_BACK_A:
        if (el >= ETB_BACK_MS) {
            /* Release is timed; spring hysteresis is not a motor failure. */
            E.s1[1] = r1;
            phase(ETB_CAL_DRIVE_B, now_ms);
            drive(1u, cal_duty());
        }
        return;

    case ETB_CAL_BACK_B:
    default:
        if (el >= ETB_BACK_MS) {
            evaluate();
        }
        return;
    }
}

/* Returns the mask of gains clipped to their page field (bit 0 KP, 1 KI,
   2 KD). */
static unsigned char tune_publish_candidate(unsigned int a, unsigned int t)
{
    unsigned int kk[3];            /* near (stack): hc_dbw_gains takes near */
    unsigned char clip;

    if (a < AT_A_MIN) a = AT_A_MIN;
    if (t < 5u) t = 5u;
    clip = hc_dbw_gains(a, t, kk);
    E.k[0] = kk[0]; E.k[1] = kk[1]; E.k[2] = kk[2];
    return clip;
}

static void tune_step(unsigned int now_ms, unsigned int pos)
{
    unsigned char above = (unsigned char)(pos > AT_TARGET_X10);
    int out;
    unsigned int amp = tune_amp(), mag, bias;
    unsigned char opening, cfgdir;

    if (E.ph == ETB_CAL_APPROACH) {
        if (pos > E.pmax) E.pmax = pos;
        if (above) {
            phase(ETB_CAL_TUNE, now_ms);
            E.tcyc = now_ms;
            E.pmin = 1000u; E.pmax = 0u;
        } else if ((unsigned int)(now_ms - E.tph) >= AT_APPROACH_MS) {
            E.detail = E.pmax;
            finish(ETB_RES_FAIL, ETB_WHY_UNREACHED);
            return;
        }
    } else {
        if (pos < AT_BAND_LO || pos > AT_BAND_HI) {
            E.detail = pos;
            finish(ETB_RES_FAIL, ETB_WHY_BAND);
            return;
        }
        if (pos < E.pmin) E.pmin = pos;
        if (pos > E.pmax) E.pmax = pos;
        /* End of a relay cycle: the plate crossed back below the target. */
        if (!above && E.above) {
            unsigned int a = (E.pmax > E.pmin) ? (unsigned int)(E.pmax - E.pmin)
                                               : 0u;
            unsigned int t = (unsigned int)(now_ms - E.tcyc);
            if (t > AT_TU_CLAMP) t = AT_TU_CLAMP;
            E.a_live = a;
            E.tu_live = t;
            if (E.cycles >= AT_WARM) {
                E.sum_a = (unsigned int)(E.sum_a + a);
                E.sum_t = (unsigned int)(E.sum_t + t);
            }
            E.cycles++;
            E.tcyc = now_ms;
            E.pmin = 1000u;
            E.pmax = 0u;
            (void)tune_publish_candidate(a, t);
            if (E.cycles >= AT_WARM + AT_MEASURE) {
                E.a_x10 = (unsigned int)(E.sum_a / AT_MEASURE);
                E.tu_ms = (unsigned int)(E.sum_t / AT_MEASURE);
                if (E.a_x10 < AT_A_MIN || E.a_x10 > AT_A_MAX
                    || E.tu_ms < AT_TU_MIN || E.tu_ms > AT_TU_MAX) {
                    E.detail = E.a_x10;
                    finish(ETB_RES_FAIL, ETB_WHY_IMPLAUS);
                    return;
                }
                /* A gain larger than its page field holds (KI above 65.5 /s
                   is the realistic one at a 5 ms raster) is written at the
                   field's maximum - LOWER than the rule, the conservative
                   side - and said: detail bit 15 + the clipped mask. */
                {
                    unsigned char clip = tune_publish_candidate(E.a_x10,
                                                                E.tu_ms);
                    E.detail = clip ? (unsigned int)(0x8000u | clip) : 0u;
                }
                /* A relay rule is an initial estimate, not a verified
                   controller. Standalone PID uses the same response gate. */
                E.newtune = 0u;
                E.above = 0u;          /* verification damping attempt count */
                E.t0 = now_ms;         /* bounded across every attempt */
                verify_begin(now_ms);
                return;
            }
        }
    }
    E.above = above;
    bias = hc_cal_curve16(CAL_DBW_BIAS_AX, CAL_DBW_BIAS_VAL, 8u, AT_TARGET_X10);
    out = (int)bias - (int)DBW_BIAS_ZERO + (above ? -(int)amp : (int)amp);
    opening = (unsigned char)(out >= 0);
    mag = (unsigned int)(out < 0 ? -out : out);
    if (mag > ETB_DUTY_MAX) mag = ETB_DUTY_MAX;
    cfgdir = E.calok ? (unsigned char)E.out[4]
                     : hc_cal_u8(CFG_U_DBW_MOTOR_DIR);
    drive((unsigned char)(cfgdir ? opening : !opening), mag);
}

/* one 5 ms verify step. The closed loop (hc_dbw.c) runs on its own
   raster this pass; this only moves the target and grades the plate. */
static void verify_step(unsigned int now_ms, unsigned int rpm,
                        unsigned char armed)
{
    unsigned int el = (unsigned int)(now_ms - E.tph);
    unsigned int act, q, e, over;

    if (rpm != 0u) {
        finish(ETB_RES_FAIL, ETB_WHY_TURNING);
        return;
    }
    if (!armed || !hc_hal_outputs_live()) {
        finish(ETB_RES_FAIL, ETB_WHY_NOTLIVE);
        return;
    }
    if (hc_dbw_state() == DBW_FAULT
        && (hc_dbw_faults() & (unsigned int)~(DBW_F_APP_PAIR | DBW_F_APP_RANGE))) {
        E.detail = hc_dbw_faults();
        finish(ETB_RES_FAIL, ETB_WHY_V_FAULT);
        return;
    }
    if (!hc_hal_ain_ok(HC_AIN_TPS1) || !hc_hal_ain_ok(HC_AIN_TPS2)) {
        finish(ETB_RES_FAIL, hc_fresh_tps_why());
        return;
    }
    if ((unsigned int)(now_ms - E.t0) > VFY_RUN_MAX) {
        finish(ETB_RES_FAIL, ETB_WHY_TIMEOUT);
        return;
    }
    if (!E.ready) {
        /* Every gain change begins with a motor-OFF release, zeroed loop
           state and the same fresh-source/latched-fault guards. */
        if (el < ETB_BACK_MS) return;
        hc_dbw_override(AT_TARGET_X10);
        E.ready = 1u;
        E.vset = 0u;
        E.verr = hc_dbw_actual_x10();
        E.tph = now_ms;
        return;
    }
    if (el < VFY_SETTLE_MS) {
        return;                         /* allow the controller to settle on private candidates */
    }
    if (E.vstep == 0u) {
        /* A step response must begin from a settled plate, not from a
           fixed-time point in the preceding approach's overshoot. */
        act = hc_dbw_actual_x10();
        if (udiff(act, AT_TARGET_X10) <= VFY_BAND && udiff(act, E.verr) <= 5u) {
            if (E.vset < 8u) E.vset++;
        } else E.vset = 0u;
        E.verr = act;
        if (E.vset < 8u) {
            if (el >= AT_APPROACH_MS) {
                /* A candidate that cannot hold 50 % steadily is the same
                   finding as one that overshoots: too much P/D for this
                   plant. Damp and retest within the same bounded budget
                   (bench, 2026-10-05: every failed autotune hunted here on
                   the undamped relay gains; every pass had been halved). */
                if (E.above < VFY_RETRIES) {
                    E.k[0] >>= 1; E.k[2] >>= 1;
                    E.above++;
                    verify_begin(now_ms);
                    return;
                }
                E.detail = 0u;
                finish(ETB_RES_FAIL, ETB_WHY_V_SLOW);
            }
            return;
        }
    }
    if (E.vstep == 0u || (unsigned int)(now_ms - E.vt0) >= VFY_STEP_MS) {
        if (E.vstep != 0u) {
            /* grade the step that just ended */
            e = E.vn ? (unsigned int)(E.vsum / E.vn) : 0xFFFFu;
            if (!E.vset) E.vsettle = VFY_STEP_MS;
            if (E.vsettle > E.w_settle) E.w_settle = E.vsettle;
            if (E.vover > E.w_over) E.w_over = E.vover;
            if (e > E.w_err) E.w_err = e;
            if (!E.vset || E.vsettle > VFY_SETTLE_MAX) {
                E.detail = E.vstep;
                finish(ETB_RES_FAIL, ETB_WHY_V_SLOW);
                return;
            }
            if (E.vover > VFY_OVER_MAX) {
                if (E.above < VFY_RETRIES) {
                    /* Reduce proportional/derivative aggression while
                       retaining integral recovery against spring/friction.
                       Retest ALL five targets from the start.
                       Sensor, supply and bridge faults never enter here. */
                    E.k[0] >>= 1; E.k[2] >>= 1;
                    E.above++;
                    verify_begin(now_ms);
                    return;
                }
                E.detail = E.vstep;
                finish(ETB_RES_FAIL, ETB_WHY_V_OVER);
                return;
            }
            if (e > VFY_ERR_MAX) {
                if (E.above < VFY_RETRIES && E.k[1] < 65535u) {
                    /* A settled plate can still need more integral recovery
                       after spring/friction reversal. Do not relax the tail
                       error limit or publish the unverified candidate. */
                    E.k[1] = E.k[1] >= 32768u ? 65535u
                                             : (unsigned int)(E.k[1] << 1);
                    E.above++;
                    verify_begin(now_ms);
                    return;
                }
                E.detail = E.vstep;
                finish(ETB_RES_FAIL, ETB_WHY_V_ERROR);
                return;
            }
            if (E.vstep >= VFY_STEPS) {
                /* attempts in bits 8..9; KEEP the autotune's clipped-gain
                   report (bit 15 + mask) - it was overwritten here, so a
                   gain written at its field maximum was never said. */
                E.detail = (unsigned int)((E.detail & 0x8007u) | (E.above << 8));
                E.vstep = (unsigned char)(E.vstep | 0x80u);
                E.newcal = E.calok; E.newtune = 1u;
                finish(E.proc == ETB_PROC_COMMISSION ? ETB_RES_COMMISSIONED
                                                       : ETB_RES_TUNED,
                       ETB_WHY_NONE);
                return;
            }
        }
        E.vprev = (E.vstep == 0u) ? hc_dbw_actual_x10()
                                  : vfy_tgt[E.vstep - 1u];
        E.vstep++;
        E.vt0 = now_ms;
        E.vset = 0u; E.vsettle = 0u; E.vover = 0u; E.vsum = 0u; E.vn = 0u;
        hc_dbw_override(vfy_tgt[E.vstep - 1u]);
        return;
    }
    q = vfy_tgt[E.vstep - 1u];
    act = hc_dbw_actual_x10();
    e = udiff(act, q);
    over = (q >= E.vprev) ? ((act > q) ? (unsigned int)(act - q) : 0u)
                          : ((act < q) ? (unsigned int)(q - act) : 0u);
    if (over > E.vover) E.vover = over;
    if (!E.vset && e <= VFY_BAND) {
        E.vset = 1u;
        E.vsettle = (unsigned int)(now_ms - E.vt0);
    }
    if ((unsigned int)(now_ms - E.vt0) >= (unsigned int)(VFY_STEP_MS - VFY_TAIL_MS)) {
        E.vsum = (unsigned int)(E.vsum + e);
        E.vn++;
    }
}

static void step(unsigned int now_ms, unsigned int rpm, unsigned char armed)
{
    unsigned int r1, r2, sample_ms;
    unsigned char tune = (unsigned char)(E.ph == ETB_CAL_TUNE_REST
                                         || E.ph == ETB_CAL_TUNE
                                         || E.ph == ETB_CAL_APPROACH);

    if (rpm != 0u) {
        finish(ETB_RES_FAIL, ETB_WHY_TURNING);
        return;
    }
    if (!armed || !hc_hal_outputs_live()) {
        finish(ETB_RES_FAIL, ETB_WHY_NOTLIVE);
        return;
    }
    if (!hc_hal_ain_ok(HC_AIN_TPS1) || !hc_hal_ain_ok(HC_AIN_TPS2)) {
        finish(ETB_RES_FAIL, hc_fresh_tps_why());
        return;
    }
    r1 = hc_hal_ain(HC_AIN_TPS1);
    r2 = hc_hal_ain(HC_AIN_TPS2);
    if (r1 < ETB_ADC_LO || r1 > ETB_ADC_HI
        || r2 < ETB_ADC_LO || r2 > ETB_ADC_HI) {
        E.detail = (r1 < ETB_ADC_LO || r1 > ETB_ADC_HI) ? r1 : r2;
        finish(ETB_RES_FAIL, ETB_WHY_RAIL);
        return;
    }
    E.p1 = hc_hal_ain_age(HC_AIN_TPS1);
    E.lim = hc_hal_ain_age(HC_AIN_TPS2);
    E.moved = (int)(hc_fresh_reason(HC_AIN_TPS1)
                | (hc_fresh_reason(HC_AIN_TPS2) << 4));
    if (!hc_fresh_tps_pair(&r1, &r2, &sample_ms)) {
        /* A first scan may not bracket both tracks yet. Remain unpowered
           while gathering history; never keep an existing drive alive. */
        if (!E.on && (unsigned int)(now_ms - E.t0) <= 100u) return;
        finish(ETB_RES_FAIL, ETB_WHY_ALIGN);
        return;
    }
    E.ipv = hc_hal_ain(HC_AIN_TPS1_AMP);
    E.raw1 = r1;
    E.raw2 = r2;
    /* Uncalibrated independent tracks need not sum to full ADC scale, and
       MAIN scans them at different instants. Judge their endpoint spans,
       opposing direction, spring return and normalized rest fraction in
       evaluate(); VERIFY then uses the normal calibrated pair monitor. */
    /* SF is LOW whenever the bridge is disabled (CJ220 rows 5, 6, 9): judge
       it only while this procedure has the bridge enabled. */
    if (E.on && hc_hal_dbw_sf_faulted()) {
        finish(ETB_RES_FAIL, ETB_WHY_SF);
        return;
    }
    if ((unsigned int)(now_ms - E.t0) > (tune ? AT_RUN_MS : ETB_RUN_MAX)) {
        finish(ETB_RES_FAIL, ETB_WHY_TIMEOUT);
        return;
    }
    if (tune) {
        unsigned char ok, ok2;
        unsigned int lo1, hi1, lo2, hi2, pos, pos2;
        if (E.calok) {                  /* commission: just measured */
            lo1 = E.out[0]; hi1 = E.out[1];
            lo2 = E.out[2]; hi2 = E.out[3];
        } else {                        /* autotune only: the stored ones */
            lo1 = hc_cal_u16(CAL_TPS1_MIN); hi1 = hc_cal_u16(CAL_TPS1_MAX);
            lo2 = hc_cal_u16(CAL_TPS2_MIN); hi2 = hc_cal_u16(CAL_TPS2_MAX);
            if (udiff(lo1, hi1) < ETB_SPAN_MIN
                || udiff(hc_cal_u16(CAL_TPS2_MIN), hc_cal_u16(CAL_TPS2_MAX))
                   < ETB_SPAN_MIN) {
                E.detail = udiff(lo1, hi1);
                finish(ETB_RES_FAIL, ETB_WHY_NOENDPTS);
                return;
            }
        }
        pos = hc_dbw_normalise(r1, lo1, hi1, &ok);
        pos2 = hc_dbw_normalise(r2, lo2, hi2, &ok2);
        if (!ok || !ok2) {
            finish(ETB_RES_FAIL, ETB_WHY_UNCAL);
            return;
        }
        if ((!E.calok && hc_cal_u8(CFG_U_TPS_CORR) == HC_TRACK_OPPOSITE
             ? udiff(pos, (unsigned int)(1000u - pos2)) : udiff(pos, pos2))
            > hc_cal_u16(CFG_U_TPS_TOL_X10)) {
            E.detail = pos2;
            finish(ETB_RES_FAIL, ETB_WHY_TRACKS);
            return;
        }
        if (E.ph == ETB_CAL_TUNE_REST) {
            /* A timed endpoint release is not evidence that the spring or
               staggered ADC tracks have settled. Qualify 40 ms below the
               relay target, then start a fresh approach timer/history. */
            if (pos < AT_TARGET_X10 - 50u && udiff(pos, E.pmax) <= 5u) {
                if (E.ready < 8u) E.ready++;
            } else E.ready = 0u;
            E.pmax = pos;
            if ((unsigned int)(now_ms - E.tph) >= ETB_REST_MS && E.ready >= 8u) {
                E.above = 0u; E.pmin = 1000u; E.pmax = 0u;
                E.tcyc = now_ms;
                phase(ETB_CAL_APPROACH, now_ms);
            } else if ((unsigned int)(now_ms - E.tph) >= AT_APPROACH_MS) {
                E.detail = pos;
                finish(ETB_RES_FAIL, ETB_WHY_UNSETTLED);
            }
            return;
        }
        tune_step(now_ms, pos);
        return;
    }
    cal_step(now_ms, r1, r2);
}

static void start(unsigned char tune, unsigned int now_ms)
{
    hc_dbw_calibration_begin(now_ms);
    E.ready = 0u;
    E.on = 0u; E.duty = 0u; E.dir = 0u;
    E.res = ETB_RES_RUN;
    E.why = ETB_WHY_NONE;
    E.detail = 0u;
    E.t0 = now_ms;
    E.step = now_ms;
    E.above = 0u; E.cycles = 0u; E.tcyc = now_ms;
    E.pmin = 1000u; E.pmax = 0u;
    E.sum_a = 0u; E.sum_t = 0u; E.a_live = 0u; E.tu_live = 0u;
    if (tune) {
        E.a_x10 = 0u; E.tu_ms = 0u;
        E.k[0] = 0u; E.k[1] = 0u; E.k[2] = 0u;
    }
    phase(tune ? ETB_CAL_TUNE_REST : ETB_CAL_REST, now_ms);
}


/* Every main-loop pass AND serial yield: no debounce permits a suspect TPS
   to resume this test. SF is meaningful only after bridge enable (CJ220). */
static unsigned char sweep_guard(unsigned int rpm, unsigned char armed)
{
    unsigned int a, b, ms, x, y;
    unsigned char ok1, ok2;
    if (rpm || trg_state != TRG_NO_SIGNAL) return ETB_WHY_TURNING;
    if (!(P6 & (1u << TGT_KL15STAT_PORT_BIT)) || !armed
        || !hc_hal_out_class_live(HC_OUT_THR_EN) || !hc_hal_outputs_live())
        return ETB_WHY_NOTLIVE;
    if (!hc_hal_ain_ok(HC_AIN_TPS1) || !hc_hal_ain_ok(HC_AIN_TPS2))
        return hc_fresh_tps_why();
    if (hc_cal_u16(CAL_DBW_SF_MODE) == HC_DBW_SF_IGNORE) return ETB_WHY_SF;
    if (hc_etbcal_config_faults(1u)) return ETB_WHY_NOENDPTS;
    if (hc_etbcal_rail_faults(1u)) return ETB_WHY_RAIL;
    if (!hc_fresh_tps_pair(&a, &b, &ms)) return ETB_WHY_ALIGN;
    B.fms_now = ms;
    x = hc_dbw_normalise(a, hc_cal_u16(CAL_TPS1_MIN), hc_cal_u16(CAL_TPS1_MAX), &ok1);
    y = hc_dbw_normalise(b, hc_cal_u16(CAL_TPS2_MIN), hc_cal_u16(CAL_TPS2_MAX), &ok2);
    if (!ok1 || !ok2) return ETB_WHY_UNCAL;
    if (hc_cal_u8(CFG_U_TPS_CORR) == HC_TRACK_OPPOSITE) y = 1000u - y;
    E.h1 = x; E.h2 = y;
    if (udiff(x,y) > E.sweep.pairmax) E.sweep.pairmax = udiff(x,y);
    if (udiff(x,y) > hc_cal_u16(CFG_U_TPS_TOL_X10)) return ETB_WHY_TRACKS;
    if (hc_dbw_bridge_on() && hc_hal_dbw_sf_faulted()) return ETB_WHY_SF;
    if (hc_dbw_faults() & (unsigned int)~(DBW_F_APP_PAIR | DBW_F_APP_RANGE))
        return ETB_WHY_V_FAULT;
    return ETB_WHY_NONE;
}

/* ------------------------------------------------ break-away edges ----
   Per position: the closed loop brings the plate near the position and it
   stays STILL for FRIC_QUIET steps (stiction leaves it a few counts off the
   target, and that is irrelevant to where the band edges are),
   then the loop opens at the command that was holding the plate - inside
   the friction band by definition, since the plate is still - and the
   command ramps FRIC_RATE per step until the plate moves FRIC_MOVE beyond
   its settled mean on two consecutive FRESH acquisitions. No P, I or D acts
   during a ramp. The edge is the command at the first of those two samples,
   so the acquisition lag biases both edges outward equally: the midpoint is
   unbiased, the width slightly over-stated. The closed loop then takes the
   plate back (integrator untouched: a bumpless hand-back) and settles again
   for the next trial. Every guard of the sweep stays active throughout. */
#define FRIC_SETTLE_MIN  250u   /* ms of closed loop before a trial          */
#define FRIC_SETTLE_MAX 2000u   /* could not hold the position: exclude it   */
#define FRIC_QUIET        30u   /* 150 ms consecutive, stationary            */
#define FRIC_NEAR         30u   /* counts from the position: near enough -
                                   a wrong bias can leave the clamped
                                   integrator short of it (60 %: 58.3) */
#define FRIC_STILL         3u   /* counts from the streak's first sample     */
#define FRIC_MOVE          6     /* counts beyond the settled mean           */
#define FRIC_DRIFT        12     /* counts the wrong way voids the trial     */
#define FRIC_RATE          1     /* 0.1 % duty per 5 ms = 20 %/s             */
#define FRIC_SPAN        500     /* at most 50 % duty from the held command  */

static void fric_settle(unsigned int now)
{
    B.fsub = 0u; B.fn = 0u; B.fsum = 0uL; B.fmov = 0u; B.ft = now;
    E.sweep.segment = (unsigned char)(SWEEP_COUNT + B.fj);   /* telemetry 60.. */
    hc_dbw_override(bias_positions[B.fj]);
}

static unsigned char fric_wanted(unsigned char j)
{
    return (unsigned char)(bias_positions[j] >= B.min_target
                           && bias_positions[j] <= B.max_target);
}

/* Opening, then closing, FRIC_REPS times; then the next position. */
static void fric_next(unsigned int now)
{
    if (B.fe) B.fe = 0u;
    else { B.fe = 1u; if (++B.fr >= FRIC_REPS) { B.fr = 0u; B.fj++; } }
    while (B.fj < BIAS_POINTS && !fric_wanted(B.fj)) B.fj++;
    if (B.fj >= BIAS_POINTS) { finish(ETB_RES_CHARACTERIZED, ETB_WHY_NONE); return; }
    fric_settle(now);
}

/* A failed trial excludes the position; its remaining trials are skipped. */
static void fric_fail(unsigned char why, unsigned int now)
{
    if (!B.fail[B.fj]) B.fail[B.fj] = why;
    B.fr = FRIC_REPS - 1u; B.fe = 0u;
    fric_next(now);
}

static void fric_begin(unsigned int now)
{
    phase(ETB_CAL_FRICTION, now); E.t0 = now;
    B.fj = 0u; B.fr = 0u; B.fe = 1u;
    while (B.fj < BIAS_POINTS && !fric_wanted(B.fj)) B.fj++;
    if (B.fj >= BIAS_POINTS) { finish(ETB_RES_CHARACTERIZED, ETB_WHY_NONE); return; }
    fric_settle(now);
}

static void fric_drive(int u)
{
    unsigned char opening = (unsigned char)(u >= 0);
    unsigned char cfgdir = hc_cal_u8(CFG_U_DBW_MOTOR_DIR);
    D.out_t = u;
    drive((unsigned char)(cfgdir ? opening : !opening),
          (unsigned int)(u < 0 ? -u : u));
}

static void fric_tick(unsigned int now)
{
    unsigned int x = E.h1;
    int d;
    if (!B.fsub) {
        if (D.st != DBW_RUN || udiff(x, bias_positions[B.fj]) > FRIC_NEAR) {
            B.fn = 0u; B.fsum = 0uL;
        } else if (B.fn && udiff(x, B.fref) <= FRIC_STILL) {
            if (B.fn < 255u) { B.fn++; B.fsum += x; }
        } else { B.fn = 1u; B.fsum = x; B.fref = x; }   /* streak anchor */
        if (B.fn >= FRIC_QUIET && (unsigned int)(now - B.ft) >= FRIC_SETTLE_MIN) {
            B.fref = sweep_mean_abs((long)B.fsum, B.fn);
            B.fu0 = B.fu = D.out_t;
            B.fms = B.fms_now; B.fsub = 1u; B.ft = now;
            /* telemetry: 70+j opening ramp, 80+j closing ramp */
            E.sweep.segment = (unsigned char)(SWEEP_COUNT + (B.fe ? 10u : 20u) + B.fj);
            fric_drive(B.fu);              /* same command: plate stays */
        } else if ((unsigned int)(now - B.ft) >= FRIC_SETTLE_MAX)
            fric_fail(BIAS_UNSETTLED, now);
        return;
    }
    D.act = x;                            /* the loop is open: publish it */
    if (B.fms_now != B.fms) {             /* one verdict per acquisition */
        B.fms = B.fms_now;
        d = B.fe ? (int)x - (int)B.fref : (int)B.fref - (int)x;
        if (d >= FRIC_MOVE) {
            if (!B.fmov) B.fcross = B.fu;
            if (++B.fmov >= 2u) {
                bias_edge(&B, B.fcross);
                fric_next(now);
                return;
            }
        } else {
            B.fmov = 0u;
            if (d <= -FRIC_DRIFT) { fric_fail(BIAS_DRIFT, now); return; }
        }
    }
    if (sweep_abs(B.fu - B.fu0) >= (unsigned int)FRIC_SPAN
        || (E.on && E.duty >= hc_cal_u16(CFG_U_DBW_MAX_DUTY_X10))) {
        fric_fail(BIAS_SATURATION, now);
        return;
    }
    B.fu += B.fe ? FRIC_RATE : -FRIC_RATE;
    fric_drive(B.fu);
}

static void sweep_tick(unsigned int now)
{
    unsigned int elapsed, target, duration, vb;
    unsigned char seg = E.sweep.segment;
    if (!E.ready) {
        if ((unsigned int)(now - E.tph) < 400u) return;
        E.ready = 1u; E.sweep.step_start = now; E.sweep.origin = E.h1;
        hc_dbw_override(100u); return;
    }
    elapsed = (unsigned int)(now - E.sweep.step_start);
    duration = sweep_duration(seg);
    if (elapsed >= duration) {
        sweep_segment_end(&E.sweep, duration);
        E.sweep.origin = seg >= SWEEP_SLAM_START ? D.tgt : (unsigned int)sweep_positions[seg] * 10u;
        if (++seg >= SWEEP_COUNT) {
            sweep_classify(&E.sweep);
            /* Deliberate target slew is recorded independently of findings. */
            E.detail |= E.sweep.flags;
            E.k[0] = E.sweep.settle; E.k[1] = E.sweep.over; E.k[2] = E.sweep.steady;
            fric_begin(now); return;
        }
        if (seg == SWEEP_SLAM_START) {
            sweep_classify(&E.sweep); E.detail = E.sweep.flags;
            E.w_settle = E.sweep.settle; E.w_over = E.sweep.over; E.w_err = E.sweep.steady;
            E.sum_a = sweep_rms(&E.sweep);
            E.sum_t = E.sweep.samples ? (unsigned int)((unsigned long)E.sweep.saturated * 1000u / E.sweep.samples) : 0u;
            sweep_begin(&E.sweep, now); E.sweep.origin = D.tgt;
            phase(ETB_CAL_SLAM, now); E.t0 = now;   /* each section its own 60 s */
        }
        E.sweep.segment = seg; E.sweep.step_start = now;
        E.sweep.quiet = 0u; E.sweep.quiet_start = 0u; E.sweep.rose = 0u;
        E.sweep.tail_n = 0u; E.sweep.tail_error = 0L; E.sweep.tail_i = 0L;
        elapsed = 0u;
    }
    if (seg >= SWEEP_SLAM_START) {
        target = 0x8000u | sweep_app(seg, elapsed);
        if (udiff(D.requested,D.tgt) > 5u) E.detail |= SWEEP_RATE;
    } else target = sweep_target(seg, elapsed, E.sweep.origin);
    /* Measure the prior executed control step BEFORE changing its request. */
    vb = hc_hal_ain_ok(HC_AIN_VBAT)
        ? (unsigned int)((unsigned long)hc_hal_ain(HC_AIN_VBAT)
                         * cfg_u16(CFG_ADC_BATT_FS_DV) / 1023u) : 0u;
    if (vb && vb < E.a_live) E.a_live = vb;
    if (vb > E.tu_live) E.tu_live = vb;
    if (D.st == DBW_RUN)
        sweep_measure(&E.sweep, elapsed, D.tgt, D.act, D.duty,
            hc_cal_u16(CFG_U_DBW_MAX_DUTY_X10), D.out_t, (int)D.integ, vb, E.sweep.pairmax);
    if (seg < SWEEP_RAMP_START && D.st == DBW_RUN)
        bias_hold(&B,elapsed,duration,D.prev_sample_ms,D.tgt,D.act,
                  D.p_t,D.d_t,(int)D.integ);
    hc_dbw_override(target);
}

unsigned char far hc_etbcal_service(unsigned int now_ms, unsigned int rpm,
                                    unsigned char armed,
                                    unsigned char dbw_running)
{
    if (E.req != 0u) {
        unsigned char q = E.req;
        E.req = 0u;
        if (q == 3u) {
            if (E.ph != ETB_CAL_IDLE) {
                finish(ETB_RES_FAIL, ETB_WHY_ABORTED);
                return 1u;
            }
        } else if (E.ph == ETB_CAL_IDLE) {
            unsigned int nv=hc_nvm_state();
            if(nv==HCNV_ST_PENDING || nv==HCNV_ST_ARMED || nv==HCNV_ST_COMMITTING || nv==HCNV_ST_STAGING) {
                E.res=ETB_RES_FAIL; E.why=ETB_WHY_RUNNING; return 1u;
            }
            E.proc = (unsigned char)((q == 7u) ? ETB_PROC_SWEEP : (q == 1u) ? ETB_PROC_AUTOCAL
                                     : (q == 2u) ? ETB_PROC_AUTOTUNE
                                     : (q == 5u) ? ETB_PROC_DIR_A
                                     : (q == 6u) ? ETB_PROC_DIR_B
                                     : ETB_PROC_COMMISSION);
            E.newcal = 0u; E.newtune = 0u;
            E.failph = 0u; E.calok = 0u; E.oper = 0u;
            if (q == 7u) {
                unsigned char j;
                bias_begin(&B,hc_cfg_desired_rev);
                B.min_target=hc_cal_u16(CAL_DBW_MIN_X10);
                B.max_target=hc_cal_u16(CAL_DBW_MAX_X10);
                for(j=0u;j<8u;j++) {
                    B.axis[j]=hc_cal_u16(CAL_DBW_BIAS_AX+2u*j);
                    B.current[j]=B.proposed[j]=hc_cal_u16(CAL_DBW_BIAS_VAL+2u*j);
                }
                release(); sweep_begin(&E.sweep, now_ms);
                E.a_live = 65535u; E.tu_live = 0u; E.detail = 0u;
                E.sum_a = 0u; E.sum_t = 0u;
                E.k[0] = 0u; E.k[1] = 0u; E.k[2] = 0u;
                E.w_settle = 0u; E.w_over = 0u; E.w_err = 0u;
                hc_dbw_calibration_begin(now_ms);
                E.res = ETB_RES_RUN; E.why = 0u; E.ready = 0u;
                E.t0 = now_ms; E.step = now_ms; phase(ETB_CAL_SWEEP, now_ms);
            } else if (dbw_running) {
                E.res = ETB_RES_FAIL;
                E.why = ETB_WHY_RUNNING;
            } else {
                E.sweep.inhibit = 0u;
                start((unsigned char)(q == 2u), now_ms);
            }
        }
    }
    if (E.ph == ETB_CAL_IDLE) {
        /* A characterization exit remains motor OFF until ECU reinit or
           another explicitly requested commissioning procedure. */
        if (E.sweep.inhibit || TGT_ETB_DIAGNOSTIC_BENCH) return 1u;
        return 0u;
    }
    if (E.ph == ETB_CAL_SWEEP || E.ph == ETB_CAL_SLAM || E.ph == ETB_CAL_FRICTION) {
        unsigned char why = sweep_guard(rpm, armed);
        if (!why && (unsigned int)(now_ms - E.t0) > 60000u) why = ETB_WHY_TIMEOUT;
        if (why) {
            if (why == ETB_WHY_TRACKS || why == ETB_WHY_STALE
                || why == ETB_WHY_ALIGN || why == ETB_WHY_RAIL
                || why == ETB_WHY_ADC || why == ETB_WHY_NOSAMPLE) E.detail |= SWEEP_TPS;
            finish(ETB_RES_FAIL, why); return 1u;
        }
        if ((unsigned int)(now_ms - E.step) >= ETB_STEP_MS) {
            E.step = now_ms;
            if (E.ph == ETB_CAL_FRICTION) fric_tick(now_ms);
            else sweep_tick(now_ms);
        }
        /* An open-loop break-away ramp owns the bridge; otherwise the
           closed loop runs on the scripted target. */
        if (E.ph == ETB_CAL_FRICTION) return B.fsub;
        return (unsigned char)((E.ph == ETB_CAL_SWEEP || E.ph == ETB_CAL_SLAM) && E.ready ? 0u : 1u);
    }
    if (E.ph == ETB_CAL_VERIFY) {
        /* the closed loop owns the bridge; this module owns the target */
        if ((unsigned int)(now_ms - E.step) >= ETB_STEP_MS) {
            E.step = now_ms;
            verify_step(now_ms, rpm, armed);
        }
        /* Retain bridge ownership throughout the motor-OFF release. Even a
           valid pedal with normal DBW enabled cannot restart it here. */
        return (unsigned char)(E.ph == ETB_CAL_VERIFY && E.ready ? 0u : 1u);
    }
    if ((unsigned int)(now_ms - E.step) >= ETB_STEP_MS) {
        E.step = now_ms;
        step(now_ms, rpm, armed);
    }
    return 1u;
}

unsigned int far hc_etbcal_status(void)
{
    return (unsigned int)((unsigned int)(E.res & 0x0Fu)
                          | ((unsigned int)(E.ph & 0x0Fu) << 4)
                          | ((unsigned int)E.why << 8));
}

unsigned char far hc_etbcal_take(unsigned int *r)
{
    unsigned char i;

    if (!E.newcal) {
        return 0u;
    }
    for (i = 0u; i < 5u; i++) {
        r[i] = E.out[i];
    }
    E.newcal = 0u;
    return 1u;
}

unsigned char far hc_etbcal_tune_take(unsigned int *k)
{
    if (!E.newtune) {
        return 0u;
    }
    k[0] = E.k[0]; k[1] = E.k[1]; k[2] = E.k[2];
    E.newtune = 0u;
    return 1u;
}

unsigned int far hc_etbcal_value(unsigned char i)
{
    if(i==34u) return B.state;
    if(i>=35u && i<43u) return B.proposed[i-35u];
    if(i>=43u && i<51u) return hc_cal_u16(CAL_DBW_BIAS_VAL+2u*(i-43u));
    if(i>=51u && i<59u) return B.axis[i-51u];
    if(i==59u) return B.samples;
    if(i==60u) return B.integral_before;
    if(i==61u) return B.integral_after;
    if(i==62u) return B.changed;
    if(i==63u) return B.valid_min;
    if(i==64u) return B.valid_max;
    if(i==65u) return B.excluded;
    if(i==66u) return B.excluded_reason;
    if(i==67u) return B.qualified_samples;
    /* What the BRIDGE is switching at, read back from the HAL rather than
       from the page, so this says the frequency was applied and not merely
       requested. */
    if(i==68u) return hc_hal_dbw_pwm_applied_hz();
    /* The friction band per measurement position: midpoint (+1000, the bias
       curve's own encoding), width and the worst trial-to-trial spread. */
    if(i>=69u && i<75u) return (unsigned int)(B.mid[i-69u]+1000);
    if(i>=75u && i<81u) return (unsigned int)B.width[i-75u];
    if(i>=81u && i<87u) return B.spread[i-81u];
    if(i>=87u && i<95u) return B.pax[i-87u];          /* proposed axis */
    if (i == ETBV_SWEEP_DUTY) return (unsigned int)(D.out_t < 0 ? -(int)D.duty : (int)D.duty);
    if (i == ETBV_SWEEP_FLAGS) return E.proc == ETB_PROC_SWEEP ? E.detail : 0u;
    if (i == ETBV_SWEEP_RMS) return E.proc == ETB_PROC_SWEEP ? sweep_rms(&E.sweep) : 0u;
    if (i == ETBV_SWEEP_SAT) return E.proc == ETB_PROC_SWEEP && E.sweep.samples ? (unsigned int)((unsigned long)E.sweep.saturated * 1000u / E.sweep.samples) : 0u;
    if (E.proc == ETB_PROC_SWEEP) {
        /* One compact read can graph the complete controller at bench speed. */
        if (i == ETBV_REST1) return D.tgt;
        if (i == ETBV_A1) return D.act;
        if (i == ETBV_B1) return (unsigned int)(D.out_t < 0 ? -(int)D.duty : (int)D.duty);
        if (i == ETBV_A2) return (unsigned int)D.p_t;
        if (i == ETBV_B2) return (unsigned int)(int)D.integ;
        if (i == ETBV_REST2) return (unsigned int)D.d_t;
        if (i == ETBV_DRIVE) return (unsigned int)D.ff_t;
        if (i == ETBV_PHASE_MS) return E.sweep.segment + 1u;
        if (i == ETBV_DETAIL) return D.requested;
        if (i == ETBV_V_STEP) return E.sweep.segment + 1u;
        if (i == ETBV_AMP) return E.sum_a;
        if (i == ETBV_TU) return E.sum_t;
        if (i == ETBV_AMP_LIVE) return E.a_live == 65535u ? 0u : E.a_live;
        if (i == ETBV_TU_LIVE) return E.tu_live;
        if (i == ETBV_CYCLES) return E.sweep.pairmax;
    }
    switch (i) {
    case ETBV_REST1:    return E.rest1;
    case ETBV_A1:       return E.e1[0];
    case ETBV_B1:       return E.e1[1];
    case ETBV_A2:       return E.e2[0];
    case ETBV_B2:       return E.e2[1];
    case ETBV_REST2:    return E.rest2;
    case ETBV_AMP:      return E.a_x10;
    case ETBV_TU:       return E.tu_ms;
    case ETBV_DETAIL:   return E.detail;
    case ETBV_CYCLES:   return E.cycles;
    case ETBV_KP:       return E.k[0];
    case ETBV_KI:       return E.k[1];
    case ETBV_KD:       return E.k[2];
    case ETBV_AMP_LIVE: return E.a_live;
    case ETBV_TU_LIVE:  return E.tu_live;
    case ETBV_DRIVE:
        return (unsigned int)((E.on ? 0x8000u : 0u) | (E.dir ? 0x4000u : 0u)
                              | (E.duty & 0x03FFu));
    case ETBV_V_SETTLE: return E.w_settle;
    case ETBV_V_OVER:   return E.w_over;
    case ETBV_V_ERR:    return E.w_err;
    case ETBV_V_STEP:   return (unsigned int)((E.vstep & 0x7Fu)
                                              | ((E.vstep & 0x80u) ? 0x0100u : 0u));
    case ETBV_PHASE_MS:
        return (E.ph == ETB_CAL_IDLE) ? 0u : (unsigned int)(E.step - E.tph);
    case ETBV_HOLD1:    return E.h1;
    case ETBV_PUSH1:    return E.p1;
    case ETBV_LIMIT:    return E.lim;
    case ETBV_MOVED:    return (unsigned int)E.moved;
    case ETBV_HOLD_MS:  return E.hold_ms;
    case ETBV_DISP:     return E.disp;
    case ETBV_IPV:      return E.ipv;
    case ETBV_RAW1:     return E.raw1;
    case ETBV_RAW2:     return E.raw2;
    default:            return 0u;
    }
}

/* Main-loop command consumer, never from a serial yield or control ISR.
 * The transaction rolls back all proposed bytes on validation refusal. */
void far hc_etbcal_bias_service(unsigned int now)
{
    unsigned char j;
    unsigned int f;
    if(!B.pending || B.busy) return;
    B.pending=0u;
    if(E.ph!=ETB_CAL_IDLE || E.res!=ETB_RES_CHARACTERIZED || B.state!=BIAS_READY) return;
    if(B.revision!=hc_cfg_desired_rev) {B.state=BIAS_CHANGED;return;}
    if(trg_rpm || trg_state!=TRG_NO_SIGNAL || hc_dbw_bridge_on()
        || !hc_hal_ain_ok(HC_AIN_TPS1) || !hc_hal_ain_ok(HC_AIN_TPS2)
        || hc_etbcal_rail_faults(1u) || hc_etbcal_tps_pair_fault()
        || hc_dbw_faults() || (eng_sensor_err & (ENG_ERR_TPS1|ENG_ERR_TPS2|ENG_ERR_TPS_DIFF))) {
        B.state=BIAS_FAULT;return;
    }
    f=hc_nvm_state();
    if(f==HCNV_ST_PENDING || f==HCNV_ST_ARMED || f==HCNV_ST_COMMITTING || f==HCNV_ST_STAGING) return;
    B.busy=1u;
    hc_cfg_mgr_txn_begin();
    for(j=0u;j<8u;j++) {
        hc_cfg_mgr_txn_put_u8(CAL_DBW_BIAS_AX+2u*j,(unsigned char)(B.pax[j]>>8));
        hc_cfg_mgr_txn_put_u8(CAL_DBW_BIAS_AX+2u*j+1u,(unsigned char)B.pax[j]);
        hc_cfg_mgr_txn_put_u8(CAL_DBW_BIAS_VAL+2u*j,(unsigned char)(B.proposed[j]>>8));
        hc_cfg_mgr_txn_put_u8(CAL_DBW_BIAS_VAL+2u*j+1u,(unsigned char)B.proposed[j]);
    }
    f=hc_cfg_mgr_txn_commit(0u);
    B.busy=0u;
    if(f) {B.state=BIAS_VALIDATE;return;}
    cfg_writes++; hc_nvm_mark_dirty(); B.state=BIAS_SAVED;
    OCH[774]=(unsigned char)(now>>8); OCH[775]=(unsigned char)now;
    OCH[770]=0u; OCH[771]=1u;
}

/* The normal controller uses this only for candidate verification. Values
   remain private to this procedure until all response tests have passed. */
unsigned int far hc_etbcal_u16(unsigned int field)
{
    if (E.ph == ETB_CAL_VERIFY) {
        if (E.calok) {
            if (field == CAL_TPS1_MIN) return E.out[0];
            if (field == CAL_TPS1_MAX) return E.out[1];
            if (field == CAL_TPS2_MIN) return E.out[2];
            if (field == CAL_TPS2_MAX) return E.out[3];
            if (field == CFG_U_DBW_MOTOR_DIR) return E.out[4];
            if (field == CFG_U_TPS_CORR) return 1u;
        }
        if (field == CAL_DBW_KP) return E.k[0];
        if (field == CAL_DBW_KI) return E.k[1];
        if (field == CAL_DBW_KD) return E.k[2];
    }
    if (field == CFG_U_DBW_MOTOR_DIR || field == CFG_U_TPS_CORR)
        return hc_cal_u8(field);
    return hc_cal_u16(field);
}

/* The bias and P/D terms move the plate; integral corrects holding error.
   During a large moving error, preserve its existing holding charge instead
   of accumulating a delayed command that survives the target crossing.
   A stationary error may integrate after 40 ms, so friction or a small
   candidate gain cannot strand the plate outside the integration band.
   Use acquisition time; cached pairs do not count as stationary samples. */
static void integral_qualify(unsigned int sample_ms, unsigned char entry)
{
    unsigned int dt, movement;
    if (entry) {
        D.integral_target = D.tgt;
        D.integral_quiet_ms = 40u;
    }
    if (udiff(D.tgt, D.integral_target) > 50u)
        D.integral_quiet_ms = 0u;
    D.integral_target = D.tgt;
    dt = (unsigned int)(sample_ms - D.prev_sample_ms);
    if (!entry && dt && dt <= 100u) {
        movement = udiff(D.act, (unsigned int)D.prev_act);
        if (movement > dt) D.integral_quiet_ms = 0u;
        else if (D.integral_quiet_ms < 40u) {
            D.integral_quiet_ms += dt;
            if (D.integral_quiet_ms > 40u) D.integral_quiet_ms = 40u;
        }
    }
    D.integral_allowed = (unsigned char)((D.err <= 50 && D.err >= -50)
                           || D.integral_quiet_ms >= 40u);
}

/* COULOMB FRICTION COMPENSATION, dbwFrictionX10: +-c in the direction of
   the error, linear inside +-FCOMP_ZONE so a held plate is not dithered, 0
   inside the deadband (err is post-deadband). Normal closed loop and the
   commissioning verify only; break-away ramps and the relay autotune drive
   their own command. Bench A/B: zone 15/30/50
   gave the same autotune pass rate; 15 is the one the A/B validated. */
#define FCOMP_ZONE 15
int far hc_etbcal_friction(int err)
{
    int c = (int)hc_cal_u16(CFG_U_DBW_FRICTION_X10);
    if (c > 300) c = 300;               /* hc_validate refuses more anyway */
    if (err >= FCOMP_ZONE) return c;
    if (err <= -FCOMP_ZONE) return -c;
    return err * c / FCOMP_ZONE;        /* |err| < 15, c <= 300: int */
}

int far hc_etbcal_derivative(unsigned int sample_ms, unsigned char entry,
                             unsigned int gain)
{
    unsigned int dt, divisor, mag, v;
    int delta;
    unsigned long num;
    integral_qualify(sample_ms, entry);
    if (entry) {
        D.prev_act = (int)D.act;
        D.prev_sample_ms = sample_ms;
        return 0;
    }
    dt = (unsigned int)(sample_ms - D.prev_sample_ms);
    if (dt == 0u) return D.d_t;
    /* KD page units encode the nominal 5 ms raster. Differentiate once per
       new coherent pair over its ACTUAL acquisition interval, then retain
       that velocity estimate between acquisitions. */
    delta = D.prev_act - (int)D.act;
    D.prev_act = (int)D.act;
    D.prev_sample_ms = sample_ms;
    if (dt > 100u) return 0;      /* cannot bridge the source freshness bound */
    mag = (unsigned int)(delta < 0 ? -delta : delta);
    num = (unsigned long)mag * (unsigned long)gain;
    divisor = dt * 200u;         /* gain*5/(dt*1000), denominator <=20000 */
    /* Native 16x16 MULU / 32:16 DIVLU. Far code must not call the SMALL
       runtime library with its incompatible near-return convention. Clamp
       before DIVLU, whose 16-bit quotient must not overflow. */
    v = num > (unsigned long)32000u * divisor ? 32000u
                                              : (unsigned int)(num / divisor);
    return delta < 0 ? -(int)v : (int)v;
}

/* Cold page qualification shared by normal DBW and candidate verification. */
static unsigned char span_bad(unsigned int a, unsigned int b)
{
    unsigned int d = (a > b) ? (unsigned int)(a - b) : (unsigned int)(b - a);
    return (unsigned char)(a < 10u || a > 1013u || b < 10u || b > 1013u
                           || d < 32u);
}

unsigned int far hc_etbcal_config_faults(unsigned char override)
{
    unsigned int lo, hi;

    /* direction is allowed, a missing span is not - hc_dbw_normalise(). */
    if ((!override
         && (span_bad(hc_cal_u16(CAL_PEDAL1_MIN), hc_cal_u16(CAL_PEDAL1_MAX))
             || span_bad(hc_cal_u16(CAL_PEDAL2_MIN), hc_cal_u16(CAL_PEDAL2_MAX))))
        || span_bad(hc_etbcal_u16(CAL_TPS1_MIN), hc_etbcal_u16(CAL_TPS1_MAX))
        || span_bad(hc_etbcal_u16(CAL_TPS2_MIN), hc_etbcal_u16(CAL_TPS2_MAX))) {
        return DBW_F_CFG;
    }
    if (hc_etbcal_u16(CFG_U_TPS_CORR) > HC_TRACK_SCALED
        || (!override && hc_cal_u8(CFG_U_APP_CORR) > HC_TRACK_SCALED))
        return DBW_F_CFG;
    lo = hc_cal_u16(CAL_DBW_MIN_X10);
    hi = hc_cal_u16(CAL_DBW_MAX_X10);
    if (hi <= lo || hi > (unsigned int)1000u) {
        return DBW_F_CFG;
    }
    if (hc_cal_u16(CFG_U_DBW_MAX_DUTY_X10) == 0u
        || hc_cal_u16(CFG_U_DBW_MAX_DUTY_X10) > (unsigned int)1000u) {
        return DBW_F_CFG;
    }
    return 0u;
}


unsigned int far hc_etbcal_rail_faults(unsigned char override)
{
    unsigned int f = 0u, v;
    v = hc_hal_ain(HC_AIN_TPS1);
    if (v < 10u || v > 1013u) f |= DBW_F_TPS_RANGE;
    v = hc_hal_ain(HC_AIN_TPS2);
    if (v < 10u || v > 1013u) f |= DBW_F_TPS_RANGE;
    if (!override) {
        v = hc_hal_ain(HC_AIN_APP1);
        if (v < 10u || v > 1013u) f |= DBW_F_APP_RANGE;
        v = hc_hal_ain(HC_AIN_APP2);
        if (v < 10u || v > 1013u) f |= DBW_F_APP_RANGE;
    }
    return f;
}

unsigned char far hc_etbcal_pair_bad(unsigned int a, unsigned int b,
                              unsigned char corr, unsigned int tol_x10)
{
    int d;

    if (corr == HC_TRACK_OPPOSITE) {
        d = (int)a + (int)b - (int)1000;
    } else {
        d = (int)a - (int)b;
    }
    if (d < 0) {
        d = -d;
    }
    return (unsigned char)(d > (int)tol_x10);
}


/* Cold controller telemetry keeps the C167 near segment bounded. */
unsigned int far hc_etbcal_control_term(unsigned char i)
{
    switch (i) {
    case DBW_T_CONTROL_MS: return D.step_mark;
    case DBW_T_P:       return (unsigned int)D.p_t;
    case DBW_T_D:       return (unsigned int)D.d_t;
    case DBW_T_FF:      return (unsigned int)D.ff_t;
    case DBW_T_OUT:     return (unsigned int)D.out_t;
    case DBW_T_VFAC:    return D.vfac;
    case DBW_T_PEND:    return D.pend;
    case DBW_T_PEND_MS: return D.pend ? (unsigned int)(D.step_mark - D.pend_since) : 0u;
    case DBW_T_OVR:     return D.ovr;
    case DBW_T_CLEARS:  return D.clears;
    default:            return 0u;
    }
}
/* TunerStudio's engine-side TPS disagreement flag must use the same time
   basis as the motor safety check, rather than independently filtered,
   asynchronous latest readings. Engine control position filters stay intact. */
unsigned char far hc_etbcal_tps_pair_fault(void)
{
    unsigned int r1, r2, ms, p1, p2;
    unsigned char ok1, ok2;
    if (!hc_fresh_tps_pair(&r1, &r2, &ms)) return 0u;
    p1 = hc_dbw_normalise(r1, hc_cal_u16(CAL_TPS1_MIN),
                            hc_cal_u16(CAL_TPS1_MAX), &ok1);
    p2 = hc_dbw_normalise(r2, hc_cal_u16(CAL_TPS2_MIN),
                            hc_cal_u16(CAL_TPS2_MAX), &ok2);
    if (!ok1 || !ok2) return 0u; /* rail/range has separate indicators */
    return hc_etbcal_pair_bad(p1, p2, hc_cal_u8(CFG_U_TPS_CORR),
                              hc_cal_u16(CFG_U_TPS_TOL_X10));
}
