/*
 * hcwb.c - see hcwb.h. SHARED, SFR-FREE, 16-BIT ONLY.
 *
 * Numbers and their sources (docs/ARCHITECTURE.md has the chain):
 *   rusEFI wideband heater_control.cpp (SOFTWARE REFERENCE IMPLEMENTATION):
 *     preheat 2 V, ramp from 7 V at 0.4 V/s to 12 V, closed loop at
 *     target - 30 C, 60 s warm-up timeout, over/under heat +-100 C for 0.5 s,
 *     supply on 9.5 V / off 8.5 V after 0.5 s, stop >= 23 V, PI 0.3 / 0.3 V
 *     per ohm around 7.5 V, integrator clamp 3 V; LSU 4.2 at 80 ohm; a
 *     sensor already above 550 C (HEATER_FAST_HEATING_THRESHOLD_T, dual board)
 *     skips preheat and ramps from 9 V. HaniCore takes 300 ohm (~598 C,
 *     sampling.cpp lsu42 table): rusEFI's 545 ohm sits at the top of what
 *     this board can measure (UR saturates near 1010 raw; with the bench's
 *     URcal of 187 that is ~609 ohm), 300 ohm is mid-scale.
 *   HaniCore deviation, stated: the cold preheat is 15 s (rusEFI
 *     HEATER_PREHEAT_TIME 5 s) - water shock on a cold exhaust costs a sensor,
 *     the extra 10 s only costs lambda on a cold start.
 *   the Bosch CJ120 datasheet (EXACT COMPONENT DATASHEET): INIT_REG1 bits, LA pump zero
 *     0.285..0.315 VCC, UR zero 0.05..0.063 VCC, UA swing 0.20..VCC-0.18,
 *     DIAG codes.
 *   the ME7.1.1 schematic (SAME-GENERATION SCHEMATIC): R1076 = 82.5 ohm Ri reference,
 *     61.9 ohm pump shunt, UA -> AN6/AN4, UR -> ASIC AN12/13.
 *   OEM binary (EXACT TARGET BINARY): PA follows a per-bank warm-up flag
 *     [0x862EAA, 0x88FDC0]; which polarity pumps is NOT decided by it - the
 *     car and rusEFI decide it (hcwb.h: PA is active low).
 */
#include "hcwb.h"

#define RI_CLOSED_X10  1200u   /* 1.45 x: ~30 C below the operating point  */
#define RI_FAST_X10    3000u   /* ~598 C: warm, therefore dry (see above)    */
#define RI_OK_LO_X10    701u   /* +-15 %                                    */
#define RI_OK_HI_X10    949u
#define RI_OVER_X10     578u   /* 0.70 x: ~+100 C                           */
#define RI_UNDER_X10   2145u   /* 2.60 x: ~-100 C                           */
#define UR0_RAW          58u   /* datasheet zero point, middle              */
#define URCAL_SPAN_MIN   20u
#define UR_MAX          982u
#define UA0_MIN         291u
#define UA0_MAX         322u
#define UA_MIN_RAW       41u   /* 0.20 V                                    */
#define UA_MAX_RAW      986u   /* VCC - 0.18 V                              */
#define CAL_SETTLE_MS   300u
#define CHIP_WAIT_MS   3000u
#define DEW_MS        15000u   /* preheat at 2 V while the exhaust is wet  */
#define V_PREHEAT_DV     20u
#define V_START_DV       70u
#define V_FAST_DV        90u   /* rusEFI: a warm sensor ramps from 9 V       */
#define V_MAX_DV        120u
#define RAMP_TIMEOUT_MS 60000u
#define HEAT_AFTERRUN_MS 30000u /* the heater keeps running this
                                   long after the engine stops turning,
                                   so a stall or a restart does not
                                   throw the warm-up away. Longer than
                                   every stall-to-crank gap in the AWT
                                   evidence (3..7 s); bounded by the key
                                   (!key_on resets above).           */
#define VB_ON_DV         95u
#define VB_OFF_DV        85u
#define VB_MAX_DV       230u
#define INTEG_MAX     30000    /* 0.1 mV = 3 V                              */
/* A DIAG failure latches only after it has PERSISTED this long with the
   supply at or above DIAG_VB_DV. The AWT car (2026-10-10) latched "heater
   open" from one DIAG read in the starter's dip to 8 V: the CJ120 itself
   lost verification for a moment and its heater stage cannot judge a load
   at that voltage. Bosch suspends heater diagnosis in start; 0.5 s is the
   over/underheat confirm time below. */
