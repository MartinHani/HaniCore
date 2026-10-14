/*
 * hcasic.c - the Bosch ME7.1.1 MAIN <-> ASIC link, HaniCore's own.
 *
 * Every register value here was read out of the target OEM firmware
 * and the address it came from is in the comment beside it. What is NOT taken
 * from Bosch is the code: this is a small state machine with bounded waits and
 * one buffer it owns, not a translation of the OEM's dispatcher.
 *
 * The buffer is the clearest example of the difference. Bosch put its frame at
 * 0xD33E; the transfer primitive at 0x8233A6 takes the address in R13 and
 * would work with any segment-0 address, so 0xD33E is a Bosch SOFTWARE choice
 * and not a hardware requirement. HaniCore's frame is at TGT_ASIC_FRAME, in
 * the XRAM the boot block itself tests and resets on - which is the only part
 * of segment 0 this firmware can point at and know is RAM.
 */
#include <reg167.h>
#include "hctarget.h"
#include "hcliveforensics.h"
#include "hcts.h"
#include "hcasic.h"
#include "hcnvm.h"

/* SRCPn/DSTPn and PECCn come from reg167.h. The addresses the PEC pointers are
   loaded with are the SSC's own data registers in ESFR space, and they are the
   same two constants the OEM ME7.1.1 image loads at 0x8233D4 and 0x8233E6. */
#define SSC_RB_ADDR   0xF0B2u
#define SSC_TB_ADDR   0xF0B0u

/* The frame. ONE buffer, transferred in place, exactly as the OEM does: PEC0
   walks it out to SSCTB while PEC4 walks SSCRB back into it. That is not a
   race - the SSC is a shift register, so word n is fully transmitted before
   word n is received. */
#define FRAME   ((unsigned int volatile far *)((unsigned long)TGT_ASIC_FRAME))

/* P6.4 = CS-ASIC. Driven LOW to select, released to an INPUT otherwise, so a
   HaniCore that never talks to the ASIC never asserts its select line at all.
   Bit-addressed: P6.0 and P6.1 are the flash and RAM chip selects and a
   read-modify-write on the whole port would disturb them. */
sbit ASIC_CS_LATCH = P6 ^ TGT_ASIC_CS_PORT_BIT;
sbit ASIC_CS_DIR   = DP6 ^ TGT_ASIC_CS_PORT_BIT;
sbit ASIC_MRST_DIR = DP3 ^ 8;
sbit ASIC_MTSR_DIR = DP3 ^ 9;
sbit ASIC_SCLK_DIR = DP3 ^ 13;

unsigned char asic_state;
unsigned char asic_alive;
unsigned char asic_last_class;
unsigned int  asic_tx_count;
unsigned int  asic_rx_count;
unsigned int  asic_start_count;
unsigned int  asic_run_count;
unsigned int  asic_csum_ok;
unsigned int  asic_csum_err;
unsigned int  asic_class_err;
unsigned int  asic_timeouts;
unsigned int  asic_ssc_err;
unsigned int  asic_last_csum;
unsigned int  asic_want_csum;

/* The accepted snapshot. A frame is only copied here once its checksum and its
   reply class have both passed, so nothing downstream can read half a frame or
   a rejected one. THIS is the double buffer: FRAME is the PEC's, this is
   HaniCore's, and the copy is the acceptance. */
static unsigned int volatile far *const RXSNAP =
    (unsigned int volatile far *)(TGT_EXTRAM_BASE + TGT_RAM_ASICLOG);

static unsigned char in_flight;      /* words expected back, 0 = nothing     */
unsigned char asic_err_latched;      /* an SSC error needs a full re-init    */

/* MEASURED chip-select-to-first-clock delay, in T7 ticks (0.8 us each). The
   whole point of V9 is this number, so it is published rather than assumed. */
unsigned int hc_ssc_cs_arm_ticks;

/* The SSC interrupt bookkeeping. Published: a bench run has to be able to say
   whether the block ends arrived as interrupts at all, which is exactly what
   ASICLIVE_V4 could not answer. */
