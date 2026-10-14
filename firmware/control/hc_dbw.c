/*
 * hc_dbw.c - the closed-loop electronic throttle. Read hc_dbw.h first; the
 * ownership split and the safety rules are there and they are why this file
 * never names a pin.
 *
 * Fixed point throughout. No division by a runtime value that can be zero, no
 * loop whose bound is not a constant, no allocation, no floating point. The
 * whole control step is straight-line arithmetic plus two clamped table
 * lookups.
 *
 * UNITS, ONCE, HERE:
 *   position, target, error   0..1000 = 0.1 % of travel      (X10)
 *   duty                      0..1000 = 0.1 % of full duty   (X10)
 *   gains                     page units, scaled by GAIN_DIV below
 *   time                      milliseconds
 *
 * Nothing in this file assumes no C runtime initialisation is available -
 * because none is. hc_dbw_init() writes every static explicitly.
 */
#include "hctarget.h"
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hchal.h"
#include "hc_dbw.h"
#include "hcengine.h"
#if defined(TGT_ETBCAL_FAR)
#define dbw_cal_u16 hc_etbcal_u16
#define dbw_cal_u8(field) ((unsigned char)hc_etbcal_u16(field))
#include "hcfresh711.h"
#include "hcetbcal.h"         /* the target's far calibration module */
extern unsigned int hc_idle_floor_x10;   /* hcidle711.c (ME7.1.1) */
#else
#define dbw_cal_u16 hc_cal_u16
#define dbw_cal_u8 hc_cal_u8
#endif

/* V47 is deliberately a zero-output live-persistence qualification target.
 * Its caller has always passed armed=0, so retaining a complete PID, ADC
 * plausibility and bridge-control implementation only adds code that cannot
 * affect the qualification.  These explicit safe stubs preserve the public
 * diagnostics ABI and leave the bridge disabled.  Production-capable targets
 * compile the full controller below.
 *
 * TGT_DBW_CONTROLLER is the positive switch, for the same reason hcsched_dry.c
 * gives. The controller it restores contains no pin, no port and no sbit - it
 * computes a duty and a direction and nothing else - so restoring it cannot
 * move a throttle plate. Only hcbench.c can reach the bridge. */
#if !defined(TGT_DBW_CONTROLLER)
void hc_dbw_init(void) { }
unsigned char hc_dbw_due(unsigned int now) { return (unsigned char)(now & 0u); }
unsigned int hc_dbw_gap_max(void) { return 0u; }
void hc_dbw_calibration_begin(unsigned int now) { if (now) return; }
void hc_dbw_service(unsigned int now, unsigned int rpm, unsigned char armed)
{ if (now || rpm || armed) return; }
void hc_dbw_shutdown(unsigned int faults) { if (faults) return; }
unsigned char hc_dbw_state(void) { return 0u; }
unsigned int hc_dbw_faults(void) { return DBW_F_NOTLIVE; }
unsigned int hc_dbw_target_x10(void) { return 0u; }
unsigned int hc_dbw_actual_x10(void) { return 0u; }
int hc_dbw_error_x10(void) { return 0; }
unsigned int hc_dbw_duty_x10(void) { return 0u; }
unsigned char hc_dbw_dir(void) { return 0u; }
unsigned char hc_dbw_bridge_on(void) { return 0u; }
unsigned int hc_dbw_pedal_x10(void) { return 0u; }
unsigned int hc_dbw_app1_x10(void) { return 0u; }
unsigned int hc_dbw_app2_x10(void) { return 0u; }
unsigned int hc_dbw_tps1_x10(void) { return 0u; }
unsigned int hc_dbw_tps2_x10(void) { return 0u; }
int hc_dbw_integ(void) { return 0; }
unsigned int hc_dbw_steps(void) { return 0u; }
unsigned int hc_dbw_term(unsigned char i) { return (unsigned int)(i & 0u); }
void hc_dbw_clear_faults(void) { }
void hc_dbw_key(unsigned char k, unsigned int r) { if (k || r) return; }
void hc_dbw_override(unsigned int t) { if (t) return; }
unsigned int hc_dbw_normalise(unsigned int raw, unsigned int lo,
                              unsigned int hi, unsigned char *ok)
{ if (raw || lo || hi) { if (ok) *ok = 0u; return 0u; }
  if (ok) *ok = 0u; return 0u; }
void hc_dbw_drive(unsigned char dir, unsigned int duty) { if (dir || duty) return; }
unsigned char hc_dbw_gains(unsigned int a_x10, unsigned int tu_ms, unsigned int *k)
{ k[0] = (unsigned int)(a_x10 & 0u); k[1] = (unsigned int)(tu_ms & 0u); k[2] = 0u; return 1u; }

#else

/* ------------------------------------------------------------ the raster --
 *
 * FIXED, and NOT the main loop's rate. The loop runs at roughly 10 kHz here
 * and varies with whatever else it is doing; a gain tuned against it would
 * change whenever anything else changed. 5 ms is fast enough for a throttle
 * plate's mechanical bandwidth and slow enough that the derivative term is
 * not differentiating ADC noise. */
#define DBW_STEP_MS        5u
#define DBW_DEV_PROGRESS   2      /* 0.2 % per step = still converging */
/* HOW LONG DBW_INIT LASTS, in control steps. Four steps at DBW_STEP_MS is
 * 20 ms - long enough that a transient agreement between two tracks cannot
 * carry the controller into RUN, short enough to be invisible to a driver.
 *
 * IT IS A COUNT OF CONSECUTIVE GOOD PASSES, NOT A TIMER. A timer would let a
 * pair that agrees, disagrees, and agrees again arrive at RUN anyway; any
 * refusal resets this to zero, so the settle has to be clean throughout. */
#define DBW_INIT_PASSES    4u

/* Full travel, in the units above. */
#define DBW_FULL_X10    1000

/* THE GAIN DIVISOR. The page carries KP/KI/KD as plain 16-bit integers so a
   tuner types 120 rather than 0.12. duty_x10 = error_x10 * KP / GAIN_DIV, so
   KP = 1000 gives one duty unit per position unit. */
#define GAIN_DIV        1000L

/* THE INTEGRATOR'S HARD BOUND, compiled in. Anti-windup clamps to this
   whatever the gains are, so an integrator cannot store enough to slam a
   plate open when the error finally changes sign. Expressed in the same
   units as the duty it eventually becomes. */
#define INTEG_MAX      300L
/* 30 % OF FULL DUTY, WAS 200 %. rusEFI clamps its ETB integrator to
   etb_iTermMin/Max = -30/+30 % (electronic_throttle.cpp,
   setDefaultEtbParameters) - SOFTWARE REFERENCE IMPLEMENTATION. The spring is
   the bias curve's job; the integrator only removes what is left, and 200 %
   let it store twice the bridge's whole authority. */

/* How far outside its calibrated span a track may read before it is treated
   as broken rather than merely at an end stop. 10 % of the span. */
