/* ME7.1.1 platform startup and bounded background services.
   Capture, ignition and injection use dedicated interrupt levels. DBW is
   polled at service boundaries; communications and diagnostics yield to
   engine work. Linked-image gates do not qualify physical actuator timing. */
#include <reg167.h>
#include "hctarget.h"
#include "hcconfig.h"
#include "hcts.h"
#include "hcasic.h"
#include "hcasicframe.h"
#include "hcasicstart.h"
#include "hcasicdump.h"
#include "hcpower.h"
#include "hchal.h"
#include "hchal_me711.h"
#include "hctrigger.h"
#include "hcsched_dry.h"
#include "hcdeadline711.h"
#include "hcbench.h"
#include "hcnvm.h"
#include "hcburnforensics.h"
#include "hcliveforensics.h"
#include "hcsafety.h"
#include "hcengine.h"
#include "hcmainrelay.h"
#include "hcfuelpump.h"
#include "hc_dbw.h"
#include "hcetbcal.h"         /* ETB calibration / autotune (far) */
#include "hc_config_manager.h"
#include "hc_pin_descriptor.h"
#include "hc_presets.h"
#include "hc_route.h"
#include "hcio711.h"
#include "hcboost711.h"
#include "hcidle711.h"
#include "hcknock711.h"       /* knock window, CC195, retard per slot */
#include "hcvvt711.h"         /* cam phase control, POUT0/POUT1 */
#include "hctrans711.h"    /* transient fuel */
#include "hcdtc711.h"
#include "hclimp711.h"
#include "hckwp_me711.h"      /* VAG/KWP vehicle entry (far) */
#include "hcrtmon711.h"       /* runtime health record (far) */
#include "hcserial711.h"      /* PEC6 receive, interrupt transmit */

sbit TXD0_LATCH = P3 ^ 10;
sbit TXD0_DIR   = DP3 ^ 10;
sbit RXD0_DIR   = DP3 ^ 11;

/* ------------------------------------------------------------- diagnostics */
extern unsigned int hc_badvec;      /* interrupts nobody enabled             */
extern unsigned int hc_firstvec;
extern unsigned int hc_lastvec;

unsigned int boot_stage;
unsigned int loop_count;
unsigned int frames;
/* NOT static: the catch-all trap handlers timestamp themselves with it, so an
   NMI that is followed by a reset before the next 10 ms raster still records
   WHEN it happened. That is precisely what was lost on the second hardware
   run, where TR=0002 survived and the tick did not. */
unsigned int hc_tick_ms;
#define tick_ms hc_tick_ms
unsigned int tick_ok;        /* the tick was seen to move at boot     */
unsigned int cal_ticks;      /* MEASURED T7 ticks per transmitted byte */
unsigned int status;
static unsigned int och_mark;       /* ms at the last telemetry refresh      */
static unsigned int alive_mark;     /* ms at the last alive line             */
/* NOT static: hchal_me711.c resolves the S5000-direct semantic channels
   straight out of this array, exactly as hchal_me75.c does on the other
   board. The round robin in adc_service() below is still the only writer. */
unsigned int adc_raw[TGT_ADC_CH_COUNT];
/* THE ADC OWNER'S ONE BYTE (XRAM near data is full to the byte):
   bits 0..3 the round robin's channel, 4 knock asks for KI (hcknock711.c),
   5 the KI sample is in adc_raw[15], 6 the conversion in flight is that KI
   read, 7 a conversion is in flight. The knock sets/clears 4 and 5 under the
   critical level; everything else is the tick's. */
volatile unsigned char hc_adc_ctl;
#define ADC_RR      0x0Fu
#define ADC_KI_REQ  0x10u
#define ADC_KI_DONE 0x20u
#define ADC_KI_RUN  0x40u
#define ADC_BUSY    0x80u
static unsigned char yield_armed;   /* the platform is up (hcts_target_yield) */
static void adc_service(void);      /* the 1 ms tick's, below */
static unsigned char s5500_page_last; /* the page value the window last took */
unsigned int cfg_fault_cache;
static unsigned int cfg_fault_gen;
static unsigned int cfg_settle_gen;
static unsigned int cfg_settle_t;

static unsigned int  uptime_s;      /* whole seconds, does not wrap at 65.5 s */
static unsigned int  uptime_mark;

/* Fine-grained persistent markers. The high byte names the broad boot stage;
   the low byte orders operations inside the reset-sensitive transition. */
#define DIAG_BEFORE_IEN       0x0901u
#define DIAG_AFTER_IEN        0x0902u
#define DIAG_BEFORE_ASIC      0x0A01u
#define DIAG_ASIC_ISOLATED    0x0A02u
#define DIAG_MAIN_LOOP        0x0B01u

/* ============================================== RESETDIAG_V4: the handshake
 *
 * There is no A/B in this build. Four experiments settled what they could:
 *
 *   V1  watchdog serviced, WDTR clear            -> not the watchdog
 *   V2  bare P6.4 chip-select pulses             -> no effect, PT=0x0134
 *   V3  NLEN_FR asserted vs not                  -> no effect, PT=0x0134
 *   and every one of them reports RAW=0x001C with PONR CLEAR, which on this
 *   part means a long hardware reset through RSTIN with the supply INTACT.
 *   A genuine power-on sets PONR and the first boot of a session does show
 *   0x3C, so the 5 V rail is provably not cycling.
 *
 * V3 also explained itself: BASE reported NL=0001/0000 - latch 0, direction
 * input, pin reading HIGH. On the C167 an input reads the PIN, so NLEN_FR was
 * already high without us. Asserting it could not change anything.
 *
 * That leaves an external agent pulling RSTIN while VCC stays up, and the ASIC
 * IROM names the condition: it validates the frame it receives with
 * one's-complement pairs and, on any mismatch, runs
 *      0x007878  BCLR P1H.2   ESRST_SM
 *      0x00787A  BCLR P1H.3   SWRST_SM   <- resets the main computer
 * A HaniCore that transmits nothing can never satisfy that check.
 *
 * So this build TALKS TO THE ASIC, with the OEM's own startup frame, and
 * records in battery-backed SRAM exactly how far it got.
 */

/* NLEN_FR (P3.12) and the ASIC select (P6.4), for the live line. Reading a
   port bit that is an OUTPUT returns the latch; reading one that is an INPUT
   returns the PIN. That distinction is not pedantry - it is how V3's BASE half
   reported NL=0001/0000 and told us the net is externally high. */
sbit NLEN_FR_LATCH = P3  ^ TGT_NLEN_FR_PORT_BIT;
sbit NLEN_FR_DIR   = DP3 ^ TGT_NLEN_FR_PORT_BIT;

#define OCHP   OCH

/* ==================================================== the 1 ms system tick =
 *
 * T8, trap 0x3E. [DS] C167CR UM Table 5-1 gives T8INT that number, and the
 * ME7.5 board MEASURED it there on the bench, so this is a datasheet value
 * with an independent confirmation rather than a guess.
 *
 * V50 F1: THE HARDWARE RELOADS T8, NOT THIS ISR.
 *
 * Up to V49 this routine wrote T8 = 0 - TGT_TICK_RELOAD on every entry, with
 * T8REL left at 0. That made a single lost T8 request catastrophic rather than
 * merely late: if the ISR does not run, nothing reloads T8, so the next
 * overflow is a FULL period away - 65536 ticks at 1.25 MHz = 51.4 ms, not
 * 1 ms. On 2026-09-11 that is exactly what happened on the ECU, and because
 * hc_asic_start_service(tick_ms) is clocked by this tick, the S5500 raster
 * stopped dead and the supervisor reset the CPU 25.80 ms later.
 *
 * [DS] C167CR Derivatives User's Manual V3.1 (2000-03), section 15, The
 * Capture/Compare Units - the chapter that names T0R, T1R, T7R and T8R:
 *
 *     "When a timer overflows from FFFFH to 0000H it is reloaded with the
 *      value stored in its respective reload register TxREL."
 *
 * Unconditional. There is no reload-enable bit for the CAPCOM timers. So
 * programming T8REL once at init gives exactly the same period with none of
 * the fragility:
 *
 *     PT8 = (2^16 - <T8REL>) * 2^(<T8I>+3) / fCPU
 *         = (65536 - 64286) * 2^5 / 40 MHz = 1250 * 32 / 40e6 = 1.000000 ms
 *
 * F1 is NOT a substitute for F2 - hcnvm.c's IE-only masking is what makes
 * request destruction impossible. F1 is what keeps a delayed or lost tick a
 * 1 ms event instead of a 51.4 ms one, for any future cause.
 *
 * A bonus, not the reason: the period no longer includes ISR entry latency,
 * because the reload happens in hardware at the overflow rather than several
 * instructions later.
 *
 * It is deliberately the ONLY periodic interrupt in this build apart from the
 * serial drain: a bench image that resets is nearly always an image that armed
 * something it did not understand.
 */
void hc_tick_isr(void) interrupt TGT_TRAP_T8INT using TICKBANK
{
    unsigned int lf_now;
    unsigned int lf_gap;
    HC_PROBE_CLAIM(TGT_TRAP_T8INT);

    /* NO SOFTWARE RELOAD HERE. See the note above; T8REL does it. */
    lf_now = 0u;
    if (hc_lf_fast_active != 0u)
        lf_now = (unsigned int)T7;
    tick_ms++;
    asic_tick();
    if (yield_armed) {
        adc_service();   /* the main ADC's only owner (above) */
    }
    hc_rt_supervise();   /* CC25 liveness, stack guard (hcsafety.h) */
    if (rx_irq_mode) {
        hc_pecrx_tick(); /* K-line bytes PEC6 stored -> hcts ring */
    }
    if (hc_lf_fast_active != 0u) {
        lf_gap = (unsigned int)(lf_now - HC_LF_WORD(LF_TICK_LAST_T7));
        HC_LF_WORD(LF_TICK_LAST_T7) = lf_now;
        HC_LF_WORD(LF_TICK_LAST_GAP) = lf_gap;
        if (lf_gap > HC_LF_WORD(LF_TICK_MAX_GAP))
            HC_LF_WORD(LF_TICK_MAX_GAP) = lf_gap;
    }
    /* The ASIC handshake is NOT serviced here. It copies 96 words and runs a
       state machine; that belongs in the main loop, where it cannot delay the
       serial drain. The tick only advances time. */
    /* V2's chip-select stimulus is deliberately gone. Nothing in this build
       drives P6.4, in either half. */
}

