/*
 * test_hcwb.c - host test for the wideband core (hcwb.c), gcc -std=c89.
 * Run by tools/test_hcwb_host.py.
 *
 * A small CHIP + SENSOR model drives real inputs: the chip reads back the
 * mode it was asked for one step later (like the 25 ms SPI slot), UA / UR
 * follow the mode (LA -> pump zero, RA -> the 82.5 ohm reference), and a
 * first-order sensor warms with heater power. The assertions are about the
 * outputs only (state, fault, mode, duty, lambda), never about the core's
 * internal arithmetic.
 */
#include <assert.h>
#include <stdio.h>
#include "hcwb.h"

#include "hcwb_model.h"

/* ---- the tests -------------------------------------------------------- */
static void test_calibration(void)
{
    hcwb_t w; model_t m;
    hcwb_init(&w); model_init(&m);
    step(&w, &m);
    assert(w.want == HCWB_MODE_CAL);                    /* asked first thing */
    run(&w, &m, 1000u);
    assert(w.cal_st == HCWB_CAL_OK && w.ua0 == UA0 && w.urc == URC);
    assert(w.want == HCWB_MODE_COLD && w.duty_x10 == 0u);
    assert(w.state == HCWB_ST_WAIT);                    /* engine not running */
    printf("  calibration: RA+LA mode, UA0 %u URcal %u, back to cold: OK\n",
           w.ua0, w.urc);
}

static void test_no_sensor(void)
{
    hcwb_t w; model_t m; unsigned int i, maxduty = 0u;
    hcwb_init(&w); model_init(&m); m.sensor = 0u; m.diag = 0x7Fu;
    for (i = 0u; i < 3000u; i++) {                      /* 30 s, running */
        if (i == 200u) m.running = 1u;
        step(&w, &m);
        if (w.duty_x10 > maxduty) maxduty = w.duty_x10;
    }
    assert(w.state == HCWB_ST_FAULT && w.fcode == HCWB_F_HEATER_OPEN);
    assert(maxduty == 0u && w.lambda == 0u && w.valid == 0u);
    printf("  no sensor: fault 2 (heater open), heater never driven: OK\n");
}

static void test_wait_not_running(void)
{
    hcwb_t w; model_t m;
    hcwb_init(&w); model_init(&m);
    run(&w, &m, 20000u);
    assert(w.state == HCWB_ST_WAIT && w.duty_x10 == 0u && w.lambda == 0u);
    printf("  key on, engine stopped: WAIT, heater off for 20 s: OK\n");
}

static void test_warmup_to_ready(void)
{
    hcwb_t w; model_t m; unsigned int t_ready = 0u, i, pre_max = 0u;
    unsigned char saw_pre = 0u, saw_ramp = 0u, saw_closed = 0u;
    hcwb_init(&w); model_init(&m);
    run(&w, &m, 1000u);
    m.running = 1u;
    m.ip_ua = 0;
    for (i = 0u; i < 12000u && w.state != HCWB_ST_READY; i++) {
        step(&w, &m);
        if (w.state == HCWB_ST_PREHEAT) {
            saw_pre = 1u;
            if (w.veff_dv > pre_max) pre_max = w.veff_dv;
            assert(w.want == HCWB_MODE_COLD);           /* no pump while cold */
        }
        if (w.state == HCWB_ST_RAMP) { saw_ramp = 1u; assert(w.veff_dv <= 120u); }
        if (w.state == HCWB_ST_CLOSED) saw_closed = 1u;
        assert(w.valid == 0u || w.state == HCWB_ST_READY);
    }
    t_ready = i * 10u;
    assert(saw_pre && saw_ramp && saw_closed && pre_max == 20u);
    assert(w.state == HCWB_ST_READY && w.want == HCWB_MODE_PUMP);
    run(&w, &m, 1500u);
    assert(w.valid == 1u && w.lambda >= 1000u && w.lambda <= 1020u);
    printf("  warm-up: PREHEAT 2.0 V -> RAMP -> CLOSED -> READY in %u ms, "
           "lambda %u at Ip 0: OK\n", t_ready, w.lambda);
    /* lambda follows the pump current */
    m.ip_ua = -1000; run(&w, &m, 200u);
    assert(w.valid && w.lambda >= 780u && w.lambda <= 830u);
    m.ip_ua = 800; run(&w, &m, 200u);
    assert(w.valid && w.lambda >= 1350u);
    printf("  lambda follows Ip: -1.0 mA -> %u: OK\n", hcwb_lambda_ip(-1000));
    /* V100: THE ENGINE STOPS and NOTHING IS DISCARDED. The state and the
       heater are kept for HEAT_AFTERRUN_MS and the reading stays a
       measurement: rusEFI's wideband path never asks whether the engine
       runs, and whether a reading may steer FUELLING is the closed loop's
       question, not the sensor's. Until V99 this test asserted WAIT +
       duty 0 here - i.e. it asserted the defect that kept lambda at 0.000
       for the whole AWT session.
       The bounded afterrun, the policies and the warm restart are proven in
       test_hcwb_warmup.c (W2, W3, P1..P3). */
    m.running = 0u; run(&w, &m, 100u);
    assert(w.state != HCWB_ST_WAIT && w.duty_x10 > 0u);
    assert(w.valid == 1u && w.why == HCWB_WHY_VALID);
    /* restart: straight back to a measurement, no second preheat */
    m.running = 1u; run(&w, &m, 200u);
    assert(w.state == HCWB_ST_CLOSED || w.state == HCWB_ST_READY);
    printf("  engine stop -> heater KEPT, still a measurement; restart "
           "skips preheat: OK\n");
}

