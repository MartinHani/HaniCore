/*
 * hcasic.h - the Bosch ME7.1.1 MAIN <-> ASIC link.
 *
 * On the 4B0906018DC the monitoring module is a 68HC05 answering pulse widths
 * on P2.5. On ME7.1.1 it is a SECOND C167 talking over the SSC, and it is not
 * a passenger: its P1H.2 is ESRST_SM ("Abschaltung EGAS + Endstufen") and its
 * P1H.3 is SWRST_SM ("Abschaltung SG-Rechner"), and the Rechnerkern schematic
 * shows both arriving at the comparator network that drives RSTIN_FR. It can
 * disable the output stages and it can reset this CPU.
 *
 * It also OWNS most of the engine's analog inputs - TMOT on its AN0, TANS on
 * its AN1, TMOT2 on its AN15 - so the frame is not only a safety handshake, it
 * is how a ME7.1.1 knows how warm the engine is.
 *
 * FAIL CLOSED, ALWAYS. Nothing here can enable an output; the only thing a
 * failed exchange does is stop, count, and say so. A bench with no ASIC
 * responding must still leave the K-line alive and TunerStudio connected,
 * which is why every wait is bounded in TIME and nothing here blocks.
 */
#ifndef HCASIC_H
#define HCASIC_H

void asic_init(void);        /* SSC + PEC + pins. Call with IEN still 0.     */
void asic_frame_clear(void); /* the exchange buffer - ONCE, at SSC_INIT only */
void asic_isolate(void);     /* no frame; CS and every SSC pin remain inputs */
unsigned int asic_frame_word(unsigned char i);  /* the RAW buffer */

/* Exported for hcasicstart.c, which owns the startup/runtime state machine.
   The transport primitives stay here because they touch the SSC and the PEC
   and nothing outside this file should. */
unsigned int  hc_asic_frame_sum(unsigned char n);
unsigned char asic_start_transfer(unsigned char n);
void          asic_abort_transfer(void);


/* SSC interrupt bookkeeping, for the transport-level bench log. */
extern unsigned int  hc_ssc_tx_vec;
extern unsigned int  hc_ssc_rx_vec;
extern unsigned int  hc_ssc_err_vec;
extern unsigned int  hc_ssc_last_err;
extern unsigned char hc_ssc_done;
extern unsigned int  hc_ssc_xfer_ticks;
extern unsigned int  hc_ssc_start_t7;      /* T7 when the frame started    */
extern unsigned char asic_err_latched;

/* MEASURED CS-to-first-clock delay in T7 ticks - the V9 experiment. */
extern unsigned int hc_ssc_cs_arm_ticks;

/* The live PEC counts, so a bench run can say how many words actually moved
   rather than only whether the block finished. */
/* V51.  Non-zero while an S5500 frame is actually on the wire.  This, not a
   latched SSCCON error flag, is what a flash window must stand clear of. */
unsigned char hc_asic_frame_in_flight(void);

unsigned int hc_ssc_pec_tx_left(void);
unsigned int hc_ssc_pec_rx_left(void);
unsigned int hc_ssc_sscon(void);

#endif /* HCASIC_H */
