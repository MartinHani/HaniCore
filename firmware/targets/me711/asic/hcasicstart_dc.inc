/*
 * hcasicstart_dc.inc - THE ME7.5 DC's "ASIC" service: the CC650 bus ASIC and
 * the 68HC05 monitor instead of the S5500 frame exchange. Compiled as
 * hcasicstart.c (module HCASICSTART, same object, linker file unchanged)
 * when TGT_BOARD_VAG_ME75_DC is set; every symbol hcasicstart.h exports is
 * defined here so the rest of the firmware is untouched.
 *
 * Called from hc_asic_isr() (CC27, ILVL 9) every millisecond:
 *   1. CC650 bus writes, TGT_CC650_WRITES_PER_MS per call, in the order
 *      hccc650.c decides (stock boot, stock setup, then dirty-first +
 *      round-robin refresh of the output shadows);
 *   2. every TGT_CC650_ANA_MS: the CC650 analog bytes into the HAL's tagged
 *      window (IAT = ASIC tag 1, ambient = tag 8, as the S5500 carried them),
 *      hc_io_frame() (duties -> outputs), the outputs into the shadows, and
 *      the HAL's accept hook - exactly what an accepted S5500 reply did;
 *   3. the monitor on P2.5: CC5 captures both edges of a question (RX
 *      slots); an answer is a LOW pulse whose two edges are CC5 compare
 *      mode 1 TOGGLES on T1 (exact width, no busy wait, no interrupt).
 *
 * Evidence: .scratch/me75-reverse/ (CC650_REGISTER_MAP.md, PORT_SPEC.md);
 * the stock responder 4B0906018DC 0x08CF80 (CC5 compare on T1).
 */
#include <reg167.h>
#include "hctarget.h"
#include "hcasic.h"
#include "hcasicstart.h"
#include "hcumkom.h"
#include "hcio711.h"
#include "hcrtmon711.h"
#include "hchal.h"
#include "hcatomic.h"       /* the answer's compare is armed atomically */
/* the two SFR-free cores, compiled into this module (host-tested:
   tests/host/test_hccc650_host.py, test_hcme75mon_host.py) */
#include "hccc650.c"
#include "hcme75mon.c"

#define FRAME ((unsigned int volatile far *)((unsigned long)TGT_ASIC_FRAME))
#define CC650(reg) (*(unsigned char volatile huge *)(TGT_CC650_BASE + (reg)))

/* ---------------------------------------------- hcasicstart.h exports -- */
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
unsigned int   hc_asic_run_csum_err;
unsigned int   hc_asic_run_timeout;
unsigned int   hc_asic_last_ok_ms;
unsigned int   hc_asic_last_xfer_ms;
unsigned int   hc_asic_retries;
unsigned int   hc_asic_reply_w0;
unsigned int   hc_asic_reply_w1;
unsigned int   hc_asic_ssc_errors;
unsigned int   hc_asic_pec_tx_end;
unsigned int   hc_asic_pec_rx_end;
unsigned int   hc_asic_busy_refusals;
unsigned int   hc_asic_reinits;
unsigned int   hc_asic_last_calc;
unsigned int   hc_asic_last_recv;
unsigned int   hc_asic_next_attempt;

/* set by hcio711.c (the DC branches), applied to the shadows here */
unsigned char  hc_dc_hold;        /* run-on keep-alive  -> 0x44 bit 2       */
unsigned char  hc_dc_la;          /* CJ110 LA (cal)     -> 0x46 bit 0       */
unsigned char  hc_dc_io_on;       /* hc_io_frame()'s channel ON mask        */

static hccc650_t   cc;
static hcme75mon_t mon;
unsigned char hc_asic_up;         /* hc_asic_start_init() has run           */
static unsigned char ana_step;    /* the 10 ms block, one step a ms (0 idle) */
unsigned char hc_asic_mon_on;     /* the tick requests the service          */
static unsigned char mon_mode;    /* MON_* below                            */
static unsigned int  mon_end_t1;  /* T1 of the answer's rising edge         */

