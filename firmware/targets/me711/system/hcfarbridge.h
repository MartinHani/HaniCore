/*
 * hcfarbridge.h - how a FAR (FCODE) module reaches the NEAR (NCODE) world.
 *
 * WHY. NCODE is one 64 KiB CGROUP and V80 left it 2 bytes free
 * (docs/ARCHITECTURE.md). The cold setup modules - validation, the
 * config manager, the bench qualifier, analog routing - are compiled
 * MOD167 MEDIUM with DEFINE(HC_FAR_BRIDGE), so they link into FCODE
 * (segment 0x85) instead.
 *
 * THE CONSTRAINT. A near call (CALLA/CALLR) stays inside the CURRENT code
 * segment, so FCODE code cannot near-call anything in segment 0x84, and a
 * near function returns with RET, so it cannot be far-called either. Every
 * NCODE function a FAR module calls therefore goes through a one-line far
 * THUNK in hcfar_me711.c (SMALL, NCODE): CALLS in, CALLA to the real
 * function, RETS out. The hot callers - the trigger, the scheduler, the HAL,
 * the main loop - keep their near calls and pay nothing.
 *
 * THE MECHANISM. This header is included FIRST by those modules, so the
 * ordinary prototypes in hcconfig.h, hchal.h, ... that follow it declare the
 * _f names - and in the MEDIUM model an unqualified function is far, which
 * is exactly what the thunks are. L166 checks every reference against the
 * definition: a callee missing from this list is an L20 DATA TYPES DIFFERENT
 * (near vs far) at link, which build_hanicore_me711.py treats as fatal, and
 * tools/me711_far_boundary_proof.py checks the linked image besides.
 *
 * ADDING A CALL from a far module to a new NCODE function: add the rename
 * here and the thunk in hcfar_me711.c. Nothing else.
 */
#ifndef HCFARBRIDGE_H
#define HCFARBRIDGE_H

/* hcconfig.c */
#define hc_cal_u8                     hc_cal_u8_f
#define hc_cal_u16                    hc_cal_u16_f
#define hc_cal_set_u8                 hc_cal_set_u8_f
#define hc_cal_set_u16                hc_cal_set_u16_f
#define hc_cfg_commit                 hc_cfg_commit_f
#define hc_cfg_faults                 hc_cfg_faults_f
/* hcmain_me711.c */
#define hcts_target_yield             hcts_target_yield_f
/* hchal_me711.c */
#define hc_hal_capture_channel        hc_hal_capture_channel_f
#define hc_hal_out_bindable           hc_hal_out_bindable_f
#define hc_hal_ain                    hc_hal_ain_f
#define hc_hal_ain_ok                 hc_hal_ain_ok_f
#define hc_hal_ain_bind               hc_hal_ain_bind_f
#define hc_hal_ain_phys               hc_hal_ain_phys_f
#define hc_hal_ain_bound              hc_hal_ain_bound_f
#define hc_hal_dbw_sf_faulted         hc_hal_dbw_sf_faulted_f
#define hc_hal_dbw_sf_level           hc_hal_dbw_sf_level_f
/* hc_pin_descriptor.c: FAR itself since V98r2 - called directly, no thunk */
/* hc_config_generated.c */
#define hc_cfg_slot_at                hc_cfg_slot_at_f
/* hc_presets.c (generated, so it stays SMALL) */
/* hc_dbw.c (V92: the bench refuses while the ETB owns the bridge) */
#define hc_dbw_state                  hc_dbw_state_f
/* hc_dbw.c (V93: hcetbcal.c borrows the bridge) */
#define hc_dbw_calibration_begin       hc_dbw_calibration_begin_f
#define hc_dbw_bridge_on              hc_dbw_bridge_on_f
#define hc_dbw_duty_x10               hc_dbw_duty_x10_f
#define hc_dbw_drive                  hc_dbw_drive_f
#define hc_dbw_shutdown               hc_dbw_shutdown_f
#define hc_dbw_clear_faults           hc_dbw_clear_faults_f
#define hc_dbw_gains                  hc_dbw_gains_f
#define hc_dbw_normalise              hc_dbw_normalise_f
/* hc_dbw.c (V97: the commissioning verify, the DBW telemetry) */
#define hc_dbw_override               hc_dbw_override_f
#define hc_dbw_actual_x10             hc_dbw_actual_x10_f
#define hc_dbw_target_x10             hc_dbw_target_x10_f
#define hc_hal_din                    hc_hal_din_f
#define hc_hal_din_ok                 hc_hal_din_ok_f
#define hc_dbw_term                   hc_dbw_term_f
#define hc_hal_outputs_live           hc_hal_outputs_live_f
#define hc_cal_curve16                hc_cal_curve16_f
/* hcconfig.c (V97: hcboost711.c reads the boost maps) */
#define hc_cal_map                    hc_cal_map_f
/* hc_dbw.c (V97: hcidle711.c reads the pedal) */
#define hc_dbw_pedal_x10              hc_dbw_pedal_x10_f
/* hc_dbw.c (V97: hcdtc711.c reads the latched throttle faults) */
#define hc_dbw_faults                 hc_dbw_faults_f
/* hcsched_dry.c (V97: hcknock711.c arms its window from the last tooth) */
#define hc_drysched_snap              hc_drysched_snap_f
#define hc_lf_export_byte             hc_lf_export_byte_f
/* hcts.c (V94: hckwp_me711.c transmits and sets the rate) */
#define hcts_tx                       hcts_tx_f
#define hcts_tx_end                   hcts_tx_end_f
#define hcts_link_force               hcts_link_force_f
#define hcts_link_hunt                hcts_link_hunt_f
/* hcfuelpump.c and hcmainrelay.c are FAR themselves now (HC_COLD in
   their headers), so far callers reach them directly; they in turn reach
   the HAL through these. */