/* --------------------------------------------------------------------- ADC
 * ONE conversion per main-loop pass, round robin - never a whole sweep.
 *
 * That is a MEASURED rule from the ME7.5 board, not a style preference: a
 * 16-channel sweep blocks the loop for tens of milliseconds, and the receive
 * register holds exactly one byte. A request arriving during a sweep loses
 * every byte but its last and is never answered, and TunerStudio disconnects.
 *
 * ADCON's 0xF000 is the slowest conversion timing the part offers. On a 40 MHz
 * ST10 that is the only setting that is certainly in specification, and
 * telemetry does not need speed.
 */
/* THE MAIN ADC HAS ONE OWNER: THE 1 MS TICK. It used to be
   called from the main loop and every serial yield, so how often a channel
   was sampled depended on how fast the main loop ran: at 8500 rpm with
   TunerStudio polling at 115200 a TPS track went > 100 ms without a sample,
   hc_fresh_service() latched DBW_F_STALE and engine protection cut the fuel
   (simulator, docs/ARCHITECTURE.md). Now one
   conversion completes and the next starts every tick: each of the sixteen
   channels every 16 ms, the AN1/AN3 TPS pair 1 ms apart, whatever the loop
   is doing. The knock KI read (AN15) is a REQUEST served here, not a second
   writer of ADCON; the requested conversion starts AFTER the request (a
   round-robin AN15 sample may predate the window close). */
static void adc_service(void)
{
    unsigned int word;
    unsigned char c = hc_adc_ctl, ch;
    if (c & ADC_BUSY) {
        if (ADBSY || !ADCIR) return;
        ch = (unsigned char)((c & ADC_KI_RUN) ? 15u : (c & ADC_RR));
        word = ADDAT;
        hc_hal_main_sample(ch, word, 1u, MAIN_ADC_STARTED);
        ADCIR = 0;
        if (c & ADC_KI_RUN) {
            c = (unsigned char)((c & ADC_RR) | ADC_KI_DONE);
        } else {
            c = (unsigned char)((c & (ADC_KI_REQ | ADC_KI_DONE))
                | ((ch == 1u) ? 3u : (ch == 3u) ? 2u
                   : (ch == 2u) ? 4u : (ch + 1u) & 15u));
        }
    } else if (ADBSY) return;
    if ((c & (ADC_KI_REQ | ADC_KI_DONE)) == ADC_KI_REQ) {
        ch = 15u;
        c = (unsigned char)((c & ADC_RR) | ADC_BUSY | ADC_KI_RUN);
    } else {
        ch = (unsigned char)(c & ADC_RR);
        c |= ADC_BUSY;
    }
    hc_adc_ctl = c;
    ADCON = (unsigned int)(0xF000u | ch);
    ADCIR = 0;
    MAIN_ADC_STARTED = tick_ms;
    ADST = 1;
}



/* ================================================= the timer rate, MEASURED
 *
 * TGT_TICKS_PER_MS_X10 is derived from the datasheet and from the OEM's own
 * baud constant, and that derivation is sound - but this project's rule is
 * VERIFY, NEVER DERIVE, and it has that rule because a factor-of-two error in
 * exactly this number went unnoticed on the other target for weeks.
 *
 * So the rate is measured against something whose duration is fixed by the
 * silicon and not by our arithmetic: the time to shift one byte out of ASC0.
 * At the nominal 57600 setting the nearest safe integer reload produces
 * 56,818 baud. One 8N1 byte is 176 us, which at 1.25 MHz is about 220 ticks.
 *
 * Published as calTicks and printed in the banner, so it can be read with a
 * plain terminal before TunerStudio is ever involved. Half or double means the
 * prescaler constant is wrong and EVERY timing in the firmware is scaled with
 * it - which is exactly the reading a first bench test should hand back.
 *
 * the two measurement bytes go out through ASC0's S0LB INTERNAL
 * loopback, not the wire - see hcts_rx_learn() below (and
 * docs/ARCHITECTURE.md, "S0LB, a loopback bit that ties the
 * transmitter to the receiver inside the chip... keeps a stray byte off the
 * wire", hardware-confirmed for that probe) for the same mechanism used the
 * same way. Real K-line tracing over a genuine KKL cable found this
 * function's two 0x00 bytes going out UNSOLICITED before anything asked for
 * them - this was the version that used the wire directly, the same mistake
 * S0LB already existed to fix elsewhere in this file. echo_seen is left
 * clear across it for the same reason as before: with the wire never
 * touched there is nothing on it to wait for or drop.
 */
static void cal_measure(void)
{
    unsigned int t0, t1;
    unsigned int guard;

    echo_seen = 0;
    S0LB = 1;

    S0TIC &= 0x7F;
    S0TBUF = 0x00;
    guard = 40000u;
    while (((S0TIC & 0x80) == 0) && --guard) {
        hc_srvwdt();
    }
    S0TIC &= 0x7F;
    t0 = T7;
    S0TBUF = 0x00;
    guard = 40000u;
    while (((S0TIC & 0x80) == 0) && --guard) {
        hc_srvwdt();
    }
    S0TIC &= 0x7F;
    t1 = T7;
    cal_ticks = (unsigned int)(t1 - t0);
    S0LB = 0;

    /* Whatever the internal loopback delivered into the receive path, drain
       it here rather than let it surface as a phantom byte once hcts_rx_pump()
       starts being called from the ordinary boot path. One millisecond is
       more than five byte times at this baud. */
    t1 = 0;
    guard = T7;
    while ((t1 < 2)
           && (unsigned int)(T7 - guard) < (unsigned int)US_TO_TICKS(1000u)) {
        unsigned char b;

        hc_srvwdt();
        hcts_rx_pump();
        if (hcts_rx_pop(&b)) {
            t1++;
        }
    }
    echo_seen = 1;
}


extern void far hc_diag_publish(void);
extern unsigned char far hc_diag_publish_step(void);
static unsigned char och_cycle;   /* a sliced publication is in progress */
extern void far hc_preset_cmd_service_cold(void);
extern void far hc_target_cmd_cold(unsigned char *p, unsigned int n);
static void update_live(void) { hc_diag_publish(); }
void hc_preset_cmd_service(void) { hc_preset_cmd_service_cold(); }
void hcts_target_cmd(unsigned char *p, unsigned int n) { hc_target_cmd_cold(p, n); }

/* ------------------------------------------------------------ live values */
/* Read one published word back. The OUTPUT CHANNEL BLOCK IS ORDINARY EXTERNAL
   SRAM, so a counter can live there and be incremented in place - which is how
   the endpoint grab keeps its state without spending a byte of near RAM. Big
   endian, matching put16(). */
/* The output-channel block. Every number here answers a question the first
   bench test asks, and the order is the order somebody standing at the bench
   would want them in: did it boot, is it alive, is the serial link healthy, is
   the ASIC there, what do the sensors read.

   TGT_OCH_SIZE must match ochBlockSize in the .ini. tools/ts_ini_check.py
   enforces that; do not edit one without the other. */
/* When hc_stack_used() last re-scanned. Explicitly zeroed in main() with
   everything else: this startup runs no ?C_INIT. */
unsigned int stack_scan_ms;

/* V79. The run-on verdict of this pass and the N75 request, for the OCH. */
static unsigned char io_ro;
unsigned int io_boost_req;



/* ============ THE PLATFORM YIELD - THE ONE THING THAT LETS TS RUN HERE ====
 *
 * hcts_tx() is baud-paced and blocking, and on this board that is a reset:
 *
 *      one byte at nominal 57600 8N1           about 176 us
 *      the output-channel reply                -> tens of ms
 *      the calibration page reply              -> over 100 ms
 *      even the bare signature reply           -> 15 ms
 *
 * against a 10 ms S5500 supervision raster serviced ONLY from the main loop.
 * A single routine TunerStudio poll would starve hc_asic_start_service() for
 * several rasters, which is exactly the V15 defect that reset this ECU at
 * ~140 ms every boot (docs/ARCHITECTURE.md).
 *
 * So the shared server calls this from every bounded wait it has, and here it
 * services the supervision state machine THROUGH a long reply instead of
 * being starved by it.
 *
 * TICK-GATED, deliberately. hc_asic_start_service() is cheap when it has
 * nothing to do, but the wait loops spin far faster than once per
 * millisecond and its work is paced in whole milliseconds anyway. One call per
 * tick keeps the worst-case service gap at about 1 ms - a tenth of the budget
 * - without making every transmitted byte pay for a state machine.
 *
 * WHAT IT DOES NOT DO: it does not transmit, it does not poll the receiver,
 * and it does not touch the calibration page. hc_asic_start_service() does at
 * most one state transition per call and never blocks, so this cannot recurse
 * and cannot itself become the thing that misses a deadline. */
static unsigned int  yield_mark;
/* yield_armed is declared with the ADC state above: the tick reads it. */

/* THE MAIN LOOP FEEDS THE WATCHDOG ONLY WHILE THE TICK IS ALIVE.
 * The tick ISR carries the runtime supervisor (hc_rt_supervise: is the CC25
 * executor running?). A main loop that fed the watchdog unconditionally would
 * keep a board alive whose tick - and with it that supervisor - had died. The
 * judge is T0, a CAPCOM1 timer, so a dead CAPCOM2 unit (T7/T8/CC25) cannot
 * hide itself: 50 ms without a tick and the 200 ms watchdog is left to bite. */
