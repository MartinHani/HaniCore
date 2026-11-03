# ME7.5 BFB (8E0909518AQ / 0261208524): what the stock read proves

Bench bring-up, what was changed and what is still unproven: `ME75_BFB_BRINGUP.md`.

Source: `audi-a4-b7-1.8t-bfb-163hp.ori.bin` (SW 1037372505), disassembled with
Ghidra + the C166 module. The first half of this file is from the stock read; the clock, bus and supervisor sections were confirmed on a running ECU (see their dates).

## Measured (stock startup code, file offsets 0x0DC02 and 0xAD0BC / 0xAD450)

| register | stock value | HaniCore 18T (DC) board |
|---|---|---|
| BUSCON0 / ADDRSEL1 | 0x04AE / 0x3803 | same |
| ADDRSEL2 / BUSCON2 | 0x4800 / **0x064D** (CC650 at 0x480000) | 0x4800 / 0x064E - **different** |
| BUSCON1 (external SRAM) | **0x051C** (both startup stages: 0x0DC0E, 0x0AD0D2) | 0x040D - **different** |
| CPU clock | **32 MHz** (S0BG 0x5F beside S0CON 0x80D1) | 24 MHz - **different** |
| DP2, P2 | 0x3CBF, 0xC7BF | DP2 0x3CBF quoted in hctarget.h |
| DP3, P3 | 0x35E0, 0x2FC1 | both quoted in start_me711.a66 / hctarget.h |
| DP4, DP6, DP7, DP8 | 0xCF, 0x7F, 0xFF, 0x81 | consistent with the 18T rows below |
| ROMSYS variant (0x8004) | **0x5C02** | 0x5BDC - **different** |

## The 18T descriptor's port resources against the BFB direction registers

All consistent (output = DP bit set; input = clear):
coils P2.0-3, heaters P2.4 / P2.12, ETR P2.7, tacho P2.13, EGENFR P2.11 (outputs);
crank P2.15, cam P2.8, CJ220 SF P2.9, KL15 P4.4 (inputs);
fuel pump P3.7, FPW P3.5, NLEN_FR P3.12 (outputs; P3.7 idles HIGH = off);
P7.0-7 (all outputs: POUT0/1, DVE1/2, TEV, injectors 1-3), injector 4 P8.7 (output).

## Mask-ROM check (simulated, against this ECU's own ROM)

