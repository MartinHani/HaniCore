#!/usr/bin/env python3
r"""
Does the configuration source of truth actually control anything?

    py -m pytest tests/unit/test_config_source_of_truth.py -q

WHY THESE TESTS LOOK THE WAY THEY DO. The tests this file replaces asserted
that hand-typed data equalled itself:

    assert p18t["injPinCyl"][:4] == [96, 89, 97, 88]

against a table in which somebody had typed exactly that. It cannot fail, and
it did not fail while the same file routed a V8's injectors 5..8 onto the
lambda-2 sensor wiring.

So every test below either

  * MUTATES the model and asserts the cross-check NOTICES - a test that cannot
    be made to fail by breaking the thing it guards is not a test; or
  * checks the model against a DIFFERENT source in the repository, so passing
    means two independent things agree.
"""
from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/config_source"))

import generate_config as GEN          # noqa: E402
import hanicore_config_def as MODEL    # noqa: E402
import hcconfig_layout as LAYOUT       # noqa: E402
from hanicore_config_schema import ApplyPolicy  # noqa: E402

HCCONFIG_H = ROOT / "firmware/config/hcconfig.h"
GENERATED_H = ROOT / "firmware/generated/hc_config_generated.h"


# ==========================================================================
# 1. the model and the firmware header agree, and the check is real
# ==========================================================================
def test_the_model_resolves_against_the_firmware_header():
    fields, consts, problems = MODEL.resolve()
    assert problems == [], "\n".join(problems)
    assert len(fields) > 150
    assert consts["HC_CFG_SIZE"] == 4096


def test_every_firmware_slot_has_metadata_and_the_reverse():
    """Both directions, because either gap is a real defect: a firmware field
    with no metadata is a page byte TunerStudio cannot see, and a metadata
    entry with no firmware field is a control that writes nowhere."""
    slots, _ = LAYOUT.parse()
    fields, _, _ = MODEL.resolve()
    slot_names = {s.name for s in slots} - {"CFG_UNIVERSAL_BASE"}
    model_names = {f.slot for f in fields if not GEN.is_universal(f.slot)}
    assert slot_names == model_names


def test_a_new_firmware_field_without_metadata_is_caught(monkeypatch):
    """MUTATION: pretend hcconfig.h grew a field the model does not know."""
    real_parse = LAYOUT.parse

    def fake_parse(path=LAYOUT.HCCONFIG_H):
        slots, consts = real_parse(path)
        slots = list(slots) + [LAYOUT.Slot("CAL_SOMETHING_NEW", 3020, "u8", 1,
                                           "u8 a field nobody described")]
        slots.sort(key=lambda s: s.offset)
        return slots, consts

    monkeypatch.setattr(LAYOUT, "parse", fake_parse)
    _fields, _consts, problems = MODEL.resolve()
    assert any("CAL_SOMETHING_NEW" in p and "no metadata" in p
               for p in problems), problems


def test_an_offset_that_drifts_is_caught(monkeypatch):
    """MUTATION: move ONE field in the firmware header and prove the generator
    refuses. This is the failure the whole design exists to make impossible -
    a .ini writing a cylinder count into a page-size field."""
    real_parse = LAYOUT.parse

    def fake_parse(path=LAYOUT.HCCONFIG_H):
        slots, consts = real_parse(path)
        moved = []
        for s in slots:
            if s.name == "CFG_SY_GAP":
                moved.append(LAYOUT.Slot(s.name, s.offset + 40, s.ctype,
                                         s.count, s.comment))
            else:
                moved.append(s)
        moved.sort(key=lambda s: s.offset)
        return moved, consts

    monkeypatch.setattr(LAYOUT, "parse", fake_parse)
    fields, _consts, problems = MODEL.resolve()
    # The move lands CFG_SY_GAP on top of another field, and the merged-model
    # overlap scan is what notices.
    assert problems, "moving a field produced no complaint at all"
    assert any("OVERLAP" in p for p in problems), problems


def test_an_overlapping_universal_field_is_caught(monkeypatch):
    """MUTATION: make the universal block bigger than its reservation."""
    extra = MODEL.NewField(
        "CFG_U_BLOAT", "u8", 4096,
        MODEL.Meta("CFG_U_BLOAT", "bloat", "too big", ApplyPolicy.LIVE_APPLY,
                   MODEL.G.GENERAL),
        "u8[4096]")
    monkeypatch.setattr(MODEL, "UNIVERSAL", MODEL.UNIVERSAL + [extra])
    _fields, _consts, problems = MODEL.resolve()
    assert any("universal block needs" in p for p in problems), problems


