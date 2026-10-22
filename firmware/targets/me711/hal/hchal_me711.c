/*
 * hchal_me711.c - the HaniCore HAL for the Bosch ME7.1.1.
 *
 * SOME OF THIS ECU'S ENGINE SENSORS ARE NOT ON THE MAIN CPU. Bosch's port map
 * puts coolant (TMOT, cavity 93) on the S5500's AN0, intake air (TANS, cavity
 * 26) on its AN1 and further inputs on its other channels; they reach the
 * C167 only inside the S5500's runtime reply frame.
 *
 * Analog inputs:
 *   - main-CPU channels are converted by the 1 ms tick, one per tick, and
 *     published with their age by hcfresh711.c; a reading is valid only while
 *     its sample is fresh;
 *   - S5500 channels come from a 16-word window of the ACCEPTED runtime
 *     frame. Each word is a verbatim ADDAT, (channel << 12) | 10-bit result,
 *     and a slot is accepted only when its channel tag matches (bench-proven:
 *     the window carries ADC tags 0..15 in order);
 *   - which channel a semantic input reads follows the configuration
 *     (hc_route_service -> hc_hal_ain_bind); throttle and pedal tracks are
 *     read only where they are bound.
 *
 * Outputs: the resting state of every engine output is high impedance; an OFF
 * writes the inactive level first and then releases the direction. Engine
 * edges are timed by the compare-interrupt executor (hcdeadline711.c); this
 * file holds the port primitives and the slower lifecycles (pump, relay,
 * throttle bridge, ASIC port images).
 */
#include <reg167.h>
#include <intrins.h>
#include "hctarget.h"
#include "hcdeadline711.h"
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hchal.h"
#include "hc_route.h"
#include "hchal_me711.h"
#include "hcsched_dry.h"   /* hc_ign_ovd_latch */
#include "hc_pin_descriptor.h"   /* HC_ADC_NONE - one definition, not two */
#include "hc_config_manager.h"  /* hc_cfg_validation - a refused page
                                   must not reach a motor */
#include "hcasic.h"
#include "hcasicstart.h"
#include "hcsafety.h"        /* the permission layer, not duplicated here */
#include "hcio711.h"

extern unsigned int adc_raw[];

/* The census lives in the external SRAM - see hchal.h. TGT_RAM_HALCENSUS is
   declared in hctarget.h, once, like every other region of that chip. */
#define CENSUS ((unsigned int huge *)(TGT_EXTRAM_BASE + TGT_RAM_HALCENSUS))
#define CENSUS_REQ(i)  CENSUS[(i)]
#define CENSUS_VAL(i)  CENSUS[HC_OUT_COUNT + (i)]

#define OUT_HOT_N   16u          /* HC_OUT_IGN1..8 and HC_OUT_INJ1..8 */
#define OUT_UNROUTED 0u

unsigned char hc_hal_actuator_route[OUT_HOT_N]; /* sealed physical bit; zero unrouted */
static unsigned int  out_route_rev;
static unsigned int  out_on_ign, out_on_inj;  /* what is commanded ON, now */

unsigned int  hc_hal_out_calls;
unsigned char hc_hal_trig_armed;
/* THE LOGICAL MAIN_RELAY's HAL state. The request as last handed over,
   the cavity this HAL is DRIVING for it right now (HC_PIN_NONE when released),
   and whether the request is being refused for lack of permission. */
static unsigned char relay_request;
static unsigned char relay_driven_cav;
static unsigned char relay_inhibit;

unsigned int hc_hal_out_reqs(unsigned char sem)
{
    return (sem < HC_OUT_COUNT) ? CENSUS_REQ(sem) : 0u;
}

unsigned int hc_hal_out_value(unsigned char sem)
{
    /* The hot semantics are held in the near masks now - see hc_hal_actuator_route[]. */
    if (sem < OUT_HOT_N) {
        unsigned int m = (unsigned int)(1u << (sem & 7u));
        return (unsigned int)(((sem < 8u ? out_on_ign : out_on_inj) & m)
                              ? 1u : 0u);
    }
    return (sem < HC_OUT_COUNT) ? CENSUS_VAL(sem) : 0u;
}

/* ===================================================== the S5500 window ====
 *
 * 16 consecutive words of the last ACCEPTED runtime frame, and the ADDAT
 * decode of them. Both are published; the raw words are the evidence and the
 * decode is the hypothesis.
 */
#define S5500_N            16u
#define S5500_BASE_DEFAULT  4u      /* where the STARTUP frame carries it    */

/* The window itself is in the EXTERNAL SRAM (TGT_RAM_S5500WIN), for the same
   reason as the census: near RAM here is 1792 bytes and the engine layer has
   to fit in it. 32 words. */
#define WIN     ((unsigned int huge *)(TGT_EXTRAM_BASE + TGT_RAM_S5500WIN))
#define WIN_RAW(i)  WIN[(i)]
#define WIN_VAL(i)  WIN[S5500_N + (i)]

unsigned int  hc_s5500_idx;             /* bit i set = word i decoded with
                                           channel field == its own position */
unsigned char hc_s5500_base;            /* first frame word in the window    */
unsigned int  hc_s5500_snaps;           /* snapshots taken                   */
unsigned int  hc_s5500_plausible;       /* snapshots where ALL 16 indices
                                           matched - the V9 signature        */
static unsigned int s5500_last_ok;      /* hc_asic_run_ok at the last snap   */
extern unsigned int hc_tick_ms;

/* THE SWITCH INPUTS' REPLY WORDS, taken at the same accepted-frame
   edge as the window. hc_hal_din() used hcasic.c's asic_alive / RXSNAP,
   which only that module's own acceptance path (not the ME7.1.1 runtime
   exchange in hcasicstart.c) ever writes - on the bench every ASIC input
   read "unreadable" (real TunerStudio, 2026-10-02); the simulator gate had
   forced asic_alive. Stale (no accepted frame for 40 ms) = unreadable. */
/* generated from that table (hc_config_generated.h), not retyped */
static const unsigned char din_cav[HC_SWITCH_ASIC_N]  = HC_SWITCH_ASIC_CAV;
static const unsigned char din_word[HC_SWITCH_ASIC_N] = HC_SWITCH_ASIC_WORD;
static const unsigned char din_bit[HC_SWITCH_ASIC_N]  = HC_SWITCH_ASIC_BIT;
static unsigned int din_snap[HC_SWITCH_ASIC_N];
static unsigned int din_t;
static unsigned char din_live;

unsigned int hc_s5500_raw(unsigned char i)
{
    return (i < (unsigned char)S5500_N) ? WIN_RAW(i) : 0u;
}

unsigned int hc_s5500_val(unsigned char i)
{
    return (i < (unsigned char)S5500_N) ? WIN_VAL(i) : 0u;
}

/* THE SNAPSHOT WINDOW, and why this is race-free without touching a frozen
 * file.
 *
 * The exchange buffer at TGT_ASIC_FRAME is used IN PLACE - the PEC transmits
 * out of it and receives into it - so after a completed transfer it holds the
 * ASIC's reply, and hcasicstart.c's build() zeroes words 4..117 again before
 * the NEXT transmission. The reply is therefore valid only between those two
 * moments.
 *
 * That window is not tight: hcasicstart.c sets next_attempt = ms on a
 * successful runtime exchange and the next build waits out
 * TGT_ASIC_RUN_PERIOD_MS = 10 ms. The main loop runs far more often than once
 * per 10 ms, so snapshotting on the EDGE of hc_asic_run_ok - a counter that
 * advances only when a reply has passed both the checksum and the class test -
 * catches the frame with milliseconds to spare.
 *
 * asic_frame_word() already exists in hcasic.c and returns exactly this
 * buffer. NOTHING in the frozen platform layer had to change.
 */
/* 2026-10-13: THE EXCHANGE RUNS AT AN INTERRUPT LEVEL NOW (CC27, requested
   by the 1 ms tick - hcasicstart.c), so
   the main loop can no longer be relied on to see a reply before the next
   build() zeroes it: hc_asic_start_service() calls hc_hal_ain_capture() at
   the accept itself, at that level, before anything can rebuild the buffer.
   The service below keeps the freshness work and the staleness verdict. */
void hc_hal_ain_service(void)
{
    hc_fresh_service();
    if (!ASIC_SAMPLE_LIVE) din_live = 0u;
    if (din_live && !hc_asic_healthy()) {
        din_live = 0u;                /* the link stopped answering          */
    }
}

/* Called by hcasicstart.c the moment a runtime reply is accepted (CC27
   level, ILVL 9): the reply is in the buffer and nothing can rebuild it before this
   returns. Single words - every reader takes one word at a time. */