#define cfg_set_u16                   cfg_set_u16_f
#define cfg_u16                       cfg_u16_f
#define hc_hal_out                    hc_hal_out_f
#define hc_hal_out_duty               hc_hal_out_duty_f
#define hc_hal_dbw_pwm_hz             hc_hal_dbw_pwm_hz_f
#define hc_hal_dbw_pwm_applied_hz     hc_hal_dbw_pwm_applied_hz_f
#define hc_hal_out_class_live         hc_hal_out_class_live_f
#define hc_hal_main_relay_set         hc_hal_main_relay_set_f
#define hc_hal_main_relay_bound       hc_hal_main_relay_bound_f
#define hc_hal_main_relay_feedback_valid hc_hal_main_relay_feedback_valid_f
#define hc_hal_main_relay_feedback_dv hc_hal_main_relay_feedback_dv_f
#define hc_hal_main_relay_feedback_state hc_hal_main_relay_feedback_state_f

#define asic_frame_word asic_frame_word_f
#define asic_isolate asic_isolate_f
#define eng_lambda_x1000 eng_lambda_x1000_f
#define hc_bf_u16 hc_bf_u16_f
#define hc_bf_u8 hc_bf_u8_f
#define hc_cfg_persist_class hc_cfg_persist_class_f
#define hc_dbw_app1_x10 hc_dbw_app1_x10_f
#define hc_dbw_app2_x10 hc_dbw_app2_x10_f
#define hc_dbw_dir hc_dbw_dir_f
#define hc_dbw_error_x10 hc_dbw_error_x10_f
#define hc_dbw_integ hc_dbw_integ_f
#define hc_dbw_steps hc_dbw_steps_f
#define hc_dbw_tps1_x10 hc_dbw_tps1_x10_f
#define hc_dbw_tps2_x10 hc_dbw_tps2_x10_f
#define hc_hal_ain_mask hc_hal_ain_mask_f
#define hc_hal_fuelpump_driven hc_hal_fuelpump_driven_f
#define hc_hal_main_relay_driven hc_hal_main_relay_driven_f
#define hc_hal_main_relay_inhibited hc_hal_main_relay_inhibited_f
#define hc_hal_out_mask_ign hc_hal_out_mask_ign_f
#define hc_hal_out_mask_inj hc_hal_out_mask_inj_f
#define hc_hal_s5500_window hc_hal_s5500_window_f
#define hc_nvm_attempts hc_nvm_attempts_f
#define hc_nvm_cells_total hc_nvm_cells_total_f
#define hc_nvm_commit_fail_stage hc_nvm_commit_fail_stage_f
#define hc_nvm_commit_last_stage hc_nvm_commit_last_stage_f
#define hc_nvm_commit_stage hc_nvm_commit_stage_f
#define hc_nvm_commits hc_nvm_commits_f
#define hc_nvm_erase_fails hc_nvm_erase_fails_f
#define hc_nvm_erase_ms hc_nvm_erase_ms_f
#define hc_nvm_erase_slices hc_nvm_erase_slices_f
#define hc_nvm_erase_state hc_nvm_erase_state_f
#define hc_nvm_erase_tries hc_nvm_erase_tries_f
#define hc_nvm_error hc_nvm_error_f
#define hc_nvm_fail_exp hc_nvm_fail_exp_f
#define hc_nvm_fail_got hc_nvm_fail_got_f
#define hc_nvm_fail_got2 hc_nvm_fail_got2_f
#define hc_nvm_fail_word hc_nvm_fail_word_f
#define hc_nvm_free_cells hc_nvm_free_cells_f
#define hc_nvm_generation hc_nvm_generation_f
#define hc_nvm_live_admission hc_nvm_live_admission_f
#define hc_nvm_live_deadline_ms hc_nvm_live_deadline_ms_f
#define hc_nvm_live_horizon_us hc_nvm_live_horizon_us_f
#define hc_nvm_live_mask hc_nvm_live_mask_f
#define hc_nvm_live_owner hc_nvm_live_owner_f
#define hc_nvm_live_pause_reason hc_nvm_live_pause_reason_f
#define hc_nvm_live_pending_after hc_nvm_live_pending_after_f
#define hc_nvm_live_pending_before hc_nvm_live_pending_before_f
#define hc_nvm_live_predicted_ms hc_nvm_live_predicted_ms_f
#define hc_nvm_live_vector_violations hc_nvm_live_vector_violations_f
#define hc_nvm_live_windows_ok hc_nvm_live_windows_ok_f
#define hc_nvm_live_windows_rejected hc_nvm_live_windows_rejected_f
#define hc_nvm_live_writer_entries hc_nvm_live_writer_entries_f
#define hc_nvm_live_writer_failures hc_nvm_live_writer_failures_f
#define hc_nvm_live_writer_success hc_nvm_live_writer_success_f
#define hc_nvm_lkg_steps hc_nvm_lkg_steps_f
#define hc_nvm_phase hc_nvm_phase_f
#define hc_nvm_poll_max hc_nvm_poll_max_f
#define hc_nvm_poll_min hc_nvm_poll_min_f
#define hc_nvm_prog_flags hc_nvm_prog_flags_f
#define hc_nvm_prog_retries hc_nvm_prog_retries_f
#define hc_nvm_ram_result hc_nvm_ram_result_f
#define hc_nvm_ram_runs hc_nvm_ram_runs_f
#define hc_nvm_ram_seed hc_nvm_ram_seed_f
#define hc_nvm_ram_state hc_nvm_ram_state_f
#define hc_nvm_ramtest hc_nvm_ramtest_f
#define hc_nvm_reclaims hc_nvm_reclaims_f
#define hc_nvm_slot hc_nvm_slot_f
#define hc_nvm_source hc_nvm_source_f
#define hc_nvm_state hc_nvm_state_f
#define hc_nvm_mark_dirty hc_nvm_mark_dirty_f
#define hc_nvm_words_completed hc_nvm_words_completed_f
#define hc_nvm_words_remaining hc_nvm_words_remaining_f
#define hc_nvm_words_total hc_nvm_words_total_f
#define hc_power_hold_state hc_power_hold_state_f
#define hc_power_nl_predict hc_power_nl_predict_f
#define hc_rst_get hc_rst_get_f
#define hc_s5500_raw hc_s5500_raw_f
#define hc_ssc_pec_rx_left hc_ssc_pec_rx_left_f
#define hc_ssc_pec_tx_left hc_ssc_pec_tx_left_f
#define hc_ssc_sscon hc_ssc_sscon_f
#define hcts_link_evid hcts_link_evid_f
#define hcts_link_state hcts_link_state_f
#define hcts_poll hcts_poll_f
#define hcts_service hcts_service_f
#define hcts_rx_pump hcts_rx_pump_f
#define hc_tlog_byte hc_tlog_byte_f
#endif
