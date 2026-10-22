/*
 * hcasicdump.c - freeze one real ASIC reply and get it out in ONE flash.
 *
 * THE PROBLEM THIS SOLVES. ASICXPORT_V5 proved the transport works on real
 * hardware: PEC residuals 0/0, SSC errors 0, bad vectors 0, TX and RX vector
 * counts advancing together, and warm-reset restart working. What it could not
 * say is WHAT the ASIC sent back - only `R=` , the first word, which came back
 * as FE12 / FE78 / FE02 / FEF0.
 *
 * The ECU resets every ~310 ms, so there is no time to print 96 words in one
 * run, and flashing a new image per chunk is exactly the manual grind this
 * project is trying to avoid.
 *
 * THE MECHANISM. The battery-backed SRAM survives the reset - that is already
 * proven, it is where the reset log lives. So:
 *
 *   1. the FIRST completed RX of a power-on session is copied whole into
 *      battery SRAM and FROZEN. Later transfers do not overwrite it, so every
 *      chunk printed afterwards belongs to the SAME frame.
 *   2. a second slot freezes the first reply seen in a DIFFERENT ASIC state,
 *      because V5 showed the state advancing 0x02 -> 0x03 and the reply may
 *      not be the same in both.
 *   3. each boot prints ONE chunk and advances a persistent cursor. Eight
 *      words per boot keeps every line short, comfortably inside the
 *      supervisor's deadline whatever it currently is.
 *
 * So one flash and roughly four seconds of the ECU resetting on its own yields
 * every complete frame, in order, with its metadata.
 *
 * WHY NOT JUST SEND IT OVER THE K-LINE ON REQUEST. Because that needs the ECU
 * to still be alive when the request arrives, and it is not. The frozen-
 * frame-plus-cursor scheme needs no interaction at all.
 *
 * ============================== V12: POST-RESET SALVAGE ====================
 *
 * V11 captures runtime reply #1 (slot 2) but resets before reply #2 is ever
 * observed. The fix that would need reply #2 to evaluate (whatever it is)
 * cannot be tested without it - and every way of watching for it FROM INSIDE
 * the boot that receives it costs instructions in the runtime path, which is
 * exactly the thing under study and must not be disturbed.
 *
 * The C167CR does not require that. Two facts, both from the User's Manual
 * S19.2 ("Status After Reset"), page 19-8, quoted verbatim:
 *
 *   "The contents of the on-chip extension RAM are not affected by a system
 *    reset. However, after a power-on reset, the contents of the XRAM are
 *    undefined."
 *   "The contents of the internal RAM are not affected by a system reset.
 *    However, after a power-on reset, the contents of the internal RAM are
 *    undefined."
 *
 * "System reset" is defined in S19.1 to cover hardware reset (RSTIN),
 * software reset (SRST) and watchdog reset - all three, by name. FRAME
 * (TGT_ASIC_FRAME = 0xE100, physical 0x00E100) is on-chip XRAM. The counters
 * hc_asic_run_tx/run_rx/run_ok and hc_asic_state are on-chip IRAM. Every
 * SWRST_SM reset observed on this bench reports RAW=0x001C with PONR CLEAR -
 * precisely the non-power-on case both quotes cover. Only the first boot of
 * a session reports PONR SET (RAW=0x003C).
 *
 * So: the boot that RECEIVES reply #2 needs no new code at all. The NEXT
 * boot, before hc_asic_start_init() zeroes the counters and before anything
 * builds a new frame into FRAME, can simply COPY what is already sitting
 * there. hc_asicdump_salvage() is that copy, called once, early in main(),
 * strictly before hc_asic_start_init(). See the maintainer's design notes
 * for the full write-order proof.
 */
#include <reg167.h>
#include "hctarget.h"
#include "hcasic.h"
#include "hcasicdump.h"
#include "hcts.h"
#include "hcasicstart.h"

