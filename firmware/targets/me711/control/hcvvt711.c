/*
 * hcvvt711.c - camshaft phase control on ME7.1.1. Read hcvvt711.h.
 *
 * FAR (FCODE), MOD167 MEDIUM with DEFINE(HC_FAR_BRIDGE). 16-bit arithmetic;
 * every 32-bit product is divided by a constant or a 16-bit divisor with the
 * quotient bounded first (inline, no ?C_ helper).
 *
 * PER CAM b (1 = intake / bank 1, 2 = its pair - which physical cam is the
 * page's: pinCam<b>Sol and the cam input it closes on, cam b of the trigger):
 *   target   vvtTarget<b> (rpm x rl, 0.1 deg ADVANCE from the cam's zero
 *            position, bilinear);
 *   position -hccam_bank[b-1].sync_dev_x10 (the PATTERN core's tooth-0
 *            deviation, + = the tooth arrives EARLIER = advanced), fresh
 *            only while tooth 0 keeps being identified (syncs[], counted by
 *            the trigger);
 *   core     control/hcvvt.c: OFF / SWITCH (on-off adjusters) / CLOSED (PID,
 *            conditional integration, invalid position -> 0);
 *   output   POUT0 (cavity 115) or POUT1 (cavity 120), vvtFreqHz, the stage
 *            ON while PT < PW (the CJ920 inverts; latch 0), duty 0 = the
 *            pin RELEASED (the stage's input bias is OFF) - as the bench's
 *            V82 cam solenoid test, which is the only other writer and which
 *            owns the unit while it runs;
 *   faults   no position while closing the loop (NOFB), error beyond the
 *            limit for the time (SLOW - stuck / slow phaser), the tooth
 *            outside the VVT authority (RANGE), enabled with no stage routed
 *            (ROUTE). A fault drops the duty to 0 (the phaser's rest
 *            position) and latches until the engine stops; hcdtc711.c turns
 *            it into P0011 / P0021.
 */
#include "hcfarbridge.h"
#include <reg167.h>
#include "hctarget.h"
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hcfarinline.h"
#include "hctrigger.h"
#include "hcengine.h"
#include "hccam.h"
#include "hcbench.h"
#include "hcvvt711.h"

#define VV HC_VVT711
typedef char hc_vvt_fits[(sizeof(hc_vvt711_t) <= TGT_RAM_VVT_LIMIT) ? 1 : -1];

#define OCH2B ((unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_OCH2))
#define OCH2_BASE  1024u
#define STEP_MS    20u

/* ------------------------------------------------------------- output -- */
static void unit_write(unsigned char u, unsigned int duty_x10)
{
    unsigned int b = (u == 1u) ? 0x0002u : 0x0001u;
    unsigned int f = hc_cal_u16(CFG_U_VVT_FREQ_HZ);
    unsigned int pp, pw;

    if (f < 20u) f = 250u;                  /* the OEM's 250 Hz            */
    if (f > 1000u) f = 1000u;
    pp = (unsigned int)((62500u / f) * 10u);   /* fCPU/64 counts per period */
    pw = (unsigned int)((unsigned long)duty_x10 * pp / 1000u);
    if (duty_x10 == 0u || pw == 0u) {
        if (VV.unit_on[u]) {
            PWMCON1 &= (unsigned int)~b;    /* the pin is the latch again  */
            DP7 &= (unsigned int)~b;        /* released: stage OFF         */
            PWMCON0 &= (unsigned int)~b;    /* timer stopped               */
            VV.unit_on[u] = 0u;
        }
        VV.pw[u] = 0u;
        return;
    }
    if (u == 1u) { PP1 = (unsigned int)(pp - 1u); PW1 = pw; }
    else         { PP0 = (unsigned int)(pp - 1u); PW0 = pw; }
    if (!VV.unit_on[u]) {
        P7 &= (unsigned int)~b;             /* latch 0: pin = PWM signal   */
        if (u == 1u) PT1 = 0u; else PT0 = 0u;
        PWMCON0 |= (unsigned int)(b | (b << 4));   /* run, fCPU/64        */
        PWMCON1 |= b;                       /* POUTx drives the pin        */
        DP7 |= b;
        VV.unit_on[u] = 1u;
    }
    VV.pw[u] = pw;
}

/* ------------------------------------------------------------- tables -- */
static int lerp_s(int v0, int v1, unsigned int f256)
{
    if (v1 >= v0) {
        return (int)(v0 + (int)(((unsigned long)(unsigned int)(v1 - v0) * f256) / 256u));
    }
    return (int)(v0 - (int)(((unsigned long)(unsigned int)(v0 - v1) * f256) / 256u));
}

