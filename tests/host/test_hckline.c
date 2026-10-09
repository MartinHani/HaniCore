/*
 * test_hckline.c - host test for the KWP vehicle-mode core (hckline.c).
 *
 * Compiled and run by tools/test_hckline_host.py on gcc/clang. It models the
 * TESTER side against a virtual wire and asserts the ECU-side core behaves.
 *
 * It deliberately does NOT re-model the core's own arithmetic: it drives real
 * inputs and checks real outputs (bytes on the wire, state, counters), so it
 * cannot pass vacuously by sharing an assumption with the implementation.
 */
#include <assert.h>
#include <stdio.h>
#include <string.h>

#include "hckline.h"

/* -------- a deterministic RNG so failures reproduce exactly -------- */
static unsigned long g_rng = 0x12345678uL;
static unsigned int rnd(unsigned int n)
{
    g_rng = g_rng * 1103515245uL + 12345uL;
    return (unsigned int)((g_rng >> 16) % (n ? n : 1u));
}

/* -------- virtual wire helpers -------- */
static unsigned char cksum(const unsigned char *p, unsigned int n)
{
    unsigned int i; unsigned char c = 0u;
    for (i = 0u; i < n; i++) c = (unsigned char)(c + p[i]);
    return c;
}

/* Drain everything the ECU has queued into out[], return the count. */
static unsigned int drain(hckline_t *k, unsigned char *out, unsigned int max)
{
    unsigned int n = 0u; unsigned char b;
    while (n < max && hckline_tx_pop(k, &b)) out[n++] = b;
    return n;
}

/* Send a KWP request to the ECU addressed to ecu_addr from tester_addr. */
static void send_kwp(hckline_t *k, unsigned long *t,
                     const unsigned char *data, unsigned char n)
{
    unsigned char f[64]; unsigned int i, idx = 0u;
    f[idx++] = (unsigned char)(0x80u | n);
    f[idx++] = k->cfg.ecu_addr;
    f[idx++] = k->cfg.tester_addr;
    for (i = 0u; i < n; i++) f[idx++] = data[i];
    f[idx] = cksum(f, idx); idx++;
    for (i = 0u; i < idx; i++) { hckline_on_rx(k, f[i], *t); *t += 200u; }
}

/* Advance time and tick repeatedly so every scheduled emission fires. */
static void run_us(hckline_t *k, unsigned long *t, unsigned long us)
{
    unsigned long end = *t + us;
    while (*t < end) { hckline_tick(k, *t); *t += 500u; }
    hckline_tick(k, *t);
}

/* Collect emitted bytes in order while the handshake runs to COMPL. The W2/W3
   gaps are short, so a single coarse run_us can emit more than one byte before
   we look: gather them all rather than assuming one-per-step. */
static int collect_to_compl(hckline_t *k, unsigned long *t,
                            unsigned char *seq, unsigned int *seq_n)
{
    unsigned long guard = 0u;
    unsigned char b;
    *seq_n = 0u;
    while (k->state != HCKLINE_ST_COMPL && guard < 400000uL) {
        hckline_tick(k, *t);
        while (hckline_tx_pop(k, &b)) {
            if (*seq_n < 8u) seq[(*seq_n)++] = b;
        }
        *t += 500u; guard += 500u;
    }
    return (k->state == HCKLINE_ST_COMPL);
}

/* Drive a full, valid 5-baud + complement handshake to SESSION. Returns 1 on
   success. jitter_us perturbs the tester complement timing inside W4. */
static int do_init(hckline_t *k, unsigned long *t, long jitter_us)
{
    unsigned char seq[8]; unsigned int n = 0u; unsigned char out[8];

    hckline_on_slow_init(k, k->cfg.addr, *t);
    if (!collect_to_compl(k, t, seq, &n)) return 0;
    if (n != 3u) return 0;
    if (seq[0] != k->cfg.sync || seq[1] != k->cfg.kb1 || seq[2] != k->cfg.kb2)
        return 0;

    /* tester complement of KB2, possibly jittered inside the W4 window */
    if (jitter_us > 0) run_us(k, t, (unsigned long)jitter_us);
    hckline_on_rx(k, (unsigned char)(~k->cfg.kb2), *t);
    hckline_tick(k, *t);
    if (drain(k, out, sizeof(out)) != 1u || out[0] != (unsigned char)(~k->cfg.addr))
        return 0;

    return (k->state == HCKLINE_ST_SESSION);
}

