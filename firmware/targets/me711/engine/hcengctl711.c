/*
 * hcengctl711.c - the V98 engine-control layer (read hcengctl711.h).
 *
 * FAR (FCODE), MOD167 MEDIUM, DEFINE(HC_FAR_BRIDGE). Page reads are the
 * call-free hcfarinline.h macros; hc_cal_map / hc_cal_curve16 / the HAL go
 * through hcfar_me711.c thunks. Arithmetic is 16x16 -> 32 products and 32/16
 * divisions whose quotient is bounded to 16 bits first (DIV32U), so Keil
 * emits inline MUL/DIVLU and never a ?C_ helper (the project rules, checked by
 * tools/me711_engctl_proof.py on the listing).
 *
 * Everything here runs in the MAIN LOOP (eng_service and its neighbours),
 * never on a tooth. What the tooth path needs is handed over in near
 * variables the scheduler owns (dry_skip_ratio, dry_rev_limit, ...), read
 * there with one load each.
 */
#include "hcfarbridge.h"
#include <reg167.h>
#include "hctarget.h"
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hcfarinline.h"
#include "hctrigger.h"
#include "hcengine.h"
#include "hchal.h"
#include "hc_dbw.h"
#include "hcsafety.h"
#include "hcsched_dry.h"
#include "hctrans711.h"
#include "hcio711.h"
#include "hcigncorr711.h"
#include "hcboost711.h"
#include "hcidle711.h"
#include "hclimp711.h"
#include "hcknock711.h"
#include "hcengctl711.h"
#include "hc_validation.h"
#include "hcdeadline711.h"
#include "hcevlog711.h"

#define T1_PER_MS  ((unsigned int)(TGT_TICKS_PER_MS_X10 / 10uL))   /* 1250 */
/* 32/16 unsigned division, quotient bounded to 16 bits by every caller. */
#define DIV32U(n, d)  ((unsigned int)((unsigned long)(n) / (unsigned int)(d)))
#define E HC_EC

typedef char hc_ec_fits[(sizeof(hc_ec_t) <= TGT_RAM_ENGCTL_LIMIT) ? 1 : -1];

#define OCH1B ((unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_OCH))
#define OCH2B ((unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_OCH2))

#define PRIME_MAGIC  0x5052u            /* "PR": the key-cycle counter is ours */
#define VE_TUNE_MS   20000u             /* rusEFI isTuningVeNow(): 20 s        */

/* ============================================================ firing order
 * rusEFI firing_order.cpp's tables, by firing_order_e id: id, length, then
 * the 1-based cylinder numbers in firing order. The ids are the page's
 * firingOrder values (hanicore_config_def.ENUM_FIRING_ORDER), and
 * tools/me711_engctl_proof.py checks this table against both that enum and
 * rusEFI's own source. */
static const unsigned char fo_tab[] = {
    8,  2, 1, 2,
    10, 3, 1, 2, 3,
    24, 3, 1, 3, 2,
    1,  4, 1, 3, 4, 2,
    2,  4, 1, 2, 4, 3,
    3,  4, 1, 3, 2, 4,
    17, 4, 1, 4, 3, 2,
    35, 4, 1, 2, 3, 4,
    6,  5, 1, 2, 4, 5, 3,
    4,  6, 1, 5, 3, 6, 2, 4,
    30, 6, 1, 6, 5, 4, 3, 2,
    31, 6, 1, 4, 5, 2, 3, 6,
    7,  6, 1, 4, 2, 5, 3, 6,
    9,  6, 1, 2, 3, 4, 5, 6,
    13, 6, 1, 6, 3, 2, 5, 4,
    27, 6, 1, 4, 3, 6, 2, 5,
    29, 6, 1, 6, 2, 4, 3, 5,
    36, 6, 1, 6, 2, 5, 3, 4,
    5,  8, 1, 8, 4, 3, 6, 5, 7, 2,
    11, 8, 1, 8, 7, 2, 6, 5, 4, 3,
    12, 8, 1, 5, 4, 2, 6, 3, 7, 8,
    19, 8, 1, 2, 7, 8, 4, 5, 6, 3,
    20, 8, 1, 3, 7, 2, 6, 5, 4, 8,
    25, 8, 1, 2, 3, 4, 5, 6, 7, 8,
    26, 8, 1, 5, 4, 8, 6, 3, 7, 2,
    32, 8, 1, 5, 4, 8, 3, 7, 2, 6,
    28, 8, 1, 8, 7, 3, 6, 5, 4, 2,
    34, 8, 1, 8, 6, 2, 7, 3, 4, 5,
    14, 10, 1, 10, 9, 4, 3, 6, 5, 8, 7, 2,
    33, 10, 1, 6, 5, 10, 2, 7, 3, 8, 4, 9,
    15, 12, 1, 7, 5, 11, 3, 9, 6, 12, 2, 8, 4, 10,
    16, 12, 1, 7, 4, 10, 2, 8, 6, 12, 3, 9, 5, 11,
    18, 12, 1, 12, 5, 8, 3, 10, 6, 7, 2, 11, 4, 9,
    23, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12,
    0xFFu
};

static unsigned int fo_find(unsigned char order)
{
    unsigned int i = 0u;

    while (fo_tab[i] != 0xFFu) {
        if (fo_tab[i] == order) {
            return i;
        }
        i = (unsigned int)(i + 2u + fo_tab[i + 1u]);
    }
    return 0xFFFFu;
}

unsigned char far hc_fo_length(unsigned char order)
{
    unsigned int i = fo_find(order);

    return (i == 0xFFFFu) ? 0u : fo_tab[i + 1u];
}

unsigned char far hc_fo_position(unsigned char order, unsigned char cyl,
                                 unsigned char ncyl)
{
    unsigned int i = fo_find(order);
    unsigned char n, k;

    if (i == 0xFFFFu || fo_tab[i + 1u] != ncyl) {
        return 0xFFu;
    }
    n = fo_tab[i + 1u];
    for (k = 0u; k < n; k++) {
        if (fo_tab[i + 2u + k] == (unsigned char)(cyl + 1u)) {
            return k;
        }
    }
    return 0xFFu;
}

/* ============================================================== helpers */
static unsigned int sat_add(unsigned int a, unsigned int b)
{
    unsigned int s = (unsigned int)(a + b);
    return (s < a) ? 0xFFFFu : s;
}

static void och(unsigned int at, unsigned int v)
{
    unsigned char huge *p = (at >= 1024u) ? (OCH2B + (at - 1024u))
                                          : (OCH1B + at);
    p[0] = (unsigned char)(v >> 8);
    p[1] = (unsigned char)(v & 0xFFu);
}

/* Index and fraction (0..256) of x on an 8-point u16 axis. */
static unsigned char ax8(unsigned int ax, unsigned int x, unsigned int *frac)
{
    unsigned char i;
    unsigned int a0 = hc_cal_u16(ax), a1;

    *frac = 0u;
    if (x <= a0) {
        return 0u;
    }
    for (i = 1u; i < 8u; i++) {
        a1 = hc_cal_u16((unsigned int)(ax + 2u * i));
        if (x < a1) {
            if (a1 > a0) {
                *frac = DIV32U((unsigned long)(unsigned int)(x - a0) * 256u,
                               (unsigned int)(a1 - a0));
            }
            return (unsigned char)(i - 1u);
        }
        a0 = a1;
    }
    *frac = 256u;
    return 6u;
}

