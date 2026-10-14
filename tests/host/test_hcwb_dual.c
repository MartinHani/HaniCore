/*
 * test_hcwb_dual.c - BOTH wideband banks through hcwb_pair_step(), the glue
 * the target calls (hcio711.c hc_io_lambda_service). gcc -std=c89.
 * Run by tools/test_hcwb_host.py.
 *
 * Two independent chip + sensor models (hcwb_model.h) share only what one
 * ECU shares: the supply, KL15 and the engine. Every scenario asserts on
 * BOTH banks - the point is that one bank's absence, fault, calibration or
 * heater never reaches the other - and on the published lambdaStatus bits.
 */
#include <assert.h>
#include <stdio.h>
#include "hcwb.h"
#include "hcwb_model.h"

static unsigned int status;

/* one 10 ms step of both banks */
static void pstep(hcwb_t w[2], model_t m[2], unsigned char en_mask)
{
    hcwb_pair_in_t in;
    hcwb_in_t b_in;
    unsigned char b;
    in.ms = m[0].ms;
    in.vbatt_dv = m[0].vbatt;
    in.en_mask = en_mask;
    in.key_on = m[0].key_on;
    in.running = m[0].running;
    /* V100: the heater policy is one ECU-wide verdict (hcwb_in_t.heat_allow).
       These two-bank tests were written against the pre-V100 rule, so the
       model keeps HCWB_HEAT_RUNNING and this reproduces it exactly. */
    in.heat_allow = (unsigned char)(m[0].key_on && m[0].running);
    in.afterrun = 1u;
    in.hold = 0u;
    in.hold_mode = 0u;
    for (b = 0u; b < 2u; b++) {
        inputs(&m[b], &b_in);
        in.ua[b] = b_in.ua;
        in.ur[b] = b_in.ur;
        in.ua_sample[b] = b_in.ua_sample;
        in.ur_sample[b] = b_in.ur_sample;
        in.chip_ok[b] = m[b].chip_ok;
        in.reg1[b] = m[b].reg1;
        in.diag[b] = m[b].diag;
    }
    status = hcwb_pair_step(w, &in);
    follow(&w[0], &m[0]);
    follow(&w[1], &m[1]);
}

static void prun(hcwb_t w[2], model_t m[2], unsigned int ms, unsigned char en)
{
    unsigned int n = ms / 10u;
    while (n--) pstep(w, m, en);
}

/* the shared inputs */
static void set_running(model_t m[2], unsigned char v) { m[0].running = v; m[1].running = v; }
static void set_key(model_t m[2], unsigned char v) { m[0].key_on = v; m[1].key_on = v; }
static void set_vbatt(model_t m[2], unsigned int v) { m[0].vbatt = v; m[1].vbatt = v; }

static void pinit(hcwb_t w[2], model_t m[2])
{
    hcwb_init(&w[0]); hcwb_init(&w[1]);
    model_init(&m[0]); model_init(&m[1]);
    m[0].ip_ua = 250;            /* bank 1 a little lean  */
    m[1].ip_ua = -300;           /* bank 2 a little rich  */
}

static unsigned int st(unsigned char b) { return (status >> (2u + 3u * b)) & 7u; }

/* both banks to READY from a cold start */
static unsigned int to_ready(hcwb_t w[2], model_t m[2], unsigned char want_mask)
{
    unsigned int i;
    prun(w, m, 1000u, 3u);
    set_running(m, 1u);
    for (i = 0u; i < 12000u; i++) {
        pstep(w, m, 3u);
        if (((want_mask & 1u) == 0u || w[0].state == HCWB_ST_READY)
            && ((want_mask & 2u) == 0u || w[1].state == HCWB_ST_READY)) break;
    }
    prun(w, m, 1500u, 3u);          /* settle: pump on >= 1 s, valid */
    return i;
}

