#!/usr/bin/env python3
r"""me711_ts_session_audit.py - score a REAL TunerStudio session from the log
TunerStudio itself writes.

    py tools\tunerstudio\me711_ts_session_audit.py --since 2026-09-16T12:00
    py tools\tunerstudio\me711_ts_session_audit.py --out <folder>

WHY THIS EXISTS
===============
The acceptance test for a Burn is not a gate in this repository. It is a person
pressing Burn in real TunerStudio, and until now the only record of what
happened was what they remembered. On 2026-09-16 that record said "an error,
then it reconnected several times", which is true and is not enough to fix
anything.

TunerStudio writes a complete protocol-level account of every session to
`Documents/TunerStudioProjects/TunerStudioAppDebug.txt`, including the exact
thing that matters here:

    Warning: Controller Reported a Unrecognized Command!
    call failed protocol validation, running stats: 1 failed, 574 successful
    Going offline before all changes were permanently saved to the Controller.
    Re-establishing connection to: RS232: Port:COM3, Baud:57600

So the operator does not have to decode anything and does not have to remember
anything. They run the acceptance matrix; this reads what TunerStudio thought
of it.

**IT IS THE HOST'S HALF OF THE EVIDENCE AND ONLY THE HOST'S HALF.** The ECU's
half - rstBootCount, the receive counters, nvmState, cfgValidation - comes from
`me711_och_snapshot.py` before and after, because TunerStudio holds COM3 while
it is connected and nothing else can ask the ECU anything.

WHAT COUNTS AS A PASS
---------------------
Per the V60 acceptance matrix: a Burn may be refused, and a refusal may not
cost the session. So:

    unrecognised-command reports      MUST be 0
    other protocol-validation failures MUST be 0
    reconnects                        MUST be 0
    CRC failures on received payloads MUST be 0
    read timeouts                     MUST be 0
    the signature TunerStudio saw     MUST be the one the firmware declares

A Burn that is refused leaves NO trace in this log at all, because the reply is
an ordinary accepted response - which is the whole design. The refusal is read
off the ECU instead.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG = (Path.home() / "Documents" / "TunerStudioProjects"
               / "TunerStudioAppDebug.txt")
TGT = ROOT / "firmware/targets/me711/hctarget.h"

# Every line TunerStudio writes that means the session was hurt. The strings
# are TunerStudio's own, from TunerStudioMS.jar - not paraphrases.
EVENTS = [
    ("unrecognized_command", r"Controller Reported a Unrecognized Command"),
    ("out_of_range", r"Controller Reported a Out of Range"),
    ("busy", r"Controller reporting BUSY"),
    ("under_run", r"Controller Reported an Under-run"),
    ("over_run", r"Controller Reported an Over-run"),
    ("crc_mismatch", r"Controller Reported a CRC Mismatch"),
    ("flash_locked", r"Controller Reported Flash Locked"),
    ("framing_error", r"Controller Reported Framing Error"),
    ("payload_crc_failure", r"CRC failure on received payload"),
    ("failed_validation", r"call failed protocol validation"),
    ("reconnect", r"Re-establishing connection to"),
    ("went_offline", r"Going offline before all changes were permanently"),
    ("read_timeout", r"Timeout after:\d+ms"),
    ("burn_queued", r"Queueing burn to page"),
    ("burn_skipped", r"skip burn to page|Skip Burn, last write page"),
    ("page_read", r"Read page time:"),
    ("connected", r"Communicating with sig:"),
]

# The ones that mean the session was hurt. burn_queued / page_read / connected
# are progress, not damage.
FATAL = ("unrecognized_command", "out_of_range", "busy", "under_run",
         "over_run", "crc_mismatch", "flash_locked", "framing_error",
         "payload_crc_failure", "failed_validation", "reconnect",
         "went_offline", "read_timeout")

STAMP = re.compile(r"^(\d\d)/(\d\d)/(\d\d) (\d\d):(\d\d):(\d\d)")


def parse_when(line):
    m = STAMP.match(line)
    if not m:
        return None
    d, mo, y, h, mi, s = (int(x) for x in m.groups())
    return datetime(2000 + y, mo, d, h, mi, s)


def audit(lines, since=None, until=None):
    out = {k: [] for k, _ in EVENTS}
    sigs = []
    when = None
    for i, line in enumerate(lines):
        w = parse_when(line)
        if w:
            when = w
        if since and (when is None or when < since):
            continue
        if until and when is not None and when > until:
            continue
        for key, pat in EVENTS:
            if re.search(pat, line):
                out[key].append((i + 1, when.isoformat() if when else "?",
                                 line.strip()[:160]))
        m = re.search(r"Communicating with sig:([^,]+),\s*(.*)", line)
        if m:
            sigs.append((m.group(1).strip(), m.group(2).strip()))
    return out, sigs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", type=Path, default=DEFAULT_LOG)
    ap.add_argument("--since", help="ISO datetime, e.g. 2026-09-16T12:00")
    ap.add_argument("--until", help="ISO datetime")
    ap.add_argument("--out", type=Path, help="write the JSON and an extract here")
    ap.add_argument("--expect-signature", default=None,
                    help="default: the one hctarget.h declares")
    a = ap.parse_args()

    if not a.log.exists():
        print("no TunerStudio log at %s" % a.log)
        return 2
    lines = a.log.read_text(encoding="latin1").splitlines()
    since = datetime.fromisoformat(a.since) if a.since else None
    until = datetime.fromisoformat(a.until) if a.until else None
    ev, sigs = audit(lines, since, until)

    want = a.expect_signature
    if want is None and TGT.exists():
        m = re.search(r'#define\s+TGT_SIGNATURE\s+"([^"]*)"',
                      TGT.read_text(errors="replace"))
        want = m.group(1) if m else None

    print("=== real TunerStudio session audit ===")
    print("  log      %s" % a.log)
    print("  window   %s .. %s" % (a.since or "(start)", a.until or "(end)"))
    print("  expected signature %r\n" % want)

    print("  --- what TunerStudio connected to ---")
    if not sigs:
        print("      (no connection in this window)")
    for s, fw in dict.fromkeys(sigs):
        ok = (want is None or s == want)
        print("      [%s] %-34r %s" % ("PASS" if ok else "FAIL", s, fw))

    print("\n  --- what TunerStudio reported ---")
    fails = 0
    for key, _pat in EVENTS:
        n = len(ev[key])
        if key in FATAL:
            print("      [%s] %-24s %d" % ("PASS" if n == 0 else "FAIL", key, n))
            if n:
                fails += 1
                for ln, w, txt in ev[key][:4]:
                    print("             %s  line %d  %s" % (w, ln, txt))
        else:
            print("      [ -- ] %-24s %d" % (key, n))

    bad_sig = [s for s, _ in sigs if want is not None and s != want]
    if bad_sig:
        fails += 1

    ok = fails == 0 and bool(sigs)
    print("\n%s" % ("TS SESSION AUDIT: PASS - the session was never hurt"
                    if ok else
                    "TS SESSION AUDIT: %d category(ies) failed" % fails))
    if not sigs:
        print("  (and no connection was found in the window, so nothing was "
              "proven - check --since)")

    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "ts_session_audit.json").write_text(
            json.dumps({"log": str(a.log), "since": a.since, "until": a.until,
                        "expected_signature": want,
                        "signatures": [list(s) for s in dict.fromkeys(sigs)],
                        "counts": {k: len(v) for k, v in ev.items()},
                        "events": {k: v for k, v in ev.items() if v},
                        "pass": ok}, indent=2) + "\n", encoding="ascii")
        lo = min((e[0] for v in ev.values() for e in v), default=1)
        hi = max((e[0] for v in ev.values() for e in v), default=len(lines))
        (a.out / "ts_session_extract.txt").write_text(
            "\n".join(lines[max(0, lo - 40):min(len(lines), hi + 40)]) + "\n",
            encoding="latin1")
        print("  wrote %s" % (a.out / "ts_session_audit.json"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
