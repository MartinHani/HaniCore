# Architecture

HaniCore is a complete replacement firmware for the Bosch ME7.1.1. It keeps
the ECU's hardware and nothing of the OEM software. The hardware itself is
described in [PLATFORM.md](PLATFORM.md).

## Structure

```
  TunerStudio ──K-line──► comms/        TunerStudio server, VAG/KWP entry
                            │
                            ▼
  page (4096 B) ◄──── config/          DESIRED/ACTIVE page, validation,
                            │           pin routing, presets
                            ▼
      engine/   control/   sensors/   diagnostics/            portable C,
      load, fuel, DBW, idle, boost,   wideband   DTC, lamp     no registers
      ignition   VVT, knock, limp
                            │  semantic channels (hal/hchal.h)
  ──────────────────────────┼──────────────────────────────────────────────
                            ▼
      targets/me711/   HAL, trigger capture, planner and edge executor,
                       ETB commissioning, S5500 exchange, flash store,
                       startup and boot region
  ──────────────────────────┼──────────────────────────────────────────────
                            ▼
      C167 CAPCOM/PWM/ADC/SSC/ASC0 · S5500 · CJ910 · CJ920 · CK110 · CJ220
      · CJ120 · AM29F800BB · battery-backed SRAM
```

Two rules hold this together:

* **Everything engine-specific is configuration.** Cylinder count, firing
  order, trigger wheel, cam pattern, sensors, injector and coil routing,
  strategies and calibration are page fields. There is no engine constant in
  the firmware and no runtime path keyed on a preset.
* **Everything board-specific lives in `firmware/targets/me711/`.** Portable
  code touches no register. Board facts (which CPU pin drives which stage,
  stage polarity, ADC channels) are in `hctarget.h`, each with its source.

| directory | contents |
|---|---|
| `firmware/config/` | the page, the DESIRED/ACTIVE manager with apply policies and transactions, the validator, the pin router |
| `firmware/engine/` | load and air/fuel model, cylinder event geometry, transient fuel, cam pattern decoding |
| `firmware/control/` | electronic throttle, idle, boost, VVT, knock, engine protection, fuel pump and main relay |
| `firmware/sensors/` | wideband controller (CJ120 + LSU 4.2) |
| `firmware/diagnostics/` | trouble codes, check-engine lamp |
| `firmware/comms/` | K-line transport, TunerStudio server, KWP entry |
| `firmware/hal/` | the HAL contract the target implements |
| `firmware/generated/` | page layout, pin descriptor, presets — generated from `tools/config_source/` |
| `firmware/targets/me711/` | the ME7.1.1 target: HAL, ASIC exchange, trigger and scheduler, flash store, startup |

## Configuration

* One **4096-byte calibration page**, defined by the model in
  `tools/config_source/`. The generator writes the C layout and the
  TunerStudio view from that model; a CRC of the field layout (the layout id)
  is part of the TunerStudio signature, so an `.ini` built for another layout
  cannot connect.
* **DESIRED and ACTIVE.** TunerStudio writes DESIRED. Each field has an apply
  policy: immediately, with the engine stopped, or at restart. A Burn with
  the engine stopped is the restart point.
* **Validation.** A page is checked as a whole before it reaches an output:
  electrically impossible or conflicting routes, missing cycle sync for
  sequential strategies, out-of-range values. A refused page drives nothing,
  and the first failing field is published to TunerStudio.
* **Routing.** TunerStudio exposes connector cavities (1–121) only. The router
  maps cavity → capability → CPU/ASIC resource from the hardware descriptor.
  A configured cavity is the one the firmware actually uses.
