/*
 * hccam.c - see hccam.h. SHARED, SFR-FREE, 16-BIT ONLY, bounded loops.
 *
 * Pattern angles (crank degrees x10, CPU-pin edges, tooth 0 = 0) and their
 * SOFTWARE REFERENCE IMPLEMENTATION (rusEFI firmware/controllers/trigger/
 * decoders), cam degrees doubled to crank degrees:
 *   QUICKSTART  trigger_universal.cpp configureQuickStartSenderWheel: the
 *               sensor's falling edges at cam 90/130/220/360 = crank 180/260/
 *               440/720 -> spacing 80/180/280/180. On the ME7.1.1 the input
 *               stage inverts: these are the CPU-RISING edges; the CPU-
 *               falling ones are equidistant (car, 2026-09-27, the project rules).
 *   HONDA_K_4P1 trigger_honda.cpp configureHondaK_4_1: rises at cam 55.5/
 *               145.5/235.5/325.5/353 -> 180/180/180/55/125.
 *   BARRA_3P1   trigger_misc.cpp configureBarra3plus1cam -> 120/240/240/120.
 *   TOYOTA_4M1  trigger_structure.cpp TT_VVT_TOYOTA_4_1 (4 slots, 1 missing)
 *               -> 180/180/360.
 *   NISSAN_VQ   trigger_nissan.cpp initializeNissanVQvvt -> 120/40/80/40/
 *               200/240.
 *   MIATA_NB    trigger_mazda.cpp initializeMazdaMiataVVtCamShape (rises at
 *               360/679/720) -> 319/41/360.
 */
#include "hccam.h"

hccam_t hccam_bank[2];
static hccam_t s_check;          /* hccam_check()'s scratch */

static const unsigned int P_QS[]  = { 0u, 800u, 2600u, 5400u };
static const unsigned int P_HK[]  = { 0u, 1800u, 3600u, 5400u, 5950u };
static const unsigned int P_BA[]  = { 0u, 1200u, 3600u, 6000u };
static const unsigned int P_T41[] = { 0u, 1800u, 3600u };
static const unsigned int P_VQ[]  = { 0u, 1200u, 1600u, 2400u, 2800u, 4800u };
static const unsigned int P_NB[]  = { 0u, 3190u, 3600u };

static unsigned int fwd(unsigned int a, unsigned int b)   /* b -> a, 0..7199 */
{
    return (a >= b) ? (unsigned int)(a - b) : (unsigned int)(a + HCCAM_CYCLE - b);
}

static unsigned int dist(unsigned int a, unsigned int b)  /* |a - b| */
{
    return (a >= b) ? (unsigned int)(a - b) : (unsigned int)(b - a);
}

static unsigned int circ(unsigned int a, unsigned int b)  /* on the 720 circle */
{
    unsigned int d = dist(a, b);
    return (d > HCCAM_HALF) ? (unsigned int)(HCCAM_CYCLE - d) : d;
}

static unsigned int add_half(unsigned int a)
{
    return (a >= HCCAM_HALF) ? (unsigned int)(a - HCCAM_HALF)
                             : (unsigned int)(a + HCCAM_HALF);
}

unsigned char HCCAM_FAR hccam_pattern_teeth(unsigned char pattern, unsigned char equal_n,
                                  unsigned int *rel)
{
    const unsigned int *t = 0;
    unsigned char n = 0u, i;

    switch (pattern) {
    case HCCAM_P_SINGLE:      rel[0] = 0u; return 1u;
    case HCCAM_P_EQUAL:
        if (equal_n < 1u || equal_n > HCCAM_MAX_TEETH) return 0u;
        for (i = 0u; i < equal_n; i++) {
            rel[i] = (unsigned int)(((unsigned int)i * HCCAM_CYCLE) / equal_n);
        }
        return equal_n;
    case HCCAM_P_QUICKSTART:  t = P_QS;  n = 4u; break;
    case HCCAM_P_HONDA_K_4P1: t = P_HK;  n = 5u; break;
    case HCCAM_P_BARRA_3P1:   t = P_BA;  n = 4u; break;
    case HCCAM_P_TOYOTA_4M1:  t = P_T41; n = 3u; break;
    case HCCAM_P_NISSAN_VQ:   t = P_VQ;  n = 6u; break;
    case HCCAM_P_MIATA_NB:    t = P_NB;  n = 3u; break;
    default: return 0u;
    }
    for (i = 0u; i < n; i++) rel[i] = t[i];
    return n;
}

