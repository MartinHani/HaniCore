# Status

HaniCore **1.0-dev**: development firmware, not road-ready. This page is the
one place that says what has been proven, and how.

| level | meaning |
|---|---|
| **VEHICLE** | worked on the test car (VW/Audi 1.8T AWT, drive-by-wire) |
| **BENCH** | measured on a real ECU on the bench |
| **SIMULATOR** | the linked firmware image executed in the instruction-level simulator |
| **HOST** | portable C compiled and tested on a PC |
| **IMPLEMENTED** | in the image, checked by build and static gates only |

"Not yet run on the car" never means "not implemented".

## Summary

Earlier development builds started and ran the AWT on HaniCore's own fuel and
spark: 60-2 crank sync, batch and sequential fuel, wasted-spark coil-on-plug,
up to about 2800 rpm, electronic throttle active in later sessions. Those
sessions exposed late spark and fuel events from the old polled executor, a
rich idle from a load-axis mismatch, and throttle and wideband commissioning
faults. The current tree fixes each of them; none of the fixes has been
confirmed on the car yet.

The current runtime — planner on its own interrupt level, compare-interrupt
edge executor, quiesce and supervisor logic — is proven in simulation only.
**Its crank, coil and injector timing has not yet been measured on
hardware.** The current image boots and runs on the bench ECU with the
HaniCore-owned boot region.

## Functions

### Platform

