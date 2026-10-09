/*
 * hcconfig.c - the TunerStudio constants page, and where it is kept.
 *
 * See hcconfig.h for the portability contract. This file is target-independent
 * on purpose: everything board-specific it needs comes from hctarget.h.
 */
#include <reg167.h>
#include "hctarget.h"
#include "hcconfig.h"
#include "hcts.h"
#include "hc_config_manager.h"

unsigned char hc_cfg[HC_CFG_CORE];
unsigned int  hc_cfg_source;
unsigned int  hc_ram_bad;

/* ------------------------------------------------------ external SRAM ----
 *
 * TC55257, 32 KB, chip select P6.1, mapped at TGT_EXTRAM_BASE by the startup
 * code. Its VDD comes from VSTBY on the schematic, so it is battery-backed and
 * keeps its contents with the ignition off.
 *
 * NOTHING HAD EVER READ OR WRITTEN IT before this milestone. The bus setup was
 * copied from the stock application entry and assumed to work. hc_ram_probe()
 * checks that assumption at boot and publishes the result rather than letting
 * a dead bus turn into a mystery further down.
 *
 * `huge` because the SMALL memory model's default pointers are 16-bit and this
 * lives at 0x380000. Verified against the compiler's own output: it builds a
 * 32-bit pointer in a register pair.
 */
#define RAM  ((unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_CFG))

/* Header, kept OUTSIDE the TunerStudio page. If the checksum lived inside the
   page, every TunerStudio write would invalidate it. */
#define HDR_MAGIC     0uL      /* u32 */
#define HDR_VERSION   4uL      /* u16 */
#define HDR_SIZE      6uL      /* u16 */
#define HDR_SUM       8uL      /* u16 */
#define HDR_LEN       ((unsigned long)HC_CFG_HDR_LEN)
#define HC_CFG_MAGIC  0x48433031uL   /* "HC01" */

static unsigned int ram_u16(unsigned long off)
{
    return (unsigned int)(((unsigned int)RAM[off] << 8) | RAM[off + 1]);
}

static void ram_set_u16(unsigned long off, unsigned int v)
{
    RAM[off]     = (unsigned char)(v >> 8);
    RAM[off + 1] = (unsigned char)(v & 0xFF);
}

static unsigned long ram_u32(unsigned long off)
{
    return ((unsigned long)ram_u16(off) << 16) | ram_u16(off + 2);
}

static void ram_set_u32(unsigned long off, unsigned long v)
{
    ram_set_u16(off, (unsigned int)(v >> 16));
    ram_set_u16(off + 2, (unsigned int)(v & 0xFFFFuL));
}

/* A validity marker, not integrity protection. The failure it has to catch is
   "this SRAM has never been written", and magic + version + size + this is
   comfortably enough for that. */
static unsigned int cfg_sum(void)
{
    unsigned int s = 0xA5A5;
    unsigned int i;

    /* The scalars from near RAM and the tables from the SRAM they live in.
       Both halves are the page, so both halves are in the checksum - or a
       fresh, never-written SRAM would pass with garbage maps. */
    for (i = 0; i < HC_CFG_CORE; i++) {
        s = (unsigned int)((s << 1) | (s >> 15));   /* rotate, so order counts */
        s = (unsigned int)(s + hc_cfg[i]);
    }
    for (i = HC_CFG_CORE; i < HC_CFG_SIZE; i++) {
        /* THE SUPERVISION YIELD, every 256 bytes. MEASURED, not stylistic:
           this loop is 4096 huge-pointer reads with a 32-bit address add on
           each one, and hc_cfg_commit() - which every TunerStudio Burn calls -
           took 33 ms of a 10 ms S5500 raster because of it. The yield is the
           same mechanism hcts_tx() uses to survive a 112 ms blocking reply; it
           is tick-gated, so sixteen calls cost almost nothing and the worst
           service gap through here drops to about a millisecond.
           It is safe before the ASIC state machine exists: the target's yield
           returns immediately until main() arms it. */
        if ((i & 0x00FFu) == 0u) {
            hcts_target_yield();
        }
        s = (unsigned int)((s << 1) | (s >> 15));
        s = (unsigned int)(s + RAM[HDR_LEN + (unsigned long)i]);
    }
    return s;
}

