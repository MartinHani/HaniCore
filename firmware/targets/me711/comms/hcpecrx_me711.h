/*
 * hcpecrx_me711.h - ASC0 receive via PEC channel 6 into an XRAM ring.
 *
 * WHY THIS EXISTS
 * ---------------
 * HaniCore's runtime RX path is a CC7 CAPCOM compare tick that drains S0RBUF
 * every HC_RXTICK_US (40 us) - see hcts.c hc_cc7_isr(). At 57600 baud a byte is
 * 174 us, so four drains per byte leaves margin. At 124800 baud a byte is 80 us
 * and the 40 us tick has only ~2 slots per byte; with the crank capture stealing
 * ~18 % of those slots (measured, V57), the register overruns. The OEM does NOT
 * poll: it moves S0RBUF into an XRAM buffer with PEC channel 6, one stolen bus
 * cycle per byte, no per-byte CPU handler.
 *
 *   OEM PROVEN (Porsche ME7.1.1 the target OEM firmware):
 *     seg84:3E40  MOV  S0RIC, #003Eh     ; ILVL 15, GLVL 2, IE clear at setup
 *     seg84:3E4A  MOV  S0EIC, #0066h     ; error interrupt ILVL ...
 *     seg83:AF08  MOV  FCFA (DSTP6), #E0A2h  ; PEC6 dest = XRAM buffer base
 *     seg83:AF18  MOV  PECC6, (count)|0x0300 ; arm channel 6
 *   S0RBUF (0xFEB2) is the fixed PEC source; DSTP6 walks the XRAM buffer.
 *
 * STATUS: this module is COMPLETE and self-contained but is NOT yet wired into
 * hcmain_me711.c. That wiring is deliberately deferred to the V90 reconciliation
 * pass (the other session owns hcmain/hcvec right now). Until this path is
 * PHYSICALLY QUALIFIED at 124800, the CC7 polling drain in hcts.c remains the
 * default and the fallback. Selecting this path is a build-time decision
 * (HC_RX_USE_PEC6), never a silent replacement.
 *
 * HOST TESTABILITY: the ring index arithmetic (hc_pecrx_*) touches no SFR and is
 * exercised by tests/host/test_hcpecrx.c. The SFR setup / ISR below it is
 * compiled only on the target (guarded by !HC_PECRX_HOST_TEST).
 */
#ifndef HCPECRX_ME711_H
#define HCPECRX_ME711_H

/* The XRAM ring. Size MUST be a power of two: head/tail wrap by masking, which
   is what makes the producer/consumer split free of a critical section. 256 at
   124800 gives the main loop ~20 ms of slack (256 bytes * 80 us). */
#ifndef HC_PECRX_SIZE
#define HC_PECRX_SIZE 256u
#endif
#define HC_PECRX_MASK (HC_PECRX_SIZE - 1u)

/* Pure ring state. `buf` points at the XRAM ring on the target; on the host it
   points at an ordinary array. head/tail are FREE-RUNNING counts (not masked),
   so their unsigned difference is the number of unread bytes and an overflow is
   simply (head - tail) > size. The byte at ring position i lives at
   buf[i & mask]. */
typedef struct {
    unsigned char *buf;
    unsigned int   size;       /* power of two                                 */
    unsigned int   mask;       /* size - 1                                     */
    unsigned int   head;       /* bytes the producer (PEC) has delivered       */
    unsigned int   tail;       /* bytes the consumer has taken                 */
    unsigned int   overflow;   /* times the producer lapped the consumer       */
    unsigned int   frame_err;  /* ASC0 framing errors (wire is wrong)          */
    unsigned int   hw_ovr;     /* ASC0 hardware overrun (a byte was destroyed) */
} hc_pecrx_t;

/* --- pure ring API (no SFR; host-tested) --- */

/* Bind the ring to its backing buffer and clear it. size must be a power of two. */
void hc_pecrx_ring_init(hc_pecrx_t *r, unsigned char *buf, unsigned int size);

/* The producer delivered `n` more bytes into the ring (the PEC/ISR path calls
   this after advancing DSTP6, or a host test after copying test data in). If the
   delivery laps the consumer, the OLDEST unread bytes are discarded and overflow
   is counted - a lost byte must never be read as valid. */
void hc_pecrx_produced(hc_pecrx_t *r, unsigned int n);

/* Unread byte count. */
unsigned int hc_pecrx_available(const hc_pecrx_t *r);

/* Pop one byte in order. Returns 1 and sets *b, or 0 if the ring is empty. */
unsigned char hc_pecrx_pop(hc_pecrx_t *r, unsigned char *b);

#ifndef HC_PECRX_HOST_TEST
/* --- target-only SFR path (compiled into the C167 image) ---
 *
 * NO COMPLETION INTERRUPT. This is the whole reason the design looks the way it
 * does. When PECC6's count reaches 0 the ASC0 receive request stops being
 * PEC-serviced and becomes a NORMAL interrupt on trap 0x2B (S0RINT) - and on
 * this ECU family that first-level vector is owned by the Bosch boot block
 * (0x003576: EXTR / BSET S0EIR / RETI), which hands the byte to the flash
 * bootstrap loader's receiver. HaniCore must never let that happen. So, exactly
 * as the OEM does, the count is TOPPED UP from the main-loop consumer while it
 * is still positive; the completion vector is never taken.
 *
 * See hctarget.h "first-level vector ownership" and hcts.c hcts_rx_learn(). */

/* Arm ASC0 RX on PEC channel 6 into the module's XRAM ring. Call with IEN still
   0, exactly like hcts_rx_arm(). Idempotent. */
void hc_pecrx_arm(void);

/* The consumer, run from the main loop. It (1) advances the ring head by however
   many bytes PEC has moved since the last call, from the live DSTP6 pointer;
   (2) folds in ASC0 framing/overrun error flags; (3) TOPS UP PECC6 so the count
   never approaches 0. Bounded, never blocks, no critical section. Must be called
   often enough that fewer than (pass) bytes arrive between calls - at 124800 a
   128-byte pass is ~10 ms, and the main loop runs far faster than that. */
void hc_pecrx_service(void);

/* Published accessor for telemetry (overflow / frame_err / hw_ovr counters). */
extern hc_pecrx_t hc_pecrx;
#endif /* HC_PECRX_HOST_TEST */

#endif /* HCPECRX_ME711_H */
