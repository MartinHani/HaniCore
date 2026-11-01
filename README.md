# HaniCore

**Open standalone engine-management firmware for Bosch ME7 ECUs.**

HaniCore replaces the factory software of a Bosch ME7 ECU with a configurable
engine controller, tuned with [LibreTune](#tuning-app-libretune) over an
ordinary KKL (K-line) cable. Every image runs on HaniCore's own boot region:
it contains no Bosch code. 1.0-dev, not road-ready. Test car: VW/Audi 1.8T,
drive-by-wire, on the Porsche ECU.

| ECU (`--board`) | hardware | release files | proven |
|---|---|---|---|
| Porsche ME7.1.1 (`porsche`, the default) | `0261207696`, C167 40 MHz | `HaniCore_Porsche_022906032BT_<build>` | **car** (1.8T) and bench (outputs, crank, Burn, OBD update) |
| Audi 2.7T ME7.1 (`27t`) | `4B0907551F` / `0261206378`, C167CR 24 MHz | `HaniCore_27T_4B0907551F_<build>` | bench (outputs, crank to 7500 rpm, Burn, OBD update); ceiling 7800 rpm |
| Audi 4F 4.2 V8 ME7.1.1 (`4f`) | `0261208363`, C167 40 MHz | `HaniCore_4F_4F0910560_<build>` | experimental: simulator, and a tester's ECU connects |
| VAG 1.8T ME7.5 (`18t`) | `4B0906018DC` / `0261207636`, C167CR 24 MHz | `HaniCore_18T_4B0906018DC_<build>` | bench (outputs, crank to 7000 rpm, Burn, OBD update); not yet in a car |

## Features

* crank and cam sync, sequential injection and sequential coil-on-plug
  (wasted spark until the cam has found the cycle)
* fuel: alpha-N × charge pressure, VE, warm-up, after-start, wall film,
  cranking, DFCO
* ignition tables, dwell, CLT/IAT corrections
* wideband lambda (on-board CJ120, bank 1) and closed-loop fuel trim
* electronic throttle: control, idle, AutoCal, PID autotune, friction
  characterization
* boost control (N75, open or closed loop) and overboost fuel cut
* cable throttle: idle air valve (2- or 3-wire) on a PWM output, single-track
  TPS (simulator only so far)
* sensors: coolant, charge pressure, onboard baro, throttle, pedal, battery
* Burn in the car, main relay and run-on, fuel pump, tacho output
* tuning over the K-line, direct (cavity 43) or the car's diagnostic port
* firmware update over the same K-line, ECU closed, tune kept (below)
* read-only vehicle logger with automatic analysis
  (`tools\vehicle\me711_vehicle_test.py`, `me711_log_analyze.py`)

## Not yet working / not proven

* knock control (the monitor runs; no calibration yet)
* VVT, launch, flat shift, anti-lag, check-engine lamp: simulator only
* outputs 5–8 and the second wideband bank: unused on a 4-cylinder
* no CAN
* the K-line update on the 4F: not tried on hardware (bench-proven on the
  Porsche, the 2.7T and the 1.8T ME7.5)

## Known bugs

* with the engine running, an ASIC frame checksum error every 40–60 s (no
  reset, the next frame is good). A retry no longer stretches the 10 ms frame
  raster, and the bad frame is now captured; the cause needs a car log
* at 9600 rpm full acceleration (simulation) a few injector openings are
  skipped; 9600 rpm is far above an I4 1.8T's limit (fix: the hardware-compare
  output executor, designed, not built)

Fixed, car check pending: main-loop passes of 24–41 ms (the K-line wake-up
reply held the loop; bench worst pass 44 → 11 ms).

## Build the firmware