# ==========================================================================
# 2. the generated C really carries the firmware's offsets
# ==========================================================================
def test_generated_header_repeats_no_offset_it_does_not_own():
    """hc_config_generated.h must NOT redefine hcconfig.h's CFG_*/CAL_* names.
    Two definitions of one offset is the defect, not the fix for it."""
    text = GENERATED_H.read_text()
    slots, _ = LAYOUT.parse()
    legacy = {s.name for s in slots} - {"CFG_UNIVERSAL_BASE"}
    redefined = [n for n in legacy
                 if re.search(r"^#define\s+%s\s" % n, text, re.M)]
    assert redefined == [], redefined


def test_generated_header_asserts_every_legacy_offset_at_compile_time():
    """The C compiler is the cross-check. Every legacy field must have a
    negative-array-size assertion naming its offset, so a moved field fails
    the BUILD rather than the review."""
    text = GENERATED_H.read_text()
    fields, _, _ = MODEL.resolve()
    missing = []
    for f in fields:
        if GEN.is_universal(f.slot):
            continue
        want = "hc_cfg_assert_%s[(%s == %du) ? 1 : -1]" % (
            f.slot.lower(), f.slot, f.offset)
        if want not in text:
            missing.append(f.slot)
    assert missing == [], missing[:10]


def test_universal_offsets_are_inside_the_reservation():
    fields, _, _ = MODEL.resolve()
    base = GEN._raw_define("CFG_UNIVERSAL_BASE")
    size = GEN._raw_define("CFG_UNIVERSAL_SIZE")
    for f in fields:
        if not GEN.is_universal(f.slot):
            continue
        assert base <= f.offset and f.end <= base + size, f.slot


# ==========================================================================
# 3. the page is completely described
# ==========================================================================
def test_every_byte_of_the_page_is_owned():
    fields, consts, _ = MODEL.resolve()
    base = GEN._raw_define("CFG_UNIVERSAL_BASE")
    size = GEN._raw_define("CFG_UNIVERSAL_SIZE")
    assert GEN.coverage(fields, consts["HC_CFG_SIZE"], base, size) == []


def test_no_two_fields_share_a_tunerstudio_name():
    fields, _, _ = MODEL.resolve()
    names = [f.meta.ts for f in fields]
    dupes = {n for n in names if names.count(n) > 1}
    assert dupes == set(), dupes


def test_every_16_bit_field_is_even_aligned():
    fields, _, _ = MODEL.resolve()
    bad = [f.slot for f in fields if f.ctype in ("u16", "s16") and f.offset % 2]
    assert bad == [], bad


# ==========================================================================
# 4. apply policy and SAFETY_CRITICAL are orthogonal, and used
# ==========================================================================
def test_safety_critical_is_not_an_apply_policy():
    """It must be possible to say LIVE_APPLY *and* safety critical, and
    RESTART_REQUIRED *and* safety critical. If SAFETY_CRITICAL were a member
    of ApplyPolicy, one of those would be inexpressible."""
    assert "SAFETY" not in {p.name for p in ApplyPolicy}
    fields, _, _ = MODEL.resolve()
    live_crit = [f for f in fields
                 if f.meta.apply is ApplyPolicy.LIVE_APPLY
                 and f.meta.safety_critical]
    restart_crit = [f for f in fields
                    if f.meta.apply is ApplyPolicy.RESTART_REQUIRED
                    and f.meta.safety_critical]
    zero_crit = [f for f in fields
                 if f.meta.apply is ApplyPolicy.RPM_ZERO_APPLY
                 and f.meta.safety_critical]
    assert live_crit and restart_crit and zero_crit
    # and the combination this project actually needs
    oil = [f for f in fields if f.meta.ts == "oilPressMinKpa"][0]
    assert oil.meta.apply is ApplyPolicy.LIVE_APPLY
    assert oil.meta.safety_critical is True