The ECU's internal 32 KB ROM was read out through boot mode (`ME7BootTool
-readInt 0x8000`, 2026-11-02). It is **not** the `CPU.BIN` the first version of
this proof assumed (31 348 of 32 768 bytes differ); it is byte-identical to the
first 32 KB of the stock read.

`tests/firmware/build/me75_bfb_boot_proof.py <image> <stock> <that ROM>` runs it
from reset in c167sim. Results (9/9): the ECU's own stock read reaches its own
entry 0x8AD0B4; the HaniCore BFB image reaches its loader entry 0x820200; a
changed startup record, entry pointer or parameter-page marker is refused. On
hardware the handoff works (the loader runs: bench breadcrumbs).

## Analog channels (stock ADC scan, routines at 0x0F0AE, 0x3FE36, 0x432A2)

The stock code auto-scans AN15..AN0 into a 16-word RAM array at 0xF802 (index 0 =
AN15, index 15 = AN0) and copies each word into a named RAM cell. Cell names are
from the me7logger symbol dump; the AN14 -> charge pressure link was followed
through its consumer (0x6D4C4 writes pvdks_w / pvdkdsl_w / pvdkds).

| channel | stock destination | 18T descriptor row | result |
|---|---|---|---|
| AN0 | uhfm_w (MAF voltage) | G70 air mass AN0 | **match** |
| AN1 | udkp1_w (throttle pot 1) | J338 p1 AN1 | **match** |
| AN3 | udkp2_w (throttle pot 2) | J338 p4 AN3 | **match** |
| AN5 | wub (battery) | battery AN5 | **match** |
| AN6 | uulsuv_w (wideband UA) | CJ110 UA on AN6 | **match** |
| AN8 | upwg1_w (pedal 1) | G79 AN8 | **match** |
| AN9 | upwg2_w (pedal 2) | G185 AN9 | **match** |
| AN14 | pvdkds (charge pressure) | G31 AN14 | **match** |
| AN4 | uhsv (heater voltage) | not in the descriptor | info |
| AN10 | raw cell 0x8F60 -> one of two NTC curves (0x7C19C/0x7C1AE) -> tmotlin 0x3848BD | coolant AN10 | **match** |
| AN11, AN13 | copied to cells 0x8F42 / 0x88DB that no code reads | TMOT2 spare AN13 | **unused by the stock code** (the descriptor's "spare" claim holds) |
| intake air | read from CC650 register 0x1E (not the C167 ADC) -> cell 0x88DA -> curve -> tanslin 0x3848B1 | G42 via the ASIC (PXAN1) | **match** (0x3FEA6, 0x7B2E8) |

## Temperature curves (stock tables vs HaniCore's default for this board)

Coolant: stock 20-point table at file 0x27456 (10-bit counts -> 0.75 C/bit, -48 C
offset). With the board's 2.61 k pull-up and 38.3 k pull-down it reproduces a
standard 2.5 k @ 20 C NTC (2496 ohm at 20.2 C, 324 at 80.2 C, 187 at 99.8 C), i.e.
the same circuit the repo models for the C4/DC family (R_PU_CLT = R_PU_IAT).
HaniCore's default cltSens curve for this board matches the stock table to
**0.7 C max** (0.1 C typical).
Intake air: stock table at file 0x19BF0 (8-bit counts from the CC650). HaniCore's
default iatSens matches to 0.1 C from -30 to +100 C; it differs only at the
extremes (+3..+5 C near 110-130 C, 8 C at -48 C), outside any usable range.

## The clock is 32 MHz (bench finding, 2026-11-02)

A HaniCore BFB image built with the 18T's 24 MHz was silent on the K-line and
the ECU reset about nine times a second. A breadcrumb build (one letter per
startup stage on the K-line) showed the loader and the app startup running,
then a reset; the letters decoded cleanly only at ~13.9 kbaud instead of
10.4 k, i.e. fCPU = 24 MHz x 4/3 = 32 MHz.

The stock read agrees: it writes S0BG = 0x5F beside S0CON = 0x80D1 for its
10400 baud K-line (0x0237FA, 0x0240AC, 0x0397C8): 10400 x 32 x 96 = 31.95 MHz.
The timers are fCPU/32 (T01CON 0x424A, T78CON 0x474A at 0x0AD440 / 0x0AD448), so
T0/T1/T7/T8 run at **1.000 MHz** (the 18T: 0.75 MHz). The bus timing differs
as well (BUSCON1 0x051C, BUSCON2 0x064D, table at the top). The firmware's
BFB block in `hctarget.h` carries all of it; `me75_bfb_clock_proof.py` compares
the image against the stock read.

Status of the conversion: the clock, baud rates, SSC rate, tick domain
(TICKS_PER_MS_X10 10000, 1 ms reload 1000, planner and ASIC tick counts x 4/3),
the monitor clock and the tick-conversion sites in the engine code (deadline
planner, prime pulse, tach period, live-burn horizon) are done and build. Only
the supervisor exchange was run in the simulator (correct pulse widths and
slot spacing at 1 MHz). **None of the engine timing has run on this ECU.**

## The supervisor (68HC05) protocol is the 18T's

The stock code (live copy at 0x8A:6D5C, answer function 0x8A:6E88) runs the same
question/answer exchange as the 18T's: the question's LOW pulse is banded into
16 bands with 15 edges (0x1143 ... 0x23F8, window 0x1048-0x25C0) and answered
with a LOW pulse whose width is a fixed table value (band 0..15: 0x1FD6, 0x13E2,
0x19FA, 0x1504, 0x231E, 0x2170, 0x24D6, 0x1B58, 0x12CA, 0x10C2, 0x18A6, 0x1CCA,
0x1630, 0x1E46, 0x1766, 0x11C6; default 0x0FD2) - the 18T's 05.12 table in
microseconds instead of 1.5 MHz ticks (e.g. 0x1C36 / 1.5 = 4812 us vs 0x12CA =
4810 us). The stock additionally checks a program-flow token (AA26 / AA28 /
AA1A) before it picks a row; a healthy ECU always satisfies it, so HaniCore
answers with the row of the question's band, as on the 18T. HaniCore's monitor
core is reused unchanged; its glue converts T1's 1.000 MHz to the core's
1.5 MHz units (hcasicstart_dc.inc, "THE MONITOR'S CLOCK"). On the bench the
ECU stopped resetting once the 32 MHz conversion was in; which of the changes
(baud, bus timing, tick domain, monitor clock) mattered was not isolated.

## Base tune (preset "VAG 1.8T BFB (Audi A4 B7)", ident 10)

The existing 1.8T engine preset fits the BFB engine; checked against the BFB stock read:
KUMSRL raw 88 (same displacement 1781 cc), KFSZT dwell table identical, DLRPIDMAX 80 %,
TVPWDK12 0.14 s, DSLGRAD 541.0 hPa/V and DSLOFS -16.4 hPa (all identical). The injector
flow class (301 cc/min) holds: the car logs give te/rk = 0.100-0.106 ms/% against the
AWT's KRKTE 0.1049 (the XDF's KRKTE scale is wrong by ~40x and was not used).
Only the injector dead-time curve (TVUB) is the BFB's own: raw 527/329/229/167/124
at 7.96/10.0/11.97/14.01/15.98 V -> 1.405/0.877/0.611/0.445/0.331 ms with the /375
scale (PROBABLE; the XDF says 0.004 ms/bit, which would be 1.5x larger).
Ignition, VE, boost and idle tables are NOT from the stock tune: they stay the
AWT preset's (a car-run 1.8T tune), to be set up on the car.

## NOT proven

* which connector cavity each port bit reaches on the B7 loom (direction says a
  bit is driven, not where it goes): every pin is still the 18T's, unverified
* the dead-time unit (/375 vs the XDF's 0.004) - check short-term trim at idle;
  pedal/throttle/wideband scaling (only the channel -> variable links and the two temperature curves are proven)
* CAN: none; the B7 cluster/ESP expect it