/* index i (0..6) and fraction (0..256) of x on an 8-point axis */
static unsigned char axis(unsigned int ax_off, unsigned int x, unsigned int *f)
{
    unsigned char i;
    unsigned int a0 = hc_cal_u16v(ax_off), a1;
    *f = 0u;
    if (x <= a0) return 0u;
    for (i = 0u; i < 7u; i++) {
        a0 = hc_cal_u16v((unsigned int)(ax_off + 2u * i));
        a1 = hc_cal_u16v((unsigned int)(ax_off + 2u * (i + 1u)));
        if (x < a1) {
            if (a1 > a0) {
                *f = (unsigned int)(((unsigned long)(x - a0) * 256u) / (unsigned int)(a1 - a0));
            }
            return i;
        }
    }
    *f = 256u;
    return 6u;
}

/* [load][rpm] - a row is one load, as TunerStudio's [8x8] with
   xBins = rpm, yBins = load reads it (hc_cal_map has the same order). */
static int cell(unsigned int tbl, unsigned char r, unsigned char c)
{
    return (int)hc_cal_u16v((unsigned int)(tbl + 2u * (8u * c + r)));
}

/* r = rpm index, l = load index */
static int target_of(unsigned int tbl, unsigned int rpm, unsigned int load)
{
    unsigned int fr, fl;
    unsigned char r = axis(CFG_U_VVT_RPM_AX, rpm, &fr);
    unsigned char l = axis(CFG_U_VVT_LOAD_AX, load, &fl);
    int a = lerp_s(cell(tbl, r, l), cell(tbl, r, (unsigned char)(l + 1u)), fl);
    int b = lerp_s(cell(tbl, (unsigned char)(r + 1u), l),
                   cell(tbl, (unsigned char)(r + 1u), (unsigned char)(l + 1u)), fl);
    return lerp_s(a, b, fr);
}

/* ------------------------------------------------------------ service -- */
void far hc_vvt_init(void)
{
    unsigned int i;
    unsigned char huge *p = (unsigned char huge *)&VV;
    for (i = 0u; i < (unsigned int)sizeof(hc_vvt711_t); i++) {
        p[i] = 0u;                      /* ?C_INIT never runs; SRAM keeps junk */
    }
    hcvvt_reset(&VV.v[0]);
    hcvvt_reset(&VV.v[1]);
}

void far hc_vvt_clear_faults(void)
{
    VV.fault[0] = VVT_F_NONE; VV.err_ms[0] = 0u;
    VV.fault[1] = VVT_F_NONE; VV.err_ms[1] = 0u;
}

unsigned char far hc_vvt_fault(unsigned char b)
{
    return VV.fault[b & 1u];
}

static void o16(unsigned int off, unsigned int v)
{
    OCH2B[off - OCH2_BASE] = (unsigned char)(v >> 8);
    OCH2B[off - OCH2_BASE + 1u] = (unsigned char)(v & 0xFFu);
}

