/*
 * hc_config_generated.h - GENERATED. Do not edit.
 *
 * Source: tools/config_source/generate_config.py, over the layout in
 * firmware/config/hcconfig.h and the metadata in
 * tools/config_source/hanicore_config_def.py.
 *
 * This header does NOT redefine hcconfig.h's offsets. hcconfig.h owns
 * the layout; everything here either comes from it or lives inside the
 * region it reserves as CFG_UNIVERSAL_BASE. The compile-time checks at
 * the bottom fail the BUILD if the two ever disagree, which is the
 * whole point: an offset that exists in two places is an offset that
 * will eventually differ in two places.
 */
#ifndef HC_CONFIG_GENERATED_H
#define HC_CONFIG_GENERATED_H

#include "hcconfig.h"

/* ---------------------------------------------------------- limits -- */
/* The universal model's ceiling. HC_MAX_CYL (8) is what the LEGACY
   arrays in hcconfig.h are sized for; CFG_U_TDC_CYL_EXT and the
   universal pin arrays carry cylinders 9..12, so nothing in the
   architecture assumes 4, 6 or 8. */
#define HC_MAX_CYL_UNIVERSAL         12u
#define HC_N_GENERIC_IO              8u
#define HC_PIN_NONE                  255u
#define HC_PHYSICAL_PIN_COUNT        121u
/* DERIVED from the universal block's own layout - see
   universal_schema(). A literal here meant that adding a field
   left a battery-backed page from the previous firmware looking
   valid, with the new bytes holding whatever SRAM had. */
#define HC_UNIVERSAL_SCHEMA          0xE921u
#define HC_UNIVERSAL_MAGIC           0x4855u   /* 'HU' */

/* ------------------------------------------------- layout identity -- */
/* DERIVED, never hand-maintained: a CRC32 over every field's slot name,
   offset, C type and element count, plus the page and core sizes. It is
   what a stored calibration record carries so that a firmware whose page
   layout has moved REFUSES the record instead of reinterpreting it. See
   layout_id() in tools/config_source/generate_config.py. */
#define HC_CFG_LAYOUT_ID             0x83D8361EuL

/* -------------------------------------------------------- apply policy -- */
/* WHEN a validated change may reach the running engine. SAFETY_CRITICAL
   is NOT a member of this enum - it is an independent flag, because an
   oil-pressure shutdown threshold is LIVE_APPLY and safety critical at
   the same time and one enum cannot say both. */
typedef enum {
    HC_APPLY_LIVE     = 0,
    HC_APPLY_RPM_ZERO = 1,
    HC_APPLY_RESTART  = 2
} hc_apply_policy_t;

/* The unit of atomicity for an RPM_ZERO_APPLY transaction. */
typedef enum {
    HC_GRP_GENERAL            = 0,
    HC_GRP_ENGINE_SETUP       = 1,
    HC_GRP_TRIGGER_SETUP      = 2,
    HC_GRP_INJECTOR_ROUTING   = 3,
    HC_GRP_IGNITION_ROUTING   = 4,
    HC_GRP_SENSOR_ROUTING     = 5,
    HC_GRP_DBW_SETUP          = 6,
    HC_GRP_OUTPUT_ROUTING     = 7,
    HC_GRP_RELAY_SETUP        = 8,
    HC_GRP_TABLES             = 9,
    HC_GRP_MOTORSPORT         = 10,
    HC_GRP_COUNT
} hc_apply_group_t;

/* Independent per-field flags. */
#define HC_FLAG_SAFETY_CRITICAL   0x01u
#define HC_FLAG_IS_PIN            0x02u   /* value is a physical pin */

/* ------------------------------------------------- capability bits -- */
#define HC_PINCAP_AIN            0x0001u
#define HC_PINCAP_DIN            0x0002u
#define HC_PINCAP_FREQ_IN        0x0004u
#define HC_PINCAP_VR_IN          0x0008u
#define HC_PINCAP_HALL_IN        0x0010u
#define HC_PINCAP_LOW_SIDE       0x0020u
#define HC_PINCAP_PWM_OUT        0x0040u
#define HC_PINCAP_INJ_OUT        0x0080u
#define HC_PINCAP_IGN_OUT        0x0100u
#define HC_PINCAP_DBW_HBRIDGE    0x0200u
#define HC_PINCAP_RELAY_OUT      0x0400u
#define HC_PINCAP_MAIN_RELAY_HW  0x0800u
#define HC_PINCAP_SPECIAL_LOCKED 0x8000u

/* ------------------------------------------------------------ enums -- */
/* LoadSource: Load model */
#define HC_LOAD_MAP                   0u
#define HC_LOAD_TPS                   1u
#define HC_LOAD_ALPHAN                2u

/* TriggerEdge: Capture active edge */
#define HC_EDGE_FALLING               0u
#define HC_EDGE_RISING                1u

/* TriggerSource: Which trigger input may be armed at all */
#define HC_TRIG_SRC_BENCH             0u
#define HC_TRIG_SRC_REAL              1u

/* MainRelayMode: Generic relay operating mode */
#define HC_RELAY_OFF                  0u
#define HC_RELAY_ON                   1u
#define HC_RELAY_AUTO                 2u

/* RevLimMode: Rev limiter cut mechanism */
#define HC_REVLIM_SPARK               0u
#define HC_REVLIM_FUEL                1u
#define HC_REVLIM_BOTH                2u

/* BoostMode: Boost control strategy */
#define HC_BOOST_OPEN_LOOP            0u
#define HC_BOOST_CLOSED_LOOP          1u

/* DbwSfMode: How to read the H-bridge status pin */
#define HC_DBW_SF_IGNORE              0u
#define HC_DBW_SF_LOW_IS_FAULT        1u
#define HC_DBW_SF_HIGH_IS_FAULT       2u

/* FuelPumpMode:  */
#define HC_PUMP_OFF                   0u
#define HC_PUMP_AUTO                  1u

/* InjStrategy: Fuel injection execution strategy */
#define HC_INJ_BATCH                  0u
#define HC_INJ_SEMI_SEQ               1u
#define HC_INJ_SEQUENTIAL             2u

/* IgnStrategy: Ignition execution strategy. NOT the same question as how many coils there are: wasted COP uses individual coils and still runs crank-only. */
#define HC_IGN_WASTED_PAIRED          0u
#define HC_IGN_WASTED_COP             1u
#define HC_IGN_SEQUENTIAL_COP         2u
#define HC_IGN_DISTRIBUTOR            3u

/* SyncMode: How much engine position the decoder is configured to establish */
#define HC_SYNC_NONE                  0u
#define HC_SYNC_CRANK_ONLY            1u
#define HC_SYNC_CAM1_CYCLE            2u
#define HC_SYNC_CAM2_CYCLE            3u
#define HC_SYNC_DUAL_CAM              4u

/* TriggerDecoder: Crank decoder. Validation rules are PER DECODER - a tooth-count or gap-ratio rule that belongs to the missing-tooth decoder must not be enforced against a decoder that has no gap. */
#define HC_TRIGDEC_CUSTOM             0u
#define HC_TRIGDEC_MISSING_TOOTH      1u
#define HC_TRIGDEC_EVEN_TOOTH         2u
#define HC_TRIGDEC_BOSCH_ME711        3u

/* TrackCorrelation: Dual-track correlation model for TPS and APP. Do NOT assume opposite: it is true of the ME7.5 pair and is not a law. */
#define HC_TRACK_OPPOSITE             0u
#define HC_TRACK_SAME                 1u
#define HC_TRACK_SCALED               2u

