/*
 * hcts.h - HaniCore's K-line transport and TunerStudio server.
 *
 * THIS IS SHARED CORE. One copy, compiled into every target. The board it is
 * running on reaches it only through hctarget.h and through the two hooks at
 * the bottom of this file - nothing in hcts.c knows what an injector is.
 *
 * It is not new code. Every line of it was lifted from the 4B0906018DC
 * firmware that is bench-proven at 57600 baud with TunerStudio connected, and
 * it carries that firmware's measurements with it:
 *
 *   - the K-line echoes every transmitted byte straight back into our own
 *     receiver, so tx() consumes its own echo (bench, 2026-08-23);
 *   - ASC0 has ONE receive register and a byte survives one byte-time, so the
 *     register is drained by an interrupt into a ring (bench, 2026-08-24);
 *   - a reply is CRC'd as it is transmitted, never buffered, so the output
 *     channel block is answered in one request instead of three;
 *   - a first byte of 0x00 is an envelope length, anything else is a plain
 *     legacy command (rusEFI tunerstudio.cpp).
 *
 * What a target must define in its hctarget.h:
 *
 *   TGT_S0BG          ASC0 reload for TGT_BAUD
 *   TGT_BAUD          documentation only
 *   TGT_SIGNATURE     the TunerStudio signature string
 *   TGT_VERSIONTXT    the human-readable build string
 *   TGT_OCH_SIZE      output-channel block size, == ochBlockSize in the .ini
 *   TGT_EXTRAM_BASE / TGT_RAM_OCH     where that block lives
 *   TGT_TRAP_CC7INT / HC_RXTICK_US    the receive drain tick
 *   TGT_ILVL_SERIAL, HC_IC(), US_TO_TICKS(), HC_PROBE_CLAIM()
 *
 * What a target must implement (see the hooks at the bottom).
 */
#ifndef HCTS_H
#define HCTS_H

/* ===================== THE RESPONSE CODES, AND TUNERSTUDIO'S OWN RULE =====
 *
 * The names are rusEFI's protocol reference -
 * rusEFI firmware/integration/ts_protocol.txt, lines 34-64. The RULE
 * below is not from any document: it was read out of TunerStudio MS 3.3.01
 * itself, because the documents do not say it and this project guessed wrong
 * once already.
 *
 *     TunerStudioMS.jar, class J/f, method b(byte[], byte[]):
 *
 *         int code = d(response);          // response[2], the code byte
 *         if ((code & 0x80) != 0x80) {
 *             return true;                 // ACCEPTED, and never looked at
 *         }
 *         ... one arm per code, 0x80 through 0x90 ...
 *         return false;                    // EVERY one of them
 *
 * **A RESPONSE CODE WITH BIT 7 SET IS A PROTOCOL ERROR AND COSTS THE SESSION.
 * THERE IS NO SOFT ERROR CODE.** Under-run, over-run, bad CRC, unrecognised
 * command, out of range, BUSY, flash locked, two sequence failures, four CAN
 * faults, parity, framing, noise, unknown - every one is named, counted and
 * then fails the packet identically. The caller
 * logs `call failed protocol validation`, throws
 * `Response packet failed validation`, goes offline and handshakes again.
 *
 * A code with bit 7 CLEAR is accepted without the value being inspected at
 * all, which is why rusEFI's TS_RESPONSE_BURN_OK (4) works as well as 0.
 *
 * SO: THESE THREE MAY ONLY ANSWER A GENUINE PROTOCOL FAULT.
 *
 *   TS_BAD_CRC       the request's own CRC32 did not check out
 *   TS_BAD_CMD       the command BYTE is not one this server implements
 *   TS_OUT_OF_RANGE  defined for completeness; nothing here sends it
 *
 * A command that was understood and could not be carried out is NOT a
 * protocol fault, and it has nowhere to say so in the response code. It says
 * so in the output channels instead - see TS_REFUSED.
 *
 * MEASURED ON THE PORSCHE ME7.1.1, 2026-09-16, V59, and it is what this
 * paragraph exists for. A Burn of a page that fails validation answered
 * `00 01 83 A6 B3 3D 17` in 22 ms. The refusal was correct. Calling it 0x83
 * was not, and TunerStudio said so in its own words:
 *
 *     12:09:11  Queueing burn to page:1
 *     12:09:12  Warning: Controller Reported a Unrecognized Command!
 *     12:09:12  call failed protocol validation, 1 failed, 574 successful
 *     12:09:15  Going offline before all changes were permanently saved
 *     12:09:16  Sig Bytes: rusEFI Hanicore v1          <- reconnect 1
 *     12:09:17  CRC failure on received payload         <- the stream it
 *     12:09:19  Timeout, Expected bytes: 65475             abandoned bytes in
 *     12:09:20  Re-establishing connection              <- reconnect 2
 *     12:09:23  Timeout, Expected bytes: 30915
 *     12:09:27  Re-establishing connection (x2)         <- reconnects 3, 4
 *
 * bench measurements The later reconnects are the first one's wake:
 * a host that abandons a session mid-reply leaves bytes in its own receive
 * buffer, and reads them as the front of the next reply until they run out.
 */
