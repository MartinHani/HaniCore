/* Host test of firmware/diagnostics/hccel.c - the lamp policy, at the boundaries. */
#include <assert.h>
#include <stdio.h>
#include "hccel.h"

static unsigned char at(hccel_t *c, unsigned int t, unsigned char mil)
{
    return hccel_step(c, t, 1u, mil);
}

int main(void)
{
    hccel_t c;
    unsigned int t;

    /* 1. no DTC: 0-3 s ON, 3-4 s OFF, then OFF */
    hccel_reset(&c);
    for (t = 0u; t < 3000u; t += 10u) assert(at(&c, 1000u + t, 0u) == 1u);
    assert(c.mode == HCCEL_TEST_ON);
    assert(at(&c, 1000u + 2999u, 0u) == 1u);
    assert(at(&c, 1000u + 3000u, 0u) == 0u && c.mode == HCCEL_TEST_GAP);
    assert(at(&c, 1000u + 3999u, 0u) == 0u && c.mode == HCCEL_TEST_GAP);
    assert(at(&c, 1000u + 4000u, 0u) == 0u && c.mode == HCCEL_OFF);
    for (t = 4000u; t < 20000u; t += 50u) assert(at(&c, 1000u + t, 0u) == 0u);
    printf("no DTC: ON 0..2999 ms, OFF 3000..3999, OFF after (boundaries exact)\n");

    /* 2. MIL present before start: ON 3 s, OFF 1 s, ON */
    hccel_reset(&c);
    assert(at(&c, 0u, 1u) == 1u && c.mode == HCCEL_TEST_ON);
    assert(at(&c, 2999u, 1u) == 1u);
    assert(at(&c, 3000u, 1u) == 0u);      /* the separating dark second  */
    assert(at(&c, 3999u, 1u) == 0u);
    assert(at(&c, 4000u, 1u) == 1u && c.mode == HCCEL_ON);
    printf("MIL at key-on: ON-OFF-ON, the gap is forced even with a fault\n");

    /* 3. MIL appears later: ON at once; 4. cleared: OFF at once */
    assert(at(&c, 9000u, 0u) == 0u);
    assert(at(&c, 9001u, 1u) == 1u);
    assert(at(&c, 9002u, 0u) == 0u);
    printf("MIL later: ON on the same step, OFF on the same step it clears\n");

    /* 6. key cycle (no reset): the test repeats */
    assert(hccel_step(&c, 10000u, 0u, 1u) == 0u && c.mode == HCCEL_OFF);
    assert(at(&c, 10500u, 0u) == 1u && c.mode == HCCEL_TEST_ON);
    assert(at(&c, 13500u, 0u) == 0u);
    assert(at(&c, 14500u, 0u) == 0u && c.mode == HCCEL_OFF);
    printf("key cycle: the test repeats\n");

    /* the uptime wraps: the test is never re-armed by it */
    hccel_reset(&c);
    at(&c, 65000u, 0u);
    at(&c, (65000u + 5000u) & 0xFFFFu, 0u); /* wrapped past 65535        */
    for (t = 0u; t < 70000u; t += 500u) {
        assert(at(&c, (unsigned int)((70000u + t) & 0xFFFFu), 0u) == 0u);
    }
    printf("uptime wrap: no second test without a key-on edge\n");

    /* V97: the page's lamp test - disabled: the lamp is the MIL at once */
    hccel_reset(&c);
    hccel_config(&c, 0u, 3000u, 1000u);
    assert(at(&c, 100u, 0u) == 0u && c.mode == HCCEL_OFF);
    assert(at(&c, 200u, 1u) == 1u && c.mode == HCCEL_ON);
    printf("test disabled: no ON/OFF sequence, the MIL request at once\n");

    /* V97: other times, boundaries exact (2.0 s ON, 0.5 s dark) */
    hccel_reset(&c);
    hccel_config(&c, 1u, 2000u, 500u);
    assert(at(&c, 0u, 1u) == 1u);
    assert(at(&c, 1999u, 1u) == 1u);
    assert(at(&c, 2000u, 1u) == 0u && c.mode == HCCEL_TEST_GAP);
    assert(at(&c, 2499u, 1u) == 0u);
    assert(at(&c, 2500u, 1u) == 1u && c.mode == HCCEL_ON);
    printf("configured 2.0 s / 0.5 s: boundaries exact\n");
    printf("hccel: ALL PASS\n");
    return 0;
}
