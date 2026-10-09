/*
 * test_hcdtc.c - the DTC core (hcdtc.c), gcc -std=c89.
 * Run by tools/test_hcdtc_host.py (negative controls + Keil helper check).
 */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "hcdtc.h"

static const hcdtc_def_t DEFS[] = {
    {0x0105u, 500u, 1000u, HCDTC_MIL},   /* 0 MAP circuit                   */
    {0x0560u, 2000u, 2000u, 0u},         /* 1 system voltage, no MIL        */
    {0x0335u, 0u, 10000u, HCDTC_MIL},    /* 2 crank sync loss: an event     */
};
#define N 3u

static unsigned int ff[HCDTC_FF_N] = {3000u, 900u, 1500u, 250u};

static void step(hcdtc_t *d, unsigned int bits, unsigned int ms)
{
    unsigned int fail[2];
    fail[0] = bits; fail[1] = 0u;
    hcdtc_step(d, DEFS, N, fail, ms, ff);
}

static void test_debounce(void)
{
    hcdtc_t d;
    unsigned int t;
    hcdtc_clear(&d);
    for (t = 10u; t < 500u; t += 10u) {
        step(&d, 1u, 10u);
        assert(!(d.p[0].st & HCDTC_S_ACTIVE) && (d.p[0].st & HCDTC_S_FAIL) && !d.mil);
    }
    step(&d, 1u, 10u);                                 /* 500 ms */
    assert((d.p[0].st & HCDTC_S_ACTIVE) && (d.p[0].st & HCDTC_S_STORED));
    assert(d.mil && d.n_active == 1u && d.n_stored == 1u && d.p[0].count == 1u);
    /* heal: 1000 ms clean */
    for (t = 10u; t < 1000u; t += 10u) { step(&d, 0u, 10u); assert(d.mil); }
    step(&d, 0u, 10u);
    assert(!(d.p[0].st & HCDTC_S_ACTIVE) && (d.p[0].st & HCDTC_S_STORED) && !d.mil);
    assert(d.n_active == 0u && d.n_stored == 1u);
    printf("debounce: confirmed at exactly 500 ms, healed at exactly 1000 ms, history kept\n");
}

static void test_flicker(void)
{
    hcdtc_t d;
    unsigned int k;
    hcdtc_clear(&d);
    for (k = 0u; k < 1000u; k++) {
        step(&d, (k % 10u) < 9u ? 1u : 0u, 50u);   /* 450 ms fail, 50 ms clean */
        assert(!(d.p[0].st & HCDTC_S_ACTIVE));
    }
    printf("flicker: 450 ms fails with 50 ms gaps never confirm a 500 ms path\n");
}

static void test_heal_restart(void)
{
    hcdtc_t d;
    unsigned int k;
    hcdtc_clear(&d);
    step(&d, 1u, 500u);
    assert(d.p[0].st & HCDTC_S_ACTIVE);
    for (k = 0u; k < 100u; k++) {                    /* 900 ms clean, 10 fail */
        step(&d, 0u, 900u);
        step(&d, 1u, 10u);
        assert(d.p[0].st & HCDTC_S_ACTIVE);
    }
    assert(d.p[0].count == 1u);
    printf("heal restart: a fault returning within the heal time stays one active event\n");
}

static void test_mil_class_and_events(void)
{
    hcdtc_t d;
    hcdtc_clear(&d);
    step(&d, 2u, 2000u);                              /* voltage: no MIL */
    assert((d.p[1].st & HCDTC_S_ACTIVE) && !d.mil);
    step(&d, 4u, 10u);                                /* event, set 0 */
    assert((d.p[2].st & HCDTC_S_ACTIVE) && d.mil);
    assert(!(d.p[1].st & HCDTC_S_ACTIVE) || d.p[1].t_ms == 10u);
    printf("MIL class: a no-MIL path never lights it; an event path (set 0) confirms on one sample\n");
}

