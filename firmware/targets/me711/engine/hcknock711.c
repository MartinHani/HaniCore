/*
 * hcknock711.c - the ME7.1.1 knock driver. See hcknock711.h for who
 * shares HC_KN711 and docs/ARCHITECTURE.md for the evidence of every pin.
 *
 * FAR (FCODE), MOD167 MEDIUM with DEFINE(HC_FAR_BRIDGE): page reads through
 * hcfarinline.h, the scheduler snapshot through its far thunk. 16-bit
 * arithmetic only; every 32-bit product is divided by a 16-bit divisor with
 * the quotient bounded first (inline DIVLU, no ?C_ helper).
 *
 * THE CHAIN, one cylinder at a time:
 *   arm (main loop + serial yield) - the next cylinder's window opening, from
 *     the last planned tooth: engine angle of its TDC + knockWinStart, as a
 *     T7 time; the sensor select and gain for it on P3 (KSA1/KSA2, G0..G2)
 *     BEFORE the window opens (the OEM sets them at the previous close);
 *     CC16 = that time, compare mode 0, interrupt 11/0.
 *   CC16 ISR (hctrig_me711.c) - MF (P8.0) high, CC16 += length; then MF low.
 *   service (main loop only - it converts) - AN15 (KI) once, the strategy
 *     for that cylinder, the recovery clock, the retard per ignition slot the
 *     scheduler adds (ACTIVE only), the telemetry.
 * One window at a time: the next is armed only after this one is sampled.
 * A window whose opening is already past is not taken (counted, never
 * opened late); a window that never closes is aborted and counted.
 *
 * PINS (the ME7.1.1 schematic S1300, CC195): G0..G2 = P3.1..P3.3, KSA1 P3.4, KSA2 P3.7,
 * KSA3 P3.6, KTI P3.5, MF P8.0, KI AN15; BF0..BF3 = ASIC P1.12..15 (word 54
 * of the runtime frame, hcio711.c). The OEM port init [BIN seg8C:0DCC]
 * drives P3.1..P3.7 as push-pull outputs, LOW; HaniCore takes them only
 * while knockMode is not Off and releases them (inputs) otherwise.
 */
#include "hcfarbridge.h"
#include <reg167.h>
#include "hctarget.h"
#include "hcatomic.h"
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hcfarinline.h"
#include "hc_config_manager.h"
#include "hctrigger.h"
#include "hcengine.h"
#include "hcsched_dry.h"
#include "hcio711.h"
#include "hcknock711.h"

#define KN HC_KN711
typedef char hc_kn_fits[(sizeof(hc_kn711_t) <= TGT_RAM_KNOCK_LIMIT) ? 1 : -1];

#define OCH2B ((unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_OCH2))
#define OCH2_BASE  1024u            /* TGT_OCH_SPLIT: OCH offset of OCH2B[0] */

/* [BIN] band code per centre frequency (5,6,7,8,9,10,12,14,16 kHz) and the
   gain code per x2 step; the select code per sensor index [BIN 0x094690:
   C019..C01C = 3, 2, 0, 1]. */
static const unsigned char band_code[9] = { 8u, 10u, 11u, 12u, 6u, 0u, 2u, 3u, 4u };
static const unsigned char gain_code[7] = { 0u, 1u, 2u, 3u, 5u, 6u, 7u };
static const unsigned char sel_code[4]  = { 3u, 2u, 0u, 1u };

#define MIN_LEAD_TICKS  US_TO_TICKS(80u)     /* arm at least this far ahead   */
#define MAX_LEAD_TICKS  30000u               /* 24 ms: T7 compare horizon     */
#define STALE_TICKS     40000u               /* 32 ms without a close: abort  */
#define ADC_TMO_TICKS   US_TO_TICKS(3000u)   /* two ticks + a conversion */
extern volatile unsigned char hc_adc_ctl;    /* hcmain_me711.c adc_service() */
extern unsigned int adc_raw[];
#define ADC_KI_REQ  0x10u
#define ADC_KI_DONE 0x20u
/* the tick reads-modifies-writes the same byte: change it at the critical
   level (hcatomic.h, above the tick) */
#define KI_SET(m, v) do { unsigned int _p; HC_ATOMIC_ENTER(_p);             \
        hc_adc_ctl = (unsigned char)((hc_adc_ctl & ~(m)) | (v));            \
        HC_ATOMIC_EXIT(_p); } while (0)
#define DYN_TPS_RATE    500                  /* 50 %/s: threshold dynamics    */

