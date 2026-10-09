/*
 * hcdtc.c - DTC debounce, history and MIL request. Read hcdtc.h first; the
 * proof is tests/host/test_hcdtc.c (tools/test_hcdtc_host.py, with the Keil
 * no-helper check). 16-bit arithmetic only.
 */
#include "hcdtc.h"

void HCDTC_FAR hcdtc_clear(hcdtc_t HCDTC_MEM *d)
{
    unsigned char i;

    for (i = 0u; i < HCDTC_MAX; i++) {
        d->p[i].t_ms = 0u;
        d->p[i].st = 0u;
        d->p[i].count = 0u;
    }
    d->mil = 0u;
    d->n_active = 0u;
    d->n_stored = 0u;
    d->ff_code = 0u;
    for (i = 0u; i < HCDTC_FF_N; i++) d->ff[i] = 0u;
}

static unsigned int add_sat(unsigned int a, unsigned int b)
{
    return (a > 65535u - b) ? 65535u : (unsigned int)(a + b);
}

void HCDTC_FAR hcdtc_step(hcdtc_t HCDTC_MEM *d, const hcdtc_def_t *defs, unsigned char n,
                          const unsigned int *fail, unsigned int ms,
                          const unsigned int *ff_now)
{
    unsigned char i, j;
    unsigned char mil = 0u, na = 0u, ns = 0u;

    if (n > HCDTC_MAX) n = HCDTC_MAX;
    for (i = 0u; i < n; i++) {
        hcdtc_path_t HCDTC_MEM *p = &d->p[i];
        unsigned char f = (unsigned char)((fail[i >> 4] >> (i & 15u)) & 1u);

        if (f) {
            p->st |= HCDTC_S_FAIL;
            if (p->st & HCDTC_S_ACTIVE) {
                p->t_ms = 0u;                        /* heal starts over    */
            } else {
                p->t_ms = add_sat(p->t_ms, ms);
                if (p->t_ms >= defs[i].set_ms) {
                    p->st |= (unsigned char)(HCDTC_S_ACTIVE | HCDTC_S_STORED);
                    p->t_ms = 0u;
                    if (p->count < 255u) p->count++;
                    if (d->ff_code == 0u) {
                        d->ff_code = defs[i].code;
                        for (j = 0u; j < HCDTC_FF_N; j++) d->ff[j] = ff_now[j];
                    }
                }
            }
        } else {
            p->st &= (unsigned char)(0xFFu & ~HCDTC_S_FAIL);
            if (p->st & HCDTC_S_ACTIVE) {
                p->t_ms = add_sat(p->t_ms, ms);
                if (p->t_ms >= defs[i].heal_ms) {
                    p->st &= (unsigned char)(0xFFu & ~HCDTC_S_ACTIVE);
                    p->t_ms = 0u;
                }
            } else {
                p->t_ms = 0u;                        /* a flicker restarts  */
            }
        }
        if (p->st & HCDTC_S_ACTIVE) {
            na++;
            if (defs[i].flags & HCDTC_MIL) mil = 1u;
        }
        if (p->st & HCDTC_S_STORED) ns++;
    }
    d->mil = mil;
    d->n_active = na;
    d->n_stored = ns;
}

unsigned int HCDTC_FAR hcdtc_code(const hcdtc_t HCDTC_MEM *d, const hcdtc_def_t *defs,
                                  unsigned char n, unsigned char mask,
                                  unsigned char k)
{
    unsigned char i;

    if (n > HCDTC_MAX) n = HCDTC_MAX;
    for (i = 0u; i < n; i++) {
        if (d->p[i].st & mask) {
            if (k == 0u) return defs[i].code;
            k--;
        }
    }
    return 0u;
}

void HCDTC_FAR hcdtc_lists(const hcdtc_t HCDTC_MEM *d, const hcdtc_def_t *defs,
                           unsigned char n, unsigned int *act,
                           unsigned int *sto, unsigned char k_n)
{
    unsigned char i, na = 0u, ns = 0u, st;

    for (i = 0u; i < k_n; i++) {
        act[i] = 0u;
        sto[i] = 0u;
    }
    if (n > HCDTC_MAX) n = HCDTC_MAX;
    for (i = 0u; i < n && (na < k_n || ns < k_n); i++) {
        st = d->p[i].st;
        if ((st & HCDTC_S_ACTIVE) && na < k_n) act[na++] = defs[i].code;
        if ((st & HCDTC_S_STORED) && ns < k_n) sto[ns++] = defs[i].code;
    }
}
