#!/usr/bin/env python3
r"""
audit_gates.py - what evidence does each gate actually rest on?

    py tests\run_gates.py --audit [selection]     (the usual way in)
    py tests\audit_gates.py                       every gate

WHY. Gates have been green for months while proving less than they appeared
to: a stack proof that never saw the stack pointer move, a state test calling
a function that no longer did the work, an .ini check reading a length as an
offset. So the question for every gate is not "is it green" but "what broken
implementation would still make it green". This tool cannot answer that
alone; it classifies the evidence each gate rests on so the weak ones are
visible:

  EXECUTES        runs the linked image in c167sim - evidence about the
                  artefact that will be flashed
  HOST EXECUTES   an SFR-free core compiled and run on a host compiler
  READS MAP       reads the linker's output
  READS IMAGE BYTES / READS OEM BINARY
  CONTROL         runs a negative control (mutation or frozen older image)
  MUTATED         a unit test deliberately breaks this gate's parser
  READS SOURCE    none of the above: inspects source text only
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import catalog as CAT  # noqa: E402

# Modules that BRING A HARNESS with them: importing one executes the image.
HARNESS = ("c167sim", "me711_boot_test", "me711_hal_test", "me711_trigger_test",
           "me711_config_state_test", "me711_heartbeat_gap_proof", "me711_ts_gap_proof",
           "me711_gap_scheduler_proof")


def classify(path: Path) -> list:
    t = path.read_text(errors="replace")
    tags = []
    if any(re.search(r"\b(?:import|from)\s+%s\b" % h, t) for h in HARNESS):
        tags.append("EXECUTES")
    if re.search(r"c166_disasm|OEM\b.*\.bin|disassemb", t) or re.search(r"bins/.*(a1146|oem|OEM)", t):
        tags.append("READS OEM BINARY")
    if ".M66" in t or "PI.MAP" in t or "MAP_FILE" in t or "map_path" in t:
        tags.append("READS MAP")
    if re.search(r"(?:PI|IMG)\.image\(\)(?:\.read_bytes)?|IMG\.read_bytes", t) and "EXECUTES" not in tags:
        tags.append("READS IMAGE BYTES")
    if re.search(r"\bimport\s+host_c_test\b", t):
        tags.append("HOST EXECUTES")
    if re.search(r"\bCONTROL\b|nop_yield|_without_yield", t):
        tags.append("CONTROL")
    return tags or ["READS SOURCE"]


def mutated(gates) -> set:
    names = {g.name for g in gates}
    out = set()
    for f in (ROOT / "tests" / "unit").glob("test_*.py"):
        t = f.read_text(errors="replace")
        out |= {n for n in names if n in t}
    return out


def audit(gates) -> int:
    gates = [g for g in gates if g.kind != "physical"]
    mut = mutated(gates)
    rows = []
    for g in gates:
        tags = classify(g.path) + (["MUTATED"] if g.name in mut else [])
        rows.append((g.name, tags))
    width = max((len(n) for n, _ in rows), default=10)
    for n, tags in rows:
        print("  %-*s  %s" % (width, n, ", ".join(tags)))
    strong = ("EXECUTES", "READS MAP", "READS IMAGE BYTES", "READS OEM BINARY")
    artefact = [n for n, t in rows if any(x in t for x in strong)]
    host = [n for n, t in rows if "HOST EXECUTES" in t]
    controls = [n for n, t in rows if "CONTROL" in t]
    weak = [n for n, t in rows if not any(x in t for x in strong) and "HOST EXECUTES" not in t]
    print("\n    %3d of %d gates rest on the artefact (image, map or OEM binary)" % (len(artefact), len(rows)))
    print("    %3d run a negative control" % len(controls))
    print("    %3d execute an SFR-free core on a host compiler" % len(host))
    print("    %3d rest on source text alone" % len(weak))
    return 0


if __name__ == "__main__":
    sys.exit(audit(CAT.gates()))