/* LambdaSource: Wideband controller source */
#define HC_LAMBDA_OFF                 0u
#define HC_LAMBDA_INTERNAL_LSU        1u
#define HC_LAMBDA_EXTERNAL_ANALOG     2u
#define HC_LAMBDA_CAN                 3u

/* LambdaHeaterPolicy: When the wideband heater may run */
#define HC_LAMBDA_HEAT_OFF            0u
#define HC_LAMBDA_HEAT_IGNITION       1u
#define HC_LAMBDA_HEAT_RUNNING        2u

/* Bank: Cylinder bank association */
#define HC_BANK_NONE                  0u
#define HC_BANK_1                     1u
#define HC_BANK_2                     2u
#define HC_BANK_BOTH                  3u

/* TestMode: Bench test selection. Every entry is gated on RPM = 0 and on CFG_OUTPUTS_ARMED; selecting one does not by itself drive anything. */
#define HC_TEST_NONE                  0u
#define HC_TEST_FUEL_PUMP             1u
#define HC_TEST_FAN                   2u
#define HC_TEST_INJECTOR              3u
#define HC_TEST_COIL                  4u
#define HC_TEST_BOOST                 5u
#define HC_TEST_VVT                   6u
#define HC_TEST_IDLE                  7u
#define HC_TEST_DBW                   8u
#define HC_TEST_GENERIC_OUT           9u
#define HC_TEST_MAIN_RELAY            10u

/* CamPattern: The cam wheel, for camPhaseMode PATTERN */
#define HC_CAMPAT_NONE                0u
#define HC_CAMPAT_SINGLE              1u
#define HC_CAMPAT_EQUAL               2u
#define HC_CAMPAT_QUICKSTART          3u
#define HC_CAMPAT_HONDA_K_4P1         4u
#define HC_CAMPAT_BARRA_3P1           5u
#define HC_CAMPAT_TOYOTA_4M1          6u
#define HC_CAMPAT_NISSAN_VQ           7u
#define HC_CAMPAT_MIATA_NB            8u

/* FuelModel: Fuel model */
#define HC_FUEL_LEGACY                0u
#define HC_FUEL_ALPHAN                1u
#define HC_FUEL_MANIFOLD              2u
#define HC_FUEL_CHARGE                3u

/* PressureRole: Where the pressure sensor measures */
#define HC_PRESSURE_NONE              0u
#define HC_PRESSURE_MANIFOLD          1u
#define HC_PRESSURE_CHARGE            2u

/* DensityPolicy: Air density pressure */
#define HC_DENSITY_FIXED              0u
#define HC_DENSITY_ABSOLUTE           1u
#define HC_DENSITY_BLEND              2u

/* BaroSource: Ambient pressure source */
#define HC_BARO_FIXED                 0u
#define HC_BARO_STOPPED               1u
#define HC_BARO_DEDICATED             2u

/* InjPressMode: Injector pressure compensation (rusEFI injectorCompensationMode) */
#define HC_INJP_NONE                  0u
#define HC_INJP_REFERENCED            1u
#define HC_INJP_FIXED_RAIL            2u
#define HC_INJP_SENSED                3u

/* ------------------------------- universal block field offsets -- */
/* Inside hcconfig.h's CFG_UNIVERSAL_BASE (2502, 1336 bytes reserved).
   1336 bytes used.
   Every one of these is an OFFSET INTO THE SAME 4096-byte page, so a
   TunerStudio write reaches them through the identical path as any
   calibration byte. */