/* Write a byte pattern that no plausible bus fault reproduces, read it back,
   and count the mismatches. Deliberately does NOT use the configuration area:
   it runs before the configuration is loaded and must not destroy a good one,
   so it works in a scratch window past the header and the page. */
#define PROBE_OFF   (HDR_LEN + (unsigned long)HC_CFG_SIZE)
#define PROBE_LEN   256u

/* ONE BYTE, and it is in the SRAM rather than in near RAM ON PURPOSE.
 *
 * It says whether this ECU really has a committed calibration record in a
 * non-volatile device, and only a target's non-volatile store ever writes it
 * (hcnvm.c on the ME7.1.1). Near RAM on that target is 1792 bytes and
 * near_ram_hazard_proof holds a 192-byte engineering reserve for the engine
 * subsystems still to land; the whole persistence feature was written to cost
 * ZERO of it, and one stray global here would have been three bytes of the
 * three that were left.
 *
 * It sits just past the RAM probe, inside the region TGT_RAM_CFG already
 * reserves, and hc_cfg_init() clears it at every boot before anything can set
 * it - so a battery-backed 1 from a previous firmware cannot outlive the store
 * that justified it. */
#define NONVOL_OFF  (PROBE_OFF + (unsigned long)PROBE_LEN)

/* HDR_LEN and PROBE_OFF carry casts and the preprocessor cannot evaluate one,
   so this guard uses the UNCAST constants they are built from. It does not
   restate a single number: HC_CFG_HDR_LEN, HC_CFG_SIZE, PROBE_LEN and
   TGT_RAM_CFG_LIMIT are all still the only definitions. */
#if ((HC_CFG_HDR_LEN + HC_CFG_SIZE + PROBE_LEN + 1) > TGT_RAM_CFG_LIMIT)
#error "the calibration page, its probe and the persistence flag do not fit"
#endif

static void hc_ram_probe(void)
{
    unsigned int i;
    unsigned char v;

    hc_ram_bad = 0;
    for (i = 0; i < PROBE_LEN; i++) {
        RAM[PROBE_OFF + i] = (unsigned char)(i ^ 0x5A);
    }
    for (i = 0; i < PROBE_LEN; i++) {
        v = RAM[PROBE_OFF + i];
        if (v != (unsigned char)(i ^ 0x5A)) {
            hc_ram_bad++;
        }
    }
}

/* ------------------------------------------------------------ accessors -- */
unsigned int cfg_u16(unsigned char off)
{
    return (unsigned int)(((unsigned int)hc_cfg[off] << 8) | hc_cfg[off + 1]);
}

void cfg_set_u16(unsigned char off, unsigned int v)
{
    hc_cfg[off]     = (unsigned char)(v >> 8);
    hc_cfg[off + 1] = (unsigned char)(v & 0xFF);
}

/* ---------------------------------------------------------- validation --
 *
 * Bosch Motorsport state the rule plainly for their own engine setup: "A valid
 * setup configuration is indicated by engsetupOK_b = TRUE. If the setup is not
 * accepted the injection is switched off for safety reasons."
 *
 * The same rule, for the same reason. TunerStudio writes this page one value
 * at a time, so an edit in progress passes through combinations that describe
 * no real engine - four cylinders still listed while the count already says
 * eight, two cylinders momentarily at the same TDC angle. Acting on any of
 * those means firing an output at the wrong time.
 */
