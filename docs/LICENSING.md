# Licensing and provenance

HaniCore is licensed under the **GNU General Public License, version 3 or
(at your option) any later version** (`GPL-3.0-or-later`); the full text is in
[`LICENSE`](../LICENSE). Firmware, tools, tests, generators, the C167
simulator, the TunerStudio plugin and the documentation are all covered.

The choice is the project's, not an inherited obligation: nothing in the
repository is copied or ported from GPL code (see the audit below). It was
made so that anyone who distributes modified firmware also publishes the
source, as with rusEFI and Speeduino.

**Additional permission for the TunerStudio plugin** (GPLv3 section 7): the
code under `tools/tunerstudio/plugin/` may be combined with, and run inside,
TunerStudio and its plugin API and serial library, and the result conveyed,
without those proprietary components becoming subject to the GPL. The plugin
itself stays under the GPL.

This is development firmware for test benches and off-road use. It is not
certified for road use or emissions compliance and comes with no warranty
(GPL sections 15 and 16).

## Audit

Every source line of 30 or more characters (C, assembler, Python, Java,
linker and build files) was compared, whitespace-normalised, with the
third-party source trees available to the project: rusEFI (firmware, console,
tools — 34 000 files), Speeduino, the M744 stand-alone ECU, ME7Sum,
me7-tools, NefMoto open-source tools, C167BootTool, kw1281test and others.

* **No copied code.** The only common lines are three standard Keil startup
  directives, separator comment lines and generic Python idioms.
* No file carries a third-party license or copyright header.
* Five short TunerStudio UI labels equal labels in rusEFI's TunerStudio
  projects (the menu wording deliberately follows rusEFI's).

## What the repository contains

| category | content |
|---|---|
| **Original work** | all firmware, tools, tests, generators, the simulator, the plugin and the documentation |
| **Concepts from other projects, independently implemented** | control strategies and parameter sets published by rusEFI and Speeduino (X-tau wall film, relay PID autotune, quick-start cam decoding, limp management); the TunerStudio menu structure; a few numeric starting values from rusEFI's source (throttle-body PID gains and bias curve, overrun fuel-cut thresholds, idle-timing defaults), each cited where it is used |
| **Interfaces and formats** | TunerStudio's `.ini` format and serial protocol, ISO 14230 / KWP2000 entry, the C167 bootstrap-loader protocol, AM29F800 command sequences, Keil startup conventions |
| **Hardware facts** | register values, pin and connector assignments, the S5500 startup handshake, the boot-ROM header layout and markers, Bosch signal names in the connector tables (`tools/config_source/data/`), and the coolant and intake-air transfer curves of this ECU's input stages, which the 1.8T AWT preset uses. Each is cited to its source (the target's schematic, its OEM firmware, Bosch datasheets, bench measurement). They are needed to operate the hardware; no OEM code is reproduced and the license claims no rights over them |
| **OEM calibration values** | the "VAG 1.8T DBW (AWT)" preset takes its injector, dead-time, cranking-dwell, pressure-sensor, VE (from the stock throttle model), ignition-timing and knock values from the stock AWT ECU image (VW `4B0906018DC`), converted to HaniCore's units; each value cites the map it came from (`tools/config_source/hanicore_presets.py`). The image itself is not included |
| **Not contained** | OEM firmware or boot code, OEM ECU images, A2L/DAMOS files, schematics, datasheets |

## Third-party software used but not included

| software | license | use |
|---|---|---|
| Keil C166 | proprietary | compiler; its headers come from the installation |
| TunerStudio MS and its plugin API | proprietary | the plugin is compiled against the API and uses TunerStudio's serial library at run time; neither is redistributed |
| C167BootTool (EcuProg7) | GPL-3.0 | boot-mode flasher, downloaded by `tools/flash/me7boot/install.ps1` and run as a separate program |
| pyserial, pytest | BSD-3-Clause, MIT | installed from PyPI |
