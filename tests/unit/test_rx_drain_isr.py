"""The serial RX drain ISR is the highest-rate handler in the system.

HC_RXTICK_US is 40 us, so hc_cc7_isr runs 25 000 times a second and everything
it costs is multiplied by that. These tests hold the two properties that make
it affordable and correct, and they are written so that undoing either one
fails here rather than showing up later as a mystery in a timing gate.

1. IT MUST NOT CALL ACROSS MODULES. hc_rx_store() lives in the target's hcvec
   module. Calling it made Keil emit RMASK = @0x7FFF - the compiler cannot see
   a cross-module callee's register usage, so it saved DPP0, DPP3, MDC, MDH,
   MDL and R1..R12 around an eleven-instruction fast path: 35 instructions of
   context for 11 of work. Writing the ring store inline dropped the mask to
   @0x40F0 and the fast path from 46 instructions to 22.

2. THE DRAIN INTERVAL MUST STAY UNDER ONE CHARACTER TIME. ASC0 has a one-byte
   receive buffer and, on this ECU family, no usable receive interrupt - the
   Bosch boot block owns trap 0x2B permanently (hctarget.h, confirmed by the
   2026-08-25 bench run reporting s0rTrap 0). If the drain period reaches a
   whole character time there is no margin left for interrupt latency or for a
   higher-priority ASIC PEC completion, and a byte is lost.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

TARGET = ROOT / "firmware/targets/me711"
HCTS = ROOT / "firmware/comms/hcts.c"
HCVEC = TARGET / "generated/hcvec_me711.c"
HCTARGET = TARGET / "hctarget.h"


def _define(text, name):
    m = re.search(r"#define\s+%s\s+([0-9]+)" % name, text)
    assert m, "%s not found" % name
    return int(m.group(1))


def _isr_source():
    src = HCTS.read_text(errors="replace")
    start = src.index("void hc_cc7_isr(void)")
    end = src.index("\n}", start)
    return src[start:end]


# ---------------------------------------------------------------- interval --

def test_the_drain_period_is_shorter_than_one_character_time():
    """The hard safety bound, derived rather than quoted."""
    h = HCTARGET.read_text(errors="replace")
    tick_us = _define(h, "HC_RXTICK_US")
    baud = _define(h, "TGT_BAUD")
    # 8N1 is ten bit times per character: start + 8 data + stop.
    char_us = 10.0 / baud * 1e6
    assert tick_us < char_us, (
        "the drain period %d us is not shorter than one %d-baud character "
        "(%.0f us) - a byte can be overwritten before it is read"
        % (tick_us, baud, char_us))
    # And it must leave real room, not just be arithmetically smaller: the
    # worst case is a byte arriving just after a poll, so the next poll must
    # still land well inside the following character.
    assert tick_us <= char_us / 2.0, (
        "the drain period %d us leaves under half a character (%.0f us) of "
        "margin for interrupt latency and higher-priority blocking"
        % (tick_us, char_us))


def test_the_receive_interrupt_is_still_documented_as_unusable():
    """If somebody ever makes the RX interrupt work, the polled drain and its
    cost stop being necessary - but that is a hardware finding, and it has to
    replace the recorded evidence rather than quietly coexist with it."""
    h = HCTARGET.read_text(errors="replace")
    assert "UNREACHABLE" in h and "TGT_TRAP_S0RINT" in h
    assert "CAPCOM1 COMPARE TICK" in h or "CAPCOM1 compare" in h


# ------------------------------------------------------------------- cost --

def test_the_isr_does_not_call_out_of_line():
    """A call in this handler is what forced the maximal register save."""
    body = _isr_source()
    assert "hc_rx_store(" not in body, (
        "hc_cc7_isr calls hc_rx_store() again - that is a cross-module call "
        "and Keil will go back to RMASK = @0x7FFF, 35 instructions of context "
        "around an 11-instruction fast path")
    # Nothing else may creep in either. Any identifier followed by '(' that is
    # not a cast, a keyword or a macro known to be inline is suspect.
    calls = set(re.findall(r"\b([a-z_][a-z0-9_]*)\s*\(", body))
    allowed = {"if", "unsigned", "int", "char", "while", "for", "return",
               "hc_cc7_isr", "void", "us_to_ticks"}
    suspicious = {c for c in calls if c not in allowed
                  and not c.startswith("us_to")}
    assert not suspicious, (
        "hc_cc7_isr gained call(s) to %s - the highest-rate handler in the "
        "system must not call anything" % ", ".join(sorted(suspicious)))


def test_the_isr_does_no_protocol_work():
    """The high-rate path captures a byte and advances hardware state. Parsing,
    framing, checksums and command dispatch belong to the main loop."""
    body = _isr_source().lower()
    for forbidden in ("crc", "hcts_", "memcpy", "strlen", "hc_cal_",
                      "put16", "page", "envelope", "sprintf"):
        assert forbidden not in body, (
            "hc_cc7_isr contains %r - protocol work does not belong in a "
            "25 kHz handler" % forbidden)


def test_the_inline_ring_store_matches_hc_rx_store():
    """The logic is duplicated on purpose, so it has to stay identical: same
    bounded ring, same head/tail discipline, same overflow counter."""
    isr = _isr_source()
    store = HCVEC.read_text(errors="replace")
    store = store[store.index("void hc_rx_store("):]
    store = store[:store.index("\n}")]

    def shape(t):
        t = re.sub(r"/\*.*?\*/", " ", t, flags=re.S)
        t = re.sub(r"\s+", " ", t)
        return t

    isr_s, store_s = shape(isr), shape(store)
    for frag in ("hc_rx_head + 1u", "HC_RXRING - 1u",
                 "hc_rx_ring[hc_rx_head]", "hc_rx_head = h", "hc_rx_ovf++"):
        assert frag in store_s, "hc_rx_store no longer has %r" % frag
        assert frag in isr_s, (
            "the inline store in hc_cc7_isr lost %r - it has drifted from "
            "hc_rx_store and the two must stay identical" % frag)
    # the guard has to be the SAME comparison, not a rewritten one
    assert "h != hc_rx_tail" in isr_s and "h != hc_rx_tail" in store_s


def test_the_byte_is_read_before_the_flag_is_cleared():
    """Clearing first risks clearing the flag of a byte that arrived in
    between. A lost interrupt stops the port for good; a lost byte costs one
    request."""
    body = _isr_source()
    read = body.index("S0RBUF")
    clear = body.index("S0RIC &= 0x7F")
    assert read < clear, (
        "hc_cc7_isr clears S0RIC before reading S0RBUF - see the comment in "
        "hc_rx_take() for why that eventually kills the port")


def test_the_compare_is_rescheduled_with_a_catch_up_path():
    """Without the catch-up, a handler that ran late behind a crank interrupt
    would not match again until T0 wrapped 43.7 ms later and the drain would
    simply stop."""
    body = _isr_source()
    assert "CC7 = (unsigned int)(CC7 +" in body, "the compare is not advanced"
    # EQUAL counts as passed (a compare fires on the increment TO the value):
    # me711_rx_drain_rearm_proof executes it; this only pins the source form.
    assert "(int)(CC7 - T0) <= 0" in body, "the late-handler catch-up test is gone"
    assert body.count("US_TO_TICKS(HC_RXTICK_US)") >= 2


# ------------------------------------------------- the compiled evidence --

def _listing():
    """The Keil listing for the ISR, if a CODE build has been made. Optional:
    the source-level tests above are the ones that must always run."""
    import os
    cand = []
    scratch = os.environ.get("HANICORE_SCRATCH")
    if scratch:
        cand.append(Path(scratch) / "hcts_after.lst")
    for p in cand:
        if p.exists():
            return p.read_text(errors="replace")
    return None


def test_compiled_register_mask_is_small_when_a_listing_is_available():
    text = _listing()
    if text is None:
        pytest.skip("no CODE listing built; source-level tests cover this")
    m = re.search(r"FUNCTION hc_cc7_isr \(BEGIN\s+RMASK = @0x([0-9A-Fa-f]+)",
                  text)
    assert m, "hc_cc7_isr not found in the listing"
    mask = int(m.group(1), 16)
    assert bin(mask).count("1") <= 8, (
        "RMASK 0x%04X saves %d registers - the cross-module call is back"
        % (mask, bin(mask).count("1")))