#define CFG_U_MAGIC                    2502u /* u16 Universal block magic */
#define CFG_U_SCHEMA                   2504u /* u16 Universal schema version */
#define CFG_U_GENERATION               2506u /* u16 Desired config revision */
#define CFG_U_CRC                      2508u /* u16 Universal block CRC */
#define CFG_U_DISPLACEMENT_CC          2510u /* u16 Displacement */
#define CFG_U_ENGINE_PRESET            2512u /* u8 Engine preset */
#define CFG_U_INJECTOR_PRESET          2513u /* u8 Injector preset */
#define CFG_U_COIL_PRESET              2514u /* u8 Coil preset */
#define CFG_U_MAP_PRESET               2515u /* u8 Pressure sensor preset */
#define CFG_U_CYL_BANK                 2516u /* u8[12] Cylinder bank */
#define CFG_U_TDC_CYL_EXT              2528u /* u16[4] Cylinder 9..12 TDC */
#define CFG_U_INJ_STRATEGY             2536u /* u8 Injection strategy */
#define CFG_U_IGN_STRATEGY             2537u /* u8 Ignition strategy */
#define CFG_U_SYNC_MODE                2538u /* u8 Synchronisation mode */
#define CFG_U_TRIG_DECODER             2539u /* u8 Crank decoder */
#define CFG_U_TRIG_ANGLE_X10           2540u /* s16 Trigger angle (tooth #1, deg ATDC) */
#define CFG_U_CAM_REFS                 2542u /* u8 Cam references per cycle */
#define CFG_U_CAM_PAD                  2543u /* u8 Alignment pad */
#define CFG_U_CAM_REF_X10              2544u /* u16 First cam reference angle */
#define CFG_U_CAM_WINDOW_X10           2546u /* u16 Cam acceptance window */
#define CFG_U_PIN_CRANK                2548u /* u8 Crank sensor pin */
#define CFG_U_PIN_CAM1                 2549u /* u8 Camshaft 1 pin */
#define CFG_U_PIN_CAM2                 2550u /* u8 Camshaft 2 pin */
#define CFG_U_PIN_INJ                  2551u /* u8[12] Injector pin per cylinder */
#define CFG_U_PIN_IGN                  2563u /* u8[12] Ignition pin per cylinder */
#define CFG_U_PIN_MAP                  2575u /* u8 Pressure sensor pin */
#define CFG_U_PIN_BARO                 2576u /* u8 Barometric sensor pin */
#define CFG_U_PIN_CLT                  2577u /* u8 Coolant sensor pin */
#define CFG_U_PIN_IAT                  2578u /* u8 Intake air sensor pin */
#define CFG_U_PIN_TPS1                 2579u /* u8 Throttle track 1 pin */
#define CFG_U_PIN_TPS2                 2580u /* u8 Throttle track 2 pin */
#define CFG_U_PIN_APP1                 2581u /* u8 Pedal track 1 pin */
#define CFG_U_PIN_APP2                 2582u /* u8 Pedal track 2 pin */
#define CFG_U_PIN_VBAT                 2583u /* u8 Battery sense pin */
#define CFG_U_PIN_OIL_PRESS            2584u /* u8 Oil pressure pin */
#define CFG_U_PIN_FUEL_PRESS           2585u /* u8 Fuel pressure pin */
#define CFG_U_PIN_FLEX                 2586u /* u8 Flex fuel sensor pin */
#define CFG_U_PIN_MAF                  2587u /* u8 Air mass sensor pin */
#define CFG_U_PIN_LAMBDA1              2588u /* u8 Lambda 1 input pin */
#define CFG_U_PIN_LAMBDA2              2589u /* u8 Lambda 2 input pin */
#define CFG_U_PIN_MAIN_RELAY           2590u /* u8 Main relay pin */
#define CFG_U_PIN_FUEL_PUMP            2591u /* u8 Fuel pump relay pin */
#define CFG_U_PIN_TACHO                2592u /* u8 Tachometer output pin */
#define CFG_U_PIN_BOOST                2593u /* u8 Boost solenoid pin */
#define CFG_U_PIN_CAM1_SOL             2594u /* u8 Cam 1 solenoid pin */
#define CFG_U_PIN_CAM2_SOL             2595u /* u8 Cam 2 solenoid pin */
#define CFG_U_PIN_GEN_AIN              2596u /* u8[8] Generic analog pin */
#define CFG_U_PIN_GEN_PWM              2604u /* u8[8] Generic PWM pin */
#define CFG_U_PIN_GEN_OUT              2612u /* u8[8] Generic output pin */
#define CFG_U_TPS_CORR                 2620u /* u8 TPS track correlation */
#define CFG_U_APP_CORR                 2621u /* u8 Pedal track correlation */
#define CFG_U_TPS_TOL_X10              2622u /* u16 TPS track tolerance */
#define CFG_U_APP_TOL_X10              2624u /* u16 Pedal track tolerance */
#define CFG_U_LAM1_CYLMASK             2626u /* u16 Lambda 1 cylinders */
#define CFG_U_LAM2_CYLMASK             2628u /* u16 Lambda 2 cylinders */
#define CFG_U_LAM1_SRC                 2630u /* u8 Lambda 1 source */
#define CFG_U_LAM1_BANK                2631u /* u8 Lambda 1 bank */
#define CFG_U_LAM1_AUTH                2632u /* u8 Lambda 1 trim authority */
#define CFG_U_LAM2_SRC                 2633u /* u8 Lambda 2 source */
#define CFG_U_LAM2_BANK                2634u /* u8 Lambda 2 bank */
#define CFG_U_LAM2_AUTH                2635u /* u8 Lambda 2 trim authority */
#define CFG_U_STOICH_X100              2636u /* u16 Fuel stoichiometric ratio */
#define CFG_U_INJ_FLOW_CCMIN           2638u /* u16 Injector flow */
#define CFG_U_INJ_REF_KPA              2640u /* u16 Injector test pressure */
#define CFG_U_CRANK_DWELL_X100         2642u /* u16 Cranking dwell */
#define CFG_U_MS_ENABLE                2644u /* u16 Motorsport features */
#define CFG_U_PIN_LAUNCH               2646u /* u8 Launch switch input */
#define CFG_U_PIN_FLATSHIFT            2647u /* u8 Clutch / flat-shift input */
#define CFG_U_PIN_ANTILAG              2648u /* u8 ALS enable input */
#define CFG_U_PIN_PITLIM               2649u /* u8 Pit limiter input */
#define CFG_U_PIN_MAPSWITCH            2650u /* u8 Map switch pin */
#define CFG_U_PIN_VSS                  2651u /* u8 Road speed pin */
#define CFG_U_LAUNCH_RPM               2652u /* u16 Launch: rpm */
#define CFG_U_LAUNCH_RETARD_X10        2654u /* s16 Launch: ignition timing */
#define CFG_U_FLATSHIFT_RPM            2656u /* u16 Flat shift: above rpm */
#define CFG_U_FLATSHIFT_CUT_MS         2658u /* u16 Flat shift: cut time */
#define CFG_U_ANTILAG_RETARD_X10       2660u /* s16 Anti-lag: timing change */
#define CFG_U_ANTILAG_FUEL_PCT         2662u /* u8 Anti-lag: fuel added */
#define CFG_U_PITLIM_RPM_PAD           2663u /* u8 Alignment pad */
#define CFG_U_PITLIM_RPM               2664u /* u16 Pit limiter: rpm */
#define CFG_U_OILP_MIN_KPA             2666u /* u16 Minimum oil pressure */
#define CFG_U_OILP_MIN_RPM             2668u /* u16 Oil pressure check above */
#define CFG_U_CLT_MAX_X10              2670u /* u16 Coolant limit */
#define CFG_U_TEST_MODE                2672u /* u8 Bench test */
#define CFG_U_TEST_PIN                 2673u /* u8 Bench test pin */
#define CFG_U_TEST_VALUE               2674u /* u16 Bench test value */
#define CFG_U_TEST_TIMEOUT_MS          2676u /* u16 Bench test timeout */
#define CFG_U_S5500_BASE               2678u /* u8 Analog window base word */
#define CFG_U_DBW_MOTOR_DIR            2679u /* u8 Throttle motor direction */
#define CFG_U_FUEL_PUMP_MODE           2680u /* u8 Fuel pump mode */
#define CFG_U_LAM_HEAT_POLICY          2681u /* u8 Wideband heater */
#define CFG_U_MAIN_RELAY_HOLD_MS       2682u /* u16 Main relay release delay */
#define CFG_U_DBW_MAX_DUTY_X10         2684u /* u16 Throttle output authority */
#define CFG_U_DBW_RATE_X10             2686u /* u16 Throttle target rate limit */
#define CFG_U_DBW_DEADBAND_X10         2688u /* u16 Throttle position deadband */
#define CFG_U_TIMING_MODE              2690u /* u8 Ignition timing mode */
#define CFG_U_IGN_PAD                  2691u /* u8 Alignment pad */
#define CFG_U_FIXED_TIMING_X10         2692u /* u16 Fixed ignition advance */
#define CFG_U_CAM_PHASE_MODE           2694u /* u8 Cam phase method */
#define CFG_U_CAM_PHASE_LEVEL          2695u /* u8 Cam level at the phase angle */
#define CFG_U_CAM_PHASE_ANGLE_X10      2696u /* u16 Cam phase check angle */
#define CFG_U_CAM_PHASE_CONFIRM        2698u /* u8 Cam phase confirmations */
#define CFG_U_CAM_PHASE_PAD            2699u /* u8 Alignment pad */
#define CFG_U_CAM1_PATTERN             2700u /* u8 Cam 1 wheel */
#define CFG_U_CAM2_PATTERN             2701u /* u8 Cam 2 wheel */
#define CFG_U_CAM2_REF_X10             2702u /* u16 Cam 2 tooth 0 angle */
#define CFG_U_CAM_TOOTH_TOL            2704u /* u8 Cam tooth spacing tolerance */
#define CFG_U_CAM_PAT_PAD              2705u /* u8 Alignment pad */
#define CFG_U_BOOST_CL_MIN_X10         2706u /* u16 Closed loop above pressure */
#define CFG_U_BOOST_I_BAND_X10         2708u /* u16 Integrate within (below target) */
#define CFG_U_IDLE_PEDAL_X10           2710u /* u16 Idle: pedal released below */
#define CFG_U_IDLE_START_MS            2712u /* u16 Idle: closed loop after start */
#define CFG_U_CLT_LIMP_RPM             2714u /* u16 Coolant limit: rev limit */
#define CFG_U_ETB_LIMP_RPM             2716u /* u16 Throttle fault: rev limit */
#define CFG_U_INJ_DUTY_INST_X10        2718u /* u16 Injector duty cut at once */
#define CFG_U_INJ_DUTY_SUST_X10        2720u /* u16 Injector duty cut sustained */
#define CFG_U_INJ_DUTY_SUST_MS         2722u /* u16 Injector duty sustained for */
#define CFG_U_FLOOD_CLEAR_X10          2724u /* u16 Flood clear above pedal */
#define CFG_U_DBW_FAULT_DEBOUNCE_MS    2726u /* u16 Sensor fault confirm time */
#define CFG_U_DBW_BATT_COMP            2728u /* u8 Battery voltage compensation */
#define CFG_U_DBW_PAD                  2729u /* u8 Alignment pad */
#define CFG_U_INJ_TIMING_MODE          2730u /* u8 Injection timing refers to */
#define CFG_U_SEQ_PAD                  2731u /* u8 Alignment pad */
#define CFG_U_TRANS_ENABLE             2732u /* u8 Transient fuel */
#define CFG_U_TRANS_PAD                2733u /* u8 Alignment pad */
#define CFG_U_AS_DECAY_MS              2734u /* u16 After-start duration */
#define CFG_U_WW_X_PCT                 2736u /* u8[16] Wall wetting fraction */
#define CFG_U_WW_TAU_20MS              2752u /* u8[16] Wall film time constant */
#define CFG_U_AS_PCT                   2768u /* u8[16] After-start extra fuel */
#define CFG_U_IGN_CLT_CORR             2784u /* s16[16] CLT timing correction */
#define CFG_U_IGN_IAT_AX               2816u /* u16[8] IAT timing correction axis */
#define CFG_U_IGN_IAT_CORR             2832u /* s16[8] IAT timing correction */
#define CFG_U_IDLE_TIM_EN              2848u /* u8 Closed loop idle ignition timing */
#define CFG_U_IDLE_TIM_PAD             2849u /* u8 Alignment pad */
#define CFG_U_IDLE_TIM_KP              2850u /* u16 Idle timing proportional gain */
#define CFG_U_IDLE_TIM_MIN             2852u /* s16 Idle timing min adjustment (retard) */
#define CFG_U_IDLE_TIM_MAX             2854u /* s16 Idle timing max adjustment (advance) */
#define CFG_U_IDLE_TIM_SOFT_MS         2856u /* u16 Idle timing soft entry */
#define CFG_U_IDLE_DASH_X10            2858u /* u16 Dashpot coasting-to-idle initial adder */
#define CFG_U_IDLE_DASH_HOLD_MS        2860u /* u16 Dashpot coasting-to-idle hold time */
#define CFG_U_IDLE_DASH_DECAY_MS       2862u /* u16 Dashpot coasting-to-idle decay time */
#define CFG_U_CEL_ENABLE               2864u /* u8 Check engine lamp output */
#define CFG_U_PIN_MIL                  2865u /* u8 Check engine lamp pin */
#define CFG_U_CEL_TEST_ENABLE          2866u /* u8 Key-on lamp test */
#define CFG_U_CEL_PAD                  2867u /* u8 Alignment pad */
#define CFG_U_CEL_TEST_ON_MS           2868u /* u16 Lamp test ON time */
#define CFG_U_CEL_TEST_GAP_MS          2870u /* u16 Lamp test OFF gap */
#define CFG_U_KNOCK_MODE               2872u /* u8 Knock control */
#define CFG_U_KNOCK_BAND               2873u /* u8 Band-pass centre frequency */
#define CFG_U_KNOCK_GAIN               2874u /* u8[4] Sensor gain */
#define CFG_U_KNOCK_SENSOR             2878u /* u8[8] Sensor for cylinder */
#define CFG_U_KNOCK_RPM_AX             2886u /* u16[8] Knock window rpm axis */
#define CFG_U_KNOCK_WIN_START          2902u /* u16[8] Window start after TDC */
#define CFG_U_KNOCK_WIN_LEN            2918u /* u16[8] Window length */
#define CFG_U_KNOCK_KEF_RPM            2934u /* u16[6] Threshold factor rpm axis */
#define CFG_U_KNOCK_KEF                2946u /* u8[6] Knock threshold factor */
#define CFG_U_KNOCK_KEF_DYN            2952u /* u8 Threshold factor in transients */
#define CFG_U_KNOCK_TP                 2953u /* u8 Reference filter */
#define CFG_U_KNOCK_TP_DYN             2954u /* u8 Reference filter in transients */
#define CFG_U_KNOCK_LOAD_MIN           2955u /* u8 Minimum load */
#define CFG_U_KNOCK_RPM_MIN            2956u /* u16 Minimum rpm */
#define CFG_U_KNOCK_CLT_MIN            2958u /* u16 Minimum coolant */
#define CFG_U_KNOCK_REF_INIT           2960u /* u16 Reference start value */
#define CFG_U_KNOCK_REAPPLY_MS         2962u /* u16 Retard recovery time per 0.25 deg */
#define CFG_U_KNOCK_DIAG_RPM           2964u /* u16 Sensor diagnosis above */
#define CFG_U_KNOCK_REF_MIN            2966u /* u16 Plausible reference minimum */
#define CFG_U_KNOCK_REF_MAX            2968u /* u16 Plausible reference maximum */
#define CFG_U_KNOCK_LEARN              2970u /* u8 Settling windows */
#define CFG_U_KNOCK_STOP_N             2971u /* u8 At-stop count */
#define CFG_U_KNOCK_STEP_Q             2972u /* u8 Retard per knock */
#define CFG_U_KNOCK_MAX_Q              2973u /* u8 Maximum retard */
#define CFG_U_KNOCK_SAFE_Q             2974u /* u8 Sensor-fault retard */
#define CFG_U_KNOCK_DIAG_N             2975u /* u8 Diagnosis count */
#define CFG_U_VVT_MODE                 2976u /* u8[2] VVT control */
#define CFG_U_VVT_INVERT               2978u /* u8[2] Solenoid control direction */
#define CFG_U_VVT_FREQ_HZ              2980u /* u16 Solenoid PWM frequency */
#define CFG_U_VVT_MIN_RPM              2982u /* u16 Do not control below RPM */
#define CFG_U_VVT_MIN_CLT              2984u /* u16 Do not control below CLT */
#define CFG_U_VVT_DELAY_MS             2986u /* u16 Activation delay */
#define CFG_U_VVT_KP                   2988u /* u16[2] P factor */
#define CFG_U_VVT_KI                   2992u /* u16[2] I factor */
#define CFG_U_VVT_KD                   2996u /* u16[2] D factor */
#define CFG_U_VVT_DUTY_MIN             3000u /* u16[2] Min duty */
#define CFG_U_VVT_DUTY_MAX             3004u /* u16[2] Max duty */
#define CFG_U_VVT_DUTY_ON              3008u /* u16[2] On/off: ON duty */
#define CFG_U_VVT_ERR_MAX              3012u /* u16 Fault: error above */
#define CFG_U_VVT_ERR_MS               3014u /* u16 Fault: for longer than */
#define CFG_U_VVT_FB_MS                3016u /* u16 Cam position max age */
#define CFG_U_VVT_RPM_AX               3018u /* u16[8] VVT rpm axis */
#define CFG_U_VVT_LOAD_AX              3034u /* u16[8] VVT load axis */
#define CFG_U_VVT_TARGET1              3050u /* s16[64] Cam 1 target */
#define CFG_U_VVT_TARGET2              3178u /* s16[64] Cam 2 target */
#define CFG_U_FIRING_ORDER             3306u /* u8 Firing order */
#define CFG_U_ALPHAN_IAT               3307u /* u8 Use intake air temperature */
#define CFG_U_IGN_LOAD_MODE            3308u /* u8 Ignition table load */
#define CFG_U_LAM_LOAD_MODE            3309u /* u8 Target lambda table load */
#define CFG_U_LAM_RPM_AX               3310u /* u16[16] Target lambda rpm axis */
#define CFG_U_LAM_LOAD_AX              3342u /* u16[16] Target lambda load axis */
#define CFG_U_MAPEST_RPM_AX            3374u /* u16[8] Pressure estimate rpm axis */
#define CFG_U_MAPEST_TPS_AX            3390u /* u16[8] Pressure estimate throttle axis */
#define CFG_U_MAPEST                   3406u /* u8[64] Pressure estimate */
#define CFG_U_PRIME_MG                 3470u /* u16[8] Priming pulse fuel */
#define CFG_U_PRIME_DELAY              3486u /* u8 Priming delay */
#define CFG_U_DFCO_DELAY               3487u /* u8 Fuel cut delay */
#define CFG_U_DFCO_MIN_CLT             3488u /* u16 Fuel cut: coolant above */
#define CFG_U_DFCO_MAP_MAX             3490u /* u8 Fuel cut: manifold pressure below */
#define CFG_U_DFCO_RETARD              3491u /* u8 Fuel cut timing retard */
#define CFG_U_DFCO_RAMP                3492u /* u8 Fuel cut retard ramp-out */
#define CFG_U_STFT_ENABLE              3493u /* u8 Closed loop fuel correction */
#define CFG_U_STFT_DELAY               3494u /* u8 Startup delay */
#define CFG_U_STFT_DEADBAND            3495u /* u8 Deadband */
#define CFG_U_STFT_MIN_CLT             3496u /* u16 Minimum coolant */
#define CFG_U_STFT_IDLE_RPM            3498u /* u16 Idle region below */
#define CFG_U_STFT_OVR_LOAD            3500u /* u8 Overrun region below load */
#define CFG_U_STFT_PWR_LOAD            3501u /* u8 Power region above load */
#define CFG_U_STFT_LAM_MIN             3502u /* u8 Learn above lambda */
#define CFG_U_STFT_LAM_MAX             3503u /* u8 Learn below lambda */
#define CFG_U_STFT_AFTER_DFCO          3504u /* u8 Hold after fuel cut */
#define CFG_U_STFT_AFTER_AE            3505u /* u8 Hold after acceleration enrichment */
#define CFG_U_STFT_ADD                 3506u /* u8[4] Max add */
#define CFG_U_STFT_REMOVE              3510u /* u8[4] Max remove */
#define CFG_U_STFT_TAU                 3514u /* u8[4] Time constant */
#define CFG_U_REVLIM_HYST              3518u /* u8 Rev limit hysteresis */
#define CFG_U_REVLIM_SOFT_RETARD       3519u /* u8 Soft limit timing retard */
#define CFG_U_REVLIM_SOFT_FUEL         3520u /* u8 Soft limit fuel added */
#define CFG_U_MS_SWITCH_INV            3521u /* u8 Motorsport switch polarity */
#define CFG_U_LAUNCH_TPS               3522u /* u8 Launch: pedal above */
#define CFG_U_LAUNCH_WINDOW            3523u /* u8 Launch: window */
#define CFG_U_LAUNCH_CUT_START         3524u /* u8 Launch: initial spark cut */
#define CFG_U_LAUNCH_CUT_END           3525u /* u8 Launch: spark cut before launch rpm */
#define CFG_U_LAUNCH_FUEL              3526u /* u8 Launch: fuel added */
#define CFG_U_FLATSHIFT_TPS            3527u /* u8 Flat shift: pedal above */
#define CFG_U_FLATSHIFT_CUT_PCT        3528u /* u8 Flat shift: spark cut */
#define CFG_U_ALS_TPS_MAX              3529u /* u8 Anti-lag: pedal below */
#define CFG_U_FLATSHIFT_TIMING         3530u /* s16 Flat shift: ignition timing */
#define CFG_U_ALS_RPM_MIN              3532u /* u16 Anti-lag: above rpm */
#define CFG_U_ALS_RPM_MAX              3534u /* u16 Anti-lag: below rpm */
#define CFG_U_ALS_CLT_MIN              3536u /* u16 Anti-lag: coolant above */
#define CFG_U_ALS_CLT_MAX              3538u /* u16 Anti-lag: coolant below */
#define CFG_U_ALS_CUT_PCT              3540u /* u8 Anti-lag: spark cut */
#define CFG_U_ALS_THROTTLE             3541u /* u8 Anti-lag: throttle open */
#define CFG_U_ALS_MAX_S                3542u /* u8 Anti-lag: max duration */
#define CFG_U_ROTIDLE_CUT              3543u /* u8 Rotational idle: spark cut */
#define CFG_U_ROTIDLE_TPS              3544u /* u8 Rotational idle: pedal below */
#define CFG_U_INJ_PHASE_MODE           3545u /* u8 Injection timing */
#define CFG_U_ROTIDLE_RPM              3546u /* u16 Rotational idle: below rpm */
#define CFG_U_IDLE_ETB_RANGE           3548u /* u8 Idle throttle range */
#define CFG_U_V98_PAD                  3549u /* u8 Alignment pad */
#define CFG_U_INJ_PHASE_RPM_AX         3550u /* u16[8] Injection timing rpm axis */
#define CFG_U_INJ_PHASE_LOAD_AX        3566u /* u16[8] Injection timing load axis */
#define CFG_U_INJ_PHASE                3582u /* u16[64] Injection timing */
#define CFG_U_FUEL_MODEL               3710u /* u8 Fuel model */
#define CFG_U_PRESSURE_ROLE            3711u /* u8 Pressure sensor location */
#define CFG_U_DENSITY_POLICY           3712u /* u8 Air density pressure */
#define CFG_U_BARO_SOURCE              3713u /* u8 Ambient pressure source (not used: always the onboard sensor) */
#define CFG_U_AMBIENT_CORR             3714u /* u8 Correct for ambient pressure (not used: always) */
#define CFG_U_IAT_POLICY               3715u /* u8 Use intake air temperature */
#define CFG_U_LEAN_ENABLE              3716u /* u8 Lean protection */
#define CFG_U_LAMBDA_QUALIFIED         3717u /* u8 Wideband commissioned for protection */
#define CFG_U_PRESSURE_GUARD           3718u /* u8 Pressure-loss cut, other fuel algorithms */
#define CFG_U_V102_PAD                 3719u /* u8 Alignment pad */
#define CFG_U_PRESSURE_REF             3720u /* u16 Ambient if the onboard sensor fails */
#define CFG_U_BLEND_START              3722u /* u16 Boost blend starts at (above ambient) */
#define CFG_U_BLEND_FULL               3724u /* u16 Boost blend complete at (above ambient) */
#define CFG_U_BARO_MAX_AGE             3726u /* u16 Onboard reading held for (sensor fault) */
#define CFG_U_PRESSURE_TIMEOUT         3728u /* u16 Pressure reading maximum age */
#define CFG_U_GUARD_RPM                3730u /* u16 Pressure-loss cut above */
#define CFG_U_GUARD_TPS                3732u /* u16 Pressure-loss cut above TPS */
#define CFG_U_LEAN_RPM                 3734u /* u16 Lean protection above */
#define CFG_U_LEAN_TPS                 3736u /* u16 Lean protection above TPS */
#define CFG_U_LEAN_CHARGE              3738u /* u16 Lean protection above cylinder filling */
#define CFG_U_LEAN_DEVIATION           3740u /* u16 Lean margin over target */
#define CFG_U_LEAN_PERSIST             3742u /* u16 Lean for longer than */
#define CFG_U_LEAN_RECOVERY            3744u /* u16 Recovery: at target, off load, for */
#define CFG_U_DBW_PWM_HZ               3746u /* u16 Throttle bridge PWM frequency */
#define CFG_U_DBW_FRICTION_X10         3748u /* u16 Throttle friction compensation */
#define CFG_U_DWELL_RPM_AX             3750u /* u16[6] Dwell by rpm: rpm axis */
#define CFG_U_DWELL_RPM_PCT            3762u /* u16[6] Dwell by rpm */
#define CFG_U_OILP_LO_MV               3774u /* u16 Oil pressure sensor: voltage at 0 kPa */
#define CFG_U_OILP_HI_MV               3776u /* u16 Oil pressure sensor: voltage at full scale */
#define CFG_U_OILP_HI_KPA              3778u /* u16 Oil pressure sensor: full scale */
#define CFG_U_GP1_THR_A                3780u /* s16 Output 1 condition A: threshold */
#define CFG_U_GP1_THR_B                3782u /* s16 Output 1 condition B: threshold */
#define CFG_U_GP2_THR_A                3784u /* s16 Output 2 condition A: threshold */
#define CFG_U_GP2_THR_B                3786u /* s16 Output 2 condition B: threshold */
#define CFG_U_FAN_ON_C                 3788u /* u16 Fan on at */
#define CFG_U_FAN_OFF_C                3790u /* u16 Fan off at */
#define CFG_U_AC_MAX_CLT               3792u /* u16 A/C off above coolant */
#define CFG_U_IGN_TRIM                 3794u /* u8[8] Ignition trim, cylinder */
#define CFG_U_PIN_FAN                  3802u /* u8 Fan relay output */
#define CFG_U_FAN_WITH_AC              3803u /* u8 Fan on with the A/C compressor */
#define CFG_U_FAN_STOPPED_OFF          3804u /* u8 Fan off when the engine is stopped */
#define CFG_U_PIN_AC_REQ               3805u /* u8 A/C request input */
#define CFG_U_PIN_AC_CLUTCH            3806u /* u8 A/C compressor relay output */
#define CFG_U_AC_REQ_ACTIVE            3807u /* u8 A/C request is active when */
#define CFG_U_AC_IDLE_UP_X10           3808u /* u8 A/C idle-up: throttle added */
#define CFG_U_AC_IDLE_RPM              3809u /* u8 A/C idle-up: target rpm added */
#define CFG_U_AC_MIN_RPM               3810u /* u8 A/C off below */
#define CFG_U_AC_MAX_RPM               3811u /* u8 A/C off above */
#define CFG_U_AC_MAX_TPS               3812u /* u8 A/C off above throttle */
#define CFG_U_AC_DELAY                 3813u /* u8 A/C compressor delay */
#define CFG_U_GP1_PIN                  3814u /* u8 Output 1 pin */
#define CFG_U_GP1_SRC_A                3815u /* u8 Output 1 condition A: source */
#define CFG_U_GP1_OP_A                 3816u /* u8 Output 1 condition A */
#define CFG_U_GP1_HYST_A               3817u /* u8 Output 1 condition A: hysteresis */
#define CFG_U_GP1_SRC_B                3818u /* u8 Output 1 condition B: source */
#define CFG_U_GP1_OP_B                 3819u /* u8 Output 1 condition B */
#define CFG_U_GP1_HYST_B               3820u /* u8 Output 1 condition B: hysteresis */
#define CFG_U_GP1_LOGIC                3821u /* u8 Output 1: conditions */
#define CFG_U_GP1_DELAY                3822u /* u8 Output 1: on delay */
#define CFG_U_GP2_PIN                  3823u /* u8 Output 2 pin */
#define CFG_U_GP2_SRC_A                3824u /* u8 Output 2 condition A: source */
#define CFG_U_GP2_OP_A                 3825u /* u8 Output 2 condition A */
#define CFG_U_GP2_HYST_A               3826u /* u8 Output 2 condition A: hysteresis */
#define CFG_U_GP2_SRC_B                3827u /* u8 Output 2 condition B: source */
#define CFG_U_GP2_OP_B                 3828u /* u8 Output 2 condition B */
#define CFG_U_GP2_HYST_B               3829u /* u8 Output 2 condition B: hysteresis */
#define CFG_U_GP2_LOGIC                3830u /* u8 Output 2: conditions */
#define CFG_U_GP2_DELAY                3831u /* u8 Output 2: on delay */
#define CFG_U_OILP_DELAY               3832u /* u8 Low oil pressure for */
#define CFG_U_INJ_PRESS_MODE           3833u /* u8 Fuel pressure compensation */
#define CFG_U_FUEL_REG_KPA             3834u /* u16 Fuel regulator pressure */
#define CFG_U_FUEL_SENS_KPA            3836u /* u16 Fuel pressure sensor at 4.5 V */

