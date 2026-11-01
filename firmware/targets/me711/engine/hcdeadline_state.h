#ifndef HCDEADLINE_STATE_H
#define HCDEADLINE_STATE_H
/* Private near state shared with task-only FCODE publication. */

/* Planner-owned context for the cold live-offset guard. No lower level may
   mutate it while the planner is running. The capture ISR only appends teeth. */
extern unsigned long hc_plan_epoch;
extern unsigned int hc_plan_generation, hc_plan_acc;
extern unsigned char hc_plan_acc_bad;
extern unsigned int TGT_PLAN_CAP_MEM hc_plan_cap_angle[TGT_PLAN_CAP_N], TGT_PLAN_CAP_MEM hc_plan_cap_stamp[TGT_PLAN_CAP_N];
extern volatile unsigned char hc_plan_cap_head, hc_plan_cap_tail;
unsigned int far hc_plan_advance_epoch_f(unsigned int angle);
void far hc_plan_collect_f(void);
void far hc_plan_count_tooth_f(unsigned int angle);
extern unsigned int hc_plan_cycle, hc_plan_angle, hc_plan_ahead;
extern unsigned int hc_plan_ign_anchors[], hc_plan_inj_anchors[];
extern unsigned char hc_plan_cursors[4];
extern unsigned char hc_plan_inj_slots[], hc_plan_inj_masks[];
void far hc_plan_merge_f(unsigned int *ang, unsigned char *slot,
                         unsigned char *msk, unsigned char *n);
void far hc_plan_spans_f(unsigned char n);
/* the cold planner routines (hcdeadline_plan711.c) and their state */
extern unsigned char hc_plan_angle_valid, hc_plan_ig_n, hc_plan_in_n, hc_plan_cursors_valid;
extern unsigned char hc_plan_ign_masks[];
extern unsigned int w_window;
void far hc_plan_epoch_rebase_f(void);
void far hc_plan_seed_f(unsigned int angle, unsigned int off_dw, unsigned int off_sp,
                        unsigned int off_is, unsigned int off_ie);
void far hc_plan_remap360_f(void);
extern volatile unsigned long hc_dl_q_time[HC_DL_N];
extern volatile unsigned int hc_dl_q_id[HC_DL_N];
extern volatile unsigned char hc_dl_q_type[HC_DL_N], hc_dl_q_mask[HC_DL_N], hc_dl_q_next[HC_DL_N];
extern volatile unsigned char hc_dl_q_head;
extern unsigned char hc_dl_done_head, hc_dl_done_tail;
extern unsigned char hc_dl_done_channel, hc_dl_cooldown_channel;
extern volatile unsigned char hc_dl_corrupt;
extern volatile unsigned int hc_dl_revision;
extern unsigned int hc_dl_token, hc_dl_owner[16];
extern unsigned int hc_dl_active_inj[8];
extern unsigned char hc_dl_reserved_ign, hc_dl_reserved_inj, hc_dl_on_ign, hc_dl_on_inj;
extern unsigned char hc_rt_ign_fresh;
extern unsigned char hc_plan_coincide;
extern unsigned long hc_dl_clock_ticks;
extern unsigned int hc_dl_clock_last;
unsigned long far hc_deadline_now_f(void);
unsigned long far hc_deadline_ticks_us_f(unsigned long ticks);
void far hc_deadline_arm_f(void);
void far hc_hal_deadline_prepare_f(void);
void far hc_deadline_bench_port_f(unsigned char type, unsigned char mask, unsigned char on);
extern unsigned char hc_hal_actuator_route[16];
unsigned int far hc_hal_deadline_ports_f(unsigned char base, unsigned int mask,
    unsigned char physical, unsigned char on);
#endif