#define MON_RX      0u            /* released, CC5 captures both edges      */
#define MON_TX_IDLE 1u            /* driven HIGH, no pulse                  */
#define MON_TX_FALL 2u            /* compare armed for the falling edge     */
#define MON_TX_RISE 3u            /* compare armed for the rising edge      */
#if TGT_BOARD_VAG_ME75_BFB
#define MON_LEAD_T1 100u          /* 100 us at T1 = 1.000 MHz */
#else
#define MON_LEAD_T1 75u           /* 100 us: the falling edge is in the future */
#endif
#define MON_SLOT_T1 ((unsigned int)US_TO_TICKS(1500u))   /* slot start -> fall */

/* THE MONITOR'S CLOCK. hcme75mon works in 1.5 MHz ticks. T1 is 0.75 MHz on the
   24 MHz 18T (fCPU/32), so monitor ticks = T1 << 1. On the 32 MHz BFB T1 is
   1.000 MHz and no shift gives 1.5 MHz: monitor ticks = T1 x 3/2, kept as an
   accumulator (a plain 3/2 multiply would break at T1's 16-bit wrap). It is
   advanced by every T1 reading that reaches the monitor, at least once per
   ms (monitor_service runs from the 1 ms tick). */
#if TGT_BOARD_VAG_ME75_BFB
static unsigned int  mon_acc;       /* monitor-tick clock                    */
static unsigned int  mon_last;      /* T1 at the last advance                */
static unsigned char mon_carry;     /* a half tick owed                      */
static unsigned int mon_clock(unsigned int t1)
{
    unsigned int dt = (unsigned int)(t1 - mon_last);
    unsigned int add = (unsigned int)(dt + (dt >> 1));
    mon_last = t1;
    if (dt & 1u) {
        if (mon_carry) { add++; mon_carry = 0u; } else { mon_carry = 1u; }
    }
    mon_acc = (unsigned int)(mon_acc + add);
    return mon_acc;
}
/* a CC5 capture `cap` (taken before the T1 reading `t1`) in monitor ticks */
#define MON_FROM_CAP(t1, cap, nowmon) \
    ((unsigned int)((nowmon) - (unsigned int)(((unsigned int)((t1) - (cap))) \
        + (((unsigned int)((t1) - (cap))) >> 1))))
#define MON_TO_T1(w)  ((unsigned int)(((unsigned long)(w) * 2uL) / 3uL))
#define MON_CLOCK_RESET()  do { mon_last = T1; mon_acc = 0u; mon_carry = 0u; } while (0)
#else
#define mon_clock(t1)  ((unsigned int)((t1) << TGT_MON_TICK_SHIFT))
#define MON_FROM_CAP(t1, cap, nowmon) ((unsigned int)((cap) << TGT_MON_TICK_SHIFT))
#define MON_TO_T1(w)   ((unsigned int)((w) >> TGT_MON_TICK_SHIFT))
#define MON_CLOCK_RESET()  do { } while (0)
#endif

/* CCM1 bits 7..4 = CC5: bit 3 of the nibble = T1, mode 011 capture both
   edges, 101 compare mode 1 (toggle on match) [C167CR UM 15] */
#define CC5_CAPTURE_BOTH  0x00B0u
#define CC5_COMPARE_TOG   0x00D0u
sbit MON_PIN  = P2  ^ TGT_MON_PORT_BIT;
sbit MON_DIR  = DP2 ^ TGT_MON_PORT_BIT;

static void cc5_mode(unsigned int nibble)
{
    CCM1 = (unsigned int)((CCM1 & 0xFF0Fu) | nibble);
    CC5IR = 0;
}

/* the analog bytes the stock routine reads (DC 0x03E860): IAT 0x1E,
   ambient 0x16 - into the HAL's window as S5500-style tagged words
   (tag << 12 | 10-bit value), the channels the S5500 carried them on */
static void window_fill(void)
{
    extern unsigned char hc_s5500_base;
    unsigned char i, base = hc_s5500_base;
    for (i = 0u; i < 16u; i++) {
        FRAME[(unsigned char)(base + i)] = 0xFFFFu;   /* no sample: tag 15 */
    }
    FRAME[(unsigned char)(base + 1u)] =
        (unsigned int)(0x1000u | ((unsigned int)CC650(0x1Eu) << 2));
    FRAME[(unsigned char)(base + 8u)] =
        (unsigned int)(0x8000u | ((unsigned int)CC650(0x16u) << 2));
}

