#!/usr/bin/env python3
r"""
ts_ini_ui_contract.py - does every UI reference in the .ini resolve the way
TunerStudio resolves it?

    py tests\tunerstudio\ts_ini_ui_contract.py                     # the live ME7.1.1 .ini
    py tests\tunerstudio\ts_ini_ui_contract.py <file.ini> [...]    # any .ini, e.g. a frozen one

WHY THIS EXISTS - A REAL HARDWARE FAILURE, 2026-09-02.

The frozen V29 package went to the bench and TunerStudio stayed online at
57600. The S5500 window-sweep dialog opened. Pressing "window at word 12" did
nothing: the window base stayed at 4, and NO S5500 COMMAND WENT OUT ON THE
WIRE. The firmware was never reached.

TunerStudio's own log said why, and it said it at LOAD time:

    open-ended String  (around line 588)
    invalid Constant 's5500Base'
    invalid Constant 's5500Idx'
    invalid Constant 's5500Snaps'
    invalid Constant 's5500Plaus'
  ... and when the dialog opened:
    EcuParameter 's5500Base' not found        (and the other three)

TWO DEFECTS, both in the generated .ini, neither visible to any existing gate:

 1. A LABEL LINE HAD NO CLOSING QUOTE. `field = "…word 21-23 and` ran on into
    the following lines, so everything after it - including the ten
    commandButtons - was inside a string.

 2. OUTPUT CHANNELS WERE USED AS `field`. In TunerStudio, `field = "label",
    name` binds an EcuParameter, which is a CONSTANT on a settings page.
    s5500Base and friends are OutputChannels. A dialog shows a live output
    channel with `gauge = <gaugeName>`, against a gauge defined in
    [GaugeConfigurations] - see rusEFI .../rusefi_cypress.ini, which
    does this everywhere and never puts an output channel in a `field`.

WHY THE EXISTING GATES MISSED IT. check_hanicore_ts_ini_syntax.py and
ts_ini_check.py both compare the .ini against the FIRMWARE - offsets, sizes,
command letters. Both were green. Neither had any model of what TunerStudio
does with a dialog, so a .ini can satisfy the firmware perfectly and still be
un-loadable. That is the same shape as every other artefact-pair defect this
project has paid for: two things that must agree, and nothing that makes them.

WHAT THIS CHECKS - the .ini against ITSELF, with TunerStudio's namespace rules:

    every quoted string on a line is closed
    field  = "label", X    ->  X is a page Constant           (NOT a channel)
    gauge  = X             ->  X is defined in [GaugeConfigurations]
    <name>Gauge = SRC,...  ->  SRC is an OutputChannel
    commandButton = "l", C ->  C is defined in [ControllerCommands]
    subMenu/panel = D      ->  D is a dialog defined in [UserDefined]
    indicator = { expr }   ->  every name in expr is an OutputChannel
    [Datalog] entry = X    ->  X is an OutputChannel
    [FrontPage] gaugeN     ->  that gauge is defined

WHAT IT IS NOT. It is not TunerStudio. It encodes the rules that TunerStudio's
own error messages and the rusEFI reference .ini demonstrate; a rule
TunerStudio has that is not written here will still get through. When the bench
finds another one, ADD IT HERE - that is the whole point of the file.

tests/unit/test_ts_ini_ui_contract.py mutates a good .ini back into each of the two
real V29 defects and proves this tool goes red for both.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# THE DIALOG SECTION HAS TWO LEGAL SPELLINGS. TunerStudio 3.3.01 loads
# [UserDefined] with a deprecation warning and names [UiDialogs] as the
# replacement; rusEFI's own .junie/ts-help-topic.md documents both. A gate
# that knew only one spelling would refuse the file the ECU is meant to get.
DIALOG_SECTIONS = ("[UserDefined]", "[UiDialogs]")

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / "tunerstudio/hanicore_me711.ini"


def strip_comment(line: str) -> str:
    """TunerStudio treats ';' as a comment - but not inside a string."""
    out, inq = [], False
    for ch in line:
        if ch == '"':
            inq = not inq
        if ch == ";" and not inq:
            break
        out.append(ch)
    return "".join(out)


class Ini:
    def __init__(self, text: str, name: str = "<ini>"):
        self.name = name
        self.lines = text.splitlines()
        self.constants = set()      # page variables: `field` may bind these
        self.channels = set()       # [OutputChannels]: gauges/indicators/log
        self.gauges = set()         # [GaugeConfigurations] names
        self.gauge_src = {}         # gauge -> the channel it displays
        self.commands = set()       # [ControllerCommands]
        self.dialogs = set()        # dialog / panel ids
        self.panels = set()
        self.bins = []              # (lineno, constant) in editors
        self.pc_arrays = set()      # [PcVariables] arrays (TunerStudio-only)
        self.unclosed = []          # (lineno, text)
        self._scan()

    def _scan(self):
        section = ""
        for n, raw in enumerate(self.lines, 1):
            if raw.count('"') % 2:
                self.unclosed.append((n, raw.strip()))
            line = strip_comment(raw).strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line
                continue
            if section == "[Constants]":
                m = re.match(r"(\w+)\s*=\s*(scalar|bits|array|string)\b", line)
                if m:
                    self.constants.add(m.group(1))
            elif section == "[PcVariables]":
                m = re.match(r"(\w+)\s*=\s*array\b", line)
                if m:
                    self.pc_arrays.add(m.group(1))
            elif section == "[OutputChannels]":
                m = re.match(r"(\w+)\s*=", line)
                if m and m.group(1) not in ("ochGetCommand", "ochBlockSize"):
                    self.channels.add(m.group(1))
            elif section == "[GaugeConfigurations]":
                m = re.match(r"(\w+)\s*=\s*(\w+)\s*,", line)
                if m:
                    self.gauges.add(m.group(1))
                    self.gauge_src[m.group(1)] = m.group(2)
            elif section == "[ControllerCommands]":
                m = re.match(r"(\w+)\s*=\s*\"", line)
                if m:
                    self.commands.add(m.group(1))
            elif section in DIALOG_SECTIONS:
                m = re.match(r"(dialog|indicatorPanel|readoutPanel)\s*=\s*(\w+)", line)
                if m:
                    self.dialogs.add(m.group(2))
            elif section == "[TableEditor]":
                # `table = <panel id>, <map3d id>, "title", page`. BOTH names
                # become referenceable UI elements: rusEFI panels the first and
                # puts the second in its menu.
                m = re.match(r"table\s*=\s*(\w+)\s*,\s*(\w+)", line)
                if m:
                    self.dialogs.add(m.group(1))
                    self.dialogs.add(m.group(2))
                m = re.match(r"([xyz])Bins\s*=\s*(\w+)", line)
                if m:
                    self.bins.append((n, m.group(2)))
            elif section == "[CurveEditor]":
                m = re.match(r"curve\s*=\s*(\w+)", line)
                if m:
                    self.dialogs.add(m.group(1))
                m = re.match(r"([xy])Bins\s*=\s*(\w+)", line)
                if m:
                    self.bins.append((n, m.group(2)))


def names_in(expr: str) -> set:
    """Identifiers in a TunerStudio expression, minus numbers and keywords."""
    return {t for t in re.findall(r"[A-Za-z_]\w*", expr)}


def audit(path: Path):
    ini = Ini(path.read_text(errors="replace"), path.name)
    problems = []

    def bad(n, msg):
        problems.append((n, msg))

    for n, txt in ini.unclosed:
        bad(n, "open-ended String - odd number of quotes: %s" % txt[:70])

    section = ""
    for n, raw in enumerate(ini.lines, 1):
        line = strip_comment(raw).strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line
            continue

        m = re.match(r"field\s*=\s*\"[^\"]*\"\s*,\s*([A-Za-z_]\w*)", line)
        if m:
            nm = m.group(1)
            if nm not in ini.constants:
                if nm in ini.channels:
                    bad(n, "field binds '%s', which is an OUTPUT CHANNEL. "
                           "TunerStudio will report `invalid Constant` and "
                           "`EcuParameter not found`. Use a gauge." % nm)
                else:
                    bad(n, "field binds '%s', which is not a page Constant"
                        % nm)

        # V89: a `readout` in a readoutPanel names a gauge exactly as a
        # `gauge` line does - the diagnostics dialogs now show their channels
        # that way, so an unchecked readout would be an unchecked value.
        m = re.match(r"(?:gauge|readout)\s*=\s*([A-Za-z_]\w*)", line)
        if m and section in DIALOG_SECTIONS:
            if m.group(1) not in ini.gauges:
                bad(n, "gauge '%s' is not defined in [GaugeConfigurations]"
                    % m.group(1))

        m = re.match(r"commandButton\s*=\s*\"[^\"]*\"\s*,\s*([A-Za-z_]\w*)",
                     line)
        if m and m.group(1) not in ini.commands:
            bad(n, "commandButton refers to '%s', which is not defined in "
                   "[ControllerCommands] - the button will do nothing"
                % m.group(1))

        # `std_*` are TunerStudio's OWN built-in entries - std_separator,
        # std_ms3SdConsole and friends. rusEFI's generated .ini, which loads,
        # uses std_separator thirty times without declaring it anywhere, so a
        # gate that demanded a declaration would refuse its own corpus.
        m = re.match(r"(?:subMenu|groupChildMenu|panel)\s*=\s*([A-Za-z_]\w*)",
                     line)
        if m and m.group(1).startswith("std_"):
            m = None
        if m and m.group(1) not in ini.dialogs:
            bad(n, "menu/panel refers to dialog '%s', which is not defined"
                % m.group(1))

        if line.startswith("indicator") and "{" in line:
            expr = line[line.index("{") + 1:line.index("}")]
            for nm in names_in(expr) - ini.channels:
                bad(n, "indicator expression uses '%s', which is not an "
                       "output channel" % nm)

        if section == "[Datalog]":
            m = re.match(r"entry\s*=\s*([A-Za-z_]\w*)", line)
            if m and m.group(1) not in ini.channels:
                bad(n, "datalog entry '%s' is not an output channel"
                    % m.group(1))

        if section == "[FrontPage]":
            m = re.match(r"gauge\d+\s*=\s*([A-Za-z_]\w*)", line)
            if m and m.group(1) not in ini.gauges:
                bad(n, "front page gauge '%s' is not defined" % m.group(1))

    # A table or curve edits PAGE CONSTANTS. A misspelled bin is a map editor
    # that opens on nothing, which looks like a firmware fault from the driver's
    # seat.
    # A [PcVariables] ARRAY is a legal bin too: TunerStudio keeps it on the
    # PC and VE/WUE Analyze writes it. Evidence: every one of rusEFI's 40
    # generated .ini files declares wueAnalRecommend / wueAfrTargetOffset in
    # [PcVariables] and binds them as curve yBins (rusefi_proteus_f7.ini:
    # 4156-4157, 4649, 4658) - files that load in TunerStudio.
    for n, nm in ini.bins:
        if nm not in ini.constants and nm not in ini.pc_arrays:
            bad(n, "editor bins '%s', which is not a page Constant" % nm)

    for g, src in ini.gauge_src.items():
        if src not in ini.channels:
            bad(0, "gauge '%s' displays '%s', which is not an output channel"
                % (g, src))

    return ini, problems


def main(argv) -> int:
    paths = [Path(a) for a in argv[1:]] or [DEFAULT]
    print("=== HaniCore - does TunerStudio's own namespace resolve? ===\n")
    total = 0
    for p in paths:
        if not p.exists():
            print("  MISSING %s" % p)
            total += 1
            continue
        ini, problems = audit(p)
        print("  %s" % p)
        print("     %d constants, %d output channels, %d gauges, "
              "%d commands, %d dialogs"
              % (len(ini.constants), len(ini.channels), len(ini.gauges),
                 len(ini.commands), len(ini.dialogs)))
        for n, msg in problems:
            print("     [FAIL] line %-5s %s" % (n or "-", msg))
        if not problems:
            print("     [PASS] every UI reference resolves")
        total += len(problems)
        print("")

    if total:
        print("UI CONTRACT FAILS - %d unresolved reference(s). TunerStudio "
              "reports these at .ini LOAD time and then silently gives you a "
              "dialog whose buttons do nothing." % total)
        return 1
    print("UI CONTRACT PASSES - every field, gauge, command, dialog, "
          "indicator and datalog entry resolves.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
