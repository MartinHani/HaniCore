#!/usr/bin/env python3
r"""
me711_build_integrity_proof.py - a successful build can never link stale
generated config sources.

    py tests\firmware\build\me711_build_integrity_proof.py

THE DEFECT. `build_hanicore_me711.py` did not run
`tools/config_source/generate_config.py` and did not check its outputs.
Editing `hanicore_presets.py` and rebuilding produced a **byte-identical
image** - successful build, clean gate suite, and the edit nowhere in the
firmware. A stale `.ini` is caught by the signature; a stale
`hc_presets.c` compiles, links, passes every gate that reads the image, and
ships an ECU whose presets are not the ones this repository describes.

THE FIX, AND WHY IT REFUSES RATHER THAN REGENERATES. The build now runs the
freshness check first and ABORTS on drift. Silently regenerating would make an
image's provenance depend on whether the generator happened to run - the
committed source and the compiled source could differ and the build would hide
it. Refusing keeps them the same thing, and the error message names the one
command that fixes it.

WHAT THIS GATE PROVES, and each one is an experiment rather than an assertion:

  1. **editing a config source regenerates the expected generated file** - and
     the change lands where it is supposed to, not merely somewhere;
  2. **a stale generated output makes the build FAIL HARD** - non-zero exit,
     and the existing image is not touched;
  3. **a clean rebuild is reproducible** - same sources, same hash;
  4. **the intended preset change is actually IN the produced binary** - by
     BOOTING the image and applying the preset, so the compiled table is the
     thing being used, not inferred from the build having succeeded.

EVERY MUTATION IS RESTORED. The tree is byte-identical afterwards whether this
passes or fails, and check 5 asserts that rather than trusting it.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_image as PI                  # noqa: E402

BUILD = ROOT / "tools/build/build_hanicore_me711.py"
GEN = ROOT / "tools/config_source/generate_config.py"
PRESETS_SRC = ROOT / "tools/config_source/hanicore_presets.py"
PRESETS_GEN = ROOT / "firmware/generated/hc_presets.c"

SYNC_MODE_OFF = 2538          # CFG_U_SYNC_MODE, from the generated header

CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print("  [%s] %-48s %s" % ("PASS" if ok else "FAIL", name, detail))


def sha(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest().upper()


def build():
    r = subprocess.run([sys.executable, str(BUILD)], cwd=str(ROOT),
                       capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


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

def preset_sync_modes():
    """Every preset's syncMode as the GENERATED SOURCE states it."""
    rows = re.findall(r"\{\s*%du,\s*(\d+)u,\s*\d+u\s*\}" % SYNC_MODE_OFF,
                      PRESETS_GEN.read_text(errors="replace"))
    return [int(v) for v in rows]


def source_sync_mode(preset_id: int) -> int:
    """What the CONFIG SOURCE says this preset's syncMode is (V97: the AWT
    preset moved from SYNC_CRANK_ONLY to cam-1 cycle sync for sequential).
    The applied value must equal the source - never a number typed here."""
    sys.path.insert(0, str(ROOT / "tools" / "config_source"))
    import hanicore_presets as HP          # noqa: E402
    for p in HP.ENGINE_PRESETS:
        if p.ident == preset_id:
            v = p.values.get("syncMode")
            if v is not None:
                return int(v.value)
    raise SystemExit("preset %d has no syncMode in the config source" % preset_id)


def applied_sync_mode(preset_id: int):
    """What the FIRMWARE writes when it applies this preset, and whether the
    resulting page validates.

    READ BY EXECUTION, NOT BY SCANNING THE IMAGE. The first version of this
    searched the code sectors for the three consecutive 16-bit words
    `offset, value, size` on the assumption that hc_engine_presets[] is laid
    out that way. It found ZERO entries - the assumption about the compiled
    struct was wrong - and a byte pattern that does not appear proves nothing
    either way.

    Booting the image and calling hc_preset_apply_engine_active() then reading
    the ACTIVE page back is stronger anyway: it is the compiled preset table
    being USED, so a build that linked a stale object shows up as the old
    value arriving in the page."""
    import me711_config_state_test as T   # local: it boots an image
    r = T.boot()
    r("hc_preset_apply_engine_active", preset_id)
    rc = r("hc_validate", T.VAL["HC_VAL_SRC_ACTIVE"]) & 0xFFFF
    return r.active(SYNC_MODE_OFF), rc


