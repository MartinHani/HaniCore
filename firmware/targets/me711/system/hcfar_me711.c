/*
 * hcfar_me711.c - far THUNKS into NCODE for the modules compiled MEDIUM.
 *
 * Compiled SMALL, so it links into NCODE (segment 0x84) and each body is a
 * near call to the real function. Each thunk is declared `far`, so it is
 * entered with CALLS and returns with RETS. See hcfarbridge.h for why, and for
 * the rename list that must stay in step with this file.
 *
 * Nothing here may hold state or do work: a thunk is a calling-convention
 * adapter and nothing else, so the callee's behaviour is unchanged.
 */
#include <reg167.h>
#include "hcsafety.h"
#include "hcpower.h"
#include "hcnvm.h"
#include "hchal_me711.h"
#include "hcburnforensics.h"
#include "hcengine.h"
#include "hcasic.h"
#include "hctarget.h"
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hc_pin_descriptor.h"
#include "hchal.h"
#include "hc_route.h"
#include "hcts.h"
#include "hc_presets.h"
#include "hcfuelpump.h"
#include "hcmainrelay.h"
#include "hc_dbw.h"           /* V92 thunks */
#include "hcsched_dry.h"      /* V97 knock snapshot */
#include "hcdeadline711.h"

unsigned int far hc_hal_deadline_ports_f(unsigned char base, unsigned int mask, unsigned char physical, unsigned char on) { return hc_hal_deadline_ports(base, mask, physical, on); }

unsigned char far hc_lf_export_byte_f(unsigned int off) { return hc_lf_export_byte(off); }

unsigned char far hc_cal_u8_f(unsigned int off)            { return hc_cal_u8(off); }
unsigned int  far hc_cal_u16_f(unsigned int off)           { return hc_cal_u16(off); }
void far hc_cal_set_u8_f(unsigned int off, unsigned char v) { hc_cal_set_u8(off, v); }
void far hc_cal_set_u16_f(unsigned int off, unsigned int v) { hc_cal_set_u16(off, v); }
void          far hc_cfg_commit_f(void)                    { hc_cfg_commit(); }
unsigned int  far hc_cfg_faults_f(void)                    { return hc_cfg_faults(); }

void far hcts_target_yield_f(void)                         { hcts_target_yield(); }

