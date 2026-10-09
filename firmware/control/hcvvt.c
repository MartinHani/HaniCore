/*
 * hcvvt.c - VVT core. Read hcvvt.h first; the proof is
 * tests/host/test_hcvvt.c (tools/test_hcvvt_host.py, with the Keil
 * no-helper check). Arithmetic as in hcldr.c.
 */
#include "hcvvt.h"

static int i16(unsigned int v)
{
    return v > 32767u ? 32767 : (int)v;
}

static int div100_sat(long v)
{
    if (v >= 100000L) return 1000;
    if (v <= -100000L) return -1000;
    return (int)(v / 100);
}

static void pid_reset(hcvvt_t HCVVT_MEM *v)
{
    v->integ100 = 0L;
    v->have_last = 0u;
    v->err_x10 = 0;
}

void HCVVT_FAR hcvvt_reset(hcvvt_t HCVVT_MEM *v)
{
    pid_reset(v);
    v->last_pos = 0;
    v->state = 0u;
    v->run_ms = 0u;
    v->duty_x10 = 0u;
}

static unsigned int out(hcvvt_t HCVVT_MEM *v, unsigned int duty,
                        unsigned char st)
{
    if (duty > 1000u) duty = 1000u;
    v->duty_x10 = duty;
    v->state = st;
    return duty;
}

unsigned int HCVVT_FAR hcvvt_step(hcvvt_t HCVVT_MEM *v, const hcvvt_cfg_t *c,
                                  const hcvvt_in_t *in, unsigned int ms)
{
    int e, p, d, lo, hi;
    long u, di;

    if (c->mode == HCVVT_MODE_OFF || c->mode > HCVVT_MODE_CLOSED) {
        hcvvt_reset(v);
        return out(v, 0u, HCVVT_S_OFF);
    }
    if (in->rpm == 0u) v->run_ms = 0u;
    else v->run_ms = (v->run_ms > 65535u - ms) ? 65535u : (unsigned int)(v->run_ms + ms);
    if (in->rpm < c->min_rpm || in->rpm == 0u || in->clt_c < c->min_clt_c
        || v->run_ms < c->delay_ms) {
        pid_reset(v);
        return out(v, 0u, HCVVT_S_WAIT);
    }
    if (c->mode == HCVVT_MODE_SWITCH) {
        pid_reset(v);
        return out(v, in->target_x10 > 0 ? c->duty_on_x10 : 0u, HCVVT_S_SWITCH);
    }
    if (!in->pos_ok) {                              /* rusEFI: unexpected -> 0 */
        pid_reset(v);
        return out(v, 0u, HCVVT_S_NOPOS);
    }

    lo = i16(c->duty_min_x10 > 1000u ? 1000u : c->duty_min_x10);
    hi = i16(c->duty_max_x10 > 1000u ? 1000u : c->duty_max_x10);
    if (hi < lo) hi = lo;
    {
        long ev = (long)in->target_x10 - (long)in->pos_x10;
        if (c->invert) ev = -ev;
        e = (int)(ev > 3600L ? 3600L : (ev < -3600L ? -3600L : ev));
    }
    v->err_x10 = e;
    p = div100_sat((long)i16(c->kp) * e);
    d = 0;
    if (v->have_last) {
        long dm = (long)in->pos_x10 - (long)v->last_pos;
        int dmi;
        if (c->invert) dm = -dm;
        dmi = (int)(dm > 3600L ? 3600L : (dm < -3600L ? -3600L : dm));
        d = -div100_sat((long)i16(c->kd) * dmi);   /* on the measurement */
    }
    v->last_pos = in->pos_x10;
    v->have_last = 1u;

    di = (long)i16(c->ki) * e;
    u = (long)p + d + div100_sat(v->integ100);
    /* conditional integration inside [lo, hi] */
    if (!((u >= (long)hi && di > 0L) || (u <= (long)lo && di < 0L))) {
        long lim = 100000L;                         /* I <= 100 % */
        v->integ100 += di;
        if (v->integ100 > lim) v->integ100 = lim;
        if (v->integ100 < -lim) v->integ100 = -lim;
    }
    u = (long)p + d + div100_sat(v->integ100);
    {
        unsigned char st = HCVVT_S_CLOSED;
        if (u >= (long)hi) { u = hi; st |= HCVVT_S_SAT; }
        if (u <= (long)lo) { u = lo; st |= HCVVT_S_SAT; }
        return out(v, (unsigned int)u, st);
    }
}