/* ------------------------------------------------- the slot table -- */
/* One entry per configuration field, sorted by offset. The config
   manager classifies a written byte by BINARY SEARCH over this table:
   bounded, no allocation, no per-byte scan of the model. */
typedef struct {
    unsigned int  offset;      /* first byte                          */
    unsigned int  size;        /* bytes, including array elements     */
    unsigned char policy;      /* hc_apply_policy_t                   */
    unsigned char group;       /* hc_apply_group_t                    */
    unsigned char flags;       /* HC_FLAG_*                           */
    unsigned char elem;        /* bytes per element: 1 or 2           */
    unsigned int  pin_needs;   /* HC_PINCAP_* required, 0 if not a pin */
} hc_cfg_slot_t;

#define HC_CFG_SLOT_COUNT   452u
extern const hc_cfg_slot_t hc_cfg_slots[HC_CFG_SLOT_COUNT];

/* Slot covering `off`, or 0 when the byte belongs to a reserved area.
   Bounded: ceil(log2(HC_CFG_SLOT_COUNT)) iterations. */
const hc_cfg_slot_t *hc_cfg_slot_at(unsigned int off);

/* Bit `g` set means apply group g contains at least one RPM_ZERO field. */
extern const unsigned int hc_cfg_rpm_zero_groups;