static void test_both_absent(void)
{
    hcwb_t w[2]; model_t m[2]; unsigned int i, d0 = 0u, d1 = 0u;
    pinit(w, m);
    m[0].sensor = 0u; m[1].sensor = 0u; m[0].diag = 0x7Fu; m[1].diag = 0x7Fu;
    prun(w, m, 1000u, 3u);
    set_running(m, 1u);
    for (i = 0u; i < 3000u; i++) {
        pstep(w, m, 3u);
        if (w[0].duty_x10 > d0) d0 = w[0].duty_x10;
        if (w[1].duty_x10 > d1) d1 = w[1].duty_x10;
    }
    assert(w[0].fcode == HCWB_F_HEATER_OPEN && w[1].fcode == HCWB_F_HEATER_OPEN);
    assert(d0 == 0u && d1 == 0u && (status & 3u) == 0u);
    assert(st(0) == HCWB_ST_FAULT && st(1) == HCWB_ST_FAULT);
    printf("  both absent: both 'no sensor', neither heater driven: OK\n");
}

static void test_one_absent(unsigned char absent)
{
    hcwb_t w[2]; model_t m[2]; unsigned int dmax = 0u, i;
    unsigned char ok = (unsigned char)(absent ^ 1u);
    pinit(w, m);
    m[absent].sensor = 0u; m[absent].diag = 0x7Fu;
    prun(w, m, 1000u, 3u);
    set_running(m, 1u);
    for (i = 0u; i < 12000u && w[ok].state != HCWB_ST_READY; i++) {
        pstep(w, m, 3u);
        if (w[absent].duty_x10 > dmax) dmax = w[absent].duty_x10;
    }
    prun(w, m, 1500u, 3u);
    assert(w[absent].state == HCWB_ST_FAULT && w[absent].fcode == HCWB_F_HEATER_OPEN);
    assert(dmax == 0u && w[absent].lambda == 0u && w[absent].valid == 0u);
    assert(w[ok].state == HCWB_ST_READY && w[ok].valid == 1u);
    assert(((status >> ok) & 1u) == 1u && ((status >> absent) & 1u) == 0u);
    assert(ok == 0u ? w[0].lambda > 1000u : w[1].lambda < 1000u);
    printf("  bank %u absent: it faults (2) cold, bank %u READY lambda %u: OK\n",
           absent + 1u, ok + 1u, w[ok].lambda);
}

static void test_status_bits(void)
{
    hcwb_t w[2]; model_t m[2];
    pinit(w, m);
    to_ready(w, m, 3u);
    assert(w[0].state == HCWB_ST_READY && w[1].state == HCWB_ST_READY);
    assert(status == (0x0003u | (5u << 2) | (5u << 5) | 0x0300u | 0x0C00u
                      | 0x3000u | 0xC000u));
    assert(w[0].lambda > 1000u && w[1].lambda < 1000u);
    assert(w[0].ip_ua > 150 && w[0].ip_ua < 350);
    assert(w[1].ip_ua < -200 && w[1].ip_ua > -400);
    printf("  both READY: lambdaStatus 0x%04X, lambda %u / %u, Ip %d / %d uA: OK\n",
           status, w[0].lambda, w[1].lambda, w[0].ip_ua, w[1].ip_ua);
}

static void test_one_fails_running(void)
{
    hcwb_t w[2]; model_t m[2]; unsigned int i, d0min = 0xFFFFu;
    pinit(w, m);
    to_ready(w, m, 3u);
    m[1].diag_force = 0x3Fu;                     /* bank 2 heater short to GND */
    for (i = 0u; i < 500u; i++) {
        pstep(w, m, 3u);
        if (w[0].duty_x10 < d0min) d0min = w[0].duty_x10;
        assert(w[0].state == HCWB_ST_READY && w[0].valid == 1u);
    }
    assert(w[1].state == HCWB_ST_FAULT && w[1].fcode == HCWB_F_HEATER_GND);
    assert(w[1].duty_x10 == 0u && w[1].valid == 0u && (status & 3u) == 1u);
    assert(d0min > 0u);
    printf("  bank 2 heater short while running: bank 2 fault 1 + heater off, "
           "bank 1 READY throughout (duty >= %u): OK\n", d0min);
}