/* ------------------------------------------------------------------------
 * TGT_BURN_DIAGNOSTICS is the positive switch, the same idiom hc_dbw.c and
 * hcsched_dry.c use. Without it this module is a set of empty stubs that
 * keep the ABI and cost 2074 bytes less of a 64 K code budget. Nothing here
 * is on a control path: every function records or prints, and the one value
 * a caller reads back - hc_dump_slots_full - stays defined and stays 0.
 * ---------------------------------------------------------------------- */
#if !defined(TGT_BURN_DIAGNOSTICS)

/* Generated from hcasicdump.h. Every function here records or prints;
   none of them decides anything, and hc_dump_slots_full stays 0. */

unsigned char hc_dump_slots_full;

void hc_asicdump_init(void) { }
void hc_asicdump_salvage(unsigned int reset_raw)
{ if (reset_raw) return; }
void hc_asicdump_echo(unsigned int r1, unsigned int r2, unsigned int r3, unsigned int t0, unsigned int t1, unsigned int t2, unsigned int t3)
{ if (r1 || r2 || r3 || t0 || t1 || t2 || t3) return; }
void hc_asicdump_txprefix(unsigned int w0, unsigned int w1, unsigned int w2, unsigned int w3)
{ if (w0 || w1 || w2 || w3) return; }
void hc_asicdump_capture(unsigned char st, unsigned int xfer, unsigned int nwords, unsigned int calc, unsigned int recv, unsigned int ms, unsigned int runtx)
{ if (st || xfer || nwords || calc || recv || ms || runtx) return; }
unsigned char hc_asicdump_print(void) { return 0u; }

#else

/* The persistent region in the battery-backed SRAM the ASIC log already owns. */
#define DUMP ((unsigned int volatile far *) \
              (TGT_EXTRAM_BASE + TGT_RAM_ASICDUMP))

/* THREE slots, each sized to hold the RUNTIME frame's 118 words:
     slot 0  the first startup reply   (96 words, state WAIT1)
     slot 1  the second startup reply  (96 words, state WAIT2)
     slot 2  the first RUNTIME reply  (118 words, state RUNTIME_WAIT)
   First one of each wins; none is ever overwritten. */
#define SLOT_WORDS   134u          /* 16 metadata + 118 payload            */
#define SLOTS          3u
#define MAX_PAY      118u
/* 8 words per line, not 16 - the long form was 95 bytes, and the supervisor's
   deadline has been as short as ~35 ms. 55 bytes leaves room for the boot
   lines sharing the same window. More boots, each one cheaper. */
#define CHUNK          8u
#define D_VALID       1u
#define D_BOOT        2u
#define D_STATE       3u
#define D_XFER        4u
#define D_COUNT       5u
#define D_CALC        6u
#define D_RECV        7u
#define D_SSCCON      8u
#define D_PEC         9u
#define D_MS         10u
#define D_RUNTX      11u          /* the runtime exchange index            */
#define D_TX0        12u          /* what WE transmitted, words 0..3       */
#define D_TX1        13u
#define D_TX2        14u
#define D_TX3        15u
#define D_PAY        16u

/* The global header lives AFTER all three slots: 3 * 134 = 402. It used to
   sit at word 0, which is also slot 0's own D_MAGIC - so a capture and the
   region magic aliased each other and the magic read back as zero. Caught in
   the simulator. */
#define G_MAGIC      402u
#define G_CURSOR     403u                 /* the persistent print cursor    */

/* THE ECHO RECORD - the V11 result, 8 words after the cursor.
   [0] valid  [1..3] words 1..3 as they were BEFORE the first runtime build
   [4..7] words 0..3 as they went OUT after it.
   Recorded once per power-on. [1..3] and [5..7] must be identical: that is
   the handshake proven on the wire rather than assumed from the source. */
#define G_ECHO       404u
#define G_ECHO_N       8u

/* THE V12 SALVAGE RECORD, immediately after the echo record. Populated ONCE,
   by hc_asicdump_salvage(), from state that belongs to the PREVIOUS power-on
   session and would otherwise be destroyed within a few instructions of the
   boot that finds it. First valid salvage wins - never overwritten. */
