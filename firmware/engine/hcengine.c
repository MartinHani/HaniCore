/*
 * hcengine.c - counts in, fuel and spark out.
 *
 * See hcengine.h for why every sensor carries an error flag and a default.
 *
 * Channel assignments are BOARD facts and come from hctarget.h, which took
 * them from the schematic and the connector database - see
 * the maintainer's design notes. What a count MEANS is calibration and comes
 * from the page.
 *
 * SENSORS ARE READ THROUGH THE HAL, NOT THROUGH adc_raw[]. This file used to
 * index adc_raw[TGT_ADC_CLT_CH] and friends directly, which was correct while
 * there was one board and became wrong the moment there were two: on the
 * Bosch ME7.1.1 the coolant and intake-air sensors are NOT on this CPU's
 * converter at all - they are on the S5500 and arrive inside a 118-word
 * frame. hc_hal_ain() returns a raw 10-bit count from wherever the channel
 * actually lives, and hc_hal_ain_ok() says whether this board has it.
 *
 * EVERYTHING ELSE STAYED HERE ON PURPOSE. The plausibility windows, the
 * filters, the substitute values and the per-sensor error bits are the MS 4
 * Sport sensor model and they are CALIBRATION behaviour, identical on both
 * ECUs. Pushing them below the HAL would have meant two copies of the one
 * thing that must never differ between targets.
 */
#include <reg167.h>
#include "hctarget.h"
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hchal.h"
#include "hctrigger.h"
#include "hcengine.h"
#if defined(TGT_ETBCAL_FAR)
#include "hcetbcal.h"
#endif
#if defined(TGT_ENGINE_RUNTIME)
#include "hctrans711.h"   /* transient fuel, warm-up (far) */
#include "hcigncorr711.h" /* CLT / IAT timing corrections (far) */
#include "hcengctl711.h"  /* the engine-control layer (far) */
#include "hcload711.h"
#endif
#include "hc_airfuel.h"

unsigned int  eng_batt_dv;
unsigned int  eng_clt_dc;
unsigned int  eng_clt_meas_dc;   /* the reading, fault or not */
unsigned int  eng_map_kpa_x10;
unsigned int  eng_iat_dc;
unsigned int  eng_baro_kpa_x10;
unsigned int  eng_tps_x10;
/* THE THROTTLE THE LOAD USES IS NOT FILTERED (2026-10-11). filt() moves 1/16
   per main-loop pass - a time constant of 50..150 ms that changes with the
   pass length (TunerStudio polling). In front of the FR BGSRM filling model
   (hc_ec_load_lag) it was a SECOND lag: the computed air trailed the air the
   engine really took on a tip-in (me711_tipin_fill_proof: 12 % at 100 ms
   where the FR model alone gives 21 %) - lean fuel, early-load advance. The
   filling model is the one lag, by rpm; the display, idle and DFCO keep the
   filtered value. runtime_tail() takes the span of the same ADC value with
   the same calibration (no stored copy: near RAM is at its reserve). */
unsigned int  eng_tps2_x10;
unsigned int  eng_pedal_x10;
unsigned int  eng_pedal2_x10;
unsigned int  eng_sensor_err;

unsigned int  eng_load;
unsigned int  eng_rl_x10;       /* relative air charge, 0.1 % */
unsigned int  eng_air_mg_x10;   /* cylinder air mass, 0.1 mg  */
unsigned int  eng_ti_us;
unsigned int  eng_ti_base_us;
unsigned int  eng_deadtime_us;
#if defined(TGT_ENGINE_RUNTIME)
int           eng_ign_corr_x10;   /* CLT + IAT timing correction, 0.1 deg */
#endif
unsigned int  eng_afr_x10;
#if defined(TGT_ENGINE_RUNTIME)
int           eng_adv_x10;      /* signed, negative = after TDC */
unsigned int  eng_ve_x10;       /* VE looked up, 0.1 % */
unsigned int  eng_ve_load_x10;  /* the fuel table's load */
int           eng_adv_base_x10; /* the table's advance, signed */
#else
unsigned int  eng_adv_x10;
#endif
unsigned int  eng_dwell_x100;
unsigned char eng_cranking;
unsigned char eng_warmup_pct;
int           eng_tps_rate;
unsigned int  eng_accel_us;
unsigned int  eng_fuelcut;

/* Acceleration enrichment and the throttle rate it is computed from. Both live
   on the same fixed raster so the rate is a rate and not "however often the
   main loop happened to run". */
#define ACC_STEP_US   10000u
#define ACC_STEP_MS   10u
static unsigned int acc_mark;
static unsigned int acc_last_tps;
static unsigned int acc_shot_us;
static unsigned char overrun_cut;

/* An open or shorted analog input parks at one rail. Anything inside this
   window is a real signal; anything outside it is a wiring fault, whatever
   the sensor curve would make of it. 10-bit counts. */
#define ADC_PLAUS_LO   10u
#define ADC_PLAUS_HI   1013u

/* ============================ THE IGNITION ADVANCE CEILING, IN CODE ========
 *
 * CAL_IGN_MAP holds one byte per cell, decoded as (cell - 40) * 0.5 degrees so
 * the map can carry retard as well as advance. THAT ENCODING REACHES 107.5
 * DEGREES BTDC at cell 255, and nothing stopped it: a corrupt page, an
 * uninitialised record or a mis-scaled import would command an angle no spark
 * engine has ever wanted, into the scheduler's own angle arithmetic.
 *
 * The .ini's field limits are not a defence. They constrain what a TUNER can
 * type; they say nothing about what a byte in the page can hold, and the page
 * is what the runtime reads.
 *
 * 60.0 degrees is the ceiling. It is above any real demand - rusEFI's own
 * generated .ini bounds its ignition table at -20..90 and its default table
 * generator (controllers/algo/defaults/default_ignition.cpp, getInitialAdvance)
 * tops out far below that - and it is low enough that an angle arriving here
 * is recognisably a fault rather than a tune.
 *
 * THE CLAMP IS SILENT ON PURPOSE. It has one job, which is to stop an absurd
 * angle reaching the scheduler; publishing a new fault bit would mean a new
 * OCH offset, and eng_adv_x10 is already on the dashboard where a 60.0 that
 * will not move is exactly as visible as a warning light would be.
 */
#define IGN_ADV_MAX_X10   600u          /* 60.0 deg BTDC, hard */

static unsigned int ign_clamp(unsigned int adv_x10)
{
    return (adv_x10 > IGN_ADV_MAX_X10) ? IGN_ADV_MAX_X10 : adv_x10;
}

/* How far the two throttle tracks - or the two pedal tracks - may disagree
   before neither is believed. They are wired with OPPOSING slopes, so what is
   compared is one against the other's mirror image. 10 % of full scale. */
#define TRACK_TOL_X10  100u

/* First-order filter, done in 1/16ths so it needs no floating point and no
   division. Applied to the PHYSICAL value, not the counts, so the time
   constant means the same thing whatever the sensor curve does. */
/* A 1/16 FIRST-ORDER FILTER THAT REACHES ITS TARGET.
 *
 * It was (15*old + now) / 16 with truncation, whose RISING fixed point is
 * anywhere down to now - 15: a throttle at 2.0 % settled at 0.5 %, measured in
 * c167sim (me711_alphan_start_proof). Harmless for 0.1 kPa of MAP, most of
 * the idle opening once the throttle IS the load (alpha-N). Same time
 * constant for large errors; the last counts close one per pass. */
static unsigned int filt(unsigned int old, unsigned int now)
{
    unsigned int step;

    if (now > old) {
        step = (unsigned int)((now - old) >> 4);
        return (unsigned int)(old + (step != 0u ? step : 1u));
    }
    if (now < old) {
        step = (unsigned int)((old - now) >> 4);
        return (unsigned int)(old - (step != 0u ? step : 1u));
    }
    return old;
}

