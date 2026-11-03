# ME7.5 BFB (8E0909518AQ / 0261208524): bench bring-up record

Written 2026-11-03 after the first bring-up on a bench ECU (Audi A4 B7 1.8T BFB).
Companion files: `ME75_BFB_EVIDENCE.md` (what the stock read proves),
`ME75_BFB_CAN.md` (stock CAN notes). This file is the chronological record:
what was found, how, what was changed, what is and is not proven.

## 1. State in one paragraph

A HaniCore BFB image boots on the real ECU, holds the hardware supervisor's
handshake (no reset loop), and is tuned with LibreTune over the K-line (cavity
43, COM3, 57600 baud). The K-line firmware update works. **Nothing that runs an
engine has been tested on this ECU**: no crank signal, no injector or spark
output, no throttle, no CAN. The pin map is still the 18T's and is unverified on
the B7 loom. Do not put it in a car on the strength of this record.

## 2. What differs from the 18T (the reason it did not work at first)

| | 18T (4B0906018DC, `18t`) | BFB (0261208524, `bfb`) | evidence |
|---|---|---|---|
| CPU clock | 24 MHz | **32 MHz** | stock S0BG 0x5F beside S0CON 0x80D1 (0x0237FA, 0x0240AC, 0x0397C8): 10400 x 32 x 96 = 31.95 MHz; an image with 0x47 sent at 13889 baud |
| T0/T1/T7/T8 | fCPU/32 = 0.75 MHz | fCPU/32 = **1.000 MHz** | stock T01CON 0x424A, T78CON 0x474A (0x0AD440 / 0x0AD448) |
| BUSCON1 (ext. SRAM) | 0x040D | **0x051C** | stock, both startup stages (0x0DC0E, 0x0AD0D2) |
| BUSCON2 (CC650) | 0x064E | **0x064D** | stock (0x0DC16, 0x0AD0DA) |
| ROMSYS variant (0x8004) | 0x5BDC | 0x5C02 | stock |
| Internal 32 KB ROM | n/a | **not the repo's `CPU.BIN`** (31 348 of 32 768 bytes differ); equals the first 32 KB of the stock read | read through boot mode, `ME7BootTool -readInt 0x8000` |
| Supervisor (68HC05) protocol | 05.12 tables, 1.5 MHz ticks | the same protocol and answers, in microseconds | section 4 |
| Pin map | verified on the 18T | **the 18T's, unverified on the B7 loom** | `ME75_BFB_EVIDENCE.md` |
| CAN | none | none (the B7 cluster/ESP expect it) | `ME75_BFB_CAN.md` |

## 3. Bring-up chain (symptom -> cause), in the order it was found

1. **LibreTune could not connect.** The probe (`tools/bench/ts_serial_probe.py`)
   saw only the KKL cable's own echo at every baud; the KWP wake-up failed at
   stage 1. The cable and COM3 were fine.
2. **The flash held the 18T image, not the BFB image.** A boot-mode readback
   showed variant 0x5BDC and 18T code. The BFB image was then written and
   verified by SHA-256.
3. **Still silent after the BFB image.** Boot mode was ruled out (sending 0x00
   at 57600 gets no ident byte), wiring was checked (see section 6), and the
   internal ROM was read out. The boot proof against the real ROM passes, so the
   ROM hand-off was not the problem.
4. **Bus timing.** The stock BUSCON1/BUSCON2 differ from the 18T's. Matched in
   both the loader (`hcloader.a66`) and the app startup (`start_me711.a66`).
5. **Breadcrumb build.** A diagnostic image put one letter on the K-line per
   startup stage (loader entry A, header OK H, app startup C, after EINIT E).
   It repeated `A H C E` about 17 times a second: both stages ran, then the CPU
   was reset. The letters decoded cleanly only at ~13.9 kbaud, not 10.4 k:
   **fCPU is 32 MHz**.
6. **Reset cause.** The reset flags (`T0` = WDTCON saved by the ROM) read
   0x001C (hardware-reset flags, watchdog flag clear; first boot 0x003C): an
   external reset from the supervisor, not the CPU's watchdog.
7. **32 MHz conversion** (section 5). After it the ECU stopped resetting. Which
   single change did it was not isolated (baud, bus timing, tick domain and
   monitor clock went in together).
8. **Link up.** `S` returns `HaniCore ME75BFB 3EF8E9EA` with a valid CRC, the
   output-channel request returns a valid frame, no unsolicited bytes in 8 s.
9. **Diagnostics removed**, clean image built and updated over the K-line.

Dead ends worth remembering: driving FPW (P3.5) high did **not** stop the
resets (the 18T note "HIGH stops the module" does not carry over); and a search
for the 05.12 monitor tables in the stock read finds nothing because the BFB
stores them as inline immediates in microseconds, not as a table.

