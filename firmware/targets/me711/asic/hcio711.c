/*
 * hcio711.c - see hcio711.h first. FAR, SELF-CONTAINED, 16-BIT ONLY.
 *
 * ============================================ 1. THE ASIC'S OUTPUT PORTS ==
 *
 * The peripheral ASIC (S5500, a second C167) owns LDR (N75), TEV (EVAP) and
 * all four lambda heaters. The main CPU does not drive a pin for them: it
 * sends the ASIC an IMAGE of the ASIC's output ports in every runtime frame.
 *
 *   [BIN 0x8BE2B6] runtime TX builder. Normal path: words 4..70 copied
 *     through the pointer table at 0x816E80; words 52..58 <- FDDC..FDE8, the
 *     bit-addressable port images the OEM sets and clears with BSET/BCLR.
 *     Special path (D328 == 0x3070): 0x8B1CE6 writes the shadow 0x8052..
 *     0x805E into the same words 52..58.
 *   [BIN 0x828B1C] the register table 0x8B3502 writes through: entries
 *     0x11..0x1D are the ASIC's P0L,P0H,P1L,P1H,P2L,P2H,P3L,P3H,P4,P7,P8,P6
 *     at 0x8054..0x805F/0x8052 - the same order as the MAIN CPU's own
 *     entries 1..0x0C (0xFF00..0xFFD4). So word 52 = P6, 53 = P0, 54 = P1,
 *     55 = P2, 56 = P3, 57 = P4, 58 = P7 (low byte) / P8 (high byte).
 *   [BIN 0x8B17B0] seeds the shadow from calibration: P6 0x00FF, P0 0x0000,
 *     P1 0x3DCF, P2 0x0069, P3 0x6301, P4 0x00F0, P7/P8 0xFFFF. THOSE ARE
 *     SENT HERE AS THE IDLE IMAGE. Up to V78 HaniCore sent 0x0000 in all
 *     seven words - for an active-LOW stage family (EKP measured V76) that is
 *     "every ASIC output ON" if the ASIC applies them unmasked. Nothing was
 *     connected on the bench, so nothing showed it.
 *   [BIN 0x88F766/0x88F76A] the OEM's actuator test: BSET/BCLR FDE8.2 = LDR
 *     off/on. [port map] ASIC P7.2 LDR, P7.3 TEV, P7.4 LSH2VK, P7.5 LSH1HK,
 *     P7.6 LSH2HK, P8.7 LSH1VK. Active LOW: bit CLEAR = stage ON - EXCEPT
 *     the pre-cat heater gates P7.4 / P8.7: ACTIVE HIGH, measured V93
 *     (see idle_img below).
 *
 * The frame goes every 10 ms, so a duty is FRAME-SYNCHRONOUS: an accumulator
 * adds the duty (0.1 %) each frame and switches ON when it crosses 100 %.
 * The average is exact; the pulse unit is 10 ms (50 Hz at 50 %). That is NOT
 * the OEM's hardware PWM - its duty path through the mailbox words is not yet
 * decoded - and it is stated as such in TunerStudio and the evidence.
 *
 * ==================================================== 2. RUN-ON ============
 *
 * NL (CJ910 /EN2, keep-alive, active LOW) = NLEN_FR OR NOT(NLEN_AS). The idle
 * P1 image has NLEN_AS = 1, so NLEN_FR alone decides - exactly the OEM, which
 * holds P3.12 HIGH (veto) while running and clears it on its shutdown path
 * [BIN 0x8B5088]. On KL15 LOW this asserts run-on at once (the CJ910 is
 * counting), then keeps every output safe, waits for the persistence engine
 * and the page's minimum hold, and restores the veto. A maximum bounds it
 * whatever the store says; a reset tri-states P3.12 and R5602 pulls it HIGH,
 * so no reset can leave run-on asserted.
 *
 * ====================================================== 3. CJ120 ===========
 *
 * [BIN 0x8C0734]: 0x82325E(SSCCON 0x4617, SSCBR 0x13) = 8-bit frames at the
 * S5500's baud; BCLR P8.1/P8.2 (device 0/1); command byte then data byte;
 * BSET. The OEM scheduler [0x8C06B0] sends a pending request, else a 0x6C22
 * read-back when a write needs verifying, else 0x7822 DIAG. V96: the
 * running INIT_REG1 is COMPOSED from flags (see "THE CJ120 OPERATING MODE"
 * below); 0x98 / 0x90 are only its power-up constants, and the V79..V95
 * reading "0x98 = LA, 0x90 = measurement" was a mis-decode of the register
 * (datasheet: x PA x RA x LA x VL - 0x90 is RA = 1 with the pump OFF).
 * HaniCore writes the mode the lambda layer asks for (cj_want), verifies the
 * read-back against what it wrote, reads IDENT, then polls DIAG.
 *
 * Called only from hcasicstart.c's RUNTIME_TX idle window, in task context,
 * with the SSC's own interrupt enables already cleared by the S5500 exchange
 * teardown; SSCEIE is cleared here for the ~40 us and restored. The next
 * S5500 exchange reprograms SSCCON from scratch (asic_start_transfer).
 *
 * ================================================= 4. LSU 4.2 ============
 *
 *   UA (V)   = raw * 5 / 1023
 *   Ip (mA)  = (UA - 1.5) / (8 * 61.9 ohm)   1.5 V = 0.3 VCC, CJ120 datasheet
 *              "output voltage adjustment" 0.285..0.315 VCC; 61.9 ohm is R1070
 *              (bank 1) / R1050 (bank 2) on the ME7.1.1 schematic
 *              page 1 - in the LOWER HALF that the PDF's crop box hides
 *             . SAME-GENERATION SHEET, not a measurement of this board.
 *
 *   V85, the same sheet: bank 1 CJ120 S1071 <- UN 70, VM 51, IA 71, IP 52,
 *   heater low side cavity 5 (BUK138-50, gate ASIC P8.7); bank 2 S1051 <-
 *   UN 13, VM 12, IA 14, IP 15, heater cavity 4 (gate ASIC P7.4). UA -> MAIN
 *   AN6 / AN4; UR (the Ri signal) -> ASIC AN12 / AN13 = S5500 w12 / w13.
 *   The ME7.5 C2-2 sheet uses 70/51/71/52 + 5 for its own LSU, so an AWT
 *   G39 lands on bank 1 pin for pin (evidence V85 WIDEBAND_MAPPING.md).
 *   phi      = 0.99153 - 0.23505 Ip (Ip < 0) / 0.41441 Ip (Ip >= 0), valid
 *              -1.85..+1.19 mA: rusefi wideband_firmware
 *              lambda_conversion.cpp GetPhiLsu42, fitted to Bosch's table.
 *   lambda   = 1 / phi.
 * Valid only with the heater READY, the CJ120 verified and reporting no
 * failure, and UA inside the amplifier's swing. Otherwise the channel reads
 * 0 and the valid bit is clear - never a plausible-looking number.
 */
#include <reg167.h>
#include "hctarget.h"
#include "hchal.h"
#include "hchal_me711.h"
#include "hcasicstart.h"
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hcio711.h"
#include "hcengctl711.h"
#include "hcdeadline711.h"
#include "hcload711.h"
#include "hcwb.h"
#include "hccam.h"
#include "hctrigger.h"
#include "hcsched_dry.h"
#include "hcetbcal.h"
#include "hcboost711.h"
#include "hcidle711.h"
#include "hcdtc711.h"
#include "hctrans711.h"
#include "hcatomic.h"
#include "hclimp711.h"
#include "hcengine.h"
#include "hcsafety.h"
#include "hcevlog711.h"
extern unsigned char hc_hal_trig_armed;   /* hchal.h: not included (far prototypes) */
/* hc_dbw.c through its far thunk (hcfar_me711.c): this module does not
   include hcfarbridge.h, so the thunk is named directly. */
#include "hc_dbw.h"
#include "hcbench.h"
#include "hcfuelpump.h"
#include "hcmainrelay.h"
#include "hc_config_manager.h"
#include "hc_validation.h"
#include "hc_route.h"
extern unsigned int far hc_dbw_term_f(unsigned char i);

#define IO_OCH  ((unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_OCH))
/* The page, read directly: every offset used here is >= HC_CFG_CORE and so
   lives in external SRAM behind the 12-byte header (hcconfig.c hc_cal_u8).
   READ ONLY - a far routine cannot call hc_cal_u8(), and this is the same
   byte it would return. */
#define IO_PAGE ((unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_CFG                                         + HC_CFG_HDR_LEN))

sbit IO_NLEN_FR  = P3  ^ TGT_NLEN_FR_PORT_BIT;
sbit IO_NLEN_FRD = DP3 ^ TGT_NLEN_FR_PORT_BIT;
sbit IO_CJ_CS1   = P8  ^ 1;
sbit IO_CJ_CS2   = P8  ^ 2;