void hc_hal_ain_capture(void)
{
    /* the in-place buffer read directly (near, system page): this runs at
       the CC27 level, and 32 far function calls were most of its cost */
    const unsigned int *fw = (const unsigned int *)TGT_ASIC_FRAME;
    unsigned char i;
    unsigned int all = 1u;

    s5500_last_ok = hc_asic_run_ok;
    if (!hc_asic_run_live) return;
    ASIC_SAMPLE_MS = hc_asic_last_ok_ms;
    ASIC_SAMPLE_LIVE = 1u;
    for (i = 0; i < (unsigned char)HC_SWITCH_ASIC_N; i++) {
        din_snap[i] = fw[din_word[i]];
    }
    din_t = hc_tick_ms;
    din_live = 1u;

    hc_s5500_idx = 0;
    for (i = 0; i < (unsigned char)S5500_N; i++) {
        unsigned int w = fw[(unsigned char)(hc_s5500_base + i)];

        WIN_RAW(i) = w;
        WIN_VAL(i) = (unsigned int)(w & 0x03FFu);
        if ((unsigned int)((w >> 12) & 0x000Fu) == (unsigned int)i) {
            hc_s5500_idx |= (unsigned int)(1u << i);
        } else {
            all = 0;
        }
    }
    hc_s5500_snaps++;
    if (all) {
        hc_s5500_plausible++;
    }
}

/* Move the correlation window. Called from the '!' command so the bench can
   sweep the frame without a reflash. Bounded so it can never read past the
   frame. */
void hc_hal_s5500_window(unsigned char base)
{
    if ((unsigned int)base + S5500_N > (unsigned int)TGT_ASIC_WORDS_RUN) {
        base = (unsigned char)((unsigned int)TGT_ASIC_WORDS_RUN - S5500_N);
    }
    hc_s5500_base = base;
    ASIC_SAMPLE_LIVE = 0u;             /* require an actual new accepted reply */
    s5500_last_ok = hc_asic_run_ok;
}

/* ==================================================== analog channel map ===
 *
 * [BOSCH-PM] the ME7.1.1 schematic set sheet "FR", columns
 * "Belegung ME7.1.1 B-Muster" and "ME7.1.1 C-Muster, AUDI" - they agree on
 * every channel below. Confidence STRONG for all of them: this is the
 * manufacturer's own port map for this exact ECU variant, but not one has been
 * measured against a known voltage on THIS board. The raw counts are published
 * so the first bench run turns STRONG into CONFIRMED.
 *
 * 0xFF = no such channel on this board.
 * HC_ADC_ASIC(n) = the peripheral ASIC's AN n, read out of the S5500 frame -
 * see s5500_sample(). V86: the SAME code the descriptor gives cavities 93 and
 * 26, so a page that routes pinClt = 93 / pinIat = 26 binds exactly what this
 * table already reads and hc_route_check() agrees (it was 0xFE, a code no
 * cavity could carry, so the page had to say NONE).
 */
#define PHYS_NONE   0xFFu



/* THE BOUND CHANNEL PER SEMANTIC, in external SRAM (TGT_RAM_ROUTE).
 *
 * 0xFF means "the configuration routes nothing here", and every read then
 * falls back to PHYS[] - so an unconfigured page behaves exactly as every
 * image up to V61 did, and a Porsche board default, which routes the cavities
 * this board actually has, resolves to the same channels PHYS[] names.
 * hc_route_check() is the number that proves those two agree, and it reads 0.
 *
 * Out of near RAM deliberately: see TGT_RAM_ROUTE in hctarget.h. */
#define BOUND      ((unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_ROUTE))

void hc_hal_ain_bind(unsigned char sem, unsigned char adc_ch)
{
    hc_fresh_bind(sem, adc_ch);
}

unsigned char hc_hal_ain_bound(unsigned char sem)
{
    return hc_fresh_bound(sem);
}

/* THE S5500-OWNED TEMPERATURES, READ ONLY WHEN THE ADC SAYS WHICH THEY ARE.
 *
 * Cavity 93 E_A_TMOT -> N1100 -> TMOT_PXA50 and cavity 26 E_A_TANS -> N1100
 * -> TANS_PXA51 (the ME7.1.1 schematic, read twice): ASIC AN0
 * and AN1. The runtime reply carries them in mailbox slots 0 and 1 (frame
 * words 4 and 5; the OEM's own copy at [BIN 84:4B9A] masks slot 0 with
 * 0x03FF). THE WORD IS A VERBATIM ADDAT: bits 15..12 are the converter's own
 * channel number. So this is not window arithmetic - a sample is accepted
 * only when the ADC itself tagged it AN0 (or AN1), on every read, and a
 * moved window, a garbled frame or a different reply layout reads as "no
 * sensor" (substitute + sensorErr), never as a wrong temperature. BARO
 * (AN8, slot 8) was confirmed physically this same way at V61.
 *
 * WHAT IS STILL A MEASUREMENT: the transfer curve. The ASIC's pull-up is not
 * legible on the sheet, so cltSensAx/Val and iatSensAx/Val are calibrated with
 * a resistor on the cavity. A
 * tuner who routes pinClt/pinIat to a MAIN CPU analog cavity still wins: the
 * configured cavity is consulted first, exactly as for every other channel. */


/* any ASIC converter channel 0..15 out of the window, accepted only
   when the ADC itself tagged it that channel (as s5500_sample() above); 0xFFFF
   otherwise. The wideband layer reads the CJ120 UR outputs here: ASIC AN12
   (bank 1, U_LS1HVK_PXA512) and AN13 (bank 2) - the ME7.1.1 schematic p1 lower half. */
unsigned int hc_hal_asic_an(unsigned char ch)
{
    return hc_fresh_asic_an(ch);
}

unsigned int hc_hal_ain(unsigned char sem)
{
    return hc_fresh_ain(sem);
}

unsigned char hc_hal_ain_phys(unsigned char sem)
{
    return hc_fresh_phys(sem);
}

/* A SWITCH INPUT, BY CAVITY. Only the camshaft inputs are readable as
   a level on this board - open-collector front ends with the 2.61 k
   pull-up the sheet shows, CPU pins P2.8 (cavity 86) and P2.9 (cavity 87),
   whose live level the V77 outputPins word already publishes. A switch to
   ground reads 0. Any other cavity: 0xFF (no read path - the validator
   refuses routing a motorsport switch there). */
/* THE DIGITAL SWITCH INPUTS (hw_descriptors.SWITCH_INPUTS, the one
   table; me711_switch_input_proof holds this function to it).
   86/87: the phase inputs, CPU P2.8/P2.9 (2.61 kOhm pull-up).
   The OEM switch inputs reach the CPU through the S5500: every accepted
   runtime reply carries the ASIC's port snapshot in words 53..59 (P0, P1, P2,
   P3, P5, P6:P4, P8:P7 - S5500 IROM 0x48AE; this binary reads the same bits
   at 0x88F62C; bench 2026-10-01: our own P8.7/P7.4 output images appear in
   word 59). Unreadable (0xFF) while the ASIC link is down - a switch nobody
   can read is never "on". Returns the PIN LEVEL; polarity is the caller's. */
/* (din_cav / din_word / din_bit: above, beside the window snapshot) */

/* Does the cavity HAVE a read path? Static - the validator's question; the
   ASIC link being down at that instant does not make a route invalid. */
unsigned char hc_hal_din_ok(unsigned char cav)
{
    unsigned char i;

    if (cav == 86u || cav == 87u) {
        return 1u;
    }
    for (i = 0u; i < HC_SWITCH_ASIC_N; i++) {
        if (din_cav[i] == cav) {
            return 1u;
        }
    }
    return 0u;
}

unsigned char hc_hal_din(unsigned char cav)
{
    unsigned char i;

    if (cav == 86u) {
        return (unsigned char)((P2 & 0x0100u) ? 1u : 0u);
    }
    if (cav == 87u) {
        return (unsigned char)((P2 & 0x0200u) ? 1u : 0u);
    }
    for (i = 0u; i < HC_SWITCH_ASIC_N; i++) {
        if (din_cav[i] == cav) {
            if (!din_live || !hc_asic_healthy()) {
                return 0xFFu;
            }
            return (unsigned char)((din_snap[i] >> din_bit[i]) & 1u);
        }
    }
    return 0xFFu;
}

unsigned char hc_hal_ain_ok(unsigned char sem)
{
    return hc_fresh_ok(sem);
}

unsigned int hc_hal_ain_mask(void)
{
    unsigned int m = 0;
    unsigned char i;

    for (i = 0; i < HC_AIN_COUNT; i++) {
        if (hc_hal_ain_ok(i)) {
            m |= (unsigned int)(1u << i);
        }
    }
    return m;
}

/* ===================================================== the capture route ====
 *
 * THE ONLY PLACE ON THIS TARGET THAT TURNS A CONNECTOR CAVITY INTO A CAPTURE
 * CHANNEL, and it is three rows because this board has three such cavities.
 *
 * Evidence, per row, and all of it already in the tree:
 *
 *   cavity 82  DZG+_S   MAIN P2.15/CC15, both ME7.1.1 columns of
 *                       me711_iomap.csv agree, and the OEM ISR confirms it.
 *                       PHYSICALLY EXERCISED: crank sync 200..3000 rpm.
 *                       The front end is the CJ910's DIFFERENTIAL INDUCTIVE
 *                       interface - cavity 82 is DG+, cavity 90 is DG-, and
 *                       the clean one-edge-per-tooth signal comes back out on
 *                       the CJ910's NBM pin as KWDG. A Hall sensor does not
 *                       belong on it.
 *   cavity 86  PHA1_S   MAIN P2.8/CC8  = NWDG1. A LOGIC-LEVEL Hall input.
 *   cavity 87  PHA2_S   MAIN P2.9/CC9  = NWDG2. Likewise.
 *
 * Cavity 90 is deliberately NOT here. It is the negative half of one
 * differential pair, not a second capture input: assigning a decoder to it
 * would be assigning it to the same CJ910 channel cavity 82 already owns.
 *
 * ANY OTHER CAVITY ANSWERS HC_CAPCH_NONE, including cavities whose descriptor
 * carries FREQ_IN. A capability bit says what a circuit could do; this table
 * says what this board actually wired to a capture unit, and hc_validate()
 * refuses the difference instead of accepting a pin it cannot honour. */
