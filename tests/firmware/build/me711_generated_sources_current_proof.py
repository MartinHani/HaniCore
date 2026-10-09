#!/usr/bin/env python3
r"""
me711_generated_sources_current_proof.py - the checked-in generated sources are
what the generator produces from the checked-in config source.

    py tests\firmware\build\me711_generated_sources_current_proof.py

WHY, AND IT COST A BUILD TO FIND. `tools/build/build_hanicore_me711.py` does NOT run
`tools/config_source/generate_config.py`, and does not check that its outputs
are current. So editing `hanicore_presets.py` and rebuilding produces an image
compiled from the PREVIOUS generated sources - silently, with a successful
build and a clean gate suite.

Measured: after changing preset 3's `syncMode` and rebuilding, the image hash
was **byte-identical** to the build before the edit. The change had not reached
the firmware at all. Only running the generator by hand and rebuilding moved
it.

That is this project's oldest standing defect, from its own rules:

> *"Two artefacts that must agree, and nothing that makes them. This defect has
> now cost four incidents... Derive or prove metadata; never copy it by hand.
> Every generated pair needs a gate that loads both artefacts."*

**A STALE GENERATED SOURCE IS WORSE THAN A STALE `.ini`.** An `.ini` mismatch
is caught by the signature (§12J). A stale `hc_presets.c` compiles, links,
passes every gate that reads the image, and ships an ECU whose presets are not
the ones the repository describes.

HOW IT WORKS. The generator is run and its outputs compared with what is
checked in. **The tree is left exactly as it was found**, byte for byte,
whether the check passes or fails - the originals are held in memory and
written back unconditionally, so this gate can never be the reason a file
changed.

PROVEN ABLE TO FAIL. One token in `hc_presets.c` was altered and the gate
reported `STALE: firmware/generated/hc_presets.c`, 3/4, exit 1 - and then
restored the altered file, because "leave the tree as found" applies to the
failing case too. A gate that quietly regenerated would hide the drift it
exists to report.

WHAT IT DOES NOT DO: run the generator as part of the build. That is the real
fix and it is a build change, not a gate change. This makes the gap visible on
every suite run in the meantime.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GEN = ROOT / "tools/config_source/generate_config.py"

# Everything generate_config.py writes. Taken from its own output lines rather
# than guessed, and checked below - a file that stops being written is a
# change to the generator that this list has to notice.
OUTPUTS = [
    "firmware/generated/hc_config_generated.h",
    "firmware/generated/hc_config_generated.c",
    "firmware/generated/hc_pin_descriptor.h",
    "firmware/generated/hc_pin_descriptor.c",
    "firmware/generated/hc_presets.h",
    "firmware/generated/hc_presets.c",
    "firmware/generated/hc_pin_desc_bosch_me711.c",
    "firmware/generated/hc_pin_desc_me75_4b0906018dc.c",
    "build/generated/hc_config_model.csv",
]

CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print("  [%s] %-50s %s" % ("PASS" if ok else "FAIL", name, detail))


def run_generator():
    """Run the config generator with a PURGED BYTECODE CACHE.

    WITHOUT THIS THE WHOLE CHECK CAN AGREE WITH ITSELF AND BE WRONG. Python
    validates a cached .pyc by (mtime, size). A tool that rewrites
    hanicore_presets.py with content of the SAME LENGTH inside the filesystem's
    mtime granularity leaves the cache looking valid, so the generator imports
    the OLD module - and then the generated files and the generator's output
    are consistently stale together, which is exactly what this gate cannot
    detect by comparing them.

    MEASURED: a test harness rewrote the config source, regenerated, restored
    the source byte-identically, regenerated again - and `revMax 7123`, a
    value that exists in no config source, survived in hc_presets.c and was
    COMPILED INTO AN IMAGE. Deleting __pycache__ and regenerating removed it.
    """
    import shutil
    cache = GEN.parent / "__pycache__"
    if cache.exists():
        shutil.rmtree(cache, ignore_errors=True)
    return subprocess.run([sys.executable, str(GEN)], cwd=str(ROOT),
                          capture_output=True, text=True)

def digest(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def main() -> int:
    print("=== the generated sources are current with the config source ===\n")

    # build/ outputs are local review files (gitignored): a fresh checkout has
    # none, and an absent file cannot be stale - the generator writes it.
    present = [rel for rel in OUTPUTS
               if not (rel.startswith("build/") and not (ROOT / rel).exists())]
    paths = [ROOT / rel for rel in present]
    missing = [rel for rel, p in zip(present, paths) if not p.exists()]
    check("every generated file this gate knows about exists", not missing,
          "absent: %s" % (", ".join(missing) if missing else "none"))
    if missing:
        print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
        return 1

    before = {p: p.read_bytes() for p in paths}

    r = run_generator()
    try:
        check("the generator runs", r.returncode == 0,
              "exit %d%s" % (r.returncode,
                             "" if r.returncode == 0
                             else " - " + (r.stderr or "")[-200:]))
        after = {p: p.read_bytes() for p in paths}
        drifted = [p.relative_to(ROOT).as_posix()
                   for p in paths if before[p] != after[p]]
        check("nothing the generator writes is out of date", not drifted,
              "STALE: %s - run py tools\\config_source\\generate_config.py "
              "and rebuild" % ", ".join(drifted) if drifted
              else "%d files byte-identical" % len(paths))
    finally:
        # THE TREE IS RESTORED WHETHER THIS PASSES OR FAILS. A gate that
        # silently regenerates sources would hide the very drift it exists to
        # report, and would make the next build's provenance depend on whether
        # somebody had run the suite.
        for p, data in before.items():
            p.write_bytes(data)
    check("the tree is exactly as this gate found it",
          all(digest(p) == hashlib.sha256(before[p]).hexdigest() for p in paths),
          "all %d files restored byte for byte" % len(paths))

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("GENERATED SOURCES ARE STALE - the firmware would be built from "
              "config the repository no longer describes, and the build does "
              "not check. Run the generator, rebuild, and compare the image "
              "hash: if it does not move, the edit never reached the image.")
        return 1
    print("GENERATED SOURCES ARE CURRENT - what is checked in is what the "
          "generator produces from the config source beside it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
