#!/usr/bin/env python3
r"""
The physical pin descriptors, checked against Bosch's own documents.

    py -m pytest tests/unit/test_hw_descriptor_evidence.py -q

WHAT THIS REPLACES. The previous test for this area asserted a hand-typed
table against itself - "pin 21 has RELAY_OUT and evidence VERIFIED" against a
row somebody had typed as exactly that. It passed while the table said
connector pin 21 was the J271 main relay on BOTH the ME7.5 and the Bosch
board, and while it routed a V8's injectors 5..8 onto the four LSU lambda-2
wires.

Every test here reads a SOURCE - the extracted connector CSV, the extracted
port map, or the repo's own I/O map - and checks the descriptor against it. A
test whose expected value is only in the file under test proves nothing.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/config_source"))

import hw_descriptors as HW           # noqa: E402
from hanicore_config_schema import EvidenceClass, PinCap  # noqa: E402

CONN_CSV = ROOT / "tools/config_source/data/me71_connector_121.csv"
IOMAP_CSV = ROOT / "tools/config_source/data/me711_iomap.csv"
# ME7.5 is not part of this repository; its I/O map lives in the local ME7.5 archive.
ME75_IOMAP = ROOT.parent / "archive" / "me75_target_2026-10-06" / "docs" / "HANICORE_ENGINE_IO_MAP.md"


@pytest.fixture(scope="module")
def me711():
    return HW.build_me711()


@pytest.fixture(scope="module")
def me75():
    return HW.build_me75()


@pytest.fixture(scope="module")
def connector():
    assert CONN_CSV.exists(), (
        "run tools/config_source/extract_me71_connector.py first")
    return {int(r["pin"]): r for r in csv.DictReader(
        CONN_CSV.open(encoding="utf-8"))}


# ==========================================================================
# 1. one descriptor per board, and they are NOT the same
# ==========================================================================
def test_there_is_more_than_one_descriptor():
    assert len(HW.DESCRIPTORS) >= 2


def test_the_two_boards_disagree_about_a_great_many_pins(me711, me75):
    """The single-table version had 118 of 121 rows identical across both
    ECUs. If these two ever converge again, the portability model has
    collapsed back into one board's pinout asserted about two boards."""
    differing = sum(1 for a, b in zip(me711.pins, me75.pins)
                    if a.capabilities != b.capabilities)
    assert differing > 60, differing


def test_connector_pin_21_is_not_the_oem_main_relay_on_the_me711_board(
        me711, connector):
    """THE HEADLINE CORRECTION SURVIVES - but it is about the OEM FUNCTION,
    not about capability.

    Bosch's own 121-pin sheet puts ZAS2_S on pin 21 and their abbreviation
    list expands ZAS2 as "Zylinderabschaltung 2", cylinder deactivation. The
    old table called it MAIN_RELAY_J271, VERIFIED, on BOTH boards - a ME7.5
    fact copied onto a ME7.1.1 row - and a preset then assigned it as the ECU
    main relay. That is what must never come back.

    THIS ASSERTION HAS BEEN WRITTEN THREE TIMES AND THE HISTORY IS THE POINT.

    First: `not (capabilities & RELAY_OUT)`, because Bosch called the signal
    "Zylinderabschaltung". That was the defect the project rules forbid - an
    OEM name is not an electrical property.

    Then: `capabilities & RELAY_OUT`, because cavity 21 is a CJ420 smart
    low-side channel on the same die as EV7 and EV8, TVS clamped. The right
    rule - capability comes from the DRIVER STAGE - applied to data from
    `Steckerb. ME7.1.XLS`, a VW/Audi ME7.1 C4 workbook.

    Now: no capability at all, because THAT WORKBOOK IS WRONG FOR THIS BLOCK ON
    ME7.1.1. Cavity 21 here is KL15, the ignition-lock feed into the CJ910's
    enable pin, settled by three agreeing sources - Porsche service
    documentation, the ME7.1.1 schematic at 600 dpi, and this ECU on the bench,
    where removing +12 V from cavity 21 while 3 and 62 stay powered takes it
    OFFLINE. It is a POWER INPUT.

    The connector CSV still says ZAS2, because the CSV is what the family
    workbook holds and this test checks that it has not been quietly rewritten.
    The DESCRIPTOR is what the routing asks, and it now says SPECIAL_LOCKED."""
    assert "ZAS2" in connector[21]["signals"]
    assert "Zylinderabschaltung" in connector[21]["bosch_meaning"]
    p = me711.pin(21)
    assert "J271" not in p.oem_name
    assert "J271" not in p.meaning
    assert not (p.capabilities & PinCap.RELAY_OUT)
    assert not (p.capabilities & PinCap.LOW_SIDE)
    assert p.capabilities == PinCap.SPECIAL_LOCKED
    assert "KL15" in p.meaning