static unsigned int wdt_tick, wdt_t0;
/* Wall time of one main-loop service, interrupts included - what the rest
   of the loop waits for (hcrtmon711.h svc_*). */
static unsigned int svc_t, pass_t;
/* DBW IS POLLED AT EVERY SERVICE BOUNDARY. Called once per pass
   its 5 ms raster stretched to the pass: median 8.4, p95 24.5, max 28 ms at
   9600 rpm with TunerStudio polling at 115200 (simulator) - and the PID's I
   and D are per step, so its effective gains moved with engine load. With a
   due-check after every timed service (cheap: one compare when not due) the
   step interval is bounded by the longest single background stretch.
   docs/ARCHITECTURE.md, DBW cadence. */
static void wdt_main(void);
static void service_boundary(void);
static void dbw_poll(void)
{
    wdt_main();
    if (hc_dbw_due(tick_ms)) {
        hc_dbw_service(tick_ms, trg_rpm,
                       (unsigned char)(hc_dbw_allowed != 0u
                                       && hcb_state != HCB_RUNNING));
    }
}
#define SVC_BEGIN()   (svc_t = T7)
#define SVC_END(f)    do { HC_RT_MAX(f, (unsigned int)(T7 - svc_t)); service_boundary(); } while (0)
static void wdt_main(void)
{
    if (tick_ms != wdt_tick) {
        wdt_tick = tick_ms;
        wdt_t0 = T0;
    } else if ((unsigned int)(T0 - wdt_t0) > (unsigned int)US_TO_TICKS(50000u)) {
        return;
    }
    hc_srvwdt();
}

/* One bounded boundary shared by timed services; parser work stays outside
   the generic page-work yield. */
static void service_boundary(void)
{
    dbw_poll();
    wdt_main();
    hc_serial_boundary();
}

/* ARMED ONLY AFTER hc_asic_start_init(), AND THAT IS NOT A DETAIL.
 *
 * The boot path calls update_live() BEFORE hc_asic_start_init() runs, and it
 * reaches this function through put16() and hcts_tx() (put16() only touches
 * RAM, but hcts_target_yield() runs from inside hcts_tx() too, called by
 * whatever DOES transmit early in boot). V23 removed the two functions that
 * used to run here as well (reset_report(), banner() - see their old
 * definition site), but the guard below is unrelated to what transmits and
 * stays exactly as measured. start_me711.a66 never runs Keil's
 * ?C_INIT, so until hc_asic_start_init() executes, hc_asic_state holds
 * WHATEVER THE RAM HELD. If that stale byte happened to be
 * HC_ASIC_ST_SSC_INIT, an unguarded yield would call asic_init() - bringing
 * the SSC up before hc_asicdump_salvage() and hc_power_hold_assert().
 *
 * That is precisely the ordering the V12 salvage fix exists to protect (see
 * the comment at the salvage call site) and precisely the "do not reorder the
 * platform bring-up" rule this target has held since V17. The boot sequence
 * is therefore byte-for-byte V19's until the state machine owns itself. */
void hcts_target_yield(void)
{
    if (!yield_armed) {
        return;
    }
    /* Engine planning is its own interrupt level (TGT_TRAP_PLAN), requested
       by the crank ISR; nothing here plans or executes engine events. */
    if (tick_ms == yield_mark) {
        return;
    }
    yield_mark = tick_ms;
    /* the next knock window is armed from here too (a long serial
       reply would otherwise skip windows); it never converts - KI is a
       request the tick's adc_service() serves. */
    hc_knock_arm();
    /* V52. THE WATCHDOG IS THE OTHER DEADLINE, AND THIS PRIMITIVE OWNED ONLY
     * ONE OF THEM.
     *
     * This function exists so that a long operation can hold the main loop
     * without starving the platform.  It kept the 10 ms S5500 raster alive -
     * the tighter deadline, and the one behind every reset this project had
     * seen - and did nothing at all for the C167's own watchdog.  That period
     * is TGT_WDTCON_SERVICE = 0x0B01 at 40 MHz: WDTIN = 1 so the prescaler is
     * /128, SRVWDT restarts the counter at WDTREL << 8 = 0x0B00, and 62720
     * counts of fCPU/128 is 200.7 ms [C167CR UM V3.1 13.1].
     *
     * AND THE ONLY RUNTIME SERVICE WAS AT THE TOP OF THE MAIN LOOP.  The whole
     * image holds eight SRVWDT opcodes - five in start_me711.a66, one in
     * hc_srvwdt(), two inline in hcnvm.c's SRAM-resident programmer, a census
     * validate_me711_image pins by name - so ANY SINGLE main-loop iteration
     * longer than 200.7 ms resets the ECU, and eleven call sites hold the loop
     * behind this yield alone: crc_block(), cell_blank()'s outer chunk loop,
     * nvm_select()'s 4096-byte page copy, cfg_sum(), and hcts.c's long-reply
     * transmit paths.
     *
     * V51 WAS FLASHED AND IT IS WHAT PROVED THIS.  Its Burn committed
     * perfectly - 2060 of 2060 words, zero retries, the record complete in
     * cell 0 ending in DONE, and the rebooted ECU selected it with
     * idlePad = 0x02 - and then the ECU reset with rstRawReset = 0x0006 =
     * SWR | WDTR, which UM Table 13-2 gives exactly one event for: a watchdog
     * timer reset.  No NMI (LF_NMI_STARTED 0, and 0x0006 carries neither LHWR
     * nor SHWR), no trap, not the S5500.  See
     * the maintainer's design records.
     *
     * THE CODEBASE ALREADY KNEW THE TWO BELONG TOGETHER: hcts_stall() and
     * adc_service() both write `hc_srvwdt(); hcts_target_yield();`.  Folding
     * the service in here makes that pairing unconditional instead of
     * remembered, and costs one SFR write plus SRVWDT at most once a
     * millisecond.
     *
     * IT STAYS BEHIND THE TICK GATE, DELIBERATELY.  If the millisecond tick
     * ever dies the yield stops servicing and the watchdog resets the ECU,
     * which is the correct fail-safe and is exactly the V49 fault this project
     * spent weeks on.  Servicing unconditionally here would MASK a frozen
     * tick, and a watchdog that cannot fire is not a watchdog. */
    hc_srvwdt();
    hc_asic_start_service(tick_ms);
    /* a DUE bench pulse ends here too, so a TunerStudio reply cannot
       stretch it (measured 605 ms for 500 on V76). Only the end - see
       hcbench_yield_service(). */
    hcbench_yield_service(tick_ms);
    /* The rev-limit decision and the fuel-cut release, once a millisecond. */
    hc_drysched_overdwell_service(T1);
    /* AND THE SNAPSHOT, IN THE SAME BREATH. hc_hal_ain_service() captures the
       S5500 correlation window on the EDGE of hc_asic_run_ok, and the reply
       only survives in the in-place exchange buffer until the next build()
       zeroes it. During a TunerStudio reply the main loop is inside
       hcts_tx(), so it is these yields - not the loop - that advance the
       exchange: without this call a window sample could be taken one whole
       10 ms period late and read the frame we are TRANSMITTING instead of the
       one we received. That matters precisely because the correlation is done
       with TunerStudio connected. It is cheap: 16 far reads, and only when
       the counter actually moved. */
    hc_hal_ain_service();
    wdt_main();
    /* The main loop's own predicate: disarmed while a bench test runs. Not
       through dbw_poll(): one call level less on the deepest stack chain. */
    hc_dbw_service(tick_ms, trg_rpm,
                   (unsigned char)(hc_dbw_allowed != 0u && hcb_state != HCB_RUNNING));
}

/* --------------------------------------------- the board-specific command --
 * The '!' command. This board has no throttle to calibrate and no flash burn
 * yet, so the only actions are diagnostics.  */
/* ---------------------------------------------- the configuration store --
 *
 * THIS is where the desired/active split becomes real on this board. hcts.c
 * no longer touches hcconfig's page directly; it asks the target, and the
 * target hands it hc_config_manager.
 *
 * What changes for a tuner, in one sentence each:
 *
 *   a page READ returns DESIRED, so what comes back is what was typed, even
 *   while the engine is still running the previous value;
 *
 *   a page WRITE is classified by the generated slot table - a calibration
 *   byte goes straight through to the active page as it always did, a routing
 *   or geometry byte is staged until RPM is zero, and a restart-required byte
 *   is stored and NOT applied at all;
 *
 *   a BURN validates DESIRED first and refuses to store a configuration that
 *   does not describe a runnable engine.
 *
 * The 'W' path is one hc_cfg_slot_at() binary search per byte - at most nine
 * iterations over 207 slots - which is nothing beside the 520 us it takes to
 * receive the byte at 19200 baud. It deliberately does NOT validate per byte:
 * a 16-bit value arrives as two writes and the page is meaningless between
 * them, which is exactly the settling problem the main loop already solves
 * below with cfg_settle_t.
 */
unsigned char hcts_cfg_read(unsigned int off)
{
    return hc_cfg_mgr_read_u8(off);
}

void hcts_cfg_write(unsigned int off, unsigned char v)
{
    hc_cfg_mgr_write_u8(off, v);
    /* "the page has been edited since the last burn" - one comparison and a
       byte, so it can afford to be on the per-byte path. It is what puts the
       NOT BURNED light on in TunerStudio. */
    hc_nvm_mark_dirty();
}

