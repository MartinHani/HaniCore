/*
 * hcasicstart.c - the Bosch ME7.1.1 ASIC startup handshake, HaniCore's own.
 *
 * WHY THIS EXISTS. Four bench experiments proved the ECU is reset from
 * outside while its 5 V rail stays up:
 *
 *   RAW=0x001C every time  =  LHWR|SHWR|SWR with PONR CLEAR. On this part the
 *   reset flags nest, and a genuine power-on sets PONR (the first boot of a
 *   session does show 0x3C). So the supply is NOT cycling - something pulls
 *   RSTIN low while VCC is fine.
 *
 * The ASIC's SWRST_SM is exactly such a source, and the ASIC IROM says when it
 * pulls it: the received frame is validated with one's-complement pairs, and
 * ANY mismatch runs
 *
 *      0x007878  BCLR P1H.2     ESRST_SM  - kill EGAS and the output stages
 *      0x00787A  BCLR P1H.3     SWRST_SM  - reset the main computer
 *
 * A HaniCore that never transmits leaves that frame at whatever the ASIC's RAM
 * holds, which cannot satisfy a value/complement pair. That is a mechanism,
 * not a timing coincidence, and it is the first explanation this project has
 * had that accounts for every observation at once: the fixed deadline, the
 * NMI-then-RSTIN order, the intact supply, and the total indifference to P6.4
 * pulses and to NLEN_FR.
 *
 * CAVEAT, STATED PLAINLY: the IROM read is from
 * the S5500 ASIC ROM read, a DIFFERENT ECU. The structure
 * - complement validation, and SWRST_SM as the failure action - is family
 * evidence at high confidence. The exact RAM offsets in it are that part's,
 * not ours, which is why this module reproduces the OEM ME7.1.1 MAIN side exactly
 * rather than trying to satisfy the other part's field layout.
 *
 * WHAT THE OEM DOES, and this module mirrors it step for step:
 *
 *   [BIN] 0x8BE73A, gated on the state byte F247
 *      F247 == 0 -> phase 1        0x8BE75E
 *      F247 == 1 -> phase 2        0x8BE81C
 *      else      -> nothing        0x8BE8EA
 *
 *   each phase:
 *      BSET P6.4 ; BCLR P6.4          idle high, then ASSERT LOW
 *      build the 96-word frame into the buffer
 *      checksum words 0..94 -> word 95
 *      SSC init  SSCCON=0x461F, SSCBR=0x13
 *      short settle
 *      start the PEC exchange, 0x60 words
 *      wait for completion, at most 0xA5 T4 ticks
 *          completion is P6.4 going HIGH again - the RX ISR raises it
 *      transfer status must be 0
 *      checksum the RECEIVED frame, words 0..94, compare against word 95
 *      match -> advance the state, clear the retry counter
 *      miss  -> retry counter++
 *
 *   [BIN] 0x8BE8CA, after phase 2 succeeds, MAIN registers the runtime
 *   handler 0x8BE8F4 with the boot-block scheduler and moves to 118-word
 *   exchanges.
 *
 * ONE DELIBERATE DIFFERENCE. After 17 failures the OEM gives up and marks
 * startup done anyway ([BIN] 0x8BE7FE: CMPB RL4,#0010h then fall through to
 * the success path) because it has an application to get on with. HaniCore
 * does not: it keeps retrying and keeps counting, because a bench log that
 * says "attempted 400 times, never once answered" is worth far more than one
 * that silently pretends to have succeeded.
 */
#include <reg167.h>
#include "hctarget.h"
#include "hcasic.h"
#include "hcasicframe.h"
#include "hcasicstart.h"
#include "hcasicdump.h"
#include "hcumkom.h"
#include "hcliveforensics.h"
#include "hcio711.h"
#include "hcrtmon711.h"    /* the S5500 raster in the reset witness */
#include "hchal.h"          /* hc_hal_ain_capture */
#include "hckwp_me711.h"    /* HC_KL.asic_prep (SRAM) */
#include "hcnvm.h"          /* hc_nvm_word_owned */

