/*
 * hcidle.c - idle speed control core. Read hcidle.h first; the proof is
 * tests/host/test_hcidle.c (tools/test_hcidle_host.py, which also compiles
 * this file with Keil and fails on any ?C_ helper call).
 *
 * Arithmetic as in hcldr.c: int x int -> long (inline MUL), and
 * (int)(long / 100) only with the quotient bounded to +-1000 first (inline
 * DIVL).
 */
#include "hcidle.h"

static const int thousand = 1000;

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

/* the I term is kept x1000 (2026-10-15): x100 made Ki 1, the smallest gain,
   integrate 5 % throttle per second per 100 rpm - faster than the intake
   lets any idle loop be stable, so no page value could tune it */
static int div1000_sat(long v)
{
    if (v >= 1000000L) return 1000;
    if (v <= -1000000L) return -1000;
    return (int)(v / 1000);
}

void HCIDLE_FAR hcidle_reset(hcidle_t *d)
{
    d->integ1000 = 0L;
    d->last_rpm = 0u;
    d->have_last = 0u;
    d->run_ms = 0u;
    d->pos_x10 = 0u;
    d->trim_x10 = 0;
    d->p_x10 = 0;
    d->i_x10 = 0;
    d->state = 0u;
    d->dash_ms = 0xFFFFu;
}

/* the dashpot adder now: full while held, then a linear decay to 0 */
static unsigned int dash_add(const hcidle_t *d, const hcidle_cfg_t *c)
{
    unsigned int a = c->dash_x10 > 200u ? 200u : c->dash_x10;
    unsigned int t;
    if (a == 0u || d->dash_ms == 0xFFFFu) return 0u;
    if (d->dash_ms <= c->dash_hold_ms) return a;
    t = (unsigned int)(d->dash_ms - c->dash_hold_ms);
    if (t >= c->dash_decay_ms) return 0u;
    return (unsigned int)((unsigned long)a * (unsigned int)(c->dash_decay_ms - t)
                          / c->dash_decay_ms);
}

static unsigned int with_dash(hcidle_t *d, unsigned int add)
{
    unsigned int p = d->pos_x10 + add;          /* both <= 1000 */
    d->pos_x10 = p > 1000u ? 1000u : p;
    return d->pos_x10;
}

/* the trim is clamped to the CURRENT authority in every state: a held trim
   must not exceed a range the tuner has since reduced (host fuzz) */
static unsigned int place(hcidle_t *d, const hcidle_in_t *in, int trim, int range,
                          unsigned char st)
{
    long pos;
    if (!(st & HCIDLE_S_CLOSED)) d->have_last = 0u;
    if (trim > range) trim = range;
    if (trim < -range) trim = -range;
    pos = (long)in->base_x10 + trim;
    if (pos < 0L) pos = 0L;
    if (pos > 1000L) pos = 1000L;
    d->trim_x10 = trim;
    d->pos_x10 = (unsigned int)pos;
    d->state = st;
    return d->pos_x10;
}

