#ifndef HCRTMON711_H
#define HCRTMON711_H
/* Runtime health record.
 *
 * Cheap high-water marks and counters written where the event happens - the
 * crank ISR, the planner level, CC25, the tick supervisor, the main loop -
 * and read off the ECU through the extended output-channel window (after the
 * event ring, hctarget.h TGT_RT_EXPORT_BYTES), big-endian like every channel.
 * Formatting and judgement are host-side (tools/vehicle, the stress rig,
 * tests/firmware/trigger/me711_runtime_stress_proof.py). Zeroed at boot.
 *
 * Units: T = 0.8 us timer ticks (T1/T7), ms = the 1 ms tick. */
#include "hctarget.h"

typedef struct {
    unsigned int ver;           /*  0 HC_RT_VER                                 */
    unsigned int plan_lat_max;  /*  1 T: walked tooth captured -> walk, worst    */
    unsigned int plan_run_max;  /*  2 T: one planner-level run, worst            */
    unsigned int cap_hwm;       /*  3 teeth waiting in the capture ring, worst  */
    unsigned int dlq_hwm;       /*  4 deadline-queue entries, worst (of HC_DL_N) */
    unsigned int quiesce_n;     /*  5 integrity withdrawals (hc_deadline_quiesce) */
    unsigned int quiesce_last;  /*  6 the last one's HC_Q_* reason               */
    unsigned int beat_age_max;  /*  7 ms: longest CC25 heartbeat silence seen   */
    unsigned int rt_fault;      /*  8 hc_rt_fault (HC_RT_F_*), latched           */
    unsigned int exec_faults;   /*  9 executor faults the supervisor acted on    */
    unsigned int ustk_hwm;      /* 10 bytes of the 512-byte user stack, worst    */
    unsigned int sstk_hwm;      /* 11 bytes of the 634-byte system stack, worst  */
    unsigned int pass_max;      /* 12 T: one main-loop pass, worst (wraps 52 ms) */
    unsigned int wdt_gap_max;   /* 13 ms between two watchdog services, worst    */
    unsigned int svc_eng;       /* 14 T: eng_service, worst                      */
    unsigned int svc_dbw;       /* 15 T: hc_dbw_service, worst                   */
    unsigned int svc_diag;      /* 16 T: one telemetry-publication slice, worst  */
    unsigned int svc_lambda;    /* 17 T: hc_io_lambda_service, worst             */
    unsigned int svc_other;     /* 18 T: idle..cel service group, worst          */
    unsigned int rx_hw_ovr;     /* 19 ASC0 receive overruns (a byte destroyed)   */
    unsigned int rx_hwm;        /* 20 receive ring bytes waiting, worst          */
    unsigned int rx_lost;       /* 21 receive bytes the ring could not take      */
    unsigned int tx_bytes;      /* 22 bytes transmitted (wraps)                  */
    unsigned int plan_runs;     /* 23 planner-level runs (wraps)                 */
    unsigned int pec_exhaust;   /* 24 PEC6 count found at zero (bytes lost)      */
    unsigned int dbw_gap_max;   /* 25: largest DBW step interval in RUN, ms      */
    unsigned int svc_comms;     /* 26 T: main-context protocol service, worst    */
    unsigned long abort_time;   /* 27..28 T: catastrophic release stamp          */
    unsigned int abort_pending;/* 29 diagnostic cleanup outstanding             */
    unsigned int clock_last;   /* 30 T1 at the last independent supervision     */
    unsigned int clock_frac;   /* 31 residual ticks below one millisecond        */
} hc_rt_t;
#define HC_RT_VER 0x0001u
/* Near RAM, at an address reserved by the linker: 0xF280 precedes the
   serial transport state and the user stack's guard band. A near operand keeps every update a
   single 4-byte instruction in the ISRs that make them. */
#define TGT_RTMON_ADDR 0xF280u
#define HC_RT (*(hc_rt_t volatile *)TGT_RTMON_ADDR)
typedef char hc_rt_fits[(sizeof(hc_rt_t) <= 0x40u) ? 1 : -1];
#define HC_RT_MAX(field, v) do { unsigned int _v = (v); \
    if (_v > HC_RT.field) HC_RT.field = _v; } while (0)
#define HC_RT_INC(field) do { if (HC_RT.field != 0xFFFFu) HC_RT.field++; } while (0)

void far hc_rtmon_init(void);
void far hc_rtmon_service(unsigned int now_ms);   /* main loop: scans, mirrors */
unsigned char far hc_rt_byte(unsigned int off);   /* the extended window       */
unsigned char far hc_rtwit_byte(unsigned int off); /* the reset witness         */
void far hc_rtwit_frame_start(unsigned int t7);    /* S5500 raster, per frame   */
void far hc_rtwit_stall_set(unsigned char ms, unsigned char every_ms); /* '!Z'  */
void far hc_rtwit_stall_service(unsigned int now_ms); /* main loop, bench only   */
void far hc_irq_disable_all(void);
void far hc_rst_publish(void);                     /* reset-log target words   */                /* boot: every xxIC = 0     */
#endif
