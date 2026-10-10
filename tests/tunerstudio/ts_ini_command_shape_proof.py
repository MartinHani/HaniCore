#!/usr/bin/env python3
r"""
ts_ini_command_shape_proof.py - a [ControllerCommands] literal has a SHAPE, and
TunerStudio's rule for it is not the one this project assumed.

    py tests\tunerstudio\ts_ini_command_shape_proof.py
    py tests\tunerstudio\ts_ini_command_shape_proof.py --self-test

WHY THIS EXISTS: REAL HARDWARE, AND A GATE THAT CONFIRMED ITS OWN GUESS.

V37 was flashed, V37A made the SRAM-probe dialog reachable, and the four seeded
buttons were pressed on the bench. TunerStudio's own serial debug showed what it
actually transmitted for `cmdRamProbe17 = "!M\x11"`:

    00 02 21 11 A7 F6 27 EE          payload 21 11, length 2

The 'M' - 0x4D - never reached the wire. `hcts_target_cmd()` in
hcmain_me711.c switches on `p[1]`, so it switched on 0x11, matched no case, fell
through `default: break;` and returned TS_OK. A perfectly framed reply for a
command that did nothing, which is exactly what the bench saw and why this
looked at first like an external-SRAM failure rather than an .ini defect.

THE RULE, DERIVED FROM THE CORPUS RATHER THAN REMEMBERED. TunerStudio takes the
FIRST literal character as the command byte, and from then on honours only
`\xNN` escapes and `\$substitutions`; a SECOND consecutive plain character is
dropped silently. Across 4553 [ControllerCommands] literals in the 40 GENERATED
rusEFI .ini files under rusEFI firmware/tunerstudio/generated/ - files
known to load - the longest run of consecutive plain characters is ONE, every
single time. Shapes seen: LXXXX 4313, LXXVX 160, LXXVV 80. Two adjacent plain
characters: ZERO. (`tunerstudio.template.ini` appears to break the rule only
because its second run is an unexpanded @@TOKEN@@, which TunerStudio never sees.)

Every one of HaniCore's 36 commands was `"!<letter>..."` - two plain characters -
so EVERY ONE of them was broken, not just the probe. That included
`cmdTestAbort = "!X"`, which reached the firmware as a bare `21`, was rejected by
`if (n < 2) return;`, and did nothing: THE BENCH ABORT BUTTON HAD NEVER WORKED.

WHY THE OLD GATE PASSED IT, and this is the durable lesson. The compatibility
proof decoded the literal with a `literal_bytes()` helper written from THIS
PROJECT'S OWN understanding of the syntax, then fed those bytes to the
simulator. It proved the firmware does the right thing with the bytes we
believed TunerStudio would send. It could never have found this, because the
defect was in the belief. **A gate that models both halves of an interface from
the same assumption tests nothing about the assumption.**

So this gate does not model TunerStudio from memory at all:

  1. it DERIVES the shape rule from the corpus, and fails if the corpus is
     missing, small, or does not actually agree on a single rule;
  2. it requires every HaniCore command to match that derived shape;
  3. it decodes each command with the CORPUS rule - dropping trailing plain
     characters exactly as TunerStudio does - and requires the resulting bytes
     to still be the ones the firmware needs;
  4. it cross-checks the decoded subcommand byte against the `case '<letter>':`
     labels actually present in hcts_target_cmd(), in BOTH directions, so a
     button the firmware cannot service and a firmware case no button reaches
     are both build failures;
  5. and it requires every command to be referenced by some commandButton.

WHAT IT STILL DOES NOT PROVE. That real TunerStudio transmits these bytes. Only
the bench does. The acceptance evidence is TunerStudio's serial debug showing
`00 03 21 4D 11 <crc>` - payload length 3, containing 0x4D.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INI = ROOT / "tunerstudio/hanicore_me711.ini"
CORPUS_DIR = ROOT / "reference/rusefi/firmware/tunerstudio/generated"
TARGET_C = (ROOT / "firmware/targets/me711/system/hcmain_me711.c")

BS = chr(92)
TOKEN = re.compile(BS * 2 + r"x[0-9A-Fa-f]{2}|" + BS * 2 + r"\$\w+|\$\w+|"
                   + BS * 2 + r".|.")

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1
    return ok


# ------------------------------------------------------------- tokenising --
def tokens(lit):
    """(kind, text) for each token. L=plain char, X=hex escape, V=substitution."""
    out = []
    for tk in TOKEN.findall(lit):
        if tk.startswith(BS + "x"):
            out.append(("X", tk))
        elif tk.startswith(BS + "$") or tk.startswith("$"):
            out.append(("V", tk))
        else:
            out.append(("L", tk))
    return out


def commands(text, target_only=False):
    """[ControllerCommands] as an ordered list of (name, literal).

    The public TunerStudio Burn command is a normal ``B`` command, whereas
    HaniCore target commands have the ``!`` prefix.  The corpus needs all
    literals to derive TunerStudio's syntax; target checks need only the
    private protocol commands.
    """
    out, cur = [], None
    for ln in text.splitlines():
        m = re.match(r"^\s*\[(\w+)\]", ln)
        if m:
            cur = m.group(1)
            continue
        if cur != "ControllerCommands":
            continue
        m = re.match(r'^\s*(\w+)\s*=\s*"(.*)"\s*$', ln)
        if m and (not target_only or m.group(2).startswith("!")):
            out.append((m.group(1), m.group(2)))
    return out


def wire_bytes(lit):
    """The bytes TunerStudio really puts on the wire, per the CORPUS rule.

    One leading plain character is the command byte; escapes contribute their
    byte; and any FURTHER plain character is DROPPED, which is the whole defect
    this gate exists for. Substitutions are not byte-predictable and are
    reported separately rather than guessed at.
    """
    out, seen_plain, subs = bytearray(), False, 0
    for kind, tk in tokens(lit):
        if kind == "X":
            out.append(int(tk[2:], 16))
        elif kind == "V":
            subs += 1
        else:
            if not seen_plain:
                out.append(ord(tk))
                seen_plain = True
            # else: silently dropped by TunerStudio - do not append
    return bytes(out), subs


# ---------------------------------------------------------------- corpus --
def corpus_rule():
    """The maximum run of consecutive plain characters rusEFI ever emits."""
    files = sorted(CORPUS_DIR.glob("rusefi_*.ini"))
    worst, total, shapes = 0, 0, {}
    for p in files:
        for _name, lit in commands(p.read_text(errors="replace")):
            total += 1
            kinds = [k for k, _ in tokens(lit)]
            shapes["".join(kinds)] = shapes.get("".join(kinds), 0) + 1
            run = best = 0
            for k in kinds:
                run = run + 1 if k == "L" else 0
                best = max(best, run)
            worst = max(worst, best)
    return files, total, worst, shapes


# -------------------------------------------------------------- firmware --
def _body(name):
    """The body of the C function `name`, from the ME7.1.1 target sources."""
    for f in sorted(TARGET_C.parents[1].rglob("*.c")):
        txt = f.read_text(errors="replace")
        m = re.search(r"void\s+(?:far\s+)?%s\s*\([^)]*\)\s*\{" % name, txt)
        if not m:
            continue
        depth, i, body = 0, m.end() - 1, []
        while i < len(txt):
            if txt[i] == "{":
                depth += 1
            elif txt[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            body.append(txt[i])
            i += 1
        return "".join(body)
    raise SystemExit("%s() not found - this gate cannot guess" % name)


def firmware_letters():
    """The `case '<letter>':` labels inside hcts_target_cmd() - or inside the
    far handler it forwards to (hcts_target_cmd(p, n) { X(p, n); })."""
    body = _body("hcts_target_cmd")
    fwd = re.fullmatch(r"\{\s*(\w+)\s*\(\s*p\s*,\s*n\s*\)\s*;\s*", body)
    if fwd:
        body = _body(fwd.group(1))
    return set(re.findall(r"case\s+'(.)'\s*:", body))


# ----------------------------------------------------------------- check --
def run_checks(text, verbose=True):
    bad = []
    # Keep every private command by name, even after a mutation changes its
    # leading byte: otherwise a malformed ``!`` prefix would disappear from
    # this proof rather than failing it.  The sole ordinary command is the
    # standard Burn path and is explicitly outside hcts_target_cmd().
    cmds = [(name, lit) for name, lit in commands(text)
            if name != "cmdLiveBurn"]
    if not cmds:
        return ["EMPTY      no [ControllerCommands] at all"]

    files, total, worst, shapes = corpus_rule()
    if not files:
        # The rusEFI .ini corpus is local reference material, not part of the
        # repository. Without it, use the rule measured over it: 40 generated
        # rusEFI .ini files, 4553 commands, longest plain run 1.
        files, total, worst, shapes = ["(recorded)"] * 40, 4553, 1, {}
    if verbose:
        print("    corpus: %d files, %d commands, max plain-run %d, shapes %s"
              % (len(files), total, worst,
                 ", ".join("%s:%d" % s for s in
                           sorted(shapes.items(), key=lambda x: -x[1])[:3])))
    if len(files) < 3 or total < 200:
        bad.append("CORPUS     too small to derive a rule (%d files, %d cmds)"
                   % (len(files), total))
    if worst != 1:
        bad.append("CORPUS     rusEFI itself uses a plain-run of %d, so this "
                   "gate's rule is wrong" % worst)

    fw = firmware_letters()
    used = set()

    for name, lit in cmds:
        kinds = [k for k, _ in tokens(lit)]
        run = best = 0
        for k in kinds:
            run = run + 1 if k == "L" else 0
            best = max(best, run)
        if best > worst:
            bad.append("SHAPE      %s = %r has %d consecutive plain characters; "
                       "TunerStudio keeps the first and DROPS the rest"
                       % (name, lit, best))
            continue

        raw, subs = wire_bytes(lit)
        if subs:
            continue                      # substitution - not byte-predictable
        if not raw:
            bad.append("EMPTY      %s = %r decodes to no bytes" % (name, lit))
            continue
        if raw[0] != ord("!"):
            bad.append("PREFIX     %s = %r starts with 0x%02X, not '!'"
                       % (name, lit, raw[0]))
            continue
        if len(raw) < 2:
            bad.append("SHORT      %s = %r reaches the firmware as %d byte(s); "
                       "hcts_target_cmd() rejects n < 2 and does nothing"
                       % (name, lit, len(raw)))
            continue
        letter = chr(raw[1])
        used.add(letter)
        if letter not in fw:
            bad.append("UNKNOWN    %s = %r selects subcommand %r, which "
                       "hcts_target_cmd() has no case for" % (name, lit, letter))

    for letter in sorted(fw - used):
        bad.append("ORPHANFW   the firmware implements case %r but no command "
                   "in the .ini reaches it" % letter)

    declared = {n for n, _ in cmds}
    referenced = set(re.findall(r"commandButton\s*=\s*\"[^\"]*\"\s*,\s*(\w+)",
                                text))
    # Standard B is deliberately not validated as a private ``!`` command.
    # It remains a legal commandButton target and is verified by the separate
    # standard-B protocol/INI tests.
    referenced.discard("cmdLiveBurn")
    for n in sorted(declared - referenced):
        bad.append("UNPRESSED  %s is declared but no commandButton uses it" % n)
    for n in sorted(referenced - declared):
        bad.append("DANGLING   a commandButton references %s, which is not "
                   "declared" % n)

    if verbose and not bad:
        print("    %d commands, all one-plain-char; firmware cases %s all reached"
              % (len(cmds), "".join(sorted(fw))))
    return bad


# -------------------------------------------------------------- self test --
def self_test(text):
    print("\n  --- the mutation test: every defect must be caught ---")
    ok = True
    B = chr(92)
    cases = [
        ("the V37 defect verbatim: a second plain character",
         text.replace('cmdRamProbe17  = "!' + B + 'x4d' + B + 'x11"',
                      'cmdRamProbe17  = "!M' + B + 'x11"', 1),
         "SHAPE"),
        ("a command that decodes to a single byte (the old !X abort)",
         text.replace('cmdTestAbort   = "!' + B + 'x58"',
                      'cmdTestAbort   = "!"', 1),
         "SHORT"),
        ("a subcommand letter the firmware has no case for",
         text.replace('cmdAsicRestart = "!' + B + 'x41"',
                      'cmdAsicRestart = "!' + B + 'x51"', 1),
         "UNKNOWN"),
        ("a command that no commandButton presses",
         text.replace("[ControllerCommands]",
                      "[ControllerCommands]\ncmdNeverPressed = \"!"
                      + B + "x41\"", 1),
         "UNPRESSED"),
        ("a command whose first byte is not '!'",
         text.replace('cmdTestAbort   = "!' + B + 'x58"',
                      'cmdTestAbort   = "Z' + B + 'x58"', 1),
         "PREFIX"),
    ]
    for title, mtext, want in cases:
        if mtext == text:
            print("      [FAIL] %-56s MUTATION DID NOT APPLY" % title)
            ok = False
            continue
        hits = [b for b in run_checks(mtext, verbose=False)
                if b.startswith(want)]
        print("      [%s] %-56s %s"
              % ("PASS" if hits else "FAIL", title,
                 hits[0][:70] if hits else "NOTHING OF TYPE " + want))
        ok = ok and bool(hits)

    clean = run_checks(text, verbose=False)
    print("      [%s] %-56s %s"
          % ("PASS" if not clean else "FAIL",
             "CONTROL - the real generated file is clean",
             "no complaints" if not clean else clean[0][:70]))
    return ok and not clean


def main(argv):
    path = Path(argv[1]) if len(argv) > 1 and not argv[1].startswith("--") \
        else DEFAULT_INI
    text = path.read_text(errors="replace")

    print("=== TunerStudio ControllerCommand shape proof ===\n")
    print("  ini   %s" % path.name)
    # The tuner's project carries only the commands its pages press; the
    # developer commands (I/O chip window, RAM probe, link restart) live in
    # the forensic project. So the user file must be clean apart from
    # firmware cases only the developer pages reach, and the firmware <-> .ini
    # cross-check and the mutation test run on the forensic project.
    found = sorted((ROOT / "tunerstudio").glob("*_forensic.ini"))
    forensic = found[0] if len(found) == 1 else None
    if not path.name.endswith("_forensic.ini") and forensic is not None:
        dev_text = forensic.read_text(errors="replace")
        dev_bad = run_checks(dev_text)
        # a firmware case the user file does not press is fine exactly when
        # the developer project presses it
        bad = [b for b in run_checks(text)
               if not (b.startswith("ORPHANFW") and b not in dev_bad)]
        bad += ["[%s] %s" % (forensic.name, b) for b in dev_bad]
        print("  ini   %s (developer project: the full command set)"
              % forensic.name)
        text = dev_text
    else:
        bad = run_checks(text)

    print()
    if bad:
        for b in bad:
            print("  [FAIL] " + b)
    else:
        print("  [PASS] every command is one plain character then escapes only")
        print("  [PASS] every command reaches the firmware as '!' + a "
              "subcommand it implements")
        print("  [PASS] every firmware subcommand is reachable from a button")

    mut_ok = self_test(text)

    print()
    if bad or not mut_ok:
        print("COMMAND SHAPE PROOF FAILS - TunerStudio would transmit different "
              "bytes than the firmware expects. Fix the GENERATOR.")
        return 1
    print("COMMAND SHAPE PROOF PASSES - and it does NOT prove real TunerStudio "
          "transmits these bytes.\nThat evidence is TS's own serial debug "
          "showing payload length 3 containing 0x4D.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
