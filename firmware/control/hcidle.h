/*
 * hcidle.h - idle speed control through the electronic throttle (V97,
 * SFR-free, host-tested). The throttle IS the idle actuator on a DBW engine
 * (hcconfig.h, CAL_IDLE_*): this core turns rpm + coolant into a throttle
 * FLOOR; the DBW target becomes max(pedal demand, idle position).
 *
 * rusEFI idle_thread.cpp is the model (SOFTWARE REFERENCE): an open-loop
 * base position by coolant, a PID on the rpm error toward a coolant-based
 * target, closed loop only while idling (pedal released, rpm below target +
 * idlePidRpmUpperLimit), not while cranking or just after (the post-crank
 * taper), with the I term bounded. Here, from the page fields HaniCore
 * already had: idleBaseVal (base, 0.1 % throttle), idleTargetVal (rpm),
 * idleKp / idleKi, idleRangeX10 (the trim authority) and idleRpmBand (the
 * upper limit above target).
 *
 * The I term is HELD, not reset, while the pedal is pressed or the engine
 * coasts down above the band - it is the learned idle air and the engine
 * comes back to it - and reset only when the engine stops or idle control
 * is disabled. A controller that integrated during coast-down would wind
 * the trim to its lower limit and dip the rpm on return (host test).
 *
 * Units: throttle 0.1 % (0..1000); gains x100 per 20 ms step, trim 0.1 %
 * per rpm of error.
 */
#ifndef HCIDLE_H
#define HCIDLE_H

#ifdef __C166__
#define HCIDLE_FAR far
#define HCIDLE_TMEM huge          /* the timing state lives in external SRAM */
#else
#define HCIDLE_FAR
#define HCIDLE_TMEM
#endif

typedef struct {
    unsigned char enabled;
    unsigned int  kp, ki;          /* x100 per step                         */
    unsigned int  range_x10;       /* trim authority, +-                    */
    unsigned int  band_rpm;        /* closed loop only below target + band  */
    unsigned int  pedal_x10;       /* pedal at or below = released          */
    unsigned int  start_ms;        /* after cranking, closed loop waits     */
    /* the DASHPOT (rusEFI iacByTpsTaper / iacByTpsHoldTime /
       iacByTpsDecayTime): after the pedal is released, the floor carries
       dash_x10 extra for dash_hold_ms, then decays it linearly to 0 over
       dash_decay_ms - a slow pedal release that keeps a coasting engine
       from dipping into idle. The trim is HELD meanwhile (state DASH), so
       the loop does not learn the extra air. 0 = off. */
    unsigned int  dash_x10;        /* extra throttle, 0.1 %, <= 20.0 %      */
    unsigned int  dash_hold_ms;
    unsigned int  dash_decay_ms;
} hcidle_cfg_t;

typedef struct {
    unsigned int  rpm;
    unsigned int  target_rpm;      /* from the coolant curve                */
    unsigned int  base_x10;        /* from the coolant curve                */
    unsigned int  pedal_x10;
    unsigned char cranking;
} hcidle_in_t;

#define HCIDLE_S_OFF      0x01u    /* disabled: position 0 (no floor)       */
#define HCIDLE_S_STOPPED  0x02u    /* rpm 0: base only, trim reset          */
#define HCIDLE_S_CRANK    0x04u    /* cranking / post-start wait: base      */
#define HCIDLE_S_PEDAL    0x08u    /* pedal pressed: base + held trim       */
#define HCIDLE_S_COAST    0x10u    /* above target + band: held trim        */
#define HCIDLE_S_CLOSED   0x20u    /* closed loop running                   */
#define HCIDLE_S_LIMIT    0x40u    /* trim at its authority limit           */
#define HCIDLE_S_DASH     0x80u    /* dashpot after a release: held trim    */

typedef struct {
    long          integ100;        /* I, 0.1 % x100                         */
    unsigned int  run_ms;          /* time since cranking ended             */
    unsigned int  pos_x10;         /* the throttle floor                    */
    int           trim_x10;        /* P + I, bounded                        */
    int           p_x10, i_x10;
    unsigned int  last_rpm;        /* the error trend                       */
    unsigned char have_last;
    unsigned char state;
    unsigned int  dash_ms;         /* since the pedal was released; 0xFFFF =
                                      not since the engine started          */
} hcidle_t;

/*
 * IDLE IGNITION TIMING (V97, rusEFI useIdleTimingPidControl /
 * IdleController::getIdleTimingAdjustment): spark reacts within a cycle
 * where the throttle takes a manifold time constant, so while the throttle
 * floor is in CLOSED LOOP a proportional term adds advance below the target
 * and retards above it, bounded to [min, max]; nothing outside closed-loop
 * idle (rusEFI resets it outside Phase::Idling). P ONLY, like rusEFI's
 * default (iFactor 0): a second integrator on the same rpm error would
 * fight the throttle trim's. The soft entry scales the term 0 -> 1 over
 * soft_ms after closed loop begins (rusEFI idleTimingSoftEntryTime).
 * Units: kp_x10 = 0.1 deg per 100 rpm (rusEFI 0.1 deg/rpm = 100); out 0.1 deg.
 */
typedef struct {
    unsigned char enabled;
    unsigned int  kp_x10;          /* 0.1 deg per 100 rpm of error          */
    int           min_x10;         /* most retard, <= 0                     */
    int           max_x10;         /* most advance, >= 0                    */
    unsigned int  soft_ms;         /* 0 = full authority at once            */
} hcidle_tcfg_t;

typedef struct {
    unsigned int  closed_ms;       /* time in closed loop, saturating       */
    int           out_x10;         /* the correction, 0.1 deg (+ = advance) */
} hcidle_timing_t;

void HCIDLE_FAR hcidle_reset(hcidle_t *d);
/* one 20 ms step (ms = elapsed); returns the throttle floor, 0.1 % */
unsigned int HCIDLE_FAR hcidle_step(hcidle_t *d, const hcidle_cfg_t *c,
                                   const hcidle_in_t *in, unsigned int ms);
/* after hcidle_step(): closed = (state & HCIDLE_S_CLOSED); returns out_x10 */
int HCIDLE_FAR hcidle_timing_step(hcidle_timing_t HCIDLE_TMEM *t,
                                  const hcidle_tcfg_t *c, unsigned char closed,
                                  unsigned int rpm, unsigned int target_rpm,
                                  unsigned int ms);

#endif