/* the window of k spacings ending at tooth i equals the one ending at j */
static unsigned char same_window(const hccam_t *c, unsigned char i,
                                 unsigned char j, unsigned char k)
{
    unsigned char m, a, b;
    for (m = 0u; m < k; m++) {
        a = (unsigned char)((i + c->n - m) % c->n);
        b = (unsigned char)((j + c->n - m) % c->n);
        if (dist(c->sp[a], c->sp[b]) > (unsigned int)(2u * c->cfg.tol_x10)) {
            return 0u;
        }
    }
    return 1u;
}

unsigned char HCCAM_FAR hccam_init(hccam_t *c, const hccam_cfg_t *cfg)
{
    unsigned int i;
    unsigned char *p = (unsigned char *)c;
    unsigned char a, b, k, uniq, n, hit;

    for (i = 0u; i < sizeof(*c); i++) p[i] = 0u;   /* no ?C_INIT on target */
    c->cfg = *cfg;
    c->tooth = 0xFFu;
    n = hccam_pattern_teeth(cfg->pattern, cfg->equal_n, c->rel);
    if (n == 0u || cfg->confirm == 0u || cfg->errlimit == 0u) {
        c->n = 0u;
        return 0u;
    }
    c->n = n;
    c->min_sp = HCCAM_CYCLE;
    for (a = 0u; a < n; a++) {
        c->sp[a] = (n == 1u) ? HCCAM_CYCLE
                 : fwd(c->rel[a], c->rel[(unsigned char)((a + n - 1u) % n)]);
        if (c->sp[a] < c->min_sp) c->min_sp = c->sp[a];
    }
    /* a spacing tolerance must leave room for noise below the closest pair */
    if (c->cfg.tol_x10 == 0u || (unsigned int)(2u * c->cfg.tol_x10) >= c->min_sp) {
        c->n = 0u;
        return 0u;
    }
    /* the shortest window that tells every tooth apart */
    c->k = 0u;
    for (k = 1u; k <= (unsigned char)(n < HCCAM_HIST ? n : HCCAM_HIST); k++) {
        uniq = 1u;
        for (a = 0u; a < n && uniq; a++) {
            for (b = (unsigned char)(a + 1u); b < n; b++) {
                if (same_window(c, a, b, k)) { uniq = 0u; break; }
            }
        }
        if (uniq) { c->k = k; break; }
    }
    if (c->k == 0u) {
        c->k = (unsigned char)(n < HCCAM_HIST ? n : HCCAM_HIST);
    } else if (c->k < HCCAM_HIST) {
        /* ONE SPACING MORE THAN IDENTIFICATION NEEDS: a glitch then has to
           fake two spacings, not one, to look like a tooth (the fuzz found
           a Miata NB - identifiable from one spacing - claimed on the wrong
           half by two coincidental glitches). */
        c->k++;
    }
    /* the half: a tooth decides it when no tooth its spacing window cannot
       tell apart sits within twice the VVT authority of it moved by 360
       degrees (then "this half at +dev" and "the other half at -dev" are
       both possible). Equal teeth at an even count never decide; at an odd
       count only while the authority is below a quarter of the spacing. */
    c->resolves = 0u;
    for (a = 0u; a < n && !c->resolves; a++) {
        hit = 0u;
        for (b = 0u; b < n; b++) {
            if (same_window(c, a, b, c->k)
                && circ(c->rel[b], add_half(c->rel[a]))
                   < (unsigned int)(2u * c->cfg.auth_x10)) hit = 1u;
        }
        if (!hit) c->resolves = 1u;
    }
    return 1u;
}