/* Bilinear 8x8 table [y][x]; u8 cells (wide = 0) or u16 cells (wide = 1).
   Returns the value for u16 cells, the value x 16 for u8 cells. */
static unsigned int lut8(unsigned int tab, unsigned int xax, unsigned int yax,
                         unsigned int x, unsigned int y, unsigned char wide)
{
    unsigned int fx, fy, c00, c01, c10, c11, top, bot;
    unsigned char ix = ax8(xax, x, &fx);
    unsigned char iy = ax8(yax, y, &fy);
    unsigned int r0 = (unsigned int)(iy * 8u), r1 = (unsigned int)(r0 + 8u);

    if (wide) {
        c00 = hc_cal_u16((unsigned int)(tab + 2u * (r0 + ix)));
        c01 = hc_cal_u16((unsigned int)(tab + 2u * (r0 + ix + 1u)));
        c10 = hc_cal_u16((unsigned int)(tab + 2u * (r1 + ix)));
        c11 = hc_cal_u16((unsigned int)(tab + 2u * (r1 + ix + 1u)));
        top = DIV32U((unsigned long)c00 * (unsigned int)(256u - fx)
                     + (unsigned long)c01 * fx, 256u);
        bot = DIV32U((unsigned long)c10 * (unsigned int)(256u - fx)
                     + (unsigned long)c11 * fx, 256u);
        return DIV32U((unsigned long)top * (unsigned int)(256u - fy)
                      + (unsigned long)bot * fy, 256u);
    }
    c00 = hc_cal_u8((unsigned int)(tab + r0 + ix));
    c01 = hc_cal_u8((unsigned int)(tab + r0 + ix + 1u));
    c10 = hc_cal_u8((unsigned int)(tab + r1 + ix));
    c11 = hc_cal_u8((unsigned int)(tab + r1 + ix + 1u));
    top = (unsigned int)(c00 * (unsigned int)(256u - fx) + c01 * fx);
    bot = (unsigned int)(c10 * (unsigned int)(256u - fx) + c11 * fx);
    return DIV32U((unsigned long)top * (unsigned int)(256u - fy)
                  + (unsigned long)bot * fy, 4096u);
}

/* The driver's demand: the pedal on an electronic throttle, the throttle
   otherwise (rusEFI DriverThrottleIntent). 0xFFFF = not valid. */
static unsigned int intent_x10(void)
{
    unsigned int err = eng_sensor_err;

    if (hc_cal_u8(CAL_DBW_ENABLE) != 0u) {
        return (err & (ENG_ERR_PEDAL1 | ENG_ERR_PED_DIFF)) ? 0xFFFFu
                                                           : eng_pedal_x10;
    }
    return (err & ENG_ERR_TPS1) ? 0xFFFFu : eng_tps_x10;
}

/* Biased temperature (10*C + 10000) compare against a page word. */
static unsigned char clt_ok(void)
{
    return (unsigned char)((eng_sensor_err & ENG_ERR_CLT) == 0u);
}

/* A motorsport switch: 1 active, 0 inactive or not readable. */
static unsigned char sw(unsigned int pin_off, unsigned char mask)
{
    unsigned char lvl = hc_hal_din(hc_cal_u8(pin_off));

    if (lvl > 1u) {
        return 0u;
    }
    if (hc_cal_u8(CFG_U_MS_SWITCH_INV) & mask) {
        return lvl;                       /* active high                  */
    }
    return (unsigned char)(lvl == 0u);    /* active when grounded         */
}

/* A function's switch changes state only after the new level has held
   SW_DEBOUNCE_MS: a mechanical switch bounces, and a bouncing flat-shift
   switch restarted the cut on every bounce. i = the function's bit
   in sw_last (0 launch, 1 flat shift, 2 anti-lag, 3 pit). */
#define SW_DEBOUNCE_MS  10u

static unsigned char sw_deb(unsigned char i, unsigned char raw)
{
    unsigned char m = (unsigned char)(1u << i);
    unsigned char was = (unsigned char)((E.sw_last & m) != 0u);

    if (raw == was) {
        E.sw_db[i] = 0u;
        return was;
    }
    if ((unsigned int)(E.sw_db[i] + E.dt_ms) >= SW_DEBOUNCE_MS) {
        E.sw_db[i] = 0u;
        return raw;
    }
    E.sw_db[i] = (unsigned char)(E.sw_db[i] + E.dt_ms);
    return was;
}

/* ======================================================= endpoint grab
 * hcengine.c's eng_calib_grab(), moved here unchanged in behaviour (V98
 * NCODE relief): one end of one pair, both tracks, RAM only, refused
 * unless the engine is demonstrably stopped. */
#define ADC_PLAUS_LO   10u
#define ADC_PLAUS_HI   1013u

/* Historical minimum-span diagnostic/test constant. Capture no longer
   compares against a previous endpoint.
   How far apart the two ends of a track must end up. rusEFI's autocal uses
   100 counts of a 10-bit converter for exactly this test and calls a smaller
   travel "check your wiring". A real throttle or pedal moves several hundred.
   COMPILED IN, not a page value: a check a tuner can widen until it passes is
   not a check. */
#define GRAB_MIN_SPAN   100u

static unsigned int grab_pair(unsigned char ch1, unsigned char ch2,
                              unsigned int slot1, unsigned int slot2)
{
    unsigned int r1;
    unsigned int r2;

    if (!hc_hal_ain_ok(ch1) || !hc_hal_ain_ok(ch2)) {
        return ENG_GRAB_NOCHANNEL;
    }
    r1 = hc_hal_ain(ch1);
    r2 = hc_hal_ain(ch2);
    if (r1 < ADC_PLAUS_LO || r1 > ADC_PLAUS_HI
        || r2 < ADC_PLAUS_LO || r2 > ADC_PLAUS_HI) {
        return ENG_GRAB_RAIL;
    }

    /* THE SPAN IS CHECKED BEFORE ANYTHING IS WRITTEN, against whatever the
       OTHER end already holds. A zero there means it has not been grabbed yet
       on this page, so there is nothing to compare and the first grab of a
       pair is always allowed. */
    /* Capture must be independent of old endpoints. Runtime/page validation
       qualifies the completed span; the command handler requires motor OFF. */
    hc_cal_set_u16(slot1, r1);
    hc_cal_set_u16(slot2, r2);
    return ENG_GRAB_PASS;
}