unsigned char hc_hal_capture_channel(unsigned char pin)
{
    switch (pin) {
    case 82u: return TGT_CAPCH_CC15;
    case 86u: return TGT_CAPCH_CC8;
    case 87u: return TGT_CAPCH_CC9;
    default:  return HC_CAPCH_NONE;
    }
}

/* ---------------------------------------------------------------- position -
 *
 * Disabled by default in V27, and that is a decision rather than an omission.
 *
 * The pins are confirmed from Bosch's own port map - KWDG on P2.15/CC15 and
 * also P3.0/T0IN, NWDG1 on P2.8/CC8, NWDG2 on P2.9/CC9. Exact OEM ME7.1.1 code
 * proves their traps, capture modes and handlers. The ME7.5 board
 * MEASURED what arming a capture on an unconnected pin costs: a floating input
 * makes its own edges, the decoder read 20000 rpm, and the interrupt load
 * stopped the ECU answering TunerStudio.
 *
 * V27 therefore leaves the captures down by default and gates them on
 * CFG_TRIG_SOURCE, whose default is 0 = bench generator only, and reads it
 * LIVE. Arming is a deliberate TunerStudio edit, not a rebuild. rpm reads 0
 * on a stationary bench, which is the correct answer.
 */
void hc_hal_trig_arm(void)
{
    /* Observation only: the decoder owns the CAPCOM registers. */
    hc_hal_trig_armed = 1;
}

void hc_hal_trig_disarm(void)
{
    hc_hal_trig_armed = 0;
}

/* ==================================================== the bench-safe sink ==
 *
 * NOT ONE PORT, LATCH OR DIRECTION REGISTER IS WRITTEN IN THIS FILE.
 *
 * That is stronger than a runtime flag and it is checked mechanically:
 * tools/me711_output_safety_test.py disassembles the linked image and fails
 * the build if any instruction reachable from these functions writes P2, P7,
 * P8, DP2, DP7, DP8, ODP2/7/8, PWMCON0/1, PP0-PP3 or PT0-PT3.
 *
 * The census is not decoration: it is how a bench run proves the common
 * engine logic is asking for the right things - the right cylinder, at the
 * right time, the right number of times - while nothing can move.
 */
/* ======================================================= THE OUTPUT BACK END
 *
 * V63. Until now hc_hal_out() counted and returned, hc_hal_outputs_live()
 * returned 0 behind an #error, and nothing on this board could drive a pin.
 * The #error's text was precise about why - "the output back end does not
 * exist" - and that sentence is what this section makes false.
 *
 * ------------------------------------------------------------- THE SAFETY
 *
 * THE RESTING STATE OF EVERY ENGINE OUTPUT IS HIGH IMPEDANCE, NOT A LEVEL.
 *
 * That is the single most important decision here and it is deliberate. The
 * CPU pin does not drive a coil or an injector; it drives the INPUT of a
 * CJ920 / CJ420 low-side stage. THE ACTIVE POLARITY OF THOSE STAGES IS NOT
 * ESTABLISHED ANYWHERE IN THIS REPOSITORY - the maintainer's design notes says in
 * as many words that "polarity and cavity are what the test measures", and
 * the same is true of every EV and ZUE cavity.
 *
 * A resting LEVEL would therefore be a guess, and a wrong guess is an
 * injector held open by a parked ECU. A resting DIRECTION is not a guess:
 * an input pin drives nothing at all, whichever way the stage is wired, and
 * automotive driver ICs are designed to sit off when their input floats.
 *
 * So DPx stays 0 - input - for every engine output until three separate
 * conditions are all true, and goes back to 0 the moment any of them stops
 * being true. hc_hal_outputs_safe() is called from hc_hal_init(), before the
 * configuration has even been read.
 *
 * THE CONDITIONS FOR AN ON, and all are required (V84 - there is no longer a
 * user-facing arm; CFG_OUTPUTS_ARMED is a retired page byte):
 *
 *   1. the back end is compiled in           - HANICORE_BENCH_SAFE absent
 *   2. the CLASS is permitted by hcsafety.c  - spark/fuel need the crank;
 *                                              throttle/pump/relay need only
 *                                              the ALWAYS set (link, page,
 *                                              key on)
 *   3. the page is RUNNABLE                  - hc_cfg_validation == 0
 *   4. the semantic is ROUTED                - an unassigned cavity drives
 *                                              nothing
 *
 * Condition 3 is what stops a configuration that hc_validate() has already
 * refused from reaching a motor anyway. An OFF needs none of them: releasing
 * is safe whatever the permission (V75 cold path, V84 hot path).
 *
 * WHAT IS STILL NOT PROVEN, and must not be claimed: which way round each
 * stage is - EXCEPT EKP, which V76 measured ACTIVE-LOW (see
 * stage_active_high() below and hctarget.h TGT_EKP_ACTIVE_HIGH).
 *
 * THIS PARAGRAPH USED TO DESCRIBE A FUNCTION THAT DOES NOT EXIST. It said
 * "hc_hal_out_active_high() reads that from the page per class so that a bench
 * can MEASURE it rather than this file asserting it". **grep finds that name
 * only inside this comment.** What exists is `#define OUT_ACTIVE_HIGH 1u` and
 * a static that returns it: every output on this board is COMPILE-TIME
 * active-high, and the page has no say in it at all.
 *
 * So the comment claimed a configurability the firmware does not have, which
 * is the same defect as a TunerStudio knob nothing reads (12Q) pointed the
 * other way - and it is worse here, because the thing being claimed is a
 * safety property somebody might rely on.
 *
 * WHAT THE POLARITY ACTUALLY COSTS TODAY, stated rather than hand-waved.
 * Since 12P/12Q/12T every OFF path RELEASES the pin instead of driving it, so
 * a wrong OUT_ACTIVE_HIGH no longer leaves anything held at an active level.
 * What remains is: an ON command drives the wrong level, so the output simply
 * does not actuate - visible and safe - plus the two SFR writes between
 * "write inactive level" and "drop the direction" on the OFF path, during
 * which an inverted stage conducts.
 *
 * BOTH HALVES WERE MEASURED ON EKP (V75, 2026-09-25): "ON" left cavity 65
 * open for the whole prime, and every release sank it for 13-14 us - not "a
 * few CPU cycles". Harmless for a relay coil; not harmless for an injector,
 * which is why the other stages stay unenergised until measured.
 *
 * "MAKING IT PAGE-DRIVEN IS THE RIGHT FIX" USED TO BE WRITTEN HERE AND IS
 * RETRACTED. A stage's active level is a board fact, so it is a per-stage
 * constant (stage_active_high()), not a page field; see the note there.
 * the bench measurement has the two
 * same-family references, which disagree with each other; the M744 one
 * (active low) is the one the EKP measurement agrees with.
 */

/* Port identifiers for the tiny dispatcher below. Only the three ports that
   carry engine outputs on this board exist here. */
#define OP_NONE   0u
#define OP_P2     2u
#define OP_P7     7u
#define OP_P8     8u

/* A configured CAVITY resolved to (port, bitno). The mapping is the one the
   descriptor and tools/config_source/data/me711_iomap.csv carry, where both ME7.1.1
   columns agree; hw_descriptors.py is generated from the same sheet, and
   me711_output_backend_proof.py checks this table against it rather than
   trusting that two lists were typed the same way twice. */
void HC_COLD hc_hal_port_of(unsigned char cav, unsigned char *port, unsigned char *bitno);

/* Which cavity, if any, a logical output semantic is routed to RIGHT NOW. */
static unsigned char out_cavity_of(unsigned char sem)
{
    if (sem >= HC_OUT_IGN1 && sem < HC_OUT_IGN1 + 8u) {
        return hc_cal_u8((unsigned int)(CFG_U_PIN_IGN + (sem - HC_OUT_IGN1)));
    }
    if (sem >= HC_OUT_INJ1 && sem < HC_OUT_INJ1 + 8u) {
        return hc_cal_u8((unsigned int)(CFG_U_PIN_INJ + (sem - HC_OUT_INJ1)));
    }
    if (sem == HC_OUT_FUELPUMP) {
        return hc_cal_u8(CFG_U_PIN_FUEL_PUMP);
    }
    return HC_PIN_NONE;
}

/* THE ACTIVE LEVEL IS A PROPERTY OF EACH DRIVER STAGE, NOT OF THE BOARD, AND
 * NOT OF THE PAGE.
 *
 * The comment that stood here said this should become a page field. That was
 * the wrong fix: which CPU level turns a CJ920 stage on is a fact about the
 * silicon between the pin and the cavity, a tuner cannot change it, and a
 * page field would only have replaced a compile-time guess with a page-time
 * one. What IS the tuner's - which logical function drives which cavity - is
 * already on the page, and what a cavity can electrically do is in the
 * descriptor (LOW_SIDE: it sinks or it is open, it never sources).
 *
 * MEASURED: the EKP stage (P2.12 -> cavity 65) is ACTIVE-LOW at the CPU pin -
 * hctarget.h TGT_EKP_ACTIVE_HIGH, logic analyzer on the cavity, 2026-09-25.
 *
 * STILL INFERRED: every other stage (EV1..8, ZUE1..7) keeps OUT_ACTIVE_HIGH =
 * 1. The EKP result makes that inference WEAKER, not stronger - the same
 * NON-INVERTING symbol was drawn for it - so none of them may be energised
 * until each is measured the same way. They are released (input) at rest, as
 * EKP is, so an inverted stage is off whenever the HAL is not driving it. */