/* ------------------------------------------------------------- pins -- */
static void p3_select(unsigned char gain, unsigned char sel)
{
    unsigned int set = (unsigned int)((gain & 7u) << 1);
    if (sel & 1u) set |= 0x0010u;           /* KSA1 P3.4 */
    if (sel & 2u) set |= 0x0080u;           /* KSA2 P3.7 */
    /* KTI (P3.5) and KSA3 (P3.6) stay LOW, the OEM's idle levels. Two
       single-instruction ops: nothing else on P3 is touched. */
    P3 |= set;
    P3 &= (unsigned int)~(0x00FEu & ~set);
    KN.gain_code = (unsigned char)(gain & 7u);
    KN.sel_code = (unsigned char)(sel & 3u);
}

static void pins_take(void)
{
    CC16IC = 0u;
    P8 &= (unsigned int)~0x0001u;           /* MF low, then drive it */
    DP8 |= 0x0001u;
    P3 &= (unsigned int)~0x00FEu;           /* OEM levels: all LOW */
    DP3 |= 0x00FEu;
    CCM4 &= 0xFFF0u;                        /* CC16: compare mode 0 on T7 */
    CCM4 |= 0x0004u;
    KN.pins_owned = 1u;
}

static void pins_release(void)
{
    CC16IC = 0u;
    CCM4 &= 0xFFF0u;
    P8 &= (unsigned int)~0x0001u;           /* value first, then direction */
    DP8 &= (unsigned int)~0x0001u;
    P3 &= (unsigned int)~0x00FEu;
    DP3 &= (unsigned int)~0x00FEu;
    KN.pins_owned = 0u;
    KN.st = KN_ST_IDLE;
}

/* -------------------------------------------------------------- math -- */
/* a * b / c with the quotient known to fit (callers bound it) */
static unsigned int muldiv(unsigned int a, unsigned int b, unsigned int c)
{
    return (unsigned int)((unsigned long)a * b / c);
}

static unsigned int lerp_u16(unsigned int x0, unsigned int x1, unsigned int v0,
                             unsigned int v1, unsigned int x)
{
    unsigned int span, d;
    if (x1 <= x0 || x <= x0) return v0;
    if (x >= x1) return v1;
    span = (unsigned int)(x1 - x0);
    d = (unsigned int)(x - x0);
    if (v1 >= v0) return (unsigned int)(v0 + muldiv((unsigned int)(v1 - v0), d, span));
    return (unsigned int)(v0 - muldiv((unsigned int)(v0 - v1), d, span));
}

/* the 8-point knock rpm curve at rpm */
static unsigned int curve8(unsigned int val_off, unsigned int rpm)
{
    unsigned char i;
    unsigned int a0 = hc_cal_u16(CFG_U_KNOCK_RPM_AX), a1;
    if (rpm <= a0) return hc_cal_u16(val_off);
    for (i = 1u; i < 8u; i++) {
        a1 = hc_cal_u16((unsigned int)(CFG_U_KNOCK_RPM_AX + 2u * i));
        if (rpm < a1) {
            return lerp_u16(a0, a1, hc_cal_u16((unsigned int)(val_off + 2u * (i - 1u))),
                            hc_cal_u16((unsigned int)(val_off + 2u * i)), rpm);
        }
        a0 = a1;
    }
    return hc_cal_u16((unsigned int)(val_off + 14u));
}

/* ------------------------------------------------------ configuration -- */
static unsigned int cfg_rev;

