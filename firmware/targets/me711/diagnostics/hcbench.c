/*
 * hcbench.c - single-channel bench output qualification. Read hcbench.h first.
 *
 * This is the first code in any HaniCore Bosch image that writes an engine
 * output port, and it is written on the assumption that somebody will one day
 * change it without reading the header. Hence: the invariants are re-checked
 * on EVERY service pass and not only at the start, the bounds are compiled in
 * rather than configured, and the driver is one function with one caller.
 *
 * WHY BIT OPERATIONS AND NOT A MASK. P2 carries the eight ignition outputs AND
 * the two cam capture inputs (P2.8/P2.9, NWDG1/NWDG2) AND the throttle bridge
 * enable (P2.11, EGENFR). A read-modify-write of P2 would sample those inputs
 * and write them back, and it would do so from task context while the capture
 * interrupt is live. PROJECT_STATE's standing rule - no read-modify-write
 * across interrupt levels - applies exactly here. `sbit` compiles to BSET and
 * BCLR, which are single instructions and touch one bit.
 *
 * That forces the switch statements below, because a `sbit` needs a
 * compile-time bit number and the channel is chosen at runtime. Sixteen cases
 * is the price of not corrupting a cam input, and it is worth paying.
 *
 * WHAT THE FIRST PHYSICAL TEST IS FOR. Nothing here knows whether a HIGH on
 * P2.0 charges coil 1 or releases it, or which of the 121 connector pins moves
 * when it does. That is what the bounded pulse is for: scope the connector,
 * nothing else attached, and read the answer off the screen. Until that
 * measurement exists, no other part of this firmware may drive an output, and
 * none does.
 */
#ifdef HC_FAR_BRIDGE
#include "hcfarbridge.h"  /* FIRST: this module is FAR code on ME7.1.1 */
#endif
#include <reg167.h>
#include "hctarget.h"
#if defined(TGT_ETBCAL_FAR)
#include "hcfresh711.h"
#endif
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hctrigger.h"
#include "hcasicstart.h"
#include "hchal.h"
#include "hc_pin_descriptor.h"
#include "hcio711.h"
#include "hc_dbw.h"          /* the bench refuses while the ETB owns the bridge */
#include "hcetbcal.h"        /* calibration/autotune status (far, native) */
#include "hcbench.h"
#include "hcdeadline711.h"
#include "hcfuelpump.h"
#include "hcmainrelay.h"
#ifdef HC_FAR_BRIDGE
#include "hcfarinline.h"   /* AFTER hcconfig.h: call-free page reads */
#endif

unsigned int hcb_state, hcb_mode, hcb_channel, hcb_refuse, hcb_abort;
unsigned int hcb_pulses, hcb_requests, hcb_runs, hcb_port, hcb_bit;
unsigned int hcb_width_us, hcb_width_ms, hcb_conn_pin;
unsigned int hcb_tps_start, hcb_tps_now, hcb_sf_level;

/* ---------------------------------------------------------- the bounds --
 *
 * COMPILED IN. CFG_U_TEST_VALUE is read and then clamped to these, so no page
 * edit can lengthen a pulse or ask for a continuous energisation.
 *
 * 20 ms of injector is about four times the longest pulse this engine would
 * ever ask for at full load, so it is unmistakable on a scope and still far
 * short of anything that could overheat a winding on a bench supply. 4 ms of
 * coil dwell is a normal charge time - long enough to see, short enough that a
 * driver stage held on by a wrong polarity guess is held on for 4 ms.
 *
 * The 200 ms gap between pulses is the important one: it means the duty cycle
 * of the worst case here is 10 % for an injector and 2 % for a coil, so even
 * ten pulses in a row cannot heat anything.
 */
#define HCB_INJ_MAX_US    20000u
#define HCB_IGN_MAX_US     4000u
#define HCB_MIN_US          200u
#define HCB_PULSES_MAX       10u
#define HCB_GAP_MS          200u
/* The whole run may not outlive this, whatever the arithmetic says. Ten
   pulses at 200 ms is 2 s; 5 s is the belt to that brace. The relay mode
   needs longer because its pulses are a thousand times longer, so the cap is
   COMPUTED per run from the mode's own numbers rather than widened for
   everybody. HCB_RUN_CEIL_MS is the ceiling on that computation. */
#define HCB_RUN_MAX_MS     5000u
#define HCB_RUN_CEIL_MS   15000u

/* ------------------------------------------- the relay / fuel pump mode --
 *
 * MILLISECONDS, and only here. A relay coil pulls in somewhere around 5-15 ms
 * and a multimeter integrates over far longer than that, so a microsecond
 * pulse would answer nothing to the instrument a bench operator is most
 * likely to have in their hand. One second, three times, a second apart: an
 * audible click, a clean edge on a scope, a readable swing on a meter, and a
 * 50 % duty on a relay coil that is rated for continuous energisation anyway.
 *
 * CFG_U_TEST_VALUE is read as MILLISECONDS in this mode. That is a different
 * unit for the same page field, which is exactly the kind of thing that gets
 * misread later - so the two clamped values are published in SEPARATE
 * telemetry words, hcb_width_ms and hcb_width_us, and the one that does not
 * apply reads zero.
 */
#define HCB_RLY_MIN_MS       50u
#define HCB_RLY_MAX_MS     1000u
#define HCB_RLY_PULSES        3u
#define HCB_RLY_GAP_MS     1000u

/* -------------------------------------------------------- the DBW mode --
 *
 * A NUDGE, NOT A STROKE. 50 ms is enough to see an edge at cavity 117/118 and
 * enough for a free throttle plate to twitch; it is not enough for the plate
 * to reach a stop even if the bridge latches on, and the runaway guard below
 * catches that case anyway. Three of them, half a second apart.
 *
 * HCB_DBW_TPS_BAND is in raw 10-bit ADC counts. A full throttle sweep on this
 * sensor is several hundred counts, so 150 is roughly a quarter of travel:
 * far more than a nudge produces, far less than a runaway reaches. It is
 * COMPILED IN. A page cannot widen it.
 */
#define HCB_DBW_MIN_US     1000u
#define HCB_DBW_MAX_US    50000u
#define HCB_DBW_PULSES        3u
#define HCB_DBW_GAP_MS      500u
#define HCB_DBW_TPS_BAND    150u

/* how long after dbw_arm() the bridge's fault flag is first believed.
   The CJ220 releases SF when DI goes inactive; two millisecond ticks is far
   longer than that and far shorter than any pulse this mode can command. */
#define HCB_DBW_SF_SETTLE_MS  2u
static unsigned int  dbw_arm_ms;
static unsigned char dbw_arm_seen;

/* The supervision link must have completed this many runtime exchanges before
   anything is driven. Four is the same threshold hcasicstart.c's own state
   machine treats as "running", and it is about 40 ms of healthy 10 ms raster. */
#define HCB_ASIC_OK_MIN       4u