unsigned int eng_calib_grab(unsigned char what)
{
    unsigned int v;

    /* THE ENGINE MUST BE DEMONSTRABLY STOPPED. Not "rpm reads zero" - the
       decoder must also be reporting no crank signal at all, which is the
       same pair of facts hcbench.c requires before it drives a pin. A
       calibration captured while something is turning is a calibration of a
       moment. */
    if (trg_rpm != 0u || trg_state != TRG_NO_SIGNAL) {
        v = ENG_GRAB_RPM;
    } else {
        switch (what) {
        case ENG_GRAB_TPS_CLOSED:
            v = grab_pair(HC_AIN_TPS1, HC_AIN_TPS2,
                          CAL_TPS1_MIN, CAL_TPS2_MIN);
            break;
        case ENG_GRAB_TPS_OPEN:
            v = grab_pair(HC_AIN_TPS1, HC_AIN_TPS2,
                          CAL_TPS1_MAX, CAL_TPS2_MAX);
            break;
        case ENG_GRAB_APP_REST:
            v = grab_pair(HC_AIN_APP1, HC_AIN_APP2,
                          CAL_PEDAL1_MIN, CAL_PEDAL2_MIN);
            break;
        case ENG_GRAB_APP_FULL:
            v = grab_pair(HC_AIN_APP1, HC_AIN_APP2,
                          CAL_PEDAL1_MAX, CAL_PEDAL2_MAX);
            break;
        default:
            v = ENG_GRAB_WHAT;
            break;
        }
    }

    return v;
}

/* ================================================================== init */
void far hc_ec_init(void)
{
    E.t_last = T1;
    E.t_rem = 0u;
    E.ms = 0u;
    E.dt_ms = 0u;
    E.run_ms = 0u;
    E.flags = 0u;
    E.lag_ok = 0u;          /* the filling model starts from the throttle */
    E.lag_x16 = 0u;
    E.dfco = 0u;
    E.dfco_cond = 0u;
    E.dfco_cond_ms = 0u;
    E.since_dfco_ms = 0xFFFFu;
    E.since_cut_ms = 0xFFFFu;
    E.since_ae_ms = 0xFFFFu;
    E.stft_pm[0] = 0;
    E.stft_pm[1] = 0;
    E.stft_acc[0] = 0;
    E.stft_acc[1] = 0;
    E.stft_state = EC_STFT_OFF;
    E.stft_region = 0u;
    E.stft_bad_ms[0] = 0u;
    E.stft_bad_ms[1] = 0u;
    E.rev_limit = 0u;
    E.rev_hyst = 200u;
    E.skip = 0u;
    E.launch = 0u;
    E.flat = 0u;
    E.als = 0u;
    E.rot = 0u;
    E.pit = 0u;
    E.sw_last = 0u;
    E.sw_db[0] = 0u;
    E.sw_db[1] = 0u;
    E.sw_db[2] = 0u;
    E.sw_db[3] = 0u;
    E.sw_raw = 0u;
    E.sw_raw_ms = 0u;
    E.flat_ms = 0xFFFFu;
    E.als_ms = 0u;
    E.spark_last = 0;
    E.fuel_pm = 1000u;
    E.map_ctrl_x10 = 0u;
    E.lambda_x1000 = 1000u;
    E.ign_load = 0u;
    E.lam_load = 0u;
    E.ve_tune_ms = 0xFFFFu;
    E.prime_st = 0u;
    E.prime_ms = 0u;
    /* THE KEY-CYCLE COUNTER SURVIVES A POWER CYCLE (battery-backed SRAM),
       exactly as rusEFI keeps it in backup RAM: a prime only on the first
       key-on after the engine ran, so repeated key cycles of an engine that
       will not start do not flood it. */
    if (E.prime_magic != PRIME_MAGIC) {
        E.prime_magic = PRIME_MAGIC;
        E.prime_count = 0u;
    }
    dry_skip_ratio = 0u;
    dry_rev_limit = 0u;
    dry_rev_hyst = 200u;
}

/* ================================================================== DFCO
 * rusEFI dfco.cpp, plus Speeduino's "never during after-start": every
 * sensor the decision rests on must be VALID - a failed throttle reads 0 %
 * and used to satisfy "closed throttle" (bug B4). */
static void dfco_update(unsigned int rpm)
{
    unsigned int cut_rpm = hc_cal_u16(CAL_OVERRUN_RPM);
    unsigned int resume = hc_cal_u16(CAL_OVERRUN_RESUME);
    unsigned int intent = intent_x10();
    unsigned char allowed = 1u;
    unsigned char mapmax = hc_cal_u8(CFG_U_DFCO_MAP_MAX);

    if (cut_rpm == 0u || eng_cranking || intent == 0xFFFFu || !clt_ok()) {
        allowed = 0u;
    } else if (hc_cal_u8(CFG_U_PIN_MAP) != HC_PIN_NONE
               && (eng_sensor_err & ENG_ERR_MAP)) {
        allowed = 0u;                /* a MAP that is present but broken */
    } else if (intent >= hc_cal_u16(CAL_OVERRUN_TPS_X10)) {
        allowed = 0u;
    } else if (eng_clt_dc <= hc_cal_u16(CFG_U_DFCO_MIN_CLT)) {
        allowed = 0u;
    } else if (mapmax != 0u
               && (hc_cal_u8(CFG_U_FUEL_MODEL) == 0u
                   ? hc_cal_u8(CAL_LOAD_SOURCE) != CAL_LOAD_TPS
                   : hc_cal_u8(CFG_U_PRESSURE_ROLE) == 1u)
               && eng_map_kpa_x10 >= (unsigned int)(mapmax * 10u)) {
        /* only a MANIFOLD pressure says "coasting". Under alpha-N x
           inlet pressure the sensor is BEFORE the throttle (the AWT's 101)
           and reads ambient or boost on a closed throttle - the ceiling
           would forbid DFCO for ever. The legacy model knows that from its
           load source, the others from the declared sensor location. */
        allowed = 0u;
    } else if (hc_trans.as_pm != 0u) {
        allowed = 0u;                /* Speeduino: not during after-start */
    }
    if (allowed && rpm > cut_rpm) {
        E.dfco_cond = 1u;
    } else if (!allowed || rpm < resume) {
        E.dfco_cond = 0u;
    }
    E.dfco_cond_ms = E.dfco_cond ? sat_add(E.dfco_cond_ms, E.dt_ms) : 0u;
    E.dfco = (unsigned char)(E.dfco_cond
             && E.dfco_cond_ms >= (unsigned int)(hc_cal_u8(CFG_U_DFCO_DELAY)
                                                 * 100u));
    E.since_dfco_ms = E.dfco ? 0u : sat_add(E.since_dfco_ms, E.dt_ms);
    eng_fuelcut = (unsigned int)((eng_fuelcut & ~ENG_CUT_OVERRUN)
                                 | (E.dfco ? ENG_CUT_OVERRUN : 0u));
    if(E.dfco) hc_deadline_fuel_cut();
}

/* ============================================================ motorsport */
static unsigned char pct255(unsigned char pct)
{
    return (unsigned char)((pct >= 100u) ? 255u
                           : DIV32U((unsigned int)pct * 255u, 100u));
}