/* A BURN IS A REQUEST, NOT AN ERASE.
 *
 * It validates DESIRED, commits it to the standby page exactly as it always
 * did, and then SNAPSHOTS the whole record into the staging buffer. Nothing is
 * erased and nothing is programmed here, so this cannot stop an engine and
 * cannot make TunerStudio wait on a flash device. The physical commit happens
 * later, from hc_nvm_service(), and only when the engine is stopped.
 *
 * The snapshot is what makes the semantics unambiguous: burn A, then edit to
 * B without burning, and it is A that becomes permanent. */
unsigned char hcts_cfg_burn(void)
{
    if (hc_nvm_request() == HCNV_ERR_NONE) {
        /* The shared protocol holds Burn's TS_OK until DONE has been read
           back, the NOR is explicitly in read-array mode, and this runtime
           can accept the following request without a signature reconnect. */
        hcts_defer_response();
        return TS_OK;                      /* not used - the reply is held */
    }
    /* The ONLY way hc_nvm_request() declines is hc_ram_bad: the external SRAM
       that holds the staging buffer failed its probe, so there is nowhere to
       build a record. Nothing is staged and nothing is deferred.

       The code is TS_REFUSED, which is TS_OK - TunerStudio ends the session on
       every response code with bit 7 set, so a refusal cannot be spelled in
       one (hcts.h). `nvmError` low byte reads HCNV_ERR_RAM and `ramBad` is
       non-zero, and those are what say this ECU cannot store a calibration at
       all. */
    return TS_REFUSED;
}

/* ============================================ V86: ENGINE PRESET APPLY ====
 *
 * THE MISSING HALF OF THE PRESET SYSTEM. Until V86 hc_preset_apply_engine()
 * was linked into the image and called by nothing: selecting a preset in
 * TunerStudio wrote the one enginePreset byte and populated no other field.
 *
 * OCH words 764..775 belong to this path alone (the '!G' pattern - no near
 * RAM, update_live() never rewrites them):
 *   764  verdict (low byte, PRESET_V_*) | preset id asked (high byte)
 *   766  hc_validate() mask of the last attempt (0 = clean)
 *   768  first refused page offset of the last attempt (0 = none)
 *   770  1 while TunerStudio should RE-READ the page (after an apply) -
 *        [EventTriggers] triggeredPageRefresh in the .ini, rusEFI's
 *        triggerPageRefreshFlag
 *   772  pending request: 0x0100 | id, or 0
 *   774  tick_ms of the last successful apply
 *
 * PRECONDITIONS, each refusal named: engine stopped (rpm 0 AND no crank
 * edges), no bench output test running. The preset itself is ONE transaction
 * (hc_cfg_mgr_txn_*): the whole resulting page is validated, a refusal
 * changes nothing, and nothing is ever burned - Burn stays the tuner's. */
/* ------------------------------------------------------------- the banner -
 * Sent once at boot and then repeated once a second until something talks to
 * us. §49: the proof must not be a single burst two milliseconds after
 * power-up that the user's terminal was not open for yet.
 *
 * Everything in it is readable with a dumb terminal, because the first bench
 * test must not depend on TunerStudio being configured correctly to tell the
 * user whether the ECU is alive. */
/* THE FIVE TARGET WORDS of the persistent reset log.
 *
 * hcconfig owns the log; what a board records in its own words is the board's
 * business. On this ECU they are the ASIC link's state, because the ASIC is
 * the only thing on this board that can reset the CPU other than the watchdog
 * - its P1H.3 is SWRST_SM, "Abschaltung SG-Rechner". RESETDIAG_V1 keeps the
 * link isolated, so these should all stay at zero: if they do not, something
 * touched the SSC that this build believes it never enables. */
static void rst_publish(void)
{
    unsigned int t[RST_TGT_WORDS];

    /* Five words survive a reset, and after four experiments that answered
       "still resets" and nothing else, these are the five worth having:
       how far the handshake got, whether the ASIC ever answered at all, and
       when. [PART V of the brief.] */
    /* Five words survive a reset. After V4 these are the five that decide
       whether the TRANSPORT worked, because that is the question a reset
       otherwise erases. */
    t[0] = (unsigned int)((hc_asic_state & 0x00FFu)
                          | ((hc_asic_reinits & 0xFFu) << 8));
    t[1] = (unsigned int)((hc_asic_start_tx & 0x00FFu)
                          | ((hc_asic_start_rx & 0xFFu) << 8));
    t[2] = (unsigned int)((hc_ssc_rx_vec & 0x00FFu)
                          | ((hc_ssc_err_vec & 0xFFu) << 8));
    t[3] = (unsigned int)((hc_asic_pec_tx_end & 0x00FFu)
                          | ((hc_asic_pec_rx_end & 0xFFu) << 8));
    t[4] = hc_asic_reply_w0;
    hc_rst_progress(tick_ms, loop_count, hc_firstvec, hc_lastvec,
                    hc_wdt_services, t);
}

/* reset_report(), banner() and step_line() are REMOVED, not merely
 * uncalled - real-hardware K-line tracing over a genuine KKL cable (no
 * host-side echo cancellation) showed "HCRST B=...", "HC711 RELAYV22 CAL=..."
 * and "HCSTEP ST=..." going out UNSOLICITED, immediately after reset, with no
 * TunerStudio request behind them. TunerStudio's own detection retry (~4 s)
 * has to compete with that traffic, and this build's whole point is that
 * K-line carries ZERO bytes from reset until the host asks for something. See
 * tools/me711_idle_silence_proof.py, which now checks the FULL boot window,
 * not just the post-boot idle window.
 *
 * The persistent, battery-backed side of this diagnosis (hc_rst_progress(),
 * hc_rst_stage(), hc_rst_marker() - all RAM/SRAM writes, never K-line) is
 * UNCHANGED and still runs from rst_publish()/stage(): a bench post-mortem is
 * still readable through the '!' command or a future dump, just not pushed
 * onto the wire on every boot uninvited.
 */

/* THE LINE THE WHOLE TEST TURNS ON, and WD= is the number that settles it.
 *
 * WDT (SFR 0xFEAE) is the watchdog's own live 16-bit count, and it is readable.
 * That turns "is SRVWDT actually working?" into a MEASUREMENT rather than an
 * argument, which is the only way this project has ever settled anything:
 *
 *   WD= near 0x0B00 and roughly steady   the service WORKS. SRVWDT reloads the
 *                                        high byte from WDTREL = 0x0B and the
 *                                        count only climbs between services.
 *   WD= climbing towards 0xFFFF          the service does NOT work, whatever
 *                                        the reason, and the reset that
 *                                        follows is the watchdog's.
 *   WD= low but the ECU still resets     the watchdog is being held off and
 *                                        something ELSE resets us - on this
 *                                        board that means the ASIC, whose
 *                                        P1H.3 SWRST_SM can reset this CPU.
 *
 * WN= is WDTCON read back, so a write that did not take is visible rather than
 * assumed; it should read the same as WR=.
 */
/* The line the experiment is read from. Kept SHORT on purpose: the previous
   image spent 231 ms of a 255 ms run transmitting, which left room for only
   two samples and made serial loading a confounder in its own right. This one
   is about a third of that.
 *
 *   C=  condition: 0 silent, 1 CS pulses
 *   WD= the live watchdog counter. Steady near 0B00 = the service works.
 *   CS= what P6.4 is doing: commanded level, and pulses completed
 *   BV= interrupts nobody asked for, LV= the last one
 */
/* alive_period()/alive_line() USED TO LIVE HERE and are REMOVED, not merely
 * disabled - a function nobody calls still has to compile clean, and Keil
 * flags an unreferenced static function (C174), so "gate the call site" and
 * "delete the function" ended up the same amount of work. The reason for the
 * removal, in full, is on the (former) call site's comment in the main loop
 * below: `alive_line()` is ~35 fields / ~239 characters, and at this file's
 * own MEASURED K-line cost of ~533 us/character (see `banner()`'s comment) one
 * call is ~127 ms of pure blocking transmission - while `hc_asic_start_service()`,
 * the runtime ASIC exchange's state machine, is only ever serviced from the
 * same main loop. No count of prior successful exchanges makes starting a
 * 127 ms block safe against a 10 ms raster; the call itself cannot happen
 * while that raster is live, so it does not exist any more.
 *
 * Kept here as documentation, not code, because the field list is real bench
 * knowledge and a future NON-BLOCKING or interrupt-driven liveness line
 * (which the ASIC-supervision problem does not need) should not have to
 * re-derive it:
 *
 *   T=  tick_ms                S=  whole seconds of uptime
 *   A=  hc_asic_state           WD= the live watchdog counter (WDT); steady
 *                                    near 0x0B00 means SRVWDT is working
 *   CF= RP0H (CLKCFG, bits 7-5, latched from P0H at the last long hardware
 *       reset - the PLL factor read from silicon: 100b=x5, 000b=x2.5, 111b=x4)
 *   P6=/DP6=   the shared-SPI chip selects (P6.3 CS_EEPR, P6.4 CS_ASIC) and
 *              their direction register - both must read 1 (deselected)
 *              except while a frame is in flight
 *   TX=/RX=/OK=   startup exchanges attempted / completed / accepted
 *   V=  SSC vector counts, TX node/RX node/ERROR node - RX=0 means no block
 *       ever finished, whatever else the log says
 *   P=  PEC words still owed at completion, TX/RX - both 0 is a clean block
 *   SC= SSCCON as the last error ISR saw it / the live value
 *   RI= SSC re-init count       E=  checksum,timeout,SSC-error counts
 *   X=  measured duration of the last exchange, ms
 *   XT= transfer duration in T7 ticks (0.8 us each at T7=fCPU/32=1.25 MHz)
 *   CSD= chip-select-to-first-clock delay, T7 ticks - expect 0x004F=63.2 us;
 *        shorter clocked into a slave that had not armed yet
 *   R=  the ASIC reply's word 0     CK= our checksum / the reply's own
 *   D=  frozen-capture slots filled  RUN= hc_asic_run_ok
 *   NL=/  NLEN_FR latch/direction (an input reads the pin, an output the
 *         latch - that distinction found the net was already high in V3)
 *   L=  main-loop pass count   BV=/LV= bad-vector count / the last one
 */