unsigned int  hc_ssc_tx_vec;         /* PEC0 block ends                      */
unsigned int  hc_ssc_rx_vec;         /* PEC4 block ends = frame complete     */
unsigned int  hc_ssc_err_vec;        /* SSC error node                       */
unsigned int  hc_ssc_last_err;       /* SSCCON error flags as the ISR saw them */
unsigned char hc_ssc_done;           /* set by the RX ISR, cleared by reader */
/* The transfer duration in T7 TICKS, latched inside the RX ISR. V5 measured it
   in whole milliseconds and reported X=1 for an exchange that should take
   3.07 ms at 500 kHz, which was unresolvable at that resolution. T7 runs at
   fCPU / 2^(T7I+3) = 40 MHz / 32 = 1.25 MHz (0.8 us), so 96 words should read
   about 3840
   ticks - and whatever it actually reads gives the REAL SSC bit rate, and
   therefore fCPU, by a measurement in which fCPU does not cancel.

   This comment used to say "fCPU/16 = 1.25 MHz at 20 MHz". The FREQUENCY was
   right and the derivation was not: the clock is 40 MHz and T7I=2 divides by
   32, not 16 at 20 MHz. Those are exactly the two errors hctarget.h records
   as having cancelled each other for a while, which is why nothing caught it.
   The number below is unchanged; only the reasoning is now correct. */
unsigned int  hc_ssc_xfer_ticks;
unsigned int  hc_ssc_start_t7;
static unsigned int  flight_start;   /* T7 when it was started               */
static unsigned char fail_run;       /* consecutive failures                 */
static unsigned int  ms_since;       /* ms since the last exchange started   */

/* How long a frame may take before it is written off. 118 words at the SSC's
   own rate is well under a millisecond; 20 ms is two orders of margin and it
   is short enough that a dead ASIC costs nothing visible in the main loop. */
#define ASIC_FLIGHT_MS      20u
/* How often a runtime frame goes out. The OEM schedules its runtime service
   from a task table whose tick length this repo cannot yet convert into
   milliseconds, so this is HaniCore's own choice and it is deliberately slow:
   10 ms is fast enough to prove the link is alive and slow enough that a
   misunderstanding of the protocol cannot flood the ASIC. */
#define ASIC_RUN_PERIOD_MS  10u
/* After this many consecutive failures the link latches out. It keeps trying
   the STARTUP frame after that, but it never claims to be running. */
#define ASIC_FAIL_LIMIT     8u

static void asic_clear_diag(void)
{
    asic_state = ASIC_OFF;
    asic_alive = 0;
    asic_last_class = 0;
    asic_tx_count = 0;
    asic_rx_count = 0;
    asic_start_count = 0;
    asic_run_count = 0;
    asic_csum_ok = 0;
    asic_csum_err = 0;
    asic_class_err = 0;
    asic_timeouts = 0;
    asic_ssc_err = 0;
    asic_last_csum = 0;
    asic_want_csum = 0;
    in_flight = 0;
    fail_run = 0;
    ms_since = 0;
}

/* RESETDIAG_V1 intentionally does not attempt an ASIC handshake. OEM copies
   a dedicated 96-word initialization block before the first exchange; the
   former HaniCore image substituted a runtime-style zero frame whose fields
   are not understood. Leaving CS, MRST, MTSR and SCLK as inputs makes this a
   clean A/B experiment and cannot command an output through the monitor. */
void asic_isolate(void)
{
    asic_clear_diag();
    SSCTIC = 0;
    SSCRIC = 0;
    SSCEIC = 0;
    /* Deselected but STILL DRIVEN. Even in the isolate path the select must
       not float: the ASIC edge-triggers a CAPCOM interrupt on it, and the
       EEPROM shares the same three data wires. */
    ASIC_CS_LATCH = 1;
    ASIC_CS_DIR = 1;
    ASIC_MRST_DIR = 0;
    ASIC_MTSR_DIR = 0;
    ASIC_SCLK_DIR = 0;
}

/* ======================================================================== *
 * EVERYTHING BELOW IS COMPILED OUT WHILE THE LINK IS ISOLATED.
 *
 * Not #if-ed for tidiness. RESETDIAG_V1 exists to answer one question - is
 * the ~420 ms reset the on-chip watchdog? - and it cannot answer it while a
 * second candidate is in the image. Leaving this code linked but unreachable
 * would be nearly as good and not quite: a routine that programs PEC source
 * and destination pointers and sets SSCEN is exactly the kind of thing that
 * must be ABSENT rather than merely not called, and
 * tools/me711_wdt_audit.py checks the final BIN for precisely those
 * register writes. If they are in the image, the audit fails and the build
 * does not ship.
 *
 * The startup frame itself is a second reason. OEM ME7.1.1 does not begin with the
 * 118-word runtime frame this module sends: 0x8BE73A builds and transfers a
 * 96-word STARTUP image first and only schedules runtime traffic after it is
 * accepted. Until that startup frame is recovered well enough to know that
 * every word of it is inert, transmitting anything to a processor that can
 * reset this CPU - and drive output stages - is not a bench-safe act.
 * ======================================================================== */