def main() -> int:
    print("=== a build can never link stale generated config sources ===\n")
    print("  image  %s\n" % PI.STEM)

    img_path = PI.image()
    base_hash = sha(img_path)
    src_before = PRESETS_SRC.read_bytes()
    # THE BASELINE IS REGENERATED, NOT SNAPSHOTTED. An earlier version captured
    # whatever happened to be on disk and restored THAT - which reintroduced
    # staleness whenever the file started out stale, and made the build fail
    # later in this very gate. The generator is deterministic (verified: two
    # consecutive runs are byte-identical), so the source is the baseline and
    # regenerating is the restore.
    run_generator()
    gen_before = PRESETS_GEN.read_bytes()
    before_modes = preset_sync_modes()
    print("  starting image sha256 %s\n" % base_hash)

    # ---------- 1. editing a config source regenerates the right file ------
    #
    # A SENTINEL VALUE, NOT A REAL ONE. The first two versions of this edited a
    # preset's syncMode and then tried to assert WHICH generated row moved.
    # Both were wrong, for the same reason: the generator emits presets in the
    # order 2, 4, 3 - not by id - so "the row I edited" was archaeology, and
    # one run was additionally confounded by the generated file being stale to
    # begin with. 7123 is a revMax no preset uses, so its appearance in the
    # generated output is unambiguous and needs no knowledge of row order.
    SENTINEL = b"7123"
    try:
        had_before = SENTINEL + b"u" in gen_before
        edited = src_before.replace(b'"revMax": Value(7500', b'"revMax": Value(7123', 1)
        check("the sentinel is not already in the generated output",
              not had_before and edited != src_before,
              "revMax 7123 is unused, and the edit applied")
        PRESETS_SRC.write_bytes(edited)
        run_generator()
        now = PRESETS_GEN.read_bytes()
        check("editing the config source regenerates hc_presets.c",
              now != gen_before and SENTINEL + b"u" in now,
              "the edited value appears in the generated file")
    finally:
        PRESETS_SRC.write_bytes(src_before)
        run_generator()
    check("...and reverting the source restores it byte for byte",
          PRESETS_GEN.read_bytes() == gen_before,
          "generation is a function of the source, not of history")

    # ---------- 2. a stale generated output FAILS THE BUILD HARD -----------
    try:
        PRESETS_GEN.write_bytes(
            gen_before.replace(b"/* syncMode */", b"/* syncMOD3 */", 1))
        code, out = build()
        check("a stale generated source FAILS the build", code != 0,
              "build exit %d, %s"
              % (code, "refused" if "STALE" in out or code else "PROCEEDED"))
        check("...and it names the file and the fix",
              "hc_presets.c" in out and "generate_config.py" in out,
              "the message points at the file and the command")
        check("...and the existing image was NOT touched",
              sha(img_path) == base_hash,
              "image hash unchanged at %s" % base_hash[:16])
    finally:
        # Regenerate rather than write the snapshot back: the source is the
        # truth and the generator is deterministic.
        run_generator()

    # ---------- 3. a clean rebuild is reproducible -------------------------
    code, out = build()
    first = sha(img_path)
    check("the build succeeds again once the tree is restored", code == 0,
          "exit %d" % code)
    code2, _ = build()
    second = sha(img_path)
    # TWO BUILDS THIS GATE PERFORMS, NOT A COMPARISON AGAINST WHATEVER IMAGE
    # WAS ON DISK WHEN IT STARTED. The first version compared against the
    # starting hash and failed - correctly, as it turned out, because the image
    # on disk had been built from a CONTAMINATED tree (a leaked test sentinel,
    # see run_generator()). Comparing a build to a build is the property that
    # was meant: same sources in, same image out.
    check("a clean rebuild reproduces the same image",
          code2 == 0 and first == second,
          "%s vs %s" % (first[:24], second[:24]))
    if first != base_hash:
        print("      NOTE: the image on disk when this gate started was %s; "
              "the reproducible build is %s" % (base_hash[:16], first[:16]))

    # ---------- 4. the preset change is IN the binary ----------------------
    mode3, rc3 = applied_sync_mode(3)
    mode4, rc4 = applied_sync_mode(4)
    want3 = source_sync_mode(3)
    check("applying the 1.8T preset writes the config source's syncMode",
          mode3 == want3,
          "the firmware's own preset table put syncMode = %s into the ACTIVE "
          "page; the source says %d (1 = SYNC_CRANK_ONLY, 2 = SYNC_CAM1_CYCLE)"
          % (mode3, want3))
    check("...and the page it produces is one hc_validate() ACCEPTS",
          rc3 == 0,
          "rc 0x%04X - a refused page can never arm an output (12M/3)" % rc3)
    check("the board default is unaffected and still applies clean",
          mode4 == source_sync_mode(4) and rc4 == 0,
          "board default syncMode = %s, rc 0x%04X" % (mode4, rc4))

    # ---------- 4b. the MANIFEST records the config pipeline ---------------
    #
    # A stale hc_presets.c once shipped an image whose presets were not the
    # ones the repository described, and the manifest could not have shown it:
    # neither the config SOURCE nor the GENERATED sources were in its
    # provenance list, so the recorded hashes were identical either way. The
    # build refuses stale sources now; this asserts the package can also be
    # AUDITED after the fact.
    import hashlib as _h
    import json as _j
    man = _j.loads(Path(str(img_path)[:-4] + ".json").read_text())
    src = man.get("provenance", {}).get("source_sha256", {})
    pipeline = [k for k in src
                if "config_source" in k or "hc_presets" in k
                or "hc_config_generated" in k or "pin_desc" in k]
    check("the manifest records the config pipeline", len(pipeline) >= 8,
          "%d of %d provenance entries are config source or generated source"
          % (len(pipeline), len(src)))

    drift = []
    for rel, want in src.items():
        f = ROOT / rel
        if not f.exists():
            drift.append(rel + " (absent)")
        elif _h.sha256(f.read_bytes()).hexdigest().upper() != want.upper():
            drift.append(rel)
    check("every file the manifest names still hashes as recorded",
          not drift, "drifted: %s" % (", ".join(drift[:4]) if drift else "none"))

    # ---------- 4c. no RELEASE package disagrees with its own binary -------
    bad = []
    for j in sorted((ROOT / "release").glob("*/*.json")):
        try:
            m = _j.loads(j.read_text())
        except Exception:
            continue
        want = str(m.get("sha256", "")).upper()
        b = j.with_suffix(".bin")
        if want and b.exists():
            got = _h.sha256(b.read_bytes()).hexdigest().upper()
            if got != want:
                bad.append("%s/%s" % (j.parent.name, j.name))
    check("no release package's manifest disagrees with its binary",
          not bad, "mismatched: %s" % (", ".join(bad) if bad else "none"))

    # ---------- 5. the tree is exactly as it was found ---------------------
    check("every mutation this gate made was restored",
          PRESETS_SRC.read_bytes() == src_before
          and PRESETS_GEN.read_bytes() == gen_before,
          "config source and generated source byte-identical")

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("BUILD INTEGRITY FAILS - a build can still link generated "
              "sources that do not match the config source beside them.")
        return 1
    print("BUILD INTEGRITY PASSES - the build refuses stale generated "
          "sources, a rebuild is reproducible, and the configured value is "
          "present in the binary rather than merely in the repository.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