/* [BIN 0x8B17B0] the OEM's own idle images, computed from its calibration -
   EXCEPT the two PRE-CAT HEATER gates in word 58 (P7.4, P8.7), which rest
   CLEAR. PHYSICAL, V93 bench 2026-09-28 (bench measurement
   WIDEBAND_HEATER_DRIVE.md): with no heater fitted, both CJ120s report heater
   "no failure" (DIAG 7..6 = 11) while the bit is SET and "open load" (01)
   while it is CLEAR - P8.7 on chip 1, P7.4 on chip 2, nothing else moved. By
   the Bosch CJ120 datasheet "Diagnosis of external heater", no-load "no failure"
   exists only with DIAHG HIGH and the drain SINKING, i.e. the BUK138 gate
   HIGH and the FET conducting; "open load" is gate LOW. So these two stages
   are ACTIVE HIGH (the ASIC pin is the gate), and the OEM seed 0xFFFF, sent
   unchanged from V79 to the first V93 bench image, held both pre-cat heater
   FETs ON from ASIC start. The OEM never BSETs/BCLRs these two bits (it does
   for LDR, TEV and the post-cat pair) - it drives these gates another way. */
static const unsigned int idle_img[HC_IO_WORDS] = {
    0x00FFu, 0x0000u, 0x3DCFu, 0x0069u, 0x6301u, 0x00F0u, 0x7FEFu
};
/* every managed output is in word 58 (index 6): P7.2..P7.6 and P8.7 */
static const unsigned int ch_bit[HC_IO_COUNT] = {
    0x0004u, 0x0008u, 0x0010u, 0x0020u, 0x0040u, 0x8000u,
    0x0001u                                 /* P7.0 lamp, active LOW */
};
/* stages whose ON is a SET bit (measured, above); the rest are active LOW.
   The post-cat pair P7.5/P7.6 is NOT measured (no CJ120 senses it). */
#define CH_ACT_HIGH  ((unsigned char)((1u << HC_IO_LSH2VK) | (1u << HC_IO_LSH1VK)))

#define RUNON_MAX_MS      15000u   /* whatever the store says             */
#define RUNON_SETTLE_MS     300u   /* pump off, throttle at rest          */
#define KEYOFF_DEBOUNCE_MS   20u   /* a dropout is not a key-off          */
#define CJ_PERIOD_MS         25u   /* one transaction per 25 ms           */
/* V81. The CJ120 IDENT read 0x1A on both chips of this ECU (V79 bench);
   bits 7..3 are the device, 2..0 the revision (the CJ125 layout). A dead or
   absent chip answers 0x00 or 0xFF and is NOT a verified chip. */
#define CJ_IDENT_MASK      0xF8u
#define CJ_IDENT_DEV       0x18u
/* Re-read INIT_REG1 after this many DIAG polls (per chip one poll per 50 ms,
   so ~1 s): a CJ120 that reset has lost its mode and must be rewritten. */
#define CJ_REVERIFY_POLLS    20u
/* ======================================= V96: THE CJ120 OPERATING MODE ==
 *
 * INIT_REG1 is "x PA x RA x LA x VL" from bit 7 down (the Bosch CJ120 datasheet p6,
 * EXACT COMPONENT DATASHEET): PA = pump current control ON ("no output
 * current PA = 0", p4), RA = Ri ADJUSTMENT (the Ri path measures the board's
 * reference resistor instead of the sensor), LA = pump-amplifier ADJUSTMENT
 * (UA reads the Ip = 0 point), VL = gain 17 instead of 8.
 *
 * The OEM [BIN 0x88FD92..0x88FDEC, chip 1 at 0x8605; chip 0 the same at
 * 0x88FC60.. into 0x8606] COMPOSES the running value: 0x80, + VL unless a
 * flag, + LA / RA on its adjustment requests, + PA only once a warm-up
 * value passes a calibration threshold (RAM 0x8509 bit 0/1 <- 0x13E6/0x13E4
 * >= [0x81DFBE] = 12800 AND 0x07EC.2, [BIN 0x862EAA / 0x86306A]), + 0x08
 * unless a flag. The constants 0x98 / 0x90 at 0x88FCC8 / 0x88FD58 are only
 * its power-up sequence. V79..V95 wrote 0x90 for ever: RA = 1 (Ri reference
 * mode) and PA = 0 (NO PUMP CURRENT) - a hot sensor would have read Ip = 0,
 * lambda ~1.01, and the UA "alive" test withheld it as "no sensor".
 *
 * HaniCore (corrected 2026-10-10, hcwb.h): PA IS ACTIVE LOW. 0xC8 cold
 * (PA = 1, pump held off), 0x88 with the pump on once the sensor is at
 * temperature, 0x9C (RA + LA) to calibrate. V96..V102 had 0x88/0xC8 the
 * other way round and the AWT car showed it: Ip = 0 in "pump" mode.
 * VL stays 0 (gain 8, the full -1.85..+1.19 mA LSU 4.2 range; the OEM runs
 * gain 17 near stoichiometry for resolution). */
/* The modes, states, faults and every threshold live in the shared core,
   sensors/hcwb.c (SFR-free, host-tested: tests/host/test_hcwb.c). */

unsigned char hc_io_cj_mask;       /* set by main: lambda source INTERNAL  */

static unsigned int  img[HC_IO_WORDS];
static unsigned int  duty[HC_IO_COUNT];
static unsigned int  acc[HC_IO_COUNT];
static unsigned char on_mask;

static unsigned char tst_ch, tst_on, tst_n, tst_active, tst_pending;
/* 0..3 = the ASIC PWM unit a heater-drive experiment pulses, else 0xFF */
static unsigned char tst_pwm;
static unsigned int  tst_mark, tst_on_ms;

static unsigned char ro_state, ro_flags, ro_seen_kl15;
static unsigned int  ro_mark, ro_elapsed, ro_count;

static unsigned char cj_phase[2], cj_next;
static unsigned int  cj_reg1[2], cj_ident[2], cj_diag[2], cj_err[2];
static unsigned char cj_rv[2];        /* DIAG polls since the last INIT_REG1 check */
static unsigned char cj_want[2];      /* the INIT_REG1 the chip must hold  */
static unsigned char cj_wrote[2];     /* what phase 0 last wrote           */
static unsigned char cj_ok[2];        /* IDENT and the mode verified; only
                                         a failed check clears it (the ~1 s
                                         re-verification does not)            */
static unsigned int  cj_mark, cj_xfers;
static unsigned int  cj_tmo[2];     /* SSC exchanges that never completed */

/* V96 wideband state, per bank - the shared core's */
static hcwb_t        wb[2];
static unsigned int  wb_ur_raw[2];
/* a bench MODE HOLD - both chips held in one INIT_REG1 for a bounded
   time (hcbench mode 5, channels 8..13), heater off, lambda withheld: the
   bench experiment that proves RA / LA / PA physically. */
static unsigned char tst_cj_active, tst_cj_mode;
static unsigned int  tst_cj_mark, tst_cj_ms;
static const unsigned char tst_cj_modes[HC_IO_TEST_CJ_N] = {
    HCWB_MODE_COLD, HCWB_MODE_COLD | HCWB_RA, HCWB_MODE_COLD | HCWB_LA,
    HCWB_MODE_PUMP, HCWB_MODE_CAL, 0x90u
};

static unsigned int  lam_status;
static unsigned int  lam_acq_flags;
static unsigned int io_last_ms;     /* last lifecycle step, also event clock */
extern unsigned int hc_tick_ms;

/* A write invalidates acquisition ownership. Readback establishes a new
   epoch. After analog settling, BOTH acquisitions must be newer than that
   boundary; the request itself never qualifies a cached sample. */
typedef struct {
    unsigned int ack_ms, reply_ms;
    unsigned char settled;
} cj_acq_t;
#define CQ ((cj_acq_t huge *)(TGT_EXTRAM_BASE + TGT_RAM_CJ_ACQ))
#define CJ_ANALOG_SETTLE_MS 300u
#define CJ_REPLY_FRESH_MS  300u
typedef char cj_acq_fits[((TGT_RAM_CJ_ACQ - TGT_RAM_ROUTE
                       + 2uL * sizeof(cj_acq_t)) <= TGT_RAM_ROUTE_LIMIT) ? 1 : -1];

void far hc_io_init(void)
{
    unsigned char i;
    for (i = 0u; i < HC_IO_WORDS; i++) {
        img[i] = idle_img[i];
    }
    for (i = 0u; i < HC_IO_COUNT; i++) {
        duty[i] = 0u;
        acc[i] = 0u;
    }
    on_mask = 0u;
    tst_active = 0u; tst_on = 0u; tst_n = 0u; tst_ch = 0u; tst_pending = 0u;
    tst_mark = 0u; tst_on_ms = 0u; tst_pwm = 0xFFu;
    ro_state = HC_RO_RUN; ro_flags = 0u; ro_mark = 0u; ro_seen_kl15 = 0u;
    ro_elapsed = 0u; ro_count = 0u;
    for (i = 0u; i < 2u; i++) {
        cj_phase[i] = 0u; cj_reg1[i] = 0u; cj_ident[i] = 0u;
        cj_diag[i] = 0u; cj_err[i] = 0u; cj_rv[i] = 0u;
        cj_want[i] = HCWB_MODE_COLD; cj_wrote[i] = HCWB_MODE_COLD;
        cj_ok[i] = 0u; cj_tmo[i] = 0u;
        CQ[i].ack_ms = 0u; CQ[i].reply_ms = 0u; CQ[i].settled = 0u;
        hcwb_init(&wb[i]);
        wb_ur_raw[i] = HCWB_UR_NONE;
    }
    cj_next = 0u; cj_mark = 0u; cj_xfers = 0u; lam_status = 0u; lam_acq_flags = 0u;
    io_last_ms = 0u;
    tst_cj_active = 0u; tst_cj_mode = HCWB_MODE_COLD; tst_cj_mark = 0u;
    tst_cj_ms = 0u;
    hc_io_cj_mask = 0u;
}

