/*
 * hcetbcal.h - ETB endpoint calibration ('!C1') and PID relay autotune
 * ('!C2'), V93. FAR code (FCODE): the procedures run only while a tuner asks
 * for them, so they do not belong in the 64 KiB near group.
 *
 * hc_dbw.c owns the bridge and the closed loop; this module borrows the
 * bridge through hc_dbw_drive()/hc_dbw_shutdown() while a procedure runs and
 * hc_dbw_service() executes nothing else meanwhile. Every exit releases.
 */
#ifndef HCETBCAL_H
#define HCETBCAL_H

/* Results (status bits 0..3). */
#define ETB_RES_NONE     0u
#define ETB_RES_RUN      1u
#define ETB_RES_PASS     2u      /* endpoints written to RAM, Burn to keep   */
#define ETB_RES_FAIL     3u
#define ETB_RES_TUNED    4u      /* PID written to RAM, Burn to keep         */
#define ETB_RES_COMMISSIONED 5u  /* '!C3': endpoints AND PID written to RAM  */
#define ETB_RES_CAPTURED     6u      /* V99 '!C4'/'!C5': bounded position captured */

/* Phases (status bits 4..7). */
#define ETB_CAL_SWEEP    12u
#define ETB_CAL_SLAM     13u
#define ETB_CAL_FRICTION 14u      /* characterization: break-away edges */
#define ETB_PROC_SWEEP    6u
#define ETB_RES_CHARACTERIZED 7u
#define ETBV_SWEEP_DUTY 30u
#define ETBV_SWEEP_FLAGS 31u
#define ETBV_SWEEP_RMS 32u
#define ETBV_SWEEP_SAT 33u

#define ETB_CAL_IDLE     0u
#define ETB_CAL_REST     1u      /* reading the unpowered (limp) rest        */
#define ETB_CAL_DRIVE_A  2u      /* direction A at the autocal duty          */
#define ETB_CAL_BACK_A   3u      /* released, the spring returns it          */
#define ETB_CAL_DRIVE_B  4u
#define ETB_CAL_BACK_B   5u
#define ETB_CAL_TUNE     6u      /* autotune: relay around 50 %              */
#define ETB_CAL_PUSH_A   7u      /* reserved legacy phase, not entered V101 */
#define ETB_CAL_PUSH_B   8u      /* reserved legacy phase, not entered V101 */
#define ETB_CAL_APPROACH 9u      /* autotune: bringing the plate to 50 %     */
#define ETB_CAL_TUNE_REST 11u    /* motor OFF, fresh settled TPS before PID */
#define ETB_CAL_VERIFY  10u      /* V97 commission: closed-loop step response */

/* Why it stopped (status bits 8..15). */
#define ETB_WHY_NONE        0u
#define ETB_WHY_TURNING     1u   /* the engine turned                        */
#define ETB_WHY_NOTLIVE     2u   /* outputs not permitted                    */
#define ETB_WHY_SF          3u   /* the CJ220 flagged a fault                */
#define ETB_WHY_RAIL        4u   /* a TPS track at a rail                    */
#define ETB_WHY_NOMOVE_A    5u   /* direction A did not move the plate       */
#define ETB_WHY_NOMOVE_B    6u
#define ETB_WHY_SPAN        7u   /* closed-open span < 100 counts on a track */
#define ETB_WHY_TIMEOUT     8u
#define ETB_WHY_RUNNING     9u   /* closed-loop DBW is running               */
#define ETB_WHY_ABORTED    10u
#define ETB_WHY_NOTPS      11u   /* no configured TPS input source                 */
#define ETB_WHY_UNCAL      12u   /* autotune: TPS 1 not calibrated           */
#define ETB_WHY_BAND       13u   /* autotune: plate left 20..80 %            */
#define ETB_WHY_NOTSTOP_A  14u   /* legacy reason, not emitted V101         */
#define ETB_WHY_NOTSTOP_B  15u   /* legacy reason, not emitted V101         */
#define ETB_WHY_REST       16u   /* the rest position is not between the ends*/
#define ETB_WHY_TRACKS     17u   /* track 2 does not follow track 1          */
#define ETB_WHY_UNREACHED  18u   /* autotune: never reached 50 %             */
#define ETB_WHY_IMPLAUS    19u   /* autotune: amplitude/period implausible   */
#define ETB_WHY_NOENDPTS   20u   /* autotune only: no valid stored endpoints */
#define ETB_WHY_V_SLOW     21u   /* verify: a step did not settle in time    */
#define ETB_WHY_V_OVER     22u   /* verify: a step overshot                  */
#define ETB_WHY_V_ERROR    23u   /* verify: steady-state error too large     */
#define ETB_WHY_V_FAULT    24u   /* verify: the closed loop latched a fault  */
#define ETB_WHY_UNSETTLED  25u   /* legacy reason, not emitted V101         */
/* The procedure a request started (etbProc bits 0..3). */
#define ETB_PROC_NONE      0u
#define ETB_PROC_AUTOCAL   1u    /* '!C1' endpoint calibration only          */
#define ETB_PROC_AUTOTUNE  2u    /* '!C2' PID autotune only                  */
#define ETB_PROC_COMMISSION 3u   /* '!C3' AutoCal -> validate -> autotune    */
#define ETB_PROC_DIR_A     4u    /* '!C4' bounded direction-A capture       */
#define ETB_PROC_DIR_B     5u    /* '!C5' bounded direction-B capture       */

