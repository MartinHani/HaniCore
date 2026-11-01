/*
 * hcme75mon.c - ME7.5 DC monitor question/answer core. See hcme75mon.h.
 * SFR-free, 16-bit, wrap-safe time differences.
 */
#include "hcme75mon.h"

/* 16-bit tick arithmetic on every host (the C167 int is 16-bit already) */
#define T16(x) ((unsigned int)((x) & 0xFFFFu))

/* 05.12 response widths (06A906032HS seg89:1D26 +0x080 / +0x21E) */
static const unsigned int resp[16] = {
    0x2FCDu, 0x1DDAu, 0x2700u, 0x1F8Eu, 0x34BAu, 0x3234u, 0x374Fu, 0x290Eu,
    0x1C36u, 0x1929u, 0x2502u, 0x2B3Au, 0x2150u, 0x2D74u, 0x2321u, 0x1AAFu
};
/* 05.12 band edges: band q = [edge[q-1], edge[q]) inside WIN_LO..WIN_HI */
static const unsigned int edge[15] = {
    0x19EBu, 0x1B6Eu, 0x1D06u, 0x1EAFu, 0x2067u, 0x2234u, 0x2410u, 0x2601u,
    0x2806u, 0x2A1Eu, 0x2C4Fu, 0x2E97u, 0x30F8u, 0x336Du, 0x3601u
};

unsigned char hcme75mon_band(unsigned int w)
{
    unsigned char q;
    if (w < HCME75MON_WIN_LO || w >= HCME75MON_WIN_HI) return HCME75MON_BAND_NONE;
    for (q = 0u; q < 15u; q++) {
        if (w < edge[q]) return q;
    }
    return 15u;
}

unsigned int hcme75mon_response(unsigned char band)
{
    return resp[band & 15u];
}

void hcme75mon_init(hcme75mon_t *m, unsigned int now)
{
    m->phase = HCME75MON_PH_START;
    m->frames = 0u;
    m->sent = 0u;
    m->got_q = 0u;
    m->low = 0u;
    m->listen = 0u;
    m->last_q = HCME75MON_BAND_NONE;
    m->t0 = now;
    m->fall_t = now;
    m->cur = HCME75MON_ASYNC;
    m->next = HCME75MON_ASYNC2;
    m->answers = 0u;
    m->asyncs = 0u;
    m->invalid = 0u;
    m->timeouts = 0u;
}

void hcme75mon_listen(hcme75mon_t *m)
{
    if (m->phase == HCME75MON_PH_START) return;
    m->listen = 1u;
    m->low = 0u;
}

void hcme75mon_edge(hcme75mon_t *m, unsigned char high, unsigned int t)
{
    unsigned char q;
    if (!m->listen) return;                     /* our own pulse, startup */
    if (!high) {
        m->fall_t = t;
        m->low = 1u;
        return;
    }
    if (!m->low) return;
    m->low = 0u;
    q = hcme75mon_band(T16(t - m->fall_t));
    m->last_q = q;
    if (q == HCME75MON_BAND_NONE) {
        m->invalid++;
        m->next = HCME75MON_INVALID;
        return;
    }
    m->next = resp[q];                          /* sent two TX slots later */
    m->got_q = 1u;
}

unsigned char hcme75mon_poll(hcme75mon_t *m, unsigned int now,
                             unsigned int *width)
{
    unsigned int el = T16(now - m->t0);

    switch (m->phase) {
    case HCME75MON_PH_START:
        if (m->frames < HCME75MON_START_FRAMES) {
            if (el >= HCME75MON_FRAME) {
                m->frames++;
                m->t0 = T16(m->t0 + HCME75MON_FRAME);
            }
            return 0u;
        }
        if (el < HCME75MON_START_REM) return 0u;
        m->phase = HCME75MON_PH_TX;             /* the first TX slot: now */
        m->t0 = now;
        m->sent = 0u;
        break;

    case HCME75MON_PH_TX:
        if (m->sent && el >= HCME75MON_FRAME) {
            m->phase = HCME75MON_PH_RX;
            m->t0 = T16(m->t0 + HCME75MON_FRAME);
            if (!m->listen) {                   /* never told: listen now */
                m->listen = 1u;
                m->low = 0u;
            }
        }
        break;

    default:                                    /* HCME75MON_PH_RX */
        if (el >= HCME75MON_FRAME) {
            if (!m->got_q) m->timeouts++;
            m->phase = HCME75MON_PH_TX;
            m->t0 = T16(m->t0 + HCME75MON_FRAME);
            m->sent = 0u;
        }
        break;
    }

    /* a TX slot's pulse starts at the poll that opens the slot */
    if (m->phase == HCME75MON_PH_TX && !m->sent) {
        m->sent = 1u;
        m->listen = 0u;                         /* our pulse is on the line */
        m->got_q = 0u;
        m->low = 0u;
        *width = m->cur;
        if (m->cur == HCME75MON_ASYNC || m->cur == HCME75MON_ASYNC2) m->asyncs++;
        else m->answers++;
        m->cur = m->next;
        m->next = HCME75MON_INVALID;
        return 1u;
    }
    return 0u;
}
