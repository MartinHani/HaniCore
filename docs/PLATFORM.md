# Platform: Bosch ME7.1.1

## Supported ECU

| item | value |
|---|---|
| ECU | Porsche Bosch ME7.1.1, Bosch hardware `0261207696` |
| OEM software | Porsche `022906032BT`, Bosch `1037371766` |
| CPU | C167CR-class (ST10-class core) at 40 MHz |
| flash | AMD AM29F800BB, 1 MiB, bottom-boot sectors |
| RAM | 2 KiB IRAM + 2 KiB XRAM on chip; 32 KiB battery-backed SRAM |
| connector | one 121-cavity Bosch connector |

Other ME7.1.1 hardware numbers and other ME7 variants are not supported. A
board with a different part number may differ in cavities, stages and ASIC
configuration. The connector, cavity by cavity: [PINOUT.md](PINOUT.md).

Sources, in order of strength: measurement on this ECU; the ECU's own OEM
firmware; the same-generation ME7.1.1 schematic (Audi W12, not this exact
board); Bosch component datasheets (CJ120, CJ220, CK110, CJ911).

## Hardware blocks

```
        KL30 62 ─┐   KL15 21 ─┐
                 ▼            ▼
           ┌──────────── CJ910 ─────────────────┐
           │ supplies · KL15 input · main-relay │── 23 main-relay coil (low side)
 82/90 ───►│ stage · crank VR conditioner ·     │
 43 ◄─────►│ K-line transceiver                 │
           └────────┬───────────────────────────┘
           ┌────────▼───────────────────────────┐
           │ C167, 40 MHz · flash · SRAM        │◄── cams 86/87, TPS 92/84,
           │ CAPCOM · PWM · ADC · SSC · ASC0     │    pedal 35/34, pressure 101
           └─┬───────┬────────┬────────┬────────┘
             │       │        │        │ SSC
        ┌────▼───┐ ┌─▼────┐ ┌─▼────┐ ┌─▼───────────────────────────┐
        │ CJ920  │ │CK110 │ │CJ220 │ │ S5500 peripheral ASIC        │
        │ low    │ │ignit-│ │H-    │ │ 16-word ADC window (CLT, IAT,│
        │ sides  │ │ion   │ │bridge│ │ baro …), port images (heaters,│
        └────────┘ └──────┘ └──────┘ │ N75, MIL), switch inputs,    │
                                      │ runtime supervision          │
                                      └──────────────────────────────┘
        2 × CJ120 wideband controllers on the same SSC; knock front end on
        P8.0/CC16 with the integrator on AN15
```

| part | role | notes |
|---|---|---|
| CJ910 | supplies, KL15 input, main-relay stage, crank conditioner, K-line | the main relay closes with KL15 in hardware; the CPU holds it after key-off through `NLEN_FR` (P3.12) |
| S5500 | ADC window, output port images, switch inputs, supervision | exchanged every 10 ms over SSC/PEC; it resets the CPU if the exchange stops. No exchange, no outputs |
| CJ920 | low-side drivers | injectors, fuel-pump relay (65), PWM loads on 115/120 |
| CK110 | ignition outputs | ~5 V current-source drive during dwell, spark on the falling edge: coils with integrated igniters only |
| CJ220 | throttle H-bridge | IN1 PWM (P7.2), IN2 direction (P7.7), enable P2.11 (active low), status flag P3.15 |
| CJ120 ×2 | LSU 4.2 interface | pump-current resistor 61.9 Ω, Ri reference 82.5 Ω |
| BUK138-50 ×2 | LSU heater low sides (cavities 5 and 4) | gates on ASIC port bits, active high |

## Inputs and outputs

| function | cavities | hardware |
|---|---|---|
| injectors 1–8 | 96, 97, 88, 89, 112, 113, 24, 19 | CJ920 low sides, active low at the CPU |
| ignition 1–8 | 102, 103, 94, 95, 110, 111, 8, 7 | CK110 current sources |
| crank | 82 / 90 | inductive, differential, through the CJ910 conditioner to CC15 |
| cams | 86, 87 | open collector with 2.61 kΩ pull-up, CC8 / CC9 |
| throttle motor | 117 / 118 | CJ220 bridge |
| throttle position, pedal | 92 / 84, 35 / 34 | main-CPU ADC |
| pressure | 101 | main-CPU ADC |
| coolant, intake air | 93, 26 | S5500 ADC; cavity 93 has a switched pull-up the board holds on |
| wideband bank 1 / 2 | 70, 51, 71, 52 + heater 5 / 13, 12, 14, 15 + heater 4 | on-board CJ120 |
| fuel-pump relay | 65 | CJ920, active low |
| main relay | 23 | CJ910 hardware stage |
| N75 boost valve | 104 | S5500 port image, 10 ms frame resolution |
| VVT / PWM loads | 115, 120 | CPU PWM through CJ920 with freewheel diode |
| check-engine lamp | 47 | S5500 port image |
| switch inputs | 38, 39, 40, 55, 56, 57, 75, 76 (via S5500); 86, 87 (CPU, when no cam uses them) | |
| K-line | 43 | TunerStudio and boot mode |

