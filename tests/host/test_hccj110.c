/*
 * test_hccj110.c - host test for the CJ110 wideband core (hccj110.c),
 * gcc -std=c89. Run by tests/host/test_hccj110_host.py.
 *
 * A small CHIP model: with LA high UA sits at the chip's offset (the
 * pump-current zero); with LA low it follows the pump current of a sensor
 * at a given lambda (UA = zero + 17 x 61.9 ohm x Ip, i.e. the stock LALIUS
 * curve shifted by the zero). Assertions are about outputs only.
 */
#include <assert.h>
#include <stdio.h>
#include "hccj110.h"

/* the stock curve's own points, used as the "true" sensor here */
static const unsigned int pts_ua[]  = { 28u, 203u, 305u, 307u, 393u, 565u, 738u };
static const unsigned int pts_lam[] = { 730u, 879u, 1000u, 1004u, 1200u, 2000u, 5000u };

typedef struct {
    unsigned int zero;      /* this chip's UA at Ip = 0 (offset)          */
    unsigned int ua_meas;   /* UA in measurement mode, table units        */
    unsigned char diag;     /* chip diagnosis active                      */
} chip_t;

static unsigned int chip_ua(const chip_t *m, unsigned char la)
{
    if (m->diag) return 1000u;                  /* VCC - 0.175 V and above */
    if (la) return m->zero;
    /* the sensor's UA relative to the table zero 307, moved by the offset */
    return (unsigned int)(m->ua_meas + m->zero - 307u);
}

static void run(hccj110_t *c, chip_t *m, unsigned char hot, unsigned int ms)
{
    unsigned int t;
    for (t = 0u; t < ms; t += 10u) hccj110_step(c, chip_ua(m, c->la), hot, 10u);
}

static void test_table(void)
{
    unsigned int x, i, prev = 0u;
    for (i = 0u; i < sizeof pts_ua / sizeof pts_ua[0]; i++)
        assert(hccj110_lambda_x1000(pts_ua[i]) == pts_lam[i]);
    assert(hccj110_lambda_x1000(0u) == 730u);           /* clamped ends   */
    assert(hccj110_lambda_x1000(1023u) == 5000u);
    for (x = 0u; x <= 1023u; x++) {                     /* monotonic, no  */
        unsigned int l = hccj110_lambda_x1000(x);       /* 16-bit wrap    */
        assert(l >= prev && l >= 730u && l <= 5000u);
        prev = l;
    }
    printf("  LALIUS table: stock points exact, monotonic over 0..1023: OK\n");
}

static void test_calibration_and_lambda(void)
{
    hccj110_t c; chip_t m;
    unsigned int i;
    m.zero = 312u; m.ua_meas = 305u; m.diag = 0u;       /* offset +5 counts */
    hccj110_init(&c);
    assert(c.la == 1u && c.st == HCCJ110_ST_CAL_SETTLE);
    run(&c, &m, 0u, 150u);
    assert(c.la == 1u && c.valid == 0u);                /* still settling */
    run(&c, &m, 0u, 200u);
    assert(c.st == HCCJ110_ST_MEASURE && c.la == 0u && c.ua0 == 312u);
    assert(c.valid == 0u && c.lambda == 0u);            /* cold: no lambda */
    run(&c, &m, 1u, 20u);
    assert(c.valid == 0u && c.lambda == 0u);            /* hot, at 1: not ready */
    m.ua_meas = 393u;                                   /* lambda 1.20     */
    run(&c, &m, 1u, 150u);
    assert(c.valid == 0u);                              /* < TSTBB         */
    run(&c, &m, 1u, 60u);
    assert(c.valid == 1u && c.lambda == 1200u && c.ready);
    m.ua_meas = 305u;
    run(&c, &m, 1u, 20u);
    assert(c.valid == 1u && c.lambda == 1000u);         /* offset removed  */
    for (i = 0u; i < sizeof pts_ua / sizeof pts_ua[0]; i++) {
        m.ua_meas = pts_ua[i];
        run(&c, &m, 1u, 20u);
        assert(c.valid == 1u && c.lambda == pts_lam[i]);
    }
    run(&c, &m, 0u, 20u);
    assert(c.valid == 0u && c.lambda == 0u);            /* cooled: withdrawn */
    printf("  calibration: LA high 200 ms + 8 samples, UA0 312, LA low; "
           "lambda only when hot and once away from 1 for 200 ms, "
           "offset-corrected: OK\n");
}

