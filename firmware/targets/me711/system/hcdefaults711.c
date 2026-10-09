#include "hcfarbridge.h"
#include <reg167.h>
#include "hctarget.h"
#include "hcconfig.h"
#include "hc_config_generated.h"   /* CFG_U_* universal-block offsets */

void HC_COLD hc_cal_defaults711(void)
{
    unsigned char r, c;
    unsigned int i;

    for (i = HC_CFG_CORE; i < HC_CFG_SIZE; i++) {
        hc_cal_set_u8(i, 0);
    }

    /* Axes. rpm from idle to a little past the limiter.
     *
     * LOAD IS IN THE UNITS OF WHATEVER CAL_LOAD_SOURCE SELECTS - 0.1 kPa of
     * manifold pressure, or 0.1 % of throttle. The axis is calibration, so a
     * tuner who switches the source rescales the axis to match; the default
     * below is manifold pressure, 20..250 kPa, which is what a turbocharged
     * engine actually wants. */
    for (i = 0; i < CAL_AXIS_N; i++) {
        unsigned int rpm = (unsigned int)(500u + i * 450u);      /* 500..7250 */
        unsigned int load = (unsigned int)(200u + i * 2300u / (CAL_AXIS_N - 1));

        hc_cal_set_u16((unsigned int)(CAL_FUEL_RPM_AX + 2u * i), rpm);
        hc_cal_set_u16((unsigned int)(CAL_IGN_RPM_AX + 2u * i), rpm);
        hc_cal_set_u16((unsigned int)(CAL_FUEL_LOAD_AX + 2u * i), load);
        hc_cal_set_u16((unsigned int)(CAL_IGN_LOAD_AX + 2u * i), load);
    }

    /* r = rpm index, c = load index. THE CELL IS [load][rpm] (V97,
       hc_cal_map): TunerStudio's order, so a row on screen is one load. */
    for (r = 0; r < CAL_AXIS_N; r++) {
        for (c = 0; c < CAL_AXIS_N; c++) {
            unsigned int cell = (unsigned int)(c * CAL_AXIS_N + r);
            /* Column 0 is 20 kPa and column 15 is 250 kPa; as a percentage of
               atmospheric that is roughly 20..250, and the shapes below are
               written against 0..100 "percent of a full cylinder". */
            unsigned int loadpct = (unsigned int)(c * 100u / (CAL_AXIS_N - 1));

            /* VE: a flat 80.0 % (rusEFI's default table). Under speed
               density the MAP term already carries the load, so a VE that
               rose with load (this was a pulse-width table once) counted it
               twice. u16, 0.1 % per count. */
            hc_cal_set_u16((unsigned int)(CAL_FUEL_MAP + 2u * cell), 800u);

            /* Ignition: 10 deg at idle rising to 24 deg light-load, pulled
               back to 12 deg at full load because this engine is turbocharged
               and nobody should meet boost on a default map. One count is
               0.5 deg with a -20 deg offset. */
            {
                unsigned int adv = (unsigned int)(24u - (loadpct * 12u) / 100u);

                if (r == 0) {
                    adv = 10u;                    /* idle/cranking row */
                }
                hc_cal_set_u8((unsigned int)(CAL_IGN_MAP + cell),
                              (unsigned char)(adv * 2u + 40u));
            }

            /* Target AFR: stoichiometric off boost, progressively richer with
               load, 12.0 at full load. */
            hc_cal_set_u8((unsigned int)(CAL_AFR_MAP + cell),
                          (unsigned char)(147u - (loadpct * 27u) / 100u));
        }
    }

    /* Warm-up enrichment against coolant temperature. 100 = no enrichment. */
    for (i = 0; i < CAL_AXIS_N; i++) {
        int degc = (int)(-30 + (int)i * 10);      /* -30..+120 degC */
        unsigned int enr;

        hc_cal_set_u16((unsigned int)(CAL_CLT_ENR_AX + 2u * i),
                       (unsigned int)((degc * 10) + (int)CAL_TEMP_BIAS * 10));
        if (degc >= 60) {
            enr = 100u;
        } else {
            enr = (unsigned int)(100 + (60 - degc));   /* +1 % per degC below 60 */
        }
        if (enr > 255u) {
            enr = 255u;
        }
        hc_cal_set_u8((unsigned int)(CAL_CLT_ENR_VAL + i), (unsigned char)enr);
    }

    /* Cranking pulse width against coolant temperature. */
    for (i = 0; i < 8u; i++) {
        int degc = (int)(-30 + (int)i * 20);      /* -30..110 degC */
        unsigned int us;

        hc_cal_set_u16((unsigned int)(CAL_CRANK_PW_AX + 2u * i),
                       (unsigned int)((degc * 10) + (int)CAL_TEMP_BIAS * 10));
#if defined(TGT_ENGINE_RUNTIME)
        /* ME7.1.1's cranking table is FUEL MASS, 0.1 mg per cylinder
           per cycle: rusEFI's 27 mg base x its coolant multipliers
           (default_cranking.cpp), 87 mg at -30 C down to 27 mg warm. */
        {
            unsigned int d = (degc < 70) ? (unsigned int)(70 - degc) : 0u;
            us = (unsigned int)(270u + (d * d * 6u) / 100u);
        }
#else
        us = (unsigned int)(6000 - (degc + 30) * 30);
        if (us < 1500u) {
            us = 1500u;
        }
#endif
        hc_cal_set_u16((unsigned int)(CAL_CRANK_PW_VAL + 2u * i), us);
    }

    /* Dwell and injector dead time against battery voltage. Both get LONGER
       as the battery sags, which is exactly the cranking case, and a fixed
       number for either is wrong at the one moment that matters most. */
    for (i = 0; i < 8u; i++) {
        unsigned int mv100 = (unsigned int)(800u + i * 120u);   /* 8.0..16.4 V */

        hc_cal_set_u16((unsigned int)(CAL_DWELL_BATT_AX + 2u * i), mv100);
        /* 6.0 ms at 8 V down to 2.4 ms at 16 V, in 0.01 ms. */
        hc_cal_set_u16((unsigned int)(CAL_DWELL_BATT_VAL + 2u * i),
                       (unsigned int)(600u - i * 52u));
        /* 1900 us at 8 V down to 640 us at 16 V. */
        hc_cal_set_u16((unsigned int)(CAL_DEADTIME_VAL + 2u * i),
                       (unsigned int)(1900u - i * 180u));
    }

    /* Coolant sensor: a VAG-style NTC through the pull-up in CFG_CLT_PULLUP_OHM.
       Stored as a measured curve rather than a formula, because that is what a
       tuner can correct against a thermometer without recompiling anything. */
    {
        static const unsigned int cnt[CAL_AXIS_N] = {
             40u,  70u, 110u, 160u, 220u, 300u, 390u, 480u,
            570u, 660u, 740u, 810u, 870u, 920u, 960u, 1000u };
        static const int deg[CAL_AXIS_N] = {
            150, 130, 110,  95,  85,  75,  65,  55,
             45,  35,  25,  15,   5, -10, -25, -40 };

        for (i = 0; i < CAL_AXIS_N; i++) {
            hc_cal_set_u16((unsigned int)(CAL_CLT_SENS_AX + 2u * i), cnt[i]);
            hc_cal_set_u16((unsigned int)(CAL_CLT_SENS_VAL + 2u * i),
                           (unsigned int)((deg[i] * 10) + (int)CAL_TEMP_BIAS * 10));
        }
    }

    /* Charge air pressure sensor, connector pin 101 on AN14. A 2.5 bar sensor
       reading 20 kPa at 0.5 V and 250 kPa at 4.5 V, over a 1023-count 5 V
       span: 0 counts is about -8.8 kPa and the slope is 281 kPa per 1000
       counts. Stored in 0.1 kPa. */
    hc_cal_set_u16(CAL_MAP_SENS_OFF, 0u);
    hc_cal_set_u16(CAL_MAP_SENS_GRD, 2810u);

    /* Throttle and pedal end points. Deliberately the full span: a real
       calibration is taken by moving the pedal, and a span that is too wide
       reads low rather than pretending to be at full throttle. */
    hc_cal_set_u16(CAL_TPS1_MIN, 100u);
    hc_cal_set_u16(CAL_TPS1_MAX, 900u);
    hc_cal_set_u16(CAL_TPS2_MIN, 100u);
    hc_cal_set_u16(CAL_TPS2_MAX, 900u);
    hc_cal_set_u16(CAL_PEDAL1_MIN, 100u);
    hc_cal_set_u16(CAL_PEDAL1_MAX, 900u);
    hc_cal_set_u16(CAL_PEDAL2_MIN, 100u);
    hc_cal_set_u16(CAL_PEDAL2_MAX, 900u);

    /* The throttle. Disabled, and the gains are a starting point only - a
       real one is found on the bench with the plate in front of you. */
    hc_cal_set_u8(CAL_DBW_ENABLE, 0u);
    hc_cal_set_u16(CAL_DBW_KP, 400u);          /* 4.00 */
    hc_cal_set_u16(CAL_DBW_KI, 40u);           /* 0.40 */
    hc_cal_set_u16(CAL_DBW_DEV_X10, 150u);     /* 15 % of travel */
    hc_cal_set_u16(CAL_DBW_DEV_MS, 200u);
    hc_cal_set_u16(CAL_DBW_LIMP_X10, 60u);     /* 6 %, a fast idle */

    /* Intake air. No channel by default, because on this board the sensor is
       on the ASIC and the ASIC cannot be read. V97: a fault reads -40 degC
       (ENG_FAULT_TEMP_DC, hcengine.h); CAL_IAT_DEFAULT is stored but no
       longer read, and seeded with the same -40 so the page cannot say
       otherwise. */
    hc_cal_set_u8(CAL_IAT_CHANNEL, CAL_IAT_NONE);
    hc_cal_set_u16(CAL_IAT_DEFAULT, (unsigned int)((-40 + (int)CAL_TEMP_BIAS) * 10));
    for (i = 0; i < CAL_AXIS_N; i++) {
        /* The same NTC shape as the coolant sensor - most intake air sensors
           are the same part with a different housing, and it is a curve a
           tuner corrects against a thermometer anyway. */
        hc_cal_set_u16((unsigned int)(CAL_IAT_SENS_AX + 2u * i),
                       hc_cal_u16((unsigned int)(CAL_CLT_SENS_AX + 2u * i)));
        hc_cal_set_u16((unsigned int)(CAL_IAT_SENS_VAL + 2u * i),
                       hc_cal_u16((unsigned int)(CAL_CLT_SENS_VAL + 2u * i)));
    }

    /* ---------------------------------------------- the throttle, part 2 --
     *
     * The bias curve is rusEFI's, measured on the Bosch VAG throttle body -
     * which is the one on this car - and it is the reason the closed loop has
     * so little left to do. Read it as: to HOLD the plate at 1 % you must push
     * it SHUT with 15 % duty, because the return spring is winning at that
     * position; at 7 % it balances; above the limp-home detent it takes 20 %
     * or more to hold it open.
     *
     * Stored with a +1000 offset because the page has no signed type and the
     * negative half of this curve is the important half. */
    {
        static const unsigned int bias_ax[8]  = { 0, 10, 50, 70, 140, 650, 660, 1000 };
        static const int          bias_val[8] = { -150, -150, -100, 0, 190, 200, 260, 280 };

        for (i = 0; i < 8u; i++) {
            hc_cal_set_u16((unsigned int)(CAL_DBW_BIAS_AX + 2u * i), bias_ax[i]);
            hc_cal_set_u16((unsigned int)(CAL_DBW_BIAS_VAL + 2u * i),
                           (unsigned int)(1000 + bias_val[i]));
        }
    }
    /* POSITION DEADBAND, AND WHY ZERO IS NOT A SAFE DEFAULT HERE.
     * The plate position is an integer 0.1 % count, so the smallest error the
     * loop can represent that is not zero is one count - and at the AWT's KI
     * one count winds the integrator 3.5 % duty per second, to the +-30 %
     * clamp, forever, because stiction keeps the plate from giving that count
     * back for seconds at a time. Measured on the bench 2026-10-05: the
     * integrator never settled at ANY plateau of a 42-segment sweep, ramping
     * 218 -> -57 -> +156 -> -74 counts on consecutive 2 s holds, so no steady
     * holding duty existed to measure.
     * rusEFI has no ETB deadband and needs none: its TPS is a float percent at
     * 500 Hz, so its error shrinks continuously instead of quantizing to a
     * floor. Two counts covers the one-count quantum plus one count of noise -
     * 84 % of that run's settled samples - and leaves a real offset of 0.3 %
     * or more to the integrator. Its cost is up to 0.2 % of travel of steady
     * position error; the deviation supervisor's window is unaffected. */
    /* The OEM ME7.1.1's own bridge frequency (its port init programs
     * PP2 = 19999 at f_CPU, EXACT TARGET BINARY @0xC0D96). A different
     * throttle body may want another rate; hc_validation.c bounds it to
     * what the CJ220 is rated to switch. */
    hc_cal_set_u16(CFG_U_DBW_PWM_HZ, 2000u);   /* 2 kHz, the OEM value   */
    /* SENSOR FAULT CONFIRM TIME. hc_dbw.c drops the bridge on the FIRST bad
     * TPS/pedal sample and needs DBW_INIT_PASSES (4 x 5 ms) clean steps to
     * drive again, whatever this says; the confirm time only decides when a
     * fault that keeps going becomes final (latched to key-off, and engine
     * protection's fuel cut above etbLimpRpm). 0 latched one disturbed
     * conversion or a pedal step that put the two tracks one sample apart.
     * 50 ms = 10 control steps: a single bad sample (one step) or a short
     * burst of them is forgiven, a lasting fault latches within 55 ms. */
    hc_cal_set_u16(CFG_U_DBW_FAULT_DEBOUNCE_MS, 50u);
    hc_cal_set_u16(CFG_U_DBW_DEADBAND_X10, 2u); /* 0.2 % of travel           */
    hc_cal_set_u16(CAL_DBW_KD, 9u);            /* 0.09 - rusEFI's 0.088     */
    hc_cal_set_u16(CAL_DBW_MIN_X10, 0u);
    hc_cal_set_u16(CAL_DBW_MAX_X10, 1000u);
    hc_cal_set_u16(CAL_DBW_REVLIM_RPM, 0u);    /* off - the limiter cuts     */
    hc_cal_set_u16(CAL_DBW_REVLIM_RANGE, 300u);
    hc_cal_set_u16(CAL_DBW_AUTOCAL_MS, 1000u); /* rusEFI holds each stop 1 s */
    hc_cal_set_u16(CAL_DBW_AUTOCAL_DUTY, 500u);/* 50 %, likewise            */
    hc_cal_set_u16(CAL_DBW_TUNE_AMP, 200u);    /* 20 % relay amplitude      */

    /* Pedal to throttle. The default is a straight 1:1 at every engine speed,
       which is exactly what the module did before this map existed - so
       turning the map on changes nothing until somebody shapes it. */
    for (i = 0; i < CAL_AXIS_N; i++) {
        hc_cal_set_u16((unsigned int)(CAL_PEDAL_RPM_AX + 2u * i),
                       (unsigned int)(500u + i * 450u));
        hc_cal_set_u16((unsigned int)(CAL_PEDAL_AX + 2u * i),
                       (unsigned int)(i * 1000u / (CAL_AXIS_N - 1)));
    }
    for (r = 0; r < CAL_AXIS_N; r++) {
        for (c = 0; c < CAL_AXIS_N; c++) {
            /* One count is 0.5 %, so 100 % is 200 counts. [pedal][rpm]:
               c is the pedal index, r the rpm index. */
            hc_cal_set_u8((unsigned int)(CAL_PEDAL_MAP + c * CAL_AXIS_N + r),
                          (unsigned char)(c * 200u / (CAL_AXIS_N - 1)));
        }
    }

    /* ---------------------------------------------------------- boost -----
     *
     * OFF, and every default below is a shape rather than a tune. A boost
     * table that arrives with real numbers in it is a table somebody will
     * forget to check.
     */
    hc_cal_set_u8(CAL_BOOST_ENABLE, 0u);
    hc_cal_set_u8(CAL_BOOST_MODE, 0u);         /* open loop until proven    */
    for (i = 0; i < CAL_AXIS_N; i++) {
        unsigned int rpm = (unsigned int)(500u + i * 450u);
        unsigned int tps = (unsigned int)(i * 1000u / (CAL_AXIS_N - 1));

        hc_cal_set_u16((unsigned int)(CAL_BOOST_RPM_AX + 2u * i), rpm);
        hc_cal_set_u16((unsigned int)(CAL_BOOST_TGT_RPM_AX + 2u * i), rpm);
        hc_cal_set_u16((unsigned int)(CAL_BOOST_TPS_AX + 2u * i), tps);
        hc_cal_set_u16((unsigned int)(CAL_BOOST_TGT_TPS_AX + 2u * i), tps);
    }
    for (r = 0; r < CAL_AXIS_N; r++) {
        for (c = 0; c < CAL_AXIS_N; c++) {
            unsigned int cell = (unsigned int)(c * CAL_AXIS_N + r);

            /* Zero duty everywhere: the wastegate spring alone. That is the
               only starting point that cannot make more boost than the engine
               was built for. */
            hc_cal_set_u8((unsigned int)(CAL_BOOST_DUTY_MAP + cell), 0u);
            /* Target = spring pressure, so closed loop has nothing to chase
               until a tuner raises it. 1 count = 1 kPa absolute. */
            hc_cal_set_u8((unsigned int)(CAL_BOOST_TGT_MAP + cell), 150u);
        }
    }
    hc_cal_set_u16(CAL_BOOST_KP, 100u);        /* 1.00 */
    hc_cal_set_u16(CAL_BOOST_KI, 20u);         /* 0.20 */
    hc_cal_set_u16(CAL_BOOST_KD, 0u);
    hc_cal_set_u16(CAL_BOOST_MIN_RPM, 1500u);
    hc_cal_set_u16(CAL_BOOST_MIN_TPS_X10, 300u);
    hc_cal_set_u16(CAL_BOOST_FREQ_HZ, 30u);    /* N75 valves like 25..35 Hz */
    hc_cal_set_u16(CAL_BOOST_CUT_KPA, 2200u);  /* 220 kPa absolute = 1.2 bar */
    hc_cal_set_u16(CAL_BOOST_CUT_HYST, 150u);
    for (i = 0; i < 8u; i++) {
        /* Flat multipliers: no correction until somebody measures one. */
        hc_cal_set_u16((unsigned int)(CAL_BOOST_CLT_AX + 2u * i),
                       (unsigned int)(((int)(-20 + (int)i * 20) + (int)CAL_TEMP_BIAS) * 10));
        hc_cal_set_u16((unsigned int)(CAL_BOOST_CLT_MUL + 2u * i), 100u);
        hc_cal_set_u16((unsigned int)(CAL_BOOST_IAT_AX + 2u * i),
                       (unsigned int)(((int)(-20 + (int)i * 20) + (int)CAL_TEMP_BIAS) * 10));
        hc_cal_set_u16((unsigned int)(CAL_BOOST_IAT_MUL + 2u * i), 100u);
    }

    /* ------------------------------------------- the drivability four -----
     *
     * Acceleration enrichment and the overrun cut both start OFF: they change
     * fuel, and a default that changes fuel on an engine nobody has tuned is a
     * default that hides itself.
     */
    hc_cal_set_u16(CAL_ACCEL_THRESH_X10, 500u);  /* 50 %/s */
    hc_cal_set_u16(CAL_ACCEL_GAIN, 0u);          /* off    */
    hc_cal_set_u16(CAL_ACCEL_DECAY_MS, 300u);

    hc_cal_set_u16(CAL_OVERRUN_RPM, 0u);         /* off    */
    hc_cal_set_u16(CAL_OVERRUN_TPS_X10, 20u);
    hc_cal_set_u16(CAL_OVERRUN_RESUME, 1400u);

    /* The limiter DOES change, and deliberately: cutting spark alone pumps
       unburnt fuel into the exhaust, and that is how a limiter destroys a
       catalyst. Both, in a rotating pattern, six events out of eight. */
    /* FUEL ONLY by default. Cutting spark and leaving fuel pumps a full raw
       charge into the exhaust on every cut event, which is how a limiter
       destroys a catalyst - and cutting fuel alone limits the engine just as
       effectively, on a rotating pattern so no cylinder takes all of it. Spark
       cutting is available (0 or 2) and is a hard, whole cut when selected. */
    hc_cal_set_u8(CAL_REVLIM_MODE, 1u);
    hc_cal_set_u8(CAL_REVLIM_PATTERN, 6u);

    hc_cal_set_u8(CAL_IDLE_ENABLE, 0u);
    hc_cal_set_u8(CAL_IDLE_PAD, 0u);
    for (i = 0; i < 8u; i++) {
        int degc = -20 + (int)i * 20;            /* -20 .. 120 */
        unsigned int ax = (unsigned int)((degc + (int)CAL_TEMP_BIAS) * 10);
        /* 1300 rpm cold falling to 800 hot, and the throttle opening a tuner
           would expect to need to get there. */
        unsigned int tgt = (unsigned int)(degc < 80 ? 1300u - (unsigned int)(degc + 20) * 5u
                                                    : 800u);
        unsigned int base = (unsigned int)(degc < 80 ? 90u - (unsigned int)(degc + 20) / 4u
                                                     : 65u);

        hc_cal_set_u16((unsigned int)(CAL_IDLE_TARGET_AX + 2u * i), ax);
        hc_cal_set_u16((unsigned int)(CAL_IDLE_TARGET_VAL + 2u * i), tgt);
        hc_cal_set_u16((unsigned int)(CAL_IDLE_BASE_AX + 2u * i), ax);
        hc_cal_set_u16((unsigned int)(CAL_IDLE_BASE_VAL + 2u * i), base);
    }
    hc_cal_set_u16(CAL_IDLE_KP, 20u);          /* 0.20 - gentle            */
    hc_cal_set_u16(CAL_IDLE_KI, 5u);           /* 0.05                     */
    hc_cal_set_u16(CAL_IDLE_RANGE_X10, 50u);   /* 5 % of travel, no more   */
    hc_cal_set_u16(CAL_IDLE_RPM_BAND, 400u);

    hc_cal_set_u16(CAL_BARO_DEFAULT, 1000u);   /* 100.0 kPa */
    /* Ignored until the bench says which level is healthy. A guessed polarity
       either refuses to ever run, or ignores a real bridge fault - and one of
       those two is much worse than reading the pin first. */
    hc_cal_set_u16(CAL_DBW_SF_MODE, DBW_SF_IGNORE);

    hc_cal_set_u8(CAL_LOAD_SOURCE, CAL_LOAD_MAP);
    hc_cal_set_u8(CAL_INJ_MODE, 0u);            /* batch until the cam proves */
    hc_cal_set_u16(CAL_FUELPUMP_PRIME_MS, 2000u);
}


