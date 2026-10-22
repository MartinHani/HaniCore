"""Every runtime configuration read must use the accessor its field's type
declares.

WHY THIS IS THE RIGHT SHAPE OF CHECK FOR THIS ARCHITECTURE.

Project 2B asks that engine code not scatter raw TunerStudio byte offsets. It
does not: all 29 configuration reads in hcengine.c already go through
generated symbolic constants (CAL_*, CFG_U_*), and hc_cal_u16() does the
big-endian page conversion, so the wire format is confined to the boundary.
Wrapping those in another layer of hc_cfg_engine()-style accessors would add
code and indirection to a part with tens of bytes of near RAM to spare and buy
no safety.

What was genuinely unchecked is the WIDTH. Nothing stopped

    hc_cal_u16(CAL_LOAD_SOURCE)      /* a u8 field */

from compiling. It reads two bytes where one was declared, so the value picks
up the neighbouring field's byte as its high half - and on this page the
neighbour is a different setting entirely. The result is a plausible-looking
number, not a crash, which is the worst kind of wrong. The same mistake in the
other direction, hc_cal_u8() on a u16 field, silently returns the high byte.

hcconfig.h already records every field's type - hcconfig_layout.py refuses to
parse a layout define without one - so the check is just a matter of using it.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths as HCP  # noqa: E402

sys.path.insert(0, str(ROOT / "tools/config_source"))

from hcconfig_layout import parse            # noqa: E402
import hanicore_config_def as CFGDEF          # noqa: E402

SHARED = ROOT / "firmware"
ME711 = ROOT / "firmware/targets/me711"

# Which declared type each scalar accessor is entitled to read.
# There is no hc_cal_s16(): a signed word is read with hc_cal_u16() and cast
# at the call site - same two bytes, so the WIDTH (what this file checks) is
# right either way.
SCALAR = {
    "hc_cal_u8": ("u8",),
    "hc_cal_u16": ("u16", "s16"),
    "hc_cal_set_u8": ("u8",),
    "hc_cal_set_u16": ("u16", "s16"),
    # 2026-10-14: the far modules' variable-offset reads (hcfarinline.h) -
    # the same reads behind one call; held to the same widths
    "hc_cal_u8v": ("u8",),
    "hc_cal_u16v": ("u16", "s16"),
}
# Accessors that take the FIRST element of an array and walk it themselves.
# They must be pointed at a field with more than one element, or they are
# reading a scalar as a table.
ARRAY = {"hc_cal_map", "hc_cal_curve16", "hc_cal_curve8"}

CALL = re.compile(
    r"\b(hc_cal_(?:set_)?(?:u8v|u16v|u8|u16|s16|map|curve16|curve8))\s*\(\s*"
    r"((?:CFG|CAL)_[A-Z0-9_]+)\b")


def _sources():
    files = HCP.sources("me711", "*.c")
    return [f for f in files if "/build/" not in f.as_posix()]


def _slots():
    """Every field the runtime can name, from the RESOLVED model.

    hcconfig.h alone is not enough: it declares the legacy page and the
    universal block's BASE, while the universal fields themselves - every
    CFG_U_* - are generated. resolve() merges both and fails if either side
    has an orphan, so it is the only place that knows all 207.
    """
    fields = CFGDEF.resolve()[0]
    out = {}
    for f in fields:
        out[f.slot] = f
    return out


def _calls():
    out = []
    for f in _sources():
        text = f.read_text(errors="replace")
        # blank comments but keep their newlines: line numbers stay true
        text = re.sub(r"/\*.*?\*/", lambda c: "\n" * c.group().count("\n"),
                      text, flags=re.S)
        for m in CALL.finditer(text):
            line = text[:m.start()].count("\n") + 1
            out.append((f.relative_to(ROOT), line, m.group(1), m.group(2)))
    return out


def test_there_are_configuration_reads_to_check():
    calls = _calls()
    assert len(calls) > 20, (
        "only %d configuration accesses found - the parser is probably wrong, "
        "and a test that checks nothing passes for the wrong reason"
        % len(calls))


def test_no_runtime_read_uses_a_raw_numeric_offset():
    """The Project 2B requirement itself: no scattered byte offsets."""
    raw = re.compile(r"\bhc_cal_(?:set_)?(?:u8|u16|s16|map|curve16|curve8)"
                     r"\s*\(\s*[0-9]")
    bad = []
    for f in _sources():
        text = re.sub(r"/\*.*?\*/", " ", f.read_text(errors="replace"),
                      flags=re.S)
        for m in raw.finditer(text):
            bad.append("%s:%d" % (f.relative_to(ROOT),
                                  text[:m.start()].count("\n") + 1))
    assert not bad, (
        "configuration read at a raw numeric offset: %s - offsets belong in "
        "hcconfig.h, which is the layout authority" % ", ".join(bad[:5]))


def test_every_named_field_actually_exists_in_the_layout():
    slots = _slots()
    unknown = sorted({name for _f, _l, _a, name in _calls()
                      if name not in slots})
    assert not unknown, (
        "read of %s, which hcconfig.h does not declare as a layout field - "
        "either it is a constant being used as an offset or the name is stale"
        % ", ".join(unknown))


def test_scalar_accessors_match_the_declared_width():
    slots = _slots()
    wrong = []
    for f, line, acc, name in _calls():
        if acc not in SCALAR:
            continue
        s = slots.get(name)
        if s is None:
            continue
        if s.ctype not in SCALAR[acc]:
            wrong.append("%s:%d %s(%s) but %s is %s"
                         % (f, line, acc, name, name, s.ctype))
    assert not wrong, (
        "accessor and declared type disagree - this reads the wrong bytes and "
        "returns a plausible number:\n  " + "\n  ".join(wrong))


def _walked():
    """(file, NAME) where a scalar accessor indexes NAME's elements itself:
    hc_cal_u16(NAME + 2u * i). In such a file NAME's element 0 is read too,
    as hc_cal_u16(NAME), and that is an element read, not a table read."""
    idx = re.compile(r"\bhc_cal_(?:set_)?(?:u8|u16)v?\s*\("
                     r"(?:\s*\(unsigned int\))?[\s(]*((?:CFG|CAL)_[A-Z0-9_]+)\s*\+")
    return {(f.relative_to(ROOT), m.group(1)) for f in _sources()
            for m in idx.finditer(f.read_text(errors="replace"))}


def test_scalar_accessors_are_not_pointed_at_arrays():
    """hc_cal_u16(CAL_FUEL_MAP) would return the first two bytes of a table,
    unless the same file walks CAL_FUEL_MAP's elements one by one."""
    slots = _slots()
    walked = _walked()
    assert walked, "no element walk found - the pattern is probably wrong"
    wrong = []
    for f, line, acc, name in _calls():
        if acc not in SCALAR:
            continue
        s = slots.get(name)
        if s is not None and s.count > 1 and (f, name) not in walked:
            wrong.append("%s:%d %s(%s) but %s has %d elements"
                         % (f, line, acc, name, name, s.count))
    assert not wrong, (
        "a scalar accessor is reading a table:\n  " + "\n  ".join(wrong))