#define RANGE_MARGIN_X10  100

/* What a stored CAL_DBW_BIAS_VAL of this value means: zero feed-forward. The
   model declares that field with translate = -1000, and this constant is the
   firmware's half of that agreement. */
#define DBW_BIAS_ZERO     1000

/* A calibration span narrower than this cannot describe a real sensor, and
   dividing by it would turn ADC noise into full-scale position. */
#define MIN_SPAN_COUNTS    32u

/* BATTERY COMPENSATION. The bridge applies duty x Ubatt to the motor, so
   the same duty is 35 % less torque at 8.8 V (cranking) than at 13.5 V and
   every gain tuned at one voltage is wrong at the other. Bosch scales the DLR
   output by DLRUBSOLL / Ubatt (filtered) - 13.5 V in the AWT's own image
   (4B0906018DC, tools/an OEM-firmware analysis script (not published): DLRUBSOLL 13.52 V,
   ZKUBDLR filter; EXACT TARGET BINARY bytes, sibling-A2L meaning). rusEFI
   has no equivalent. The factor is bounded so a failed battery reading can
   neither remove the output nor double it past the page's authority. */
#define DBW_VNOM_DV       135u        /* 13.5 V                              */
#define DBW_VFAC_MIN      700u        /* x1000: above 19.3 V, no further cut */
#define DBW_VFAC_MAX     1800u        /* below 7.5 V, no further boost       */
#define DBW_SENSOR_BITS  (DBW_F_APP_RANGE | DBW_F_APP_PAIR | DBW_F_TPS_RANGE                           | DBW_F_TPS_PAIR)

/* --------------------------------------------------------------- state ---
 *
 * IN THE EXTERNAL SRAM, NOT IN NEAR RAM. near_ram_hazard_proof reported 153
 * bytes free against its 192-byte engineering reserve the moment this module
 * landed, and the project's standing rule is that cold data goes to far memory.
 * This controller runs on a 5 ms raster; it is not the tooth path. The region
 * is declared ONCE in hctarget.h as TGT_RAM_DBW, like every other region of
 * that chip - see feedback_one_place_for_shared_layout.
 *
 * One struct rather than a scatter of pointers: the compiler then addresses
 * every field from one base, which costs less than 38 separate far accesses
 * would.
 */
#include "hc_dbw_state.h"

/* ------------------------------------------------------------ helpers ---- */
static int clampi(long v, long lo, long hi)
{
    if (v < lo) {
        return (int)lo;
    }
    if (v > hi) {
        return (int)hi;
    }
    return (int)v;
}

unsigned int hc_dbw_normalise(unsigned int raw, unsigned int lo,
                              unsigned int hi, unsigned char *ok)
{
    long span, v;

    *ok = 0u;
    /* `lo` IS THE CLOSED/RELEASED READING AND `hi` THE OPEN/FLOORED ONE,
     * AND EITHER MAY BE THE LARGER. That is rusEFI's model (tpsMin 890,
     * tpsMax 70 in setBoschVAGETB) and it is what the endpoint grab has always
     * stored - "MIN IS THE CLOSED READING AND MAX THE OPEN ONE, WITHOUT
     * SORTING" (me711_calib_grab_proof). This function refused hi <= lo, so a
     * grabbed VAG throttle, whose track 1 FALLS as the plate opens, could
     * never leave DBW_F_CFG. Now every track reads 0 closed and 1000 open
     * whichever way its voltage runs, and a pair calibrated by the grab is
     * compared SAME. Only a span too narrow to be a sensor is refused. */
    /* THE DIVISOR IS ALWAYS POSITIVE. A falling track swaps the operands
       instead of dividing by a negative span: me711_dbw_control_proof caught
       (660 - 900) * 1000 / -800 coming out 0, and a signed long division by a
       negative divisor is not a case this firmware needs to trust. */
    if (hi >= lo) {
        span = (long)hi - (long)lo;
        v = (long)raw - (long)lo;
    } else {
        span = (long)lo - (long)hi;
        v = (long)lo - (long)raw;
    }
    if (span < (long)MIN_SPAN_COUNTS) {
        return 0u;
    }
    v = v * (long)DBW_FULL_X10 / span;
    if (v < -(long)RANGE_MARGIN_X10
        || v > (long)(DBW_FULL_X10 + RANGE_MARGIN_X10)) {
        return (unsigned int)clampi(v, 0, DBW_FULL_X10);
    }
    *ok = 1u;
    return (unsigned int)clampi(v, 0, DBW_FULL_X10);
}

/* Do two normalised tracks agree, under the CONFIGURED relationship?
 *
 * The relationship is configured and never assumed: HC_TRACK_OPPOSITE is true
 * of the ME7.5 pair and is not a law. SCALED cannot be checked from two
 * normalised values alone once each has been through its own calibration -
 * after normalisation a correctly scaled pair reads the same - so SCALED is
 * checked as SAME, which is exactly right and not a concession. */
#if defined(TGT_ETBCAL_FAR)
#define pair_bad hc_etbcal_pair_bad
#else
static unsigned char pair_bad(unsigned int a, unsigned int b,
                              unsigned char corr, unsigned int tol_x10)
{
    long d;

    if (corr == HC_TRACK_OPPOSITE) {
        d = (long)a + (long)b - (long)DBW_FULL_X10;
    } else {
        d = (long)a - (long)b;
    }
    if (d < 0) {
        d = -d;
    }
    return (unsigned char)(d > (long)tol_x10);
}

#endif

/* Everything that must be true of the page before a motor may turn. Checked
   on EVERY step, not once: a tuner can edit these live. */
#if defined(TGT_ETBCAL_FAR)
static unsigned int cfg_bad(void)
{ return hc_etbcal_config_faults((unsigned char)(D.ovr != 0xFFFFu)); }
#else
static unsigned char span_bad(unsigned int a, unsigned int b)
{
    unsigned int d = (a > b) ? (unsigned int)(a - b) : (unsigned int)(b - a);
    return (unsigned char)(a < 10u || a > 1013u || b < 10u || b > 1013u
                           || d < MIN_SPAN_COUNTS);
}

static unsigned int cfg_bad(void)
{
    unsigned int lo, hi;

    /* direction is allowed, a missing span is not - hc_dbw_normalise(). */
    if ((D.ovr == 0xFFFFu
         && (span_bad(hc_cal_u16(CAL_PEDAL1_MIN), hc_cal_u16(CAL_PEDAL1_MAX))
             || span_bad(hc_cal_u16(CAL_PEDAL2_MIN), hc_cal_u16(CAL_PEDAL2_MAX))))
        || span_bad(dbw_cal_u16(CAL_TPS1_MIN), dbw_cal_u16(CAL_TPS1_MAX))
        || span_bad(dbw_cal_u16(CAL_TPS2_MIN), dbw_cal_u16(CAL_TPS2_MAX))) {
        return DBW_F_CFG;
    }
    if (dbw_cal_u8(CFG_U_TPS_CORR) > HC_TRACK_SCALED
        || (! (D.ovr != 0xFFFFu) && hc_cal_u8(CFG_U_APP_CORR) > HC_TRACK_SCALED))
        return DBW_F_CFG;
    lo = hc_cal_u16(CAL_DBW_MIN_X10);
    hi = hc_cal_u16(CAL_DBW_MAX_X10);
    if (hi <= lo || hi > (unsigned int)DBW_FULL_X10) {
        return DBW_F_CFG;
    }
    if (hc_cal_u16(CFG_U_DBW_MAX_DUTY_X10) == 0u
        || hc_cal_u16(CFG_U_DBW_MAX_DUTY_X10) > (unsigned int)DBW_FULL_X10) {
        return DBW_F_CFG;
    }
    return 0u;
}

