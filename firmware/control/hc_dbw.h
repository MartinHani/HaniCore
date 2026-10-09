/*
 * hc_dbw.h - the electronic throttle, pedal to plate, target independent.
 *
 * THE DIVISION OF OWNERSHIP, and it is the whole reason this file is in
 * shared/ rather than in a target directory:
 *
 *   THE TARGET HAL OWNS   the H-bridge itself. Which pins, which PWM unit,
 *                         what EGENFR and SF are, how a duty reaches silicon.
 *                         On ME7.1.1 that is S8100 with DVE1 on P7.2/POUT2,
 *                         DVE2 on P7.7, EGENFR on P2.11, SF on P3.15 and the
 *                         motor at connector cavities 117/118 - every one of
 *                         those numbers from hctarget.h and none from here.
 *
 *   THE PAGE OWNS         the throttle body. APP and TPS calibration, the
 *                         track relationship, motor direction, travel limits,
 *                         controller gains, plausibility tolerances, output
 *                         authority, rate limit, deadband.
 *
 * That split is not tidiness. The 4B0906018DC hcdbw.c declares
 * `sbit SF_PIN = P2 ^ 9`, and on ME7.1.1 P2.9 is NWDG2 - the second cam
 * input. A DBW module that reaches for a pin cannot be moved between boards
 * without driving something else's hardware. This one never names a pin.
 *
 * THE FIRST PHYSICAL THROTTLE BODY IS A VAG 1.8T UNIT. Nothing here is
 * calibrated for it, and no constant in this file was invented to make it
 * look ready. Every throttle-specific number is a page value with a
 * documented meaning and a bench procedure that produces it.
 *
 * ==================================================== THE CHAIN ===========
 *
 *   APP1, APP2 raw counts        hc_hal_ain(HC_AIN_APP1 / APP2)
 *     -> per-track calibration   CAL_PEDAL1_MIN/MAX, CAL_PEDAL2_MIN/MAX
 *     -> normalised 0..1000      0.1 % of pedal travel
 *     -> pair plausibility       CFG_U_APP_CORR, CFG_U_APP_TOL_X10
 *     -> driver demand
 *     -> throttle target         CAL_PEDAL_MAP over (rpm, pedal)
 *     -> travel limits           CAL_DBW_MIN_X10, CAL_DBW_MAX_X10
 *     -> rate limit              CFG_U_DBW_RATE_X10
 *
 *   TPS1, TPS2 raw counts        hc_hal_ain(HC_AIN_TPS1 / TPS2)
 *     -> per-track calibration   CAL_TPS1_MIN/MAX, CAL_TPS2_MIN/MAX
 *     -> normalised 0..1000
 *     -> pair plausibility       CFG_U_TPS_CORR, CFG_U_TPS_TOL_X10
 *     -> actual position
 *
 *   error = target - actual
 *     -> deadband                CFG_U_DBW_DEADBAND_X10
 *     -> PID, fixed point        CAL_DBW_KP / KI / KD, anti-windup
 *     -> feed-forward bias       CAL_DBW_BIAS_AX / CAL_DBW_BIAS_VAL
 *     -> authority clamp         CFG_U_DBW_MAX_DUTY_X10
 *     -> direction               CFG_U_DBW_MOTOR_DIR
 *     -> hc_hal_out_duty(HC_OUT_THR_PWM), hc_hal_out(HC_OUT_THR_DIR/EN)
 *
 *   supervision, every step      SF, deviation-for-a-duration, sensor
 *                                availability, calibration validity
 *
 * ================================================== THE SAFETY RULES ======
 *
 * 1. THE BRIDGE IS DISABLED UNLESS EVERYTHING IS RIGHT. `hc_dbw_service()`
 *    re-evaluates every precondition on every step and drops EGENFR on the
 *    first failure. There is no "it was fine when we started".
 * 2. A FAULT LATCHES. Only hc_dbw_init() clears it. A throttle that
 *    re-enables itself because a sensor glitch cleared is worse than one that
 *    stays limp until somebody looks.
 * 3. THE INTEGRATOR IS ZERO WHENEVER THE BRIDGE IS NOT DRIVING. Not frozen -
 *    zero. An integrator that accumulated while disabled would hand the motor
 *    a step the moment it was enabled.
 * 4. AUTHORITY IS BOUNDED BY THE PAGE, AND THE PAGE IS BOUNDED BY THE MODEL.
 *    CFG_U_DBW_MAX_DUTY_X10 cannot exceed 1000 (100 %) and the code clamps
 *    again anyway.
 * 5. ED_RST CAN DISABLE THE BRIDGE WITHOUT US. On ME7.1.1 the monitoring
 *    module reaches S8100's DI2 directly. "Commanded and did not move, with
 *    SF clean" is a legitimate platform veto, and the deviation supervisor
 *    reports it as DBW_F_DEV rather than trying harder.
 * 6. hc_hal_outputs_live() IS CHECKED HERE TOO. Defence in depth: the HAL
 *    already refuses, and this module refuses as well.
 */
