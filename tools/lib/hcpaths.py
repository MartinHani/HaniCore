#!/usr/bin/env python3
r"""
hcpaths.py - where things live in this repository. ONE place.

    py tools\lib\hcpaths.py      print the layout and check it

Tools resolve every path from here (or from their own location), never from
the current directory or a personal absolute path.

IMPORTING THIS MODULE MAKES EVERY TOOL AND TEST MODULE IMPORTABLE. Scripts
live in purpose directories (tools/build, tests/firmware/dbw, ...) and still
import each other by module name (`import me711_image`, `import c167sim`,
`import me711_config_state_test`). Every script therefore starts with

    sys.path.insert(0, str(<repo root> / "tools" / "lib"))
    import hcpaths

and this module appends each directory under tools/ and tests/ that holds a
Python module. Module names are unique across those directories - check()
proves it - so an import can never pick the wrong file.

The firmware is organised by subsystem (firmware/README.md):

    firmware/<subsystem>/      portable code, compiled into every target
    firmware/generated/        written by tools/config_source/generate_config.py
    firmware/targets/me711/    the Bosch ME7.1.1 target (hctarget.h at its root)

`include_dirs(target)` is the compiler's search path for a target, and
`find(name, target)` locates a source file by name in that search path. Header
names are UNIQUE across a target's search path - `check()` proves it - so a
bare `#include "x.h"` can never resolve to two different files, and the order
of the directories cannot matter.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = ROOT / "firmware"
PORTABLE = ("config", "engine", "control", "sensors", "diagnostics", "comms",
            "hal", "generated")
PORTABLE_DIRS = [FIRMWARE / d for d in PORTABLE]
GENERATED = FIRMWARE / "generated"

ME711 = FIRMWARE / "targets" / "me711"
ME711_SUBDIRS = ("system", "asic", "hal", "comms", "engine", "control",
                 "diagnostics", "nvm", "generated")
ME711_BUILD = ME711 / "build"          # Keil output: .obj .lst .M66 .abs .H86

# The Keil C166 toolchain. reg167.h is ITS header (the ME7.1.1 build includes
# the installed copy); tools that need SFR addresses read the same file.
KEIL = Path(os.environ.get("HANICORE_KEIL_C166", r"C:\Keil\C166"))
REG167 = KEIL / "INC" / "reg167.h"

BINS = ROOT / "bins"
IMAGES = BINS / "hanicore"             # built images + manifests (local)
# A read of the target ECU's own OEM flash (1 MiB). Never in Git; gates that
# compare against the OEM firmware skip without it. Override with
# HANICORE_OEM_READ.
OEM_READ = Path(os.environ.get("HANICORE_OEM_READ", str(BINS / "oem" / "oem_read.bin")))
TUNERSTUDIO = ROOT / "tunerstudio"          # generated .ini / .dash
CONFIG_SOURCE = ROOT / "tools" / "config_source"
# Raw bench / vehicle evidence: the workspace folder next to the repository
# (HaniCore\evidence), never inside it. Override with HANICORE_RAW_EVIDENCE.
RAW_EVIDENCE = Path(os.environ.get("HANICORE_RAW_EVIDENCE", str(ROOT.parent / "evidence")))

# Directories that hold importable tool/test modules (not data, not builds).
_SKIP = {"__pycache__", "plugin", "fixtures", "me7boot"}


def module_dirs() -> list[Path]:
    out = []
    for top in (ROOT / "tools", ROOT / "tests"):
        for d in sorted([top] + [p for p in top.rglob("*") if p.is_dir()]):
            if _SKIP & set(d.relative_to(ROOT).parts):
                continue
            if any(d.glob("*.py")):
                out.append(d)
    return out


for _d in module_dirs():
    if str(_d) not in sys.path:
        sys.path.append(str(_d))


def include_dirs(target: str = "me711") -> list[Path]:
    """The directories a unit of `target` may include from, target first."""
    if target == "me711":
        return [ME711] + [ME711 / d for d in ME711_SUBDIRS] + PORTABLE_DIRS
    raise ValueError("unknown target %r" % target)


def find(name: str, target: str = "me711") -> Path:
    """The one file called `name` in `target`'s search path."""
    hits = [d / name for d in include_dirs(target) if (d / name).is_file()]
    if len(hits) != 1:
        raise FileNotFoundError("%s: %d matches in the %s search path%s" % (
            name, len(hits), target, "" if not hits else ": " + ", ".join(map(str, hits))))
    return hits[0]


def sources(target: str = "me711", pattern: str = "*.c") -> list[Path]:
    """Every file matching `pattern` in `target`'s search path."""
    out: list[Path] = []
    for d in include_dirs(target):
        out += sorted(d.glob(pattern))
    return out


def target_sources(pattern: str = "*.c") -> list[Path]:
    """The ME7.1.1 target's own files (firmware/targets/me711/**)."""
    return [p for p in sources("me711", pattern) if ME711 in p.parents]


def portable_sources(pattern: str = "*.c") -> list[Path]:
    """The portable files (everything in firmware/ outside targets/)."""
    return [p for p in sources("me711", pattern) if ME711 not in p.parents]


def script(stem: str) -> Path:
    """The one tool or test script called <stem>.py, wherever it lives."""
    hits = [d / (stem + ".py") for d in module_dirs() if (d / (stem + ".py")).is_file()]
    if len(hits) != 1:
        raise FileNotFoundError("%s.py: %d matches under tools/ and tests/" % (stem, len(hits)))
    return hits[0]


def check() -> int:
    bad = 0
    seen_mod: dict[str, Path] = {}
    for d in module_dirs():
        for f in d.glob("*.py"):
            if f.stem in seen_mod and f.stem != "__init__":
                print("[FAIL] module %s in both %s and %s" % (f.stem, seen_mod[f.stem].parent, d))
                bad += 1
            seen_mod[f.stem] = f
    print("[%s] %d tool/test modules, names unique" % ("PASS" if not bad else "FAIL", len(seen_mod)))
    for target in ("me711",):
        seen: dict[str, Path] = {}
        for d in include_dirs(target):
            if not d.is_dir():
                print("[FAIL] %s: missing directory %s" % (target, d))
                bad += 1
                continue
            for h in d.glob("*.h"):
                if h.name in seen:
                    print("[FAIL] %s: %s in both %s and %s" % (target, h.name, seen[h.name].parent, d))
                    bad += 1
                seen[h.name] = h
        holders = [p for p in PORTABLE_DIRS if (p / "hctarget.h").exists()]
        if holders:
            print("[FAIL] a portable directory holds an hctarget.h: %s" % holders)
            bad += 1
        print("[%s] %s: %d headers, unique" % ("PASS" if not bad else "FAIL", target, len(seen)))
    return bad


if __name__ == "__main__":
    for k in ("ROOT", "FIRMWARE", "ME711", "ME711_BUILD", "IMAGES", "TUNERSTUDIO", "REG167", "RAW_EVIDENCE"):
        print("%-12s %s" % (k, globals()[k]))
    sys.exit(1 if check() else 0)
