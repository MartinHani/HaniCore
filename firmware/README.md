# firmware/

Everything compiled into a HaniCore image.

| directory | contents |
|---|---|
| `config/` | calibration page, DESIRED/ACTIVE manager, validator, pin router |
| `engine/` | load and air/fuel model, cylinder event geometry, transient fuel, cam decoding |
| `control/` | electronic throttle, idle, boost, VVT, knock, engine protection, fuel pump, main relay |
| `sensors/` | wideband controller (CJ120 + LSU 4.2) |
| `diagnostics/` | trouble codes, check-engine lamp |
| `comms/` | K-line transport, TunerStudio server, KWP entry |
| `hal/` | `hchal.h`, the hardware-abstraction contract |
| `generated/` | generated page layout, pin descriptor and presets (`tools/config_source/generate_config.py`) |
| `targets/me711/` | the Bosch ME7.1.1 target: board header, HAL, ASIC exchange, trigger, planner and executor, flash store, startup |

Code outside `targets/` is portable: it touches no register, and no portable
directory contains an `hctarget.h`, so a portable unit always picks up the
header of the target being built. Header names are unique across the include
path; `py tools\lib\hcpaths.py` checks both rules.

Design: [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md). Build:
`py tools\build\build_hanicore_me711.py`.