#define DIAG_CONFIRM_MS 500u
#define DIAG_VB_DV      105u
/* ONE MISSED CJ120 EXCHANGE IS NOT A COLD SENSOR. A timed-out SSC exchange
   (hcio711.c cj_tmo) unverifies the chip; the target rewrites INIT_REG1,
   reads it back, checks IDENT and lets the analog path settle 300 ms - with
   one bank ~0.4 s, with two ~0.45 s of samples that are not measurements.
   Until 2026-10-10 that reset pa_ms (1 s to re-verify), cut the heater and
   zeroed ready_ms: the AWT car showed 1..5 s of lambda lost per timeout
   (VEHICLE_CAPTURE_20261010T180458Z, cjTmo 1..6). While the bank is CLOSED
   or READY and its last good acquisition (ur_seen) is younger than this, the
   heater duty, pump time, readiness and the last lambda are HELD. A longer
   gap is the old path; a real chip loss still faults at CHIP_WAIT_MS. */
#define GAP_HOLD_MS     600u
/* READY -> CLOSED needs Ri outside the +-15 % band for this long (the
   over/underheat confirm time), not one sample. */
#define RI_BAND_CONFIRM_MS 500u

static unsigned int el(unsigned int now, unsigned int then)
{
    return (unsigned int)((now - then) & 0xFFFFu);
}

unsigned int hcwb_lambda_ip(int ip)
{
    unsigned int phi, q, rem, out, k;

    if (ip < -1850) {
        return 700u;
    }
    if (ip > 1190) {
        return 2000u;
    }
    if (ip < 0) {
        k = (unsigned int)(-ip);
        phi = (unsigned int)(9915u + k * 2u + (k * 7u) / 20u);
    } else {
        k = (unsigned int)ip;
        phi = (unsigned int)(9915u - k * 4u - (k * 13u) / 90u);
    }
    phi = (unsigned int)(phi / 10u);
    q = 1000u / phi;
    rem = 1000u % phi;
    out = (unsigned int)(q * 1000u);
    for (k = 100u; k != 0u; k = (unsigned int)(k / 10u)) {
        rem = (unsigned int)(rem * 10u);
        out = (unsigned int)(out + (rem / phi) * k);
        rem = (unsigned int)(rem % phi);
    }
    return out;
}

/* raw (5 V, 10 bit) -> mV: 5000 / 1023 = 5 - 9/80 */
static int raw_mv(unsigned int raw)
{
    return (int)(raw * 5u - (raw * 9u) / 80u);
}

/* mV across the pump shunt amplifier -> uA: 1 / (8 x 61.9 ohm) */
static int ip_ua(int dmv)
{
    return (int)(dmv * 2 + dmv / 52);
}

unsigned int hcwb_lambda_raw(unsigned int ua_raw)
{
    return hcwb_lambda_ip(ip_ua(raw_mv(ua_raw) - 1500));
}

unsigned int hcwb_ri_x10(unsigned int ur, unsigned int urc)
{
    unsigned int num, den, q, rem, r;

    if (ur == HCWB_UR_NONE || urc == HCWB_UR_NONE
        || urc <= (unsigned int)(UR0_RAW + URCAL_SPAN_MIN)) {
        return 0u;
    }
    if (ur <= UR0_RAW) {
        return 1u;
    }
    if (ur >= UR_MAX) {
        return 60000u;          /* saturated = open / cold, never a
                                   finite Ri (a cold LSU saturates UR) */
    }
    num = (unsigned int)(ur - UR0_RAW);
    den = (unsigned int)(urc - UR0_RAW);
    q = num / den;
    if (q >= 70u) {
        return 60000u;
    }
    rem = num % den;
    r = (unsigned int)(q * HCWB_RCAL_X10);
    r = (unsigned int)(r + ((((rem * 64u) / den) * HCWB_RCAL_X10) >> 6));
    return (r == 0u) ? 1u : r;
}

/* DIAG 7..6 heater, 5..4 IA/IP, 3..2 UN, 1..0 VM: 00 GND, 01 open (heater)
   / low battery (sensor lines), 10 UB, 11 no failure */