void far hc_io_frame(void)
{
    unsigned char c, on;
    unsigned int w = idle_img[6];

    on_mask = 0u;
    for (c = 0u; c < HC_IO_COUNT; c++) {
        if (tst_active && !tst_pending && c == tst_ch) {
            on = tst_on;
        } else if (duty[c] >= 1000u) {
            on = 1u;
            acc[c] = 0u;
        } else {
            acc[c] = (unsigned int)(acc[c] + duty[c]);
            on = 0u;
            if (acc[c] >= 1000u) {
                acc[c] = (unsigned int)(acc[c] - 1000u);
                on = 1u;
            }
        }
        if (c == HC_IO_LSH1VK || c == HC_IO_LSH2VK) {
            unsigned char b = (unsigned char)(c == HC_IO_LSH2VK);
            unsigned char bench = (unsigned char)(tst_active && c == tst_ch);
            if (bench && !tst_pending && tst_on
                && (unsigned int)(hc_tick_ms - tst_mark) >= tst_on_ms) {
                on = 0u; tst_on = 0u; tst_mark = hc_tick_ms;
                if (++tst_n >= 3u) { tst_active = 0u; tst_pwm = 0xFFu; }
            }
            if (!(P6 & (1u << TGT_KL15STAT_PORT_BIT))
                || (!bench && ((unsigned int)(hc_tick_ms - io_last_ms) > TGT_ADC_FRESH_MS
                    || !cj_ok[b] || !CQ[b].settled
                    || !hc_fresh_ok(HC_AIN_VBAT) || (eng_sensor_err & ENG_ERR_BATT)
                    || hc_hal_asic_age() > TGT_ASIC_FRESH_MS
                    || IO_PAGE[CFG_U_LAM_HEAT_POLICY] == HCWB_HEAT_OFF
                    || !(hc_io_cj_mask & (unsigned char)(1u << b))))) {
                /* Release cached normal duty terminally; frame progression
                   is not proof that the lifecycle controller has run. */
                on = 0u; duty[c] = 0u; acc[c] = 0u;
                wb[b].valid = 0u; wb[b].lambda = 0u;
                wb[b].permission = 0u; wb[b].tail_ms = 0u;
                lam_status &= (unsigned int)~(1u << b);
                if (bench) { tst_active = 0u; tst_on = 0u; tst_pending = 0u; }
            }
        }
        if (on) {
            if (CH_ACT_HIGH & (unsigned char)(1u << c)) {
                w |= ch_bit[c];                     /* heater gate HIGH */
            } else {
                w &= (unsigned int)~ch_bit[c];      /* active LOW */
            }
            on_mask |= (unsigned char)(1u << c);
        }
    }
    img[6] = w;
}

unsigned int far hc_io_word(unsigned char i)
{
    return (i < HC_IO_WORDS) ? img[i] : 0u;
}

/* PP0..PP3 = 0xFFFE, PW0..PW3 = 0xFFFF: the OEM's forced-OFF pair, so a PWM
   unit that IS enabled can never drive P7.0..P7.3 away from the port image.
   See hcio711.h. HaniCore does not use the ASIC's hardware PWM - EXCEPT the
   V93 heater-drive bench experiment: while one of its bounded pulses is ON,
   the pulsed unit gets the OEM period (0x7A11, the ROM default frame
   0x817032 entries 55..57) and PW 0 = output HIGH for the whole period
   (C167 PWM mode 0). The OEM's own LSU heater routine (0x88F3BC) writes PW1
   and PW2 from PP1/PP2 as period x (255 - duty) / 256 - so if a PWM unit
   drives a heater gate, this is the shape the OEM uses, at 100 %. */
#define TST_PWM_PERIOD  0x7A11u
unsigned int far hc_io_pwm_word(unsigned char i)
{
    if (tst_active && tst_on && tst_pwm == (unsigned char)(i & 3u)) {
        return (i < 4u) ? TST_PWM_PERIOD : 0x0000u;
    }
    return (i < 4u) ? 0xFFFEu : 0xFFFFu;
}

void far hc_io_duty(unsigned char ch, unsigned int d)
{
    if (ch >= HC_IO_COUNT) {
        return;
    }
    if (d > 1000u) {
        d = 1000u;
    }
    if (d == 0u) {
        acc[ch] = 0u;
    }
    duty[ch] = d;
}

void far hc_io_all_off(void)
{
    unsigned char c;
    for (c = 0u; c < HC_IO_COUNT; c++) {
        duty[c] = 0u;
        acc[c] = 0u;
    }
    tst_active = 0u;
    tst_on = 0u;
}

/* ------------------------------------------------------------ run-on -- */
static void veto(void)
{
    IO_NLEN_FR  = 1;       /* value first ... */
    IO_NLEN_FRD = 1;       /* ... then the driver, as hc_power_hold_assert */
}

#define BH  ((unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_BOOTHIST))
typedef char hc_bh_fits[(HC_BH_BYTES <= TGT_RAM_BOOTHIST_LIMIT) ? 1 : -1];

void far hc_io_boothist_boot(unsigned int boots, unsigned int raw,
                             unsigned int prev_ms, unsigned int prev_stage,
                             unsigned char kl15)
{
    unsigned char h, i;
    unsigned char huge *r;

    hc_evlog_init(boots, raw);     /* the event ring records the boot */

    if (BH[0] != 'B' || BH[1] != 'H' || BH[2] >= HC_BH_N
        || BH[3] > HC_BH_N) {
        for (i = 0u; i < (unsigned char)HC_BH_BYTES; i++) {
            BH[i] = 0u;
        }
        BH[0] = 'B'; BH[1] = 'H';
        BH[4] = 0xFFu; BH[5] = 0xFFu; BH[6] = 0xFFu; BH[7] = 0u;
    }
    h = BH[2];
    r = BH + HC_BH_HDR + (unsigned int)h * HC_BH_REC;
    r[0] = (unsigned char)(boots >> 8);  r[1] = (unsigned char)boots;
    r[2] = (unsigned char)(raw >> 8);    r[3] = (unsigned char)raw;
    r[4] = (unsigned char)(prev_ms >> 8); r[5] = (unsigned char)prev_ms;
    r[6] = (unsigned char)prev_stage;
    r[7] = BH[4];                       /* previous boot's last run-on state */
    r[8] = BH[5];                       /* previous boot's lowest battery    */
    r[9] = (unsigned char)((kl15 ? 1u : 0u)
                           | ((BH[6] == 1u) ? 2u : 0u)   /* its last KL15   */
                           | ((BH[7] & 1u) ? 4u : 0u));  /* it held power   */
    BH[2] = (unsigned char)((h + 1u) % HC_BH_N);
    if (BH[3] < HC_BH_N) BH[3]++;
    BH[4] = 0xFFu; BH[5] = 0xFFu; BH[6] = (unsigned char)(kl15 ? 1u : 0u);
    BH[7] = 0u;
}

unsigned char far hc_io_boothist_byte(unsigned int off)
{
    /* the event ring follows the boot history in the window */
    return (off < HC_BH_BYTES) ? BH[off]
         : hc_evlog_byte((unsigned int)(off - TGT_BH_EXPORT_BYTES));
}