#if !TGT_ASIC_ISOLATED

/* ------------------------------------------------------------- checksum ---
 * A wrapping 16-bit additive word sum over words 0..n-2, compared against word
 * n-1. [OEM ME7.1.1 0x8BEB34 is exactly this, and the reference ASIC IROM's 0x724A
 * does the same thing on its side - two independent implementations of one
 * agreement.] */
unsigned int hc_asic_frame_sum(unsigned char n)
{
    /* 2026-10-13: the exchange runs at an interrupt level now (CC27), and
       this loop was 58 % of it (117 reads through a volatile FAR pointer,
       up to three sums per frame). No transfer is in flight when a sum is
       taken (built before the start, checked after the end), so a plain
       pointer into the system page (DPP3 = page 3: 0xC000-0xFFFF) reads the
       same words. */
    const unsigned int *p = (const unsigned int *)TGT_ASIC_FRAME;
    unsigned int s = 0u;
    unsigned char i = (unsigned char)(n - 1u);

    while (i >= 4u) {             /* four a pass: twice per 10 ms frame, at
                                     the planner's level (2026-10-14)      */
        s = (unsigned int)(s + p[0] + p[1] + p[2] + p[3]);
        p += 4;
        i = (unsigned char)(i - 4u);
    }
    while (i != 0u) {
        s = (unsigned int)(s + *p++);
        i--;
    }
    return s;
}

/* RXSNAP is HaniCore's own accepted-frame copy, not part of the exchange, so
   clearing it on every re-init is harmless and keeps stale frames from being
   read back as current. */
/* (RXSNAP is cleared inline in asic_init - see below.) */

/* Clear the exchange buffer. Called ONCE per session, from the SSC_INIT
   transition - never from a mid-session re-init, because words 1..3 hold the
   supervision handshake and must survive one. This is what keeps a warm reset
   from transmitting the previous session's words: FRAME is at 0xE100 in near
   RAM, which a reset does not clear. */
void asic_frame_clear(void)
{
    unsigned char i;

    for (i = 0; i < TGT_ASIC_WORDS_RUN; i++) {
        FRAME[i] = 0;
    }
}


/* ------------------------------------------------------------- the SSC ----
 * [OEM ME7.1.1 0x82325E is called with R12 = 0x461F, R13 = 0x0013, R14 = 2.] */
void asic_init(void)
{
    unsigned char i;

    asic_clear_diag();

    /* THE FRAME BUFFER IS NOT CLEARED HERE ANY MORE.
     *
     * asic_init() runs at boot AND on every mid-session re-initialisation -
     * the escalation after three busy refusals, and the SSC error path. It
     * used to zero all 118 words of FRAME, which destroyed the runtime
     * handshake: words 1..3 carry the ASIC's previous reply straight back to
     * it, and a re-init in the middle of a session wiped them. The execution
     * proof caught it - the echo held on only every third runtime frame, and
     * the FIRST one went out as zeros.
     *
     * The OEM's own SSC init at 0x82325E touches SSCCON, SSCBR and the PEC
     * and nothing else; it never goes near the frame buffer. This now matches.
     *
     * Clearing at boot is still required, and hcasicstart does it once at the
     * SSC_INIT transition via asic_frame_clear().
     *
     * RXSNAP is HaniCore's own accepted-frame copy and takes no part in the
     * exchange, so clearing it on every re-init is harmless and stops a stale
     * frame being read back as current. */
    for (i = 0; i < TGT_ASIC_WORDS_RUN; i++) {
        RXSNAP[i] = 0;
    }

    /* Deselect, and KEEP IT DRIVEN. Earlier images returned the select to an
       INPUT between frames on the theory that a floating line is "quieter"
       than a driven one. On a shared SPI bus that is exactly backwards: the
       ASIC watches this pin with an edge-triggered CAPCOM interrupt - its own
       IROM arms CC9IC in the SSC init, and CC9IO/P2.9 is CS_ASIC on its side
       [BOSCH-PM sheet ASIC] - so a floating select is a stream of spurious
       frame-start edges. Driven high, always. */
    ASIC_CS_LATCH = 1;
    ASIC_CS_DIR = 1;

    /* The SSC pins. MTSR (P3.9) and SCLK (P3.13) are outputs because this end
       is the master; MRST (P3.8) stays an input. [BOSCH-PM: SSDO/SSCLK/SSDI.]
       Bit-addressed - P3.10 is the K-line transmitter and must not be
       disturbed. */
    P3  |=  0x2200u;          /* latch high before direction: idle levels    */
    DP3 |=  0x2200u;          /* P3.9 MTSR, P3.13 SCLK  -> outputs           */
    DP3 &= (unsigned int)~0x0100u;   /* P3.8 MRST -> input                   */

    /* SSCEN low BEFORE the control bits, always. See the long note in
       asic_start_transfer: writing SSCCON while enabled silently does
       nothing, which is what left V4 unable to recover from its first error. */
    SSCCON &= (unsigned int)~0x8000u;
    SSCCON = TGT_ASIC_SSCCON_IDLE;   /* 0x461F: master, 16 bit, MSB first    */
    SSCBR  = TGT_ASIC_SSCBR;         /* 0x13  [OEM ME7.1.1 R13 at 0x82325E]        */

    SSCTIC = 0;
    SSCRIC = 0;
    SSCEIC = 0;

    asic_state = ASIC_IDLE;
}