/* ============================ the tests ============================ */

static void test_exact_init(void)
{
    hckline_cfg_t cfg; hckline_t k; unsigned long t = 1000u;
    hckline_default_cfg(&cfg); hckline_init(&k, &cfg);
    assert(do_init(&k, &t, 0));
    assert(k.init_ok == 1u && k.init_fail == 0u);
    printf("  exact 0x01 init -> 55 EF 8F / 70 -> FE / SESSION: OK\n");
}

static void test_wrong_address(void)
{
    hckline_cfg_t cfg; hckline_t k; unsigned long t = 1000u; unsigned char o[8];
    hckline_default_cfg(&cfg); hckline_init(&k, &cfg);
    hckline_on_slow_init(&k, 0x11u, t);   /* not our address */
    run_us(&k, &t, cfg.w1_us + 5000u);
    assert(drain(&k, o, sizeof(o)) == 0u);
    assert(k.state == HCKLINE_ST_IDLE && k.wrong_addr == 1u);
    printf("  wrong 5-baud address (0x11) ignored, no sync emitted: OK\n");
}

static void test_wrong_complement(void)
{
    hckline_cfg_t cfg; hckline_t k; unsigned long t = 1000u; unsigned char o[8];
    hckline_default_cfg(&cfg); hckline_init(&k, &cfg);
    hckline_on_slow_init(&k, cfg.addr, t);
    run_us(&k, &t, cfg.w1_us + cfg.w2_us + cfg.w3_us + 6000u);
    drain(&k, o, sizeof(o));            /* 55 EF 8F */
    assert(k.state == HCKLINE_ST_COMPL);
    hckline_on_rx(&k, 0x00u, t);        /* wrong complement */
    hckline_tick(&k, t);
    /* one retry: back to SYNC */
    assert(k.state == HCKLINE_ST_SYNC && k.retry_used == 1u);
    /* second failure -> idle */
    run_us(&k, &t, cfg.w1_us + cfg.w2_us + cfg.w3_us + 6000u);
    drain(&k, o, sizeof(o));
    hckline_on_rx(&k, 0x00u, t);
    hckline_tick(&k, t);
    assert(k.state == HCKLINE_ST_IDLE && k.init_fail == 1u && k.init_ok == 0u);
    printf("  wrong complement -> one retry -> idle, init_fail=1: OK\n");
}

static void test_missing_complement(void)
{
    hckline_cfg_t cfg; hckline_t k; unsigned long t = 1000u; unsigned char o[8];
    hckline_default_cfg(&cfg); hckline_init(&k, &cfg);
    hckline_on_slow_init(&k, cfg.addr, t);
    run_us(&k, &t, cfg.w1_us + cfg.w2_us + cfg.w3_us + 6000u);
    drain(&k, o, sizeof(o));
    assert(k.state == HCKLINE_ST_COMPL);
    run_us(&k, &t, cfg.w4_us + 2000u);          /* let W4 expire */
    assert(k.state == HCKLINE_ST_SYNC);          /* retry */
    run_us(&k, &t, cfg.w1_us + cfg.w2_us + cfg.w3_us + cfg.w4_us + 10000u);
    assert(k.state == HCKLINE_ST_IDLE && k.init_fail == 1u);
    printf("  missing complement -> retry -> W4 timeout -> idle: OK\n");
}

static void test_tester_present_and_diag(void)
{
    hckline_cfg_t cfg; hckline_t k; unsigned long t = 1000u; unsigned char o[16]; unsigned int n;
    unsigned char tp[1]; unsigned char sd[2];
    hckline_default_cfg(&cfg); hckline_init(&k, &cfg);
    assert(do_init(&k, &t, 0));

    tp[0] = HCKLINE_SID_TESTER_PRES;
    send_kwp(&k, &t, tp, 1u); hckline_tick(&k, t);
    n = drain(&k, o, sizeof(o));
    assert(n >= 4u && o[3] == (unsigned char)(HCKLINE_SID_TESTER_PRES + 0x40u));

    sd[0] = HCKLINE_SID_START_DIAG; sd[1] = 0x89u;
    send_kwp(&k, &t, sd, 2u); hckline_tick(&k, t);
    n = drain(&k, o, sizeof(o));
    assert(n >= 5u && o[3] == (unsigned char)(HCKLINE_SID_START_DIAG + 0x40u) && o[4] == 0x89u);
    assert(k.frames_ok == 2u && k.frames_bad == 0u);
    printf("  TesterPresent + StartDiagnosticSession answered: OK\n");
}