#define FRAME ((unsigned int volatile far *)((unsigned long)TGT_ASIC_FRAME))
/* the pre-build steps between runtime frames (HC_KL.asic_prep, 2026-10-14) */
#define PREP_CAPTURE  0u   /* the accepted reply is not snapshotted yet     */
#define PREP_ZERO     1u
#define PREP_FILL     2u
#define PREP_SUM      3u
#define PREP_READY    4u   /* the next frame is complete                    */

sbit ASIC_CS_LATCH_S = P6  ^ TGT_ASIC_CS_PORT_BIT;
sbit ASIC_CS_DIR_S   = DP6 ^ TGT_ASIC_CS_PORT_BIT;

unsigned char  hc_asic_state;
unsigned int   hc_asic_start_tx;
unsigned int   hc_asic_start_rx;
unsigned int   hc_asic_start_ok;
unsigned int   hc_asic_start_csum_err;
unsigned int   hc_asic_start_timeout;
unsigned int   hc_asic_run_tx;
unsigned int   hc_asic_run_rx;
unsigned int   hc_asic_run_ok;
unsigned char  hc_asic_run_live;
static unsigned char run_initial;
unsigned int   hc_asic_run_csum_err;
unsigned int   hc_asic_run_timeout;
unsigned int   hc_asic_last_ok_ms;
unsigned int   hc_asic_last_xfer_ms;    /* MEASURED duration of the last one  */
unsigned int   hc_asic_retries;
unsigned int   hc_asic_reply_w0;        /* first word the ASIC sent back      */
unsigned int   hc_asic_reply_w1;
unsigned int   hc_asic_ssc_errors;      /* SSC error node, not a bad checksum */
unsigned int   hc_asic_pec_tx_end;      /* PEC0 words still owed at the end   */
unsigned int   hc_asic_pec_rx_end;      /* PEC4 words still owed at the end   */
unsigned int   hc_asic_busy_refusals;   /* consecutive "SSC busy" refusals    */
unsigned int   hc_asic_reinits;         /* full SSC re-initialisations        */
unsigned int   hc_asic_last_calc;       /* our sum of the last reply          */
unsigned int   hc_asic_last_recv;       /* its own checksum word              */

static unsigned int  phase_mark;        /* when the current wait started      */
unsigned int  hc_asic_next_attempt;   /* hcnvm.c live_admit(): frame due */
/* 1 = the next exchange may start AT ONCE, without waiting out the retry
   period. Set when an exchange SUCCEEDS, and once when the SSC comes up.

   PROVEN FROM THE OEM ME7.1.1 BINARY (tools/me711_startup_delay_proof.py, 7/7):
   the OEM gates a startup exchange on the phase byte F247 alone and reads NO
   timer to decide whether to run one. Every timer wait it performs is INSIDE
   an exchange - the arming window before the first clock, and the 0xA5-tick
   wait for P6.4 to return high. Its success path writes only F247 and clears
   F246, then returns; nothing arms a delay before the next exchange.

   HaniCore was applying its RETRY interval to a non-retry. The V9 hardware log
   showed the cost: with the supervisor's deadline collapsed to 68 ms, startup
   #1 landed at 41 ms and startup #2 at 64 ms, putting the first runtime frame
   at 87 ms - 19 ms after the reset. */
static unsigned char run_now;
static unsigned char words_in_flight;

/* COMPLETION. V4 polled PEC4's count field because HaniCore had no SSC ISR.
   The hardware showed why that was the wrong architecture: with no handler on
   the SSC nodes, the END of every PEC block - which is delivered as an
   ordinary interrupt once COUNT hits zero - landed on the catch-all, and
   nothing disabled the node, so it kept requesting. hc_badvec climbed with
   FV=0x2D and LV=0x2E, which the OEM vector table identifies as SSCTINT and
   SSCRINT exactly.

   So completion is now what the OEM makes it: the RX ISR fires at the end of
   the block, disables its own enable, raises P6.4 and sets a flag. This reads
   that flag. */