#define TS_OK           0x00
#define TS_BAD_CRC      0x82
#define TS_BAD_CMD      0x83
#define TS_OUT_OF_RANGE 0x84

/* AN OPERATION THE ECU UNDERSTOOD, ACCEPTED AND THEN COULD NOT COMPLETE.
 *
 * It is TS_OK, and that is deliberate rather than convenient. The reply to a
 * Burn is an ACKNOWLEDGEMENT OF THE REQUEST - "I heard you, I am done working
 * on it, ask me anything" - because the protocol gives it no way to be
 * anything else. Every code that could carry "no" ends the session, and a
 * session ended by a refusal is a worse outcome than the refusal.
 *
 * THE VERDICT IS A CHANNEL, NOT A CODE, and every one of these is already in
 * the .ini and on the dashboard:
 *
 *   nvmState           6 = BURN FAILED, the PREVIOUS record still stands
 *   nvmError           low byte, HCNV_ERR_* - 2 = would not validate
 *   cfgValidation      HC_VAL_* over DESIRED; 0 means runnable
 *   cfgFirstBadOffset  the page offset of the first rule that failed
 *   nvmBurnFailed / nvmNotBurned   the indicators that light because of them
 *
 * So the tuner is told, in words, which setting is wrong - which is more than
 * a response code could ever have carried, and more than 0x83 told them.
 */
#define TS_REFUSED      TS_OK

/* What TunerStudio is told it may ask for in one go. 256 because the reply
   path streams: the whole output-channel block fits in ONE request. */
#define BLOCKING       256
#define RXMAX          72

/* The output channel block lives in the EXTERNAL SRAM, not in near RAM. Near
   RAM is under 2 KB on this part and the block's only destination is a serial
   wire, so a few cycles per byte to fetch it from external memory costs
   nothing measurable and buys back the room the engine modules need. */
#define OCH   ((unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_OCH))
/* V97 (ME7.1.1): a block longer than its SRAM region continues in a second
   region - offsets >= TGT_OCH_SPLIT are served from TGT_RAM_OCH2. A target
   without the split reads one region, as before. */
#ifdef TGT_OCH_SPLIT
#define OCH2  ((unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_OCH2))
#define OCH_BYTE(o) (((o) < TGT_OCH_SPLIT) ? OCH[o] : OCH2[(o) - TGT_OCH_SPLIT])
#else
#define OCH_BYTE(o) (OCH[o])
#endif

/* ---------------------------------------------------------------- the API */

void hc_srvwdt(void);
#ifdef TGT_RSTDIAG_WDT_COUNT
extern unsigned int hc_wdt_services; /* runtime services since main init     */
#endif
void hcts_init(void);              /* ASC0 up, state cleared. Before any tx. */
void hcts_poll(void);              /* drain the register, parse a request    */
void hcts_service(void);           /* answer a parsed request                */
void hcts_rx_pump(void);           /* the polled drain, for wait loops       */
unsigned char hcts_rx_pop(unsigned char *b);   /* one byte out of the ring    */
void hcts_tx(unsigned char c);     /* one byte, and consume its own echo     */
void hcts_tx_end(void);            /* TGT_TX_PIPELINE: wait for the last echo */
/* TGT_S0BG_ALT: bits 0..1 rate (0 TGT_S0BG, 1 _ALT, 2 _ALT2), bit 4 locked,
   bits 8..15 rate changes since boot (mod 256). 0 on a target without it. */
unsigned int hcts_link_state(void);
/* rate-evidence events counted since boot (mod 256) - framing errors,
   bad CRCs, impossible first/length bytes; one per burst. */
unsigned char hcts_link_evid(void);
/* TGT_S0BG_ALT: put the line at raw S0BG `bg` (locked or not) / back to the
   boot rate hunting. For a target that negotiates a rate itself (KWP). */
void hcts_link_force(unsigned char bg, unsigned char locked);
void hcts_link_hunt(void);
void hcts_puts(const char *s);
void hcts_hex4(unsigned int v);    /* four hex digits, for boot banners      */
unsigned long hcts_crc32(unsigned char *p, unsigned int n);
void hcts_send_response(unsigned char code, unsigned char *data, unsigned int n);
void hcts_defer_response(void);
void hcts_finish_deferred_response(unsigned char code);

