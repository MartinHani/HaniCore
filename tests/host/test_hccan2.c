/* test_hccan2.c - stdin driver for the 2026-11-04 additions of
 * firmware/comms/hccan.c (tests/host/test_hccan2_host.py):
 *   b1 <vss_x10> <brake> <ctr>        -> 8 bytes hex
 *   b3 <w1> <w2> <w3> <w4>            -> 8 bytes hex
 *   al <16 hex chars>                 -> lock_x10 status
 *   wbr <16 hex> / wba <16 hex>       -> lambda x1000
 *   hxr                               (reset the Haldex integrator)
 *   hx <want> <act> <ok> <no> <full> <kp> <ki> <db> <dt> -> offset_x10
 *   obd <pid> <rpm> <vss> <clt> <iat> <map> <baro> <tps> <adv> <load>
 *       <lam> <vbat> <run> <mil> <ndtc>  -> len then hex
 */
#include <stdio.h>
#include <string.h>
#include "hccan.h"

static void hexin(const char *s, unsigned char *d)
{
    unsigned int i, v;
    for (i = 0; i < 8; i++) {
        sscanf(s + 2 * i, "%2x", &v);
        d[i] = (unsigned char)v;
    }
}

static void hexout(const unsigned char *d, unsigned int n)
{
    unsigned int i;
    for (i = 0; i < n; i++) printf("%02x", d[i]);
    printf("\n");
}

int main(void)
{
    char cmd[16], hx[40];
    unsigned char d[8];
    hccan_hx_t h;
    hccan_hx_reset(&h);
    while (scanf("%15s", cmd) == 1) {
        if (!strcmp(cmd, "b1")) {
            unsigned int v, b, c;
            if (scanf("%u %u %u", &v, &b, &c) != 3) return 2;
            hccan_tx_bremse1(v, (unsigned char)b, (unsigned char)c, d);
            hexout(d, 8);
        } else if (!strcmp(cmd, "b3")) {
            unsigned int w[4];
            if (scanf("%u %u %u %u", &w[0], &w[1], &w[2], &w[3]) != 4) return 2;
            hccan_tx_bremse3(w, d);
            hexout(d, 8);
        } else if (!strcmp(cmd, "al")) {
            unsigned int lk; unsigned char st;
            if (scanf("%39s", hx) != 1) return 2;
            hexin(hx, d);
            hccan_rx_allrad1(d, &lk, &st);
            printf("%u %u\n", lk, st);
        } else if (!strcmp(cmd, "wbr") || !strcmp(cmd, "wba")) {
            if (scanf("%39s", hx) != 1) return 2;
            hexin(hx, d);
            printf("%u\n", cmd[2] == 'r' ? hccan_rx_wb_rusefi(d) : hccan_rx_wb_aem(d));
        } else if (!strcmp(cmd, "hxr")) {
            hccan_hx_reset(&h);
        } else if (!strcmp(cmd, "hx")) {
            unsigned int w, a, ok, no, fu, kp, ki, db, dt;
            if (scanf("%u %u %u %u %u %u %u %u %u", &w, &a, &ok, &no, &fu, &kp, &ki, &db, &dt) != 9) return 2;
            printf("%u\n", hccan_hx_offset(&h, w, a, (unsigned char)ok, no, fu,
                                           (unsigned char)kp, (unsigned char)ki,
                                           (unsigned char)db, dt));
        } else if (!strcmp(cmd, "obd")) {
            unsigned int pid, rpm, vss, clt, iat, map, baro, tps, load, lam, vb, run, mil, nd;
            int adv;
            hccan_obd_t o;
            unsigned char out[8], n;
            if (scanf("%u %u %u %u %u %u %u %u %d %u %u %u %u %u %u", &pid, &rpm, &vss,
                      &clt, &iat, &map, &baro, &tps, &adv, &load, &lam, &vb, &run,
                      &mil, &nd) != 15) return 2;
            o.rpm = rpm; o.vss_x10 = vss; o.clt_dc = clt; o.iat_dc = iat;
            o.map_x10 = map; o.baro_x10 = baro; o.tps_x10 = tps; o.adv_x10 = adv;
            o.load_x10 = load; o.lam_x1000 = lam; o.vbat_mv = vb; o.run_s = run;
            o.mil = (unsigned char)mil; o.n_dtc = (unsigned char)nd;
            n = hccan_obd_pid((unsigned char)pid, &o, out);
            printf("%u ", n);
            hexout(out, n);
        } else {
            return 3;
        }
        fflush(stdout);
    }
    return 0;
}
