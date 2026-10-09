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

Development tree, 2026-10-09.

| check | result |
|---|---|
| build from a fresh clone | pass, byte-identical image |
| generators and repository checks | pass |
| `run_gates.py fast`, fresh public clone | **70 pass, 9 red, 6 skipped** (85 gates) |
| runtime qualification gates (stress 1000–9600 rpm, fault injection, K-line under load, executor, DBW readiness, stack and resource budgets) | see [STATUS.md](STATUS.md#runtime-timing) |
| boot region (`me711_owned_boot_proof`) | pass; also bench-proven |
| Tier 1 and the full set | not run on this exact tree |

Red gates in the fast set:

| gate | cause | kind |
|---|---|---|
| `test_config_access_types` | firmware reads whose accessor does not match the field's declared type (e.g. `hc_cal_u16` on signed or table fields); some may be deliberate read-then-cast | open issue |
| `test_config_source_of_truth` | a temperature axis (`CAL_CLT_ENR_AX`) is not declared signed | open issue |
| `ts_pin_dropdown_agreement_proof` | the cam-solenoid cavity list in TunerStudio differs from what the validator accepts | open issue (UI) |
| `ts_ini_terminology_proof` | four load-panel texts use Bosch signal names | open issue (UI wording) |
| `test_hw_descriptor_evidence` | the evidence test and the hardware descriptor are out of step | needs review |
| `ts_ini_command_shape_proof` | the gate's rule about plain characters in command strings contradicts TunerStudio practice | gate defect |
| `test_plan_cost_gate` | per-tooth planning cost over the 12 000 rpm headroom budget | known limitation |
| `me711_vehicle_capture_test`, `me711_commission_tools_test` | expectations lag the current output-channel block and messages | stale tests |

Six gates skip in a public clone because they read material that is not in
the repository: the target's OEM flash and ASIC reads, the reference A2L, the
rusEFI `.ini` corpus and older release files.

The gates that compare HaniCore with the OEM firmware run when a 1 MiB
read of your own ECU's flash is present: set `HANICORE_OEM_READ` to its path.
Never commit it.

Outside the fast set, these are known to be red: `me711_kline_mixed_proof`
(transient scenario, see [STATUS.md](STATUS.md#runtime-timing)),
`me711_page_migration_proof`
(a committed record of the previous page layout is not migrated at boot —
the ECU falls back to defaults), `me711_alphan_start_proof`,
`me711_engine_control_proof`, `me711_table_order_proof`,
`me711_trigger_angle_proof`, `me711_sensor_fallback_proof`,
`me711_awt_first_start_page_proof` and `me711_preset_gap_proof` (fixtures
written for an earlier load model and executor). `near_ram_hazard_proof`,
`me711_boot_cost_proof` and `me711_plan_cost_proof` are deliberate tripwires
at their limits.
