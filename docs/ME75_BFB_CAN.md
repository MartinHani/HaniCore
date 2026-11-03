# ME7.5 BFB (8E0909518AQ): what the stock read does on CAN

Source: `audi-a4-b7-1.8t-bfb-163hp.ori.bin`, disassembled with Ghidra + the C166
module. First pass only; nothing here has been seen on a bus.

## Hardware
* The C167CR's on-chip CAN module (registers 0xEF00-0xEFFF). Stock code touches 36
  of its registers; the driver is at file 0x43300-0x45EB0.
* Pins: DP4 = 0xCF (measured) leaves P4.5 an input and P4.6 an output, the C167's
  CAN1 RxD/TxD on port 4 - consistent with an external CAN transceiver.

## Init (0x43300)
* Control reg 0xEF00 = 0x41 (INIT|CCE) while configuring, 0x00 afterwards.
* Bit timing: 0xEF04 = 0x01 (BRP = 1, SJW = 0), 0xEF05 = 0x49 (TSEG1 = 9,
  TSEG2 = 4) -> 16 time quanta per bit, sample point 69 %.
  **The bit rate is NOT derived yet**: it depends on the CAN module clock; check
  with a CAN analyser before connecting (VAG powertrain CAN is normally
  500 kbit/s).
* Global mask 0xEF06/07 = 0xFFE0 (11-bit IDs compared in full); all 15 message
  objects (0xEF10..0xEFF0, 16 bytes each) are first set to 0x55 (invalid).
* Object setup routine at 0x433B0: r12 object, r13 11-bit ID, r14 1 = transmit,
  r15 data length.

## Messages the stock code sets up (28 call sites)
Transmit (ECU -> bus):

| ID | obj | DLC | note |
|---|---|---|---|
| 0x280 | 0 | 8 | VAG Motor_1 (rpm, pedal, torque) |
| 0x288 | 0 | 8 | VAG Motor_2 |
| 0x380 | 2 | 8 | VAG Motor_3 |
| 0x480 | 3 | 8 | VAG Motor_5 |
| 0x488 | 4 | 8 | VAG Motor_6 |
| 0x580 | 3 | 8 | VAG Motor_7 |
| 0x588 | 3 | 3 | |
| 0x38A | 12 | 4 | also set up as receive |
| 0x201 / 0x7A1 / 0x010 | 13 | 3 / 6 / 6 | diagnosis / transport-protocol channel |

Receive (bus -> ECU): 0x440, 0x1A0, 0x540, 0x420 (also 0x520), 0x320, 0x5E0,
0x050, 0x0C2, 0x38A (gearbox, brake/ESP, cluster, climate, airbag-class
messages). The names are the usual VAG powertrain-CAN assignments, **not read
from this ECU**; the signal layout of every byte is still to be extracted from
the code that fills each object's data bytes.

## What rebuilding it in HaniCore needs
1. A CAN driver for the C167CR module (init, 15 objects, TX/RX interrupt) in the
   HAL, under the same 10 ms frame budget as the ASIC exchange.
2. The transmit signals: rpm, pedal, coolant temp, throttle, torque, MIL - the
   cluster only needs the 0x280/0x288/0x380/0x480/0x488 family.
3. The bit rate, verified on a bus, and the byte layout of each message from
   the stock code (or a real bus log of this car).
4. Receive handling: at first only to ignore everything; later brake/clutch
   state from the ESP/gearbox messages if a feature needs it.
Not started: no HaniCore code was changed for CAN.