unsigned int hc_cfg_faults(void)
{
    unsigned int f = 0;
    unsigned int n;
    unsigned int i, j;
    unsigned int a;

    if (cfg_u16(CFG_VERSION) != HC_CFG_VERSION) {
        f |= CFG_FAULT_VERSION;
    }

    n = (unsigned int)cfg_u8(CFG_CYLINDERS);
    if (n < 1 || n > HC_MAX_CYL) {
        f |= CFG_FAULT_CYLINDERS;
        return f;                    /* nothing below is meaningful without it */
    }
    if (cfg_u8(CFG_STROKES) != 2 && cfg_u8(CFG_STROKES) != 4) {
        f |= CFG_FAULT_STROKES;
    }

    /* A wheel needs more teeth than it is missing, and a gap of zero is not a
       gap. The upper bound is what a 16-bit tooth counter and the angle maths
       can carry, not a guess about what wheels exist. */
    if (cfg_u16(CFG_SY_TEETH) < 4 || cfg_u16(CFG_SY_TEETH) > 200
        || cfg_u8(CFG_SY_GAP) < 1
        || (unsigned int)cfg_u8(CFG_SY_GAP) >= cfg_u16(CFG_SY_TEETH)) {
        f |= CFG_FAULT_TEETH;
    }

    /* TDC angles: inside two crank revolutions, and no two cylinders sharing
       one. A duplicate is how a half-finished edit fires two cylinders at the
       same instant. */
    for (i = 0; i < n; i++) {
        a = cfg_u16((unsigned char)(CFG_TDC_CYL + 2 * i));
        if (a > 7200) {
            f |= CFG_FAULT_TDC_RANGE;
        }
        for (j = 0; j < i; j++) {
            if (a == cfg_u16((unsigned char)(CFG_TDC_CYL + 2 * j))) {
                f |= CFG_FAULT_TDC_DUP;
            }
        }
    }

    /* Output indices must exist on this board, or be explicitly unused. */
    for (i = 0; i < n; i++) {
        if (hc_cfg[CFG_INJ_CHANNEL + i] != 0xFF
            && hc_cfg[CFG_INJ_CHANNEL + i] >= TGT_N_INJ) {
            f |= CFG_FAULT_CHANNEL;
        }
        if (hc_cfg[CFG_IGN_CHANNEL + i] != 0xFF
            && hc_cfg[CFG_IGN_CHANNEL + i] >= TGT_N_IGN) {
            f |= CFG_FAULT_CHANNEL;
        }
    }

    if (cfg_u16(CFG_REV_MAX) < 1000
        || cfg_u16(CFG_REV_LIMIT) > cfg_u16(CFG_REV_MAX)
        || cfg_u16(CFG_REV_MIN) >= cfg_u16(CFG_REV_MAX)) {
        f |= CFG_FAULT_REV;
    }
    return f;
}

/* ------------------------------------------------------------- defaults --
 *
 * 1.8T AWT, which is the first engine this will run: four cylinders, a 60-2
 * crank wheel, firing 1-3-4-2.
 *
 * SY_TEETH = 60 and SY_GAP = 2 are the ME7 Funktionsrahmen's own values for a
 * 60-2 crank wheel ("SY_TEETH = 60 bei 60-2 KW Geberrad").
 *
 * The TDC angles encode the firing order: an evenly-firing four-cylinder puts
 * a cylinder at TDC every 180 crank degrees over a 720 degree cycle, and
 * 1-3-4-2 means cylinder 1 at 0, cylinder 3 at 180, cylinder 4 at 360 and
 * cylinder 2 at 540. Expressed per cylinder, in cylinder order, that is
 * 0 / 540 / 180 / 360.
 *
 * The zero point is a placeholder. It is the angle from the second tooth after
 * the gap to cylinder 1 TDC, and it is a MEASUREMENT on the engine, not a
 * number anyone can derive. Until it is measured the engine cannot be timed,
 * which is why the outputs also default to disarmed.
 */
/* ------------------------------------------------- default calibration --
 *
 * A 1.8T AWT that would actually start, not a page of zeros. Every number here
 * is a STARTING POINT for a tuner, and the ones that matter for not hurting
 * anything - ignition advance, target AFR - are deliberately conservative:
 * late timing and a rich mixture are slow, not expensive.
 *
 * Nothing here is claimed to be a Bosch calibration. The shapes come from
 * docs/ARCHITECTURE.md; the numbers are ordinary engine practice.
 */
#ifdef TGT_DEADLINE_EXECUTOR
void HC_COLD hc_cal_defaults711(void);
#define cal_defaults hc_cal_defaults711
#else
static void cal_defaults(void)
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

#endif

#ifdef TGT_DEADLINE_EXECUTOR
void HC_COLD hc_cfg_defaults711(void);
#define hc_cfg_defaults hc_cfg_defaults711
#else
static void hc_cfg_defaults(void)
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
    cal_defaults();
}

#endif

