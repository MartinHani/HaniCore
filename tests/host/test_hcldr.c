/*
 * test_hcldr.c - the boost control core (hcldr.c), gcc -std=c89.
 * Run by tools/test_hcldr_host.py (which also runs the negative controls
 * and the Keil no-helper check).
 *
 * The plant: a turbo whose achievable pressure rises with rpm (spool), a
 * wastegate whose spring alone holds 140 kPa, the valve adding up to 120 kPa
 * at 100 % duty, and a first-order response (tau 0.4 s = 20 steps of 20 ms).
 * Crude, but it has the two properties the controller must survive: a target
 * the turbo cannot reach yet, and a lag.
 */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "hcldr.h"

typedef struct { double map; unsigned int rpm; } plant_t;

static double pmax(unsigned int rpm)       /* kPa absolute */
{
    double f = ((double)rpm - 2000.0) / 2000.0;
    if (f < 0.0) f = 0.0;
    if (f > 1.0) f = 1.0;
    return 100.0 + 170.0 * f;
}

static void plant_step(plant_t *p, unsigned int duty_x10)
{
    double eq = 140.0 + 120.0 * duty_x10 / 1000.0;
    if (eq > pmax(p->rpm)) eq = pmax(p->rpm);
    p->map += (eq - p->map) / 20.0;
}

static hcldr_cfg_t cfg_closed(void)
{
    hcldr_cfg_t c;
    memset(&c, 0, sizeof c);
    c.closed = 1u;
    c.min_rpm = 1500u;
    c.min_tps_x10 = 300u;
    c.cl_min_map_x10 = 1100u;
    c.kp = 60u;          /* 0.60 duty x10 per 0.1 kPa per step */
    c.ki = 4u;
    c.i_band_x10 = 200u; /* integrate within 20 kPa of the target */
    c.kd = 0u;
    c.cut_x10 = 2200u;
    c.hyst_x10 = 150u;
    return c;
}

static hcldr_in_t input(const plant_t *p, unsigned int target_x10)
{
    hcldr_in_t in;
    in.rpm = p->rpm;
    in.tps_x10 = 900u;
    in.map_x10 = (unsigned int)(p->map * 10.0 + 0.5);
    in.map_ok = 1u;
    in.enabled = 1u;
    in.keyoff = 0u;
    in.open_x10 = 300u;
    in.target_x10 = target_x10;
    return in;
}

static void test_overboost(void)
{
    hcldr_cfg_t c = cfg_closed();
    hcldr_t b;
    hcldr_in_t in;
    hcldr_reset(&b);
    {
        plant_t p; p.map = 150.0; p.rpm = 5000u;
        in = input(&p, 1800u);
    }
    in.enabled = 0u;                              /* boost control OFF      */
    in.map_x10 = 2199u; assert(hcldr_step(&b, &c, &in) == 0u && !b.cut);
    in.map_x10 = 2200u; hcldr_step(&b, &c, &in); assert(b.cut && b.state == HCLDR_S_CUT && b.cuts == 1u);
    in.map_x10 = 2100u; hcldr_step(&b, &c, &in); assert(b.cut);          /* inside the hysteresis */
    in.map_x10 = 2051u; hcldr_step(&b, &c, &in); assert(b.cut);
    in.map_x10 = 2049u; hcldr_step(&b, &c, &in); assert(!b.cut);
    in.map_x10 = 2300u; hcldr_step(&b, &c, &in); assert(b.cut && b.cuts == 2u);
    in.map_x10 = 2400u; hcldr_step(&b, &c, &in); assert(b.cuts == 2u);   /* one event */
    /* a page of zeros still protects: 220 kPa / 15 kPa */
    c.cut_x10 = 0u; c.hyst_x10 = 0u; hcldr_reset(&b);
    in.map_x10 = 2200u; hcldr_step(&b, &c, &in); assert(b.cut);
    in.map_x10 = 2051u; hcldr_step(&b, &c, &in); assert(b.cut);
    in.map_x10 = 2049u; hcldr_step(&b, &c, &in); assert(!b.cut);
    /* hysteresis >= limit is clamped (release one count below) */
    c.cut_x10 = 1500u; c.hyst_x10 = 4000u; hcldr_reset(&b);
    in.map_x10 = 1500u; hcldr_step(&b, &c, &in); assert(b.cut);
    in.map_x10 = 2u;    hcldr_step(&b, &c, &in); assert(b.cut);
    in.map_x10 = 0u;    hcldr_step(&b, &c, &in); assert(!b.cut);
    printf("overboost: latches at the limit with boost control OFF, releases only below limit-hyst, "
           "one count per event, defaults protect\n");
}