#define OUT_ACTIVE_HIGH 1u

/* coils and injectors take their level from hctarget.h per CLASS -
   TGT_IGN_ACTIVE_HIGH / TGT_INJ_ACTIVE_HIGH, active-LOW on the OEM's own
   key-on port init (see there). OUT_ACTIVE_HIGH is what any OTHER stage
   assumes, and no other stage is bound on this board. The DBW bridge legs
   (P7.2, P7.7, P2.11) are logic inputs to the S8100 and are not stages. */
#define IGN_LVL(on) ((unsigned char)((on) ? TGT_IGN_ACTIVE_HIGH \
                                          : !TGT_IGN_ACTIVE_HIGH))
#define INJ_LVL(on) ((unsigned char)((on) ? TGT_INJ_ACTIVE_HIGH \
                                          : !TGT_INJ_ACTIVE_HIGH))
/* THE TOOTH PATH PAYS NOTHING FOR THE SPLIT while the two classes agree: the
   class test folds away at compile time, so the per-event code is the same
   shape as V76's single constant (me711_plan_cost_proof: worst tooth 653
   instructions on both). Should a measurement ever make the classes differ,
   the runtime selection is what compiles - and the cost gate will say so. */
#if TGT_IGN_ACTIVE_HIGH == TGT_INJ_ACTIVE_HIGH
#define HOT_LVL(is_ign, on) IGN_LVL(on)
#else
#define HOT_LVL(is_ign, on) ((is_ign) ? IGN_LVL(on) : INJ_LVL(on))
#endif

static unsigned char stage_active_high(unsigned char port, unsigned char bitno)
{
    if (port == OP_P2) {
        if (bitno == (unsigned char)TGT_EKP_PORT_BIT) {
            return (unsigned char)TGT_EKP_ACTIVE_HIGH;
        }
        if (bitno < 8u) {
            return (unsigned char)TGT_IGN_ACTIVE_HIGH;   /* ZUE1..8 */
        }
    } else if (port == OP_P7) {
        if (bitno >= 4u && bitno <= 6u) {
            return (unsigned char)TGT_INJ_ACTIVE_HIGH;   /* EV3..EV1 */
        }
    } else if (port == OP_P8) {
        if (bitno >= 3u) {
            return (unsigned char)TGT_INJ_ACTIVE_HIGH;   /* EV8..EV4 */
        }
    }
    return OUT_ACTIVE_HIGH;
}

/* is the bridge enable DRIVEN AT ITS ACTIVE LEVEL right now? Read from
   the port, not a shadow - the bench qualifier drives it too. */
static unsigned char dbw_en_asserted(void)
{
    unsigned int m = (unsigned int)(1u << TGT_DBW_EN_PORT_BIT);
    if (!(DP2 & m)) {
        return 0u;
    }
    return (unsigned char)(((P2 & m) ? 1u : 0u) == (unsigned)TGT_DBW_EN_ACTIVE_HIGH);
}

static void port_set_dir(unsigned char port, unsigned char bitno,
                         unsigned char is_out)
{
    unsigned int m = (unsigned int)(1u << bitno);
    if (port == OP_P2) { if (is_out) DP2 |= m; else DP2 &= (unsigned int)~m; }
    else if (port == OP_P7) { if (is_out) DP7 |= m; else DP7 &= (unsigned int)~m; }
    else if (port == OP_P8) { if (is_out) DP8 |= m; else DP8 &= (unsigned int)~m; }
}

/* Is this pin an OUTPUT right now? Read from the direction register itself,
   so the answer is the port's and not a shadow's. */
static unsigned char port_is_output(unsigned char port, unsigned char bitno)
{
    unsigned int m = (unsigned int)(1u << bitno);
    if (port == OP_P2) { return (unsigned char)((DP2 & m) ? 1u : 0u); }
    if (port == OP_P7) { return (unsigned char)((DP7 & m) ? 1u : 0u); }
    if (port == OP_P8) { return (unsigned char)((DP8 & m) ? 1u : 0u); }
    return 0u;
}

static void port_write(unsigned char port, unsigned char bitno,
                       unsigned char level)
{
    unsigned int m = (unsigned int)(1u << bitno);
    if (port == OP_P2) { if (level) P2 |= m; else P2 &= (unsigned int)~m; }
    else if (port == OP_P7) { if (level) P7 |= m; else P7 &= (unsigned int)~m; }
    else if (port == OP_P8) { if (level) P8 |= m; else P8 &= (unsigned int)~m; }
}

/* EVERY ENGINE OUTPUT TO HIGH IMPEDANCE, unconditionally and without reading
   the configuration. Called from hc_hal_init() before anything is configured,
   and from hc_hal_outputs_safe() whenever arming is withdrawn. Walking the
   cavity table rather than a port mask means a cavity that is not an output
   on this board is never touched. */
void hc_hal_outputs_safe(void)
{
    static const unsigned char CAVS[18] = {
        96u, 97u, 88u, 89u, 112u, 113u, 24u, 19u,
        102u, 103u, 94u, 95u, 110u, 111u, 8u, 7u,     /* + ZUE8 */
        65u, 0u
    };
    unsigned char i, port, bitno;
    for (i = 0u; CAVS[i] != 0u; i++) {
        hc_hal_port_of(CAVS[i], &port, &bitno);
        if (port != OP_NONE) {
            /* the INACTIVE level of this stage, then input = high-Z = off */
            port_write(port, bitno,
                       (unsigned char)!stage_active_high(port, bitno));
            port_set_dir(port, bitno, 0u);
        }
    }
    /* The throttle bridge, by its own named constants. Duty to zero before
       the enable drops, the same ordering hc_dbw_shutdown() uses. */
    PWMCON1 &= (unsigned int)~0x0004u;            /* PWM channel 2 output off */
    port_write(OP_P7, (unsigned char)TGT_DBW_PWM_PORT_BIT, 0u);
    port_set_dir(OP_P7, (unsigned char)TGT_DBW_PWM_PORT_BIT, 0u);
    port_write(OP_P7, (unsigned char)TGT_DBW_DIR_PORT_BIT, 0u);
    port_set_dir(OP_P7, (unsigned char)TGT_DBW_DIR_PORT_BIT, 0u);
    port_write(OP_P2, (unsigned char)TGT_DBW_EN_PORT_BIT,
               (unsigned char)!TGT_DBW_EN_ACTIVE_HIGH);   /* inactive */
    port_set_dir(OP_P2, (unsigned char)TGT_DBW_EN_PORT_BIT, 0u);
}


/* ===================================== THE OUTPUT HOT PATH, PRE-RESOLVED ==
 *
 * me711_plan_cost_proof priced the first version: a tooth that executes a
 * batch injection event calls hc_hal_out() eight times, and every one of those
 * calls was doing THREE external-SRAM accesses - two census words and a
 * hc_cal_u8() to find out which cavity the semantic is routed to - plus two
 * nested permission calls. 416 instructions of a 1426-instruction tooth, 29 %,
 * to answer questions whose answers had not changed.
 *
 * NONE OF IT BELONGS BETWEEN TWO TEETH:
 *
 *   * the CAVITY a semantic is routed to changes only when the configuration
 *     is applied, and hc_cfg_active_rev already counts exactly that;
 *   * the PORT BIT a cavity resolves to never changes at all - it is a
 *     property of the board;
 *   * the ARMING byte is HC_APPLY_RPM_ZERO, so it cannot change while an
 *     engine is turning;
 *   * and the per-semantic census VALUE is read by nothing except the
 *     publisher that turns it back into these two masks.
 *
 * So the whole lot is resolved ONCE, into near memory, whenever the config
 * generation moves - which is the same trigger hctrig_me711.c uses to decide
 * when to re-read its geometry. Between two teeth the hot path touches near
 * memory only: one mask update, two near permission words, one table byte and
 * the port write itself.
 *
 * 20 bytes of near RAM, and they are the right 20 bytes: this is the tooth
 * path, and the project's rule is that cold data goes far and hot data does
 * not. The cold semantics - the pump, the throttle bridge, everything a bench
 * drives by hand - keep the far census exactly as before.
 */