static void motorsport_update(unsigned int rpm)
{
    unsigned int ms = hc_cal_u16(CFG_U_MS_ENABLE);
    unsigned int intent = intent_x10();
    unsigned char now = 0u, skip = 0u;
    unsigned char running = (unsigned char)(trg_rpm != 0u && !eng_cranking);

    /* ---- launch control (rusEFI LaunchControlBase) ---- */
    E.launch = 0u;
    if ((ms & 0x0001u) && sw_deb(0u, sw(CFG_U_PIN_LAUNCH, 1u))) {
        unsigned int lrpm = hc_cal_u16(CFG_U_LAUNCH_RPM);
        unsigned int win = (unsigned int)(hc_cal_u8(CFG_U_LAUNCH_WINDOW) * 10u);
        now |= 1u;
        if (intent != 0xFFFFu && lrpm != 0u
            && intent > (unsigned int)(hc_cal_u8(CFG_U_LAUNCH_TPS) * 10u)) {
            if (rpm >= lrpm) {
                E.launch = 2u;                         /* launch           */
            } else if (rpm + win >= lrpm) {
                E.launch = 1u;                         /* pre-launch       */
            }
        }
        if (E.launch == 2u) {
            if (hc_cal_u8(CFG_U_LAUNCH_CUT_END) || hc_cal_u8(CFG_U_LAUNCH_CUT_START)) {
                skip = 255u;
            }
        } else if (E.launch == 1u && win != 0u) {
            unsigned char c0 = hc_cal_u8(CFG_U_LAUNCH_CUT_START);
            unsigned char c1 = hc_cal_u8(CFG_U_LAUNCH_CUT_END);
            unsigned int d = (unsigned int)(rpm + win - lrpm);    /* 0..win */
            unsigned char pc = (c1 >= c0)
                ? (unsigned char)(c0 + DIV32U((unsigned long)(unsigned int)(c1 - c0) * d, win))
                : (unsigned char)(c0 - DIV32U((unsigned long)(unsigned int)(c0 - c1) * d, win));
            skip = pct255(pc);
        }
    }

    /* ---- flat shift (rusEFI ShiftTorqueReductionController) ---- */
    E.flat = 0u;
    if ((ms & 0x0002u) && sw_deb(1u, sw(CFG_U_PIN_FLATSHIFT, 2u))) {
        now |= 2u;
        if (!(E.sw_last & 2u)) {
            E.flat_ms = 0u;                            /* the press starts */
        } else {
            E.flat_ms = sat_add(E.flat_ms, E.dt_ms);
        }
        if (running && rpm >= hc_cal_u16(CFG_U_FLATSHIFT_RPM)
            && intent != 0xFFFFu
            && intent > (unsigned int)(hc_cal_u8(CFG_U_FLATSHIFT_TPS) * 10u)
            && E.flat_ms < hc_cal_u16(CFG_U_FLATSHIFT_CUT_MS)) {
            E.flat = 1u;
            if (pct255(hc_cal_u8(CFG_U_FLATSHIFT_CUT_PCT)) > skip) {
                skip = pct255(hc_cal_u8(CFG_U_FLATSHIFT_CUT_PCT));
            }
        }
    }

    /* ---- anti-lag (rusEFI AntilagSystemBase) ---- */
    E.als = 0u;
    if ((ms & 0x0004u) && sw_deb(2u, sw(CFG_U_PIN_ANTILAG, 4u))) {
        unsigned char mx = hc_cal_u8(CFG_U_ALS_MAX_S);
        now |= 4u;
        if (!(E.sw_last & 4u) || rpm >= hc_cal_u16(CFG_U_ALS_RPM_MAX)) {
            E.als_ms = 0u;
        } else {
            E.als_ms = sat_add(E.als_ms, E.dt_ms);
        }
        if (running && clt_ok()
            && rpm > hc_cal_u16(CFG_U_ALS_RPM_MIN)
            && rpm < hc_cal_u16(CFG_U_ALS_RPM_MAX)
            && eng_clt_dc > hc_cal_u16(CFG_U_ALS_CLT_MIN)
            && eng_clt_dc < hc_cal_u16(CFG_U_ALS_CLT_MAX)
            && intent != 0xFFFFu
            && intent < (unsigned int)(hc_cal_u8(CFG_U_ALS_TPS_MAX) * 10u)
            && (mx == 0u || E.als_ms < (unsigned int)(mx * 1000u))) {
            E.als = 1u;
            if (pct255(hc_cal_u8(CFG_U_ALS_CUT_PCT)) > skip) {
                skip = pct255(hc_cal_u8(CFG_U_ALS_CUT_PCT));
            }
        }
    }

    /* ---- rotational idle (rusEFI rotational_idle.cpp, a skip ratio) ---- */
    E.rot = 0u;
    if ((ms & 0x0400u) && running && intent != 0xFFFFu
        && rpm < hc_cal_u16(CFG_U_ROTIDLE_RPM)
        && intent < (unsigned int)(hc_cal_u8(CFG_U_ROTIDLE_TPS) * 10u)) {
        E.rot = 1u;
        if (pct255(hc_cal_u8(CFG_U_ROTIDLE_CUT)) > skip) {
            skip = pct255(hc_cal_u8(CFG_U_ROTIDLE_CUT));
        }
    }

    /* ---- pit limiter: a lower rev limit while the switch is held ---- */
    E.pit = (unsigned char)((ms & 0x0008u)
                            && sw_deb(3u, sw(CFG_U_PIN_PITLIM, 8u)));
    if (E.pit) {
        now |= 8u;
    }
    E.sw_last = now;
    E.skip = skip;
}

/* =============================================================== rev limit
 * rusEFI LimpManager::updateRevLimit: hard limit with hysteresis (the hard
 * cut itself is in hcsched_dry.c, once a millisecond, so a stalled main loop
 * cannot let the engine through it); the soft limit ramps a retard and a
 * fuel adder across the hysteresis window below it. */
static void revlimit_update(void)
{
    unsigned int lim = cfg_u16(CFG_REV_LIMIT);
    unsigned char h = hc_cal_u8(CFG_U_REVLIM_HYST);

    if (E.pit) {
        unsigned int p = hc_cal_u16(CFG_U_PITLIM_RPM);
        if (p != 0u && (lim == 0u || p < lim)) {
            lim = p;
        }
    }
    E.rev_limit = lim;
    E.rev_hyst = (h == 0u) ? 200u : (unsigned int)(h * 10u);
    if (E.rev_hyst >= lim) {
        E.rev_hyst = (unsigned int)(lim >> 1);
    }
    dry_rev_limit = E.rev_limit;
    dry_rev_hyst = E.rev_hyst;
    dry_skip_ratio = E.skip;
}

/* Soft-limit fraction 0..256 of the way from (limit - hyst) to the limit. */
static unsigned int soft_frac(void)
{
    unsigned int lo;

    if (E.rev_limit == 0u || E.rev_hyst == 0u || eng_cranking) {
        return 0u;
    }
    lo = (unsigned int)(E.rev_limit - E.rev_hyst);
    if (trg_rpm <= lo) {
        return 0u;
    }
    if (trg_rpm >= E.rev_limit) {
        return 256u;
    }
    return DIV32U((unsigned long)(unsigned int)(trg_rpm - lo) * 256u,
                  E.rev_hyst);
}

/* ====================================================== closed-loop fuel
 * rusEFI ShortTermFuelTrim + ClosedLoopFuelCellImpl: four regions, each an
 * integrator with its own limits and time constant; learning only from a
 * valid lambda within range, not after DFCO / AE / a cut, not while the VE
 * table is being written. A bank whose sensor is not valid gets NO trim -
 * its correction is dropped, not held (the brief: never trim from a sensor
 * that is not READY). The adjustment is kept in 1/16 per mille. */