static unsigned int span_pct_x10(unsigned int raw, unsigned int lo,
                                 unsigned int hi)
{
    /* AN INVERTED SPAN IS NOT AN ERROR, IT IS THE NORMAL CASE HERE.
     *
     * On the Bosch VAG throttle body the first position track FALLS as the
     * plate opens - rusEFI's own defaults for this exact body are tpsMin 890
     * and tpsMax 70 - and the autocal writes the closed reading into MIN and
     * the open reading into MAX without sorting them, because sorting would
     * throw the direction away.
     *
     * The previous version returned 0 whenever hi <= lo, so an inverted track
     * read 0 % forever and looked exactly like a dead sensor. */
    if (lo > hi) {
        if (raw >= lo) {
            return 0;
        }
        if (raw <= hi) {
            return 1000u;
        }
        return (unsigned int)(((unsigned long)(lo - raw) * 1000uL)
                              / (unsigned long)(lo - hi));
    }
    if (hi == lo) {
        return 0;
    }
    if (raw <= lo) {
        return 0;
    }
    if (raw >= hi) {
        return 1000u;
    }
    return (unsigned int)(((unsigned long)(raw - lo) * 1000uL)
                          / (unsigned long)(hi - lo));
}

void eng_init(void)
{
    eng_batt_dv = 0;
    /* Until the first read, every sensor is what a fault makes it: the
       ONE fallback per sensor (ENG_FAULT_*), never a second, quieter one. */
    eng_clt_dc = ENG_FAULT_TEMP_DC;
    eng_clt_meas_dc = ENG_FAULT_TEMP_DC;
    eng_map_kpa_x10 = ENG_FAULT_MAP_X10;
    eng_iat_dc = ENG_FAULT_TEMP_DC;
    eng_baro_kpa_x10 = hc_cal_u16(CAL_BARO_DEFAULT);
    if (eng_baro_kpa_x10 == 0) {
        eng_baro_kpa_x10 = 1000u;
    }
    eng_tps_x10 = 0;
    eng_tps2_x10 = 0;
    eng_pedal_x10 = 0;
    eng_pedal2_x10 = 0;
    eng_sensor_err = 0;
    eng_load = 1000u;
    eng_rl_x10 = 0u;
    eng_air_mg_x10 = 0u;
    eng_ti_us = 0;
    eng_ti_base_us = 0;
    eng_deadtime_us = 0;
#if defined(TGT_ENGINE_RUNTIME)
    eng_ign_corr_x10 = 0;
#endif
    eng_afr_x10 = 147u;
    eng_adv_x10 = 100u;              /* 10.0 deg, inside the clamp */
#if defined(TGT_ENGINE_RUNTIME)
    eng_ve_x10 = 0u;
    eng_ve_load_x10 = 0u;
    eng_adv_base_x10 = 100;
    hc_ec_init();
    hc_load_init();
#endif
    eng_dwell_x100 = 300u;
    eng_cranking = 1;
    eng_warmup_pct = 100u;
    eng_tps_rate = 0;
    eng_accel_us = 0;
    eng_fuelcut = 0;
    acc_mark = T7;
    acc_last_tps = 0;
    acc_shot_us = 0;
    overrun_cut = 0;
}

/* -------------------------------------------------- acceleration enrichment
 *
 * A throttle opening faster than the manifold can fill leaves the mixture lean
 * for a moment - the air arrives before the extra fuel does. The classic fix
 * is a shot of fuel proportional to how fast the plate is moving, decaying
 * away over a couple of hundred milliseconds.
 *
 * Scaled by the warm-up factor rather than given its own temperature table: a
 * cold engine needs more of this for exactly the same reason it needs more
 * everywhere else, and one table that is already tuned beats two that are not.
 */
static void accel_service(void)
{
    unsigned int now = T7;
    int d;
    unsigned int thresh;
    unsigned int gain;
    unsigned int decay;

    if ((unsigned int)(now - acc_mark) < (unsigned int)US_TO_TICKS(ACC_STEP_US)) {
        return;
    }
    acc_mark = now;

    d = (int)eng_tps_x10 - (int)acc_last_tps;
    acc_last_tps = eng_tps_x10;
    if (eng_sensor_err & ENG_ERR_TPS1) {
        d = 0;          /* V98r2, rusEFI: no AE from an invalid TPS - a fault
                           and its recovery are steps, not driver demand */
    }

    /* 0.1 % per 10 ms is 10 units of 0.1 %/s, so the rate is the difference
       times a hundred. Clamped so a sensor glitch cannot become a fuel event
       the size of a cylinder. */
    if (d > 300) {
        d = 300;
    }
    if (d < -300) {
        d = -300;
    }
    eng_tps_rate = (int)(d * 100);

    thresh = hc_cal_u16(CAL_ACCEL_THRESH_X10);
    gain = hc_cal_u16(CAL_ACCEL_GAIN);
    decay = hc_cal_u16(CAL_ACCEL_DECAY_MS);
    if (decay < ACC_STEP_MS) {
        decay = ACC_STEP_MS;
    }

    if (gain != 0u && eng_tps_rate > (int)thresh) {
        /* gain is microseconds per 1 %/s, and the rate is in 0.1 %/s. */
        unsigned long shot = ((unsigned long)(eng_tps_rate - (int)thresh)
                              * (unsigned long)gain) / 10uL;

        shot = (shot * (unsigned long)eng_warmup_pct) / 100uL;
        if (shot > 20000uL) {
            shot = 20000uL;
        }
        if (shot > (unsigned long)acc_shot_us) {
            acc_shot_us = (unsigned int)shot;
        }
    } else if (acc_shot_us != 0u) {
        /* Linear decay over CAL_ACCEL_DECAY_MS. */
        unsigned int step = (unsigned int)((unsigned long)acc_shot_us
                                           * ACC_STEP_MS / decay);

        if (step == 0u) {
            step = 1u;
        }
        acc_shot_us = (acc_shot_us > step) ? (unsigned int)(acc_shot_us - step) : 0u;
    }
    eng_accel_us = acc_shot_us;
}

#if !defined(TGT_ENGINE_RUNTIME)   /* ME7.1.1 has it in hcengctl711.c (far) */
/* ==================================== ENDPOINT GRAB - see hcengine.h =======
 *
 * One end of one pair at a time, both tracks together, RAM only.
 */

/* Historical minimum-span diagnostic/test constant. Capture no longer
   compares against a previous endpoint.
   How far apart the two ends of a track must end up. rusEFI's autocal uses
   100 counts of a 10-bit converter for exactly this test and calls a smaller
   travel "check your wiring". A real throttle or pedal moves several hundred.
   COMPILED IN, not a page value: a check a tuner can widen until it passes is
   not a check. */
#define GRAB_MIN_SPAN   100u

static unsigned int grab_pair(unsigned char ch1, unsigned char ch2,
                              unsigned int slot1, unsigned int slot2)
{
    unsigned int r1;
    unsigned int r2;

    if (!hc_hal_ain_ok(ch1) || !hc_hal_ain_ok(ch2)) {
        return ENG_GRAB_NOCHANNEL;
    }
    r1 = hc_hal_ain(ch1);
    r2 = hc_hal_ain(ch2);
    if (r1 < ADC_PLAUS_LO || r1 > ADC_PLAUS_HI
        || r2 < ADC_PLAUS_LO || r2 > ADC_PLAUS_HI) {
        return ENG_GRAB_RAIL;
    }

    /* Capture is independent of the previous opposite endpoint, as in
       rusEFI's individual endpoint commands. Page/runtime validation still
       refuses an impossible span. The command handler requires motor OFF. */
    hc_cal_set_u16(slot1, r1);
    hc_cal_set_u16(slot2, r2);
    return ENG_GRAB_PASS;
}

