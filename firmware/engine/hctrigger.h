/*
 * hctrigger.h - crank/cam decoding and engine position.
 *
 * The layering here is deliberate and is the one thing about this file that
 * matters most (the maintainer's design notes):
 *
 *     physical edge      CC15 capture, hardware timestamp
 *          |
 *     TRIGGER DECODER    pattern-specific. Knows what a wheel looks like.
 *          |             Emits: tooth index, and "the gap is here".
 *          v
 *     ENGINE POSITION    pattern-INDEPENDENT. Owns sync, phase, crank angle,
 *          |             the cylinder counter and the loss counters.
 *          v
 *     ANGLE SCHEDULER    later milestone
 *
 * Everything above the decoder never learns what a trigger wheel looks like,
 * so adding 36-2, 60-2-2-2, 36-1 or an OEM pattern later is one decoder and a
 * configuration value - not a rewrite of the position logic.
 *
 * The state machine and the counter names follow Bosch's own %REVCALC/%REVDET
 * in the MS 4 Sport Funktionsrahmen, because their decomposition is right and
 * because sharing their vocabulary keeps the documentation useful:
 *
 *     synched_b    engine position synchronised          -> TRG_SYNC_CRANK
 *     phsok_b      phase signal ok                       -> TRG_SYNC_FULL
 *     synccorr_c   engine position CORRECTIONS counter
 *     synclost_c   engine position LOSS counter
 *
 * The single most important idea taken from them is that those last two are
 * SEPARATE. One disagreeing tooth is a correction that is counted and
 * absorbed; only repeated disagreement is a loss. An ECU that drops sync on
 * every bit of noise cannot run an engine.
 *
 * MS 4 Sport is not stock ME7 and none of its registers or vectors are assumed
 * here - only its decomposition.
 */
#ifndef HCTRIGGER_H
#define HCTRIGGER_H

/* Sync states. Ordered, so ">= TRG_SYNC_CRANK" is a meaningful test. */
#define TRG_NO_SIGNAL     0     /* no edges within the timeout            */
#define TRG_COUNTING      1     /* edges arriving, no gap identified yet  */
#define TRG_GAP_SEEN      2     /* one gap, position not yet proven       */
#define TRG_SYNC_CRANK    3     /* synched_b: 360 deg known, 720 not      */
#define TRG_SYNC_FULL     4     /* phsok_b: cylinder identified           */

/* A reason is a contract, not a prose log. It survives after recovery so a
   bench trace can distinguish a stall from noise or malformed geometry. */
#define TRG_LOSS_NONE             0
#define TRG_LOSS_STALL            1
#define TRG_LOSS_EARLY_GAP        2
#define TRG_LOSS_MISSING_GAP      3
#define TRG_LOSS_MALFORMED_GAP    4
#define TRG_LOSS_EXTRA_EDGE       5
#define TRG_LOSS_CAM_WINDOW       6
#define TRG_LOSS_CAM_MISSING      7
#define TRG_LOSS_CAM_PATTERN      8   /* cam level did not alternate */
#define TRG_LOSS_CAM_PHASE        9   /* cam level contradicted the claimed half */

void          trg_init(void);

/* Called from the main loop. Owns everything that must not run in an ISR:
   the 32-bit divide for rpm, and the stall timeout. */
void          trg_service(void);

/* Published state. All written in interrupt context, read anywhere. */
extern unsigned char trg_state;
extern unsigned int  trg_rpm;
extern unsigned int  trg_tooth;        /* 0 = first tooth after the gap   */
extern unsigned int  trg_teeth_seen;
extern unsigned int  trg_gaps;
extern unsigned int  trg_synccorr;     /* Bosch synccorr_c                */
extern unsigned int  trg_tooth_corr;   /* +/-1 tooth corrections     */
extern unsigned int  trg_cycle_acq, trg_cycle_lost, trg_ph_noalt, trg_ph_status;
extern unsigned int  trg_cam_lo_w_x10, trg_cam_hi_w_x10;
extern unsigned int  trg_synclost;     /* Bosch synclost_c                */
extern unsigned int  trg_last_dt;      /* last tooth period, ticks        */
extern unsigned int  trg_cam_edges;
extern unsigned int  trg_cam_tooth;    /* Bosch camshaftpos               */
extern unsigned int  trg_rev;          /* Bosch crankrev_c                */
extern unsigned int  trg_loss_reason;
extern unsigned int  trg_noise_edges;
extern unsigned int  trg_gap_metric_x10;
extern unsigned int  trg_gap_detected;
extern unsigned int  trg_gap_pending;
extern unsigned int  trg_engine_deg_x10;
extern unsigned int  trg_stall_state;
extern unsigned long trg_crank_period;
extern unsigned int  trg_last_edge_t1;  /* T1 timestamp of last crank edge */