/* Start one exchange of n words. Returns 0 if it could not be started, which
   is not an error - it just means the SSC is still busy and the caller will be
   back in a millisecond. */
unsigned char asic_start_transfer(unsigned char n)
{
    /* live_admit() claims this before its in-flight test and its IC masking
       setup.  The ASIC service runs in the 1 ms tick (2026-10-13), and its only hardware-launch primitive
       reject the claim is the interleaving contract: no code path may arm
       PEC or touch SSCCON while an admitted AM29 word owns the window. */
    if (hc_nvm_word_owned()) {
        return 0;
    }
    if (SSCBSY) {
        return 0;
    }

    /* PEC4 receives, PEC0 transmits, both against the SAME buffer, in place.
       [OEM ME7.1.1 0x8233A6: PECC4 = 0x0200|count, DSTP4 = buffer, SRCP4 = 0xF0B2;
        PECC0 = 0x0400|count, DSTP0 = 0xF0B0, SRCP0 = buffer.]
       0x0200 is "byte/word = word, increment destination"; 0x0400 is the same
       with the SOURCE incrementing instead. */
    PECC4 = (unsigned int)(0x0200u | n);
    DSTP4  = (unsigned int)TGT_ASIC_FRAME;
    SRCP4  = SSC_RB_ADDR;

    PECC0 = (unsigned int)(0x0400u | n);
    DSTP0  = SSC_TB_ADDR;
    SRCP0  = (unsigned int)TGT_ASIC_FRAME;

    /* THE WRITE DISCIPLINE, and V4 got it wrong. On this core the SSCCON
       control bits are only writable while SSCEN is LOW; a write with SSCEN
       already set does not take. The OEM never does it any other way -
       [BIN 0x823270] BCLR SSCEN, [0x823272] MOV SSCCON,R12, [0x823276] MOV
       SSCBR,R13, [0x82327A] BSET SSCEN. V4 wrote 0xC61F in one go, so after
       the first transfer its "clear the error flags" and its reconfiguration
       were both no-ops and the peripheral could never be recovered.

       Full sequence every time, so a transfer always starts from a known
       state whatever the previous one did. */
    SSCCON &= (unsigned int)~0x8000u;    /* SSCEN LOW first - now writable   */
    SSCCON = TGT_ASIC_SSCCON_IDLE;       /* 0x461F, control bits, SSCEN 0    */
    SSCBR  = TGT_ASIC_SSCBR;             /* re-stated: it is reset with it   */
    SSCEIR = 0;
    asic_err_latched = 0;
    hc_ssc_done = 0;

    /* Select the ASIC, the OEM's way: drive the select HIGH first, THEN low,
       so the falling edge is unambiguous. The ASIC arms on a CC9 CAPTURE of
       that edge - its CCM2 is set to negative-edge capture while idle
       [IROM 0x181C AND CCM2,#FF8Fh / 0x1820 OR CCM2,#0020h] - and an edge it
       does not see is an exchange with no slave on the wire at all.
       [OEM ME7.1.1 0x8BE75E BSET P6.4, 0x8BE760 BCLR P6.4]

       Direction first here, because the pin is already an output from the
       startup and re-stating the latch before the direction would be a
       no-op that costs an edge. */
    ASIC_CS_DIR = 1;
    ASIC_CS_LATCH = 1;
    ASIC_CS_LATCH = 0;

    SSCCON |= 0x8000u;                   /* ... and only NOW enable it      */

    /* ------------------------------------------------ THE ARMING WINDOW --
     * The ASIC's SSC is DISARMED between frames. Its teardown clears SSCEN
     * and, at IROM 0x1818, clears DP3.8 - so its data output is an INPUT,
     * high-Z. It re-arms only inside the chip-select interrupt at 0x18E6,
     * and the SSCCON = 0x871F write that creates a slave is the LAST thing
     * that path does, after two SCXT context switches, two helper calls and
     * the whole SSC + PEC setup at 0x17B0.
     *
     * The OEM master leaves that window open. Between BCLR P6.4 and the PEC
     * start it copies 96 words, checksums 95, initialises the SSC and then
     * WAITS FOR T4 TO ADVANCE [0x8BE79E..0x8BE7AA] - a delay with no other
     * purpose. That is >= 1270 instructions before the first clock.
     *
     * HaniCore builds its frame once at init, so the exchange had nothing to
     * do between the edge and firing SSCTIC's request bit: about six
     * instructions. Every image up to V8 therefore clocked its first word
     * into a slave that was not listening, and read a high-Z line.
     *
     * WHAT WE DO NOT KNOW: the S5500's own fCPU. CLKCFG is strapped on P0H at
     * reset and its ROM never writes SYSCON, so its instruction count cannot
     * honestly be converted into microseconds - MAIN's 40 MHz does not apply
     * to a part with its own 10 MHz crystal. We therefore reproduce the OEM's
     * BEHAVIOUR, which is measured from the OEM ME7.1.1 binary, rather than a
     * derived slave-side figure.
     *
     * Bounded in TIME, not iterations - the boot-budget rule. */
    {
        unsigned int t0 = T7;
        while ((unsigned int)(T7 - t0) < (unsigned int)TGT_ASIC_CS_ARM_TICKS) {
            /* spin. Interrupts stay enabled: a longer wait is always safe,
               a shorter one is the bug we are fixing. */
        }
        hc_ssc_cs_arm_ticks = (unsigned int)(T7 - t0);
    }

    /* ILVL 15/GLVL 0 is PEC4 and ILVL 14/GLVL 0 is PEC0 on this core, which is
       what makes these two writes a DMA setup rather than an interrupt setup.
       SSCTIC's request flag is set deliberately: that is what kicks the first
       word out. [OEM ME7.1.1 writes 0x007C and 0x00F8 - the 0x80 in 0xF8 IS the
       request bit.] */
    /* IN FLIGHT BEFORE THE KICK, AND NOT AFTER IT.
       The write below sets SSCTIC's request bit, which is what starts the
       exchange - so from that instruction on, the RX block-end ISR is
       entitled to run, and hc_ssc_rx_isr() is the only thing that clears
       `in_flight`.  Assigning the flag AFTERWARDS means setting it after its
       own clearer, and a flag set after its clearer is stuck.
       On this hardware the block end is TGT_ASIC_WORDS_RUN = 118 words =
       1.89 ms away, so the old order never bit - but nothing in the code said
       why it was safe, and the first consumer of the flag found it at once.
       MEASURED in the modelled rig, whose exchange completes inside that same
       write: `in_flight` read 118 in 600 of 600 samples with hc_ssc_rx_vec at
       119, i.e. the ISR had run 119 times and cleared nothing. */
    in_flight = n;
    flight_start = T7;
    hc_ssc_start_t7 = T7;

    SSCRIC = HC_IC(TGT_ILVL_ASIC, 0);
    SSCTIC = (unsigned int)(HC_IC(TGT_ILVL_ASIC_TX, 0) | 0x0080u);

    asic_tx_count++;
    return 1;
}