#endif

/* One place drives the bridge, and it is the only place. */
static void apply(unsigned char on, unsigned char dir, unsigned int duty)
{
    D.on = on;
    D.dir = dir;
    D.duty = duty;
    /* From this point the CONTROLLER owns the bridge and hc_dbw_shutdown()
       must release it. Set before the writes, not after: a reset between the
       two would otherwise leave a driven bridge nobody believes they hold. */
    D.held = 1u;
#if defined(TGT_DBW_MOTOR_PRIMITIVE)
    hc_hal_dbw_motor(on, dir, duty);
#else
    hc_hal_out(HC_OUT_THR_EN, on);
    hc_hal_out(HC_OUT_THR_DIR, dir);
    hc_hal_out_duty(HC_OUT_THR_PWM, duty);
#endif
}

void hc_dbw_shutdown(unsigned int fault_bits)
{
    /* RELEASE WHAT WE HOLD, AND DO NOT TOUCH WHAT WE DO NOT - the project rules
     * 12O/9a.
     *
     * hc_dbw_service() calls this on EVERY main-loop pass while `armed` is 0,
     * which on this build is always: hcmain_me711.c passes armed = 0 and only
     * the bench qualifier may pass 1. Unguarded, that re-drove the bridge pins
     * from the HAL a few hundred times a second - so a bounded bench command
     * could complete, put EGENFR back to high impedance in its own
     * dbw_disarm(), and have the very next pass of an UNARMED controller
     * take the pins back. That is the ownership defect; the HAL leaving them
     * driven rather than released was the second half of it.
     *
     * THE SAFETY PATH IS STILL UNCONDITIONAL. `fault_bits` means something has
     * gone wrong and the bridge must be forced down whoever believes they own
     * it, so the release runs then regardless of D.held. What is suppressed is
     * only the idle case: an unarmed controller that has never driven anything
     * and has nothing to release.
     *
     * D.held LIVES IN EXTERNAL SRAM AND STARTS UNKNOWN - this startup runs no
     * ?C_INIT - so hc_dbw_init() forces it to 1 before calling here, which
     * makes the boot release unconditional and stops a stale byte convincing
     * this function that a driven bridge is somebody else's problem. */
    if (D.held || fault_bits) {
#if defined(TGT_DBW_MOTOR_PRIMITIVE)
        hc_hal_dbw_motor(0u, 0u, 0u);
#else
        /* ORDER MATTERS. Duty to zero before the enable drops, so the bridge
           is never disabled while a leg is still being asked to conduct. */
        hc_hal_out_duty(HC_OUT_THR_PWM, 0u);
        hc_hal_out(HC_OUT_THR_EN, 0u);
        hc_hal_out(HC_OUT_THR_DIR, 0u);
#endif
        D.held = 0u;
    }
    D.duty = 0u;
    D.on = 0u;
    D.dir = 0u;
    /* ZEROED, NOT FROZEN. An integrator that kept its charge while the bridge
       was down would hand the motor a step the moment it came back. */
    D.integ = 0L;
    D.irem = 0L;
    D.prev_act = 0;
    D.err = 0;
    /* AND THE SETTLE RESTARTS. Every refusal in hc_dbw_service() returns
       through here, so clearing it is what makes DBW_INIT require
       DBW_INIT_PASSES CONSECUTIVE clean passes rather than that many good
       passes eventually. A pair that agrees, disagrees and agrees again goes
       back to the start of the settle - which is the whole reason the state
       is a count and not a timer. */
    D.settle = 0u;
    D.dev_pending = 0u; D.dev_since = 0u; D.dev_e = 0;
    D.tgt_ramped = D.act;
    D.p_t = 0; D.d_t = 0; D.ff_t = 0; D.out_t = 0;
    if (fault_bits) {
        D.flt |= fault_bits;
        D.st = DBW_FAULT;
    }
}

/* THE BRIDGE, LENT. hcetbcal.c (far, through a thunk) drives the plate
   with this while a calibration or autotune owns the raster; it is apply()
   with the enable asserted, so D.held is set and hc_dbw_shutdown() releases
   it on every exit exactly as it releases the closed loop. */
/* All authorities are specified at 13.5 V. The fresh routed ADC is used
   directly: eng_batt_dv substitutes 12 V on error and cannot qualify drive.
   No owner may apply compensation again after this point. The configured
   duty ceiling is a PHYSICAL PWM ceiling, including compensation. */
void hc_dbw_drive(unsigned char dir, unsigned int duty)
{
    unsigned long batt, fac = 1000uL, scaled;
    unsigned int maxd = hc_cal_u16(CFG_U_DBW_MAX_DUTY_X10);
    if (D.flt & (DBW_F_TPS_RANGE | DBW_F_TPS_PAIR | DBW_F_SF
                 | DBW_F_DEV | DBW_F_STALE | DBW_F_VBAT)) {
        hc_dbw_shutdown(0u);
        return;
    }
    if (maxd == 0u || maxd > 1000u) {
        hc_dbw_shutdown(DBW_F_CFG);
        return;
    }
    if (!hc_hal_ain_ok(HC_AIN_VBAT)) {
        hc_dbw_shutdown(DBW_F_VBAT);
        return;
    }
    batt = (unsigned long)hc_hal_ain(HC_AIN_VBAT)
           * (unsigned long)cfg_u16(CFG_ADC_BATT_FS_DV) / 1023uL;
    /* Same plausible measurement range as hcengine, without its fallback.
       BELOW IT IS A STATE, NOT A FAULT (2026-10-11 car: KL15 off with the
       engine turning latched DBW_F_VBAT). The bridge is not driven; the
       Bosch DLR likewise only suspends its monitoring (FR B_ubdve). */
    if (batt < 40uL) {
        hc_dbw_shutdown(0u);
        return;
    }
    if (batt > 200uL) {
        hc_dbw_shutdown(DBW_F_VBAT);
        return;
    }
    if (hc_cal_u8(CFG_U_DBW_BATT_COMP) == 0u) {
        fac = 135000uL / batt;
        if (fac < DBW_VFAC_MIN) fac = DBW_VFAC_MIN;
        if (fac > DBW_VFAC_MAX) fac = DBW_VFAC_MAX;
    }
    D.vfac = (unsigned int)fac;
    if (duty > 1000u) duty = 1000u;
    scaled = (unsigned long)duty * fac / 1000uL;
    if (scaled > maxd) scaled = maxd;
    apply(1u, dir, (unsigned int)scaled);
}