/* Find out which trap ASC0's receive interrupt uses, or fall back to a CAPCOM
   compare tick. Both are CHECKED at boot, never assumed - see hcts.c. */
void hcts_rx_learn(void);
/* Arm whichever receive path the probe found. Call once, with IEN still 0. */
void hcts_rx_arm(void);
/* Deliberately do nothing for n milliseconds, servicing only the on-chip
   watchdog. The stall test that proves the responder is not in the main loop. */
void hcts_stall(unsigned int ms);

/* MAY FREE-RUNNING TEXT GO OUT RIGHT NOW?
 *
 * A boot banner or a repeating alive line is only useful before a tool is
 * talking, and it is actively harmful once one is: text landing between the
 * length word and the CRC of a reply is a protocol error, and TunerStudio's
 * answer to a protocol error is to reconnect.
 *
 * "Nobody has talked to us" is not enough on its own, because a request takes
 * several byte times to arrive and a line started in that window finishes
 * inside somebody's reply. So this is BOTH conditions: the target still wants
 * text, AND either not one byte has ever been received or the receiver has
 * been quiet for 40 ms - which is longer than any gap inside one request and
 * shorter than the gap between two polls from a tool that has gone away.
 *
 * Found by ts_protocol_test.py with the K-line echo OFF. With echo ON the
 * banner's own echo silenced the text immediately and hid it. */
unsigned char hcts_quiet(void);

/* ------------------------------------------------------------- the state --
 * Public because a target's telemetry publishes it. Names are unchanged from
 * the ME7.5 firmware so its update_live() needed no edits. */
extern unsigned int  rx_echo_lost;
extern unsigned int  rx_hw_ovr;      /* the HARDWARE threw a byte away       */
extern unsigned int  rx_frame_err;   /* the WIRE is wrong, not the timing    */
extern unsigned int  rx_resync;      /* the parser gave up mid-frame         */
extern unsigned int  rx_bytes;
extern unsigned int  rx_reqs;
extern unsigned int  rx_idle;        /* T7 at the last byte                  */
extern unsigned int  probe_bad;      /* hc_badvec straight after the probe   */
extern unsigned int  probe_s0ric;
extern unsigned int  probe_psw;
extern unsigned int  probe_ir;
extern unsigned char rx_irq_ok;      /* the ASC0 node named itself           */
extern unsigned char rx_tick_ok;     /* the CAPCOM fallback tick really runs */
extern unsigned int  rx_ticks;
extern unsigned char rx_irq_mode;    /* 1 = something else owns S0RBUF       */
extern unsigned char echo_seen;
extern unsigned int  cfg_writes;     /* TunerStudio page value writes        */
extern unsigned int  cfg_burns;      /* TunerStudio burns                    */
extern unsigned int  hc_stalls;
extern unsigned char hc_stall_req;   /* ms of stall asked for over the wire  */
/* A target's free-running boot text, until something talks to us.
   hcts_init() clears it; a target that wants text sets it AFTER that. */
extern unsigned char hc_trace_on;

/* The ring itself lives in hcvec.c, next to the vectors that fill it. Declared
   here so a target's telemetry can publish hc_rx_ovf - which must stay at ZERO:
   it means the MAIN LOOP fell behind, a different failure from a byte lost in
   the register (rx_hw_ovr). */
extern volatile unsigned char hc_rx_ring[HC_RXRING];
extern volatile unsigned char hc_rx_head;
extern volatile unsigned char hc_rx_tail;
extern volatile unsigned int  hc_rx_ovf;
/* FAR, and that is a CODE-SPACE decision, not a protocol one. hcvec_me711.c
   is compiled MOD167 MEDIUM so its 117 unclaimed-trap catch-alls live in the
   FCODE class in segment 0x85 instead of the single 64 KiB NCODE CGROUP. Far
   code means a far call, and this prototype has to say so or L166 reports
   L20 DATA TYPES DIFFERENT against the MEDIUM module's own record.

   The one caller here is hcts_rx_pump(), the POLLED fallback, which runs only
   while the receive interrupt is disabled - never at the 25 kHz the CC7 drain
   runs at, and that drain still writes the ring inline for the reason the long
   comment above hc_cc7_isr() gives. A far call costs this path nothing that
   matters. Targets that compile hcvec SMALL are unaffected: HC_RX_STORE_FAR is
   empty for them. */
