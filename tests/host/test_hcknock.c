/*
 * test_hcknock.c - the knock-control strategy core (hcknock.c), gcc -std=c89.
 * Run by tools/test_hcknock_host.py (which also runs the negative controls).
 *
 * The model: per-cylinder background noise (the integrated knock-window
 * level of a quiet combustion, mean m[cyl] counts, +-25 % uniform), a knock
 * adds a multiple of it. Deterministic LCG. The parameter set is the Bosch
 * ME7.1.1 sibling calibration read by tools/an OEM-firmware analysis script (not published) (KFKEF1
 * 2.69..3.5, KRFTP1 16 / KRFTP2 4, FKENDY 1.125, KRFKN 2.25 deg, KRMXN 18,
 * KRDWSN 15), expressed in this core's units.
 */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "hcknock.h"

static unsigned long seed = 12345u;
static unsigned int rnd(unsigned int n)
{
    seed = seed * 1103515245UL + 12345UL;
    return (unsigned int)((seed >> 16) & 0x7FFFu) % n;
}

/* m * (0.75 .. 1.25) */
static unsigned int noise(unsigned int m)
{
    return (unsigned int)(((unsigned long)m * (750u + rnd(501u))) / 1000u);
}

static hcknock_cfg_t base_cfg(void)
{
    hcknock_cfg_t c;
    unsigned char i;
    static const unsigned int rpm[HCKNOCK_KEFN] = {800u, 1600u, 2400u, 3600u, 5200u, 6400u};
    static const unsigned char kef[HCKNOCK_KEFN] = {56u, 44u, 44u, 43u, 43u, 46u};

    memset(&c, 0, sizeof c);
    c.cyls = 4u;
    for (i = 0u; i < HCKNOCK_CYL; i++) c.sensor[i] = (unsigned char)(i < 4u ? 0u : 1u);
    c.rpm_min = 400u;             /* NKRF */
    c.load_min = 25u;             /* LKRN ~25 % */
    c.clt_min = 39;               /* TMKR */
    c.tp = 16u;                   /* KRFTP1 */
    c.tp_dyn = 4u;                /* KRFTP2/3 */
    for (i = 0u; i < HCKNOCK_KEFN; i++) { c.kef_rpm[i] = rpm[i]; c.kef16[i] = kef[i]; }
    c.kef_dyn16 = 18u;            /* FKENDY 1.125 */
    c.ref_init = 204u;            /* REFINI 0.996 V of 5 V */
    c.learn = 32u;
    c.step_q = 9u;                /* 2.25 deg */
    c.max_q = 72u;                /* 18 deg */
    c.safe_q = 60u;               /* 15 deg */
    c.reapply_ms = 600u;          /* 0.25 deg / 0.6 s ~ 0.75 deg per KRVFN at 3 krpm */
    c.diag_rpm = 2000u;
    c.ref_min = 10u;
    c.ref_max = 900u;
    c.diag_n = 50u;
    c.stop_n = 200u;
    return c;
}

static hcknock_in_t run_in(unsigned int ikr)
{
    hcknock_in_t in;
    in.ikr = ikr; in.rpm = 3000u; in.load = 60u; in.clt = 90; in.dyn = 0u;
    return in;
}

static const unsigned int M[HCKNOCK_CYL] = {90u, 110u, 100u, 120u, 95u, 105u, 80u, 130u};

/* warm up every cylinder on its own noise */
static void settle(hcknock_t *k, const hcknock_cfg_t *c, unsigned int n)
{
    unsigned int i;
    for (i = 0u; i < n; i++) {
        unsigned char cyl = (unsigned char)(i % c->cyls);
        hcknock_in_t in = run_in(noise(M[cyl]));
        (void)hcknock_ignition(k, c, cyl, &in);
    }
}

