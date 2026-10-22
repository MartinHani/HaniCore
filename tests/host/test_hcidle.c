/*
 * test_hcidle.c - the idle speed control core (hcidle.c), gcc -std=c89.
 * Run by tools/test_hcidle_host.py (negative controls + Keil helper check).
 *
 * The plant: an engine whose equilibrium rpm is 130 rpm per % of throttle
 * air minus an accessory load (an AC compressor: 150 rpm), first-order with
 * tau 0.3 s behind a 60 ms transport delay (intake filling + the next
 * combustions). The throttle is max(pedal, idle floor), as hc_dbw.c applies
 * it. Crude, but it has what idle control must survive: a delay, a load
 * step, a pedal blip and a coast-down from high rpm.
 */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "hcidle.h"

#define DT 20u

typedef struct {
    double rpm;
    double load;          /* rpm the accessories take            */
    double hist[3];       /* throttle, 60 ms delay line          */
} eng_t;

static void eng_step(eng_t *g, double thr_pct)
{
    double eq;
    g->hist[2] = g->hist[1]; g->hist[1] = g->hist[0]; g->hist[0] = thr_pct;
    eq = 130.0 * g->hist[2] - g->load;
    if (eq < 0.0) eq = 0.0;
    g->rpm += (eq - g->rpm) * (DT / 300.0);
}

static hcidle_cfg_t cfg(void)
{
    hcidle_cfg_t c;
    memset(&c, 0, sizeof c);
    c.enabled = 1u;
    c.kp = 3u;             /* 0.03 % per rpm */
    c.ki = 10u;            /* 0.01 % per rpm per step (x1000) */
    c.range_x10 = 50u;     /* +-5 % */
    c.band_rpm = 400u;
    c.pedal_x10 = 20u;     /* rusEFI idlePidDeactivationTpsThreshold 2 % */
    c.start_ms = 1000u;
    return c;
}

static hcidle_in_t in_of(const eng_t *g, unsigned int pedal_x10)
{
    hcidle_in_t in;
    in.rpm = (unsigned int)(g->rpm + 0.5);
    in.target_rpm = 800u;
    in.base_x10 = 65u;     /* 6.5 %: 845 rpm unloaded - the trim must take 45 off */
    in.pedal_x10 = pedal_x10;
    in.cranking = 0u;
    return in;
}

/* run n steps; returns min rpm seen after step `from` */
static double run(hcidle_t *d, const hcidle_cfg_t *c, eng_t *g, unsigned int n,
                  unsigned int pedal_x10, unsigned int from, double *max_out)
{
    unsigned int k;
    double mn = 1e9, mx = 0.0;
    for (k = 0u; k < n; k++) {
        hcidle_in_t in = in_of(g, pedal_x10);
        unsigned int floor_x10 = hcidle_step(d, c, &in, DT);
        double thr = floor_x10 / 10.0;
        if (pedal_x10 / 10.0 > thr) thr = pedal_x10 / 10.0;
        eng_step(g, thr);
        assert(d->trim_x10 >= -(int)c->range_x10 && d->trim_x10 <= (int)c->range_x10);
        if (k >= from && g->rpm < mn) mn = g->rpm;
        if (k >= from && g->rpm > mx) mx = g->rpm;
    }
    if (max_out) *max_out = mx;
    return mn;
}

static void settle(hcidle_t *d, const hcidle_cfg_t *c, eng_t *g)
{
    memset(g, 0, sizeof *g);
    g->rpm = 845.0;
    g->hist[0] = g->hist[1] = g->hist[2] = 6.5;
    hcidle_reset(d);
    (void)run(d, c, g, 500u, 0u, 0u, 0);          /* 10 s */
}

static void test_states(void)
{
    hcidle_cfg_t c = cfg();
    hcidle_t d;
    hcidle_in_t in;
    eng_t g;
    unsigned int k;
    memset(&g, 0, sizeof g);
    g.rpm = 845.0;
    hcidle_reset(&d);
    c.enabled = 0u;
    in = in_of(&g, 0u);
    assert(hcidle_step(&d, &c, &in, DT) == 0u && d.state == HCIDLE_S_OFF);
    c.enabled = 1u;
    in.rpm = 0u;
    assert(hcidle_step(&d, &c, &in, DT) == 65u && d.state == HCIDLE_S_STOPPED);
    in.rpm = 250u; in.cranking = 1u;               /* far below target */
    assert(hcidle_step(&d, &c, &in, DT) == 65u && d.state == HCIDLE_S_CRANK);
    in.cranking = 0u;
    for (k = 0u; k < 1000u / DT; k++) {            /* the post-start wait */
        assert(hcidle_step(&d, &c, &in, DT) == 65u && d.state == HCIDLE_S_CRANK);
    }
    assert(hcidle_step(&d, &c, &in, DT) > 65u && (d.state & HCIDLE_S_CLOSED));
    printf("states: off -> 0 (no floor); stopped / cranking / first %u ms -> base only; "
           "then closed loop\n", c.start_ms);
}