extern unsigned int  trg_cam1_edges;
extern unsigned int  trg_cam2_edges;
extern unsigned int  trg_cam1_tooth;
extern unsigned int  trg_cam2_tooth;
extern unsigned int  trg_cam1_window;
extern unsigned int  trg_cam2_window;
extern unsigned int  trg_cam_error;
extern unsigned int  trg_cam_loss_reason;
extern unsigned int  trg_cam1_raw;
extern unsigned int  trg_cam2_raw;
extern unsigned int  trg_cam1_angle;   /* observed falling edge, deg x10 */
extern unsigned int  trg_cam2_angle;

/* The synthetic crank generator. There is no engine and no signal generator on
   the bench, so the decoder has to be exercisable without either - and this
   also stays afterwards as the regression test. Driven from the main loop, and
   only ever active while the real capture is disabled, so the two can never
   both feed the decoder. */
void          trg_sim_service(void);
extern unsigned int trg_sim_rpm;       /* 0 = off */

/* Teeth whose period is already past a third of T0's 43.76 ms wrap, so the
   gap that follows cannot be timed. Non-zero means "slower than this decoder
   can honestly measure" - about 69 rpm on a 60 tooth wheel - NOT a fault. */
/* The last CLEAN tooth period, in timer ticks. Use this and not trg_last_dt
   for anything that converts between time and angle: trg_last_dt is the raw
   last period and at the gap edge it spans three tooth positions. */
extern unsigned int trg_tooth_dt;

extern unsigned int trg_toolow;

/* Cost of the tooth interrupt, in timer ticks. trg_isr_headroom is what is
   left of the tooth period after it finished - when that reaches zero, teeth
   are lost and every angle derived from them is quietly wrong. */
extern unsigned int trg_isr_ticks;
extern unsigned int trg_isr_max;
extern unsigned int trg_isr_headroom;

/* ------------------------------------------------- what is CONFIGURED -----
 *
 * The decoder publishes the geometry it resolved out of the page, and it does
 * that because until V55 there was no geometry in the page to publish: the
 * wheel was three #defines inside the target's own trigger file. A bench that
 * cannot read back what the firmware believes it is decoding has to infer it
 * from behaviour, and "no sync" reads identically whether the signal is wrong
 * or the configuration is.
 *
 * trg_cam_resolves is the one that is easy to miss. An even number of equally
 * spaced cam references is invariant under a 360 degree shift, so it cannot
 * say which revolution the engine is in, and the decoder will never claim
 * TRG_SYNC_FULL from one. Zero here with a live cam is not a fault.
 *
 * trg_cfg_generation counts how many times the geometry has been re-read at
 * RPM zero. It is how a rig proves a TunerStudio edit reached the decoder. */
extern unsigned int trg_cfg_teeth;         /* SY_TEETH, as resolved         */
extern unsigned int trg_cfg_gap;           /* SY_GAP, as resolved           */
extern unsigned int trg_cfg_ratio_x10;     /* gap ratio in force, x10       */
extern unsigned int trg_cfg_min_teeth;
extern unsigned int trg_cfg_tooth_x10;     /* one tooth, 0.1 crank degrees  */
extern int trg_cfg_angle_x10;              /* trigAngleX10 in force   */
/* tooth #1's physical angle (the stored s16 word, 0.1 deg ATDC) ->
   the decoder's internal rotation 0..3599. The ONLY conversion; see
   hctrig_me711.c. */
unsigned int hc_trig_rotation_x10(unsigned int stored);
extern unsigned int trg_cfg_cam_refs;
extern unsigned int trg_cfg_cam_ref_x10;   /* first reference, 0.1 deg      */
extern unsigned int trg_cfg_cam_window_x10;
extern unsigned int trg_cfg_crank_edge;    /* 0 falling, 1 rising           */
extern unsigned int trg_cfg_cam_edge;
extern unsigned int trg_cam_resolves;      /* 1 = the cam decides the cycle */
extern unsigned int trg_cfg_generation;

/* WHICH CAPTURE CHANNEL ENDED UP DOING WHAT, three nibbles, low to high:
   CC15, CC8, CC9. 0 = unused, 1 = crank, 2 = cam 1, 3 = cam 2.
   The Porsche board default resolves to 0x0321 - crank on CC15 (cavity 82),
   cam 1 on CC8 (cavity 86), cam 2 on CC9 (cavity 87) - which is exactly the
   arrangement every image from V55 to V61 compiled in.
   It is published because "the page says cavity 86" and "the hardware is
   capturing cavity 86" are different statements, and before V62 there was no
   way to tell them apart without a reflash. */
extern unsigned int trg_cfg_capture_map;

/* Which half of the 720 degree cycle the crank is in: 0 = first revolution,
   1 = second. Only meaningful once trg_state reaches TRG_SYNC_FULL. */
extern unsigned char trg_phase;
extern unsigned int  trg_phsok_c;
extern unsigned int  trg_phase_corr;
extern unsigned int  trg_phase_lost;

#endif /* HCTRIGGER_H */
