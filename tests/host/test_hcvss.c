/* test_hcvss.c - stdin driver for firmware/sensors/hcvss.c
 * (tests/host/test_hcvss_host.py). One command per line:
 *   reset <n>
 *   k <pulses per km>                 -> prints k
 *   step <n> <ms_edge> <now> <k> <filt> <tmo>  -> prints the speed
 *   v1000 <vss_x10> <rpm>             -> prints speed per 1000 rpm
 *   gear <vss_x10> <rpm> <band> <min_x10> <n> <g1> ... <gn> -> prints gear
 * The gear state persists between gear commands (hold band). */
#include <stdio.h>
#include <string.h>
#include "hcvss.h"

int main(void)
{
    char cmd[32];
    hcvss_state_t s;
    hcvss_reset(&s, 0u);
    while (scanf("%31s", cmd) == 1) {
        if (strcmp(cmd, "reset") == 0) {
            unsigned int n;
            if (scanf("%u", &n) != 1) return 2;
            hcvss_reset(&s, n);
        } else if (strcmp(cmd, "k") == 0) {
            unsigned int p;
            if (scanf("%u", &p) != 1) return 2;
            printf("%u\n", hcvss_k(p));
        } else if (strcmp(cmd, "step") == 0) {
            unsigned int n, me, now, k, f, t;
            if (scanf("%u %u %u %u %u %u", &n, &me, &now, &k, &f, &t) != 6) return 2;
            printf("%u\n", hcvss_step(&s, n & 0xFFFFu, me & 0xFFFFu, now & 0xFFFFu,
                                      k, (unsigned char)f, t));
        } else if (strcmp(cmd, "v1000") == 0) {
            unsigned int v, r;
            if (scanf("%u %u", &v, &r) != 2) return 2;
            printf("%u\n", hcvss_v1000(v, r));
        } else if (strcmp(cmd, "gear") == 0) {
            unsigned int v, r, b, mn, n, i, g[8];
            if (scanf("%u %u %u %u %u", &v, &r, &b, &mn, &n) != 5 || n > 8) return 2;
            for (i = 0; i < n; i++) {
                if (scanf("%u", &g[i]) != 1) return 2;
            }
            printf("%u\n", hcvss_gear(&s, v, r, g, (unsigned char)n,
                                      (unsigned char)b, mn));
        } else {
            return 3;
        }
        fflush(stdout);
    }
    return 0;
}
