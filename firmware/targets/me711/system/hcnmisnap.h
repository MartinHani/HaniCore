/*
 * hcnmisnap.h - the NMI post-mortem for the Bosch ME7.1.1.
 *
 * NOT COMPILED INTO RESETDIAG_V2. Prepared for the image after it.
 *
 * The bench already showed NMI fires immediately before the reset (TR=0002,
 * written from HaniCore's own catch-all and still readable afterwards). So
 * there IS time to run code in the NMI. This module spends that time on the
 * one question the bench cannot otherwise answer:
 *
 *      did the 5 V rail collapse, or did something ASK us to reset?
 *
 * Both arrive as "NMI then a long hardware reset via RSTIN" because the CJ910
 * supply's RES output and the ASIC's SWRST_SM are wired-OR onto the same
 * LM2901 network. Inside the CPU they are indistinguishable AT THE MOMENT OF
 * THE RESET. They are NOT indistinguishable in the seconds before it: a
 * collapsing rail drags UBAT down with it, and an ASIC request does not.
 *
 * Hence a HISTORY, not a sample. The main loop drops one UBAT reading per
 * millisecond into a small ring; the NMI handler copies the ring out. A
 * falling ramp is a supply event. A flat line at battery voltage right up to
 * the last millisecond is not.
 */
#ifndef HCNMISNAP_H
#define HCNMISNAP_H

#define NMISNAP_HIST   8u        /* 8 ms of UBAT history */

/* Feed one UBAT reading. Call from the 1 ms tick with whatever the ADC last
   produced for TGT_ADC_UBAT - this must NOT start a conversion. */
void hc_nmisnap_feed(unsigned int ubat_counts);

/* Arm the snapshot area: stamp the magic and clear the current record. Call
   once at startup AFTER the previous record has been read out. */
void hc_nmisnap_init(void);

/* THE HANDLER SIDE. Straight-line stores only: no loop bound that depends on
   data, no call into another module, no ADC start, no serial. Everything it
   writes is already in RAM or is one SFR read. */
void hc_nmisnap_capture(unsigned int tick_ms, unsigned int stage);

/* READ-OUT, from the next boot. Returns 1 if a valid previous record exists.
   Fills the caller's fields; ubat_hist must have room for NMISNAP_HIST. */
unsigned char hc_nmisnap_prev(unsigned int *tick_ms,
                              unsigned int *stage,
                              unsigned int *p3,
                              unsigned int *p6,
                              unsigned int *wdt,
                              unsigned int *ubat_hist);

/* Convenience for the bench line: the slope of the stored history, as
   (oldest - newest) in ADC counts. Positive means UBAT was FALLING. */
int hc_nmisnap_prev_slope(void);

#endif