static void cfg_load(void)
{
    unsigned char i, j, n;
    unsigned int t, c;
    unsigned char e;

    n = KN.geom_n;
    KN.cfg.cyls = (unsigned char)(n ? n : 1u);
    for (i = 0u; i < HCKNOCK_CYL; i++) {
        KN.cfg.sensor[i] = hc_cal_u8((unsigned int)(CFG_U_KNOCK_SENSOR + i));
    }
    KN.cfg.rpm_min = hc_cal_u16(CFG_U_KNOCK_RPM_MIN);
    KN.cfg.load_min = hc_cal_u8(CFG_U_KNOCK_LOAD_MIN);
    t = hc_cal_u16(CFG_U_KNOCK_CLT_MIN);           /* 10*C + 10000 */
    if (t >= 10000u) {
        t = (unsigned int)((t - 10000u) / 10u);
        KN.cfg.clt_min = (signed char)(t > 127u ? 127 : (int)t);
    } else {
        t = (unsigned int)((10000u - t) / 10u);
        KN.cfg.clt_min = (signed char)(t > 128u ? -128 : -(int)t);
    }
    KN.cfg.tp = hc_cal_u8(CFG_U_KNOCK_TP);
    KN.cfg.tp_dyn = hc_cal_u8(CFG_U_KNOCK_TP_DYN);
    for (i = 0u; i < HCKNOCK_KEFN; i++) {
        KN.cfg.kef_rpm[i] = hc_cal_u16((unsigned int)(CFG_U_KNOCK_KEF_RPM + 2u * i));
        KN.cfg.kef16[i] = hc_cal_u8((unsigned int)(CFG_U_KNOCK_KEF + i));
    }
    KN.cfg.kef_dyn16 = hc_cal_u8(CFG_U_KNOCK_KEF_DYN);
    KN.cfg.ref_init = hc_cal_u16(CFG_U_KNOCK_REF_INIT);
    KN.cfg.learn = hc_cal_u8(CFG_U_KNOCK_LEARN);
    KN.cfg.step_q = hc_cal_u8(CFG_U_KNOCK_STEP_Q);
    KN.cfg.max_q = hc_cal_u8(CFG_U_KNOCK_MAX_Q);
    KN.cfg.safe_q = hc_cal_u8(CFG_U_KNOCK_SAFE_Q);
    KN.cfg.reapply_ms = hc_cal_u16(CFG_U_KNOCK_REAPPLY_MS);
    KN.cfg.diag_rpm = hc_cal_u16(CFG_U_KNOCK_DIAG_RPM);
    KN.cfg.ref_min = hc_cal_u16(CFG_U_KNOCK_REF_MIN);
    KN.cfg.ref_max = hc_cal_u16(CFG_U_KNOCK_REF_MAX);
    KN.cfg.diag_n = hc_cal_u8(CFG_U_KNOCK_DIAG_N);
    KN.cfg.stop_n = hc_cal_u8(CFG_U_KNOCK_STOP_N);

    e = hcknock_check(&KN.cfg);
    if (!e && n == 0u) e = HCKNOCK_E_CYLS;          /* no engine described */
    if (!e && KN.cfg.max_q > 100u) e = HCKNOCK_E_RETARD;   /* <= 25.0 deg */
    if (!e && hc_cal_u8(CFG_U_KNOCK_BAND) > 8u) e = 8u;
    for (i = 0u; !e && i < 4u; i++) {
        if (hc_cal_u8((unsigned int)(CFG_U_KNOCK_GAIN + i)) > 6u) e = 9u;
    }
    KN.cfg_err = e;

    /* the cylinder 360 deg away (its twin while the cycle is unknown) */
    c = KN.geom_cycle;
    for (i = 0u; i < 8u; i++) {
        KN.twin[i] = 0xFFu;
        if (i >= n || c != 7200u) continue;
        for (j = 0u; j < n; j++) {
            unsigned int d = (KN.geom_tdc[j] >= KN.geom_tdc[i])
                ? (unsigned int)(KN.geom_tdc[j] - KN.geom_tdc[i])
                : (unsigned int)(KN.geom_tdc[i] - KN.geom_tdc[j]);
            if (d >= 3550u && d <= 3650u) {
                KN.twin[i] = j;
            }
        }
    }
    KN.band_code = band_code[hc_cal_u8(CFG_U_KNOCK_BAND) > 8u ? 7u
                             : hc_cal_u8(CFG_U_KNOCK_BAND)];
    hcknock_reset(&KN.k, &KN.cfg);
    cfg_rev = hc_cfg_active_rev;
}

/* ----------------------------------------------------------- lifecycle -- */
void far hc_knock_init(void)
{
    unsigned int i;
    unsigned char huge *p = (unsigned char huge *)&KN;
    unsigned char huge *g0 = (unsigned char huge *)&KN.geom_n;
    unsigned char huge *g1 = (unsigned char huge *)&KN.snap_angle;
    /* ?C_INIT never runs and the SRAM keeps junk: zero everything EXCEPT the
       geometry, which the scheduler writes whenever it (re)builds its lists -
       possibly before this runs */
    for (i = 0u; i < (unsigned int)sizeof(hc_kn711_t); i++) {
        if (p + i >= g0 && p + i < g1) continue;
        p[i] = 0u;
    }
    /* OCH2 belongs to the V97 channels (knock, VVT): cleared at every boot */
    for (i = 0u; i < (unsigned int)TGT_RAM_OCH2_LIMIT; i++) {
        OCH2B[i] = 0u;
    }
    KN.st = KN_ST_IDLE;
    KN.mode = KN_MODE_OFF;
    KN.why = KN_WHY_OFF;
    cfg_rev = 0xFFFFu;
    pins_release();
}

