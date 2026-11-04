/*
 * hcvss.c - vehicle speed from an edge input, and gear detection.
 * See hcvss.h. Far-code rules: int x int -> long products and DIV32U with a
 * bounded quotient only (no Keil ?C_ helper), no variable shifts.
 */
#include "hcvss.h"

#ifndef DIV32U
#define DIV32U(n, d)  ((unsigned int)((unsigned long)(n) / (unsigned int)(d)))
#endif

void HCVSS_FAR hcvss_reset(hcvss_state_t *s, unsigned int n_now)
{
    s->n_prev = n_now;
    s->ms_prev = 0u;
    s->raw_x10 = 0u;
    s->f_x10 = 0u;
    s->have = 0u;
    s->gear = 0u;
}

unsigned int HCVSS_FAR hcvss_k(unsigned int ppk)
{
    if (ppk < 550u) {
        return 0u;
    }
    return DIV32U(36000000uL, ppk);
}

/* edges x k / dt, saturated below HCVSS_NONE */
static unsigned int rate(unsigned int edges, unsigned int k, unsigned int dt)
{
    unsigned long p = (unsigned long)edges * k;
    if (dt == 0u) {
        return 65000u;
    }
    if (p >= (unsigned long)dt * 65000u) {
        return 65000u;
    }
    return DIV32U(p, dt);
}

unsigned int HCVSS_FAR hcvss_step(hcvss_state_t *s, unsigned int n,
                                  unsigned int ms_edge, unsigned int now,
                                  unsigned int k, unsigned char filt,
                                  unsigned int tmo_ms)
{
    unsigned int edges = (unsigned int)(n - s->n_prev);
    unsigned int a, d, step;

    if (k == 0u) {
        hcvss_reset(s, n);
        return HCVSS_NONE;
    }
    if (tmo_ms == 0u) {
        tmo_ms = HCVSS_TMO_MS;
    }
    if (filt > 15u) {
        filt = 15u;
    }
    if (!s->have) {
        /* the first edge only starts the window */
        if (edges != 0u) {
            s->n_prev = n;
            s->ms_prev = ms_edge;
            s->have = 1u;
        }
        s->raw_x10 = 0u;
        s->f_x10 = 0u;
        return 0u;
    }
    if (edges != 0u) {
        unsigned int dt = (unsigned int)(ms_edge - s->ms_prev);
        /* a full window, or a short one that no further edge will extend
           (the edges stopped): close it, so the decay and the standing
           timeout below run from the LAST edge */
        if (dt >= HCVSS_WIN_MS
            || (dt != 0u && (unsigned int)(now - ms_edge) >= HCVSS_WIN_MS)) {
            s->raw_x10 = rate(edges, k, dt);
            s->n_prev = n;
            s->ms_prev = ms_edge;
        }
    } else {
        unsigned int since = (unsigned int)(now - s->ms_prev);
        if (since >= tmo_ms) {
            /* standing: the next edge starts a new window */
            s->have = 0u;
            s->raw_x10 = 0u;
            s->f_x10 = 0u;
            return 0u;
        }
        if (since >= HCVSS_WIN_MS) {
            /* no edge yet: the speed is at most one edge in `since` */
            unsigned int cap = rate(1u, k, since);
            if (s->raw_x10 > cap) {
                s->raw_x10 = cap;
            }
        }
    }

    /* first-order filter that reaches its target (a remainder below one
       count still moves one count) */
    a = (unsigned int)(16u - filt);
    if (s->raw_x10 >= s->f_x10) {
        d = (unsigned int)(s->raw_x10 - s->f_x10);
        step = DIV32U((unsigned long)d * a, 16u);
        if (step == 0u && d != 0u) {
            step = 1u;
        }
        s->f_x10 = (unsigned int)(s->f_x10 + step);
    } else {
        d = (unsigned int)(s->f_x10 - s->raw_x10);
        step = DIV32U((unsigned long)d * a, 16u);
        if (step == 0u) {
            step = 1u;
        }
        s->f_x10 = (unsigned int)(s->f_x10 - step);
    }
    return s->f_x10;
}

unsigned int HCVSS_FAR hcvss_v1000(unsigned int vss_x10, unsigned int rpm)
{
    unsigned long p;
    if (vss_x10 == HCVSS_NONE || rpm < 400u) {
        return 0u;
    }
    /* (km/h x10) x 10000 / rpm = km/h per 1000 rpm in 0.01 */
    p = (unsigned long)vss_x10 * 10000u;
    if (p >= (unsigned long)rpm * 65000u) {
        return 65000u;
    }
    return DIV32U(p, rpm);
}

unsigned char HCVSS_FAR hcvss_gear(hcvss_state_t *s, unsigned int vss_x10,
                                   unsigned int rpm, const unsigned int *g,
                                   unsigned char n, unsigned char band_pct,
                                   unsigned int min_x10)
{
    unsigned int v, lo, hi;
    unsigned char i, cur;

    if (min_x10 == 0u) {
        min_x10 = 30u;
    }
    if (band_pct == 0u) {
        band_pct = 10u;
    }
    if (band_pct > 50u) {
        band_pct = 50u;
    }
    if (n == 0u || n > HCVSS_GEARS || vss_x10 == HCVSS_NONE
        || vss_x10 < min_x10 || rpm < 400u) {
        s->gear = 0u;
        return 0u;
    }
    for (i = 0u; i < n; i++) {
        if (g[i] == 0u || (i != 0u && g[i] <= g[i - 1u])) {
            s->gear = 0u;            /* not ascending: detection off */
            return 0u;
        }
    }
    v = hcvss_v1000(vss_x10, rpm);
    /* clutch in / slipping / implausible: below 1st / 1.5, above top x 1.5 */
    if ((unsigned long)v * 3u < (unsigned long)g[0] * 2u
        || (unsigned long)v * 2u > (unsigned long)g[n - 1u] * 3u) {
        s->gear = 0u;
        return 0u;
    }
    cur = s->gear;
    if (cur >= 1u && cur <= n) {
        unsigned long v100 = (unsigned long)v * 100u;
        lo = (unsigned int)(100u - band_pct);
        hi = (unsigned int)(100u + band_pct);
        if (v100 >= (unsigned long)g[cur - 1u] * lo
            && v100 <= (unsigned long)g[cur - 1u] * hi) {
            return cur;              /* held inside its band */
        }
    }
    for (i = 0u; i + 1u < n; i++) {
        /* the boundary to the next gear: the geometric mean */
        if ((unsigned long)v * v < (unsigned long)g[i] * g[i + 1u]) {
            break;
        }
    }
    s->gear = (unsigned char)(i + 1u);
    return s->gear;
}
