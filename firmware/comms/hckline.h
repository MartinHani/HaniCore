/*
 * hckline.h - HaniCore VAG / KWP vehicle-mode bootstrap core. SHARED CORE.
 *
 * This is the ECU side of the "connect through the car's normal OBD K-line"
 * path. It is a BOUNDED, SFR-INDEPENDENT state machine: it reads the clock and
 * the received bytes the target hands it, and it produces bytes into an output
 * FIFO the target drains. It never touches an SFR, never blocks, never loops
 * unbounded, allocates nothing and uses no floating point, so the SAME object
 * compiles into the C167 image and into the host test on gcc.
 *
 * WHERE THE TARGET STOPS AND THIS CORE STARTS
 * -------------------------------------------
 *   - 5-BAUD RECOGNITION is the TARGET's job, because the OEM does it with GPT
 *     timing on RXD0/P3.11 and there is no portable way to express that here.
 *     When the target's timing logic has decoded a 5-baud address byte it calls
 *     hckline_on_slow_init(); this core validates the address and drives
 *     everything after it.
 *   - Every received UART byte (AFTER the target has swallowed the K-line TX
 *     echo, exactly as hcts_tx() already does) is handed to hckline_on_rx().
 *   - hckline_tick() is called from the main loop; it emits the scheduled
 *     handshake bytes and enforces every timeout.
 *   - The target drains the output FIFO with hckline_tx_pop() into S0TBUF,
 *     consuming the echo per byte just like hcts_tx().
 *   - A private-mode baud change is DEFERRED: the positive response is queued
 *     into the FIFO first; only after the FIFO is empty does hckline_take_baud()
 *     report the switch, so the target changes S0BG strictly AFTER the answer
 *     (and its echo) has left the wire.
 *
 * EVIDENCE CLASSES (see docs/ARCHITECTURE.md for the full table):
 *   - address 0x01 -> sync 0x55, keybytes EF 8F, tester complement 70,
 *     ECU complement FE ............................ OEM PROVEN
 *     (Porsche ME7.1.1 image the target OEM firmware, slow-init records at file
 *      0x877A/0x87F1/0x8869/0x88E1; state machine at seg84:3F48..)
 *   - private high-speed transition after a KWP session ... OEM ARCHITECTURAL
 *     PRECEDENT (Bosch McMess), but OUR SID/wire encoding is a HANICORE
 *     EXTENSION and is labelled as such everywhere.
 */
#ifndef HCKLINE_H
#define HCKLINE_H

/* ------------------------------------------------------------- baud codes --
 * The only rates HaniCore vehicle mode negotiates. One byte on the wire. */
#define HCKLINE_BAUD_10400   0x01u   /* KWP init rate; emergency fallback     */
#define HCKLINE_BAUD_57600   0x02u   /* legacy HaniCore runtime               */
#define HCKLINE_BAUD_124800  0x03u   /* preferred HaniCore runtime (OEM rate) */
#define HCKLINE_BAUD_115200  0x04u   /* TunerStudio's own list offers
                                        115200 and not 124800 (TunerStudioMS
                                        .jar baud list: 9600..57600, 115200,
                                        230400, 250000, 500000, 1000000) */

/* ----------------------------------------------------- HaniCore private SIDs
 *
 * WHY NOT the "10 FA <baud> 48 43" sketch from the research brief.
 * 0x10 is StartDiagnosticSession, a STANDARD ISO 14230 service. Overloading it
 * with a sub-function 0xFA and trailing "HC" would (a) risk a stock ECU that
 * DOES implement 0x10 acting on the request, and (b) hide the magic behind a
 * standard reply code. Instead HaniCore uses the ISO 14230-3
 * systemSupplierSpecific SID range 0xB0..0xBF, which a stock ECU answers with a
 * negative response (0x7F) - so a stock ECU can never be mistaken for HaniCore,
 * and the transition can never fire on one. This is a HANICORE EXTENSION.
 *
 *   0xB0  IDENTIFY   request  data = 'H' 'C'          (0x48 0x43)
 *                    positive 0xF0 + <signature bytes>
 *   0xB1  GOFAST     request  data = <baud-code>
 *                    positive 0xF1 <baud-code>   (sent at the OLD baud)
 *
 * 0xB1 is honoured ONLY after a 0xB0 in the same session has succeeded - that
 * is the identity gate. A positive 0xB0 is REQUIRED before any baud change. */