static void test_thr_exhaustive(void)
{
    unsigned int r4;
    unsigned int kef;
    for (r4 = 0u; r4 <= 4092u; r4++)
        for (kef = 16u; kef <= 255u; kef++)
            assert(hcknock_thr4(r4, (unsigned char)kef)
                   == (unsigned int)(((unsigned long)r4 * kef) / 16u));
    assert(hcknock_thr4(60000u, 255u) == hcknock_thr4(4092u, 255u));
    printf("thr4 exhaustive: exact over r4 0..4092 x kef 16..255\n");
}

static void test_quiet(void)
{
    hcknock_cfg_t c = base_cfg();
    hcknock_t k;
    unsigned int i;
    hcknock_reset(&k, &c);
    for (i = 0u; i < 40000u; i++) {
        unsigned char cyl = (unsigned char)(i % 4u);
        hcknock_in_t in = run_in(noise(M[cyl]));
        in.rpm = (unsigned int)(1000u + (i / 8u) % 5500u);   /* sweep the kef curve */
        assert(hcknock_ignition(&k, &c, cyl, &in) == 0u);
    }
    for (i = 0u; i < 4u; i++) {
        unsigned int r = k.ref16[i] >> 4;
        assert(r * 100u >= M[i] * 92u && r * 100u <= M[i] * 108u);
        assert(hcknock_retard(&k, &c, (unsigned char)i) == 0u);
    }
    assert(k.knocks == 0u && k.fault == 0u);
    printf("quiet: 40000 ignitions, +-25%% noise, 1000..6500 rpm: 0 knocks, reference within 8%%\n");
}

static void test_single(void)
{
    hcknock_cfg_t c = base_cfg();
    hcknock_t k;
    hcknock_in_t in;
    unsigned int t;
    hcknock_reset(&k, &c);
    settle(&k, &c, 4000u);
    in = run_in(M[2] * 4u);
    assert(hcknock_ignition(&k, &c, 2u, &in) == 1u);
    assert(hcknock_retard(&k, &c, 2u) == c.step_q);
    assert(hcknock_retard(&k, &c, 0u) == 0u && hcknock_retard(&k, &c, 1u) == 0u
           && hcknock_retard(&k, &c, 3u) == 0u);
    assert(k.kcount[2] == 1u && k.knocks == 1u);
    /* recovery: exactly one q per reapply_ms of quiet, in 10 ms ticks */
    for (t = 10u; t <= (unsigned int)c.step_q * c.reapply_ms; t += 10u) {
        hcknock_tick(&k, &c, 10u);
        assert(k.ret_q[2] == c.step_q - t / c.reapply_ms);
    }
    assert(hcknock_retard(&k, &c, 2u) == 0u);
    printf("single knock: only its cylinder retards %u q, back to 0 in exactly %u ms\n",
           c.step_q, (unsigned int)c.step_q * c.reapply_ms);
}

static void test_sustained(void)
{
    hcknock_cfg_t c = base_cfg();
    hcknock_t k;
    unsigned int i, det = 0u, r;
    hcknock_reset(&k, &c);
    settle(&k, &c, 4000u);
    for (i = 0u; i < 2000u; i++) {
        /* 4x the mean +-10 %: every one above 2.69 x the settled reference */
        hcknock_in_t in = run_in((unsigned int)((unsigned long)M[1] * 4u * (900u + rnd(201u)) / 1000u));
        det += hcknock_ignition(&k, &c, 1u, &in);
        hcknock_tick(&k, &c, 5u);
    }
    r = k.ref16[1] >> 4;
    printf("sustained: %u/2000 detected, reference %u (noise %u), retard %u q, at max %u\n",
           det, r, M[1], k.ret_q[1], k.at_max);
    assert(det == 2000u);                     /* the reference never learns knock */
    assert(r * 100u <= M[1] * 108u);
    assert(k.ret_q[1] == c.max_q);
    assert(k.at_max >= det - c.max_q / c.step_q - 1u);
    assert(hcknock_retard(&k, &c, 0u) == 0u);
}