/* ------------------------------------------------------------ lifecycle -- */
void hc_cfg_commit(void)
{
    unsigned int i;

    /* The firmware owns the version field: a page written by an older
       TunerStudio project must not be able to claim a version it is not. */
    cfg_set_u16(CFG_VERSION, HC_CFG_VERSION);

    /* Only the scalars are mirrored - the tables are ALREADY in this SRAM and
       were edited in place. Copying them over themselves would be pointless
       and would double the burn time for no gain. */
    for (i = 0; i < HC_CFG_CORE; i++) {
        RAM[HDR_LEN + i] = hc_cfg[i];
    }
    ram_set_u32(HDR_MAGIC, HC_CFG_MAGIC);
    ram_set_u16(HDR_VERSION, HC_CFG_VERSION);
    ram_set_u16(HDR_SIZE, HC_CFG_SIZE);
    ram_set_u16(HDR_SUM, cfg_sum());
}

/* What a burn is actually worth on this board. See the long note beside the
   HC_PERSIST_* defines in hcconfig.h - this is deliberately a FUNCTION and not
   a constant, so the day a flash journal exists there is exactly one line to
   change and every caller learns about it at once. */
unsigned int hc_cfg_persist_class(void)
{
    /* Order matters. A flash record is worth more than the SRAM even when the
       SRAM is broken - it is what a cold ECU comes up on - so the non-volatile
       answer is tested first. It cannot be trusted from a dead store, though,
       which is why hc_ram_bad gates the read as well as the fallback. */
    if (!hc_ram_bad && RAM[NONVOL_OFF] == 1u) {
        return HC_PERSIST_NONVOL;
    }
    return hc_ram_bad ? HC_PERSIST_NONE : HC_PERSIST_STANDBY;
}

/* Called by a target's non-volatile store, and by nothing else. */
void hc_cfg_set_nonvol(unsigned char present)
{
    if (!hc_ram_bad) {
        RAM[NONVOL_OFF] = (unsigned char)(present ? 1u : 0u);
    }
}

void hc_cfg_init(void)
{
    unsigned int i;

    hc_ram_probe();
    hc_cfg_migrated = 0u;

    /* Explicitly, and AFTER the probe because it writes to the SRAM: nothing
       here begins at zero on its own - the ME7.1.1 startup hands straight to
       main() and never runs Keil's ?C_INIT, and this byte is battery-backed
       besides. A target's non-volatile store sets it after its own scan. */
    hc_cfg_set_nonvol(0u);

    if (hc_ram_bad) {
        /* No usable backing store. Run on defaults and say so - refusing to
           run would take the ECU off the air for a fault that does not stop
           the engine from working. */
        hc_cfg_defaults();
        hc_cfg_source = 2;
        return;
    }

    if (ram_u32(HDR_MAGIC) == HC_CFG_MAGIC
        && ram_u16(HDR_VERSION) == HC_CFG_VERSION
        && ram_u16(HDR_SIZE) == HC_CFG_SIZE) {
        for (i = 0; i < HC_CFG_CORE; i++) {
            hc_cfg[i] = RAM[HDR_LEN + i];
        }
        if (cfg_sum() == ram_u16(HDR_SUM) && hc_cfg_page_known()) {
            hc_cfg_source = 1;              /* restored from standby SRAM */
            return;
        }
    }

    hc_cfg_defaults();
    hc_cfg_commit();
    hc_cfg_source = 0;                      /* fresh defaults */
}

/* ======================================= the whole page, and the tables ==
 *
 * One flat address space for TunerStudio and for every lookup: below
 * HC_CFG_CORE the byte is in near RAM, above it the byte is in the
 * battery-backed SRAM. Nothing outside this file needs to know which.
 */
unsigned char hc_cal_u8(unsigned int off)
{
    if (off < HC_CFG_CORE) {
        return hc_cfg[off];
    }
    if (off >= HC_CFG_SIZE) {
        return 0;
    }
    return RAM[HDR_LEN + (unsigned long)off];
}

void hc_cal_set_u8(unsigned int off, unsigned char v)
{
    if (off < HC_CFG_CORE) {
        hc_cfg[off] = v;
        return;
    }
    if (off < HC_CFG_SIZE) {
        RAM[HDR_LEN + (unsigned long)off] = v;
    }
}

unsigned int hc_cal_u16(unsigned int off)
{
    return (unsigned int)(((unsigned int)hc_cal_u8(off) << 8)
                          | hc_cal_u8((unsigned int)(off + 1)));
}

void hc_cal_set_u16(unsigned int off, unsigned int v)
{
    hc_cal_set_u8(off, (unsigned char)(v >> 8));
    hc_cal_set_u8((unsigned int)(off + 1), (unsigned char)(v & 0xFF));
}