def test_connector_pin_121_carries_no_signal_at_all(me711, connector):
    """Bosch's sheet is titled "Maximalumfang" - maximum scope - and pin 121
    is blank in it. The previous table called it "Main Relay Switched Power 2 /
    Secondary Feed (KL87)", VERIFIED."""
    assert connector[121]["assigned"] == "no"
    assert connector[121]["signals"] == ""
    p = me711.pin(121)
    assert p.capabilities == 0
    assert p.hal_resource == ""


def test_the_pins_bosch_leaves_blank_are_left_blank(me711, connector):
    """A cavity the family workbook leaves blank advertises nothing - unless
    the ME7.1.1 schematic itself draws a signal there (cavity 120: the
    second cam-timing valve on main-CPU POUT1). Then that sheet is the
    source, and the property must say so."""
    blank = [n for n, r in connector.items() if r["assigned"] == "no"]
    assert 121 in blank
    for n in blank:
        p = me711.pin(n)
        for prop in p.properties:
            assert "ME7.1.1 SHEET LAYER" in prop.source, (n, prop.source)
            assert prop.evidence is EvidenceClass.PROBABLE, n


def test_there_is_no_spare_io_default(me711, me75):
    """The previous table gave ~60 pins "Spare I/O", DIN|LOW_SIDE, evidence
    UNVERIFIED. That is what let an injector be assigned to almost any pin. An
    undescribed pin must advertise NOTHING."""
    for d in (me711, me75):
        for p in d.pins:
            if not p.properties:
                assert p.capabilities == 0, (d.target_id, p.number)
            for prop in p.properties:
                assert prop.evidence is not EvidenceClass.UNVERIFIED, (
                    d.target_id, p.number)


# ==========================================================================
# 2. the ME7.1.1 descriptor really is derived from Bosch's documents
# ==========================================================================
def test_every_me711_capability_names_its_source(me711):
    """Every capability cites where it came from - the family connector
    workbook, Bosch's port map, or the Porsche override that outranks both.

    The third source is new and it is the STRONGEST: Porsche service
    documentation plus a measurement on this ECU. A test that demanded the
    workbook would have refused evidence better than the workbook's."""
    for p in me711.pins:
        for prop in p.properties:
            assert prop.source, p.number
            assert ("me71_connector_121.csv" in prop.source
                    or "me7_port.xls" in prop.source
                    or "Porsche" in prop.source
                    or "the project rules" in prop.source
                    # THE FOURTH SOURCE, added at V62 and stronger than the
                    # first: the ME7.1.1 sheet itself, read at 330 dpi. It is
                    # what the project rules asked for when it locked
                    # cavities 18..24 - "until the descriptor is regenerated
                    # against ME7.1.1 evidence". A test that demanded the
                    # family workbook would refuse the evidence that settles
                    # the block, which is the same mistake the docstring above
                    # already records about the Porsche override.
                    or "ME7.1.1 SHEET LAYER" in prop.source
                    # the S5500 frame and switch-input decodes: the ASIC ROM
                    # and this ECU's firmware, position bench-confirmed
                    or "ASIC FRAME LAYER" in prop.source
                    or "SWITCH INPUT" in prop.source), prop.source


