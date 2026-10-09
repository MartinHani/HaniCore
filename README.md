# HaniCore

**Open standalone engine-management firmware for the Bosch ME7.1.1 ECU.**

HaniCore replaces the factory software of a Bosch ME7.1.1 (Porsche
`0261207696`, Infineon C167 at 40 MHz) with a configurable engine controller
that is tuned in TunerStudio. The ECU hardware is used as it is: eight
injector and eight ignition outputs, the electronic-throttle H-bridge, two
on-board CJ120 wideband controllers, knock inputs and the K-line. The image
is built entirely from this repository — it contains no Bosch code, boot
region included.

> **Status: 1.0-dev, active development, not road-ready.** Earlier builds
> started and ran a VW/Audi 1.8T (AWT) on HaniCore fuel and spark. The
> current runtime is proven in simulation and boots on the bench; its engine
> timing has not yet been measured on hardware. Details: [STATUS.md](docs/STATUS.md).

| | |
|---|---|
| Target | Bosch ME7.1.1, `0261207696` (Porsche), C167CR-class CPU, 1 MiB AM29F800 flash, S5500 peripheral ASIC |
| First vehicle | VW/Audi 1.8T 20V turbo, drive-by-wire (engine code AWT), with a connector adaptation |
| Tuning | TunerStudio MS over the K-line, generated project file, connection plugin included |
| Toolchain | Keil C166 V7.53 (commercial, not included), Python 3.13, Windows |
| License | GPL-3.0-or-later |

## Highlights

* **Engine-agnostic by configuration.** Cylinder count, firing order, trigger
  wheel, cam pattern, sensors, injection and ignition strategy, and the
  routing of every function to a connector cavity are page settings, checked
  by a validator before anything is driven.
* **The whole ECU from source.** Injectors, coils, the throttle bridge, the
  S5500 ASIC link, the CJ120 wideband controllers and the knock front end are
  driven by HaniCore code; every board fact is documented with its source.
* **Tested against the linked image.** About 200 offline gates, most of them
  running the built firmware in an instruction-level C167 simulator; the
  critical ones carry a negative control that must fail.

## Features

| area | |
|---|---|
| Fuel | fuel models: speed density, pure alpha-N, boosted alpha-N (throttle VE + charge-pressure density), and legacy compatibility; onboard barometric sensor; VE and target-lambda tables; injector flow and dead-time model; warm-up, after-start, X-tau wall film; cranking fuel by mass; DFCO; closed-loop trim |
| Ignition | timing tables with CLT/IAT corrections, dwell vs battery, overdwell protection, closed-loop idle timing, per-cylinder knock retard |
| Injection and spark | batch, semi-sequential, sequential; wasted or sequential coil-on-plug, with a crank-only fallback until the cam has resolved the cycle |
| Trigger | missing-tooth crank wheels (VR or Hall), cam level or pattern decoding, named firing orders, tooth and composite loggers |
| Air | electronic throttle with on-ECU commissioning (endpoint calibration, relay PID autotune, friction characterization), idle control, boost control, two VVT outputs |
| Protection | rev limiter (fuel / spark / soft), coolant and throttle-fault limp, injector duty cut, overboost cut, pressure-loss and lean protection, flood clear |
| Diagnostics | trouble codes, per-consumer sensor fallbacks, engine event recorder, read-only vehicle logger with automatic analysis |
| Calibration | 4 KiB page with transactional writes; Burn to an append-only flash store with validation and fallback; built-in and user presets |
| Link | TunerStudio at 57600 / 115200 baud, VAG/KWP 5-baud entry, TunerStudio connection plugin |

## Validation

| level | what it covers today |
|---|---|
| **Vehicle** (1.8T AWT) | crank sync, batch and wasted-spark operation, alpha-N × pressure load, coolant and pressure sensors, pedal, TunerStudio over the K-line — on earlier builds |
| **Bench** (real ECU) | owned boot region, flashing, Burn and flash restore, link and KWP entry, throttle control and commissioning on a bench throttle body, CJ120 modes and heater gates, main relay, fuel-pump output |
| **Simulator** (linked image) | the current runtime: planner, compare-interrupt executor, sequential switch-over, fuel and ignition models, closed loops, timing budgets at 1000–9600 rpm with TunerStudio traffic |

Function by function: [STATUS.md](docs/STATUS.md).

## Getting started

```powershell
git clone https://github.com/MartinHani/HaniCore.git
cd HaniCore
py -m pip install -r requirements.txt
py tools\build\build_hanicore_me711.py     # firmware image -> bins\hanicore\
py tools\tunerstudio\gen_ts_ini_me711.py   # matching TunerStudio project file
py tests\run_gates.py fast                 # offline checks, a few minutes
```

Flashing, connecting and the first start: [BUILDING.md](docs/BUILDING.md),
[TUNERSTUDIO.md](docs/TUNERSTUDIO.md), [COMMISSIONING.md](docs/COMMISSIONING.md).

## TunerStudio

The project file and dashboard are generated from the firmware's
configuration model, so offsets, scales and menus always match the image.
`tunerstudio/plugin/` holds the K-line connection plugin (source in
`tools/tunerstudio/plugin/`, rebuildable byte for byte).

The ECU identifies itself as `rusEFI HaniCore ME711 <layout>`. The prefix
selects TunerStudio's rusEFI-protocol handling; **HaniCore is not rusEFI
firmware** and is not affiliated with rusEFI, whose work is the reference for
many of its control concepts. The prefix stays until a native signature is
supported.

## Documentation

| | |
|---|---|
| [STATUS.md](docs/STATUS.md) | proof level of every function, runtime timing, limitations |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | firmware structure, configuration, engine model, runtime |
| [PLATFORM.md](docs/PLATFORM.md) | the ME7.1.1 hardware, flash layout, boot region, AWT harness adaptation |
| [PINOUT.md](docs/PINOUT.md) | every connector cavity and what it can do |
| [BUILDING.md](docs/BUILDING.md) | build pipeline, flashing, restoring a calibration |
| [TUNERSTUDIO.md](docs/TUNERSTUDIO.md) | project files, connecting, presets |
| [COMMISSIONING.md](docs/COMMISSIONING.md) | bench setup and first start |
| [TESTING.md](docs/TESTING.md) | the gates and current results |
| [CONTRIBUTING.md](docs/CONTRIBUTING.md) | layout, rules, generated files, versioning |
| [LICENSING.md](docs/LICENSING.md) | license and provenance |

## Safety

This firmware drives injectors, ignition coils, a fuel pump and an electronic
throttle. A configuration error or a firmware defect can damage an engine or
cause a fire or a crash. Use it on test benches and in closed test
environments, off public roads.

## License

GPL-3.0-or-later ([LICENSE](LICENSE)), with an additional permission that
lets the TunerStudio plugin run inside TunerStudio. No warranty. Provenance:
[LICENSING.md](docs/LICENSING.md).