/* ------------------------------------------------------- interpolation --
 *
 * Both of these CLAMP at the ends. An axis that stops at 7000 rpm must not be
 * asked to invent a value at 8000: extrapolating a fuel or ignition table off
 * the end of its own axis is how an engine gets hurt, and a tuner who sees the
 * last cell held knows exactly what happened.
 *
 * Axes must be ascending. A descending or unsorted axis is a calibration
 * error, and the search below simply stops at the first cell that is not
 * smaller - which yields the first cell, i.e. the safest end.
 */
static unsigned char cal_bracket(unsigned int ax_off, unsigned char n,
                                 unsigned int x, unsigned int *frac)
{
    unsigned char i;
    unsigned int lo, hi;

    *frac = 0;
    if (x <= hc_cal_u16(ax_off)) {
        return 0;
    }
    for (i = 1; i < n; i++) {
        hi = hc_cal_u16((unsigned int)(ax_off + 2u * i));
        if (x <= hi) {
            lo = hc_cal_u16((unsigned int)(ax_off + 2u * (i - 1)));
            if (hi > lo) {
                /* 0..256 rather than 0..255: the top of the cell has to be
                   reachable or every interpolation is short by one cell edge. */
                *frac = (unsigned int)(((unsigned long)(x - lo) * 256uL)
                                       / (unsigned long)(hi - lo));
            }
            return (unsigned char)(i - 1);
        }
    }
    return (unsigned char)(n - 1);          /* past the end: hold the last */
}

unsigned int hc_cal_curve16(unsigned int ax_off, unsigned int val_off,
                            unsigned char n, unsigned int x)
{
    unsigned int frac;
    unsigned char i = cal_bracket(ax_off, n, x, &frac);
    unsigned int a, b;

    a = hc_cal_u16((unsigned int)(val_off + 2u * i));
    if (frac == 0 || i + 1 >= n) {
        return a;
    }
    b = hc_cal_u16((unsigned int)(val_off + 2u * (i + 1)));
    if (b >= a) {
        return (unsigned int)(a + (unsigned int)(((unsigned long)(b - a)
                                                  * frac) >> 8));
    }
    return (unsigned int)(a - (unsigned int)(((unsigned long)(a - b)
                                              * frac) >> 8));
}

/* Bilinear over a 16x16 map of bytes (wide 0) or u16 words (wide 1, the VE
   table since V98r2). The u16 worst case still fits 32 bits: 65535 x 256 x
   256 = 4 294 901 760. */
static unsigned int cal_cell(unsigned int map_off, unsigned char wide,
                             unsigned int i)
{
    return wide ? hc_cal_u16((unsigned int)(map_off + 2u * i))
                : (unsigned int)hc_cal_u8((unsigned int)(map_off + i));
}

static unsigned int cal_map(unsigned int map_off, unsigned char wide,
                            unsigned int rpm_ax_off, unsigned int load_ax_off,
                            unsigned int rpm, unsigned int load)
{
    unsigned int rf, lf;
    unsigned char ri = cal_bracket(rpm_ax_off, CAL_AXIS_N, rpm, &rf);
    unsigned char li = cal_bracket(load_ax_off, CAL_AXIS_N, load, &lf);
    unsigned char ri2 = (unsigned char)(ri + 1 < CAL_AXIS_N ? ri + 1 : ri);
    unsigned char li2 = (unsigned char)(li + 1 < CAL_AXIS_N ? li + 1 : li);
    unsigned long c00, c01, c10, c11, top, bot;

    /* THE CELL IS [load][rpm] - a ROW is one load, a COLUMN one rpm.
       That is TunerStudio's order for `[16x16]` with xBins = rpm, yBins =
       load (index = y * 16 + x; rusEFI veTable[LOAD][RPM]). Until V97 this
       read [rpm][load], so every 16x16 table - VE, ignition, AFR, pedal,
       boost - appeared TRANSPOSED in TunerStudio: the row labelled 100 %
       throttle held the 6800 rpm row. The page layout id carries the order
       (generate_config.layout_id), so an older record is refused, not
       reinterpreted; tools/me711_migrate_calibration.py transposes it. */
    c00 = cal_cell(map_off, wide, (unsigned int)(li * CAL_AXIS_N + ri));
    c01 = cal_cell(map_off, wide, (unsigned int)(li2 * CAL_AXIS_N + ri));
    c10 = cal_cell(map_off, wide, (unsigned int)(li * CAL_AXIS_N + ri2));
    c11 = cal_cell(map_off, wide, (unsigned int)(li2 * CAL_AXIS_N + ri2));

    top = c00 * (256uL - lf) + c01 * lf;
    bot = c10 * (256uL - lf) + c11 * lf;
    return (unsigned int)((top * (256uL - rf) + bot * rf) >> 16);
}

