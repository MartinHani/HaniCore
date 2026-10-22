/*
 * hcumkom.c - Bosch ME7.1.1 runtime supervision (UMKOM) responder.
 *
 * A faithful port of the OEM ME7.1.1 OEM `um_service` ([BIN] 0x8B1E24) + `um_init`
 * ([BIN] 0x8B2188) + the accumulator advance ([BIN] 0x8B20FC, first two
 * instructions only - its CAPCOM CCM0..7 self-test is dropped, HaniCore does
 * not configure those channels).
 *
 * VERIFIED: scratchpad/um_closedloop.py runs the real OEM `um_service` out of
 * the image in the C167 simulator against a modelled S5500 that implements the
 * semantics this file reproduces - 300+ process cycles, zero MAIN SRST, the
 * FR +3 / -1 counter law, the 40 ms question raster. See
 * the maintainer's design notes/5c.
 *
 * The mechanism (frame word 1, one byte, both directions):
 *
 *   S5500 -> MAIN :  bits[7:4] = trust counter (must equal our `expect`)
 *                    bits[3:0] = question index 0..15  (S5500's 8-bit LFSR)
 *   MAIN  -> S5500 :  FR_TABLE[question from the PREVIOUS process cycle],
 *                     or 16 (FR "invalid") on the periodic resync tick.
 *
 * FR_TABLE is the Bosch ME7 Funktionsrahmen standard permutation (UMKOM 7.10,
 * p1489) - the same one tools/wd_ref/wd_table_0512.py uses for the ME7.5 P2.5
 * watchdog. Nothing here is Bosch-specific except the question-code
 * arithmetic-progression base/step (0x131C / 0x40E), which is recovered from
 * the OEM ME7.1.1 binary and confirmed byte-identical in the A1104F sibling.
 */
#include <reg167.h>
#include "hctarget.h"
#include "hcumkom.h"
#include "hcliveforensics.h"

/* Bosch ME7 FR question -> answer, no fixed point. [FR UMKOM 7.10 p1489] */
static const unsigned char UM_FR[16] = {
    12, 3, 8, 4, 14, 13, 15, 9, 2, 0, 7, 10, 5, 11, 6, 1
};

/* Question-code progression: Qcode(n) = UM_QBASE + n*UM_QSTEP, n = 0..15.
   [OEM ME7.1.1] the 16 CMP leaves at 0x8B1EE0..0x8B2062; [A1104F] identical. */
#define UM_QBASE   0x131Cu
#define UM_QSTEP   0x040Eu

/* OEM state, names are the OEM ME7.1.1 ext-RAM addresses they mirror. */
static unsigned int  um_acc_hi;    /* 0x80A8 - Qcode high 6 bits accumulator  */
static unsigned int  um_acc_lo;    /* 0x80AA - Qcode low 10 bits accumulator  */
static unsigned char um_seed;      /* 0x8096 - last received question nibble  */

unsigned char hc_umkom_health;     /* 0x8092 */
unsigned char hc_umkom_expect;     /* 0x8091 */
unsigned char hc_umkom_phase;      /* 0x8094 */
unsigned int  hc_umkom_answers;
unsigned int  hc_umkom_mismatch;
unsigned int  hc_umkom_last_rx;
unsigned int  hc_umkom_last_tx;

static unsigned int  um_ans;       /* 0x809E - last computed answer (0..16)   */

void hc_umkom_init(void)
{
    /* [BIN] 0x8B2188 */
    um_acc_hi = 0x000Cu;
    um_acc_lo = 0x038Cu;
    um_seed   = 0x0Cu;             /* 0x8098 init 0xBC -> low nibble 0x0C     */
    hc_umkom_phase  = 4u;
    hc_umkom_health = 11u;
    hc_umkom_expect = 11u;
    um_ans = 0u;
    hc_umkom_answers = 0u;
    hc_umkom_mismatch = 0u;
    hc_umkom_last_rx = 0u;
    hc_umkom_last_tx = 0u;
}

/* The dispatch of [BIN] 0x8B1EE0..0x8B2062, as arithmetic. Every OEM leaf is
   "Qcode == UM_QBASE + n*UM_QSTEP -> UM_FR[n]"; anything else -> 16. */
static unsigned char um_dispatch(unsigned int qcode)
{
    unsigned int d;
    if (qcode < UM_QBASE || qcode > (unsigned int)(UM_QBASE + 15u * UM_QSTEP))
        return 16u;
    d = (unsigned int)(qcode - UM_QBASE);
    if (d % UM_QSTEP != 0u)
        return 16u;
    return UM_FR[d / UM_QSTEP];
}