unsigned int HCIDLE_FAR hcidle_step(hcidle_t *d, const hcidle_cfg_t *c,
                                   const hcidle_in_t *in, unsigned int ms)
{
    int range = i16(c->range_x10 > 1000u ? 1000u : c->range_x10);
    int e, p, i, held;
    long di;
    unsigned char over;

    if (!c->enabled) {
        hcidle_reset(d);
        d->state = HCIDLE_S_OFF;
        return 0u;
    }
    if (in->rpm == 0u) {
        d->dash_ms = 0xFFFFu;
        d->integ1000 = 0L;
        d->run_ms = 0u;
        d->p_x10 = 0;
        d->i_x10 = 0;
        return place(d, in, 0, range, HCIDLE_S_STOPPED);
    }
    if (in->cranking) {
        d->dash_ms = 0xFFFFu;
        d->run_ms = 0u;
        d->p_x10 = 0;
        return place(d, in, d->i_x10, range, HCIDLE_S_CRANK);
    }
    if (d->run_ms < c->start_ms) {
        d->run_ms = (d->run_ms > 65535u - ms) ? 65535u : (unsigned int)(d->run_ms + ms);
        d->p_x10 = 0;
        return place(d, in, d->i_x10, range, HCIDLE_S_CRANK);
    }
    if (in->pedal_x10 > c->pedal_x10) {
        d->p_x10 = 0;
        d->dash_ms = 0u;                         /* the dashpot is armed */
        (void)place(d, in, d->i_x10, range, HCIDLE_S_PEDAL);
        return with_dash(d, dash_add(d, c));
    }
    /* NO ADDED AIR ABOVE THE BAND (2026-10-15, car; rusEFI getClosedLoop:
       "a positive correction could inhibit a return to idle"): pedal
       released and the engine above target + band, a POSITIVE trim is not
       applied - it is kept (the learned air, for the return) but it does not
       open the throttle. A held +100 % trim, wound up while a cold engine
       stumbled, kept the throttle open to the rev limiter with the pedal
       released. A negative trim is still applied (less air helps the
       return). */
    over = (unsigned char)((unsigned long)in->rpm
                           >= (unsigned long)in->target_rpm + c->band_rpm);
    held = (over && d->i_x10 > 0) ? 0 : d->i_x10;
    if (d->dash_ms != 0xFFFFu)
        d->dash_ms = (d->dash_ms >= 0xFFFEu - ms) ? 0xFFFEu
                   : (unsigned int)(d->dash_ms + ms);
    {
        unsigned int add = dash_add(d, c);
        if (add != 0u) {
            d->p_x10 = 0;
            (void)place(d, in, held, range, HCIDLE_S_DASH);
            return with_dash(d, add);
        }
    }
    if (over) {
        d->p_x10 = 0;
        return place(d, in, held, range, HCIDLE_S_COAST);
    }

    /* closed loop: error in rpm, clamped so the products stay in range */
    {
        long ev = (long)in->target_rpm - (long)in->rpm;
        e = (int)(ev > 5000L ? 5000L : (ev < -5000L ? -5000L : ev));
    }
    p = div100_sat((long)i16(c->kp) * e);
    di = (long)i16(c->ki) * e;
    /* I does not integrate while the error is already shrinking by itself
       (a coast-down settling, a dip recovering): that is a transient, not
       the steady-state error I exists for. Entering closed loop from a
       coast-down at target + band, integrating it dipped the engine 150 rpm
       under target (host test). Bosch forbids negative integration after
       start (TVLISTU) for the same reason. */
    if (d->have_last && ((e < 0 && in->rpm < d->last_rpm)
                         || (e > 0 && in->rpm > d->last_rpm)))
        di = 0L;
    d->last_rpm = in->rpm;
    d->have_last = 1u;
    /* the I part alone never exceeds the authority (anti-windup) */
    d->integ1000 += di;
    {
        long lim = (long)range * thousand;          /* int x int: inline MUL */
        if (d->integ1000 > lim) d->integ1000 = lim;
        if (d->integ1000 < -lim) d->integ1000 = -lim;
    }
    i = div1000_sat(d->integ1000);
    d->p_x10 = p;
    d->i_x10 = i;
    {
        int t = p + i;                              /* |p|,|i| <= 1000 */
        unsigned char st = HCIDLE_S_CLOSED;
        if (t >= range) { t = range; st |= HCIDLE_S_LIMIT; }
        if (t <= -range) { t = -range; st |= HCIDLE_S_LIMIT; }
        return place(d, in, t, range, st);
    }
}

/* ---------------------------------------------------------------------- */
/* idle ignition timing (hcidle.h). Magnitudes in unsigned 32/16 arithmetic:
   |e| <= 1000 rpm, kp <= 500 -> |e| * kp / 100 <= 5000; the soft entry
   scales by closed_ms / soft_ms < 1. No ?C_ helper (the host test's Keil
   check). */
int HCIDLE_FAR hcidle_timing_step(hcidle_timing_t HCIDLE_TMEM *t,
                                  const hcidle_tcfg_t *c, unsigned char closed,
                                  unsigned int rpm, unsigned int target_rpm,
                                  unsigned int ms)
{
    unsigned int e, kp, mag;
    unsigned char below;
    int out;

    if (!c->enabled || !closed) {
        t->closed_ms = 0u;
        t->out_x10 = 0;
        return 0;
    }
    t->closed_ms = (t->closed_ms > 65535u - ms) ? 65535u
                 : (unsigned int)(t->closed_ms + ms);
    below = (unsigned char)(rpm < target_rpm);
    e = below ? (unsigned int)(target_rpm - rpm) : (unsigned int)(rpm - target_rpm);
    if (e > 1000u) e = 1000u;
    kp = c->kp_x10 > 500u ? 500u : c->kp_x10;
    mag = (unsigned int)((unsigned long)e * kp / 100u);
    if (c->soft_ms != 0u && t->closed_ms < c->soft_ms)
        mag = (unsigned int)((unsigned long)mag * t->closed_ms / c->soft_ms);
    out = below ? (int)mag : -(int)mag;         /* below target: advance */
    if (out > c->max_x10) out = c->max_x10 > 0 ? c->max_x10 : 0;
    if (out < c->min_x10) out = c->min_x10 < 0 ? c->min_x10 : 0;
    t->out_x10 = out;
    return out;
}