* **Presets** fill ordinary fields and are applied as one transaction (stage,
  validate, roll back on refusal) by APPLY ENGINE PRESET. A preset never sets
  what it cannot source; such fields are named gaps. User presets are kept on
  the PC ([TUNERSTUDIO.md](TUNERSTUDIO.md#presets)).
* **Persistence.** A Burn snapshots the page and programs it into an
  append-only store in flash (eighty 8 KiB cells), in bounded slices between
  engine work. The previous record stays valid until the new one is complete.
  At boot the newest valid record is used. A record that fails validation
  falls back to older records (up to four), then to a runnable board default.

## Engine model

* **Load**: one of four fuel models (below). Air mass → target lambda → fuel
  mass → injector flow and dead time → pulse width.
* **Fuel**: VE and target-lambda tables, warm-up, after-start, X-tau wall
  film, cranking fuel as mass, priming, DFCO, closed-loop short-term trim
  (only while the wideband reports a valid, moving signal).
* **Ignition**: signed timing table, CLT/IAT corrections, closed-loop idle
  timing, dwell against battery voltage, overdwell limit, knock retard.
* **Injection and ignition strategies**: batch, semi-sequential, sequential;
  wasted or sequential coil-on-plug. Sequential strategies run their
  crank-only fallback (two half pulses, wasted spark) until the cam has
  established the cycle, then switch per cylinder.
* **Sensor faults**: an invalid sensor shows one fault value (−40 °C, 0 kPa);
  each consumer applies its own documented fallback.
* **Limits**: rev limiter (fuel, spark or both, soft limit), coolant and
  throttle-fault protection, injector duty cut, overboost fuel cut, flood
  clear, pressure-loss and lean protection.

### Fuel model

The air in each cylinder is

    air = density × (displacement / cylinders) × VE(rpm, VE axis)
    density = p_density / (R_air × T)
    fuel = air / (stoichiometric ratio × target lambda)

Three things are chosen separately, and the TunerStudio project names each
one (*Fuel → Fuel model*):

* the **VE table axis** — what the VE table is looked up on;
* the **air-density pressure** `p_density` — which pressure enters the
  density, exactly once (there is no second pressure multiplier);
* the **pressure sensor location** — where the one external pressure sensor
  physically measures: manifold (after the throttle) or charge pressure
  (before the throttle).

| fuel model | VE table axis | air-density pressure | needs |
|---|---|---|---|
| Pure Alpha-N | throttle position | reference pressure, optionally corrected by ambient | no pressure sensor |
| Speed density | manifold pressure | the same measured manifold pressure | a manifold sensor |
| Boosted Alpha-N | throttle position | measured charge pressure, or ambient + boost blend | a charge-pressure sensor |
| Legacy compatibility | per legacy variant | per legacy variant | — |

*Ambient + boost blend*: `gauge = max(p_charge − p_ambient, 0)`,
`w = clamp((gauge − start) / (full − start), 0, 1)`,
`p_density = p_ambient + gauge × w` — ambient density off boost, the measured
charge pressure fully above `full`.

*Legacy compatibility* keeps HaniCore's original three load strategies
byte-for-byte for existing calibrations: speed density (MAP axis, measured
pressure), alpha-N + measured pressure (throttle axis, the measured pressure —
the AWT base tune), and pure alpha-N (throttle axis, 101.3 kPa). A failed
pressure sensor fuels from the pressure estimate table (rpm × throttle).

Legacy alpha-N + measured pressure and Boosted Alpha-N with measured density
compute the same air while every sensor is valid. They differ on faults:

| condition | Legacy alpha-N + measured pressure | Boosted Alpha-N |
|---|---|---|
| pressure sensor fault | pressure estimate table (rpm × throttle) | no density pressure: no fuel, plus the pressure-loss cut under load |
| pressure reading older than *Pressure reading maximum age*, or outside 10–500 kPa | used unless the sensor's own fault detection rejects it | treated as lost |
| intake air temperature fault | 0 °C (rich side) | 20 °C |
| intake air temperature not selected | always uses it | 20 °C |

The VAG 1.8T (AWT) base tune therefore stays on Legacy compatibility, with the
sensor location (charge pressure) and the ambient source (onboard sensor)
stated explicitly; switching it to Boosted Alpha-N is a deliberate choice of
those fault semantics.

The configuration is refused when the location does not fit the model (Speed
density needs a manifold sensor, Boosted Alpha-N a charge-pressure sensor).
Changing the model never rescales the VE table: a VE table is an effective
filling model on its own axis and density basis, so it is retuned, not
converted.

The ignition and target-lambda tables have their own load selector: the fuel
load, the pressure sensor, the throttle or the cylinder filling. On a VAG
1.8T (AWT), "pressure sensor" is charge pressure, not manifold load.

**Ambient pressure** is used only by Pure Alpha-N's ambient correction and by
the Boosted Alpha-N blend. Sources: the ECU's **onboard barometric sensor**
(an absolute-pressure sensor on the circuit board, read through the I/O chip
every 10 ms; converted with this ECU's own factory calibration and accepted
between 400 and 1200 hPa — see [PLATFORM.md](PLATFORM.md#onboard-barometric-sensor));
the external pressure sensor read after 1 s with the engine stopped, kept for
a set time and never learnt from running boost; or a fixed reference. A
missing or out-of-range reading falls back to the reference.

**Protection**: Speed density and Boosted Alpha-N have no pressure estimate:
when the pressure they need is missing or stale the density pressure is zero,
so no fuel is delivered, and above the configured rpm / throttle the
pressure-loss cut is also set (optional for the other models). The boost
valve is closed on any pressure loss. Lean protection
cuts fuel when a qualified wideband reads leaner than target by a margin for
a set time under load; it is off by default and a cold, faulted or stale
wideband can neither trigger nor release it.

## Trigger and runtime

The crank wheel, gap, edges and timeouts are page fields. The crank reference
is one number: `trigAngleX10`, the angle of the first tooth after the gap in
degrees after cylinder-1 TDC. A ±1-tooth disagreement at a confirmed gap is
corrected; two in a row lose sync. The cam can only withdraw the 720° cycle,
never the crank position. Cam phase is decided by level at a crank angle or by
a pattern library (Bosch quick-start and others).

Engine events run in interrupt context, by priority:

| context | level | job |
|---|---|---|
| SSC / PEC | 14–15 | S5500 frame (and K-line receive by PEC) |
| crank, cam capture | 12 | record a timestamp, request the planner when a walk is due |
| edge executor (CC25 compare) | 11 | drive coil and injector edges at their deadline |
| planner (CC26 software request) | 9 | convert angles to deadlines and publish them |
| 1 ms tick, reply transmit | 8 | ADC, freshness, output supervisor; K-line transmit |
| main loop | 0 | engine and control calculations, DBW, diagnostics, TunerStudio |

Each level has its own register bank; critical sections raise the interrupt
level (never clear the global enable) and stay below 50 µs.

Output safety is structural:

* Engine outputs rest released (pin direction = input). Every OFF writes the
  inactive level, then releases the pin.
* Permissions gate ON, never OFF. Spark and fuel need crank position;
  throttle, pump and relay need a valid page and the ASIC link.
* Losing sync quiesces the executor: queued ON edges are refused, committed
  OFF edges (spark, injector close) still execute at their time.
* Every dwell carries its own maximum-dwell release. An independent tick
  supervisor releases any coil held on for more than 25 ms or injector for
  more than 140 ms.
* There is no global "arm" switch for normal operation. Bench actuator tests
  are separate, bounded commands.

Simulated timing budgets and current results are in [STATUS.md](STATUS.md).

## Throttle, lambda and other closed loops

* **Electronic throttle**: PID with a bias curve (break-away midpoints), a
  signed friction term and battery compensation, 2 kHz bridge PWM. TPS and
  pedal pairs are cross-checked. Every fault, key-off and procedure end
  releases the bridge, and the springs return the plate to its limp opening.
  Commissioning (endpoint calibration, relay autotune, verify,
  characterization) runs on the ECU and is started from TunerStudio.
* **Wideband**: two CJ120 controllers on the SSC shared with the S5500.
  Heater control is staged (dew wait, preheat, ramp, closed loop on Ri).
  Lambda is published only when the sensor is ready, the pump is on and the
  signal moves.
* **Idle** is a throttle floor (base + PI) plus closed-loop idle timing and a
  dashpot. **Boost** is open loop or closed loop on the N75 output. **VVT**
  closes on the cam pattern position. **Knock** runs per-cylinder windows with
  monitor or active retard.

## Boot and memory

HaniCore owns the whole flash image, including the boot region
([PLATFORM.md](PLATFORM.md#boot-region)). Startup runs no C runtime
initialisation: every variable is set in code. Time-critical code stays in
the 64 KiB near-code group; cold modules are compiled as far code and reach
near code through thunks. The build refuses an image whose near code, far
code, constants, RAM or static stack bound drops below its reserve.

## TunerStudio interface

The firmware speaks TunerStudio's framed serial protocol (CRC32 envelope)
over the K-line: one page, an output-channel block, loggers, and `!` commands
for actions (preset apply, grabs, throttle commissioning, bench tests).
Refused operations answer OK and publish their outcome in output channels,
because any error code ends a TunerStudio session. Details:
[TUNERSTUDIO.md](TUNERSTUDIO.md).

## References

rusEFI is the reference for standalone-ECU concepts and the TunerStudio
layout; HaniCore contains no rusEFI code ([LICENSING.md](LICENSING.md)).
Hardware facts come from the target ECU's schematic, its own firmware, Bosch
component datasheets and bench measurement.