static void test_cal_out_of_window(void)
{
    hccj110_t c; chip_t m;
    m.zero = 340u; m.ua_meas = 307u; m.diag = 0u;       /* > ULSUAMX 328  */
    hccj110_init(&c);
    run(&c, &m, 1u, 1000u);
    /* GGLSU: implausible = not adjusted, no fault, the stock zero stays */
    assert(c.st == HCCJ110_ST_MEASURE && c.fcode == HCCJ110_F_NONE);
    assert(c.ua0 == HCCJ110_UA0_NOM && c.cal_ok == 0u && c.la == 0u);
    m.zero = 280u;                                      /* < ULSUAMN 287  */
    hccj110_init(&c);
    run(&c, &m, 1u, 1000u);
    assert(c.fcode == HCCJ110_F_NONE && c.ua0 == HCCJ110_UA0_NOM);
    /* after start the adjustment runs again: now plausible -> taken, and
       readiness already reached is kept */
    m.ua_meas = 393u;
    run(&c, &m, 1u, 300u);
    assert(c.ready && c.valid);
    m.zero = 312u;
    hccj110_recal(&c);
    assert(c.la == 1u && c.valid == 0u);
    run(&c, &m, 1u, 350u);
    assert(c.st == HCCJ110_ST_MEASURE && c.ua0 == 312u && c.cal_ok == 1u);
    run(&c, &m, 1u, 20u);
    assert(c.valid == 1u && c.lambda == 1200u);
    printf("  calibration window 287..328 both ways: implausible = no "
           "fault, stock zero kept; recal after start takes a good one: OK\n");
}

static void test_chip_diagnosis(void)
{
    hccj110_t c; chip_t m;
    m.zero = 307u; m.ua_meas = 393u; m.diag = 0u;
    hccj110_init(&c);
    run(&c, &m, 1u, 500u);
    assert(c.valid == 1u && c.lambda == 1200u);
    m.diag = 1u;
    run(&c, &m, 1u, 1000u);                             /* short: no latch */
    assert(c.valid == 0u && c.lambda == 0u && c.st == HCCJ110_ST_MEASURE);
    m.diag = 0u;
    run(&c, &m, 1u, 20u);
    assert(c.valid == 1u && c.lambda == 1200u);         /* recovers        */
    m.diag = 1u;
    run(&c, &m, 1u, 2100u);                             /* > TVCJLSU 2 s   */
    assert(c.st == HCCJ110_ST_FAULT && c.fcode == HCCJ110_F_CHIP);
    m.diag = 0u;
    run(&c, &m, 1u, 500u);
    assert(c.st == HCCJ110_ST_FAULT && c.valid == 0u);  /* latched         */
    printf("  chip diagnosis: lambda withdrawn at once, latched after 2 s: OK\n");
}

static void test_no_sensor(void)
{
    hccj110_t c; chip_t m;
    m.zero = 307u; m.ua_meas = 307u; m.diag = 0u;       /* no LSU: Ip 0   */
    hccj110_init(&c);
    run(&c, &m, 0u, 400u);
    run(&c, &m, 1u, 59000u);
    assert(c.valid == 0u && c.lambda == 0u && c.st == HCCJ110_ST_MEASURE);
    m.ua_meas = 312u;                                   /* 1.010: not > SDLAB */
    run(&c, &m, 1u, 500u);
    assert(c.valid == 0u);
    m.ua_meas = 307u;
    run(&c, &m, 1u, 600u);
    assert(c.st == HCCJ110_ST_FAULT && c.fcode == HCCJ110_F_NOSIG);
    assert(c.valid == 0u && c.lambda == 0u && c.la == 0u);
    /* a 150 ms excursion alone does not make a sensor ready */
    hccj110_init(&c);
    run(&c, &m, 0u, 400u);
    m.ua_meas = 393u; run(&c, &m, 1u, 150u);
    m.ua_meas = 307u; run(&c, &m, 1u, 1000u);
    assert(c.valid == 0u && c.ready == 0u);
    printf("  missing sensor (lambda stays 1): never valid, NO SIGNAL "
           "after 60 s hot: OK\n");
}

int main(void)
{
    printf("hccj110 host tests\n");
    test_table();
    test_calibration_and_lambda();
    test_cal_out_of_window();
    test_chip_diagnosis();
    test_no_sensor();
    printf("all hccj110 tests passed\n");
    return 0;
}