static void test_sensor(void)
{
    hcldr_cfg_t c = cfg_closed();
    hcldr_t b;
    plant_t p; hcldr_in_t in;
    p.map = 150.0; p.rpm = 4000u;
    hcldr_reset(&b);
    in = input(&p, 1800u);
    in.map_x10 = 2500u; hcldr_step(&b, &c, &in); assert(b.cut);
    in.map_ok = 0u;
    assert(hcldr_step(&b, &c, &in) == 0u && b.state == HCLDR_S_SENSOR && !b.cut);
    c.closed = 0u;
    in.open_x10 = 500u;
    assert(hcldr_step(&b, &c, &in) == 0u && b.state == HCLDR_S_SENSOR);
    printf("sensor: no valid pressure -> valve 0 in open AND closed loop, no fuel cut on a guess\n");
}

static void test_gates(void)
{
    hcldr_cfg_t c = cfg_closed();
    hcldr_t b;
    plant_t p; hcldr_in_t in;
    unsigned int i;
    p.map = 150.0; p.rpm = 4000u;
    hcldr_reset(&b);
    for (i = 0u; i < 50u; i++) { in = input(&p, 1600u); hcldr_step(&b, &c, &in); }
    assert(b.integ100 != 0L);
    in = input(&p, 1600u); in.keyoff = 1u;
    assert(hcldr_step(&b, &c, &in) == 0u && b.state == HCLDR_S_OFF && b.integ100 == 0L);
    for (i = 0u; i < 50u; i++) { in = input(&p, 1600u); hcldr_step(&b, &c, &in); }
    in = input(&p, 1600u); in.rpm = 1499u;
    assert(hcldr_step(&b, &c, &in) == 0u && b.state == HCLDR_S_BELOW && b.integ100 == 0L);
    in = input(&p, 1600u); in.tps_x10 = 299u;
    assert(hcldr_step(&b, &c, &in) == 0u && b.state == HCLDR_S_BELOW);
    in = input(&p, 1600u); in.enabled = 0u;
    assert(hcldr_step(&b, &c, &in) == 0u && b.state == HCLDR_S_OFF);
    /* open loop, clamped, flagged saturated at the ends */
    c.closed = 0u;
    in = input(&p, 1600u); in.open_x10 = 1500u;
    assert(hcldr_step(&b, &c, &in) == 1000u && b.state == (HCLDR_S_OPEN | HCLDR_S_SAT));
    in.open_x10 = 420u;
    assert(hcldr_step(&b, &c, &in) == 420u && b.state == HCLDR_S_OPEN);
    /* closed loop below its pressure threshold = open loop, PID reset */
    c.closed = 1u;
    for (i = 0u; i < 50u; i++) { in = input(&p, 1600u); hcldr_step(&b, &c, &in); }
    in = input(&p, 1600u); in.map_x10 = 1099u;
    assert(hcldr_step(&b, &c, &in) == 300u && b.state == HCLDR_S_OPEN && b.integ100 == 0L);
    printf("gates: key-off / disabled / below floor -> 0 and PID reset; open loop clamped; "
           "closed loop below its map threshold runs open\n");
}

/* run the closed loop; returns the peak pressure (kPa) after t_from steps */
static double run(hcldr_t *b, const hcldr_cfg_t *c, plant_t *p, unsigned int target_x10,
                  unsigned int steps, unsigned int t_from, double *final)
{
    unsigned int i;
    double peak = 0.0;
    for (i = 0u; i < steps; i++) {
        hcldr_in_t in = input(p, target_x10);
        unsigned int duty = hcldr_step(b, c, &in);
        assert(duty <= 1000u);
        assert(!b->cut);
        plant_step(p, duty);
        if (i >= t_from && p->map > peak) peak = p->map;
    }
    if (final) *final = p->map;
    return peak;
}

static void test_tracking(void)
{
    hcldr_cfg_t c = cfg_closed();
    hcldr_t b;
    plant_t p;
    double fin, peak;
    hcldr_reset(&b);
    p.map = 140.0; p.rpm = 4500u;
    peak = run(&b, &c, &p, 1800u, 400u, 0u, &fin);
    printf("tracking: target 180 kPa at 4500 rpm -> %.1f kPa after 8 s, peak %.1f\n", fin, peak);
    assert(fin > 179.0 && fin < 181.0);
    assert(peak < 184.0);
}

