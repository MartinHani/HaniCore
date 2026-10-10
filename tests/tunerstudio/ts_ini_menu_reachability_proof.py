#!/usr/bin/env python3
r"""
ts_ini_menu_reachability_proof.py - a dialog nobody can open is a feature that
does not exist.

    py tests\tunerstudio\ts_ini_menu_reachability_proof.py [file.ini]
    py tests\tunerstudio\ts_ini_menu_reachability_proof.py --self-test

WHY THIS EXISTS, and it is the third .ini gate written after real hardware.

V37 was flashed. Its `.ini` loaded in real TunerStudio 3.3.01, the main UI
opened, the menus worked and every one of 47 gates was green. And the ONE test
that must be run before this ECU is ever asked to erase a flash sector -
`hc_nvm_ramtest()`, P0a - could not be reached, because

    dialog = hcDiagRamProbe, "External SRAM execution probe"

was declared, given its four seeded command buttons and its three gauges, and
then named by NO menu entry anywhere in the file. The generator's Diagnostics
menu was a hardcoded list of six ids beside a `DIAG_DIALOGS` table of seven,
and its own completeness check read `ui_plan` - the dialogs the MODEL produced
- so it was structurally blind to the hand-written table. The operator opened
Diagnostics on the bench, counted six entries, and stopped.

EVERY EXISTING .ini GATE PASSED THIS FILE, and each for a defensible reason:

  * `ts_ini_ui_contract`  resolves references - and every reference in the
                          orphaned dialog resolved perfectly;
  * `ts_ini_namespace_proof`  asks what a NAME may mean;
  * `ts_ini_grammar_proof`    asks what a LINE may look like;
  * `me711_och_contract_proof`  asks whether the channels match the firmware.

Not one of them asks CAN A HUMAN GET THERE. Existence is not reachability, and
that is the whole point of this file.

WHAT IS PROVEN

  1. every menu entry names something the file actually declares - a
     `subMenu`/`groupChildMenu` pointing at a dialog id that does not exist is
     a dead menu item;
  2. every declared `dialog` is reachable from a TOP-LEVEL menu, directly or
     transitively through a `panel` - the transitive part matters because a
     map's editable grid reaches its 3D surface that way;
  3. no dialog is declared twice, and no menu entry appears twice;
  4. THE REQUIRED DIAGNOSTIC DIALOGS, taken from the GENERATOR'S OWN
     `DIAG_DIALOGS` table rather than typed here, are each reachable. A
     diagnostics dialog added later cannot be forgotten by this gate, because
     this gate does not hold its own copy of the list;
  5. and the SRAM execution probe specifically, as a named chain:

         top-level "Controller" (Developer diagnostics; "Diagnostics" before
         the V89 rusEFI-alignment pass)
             -> a menu entry naming hcDiagRamProbe
             -> the hcDiagRamProbe dialog
             -> four commandButtons, one per seed in RAM_PROBE_SEEDS
             -> each button's command defined in [ControllerCommands]
             -> each command is '!M' followed by exactly that seed byte
             -> and the ramProbe / ramProbeSeed / ramProbeResult gauges, so
                the operator can tell IDLE from PASS from RUNNING from WRONG
                from NOSIG.

WHY IT CANNOT PASS VACUOUSLY. `--self-test` injects five defects into the real
generated file in memory - the five the brief names - and requires the checker
to produce the MATCHING complaint for each:

  A. the dialog exists but its menu entry is deleted            -> ORPHAN
  B. a menu entry names a dialog that does not exist            -> DANGLING
  C. the dialog is moved under a host dialog that is itself in
     no menu                                                    -> ORPHAN
  D. one of the four seeded probe buttons is removed            -> PROBE
  E. the menu entry is pointed at the WRONG dialog id           -> ORPHAN

AND WHAT IT STILL DOES NOT PROVE. That real TunerStudio renders the menu. A
human with TunerStudio open moves a file from INI STATIC VERIFIED to INI REAL
TUNERSTUDIO VERIFIED and nothing offline can.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

DEFAULT_INI = ROOT / "tunerstudio/hanicore_me711.ini"

# THE REQUIRED LISTS COME FROM THE GENERATOR, NOT FROM HERE. A gate holding its
# own copy of what must exist is the same defect one level up: two artefacts
# that must agree and nothing that makes them.
import gen_ts_ini_me711 as G           # noqa: E402
# The command decoder is NOT written here. It comes from the gate that derives
# TunerStudio's real rule from rusEFI's corpus. This gate previously tested
# `lit.startswith("!M")` - a private copy of the syntax model, which is exactly
# the mistake that let all 36 commands ship broken.
import ts_ini_command_shape_proof as SHAPE   # noqa: E402

REQUIRED_DIAG = [did for did, _t, _c, _n in G.DIAG_DIALOGS]
# the channels each required dialog shows: a FROZEN .ini (a V89/V91 pair
# proof) predates dialogs the generator added later, and a dialog whose
# channels the file does not declare is not a requirement ON THAT FILE - a
# LEVEL condition read from the file, not a version list (V97: hcDiagDtc)
REQUIRED_DIAG_CHANNELS = {did: list(chans) for did, _t, _c, chans in G.DIAG_DIALOGS}


def declares_channel(text, name):
    return re.search(r"^\s*%s\s*=\s*(scalar|bits|\{)" % re.escape(name),
                     text, re.M) is not None
PROBE_DIALOG = "hcDiagRamProbe"
PROBE_SEEDS = list(G.RAM_PROBE_SEEDS)
PROBE_GAUGES = ("ramProbe", "ramProbeSeed", "ramProbeResult")
# V89 UI (rusEFI pass): the developer forensics - this probe among them -
# moved to rusEFI's &Controller menu, group "Developer diagnostics".
# Either home is legitimate; the frozen V37..V89_UI packages carry it under
# Diagnostics and must stay re-provable.
PROBE_TOP_MENUS = ("Controller", "Diagnostics")


def forward_panel_refs(text):
    """A `panel =` that names a panel declared LATER in the file.

    DERIVED, NOT ASSUMED: across all 40 rusEFI generated .ini files - the ones
    known to load - a panel reference NEVER precedes its declaration. Zero
    forward references out of 40. So declare-before-use is the corpus
    convention, and this project follows the corpus rather than hoping
    TunerStudio's parser is forgiving. That hope is exactly what "static green
    is not acceptance" is about.
    """
    lines = text.splitlines()
    decl = {}
    for i, ln in enumerate(lines):
        m = re.match(r"^\s*(indicatorPanel|readoutPanel)\s*=\s*(\w+)", ln)
        if m:
            decl.setdefault(m.group(2), i)
    out = []
    for i, ln in enumerate(lines):
        m = re.match(r"^\s*panel\s*=\s*(\w+)", ln)
        if m and m.group(1) in decl and decl[m.group(1)] > i:
            out.append((m.group(1), i + 1, decl[m.group(1)] + 1))
    return out


def _menu_name(label):
    """A top-level menu's NAME, without TunerStudio's accelerator marker.

    rusEFI's own generated files write `menu = "&Setup"`, `"&Cranking"`,
    `"&Advanced"` - the ampersand marks the keyboard accelerator and is not
    part of the name. This gate compared the raw label, so adopting the corpus
    convention made it report the SRAM probe as unreachable from Diagnostics
    while it sat under "&Diagnostics" the whole time. Compare names, not
    decoration.
    """
    return label.lstrip("&").strip()
PROBE_CMD_BYTES = (ord("!"), ord("M"))


# ------------------------------------------------------------------ model --
class Model:
    """What is declared, what is referenced, and what reaches what."""

    def __init__(self, text):
        self.decl = {}            # id -> "dialog" | "curve" | "table"
        self.decl_dups = []
        self.panels = {}          # id -> {child ids}
        self.buttons = {}         # dialog id -> [command names]
        self.gauges = {}          # dialog id -> [gauge names]
        self.entries = []         # (top menu, group or None, id, label, line)
        self.top_menus = []
        self.commands = {}        # command name -> literal payload

        cur = None
        top = None
        group = None
        section = None
        for n, ln in enumerate(text.splitlines(), 1):
            m = re.match(r"^\s*\[(\w+)\]", ln)
            if m:
                section = m.group(1)
                continue

            if section == "ControllerCommands":
                m = re.match(r'^\s*(\w+)\s*=\s*"(.*)"\s*$', ln)
                if m:
                    self.commands[m.group(1)] = m.group(2)
                continue

            # A DECLARATION carries a quoted title and sits at the outer
            # indent; a reference to one is `panel =`. All 43 dialogs, 11
            # curves and 6 tables in the V37 file follow this exactly.
            m = re.match(r"^\s{0,4}(dialog|curve|table|indicatorPanel|"
                         r"readoutPanel)\s*=\s*(\w+)\s*,", ln)
            if m:
                cur = m.group(2)
                if cur in self.decl:
                    self.decl_dups.append((cur, n))
                self.decl[cur] = m.group(1)
                self.panels.setdefault(cur, set())
                self.buttons.setdefault(cur, [])
                self.gauges.setdefault(cur, [])
                continue

            m = re.match(r"^\s*panel\s*=\s*(\w+)", ln)
            if m and cur:
                self.panels[cur].add(m.group(1))
                continue

            m = re.match(r'^\s*commandButton\s*=\s*"[^"]*"\s*,\s*(\w+)', ln)
            if m and cur:
                self.buttons[cur].append(m.group(1))
                continue

            # V89 UI: a live value may be a `readout` in a readoutPanel as
            # well as a `gauge` widget - the same [GaugeConfigurations] entry.
            m = re.match(r"^\s*(?:gauge|readout)\s*=\s*(\w+)", ln)
            if m and cur:
                self.gauges[cur].append(m.group(1))
                continue
            m = re.match(r"^\s*gauge\s*=\s*(\w+)", ln)
            if m and cur:
                self.gauges[cur].append(m.group(1))
                continue

            m = re.match(r'^\s*menu\s*=\s*"([^"]*)"', ln)
            if m:
                top = m.group(1)
                group = None
                cur = None
                self.top_menus.append(top)
                continue

            m = re.match(r'^\s*groupMenu\s*=\s*"([^"]*)"', ln)
            if m:
                group = m.group(1)
                continue

            m = re.match(r'^\s*(subMenu|groupChildMenu)\s*=\s*(\w+)\s*,\s*'
                         r'"([^"]*)"', ln)
            if m and top is not None:
                self.entries.append((top, group if m.group(1) ==
                                     "groupChildMenu" else None,
                                     m.group(2), m.group(3), n))
                continue

    # -------------------------------------------------------- reachability --
    def reachable(self):
        """Every id a human can arrive at, following panels transitively."""
        seen, work = set(), [e[2] for e in self.entries]
        while work:
            did = work.pop()
            if did in seen:
                continue
            seen.add(did)
            work.extend(self.panels.get(did, ()))
        return seen

    def entries_for(self, did):
        return [e for e in self.entries if e[2] == did]

    def within(self, did, table):
        """Everything of `table` (buttons or gauges) a human SEES on dialog
        `did`, following its panels transitively - TunerStudio draws a nested
        panel inside the dialog that names it. V89 split dialogs into column
        panels; a check that read only the dialog's own lines would call a
        button in its second column missing."""
        out, seen, work = [], set(), [did]
        while work:
            d = work.pop(0)
            if d in seen:
                continue
            seen.add(d)
            out.extend(getattr(self, table).get(d, ()))
            work.extend(sorted(self.panels.get(d, ())))
        return out


# ------------------------------------------------------------------ check --
def check(text, verbose=True, user=False):
    """user=True: the tuner's project, which must NOT carry the developer
    pages (gen_ts_ini_me711.DEV_ONLY); they are required in the forensic
    project instead, and so is the SRAM probe chain."""
    m = Model(text)
    bad = []

    for name, used, declared in forward_panel_refs(text):
        bad.append("ORDER      line %d references panel %r, which is declared "
                   "at line %d - no rusEFI .ini forward-references a panel"
                   % (used, name, declared))

    for did, n in m.decl_dups:
        bad.append("DUPLICATE  %s is declared more than once (line %d)"
                   % (did, n))

    seen_entry = {}
    for top, grp, did, lbl, n in m.entries:
        if did not in m.decl:
            bad.append("DANGLING   line %-5d menu entry %r names %r, which "
                       "this file never declares" % (n, lbl, did))
        key = (top, grp, did)
        if key in seen_entry:
            bad.append("DUPLICATE  %s appears twice under %r (lines %d, %d)"
                       % (did, top, seen_entry[key], n))
        else:
            seen_entry[key] = n

    reach = m.reachable()

    # 2. EVERY declared dialog must be reachable. Curves and tables are
    #    reachable by definition of being referenced; a dialog is the thing a
    #    human opens, so a dialog is the thing that can be lost.
    for did, kind in sorted(m.decl.items()):
        if kind == "dialog" and did not in reach:
            bad.append("ORPHAN     dialog %s is declared and NO menu reaches "
                       "it - it cannot be opened" % did)

    # 4. the required diagnostics dialogs, from the generator's own table
    for did in REQUIRED_DIAG:
        if user and did in G.DEV_ONLY:
            if did in m.decl:
                bad.append("DEVELOPER  %s is a developer page and belongs in "
                           "the forensic project only" % did)
            continue
        chans = REQUIRED_DIAG_CHANNELS.get(did, [])
        if chans and not any(declares_channel(text, c) for c in chans):
            continue                 # this file has none of its channels
        if did not in m.decl:
            bad.append("MISSING    required diagnostics dialog %s is not "
                       "declared at all" % did)
        elif did not in reach:
            bad.append("ORPHAN     required diagnostics dialog %s is not "
                       "reachable from any menu" % did)

    # 5. THE SRAM EXECUTION PROBE, as a named chain (developer project).
    ents = m.entries_for(PROBE_DIALOG)
    if user:
        pass
    elif not ents:
        bad.append("ORPHAN     the SRAM execution probe dialog %s is in no "
                   "menu - P0a cannot be performed" % PROBE_DIALOG)
    elif not any(_menu_name(e[0]) in PROBE_TOP_MENUS for e in ents):
        bad.append("ORPHAN     %s is reachable, but not from the top-level "
                   "%r menu (found under %s)"
                   % (PROBE_DIALOG, " or ".join(PROBE_TOP_MENUS),
                      ", ".join(sorted({e[0] for e in ents}))))

    if PROBE_DIALOG in m.decl and not user:
        cmds = m.within(PROBE_DIALOG, "buttons")
        for seed in PROBE_SEEDS:
            def decoded(cname):
                raw, subs = SHAPE.wire_bytes(m.commands.get(cname, ""))
                return () if subs else tuple(raw)

            want = [c for c in cmds if decoded(c)[-1:] == (seed,)]
            if not want:
                bad.append("PROBE      no command button on %s sends seed "
                           "0x%02X - the probe cannot be run with it"
                           % (PROBE_DIALOG, seed))
                continue
            for c in want:
                raw = decoded(c)
                if raw[:2] != PROBE_CMD_BYTES:
                    bad.append("PROBE      %s = %r reaches the firmware as "
                               "%s, not '!' + 'M'"
                               % (c, m.commands[c],
                                  " ".join("%02X" % b for b in raw)))
        if len(cmds) < len(PROBE_SEEDS):
            bad.append("PROBE      %s carries %d command buttons, and the "
                       "generator declares %d seeds"
                       % (PROBE_DIALOG, len(cmds), len(PROBE_SEEDS)))
        for g in PROBE_GAUGES:
            if g + "Gauge" not in m.within(PROBE_DIALOG, "gauges"):
                bad.append("PROBE      %s does not show %s - the operator "
                           "cannot tell PASS from RUNNING from WRONG"
                           % (PROBE_DIALOG, g))

    if verbose:
        print("    %d top-level menus, %d menu entries, %d declared dialogs, "
              "%d curves, %d tables"
              % (len(m.top_menus), len(m.entries),
                 sum(1 for k in m.decl.values() if k == "dialog"),
                 sum(1 for k in m.decl.values() if k == "curve"),
                 sum(1 for k in m.decl.values() if k == "table")))
        if not bad and not user:
            path = m.entries_for(PROBE_DIALOG)[0]
            print('    probe route: menu "%s" -> subMenu %s, "%s" -> dialog '
                  "%s -> %d seeded buttons"
                  % (path[0], path[2], path[3], PROBE_DIALOG,
                     len(m.within(PROBE_DIALOG, "buttons"))))
    return bad


# -------------------------------------------------------------- self test --
def self_test(text):
    """The five defects the brief names. Each must produce its own complaint."""
    print("\n  --- the mutation test: every defect must be caught ---")
    ok = True
    m = Model(text)
    ents = m.entries_for(PROBE_DIALOG)
    if not ents:
        # The file under test is ALREADY the defect this gate exists for, so
        # there is no menu line to mutate. Say so plainly rather than raising:
        # the check above has already failed and that is the answer.
        print("      [SKIP] this file has no %s menu entry at all - "
              "the mutations have nothing to remove." % PROBE_DIALOG)
        print("             That IS the defect; see the failures above.")
        return False
    line = ents[0]
    # The entry may be a top-level subMenu or (since the V89 rusEFI pass, in
    # Controller / Developer diagnostics) a groupChildMenu: mutate the line
    # that is really there, whatever its keyword and indent.
    found = re.search(r'^[ \t]*(?:subMenu|groupChildMenu)[ \t]*=[ \t]*%s[ \t]*,'
                      r'[ \t]*"%s"[ \t]*$' % (re.escape(PROBE_DIALOG),
                                               re.escape(line[3])),
                      text, re.M)
    real = found.group(0) if found else None
    if real is None or real not in text:
        print("      [SKIP] the probe menu line is not shaped as expected")
        return False

    cases = []

    # A. the dialog exists but nothing in any menu names it
    cases.append(("the dialog exists but its menu entry is deleted",
                  text.replace(real + "\n", "", 1), "ORPHAN"))

    # B. a menu entry names a dialog that does not exist
    cases.append(("a menu entry names a dialog that does not exist",
                  text.replace(real,
                               real.replace(PROBE_DIALOG,
                                            "hcDiagNoSuchDialog"), 1),
                  "DANGLING"))

    # C. the dialog is only under a HOST dialog that is itself in no menu.
    #    This is the one a non-transitive checker passes.
    host = ('   dialog = hcOrphanHost, "unreachable host"\n'
            '      panel = %s\n\n' % PROBE_DIALOG)
    mut = text.replace(real + "\n", "", 1)
    mut = mut.replace("   dialog = %s," % PROBE_DIALOG,
                      host + "   dialog = %s," % PROBE_DIALOG, 1)
    cases.append(("the dialog sits under a submenu that is itself unreachable",
                  mut, "ORPHAN"))

    # D. one of the four seeded probe actions is gone
    seed = PROBE_SEEDS[-1]
    mut = re.sub(r'^\s*commandButton\s*=\s*"[^"]*0x%02X"\s*,\s*\w+\s*$'
                 % seed, "", text, count=1, flags=re.M | re.I)
    if mut == text:
        raise SystemExit("could not remove the 0x%02X probe button - the "
                         "mutation test is broken, not the file" % seed)
    cases.append(("one of the four seeded probe buttons is removed",
                  mut, "PROBE"))

    # E. the menu entry points at the WRONG dialog id
    cases.append(("the menu entry points at the wrong dialog id",
                  text.replace(real,
                               real.replace(PROBE_DIALOG, "hcDiagPlatform"),
                               1),
                  "ORPHAN"))

    for title, mtext, want in cases:
        found = check(mtext, verbose=False)
        hits = [p for p in found if p.startswith(want)]
        print("      [%s] %-58s %s"
              % ("PASS" if hits else "FAIL", title,
                 hits[0][:78] if hits else "NOTHING OF TYPE " + want))
        ok = ok and bool(hits)

    # A CONTROL. The unmutated file must be clean, or the five above prove
    # nothing: a checker that complains about everything catches everything.
    clean = check(text, verbose=False)
    print("      [%s] %-58s %s"
          % ("PASS" if not clean else "FAIL",
             "CONTROL - the real generated file is clean",
             "no complaints" if not clean else clean[0][:78]))
    return ok and not clean


def main(argv) -> int:
    path = Path(argv[1]) if len(argv) > 1 and not argv[1].startswith("--") \
        else DEFAULT_INI
    text = path.read_text(errors="replace")
    # The tuner's project and the developer (forensic) project are checked
    # together: the user file without the developer pages, the forensic file
    # with them - and the mutation test runs where the probe lives.
    dev_path = G.OUT_FORENSIC
    user = not path.name.endswith("_forensic.ini") and dev_path.exists()

    print("=== TunerStudio menu reachability proof ===\n")
    print("  ini   %s%s" % (path.name, " (user project)" if user else ""))
    bad = check(text, user=user)
    if user:
        print("  ini   %s (developer project)" % dev_path.name)
        dev_text = dev_path.read_text(errors="replace")
        bad += ["[%s] %s" % (dev_path.name, b) for b in check(dev_text)]
        mutant = text + "\n   dialog = %s, \"probe\"\n" % PROBE_DIALOG
        if not any(b.startswith("DEVELOPER") for b in check(mutant, False, True)):
            bad.append("CONTROL    a developer page put back into the user "
                       "project is not caught")
        text = dev_text

    print()
    if bad:
        for b in bad:
            print("  [FAIL] " + b)
    else:
        print("  [PASS] every menu entry names something declared, every "
              "dialog is reachable")
        print("  [PASS] every required diagnostics dialog is reachable "
              "(%d, from the generator's own table; developer pages only in "
              "the forensic project)" % len(REQUIRED_DIAG))
        print("  [PASS] the SRAM execution probe chain is complete: "
              "Diagnostics -> dialog -> %d seeded buttons -> %s"
              % (len(PROBE_SEEDS), ", ".join(PROBE_GAUGES)))

    mut_ok = self_test(text)

    print()
    if bad or not mut_ok:
        if bad:
            print("MENU REACHABILITY PROOF FAILS - something in this .ini "
                  "cannot be opened by a human. Fix the GENERATOR, not the "
                  ".ini.")
        else:
            print("MENU REACHABILITY PROOF FAILS - the checker could not be "
                  "made to fail, so its PASS means nothing.")
        return 1
    print("MENU REACHABILITY PROOF PASSES - and it still does not prove real "
          "TunerStudio renders the menu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
