# tools/

Developer tools by purpose. Each script's docstring is its manual.

| directory | contents | start with |
|---|---|---|
| `build/` | image build, boot region, vector table, image validation, release packaging | `build_hanicore_me711.py` |
| `config_source/` | the configuration model (page fields, presets, hardware descriptor) and its generator; `data/` holds the connector tables | `generate_config.py` |
| `tunerstudio/` | `.ini` and dashboard generators, `.ini` audits, the K-line plugin (`plugin/`) | `gen_ts_ini_me711.py` |
| `flash/` | boot-mode wrapper, calibration restore, flash verification | `me7boot/hanicore_me7boot.py` |
| `calibration/` | user presets, calibration migration across page layouts, VE axis re-binning | `me711_user_presets.py` |
| `vehicle/` | vehicle logger and its analysis, throttle and trigger commissioning on the car, KWP entry | `me711_vehicle_test.py` |
| `bench/` | K-line capture, output-channel snapshots, serial probing, logic-analyser capture | `me711_och_snapshot.py` |
| `analysis/` | code-space, stack and interrupt-budget reports; runtime stress rig; OEM-binary analysis helpers (need your own ECU read) | `me711_stack_static.py` |
| `research/` | `.ini` parser and audits used by the TunerStudio gates | `ts_ini.py` |
| `maintenance/` | repository checks, generated documentation | `check_repo_paths.py` |
| `lib/` | shared modules: `hcpaths`, the C167 simulator `c167sim`, `me711_image`, `c166_disasm`, `host_c_test` | `py tools\lib\hcpaths.py` |

* Every script puts `tools/lib` on `sys.path` and imports `hcpaths`, which
  makes every module under `tools/` and `tests/` importable by name.
* Paths come from `hcpaths` or the script's location, never from a personal
  absolute path.
* Anything that can power hardware, write flash or move an actuator refuses
  without an explicit flag.