static unsigned char stft_region(unsigned int rpm, unsigned int load_x10)
{
    unsigned int l = (unsigned int)(load_x10 / 10u);

    if (rpm < hc_cal_u16(CFG_U_STFT_IDLE_RPM)) {
        return 0u;                                   /* idle    */
    }
    if (l < hc_cal_u8(CFG_U_STFT_OVR_LOAD)) {
        return 1u;                                   /* overrun */
    }
    if (l > hc_cal_u8(CFG_U_STFT_PWR_LOAD)) {
        return 2u;                                   /* power   */
    }
    return 3u;                                       /* cruise  */
}

static void stft_bank(unsigned char b, unsigned int lam, unsigned char learn,
                      unsigned char reg)
{
    int lim_hi = (int)(hc_cal_u8((unsigned int)(CFG_U_STFT_ADD + reg)) * 160u);
    int lim_lo = -(int)(hc_cal_u8((unsigned int)(CFG_U_STFT_REMOVE + reg)) * 160u);
    unsigned int tau = (unsigned int)(hc_cal_u8((unsigned int)(CFG_U_STFT_TAU + reg))
                                      * 100u);
    int err, a;
    unsigned int mag, step;

    if (lam == 0u) {
        E.stft_acc[b] = 0;               /* never trim from a dead sensor */
        return;
    }
    if (!learn) {
        return;
    }
    err = (int)lam - (int)E.lambda_x1000;          /* + = lean: add fuel */
    mag = (unsigned int)((err < 0) ? -err : err);
    if (mag < hc_cal_u8(CFG_U_STFT_DEADBAND)) {
        return;
    }
    if (mag > 500u) {
        mag = 500u;
    }
    if (tau < 100u) {
        tau = 100u;
    }
    /* d(adj) = err * dt / tau, in 1/16 per mille: |err| <= 500, dt <= 200,
       x16 -> 1.6e6; / tau >= 100 -> <= 16000: fits. */
    step = DIV32U((unsigned long)(unsigned int)(mag * 16u) * E.dt_ms, tau);
    a = E.stft_acc[b];
    a = (err < 0) ? (int)(a - (int)step) : (int)(a + (int)step);
    if (a > lim_hi) a = lim_hi;
    if (a < lim_lo) a = lim_lo;
    E.stft_acc[b] = a;
}

static void stft_update(unsigned int rpm, unsigned int load_x10)
{
    unsigned char st;
    unsigned char b;
    unsigned int lam[2];
    unsigned char learn = 0u;
    unsigned int lmin = (unsigned int)(hc_cal_u8(CFG_U_STFT_LAM_MIN) * 10u);
    unsigned int lmax = (unsigned int)(hc_cal_u8(CFG_U_STFT_LAM_MAX) * 10u);

    lam[0] = (hc_cal_u8(CFG_U_LAM1_SRC) != 0u) ? hc_io_lambda(0u) : 0u;
    lam[1] = (hc_cal_u8(CFG_U_LAM2_SRC) != 0u) ? hc_io_lambda(1u) : 0u;

    if (hc_cal_u8(CFG_U_STFT_ENABLE) == 0u) {
        st = EC_STFT_OFF;
    } else if (trg_rpm == 0u || eng_cranking) {
        st = EC_STFT_RPM;
    } else if (E.run_ms < (unsigned int)(hc_cal_u8(CFG_U_STFT_DELAY) * 1000u)) {
        st = EC_STFT_DELAY;
    } else if (!clt_ok() || eng_clt_dc < hc_cal_u16(CFG_U_STFT_MIN_CLT)) {
        st = EC_STFT_CLT;
    } else if (E.ve_tune_ms < VE_TUNE_MS) {
        st = EC_STFT_VETUNE;
    } else if (E.since_dfco_ms < (unsigned int)(hc_cal_u8(CFG_U_STFT_AFTER_DFCO) * 100u)) {
        st = EC_STFT_DFCO;
    } else if (E.since_ae_ms < (unsigned int)(hc_cal_u8(CFG_U_STFT_AFTER_AE) * 100u)) {
        st = EC_STFT_AE;
    } else if (E.since_cut_ms < 2000u) {
        st = EC_STFT_CUT;
    } else {
        st = EC_STFT_ACTIVE;
        learn = 1u;
    }
    if (st == EC_STFT_OFF || st == EC_STFT_RPM || st == EC_STFT_DELAY
        || st == EC_STFT_CLT || st == EC_STFT_VETUNE) {
        /* rusEFI getCorrectionState(): no correction is APPLIED. */
        E.stft_pm[0] = 0;
        E.stft_pm[1] = 0;
        if (st == EC_STFT_OFF) {
            E.stft_acc[0] = 0;
            E.stft_acc[1] = 0;
        }
        E.stft_state = st;
        return;
    }
    E.stft_region = stft_region(rpm, load_x10);
    for (b = 0u; b < 2u; b++) {
        unsigned char inr = (unsigned char)(lam[b] != 0u && lam[b] >= lmin
                                            && lam[b] <= lmax);
        /* Lifecycle-qualified lambda remains valid at steady conditions. */
        unsigned char ok = inr;
        if (lam[b] != 0u && !inr && st == EC_STFT_ACTIVE) {
            st = EC_STFT_LAMBDA;
        }
        stft_bank(b, lam[b], (unsigned char)(learn && ok), E.stft_region);
        E.stft_pm[b] = (int)(E.stft_acc[b] / 16);
    }
    if (lam[0] == 0u && lam[1] == 0u) {
        st = EC_STFT_LAMBDA;
    }
    E.stft_state = st;
}

/* The trim actually applied, per mille: one bank, or the mean of two.
   A bank counts only while its sensor is a measurement - a configured but
   dead bank 2 must not halve bank 1's trim. */
static int stft_applied(void)
{
    unsigned char on1 = (unsigned char)(hc_cal_u8(CFG_U_LAM1_SRC) != 0u
                                        && hc_io_lambda(0u) != 0u);
    unsigned char on2 = (unsigned char)(hc_cal_u8(CFG_U_LAM2_SRC) != 0u
                                        && hc_io_lambda(1u) != 0u);

    /* ponytail: both banks trim the whole engine by their mean; a per-bank
       trim needs the cylinder mask in the scheduler's pulse path. */
    if (on1 && on2) {
        return (int)((E.stft_pm[0] + E.stft_pm[1]) / 2);
    }
    return on1 ? E.stft_pm[0] : (on2 ? E.stft_pm[1] : 0);
}

/* ============================================================ table loads
 * rusEFI getLoadOverride(): a failed sensor reads 200 kPa / 100 % - the
 * rich, retarded corner. */
static unsigned int load_for(unsigned char mode, unsigned int fuel_load)
{
    switch (mode) {
    case 1u:
        return (eng_sensor_err & ENG_ERR_MAP) ? 2000u : eng_map_kpa_x10;
    case 2u:
        return (eng_sensor_err & ENG_ERR_TPS1) ? 1000u : eng_tps_x10;
    case 3u:
        return eng_rl_x10;
    default:
        return fuel_load;
    }
}