static void test_identity_gate(void)
{
    hckline_cfg_t cfg; hckline_t k; unsigned long t = 1000u; unsigned char o[48]; unsigned int n;
    unsigned char gf[2]; unsigned char id[3];
    hckline_default_cfg(&cfg); hckline_init(&k, &cfg);
    assert(do_init(&k, &t, 0));

    /* GOFAST before identity -> NAK conditionsNotCorrect, no baud pending */
    gf[0] = HCKLINE_SID_GOFAST; gf[1] = HCKLINE_BAUD_124800;
    send_kwp(&k, &t, gf, 2u); hckline_tick(&k, t);
    n = drain(&k, o, sizeof(o));
    assert(n >= 6u && o[3] == HCKLINE_SID_NEG && o[4] == HCKLINE_SID_GOFAST
           && o[5] == HCKLINE_NRC_COND_WRONG);
    assert(k.baud_pending == 0u);

    /* IDENTIFY without the "HC" magic -> format NAK, gate stays shut */
    id[0] = HCKLINE_SID_IDENTIFY; id[1] = 'X'; id[2] = 'Y';
    send_kwp(&k, &t, id, 3u); hckline_tick(&k, t);
    n = drain(&k, o, sizeof(o));
    assert(o[3] == HCKLINE_SID_NEG && o[5] == HCKLINE_NRC_FMT);
    assert(k.identified == 0u);

    /* proper IDENTIFY -> positive 0xF0 + "HANICORE", gate opens */
    id[0] = HCKLINE_SID_IDENTIFY; id[1] = 'H'; id[2] = 'C';
    send_kwp(&k, &t, id, 3u); hckline_tick(&k, t);
    n = drain(&k, o, sizeof(o));
    assert(n >= 12u && o[3] == (unsigned char)(HCKLINE_SID_IDENTIFY + 0x40u));
    assert(o[4] == 'H' && o[5] == 'A' && o[6] == 'N' && o[7] == 'I');
    assert(k.identified == 1u);
    printf("  identity gate: GOFAST refused until IDENTIFY 'HC' succeeds: OK\n");
}

static void test_private_transition(void)
{
    hckline_cfg_t cfg; hckline_t k; unsigned long t = 1000u; unsigned char o[48]; unsigned int n;
    unsigned char id[3]; unsigned char gf[2]; unsigned char code;
    hckline_default_cfg(&cfg); hckline_init(&k, &cfg);
    assert(do_init(&k, &t, 0));

    id[0] = HCKLINE_SID_IDENTIFY; id[1] = 'H'; id[2] = 'C';
    send_kwp(&k, &t, id, 3u); hckline_tick(&k, t);
    drain(&k, o, sizeof(o));

    gf[0] = HCKLINE_SID_GOFAST; gf[1] = HCKLINE_BAUD_124800;
    send_kwp(&k, &t, gf, 2u); hckline_tick(&k, t);

    /* Before draining the response, the baud switch must NOT be reported. */
    assert(k.baud_pending == 1u);
    assert(hckline_take_baud(&k, &code) == 0u);   /* FIFO still busy */

    n = drain(&k, o, sizeof(o));
    assert(n >= 6u && o[3] == (unsigned char)(HCKLINE_SID_GOFAST + 0x40u)
           && o[4] == HCKLINE_BAUD_124800);

    /* Now the FIFO is empty: the switch is due exactly once. */
    assert(hckline_take_baud(&k, &code) == 1u && code == HCKLINE_BAUD_124800);
    assert(hckline_take_baud(&k, &code) == 0u);

    hckline_enter_private(&k);
    assert(k.state == HCKLINE_ST_PRIVATE);

    /* In private mode the core is dormant: ticks emit nothing. */
    run_us(&k, &t, 1000000uL);
    assert(drain(&k, o, sizeof(o)) == 0u);
    printf("  private transition: F1 03 at old baud, switch only after drain: OK\n");
}