No Keil? The flash images and `.ini` files are under
[Releases](https://github.com/MartinHani/HaniCore/releases).

Keil C166 V7.53 (not included), Python 3.11+, Windows.

```powershell
py -m pip install -r requirements.txt
py tools\build\build_hanicore.py --board 4B0907551F    # or --board all
```

`--board` is the ECU part number from the table (022906032BT, 4B0907551F,
4F0910560, 4B0906018DC). It writes `bins\release\HaniCore_27T_4B0907551F_<build>.bin`
and the `.ini` for exactly that image - the same files as a release.
Offline checks: `py tests\run_gates.py fast`.

## Flash

The image is a full 1 MiB flash image. Write
it with any ME7 boot-mode tool; do not let the tool correct checksums. A
full-image flash leaves the calibration store blank.

**Update over the K-line, ECU closed.** The release images take it: the
first one goes in by boot mode, every later one over cavity 43 or the car's
diagnostic port, engine stopped:

```powershell
py tools\flash\hc_update.py --image HaniCore_27T_4B0907551F_<build>.bin --port COM3 [--kwp]
```

It saves the tune, writes the new image, lets a resident loader install it
and puts the tune back (carried across by field name after a page-layout
change). Bench: ~40 s on the Porsche, ~60 s on the 2.7T, ~45 s on the
1.8T ME7.5. An interrupted
update is recovered by boot mode.

## Wiring

The Porsche ECU on a VAG 1.8T DBW (ME7.5) harness needs four terminal moves in the
harness connector: KL15 3 → 21, relay-switched feed 121 → 3, main-relay drive
21 → 23, intake-air temperature 85 → 26. Every cavity: [docs/PINOUT.md](docs/PINOUT.md).

## Tuning app: LibreTune

**TunerStudio is no longer supported; HaniCore uses LibreTune only.**

HaniCore is tuned with **LibreTune**, an open-source tuning app. Its K-line
support (an ordinary KKL / VAG-COM cable: the line's echo removed, the car's
OBD wake-up) is in HaniCore's LibreTune build:
[github.com/MartinHani/LibreTune/releases](https://github.com/MartinHani/LibreTune/releases)
(a fork of [RallyPat/LibreTune](https://github.com/RallyPat/LibreTune),
GPL-2.0; its own source and license).

## First setup

1. LibreTune: **New project / Connect ECU** → **K-line (KKL / VAG-COM
   cable)** → cable connected to **ECU K-line pin** (bench) or **car OBD
   socket**, the KKL's COM port, 57600 or 124800 baud. When asked for the
   ECU definition, import the board's `.ini` from the release (or from
   `tuning\` after a build).
2. Base calibration:
   * an engine with a preset (today *VAG 1.8T DBW* or *Audi 2.7T biturbo V6*): **Controller →
     Base Tunes**, choose it, **APPLY ENGINE PRESET** with the engine stopped,
     Burn, key off and on;
   * any other engine: set the engine, trigger, injectors, ignition, sensors
     and output pins yourself, then Burn.
3. Electronic throttle (**Advanced → Electronic throttle (ETB)**):
   * **Electronic Throttle Body → AutoCal ETB** (endpoints and PID);
   * **Characterization → Run ETB Characterization**, then **Save Measured
     Bias / Feedforward**;
   * **Tools → Calibrate pedal sensor**: grab both ends;
   * Burn.
4. Check the sensors and the trigger, then start.

The ECU identifies itself as `HaniCore <board> <layout>`; the layout id makes
an `.ini` for another page layout refuse to match.

## Resources used

| resource | size | used | free |
|---|---|---|---|
| near code (one 64 KiB segment) | 64 512 B | 58 622 B | 5 890 B (3 072 kept as reserve) |
| far code | 183 984 B | 119 022 B | 64 962 B |
| constants (near + huge) | 12 608 B | 10 116 B | 2 492 B |
| internal RAM (near data) | — | — | 194 B |
| on-chip XRAM | — | — | 95 B |
| user / system stack (worst case) | 512 / 634 B | — | ≤ 85 % (build gate) |
| external SRAM | 32 KiB | — | 2 648 B spare |
| calibration page | 4 096 B | 4 091 B | 5 B |
| live data block | 1 664 B | 1 578 B | 86 B |
| flash: calibration store | 576 KiB | 72 records of 8 KiB | — |
| flash, `--updater` image | — | resident loader 64 KiB, staging 256 KiB, store 40 records | — |

Porsche release image, 2026-10-30. Code space is not the limit; the
calibration page and RAM are.

## Safety

This firmware drives injectors, ignition coils, a fuel pump and an electronic
throttle. A configuration error or a firmware defect can damage an engine or
cause a fire or a crash. Use it on test benches and closed test environments,
off public roads.

## License

GPL-3.0-or-later ([LICENSE](LICENSE)). No warranty.
[docs/LICENSING.md](docs/LICENSING.md).
