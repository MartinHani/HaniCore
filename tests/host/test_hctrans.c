/* Host test of firmware/engine/hctrans.c against a floating-point X-tau PLANT: the
 * port wall the model believes in, simulated independently. The claim under
 * test is the one the firmware makes: whatever the steady model wants, the
 * CYLINDER receives it, cycle by cycle, through tip-in, tip-out, a fuel cut
 * and its re-entry. */
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "hctrans.h"

typedef struct { double film; } plant_t;

/* One cycle of the real wall: returns what reached the cylinder. */
static double plant_cycle(plant_t *p, double inj, double x, double alpha)
{
    double cyl = (1.0 - x) * inj + alpha * p->film;
    p->film = p->film + x * inj - alpha * p->film;
    return cyl;
}

static hctrans_in_t in_of(unsigned int base, unsigned int rpm)
{
    hctrans_in_t in;
    memset(&in, 0, sizeof in);
    in.base_us = base;
    in.rpm = rpm;
    in.dt_ms = (unsigned int)(2u * (60000u / rpm));   /* exactly one cycle */
    in.x_pm = 300u;
    in.tau_ms = 300u;
    return in;
}

/* Run n cycles, the model steering the plant; worst |cyl - want| / want over
   cycles `from`.. (the model and the plant start from the same empty wall). */
static double run(hctrans_t *s, plant_t *p, hctrans_in_t *in, int n, int from,
                  double *last_cyl)
{
    int i;
    double worst = 0.0, x = in->x_pm / 1000.0;
    for (i = 0; i < n; i++) {
        unsigned int out = hctrans_step(s, in);
        double a = s->alpha / 1000.0;
        double cyl = plant_cycle(p, (double)out, x, a);
        if (i >= from && s->want > 0u) {
            double e = fabs(cyl - s->want) / s->want;
            if (e > worst) worst = e;
        }
        *last_cyl = cyl;
    }
    return worst;
}

static void test_steady_and_steps(void)
{
    hctrans_t s;
    plant_t p = {0.0};
    hctrans_in_t in = in_of(5000u, 2000u);
    double cyl, w;

    hctrans_reset(&s);
    in.cranking = 1u;                     /* cranking builds the film     */
    run(&s, &p, &in, 40, 0, &cyl);
    in.cranking = 0u;
    w = run(&s, &p, &in, 200, 0, &cyl);
    assert(w < 0.01);
    assert(fabs(s.out - 5000.0) / 5000.0 < 0.01);        /* no bias          */
    printf("steady: out %u film %u worst %.3f %%\n", s.out, s.film, w * 100);

    in.base_us = 9000u;                   /* tip-in                       */
    w = run(&s, &p, &in, 1, 0, &cyl);
    assert(s.out > 9000u);                /* the film takes its share     */
    w += run(&s, &p, &in, 100, 0, &cyl);
    assert(w < 0.01);
    printf("tip-in 5 -> 9 ms: first pulse over the want, cylinder within %.3f %%\n",
           w * 100);

    in.base_us = 3000u;                   /* tip-out                      */
    w = run(&s, &p, &in, 1, 0, &cyl);
    assert(s.out < 3000u);
    w += run(&s, &p, &in, 100, 0, &cyl);
    assert(w < 0.01);
    printf("tip-out 9 -> 3 ms: under the want, cylinder within %.3f %%\n", w * 100);
}

static void test_cut_and_reentry(void)
{
    hctrans_t s;
    plant_t p = {0.0};
    hctrans_in_t in = in_of(6000u, 3000u);
    double cyl, w;
    unsigned int film_before;

    hctrans_reset(&s);
    in.cranking = 0u;
    s.was_crank = 0u;
    run(&s, &p, &in, 300, 0, &cyl);
    film_before = s.film;
    in.cut = 1u;
    run(&s, &p, &in, 30, 0, &cyl);
    assert(s.out == 0u);
    assert(s.film < film_before / 4u);    /* the wall dried               */
    in.cut = 0u;
    w = run(&s, &p, &in, 1, 0, &cyl);
    assert(s.out > 6000u);                /* re-entry rebuilds the film   */
    w += run(&s, &p, &in, 60, 0, &cyl);
    assert(w < 0.01);
    printf("cut + re-entry: film %u -> dry, re-entry pulse over the want, "
           "cylinder within %.3f %%\n", film_before, w * 100);
}