unsigned int far hc_ec_ign_load(unsigned int fuel_load)
{
    E.ign_load = load_for(hc_cal_u8(CFG_U_IGN_LOAD_MODE), fuel_load);
    return E.ign_load;
}

unsigned int far hc_ec_target_lambda(unsigned int rpm, unsigned int fuel_load)
{
    unsigned char cell;

    E.lam_load = load_for(hc_cal_u8(CFG_U_LAM_LOAD_MODE), fuel_load);
    cell = hc_cal_map(CAL_AFR_MAP, CFG_U_LAM_RPM_AX, CFG_U_LAM_LOAD_AX, rpm,
                      E.lam_load);
    eng_afr_x10 = cell;          /* lambda x 147 (= AFR x 10 on gasoline) */
    /* lambda x 1000 = cell / 147; a 0 cell would be lambda 0 - refuse it */
    E.lambda_x1000 = (cell == 0u) ? 1000u
                   : DIV32U((unsigned long)(unsigned int)cell * 1000u, 147u);
    return E.lambda_x1000;
}

/* ================================== THE INTAKE-MANIFOLD FILLING MODEL ===
 *
 * FR "Audi R4-5V T 132kW ME7.1" BGSRM 17.10 (pp. 292-294): the stock ME7
 * never takes the throttle angle as the cylinder load. Air through the
 * throttle fills the intake manifold, an integrator per segment with
 *     KISRM = zkorr / (z * Vs/VH)        (z = 4, Vs/VH = 2.2, zkorr 0.90
 *                                         -> 0.1023: the FR's own example)
 * so a throttle step reaches the cylinders over ~(Vs/VH)/zkorr x 2 = 4.9
 * crank revolutions (0.23 s at 1300 rpm). HaniCore's alpha-N used the
 * throttle directly: a quick press at 1300 rpm moved the fuel AND the
 * ignition load from 5 % to 50 % in one sample - the ignition table's
 * full-load cells (3-7.5 deg) fired into a manifold that had not filled
 * (car 2026-10-11 s4 218.8 s: advance 29 -> 9 -> 3 deg, rpm 1465 -> 1236,
 * no cut, no reset). Per ms the integrator moves KISRM x z x rpm / 120000
 * of the distance = rpm / 71.6 in Q12 (z cancels). Below 400 rpm and while
 * cranking the manifold is at the throttle's own value. A failed throttle
 * (0xFFFF) passes through and restarts the model. */
#define SRM_Q12_DIV  72u

unsigned int far hc_ec_load_lag(unsigned int x, unsigned int rpm)
{
    unsigned int f, y, t, d, s;

    if (x == 0xFFFFu) {
        E.lag_ok = 0u;
        return x;
    }
    if (x > 1000u) {
        x = 1000u;
    }
    t = (unsigned int)(x << 4);
    if (!E.lag_ok || rpm < 400u || eng_cranking) {
        E.lag_x16 = t;
        E.lag_ok = 1u;
        return x;
    }
    f = DIV32U((unsigned long)(unsigned int)rpm * E.dt_ms, SRM_Q12_DIV);
    if (f > 4096u) {
        f = 4096u;
    }
    y = E.lag_x16;
    d = (t > y) ? (unsigned int)(t - y) : (unsigned int)(y - t);
    s = DIV32U((unsigned long)(unsigned int)d * f, 4096u);
    if (s == 0u && d != 0u) {
        s = 1u;                         /* it reaches its target (V89 filt) */
    }
    y = (t > y) ? (unsigned int)(y + s) : (unsigned int)(y - s);
    E.lag_x16 = y;
    return (unsigned int)((y + 8u) >> 4);
}

/* =================================================================== pre */
void far hc_ec_pre(unsigned int rpm)
{
    unsigned int now = T1;
    unsigned int d = (unsigned int)((unsigned int)(now - E.t_last) + E.t_rem);
    unsigned int ms = (unsigned int)(d / T1_PER_MS);

    E.t_last = now;
    E.t_rem = (unsigned int)(d - ms * T1_PER_MS);
    if (ms > 200u) {
        ms = 200u;
    }
    E.dt_ms = ms;
    E.ms = (unsigned int)(E.ms + ms);
    E.run_ms = (trg_rpm != 0u && !eng_cranking) ? sat_add(E.run_ms, ms) : 0u;
    E.ve_tune_ms = sat_add(E.ve_tune_ms, ms);
    E.since_ae_ms = (eng_accel_us != 0u) ? 0u : sat_add(E.since_ae_ms, ms);
    E.since_cut_ms = (eng_fuelcut & (ENG_CUT_REV | ENG_CUT_BOOST | ENG_CUT_LIMP))
                   ? 0u : sat_add(E.since_cut_ms, ms);
    /* THE PRESSURE THE FUEL USES. Measured while the sensor is valid;
       otherwise rusEFI's MAP estimate table, by rpm and throttle. The
       DISPLAYED MAP stays 0 kPa (eng_map_kpa_x10). */
    if (!(eng_sensor_err & ENG_ERR_MAP)) {
        E.map_ctrl_x10 = eng_map_kpa_x10;
    } else {
        E.map_ctrl_x10 = DIV32U((unsigned long)lut8(CFG_U_MAPEST,
                                                    CFG_U_MAPEST_RPM_AX,
                                                    CFG_U_MAPEST_TPS_AX, rpm,
                                                    eng_tps_x10, 0u) * 10u, 16u);
    }
    if (E.run_ms != 0u) {
        E.prime_count = 0u;               /* the engine ran: prime next key-on */
    }
    dfco_update(rpm);
    motorsport_update(rpm);
    revlimit_update();
}

unsigned int far hc_ec_map_ctrl(void)
{
    return E.map_ctrl_x10;
}

