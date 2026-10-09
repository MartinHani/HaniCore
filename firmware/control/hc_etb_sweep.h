/* Cold, bounded characterization math. No controller or calibration writes.
 * Units: position/duty 0.1%, time ms. Full-resolution segment analysis lives
 * in the log analyzer; this compact accumulator is the live ECU summary. */
#ifndef HC_ETB_SWEEP_H
#define HC_ETB_SWEEP_H
#ifndef HC_SWEEP_PTR
#define HC_SWEEP_PTR
#endif
#define SWEEP_RAMP_START 16u
#define SWEEP_DITHER_START 22u
#define SWEEP_SLAM_START 37u
#define SWEEP_COUNT 59u
#define SWEEP_AUTHORITY 1u
#define SWEEP_BIAS 2u
#define SWEEP_P 4u
#define SWEEP_I 8u
#define SWEEP_D 16u
#define SWEEP_MECHANICAL 32u
#define SWEEP_TPS 64u
#define SWEEP_RATE 128u
#define SWEEP_INCONCLUSIVE 256u
static const unsigned char sweep_positions[SWEEP_COUNT] = {
    2,5,10,20,40,60,80,90,80,60,40,20,10,5,2,5,
    70,10,70,10,70,10,
    20,21,19,21,20,40,41,39,41,40,60,61,59,61,60,
    /* DRIVER DEMAND, as 0.1 % APP through the production chain: slams
       0->100->0 x3, 0->50->100->50->0, APP ramps 2 s / 0.5 s / 0.15 s each
       way, then 30<->70 reversals. */
    0,100,0,100,0,100,0, 50,100,50,0, 100,0,100,0,100,0, 30,70,30,70,0
};
static const unsigned int slam_ms[SWEEP_COUNT-SWEEP_SLAM_START] = {
    800,800,800,800,800,800,800, 600,600,600,800,
    2500,2500,1000,1000,650,650, 300,300,300,300,800 };
static const unsigned int slam_ramp[SWEEP_COUNT-SWEEP_SLAM_START] = {
    0,0,0,0,0,0,0, 0,0,0,0, 2000,2000,500,500,150,150, 0,0,0,0,0 };
