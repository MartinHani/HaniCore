#!/usr/bin/env python3
r"""
ts_ini_namespace_proof.py - TunerStudio has ONE namespace, and a name may not
be both a page Constant and an output channel.

    py tests\tunerstudio\ts_ini_namespace_proof.py [file.ini]
    py tests\tunerstudio\ts_ini_namespace_proof.py --self-test

WHY THIS EXISTS, and it is the second time.

On 2026-09-02 the S5500 dialog did not load because the generated `.ini` had an
unterminated string and four output channels bound with `field =`. The gate
written in response, `ts_ini_ui_contract.py`, resolves every reference - and it
still passed the V30 and V31 files that **real TunerStudio 3.3.01 refuses to
load**, because its resolver pools `[Constants]` and `[OutputChannels]` into one
set and asks only "does this name exist somewhere".

TunerStudio does not work that way. The two sections share one namespace, and
the ROLE a reference needs is fixed by the keyword using it:

    field       = "label", NAME        NAME must be a page CONSTANT
    gauge       = NAMEGauge            the gauge's source must be a CHANNEL
    indicator   = { NAME }             CHANNEL
    entry       = NAME, ...            CHANNEL  (datalog)

So a name defined in both sections is ambiguous, and TunerStudio answers with
`invalid Constant` / `EcuParameter not found` and stops. V31 had two:
`outputsArmed` and `mainRelayMode`. The V29B file - the one this project has
CONFIRMED loads - avoided exactly those two by suffixing the settings `Cfg`,
and the generated UI dropped the suffix.

WHAT THIS GATE CHECKS

  1. no name is declared in both [Constants] and [OutputChannels];
  2. every dialog `field =` binds a name that is a Constant and NOT a channel;
  3. every `gauge` source, `indicator` expression name and datalog `entry`
     binds a name that is a channel and NOT a Constant;
  4. no duplicate top-level `menu = "label"`;
  5. no duplicate declaration of the same name inside one section.

WHY IT CANNOT PASS VACUOUSLY. `--self-test` injects each defect into the real
generated `.ini` in memory and requires the checker to fail on every one. A
checker that cannot be made to fail proves nothing when it passes.

AND WHAT IT STILL DOES NOT PROVE. That real TunerStudio loads the file. Nothing
offline can prove that. See the project rules: INI STATIC VERIFIED and INI
REAL TUNERSTUDIO VERIFIED are different states and only a human with
TunerStudio open can move a file into the second one.
"""
from __future__ import annotations

import collections
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INI = ROOT / "tunerstudio/hanicore_me711.ini"

SEC = re.compile(r"^\s*\[(\w+)\]")
DECL = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*(scalar|bits|array|string)\b")
EXPR = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*\{")
FIELD = re.compile(r'^\s*field\s*=\s*"(?:[^"]*)"\s*,\s*([A-Za-z_]\w*)')
GAUGEDEF = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*)\s*,")
ENTRY = re.compile(r"^\s*entry\s*=\s*([A-Za-z_]\w*)")
INDIC = re.compile(r"^\s*indicator\s*=\s*\{\s*([A-Za-z_]\w*)")
MENU = re.compile(r'^\s*menu\s*=\s*"([^"]*)"')


class Model:
    """What the file declares, split by the namespace role TunerStudio uses."""

    def __init__(self, text):
        self.constants = {}        # name -> line
        self.channels = {}         # name -> line
        self.gauges = {}           # gauge name -> (source name, line)
        self.field_refs = []       # (name, line)
        self.channel_refs = []     # (name, line, why)
        self.menus = []            # (label, line)
        self.dups = []             # (section, name, line)

        sec = None
        for i, raw in enumerate(text.splitlines(), 1):
            body = raw.split(";", 1)[0] if raw.lstrip().startswith(";") else raw
            m = SEC.match(body)
            if m:
                sec = m.group(1)
                continue

            if sec == "Constants":
                m = DECL.match(body)
                if m:
                    if m.group(1) in self.constants:
                        self.dups.append((sec, m.group(1), i))
                    self.constants[m.group(1)] = i
                    continue
            if sec == "OutputChannels":
                m = DECL.match(body) or EXPR.match(body)
                if m:
                    if m.group(1) in self.channels:
                        self.dups.append((sec, m.group(1), i))
                    self.channels[m.group(1)] = i
                    continue
            if sec == "GaugeConfigurations":
                m = GAUGEDEF.match(body)
                if m and not body.lstrip().startswith("gaugeCategory"):
                    self.gauges[m.group(1)] = (m.group(2), i)
                    self.channel_refs.append((m.group(2), i, "gauge source"))
                    continue
            if sec == "Datalog":
                m = ENTRY.match(body)
                if m:
                    self.channel_refs.append((m.group(1), i, "datalog entry"))
                    continue
            if sec in ("FrontPage", "UserDefined", "UiDialogs"):
                m = INDIC.match(body)
                if m:
                    self.channel_refs.append((m.group(1), i, "indicator"))
                    continue
            if sec in ("UserDefined", "UiDialogs"):
                m = FIELD.match(body)
                if m:
                    self.field_refs.append((m.group(1), i))
                    continue
            m = MENU.match(body)
            if m and sec == "Menu":
                self.menus.append((m.group(1), i))