/* ------------------------------------------------------------- arming -- */
void far hc_knock_arm(void)
{
    unsigned int now1, now7, age, cyc, tooth, dt, best_lead, lead, a, da;
    unsigned char i, c, best, n;

    if (KN.mode == KN_MODE_OFF || KN.cfg_err || KN.st != KN_ST_IDLE) {
        return;
    }
    n = KN.geom_n;
    if (n == 0u || trg_state < TRG_SYNC_CRANK) {
        KN.why = KN_WHY_SYNC;
        return;
    }
    if (trg_rpm < KN.cfg.rpm_min || trg_rpm == 0u) {
        KN.why = KN_WHY_RPM;
        return;
    }
    hc_drysched_snap();
    if (!KN.snap_valid) {
        KN.why = KN_WHY_SYNC;
        return;
    }
    if (KN.snap_stamp != KN.stamp_seen) {
        KN.stamp_seen = KN.snap_stamp;
        KN.stamp_ms = KN.last_ms;
    } else if ((unsigned int)(KN.last_ms - KN.stamp_ms) > 20u) {
        KN.why = KN_WHY_SYNC;           /* no tooth for 20 ms: stopped */
        return;
    }
    now1 = T1;
    now7 = T7;
    cyc = KN.geom_cycle;
    tooth = KN.snap_tooth;
    dt = KN.snap_dt;
    if (cyc == 0u || tooth == 0u || dt == 0u) {
        return;
    }
    age = (unsigned int)(now1 - KN.snap_stamp);
    if (age >= MAX_LEAD_TICKS) {
        KN.why = KN_WHY_SYNC;           /* no tooth for 24 ms: not turning */
        return;
    }
    best = 0xFFu;
    best_lead = 0xFFFFu;
    for (i = 0u; i < n; i++) {
        c = (unsigned char)(KN.next + i);
        if (c >= n) c = (unsigned char)(c - n);
        a = (unsigned int)(KN.geom_tdc[c] + KN.win_start_x10);
        while (a >= cyc) a = (unsigned int)(a - cyc);
        da = (a >= KN.snap_angle) ? (unsigned int)(a - KN.snap_angle)
                                  : (unsigned int)(a + cyc - KN.snap_angle);
        /* ticks = da * dt / tooth, only if it fits the horizon */
        if ((unsigned long)da * dt >= (unsigned long)tooth * MAX_LEAD_TICKS) {
            continue;
        }
        lead = muldiv(da, dt, tooth);
        if (lead <= age || (unsigned int)(lead - age) < MIN_LEAD_TICKS) {
            continue;                   /* already past, or too close */
        }
        lead = (unsigned int)(lead - age);
        if (lead < best_lead) {
            best_lead = lead;
            best = c;
        }
    }
    if (best == 0xFFu) {
        KN.why = KN_WHY_LATE;
        if (KN.late != 0xFFFFu) KN.late++;
        return;
    }
    if ((unsigned long)KN.win_len_x10 * dt >= (unsigned long)tooth * MAX_LEAD_TICKS) {
        return;
    }
    p3_select(gain_code[hc_cal_u8((unsigned int)(CFG_U_KNOCK_GAIN
                                                 + (KN.cfg.sensor[best] & 3u))) % 7u],
              sel_code[KN.cfg.sensor[best] & 3u]);
    KN.cyl = best;
    KN.len_ticks = muldiv(KN.win_len_x10, dt, tooth);
    if (KN.len_ticks < 10u) KN.len_ticks = 10u;
    KN.t_arm = now7;
    /* the elapsed part since now7 was read is inside MIN_LEAD */
    KN.st = KN_ST_ARMED;
    CC16 = (unsigned int)(now7 + best_lead);
    CC16IC = HC_IC(TGT_ILVL_KNOCK, TGT_GLVL_KNOCK);   /* IR clear, IE set */
    if (KN.windows != 0xFFFFu) KN.windows++;
    KN.next = (unsigned char)(best + 1u);
    if (KN.next >= n) KN.next = 0u;
    KN.why = KN_WHY_OK;
}