static void test_freeze_and_list(void)
{
    hcdtc_t d;
    hcdtc_clear(&d);
    step(&d, 4u, 10u);
    ff[0] = 5000u;
    step(&d, 5u, 500u);
    assert(d.ff_code == 0x0335u && d.ff[0] == 3000u);    /* the FIRST one */
    assert(hcdtc_code(&d, DEFS, N, HCDTC_S_ACTIVE, 0u) == 0x0105u);
    assert(hcdtc_code(&d, DEFS, N, HCDTC_S_ACTIVE, 1u) == 0x0335u);
    assert(hcdtc_code(&d, DEFS, N, HCDTC_S_ACTIVE, 2u) == 0u);
    hcdtc_clear(&d);
    assert(d.ff_code == 0u && d.n_stored == 0u && hcdtc_code(&d, DEFS, N, HCDTC_S_STORED, 0u) == 0u);
    step(&d, 1u, 500u);                                 /* still present: re-confirms */
    assert((d.p[0].st & HCDTC_S_ACTIVE) && d.ff_code == 0x0105u && d.ff[0] == 5000u);
    ff[0] = 3000u;
    printf("freeze frame: the first confirmation since the clear; list by status; clear = OBD mode 04\n");
}

static void test_bounds(void)
{
    hcdtc_t d;
    static hcdtc_def_t many[40];
    unsigned int fail[3] = {0xFFFFu, 0xFFFFu, 0xFFFFu};
    unsigned int k;
    memset(many, 0, sizeof many);
    for (k = 0u; k < 40u; k++) { many[k].code = (unsigned int)k + 1u; many[k].heal_ms = 65535u; }
    memset(&d, 0xA5, sizeof d);
    hcdtc_clear(&d);
    for (k = 0u; k < 300u; k++) {
        hcdtc_step(&d, many, 40u, fail, 65535u, ff);
        fail[0] ^= 0xFFFFu; fail[1] ^= 0xFFFFu;
    }
    assert(d.n_stored == HCDTC_MAX && d.p[0].count == 150u);
    for (k = 0u; k < 300u; k++) {
        hcdtc_step(&d, many, 40u, fail, 65535u, ff);
        fail[0] ^= 0xFFFFu; fail[1] ^= 0xFFFFu;
    }
    assert(d.p[0].count == 255u);
    assert(hcdtc_code(&d, many, 40u, HCDTC_S_STORED, (unsigned char)(HCDTC_MAX - 1u)) == HCDTC_MAX);
    assert(hcdtc_code(&d, many, 40u, HCDTC_S_STORED, (unsigned char)HCDTC_MAX) == 0u);
    printf("bounds: n clamped to %u paths, counts saturate at 255, timers at 65535\n", HCDTC_MAX);
}

/* hcdtc_lists() == 2 x k_n hcdtc_code() calls, over pseudo-random states */
static void test_lists_equal_code(void)
{
    hcdtc_def_t many[30];
    hcdtc_t d;
    unsigned int act[4], sto[4];
    unsigned int seed = 12345u, t, k;
    for (k = 0u; k < 30u; k++) { many[k].code = 100u + k; many[k].flags = 0u; }
    for (t = 0u; t < 2000u; t++) {
        unsigned char n = (unsigned char)(t % 31u);
        memset(&d, 0, sizeof d);
        for (k = 0u; k < HCDTC_MAX; k++) {
            seed = seed * 1103515245u + 12345u;
            d.p[k].st = (unsigned char)((seed >> 16) & 0x07u);
        }
        hcdtc_lists(&d, many, n, act, sto, 4u);
        for (k = 0u; k < 4u; k++) {
            assert(act[k] == hcdtc_code(&d, many, n, HCDTC_S_ACTIVE, (unsigned char)k));
            assert(sto[k] == hcdtc_code(&d, many, n, HCDTC_S_STORED, (unsigned char)k));
        }
    }
    printf("lists: one pass == eight hcdtc_code() scans over 2000 states\n");
}

int main(void)
{
    test_debounce();
    test_flicker();
    test_heal_restart();
    test_mil_class_and_events();
    test_freeze_and_list();
    test_bounds();
    test_lists_equal_code();
    printf("hcdtc: ALL PASS\n");
    return 0;
}
