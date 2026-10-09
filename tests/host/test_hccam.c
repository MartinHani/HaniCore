/*
 * test_hccam.c - the cam pattern core (hccam.c) on every library pattern,
 * gcc -std=c89. Run by tools/test_hccam_host.py.
 *
 * The model: the engine's TRUE cycle position, a crank decoder that believes
 * a half (possibly the wrong one), and a cam that produces the pattern's
 * edges at offset + VVT. The decoder sees the true angle, or the true angle
 * + 360 while its half is wrong. Every action the core returns is applied
 * exactly as the firmware applies it. THE INVARIANT, checked on every edge:
 * the cycle is never claimed while the believed half is wrong.
 */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include "hccam.h"

#ifndef FUZZ_RUNS
#define FUZZ_RUNS 200
#endif

typedef struct {
    hccam_t c;
    unsigned char wrong;          /* the decoder's half is wrong             */
    unsigned char full;           /* the cycle is claimed                    */
    unsigned int  claims_wrong;   /* claims made while wrong (must stay 0)   */
    unsigned int  grants, loses, flips;
} eng_t;

static unsigned int wrap(long a)
{
    a %= 7200L;
    if (a < 0) a += 7200L;
    return (unsigned int)a;
}

static void edge(eng_t *e, unsigned int true_angle)
{
    unsigned int seen = e->wrong ? wrap((long)true_angle + 3600L) : true_angle;
    unsigned char act = hccam_edge(&e->c, seen, 1u, e->full);
    if (act & HCCAM_A_LOSE) { e->full = 0u; e->loses++; }
    if (act & HCCAM_A_FLIP) { e->wrong ^= 1u; e->flips++; }
    if (act & HCCAM_A_GRANT) { e->full = 1u; e->grants++; }
    if (e->full && e->wrong) e->claims_wrong++;
}

/* one cycle of the pattern at the given VVT deviation */
static void cycle(eng_t *e, int vvt_x10)
{
    unsigned char i;
    for (i = 0u; i < e->c.n; i++) {
        edge(e, wrap((long)e->c.cfg.offset_x10 + e->c.rel[i] + vvt_x10));
    }
}

static void setup(eng_t *e, unsigned char pattern, unsigned char n,
                  unsigned int offset, unsigned char wrong)
{
    hccam_cfg_t cfg;
    cfg.pattern = pattern; cfg.equal_n = n; cfg.offset_x10 = offset;
    cfg.tol_x10 = 150u; cfg.auth_x10 = 600u; cfg.confirm = 2u; cfg.errlimit = 3u;
    if (pattern == HCCAM_P_NISSAN_VQ || pattern == HCCAM_P_MIATA_NB) {
        cfg.tol_x10 = 100u;       /* their closest teeth are 40 degrees apart */
    }
    e->wrong = wrong; e->full = 0u; e->claims_wrong = 0u;
    e->grants = e->loses = e->flips = 0u;
    assert(hccam_init(&e->c, &cfg));
}

static const char *NAMES[] = { "none", "single", "equal", "quick-start",
    "Honda K 4+1", "Barra 3+1", "Toyota 4-1", "Nissan VQ", "Miata NB" };

static void test_acquire(unsigned char p, unsigned char n)
{
    eng_t e; unsigned char wrong; int c;
    for (wrong = 0u; wrong < 2u; wrong++) {
        setup(&e, p, n, 1234u, wrong);
        for (c = 0; c < 4; c++) cycle(&e, 0);
        assert(e.c.resolves);
        assert(e.full && !e.wrong && e.claims_wrong == 0u);
        assert(e.flips == wrong && e.c.dev_x10 == 0);
    }
    printf("  %-12s (%u teeth, window %u): acquires from either half, "
           "flips only the wrong one: OK\n", NAMES[p], e.c.n, e.c.k);
}