unsigned char hc_cal_map(unsigned int map_off, unsigned int rpm_ax_off,
                         unsigned int load_ax_off,
                         unsigned int rpm, unsigned int load)
{
    return (unsigned char)cal_map(map_off, 0u, rpm_ax_off, load_ax_off,
                                  rpm, load);
}

unsigned int hc_cal_map16(unsigned int map_off, unsigned int rpm_ax_off,
                          unsigned int load_ax_off,
                          unsigned int rpm, unsigned int load)
{
    return cal_map(map_off, 1u, rpm_ax_off, load_ax_off, rpm, load);
}

/* ======================================== the reset log ==================
 *
 * Lives past the calibration page and past the SRAM probe window, in memory
 * that a reset does not clear. See hcconfig.h for why it exists.
 */
/* Was 4096, which is 0x1000, which is EXACTLY where hcmain.c puts the
   telemetry block. The reset log - whose entire purpose is to survive and be
   believed - was being overwritten by the output channels hundreds of times a
   second, so bootCount and bootStage were whatever telemetry happened to be
   sitting there. Two files each picked an offset and neither could see the
   other. Every region of this SRAM is now declared in ONE place. */
#define RSTLOG   TGT_RAM_RSTLOG

static unsigned int rst_u16(unsigned int off)
{
    return (unsigned int)(((unsigned int)RAM[RSTLOG + off] << 8)
                          | RAM[RSTLOG + off + 1u]);
}

static void rst_set_u16(unsigned int off, unsigned int v)
{
    RAM[RSTLOG + off] = (unsigned char)(v >> 8);
    RAM[RSTLOG + off + 1u] = (unsigned char)(v & 0xFF);
}

unsigned int hc_rst_get(unsigned int off)
{
    return rst_u16(off);
}