#define G_SALV            412u
#define G_SALV_VALID        0u
#define G_SALV_RUNTX        1u
#define G_SALV_RUNRX        2u
#define G_SALV_RUNOK        3u
#define G_SALV_STATE        4u
#define G_SALV_RESETRAW     5u
#define G_SALV_PAY          6u
#define G_SALV_N          124u            /* 6 metadata + 118 payload      */

/* V11 used 0x4144 ('A','D') to guard words [0, G_ECHO+G_ECHO_N) = [0, 412).
   G_SALV (412) and its 124 words are new in V12 and sit ENTIRELY outside that
   range, so a V11 session's leftover magic - or, on a bench SRAM that has
   carried a battery charge across several experiments, an even older one's -
   would read as "already initialised" here and hc_asicdump_init() would then
   skip clearing DUMP[G_SALV+G_SALV_VALID], leaving whatever garbage a
   DIFFERENT record layout left at that address to be misread as a genuine
   salvage. A new magic forces exactly one real clear, of the FULL extended
   region, the first time a V12 image ever boots on a given SRAM - regardless
   of what was there before. */
#define D_MAGIC_VAL  0x4432u               /* 'D','2' - the V12 layout       */

/* Compile-time proof that the capture fits its region and does not touch the
   next one. A silent overlap cost two hardware runs of confusing data. */
#if (G_SALV + G_SALV_N) * 2u > TGT_RAM_ASICDUMP_LIMIT
#error "the ASIC dump does not fit TGT_RAM_ASICDUMP_LIMIT"
#endif
#if MAX_PAY < TGT_ASIC_WORDS_RUN
#error "a capture slot cannot hold a whole runtime frame"
#endif
#if TGT_RAM_ASICDUMP < (TGT_RAM_ASICLOG + TGT_RAM_ASICLOG_LIMIT)
#error "TGT_RAM_ASICDUMP overlaps TGT_RAM_ASICLOG (RXSNAP) - the V6/V7 bug"
#endif


unsigned char hc_dump_slots_full;

/* The last frame's transmitted words 0..3, stashed by build() the moment it
   finishes and copied into whichever slot the following capture fills. This
   is a diagnostic side-channel only: nothing reads it back into the frame. */
/* The first eight words are a deliberate encoding guard. With the array at
   its former near address, Keil encoded `MOV tx_pre[2],R10` as
   `F6 FA 84 BB`; starting at byte 1 those operands spell a syntactically
   valid `JMPS 84:F6BB` into removed OEM flash. It is not an instruction (the
   real instruction starts one byte earlier), but the release gate scans every
   byte alignment so erased-code jumps cannot hide behind decoder drift. Keep
   the gate strict and place the four live words outside low addresses 80..8F.
   The guard is never read and changes no protocol or timing decision. */
static unsigned int tx_pre[12];
#define TX_PRE(i) tx_pre[8u + (i)]

void hc_asicdump_txprefix(unsigned int w0, unsigned int w1,
                          unsigned int w2, unsigned int w3)
{
    TX_PRE(0) = w0;
    TX_PRE(1) = w1;
    TX_PRE(2) = w2;
    TX_PRE(3) = w3;
}

static unsigned int volatile far *slot(unsigned char n)
{
    return DUMP + (unsigned int)n * SLOT_WORDS;
}

void hc_asicdump_init(void)
{
    /* The cursor and the frames persist ACROSS resets on purpose - that is
       the whole mechanism. Only a cold, wiped SRAM starts over. The clear
       covers the magic, the cursor and the echo record: G_ECHO + G_ECHO_N
       = 412 words. The salvage record BEYOND that is deliberately NOT
       cleared here - see hc_asicdump_salvage() for why. */
    if (DUMP[G_MAGIC] != D_MAGIC_VAL) {
        unsigned int i;
        for (i = 0u; i < (G_ECHO + G_ECHO_N); i++)
            DUMP[i] = 0u;
        DUMP[G_SALV + G_SALV_VALID] = 0u;   /* one store: the salvage guard */
        DUMP[G_MAGIC] = D_MAGIC_VAL;
    }
    {
        unsigned char i, n = 0u;
        for (i = 0u; i < (unsigned char)SLOTS; i++)
            if (slot(i)[D_VALID]) n++;
        hc_dump_slots_full = n;
    }
}