unsigned char far hc_io_runon_service(unsigned int ms, unsigned char kl15,
                                      unsigned char enabled,
                                      unsigned char nvm_busy,
                                      unsigned int min_hold_ms,
                                      unsigned int batt_dv)
{
    /* the boot history's live half, cheap enough for every pass. */
    BH[6] = (unsigned char)(kl15 ? 1u : 0u);
    if (batt_dv >= 30u) {               /* below 3 V: no reading yet */
        unsigned char b = (unsigned char)((batt_dv > 254u) ? 254u : batt_dv);
        if (b < BH[5]) BH[5] = b;
    }
    if (!kl15 && !ro_seen_kl15) {
        /* BOOTED WITH KL15 ALREADY OFF. Until V92 ro_state started at
           RUN, so the first pass of a boot that happened DURING a key-off
           took the RUN -> HOLD edge below and re-asserted keep-alive: the ECU
           re-latched its own supply for another hold, and a reset inside that
           hold (supply dip, monitoring) booted it into the same edge again -
           a self-sustaining loop that only a key-on ends. The car showed it:
           V91 85 boots in 7.8 s (LHWR, ~92 ms each), V92 4 boots in 1.7 s on
           a 5.7 V battery. After a
           reset nothing is pending that run-on exists for - a Burn or erase
           in flight was aborted by the reset and the store recovers it - so a
           boot that never saw KL15 vetoes at once and never holds. */
        if (ro_state != HC_RO_BOOTOFF) {
            ro_state = HC_RO_BOOTOFF;
            ro_mark = ms;
        }
        veto();
        ro_elapsed = (unsigned int)(ms - ro_mark);
        ro_flags = (unsigned char)((ro_elapsed >= KEYOFF_DEBOUNCE_MS)
                                   ? HC_RO_F_KEYOFF : 0u);
        BH[4] = ro_state;
        return ro_flags;
    }
    if (kl15) {
        ro_seen_kl15 = 1u;
        /* PRE-ARMED. MEASURED on V79 (2026-09-25): asserting keep-alive when
           the CPU sees KL15 fall is TOO LATE - the ECU never answered again,
           so the CJ910 removes VCC before a main-loop pass can react. So
           while the native relay is configured, keep-alive is requested for
           the whole key-on and RELEASED when shutdown is done. A reset
           tri-states P3.12 and R5602 pulls it HIGH (veto): no reset, hang or
           watchdog can leave it asserted. */
        if (enabled) {
            IO_NLEN_FR = 0;
        } else {
            veto();
        }
        ro_state = HC_RO_RUN;
        ro_flags = 0u;
        ro_elapsed = 0u;
        BH[4] = HC_RO_RUN;
        return 0u;
    }
    if (ro_state == HC_RO_RUN) {
        ro_mark = ms;
        ro_count++;
        if (enabled) {
            IO_NLEN_FR = 0;              /* already low; stays low          */
            ro_state = HC_RO_HOLD;
        } else {
            veto();
            ro_state = HC_RO_OFF;        /* nothing holds us: power-off     */
        }
    }
    ro_elapsed = (unsigned int)(ms - ro_mark);
    ro_flags = 0u;
    if (ro_elapsed >= KEYOFF_DEBOUNCE_MS) {
        ro_flags |= HC_RO_F_KEYOFF;
    }
    if (ro_state == HC_RO_HOLD) {
        if (min_hold_ms > RUNON_MAX_MS) {
            min_hold_ms = RUNON_MAX_MS;
        }
        if (ro_elapsed >= RUNON_MAX_MS) {
            veto();
            ro_state = HC_RO_TIMEOUT;
        } else if (!nvm_busy && ro_elapsed >= RUNON_SETTLE_MS
                   && ro_elapsed >= min_hold_ms) {
            veto();
            ro_state = HC_RO_RELEASED;
        } else {
            ro_flags |= HC_RO_F_HOLDING;
            BH[7] |= 1u;                 /* this boot held power at key-off */
        }
    }
    BH[4] = ro_state;
    return ro_flags;
}

/* -------------------------------------------------------------- CJ120 -- */
/* THE BYTE IS BOUNDED BY TIME (T7), NOT BY A PASS COUNT. A byte is 8 us
   (SSCBR 0x13 = fCPU / 40 = 1 MHz, 8 bits; C167 UM SSC baud formula). The SSC
   is the MASTER and makes its own clock, so an absent or dead CJ120 cannot
   delay it - the byte completes and reads 0x00 / 0xFF, and the IDENT check
   refuses the chip. Only an SSC that stops completing at all (a module
   fault, a reconfiguration race) can wait here. Until V97 that cost 2000
   polling passes per byte, twice per slot (1..6 ms of main loop every 25 ms,
   HANDOFF_V97 E9; the rig measured 6.4 ms per slot). Now a byte waits at most
   CJ_BYTE_TMO_US - 8x its wire time - and a timed-out first byte aborts the
   transfer, so a dead SSC costs <= ~70 us per 25 ms slot. */
#define CJ_BYTE_TMO_US   64u
static unsigned char cj_tmo_flag;
static unsigned char ssc_byte(unsigned char b)
{
    unsigned int t0;
    SSCRIC &= (unsigned int)~0x0080u;
    SSCTB = b;
    t0 = T7;
    for (;;) {
        /* THE TIMER IS SAMPLED BEFORE THE FLAG IS TESTED (owner OK,
           2026-10-11). This runs at task level. Testing the flag first and
           the timer second let an interrupt > 64 us landing between the two
           turn a byte that completed in 8 us into a time-out - the AWT car's
           cjTmo, ~9x more often with the engine running
           (..\evidence\SEMISEQ_WB_FIX_20261010; me711_cj120_preempt_proof).
           Sampled first, an expired bound is acted on only after one more
           flag test that follows it: a completed byte is always seen. */
        unsigned int waited = (unsigned int)(T7 - t0);
        if (SSCRIC & 0x0080u) {
            SSCRIC &= (unsigned int)~0x0080u;
            return (unsigned char)(SSCRB & 0xFFu);
        }
        if (waited >= US_TO_TICKS(CJ_BYTE_TMO_US)) {
            cj_tmo_flag = 1u;                   /* counted by the slot */
            return 0u;
        }
    }
}

static unsigned int cj_xfer(unsigned char dev, unsigned int word)
{
    unsigned int eic = SSCEIC;
    unsigned char hi, lo;

    cj_tmo_flag = 0u;
    SSCEIC &= (unsigned int)~0x0040u;           /* SSCEIE off for the burst */
    SSCTIC &= (unsigned int)~0x0040u;
    SSCRIC &= (unsigned int)~0x0040u;
    SSCCON &= (unsigned int)~0x8000u;           /* SSCEN low: now writable */
    SSCCON = 0x4617u;                           /* [BIN] 8-bit CJ120 mode   */
    SSCBR = TGT_ASIC_SSCBR;
    SSCCON |= 0x8000u;
    if (dev) { IO_CJ_CS2 = 0; } else { IO_CJ_CS1 = 0; }
    hi = ssc_byte((unsigned char)(word >> 8));
    lo = cj_tmo_flag ? 0u : ssc_byte((unsigned char)(word & 0xFFu));
    if (dev) { IO_CJ_CS2 = 1; } else { IO_CJ_CS1 = 1; }
    SSCCON &= (unsigned int)~0x8000u;
    SSCCON = TGT_ASIC_SSCCON_IDLE;              /* the S5500's 16-bit mode   */
    SSCCON |= 0x8000u;
    SSCCON &= (unsigned int)~0x0F00u;           /* drop any error flags     */
    SSCTIC &= (unsigned int)~0x0080u;
    SSCRIC &= (unsigned int)~0x0080u;
    SSCEIC = (unsigned int)(eic & ~0x0080u);
    return (unsigned int)(((unsigned int)hi << 8) | lo);
}

unsigned char far hc_io_cj120_due(unsigned int ms, unsigned char mask)
{
    return (unsigned char)(mask && (unsigned int)(ms - cj_mark) >= CJ_PERIOD_MS);
}

void far hc_io_cj120_slot(unsigned int ms, unsigned char mask)
{
    unsigned char d;
    unsigned int cmd, r;

    if (!mask || (unsigned int)(ms - cj_mark) < CJ_PERIOD_MS) {
        return;
    }
    cj_mark = ms;
    d = cj_next;
    cj_next ^= 1u;
    if (!(mask & (unsigned char)(1u << d))) {
        d ^= 1u;
        if (!(mask & (unsigned char)(1u << d))) {
            return;
        }
    }
    if (cj_phase[d] >= 3u && (cj_reg1[d] & 0xFFu) != cj_want[d]) {
        cj_phase[d] = 0u;               /* a mode change: write it    */
    }
    switch (cj_phase[d]) {
    case 0u:  cj_wrote[d] = cj_want[d];
              cmd = (unsigned int)(0x5600u | cj_wrote[d]); break;
    case 1u:  cmd = 0x6C22u; break;     /* read it back                    */
    case 2u:  cmd = 0x4822u; break;     /* IDENT                           */
    default:  cmd = 0x7822u; break;     /* DIAG, for ever                  */
    }
    r = cj_xfer(d, cmd);
    cj_xfers++;
    if (cj_tmo_flag) {
        /* the SSC never completed - no answer at all, whatever the
           phase. The chip is unverified until a full exchange succeeds;
           the core faults the bank (7) after 3 s without one. */
        if (cj_tmo[d] != 0xFFFFu) cj_tmo[d]++;
        cj_err[d]++;
        cj_ok[d] = 0u;
        CQ[d].settled = 0u;
        cj_phase[d] = 0u;
        return;
    }
    switch (cj_phase[d]) {
    case 0u:
        cj_ok[d] = 0u;
        CQ[d].settled = 0u;
        cj_phase[d] = 1u;
        break;
    case 1u:
        cj_reg1[d] = r;
        if ((r & 0xFFu) == cj_wrote[d]) {
            if (!cj_ok[d]) {
                CQ[d].ack_ms = ms;
                CQ[d].settled = 0u;
            }
            cj_phase[d] = 2u;           /* a new request is written at 3 */
        } else {
            /* not what was written: a chip that reset - write it again */
            cj_err[d]++;
            cj_ok[d] = 0u;
            cj_phase[d] = 0u;
        }
        break;
    case 2u:
        cj_ident[d] = r;
        if ((r & CJ_IDENT_MASK) == CJ_IDENT_DEV) {
            cj_phase[d] = 3u;
            cj_rv[d] = 0u;
            cj_ok[d] = 1u;
        } else {
            cj_err[d]++;
            cj_ok[d] = 0u;
            cj_phase[d] = 0u;           /* no chip answered: start over    */
        }
        break;
    default:
        cj_diag[d] = r;
        if (++cj_rv[d] >= CJ_REVERIFY_POLLS) {
            cj_rv[d] = 0u;
            cj_phase[d] = 1u;           /* read INIT_REG1 back: a reset CJ
                                           fails the check and is rewritten */
        }
        break;
    }
    CQ[d].reply_ms = ms;
}