unsigned int eng_calib_grab(unsigned char what)
{
    unsigned int v;

    /* THE ENGINE MUST BE DEMONSTRABLY STOPPED. Not "rpm reads zero" - the
       decoder must also be reporting no crank signal at all, which is the
       same pair of facts hcbench.c requires before it drives a pin. A
       calibration captured while something is turning is a calibration of a
       moment. */
    if (trg_rpm != 0u || trg_state != TRG_NO_SIGNAL) {
        v = ENG_GRAB_RPM;
    } else {
        switch (what) {
        case ENG_GRAB_TPS_CLOSED:
            v = grab_pair(HC_AIN_TPS1, HC_AIN_TPS2,
                          CAL_TPS1_MIN, CAL_TPS2_MIN);
            break;
        case ENG_GRAB_TPS_OPEN:
            v = grab_pair(HC_AIN_TPS1, HC_AIN_TPS2,
                          CAL_TPS1_MAX, CAL_TPS2_MAX);
            break;
        case ENG_GRAB_APP_REST:
            v = grab_pair(HC_AIN_APP1, HC_AIN_APP2,
                          CAL_PEDAL1_MIN, CAL_PEDAL2_MIN);
            break;
        case ENG_GRAB_APP_FULL:
            v = grab_pair(HC_AIN_APP1, HC_AIN_APP2,
                          CAL_PEDAL1_MAX, CAL_PEDAL2_MAX);
            break;
        default:
            v = ENG_GRAB_WHAT;
            break;
        }
    }

    return v;
}
#endif


/* AN NTC READING OUTSIDE ITS OWN CURVE IS A WIRING FAULT, NOT A
   TEMPERATURE. The generic ADC window (10..1013) let an OPEN intake-air input
   through - measured on V78: raw 958 against an OEM curve that ends at 900,
   shown as a valid -24.5 C. The curve says where a real sensor can be; 30
   counts beyond its cold end is open, 10 short of its hot end is shorted. */
/* THE COLD END IS THE END. The first AWT test read the coolant input
   at raw 923 against an OEM curve that ends at 909 (-40 C): a connected but
   far too high resistance, 14 counts past the curve - and the 30-count margin
   let it through as a VALID -40.0 C, error bit clear, "CLT OK" lit, cranking
   fuel at its coldest. A reading beyond the curve's cold end claims a sensor
   colder than its own calibration; only ADC noise may exceed it. */
#define CURVE_COLD_MARGIN  4u

static unsigned char curve_span_ok(unsigned int ax_off, unsigned int raw)
{
    if (raw < ADC_PLAUS_LO || raw > ADC_PLAUS_HI) {
        return 0u;
    }
    if (raw > (unsigned int)(hc_cal_u16((unsigned int)(ax_off
                              + 2u * (CAL_AXIS_N - 1u))) + CURVE_COLD_MARGIN)) {
        return 0u;
    }
    if ((unsigned int)(raw + 10u) < hc_cal_u16(ax_off)) {
        return 0u;
    }
    return 1u;
}

/* DO TWO NORMALISED TRACKS AGREE, UNDER THE CONFIGURED RELATIONSHIP?
 *
 * The same rule as hc_dbw.c pair_bad(), for the sensor-error bits the UI shows
 * as PEDAL / TPS PLAUSIBILITY. Until V90 this file assumed OPPOSING slopes for
 * both pairs, whatever appCorrelation/tpsCorrelation said: a VAG pedal - G185
 * rises with G79 at half its amplitude, which after each track's own
 * calibration is the SAME 0..100 % - could only "agree" where p1 + p2 = 100 %,
 * i.e. around 50 % pedal. Measured on the AWT, 2026-09-26. Tolerance is the
 * configured one; 0 falls back to 10 %. */
static unsigned char tracks_disagree(unsigned int a, unsigned int b,
                                     unsigned char corr, unsigned int tol)
{
    unsigned int d;

    if (tol == 0u) {
        tol = TRACK_TOL_X10;
    }
    if (corr == HC_TRACK_OPPOSITE) {
        b = (unsigned int)(1000u - (b > 1000u ? 1000u : b));
    }
    d = (a > b) ? (unsigned int)(a - b) : (unsigned int)(b - a);
    return (unsigned char)(d > tol);
}

#if defined(TGT_ENGINE_RUNTIME)
/* ======================== V98: THE ME7.1.1 ENGINE MODEL ====================
 *
 * the maintainer's design notes. What changed against the V97 tail below (which
 * stays, unchanged, for ME7.5):
 *
 *  - THREE LOAD STRATEGIES (CAL_LOAD_SOURCE): speed density, alpha-N x
 *    inlet pressure (the V97 "throttle" mode, unchanged in meaning) and pure
 *    alpha-N (rusEFI alphan_airmass.cpp: 101.3 kPa, 20 C or IAT) - which
 *    needs no pressure sensor at all.
 *  - THE CONTROL VALUE OF A FAILED SENSOR IS PER CONSUMER (rusEFI's
 *    value_or() at each call site). The displayed values stay what they were
 *    (CLT/IAT -40 C, MAP 0 kPa); the fuel uses the MAP estimate table, the
 *    air temperature 0 C, the warm-up 100 %, cranking 20 C, the timing
 *    corrections 0 (hcengctl711.c).
 *  - A FAILED THROTTLE TRACK 1 falls back to track 2, then (electronic
 *    throttle) to the limp-home opening the spring holds; with neither,
 *    alpha-N has no air (rusEFI: "if the TPS fails, stop the engine").
 *  - SIGNED SPARK: the table already held -20..+107.5 deg and was floored at
 *    0; it now commands after-TDC timing too, -30..+60 deg after every
 *    correction (hcengctl711.c hc_ec_spark).
 *  - CRANKING FUEL IS A MASS (0.1 mg per cylinder per cycle, rusEFI
 *    crankingCycleBaseFuel), turned into time by the same injector model as
 *    running fuel.
 *  - TARGET LAMBDA ON ITS OWN AXES, DFCO, CLOSED LOOP, REV LIMIT AND
 *    MOTORSPORT in hcengctl711.c (far).
 */
#define T_20C_X10    2932u                 /* 20 C in 0.1 K               */
#define CLT_20C_DC   ((unsigned int)((20 + (int)CAL_TEMP_BIAS) * 10))
#define IAT_0C_DC    ((unsigned int)((0 + (int)CAL_TEMP_BIAS) * 10))
#define TPS_INVALID  0xFFFFu