static void test_chip_loss(void)
{
    hcwb_t w[2]; model_t m[2]; unsigned int i;
    pinit(w, m);
    to_ready(w, m, 3u);
    m[0].chip_ok = 0u;                           /* bank 1 CJ120 stops answering */
    for (i = 0u; i < 400u; i++) {
        pstep(w, m, 3u);
        /* 2026-10-10: held through a one-exchange gap (< 0.6 s), then
           withheld (hcwb.c GAP_HOLD_MS) */
        if (i >= 60u) assert(w[0].valid == 0u);
        assert(w[1].state == HCWB_ST_READY && w[1].valid == 1u);
    }
    assert(w[0].state == HCWB_ST_FAULT && w[0].fcode == HCWB_F_CHIP);
    assert(((status >> 8) & 3u) == 2u);
    printf("  bank 1 chip lost: lambda withheld after the 0.6 s gap hold, "
           "fault 7 after 3 s, bank 2 untouched: OK\n");
}

static void test_bad_cal_one_bank(void)
{
    hcwb_t w[2]; model_t m[2];
    pinit(w, m);
    m[1].ua_shift = 40;                          /* bank 2 pump zero out of spec */
    to_ready(w, m, 1u);
    assert(w[1].state == HCWB_ST_FAULT && w[1].fcode == HCWB_F_CAL);
    assert(w[0].state == HCWB_ST_READY && w[0].valid == 1u);
    assert(((status >> 14) & 3u) == 1u && w[1].ip_ua == 0);
    printf("  bank 2 calibration out of spec: fault 8, no Ip; bank 1 READY: OK\n");
}

/* a supply dip with the engine running (exhaust ~400 C): both banks drop to
   WAIT with the heaters off and no fault; on the way back the preheat is
   skipped only if the sensor is still >= ~598 C (Ri <= 300 ohm) after the
   0.5 s supply-stability wait - otherwise the full dew wait again */
static unsigned int dip(unsigned int dip_ms, unsigned char *fast)
{
    hcwb_t w[2]; model_t m[2]; unsigned int i;
    pinit(w, m);
    m[0].amb = 400u; m[1].amb = 400u;
    to_ready(w, m, 3u);
    set_vbatt(m, 80u);
    prun(w, m, dip_ms, 3u);
    assert(w[0].state == HCWB_ST_WAIT && w[1].state == HCWB_ST_WAIT);
    assert(w[0].duty_x10 == 0u && w[1].duty_x10 == 0u && (status & 3u) == 0u);
    assert(w[0].fcode == 0u && w[1].fcode == 0u);
    set_vbatt(m, 140u);
    *fast = 2u;
    for (i = 0u; i < 4000u && !(w[0].state == HCWB_ST_READY
                                && w[1].state == HCWB_ST_READY); i++) {
        pstep(w, m, 3u);
        if (w[0].state == HCWB_ST_RAMP && *fast == 2u) {
            *fast = (unsigned char)(w[0].veff_dv >= 90u);
        }
    }
    assert(w[0].state == HCWB_ST_READY && w[1].state == HCWB_ST_READY);
    return i * 10u;
}

static void test_undervoltage(void)
{
    unsigned char fast;
    unsigned int t;
    t = dip(300u, &fast);
    assert(fast != 0u && t < 12000u);
    printf("  0.3 s supply dip, engine running: WAIT + heaters off, no fault; "
           "still >= 598 C -> %s, READY in %u ms: OK\n",
           fast == 1u ? "ramp from 9 V" : "straight to closed loop", t);
    t = dip(3000u, &fast);
    assert(fast == 0u && t > 15000u);
    printf("  3 s outage: cooled below 598 C -> the full 15 s preheat again, "
           "READY in %u ms: OK\n", t);
}

