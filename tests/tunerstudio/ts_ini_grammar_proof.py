#!/usr/bin/env python3
r"""
ts_ini_grammar_proof.py - does every line have a SHAPE TunerStudio has been
seen to accept?

    py tests\tunerstudio\ts_ini_grammar_proof.py [--ini path] [--no-mutate]

WHY THIS EXISTS. On 2026-09-03 the V34 `.ini` failed T0 in real TunerStudio
3.3.01, before the ECU was even connected:

    Invalid Ini entry in Loading Tables
    Error in [TableEditor] Section, I don't know how to handle this line.

Every static gate called that file green. The cause was an ARITY: HaniCore
emitted

    xBins = fuelRpmAx

and TunerStudio's table parser wants the tracing output channel as well:

    xBins = fuelRpmAx, rpm

That is the SECOND time a `.ini` that passed every gate would not load - the
first was the `[Constants]`/`[OutputChannels]` namespace collision that
`ts_ini_namespace_proof` now models. Both were the same failure of method: the
gates checked what the file MEANT and never checked whether its lines had a
shape TunerStudio can parse at all.

HOW THIS ONE KNOWS. It does not encode a grammar somebody wrote down from
memory. It builds a CORPUS from rusEFI's own generated `.ini` files - which do
load in TunerStudio, are in this repository already, and belong to the project
HaniCore's protocol is cloned from - and then asserts:

    for every line `keyword = a, b, c`, if that KEYWORD is one rusEFI also
    uses IN THE SAME SECTION, our argument count must be one rusEFI uses too.

A name rusEFI never uses is skipped, because it is one of ours - a
`[Constants]` field, an `[OutputChannels]` channel, a command. That is what
keeps the rule free of false positives while still catching exactly the class
of defect that got past everything else: `xBins` appears in the corpus 636
times and never once with a single argument.

It found a SECOND latent defect the same way. `[FrontPage] indicator` has seven
fields in 1235 corpus occurrences; HaniCore emitted eight. TunerStudio stops at
the first bad line, so that one was still waiting behind the table editor.

Then, because the editors are where it bit, they get explicit structural and
ROLE checks on top: a table needs all three axes, an axis's first argument must
be a page Constant and its second an OutputChannel, and a curve's axes must
resolve the same way.

WHY IT CANNOT PASS VACUOUSLY. `--mutate` injects each defect into the real
generated file and requires a problem the CLEAN file does not have - not
merely "some problem", which is what made the first version of this test
useless while five false positives were still in it.

IT STILL DOES NOT PROVE TUNERSTUDIO LOADS THE FILE. Only a human with
TunerStudio open can do that. the project rules: INI STATIC VERIFIED and
INI REAL TUNERSTUDIO VERIFIED are separate states, and this file only ever
produces the first.
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_image as PI                       # noqa: E402

LIVE_INI = ROOT / "tunerstudio/hanicore_me711.ini"
CORPUS_DIR = ROOT / "reference/rusefi/firmware/tunerstudio/generated"

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


# ======================================================== the tiny INI parser
SECTION = re.compile(r"^\s*\[([A-Za-z0-9_]+)\]")


def strip_comment(line: str) -> str:
    """Everything before an UNQUOTED semicolon. rusEFI puts semicolons inside
    quoted strings 18 times, so a naive split loses real content."""
    out = []
    q = False
    for ch in line:
        if ch == '"':
            q = not q
        if ch == ";" and not q:
            break
        out.append(ch)
    return "".join(out)


def split_args(rhs: str):
    """Top-level commas only - not inside quotes, braces or parentheses."""
    args, cur, q, depth = [], "", False, 0
    for ch in rhs:
        if ch == '"':
            q = not q
        if not q:
            if ch in "{(":
                depth += 1
            elif ch in "})":
                depth -= 1
            elif ch == "," and depth == 0:
                args.append(cur.strip())
                cur = ""
                continue
        cur += ch
    if cur.strip():
        args.append(cur.strip())
    return args


def parse(path: Path):
    """[(section, lhs, [args], lineno, raw)] for every `lhs = rhs` line."""
    out = []
    sec = None
    for n, raw in enumerate(path.read_text(errors="replace").splitlines(), 1):
        m = SECTION.match(raw)
        if m:
            sec = m.group(1)
            continue
        body = strip_comment(raw).strip()
        if not body or "=" not in body:
            continue
        lhs, rhs = body.split("=", 1)
        lhs = lhs.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", lhs):
            continue
        out.append((sec, lhs, split_args(rhs), n, body))
    return out


# ============================================================== the corpus ===
def build_corpus():
    """(section, keyword) -> the set of argument counts rusEFI uses."""
    seen = collections.defaultdict(set)
    files = sorted(CORPUS_DIR.glob("rusefi_*.ini"))
    for f in files:
        for sec, lhs, args, _n, _raw in parse(f):
            seen[(sec, lhs)].add(len(args))
    return seen, files


# Sections whose LEFT-HAND SIDE is a name the author chose rather than a
# TunerStudio keyword. `tps2Min = scalar, U16, 88, ...` is a field, and the
# fact that rusEFI happens to have a field of the same name with a different
# shape says nothing at all. Only the genuine keywords in these are checked.
NAME_SECTIONS = {"Constants", "OutputChannels", "PcVariables",
                 "ControllerCommands", "GaugeConfigurations", "Datalog",
                 "SettingGroups", "ReferenceTables"}

# The keywords that ARE real inside those sections, so the rule still applies
# where it should.
SECTION_KEYWORDS = {
    "Constants": {"page", "endMenu", "menuDialog"},
    "OutputChannels": {"ochGetCommand", "ochBlockSize"},
    "PcVariables": set(),
    "ControllerCommands": set(),
    "GaugeConfigurations": {"gaugeCategory"},
    "Datalog": {"entry"},
    "SettingGroups": {"settingGroup", "settingOption"},
    "ReferenceTables": {"referenceTable"},
}

# ONE VALUE PER PAGE, so the count is a property of THIS file and not of
# rusEFI's. rusEFI ships four pages and HaniCore ships one; comparing the two
# counts would condemn a perfectly good line.
PAGE_KEYWORDS = {"pageSize", "pageIdentifier", "pageReadCommand",
                 "pageValueWrite", "pageChunkWrite", "burnCommand",
                 "pageActivate", "pageActivationDelay", "pageValueRead"}


def page_count(entries) -> int:
    for _sec, lhs, args, _n, _raw in entries:
        if lhs == "nPages" and args:
            try:
                return int(args[0])
            except ValueError:
                pass
    return 1


# ======================================================== what our file has ==
def declared(entries):
    """The two namespaces ts_ini_namespace_proof models: page Constants and
    runtime OutputChannels."""
    consts, chans = set(), set()
    for sec, lhs, _args, _n, _raw in entries:
        if sec in ("Constants", "PcVariables"):
            consts.add(lhs)
        elif sec == "OutputChannels":
            chans.add(lhs)
    return consts, chans


def grammar_checks(entries, corpus, label):
    """RULE ONE - the corpus arity rule."""
    bad = []
    checked = 0
    npages = page_count(entries)
    for sec, lhs, args, n, _raw in entries:
        if lhs in PAGE_KEYWORDS:
            checked += 1
            if len(args) != npages:
                bad.append("%s:%d [%s] %s has %d value(s) for %d page(s)"
                           % (label, n, sec, lhs, len(args), npages))
            continue
        if sec in NAME_SECTIONS and lhs not in SECTION_KEYWORDS.get(sec, set()):
            continue                     # one of our own names, not a keyword
        arities = corpus.get((sec, lhs))
        if not arities:
            continue                     # rusEFI never uses it - nothing to
        checked += 1                     # compare against
        if len(args) not in arities:
            bad.append("%s:%d [%s] %s takes %d, corpus has %s"
                       % (label, n, sec, lhs, len(args), sorted(arities)))
    return checked, bad


def editor_checks(entries, consts, chans, label):
    """RULE TWO - the table and curve editors, explicitly. A shape check alone
    would not catch an axis pointing into the wrong NAMESPACE."""
    problems = []
    tables = collections.OrderedDict()
    curves = collections.OrderedDict()
    cur = None
    kind = None
    for sec, lhs, args, n, _raw in entries:
        if sec == "TableEditor":
            if lhs == "table":
                cur = args[0] if args else "?"
                kind = "table"
                tables[cur] = {"line": n, "args": args}
            elif kind == "table" and cur is not None:
                tables[cur].setdefault(lhs, (args, n))
        elif sec == "CurveEditor":
            if lhs == "curve":
                cur = args[0] if args else "?"
                kind = "curve"
                curves[cur] = {"line": n, "args": args}
            elif kind == "curve" and cur is not None:
                curves[cur].setdefault(lhs, (args, n))
        else:
            cur, kind = None, None

    for tid, d in tables.items():
        if len(d["args"]) != 4:
            problems.append("%s:%d table %s has %d fields, wants 4"
                            % (label, d["line"], tid, len(d["args"])))
        for axis in ("xBins", "yBins", "zBins"):
            if axis not in d:
                problems.append("%s:%d table %s has no %s"
                                % (label, d["line"], tid, axis))
        for axis in ("xBins", "yBins"):
            if axis not in d:
                continue
            args, n = d[axis]
            if len(args) < 2:
                problems.append(
                    "%s:%d table %s %s has %d argument(s); TunerStudio wants "
                    "the axis constant AND its tracing output channel"
                    % (label, n, tid, axis, len(args)))
                continue
            if args[0] not in consts:
                problems.append("%s:%d table %s %s: %s is not a page Constant"
                                % (label, n, tid, axis, args[0]))
            if args[1] not in chans:
                problems.append(
                    "%s:%d table %s %s: %s is not an OutputChannel - the "
                    "second argument is the runtime tracer, not a constant"
                    % (label, n, tid, axis, args[1]))
            if len(args) > 2 and args[2] != "readOnly":
                problems.append("%s:%d table %s %s: third field is %r, only "
                                "readOnly is known"
                                % (label, n, tid, axis, args[2]))
        if "zBins" in d:
            args, n = d["zBins"]
            if args and args[0] not in consts:
                problems.append("%s:%d table %s zBins: %s is not a page "
                                "Constant" % (label, n, tid, args[0]))

    for cid, d in curves.items():
        for k in ("xBins", "yBins"):
            if k not in d:
                problems.append("%s:%d curve %s has no %s"
                                % (label, d["line"], cid, k))
                continue
            args, n = d[k]
            if args[0] not in consts:
                problems.append("%s:%d curve %s %s: %s is not a page Constant"
                                % (label, n, cid, k, args[0]))
    return len(tables), len(curves), problems


def run(path: Path, corpus, label, quiet=False):
    entries = parse(path)
    consts, chans = declared(entries)
    checked, bad = grammar_checks(entries, corpus, label)
    ntab, ncur, problems = editor_checks(entries, consts, chans, label)
    if not quiet:
        print("    %d lines matched a rusEFI keyword; %d tables, %d curves"
              % (checked, ntab, ncur))
    return bad + problems


# ================================================================ mutations ==
NL = chr(10)


def _eighth_field_on_first_frontpage_indicator(text: str) -> str:
    """Give the FIRST [FrontPage] indicator one field too many, wherever it
    happens to be and whatever it is about. 1235 corpus occurrences carry
    seven; eight is the latent V34 defect this mutation exists to prove the
    gate can see."""
    out, in_front, done = [], False, False
    for line in text.splitlines(keepends=True):
        st = line.strip()
        if st.startswith("["):
            in_front = st.startswith("[FrontPage]")
        elif in_front and not done and st.startswith("indicator ="):
            line = line.rstrip("\r\n") + ", black\n"
            done = True
        out.append(line)
    return "".join(out)



def _drop_last_field_of_first_curve_xaxis(text: str) -> str:
    """Give the FIRST [CurveEditor] xAxis two fields where the corpus has
    three - wherever it is, and whatever its numbers are."""
    out, in_curve, done = [], False, False
    for line in text.splitlines(keepends=True):
        st = line.strip()
        if st.startswith("["):
            in_curve = st.startswith("[CurveEditor]")
        elif in_curve and not done and st.startswith("xAxis"):
            head, _sep, rhs = line.partition("=")
            parts = [q.strip() for q in rhs.split(",")]
            if len(parts) >= 3:
                line = "%s= %s\n" % (head, ", ".join(parts[:-1]))
                done = True
        out.append(line)
    return "".join(out)


MUTATIONS = [
    # STRUCTURAL: these anchored on the literal tracer ("fuelRpmAx, rpm",
    # "ignLoadAx, engLoad", "Ignition advance") and went inapplicable when
    # V98 moved the tracers to the fast block and renamed the table. They
    # now match the AXIS, whatever its tracer or title.
    ("an axis with only its constant - THE V34 DEFECT",
     lambda t: re.sub(r"(      xBins = fuelRpmAx), \w+\n",
                      lambda m: m.group(1) + "\n", t, count=1)),
    ("an axis tracer that is a Constant, not an OutputChannel",
     lambda t: re.sub(r"(      yBins = ignLoadAx), \w+\n",
                      lambda m: m.group(1) + ", ignLoadAx\n", t, count=1)),
    ("an axis constant that is really an output channel",
     lambda t: re.sub(r"      xBins = ignRpmAx, (\w+)\n",
                      lambda m: "      xBins = %s, %s\n" % (m.group(1),
                                                           m.group(1)),
                      t, count=1)),
    ("a table with no zBins",
     lambda t: t.replace("      zBins = ignMap\n", "", 1)),
    ("a table line with a missing field",
     lambda t: re.sub(r'(   table = ignMapTbl, ignMapTblMap, "[^"]*"), 1\n',
                      lambda m: m.group(1) + "\n", t, count=1)),
    ("a curve axis pointing at nothing",
     lambda t: t.replace("      xBins = cltEnrAx\n",
                         "      xBins = notAThing\n", 1)),
    # STRUCTURAL, LIKE THE FRONTPAGE ONE BELOW, AND FOR THE SAME REASON.
    # This anchored on the literal `xAxis = 0, 65535, 9`, which existed only
    # while the curve axes were emitted in RAW counts. Converting them to
    # display units - rusEFI writes `xAxis = -40, 120, 9` - made the mutation
    # inapplicable, and the gate would have gone on reporting PASS for a
    # check that no longer ran. THIRD TIME IN THIS SESSION: a mutation
    # anchored on literal text is a check with a shelf life.
    ("a curve xAxis with the wrong number of fields",
     lambda t: _drop_last_field_of_first_curve_xaxis(t)),
    # STRUCTURAL, NOT LITERAL. This anchored on `indicator = { benchSafe }`
    # and went silently inapplicable the moment the front page was rebuilt
    # around what a tuner acts on. A mutation that no longer applies is a
    # gate check that has quietly stopped testing anything.
    ("an eighth field on a FrontPage indicator - THE LATENT V34 DEFECT",
     lambda t: _eighth_field_on_first_frontpage_indicator(t)),
    ("a page keyword carrying more values than there are pages",
     lambda t: t.replace("   pageSize       = 4096" + NL,
                         "   pageSize       = 4096, 4096" + NL, 1)),
]


def mutate(path: Path, corpus):
    """Each defect must produce a problem the CLEAN file does not have.

    Comparing against the clean baseline rather than against "any problem at
    all" is the difference between a mutation test and a decoration: while five
    false positives were still in this file, every mutation "passed" on one of
    those instead of on the defect it had just injected."""
    print("\n=== MUTATIONS - each defect must be CAUGHT ===\n")
    base = path.read_text(errors="replace")
    baseline = set(x.split(":", 1)[1] for x in run(path, corpus, "MUT",
                                                   quiet=True))
    tmp = ROOT / "tunerstudio/.grammar_mutation.ini"
    for name, fn in MUTATIONS:
        text = fn(base)
        if text == base:
            check("mutation applies: %s" % name, False,
                  "the anchor is not in the file - fix the mutation")
            continue
        tmp.write_text(text, encoding="ascii", newline="\n")
        try:
            found = run(tmp, corpus, "MUT", quiet=True)
        finally:
            tmp.unlink(missing_ok=True)
        fresh = [x for x in found if x.split(":", 1)[1] not in baseline]
        check("caught: %s" % name, bool(fresh),
              fresh[0].split(":", 1)[1][:70] if fresh else "NOT CAUGHT")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ini", type=Path, default=None)
    ap.add_argument("--mutate", action="store_true", default=True)
    ap.add_argument("--no-mutate", dest="mutate", action="store_false")
    args = ap.parse_args()

    print("=== HaniCore - does every .ini line have a shape TunerStudio "
          "accepts? ===\n")
    corpus, files = build_corpus()
    check("the rusEFI corpus is present and substantial",
          len(files) >= 3 and len(corpus) >= 60,
          "%d files, %d (section, keyword) pairs" % (len(files), len(corpus)))
    if len(files) < 3:
        print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
        return 1
    check("and it knows the keyword that broke V34",
          ("TableEditor", "xBins") in corpus
          and 1 not in corpus[("TableEditor", "xBins")],
          "[TableEditor] xBins arities seen: %s"
          % sorted(corpus[("TableEditor", "xBins")]))
    check("and the one that was waiting behind it",
          corpus.get(("FrontPage", "indicator")) == {7},
          "[FrontPage] indicator arities seen: %s"
          % sorted(corpus.get(("FrontPage", "indicator"), [])))

    stem = PI.STEM.replace("HaniCore_ME711_", "hanicore_me711_").lower()
    targets = [args.ini] if args.ini else [
        LIVE_INI,
        ROOT / ("tunerstudio/%s.ini" % stem),
    ]
    for t in targets:
        if not t.exists():
            check("target present: %s" % t.name, False, "missing")
            continue
        print("\n  --- %s" % t.name)
        problems = run(t, corpus, t.name)
        check("every line in %s has a shape rusEFI also uses" % t.name,
              not problems,
              "clean" if not problems else "%d problem(s)" % len(problems))
        for p in problems[:12]:
            print("        %s" % p)

    if args.mutate:
        mutate(targets[0], corpus)

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("\nGRAMMAR PROOF FAILS - %d check(s)." % FAILS)
        return 1
    print("\nGRAMMAR PROOF PASSES - every keyword this file shares with "
          "rusEFI carries an\nargument count rusEFI also uses, and both "
          "editors resolve into the right\nnamespaces. IT STILL DOES NOT "
          "PROVE TUNERSTUDIO LOADS THE FILE - only a human\nwith TunerStudio "
          "open can do that.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
