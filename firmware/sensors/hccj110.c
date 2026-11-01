/*
 * hccj110.c - CJ110 + LSU 4.2 wideband core (ME7.5 DC). See hccj110.h.
 * SFR-free, 16-bit arithmetic only.
 */
#include "hccj110.h"

/* LALIUS, 4B0906018DC 0x813A08: axis = offset-corrected UA in 10-bit counts
   (5 V), value = lambda (raw / 4096, here x 1000, rounded). EXACT TARGET
   BINARY - the X505P image carries the identical curve at 0x813A00. */
#define LALIUS_N 22u
static const unsigned int lalius_ua[LALIUS_N] = {
     28u, 117u, 203u, 258u, 290u, 298u, 305u, 307u, 312u, 318u, 324u,
    334u, 351u, 371u, 393u, 450u, 504u, 565u, 621u, 666u, 705u, 738u
};
static const unsigned int lalius_lam[LALIUS_N] = {
     730u,  800u,  879u,  940u,  980u,  990u, 1000u, 1004u, 1010u, 1020u, 1030u,
    1050u, 1090u, 1140u, 1200u, 1400u, 1640u, 2000u, 2500u, 3100u, 3900u, 5000u
};

unsigned int hccj110_lambda_x1000(unsigned int x)
{
    unsigned char i;
    if (x <= lalius_ua[0]) return lalius_lam[0];
    if (x >= lalius_ua[LALIUS_N - 1u]) return lalius_lam[LALIUS_N - 1u];
    for (i = 1u; i < LALIUS_N; i++) {
        if (x <= lalius_ua[i]) break;
    }
    /* (x - x0) <= 89 counts and dy <= 1100 in every segment: the product
       stays below 65536 (checked by the host test over the whole axis) */
    return (unsigned int)(lalius_lam[i - 1u]
        + ((x - lalius_ua[i - 1u]) * (lalius_lam[i] - lalius_lam[i - 1u]))
          / (lalius_ua[i] - lalius_ua[i - 1u]));
}

static void enter(hccj110_t *c, unsigned char st)
{
    c->st = st;
    c->t_ms = 0u;
}

void hccj110_init(hccj110_t *c)
{
    c->fcode = HCCJ110_F_NONE;
    c->la = 1u;
    c->valid = 0u;
    c->lambda = 0u;
    c->ua0 = 0u;
    c->sum = 0u;
    c->n = 0u;
    enter(c, HCCJ110_ST_CAL_SETTLE);
}

static void fault(hccj110_t *c, unsigned char f)
{
    c->fcode = f;
    c->la = 0u;                 /* measurement mode: the safe pin state   */
    c->valid = 0u;
    c->lambda = 0u;
    enter(c, HCCJ110_ST_FAULT);
}

void hccj110_step(hccj110_t *c, unsigned int ua, unsigned char hot,
                  unsigned int dt_ms)
{
    unsigned int t = c->t_ms + dt_ms;
    c->t_ms = (t < c->t_ms) ? 0xFFFFu : t;      /* saturate, never wrap   */

    switch (c->st) {
    case HCCJ110_ST_CAL_SETTLE:
        c->la = 1u;
        if (c->t_ms >= HCCJ110_SETTLE_MS) {
            c->sum = 0u;
            c->n = 0u;
            enter(c, HCCJ110_ST_CAL_SAMPLE);
        }
        break;

    case HCCJ110_ST_CAL_SAMPLE:
        c->la = 1u;
        c->sum = (unsigned int)(c->sum + (ua & 0x03FFu)); /* 8 x 1023 fits */
        c->n++;
        if (c->n >= HCCJ110_CAL_SAMPLES) {
            c->ua0 = (unsigned int)(c->sum / HCCJ110_CAL_SAMPLES);
            if (c->ua0 < HCCJ110_UA0_MIN || c->ua0 > HCCJ110_UA0_MAX) {
                fault(c, HCCJ110_F_CAL);
            } else {
                c->la = 0u;
                enter(c, HCCJ110_ST_MEASURE);
            }
        }
        break;

    case HCCJ110_ST_MEASURE:
        c->la = 0u;
        if (ua >= HCCJ110_UA_DIAG) {
            /* the chip's diagnosis level: lambda is withdrawn at once and
               the fault latches only if it lasts TVCJLSU */
            c->valid = 0u;
            c->lambda = 0u;
            if (c->t_ms >= HCCJ110_DIAG_MS) fault(c, HCCJ110_F_CHIP);
            break;
        }
        c->t_ms = 0u;               /* the diagnosis timer restarts      */
        if (!hot) {
            c->valid = 0u;
            c->lambda = 0u;
            break;
        }
        {
            /* the table is relative to the stock zero USABGL: shift the
               measured UA by (USABGL - UA0) */
            unsigned int corr;
            if (ua + HCCJ110_UA0_NOM <= c->ua0) corr = 0u;
            else corr = (unsigned int)(ua + HCCJ110_UA0_NOM - c->ua0);
            c->lambda = hccj110_lambda_x1000(corr);
            c->valid = 1u;
        }
        break;

    default:                        /* HCCJ110_ST_FAULT: latched           */
        c->la = 0u;
        c->valid = 0u;
        c->lambda = 0u;
        break;
    }
}