void HC_COLD hc_cfg_defaults711(void)
{
    unsigned int i;
    /* cylinder order, 0.1 degree: cyl1, cyl2, cyl3, cyl4 */
    static const unsigned int awt_tdc[4] = { 0u, 5400u, 1800u, 3600u };

    for (i = 0; i < HC_CFG_CORE; i++) {
        hc_cfg[i] = 0;
    }

    cfg_set_u16(CFG_VERSION, HC_CFG_VERSION);
    cfg_set_u8(CFG_CYLINDERS, 4);
    cfg_set_u8(CFG_STROKES, 4);
    for (i = 0; i < HC_MAX_CYL; i++) {
        cfg_set_u16((unsigned char)(CFG_TDC_CYL + 2 * i),
                    (i < 4) ? awt_tdc[i] : 0u);
    }

    cfg_set_u16(CFG_SY_TEETH, 60);          /* SY_TEETH, 60-2 crank wheel */
    cfg_set_u8(CFG_SY_GAP, 2);              /* SY_GAP                     */
    cfg_set_u8(CFG_TRIG_EDGE, 0);           /* falling                    */
    cfg_set_u16(CFG_TRIG_GAP_RATIO_X10, 25);/* 2.5x the last tooth        */
    cfg_set_u8(CFG_TRIG_MIN_TEETH, 6);
    cfg_set_u8(CFG_TRIG_TIMEOUT_MS, 200);

    cfg_set_u16(CFG_REV_MAX, 7500);
    cfg_set_u16(CFG_REV_MIN, 80);

    cfg_set_u8(CFG_CAM_ENABLE, 1);
    cfg_set_u8(CFG_CAM_EDGE, 0);

    /* Logical output index per cylinder, in cylinder order. The mapping from
       index to a physical pin is hctarget.h's job. 0xFF = unused, which is
       what cylinders 5-8 are on a four-cylinder engine. */
    /* The factory wiring, so a freshly flashed ECU works on the original loom
       without anyone rebuilding the pin map.

       The board's output channels are numbered in FIRING order, not cylinder
       order - EV1/ZUE1I is the first to fire, which is cylinder 1, EV2 is the
       second, which is cylinder 3, and so on. Evidence: the 30344 and 30397
       driver sheets in pinouts/Pinout.xlsx map E1..E4 through to ECU
       connector pins 96/97/88/89 and 102/103/94/95, whose VAG codes are
       N30/N32/N33/N31 = cylinders 1/3/4/2. Both sequences are 1-3-4-2, the
       1.8T firing order.

       So in CYLINDER order the channel indices are 0, 3, 1, 2. Getting this
       backwards puts fuel and spark in the wrong cylinder, which is why it is
       written out rather than computed. */
    {
        static const unsigned char awt_chan[4] = { 0, 3, 1, 2 };

        for (i = 0; i < HC_MAX_CYL; i++) {
            hc_cfg[CFG_INJ_CHANNEL + i] = (i < 4) ? awt_chan[i] : 0xFF;
            hc_cfg[CFG_IGN_CHANNEL + i] = (i < 4) ? awt_chan[i] : 0xFF;
        }
    }

    cfg_set_u16(CFG_REV_LIMIT, 6800);
    cfg_set_u16(CFG_CRANK_RPM_MAX, 400);
    cfg_set_u16(CFG_DWELL_MS_X100, 300);      /* 3.00 ms */
    cfg_set_u16(CFG_INJ_DEADTIME_US, 1000);
    cfg_set_u16(CFG_INJ_START_DEG_X10, 3600); /* 360.0 deg BTDC */
    cfg_set_u16(CFG_IGN_ADVANCE_DEG_X10, 100);/* 10.0 deg, cranking-safe */

    cfg_set_u16(CFG_ADC_BATT_FS_DV, TGT_ADC_BATT_FS_DV);
    cfg_set_u16(CFG_CLT_PULLUP_OHM, 1000);
    cfg_set_u16(CFG_IAT_PULLUP_OHM, 1000);

    /* Nothing is driven until the bench says so. An output that comes up armed
       after a reset is how a wrong pin becomes a burnt driver. */
    cfg_set_u8(CFG_OUTPUTS_ARMED, 0);
    cfg_set_u8(CFG_FLAGS, 0);
    cfg_set_u16(CFG_SIM_RPM, 0);      /* the generator is off */
    /* Nothing is armed on an input until somebody says a sensor is connected.
       An unconnected P2.15 produces captures out of noise. */
    cfg_set_u8(CFG_TRIG_SOURCE, TRIG_SRC_BENCH);
    cfg_set_u8(CFG_MAIN_RELAY_MODE, MAIN_RELAY_OFF);
    cfg_set_u16(CFG_MAIN_RELAY_GRACE_MS, 500u);
    hc_cal_defaults711();
}

