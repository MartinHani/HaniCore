/*
 * test_hcme75mon.c - host test for the ME7.5 DC monitor core
 * (hcme75mon.c), gcc -std=c89. Run by tests/host/test_hcme75mon_host.py.
 *
 * A MONITOR model sends a question (a LOW pulse) 2 ms into every ECU RX
 * slot (or, with `early`, 3000 ticks after our answer ended, inside the TX
 * slot); the test records every pulse the core starts and checks timing,
 * the two-deep answer pipeline and the band table. Time is a 16-bit tick
 * counter that starts near its wrap.
 */
#include <assert.h>
#include <stdio.h>
#include "hcme75mon.h"

#define STEP 150u                     /* 0.1 ms per poll                    */
#define MAXP 64u

static unsigned int pulse_t[MAXP], pulse_w[MAXP];
static unsigned int npulse;

/* band mid widths, from the published edges */
static unsigned int mid(unsigned char q)
{
    static const unsigned int lo[16] = {
        0x1872u, 0x19EBu, 0x1B6Eu, 0x1D06u, 0x1EAFu, 0x2067u, 0x2234u, 0x2410u,
        0x2601u, 0x2806u, 0x2A1Eu, 0x2C4Fu, 0x2E97u, 0x30F8u, 0x336Du, 0x3601u
    };
    unsigned int hi = (q < 15u) ? lo[q + 1u] : 0x38AEu;
    return (unsigned int)(lo[q] + (hi - lo[q]) / 2u);
}

/* run from `start` for `ticks`; questions[k] is sent in RX slot k
   (0xFFFF = no question) */
static unsigned int run(hcme75mon_t *m, unsigned int start, unsigned long ticks,
                        const unsigned int *questions, unsigned int nq,
                        unsigned char early)
{
    unsigned long el;
    unsigned int now = start, w, k = 0u;
    unsigned char was_rx = 0u, sent_q = 1u;
    unsigned int rx_t0 = 0u;
    npulse = 0u;
    for (el = 0uL; el < ticks; el += STEP) {
        now = (unsigned int)((start + el) & 0xFFFFuL);   /* a 16-bit timer */
        if (hcme75mon_poll(m, now, &w)) {
            assert(npulse < MAXP);
            pulse_t[npulse] = now; pulse_w[npulse] = w; npulse++;
            /* our own pulse is seen on the shared line: must be ignored */
            hcme75mon_edge(m, 0u, now);
            hcme75mon_edge(m, 1u, (unsigned int)((now + w) & 0xFFFFu));
            if (early) {             /* the target releases the line here */
                hcme75mon_listen(m);
                rx_t0 = (unsigned int)((now + w) & 0xFFFFu);
                sent_q = 0u;
            }
        }
        if (!early && m->phase == HCME75MON_PH_RX && !was_rx) { rx_t0 = now; sent_q = 0u; }
        if (m->phase == HCME75MON_PH_TX && was_rx) k++;
        was_rx = (unsigned char)(m->phase == HCME75MON_PH_RX);
        if (!sent_q && ((now - rx_t0) & 0x8000u) == 0u
            && ((now - rx_t0) & 0xFFFFu) >= 3000u) {
            sent_q = 1u;
            if (k < nq && questions[k] != 0xFFFFu) {
                hcme75mon_edge(m, 0u, now);
                hcme75mon_edge(m, 1u, (unsigned int)((now + questions[k]) & 0xFFFFu));
            }
        }
    }
    return now;
}

static void test_bands(void)
{
    unsigned char q;
    for (q = 0u; q < 16u; q++) assert(hcme75mon_band(mid(q)) == q);
    assert(hcme75mon_band(0x1871u) == HCME75MON_BAND_NONE);
    assert(hcme75mon_band(0x1872u) == 0u);
    assert(hcme75mon_band(0x19EAu) == 0u && hcme75mon_band(0x19EBu) == 1u);
    assert(hcme75mon_band(0x38ADu) == 15u);
    assert(hcme75mon_band(0x38AEu) == HCME75MON_BAND_NONE);
    assert(hcme75mon_response(8u) == HCME75MON_ASYNC);   /* RESPONSE[9]    */
    printf("  16 bands + window edges exact; RESPONSE[9] is the async width: OK\n");
}

static void test_startup_silence(void)
{
    hcme75mon_t m;
    unsigned int start = 0xFF00u;
    unsigned long silence = 2uL * HCME75MON_FRAME + HCME75MON_START_REM;
    hcme75mon_init(&m, start);
    run(&m, start, silence - STEP, 0, 0u, 0u);
    assert(npulse == 0u);
    hcme75mon_init(&m, start);
    run(&m, start, silence + STEP, 0, 0u, 0u);
    assert(npulse == 1u && pulse_w[0] == HCME75MON_ASYNC);
    /* the bench's monitor resets after ~90 ms without a first answer */
    assert(silence < 90uL * 1500uL);
    printf("  startup: silent for 2 x 20 ms + 16 ms, then ASync1: OK\n");
}

static void test_pipeline(unsigned char early)
{
    /* questions in RX slots 0..5 */
    static const unsigned int qs[6] = { 0, 0, 0xFFFFu, 0x1000u, 0, 0 };
    unsigned int qw[6];
    unsigned char qb[6] = { 0u, 13u, 0u, 0u, 5u, 15u };
    hcme75mon_t m;
    unsigned int start = 0xF000u, i, first;
    unsigned long silence = 2uL * HCME75MON_FRAME + HCME75MON_START_REM;
    for (i = 0u; i < 6u; i++) qw[i] = qs[i] ? qs[i] : mid(qb[i]);
    hcme75mon_init(&m, start);
    run(&m, start, silence + 15uL * HCME75MON_FRAME, qw, 6u, early);
    /* TX slots are 2 frames apart */
    for (i = 1u; i < npulse; i++)
        assert(((pulse_t[i] - pulse_t[i - 1u]) & 0xFFFFu) <= 2u * HCME75MON_FRAME + STEP &&
               ((pulse_t[i] - pulse_t[i - 1u]) & 0xFFFFu) >= 2u * HCME75MON_FRAME - STEP);
    first = 0u;
    /* TX0 ASync1, TX1 ASync2; TX(k+2) answers frame k */
    assert(pulse_w[first] == HCME75MON_ASYNC && pulse_w[first + 1u] == HCME75MON_ASYNC2);
    assert(pulse_w[first + 2u] == hcme75mon_response(0u));
    assert(pulse_w[first + 3u] == hcme75mon_response(13u));
    assert(pulse_w[first + 4u] == HCME75MON_INVALID);     /* frame 2 silent  */
    assert(pulse_w[first + 5u] == HCME75MON_INVALID);     /* frame 3 invalid */
    assert(pulse_w[first + 6u] == hcme75mon_response(5u));
    assert(pulse_w[first + 7u] == hcme75mon_response(15u));
    assert(m.invalid == 1u && m.timeouts >= 1u && m.answers >= 4u);
    printf("  %s: answers two TX slots after the question; silent/invalid -> "
           "the invalid width; own pulse ignored; 16-bit wrap: OK\n",
           early ? "question right after our pulse" : "question in the RX slot");
}

int main(void)
{
    printf("hcme75mon host tests\n");
    test_bands();
    test_startup_silence();
    test_pipeline(0u);
    test_pipeline(1u);
    printf("all hcme75mon tests passed\n");
    return 0;
}