#ifndef HC_DBW_H
#define HC_DBW_H

/* --------------------------------------------------------------- states -- */
#define DBW_OFF        0u   /* CAL_DBW_ENABLE is 0, or outputs are not live  */
#define DBW_INIT       1u   /* enabled; waiting for plausible sensors        */
#define DBW_RUN        2u   /* closed loop, bridge enabled                   */
#define DBW_FAULT      3u   /* latched; bridge disabled until init()         */

/* --------------------------------------------------------------- faults -- */
#define DBW_F_CFG        0x0001u  /* calibration does not describe a throttle */
#define DBW_F_APP_PAIR   0x0002u  /* the two pedal tracks disagree            */
#define DBW_F_TPS_PAIR   0x0004u  /* the two throttle tracks disagree         */
#define DBW_F_APP_RANGE  0x0008u  /* a pedal track is outside its calibration */
#define DBW_F_TPS_RANGE  0x0010u  /* a throttle track is outside its own      */
#define DBW_F_SF         0x0020u  /* the bridge asserted its fault pin        */
#define DBW_F_DEV        0x0040u  /* off target beyond the window, for too long */
#define DBW_F_STALE      0x0080u  /* the HAL has no backing source for a track */
#define DBW_F_VBAT       0x0200u  /* missing/stale/implausible motor supply */
#define DBW_F_NOTLIVE    0x0100u  /* hc_hal_outputs_live() is 0               */
/* DBW_F_CFG is a LIVE refusal (the page does not describe a throttle
   yet), not a latched fault: it clears the step the page is fixed. Every
   other bit latches until hc_dbw_init() or hc_dbw_clear_faults(). */

/* what hc_dbw_term() publishes (telemetry, signed where noted) */
#define DBW_T_CONTROL_MS 9u   /* last control service tick, wraps at 65536 */
#define DBW_T_P          0u   /* proportional term, 0.1 % duty, signed     */
#define DBW_T_D          1u   /* derivative term, 0.1 % duty, signed       */
#define DBW_T_FF         2u   /* bias-curve feed-forward, 0.1 %, signed    */
#define DBW_T_OUT        3u   /* PID + FF before battery compensation      */
#define DBW_T_VFAC       4u   /* battery factor x1000 (13.5 V / Ubatt)     */
#define DBW_T_PEND       5u   /* sensor fault bits being debounced         */
#define DBW_T_PEND_MS    6u   /* how long they have been pending, ms       */
#define DBW_T_OVR        7u   /* commissioning target override, 0xFFFF none */
#define DBW_T_CLEARS     8u   /* latched faults cleared (key-on / commission) */

void hc_dbw_init(void);

/*
 * Once per main-loop pass, with the millisecond tick and the engine speed.
 * Runs its control law on a FIXED raster (DBW_STEP_MS) regardless of how
 * often it is called, because a gain tuned against a variable loop rate
 * changes whenever anything else in the loop changes.
 *
 * `armed` is the caller's deliberate permission - on this build that is the
 * bench qualifier, not the engine runtime. Passing 0 commands the safe state
 * and is always honoured immediately.
 *
 * Never blocks, never allocates, bounded in every path.
 */