@pytest.mark.parametrize("ts_name,policy", [
    # the examples the architecture brief names, one by one
    # Was "fuelMap" when the table held a byte of PULSE WIDTH at 32 us per
    # count. It is now VOLUMETRIC EFFICIENCY at 0.5 % per count and the fuel
    # comes from an air model, so the TunerStudio name changed with it - a
    # table whose name still said "fuel" while holding VE would be the same
    # class of mislabelling this suite exists to catch. Still LIVE_APPLY: a
    # tuner changes a VE cell with the engine running and expects it to take.
    ("veTable", ApplyPolicy.LIVE_APPLY),
    ("ignMap", ApplyPolicy.LIVE_APPLY),
    ("injPin", ApplyPolicy.RPM_ZERO_APPLY),
    ("ignPin", ApplyPolicy.RPM_ZERO_APPLY),
    ("trigEdge", ApplyPolicy.RPM_ZERO_APPLY),
    ("cylinders", ApplyPolicy.RESTART_REQUIRED),
])
def test_named_fields_have_the_policy_the_architecture_requires(ts_name, policy):
    fields, _, _ = MODEL.resolve()
    f = [x for x in fields if x.meta.ts == ts_name]
    assert f, ts_name
    assert f[0].meta.apply is policy


def test_anything_that_changes_what_an_output_means_is_not_live():
    """A blanket rule rather than a list, so a NEW routing field cannot be
    added as LIVE_APPLY by accident."""
    fields, _, _ = MODEL.resolve()
    offenders = [f.slot for f in fields
                 if f.meta.is_pin and f.meta.apply is ApplyPolicy.LIVE_APPLY]
    assert offenders == [], offenders


def test_outputs_armed_can_never_be_set_under_a_running_engine():
    """BY THE CONFIG KEY, NOT BY THE TUNERSTUDIO NAME.

    This looked the field up as `outputsArmed` and broke the day that name
    became `outputsArmedCfg` - which it had to, because TunerStudio shares one
    namespace between [Constants] and [OutputChannels] and `outputsArmed` is
    also a runtime channel. A TunerStudio name is presentation and may be
    renamed for the UI's sake; CFG_OUTPUTS_ARMED is the identity, and a safety
    assertion must key off the thing that cannot move."""
    fields, _, _ = MODEL.resolve()
    f = [x for x in fields if x.meta.slot == "CFG_OUTPUTS_ARMED"][0]
    assert f.meta.apply is ApplyPolicy.RPM_ZERO_APPLY
    assert f.meta.safety_critical is True


# ==========================================================================
# 5. the universal model is not shaped around one engine
# ==========================================================================
def test_nothing_in_the_model_hardcodes_four_six_or_eight_cylinders():
    """The per-cylinder arrays must reach HC_MAX_CYL_UNIVERSAL. The legacy
    arrays stay 8 wide - moving them would break every flashed image - and the
    universal block carries 9..12."""
    fields, consts, _ = MODEL.resolve()
    by_ts = {f.meta.ts: f for f in fields}
    assert by_ts["injPin"].count == MODEL.MAX_CYL_UNIVERSAL
    assert by_ts["ignPin"].count == MODEL.MAX_CYL_UNIVERSAL
    assert by_ts["cylBank"].count == MODEL.MAX_CYL_UNIVERSAL
    assert by_ts["tdcCylDegX10"].count == consts["HC_MAX_CYL"]
    assert (by_ts["tdcCylExtDegX10"].count
            == MODEL.MAX_CYL_UNIVERSAL - consts["HC_MAX_CYL"])


def test_generic_io_is_not_capped_at_four():
    """The brief is explicit that an arbitrary four-channel limit must not be
    baked into the architecture."""
    assert MODEL.N_GENERIC >= 8
    fields, _, _ = MODEL.resolve()
    by_ts = {f.meta.ts: f for f in fields}
    for name in ("pinGenericAin", "pinGenericPwm", "pinGenericOut"):
        assert by_ts[name].count == MODEL.N_GENERIC


def test_both_lambda_channels_are_symmetrical():
    """Neither channel may be "the" sensor with the other bolted on."""
    fields, _, _ = MODEL.resolve()
    by_ts = {f.meta.ts: f for f in fields}
    for a, b in (("lambda1Source", "lambda2Source"),
                 ("lambda1Bank", "lambda2Bank"),
                 ("lambda1AuthPct", "lambda2AuthPct"),
                 ("lambda1CylMask", "lambda2CylMask")):
        assert by_ts[a].ctype == by_ts[b].ctype
        assert by_ts[a].count == by_ts[b].count
        assert by_ts[a].meta.apply is by_ts[b].meta.apply
        assert by_ts[a].meta.safety_critical == by_ts[b].meta.safety_critical


