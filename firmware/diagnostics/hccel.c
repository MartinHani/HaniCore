/* hccel.c - the check-engine lamp policy. Read hccel.h. */
#include "hccel.h"

void HCCEL_FAR hccel_reset(hccel_t HCCEL_MEM *c)
{
    c->t0 = 0u;
    c->key = 0u;
    c->testing = 0u;
    c->mode = HCCEL_OFF;
    c->cmd = 0u;
    c->test_en = 1u;
    c->on_ms = HCCEL_TEST_ON_MS;
    c->end_ms = HCCEL_TEST_END_MS;
}

void HCCEL_FAR hccel_config(hccel_t HCCEL_MEM *c, unsigned char test_en,
                            unsigned int on_ms, unsigned int gap_ms)
{
    c->test_en = (unsigned char)(test_en ? 1u : 0u);
    c->on_ms = on_ms;
    c->end_ms = (on_ms > (unsigned int)(0xFFFFu - gap_ms))
              ? 0xFFFFu : (unsigned int)(on_ms + gap_ms);
}

unsigned char HCCEL_FAR hccel_step(hccel_t HCCEL_MEM *c, unsigned int now_ms,
                                   unsigned char key_on, unsigned char mil_req)
{
    if (!key_on) {
        c->key = 0u;
        c->testing = 0u;
        c->mode = HCCEL_OFF;
        c->cmd = 0u;
        return 0u;
    }
    if (!c->key) {                        /* a key-on edge (or boot)       */
        c->key = 1u;
        c->testing = c->test_en;
        c->t0 = now_ms;
    }
    if (c->testing) {
        /* 16-bit on the C167; masked so a 32-bit host wraps the same way */
        unsigned int el = (unsigned int)((now_ms - c->t0) & 0xFFFFu);
        if (el < c->on_ms) {
            c->mode = HCCEL_TEST_ON;
            c->cmd = 1u;
            return 1u;
        }
        if (el < c->end_ms) {
            c->mode = HCCEL_TEST_GAP;
            c->cmd = 0u;
            return 0u;
        }
        c->testing = 0u;                  /* done: never re-armed by a wrap */
    }
    c->mode = mil_req ? HCCEL_ON : HCCEL_OFF;
    c->cmd = mil_req ? 1u : 0u;
    return c->cmd;
}
