/*
 * hckwp_me711.h - VAG/KWP vehicle-mode entry on the ME7.1.1. FAR.
 *
 * The glue between the K-line hardware and the target-independent KWP core
 * (comms/hckline.c): the 5-baud address is decoded HERE from the RXD0 pin
 * level (P3.11) sampled once a millisecond, the UART is moved to 10400 for
 * the handshake and the KWP session, received bytes are routed to the core
 * instead of the TunerStudio parser, the core's output is transmitted through
 * hcts_tx() (so the echo accounting is the same one), and a HaniCore GOFAST
 * (0xB1) hands the line back to the TunerStudio parser at the negotiated
 * rate, LOCKED. A failed or timed-out session returns the line to the rate
 * hunt (hcts.c "THE LINK RATE"). See docs/ARCHITECTURE.md.
 *
 * WHY THE PIN AND NOT THE UART FOR THE 5-BAUD BYTE: 5 baud is 200 ms a bit,
 * far below any ASC0 rate, and the OEM decodes it on RXD0/P3.11 with timer
 * logic too (the maintainer's design records, OEM seg84:3F48). A millisecond
 * sample is 0.5 % of a bit. A UART byte cannot hold the line low for the
 * 180 ms the start bit must, so TunerStudio traffic cannot start a decode;
 * three high samples abort one within ~3 ms and the receive path is not
 * touched until the start bit has qualified.
 */
#ifndef HCKWP_ME711_H
#define HCKWP_ME711_H

/* THE SHARED-BUS ENTRY STATE (2026-10-13, ME711_OBD_KLINE.md section 6), in
   external SRAM (TGT_RAM_KLINE: the far modules' XRAM is full). The 1 ms
   tick measures every LOW run of the RXD0 pin exactly (HC_KL_TICK); the main
   loop reads the finished run - an ISO 14230 fast-init wake-up is TiniL
   25 ms low then 25 ms high, and no UART byte (< 1 ms of low) or 5-baud bit
   (200 ms) lands in 20..30 ms. */
typedef struct {
    unsigned char st;          /* KL_PV: a GOFAST rate is on probation      */
    unsigned char lowcnt;      /* ms the pin has been low (tick, <= 255)    */
    unsigned char run;         /* the last finished low run, ms; 0 = taken  */
    unsigned char asic_prep;   /* hcasicstart.c: the NEXT runtime frame's
                                  build step, done between frames (0 none,
                                  1 payload zeroed, 2 complete) - parked here
                                  because near RAM has no byte left */
    unsigned char run_t;       /* tick_ms when that run ended (mod 256)     */
    unsigned char rxp;         /* low byte of DSTP6 at the last tick: a byte
                                  the UART received ends a low run          */
    unsigned int  t_pv;        /* when the GOFAST rate was taken, ms        */
} kl_t;
#define HC_KL   (*(kl_t huge *)(TGT_EXTRAM_BASE + TGT_RAM_KLINE))
/* hc_tick_isr, every ms: `hi` = the RXD0 pin (P3.11), `rxp` = the low byte
   of the PEC6 receive pointer (DSTP6). FAR - an inline copy cost 74 bytes of
   the near code that has none left. */
void far hc_kl_tick(unsigned char hi, unsigned char rxp, unsigned int now);

void far hc_kwp_init(void);
/* main loop, every pass: the ms tick and the RXD0 pin level (1 = idle high) */
void far hc_kwp_service(unsigned int ms, unsigned char rxd_high);
/* hcts_poll(): 1 = this received byte belongs to the KWP side (or is noise
   inside a 5-baud byte) and must not reach the TunerStudio parser */
unsigned char far hc_kwp_rx_take(unsigned char b);
/* 1 while a 5-baud byte is being decoded or a KWP session owns the line: the
   TunerStudio rate hunt must not act on what it receives */
unsigned char far hc_kwp_active(void);
/* OCH 844: bits 0..3 hckline state, 4..6 5-baud decoder stage, 8..15 good
   inits (mod 256). OCH 846: bits 8..15 failed inits, 0..7 wrong addresses. */
unsigned int far hc_kwp_state(void);
unsigned int far hc_kwp_counts(void);
/* KWP sessions ended by a run of bad frames (mod 256). */
unsigned char far hc_kwp_drops(void);

#endif
