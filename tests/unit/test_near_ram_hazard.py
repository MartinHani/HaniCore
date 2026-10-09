"""The near-memory hazard gate must actually catch the defect it exists for.

A gate nobody has ever seen fail is not evidence. These tests feed
near_ram_hazard_proof's own parsers synthetic linker maps that reproduce the
V29 defect and its neighbours, and assert the gate sees them.

The defect being reproduced: hc_asic_state allocated at 0x00FCE2, which is
DSTP0, so every PEC-driven SSC transfer overwrote the ASIC state machine's
state with the low byte of a buffer address.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import near_ram_hazard_proof as G  # noqa: E402


# A minimal map in the shape L166 emits: the located-segment table, then the
# symbol table. Only the columns the gate reads have to be right.
def _map(segments, variables):
    lines = ["  SEGMENT/GROUP LOCATION TABLE", ""]
    for start, end, kind, cls, name in segments:
        lines.append(
            "%06XH   %06XH   %06XH   %s  REL   WORD   ---    2  PUBL  %s   %s"
            % (start, end, end - start + 1, kind, cls, name))
    lines += ["", "  SYMBOL TABLE", ""]
    for addr, name in variables:
        lines.append("      %06XH     %-32s VAR   ---  NDATA0  ?ND0?X"
                     % (addr, name))
    return "\n".join(lines) + "\n"


GPR = (0x00FC00, 0x00FC1F, "DATA", "---", "?C_MAINREGISTERS")


def test_reg167_is_the_authority_and_is_actually_present():
    """The gate derives its regions from Infineon's header, not from a list
    somebody typed. If that header goes missing the gate must not quietly
    keep asserting the addresses from memory."""
    regs = G.reg167_addresses()
    assert regs, "reg167.h did not parse - the gate has no authority"
    assert regs.get(0xFCE0) == "SRCP0"
    assert regs.get(0xFCE2) == "DSTP0"
    assert regs.get(0xFCFE) == "DSTP7"
    # and every span the gate reserves is backed by real registers in it
    for lo, hi, _what, _why in G.ARCH_REGIONS:
        assert any(lo <= a <= hi for a in regs), \
            "span 0x%04X-0x%04X has no register behind it" % (lo, hi)


def test_every_reg167_address_is_inside_a_reserved_span():
    """If the header names a register the gate does not know a span for, the
    gate is blind to it. That must be visible, not silent."""
    regs = G.reg167_addresses()
    stray = [a for a in regs
             if not any(lo <= a <= hi for lo, hi, _, _ in G.ARCH_REGIONS)]
    assert not stray, \
        "registers outside every reserved span: " + ", ".join(
            "%s@0x%04X" % (regs[a], a) for a in sorted(stray)[:8])


def test_the_v29_defect_is_detected_when_reintroduced():
    """THE mutation: put hc_asic_state back on DSTP0."""
    text = _map(
        [GPR,
         (0x00FCB2, 0x00FCE4, "DATA", "NDATA0", "?ND0?HCASICSTART")],
        [(0x00FCE2, "hc_asic_state")])
    found = [(a, n) for a, n in G.variables(text) if 0xFCE0 <= a <= 0xFCFF]
    assert found == [(0x00FCE2, "hc_asic_state")], \
        "the gate no longer sees a variable on DSTP0"


def test_a_segment_that_merely_spans_the_pec_file_is_detected():
    """Stronger than the per-variable check: a segment can hold data the map
    never names. Spanning the region is enough to fail."""
    text = _map(
        [GPR,
         (0x00FCD0, 0x00FD10, "DATA", "NDATA0", "?ND0?SOMETHING")],
        [])           # deliberately NO named variable inside
    segs = G.data_segments(text)
    crossing = [s for s in segs
                if "MAINREGISTERS" not in s[2]
                and G.overlap(s[0], s[1], 0xFCE0, 0xFCFF)]
    assert crossing, "a segment spanning the PEC file went unnoticed"


def test_sfr_and_esfr_overflow_are_detected():
    """The ME7.5 m0 carve-out attempt pushed segments past 0xFDFF into SFR
    space. That is worse than the PEC overlap and must be caught."""
    text = _map(
        [GPR,
         (0x00FDBE, 0x00FE0A, "DATA", "NDATA0", "?ND0?HCVEC"),
         (0x00F1F0, 0x00F1FE, "DATA", "NDATA0", "?ND0?LOWONE")],
        [(0x00FE04, "hc_badvec"), (0x00F1F4, "something_low")])
    vs = G.variables(text)
    assert any(0xFE00 <= a <= 0xFFFF for a, _ in vs), "SFR overflow missed"
    assert any(0xF000 <= a <= 0xF1FF for a, _ in vs), "ESFR overlap missed"


def test_a_clean_map_passes():
    """The negative control. A gate that fails everything proves nothing."""
    text = _map(
        [GPR,
         (0x00FC20, 0x00FCDE, "DATA", "NDATA0", "?ND0?PART2"),
         (0x00FD00, 0x00FDAF, "DATA", "NDATA0", "?ND0?PART3")],
        [(0x00FD30, "hc_asic_state"), (0x00FC74, "adc_raw")])
    vs = G.variables(text)
    segs = G.data_segments(text)
    for lo, hi, _w, _y in G.ARCH_REGIONS:
        assert not [a for a, _ in vs if lo <= a <= hi]
        assert not [s for s in segs
                    if "MAINREGISTERS" not in s[2] and G.overlap(s[0], s[1], lo, hi)]


def test_the_linker_script_range_check_sees_a_hazardous_window():
    """Catches a bad script BEFORE a build happens to place something badly."""
    wide = G.declared_ranges("CLASSES (\n  NDATA0 (0xF700-0xFDFF),\n)")
    assert (0xF700, 0xFDFF) in wide
    assert any(G.overlap(lo, hi, 0xFCE0, 0xFCFF) for lo, hi in wide)

    carved = G.declared_ranges(
        "CLASSES (\n  NDATA0 (0xF700-0xFCDF, 0xFD00-0xFDFF),\n)")
    assert (0xF700, 0xFCDF) in carved and (0xFD00, 0xFDFF) in carved
    assert not any(G.overlap(lo, hi, 0xFCE0, 0xFCFF) for lo, hi in carved)


def test_the_real_me711_linker_script_still_carves_the_pec_file_out():
    """The actual shipped script, not a synthetic one."""
    lnp = (ROOT / "firmware/targets/me711"
           / "linker_me711.lnp").read_text(errors="replace")
    rngs = G.declared_ranges(lnp)
    assert rngs, "no near-data class ranges parsed from the ME7.1.1 script"
    for lo, hi, what, _why in G.ARCH_REGIONS:
        assert not any(G.overlap(a, b, lo, hi) for a, b in rngs), \
            "the ME7.1.1 script offers %s to the allocator again" % what