unsigned char far hc_hal_capture_channel_f(unsigned char pin)
{
    return hc_hal_capture_channel(pin);
}
unsigned char far hc_hal_out_bindable_f(unsigned int field, unsigned char cav)
{
    return hc_hal_out_bindable(field, cav);    /* V95 */
}
unsigned int  far hc_hal_ain_f(unsigned char sem)          { return hc_hal_ain(sem); }
unsigned char far hc_hal_ain_ok_f(unsigned char sem)       { return hc_hal_ain_ok(sem); }
void far hc_hal_ain_bind_f(unsigned char sem, unsigned char adc_ch)
{
    hc_hal_ain_bind(sem, adc_ch);
}
unsigned char far hc_hal_ain_phys_f(unsigned char sem)     { return hc_hal_ain_phys(sem); }
unsigned char far hc_hal_ain_bound_f(unsigned char sem)    { return hc_hal_ain_bound(sem); }
unsigned char far hc_hal_dbw_sf_faulted_f(void)            { return hc_hal_dbw_sf_faulted(); }
unsigned char far hc_hal_dbw_sf_level_f(void)              { return hc_hal_dbw_sf_level(); }
/* V92 */
unsigned char far hc_dbw_state_f(void)                     { return hc_dbw_state(); }
/* hckwp_me711.c */
void          far hcts_tx_f(unsigned char c)               { hcts_tx(c); }
void          far hcts_tx_end_f(void)                      { hcts_tx_end(); }
void          far hcts_link_force_f(unsigned char bg, unsigned char locked)
{
    hcts_link_force(bg, locked);
}
void          far hcts_link_hunt_f(void)                   { hcts_link_hunt(); }
/* hcetbcal.c */
void far hc_dbw_calibration_begin_f(unsigned int now_ms) { hc_dbw_calibration_begin(now_ms); }
unsigned char far hc_dbw_bridge_on_f(void) { return hc_dbw_bridge_on(); }
unsigned int far hc_dbw_duty_x10_f(void) { return hc_dbw_duty_x10(); }
void          far hc_dbw_drive_f(unsigned char dir, unsigned int duty) { hc_dbw_drive(dir, duty); }
void          far hc_dbw_shutdown_f(unsigned int fault_bits) { hc_dbw_shutdown(fault_bits); }
void far hc_dbw_clear_faults_f(void) { hc_dbw_clear_faults(); }
unsigned char far hc_dbw_gains_f(unsigned int a_x10, unsigned int tu_ms,
                                 unsigned int *k)
{
    return hc_dbw_gains(a_x10, tu_ms, k);
}
unsigned int far hc_dbw_normalise_f(unsigned int raw, unsigned int lo,
                                    unsigned int hi, unsigned char *ok)
{
    return hc_dbw_normalise(raw, lo, hi, ok);
}
unsigned char far hc_hal_outputs_live_f(void)              { return hc_hal_outputs_live(); }
unsigned int far hc_cal_curve16_f(unsigned int ax_off, unsigned int val_off,
                                  unsigned char n, unsigned int x)
{
    return hc_cal_curve16(ax_off, val_off, n, x);
}
unsigned int far hc_dbw_pedal_x10_f(void)             { return hc_dbw_pedal_x10(); }
unsigned int far hc_dbw_faults_f(void)                { return hc_dbw_faults(); }
/* the commissioning verify (hcetbcal.c) and the DBW telemetry (hcio711.c) */
void         far hc_dbw_override_f(unsigned int t)      { hc_dbw_override(t); }
unsigned int far hc_dbw_actual_x10_f(void)              { return hc_dbw_actual_x10(); }
/* the engine-control layer (hcengctl711.c) */
unsigned int far hc_dbw_target_x10_f(void)              { return hc_dbw_target_x10(); }
unsigned char far hc_hal_din_f(unsigned char cav)       { return hc_hal_din(cav); }
unsigned char far hc_hal_din_ok_f(unsigned char cav)    { return hc_hal_din_ok(cav); }
unsigned int far hc_dbw_term_f(unsigned char i)         { return hc_dbw_term(i); }
unsigned char far hc_cal_map_f(unsigned int map_off, unsigned int rpm_ax_off,
                               unsigned int load_ax_off,
                               unsigned int rpm, unsigned int load)
{
    return hc_cal_map(map_off, rpm_ax_off, load_ax_off, rpm, load);
}


const hc_cfg_slot_t *far hc_cfg_slot_at_f(unsigned int off) { return hc_cfg_slot_at(off); }

/* hc_presets.c is FAR itself now - no thunks. */

/* the HAL, for hcfuelpump.c / hcmainrelay.c (now FAR) */
unsigned int  far cfg_u16_f(unsigned char off)            { return cfg_u16(off); }
void          far hc_hal_out_f(unsigned char sem, unsigned char on) { hc_hal_out(sem, on); }
void far hc_hal_out_duty_f(unsigned char sem, unsigned int duty)
{ hc_hal_out_duty(sem, duty); }
/* The bridge PWM frequency: hcetbcal.c sets it while evaluating candidates and
   publishes what the hardware ended up switching at. */
void far hc_hal_dbw_pwm_hz_f(unsigned int hz)
{ hc_hal_dbw_pwm_hz(hz); }
unsigned int far hc_hal_dbw_pwm_applied_hz_f(void)
{ return hc_hal_dbw_pwm_applied_hz(); }
unsigned char far hc_hal_out_class_live_f(unsigned char sem) { return hc_hal_out_class_live(sem); }
void          far hc_hal_main_relay_set_f(unsigned char on)  { hc_hal_main_relay_set(on); }
unsigned char far hc_hal_main_relay_bound_f(void)            { return hc_hal_main_relay_bound(); }
unsigned char far hc_hal_main_relay_feedback_valid_f(void)   { return hc_hal_main_relay_feedback_valid(); }
unsigned int  far hc_hal_main_relay_feedback_dv_f(void)      { return hc_hal_main_relay_feedback_dv(); }
unsigned char far hc_hal_main_relay_feedback_state_f(void)   { return hc_hal_main_relay_feedback_state(); }

/* the knock driver's tooth snapshot (hcsched_dry.c) */
void          far hc_drysched_snap_f(void)                  { hc_drysched_snap(); }

void far cfg_set_u16_f(unsigned char off, unsigned int v) { cfg_set_u16(off, v); }