Hard limits:

* Ignition outputs drive coils with integrated igniters only.
* Injector stages are plain low-side switches (high-impedance injectors).
* Outputs owned by the S5500 (heaters, N75, MIL) switch at the 10 ms frame
  rate.
* Cavity 85 cannot read an NTC (brake-booster pressure input).
* CAN (58–60, 77–79) has no driver. There is no tacho output path and no oil
  pressure input.
* Stage polarity is a board fact in `hctarget.h`, never a page field.

## Flash layout

| file offset | sectors | content |
|---|---|---|
| `0x000000–0x01FFFF` | SA0–SA4 | boot region (below) |
| `0x020000–0x0201FF` | SA5 | interrupt vector table |
| `0x020200–0x02FFFF` | SA5 | reserved for a resident update loader |
| `0x030000–0x05FFFF` | SA6–SA8 | firmware: near code, far code, constants |
| `0x060000–0x0FFFFF` | SA9–SA18 | calibration store, eighty 8 KiB append-only cells |

A full-image flash blanks the calibration store: extract the calibration
first ([BUILDING.md](BUILDING.md#flashing)).

## Boot region

The image contains no OEM code. `tools/build/me711_owned_boot.py` generates
the first 128 KiB:

| file offset | content |
|---|---|
| `0x000000–0x0001FF` | vector table: slot 0 → reset prologue, slots 1–127 → `JMPS 82:N*4` (the HaniCore interrupt table) |
| `0x000200` | reset prologue (~100 bytes): reset cause to T0, register bank, clock and reset configuration, XRAM/IRAM cleared, jump to the startup |
| `0x008000–0x00803F` | ROMSYS header: entry pointer, checksum ranges, startup and program-page sums |
| `0x00FFFE`, `0x010000`, `0x01FFFE` | sector format markers `0x3CC3`, `0x5A5A`, `0x3CC3` |
| `0x01E572` | parameter-page checksum record |
| everything else | `0xFF` |

Depending on `SYSCON.ROMEN` at reset, the C167 starts either from an internal
mask ROM, which checks the ROMSYS header and sums and then jumps through the
entry pointer, or from the flash reset vector. The region is built for both.
What the reset path needs was established by executing the OEM boot code in
the simulator and removing bytes until the hand-off failed. Besides the header
and checksums, only the three marker words are required.

Status: **bench-proven** (flash with full readback, cold boots after 95 s
without power, calibration Burn and restore from flash). Which reset path
runs on this ECU is not determined. A non-booting image is recovered through
the C167 bootstrap loader, which does not depend on the flash contents.

## Fitting the ECU to a VW/Audi 1.8T (AWT) harness

The AWT harness connector fits the ME7.1.1, and most signals land on the
right cavity. The power and relay wiring does not.

**Do not plug the ECU into an unmodified AWT harness.** Move these terminals
in the harness connector (or use an adapter that does the same):

| signal | AWT cavity | ME7.1.1 cavity |
|---|---|---|
| KL15 (ignition) | 3 | **21** |
| relay-switched supply (relay terminal 87) | 121 | **3** |
| main-relay coil drive (relay terminal 85) | 21 | **23** |
| intake air temperature (G42) | 85 | **26** |

Before moving the relay drive to 23, check whether the AWT harness has a wire
in its cavity 23 and identify it. Cavity 21 is a power input; removing +12 V
from it takes the ECU offline.

Already correct: crank 82/90, cam 86, throttle body 117/118 and 92/84, pedal
35/34, charge-pressure sensor 101 (it measures before the throttle), coolant
93, wideband bank 1, injectors 96/89/97/88 and coils 102/95/103/94 for
cylinders 1–4, fuel pump 65, N75 104, N205 115, MIL 47, K-line 43.

Check before first power-up: KL30 on 62, grounds on 1/2, +12 V on cavity 21
with the key on, relay coil from 23 to +12 V.

## Boot mode

The C167 enters its bootstrap loader when the BOOT strap (flash-chip pin 24
to ground on this board) is held while the ECU powers up. The loader talks
over the K-line at 124800 baud. Procedure: [BUILDING.md](BUILDING.md#flashing).