void hc_dbw_service(unsigned int now_ms, unsigned int rpm, unsigned char armed);

/* Force the safe state now: duty 0, direction cleared, bridge disabled,
   integrator zeroed. Safe from any state, including OFF. */
void hc_dbw_shutdown(unsigned int fault_bits);

/* -------------------------------------------------- published telemetry -- */
unsigned char hc_dbw_state(void);
unsigned int  hc_dbw_faults(void);       /* DBW_F_*, latched                  */
unsigned int  hc_dbw_target_x10(void);   /* 0..1000, 0.1 % of travel          */
unsigned int  hc_dbw_actual_x10(void);   /* 0..1000                           */
int           hc_dbw_error_x10(void);    /* target - actual, after deadband   */
unsigned int  hc_dbw_duty_x10(void);     /* what was asked of the bridge      */
unsigned char hc_dbw_dir(void);          /* the direction leg as commanded    */
unsigned char hc_dbw_bridge_on(void);    /* EGENFR as commanded               */
unsigned int  hc_dbw_pedal_x10(void);    /* normalised driver demand          */
unsigned int  hc_dbw_app1_x10(void);
unsigned int  hc_dbw_app2_x10(void);
unsigned int  hc_dbw_tps1_x10(void);
unsigned int  hc_dbw_tps2_x10(void);
int           hc_dbw_integ(void);        /* the integrator, for tuning        */
unsigned int  hc_dbw_steps(void);        /* control steps executed, ever      */
/* Nonzero when a control step is due (DBW_STEP_MS since the
   last one) - the main loop polls DBW at every service boundary with it,
   so the raster does not stretch to a whole main-loop pass. */
unsigned char hc_dbw_due(unsigned int now_ms);
unsigned int  hc_dbw_gap_max(void);      /* largest RUN step interval, ms    */
unsigned int  hc_dbw_term(unsigned char i);  /* DBW_T_* telemetry        */
/* CLEAR THE LATCHED FAULTS - a new driving cycle (key on with the engine
   stopped: Bosch heals DV-E faults per driving cycle) or a commissioning run
   that just produced a valid calibration. The bridge stays down; the next
   service passes through DBW_INIT's settle as after boot. */
void          hc_dbw_clear_faults(void);
/* once per main-loop pass - a key-on edge with the engine stopped is a
   new driving cycle and clears the latched faults (hc_dbw_clear_faults). */
void          hc_dbw_key(unsigned char key_on, unsigned int rpm);
/* THE COMMISSIONING VERIFY STEP drives the CLOSED LOOP to a scripted
   target with the page's gains: 0..1000 = target (no pedal, no idle floor, no
   rate limit, dbwEnable not required), 0xFFFF = off. Engine stopped only -
   hcetbcal.c owns the procedure and ends it on every exit. */
/* Private characterization only: 0x8000 | normalized APP demand routes
   through the production map/floors/limits/rate limiter, still pedal-free. */
void          hc_dbw_override(unsigned int target_x10);
/* the ETB endpoint calibration and PID autotune live in the target's
   far module (ME7.1.1: hcetbcal.c). It borrows the bridge through these:
   hc_dbw_drive() = enable + direction + duty (held, so hc_dbw_shutdown()
   releases it); hc_dbw_gains() = rusEFI's relay rule in page units,
   k[3] = KP, KI, KD, from the amplitude (0.1 %) and period (ms). */
void hc_dbw_calibration_begin(unsigned int now_ms);
void          hc_dbw_drive(unsigned char dir, unsigned int duty);
unsigned char hc_dbw_gains(unsigned int a_x10, unsigned int tu_ms,
                           unsigned int *k);   /* mask of gains clipped */

/* Normalise one raw count against a calibrated pair. Exposed because the
   bench qualifier and the gates use exactly the same arithmetic the
   controller does - a test that re-implements the thing it tests, tests
   nothing. Returns 0..1000; `ok` receives 0 if the calibration is unusable
   or the reading is outside it by more than the margin. */
unsigned int hc_dbw_normalise(unsigned int raw, unsigned int lo,
                              unsigned int hi, unsigned char *ok);

#endif /* HC_DBW_H */