static void runtime_tail(unsigned int rpm)
{
    unsigned int err = eng_sensor_err;
    unsigned char src = hc_cal_u8(CAL_LOAD_SOURCE);
    unsigned int cyl = cfg_u8(CFG_CYLINDERS);
    unsigned int disp = hc_cal_u16(CFG_U_DISPLACEMENT_CC);
    unsigned int vd = (cyl != 0u) ? (unsigned int)(disp / cyl) : 0u;
    unsigned int tps_c = span_pct_x10(hc_hal_ain(HC_AIN_TPS1),
                                      hc_cal_u16(CAL_TPS1_MIN),
                                      hc_cal_u16(CAL_TPS1_MAX));
    unsigned int p_x10, t_x10, load, ve_x10, lam, flow;
    unsigned long air;
    int base;

    hc_ec_pre(rpm);

    /* ---- the throttle the fuel uses ---------------------------------- */
    if (err & ENG_ERR_TPS1) {
        if (!(err & ENG_ERR_TPS2)) {
            tps_c = span_pct_x10(hc_hal_ain(HC_AIN_TPS2),
                                 hc_cal_u16(CAL_TPS2_MIN),
                                 hc_cal_u16(CAL_TPS2_MAX));
            tps_c = (hc_cal_u8(CFG_U_TPS_CORR) == HC_TRACK_OPPOSITE)
                  ? (unsigned int)(1000u - (tps_c > 1000u ? 1000u : tps_c))
                  : tps_c;
        } else if (hc_cal_u8(CAL_DBW_ENABLE) != 0u) {
            tps_c = hc_cal_u16(CAL_DBW_LIMP_X10);   /* the spring's opening */
        } else {
            tps_c = TPS_INVALID;
        }
    }

    /* THE MANIFOLD FILLS, IT DOES NOT JUMP (FR BGSRM 17.10, hcengctl711.c):
       the throttle the fuel and the ignition load use is the filled one. */
    tps_c = hc_ec_load_lag(tps_c, rpm);

    /* ---- air ---------------------------------------------------------- */
    hc_load_select(tps_c);
    if (HC_LOAD.model != 0u) {
        /* New policies select density pressure and VE axis independently.
           Legacy branch below remains the exact V101 arithmetic contract. */
        p_x10 = HC_LOAD.effective; t_x10 = HC_LOAD.temperature; load = HC_LOAD.axis;
    } else if (src == CAL_LOAD_ALPHAN) {
        /* the ambient hc_load_select() just published - the onboard sensor
           on ME7.1.1 (2026-10-16: no fixed 1013 hPa) */
        p_x10 = eng_baro_kpa_x10;
        t_x10 = (hc_cal_u8(CFG_U_ALPHAN_IAT) != 0u && !(err & ENG_ERR_IAT))
              ? hc_af_charge_t_x10(eng_iat_dc) : T_20C_X10;
        load = tps_c;
    } else {
        p_x10 = hc_ec_map_ctrl();          /* measured, or the estimate   */
        /* rusEFI getTCharge(): a failed intake sensor is 0 C (dense: the
           mixture errs rich, never lean). */
        t_x10 = hc_af_charge_t_x10((err & ENG_ERR_IAT) ? IAT_0C_DC
                                                       : eng_iat_dc);
        load = (src == CAL_LOAD_TPS) ? tps_c : p_x10;
    }
    if (load == TPS_INVALID) {
        load = 0u;
        ve_x10 = 0u;                                  /* no throttle: no air */
    } else {
        /* one count = 0.1 % - see CAL_FUEL_MAP; 400.0 % is the
           field's limit and hc_af_air_x100's 32-bit bound */
        ve_x10 = hc_cal_map16(CAL_FUEL_MAP, CAL_FUEL_RPM_AX,
                              CAL_FUEL_LOAD_AX, rpm, load);
        if (ve_x10 > VE_MAX_X10) {
            ve_x10 = VE_MAX_X10;
        }
    }
    air = hc_af_air_x100(hc_af_charge_x100(hc_af_density_x1000(p_x10, t_x10),
                                           vd), ve_x10);
    eng_air_mg_x10 = (unsigned int)((air > 655350uL) ? 65535uL : (air / 10uL));
    eng_rl_x10 = hc_af_rl_x10(air, vd);
    eng_ve_x10 = ve_x10;
    eng_ve_load_x10 = load;
    eng_load = load;
    HC_LOAD.effective = p_x10; HC_LOAD.temperature = t_x10; HC_LOAD.axis = load;

    /* ---- cranking (MS 4 Sport STARTENDREV_HYS, unchanged) -------------- */
    {
        unsigned int crank_max = cfg_u16(CFG_CRANK_RPM_MAX);

        if (eng_cranking) {
            if (rpm > (unsigned int)(crank_max + 100u)) {
                eng_cranking = 0;
            }
        } else if (rpm < crank_max) {
            eng_cranking = 1;
        }
    }

    /* ---- dwell and dead time against battery ------------------------
     * ONE store: the cranking dwell and the rpm factor are hcengctl711.c's
     * (hc_ec_dwell), so the planner never reads a half-corrected value. */
    eng_dwell_x100 = hc_ec_dwell(hc_cal_curve16(CAL_DWELL_BATT_AX,
                                                CAL_DWELL_BATT_VAL, 8u,
                                                (unsigned int)(eng_batt_dv * 10u)));
    eng_deadtime_us = hc_cal_curve16(CAL_DWELL_BATT_AX, CAL_DEADTIME_VAL,
                                     8u, (unsigned int)(eng_batt_dv * 10u));

    /* ---- ignition ------------------------------------------------------
     * FIXED TIMING short-circuits everything (rusEFI getAdvance(): "fixed
     * timing is the simple: cranking/running does not matter, no
     * corrections!"). Otherwise the table - one count 0.5 deg, -20 deg
     * offset, so it carries after-TDC timing - or the cranking angle, then
     * hcengctl711.c's corrections and overrides. */
    if (hc_cal_u8(CFG_U_TIMING_MODE) != 0u) {
        eng_adv_x10 = (int)ign_clamp(hc_cal_u16(CFG_U_FIXED_TIMING_X10));
        eng_adv_base_x10 = eng_adv_x10;
        eng_ign_corr_x10 = 0;
    } else {
        unsigned char c = hc_cal_map(CAL_IGN_MAP, CAL_IGN_RPM_AX,
                                     CAL_IGN_LOAD_AX, rpm,
                                     hc_ec_ign_load(load));
        base = (int)(((int)c - 40) * 5);
        if (eng_cranking) {
            base = (int)ign_clamp(cfg_u16(CFG_IGN_ADVANCE_DEG_X10));
            eng_ign_corr_x10 = 0;
        }
        eng_adv_base_x10 = base;
        eng_adv_x10 = hc_ec_spark(base, eng_cranking);
    }

    /* ---- target lambda, warm-up --------------------------------------- */
    lam = hc_ec_target_lambda(rpm, load);
    /* rusEFI getCltFuelCorrection(): a failed coolant sensor enriches
       NOTHING (1.0) - it must not flood a warm engine. */
    eng_warmup_pct = (err & ENG_ERR_CLT) ? 100u : hc_trans_warmup(eng_clt_dc);

    /* ---- fuel ---------------------------------------------------------- */
    /* the rated flow, corrected for the pressure across the injector
       (hcengctl711.c inj_pressure(); 0/0 = as rated) */
    flow = hc_af_flow_at_dp_x100(hc_af_flow_x100(hc_cal_u16(CFG_U_INJ_FLOW_CCMIN)),
                                 HC_EC.inj_dp_x10, HC_EC.inj_ref_x10);
    HC_EC.inj_flow_x100 = flow;
    if (eng_cranking) {
        /* THE CRANKING FUEL IS A MASS: 0.1 mg per cylinder per cycle by
           coolant (20 C if the sensor has failed, rusEFI getCrankingFuel3),
           through the injector model like running fuel. */
        unsigned int m = hc_cal_curve16(CAL_CRANK_PW_AX, CAL_CRANK_PW_VAL, 8u,
                                        (err & ENG_ERR_CLT) ? CLT_20C_DC
                                                            : eng_clt_dc);
        HC_LOAD.base_fuel_x100 = (unsigned long)m * 10uL;
        eng_ti_base_us = hc_af_te_us((unsigned long)m * 10uL, flow);
    } else {
        unsigned long fuel_x100 = hc_af_fuel_x100((unsigned long)eng_air_mg_x10
                                                  * 10uL,
                                                  hc_cal_u16(CFG_U_STOICH_X100),
                                                  lam);
        unsigned long w;

        HC_LOAD.base_fuel_x100 = fuel_x100;

        eng_ti_base_us = hc_af_te_us(fuel_x100, flow);
        /* saturate - te_us reaches 65535 and warm-up 255 %, and the
           truncated product was a SHORT pulse */
        w = ((unsigned long)eng_ti_base_us * eng_warmup_pct) / 100uL;
        eng_ti_base_us = (unsigned int)((w > 65535uL) ? 65535uL : w);
    }
    accel_service();
    if (!eng_cranking) {
        eng_ti_base_us = (eng_accel_us > (unsigned int)(65535u - eng_ti_base_us))
                       ? 65535u : (unsigned int)(eng_ti_base_us + eng_accel_us);
        /* closed loop, soft limit, launch, anti-lag (hcengctl711.c) */
        eng_ti_base_us = hc_ec_fuel(eng_ti_base_us);
    }
    /* transient fuel - wall film and after-start (hctrans711.c); a cut
       injects nothing and lets the film dry */
    eng_ti_base_us = hc_trans_fuel(eng_ti_base_us, eng_cranking,
                                   (unsigned char)((eng_fuelcut
                                       & ENG_CUT_ALL)
                                       != 0u));
    hc_load_protect(rpm, lam);
    hc_ec_post(rpm, load);
    {
        unsigned long t = (unsigned long)eng_ti_base_us
                        + (unsigned long)eng_deadtime_us;

        eng_ti_us = (unsigned int)((t > 60000uL) ? 60000uL : t);
    }
}
#endif /* TGT_ENGINE_RUNTIME */