## 4. The supervisor protocol on the BFB

The stock code (live copy `0x8A:6D5C`, answer function `0x8A:6E88`; a second,
uncalled copy sits at `0x89:F69C`) uses the 18T's exchange: the supervisor's
LOW pulse (window 0x1048-0x25C0 us) is banded into 16 bands with the 15 edges
0x1143, 0x1245, 0x1355, 0x1470, 0x1595, 0x16C8, 0x1805, 0x1950, 0x1AA8, 0x1C0D,
0x1D83, 0x1F08, 0x209D, 0x2240, 0x23F8, and answered with a LOW pulse of a fixed
width. Answers by band 0..15 (us): 0x1FD6, 0x13E2, 0x19FA, 0x1504, 0x231E,
0x2170, 0x24D6, 0x1B58, 0x12CA, 0x10C2, 0x18A6, 0x1CCA, 0x1630, 0x1E46, 0x1766,
0x11C6; no valid band: 0x0FD2. These equal the 18T's 05.12 table / 1.5
(e.g. 0x1C36 -> 4812 us vs 0x12CA = 4810 us). The stock first answer (band 8
row, 0x12CA) matches HaniCore's ASync1.

The stock additionally checks a program-flow token (AA26 / AA28 / AA1A, summed
at ~21 checkpoints in the main program) before it selects a row. A healthy ECU
always satisfies it; HaniCore answers with the row of the question's band, as on
the 18T. In the simulator the BFB image answers with widths 4814 / 5685 / 4054
us and a 40 ms slot spacing, first answer ~58.5 ms after the timers start.

## 5. What was changed (this bring-up)

Firmware
* `hctarget.h` (BFB block at the end): `TGT_FCPU_HZ` 32 MHz; `TGT_S0BG` 0x10
  (57600), `_ALT` 0x07 (124800), `_10400` 0x5F, `_250000` 0x03; `TGT_ASIC_SSCBR`
  0x0F; tick domain `TICKS_PER_MS_X10` 10000, `TICK_RELOAD` 1000,
  `HC_PLAN_HORIZON_TICKS` 4000, `HC_PLAN_PERIOD_TICKS` 1933,
  `TGT_PLAN_DECIM_DT` 333 / `_DECIM4_DT` 200, `TGT_ASIC_CS_ARM_TICKS` 63,
  `TGT_DBW_PWM_PERIOD` 16000.
* `start_me711.a66`, `hcloader.a66`: BFB BUSCON1 0x051C, BUSCON2 0x064D
  (`$IF (BOARD_BFB)`).
* `hcasicstart_dc.inc`: the monitor core works in 1.5 MHz ticks; on the BFB
  they are derived from T1 (1.000 MHz) by an exact running accumulator
  (`mon_clock`, "THE MONITOR'S CLOCK"), not a shift. 18T path unchanged.
* Engine tick-conversion branches for 1.000 MHz (`TICKS_PER_MS_X10 == 10000`):
  `hcdeadline_plan711.c` (us->ticks, injector request, prime pulse),
  `hcengctl711.c`, `hcroutes711.c` (tach), `hcnvm.c` (live-burn horizon).
  Sites that derive from `TGT_TICKS_PER_MS_X10` need no change.

Tools and tests
* `tools/build/build_hanicore_me711.py`: its private copy of `board_text` did
  not know the `#if TGT_BOARD_VAG_ME75_BFB` block, so **every other board's
  manifest got the BFB's signature and version text** (the image bytes were
  correct). Fixed; verified only on the BFB.
* `tools/tuning/gen_ts_ini_me711.py`: the tick length in the `.ini` (telemetry
  note and the tooth-log time scale) was `1.333 us if IS_C4`, wrong for the BFB.
  Now from the header (BFB 1 us). **A BFB log taken with an older `.ini` has a
  time axis 33 % too long.**
* `tools/lib/hc_board.py`: `fcpu_hz()`, `define_int()`, `s0bg_rates()`.
  `uart_wire_model.py` and the tests below use them instead of per-board
  literals.
* `tools/flash/me7boot/hanicore_me7boot.py`: `diffWrite --assume-current FILE`
  (skip the pre-read) and `--verify-size N` (verify a prefix).
* New gate `tests/firmware/build/me75_bfb_clock_proof.py` (12 checks: header,
  stock read, image). It fails on a 24 MHz image (control).
* `me75_bfb_boot_proof.py` defaults to this ECU's own ROM
  (`bins/oem/ME75_BFB_IROM.bin`, git-ignored like `CPU.BIN`).
