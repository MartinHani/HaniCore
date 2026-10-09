# TunerStudio

HaniCore is tuned with **TunerStudio MS 3.3.01** (EFI Analytics). The
project file (`.ini`) and default dashboard are generated from the firmware's
configuration model and must match the image in the ECU.

## Files

```powershell
py tools\tunerstudio\gen_ts_ini_me711.py
```

| file | contents |
|---|---|
| `tunerstudio/hanicore_me711.ini` | the `.ini` for the image built from the same tree |
| `tunerstudio/hanicore_me711_<stem>.ini` | the same file under the image's name |
| `tunerstudio/hanicore_me711_<stem>_forensic.ini` | read-only variant with the extended diagnostic channels |
| `tunerstudio/hanicore_me711_<stem>_userdefined_fallback.ini` | variant for TunerStudio builds that reject newer dialog syntax |
| `tunerstudio/HaniCore.dash` | default gauge cluster (needs a local rusEFI checkout to generate) |
| `tunerstudio/plugin/` | the K-line connection plugin (published binary) |

Never edit a generated `.ini`; change the generator
(`tools/tunerstudio/gen_ts_*.py`, `ts_gauges_me711.py`,
`ts_semantics_me711.py`) and regenerate.

## Signature

The firmware answers `rusEFI HaniCore ME711 <layout id>`. The layout id is a
CRC of the page layout, so TunerStudio refuses an `.ini` built for another
layout — it cannot write values to the wrong offsets. The output-channel block
size must also match; the build and the Tier 1 gates check both.

**HaniCore is not rusEFI firmware** and is not affiliated with the rusEFI
project. The `rusEFI` prefix is a TunerStudio compatibility workaround:
TunerStudio selects its rusEFI-protocol handling (framed CRC commands, the
output-channel and logger requests HaniCore implements) from it. The build
refuses a signature without it. It will change only when a supported way to
register a native HaniCore signature has been proven against real
TunerStudio.

## Connecting

The ECU's serial port is the K-line on cavity 43. A KKL (FTDI) cable echoes
every byte the PC sends, and the ECU expects either a direct connection at
its current baud rate or a VAG/KWP 5-baud entry, as on the car's diagnostic
port. Stock TunerStudio handles neither, so HaniCore ships a connection plugin.

1. Install `tunerstudio/plugin/HaniCore_KLine_Transport_<version>.jar`:
   *Tools → TunerStudio Plugins → Add or Update a Plugin*, then restart
   TunerStudio.
2. Create a project with `tunerstudio/hanicore_me711.ini`.
3. Connection type **HaniCore K-Line**, the KKL's COM port, 115200 baud.

On open, the plugin probes the ECU directly at TunerStudio's baud rate.
Failing that, it performs the KWP entry (5-baud init, handshake, rate change)
and hands the port to TunerStudio, removing the echo. It also re-enters a
session that went silent. The ECU starts at 57600 baud and follows the host
to 115200 (stock TunerStudio offers no 124800). The direct connection on
cavity 43 is proven on the bench and in the car; the car's shared OBD K-line
path is not yet proven.

The plugin contains only HaniCore classes. It is compiled against
TunerStudio's plugin API and uses TunerStudio's serial library at run time;
neither is redistributed. Rebuild and check it against the published binary:

```powershell
py tools\tunerstudio\plugin\build_plugin.py --ts "<TunerStudio folder>" --verify
```

The build is deterministic. `HaniCore_KLine_Transport_<version>.jar.json`
records the jar hash, the hash of every source file, the JDK and the
TunerStudio jars it was compiled against. `--verify` rebuilds and reports
whether the result is byte-identical, and if not, which source changed.

## Presets

**Built-in presets** are compiled into the firmware: *Controller → Base
Tunes*, choose a preset, press **APPLY ENGINE PRESET** with the engine
stopped. The preset is applied as one transaction; a refusal leaves the page
unchanged and names the field. It never Burns. Built-ins:

* **Board default** — what is true of this ECU whatever engine is fitted; a
  fresh or blank-store ECU starts on it.
* **VAG 1.8T DBW (AWT)** — routing, trigger, cam, strategies and engineering
  starting points for the AWT. It deliberately does **not** set injector,
  coil or pressure-sensor data, or VE and ignition tables (named gaps). With
  no injector flow entered, a fresh page delivers no fuel.
* **Custom** — nothing is set.

The list also shows two entries this ECU refuses: the AWT configuration for
the ME7.5 board, and the incomplete Porsche V8 donor engine (its firing
order is not sourced).

**User presets** are snapshots of a whole calibration page, kept on the PC
(`%HANICORE_USER_PRESETS%`, default `~/.hanicore/user_presets/`, one JSON
file each, tied to the page layout):

```powershell
py tools\calibration\me711_user_presets.py list
py tools\calibration\me711_user_presets.py save "My AWT" --from-ecu --port COM3
py tools\calibration\me711_user_presets.py save "My AWT" --from-dump readback.bin
py tools\calibration\me711_user_presets.py apply "My AWT" --port COM3 [--dry-run]
py tools\calibration\me711_user_presets.py delete "My AWT" --yes
```

* Built-in names cannot be used, replaced or deleted. A name collision needs
  `--replace`. Files are written atomically and carry a checksum; a preset
  saved for another page layout is listed but not applied.
* `apply` needs the engine stopped. It writes only the bytes that differ,
  with TunerStudio's own page writes, reads the page back, reports whether
  the ECU accepts the result as a runnable setup, and never Burns. If the ECU
  refuses a write part-way, the bytes already written are put back. Throttle
  and pedal endpoints and the throttle bias curve are skipped unless
  `--include-measured` is given: they belong to one throttle body and one
  pedal.
* A preset that differs from the ECU's page by more than one configuration
  transaction holds is refused. Apply the built-in it was based on first.
* TunerStudio and the user-preset tool cannot share the serial port; close
  TunerStudio first.

User presets live on the PC on purpose. The ECU's flash store holds the
working page, and TunerStudio's own tune files (`.msq`) already keep any
number of whole tunes; the preset tool adds the layout check, keeps the
built-in names apart and leaves per-unit measurements alone.

## Layout

The menus follow rusEFI's TunerStudio projects: settings and live values in
one dialog, tables with rpm/load axes and tracers, curves where they are
calibrated, and test buttons in the dialog of the thing they test. Pin
selectors show connector cavities ("93 - Coolant temperature"), never CPU
ports. A field the firmware does not read is labelled "(not used)".
Diagnostics and developer channels live under Diagnostics and Controller.
Electronic throttle commissioning is under *Advanced → Electronic Throttle
Body* ([COMMISSIONING.md](COMMISSIONING.md)).

Any TunerStudio response code with bit 7 set ends the session, so the
firmware answers refused operations with OK and publishes the outcome
(validation result, Burn state, command verdicts) in output channels.