static void test_converge(void)
{
    hcidle_cfg_t c = cfg();
    hcidle_t d;
    eng_t g;
    settle(&d, &c, &g);
    printf("warm idle: 845 unloaded -> %.1f rpm after 10 s, trim %d (0.1 %%)\n", g.rpm, d.trim_x10);
    assert(g.rpm > 790.0 && g.rpm < 810.0);
    assert(d.trim_x10 < 0);
}

static void test_load_step(void)
{
    hcidle_cfg_t c = cfg();
    hcidle_t d;
    eng_t g;
    double mn, mx;
    settle(&d, &c, &g);
    g.load = 150.0;                                  /* AC on */
    mn = run(&d, &c, &g, 250u, 0u, 0u, &mx);         /* 5 s */
    printf("load step 150 rpm: dip to %.1f, after 5 s %.1f rpm, trim %d\n", mn, g.rpm, d.trim_x10);
    assert(mn > 680.0);
    assert(g.rpm > 785.0 && g.rpm < 815.0);
}

static void test_blip_and_coast(void)
{
    hcidle_cfg_t c = cfg();
    hcidle_t d;
    eng_t g;
    long held;
    double mn, mx;
    settle(&d, &c, &g);
    g.load = 150.0;
    (void)run(&d, &c, &g, 400u, 0u, 0u, 0);          /* learned the AC load */
    held = d.integ1000;
    (void)run(&d, &c, &g, 100u, 250u, 0u, &mx);      /* 2 s at 25 % pedal */
    assert(d.integ1000 == held && d.state == HCIDLE_S_PEDAL);
    mn = run(&d, &c, &g, 400u, 0u, 0u, 0);           /* release: coast down */
    printf("pedal 25 %% for 2 s (%.0f rpm), release: I held through pedal and coast, "
           "lowest %.1f rpm, final %.1f\n", mx, mn, g.rpm);
    assert(mx > 2500.0);
    assert(mn > 740.0);
    assert(g.rpm > 785.0 && g.rpm < 815.0);
}

static void test_coast_in_gear(void)
{
    hcidle_cfg_t c = cfg();
    hcidle_t d;
    eng_t g;
    unsigned int k;
    long held;
    double mn;
    settle(&d, &c, &g);
    held = d.integ1000;
    /* 10 s coasting in gear, pedal released: the VEHICLE holds 2000 rpm */
    for (k = 0u; k < 500u; k++) {
        hcidle_in_t in;
        g.rpm = 2000.0;
        in = in_of(&g, 0u);
        (void)hcidle_step(&d, &c, &in, DT);
    }
    assert(d.integ1000 == held && d.state == HCIDLE_S_COAST);
    /* clutch in: the engine falls to idle on its own */
    mn = run(&d, &c, &g, 400u, 0u, 0u, 0);
    printf("coast in gear at 2000 rpm for 10 s: I held (above target + band); clutch in -> "
           "lowest %.1f rpm, final %.1f\n", mn, g.rpm);
    assert(mn > 740.0);
}

static void test_limit(void)
{
    hcidle_cfg_t c = cfg();
    hcidle_t d;
    eng_t g;
    double mn, mx;
    settle(&d, &c, &g);
    g.load = 1200.0;                                  /* needs +9 %: beyond the 5 % range */
    (void)run(&d, &c, &g, 500u, 0u, 0u, 0);
    assert(d.trim_x10 == 50 && (d.state & HCIDLE_S_LIMIT));
    assert(d.integ1000 <= 50L * 1000L);
    g.load = 0.0;                                     /* the load goes away */
    mn = run(&d, &c, &g, 400u, 0u, 0u, &mx);
    printf("beyond authority: trim held at +5.0 %%; load removed -> peak %.1f rpm, final %.1f\n",
           mx, g.rpm);
    assert(mx < 1600.0);
    assert(g.rpm > 785.0 && g.rpm < 815.0);
    (void)mn;
}