/* Freeze a reply. Slot 0 takes the first one seen at all; slot 1 takes the
   first one seen in a DIFFERENT asic state, so a phase change is captured
   rather than averaged away. Neither is ever overwritten. */
void hc_asicdump_capture(unsigned char st, unsigned int xfer,
                         unsigned int nwords, unsigned int calc,
                         unsigned int recv, unsigned int ms,
                         unsigned int runtx)
{
    unsigned int volatile far *s;
    unsigned int i;
    unsigned char which;

    if (nwords > MAX_PAY) nwords = MAX_PAY;

    /* THE SLOT IS CHOSEN BY THE EXCHANGE'S STATE, not by an attempt count.
         WAIT1        -> slot 0   the first startup reply,   96 words
         WAIT2        -> slot 1   the second startup reply,  96 words
         RUNTIME_WAIT -> slot 2   the FIRST runtime reply,  118 words
       First one of each wins; none is ever overwritten. Runtime reply #2
       onward is NOT captured here - that is what the post-reset salvage is
       for, and doing it here would cost instructions in this exact path. */
    if (st == HC_ASIC_ST_WAIT1)             which = 0u;
    else if (st == HC_ASIC_ST_WAIT2)        which = 1u;
    else if (st == HC_ASIC_ST_RUNTIME_WAIT) which = 2u;
    else return;

    if (slot(which)[D_VALID]) {
        return;                          /* already frozen - do not disturb */
    }

    s = slot(which);
    s[D_BOOT]   = 0u;                /* filled by the caller's boot number   */
    s[D_STATE]  = (unsigned int)st;
    s[D_XFER]   = xfer;
    s[D_COUNT]  = nwords;
    s[D_CALC]   = calc;
    s[D_RECV]   = recv;
    s[D_SSCCON] = hc_ssc_sscon();
    s[D_PEC]    = (unsigned int)((hc_ssc_pec_tx_left() & 0xFFu)
                                 | ((hc_ssc_pec_rx_left() & 0xFFu) << 8));
    s[D_MS]     = ms;
    s[D_RUNTX]  = runtx;
    /* The TX prefix that went OUT on this same exchange, stashed by build().
       Recorded per slot so the log shows TX and RX side by side without
       anyone having to line up two lines by eye. */
    s[D_TX0]    = TX_PRE(0);
    s[D_TX1]    = TX_PRE(1);
    s[D_TX2]    = TX_PRE(2);
    s[D_TX3]    = TX_PRE(3);

    /* Copy FIRST, then checksum the COPY. The V6 hardware run exposed why:
       the metadata said CALC=0x0997 while the dumped payload summed to
       0x0B97 - a difference of exactly 0x0200, which is the same quantum by
       which CALC varies between exchanges. The caller had checksummed the LIVE
       PEC buffer and the snapshot was taken a moment later, so the two could
       describe different exchanges. Checksumming the frozen copy makes that
       impossible by construction: whatever is printed is what was summed. */
    for (i = 0u; i < nwords; i++)
        s[D_PAY + i] = asic_frame_word((unsigned char)i);
    {
        unsigned int sum = 0u;
        for (i = 0u; i + 1u < nwords; i++)
            sum = (unsigned int)(sum + s[D_PAY + i]);
        s[D_CALC] = sum;                       /* over the SNAPSHOT           */
        s[D_RECV] = s[D_PAY + nwords - 1u];    /* from the SNAPSHOT           */
    }
    s[D_VALID] = 1u;                 /* LAST: a torn record reads as invalid */
    hc_dump_slots_full++;
}