static unsigned char diag_fault(unsigned char diag, unsigned char lines)
{
    unsigned char h = (unsigned char)((diag >> 6) & 3u);

    /* heater 00 / 01 / 10 = HCWB_F_HEATER_GND / _OPEN / _UB (1 / 2 / 3) */
    if (h != 3u) {
        return (unsigned char)(h + 1u);
    }
    /* a line pair is 00 or 10 (GND / UB) exactly when its LOW bit is 0
       (01 = low battery is not a line fault, 11 = none) */
    if (lines) {
        if (!(diag & 0x10u)) {
            return HCWB_F_LINE_IAIP;
        }
        if (!(diag & 0x04u)) {
            return HCWB_F_LINE_UN;
        }
        if (!(diag & 0x01u)) {
            return HCWB_F_LINE_VM;
        }
    }
    return 0u;
}

static unsigned int veff_duty(unsigned int veff_dv, unsigned int vb)
{
    unsigned int r;

    if (vb < 60u || veff_dv == 0u) {
        return 0u;
    }
    r = (unsigned int)(((unsigned int)veff_dv * 100u) / vb);
    if (r > 100u) {
        r = 100u;
    }
    return (unsigned int)((r * r) / 10u);
}

/* Heater off - and lambda withheld: every path that stops the heater also
   stops the measurement (step() relies on it: only the gap hold keeps the
   previous lambda). */
static void heat_off(hcwb_t *w)
{
    w->duty_x10 = 0u;
    w->veff_dv = 0u;
    w->lambda = 0u;
    w->valid = 0u;
    w->ip_ua = 0;
}

static void fault(hcwb_t *w, unsigned char code)
{
    if (w->state != HCWB_ST_FAULT) {
        w->state = HCWB_ST_FAULT;
        w->fcode = code;
    }
    heat_off(w);
    w->want = HCWB_MODE_COLD;
}

void hcwb_init(hcwb_t *w)
{
    unsigned int i;
    unsigned char *p = (unsigned char *)w;

    for (i = 0u; i < sizeof(*w); i++) {
        p[i] = 0u;              /* no ?C_INIT on the target */
    }
    w->want = HCWB_MODE_COLD;
    w->cal_st = HCWB_CAL_NEED;
}

void hcwb_clear(hcwb_t *w)
{
    if (w->state == HCWB_ST_FAULT) {
        w->state = HCWB_ST_OFF;          /* the next step re-enters WAIT */
        w->fcode = 0u;
        w->integ = 0;
        w->ready_ms = 0u;
        w->cal_st = HCWB_CAL_NEED;
    }
}

/* the calibration: RA + LA, verified, settled, 8 samples */
static void cal(hcwb_t *w, const hcwb_in_t *in)
{
    switch (w->cal_st) {
    case HCWB_CAL_NEED:
        w->want = HCWB_MODE_CAL;
        w->cal_st = HCWB_CAL_SETTLE;
        w->cal_mark = in->ms;
        w->ur_miss = 0u;
        break;
    case HCWB_CAL_SETTLE:
        if (in->reg1 != HCWB_MODE_CAL || !in->chip_ok) {
            w->cal_mark = in->ms;
        } else if (el(in->ms, w->cal_mark) >= CAL_SETTLE_MS) {
            w->cal_st = HCWB_CAL_SAMPLE;
            w->cal_n = 0u;
            w->ua_sum = 0u;
            w->ur_sum = 0u;
            w->cal_seq = in->ur_sample.seq;
            w->cal_ua_seq = in->ua_sample.seq;
            w->cal_mark = in->ms;
        }
        break;
    case HCWB_CAL_SAMPLE:
        if (el(in->ms, w->cal_mark) < 25u) {
            break;
        }
        w->cal_mark = in->ms;
        if (!in->chip_ok || in->reg1 != HCWB_MODE_CAL
            || !in->ur_sample.valid || !in->ua_sample.valid
            || in->ur_sample.mode != HCWB_MODE_CAL
            || in->ua_sample.mode != HCWB_MODE_CAL
            || in->ur == HCWB_UR_NONE) {
            if (++w->ur_miss > 40u) {
                w->cal_st = HCWB_CAL_BAD;
                w->cal_why = 3u;
                w->want = HCWB_MODE_COLD;
            }
            break;
        }
        if (in->ur_sample.seq == w->cal_seq
            || in->ua_sample.seq == w->cal_ua_seq) break;
        w->cal_seq = in->ur_sample.seq;
        w->cal_ua_seq = in->ua_sample.seq;
        w->ua_sum = (unsigned int)(w->ua_sum + in->ua);
        w->ur_sum = (unsigned int)(w->ur_sum + in->ur);
        if (++w->cal_n >= 8u) {
            w->ua0 = (unsigned int)(w->ua_sum / 8u);
            w->urc = (unsigned int)(w->ur_sum / 8u);
            w->cal_why = 0u;
            if (w->ua0 < UA0_MIN || w->ua0 > UA0_MAX) {
                w->cal_why = 1u;
            } else if (w->urc <= (unsigned int)(UR0_RAW + URCAL_SPAN_MIN)
                       || w->urc > UR_MAX) {
                w->cal_why = 2u;
            }
            w->cal_st = w->cal_why ? HCWB_CAL_BAD : HCWB_CAL_OK;
            w->want = HCWB_MODE_COLD;
        }
        break;
    default:
        break;
    }
}