/* ------------------------------------------------------- the pin table --
 *
 * MAIN CPU ports, from tools/config_source/data/me711_iomap.csv, which is generated from
 * Bosch's own "Ressourcen SAB C167" workbook. Every row below is marked "both
 * ME7.1.1 columns agree" there - the target's own column in the manufacturer's
 * own document, twice.
 *
 *   ZDG1..ZDG8   ignition   P2.0 P2.1 P2.2 P2.3 P2.4 P2.5 P2.6 P2.7
 *   EV1..EV8     injectors  P7.6 P7.5 P7.4 P8.7 P8.6 P8.5 P8.4 P8.3
 *
 * NOTE THE INJECTOR ORDER. EV1..EV3 count DOWN through P7 and EV4..EV8 count
 * DOWN through P8. It is not P7.0.. and it is not ascending. PROJECT_STATE
 * records that the ME7.5 port plan had this wrong and the schematic had it
 * right; the same trap is here, and the table above is the schematic's answer.
 *
 * EVn / ZDGn are FIRING-ORDER indices, not cylinder numbers - see
 * the maintainer's design records. This module addresses the OUTPUT, so it
 * publishes the port and bit it drove and says nothing about cylinders. The
 * cylinder mapping is hc_route.c's, and it is not involved in a bench test.
 */
sbit IGN0 = P2 ^ 0;  sbit IGN0D = DP2 ^ 0;
sbit IGN1 = P2 ^ 1;  sbit IGN1D = DP2 ^ 1;
sbit IGN2 = P2 ^ 2;  sbit IGN2D = DP2 ^ 2;
sbit IGN3 = P2 ^ 3;  sbit IGN3D = DP2 ^ 3;
sbit IGN4 = P2 ^ 4;  sbit IGN4D = DP2 ^ 4;
sbit IGN5 = P2 ^ 5;  sbit IGN5D = DP2 ^ 5;
sbit IGN6 = P2 ^ 6;  sbit IGN6D = DP2 ^ 6;
sbit IGN7 = P2 ^ 7;  sbit IGN7D = DP2 ^ 7;

sbit EV1  = P7 ^ 6;  sbit EV1D = DP7 ^ 6;
sbit EV2  = P7 ^ 5;  sbit EV2D = DP7 ^ 5;
sbit EV3  = P7 ^ 4;  sbit EV3D = DP7 ^ 4;
sbit EV4  = P8 ^ 7;  sbit EV4D = DP8 ^ 7;
sbit EV5  = P8 ^ 6;  sbit EV5D = DP8 ^ 6;
sbit EV6  = P8 ^ 5;  sbit EV6D = DP8 ^ 5;
sbit EV7  = P8 ^ 4;  sbit EV7D = DP8 ^ 4;
sbit EV8  = P8 ^ 3;  sbit EV8D = DP8 ^ 3;

/* THE CAVITIES THIS BUILD CAN DRIVE AS A LOGICAL RELAY OUTPUT.
 *
 * A cavity gets in here only when this repository can quote its MAIN CPU port
 * from Bosch's own sheet. The descriptor's RELAY_OUT capability is necessary
 * and NOT sufficient: cavity 46 (SLP) is relay capable and is driven by the
 * PERIPHERAL ASIC's P1L.0, so this CPU cannot reach it at all, and pretending
 * otherwise would be the guessed pin this module exists to avoid.
 *
 *   cavity 65  P2.12 / CC12IO CPU pin 61   EKP    <- the only one, and the
 *                                                     FUEL_PUMP default too
 *
 * CAVITIES 21 AND 22 WERE HERE, WITH TWO sbit DECLARATIONS AND A DRIVE PATH.
 * They are gone, and this is the note that used to justify them:
 *
 *     cavity 21  P8.2 / CC18IO  CPU pin 11   ZAS2   <- the MAIN_RELAY default
 *     cavity 22  P8.1 / CC17IO  CPU pin 10   ZAS1
 *
 * The signal names came from `Steckerb. ME7.1.XLS`, a VW/Audi ME7.1 C4
 * connector workbook, and against the ME7.1.1 sheet that workbook is wrong for
 * the whole 18..24 block. CAVITY 21 IS KL15 - the ignition-lock feed into the
 * CJ910's enable pin - settled by three agreeing sources, one of which is this
 * ECU on the bench: remove +12 V from cavity 21 while 3 and 62 stay powered
 * and it goes OFFLINE. It is a POWER INPUT, and this module held a port write
 * for it.
 *
 * The old note already recorded that the two ME7.1.1 columns DISAGREE on
 * P8.1/P8.2 - B-Muster ZAS2/ZAS1, C-Muster CS_CJ120/ZAS1 - and that on some
 * boards P8.2 may be an SPI chip select rather than a low-side output. It
 * treated that as a reason to test cavity 24 first. It was a reason not to
 * carry the pin at all.
 *
 * hc_pin_can(21, RELAY_OUT) is now false as well, because the descriptor
 * override marks cavity 21 SPECIAL_LOCKED. Two checks; but a port write for a
 * power input is not a thing to leave standing behind one.
 */

/* Which port a cavity maps to, or 0 for "this build cannot drive it".
   Reporting and gating only; the drive itself goes through the switch in
   drive(), so this table cannot be the thing that moves a wrong pin. */
/* WHICH CAVITIES THE LOGICAL MAIN RELAY MAY BE DRIVEN ON.
 *
 * CAVITIES 21 AND 22 WERE HERE AND THEY ARE GONE. Cavity 21 is KL15 - the
 * ignition-lock feed into the CJ910's enable pin - settled by three agreeing
 * sources, one of which is this ECU on the bench: removing +12 V from cavity
 * 21 while 3 and 62 stay powered takes it OFFLINE. It is a POWER INPUT, and
 * this module used to hold a port write for it. Cavity 22 is in the same
 * block, where the ME7.1 C4 connector workbook the descriptor was derived from
 * is wrong for every row but one.
 *
 * The descriptor override refuses both before this table is reached -
 * hc_pin_can(21, RELAY_OUT) is now false, because cavity 21 advertises
 * SPECIAL_LOCKED and nothing else. That is a second check, and a port write
 * for a power input is not a thing to leave standing behind one.
 *
 * WHAT IS LEFT IS CAVITY 65, and it is the best-evidenced relay-class output
 * the MAIN CPU definitely owns: EKPR, P2.12 / CC12IO, "EKP-Ansteuerung", BOTH
 * ME7.1.1 port-map columns, through a CJ920 low-side driver - row 68 of this
 * repository's own generated I/O map.
 *
 * CAVITY 23 IS NOT HERE EITHER, and that is deliberate. Porsche's service
 * documentation and the ME7.1.1 schematic agree it is the DME main relay
 * drive - but the only HR in the whole port map is on the PERIPHERAL ASIC, at
 * a port Bosch annotates "Port nur Input". The main CPU does not own that
 * node, the internal driver path is untraced, and naming a cavity in a service
 * pinout says what it does in the car, not which silicon we can reach it
 * through.
 */
static unsigned char relay_port_of(unsigned char cavity)
{
    switch (cavity) {
    case TGT_EKP_CONN_PIN: return 2u;
    default: return 0u;
    }
}