static void test_equal_symmetry(void)
{
    eng_t e; unsigned char n; int c;
    for (n = 1u; n <= 8u; n++) {
        setup(&e, HCCAM_P_EQUAL, n, 500u, 1u);
        for (c = 0; c < 6; c++) cycle(&e, 0);
        /* the half is GUARANTEED only if a tooth moved by 360 deg stays more
           than twice the VVT authority (+/-60) from every tooth it could be
           confused with: 1 tooth (360 away), 3 (120 away). 5 teeth: 72, 7:
           ~51 - decidable near zero VVT only, so not claimed at all */
        if (n == 1u || n == 3u) {
            assert(e.c.resolves && e.full && !e.wrong);
        } else {
            assert(!e.c.resolves && !e.full && e.flips == 0u);
            assert(e.c.cls == HCCAM_C_ALIVE);
        }
        assert(e.claims_wrong == 0u);
    }
    {
        hccam_cfg_t cfg = e.c.cfg;
        cfg.equal_n = 7u; cfg.auth_x10 = 200u;   /* +/-20 deg: decidable */
        assert(hccam_init(&e.c, &cfg) && e.c.resolves);
    }
    printf("  equal teeth at +/-60 deg VVT authority: 1 and 3 resolve, 2 and "
           "4..8 only say ALIVE (never a claim); 7 at +/-20 deg resolves: OK\n");
}

static void test_vvt(void)
{
    eng_t e; int c, v;
    setup(&e, HCCAM_P_QUICKSTART, 0u, 3000u, 0u);
    for (c = 0; c < 3; c++) cycle(&e, 0);
    assert(e.full);
    for (v = 0; v <= 450; v += 15) cycle(&e, v);    /* the phaser moves 45 deg */
    assert(e.full && e.c.sync_dev_x10 == 450 && e.loses == 0u);
    for (v = 450; v >= -300; v -= 15) cycle(&e, v);
    assert(e.full && e.c.sync_dev_x10 == -300);
    printf("  VVT sweep -30..+45 deg: stays synchronised, deviation follows "
           "(%d): OK\n", e.c.sync_dev_x10);
    for (c = 0; c < 3; c++) cycle(&e, 900);          /* beyond the authority */
    assert(!e.full && e.claims_wrong == 0u && e.c.cls == HCCAM_C_OFFSET);
    printf("  a cam 90 deg off (authority 60): OFFSET error, cycle withdrawn, "
           "never a flip: OK\n");
}

static void test_glitch_and_loss(void)
{
    eng_t e; int c; unsigned int l0;
    setup(&e, HCCAM_P_BARRA_3P1, 0u, 2000u, 0u);
    for (c = 0; c < 3; c++) cycle(&e, 0);
    assert(e.full);
    l0 = e.loses;
    /* a single extra edge in the 240 deg gap between teeth 1 and 2, 120 deg
       from both - not noise, only the window can reject it */
    edge(&e, wrap(2000L + 0L)); edge(&e, wrap(2000L + 1200L));
    edge(&e, wrap(2000L + 2400L)); edge(&e, wrap(2000L + 3600L));
    edge(&e, wrap(2000L + 6000L));
    for (c = 0; c < 3; c++) cycle(&e, 0);
    assert(e.c.glitches == 1u && e.loses == l0);
    assert(e.full && e.flips == 0u && e.claims_wrong == 0u);
    printf("  one glitch edge between two teeth: taken out of the window "
           "(%u error), no loss, no flip: OK\n", e.c.errors);
    /* a lost edge: skip tooth 2 once */
    edge(&e, wrap(2000L + 0L)); edge(&e, wrap(2000L + 1200L));
    edge(&e, wrap(2000L + 6000L));
    for (c = 0; c < 3; c++) cycle(&e, 0);
    assert(e.full && e.flips == 0u && e.claims_wrong == 0u && e.loses == l0);
    printf("  one missing edge: recovers, no flip: OK\n");
    /* noise: a pulse 2 degrees after a real edge */
    {
        unsigned int n0 = e.c.noise;
        edge(&e, wrap(2000L + 0L)); edge(&e, wrap(2000L + 20L));
        edge(&e, wrap(2000L + 1200L)); edge(&e, wrap(2000L + 3600L));
        edge(&e, wrap(2000L + 6000L));
        assert(e.c.noise == n0 + 1u && e.full && e.c.cls == HCCAM_C_SAME);
    }
    printf("  a noise pulse beside a real edge: ignored as NOISE: OK\n");
}