/* ==================================================== interrupts, all off ==
 * The boot block ran a full bring-up before handing over and may have left
 * interrupt sources enabled. That is not theoretical: this firmware POLLS
 * S0TIC and ADBSY, and taking an interrupt clears the very request flag those
 * polls wait on. Every interrupt control register is cleared before IEN goes
 * up, and only what is enabled afterwards can fire. */
static void irq_disable_all(void)
{
    CC0IC  = 0; CC1IC  = 0; CC2IC  = 0; CC3IC  = 0;
    CC4IC  = 0; CC5IC  = 0; CC6IC  = 0; CC7IC  = 0;
    CC8IC  = 0; CC9IC  = 0; CC10IC = 0; CC11IC = 0;
    CC12IC = 0; CC13IC = 0; CC14IC = 0; CC15IC = 0;
    CC16IC = 0; CC17IC = 0; CC18IC = 0; CC19IC = 0;
    CC20IC = 0; CC21IC = 0; CC22IC = 0; CC23IC = 0;
    CC24IC = 0; CC25IC = 0; CC26IC = 0; CC27IC = 0;
    CC28IC = 0; CC29IC = 0; CC30IC = 0; CC31IC = 0;
    T0IC   = 0; T1IC   = 0; T2IC   = 0; T3IC   = 0;
    T4IC   = 0; T5IC   = 0; T6IC   = 0; T7IC   = 0;
    T8IC   = 0;
    ADCIC  = 0; ADEIC  = 0;
    S0TIC  = 0; S0RIC  = 0; S0EIC  = 0; S0TBIC = 0;
    SSCTIC = 0; SSCRIC = 0; SSCEIC = 0;
    CRIC   = 0; PWMIC  = 0;
    XP0IC  = 0; XP1IC  = 0; XP2IC  = 0; XP3IC  = 0;
}

static void stage(unsigned int s)
{
    boot_stage = s;
    hc_rst_stage(s);
    hc_bf_boot_stage(s);
}

/* ============================================ the non-blocking heartbeat ===
 *
 * V17 deleted alive_line() because it blocked the main loop for ~127 ms per
 * call and starved hc_asic_start_service() - the runtime ASIC exchange's own
 * state machine, serviced only from this loop - which is what let the S5500
 * reset us at ~140 ms regardless of UMKOM answer content
 * (docs/ARCHITECTURE.md). The comment where
 * alive_line() used to live reserved room for "a future NON-BLOCKING or
 * interrupt-driven liveness facility". This is it, kept to the bare minimum:
 *
 *   - two characters, "H\n", once per second;
 *   - emitted ONE byte per main-loop pass and NEVER waited on - the only
 *     hardware touch is a single S0TBUF store.
 *
 * Pacing is by T7, not by S0TIC. S0TIC bit 7 is the ASC0 transmit-interrupt
 * REQUEST LATCH, not a "buffer free" level: hardware sets it once per
 * S0TBUF->shifter transfer and hcts_tx() clears it (S0TIC &= 0x7F) at the end
 * of every call, so after the boot banner it stays 0 and never re-asserts on
 * its own. V18 gated the emit on `S0TIC & 0x80` and therefore never
 * transmitted a single heartbeat on hardware. This version does not touch
 * S0TIC at all - it writes S0TBUF only once after a complete serial byte time
 * has elapsed on T7 since the
 * previous heartbeat byte, so ASC0's transmit buffer AND shifter have both
 * drained and the store cannot land on a byte still in flight. hcts_tx()
 * itself never had this bug because it writes S0TBUF unconditionally and
 * waits AFTER, never before.
 *
 * It is deliberately NOT interrupt-driven. This firmware POLLS S0TIC in
 * hcts_tx()/cal_measure()/adc_service() (see irq_disable_all()'s comment),
 * and enabling the ASC0 transmit interrupt would clear the very request flag
 * those polls wait on. A one-byte-per-pass emitter in task context is the
 * safe shape here.
 *
 * It touches NOTHING the S5500 supervision depends on: no ASIC path, no SSC
 * frame builder, no hc_umkom_service, no hc_asic_start_service, and no
 * blocking transmit. tools/me711_heartbeat_gap_proof.py runs the real
 * built image in c167sim (S0TIC modelled correctly as a latched TX request)
 * and proves the worst-case hc_asic_start_service() gap stays well under the
 * 10 ms supervision budget and that "H\n" actually goes out once per second.
 *
 * It stands down the instant TunerStudio completes one CRC request
 * (rx_reqs != 0), so it can never interleave a byte into an envelope reply.
 * Its own K-line echo returns as the bytes 'H' (0x48) and '\n' (0x0A); the
 * shared parser takes each as a plain legacy command, both of which fall
 * through handle_plain()'s default and are answered with silence.
 */
/* hb_service() and its statics (HB_MSG/hb_mark/hb_byte_t7/hb_idx) are
   REMOVED, not merely disabled - an unreferenced static function is a build
   warning under this target's "if errorlevel 1 goto fail" batch, and a
   function nobody calls is exactly the kind of dead code the boot-contract
   build already refuses to carry silently. The mechanism (T7-paced,
   one-byte-per-pass, never blocking) is described in full in
   docs/ARCHITECTURE.md and in the V19 archive
   (the maintainer's hardware-session record) if it is ever
   reinstated as an interrupt-driven facility instead of unsolicited K-line
   traffic. */