/* Reset transient control ownership/history, never clear a latched fault.
   Both PID entry paths call this through the same ETB start() function. */
void hc_dbw_calibration_begin(unsigned int now_ms)
{
    hc_dbw_override(0xFFFFu);
    hc_dbw_shutdown(0u);
    D.step_mark = now_ms; D.pend = 0u;
    D.st = (D.flt & (unsigned int)~(DBW_F_APP_PAIR | DBW_F_APP_RANGE))
           ? DBW_FAULT : DBW_OFF;
}

/* THE RELAY AUTOTUNE's GAINS, rusEFI EtbController::
   getClosedLoopAutotune(): Ku = 4 b / (pi a), b = 40 % the relay's peak to
   peak, Kp = 0.35 Ku, Ki = 0.25 Ku / Tu, Kd = 0.08 Ku Tu. In page units
   (duty and position 0.1 %, GAIN_DIV 1000, the 5 ms raster):
       KP = 178254 / a_x10      KI = 127323954 / (a_x10 Tu_ms)
       KD = 8149 Tu_ms / a_x10
   rusEFI's own VAG gains 5.12/47/0.088 are a = 3.5 %, Tu = 77 ms here.
   NCODE because it is the one piece of 32-bit arithmetic hcetbcal.c needs
   and far code may not call Keil's near long helpers. The relay amplitude b
   is the page's dbwTuneAmp: the constants scale with it. Returns a mask of
   the gains clipped to the 16-bit page field (bit 0 KP, 1 KI, 2 KD): a
   lower gain is the conservative direction, and the caller says so. */
unsigned char hc_dbw_gains(unsigned int a_x10, unsigned int tu_ms, unsigned int *k)
{
    unsigned long v, amp;
    unsigned char clip = 0u;

    if (a_x10 == 0u) a_x10 = 1u;
    if (tu_ms == 0u) tu_ms = 1u;
    amp = (unsigned long)hc_cal_u16(CAL_DBW_TUNE_AMP);
    if (amp < 50uL || amp > 300uL) amp = 200uL;
    v = (178254uL * amp / 200uL) / (unsigned long)a_x10;
    if (v > 65535uL) { v = 65535uL; clip |= 1u; }
    k[0] = (unsigned int)v;
    v = (127323954uL / 200uL * amp) / ((unsigned long)a_x10 * tu_ms);
    if (v > 65535uL) { v = 65535uL; clip |= 2u; }
    k[1] = (unsigned int)v;
    v = ((8149uL * amp / 200uL) * (unsigned long)tu_ms) / (unsigned long)a_x10;
    if (v > 65535uL) { v = 65535uL; clip |= 4u; }
    k[2] = (unsigned int)v;
    return clip;
}

/* Startup ordering can expose the ASIC link before the ADC has acquired all
 * tracks. Keep the bridge off while collecting the initial samples, with a
 * bounded window. After readiness, sensor loss latches immediately under the
 * ordinary freshness rule; it cannot reopen the startup window. */
#define DBW_READY_MS 1000u
static unsigned char not_ready(unsigned int now_ms)
{
    if (D.ready == 2u) return 0u;
    if (D.ready != 1u) {
        D.ready = 1u;
        D.ready_since = now_ms;
    }
    return (unsigned char)((unsigned int)(now_ms - D.ready_since) < DBW_READY_MS);
}

#if defined(TGT_ETBCAL_FAR)
void hc_dbw_init(void)
{
    hc_etbcal_dbw_init();          /* cold: FCODE (hcetbcal.c) */
}
#else
void hc_dbw_init(void)
{
    D.st = DBW_OFF;
    D.ready = 0u; D.ready_since = 0u; D.gap_max = 0u;
    D.flt = 0u;
    D.tgt = 0u; D.act = 0u; D.duty = 0u; D.pedal = 0u;
    D.a1 = 0u; D.a2 = 0u; D.t1 = 0u; D.t2 = 0u;
    D.err = 0; D.dir = 0u; D.on = 0u;
    D.integ = 0L; D.irem = 0L; D.prev_act = 0;
    D.step_mark = 0u; D.dev_since = 0u; D.dev_pending = 0u; D.dev_e = 0;
    D.steps = 0u; D.tgt_ramped = 0u; D.settle = 0u;
    D.p_t = 0; D.d_t = 0; D.ff_t = 0; D.out_t = 0; D.vfac = 1000u;
    D.pend = 0u; D.pend_since = 0u; D.ovr = 0xFFFFu; D.clears = 0u; D.requested = 0u;
    D.busy = 0u; D.align_pending = 0u; D.align_since = 0u;
    D.key = 1u;        /* a boot is not a key-on edge: nothing to clear */
    /* FORCE ONE UNCONDITIONAL RELEASE. D is in external SRAM with no ?C_INIT,
       so `held` starts at whatever the last power cycle left; claiming it here
       makes the release below happen whatever that byte says. */
    D.held = 1u;
    hc_dbw_shutdown(0u);
    D.st = DBW_OFF;
    D.flt = 0u;
}
#endif


void hc_dbw_clear_faults(void)
{
    /* The bridge is already down in DBW_FAULT (every entry to it ran
       hc_dbw_shutdown()); the settle restarts from zero. */
    if (D.st == DBW_FAULT) {
        D.st = DBW_OFF;
    }
    D.flt = 0u;
    D.pend = 0u;
    D.settle = 0u;
    D.ready = 0u;                  /* a new driving cycle: a new window */
#if defined(TGT_ETBCAL_FAR)
    hc_etbcal_dlr_reset();
#endif
    if (D.clears != 0xFFFFu) {
        D.clears++;
    }
}

void hc_dbw_key(unsigned char key_on, unsigned int rpm)
{
    if (key_on && !D.key && rpm == 0u) {
        hc_dbw_clear_faults();
    }
    D.key = key_on;
}

void hc_dbw_override(unsigned int target_x10)
{
    D.ovr = target_x10;
    /* Pedal faults remain latched throughout pedal-independent commissioning.
       Handing its target back must restore their normal motor refusal. */
    if (target_x10 == 0xFFFFu && (D.flt & (unsigned int)~DBW_F_CFG))
        D.st = DBW_FAULT;
}

/* Sensor debounce confirms the latch only. The bridge disables on the
   first suspect pair and requires clean INIT passes before recovery. */