def test_the_canonical_fuel_target_relationship_exists_exactly_once():
    """AFR and lambda are related through ONE configured number. If a second
    stoichiometric constant appeared, two subsystems could disagree about what
    lambda 1.00 means."""
    fields, _, _ = MODEL.resolve()
    stoich = [f for f in fields if "stoich" in f.meta.ts.lower()]
    assert len(stoich) == 1
    assert stoich[0].meta.ts == "stoichAfrX100"
    assert stoich[0].meta.safety_critical is True


# ==========================================================================
# 6. representation
# ==========================================================================
def test_temperature_axes_are_signed_through_their_translate():
    """hcconfig.h stores temperatures in 0.1 degC with CAL_TEMP_BIAS (1000 C)
    added, raw = 10 * C + 10000, so a u16 carries negative temperatures. The
    model must express that as scale 0.1 / translate -CAL_TEMP_BIAS, or
    TunerStudio shows a 1000-degree offset."""
    h = (ROOT / "firmware/config/hcconfig.h").read_text(errors="replace")
    bias = int(re.search(r"#define\s+CAL_TEMP_BIAS\s+(\d+)", h).group(1))
    fields, _, _ = MODEL.resolve()
    temps = [f for f in fields if f.meta.units == "C"]
    assert len(temps) > 5, "no temperature fields found"
    for f in temps:
        assert f.meta.scale == pytest.approx(0.1), f.slot
        assert f.meta.translate == pytest.approx(-float(bias)), f.slot


def test_signed_fields_use_a_signed_type():
    """A spark retard is negative. Storing it unsigned and hoping the reader
    subtracts a bias is how a retard becomes an advance."""
    fields, _, _ = MODEL.resolve()
    for f in fields:
        if f.meta.lo < 0:
            assert f.ctype.startswith("s"), f.slot


def test_no_field_range_can_overflow_its_own_storage():
    fields, _, _ = MODEL.resolve()
    for f in fields:
        if f.ctype == "u8":
            lo, hi = 0, 255
        elif f.ctype == "u16":
            lo, hi = 0, 65535
        else:
            lo, hi = -32768, 32767
        assert lo <= f.meta.lo <= hi, f.slot
        assert lo <= f.meta.hi <= hi, f.slot
        assert f.meta.lo <= f.meta.hi, f.slot


def test_lambda_and_voltage_resolution_are_fine_enough_to_tune_with():
    """0.01 on a lambda target is 0.15 AFR at stoich - too coarse to see a
    closed-loop trim. The page stores the mixture target as AFR x 10 for the
    firmware that already reads it, so what matters here is that the
    stoichiometric ratio carries two decimals, which makes the lambda
    conversion exact to 1 part in 1470."""
    fields, _, _ = MODEL.resolve()
    by_ts = {f.meta.ts: f for f in fields}
    assert by_ts["stoichAfrX100"].meta.scale == pytest.approx(0.01)
    # battery axis for dwell: 0.01 V
    assert by_ts["dwellBattAx"].meta.scale == pytest.approx(0.01)
    # dwell itself: 0.01 ms - 10 us, well inside coil tolerance
    assert by_ts["dwellBattVal"].meta.scale == pytest.approx(0.01)
    # ignition advance: 0.1 degree
    assert by_ts["ignAdvanceDegX10"].meta.scale == pytest.approx(0.1)


# ==========================================================================
# 7. the TunerStudio view comes from the same model
# ==========================================================================
def test_every_generated_ini_line_carries_the_model_offset():
    lines = GEN.universal_ini_lines()
    got = {}
    for line in lines:
        m = re.match(r"\s+(\w+)\s*=\s*(?:scalar|array|bits),\s*\w+,\s*(\d+)",
                     line)
        if m:
            got[m.group(1)] = int(m.group(2))
    fields, _, _ = MODEL.resolve()
    for f in fields:
        if GEN.is_universal(f.slot):
            assert got.get(f.meta.ts) == f.offset, f.slot


def test_the_generated_ini_declares_the_unused_tail_of_the_reservation():
    """Otherwise TunerStudio has a hole in the page and ts_ini_check.py's
    "page fully covered" check has nothing to find there."""
    lines = GEN.universal_ini_lines()
    base = GEN._raw_define("CFG_UNIVERSAL_BASE")
    tail = GEN._raw_define("CFG_UNIVERSAL_SIZE") - MODEL.universal_size(base)
    # 2026-10-15: the injector pressure compensation filled the block to the
    # byte - a FULL block has no tail, and must not declare one
    assert any("uniReserved" in line for line in lines) == (tail > 0), tail