/* V96: GOFAST 115200 (code 0x04) - TunerStudio's own fast rate. */
static void test_gofast_115200(void)
{
    hckline_cfg_t cfg; hckline_t k; unsigned long t = 1000u; unsigned char o[48];
    unsigned char id[3]; unsigned char gf[2]; unsigned char code; unsigned int n;
    hckline_default_cfg(&cfg); hckline_init(&k, &cfg);
    assert(do_init(&k, &t, 0));
    id[0] = HCKLINE_SID_IDENTIFY; id[1] = 'H'; id[2] = 'C';
    send_kwp(&k, &t, id, 3u); hckline_tick(&k, t);
    drain(&k, o, sizeof(o));
    gf[0] = HCKLINE_SID_GOFAST; gf[1] = 0x05u;
    send_kwp(&k, &t, gf, 2u); hckline_tick(&k, t);
    n = drain(&k, o, sizeof(o));
    assert(n >= 6u && o[3] == HCKLINE_SID_NEG && o[5] == HCKLINE_NRC_SUBF_NOT_SUP);
    gf[1] = HCKLINE_BAUD_115200;
    send_kwp(&k, &t, gf, 2u); hckline_tick(&k, t);
    n = drain(&k, o, sizeof(o));
    assert(n >= 6u && o[4] == HCKLINE_BAUD_115200);
    assert(hckline_take_baud(&k, &code) == 1u && code == HCKLINE_BAUD_115200);
    printf("  GOFAST 115200 accepted, 0x05 refused: OK\n");
}

static void test_bad_frames(void)
{
    hckline_cfg_t cfg; hckline_t k; unsigned long t = 1000u; unsigned char o[16];
    unsigned int bad0;
    hckline_default_cfg(&cfg); hckline_init(&k, &cfg);
    assert(do_init(&k, &t, 0));
    bad0 = k.frames_bad;

    /* bad checksum */
    {
        unsigned char f[6]; unsigned int i;
        f[0] = 0x82u; f[1] = cfg.ecu_addr; f[2] = cfg.tester_addr;
        f[3] = HCKLINE_SID_TESTER_PRES; f[4] = 0x00u; /* payload */
        f[5] = 0xFFu; /* wrong checksum */
        for (i = 0u; i < 6u; i++) hckline_on_rx(&k, f[i], t);
        hckline_tick(&k, t);
        assert(drain(&k, o, sizeof(o)) == 0u);   /* no reply to a bad cksum */
        assert(k.frames_bad == bad0 + 1u);
    }
    /* functional/broadcast format byte (bit6) -> refused, no action */
    {
        unsigned char f[5]; unsigned int i;
        f[0] = 0xC1u; f[1] = cfg.ecu_addr; f[2] = cfg.tester_addr;
        f[3] = HCKLINE_SID_TESTER_PRES; f[4] = cksum(f,4u);
        for (i = 0u; i < 5u; i++) hckline_on_rx(&k, f[i], t);
        hckline_tick(&k, t);
        assert(drain(&k, o, sizeof(o)) == 0u);
    }
    /* wrong target address -> ignored */
    {
        unsigned char f[5]; unsigned int i;
        f[0] = 0x81u; f[1] = 0x77u; f[2] = cfg.tester_addr;
        f[3] = HCKLINE_SID_TESTER_PRES; f[4] = cksum(f,4u);
        for (i = 0u; i < 5u; i++) hckline_on_rx(&k, f[i], t);
        hckline_tick(&k, t);
        assert(drain(&k, o, sizeof(o)) == 0u);
    }
    printf("  bad checksum / functional / wrong-target frames refused: OK\n");
}

/* V95: a tester that abandons the session and talks at another rate. Before
   V95 every byte refreshed P3 and the session never ended while the host kept
   retrying (bench, V94). Now: garbage never refreshes P3, and three separate
   bad bursts end the session; one corrupted frame costs nothing. */
static void garbage_burst(hckline_t *k, unsigned long *t)
{
    static const unsigned char g[] = { 0x18u, 0x20u, 0xFEu, 0x66u, 0x06u,
                                       0x00u, 0x9Eu, 0x60u };
    unsigned int i;
    for (i = 0u; i < sizeof(g); i++) { hckline_on_rx(k, g[i], *t); *t += 180u; }
    hckline_tick(k, *t);
}

