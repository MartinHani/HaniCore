/*
 * hcldr.h - boost control (Bosch "LDR") decision core (V97, SFR-free,
 * host-tested). The target looks up the tables (open-loop duty with its
 * temperature multipliers, closed-loop target) and drives the valve; this
 * core decides what the valve gets and whether fuel must be cut.
 *
 * rusEFI boost_control.cpp is the model (SOFTWARE REFERENCE): open loop +
 * closed-loop PID on manifold pressure, closed loop only above
 * minimumBoostClosedLoopMap, PID reset whenever it is not running; overboost
 * is rusEFI's boostCutPressure (+hysteresis) in the limp manager - a FUEL
 * cut, independent of whether boost control is enabled (a stuck wastegate
 * overboosts with the valve unpowered).
 *
 * Where HaniCore differs, and why:
 *  - a pressure sensor that is not valid gives duty 0 in BOTH modes (rusEFI
 *    keeps open loop): a MAP fault reads 0 kPa (V97; 100 kPa before), and a
 *    closed loop fed a fault value would drive the wastegate shut;
 *  - the integrator does not run while the pressure is more than i_band
 *    BELOW target (above target it always may: down is the safe way), and
 *    never further into a saturated output. Conditional integration alone is not enough:
 *    while P saturates the output against a target the turbo cannot reach
 *    yet, I parks at (100 % - open - P) and overshoots on spool (the host
 *    test measured +15..19 kPa). Bosch bounds the I part (LDIMX) and rusEFI has
 *    iTermMin/Max for the same reason; a band is independent of rpm;
 *  - D acts on the measurement, not the error (no kick on a target step).
 *
 * Units: pressure 0.1 kPa absolute; duty 0.1 % (0..1000); gains are the
 * page's, x100 per 20 ms step (duty x10 per 0.1 kPa of error).
 */
#ifndef HCLDR_H
#define HCLDR_H

#ifdef __C166__
#define HCLDR_FAR far
#else
#define HCLDR_FAR
#endif

#define HCLDR_CUT_DEFAULT_X10   2200u   /* a page of zeros still protects */
#define HCLDR_HYST_DEFAULT_X10   150u
#define HCLDR_DUTY_MAX          1000u

typedef struct {
    unsigned char closed;          /* 0 open loop, 1 closed loop            */
    unsigned int  min_rpm;
    unsigned int  min_tps_x10;
    unsigned int  cl_min_map_x10;  /* closed loop only at/above this        */
    unsigned int  kp, ki, kd;      /* x100 per step                         */
    unsigned int  i_band_x10;      /* I does not integrate while the pressure
                                      is more than this BELOW target; 0 =
                                      always integrates                      */
    unsigned int  cut_x10;         /* overboost; 0 -> the default           */
    unsigned int  hyst_x10;        /* 0 -> the default; >= cut -> cut - 1   */
} hcldr_cfg_t;

typedef struct {
    unsigned int  rpm;
    unsigned int  tps_x10;
    unsigned int  map_x10;
    unsigned char map_ok;          /* the pressure is a MEASUREMENT         */
    unsigned char enabled;         /* boost control enabled on the page     */
    unsigned char keyoff;          /* the controlled key-off is running     */
    unsigned int  open_x10;        /* open-loop duty incl. temperature      */
    unsigned int  target_x10;      /* closed-loop target                    */
} hcldr_in_t;

#define HCLDR_S_CUT      0x01u     /* overboost: valve 0, fuel cut          */
#define HCLDR_S_SENSOR   0x02u     /* no valid pressure: valve 0            */
#define HCLDR_S_OFF      0x04u     /* disabled or key-off                   */
#define HCLDR_S_BELOW    0x08u     /* below the rpm/throttle floor          */
#define HCLDR_S_OPEN     0x10u     /* open loop (or closed below its map)   */
#define HCLDR_S_CLOSED   0x20u     /* closed loop running                   */
#define HCLDR_S_SAT      0x40u     /* output saturated (0 or 100 %)         */

typedef struct {
    long          integ100;        /* I term, duty x10 x100                 */
    unsigned int  last_map;
    unsigned char have_last;
    unsigned char cut;             /* latched overboost                     */
    unsigned char state;
    unsigned int  duty_x10;
    int           p_x10, i_x10, d_x10;   /* telemetry: the closed-loop parts */
    unsigned int  cuts;            /* overboost events, wrapping            */
} hcldr_t;

void HCLDR_FAR hcldr_reset(hcldr_t *b);
/* one 20 ms control step; returns the valve duty (0..1000). b->cut is the
   fuel-cut request, b->state the reason. */
unsigned int HCLDR_FAR hcldr_step(hcldr_t *b, const hcldr_cfg_t *c, const hcldr_in_t *in);

#endif