static void test_stop_resets(void)
{
    hcidle_cfg_t c = cfg();
    hcidle_t d;
    eng_t g;
    hcidle_in_t in;
    settle(&d, &c, &g);
    g.load = 150.0;
    (void)run(&d, &c, &g, 400u, 0u, 0u, 0);
    assert(d.integ1000 != 0L);
    in = in_of(&g, 0u);
    in.rpm = 0u;
    (void)hcidle_step(&d, &c, &in, DT);
    assert(d.integ1000 == 0L && d.trim_x10 == 0 && d.run_ms == 0u);
    printf("engine stop: trim and post-start timer reset\n");
}

static unsigned long seed = 7u;
static unsigned int rnd16(void)
{
    seed = seed * 1103515245UL + 12345UL;
    return (unsigned int)((seed >> 8) & 0xFFFFu);
}

static void test_fuzz(void)
{
    hcidle_t d;
    unsigned int k;
    hcidle_reset(&d);
    for (k = 0u; k < 200000u; k++) {
        hcidle_cfg_t c;
        hcidle_in_t in;
        unsigned int pos;
        c.enabled = (unsigned char)((rnd16() & 7u) != 0u);
        c.kp = rnd16(); c.ki = rnd16(); c.range_x10 = rnd16();
        c.band_rpm = rnd16(); c.pedal_x10 = rnd16() & 0x3FFu; c.start_ms = rnd16() & 0x7FFu;
        in.rpm = rnd16(); in.target_rpm = rnd16(); in.base_x10 = rnd16();
        in.pedal_x10 = rnd16() & 0x3FFu; in.cranking = (unsigned char)((rnd16() & 15u) == 0u);
        pos = hcidle_step(&d, &c, &in, rnd16() & 0xFFu);
        assert(pos <= 1000u);
        {
            int r = c.range_x10 > 1000u ? 1000 : (int)c.range_x10;
            assert(d.trim_x10 >= -r && d.trim_x10 <= r);
        }
    }
    printf("fuzz: 200000 random steps, position 0..1000 and trim within authority\n");
}

/* ------------------------------------------------ idle ignition timing -- */
static hcidle_tcfg_t tcfg(void)
{
    hcidle_tcfg_t c;
    c.enabled = 1u;
    c.kp_x10 = 100u;       /* rusEFI default 0.1 deg/rpm = 10 deg per 100 rpm */
    c.min_x10 = -100;
    c.max_x10 = 100;
    c.soft_ms = 0u;
    return c;
}

static void test_timing_basic(void)
{
    hcidle_tcfg_t c = tcfg();
    hcidle_timing_t t;
    memset(&t, 0, sizeof t);
    assert(hcidle_timing_step(&t, &c, 1u, 800u, 800u, DT) == 0);
    assert(hcidle_timing_step(&t, &c, 1u, 750u, 800u, DT) == 50);    /* 5.0 adv */
    assert(hcidle_timing_step(&t, &c, 1u, 830u, 800u, DT) == -30);   /* 3.0 ret */
    assert(hcidle_timing_step(&t, &c, 1u, 500u, 800u, DT) == 100);   /* max */
    assert(hcidle_timing_step(&t, &c, 1u, 1500u, 800u, DT) == -100); /* min */
    assert(t.closed_ms == 5u * DT);
    /* only in closed-loop idle, and nothing when disabled */
    assert(hcidle_timing_step(&t, &c, 0u, 700u, 800u, DT) == 0 && t.closed_ms == 0u);
    c.enabled = 0u;
    assert(hcidle_timing_step(&t, &c, 1u, 700u, 800u, DT) == 0);
    /* a misconfigured limit never flips the sign */
    c = tcfg(); c.max_x10 = -20; c.min_x10 = 20;
    assert(hcidle_timing_step(&t, &c, 1u, 700u, 800u, DT) == 0);
    assert(hcidle_timing_step(&t, &c, 1u, 900u, 800u, DT) == 0);
    printf("idle timing: P 10 deg/100 rpm, +-10 deg, closed loop only\n");
}

static void test_timing_soft(void)
{
    hcidle_tcfg_t c = tcfg();
    hcidle_timing_t t;
    int a, b, z = 0;
    unsigned int k;
    memset(&t, 0, sizeof t);
    c.soft_ms = 1000u;
    a = hcidle_timing_step(&t, &c, 1u, 750u, 800u, DT);            /* 20 ms in */
    for (k = 0u; k < 23u; k++) (void)hcidle_timing_step(&t, &c, 1u, 750u, 800u, DT);
    b = hcidle_timing_step(&t, &c, 1u, 750u, 800u, DT);            /* 500 ms */
    for (k = 0u; k < 30u; k++) z = hcidle_timing_step(&t, &c, 1u, 750u, 800u, DT);
    printf("idle timing soft entry 1 s: %d / %d / %d (0.1 deg)\n", a, b, z);
    assert(a == 1 && b == 25 && z == 50);
    /* leaving closed loop restarts the ramp */
    (void)hcidle_timing_step(&t, &c, 0u, 750u, 800u, DT);
    assert(hcidle_timing_step(&t, &c, 1u, 750u, 800u, DT) == 1);
}

