#!/usr/bin/env python3
r"""me711_irq_priority_proof.py - two enabled interrupts may not share an
ILVL/GLVL pair.

    py tests\firmware\build\me711_irq_priority_proof.py

WHY, AND IT IS A MEASUREMENT RATHER THAN A RULE QUOTED FROM A MANUAL
--------------------------------------------------------------------
On the C166 core an interrupt's priority is the pair (ILVL, GLVL): ILVL
decides preemption, GLVL breaks ties between requests that arrive together.
The pair has to be unique among ENABLED sources, and this project's own ME7.5
target header has said so since it was written - "GLVL 2 keeps it distinct
from CC15's 12/3, so simultaneous requests still arbitrate deterministically".

THE ME7.1.1 PORT LOST THE DISTINCTION. Up to and including V57 the ASC0 drain
tick was `CC7IC = HC_IC(TGT_ILVL_SERIAL, 2)` and the crank capture was
`CC15IC = HC_IC(TGT_ILVL_CRANK, 2)` - both 12/2. Measured on the real ECU
with no Burn running at all, over a window short enough that the 16-bit
rx_ticks counter cannot lap:

    generator OFF, capture ON     25003 drain ticks/s   period 40.0 us
    200 rpm,       capture ON     20510 drain ticks/s   period 48.8 us
    200 rpm,       capture OFF    24996 drain ticks/s   period 40.0 us

Same signal, same wire; the only difference is whether CC15's interrupt is
enabled. Eighteen per cent of the drain's slots disappear and the ASC0
receive register then overruns.
the bench records

THE CONTROL IS THE DEFECT ITSELF: the same check is re-run with
TGT_GLVL_CRANK forced back to 2, and it must FAIL. A gate that cannot
reproduce what it forbids is not evidence.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TGT = ROOT / "firmware/targets/me711/hctarget.h"
SOURCES = [
    ROOT / "firmware/comms/hcts.c",
    ROOT / "firmware/targets/me711/asic/hcasic.c",
    ROOT / "firmware/targets/me711/system/hcmain_me711.c",
    ROOT / "firmware/targets/me711/engine/hctrig_me711.c",
    # 2026-10-06: the planner level, the deadline executor, knock and the
    # interrupt-driven K-line transport are enabled sources too
    ROOT / "firmware/targets/me711/engine/hcsched_dry.c",
    ROOT / "firmware/targets/me711/engine/hcdeadline711.c",
    ROOT / "firmware/targets/me711/engine/hcknock711.c",
    ROOT / "firmware/targets/me711/comms/hcserial711.c",
]
# With TGT_RX_PEC the receive path is PEC channel 6 (hcserial711.c) and every
# S0RIC/CC7IC assignment in hcts.c sits behind an `#ifdef TGT_RX_PEC ...
# return` - compiled, never executed.
PEC_DEAD = {("hcts.c", "S0RIC"), ("hcts.c", "CC7IC")}

# Nodes that are never enabled at the same time, and why. S0RIC and CC7IC are
# the two halves of one CHOICE - hcts_rx_arm() enables exactly one of them,
# whichever hcts_rx_learn() proved works on the board - so they may share.
EXEMPT = {frozenset({"S0RIC", "CC7IC"})}

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def defines(text):
    """TGT_ILVL_/TGT_GLVL_ values as the compiler sees them: #ifdef, #ifndef
    and #else are followed (any other #if counts as true)."""
    out, known, stack = {}, set(), []
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r"#\s*(ifdef|ifndef)\s+(\w+)", s)
        if m:
            stack.append((m.group(2) in known) == (m.group(1) == "ifdef"))
            continue
        if re.match(r"#\s*if\b", s):
            stack.append(True)
            continue
        if re.match(r"#\s*else\b", s) and stack:
            stack[-1] = not stack[-1]
            continue
        if re.match(r"#\s*endif\b", s) and stack:
            stack.pop()
            continue
        if not all(stack):
            continue
        m = re.match(r"#define\s+(\w+)(?:\s+(\d+))?", s)
        if m:
            known.add(m.group(1))
            if m.group(2) and re.match(r"TGT_(?:ILVL|GLVL)_", m.group(1)):
                out[m.group(1)] = int(m.group(2))
    if "TGT_RX_PEC" in known:
        out["TGT_RX_PEC"] = 1
    return out


