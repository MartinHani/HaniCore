#ifndef HCDEADLINE711_H
#define HCDEADLINE711_H

/* Extended T1 capture ticks, 0.8 us. T7 compare uses the remaining delay.
   No signed-16 deadline arithmetic. */
#define HC_DL_N 24u
#define HC_DL_NONE 255u
#define HC_DL_DWELL 1u
#define HC_DL_SPARK 2u
#define HC_DL_OPEN 3u
#define HC_DL_CLOSE 4u
#define HC_DL_MAXDWELL 5u
#define HC_DL_BENCH_IGN 6u
#define HC_DL_BENCH_INJ 7u
#define HC_DL_BENCH_INJ_P8 8u
#define HC_DL_GUARD 16u
#define HC_DL_CHECKPOINT 16000u
#define HC_DL_MAX_AHEAD 250000uL
#define HC_DL_OFF_TICKS 125u /* software separation, not injector calibration */
#define HC_DL_OK 0u
#define HC_DL_FULL 1u
#define HC_DL_STALE 2u
#define HC_DL_HORIZON 3u
#define HC_DL_OVERLAP 4u
#define HC_DL_PERMISSION 5u
#define HC_DL_OVERDWELL 6u
#define HC_DL_LATE 7u
#define HC_DL_EXHAUSTED 8u
#define HC_DL_INHIBIT 9u   /* publication refused: the executor is quiescing */

typedef struct {
    unsigned int fuel_us, dead_us, requested_us, scheduled_us, delivered_us;
    unsigned int token, on_stamp, next_legal, flags;
    unsigned long on_time, legal_time;
} hc_dl_inj_t;
typedef struct {
    unsigned int planned[4], executed[4], armed, suppressed, cancelled;
    unsigned int clipped, rejected, late, max_late, reason;
    unsigned int requested_tick, compare_tick, command_tick;
    hc_dl_inj_t inj[8];
    unsigned int cooldown;
    unsigned int bench_token, bench_done;
    unsigned char bench_type, bench_mask;
    unsigned char ovd_one, ovd_two;
} hc_dl_diag_t;
#define HC_DL_DIAG (*(hc_dl_diag_t huge *)(TGT_EXTRAM_BASE + TGT_RAM_DEADLINE))
typedef struct {
    unsigned long accepted[8], delivered[8];
    unsigned int progress_ticket[8], accepted_ticket[8];
    unsigned int next_angle[8]; /* minimum configured interval on each output */
} hc_dl_width_t;
#define HC_DL_WIDTH (*(hc_dl_width_t huge *)(TGT_EXTRAM_BASE+TGT_RAM_SCHEDPLAN+144uL))
typedef char dl_width_fits[(144u+sizeof(hc_dl_width_t)<=TGT_RAM_SCHEDPLAN_LIMIT)?1:-1];

extern volatile unsigned int hc_dl_generation;
extern volatile unsigned char hc_dl_count;
/* QUIESCE. hc_deadline_quiesce() withdraws timing integrity:
   no coil charge or injector opening that was queued before it may start,
   every OFF already committed (spark, its backstop, injector close) still
   executes at its own time, and what the planner publishes afterwards - a
   new generation - is admitted at once (hc_dl_stale_id/_n). Before this a
   sync loss or a capture-ring overflow called hc_deadline_cancel(), which
   RELEASES every charging coil at once - and on this hardware a release IS a
   spark (CK110: input high = low-side = the falling edge that fires the
   coil). Overload therefore made a spark at an angle nobody chose.
   hc_dl_inhibit is the EXECUTOR fault latch (HC_Q_EXECUTOR, hcrtmon711.c):
   nothing is admitted or switched ON until the engine has stopped. */
extern volatile unsigned char hc_dl_inhibit;
extern unsigned int hc_dl_stale_id;     /* quiesce: entries up to this token */
extern unsigned char hc_dl_stale_n;     /* ... and how many of them remain   */
/* Incremented by every CC25 dispatch - including the empty 12.8 ms
   checkpoint - so a supervisor that never sees it move knows the executor is
   dead even with nothing queued (hcsafety.c hc_rt_supervise). */
extern volatile unsigned int hc_dl_beat;
void hc_deadline_quiesce(unsigned char reason);
unsigned char HC_COLD hc_deadline_health(void);   /* supervisor input, see plan711.c */
void HC_COLD hc_deadline_init(void);
void HC_COLD hc_deadline_abort_history(void); /* main, while executor inhibited */
void HC_COLD hc_deadline_cancel(void);   /* abort: release everything now */
unsigned long hc_deadline_capture_time(void);
unsigned long far hc_deadline_ticks_us_f(unsigned long ticks);
unsigned int HC_COLD hc_deadline_bench_start(unsigned char type, unsigned char channel, unsigned int ticks);
void HC_COLD hc_deadline_bench_stop(void);
void HC_COLD hc_deadline_fuel_cut(void);
void HC_COLD hc_deadline_publish_diag(void);
unsigned long HC_COLD hc_deadline_inj_request(unsigned char mask,unsigned int fuel,unsigned int dead,unsigned long period);
unsigned int HC_COLD hc_deadline_inj_admitted(unsigned char mask,unsigned int id,unsigned int generation,unsigned long duration);
unsigned char HC_COLD hc_deadline_flash_admit(unsigned int guard_ticks);
/* Task only. Capture generation BEFORE planning, pass it on every publication.
   ON reserves its OFF first; spark uses the last admitted dwell's token.
   ahead is relative to T1 stamp and can exceed one timer wrap. */
unsigned int HC_COLD hc_deadline_publish(unsigned int generation, unsigned int stamp,
    unsigned long ahead, unsigned char type, unsigned char mask,
    unsigned long duration);
unsigned int HC_COLD hc_deadline_plan_offset(unsigned int kind, unsigned int proposed);
void hc_deadline_dispatch(void); /* real backend, called only by CC25 ISR */
unsigned int HC_COLD hc_hal_deadline_out(unsigned char base, unsigned int mask,
                                 unsigned char on);
unsigned int hc_hal_deadline_ports(unsigned char base, unsigned int mask,
    unsigned char physical, unsigned char on);
#endif