void hc_rst_stage(unsigned int stage)
{
    /* No hc_ram_bad guard: the very first stage is recorded BEFORE the SRAM
       has been probed, and that is the stage that matters most - it is the one
       a boot that dies early never gets past. Writing to an SRAM that is not
       there simply does not stick, which is the same outcome as not writing. */

    if (stage == RST_ST_ENTRY) {
        unsigned long magic = ((unsigned long)rst_u16(0) << 16) | rst_u16(2u);
        unsigned int off;

        if (magic != RST_MAGIC_VAL) {
            /* First ever boot on this ECU, or the battery was disconnected. */
            rst_set_u16(0u, (unsigned int)(RST_MAGIC_VAL >> 16));
            rst_set_u16(2u, (unsigned int)(RST_MAGIC_VAL & 0xFFFFuL));
            for (off = RST_BOOTS; off <= RST_LAST; off += 2u) {
                rst_set_u16(off, 0u);
            }
            rst_set_u16(RST_LAYOUT, RST_LAYOUT_CUR);
        } else if (rst_u16(RST_LAYOUT) != RST_LAYOUT_CUR) {
            /* Upgrade the original four-word log in place. Preserve the one
               useful post-mortem it already had, and never print unwritten
               SRAM as RESETDIAG_V1 progress. */
            unsigned int legacy_stage = rst_u16(RST_STAGE);
            unsigned int legacy_trap = rst_u16(RST_TRAP);

            for (off = RST_PREV_STAGE; off <= RST_LAST; off += 2u) {
                rst_set_u16(off, 0u);
            }
            rst_set_u16(RST_PREV_STAGE, legacy_stage);
            rst_set_u16(RST_PREV_TRAP, legacy_trap);
            rst_set_u16(RST_LAYOUT, RST_LAYOUT_CUR);
        } else {
            /* Freeze the last run before ENTRY starts overwriting it. */
            rst_set_u16(RST_PREV_STAGE, rst_u16(RST_STAGE));
            rst_set_u16(RST_PREV_MS, rst_u16(RST_MS));
            rst_set_u16(RST_PREV_LOOP, rst_u16(RST_LOOP));
            rst_set_u16(RST_PREV_FIRSTVEC, rst_u16(RST_FIRSTVEC));
            rst_set_u16(RST_PREV_LASTVEC, rst_u16(RST_LASTVEC));
            rst_set_u16(RST_PREV_TRAP, rst_u16(RST_TRAP));
            rst_set_u16(RST_PREV_TGT0, rst_u16(RST_TGT0));
            rst_set_u16(RST_PREV_TGT1, rst_u16(RST_TGT1));
            rst_set_u16(RST_PREV_TGT2, rst_u16(RST_TGT2));
            rst_set_u16(RST_PREV_WDT_COUNT, rst_u16(RST_WDT_COUNT));
            rst_set_u16(RST_PREV_MARKER, rst_u16(RST_MARKER));
            rst_set_u16(RST_PREV_TGT3, rst_u16(RST_TGT3));
            rst_set_u16(RST_PREV_TGT4, rst_u16(RST_TGT4));
            rst_set_u16(RST_PREV_TRAP_MS, rst_u16(RST_TRAP_MS));
            rst_set_u16(RST_PREV_COND, rst_u16(RST_COND));
        }
        rst_set_u16(RST_BOOTS, (unsigned int)(rst_u16(RST_BOOTS) + 1u));
        rst_set_u16(RST_RESET_RAW, 0xFFFFu);
        rst_set_u16(RST_MS, 0u);
        rst_set_u16(RST_LOOP, 0u);
        rst_set_u16(RST_FIRSTVEC, 0u);
        rst_set_u16(RST_LASTVEC, 0u);
        rst_set_u16(RST_TRAP, 0u);
        rst_set_u16(RST_TGT0, 0u);
        rst_set_u16(RST_TGT1, 0u);
        rst_set_u16(RST_TGT2, 0u);
        rst_set_u16(RST_WDT_COUNT, 0u);
        rst_set_u16(RST_MARKER, 0u);
        rst_set_u16(RST_TGT3, 0u);
        rst_set_u16(RST_TGT4, 0u);
        rst_set_u16(RST_TRAP_MS, 0u);
        rst_set_u16(RST_COND, 0u);
    }

    rst_set_u16(RST_STAGE, stage);
    if (stage > rst_u16(RST_MAXSTAGE)) {
        rst_set_u16(RST_MAXSTAGE, stage);
    }
}

void hc_rst_reset_raw(unsigned int raw)
{
    rst_set_u16(RST_RESET_RAW, raw);
}

/* The five target words are written through a table so the log's LAYOUT stays
   here - where the offsets are declared - while their MEANING stays with the
   board that chose it. */
static const unsigned int rst_tgt_off[RST_TGT_WORDS] = {
    RST_TGT0, RST_TGT1, RST_TGT2, RST_TGT3, RST_TGT4
};

void hc_rst_progress(unsigned int ms, unsigned int loops,
                     unsigned int firstvec, unsigned int lastvec,
                     unsigned int wdt_count, unsigned int *tgt)
{
    unsigned char i;

    rst_set_u16(RST_MS, ms);
    rst_set_u16(RST_LOOP, loops);
    rst_set_u16(RST_FIRSTVEC, firstvec);
    rst_set_u16(RST_LASTVEC, lastvec);
    rst_set_u16(RST_WDT_COUNT, wdt_count);
    if (tgt != 0) {
        for (i = 0; i < RST_TGT_WORDS; i++) {
            rst_set_u16(rst_tgt_off[i], tgt[i]);
        }
    }
}

void hc_rst_marker(unsigned int marker)
{
    rst_set_u16(RST_MARKER, marker);
}

void hc_rst_vector(unsigned int vector)
{
    rst_set_u16(RST_TRAP, vector);
}

/* Timestamped, and called from INSIDE the trap handler on purpose. The 10 ms
   progress raster never gets another turn once a reset is on its way: the
   second Bosch hardware run captured TR=0002 this way and lost FV/LV to
   exactly that. */
void hc_rst_vector_at(unsigned int vector, unsigned int ms)
{
    rst_set_u16(RST_TRAP, vector);
    rst_set_u16(RST_TRAP_MS, ms);
}

void hc_rst_cond(unsigned int cond)
{
    rst_set_u16(RST_COND, cond);
}