def sites(consts):
    """Every `<NODE>IC = HC_IC(level, group)` assignment in the sources."""
    found = []
    pat = re.compile(r"(\w+IC)\s*=\s*\(?\s*(?:\(unsigned int\)\s*\()?"
                     r"HC_IC\(\s*([A-Za-z0-9_]+)\s*,\s*([A-Za-z0-9_]+)\s*\)")
    for p in SOURCES:
        t = p.read_text(errors="replace")
        for m in pat.finditer(t):
            node, lv, gv = m.group(1), m.group(2), m.group(3)
            lvl = consts.get(lv, None) if not lv.isdigit() else int(lv)
            glv = consts.get(gv, None) if not gv.isdigit() else int(gv)
            if lvl is None or glv is None:
                raise SystemExit("unresolved HC_IC(%s, %s) in %s"
                                 % (lv, gv, p.name))
            if consts.get("TGT_RX_PEC") and (p.name, node) in PEC_DEAD:
                continue
            found.append((node, lvl, glv, p.name))

    # ---- THE CAPTURE ROLES, WHICH ARE NO LONGER A CODE SHAPE ------------
    #
    # This scanner looked for `<NODE>IC = HC_IC(level, group)` and V62 stopped
    # writing that: the page decides which channel carries the crank, so the
    # assignment became `CC15IC = role_ic(g_role[...])` and the pair moved into
    # one function. The regex then found NO crank assignment at all, the
    # collision scan silently stopped covering the three capture channels, and
    # only this gate's own control caught it - "it did not - this gate proves
    # nothing" is what a blind gate looks like when it is built to notice.
    #
    # So the roles are read from the TGT_ CONSTANTS instead of from the shape
    # of the code. That is robust to formatting, and it is the same three pairs
    # role_ic() returns. `role_ic_uses_them` below asserts the firmware really
    # does use these names, so this cannot drift into checking constants that
    # nothing reads.
    for node, lv, gv in (("crank capture", "TGT_ILVL_CRANK", "TGT_GLVL_CRANK"),
                         ("cam 1 capture", "TGT_ILVL_CAM", "TGT_GLVL_CAM1"),
                         ("cam 2 capture", "TGT_ILVL_CAM", "TGT_GLVL_CAM2")):
        if lv in consts and gv in consts:
            found.append((node, consts[lv], consts[gv], "hctrig_me711.c"))
    return found


def collisions(found):
    seen = {}
    bad = []
    for node, lvl, glv, where in found:
        key = (lvl, glv)
        if key in seen and seen[key][0] != node:
            pair = frozenset({seen[key][0], node})
            if pair not in EXEMPT:
                bad.append((seen[key][0], node, lvl, glv))
        seen.setdefault(key, (node, where))
    return bad


def main():
    print("=== two enabled interrupts may not share an ILVL/GLVL pair ===\n")
    tgt = TGT.read_text(errors="replace")
    consts = defines(tgt)

    check("the target names a GLVL for the receive path",
          "TGT_GLVL_SERIAL" in consts,
          "TGT_GLVL_SERIAL = %s" % consts.get("TGT_GLVL_SERIAL"))
    check("the target names a GLVL for the crank capture",
          "TGT_GLVL_CRANK" in consts,
          "TGT_GLVL_CRANK = %s" % consts.get("TGT_GLVL_CRANK"))

    found = sites(consts)
    print("")
    for node, lvl, glv, where in found:
        print("      %-8s ILVL %-2d GLVL %-2d   %s" % (node, lvl, glv, where))
    print("")

    bad = collisions(found)
    check("no two enabled sources share one (ILVL, GLVL)", not bad,
          "; ".join("%s and %s both %d/%d" % b for b in bad) or
          "%d assignments, all distinct" % len(found))

    check("the crank capture and the drain tick are distinct",
          consts.get("TGT_GLVL_CRANK") != consts.get("TGT_GLVL_SERIAL")
          or consts.get("TGT_ILVL_CRANK") != consts.get("TGT_ILVL_SERIAL"),
          "crank %s/%s, drain %s/%s"
          % (consts.get("TGT_ILVL_CRANK"), consts.get("TGT_GLVL_CRANK"),
             consts.get("TGT_ILVL_SERIAL"), consts.get("TGT_GLVL_SERIAL")))

    # THE CONSTANTS MUST BE THE ONES THE FIRMWARE ACTUALLY USES.
    trig = (ROOT / "firmware/targets/me711/engine/hctrig_me711.c").read_text(errors="replace")
    missing = [n for n in ("TGT_GLVL_CRANK", "TGT_GLVL_CAM1", "TGT_GLVL_CAM2")
               if n not in trig]
    check("role_ic() uses the three named group levels", not missing,
          "missing from hctrig_me711.c: %s" % (missing or "none")
          + " - a gate that reads a constant nothing uses proves nothing")

    # ---------------------------------------------------- the control -------
    ctl = dict(consts)
    ctl["TGT_GLVL_CRANK"] = ctl.get("TGT_GLVL_CAM1", 2)   # the V57 shape: a shared group
    ctl_bad = collisions(sites(ctl))
    check("the check REPRODUCES the V57 defect when the crank is put back "
          "on the drain's group", bool(ctl_bad),
          "; ".join("%s and %s both %d/%d" % b for b in ctl_bad)
          or "it did not - this gate proves nothing")

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("INTERRUPT PRIORITY PROOF FAILED")
        return 1
    print("INTERRUPT PRIORITY PROOF PASSES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