static unsigned char relay_bit_of(unsigned char cavity)
{
    switch (cavity) {
    case TGT_EKP_CONN_PIN: return TGT_EKP_PORT_BIT;
    default: return 0xFFu;
    }
}

/* The cavity the LOGICAL main relay is routed to, from the page. */
static unsigned char relay_cavity(void)
{
    return hc_cal_u8(CFG_U_PIN_MAIN_RELAY);
}

/* EKP, the fuel pump relay. P2.12 / CC12IO, CPU pin 61, "EKP-Ansteuerung",
   both ME7.1.1 columns - see hctarget.h. P2 also carries the eight coils and
   the two cam captures, which is exactly why this is a bit operation. */
sbit EKP  = P2 ^ TGT_EKP_PORT_BIT;   sbit EKPD = DP2 ^ TGT_EKP_PORT_BIT;
/* THE STAGE IS ACTIVE-LOW (V76, measured - hctarget.h TGT_EKP_ACTIVE_HIGH).
   Until V76 this file wrote `EKP = on`, so a bench pulse left cavity 65 open
   and release()'s "pin low, then input" was the only thing that sank it. */
#define EKP_LEVEL(on) ((unsigned char)(((on) != 0u) ? TGT_EKP_ACTIVE_HIGH \
                                                     : !TGT_EKP_ACTIVE_HIGH))
/* the coil and injector stages are active-LOW too (hctarget.h, the
   OEM's own key-on port init). drive() also writes the LEVEL BEFORE the
   DIRECTION now - it did the reverse, so a pin was briefly an output at
   whatever its latch held, the order start_me711.a66 section 2 calls the only
   unsafe one. */
#define IGN_LEVEL(on) ((unsigned char)(((on) != 0u) ? TGT_IGN_ACTIVE_HIGH \
                                                     : !TGT_IGN_ACTIVE_HIGH))
#define INJ_LEVEL(on) ((unsigned char)(((on) != 0u) ? TGT_INJ_ACTIVE_HIGH \
                                                     : !TGT_INJ_ACTIVE_HIGH))

/* The throttle bridge. THE FAULT PIN IS ON P3 HERE, not on P2.9 as it is on
   the 4B0906018DC board - P2.9 is NWDG2, the second cam input, on this ECU.
   The bit numbers come from hctarget.h so that difference lives in one
   place. */
sbit DBW_EN  = P2  ^ TGT_DBW_EN_PORT_BIT;    /* EGENFR -> S8100 DI1 */
sbit DBW_END = DP2 ^ TGT_DBW_EN_PORT_BIT;
sbit DBW_PWM = P7  ^ TGT_DBW_PWM_PORT_BIT;   /* DVE1   -> S8100 IN1 */
sbit DBW_PWMD = DP7 ^ TGT_DBW_PWM_PORT_BIT;
sbit DBW_DIR = P7  ^ TGT_DBW_DIR_PORT_BIT;   /* DVE2   -> S8100 IN2 */
sbit DBW_DIRD = DP7 ^ TGT_DBW_DIR_PORT_BIT;
/* SF is NOT declared here. It is P3.15 and hchal_me711.c owns it - see
   sf_faulted() below. */

/* Which port and bit a (mode, channel) pair addresses. Reporting only - the
   drive itself goes through the switch below, so this table cannot be the
   thing that drives a wrong pin. */
static void publish_pin(unsigned char mode, unsigned char ch)
{
    static const unsigned char inj_port[8] = { 7, 7, 7, 8, 8, 8, 8, 8 };
    static const unsigned char inj_bit[8]  = { 6, 5, 4, 7, 6, 5, 4, 3 };

    hcb_conn_pin = 0u;
    if (mode == HC_TEST_COIL) {
        hcb_port = 2u;
        hcb_bit = (unsigned int)(ch - 1u);
    } else if (mode == HC_TEST_FUEL_PUMP) {
        hcb_port = 2u;
        hcb_bit = TGT_EKP_PORT_BIT;
        hcb_conn_pin = TGT_EKP_CONN_PIN;
    } else if (mode == HC_TEST_MAIN_RELAY) {
        unsigned char cav = relay_cavity();
        hcb_port = relay_port_of(cav);
        hcb_bit = relay_bit_of(cav);
        hcb_conn_pin = cav;
    } else if (mode == HC_TEST_VVT) {
        hcb_port = 7u;
        hcb_bit = (unsigned int)(ch - 1u);
        hcb_conn_pin = (ch == 2u) ? 120u : 115u;
    } else if (mode == HC_TEST_DBW) {
        /* The pin that carries the pulse is DVE1; the enable and the
           direction are reported through hcb_channel and the header, because
           this field is "where do I put the probe on the CPU side" and the
           answer during a pulse is P7.2. The connector side is the pair. */
        hcb_port = 7u;
        hcb_bit = TGT_DBW_PWM_PORT_BIT;
        hcb_conn_pin = TGT_DBW_CONN_PIN_P;
    } else {
        hcb_port = inj_port[ch - 1u];
        hcb_bit = inj_bit[ch - 1u];
    }
}

/* ------------------------------------------------- the DBW-only helpers --
 *
 * SF is an open-drain output on the bridge with R8100 pulling it to VCC_OUT,
 * so "asserted" is LOW - but the page says which way round to read it,
 * because CAL_DBW_SF_MODE exists precisely so a board that wires it the other
 * way is a configuration change and not a code change. IGNORE is honoured:
 * on an ECU whose bridge is not populated, a permanently low SF must not make
 * the mode unusable.
 */
static unsigned char sf_faulted(void)
{
    /* THE HAL OWNS THE PIN. This used to read P3.15 itself, and hc_dbw.c
       would have been a third place that knew where SF lives - the exact
       shape of the ME7.5 `SF_PIN = P2^9` trap, which on this board is a cam
       input. One implementation, in hchal_me711.c, from hctarget.h. */
    hcb_sf_level = hc_hal_dbw_sf_level();
    return hc_hal_dbw_sf_faulted();
}

/* Do the two throttle tracks agree? The relationship is CONFIGURED, not
   assumed: HC_TRACK_OPPOSITE is true of the ME7.5 pair and is not a law, and
   an ECU whose tracks run the same way must be able to say so without a
   firmware change. SCALED is not checkable from raw counts alone without the
   per-track calibration, so it is accepted here rather than failed - saying
   "I cannot check this" by passing is wrong, so it is reported: the raw
   counts are published and the bench card says to read them.

   Counts, not per cent: this runs before any calibration is trusted. */
/* ONE TRACK, NORMALISED THE WAY THE CONTROLLER DOES (hc_dbw_normalise):
   0 at the CLOSED reading, 1000 at the OPEN one, whichever way the voltage
   runs. 0xFFFF when the calibration has no span. */
/* 16-BIT ONLY: this module is FAR code and Keil's long multiply/divide
   helpers are near.
   v * 1000 / span, exactly, as (v * 50 / span) * 20 plus the remainder's
   share: v < span <= 1023, so v * 50 <= 51150 and r * 20 <= 20460. */