#define HCKLINE_SID_IDENTIFY   0xB0u
#define HCKLINE_SID_GOFAST     0xB1u
#define HCKLINE_RESP_OFFSET    0x40u   /* positive response = SID + 0x40      */

/* Standard KWP services we answer (minimum for a reliable bootstrap). */
#define HCKLINE_SID_START_COMM   0x81u  /* StartCommunication                 */
#define HCKLINE_SID_STOP_COMM    0x82u  /* StopCommunication                  */
#define HCKLINE_SID_START_DIAG   0x10u  /* StartDiagnosticSession             */
#define HCKLINE_SID_TESTER_PRES  0x3Eu  /* TesterPresent                      */
#define HCKLINE_SID_NEG          0x7Fu  /* negative response                  */

/* Negative response codes (ISO 14230-3) we use. */
#define HCKLINE_NRC_SVC_NOT_SUPP 0x11u  /* serviceNotSupported                */
#define HCKLINE_NRC_SUBF_NOT_SUP 0x12u  /* subFunctionNotSupported            */
#define HCKLINE_NRC_COND_WRONG   0x22u  /* conditionsNotCorrect (not identified)*/
#define HCKLINE_NRC_FMT          0x13u  /* messageLengthOrFormatIncorrect     */

/* ------------------------------------------------------------- the states -- */
#define HCKLINE_ST_IDLE        0u   /* nothing; waiting for a 5-baud address   */
#define HCKLINE_ST_SYNC        1u   /* addr accepted; W1 then send 0x55        */
#define HCKLINE_ST_KB1         2u   /* W2 then send keybyte 1                  */
#define HCKLINE_ST_KB2         3u   /* W3 then send keybyte 2                  */
#define HCKLINE_ST_COMPL       4u   /* wait tester complement (~KB2) within W4 */
#define HCKLINE_ST_ECU_COMPL   5u   /* got it; send ECU complement (~addr)     */
#define HCKLINE_ST_SESSION     6u   /* KWP frames                              */
#define HCKLINE_ST_PRIVATE     7u   /* raw HaniCore mode; dormant until reset  */

/* Sizes. A vehicle-mode KWP frame is tiny; 64 is generous and a power of two
   is not required here (no masked ring). */
#define HCKLINE_RX_MAX   64u
#define HCKLINE_TX_MAX   64u
#define HCKLINE_SIG_MAX  32u

/* ------------------------------------------------------------ configuration
 * All timings in microseconds. Defaults (hckline_default_cfg) are OEM/ISO
 * ranges; a target may override any of them from hctarget.h. */
typedef struct {
    unsigned char  addr;        /* accepted 5-baud address (0x01, OEM PROVEN)  */
    unsigned char  sync;        /* 0x55                                        */
    unsigned char  kb1;         /* keybyte 1 (0xEF)                            */
    unsigned char  kb2;         /* keybyte 2 (0x8F)                            */
    unsigned char  ecu_addr;    /* our KWP address (target of tester frames)   */
    unsigned char  tester_addr; /* expected tester address (source)            */

    unsigned long  w1_us;       /* addr end -> sync   (ISO 60..300 ms)         */
    unsigned long  w2_us;       /* sync -> keybyte 1  (ISO 5..20 ms)           */
    unsigned long  w3_us;       /* keybyte1 -> keybyte2 (ISO 0..20 ms)         */
    unsigned long  w4_us;       /* keybyte2 -> tester complement, max wait     */
    unsigned long  p2_us;       /* request -> our response, max                */
    unsigned long  p3_us;       /* session inactivity -> IDLE                  */

    unsigned char  retries;     /* complement retries (OEM does one)           */

    const unsigned char *sig;   /* IDENTIFY payload (after 0xF0)               */
    unsigned char  sig_len;     /* its length (<= HCKLINE_SIG_MAX)             */
} hckline_cfg_t;

