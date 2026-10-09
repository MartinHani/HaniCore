/*
 * hctrans.c - transient fuel core. Read hctrans.h first.
 *
 * Far on ME7.1.1: every division is DIV32U (Keil's inline 32/16 _div32u_,
 * a quotient that fits 16 bits by construction), every product a 16x16 into
 * a long - no ?C_ runtime helper.
 */
#include "hctrans.h"

/* A 32/16 unsigned division whose quotient fits 16 bits (every caller
   bounds it). Keil C166 emits the inline DIVLU for this shape; the host test's
   Keil check fails on any ?C_ helper call, so a compiler that does not is
   caught. */
#define DIV32U(n, d)  ((unsigned int)((unsigned long)(n) / (unsigned int)(d)))

void HCTRANS_FAR hctrans_reset(hctrans_t HCTRANS_MEM *s)
{
    s->film = 0u;
    s->acc_ms = 0u;
    s->as_ms = 0u;
    s->was_crank = 1u;
    s->pad = 0u;
    s->base = 0u;
    s->want = 0u;
    s->out = 0u;
    s->corr = 0;
    s->alpha = 0u;
    s->as_pm = 0u;
}

unsigned char HCTRANS_FAR hctrans_lerp8(unsigned int x0, unsigned int x1,
                                        unsigned char v0, unsigned char v1,
                                        unsigned int x)
{
    unsigned int span, d;

    if (x1 <= x0 || x <= x0) {
        return v0;
    }
    if (x >= x1) {
        return v1;
    }
    span = (unsigned int)(x1 - x0);
    d = (unsigned int)(x - x0);
    if (v1 >= v0) {
        return (unsigned char)(v0 + (unsigned char)DIV32U(
            (unsigned long)(unsigned int)(v1 - v0) * d, span));
    }
    return (unsigned char)(v0 - (unsigned char)DIV32U(
        (unsigned long)(unsigned int)(v0 - v1) * d, span));
}

/* The evaporating fraction per cycle, per mille: Tc / (tau + Tc). */
static unsigned int alpha_pm(unsigned int tc_ms, unsigned int tau_ms)
{
    unsigned long sum = (unsigned long)tc_ms + (unsigned long)tau_ms;

    if (sum == 0uL) {
        return 1000u;
    }
    while (sum > 65535uL) {               /* keep the divisor 16-bit */
        sum >>= 1;
        tc_ms >>= 1;
    }
    return DIV32U((unsigned long)tc_ms * 1000u, (unsigned int)sum);
}

/* One engine cycle of the film: F <- F + X*I - alpha*F. */
static void film_cycle(hctrans_t HCTRANS_MEM *s, unsigned int x_pm,
                       unsigned int inj)
{
    unsigned int dep = DIV32U((unsigned long)x_pm * inj, 1000u);
    unsigned int ev = DIV32U((unsigned long)s->alpha * s->film, 1000u);
    unsigned long f = (unsigned long)s->film + dep;

    f = (f > ev) ? (f - ev) : 0uL;
    s->film = (unsigned int)((f > HCTRANS_FILM_MAX) ? HCTRANS_FILM_MAX : f);
}

unsigned int HCTRANS_FAR hctrans_step(hctrans_t HCTRANS_MEM *s,
                                      const hctrans_in_t *in)
{
    unsigned int x = in->x_pm;
    unsigned int base = in->base_us;
    unsigned int want, out, tc;
    unsigned char k;

    if (x > HCTRANS_X_MAX) {
        x = HCTRANS_X_MAX;
    }
    if (base > HCTRANS_OUT_MAX) {
        base = HCTRANS_OUT_MAX;
    }
    s->base = base;

    /* ---- engine stopped: nothing injected, the film dries in time ---- */
    if (in->rpm < 50u) {
        unsigned int a = alpha_pm(in->dt_ms, in->tau_ms);
        s->film = (unsigned int)(s->film
                  - DIV32U((unsigned long)a * s->film, 1000u));
        s->acc_ms = 0u;
        s->was_crank = 1u;
        s->as_ms = 0u;
        s->want = base;
        s->out = in->cut ? 0u : base;
        s->corr = 0;
        s->as_pm = 0u;
        return s->out;
    }

    tc = (unsigned int)(2u * (60000u / in->rpm));   /* one cycle, ms */
    if (tc == 0u) {
        tc = 1u;
    }
    s->alpha = alpha_pm(tc, in->tau_ms);

    /* ---- after-start ---------------------------------------------- */
    if (in->cranking) {
        s->was_crank = 1u;
        s->as_ms = 0u;
        s->as_pm = 0u;
    } else {
        if (s->was_crank) {
            s->was_crank = 0u;
            s->as_ms = 0u;
        }
        if (s->as_ms < in->as_decay_ms) {
            s->as_pm = DIV32U((unsigned long)in->as_pm
                              * (unsigned int)(in->as_decay_ms - s->as_ms),
                              in->as_decay_ms);
            {
                unsigned int n = (unsigned int)(s->as_ms + in->dt_ms);
                s->as_ms = (n < s->as_ms) ? 0xFFFFu : n;
            }
        } else {
            s->as_pm = 0u;
        }
    }
    {
        /* as_pm reaches 2550; base x as_pm / 1000 would leave the
           16-bit quotient DIV32U needs (DIVLU overflow) for a pulse past
           25.7 ms - whole per-mille thousands multiply, the rest divides */
        unsigned int k = (unsigned int)(s->as_pm / 1000u);
        unsigned int fr = (unsigned int)(s->as_pm - k * 1000u);
        unsigned long w = (unsigned long)base * (unsigned int)(1u + k)
                        + DIV32U((unsigned long)base * fr, 1000u);
        want = (unsigned int)((w > HCTRANS_OUT_MAX) ? HCTRANS_OUT_MAX : w);
    }
    s->want = want;

    /* ---- the injector's share: I = (M - alpha F) / (1 - X) ---------- */
    if (in->cut) {
        out = 0u;
    } else if (in->cranking || x == 0u) {
        out = want;
    } else {
        unsigned long m = (unsigned long)want * 1000u;
        unsigned long af = (unsigned long)s->alpha * s->film;
        unsigned int den = (unsigned int)(1000u - x);
        if (af >= m) {
            out = 0u;
        } else {
            m -= af;
            if (m >= (unsigned long)HCTRANS_OUT_MAX * den) {
                out = HCTRANS_OUT_MAX;
            } else {
                out = DIV32U(m, den);
            }
        }
    }
    s->out = out;
    s->corr = (int)((long)out - (long)want);

    /* ---- the film, once per engine cycle of elapsed time ------------ */
    {
        unsigned int acc = (unsigned int)(s->acc_ms + in->dt_ms);
        if (acc < s->acc_ms) acc = 0xFFFFu;
        for (k = 0u; k < 4u && acc >= tc; k++) {
            film_cycle(s, x, out);
            acc = (unsigned int)(acc - tc);
        }
        s->acc_ms = (k >= 4u) ? 0u : acc;
    }
    return out;
}