/* Rebuild the resolved table. TASK CONTEXT ONLY - it reads the page. */
static void out_routes_resolve(void)
{
    unsigned char i, cav, port, bitno;

    unsigned char candidate[OUT_HOT_N], different = 0u;
    unsigned int ps;
    for (i = 0u; i < OUT_HOT_N; i++) {
        cav = (i < 8u)
            ? hc_cal_u8((unsigned int)(CFG_U_PIN_IGN + i))
            : hc_cal_u8((unsigned int)(CFG_U_PIN_INJ + (i - 8u)));
        candidate[i] = OUT_UNROUTED;
        if (!HC_PIN_IS_UNASSIGNED(cav)) {
            hc_hal_port_of(cav, &port, &bitno);
            if (i < 8u && port == OP_P2 && bitno < 8u)
                candidate[i] = (unsigned char)(1u << bitno);
            else if (i >= 8u && port == OP_P7 && bitno >= 4u && bitno <= 6u)
                candidate[i] = (unsigned char)(1u << (bitno - 4u));
            else if (i >= 8u && port == OP_P8 && bitno >= 3u && bitno <= 7u)
                candidate[i] = (unsigned char)(1u << bitno);
        }
        if (candidate[i] != hc_hal_actuator_route[i]) different = 1u;
    }
    ps = PSW & 0xF000u;
    if (ps < 0xD000u) _bfld_(PSW, 0xF000u, 0xD000u);
    _nop_(); _nop_();
    /* Release with OLD routes before installing a changed route table - an
       ABORT, not a quiesce: a committed edge would otherwise execute on the
       NEW route. Routing only changes with the engine stopped. */
    if (different && hc_dl_count) hc_drysched_abort(0u);
    for (i = 0u; i < OUT_HOT_N; i++) hc_hal_actuator_route[i] = candidate[i];
    out_route_rev = hc_cfg_active_rev;
    PSW = (unsigned int)((PSW & 0x0FFFu) | ps);
}

void far hc_hal_deadline_prepare_f(void)
{
    if (hc_cfg_active_rev != out_route_rev) out_routes_resolve();
}

unsigned int hc_hal_out_mask_ign(void) { return out_on_ign; }
unsigned int hc_hal_out_mask_inj(void) { return out_on_inj; }


unsigned char hc_hal_outputs_live(void)
{
#ifdef HANICORE_BENCH_SAFE
    /* The compile-time veto still exists and still wins. It is no longer an
       #error, because the thing it used to assert - that there is no back end
       - is no longer true. */
    return 0u;
#else
    /* THE PERMISSION LAYER IS hcsafety.c AND IT IS NOT DUPLICATED HERE.
       It weighs ASIC health, calibration, key-off, crank and cycle, and it
       is the one place that decides. This asks it.

       V84: THE PAGE ARMING BYTE IS GONE FROM THIS CHAIN. CFG_OUTPUTS_ARMED
       used to be ANDed in here, cached against hc_cfg_active_rev, and it made
       every normal engine output wait for a manual arm - which a standalone
       ECU must not need. The byte stays in the page, retired,
       so the layout id and every Burned calibration are unchanged. */
    if (!hc_dbw_allowed && !hc_ignition_allowed && !hc_injection_allowed) {
        return 0u;
    }
    /* A CONFIGURATION hc_validate() HAS REFUSED MUST NOT REACH A MOTOR.
       Defence in depth: cfg_fault_cache already feeds the supervisor above,
       and this reads the live verdict directly so a stale cache cannot arm. */
    if (hc_cfg_validation != 0u) {
        return 0u;
    }
    return 1u;
#endif
}

/* Per-class permission, for the callers that should ask a narrower question
   than "is anything allowed". An angle-scheduled output must not fire before
   the crank is synchronised even though a throttle may already hold. */
unsigned char hc_hal_out_class_live(unsigned char sem)
{
    if (!hc_hal_outputs_live()) {
        return 0u;
    }
    if (sem == HC_OUT_THR_PWM || sem == HC_OUT_THR_DIR
        || sem == HC_OUT_THR_EN) {
        return (unsigned char)(hc_dbw_allowed != 0u);
    }
    if (sem >= HC_OUT_IGN1 && sem < HC_OUT_IGN1 + 8u) {
        return (unsigned char)(hc_ignition_allowed != 0u);
    }
    if (sem >= HC_OUT_INJ1 && sem < HC_OUT_INJ1 + 8u) {
        return (unsigned char)(hc_injection_allowed != 0u);
    }
    return 1u;
}

/* EIGHT OUTPUTS, ONE CALL, AT MOST THREE PORT WRITES.
 *
 * Batch injection and paired wasted spark drive every slot of a class
 * together - HC_PLAN_SLOT_ALL - and the obvious way to express that is a loop
 * calling hc_hal_out() eight times. me711_plan_cost_proof priced it: 31
 * instructions a call, 248 a tooth, and about a third of that is function
 * frame rather than work. The permission is the same permission all eight
 * times, the route table is the same table, and the eight pins land on at
 * most three ports.
 *
 * So the check happens once and the writes are accumulated per port: the
 * read-modify-write of P2/P7/P8 is paid once each instead of once per pin.
 * `which` is a bitmask of slots, so this also serves a single slot and a
 * wasted-spark pair without a second entry point.
 *
 * SAME SEMANTICS AS hc_hal_out(), deliberately: the command masks are updated
 * before the permission is consulted, so a refused request is still visible to
 * a bench, and an unrouted slot silently drives nothing.
 */
/* Engine ISR supplies sealed physical masks after token checks. Fixed GPIO
   writes contain no routing scan. The task adapter below is OFF-only. */
unsigned int hc_hal_deadline_ports(unsigned char base, unsigned int which,
    unsigned char physical, unsigned char on)
{
    unsigned int a, b;
    if (!physical) return 0u;
    if (on && (hc_cfg_validation || (base == HC_OUT_IGN1
        ? !hc_ignition_allowed : (!hc_injection_allowed && !hc_prime_on)))) return 0u;
    if (base == HC_OUT_IGN1) {
        /* Widen BEFORE the complement. Keil compiles ~(unsigned char) as
           CPLB on the low byte, so (unsigned int)~physical was 0x00xx and
           every coil edge cleared P2.8..P2.15 (ON: the latches, OFF: the
           directions) - the fuel pump P2.12 and the bridge enable P2.11
           among them. me711_port_mask_proof reads the image for this. */
        a = physical;
        if (on) { P2 &= ~a; DP2 |= a; out_on_ign |= which; }
        else { P2 |= a; DP2 &= ~a; out_on_ign &= (unsigned int)~which; }
    } else {
        a = (unsigned int)((physical & 7u) << 4); b = physical & 0xF8u;
        if (on) { P7 &= (unsigned int)~a; P8 &= (unsigned int)~b; DP7 |= a; DP8 |= b; out_on_inj |= which; }
        else { P7 |= a; P8 |= b; DP7 &= (unsigned int)~a; DP8 &= (unsigned int)~b; out_on_inj &= (unsigned int)~which; }
    }
    return which;
}

void hc_hal_out_group(unsigned char base, unsigned int which, unsigned char on)
{
    if (on) return; /* engine ON requires CC25 pulse ownership */
    if (hc_cfg_active_rev != out_route_rev) out_routes_resolve();
    hc_hal_deadline_out(base, which, on);
}