static void closed_loop(hcwb_t *w, const hcwb_in_t *in, unsigned int ri)
{
    int e, p, v;

    if (el(in->ms, w->step) < 50u) {
        return;
    }
    w->step = in->ms;
    /* e in 0.1 ohm, + = too cold. kP 0.3 V/ohm = 30 mV per 0.1 ohm; kI
       0.3 V/(ohm s) = 1.5 mV per 0.1 ohm per 50 ms (integrator in 0.1 mV) */
    e = (ri >= 60000u) ? 1000 : (int)ri - (int)HCWB_RCAL_X10;
    if (e > 1000) {
        e = 1000;
    }
    if (e < -1000) {
        e = -1000;
    }
    p = (int)(e * 15);
    if (p > 0 && w->integ > INTEG_MAX - p) {
        w->integ = INTEG_MAX;
    } else if (p < 0 && w->integ < -INTEG_MAX - p) {
        w->integ = -INTEG_MAX;
    } else {
        w->integ = (int)(w->integ + p);
    }
    v = (int)(7500 + w->integ / 10);        /* 4500..10500 mV */
    p = (int)(e * 30);
    if (p > 12000 - v) {
        v = 12000;
    } else if (p < -v) {
        v = 0;
    } else {
        v = (int)(v + p);
    }
    w->veff_dv = (unsigned char)((unsigned int)v / 100u);
    /* ri >= 1 here (see the switch in step()) */
    if (ri < RI_OVER_X10) {
        if (el(in->ms, w->over_mark) >= 500u) {
            fault(w, HCWB_F_OVERHEAT);
            return;
        }
    } else {
        w->over_mark = in->ms;
    }
    if (ri > RI_UNDER_X10) {
        if (el(in->ms, w->under_mark) >= 500u) {
            fault(w, HCWB_F_UNDERHEAT);
            return;
        }
    } else {
        w->under_mark = in->ms;
    }
    /* `mark` is free in CLOSED/READY (set at entry): Ri last in band */
    if (ri >= RI_OK_LO_X10 && ri <= RI_OK_HI_X10) {
        w->mark = in->ms;
        if (w->ready_ms < 60000u) {
            w->ready_ms = (unsigned int)(w->ready_ms + 50u);
        }
    } else if (el(in->ms, w->mark) >= RI_BAND_CONFIRM_MS) {
        w->ready_ms = 0u;
    }
    if (w->ready_ms >= 3000u && w->pa_ms >= 1000u) {
        w->state = HCWB_ST_READY;
    } else if (w->ready_ms == 0u) {
        w->state = HCWB_ST_CLOSED;
    }
}

