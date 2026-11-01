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

static void asic_clear_diag(void)
{
    in_flight = 0;
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
     * SSC_INIT transition via asic_frame_clear(). */

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
    hc_ssc_start_t7 = T7;

    SSCRIC = HC_IC(TGT_ILVL_ASIC, 0);
    SSCTIC = (unsigned int)(HC_IC(TGT_ILVL_ASIC_TX, 0) | 0x0080u);

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
    SSCRIC &= (unsigned int)~0x0040u;    /* BCLR SSCRIE */
    hc_ssc_rx_vec++;
    if (!ASIC_CS_LATCH) {
        hc_ssc_xfer_ticks = (unsigned int)((unsigned int)T7 - hc_ssc_start_t7);
        ASIC_CS_LATCH = 1;               /* deselect, once */
        hc_ssc_done = 1;
        in_flight = 0;
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
/* The RAW PEC buffer word i. */
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