static void test_after_start(void)
{
    hctrans_t s;
    hctrans_in_t in = in_of(4000u, 1000u);
    unsigned int i, prev = 0xFFFFu;

    hctrans_reset(&s);
    in.x_pm = 0u;                         /* after-start alone            */
    in.as_pm = 500u;                      /* +50 %                        */
    in.as_decay_ms = 3000u;
    in.cranking = 1u;
    hctrans_step(&s, &in);
    assert(s.as_pm == 0u && s.out == 4000u);
    in.cranking = 0u;
    in.dt_ms = 100u;
    hctrans_step(&s, &in);
    assert(s.as_pm == 500u && s.out == 6000u);
    for (i = 0u; i < 40u; i++) {
        hctrans_step(&s, &in);
        assert(s.as_pm <= prev || prev == 0xFFFFu);
        prev = s.as_pm;
        if (i == 14u) {                   /* 1.5 s of 3: half left        */
            assert(s.as_pm >= 230u && s.as_pm <= 270u);
        }
    }
    assert(s.as_pm == 0u && s.out == 4000u);
    /* V98r2: +150 % on a 20 ms pulse is 50 ms, exact - the product passes
       the 16-bit quotient the C167's DIVLU can return */
    hctrans_reset(&s);
    in = in_of(20000u, 1000u);
    in.x_pm = 0u;
    in.as_pm = 1500u;
    in.as_decay_ms = 60000u;
    in.dt_ms = 1u;
    s.was_crank = 0u;
    hctrans_step(&s, &in);
    assert(s.want >= 49990u && s.want <= 50000u);
    printf("after-start: +50 %% decays linearly to 0 over 3 s; +150 %% of "
           "20 ms is 50 ms\n");
}

static void test_bounds(void)
{
    hctrans_t s;
    hctrans_in_t in = in_of(60000u, 20000u);
    unsigned int i;

    hctrans_reset(&s);
    in.x_pm = 2000u;                      /* refused above 90 %           */
    in.tau_ms = 65535u;
    in.as_pm = 60000u;
    in.as_decay_ms = 65535u;
    s.was_crank = 0u;
    for (i = 0u; i < 2000u; i++) {
        unsigned int out = hctrans_step(&s, &in);
        assert(out <= HCTRANS_OUT_MAX && s.film <= HCTRANS_FILM_MAX);
    }
    in.rpm = 30u;                         /* stopped: the film dries      */
    in.dt_ms = 200u;
    in.tau_ms = 100u;
    for (i = 0u; i < 50u; i++) hctrans_step(&s, &in);
    assert(s.film < 100u);
    assert(hctrans_lerp8(100u, 200u, 10u, 30u, 150u) == 20u);
    assert(hctrans_lerp8(100u, 200u, 30u, 10u, 150u) == 20u);
    assert(hctrans_lerp8(100u, 200u, 10u, 30u, 50u) == 10u);
    assert(hctrans_lerp8(100u, 200u, 10u, 30u, 250u) == 30u);
    assert(hctrans_lerp8(200u, 100u, 10u, 30u, 150u) == 10u);
    assert(hctrans_lerp8(0u, 65535u, 0u, 255u, 65534u) == 254u);
    printf("bounds: saturated inputs stay inside 0..60000 us, film dries "
           "when stopped, lerp clamps\n");
}

int main(void)
{
    test_steady_and_steps();
    test_cut_and_reentry();
    test_after_start();
    test_bounds();
    printf("hctrans: ALL PASS\n");
    return 0;
}