static void step(hcwb_t *w, const hcwb_in_t *in)
{
    unsigned int d, ri;
    unsigned char f;
    unsigned char ri_ok, gap;
    int e;

    d = w->started ? el(in->ms, w->last_ms) : 0u;
    w->last_ms = in->ms;
    w->started = 1u;
    /* GAP_HOLD_MS: a regulating bank whose last qualified UR (ur_seen) is
       recent. Only used when this step has none (!ri_ok below). */
    gap = (unsigned char)((unsigned char)(w->state - HCWB_ST_CLOSED) < 2u
                          && el(in->ms, w->ur_seen) < GAP_HOLD_MS);
    /* the pump is on while the chip has VERIFIED the pump mode (PA = 0);
       through a gap the verified time is held, not restarted */
    if (in->chip_ok && in->reg1 == HCWB_MODE_PUMP) {
        /* saturating at 60000 (pa_ms never exceeds it) */
        w->pa_ms = (d > (unsigned int)(60000u - w->pa_ms)) ? 60000u
                 : (unsigned int)(w->pa_ms + d);
    } else if (!gap) {
        w->pa_ms = 0u;
    }
    /* lambda / valid / Ip are cleared by heat_off() on every withholding
       path and recomputed at the end; the gap path leaves them as they were
       (the last measurement, < GAP_HOLD_MS old). */

    /* Permission is a lifecycle, not a timestamp reusable after timer wrap.
       OFF cancels a tail immediately; a tail starts only after a legitimate
       running grant and expires once. Saturating subtraction is target-width. */
    if (!in->en || !in->key_on || in->hold
        || in->vbatt_dv < VB_OFF_DV || in->vbatt_dv >= VB_MAX_DV
        || (!w->supply_ok && in->vbatt_dv < VB_ON_DV)) {
        w->permission = 0u;
        w->tail_ms = 0u;
    } else if (in->heat_allow) {
        w->permission = (unsigned char)((in->afterrun && in->running) ? 1u : 0u);
        w->tail_ms = HEAT_AFTERRUN_MS;
    } else if (!in->afterrun) {
        w->permission = 0u;
        w->tail_ms = 0u;
    } else if (w->permission != 0u) {
        w->permission = 2u;
        w->tail_ms = (d >= w->tail_ms) ? 0u : (unsigned int)(w->tail_ms - d);
        if (!w->tail_ms) w->permission = 0u;
    }

    if (in->hold) {
        heat_off(w);                     /* a bench mode hold: nothing else */
        w->want = in->hold_mode;
        return;
    }
    if (!in->en || !in->key_on) {
        w->state = HCWB_ST_OFF;
        w->fcode = 0u;
        heat_off(w);
        w->integ = 0;
        w->ready_ms = 0u;
        w->cal_st = HCWB_CAL_NEED;       /* recalibrate at the next key-on */
        w->want = HCWB_MODE_COLD;
        w->ri_x10 = 0u;
        return;
    }
    if (w->state == HCWB_ST_OFF) {
        w->state = HCWB_ST_WAIT;
        w->mark = in->ms;
        w->chip_mark = in->ms;
        w->supply_mark = in->ms;
        w->ur_seen = in->ms;
        w->ur_live = 0u;
        w->diag_mark = in->ms;
    }
    if (w->state == HCWB_ST_FAULT) {
        fault(w, 0u);                    /* latched: heater off, cold mode */
        return;
    }

    /* calibration first, never while heating */
    if (w->cal_st != HCWB_CAL_OK && w->cal_st != HCWB_CAL_BAD) {
        heat_off(w);
        if (el(in->ms, w->mark) >= CHIP_WAIT_MS) {
            fault(w, in->chip_ok ? HCWB_F_NO_RI : HCWB_F_CHIP);
            return;
        }
        if (in->chip_ok) {
            cal(w, in);
        }
        return;
    }
    if (w->cal_st == HCWB_CAL_BAD) {
        fault(w, (unsigned char)(w->cal_why == 3u ? HCWB_F_NO_RI : HCWB_F_CAL));
        return;
    }
    if (!in->chip_ok) {
        w->diag_mark = in->ms;
        if (el(in->ms, w->chip_mark) >= CHIP_WAIT_MS) {
            fault(w, HCWB_F_CHIP);
            return;
        }
    } else {
        w->chip_mark = in->ms;
        f = diag_fault(in->diag, (unsigned char)(w->state >= HCWB_ST_CLOSED
                                                 && w->pa_ms >= 200u));
        if (!f || in->vbatt_dv < DIAG_VB_DV) {
            w->diag_mark = in->ms;
        } else if (el(in->ms, w->diag_mark) >= DIAG_CONFIRM_MS) {
            fault(w, f);
            return;
        }
    }

    /* supply */
    if (in->vbatt_dv < VB_OFF_DV || in->vbatt_dv >= VB_MAX_DV) {
        w->supply_ok = 0u;
        w->supply_mark = in->ms;
    } else if (in->vbatt_dv >= VB_ON_DV) {
        if (el(in->ms, w->supply_mark) >= 500u) {
            w->supply_ok = 1u;
        }
    } else {
        w->supply_mark = in->ms;
    }

    ri_ok = (unsigned char)(in->chip_ok && in->ur_sample.valid
                 && in->ur_sample.mode == in->reg1
                 && (in->reg1 == HCWB_MODE_COLD || in->reg1 == HCWB_MODE_PUMP)
                 && in->ur != HCWB_UR_NONE);
    ri = ri_ok ? hcwb_ri_x10(in->ur, w->urc) : 0u;
    w->ri_x10 = ri;
    /* Record qualified UR leaving its rail. This separates observed warming
       from persistently railed acquisition, not physical root causes. */
    if (ri_ok && in->ur < UR_MAX) {
        w->ur_live = 1u;
    }
    if (in->chip_ok && !ri_ok && w->state >= HCWB_ST_PREHEAT) {
        if (el(in->ms, w->ur_seen) >= 1000u) {
            fault(w, HCWB_F_NO_RI);
            return;
        }
    } else if (ri_ok) {
        w->ur_seen = in->ms;
    }

    /* Target policy supplies direct permission; only an explicitly granted
       RUNNING tail can continue after it is withdrawn. The saturating tail
       above expires terminally and cannot resurrect at a 16-bit wrap.
       IGNITION heating is an installation choice, not proof that the actual
       H+ feed remains powered through cranking, stall and run-on. */
    if (!w->supply_ok
        || (!in->heat_allow && w->permission == 0u)) {
        if (w->state != HCWB_ST_WAIT) {
            w->state = HCWB_ST_WAIT;
            w->mark = in->ms;
        }
        heat_off(w);
        w->integ = 0;
        w->ready_ms = 0u;
        w->ur_live = 0u;
        w->want = HCWB_MODE_COLD;
        return;
    }
    /* No heater-control/temperature transition from a cached adjustment
       sample, an unacknowledged mode, or stale acquisition. */
    if (!ri_ok) {
        w->step = in->ms;
        w->over_mark = in->ms;
        w->under_mark = in->ms;
        if (gap) {
            /* HOLD: heater duty, mode (want), ready_ms and pa_ms as they
               were; lambda/Ip as last measured - a measurement < 0.6 s old.
               The Ri-band confirm restarts like the over/under marks: a gap
               is no evidence the sensor left its band. */
            w->mark = in->ms;
            /* a held value is marked as such (why HELD), never as fresh:
               0 -> 0, 1 -> 2, 2 -> 2 (branch-free: FCODE has no room) */
            w->valid = (unsigned char)((w->valid + 1u) & 2u);
            return;
        }
        heat_off(w);
        w->ready_ms = 0u;
        return;
    }

    /* ri >= 1 from here on: the state machine runs only with the calibration
       OK (urc inside UR0+SPAN..UR_MAX) and ri_ok (ur tagged), and then
       hcwb_ri_x10() never returns 0 - so no "ri != 0" test is needed */
    switch (w->state) {
    case HCWB_ST_WAIT:
        w->state = HCWB_ST_PREHEAT;
        w->mark = in->ms;
        w->veff_dv = V_PREHEAT_DV;
        break;
    case HCWB_ST_PREHEAT:
        w->veff_dv = V_PREHEAT_DV;
        if (ri <= RI_CLOSED_X10) {
            w->state = HCWB_ST_CLOSED;           /* already hot: a restart */
            w->mark = in->ms;
            w->integ = 0;
            w->step = in->ms;
            w->over_mark = in->ms;
            w->under_mark = in->ms;
        } else if (ri <= RI_FAST_X10) {
            w->state = HCWB_ST_RAMP;             /* warm = dry, rusEFI */
            w->veff_dv = V_FAST_DV;
            w->step = in->ms;
            w->mark = in->ms;
        } else if (el(in->ms, w->mark) >= DEW_MS) {
            w->state = HCWB_ST_RAMP;
            w->veff_dv = V_START_DV;
            w->step = in->ms;
            w->mark = in->ms;
        }
        break;
    case HCWB_ST_RAMP:
        if (el(in->ms, w->step) >= 250u) {
            w->step = in->ms;
            if (w->veff_dv < V_MAX_DV) {
                w->veff_dv++;                    /* 0.1 V / 250 ms = 0.4 V/s */
            }
        }
        if (ri <= RI_CLOSED_X10) {
            w->state = HCWB_ST_CLOSED;
            w->mark = in->ms;
            e = (int)w->veff_dv - 75;            /* bumpless: carry the ramp */
            if (e > 30) {
                e = 30;
            }
            if (e < -30) {
                e = -30;
            }
            w->integ = (int)(e * 1000);
            w->over_mark = in->ms;
            w->under_mark = in->ms;
        } else if (el(in->ms, w->mark) >= RAMP_TIMEOUT_MS) {
            /* Distinguish persistently railed UR from observed UR movement
               without reaching temperature. Neither proves actual H+ or
               heating current; physical root cause requires measurement. */
            fault(w, (unsigned char)(w->ur_live ? HCWB_F_NO_HEAT
                                                : HCWB_F_OPEN_CELL));
            return;
        }
        break;
    case HCWB_ST_CLOSED:
    case HCWB_ST_READY:
        closed_loop(w, in, ri);
        if (w->state == HCWB_ST_FAULT) {
            return;
        }
        break;
    default:
        break;
    }
    w->duty_x10 = veff_duty(w->veff_dv, in->vbatt_dv);
    w->want = (unsigned char)((w->state == HCWB_ST_CLOSED
                               || w->state == HCWB_ST_READY)
                              ? HCWB_MODE_PUMP : HCWB_MODE_COLD);

    w->lambda = 0u;
    w->valid = 0u;
    w->ip_ua = 0;
    /* the raw measurement: whenever the pump zero is known and UA is
       inside the amplifier swing - a diagnostic, never lambda */
    if (w->cal_st == HCWB_CAL_OK && in->ua_sample.valid
        && in->ua_sample.mode == HCWB_MODE_PUMP && in->reg1 == HCWB_MODE_PUMP
        && in->ua >= UA_MIN_RAW && in->ua <= UA_MAX_RAW) {
        w->ip_ua = ip_ua(raw_mv(in->ua) - raw_mv(w->ua0));
    }

    /* lambda: a measurement only when everything above holds.
       V100: NOT gated on the engine turning. rusEFI publishes lambda from
       the sensor's own readiness (heater_control.cpp drives the heater from
       supply + HeaterAllow; nothing in the wideband path asks whether the
       engine runs), and whether a reading may STEER FUELLING is a separate
       question that belongs to the closed loop. Gating the measurement here
       would also defeat the whole point of ignition-on heating: warming the
       sensor before a start so READY is reached early is only useful if the
       value is then visible. */
    if (w->state == HCWB_ST_READY && w->pa_ms >= 1000u
        && w->cal_st == HCWB_CAL_OK && in->chip_ok && in->diag == 0xFFu
        && in->reg1 == HCWB_MODE_PUMP && in->ua_sample.valid
        && in->ua_sample.mode == HCWB_MODE_PUMP
        && in->ua >= UA_MIN_RAW && in->ua <= UA_MAX_RAW
        && in->ur != HCWB_UR_NONE) {
        /* every condition of the Ip block above holds here: same Ip */
        w->lambda = hcwb_lambda_ip(w->ip_ua);
        w->valid = 1u;
    }
}

