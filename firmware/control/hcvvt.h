/*
 * hcvvt.h - camshaft phase control (VVT) core, one cam (V97, SFR-free,
 * host-tested). The target supplies the target (from its rpm x load table)
 * and the measured cam position (the cam PATTERN core's tooth-0 deviation,
 * hccam sync_dev_x10); this core returns the solenoid duty.
 *
 * rusEFI vvt.cpp is the model (SOFTWARE REFERENCE): enabled above
 * vvtControlMinRpm and vvtControlMinClt after vvtActivationDelayMs;
 * closed-loop PID on the cam position toward the target; an INVALID position
 * gives duty 0 and resets the PID; invertVvtControl flips the error. Two
 * HaniCore additions:
 *  - SWITCH mode, for the on/off cam adjusters that need no position (the
 *    1.8T 20V's intake chain tensioner): the target table holds 0 / >0 and
 *    the solenoid is off / fully on - rusEFI would run that through its PID;
 *  - the integrator does not integrate into a saturated output
 *    (conditional integration - the controllers in hcldr.c and hcidle.c
 *    have the same rule and the same reason).
 *
 * Units: angle 0.1 deg crank, duty 0.1 % (0..1000), gains x100 per 20 ms
 * step (duty x10 per 0.1 deg of error).
 */
#ifndef HCVVT_H
#define HCVVT_H

#ifdef __C166__
#define HCVVT_FAR far
#define HCVVT_MEM huge        /* the state lives in external SRAM */
#else
#define HCVVT_FAR
#define HCVVT_MEM
#endif

#define HCVVT_MODE_OFF     0u
#define HCVVT_MODE_SWITCH  1u
#define HCVVT_MODE_CLOSED  2u

typedef struct {
    unsigned char mode;
    unsigned char invert;          /* the phaser moves AGAINST the duty     */
    unsigned int  min_rpm;
    int           min_clt_c;       /* deg C                                 */
    unsigned int  delay_ms;        /* running this long first               */
    unsigned int  kp, ki, kd;      /* x100 per step                         */
    unsigned int  duty_min_x10;    /* closed loop output range              */
    unsigned int  duty_max_x10;
    unsigned int  duty_on_x10;     /* SWITCH mode: the ON duty              */
} hcvvt_cfg_t;

typedef struct {
    unsigned int  rpm;
    int           clt_c;
    int           target_x10;      /* deg; SWITCH: > 0 = on                 */
    int           pos_x10;         /* deg, the measured cam position        */
    unsigned char pos_ok;          /* the position is a measurement         */
} hcvvt_in_t;

#define HCVVT_S_OFF      0x01u     /* mode off                              */
#define HCVVT_S_WAIT     0x02u     /* rpm / coolant / delay not met         */
#define HCVVT_S_NOPOS    0x04u     /* closed loop without a position: 0     */
#define HCVVT_S_SWITCH   0x08u
#define HCVVT_S_CLOSED   0x10u
#define HCVVT_S_SAT      0x20u

typedef struct {
    long          integ100;
    int           last_pos;
    unsigned char have_last;
    unsigned char state;
    unsigned int  run_ms;
    unsigned int  duty_x10;
    int           err_x10;
} hcvvt_t;

void HCVVT_FAR hcvvt_reset(hcvvt_t HCVVT_MEM *v);
unsigned int HCVVT_FAR hcvvt_step(hcvvt_t HCVVT_MEM *v, const hcvvt_cfg_t *c,
                                  const hcvvt_in_t *in, unsigned int ms);

#endif
