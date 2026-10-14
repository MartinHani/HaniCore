/*
 * hcengctl711.h - the V98 engine-control layer on ME7.1.1 (FAR, FCODE).
 *
 * What hcengine.c computes from the sensors (air, base fuel, base spark) is
 * turned here into what a mature standalone ECU does with it, each piece
 * after its rusEFI runtime counterpart (docs/ARCHITECTURE.md):
 *
 *   firing order -> TDC geometry           firing_order.cpp
 *   control value of a FAILED sensor       Sensor::get(..).value_or() per
 *     (the displayed value stays -40 C /   consumer, never one shared value
 *      0 kPa)
 *   MAP estimate on a MAP fault            speed_density_airmass.cpp getMap
 *   target lambda, own axes                fuel_computer.cpp getTargetLambda
 *   table load overrides                   fuel_computer.cpp getLoadOverride
 *   DFCO                                   dfco.cpp
 *   closed-loop fuel (STFT)                closed_loop_fuel.cpp
 *   rev limit (hard/soft, pit)             limp_manager.cpp updateRevLimit
 *   launch, flat shift, anti-lag,          launch_control.cpp,
 *     rotational idle                      shift_torque_reduction_controller,
 *                                          antilag_system.cpp
 *   priming pulse                          prime_injection.cpp
 *   injection phase table                  fuel_math.cpp getInjectionOffset
 *
 * Far, MEDIUM, DEFINE(HC_FAR_BRIDGE): page reads through hcfarinline.h, near
 * helpers through hcfar_me711.c thunks, no Keil ?C_ helper (16x16 products,
 * 32/16 divisions with a bounded quotient). State in external SRAM
 * (TGT_RAM_ENGCTL): the on-chip XRAM the far modules use is full.
 */
#ifndef HCENGCTL711_H
#define HCENGCTL711_H

/* ---- engine status flags (OCH engineFlags) - TunerStudio's Tune Analyze
   filters and the logger read these; bit numbers are a wire contract. */
#define EC_F_RUNNING    0x0001u
#define EC_F_CRANKING   0x0002u
#define EC_F_ASE        0x0004u   /* after-start enrichment active         */
#define EC_F_WARMUP     0x0008u   /* warm-up enrichment != 100 %           */
#define EC_F_TRANSIENT  0x0010u   /* acceleration / wall-film correction   */
#define EC_F_DFCO       0x0020u   /* deceleration fuel cut                 */
#define EC_F_LAM1_OK    0x0040u
#define EC_F_LAM2_OK    0x0080u
#define EC_F_STFT       0x0100u   /* closed-loop fuel correcting           */
#define EC_F_FUELCUT    0x0200u   /* any fuel cut (rev, boost, limp, DFCO) */
#define EC_F_LAUNCH     0x0400u
#define EC_F_FLATSHIFT  0x0800u
#define EC_F_ALS        0x1000u
#define EC_F_REVLIM     0x2000u   /* hard or soft rev limit acting         */
#define EC_F_MAPEST     0x4000u   /* fuel is using the MAP estimate        */
#define EC_F_VETUNE     0x8000u   /* VE table written in the last 20 s     */

/* STFT state (OCH stftState low byte), rusEFI stft_state_e in spirit */
#define EC_STFT_OFF        0u   /* disabled in settings                 */
#define EC_STFT_RPM        1u   /* not running                          */
#define EC_STFT_DELAY      2u   /* startup delay                        */
#define EC_STFT_CLT        3u   /* coolant too cold or sensor failed    */
#define EC_STFT_LAMBDA     4u   /* no valid lambda / out of range       */
#define EC_STFT_DFCO       5u   /* hold after a fuel cut                */
#define EC_STFT_AE         6u   /* hold after acceleration enrichment   */
#define EC_STFT_CUT        7u   /* hold after any other cut             */
#define EC_STFT_ACTIVE     8u   /* learning                             */
#define EC_STFT_VETUNE     9u   /* VE table being written (Tune Analyze) */
#define EC_STFT_DYN       10u   /* reserved legacy activity hold, not emitted */