typedef struct {
    unsigned long squares;
    unsigned int samples, saturated, peak, maxerr, sat_run, sat_long;
    unsigned int settle, over, steady, flags;
    unsigned int vbmin, vbmax, pairmax, bias_n, tail_n;
    long tail_error, tail_i;
    unsigned int prev, origin, step_start, quiet_start, rise_start, rise;
    unsigned char segment, quiet, rose, inhibit;
} hc_sweep_t;
static unsigned int sweep_abs(int x) { return (unsigned int)(x < 0 ? -x : x); }
/* Ramps (bounded or APP) carry no settle/overshoot/steady verdict. */
static unsigned char sweep_is_ramp(unsigned char s)
{
    if (s >= SWEEP_SLAM_START) return (unsigned char)(slam_ramp[s-SWEEP_SLAM_START] != 0u);
    return (unsigned char)(s >= SWEEP_RAMP_START && s < SWEEP_DITHER_START);
}
/* The APP demand (0.1 %) of a driver segment at `elapsed`. */
static unsigned int sweep_app(unsigned char s, unsigned int elapsed)
{
    unsigned int dest = (unsigned int)sweep_positions[s] * 10u;
    unsigned int from = (unsigned int)sweep_positions[s-1u] * 10u;
    unsigned int r = slam_ramp[s-SWEEP_SLAM_START], delta, move;
    if (!r || elapsed >= r) return dest;
    delta = dest > from ? dest - from : from - dest;
    move = (unsigned int)((unsigned long)delta * elapsed / r);
    return dest > from ? from + move : from - move;
}
static unsigned int sweep_duration(unsigned char s)
{
    if (s >= SWEEP_SLAM_START) return slam_ms[s-SWEEP_SLAM_START];
    if (s >= SWEEP_RAMP_START && s < SWEEP_DITHER_START)
        return s < SWEEP_RAMP_START+2u ? 2000u : s < SWEEP_RAMP_START+4u ? 1000u : 500u;
    return s < SWEEP_RAMP_START ? 2000u : 450u;
}
static unsigned int sweep_target(unsigned char s, unsigned int elapsed,
                                 unsigned int origin)
{
    unsigned int dest = (unsigned int)sweep_positions[s] * 10u;
    unsigned int duration = sweep_duration(s);
    unsigned int delta, move;
    if (s < SWEEP_RAMP_START || s >= SWEEP_DITHER_START || elapsed >= duration) return dest;
    delta = dest > origin ? dest - origin : origin - dest;
    move = (unsigned int)((unsigned long)delta * elapsed / duration);
    return dest > origin ? origin + move : origin - move;
}
static void sweep_begin(hc_sweep_t HC_SWEEP_PTR *s, unsigned int now)
{
    unsigned int j;
    unsigned char HC_SWEEP_PTR *p = (unsigned char HC_SWEEP_PTR *)s;
    for (j = 0u; j < sizeof(hc_sweep_t); j++) p[j] = 0u;
    s->vbmin = 65535u; s->origin = 100u; s->step_start = now;
    s->inhibit = 1u;
}
/* Force native 32:16 DIVLU; a far module cannot call SMALL runtime helpers. */
static unsigned int sweep_mean_abs(long sum, unsigned int n)
{
    unsigned long mag = (unsigned long)(sum < 0L ? -sum : sum);
    return n ? (unsigned int)(mag / n) : 0u;
}
static void sweep_segment_end(hc_sweep_t HC_SWEEP_PTR *s, unsigned int duration)
{
    unsigned int error;
    if (sweep_is_ramp(s->segment)) return;
    if (!s->quiet && duration > s->settle) s->settle = duration;
    if (s->tail_n) {
        error = sweep_mean_abs(s->tail_error, s->tail_n);
        if (error > s->steady) s->steady = error;
        /* Sustained correction at a hold is bias evidence, not an I verdict. */
        if (sweep_mean_abs(s->tail_i, s->tail_n) > 80u && error < 20u)
            s->bias_n++;
    }
}
static void sweep_measure(hc_sweep_t HC_SWEEP_PTR *s, unsigned int elapsed,
    unsigned int target, unsigned int actual, unsigned int duty,
    unsigned int limit, int command, int integral, unsigned int vbat, unsigned int pair)
{
    unsigned int e = sweep_abs((int)target - (int)actual), q;
    int beyond;
    s->samples++;
    s->squares += ((unsigned long)e * e) >> 4;
    if (e > s->maxerr) s->maxerr = e;
    if (duty > s->peak) s->peak = duty;
    if (limit && (duty >= limit || sweep_abs(command) >= limit)) {
        s->saturated++; s->sat_run += 5u;
        if (s->sat_run > s->sat_long) s->sat_long = s->sat_run;
    } else s->sat_run = 0u;
    if (vbat < s->vbmin) s->vbmin = vbat;
    if (vbat > s->vbmax) s->vbmax = vbat;
    if (pair > s->pairmax) s->pairmax = pair;
    if (!sweep_is_ramp(s->segment)) {
        beyond = target >= s->origin ? (int)actual - (int)target
                                     : (int)target - (int)actual;
        if (beyond > 0 && (unsigned int)beyond > s->over) s->over = beyond;
        /* Last entry into a sustained +/-2% band, with 100 ms dwell. */
        if (e > 20u) { s->quiet = 0u; s->quiet_start = elapsed; }
        else if (!s->quiet && elapsed - s->quiet_start >= 100u) {
            s->quiet = 1u;
            if (s->quiet_start > s->settle) s->settle = s->quiet_start;
        }
        q = sweep_abs((int)target - (int)s->origin);
        if (q >= 50u) {
            unsigned int travelled = sweep_abs((int)actual - (int)s->origin);
            if (!s->rose && travelled >= q / 10u) {
                s->rise_start = elapsed; s->rose = 1u;
            }
            if (s->rose == 1u && travelled >= q * 9u / 10u) {
                s->rise = elapsed - s->rise_start; s->rose = 2u;
            }
        }
        if (elapsed + 100u >= sweep_duration(s->segment)) {
            s->tail_n++; s->tail_error += (int)target - (int)actual;
            s->tail_i += integral;
        }
    }
    s->prev = actual;
}
static unsigned int sweep_rms(hc_sweep_t HC_SWEEP_PTR *s)
{
    unsigned long value;
    unsigned int lo = 0u, hi = 1000u, mid;
    if (!s->samples) return 0u;
    value = (unsigned long)(unsigned int)(s->squares / s->samples) << 4;
    while (lo < hi) {
        mid = (lo + hi + 1u) / 2u;
        if ((unsigned long)mid * mid <= value) lo = mid;
        else hi = mid - 1u;
    }
    return lo;
}
static void sweep_classify(hc_sweep_t HC_SWEEP_PTR *s)
{
    unsigned int saturation = s->samples ?
        (unsigned int)((unsigned long)s->saturated * 1000u / s->samples) : 0u;
    s->flags = 0u;
    if (saturation > 50u && s->sat_long >= 200u
        && (s->steady > 20u || s->settle >= 500u)) s->flags |= SWEEP_AUTHORITY;
    if (s->bias_n >= 3u) s->flags |= SWEEP_BIAS;
    /* Avoid diagnosing P while bias or authority can explain the response. */
    if (!s->flags && s->settle >= 500u && s->over < 30u && s->steady < 20u)
        s->flags |= SWEEP_P;
    if (s->over > 50u || s->steady > 20u || !s->samples)
        s->flags |= SWEEP_INCONCLUSIVE;
}
#endif