static void outputs_apply(void)
{
    unsigned char on = hc_dc_io_on;
    hccc650_out(&cc, HCCC650_OUT_MIL,
                (unsigned char)((on & (1u << HC_IO_MIL)) != 0u));
    hccc650_out(&cc, HCCC650_OUT_N205,
                (unsigned char)((on & (1u << HC_IO_LDR)) != 0u));
    hccc650_out(&cc, HCCC650_OUT_RUNON, hc_dc_hold);
    hccc650_out(&cc, HCCC650_OUT_LSU_CAL, hc_dc_la);
}

static void monitor_service(void)
{
    unsigned int t1 = T1, w;
    unsigned int now = mon_clock(t1);

    if (CC5IR) {
        if (mon_mode == MON_RX) {
            CC5IR = 0;
            hcme75mon_edge(&mon, (unsigned char)MON_PIN,
                           MON_FROM_CAP(t1, CC5, now));
        } else if (mon_mode == MON_TX_FALL) {
            CC5IR = 0;                       /* LOW now: arm the rising edge */
            CC5 = mon_end_t1;
            mon_mode = MON_TX_RISE;
        } else if (mon_mode == MON_TX_RISE) {
            /* THE ANSWER IS COMPLETE: release the line and listen at once.
               The monitor may ask any time after our answer (the responder
               that ran on this ECU in 2026-08 listened for the whole rest of
               the 40 ms frame); driving P2.5 HIGH until the RX slot would
               fight its open-drain question. */
            MON_PIN = 1;
            MON_DIR = 0;
            cc5_mode(CC5_CAPTURE_BOTH);
            mon_mode = MON_RX;
            hcme75mon_listen(&mon);
        } else {
            CC5IR = 0;
        }
    }
    if (hcme75mon_poll(&mon, now, &w)) {
        /* a TX slot opens: drive HIGH, toggle LOW at +lead, HIGH at +width.
           ARMED AT THE CONFIG-CRITICAL LEVEL, T1 read inside (2026-10-28):
           with T1 read at entry, a CC25 entry (40-145 us at 24 MHz) between
           the read and the mode write put the compare 100 us in the PAST -
           CC5 then matched only after T1 wrapped (87 ms) and the answer was
           lost (me75_dc_runtime_proof E: 2 of 232 slots, gaps 60000). */
        unsigned int ps;
        MON_PIN = 1;
        MON_DIR = 1;
        HC_ATOMIC_ENTER(ps);
        t1 = T1;
        /* ON THE SLOT GRID, not at the service's time: slot start + 1.5 ms
           (the 1 ms service runs inside that, so the answer's place does not
           jitter with its latency - one answer came 1.9 ms late); a service
           later than that answers at once (+lead) */
        /* the slot's start in T1 through the ELAPSED time: the monitor's
           clock is T1 << shift in 16 bits (it drops T1's top bit), so
           t0 >> shift is not a T1 time - but a 16-bit difference is */
        now = (unsigned int)(t1 - MON_TO_T1((unsigned int)(mon_clock(t1) - mon.t0))
              + MON_SLOT_T1);
        if ((int)(now - (unsigned int)(t1 + MON_LEAD_T1)) < 0)
            now = (unsigned int)(t1 + MON_LEAD_T1);
        CC5 = now;
        mon_end_t1 = (unsigned int)(now + MON_TO_T1(w));
        cc5_mode(CC5_COMPARE_TOG);
        HC_ATOMIC_EXIT(ps);
        mon_mode = MON_TX_FALL;
    } else if (mon.phase == HCME75MON_PH_RX && mon_mode != MON_RX
               && mon_mode != MON_TX_FALL && mon_mode != MON_TX_RISE) {
        /* the monitor's turn: release the line, capture its question */
        MON_PIN = 1;
        MON_DIR = 0;
        cc5_mode(CC5_CAPTURE_BOTH);
        mon_mode = MON_RX;
    }
    hc_umkom_answers  = mon.answers;
    hc_umkom_mismatch = (unsigned int)(mon.invalid + mon.timeouts);
}