void hc_hal_out(unsigned char sem, unsigned char on)
{
    unsigned char port, bitno, act, cav;

    if (sem >= HC_OUT_COUNT) {
        return;
    }
    hc_hal_out_calls++;

    /* ------------------------------------------------- THE HOT PATH ----
       Coils and injectors, scheduled against an engine angle. Near memory
       only: see the note on hc_hal_actuator_route[] above for why nothing here needs to
       ask the configuration anything. */
    if (sem < OUT_HOT_N) {
        /* An ON command needs a deadline token and an independent ending.
           Engine ON enters only through hc_hal_deadline_out from CC25.
           The board-index bench adapter reserves its own ending first. */
        if (!on) hc_hal_out_group((unsigned char)(sem < 8u ? HC_OUT_IGN1 : HC_OUT_INJ1),
                                  (unsigned int)(1u << (sem & 7u)), 0u);
        return;
    }

    /* ------------------------------------------------ THE COLD PATH ----
       The pump, the throttle bridge and everything a bench drives by hand.
       Nothing here runs between two teeth, so the far census stays exactly
       as it was and so does the full permission chain. */
    CENSUS_REQ(sem)++;
    CENSUS_VAL(sem) = (unsigned int)(on ? 1u : 0u);

    /* PERMISSION GATES ON, NEVER OFF. This used to return for BOTH
     * directions, so an OFF asked for after the permission had gone - a
     * disarm, a lost S5500 link, a page refused - left the pin exactly as
     * the last permitted ON had set it: DRIVEN. hc_hal_outputs_safe() only
     * runs from hc_hal_init(), so nothing else would ever release it.
     * Releasing a pin is the one thing that is safe whatever the permission,
     * the stage polarity or the configuration, so OFF always proceeds.
     *
     * AND RELEASING A RELEASED PIN WRITES NOTHING. hc_dbw_service() asks for
     * THR_EN/THR_DIR OFF on every pass; once OFF stopped being gated, that
     * became two port read-modify-writes per pass, from outside hcbench,
     * in the middle of a bench run - me711_bench_output_proof caught it.
     * The OFF branches below therefore act only on a pin that is an OUTPUT,
     * which is exactly the pin that needs releasing. */
    if (on && !hc_hal_out_class_live(sem)) {
        return;
    }

    /* OFF IS HIGH-IMPEDANCE, NOT DRIVEN LOW, AND THAT IS A SAFETY REGRESSION
     * BEING REPAIRED - see the maintainer's design notes.
     *
     * Until V62 the bench owned these pins directly and its dbw_disarm() put
     * the direction back to INPUT on the way out. V63 routed the bridge
     * through here, and this branch set the direction to OUTPUT
     * UNCONDITIONALLY - so hc_dbw_shutdown()'s `hc_hal_out(THR_EN, 0)`, the
     * call whose entire job is to DISABLE the bridge, left EGENFR a driven
     * output instead of releasing it.
     *
     * MEASURED, me711_dbw_bench_proof: V62 34/34, V63/V64/V65 23/34, with
     * `DP2 = 0x0800` and `DP7 = 0x0084` after a completed bounded bench
     * command - the bridge enable and the direction leg both left driven.
     *
     * 12M/1 made the resting state a DIRECTION precisely because the active
     * polarity of this stage is INFERRED and unmeasured: a driven level is a
     * guess about the S8100, a released pin is not. So the off path now does
     * what hc_hal_outputs_safe() has always done - write the inactive level
     * FIRST, then release the direction, so the pin is never left floating at
     * whatever the driver pulls it to for the instruction in between. */
    /* THE BRIDGE, READ OFF THE CJ220's OWN TRUTH TABLE (the Bosch CJ220 datasheet).
     *
     *   EN (our P2.11 -> DI): ACTIVE LOW - TGT_DBW_EN_ACTIVE_HIGH is 0 and
     *   hctarget.h carries the chain. V63..V82 drove it HIGH for "on", which
     *   is DISABLE, so the bridge never conducted.
     *
     *   DIR (P7.7 -> IN2): AN OPEN IN2 IS NOT "0". Row 8, "IN2 disconnected",
     *   gives OU2 = H - the input pulls itself HIGH. So while the bridge is
     *   enabled, direction 0 has to be DRIVEN LOW; releasing it there (what
     *   V63..V82 did for every forward step) commands reverse/freewheel. It is
     *   released only once EN is no longer asserted, which is the order
     *   hc_dbw_shutdown() and dbw_disarm() use: enable down first.
     *
     *   IN1 (P7.2/POUT2) FOLLOWS IN2 AT THE LATCH. The PWM unit XORs its
     *   output with the port latch [C167CR UM 16, "PWM x Latch P7.x XOR"], so
     *   with the latch equal to IN2: duty d forward is IN1 high for d (H,L);
     *   duty d reverse is IN1 LOW for d (L,H); and zero duty, with the channel
     *   disconnected, is IN1 = IN2 - a freewheel, never a full-on leg. Until
     *   V83 zero duty in reverse was IN1 = L, IN2 = H: FULL REVERSE. */
    if (sem == HC_OUT_THR_EN) {
        if (on) {
            port_write(OP_P2, (unsigned char)TGT_DBW_EN_PORT_BIT,
                       (unsigned char)TGT_DBW_EN_ACTIVE_HIGH);
            port_set_dir(OP_P2, (unsigned char)TGT_DBW_EN_PORT_BIT, 1u);
        } else if (port_is_output(OP_P2, (unsigned char)TGT_DBW_EN_PORT_BIT)) {
            port_write(OP_P2, (unsigned char)TGT_DBW_EN_PORT_BIT,
                       (unsigned char)!TGT_DBW_EN_ACTIVE_HIGH);
            port_set_dir(OP_P2, (unsigned char)TGT_DBW_EN_PORT_BIT, 0u);
        }
        return;
    }
    if (sem == HC_OUT_THR_DIR) {
        if (on || dbw_en_asserted()) {
            /* Input bits read the external pin, not the output latch.
               Establish BOTH outputs before the two whole-port RMWs:
               otherwise IN1's write undoes a LOW IN2 via its pull-up.
               C167 direction changes take one following instruction. */
            DP7 |= 0x0084u;
            _nop_();
            port_write(OP_P7, (unsigned char)TGT_DBW_DIR_PORT_BIT,
                       (unsigned char)(on ? 1u : 0u));
            port_write(OP_P7, (unsigned char)TGT_DBW_PWM_PORT_BIT,
                       (unsigned char)(on ? 1u : 0u));
            port_set_dir(OP_P7, (unsigned char)TGT_DBW_DIR_PORT_BIT, 1u);
        } else if (port_is_output(OP_P7, (unsigned char)TGT_DBW_DIR_PORT_BIT)) {
            port_write(OP_P7, (unsigned char)TGT_DBW_DIR_PORT_BIT, 0u);
            port_write(OP_P7, (unsigned char)TGT_DBW_PWM_PORT_BIT, 0u);
            port_set_dir(OP_P7, (unsigned char)TGT_DBW_DIR_PORT_BIT, 0u);
        }
        return;
    }

    cav = out_cavity_of(sem);
    if (HC_PIN_IS_UNASSIGNED(cav)) {
        return;
    }
    hc_hal_port_of(cav, &port, &bitno);
    if (port == OP_NONE) {
        return;
    }
    /* OFF RELEASES THE PIN, the same way the throttle branches above do and
     * the same way hc_hal_outputs_safe() always has - see the project rules and
     *
     *
     * This branch serves CAMSOL1/2, FUELPUMP and BOOST. Until V67 it ended
     * with port_set_dir(..., 1u) UNCONDITIONALLY, so an output the RUNTIME
     * turned off - a prime timing out, a solenoid released mid-run - was left
     * DRIVEN at `!act`, where `act` is the compile-time OUT_ACTIVE_HIGH.
     *
     * MEASURED, me711_armed_off_release_proof on V66: the real compiled
     * hc_fuelpump_service() commands the pump off with the page still ARMED
     * and DP2 bit 12 stays SET. hc_hal_outputs_safe() masked it in every
     * other gate, because those runs end by withdrawing arming.
     *
     * The level is per stage (stage_active_high()): measured for EKP, a
     * guess for the rest - which is exactly why the DIRECTION is the thing
     * that must come back. An input pin drives nothing whichever way the
     * stage is wired. Write the inactive level FIRST so the pin is never left
     * floating at whatever the driver pulls it to for the instruction in
     * between - and with the level right, that write is a no-op at the
     * cavity, where V75's wrong one sank cavity 65 for 13-14 us. */
    act = stage_active_high(port, bitno);
    if (on) {
        port_write(port, bitno, act);
        port_set_dir(port, bitno, 1u);
    } else if (port_is_output(port, bitno)) {
        port_write(port, bitno, (unsigned char)!act);
        port_set_dir(port, bitno, 0u);
    }
}

/* THE BRIDGE PWM PERIOD IS CONFIGURATION, CACHED IN COUNTS.
 *
 * TGT_DBW_PWM_PERIOD is the BOARD default (the OEM's own 2 kHz) and remains
 * the value this runs at until a page says otherwise, including before the
 * configuration is readable. hc_hal_dbw_pwm_hz() converts a validated page
 * frequency to f_CPU counts once, at apply time, so the 5 ms duty path keeps
 * doing one multiply and one divide and never a division by a page field.
 * The validator has already refused anything outside 1000..10000 Hz, but this
 * clamps too: the HAL is reached by bench and commissioning paths as well, and
 * a period that does not fit PP2 would alias to a frequency nobody asked for. */
/* ONE NEAR WORD, NOT THREE. Three statics here cost 63 bytes of near headroom
   (6 bytes of variables plus the segment growth the linker repacked around
   them) and took near_ram_hazard_proof from 193 to 130 bytes free, under its
   192-byte engineering reserve. Only the period has to be cheap to read - it is
   used on the 5 ms duty write - and the other two are recovered by dividing,
   which happens at the 10 ms poll and at the 10 ms publish, never per tooth. */
static unsigned int g_dbw_period;

/* The period a given page frequency asks for, clamped to what the CJ220 is
   rated to switch and to what PP2 can hold. Separated from the setter so the
   poll can compare periods without writing anything. */
static unsigned int dbw_period_for(unsigned int hz)
{
    unsigned long p;
    /* A BLANK FIELD MEANS THE BOARD DEFAULT, NOT THE SLOWEST LEGAL RATE. A
       fresh page reads 0 before hc_cal_defaults711() has run, and clamping
       that up to 1 kHz would quietly switch the bridge to a frequency no
       calibration was measured at. */
    if (hz == 0u) {
        return (unsigned int)TGT_DBW_PWM_PERIOD;
    }
    if (hz < 1000u) {
        hz = 1000u;
    } else if (hz > 10000u) {
        hz = 10000u;
    }
    p = (unsigned long)TGT_FCPU_HZ / (unsigned long)hz;
    if (p > 65535uL) {
        p = 65535uL;
    }
    return (unsigned int)p;
}

void hc_hal_dbw_pwm_hz(unsigned int hz)
{
    g_dbw_period = dbw_period_for(hz);
}

unsigned int hc_hal_dbw_pwm_period(void)
{
    return g_dbw_period;
}

unsigned int hc_hal_dbw_pwm_applied_hz(void)
{
    /* Derived from the period the hardware is loaded with, so this reports what
       the bridge is really switching at and not what a page asked for. */
    return g_dbw_period ? (unsigned int)((unsigned long)TGT_FCPU_HZ
                                         / (unsigned long)g_dbw_period) : 0u;
}

/* FOLLOW THE PAGE, FROM THE MAIN LOOP, NOT FROM THE DUTY PATH.
 *
 * Polling here rather than inside hc_hal_out_duty() does two things: the 5 ms
 * duty path keeps no page read at all, and the applied frequency - which the
 * UI shows and the characterization reports - becomes true as soon as a tuner
 * changes the field, instead of only once something next drives the bridge.
 * The divide happens on the edge, never per pass. */