static void sensor_fault(unsigned int bits, unsigned int now_ms)
{
    unsigned int db = hc_cal_u16(CFG_U_DBW_FAULT_DEBOUNCE_MS);

    if (D.pend == 0u) {
        D.pend_since = now_ms;
    }
    D.pend |= bits;
    if (db == 0u || (unsigned int)(now_ms - D.pend_since) >= db) {
        bits = D.pend;
        D.pend = 0u;
        hc_dbw_shutdown(bits);
        return;
    }
    /* Confirm-time debounces the LATCH, never motor permission. */
    hc_dbw_shutdown(0u);
    D.st = DBW_INIT;
}

static void dbw_step(unsigned int now_ms, unsigned int rpm, unsigned char armed)
{
    unsigned int f, tol, lo, hi, want, maxd, rate, dead, sb;
    unsigned int raw1, raw2, pair_ms;
    unsigned char ok1, ok2, corr, sf, entry, ovr;
    long p, i, d, out, mag;
    int err, step;

    /* THE ETB CALIBRATION / AUTOTUNE (V93: hcetbcal.c, FCODE). A request
       starts it unless the closed loop is running; while it runs it owns the
       bridge and nothing below executes - no pedal, no dbwEnable, no pair
       check on uncalibrated tracks. A latched controller fault does not block
       it from reading/calculating candidates, but drive always rejects serious
       latched faults. Calibration never clears those faults. */
#if defined(TGT_ETBCAL_FAR)
    if (hc_etbcal_service(now_ms, rpm, armed,
                          (unsigned char)(D.st == DBW_RUN))) {
        D.step_mark = now_ms;
        return;
    }
#endif

    /* A LATCHED FAULT IS FINAL until hc_dbw_init(). Checked first so no later
       path can talk itself out of it. */
    if (D.st == DBW_FAULT) {
        if (D.ovr != 0xFFFFu
            && !(D.flt & (unsigned int)~(DBW_F_APP_PAIR | DBW_F_APP_RANGE))) {
            /* Private stopped-engine verify target does not use a pedal. */
            D.st = DBW_INIT;
        } else {
            hc_dbw_shutdown(0u);
            return;
        }
    }

    /* The three unconditional refusals. Each drops the bridge immediately and
       none of them latches a fault - they are states, not failures. */
    /* the commissioning VERIFY step runs the closed loop with dbwEnable
       still 0 (a tuner decides that after seeing the result). */
    ovr = (unsigned char)(D.ovr != 0xFFFFu);
    if (!armed || (hc_cal_u8(CAL_DBW_ENABLE) != 1u && !ovr)) {
        D.st = DBW_OFF;
        hc_dbw_shutdown(0u);
        return;
    }
    if (!hc_hal_outputs_live()) {
        /* Defence in depth: the HAL already refuses. Reported so a bench can
           tell "not built to drive" from "refused to drive". */
        D.st = DBW_OFF;
        D.flt |= DBW_F_NOTLIVE;
        hc_dbw_shutdown(0u);
        return;
    }

    /* THE RASTER. Everything below runs at DBW_STEP_MS and not at whatever
       rate the caller happens to have. */
    if (D.steps != 0u
        && (unsigned int)(now_ms - D.step_mark) < DBW_STEP_MS) {
        return;
    }
    if (D.steps != 0u && D.st == DBW_RUN
        && (unsigned int)(now_ms - D.step_mark) > D.gap_max) {
        D.gap_max = (unsigned int)(now_ms - D.step_mark);
    }
    /* THE REAL TIME SINCE THE LAST STEP, for the timers below: a step runs
       on the first main-loop pass >= DBW_STEP_MS after the last one, so the
       period is 5..10 ms on the car and counting a fixed 5 ms stretched the
       Bosch DLR times by up to 2x (2026-10-12). Bounded to 4 steps. */
    D.step_dt = (unsigned int)(now_ms - D.step_mark);
    if (D.steps == 0u || D.step_dt < DBW_STEP_MS) {
        D.step_dt = DBW_STEP_MS;
    } else if (D.step_dt > 4u * DBW_STEP_MS) {
        D.step_dt = 4u * DBW_STEP_MS;
    }
    D.step_mark = now_ms;
    if (D.steps != 0xFFFFu) {
        D.steps++;
    }

    /* A LIVE REFUSAL, NOT A LATCH. A page that does not describe a
       throttle yet (a span, a limit, a duty ceiling) is a state the tuner is
       in the middle of fixing - latching it meant a reboot after the very
       calibration run that fixed it. The bit reads while it is true. */
    f = cfg_bad();
    if (f) {
        D.st = DBW_OFF;
        D.flt |= f;
        hc_dbw_shutdown(0u);
        return;
    }
    D.flt &= (unsigned int)~DBW_F_CFG;

    /* ---------------------------------------------------- the sensors ---- */
    if ((!ovr && (!hc_hal_ain_ok(HC_AIN_APP1) || !hc_hal_ain_ok(HC_AIN_APP2)))
        || !hc_hal_ain_ok(HC_AIN_TPS1) || !hc_hal_ain_ok(HC_AIN_TPS2)) {
        /* No backing source is not a sensor fault - it is a board that does
           not have that input wired. Either way a motor must not turn. */
        if (not_ready(now_ms)) {
            hc_dbw_shutdown(0u);
            D.st = DBW_INIT;
            return;
        }
        hc_dbw_shutdown(DBW_F_STALE);
        return;
    }

    sb = 0u;
#if defined(TGT_ETBCAL_FAR)
    sb = hc_etbcal_rail_faults(ovr);
    if (sb) { hc_dbw_shutdown(sb); return; }
#endif
    raw1 = hc_hal_ain(HC_AIN_APP1);
    raw2 = hc_hal_ain(HC_AIN_APP2);
#if defined(TGT_ETBCAL_FAR)
    /* The pair is read at ONE sample time (hcfresh711.c: one track can be
       15 ms older; a fast press then read as a disagreement and dropped
       the bridge). The target follows the same aligned pedal 1, at most
       15 ms behind its newest sample for 1 ms in 16. */
    hc_fresh_app_pair(&raw1, &raw2);
#endif
    D.a1 = hc_dbw_normalise(raw1, hc_cal_u16(CAL_PEDAL1_MIN),
                              hc_cal_u16(CAL_PEDAL1_MAX), &ok1);
    D.a2 = hc_dbw_normalise(raw2, hc_cal_u16(CAL_PEDAL2_MIN),
                              hc_cal_u16(CAL_PEDAL2_MAX), &ok2);
    /* The pedal is not consulted while the commissioning verify owns the
       target - it runs with the pedal released or not fitted at all. */
    if (!ovr) {
        if (!ok1 || !ok2) {
            sb |= DBW_F_APP_RANGE;
        } else {
            corr = hc_cal_u8(CFG_U_APP_CORR);
            tol = hc_cal_u16(CFG_U_APP_TOL_X10);
            if (pair_bad(D.a1, D.a2, corr, tol)) {
                sb |= DBW_F_APP_PAIR;
            }
        }
    }

#if defined(TGT_ETBCAL_FAR)
    if (!hc_fresh_tps_pair(&raw1, &raw2, &pair_ms)) {
        /* An initial staggered scan has no common bracket yet. Keep the
           motor OFF while collecting it; this is not track disagreement.
           Bound that wait by the unchanged sample freshness deadline. */
        if (!D.align_pending) { D.align_pending = 1u; D.align_since = now_ms; }
        hc_dbw_shutdown(0u);
        if (!not_ready(now_ms)
            && (unsigned int)(now_ms - D.align_since) > 100u)
            hc_dbw_shutdown(DBW_F_STALE);
        else D.st = DBW_INIT;
        return;
    }
    D.align_pending = 0u;
    D.ready = 2u;                  /* every track fresh and paired: ready */
#else
    raw1 = hc_hal_ain(HC_AIN_TPS1); raw2 = hc_hal_ain(HC_AIN_TPS2);
#endif
    D.t1 = hc_dbw_normalise(raw1,
                              dbw_cal_u16(CAL_TPS1_MIN),
                              dbw_cal_u16(CAL_TPS1_MAX), &ok1);
    D.t2 = hc_dbw_normalise(raw2,
                              dbw_cal_u16(CAL_TPS2_MIN),
                              dbw_cal_u16(CAL_TPS2_MAX), &ok2);
    if (!ok1 || !ok2) {
        sb |= DBW_F_TPS_RANGE;
    } else {
        corr = dbw_cal_u8(CFG_U_TPS_CORR);
        tol = hc_cal_u16(CFG_U_TPS_TOL_X10);
        if (pair_bad(D.t1, D.t2, corr, tol)) {
            sb |= DBW_F_TPS_PAIR;
        }
    }
    if (sb != 0u) {
        sensor_fault(sb, now_ms);
        return;
    }
    D.pend = 0u;

    /* THE BRIDGE'S OWN OPINION, and it outranks ours - BUT ONLY WHILE WE
       HAVE IT ENABLED. V83: a CJ220 whose DI is inactive reports SF LOW by
       design (truth table rows 5, 6, 9), so reading SF in DBW_INIT - bridge
       down, as INIT requires - latched DBW_F_SF on every correctly working
       board before the first enable. It is judged from the step AFTER a step
       that enabled the bridge (D.on), which is DBW_STEP_MS later: far longer
       than the part needs to release the flag. */
    /* bit 0: read with the stage ON (a disabled CJ220 reads LOW by design),
       bit 1: the flag says faulted. */
    sf = (unsigned char)(D.on ? (hc_hal_dbw_sf_faulted() ? 3u : 1u) : 0u);
#if !defined(TGT_ETBCAL_FAR)
    if (sf & 2u) {
        hc_dbw_shutdown(DBW_F_SF);
        return;
    }
#endif

    /* ============================ DBW_INIT ==============================
     *
     * EVERY CHECK ABOVE HAS NOW PASSED ON THIS PASS, AND UNTIL V73 THAT WAS
     * ENOUGH TO COMMAND THE MOTOR. `DBW_INIT` was defined in hc_dbw.h from the
     * day the module was written, the TunerStudio `.ini` has always decoded
     * dbwState as "0 OFF 1 INIT 2 RUN 3 FAULT", and **nothing ever assigned
     * it**: the controller went OFF -> RUN, and the first serviced pass that
     * saw plausible sensors computed a duty and drove the bridge.
     *
     * That is a state the UI claimed and the firmware did not have - the same
     * family as the dead calibration knobs 12Q captioned, and worse, because
     * this one is about when a throttle motor is allowed to move.
     *
     * WHAT INIT IS: the bridge stays DOWN while the sensors are watched for
     * DBW_INIT_PASSES consecutive clean passes. A transient agreement cannot
     * carry the controller into RUN, because every refusal above returns
     * through hc_dbw_shutdown(), and the reset below is what makes the settle
     * have to be clean throughout rather than merely eventually.
     *
     * WHY THE SHUTDOWN CALL HERE IS NOT A REGRESSION OF 12P. V66 made
     * hc_dbw_shutdown() release only what the controller HOLDS, so on the
     * second and later INIT passes this is a no-op: nothing is held, no port
     * is touched, and an unarmed or settling controller still cannot re-assert
     * EGENFR after a bounded bench command. The first pass after a fault or a
     * bench command is the one that actually releases, which is the point.
     *
     * NO FAULT IS LATCHED. INIT is a state, not a failure - exactly like
     * DBW_OFF above it. */
    if (D.settle < DBW_INIT_PASSES) {
        /* THE COUNT IS CARRIED ACROSS THE RELEASE ON PURPOSE.
         *
         * hc_dbw_shutdown() clears D.settle, because every REFUSAL above
         * returns through it and a refusal has to restart the settle. This
         * path is not a refusal - it is the settle itself - so the pass is
         * counted after the release rather than before it. Incrementing first
         * pinned the counter at 1 for ever and the controller never left
         * DBW_INIT, which me711_dbw_init_proof caught on its first run.
         *
         * The release still happens, and it still obeys 12P: shutdown only
         * touches a port when the controller HOLDS the bridge, so the first
         * INIT pass after a fault or a bounded bench command releases and
         * every pass after that touches nothing. */
        unsigned char counted = (unsigned char)(D.settle + 1u);
        hc_dbw_shutdown(0u);
        D.settle = counted;
        D.st = DBW_INIT;
        return;
    }

    /* ------------------------------------------- demand -> target -------- */
    /* Track 1 is the authority once the pair has agreed. Averaging two tracks
       that already agree buys nothing and hides which one moved. */
    D.pedal = (ovr && (D.ovr & 0x8000u)) ? (D.ovr & 0x03FFu) : D.a1;
    if (ovr && !(D.ovr & 0x8000u)) {
        want = D.ovr;
    } else {
    want = (unsigned int)hc_cal_map(CAL_PEDAL_MAP, CAL_PEDAL_RPM_AX,
                                    CAL_PEDAL_AX, rpm, D.pedal);
    /* THE MAP'S SCALE IS 0.5 % PER COUNT, not 1. The model declares
       CAL_PEDAL_MAP with scale 0.5, so a stored byte of 200 is 100 % - which
       is what lets a 0..255 byte reach full travel with resolution to spare.
       This multiplied by 10 at first, on the assumption of 1 %/count, and
       every demand came out doubled and then clamped at full travel.
       me711_dbw_control_proof caught it. 0.1 % units = raw * 5. */
    want = (unsigned int)((unsigned long)want * 5uL);
    /* IDLE. The idle speed controller (hcidle711.c) publishes a
       throttle floor - base by coolant + a bounded rpm trim, 0 when idle
       control is off - and the demand never goes below it.
       V98 (ME7.1.1): OR rusEFI's compression (getSetpointEtb): with
       etbIdleRange set, the idle position is the bottom of the pedal map's
       range - target = idle + map x (100 % - idle) - so the first
       millimetre of pedal already opens the throttle (no dead zone).
       And rusEFI's ETB rev limiter: above dbwRevlimRpm the target tapers
       to closed across dbwRevlimRange. */
#if defined(TGT_ENGINE_RUNTIME)
    {
        unsigned char rng = hc_cal_u8(CFG_U_IDLE_ETB_RANGE);
        unsigned int r0 = hc_cal_u16(CAL_DBW_REVLIM_RPM);
        unsigned int rr = hc_cal_u16(CAL_DBW_REVLIM_RANGE);
        if (rng != 0u) {
            unsigned int add = (unsigned int)(((unsigned long)hc_idle_floor_x10
                                               * rng) / 100uL);
            if (add > 1000u) add = 1000u;
            want = (unsigned int)(add + (unsigned int)(((unsigned long)want
                                   * (1000u - add)) / 1000uL));
        } else if (want < hc_idle_floor_x10) {
            want = hc_idle_floor_x10;
        }
        if (r0 != 0u && rpm > r0) {
            unsigned int over = (unsigned int)(rpm - r0);
            want = (rr == 0u || over >= rr) ? 0u
                 : (unsigned int)(((unsigned long)want * (rr - over)) / rr);
        }
    }
#else
    if (want < hc_idle_floor_x10) {
        want = hc_idle_floor_x10;
    }
#endif
    }

    lo = hc_cal_u16(CAL_DBW_MIN_X10);
    hi = hc_cal_u16(CAL_DBW_MAX_X10);
    if (want < lo) {
        want = lo;
    }
    if (want > hi) {
        want = hi;
    }

    /* THE RATE LIMIT bounds how violently a pedal step reaches the
       controller. 0 disables it, which is a deliberate configuration and not
       an accident: the authority clamp still applies. */
    rate = hc_cal_u16(CFG_U_DBW_RATE_X10);
    /* THE FIRST RUN STEP STARTS FROM WHERE THE PLATE IS. This used to be
       `if (D.steps <= 1u) D.tgt_ramped = D.act;` - but D.steps counts every
       raster step, INIT's four included, so by the first RUN step it was at
       least 5 and the seed never ran: the rate limiter ramped from 0 (or from
       whatever an earlier RUN left) instead of from the plate. Every entry
       into RUN - after OFF, INIT or a bench command - now seeds from the
       tracked position, D.t1, which this pass has already validated. */
    entry = (unsigned char)(D.st != DBW_RUN);
    if (entry) {
        D.tgt_ramped = D.t1;
    }
    D.requested = want;
    if (rate != 0u && (!ovr || (D.ovr & 0x8000u))) {
        step = (int)(((unsigned long)rate * (unsigned long)DBW_STEP_MS)
                     / 1000uL);
        if (step < 1) {
            step = 1;
        }
        if ((long)want > (long)D.tgt_ramped + step) {
            D.tgt_ramped = (unsigned int)((long)D.tgt_ramped + step);
        } else if ((long)want < (long)D.tgt_ramped - step) {
            D.tgt_ramped = (unsigned int)((long)D.tgt_ramped - step);
        } else {
            D.tgt_ramped = want;
        }
    } else {
        D.tgt_ramped = want;
    }
    D.tgt = D.tgt_ramped;

    /* ------------------------------------------------------- the loop ---- */
    D.act = D.t1;
    err = (int)((long)D.tgt - (long)D.act);

    dead = hc_cal_u16(CFG_U_DBW_DEADBAND_X10);
    if (err <= (int)dead && err >= -(int)dead) {
        err = 0;
    }
    D.err = err;
    /* Differentiate the measured plate, so a new target cannot produce a
       fictitious velocity and a full-authority motor kick. Seed on entry. */
#if !defined(TGT_ETBCAL_FAR)
    if (entry) {
        D.prev_act = (int)D.act;
    }
#endif

#if defined(TGT_ETBCAL_FAR)
    d = hc_etbcal_derivative(pair_ms, entry, dbw_cal_u16(CAL_DBW_KD));
#else
    d = (long)(D.prev_act - (int)D.act) * (long)dbw_cal_u16(CAL_DBW_KD)
        / GAIN_DIV;
    D.prev_act = (int)D.act;
#endif

    p = (long)err * (long)dbw_cal_u16(CAL_DBW_KP) / GAIN_DIV;

    /* ANTI-WINDUP, TWO WAYS. The integrator is clamped to INTEG_MAX, and it
       does not accumulate at all while the output is saturated in the same
       direction as the error - which is the case that would otherwise store
       a step the plate can never work off. */
    maxd = hc_cal_u16(CFG_U_DBW_MAX_DUTY_X10);
    /* THE REMAINDER IS CARRIED, and without it the integrator is useless at
       exactly the errors it exists to remove. err * KI * 5 / 1000000 is ZERO
       in integer arithmetic for a 2 % error at KI = 4000 - so a small steady
       offset would sit there forever while the term that should erase it
       truncated away every step. me711_dbw_control_proof caught it.
       Worst case here is 1000 * 65535 * 5 = 3.3e8 plus a remainder below
       1e6, comfortably inside a 32-bit long. */
    {
        long num = (long)err * (long)dbw_cal_u16(CAL_DBW_KI)
                   * (long)DBW_STEP_MS + D.irem;
        i = num / (GAIN_DIV * 1000L);
        D.irem = num - i * (GAIN_DIV * 1000L);
    }
    #if defined(TGT_ETBCAL_FAR)
    if (D.integral_allowed &&
#else
    if (
#endif
        !((D.duty >= maxd) && ((err > 0) == (D.out_t >= 0)) && err != 0)) {
        D.integ += i;
    } else {
        /* Saturated in the direction of the error: do not accumulate, and do
           not hoard a remainder that would jump the moment it un-saturates. */
        D.irem = 0L;
    }
    if (D.integ > INTEG_MAX) {
        D.integ = INTEG_MAX;
    } else if (D.integ < -INTEG_MAX) {
        D.integ = -INTEG_MAX;
    }



    /* FEED-FORWARD. The bias curve is what it takes to hold the plate at a
       position against its return spring; the loop then only has to correct.
       Clamped and interpolated by hc_cal_curve16, which never extrapolates. */
    /* THE BIAS CURVE IS STORED WITH A +1000 OFFSET so an unsigned 16-bit
       page value can express a NEGATIVE duty - the curve has to be able to
       push the plate shut below its limp-home detent, which is a negative
       request. The model declares translate = -1000; 1000 stored is zero
       bias. Adding it raw made every neutral calibration contribute a
       full-scale feed-forward. */
    {
        long ff = (long)hc_cal_curve16(CAL_DBW_BIAS_AX, CAL_DBW_BIAS_VAL, 8u,
                                       D.tgt) - (long)DBW_BIAS_ZERO;
#if defined(TGT_ETBCAL_FAR)
        ff += hc_etbcal_friction(err);
#endif
        out = p + D.integ + d + ff;
        D.p_t = clampi(p, -32000L, 32000L);
        D.d_t = clampi(d, -32000L, 32000L);
        D.ff_t = (int)ff;
        D.out_t = clampi(out, -32000L, 32000L);
    }
    /* ---------------------------------------------- direction and duty --- */
    mag = out < 0 ? -out : out;
    if (mag > (long)maxd) {
        mag = (long)maxd;
    }
    /* THE PAGE SAYS WHICH WAY OPENS. Getting it wrong makes the controller
       drive away from its target; the deviation supervisor below is what
       catches that, which is why it exists and why it is not optional. */
    {
        unsigned char opening = (unsigned char)(out >= 0L);
        unsigned char cfgdir = dbw_cal_u8(CFG_U_DBW_MOTOR_DIR);
        hc_dbw_drive((unsigned char)(cfgdir ? opening : !opening),
              (unsigned int)mag);
    }

#if defined(TGT_ETBCAL_FAR)
    /* THE BOSCH DLR SETTING-RANGE MONITOR (FR DLR 3.60, hcetbcal.c): the
       output beyond the configured duty ceiling (DLRPIDMAX) is what counts,
       the status flag only matters while it is - restart the power stage,
       latch only after DLRPID2T. Replaces V99's "not shrinking" timer. */
    f = hc_etbcal_dlr_monitor((unsigned char)((out < 0L ? -out : out)
                                              > (long)maxd), sf, D.step_dt);
    if (f & DBW_DLR_RESTART) {
        /* THE FR's B_dveesh PULSE: the power stage is released for THIS
           control step only and re-enabled by the next one. The controller
           keeps RUN, its integrator and the setting-range time - a restart is
           not a re-initialisation (FR DLR 3.60). Until 2026-10-12 this was a
           full shutdown: the 4-step INIT and the PID reset made the output
           leave saturation every 25 ms, the setting-range timer fell faster
           than it rose, and a dead bridge was never judged
           (me711_dbw_dlr_monitor_proof M3 with gentler gains). D.held stays
           set: the controller still owns the bridge. */
#if defined(TGT_DBW_MOTOR_PRIMITIVE)
        hc_hal_dbw_motor(0u, 0u, 0u);
#else
        hc_hal_out_duty(HC_OUT_THR_PWM, 0u);
        hc_hal_out(HC_OUT_THR_EN, 0u);
#endif
        D.on = 0u;
        D.duty = 0u;
        return;
    }
    if (f) {
        hc_dbw_shutdown(f);
        return;
    }
#else
    /* --------------------------------------- the deviation supervisor ---- */
    /* A PLATE THAT IS GETTING THERE IS NOT JAMMED. V83..V98 timed any
       error above dbwDevX10 against the RAW target, so a sharp pedal step
       (6 -> 60 %) on a plate that needs more than dbwDevMs (AWT 200 ms) to
       come within the window latched DBW_F_DEV: the bridge dropped to the
       limp opening AND hclimp cut the fuel above etbLimpRpm (0 = 1500 rpm)
       until the next key-on - the car's "dies on a sharp throttle as if the
       ignition were cut" (2026-10-02, V98r2). rusEFI's jam detector
       (EtbController::checkJam) is 10 % for etbJamTimeout - default OFF, 1 s
       when set. The time now runs only while the error is NOT shrinking by
       at least DBW_DEV_PROGRESS per control step (0.2 % / 5 ms = 40 %/s):
       a stuck plate, a reversed motor or a dead bridge (error constant or
       growing) still latches after dbwDevMs; a plate travelling toward its
       target restarts the clock every step it gains. */
    {
        int e = D.tgt > D.act ? (int)(D.tgt - D.act)
                                  : (int)(D.act - D.tgt);
        int gained = (int)(D.dev_e - e);
        D.dev_e = e;
        if ((unsigned int)e > hc_cal_u16(CAL_DBW_DEV_X10)) {
            if (!D.dev_pending || gained >= DBW_DEV_PROGRESS) {
                D.dev_pending = 1u;
                D.dev_since = now_ms;
            } else if ((unsigned int)(now_ms - D.dev_since)
                       >= hc_cal_u16(CAL_DBW_DEV_MS)) {
                hc_dbw_shutdown(DBW_F_DEV);
                return;
            }
        } else {
            D.dev_pending = 0u;
            D.dev_since = now_ms;
        }
    }
#endif

    if (D.on) D.st = DBW_RUN;
}

void hc_dbw_service(unsigned int now_ms, unsigned int rpm, unsigned char armed)
{
    if (D.busy) return;
    D.busy = 1u;
    dbw_step(now_ms, rpm, armed);
    D.busy = 0u;
}

/* -------------------------------------------------------- telemetry ------ */
unsigned char hc_dbw_state(void)      { return D.st; }
unsigned int  hc_dbw_faults(void)     { return D.flt; }
unsigned int  hc_dbw_target_x10(void) { return D.tgt; }
unsigned int  hc_dbw_actual_x10(void) { return D.act; }
int           hc_dbw_error_x10(void)  { return D.err; }
unsigned int  hc_dbw_duty_x10(void)   { return D.duty; }
unsigned char hc_dbw_dir(void)        { return D.dir; }
unsigned char hc_dbw_bridge_on(void)  { return D.on; }
unsigned int  hc_dbw_pedal_x10(void)  { return D.pedal; }
unsigned int  hc_dbw_app1_x10(void)   { return D.a1; }
unsigned int  hc_dbw_app2_x10(void)   { return D.a2; }
unsigned int  hc_dbw_tps1_x10(void)   { return D.t1; }
unsigned int  hc_dbw_tps2_x10(void)   { return D.t2; }
int           hc_dbw_integ(void)      { return (int)D.integ; }
unsigned int  hc_dbw_steps(void)      { return D.steps; }
unsigned int  hc_dbw_gap_max(void)    { return D.gap_max; }
unsigned char hc_dbw_due(unsigned int now_ms)
{
    return (unsigned char)((unsigned int)(now_ms - D.step_mark) >= DBW_STEP_MS);
}
#if defined(TGT_ETBCAL_FAR)
unsigned int hc_dbw_term(unsigned char i) { return hc_etbcal_control_term(i); }
#else
unsigned int  hc_dbw_term(unsigned char i)
{
    switch (i) {
    case DBW_T_CONTROL_MS: return D.step_mark;
    case DBW_T_P:       return (unsigned int)D.p_t;
    case DBW_T_D:       return (unsigned int)D.d_t;
    case DBW_T_FF:      return (unsigned int)D.ff_t;
    case DBW_T_OUT:     return (unsigned int)D.out_t;
    case DBW_T_VFAC:    return D.vfac;
    case DBW_T_PEND:    return D.pend;
    case DBW_T_PEND_MS: return D.pend ? (unsigned int)(D.step_mark - D.pend_since) : 0u;
    case DBW_T_OVR:     return D.ovr;
    case DBW_T_CLEARS:  return D.clears;
    default:            return 0u;
    }
}
#endif

#endif /* !TGT_DBW_CONTROLLER */