/* the reason lambda is withheld, in the order the step decides it */
static unsigned char why(const hcwb_t *w, const hcwb_in_t *in)
{
    if (w->valid) {
        /* valid 1 -> HCWB_WHY_VALID (0), 2 -> HCWB_WHY_HELD (16) */
        return (unsigned char)((w->valid & 2u) << 3);
    }
    if (in->hold) {
        return HCWB_WHY_HOLD;
    }
    if (w->state == HCWB_ST_OFF) {
        return HCWB_WHY_OFF;
    }
    if (w->state == HCWB_ST_FAULT) {
        return HCWB_WHY_FAULT;
    }
    if (!in->chip_ok) {
        return HCWB_WHY_CHIP;
    }
    if (w->cal_st != HCWB_CAL_OK) {
        return HCWB_WHY_CAL;
    }
    if (!in->ur_sample.valid || in->ur_sample.mode != in->reg1
        || (in->reg1 != HCWB_MODE_COLD && in->reg1 != HCWB_MODE_PUMP)) {
        return HCWB_WHY_UR;
    }
    switch (w->state) {
    case HCWB_ST_WAIT:
        /* WAIT now means the heater is not PERMITTED (policy, supply or
           the engine-running policy), so say which. */
        return in->heat_allow ? HCWB_WHY_SUPPLY : HCWB_WHY_ENGINE;
    case HCWB_ST_PREHEAT:
        return HCWB_WHY_PREHEAT;
    case HCWB_ST_RAMP:
        return HCWB_WHY_RAMP;
    case HCWB_ST_CLOSED:
        return HCWB_WHY_SETTLE;
    default:
        break;
    }
    if (w->pa_ms < 1000u) {
        return HCWB_WHY_PUMP;
    }
    if (in->diag != 0xFFu) {
        return HCWB_WHY_DIAG;
    }
    if (in->ur == HCWB_UR_NONE) {
        return HCWB_WHY_UR;
    }
    return HCWB_WHY_UA;         /* READY, clean, pumping: only UA is left */
}