unsigned int far asic_frame_word_f(unsigned char i) { return asic_frame_word(i); }

void far asic_isolate_f(void) { asic_isolate(); }

unsigned int far eng_lambda_x1000_f(void) { return eng_lambda_x1000(); }

unsigned int far hc_bf_u16_f(unsigned int off) { return hc_bf_u16(off); }

unsigned int far hc_bf_u8_f(unsigned int off) { return hc_bf_u8(off); }

unsigned int far hc_cfg_persist_class_f(void) { return hc_cfg_persist_class(); }

unsigned int far hc_dbw_app1_x10_f(void) { return hc_dbw_app1_x10(); }

unsigned int far hc_dbw_app2_x10_f(void) { return hc_dbw_app2_x10(); }

unsigned char far hc_dbw_dir_f(void) { return hc_dbw_dir(); }

int far hc_dbw_error_x10_f(void) { return hc_dbw_error_x10(); }

int far hc_dbw_integ_f(void) { return hc_dbw_integ(); }

unsigned int far hc_dbw_steps_f(void) { return hc_dbw_steps(); }

unsigned int far hc_dbw_tps1_x10_f(void) { return hc_dbw_tps1_x10(); }

unsigned int far hc_dbw_tps2_x10_f(void) { return hc_dbw_tps2_x10(); }

unsigned int far hc_hal_ain_mask_f(void) { return hc_hal_ain_mask(); }

unsigned char far hc_hal_fuelpump_driven_f(void) { return hc_hal_fuelpump_driven(); }

unsigned char far hc_hal_main_relay_driven_f(void) { return hc_hal_main_relay_driven(); }

unsigned char far hc_hal_main_relay_inhibited_f(void) { return hc_hal_main_relay_inhibited(); }

unsigned int far hc_hal_out_mask_ign_f(void) { return hc_hal_out_mask_ign(); }

unsigned int far hc_hal_out_mask_inj_f(void) { return hc_hal_out_mask_inj(); }

void far hc_hal_s5500_window_f(unsigned char base) { hc_hal_s5500_window(base); }

unsigned int far hc_nvm_attempts_f(void) { return hc_nvm_attempts(); }

unsigned int far hc_nvm_cells_total_f(void) { return hc_nvm_cells_total(); }

unsigned int far hc_nvm_commit_fail_stage_f(void) { return hc_nvm_commit_fail_stage(); }

unsigned int far hc_nvm_commit_last_stage_f(void) { return hc_nvm_commit_last_stage(); }

unsigned int far hc_nvm_commit_stage_f(void) { return hc_nvm_commit_stage(); }

unsigned int far hc_nvm_commits_f(void) { return hc_nvm_commits(); }

unsigned int far hc_nvm_erase_fails_f(void) { return hc_nvm_erase_fails(); }

unsigned int far hc_nvm_erase_ms_f(void) { return hc_nvm_erase_ms(); }

unsigned int far hc_nvm_erase_slices_f(void) { return hc_nvm_erase_slices(); }

unsigned int far hc_nvm_erase_state_f(void) { return hc_nvm_erase_state(); }

unsigned int far hc_nvm_erase_tries_f(void) { return hc_nvm_erase_tries(); }

unsigned int far hc_nvm_error_f(void) { return hc_nvm_error(); }

unsigned int far hc_nvm_fail_exp_f(void) { return hc_nvm_fail_exp(); }

unsigned int far hc_nvm_fail_got_f(void) { return hc_nvm_fail_got(); }

unsigned int far hc_nvm_fail_got2_f(void) { return hc_nvm_fail_got2(); }

unsigned int far hc_nvm_fail_word_f(void) { return hc_nvm_fail_word(); }

unsigned int far hc_nvm_free_cells_f(void) { return hc_nvm_free_cells(); }

unsigned int far hc_nvm_generation_f(void) { return hc_nvm_generation(); }

unsigned int far hc_nvm_live_admission_f(void) { return hc_nvm_live_admission(); }

unsigned int far hc_nvm_live_deadline_ms_f(void) { return hc_nvm_live_deadline_ms(); }

unsigned int far hc_nvm_live_horizon_us_f(void) { return hc_nvm_live_horizon_us(); }

unsigned int far hc_nvm_live_mask_f(void) { return hc_nvm_live_mask(); }