/* --------------------------------------------------------------- the state -- */
typedef struct {
    hckline_cfg_t cfg;

    unsigned char state;
    unsigned long t_state;      /* when the current state was entered          */
    unsigned long t_rx;         /* when the last VALID frame completed (P3)    */

    /* frame assembly */
    unsigned char rx[HCKLINE_RX_MAX];
    unsigned char rx_len;       /* bytes buffered so far                       */
    unsigned char rx_need;      /* total bytes expected (0 = header not parsed)*/

    /* output FIFO */
    unsigned char tx[HCKLINE_TX_MAX];
    unsigned char tx_head;
    unsigned char tx_tail;

    /* session */
    unsigned char identified;   /* a 0xB0 succeeded this session               */
    unsigned char retry_used;

    /* deferred baud switch */
    unsigned char baud_pending; /* nonzero = a switch is queued behind the FIFO*/
    unsigned char baud_code;

    /* counters (published by target telemetry) */
    unsigned int  init_ok;
    unsigned int  init_fail;
    unsigned int  frames_ok;
    unsigned int  frames_bad;   /* checksum / format rejects                   */
    unsigned int  nak_sent;
    unsigned int  wrong_addr;   /* 5-baud address that was not ours            */
    unsigned int  sess_drops;   /* sessions ended by a run of bad frames       */
    unsigned char bad_run;      /* bad bursts since the last good frame        */
    unsigned long t_bad;        /* when bad_run last counted                   */
    unsigned long t_byte;       /* when the last SESSION byte arrived          */
} hckline_t;

/* A SESSION ends after this many consecutive bad frames. A tester that
   abandons the session and starts talking at another rate (TunerStudio at
   57600 into a 10400 receiver) produces nothing BUT bad frames; before V95
   every byte of it refreshed P3, so the session - and the line - stayed at
   10400 for as long as the host kept retrying (bench, V94, 2026-09-28: no
   answer in 40 attempts / 20 s). */
#define HCKLINE_BAD_RUN_MAX  3u
/* ...counted once per burst: every byte after a malformed header restarts the
   parse, so one corrupted frame is several "bad frames" - it must cost one. */
#define HCKLINE_BAD_BURST_US 25000uL
/* A partial frame whose next byte comes later than this is stale and dropped
   (as one bad burst). ISO 14230 P4max, the tester's inter-byte time, is
   20 ms; the margin covers a target whose clock advances once per main-loop
   pass. Without it a garbage byte that looks like a long header swallowed
   the tester's next real request. */
#define HCKLINE_STALE_US     60000uL

/* Fill cfg with the OEM/ISO defaults (address 0x01, EF 8F, FE ...). */
void hckline_default_cfg(hckline_cfg_t *cfg);

/* Bring the core up in IDLE with the given configuration. */
void hckline_init(hckline_t *k, const hckline_cfg_t *cfg);

/* Force back to IDLE (dropped private session, session timeout, target reset).
   Clears the FIFO and any pending baud switch; keeps counters. */
void hckline_reset(hckline_t *k);

/* The target decoded a 5-baud address. Only cfg.addr starts a handshake; any
   other address is counted and ignored (a stock cluster/gateway that is
   "closed until valid 5-baud 0x01" behaves the same way). */
void hckline_on_slow_init(hckline_t *k, unsigned char addr, unsigned long now_us);

/* One received byte (echo already removed by the target). */
void hckline_on_rx(hckline_t *k, unsigned char b, unsigned long now_us);

/* Main-loop service: emit scheduled handshake bytes, enforce timeouts. */
void hckline_tick(hckline_t *k, unsigned long now_us);

/* Drain one output byte. Returns 1 and sets *b, or 0 when the FIFO is empty. */
unsigned char hckline_tx_pop(hckline_t *k, unsigned char *b);

/* Nonzero while the FIFO still holds bytes (target waits for this before a
   baud switch). */
unsigned char hckline_tx_busy(const hckline_t *k);

/* When a private high-speed transition has been answered AND the FIFO has
   drained, this returns 1 once and reports the negotiated baud code. The
   target then reprograms the UART and calls hckline_enter_private(). */
unsigned char hckline_take_baud(hckline_t *k, unsigned char *code);

/* The target has switched the UART; the K-line now carries raw HaniCore
   traffic. The core goes dormant until hckline_reset(). */
void hckline_enter_private(hckline_t *k);

#endif /* HCKLINE_H */
