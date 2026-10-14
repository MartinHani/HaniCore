#!/usr/bin/env python3
r"""me711_och_relocation_proof.py - the telemetry moved out of NCODE still
publishes exactly its variables.

    py tests\firmware\build\me711_och_relocation_proof.py            the image me711_image names
    py tests\firmware\build\me711_och_relocation_proof.py --control  V96 frozen: must FAIL

V97 (sequential-work NCODE relief) moved OCH 128..162 (engine runtime) and
222..334 (trigger + scheduler) from hcmain_me711.c update_live() (NCODE) into
hcio711.c hc_io_publish() (FCODE). On the LINKED image in c167sim this gate
writes a distinct value into every source variable, calls hc_io_publish()
once, and reads each offset back from the output-channel block: every word
must equal its variable (the composite words their formula). A moved line
with a wrong offset, a truncated type or a missed variable fails here.

--control runs the frozen V96 image, whose hc_io_publish() does not write
these offsets: it must fail (proves the gate reads what the call wrote).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

CONTROL_STEM = "HaniCore_ME711_v96_wideband"
if "--control" in sys.argv:
    env = dict(os.environ, HANICORE_ME711_STEM=CONTROL_STEM)
    r = subprocess.run([sys.executable, __file__], env=env)
    ok = r.returncode != 0
    print("\nCONTROL (%s): %s" % (CONTROL_STEM,
          "FAILS as it must" if ok else "PASSED - the gate cannot tell"))
    raise SystemExit(0 if ok else 1)

import me711_config_state_test as T      # noqa: E402
import me711_preset_apply_proof as AP    # noqa: E402

# (offset, variable, width in bytes)
PLAIN = [
    (128, "eng_batt_dv", 2), (130, "eng_clt_meas_dc", 2), (132, "eng_iat_dc", 2),
    (134, "eng_map_kpa_x10", 2), (136, "eng_tps_x10", 2), (138, "eng_tps2_x10", 2),
    (140, "eng_pedal_x10", 2), (142, "eng_pedal2_x10", 2), (144, "eng_load", 2),
    (146, "eng_ti_us", 2), (148, "eng_adv_x10", 2), (150, "eng_dwell_x100", 2),
    (152, "eng_sensor_err", 2), (154, "eng_afr_x10", 2), (156, "eng_warmup_pct", 1),
    (158, "eng_fuelcut", 2), (160, "trg_rpm", 2), (162, "trg_state", 1),
    (226, "trg_last_dt", 2), (228, "trg_tooth", 2), (230, "trg_gap_metric_x10", 2),
    (232, "trg_gap_detected", 2), (238, "trg_teeth_seen", 2), (240, "trg_gaps", 2),
    (242, "trg_synclost", 2), (244, "trg_loss_reason", 2),
    (246, "trg_engine_deg_x10", 2), (248, "trg_stall_state", 2),
    (250, "trg_noise_edges", 2), (252, "trg_isr_ticks", 2), (254, "trg_isr_max", 2),
    (256, "trg_isr_headroom", 2), (258, "trg_phase", 1), (260, "trg_rev", 2),
    (262, "trg_cam1_raw", 2), (264, "trg_cam2_raw", 2), (266, "trg_cam1_edges", 2),
    (268, "trg_cam2_edges", 2), (270, "trg_cam1_tooth", 2), (272, "trg_cam2_tooth", 2),
    (274, "trg_cam1_window", 2), (276, "trg_cam2_window", 2),
    (278, "trg_cam_error", 2), (280, "trg_cam_loss_reason", 2),
    (282, "trg_phsok_c", 2), (284, "dry_sched_queued", 2),
    (286, "dry_sched_executed", 2), (288, "dry_sched_cancelled", 2),
    (290, "dry_sched_late", 2), (292, "dry_sched_missed", 2),
    (294, "dry_sched_max_latency", 2), (296, "dry_sched_next_angle", 2),
    (298, "dry_sched_last_angle", 2), (300, "dry_sched_capture_overflow", 2),
    (302, "dry_next_ign_slot", 2), (304, "dry_next_inj_slot", 2),
    (306, "dry_spark_advance_x10", 2), (308, "dry_dwell_x100", 2),
    (310, "dry_inj_pulse_us", 2), (312, "dry_dwell_start_angle", 2),
    (314, "dry_spark_angle", 2), (316, "dry_inj_start_angle", 2),
    (318, "dry_inj_end_angle", 2), (322, "hc_safety_inhibits", 2),
    (324, "trg_gap_pending", 2), (326, "trg_cam1_angle", 2),
    (328, "trg_cam2_angle", 2), (330, "dry_sched_pending", 2),
    (332, "dry_sched_status", 2), (334, "hc_hal_trig_armed", 1),
]


def main() -> int:
    import me711_image as PI
    print("=== OCH relocation (update_live -> hc_io_publish) - %s ===" % PI.STEM)
    r = T.boot()
    fails = 0
    want = {}
    for i, (off, name, w) in enumerate(PLAIN):
        a = T.sym(name) & 0xFFFF
        v = (0x1357 + 0x0101 * i) & (0xFF if w == 1 else 0xFFFF)
        if w == 1:
            r.m.w8(a, v)
        else:
            r.m.w16(a, v)
        want[off] = v
    # trg_state drives two composite words; trg_crank_period is 32 bit
    st = 3
    r.m.w8(T.sym("trg_state") & 0xFFFF, st)
    want[162] = st
    per = 0x0012ABCD
    pa = T.sym("trg_crank_period") & 0xFFFF
    r.m.w16(pa, per & 0xFFFF)
    r.m.w16(pa + 2, per >> 16)
    want[222], want[224] = per >> 16, per & 0xFFFF
    want[234], want[236] = int(st >= 3), int(st >= 4)
    for n, bit in (("hc_outputs_allowed", 1), ("hc_dbw_allowed", 0),
                   ("hc_ignition_allowed", 1), ("hc_injection_allowed", 0)):
        r.m.w16(T.sym(n) & 0xFFFF, bit)
    want[320] = 1 | 4
    for off in want:                       # poison the block
        a = 0x380000 + 0x2000 + off
        r.m.w8(a, 0xEE)
        r.m.w8(a + 1, 0xEE)
    # 2026-10-07: the publication is three bounded slices (part 0..2,
    # hcdiag711.c hc_diag_publish_step); an image without the argument
    # ignores it and publishes everything three times.
    # 2026-10-12: seven slices (parts 2..6 = the old part 2, split).
    for part in (0, 1, 2, 3, 4, 5, 6):
        r("hc_io_publish", 0, part, steps=2_000_000)
    bad = []
    for off in sorted(want):
        got = AP.och(r, off)
        if got != want[off]:
            bad.append("%d: got 0x%04X want 0x%04X" % (off, got, want[off]))
    fails += bool(bad)
    print("  [%s] %d moved words equal their variables after one "
          "publication cycle%s" % ("FAIL" if bad else "PASS", len(want),
                                 "" if not bad else ": " + "; ".join(bad[:6])))
    print("RESULT: %s" % ("PASS" if not fails else "FAIL"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
