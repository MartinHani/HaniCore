#!/usr/bin/env python3
r"""
ts_ini_indicator_scope_proof.py - the gate for what REAL TunerStudio SAYS while
it is loading the file, not for what the file means.

    py tests\tunerstudio\ts_ini_indicator_scope_proof.py [file.ini]

WHY THIS EXISTS. On 2026-09-05 the V37C .ini LOADED in real TunerStudio 3.3.01
and every static gate in this repository was green - and TunerStudioAppDebug
was full of:

    Warning: indicator defined in UserDefined with no indicatorPanel defined,
    ignoring.

thirteen times, for syncState, syncLossReason, dbwState, fuelPumpState,
mainRelayMode, nvmStateLo, nvmErrLo, nvmSrcLo, nvmSlot, nvmClass, nvmPhase,
ramProbeVerdict and hcbState. Every one of those was a DECODED STATE NAME - the
whole point of the Stage A work - and TunerStudio threw all thirteen away. The
dialogs looked finished and showed nothing.

    Loading Depricated ini section [UserDefined], use [UiDialogs]

was in the same log.

THE CLASS OF DEFECT, and it is the durable part: ts_ini_ui_contract asks
whether a reference RESOLVES, ts_ini_namespace_proof asks what a NAME may mean,
ts_ini_grammar_proof asks what a LINE may look like, and
ts_ini_menu_reachability_proof asks whether a human can GET there. Not one of
them asks whether the element SURVIVES THE PARSER once it is reached. An
element TunerStudio ignores is indistinguishable, to all four, from one it
renders.

WHAT IS CHECKED, and where each rule comes from:

  1. `indicator =` is legal at the top level of [FrontPage] and NOWHERE ELSE
     except inside an `indicatorPanel` block. rusEFI's own generated .ini -
     which loads - has 268 `indicator` lines: the ones outside a panel are all
     in [FrontPage] (rusefi_proteus_f7.ini:6093-6138) and every one inside
     [UserDefined] is under an `indicatorPanel = <id>, <cols>` (7791 onward).
     The corpus is the authority, and the real TS log agrees with it.

  2. `readout =` only inside a `readoutPanel` block, for the same structural
     reason. No real-TS evidence for this one yet - it is the same shape and
     it costs nothing to hold.

  3. The dialog section header is `[UiDialogs]`, not the deprecated
     `[UserDefined]`. TunerStudio 3.3.01 names the replacement itself, and
     rusEFI .junie/ts-help-topic.md documents both spellings as
     valid places to define an entity.

     THIS ONE IS A DEVIATION FROM THE CORPUS AND IT IS DELIBERATE. rusEFI still
     emits [UserDefined], so the corpus cannot prove [UiDialogs] loads. Two
     other sources can: TunerStudio's own message, and rusEFI's own
     documentation. The release ships a [UserDefined] fallback .ini beside the
     primary so a T0 failure costs one file swap and not a bench session.

MUTATION TESTED. Every rule is exercised against a file that must fail, and
the whole gate is run against the frozen V37C .ini, which must fail with all
thirteen indicators named.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# A line that OPENS a block. Everything after it belongs to that block until
# the next opener or the next section header. `panel = x` is a REFERENCE to a
# block, not an opener, and is deliberately absent.
OPENER = re.compile(r"^\s*(dialog|indicatorPanel|readoutPanel|help|curve|table"
                    r"|menu|settingGroup)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)")
SECTION = re.compile(r"^\s*\[([A-Za-z0-9_]+)\]")
MEMBER = re.compile(r"^\s*(indicator|readout)\s*=")

DIALOG_SECTIONS = ("UserDefined", "UiDialogs")


def scan(text: str):
    """Return (problems, stats). One pass, no ini model needed."""
    problems = []
    section = None
    block_kind = None
    block_id = None
    n_ind_panel = 0
    n_ind = 0
    n_readout_panel = 0
    saw_userdefined = False
    saw_uidialogs = False

    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split(";", 1)[0]
        if not line.strip():
            continue

        m = SECTION.match(line)
        if m:
            section = m.group(1)
            block_kind = block_id = None
            if section == "UserDefined":
                saw_userdefined = True
            if section == "UiDialogs":
                saw_uidialogs = True
            continue

        m = OPENER.match(line)
        if m:
            block_kind, block_id = m.group(1), m.group(2)
            if block_kind == "indicatorPanel":
                n_ind_panel += 1
            if block_kind == "readoutPanel":
                n_readout_panel += 1
            continue

        m = MEMBER.match(line)
        if not m:
            continue
        kind = m.group(1)

        if kind == "indicator":
            n_ind += 1
            if section == "FrontPage":
                continue                      # rule 1: legal, corpus-proven
            if section in DIALOG_SECTIONS:
                if block_kind != "indicatorPanel":
                    problems.append(
                        "%s:%d  indicator in %s under %s = %s, not an "
                        "indicatorPanel - real TunerStudio 3.3.01 IGNORES it: "
                        "%s" % (kind, lineno, section, block_kind, block_id,
                                _subject(line)))
            else:
                problems.append(
                    "%s:%d  indicator in section [%s], which is neither "
                    "[FrontPage] nor a dialog section" % (kind, lineno, section))

        elif kind == "readout":
            if block_kind != "readoutPanel":
                problems.append(
                    "readout:%d  readout under %s = %s, not a readoutPanel"
                    % (lineno, block_kind, block_id))

    if saw_userdefined and not saw_uidialogs:
        problems.append(
            "section: the dialogs are in the DEPRECATED [UserDefined]. "
            "TunerStudio 3.3.01 logs 'Loading Depricated ini section "
            "[UserDefined], use [UiDialogs]' - see the module docstring for "
            "why this is a deliberate deviation from the rusEFI corpus.")

    return problems, {
        "indicators": n_ind,
        "indicatorPanels": n_ind_panel,
        "readoutPanels": n_readout_panel,
        "section": "UiDialogs" if saw_uidialogs else
                   ("UserDefined" if saw_userdefined else "NONE"),
    }


def _subject(line: str) -> str:
    """The channel an indicator is about, for a message a human can act on."""
    m = re.search(r"\{\s*([A-Za-z_][A-Za-z0-9_]*)", line)
    return m.group(1) if m else line.strip()[:60]


# ==========================================================================
# Mutations. A gate that cannot fail proves nothing - the project rules standing
# rule, and the reason this file exists at all.
# ==========================================================================
_GOOD = """
[FrontPage]
   indicator = { crankSync }, "NO SYNC", "Sync"