static void test_cold_no_fastpath(void)
{
    hcwb_t w[2]; model_t m[2]; unsigned int i, pre = 0u;
    pinit(w, m);
    prun(w, m, 1000u, 3u);
    assert(w[0].ri_x10 == 0u || w[0].ri_x10 == 60000u || w[0].ri_x10 > 3000u);
    set_running(m, 1u);
    for (i = 0u; i < 1600u; i++) {               /* the first 16 s */
        pstep(w, m, 3u);
        if (w[0].state == HCWB_ST_PREHEAT && w[1].state == HCWB_ST_PREHEAT) pre++;
        assert(w[0].state != HCWB_ST_RAMP || i >= 1490u);
    }
    assert(pre >= 1490u);
    printf("  cold sensors (UR saturated = open / cold): the full 15 s preheat, "
           "no fast path: OK\n");
}

static void test_interrupted_warmup(void)
{
    hcwb_t w[2]; model_t m[2]; unsigned int i;
    pinit(w, m);
    prun(w, m, 1000u, 3u);
    set_running(m, 1u);
    for (i = 0u; i < 3000u && w[0].state != HCWB_ST_RAMP; i++) pstep(w, m, 3u);
    assert(w[0].state == HCWB_ST_RAMP && w[1].state == HCWB_ST_RAMP);
    /* V100: A 3 s STALL NO LONGER THROWS THE RAMP AWAY. Both banks stay in
       their warm-up with the heaters driven for HEAT_AFTERRUN_MS, which is
       what makes a stall-and-restart reach READY at all on this car: the
       AWT's runs were 18..42 s against a ~40 s warm-up, so V99's
       reset-to-WAIT meant lambda never published once
      . Until V99 this test asserted
       WAIT + duty 0 here, i.e. it asserted the defect. The BOUNDED half -
       a stop longer than the afterrun does reset - is test_hcwb_warmup W2. */
    set_running(m, 0u);                          /* the engine stalls */
    prun(w, m, 3000u, 3u);
    assert(w[0].state != HCWB_ST_WAIT && w[1].state != HCWB_ST_WAIT);
    assert(w[0].duty_x10 > 0u && w[1].duty_x10 > 0u);
    set_running(m, 1u);
    for (i = 0u; i < 12000u && !(w[0].state == HCWB_ST_READY
                                 && w[1].state == HCWB_ST_READY); i++) {
        pstep(w, m, 3u);
    }
    assert(w[0].state == HCWB_ST_READY && w[1].state == HCWB_ST_READY);
    assert(w[0].fcode == 0u && w[1].fcode == 0u);
    printf("  stall during the ramp: the ramp and both heaters are KEPT, "
           "restart reaches READY: OK\n");
}

static void test_key_cycle_mid_warmup(void)
{
    hcwb_t w[2]; model_t m[2]; unsigned int i;
    pinit(w, m);
    prun(w, m, 1000u, 3u);
    set_running(m, 1u);
    for (i = 0u; i < 4000u && w[0].state != HCWB_ST_CLOSED; i++) pstep(w, m, 3u);
    set_running(m, 0u);
    set_key(m, 0u);                              /* key off mid warm-up */
    prun(w, m, 500u, 3u);
    assert(w[0].state == HCWB_ST_OFF && w[1].state == HCWB_ST_OFF);
    assert(w[0].duty_x10 == 0u && w[1].duty_x10 == 0u && status == 0x0300u);
    set_key(m, 1u);
    pstep(w, m, 3u);
    assert(w[0].want == HCWB_MODE_CAL && w[1].want == HCWB_MODE_CAL);
    prun(w, m, 1000u, 3u);
    assert(w[0].cal_st == HCWB_CAL_OK && w[1].cal_st == HCWB_CAL_OK);
    set_running(m, 1u);
    for (i = 0u; i < 3000u && !(w[0].state == HCWB_ST_READY
                                && w[1].state == HCWB_ST_READY); i++) {
        pstep(w, m, 3u);
    }
    assert(w[0].state == HCWB_ST_READY && w[1].state == HCWB_ST_READY);
    printf("  key cycle mid warm-up: both OFF (faults and calibration cleared), "
           "recalibrated, warm-up again, READY in %u ms: OK\n", i * 10u);
}

