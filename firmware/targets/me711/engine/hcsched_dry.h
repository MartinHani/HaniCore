#ifndef HCSCHED_DRY_H
#define HCSCHED_DRY_H

#define HC_DRY_DWELL_START  1u
#define HC_DRY_SPARK         2u
#define HC_DRY_INJ_START     3u
#define HC_DRY_INJ_END       4u

void hc_drysched_init(void);
void hc_drysched_tooth(unsigned int angle_x10, unsigned int stamp,
                       unsigned int tooth_dt);
void hc_drysched_service(unsigned int now, unsigned int sync_state);
void hc_drysched_time_service(unsigned int now);
/* Withdraw timing integrity (quiesce, hcdeadline711.h): no new charge or
   opening, committed OFF edges still execute. Any context. */
void hc_drysched_cancel(unsigned int reason);
/* Release every engine output NOW (route change at rpm 0, executor fault). */
void hc_drysched_abort(unsigned int reason);
/* hc_deadline_quiesce() reasons, published in the runtime health block */
#define HC_Q_WITHDRAWN  1u    /* sync loss, permission, strategy sync       */
#define HC_Q_OVERFLOW   2u    /* the planner fell CAP_N - 1 teeth behind    */
#define HC_Q_STALE      3u    /* a capture waited more than 26 ms           */
#define HC_Q_EXECUTOR   4u    /* the runtime supervisor: CC25 not alive     */
/* copy the last planned tooth into HC_KN711.snap_* (the knock driver) */
void hc_drysched_snap(void);

/* Long-horizon angle-domain interface. The eventual ignition/injection
   planners use this rather than constructing 16-bit timer deadlines. The
   event remains software-staged until it enters one physical tooth window. */
unsigned int hc_drysched_schedule_after(unsigned int angle_x10,
                                        unsigned char type,
                                        unsigned char slot);
/* Test hooks for the epoch. 3.6 billion counts cannot be simulated one tooth
   at a time, and a defect that only appears after two hours of running is
   exactly the one that needs a test. No protocol binding, no output path. */
void HC_COLD hc_drysched_test_set_epoch(unsigned int hi, unsigned int lo);
unsigned int HC_COLD hc_drysched_test_epoch_hi(void);
unsigned int HC_COLD hc_drysched_test_epoch_lo(void);

void hc_drysched_test_anchor(unsigned int angle_x10);
void hc_drysched_test_advance(unsigned int angle_x10, unsigned int stamp,
                              unsigned int tooth_dt);

extern unsigned int dry_sched_queued, dry_sched_executed;
extern unsigned int dry_sched_cancelled, dry_sched_late, dry_sched_missed;
extern unsigned int dry_sched_max_latency, dry_sched_next_angle;
/* per-event-kind lateness (dwell start / spark / injection): the worst
   case and a six-bucket histogram on 0.25 ms boundaries. The aggregate
   counters above cannot say how late a SPARK was, which is what sets
   delivered ignition timing - bench measurements. */
/* per-kind (dwell/spark/injection) lateness is NOT implemented - it
   needs ~60 bytes of NCODE and the image has 14. See hcsched_dry.c
   DRY_LK_* and bench measurements. */
extern unsigned int dry_sched_last_angle, dry_sched_capture_overflow;
/* Epoch rebases. Increments about every two hours at 7500 rpm; a bench
   that never sees it increment has simply not run long enough. */
/* Events issued immediately because the offset (advance, dwell) moved
   further between two teeth than the crank did, stepping the cursor over
   them. Not an error - a number, so a bench can see it. */
extern unsigned int dry_sched_catchup;
extern unsigned int dry_sched_overdwell;   /* coils released by the max-dwell watch */
extern unsigned int hc_ign_ovd_latch;      /* coils latched OFF after an overdwell */
/* the maximum-dwell watch - main loop and serial yield, 1 ms gated. */
void hc_drysched_overdwell_service(unsigned int now);
extern unsigned int dry_sched_rebases;
extern unsigned int dry_sched_pending, dry_sched_status;
/* TRG_SYNC_CRANK or TRG_SYNC_FULL: what the CONFIGURED strategies need
   before anything may be scheduled. Sequential injection and sequential
   COP need a 720-degree position; batch, semi-sequential, wasted paired,
   WASTED COP and a distributor do not. */
extern unsigned int dry_sched_need_sync;
extern unsigned int dry_next_ign_slot, dry_next_inj_slot;
extern int          dry_spark_advance_x10;  /* signed, 0.1 deg BTDC */
extern unsigned int dry_dwell_x100, dry_inj_pulse_us;
extern unsigned int dry_dwell_start_angle, dry_spark_angle;
extern unsigned int dry_inj_start_angle, dry_inj_end_angle;

