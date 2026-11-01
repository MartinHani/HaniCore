/*
 * test_hccc650.c - host test for the CC650 core (hccc650.c, ME7.5 DC),
 * gcc -std=c89. Run by tests/host/test_hccc650_host.py.
 *
 * A BUS model records every byte write into a 256-byte register file and a
 * log; the assertions compare the log with the stock 4B0906018DC sequences
 * and the register file with the expected output levels.
 */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "hccc650.h"

static unsigned char regs[256];
static unsigned char log_reg[512], log_val[512];
static unsigned int nlog;

static void bus_reset(void) { memset(regs, 0xEE, sizeof regs); nlog = 0u; }

static unsigned int pump(hccc650_t *c, unsigned int calls)
{
    unsigned int k, n = 0u;
    unsigned char r, v;
    for (k = 0u; k < calls; k++) {
        if (!hccc650_next(c, &r, &v)) break;
        regs[r] = v;
        if (nlog < sizeof log_reg) { log_reg[nlog] = r; log_val[nlog] = v; nlog++; }
        n++;
    }
    return n;
}

static void test_boot_and_setup(void)
{
    /* the stock order: boot 0x096D3C, then setup 0x070960 */
    static const unsigned char want[][2] = {
        {0x02,0x00},{0x26,0x4A},{0x2A,0xFF},{0x2B,0xFF},{0x02,0x20},
        {0x3A,0xDF},{0x38,0xFF},{0x40,0x05},{0x3E,0xF1},{0x46,0x00},
        {0x44,0x00},{0x30,0x00},{0x32,0x00},
        {0x34,0x83},{0x64,0x00},{0x5E,0x04},{0x54,0x01},{0x55,0x00},
        {0x56,0x00},{0x52,0x02}
    };
    hccc650_t c; unsigned int i, n = sizeof want / sizeof want[0];
    bus_reset();
    hccc650_init(&c, 0xF1u);
    assert(pump(&c, n) == n);
    for (i = 0u; i < n; i++)
        assert(log_reg[i] == want[i][0] && log_val[i] == want[i][1]);
    assert(c.phase == HCCC650_PH_RUN);
    assert(regs[0x02] == 0x20u);                       /* mode on          */
    printf("  boot + setup: %u writes in the stock order and values: OK\n", n);
}

static void test_outputs_and_refresh(void)
{
    hccc650_t c; unsigned int i; int seen[256];
    bus_reset();
    hccc650_init(&c, 0x01u);
    pump(&c, 20u);
    assert(regs[0x3A] == 0xDFu);                       /* all active-low off */
    hccc650_out(&c, HCCC650_OUT_MIL, 1u);
    hccc650_out(&c, HCCC650_OUT_N205, 1u);
    hccc650_out(&c, HCCC650_OUT_FAN, 0u);
    nlog = 0u;
    pump(&c, 1u);                                      /* dirty goes first  */
    assert(log_reg[0] == 0x3Au && log_val[0] == (0xDFu & ~0x08u & ~0x10u & ~0x80u));
    hccc650_out(&c, HCCC650_OUT_MIL, 0u);
    hccc650_out(&c, HCCC650_OUT_SAP, 1u);
    hccc650_out(&c, HCCC650_OUT_LSU_CAL, 1u);
    hccc650_out(&c, HCCC650_OUT_RUNON, 1u);
    pump(&c, 4u);
    assert((regs[0x3A] & 0x08u) == 0x08u);             /* MIL off again     */
    assert((regs[0x40] & 0x01u) == 0x00u);             /* SAP on = LOW      */
    assert((regs[0x46] & 0x01u) == 0x01u);             /* LA high           */
    assert((regs[0x44] & 0x04u) == 0x04u);             /* keep-alive        */
    /* no change -> no dirty write; refresh visits every shadow */
    memset(seen, 0, sizeof seen);
    nlog = 0u;
    pump(&c, 2u * HCCC650_N_SH);
    for (i = 0u; i < nlog; i++) seen[log_reg[i]] = 1;
    assert(seen[0x3A] && seen[0x38] && seen[0x40] && seen[0x3E] &&
           seen[0x46] && seen[0x44] && seen[0x30] && seen[0x34]);
    printf("  outputs: polarity per bit, dirty first, refresh covers all 8: OK\n");
}

static void test_knock_and_shutdown(void)
{
    hccc650_t c; unsigned int n;
    bus_reset();
    hccc650_init(&c, 0x01u);
    pump(&c, 20u);
    hccc650_knock(&c, 3u, 2u);
    pump(&c, 1u);
    assert(regs[0x34] == (0x80u | (2u << 4) | 3u));
    hccc650_out(&c, HCCC650_OUT_RUNON, 1u);
    pump(&c, 1u);
    hccc650_shutdown(&c);
    nlog = 0u;
    n = pump(&c, 10u);
    assert(n == 2u);                                   /* then silence      */
    assert(log_reg[0] == 0x44u && log_val[0] == 0x00u);
    assert(log_reg[1] == 0x02u && log_val[1] == 0x00u);
    hccc650_out(&c, HCCC650_OUT_RUNON, 1u);            /* ignored now       */
    assert(pump(&c, 5u) == 0u && c.phase == HCCC650_PH_DEAD);
    printf("  knock band/gain byte; shutdown 44=00 then 02=00, then silent: OK\n");
}

static void test_baro(void)
{
    unsigned int b;
    /* stock law: byte x 4 x 16221 / 13107 (DSUGRAD, DSUOFS 0) */
    for (b = 0u; b <= 255u; b++) {
        unsigned long exact = (unsigned long)(b * 4u) * 16221uL / 13107uL;
        unsigned int got = hccc650_baro_hpa((unsigned char)b);
        long d = (long)got - (long)exact;
        assert(d >= -2 && d <= 2);
    }
    assert(hccc650_baro_hpa(205u) >= 1012u && hccc650_baro_hpa(205u) <= 1016u);
    printf("  baro: within 2 hPa of the stock law over 0..255 (205 -> ~1014 hPa): OK\n");
}

int main(void)
{
    printf("hccc650 host tests\n");
    test_boot_and_setup();
    test_outputs_and_refresh();
    test_knock_and_shutdown();
    test_baro();
    printf("all hccc650 tests passed\n");
    return 0;
}
