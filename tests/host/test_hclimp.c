/*
 * test_hclimp.c - the engine protection core (hclimp.c), gcc -std=c89.
 * Run by tools/test_hclimp_host.py (negative controls + Keil helper check).
 */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "hclimp.h"

static hclimp_cfg_t cfg(void)
{
    hclimp_cfg_t c;
    memset(&c, 0, sizeof c);
    c.clt_max_x10 = 1150;         /* 115 C */
    c.clt_rpm = 3000u;
    c.etb_rpm = 1500u;            /* rusEFI reportEtbJammed */
    c.oil_min_kpa = 100u;
    c.oil_rpm = 1500u;
    c.oil_ms = 500u;
    c.oil_start_ms = 5000u;
    c.duty_inst_x10 = 960u;       /* rusEFI defaults 96 / 90 % for 1 s */
    c.duty_sust_x10 = 900u;
    c.duty_sust_ms = 1000u;
    c.flood_x10 = 900u;
    return c;
}

static hclimp_in_t base(void)
{
    hclimp_in_t in;
    memset(&in, 0, sizeof in);
    in.rpm = 2500u; in.clt_x10 = 900; in.clt_ok = 1u;
    in.oil_kpa = 300u; in.oil_ok = 1u; in.duty_x10 = 300u;
    return in;
}

static unsigned char step(hclimp_t *l, const hclimp_cfg_t *c, const hclimp_in_t *in, unsigned int ms)
{
    return hclimp_step(l, c, in, ms);
}

static void test_clt(void)
{
    hclimp_cfg_t c = cfg();
    hclimp_t l;
    hclimp_in_t in = base();
    hclimp_reset(&l);
    in.clt_x10 = 1160; in.rpm = 2900u;
    assert(step(&l, &c, &in, 10u) == 0u);             /* hot, below the limp rpm */
    in.rpm = 3001u; assert(step(&l, &c, &in, 10u) == HCLIMP_CLT);
    in.rpm = 2850u; assert(step(&l, &c, &in, 10u) == HCLIMP_CLT);   /* hysteresis */
    in.rpm = 2799u; assert(step(&l, &c, &in, 10u) == 0u);
    in.rpm = 5000u; in.clt_x10 = 1150; assert(step(&l, &c, &in, 10u) == 0u);  /* not above */
    in.clt_x10 = 1300; in.clt_ok = 0u; assert(step(&l, &c, &in, 10u) == 0u);  /* not judged */
    c.clt_max_x10 = 0; in.clt_ok = 1u; assert(step(&l, &c, &in, 10u) == 0u);  /* off */
    printf("coolant: rev limit 3000 above 115 C, 200 rpm hysteresis; a faulted sensor never trips\n");
}

static void test_etb(void)
{
    hclimp_cfg_t c = cfg();
    hclimp_t l;
    hclimp_in_t in = base();
    hclimp_reset(&l);
    in.etb_fault = 1u; in.rpm = 1400u;
    assert(step(&l, &c, &in, 10u) == 0u);
    in.rpm = 1600u; assert(step(&l, &c, &in, 10u) == HCLIMP_ETB);
    in.etb_fault = 0u; assert(step(&l, &c, &in, 10u) == 0u);
    printf("ETB fault: 1500 rpm fault rev limit (rusEFI reportEtbJammed)\n");
}

static void test_oil(void)
{
    hclimp_cfg_t c = cfg();
    hclimp_t l;
    hclimp_in_t in = base();
    unsigned int k;
    /* no pressure after start */
    hclimp_reset(&l);
    in.oil_kpa = 20u; in.rpm = 900u;
    for (k = 0u; k < 500u; k++) assert(step(&l, &c, &in, 10u) == 0u);   /* 5.0 s */
    assert(step(&l, &c, &in, 10u) == HCLIMP_OIL);
    in.oil_kpa = 300u;
    assert(step(&l, &c, &in, 10u) == HCLIMP_OIL);                          /* latched */
    in.rpm = 0u; assert(step(&l, &c, &in, 10u) == 0u);                     /* engine stop */
    /* pressure lost at speed */
    hclimp_reset(&l);
    in = base();
    for (k = 0u; k < 100u; k++) assert(step(&l, &c, &in, 10u) == 0u);
    in.oil_kpa = 80u; in.rpm = 1400u;                                      /* below oil_rpm */
    for (k = 0u; k < 200u; k++) assert(step(&l, &c, &in, 10u) == 0u);
    in.rpm = 3000u;
    for (k = 0u; k < 49u; k++) assert(step(&l, &c, &in, 10u) == 0u);      /* 490 ms */
    assert(step(&l, &c, &in, 10u) == HCLIMP_OIL);                          /* 500 ms */
    /* no sensor: never */
    hclimp_reset(&l);
    in = base(); in.oil_ok = 0u; in.oil_kpa = 0u;
    for (k = 0u; k < 2000u; k++) assert(step(&l, &c, &in, 10u) == 0u);
    printf("oil: none within 5 s of start -> cut; lost above 1500 rpm for 500 ms -> cut; "
           "latched to engine stop; no sensor never trips\n");
}