/* the AC load step with the timing term: the engine answers spark within a
   cycle (15 rpm per degree here, no transport delay), so the dip is smaller
   than with the throttle alone */
static double ac_dip(int use_timing)
{
    hcidle_cfg_t c = cfg();
    hcidle_tcfg_t tc = tcfg();
    hcidle_t d;
    hcidle_timing_t t;
    eng_t g;
    unsigned int k;
    double mn = 1e9, adv = 0.0;
    memset(&t, 0, sizeof t);
    settle(&d, &c, &g);
    g.load = 150.0;
    for (k = 0u; k < 250u; k++) {
        hcidle_in_t in = in_of(&g, 0u);
        unsigned int pos = hcidle_step(&d, &c, &in, DT);
        double eq;
        if (use_timing)
            adv = hcidle_timing_step(&t, &tc, (unsigned char)(d.state & HCIDLE_S_CLOSED),
                                     in.rpm, in.target_rpm, DT) / 10.0;
        g.hist[2] = g.hist[1]; g.hist[1] = g.hist[0]; g.hist[0] = pos / 10.0;
        eq = 130.0 * g.hist[2] - g.load + 15.0 * adv;
        if (eq < 0.0) eq = 0.0;
        g.rpm += (eq - g.rpm) * (DT / 300.0);
        if (g.rpm < mn) mn = g.rpm;
    }
    return mn;
}

static void test_timing_load_step(void)
{
    double without = ac_dip(0), with = ac_dip(1);
    printf("AC step: lowest %.1f rpm throttle only, %.1f with idle timing\n", without, with);
    assert(with > without + 15.0);
}

static void test_timing_fuzz(void)
{
    hcidle_timing_t t;
    unsigned int k;
    memset(&t, 0, sizeof t);
    for (k = 0u; k < 200000u; k++) {
        hcidle_tcfg_t c;
        int o, lo, hi;
        c.enabled = (unsigned char)((rnd16() & 7u) != 0u);
        c.kp_x10 = rnd16(); c.soft_ms = rnd16() & 0x1FFFu;
        c.min_x10 = (int)(rnd16() & 0x3FFu) - 700; c.max_x10 = (int)(rnd16() & 0x3FFu) - 300;
        o = hcidle_timing_step(&t, &c, (unsigned char)(rnd16() & 1u), rnd16(), rnd16(),
                               rnd16() & 0xFFu);
        lo = c.min_x10 < 0 ? c.min_x10 : 0;
        hi = c.max_x10 > 0 ? c.max_x10 : 0;
        assert(o >= lo && o <= hi && o >= -5000 && o <= 5000);
    }
    printf("idle timing fuzz: 200000 steps inside [min, max]\n");
}


/* ---------------------------------------------------------- dashpot -- */
/* 25 % pedal for 2 s, then released; returns the lowest rpm after release
   and records the states seen */
static double dash_run(unsigned int dash_x10, unsigned char *saw_dash,
                       double *floor_at_500ms, double *final_rpm)
{
    hcidle_cfg_t c = cfg();
    hcidle_t d;
    eng_t g;
    unsigned int k;
    double mn = 1e9;
    c.dash_x10 = dash_x10;
    c.dash_hold_ms = 1000u;
    c.dash_decay_ms = 2000u;
    settle(&d, &c, &g);
    (void)run(&d, &c, &g, 100u, 250u, 0u, 0);          /* 2 s at 25 % pedal */
    *saw_dash = 0u;
    for (k = 0u; k < 500u; k++) {                      /* 10 s released */
        hcidle_in_t in = in_of(&g, 0u);
        unsigned int pos = hcidle_step(&d, &c, &in, DT);
        if (d.state == HCIDLE_S_DASH) *saw_dash = 1u;
        if (k == 24u) *floor_at_500ms = pos;
        eng_step(&g, pos / 10.0);
        if (g.rpm < mn) mn = g.rpm;
    }
    *final_rpm = g.rpm;
    return mn;
}