static void test_fault_latch(void)
{
    hcwb_t w[2]; model_t m[2]; unsigned int i;
    pinit(w, m);
    to_ready(w, m, 3u);
    m[1].diag_force = 0xBFu;                     /* heater short to UB */
    prun(w, m, 700u, 3u);                        /* DIAG confirm 0.5 s */
    assert(w[1].fcode == HCWB_F_HEATER_UB);
    m[1].diag_force = 0u;                        /* the short goes away */
    prun(w, m, 5000u, 3u);
    assert(w[1].state == HCWB_ST_FAULT && w[1].fcode == HCWB_F_HEATER_UB);
    assert(w[0].state == HCWB_ST_READY);
    set_running(m, 0u); set_key(m, 0u);
    prun(w, m, 500u, 3u);
    assert(w[1].fcode == 0u);                    /* cleared at key-off only */
    set_key(m, 1u);
    prun(w, m, 1000u, 3u);
    set_running(m, 1u);
    for (i = 0u; i < 3000u && w[1].state != HCWB_ST_READY; i++) pstep(w, m, 3u);
    assert(w[1].state == HCWB_ST_READY);
    printf("  fault latches while the cause is gone, clears at key-off, bank "
           "re-qualifies: OK\n");
}

static void test_one_bank_enabled(void)
{
    hcwb_t w[2]; model_t m[2]; unsigned int i;
    pinit(w, m);
    prun(w, m, 1000u, 2u);
    set_running(m, 1u);
    for (i = 0u; i < 12000u && w[1].state != HCWB_ST_READY; i++) pstep(w, m, 2u);
    prun(w, m, 1500u, 2u);
    assert(w[0].state == HCWB_ST_OFF && w[0].duty_x10 == 0u && w[0].want == HCWB_MODE_COLD);
    assert(w[1].state == HCWB_ST_READY && ((status >> 2) & 7u) == 0u && (status & 3u) == 2u);
    printf("  only bank 2 on-board: bank 1 OFF / cold / heater off, bank 2 "
           "READY: OK\n");
}

static void test_ip_is_raw(void)
{
    hcwb_t w[2]; model_t m[2]; unsigned int i; unsigned char seen = 0u;
    pinit(w, m);
    pstep(w, m, 3u);
    assert(w[0].ip_ua == 0 && w[1].ip_ua == 0);  /* no pump zero yet */
    prun(w, m, 1000u, 3u);
    set_running(m, 1u);
    for (i = 0u; i < 12000u && w[0].state != HCWB_ST_READY; i++) {
        pstep(w, m, 3u);
        if (w[0].state == HCWB_ST_CLOSED && w[0].pa_ms > 0u && w[0].ip_ua > 150) {
            assert(w[0].valid == 0u && w[0].lambda == 0u);
            seen = 1u;
        }
    }
    assert(seen);
    printf("  Ip is published while lambda is still withheld (CLOSED, pump on): "
           "OK\n");
}

/* V97: the reason lambda is withheld, traced through a cold start on bank 1
   while bank 2 has no sensor: every stage names itself, in order, and the
   unfitted bank says FAULT (fcode 2) the whole time it is judged */