void HCCAM_FAR hccam_reset(hccam_t *c)
{
    c->hn = 0u;
    c->est = 0u;
    c->same_run = 0u;
    c->other_run = 0u;
    c->err_run = 0u;
    c->tooth = 0xFFu;
    c->cls = HCCAM_C_NONE;
}

static unsigned char pattern_error(hccam_t *c, unsigned char cls,
                                   unsigned char cycle_known)
{
    c->cls = cls;
    c->tooth = 0xFFu;
    c->same_run = 0u;
    c->other_run = 0u;
    if (c->errors != 0xFFFFu) c->errors++;
    if (c->err_run < 255u) c->err_run++;
    if (cycle_known && c->err_run >= c->cfg.errlimit) {
        return HCCAM_A_LOSE;
    }
    return 0u;
}

/* The last k spacings of win[0..k] against every tooth's window; every
   candidate that matches is judged by its ANGLE (a = win[k]). A pattern whose
   spacing cannot name the tooth (equal teeth) still decides the half when all
   candidates inside the authority agree on it. */
typedef struct {
    unsigned char found, n_same, n_other, t_same, t_other;
    int best_same, best_other;
} judge_t;

static int iabs(int v) { return v < 0 ? -v : v; }

static void judge(const hccam_t *c, const unsigned int *win, judge_t *j)
{
    unsigned char i, m;
    unsigned int e, d;
    int dev;

    j->found = 0u; j->n_same = 0u; j->n_other = 0u;
    j->t_same = 0xFFu; j->t_other = 0xFFu;
    j->best_same = 0x7FFF; j->best_other = 0x7FFF;
    for (i = 0u; i < c->n; i++) {
        for (m = 0u; m < c->k; m++) {
            d = fwd(win[c->k - m], win[c->k - m - 1u]);
            /* one tooth: consecutive edges are ~720 apart, and 720 + jitter
               wraps to a small number */
            if (c->n == 1u && d < HCCAM_HALF) d = (unsigned int)(d + HCCAM_CYCLE);
            if (dist(d, c->sp[(unsigned char)((i + c->n - m) % c->n)])
                > c->cfg.tol_x10) break;
        }
        if (m != c->k) continue;
        j->found++;
        e = (unsigned int)(c->cfg.offset_x10 + c->rel[i]);
        if (e >= HCCAM_CYCLE) e = (unsigned int)(e - HCCAM_CYCLE);
        d = fwd(win[c->k], e);
        dev = (d > HCCAM_HALF) ? -(int)(HCCAM_CYCLE - d) : (int)d;
        if ((unsigned int)iabs(dev) <= c->cfg.auth_x10) {
            j->n_same++;
            if (iabs(dev) < iabs(j->best_same)) { j->best_same = dev; j->t_same = i; }
            continue;
        }
        d = add_half(d);
        dev = (d > HCCAM_HALF) ? -(int)(HCCAM_CYCLE - d) : (int)d;
        if ((unsigned int)iabs(dev) <= c->cfg.auth_x10) {
            j->n_other++;
            if (iabs(dev) < iabs(j->best_other)) { j->best_other = dev; j->t_other = i; }
        }
    }
}

