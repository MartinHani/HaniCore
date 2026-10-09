#!/usr/bin/env python3
r"""
me711_page_reader_audit.py - which page fields does the LINKED ME7.1.1 image
actually read at runtime, and does the TunerStudio interface say so?

    py tests\tunerstudio\me711_page_reader_audit.py              THE GATE (Tier 1): the UI
                                                     and the image agree
    py tests\tunerstudio\me711_page_reader_audit.py --table      every field and its class
    py tests\tunerstudio\me711_page_reader_audit.py --dead       only the fields nothing uses
    py tests\tunerstudio\me711_page_reader_audit.py --self-test  the gate must catch both
                                                     directions of disagreement

WHY. the project rules: "A dead knob is allowed; a silent one is not."
ts_ini_dead_knob_proof holds that line for the DBW slots only. On V89 the same
question asked of the WHOLE page found, among others, that no linked module
reads revLimit / revlimMode / revlimPattern - there is no rev limiter in the
ME7.1.1 build (ENG_CUT_REV is ORed in only by the deferred ME7.5 scheduler) -
while TunerStudio offered "Limits and fallbacks" as if there were. Idle
control, closed-loop boost, the CLT/oil protections and the motorsport
functions were in the same state.

HOW. A field is identified by the macro its Meta() row defines
(tools/config_source/hanicore_config_def.py), which is the name every C
reader uses (hc_config_generated.h). The linked modules are those whose
object the image-under-test's linker map (me711_image.MAP) names. A module's
use of the macro is classified:

    RUNTIME     read by a linked module other than the ones below
    VALIDATED   only hc_validation.c - checked, never used to run the engine
    SEEDED      only hc_config_manager.c / hc_presets.c - default-written
    NONE        no linked module names it at all

hcconfig.c is the page DEFINITION and never counts (the same exclusion
ts_ini_dead_knob_proof makes, for the same reason).

LIMITS, stated so nobody reads more into it: this is a TEXT search of C
sources for the defining macro, resolved against the linked module list. A
field read by computed offset or from assembly would be reported NONE. So a
NONE is a question to answer before a caption claims "unused", not an answer.
Every entry of gen_ts_ux_me711.UNUSED was checked by hand as well (V89: all
SEEDED hits are hc_cal_set_* default writes; the only config-manager READS are
the uMagic / uSchema identity checks, which are exempt).

THE GATE, in both directions (the shape ts_ini_dead_knob_proof has for DBW):

  1. a field the UI PLACES that the image does not read at runtime must be in
     gen_ts_ux_me711.UNUSED (or UNUSED_EXEMPT / NOT_SHOWN) - no silent dead
     knob;
  2. a field in UNUSED must NOT be read at runtime - implement it and the
     "(not used)" label has to go, or the UI lies the other way;
  3. every placed UNUSED field carries the words "not used" in its label in
     the GENERATED .ini, and every curve/table editor whose values are UNUSED
     says "not used" / "not implemented" in its menu entry.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths as HCP  # noqa: E402

SHARED = ROOT / "firmware"
TGT = ROOT / "firmware/targets/me711"
DEF = ROOT / "tools/config_source/hanicore_config_def.py"
INI = ROOT / "tunerstudio/hanicore_me711.ini"
pass  # (bootstrap above)
import me711_image as _IMG  # noqa: E402  the ONE place that names the image
MAP = _IMG.MAP

NOT_A_READER = {"hcconfig.c"}
VALIDATION = {"hc_validation.c"}
# hcdefaults711.c is the BOARD-DEFAULT WRITER, extracted from hcconfig.c
# (which is NOT_A_READER). It only ever calls hc_cal_set_*, so naming a
# field there is seeding, not a runtime read; while it was missing from
# this set the gate called eleven honestly-unused fields a lying label.
SEEDING = {"hc_config_manager.c", "hc_presets.c", "hc_config_generated.c",
           "hcdefaults711.c"}


def linked_modules():
    if not MAP.exists():
        raise SystemExit("no linker map %s - build the image first" % MAP)
    m = MAP.read_text(errors="replace").lower()
    out = []
    for p in HCP.sources("me711", "*.c"):
        if re.search(r"\b%s\b" % re.escape(p.stem.lower()), m):
            out.append(p)
    return out


def classify():
    mods = {p.name: p.read_text(errors="replace") for p in linked_modules()}
    rows = re.findall(r'Meta\("((?:CAL|CFG)_[A-Z0-9_]+)",\s*"(\w+)"',
                      DEF.read_text(errors="replace"))
    out = []
    for macro, ts in rows:
        pat = re.compile(r"\b%s\b" % re.escape(macro))
        who = sorted(n for n, t in mods.items()
                     if n not in NOT_A_READER and pat.search(t))
        run = [n for n in who if n not in VALIDATION | SEEDING]
        if run:
            cls = "RUNTIME"
        elif any(n in VALIDATION for n in who):
            cls = "VALIDATED"
        elif who:
            cls = "SEEDED"
        else:
            cls = "NONE"
        out.append((ts, macro, cls, who))
    return out, len(mods)


def check(unused=None, exempt=None, verbose=True):
    import gen_ts_ux_me711 as UX
    import gen_ts_ui_me711 as UI
    unused = set(UX.UNUSED) if unused is None else set(unused)
    exempt = set(UX.UNUSED_EXEMPT) if exempt is None else set(exempt)
    cls = {ts: c for ts, _m, c, _w in classify()[0]}
    placed = UX.placed_fields()
    fails = []
    for ts in sorted(placed):
        c = cls.get(ts, "RUNTIME")
        if c != "RUNTIME" and ts not in unused | exempt | set(UX.NOT_SHOWN):
            fails.append("SILENT     %s is shown and the image never reads it "
                         "(%s) - add it to UNUSED with a reason" % (ts, c))
    for ts in sorted(unused):
        if cls.get(ts) == "RUNTIME":
            fails.append("LIES       %s is labelled unused but the image READS "
                         "it - remove it from UNUSED" % ts)

    text = INI.read_text(encoding="utf-8", errors="replace")
    for ts in sorted(unused & placed):
        labels = re.findall(r'field\s*=\s*"([^"]*)"\s*,\s*%s\d*\s*(?:,|$)'
                            % re.escape(ts), text, re.M)
        if not labels:
            fails.append("UNPLACED   %s is UNUSED and placed, but no field "
                         "line binds it in %s" % (ts, INI.name))
        for lbl in labels:
            if "not used" not in lbl:
                fails.append("UNLABELLED %s is shown as %r" % (ts, lbl))

    menu = dict(re.findall(
        r'(?:subMenu|groupChildMenu)\s*=\s*(\w+)\s*,\s*"([^"]*)"', text))
    dead_menu = re.compile(r"not used|not implemented")
    for cid, _x, y, *_rest in UI.CURVES:
        if y in unused and cid in menu and not dead_menu.search(menu[cid]):
            fails.append("UNLABELLED curve %s (%s) is %r in the menu"
                         % (cid, y, menu[cid]))
    for t in UI.TABLES:
        tid, z = t[0], t[1]
        for mid in (tid + "Edit", tid + "3D"):
            if z in unused and mid in menu and not dead_menu.search(menu[mid]):
                fails.append("UNLABELLED table %s (%s) is %r in the menu"
                             % (mid, z, menu[mid]))
    if verbose:
        for f in fails:
            print("  FAIL " + f)
    return fails


def self_test() -> int:
    import gen_ts_ux_me711 as UX
    ok = True
    base = check(verbose=False)
    print("  [%s] baseline is clean%s" % ("PASS" if not base else "FAIL",
                                          "" if not base else ": %s" % base))
    ok &= not base
    # THE PROBE IS CHOSEN FROM THE LIVE LISTS, NOT HARDCODED. This read
    # "revLimit" from V89, when nothing in the image implemented a rev
    # limiter; V98 added one, revLimit left UNUSED, and removing it from a
    # set it was no longer in mutated nothing - the control had quietly
    # stopped testing while still printing a verdict.
    cls = {ts: c for ts, _m, c, _w in classify()[0]}
    placed = UX.placed_fields()
    dead = sorted(ts for ts in set(UX.UNUSED) & placed
                  if cls.get(ts) != "RUNTIME"
                  and ts not in set(UX.UNUSED_EXEMPT) | set(UX.NOT_SHOWN))
    if not dead:
        print("  [FAIL] no placed UNUSED field left to mutate - this control "
              "cannot test anything")
        ok = False
    else:
        probe = dead[0]
        a = check(unused=set(UX.UNUSED) - {probe}, verbose=False)
        hit = any(f.startswith("SILENT") and probe in f for f in a)
        print("  [%s] a dead knob dropped from UNUSED (%s) reads SILENT"
              % ("PASS" if hit else "FAIL", probe))
        ok &= hit
    b = check(unused=set(UX.UNUSED) | {"tps1Min"}, verbose=False)
    hit = any(f.startswith("LIES") and "tps1Min" in f for f in b)
    print("  [%s] a live field added to UNUSED (tps1Min) reads LIES"
          % ("PASS" if hit else "FAIL"))
    ok &= hit
    print("\nSELF-TEST %s" % ("PASSES" if ok else "FAILS"))
    return 0 if ok else 1


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    if "--table" in sys.argv or "--dead" in sys.argv:
        rows, nmods = classify()
        dead_only = "--dead" in sys.argv
        print("linked modules: %d (from %s)" % (nmods, MAP.relative_to(ROOT)))
        counts = {}
        for ts, macro, cls, who in rows:
            counts[cls] = counts.get(cls, 0) + 1
            if dead_only and cls == "RUNTIME":
                continue
            print("  %-9s %-22s %-28s %s" % (cls, ts, macro, ", ".join(who)))
        print("\n" + "  ".join("%s %d" % kv for kv in sorted(counts.items())))
        return 0

    print("=== the UI's 'not used' labels agree with the linked image ===")
    fails = check()
    rows, nmods = classify()
    n = sum(1 for r in rows if r[2] != "RUNTIME")
    print("  %d linked modules; %d of %d page fields are not read at runtime"
          % (nmods, n, len(rows)))
    print("PAGE READER AUDIT %s" % ("PASSES" if not fails else
                                    "FAILS (%d)" % len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