static unsigned int tps_norm(unsigned int raw, unsigned int lo, unsigned int hi)
{
    unsigned int span, v, q, r;

    if (hi >= lo) { span = hi - lo; v = (raw > lo) ? raw - lo : 0u; }
    else          { span = lo - hi; v = (raw < lo) ? lo - raw : 0u; }
    if (span < 32u || span > 1023u) {
        return 0xFFFFu;
    }
    if (v >= span) {
        return 1000u;
    }
    q = (unsigned int)((unsigned int)(v * 50u) / span);
    r = (unsigned int)((unsigned int)(v * 50u) % span);
    return (unsigned int)(q * 20u + (unsigned int)(r * 20u) / span);
}

static unsigned char tps_pair_bad(void)
{
    unsigned int a, b, tol, diff, sum;
#if defined(TGT_ETBCAL_FAR)
    unsigned int raw1, raw2, sample_ms;
#endif

    if (!hc_hal_ain_ok(HC_AIN_TPS1) || !hc_hal_ain_ok(HC_AIN_TPS2)) {
#if defined(TGT_ETBCAL_FAR)
        return 1u; /* Missing TPS is never motor permission on ME7.1.1. */
#else
        /* No second track bound on this board. Refusing would make the mode
           unusable on a bench with one sensor; pretending it agreed would be
           a lie. The pair check is skipped and hcb_tps_now still reports what
           track 1 does, which is the guard that actually protects anything. */
        return 0u;
#endif
    }
    /* THE TRACKS ARE COMPARED AS THE CONTROLLER COMPARES THEM - each
     * through its OWN calibration, then under the configured correlation.
     *
     * V91 compared RAW counts. A Grab (or the ETB calibration) sets the pair
     * to SAME - correct for NORMALISED tracks - and a VAG body's raw tracks
     * run opposite (the AWT at rest: 157 and 864). So every throttle bridge
     * test on the car was refused TPSPAIR, whatever the plate did
     * (2026-09-27, "Throttle bridge direction A" refused at once). */
#if defined(TGT_ETBCAL_FAR)
    if (!hc_fresh_tps_pair(&raw1, &raw2, &sample_ms)) return 1u;
#else
#define raw1 hc_hal_ain(HC_AIN_TPS1)
#define raw2 hc_hal_ain(HC_AIN_TPS2)
#endif
    a = tps_norm(raw1, hc_cal_u16(CAL_TPS1_MIN),
                 hc_cal_u16(CAL_TPS1_MAX));
    b = tps_norm(raw2, hc_cal_u16(CAL_TPS2_MIN),
                 hc_cal_u16(CAL_TPS2_MAX));
#if !defined(TGT_ETBCAL_FAR)
#undef raw1
#undef raw2
#endif
    if (a == 0xFFFFu || b == 0xFFFFu) {
        return 1u;                      /* no calibration: cannot judge   */
    }
    tol = hc_cal_u16(CFG_U_TPS_TOL_X10);     /* 0.1 % of travel          */
    switch (hc_cal_u8(CFG_U_TPS_CORR)) {
    case HC_TRACK_OPPOSITE:
        sum = (unsigned int)(a + b);
        diff = (unsigned int)((sum > 1000u) ? (sum - 1000u) : (1000u - sum));
        return (unsigned char)(diff > tol);
    case HC_TRACK_SAME:
    default:
        /* SCALED is SAME once each track has its own calibration. */
        diff = (unsigned int)((a > b) ? (a - b) : (b - a));
        return (unsigned char)(diff > tol);
    }
}

/* THE ONE FUNCTION IN THIS FIRMWARE THAT WRITES AN OUTPUT PORT.
 *
 * `on` drives the pin HIGH. Whether HIGH energises or releases the load is
 * the unknown this whole module exists to measure, so the naming stays
 * electrical - `on` means "the CPU pin is high" and nothing more. When the
 * bench answers the polarity question, THAT is when a semantic name is
 * earned.
 *
 * The direction register is set to OUTPUT on the first drive and left there
 * for the run; release() puts it back to INPUT, which is the state every one
 * of these pins is in for the whole life of the image otherwise. A reset also
 * leaves them as inputs, so the failure direction is a tri-stated pin. */
/* ------------------------------------------ V82: the cam solenoid stages --
 *
 * [SHEET the ME7.1.1 schematic p1] MAIN P7.0/POUT0 net KNWS1_P70 -> S6600 (CJ920, 2.2 A,
 * 70 V) OUT 6/7 -> cavity 115, BYG22D freewheel D6600; P7.1/POUT1 KNWS2_P71
 * -> OUT 50/51 -> cavity 120. These are the MAIN CPU's own PWM pins.
 * [BIN 0x8C0D78] the OEM's key-on PWM init: PP0 = PP1 = 0x09C3, PW0 = PW1 =
 * 0, PWMCON0 = 0x00BF (PTI0/PTI1 = fCPU/64), PWMCON1 = 0x000F, with the P7
 * latch 0x00F4 (P7.0/P7.1 = 0): 40 MHz / 64 / 2500 = 250 Hz, and PW = 0 is
 * the OEM's OFF. The CJ920 inverts (EKP measured, V76): pin LOW = stage ON,
 * so with the latch 0 the stage is ON while PT < PW - ON duty = PW / 2500.
 * Here: a fixed 50 % at the OEM 250 Hz for each bounded burst, so a logic
 * analyzer on 115/120 answers frequency, polarity and duty in one capture.
 * Off = output disabled AND the pin released (CJ920 input bias = OFF). */
#define VVT_PP      2499u        /* OEM 0x09C3                            */
#define VVT_PW50    1250u
static void vvt_pwm(unsigned char ch, unsigned char on)
{
    unsigned int b = (ch == 2u) ? 0x0002u : 0x0001u;

    if (on) {
        P7 &= (unsigned int)~b;              /* latch 0: pin = PWM signal  */
        if (ch == 2u) {
            PT1 = 0u; PP1 = VVT_PP; PW1 = VVT_PW50;
        } else {
            PT0 = 0u; PP0 = VVT_PP; PW0 = VVT_PW50;
        }
        PWMCON0 |= (unsigned int)(b | (b << 4)); /* run, fCPU/64          */
        PWMCON1 |= b;                        /* POUTx drives the pin       */
        DP7 |= b;
    } else {
        PWMCON1 &= (unsigned int)~b;         /* the pin is the latch again */
        DP7 &= (unsigned int)~b;             /* released: stage OFF        */
        PWMCON0 &= (unsigned int)~b;         /* timer stopped              */
    }
}