/* ---------------------------------------------------- LSU 4.2 lambda -- */
/* The V79..V95 entry point, zero fixed at 1.5 V (the gates pin it). */
unsigned int far hc_io_lambda_calc(unsigned int raw)
{
    return hcwb_lambda_raw(raw);
}

/* the glue. The state machine is the shared core (hcwb.c); this hands
   it what the chip and the converters say and applies what it asks for:
   the INIT_REG1 mode (cj_want, written by hc_io_cj120_slot), the heater
   duty (the ASIC port image) and lambda. */

void far hc_io_lambda_service(unsigned int ms, unsigned int ua1,
                              unsigned int ua2, unsigned int ur1,
                              unsigned int ur2, unsigned int vbatt_dv,
                              unsigned char running)
{
    static hcwb_pair_in_t in;     /* static: the user stack is 256 bytes */
    unsigned char b, mask;

    mask = (unsigned char)(
        (IO_PAGE[CFG_U_LAM1_SRC] == HC_LAMBDA_INTERNAL_LSU ? 1u : 0u)
        | (IO_PAGE[CFG_U_LAM2_SRC] == HC_LAMBDA_INTERNAL_LSU ? 2u : 0u));
    hc_io_cj_mask = mask;

    /* the two-bank glue is the shared core's (hcwb_pair_step, host-
       tested with both banks in tests/host/test_hcwb_dual.c); this only
       reads the chips and the converters and applies what it asks for. */
    in.ms = ms;
    /* Engine maths uses 12 V as a fallback. It is not heater permission. */
    in.vbatt_dv = (hc_fresh_ok(HC_AIN_VBAT)
                  && !(eng_sensor_err & ENG_ERR_BATT)) ? vbatt_dv : 0u;
    in.en_mask = mask;
    in.key_on = (unsigned char)(ro_state == HC_RO_RUN);
    in.running = running;
    in.afterrun = (unsigned char)(IO_PAGE[CFG_U_LAM_HEAT_POLICY] == HC_LAMBDA_HEAT_RUNNING);
    /* Selected installation policy, not proof of actual H+ availability.
       Supply gates require a real qualified VBAT reading, never fallback. */
    switch (IO_PAGE[CFG_U_LAM_HEAT_POLICY]) {
    case HC_LAMBDA_HEAT_IGNITION:
        in.heat_allow = in.key_on;
        break;
    case HC_LAMBDA_HEAT_RUNNING:
        in.heat_allow = (unsigned char)(in.key_on && running);
        break;
    default:
        in.heat_allow = 0u;
        break;
    }
    in.hold = (unsigned char)(tst_cj_active != 0u);
    in.hold_mode = tst_cj_mode;
    in.ua[0] = ua1;
    in.ua[1] = ua2;
    in.ur[0] = ur1;
    in.ur[1] = ur2;
    lam_acq_flags = 0u;
    for (b = 0u; b < 2u; b++) {
        unsigned int age, since;
        unsigned char sem = (unsigned char)(b ? HC_AIN_O2_2_PRE : HC_AIN_O2_1_PRE);
        {   /* the CJ120 slot runs inside the S5500 exchange, an interrupt
               level since 2026-10-13 (CC27), and writes these three too */
            unsigned int s, rage;
            HC_ATOMIC_ENTER(s);
            /* `ms` was read before this block: a reply stamped since then
               is a "negative" age, i.e. fresh - never a wrapped 65 s */
            rage = (unsigned int)(ms - CQ[b].reply_ms);
            if (cj_ok[b] && rage < 0x8000u && rage > CJ_REPLY_FRESH_MS) {
                cj_ok[b] = 0u; cj_phase[b] = 0u; CQ[b].settled = 0u;
            }
            HC_ATOMIC_EXIT(s);
        }
        since = (unsigned int)(ms - CQ[b].ack_ms);
        if (since & 0x8000u) since = 0u;   /* acknowledged after `ms` was read */
        if (cj_ok[b] && !CQ[b].settled && since >= CJ_ANALOG_SETTLE_MS) {
            /* Move the boundary to settling completion and require newly
               acquired samples. It is consumed once, never reused on wrap. */
            CQ[b].settled = 1u;
            CQ[b].ack_ms = ms;
            since = 0u;
        }
        in.ua_sample[b].seq = hc_hal_main_seq(sem);
        /* UR generation is accepted tagged transport, not an established
           internal ASIC ADC-completion counter. The acknowledged-mode plus
           post-settle snapshot boundary still needs exact-board physical
           qualification; it cannot detect a frozen internal ADC mailbox. */
        in.ur_sample[b].seq = hc_s5500_snaps;
        in.ua_sample[b].mode = in.ur_sample[b].mode = (unsigned char)cj_reg1[b];
        age = hc_hal_ain_age(sem);
        in.ua_sample[b].valid = (unsigned char)(cj_ok[b] && CQ[b].settled
            && age != 0xFFFFu && age < since);
        age = hc_hal_asic_age();
        in.ur_sample[b].valid = (unsigned char)(cj_ok[b] && CQ[b].settled
            && age != 0xFFFFu && age < since && in.ur[b] != HCWB_UR_NONE);
        if (in.ua_sample[b].valid) lam_acq_flags |= (unsigned int)(1u << (2u*b));
        if (in.ur_sample[b].valid) lam_acq_flags |= (unsigned int)(2u << (2u*b));
        if (CQ[b].settled) lam_acq_flags |= (unsigned int)(16u << b);
        if (cj_ok[b]) lam_acq_flags |= (unsigned int)(64u << b);
        in.chip_ok[b] = cj_ok[b];
        in.reg1[b] = (unsigned char)(cj_reg1[b] & 0xFFu);
        in.diag[b] = (unsigned char)(cj_diag[b] & 0xFFu);
        wb_ur_raw[b] = in.ur[b];
    }
    lam_status = hcwb_pair_step(wb, &in);
    io_last_ms = ms;
    /* Passive variation is advisory. Stable exhaust can produce stable UA;
       neither noise nor a quiet signal establishes sensor response health. */
    for (b = 0u; b < 2u; b++) {
        (void)hc_lamdyn_step(b, wb[b].valid, in.ua[b], running, ms);
    }
    for (b = 0u; b < 2u; b++) {
        cj_want[b] = wb[b].want;
        hc_io_duty((unsigned char)(b ? HC_IO_LSH2VK : HC_IO_LSH1VK),
                   wb[b].duty_x10);
    }
}

/* ---------------------------------------------------------- bench test -- */
unsigned char far hc_io_test_start(unsigned char ch, unsigned int on_ms,
                                   unsigned int ms)
{
    /* a CJ120 MODE HOLD (both chips, one INIT_REG1), bounded 200 ms ..
       5 s, heater off, lambda withheld, key-off aborts. */
    if (ch >= HC_IO_TEST_CJ0 && ch < HC_IO_TEST_CJ0 + HC_IO_TEST_CJ_N) {
        if (tst_active || tst_cj_active) {
            return 0u;
        }
        tst_cj_mode = tst_cj_modes[ch - HC_IO_TEST_CJ0];
        tst_cj_ms = (on_ms < 200u) ? 200u : (on_ms > 5000u) ? 5000u : on_ms;
        tst_cj_mark = ms;
        tst_cj_active = 2u;     /* 2: the clock starts at the next pass */
        return 1u;
    }
    /* the two PRE-CAT HEATER stages may be pulsed too - the bench
       experiment that decides whether the port-image bit reaches the heater
       FET's gate (the CJ120 senses that gate on DIAHG: with no heater
       fitted, gate LOW reads "open load", gate HIGH "no failure").
       Bounded exactly like N75: three pulses of <= 1 s, 1 s apart, engine
       stopped (hcbench), key-off aborts. The post-cat stages stay out. */
    if ((ch > HC_IO_TEV && ch != HC_IO_LSH1VK && ch != HC_IO_LSH2VK
         && ch != HC_IO_MIL
         && (ch < HC_IO_TEST_PWM0 || ch > HC_IO_TEST_PWM0 + 3u))
        || tst_active) {
        return 0u;
    }
    tst_pwm = (unsigned char)((ch >= HC_IO_TEST_PWM0)
                              ? (unsigned char)(ch - HC_IO_TEST_PWM0) : 0xFFu);
    if (on_ms < 50u) {
        on_ms = 50u;
    }
    if (on_ms > 1000u) {
        on_ms = 1000u;
    }
    tst_ch = ch;
    tst_on_ms = on_ms;
    tst_n = 0u;
    tst_on = 1u;
    tst_mark = ms;
    tst_pending = 1u;          /* the clock starts at the next service pass */
    tst_active = 1u;
    return 1u;
}

