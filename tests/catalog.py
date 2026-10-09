#!/usr/bin/env python3
r"""
catalog.py - every gate in tests/, what kind it is, what it is about, and when
to run it. ONE place, read by tests/run_gates.py.

    py tests\catalog.py            print the catalog
    py tests\catalog.py --check    exit 1 if an override names a gate that does not exist

THE GATE LIST IS THE DIRECTORY TREE. A script in tests/<kind>/... is a gate;
nobody has to remember to register it. (The old hand-kept registry had
drifted: 85 proof/test scripts, including half of Tier 1, were never run by
the full suite.) The tables below only ADD facts the location cannot carry:
which gates are fast, which form Tier 1, extra subsystem tags, time budgets and
the level conditions under which a gate's question no longer applies.

KINDS (= the directory under tests/):
  host         SFR-free firmware cores compiled and run on a host C compiler
  unit         tool-level tests and pytest suites (no firmware image needed)
  simulator    tests of the C167 simulator itself (c167sim)
  tunerstudio  the generated .ini against the firmware and TunerStudio's rules
  firmware     the LINKED IMAGE: executed in c167sim, or its map/bytes read
               (subdirectory = subsystem tag: build, asic, comms, config,
               persistence, trigger, engine, dbw, outputs)
  history      proofs about one FROZEN release (they skip on a newer image)
  physical     hardware-in-the-loop qualification - NEVER run by a tier;
               each script refuses to touch hardware without its own flag
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
KINDS = ("host", "unit", "simulator", "tunerstudio", "firmware", "history", "physical")


@dataclass(frozen=True)
class Gate:
    name: str
    path: Path
    kind: str
    tags: tuple = ()
    fast: bool = False
    tier1: bool = False
    timeout: int = 1800
    skip_if: str = ""
    pytest: bool = False

    @property
    def rel(self) -> str:
        return self.path.relative_to(ROOT).as_posix()


# ---------------------------------------------------------------- overrides
# FAST: a few seconds to about a minute each, so `run_gates.py fast` finishes
# in minutes. Every host, unit and simulator test is fast by kind; these are
# the firmware / tunerstudio gates that also qualify (measured 2026-10-06).
FAST = {
    "me711_dbw_warm_binding_proof", "me711_serial_crc_proof",
    "me711_far_boundary_proof", "near_ram_hazard_proof", "me711_keil_shift_scan",
    # Resource and realtime budgets that fail before qualification.
    "me711_resource_budget_proof", "me711_stack_budget_proof", "me711_burn_interrupt_guard",
    "me711_executor_slice_proof",
    "me711_clock_proof", "me711_irq_priority_proof", "me711_generated_sources_current_proof",
    "me711_target_isolation_test", "me711_runtime_handshake_proof", "me711_calib_grab_proof",
    "me711_dbw_control_proof", "me711_dbw_audit_proof", "me711_dbw_target_step_proof",
    "me711_etb_bias_transaction_proof", "me711_deadline_proof", "me711_ambient_pressure",
    "me711_config_state_test", "me711_page_reader_audit", "me711_preset_apply_proof",
    "me711_preset_validates_proof", "me711_preset_routing_proof", "me711_cavity_truth_proof",
    "me711_safety_test", "me711_output_safety_test", "me711_identity_proof",
    "check_hanicore_ts_ini_syntax", "ts_ini_grammar_proof", "ts_ini_namespace_proof",
    "ts_ini_indicator_scope_proof", "ts_ini_menu_reachability_proof", "ts_ini_ui_contract",
    "ts_ini_och_scale_proof", "ts_ini_terminology_proof", "ts_ini_ux_contract_proof",
    "ts_ini_command_shape_proof", "ts_ini_dead_knob_proof", "ts_ini_scaling_proof",
    "ts_dash_proof", "ts_signature_layout_proof", "ts_pin_dropdown_agreement_proof",
}

# TIER 1: the milestone check of the TunerStudio interface against the image
# (run before a bench flash and before a checkpoint commit). run_gates.py
# regenerates the .ini and the dashboard first, as the old Tier 1 did.
TIER1 = [
    "ts_semantics_me711",               # (generator module self-check, see run_gates)
    "me711_ambient_pressure", "check_hanicore_ts_ini_syntax", "ts_ini_grammar_proof",
    "ts_ini_namespace_proof", "ts_ini_indicator_scope_proof", "ts_ini_menu_reachability_proof",
    "ts_ini_ui_contract", "me711_page_reader_audit", "ts_ini_och_scale_proof",
    "ts_ini_terminology_proof", "ts_ini_ux_contract_proof", "ts_ini_command_shape_proof",
    "ts_dash_proof", "me711_och_contract_proof",
]

# Extra subsystem tags. Every firmware gate is already tagged with its
# directory; these add the gates that matter to a subsystem from elsewhere.
EXTRA_TAGS = {
    "dbw": {"me711_tps_diagnostic_proof", "me711_tps_lifecycle_proof", "me711_etb_bias_host_test",
            "me711_etb_characterization_analyze_test", "me711_idle_proof", "me711_bench_output_proof",
            "me711_sensor_plausibility_proof"},
    "config": {"me711_generated_sources_current_proof", "me711_build_integrity_proof",
               "me711_identity_proof", "ts_signature_layout_proof", "ts_pin_dropdown_agreement_proof",
               "me711_och_contract_proof", "test_config_access_types", "test_config_source_of_truth",
               "test_hw_descriptor_evidence", "test_och_contract", "me711_page_reader_audit",
               "ts_ini_dead_knob_proof", "me711_nvm_proof", "me711_lkg_walkback_proof"},
    "wideband": {"test_hcwb_host", "me711_lambda_activity_proof", "me711_heater_path_proof",
                 "me711_wideband_ssc_bound_proof", "me711_native_io_proof", "me711_acquisition_proof"},
    "trigger": {"test_hccam_host", "me711_cam_fault_proof", "me711_cam_pattern_proof"},
    "engine": {"test_hctrans_host", "test_hcidle_host", "test_hcldr_host", "test_hcvvt_host",
               "test_hcknock_host", "test_hclimp_host", "test_hcdtc_host", "test_hccel_host"},
    "comms": {"test_hckline_host", "test_hcpecrx_host", "me711_kwp_connect_test", "ts_kline_bridge_test",
              "test_plugin_auto", "me711_ts_query_collision_proof", "test_ts_commands"},
    "runtime": {"me711_runtime_stress_proof", "me711_runtime_fault_proof",
                "me711_kline_mixed_proof", "me711_dbw_readiness_proof",
                "me711_deadline_proof", "me711_cc25_stack_proof",
                "me711_executor_slice_proof", "me711_dbw_warm_binding_proof",
                "me711_serial_crc_proof", "me711_plan_cost_proof",
                "me711_stack_budget_proof", "me711_resource_budget_proof",
                "near_ram_hazard_proof", "me711_far_boundary_proof",
                "me711_irq_priority_proof", "me711_burn_interrupt_guard",
                "me711_crank_period_atomic_proof", "test_c167sim_irq_nesting",
                "test_c167sim_bfld"},
    "vehicle-tools": {"me711_vehicle_test_test", "me711_log_analyze_test", "me711_vehicle_capture_test",
                      "me711_commission_tools_test", "me711_kwp_connect_test"},
}

# Gates that legitimately need more than the default 1800 s (measured).
TIMEOUTS = {
    "me711_ts_gap_proof": 9000,
    "me711_flash_bus_proof": 7200,
    "me711_nvm_rotation_proof": 3600,
    # These execute full main-loop workloads, including a fresh simulated boot.
    "me711_runtime_stress_proof": 14400, # three complete transport matrices
    "me711_runtime_fault_proof": 7200,
    "me711_kline_mixed_proof": 5400,
    "me711_dbw_readiness_proof": 7200,
}

# A gate whose question no longer applies SKIPS - on a LEVEL read from the
# tree at run time (tests/run_gates.py CONDITIONS), never a remembered list.
SKIP_IF = {
    "me711_sched_epoch_proof": "planner_absent",
    "me711_trigger_test": "planner_absent",
    "me711_trigger_adversarial_test": "planner_absent",
    "me711_plan_cost_proof": "planner_on_own_level",
    "test_plan_cost_gate": "planner_on_own_level",
    "me711_bootsum_coverage_proof": "owned_boot",
    "me711_dbw_control_proof": "dbw_absent",
    "me711_burn_forensics_proof": "diag_absent",
    "me711_forensics_retention_proof": "diag_absent",
    "me711_asicdump_coherence": "diag_absent",
    "me711_build_integrity_proof": "image_frozen",
    "me711_heartbeat_gap_proof": "heartbeat_retired",
    "me711_rx_drain_rearm_proof": "rx_pec",
    # They read the OEM binaries, the A2L, the rusEFI .ini corpus or the
    # frozen release .ini files themselves.
    "me711_runtime_handshake_proof": "local_corpus_absent",
    "me711_ambient_pressure": "local_corpus_absent",
    "ts_ini_grammar_proof": "local_corpus_absent",
    "ts_dash_proof": "local_corpus_absent",
    "ts_signature_layout_proof": "local_corpus_absent",
    # their subject is a frozen release binary (the image that failed)
    "me711_flash_bus_proof": "local_corpus_absent",
    "me711_live_burn_proof": "local_corpus_absent",
}

# Renamed in the 2026-10 restructure (old name -> new name). Evidence and
# frozen release notes use the old names.
FORMERLY = {
    "me711_dbw_v97_proof": "me711_dbw_audit_proof",
    "me711_v12_salvage_proof": "me711_asicdump_salvage_proof",
    "me711_v27_adversarial_test": "me711_trigger_adversarial_test",
    "me711_v40_resetless_proof": "me711_burn_resetless_proof",
    "me711_v40_session_proof": "me711_burn_two_in_session_proof",
    "me711_v48_live_burn_proof": "me711_live_burn_proof",
    "me711_v49_forensics_proof": "me711_burn_forensics_proof",
    "me711_v49_nmi_execution_proof": "me711_nmi_handler_proof",
    "me711_v49_retention_proof": "me711_forensics_retention_proof",
    "me711_v50_ir_preserve_proof": "me711_burn_ir_preserve_proof",
    "me711_v50_request_preservation_proof": "me711_burn_request_preservation_proof",
    "me711_v51_admission_proof": "me711_flash_admission_proof",
    "me711_v75_relay_pump_proof": "me711_relay_pump_port_proof",
    "me711_v79_io_proof": "me711_native_io_proof",
    "me711_v92_trigger_proof": "me711_trigger_scheduler_proof",
    "me711_v98_engine_proof": "me711_engine_control_proof",
    "me711_v102_edge_contract_proof": "me711_edge_contract_proof",
    "me711_v102_legacy_proof": "me711_engine_service_equivalence_proof",
    "me711_v102_load_proof": "me711_load_contract_proof",
    "me711_v102_migration_proof": "me711_page_migration_proof",
    "me711_v102_planning_proof": "me711_planner_geometry_proof",
    "me711_v102_stack_proof": "me711_cc25_stack_proof",
    "me711_v75_relay_pump_bench": "me711_bench_session",
    "me711_v49_forensic_capture": "me711_burn_forensics_capture",
}


def _is_pytest(p: Path) -> bool:
    t = p.read_text(encoding="utf-8", errors="replace")
    return "__main__" not in t and "def test_" in t


def gates() -> list[Gate]:
    out = []
    for kind in KINDS:
        for p in sorted((TESTS / kind).rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            name = p.stem
            sub = p.parent.relative_to(TESTS / kind).parts
            tags = {kind} | set(sub)
            tags |= {t for t, names in EXTRA_TAGS.items() if name in names}
            fast = kind in ("host", "unit", "simulator") or name in FAST
            out.append(Gate(name, p, kind, tuple(sorted(tags)), fast,
                            name in TIER1, TIMEOUTS.get(name, 1800),
                            SKIP_IF.get(name, ""), _is_pytest(p)))
    return out


def check() -> int:
    names = {g.name for g in gates()}
    names.add("ts_semantics_me711")
    bad = 0
    for table, label in ((FAST, "FAST"), (set(TIER1), "TIER1"), (set(TIMEOUTS), "TIMEOUTS"),
                         (set(SKIP_IF), "SKIP_IF"),
                         (set().union(*EXTRA_TAGS.values()), "EXTRA_TAGS")):
        for n in sorted(table - names):
            print("[FAIL] %s names %s, which is not a gate under tests/" % (label, n))
            bad += 1
    for n in sorted(set(FORMERLY.values()) - names - {"me711_bench_session", "me711_burn_forensics_capture"}):
        print("[FAIL] FORMERLY maps to %s, which is not a gate under tests/" % n)
        bad += 1
    if not bad:
        print("[PASS] every override names a real gate (%d gates)" % len(names))
    return bad


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(1 if check() else 0)
    for g in gates():
        print("%-12s %-46s %-5s %s" % (g.kind, g.name, "fast" if g.fast else "", ",".join(g.tags)))