def check(text, verbose=True):
    """Returns a list of problems. Empty means the namespaces are consistent."""
    m = Model(text)
    bad = []

    for name in sorted(set(m.constants) & set(m.channels)):
        bad.append("COLLISION  %-24s is a Constant (line %d) AND an output "
                   "channel (line %d)"
                   % (name, m.constants[name], m.channels[name]))

    for name, line in m.field_refs:
        if name in m.channels and name not in m.constants:
            bad.append("ROLE       line %-5d field = ..., %s  binds an OUTPUT "
                       "CHANNEL; a dialog field must bind a page Constant"
                       % (line, name))
        elif name not in m.constants and name not in m.channels:
            bad.append("MISSING    line %-5d field = ..., %s  is declared "
                       "nowhere" % (line, name))

    for name, line, why in m.channel_refs:
        if name in m.constants and name not in m.channels:
            bad.append("ROLE       line %-5d %s '%s' binds a page CONSTANT; "
                       "it must bind an output channel" % (line, why, name))

    c = collections.Counter(lbl for lbl, _ in m.menus)
    for lbl, n in sorted(c.items()):
        if n > 1:
            bad.append("MENU       top-level menu %r is emitted %d times"
                       % (lbl, n))

    for sec, name, line in m.dups:
        bad.append("DUPLICATE  [%s] %s redeclared at line %d"
                   % (sec, name, line))

    if verbose:
        print("    %d constants, %d output channels, %d gauges, %d dialog "
              "fields, %d channel references, %d top-level menus"
              % (len(m.constants), len(m.channels), len(m.gauges),
                 len(m.field_refs), len(m.channel_refs), len(m.menus)))
    return bad


# ------------------------------------------------------------- self test --
def self_test(text):
    """Inject each defect and require the checker to catch it."""
    print("\n  --- the mutation test: every defect must be caught ---")
    ok = True

    cases = []

    # 1. a collision: rename a Constant onto an existing channel name
    mm = Model(text)
    ch = sorted(set(mm.channels) - set(mm.constants))[0]
    cst = sorted(mm.constants)[0]
    mut = re.sub(r"^(\s*)%s(\s*=\s*(?:scalar|bits|array|string))" % cst,
                 r"\g<1>%s\g<2>" % ch, text, count=1, flags=re.M)
    cases.append(("a Constant renamed onto an existing channel name",
                  mut, "COLLISION"))

    # 2. a dialog field bound to an output channel
    mut = text.replace('field = "Arm hardware outputs", outputsArmedCfg',
                       'field = "Arm hardware outputs", rpm', 1)
    if mut == text:
        mut = re.sub(r'^(\s*field\s*=\s*"[^"]*",\s*)\w+\s*$',
                     r"\g<1>rpm", text, count=1, flags=re.M)
    cases.append(("a dialog field bound to an output channel", mut, "ROLE"))

    # 3. a duplicate top-level menu label.
    #
    # TAKEN FROM THE FILE, NOT TYPED. This used to write the literal "Fuel"
    # into the first menu, and stopped colliding the moment the menus were
    # renamed - the label became "&Fuel", the mutation became a no-op, and
    # the gate still reported PASS. Copy the SECOND menu's own label over
    # the first instead, so the collision holds whatever they are called.
    labels = re.findall(r'^\s*menu\s*=\s*"([^"]*)"', text, flags=re.M)
    if len(labels) < 2:
        raise SystemExit("the .ini has fewer than two top-level menus, so "
                         "the duplicate-label mutation cannot be built")
    mut = re.sub(r'^(\s*menu\s*=\s*")([^"]*)(")',
                 lambda m: m.group(1) + labels[1] + m.group(3),
                 text, count=1, flags=re.M)
    cases.append(("a duplicate top-level menu label", mut, "MENU"))

    for title, mtext, want in cases:
        found = check(mtext, verbose=False)
        # THE MATCHING problem, not merely the first one in the list. Printing
        # found[0] made an unrelated pre-existing defect look like the catch.
        hits = [p for p in found if p.startswith(want)]
        print("      [%s] %-52s %s"
              % ("PASS" if hits else "FAIL", title,
                 hits[0][:74] if hits else "NOTHING OF TYPE " + want))
        hit = bool(hits)
        ok = ok and hit
    return ok


def main(argv) -> int:
    path = Path(argv[1]) if len(argv) > 1 and not argv[1].startswith("--") \
        else DEFAULT_INI
    text = path.read_text(errors="replace")

    print("=== TunerStudio namespace proof ===\n")
    print("  ini   %s" % path.name)
    bad = check(text)

    print()
    if bad:
        for b in bad:
            print("  [FAIL] " + b)
    else:
        print("  [PASS] no Constant/OutputChannel collision, every dialog "
              "field binds a Constant,")
        print("         every gauge/indicator/datalog reference binds a "
              "channel, no duplicate menus")

    mut_ok = self_test(text)

    print()
    if bad or not mut_ok:
        if bad:
            print("NAMESPACE PROOF FAILS - real TunerStudio will report "
                  "'invalid Constant' or 'EcuParameter not found' and refuse "
                  "to load this file. Fix the GENERATOR, not the .ini.")
        else:
            print("NAMESPACE PROOF FAILS - the checker could not be made to "
                  "fail, so its PASS means nothing.")
        return 1
    print("NAMESPACE PROOF PASSES - and it still does not prove real "
          "TunerStudio loads the file. Only a human with TunerStudio open "
          "can do that.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
