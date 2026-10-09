/*
 * test_hcwb_warmup.c - V100: the heater POLICY, the warm-up LIFETIME and the
 * open-cell / still-cold split (firmware/sensors/hcwb.c), gcc -std=c89.
 * Run by tools/test_hcwb_host.py.
 *
 * THE CAR (2026-10-02/03, V99 on the AWT,
 * CARTEST_ANALYSIS.md B3/B4): lambdaValue was 0.000 in EVERY row of EVERY
 * session and stftBank1 never left 0, yet the sensor is healthy - twice it
 * reached Ri = 81.2 ohm with the heater closing its own loop. The cause was
 * lifetime, not hardware: publishing needs ~40 s of uninterrupted permission
 * (15 s dew + ~21 s ramp + 3 s of Ri inside the ready window) and V96..V99
 * both required the engine to be turning AND reset the machine to WAIT with
 * the heater OFF the instant that fell. The car's runs were 18..42 s with
 * 3..7 s gaps.
 *
 * THE REFERENCE (rusEFI .../wideband_firmware/firmware/
 * heater_control.cpp, HeaterControllerBase::GetNextState): the permission is
 * supply voltage + an explicit HeaterAllow, HeaterAllow::Unknown PERMITS
 * heating, and no engine-turning term exists anywhere in that function.
 *
 * P1 the IGNITION policy warms and PUBLISHES with the engine stopped - the
 *    workflow this project wants, so lambda is ready before the first crank;
 * P2 the DISABLED policy never heats, even with the engine running;
 * P3 a warm restart skips the dew wait on Ri alone (rusEFI's own escape);
 * W1 under the RUNNING policy a stall shorter than the afterrun keeps the
 *    heater and the state, so a restart does not sit out a second dew wait;
 * W2 a stop longer than the afterrun does reset (it is bounded);
 * W3 the afterrun is an AFTERRUN: under RUNNING, nothing heats before the
 *    engine has turned once, so a sensor that has never seen exhaust flow is
 *    never ramped (the water-shock case the dew preheat exists for);
 * W4 key-off still resets everything, afterrun or not;
 * W5 a supply failure resets immediately (rusEFI HEATER_SUPPLY_OFF_VOLTAGE);
 * O1 NO SENSOR (UR saturated through a whole ramp at V_MAX) faults as
 *    HCWB_F_OPEN_CELL, not NO_HEAT and not an endless wait;
 * O2 a sensor that is merely COLD - UR saturated at first, then coming off
 *    the rail exactly as the AWT's did (1010 -> 974 -> ... -> 185) - reaches
 *    READY and never reports OPEN_CELL.
 */
#include <assert.h>
#include <stdio.h>
#include "hcwb.h"
#include "hcwb_model.h"

/* hcwb.c's own el() is static; the tests need the same wrap arithmetic */
static unsigned int el_t(unsigned int now, unsigned int then)
{
    return (unsigned int)(now - then);
}

/* step until lambda is a measurement; -> ms taken, 0 = it never was */
static unsigned int to_valid(hcwb_t *w, model_t *m, unsigned int limit_ms)
{
    unsigned int t0 = m->ms;
    while (el_t(m->ms, t0) < limit_ms) {
        step(w, m);
        if (w->valid) {
            return el_t(m->ms, t0);
        }
    }
    return 0u;
}