static void test_why_trace(void)
{
    hcwb_t w[2]; model_t m[2]; unsigned int i;
    unsigned char seen[16], last = 0xFFu, order[16], n = 0u, k;
    for (k = 0u; k < 16u; k++) seen[k] = 0u;
    pinit(w, m);
    m[1].sensor = 0u;
    set_key(m, 0u);
    pstep(w, m, 3u);
    assert(w[0].why == HCWB_WHY_OFF && w[1].why == HCWB_WHY_OFF);
    set_key(m, 1u);
    for (i = 0u; i < 16000u; i++) {
        if (i == 150u) set_running(m, 1u);
        pstep(w, m, 3u);
        seen[w[0].why] = 1u;
        if (w[0].why != last && n < 16u) { order[n++] = w[0].why; last = w[0].why; }
        if (w[0].valid) {
            assert(w[0].why == HCWB_WHY_VALID);
            break;
        }
        assert(w[0].lambda == 0u);
    }
    assert(w[0].valid);
    /* calibration, engine wait, preheat, ramp, settle, valid - in order */
    assert(seen[HCWB_WHY_CAL] && seen[HCWB_WHY_ENGINE] && seen[HCWB_WHY_PREHEAT]
           && seen[HCWB_WHY_RAMP] && seen[HCWB_WHY_SETTLE]);
    for (k = 1u; k < n; k++) {
        /* never goes backwards through the warm-up */
        assert(!(order[k] == HCWB_WHY_PREHEAT && order[k - 1u] == HCWB_WHY_RAMP));
    }
    assert(w[1].why == HCWB_WHY_FAULT && w[1].fcode == HCWB_F_HEATER_OPEN);
    printf("  reason trace bank 1:");
    for (k = 0u; k < n; k++) printf(" %u", order[k]);
    printf("; bank 2 (no sensor) FAULT/2: OK\n");
}

/* V97: a READY bank whose pump current leaves the amplifier swing (UA at a
   rail: an extreme mixture or a pump-line fault the DIAG cannot see) is not a
   measurement - reason UA, lambda 0, NO latched fault - and returns by
   itself; the other bank keeps measuring */
static void test_pump_saturated(void)
{
    hcwb_t w[2]; model_t m[2]; unsigned int i;
    pinit(w, m);
    to_ready(w, m, 3u);
    m[0].ua_shift = 800;                        /* UA pinned to the top rail */
    for (i = 0u; i < 300u; i++) {
        pstep(w, m, 3u);
        assert(w[1].valid == 1u);
    }
    assert(w[0].valid == 0u && w[0].lambda == 0u && w[0].why == HCWB_WHY_UA);
    assert(w[0].state == HCWB_ST_READY && w[0].fcode == 0u);
    m[0].ua_shift = 0;
    prun(w, m, 100u, 3u);
    assert(w[0].valid == 1u && w[0].why == HCWB_WHY_VALID);
    printf("  bank 1 pump current saturated: withheld (reason UA), no fault, "
           "back when it returns; bank 2 valid throughout: OK\n");
}

/* V97: a pump-line (IA/IP) short reported by DIAG on a pumping bank latches
   fault 4 on that bank only; an IA/IP code while the pump is still OFF is not
   judged (the lines mean nothing then) */
static void test_pump_line_fault(void)
{
    hcwb_t w[2]; model_t m[2]; unsigned int i;
    pinit(w, m);
    m[1].diag_force = 0xCFu;                    /* bank 2 IA/IP 00 from key-on */
    prun(w, m, 1000u, 3u);
    assert(w[1].state != HCWB_ST_FAULT);        /* pump off: not judged */
    set_running(m, 1u);
    for (i = 0u; i < 12000u && w[0].state != HCWB_ST_READY; i++) pstep(w, m, 3u);
    assert(w[0].state == HCWB_ST_READY);
    prun(w, m, 1500u, 3u);
    assert(w[1].state == HCWB_ST_FAULT && w[1].fcode == HCWB_F_LINE_IAIP);
    assert(w[1].duty_x10 == 0u && w[1].want == HCWB_MODE_COLD);
    assert(w[0].valid == 1u);
    printf("  bank 2 IA/IP short: judged only once pumping, fault 4, heater "
           "off, pump off; bank 1 valid: OK\n");
}

/* V97: implausible Ri on a READY bank - too low (over-heat) and too high
   (under-heat) for 0.5 s latch 10 / 11 on that bank alone; a UR the ASIC
   stops tagging for 1 s latches 12 */
