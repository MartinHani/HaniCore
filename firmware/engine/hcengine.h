/*
 * hcengine.h - sensors, load, fuel quantity, ignition advance, dwell.
 *
 * Everything here runs in the MAIN LOOP. Nothing in this file is called from
 * an interrupt, and that is deliberate: turning counts into degrees Celsius
 * and looking up a bilinear map is arithmetic with no deadline, while the
 * things that do have deadlines - the tooth, the compare, the watchdog - must
 * never wait behind it.
 *
 * The sensor model is Bosch Motorsport's, from the MS 4 Sport function sheet
 * (the maintainer's design notes). Every analog input carries the same five
 * things, and the last two are the ones this project did not have:
 *
 *     x_u    the raw voltage, so a wiring fault is visible
 *     x      the physical value
 *     x_f    a filtered value, so a gauge is readable
 *     x_e    an ERROR FLAG for that sensor alone
 *     X_DEF  the value used WHILE that sensor is faulty
 *
 * V97: THE FAULT VALUE IS ONE NUMBER PER SENSOR, AND THE
 * DISPLAY, THE CONTROL VALUE AND EVERY CONSUMER SEE THAT SAME NUMBER:
 *     coolant and intake air  -40 C   (ENG_FAULT_TEMP_DC)
 *     manifold pressure         0 kPa (ENG_FAULT_MAP_X10)
 * The error bit (and its DTC and front-page lamp) is what says a value is a
 * fault value. The old substitutes - 80 C coolant for control only, 20 C (or
 * iatDefault) intake air, 100 kPa atmospheric - were hidden second values
 * and are gone; tools/me711_sensor_fallback_proof.py holds it.
 *
 * V98 (ME7.1.1): THE DISPLAY RULE STAYS, AND THE CONTROL VALUE BECOMES PER
 * CONSUMER - rusEFI's Sensor::get(..).value_or(x) at each call site. The
 * variables below still read -40 C / 0 kPa on a fault (gauges, logs, DTC);
 * each function that consumes one checks the error bit and uses its OWN
 * named fallback: warm-up 100 %, cranking fuel 20 C, air density 0 C,
 * timing corrections 0, wall film 90 C, DFCO and closed loop inhibited,
 * fuel pressure = the MAP estimate table (hcengctl711.c, hcengine.c
 * runtime_tail, hctrans711.c, hcboost711.c). the maintainer's design notes.
 */
#ifndef HCENGINE_H
#define HCENGINE_H

/* ------------------------------------------------------------- sensors -- */
extern unsigned int  eng_batt_dv;      /* battery, 0.1 V                    */
extern unsigned int  eng_clt_dc;       /* coolant, 0.1 degC + CAL_TEMP_BIAS -
                                          the CONTROL value (-40 C on a
                                          fault)                            */
extern unsigned int  eng_clt_meas_dc;  /* coolant as MEASURED through the
                                          curve, fault or not; 0 = no sample */
extern unsigned int  eng_map_kpa_x10;  /* manifold pressure, 0.1 kPa        */
extern unsigned int  eng_iat_dc;       /* intake air, 0.1 degC + BIAS       */
extern unsigned int  eng_baro_kpa_x10; /* ambient pressure, 0.1 kPa         */
extern unsigned int  eng_tps_x10;      /* throttle, 0.1 %                   */
extern unsigned int  eng_tps2_x10;     /* second throttle track, 0.1 %      */
extern unsigned int  eng_pedal_x10;    /* pedal, 0.1 %                      */
extern unsigned int  eng_pedal2_x10;   /* second pedal track, 0.1 %         */

/* The value a faulty sensor reads, for display and control alike. */
#define ENG_FAULT_TEMP_DC  ((unsigned int)((-40 + (int)CAL_TEMP_BIAS) * 10))
#define ENG_FAULT_MAP_X10  0u

/* One bit per sensor. A set bit means that sensor is out of its plausibility
   window and its FAULT VALUE (above) is used in every calculation below. */
