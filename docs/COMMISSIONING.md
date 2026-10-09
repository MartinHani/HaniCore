# Commissioning

From a flashed ECU to a first start. HaniCore is development firmware: check
[STATUS.md](STATUS.md) for what has been proven on hardware, keep the engine
stopped for every configuration step, and have a way to cut fuel and ignition
that does not depend on the ECU.

## Bench

| item | |
|---|---|
| the ECU on a breakout or harness | KL30 on 62, KL15 on 21, relay-switched supply on 3, grounds 1/2 |
| 12–14 V supply with switchable KL30 and KL15 | |
| KKL (FTDI) cable on cavity 43 | TunerStudio and boot mode |
| switchable BOOT strap | boot mode ([BUILDING.md](BUILDING.md#flashing)) |
| optional: logic analyser, throttle body, crank/cam signal source on 82/90, 86/87 | |

* Cavity 21 is KL15, a power input — never wire it as an output.
* Probe ignition outputs through a divider: they are current sources.
* Bench actuator tests (TunerStudio's bench-test dialog) run only with the
  engine stopped and no crank signal. They drive one channel, with clamped
  duty and duration and a finite count, release automatically, and say why
  when refused.
* A COM port that opens says nothing about what answers on it; identify the
  device first. After a failed boot-mode attempt, leave the ECU unpowered for
  about 95 s.

## 1. Connect

Install the plugin and open a project with the `.ini` generated for the
flashed image ([TUNERSTUDIO.md](TUNERSTUDIO.md#connecting)).

## 2. Base configuration

1. *Controller → Base Tunes*: choose a preset and press **APPLY ENGINE
   PRESET** with the engine stopped, or configure every field yourself.
2. Enter what no preset sets: injector flow and dead time, coil dwell, the
   pressure sensor's transfer function, VE and ignition tables. Until an
   injector flow is entered, no fuel is delivered.
3. **Burn** with the engine stopped. That is the restart point at which
   restart-required fields (cylinder count, displacement, routing) take
   effect.

## 3. Sensors

With the key on and the engine stopped, check the gauges: coolant and intake
temperature plausible (an invalid sensor reads −40 °C), pressure near ambient
(an invalid sensor reads 0 kPa), battery voltage, and both throttle and pedal
tracks moving together.

## 4. Electronic throttle

*Advanced → Electronic Throttle Body*, with `dbwEnable` off:

1. Pedal: *Grab* released and fully pressed.
2. **Commission** runs endpoint calibration, relay PID autotune and a verify.
   Any fault releases the bridge; nothing is written unless the whole
   procedure passes, and the status says which step failed. Endpoint
   calibration and autotune can also be run alone.
3. Optional: **Characterization** measures the break-away band; **Save**
   writes the bias curve to RAM.
4. Review gains and limits, including **Sensor fault confirm time**
   (`dbwFaultDebounceMs`, default 50 ms). A bad pedal or throttle sample
   releases the bridge at once whatever this is set to; the confirm time is
   how long the fault must last before it latches the throttle off until
   key-off (engine protection then cuts fuel above 1500 rpm). 0 latches on
   the first bad sample. Enable `dbwEnable`, Burn.

## 5. Trigger and cam

* Wheel: teeth, missing teeth, edge, gap ratio.
* `trigAngleX10`: the angle of the first tooth after the gap, in degrees
  after cylinder-1 TDC. For the AWT, −78.0. Confirm it with a timing light in
  fixed-timing mode (`timingModeCfg`, `fixedTimingX10`) before any other
  timing work.
* Cam: `syncMode`, `camPhaseMode` (level or pattern) and their angles.
  Sequential strategies run their crank-only fallback until the cycle is
  confirmed.

## 6. First start

1. Start the vehicle logger (TunerStudio closed; the tool owns the K-line):

   ```powershell
   py tools\vehicle\me711_vehicle_test.py --port COM3 --full
   py tools\vehicle\me711_log_analyze.py <session folder>
   ```

2. Key on: the pump primes; no unexplained fault lamps.
3. Crank: crank sync within a revolution or two, plausible rpm.
4. If it does not fire, check spark timing with the timing light, the fuel
   pulse width in the log, `trigAngleX10` and the cam level before changing
   fuel.
5. Burn only with the engine stopped.

Lambda is display and log only until the wideband is qualified on the engine.
Closed-loop trim acts only on a lambda the firmware reports as valid.
