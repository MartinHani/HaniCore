/*
 * hcasicstart.h - the Bosch ME7.1.1 ASIC startup handshake.
 *
 * The states mirror the OEM's own progression, which is gated on the state
 * byte F247 at [BIN] 0x8BE74E: phase 1, then phase 2, then 118-word runtime.
 */
#ifndef HCASICSTART_H
#define HCASICSTART_H

#define HC_ASIC_ST_IDLE          0u
#define HC_ASIC_ST_SSC_INIT      1u
#define HC_ASIC_ST_TX1           2u
#define HC_ASIC_ST_WAIT1         3u
#define HC_ASIC_ST_TX2           4u
#define HC_ASIC_ST_WAIT2         5u
#define HC_ASIC_ST_RUNTIME_TX    6u
#define HC_ASIC_ST_RUNTIME_WAIT  7u

void hc_asic_start_init(void);
/* THE ME7.5 DC's 68HC05 MONITOR, started at the top of boot (bench
   2026-11-01: without a first answer ~90 ms after reset it resets the CPU,
   and this firmware's boot takes longer than that). Until
   hc_asic_start_init() has run, hc_asic_start_service() serves only the
   monitor (hc_asic_mon_service(), called by hc_asic_isr() while hc_asic_up
   is 0); hc_asic_mon_on tells the 1 ms tick to request it. DC only. */
void hc_asic_mon_early(void);
void hc_asic_mon_service(void);
extern unsigned char hc_asic_mon_on;
extern unsigned char hc_asic_up;

/* Drive the handshake. Call from the 1 ms tick; it does at most one state
   transition per call and never blocks. */
void hc_asic_start_service(unsigned int ms);
/* Current runtime supervision, independent of the wrapping success counter. */
unsigned char hc_asic_healthy(void);
extern unsigned char hc_asic_run_live;

extern unsigned char hc_asic_state;
extern unsigned int  hc_asic_next_attempt;  /* last runtime start (period anchor) */
extern unsigned int  hc_asic_start_tx;
extern unsigned int  hc_asic_start_rx;
extern unsigned int  hc_asic_start_ok;
extern unsigned int  hc_asic_start_csum_err;
extern unsigned int  hc_asic_start_timeout;
extern unsigned int  hc_asic_run_tx;
extern unsigned int  hc_asic_run_rx;
extern unsigned int  hc_asic_run_ok;
extern unsigned int  hc_asic_run_csum_err;
extern unsigned int  hc_asic_run_timeout;
extern unsigned int  hc_asic_last_ok_ms;
extern unsigned int  hc_asic_last_xfer_ms;
extern unsigned int  hc_asic_retries;
extern unsigned int  hc_asic_reply_w0;
extern unsigned int  hc_asic_reply_w1;

extern unsigned int  hc_asic_ssc_errors;
extern unsigned int  hc_asic_pec_tx_end;
extern unsigned int  hc_asic_pec_rx_end;
extern unsigned int  hc_asic_busy_refusals;
extern unsigned int  hc_asic_reinits;
extern unsigned int  hc_asic_last_calc;
extern unsigned int  hc_asic_last_recv;

#endif