static void test_windup(void)
{
    hcldr_cfg_t c = cfg_closed();
    hcldr_t b;
    plant_t p;
    double fin, peak;
    unsigned int i;
    hcldr_reset(&b);
    /* 10 s at 2600 rpm: the turbo makes at most 151 kPa, target 190 */
    p.map = 140.0; p.rpm = 2600u;
    (void)run(&b, &c, &p, 1900u, 500u, 0u, 0);
    /* then it spools: rpm ramps to 5000 in 1 s */
    peak = 0.0;
    for (i = 0u; i < 400u; i++) {
        hcldr_in_t in;
        unsigned int duty;
        p.rpm = i < 50u ? 2600u + i * 48u : 5000u;
        in = input(&p, 1900u);
        duty = hcldr_step(&b, &c, &in);
        assert(!b.cut);
        plant_step(&p, duty);
        if (p.map > peak) peak = p.map;
    }
    fin = p.map;
    printf("windup: 10 s against an unreachable target, then spool -> peak %.1f kPa, final %.1f\n",
           peak, fin);
    assert(peak < 193.0);
    assert(fin > 189.0 && fin < 191.0);
}

static void test_saturation_low(void)
{
    hcldr_cfg_t c = cfg_closed();
    hcldr_t b;
    plant_t p;
    unsigned int i, reached = 0u;
    hcldr_reset(&b);
    /* 10 s asking for 128 kPa - inside the band, but below what the
       wastegate spring holds (140): the output sits at 0 */
    p.map = 140.0; p.rpm = 4500u;
    for (i = 0u; i < 500u; i++) {
        hcldr_in_t in = input(&p, 1280u);
        plant_step(&p, hcldr_step(&b, &c, &in));
    }
    assert(b.duty_x10 < 30u);                     /* at (or next to) 0 */
    /* then the target returns to 150 kPa: it must be reached promptly */
    for (i = 0u; i < 500u; i++) {
        hcldr_in_t in = input(&p, 1500u);
        plant_step(&p, hcldr_step(&b, &c, &in));
        if (!reached && p.map > 149.0) reached = i + 1u;
    }
    printf("saturated at 0 for 10 s, then target 150 kPa: reached in %u ms, I part %d\n",
           reached * 20u, b.i_x10);
    assert(reached && reached * 20u <= 2000u);
}

static void test_d_on_measurement(void)
{
    hcldr_cfg_t c = cfg_closed();
    hcldr_t b;
    plant_t p;
    hcldr_in_t in;
    unsigned int d0, d1;
    c.kd = 400u;
    hcldr_reset(&b);
    p.map = 150.0; p.rpm = 4500u;
    in = input(&p, 1500u); d0 = hcldr_step(&b, &c, &in);
    in = input(&p, 1500u); (void)hcldr_step(&b, &c, &in);
    in = input(&p, 1800u); d1 = hcldr_step(&b, &c, &in);   /* target step, map constant */
    assert(b.d_x10 == 0);
    printf("derivative on the measurement: a 30 kPa target step gives D = 0 (duty %u -> %u)\n", d0, d1);
    /* and D does act on a moving pressure */
    in = input(&p, 1800u); in.map_x10 = 1520u; (void)hcldr_step(&b, &c, &in);
    assert(b.d_x10 == -80);
}

static unsigned long seed = 99u;
static unsigned int rnd16(void)
{
    seed = seed * 1103515245UL + 12345UL;
    return (unsigned int)((seed >> 8) & 0xFFFFu);
}

static void test_fuzz(void)
{
    hcldr_cfg_t c;
    hcldr_t b;
    unsigned int i;
    hcldr_reset(&b);
    for (i = 0u; i < 200000u; i++) {
        hcldr_in_t in;
        unsigned int duty;
        memset(&c, 0, sizeof c);
        c.closed = (unsigned char)(rnd16() & 1u);
        c.kp = rnd16(); c.ki = rnd16(); c.kd = rnd16();
        c.cut_x10 = rnd16(); c.hyst_x10 = rnd16();
        c.cl_min_map_x10 = rnd16() & 0x0FFFu;
        in.rpm = rnd16(); in.tps_x10 = rnd16() & 0x07FFu;
        in.map_x10 = rnd16(); in.map_ok = (unsigned char)((rnd16() & 15u) != 0u);
        in.enabled = 1u; in.keyoff = 0u;
        in.open_x10 = rnd16(); in.target_x10 = rnd16();
        duty = hcldr_step(&b, &c, &in);
        assert(duty <= 1000u && duty == b.duty_x10);
        assert(b.p_x10 >= -1000 && b.p_x10 <= 1000 && b.d_x10 >= -1000 && b.d_x10 <= 1000);
        assert(b.i_x10 >= -1000 && b.i_x10 <= 1000);
        assert(b.integ100 >= -100000L && b.integ100 <= 100000L);
        assert(!b.cut || (b.state == HCLDR_S_CUT && duty == 0u));
    }
    printf("fuzz: 200000 steps of random gains/limits/inputs - every value in range\n");
}

int main(void)
{
    test_overboost();
    test_sensor();
    test_gates();
    test_tracking();
    test_windup();
    test_saturation_low();
    test_d_on_measurement();
    test_fuzz();
    printf("hcldr: ALL PASS\n");
    return 0;
}