/* ------------------------------------------------------------ sampling -- */
static void sample(void)
{
    unsigned int ikr, rl;
    unsigned char cyl = KN.cyl;
    hcknock_in_t in;
    int clt;

    /* the 1 ms tick owns the main ADC (hcmain_me711.c); KI is
       REQUESTED and read back from adc_raw[15] on a later pass. */
    if (!(hc_adc_ctl & (ADC_KI_REQ | ADC_KI_DONE))) {
        KI_SET(ADC_KI_REQ | ADC_KI_DONE, ADC_KI_REQ);
        KN.t_arm = T7;        /* the request time: t_arm is unused once CLOSED */
        return;
    }
    if (!(hc_adc_ctl & ADC_KI_DONE)) {
        if ((unsigned int)(T7 - KN.t_arm) >= ADC_TMO_TICKS) {
            KI_SET(ADC_KI_REQ | ADC_KI_DONE, 0u);
            KN.st = KN_ST_IDLE;
            KN.why = KN_WHY_ADC;
            if (KN.adc_fail != 0xFFFFu) KN.adc_fail++;
        }
        return;
    }
    KI_SET(ADC_KI_REQ | ADC_KI_DONE, 0u);
    ikr = (unsigned int)(adc_raw[15] & 0x03FFu);
    KN.st = KN_ST_IDLE;                 /* the next window may be armed */
    if (cyl >= 8u) {
        return;
    }
    KN.ikr[cyl] = ikr;
    if (KN.samples != 0xFFFFu) KN.samples++;
    in.ikr = ikr;
    in.rpm = trg_rpm;
    rl = (unsigned int)(eng_rl_x10 / 10u);
    in.load = (unsigned char)(rl > 255u ? 255u : rl);
    clt = (eng_clt_dc >= 10000u) ? (int)((eng_clt_dc - 10000u) / 10u)
                                 : -(int)((10000u - eng_clt_dc) / 10u);
    if (eng_sensor_err & ENG_ERR_CLT) {
        clt = 90;      /* a failed coolant sensor must not switch knock
                          control OFF (its minimum coolant): taken as warm */
    }
    in.clt = (signed char)(clt > 127 ? 127 : (clt < -40 ? -40 : clt));
    in.dyn = (unsigned char)(eng_tps_rate > DYN_TPS_RATE
                             || eng_tps_rate < -DYN_TPS_RATE);
    (void)hcknock_ignition(&KN.k, &KN.cfg, cyl, &in);
}

/* ---------------------------------------------------------- the retard -- */
static void slot_retard(void)
{
    unsigned char r[9], i, s, q, full;
    unsigned int x;

    for (i = 0u; i < 9u; i++) r[i] = 0u;
    if (KN.mode == KN_MODE_ACTIVE && !KN.cfg_err) {
        full = (unsigned char)(trg_state >= TRG_SYNC_FULL);
        for (i = 0u; i < KN.geom_n && i < 8u; i++) {
            q = hcknock_retard(&KN.k, &KN.cfg, i);
            x = (unsigned int)(((unsigned int)q * 5u) >> 1);    /* q -> 0.1 deg */
            if (x > 250u) x = 250u;
            s = (unsigned char)(KN.geom_slot[i] & 0x0Fu);
            if (s > 8u) s = 0u;
            if ((unsigned char)x > r[s]) r[s] = (unsigned char)x;
            if ((unsigned char)x > r[0]) r[0] = (unsigned char)x;
            /* the cycle unknown: this cylinder may be its twin - retard both */
            if (!full && KN.twin[i] < 8u) {
                s = (unsigned char)(KN.geom_slot[KN.twin[i]] & 0x0Fu);
                if (s <= 8u && (unsigned char)x > r[s]) r[s] = (unsigned char)x;
            }
        }
        if (r[0]) {
            /* a slot of 0 means every output (batch / distributor) */
            for (i = 0u; i < KN.geom_n && i < 8u; i++) {
                if ((KN.geom_slot[i] & 0x0Fu) == 0u) {
                    for (s = 1u; s < 9u; s++) if (r[s] < r[0]) r[s] = r[0];
                }
            }
        }
    }
    for (i = 0u; i < 9u; i++) {
        KN.slot_ret[i] = r[i];          /* bytes: no torn read on the tooth */
    }
}

unsigned char far hc_knock_faults(void)
{
    return (unsigned char)((KN.mode == KN_MODE_OFF || KN.cfg_err)
                           ? 0u : (KN.k.fault & 0x0Fu));
}

unsigned int far hc_knock_max_x10(void)
{
    return (unsigned int)KN.slot_ret[0];
}

