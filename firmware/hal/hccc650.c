/*
 * hccc650.c - CC650 bus ASIC core (ME7.5 DC). See hccc650.h. SFR-free.
 */
#include "hccc650.h"

static const unsigned char sh_reg[HCCC650_N_SH] = {
    0x3Au, 0x38u, 0x40u, 0x3Eu, 0x46u, 0x44u, 0x30u, 0x34u
};

/* boot (4B0906018DC 0x096D3C): mode off, configure, mode 0x20 */
static const unsigned char boot_seq[][2] = {
    { 0x02u, 0x00u }, { 0x26u, 0x4Au }, { 0x2Au, 0xFFu }, { 0x2Bu, 0xFFu },
    { 0x02u, 0x20u }
};
#define BOOT_N (sizeof boot_seq / sizeof boot_seq[0])

/* setup (0x070960) in the stock order: 3A 38 40 3E 46 44 30 32 34 64 5E 54
   55 56 52. SH(i) = shadow i (its current value), else { register, value }.
   (The 0x32 write sat after 0x34 until 2026-10-28: me75_dc_runtime_proof B.) */
#define SH(i) { (unsigned char)(0x80u | (i)), 0u }
static const unsigned char setup_seq[][2] = {
    SH(HCCC650_SH_3A), SH(HCCC650_SH_38), SH(HCCC650_SH_40), SH(HCCC650_SH_3E),
    SH(HCCC650_SH_46), SH(HCCC650_SH_44), SH(HCCC650_SH_30), { 0x32u, 0x00u },
    SH(HCCC650_SH_34), { 0x64u, 0x00u }, { 0x5Eu, 0x04u }, { 0x54u, 0x01u },
    { 0x55u, 0x00u }, { 0x56u, 0x00u }, { 0x52u, 0x02u }
};
#define SETUP_N (sizeof setup_seq / sizeof setup_seq[0])

/* output -> shadow, bit, active level */
static const unsigned char out_sh[HCCC650_N_OUT] = {
    HCCC650_SH_3A, HCCC650_SH_3A, HCCC650_SH_3A, HCCC650_SH_3A,
    HCCC650_SH_3A, HCCC650_SH_3A, HCCC650_SH_3A, HCCC650_SH_3A,
    HCCC650_SH_40, HCCC650_SH_46, HCCC650_SH_44
};
static const unsigned char out_bit[HCCC650_N_OUT] = {
    0x01u, 0x02u, 0x04u, 0x08u, 0x10u, 0x20u, 0x40u, 0x80u, 0x01u, 0x01u, 0x04u
};
static const unsigned char out_high[HCCC650_N_OUT] = {
    0u, 0u, 0u, 0u, 0u, 1u, 1u, 1u, 0u, 1u, 1u
};

void hccc650_init(hccc650_t *c, unsigned char setup_3e)
{
    /* the stock setup values (0x070960): every active-low output off,
       A/C cut and the fan bit as the stock writes them first */
    c->sh[HCCC650_SH_3A] = 0xDFu;
    c->sh[HCCC650_SH_38] = 0xFFu;
    c->sh[HCCC650_SH_40] = 0x05u;
    c->sh[HCCC650_SH_3E] = setup_3e;
    c->sh[HCCC650_SH_46] = 0x00u;
    c->sh[HCCC650_SH_44] = 0x00u;
    c->sh[HCCC650_SH_30] = 0x00u;
    c->sh[HCCC650_SH_34] = 0x83u;   /* band code 3 = 14 kHz, as the stock */
    c->setup_3e = setup_3e;
    c->dirty = 0u;
    c->phase = HCCC650_PH_BOOT;
    c->cur = 0u;
}

unsigned char hccc650_next(hccc650_t *c, unsigned char *reg, unsigned char *val)
{
    unsigned char i;
    switch (c->phase) {
    case HCCC650_PH_BOOT:
        *reg = boot_seq[c->cur][0];
        *val = boot_seq[c->cur][1];
        if (++c->cur >= BOOT_N) { c->phase = HCCC650_PH_SETUP; c->cur = 0u; }
        return 1u;

    case HCCC650_PH_SETUP:
        if (setup_seq[c->cur][0] & 0x80u) {
            i = (unsigned char)(setup_seq[c->cur][0] & 0x7Fu);
            *reg = sh_reg[i];
            *val = c->sh[i];
            c->dirty = (unsigned char)(c->dirty & ~(1u << i));
        } else {
            *reg = setup_seq[c->cur][0];
            *val = setup_seq[c->cur][1];
        }
        if (++c->cur >= SETUP_N) {
            c->phase = HCCC650_PH_RUN;
            c->cur = 0u;
        }
        return 1u;

    case HCCC650_PH_RUN:
        /* a changed shadow goes out first, lowest index first */
        for (i = 0u; i < HCCC650_N_SH; i++) {
            if (c->dirty & (1u << i)) {
                c->dirty = (unsigned char)(c->dirty & ~(1u << i));
                *reg = sh_reg[i];
                *val = c->sh[i];
                return 1u;
            }
        }
        /* otherwise refresh one shadow per call (the stock rewrites them
           every pass: a lost or corrupted bus write heals itself) */
        i = c->cur;
        c->cur = (unsigned char)((c->cur + 1u) % HCCC650_N_SH);
        *reg = sh_reg[i];
        *val = c->sh[i];
        return 1u;

    case HCCC650_PH_SHUTDOWN:
        if (c->cur == 0u) {
            *reg = 0x44u; *val = 0x00u;     /* run-on off first             */
            c->sh[HCCC650_SH_44] = 0x00u;
            c->cur = 1u;
        } else {
            *reg = 0x02u; *val = 0x00u;     /* then the CC650 mode           */
            c->phase = HCCC650_PH_DEAD;
        }
        return 1u;

    default:
        return 0u;
    }
}

void hccc650_out(hccc650_t *c, unsigned char out, unsigned char on)
{
    unsigned char i, m, old;
    if (out >= HCCC650_N_OUT || c->phase >= HCCC650_PH_SHUTDOWN) return;
    i = out_sh[out];
    m = out_bit[out];
    old = c->sh[i];
    if ((on != 0u) == (out_high[out] != 0u)) c->sh[i] = (unsigned char)(old | m);
    else                                      c->sh[i] = (unsigned char)(old & ~m);
    if (c->sh[i] != old) c->dirty = (unsigned char)(c->dirty | (1u << i));
}

void hccc650_knock(hccc650_t *c, unsigned char band, unsigned char gain)
{
    unsigned char v = (unsigned char)(0x80u | ((gain & 7u) << 4) | (band & 15u));
    if (c->phase >= HCCC650_PH_SHUTDOWN) return;
    if (c->sh[HCCC650_SH_34] != v) {
        c->sh[HCCC650_SH_34] = v;
        c->dirty = (unsigned char)(c->dirty | (1u << HCCC650_SH_34));
    }
}

void hccc650_shutdown(hccc650_t *c)
{
    if (c->phase >= HCCC650_PH_SHUTDOWN) return;
    c->phase = HCCC650_PH_SHUTDOWN;
    c->cur = 0u;
}

unsigned int hccc650_baro_hpa(unsigned char reg16)
{
    unsigned int counts = (unsigned int)reg16 * 4u;          /* <= 1020   */
    return (unsigned int)(counts + (counts * 61u) / 256u);   /* <= 62220 */
}
