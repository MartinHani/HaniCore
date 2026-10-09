/* Internal DBW SRAM layout, shared only with cold diagnostic code. */
#ifndef HC_DBW_STATE_H
#define HC_DBW_STATE_H
#include <stddef.h>
typedef struct {
    unsigned char st;
    unsigned int  flt;
    unsigned int  tgt, act, duty, pedal;
    unsigned int  a1, a2, t1, t2;
    int           err;
    unsigned char dir, on;
    long          integ;
    long          irem;              /* the integral term's carried remainder */
    int           prev_act;          /* derivative history: measured plate */
    unsigned int  prev_sample_ms;    /* acquisition time, not service time */
    unsigned int  step_mark;         /* tick of the last control step        */
    unsigned int  dev_since;         /* tick the deviation started           */
    unsigned char dev_pending;
    int           dev_e;             /* the error at the last step     */
    unsigned int  steps;
    unsigned int  tgt_ramped;        /* the rate-limited target              */
    /* DOES THIS CONTROLLER HOLD THE BRIDGE? See hc_dbw_shutdown().
       Lives here rather than in near RAM because the whole state block is
       already in external SRAM, and it is written on transitions only. */
    unsigned char held;
    /* CONSECUTIVE SERVICE PASSES WITH EVERY PLAUSIBILITY CHECK SATISFIED.
       DBW_INIT's whole content: the bridge stays down until this reaches
       DBW_INIT_PASSES, and ANY refusal resets it to zero. */
    unsigned char settle;
    /* the ETB endpoint calibration and the autotune moved to
       hcetbcal.c (FCODE) with their own SRAM region, TGT_RAM_ETBCAL. */
    /* the terms of the last step (telemetry: WHY the duty is what it
       is), the battery factor, the sensor-fault debounce and the
       commissioning override. */
    int           p_t, d_t, ff_t, out_t;
    unsigned int  vfac;              /* x1000                               */
    unsigned int  pend;              /* DBW_F_* sensor bits being debounced */
    unsigned int  pend_since;
    unsigned int  ovr;               /* 0xFFFF = no override                */
    unsigned int  requested;          /* target before production slew limiter */
    unsigned int  clears;
    unsigned char key;               /* the key as last reported            */
    unsigned char busy, align_pending;
    unsigned int align_since;
    unsigned int integral_target, integral_quiet_ms;
    unsigned char integral_allowed;
    /* START-UP READINESS. 0 = no sample seen since init, 1 =
       waiting since ready_since, 2 = every track the loop needs has been
       fresh and paired once. Until 2 a missing sample is "not yet", not a
       stale sensor (hc_dbw.c not_ready()). */
    unsigned char ready;
    unsigned int  ready_since;
    /* The largest interval between two control steps while in
       RUN, ms - the cadence the PID really got (hc_dbw_gap_max()). */
    unsigned int  gap_max;
} hc_dbw_state_t;
/* The linked runtime rig observes this counter independently of tick time. */
typedef char hc_dbw_steps_layout[(offsetof(hc_dbw_state_t,steps)==44u)?1:-1];

#define D  (*(hc_dbw_state_t huge *)(TGT_EXTRAM_BASE + TGT_RAM_DBW))
typedef char hc_dbw_state_fits[(sizeof(hc_dbw_state_t) <= TGT_RAM_DBW_LIMIT)
                               ? 1 : -1];


#endif