static void test_ri_implausible(void)
{
    hcwb_t w[2]; model_t m[2];
    pinit(w, m);
    to_ready(w, m, 3u);
    m[1].ur_force = 90u;                        /* Ri ~ 14 ohm: over-heat */
    prun(w, m, 800u, 3u);
    assert(w[1].state == HCWB_ST_FAULT && w[1].fcode == HCWB_F_OVERHEAT);
    assert(w[0].valid == 1u);

    pinit(w, m);
    to_ready(w, m, 3u);
    m[0].ur_force = 700u;                       /* Ri ~ 410 ohm: under-heat */
    prun(w, m, 800u, 3u);
    assert(w[0].state == HCWB_ST_FAULT && w[0].fcode == HCWB_F_UNDERHEAT);
    assert(w[1].valid == 1u);

    pinit(w, m);
    to_ready(w, m, 3u);
    m[0].ur_force = HCWB_UR_NONE;               /* next acquisition loses tag */
    pstep(w, m, 3u);                            /* conversion completes */
    pstep(w, m, 3u);                            /* core consumes it */
    assert(w[0].valid == 2u                     /* 2026-10-10: one untagged
                                                   sample is HELD (gap)    */
           && w[0].why == HCWB_WHY_HELD);
    prun(w, m, 700u, 3u);
    assert(w[0].valid == 0u);                   /* withheld after 0.6 s    */
    prun(w, m, 500u, 3u);
    assert(w[0].state == HCWB_ST_FAULT && w[0].fcode == HCWB_F_NO_RI);
    assert(w[1].valid == 1u);
    printf("  Ri implausible: over-heat 10 / under-heat 11 / no UR 12, each on "
           "its own bank, the other valid: OK\n");
}

/* V97: an ECU reset while both sensors are hot (the core state is lost, the
   sensor is not): recalibrate, then the hot restart path - no 15 s preheat -
   back to valid in seconds */
static void test_reset_hot(void)
{
    hcwb_t w[2]; model_t m[2]; unsigned int i;
    pinit(w, m);
    m[0].amb = 400u; m[1].amb = 400u;           /* running exhaust */
    to_ready(w, m, 3u);
    hcwb_init(&w[0]); hcwb_init(&w[1]);         /* the reset */
    for (i = 0u; i < 1500u; i++) {              /* 15 s */
        pstep(w, m, 3u);
        assert(w[0].state != HCWB_ST_RAMP || i > 0u);
        if (w[0].valid && w[1].valid) break;
    }
    assert(w[0].valid && w[1].valid);
    assert(i * 10u < 8000u);                    /* well inside the dew wait */
    printf("  reset while hot: both valid again after %u ms (no preheat): OK\n",
           i * 10u);
}

static void test_asymmetric_transport(void)
{
    hcwb_t w[2]; model_t m[2]; unsigned int i;
    pinit(w, m); set_running(m, 1u);
    m[0].write_delay = 200u; m[0].ack_delay = 200u;
    m[0].adc_delay = 700u; m[0].contention = 100u;
    m[1].fail_write = 1u;
    for (i = 0u; i < 12000u; i++) {
        pstep(w, m, 3u);
        assert(!w[1].valid && !w[1].duty_x10);
        if (w[0].valid) break;
    }
    assert(w[0].valid && w[1].fcode && !w[1].urc);
    prun(w, m, 10000u, 3u);
    assert(w[0].valid && !w[1].valid && !w[1].duty_x10);
    puts("  asymmetric delayed SSC / failed write: only healthy bank qualifies: OK");
}

int main(void)
{
    printf("hcwb two-bank tests (hcwb_pair_step)\n");
    test_both_absent();
    test_one_absent(0u);
    test_one_absent(1u);
    test_status_bits();
    test_one_fails_running();
    test_chip_loss();
    test_bad_cal_one_bank();
    test_undervoltage();
    test_cold_no_fastpath();
    test_interrupted_warmup();
    test_key_cycle_mid_warmup();
    test_fault_latch();
    test_one_bank_enabled();
    test_ip_is_raw();
    test_why_trace();
    test_pump_saturated();
    test_pump_line_fault();
    test_ri_implausible();
    test_reset_hot();
    test_asymmetric_transport();
    printf("PASS: all hcwb two-bank tests\n");
    return 0;
}