static void drive(unsigned char mode, unsigned char ch, unsigned char on)
{
    if (mode == HC_TEST_COIL) {
        switch (ch) {
        case 1: IGN0 = IGN_LEVEL(on); IGN0D = 1; break;
        case 2: IGN1 = IGN_LEVEL(on); IGN1D = 1; break;
        case 3: IGN2 = IGN_LEVEL(on); IGN2D = 1; break;
        case 4: IGN3 = IGN_LEVEL(on); IGN3D = 1; break;
        case 5: IGN4 = IGN_LEVEL(on); IGN4D = 1; break;
        case 6: IGN5 = IGN_LEVEL(on); IGN5D = 1; break;
        case 7: IGN6 = IGN_LEVEL(on); IGN6D = 1; break;
        case 8: IGN7 = IGN_LEVEL(on); IGN7D = 1; break;
        default: break;
        }
    } else if (mode == HC_TEST_INJECTOR) {
        switch (ch) {
        case 1: EV1 = INJ_LEVEL(on); EV1D = 1; break;
        case 2: EV2 = INJ_LEVEL(on); EV2D = 1; break;
        case 3: EV3 = INJ_LEVEL(on); EV3D = 1; break;
        case 4: EV4 = INJ_LEVEL(on); EV4D = 1; break;
        case 5: EV5 = INJ_LEVEL(on); EV5D = 1; break;
        case 6: EV6 = INJ_LEVEL(on); EV6D = 1; break;
        case 7: EV7 = INJ_LEVEL(on); EV7D = 1; break;
        case 8: EV8 = INJ_LEVEL(on); EV8D = 1; break;
        default: break;
        }
    } else if (mode == HC_TEST_FUEL_PUMP) {
        EKP = EKP_LEVEL(on); EKPD = 1;
    } else if (mode == HC_TEST_MAIN_RELAY) {
        switch (relay_cavity()) {
        case TGT_EKP_CONN_PIN: EKP = EKP_LEVEL(on); EKPD = 1; break;
        default: break;          /* why_not() already refused; belt and brace */
        }
    } else if (mode == HC_TEST_VVT) {
        vvt_pwm(ch, on);
    } else if (mode == HC_TEST_DBW) {
        /* One leg is pulsed - IN1 for channel 1, IN2 for channel 2.
           The enable and the idle-LOW legs were set by dbw_arm() before the
           first pulse and are dropped by dbw_disarm() after the last one or
           on any abort, so a pulse cannot leave the bridge enabled and a
           dropped enable cannot leave a leg driven. */
        if (on) hc_dbw_drive((unsigned char)(ch == 2u), 1000u);
        else hc_dbw_shutdown(0u);
    }
}

/* The bridge enable and legs, for the whole run rather than per pulse.
 *
 * V83, FROM THE CJ220 TRUTH TABLE (the Bosch CJ220 datasheet), because V38..V82 had
 * three things backwards and only the first one kept the motor still:
 *
 *   1. EGENFR (P2.11 -> DI) IS ACTIVE LOW. `DBW_EN = 1` was DISABLE.
 *   2. BETWEEN PULSES BOTH LEGS ARE DRIVEN LOW - L/L, "free-wheeling low".
 *      Channel 2 used to hold IN2 HIGH for the whole run and pulse IN1, which
 *      is REVERSE (L/H) for every millisecond the pulse was NOT on, and a
 *      freewheel during the pulse: the opposite of a bounded nudge.
 *   3. THE PULSE GOES ON THE LEG THAT NAMES THE DIRECTION: IN1 for channel 1
 *      (H/L forward), IN2 for channel 2 (L/H reverse). The other leg stays
 *      LOW, so the pulse width IS the drive time in both directions.
 *
 * ORDER. Arming drives both legs LOW before the enable, so the bridge comes
 * up freewheeling. Disarming puts both legs LOW, drops the enable to its
 * inactive level, releases it, and releases the legs last - at no instant is
 * a leg high on an enabled bridge with nothing timing it. */
static void dbw_arm(void)
{
    hc_dbw_shutdown(0u);
}

static void dbw_disarm(void)
{
    hc_hal_dbw_motor(0u, 0u, 0u);
}

/* Pin INACTIVE - drive(.., 0): low for the coils and injectors as inferred,
   HIGH for EKP as measured - then direction back to INPUT. Both, in that
   order: dropping the
   direction first would leave the pin floating at whatever the driver stage
   pulls it to for the instruction between. */
static void release(unsigned char mode, unsigned char ch)
{
    if (mode == HC_TEST_COIL || mode == HC_TEST_INJECTOR) hc_deadline_bench_stop();
    drive(mode, ch, 0u);
    if (mode == HC_TEST_COIL) {
        switch (ch) {
        case 1: IGN0D = 0; break;
        case 2: IGN1D = 0; break;
        case 3: IGN2D = 0; break;
        case 4: IGN3D = 0; break;
        case 5: IGN4D = 0; break;
        case 6: IGN5D = 0; break;
        case 7: IGN6D = 0; break;
        case 8: IGN7D = 0; break;
        default: break;
        }
    } else if (mode == HC_TEST_INJECTOR) {
        switch (ch) {
        case 1: EV1D = 0; break;
        case 2: EV2D = 0; break;
        case 3: EV3D = 0; break;
        case 4: EV4D = 0; break;
        case 5: EV5D = 0; break;
        case 6: EV6D = 0; break;
        case 7: EV7D = 0; break;
        case 8: EV8D = 0; break;
        default: break;
        }
    } else if (mode == HC_TEST_FUEL_PUMP) {
        EKPD = 0;
    } else if (mode == HC_TEST_MAIN_RELAY) {
        switch (relay_cavity()) {
        case TGT_EKP_CONN_PIN: EKPD = 0; break;
        default: break;
        }
    } else if (mode == HC_TEST_VVT) {
        vvt_pwm(ch, 0u);
    } else if (mode == HC_TEST_DBW) {
        /* release() is called between pulses too, so it must NOT drop the
           enable - dbw_disarm() owns that and runs once, at the end. */
        /* Keep both bridge inputs driven at equal levels between pulses. */
    }
}

/* ------------------------------------------------------ the invariants --
 *
 * EVERY reason is evaluated, not the first one - a bench operator who is told
 * only "RPM" fixes that, presses again, and is then told "config". Say all
 * of it at once.
 *
 * Called at the start AND on every service pass. An invariant that was true
 * when the button was pressed is not an invariant.
 */