extern unsigned int  eng_sensor_err;
#define ENG_ERR_CLT      0x0001u
#define ENG_ERR_MAP      0x0002u
#define ENG_ERR_TPS1     0x0004u
#define ENG_ERR_TPS2     0x0008u
#define ENG_ERR_PEDAL1   0x0010u
#define ENG_ERR_PEDAL2   0x0020u
#define ENG_ERR_TPS_DIFF 0x0040u   /* the two throttle tracks disagree   */
#define ENG_ERR_PED_DIFF 0x0080u   /* the two pedal tracks disagree      */
#define ENG_ERR_BATT     0x0100u
#define ENG_ERR_IAT      0x0200u   /* no channel, or out of range        */

/* --------------------------------------------------------- the outputs -- */
extern unsigned int  eng_load;         /* whatever CAL_LOAD_SOURCE selects  */
extern unsigned int  eng_rl_x10;       /* relative air charge, 0.1 % - THE
                                          canonical load. 100 % is the charge
                                          at 0 degC and 1013 hPa, ME7's own
                                          reference, so a naturally aspirated
                                          engine reads about 92 % at sea
                                          level. See hc_airfuel.h.          */
extern unsigned int  eng_air_mg_x10;   /* cylinder air mass, 0.1 mg         */
extern unsigned int  eng_ti_us;        /* injection pulse INCLUDING deadtime */
extern unsigned int  eng_ti_base_us;   /* before deadtime, for telemetry    */
extern unsigned int  eng_deadtime_us;
extern unsigned int  eng_afr_x10;      /* target AFR from the map           */
/* THE CANONICAL FUEL TARGET. Lambda x 1000, derived from eng_afr_x10 through
   the one configured stoichiometric ratio. AFR is the STORED form and a
   display convenience; lambda is what the engine, the wideband and any future
   closed loop are about, and it is the value to reason with. */
/* Lambda x 1000, DERIVED from eng_afr_x10 and CFG_U_STOICH_X100.
   A function, not a variable: see the definition for why the two
   bytes mattered. */
unsigned int eng_lambda_x1000(void);
#if defined(TGT_ENGINE_RUNTIME)
extern int           eng_adv_x10;      /* ignition advance, 0.1 deg BTDC,
                                          SIGNED - negative is after TDC     */
extern int           eng_adv_base_x10; /* the table/cranking angle      */
extern unsigned int  eng_ve_x10;       /* VE looked up, 0.1 %           */
extern unsigned int  eng_ve_load_x10;  /* the fuel table's load         */
#else
extern unsigned int  eng_adv_x10;      /* ignition advance, 0.1 deg BTDC    */
#endif
extern int           eng_ign_corr_x10; /* V97 (ME7.1.1): CLT+IAT timing correction, 0.1 deg */

/* ==================================== ENDPOINT GRAB, THE COMMISSIONING ACT ==
 *
 * "Move it there, and tell the ECU that this is there." rusEFI spells it
 *
 *     commandButton = "Grab Closed Throttle voltage", cmd_calibrate_tps_closed
 *     commandButton = "Grab Idle/Up",                 cmd_calibrate_pedal_up
 *
 * and it is the difference between a calibration a tuner can perform and four
 * raw counts they have to read off one gauge and retype into another field.
 *
 * WHAT IT WRITES, AND WHAT IT DOES NOT. It writes the LIVE calibration page in
 * RAM - CAL_TPS1_MIN and friends - and nothing else. It never touches flash.
 * The project rule is unchanged and this does not bend it: an ordinary edit
 * goes to RAM, and only an explicit Burn makes anything permanent. After a
 * grab the tune is modified and unburned, exactly as if the number had been
 * typed, and the .ini's own "Unsaved changes" light says so.
 *
 * MIN IS THE CLOSED READING AND MAX IS THE OPEN ONE, IN THAT ORDER AND WITHOUT
 * SORTING THEM. On a Bosch/VAG throttle body the first track FALLS as the
 * plate opens - rusEFI's own defaults for this body are tpsMin 890 and
 * tpsMax 70 - so a correct calibration has min > max, and span_pct_x10()
 * handles an inverted span deliberately. Sorting would throw the direction
 * away and read the throttle backwards.
 *
 * IT REFUSES RATHER THAN GUESSES, and says which reason:
 *
 *   the engine must be demonstrably stopped;
 *   the two channels must both exist on this board and be readable;
 *   neither raw count may be at a rail - an open input reads a clean, stable,
 *     completely wrong number, and a calibration built on one is worse than
 *     no calibration because nothing downstream can tell;
 *   once BOTH ends of a track are known they must differ by more than
 *     GRAB_MIN_SPAN counts. rusEFI's autocal calls this "check your wiring";
 *     a full travel calibrated into a few counts of noise makes the runtime
 *     treat noise as a 100 % command.
 */