static void test_duty(void)
{
    hclimp_cfg_t c = cfg();
    hclimp_t l;
    hclimp_in_t in = base();
    unsigned int k;
    hclimp_reset(&l);
    in.duty_x10 = 970u; assert(step(&l, &c, &in, 10u) == HCLIMP_DUTY);     /* instant */
    in.duty_x10 = 500u; assert(step(&l, &c, &in, 10u) == HCLIMP_DUTY);     /* held */
    in.duty_x10 = 199u; assert(step(&l, &c, &in, 10u) == 0u);              /* < 20 % */
    in.duty_x10 = 920u;
    for (k = 0u; k < 99u; k++) assert(step(&l, &c, &in, 10u) == 0u);
    assert(step(&l, &c, &in, 10u) == HCLIMP_DUTY);                         /* 1.0 s */
    printf("injector duty: > 96 %% at once or > 90 %% for 1 s -> cut until below 20 %%\n");
}

static void test_flood(void)
{
    hclimp_cfg_t c = cfg();
    hclimp_t l;
    hclimp_in_t in = base();
    hclimp_reset(&l);
    in.cranking = 1u; in.rpm = 200u; in.pedal_x10 = 950u;
    assert(step(&l, &c, &in, 10u) == HCLIMP_FLOOD);
    in.pedal_x10 = 500u; assert(step(&l, &c, &in, 10u) == 0u);
    in.cranking = 0u; in.rpm = 3000u; in.pedal_x10 = 1000u;
    assert(step(&l, &c, &in, 10u) == 0u);                                  /* running */
    printf("flood clear: cranking with the pedal above 90 %% -> no fuel; never while running\n");
}

static unsigned long seed = 11u;
static unsigned int rnd16(void)
{
    seed = seed * 1103515245UL + 12345UL;
    return (unsigned int)((seed >> 8) & 0xFFFFu);
}

static void test_fuzz(void)
{
    hclimp_t l;
    unsigned int k;
    hclimp_reset(&l);
    for (k = 0u; k < 200000u; k++) {
        hclimp_cfg_t c;
        hclimp_in_t in;
        unsigned char r;
        c.clt_max_x10 = (int)rnd16(); c.clt_rpm = rnd16(); c.etb_rpm = rnd16();
        c.oil_min_kpa = rnd16() & 0x3FFu; c.oil_rpm = rnd16(); c.oil_ms = rnd16();
        c.oil_start_ms = rnd16(); c.duty_inst_x10 = rnd16() & 0x7FFu;
        c.duty_sust_x10 = rnd16() & 0x7FFu; c.duty_sust_ms = rnd16(); c.flood_x10 = rnd16() & 0x7FFu;
        in.rpm = rnd16(); in.cranking = (unsigned char)(rnd16() & 1u);
        in.clt_x10 = (int)rnd16(); in.clt_ok = (unsigned char)(rnd16() & 1u);
        in.oil_kpa = rnd16() & 0x3FFu; in.oil_ok = (unsigned char)(rnd16() & 1u);
        in.etb_fault = (unsigned char)(rnd16() & 1u); in.duty_x10 = rnd16() & 0x7FFu;
        in.pedal_x10 = rnd16() & 0x7FFu;
        r = hclimp_step(&l, &c, &in, rnd16() & 0xFFFu);
        assert(r == l.cut && (r & ~0x1Fu) == 0u);
    }
    printf("fuzz: 200000 random steps, only defined reason bits\n");
}

int main(void)
{
    test_clt();
    test_etb();
    test_oil();
    test_duty();
    test_flood();
    test_fuzz();
    printf("hclimp: ALL PASS\n");
    return 0;
}