static unsigned int why_not(unsigned char mode, unsigned char ch)
{
    unsigned int r = 0u;

    /* Not merely "rpm reads zero". The decoder must be reporting NO SIGNAL,
       which means no edge inside CFG_TRIG_TIMEOUT_MS. rpm alone goes to zero
       between two teeth of a barely-turning engine. */
    if (trg_rpm != 0u || trg_state != TRG_NO_SIGNAL) {
        r |= HCB_R_RPM;
    }
    /* NO PAGE ARM. The deliberate act is the explicit, bounded '!T'
       command itself, with the invariants here; HCB_R_ARMED is retired and
       never set. A page byte that had to be flipped first was a second,
       latching switch in front of a one-shot one - and the same byte gated
       normal engine operation, which it must not. */
    if (hc_cfg_faults() != 0u) {
        r |= HCB_R_CFG;
    }
    if (hc_asic_run_ok < HCB_ASIC_OK_MIN) {
        /* The S5500 can reset this CPU. Driving a pin while the supervision
           link is not established means a reset can arrive mid-pulse from a
           cause nobody is watching. A reset tri-states the pin, so this is not
           a hazard - it is an experiment with an uncontrolled variable, which
           is worse for a measurement whose whole purpose is to answer a
           question. */
        r |= HCB_R_SUPERVISOR;
    }
    /* One place decides which modes exist and how many channels each has.
       A mode absent from this switch is refused, which is the correct
       default for a module whose failure mode is energising something. */
    switch (mode) {
    case HC_TEST_INJECTOR:
    case HC_TEST_COIL:
        if (ch < 1u || ch > 8u) {
            r |= HCB_R_CHANNEL;
        }
        break;
    case HC_TEST_FUEL_PUMP:
        if (ch != 1u) {
            r |= HCB_R_CHANNEL;
        }
        /* ONE OWNER PER PIN. Since the lifecycles drive a real pin, a
           bench pulse on cavity 65 while the pump is primed or running - or
           while MAIN_RELAY holds the same cavity - would be two owners
           writing one port bit, and the bench's own exit path would release
           a pin the lifecycle still wants. Refused as BUSY: the output is in
           use, wait for it. */
        if (hc_fuelpump_command() || hc_main_relay_get_command()) {
            r |= HCB_R_BUSY;
        }
        break;
    case HC_TEST_MAIN_RELAY: {
        /* THREE SEPARATE THINGS MUST BE TRUE OF THE CAVITY, and none of them
           implies another:
             it is assigned at all;
             the DESCRIPTOR says it can carry a relay - a driver-stage
               judgement since 2026-09-03, not an OEM-name one;
             and THIS BUILD knows its CPU port. Cavity 46 passes the first
               two and fails the third: it is relay capable and it is on the
               peripheral ASIC, so this CPU cannot reach it. */
        unsigned char cav = relay_cavity();
        if (ch != 1u) {
            r |= HCB_R_CHANNEL;
        }
        if (cav == 0u || cav == 0xFFu
            || !hc_pin_can(cav, HC_PINCAP_RELAY_OUT)
            || relay_port_of(cav) == 0u) {
            r |= HCB_R_PIN;
        }
        if (hc_fuelpump_command() || hc_main_relay_get_command()) {
            r |= HCB_R_BUSY;             /* one owner per pin - see above */
        }
        break;
    }
    case HC_TEST_BOOST:
        /* N75 on the ASIC's LDR stage - three bounded ms pulses timed by
           hcio711.c, and only where the page routes boost to cavity 104.
           V93: THE HEATER-DRIVE EXPERIMENT, the same bounded pulses (three
           of <= 1 s, 1 s apart, engine stopped, key-off aborts): channel 2 =
           the port-image bit of ASIC P8.7 (bank 1, cavity 5 per the W12
           sheet), 3 = ASIC P7.4 (bank 2, cavity 4), 4..7 = the S5500's own
           PWM units 0..3 (the OEM heater routine 0x88F3BC drives PWM1/PWM2).
           The CJ120s' DIAG heater bits show which one reaches a heater gate
           (tools/me711_v93_bench_session.py). Fixed stages, no route. */
        /* 8..13 hold BOTH CJ120s in one INIT_REG1 for the test
           value's ms (200..5000): 8 0x88 cold, 9 RA, 10 LA, 11 PA (0xC8),
           12 the calibration 0x9C, 13 the V79..V95 0x90 - the experiment
           that proves the register's bits on this board (UR with RA,
           UA with LA, DIAG with PA). Heater off, lambda withheld. */
        /* 14 = the check-engine lamp stage, cavity 47 (ASIC P7.0) -
           the same bounded pulses, so a meter or a lamp on 47 proves the
           port-image bit reaches the cavity. Fixed stage, no route. */
        if (ch < 1u || ch > 14u) {
            r |= HCB_R_CHANNEL;
        } else if (ch == 1u && hc_cal_u8(CFG_U_PIN_BOOST) != TGT_LDR_CAV) {
            r |= HCB_R_PIN;
        }
        break;
    case HC_TEST_VVT:
        /* 1 = cavity 115 (KNWS1, POUT0), 2 = cavity 120 (KNWS2, POUT1).
           Nothing else in this image drives P7.0/P7.1. */
        if (ch < 1u || ch > 2u) {
            r |= HCB_R_CHANNEL;
        }
        break;
    case HC_TEST_DBW:
        if (ch < 1u || ch > 2u) {
            r |= HCB_R_CHANNEL;
        }
        /* THE TWO EXTRA INVARIANTS, and they are evaluated even when the
           channel is wrong so the answer is complete in one go. */
        if (tps_pair_bad()) {
            r |= HCB_R_TPSPAIR;
        }
        /* the ETB already owns the bridge - closed loop RUN or INIT, an
           endpoint calibration or the autotune (V93 status phase bits 4..7). */
        if (hc_dbw_state() == DBW_RUN || hc_dbw_state() == DBW_INIT
            || (hc_etbcal_status() & 0x00F0u) != 0u) {
            r |= HCB_R_ETB;
        }
        if (!hc_hal_out_class_live(HC_OUT_THR_EN)) {
            r |= HCB_R_PERMIT;
        }
        /* SF IS NOT A PRE-RUN CONDITION. A CJ220 whose DI is inactive
           reports SF LOW by design (truth table rows 5 and 9), and before the
           run the bridge IS disabled - so this refused every DBW run on a
           correctly working board. SF is judged once the run has enabled the
           bridge; see HCB_DBW_SF_SETTLE_MS. The level is still published. */
        (void)sf_faulted();
        break;
    default:
        r |= HCB_R_MODE;
        break;
    }
    return r;
}

/* --------------------------------------------------------- the run state */
static unsigned char run_mode, run_ch;
static unsigned int  run_t0;         /* tick_ms the run started             */
static unsigned int  run_mark;       /* tick_ms of the last state change    */
static unsigned int  run_pulses_max;
static unsigned int  run_ticks;      /* the pulse width, in T7 counts       */
static unsigned int  run_on_ms;      /* the pulse width, in ms - relay mode */
static unsigned int  run_gap_ms;     /* between pulses, per mode            */
static unsigned int  run_cap_ms;     /* the whole run may not outlive this  */
static unsigned char run_ms_timed;   /* 1 = the ON time is timed on the tick */
static unsigned char pin_high;
/* The two pulse clocks. Declared here with the rest of the run state so
   hcbench_init() can write them explicitly - nothing in this image runs
   Keil's ?C_INIT, so a static that is not written in init() is whatever the
   last power cycle left behind. */
static unsigned int  pulse_t7;
static unsigned int  pulse_ms;