#if defined(TGT_ENGINE_RUNTIME)
void eng_acquire(void)
#else
void eng_service(void)
#endif
{
    unsigned int raw;
    unsigned int err = 0;
#if !defined(TGT_ENGINE_RUNTIME)
    unsigned int rpm = trg_rpm;
    unsigned char cell;
#endif

    /* ---------------------------------------------------------- battery -- */
    raw = hc_hal_ain(HC_AIN_VBAT);
    eng_batt_dv = (unsigned int)(((unsigned long)raw
                                  * (unsigned long)cfg_u16(CFG_ADC_BATT_FS_DV))
                                 / 1023uL);
    if (!hc_hal_ain_ok(HC_AIN_VBAT) || eng_batt_dv < 40u || eng_batt_dv > 200u) {
        err |= ENG_ERR_BATT;
        /* Do NOT substitute here: dwell and dead time both lengthen as the
           battery sags, so guessing high would UNDER-fuel and UNDER-charge at
           exactly the moment the reading went missing. 12.0 V is the value
           every default table is centred on. */
        eng_batt_dv = 120u;
    }

    /* ---------------------------------------------------------- coolant --
     *
     * On ME7.1.1 this is the S5500's AN0, and since V78 hc_hal_ain_ok() is 1
     * only for a sample the ASIC's ADC itself tagged AN0 (hchal_me711.c
     * s5500_sample()). Otherwise the substitute below is used and
     * ENG_ERR_CLT is set. An open sensor reads near 1023 and is refused by
     * the plausibility window, not believed. */
    raw = hc_hal_ain(HC_AIN_CLT);
    /* V97: AN INVALID COOLANT READING IS -40 C, AND IT
       IS THE SAME -40 C EVERYWHERE. The displayed value (eng_clt_meas_dc,
       OCH 130), the control value (eng_clt_dc, OCH 780) and every consumer
       of eng_clt_dc - warm-up, cranking fuel, after-start, wall film, idle,
       ignition correction, knock, VVT, boost - see -40 C while ENG_ERR_CLT
       is set. V91..V97 substituted 80 C for control only; that hidden
       second value is gone. Consequence, on purpose: a failed sensor
       commands the cold-start enrichment, and the CLT FAULT lamp and P0115
       say why. eng_clt_meas_dc and eng_clt_dc are still two variables
       because the measurement is filtered separately from the control
       value; on a fault both are ENG_FAULT_TEMP_DC exactly. */
    if (!hc_hal_ain_ok(HC_AIN_CLT) || !curve_span_ok(CAL_CLT_SENS_AX, raw)) {
        err |= ENG_ERR_CLT;
        eng_clt_meas_dc = ENG_FAULT_TEMP_DC;
        eng_clt_dc = ENG_FAULT_TEMP_DC;
    } else {
        unsigned int t = hc_cal_curve16(CAL_CLT_SENS_AX, CAL_CLT_SENS_VAL,
                                        CAL_AXIS_N, raw);
        eng_clt_meas_dc = filt(eng_clt_meas_dc, t);
        eng_clt_dc = filt(eng_clt_dc, t);
    }

    /* ------------------------------------------------ manifold pressure --
     *
     * ME7.1.1 is a MAF-load ECU and Bosch's port map shows no manifold
     * pressure channel on it, so hc_hal_ain_ok() returns 0 there and the load
     * axis has to be the throttle (CAL_LOAD_SOURCE). That is a real
     * difference between the two engines, and it is why load source is
     * calibration rather than a compile-time choice. */
    raw = hc_hal_ain(HC_AIN_MAP);
    if (!hc_hal_ain_ok(HC_AIN_MAP) || raw < ADC_PLAUS_LO || raw > ADC_PLAUS_HI) {
        err |= ENG_ERR_MAP;
        /* V97 (2026-09-30): 0 kPa, not atmospheric. Nothing substitutes a
           pressure any more: the density term, the load axis and boost all
           see 0, so speed density and alpha-N compute NO AIR and therefore
           NO FUEL while the fault stands - the MAP FAULT lamp and P0105 say
           why. (V30..V97 used 100 kPa, which let a failed sensor run the
           engine on a guess.) Overboost ignores a MAP fault (hcboost711.c). */
        eng_map_kpa_x10 = ENG_FAULT_MAP_X10;
    } else {
        unsigned int k = (unsigned int)(hc_cal_u16(CAL_MAP_SENS_OFF)
                         + (unsigned int)(((unsigned long)raw
                            * (unsigned long)hc_cal_u16(CAL_MAP_SENS_GRD))
                            / 1000uL));
        eng_map_kpa_x10 = filt(eng_map_kpa_x10, k);
    }

    /* ------------------------------------------------------- intake air --
     *
     * The sensor is wired to connector pin 85, which on this board goes to the
     * CG650 ASIC and not to the C167's converter - and there is no read path
     * for the ASIC. The stock Bosch image builds no pointer into that segment
     * at all, so there was no protocol to recover, and guessing at a
     * peripheral's registers is exactly what this project has a rule against.
     *
     * So the channel is CONFIGURED. Connector pin 17 is a second temperature
     * input this car does not use, on AN13: move the sensor wire there, set
     * CAL_IAT_CHANNEL to 13, and it works. Until somebody does, the substitute
     * is used and the error bit says so - which is honest, and costs a few per
     * cent of fuel accuracy rather than pretending to a reading.
     *
     * On ME7.1.1 the same signal is TANS on the S5500's AN1, so the HAL
     * resolves HC_AIN_IAT completely differently there - and this code does
     * not change at all, which is the point of the seam. The ME7.5 HAL still
     * reads CAL_IAT_CHANNEL LIVE on every call, so moving the wire and typing
     * the new channel number still works without a power cycle. */
    raw = hc_hal_ain(HC_AIN_IAT);
    if (!hc_hal_ain_ok(HC_AIN_IAT) || !curve_span_ok(CAL_IAT_SENS_AX, raw)) {
        err |= ENG_ERR_IAT;
        /* V97 (2026-09-30): -40 C, fixed. The iatDefault page field is
           no longer read - a configurable fallback was a second, silent
           value; the field is labelled "(not used)". */
        eng_iat_dc = ENG_FAULT_TEMP_DC;
    } else {
        eng_iat_dc = filt(eng_iat_dc,
                          hc_cal_curve16(CAL_IAT_SENS_AX, CAL_IAT_SENS_VAL,
                                         CAL_AXIS_N, raw));
    }

    /* --------------------------------------------------- ambient pressure --
     *
     * Not read from anywhere. WITH THE ENGINE STOPPED THE MANIFOLD IS AT
     * AMBIENT, so the manifold sensor measures barometric pressure directly -
     * no second sensor, no ASIC, and it re-learns every time the car is
     * switched on at a different altitude.
     *
     * Only while genuinely stopped, and only when the manifold reading is
     * trustworthy: a cranking engine is already pulling vacuum. */
    if (trg_rpm == 0 && !(err & ENG_ERR_MAP)) {
        eng_baro_kpa_x10 = eng_map_kpa_x10;
    }

    /* ------------------------------------------- throttle and pedal -------
     *
     * Two tracks each, wired with opposing slopes. That is the whole point of
     * a drive-by-wire position sensor: the pair must always disagree in a
     * fixed way, and if they ever AGREE, a track has failed. Both are read and
     * cross-checked here even though nothing drives the motor yet, because the
     * check has to be trustworthy before it is ever relied on.
     */
    raw = hc_hal_ain(HC_AIN_TPS1);
    if (!hc_hal_ain_ok(HC_AIN_TPS1) || raw < ADC_PLAUS_LO || raw > ADC_PLAUS_HI) {
        err |= ENG_ERR_TPS1;
        eng_tps_x10 = 0;
    } else {
        eng_tps_x10 = filt(eng_tps_x10,
                           span_pct_x10(raw, hc_cal_u16(CAL_TPS1_MIN),
                                        hc_cal_u16(CAL_TPS1_MAX)));
    }
    raw = hc_hal_ain(HC_AIN_TPS2);
    if (!hc_hal_ain_ok(HC_AIN_TPS2) || raw < ADC_PLAUS_LO || raw > ADC_PLAUS_HI) {
        err |= ENG_ERR_TPS2;
        eng_tps2_x10 = 0;
    } else {
        eng_tps2_x10 = filt(eng_tps2_x10,
                            span_pct_x10(raw, hc_cal_u16(CAL_TPS2_MIN),
                                         hc_cal_u16(CAL_TPS2_MAX)));
    }
    if (!(err & (ENG_ERR_TPS1 | ENG_ERR_TPS2))
#if defined(TGT_ETBCAL_FAR)
        && hc_etbcal_tps_pair_fault()) {
#else
        && tracks_disagree(eng_tps_x10, eng_tps2_x10,
                           hc_cal_u8(CFG_U_TPS_CORR),
                           hc_cal_u16(CFG_U_TPS_TOL_X10))) {
#endif
        err |= ENG_ERR_TPS_DIFF;
    }

    raw = hc_hal_ain(HC_AIN_APP1);
    if (!hc_hal_ain_ok(HC_AIN_APP1) || raw < ADC_PLAUS_LO || raw > ADC_PLAUS_HI) {
        err |= ENG_ERR_PEDAL1;
        eng_pedal_x10 = 0;
    } else {
        eng_pedal_x10 = filt(eng_pedal_x10,
                             span_pct_x10(raw, hc_cal_u16(CAL_PEDAL1_MIN),
                                          hc_cal_u16(CAL_PEDAL1_MAX)));
    }
    raw = hc_hal_ain(HC_AIN_APP2);
    if (!hc_hal_ain_ok(HC_AIN_APP2) || raw < ADC_PLAUS_LO || raw > ADC_PLAUS_HI) {
        err |= ENG_ERR_PEDAL2;
        eng_pedal2_x10 = 0;
    } else {
        eng_pedal2_x10 = filt(eng_pedal2_x10,
                              span_pct_x10(raw, hc_cal_u16(CAL_PEDAL2_MIN),
                                           hc_cal_u16(CAL_PEDAL2_MAX)));
    }
    if (!(err & (ENG_ERR_PEDAL1 | ENG_ERR_PEDAL2))
        && tracks_disagree(eng_pedal_x10, eng_pedal2_x10,
                           hc_cal_u8(CFG_U_APP_CORR),
                           hc_cal_u16(CFG_U_APP_TOL_X10))) {
        err |= ENG_ERR_PED_DIFF;
    }

    eng_sensor_err = err;

#if defined(TGT_ENGINE_RUNTIME)
}