static void test_dashpot(void)
{
    hcidle_cfg_t c = cfg();
    hcidle_t d;
    hcidle_in_t in;
    eng_t g;
    unsigned char saw0, saw1;
    double f0 = 0.0, f1 = 0.0, fin0, fin1;
    double lo0 = dash_run(0u, &saw0, &f0, &fin0);
    double lo1 = dash_run(30u, &saw1, &f1, &fin1);
    unsigned int k, a, b, e;
    printf("dashpot 3.0 %% hold 1 s decay 2 s: release lowest %.1f rpm (off: %.1f), "
           "floor at 0.5 s %.0f (off %.0f), final %.1f\n", lo1, lo0, f1, f0, fin1);
    assert(!saw0 && saw1);
    assert(f1 >= f0 + 25.0);                 /* the adder is in the floor */
    assert(lo1 >= lo0);
    assert(fin1 > 785.0 && fin1 < 815.0);    /* back to target after decay */

    /* the shape, open loop: full through the hold, half way through the
       decay at half its time, 0 after */
    c.dash_x10 = 40u; c.dash_hold_ms = 1000u; c.dash_decay_ms = 2000u;
    c.band_rpm = 0u;                         /* rpm above target: no loop */
    settle(&d, &c, &g);
    in = in_of(&g, 250u);
    (void)hcidle_step(&d, &c, &in, DT);      /* pedal: armed */
    in.pedal_x10 = 0u; in.rpm = 1500u;
    for (k = 0u; k < 25u; k++) a = hcidle_step(&d, &c, &in, DT);        /* 0.5 s */
    for (k = 0u; k < 75u; k++) b = hcidle_step(&d, &c, &in, DT);        /* 2.0 s */
    for (k = 0u; k < 60u; k++) e = hcidle_step(&d, &c, &in, DT);        /* 3.2 s */
    printf("dashpot shape: %u / %u / %u over base+trim %d\n", a, b, e,
           65 + d.trim_x10);
    assert(a == (unsigned int)(65 + d.trim_x10 + 40));
    assert(b == (unsigned int)(65 + d.trim_x10 + 20));
    assert(e == (unsigned int)(65 + d.trim_x10) && d.state == HCIDLE_S_COAST);

    /* never right after a start: the engine has not been released from
       anything */
    hcidle_reset(&d);
    in = in_of(&g, 0u); in.rpm = 0u;
    (void)hcidle_step(&d, &c, &in, DT);                  /* stopped */
    in.cranking = 1u; in.rpm = 200u;
    (void)hcidle_step(&d, &c, &in, DT);
    in.cranking = 0u; in.rpm = 900u;
    for (k = 0u; k < 100u; k++) {
        (void)hcidle_step(&d, &c, &in, DT);
        assert(d.state != HCIDLE_S_DASH);
    }
    printf("dashpot: not after a start, only after a release\n");
}

/* 2026-10-15, car: a positive trim wound to its limit (a stumbling cold
   engine) must not hold the throttle open once the engine is above target +
   band with the pedal released - rusEFI applies no closed-loop correction
   outside idling. The I is kept and unwinds on the way back. */
static void test_no_air_above_band(void)
{
    hcidle_cfg_t c = cfg();
    hcidle_t d;
    eng_t g;
    hcidle_in_t in;
    unsigned int floor_x10;
    double mn, mx;
    settle(&d, &c, &g);
    d.integ1000 = (long)c.range_x10 * 1000L;           /* wound to +5 % */
    d.i_x10 = (int)c.range_x10;
    g.rpm = 4000.0;                                  /* ran away */
    in = in_of(&g, 0u);
    floor_x10 = hcidle_step(&d, &c, &in, DT);
    assert(floor_x10 <= in.base_x10 && d.state == HCIDLE_S_COAST);
    assert(d.integ1000 > 0L);                         /* kept, not applied */
    mn = run(&d, &c, &g, 750u, 0u, 0u, &mx);         /* 15 s, pedal released */
    printf("wound +5 %% trim at 4000 rpm, pedal released: floor = base above the band, "
           "lowest %.1f rpm, final %.1f\n", mn, g.rpm);
    assert(g.rpm > 785.0 && g.rpm < 815.0);
    assert(mn > 700.0);
}

int main(void)
{
    test_states();
    test_converge();
    test_load_step();
    test_blip_and_coast();
    test_coast_in_gear();
    test_limit();
    test_no_air_above_band();
    test_stop_resets();
    test_fuzz();
    test_timing_basic();
    test_timing_soft();
    test_timing_load_step();
    test_timing_fuzz();
    test_dashpot();
    printf("hcidle: ALL PASS\n");
    return 0;
}
