#ifndef HCSERIAL711_H
#define HCSERIAL711_H
/* ME7.1.1 K-line transport beneath hcts.c.
 * PEC6 moves ASC0 bytes to the reserved 96-byte XRAM ring without a CPU ISR.
 * The tick drains it, drops reply echo and rearms PEC before buffer exhaustion.
 * Its control level ranks below engine capture, planning and output edges.
 * S0TBINT streams one reply byte and CRC update per entry. A 16-bit output
 * channel is captured together, so task publication cannot tear its bytes.
 * Parsing occurs at bounded main service boundaries; communication waits
 * whenever engine work needs the CPU. */
#include "hctarget.h"

#define HC_TXK_BUF    0u   /* envelope around the job's own copy           */
#define HC_TXK_OCH    1u   /* envelope around output channels              */
#define HC_TXK_PAGE   2u   /* envelope around DESIRED page bytes           */
#define HC_TXK_TLOG   3u   /* envelope around tooth-logger bytes           */
#define HC_TXK_PLAIN  4u   /* the job's own copy, no envelope              */
#define HC_TX_BUF_N   64u

void far hc_pecrx_arm(void);
/* SER.pad: tick publishes a ring boundary after a quiet wire gap; parser
   clears it before consuming the first byte after that boundary. */
#define HC_PECRX_GAP (*(unsigned char volatile *)0xF2D7u)
void far hc_pecrx_tick(void);           /* T8 tick ISR, once per ms          */
void far hc_pecrx_flush(void);          /* drop what has arrived (rate change) */
void far hc_serial_boundary(void);     /* main-loop service boundaries only */
unsigned char far hc_tx_start(unsigned char kind, unsigned char code,
                              unsigned int off, unsigned int n,
                              const unsigned char *src);
unsigned char far hc_tx_busy(void);
unsigned int far hc_tx_sent(void);      /* bytes loaded, echo accounting     */
unsigned int far hc_tx_echo_owed(void);
void far hc_tx_echo_ate(unsigned char all);
unsigned int far hc_tx_echo_age(void);  /* T7 ticks since echo/job progress */
unsigned long far hc_crc32_update(unsigned long crc, unsigned char b);
#endif