static unsigned char xfer_done(void)
{
    return hc_ssc_done;
}

void hc_asic_start_init(void)
{
    hc_asic_state = HC_ASIC_ST_IDLE;
    hc_asic_start_tx = 0; hc_asic_start_rx = 0; hc_asic_start_ok = 0;
    hc_asic_start_csum_err = 0; hc_asic_start_timeout = 0;
    hc_asic_run_tx = 0; hc_asic_run_rx = 0; hc_asic_run_ok = 0;
    hc_asic_run_live = 0u; run_initial = 0u;
    hc_asic_run_csum_err = 0; hc_asic_run_timeout = 0;
    hc_asic_last_ok_ms = 0; hc_asic_last_xfer_ms = 0;
    hc_asic_retries = 0;
    hc_asic_reply_w0 = 0; hc_asic_reply_w1 = 0;
    hc_asic_ssc_errors = 0;
    hc_asic_pec_tx_end = 0; hc_asic_pec_rx_end = 0;
    hc_asic_busy_refusals = 0; hc_asic_reinits = 0;
    hc_asic_last_calc = 0; hc_asic_last_recv = 0;
    hc_asic_next_attempt = 0;
    run_now = 0;
    words_in_flight = 0;

    hc_umkom_init();          /* mirrors [BIN] 0x8B2188, once per session     */
    HC_KL.asic_prep = PREP_ZERO;   /* no runtime frame pre-built             */

    /* Idle HIGH, push-pull, output. [BIN] 0x823214-0x82321A does exactly this
       order: latch, then open-drain off, then direction. */
    ASIC_CS_LATCH_S = 1;
    ODP6 &= (unsigned int)~(1u << TGT_ASIC_CS_PORT_BIT);
    ASIC_CS_DIR_S = 1;
}

static void build_rt_zero(void);
static void build_rt_fill(void);
static unsigned char build_rt_sum(void);