typedef struct {
    unsigned int t_last, t_rem;     /* T1 time base                       */
    unsigned int ms;                /* this module's millisecond clock    */
    unsigned int dt_ms;             /* this pass                          */
    unsigned int run_ms;            /* time running (saturates)           */
    unsigned int flags;             /* EC_F_*                              */
    /* DFCO */
    unsigned char dfco, dfco_cond;
    unsigned int dfco_cond_ms;      /* conditions held this long          */
    unsigned int since_dfco_ms;     /* since the last cut ended           */
    unsigned int since_cut_ms;      /* since any fuel cut                  */
    unsigned int since_ae_ms;       /* since acceleration enrichment       */
    /* STFT */
    int stft_pm[2];                 /* per mille fuel trim per bank       */
    int stft_acc[2];                /* integrator remainder                */
    unsigned char stft_state, stft_region;
    unsigned int stft_bad_ms[2];    /* sensor not valid this long          */
    /* rev limit and motorsport */
    unsigned int rev_limit, rev_hyst;
    unsigned char skip;             /* spark skip ratio, 0..255            */
    unsigned char launch, flat, als, rot, pit;
    unsigned char sw_last;          /* switch levels last pass (bits)     */
    unsigned int flat_ms, als_ms;
    int spark_last;                 /* the advance-rate limiter            */
    unsigned int fuel_pm;           /* fuel multiplier, per mille          */
    unsigned int map_ctrl_x10;      /* pressure the fuel uses              */
    unsigned int lambda_x1000;      /* target                              */
    unsigned int ign_load, lam_load;
    unsigned int ve_tune_ms;        /* since the last VE write             */
    /* priming */
    unsigned char prime_st, prime_pad;
    unsigned int prime_ms;
    unsigned int prime_magic, prime_count;   /* key cycles since a run    */
    unsigned char sw_db[4];         /* per-function debounce, ms    */
    unsigned int sw_raw;            /* raw input levels, switchRaw  */
    unsigned int sw_raw_ms;         /* its refresh clock                    */
    /* the Bosch intake-manifold filling model (hc_ec_load_lag()) */
    unsigned int lag_x16;           /* filled load, 0.1 % x 16              */
    unsigned int lag_ms;            /* its clock                            */
    unsigned char lag_ok, lag_pad;
} hc_ec_t;

#define HC_EC (*(hc_ec_t huge *)(TGT_EXTRAM_BASE + TGT_RAM_ENGCTL))

void          far hc_ec_init(void);

/* Position (0-based) of cylinder `cyl` (0-based) in firing order `order`,
   0xFF when the order is unknown or its length is not `ncyl`. */
unsigned char far hc_fo_position(unsigned char order, unsigned char cyl,
                                 unsigned char ncyl);
unsigned char far hc_fo_length(unsigned char order);

/* Once per main-loop pass from eng_service(), after the sensors: the time
   base, the control pressure, the motorsport and DFCO states. */
void          far hc_ec_pre(unsigned int rpm);
/* The table loads (ignition, lambda) for a fuel load and the target lambda,
   x1000 - eng_service() then fuels to it. */
unsigned int  far hc_ec_target_lambda(unsigned int rpm, unsigned int fuel_load);
unsigned int  far hc_ec_ign_load(unsigned int fuel_load);
unsigned int  far hc_ec_load_lag(unsigned int throttle_x10, unsigned int rpm);
/* Base table advance (signed 0.1 deg) -> commanded advance: corrections,
   DFCO and soft-limit retard, launch / flat-shift / anti-lag timing,
   clamped -30..+60 deg and rate-limited in the advance direction. */
int           far hc_ec_spark(int base_x10, unsigned char cranking);
/* The cycle's open time -> with closed-loop and motorsport fuel. */
unsigned int  far hc_ec_fuel(unsigned int te_us);
/* After the fuel: closed loop, the flags, the injection angle. */
void          far hc_ec_post(unsigned int rpm, unsigned int fuel_load);
/* The pressure the fuel uses: measured, or the MAP estimate on a fault. */
unsigned int  far hc_ec_map_ctrl(void);
/* Main loop: the key-on priming pulse. */
void          far hc_ec_prime_service(void);
/* A VE cell was written (Tune Analyze): closed loop holds 20 s. */
void          far hc_ec_ve_written(void);
/* Telemetry. */
void          far hc_ec_publish(unsigned int boost_req_x10);

#endif