# ==========================================================================
# 8. the offset-9 class of bug, specifically
# ==========================================================================
def test_no_tunerstudio_name_can_land_on_another_fields_bytes():
    """THE OFFSET-9 REGRESSION.

    The first Project 2A .ini declared `cylinderCount` at offset 9. In the
    firmware, offset 9 is the HIGH BYTE of cylinder 3's TDC angle inside
    CFG_TDC_CYL (u16[8] at 4..19). Setting a cylinder count through that file
    would have written into a cylinder's ignition timing.

    The mechanism that prevents it is that every offset now comes from
    hcconfig.h. This test states the consequence directly, so the property is
    checked even if somebody later reintroduces a hand-written offset table."""
    fields, consts, _ = MODEL.resolve()
    owner = {}
    for f in fields:
        for b in range(f.offset, f.end):
            assert b not in owner, (
                "byte %d claimed by both %s and %s" % (b, owner[b], f.slot))
            owner[b] = f.slot
    # the specific historical collision
    assert owner[9] == "CFG_TDC_CYL"
    cylinders = [f for f in fields if f.meta.ts == "cylinders"][0]
    assert cylinders.offset == 2, cylinders.offset
    assert cylinders.offset != 9


def test_the_cylinder_count_field_is_where_the_firmware_reads_it():
    """Belt and braces: read the offset straight out of hcconfig.h rather than
    through the model, so this fails even if the model itself is wrong."""
    import re
    text = HCCONFIG_H.read_text(errors="replace")
    m = re.search(r"^#define\s+CFG_CYLINDERS\s+(\d+)", text, re.M)
    assert m, "CFG_CYLINDERS not found in hcconfig.h"
    assert int(m.group(1)) == 2
    fields, _, _ = MODEL.resolve()
    assert [f for f in fields if f.meta.ts == "cylinders"][0].offset == 2


def test_the_dangerous_old_ini_is_not_loadable_as_an_ini():
    """It is kept for inspection, but it must not sit in the TunerStudio
    directory under a name TunerStudio will offer to open."""
    ts = ROOT / "tunerstudio"
    hist = ts / "history"
    assert not (ts / "hanicore_universal.ini").exists()
    assert not (hist / "hanicore_universal.ini").exists()
    if hist.is_dir():                   # the maintainer's history, kept locally
        assert (hist / "hanicore_universal.ini.DO_NOT_LOAD").exists()
        assert (hist / "README_hanicore_universal.md").exists()


def test_lambda_is_the_canonical_fuel_target_in_the_runtime():
    """The page stores the mixture target as AFR x 10 because that is the
    layout every flashed image has. The RUNTIME's canonical value must still be
    lambda, converted once through the one configured stoichiometric ratio."""
    eng = (ROOT / "firmware/engine/hcengine.c").read_text(errors="replace")
    hdr = (ROOT / "firmware/engine/hcengine.h").read_text(errors="replace")
    assert "eng_lambda_x1000" in hdr, "no canonical lambda target is published"
    assert "CFG_U_STOICH_X100" in eng, "lambda is not derived from the config"
    # eng_lambda_x1000 is a FUNCTION, not a stored variable. Two bytes of near
    # RAM are not a rounding error on this part: those exact two bytes pushed
    # the ME7.5 m0 build one byte past what the C167 has once the PEC pointer
    # file is honoured. See tests/firmware/build/near_ram_hazard_proof.py.
    assert "unsigned int eng_lambda_x1000(void)" in eng,         "lambda must be derived, not stored"
    assert "unsigned int  eng_lambda_x1000;" not in eng,         "lambda is stored again - it costs near RAM this part does not have"
    # The conversion must use a 32-bit intermediate: at the stoichiometric
    # point the numerator is 147 * 10000 = 1 470 000, which does not fit in 16
    # bits and would silently wrap.
    # The function is the last thing in the file, so its body runs to the end;
    # do not slice a window, the explanatory comment above the arithmetic is
    # longer than any window worth guessing at.
    body = eng.split("unsigned int eng_lambda_x1000(void)")[1]
    assert "10000uL" in body, "no lambda conversion found in the body"
    assert "unsigned long" in body, "16-bit intermediate would wrap"
