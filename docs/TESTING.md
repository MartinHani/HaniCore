# Testing

About 200 offline gates check the firmware. Most run the **linked image** in
an instruction-level C167 simulator (`tools/lib/c167sim.py`); others compile
the portable C cores on a PC, check the generated TunerStudio file against
the firmware, or test the tools. Simulator results are not hardware
measurements. What has been measured on hardware is listed in
[STATUS.md](STATUS.md).

## Running the gates

```powershell
py tests\run_gates.py fast             # a few minutes
py tests\run_gates.py --tag dbw        # one subsystem: dbw config trigger engine wideband comms outputs runtime
py tests\run_gates.py tier1            # TunerStudio file vs image, about 10 minutes
py tests\run_gates.py full             # every offline gate, about 4 hours
py tests\run_gates.py --list -k <text> # find a gate without running it
```

Build first if the firmware changed; the runner does not build. A missing
optional tool (host C compiler, Keil) makes the affected gates skip with the
reason, never pass silently.

| directory | what it checks |
|---|---|
| `tests/host/` | portable C cores compiled with `-std=c89 -Wall -Wextra -Werror` and run on a PC, each with negative controls; most also compile the core with Keil to prove it calls no runtime helper |
| `tests/firmware/<subsystem>/` | the linked image, executed from reset in the simulator, or its map and bytes |
| `tests/tunerstudio/` | the generated `.ini` against TunerStudio's grammar and the firmware: offsets, scales, output block, commands, menus, wording |
| `tests/unit/` | the Python tools and the simulator itself |
| `tests/simulator/` | simulator instruction and peripheral models |
| `tests/physical/` | hardware-in-the-loop checks on a real ECU; never run by a tier, each needs an explicit flag |

`tests/catalog.py` adds the fast and Tier 1 sets, tags, time budgets and
level-condition skips to what the directory tree already defines.

## Rules for gates

* A gate states which broken implementation it catches and carries a
  **negative control** — a mutation or an older image that must fail.
* Gates that reason about code read the linked image or the map, not the
  source text.
* A gate whose question no longer applies skips on a condition read from the
  tree; it does not go red and is not deleted.
* A simulated timing margin is not a margin: gate on a fraction of the real
  deadline.
* When a gate and the firmware disagree, check the instrument first —
  simulator, fixture and compiler defects have all looked like firmware bugs.

## Current results

Current image `26DFF618…` (2026-10-10; layout `5AB824FA`). It differs from
`484F9753…` by two changes only - the onboard barometric sensor as an ambient
source, and the DFCO pressure limit applying only to a manifold sensor;
reverting them rebuilds `484F9753…` bit for bit. Run on `26DFF618…`:
`run_gates.py tier1` 14/14, the TunerStudio gates 18/18, `run_gates.py fast`
84/84 (one skip by design), the load-contract, engine-control,
ambient-pressure and baro-honesty gates with their negative controls (the new
checks fail on `484F9753…`), and the sensor-fallback, alpha-N start, boost,
preset-apply, first-start-page and page-migration proofs. Not yet run on it:
`full`, runtime qualification, bench.

The table below was measured on `484F9753…`.

| check | result |
|---|---|
| build from a fresh clone | pass, byte-identical image |
| generators, repository paths, documentation links | pass |
| `run_gates.py fast` | pass; six gates skip in a public clone (below) |
| `run_gates.py tier1` | **14/14** |
| runtime qualification (stress 1000–9600 rpm, fault injection + control, deadline executor + control, DBW readiness + control, stack and resource budgets + controls, owned boot region) | pass; one transient case at 9600 rpm, see [STATUS.md](STATUS.md#runtime-timing) |
| K-line under engine load, 115200 baud | 9600 rpm steady 6/6; transients to 7000 and 8500 rpm 6/6; transient to 9600 rpm 4/6 (one capture overflow) |
| `run_gates.py full` (214 gates) | run gate by gate; the reds that remain are listed below |
| bench, real ECU | flashed and read back, cold boots, Burn, restore from flash |

### Red gates in the full set

None is silenced. Each is in one of these classes:

| gate | why it is red | class |
|---|---|---|
| `me711_kline_mixed_proof` | transient to 9600 rpm with TunerStudio traffic: one capture-ring overflow, the executor quiesces, 3 of 1049 injector openings are not executed, no edge late | known limitation above the AWT's ~6800 rpm |
| `me711_pinwrite_gap_proof`, `me711_preset_gap_proof`, `me711_ts_gap_proof`, `me711_wideband_ssc_bound_proof` | the longest main-loop pass is 9–10.6 ms against a gate limit of 6.5 ms (a fraction of the S5500's 10 ms raster); no supervision reset seen on the bench | known limitation |
| `me711_link_rate_proof` | the host-baud-rate hunt laps the receive ring in 4 of its rate-change cases | known limitation (rate changes only) |
| `me711_burn_session_proof` | a request sent *during* a Burn is dropped (no reply) instead of being answered after it; the session-fatal `0x83` frame does not occur | known limitation, needs a real-TunerStudio check |
| `me711_boot_cost_proof`, `near_ram_hazard_proof` | deliberate tripwires at their limit | tripwire |
| `me711_burn_two_in_session_proof` | the simulator rig stops delivering received bytes after the Burn's flash window; a direct reproduction with the same rig and the real ECU both answer after a Burn | rig defect |
| `me711_knock_proof` | its rig opens no knock window since the planner moved to its own interrupt level | stale fixture (knock is MONITOR-only in every preset) |
| `me711_trigger_test`, `me711_trigger_adversarial_test`, `me711_tooth_deadline_proof`, `me711_overdwell_proof`, `me711_output_arming_proof`, `me711_output_backend_proof` (hot-path checks), `me711_bench_output_proof`, `me711_dbw_bench_proof` | written for the polled executor: they expect engine outputs to switch from task-level calls or from `trg_service()`. Coils and injectors now switch only from the compare interrupt; the same properties are covered by `me711_deadline_proof`, `me711_planner_geometry_proof`, `me711_gap_scheduler_proof`, `me711_sequential_proof`, `me711_trigger_scheduler_proof`, `me711_group_off_release_proof`, `me711_port_mask_proof` and `me711_runtime_fault_proof` | stale fixture |
| `me711_v89_ui_ini_pair_proof`, `me711_v89_ui2_ini_pair_proof`, `me711_v91_ui_ini_pair_proof`, `v44_release_gate` | compare against frozen historical releases, or require a committed tree | needs the maintainer's records |

Gates that skip by design: `me711_plan_cost_proof` and `test_plan_cost_gate`
(the planner is its own interrupt level; its budget is the stress proof),
`me711_bootsum_coverage_proof` (owned boot region), `me711_rx_drain_rearm_proof`
(PEC receive), the burn-forensics gates (compiled out) and the two V37
compatibility gates.

Six gates skip in a public clone because they read material that is not in
the repository: the target's OEM flash and ASIC reads, the reference A2L, the
rusEFI `.ini` corpus and older release files.

The gates that compare HaniCore with the OEM firmware run when a 1 MiB
read of your own ECU's flash is present: set `HANICORE_OEM_READ` to its path.
Never commit it.
