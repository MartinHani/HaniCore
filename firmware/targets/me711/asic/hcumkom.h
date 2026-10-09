/*
 * hcumkom.h - the Bosch ME7.1.1 runtime supervision (UMKOM) responder.
 *
 * The recurring SWRST_SM on this ECU is the Bosch level-2 question/answer
 * monitor, carried in words 1..3 of the 118-word runtime SSC frame. The OEM
 * OEM ME7.1.1 handler is `um_service` at [BIN] 0x8B1E24 (A1104F homolog 0x8CDB96,
 * byte-identical logic). This module reproduces its MAIN side.
 *
 * Full derivation, cross-witness table and the closed-loop simulation that
 * validated it: docs/ARCHITECTURE.md.
 *
 * WHY THIS IS SAFE TO PORT WITHOUT THE S5500 ROM: the Bosch S5500 and the
 * OEM ME7.1.1 MAIN ship together and work on real hardware, so the S5500 is built
 * to accept exactly what `um_service` produces. `um_service` is deterministic
 * and fully characterised; running it verbatim reproduces the accepted
 * sequence. The one thing this module deliberately drops is the OEM's
 * `8092 >= 13 -> SRST` (that is MAIN policing the S5500, not the reverse - it
 * cannot stop an S5500 that has already decided to reset us, and a HaniCore
 * self-reset helps nothing). The health counter is still tracked, for
 * telemetry only.
 */
#ifndef HCUMKOM_H
#define HCUMKOM_H

/* Call once, before the first runtime exchange (mirrors [BIN] 0x8B2188). */
void hc_umkom_init(void);

/* Call on EVERY runtime frame build, after the header is set and before the
 * checksum is computed, with a pointer to the in-place SSC frame buffer
 * (word 0 first). It reads words 1..3 (the S5500's reply, still in the
 * buffer from the previous in-place exchange), and writes words 1..3 with
 * this cycle's response. Mirrors one raster call of [BIN] 0x8B1E24 followed
 * by the accumulator advance of [BIN] 0x8B20FC.
 *
 * Internally it processes once every 4 calls (the OEM's 8094 phase) and
 * re-transmits the last answer on the other 3 - one question/answer per
 * ~40 ms at a 10 ms runtime raster, exactly the FR's "new question on a
 * 40 ms raster".
 */
void hc_umkom_service(unsigned int volatile far *frame);

/* Telemetry - published on the bench line, never gates anything. */
extern unsigned char hc_umkom_health;    /* OEM 8092: -1 ok / +3 wrong        */
extern unsigned char hc_umkom_expect;    /* OEM 8091: the shared sync counter */
extern unsigned char hc_umkom_phase;     /* OEM 8094: 4, then 3..0 cycle      */
extern unsigned int  hc_umkom_answers;   /* process cycles completed          */
extern unsigned int  hc_umkom_mismatch;  /* counter-nibble mismatches seen    */
extern unsigned int  hc_umkom_last_rx;   /* last received word 1              */
extern unsigned int  hc_umkom_last_tx;   /* last transmitted word 1          */

#endif
