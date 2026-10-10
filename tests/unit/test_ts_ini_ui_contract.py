#!/usr/bin/env python3
r"""
test_ts_ini_ui_contract.py - prove the UI gate catches the defects that
actually reached hardware.

    py -m pytest tests/unit/test_ts_ini_ui_contract.py -q

The two defects are not invented for this test. They are the exact lines that
were in the frozen V29 .ini on 2026-09-02 when the bench pressed "window at
word 12" and nothing went out on the wire:

    field = "me711_s5500_static_map puts coolant at word 21-23 and    <- no "
    field = "window base", s5500Base                                  <- channel

TunerStudio reported, at .ini LOAD time, "open-ended String" and four
"invalid Constant" lines, then "EcuParameter not found" when the dialog opened.

A gate that has never been seen to fail is a gate nobody should trust, so each
rule is re-created here from a KNOWN-GOOD .ini and must go red - and the
known-good .ini must go green, which is what stops this being satisfied by a
checker that always fails.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import ts_ini_ui_contract as C          # noqa: E402

GOOD = ROOT / "tunerstudio/hanicore_me711.ini"
FROZEN_V29 = (ROOT / "release/Porsche_ME711_V29_PHYSICAL_TEST"
              / "hanicore_me711_v29.ini")


def audit_text(tmp_path, text, name="mutant.ini"):
    p = tmp_path / name
    p.write_text(text, encoding="ascii", errors="replace")
    return C.audit(p)[1]


def good_text():
    return GOOD.read_text(errors="replace")


# The developer pages (I/O chip window, RAM probe, Burn forensics) are only in
# the forensic project; the mutations that edit them use that file.
DEV = sorted((ROOT / "tunerstudio").glob("*_forensic.ini"))[0]


def dev_text():
    return DEV.read_text(errors="replace")


def test_the_generated_ini_is_clean():
    assert C.audit(GOOD)[1] == []


def test_the_forensic_ini_is_clean():
    assert C.audit(DEV)[1] == []


def test_an_unterminated_label_is_caught(tmp_path):
    line = '      field = "Normal operation needs base 4. After each move read s5500Idx:"'
    good = dev_text()
    assert line in good, "the mutation anchor is gone - re-anchor it"
    t = good.replace(line, line[:-1], 1)
    msgs = [m for _n, m in audit_text(tmp_path, t)]
    assert any("open-ended String" in m for m in msgs), msgs


def test_an_output_channel_in_a_field_is_caught(tmp_path):
    # The V29 line, verbatim. (V89: s5500Base is shown as a readout now.)
    t = good_text().replace('      readout = s5500BaseGauge',
                            '      field = "window base", s5500Base', 1)
    msgs = [m for _n, m in audit_text(tmp_path, t)]
    assert any("OUTPUT CHANNEL" in m and "s5500Base" in m for m in msgs), msgs


def test_a_button_with_no_command_is_caught(tmp_path):
    t = dev_text().replace("cmdS5500Win12", "cmdS5500Win12Typo", 1)
    assert "cmdS5500Win12Typo" in t, "the mutation found no cmdS5500Win12"
    msgs = [m for _n, m in audit_text(tmp_path, t)]
    assert any("not defined in [ControllerCommands]" in m
               for m in msgs), msgs


def test_a_gauge_with_no_definition_is_caught(tmp_path):
    t = good_text().replace("      readout = s5500IdxGauge",
                            "      readout = s5500IdxGaugeTypo", 1)
    msgs = [m for _n, m in audit_text(tmp_path, t)]
    assert any("not defined in [GaugeConfigurations]" in m for m in msgs), msgs


def test_a_menu_pointing_at_no_dialog_is_caught(tmp_path):
    # The entry is a groupChildMenu since the V89 rusEFI pass (Controller /
    # Developer diagnostics); mutate whichever keyword carries it.
    t = dev_text().replace('Menu = hcS5500, ', 'Menu = hcS5500Typo, ', 1)
    assert 'hcS5500Typo' in t, 'the mutation found no hcS5500 menu entry'
    msgs = [m for _n, m in audit_text(tmp_path, t)]
    assert any("not defined" in m and "hcS5500Typo" in m for m in msgs), msgs


def test_a_table_editing_a_nonexistent_constant_is_caught(tmp_path):
    t = good_text().replace("      zBins = veTable", "      zBins = veTabel", 1)
    msgs = [m for _n, m in audit_text(tmp_path, t)]
    assert any("not a page Constant" in m for m in msgs), msgs


def test_a_datalog_entry_for_no_channel_is_caught(tmp_path):
    t = good_text().replace('   entry = RPMValue, "RPM"', '   entry = rpmm, "RPM"', 1)
    msgs = [m for _n, m in audit_text(tmp_path, t)]
    assert any("datalog entry" in m for m in msgs), msgs


def test_the_frozen_v29_ini_still_shows_the_hardware_failure():
    """The evidence itself. If this ever goes green, either the frozen package
    was edited - which it must not be - or the gate stopped checking."""
    if not FROZEN_V29.exists():
        import pytest
        pytest.skip("the frozen V29 package is not present on this machine")
    msgs = [m for _n, m in C.audit(FROZEN_V29)[1]]
    assert any("open-ended String" in m for m in msgs), msgs
    assert sum("OUTPUT CHANNEL" in m for m in msgs) == 4, msgs


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