void far hc_io_test_service(unsigned int ms)
{
    if (tst_cj_active) {
        if (tst_cj_active == 2u) {
            tst_cj_active = 1u;
            tst_cj_mark = ms;
        } else if (ro_state != HC_RO_RUN
                   || (unsigned int)(ms - tst_cj_mark) >= tst_cj_ms) {
            tst_cj_active = 0u;         /* back to the automatic mode */
        }
    }
    if (!tst_active) {
        return;
    }
    if (tst_pending) {
        tst_pending = 0u;
        tst_mark = ms;
        return;
    }
    if (ro_state != HC_RO_RUN) {
        tst_active = 0u;              /* key-off aborts */
        tst_on = 0u;
        tst_pwm = 0xFFu;
        return;
    }
    if (tst_on) {
        if ((unsigned int)(ms - tst_mark) >= tst_on_ms) {
            tst_on = 0u;
            tst_mark = ms;
            tst_n++;
            if (tst_n >= 3u) {
                tst_active = 0u;
                tst_pwm = 0xFFu;
            }
        }
    } else if ((unsigned int)(ms - tst_mark) >= 1000u) {
        tst_on = 1u;
        tst_mark = ms;
    }
}

/* ------------------------------------------------------------ telemetry -- */
static unsigned int sat(unsigned int v, unsigned int top)
{
    return (v > top) ? top : v;
}

static void och16(unsigned int at, unsigned int v)
{
    unsigned char huge *p = at < 1024u ? IO_OCH + at
        : (unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_OCH2 + at - 1024u);
    p[0] = (unsigned char)(v >> 8);
    p[1] = (unsigned char)(v & 0xFFu);
}

/* THE KNOCK BAND-PASS, BF0..BF3 = ASIC P1.12..15 (the ME7.1.1 schematic: BFn_PX1Hn+4
   into CC195 pins 6/5/8/7), word 54 of the runtime frame. The OEM moves the
   same four bits from its band byte [BIN 0x094BBE..0x094C04, 0x8621 bits
   0..3 -> FDE0.12..15]. The idle image already carries code 3 = 14 kHz, the
   OEM's and the stock AWT's own value, so 0xFF (knock off) restores it. */
void far hc_io_knock_band(unsigned char code)
{
    unsigned int b = (code > 15u) ? (idle_img[2] & 0xF000u)
                                  : (unsigned int)((unsigned int)code << 12);
    img[2] = (unsigned int)((img[2] & 0x0FFFu) | b);
}

/* a bank's measured lambda x 1000 - 0 unless it is a MEASUREMENT
   (READY, pump on, calibrated, DIAG clean: the same rule the published
   channel follows). The closed loop reads only this. */
/* 2026-10-10 (owner): FRESH measurements only. A value HELD through an
   acquisition gap (hcwb.c GAP_HOLD_MS, valid 2, why HCWB_WHY_HELD) is shown
   on lambda1X1000 / lamWhy, but STFT, the VE/WUE Analyze flags and the fast
   block's lambdaValue - every consumer of this - read 0 for it, exactly as
   for no measurement: nothing learns from a frozen reading. */
unsigned int far hc_io_lambda(unsigned char b)
{
    b &= 1u;
    return (wb[b].valid == 1u) ? wb[b].lambda : 0u;
}

/* Stricter eligibility for protection; does not change V101 acquisition or
   closed-loop fuel behavior. A cached lambda alone cannot establish freshness. */
unsigned int far hc_io_lambda_protection(unsigned char b)
{
    unsigned char sem;
    b &= 1u; sem = b ? HC_AIN_O2_2_PRE : HC_AIN_O2_1_PRE;
    if (IO_PAGE[b ? CFG_U_LAM2_SRC : CFG_U_LAM1_SRC] != HC_LAMBDA_INTERNAL_LSU
        /* why == VALID implies valid == 1 (fresh): neither 0 nor HELD -
           and no latched fault (fault() zeroes valid) */
        || wb[b].why != HCWB_WHY_VALID
        || !wb[b].permission || !wb[b].supply_ok || wb[b].state != HCWB_ST_READY
        || !cj_ok[b] || !CQ[b].settled || (unsigned char)cj_reg1[b] != HCWB_MODE_PUMP
        || ((unsigned int)(hc_tick_ms - CQ[b].reply_ms) > CJ_REPLY_FRESH_MS
            && !((unsigned int)(hc_tick_ms - CQ[b].reply_ms) & 0x8000u))
        || (unsigned int)(hc_tick_ms - wb[b].last_ms) > 100u
        || hc_hal_ain_age(sem) > 100u || hc_hal_asic_age() > 100u) return 0u;
    return wb[b].lambda;
}

/* the latched wideband fault of a bank (hcdtc711.c) */
unsigned char far hc_io_wb_fault(unsigned char b)
{
    return wb[b & 1u].fcode;
}

/* a trouble-code clear (hcdtc711.c, '!D'): re-arm a latched wideband fault
   - the bank recalibrates and a real fault latches again (hcwb_clear) */
void far hc_io_wb_clear(void)
{
    hcwb_clear(&wb[0]);
    hcwb_clear(&wb[1]);
}

/* in three slices (part 0, 1, 2), one per main-loop pass - see
   hcdiag711.c hc_diag_publish_step(). */
