/*
 * hclimp.c - engine protection decisions. Read hclimp.h first; the proof is
 * tests/host/test_hclimp.c (tools/test_hclimp_host.py, with the Keil
 * no-helper check). 16-bit arithmetic only.
 */
#include "hclimp.h"

static unsigned int add_sat(unsigned int a, unsigned int b)
{
    return (a > 65535u - b) ? 65535u : (unsigned int)(a + b);
}

void HCLIMP_FAR hclimp_reset(hclimp_t *l)
{
    l->cut = 0u;
    l->run_ms = 0u;
    l->low_ms = 0u;
    l->sust_ms = 0u;
    l->had_oil = 0u;
}

/* a fuel cut above lim that returns HCLIMP_HYST_RPM below it */
static unsigned char rev_cut(unsigned char was, unsigned int rpm, unsigned int lim)
{
    if (rpm > lim) return 1u;
    if (was && (unsigned long)rpm + HCLIMP_HYST_RPM >= (unsigned long)lim) return 1u;
    return 0u;
}

unsigned char HCLIMP_FAR hclimp_step(hclimp_t *l, const hclimp_cfg_t *c,
                                     const hclimp_in_t *in, unsigned int ms)
{
    unsigned char cut = 0u;
    unsigned char running = (unsigned char)(in->rpm != 0u && !in->cranking);

    /* coolant: the rev limit drops while hot */
    if (c->clt_max_x10 != 0 && in->clt_ok && in->clt_x10 > c->clt_max_x10
        && rev_cut((unsigned char)(l->cut & HCLIMP_CLT), in->rpm, c->clt_rpm))
        cut |= HCLIMP_CLT;

    /* ETB fault: the fault rev limit */
    if (c->etb_rpm != 0u && in->etb_fault
        && rev_cut((unsigned char)(l->cut & HCLIMP_ETB), in->rpm, c->etb_rpm))
        cut |= HCLIMP_ETB;

    /* oil: latched until the engine stops */
    if (in->rpm == 0u) {
        l->run_ms = 0u;
        l->low_ms = 0u;
        l->had_oil = 0u;
    } else if (running) {
        l->run_ms = add_sat(l->run_ms, ms);
        if (c->oil_min_kpa != 0u && in->oil_ok) {
            if (in->oil_kpa > c->oil_min_kpa) l->had_oil = 1u;
            if (!l->had_oil && l->run_ms > c->oil_start_ms)
                cut |= HCLIMP_OIL;
            if (in->rpm > c->oil_rpm && in->oil_kpa <= c->oil_min_kpa)
                l->low_ms = add_sat(l->low_ms, ms);
            else
                l->low_ms = 0u;
            if (l->had_oil && l->low_ms >= c->oil_ms && c->oil_ms != 0u)
                cut |= HCLIMP_OIL;
        }
    }
    if (l->cut & HCLIMP_OIL && in->rpm != 0u) cut |= HCLIMP_OIL;

    /* injector duty: instant or sustained, released below 20 % */
    {
        unsigned char trip = 0u;
        if (c->duty_sust_x10 != 0u && in->duty_x10 > c->duty_sust_x10)
            l->sust_ms = add_sat(l->sust_ms, ms);
        else
            l->sust_ms = 0u;
        if (c->duty_inst_x10 != 0u && in->duty_x10 > c->duty_inst_x10) trip = 1u;
        if (c->duty_sust_x10 != 0u && l->sust_ms >= c->duty_sust_ms && l->sust_ms) trip = 1u;
        if (trip || ((l->cut & HCLIMP_DUTY) && in->duty_x10 >= 200u))
            cut |= HCLIMP_DUTY;
    }

    /* flood clear: cranking with the pedal floored */
    if (c->flood_x10 != 0u && !running && in->pedal_x10 > c->flood_x10)
        cut |= HCLIMP_FLOOD;

    l->cut = cut;
    return cut;
}
