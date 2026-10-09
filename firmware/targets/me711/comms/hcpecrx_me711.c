/*
 * hcpecrx_me711.c - ASC0 receive via PEC channel 6 into an XRAM ring.
 *
 * See hcpecrx_me711.h for the design and the evidence. This file holds two
 * clearly separated parts:
 *
 *   1. the PURE RING ARITHMETIC (hc_pecrx_ring_init / _produced / _available /
 *      _pop) - no SFR, always compiled, host-tested by tests/host/test_hcpecrx.c;
 *   2. the TARGET SFR PATH (hc_pecrx_arm / _service) - compiled only into the
 *      C167 image, and NOT yet wired into hcmain (V90 integration + physical
 *      qualification pending). The CC7 polling drain in hcts.c stays the default.
 */
#include "hcpecrx_me711.h"

/* =============================================================== pure ring ==
 *
 * head/tail are free-running byte counts; the physical slot is index & mask. The
 * unsigned difference (head - tail) is the unread count and is correct across a
 * 16-bit wrap. An overflow is (head - tail) > size: the producer delivered more
 * than the ring holds since the consumer last ran, so the OLDEST unread bytes
 * are gone. Rather than hand back corrupt data, tail is snapped forward to the
 * oldest still-valid byte and the loss is counted. */
void hc_pecrx_ring_init(hc_pecrx_t *r, unsigned char *buf, unsigned int size)
{
    r->buf = buf;
    r->size = size;
    r->mask = (unsigned int)(size - 1u);
    r->head = 0u;
    r->tail = 0u;
    r->overflow = 0u;
    r->frame_err = 0u;
    r->hw_ovr = 0u;
}

void hc_pecrx_produced(hc_pecrx_t *r, unsigned int n)
{
    r->head = (unsigned int)(r->head + n);
    if ((unsigned int)(r->head - r->tail) > r->size) {
        /* The producer lapped the consumer: keep only the newest `size` bytes. */
        r->tail = (unsigned int)(r->head - r->size);
        r->overflow++;
    }
}

unsigned int hc_pecrx_available(const hc_pecrx_t *r)
{
    return (unsigned int)(r->head - r->tail);
}

unsigned char hc_pecrx_pop(hc_pecrx_t *r, unsigned char *b)
{
    if (r->tail == r->head) {
        return 0u;
    }
    *b = r->buf[r->tail & r->mask];
    r->tail = (unsigned int)(r->tail + 1u);
    return 1u;
}

#ifndef HC_PECRX_HOST_TEST
/* ============================================================ target path == */
#include <reg167.h>
#include "hctarget.h"

/* PECC6 control bits beside the 8-bit count. The OEM writes (count | 0x0300)
   for this channel (seg83:AF14 OR #0300h). NOTE: the exact INC/BWT bit encoding
   is taken from the OEM image and must be re-confirmed against the C167CR UM
   Table 5-x at physical qualification before this path is trusted - it is not on
   the qualified path yet. */
#define HC_PECRX_PECC_FLAGS 0x0300u

/* The C166 PEC count field is 8 bits (max 255). DSTP6 walks the WHOLE ring
   (HC_PECRX_SIZE bytes) continuously; the count is reloaded from the main-loop
   consumer so it never reaches 0 (which would take the boot-block S0RINT
   vector). The pointer is snapped back to the ring base with this much margin
   still unfilled, so a reset never races PEC past the end. */
#define HC_PECRX_TOPUP_MARGIN 16u

/* The ring buffer. It MUST end up in PEC-addressable on-chip XRAM (the OEM used
   0xE0A2). Final placement is a linker/V90-integration step; declared here so
   the module compiles and links standalone. */
static unsigned char hc_pecrx_buf[HC_PECRX_SIZE];

hc_pecrx_t hc_pecrx;

static unsigned int  s_base;    /* &hc_pecrx_buf[0] as a 16-bit offset          */
static unsigned int  s_lap;     /* head value at the start of the current lap    */

/* Reload the count so PEC keeps filling from where DSTP6 currently is, without
   moving the pointer, up to `n` more bytes (clamped to the 8-bit field). */
static void topup(unsigned int n)
{
    if (n > 255u) { n = 255u; }
    PECC6 = (unsigned int)(n | HC_PECRX_PECC_FLAGS);
}

void hc_pecrx_arm(void)
{
    volatile unsigned char sink;

    hc_pecrx_ring_init(&hc_pecrx, hc_pecrx_buf, HC_PECRX_SIZE);
    s_base = (unsigned int)(unsigned long)&hc_pecrx_buf[0];
    s_lap = 0u;

    /* Clear a stale byte and the sticky error flags before arming. */
    sink = (unsigned char)S0RBUF;
    (void)sink;
    S0CON = (unsigned int)(S0CON & ~0x0700u);

    SRCP6 = (unsigned int)&S0RBUF;            /* fixed source, no src increment */
    DSTP6 = s_base;
    topup(HC_PECRX_SIZE - HC_PECRX_TOPUP_MARGIN);

    /* ILVL 15, GLVL 2 - the OEM's value (S0RIC = 0x3E), which selects PEC
       service for ASC0 receive. GLVL 2 keeps it distinct from the crank capture
       at 12/3, matching hctarget.h's rule that two enabled sources never share
       an (ILVL,GLVL). */
    S0RIC = HC_IC(TGT_ILVL_ASIC, TGT_GLVL_SERIAL);   /* 15 / 2 */
}

void hc_pecrx_service(void)
{
    unsigned int cur;
    unsigned int total;
    unsigned int w;

    /* Fold in the sticky ASC0 error flags (same bits hcts_poll reads). */
    w = S0CON;
    if (w & 0x0700u) {
        if (w & 0x0400u) { hc_pecrx.hw_ovr++; }
        if (w & 0x0200u) { hc_pecrx.frame_err++; }
        S0CON = (unsigned int)(w & ~0x0700u);
    }

    /* How far into the current lap DSTP6 has walked (0..SIZE). */
    cur = (unsigned int)(DSTP6 - s_base);
    if (cur > HC_PECRX_SIZE) {
        cur = HC_PECRX_SIZE;                  /* defensive clamp */
    }

    /* Advance the ring head to the live position. The data is already in the
       buffer via PEC; hc_pecrx_produced folds in overflow detection. head is
       free-running, so the physical slot (head & mask) always equals the
       physical write position (cur), because the buffer is one contiguous lap. */
    total = (unsigned int)(s_lap + cur);
    if ((unsigned int)(total - hc_pecrx.head) != 0u) {
        hc_pecrx_produced(&hc_pecrx, (unsigned int)(total - hc_pecrx.head));
    }

    /* Ring wrap: near the top, snap DSTP6 back to base and start a new lap. The
       consumer reads behind us; anything it has not taken by now is overflow and
       was already counted above. */
    if (cur >= (HC_PECRX_SIZE - HC_PECRX_TOPUP_MARGIN)) {
        DSTP6 = s_base;
        s_lap = (unsigned int)(s_lap + HC_PECRX_SIZE);
        topup(HC_PECRX_SIZE - HC_PECRX_TOPUP_MARGIN);
    } else {
        /* Keep the count healthy without moving the pointer. */
        topup((unsigned int)(HC_PECRX_SIZE - cur - HC_PECRX_TOPUP_MARGIN));
    }
}
#endif /* HC_PECRX_HOST_TEST */