| function | level | notes |
|---|---|---|
| Boot from the HaniCore-owned boot region (no OEM code) | **BENCH** | cold boots, Burn, restore from flash; earlier vehicle runs used the OEM boot block |
| Boot-mode flashing over the K-line | **BENCH** | full readback after every write |
| TunerStudio over the K-line, 57600 / 115200 baud | **VEHICLE** | direct on cavity 43; the car's OBD K-line not yet proven |
| VAG/KWP 5-baud entry (plugin) | **BENCH** | |
| Calibration persistence (Burn, append-only store, sector reclaim) | **BENCH** | proven by boot-mode readback |
| S5500 link and runtime supervision | **VEHICLE** | precondition for every output |
| Main relay (hardware stage) and run-on | **BENCH** | |
| Fuel-pump relay | **BENCH** | polarity measured |
| User presets (save, list, apply, delete) | **BENCH** | save from the ECU, apply with read-back and validation, built-in names refused; the roll-back path is host-tested. See [TUNERSTUDIO.md](TUNERSTUDIO.md#presets) |

### Engine position and outputs

| function | level | notes |
|---|---|---|
| Crank: VR, missing-tooth wheel | **VEHICLE** | bench 150–6000 rpm |
| Crank: Hall | **SIMULATOR** | |
| Cam level / pattern phase | **SIMULATOR** (decoder), **VEHICLE** (signal) | the AWT cam level assignment is not measured |
| Batch / semi-sequential injection, wasted-spark COP | **VEHICLE** | |
| Sequential injection and sequential COP with fallback | **SIMULATOR** | |
| Compare-interrupt edge executor, planner, quiesce, supervisor | **SIMULATOR** | timing below |
| Injector outputs 1–8, ignition outputs 1–8 | **VEHICLE** (1–4) | no per-channel scope measurement yet |

### Control

| function | level | notes |
|---|---|---|
| Electronic throttle: control loop and commissioning | **BENCH** | bench body fully commissioned; car commissioning partial |
| Load: speed density, alpha-N × pressure, alpha-N | **VEHICLE** (alpha-N × pressure) | |
| Fuel model: VE, injector model, warm-up, after-start, wall film, DFCO, priming, cranking mass | **SIMULATOR** | partly exercised on the car |
| Ignition: tables, corrections, dwell, overdwell, rev limiter | **SIMULATOR** | spark timing used on the car |
| Closed-loop lambda (short-term trim) | **SIMULATOR** | needs a qualified wideband |
| Idle (throttle floor + PI, idle timing, dashpot) | **SIMULATOR** | |
| Boost control, overboost cut | **SIMULATOR** | |
| VVT | **SIMULATOR** | off in every preset |
| Knock (monitor / active) | **SIMULATOR** | off in every preset; needs calibration from a log |
| Launch, flat shift, anti-lag, pit limiter, rotational idle | **SIMULATOR** | off in every preset |
| Trouble codes | **SIMULATOR** | |
| Check-engine lamp | **IMPLEMENTED** | disabled until a real lamp has been seen to respond |

### Sensors

| function | level | notes |
|---|---|---|
| Coolant temperature | **VEHICLE** | |
| Intake air temperature | **BENCH** (read path) | the AWT wire must move to cavity 26 |
| Manifold / charge pressure | **VEHICLE** | |
| Throttle and pedal pairs | **VEHICLE** (pedal), **BENCH** (throttle) | acquisition owned by the 1 ms tick: sample age 2–15 ms on the bench |
| Battery voltage | **BENCH** | |
| Ambient pressure | **BENCH** (read path) | transfer function is an estimate |
| Wideband lambda, two banks | **BENCH** (controller, heater gates) | lambda with a fitted, heated sensor not qualified |
| Switch inputs | **BENCH** (positions) | per-cavity toggle test pending |
| MAF | **IMPLEMENTED** | read, not used by the fuel model |

## Runtime timing

The linked image in the simulator (10 MIPS, crank interrupt cost calibrated
to the car), 1000–9600 rpm, steady state, ramps and transients, with
TunerStudio's full request mix at 115200 baud:

| quantity | worst case | limit |
|---|---|---|
| executor edge lateness | 83 µs | 100 µs (later ON edges are refused) |
| interrupt-masked critical section | 46.8 µs | 50 µs |
| compare-interrupt execution | 136.5 µs | 160 µs |
| planner execution | 814.5 µs cold | 1200 µs |
| watchdog service gap | 16.0 ms (stress matrix), 18.0 ms (transient below) | 200.7 ms watchdog; gates use 10 % |
| throttle-control step gap | 18.7 ms | 20 ms |
| static stack bound | user 84 %, system 85 % | 85 % |

The steady-state and ramp matrix holds every budget, with no capture
overflow, no quiesce and no lost cycle. Transients with K-line traffic
(3500 → top → 2500 → top rpm, pedal steps) execute every published event at
a top speed of 7000 and 8500 rpm. **At 9600 rpm one run is not clean:** near
9400 rpm, at full acceleration with the injectors at their duty limit, a cold
planner run (up to 0.8 ms) outlasts the 7-tooth capture ring. The executor
quiesces as designed: 3 of 1049 injector openings are not executed, no edge
is late and no output is left on. The same run also exceeds the gate's
crank-interrupt fraction. 9600 rpm is headroom above the
AWT's ~6800 rpm; a deeper ring or a bounded planner pass would restore
margin there.

**Fixed: coil edges cleared the upper half of port 2.** The coil executor
wrote `P2 &= (unsigned int)~physical` with an 8-bit `physical`; the compiler
complements only the low byte, so every coil ON edge cleared the P2.8–P2.15
latches and every OFF edge cleared their direction bits — releasing the fuel
pump (P2.12) and the throttle-bridge enable (P2.11) at the first spark. The
bench pulse path had the same defect. It showed up in the K-line + transient
simulation because the simulator also let the write overwrite the cam input
P2.8: the cam level stopped alternating, the cycle was withdrawn for ~70 ms
and the wasted-spark fallback merged events. Both masks are now widened
before the complement; `me711_port_mask_proof` scans the image for any byte
complement that reaches a 16-bit AND, and the runtime gates require that the
simulated cam never loses the cycle. The car never ran this executor.

**Fixed: two diagnostics that always read wrong.** `cfgRouteMismatch`
reported every routed sensor as disagreeing with its configured pin, from
boot until the next configuration change (the check counted "no sample yet"
as a disagreement and ran before the inputs were bound); measured 0x00F0 on
the bench, 0 since the fix. The status word always carried the "bench-safe
build, no outputs" bit, so TunerStudio showed a permanent warning; it is now
set only by a build that really has no output back ends.

**A request sent during a Burn is dropped.** The flash writer masks the
serial receive interrupt during its programming windows, so a request that
arrives while a Burn is committing is lost: no reply, and the host times out
and retries. The session-fatal reply that once forced TunerStudio to
reconnect does not occur. Whether real TunerStudio, which keeps polling
during a Burn, recovers without a visible hiccup still needs a session on the
ECU.

**Main-loop pass length.** With the engine stopped, a main-loop pass takes
2.4 ms (median) and up to 9–10.7 ms when several services and the telemetry
publication coincide. The S5500 exchange is started from the main loop on a
10 ms raster, so its gap gates (target: 6.5 ms) are red. No ASIC reset has
been seen in any bench session; the long passes are the next optimisation
item.

## Limitations and open items

1. Bench logic-analyser measurement of crank, coil and injector timing, then
   the car.
2. Margin at the 9600 rpm ceiling and the main-loop pass length (above).
3. Vehicle runs of the current fuel/load model, wideband lifecycle and
   throttle commissioning.
4. AWT cam level assignment; per-channel output measurement.
5. Near-code reserve ~3 KiB, near RAM at its reserve, static system stack at
   its 85 % limit: new hot-path features need code moved out first.
6. No CAN, tacho output, oil-pressure input or firmware update without
   opening the ECU.
7. A request sent while a Burn commits gets no reply (above).
8. Changing the baud rate on a live link: the ECU's rate hunt can pass the
   host's rate once before it locks (simulation). Connecting at a fixed rate,
   as the plugin does, is unaffected.
9. Red gates: [TESTING.md](TESTING.md#current-results).