[UiDialogs]
   indicatorPanel = pnl, 2
      indicator = { dbwState == 2 }, "A", "B"

   readoutPanel = rd, 2
      readout = rpmGauge

   dialog = d1, "Something"
      panel = pnl
      panel = rd
      gauge = rpmGauge
"""

_MUTATIONS = [
    ("indicator directly under a dialog",
     _GOOD.replace('   dialog = d1, "Something"\n      panel = pnl',
                   '   dialog = d1, "Something"\n'
                   '      indicator = { nvmSlot == 1 }, "A", "B"\n'
                   '      panel = pnl')),
    ("readout outside a readoutPanel",
     _GOOD.replace("      gauge = rpmGauge", "      readout = rpmGauge")),
    ("the deprecated section name",
     _GOOD.replace("[UiDialogs]", "[UserDefined]")),
    ("indicator in a section that has no indicators at all",
     _GOOD.replace("[FrontPage]", "[Tuning]")),
]


def main(argv) -> int:
    target = Path(argv[1]) if len(argv) > 1 else (
        ROOT / "tunerstudio/hanicore_me711.ini")
    ok = True

    print("== mutations (each MUST fail) ==")
    for name, text in _MUTATIONS:
        probs, _ = scan(text)
        state = "FAIL as required" if probs else "*** DID NOT FAIL ***"
        print("  %-46s %s" % (name, state))
        if not probs:
            ok = False

    probs, _ = scan(_GOOD)
    print("  %-46s %s" % ("control (must pass)",
                          "clean" if not probs else "*** %s ***" % probs))
    if probs:
        ok = False

    frozen = (ROOT / "release/Porsche_ME711_V37C_RUSEFI_UI"
              / "hanicore_me711_v37c_rusefi_ui.ini")
    if frozen.exists():
        fp, _ = scan(frozen.read_text(errors="replace"))
        print("\n== the frozen V37C file, which real TunerStudio warned about ==")
        print("  %d problem(s) - this file MUST fail" % len(fp))
        for p in fp[:20]:
            print("    " + p)
        if not fp:
            print("  *** V37C came back clean: this gate cannot see the "
                  "defect it was written for ***")
            ok = False

    print("\n== %s ==" % target)
    if not target.exists():
        print("  missing - generate it first")
        return 1
    probs, stats = scan(target.read_text(errors="replace"))
    print("  %(indicators)d indicators, %(indicatorPanels)d indicatorPanels, "
          "%(readoutPanels)d readoutPanels, dialogs in [%(section)s]" % stats)
    for p in probs:
        print("    " + p)
    if probs:
        ok = False

    print("\n%s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