/* Stop an exchange, however it ended, and put the wire back to rest. */
/* ===================================================== the SSC interrupts ==
 *
 * ASICLIVE_V4 ran the SSC with NO handlers on these nodes and the hardware
 * reported it immediately: hc_badvec climbed steadily, FV=0x2D and LV=0x2E.
 * Those are not mystery vectors - they are this peripheral, and the OEM's own
 * vector table proves it: slot 0x2E points at 0x8234E0, the documented SSC
 * receive ISR, and slot 0x2D at a two-instruction routine that is literally
 *
 *      0x82352C   BCLR SSCTIE
 *      0x82352E   RETI
 *
 * WHY THEY FIRE AT ALL. A PEC channel serves a request only while its COUNT
 * is non-zero. When COUNT reaches zero the next request is NOT a PEC transfer
 * - it is delivered as an ordinary vectored interrupt. So the END of every
 * block transfer arrives here by design. With no handler it went to the
 * catch-all, and because nothing disabled the node's interrupt-enable the
 * condition simply re-requested.
 *
 * So both nodes are ONE-SHOT PER TRANSFER and disable their own IE, exactly as
 * the OEM does, and asic_start_transfer re-arms them for the next frame.
 */
/* TX: the OEM's handler, instruction for instruction. Nothing else belongs
   here - the last word is already in the shift register. */
