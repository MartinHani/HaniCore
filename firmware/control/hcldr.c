/*
 * hcldr.c - boost control decision core. Read hcldr.h first; the proof is
 * tests/host/test_hcldr.c (tools/test_hcldr_host.py).
 *
 * Arithmetic (this module is far code, and Keil's long helpers are not):
 * every product is int x int -> long, which Keil emits as one inline MUL;
 * every division is (int)(long / 100) with the quotient bounded to +-1000
 * BEFORE dividing, which Keil emits as one inline DIVL. A mixed
 * unsigned/long product or a long/long division calls ?C_LMUL/?C_SLDIV -
 * tools/test_hcldr_host.py compiles this file with Keil and fails on any
 * CALLS to a ?C_ helper.
 */
#include "hcldr.h"

static void pid_reset(hcldr_t *b)
{
    b->integ100 = 0L;
    b->have_last = 0u;
    b->p_x10 = 0;
    b->i_x10 = 0;
    b->d_x10 = 0;
}

void HCLDR_FAR hcldr_reset(hcldr_t *b)
{
    pid_reset(b);
    b->last_map = 0u;
    b->cut = 0u;
    b->state = 0u;
    b->duty_x10 = 0u;
    b->cuts = 0u;
}

static int i16(unsigned int v)
{
    return v > 32767u ? 32767 : (int)v;
}

/* (int)(v / 100), saturated to +-1000 before the division so the quotient
   always fits the DIVL */
static int div100_sat(long v)
{
    if (v >= 100000L) return 1000;
    if (v <= -100000L) return -1000;
    return (int)(v / 100);
}

static unsigned int out(hcldr_t *b, unsigned int duty, unsigned char st)
{
    if (duty > HCLDR_DUTY_MAX) duty = HCLDR_DUTY_MAX;
    if ((st & (HCLDR_S_OPEN | HCLDR_S_CLOSED)) && (duty == 0u || duty == HCLDR_DUTY_MAX))
        st |= HCLDR_S_SAT;
    b->state = st;
    b->duty_x10 = duty;
    return duty;
}

unsigned int HCLDR_FAR hcldr_step(hcldr_t *b, const hcldr_cfg_t *c, const hcldr_in_t *in)
{
    unsigned int lim, hy, open;
    int e, p, d;
    long u, di;

    /* ---- overboost FIRST, whatever else is configured ----------------- */
    lim = c->cut_x10 ? c->cut_x10 : HCLDR_CUT_DEFAULT_X10;
    hy = c->hyst_x10 ? c->hyst_x10 : HCLDR_HYST_DEFAULT_X10;
    if (hy >= lim) hy = (unsigned int)(lim - 1u);
    if (!in->map_ok) {
        b->cut = 0u;                     /* it cannot be judged: no fuel cut */
        pid_reset(b);
        return out(b, 0u, HCLDR_S_SENSOR);
    }
    if (in->map_x10 >= lim) {
        if (!b->cut) b->cuts++;
        b->cut = 1u;
    } else if (b->cut && in->map_x10 < (unsigned int)(lim - hy)) {
        b->cut = 0u;
    }
    if (b->cut) {
        pid_reset(b);
        return out(b, 0u, HCLDR_S_CUT);
    }

    if (!in->enabled || in->keyoff) {
        pid_reset(b);
        return out(b, 0u, HCLDR_S_OFF);
    }
    if (in->rpm < c->min_rpm || in->tps_x10 < c->min_tps_x10) {
        pid_reset(b);
        return out(b, 0u, HCLDR_S_BELOW);
    }
    open = in->open_x10 > HCLDR_DUTY_MAX ? HCLDR_DUTY_MAX : in->open_x10;
    if (!c->closed || in->map_x10 < c->cl_min_map_x10) {
        pid_reset(b);
        return out(b, open, HCLDR_S_OPEN);
    }

    /* ---- closed loop ---------------------------------------------------- */
    {
        long ev = (long)in->target_x10 - (long)in->map_x10;   /* |ev| < 65536 */
        e = (int)(ev > 30000L ? 30000L : (ev < -30000L ? -30000L : ev));
    }
    p = div100_sat((long)i16(c->kp) * e);            /* MUL, then DIVL */
    d = 0;
    if (b->have_last) {
        long dm = (long)in->map_x10 - (long)b->last_map;
        int dmi = (int)(dm > 30000L ? 30000L : (dm < -30000L ? -30000L : dm));
        d = -div100_sat((long)i16(c->kd) * dmi);
    }
    b->last_map = in->map_x10;
    b->have_last = 1u;

    /* conditional integration: the step is taken only if it does not push
       an already saturated output further into saturation */
    di = (long)i16(c->ki) * e;                       /* x100 */
    /* far BELOW target (spooling): no integration - P and the open loop
       carry it. ABOVE target it always integrates: pulling boost down is
       the safe direction, and a two-sided band left P alone parking the
       engine 23 kPa over target (host test, saturation_low) */
    if (c->i_band_x10 && e > i16(c->i_band_x10))
        di = 0L;
    u = (long)open + p + d + div100_sat(b->integ100);
    if (!((u >= (long)HCLDR_DUTY_MAX && di > 0L) || (u <= 0L && di < 0L))) {
        b->integ100 += di;
        if (b->integ100 > 100000L) b->integ100 = 100000L;
        if (b->integ100 < -100000L) b->integ100 = -100000L;
    }
    b->p_x10 = p;
    b->d_x10 = d;
    b->i_x10 = div100_sat(b->integ100);
    u = (long)open + p + d + b->i_x10;
    if (u < 0L) u = 0L;
    return out(b, (unsigned int)(u > (long)HCLDR_DUTY_MAX ? (long)HCLDR_DUTY_MAX : u),
               HCLDR_S_CLOSED);
}
