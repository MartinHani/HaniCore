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

/* The state machine, published as asicState. */
#define ASIC_OFF        0    /* not initialised                              */
#define ASIC_IDLE       1    /* SSC up, nothing in flight                    */
#define ASIC_START_TX   2    /* the 96-word startup frame is in flight       */
#define ASIC_START_OK   3    /* it came back, checksum and class good        */
#define ASIC_RUN_TX     4    /* a 118-word runtime frame is in flight        */
#define ASIC_RUN_OK     5    /* runtime traffic is flowing                   */
#define ASIC_FAULT      6    /* latched: too many failures in a row          */

void asic_init(void);        /* SSC + PEC + pins. Call with IEN still 0.     */
void asic_frame_clear(void); /* the exchange buffer - ONCE, at SSC_INIT only */
void asic_isolate(void);     /* no frame; CS and every SSC pin remain inputs */
void asic_service(void);     /* the state machine, from the main loop        */
void asic_tick(void);        /* 1 ms, from the system tick ISR               */
unsigned int asic_rx_word(unsigned char i);
unsigned int asic_frame_word(unsigned char i);  /* the RAW buffer */   /* an ACCEPTED frame word      */

/* The CS-only experimental stimulus. No clock, no data, no SSC - see the long
   note in hcasic.c for exactly what it does and does not prove. */

/* Everything below is telemetry. Public because hcmain_me711.c publishes it
   and because the first bench test is judged on it. */
extern unsigned char asic_state;
extern unsigned char asic_alive;        /* a frame was accepted recently     */
extern unsigned char asic_last_class;   /* the reply class byte we last saw  */
extern unsigned int  asic_tx_count;
extern unsigned int  asic_rx_count;
extern unsigned int  asic_start_count;
extern unsigned int  asic_run_count;
extern unsigned int  asic_csum_ok;
extern unsigned int  asic_csum_err;
extern unsigned int  asic_class_err;
extern unsigned int  asic_timeouts;
extern unsigned int  asic_ssc_err;      /* SSCCON error bits, latched        */
extern unsigned int  asic_last_csum;    /* what the last frame summed to     */
extern unsigned int  asic_want_csum;    /* what its checksum word claimed    */


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