static void test_exact_filter(void)
{
    hcknock_cfg_t c = base_cfg();
    hcknock_t k;
    static const unsigned int targets[] = {500u, 37u, 1023u, 0u, 204u, 1u, 999u};
    unsigned int t, i;
    c.cyls = 1u;
    c.learn = 0u;
    c.kef16[0] = c.kef16[1] = c.kef16[2] = c.kef16[3] = c.kef16[4] = c.kef16[5] = 255u;
    for (t = 0u; t < sizeof targets / sizeof targets[0]; t++) {
        unsigned int tp;
        for (tp = 1u; tp <= 32u; tp++) {
            hcknock_in_t in = run_in(targets[t]);
            c.tp = (unsigned char)tp;
            hcknock_reset(&k, &c);
            /* start far away: from above, or from 1/8 below (kef 15.9 keeps
               the approach from below quiet; a reference of 0 would make
               every sample a knock - that is test_stop's case) */
            k.ref16[0] = (t & 1u) ? 16368u : targets[t] * 2u;
            for (i = 0u; i < 2000u; i++) {
                assert(hcknock_ignition(&k, &c, 0u, &in) == 0u);
                if (k.ref16[0] == targets[t] * 16u) break;
            }
            if (k.ref16[0] != targets[t] * 16u) {
                printf("filter stalls: target %u tp %u -> %u/16\n", targets[t], tp, k.ref16[0]);
                assert(0);
            }
        }
    }
    printf("reference low pass reaches every target exactly (tp 1..32, 7 targets)\n");
}

static void test_stop(void)
{
    hcknock_cfg_t c = base_cfg();
    hcknock_t k;
    unsigned int i;
    /* the reference is gone (a sensor that was open, now back, diagnosis
       off): every ignition is a knock and retard cannot cure it */
    c.diag_n = 0u;
    hcknock_reset(&k, &c);
    settle(&k, &c, 400u);
    k.ref16[3] = 0u;
    for (i = 0u; i < 400u; i++) {
        hcknock_in_t in = run_in(noise(M[3]));
        (void)hcknock_ignition(&k, &c, 3u, &in);
        if (i == (unsigned int)(c.max_q / c.step_q) + c.stop_n - 2u) assert(k.stop == 0u);
    }
    assert(k.stop == 8u && hcknock_retard(&k, &c, 3u) == c.max_q);
    /* borderline sustained knock at the ceiling, but interrupted by quiet
       ignitions: not "at stop" */
    hcknock_reset(&k, &c);
    settle(&k, &c, 4000u);
    for (i = 0u; i < 4000u; i++) {
        hcknock_in_t in = run_in(i % 150u ? M[0] * 4u : M[0]);
        (void)hcknock_ignition(&k, &c, 0u, &in);
    }
    assert(k.stop == 0u && k.ret_q[0] == c.max_q);
    printf("at stop: %u knocks in a row at the ceiling latch the cylinder; an interrupted run does not\n",
           c.stop_n);
}

static void test_inactive(void)
{
    hcknock_cfg_t c = base_cfg();
    hcknock_t k;
    hcknock_in_t in;
    unsigned int before;
    hcknock_reset(&k, &c);
    settle(&k, &c, 4000u);
    k.ret_q[0] = 20u;
    before = k.ref16[0];
    in = run_in(1000u); in.rpm = 399u;
    assert(hcknock_ignition(&k, &c, 0u, &in) == 0u && k.active == 0u);
    in = run_in(1000u); in.load = 24u;
    assert(hcknock_ignition(&k, &c, 0u, &in) == 0u && k.active == 0u);
    in = run_in(1000u); in.clt = 38;
    assert(hcknock_ignition(&k, &c, 0u, &in) == 0u && k.active == 0u);
    assert(k.ref16[0] == before && k.knocks == 0u);
    hcknock_tick(&k, &c, 20u * c.reapply_ms);
    assert(k.ret_q[0] == 0u);
    printf("inactive (rpm/load/clt below): no detection, no learning, retard still recovers\n");
}