#ifndef HC_RX_STORE_FAR
#define HC_RX_STORE_FAR
#endif
extern void HC_RX_STORE_FAR hc_rx_store(unsigned char b);

/* ------------------------------------------------------------- the hooks --
 *
 * Exactly two, and both are about the BOARD rather than the protocol.
 */

/* The '!' command: everything that is a deliberate one-off action rather than
   a setting. TunerStudio sends these from [ControllerCommands] buttons. p[1]
   selects; the reply is sent by hcts.c, so this only acts.
   A target with nothing to offer implements an empty body. */
void hcts_target_cmd(unsigned char *p, unsigned int n);

/* ============ THE CONFIGURATION STORE THE PAGE COMMANDS ACT ON ===========
 *
 * `R`/`V` read the page, `W` writes one value into it and `B` burns it. This
 * file must not know what happens on the other side of those three, and it
 * deliberately does not: the TARGET supplies them.
 *
 * That is not decoration. The whole point of a DESIRED/ACTIVE configuration
 * model is that a `W` while the engine turns must NOT reach the running
 * engine, and that a read must return what the tuner typed rather than what
 * the engine is still using. A board that has hc_config_manager.c linked
 * points these at it; a board that does not points them straight at
 * hcconfig's page, which is byte-for-byte what this file used to do inline.
 *
 * It also keeps the configuration semantics away from the TRANSPORT. Today
 * the transport is K-line. When it is CAN or USB, the page commands arrive
 * through a different reader and call these same three functions, and nothing
 * about desired-versus-active changes.
 */
unsigned char hcts_cfg_read(unsigned int off);
void          hcts_cfg_write(unsigned int off, unsigned char v);
/* RETURNS THE RESPONSE CODE THE BURN IS TO BE ANSWERED WITH, and a target that
   will answer LATER instead calls hcts_defer_response() and returns anything -
   the caller only looks at this when no reply was deferred.

   It returns a code rather than void because a Burn the target declines on the
   spot used to be answered TS_OK by the caller, which told TunerStudio that a
   calibration had been stored when nothing had been. A refusal is a legitimate
   outcome; misreporting it is not. */
unsigned char hcts_cfg_burn(void);

/* ================== THE PLATFORM YIELD, AND WHY IT HAD TO EXIST ==========
 *
 * hcts_tx() is BAUD-PACED AND BLOCKING: it writes S0TBUF and busy-waits for
 * the byte to leave, then waits again to swallow the K-line echo. That is
 * fine on a board whose safety responder runs from interrupts - the ME7.5,
 * where UMKOM is CC5 + T8 at ILVL 13 and a dead main loop costs nothing.
 *
 * IT IS FATAL ON THE BOSCH ME7.1.1, and the arithmetic is not close:
 *
 *      one byte at 19200 8N1                     520.8 us
 *      the 128-byte output-channel reply         135 bytes -> 70.3 ms
 *      the 256-byte calibration page reply       263 bytes -> 137.0 ms
 *      even the bare signature reply             29 bytes  -> 15.1 ms
 *
 * against a 10 ms S5500 supervision raster that is serviced ONLY from the main
 * loop (hc_asic_start_service()). A single routine TunerStudio realtime poll
 * would starve it for SEVEN rasters. That is precisely the V15 defect
 * (the maintainer's design notes), where a ~127 ms blocking
 * bench print reset the ECU at ~140 ms every boot.
 *
 * So every bounded wait in this file calls hcts_target_yield(). A target
 * implements it as:
 *
 *   ME7.5    an empty body. Behaviour is unchanged - the responder is already
 *            on interrupts and there is nothing to service from here.
 *   Bosch  ONE tick-gated call into hc_asic_start_service(), which does at
 *            most one state transition and never blocks. The supervision
 *            raster is then serviced THROUGH a 70 ms reply instead of being
 *            starved by it.
 *
 * The alternative - rewriting the reply path as a byte-at-a-time state machine
 * - was rejected: it would restructure bench-proven shared code that the ME7.5
 * target depends on, to solve a problem only one board has, and the reply
 * still has to be paced at one byte per 521 us either way. Servicing the
 * platform inside the wait is the smaller and more honest change.
 *
 * IT IS NOT RE-ENTRANT AND DOES NOT NEED TO BE. The only call path is
 * main loop -> hcts_service() -> handle() -> send_*() -> hcts_tx() -> yield,
 * and nothing a yield reaches transmits on the serial port.
 *
 * Proven, not asserted: tools/me711_ts_gap_proof.py runs the real built
 * image and measures the worst hc_asic_start_service() gap across every
 * TunerStudio transaction this server can be asked for. */
void hcts_target_yield(void);

#endif /* HCTS_H */