#define ENG_GRAB_TPS_CLOSED   1u
#define ENG_GRAB_TPS_OPEN     2u
#define ENG_GRAB_APP_REST     3u
#define ENG_GRAB_APP_FULL     4u

#define ENG_GRAB_IDLE         0u  /* never asked on this power-up            */
#define ENG_GRAB_PASS         1u  /* both tracks written                     */
#define ENG_GRAB_RPM          2u  /* the engine is not demonstrably stopped  */
#define ENG_GRAB_NOCHANNEL    3u  /* this board cannot read one of the pair  */
#define ENG_GRAB_RAIL         4u  /* a raw count is at a rail - open circuit */
#define ENG_GRAB_SPAN         5u  /* the two ends are too close - check wiring */
#define ENG_GRAB_WHAT         6u  /* no such endpoint                        */
/* V90, ME7.1.1 '!G': PASS, both tracks written to DESIRED (the page
   TunerStudio reads) and the pair's correlation set SAME. */
#define ENG_GRAB_PASS_SAME    7u

/* Perform one grab and RETURN the ENG_GRAB_* verdict.
 *
 * IT PUBLISHES NOTHING ITSELF, and that is deliberate. A published value needs
 * storage, and storage in this file is NEAR RAM on both targets - 188 bytes
 * free against a 192-byte reserve was the cost of two words and one call tree.
 * The caller already owns an external-SRAM output-channel block; it puts the
 * answer there. Cold data goes to far memory, and
 * a value written when a human presses a button is as cold as data gets. */
#if defined(TGT_ENGINE_RUNTIME)
unsigned int far eng_calib_grab(unsigned char what);   /* hcengctl711.c */
#else
unsigned int eng_calib_grab(unsigned char what);
#endif
extern unsigned int  eng_dwell_x100;   /* dwell, 0.01 ms                    */
extern unsigned char eng_cranking;     /* 1 while below CFG_CRANK_RPM_MAX   */
extern unsigned char eng_warmup_pct;   /* enrichment applied, 100 = none    */

/* How fast the throttle is moving, 0.1 % per second, SIGNED. Published in its
   own right because it is the one number that says whether a lean spot was a
   tip-in or a fuelling error. */
extern int           eng_tps_rate;
extern unsigned int  eng_accel_us;     /* enrichment being added right now  */

/* Why fuel is being withheld, if it is. Zero means it is not. */
extern unsigned int  eng_fuelcut;
#define ENG_CUT_OVERRUN  0x0001u   /* closed throttle, above the cut speed  */
#define ENG_CUT_REV      0x0002u   /* the rev limiter                       */
#define ENG_CUT_BOOST    0x0004u   /* overboost                             */
#define ENG_CUT_LIMP     0x0008u   /* engine protection (V97, hclimp)       */
#define ENG_CUT_LOAD     0x0010u   /* authoritative pressure/model loss    */
#define ENG_CUT_LEAN     0x0020u   /* qualified persistent lean guard       */
#define ENG_CUT_ALL      (ENG_CUT_OVERRUN|ENG_CUT_REV|ENG_CUT_BOOST|ENG_CUT_LIMP|ENG_CUT_LOAD|ENG_CUT_LEAN)

void eng_init(void);

/* Once per main-loop pass. Cheap: one map lookup and a handful of curves. */
void eng_service(void);
#if defined(TGT_ENGINE_RUNTIME)
/* Sensor acquisition and calculation are separate bounded main units. */
void eng_acquire(void);
void eng_calculate(void);
#endif

#endif /* HCENGINE_H */
