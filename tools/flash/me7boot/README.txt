HaniCore ME7 Bootmode CLI - Windows 11
======================================

Purpose
-------
Non-interactive wrapper for EcuProg7/C167BootTool / ME7BootTool.py.
Designed for explicit Windows COM-port use (COM3, COM4, ...), so it can be
called from scripts without the upstream tool asking which adapter to use.

ME7 external flash commands:
- read
- write
- diffWrite
- verify

IMPORTANT: write and diffWrite do NOT verify by default.
Add --verify when you explicitly want a full readback + SHA-256 compare.

Install
-------
1. Extract this folder.
2. Open PowerShell in the folder.
3. Run:

   powershell -ExecutionPolicy Bypass -File .\install.ps1

install.ps1 installs pyserial and downloads the upstream GPL-3.0 C167BootTool
into .\C167BootTool\. The upstream project on disk is left unchanged.

diffWrite creates a temporary patched copy of ME7BootTool.py only for that run,
then deletes the temporary copy afterward.

Commands
--------
List COM ports:

   py .\hanicore_me7boot.py ports

Read 1 MiB 29F800 flash from COM3 at 57600 baud:

   py .\hanicore_me7boot.py --port COM3 read porsche_backup.bin

FULL WRITE - no verify by default:

   py .\hanicore_me7boot.py --port COM3 write HaniCore.bin

FULL WRITE + verify:

   py .\hanicore_me7boot.py --port COM3 write HaniCore.bin --verify

DIFF WRITE - default development command, no verify:

   py .\hanicore_me7boot.py --port COM3 diffWrite HaniCore.bin

DIFF WRITE + verify:

   py .\hanicore_me7boot.py --port COM3 diffWrite HaniCore.bin --verify

HaniCore ME7.1.1: new code, calibration store (0x70000.., SA10..SA18) kept as
the ECU has it, pre-write read kept as the rollback:

   py .\hanicore_me7boot.py --port COM3 diffWrite HaniCore.bin --keep-from 0x70000 --pre-read-dump before.bin --verify-dump after.bin

Verify an already-flashed image without writing:

   py .\hanicore_me7boot.py --port COM3 verify HaniCore.bin

Keep verification readback:

   py .\hanicore_me7boot.py --port COM3 diffWrite HaniCore.bin --verify-dump HaniCore_readback.bin

Use another baud rate:

   py .\hanicore_me7boot.py --port COM3 --baud 28800 diffWrite HaniCore.bin

Machine-readable result:

   py .\hanicore_me7boot.py --json --port COM3 diffWrite HaniCore.bin

How diffWrite works
-------------------
1. Reads the current full ECU flash.
2. Compares it with the new full BIN in 0x200-byte blocks.
3. If identical: exits without erase/write.
4. If different: during the write operation, the upstream flash driver detects
   the actual 29F400/29F800 boot-block layout from the flash ID.
5. Erase is skipped for every sector containing no changed blocks.
6. A changed sector is erased and the complete new contents of that sector are
   programmed back. Unchanged sectors are not programmed.
7. No final verify is performed unless --verify (or --verify-dump) is specified.

This preserves unchanged data inside a sector after NOR erase; it does NOT try
to program arbitrary changed bytes without respecting erase-sector boundaries.

Safety behavior
---------------
- write accepts only full 29F400 (0x80000) or 29F800 (0x100000) images by default.
- write can use --allow-partial when intentionally needed.
- diffWrite requires a full 29F400 or 29F800 image because it compares and
  restores complete erase sectors safely.
- upstream interactive prompts are disabled; an unexpected prompt fails instead
  of hanging an automated job.
- verification is opt-in, not default.

Exit codes
----------
0   success
2   invalid arguments / unsafe image size
10  missing pyserial/upstream files or diff patch setup failure
20  upstream read/write failure
21  verification hash mismatch

Important
---------
The ECU must already be in C167 boot/BSL mode before read/write/diffWrite.
This CLI does not switch the ECU supply or the boot pin; enter bootmode first.

Upstream
--------
EcuProg7/C167BootTool, GPL-3.0:
https://github.com/EcuProg7/C167BootTool