def test_the_v8_injector_pins_are_bosch_own_EV1_to_EV8(me711, connector):
    """EV1..EV8 in Bosch's connector sheet. The previous preset put injectors
    5..8 on connector pins 15/14/13/12, which this same sheet assigns to
    LS2VK_IP, LS2VK_IA, LS2VK_S and LS2VK_MA - the four wires of the second
    wideband lambda sensor."""
    # EV8 IS CAVITY 19, AND THIS TABLE SAID 23 UNTIL V62.
    #
    # 23 came from the ME7.1 C4 family workbook. `the ME7.1.1 schematic`, the ME7.1.1
    # sheet, draws `A_T_EV8` on cavity **19** and `A_S_HR` - the DME main relay
    # drive - on cavity 23, and `me711_iomap.csv` row 75 gives EV8 a MAIN CPU
    # channel (P8.3/CC19IO) with BOTH ME7.1.1 columns agreeing. the project rules
    # section 10 said the same thing from Porsche documentation before the
    # sheet was ever read.
    #
    # So this board really does have EIGHT injector cavities, and the previous
    # version of this test - which required cavity 24 to advertise NO injector
    # capability - was encoding the LOCK rather than the hazard. The hazard was
    # only ever cavity 23.
    want = {"EV1": 96, "EV2": 97, "EV3": 88, "EV4": 89,
            "EV5": 112, "EV6": 113, "EV7": 24, "EV8": 19}
    for sig, pin in want.items():
        assert me711.pin(pin).capabilities & PinCap.INJ_OUT, pin

    # AND THE ONE THAT MUST NEVER COME BACK: cavity 23 is the main relay.
    assert not (me711.pin(23).capabilities & PinCap.INJ_OUT), (
        "cavity 23 is A_S_HR, the DME main relay drive - offering it as an "
        "injector output is the hazard this test exists for")
    assert "EV8" in connector[23]["signals"].split("|"), (
        "the family workbook still says EV8 on 23, and that is exactly why "
        "the descriptor may not follow it")
    # and the pins the previous data used are lambda wiring, not injectors
    for pin in (15, 14, 13, 12):
        assert "LS2VK" in connector[pin]["signals"]
        assert not (me711.pin(pin).capabilities & PinCap.INJ_OUT), pin


def test_the_v8_ignition_pins_are_bosch_own_ZUE1_to_ZUE8(me711, connector):
    want = {"ZUE1": 102, "ZUE2": 103, "ZUE3": 94, "ZUE4": 95,
            "ZUE5": 110, "ZUE6": 111, "ZUE7": 8, "ZUE8": 7}
    for sig, pin in want.items():
        assert sig in connector[pin]["signals"].split("|"), (sig, pin)
        assert me711.pin(pin).capabilities & PinCap.IGN_OUT, pin
    # the pins the previous data used for coils 5..8
    assert "LS1VK" in connector[51]["signals"]
    assert "LS1VK" in connector[52]["signals"]
    assert connector[53]["signals"] == "5V2"      # a sensor supply
    assert "VFZG" in connector[54]["signals"]     # road speed input
    for pin in (51, 52, 53, 54):
        assert not (me711.pin(pin).capabilities & PinCap.IGN_OUT), pin


def test_the_injector_hal_resources_match_the_firmwares_own_target_header(
        me711):
    """A THIRD source. hctarget.h documents the OEM ME7.1.1's own EV/CAPCOM map, and
    it was written from the same Bosch port map by a different route. If the
    mechanical join in hw_descriptors.py and that hand-written comment ever
    disagree, one of them is wrong."""
    tgt = (ROOT / "firmware/targets/me711/hctarget.h"
           ).read_text(errors="replace")
    assert "EV1 P7.6/CC30" in tgt and "EV8 P8.3/CC19" in tgt
    for pin, port in ((96, "P7.6"), (97, "P7.5"), (88, "P7.4"), (89, "P8.7"),
                      (112, "P8.6"), (113, "P8.5"), (24, "P8.4"), (19, "P8.3")):
        assert me711.pin(pin).hal_resource.startswith(port), (pin, port)


def test_the_ignition_hal_resources_match_the_target_header(me711):
    tgt = (ROOT / "firmware/targets/me711/hctarget.h"
           ).read_text(errors="replace")
    assert "ZDG1 P2.0/CC0" in tgt and "ZDG8 P2.7/CC7" in tgt
    for pin, port in ((102, "P2.0"), (103, "P2.1"), (94, "P2.2"), (95, "P2.3"),
                      (110, "P2.4"), (111, "P2.5"), (8, "P2.6"), (7, "P2.7")):
        assert me711.pin(pin).hal_resource.startswith(port), (pin, port)


def test_temperature_sensors_are_not_claimed_on_the_main_cpu(me711):
    """On this ECU TMOT (93) and TANS (26) belong to the peripheral ASIC and
    reach the CPU only inside the S5500 frame - by the ASIC channel whose ADC
    tag the HAL checks. A main-CPU port or ADC channel here would be a wrong
    reading, not a missing one. Cavity 85 is the brake-booster input (a
    681 k pull-up), not an NTC front end, and stays unroutable."""
    assert me711.pin(93).hal_resource.startswith("ASIC P5.0/AN0")
    assert me711.pin(26).hal_resource.startswith("ASIC P5.1/AN1")
    assert me711.pin(85).hal_resource == "NOT_ON_MAIN_CPU"


def test_the_boost_valve_is_not_claimed_on_the_main_cpu(me711):
    """LDR is the ASIC's P7.2 here, driven by image in the S5500 frame. An
    old table put the boost solenoid on MAIN P7.1, which on this board is
    the second cam-timing valve (cavity 120)."""
    assert me711.pin(104).hal_resource.startswith("ASIC P7.2")
    assert me711.pin(120).hal_resource.startswith("P7.1")