static void test_learn_wait(void)
{
    hcknock_cfg_t c = base_cfg();
    hcknock_t k;
    unsigned int i;
    hcknock_reset(&k, &c);
    for (i = 0u; i < c.learn; i++) {
        hcknock_in_t in = run_in(1000u);          /* 5x REFINI: would be a knock */
        assert(hcknock_ignition(&k, &c, 0u, &in) == 0u);
    }
    {
        hcknock_in_t in = run_in(1000u);
        k.ref16[0] = 200u * 16u;
        assert(hcknock_ignition(&k, &c, 0u, &in) == 1u);
    }
    printf("settling: no detection for the first %u ignitions of a cylinder, then detection\n",
           c.learn);
}

static void test_dynamics(void)
{
    hcknock_cfg_t c = base_cfg();
    hcknock_t k;
    unsigned int i, det_dyn = 0u, det_static = 0u;
    /* noiseless: steady 100, then the background steps to 300 (load step).
       kef at 3000 rpm = 43/16 = 2.69: 3.0x is a knock statically, but not
       with the dynamics factor 1.125 x ... = 3.02 and the fast filter. */
    for (i = 0u; i < 2u; i++) {
        unsigned int n;
        hcknock_reset(&k, &c);
        for (n = 0u; n < 400u; n++) {
            hcknock_in_t in = run_in(100u);
            (void)hcknock_ignition(&k, &c, 0u, &in);
        }
        for (n = 0u; n < 40u; n++) {
            hcknock_in_t in = run_in(300u);
            in.dyn = (unsigned char)(i == 0u);
            if (i == 0u) det_dyn += hcknock_ignition(&k, &c, 0u, &in);
            else det_static += hcknock_ignition(&k, &c, 0u, &in);
        }
    }
    printf("dynamics: 3x background step -> %u knocks with dyn, %u without\n", det_dyn, det_static);
    assert(det_dyn == 0u && det_static > 0u);
}

static void test_sensor_diag(void)
{
    hcknock_cfg_t c = base_cfg();
    hcknock_t k;
    unsigned int i;
    c.cyls = 8u;
    hcknock_reset(&k, &c);
    for (i = 0u; i < 16000u; i++) {
        unsigned char cyl = (unsigned char)(i % 8u);
        hcknock_in_t in = run_in(cyl >= 4u ? rnd(3u) : noise(M[cyl]));   /* sensor 1 open */
        (void)hcknock_ignition(&k, &c, cyl, &in);
    }
    assert(k.fault == 2u && k.fault_hi == 0u);
    assert(hcknock_retard(&k, &c, 5u) >= c.safe_q);
    assert(hcknock_retard(&k, &c, 1u) == 0u);
    /* too loud (saturated) on sensor 0; below diag_rpm nothing is judged */
    hcknock_reset(&k, &c);
    for (i = 0u; i < 16000u; i++) {
        unsigned char cyl = (unsigned char)(i % 8u);
        hcknock_in_t in = run_in(cyl < 4u ? 1023u : noise(M[cyl]));
        in.rpm = 1500u;
        (void)hcknock_ignition(&k, &c, cyl, &in);
    }
    assert(k.fault == 0u);
    for (i = 0u; i < 16000u; i++) {
        unsigned char cyl = (unsigned char)(i % 8u);
        hcknock_in_t in = run_in(cyl < 4u ? 1023u : noise(M[cyl]));
        (void)hcknock_ignition(&k, &c, cyl, &in);
    }
    assert(k.fault == 1u && k.fault_hi == 1u);
    assert(hcknock_retard(&k, &c, 2u) == c.safe_q && hcknock_retard(&k, &c, 6u) == 0u);
    printf("sensor diagnosis: open sensor 1 -> safety retard on cylinders 5..8 only; "
           "saturated sensor 0 -> fault_hi; nothing judged below diag_rpm\n");
}

