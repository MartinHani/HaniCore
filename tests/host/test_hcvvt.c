/*
 * test_hcvvt.c - the VVT core (hcvvt.c), gcc -std=c89.
 * Run by tools/test_hcvvt_host.py (negative controls + Keil helper check).
 *
 * The plant: a hydraulic cam phaser. The solenoid duty meters oil: at the
 * NULL duty (~50 %, depends on oil pressure and temperature) the phaser
 * holds, above it advances, below it retards, at 250 deg/s per 100 % of
 * duty away from null; it stops mechanically at 0 and 50 deg; the measured
 * position lags 40 ms (the cam tooth that reports it).
 */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "hcvvt.h"

#define DT 20u

typedef struct {
    double pos;            /* deg */
    double null_duty;      /* 0..1000 */
    int    inverted;
    double hist[2];
} ph_t;

static void ph_step(ph_t *p, unsigned int duty)
{
    double rate = 250.0 * ((double)duty - p->null_duty) / 1000.0;   /* deg/s */
    if (p->inverted) rate = -rate;
    p->hist[1] = p->hist[0];
    p->hist[0] = p->pos;
    p->pos += rate * DT / 1000.0;
    if (p->pos < 0.0) p->pos = 0.0;
    if (p->pos > 50.0) p->pos = 50.0;
}

static hcvvt_cfg_t cfg(void)
{
    hcvvt_cfg_t c;
    memset(&c, 0, sizeof c);
    c.mode = HCVVT_MODE_CLOSED;
    c.min_rpm = 1000u;
    c.min_clt_c = 40;
    c.delay_ms = 2000u;
    c.kp = 150u;           /* 1.5 duty x10 per 0.1 deg */
    c.ki = 4u;
    c.kd = 0u;
    c.duty_min_x10 = 0u;
    c.duty_max_x10 = 1000u;
    c.duty_on_x10 = 1000u;
    return c;
}

static hcvvt_in_t in_of(const ph_t *p, int target_x10)
{
    hcvvt_in_t in;
    in.rpm = 3000u;
    in.clt_c = 90;
    in.target_x10 = target_x10;
    in.pos_x10 = (int)(p->hist[1] * 10.0 + 0.5);
    in.pos_ok = 1u;
    return in;
}

/* returns the peak position after `from` */
static double run(hcvvt_t *v, const hcvvt_cfg_t *c, ph_t *p, int target_x10,
                  unsigned int n, double *final, double *lowest)
{
    unsigned int k;
    double pk = -1.0, lo = 1e9;
    for (k = 0u; k < n; k++) {
        hcvvt_in_t in = in_of(p, target_x10);
        ph_step(p, hcvvt_step(v, c, &in, DT));
        if (p->pos > pk) pk = p->pos;
        if (p->pos < lo) lo = p->pos;
    }
    if (final) *final = p->pos;
    if (lowest) *lowest = lo;
    return pk;
}

static void warm(hcvvt_t *v, const hcvvt_cfg_t *c, ph_t *p)
{
    memset(p, 0, sizeof *p);
    p->null_duty = 500.0;
    hcvvt_reset(v);
    (void)run(v, c, p, 0, 150u, 0, 0);             /* past the 2 s delay */
}

static void test_gates(void)
{
    hcvvt_cfg_t c = cfg();
    hcvvt_t v;
    ph_t p;
    hcvvt_in_t in;
    unsigned int k;
    memset(&p, 0, sizeof p);
    hcvvt_reset(&v);
    c.mode = HCVVT_MODE_OFF;
    in = in_of(&p, 200);
    assert(hcvvt_step(&v, &c, &in, DT) == 0u && v.state == HCVVT_S_OFF);
    c = cfg();
    in.rpm = 900u;
    assert(hcvvt_step(&v, &c, &in, DT) == 0u && v.state == HCVVT_S_WAIT);
    in.rpm = 3000u; in.clt_c = 30;
    assert(hcvvt_step(&v, &c, &in, DT) == 0u && v.state == HCVVT_S_WAIT);
    in.clt_c = 90;
    hcvvt_reset(&v);
    for (k = 0u; k < 2000u / DT - 1u; k++)
        assert(hcvvt_step(&v, &c, &in, DT) == 0u && v.state == HCVVT_S_WAIT);
    assert(hcvvt_step(&v, &c, &in, DT) > 0u && (v.state & HCVVT_S_CLOSED));
    in.pos_ok = 0u;
    assert(hcvvt_step(&v, &c, &in, DT) == 0u && v.state == HCVVT_S_NOPOS && v.integ100 == 0L);
    printf("gates: off / below rpm / cold / the 2 s activation delay -> 0; no position -> 0 and reset\n");
}

static void test_switch(void)
{
    hcvvt_cfg_t c = cfg();
    hcvvt_t v;
    ph_t p;
    hcvvt_in_t in;
    c.mode = HCVVT_MODE_SWITCH;
    c.duty_on_x10 = 1000u;
    memset(&p, 0, sizeof p);
    warm(&v, &c, &p);
    in = in_of(&p, 1);
    in.pos_ok = 0u;                                   /* needs no position */
    assert(hcvvt_step(&v, &c, &in, DT) == 1000u && v.state == HCVVT_S_SWITCH);
    in.target_x10 = 0;
    assert(hcvvt_step(&v, &c, &in, DT) == 0u);
    printf("switch mode (on/off adjuster): target > 0 -> ON duty, 0 -> off, no position needed\n");
}

