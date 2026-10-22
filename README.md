# HaniCore

**Open standalone engine-management firmware for the Bosch ME7.1.1 ECU.**

HaniCore replaces the factory software of a Bosch ME7.1.1 (Porsche
`0261207696`, C167 at 40 MHz) with a configurable engine controller tuned in
TunerStudio. It contains no Bosch code, boot region included. 1.0-dev, not
road-ready. Test car: VW/Audi 1.8T AWT, drive-by-wire.

**Second target in the works: the VAG 1.8T ME7.5 ECU (1 MiB flash).** The
same firmware will run on both; the ME7.5 traces in the tree (its pin
descriptor, `hchal_me75` references) belong to that port and are not usable
yet.

## Works on the car

* crank and cam sync, sequential injection and sequential coil-on-plug
  (wasted spark until the cam has found the cycle)
* fuel: alpha-N × charge pressure, VE, warm-up, after-start, wall film,
  cranking, DFCO
* ignition tables, dwell, CLT/IAT corrections
* wideband lambda (on-board CJ120, bank 1) and closed-loop fuel trim
* electronic throttle: control, idle, AutoCal, friction characterization
* sensors: coolant, charge pressure, onboard baro, throttle, pedal, battery
* Burn in the car, main relay and run-on, fuel pump, tacho output
* TunerStudio over the K-line, direct (cavity 43) or the car's diagnostic port

## Not yet working / not proven

* boost control and overboost cut under load
* knock control (the monitor runs; no calibration yet)
* throttle PID autotune on a car (works on the bench)
* wall-film values still need tuning (quick throttle goes rich)
* VVT, launch, flat shift, anti-lag, check-engine lamp: simulator only
* outputs 5–8 and the second wideband bank: unused on a 4-cylinder
* no CAN, no firmware update without opening the ECU

## Known bugs

* a TunerStudio request sent while a Burn is being written gets no reply;
  TunerStudio retries it
* with the engine running, an ASIC frame checksum error every 40–60 s (no
  reset, the next frame is good)
* above 2000 rpm a main-loop pass can take up to 24 ms, which delays throttle
  steps and TunerStudio replies
* at 9600 rpm full acceleration (simulation) a few injector openings are
  skipped; 9600 rpm is far above the AWT's limit

## Build the firmware

No Keil? The flash image, `.ini` and plugin are under
[Releases](https://github.com/MartinHani/HaniCore/releases).

Keil C166 V7.53 (not included), Python 3.11+, Windows.

```powershell
py -m pip install -r requirements.txt
py tools\build\build_hanicore_me711.py     # image -> bins\hanicore\
py tools\tunerstudio\gen_ts_ini_me711.py   # matching TunerStudio .ini -> tunerstudio\
py tests\run_gates.py fast                 # offline checks
```

## Flash

The build writes a full 1 MiB flash image, `bins\hanicore\<image>.bin`. Write
it with any ME7 boot-mode tool; do not let the tool correct checksums.

## Wiring

The Porsche ECU on a VAG 1.8T (AWT) harness needs four terminal moves in the
harness connector: KL15 3 → 21, relay-switched feed 121 → 3, main-relay drive
21 → 23, intake-air temperature 85 → 26. Every cavity: [docs/PINOUT.md](docs/PINOUT.md).

## First setup

1. TunerStudio: **Tools → TunerStudio Plugins → Add or Update a Plugin**,
   pick `tunerstudio/plugin/HaniCore_KLine_Transport_<version>.jar`, restart
   TunerStudio. Create a project with the generated `.ini`, connection type
   **HaniCore K-Line**, 115200 baud.
2. Base calibration:
   * an engine with a preset (today *VAG 1.8T DBW (AWT)*): **Controller →
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

The ECU identifies itself as `rusEFI HaniCore ME711 <layout>` so TunerStudio
uses its rusEFI protocol handling. HaniCore is not rusEFI firmware and is not
affiliated with rusEFI.

## Resources used

| resource | size | used | free |
|---|---|---|---|
| near code (one 64 KiB segment) | 64 512 B | 61 068 B | 3 444 B (3 072 kept as reserve) |
| far code | 183 984 B | 116 768 B | 67 216 B |
| constants (near + huge) | 12 608 B | 10 172 B | 2 436 B |
| internal RAM (near data) | — | — | 192 B |
| on-chip XRAM | 1 696 B | 1 631 B | 65 B |
| user / system stack (worst case) | 512 / 634 B | 426 / 534 B | 83 % / 84 % used |
| external SRAM | 32 KiB | 32 KiB | 0 (every byte assigned) |
| calibration page | 4 096 B | 4 091 B | 5 B |
| TunerStudio live data block | 1 664 B | 1 664 B | 0 |
| flash: calibration store | 576 KiB | 72 records of 8 KiB | — |
| flash: reserved for a future K-line updater | 64 KiB | — | — |

Code space is not the limit; the calibration page, the live data block and
RAM are. A good part of them still holds debug and bring-up leftovers (old
diagnostics, unused calibration fields, developer channels); cleaning that up
is in progress.

## Safety

This firmware drives injectors, ignition coils, a fuel pump and an electronic
throttle. A configuration error or a firmware defect can damage an engine or
cause a fire or a crash. Use it on test benches and closed test environments,
off public roads.

## License

GPL-3.0-or-later ([LICENSE](LICENSE)), with an additional permission that
lets the TunerStudio plugin run inside TunerStudio. No warranty.
[docs/LICENSING.md](docs/LICENSING.md).