/* TRUE SEQUENTIAL WITH A FALLBACK (the maintainer's design notes).
 * A sequential strategy plans every cylinder's event AND its twin 360 deg
 * later (slot | HC_SLOT_TWIN). Without cycle sync both fire - wasted COP and
 * two half pulses per cylinder, which is phase-agnostic. With cycle sync
 * the twin is dropped: a cylinder switches ONLY AT ITS OWN TWIN EVENT (a
 * skipped twin puts it in sequential, a fired twin takes it out), so the
 * fuel mass per intake is conserved through every transition in both
 * directions. The injector CLOSES BY TIME (start + its own width), so the
 * width can differ per event. */
#define HC_SLOT_TWIN        0x80u
#define HC_SLOT_MASK        0x7Fu     /* the slot without the twin flag */
extern unsigned char dry_seq_active;     /* 1: some cylinder is in true sequential */
extern unsigned int  dry_seq_inj_mask;   /* bit per injector slot in sequential   */
extern unsigned int  dry_seq_skips;      /* twin events dropped (ign + inj)       */
extern unsigned int  dry_seq_enters;     /* fallback -> sequential switches       */
extern unsigned int  dry_seq_leaves;     /* sequential -> fallback switches       */
extern unsigned int  dry_inj_width_us;   /* the last injection's own width        */
extern unsigned int  dry_inj_nofree;     /* injections refused: no queue slot     */

/* WHAT THE ENGINE-CONTROL LAYER (hcengctl711.c, main loop) HANDS THE
 * TOOTH PATH - one near load each where it is used.
 *   dry_skip_ratio     spark events skipped out of 255 (launch, flat shift,
 *                      anti-lag, rotational idle); the rev limiter's spark
 *                      cut is added here, once a millisecond
 *   dry_rev_limit/hyst the hard rev limit in force (pit limiter included)
 *   dry_inj_phase_x10  the injection angle (single angle or the table)
 *   dry_rev_spark_cut  1 while the rev limiter cuts spark
 *   hc_prime_on        the key-on priming pulse is open (hchal permits the
 *                      injectors for it with the engine stopped) */
extern unsigned char dry_skip_ratio, dry_rev_spark_cut;
extern unsigned int  dry_rev_limit, dry_rev_hyst, dry_inj_phase_x10;
extern unsigned char hc_prime_on;
extern unsigned int  dry_spark_skips;     /* sparks skipped by a cut ratio */
/* Open every routed injector for `t8` x 8 T1 ticks (6.4 us), engine
   stopped; closed from hc_drysched_service() (main loop AND the 1 ms serial
   yield), so a long reply cannot stretch it. Refused (0) while anything is
   queued or the crank turns. */
unsigned char HC_COLD hc_drysched_prime(unsigned int t8);  /* FCODE */

/* THE TOOTH PROFILE - where in the revolution the crank is slow.
 *
 * '!K' mode 1 COMPRESSION: engine stopped at the request; spark and fuel are
 * held off (HC_INHIBIT_TEST) while the operator cranks; every synchronised
 * tooth's period is summed per 6-degree bin; the test ends when the crank
 * stops (or 30 s). The slowest bins are the compression TDCs - a physical
 * crank-angle reference that needs no timing light.
 * '!K' mode 2 RUNNING: the same profile with outputs untouched, 64
 * revolutions - where combustion accelerates the crank.
 * '!K' mode 0 aborts. Bins are ENGINE angle mod 360 (bin = angle / tooth);
 * physical = engine - trigAngleX10 (mod 360). Published per mille of the mean tooth
 * through the extended output-channel window. */
#define HC_TL_IDLE     0u
#define HC_TL_ARMED    1u      /* compression: waiting for the crank     */
#define HC_TL_RUN      2u
#define HC_TL_DONE     3u
#define HC_TL_REFUSED  4u      /* engine was turning at the request      */
#define HC_TL_ABORTED  5u
#define HC_TL_TIMEOUT  6u      /* armed 30 s, never cranked             */
/* high-byte flag - this finished profile was RESTORED at boot from the
   sealed copy in SRAM (it was taken before a reset / key-off). The mode is
   then (state >> 8) & 0x3F. */
#define HC_TL_RESTORED 0x4000u
extern unsigned char hc_tl_inhibit, hc_tl_active;
extern unsigned int hc_tl_state, hc_tl_revs, hc_tl_teeth;
void HC_COLD hc_tl_request(unsigned char mode, unsigned int tick_ms);
void HC_COLD hc_tl_service(unsigned int tick_ms);

void HC_COLD hc_tl_add(unsigned int angle, unsigned int dt, unsigned int tooth);
void HC_COLD hc_tl_init(void);

#endif