static void test_wrong_half_while_full(void)
{
    eng_t e; int c;
    setup(&e, HCCAM_P_HONDA_K_4P1, 0u, 700u, 0u);
    for (c = 0; c < 3; c++) cycle(&e, 0);
    assert(e.full);
    /* INJECTED from outside: the crank decoder's half is now wrong. Nothing
       can notice before cam evidence arrives; the bound is that the claim is
       withdrawn within errlimit edges (the window refilling across the jump)
       and the half moved only after confirm consistent teeth. */
    e.wrong = 1u;
    for (c = 0; c < 3; c++) cycle(&e, 0);
    assert(e.full && !e.wrong && e.flips == 1u);
    assert(e.claims_wrong <= e.c.cfg.errlimit);
    printf("  the decoder's half corrupted while FULL: claim withdrawn after "
           "%u edges (<= errlimit), moved after confirmation: OK\n",
           e.claims_wrong);
}

static void test_reset_and_config(void)
{
    eng_t e; hccam_cfg_t cfg; int c;
    setup(&e, HCCAM_P_QUICKSTART, 0u, 100u, 1u);
    for (c = 0; c < 3; c++) cycle(&e, 0);
    assert(e.full);
    hccam_reset(&e.c);            /* crank lost: history gone */
    assert(e.c.hn == 0u && e.c.cls == HCCAM_C_NONE);
    assert(hccam_edge(&e.c, 100u, 0u, 1u) == 0u);   /* no crank sync: nothing */
    cfg = e.c.cfg; cfg.tol_x10 = 450u;               /* 2 x 45 >= 80 */
    assert(!hccam_init(&e.c, &cfg));
    cfg.tol_x10 = 150u; cfg.pattern = 99u;
    assert(!hccam_init(&e.c, &cfg));
    cfg.pattern = HCCAM_P_EQUAL; cfg.equal_n = 9u;
    assert(!hccam_init(&e.c, &cfg));
    /* the validator's view: unusable / cannot tell the half / resolves */
    assert(hccam_check(&cfg) == 0u);
    cfg.equal_n = 4u;
    assert(hccam_check(&cfg) == 1u);
    cfg.pattern = HCCAM_P_QUICKSTART;
    assert(hccam_check(&cfg) == 2u);
    cfg.tol_x10 = 450u;
    assert(hccam_check(&cfg) == 0u);
    printf("  reset, no-crank edges, and unusable configurations refused: OK\n");
}

/* EXHAUSTIVE: one glitch at every 0.5 degree of every gap, every pattern.
   Established cycle: the glitch must not withdraw the claim or move the
   half. Acquisition from either half: never a claim on the wrong half. */