def test_table_accessors_are_pointed_at_tables():
    slots = _slots()
    wrong = []
    for f, line, acc, name in _calls():
        if acc not in ARRAY:
            continue
        s = slots.get(name)
        if s is not None and s.count <= 1:
            wrong.append("%s:%d %s(%s) but %s is a single %s"
                         % (f, line, acc, name, name, s.ctype))
    assert not wrong, (
        "a table accessor is reading a scalar - it will walk past the field:\n"
        "  " + "\n  ".join(wrong))


def test_word_fields_are_word_aligned():
    """A u16 at an odd offset is a misaligned access on the C166 and the
    layout audit already refuses it - this keeps that guarantee visible to the
    access-side tests too."""
    slots, _consts = parse()
    bad = [s.name for s in slots
           if s.ctype in ("u16", "s16") and s.offset % 2]
    assert not bad, "misaligned word fields: %s" % ", ".join(bad)


# --------------------------------------------------- the narrow-accessor trap

NARROW = re.compile(
    r"\b(cfg_(?:set_)?u(?:8|16))\s*\(\s*((?:CFG|CAL)_[A-Z0-9_]+)")


def _core_size():
    import re as _re
    h = (ROOT / "firmware/config/hcconfig.h").read_text(
        errors="replace")
    m = _re.search(r"#define\s+HC_CFG_CORE\s+(\d+)", h)
    assert m, "HC_CFG_CORE not found"
    return int(m.group(1))


def test_the_narrow_accessors_are_never_pointed_above_the_near_mirror():
    """cfg_u16() takes an `unsigned char` offset.

    It reads hc_cfg[], the 128-byte near MIRROR of the page, so it physically
    cannot reach the universal block at 2502 and above - it reads
    offset & 0xFF instead and returns a completely different field's value.

    The compiler does warn about this (C192, 'value truncated'), and that
    warning was the only thing standing between a wired-in
    `cfg_u16(CFG_U_DISPLACEMENT_CC)` and a plausible wrong displacement
    feeding the whole air model. A warning in a build log is not a gate.
    """
    core = _core_size()
    slots = _slots()
    bad = []
    for f in _sources():
        text = re.sub(r"/\*.*?\*/", " ", f.read_text(errors="replace"),
                      flags=re.S)
        for m in NARROW.finditer(text):
            s = slots.get(m.group(2))
            if s is not None and s.offset >= core:
                bad.append("%s:%d %s(%s) - offset %d is above HC_CFG_CORE %d"
                           % (f.relative_to(ROOT),
                              text[:m.start()].count("\n") + 1,
                              m.group(1), m.group(2), s.offset, core))
    assert not bad, (
        "a narrow accessor cannot reach these fields and will read the wrong "
        "byte:\n  " + "\n  ".join(bad))


def test_the_air_model_reads_its_inputs_through_the_wide_accessor():
    """The three fields the whole fuel calculation rests on."""
    eng = re.sub(r"/\*.*?\*/", " ",
                 (SHARED / "engine/hcengine.c").read_text(errors="replace"),
                 flags=re.S)
    for slot in ("CFG_U_DISPLACEMENT_CC", "CFG_U_INJ_FLOW_CCMIN",
                 "CFG_U_STOICH_X100"):
        assert re.search(r"hc_cal_u16\s*\(\s*%s" % slot, eng), (
            "%s is not read through hc_cal_u16 - the air model would get a "
            "different field's bytes" % slot)
