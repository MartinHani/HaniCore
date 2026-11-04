/*
 * test_hccan.c - prints the VAG engine payloads hccan.c builds for a set of
 * engine states, one line per frame: "<scenario> <frame> <16 hex digits>".
 * tests/host/test_hccan_host.py decodes every line with the opendbc
 * vw_pq.dbc (an independent description of the same bits) and checks the
 * values against the scenario. This file only drives and prints.
 */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "hccan.h"

static void hex(const char *sc, const char *fr, const unsigned char *d)
{
    int i;
    printf("%s %s ", sc, fr);
    for (i = 0; i < 8; i++) {
        printf("%02X", d[i]);
    }
    printf("\n");
}

static void scenario(const char *sc, const hccan_eng_t *e,
                     const hccan_vag_id_t *id)
{
    hccan_vag_state_t s;
    unsigned char d[8];
    int i;
    char nm[8];

    hccan_vag_reset(&s);
    hccan_motor1(e, id, d);
    hex(sc, "M1", d);
    hccan_motor3(e, d);
    hex(sc, "M3", d);
    for (i = 0; i < 16; i++) {          /* a full multiplex round each      */
        sprintf(nm, "M2_%02d", i);
        hccan_motor2(&s, e, id, d);
        hex(sc, nm, d);
    }
    for (i = 0; i < 16; i++) {
        sprintf(nm, "M6_%02d", i);
        hccan_motor6(&s, e, id, 950u, d);
        hex(sc, nm, d);
    }
    for (i = 0; i < 16; i++) {
        sprintf(nm, "M5_%02d", i);
        hccan_fuel_add(&s, 2500u);
        hccan_motor5(&s, e, id, d);
        hex(sc, nm, d);
    }
}

/* receive mode: test_hccan <message> <16 hex digits> -> "key=value" lines */
static int rx(const char *msg, const char *hx)
{
    unsigned char d[8];
    int i;
    for (i = 0; i < 8; i++) {
        char b[3];
        b[0] = hx[2 * i]; b[1] = hx[2 * i + 1]; b[2] = 0;
        d[i] = (unsigned char)strtoul(b, 0, 16);
    }
    if (!strcmp(msg, "bremse1")) {
        hccan_bremse1_t o;
        hccan_rx_bremse1(d, &o);
        printf("vss_x10=%u brake=%u asr_req=%u msr_req=%u esp_off=%u asr_slow=%u asr_fast=%u msr=%u counter=%u\n",
               o.vss_x10, o.brake, o.asr_req, o.msr_req, o.esp_off, o.asr_slow, o.asr_fast, o.msr, o.counter);
    } else if (!strcmp(msg, "bremse3")) {
        unsigned int w[4];
        hccan_rx_bremse3(d, w);
        printf("fl=%u fr=%u rl=%u rr=%u\n", w[0], w[1], w[2], w[3]);
    } else if (!strcmp(msg, "getriebe1")) {
        hccan_getriebe1_t o;
        hccan_rx_getriebe1(d, &o);
        printf("gear=%u selector=%u tq_valid=%u tq_req=%u ac_off=%u cooling=%u mil=%u\n",
               o.gear, o.selector, o.tq_valid, o.tq_req, o.ac_off, o.cooling, o.mil);
    } else if (!strcmp(msg, "kombi1")) {
        hccan_kombi1_t o;
        hccan_rx_kombi1(d, &o);
        printf("vss_x10=%u fuel_l=%u fuel_low=%u\n", o.vss_x10, o.fuel_l, o.fuel_low);
    } else if (!strcmp(msg, "kombi2")) {
        unsigned int a, o;
        hccan_rx_kombi2(d, &a, &o);
        printf("amb_dc=%u oil_dc=%u\n", a, o);
    } else if (!strcmp(msg, "airbag1")) {
        printf("crash=%u\n", hccan_rx_airbag1(d));
    } else if (!strcmp(msg, "klima1")) {
        hccan_klima1_t o;
        hccan_rx_klima1(d, &o);
        printf("idle_up=%u compressor=%u load_x4=%u fan_x4=%u\n", o.idle_up, o.compressor, o.load_x4, o.fan_x4);
    } else {
        return 2;
    }
    return 0;
}

int main(int argc, char **argv)
{
    hccan_vag_id_t id;
    hccan_eng_t e;

    if (argc == 3) {
        return rx(argv[1], argv[2]);
    }

    /* the stock 1.8T identity (24HGCM8g A2L) */
    id.canvers = 10u; id.fmotc = 34u; id.cwgc = 15u; id.mottyp = 4u;
    id.mdnorm_nm = 400u; id.mdmax_nm = 230u; id.nmdmax_rpm = 2000u;
    id.kvnpz = 780u;

    /* A: warm idle */
    e.rpm = 850u; e.clt_dc = (unsigned int)((90 + 1000) * 10);
    e.iat_dc = (unsigned int)((30 + 1000) * 10); e.pedal_x10 = 0u;
    e.tps_x10 = 26u; e.rl_x10 = 180u; e.idle_rpm = 850u; e.vss_x10 = 0u;
    e.fan_pct = 0u;
    e.flags = HCCAN_F_IDLE | HCCAN_F_RUNNING;
    scenario("A", &e, &id);

    /* B: 4250 rpm, half pedal, MIL + EPC + hot, fan 50 % */
    e.rpm = 4250u; e.clt_dc = (unsigned int)((112 + 1000) * 10);
    e.iat_dc = (unsigned int)((45 + 1000) * 10); e.pedal_x10 = 500u;
    e.tps_x10 = 400u; e.rl_x10 = 1200u; e.idle_rpm = 850u; e.vss_x10 = 0u;
    e.fan_pct = 50u;
    e.flags = HCCAN_F_RUNNING | HCCAN_F_MIL | HCCAN_F_EPC | HCCAN_F_HOT;
    scenario("B", &e, &id);

    /* C: key on, engine stopped, cold, sensors faulty */
    e.rpm = 0u; e.clt_dc = (unsigned int)((-10 + 1000) * 10);
    e.iat_dc = (unsigned int)((-10 + 1000) * 10); e.pedal_x10 = 0u;
    e.tps_x10 = 0u; e.rl_x10 = 0u; e.idle_rpm = 1200u; e.vss_x10 = 0u;
    e.fan_pct = 0u;
    e.flags = HCCAN_F_STOPPED | HCCAN_F_CLT_BAD | HCCAN_F_IAT_BAD
            | HCCAN_F_PEDAL_BAD | HCCAN_F_TPS_BAD | HCCAN_F_NO_DBW;
    scenario("C", &e, &id);
    return 0;
}