unsigned char far hc_etbcal_tps_pair_fault(void);
unsigned char far hc_etbcal_pair_bad(unsigned int a, unsigned int b, unsigned char corr, unsigned int tol_x10);
unsigned int far hc_etbcal_control_term(unsigned char i);
unsigned int far hc_etbcal_rail_faults(unsigned char override);
unsigned int far hc_etbcal_config_faults(unsigned char override);
void          far hc_etbcal_init(void);
/* Serial-yield safety cancellation; no control step or new actuation. */
unsigned char far hc_etbcal_supervise(unsigned char why);
/* One call per main-loop pass from hc_dbw_service(). Returns 1 while a
   procedure owns the bridge (the controller must do nothing this pass). */
unsigned char far hc_etbcal_service(unsigned int now_ms, unsigned int rpm,
                                    unsigned char armed,
                                    unsigned char dbw_running);
/* 0 abort, 1 endpoint calibration, 2 PID autotune, 3 commission (both),
   4 / 5 drive direction A / B to its stop and report where. */
void          far hc_etbcal_request(unsigned char what);
/* bits 0..3 ETB_PROC_*, bits 4..7 the phase it FAILED in (0 none),
   bit 8 the endpoint calibration passed in this run (and was handed to the
   page), bit 9 the run ended by an operator abort. */
unsigned int  far hc_etbcal_proc(void);
/* bits 0..3 ETB_RES_*, 4..7 ETB_CAL_*, 8..15 ETB_WHY_* */
unsigned int  far hc_etbcal_status(void);
/* An unclaimed endpoint PASS, once: tps1 closed, tps1 open, tps2 closed,
   tps2 open, motor direction (0 = leg 0 opens). */
unsigned char far hc_etbcal_take(unsigned int *r);
/* An unclaimed autotune result, once: KP, KI, KD in page units. */
unsigned char far hc_etbcal_tune_take(unsigned int *k);
#define ETB_WHY_STALE      26u   /* qualified TPS sample exceeded 100 ms */
#define ETB_WHY_ADC        27u   /* rejected ADC completion/channel tag */
#define ETB_WHY_ALIGN      28u   /* no bracketed common sample time */
#define ETB_WHY_CONTROL    29u   /* calibration/control raster missed */
#define ETB_WHY_NOSAMPLE   30u   /* routed source never completed */
#define ETB_WHY_REPEAT     31u   /* autotune: two measurements disagree > 25 % */
/* Telemetry, see hcetbcal.c ETBV_* */
unsigned int  far hc_etbcal_value(unsigned char i);

#define ETBV_REST1     0u
#define ETBV_A1        1u
#define ETBV_B1        2u
#define ETBV_A2        3u
#define ETBV_B2        4u
#define ETBV_REST2     5u
#define ETBV_AMP       6u    /* autotune: averaged amplitude, 0.1 %       */
#define ETBV_TU        7u    /* autotune: averaged period, ms             */
#define ETBV_DETAIL    8u    /* failure detail; no physical stop verdict  */
#define ETBV_CYCLES    9u    /* autotune: relay cycles completed          */
#define ETBV_KP       10u    /* autotune: candidate (then final) gains    */
#define ETBV_KI       11u
#define ETBV_KD       12u
#define ETBV_AMP_LIVE 13u    /* autotune: last cycle's amplitude, 0.1 %   */
#define ETBV_TU_LIVE  14u    /* autotune: last cycle's period, ms         */
#define ETBV_DRIVE    15u    /* bit15 driving, bit14 direction, duty x10  */
#define ETBV_PHASE_MS 16u    /* ms in the current phase                    */
#define ETBV_V_SETTLE 17u    /* verify: worst settle time to +/-2 %, ms   */
#define ETBV_V_OVER   18u    /* verify: worst overshoot, 0.1 %            */
#define ETBV_V_ERR    19u    /* verify: worst steady error, 0.1 %         */
#define ETBV_V_STEP   20u    /* verify: step reached (1..5), bit 8 = done */
/* Captured position telemetry. Former push verdict slots are reserved zero. */
#define ETBV_HOLD1    21u    /* 40 ms mean at the end of the hold         */
#define ETBV_PUSH1    22u    /* TPS1 age at last step/failure, ms                     */
#define ETBV_LIMIT    23u    /* TPS2 age at last step/failure, ms                     */
#define ETBV_MOVED    24u    /* TPS qualification: track1 low / track2 high nibble                     */
#define ETBV_HOLD_MS  25u    /* actual bounded capture duration, ms       */
#define ETBV_DISP     26u    /* |hold - rest|, counts                     */
/* Diagnostic raw AN2: expected amplification and clipping, never a divisor. */
#define ETBV_IPV      27u    /* amplified TPS1 / IPV, ADC ch 2 */
#define ETBV_RAW1     28u    /* TPS1 raw, uncorrected                      */
#define ETBV_RAW2     29u    /* TPS2 raw, uncorrected                      */

unsigned int far hc_etbcal_u16(unsigned int field);
void far hc_etbcal_bias_service(unsigned int now);
int far hc_etbcal_friction(int err);
int far hc_etbcal_derivative(unsigned int sample_ms, unsigned char entry,
                             unsigned int gain);
/* The Bosch DLR setting-range monitor, one control step (hc_dbw.c). */
unsigned int far hc_etbcal_dlr_monitor(unsigned char saturated,
                                       unsigned char sf, unsigned int step_ms);
void far hc_etbcal_dlr_reset(void);
unsigned char far hc_etbcal_dlr_ska(void);
unsigned char far hc_etbcal_burn_hold(void);
void far hc_etbcal_dbw_init(void);


#endif