void hc_ssc_tx_isr(void) interrupt TGT_TRAP_SSCTINT
{
    SSCTIC &= (unsigned int)~0x0040u;    /* BCLR SSCTIE */
    hc_ssc_tx_vec++;
}

/* RX: the block is complete. [BIN 0x8234FC] disable the enable; [0x8234FE]
   skip if P6.4 is already high, so a second entry cannot double-count;
   [0x823502] raise P6.4 - the deselect IS the completion event; [0x823518]
   set a flag and let the TASK level parse. No parsing in here. */
void hc_ssc_rx_isr(void) interrupt TGT_TRAP_SSCRINT
{
    unsigned int lf_done_t7;

    SSCRIC &= (unsigned int)~0x0040u;    /* BCLR SSCRIE */
    hc_ssc_rx_vec++;
    if (!ASIC_CS_LATCH) {
        lf_done_t7 = (unsigned int)T7;
        hc_ssc_xfer_ticks = (unsigned int)(lf_done_t7 - hc_ssc_start_t7);
        ASIC_CS_LATCH = 1;               /* deselect, once */
        hc_ssc_done = 1;
        in_flight = 0;
        /* Preserve the hardware completion time, but keep all external-RAM
           forensic stores after the timing-critical chip-select release. */
        if (hc_lf_fast_active != 0u) {
            HC_LF_WORD(LF_SSC_ISR_T7) = lf_done_t7;
            HC_LF_WORD(LF_SSC_ISR_COUNT)++;
            HC_LF_WORD(LF_SSC_ISR_PEC) =
                (unsigned int)(((PECC0 & 0xFFu) << 8) | (PECC4 & 0xFFu));
        }
    }
}

/* Error: V4 had none, and an SSC error with SSCAREN clear does not clear
   itself. The flags are captured for the bench log, then the peripheral is
   put back in a state a later transfer can use - which on this core means
   SSCEN must go LOW before any control bit can be rewritten. */
void hc_ssc_err_isr(void) interrupt TGT_TRAP_SSCEINT
{
    hc_ssc_err_vec++;
    hc_ssc_last_err = (unsigned int)(SSCCON & 0x0F00u);
    SSCEIC = 0;                          /* stop it re-requesting            */
    SSCTIC = 0;
    SSCRIC = 0;
    SSCCON &= (unsigned int)~0x8000u;    /* SSCEN low - the reset condition   */
    ASIC_CS_LATCH = 1;                   /* deselect */
    in_flight = 0;
    asic_err_latched = 1;
}

/* The PEC count fields, read live. A block that stalls half-way leaves its
   remaining count here, which turns "it did not finish" into a number. */
/* The RAW PEC buffer, accepted or not. asic_rx_word() deliberately returns
   only ACCEPTED frames; the dump needs what actually arrived, because the
   whole point is to look at a reply that failed validation. */
unsigned int asic_frame_word(unsigned char i)
{
    return (i < (unsigned char)TGT_ASIC_WORDS_RUN) ? FRAME[i] : 0u;
}

/* V51.  THE FRAME-PHASE TRUTH, and it belongs to the module that owns the SSC.
   `in_flight` is set by asic_start_transfer() before the first clock and
   cleared by the RX ISR when the whole PEC block has landed, so it is the only
   task-readable answer to "is an S5500 frame on the wire right now".

   live_admit() used to ask SSCCON's error flags instead.  Per C167CR UM V3.1
   section 12.7 those flags "are not reset automatically ... but must be
   cleared by software", SSCEIC is left with SSCEIE = 0 here so hc_ssc_err_isr()
   never runs, and a write with SSCEN low targets the CONTROL bits rather than
   the flags - so nothing in this firmware clears them at all.  One receive
   error therefore denied every later flash window for the rest of the boot.
   Physically: V50 read SSCCON = 0xC00F before its Burn and 0xC60F after, and
   0xC60F is still what it read 7759 rasters later. */
unsigned char hc_asic_frame_in_flight(void) { return in_flight; }

unsigned int hc_ssc_pec_tx_left(void) { return (unsigned int)(PECC0 & 0x00FFu); }
unsigned int hc_ssc_pec_rx_left(void) { return (unsigned int)(PECC4 & 0x00FFu); }
unsigned int hc_ssc_sscon(void)       { return SSCCON; }

void asic_abort_transfer(void)
{
    SSCTIC = 0;
    SSCRIC = 0;
    SSCCON = TGT_ASIC_SSCCON_IDLE;
    ASIC_CS_LATCH = 1;      /* deselect ... */
    ASIC_CS_DIR = 1;        /* ... and keep driving it, never float it */
    in_flight = 0;
}