void hcbench_init(void)
{
    /* start_me711.a66 hands straight to main() and never runs Keil's
       ?C_INIT, so nothing here starts at a known value. */
    hcb_state = HCB_IDLE;
    hcb_mode = 0; hcb_channel = 0; hcb_refuse = 0; hcb_abort = 0;
    hcb_pulses = 0; hcb_requests = 0; hcb_runs = 0;
    hcb_port = 0; hcb_bit = 0; hcb_width_us = 0; hcb_width_ms = 0;
    hcb_conn_pin = 0; hcb_tps_start = 0; hcb_tps_now = 0; hcb_sf_level = 0;
    run_mode = 0; run_ch = 0; run_t0 = 0; run_mark = 0;
    run_pulses_max = 0; run_ticks = 0; pin_high = 0;
    run_on_ms = 0; run_gap_ms = HCB_GAP_MS; run_cap_ms = HCB_RUN_MAX_MS;
    run_ms_timed = 0; pulse_t7 = 0; pulse_ms = 0;
    /* NOTHING is driven here. hc_outputs_safe() in the startup owns the
       power-on state of every pin, and this module must not have an opinion
       about pins it has not been asked to touch. */
}

unsigned char hcbench_start(unsigned char mode, unsigned char ch)
{
    unsigned int width;

    if (hcb_requests != 0xFFFFu) {
        hcb_requests++;
    }
    hcb_abort = 0u;

    if (hcb_state == HCB_RUNNING) {
        hcb_refuse = HCB_R_BUSY;
        hcb_state = HCB_REFUSED;
        return 0u;
    }
    hcb_refuse = why_not(mode, ch);
    if (hcb_refuse) {
        hcb_state = HCB_REFUSED;
        hcb_mode = mode;
        hcb_channel = ch;
        return 0u;
    }

    /* The page proposes; this clamps. CFG_U_TEST_VALUE is LIVE_APPLY, so a
       tuner can change it between runs without an RPM-zero transaction - which
       is fine precisely because it cannot exceed the compiled bound. */
    width = hc_cal_u16(CFG_U_TEST_VALUE);

    if (mode == HC_TEST_BOOST) {
        hcb_mode = mode;
        hcb_channel = ch;
        hcb_width_ms = width;
        if (!hc_io_test_start((unsigned char)(ch == 2u ? HC_IO_LSH1VK
                                              : ch == 3u ? HC_IO_LSH2VK
                                              : ch == 14u ? HC_IO_MIL
                                              : ch >= 8u
                                                ? (HC_IO_TEST_CJ0 + ch - 8u)
                                              : ch >= 4u
                                                ? (HC_IO_TEST_PWM0 + ch - 4u)
                                              : HC_IO_LDR), width, 0u)) {
            hcb_refuse = HCB_R_BUSY;
            hcb_state = HCB_REFUSED;
            return 0u;
        }
        hcb_state = HCB_DONE;       /* the frame layer times the pulses */
        if (hcb_runs != 0xFFFFu) {
            hcb_runs++;
        }
        return 1u;
    }

    run_mode = mode;
    run_ch = ch;
    hcb_width_us = 0u;
    hcb_width_ms = 0u;
    run_ticks = 0u;
    run_on_ms = 0u;

    if (mode == HC_TEST_FUEL_PUMP || mode == HC_TEST_MAIN_RELAY
        || mode == HC_TEST_VVT) {
        /* MILLISECONDS HERE. Both relay modes: a coil pulls in in 5-15 ms and
           a multimeter cannot see a microsecond pulse. See hcbench.h. */
        if (width < HCB_RLY_MIN_MS) {
            width = HCB_RLY_MIN_MS;
        }
        if (width > HCB_RLY_MAX_MS) {
            width = HCB_RLY_MAX_MS;
        }
        run_ms_timed = 1u;
        run_on_ms = width;
        run_gap_ms = HCB_RLY_GAP_MS;
        run_pulses_max = HCB_RLY_PULSES;
        hcb_width_ms = width;
    } else {
        run_ms_timed = 0u;
        if (width < HCB_MIN_US) {
            width = HCB_MIN_US;
        }
        if (mode == HC_TEST_COIL) {
            if (width > HCB_IGN_MAX_US) {
                width = HCB_IGN_MAX_US;
            }
            run_gap_ms = HCB_GAP_MS;
            run_pulses_max = HCB_PULSES_MAX;
        } else if (mode == HC_TEST_DBW) {
            if (width < HCB_DBW_MIN_US) {
                width = HCB_DBW_MIN_US;
            }
            if (width > HCB_DBW_MAX_US) {
                width = HCB_DBW_MAX_US;
            }
            run_gap_ms = HCB_DBW_GAP_MS;
            run_pulses_max = HCB_DBW_PULSES;
        } else {
            if (width > HCB_INJ_MAX_US) {
                width = HCB_INJ_MAX_US;
            }
            run_gap_ms = HCB_GAP_MS;
            run_pulses_max = HCB_PULSES_MAX;
        }
        hcb_width_us = width;
        /* MICROSECONDS TO T7 COUNTS, ONCE, HERE. TGT_TICKS_PER_MS_X10 is
           12500, so a tick is 0.8 us and ticks = us * 5 / 4. The widest case,
           50 000 us, is 62 500 counts and still fits a 16-bit compare.
           US_TO_TICKS() is not used because it is written for compile-time
           constants. */
        run_ticks = (unsigned int)(((unsigned long)width
                                    * TGT_TICKS_PER_MS_X10) / 10000uL);
    }

    /* The overall cap is DERIVED from this mode's own numbers rather than
       being one constant stretched to fit the longest mode. Two seconds of
       slack for the service raster, and a hard ceiling on top. */
    run_cap_ms = (unsigned int)(run_pulses_max
                                * (run_gap_ms + (run_ms_timed ? run_on_ms : 0u))
                                + 2000u);
    if (run_cap_ms < HCB_RUN_MAX_MS) {
        run_cap_ms = HCB_RUN_MAX_MS;
    }
    if (run_cap_ms > HCB_RUN_CEIL_MS) {
        run_cap_ms = HCB_RUN_CEIL_MS;
    }

    hcb_mode = mode;
    hcb_channel = ch;
    hcb_pulses = 0u;
    publish_pin(mode, ch);
    hcb_state = HCB_RUNNING;
    if (hcb_runs != 0xFFFFu) {
        hcb_runs++;
    }
    if (mode == HC_TEST_DBW) {
        /* The reference the runaway guard measures against, taken BEFORE the
           bridge is enabled - so a plate that moves because we enabled the
           bridge is caught, not baselined away. */
        hcb_tps_start = hc_hal_ain_ok(HC_AIN_TPS1)
                        ? hc_hal_ain(HC_AIN_TPS1) : 0u;
        hcb_tps_now = hcb_tps_start;
        dbw_arm();
        dbw_arm_seen = 0u;          /* stamped on the first service pass */
    }
    /* The first pulse begins on the next service pass, not here. One place
       decides when a pin goes high, and it is the one that also decides when
       it comes down. */
    run_t0 = 0u;
    run_mark = 0u;
    pin_high = 0u;
    return 1u;
}

void hcbench_abort(unsigned int reason)
{
    if (pin_high || hcb_state == HCB_RUNNING) {
        release(run_mode, run_ch);
        pin_high = 0u;
    }
    /* Unconditional, and it runs on EVERY abort including one that arrives
       when nothing is running. Leaving EGENFR asserted after a stop is the
       one mistake in this module that could hold a throttle motor. */
    if (run_mode == HC_TEST_DBW) {
        dbw_disarm();
    }
    if (hcb_state == HCB_RUNNING) {
        hcb_abort = reason;
        hcb_state = HCB_ABORTED;
    }
}