unsigned char HCCAM_FAR hccam_edge(hccam_t *c, unsigned int a, unsigned char crank_ok,
                         unsigned char cycle_known)
{
    unsigned char i, n_same, n_other, t_same, t_other, act = 0u;
    int best_same, best_other;
    unsigned int win[HCCAM_HIST + 1u];
    judge_t j;

    if (c->n == 0u) {
        return 0u;
    }
    if (!crank_ok) {
        hccam_reset(c);
        return 0u;
    }
    /* noise: closer to the previous accepted edge than any tooth pair. ONE
       of the two is not a tooth - and it is not always the newer one: a
       glitch accepted just before a real tooth makes the TOOTH look like
       noise (the exhaustive sweep found it on the quick-start wheel). If the
       window with this edge in the previous one's place reads as a tooth -
       in the established half, when there is one - the previous edge was the
       glitch and is replaced. */
    if (c->hn != 0u && c->n > 1u
        && fwd(a, c->hist[c->hn - 1u]) + c->cfg.tol_x10 < c->min_sp) {
        judge_t g;
        /* only a previous edge that was NOT read as a tooth is a suspect */
        if (c->hn >= (unsigned char)(c->k + 1u)
            && c->cls != HCCAM_C_SAME && c->cls != HCCAM_C_OTHER
            && c->cls != HCCAM_C_ALIVE) {
            for (i = 0u; i < c->k; i++) win[i] = c->hist[c->hn - 1u - c->k + i];
            win[c->k] = a;
            judge(c, win, &g);
            if (c->resolves && (c->est ? (g.n_same != 0u && g.n_other == 0u)
                                       : (g.n_same != 0u || g.n_other != 0u))) {
                c->hn--;                          /* drop the glitch ... */
                if (c->glitches != 0xFFFFu) c->glitches++;
                goto accept;                      /* ... and read the tooth */
            }
        }
        c->cls = HCCAM_C_NOISE;
        if (c->noise != 0xFFFFu) c->noise++;
        return 0u;
    }
accept:
    if (c->hn == (unsigned char)(c->k + 2u)) {
        for (i = 0u; i <= c->k; i++) c->hist[i] = c->hist[i + 1u];
        c->hn = (unsigned char)(c->k + 1u);
    }
    c->hist[c->hn++] = a;
    if (c->hn < (unsigned char)(c->k + 1u)) {
        c->cls = HCCAM_C_NONE;
        return 0u;
    }
    /* the window: the newest k+1 accepted edges */
    for (i = 0u; i <= c->k; i++) win[i] = c->hist[c->hn - 1u - c->k + i];
    judge(c, win, &j);
    if (c->resolves && c->hn == (unsigned char)(c->k + 2u)
        && ((j.n_same == 0u && j.n_other == 0u)
            || (c->est && j.n_same == 0u))) {
        /* ONE GLITCH. An extra edge between two teeth breaks the windows it
           sits in - as an unknown spacing, as one that looks like another
           tooth at the wrong angle, or (the dangerous one) as a tooth of the
           OTHER half: on a Honda K 4+1 a glitch ~55 deg after a tooth mimics
           the wheel's own short tooth. If the window WITHOUT the previous
           edge puts this edge on a tooth inside the authority - in the
           established half, when there is one - that edge was the glitch:
           forget it and go on. */
        judge_t g;
        for (i = 0u; i < c->k; i++) win[i] = c->hist[i];
        win[c->k] = a;
        judge(c, win, &g);
        if (c->est ? (g.n_same != 0u && g.n_other == 0u)
                   : (g.n_same != 0u || g.n_other != 0u)) {
            j = g;
            c->hist[c->hn - 2u] = a;
            c->hn--;
            if (c->glitches != 0xFFFFu) c->glitches++;
        }
    }
    if (c->est && c->resolves && j.n_same == 0u && c->n > 1u
        && c->hn >= (unsigned char)(c->k + 1u)) {
        /* ONE MISSING EDGE, in an established half: the newest spacing is
           two consecutive pattern spacings. Put the edge that should have
           been there back and read the window again; only a reading in the
           established half is taken. */
        unsigned int d = fwd(a, c->hist[c->hn - 2u]);
        unsigned char t;
        judge_t g;
        for (t = 0u; t < c->n; t++) {
            unsigned char tp = (unsigned char)((t + c->n - 1u) % c->n);
            if (dist(d, (unsigned int)(c->sp[t] + c->sp[tp])) > c->cfg.tol_x10) {
                continue;
            }
            for (i = 0u; i + 1u < c->k; i++) win[i] = c->hist[c->hn - c->k + i];
            win[c->k - 1u] = (a >= c->sp[t]) ? (unsigned int)(a - c->sp[t])
                                             : (unsigned int)(a + HCCAM_CYCLE - c->sp[t]);
            win[c->k] = a;
            judge(c, win, &g);
            if (g.n_same != 0u && g.n_other == 0u && g.t_same == t) {
                j = g;
                c->hist[c->hn - 1u] = win[c->k - 1u];      /* the virtual edge */
                if (c->hn == (unsigned char)(c->k + 2u)) {
                    for (i = 0u; i <= c->k; i++) c->hist[i] = c->hist[i + 1u];
                    c->hn--;
                }
                c->hist[c->hn++] = a;
                if (c->missed != 0xFFFFu) c->missed++;
                break;
            }
        }
    }
    if (j.found == 0u) {
        return pattern_error(c, HCCAM_C_ERROR, cycle_known);
    }
    if (j.n_same == 0u && j.n_other == 0u && c->resolves) {
        return pattern_error(c, HCCAM_C_OFFSET, cycle_known);
    }
    n_same = j.n_same; n_other = j.n_other;
    t_same = j.t_same; t_other = j.t_other;
    best_same = j.best_same; best_other = j.best_other;
    if (!c->resolves || (n_same != 0u && n_other != 0u)) {
        c->err_run = 0u;
        c->cls = HCCAM_C_ALIVE;          /* alive; says nothing about the half */
        c->tooth = 0xFFu;
        return 0u;
    }
    if (n_same != 0u) {
        c->err_run = 0u;
        c->cls = HCCAM_C_SAME;
        c->tooth = t_same;
        c->dev_x10 = best_same;
        if (t_same == 0u) c->sync_dev_x10 = best_same;
        c->other_run = 0u;
        if (c->same_run < 255u) c->same_run++;
        if (c->same_run >= c->n && c->same_run >= c->cfg.confirm) {
            c->est = 1u;                 /* a whole cycle agrees */
        }
        if (!cycle_known && c->same_run >= c->cfg.confirm) {
            act = HCCAM_A_GRANT;
        }
        return act;
    }
    if (n_other != 0u) {
        c->err_run = 0u;
        c->cls = HCCAM_C_OTHER;
        c->tooth = t_other;
        c->same_run = 0u;
        if (c->other_run < 255u) c->other_run++;
        if (cycle_known) {
            /* the claimed cycle may be wrong: stop claiming it NOW */
            act = HCCAM_A_LOSE;
        }
        /* HYSTERESIS BY CONFIDENCE: a half a whole cycle has agreed on is
           moved only by more than a whole cycle of the other half (the claim
           is already withdrawn above; only the move waits). */
        if (c->other_run >= (c->est ? (unsigned char)(c->n + 1u > c->cfg.confirm
                                                      ? c->n + 1u : c->cfg.confirm)
                                    : c->cfg.confirm)) {
            c->est = 0u;
            for (i = 0u; i < c->hn; i++) c->hist[i] = add_half(c->hist[i]);
            c->other_run = 0u;
            c->same_run = c->cfg.confirm;
            c->dev_x10 = best_other;
            if (t_other == 0u) c->sync_dev_x10 = best_other;
            if (c->flips != 0xFFFFu) c->flips++;
            act = (unsigned char)(act | HCCAM_A_FLIP | HCCAM_A_GRANT);
        }
        return act;
    }
    return pattern_error(c, HCCAM_C_OFFSET, cycle_known);
}

unsigned char HCCAM_FAR hccam_check(const hccam_cfg_t *cfg)
{
    if (!hccam_init(&s_check, cfg)) {
        return 0u;
    }
    return (unsigned char)(s_check.resolves ? 2u : 1u);
}
