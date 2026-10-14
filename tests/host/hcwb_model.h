/*
 * hcwb_model.h - the CJ120 + LSU 4.2 model behind the wideband host tests
 * (test_hcwb.c, test_hcwb_dual.c): admission, physical register write, readback and ADC
 * publication have independent configurable delays. Cached UA / UR keep
 * their generating mode and acquisition age while a new mode is pending (LA -> pump zero, RA -> the 82.5 ohm reference), a first-order
 * sensor warms with heater power, and an absent heater reads DIAG
 * "open load" while its gate is low. Test-only; static functions.
 */
#ifndef HCWB_MODEL_H
#define HCWB_MODEL_H
#include "hcwb.h"

/* ---- the model -------------------------------------------------------- */
typedef struct {
    unsigned int  ms;
    unsigned char reg1;         /* what the chip holds (read back)          */
    unsigned char chip_ok;
    unsigned char diag;
    unsigned char sensor;       /* 1 = an LSU is plugged in                  */
    unsigned int  temp;         /* sensor temperature, C                     */
    unsigned int  vbatt;        /* 0.1 V                                     */
    unsigned char running, key_on, en;
    unsigned char heat_policy;  /* V100: HCWB_HEAT_* (model computes allow)  */
    int           ip_ua;        /* the exhaust: pump current when pumping    */
    unsigned int  ur_force;     /* 0 = model, else forced raw UR             */
    unsigned char diag_force;   /* 0 = model, else the DIAG the chip reports */
    int           ua_shift;     /* raw offset on UA (a bad pump zero)        */
    unsigned int  amb;          /* what the sensor cools toward, C: 20 still,
                                   ~400 in a running engine's exhaust        */
    unsigned char physical, pending, sample_mode;
    unsigned int write_left, ack_left, sample_left;
    unsigned int write_delay, ack_delay, adc_delay, contention;
    unsigned int ua_cached, ur_cached, seq, sample_ms;
    unsigned char freeze_adc, fail_write;
} model_t;

#define UA0     307u            /* the chip's own pump zero (LA = 1)          */
#define URC     187u            /* UR with RA = 1 (82.5 ohm): the bench value
                                   (V96, both chips 186..188)                 */
#define UR0      58u

/* Ri of an LSU 4.2 vs temperature: rusEFI wideband sampling.cpp lsu42
   table (ESR -> C), inverted and interpolated; below 503 C: 5000 ohm */
static const unsigned int lsu_t[] = { 1199, 961, 857, 806, 775, 750, 730, 715,
    692, 666, 635, 613, 598, 574, 564, 556, 543, 535, 528, 521, 514, 503 };
static const unsigned int lsu_r[] = {   35,  40,  50,  60,  70,  80,  90, 100,
    120, 150, 200, 250, 300, 400, 450, 500, 600, 700, 800, 900, 1000, 1100 };
static unsigned int ri_of(unsigned int t)
{
    unsigned int i;
    if (t >= lsu_t[0]) return lsu_r[0];
    for (i = 1u; i < sizeof lsu_t / sizeof lsu_t[0]; i++) {
        if (t >= lsu_t[i]) {
            return (unsigned int)(lsu_r[i] - (unsigned long)(lsu_r[i] - lsu_r[i - 1u])
                                  * (t - lsu_t[i]) / (lsu_t[i - 1u] - lsu_t[i]));
        }
    }
    return 5000u;
}

static unsigned int ur_of(model_t *m)
{
    unsigned long r;
    if (m->ur_force) return m->ur_force;
    if (m->physical & HCWB_RA) return URC;              /* the reference     */
    if (!m->sensor) return 1000u;                       /* open: saturated   */
    r = (unsigned long)UR0 + (unsigned long)(URC - UR0) * ri_of(m->temp) / 82u;
    return (unsigned int)(r > 1000u ? 1000u : r);
}

static unsigned int ua_of(model_t *m)
{
    long mv;
    /* PA is active low (hcwb.h): PA = 1 holds the pump current off */
    if ((m->physical & HCWB_LA) || (m->physical & HCWB_PA) || !m->sensor)
        return (unsigned int)((int)UA0 + m->ua_shift);
    /* UA = zero + 8 x 61.9 ohm x Ip */
    mv = (long)UA0 * 5000L / 1023L + (long)m->ip_ua * 4952L / 10000L;
    return (unsigned int)(mv * 1023L / 5000L + m->ua_shift);
}