void eng_calculate(void)
{
    runtime_tail(trg_rpm);
#else
    /* --------------------------------------------------------------- load
     *
     * THE CANONICAL LOAD IS RELATIVE AIR CHARGE, not manifold pressure.
     *
     * This used to be `eng_load = eng_map_kpa_x10` - raw MAP, in 0.1 kPa, used
     * directly as a table axis, with CAL_FUEL_MAP holding a byte of PULSE
     * WIDTH. That is a table of answers rather than a model: it cannot respond
     * to a different injector, a different displacement, a fuel-pressure
     * sensor or a change of air temperature, and the same table means
     * something different on every engine it is copied to.
     *
     * `rl` is ME7's own quantity - relative Luftfuellung - and the definition
     * is Bosch's: 100 % is the charge that fills the swept volume at 0 degC
     * and 1013 hPa. See the maintainer's design records and
     * hc_airfuel.h. A naturally aspirated engine therefore reads about 92 % at
     * sea level on a warm day, and that is the definition rather than an error
     * to trim out.
     *
     * ALPHA-N REMAINS SELECTABLE. CAL_LOAD_TPS keeps throttle angle as the
     * axis for engines where manifold pressure says nothing useful - throttle
     * bodies, long-duration cams at idle - and it addresses the same tables.
     */
    {
        unsigned int cyl = cfg_u8(CFG_CYLINDERS);
        /* hc_cal_u16, NOT cfg_u16: the universal block is above
           HC_CFG_CORE and cfg_u16 takes an unsigned char offset, so
           it silently reads byte 2510 & 0xFF instead. The compiler
           does warn - C192, value truncated - and that warning is the
           only thing standing between this and a plausible wrong
           displacement. tests/test_config_access_types.py now fails
           on it too. */
        unsigned int disp = hc_cal_u16(CFG_U_DISPLACEMENT_CC);
        unsigned int vd = (cyl != 0u) ? (unsigned int)(disp / cyl) : 0u;
        unsigned int t_x10 = hc_af_charge_t_x10(eng_iat_dc);
        unsigned int rho = hc_af_density_x1000(eng_map_kpa_x10, t_x10);
        unsigned long charge = hc_af_charge_x100(rho, vd);
        unsigned int ve_x10;
        unsigned long air;

        /* CAL_FUEL_MAP holds VOLUMETRIC EFFICIENCY, 0.1 % per count
           (V98r2 u16; 1 % in V98, 0.5 % until V97). */
        ve_x10 = hc_cal_map16(CAL_FUEL_MAP, CAL_FUEL_RPM_AX,
                              CAL_FUEL_LOAD_AX, rpm,
                              (hc_cal_u8(CAL_LOAD_SOURCE) == CAL_LOAD_TPS)
                              ? eng_tps_x10 : eng_map_kpa_x10);
        if (ve_x10 > VE_MAX_X10) {
            ve_x10 = VE_MAX_X10;
        }
        air = hc_af_air_x100(charge, ve_x10);
        eng_air_mg_x10 = (unsigned int)((air > 655350uL) ? 65535uL
                                                        : (air / 10uL));
        eng_rl_x10 = hc_af_rl_x10(air, vd);

        if (hc_cal_u8(CAL_LOAD_SOURCE) == CAL_LOAD_TPS) {
            eng_load = eng_tps_x10;
        } else {
            eng_load = eng_rl_x10;
        }
    }

    /* ----------------------------------------------------------- cranking */
    {
        unsigned int crank_max = cfg_u16(CFG_CRANK_RPM_MAX);

        /* Hysteresis, the way MS 4 Sport does it with STARTENDREV_HYS: a bare
           threshold chatters at exactly the speed a starting engine hovers
           around, and chattering between a cranking pulse and a running one is
           how an engine refuses to catch. */
        if (eng_cranking) {
            if (rpm > (unsigned int)(crank_max + 100u)) {
                eng_cranking = 0;
            }
        } else {
            if (rpm < crank_max) {
                eng_cranking = 1;
            }
        }
    }

    /* ------------------------------------------------------------- dwell --
     * Against battery voltage, because a coil charges more slowly on a sagging
     * battery and cranking is exactly when the battery sags. A fixed dwell is
     * wrong at the one moment it matters most. */
    eng_dwell_x100 = hc_cal_curve16(CAL_DWELL_BATT_AX, CAL_DWELL_BATT_VAL,
                                    8u, (unsigned int)(eng_batt_dv * 10u));
    /* V77. THE CRANKING DWELL WAS A KNOB NOTHING READ. crankingDwellMsX100 is
       on the page, seeded to 4.00 ms by hc_config_manager.c and shown to the
       tuner as "Cranking dwell" - and until now no linked module read
       CFG_U_CRANK_DWELL_X100, so the battery curve decided cranking dwell
       whatever was typed there. rusEFI's semantics, which is what the field
       promises: while cranking, a non-zero value replaces the curve. Zero
       keeps the curve. */
    if (eng_cranking) {
        unsigned int cd = hc_cal_u16(CFG_U_CRANK_DWELL_X100);
        if (cd != 0u) {
            eng_dwell_x100 = cd;
        }
    }

    eng_deadtime_us = hc_cal_curve16(CAL_DWELL_BATT_AX, CAL_DEADTIME_VAL,
                                     8u, (unsigned int)(eng_batt_dv * 10u));

    /* ---------------------------------------------------------- ignition --
     *
     * FIXED TIMING FIRST, and it short-circuits everything else.
     *
     * rusEFI's IgnitionState::getAdvance() opens the same way, with the same
     * comment: "fixed timing is the simple: cranking/running does not matter,
     * no corrections!". That is the point of the mode - a timing light must
     * see ONE angle, not an angle the ECU is still deciding, or the
     * measurement says nothing about the tooth offset it was meant to check.
     *
     * This is the first commissioning step that closes the loop between what
     * the ECU commands and where the spark actually lands. Until it has been
     * done, every cell in the ignition map is a hypothesis. */
    if (hc_cal_u8(CFG_U_TIMING_MODE) != 0u) {
        eng_adv_x10 = ign_clamp(hc_cal_u16(CFG_U_FIXED_TIMING_X10));
    } else {
        cell = hc_cal_map(CAL_IGN_MAP, CAL_IGN_RPM_AX, CAL_IGN_LOAD_AX,
                          rpm, eng_load);
        /* One count is 0.5 degrees with a -20 degree offset, so the map can
           hold retard as well as advance. */
        if (cell < 40u) {
            eng_adv_x10 = 0;                /* retarded past TDC: treat as 0 */
        } else {
            eng_adv_x10 = (unsigned int)((cell - 40u) * 5u);
        }
        if (eng_cranking) {
            /* A separate, fixed cranking angle - MS 4 Sport's ignstart.
               Advance from a map interpolated against a barely-moving rpm is
               not what an engine wants off the starter. */
            eng_adv_x10 = cfg_u16(CFG_IGN_ADVANCE_DEG_X10);
        }
#if defined(TGT_ENGINE_RUNTIME)
        /* COOLANT AND INTAKE-AIR CORRECTIONS (hcigncorr711.c, far;
           rusEFI ignitionCltCorr / ignitionIatCorr) - running only, never
           in fixed timing (the timing light must see ONE angle) and never
           while cranking (the cranking angle is its own setting). Published
           so a log separates the table from its corrections. */
        eng_ign_corr_x10 = 0;
        if (!eng_cranking) {
            long a;
            eng_ign_corr_x10 = hc_ign_corr_x10(eng_clt_dc, eng_iat_dc);
            a = (long)eng_adv_x10 + (long)eng_ign_corr_x10;
            eng_adv_x10 = (unsigned int)((a < 0L) ? 0L : a);
        }
#endif
        /* AND THE CEILING APPLIES TO BOTH PATHS. Cell 255 decodes to 107.5
           degrees and CFG_IGN_ADVANCE_DEG_X10 is a page word that a corrupt
           record can set to anything. */
        eng_adv_x10 = ign_clamp(eng_adv_x10);
    }

    /* -------------------------------------------------------------- fuel -- */
    eng_afr_x10 = hc_cal_map(CAL_AFR_MAP, CAL_IGN_RPM_AX, CAL_IGN_LOAD_AX,
                             rpm, eng_load);

    /* THE CANONICAL FUEL TARGET IS LAMBDA. The map is stored as AFR x 10
       because that is the page layout every flashed image already has, and
       moving it would break every burned page for no gain - but AFR is a
       number about ONE fuel. Lambda is the number about the ENGINE, and it is
       what a wideband measures, what a closed loop trims, and what stays
       meaningful on E85 or methanol.
     *
     * So the conversion happens HERE, once, through the one configured
     * stoichiometric ratio, and everything downstream reasons in lambda:
     *
     *     lambda = AFR / AFR_stoich
     *            = (eng_afr_x10 / 10) / (stoich_x100 / 100)
     *            = eng_afr_x10 * 10 / stoich_x100
     *
     * x1000 for three decimals. 32-bit intermediate on purpose: at the
     * stoichiometric point the numerator is 147 * 10000 = 1 470 000, which
     * does not fit in 16 bits and would silently wrap. */
    {
    }

#if defined(TGT_ENGINE_RUNTIME)
    /* INTERPOLATED (hctrans711.c, far). The nearest-cell-below lookup
       below stepped the fuel by up to 9 % each time the coolant crossed a
       10 C bin (the AWT curve 122 -> 116 % at 20 -> 30 C) - a lean/rich
       step while warming up that no tuner can calibrate away. */
    eng_warmup_pct = hc_trans_warmup(eng_clt_dc);
#else
    {
        unsigned char i;
        unsigned int best = 0;

        /* The enrichment curve is a u8 value against a u16 axis, so it cannot
           go through hc_cal_curve16. Nearest cell below, which for a warm-up
           curve is the safe direction: it enriches a little longer rather than
           leaning out early. */
        for (i = 0; i < CAL_AXIS_N; i++) {
            if (hc_cal_u16((unsigned int)(CAL_CLT_ENR_AX + 2u * i))
                <= eng_clt_dc) {
                best = i;
            }
        }
        eng_warmup_pct = hc_cal_u8((unsigned int)(CAL_CLT_ENR_VAL + best));
        if (eng_warmup_pct == 0) {
            eng_warmup_pct = 100u;
        }
    }
#endif

    if (eng_cranking) {
        eng_ti_base_us = hc_cal_curve16(CAL_CRANK_PW_AX, CAL_CRANK_PW_VAL,
                                        8u, eng_clt_dc);
#if defined(TGT_ENGINE_RUNTIME)
        /* THE CRANKING TABLE KEEPS ITS MEANING - the pulse each of the
           TWO per-cycle injections of batch gets (what the AWT started on,
           V91..V96) - and the value below is the CYCLE's open time, so a
           sequential start (one pulse) delivers the same mass. */
        {
            unsigned long c2 = (unsigned long)eng_ti_base_us * 2uL;
            eng_ti_base_us = (unsigned int)((c2 > 60000uL) ? 60000uL : c2);
        }
#endif
    } else {
        /* THE FUEL IS COMPUTED FROM AIR, NOT LOOKED UP.
         *
         * air mass -> fuel mass at the target lambda -> the time the injector
         * must be OPEN to pass it. Dead time is added later and never scaled.
         * Every step is hc_airfuel.c, checked against a float reference in
         * tools/me711_fuel_golden.py.
         *
         * The VE table was read during the load calculation above, so the air
         * mass is already in eng_air_mg_x10 and nothing is looked up twice. */
        unsigned long air_x100 = (unsigned long)eng_air_mg_x10 * 10uL;
        unsigned long fuel_x100;
        unsigned int flow;
        unsigned int lam = eng_lambda_x1000();

        flow = hc_af_flow_x100(hc_cal_u16(CFG_U_INJ_FLOW_CCMIN));
        /* NO PRESSURE CORRECTION IS APPLIED YET, and pretending otherwise
           would be worse than not doing it. hc_af_flow_at_dp_x100() exists and
           is proven against the reference, but it needs the pressure ACROSS
           the injector - rail minus manifold - and no fuel-pressure sensor is
           configured or routed on this target. Correcting by the rated
           pressure against itself would be a no-op dressed up as a feature.
           When a sensor exists, this is the one line that changes. */
        fuel_x100 = hc_af_fuel_x100(air_x100,
                                    hc_cal_u16(CFG_U_STOICH_X100), lam);
#if defined(TGT_ENGINE_RUNTIME)
        /* V92 SPLIT THE CYCLE'S FUEL HERE (batch/semi-sequential: x0.5, V91
         * had injected the whole cycle at every pulse, λ ≈ 0.33 on the AWT).
         * V97 MOVES THE SPLIT TO WHERE THE PULSES ARE: eng_ti_base_us is now
         * the open time ONE CYLINDER needs PER CYCLE, and hcsched_dry.c gives
         * each injection event (that time / the pulses that cylinder
         * receives this cycle) + dead time. That is what makes a switch
         * between batch-like fallback (two per cycle) and true sequential
         * (one) conserve the mass per cylinder - per cylinder, at the event
         * that switches it (the maintainer's design notes). Dead time is still
         * added per pulse and never divided. ME7.1.1 only: ME7.5's hcinj.c
         * keeps the per-pulse value it always had. */
#endif
        eng_ti_base_us = hc_af_te_us(fuel_x100, flow);
        eng_ti_base_us = (unsigned int)(((unsigned long)eng_ti_base_us
                                         * eng_warmup_pct) / 100uL);
    }

    accel_service();
    if (!eng_cranking) {
        eng_ti_base_us = (unsigned int)(eng_ti_base_us + eng_accel_us);
    }
#if defined(TGT_ENGINE_RUNTIME)
    /* TRANSIENT FUEL - the X-tau wall film and after-start
       (engine/hctrans.c via hctrans711.c, far), on the CYCLE's open time so
       every injection mode gets the same correction. Off (transEnable 0) it
       passes the value through. A cut (any owner's bit, this pass) injects
       nothing and lets the film dry, so the re-entry is compensated. */
    eng_ti_base_us = hc_trans_fuel(eng_ti_base_us, eng_cranking,
                                   (unsigned char)((eng_fuelcut
                                       & (ENG_CUT_REV | ENG_CUT_OVERRUN
                                          | ENG_CUT_BOOST | ENG_CUT_LIMP))
                                       != 0u));
#endif

    /* --------------------------------------------------------- overrun ----
     * Closed throttle above a speed means the driver has lifted, and burning
     * fuel into an engine that is being driven by the car achieves nothing but
     * heat and hydrocarbons. It resumes at a LOWER speed than it cuts at, or
     * it would chatter across the boundary at exactly the moment the engine is
     * about to need fuel again.
     */
    {
        unsigned int cut_rpm = hc_cal_u16(CAL_OVERRUN_RPM);
        unsigned int resume = hc_cal_u16(CAL_OVERRUN_RESUME);

        if (cut_rpm == 0u || eng_cranking) {
            overrun_cut = 0;
        } else if (rpm > cut_rpm
                   && eng_tps_x10 < hc_cal_u16(CAL_OVERRUN_TPS_X10)) {
            overrun_cut = 1;
        } else if (rpm < resume || eng_tps_x10 >= hc_cal_u16(CAL_OVERRUN_TPS_X10)) {
            overrun_cut = 0;
        }
    }
    /* CLEAR AND SET ONLY THIS MODULE'S OWN BIT.

       This used to be a plain assignment, and eng_fuelcut is a SHARED
       word: hcmain.c ORs ENG_CUT_BOOST and ENG_CUT_REV into it after
       eng_service() returns, because overboost is decided in hcboost.c
       and the rev limiter in hcsched.c. So every pass began by wiping
       two other owners' reasons and ended by putting them back, and
       for the stretch in between the word said the engine was not
       being cut when it was.

       MEASURED on the linked image with overboost latched
       (boost_state 0x0004): eng_fuelcut read 0x0000 in 22 of 400
       samples. Nothing in the injector path happens to look during
       that window today - inj_plan() runs after the OR - but the
       telemetry does, so the bench was being told the cut had gone
       away five percent of the time, and any future reader placed one
       line earlier would have inherited a real fuel cut that
       intermittently did not exist.

       Each owner now clears and sets its own bit and touches nobody
       else's. That is the whole of the arbitration this word needs,
       and it costs one AND. */
    eng_fuelcut = (unsigned int)((eng_fuelcut & ~ENG_CUT_OVERRUN)
                                 | (overrun_cut ? ENG_CUT_OVERRUN : 0u));

    /* Dead time is ADDED, never scaled: it is the time the valve takes to
       open, and it does not get bigger because the engine wants more fuel.
       MS 4 Sport keeps the same distinction - ti_1..10p is the duration
       BEFORE the valve opening time is applied. */
    {
        unsigned long t = (unsigned long)eng_ti_base_us
                        + (unsigned long)eng_deadtime_us;

        if (t > 60000uL) {
            t = 60000uL;               /* never longer than a T7 wrap */
        }
        eng_ti_us = (unsigned int)t;
    }
#endif
}