/* Load the buffer for the exchange we are about to run. */
static unsigned char build(unsigned char runtime)
{
    unsigned int i;

    if (!runtime) {
        /* Streamed straight into the PEC buffer and summed on the way past.
           No local array: 96 words is 192 bytes and the system stack is 250. */
        unsigned int sum = 0u;
        for (i = 0u; i < (unsigned int)(HC_ASICFRAME_WORDS - 1u); i++) {
            unsigned int w = (unsigned int)hc_asicframe_word(i);
            FRAME[i] = w;
            sum = (unsigned int)(sum + w);
        }
        FRAME[HC_ASICFRAME_CKSUM_WORD] = sum;
        hc_asicdump_txprefix(FRAME[0], FRAME[1], FRAME[2], FRAME[3]);
        return (unsigned char)TGT_ASIC_WORDS_START;
    }

    /* THE RUNTIME FRAME.
     *
     * 0x8BE2B6 writes word 0 as two BYTE immediates - A5 into byte 0, BA into
     * byte 1, so word 0 = 0xBAA5 - then fills words 4..70 from a pointer
     * table (D304 = buf+0x08, D306 = buf+0x08+0x86) and writes nothing else.
     * 0x8BE308 handles word 71 onward. WORDS 1..3 are owned by a SEPARATE
     * OEM routine, `um_service` at [BIN] 0x8B1E24, called on the runtime
     * raster before the frame is built: it is the Bosch level-2
     * question/answer monitor, and it is what asserts SWRST_SM when the
     * answer is wrong. Every image up to V13 echoed words 1..3 unchanged =
     * a valid pulse for the WRONG question = wrong answer -> reset in one or
     * two frames (V13's faster cadence made the reset arrive EARLIER, which
     * is the signature of an error counter, not a missed beat).
     *
     * hc_umkom_service() is the recovered MAIN side of that monitor - a
     * byte-exact port of um_service, validated against the real routine
     * executed from the image (scratchpad/um_verify.py: 400 ticks, 0
     * output mismatches). It reads words 1..3 (the S5500's reply, still in
     * the in-place buffer) and writes words 1..3 with the response. See
     * the maintainer's design notes.
     *
     * V14 HARDWARE (2026-08-30): calling hc_umkom_service() on EVERY runtime
     * frame from the first one quadrupled the pre-reset lifetime (37 ms ->
     * 140 ms) but SWRST_SM still fired. Disassembling [BIN] 0x8BE8F4 (the
     * handler [BIN] 0x8BE8CA registers for runtime exchanges right after
     * startup phase 2 succeeds) settled why:
     *
     *   0x8BE8F4's state byte F249 == 0 -> build+send via 0x8BE2B6/0x8BE308,
     *       verify the reply, F249 = 2
     *   F249 == 2                       -> build+send AGAIN the same way,
     *       verify the reply, then CALLS 0x001944 / CALLS 0x0017E6 with
     *       R13:R14 = 0xEAAA:0x8B - installing seg8B:0xEAAA (a stub that
     *       just BSETs a handoff flag) in place of 0x8BE8F4 itself.
     *
     * NEITHER of these two builds calls `um_service` (0x8B1E24) - confirmed
     * by disassembly, not inferred: the OEM's first TWO runtime frames go out
     * with words 1..3 UNTOUCHED (an echo of the S5500's last reply), exactly
     * the V9..V13 behaviour, and only the recurring scheduler slot that takes
     * over after that handoff calls `um_service`. Independently, RX
     * (0x8BEAB4) and TX (0x8BEAE8) - the OEM's own per-tick runtime tasks -
     * were also disassembled end to end: both are self-contained, RETS-
     * terminated routines that never call `um_service` either, so it runs as
     * its own scheduler-list entry between them, starting only once that list
     * is installed.
     *
     * hc_asic_run_ok counts SUCCESSFULLY COMPLETED runtime round trips before
     * this call, which is the exact HaniCore analogue of the OEM's F249
     * grace counter (it advances only on a validated reply, exactly like
     * F249). The first two runtime frames (hc_asic_run_ok 0 and 1) therefore
     * echo words 1..3 unchanged, matching the OEM exactly; from the third
     * frame (hc_asic_run_ok >= 2) onward hc_umkom_service() takes over, which
     * lines up its own phase==4 "answer from the init accumulator" branch
     * with the OEM's real first processed tick instead of running two ticks
     * ahead of it.
     *
     * Words 71..116 keep their zeroed behaviour - the FR level-2 torque
     * monitor is not needed with the engine off, and every startup frame
     * (also mostly zero) is accepted. */
    build_rt_zero();
    build_rt_fill();
    return build_rt_sum();
}

/* THE RUNTIME BUILD IN TWO STEPS (2026-10-14). The exchange runs at the
   planner's interrupt level (CC27, ILVL 9) and blocks it while it runs: one
   ~230 us build-and-start let the crank capture ring overflow at 9600 rpm in
   the stress simulation. hc_asic_start_service() now pre-builds the next
   frame between frames - zero the payload, then fill it - one step per
   request, and the step that starts the transfer only starts it. The reply
   has been snapshotted at its accept (hc_hal_ain_capture) before either
   step touches the buffer; words 1..3 (the reply's monitoring question)
   survive the zero step for the fill step's hc_umkom_service(). */
