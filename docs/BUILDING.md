# Building and flashing

## Requirements

| tool | version | used for |
|---|---|---|
| Keil C166 (C166, A166, L166, OH166) | V7.53 | the firmware; `HANICORE_KEIL_C166`, default `C:\Keil\C166` |
| Python with the `py` launcher | 3.11 or newer | build, generators, tests, tools |
| Python packages | `requirements.txt` | `pyserial`, `pytest` |
| host C compiler (optional) | gcc (MSYS2) or clang | host tests of the portable C; they skip without one |
| JDK (optional) | 8 or newer, plus TunerStudio 3.3.01 | rebuilding the TunerStudio plugin |

The firmware build is Windows-only because of Keil. The Python tools are
tested on Windows.

```powershell
git clone https://github.com/MartinHani/HaniCore.git
cd HaniCore
py -m pip install -r requirements.txt
py tools\build\build_hanicore_me711.py
py tools\tunerstudio\gen_ts_ini_me711.py
```

## Build pipeline

```
tools/config_source/*.py ──generate_config.py──► firmware/generated/*
  (page model, presets,                            (layout, pin descriptor,
   hardware descriptor)            │                presets)
                                   └─gen_ts_ini_me711.py──► tunerstudio/*.ini
firmware/** ──build_hanicore_me711.py──► bins/hanicore/<stem>.bin .hex .json
```

* **Configuration model.** The page layout, presets and hardware descriptor
  are edited in `tools/config_source/`, never in `firmware/generated/`. Run
  `py tools\config_source\generate_config.py` after a change; the build
  refuses stale generated sources.
* **Image.** `build_hanicore_me711.py` compiles and links with Keil, refuses
  any unexpected linker warning, generates the boot region and checksums,
  places the interrupt table, leaves the calibration store blank and writes
  the image with a manifest (hashes of the image, map and sources). It
  refuses an image that falls below any code, constant, RAM or stack reserve.
  The image name (stem) is set in `tools/lib/me711_image.py`.
* **TunerStudio file.** `gen_ts_ini_me711.py` writes `tunerstudio/*.ini`
  for the image. Its signature carries the page layout id; rebuild the `.ini`
  whenever the layout changes.
* **Pinout.** `py tools\maintenance\gen_descriptor_doc.py` regenerates
  [PINOUT.md](PINOUT.md) from the hardware descriptor.

The build is reproducible: the same sources give the same image bytes.

## Flashing

Flashing uses the C167's bootstrap loader over the K-line. You need a KKL
(FTDI) cable on cavity 43, ECU power (KL30 on 62, KL15 on 21, grounds 1/2)
and a way to hold the BOOT strap (flash-chip pin 24 to ground) while the ECU
powers up.

Install the loader wrapper once. It downloads the upstream C167BootTool
(GPL-3.0) beside it; the tool is not part of this repository.

```powershell
powershell -ExecutionPolicy Bypass -File tools\flash\me7boot\install.ps1
```

Boot mode: all power off; apply KL30, KL15 and BOOT together; release BOOT
after about 4 s and keep power on. After a failed attempt, leave the ECU
unpowered for about 95 s before retrying.

```powershell
py tools\flash\me7boot\hanicore_me7boot.py ports
py tools\flash\me7boot\hanicore_me7boot.py --port COM3 read pre_flash.bin
py tools\flash\me7boot\hanicore_me7boot.py --port COM3 write bins\hanicore\<stem>.bin --verify --verify-dump post_flash.bin
```

* **Read the ECU before every write** and keep the dump: it is your rollback
  image and holds the calibration that was in the ECU.
* **Prove a flash by a full readback** (`--verify-dump`), not by an exit code.
  A full `write` erases every sector and takes about 5 minutes.
* A full-image flash leaves the calibration store blank. Put a calibration
  back through the normal path (page writes, read-back, Burn): take the
  newest record out of the pre-flash dump and apply it, then Burn in
  TunerStudio.

  ```powershell
  py tools\calibration\me711_user_presets.py save "Before flash" --from-dump pre_flash.bin
  py tools\calibration\me711_user_presets.py apply "Before flash" --port COM3
  ```

  If the tool refuses because the page differs too much from the ECU's,
  APPLY the built-in preset the calibration was based on first. Never copy
  the store's flash range by hand.
* After a page-layout change the store must be blank, and an older
  calibration is carried across field by field with
  `tools/calibration/me711_migrate_calibration.py`.
* To prove a Burn reached flash, read back in boot mode: the battery-backed
  SRAM page survives minutes without power, so a power cycle proves nothing.
  The output channel `nvmSource` (low byte 2) reports a page restored from
  flash.