/* ----------------------------------------------------------- telemetry -- */
static void o16(unsigned int off, unsigned int v)
{
    OCH2B[off - OCH2_BASE] = (unsigned char)(v >> 8);
    OCH2B[off - OCH2_BASE + 1u] = (unsigned char)(v & 0xFFu);
}

static void o8(unsigned int off, unsigned char v)
{
    OCH2B[off - OCH2_BASE] = v;
}

static void publish(void)
{
    unsigned char i;
    o16(1024u, (unsigned int)(KN.mode | ((unsigned int)KN.why << 8)));
    o16(1026u, KN.windows);
    o16(1028u, KN.samples);
    o16(1030u, KN.late);
    o16(1032u, KN.stale);
    o16(1034u, KN.adc_fail);
    o16(1036u, (unsigned int)(KN.cyl | ((unsigned int)KN.cfg_err << 8)));
    o16(1038u, (KN.cyl < 8u) ? KN.ikr[KN.cyl] : 0u);
    o16(1040u, KN.win_start_x10);
    o16(1042u, KN.win_len_x10);
    o16(1044u, (unsigned int)(KN.band_code | ((unsigned int)KN.gain_code << 8)));
    o16(1046u, (unsigned int)(KN.sel_code
                              | ((unsigned int)(KN.k.fault & 0x0Fu) << 8)
                              | ((unsigned int)(KN.k.fault_hi & 0x0Fu) << 12)));
    o16(1048u, KN.k.knocks);
    o16(1050u, (unsigned int)KN.slot_ret[0]);
    o16(1052u, (unsigned int)(KN.k.stop | ((unsigned int)KN.k.active << 8)
                              | ((unsigned int)KN.pins_owned << 9)));
    for (i = 0u; i < 8u; i++) {
        o16((unsigned int)(1054u + 2u * i), KN.ikr[i]);
        o16((unsigned int)(1070u + 2u * i), (unsigned int)(KN.k.ref16[i] >> 4));
        o8((unsigned int)(1086u + i), KN.k.level16[i]);
        o8((unsigned int)(1094u + i), KN.k.ret_q[i]);
        o8((unsigned int)(1102u + i), KN.k.kcount[i]);
    }
    o16(1110u, (unsigned int)(KN.t_close - KN.t_open));
}

void far hc_knock_service(unsigned int now_ms)
{
    unsigned int ms;
    unsigned char mode = hc_cal_u8(CFG_U_KNOCK_MODE);

    ms = KN.have_ms ? (unsigned int)(now_ms - KN.last_ms) : 0u;
    KN.last_ms = now_ms;
    KN.have_ms = 1u;
    if (mode > KN_MODE_ACTIVE) {
        mode = KN_MODE_OFF;
    }
    if (mode != KN.mode || (mode != KN_MODE_OFF && cfg_rev != hc_cfg_active_rev)) {
        if (mode == KN_MODE_OFF) {
            pins_release();
            hc_io_knock_band(0xFFu);            /* the OEM idle image again */
        } else {
            cfg_load();
            if (!KN.pins_owned) pins_take();
            hc_io_knock_band(KN.band_code);
        }
        KN.mode = mode;
    }
    if (mode == KN_MODE_OFF) {
        KN.why = KN_WHY_OFF;
    } else if (KN.cfg_err) {
        KN.why = KN_WHY_CFG;
        if (KN.st != KN_ST_IDLE) {
            CC16IC = 0u;
            P8 &= (unsigned int)~0x0001u;
            KN.st = KN_ST_IDLE;
        }
    } else {
        KN.win_start_x10 = curve8(CFG_U_KNOCK_WIN_START, trg_rpm);
        KN.win_len_x10 = curve8(CFG_U_KNOCK_WIN_LEN, trg_rpm);
        if (KN.win_len_x10 < 50u) KN.win_len_x10 = 50u;
        if (KN.st == KN_ST_CLOSED) {
            sample();
        } else if (KN.st != KN_ST_IDLE
                   && (unsigned int)(T7 - KN.t_arm) >= STALE_TICKS) {
            /* armed or open for 32 ms: the engine stopped or lost sync */
            CC16IC = 0u;
            P8 &= (unsigned int)~0x0001u;
            KN.st = KN_ST_IDLE;
            KN.why = KN_WHY_STALE;
            if (KN.stale != 0xFFFFu) KN.stale++;
        }
        hc_knock_arm();
        hcknock_tick(&KN.k, &KN.cfg, ms);
    }
    slot_retard();
    publish();
}