static void test_config(void)
{
    hcknock_cfg_t c = base_cfg(), b;
    assert(hcknock_check(&c) == 0u);
    b = c; b.cyls = 0u;          assert(hcknock_check(&b) == HCKNOCK_E_CYLS);
    b = c; b.cyls = 9u;          assert(hcknock_check(&b) == HCKNOCK_E_CYLS);
    b = c; b.sensor[3] = 4u;     assert(hcknock_check(&b) == HCKNOCK_E_SENSOR);
    b = c; b.sensor[5] = 4u;     assert(hcknock_check(&b) == 0u);     /* unused cylinder */
    b = c; b.tp = 0u;            assert(hcknock_check(&b) == HCKNOCK_E_TP);
    b = c; b.tp_dyn = 33u;       assert(hcknock_check(&b) == HCKNOCK_E_TP);
    b = c; b.kef16[2] = 15u;     assert(hcknock_check(&b) == HCKNOCK_E_KEF);
    b = c; b.kef_rpm[3] = 100u;  assert(hcknock_check(&b) == HCKNOCK_E_KEF);
    b = c; b.kef_dyn16 = 33u;    assert(hcknock_check(&b) == HCKNOCK_E_KEF);
    b = c; b.step_q = 0u;        assert(hcknock_check(&b) == HCKNOCK_E_RETARD);
    b = c; b.max_q = 8u;         assert(hcknock_check(&b) == HCKNOCK_E_RETARD);
    b = c; b.reapply_ms = 0u;    assert(hcknock_check(&b) == HCKNOCK_E_REAPPLY);
    b = c; b.ref_init = 1024u;   assert(hcknock_check(&b) == HCKNOCK_E_REF);
    b = c; b.ref_min = 901u;     assert(hcknock_check(&b) == HCKNOCK_E_REF);
    printf("config check: every bad field named\n");
}

static void test_bounds(void)
{
    hcknock_cfg_t c = base_cfg();
    hcknock_t k;
    hcknock_in_t in;
    unsigned int i;
    hcknock_reset(&k, &c);
    in = run_in(60000u);                              /* out-of-range sample */
    for (i = 0u; i < 5000u; i++) (void)hcknock_ignition(&k, &c, 0u, &in);
    assert(k.ref16[0] <= 16368u);
    k.ref16[0] = 0u; k.rem[0] = 0;
    (void)hcknock_ignition(&k, &c, 0u, &in);
    assert(k.level16[0] == 255u);
    in = run_in(1000u);
    memset(&k, 0x5A, sizeof k);
    hcknock_reset(&k, &c);
    {   /* reset leaves no stale byte behind: every field is initialised */
        unsigned char j;
        assert(k.stop == 0u && k.fault == 0u && k.fault_hi == 0u && k.knocks == 0u
               && k.at_max == 0u && k.active == 0u);
        for (j = 0u; j < HCKNOCK_CYL; j++)
            assert(k.maxrun[j] == 0u && k.ret_q[j] == 0u && k.seen[j] == 0u
                   && k.quiet_ms[j] == 0u && k.kcount[j] == 0u && k.rem[j] == 0
                   && k.level16[j] == 0u && k.ref16[j] == c.ref_init * 16u);
        for (j = 0u; j < HCKNOCK_SENS; j++) assert(k.bad[j] == 0u);
    }
    assert(hcknock_ignition(&k, &c, 4u, &in) == 0u);   /* cyl beyond cyls */
    assert(hcknock_ignition(&k, &c, 200u, &in) == 0u);
    assert(k.seen[4] == 0u && hcknock_retard(&k, &c, 200u) == 0u);
    hcknock_tick(&k, &c, 65535u);
    printf("bounds: saturated input, zero reference, foreign cylinder index - all contained\n");
}

int main(void)
{
    test_thr_exhaustive();
    test_config();
    test_quiet();
    test_single();
    test_sustained();
    test_exact_filter();
    test_stop();
    test_inactive();
    test_learn_wait();
    test_dynamics();
    test_sensor_diag();
    test_bounds();
    printf("hcknock: ALL PASS\n");
    return 0;
}