#if defined(TGT_ENGINE_RUNTIME)
/* Complete entry for callers that do not own the target service raster. */
void eng_service(void)
{
    eng_acquire();
    eng_calculate();
}
#endif

unsigned int eng_lambda_x1000(void)
{
    /* DERIVED, NOT STORED. Lambda is a pure function of the AFR target and
       one calibration word, so keeping a copy of it in near RAM buys nothing
       and costs two bytes - which is not a rounding error here: those exact
       two bytes pushed the ME7.5 m0 build from 1727 to 1729 bytes of near
       data, one byte past what the C167 actually has once the PEC pointer
       file at 0xFCE0-0xFCFF is honoured. See tools/near_ram_hazard_proof.py.

       The page stores AFR x 10 because every flashed image has that layout.
       This is the one place that converts, so the runtime still reasons in
       lambda and there is still exactly one definition of the conversion. */
#if defined(TGT_ENGINE_RUNTIME)
    /* THE TABLE IS LAMBDA x 147 (rusEFI lambdaTable's own scale) - the
       same bytes as AFR x 10 on gasoline, so no page changed - and lambda
       no longer depends on the stoichiometric ratio. */
    return (unsigned int)(((unsigned long)eng_afr_x10 * 1000uL) / 147uL);
#else
    unsigned int st = hc_cal_u16(CFG_U_STOICH_X100);

    if (st == 0u) {
        /* A zero would divide by zero. hc_validate() refuses a page that
           contains one, but this runs whatever the page says, so it cannot
           rely on that. Gasoline, and the error stays visible because the
           target stops tracking the map. */
        st = 1470u;
    }
    return (unsigned int)(((unsigned long)eng_afr_x10 * 10000uL)
                          / (unsigned long)st);
#endif
}