void far hc_io_publish(unsigned int boost_req_x10, unsigned char part)
{
    unsigned int a, b;
    if (part == 0u) {
        a = hc_hal_ain_age(HC_AIN_TPS1);
        b = hc_hal_ain_age(HC_AIN_TPS2);
        och16(1016u, hc_hal_asic_age());
        och16(1018u, a > b ? a : b);
        och16(1020u, lam_acq_flags);
        och16(1022u, (unsigned int)((cj_reg1[0] & 0xFFu) | ((cj_reg1[1] & 0xFFu) << 8)));
        hc_ec_publish(boost_req_x10);  /* the fast block + engine control */
        return;
    }
    if (part == 1u) {
        hc_deadline_publish_diag(); hc_load_publish();
        hc_evlog_service(io_last_ms);  /* the event ring + test telemetry */
        return;
    }
    /* PARTS 2..5 (2026-10-12). Until then this was ONE slice of ~13 800
       instructions (~260 words and 88 ETB telemetry getters) - in c167sim
       the bulk of the longest main-loop pass (10.5 ms between two S5500
       services, against the 10 ms frame raster; me711_pinwrite_gap_proof).
       Same words, same values, in five passes. */
    if (part == 3u) {
        goto part3;
    }
    if (part == 4u) {
        goto part4;
    }
    if (part == 5u) {
        goto part5;
    }
    if (part == 6u) {
        goto part6;
    }
    /* MOVED FROM hcmain_me711.c update_live() (NCODE relief):
       the main relay, the configuration state, the air model, the
       bench qualifier and the fuel pump. Same offsets and values. */
    och16(208, (unsigned int)hc_main_relay_get_mode());
    och16(210, (unsigned int)hc_main_relay_get_command());
    och16(212, hc_main_relay_get_feedback_dv());
    och16(214, (unsigned int)hc_main_relay_get_feedback_state());
    och16(216, (unsigned int)hc_main_relay_get_mismatch());
    och16(218, (unsigned int)hc_main_relay_get_bound());   /* 1 = the
                         configured cavity is one this build can drive */
    och16(220, (unsigned int)hc_main_relay_get_feedback_valid());
    och16(336, hc_cfg_dirty_groups);      /* groups waiting for RPM = 0     */
    och16(338, hc_cfg_validation);        /* HC_VAL_* over DESIRED          */
    och16(340, hc_val_warnings);          /* HC_WARN_*, never blocking      */
    och16(342, hc_cfg_desired_rev);       /* host edits accepted            */
    och16(344, hc_cfg_active_rev);        /* group applications performed   */
    och16(346, hc_cfg_apply_refused);     /* applications validation refused */
    och16(350, hc_route_check_cached());  /* configured pin vs what we read */
    och16(352, hc_route_routed_mask_cached());
    och16(354, hc_val_first_bad_offset);
    och16(358, eng_rl_x10);               /* relative air charge, 0.1 % */
    och16(360, eng_air_mg_x10);           /* cylinder air mass, 0.1 mg  */
    och16(362, dry_sched_catchup);
    och16(364, hcb_state);
    och16(366, hcb_refuse);
    och16(368, (unsigned int)((hcb_mode << 8) | (hcb_channel & 0xFFu)));
    och16(370, (unsigned int)((hcb_port << 8) | (hcb_bit & 0xFFu)));
    och16(372, hcb_width_us);        /* 0 in the millisecond modes */
    och16(374, hcb_width_ms);        /* 0 in the microsecond modes */
    och16(376, hcb_conn_pin);        /* where to put the probe */
    och16(378, hcb_abort);
    och16(380, hcb_pulses);
    och16(382, hcb_runs);
    och16(384, hcb_tps_start);
    och16(386, hcb_tps_now);
    och16(388, hcb_sf_level);
    och16(390, (unsigned int)((unsigned int)hc_fuelpump_state()
                              | ((unsigned int)hc_fuelpump_command() << 8)
                              | ((unsigned int)hc_fuelpump_pin() << 9)));
    och16(392, hc_fuelpump_reason());
    och16(394, hc_fuelpump_runs());
    och16(396, hc_fuelpump_prime_left());
    och16(428, (unsigned int)((unsigned int)hc_main_relay_get_state()
                              | ((unsigned int)hc_main_relay_get_pin() << 8)));
    och16(734u, wb[0].lambda);
    och16(736u, wb[1].lambda);
    och16(738u, lam_status);
    och16(740u, (unsigned int)((cj_diag[0] & 0xFFu)
                               | ((cj_diag[1] & 0xFFu) << 8)));
    och16(742u, (unsigned int)((cj_ident[0] & 0xFFu)
                               | ((cj_ident[1] & 0xFFu) << 8)));
    och16(744u, (unsigned int)((wb[0].duty_x10 / 10u)
                               | ((wb[1].duty_x10 / 10u) << 8)));
    och16(746u, boost_req_x10);
    och16(748u, (unsigned int)(on_mask
                               | (duty[HC_IO_LDR] != 0u ? 0x0040u : 0u)
                               | (tst_active ? 0x0080u : 0u)
                               | ((img[2] & 0x0008u) ? 0x8000u : 0u)));
    och16(750u, (unsigned int)(ro_state | ((unsigned int)ro_flags << 8)));
    och16(752u, ro_elapsed);
    och16(754u, img[6]);
    och16(756u, cj_xfers);
    och16(758u, duty[HC_IO_LDR]);
    och16(760u, (unsigned int)((cj_reg1[0] & 0xFFu)
                               | ((cj_reg1[1] & 0xFFu) << 8)));
    och16(762u, ro_count);
    /* V96 wideband: Ri (0.1 ohm, 0 = not measurable), the calibration (UA
       zero and UR reference, raw), the latched fault, live UR, the heater's
       effective voltage and the mode each chip is asked to hold. */
    och16(850u, wb[0].ri_x10);
    och16(852u, wb[1].ri_x10);
    och16(854u, wb[0].ua0);
    och16(856u, wb[1].ua0);
    och16(858u, wb[0].urc);
    och16(860u, wb[1].urc);
    och16(862u, (unsigned int)(wb[0].fcode | ((unsigned int)wb[1].fcode << 8)));
    och16(864u, wb_ur_raw[0]);
    och16(866u, wb_ur_raw[1]);
    och16(868u, (unsigned int)(wb[0].veff_dv | ((unsigned int)wb[1].veff_dv << 8)));
    och16(870u, (unsigned int)(cj_want[0] | ((unsigned int)cj_want[1] << 8)));
    /* the raw measurement per bank - pump current, uA, signed */
    och16(872u, (unsigned int)wb[0].ip_ua);
    och16(874u, (unsigned int)wb[1].ip_ua);
    /* WHY each bank's lambda is withheld (HCWB_WHY_*), and the chips'
       link: exchanges refused (reset / wrong answer / no answer) and SSC
       exchanges that never completed - saturated at 255 per byte */
    och16(1010u, (unsigned int)(wb[0].why | ((unsigned int)wb[1].why << 8)));
    och16(1012u, (unsigned int)(sat(cj_err[0], 255u)
                                | (sat(cj_err[1], 255u) << 8)));
    och16(1014u, (unsigned int)(sat(cj_tmo[0], 255u)
                                | (sat(cj_tmo[1], 255u) << 8)));
    return;
part3:
    /* MOVED HERE FROM hcmain_me711.c update_live() to free NCODE
       (it had 58 bytes left): the trigger configuration readback,
       the V92/V93 trigger counters and the ETB calibration telemetry -
       plain variables and hc_etbcal_value(), which is far already.
       Same offsets, same values, one pass later at most. */
    och16(696u, trg_cfg_teeth);
    och16(698u, trg_cfg_gap);
    och16(700u, trg_cfg_ratio_x10);
    och16(702u, trg_cfg_min_teeth);
    och16(704u, trg_cfg_tooth_x10);
    och16(706u, (unsigned int)trg_cfg_angle_x10);   /* signed, physical */
    och16(708u, trg_cfg_cam_refs);
    och16(710u, trg_cfg_cam_ref_x10);
    och16(712u, trg_cfg_cam_window_x10);
    och16(714u, trg_cfg_crank_edge);
    och16(716u, trg_cfg_cam_edge);
    och16(718u, trg_cam_resolves);
    och16(720u, trg_cfg_generation);
    och16(722u, trg_cfg_capture_map);
    och16(784u, hc_tl_state);
    och16(786u, hc_tl_revs);
    och16(788u, hc_tl_teeth);
    och16(790u, trg_tooth_corr);
    och16(792u, trg_cycle_acq);
    och16(794u, trg_cycle_lost);
    och16(796u, trg_ph_noalt);
    och16(798u, trg_ph_status);
    och16(800u, trg_cam_lo_w_x10);
    och16(802u, trg_cam_hi_w_x10);
    och16(804u, trg_phase_corr);
    och16(806u, hc_etbcal_value(ETBV_REST1));
    och16(808u, hc_etbcal_value(ETBV_A1));
    och16(810u, hc_etbcal_value(ETBV_B1));
    och16(812u, hc_etbcal_value(ETBV_A2));
    och16(814u, hc_etbcal_value(ETBV_B2));
    och16(816u, hc_etbcal_value(ETBV_REST2));
    och16(818u, hc_etbcal_value(ETBV_AMP));
    och16(820u, hc_etbcal_value(ETBV_TU));
    och16(822u, hc_etbcal_value(ETBV_DETAIL));
    och16(824u, hc_etbcal_value(ETBV_CYCLES));
    och16(826u, hc_etbcal_value(ETBV_KP));
    och16(828u, hc_etbcal_value(ETBV_KI));
    och16(830u, hc_etbcal_value(ETBV_KD));
    och16(832u, hc_etbcal_value(ETBV_AMP_LIVE));
    och16(834u, hc_etbcal_value(ETBV_TU_LIVE));
    och16(836u, hc_etbcal_value(ETBV_DRIVE));
    och16(838u, hc_etbcal_value(ETBV_PHASE_MS));
    /* the cam PATTERN cores (engine/hccam.c), per cam input */
    och16(876u, (unsigned int)(hccam_bank[0].cls
                               | ((unsigned int)hccam_bank[0].tooth << 8)));
    och16(878u, (unsigned int)(hccam_bank[1].cls
                               | ((unsigned int)hccam_bank[1].tooth << 8)));
    och16(880u, (unsigned int)hccam_bank[0].dev_x10);
    och16(882u, (unsigned int)hccam_bank[1].dev_x10);
    och16(884u, (unsigned int)hccam_bank[0].sync_dev_x10);
    och16(886u, (unsigned int)hccam_bank[1].sync_dev_x10);
    och16(888u, (unsigned int)(sat(hccam_bank[0].errors, 255u)
                               | (sat(hccam_bank[1].errors, 255u) << 8)));
    och16(890u, (unsigned int)(sat(hccam_bank[0].flips, 15u)
                               | (sat((unsigned int)(hccam_bank[0].glitches
                                      + hccam_bank[0].missed), 15u) << 4)
                               | (sat(hccam_bank[1].flips, 15u) << 8)
                               | (sat((unsigned int)(hccam_bank[1].glitches
                                      + hccam_bank[1].missed), 15u) << 12)));
    /* boost control (hcboost711.c / shared hcldr.c) */
    och16(892u, hc_ldr_target_x10);
    och16(894u, (unsigned int)(hc_ldr.state | ((unsigned int)hc_ldr.cut << 8)));
    och16(896u, (unsigned int)hc_ldr.p_x10);
    och16(898u, (unsigned int)hc_ldr.i_x10);
    och16(900u, (unsigned int)hc_ldr.d_x10);
    och16(902u, hc_ldr_open_x10);
    och16(904u, hc_ldr.cuts);
    /* idle speed control (hcidle711.c / shared hcidle.c) */
    och16(906u, hc_idle_floor_x10);
    och16(908u, (unsigned int)hc_idl.trim_x10);
    och16(910u, hc_idle_target_rpm);
    och16(912u, (unsigned int)hc_idl.state);
    /* trouble codes (hcdtc711.c / shared hcdtc.c) */
    {
        och16(914u, hc_dtc.mil);
        och16(916u, hc_dtc.n_active);
        och16(918u, hc_dtc.n_stored);
        och16(920u, hc_dtc_list[0]);
        och16(922u, hc_dtc_list[1]);
        och16(924u, hc_dtc_list[2]);
        och16(926u, hc_dtc_list[3]);
        och16(928u, hc_dtc_list[4]);
        och16(930u, hc_dtc_list[5]);
        och16(932u, hc_dtc_list[6]);
        och16(934u, hc_dtc_list[7]);
        och16(936u, hc_dtc.ff_code);
        och16(938u, hc_dtc.ff[0]);
        och16(940u, hc_dtc.ff[1]);
        och16(942u, hc_dtc.ff[2]);
        och16(944u, hc_dtc.ff[3]);
    }
    return;
part4:
    /* 2026-10-11 (owner: "more than ~5 codes are not visible"): EVERY code,
       not four slots - bit i = path i of hcdtc711.c defs[] (the INI's row
       order, parsed from that table). Stored 1652/1654, active 1656/1658.
       A running mask, not 1u << i (Keil V7.53 mis-compiles a variable
       shift: me711_keil_shift_scan). */
    {
        unsigned int sm0 = 0u, sm1 = 0u, am0 = 0u, am1 = 0u, m = 1u;
        unsigned char i, st;
        for (i = 0u; i < (unsigned char)HCDTC_MAX; i++) {
            if (i == 16u) {
                m = 1u;
            }
            st = hc_dtc.p[i].st;
            if (i < 16u) {
                if (st & HCDTC_S_STORED) sm0 |= m;
                if (st & HCDTC_S_ACTIVE) am0 |= m;
            } else {
                if (st & HCDTC_S_STORED) sm1 |= m;
                if (st & HCDTC_S_ACTIVE) am1 |= m;
            }
            m = (unsigned int)(m << 1);
        }
        och16(1652u, sm0);
        och16(1654u, sm1);
        och16(1656u, am0);
        och16(1658u, am1);
    }
    /* engine protection (hclimp711.c / shared hclimp.c) */
    och16(946u, hc_limp.cut);
    och16(948u, hc_limp_duty_x10);
    /* the DBW step's terms - WHY the duty is what it is - and the
       commissioning verify's grades. */
    och16(950u, hc_dbw_term_f(DBW_T_P));
    och16(952u, hc_dbw_term_f(DBW_T_D));
    och16(954u, hc_dbw_term_f(DBW_T_FF));
    och16(956u, hc_dbw_term_f(DBW_T_OUT));
    och16(958u, hc_dbw_term_f(DBW_T_VFAC));
    och16(960u, hc_dbw_term_f(DBW_T_PEND));
    och16(962u, hc_dbw_term_f(DBW_T_PEND_MS));
    och16(964u, hc_etbcal_value(ETBV_V_SETTLE));
    och16(966u, hc_etbcal_value(ETBV_V_OVER));
    och16(968u, hc_etbcal_value(ETBV_V_ERR));
    och16(970u, hc_etbcal_value(ETBV_V_STEP));
    och16(972u, hc_dbw_term_f(DBW_T_CLEARS));
    /* sequential with fallback (hcsched_dry.c) and the fuel per cycle */
    och16(974u, (unsigned int)dry_seq_active);
    och16(976u, dry_seq_inj_mask);
    och16(978u, dry_seq_skips);
    och16(980u, dry_seq_enters);
    och16(982u, dry_seq_leaves);
    och16(984u, dry_inj_width_us);
    och16(986u, dry_inj_nofree);
    och16(988u, eng_ti_base_us);
    och16(990u, eng_deadtime_us);
    /* transient fuel (hctrans711.c) - the causal chain of a tip-in */
    och16(992u, hc_trans.want);                 /* steady x after-start   */
    och16(994u, (unsigned int)hc_trans.corr);   /* film's share, signed   */
    och16(996u, hc_trans.film);                 /* fuel on the wall, us   */
    och16(998u, hc_trans.alpha);                /* per mille per cycle    */
    och16(1000u, hc_trans.as_pm);               /* after-start, per mille */
    och16(1002u, hc_trans.base);                /* before after-start     */
    och16(1004u, hc_cel_state());               /* the lamp policy   */
    och16(1006u, (unsigned int)eng_ign_corr_x10); /* CLT+IAT timing */
    och16(1008u, (unsigned int)hc_idle_timing_x10());
    return;
part5:
    och16(1522u, hc_etbcal_value(ETBV_SWEEP_DUTY));
    och16(1524u, hc_etbcal_value(ETBV_SWEEP_FLAGS));
    och16(1526u, hc_etbcal_value(ETBV_SWEEP_RMS));
    och16(1528u, hc_etbcal_value(ETBV_SWEEP_SAT));
    {
        unsigned char j;
        for(j=34u;j<=74u;j++) och16(1530u+2u*(j-34u),hc_etbcal_value(j));
    }
    return;
part6:
    {   /* the second half of the characterization block (2026-10-12: the
           61 getters in one slice were the longest piece of a preset APPLY
           pass, me711_preset_gap_proof) */
        unsigned char j;
        for(j=75u;j<=94u;j++) och16(1530u+2u*(j-34u),hc_etbcal_value(j));
    }
    /* V97 (sequential-work NCODE relief): MOVED FROM hcmain_me711.c
       update_live() - 128..162 the engine runtime, 222..334 the trigger
       and the scheduler. Plain variables only; same offsets, same values,
       one main-loop pass later at most. */
    och16(128u, eng_batt_dv);
    /* 130 is the MEASURED coolant (gauges, logs); the control value
       with its fault substitute is at 780. */
    och16(130u, eng_clt_meas_dc);
    och16(132u, eng_iat_dc);
    och16(134u, eng_map_kpa_x10);
    och16(136u, eng_tps_x10);
    och16(138u, eng_tps2_x10);
    och16(140u, eng_pedal_x10);
    och16(142u, eng_pedal2_x10);
    och16(144u, eng_load);
    och16(146u, eng_ti_us);
    och16(148u, eng_adv_x10);
    och16(150u, eng_dwell_x100);
    och16(152u, eng_sensor_err);
    och16(154u, eng_afr_x10);
    och16(156u, (unsigned int)eng_warmup_pct);
    och16(158u, eng_fuelcut);

    /* Position. Real captures remain disabled by the default BENCH source;
       V27 arms CC15/CC8/CC9 only after an explicit page edit. */
    och16(160u, trg_rpm);
    och16(162u, (unsigned int)trg_state);

    och16(222u, (unsigned int)(trg_crank_period >> 16));
    och16(224u, (unsigned int)trg_crank_period);
    och16(226u, trg_last_dt);
    och16(228u, trg_tooth);
    och16(230u, trg_gap_metric_x10);
    och16(232u, trg_gap_detected);
    och16(234u, (unsigned int)(trg_state >= TRG_SYNC_CRANK));
    och16(236u, (unsigned int)(trg_state >= TRG_SYNC_FULL));
    och16(238u, trg_teeth_seen);
    och16(240u, trg_gaps);
    och16(242u, trg_synclost);
    och16(244u, trg_loss_reason);
    och16(246u, trg_engine_deg_x10);
    och16(248u, trg_stall_state);
    och16(250u, trg_noise_edges);
    och16(252u, trg_isr_ticks);
    och16(254u, trg_isr_max);
    och16(256u, trg_isr_headroom);
    och16(258u, (unsigned int)trg_phase);
    och16(260u, trg_rev);
    och16(262u, trg_cam1_raw);
    och16(264u, trg_cam2_raw);
    och16(266u, trg_cam1_edges);
    och16(268u, trg_cam2_edges);
    och16(270u, trg_cam1_tooth);
    och16(272u, trg_cam2_tooth);
    och16(274u, trg_cam1_window);
    och16(276u, trg_cam2_window);
    och16(278u, trg_cam_error);
    och16(280u, trg_cam_loss_reason);
    och16(282u, trg_phsok_c);
    och16(284u, dry_sched_queued);
    och16(286u, dry_sched_executed);
    och16(288u, dry_sched_cancelled);
    och16(290u, dry_sched_late);
    och16(292u, dry_sched_missed);
    och16(294u, dry_sched_max_latency);
    och16(296u, dry_sched_next_angle);
    och16(298u, dry_sched_last_angle);
    och16(300u, dry_sched_capture_overflow);
    och16(302u, dry_next_ign_slot);
    och16(304u, dry_next_inj_slot);
    och16(306u, dry_spark_advance_x10);
    och16(308u, dry_dwell_x100);
    och16(310u, dry_inj_pulse_us);
    och16(312u, dry_dwell_start_angle);
    och16(314u, dry_spark_angle);
    och16(316u, dry_inj_start_angle);
    och16(318u, dry_inj_end_angle);
    och16(320u, (unsigned int)((hc_outputs_allowed ? 1u : 0u)
          | (hc_dbw_allowed ? 2u : 0u)
          | (hc_ignition_allowed ? 4u : 0u)
          | (hc_injection_allowed ? 8u : 0u)));
    och16(322u, hc_safety_inhibits);
    och16(324u, trg_gap_pending);
    och16(326u, trg_cam1_angle);
    och16(328u, trg_cam2_angle);
    och16(330u, dry_sched_pending);
    och16(332u, dry_sched_status);
    och16(334u, (unsigned int)hc_hal_trig_armed);
}
