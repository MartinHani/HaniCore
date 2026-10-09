/*
 * hcnmisnap.c - the NMI post-mortem for the Bosch ME7.1.1.
 *
 * NOT COMPILED INTO RESETDIAG_V2.
 *
 * LAYOUT, in the battery-backed SRAM at TGT_RAM_NMISNAP. Word offsets:
 *
 *      0   magic 'N','S'          written by init, checked by the reader
 *      1   valid                  1 once capture() has run this boot
 *      2   tick_ms                when the NMI hit
 *      3   stage                  boot stage at that moment
 *      4   P3                     port input register (NLEN_FR readback)
 *      5   P6                     P6.4 CS state, P6.2 KL15_STAT
 *      6   WDT                    live watchdog counter
 *      7   WDTCON
 *      8   head                   ring write index at capture time
 *      9   .. 9+HIST-1  ubat ring
 *      then the same block again as the PREVIOUS record, copied by init.
 *
 * THE COST BUDGET. The handler does 8 word stores plus the ring copy, all to
 * external SRAM on BUSCON1 (0x040D, so a fast non-multiplexed 16-bit access).
 * There is no loop whose trip count depends on anything but NMISNAP_HIST, no
 * call out of this module, and no ADC start - starting a conversion would be
 * ~10 us of waiting for a number we would then have no reason to trust, since
 * the rail is the thing in question.
 *
 * HOW MUCH TIME DO WE ACTUALLY HAVE? Not known in closed form, and this file
 * will not pretend otherwise. What IS known:
 *   - the analog network cannot be the delay: R5402*C5402 = 22 us,
 *     C5401 into 47k||47k = 517 us, R5420*C5421 = 4.85 ms. Nothing near the
 *     255 ms deadline lives in it.
 *   - the bench has already proven at least one external SRAM write completes
 *     after the NMI, because TR=0002 survived to be printed on the next boot.
 * So the honest statement is: one store is proven, and this module is sized
 * so that if it is cut short the EARLY fields are the important ones. tick_ms
 * and stage are written FIRST for exactly that reason; the ring is last.
 */
#include <reg167.h>
#include "hctarget.h"
#include "hcnmisnap.h"

#define SNAP  ((unsigned int volatile far *) \
               (TGT_EXTRAM_BASE + TGT_RAM_NMISNAP))

#define W_MAGIC   0u
#define W_VALID   1u
#define W_TICK    2u
#define W_STAGE   3u
#define W_P3      4u
#define W_P6      5u
#define W_WDT     6u
#define W_WDTCON  7u
#define W_HEAD    8u
#define W_HIST    9u
#define W_REC     (W_HIST + NMISNAP_HIST)   /* size of one record, in words */

#define MAGIC_VAL 0x4E53u                   /* 'N','S' */

/* The ring lives in near RAM, not in the snapshot area: the tick writes it
   every millisecond and near RAM is one instruction per store. Only the NMI
   copies it out to the battery-backed side, and only once. */
static unsigned int ubat_ring[NMISNAP_HIST];
static unsigned char ubat_head;

void hc_nmisnap_feed(unsigned int ubat_counts)
{
    unsigned char h = ubat_head;
    ubat_ring[h] = ubat_counts;
    h++;
    if (h >= (unsigned char)NMISNAP_HIST) h = 0u;
    ubat_head = h;                 /* single byte write: not a torn update */
}

void hc_nmisnap_init(void)
{
    unsigned char i;

    /* Roll the current record into the previous half before clearing it, so a
       reset that happens before the next capture still leaves one readable. */
    if (SNAP[W_MAGIC] == MAGIC_VAL && SNAP[W_VALID] != 0u) {
        for (i = 0u; i < (unsigned char)W_REC; i++)
            SNAP[W_REC + i] = SNAP[i];
    } else {
        for (i = 0u; i < (unsigned char)W_REC; i++)
            SNAP[W_REC + i] = 0u;
    }

    for (i = 0u; i < (unsigned char)W_REC; i++)
        SNAP[i] = 0u;
    SNAP[W_MAGIC] = MAGIC_VAL;

    for (i = 0u; i < (unsigned char)NMISNAP_HIST; i++)
        ubat_ring[i] = 0u;
    ubat_head = 0u;
}

void hc_nmisnap_capture(unsigned int tick_ms, unsigned int stage)
{
    unsigned char i;

    /* Order matters: if this is cut short, these two are the ones worth
       having. VALID is written LAST so a torn record reads as invalid. */
    SNAP[W_TICK]   = tick_ms;
    SNAP[W_STAGE]  = stage;
    SNAP[W_P3]     = P3;
    SNAP[W_P6]     = P6;
    SNAP[W_WDT]    = WDT;
    SNAP[W_WDTCON] = WDTCON;
    SNAP[W_HEAD]   = (unsigned int)ubat_head;

    for (i = 0u; i < (unsigned char)NMISNAP_HIST; i++)
        SNAP[W_HIST + i] = ubat_ring[i];

    SNAP[W_MAGIC] = MAGIC_VAL;
    SNAP[W_VALID] = 1u;
}

unsigned char hc_nmisnap_prev(unsigned int *tick_ms,
                              unsigned int *stage,
                              unsigned int *p3,
                              unsigned int *p6,
                              unsigned int *wdt,
                              unsigned int *ubat_hist)
{
    unsigned char i;
    unsigned int  head;

    if (SNAP[W_REC + W_MAGIC] != MAGIC_VAL) return 0u;
    if (SNAP[W_REC + W_VALID] == 0u)        return 0u;

    *tick_ms = SNAP[W_REC + W_TICK];
    *stage   = SNAP[W_REC + W_STAGE];
    *p3      = SNAP[W_REC + W_P3];
    *p6      = SNAP[W_REC + W_P6];
    *wdt     = SNAP[W_REC + W_WDT];

    /* Unroll the ring so index 0 is the OLDEST sample. head points at the
       slot that would have been written next, i.e. the oldest one. */
    head = SNAP[W_REC + W_HEAD];
    for (i = 0u; i < (unsigned char)NMISNAP_HIST; i++) {
        unsigned char k = (unsigned char)((head + i) % NMISNAP_HIST);
        ubat_hist[i] = SNAP[W_REC + W_HIST + k];
    }
    return 1u;
}

int hc_nmisnap_prev_slope(void)
{
    unsigned int h[NMISNAP_HIST];
    unsigned int t, s, p3v, p6v, w;

    if (!hc_nmisnap_prev(&t, &s, &p3v, &p6v, &w, h)) return 0;
    /* oldest - newest. Positive => UBAT was falling into the reset. */
    return (int)h[0] - (int)h[NMISNAP_HIST - 1u];
}
