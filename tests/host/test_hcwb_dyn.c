/*
 * test_hcwb_dyn.c - V99: the lambda SIGNAL PATH and the LSU dynamics check
 * (firmware/sensors/hcwb.c), gcc -std=c89. Run by tools/test_hcwb_host.py.
 *
 * THE CAR (2026-10-02, V98r2 on the AWT): lambda 1 read ~1.04 almost
 * continuously while the VE was changed by up to 3x. This proves, on the
 * real conversion and the real dynamics core:
 *   P1 a deliberately large raw (UA) change propagates to lambda - rich,
 *      stoichiometric and lean read as such, monotonic, nothing pinned at
 *      ~1.04 (the conversion is not the fault);
 *   P2 ~1.04 is what a pump current of ~+70 uA reads - 7 counts above the
 *      calibrated zero, i.e. NO pump current: the signature of a sensor that
 *      is not pumping or a UA read from the other bank's (idle) chip;
 *   D1 a READY bank whose UA moves >= 12 counts in 5 s becomes ALIVE;
 *   D2 a READY bank frozen within 3 counts for 30 s of a running engine is
 *      STUCK (its lambda withdrawn), and recovers when the signal moves;
 *   D3 a frozen bank with the engine NOT running is never declared stuck;
 *   D4 losing validity resets everything (no stale ALIVE).
 */
#include <assert.h>
#include <stdio.h>
#include "hcwb.h"

static unsigned int ua_for(unsigned int ua0_raw, int counts)
{
    return (unsigned int)((int)ua0_raw + counts);
}

int main(void)
{
    hcwb_dyn_t d;
    unsigned int ms, l_rich, l_zero, l_lean, l_70, prev;
    int c;
    unsigned char st;

    /* P1: the raw -> lambda conversion over the whole swing, monotonic */
    l_rich = hcwb_lambda_raw(ua_for(307u, -100));   /* UA 1.01 V */
    l_zero = hcwb_lambda_raw(307u);                 /* UA 1.50 V */
    l_lean = hcwb_lambda_raw(ua_for(307u, +60));    /* UA 1.79 V */
    printf("P1 lambda rich %u stoich %u lean %u (x1000)\n", l_rich, l_zero,
           l_lean);
    assert(l_rich < 850u);
    assert(l_zero > 990u && l_zero < 1030u);
    assert(l_lean > 1250u);
    prev = 0u;
    for (c = -120; c <= 80; c += 4) {
        unsigned int l = hcwb_lambda_raw(ua_for(307u, c));
        assert(l >= prev);                          /* monotonic, never stuck */
        prev = l;
    }
    /* P2: ~1.04 is +7 counts = ~+70 uA = essentially no pump current */
    l_70 = hcwb_lambda_raw(ua_for(307u, 7));
    printf("P2 +7 counts above the zero reads lambda %u (x1000)\n", l_70);
    assert(l_70 >= 1030u && l_70 <= 1055u);

    /* D1: ALIVE after a window with a real swing */
    d.on = 0u;
    (void)hcwb_dyn_step(&d, 0u, 0u, 0u, 0u);        /* not valid: reset */
    for (ms = 0u; ms <= 5000u; ms += 10u) {
        st = hcwb_dyn_step(&d, 1u, (unsigned int)(300u + (ms / 250u) % 20u),
                           1u, ms);
        assert(st == 0u);
    }
    assert(d.alive == 1u && d.stuck == 0u);
    printf("D1 ALIVE after a 5 s window spanning %u counts\n", d.span);

    /* D2: frozen within +-1 count for 30 s running -> STUCK */
    for (ms = 5010u; ms <= 40000u; ms += 10u) {
        st = hcwb_dyn_step(&d, 1u, (unsigned int)(307u + (ms / 10u) % 2u),
                           1u, ms);
    }
    assert(st == 1u && d.stuck == 1u);
    printf("D2 STUCK after %u frozen windows (span %u)\n", d.frozen, d.span);
    /* ... and recovers on movement */
    for (ms = 40010u; ms <= 45100u; ms += 10u) {
        st = hcwb_dyn_step(&d, 1u, (unsigned int)(280u + (ms / 100u) % 40u),
                           1u, ms);
    }
    assert(st == 0u && d.stuck == 0u);
    printf("D2 recovered (span %u)\n", d.span);

    /* D3: frozen but the engine stopped: never stuck */
    (void)hcwb_dyn_step(&d, 0u, 0u, 0u, 0u);
    for (ms = 0u; ms <= 60000u; ms += 10u) {
        st = hcwb_dyn_step(&d, 1u, 307u, 0u, ms);
        assert(st == 0u);
    }
    printf("D3 frozen with the engine stopped: not stuck\n");

    /* D4: validity lost resets */
    d.alive = 1u;
    (void)hcwb_dyn_step(&d, 0u, 0u, 1u, 100u);
    assert(d.alive == 0u && d.stuck == 0u && d.on == 0u);
    printf("PASS: hcwb lambda signal path + dynamics\n");
    return 0;
}
