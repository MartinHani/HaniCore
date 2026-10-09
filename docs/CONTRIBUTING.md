# Contributing

## Repository layout

| path | contents |
|---|---|
| `firmware/` | firmware source: portable code by subsystem, the ME7.1.1 target in `firmware/targets/me711/` |
| `tools/` | build, configuration model and generators, TunerStudio generators and plugin, flashing, calibration, vehicle logging and analysis, the C167 simulator (`tools/lib/`) |
| `tests/` | every gate, by kind ([TESTING.md](TESTING.md)) |
| `tunerstudio/` | generated TunerStudio files (not committed) and the published plugin binary |
| `docs/` | this documentation |

Not in Git: built images (`bins/`), Keil build output, generated `.ini` and
dashboard files, local reference material (`reference/`), and measurement
records written by the bench and vehicle tools (`HANICORE_RAW_EVIDENCE`,
default an `evidence` folder beside the repository).

## Generated files

Edit the generator, never its output.

| output | generator | input |
|---|---|---|
| `firmware/generated/*` | `tools/config_source/generate_config.py` | the page model, presets and hardware descriptor in `tools/config_source/` |
| `firmware/targets/me711/generated/*` | `tools/build/gen_vector_probe.py me711` | the trap table in the generator |
| `tunerstudio/*.ini` | `tools/tunerstudio/gen_ts_ini_me711.py` | firmware headers and the config model |
| `tunerstudio/HaniCore.dash` | `tools/tunerstudio/gen_hanicore_dash.py` | the `.ini` |
| `docs/PINOUT.md` | `tools/maintenance/gen_descriptor_doc.py` | the hardware descriptor |
| `tunerstudio/plugin/*.jar` | `tools/tunerstudio/plugin/build_plugin.py --publish` | the plugin sources |

The build refuses stale generated sources. Generated text is pinned to LF in
`.gitattributes` so a Windows clone builds byte-identically.

## Firmware rules

* Portable code (`firmware/<subsystem>/`) touches no register. Board facts
  belong in `firmware/targets/me711/hctarget.h`, each with its source.
* No engine-specific constant in firmware, and no runtime path keyed on a
  preset.
* Hot paths (per tooth, per event, interrupts): fixed point, bounded loops, no
  dynamic allocation, no floating point. State the cost of a hot-path change
  in instructions.
* Engine timing always wins. A new subsystem is not finished until its
  worst-case CPU time, interrupt impact, stack, RAM, code space and buffers
  are bounded and the runtime gates pass (`run_gates.py --tag runtime`).
* Interrupt handlers, trigger, planner, executor and ASIC exchange stay in
  near code. Cold code goes far (`MOD167 MEDIUM`) and must not call Keil's
  near long-arithmetic helpers (check the listing for `CALLS ?C_`).
* Two enabled interrupt sources never share a priority pair. Never clear the
  global interrupt enable where an ASIC frame can be in flight; raise the
  interrupt level instead.
* Startup runs no C initialisation: set every variable in code.
* Outputs rest released; OFF writes the inactive level, then releases.
  Permissions gate ON, never OFF. A permission is a level; a fault latches.
* Services take the uptime and keep their own last time. A command handler
  never does long work — it stages it.
* Changes to the S5500 exchange need hardware-grade evidence.
* File names are part of the linker contract; move files freely, rename them
  deliberately.
* Keil C166 V7.53 can overwrite a shift count with its own register;
  `tests/firmware/build/me711_keil_shift_scan.py` rejects it.

## Tools and tests

* Every script puts `tools/lib` on `sys.path` and imports `hcpaths`; paths
  come from there or from the script's location, never from a personal
  absolute path. `py tools\maintenance\check_repo_paths.py` checks this.
* A tool that can power hardware, write flash or move an actuator refuses
  without an explicit flag naming that decision.
* Every gate has a negative control and reads the linked image where it
  can. A new gate is registered by its location under `tests/`.
* Preserve each file's line endings; the repository mixes LF and CRLF.

## Versions and releases

* The public version is **1.0-dev** until the first release, **v1.0.0**.
  Releases are annotated tags `vX.Y.Z` on `master`.
* Internal build names (`V102` in the firmware version text and the image
  stem, `Vnn` in comments) are development counters, not release versions.
* The page layout id in the TunerStudio signature decides which `.ini` and
  which stored calibration belong to an image.
* A release will contain the image built from the tag with its manifest and
  `SHA256SUMS`, the generated TunerStudio files, the plugin, and notes giving
  the proof level of every changed function and the test results on that
  image. No release has been made.