static void test_abandoned_session(void)
{
    hckline_cfg_t cfg; hckline_t k; unsigned long t = 1000u; unsigned char o[16];
    unsigned char tp[1];
    unsigned int n;
    hckline_default_cfg(&cfg); hckline_init(&k, &cfg);
    assert(do_init(&k, &t, 0));
    /* one corrupted burst in a healthy session: still open, still answers */
    garbage_burst(&k, &t);
    assert(k.state == HCKLINE_ST_SESSION && k.bad_run == 1u);
    run_us(&k, &t, 100000u);        /* quiet longer than HCKLINE_STALE_US */
    tp[0] = HCKLINE_SID_TESTER_PRES;
    send_kwp(&k, &t, tp, 1u); hckline_tick(&k, t);
    n = drain(&k, o, sizeof(o));
    assert(n >= 5u && o[3] == 0x7Eu && k.bad_run == 0u);
    /* three bursts a TunerStudio retry apart: the session ends, well inside P3 */
    garbage_burst(&k, &t); run_us(&k, &t, 300000u);
    assert(k.state == HCKLINE_ST_SESSION);
    garbage_burst(&k, &t); run_us(&k, &t, 300000u);
    assert(k.state == HCKLINE_ST_SESSION);
    garbage_burst(&k, &t);
    assert(k.state == HCKLINE_ST_IDLE && k.sess_drops == 1u && k.identified == 0u);
    printf("  abandoned session: 3 bad bursts -> idle, 1 burst tolerated: OK\n");

    /* garbage never refreshes P3: a session fed one malformed byte a second
       (each its own burst) is gone within P3 of its last VALID frame */
    hckline_init(&k, &cfg); t = 1000u;
    assert(do_init(&k, &t, 0));
    send_kwp(&k, &t, tp, 1u); hckline_tick(&k, t); (void)drain(&k, o, sizeof(o));
    {
        unsigned long start = t; int i;
        for (i = 0; i < 12 && k.state == HCKLINE_ST_SESSION; i++) {
            hckline_on_rx(&k, 0x3Fu, t);        /* not addressed: malformed */
            run_us(&k, &t, 1000000uL);
        }
        assert(k.state == HCKLINE_ST_IDLE);
        assert(t - start <= cfg.p3_us + 1000000uL);
    }
    printf("  garbage never keeps a session alive past P3: OK\n");
}

static void test_unknown_service(void)
{
    hckline_cfg_t cfg; hckline_t k; unsigned long t = 1000u; unsigned char o[16]; unsigned int n;
    unsigned char req[1];
    hckline_default_cfg(&cfg); hckline_init(&k, &cfg);
    assert(do_init(&k, &t, 0));
    req[0] = 0x22u;   /* readDataByLocalId: not supported here */
    send_kwp(&k, &t, req, 1u); hckline_tick(&k, t);
    n = drain(&k, o, sizeof(o));
    assert(n >= 6u && o[3] == HCKLINE_SID_NEG && o[4] == 0x22u
           && o[5] == HCKLINE_NRC_SVC_NOT_SUPP);
    printf("  unsupported service -> 7F <sid> 11: OK\n");
}

static void test_session_timeout(void)
{
    hckline_cfg_t cfg; hckline_t k; unsigned long t = 1000u;
    hckline_default_cfg(&cfg); cfg.p3_us = 100000uL; hckline_init(&k, &cfg);
    assert(do_init(&k, &t, 0));
    assert(k.state == HCKLINE_ST_SESSION);
    run_us(&k, &t, cfg.p3_us + 5000u);
    assert(k.state == HCKLINE_ST_IDLE && k.identified == 0u);
    printf("  P3 session inactivity -> idle: OK\n");
}

static void test_no_unsolicited(void)
{
    hckline_cfg_t cfg; hckline_t k; unsigned long t = 1000u; unsigned char o[8];
    int i;
    hckline_default_cfg(&cfg); hckline_init(&k, &cfg);
    /* In IDLE, ticking forever must never put a byte on the wire. */
    for (i = 0; i < 100000; i++) { hckline_tick(&k, t); t += 137u; }
    assert(drain(&k, o, sizeof(o)) == 0u);
    printf("  no unsolicited transmit in IDLE over 100000 ticks: OK\n");
}