def test_no_me711_connector_claim_is_rated_verified(me711):
    """Bosch's 121-pin workbook is a VW/Audi ME7.1 maximum-scope drawing, not
    a target harness. the maintainer's design records already says so
    about connector pin 43, and the same caution applies to all of them until
    somebody measures continuity on the actual board."""
    # THE LOCKED SET SHRANK AT V62, and only these are still refusals.
    #
    # It was `range(18, 25)`, because cavities 18..24 were locked wholesale
    # pending ME7.1.1 evidence. That evidence arrived - `hw_descriptors`
    # `_ME711_SHEET` - and 18, 19, 22 and 24 now carry real capabilities at
    # PROBABLE, from a same-generation W12 drawing that is not this board.
    # What is left locked: 20 (the sheet does not name it), 21 (KL15, a power
    # input) and 23 (the main relay drive), and those three still rest on
    # Porsche documentation plus a measurement on this ECU, so VERIFIED is
    # still earned for them.
    locked_by_porsche = {20, 21, 23} | {1, 2, 3, 43, 62}
    for p in me711.pins:
        for prop in p.properties:
            if p.number in locked_by_porsche:
                # THE ONE PLACE VERIFIED IS EARNED. These cavities do not rest
                # on the connector workbook at all - they rest on Porsche
                # service documentation, the ME7.1.1 schematic, and a
                # measurement on this ECU, and what they claim is
                # SPECIAL_LOCKED: a refusal to route, not a capability. An
                # unverified refusal would be the wrong way round.
                assert prop.evidence is EvidenceClass.VERIFIED, (
                    p.number, prop.evidence)
                # 23 is the CJ910's own main-relay stage: a hardware function
                # (closes with KL15), routable to MAIN_RELAY in AUTO only.
                want = PinCap.MAIN_RELAY_HW if p.number == 23 else PinCap.SPECIAL_LOCKED
                assert prop.cap == want, p.number
                continue
            assert prop.evidence is EvidenceClass.PROBABLE, (
                p.number, prop.evidence)


def test_but_the_cpu_side_resources_can_be_verified(me711):
    """The port map IS the target's own column in Bosch's own document, so a
    CPU resource derived from it is VERIFIED even while the connector cavity
    is not. Evidence is per property, and these are different properties."""
    verified = [p.number for p in me711.pins
                if p.hal_resource and p.hal_evidence is EvidenceClass.VERIFIED]
    assert len(verified) > 30
    assert 82 in verified and 86 in verified and 87 in verified


# ==========================================================================
# 3. the ME7.5 descriptor quotes the document that outranks the others
# ==========================================================================
def test_every_me75_capability_cites_the_io_map(me75):
    for p in me75.pins:
        for prop in p.properties:
            assert "HANICORE_ENGINE_IO_MAP" in prop.source, p.number


def test_me75_pin_21_is_the_main_relay_and_that_is_the_whole_point(me75):
    """Pin 21 IS the J271 main relay on the ME7.5 board - its own I/O map says
    so. The defect was never this row; it was copying this row onto a Bosch.
    A test that only checked the Bosch side would let the reverse mistake
    back in."""
    p = me75.pin(21)
    assert p.capabilities & PinCap.RELAY_OUT
    assert "J271" in p.oem_name


def test_me75_and_me711_pin_21_are_different_claims(me75, me711):
    """THE TWO BOARDS MEAN OPPOSITE THINGS BY CAVITY 21, and that is the whole
    origin of this project's confusion about it.

    On ME7.5, cavity 21 is `A_S_HR` - the relay coil drive OUT of the ECU, the
    J271 main relay. On the Porsche ME7.1.1, cavity 21 is KL15 - a power feed
    IN. Same connector shell, same cavity number, opposite direction.

    Putting the Porsche ECU on the AWT's ME7.5 harness is therefore a
    RE-PINNING EXERCISE, not a plug-in."""
    assert me75.pin(21).capabilities & PinCap.RELAY_OUT
    assert me711.pin(21).capabilities == PinCap.SPECIAL_LOCKED
    assert "J271" in me75.pin(21).oem_name
    assert "J271" not in me711.pin(21).oem_name
    assert "KL15" in me711.pin(21).meaning