* Tests that hard-coded a 24/40 MHz number and were wrong for the BFB:
  `me711_vvt_proof`, `me711_idle_valve_proof` (PWM counts per second),
  `me711_deadline_proof` (planner horizon; also its overlap check ran too long
  before publishing an absolute time), `me711_edge_contract_proof` (ticks to
  us), `me711_kwp_entry_proof`, `me711_link_rate_proof` (S0BG tables),
  `me711_burn_ir_preserve_proof` (fCPU), `me711_dbw_control_proof` (call step
  cap 400 000 -> 2 000 000; a us wait costs more instructions at 32 MHz).

## 6. Bench setup

* Pin 1 GND; pins 62, 3 and 121 +12 V; **pin 21 not connected** (on the 1.8T
  harness pin 21 is the ECU's main-relay drive *output*; +12 V on it shorts the
  supply to ground through the driver when the ECU switches it); pin 43 K-line
  to a KKL cable. No relay is needed.
* LibreTune: K-line (KKL), COM3, 57600; import the build's `.ini`. **LibreTune
  holds COM3: disconnect it before running any script on the port.**
* A small LED check of an injector output is possible: anode -> 1-2.2 kohm ->
  +12 V, cathode -> the injector cavity (low-side driver). Not for the coil
  outputs. The cavity numbers are the unverified part, which is what the test
  confirms.

## 7. How to flash and update

* **K-line updater** (ECU already runs HaniCore; no boot mode):
  `py tools\flash\hc_update.py --image HaniCore_BFB_8E0909518AQ_<build>.bin --port COM3`
  Use `--dry-run` first (identifies the ECU and saves the page). About 2 min.
  *It can crash in its wait-for-reboot step after a successful transfer
  (`IndexError`, `hc_update.py` `request`); check the result with `--dry-run`.*
* **Boot mode** (blank or broken ECU): `hanicore_me7boot.py --port COM3 --baud 57600
  diffWrite <image> --assume-current <file of what the ECU holds>` is about 70 s.
  115200 fails the bootloader handshake on this cable and leaves the C167 needing
  a fresh power-cycle into boot mode. The wrapper needs the upstream C167BootTool
  (`tools\flash\me7boot\install.ps1`).
* Breadcrumb technique (removed from the tree): `$IF (HC_CRUMBS)` blocks in the
  loader and startup that init ASC0 and send one byte per stage; listen at
  10400 baud and also at 13889 if the clock is wrong.

## 8. Test status (BFB, `HANICORE_BOARD=vag_me75_bfb`, fast tier)

Pass: the boot proof (9/9), the clock proof (12/12), deadline planner (89/89),
idle valve, VVT, ETB bias, KWP entry, link rate, identity, and the remaining
gates of the fast tier. Failing, none caused by the clock:
* `me711_preset_apply_proof` 23/52: **also fails on the DC board**.
* `me711_edge_contract_proof` 17/18: the "eight coil and injector channels"
  check expects 8+8 lanes; the BFB (and DC) drive 4+4. Fails identically on the DC.
* `test_hw_descriptor_evidence`: needs the `xlrd` module.
* `me711_burn_ir_preserve_proof` refuses to run without a local negative-control
  file.
The DC and Porsche builds were **not** rebuilt or re-verified after the shared
tooling fixes.

## 9. Known issues

* **A preset-applied tune is dropped on a firmware update.** The new firmware
  refuses to restore the old page (`cfgValidation 0x0800`, "output count does
  not match the cylinder count") and falls back to defaults; the updater then
  does not burn it. Seen after both updates on this ECU (46 bytes the second
  time). Cause not traced; likely the same fault as the failing preset gate.
  The pre-update page is saved by the updater (`<out>\page_before.bin`).
* This ECU's original flash was overwritten before it was ever read; only a
  stock BFB read from another car exists.
* `hc_update.py` crash described in section 7.

## 10. Before a car

None of this is proven; at minimum:
1. Verify each injector (LED/noid) and coil output against the B7 loom; verify
   the fuel pump relay output and the throttle drive.
2. Run a crank/cam simulator: sync, first injector and spark events, timing.
3. Replace the 18T preset's ignition/VE/boost tables with a BFB tune; check the
   dead-time curve (`TVUB`, "probable") and set up knock.
4. Decide about CAN (cluster, ESP, start authorization).
5. Keep the original ECU available to swap back.

## 11. Where the working files are (not in the repo)

`C:\Users\Amenofisch\HaniCore-work\hc_build` is a Windows copy of the tree used for the Keil builds:
`bins\release\` (images and `.ini`), `rb\` (readbacks, the ROM dump
`introm.bin`, update logs `upd_real`, `upd2_real`, `upd2_check`, and the ECU's
current image `current.bin`), `tools\flash\me7boot\C167BootTool` (downloaded
upstream tool). `C:\Users\Amenofisch\HaniCore-work\hc_ghidra` holds the Ghidra project and listings of the
stock read.