/* Randomised init timing: valid handshakes with jitter inside W4, plus
   complement bytes that are sometimes wrong, over many cases. */
static void test_random_init(int cases)
{
    int i, ok = 0, failed = 0;
    for (i = 0; i < cases; i++) {
        hckline_cfg_t cfg; hckline_t k; unsigned long t;
        long jit;
        int good;
        hckline_default_cfg(&cfg);
        /* randomise timings within sane bounds to prove the machine is not
           tied to specific constants */
        cfg.w1_us = 20000uL + rnd(80000u);
        cfg.w2_us = 1000uL + rnd(19000u);
        cfg.w3_us = rnd(20000u);
        cfg.w4_us = 25000uL + rnd(25000u);
        hckline_init(&k, &cfg);
        t = 1000u + rnd(1000000u);

        good = (rnd(4u) != 0u);                 /* 75% good complement timing */
        jit = good ? (long)rnd((unsigned int)(cfg.w4_us / 2u))
                   : (long)(cfg.w4_us + 5000uL);/* too late */

        if (good) {
            if (do_init(&k, &t, jit)) { ok++; }
            else { failed++; }
            assert(k.init_ok <= 1u);
        } else {
            /* let the handshake reach COMPL then miss the window entirely */
            unsigned char o[8];
            hckline_on_slow_init(&k, cfg.addr, t);
            run_us(&k, &t, cfg.w1_us + cfg.w2_us + cfg.w3_us + 8000u);
            drain(&k, o, sizeof(o));
            run_us(&k, &t, 2u * (cfg.w1_us + cfg.w2_us + cfg.w3_us + cfg.w4_us) + 20000u);
            assert(k.state == HCKLINE_ST_IDLE);
            assert(k.init_ok == 0u);
        }
        /* invariant: the core is always in a legal state */
        assert(k.state <= HCKLINE_ST_PRIVATE);
    }
    printf("  randomised init: %d cases, %d good-timed reached SESSION, %d edge: OK\n",
           cases, ok, failed);
}

/* Fuzz: random bytes at random times into every entry point. The only
   invariants are structural - never crash, never leave a legal state, and
   never emit a byte while IDLE. */
static void test_fuzz(int iters)
{
    hckline_cfg_t cfg; hckline_t k; unsigned long t = 1000u;
    int i; unsigned char o[HCKLINE_TX_MAX];
    hckline_default_cfg(&cfg); hckline_init(&k, &cfg);
    for (i = 0; i < iters; i++) {
        unsigned int action = rnd(10u);
        if (action == 0u) {
            hckline_on_slow_init(&k, (unsigned char)rnd(256u), t);
        } else if (action <= 6u) {
            hckline_on_rx(&k, (unsigned char)rnd(256u), t);
        } else if (action <= 8u) {
            /* A byte may only appear in the FIFO as a consequence of an input
               event (a 5-baud address or a received frame), never from a tick
               alone. Prove that: a tick on an idle machine that has nothing
               queued must not create output. */
            unsigned char was_busy = hckline_tx_busy(&k);
            unsigned char st_before = k.state;
            hckline_tick(&k, t);
            if (st_before == HCKLINE_ST_IDLE && !was_busy) {
                assert(!hckline_tx_busy(&k));    /* tick never speaks first */
            }
        } else {
            (void)drain(&k, o, sizeof(o));
        }
        t += 1u + rnd(80000u);
        assert(k.state <= HCKLINE_ST_PRIVATE);
        assert(k.rx_len <= HCKLINE_RX_MAX);
    }
    printf("  fuzz: %d randomised events, invariants held: OK\n", iters);
}

int main(void)
{
    printf("hckline host tests\n");
    test_exact_init();
    test_wrong_address();
    test_wrong_complement();
    test_missing_complement();
    test_tester_present_and_diag();
    test_identity_gate();
    test_private_transition();
    test_gofast_115200();
    test_bad_frames();
    test_unknown_service();
    test_session_timeout();
    test_abandoned_session();
    test_no_unsolicited();
    test_random_init(20000);
    test_fuzz(200000);
    printf("PASS: all hckline host tests\n");
    return 0;
}