typedef char hc_zero_by_two[(((unsigned int)TGT_ASIC_WORDS_RUN - 4u) % 2u) == 0u ? 1 : -1];
static void build_rt_zero(void)
{
    /* no transfer in flight while building: a plain pointer into the system
       page (DPP3), not 114 volatile FAR writes */
    unsigned int *z = (unsigned int *)TGT_ASIC_FRAME + 4;
    unsigned int i;
    for (i = 4u; i < (unsigned int)TGT_ASIC_WORDS_RUN; i += 2u) {
        z[0] = 0u;                /* two a pass (2026-10-14) */
        z[1] = 0u;
        z += 2;
    }
}

static void build_rt_fill(void)
{
    unsigned int i;
    {
        unsigned int r1 = FRAME[1], r2 = FRAME[2], r3 = FRAME[3];

        FRAME[0] = TGT_ASIC_HEADER;

        /* WORDS 52..58 ARE THE ASIC'S OUTPUT-PORT IMAGES, not zero.
           [BIN 0x8BE2B6] sends FDDC..FDE8 there; hcio711.c holds the OEM's
           own idle values and the managed outputs (N75, EVAP, heaters). */
        hc_io_frame();
        for (i = 0u; i < (unsigned int)HC_IO_WORDS; i++)
            FRAME[HC_IO_WORD0 + i] = hc_io_word((unsigned char)i);
        /* words 59..66 are the ASIC's PWM period/width registers. The
           OEM's forced-OFF values, never 0 (= full ON) - see hcio711.h. */
        for (i = 0u; i < (unsigned int)HC_IO_PWM_WORDS; i++)
            FRAME[HC_IO_PWM_WORD0 + i] = hc_io_pwm_word((unsigned char)i);

        if (run_initial < 2u) {
            FRAME[1] = r1;               /* OEM grace: echo, um_service idle  */
            FRAME[2] = r2;
            FRAME[3] = r3;
        } else {
            hc_umkom_service(FRAME);    /* owns words 1..3, in place          */
        }

        /* Bench record: words 1..3 as received vs as transmitted. */
        hc_asicdump_echo(r1, r2, r3,
                         FRAME[0], FRAME[1], FRAME[2], FRAME[3]);
        hc_asicdump_txprefix(FRAME[0], FRAME[1], FRAME[2], FRAME[3]);
    }
}

/* the checksum over every word, as the last step (its own request) */
static unsigned char build_rt_sum(void)
{
    FRAME[TGT_ASIC_WORDS_RUN - 1u] =
        hc_asic_frame_sum((unsigned char)TGT_ASIC_WORDS_RUN);
    return (unsigned char)TGT_ASIC_WORDS_RUN;
}

