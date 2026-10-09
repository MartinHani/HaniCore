#!/usr/bin/env python3
r"""The real TunerStudio session of 2026-09-16, pinned as a regression.

    py -m pytest tests/unit/test_ts_session_audit.py

WHY A LOG FILE IS A TEST FIXTURE
================================
`me711_ts_session_audit.py` is what turns a real acceptance run into evidence:
the operator presses Burn, and the audit reads TunerStudio's own log and says
whether the session was ever hurt. **That makes the audit itself
safety-critical** - an audit that silently stops recognising
`Controller Reported a Unrecognized Command` would report the next V59-class
defect as a clean pass.

So the failing session is kept, verbatim, as
`fixtures/ts_session_20260916_v59_fail.txt`, and the audit must go on failing
it with the same counts. It is the negative fixture the V60 work is built on
and it is the one trace in this repository that came from real TunerStudio
rather than from a model of it.

The positive fixture is the REAL passing session of the same day, 13:28-13:38,
against V60: the operator set a crank pin and a sync mode, pressed Burn, and
TunerStudio logged `burned page 1`. A synthesised clean session is kept beside
it as a unit check of the audit itself, but the one that matters is the
captured one - a pass proven by the absence of lines is only worth as much as
the run it came from.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_ts_session_audit as A                             # noqa: E402

FAIL_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ts_session_20260916_v59_fail.txt"
PASS_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ts_session_20260916_v60_pass.txt"

# A session that did everything and complained about nothing. Every line here
# is one the audit CLASSIFIES - connect, burn, page read - and not one is one
# it counts as damage.
CLEAN = """\
16/09/26 14:00:01 :Info: Sig Bytes:x72 x75 x73 x45 x46 x49
16/09/26 14:00:01 :Info: Communicating with sig:rusEFI HaniCore ME711 BA3113D1, HaniCore V60 BURN REFUSAL / Bosch ME7.1.1
16/09/26 14:00:02 :Info: Activating page: 1
16/09/26 14:00:03 :Debug: Read page time: 1085ms.
16/09/26 14:00:20 :Info: dirtyData.size(): 1
16/09/26 14:00:20 :Debug: Burn Page anonymous: 1
16/09/26 14:00:20 :Info: Queueing burn to page:1
16/09/26 14:00:22 :Debug: Read page time: 1090ms.
16/09/26 14:00:40 :Debug: Burn Page anonymous: 1
16/09/26 14:00:40 :Info: Queueing burn to page:1
16/09/26 14:00:42 :Debug: Read page time: 1088ms.
""".splitlines()


def audit_lines(lines, **kw):
    return A.audit(lines, **kw)


def test_the_failing_session_is_still_recognised():
    """The 2026-09-16 session, and the audit must still call every bit of it."""
    assert FAIL_FIXTURE.exists(), "the real transcript is the point of this test"
    ev, sigs = audit_lines(FAIL_FIXTURE.read_text(encoding="latin1").splitlines())

    # THE DEFECT ITSELF. If this stops being seen, the audit is blind to the
    # exact thing V60 exists to prevent.
    assert len(ev["unrecognized_command"]) == 3, ev["unrecognized_command"]
    assert len(ev["failed_validation"]) == 3
    assert len(ev["reconnect"]) == 4
    assert len(ev["read_timeout"]) == 4
    assert len(ev["payload_crc_failure"]) == 1

    # ... and its cause: ONE Burn was queued, and it produced all of that.
    assert len(ev["burn_queued"]) == 1

    # The V59 firmware and the V48 .ini answered to the same signature, which
    # is defect 2. Both are present in the trace.
    assert ("rusEFI Hanicore v1",
            "HaniCore V59 FORENSIC WINDOW / Bosch ME7.1.1") in sigs


def test_the_failing_session_scores_as_a_failure():
    ev, sigs = audit_lines(FAIL_FIXTURE.read_text(encoding="latin1").splitlines())
    hurt = [k for k in A.FATAL if ev[k]]
    assert hurt, "a session with four reconnects is not a pass"
    assert "unrecognized_command" in hurt
    assert "reconnect" in hurt


def test_the_real_v60_session_scores_as_a_pass():
    """THE ACCEPTANCE RUN, 2026-09-16 13:28-13:38, kept as a fixture.

    Same operator, same bench, same tool, ONE queued Burn - as V59's failing
    session had - and this one hurt nothing. If the audit ever stops
    distinguishing these two files it has stopped being evidence.
    """
    assert PASS_FIXTURE.exists()
    ev, sigs = audit_lines(PASS_FIXTURE.read_text(encoding="latin1").splitlines())
    hurt = [k for k in A.FATAL if ev[k]]
    assert hurt == [], hurt
    assert len(ev["burn_queued"]) == 1, "the Burn that matters must be in here"
    assert ("rusEFI HaniCore ME711 BA3113D1",
            "HaniCore V60 BURN REFUSAL / Bosch ME7.1.1") in sigs


def test_the_two_real_sessions_differ_exactly_where_they_should():
    """One queued Burn each. Everything else is the defect and its absence."""
    bad, _ = audit_lines(FAIL_FIXTURE.read_text(encoding="latin1").splitlines())
    good, _ = audit_lines(PASS_FIXTURE.read_text(encoding="latin1").splitlines())
    assert len(bad["burn_queued"]) == len(good["burn_queued"]) == 1
    for k in ("unrecognized_command", "failed_validation", "reconnect",
              "read_timeout", "payload_crc_failure"):
        assert bad[k], "V59 must still show %s" % k
        assert not good[k], "V60 must show no %s" % k


def test_a_clean_session_scores_as_a_pass():
    ev, sigs = audit_lines(CLEAN)
    hurt = [k for k in A.FATAL if ev[k]]
    assert hurt == [], hurt
    assert len(ev["burn_queued"]) == 2
    assert sigs and sigs[0][0] == "rusEFI HaniCore ME711 BA3113D1"


def test_the_window_really_windows():
    """--since must exclude what came before it, or a stale failure is scored."""
    lines = FAIL_FIXTURE.read_text(encoding="latin1").splitlines()
    after = datetime(2026, 9, 16, 12, 10, 0)
    ev, _ = audit_lines(lines, since=after)
    assert not ev["unrecognized_command"], \
        "12:09:12 is before 12:10:00 and must not be counted"
    ev_all, _ = audit_lines(lines)
    assert ev_all["unrecognized_command"], "the unwindowed run still sees it"


@pytest.mark.parametrize("code,text", [
    (0x83, "Controller Reported a Unrecognized Command"),
    (0x84, "Controller Reported a Out of Range"),
    (0x85, "Controller reporting BUSY"),
    (0x82, "Controller Reported a CRC Mismatch"),
])
def test_every_bit7_code_is_watched_for(code, text):
    """THE GENERAL RULE, NOT THE ONE CODE.

    TunerStudio ends the session on EVERY response code with bit 7 set
. V60's first attempted fix was 0x84, which would have
    behaved exactly like the 0x83 it replaced - so the audit has to watch for
    the whole class, or it would have reported that attempt as a success.
    """
    assert code & 0x80
    ev, _ = audit_lines(["16/09/26 14:00:00 :Warning: %s!" % text])
    assert any(ev[k] for k in A.FATAL), \
        "%s (0x%02X) is not being watched for" % (text, code)