static void test_supply(void)
{
    hcwb_t w; model_t m;
    hcwb_init(&w); model_init(&m); m.vbatt = 90u;       /* 9.0 V from key-on */
    run(&w, &m, 1000u);
    m.running = 1u;
    run(&w, &m, 3000u);
    assert(w.state == HCWB_ST_WAIT && w.duty_x10 == 0u);
    m.vbatt = 96u; run(&w, &m, 700u);
    assert(w.state == HCWB_ST_PREHEAT);
    m.vbatt = 80u; run(&w, &m, 50u);
    assert(w.state == HCWB_ST_WAIT && w.duty_x10 == 0u);
    m.vbatt = 240u; run(&w, &m, 1000u);
    assert(w.duty_x10 == 0u);
    printf("  supply: < 9.5 V waits, < 8.5 V stops, >= 23 V stops: OK\n");
}

static void test_no_heat(void)
{
    hcwb_t w; model_t m;
    /* V100: THIS SPLIT IS THE POINT. A full ramp that ends with the sensor
       still cold has two causes and V99 reported one code for both:
         UR stayed SATURATED      -> nothing is connected  (OPEN_CELL)
         UR came off the rail but
         Ri never reached closed  -> it cannot get hot     (NO_HEAT)
       On the car UR was railed at 1008..1013 for the whole preheat and ramp
       of every session, so "cold" and "no sensor" were indistinguishable -
       hcwb_ri_x10()'s own comment says a cold LSU saturates UR. */
    hcwb_init(&w); model_init(&m); run(&w, &m, 1000u);
    m.running = 1u;
    m.ur_force = 1000u;                       /* railed: nothing connected   */
    run(&w, &m, 15000u + 61000u);
    assert(w.state == HCWB_ST_FAULT && w.fcode == HCWB_F_OPEN_CELL);
    assert(w.duty_x10 == 0u);
    printf("  UR railed through the ramp: fault 13 OPEN_CELL: OK\n");

    /* ~503 ohm: off the rail, so a cell IS connected, but far above the
       120 ohm closed threshold - a heater that cannot get there. */
    hcwb_init(&w); model_init(&m); run(&w, &m, 1000u);
    m.running = 1u;
    m.ur_force = 845u;
    run(&w, &m, 15000u + 61000u);
    assert(w.state == HCWB_ST_FAULT && w.fcode == HCWB_F_NO_HEAT);
    assert(w.duty_x10 == 0u);
    printf("  cell answers but never heats: fault 9 NO_HEAT: OK\n");
}

static void test_overheat(void)
{
    hcwb_t w; model_t m;
    hcwb_init(&w); model_init(&m); run(&w, &m, 1000u);
    m.running = 1u;
    while (w.state != HCWB_ST_READY) step(&w, &m);
    m.ur_force = (unsigned int)(UR0 + (URC - UR0) * 50u / 82u);  /* 50 ohm */
    run(&w, &m, 700u);
    assert(w.state == HCWB_ST_FAULT && w.fcode == HCWB_F_OVERHEAT
           && w.duty_x10 == 0u && w.want == HCWB_MODE_COLD);
    /* latched until the key is off, then clean */
    m.running = 0u; run(&w, &m, 100u);
    assert(w.state == HCWB_ST_FAULT);
    m.key_on = 0u; run(&w, &m, 20u);
    assert(w.state == HCWB_ST_OFF && w.fcode == 0u);
    printf("  overheat (Ri 50 ohm): fault 10 in < 0.7 s, latched to key-off: OK\n");
}