/* Did PEC4 finish? Its count field reaching zero is the completion condition;
   reading it is cheaper and more honest than trusting an interrupt flag we
   would also have to clear. */
static unsigned char asic_done(void)
{
    return (unsigned char)((PECC4 & 0x00FFu) == 0u);
}

/* ------------------------------------------------------- frame acceptance -
 * Both tests, in the order that costs least: the checksum first because it is
 * arithmetic on data already in RAM, then the reply class.
 *
 * [OEM ME7.1.1 parser 0x8BE4E8 accepts reply class byte 0x1E or 0x2E.] The class
 * lives in the low byte of word 0 in the reply; word 0 going OUT is 0xBAA5. */
static unsigned char asic_accept(unsigned char n)
{
    unsigned int got;
    unsigned char cls;
    unsigned char i;

    got = hc_asic_frame_sum(n);
    asic_last_csum = got;
    asic_want_csum = FRAME[n - 1u];
    if (got != asic_want_csum) {
        asic_csum_err++;
        return 0;
    }
    asic_csum_ok++;

    cls = (unsigned char)(FRAME[0] & 0x00FFu);
    asic_last_class = cls;
    if (cls != TGT_ASIC_REPLY_A && cls != TGT_ASIC_REPLY_B) {
        asic_class_err++;
        return 0;
    }

    /* Only now is the frame allowed to exist outside the PEC's buffer. */
    for (i = 0; i < n; i++) {
        RXSNAP[i] = FRAME[i];
    }
    asic_rx_count++;
    asic_alive = 1;
    return 1;
}

unsigned int asic_rx_word(unsigned char i)
{
    if (i >= TGT_ASIC_WORDS_RUN) {
        return 0;
    }
    return RXSNAP[i];
}

/* ------------------------------------------------------------ the frames -
 * SAFE CONTENTS, and "safe" here means one specific thing: every word that
 * this repo has not PROVEN to be inert is left at zero, and the only words
 * written are the two the protocol demands - the header and the checksum.
 *
 * That is a deliberate refusal to guess. generated/me711_asic_runtime_frame.csv
 * shows the frame is a fixed mailbox region plus a typed extension area, and
 * the OEM packer fills words 4..70 from a pointer table at 0x816E80. Those
 * pointers are into OEM RAM that no longer exists in a HaniCore image, so
 * copying the SHAPE would mean transmitting whatever happens to be at those
 * addresses - which is exactly how an actuator command gets sent by accident.
 *
 * A frame of zeros plus a valid header and checksum is the one payload that
 * can be reasoned about. If the ASIC rejects it, that is a fact worth having
 * and it costs nothing but a counter. */
static void asic_build(unsigned char n)
{
    unsigned char i;

    for (i = 0; i < n; i++) {
        FRAME[i] = 0;
    }
    FRAME[0] = TGT_ASIC_HEADER;          /* 0xBAA5 [OEM ME7.1.1 0x8BE2B6]          */
    FRAME[n - 1u] = hc_asic_frame_sum(n);
}

/* ------------------------------------------------------------ the raster -*/
#endif /* !TGT_ASIC_ISOLATED */

#if TGT_ASIC_ISOLATED
/* Isolated: there is no accepted frame. Returning zero is better than
   returning whatever happens to be in a snapshot that was never written -
   the telemetry publishes these words, and a stale value read as live data is
   how somebody ends up believing an ASIC answered. The bounds test is kept so
   the isolated and connected versions behave the same way at the edge. */
unsigned int asic_rx_word(unsigned char i)
{
    if (i >= TGT_ASIC_WORDS_RUN) {
        return 0;
    }
    return 0;
}
#endif /* TGT_ASIC_ISOLATED */

/* ============================== the P6.4 chip-select stimulus is GONE ======
 *
 * RESETDIAG_V2 pulsed P6.4 as an active-low chip select on even boots and the
 * hardware answered: BOTH halves reset at PT=0x0134, same RAW=0x001C, same
 * TR=0x0002. The stimulus provably ran - its pulse counter advanced only on
 * even boots - and it changed nothing.
 *
 * That result means ONLY that a bare chip-select pulse does not satisfy the
 * reset source. It does NOT rule out the ASIC. But it does mean this code has
 * no further experimental value, and a safety build should not carry an unused
 * routine that drives an ASIC-facing pin. Deleted rather than left dead: V2 is
 * archived at the maintainer's hardware-session record and the code is
 * in git history.
 *
 * In RESETDIAG_V3, P6.4 is an INPUT in both halves and nothing drives it.
 */