void hcwb_step(hcwb_t *w, const hcwb_in_t *in)
{
    step(w, in);
    w->why = why(w, in);
}

unsigned int hcwb_pair_step(hcwb_t w[2], const hcwb_pair_in_t *in)
{
    static hcwb_in_t b_in;        /* static: the C167 user stack is 256 bytes */
    unsigned int status = 0u;
    unsigned char b;
    hcwb_t *k;

    for (b = 0u; b < 2u; b++) {
        k = &w[b];
        b_in.ms = in->ms;
        b_in.ua = in->ua[b];
        b_in.ur = in->ur[b];
        b_in.vbatt_dv = in->vbatt_dv;
        b_in.en = (unsigned char)((in->en_mask >> b) & 1u);
        b_in.key_on = in->key_on;
        b_in.running = in->running;
        b_in.heat_allow = in->heat_allow;
        b_in.afterrun = in->afterrun;
        b_in.ua_sample = in->ua_sample[b];
        b_in.ur_sample = in->ur_sample[b];
        b_in.chip_ok = in->chip_ok[b];
        b_in.reg1 = in->reg1[b];
        b_in.diag = in->diag[b];
        b_in.hold = in->hold;
        b_in.hold_mode = in->hold_mode;
        hcwb_step(k, &b_in);
        if (k->valid) {
            status |= (unsigned int)(1u << b);
        }
        status |= (unsigned int)((unsigned int)(k->state & 7u) << (2u + 3u * b));
        if (in->chip_ok[b]) {
            status |= (unsigned int)(0x0100u << b);
        }
        if (k->state == HCWB_ST_READY) {
            status |= (unsigned int)(0x0400u << b);
        }
        if (k->pa_ms != 0u) {
            status |= (unsigned int)(0x1000u << b);
        }
        if (k->cal_st == HCWB_CAL_OK) {
            status |= (unsigned int)(0x4000u << b);
        }
    }
    return status;
}