static void test_heater_short(void)
{
    hcwb_t w; model_t m;
    hcwb_init(&w); model_init(&m); run(&w, &m, 1000u);
    m.running = 1u; run(&w, &m, 2000u);
    m.diag_force = 0xBFu;                               /* heater 10: UB     */
    step(&w, &m);
    assert(w.state != HCWB_ST_FAULT);                   /* one read: no latch */
    run(&w, &m, 600u);
    assert(w.state == HCWB_ST_FAULT && w.fcode == HCWB_F_HEATER_UB);
    assert(w.duty_x10 == 0u);
    printf("  heater short to UB (DIAG 10) for 0.5 s: fault 3, heater off: OK\n");
}

/* The AWT car, 2026-10-10: the starter pulled the supply to 8 V, the CJ120
   lost verification for a moment and read heater "open load" - and that one
   read latched the sensor dead until key-off. A dip must not latch; a real
   open load at a healthy supply must; a trouble-code clear must re-arm. */
static void test_crank_dip(void)
{
    hcwb_t w; model_t m; unsigned int i;
    hcwb_init(&w); model_init(&m); run(&w, &m, 1000u);
    m.running = 1u;
    while (w.state != HCWB_ST_READY) step(&w, &m);
    for (i = 0u; i < 300u; i++) {                       /* 3 s of cranking   */
        m.vbatt = (unsigned int)((i & 8u) ? 98u : 80u);
        m.chip_ok = (unsigned char)(i < 5u || i > 15u);
        m.diag_force = (unsigned char)(i < 150u ? 0x7Fu : 0u);
        step(&w, &m);
        assert(w.state != HCWB_ST_FAULT);
    }
    m.vbatt = 140u; m.diag_force = 0u;
    for (i = 0u; i < 3000u && !w.valid; i++) step(&w, &m);
    assert(w.state == HCWB_ST_READY && w.valid && w.fcode == 0u);
    printf("  3 s starter dip to 8 V with DIAG open + chip lost: no latch, "
           "READY again: OK\n");

    m.diag_force = 0x7Fu;                               /* a real open load  */
    run(&w, &m, 400u);
    assert(w.state != HCWB_ST_FAULT && !w.valid);       /* withheld at once  */
    run(&w, &m, 200u);
    assert(w.state == HCWB_ST_FAULT && w.fcode == HCWB_F_HEATER_OPEN);
    hcwb_clear(&w);                                     /* still open        */
    run(&w, &m, 3000u);
    assert(w.state == HCWB_ST_FAULT && w.fcode == HCWB_F_HEATER_OPEN);
    m.diag_force = 0u;                                  /* repaired          */
    hcwb_clear(&w);
    assert(w.state == HCWB_ST_OFF && w.fcode == 0u);
    for (i = 0u; i < 6000u && !w.valid; i++) step(&w, &m);
    assert(w.state == HCWB_ST_READY && w.valid && w.cal_st == HCWB_CAL_OK);
    printf("  open load at 14 V: fault 2 after 0.5 s; clear re-latches while "
           "open, re-arms once repaired: OK\n");
}

static void test_bad_cal_and_chip(void)
{
    hcwb_t w; model_t m;
    hcwb_init(&w); model_init(&m); m.chip_ok = 0u;
    run(&w, &m, 3500u);
    assert(w.state == HCWB_ST_FAULT && w.fcode == HCWB_F_CHIP);
    hcwb_init(&w); model_init(&m); m.ur_force = 60u;    /* reference = zero  */
    run(&w, &m, 1500u);
    assert(w.state == HCWB_ST_FAULT && w.fcode == HCWB_F_CAL);
    printf("  chip never verified: fault 7; unusable Ri reference: fault 8: OK\n");
}

static void test_lambda_validity(void)
{
    hcwb_t w; model_t m;
    hcwb_init(&w); model_init(&m); run(&w, &m, 1000u);
    m.running = 1u;
    while (w.state != HCWB_ST_READY) step(&w, &m);
    run(&w, &m, 1500u);
    assert(w.valid);
    /* 2026-10-10: one missed exchange is HELD (test_ssc_gap); a chip that
       stays unverified past the hold withdraws lambda */
    m.chip_ok = 0u; run(&w, &m, 700u);
    assert(!w.valid && w.lambda == 0u && w.duty_x10 == 0u);
    m.chip_ok = 1u; run(&w, &m, 100u);
    printf("  lambda withheld once the chip stays unverified past the hold: OK\n");
}