void hc_asic_start_init(void)
{
    hc_asic_state = 0u;
    hc_asic_start_tx = hc_asic_start_rx = hc_asic_start_ok = 0u;
    hc_asic_start_csum_err = hc_asic_start_timeout = 0u;
    hc_asic_run_tx = hc_asic_run_rx = hc_asic_run_ok = 0u;
    hc_asic_run_live = 0u;
    hc_asic_run_csum_err = hc_asic_run_timeout = 0u;
    hc_asic_last_ok_ms = hc_asic_last_xfer_ms = hc_asic_retries = 0u;
    hc_asic_reply_w0 = hc_asic_reply_w1 = 0u;
    hc_asic_ssc_errors = hc_asic_pec_tx_end = hc_asic_pec_rx_end = 0u;
    hc_asic_busy_refusals = hc_asic_reinits = 0u;
    hc_asic_last_calc = hc_asic_last_recv = 0u;
    hc_asic_next_attempt = 0u;
    hc_dc_hold = 0u;
    hc_dc_la = 0u;
    hc_dc_io_on = 0u;
    {   /* the in-place buffer the HAL snapshots: defined, all zero (the
           S5500 switch-input words read "off", the window "no sample") */
        unsigned char i;
        for (i = 0u; i < (unsigned char)(TGT_ASIC_FRAME_MAX / 2u); i++) FRAME[i] = 0u;
    }
    hccc650_init(&cc, (unsigned char)TGT_CC650_SETUP_3E);
    ana_step = 0u;
    /* the monitor has been running since hc_asic_mon_early() */
    hc_asic_up = 1u;
}

/* boot: the monitor alone (hc_asic_isr() until hc_asic_up) */
void hc_asic_mon_service(void)
{
    monitor_service();
}

/* At the top of boot, T1 running, before IEN: released line, capture,
   startup silence from now (first answer ~56 ms later). */
void hc_asic_mon_early(void)
{
    hc_asic_up = 0u;
    MON_PIN = 1;
    MON_DIR = 0;
    cc5_mode(CC5_CAPTURE_BOTH);
    CC5IC = 0x0000u;                   /* flag polled, never an interrupt   */
    mon_mode = MON_RX;
    MON_CLOCK_RESET();
    hcme75mon_init(&mon, mon_clock(T1));
    hc_umkom_answers = 0u;
    hc_umkom_mismatch = 0u;
    hc_asic_mon_on = 1u;
}

void hc_asic_start_service(unsigned int ms)
{
    unsigned char k, reg, val;

    for (k = 0u; k < (unsigned char)TGT_CC650_WRITES_PER_MS; k++) {
        if (!hccc650_next(&cc, &reg, &val)) break;
        CC650(reg) = val;
        hc_asic_run_tx++;
    }
    hc_asic_state = cc.phase;

    /* THE 10 ms BLOCK IN THREE 1 ms STEPS (2026-11-01). In one call it took
       ~280 us at this level - the planner's level - against the 150 us the
       S5500 exchange is held to (me711_runtime_stress, 1.8T at 7000 rpm). */
    if (ana_step == 1u) {
        hc_io_frame();                  /* duties -> ON mask, heater pins */
        outputs_apply();
        ana_step = 2u;
    } else if (ana_step == 2u) {
        hc_asic_run_ok++;
        hc_asic_run_rx++;
        hc_asic_run_live = 1u;
        hc_asic_last_ok_ms = ms;
        hc_hal_ain_capture();
        ana_step = 0u;
    } else if (cc.phase == HCCC650_PH_RUN
        && (unsigned int)(ms - hc_asic_next_attempt) >= TGT_CC650_ANA_MS) {
        hc_asic_next_attempt = ms;
        hc_rtwit_frame_start((unsigned int)T7);    /* the raster telemetry */
        window_fill();
        ana_step = 1u;
    }
    monitor_service();
}

/* healthy = the CC650 is set up and refreshed; the monitor answers are its
   own business (a monitor that stops resets MAIN, as on the stock ECU) */
unsigned char hc_asic_healthy(void)
{
    return (unsigned char)(cc.phase == HCCC650_PH_RUN && hc_asic_run_live);
}
