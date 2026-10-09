/*
 * hcasicdump.h - freeze one real ASIC reply and get it out in ONE flash.
 *
 * The ECU resets every ~310 ms, so a 96-word frame cannot be printed in one
 * run. It is frozen in battery-backed SRAM instead and printed one chunk per
 * boot, with a persistent cursor, so every chunk belongs to the SAME frame.
 */
#ifndef HCASICDUMP_H
#define HCASICDUMP_H

void hc_asicdump_init(void);

/* copy the runtime FRAME and the run_tx/run_rx/run_ok/state counters out
   of on-chip XRAM/IRAM ONE time, on the boot after the one that received
   them, before hc_asic_start_init() (or anything else) can clear them. Valid
   only when PONR is clear and run_tx==run_rx==2 - see the long comment at its
   definition. First valid salvage wins; later boots do not disturb it. */
void hc_asicdump_salvage(unsigned int reset_raw);

/* Freeze a completed reply. Slot 0 = the first seen; slot 1 = the first seen
   in a DIFFERENT ASIC state. Neither is ever overwritten. */
/* The V11 echo record: words 1..3 as they stood BEFORE the first runtime
   build, and words 0..3 as they went out after it. They must match. */
void hc_asicdump_echo(unsigned int r1, unsigned int r2, unsigned int r3,
                      unsigned int t0, unsigned int t1,
                      unsigned int t2, unsigned int t3);

/* Stash the transmitted words 0..3 for the exchange about to happen. */
void hc_asicdump_txprefix(unsigned int w0, unsigned int w1,
                          unsigned int w2, unsigned int w3);

void hc_asicdump_capture(unsigned char st, unsigned int xfer,
                         unsigned int nwords, unsigned int calc,
                         unsigned int recv, unsigned int ms,
                         unsigned int runtx);

/* Print one chunk and advance the cursor. 0 = nothing left to print. */
unsigned char hc_asicdump_print(void);

extern unsigned char hc_dump_slots_full;

#endif