/* One CJ120 exchange the SSC never completed, as the target sees it
   (hcio711.c): ~80 ms chip unverified while the mode is rewritten, read back
   and IDENT checked, then 300 ms of analog settling with no qualified sample.
   The AWT car (2026-10-10) lost 1..5 s of lambda per timeout because this
   reset pa_ms, cut the heater and zeroed readiness. Now: held. */
static void gap_step(hcwb_t *w, model_t *m, unsigned char chip,
                     unsigned char samples)
{
    hcwb_in_t in;
    inputs(m, &in);
    in.chip_ok = chip;
    if (!samples) {
        in.ua_sample.valid = 0u;
        in.ur_sample.valid = 0u;
    }
    hcwb_step(w, &in);
    follow(w, m);
}

static void test_ssc_gap(void)
{
    hcwb_t w; model_t m; unsigned int i, lam, duty, n;
    hcwb_init(&w); model_init(&m); run(&w, &m, 1000u);
    m.running = 1u;
    while (w.state != HCWB_ST_READY) step(&w, &m);
    m.ip_ua = -500; run(&w, &m, 1500u);
    assert(w.valid && w.pa_ms >= 1000u);
    lam = w.lambda; duty = w.duty_x10;
    for (i = 0u; i < 42u; i++) {                        /* 420 ms gap        */
        gap_step(&w, &m, (unsigned char)(i >= 8u), 0u);
        /* HELD, and SAYS so: valid 2 + why HELD - never a fresh reading */
        assert(w.valid == 2u && w.lambda == lam && w.why == HCWB_WHY_HELD);
        assert(w.duty_x10 == duty && w.state == HCWB_ST_READY);
        assert(w.want == HCWB_MODE_PUMP && w.pa_ms >= 1000u);
    }
    step(&w, &m);                                       /* samples are back  */
    assert(w.valid == 1u && w.why == HCWB_WHY_VALID
           && w.state == HCWB_ST_READY);
    printf("  one missed CJ120 exchange (420 ms gap): lambda %u HELD (valid 2, "
           "why HELD), heater kept, READY + pump kept, FRESH on the next "
           "sample: OK\n", lam);

    /* repeated: a timeout every 2 s for 20 s, as on the running car */
    for (n = 0u, i = 0u; i < 2000u; i++) {
        unsigned int k = i % 200u;
        if (k < 42u) gap_step(&w, &m, (unsigned char)(k >= 8u), 0u);
        else step(&w, &m);
        if (!w.valid) n++;
    }
    assert(n == 0u && w.state == HCWB_ST_READY);
    printf("  a timeout every 2 s for 20 s: lambda never withdrawn: OK\n");

    /* ONE out-of-band Ri sample does not demote READY; a lasting one does */
    m.ur_force = (unsigned int)(UR0 + (URC - UR0) * 120u / 82u);
    step(&w, &m); m.ur_force = 0u; step(&w, &m); step(&w, &m);
    assert(w.state == HCWB_ST_READY && w.valid);
    m.ur_force = (unsigned int)(UR0 + (URC - UR0) * 120u / 82u);
    run(&w, &m, 700u);
    assert(w.state == HCWB_ST_CLOSED && !w.valid);
    m.ur_force = 0u;
    printf("  one Ri sample out of band: READY kept; 0.7 s out: CLOSED: OK\n");

    /* a gap longer than the hold is the old path: withdrawn, heater off */
    for (i = 0u; i < 3000u && w.state != HCWB_ST_READY; i++) step(&w, &m);
    run(&w, &m, 1500u);
    assert(w.valid);
    for (i = 0u; i < 80u; i++) gap_step(&w, &m, 1u, 0u);
    assert(!w.valid && w.duty_x10 == 0u);
    printf("  an 800 ms gap: withdrawn after the 0.6 s hold, heater off: OK\n");
}

static void test_hold(void)
{
    hcwb_t w; model_t m; hcwb_in_t in;
    hcwb_init(&w); model_init(&m); run(&w, &m, 1000u);
    inputs(&m, &in); in.hold = 1u; in.hold_mode = 0x98u;
    hcwb_step(&w, &in);
    assert(w.want == 0x98u && w.duty_x10 == 0u && !w.valid);
    printf("  bench mode hold: the requested mode, heater off: OK\n");
}

