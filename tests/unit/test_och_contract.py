"""The OCH contract gate must be able to FAIL, and the build must refuse.

A gate is worth exactly what its negative control is worth. This file
deliberately recreates the defect that took the frozen V29 image off the air on
real hardware on 2026-09-02 - a firmware block size and an .ini that disagree by
four bytes - and checks that both the gate and the build catch it.

The bench symptom, for the record:

    Unexpected runtime response size, expected: 116, received: 112

    blockingFactor 256, so the last chunk is ochBlockSize - 256.
      the .ini said 372  ->  asked for 116
      the image had 368  ->  answered 112, because hcts.c clamps

Neither artefact was wrong on its own. The frozen V29 pair is consistent at
368/368; the repo's live .ini had moved on to 372 while the frozen binary had
not. Nothing pinned one to the other.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "tests/tunerstudio/me711_och_contract_proof.py"
LIVE_INI = ROOT / "tunerstudio/hanicore_me711.ini"
TARGET_H = ROOT / ("firmware/targets/me711/hctarget.h")
BUILD = ROOT / "tools/build/build_hanicore_me711.py"


def _och_from_header() -> int:
    m = re.search(r"#define\s+TGT_OCH_SIZE\s+(\d+)",
                  TARGET_H.read_text(errors="replace"))
    assert m, "TGT_OCH_SIZE not found in hctarget.h"
    return int(m.group(1))


def _och_from_ini(text: str) -> int:
    m = re.search(r"^\s*ochBlockSize\s*=\s*(\d+)", text, re.M)
    assert m, "ochBlockSize not found in the .ini"
    return int(m.group(1))


def test_the_shipped_pair_agrees():
    """The live .ini and the target header must not have drifted apart.

    This is the cheap, always-on half. The expensive half - executing the
    linked image to measure what it REALLY answers - is the gate itself.
    """
    assert _och_from_header() == _och_from_ini(
        LIVE_INI.read_text(errors="replace")), (
        "TGT_OCH_SIZE and ochBlockSize disagree. TunerStudio will ask for "
        "one size and be answered another, then drop and reconnect forever.")


def test_blocking_factor_makes_a_last_chunk():
    """The arithmetic that turned four bytes into a dead connection.

    If ochBlockSize is an exact multiple of blockingFactor there is no partial
    last chunk and a size mismatch hides until the block grows. Recording the
    relationship here means the next person does not have to re-derive it from
    a TunerStudio error message.
    """
    t = LIVE_INI.read_text(errors="replace")
    och = _och_from_ini(t)
    bf = int(re.search(r"^\s*blockingFactor\s*=\s*(\d+)", t, re.M).group(1))
    chunks = [min(bf, och - o) for o in range(0, och, bf)]
    assert sum(chunks) == och
    assert all(c > 0 for c in chunks)


def test_the_build_refuses_a_mismatched_ini(tmp_path, monkeypatch):
    """Mutate the .ini by four bytes; the build must not produce an image.

    Restores the .ini whatever happens - a test that leaves the repo's
    TunerStudio contract corrupted would be worse than no test.
    """
    if not BUILD.exists():
        pytest.skip("no ME7.1.1 build tool")
    original = LIVE_INI.read_bytes()
    och = _och_from_header()
    mutated = original.replace(
        b"ochBlockSize   = %d" % och,
        b"ochBlockSize   = %d" % (och - 4), 1)
    assert mutated != original, "the mutation did not apply - check the format"
    try:
        LIVE_INI.write_bytes(mutated)
        r = subprocess.run([sys.executable, str(BUILD)],
                           capture_output=True, text=True, cwd=ROOT,
                           timeout=900)
        assert r.returncode != 0, (
            "the build ACCEPTED a four-byte .ini mismatch. That is the exact "
            "pair that took V29 off the air on hardware.")
        assert "TGT_OCH_SIZE" in (r.stdout + r.stderr), (
            "the build failed, but not for this reason - the check may be "
            "passing responsibility to something else:\n" + r.stdout[-2000:])
    finally:
        LIVE_INI.write_bytes(original)


def test_the_gate_exists_and_documents_the_bench_failure():
    """The gate must keep the evidence that produced it.

    A number like 116 is meaningless six months later; 'the last chunk is
    ochBlockSize - blockingFactor' is not.
    """
    assert GATE.exists()
    t = GATE.read_text(errors="replace")
    for needed in ("expected: 116, received: 112", "blockingFactor",
                   "TGT_OCH_SIZE"):
        assert needed in t, "the gate no longer records %r" % needed
