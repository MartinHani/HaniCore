/*
 * hcknock711.h - the ME7.1.1 knock driver: CC195 window, gain, sensor
 * select and band, integrator sample, cylinder attribution and the retard
 * handed to the scheduler. The strategy is control/hcknock.c; the hardware
 * chain and its evidence: docs/ARCHITECTURE.md.
 *
 * THE STATE LIVES IN EXTERNAL SRAM (TGT_RAM_KNOCK): the far modules' XRAM is
 * full and near RAM is below its reserve. Three parties share it, each with a
 * fixed role:
 *   - the scheduler (hcsched_dry.c, NCODE) writes geom_* at apply time and
 *     reads slot_ret[] when it stages an ignition event;
 *   - the CC16 ISR (hctrig_me711.c, NCODE) opens and closes the window;
 *   - hcknock711.c (FCODE) does everything else, in the main loop.
 */
#ifndef HCKNOCK711_H
#define HCKNOCK711_H

#include "hcknock.h"

/* window state, ISR <-> task */
#define KN_ST_IDLE    0u
#define KN_ST_ARMED   1u     /* CC16 holds the opening edge           */
#define KN_ST_OPEN    2u     /* MF high, CC16 holds the closing edge  */
#define KN_ST_CLOSED  3u     /* MF low, KI waiting to be sampled      */

/* knockMode */
#define KN_MODE_OFF      0u
#define KN_MODE_MONITOR  1u  /* measure, detect, log - no retard      */
#define KN_MODE_ACTIVE   2u  /* + the retard reaches the spark        */

/* why no window was taken for a cylinder (last reason, OCH) */
#define KN_WHY_OK        0u
#define KN_WHY_OFF       1u  /* knockMode off / page refused           */
#define KN_WHY_SYNC      2u  /* no crank position                      */
#define KN_WHY_RPM       3u  /* below knockRpmMin: nothing to measure  */
#define KN_WHY_LATE      4u  /* the opening edge was already past      */
#define KN_WHY_BUSY      5u  /* previous sample not taken yet          */
#define KN_WHY_ADC       6u  /* AN15 conversion did not complete       */
#define KN_WHY_STALE     7u  /* window never closed (sync lost) - aborted */
#define KN_WHY_CFG       8u  /* hcknock_check() refused the calibration */

typedef struct {
    /* ---- read by the scheduler on every staged ignition event ---- */
    unsigned char slot_ret[9];      /* retard per ignition slot 1..8, 0.1 deg;
                                       [0] = the most any slot has (batch) */
    unsigned char geom_n;           /* cylinders described (<= 8), 0 = none */
    /* ---- written by the scheduler's geometry_refresh() ---- */
    unsigned int  geom_cycle;       /* 7200 / 3600                         */
    unsigned int  geom_tdc[8];      /* engine angle x10 of each TDC        */
    unsigned char geom_slot[8];     /* its ignition slot, 0 = all          */
    /* ---- the scheduler's last tooth (hc_drysched_snap) ---- */
    unsigned int  snap_angle, snap_stamp, snap_dt, snap_tooth;
    unsigned char snap_valid, snap_full;
    /* ---- ISR <-> task ---- */
    unsigned char st;               /* KN_ST_*                             */
    unsigned char cyl;              /* the window's cylinder (0-based)     */
    unsigned int  len_ticks;        /* window length, T7 ticks             */
    unsigned int  t_open, t_close;  /* T7 at the edges (ISR)               */
    unsigned int  t_arm;            /* T7 when armed (stale detection)     */
    /* ---- strategy ---- */
    hcknock_cfg_t cfg;
    hcknock_t     k;
    unsigned int  ikr[8];           /* last integrator value per cylinder  */
    unsigned int  win_start_x10, win_len_x10;  /* in force now          */
    unsigned int  windows, samples, late, busy, adc_fail, stale;
    unsigned char next;             /* cylinder the next arm looks at first */
    unsigned char why;              /* KN_WHY_* of the last attempt        */
    unsigned char sel_code, gain_code;   /* on P3 now                    */
    unsigned char band_code, cfg_err;
    unsigned char mode, pins_owned;
    unsigned int  last_ms;
    unsigned char twin[8];          /* the cylinder 360 deg away, 0xFF none */
    unsigned char have_ms, pad;
    /* the last tooth stamp seen and the main-loop ms it was first
       seen at - a stopped crank is recognised in ms, not by the 16-bit T1
       age (which wraps at 52 ms and would make a stale tooth look new) */
    unsigned int  stamp_seen, stamp_ms;
} hc_kn711_t;

#define HC_KN711 (*(hc_kn711_t huge *)(TGT_EXTRAM_BASE + TGT_RAM_KNOCK))

/* far, main loop only (converts AN15) */
void far hc_knock_init(void);
void far hc_knock_service(unsigned int now_ms);
/* far, main loop AND the serial yield: arms the next window */
void far hc_knock_arm(void);
/* the retard in force, 0.1 deg: the most any cylinder has (telemetry) */
unsigned int far hc_knock_max_x10(void);
/* the latched sensor faults, bit per sensor (0 while knock is Off) */
unsigned char far hc_knock_faults(void);

#endif