/* see hcwb.h - the LSU dynamics check */
unsigned char hcwb_dyn_step(hcwb_dyn_t *d, unsigned char valid,
                                     unsigned int ua, unsigned char running,
                                     unsigned int ms)
{
    if (!valid) {
        d->alive = 0u; d->stuck = 0u; d->frozen = 0u; d->on = 0u;
        d->umin = 0xFFFFu; d->umax = 0u;
        return 0u;
    }
    if (!d->on) {
        d->on = 1u;
        d->t0 = ms;
        d->umin = 0xFFFFu; d->umax = 0u;
    }
    if (ua < d->umin) d->umin = ua;
    if (ua > d->umax) d->umax = ua;
    if (el(ms, d->t0) >= HCWB_DYN_WIN_MS) {
        d->span = (d->umax > d->umin) ? (unsigned int)(d->umax - d->umin) : 0u;
        if (d->span >= HCWB_DYN_ALIVE) {
            d->alive = 1u;
        }
        if (running && d->span < HCWB_DYN_FROZEN) {
            if (d->frozen < 255u) d->frozen++;
        } else {
            d->frozen = 0u;
        }
        if (d->frozen >= HCWB_DYN_FROZEN_N) {
            d->stuck = 1u;
        }
        if (d->span >= HCWB_DYN_RECOVER) {
            d->stuck = 0u;
        }
        d->t0 = ms;
        d->umin = 0xFFFFu; d->umax = 0u;
    }
    return d->stuck;
}
