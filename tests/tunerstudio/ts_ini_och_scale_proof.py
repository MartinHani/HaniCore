#!/usr/bin/env python3
r"""
ts_ini_och_scale_proof.py - every output channel's declared scale matches
the fixed-point unit the firmware writes there. Bugs B1/B2 (V97): the target
lambda was published x1000 and declared scale 1 (TunerStudio showed 1000,
the vehicle logger logged 1000, every VE-evidence cell read 99.9 % rich);
thirteen x10 channels showed ten times their value.

    py tests\tunerstudio\ts_ini_och_scale_proof.py [<ini>]

THE RULE (tools/research/och_scale_audit.py, promoted): HaniCore names a
fixed-point quantity by suffix (_x10 0.1, _x100 0.01, _x1000 0.001, _dv
0.1 V, _dc 0.1 C). Every put16/och16/och(offset, expr) in the ME7.1.1
target is paired with the [OutputChannels] line at that offset; an
expression whose suffix implies a scale the .ini does not declare FAILS,
and so does a channel NAME whose suffix contradicts its own scale.

ALLOWED (each with its reason): a channel that PACKS two values, whose
suffix describes one byte of it.

NEGATIVE CONTROL: the same check on a copy of the .ini with lambdaTarget's
0.001 removed must FAIL - the V97 defect, recreated.
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths as HCP  # noqa: E402

sys.path.insert(0, str(ROOT / "tools" / "research"))
import ts_ini                                   # noqa: E402
from och_scale_audit import implied             # noqa: E402

TGT = ROOT / "firmware/targets/me711"
INI = ROOT / "tunerstudio/hanicore_me711.ini"
ALLOWED = {
    868: "lamVeff packs bank 1 and bank 2 heater volts as two bytes",
}


def writers():
    out = {}
    for p in HCP.target_sources("*.c"):
        lines = p.read_text(errors="replace").splitlines()
        for i, line in enumerate(lines, 1):
            m = re.search(r"\b(?:put16|och16|och)\s*\(\s*(\d+)u?\s*,\s*(.+)$",
                          line)
            if not m:
                continue
            expr = m.group(2)
            j = i
            while expr.count("(") > expr.count(")") and j < len(lines) \
                    and j < i + 3:
                expr += " " + lines[j].strip()
                j += 1
            expr = re.sub(r"/\*.*?(\*/|$)", "", expr)      # comments
            out.setdefault(int(m.group(1)), []).append((p.name, i, expr))
    return out


def audit(ini_path):
    ini = ts_ini.load(str(ini_path))
    by_off = {}
    for c in ini.output_channels().values():
        if c["computed"] or c.get("kind") != "scalar":
            continue
        try:
            by_off.setdefault(int(c["offset"]), c)
        except (TypeError, ValueError):
            pass
    bad, paired = [], 0
    for off, ws in sorted(writers().items()):
        c = by_off.get(off)
        if not c or off in ALLOWED:
            continue
        declared = float(c["scale"]) if c["scale"] is not None else 1.0
        for fname, line, expr in ws:
            if re.search(r"[*/]|DIV32U|MUL", expr):
                continue                     # the expression rescales itself
            imp = implied(expr)
            if imp is None:
                continue
            paired += 1
            if abs(imp - declared) > 1e-9:
                bad.append("OCH %d %s: %s:%d writes %s (scale %g), declared %g"
                           % (off, c["name"], fname, line, expr[:50], imp,
                              declared))
        nimp = implied(c["name"])
        if nimp is not None and abs(nimp - declared) > 1e-9 \
                and not c["name"].endswith("Raw"):
            bad.append("OCH %d %s: the name says scale %g, declared %g"
                       % (off, c["name"], nimp, declared))
    return bad, paired


def main() -> int:
    ini = Path(sys.argv[1]) if len(sys.argv) > 1 else INI
    print("=== output-channel scales vs the firmware's fixed-point units ===")
    bad, paired = audit(ini)
    for b in bad:
        print("  [FAIL] " + b)
    print("  %d suffixed writes paired with their declarations, %d wrong"
          % (paired, len(bad)))
    text = ini.read_text(errors="replace")
    mut = re.sub(r'(lambdaTarget\s*=\s*scalar,\s*U16,\s*356,\s*"[^"]*",\s*)'
                 r'0\.001', r"\g<1>1", text, count=1)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "mut.ini"
        p.write_text(mut, encoding="utf-8")
        mbad, _ = audit(p)
    ctl = mut != text and any("356" in b for b in mbad)
    print("  control: lambdaTarget declared scale 1 (V97) -> %s"
          % ("CAUGHT" if ctl else "NOT CAUGHT - gate blind"))
    ok = not bad and paired > 20 and ctl
    print("OCH SCALE PROOF %s" % ("PASSES" if ok else "FAILS"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