/* ------------------ switch inputs (hw_descriptors.SWITCH_INPUTS) -- */
#define HC_SWITCH_N          10u
#define HC_SWITCH_CAV        { 86u, 87u, 38u, 39u, 40u, 55u, 56u, 57u, 75u, 76u }
#define HC_SWITCH_ASIC_N     8u
#define HC_SWITCH_ASIC_CAV   { 38u, 39u, 40u, 55u, 56u, 57u, 75u, 76u }
#define HC_SWITCH_ASIC_WORD  { 56u, 56u, 59u, 55u, 56u, 56u, 56u, 56u }
#define HC_SWITCH_ASIC_BIT   { 2u, 4u, 13u, 2u, 1u, 5u, 6u, 7u }

/* --------------------------------------------- compile-time checks -- */
/* If hcconfig.h moves a field, these stop the BUILD rather than letting
   a generated header describe a page that no longer exists. C89 has no
   static_assert, so this is the negative-array-size idiom. */
typedef char hc_cfg_assert_page_size[(HC_CFG_SIZE == 4096u) ? 1 : -1];
typedef char hc_cfg_assert_uni_base[(CFG_UNIVERSAL_BASE == 2502u) ? 1 : -1];
typedef char hc_cfg_assert_uni_size[(CFG_UNIVERSAL_SIZE == 1336u) ? 1 : -1];
typedef char hc_cfg_assert_uni_fits[(1336u <= CFG_UNIVERSAL_SIZE) ? 1 : -1];
typedef char hc_cfg_assert_max_cyl[(HC_MAX_CYL == 8u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_version[(CFG_VERSION == 0u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_cylinders[(CFG_CYLINDERS == 2u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_strokes[(CFG_STROKES == 3u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_tdc_cyl[(CFG_TDC_CYL == 4u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_sy_teeth[(CFG_SY_TEETH == 20u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_sy_gap[(CFG_SY_GAP == 22u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_trig_edge[(CFG_TRIG_EDGE == 23u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_trig_gap_ratio_x10[(CFG_TRIG_GAP_RATIO_X10 == 24u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_trig_min_teeth[(CFG_TRIG_MIN_TEETH == 26u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_trig_timeout_ms[(CFG_TRIG_TIMEOUT_MS == 27u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_rev_max[(CFG_REV_MAX == 28u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_rev_min[(CFG_REV_MIN == 30u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_cam_enable[(CFG_CAM_ENABLE == 32u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_cam_edge[(CFG_CAM_EDGE == 33u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_inj_channel[(CFG_INJ_CHANNEL == 34u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_ign_channel[(CFG_IGN_CHANNEL == 42u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_rev_limit[(CFG_REV_LIMIT == 50u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_crank_rpm_max[(CFG_CRANK_RPM_MAX == 52u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_dwell_ms_x100[(CFG_DWELL_MS_X100 == 54u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_inj_deadtime_us[(CFG_INJ_DEADTIME_US == 56u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_inj_start_deg_x10[(CFG_INJ_START_DEG_X10 == 58u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_ign_advance_deg_x10[(CFG_IGN_ADVANCE_DEG_X10 == 60u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_adc_batt_fs_dv[(CFG_ADC_BATT_FS_DV == 62u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_clt_pullup_ohm[(CFG_CLT_PULLUP_OHM == 64u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_iat_pullup_ohm[(CFG_IAT_PULLUP_OHM == 66u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_outputs_armed[(CFG_OUTPUTS_ARMED == 68u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_flags[(CFG_FLAGS == 69u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_sim_rpm[(CFG_SIM_RPM == 70u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_trig_source[(CFG_TRIG_SOURCE == 72u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_main_relay_mode[(CFG_MAIN_RELAY_MODE == 73u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_main_relay_grace_ms[(CFG_MAIN_RELAY_GRACE_MS == 74u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_tacho_scale[(CFG_TACHO_SCALE == 76u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_pad_77[(CFG_PAD_77 == 77u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_ign_boost_ax[(CFG_IGN_BOOST_AX == 78u) ? 1 : -1];
typedef char hc_cfg_assert_cfg_ign_boost_corr[(CFG_IGN_BOOST_CORR == 94u) ? 1 : -1];
typedef char hc_cfg_assert_cal_fuel_map[(CAL_FUEL_MAP == 128u) ? 1 : -1];
typedef char hc_cfg_assert_cal_fuel_rpm_ax[(CAL_FUEL_RPM_AX == 640u) ? 1 : -1];
typedef char hc_cfg_assert_cal_fuel_load_ax[(CAL_FUEL_LOAD_AX == 672u) ? 1 : -1];
typedef char hc_cfg_assert_cal_ign_rpm_ax[(CAL_IGN_RPM_AX == 704u) ? 1 : -1];
typedef char hc_cfg_assert_cal_ign_load_ax[(CAL_IGN_LOAD_AX == 736u) ? 1 : -1];
typedef char hc_cfg_assert_cal_afr_map[(CAL_AFR_MAP == 768u) ? 1 : -1];
typedef char hc_cfg_assert_cal_clt_enr_ax[(CAL_CLT_ENR_AX == 1024u) ? 1 : -1];
typedef char hc_cfg_assert_cal_clt_enr_val[(CAL_CLT_ENR_VAL == 1056u) ? 1 : -1];
typedef char hc_cfg_assert_cal_crank_pw_ax[(CAL_CRANK_PW_AX == 1072u) ? 1 : -1];
typedef char hc_cfg_assert_cal_crank_pw_val[(CAL_CRANK_PW_VAL == 1088u) ? 1 : -1];
typedef char hc_cfg_assert_cal_dwell_batt_ax[(CAL_DWELL_BATT_AX == 1104u) ? 1 : -1];
typedef char hc_cfg_assert_cal_dwell_batt_val[(CAL_DWELL_BATT_VAL == 1120u) ? 1 : -1];
typedef char hc_cfg_assert_cal_deadtime_val[(CAL_DEADTIME_VAL == 1136u) ? 1 : -1];
typedef char hc_cfg_assert_cal_clt_sens_ax[(CAL_CLT_SENS_AX == 1152u) ? 1 : -1];
typedef char hc_cfg_assert_cal_clt_sens_val[(CAL_CLT_SENS_VAL == 1184u) ? 1 : -1];
typedef char hc_cfg_assert_cal_map_sens_off[(CAL_MAP_SENS_OFF == 1216u) ? 1 : -1];
typedef char hc_cfg_assert_cal_map_sens_grd[(CAL_MAP_SENS_GRD == 1218u) ? 1 : -1];
typedef char hc_cfg_assert_cal_tps1_min[(CAL_TPS1_MIN == 1220u) ? 1 : -1];
typedef char hc_cfg_assert_cal_tps1_max[(CAL_TPS1_MAX == 1222u) ? 1 : -1];
typedef char hc_cfg_assert_cal_tps2_min[(CAL_TPS2_MIN == 1224u) ? 1 : -1];
typedef char hc_cfg_assert_cal_tps2_max[(CAL_TPS2_MAX == 1226u) ? 1 : -1];
typedef char hc_cfg_assert_cal_pedal1_min[(CAL_PEDAL1_MIN == 1228u) ? 1 : -1];
typedef char hc_cfg_assert_cal_pedal1_max[(CAL_PEDAL1_MAX == 1230u) ? 1 : -1];
typedef char hc_cfg_assert_cal_pedal2_min[(CAL_PEDAL2_MIN == 1232u) ? 1 : -1];
typedef char hc_cfg_assert_cal_pedal2_max[(CAL_PEDAL2_MAX == 1234u) ? 1 : -1];
typedef char hc_cfg_assert_cal_load_source[(CAL_LOAD_SOURCE == 1236u) ? 1 : -1];
typedef char hc_cfg_assert_cal_inj_mode[(CAL_INJ_MODE == 1237u) ? 1 : -1];
typedef char hc_cfg_assert_cal_fuelpump_prime_ms[(CAL_FUELPUMP_PRIME_MS == 1238u) ? 1 : -1];
typedef char hc_cfg_assert_cal_dbw_enable[(CAL_DBW_ENABLE == 1240u) ? 1 : -1];
typedef char hc_cfg_assert_cal_iat_channel[(CAL_IAT_CHANNEL == 1241u) ? 1 : -1];
typedef char hc_cfg_assert_cal_dbw_kp[(CAL_DBW_KP == 1242u) ? 1 : -1];
typedef char hc_cfg_assert_cal_dbw_ki[(CAL_DBW_KI == 1244u) ? 1 : -1];
typedef char hc_cfg_assert_cal_dbw_dev_x10[(CAL_DBW_DEV_X10 == 1246u) ? 1 : -1];
typedef char hc_cfg_assert_cal_dbw_dev_ms[(CAL_DBW_DEV_MS == 1248u) ? 1 : -1];
typedef char hc_cfg_assert_cal_dbw_limp_x10[(CAL_DBW_LIMP_X10 == 1250u) ? 1 : -1];
typedef char hc_cfg_assert_cal_iat_default[(CAL_IAT_DEFAULT == 1252u) ? 1 : -1];
typedef char hc_cfg_assert_cal_iat_sens_ax[(CAL_IAT_SENS_AX == 1254u) ? 1 : -1];
typedef char hc_cfg_assert_cal_iat_sens_val[(CAL_IAT_SENS_VAL == 1286u) ? 1 : -1];
typedef char hc_cfg_assert_cal_baro_default[(CAL_BARO_DEFAULT == 1318u) ? 1 : -1];
typedef char hc_cfg_assert_cal_dbw_sf_mode[(CAL_DBW_SF_MODE == 1320u) ? 1 : -1];
typedef char hc_cfg_assert_cal_dbw_kd[(CAL_DBW_KD == 1322u) ? 1 : -1];
typedef char hc_cfg_assert_cal_dbw_min_x10[(CAL_DBW_MIN_X10 == 1324u) ? 1 : -1];
typedef char hc_cfg_assert_cal_dbw_max_x10[(CAL_DBW_MAX_X10 == 1326u) ? 1 : -1];
typedef char hc_cfg_assert_cal_dbw_revlim_rpm[(CAL_DBW_REVLIM_RPM == 1328u) ? 1 : -1];
typedef char hc_cfg_assert_cal_dbw_revlim_range[(CAL_DBW_REVLIM_RANGE == 1330u) ? 1 : -1];
typedef char hc_cfg_assert_cal_dbw_bias_ax[(CAL_DBW_BIAS_AX == 1332u) ? 1 : -1];
typedef char hc_cfg_assert_cal_dbw_bias_val[(CAL_DBW_BIAS_VAL == 1348u) ? 1 : -1];
typedef char hc_cfg_assert_cal_dbw_autocal_ms[(CAL_DBW_AUTOCAL_MS == 1364u) ? 1 : -1];
typedef char hc_cfg_assert_cal_dbw_autocal_duty[(CAL_DBW_AUTOCAL_DUTY == 1366u) ? 1 : -1];
typedef char hc_cfg_assert_cal_dbw_tune_amp[(CAL_DBW_TUNE_AMP == 1368u) ? 1 : -1];
typedef char hc_cfg_assert_cal_pedal_map[(CAL_PEDAL_MAP == 1370u) ? 1 : -1];
typedef char hc_cfg_assert_cal_pedal_rpm_ax[(CAL_PEDAL_RPM_AX == 1626u) ? 1 : -1];
typedef char hc_cfg_assert_cal_pedal_ax[(CAL_PEDAL_AX == 1658u) ? 1 : -1];
typedef char hc_cfg_assert_cal_boost_enable[(CAL_BOOST_ENABLE == 1690u) ? 1 : -1];
typedef char hc_cfg_assert_cal_boost_mode[(CAL_BOOST_MODE == 1691u) ? 1 : -1];
typedef char hc_cfg_assert_cal_boost_duty_map[(CAL_BOOST_DUTY_MAP == 1692u) ? 1 : -1];
typedef char hc_cfg_assert_cal_boost_rpm_ax[(CAL_BOOST_RPM_AX == 1948u) ? 1 : -1];
typedef char hc_cfg_assert_cal_boost_tps_ax[(CAL_BOOST_TPS_AX == 1980u) ? 1 : -1];
typedef char hc_cfg_assert_cal_boost_tgt_map[(CAL_BOOST_TGT_MAP == 2012u) ? 1 : -1];
typedef char hc_cfg_assert_cal_boost_tgt_rpm_ax[(CAL_BOOST_TGT_RPM_AX == 2268u) ? 1 : -1];
typedef char hc_cfg_assert_cal_boost_tgt_tps_ax[(CAL_BOOST_TGT_TPS_AX == 2300u) ? 1 : -1];
typedef char hc_cfg_assert_cal_boost_kp[(CAL_BOOST_KP == 2332u) ? 1 : -1];
typedef char hc_cfg_assert_cal_boost_ki[(CAL_BOOST_KI == 2334u) ? 1 : -1];
typedef char hc_cfg_assert_cal_boost_kd[(CAL_BOOST_KD == 2336u) ? 1 : -1];
typedef char hc_cfg_assert_cal_boost_min_rpm[(CAL_BOOST_MIN_RPM == 2338u) ? 1 : -1];
typedef char hc_cfg_assert_cal_boost_min_tps_x10[(CAL_BOOST_MIN_TPS_X10 == 2340u) ? 1 : -1];
typedef char hc_cfg_assert_cal_boost_freq_hz[(CAL_BOOST_FREQ_HZ == 2342u) ? 1 : -1];
typedef char hc_cfg_assert_cal_boost_cut_kpa[(CAL_BOOST_CUT_KPA == 2344u) ? 1 : -1];
typedef char hc_cfg_assert_cal_boost_cut_hyst[(CAL_BOOST_CUT_HYST == 2346u) ? 1 : -1];
typedef char hc_cfg_assert_cal_boost_clt_ax[(CAL_BOOST_CLT_AX == 2348u) ? 1 : -1];
typedef char hc_cfg_assert_cal_boost_clt_mul[(CAL_BOOST_CLT_MUL == 2364u) ? 1 : -1];
typedef char hc_cfg_assert_cal_boost_iat_ax[(CAL_BOOST_IAT_AX == 2380u) ? 1 : -1];
typedef char hc_cfg_assert_cal_boost_iat_mul[(CAL_BOOST_IAT_MUL == 2396u) ? 1 : -1];
typedef char hc_cfg_assert_cal_accel_thresh_x10[(CAL_ACCEL_THRESH_X10 == 2412u) ? 1 : -1];
typedef char hc_cfg_assert_cal_accel_gain[(CAL_ACCEL_GAIN == 2414u) ? 1 : -1];
typedef char hc_cfg_assert_cal_accel_decay_ms[(CAL_ACCEL_DECAY_MS == 2416u) ? 1 : -1];
typedef char hc_cfg_assert_cal_overrun_rpm[(CAL_OVERRUN_RPM == 2418u) ? 1 : -1];
typedef char hc_cfg_assert_cal_overrun_tps_x10[(CAL_OVERRUN_TPS_X10 == 2420u) ? 1 : -1];
typedef char hc_cfg_assert_cal_overrun_resume[(CAL_OVERRUN_RESUME == 2422u) ? 1 : -1];
typedef char hc_cfg_assert_cal_revlim_mode[(CAL_REVLIM_MODE == 2424u) ? 1 : -1];
typedef char hc_cfg_assert_cal_revlim_pattern[(CAL_REVLIM_PATTERN == 2425u) ? 1 : -1];
typedef char hc_cfg_assert_cal_idle_enable[(CAL_IDLE_ENABLE == 2426u) ? 1 : -1];
typedef char hc_cfg_assert_cal_idle_pad[(CAL_IDLE_PAD == 2427u) ? 1 : -1];
typedef char hc_cfg_assert_cal_idle_target_ax[(CAL_IDLE_TARGET_AX == 2428u) ? 1 : -1];
typedef char hc_cfg_assert_cal_idle_target_val[(CAL_IDLE_TARGET_VAL == 2444u) ? 1 : -1];
typedef char hc_cfg_assert_cal_idle_base_ax[(CAL_IDLE_BASE_AX == 2460u) ? 1 : -1];
typedef char hc_cfg_assert_cal_idle_base_val[(CAL_IDLE_BASE_VAL == 2476u) ? 1 : -1];
typedef char hc_cfg_assert_cal_idle_kp[(CAL_IDLE_KP == 2492u) ? 1 : -1];
typedef char hc_cfg_assert_cal_idle_ki[(CAL_IDLE_KI == 2494u) ? 1 : -1];
typedef char hc_cfg_assert_cal_idle_range_x10[(CAL_IDLE_RANGE_X10 == 2496u) ? 1 : -1];
typedef char hc_cfg_assert_cal_idle_rpm_band[(CAL_IDLE_RPM_BAND == 2498u) ? 1 : -1];
typedef char hc_cfg_assert_cal_pwm_invert[(CAL_PWM_INVERT == 2500u) ? 1 : -1];
typedef char hc_cfg_assert_cal_pwm_pad[(CAL_PWM_PAD == 2501u) ? 1 : -1];
typedef char hc_cfg_assert_cal_ign_map[(CAL_IGN_MAP == 3838u) ? 1 : -1];

#endif /* HC_CONFIG_GENERATED_H */