void hc_asic_start_service(unsigned int ms)
{
    unsigned char huge *prep = &HC_KL.asic_prep;   /* the pre-build step */
    unsigned char n;
    unsigned int tx1, tx2, tx3;

    if (hc_asic_run_live && (unsigned int)(ms - hc_asic_last_ok_ms) > 50u) {
        hc_asic_run_live = 0u;
    }

    switch (hc_asic_state) {

    case HC_ASIC_ST_IDLE:
        hc_asic_state = HC_ASIC_ST_SSC_INIT;
        break;

    case HC_ASIC_ST_SSC_INIT:
        asic_init();                       /* SSCCON/SSCBR/pins, PEC off      */
        asic_frame_clear();                /* ONCE - see asic_frame_clear()   */
        hc_asic_next_attempt = ms;
        run_now = 1;                       /* the SSC is up - go NOW          */
        hc_asic_state = HC_ASIC_ST_TX1;
        break;

    case HC_ASIC_ST_TX1:
    case HC_ASIC_ST_TX2:
    case HC_ASIC_ST_RUNTIME_TX:
        if (!run_now
            && (unsigned int)(ms - hc_asic_next_attempt) < (unsigned int)
               ((hc_asic_state == HC_ASIC_ST_RUNTIME_TX)
                ? TGT_ASIC_RUN_PERIOD_MS : TGT_ASIC_START_PERIOD_MS)) {
            /* THE IDLE WINDOW BELONGS TO THE CJ120s. The last runtime
               exchange is complete (we are in TX, not WAIT) and the next is
               at least 3 ms away, so one polled 2-byte CJ120 transaction
               (~40 us) cannot overlap a PEC transfer. */
            if (hc_asic_state == HC_ASIC_ST_RUNTIME_TX) {
                /* ONE short job per request (2026-10-14): the CJ120
                   transaction when it is due and inside its window (it
                   must end >= 3 ms before the next frame), else the next
                   pre-build step - those may run up to the frame itself */
                if ((unsigned int)(ms - hc_asic_next_attempt)
                        < (unsigned int)(TGT_ASIC_RUN_PERIOD_MS - 3u)
                    && hc_io_cj120_due(ms, hc_io_cj_mask)) {
                    hc_io_cj120_slot(ms, hc_io_cj_mask);
                    break;
                }
                if (*prep < PREP_READY) {
                    if (*prep == PREP_CAPTURE)   hc_hal_ain_capture();
                    else if (*prep == PREP_ZERO) build_rt_zero();
                    else if (*prep == PREP_FILL) build_rt_fill();
                    else                         (void)build_rt_sum();
                    (*prep)++;
                }
            }
            break;
        }
        /* A FLASH WORD HOLDS THE WINDOW (live_admit claimed it): the frame
           is due, so it starts on the NEXT 1 ms request - not a raster
           later, and not as an "SSC busy" refusal. Until 2026-10-14 the
           refusal below set the next attempt a whole period on: frame
           periods of exactly 20 ms during every Burn, then the S5500 reset
           MAIN (0x1C) and the Burn died with 0x0105 (car + bench). */
        if (hc_nvm_word_owned()) {
            break;
        }
        run_now = 0;                       /* consumed - one free start only  */

        if (hc_asic_state == HC_ASIC_ST_RUNTIME_TX
            && *prep == PREP_READY) {
            n = (unsigned char)TGT_ASIC_WORDS_RUN;   /* built in advance */
        } else {
            if (*prep == PREP_CAPTURE) {
                hc_hal_ain_capture();          /* never build over a reply */
            }
            n = build((unsigned char)(hc_asic_state == HC_ASIC_ST_RUNTIME_TX));
        }
        *prep = PREP_ZERO;       /* a failed frame rebuilds, no snapshot   */
        tx1 = FRAME[1]; tx2 = FRAME[2]; tx3 = FRAME[3];

        /* The select is NOT touched here. asic_start_transfer asserts it and
           the RX ISR raises it, which is the OEM's split and the only one
           where a single owner controls each edge. V4 drove it from both
           places and could not say which. */
        if (!asic_start_transfer(n)) {
            /* The SSC said busy. V4 treated that as "wait and retry" and the
               hardware showed where that ends: after the first cold boot,
               every warm boot reported TX=0000/0000 forever. A peripheral
               that is stuck busy will not un-stick itself, so escalate -
               after a few refusals, re-initialise the SSC completely.

               This also covers the case the schematic predicts: RSTIN_SM is
               driven from MAIN's own RSTOUT, and a C167 holds RSTOUT asserted
               until EINIT, so on a warm reset the ASIC is released only when
               WE finish starting up and is still booting when we first talk
               to it. The first exchanges after a reset SHOULD be expected to
               fail; what matters is that we keep recovering. */
            hc_asic_busy_refusals++;
            if (hc_asic_busy_refusals >= 3u) {
                hc_asic_busy_refusals = 0;
                hc_asic_reinits++;
                asic_abort_transfer();
                asic_init();               /* SSCEN low, full reconfigure     */
            }
            hc_asic_next_attempt = ms;
            run_now = 0;
            break;
        }
        hc_asic_busy_refusals = 0;
        words_in_flight = n;
        phase_mark = ms;
        if (hc_asic_state == HC_ASIC_ST_RUNTIME_TX) {
            hc_lf_asic_launch(ms, (unsigned int)T7, tx1, tx2, tx3,
                              (unsigned int)hc_asic_state, hc_asic_run_tx);
            hc_rtwit_frame_start((unsigned int)T7);   /* raster telemetry */
        }
        if (hc_asic_state == HC_ASIC_ST_RUNTIME_TX) hc_asic_run_tx++;
        else                                        hc_asic_start_tx++;
        hc_asic_state = (unsigned char)(hc_asic_state + 1u);   /* -> WAITn    */
        break;

    case HC_ASIC_ST_WAIT1:
    case HC_ASIC_ST_WAIT2:
    case HC_ASIC_ST_RUNTIME_WAIT:
        /* An SSC error is a failure in its own right, and it is the one the
           V4 log could not distinguish from silence. */
        if (asic_err_latched) {
            hc_asic_start_csum_err++;      /* counted separately below too    */
            hc_asic_ssc_errors++;
            hc_asic_retries++;
            if (hc_asic_state == HC_ASIC_ST_RUNTIME_WAIT) {
                hc_lf_asic_complete(ms, (unsigned int)T7,
                    FRAME[0], FRAME[1], FRAME[2], FRAME[3], 0u,
                    FRAME[words_in_flight - 1u], 2u,
                    (unsigned int)hc_asic_state,
                    hc_ssc_pec_tx_left(), hc_ssc_pec_rx_left(),
                    (unsigned int)(ms - phase_mark));
            }
            asic_abort_transfer();
            hc_asic_state = (unsigned char)(hc_asic_state - 1u);
            hc_asic_next_attempt = ms;
            run_now = 0;
            break;
        }
        if (xfer_done()) {
            hc_ssc_done = 0;               /* consume it                      */
            hc_asic_last_xfer_ms = (unsigned int)(ms - phase_mark);
            hc_asic_pec_tx_end = hc_ssc_pec_tx_left();
            hc_asic_pec_rx_end = hc_ssc_pec_rx_left();
            hc_asic_reply_w0 = FRAME[0];
            hc_asic_reply_w1 = FRAME[1];

            if (hc_asic_state == HC_ASIC_ST_RUNTIME_WAIT) hc_asic_run_rx++;
            else                                          hc_asic_start_rx++;

            {   /* Freeze the reply BEFORE judging it - a frame that fails
                   validation is exactly the one worth having. */
                unsigned int calc = hc_asic_frame_sum(words_in_flight);
                hc_asicdump_capture(hc_asic_state, hc_asic_start_tx,
                                    (unsigned int)words_in_flight, calc,
                                    FRAME[words_in_flight - 1u], ms,
                                    hc_asic_run_tx);
                hc_asic_last_calc = calc;
                hc_asic_last_recv = FRAME[words_in_flight - 1u];
                if (hc_asic_state == HC_ASIC_ST_RUNTIME_WAIT) {
                    hc_lf_asic_complete(ms, (unsigned int)T7,
                        FRAME[0], FRAME[1], FRAME[2], FRAME[3],
                        calc, FRAME[words_in_flight - 1u],
                        (unsigned int)(calc == FRAME[words_in_flight - 1u]
                                       ? 0u : 1u),
                        (unsigned int)hc_asic_state,
                        hc_asic_pec_tx_end, hc_asic_pec_rx_end,
                        hc_asic_last_xfer_ms);
                }
            }
            if (hc_asic_last_calc == FRAME[words_in_flight - 1u]) {
                /* (the sum taken above - not a second 117-word pass) */
                hc_asic_last_ok_ms = ms;
                hc_asic_retries = 0;
                /* Runtime is a START-TO-START raster. phase_mark is the
                   timestamp captured when this transfer started. Using the
                   completion time here silently adds the whole SSC transfer
                   duration (and any task-context polling jitter) to every
                   nominal 10 ms period. Physical V25 telemetry proves the
                   result: ~251 runtime starts by tick 3000, about 11.9 ms per
                   start. During a TunerStudio full-page read that cumulative
                   slip eventually trips the S5500 and resets MAIN. Anchor
                   the next runtime due time to the previous start; startup
                   phase advancement still uses run_now below. */
                hc_asic_next_attempt = ((hc_asic_state == HC_ASIC_ST_RUNTIME_WAIT)
                                ? phase_mark : ms);
                if (hc_asic_state == HC_ASIC_ST_RUNTIME_WAIT) {
                    /* The runtime dialogue REPEATS - it does not advance to a
                       new phase - so it keeps its period. run_now is for
                       getting THROUGH the startup sequence, not for spinning
                       the runtime exchange flat out: the OEM's runtime
                       handler is scheduler-driven [registered at 0x8BE8E4],
                       and a back-to-back dialogue is a behaviour change V10
                       has no evidence for. */
                    hc_asic_run_ok++;
                    hc_asic_run_live = 1u;
                    *prep = PREP_CAPTURE;  /* snapshot it, then rebuild */
                    if (run_initial < 2u) run_initial++;
                    hc_asic_state = HC_ASIC_ST_RUNTIME_TX;
                } else if (hc_asic_state == HC_ASIC_ST_WAIT1) {
                    /* PHASE ADVANCE: startup #1 accepted -> startup #2 NOW.
                       The OEM imposes nothing here (proof: 7/7 in
                       tools/me711_startup_delay_proof.py) and the 68 ms
                       deadline does not allow a 20 ms pause. */
                    hc_asic_start_ok++;
                    hc_asic_state = HC_ASIC_ST_TX2;
                    run_now = 1;
                } else {
                    /* PHASE ADVANCE: startup #2 accepted -> the FIRST runtime
                       exchange NOW. This is the transition V9 never reached. */
                    hc_asic_start_ok++;
                    hc_asic_state = HC_ASIC_ST_RUNTIME_TX;
                    run_now = 1;
                }
            } else {
                if (hc_asic_state == HC_ASIC_ST_RUNTIME_WAIT)
                    hc_asic_run_csum_err++;
                else
                    hc_asic_start_csum_err++;
                hc_asic_retries++;
                hc_asic_state = (unsigned char)(hc_asic_state - 1u);
                hc_asic_next_attempt = ms;         /* a RETRY waits out the period    */
            }
            break;
        }
        if ((unsigned int)(ms - phase_mark)
            >= (unsigned int)TGT_ASIC_XFER_TIMEOUT_MS) {
            if (hc_asic_state == HC_ASIC_ST_RUNTIME_WAIT)
                hc_asic_run_timeout++;
            else
                hc_asic_start_timeout++;
            hc_asic_retries++;
            if (hc_asic_state == HC_ASIC_ST_RUNTIME_WAIT) {
                hc_lf_asic_complete(ms, (unsigned int)T7,
                    FRAME[0], FRAME[1], FRAME[2], FRAME[3], 0u,
                    FRAME[words_in_flight - 1u], 3u,
                    (unsigned int)hc_asic_state,
                    hc_ssc_pec_tx_left(), hc_ssc_pec_rx_left(),
                    (unsigned int)(ms - phase_mark));
            }
            /* Release the select so the ASIC sees a clean edge next time. */
            ASIC_CS_LATCH_S = 1;
            asic_abort_transfer();
            hc_asic_state = (unsigned char)(hc_asic_state - 1u);
            hc_asic_next_attempt = ms;
            run_now = 0;
        }
        break;

    default:
        hc_asic_state = HC_ASIC_ST_IDLE;
        break;
    }
}

unsigned char hc_asic_healthy(void)
{
    return (unsigned char)(hc_asic_run_live && !asic_err_latched
        && (hc_asic_state == HC_ASIC_ST_RUNTIME_TX
            || hc_asic_state == HC_ASIC_ST_RUNTIME_WAIT));
}