/* Record the first runtime build's echo. Called from build() with the three
   words as they stood BEFORE anything was written, and words 0..3 as they
   stand AFTER. First call of a power-on session wins; later runtime frames do
   not disturb it, so what is printed always describes the FIRST one. */
void hc_asicdump_echo(unsigned int r1, unsigned int r2, unsigned int r3,
                      unsigned int t0, unsigned int t1,
                      unsigned int t2, unsigned int t3)
{
    if (DUMP[G_MAGIC] != D_MAGIC_VAL) return;
    if (DUMP[G_ECHO]) return;                 /* already have the first one  */
    DUMP[G_ECHO + 1u] = r1;
    DUMP[G_ECHO + 2u] = r2;
    DUMP[G_ECHO + 3u] = r3;
    DUMP[G_ECHO + 4u] = t0;
    DUMP[G_ECHO + 5u] = t1;
    DUMP[G_ECHO + 6u] = t2;
    DUMP[G_ECHO + 7u] = t3;
    DUMP[G_ECHO] = 1u;                        /* LAST - a torn record reads 0 */
}

/* ============================================================ THE SALVAGE ==
 *
 * Called ONCE, early in main(), BEFORE hc_power_hold_assert()/
 * hc_asic_start_init() - see the maintainer's design notes for the full
 * proof that nothing between reset and this call has touched FRAME or the
 * counters read here. reset_raw is THIS boot's own T0-captured WDTCON value -
 * i.e. the cause of the reset that just ended the PREVIOUS session, which is
 * exactly the reset whose leftover state this function is reading.
 *
 * FIRST VALID SALVAGE WINS. Once DUMP[G_SALV+G_SALV_VALID] is 1 it stays 1 -
 * hc_asicdump_init() deliberately does not clear it on a warm reset (only a
 * genuinely cold, wiped SRAM re-arms it, alongside the magic), so a salvage
 * from boot N survives every later boot N+1, N+2, ... untouched.
 */
void hc_asicdump_salvage(unsigned int reset_raw)
{
    unsigned int i;

    if (DUMP[G_MAGIC] != D_MAGIC_VAL) return;      /* region not established */
    if (DUMP[G_SALV + G_SALV_VALID]) return;       /* already have one - keep it */

    /* PONR SET means THIS boot followed a genuine power-on, and the C167CR
       User's Manual is explicit that XRAM/IRAM content is UNDEFINED after
       one - never mind "retained". A stale flag from before the rail cycled
       could not have survived; do not manufacture evidence from noise. */
    if (reset_raw & TGT_RESET_PONR) return;

    /* THE PROVENANCE PREDICATE.
       run_tx == 2 is necessary AND sufficient to prove the third runtime
       exchange never started - it would read 3 if it had, since it only
       ever increments. run_rx == 2 proves the second exchange's reply was
       FULLY clocked in (the counter increments unconditionally on receipt,
       before any checksum judgement), not torn by the reset arriving
       mid-transfer. run_ok is deliberately NOT required: a checksum-failed
       reply is exactly the evidence this exists to capture. */
    if (hc_asic_run_tx != 2u || hc_asic_run_rx != 2u) return;

    /* THE BUILD-RACE CLOSE. hc_asic_run_tx reaching 2 only proves exchange
       #3's TRANSFER has not yet SUCCEEDED - it does not prove build() has
       not yet RUN for it. hc_asic_state reads HC_ASIC_ST_RUNTIME_TX for the
       entire ~20 ms wait before exchange #3 AND for the short span after
       build(1) has already zeroed FRAME[4..70]/[117] for exchange #3 but
       before asic_start_transfer() succeeds and run_tx becomes 3 - counters
       alone cannot tell those two spans apart. TX_PRE(1..3), stashed by
       build() itself on every call before it writes anything, closes it for
       free: build() never touches FRAME[1..3], so TX_PRE(1..3) == FRAME[1..3]
       here if and only if a build() has run SINCE reply #2 last changed them
       - exactly the unsafe span. Reject it; a rolling value that happens to
       repeat between replies #1 and #2 costs a missed salvage, never a
       corrupt one - the next power-on gets another try. */
    if (TX_PRE(1) == asic_frame_word(1)
        && TX_PRE(2) == asic_frame_word(2)
        && TX_PRE(3) == asic_frame_word(3))
        return;

    DUMP[G_SALV + G_SALV_RUNTX]    = hc_asic_run_tx;
    DUMP[G_SALV + G_SALV_RUNRX]    = hc_asic_run_rx;
    DUMP[G_SALV + G_SALV_RUNOK]    = hc_asic_run_ok;
    DUMP[G_SALV + G_SALV_STATE]    = (unsigned int)hc_asic_state;
    DUMP[G_SALV + G_SALV_RESETRAW] = reset_raw;

    /* RAW COPY, no on-device checksum - asic_frame_word() is the same
       read-only accessor hc_asicdump_capture() already uses on the LIVE
       buffer; it does not write FRAME. w117 is verified OFFLINE against
       exactly these 118 printed words. */
    for (i = 0u; i < 118u; i++)
        DUMP[G_SALV + G_SALV_PAY + i] = asic_frame_word((unsigned char)i);

    DUMP[G_SALV + G_SALV_VALID] = 1u;   /* LAST: a torn record reads invalid */
}