static void test_glitch_sweep(void)
{
    eng_t e; unsigned char p, g, wrong, pos_i; int c;
    unsigned long cases = 0uL;
    for (p = HCCAM_P_SINGLE; p < HCCAM_P_COUNT; p++) {
        unsigned char n = (unsigned char)(p == HCCAM_P_EQUAL ? 3u : 0u);
        setup(&e, p, n, 2500u, 0u);
        for (g = 0u; g < e.c.n; g++) {
            unsigned int gap = (g + 1u < e.c.n)
                ? (unsigned int)(e.c.rel[g + 1u] - e.c.rel[g])
                : (unsigned int)(7200u - e.c.rel[g]);
            unsigned int off;
            for (off = 5u; off + 5u < gap; off += 5u) {
                for (wrong = 0u; wrong < 3u; wrong++) {
                    /* wrong 0/1: acquisition from that half; 2: established */
                    setup(&e, p, n, 2500u, (unsigned char)(wrong == 1u));
                    if (wrong == 2u) for (c = 0; c < 4; c++) cycle(&e, 0);
                    {
                        unsigned int l0 = e.loses, f0 = e.flips;
                        for (c = 0; c < 3; c++) {
                            for (pos_i = 0u; pos_i < e.c.n; pos_i++) {
                                edge(&e, wrap((long)2500 + e.c.rel[pos_i]));
                                if (c == 1 && pos_i == g) {
                                    edge(&e, wrap((long)2500 + e.c.rel[pos_i] + off));
                                }
                            }
                        }
                        assert(e.claims_wrong == 0u);
                        if (wrong == 2u) {
                            if (!(e.full && e.loses == l0 && e.flips == f0)) {
                                printf("    pattern %u gap %u +%u.%u deg: loses %u "
                                       "flips %u full %u\n", p, g, off / 10u,
                                       off % 10u, e.loses - l0, e.flips - f0, e.full);
                            }
                            assert(e.full && e.loses == l0 && e.flips == f0);
                        }
                    }
                    cases++;
                }
            }
        }
    }
    printf("  one glitch at every 0.5 deg of every gap, all patterns (%lu "
           "cases): established cycles keep their claim and half, "
           "acquisition never claims the wrong half: OK\n", cases);
}

/* random glitches, dropped edges, VVT drift, random start half */
static void test_fuzz(void)
{
    eng_t e; unsigned char p; long t; int c, vvt, full_cycles, reported = 0;
    unsigned int trials = 0u;
    srand(12345u);
    for (p = HCCAM_P_SINGLE; p < HCCAM_P_COUNT; p++) {
        int run;
        for (run = 0; run < FUZZ_RUNS; run++) {
            unsigned char n = (unsigned char)(p == HCCAM_P_EQUAL ? 3u : 0u);
            unsigned char i;
            setup(&e, p, n, (unsigned int)(rand() % 7200), (unsigned char)(rand() & 1));
            vvt = 0; full_cycles = 0;
            for (c = 0; c < 60; c++) {
                vvt += (rand() % 21) - 10;
                if (vvt > 400) vvt = 400;
                if (vvt < -400) vvt = -400;
                for (i = 0u; i < e.c.n; i++) {
                    t = (long)e.c.cfg.offset_x10 + e.c.rel[i] + vvt;
                    if (rand() % 50 == 0) continue;               /* dropped */
                    edge(&e, wrap(t));
                    if (rand() % 30 == 0) {
                        /* half the glitches between this tooth and the next
                           (physical order), half anywhere up to 300 deg on */
                        long gap = (i + 1u < e.c.n)
                            ? (long)e.c.rel[i + 1u] - (long)e.c.rel[i]
                            : 7200L - (long)e.c.rel[i];
                        edge(&e, wrap(t + ((rand() & 1) ? rand() % (int)gap
                                                        : rand() % 3000)));
                    }
                }
                if (e.full) full_cycles++;
                if (e.claims_wrong && !reported) {
                    printf("    WRONG CLAIM: pattern %u run %d cycle %d vvt %d "
                           "tooth %u cls %u glitches %u errors %u\n", p, run, c,
                           vvt, e.c.tooth, e.c.cls, e.c.glitches, e.c.errors);
                    reported = 1;
                }
            }
            assert(e.claims_wrong == 0u);
            assert(full_cycles > 20);
            trials++;
        }
    }
    printf("  fuzz: %u runs x 60 cycles, drops 2 %%, glitches 3.3 %% (in-gap and anywhere), VVT "
           "drift: never a claim on the wrong half: OK\n", trials);
}

int main(void)
{
    unsigned char p;
    printf("hccam pattern core tests\n");
    for (p = HCCAM_P_SINGLE; p < HCCAM_P_COUNT; p++) {
        if (p == HCCAM_P_EQUAL) test_acquire(p, 3u);
        else test_acquire(p, 0u);
    }
    test_equal_symmetry();
    test_vvt();
    test_glitch_and_loss();
    test_wrong_half_while_full();
    test_reset_and_config();
    test_glitch_sweep();
    test_fuzz();
    printf("PASS: all hccam tests\n");
    return 0;
}