static void test_tracking(void)
{
    hcvvt_cfg_t c = cfg();
    hcvvt_t v;
    ph_t p;
    double fin, pk;
    warm(&v, &c, &p);
    pk = run(&v, &c, &p, 250, 150u, &fin, 0);        /* 3 s */
    printf("tracking: 0 -> 25.0 deg: %.2f after 3 s, peak %.2f\n", fin, pk);
    assert(fin > 24.0 && fin < 26.0 && pk < 28.0);
    p.null_duty = 580.0;                               /* oil hot: null moves */
    (void)run(&v, &c, &p, 250, 150u, &fin, 0);
    printf("null duty 50 -> 58 %% (hot oil): %.2f deg after 3 s\n", fin);
    assert(fin > 24.0 && fin < 26.0);
}

static void test_windup(void)
{
    hcvvt_cfg_t c = cfg();
    hcvvt_t v;
    ph_t p;
    double fin, lo;
    unsigned int k, reach = 0u;
    warm(&v, &c, &p);
    (void)run(&v, &c, &p, 600, 250u, 0, 0);            /* 60 deg: beyond the 50 stop, 5 s */
    for (k = 0u; k < 150u; k++) {
        hcvvt_in_t in = in_of(&p, 200);
        ph_step(&p, hcvvt_step(&v, &c, &in, DT));
        if (!reach && p.pos < 21.0) reach = k + 1u;
    }
    fin = p.pos;
    (void)lo;
    printf("5 s against the mechanical stop, then 20 deg: reached in %u ms, final %.2f\n",
           reach * DT, fin);
    assert(reach && reach * DT <= 1600u);
    assert(fin > 19.0 && fin < 21.0);
}

static void test_invert(void)
{
    hcvvt_cfg_t c = cfg();
    hcvvt_t v;
    ph_t p;
    double fin;
    c.invert = 1u;
    warm(&v, &c, &p);
    p.inverted = 1;
    p.pos = 40.0; p.hist[0] = p.hist[1] = 40.0;
    (void)run(&v, &c, &p, 150, 200u, &fin, 0);
    printf("inverted phaser (duty up = retard), invert set: 40 -> %.2f deg for a 15 target\n", fin);
    assert(fin > 14.0 && fin < 16.0);
}

static void test_d_kick(void)
{
    hcvvt_cfg_t c = cfg(), c0;
    hcvvt_t v, v0;
    ph_t p;
    hcvvt_in_t in;
    unsigned int dk, d0;
    c.kd = 500u;
    c0 = c; c0.kd = 0u;
    warm(&v, &c, &p);
    memcpy(&v0, &v, sizeof v0);
    in = in_of(&p, 0);
    (void)hcvvt_step(&v, &c, &in, DT);
    (void)hcvvt_step(&v0, &c0, &in, DT);
    in.target_x10 = 300;                                /* step, position constant */
    dk = hcvvt_step(&v, &c, &in, DT);
    d0 = hcvvt_step(&v0, &c0, &in, DT);
    assert(dk == d0);
    in.pos_x10 += 20;                                   /* the cam moves: D acts */
    dk = hcvvt_step(&v, &c, &in, DT);
    d0 = hcvvt_step(&v0, &c0, &in, DT);
    assert(dk < d0);
    printf("derivative on the position: a 30 deg target step gives the same duty with and "
           "without D; a moving cam does not\n");
}

static unsigned long seed = 3u;
static unsigned int rnd16(void)
{
    seed = seed * 1103515245UL + 12345UL;
    return (unsigned int)((seed >> 8) & 0xFFFFu);
}

static void test_fuzz(void)
{
    hcvvt_t v;
    unsigned int k;
    hcvvt_reset(&v);
    for (k = 0u; k < 200000u; k++) {
        hcvvt_cfg_t c;
        hcvvt_in_t in;
        unsigned int d;
        c.mode = (unsigned char)(rnd16() % 4u); c.invert = (unsigned char)(rnd16() & 1u);
        c.min_rpm = rnd16() & 0x7FFu; c.min_clt_c = (int)(rnd16() % 200u) - 50;
        c.delay_ms = rnd16() & 0x3FFu; c.kp = rnd16(); c.ki = rnd16(); c.kd = rnd16();
        c.duty_min_x10 = rnd16() & 0x7FFu; c.duty_max_x10 = rnd16() & 0x7FFu;
        c.duty_on_x10 = rnd16();
        in.rpm = rnd16(); in.clt_c = (int)(rnd16() % 300u) - 100;
        in.target_x10 = (int)rnd16(); in.pos_x10 = (int)rnd16();
        in.pos_ok = (unsigned char)(rnd16() & 1u);
        d = hcvvt_step(&v, &c, &in, rnd16() & 0xFFu);
        assert(d <= 1000u && d == v.duty_x10);
        assert(v.integ100 >= -100000L && v.integ100 <= 100000L);
    }
    printf("fuzz: 200000 random steps, duty 0..1000, I bounded\n");
}

int main(void)
{
    test_gates();
    test_switch();
    test_tracking();
    test_windup();
    test_invert();
    test_d_kick();
    test_fuzz();
    printf("hcvvt: ALL PASS\n");
    return 0;
}