/* how many serial lines one slot needs: its chunks, then its metadata line */
static unsigned int slot_lines(unsigned char n)
{
    unsigned int N = slot(n)[D_COUNT];

    if (N == 0u || N > MAX_PAY) N = MAX_PAY;
    return ((N + (CHUNK - 1u)) / CHUNK) + 1u;
}

/* One chunk per boot. Returns 0 when there is nothing left to print, which is
   itself useful - it means every captured frame is out.

   Slots are not a fixed length: startup replies are 96 words and the runtime
   reply is 118, so the cursor walks them by their stored N rather than by a
   constant. After the three slots and the echo line, the salvage record (if
   any) prints last, in the same one-chunk-per-boot style. */
unsigned char hc_asicdump_print(void)
{
    unsigned int cur, w, i, base, n;
    unsigned char which;

    if (DUMP[G_MAGIC] != D_MAGIC_VAL) return 0u;
    cur = DUMP[G_CURSOR];

    for (which = 0u; which < (unsigned char)SLOTS; which++) {
        unsigned int lines;

        if (!slot(which)[D_VALID]) {
            /* Nothing captured here yet. LEAVE THE CURSOR ALONE and try again
               on the next boot - the first version jumped to the next slot,
               which on boot 1 skipped slot 0 entirely. The simulator caught
               it. Holding here is also the honest signal when an exchange is
               never reached at all. */
            return 0u;
        }
        lines = slot_lines(which);
        if (cur < lines) break;
        cur -= lines;
    }
    if (which >= (unsigned char)SLOTS) {
        /* All three slots are printed. Next: the echo line, then the
           salvage record (metadata line + up to 15 chunks of 8 words). */
        if (cur == 0u) {
            if (DUMP[G_ECHO] != 1u) return 0u;
            hcts_puts("HCE RX=");
            hcts_hex4(DUMP[G_ECHO + 1u]); hcts_puts(",");
            hcts_hex4(DUMP[G_ECHO + 2u]); hcts_puts(",");
            hcts_hex4(DUMP[G_ECHO + 3u]);
            hcts_puts(" TX=");
            hcts_hex4(DUMP[G_ECHO + 4u]); hcts_puts(",");
            hcts_hex4(DUMP[G_ECHO + 5u]); hcts_puts(",");
            hcts_hex4(DUMP[G_ECHO + 6u]); hcts_puts(",");
            hcts_hex4(DUMP[G_ECHO + 7u]);
            hcts_puts(" ECHO=");
            hcts_hex4((unsigned int)
                      ((DUMP[G_ECHO + 1u] == DUMP[G_ECHO + 5u]
                        && DUMP[G_ECHO + 2u] == DUMP[G_ECHO + 6u]
                        && DUMP[G_ECHO + 3u] == DUMP[G_ECHO + 7u]) ? 1u : 0u));
            hcts_puts("\r\n");
            DUMP[G_CURSOR] = (unsigned int)(DUMP[G_CURSOR] + 1u);
            return 1u;
        }
        cur -= 1u;

        if (!DUMP[G_SALV + G_SALV_VALID]) return 0u;   /* nothing salvaged */

        if (cur == 0u) {
            hcts_puts("HCPM TAG=POSTMORTEM_RUNTIME_RX2");
            hcts_puts(" RUNTX="); hcts_hex4(DUMP[G_SALV + G_SALV_RUNTX]);
            hcts_puts(" RUNRX="); hcts_hex4(DUMP[G_SALV + G_SALV_RUNRX]);
            hcts_puts(" RUNOK="); hcts_hex4(DUMP[G_SALV + G_SALV_RUNOK]);
            hcts_puts(" ST=");    hcts_hex4(DUMP[G_SALV + G_SALV_STATE]);
            hcts_puts(" RAW=");   hcts_hex4(DUMP[G_SALV + G_SALV_RESETRAW]);
            hcts_puts(" N=0076");
            hcts_puts("\r\n");
            DUMP[G_CURSOR] = (unsigned int)(DUMP[G_CURSOR] + 1u);
            return 1u;
        }
        cur -= 1u;

        base = cur * CHUNK;
        if (base >= 118u) return 0u;              /* fully printed - done  */

        hcts_puts("HCP:");
        hcts_hex4(base);
        for (i = 0u; i < CHUNK && (base + i) < 118u; i++) {
            w = DUMP[G_SALV + G_SALV_PAY + base + i];
            hcts_puts(" ");
            hcts_hex4(w);
        }
        hcts_puts("\r\n");
        DUMP[G_CURSOR] = (unsigned int)(DUMP[G_CURSOR] + 1u);
        return 1u;
    }

    n = slot(which)[D_COUNT];
    if (n == 0u || n > MAX_PAY) n = MAX_PAY;
    base = cur * CHUNK;

    if (base >= n) {
        /* the metadata line for this slot */
        hcts_puts("HCDM S=");   hcts_hex4((unsigned int)which);
        hcts_puts(" ST=");      hcts_hex4(slot(which)[D_STATE]);
        hcts_puts(" N=");       hcts_hex4(slot(which)[D_COUNT]);
        hcts_puts(" CALC=");    hcts_hex4(slot(which)[D_CALC]);
        hcts_puts(" RECV=");    hcts_hex4(slot(which)[D_RECV]);
        hcts_puts(" SC=");      hcts_hex4(slot(which)[D_SSCCON]);
        hcts_puts(" P=");       hcts_hex4(slot(which)[D_PEC]);
        hcts_puts(" T=");       hcts_hex4(slot(which)[D_MS]);
        hcts_puts(" X=");       hcts_hex4(slot(which)[D_XFER]);
        hcts_puts(" R=");       hcts_hex4(slot(which)[D_RUNTX]);
        hcts_puts(" TX=");      hcts_hex4(slot(which)[D_TX0]);
        hcts_puts(",");         hcts_hex4(slot(which)[D_TX1]);
        hcts_puts(",");         hcts_hex4(slot(which)[D_TX2]);
        hcts_puts(",");         hcts_hex4(slot(which)[D_TX3]);
        hcts_puts("\r\n");
    } else {
        hcts_puts("HCD");
        hcts_hex4((unsigned int)which);
        hcts_puts(":");
        hcts_hex4(base);
        for (i = 0u; i < CHUNK && (base + i) < n; i++) {
            w = slot(which)[D_PAY + base + i];
            hcts_puts(" ");
            hcts_hex4(w);
        }
        hcts_puts("\r\n");
    }

    DUMP[G_CURSOR] = (unsigned int)(DUMP[G_CURSOR] + 1u);
    return 1u;
}

#endif /* !TGT_BURN_DIAGNOSTICS */