def test_me75_injector_and_coil_pins_come_from_the_io_map(me75):
    """Cross-check against the document, when the document is here.

    docs/PLATFORM.md was purged from this repository by a
    `git filter-branch` rewrite on 2026-09-02 and is not recoverable from git.
    Until somebody restores it from a backup, the ME7.5 descriptor rows below
    have a source string but no source, so this cross-check SKIPS rather than
    passing on nothing - a green tick here would mean the opposite of what it
    says. test_every_me75_row_names_the_same_source_document keeps the rows
    themselves under test in the meantime."""
    if not ME75_IOMAP.exists():
        pytest.skip("%s is missing - restore it and this cross-check runs "
                    "again unchanged" % ME75_IOMAP.name)
    text = ME75_IOMAP.read_text(errors="replace")
    for pin in (96, 97, 88, 89):
        assert me75.pin(pin).capabilities & PinCap.INJ_OUT
        assert f"**{pin}**" in text
    for pin in (102, 103, 94, 95):
        assert me75.pin(pin).capabilities & PinCap.IGN_OUT


def test_every_me75_row_names_the_same_source_document(me75):
    """Runs with or without the document. Every ME7.5 capability must cite ONE
    named source, so that when the file comes back there is exactly one thing
    to check it against - and so a row can never quietly acquire a different
    provenance while the document is away."""
    cited = {prop.source.split(":")[0]
             for p in me75.pins for prop in p.properties}
    assert cited == {HW._ME75_SRC}, cited
    assert HW._ME75_SRC.endswith("HANICORE_ENGINE_IO_MAP.md")


def test_me75_leaves_the_disputed_air_mass_pin_probable(me75):
    """The I/O map states plainly that the two sources disagree about whether
    connector pin 29 is analog AN0 or a frequency on CC17, and refuses to
    resolve it. The descriptor must carry that uncertainty, not erase it."""
    p = me75.pin(29)
    assert p.properties[0].evidence is EvidenceClass.PROBABLE
    assert p.hal_resource == "DISPUTED"


def test_pins_the_me75_io_map_does_not_name_have_no_capability(me75):
    named = {r[0] for r in HW._ME75_ROWS}
    for p in me75.pins:
        if p.number not in named:
            assert p.capabilities == 0, p.number


# ==========================================================================
# 4. evidence is per property, not per pin
# ==========================================================================
def test_a_pin_can_carry_capabilities_at_two_different_evidence_levels():
    """The model must be able to express "this pin is VERIFIED as an analog
    input and PROBABLE as a frequency input". A single per-pin flag cannot."""
    p = HW.PhysicalPin(
        7, "test", "",
        (HW.PinProperty(PinCap.AIN, EvidenceClass.VERIFIED, "src a"),
         HW.PinProperty(PinCap.FREQ_IN, EvidenceClass.PROBABLE, "src b")))
    assert p.capabilities == (PinCap.AIN | PinCap.FREQ_IN)
    assert p.caps_at_least(EvidenceClass.VERIFIED) == PinCap.AIN
    assert p.caps_at_least(EvidenceClass.PROBABLE) == (PinCap.AIN
                                                       | PinCap.FREQ_IN)


def test_an_unknown_bosch_signal_produces_no_capability():
    """The classifier must fail closed. A signal name nobody has expanded is
    not an excuse to guess at a digital input."""
    caps, why = HW.classify("WHAT_IS_THIS_S")
    assert caps == 0 and why == ""


def test_the_classifier_reasons_are_bosch_own_words():
    caps, why = HW.classify("EV3")
    assert caps & PinCap.INJ_OUT
    assert "Einspritzventil" in why
    caps, why = HW.classify("ZUE7")
    assert caps & PinCap.IGN_OUT
    assert "Zuendendstufe" in why


# ==========================================================================
# 5. the extraction really did read the spreadsheet
# ==========================================================================
def test_the_connector_csv_is_regenerable_and_matches(connector):
    """Not a snapshot test: re-run the extractor and compare. If somebody edits
    the CSV by hand this fails, which is the point - the spreadsheet is the
    source. The workbook is Bosch's and is not redistributed: without it this
    check cannot run, and the committed CSV is what the other tests read."""
    import extract_me71_connector as EX
    if not EX.CONNECTOR.exists():
        pytest.skip("needs the Bosch ME7.1 connector workbook (not redistributable)")
    pins = EX.read_connector()
    for n, row in connector.items():
        got = "|".join(pins.get(n, []))
        assert got == row["signals"], n


def test_the_extractor_found_the_whole_connector(connector):
    assert len(connector) == 121
    assigned = sum(1 for r in connector.values() if r["assigned"] == "yes")
    assert assigned >= 110
