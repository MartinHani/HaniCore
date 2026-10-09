/* Real target-width clocks and asynchronous acquisition regressions. */
#include <assert.h>
#include <stdio.h>
#include "hcwb_model.h"

static void denied_wraps(unsigned char policy, unsigned char running)
{
    hcwb_t w;
    model_t m;
    unsigned long elapsed;
    hcwb_init(&w); model_init(&m);
    m.heat_policy = policy; m.running = running;
    for (elapsed = 0ul; elapsed < 210000ul; elapsed += 10ul) {
        step(&w, &m);
        assert(w.duty_x10 == 0u && !w.valid);
        assert(w.permission == 0u);
    }
}

static void afterrun_wraps(void)
{
    hcwb_t w;
    model_t m;
    unsigned long elapsed;
    unsigned int cycle;
    hcwb_init(&w); model_init(&m); m.running = 1u;
    run(&w, &m, 30000u);
    assert(w.valid);
    for (cycle = 0u; cycle < 3u; cycle++) {
        m.running = 0u;
        run(&w, &m, 1000u);
        assert(w.duty_x10 && w.permission == 2u);
        for (elapsed = 1000ul; elapsed < 210000ul; elapsed += 10ul) {
            step(&w, &m);
            if (elapsed >= 30000ul) {
                assert(!w.duty_x10 && !w.valid && !w.permission);
            }
        }
        m.running = 1u;
        run(&w, &m, 30000u);
        assert(w.valid);
    }
    m.running = 0u; run(&w, &m, 1000u);
    m.heat_policy = HCWB_HEAT_OFF; step(&w, &m);
    assert(!w.duty_x10 && !w.permission);
    m.key_on = 0u; step(&w, &m);
    assert(w.state == HCWB_ST_OFF && !w.duty_x10);
}

static void calibration_exit(void)
{
    hcwb_t w;
    model_t m;
    unsigned int n;
    unsigned char left = 0u, saw_stale = 0u;
    hcwb_init(&w); model_init(&m);
    m.heat_policy = HCWB_HEAT_IGNITION;
    m.write_delay = 200u; m.ack_delay = 200u; m.adc_delay = 700u;
    m.contention = 100u;
    for (n = 0u; n < 1200u; n++) {
        step(&w, &m);
        if (w.cal_st == HCWB_CAL_OK) left = 1u;
        if (left && m.sample_mode == HCWB_MODE_CAL) {
            saw_stale = 1u;
            assert(w.ri_x10 == 0u && !w.duty_x10 && !w.valid);
        }
        assert(w.state != HCWB_ST_CLOSED && w.state != HCWB_ST_READY);
        assert(!w.fcode);
    }
    assert(left && saw_stale && w.state == HCWB_ST_PREHEAT);
    puts("L1: delayed admission/write/readback/first ADC sample: no false hot restart");
}

static void provenance(void)
{
    hcwb_t w;
    model_t m;
    hcwb_in_t in;
    unsigned int n;
    hcwb_init(&w); model_init(&m);
    m.heat_policy = HCWB_HEAT_IGNITION;
    run(&w, &m, 30000u); assert(w.valid);
    inputs(&m, &in);
    in.ua_sample.mode = HCWB_MODE_CAL;
    hcwb_step(&w, &in);
    assert(!w.valid && !w.lambda);
    in.ua_sample.mode = HCWB_MODE_PUMP;
    in.ur_sample.valid = 0u;
    hcwb_step(&w, &in);
    assert(!w.valid && !w.duty_x10 && !w.ri_x10);
    hcwb_init(&w); model_init(&m);
    m.heat_policy = HCWB_HEAT_IGNITION;
    run(&w, &m, 1500u);
    m.freeze_adc = 1u;
    for (n = 0u; n < 200u; n++) step(&w, &m);
    assert(w.fcode == HCWB_F_NO_RI && !w.duty_x10);
    puts("L1/N3: wrong-mode UA and stale UR withheld independently");
}

static void steady_activity(void)
{
    hcwb_t w;
    hcwb_dyn_t dyn;
    model_t m;
    unsigned long t;
    unsigned int rich, lean;
    hcwb_init(&w); model_init(&m);
    m.heat_policy = HCWB_HEAT_IGNITION; m.running = 1u;
    run(&w, &m, 30000u); assert(w.valid);
    (void)hcwb_dyn_step(&dyn, 0u, 0u, 0u, m.ms);
    for (t = 0ul; t < 90000ul; t += 10ul) {
        step(&w, &m);
        (void)hcwb_dyn_step(&dyn, w.valid, m.ua_cached, 1u, m.ms);
        assert(w.valid && w.lambda);
    }
    assert(dyn.stuck && !dyn.alive);
    m.ip_ua = -600; run(&w, &m, 1000u); rich = w.lambda;
    m.ip_ua = 600; run(&w, &m, 1000u); lean = w.lambda;
    assert(rich < 1000u && lean > 1000u && w.valid);
    /* A demanded response is not evidence that one happened. Constant fresh
     * input and electrical variation are advisory, never health credentials. */
    m.ip_ua = 0;
    run(&w, &m, 1000u);
    for (t = 0ul; t < 10000ul; t += 10ul) {
        step(&w, &m); /* hypothetical rich/lean demand, unchanged sensor */
        (void)hcwb_dyn_step(&dyn, w.valid, m.ua_cached, 1u, m.ms);
        assert(w.valid);
    }
    assert(dyn.stuck);
    for (t = 0ul; t < 2000ul; t += 10ul) {
        m.ip_ua = (t & 20ul) ? 40 : -40; /* noisy frozen physical mixture */
        step(&w, &m);
        (void)hcwb_dyn_step(&dyn, w.valid, m.ua_cached, 1u, m.ms);
        assert(w.valid);
    }
    m.freeze_adc = 1u; run(&w, &m, 200u);
    assert(!w.valid);
    (void)hcwb_dyn_step(&dyn, w.valid, m.ua_cached, 1u, m.ms);
    assert(!dyn.alive && !dyn.stuck && !dyn.on);
    m.key_on = 0u; step(&w, &m);
    assert(!w.valid && !w.duty_x10);
    m.key_on = 1u; m.freeze_adc = 0u; run(&w, &m, 30000u);
    assert(w.valid);
    puts("N6: steady, rich/lean, frozen/noisy response advisory, invalid acquisition and key cycle");
}

static void supply_revokes_tail(void)
{
    hcwb_t w; model_t m; unsigned long t;
    hcwb_init(&w); model_init(&m); m.running=1u;
    run(&w,&m,30000u); assert(w.valid && w.permission==1u);
    m.vbatt=0u; run(&w,&m,50u);
    assert(!w.duty_x10 && !w.permission && !w.tail_ms);
    m.running=0u; m.vbatt=120u;
    for(t=0ul;t<210000ul;t+=10ul) {
        step(&w,&m);
        assert(!w.duty_x10 && !w.permission && !w.tail_ms);
    }
    m.running=1u; run(&w,&m,30000u); assert(w.valid);
    puts("N1/N3: invalid supply revokes a running grant; recovery cannot create an afterrun tail");
}

int main(void)
{
    denied_wraps(HCWB_HEAT_OFF, 0u);
    denied_wraps(HCWB_HEAT_OFF, 1u);
    denied_wraps(HCWB_HEAT_RUNNING, 0u);
    afterrun_wraps();
    puts("N1: Disabled, never-run, expired tails, repeated starts/stops: >210 s each");
    calibration_exit();
    provenance();
    supply_revokes_tail();
    steady_activity();
    puts("PASS: target-width wideband lifecycle regressions");
    return 0;
}