static void step_cam(unsigned char b, unsigned int ms, unsigned char bench)
{
    hcvvt_cfg_t c;
    hcvvt_in_t in;
    unsigned int t, duty, pin, e;
    int clt;
    unsigned char u, cls;

    c.mode = hc_cal_u8v((unsigned int)(CFG_U_VVT_MODE + b));
    c.invert = hc_cal_u8v((unsigned int)(CFG_U_VVT_INVERT + b));
    c.min_rpm = hc_cal_u16(CFG_U_VVT_MIN_RPM);
    t = hc_cal_u16(CFG_U_VVT_MIN_CLT);             /* 10*C + 10000 */
    c.min_clt_c = (t >= 10000u) ? (int)((t - 10000u) / 10u)
                                : -(int)((10000u - t) / 10u);
    c.delay_ms = hc_cal_u16(CFG_U_VVT_DELAY_MS);
    c.kp = hc_cal_u16v((unsigned int)(CFG_U_VVT_KP + 2u * b));
    c.ki = hc_cal_u16v((unsigned int)(CFG_U_VVT_KI + 2u * b));
    c.kd = hc_cal_u16v((unsigned int)(CFG_U_VVT_KD + 2u * b));
    c.duty_min_x10 = hc_cal_u16v((unsigned int)(CFG_U_VVT_DUTY_MIN + 2u * b));
    c.duty_max_x10 = hc_cal_u16v((unsigned int)(CFG_U_VVT_DUTY_MAX + 2u * b));
    c.duty_on_x10 = hc_cal_u16v((unsigned int)(CFG_U_VVT_DUTY_ON + 2u * b));

    pin = hc_cal_u8(b ? CFG_U_PIN_CAM2_SOL : CFG_U_PIN_CAM1_SOL);
    u = (pin == 115u) ? 0u : (pin == 120u) ? 1u : 0xFFu;

    /* the position: fresh while tooth 0 keeps being identified */
    if (VV.syncs[b] != VV.seen[b]) {
        VV.seen[b] = VV.syncs[b];
        VV.fresh_ms[b] = 0u;
    } else if (VV.fresh_ms[b] < 60000u) {
        VV.fresh_ms[b] = (unsigned int)(VV.fresh_ms[b] + ms);
    }
    cls = hccam_bank[b].cls;
    in.rpm = trg_rpm;
    clt = (eng_clt_dc >= 10000u) ? (int)((eng_clt_dc - 10000u) / 10u)
                                 : -(int)((10000u - eng_clt_dc) / 10u);
    in.clt_c = clt;
    in.pos_x10 = (int)(-hccam_bank[b].sync_dev_x10);
    in.pos_ok = (unsigned char)(VV.fresh_ms[b] < hc_cal_u16(CFG_U_VVT_FB_MS)
                                && cls != HCCAM_C_ERROR
                                && cls != HCCAM_C_OFFSET);
    in.target_x10 = target_of(b ? CFG_U_VVT_TARGET2 : CFG_U_VVT_TARGET1,
                              trg_rpm, eng_rl_x10);
    VV.target[b] = in.target_x10;
    VV.pos[b] = in.pos_ok ? in.pos_x10 : 0;

    if (trg_rpm == 0u) {
        VV.fault[b] = VVT_F_NONE;       /* engine stopped: re-armed */
        VV.err_ms[b] = 0u;
    }
    if (c.mode != HCVVT_MODE_OFF && u == 0xFFu) {
        VV.fault[b] = VVT_F_ROUTE;
    }
    if (VV.fault[b] != VVT_F_NONE) {
        c.mode = HCVVT_MODE_OFF;        /* the phaser's rest position */
    }
    duty = hcvvt_step(&VV.v[b], &c, &in, ms);

    /* the diagnosis, closed loop only */
    if (c.mode == HCVVT_MODE_CLOSED) {
        if (cls == HCCAM_C_OFFSET && trg_rpm != 0u) {
            VV.fault[b] = VVT_F_RANGE;
        }
        if (VV.v[b].state & HCVVT_S_NOPOS) {
            if (VV.fresh_ms[b] >= (unsigned int)(hc_cal_u16(CFG_U_VVT_FB_MS) * 2u)) {
                VV.fault[b] = VVT_F_NOFB;
            }
        }
        e = (VV.v[b].err_x10 < 0) ? (unsigned int)(-VV.v[b].err_x10)
                                  : (unsigned int)VV.v[b].err_x10;
        if ((VV.v[b].state & HCVVT_S_CLOSED) && e > hc_cal_u16(CFG_U_VVT_ERR_MAX)) {
            VV.err_ms[b] = (VV.err_ms[b] > 60000u) ? 60000u
                         : (unsigned int)(VV.err_ms[b] + ms);
            if (VV.err_ms[b] >= hc_cal_u16(CFG_U_VVT_ERR_MS)) {
                VV.fault[b] = VVT_F_SLOW;
            }
        } else {
            VV.err_ms[b] = 0u;
        }
        if (VV.fault[b] != VVT_F_NONE) {
            hcvvt_reset(&VV.v[b]);
            duty = 0u;
        }
    }
    if (u != 0xFFu && !bench) {
        unit_write(u, duty);
    }
    o16((unsigned int)(1112u + 10u * b), (unsigned int)VV.target[b]);
    o16((unsigned int)(1114u + 10u * b), (unsigned int)VV.pos[b]);
    /* the PHYSICAL error (target - position): the core negates its own
       error under invert, which must not reach the tuner's gauge */
    o16((unsigned int)(1116u + 10u * b),
        (unsigned int)(c.invert ? -VV.v[b].err_x10 : VV.v[b].err_x10));
    o16((unsigned int)(1118u + 10u * b), VV.v[b].duty_x10);
    o16((unsigned int)(1120u + 10u * b),
        (unsigned int)(VV.v[b].state | ((unsigned int)VV.fault[b] << 8)
                       | (VV.unit_on[u & 1u] && u != 0xFFu ? 0x8000u : 0u)));
}

void far hc_vvt_service(unsigned int now_ms)
{
    unsigned int ms;
    unsigned char bench;

    VV.acc_ms = (unsigned int)(VV.acc_ms
        + (VV.have_ms ? (unsigned int)(now_ms - VV.last_ms) : 0u));
    VV.last_ms = now_ms;
    VV.have_ms = 1u;
    if (VV.acc_ms < STEP_MS) {
        return;
    }
    ms = VV.acc_ms;
    VV.acc_ms = 0u;
    if (ms > 200u) ms = 200u;
    /* the V82 bench test owns both units while it runs */
    bench = (unsigned char)(hcb_state == HCB_RUNNING && hcb_mode == HC_TEST_VVT);
    step_cam(0u, ms, bench);
    step_cam(1u, ms, bench);
    /* a unit no cam is routed to any more (the route moved while it ran)
       is released - a stale duty must not stay on a pin */
    if (!bench) {
        unsigned char u, pin0 = hc_cal_u8(CFG_U_PIN_CAM1_SOL),
                         pin1 = hc_cal_u8(CFG_U_PIN_CAM2_SOL);
        for (u = 0u; u < 2u; u++) {
            unsigned char cav = u ? 120u : 115u;
            if (VV.unit_on[u] && pin0 != cav && pin1 != cav) {
                unit_write(u, 0u);
            }
        }
    }
}
