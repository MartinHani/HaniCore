#!/usr/bin/env python3
r"""
ts_ini_terminology_proof.py - no chip names, Bosch net/part names, MCU pins,
release numbers or Bosch 'rl' in what a TUNER reads (the Setup / Fuel /
Ignition / Cranking / Idle / Advanced / Sensors workflows, tables, curves,
the front page) - the project rules "plain tuner language", bug B9.

    py tests\tunerstudio\ts_ini_terminology_proof.py [<ini>]

The term list and the tuner/diagnostic split are
tools/research/terminology_audit.py's (promoted); Diagnostics, Controller
and Developer views may keep their hardware words. Gauges whose title is the
raw channel name fail too (bug B8).

NEGATIVE CONTROL: a copy of the .ini with Bosch 'rl' put back into a tuner
table title must FAIL.
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "research"))
import ts_ini                                          # noqa: E402
from terminology_audit import TERMS, strings           # noqa: E402

INI = ROOT / "tunerstudio/hanicore_me711.ini"


def tuner_hits(path):
    ini = ts_ini.load(str(path))
    hits, raw = [], 0
    for where, text, tuner in strings(ini):
        if text.startswith("RAW-NAME-AS-TITLE:"):
            raw += 1
            continue
        if not tuner:
            continue
        for rx, cat, _rep in TERMS:
            for m in re.finditer(rx, text):
                hits.append("%s: `%s` (%s) in \"%s\"" % (where, m.group(0),
                                                        cat, text[:70]))
    return hits, raw


def main() -> int:
    ini = Path(sys.argv[1]) if len(sys.argv) > 1 else INI
    print("=== tuner-facing terminology ===")
    hits, raw = tuner_hits(ini)
    for h in hits:
        print("  [FAIL] " + h)
    print("  %d tuner-facing hits, %d gauges titled with a raw channel name"
          % (len(hits), raw))
    text = ini.read_text(errors="replace")
    mut = re.sub(r'(table = \w+, \w+, ")[^"]*"',
                 r'\1Ignition vs air charge rl"', text, count=1)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "mut.ini"
        p.write_text(mut, encoding="utf-8")
        mh, _ = tuner_hits(p)
    ctl = mut != text and len(mh) > len(hits)
    print("  control: 'air charge rl' in a tuner table title -> %s"
          % ("CAUGHT" if ctl else "NOT CAUGHT - gate blind"))
    ok = not hits and not raw and ctl
    print("TERMINOLOGY PROOF %s" % ("PASSES" if ok else "FAILS"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