void hc_hal_dbw_pwm_poll(void)
{
    unsigned int p = dbw_period_for(hc_cal_u16(CFG_U_DBW_PWM_HZ));
    if (p != g_dbw_period) {
        g_dbw_period = p;
    }
}

/* THE THROTTLE'S DUTY, on the C167 PWM unit channel 2 - P7.2, S8100 IN1.
 *
 * PWMCON0.2 enables channel 2, PWMCON1.2 connects it to the pin. PP2 is the
 * period and PW2 the pulse width, both counted on f_CPU/1 in mode 0. The
 * period is fixed at TGT_DBW_PWM_PERIOD so a duty is a plain scaling of it.
 *
 * WHAT IS INFERRED HERE AND MUST BE MEASURED: that IN1 carries the modulation
 * while IN2 selects the direction. That is the ordinary arrangement for a
 * two-input bridge and it matches the THR_PWM / THR_DIR / THR_EN semantics
 * this HAL has always exposed. V83: the S8100 IS a CJ220 and its truth table
 * IS in this repository (the Bosch CJ220 datasheet):
 * H/L forward, L/H reverse, L/L and H/H freewheel, an open input reads HIGH.
 * Which of forward/reverse OPENS a given throttle body is still the page's
 * dbwMotorDir, and 117/118 on a divided logic-analyser channel is the check. */
void hc_hal_out_duty(unsigned char sem, unsigned int duty_x10)
{
    unsigned long pw;

    if (sem >= HC_OUT_COUNT) {
        return;
    }
    CENSUS_REQ(sem)++;
    CENSUS_VAL(sem) = duty_x10;
    hc_hal_out_calls++;

    if (sem == HC_OUT_BOOST) {
        /* cavity 104 is the peripheral ASIC's LDR stage (ASIC P7.2),
           reached through the frame's port image - hcio711.c. Any other
           cavity, or no permission, commands it OFF. */
        hc_io_duty(HC_IO_LDR,
                   (hc_cal_u8(CFG_U_PIN_BOOST) == TGT_LDR_CAV
                    && hc_hal_out_class_live(sem)) ? duty_x10 : 0u);
        return;
    }
    if (sem != HC_OUT_THR_PWM || !hc_hal_out_class_live(sem)) {
        return;
    }
    if (duty_x10 > 1000u) {
        duty_x10 = 1000u;
    }
    /* MODE 0 IS HIGH WHILE PT >= PW, NOT WHILE PT < PW.
     *
     * [C167CR UM V3.1 16, Mode 0] "The PWM output signal is switched to high
     * level when the timer contents are equal to or greater than the contents
     * of the pulse width shadow register ... For a value of 0000H the output
     * will remain at a high level, representing a duty cycle of 100 %." With
     * PP = N-1 the period is N counts and the HIGH time is N - PW. V63..V82
     * wrote PW = N * duty, so IN1 was HIGH for (1 - duty): a 5 % request
     * drove the bridge at 95 %. V82's own cam PWM notes had the same fact the
     * other way round ("PW 0 = OFF ... ON duty = PW/2500", CJ920 inverting).
     * me711_dbw_pwm_proof executes this on the linked image. */
    pw = (unsigned long)g_dbw_period
         - ((unsigned long)g_dbw_period * (unsigned long)duty_x10) / 1000uL;
    PP2 = (unsigned int)(g_dbw_period - 1u);
    PW2 = (unsigned int)pw;
    if (duty_x10 == 0u) {
        /* ZERO DUTY DISCONNECTS THE CHANNEL AND LEAVES IN1 AT ITS LATCH, which
           hc_hal_out(THR_DIR) keeps equal to IN2: a freewheel whichever way
           the direction leg points. V82 forced the latch LOW here, which with
           IN2 HIGH is the CJ220's "Reverse" row at full current. */
        PWMCON1 &= (unsigned int)~0x0004u;
        port_set_dir(OP_P7, (unsigned char)TGT_DBW_PWM_PORT_BIT, 1u);
        return;
    }
    port_set_dir(OP_P7, (unsigned char)TGT_DBW_PWM_PORT_BIT, 1u);
    PWMCON1 |= 0x0004u;
    PWMCON0 |= 0x0004u;
}

/* ==================================================== the bridge fault pin ==
 *
 * S8100 pin 2, SF, reaching MAIN P3.15 - open drain on the bridge with R8100
 * pulling it to VCC_OUT, so the asserted level is LOW. P3.15's alternate
 * function is CLKOUT and it is free: the startup writes SYSCON 0xE644 or
 * 0xE244 and CLKEN (bitno 8) is clear in both, which
 * tools/me711_power_path_proof.py checks against the assembler rather than
 * against this comment.
 *
 * The direction register is written on every read. It costs one BCLR and it
 * means no other module can leave this pin an output and turn a fault
 * indication into a driven line.
 */
sbit DBW_SF_PIN = P3  ^ TGT_DBW_SF_PORT_BIT;
sbit DBW_SF_DIR = DP3 ^ TGT_DBW_SF_PORT_BIT;

unsigned char hc_hal_dbw_sf_level(void)
{
    DBW_SF_DIR = 0u;
    return (unsigned char)(DBW_SF_PIN ? 1u : 0u);
}

unsigned char hc_hal_dbw_sf_faulted(void)
{
    unsigned char lvl = hc_hal_dbw_sf_level();
    unsigned int mode = hc_cal_u16(CAL_DBW_SF_MODE);

    if (mode == HC_DBW_SF_LOW_IS_FAULT) {
        return (unsigned char)(lvl ? 0u : 1u);
    }
    if (mode == HC_DBW_SF_HIGH_IS_FAULT) {
        return lvl;
    }
    return 0u;                      /* HC_DBW_SF_IGNORE */
}

/* ====================================================== main power relay ==
 *
 * THE LOGICAL MAIN_RELAY, BOUND TO THE CONFIGURED CAVITY.
 *
 * Until V75 this was a RAM write and nothing else - "unbound", with
 * hc_hal_main_relay_bound() returning 0 on every page. That was right while
 * the only candidate anybody named was cavity 21, which is KL15, a power
 * input, and it stayed right for cavity 23, the OEM main-relay drive, which
 * this CPU cannot reach. V78 CORRECTS WHY: 23 is the CJ910's
 * own MR stage, enabled by KL15 and run-on alone - the ASIC only SENSES it -
 * so it is routable as a hardware function (bound = 2, see
 * hc_hal_main_relay_bound()) and nothing here ever writes it.
 *
 * What changed is not the evidence about 21 or 23. It is that MAIN_RELAY is a
 * GENERIC ROUTED FUNCTION and the generic output back
 * end has existed since V63: a cavity resolves through hc_hal_port_of() to a
 * MAIN CPU port bit or to nothing. So the relay is driven through exactly the
 * same resolution as the fuel pump and with exactly the same rules:
 *
 *   BOUND    the configured cavity resolves to a port this build can write.
 *            On ME7.1.1 today that is cavity 65 alone among the relay-class
 *            outputs, so a page that wants BOTH a main relay and a fuel pump
 *            on this board cannot yet have both - hc_validate() refuses the
 *            shared cavity as PIN_CONFLICT. Cavity 18 (ZAS2, P8.2, CJ420) is
 *            the candidate, blocked on the port map's own "variants differ"
 *            (ZAS2 vs CS_CJ120) until a power-off trace settles it.
 *   PERMIT   hc_hal_outputs_live(): compiled in, page VALID, key on, and
 *            the ALWAYS inhibits clear. A relay coil is a state, not an angle,
 *            so the crank is not asked (hcsafety.h).
 *   DRIVE    active level first, then the direction - the same order the
 *            cold path uses. OFF, and ANY loss of permission, writes the
 *            inactive level and RELEASES the direction, whatever the page.
 *
 * LEVEL, NOT EDGE. hcmainrelay.c hands its request over on every pass, and
 * this compares what SHOULD be driven with what IS - including the port's own
 * direction and level bits, so a pin somebody else released (the bench
 * qualifier's own exit path) is re-driven on the next pass instead of being
 * believed. The port is written only when the two differ.
 *
 * The OEM relay FEEDBACK (S5500 runtime word 11, wubr_w) is about cavity 23's
 * relay, not about whichever cavity HaniCore drives, so it stays invalid here.
 * The state HaniCore can honestly report is its OWN pin, and
 * hc_hal_main_relay_driven() reports it.
 */
static unsigned char port_is_driven_active(unsigned char port,
                                           unsigned char bitno)
{
    unsigned int m = (unsigned int)(1u << bitno);
    unsigned int dir = 0u, lvl = 0u;
    if (port == OP_P2) { dir = DP2 & m; lvl = P2 & m; }
    else if (port == OP_P7) { dir = DP7 & m; lvl = P7 & m; }
    else if (port == OP_P8) { dir = DP8 & m; lvl = P8 & m; }
    if (!dir) {
        return 0u;
    }
    return (unsigned char)(((lvl != 0u)
                            == (stage_active_high(port, bitno) != 0u))
                           ? 1u : 0u);
}