/* ================================================================= spark */
int far hc_ec_spark(int base_x10, unsigned char cranking)
{
    int a = base_x10;
    unsigned int f;

    if (cranking) {
        E.spark_last = a;
        return a;
    }
    /* CLT / IAT (and closed-loop idle) corrections; a failed sensor's
       correction is 0 (rusEFI getCltTimingCorrection / IAT). */
    eng_ign_corr_x10 = hc_ign_corr_x10(clt_ok() ? eng_clt_dc : 0u,
                                       (eng_sensor_err & ENG_ERR_IAT)
                                       ? 0u : eng_iat_dc);
    a = (int)(a + eng_ign_corr_x10);
    /* DFCO retard while cut, ramped out after (rusEFI getTimingRetard). */
    {
        unsigned char r = hc_cal_u8(CFG_U_DFCO_RETARD);
        unsigned int ramp = (unsigned int)(hc_cal_u8(CFG_U_DFCO_RAMP) * 100u);
        if (r != 0u) {
            if (E.dfco) {
                a = (int)(a - (int)(r * 10u));
            } else if (E.since_dfco_ms < ramp) {
                a = (int)(a - (int)DIV32U((unsigned long)(unsigned int)(r * 10u)
                                          * (unsigned int)(ramp - E.since_dfco_ms),
                                          ramp));
            }
        }
    }
    /* Soft rev limit retard across the hysteresis window. */
    f = soft_frac();
    if (f != 0u) {
        a = (int)(a - (int)DIV32U((unsigned long)(unsigned int)(hc_cal_u8(CFG_U_REVLIM_SOFT_RETARD)
                                                 * 10u) * f, 256u));
    }
    if (E.als) {
        a = (int)(a + (int)hc_cal_u16(CFG_U_ANTILAG_RETARD_X10));
    }
    /* Launch and flat shift set the timing outright (rusEFI: they return
       from getRunningAdvance). 0 means "no timing change". */
    if (E.launch != 0u && hc_cal_u16(CFG_U_LAUNCH_RETARD_X10) != 0u) {
        a = (int)hc_cal_u16(CFG_U_LAUNCH_RETARD_X10);
    }
    if (E.flat && hc_cal_u16(CFG_U_FLATSHIFT_TIMING) != 0u) {
        a = (int)hc_cal_u16(CFG_U_FLATSHIFT_TIMING);
    }
    if (a > 600) a = 600;
    if (a < -300) a = -300;
    /* A STEP TOWARDS ADVANCE OF MORE THAN 10 DEG PER PASS IS SPREAD: the
       scheduler's cursor walks forward only, and an anchor stepped over by
       more than a tooth window waits a whole cycle (hcsched_dry.c
       walk_kind). Retard is never limited. */
    if (a > (int)(E.spark_last + 100)) {
        a = (int)(E.spark_last + 100);
    }
    E.spark_last = a;
    return a;
}

/* ================================================================== fuel */
unsigned int far hc_ec_fuel(unsigned int te_us)
{
    int pm = (int)(1000 + stft_applied());
    unsigned int f = soft_frac();

    if (f != 0u) {
        pm = (int)(pm + (int)DIV32U((unsigned long)(unsigned int)(hc_cal_u8(CFG_U_REVLIM_SOFT_FUEL)
                                                   * 10u) * f, 256u));
    }
    if (E.launch == 2u) {
        pm = (int)(pm + (int)(hc_cal_u8(CFG_U_LAUNCH_FUEL) * 10u));
    }
    if (E.als) {
        pm = (int)(pm + (int)(hc_cal_u8(CFG_U_ANTILAG_FUEL_PCT) * 10u));
    }
    if (pm < 500) pm = 500;
    if (pm > 2000) pm = 2000;
    E.fuel_pm = (unsigned int)pm;
    if (te_us > 30000u) {
        te_us = 30000u;           /* x2000/1000 must stay inside 60000 */
    }
    return DIV32U((unsigned long)te_us * (unsigned int)pm, 1000u);
}

/* ================================================================== post */
void far hc_ec_post(unsigned int rpm, unsigned int fuel_load)
{
    unsigned int f = 0u;
    unsigned int lam1 = hc_io_lambda(0u), lam2 = hc_io_lambda(1u);

    stft_update(rpm, fuel_load);
    if (trg_rpm != 0u && !eng_cranking) f |= EC_F_RUNNING;
    if (eng_cranking && trg_rpm != 0u) f |= EC_F_CRANKING;
    if (hc_trans.as_pm != 0u) f |= EC_F_ASE;
    if (eng_warmup_pct != 100u) f |= EC_F_WARMUP;
    if (eng_accel_us != 0u
        || (hc_trans.corr > 0 && (unsigned int)hc_trans.corr
                                 > (unsigned int)(hc_trans.want >> 5))
        || (hc_trans.corr < 0 && (unsigned int)(-hc_trans.corr)
                                 > (unsigned int)(hc_trans.want >> 5))) {
        f |= EC_F_TRANSIENT;              /* AE shot, or film > 3 % */
    }
    if (E.dfco) f |= EC_F_DFCO;
    /* VE / WUE acceptance follows lifecycle validity, including steady exhaust. */
    if (lam1 != 0u) f |= EC_F_LAM1_OK;
    if (lam2 != 0u) f |= EC_F_LAM2_OK;
    if (E.stft_state == EC_STFT_ACTIVE || E.stft_state == EC_STFT_LAMBDA
        || E.stft_state == EC_STFT_DFCO || E.stft_state == EC_STFT_AE
        || E.stft_state == EC_STFT_CUT) {
        if (stft_applied() != 0) f |= EC_F_STFT;
    }
    if (eng_fuelcut != 0u) f |= EC_F_FUELCUT;
    if (E.launch) f |= EC_F_LAUNCH;
    if (E.flat) f |= EC_F_FLATSHIFT;
    if (E.als) f |= EC_F_ALS;
    if ((eng_fuelcut & ENG_CUT_REV) || soft_frac() != 0u
        || dry_rev_spark_cut) f |= EC_F_REVLIM;
    if ((eng_sensor_err & ENG_ERR_MAP)
        && hc_cal_u8(CAL_LOAD_SOURCE) != CAL_LOAD_ALPHAN) f |= EC_F_MAPEST;
    if (E.ve_tune_ms < VE_TUNE_MS) f |= EC_F_VETUNE;
    E.flags = f;
    /* THE INJECTION ANGLE the scheduler reads on every tooth: the single
       angle, or rusEFI's injectionPhase table over rpm x fuel load. */
    if (hc_cal_u8(CFG_U_INJ_PHASE_MODE) == 1u) {
        dry_inj_phase_x10 = lut8(CFG_U_INJ_PHASE, CFG_U_INJ_PHASE_RPM_AX,
                                 CFG_U_INJ_PHASE_LOAD_AX, rpm, fuel_load, 1u);
    } else {
        dry_inj_phase_x10 = cfg_u16(CFG_INJ_START_DEG_X10);
    }
    hc_ec_prime_service();
}

void far hc_ec_ve_written(void)
{
    E.ve_tune_ms = 0u;
}

/* =============================================================== priming
 * rusEFI PrimeController: ONE pulse on every injector together, at key-on,
 * engine stopped, after primeDelay (at least 100 ms), fuel mass from the
 * primeMg curve by coolant - skipped when the coolant sensor has failed or
 * the engine is already turning, and only on the first key-on after the
 * engine last ran (the counter, above). The pulse is timed and closed by
 * hcsched_dry.c (hc_drysched_prime) from the 1 ms serial yield as well as
 * the main loop, so a long TunerStudio reply cannot stretch it. */
#define PRIME_IDLE    0u
#define PRIME_DONE    1u
#define PRIME_ACTIVE  2u