/* The pulse is timed on T7, the same free-running microsecond-domain counter
 * hcts.c paces the K-line with, because a 1 ms tick cannot express 200 us and
 * an injector pulse must be measured in microseconds to mean anything.
 *
 * The GAP between pulses is timed on the millisecond tick, because 200 ms
 * would overflow a 16-bit T7 count at this tick rate and does not need the
 * resolution.
 */
/* END A PULSE THAT IS DUE. Two clocks, one decision. The microsecond modes
   need T7 because a 200 us pulse cannot be expressed on a 1 ms tick; the relay
   mode needs the tick because 1000 ms would wrap a 16-bit T7 count more than
   nineteen times. Neither is used for the other. */
static void pulse_end(unsigned int tick_ms)
{
    unsigned char done;

    if (run_ms_timed) {
        done = (unsigned char)((unsigned int)(tick_ms - pulse_ms)
                               >= run_on_ms);
    } else if (run_mode == HC_TEST_COIL || run_mode == HC_TEST_INJECTOR) {
        done = (unsigned char)(HC_DL_DIAG.bench_done != 0u);
    } else {
        done = (unsigned char)((unsigned int)(T7 - pulse_t7) >= run_ticks);
    }
    if (!done) {
        return;
    }
    release(run_mode, run_ch);
    pin_high = 0u;
    run_mark = tick_ms;
    if (hcb_pulses != 0xFFFFu) {
        hcb_pulses++;
    }
    if (hcb_pulses >= run_pulses_max) {
        if (run_mode == HC_TEST_DBW) {
            dbw_disarm();
        }
        hcb_state = HCB_DONE;
    }
}

/* A DUE PULSE ENDS EVEN WHILE THE MAIN LOOP IS INSIDE A TUNERSTUDIO REPLY.
 *
 * MEASURED ON V76 WITH A LOGIC ANALYZER on cavity 65: a 3 x 500 ms bench pump
 * run gave 499.5 / 605.3 / 499.8 ms. The end of a pulse was only ever checked
 * by hcbench_service() in the main loop, and while hcts_tx() sends a long
 * reply (an OCH block is ~130 ms of K-line at 57600) the loop is not there.
 * The microsecond modes share the defect, so a 3 ms injector test pulse could
 * have come out as 100 ms under TunerStudio polling.
 *
 * hcts_target_yield() already runs once a millisecond inside every long
 * transmit, so it calls this. ONLY THE END IS DONE HERE: releasing is always
 * the safe direction, it needs no invariant to allow it, and starting a pulse
 * stays where every invariant is re-checked first. Same main-loop context as
 * hcbench_service(), never an interrupt, so nothing here can race it. */
void hcbench_yield_service(unsigned int tick_ms)
{
    if (hcb_state == HCB_RUNNING && run_mode == HC_TEST_DBW) {
        /* Recheck TPS/SF and the bounded pulse while serial owns the loop. */
        hcbench_service(tick_ms);
    } else if (hcb_state == HCB_RUNNING && pin_high) {
        pulse_end(tick_ms);
    }
}

void hcbench_service(unsigned int tick_ms)
{
    unsigned int moved;

    if (hcb_state != HCB_RUNNING) {
        return;
    }

    /* RE-CHECKED EVERY PASS. A crank edge, a page edit that invalidates the
       configuration, or the supervision link dropping all stop the run where
       it stands - including mid-pulse, which is the case that matters. */
    if (trg_rpm != 0u || trg_state != TRG_NO_SIGNAL) {
        hcbench_abort(HCB_A_CRANK);
        return;
    }
    if (hc_cfg_faults() != 0u) {
        hcbench_abort(HCB_A_CFG);
        return;
    }
    /* THE SUPERVISION LINK IS RE-CHECKED EVERY PASS, not only at the start.
       It was a start-only condition, which made it an invariant that had been
       true once - exactly what the header says an invariant is not. The S5500
       can reset this CPU; if the link stops while an output is energised, the
       honest response is to stop energising it. This is also the closest
       thing this firmware has to a session-loss detector: the host cannot be
       observed directly, but the run's own cap bounds that case and this
       bounds the platform's. */
    if (hc_asic_run_ok < HCB_ASIC_OK_MIN) {
        hcbench_abort(HCB_A_SUPERVISOR);
        return;
    }

    /* THE DBW GUARDS, RE-EVALUATED EVERY PASS AND BEFORE ANY TIMING. A
       runaway does not wait for the pulse timer to expire. */
    if (run_mode == HC_TEST_DBW) {
        if (!dbw_arm_seen) {
            dbw_arm_seen = 1u;
            dbw_arm_ms = tick_ms;
        }
        if (sf_faulted()
            && (unsigned int)(tick_ms - dbw_arm_ms) >= HCB_DBW_SF_SETTLE_MS) {
            hcbench_abort(HCB_A_SF);
            return;
        }
        if (hc_hal_ain_ok(HC_AIN_TPS1)) {
            hcb_tps_now = hc_hal_ain(HC_AIN_TPS1);
            moved = (unsigned int)((hcb_tps_now > hcb_tps_start)
                                   ? (hcb_tps_now - hcb_tps_start)
                                   : (hcb_tps_start - hcb_tps_now));
            if (moved > HCB_DBW_TPS_BAND) {
                hcbench_abort(HCB_A_TPSMOVE);
                return;
            }
        }
        if (tps_pair_bad()) {
            hcbench_abort(HCB_A_TPSPAIR);
            return;
        }
        /* NO PULSE UNTIL SF HAS BEEN JUDGED. The bridge sits enabled
           with both legs LOW - free-wheeling, nothing driven - until the
           settle has passed and the check above has seen a clean flag. The
           run cap below starts only after that, so the wait is not charged
           to the nudge. */
        if ((unsigned int)(tick_ms - dbw_arm_ms) < HCB_DBW_SF_SETTLE_MS) {
            return;
        }
    }

    if (run_t0 == 0u) {
        run_t0 = tick_ms ? tick_ms : 1u;
        run_mark = run_t0;
    }
    if ((unsigned int)(tick_ms - run_t0) > run_cap_ms) {
        hcbench_abort(HCB_A_TIMEOUT);
        return;
    }

    if (pin_high) {
        pulse_end(tick_ms);
        return;
    }

    if ((unsigned int)(tick_ms - run_mark) >= run_gap_ms) {
        pulse_t7 = T7;
        pulse_ms = tick_ms;
        pin_high = 1u;
        if (run_mode == HC_TEST_COIL || run_mode == HC_TEST_INJECTOR) {
            if (!hc_deadline_bench_start((unsigned char)(run_mode == HC_TEST_COIL ? HC_DL_BENCH_IGN : HC_DL_BENCH_INJ), run_ch, run_ticks)) hcbench_abort(HCB_A_TIMEOUT);
        } else drive(run_mode, run_ch, 1u);
    }
}