static void relay_release(unsigned char cav)
{
    unsigned char port, bitno;
    if (HC_PIN_IS_UNASSIGNED(cav)) {
        return;
    }
    hc_hal_port_of(cav, &port, &bitno);
    if (port != OP_NONE && port_is_output(port, bitno)) {
        port_write(port, bitno, (unsigned char)!stage_active_high(port, bitno));
        port_set_dir(port, bitno, 0u);
    }
}

void hc_hal_main_relay_set(unsigned char on)
{
    unsigned char cav, port, bitno, live;

    relay_request = (unsigned char)(on ? 1u : 0u);
    cav = hc_cal_u8(CFG_U_PIN_MAIN_RELAY);
    port = OP_NONE; bitno = 0u;
    if (!HC_PIN_IS_UNASSIGNED(cav)) {
        hc_hal_port_of(cav, &port, &bitno);
    }
    live = hc_hal_outputs_live();
    relay_inhibit = (unsigned char)((relay_request && port != OP_NONE
                                     && !live) ? 1u : 0u);

    if (!relay_request || port == OP_NONE || !live) {
        /* RELEASE - and release whatever this HAL was driving, which may be
           a cavity the page has since moved away from. */
        if (!HC_PIN_IS_UNASSIGNED(relay_driven_cav)) {
            relay_release(relay_driven_cav);
            relay_driven_cav = HC_PIN_NONE;
        }
        return;
    }
    if (relay_driven_cav != cav && !HC_PIN_IS_UNASSIGNED(relay_driven_cav)) {
        relay_release(relay_driven_cav);          /* the route moved */
    }
    if (relay_driven_cav == cav && port_is_driven_active(port, bitno)) {
        return;                                   /* already true: no write */
    }
    port_write(port, bitno, stage_active_high(port, bitno));
    port_set_dir(port, bitno, 1u);
    relay_driven_cav = cav;
}

/* 1 when the CONFIGURED cavity is one this build can drive at all; 2 when
   it is the NATIVE main-relay stage (cavity 23, the CJ910's MR), which
   nothing here drives because nothing here can - it follows KL15 in
   hardware (EN1) and run-on (/EN2 <- NLEN_FR, held vetoed by hcpower.c).
   Not a statement that it is being driven - see hc_hal_main_relay_driven().
   hc_hal_main_relay_set() needs no case for it: hc_hal_port_of(23) is OP_NONE,
   so set() writes nothing, which is the truth. */
/* V95 - see hchal.h. Mirrors the drive paths exactly: the fuel pump and a
   CPU-driven main relay go through hc_hal_port_of() (hc_hal_out /
   hc_hal_main_relay_set), the boost valve only through the ASIC LDR image on
   TGT_LDR_CAV (hc_hal_out BOOST), the CJ910 main-relay stage is a hardware
   function (MAIN_RELAY_HW, bound = 2). Tacho and the cam solenoids have NO
   output path in this build, so no cavity binds them. */
unsigned char hc_hal_out_bindable(unsigned int field, unsigned char cav)
{
    unsigned char port, bitno;

    if (field == CFG_U_PIN_BOOST) {
        return (unsigned char)((cav == TGT_LDR_CAV) ? 1u : 0u);
    }
    if (field == CFG_U_PIN_MIL) {            /* the ASIC P7.0 lamp stage */
        return (unsigned char)((cav == TGT_MIL_CAV) ? 1u : 0u);
    }
    if (field == CFG_U_PIN_TACHO) {          /* P2.13 / CC13 (hcroutes711) */
        return (unsigned char)((cav == TGT_TACHO_CAV) ? 1u : 0u);
    }
    if (field == CFG_U_PIN_CAM1_SOL || field == CFG_U_PIN_CAM2_SOL) {
        /* POUT0 / POUT1 (hcvvt711.c) */
        return (unsigned char)((cav == 115u || cav == 120u) ? 1u : 0u);
    }
    if (field == CFG_U_PIN_MAIN_RELAY
        && hc_pin_can(cav, HC_PINCAP_MAIN_RELAY_HW)) {
        return 1u;
    }
    if (field == CFG_U_PIN_FUEL_PUMP || field == CFG_U_PIN_MAIN_RELAY) {
        hc_hal_port_of(cav, &port, &bitno);
        return (unsigned char)((port != OP_NONE) ? 1u : 0u);
    }
    return 0u;
}

unsigned char hc_hal_main_relay_bound(void)
{
    unsigned char cav, port, bitno;
    cav = hc_cal_u8(CFG_U_PIN_MAIN_RELAY);
    if (HC_PIN_IS_UNASSIGNED(cav)) {
        return 0u;
    }
    if (hc_pin_can(cav, HC_PINCAP_MAIN_RELAY_HW)) {
        return 2u;
    }
    hc_hal_port_of(cav, &port, &bitno);
    return (unsigned char)(port != OP_NONE ? 1u : 0u);
}

/* The CPU pin is an OUTPUT at the ACTIVE level for MAIN_RELAY right now. A
   statement about the CPU port, read back from its own registers - not about
   the CJ920 stage, whose polarity is unmeasured, and not about a relay.

   FOR THE NATIVE STAGE there is no CPU pin, so the answer is the CJ910's own
   KL15 status output (pin 25 ST/IGN -> KL15_STAT, MAIN P6.2, both ME7.1.1
   port-map columns): the MR stage is enabled by the same EN1 that line
   reports. A PREDICTION from KL15, not a measurement of cavity 23 - the
   logic analyzer on cavity 23 is that, and it is pending. */
unsigned char hc_hal_main_relay_driven(void)
{
    unsigned char port, bitno;
    if (hc_hal_main_relay_bound() == 2u) {
        return (unsigned char)((P6 & (1u << TGT_KL15STAT_PORT_BIT)) ? 1u : 0u);
    }
    if (HC_PIN_IS_UNASSIGNED(relay_driven_cav)) {
        return 0u;
    }
    hc_hal_port_of(relay_driven_cav, &port, &bitno);
    return (port != OP_NONE) ? port_is_driven_active(port, bitno) : 0u;
}

/* Requested ON, bound, and refused for lack of permission. */
unsigned char hc_hal_main_relay_inhibited(void) { return relay_inhibit; }

unsigned int hc_hal_main_relay_feedback_dv(void) { return 0u; }
unsigned char hc_hal_main_relay_feedback_valid(void) { return 0u; }
unsigned char hc_hal_main_relay_feedback_state(void) { return 0u; }

/* The FUEL PUMP pin, read back the same way, for the same telemetry. */
unsigned char hc_hal_fuelpump_driven(void)
{
    unsigned char cav, port, bitno;
    cav = hc_cal_u8(CFG_U_PIN_FUEL_PUMP);
    if (HC_PIN_IS_UNASSIGNED(cav)) {
        return 0u;
    }
    hc_hal_port_of(cav, &port, &bitno);
    return (port != OP_NONE) ? port_is_driven_active(port, bitno) : 0u;
}

void hc_hal_init(void)
{
    unsigned char i;

    /* HIGH IMPEDANCE FIRST, BEFORE ANYTHING ELSE IN THIS FUNCTION.
       Not after the census, not after the ADC binding - before. The whole
       point of a resting direction rather than a resting level is that it
       holds from reset onwards, and that is only true if nothing gets to run
       in front of it. */
    hc_hal_outputs_safe();
    /* start_me711.a66 never runs Keil's ?C_INIT, so these start at whatever
       the SRAM held. 0xFFFF forces the first call to read the page. */
    out_route_rev = 0xFFFFu;
    /* THE PWM PERIOD AND ITS REPORTED FREQUENCY ARE AMONG THEM. Their C
       initialisers never run either: on the bench dbwPwmAppliedHz read 0 at
       boot and the cached period was whatever the SRAM held. Passing 0 means
       "the board default", and leaves g_dbw_hz at 0 so the first duty write
       still picks the page's own frequency up. */
    hc_hal_dbw_pwm_hz(0u);
    out_on_ign = 0u;
    out_on_inj = 0u;
    for (i = 0; i < (unsigned char)OUT_HOT_N; i++) {
        hc_hal_actuator_route[i] = OUT_UNROUTED;
    }

    /* start_me711.a66 hands straight to main() and never runs Keil's
       ?C_INIT, so NOTHING here starts at a known value. Every one of these is
       set explicitly - the lesson this project has already paid for twice. */
    for (i = 0; i < HC_OUT_COUNT; i++) {
        CENSUS_REQ(i) = 0;
        CENSUS_VAL(i) = 0;
    }
    for (i = 0; i < (unsigned char)S5500_N; i++) {
        WIN_RAW(i) = 0;
        WIN_VAL(i) = 0;
    }
    hc_hal_out_calls = 0;
    hc_hal_trig_armed = 0;
    relay_request = 0u;
    relay_driven_cav = HC_PIN_NONE;   /* hc_hal_outputs_safe() released it */
    relay_inhibit = 0u;
    for (i = 0; i < (unsigned char)HC_AIN_COUNT; i++) {
        BOUND[i] = HC_ADC_NONE;       /* nothing routed until hc_route binds */
    }
    hc_s5500_idx = 0;
    hc_s5500_base = (unsigned char)S5500_BASE_DEFAULT;
    hc_s5500_snaps = 0;
    hc_s5500_plausible = 0;
    s5500_last_ok = 0;
    hc_fresh_init();
    hc_route_init();
    din_live = 0u; din_t = 0u;
}