void far hc_ec_prime_service(void)
{
    unsigned int wait, mass, flow, us;
    unsigned long num;

    if (E.prime_st == PRIME_ACTIVE) {
        if (!hc_prime_on) {
            E.prime_st = PRIME_DONE;
        }
        return;
    }
    if (E.prime_st != PRIME_IDLE) {
        return;
    }
    if (trg_rpm != 0u || trg_state != TRG_NO_SIGNAL) {
        E.prime_st = PRIME_DONE;          /* already turning: no prime    */
        E.prime_count = 0xFFFFu;          /* rusEFI: -1, i.e. next time 0 */
        return;
    }
    wait = (unsigned int)(hc_cal_u8(CFG_U_PRIME_DELAY) * 100u + 100u);
    if (E.ms < wait || !hc_dbw_allowed) {
        return;                           /* sensors settle, link, page   */
    }
    E.prime_st = PRIME_DONE;
    if (E.prime_count > 10u && E.prime_count != 0xFFFFu) {
        E.prime_count = 0u;               /* toying with the key: retry   */
    }
    if (E.prime_count == 0xFFFFu) {
        E.prime_count = 0u;
    }
    if (E.prime_count++ != 0u || !clt_ok()) {
        return;
    }
    mass = hc_cal_curve16(CAL_CRANK_PW_AX, CFG_U_PRIME_MG, 8u, eng_clt_dc);
    flow = hc_cal_u16(CFG_U_INJ_FLOW_CCMIN);
    if (mass == 0u || flow < 10u) {
        return;
    }
    /* flow 0.01 mg/ms = cc/min x 745 / 600 (hc_af_flow_x100); open time
       us = mass 0.1 mg x 10000 / flow, held to 200 ms. */
    flow = DIV32U((unsigned long)flow * 745u, 600u);
    num = (unsigned long)mass * 10000u;
    if (num >= (unsigned long)flow * 60000u) {
        us = 60000u;
    } else {
        us = DIV32U(num, flow);
    }
    us = sat_add(us, eng_deadtime_us);
    if (us > 60000u) {
        us = 60000u;
    }
    E.prime_ms = E.ms;
    E.prime_st = PRIME_ACTIVE;
    /* T1 ticks / 8 (6.4 us): us x 1.25 / 8 = us x 5 / 32 */
    hc_drysched_prime(DIV32U((unsigned long)us * 5u, 32u));
}

/* The largest knock retard any cylinder carries, 0.1 deg. */
static unsigned int kn_max(void)
{
    unsigned char i, m = 0u;

    for (i = 1u; i <= 8u; i++) {
        if (HC_KN711.slot_ret[i] > m) {
            m = HC_KN711.slot_ret[i];
        }
    }
    return m;
}

/* ============================================================= telemetry
 * 1136..1199 THE FAST BLOCK - the tuning core, contiguous so a TunerStudio
 * datalog reads it in ONE request (docs/TUNERSTUDIO.md).
 * 1200..       the engine-control state. Big-endian, as every channel. */
void far hc_ec_publish(unsigned int boost_req_x10)
{
    /* every switch input's RAW level for commissioning (bit i =
       HC_SWITCH_CAV[i] reads high; bit 15 = an input is unreadable, i.e.
       the ASIC link is down), refreshed every 20 ms - ten HAL reads. */
    if ((unsigned int)(E.ms - E.sw_raw_ms) >= 20u) {
        static const unsigned char cav[HC_SWITCH_N] = HC_SWITCH_CAV;
        unsigned char i, l;
        unsigned int w = 0u;

        E.sw_raw_ms = E.ms;
        for (i = 0u; i < HC_SWITCH_N; i++) {
            l = hc_hal_din(cav[i]);
            if (l == 1u) {
                w |= (unsigned int)(1u << i);
            } else if (l > 1u) {
                w |= 0x8000u;
            }
        }
        E.sw_raw = w;
    }
    och(1132u, E.sw_raw);
    /* the FIRST REFUSED FIELD as its slot index (the .ini's
       hcCfgFieldList names it in words), 0xFFFF = none - a refused Burn says
       which setting, not only "BURN FAILED" */
    {
        const hc_cfg_slot_t *s = (hc_val_first_bad_offset == 0xFFFFu)
            ? (const hc_cfg_slot_t *)0 : hc_cfg_slot_at(hc_val_first_bad_offset);
        /* NOT a pointer subtraction: over a 12-byte struct Keil divides
           with a near ?C_ library call, which far code must never make
           (me711_far_boundary_proof rule 3; it derailed the refused APPLY
           in me711_preset_gap_proof) - the inline 32/16 divide instead */
        och(1134u, s ? DIV32U((unsigned int)((const unsigned char *)s
                                             - (const unsigned char *)hc_cfg_slots),
                              (unsigned int)sizeof(hc_cfg_slot_t))
                     : 0xFFFFu);
    }
    och(1136u, trg_rpm);
    och(1138u, eng_map_kpa_x10);
    och(1140u, eng_tps_x10);
    och(1142u, (hc_cal_u8(CAL_DBW_ENABLE) != 0u) ? hc_dbw_pedal_x10()
                                                 : eng_pedal_x10);
    och(1144u, eng_clt_meas_dc);
    och(1146u, eng_iat_dc);
    och(1148u, eng_batt_dv);
    och(1150u, eng_ve_load_x10);
    och(1152u, hc_io_lambda(0u));
    och(1154u, E.lambda_x1000);
    och(1156u, (unsigned int)E.stft_pm[0]);
    och(1158u, eng_ti_us);
    och(1160u, eng_ve_x10);
    och(1162u, (unsigned int)eng_adv_x10);
    och(1164u, eng_dwell_x100);
    och(1166u, E.flags);
    och(1168u, (unsigned int)eng_warmup_pct);
    och(1170u, eng_accel_us);
    och(1172u, kn_max());
    och(1174u, hc_dbw_target_x10());
    och(1176u, hc_dbw_actual_x10());
    och(1178u, hc_idle_target_rpm);
    och(1180u, hc_ldr_target_x10);
    och(1182u, boost_req_x10);
    och(1184u, eng_fuelcut);
    och(1186u, eng_sensor_err);
    och(1188u, (unsigned int)((unsigned int)trg_state
                              | ((unsigned int)dry_seq_active << 8)));
    och(1190u, eng_air_mg_x10);
    och(1192u, hc_io_lambda(1u));
    och(1194u, E.map_ctrl_x10);
    och(1196u, (unsigned int)eng_ign_corr_x10);
    och(1198u, hc_limp_duty_x10);
    /* the engine-control state */
    och(1200u, (unsigned int)(E.stft_state | ((unsigned int)E.stft_region << 8)));
    och(1202u, (unsigned int)E.stft_pm[1]);
    och(1204u, (unsigned int)(E.skip | ((unsigned int)E.launch << 8)
                              | ((unsigned int)E.rot << 10)
                              | ((unsigned int)E.pit << 11)
                              | ((unsigned int)E.sw_last << 12)));
    och(1206u, E.rev_limit);
    och(1208u, (unsigned int)eng_adv_base_x10);
    och(1210u, DIV32U((unsigned long)E.lambda_x1000
                      * hc_cal_u16(CFG_U_STOICH_X100), 10000u));
    och(1212u, (unsigned int)(E.prime_st | ((E.prime_count > 255u ? 255u
                                             : E.prime_count) << 8)));
    och(1214u, dry_inj_phase_x10);
    och(1216u, E.fuel_pm);
    och(1218u, E.ign_load);
    och(1220u, E.lam_load);
    /* the tooth logger: bit0 ready to read, bit1..2 mode, high byte count/8 */
    och(1222u, (unsigned int)(((hc_tlog_n >= TGT_TLOG_N
                                || (hc_tlog_n != 0u && trg_rpm == 0u)) ? 1u : 0u)
                              | ((unsigned int)hc_tlog_on << 1)
                              | ((hc_tlog_n >> 3) << 8)));
}