unsigned int far hc_nvm_live_owner_f(void) { return hc_nvm_live_owner(); }

unsigned int far hc_nvm_live_pause_reason_f(void) { return hc_nvm_live_pause_reason(); }

unsigned int far hc_nvm_live_pending_after_f(void) { return hc_nvm_live_pending_after(); }

unsigned int far hc_nvm_live_pending_before_f(void) { return hc_nvm_live_pending_before(); }

unsigned int far hc_nvm_live_predicted_ms_f(void) { return hc_nvm_live_predicted_ms(); }

unsigned int far hc_nvm_live_vector_violations_f(void) { return hc_nvm_live_vector_violations(); }

unsigned int far hc_nvm_live_windows_ok_f(void) { return hc_nvm_live_windows_ok(); }

unsigned int far hc_nvm_live_windows_rejected_f(void) { return hc_nvm_live_windows_rejected(); }

unsigned int far hc_nvm_live_writer_entries_f(void) { return hc_nvm_live_writer_entries(); }

unsigned int far hc_nvm_live_writer_failures_f(void) { return hc_nvm_live_writer_failures(); }

unsigned int far hc_nvm_live_writer_success_f(void) { return hc_nvm_live_writer_success(); }

unsigned int far hc_nvm_lkg_steps_f(void) { return hc_nvm_lkg_steps(); }

unsigned int far hc_nvm_phase_f(void) { return hc_nvm_phase(); }

unsigned int far hc_nvm_poll_max_f(void) { return hc_nvm_poll_max(); }

unsigned int far hc_nvm_poll_min_f(void) { return hc_nvm_poll_min(); }

unsigned int far hc_nvm_prog_flags_f(void) { return hc_nvm_prog_flags(); }

unsigned int far hc_nvm_prog_retries_f(void) { return hc_nvm_prog_retries(); }

unsigned int far hc_nvm_ram_result_f(void) { return hc_nvm_ram_result(); }

unsigned int far hc_nvm_ram_runs_f(void) { return hc_nvm_ram_runs(); }

unsigned int far hc_nvm_ram_seed_f(void) { return hc_nvm_ram_seed(); }

unsigned int far hc_nvm_ram_state_f(void) { return hc_nvm_ram_state(); }

unsigned int far hc_nvm_ramtest_f(unsigned int seed, unsigned char safe) { return hc_nvm_ramtest(seed, safe); }

unsigned int far hc_nvm_reclaims_f(void) { return hc_nvm_reclaims(); }

unsigned int far hc_nvm_slot_f(void) { return hc_nvm_slot(); }

unsigned int far hc_nvm_source_f(void) { return hc_nvm_source(); }

unsigned int far hc_nvm_state_f(void) { return hc_nvm_state(); }
void far hc_nvm_mark_dirty_f(void) { hc_nvm_mark_dirty(); }

unsigned int far hc_nvm_words_completed_f(void) { return hc_nvm_words_completed(); }

unsigned int far hc_nvm_words_remaining_f(void) { return hc_nvm_words_remaining(); }

unsigned int far hc_nvm_words_total_f(void) { return hc_nvm_words_total(); }

unsigned char far hc_power_hold_state_f(void) { return hc_power_hold_state(); }

unsigned char far hc_power_nl_predict_f(unsigned char nlen_fr, unsigned char nlen_as) { return hc_power_nl_predict(nlen_fr, nlen_as); }

unsigned int far hc_rst_get_f(unsigned int off) { return hc_rst_get(off); }

unsigned int far hc_s5500_raw_f(unsigned char i) { return hc_s5500_raw(i); }

unsigned int far hc_ssc_pec_rx_left_f(void) { return hc_ssc_pec_rx_left(); }

unsigned int far hc_ssc_pec_tx_left_f(void) { return hc_ssc_pec_tx_left(); }

unsigned int far hc_ssc_sscon_f(void) { return hc_ssc_sscon(); }

unsigned char far hcts_link_evid_f(void) { return hcts_link_evid(); }

unsigned int far hcts_link_state_f(void) { return hcts_link_state(); }

void far hcts_poll_f(void) { hcts_poll(); }
void far hcts_service_f(void) { hcts_service(); }

void far hcts_rx_pump_f(void) { hcts_rx_pump(); }

unsigned char far hc_tlog_byte_f(unsigned int i) { return hc_tlog_byte(i); }