void hc_umkom_service(unsigned int volatile far *frame)
{
    unsigned int w1;
    unsigned char rx_trust, rx_q;
    unsigned int qcode;

    w1 = frame[1];
    hc_umkom_last_rx = w1;
    hc_lf_um_before(um_acc_hi, um_acc_lo, (unsigned int)um_seed, um_ans,
                    (unsigned int)hc_umkom_phase,
                    (unsigned int)hc_umkom_health,
                    (unsigned int)hc_umkom_expect, hc_umkom_answers, w1);

    /* --- ECHO ticks: 3 of every 4. Re-send the last answer, advance the
       accumulator, and leave. [BIN] 0x8B1E6E -> 0x8B20DC, then 0x8B20FC. --- */
    if (hc_umkom_phase != 4u && hc_umkom_phase != 0u) {
        hc_umkom_phase--;                       /* 0x8B20DC: 8094 -= 1        */
        frame[1] = um_ans;
        frame[2] = 0u;
        frame[3] = 0u;
        hc_umkom_last_tx = um_ans;
        um_acc_hi = (unsigned int)(um_acc_hi + 1u);      /* 0x8B20FC          */
        um_acc_lo = (unsigned int)(um_acc_lo + 0x00C7u);
        hc_lf_um_after(um_acc_hi, um_acc_lo, (unsigned int)um_seed, um_ans);
        return;
    }

    /* --- PROCESS tick. --- */

    /* Qcode from the accumulator as left by the last process + 3 advances.
       Guards from [BIN] 0x8B1E7C / 0x8B1E86. */
    if (um_acc_hi > 0x003Fu || um_acc_lo > 0x03FFu)
        qcode = 0xFFFFu;
    else
        qcode = (unsigned int)(((unsigned int)(um_acc_hi << 10)) + um_acc_lo);

    /* Counter-nibble check: the S5500's reported trust must equal ours.
       [BIN] 0x8B1EA2..0x8B1EC6 */
    rx_trust = (unsigned char)((w1 >> 4) & 0x0Fu);
    rx_q     = (unsigned char)(w1 & 0x0Fu);

    if (hc_umkom_phase == 4u) {
        /* first process cycle after init: the OEM skips the frame read
           entirely (8094 == 4 gate at 0x8B1E32), so the check runs against
           stale bytes and the seed stays the init 0x0C. Mirror that: no
           check, no reseed from this frame. */
        rx_trust = hc_umkom_expect;             /* force "match"             */
        rx_q     = um_seed;                     /* keep the init seed        */
    }

    if (rx_trust == hc_umkom_expect) {
        if (hc_umkom_health != 0u)
            hc_umkom_health--;                  /* correct: -1               */
    } else {
        hc_umkom_health = (unsigned char)(hc_umkom_health + 3u);   /* +3     */
        hc_umkom_expect = rx_trust;             /* resync to what it sent     */
        hc_umkom_mismatch++;
    }

    /* The shared sync counter ramp. [BIN] 0x8B1ECA..0x8B1EDE:
       expect != 0 -> expect -= 1 ; expect == 0 -> expect = 3 and force
       answer 16 (the periodic FR resync). */
    if (hc_umkom_expect == 0u) {
        qcode = 0xFFFFu;
        hc_umkom_expect = 3u;
    } else {
        hc_umkom_expect--;
    }

    um_ans = um_dispatch(qcode);

    /* [BIN] 0x8B206C..0x8B20C0: reseed the accumulator from this frame's
       question nibble for the next process cycle. um_acc_lo = seed*14
       (0xFCFC / 0x1212 == 14 exactly). */
    um_seed   = rx_q;
    um_acc_hi = (unsigned int)rx_q;
    um_acc_lo = (unsigned int)((unsigned int)rx_q * 14u);

    /* [BIN] 0x8B20D6: the OEM would SRST here if health >= 13. HaniCore does
       NOT - see the header. */

    hc_umkom_phase = 3u;                        /* [BIN] 0x8B1E72            */
    hc_umkom_answers++;

    frame[1] = um_ans;
    frame[2] = 0u;
    frame[3] = 0u;
    hc_umkom_last_tx = um_ans;

    um_acc_hi = (unsigned int)(um_acc_hi + 1u);          /* [BIN] 0x8B20FC    */
    um_acc_lo = (unsigned int)(um_acc_lo + 0x00C7u);
    hc_lf_um_after(um_acc_hi, um_acc_lo, (unsigned int)um_seed, um_ans);
}