/* ------------------------------------------------------------------- main */
void main(void)
{
    /* OEM ME7.1.1 boot block saves WDTCON in T0 at 0x807766 before its first
       SRVWDT. Capture it before this firmware turns T0 into a timer. */
    unsigned int reset_raw = T0;
    unsigned int mark;
    unsigned int rst_mark;

    hc_wdt_services = 0;
    hc_srvwdt();
    irq_disable_all();

    /* BEFORE ANYTHING DEEP RUNS. hc_stack_prime() writes a pattern over the
       part of the user stack nothing has reached yet, so hc_stack_used() can
       report afterwards how deep this firmware actually goes. Here rather
       than beside hc_safety_init() below: by then hc_cfg_init() and the ASIC
       start-up have already been down their own call chains, and priming
       after the deepest thing has run would erase the very evidence. */
    hc_stack_prime();
    stack_scan_ms = 0;
    och_cycle = 0u;
    hc_rt_armed = 0u;
    hc_rtmon_init();
    pass_t = T7;

    /* Nothing below starts at a known value: start_me711.a66 hands
       straight to main() and never runs Keil's ?C_INIT. */
    boot_stage = 0;
    loop_count = 0;
    frames = 0;
    tick_ms = 0;
    tick_ok = 0;
    cal_ticks = 0;
    status = 0;
    och_mark = 0;
    alive_mark = 0;
    /* The platform yield, zeroed HERE with everything else rather than later:
       nothing before hc_asic_start_init() may service the ASIC state machine,
       and this startup runs no ?C_INIT, so a stale non-zero yield_armed would
       be armed from the very first instruction. cal_measure() and
       hcts_rx_learn() happen to write S0TBUF directly rather than through
       hcts_tx(), so they cannot reach the yield - but relying on that is
       exactly the kind of implicit ordering this project has been bitten by. */
    yield_mark = 0;
    yield_armed = 0;
    hc_adc_ctl = 0;
    hc_badvec = 0;
    hc_firstvec = 0;
    hc_lastvec = 0;
    for (mark = 0; mark < TGT_ADC_CH_COUNT; mark++) {
        adc_raw[mark] = 0;
    }

    stage(BOOT_ENTRY);
    hc_rst_reset_raw(reset_raw);
    /* This is after RESETDIAG has frozen the preceding run, but before ASC,
       configuration, NVM and HCTS can clear any volatile transaction state. */
    hc_bf_boot_early(reset_raw);
    /* V49 freezes the preceding first-event record before configuration, NVM
       recovery or runtime traffic can overwrite the evidence it describes. */
    hc_lf_boot_early(reset_raw, hc_rst_get(RST_BOOTS));
    /* and one record in the boot history, with KL15 as this boot sees
       it (P6.2 is an input from reset) - the key-off reset storm's trail. */
    hc_io_boothist_boot(hc_rst_get(RST_BOOTS), reset_raw,
                        hc_rst_get(RST_PREV_MS), hc_rst_get(RST_PREV_STAGE),
                        (unsigned char)((P6 & (1u << TGT_KL15STAT_PORT_BIT))
                                        != 0u));
    stage(BOOT_RAM);
    stage(BOOT_WDT);

    /* --- the timers, before anything that measures time ------------------
       T7 is the microsecond timebase every bounded wait in this firmware uses,
       T8 is the 1 ms tick, T0 is CAPCOM1's timebase for the serial drain. All
       three on the same prescaler, so US_TO_TICKS() means the same thing on
       all of them - the ME7.5 target relies on exactly that identity and it is
       worth keeping true rather than clever. */
    T78CON = TGT_T78CON;
    T01CON = TGT_T01CON;
    T7 = 0;
    /* V50 F1: T8REL is the hardware reload the CAPCOM unit applies on every
       overflow, so hc_tick_isr() no longer has to - and a lost tick costs 1 ms
       instead of a full 51.4 ms period. T8 gets the same value so the FIRST
       period is 1 ms too; every period after that comes from T8REL. */
    T8REL = (unsigned int)(0u - TGT_TICK_RELOAD);
    T8 = (unsigned int)(0u - TGT_TICK_RELOAD);
    T0 = 0;
    T1 = 0;

    /* --- ASC0 and the shared TunerStudio server ------------------------- */
    TXD0_LATCH = 1;
    TXD0_DIR   = 1;
    RXD0_DIR   = 0;
    hcts_init();
    /* RESETDIAG_V1 wants the free-running text: the whole point is that a
       terminal sees progress before the ~420 ms reset arrives. The shared core
       clears this flag on the first byte received, so it stops the moment a
       tool connects. */
    hc_trace_on = 1;
    stage(BOOT_SERIAL);

    /* --- the calibration page ------------------------------------------
       hc_cfg_init() probes the external SRAM and decides whether the live page
       comes from there or from compiled-in defaults, and publishes hc_ram_bad
       either way. On this board nothing had ever read or written that SRAM
       before, so the probe result is itself a bench finding. */
    hc_cfg_init();
    /* THE NON-VOLATILE STORE, and it has to be HERE - after hc_cfg_init() has
       decided what the standby SRAM is worth, and BEFORE hc_cfg_mgr_init()
       takes the DESIRED copy, because on a cold ECU this is what puts the
       burned calibration into the page the manager is about to copy.
     *
     * V40 MOVED THE COMMIT OUT OF HERE AND THIS IS NOW THE RECOVERY PATH ONLY.
     * An ordinary Burn programs live, in bounded chunks, from
     * hc_nvm_service() in the main loop below, and RETURNS AN ACKNOWLEDGEMENT
     * INSTEAD OF RESETTING - there is no SRST on a successful Burn and no
     * TunerStudio reconnect. What is left here is what a power cut can leave
     * behind: an intent that was armed but never began (safe to finish before
     * IEN, with no interrupt able to fetch a vector out of a busy device), a
     * cell that is already a complete verified record, or a partially
     * programmed cell - which is CONSUMED, never resumed, because NOR clears
     * bits only and the old record is still the one that boots.
     * Read hcnvm.h before touching any of it. */
    hc_nvm_boot();
    /* IMMEDIATELY after, and before anything reads the page: migrate the
       universal block if this ECU's stored page predates it, then take the
       DESIRED copy. Every page access from here on - including every one
       TunerStudio makes - goes through the manager. */
    /* THE LAST-KNOWN-GOOD WALK-BACK, between the two of them deliberately.
       hc_nvm_boot() above has restored the newest record that survives its
       CRC; this asks whether it can actually RUN, and steps back through
       older generations until one can. hc_cfg_mgr_init() below still applies
       the board-default floor when nothing does, so the failure path is
       unchanged and this only improves what it finds. */
    hc_nvm_lkg_walkback();

    hc_cfg_mgr_init();
    /* THE PRESET WORDS START AT ZERO, EVERY BOOT. They live in
       battery-backed SRAM and nothing else writes them, so without this a
       power-up read whatever the SRAM held - MEASURED on the bench ECU:
       presetResult 0xFF03 before any press - and 772, the PENDING REQUEST,
       could apply a preset nobody asked for (random content after a battery
       loss, or a request cut off by a reset). Direct stores: the serial pump
       inside put16() has no business running this early. */
    {
        unsigned int k;
        for (k = 764u; k < 776u; k++) {
            OCHP[k] = 0u;
        }
        /* and the grab words. The first AWT capture read grabResult
           0xDFFE at key-on - SRAM content, not a verdict. */
        for (k = 450u; k < 454u; k++) {
            OCHP[k] = 0u;
        }
    }
    stage(BOOT_CONFIG);
    cfg_fault_cache = hc_cfg_faults();
    cfg_fault_gen = 0;
    cfg_settle_gen = 0;
    cfg_settle_t = 0;
    hc_cfg_stable = 1;

    /* --- measure the timer rate, then say so ---------------------------- */
    cal_measure();
    stage(BOOT_TIMERS);

    /* --- the HaniCore runtime layer -------------------------------------
       AFTER the calibration page exists (eng_init() reads CAL_BARO_DEFAULT
       from it) and BEFORE interrupts go up. hc_hal_init() is first because it
       owns the output census every other module may write to, and NONE of
       these three may assume a zeroed global: this startup never runs Keil's
       ?C_INIT. */
    hc_hal_init();
    hc_main_relay_init();
    trg_init();
    hc_safety_init();
    /* AFTER hc_hal_init(), which is what puts the outputs in their safe state,
       and BEFORE anything can accept a '!T'. hcbench_init() deliberately
       drives nothing: the power-on state of every pin belongs to the startup,
       and this module must have no opinion about pins it was not asked to
       touch. */
    hcbench_init();
    hc_fuelpump_init();
    hc_dbw_init();
    /* Seeded from the HAL's own default so the first pass is not a
       spurious 'the page changed' - hc_hal_init() has already chosen
       S5500_BASE_DEFAULT and the page has not been edited yet. */
    s5500_page_last = hc_s5500_base;
    eng_init();

    /* --- which trap carries the receive interrupt, if any ---------------
       On this ECU family the answer is expected to be NONE: the first-level
       vector for S0RINT jumps into the boot block, which owns the ASC0
       receive interrupt for its flash loader. See hctarget.h. The probe runs
       anyway, because it also finds and verifies the CAPCOM drain tick that
       replaces it, and because being wrong about this costs nothing. */
    hcts_rx_learn();
    stage(BOOT_PROBE);

    update_live();
    /* reset_report(reset_raw)/banner() are NOT called any more - see the
       comment where they used to be defined. stage() still records the
       transition in the (silent) battery-backed reset log. */
    stage(BOOT_BANNER);

    /* --- interrupts, in a deliberate order -------------------------------
       Vector table valid, stack valid, default handler valid, every handler
       compiled in, every dangerous output already off and left off by the
       startup. Only now. */
    hc_rst_marker(DIAG_BEFORE_IEN);
    T8IC = HC_IC(TGT_ILVL_TICK, 0);
    hcts_rx_arm();
    IEN = 1;
    hc_rst_marker(DIAG_AFTER_IEN);
    stage(BOOT_IRQ);

    /* Did the tick actually move? Bounded in TIME, and two milliseconds is
       generous. If it did not, the image still runs and still answers - it
       just says so, which is the whole point of a self-diagnosing image. */
    mark = T7;
    while ((tick_ms < 2u)
           && (unsigned int)(T7 - mark) < (unsigned int)US_TO_TICKS(5000u)) {
        hc_srvwdt();
    }
    tick_ok = (unsigned int)(tick_ms >= 2u);

    /* The former clean image sent a made-up runtime-style frame in place of
       OEM's distinct 96-word startup payload. This experiment sends no frame:
       it leaves CS and all SSC pins as inputs, separating external-monitor
       supervision from internal watchdog behaviour without output risk. */
    hc_rst_marker(DIAG_BEFORE_ASIC);
    /* Always isolate first: the SSC stays disabled and every SSC pin an input
       in BOTH halves. The only difference the experiment allows itself is the
       chip-select line. */
    /* THE ASIC LINK IS NOW LIVE. Every previous image called asic_isolate()
       here and left the SSC compiled out; V4 brings the transport up and runs
       the OEM's own startup handshake. NLEN_FR is asserted too - not because
       V3 showed it matters (it did not) but because the OEM does it in port
       init before EINIT, and correct platform state is worth keeping once it
       costs nothing. */
    hc_asicdump_init();
    /* salvage BEFORE hc_power_hold_assert()/hc_asic_start_init() can run.
       hc_power_hold_assert() only ever touches P3.12 (see hcpower.c) but
       hc_asic_start_init() zeroes every hc_asic_* counter this reads, and
       nothing before this line has touched FRAME or those counters this
       boot: the zero-list above stops at adc_raw[], irq_disable_all() only
       clears interrupt-control SFRs, and start_me711.a66 has no bulk
       RAM clear of any kind. See docs/ARCHITECTURE.md. */
    hc_asicdump_salvage(reset_raw);
    hc_power_hold_assert();
    hc_io_init();          /* ASIC images at the OEM idle values, run-on idle */
    hc_boost_init();       /* boost core idle, no cut */
    hc_idle_init();        /* idle floor 0 until a step */
    hc_knock_init();       /* CC195 lines released, OCH2 cleared */
    hc_vvt_init();         /* cam solenoid units stopped (after OCH2) */
    hc_trans_init();       /* dry wall film, no after-start */
    hc_dtc_init();         /* no codes, MIL off */
    hc_limp_init();        /* no protection cut */
    hc_kwp_init();         /* KWP core idle, 5-baud decoder qualifying */
    hc_asic_start_init();
    /* The ASIC state machine now owns its own state, so the serial waits may
       start servicing it. NOT ONE LINE EARLIER - see hcts_target_yield(). */
    yield_armed = 1;
    /* ONE chunk of the frozen ASIC reply per boot. The ECU resets every
       ~310 ms on its own, so ~4 seconds of that yields both complete 96-word
       frames in order. Printed EARLY, before the liveness lines, so a chunk is
       never lost to the deadline. */
    /* hc_asicdump_print() is NOT called any more - it transmitted
       unsolicited "HCE/HCDM/HCD/HCPM ..." lines on the real K-line with no
       host request behind them (same real-hardware trace that found
       reset_report()/banner()/step_line() doing the same thing - see the
       comment where those used to be defined). The salvage it would have
       printed is still captured by hc_asicdump_salvage() above and still
       sits in battery-backed SRAM; only the automatic K-line dump is gone. */
    hc_rst_marker(DIAG_ASIC_ISOLATED);
    hc_rst_cond((unsigned int)hc_asic_state);
    stage(BOOT_ASIC);

    stage(BOOT_LOOP);
    hc_rst_marker(DIAG_MAIN_LOOP);
    wdt_tick = tick_ms; wdt_t0 = T0;
    hc_rt_armed = 1u;    /* the executor, the tick and the stacks are up */
    pass_t = T7;         /* pass_max measures loop passes, not the boot */
    och_mark = tick_ms;
    alive_mark = tick_ms;
    rst_mark = tick_ms;
    rst_publish();

    for (;;) {
        wdt_main();
        HC_RT_MAX(pass_max, (unsigned int)(T7 - pass_t));
        pass_t = T7;

        /* hb_service() is NOT called any more. The unsolicited "H\n"
           bench heartbeat it emitted once per second (added in HEARTBEAT_V19)
           was hitting TunerStudio's serial listener as unrequested traffic
           ("Invalid data received from controller") on a genuine KKL cable
           with no host-side echo to absorb it. K-line must be silent while
           idle; hb_service() itself is left defined, unused, for possible
           interrupt-driven reinstatement later, but must not be called from
           the main loop. See tools/me711_idle_silence_proof.py. */

        if (hc_stall_req) {
            unsigned int ms = hc_stall_req;

            hc_stall_req = 0;
            hcts_stall(ms);
        }

        SVC_BEGIN();
        hcts_poll();
        hcts_service();
        SVC_END(svc_comms);
        /* the 5-baud decoder and the KWP session (P3.11 = RXD0) */
        hc_kwp_service(tick_ms, (unsigned char)((P3 & 0x0800u) ? 1u : 0u));

        hc_knock_service(tick_ms);  /* V97; KI via the tick (hc_ki_req) */
        wdt_main();

        asic_service();

        hcts_poll();
        loop_count++;

        /* Battery-backed breadcrumbs every 10 ms. A reset need not wait for
           a serial line to finish before it becomes diagnosable. */
        if ((unsigned int)(tick_ms - rst_mark) >= 10u) {
            rst_mark = tick_ms;
            rst_publish();
        }

        /* The page is only acted on once it has stopped moving. TunerStudio
           writes a 16-bit value as two separate one-byte writes, and between
           them the page holds half of the old value and half of the new one -
           MEASURED on the other target, where 7200 rpm on its way to 0 read as
           32 rpm in between. */
        {
            unsigned int gen = (unsigned int)(cfg_writes + cfg_burns);

            if (gen != cfg_fault_gen) {
                if (gen != cfg_settle_gen) {
                    cfg_settle_gen = gen;
                    cfg_settle_t = T7;
                    hc_cfg_stable = 0;
                } else if ((unsigned int)(T7 - cfg_settle_t)
                           > (unsigned int)US_TO_TICKS(20000u)) {
                    cfg_fault_gen = gen;
                    hc_cfg_stable = 1;
                    cfg_fault_cache = hc_cfg_faults();
                }
            }
        }

        /* Telemetry on a 40 ms raster off the 1 ms tick, and RESETDIAG's
           liveness line every 100 ms until somebody talks to us. hc_trace_on is
           cleared by the shared core the moment a byte arrives, so connecting
           TunerStudio silences the text without a command. */
        /* One state transition per pass, in task context. */
        hc_asic_start_service(tick_ms);
        hc_serial_boundary();

        /* --- THE HANICORE RUNTIME --------------------------------------
         * Placed immediately AFTER the supervision service, in this order,
         * for a reason each:
         *
         *   hc_hal_ain_service()  snapshots the S5500 correlation window on
         *       the edge of hc_asic_run_ok, so it runs in the same pass the
         *       counter advanced - well inside the ~10 ms the reply stays in
         *       the in-place exchange buffer before the next build() zeroes
         *       it.
         *   trg_service()         performs task-context RPM, stall, cam
         *       absence and counting-only scheduler work.
         *   eng_service()         counts to degrees, kPa, load, injection
         *       time, advance and dwell. Main-loop arithmetic with no
         *       blocking wait and no transmission: one map lookup and a
         *       handful of curves, exactly as its own header promises.
         *
         * None of the three transmits, waits on hardware, or disables an
         * interrupt, so none of them can become the next starvation defect.
         * tools/me711_ts_gap_proof.py measures that rather than asserting
         * it. */
        hc_hal_ain_service();
        dbw_poll();
        wdt_main();
        hc_serial_boundary();
        trg_service();
        hc_tl_service(tick_ms);              /* tooth profile test */
        hc_drysched_overdwell_service(T1);   /* max dwell, 1 ms gated */
        SVC_BEGIN();
        eng_acquire();
        SVC_END(svc_eng);
        SVC_BEGIN();
        eng_calculate();
        SVC_END(svc_eng);
        /* YIELD POINTS INSIDE THE PASS. The V97 services (idle, limp,
           DTC, boost, both wideband banks) made one main-loop pass up to
           8.6 ms between two S5500 services - over the 6.5 ms share of the
           10 ms raster (me711_preset_gap_proof; V96 5.8 ms). The fix is the
           project's one primitive for long work, not a slower service:
           hcts_target_yield() is tick-gated, so it services the S5500, the
           watchdog and the bench only when a millisecond has passed, and is
           two compares otherwise. Profiled on c167sim: eng_service 1.8 ms,
           the V97 block ~1.3 ms, hc_boost_service 0.8 ms of it. */
        hcts_target_yield();

        /* The RPM-zero transaction.
         *
         * Placed AFTER trg_service(), because trg_rpm is what it gates on and
         * a stale speed would either apply a routing change under a turning
         * engine or refuse one under a stopped engine. Costs nothing at all
         * when hc_cfg_dirty_groups is zero, which is every pass except the
         * ones just after a tuner edited a routing field.
         *
         * It does not transmit, does not wait on hardware and holds interrupts
         * off only across one field - see hc_config_manager.c. So it cannot
         * become the next starvation defect, and me711_ts_gap_proof.py
         * measures that rather than taking my word for it. */
        SVC_BEGIN();
        hc_cfg_mgr_service(trg_rpm);
        hc_preset_cmd_service_cold();  /* staged preset/calibration work */
        hc_route_service();   /* no-op unless the configuration moved */
        SVC_END(svc_other);
        /* Not inside a measured stretch: the yield runs its own DBW step and
           watchdog service (and the S5500 start service the 10 ms raster needs). */
        hcts_target_yield();          /* a re-route is 1.2-1.7 ms (APPLY) */
        SVC_BEGIN();
        /* THE BENCH OUTPUT QUALIFIER, and it is the only thing in this image
           that can drive an engine output at all. Placed AFTER trg_service()
           for the same reason hc_cfg_mgr_service() is: it gates on trg_rpm
           and trg_state, and a stale speed would let a pulse start under a
           turning engine. It does nothing whatever unless a '!T' arrived, and
           it re-checks every invariant on every pass - see hcbench.h. */
        hcbench_service(tick_ms);

        /* The deferred DESIRED copy, one bounded chunk per pass, and ONLY once
           the ASIC startup handshake has reached its runtime state. Measured:
           running it before that - in init, or a chunk at a time - costs
           me711_boot_test six checks, because each chunk is a main-loop pass
           that does not poll the serial port or service the exchange. The
           supervision link comes up first. */
        if (hc_asic_state >= HC_ASIC_ST_RUNTIME_TX) {
            (void)hc_cfg_mgr_seed_step();
        }
        SVC_END(svc_other);
        /* THE CONTROLLED KEY-OFF. KL15 is the CJ910's own ST/IGN line
           (P6.2). With the native main relay routed (bound = 2) the far
           module asserts run-on the pass KL15 drops, and until it releases
           it the key-off is an INHIBIT: key_on goes false below, which
           is the one lever every output class already obeys - spark, fuel,
           pump, throttle. A Burn or an erase in flight holds the release. */
        io_ro = hc_io_runon_service(tick_ms,
                    (unsigned char)((P6 & (1u << TGT_KL15STAT_PORT_BIT)) != 0u),
                    (unsigned char)(hc_hal_main_relay_bound() == 2u),
                    (unsigned char)(hc_nvm_word_owned()
                                    || hc_nvm_phase() != HCNV_PH_NONE
                                    || ((1u << hc_nvm_state())
                                        & ((1u << HCNV_ST_PENDING)
                                           | (1u << HCNV_ST_ARMED)
                                           | (1u << HCNV_ST_COMMITTING)
                                           | (1u << HCNV_ST_STAGING)))),
                    hc_cal_u16(CFG_U_MAIN_RELAY_HOLD_MS),
                    eng_batt_dv);
        hc_safety_service((unsigned int)hc_asic_healthy(),
                          (unsigned int)(cfg_fault_cache == 0),
                          (unsigned int)(trg_state >= TRG_SYNC_CRANK),
                          (unsigned int)(trg_state >= TRG_SYNC_FULL),
                          /* KEY-ON, NOT A USER ARM. CFG_OUTPUTS_ARMED
                             is a retired page byte and no longer gates any
                             output - see hcsafety.h. */
                          (unsigned int)(!(io_ro & HC_RO_F_KEYOFF)));
        /* THE LOGICAL MAIN RELAY. Mode, cavity, grace and hold are the
           page's (TunerStudio: Main relay mode / Main relay pin / release
           delay); the default is OFF and unassigned, so nothing moves until
           a tuner routes and selects it.

           run_request IS 1 AND THAT IS A MEASURED FACT, NOT A GUESS. Until
           V75 it was 0 - "no proven ignition input" - which made AUTO a mode
           that could never request anything. But on this board the CPU runs
           ONLY while KL15 is on: KL15 is CJ910 EIN, removing +12 V from
           cavity 21 takes the ECU offline (PHYSICAL EXACT, the project rules),
           and run-on is asserted ONLY when MAIN_RELAY is the native stage
           (bound = 2) - which the CJ910 switches itself, so nothing here
           drives it (V80, measured with P6.2 LOW under run-on). For a CPU-
           driven relay (bound = 1) NLEN_FR stays vetoed and the CPU dies at
           key-off. "This CPU is executing" therefore IS "the ignition is on" for
           every relay this request can reach - the
           same argument hc_fuelpump_service()'s ign_on has always rested on.

           fault is the SETTLED page verdict and it LATCHES the relay off.
           The permission layer (arming, S5500 link, a valid page) is NOT a
           fault: it gates the pin inside the HAL and clears when it clears.
           Until V75 BOTH lifecycles were handed hc_safety_inhibits != 0 -
           which includes NO_CRANK and NO_CYCLE, set whenever the engine is
           not synchronised, and which hc_safety_init() seeds to 0x3F - so
           on the first pass after every boot the relay and the pump LATCHED
           FAULT and nothing short of a reset could clear it. hcsafety.h
           already said a pump and a relay take the ALWAYS set only. */
        hc_main_relay_service(tick_ms, 1u,
                              (unsigned char)(cfg_fault_cache != 0u));

        /* THE FUEL PUMP LIFECYCLE. Mode, prime time and cavity are the
           page's (TunerStudio: Fuel pump mode / Fuel pump prime / Fuel pump
           relay pin); stall is the decoder's Stall timeout. It asks
           hc_hal_out(HC_OUT_FUELPUMP, ...) and the HAL drives the routed
           cavity only while the page is VALID, the S5500 link is up and the
           key is on - see hcfuelpump.h for how the request follows that
           permission.
           fault is the same SETTLED page verdict the relay gets, above.

           ign_on IS KL15_STAT, P6.2, through the run-on service's debounced
           key-off flag. P6.2 IS A READABLE INPUT on this board - MEASURED on
           the real ECU on V80 (2026-09-25):
           it reads 1 with the rig's KL15 on and 0 after it drops, while the
           CPU keeps executing under run-on. (An older comment here called it
           CS2 and unreadable; that was never measured and it is wrong.) With
           run-on not configured, NLEN_FR stays HIGH (veto), the CJ910 removes
           VCC at key-off, and P2.12 tri-states - the pump releases either
           way. */
        hc_fuelpump_service(tick_ms,
                            (unsigned char)((io_ro & HC_RO_F_KEYOFF) ? 0u : 1u),
                            trg_rpm, trg_state,
                            (unsigned char)(cfg_fault_cache != 0u
                                            ? FP_FAULT_CFG : 0u));

        /* THE CLOSED-LOOP THROTTLE. Its permission is hc_dbw_allowed - the
           ALWAYS set: page valid, S5500 link, not keyed off, and NOT the
           crank (a throttle must hold a start position before the engine
           turns). hc_dbw.c additionally requires dbwEnable and its own
           plausibility/INIT settle. There is no user arm. A bench DBW
           run owns the bridge while it lasts. */
        /* The bridge PWM frequency follows its page field here, so a change
           takes effect and becomes visible without driving the plate. */
        hc_hal_dbw_pwm_poll();
        SVC_BEGIN();
        hc_idle_service(tick_ms);   /* the throttle floor hc_dbw uses */
        hc_vvt_service(tick_ms);    /* cam phase control */
        SVC_END(svc_other);
        SVC_BEGIN();
        hc_limp_service(tick_ms);   /* engine protection fuel cuts */
        hc_dtc_service(tick_ms);    /* trouble codes + MIL request */
        hc_cel_service(tick_ms,     /* lamp test + MIL (policy only) */
                       (unsigned char)((io_ro & HC_RO_F_KEYOFF) == 0u));
        SVC_END(svc_other);
        hcts_target_yield();          /* the services above are one
                                         stretch - me711_preset_gap_proof */
        hc_dbw_key((unsigned char)((io_ro & HC_RO_F_KEYOFF) == 0u), trg_rpm);
        SVC_BEGIN();
        hc_dbw_service(tick_ms, trg_rpm,
                       (unsigned char)(hc_dbw_allowed != 0u
                                       && hcb_state != HCB_RUNNING));
        SVC_END(svc_dbw);
        /* Background control yields retain engine interrupt priority;
           DBW and watchdog progress at the adjacent service boundaries. */

        /* WIDEBAND AND N75, both through the ASIC. Lambda source
           INTERNAL (the CJ120s) enables the chip, its heater and the LSU
           conversion; the heater runs only while the engine turns under sync
           and never during a key-off. N75 is open loop from the page's duty
           map, and ZERO without boost enabled, below its rpm/throttle floor,
           above the overboost cut, on a MAP fault or at key-off. */
        SVC_BEGIN();
        hc_io_lambda_service(tick_ms, hc_hal_ain(HC_AIN_O2_1_PRE),
                             hc_hal_ain(HC_AIN_O2_2_PRE),
                             hc_hal_asic_an(12u), hc_hal_asic_an(13u),
                             eng_batt_dv,
                             (unsigned char)(trg_rpm != 0u
                                             && trg_state >= TRG_SYNC_CRANK));
        SVC_END(svc_lambda);
        /* boost control (hcboost711.c, FCODE; the shared hcldr core):
           open or closed loop, and the overboost FUEL cut
           (ENG_CUT_BOOST), judged whether or not boost is enabled. */
        hcts_target_yield();          /* see the note above - the
                                         wideband pair step is the longest
                                         single service in this stretch  */
        wdt_main();
        hc_serial_boundary();
        io_boost_req = hc_boost_service(tick_ms,
                           (unsigned char)((io_ro & HC_RO_F_KEYOFF) != 0u));
        hc_hal_out_duty(HC_OUT_BOOST, io_boost_req);
        hc_io_test_service(tick_ms);
        hcts_target_yield();          /* see the yield after eng_service() */
        hc_serial_boundary();

        /* THE NON-VOLATILE COMMIT. It may only begin while these safety facts
           say the stopped ECU can tolerate a bounded flash-program slice.
         *
         * Placed AFTER trg_service() and after hcbench_service(), because it
         * gates on both: a stale rpm would arm a commit under a turning
         * engine, and a bench run in progress owns an output that must not be
         * taken away by a reset. Every condition has to hold, and a burn
         * requested at 6000 rpm simply stays here, staged, until they do -
         * the engine never notices and the request is never lost.
         *
         * Each pass programs only a small RAM-resident chunk and returns to
         * this loop. The deferred Burn reply is not sent until the DONE record
         * has been read back, scanned and selected live; there is no SRST or
         * TunerStudio reconnect on a successful V40 Burn. Read hcnvm.h. */
        hc_nvm_service(tick_ms, trg_rpm,
                       (unsigned char)(trg_state >= TRG_COUNTING),
                       (unsigned char)(hcb_state == HCB_RUNNING || (hc_etbcal_status() & 0x00F0u)
                                       || hc_dbw_bridge_on() || (trg_rpm==0u && hc_dl_count)),
                       hc_cfg_stable);

        /* THE S5500 WINDOW, MOVED BY AN ORDINARY PAGE EDIT.
         *
         * '!W' still works and is still the documented command. This is a
         * SECOND, INDEPENDENT path to the same place, and it exists because
         * on 2026-09-02 the TunerStudio commandButton bound to '!W'
         * transmitted nothing on the real ECU with a correctly parsing .ini
         * and the controller online. Page WRITES are the mechanism
         * TunerStudio performs for every field on every dialog, and this
         * ECU's page transport is the part that is PHYSICALLY VERIFIED.
         *
         * ON CHANGE, NOT EVERY PASS. Applying the page value unconditionally
         * would silently undo '!W' on the next loop and leave a bench
         * operator watching a window that snaps back. Only a change to the
         * field moves the window, so the two paths coexist and the last
         * deliberate action wins. */
        {
            unsigned char want = hc_cal_u8(CFG_U_S5500_BASE);
            if (want != s5500_page_last) {
                s5500_page_last = want;
                hc_hal_s5500_window(want);
            }
        }

        if ((unsigned int)(tick_ms - uptime_mark) >= 1000u) {
            uptime_mark = (unsigned int)(uptime_mark + 1000u);
            uptime_s++;
        }
        if ((unsigned int)(tick_ms - och_mark) >= 40u) {
            och_mark = tick_ms;
            och_cycle = 1u;
        }
        if (och_cycle) {
            SVC_BEGIN();
            if (hc_diag_publish_step()) och_cycle = 0u;
            SVC_END(svc_diag);
        }
        hc_rtmon_service(tick_ms);
        HC_RT.dbw_gap_max = hc_dbw_gap_max();
        /* alive_line() IS NOT CALLED HERE ANY MORE. See the paragraph above
           the function's definition for why, and do not resurrect a call to
           it from this loop without a non-blocking replacement.

           V16's first attempt at this fix (2026-08-30) gated the call on
           `hc_asic_run_ok >= 4u || tick_ms >= 500u`, on the theory that
           waiting for a few real UMKOM answers before the print would keep
           it clear of the exchange's critical window. MEASURED, that gate
           does not work: with the runtime dialogue healthy, `hc_asic_run_ok`
           reaches 4 by roughly T=58 ms (frame 1 completes at the
           hardware-measured T=28 ms; TGT_ASIC_RUN_PERIOD_MS is 10 ms, so
           frames 2/3/4 land at ~38/48/58 ms) - comfortably BEFORE
           `alive_line()`'s own first deadline, which the V15 hardware log
           (hanicore_2026-08-30_12-54-09.log) puts at T~107-128 ms (`alive_mark`
           set at main-loop entry, `alive_period()` = 100 ms for the first
           second). So by the time the print's own timer is due, the gate
           condition is ALREADY true, and it would fire anyway - a count-based
           delay cannot outrun a print whose own deadline is later than the
           count it is waiting for.
           Counting `alive_line()`'s own literal text (35-odd fields, ~239
           characters including "\r\n") against the ~533 us/character K-line
           cost this file's own history has MEASURED (3 added banner
           characters moved every exchange timestamp by ~1.6 ms - see the
           comment on `banner()`), one call is ~127 ms of pure blocking
           transmission: 12+ missed 10 ms runtime-cadence periods in a single
           call, however late it is made to start. There is no count of
           successful exchanges that makes starting a 127 ms block safe while
           a 10 ms raster is live - the call itself has to not happen. */
    }
}