static void test_ignition_park(void)
{
    /* 2026-10-14: key-on heating with a heater that has no feed until the
       engine runs (VAG: H+ from the fuel-pump relay). UR stays railed for
       the whole dew + ramp with the engine STOPPED: that must PARK (heater
       off, no fault, why = waiting for the engine), not latch 13 -> P0130.
       The engine starting restarts the warm-up, and a railed UR then IS a
       fault, exactly as before. */
    hcwb_t w; model_t m;
    hcwb_init(&w); model_init(&m);
    m.heat_policy = HCWB_HEAT_IGNITION;
    run(&w, &m, 1000u);                       /* the key-on calibration     */
    m.ur_force = 1000u;                       /* railed: no heater power    */
    run(&w, &m, 15000u + 61000u);
    assert(w.state == HCWB_ST_WAIT && w.fcode == HCWB_F_NONE);
    assert(w.duty_x10 == 0u && w.why == HCWB_WHY_ENGINE);
    run(&w, &m, 30000u);                      /* stays parked, key on       */
    assert(w.state == HCWB_ST_WAIT && w.fcode == HCWB_F_NONE);
    printf("  key-on heating, nothing warmed, engine stopped: parked, "
           "no fault: OK\n");
    m.running = 1u;
    run(&w, &m, 200u);
    assert(w.state == HCWB_ST_PREHEAT && w.duty_x10 > 0u);
    run(&w, &m, 15000u + 61000u);
    assert(w.state == HCWB_ST_FAULT && w.fcode == HCWB_F_OPEN_CELL);
    printf("  engine started: warm-up restarts; still railed -> fault 13: "
           "OK\n");

    /* a sensor that warms normally is not affected by the park rule */
    hcwb_init(&w); model_init(&m);
    m.heat_policy = HCWB_HEAT_IGNITION;
    run(&w, &m, 1000u + 15000u + 61000u);
    assert(w.state == HCWB_ST_READY || w.state == HCWB_ST_CLOSED);
    printf("  key-on heating with a fed heater reaches closed loop: OK\n");
}

static void test_start_restarts_paper_warmup(void)
{
    /* 2026-10-15: key-on heating, heater unfed until the engine runs, the
       engine started INSIDE the park time (the usual start). The ramp had
       climbed on paper; at the start the warm-up must go back to the 2 V
       preheat, not hand a cold wet sensor 8..12 V. */
    hcwb_t w; model_t m; unsigned int pre_duty;
    hcwb_init(&w); model_init(&m);
    m.heat_policy = HCWB_HEAT_IGNITION;
    run(&w, &m, 1000u);                       /* the key-on calibration     */
    m.ur_force = 1000u;                       /* railed: no heater power    */
    run(&w, &m, 15000u + 12000u);             /* dew, then ~12 s of ramp    */
    assert(w.state == HCWB_ST_RAMP && w.veff_dv > 100u);
    m.temp = 20u;                             /* nothing was fed: cold      */
    m.running = 1u;                           /* start: the feed arrives    */
    step(&w, &m);
    assert(w.state == HCWB_ST_PREHEAT && w.veff_dv == 20u);
    m.ur_force = 0u;
    pre_duty = w.duty_x10;
    run(&w, &m, 14000u);                      /* the dew time runs again    */
    assert(w.state == HCWB_ST_PREHEAT && w.duty_x10 == pre_duty);
    run(&w, &m, 61000u);
    assert(w.state == HCWB_ST_READY || w.state == HCWB_ST_CLOSED);
    printf("  start during a paper ramp: back to the 2 V preheat, then "
           "closed loop: OK\n");

    /* control: a sensor SEEN heating before the start keeps its warm-up */
    hcwb_init(&w); model_init(&m);
    m.heat_policy = HCWB_HEAT_IGNITION;
    run(&w, &m, 1000u + 15000u);
    while (w.ur_live == 0u && w.state == HCWB_ST_RAMP) {
        step(&w, &m);
    }
    assert(w.ur_live == 1u);
    m.running = 1u;
    step(&w, &m);
    assert(w.state != HCWB_ST_PREHEAT && w.state != HCWB_ST_WAIT
           && w.veff_dv > 20u);
    printf("  start with a fed heater already warming: warm-up kept: OK\n");
}

int main(void)
{
    printf("hcwb host tests\n");
    test_calibration();
    test_no_sensor();
    test_wait_not_running();
    test_warmup_to_ready();
    test_supply();
    test_no_heat();
    test_overheat();
    test_heater_short();
    test_crank_dip();
    test_bad_cal_and_chip();
    test_lambda_validity();
    test_ssc_gap();
    test_hold();
    test_ignition_park();
    test_start_restarts_paper_warmup();
    printf("PASS: all hcwb host tests\n");
    return 0;
}