void asic_tick(void)
{
    if (ms_since < 60000u) {
        ms_since++;
    }
}

/* ------------------------------------------------------- the state machine
 * Non-blocking throughout. It is called from the main loop and it never waits
 * for anything: an exchange either has finished, has timed out, or is still in
 * flight, and all three return immediately. That is what keeps the K-line
 * alive when the ASIC is not. */
void asic_service(void)
{
#if TGT_ASIC_ISOLATED
    /* ISOLATED. There is no state machine, no SSC and no frame in this build;
       every diagnostic counter stays at zero and asic_state stays ASIC_OFF, so
       the reset test has exactly one variable in it. */
    return;
#else

    unsigned char n;

    /* SUPERSEDED - this machine no longer drives exchanges.
     *
     * hcasicstart.c owns the link. It implements the OEM sequence properly:
     * startup #1 -> startup #2 -> the 118-word runtime dialogue, with the
     * clean BSET/BCLR select edge, the 63.2 us arming delay, and immediate
     * phase advance on success. This function is the older, simpler machine
     * it replaced, and both were still being called from the main loop.
     *
     * That went unnoticed because both built the same bytes - a header, zeros
     * and a checksum - so whichever one transmitted, the ASIC saw the same
     * frame and every hardware result up to V10 stands unchanged.
     *
     * It stops being harmless with V11. The runtime handshake lives in words
     * 1..3, which must be carried back from the ASIC's previous reply, and
     * asic_build() below zeroes the buffer from index 0. With both machines
     * running, the echo survived only every third runtime frame and the FIRST
     * one went out as zeros - caught by tools/me711_echo_proof.py, which
     * executes the image and reads what actually reaches the wire.
     *
     * The counters, the transport, the ISRs and asic_accept() all stay - they
     * are shared with hcasicstart.c. Only this state machine stands down. */
    return;

    /* Kept for reference and for the isolated-build path; unreachable. */
    /*lint -unreachable */
    if (asic_state == ASIC_OFF) {
        return;
    }

    /* --- something is in flight ------------------------------------------ */
    if (in_flight) {
        n = in_flight;

        if (asic_done()) {
            asic_abort_transfer();
            /* The SSC's own error bits, latched into telemetry rather than
               acted on: a parity or baud error tells the bench something a
               checksum failure does not. */
            asic_ssc_err |= (unsigned int)(SSCCON & 0x0F00u);

            if (asic_accept(n)) {
                fail_run = 0;
                if (n == TGT_ASIC_WORDS_START) {
                    asic_start_count++;
                    asic_state = ASIC_START_OK;
                } else {
                    asic_run_count++;
                    asic_state = ASIC_RUN_OK;
                }
            } else {
                if (fail_run < 255u) {
                    fail_run++;
                }
                asic_state = (unsigned char)((fail_run >= ASIC_FAIL_LIMIT)
                                             ? ASIC_FAULT : ASIC_IDLE);
            }
            return;
        }

        if ((unsigned int)(T7 - flight_start)
            > (unsigned int)US_TO_TICKS(ASIC_FLIGHT_MS * 1000u)) {
            asic_abort_transfer();
            asic_timeouts++;
            asic_alive = 0;
            if (fail_run < 255u) {
                fail_run++;
            }
            asic_state = (unsigned char)((fail_run >= ASIC_FAIL_LIMIT)
                                         ? ASIC_FAULT : ASIC_IDLE);
        }
        return;
    }

    /* --- nothing in flight: decide what to send next --------------------- */
    if (ms_since < ASIC_RUN_PERIOD_MS) {
        return;
    }

    switch (asic_state) {
    case ASIC_IDLE:
    case ASIC_FAULT:
        /* Always the STARTUP frame from here. A latched fault keeps trying
           this and only this: it may not claim the link is running, but
           refusing to retry would mean a bench that has just plugged the ASIC
           in never recovers without a power cycle. */
        asic_build(TGT_ASIC_WORDS_START);
        if (asic_start_transfer(TGT_ASIC_WORDS_START)) {
            ms_since = 0;
            asic_state = ASIC_START_TX;
        }
        return;
    case ASIC_START_OK:
    case ASIC_RUN_OK:
        asic_build(TGT_ASIC_WORDS_RUN);
        if (asic_start_transfer(TGT_ASIC_WORDS_RUN)) {
            ms_since = 0;
            asic_state = ASIC_RUN_TX;
        }
        return;
    default:
        return;
    }
#endif /* TGT_ASIC_ISOLATED */
}