static void inputs(model_t *m, hcwb_in_t *in)
{
    in->ms = m->ms; in->ua = m->ua_cached; in->ur = m->ur_cached;
    in->ua_sample.seq = in->ur_sample.seq = m->seq;
    in->ua_sample.mode = in->ur_sample.mode = m->sample_mode;
    in->ua_sample.valid = in->ur_sample.valid = (unsigned char)(
        ((m->ms - m->sample_ms) & 0xFFFFu) <= 100u);
    in->afterrun = (unsigned char)(m->heat_policy == HCWB_HEAT_RUNNING);
    in->vbatt_dv = m->vbatt; in->en = m->en; in->key_on = m->key_on;
    in->running = m->running; in->chip_ok = m->chip_ok; in->reg1 = m->reg1;
    in->heat_allow = (unsigned char)(m->heat_policy == HCWB_HEAT_IGNITION
                                     ? m->key_on
                                     : (m->heat_policy == HCWB_HEAT_RUNNING
                                        ? (m->key_on && m->running) : 0u));
    in->diag = m->diag; in->hold = 0u; in->hold_mode = 0u;
}

/* after the core: the chip takes the mode it was asked for, the sensor
   follows its heater, DIAG follows the heater stage */
static void follow(const hcwb_t *w, model_t *m)
{
    unsigned int target;
    /* Admission, physical write, readback and ADC completion are distinct.
       Delayed mode exit intentionally leaves calibration ADC data cached. */
    if (m->pending != w->want && !m->write_left && !m->ack_left) {
        m->pending = w->want;
        m->write_left = m->write_delay + m->contention;
    }
    if (m->write_left) {
        m->write_left = m->write_left > 10u ? m->write_left - 10u : 0u;
        if (!m->write_left && !m->fail_write) {
            m->physical = m->pending;
            m->ack_left = m->ack_delay;
            m->sample_left = m->adc_delay;
        }
    } else if (m->ack_left) {
        m->ack_left = m->ack_left > 10u ? m->ack_left - 10u : 0u;
        if (!m->ack_left) m->reg1 = m->physical;
    }
    if (m->sample_left) {
        m->sample_left = m->sample_left > 10u ? m->sample_left - 10u : 0u;
    } else if (!m->freeze_adc) {
        m->ua_cached = ua_of(m); m->ur_cached = ur_of(m);
        m->sample_mode = m->physical; m->sample_ms = m->ms;
        m->seq = (m->seq + 1u) & 0xFFFFu;
    }
    if (m->sensor) {
        m->diag = 0xFFu;                                /* heater present    */
        target = (unsigned int)(m->amb + (unsigned int)w->veff_dv * 7u);
        if (m->temp < target) m->temp += (target - m->temp) / 400u + 1u;
        else if (m->temp > target) m->temp -= (m->temp - target) / 400u + 1u;
    } else {
        /* no heater: the CJ120 sees the drain floating = open load (01)
           whenever the gate is low */
        m->diag = (unsigned char)(w->duty_x10 >= 1000u ? 0xFFu : 0x7Fu);
    }
    if (m->diag_force) m->diag = m->diag_force;
    m->ms = (m->ms + 10u) & 0xFFFFu;
}

/* one 10 ms step: the core, then the chip follows its mode, the sensor its
   heater (first-order, ~4 s time constant, 12 V effective ~ 860 C
   equilibrium above amb) */
static void step(hcwb_t *w, model_t *m)
{
    hcwb_in_t in;
    inputs(m, &in);
    hcwb_step(w, &in);
    follow(w, m);
}

static void run(hcwb_t *w, model_t *m, unsigned int ms)
{
    unsigned int n = ms / 10u;
    while (n--) step(w, m);
}

static void model_init(model_t *m)
{
    unsigned int i;
    unsigned char *p = (unsigned char *)m;
    for (i = 0u; i < sizeof(*m); i++) p[i] = 0u;
    m->ms = 1000u; m->reg1 = HCWB_MODE_COLD; m->chip_ok = 1u; m->diag = 0xFFu;
    m->sensor = 1u; m->temp = 20u; m->vbatt = 140u; m->running = 0u;
    m->key_on = 1u; m->en = 1u; m->ip_ua = 0; m->ur_force = 0u;
    m->diag_force = 0u; m->ua_shift = 0; m->amb = 20u;
    m->heat_policy = HCWB_HEAT_RUNNING;  /* the pre-V100 rule: existing tests
                                            keep their own meaning; the V100
                                            tests choose a policy explicitly */
    m->physical = m->pending = m->sample_mode = HCWB_MODE_COLD;
    m->write_delay = 30u; m->ack_delay = 50u; m->adc_delay = 80u;
    m->ua_cached = UA0; m->ur_cached = 1000u; m->sample_ms = m->ms;
}

#endif /* HCWB_MODEL_H */