int main(void)
{
    hcwb_t w;
    model_t m;
    unsigned int t, duty_in_stall;
    unsigned char st_in_stall;

    /* ---- P1: THE IGNITION POLICY WARMS WITH THE ENGINE STOPPED --------- */
    hcwb_init(&w);
    model_init(&m);
    m.heat_policy = HCWB_HEAT_IGNITION;
    m.running = 0u;                     /* the engine never turns here       */
    t = to_valid(&w, &m, 90000u);
    printf("P1 IGNITION policy, engine stopped: valid after %u ms, state %u, "
           "Ri %u (0.1 ohm), duty %u\n", t, w.state, w.ri_x10, w.duty_x10);
    assert(t != 0u);                    /* it warmed with no engine at all   */
    assert(w.state == HCWB_ST_READY);
    assert(w.valid == 1u);              /* ... and it is PUBLISHED           */
    assert(w.why == HCWB_WHY_VALID);
    assert(w.ri_x10 >= 700u && w.ri_x10 <= 950u);
    m.running = 1u;                     /* starting must not disturb it      */
    run(&w, &m, 1000u);
    assert(w.valid == 1u && w.state == HCWB_ST_READY);
    printf("P1 the engine then starts: still valid, no re-warm\n");

    /* ---- P2: THE DISABLED POLICY NEVER HEATS --------------------------- */
    hcwb_init(&w);
    model_init(&m);
    m.heat_policy = HCWB_HEAT_OFF;
    m.running = 1u;                     /* even with the engine running      */
    m.amb = 400u;
    run(&w, &m, 60000u);
    printf("P2 DISABLED policy, engine running 60 s: state %u, duty %u\n",
           w.state, w.duty_x10);
    assert(w.state == HCWB_ST_WAIT);
    assert(w.duty_x10 == 0u);
    assert(!w.valid);

    /* ---- P3: a WARM restart skips the dew wait on Ri alone -------------
       rusEFI: Preheat exits on `sensorTemp > closedLoopTemp`, and
       HEATER_FAST_HEATING_THRESHOLD_T ramps an already-hot sensor from 9 V.
       The key cycle below is a FULL reset (not the afterrun), so the only
       way back quickly is that Ri says the sensor is still hot. */
    hcwb_init(&w);
    model_init(&m);
    m.heat_policy = HCWB_HEAT_IGNITION;
    m.amb = 400u;
    t = to_valid(&w, &m, 90000u);
    assert(t != 0u);
    m.key_on = 0u;                      /* full reset, sensor left HOT       */
    run(&w, &m, 200u);
    assert(w.state == HCWB_ST_OFF);
    m.key_on = 1u;
    t = to_valid(&w, &m, 20000u);
    printf("P3 key cycle with a hot sensor: valid again in %u ms "
           "(the dew wait alone is 15000 ms)\n", t);
    assert(t != 0u);
    assert(t < 15000u);                 /* it did NOT sit out the dew wait   */

    /* ---- W1: under RUNNING, a short stall keeps the warm-up ------------ */
    hcwb_init(&w);
    model_init(&m);
    m.heat_policy = HCWB_HEAT_RUNNING;
    m.running = 1u;
    m.amb = 400u;                       /* a running engine's exhaust        */
    t = to_valid(&w, &m, 90000u);
    assert(t != 0u);
    printf("W1 RUNNING policy, first warm-up: %u ms, Ri %u, state %u\n",
           t, w.ri_x10, w.state);
    assert(w.state == HCWB_ST_READY);
    assert(w.ri_x10 >= 700u && w.ri_x10 <= 950u);
    m.running = 0u;                     /* the car's sequence: 6 s stall     */
    run(&w, &m, 6000u);
    st_in_stall = w.state;
    duty_in_stall = w.duty_x10;
    printf("W1 during a 6 s stall: state %u, heater duty %u (0.1 %%)\n",
           st_in_stall, duty_in_stall);
    assert(st_in_stall != HCWB_ST_WAIT);   /* NOT thrown back to the start   */
    assert(duty_in_stall > 0u);            /* the heater KEEPS RUNNING       */
    m.running = 1u;
    t = to_valid(&w, &m, 8000u);
    printf("W1 after the stall, valid again in %u ms (no second dew wait)\n",
           t);
    assert(t != 0u);
    assert(t < 5000u);

    /* ---- W2: a stop longer than the afterrun DOES reset ---------------- */
    m.running = 0u;
    run(&w, &m, 31000u);
    printf("W2 after a 31 s stop: state %u, duty %u\n", w.state, w.duty_x10);
    assert(w.state == HCWB_ST_WAIT);
    assert(w.duty_x10 == 0u);
    assert(!w.valid);

    /* ---- W3: under RUNNING, nothing heats before the first run ---------- */
    hcwb_init(&w);
    model_init(&m);
    m.heat_policy = HCWB_HEAT_RUNNING;
    m.running = 0u;                     /* key on, engine never turned       */
    run(&w, &m, 40000u);
    printf("W3 RUNNING policy, key on 40 s, engine never ran: state %u, "
           "duty %u, sensor %u C\n", w.state, w.duty_x10, m.temp);
    assert(w.state == HCWB_ST_WAIT);    /* never left WAIT                   */
    assert(w.duty_x10 == 0u);           /* never ramped a dry-exhaust sensor */
    assert(m.temp < 100u);

    /* ---- W4: key-off resets even inside the afterrun -------------------- */
    hcwb_init(&w);
    model_init(&m);
    m.heat_policy = HCWB_HEAT_RUNNING;
    m.running = 1u;
    m.amb = 400u;
    t = to_valid(&w, &m, 90000u);
    assert(t != 0u);
    m.running = 0u;
    run(&w, &m, 2000u);
    assert(w.state != HCWB_ST_WAIT);    /* still inside the afterrun         */
    m.key_on = 0u;
    run(&w, &m, 100u);
    printf("W4 key off inside the afterrun: state %u, duty %u\n",
           w.state, w.duty_x10);
    assert(w.state == HCWB_ST_OFF);
    assert(w.duty_x10 == 0u);

    /* ---- W5: a supply failure resets immediately ------------------------ */
    hcwb_init(&w);
    model_init(&m);
    m.heat_policy = HCWB_HEAT_IGNITION;
    m.running = 1u;
    m.amb = 400u;
    t = to_valid(&w, &m, 90000u);
    assert(t != 0u);
    m.vbatt = 80u;                      /* below VB_OFF_DV (8.5 V)           */
    run(&w, &m, 200u);
    printf("W5 supply 8.0 V: state %u, duty %u\n", w.state, w.duty_x10);
    assert(w.state == HCWB_ST_WAIT);
    assert(w.duty_x10 == 0u);

    /* ---- O1: no sensor -> OPEN_CELL, not NO_HEAT ------------------------ */
    hcwb_init(&w);
    model_init(&m);
    m.heat_policy = HCWB_HEAT_IGNITION;
    m.sensor = 0u;                      /* nothing plugged in: UR saturated  */
    m.diag_force = 0xFFu;               /* ... with the DIAG kept clean, so
                                           ONLY the UR evidence can decide   */
    run(&w, &m, 90000u);
    printf("O1 no sensor, clean DIAG: state %u, fault %u\n", w.state, w.fcode);
    assert(w.state == HCWB_ST_FAULT);
    assert(w.fcode == HCWB_F_OPEN_CELL);
    assert(!w.valid);

    /* ---- O2: merely COLD is not OPEN_CELL ------------------------------- */
    hcwb_init(&w);
    model_init(&m);
    m.heat_policy = HCWB_HEAT_IGNITION;
    m.sensor = 1u;
    m.temp = 20u;                       /* stone cold: UR starts saturated,
                                           exactly as the car's did          */
    m.amb = 400u;
    t = to_valid(&w, &m, 90000u);
    printf("O2 cold sensor: valid after %u ms, fault %u, Ri %u\n",
           t, w.fcode, w.ri_x10);
    assert(t != 0u);
    assert(w.fcode != HCWB_F_OPEN_CELL);
    assert(w.fcode == HCWB_F_NONE);
    assert(w.state == HCWB_ST_READY);

    printf("PASS: hcwb heater policy + warm-up lifetime + open-cell split\n");
    return 0;
}
