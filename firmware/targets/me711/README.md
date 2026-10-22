# Target: Bosch ME7.1.1 (`0261207696`)

C167CR-class CPU at 40 MHz, AM29F800BB flash, S5500 peripheral ASIC. The
hardware is described in the maintainer's design notes.

```powershell
py tools\build\build_hanicore_me711.py
```

`build_me711.bat` only compiles and links (Keil, output in `build/`). The
Python builder is the one to run: it checks the generated sources, generates
the boot region and checksums, places the vector table and refuses an image
that fails any check (the maintainer's design notes).

| path | contents |
|---|---|
| `hctarget.h` | every board-specific number, each with its source |
| `build_me711.bat` | compile and link; one include path for every unit |
| `linker_me711.lnp` | flash layout and code classes, with the reason for every boundary |
| `system/` | startup (`start_me711.a66`), main loop, far-call thunks, safety permissions, power hold, page defaults, runtime health |
| `asic/` | S5500 startup handshake, runtime frame, supervision responder, ASIC-driven I/O |
| `hal/` | HAL implementation, acquisition freshness, routing tables, throttle motor primitive |
| `engine/` | trigger capture and decoding, planner and compare-interrupt executor, load model, engine-control layer, ignition corrections, knock |
| `control/` | throttle commissioning, idle, boost, VVT, limp |
| `diagnostics/` | trouble codes, event ring, telemetry and commands, bench actuator tests |
| `nvm/` | the append-only calibration store |
| `comms/` | K-line receive ring and serial transmit job, KWP entry |
| `generated/` | catch-all interrupt vectors (`tools/build/gen_vector_probe.py me711`) |

Portable code (`firmware/config`, `engine`, `control`, …) is compiled into the
image from where it lives and finds this board's `hctarget.h` through the
include path. File names are part of the linker contract.

Board facts every change must respect:

* The S5500 runtime supervision must be answered every 10 ms or it resets the
  CPU. Its code (`asic/`) is not changed without hardware evidence.
* Near code is one 64 KiB group. Interrupt handlers, trigger, planner,
  executor and the ASIC exchange stay near; cold code is far and uses 16-bit
  arithmetic only.
* K-line receive runs through a PEC ring, not the receive interrupt.
* Cavity 21 is KL15 (a power input); cavity 23 is the CJ910's hardware
  main-relay stage ([docs/PINOUT.md](../../../docs/PINOUT.md)).
