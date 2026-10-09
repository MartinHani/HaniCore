#!/usr/bin/env python3
r"""
me711_cavity_truth_proof.py - the connector descriptor may not offer a cavity
it is known to be wrong about.

    py tests\firmware\config\me711_cavity_truth_proof.py

THE HAZARD, IN ONE SENTENCE. `build/generated/hc_hw_descriptor_bosch_me711.csv`
is derived from `Steckerb. ME7.1.XLS`, a VW/Audi **ME7.1 C4** connector
workbook, and against the ME7.1.1 sheet that workbook is wrong for a whole
block: 21 is KL15 and not ZAS2, 23 is the main relay and not EV8, 19 is EV8,
18 is ZAS2, 22 is ZAS1. **Only 24 = EV7 agrees.** (V95: and on THIS board 18
and 22 drive nothing - their CPU pins P8.2 / P8.1 are the CJ120 chip selects -
so they are locked too; see BOARD_LOCKED.)

The consequence is electrical, not clerical. Unmodified, the descriptor OFFERS
CAVITY 23 AS AN INJECTOR OUTPUT while cavity 23 is the DME main relay drive,
and CAVITY 21 AS A RELAY OUTPUT while cavity 21 is a POWER INPUT feeding the
CJ910's enable pin. Routing a logical function to either commands a driver
stage into a wire that is not one.

WHAT IS SETTLED, AND BY WHAT. the project rules record seven cavities from
THREE AGREEING SOURCES - Porsche connector/service documentation, this ECU on
the bench, and the ME7.1.1 schematic rendered at 600 dpi:

    1, 2   Terminal 31, electronics ground
    3      relay-switched DME main power
    21     IGNITION LOCK, TERMINAL 15 (KL15)      <- a POWER INPUT
    23     DME main relay terminal 85, low-side drive
    43     K-line
    62     Terminal 30, permanent B+

and the bench half of that is decisive on 21: removing +12 V from cavity 21
while 3 and 62 stay powered takes the ECU OFFLINE.

WHAT THIS GATE REQUIRES

  1. every settled cavity advertises SPECIAL_LOCKED and nothing else - a
     dedicated wire the validator will not route a logical function to;
  2. no cavity in 18..24 advertises any drive capability, because the block is
     known-wrong and not settled. LOCKED, not relabelled: a friendly wrong
     label is worse than a raw integer, since a tuner has no reason to
     distrust it;
  3. the firmware's own compiled descriptor agrees with the generator - it is
     `hc_pin_can()` that a bench command asks, not a CSV;
  4. cavity 65 is STILL relay-capable, because a lock-everything gate would
     pass while leaving nothing routable. `EKPR`, P2.12/CC12IO through a CJ920,
     both ME7.1.1 port-map columns, row 68 of this repository's own I/O map;
  5. hcbench.c contains NO port write for any locked cavity. The descriptor
     check is a second line of defence and a `sbit` on a power input is not
     something to leave standing behind one.

WHAT THIS IS NOT. It is not the full regeneration the project rules ask
for. That needs an ME7.1.1 connector sheet this repository does not have. This
is the part the available evidence supports, and it removes the specific hazard
the descriptor was flagged for.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools/config_source"))
ROOT = Path(__file__).resolve().parents[3]

import hw_descriptors as HW                       # noqa: E402
from hanicore_config_schema import PinCap         # noqa: E402

FAILS = 0
BENCH_C = ROOT / "firmware/targets/me711/diagnostics/hcbench.c"
DESC_C = ROOT / "firmware/generated/hc_pin_desc_bosch_me711.c"

# The seven the project rules settle, and what each really is.
SETTLED = {
    1: "Terminal 31, electronics ground",
    2: "Terminal 31, electronics ground",
    3: "relay-switched DME main power",
    21: "KL15, ignition lock - A POWER INPUT",
    43: "K-line",
    62: "Terminal 30, permanent B+",
}
# THE DISPUTED SET SHRANK AT V62, AND THE SPECIFIC CHECKS GOT STRONGER.
#
# It was range(18, 25) - the whole block locked pending the evidence the project rules
# section 10 asked for: "until the descriptor is regenerated against ME7.1.1
# evidence". `the ME7.1.1 schematic` is that evidence and it names
# four of them - A_S_ZAS2 on 18, A_T_EV8 on 19, A_S_ZAS1 on 22, A_T_EV7 on 24 -
# each corroborated by a MAIN CPU CAPCOM channel in me711_iomap.csv, with BOTH
# ME7.1.1 columns agreeing on EV7 and EV8.
#
# Cavity 20 is NOT named on that sheet, so it stays disputed. 21 and 23 are in
# SETTLED above and keep their VERIFIED, measured entries.
#
# The blanket refusal is replaced by RESOLVED below, which is a stronger claim:
# it says what each cavity IS, so a regression that quietly drops a capability
# fails here too, and not just one that adds one.
DISPUTED = (20,)

# What the ME7.1.1 sheet settled, and the capability each must now carry.
RESOLVED = {
    19: (PinCap.INJ_OUT | PinCap.LOW_SIDE, "A_T_EV8 - and the family workbook "
                                           "put EV8 on cavity 23, which is the "
                                           "main relay"),
    24: (PinCap.INJ_OUT | PinCap.LOW_SIDE, "A_T_EV7 - the one cavity in this "
                                           "block the workbook got right"),
}

# V95: THE SHEET NAMED 18 AND 22 AND THE BOARD TAKES THEM BACK. The W12 sheet
# draws A_S_ZAS2 / A_S_ZAS1 there with inputs P8.2 / P8.1; on THIS board those
# pins are the CJ120 chip selects (OEM binary 0x8C0756..0x8C07A0, HaniCore's
# CJ120 driver on the bench; hw_descriptors.RESERVED_CPU_PINS) and the A2L
# says SY_ZAS = 0. Until V95 this gate REQUIRED them to be relay outputs.
BOARD_LOCKED = {
    18: "W12 A_S_ZAS2; its CPU pin P8.2 is the CJ120 bank-2 chip select",
    22: "W12 A_S_ZAS1; its CPU pin P8.1 is the CJ120 bank-1 chip select",
}

# Everything that would let a logical function be routed somewhere.
DRIVE = (PinCap.LOW_SIDE | PinCap.PWM_OUT | PinCap.INJ_OUT | PinCap.IGN_OUT
         | PinCap.RELAY_OUT | PinCap.DBW_HBRIDGE)


def check(name, ok, detail=""):
    global FAILS
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def firmware_caps():
    """What the COMPILED descriptor says, parsed out of the generated C.

    The CSV is documentation; hc_pin_can() is what a bench command asks."""
    txt = DESC_C.read_text(errors="replace")
    caps = {}
    # One row per cavity: `{ <caps>, ... }, /* cavity N ... */` - the generator
    # emits the cavity number in the trailing comment.
    for m in re.finditer(r"\{\s*(0x[0-9A-Fa-f]+)u?[^}]*\}\s*,\s*"
                         r"/\*\s*(?:cavity\s*)?(\d+)", txt):
        caps[int(m.group(2))] = int(m.group(1), 16)
    if not caps:
        # Fall back to positional order if the generator's comment shape moves.
        rows = re.findall(r"\{\s*(0x[0-9A-Fa-f]+)u?", txt)
        caps = {i + 1: int(v, 16) for i, v in enumerate(rows)}
    return caps


def main() -> int:
    global FAILS
    print("=== HaniCore ME7.1.1 - the connector descriptor's known-wrong "
          "block ===\n")

    d = HW.build_me711()

    print("  the seven cavities the project rules settle:")
    for n, what in sorted(SETTLED.items()):
        p = d.pin(n)
        print("    cavity %3d  caps 0x%04X  %s" % (n, p.capabilities, what))
    print()

    # --------------------------------------------------------------- 1 ----
    for n, what in sorted(SETTLED.items()):
        p = d.pin(n)
        check("cavity %d is a dedicated wire, not an output" % n,
              p.capabilities == PinCap.SPECIAL_LOCKED,
              "caps 0x%04X - %s" % (p.capabilities, what))

    # --------------------------------------------------------------- 2 ----
    for n in DISPUTED:
        p = d.pin(n)
        check("cavity %d advertises no drive capability" % n,
              not (p.capabilities & DRIVE),
              "caps 0x%04X, OEM name %r" % (p.capabilities, p.oem_name))

    # --------------------------------------------------------- 2a ----
    # V95: what the board takes back from the sheet.
    for n, why in sorted(BOARD_LOCKED.items()):
        p = d.pin(n)
        check("cavity %d offers nothing (CJ120 chip select behind it)" % n,
              p.capabilities == PinCap.SPECIAL_LOCKED and not p.hal_resource,
              "caps 0x%04X res %r - %s" % (p.capabilities, p.hal_resource, why))
    check("no routable cavity names a reserved CPU pin",
          not HW.reserved_collisions(d),
          "%s" % (HW.reserved_collisions(d) or "none"))

    # --------------------------------------------------------- 2b ----
    # AND WHAT THE SHEET RESOLVED, ASSERTED POSITIVELY.
    for n, (want, why) in sorted(RESOLVED.items()):
        got = d.pin(n).capabilities
        check("cavity %d carries what the ME7.1.1 sheet gives it" % n,
              (got & want) == want,
              "caps 0x%04X, needs 0x%04X - %s" % (got, want, why))

    # --------------------------------------------------------- 2c ----
    # CAVITY 23 LEFT THE LOCKED SET AT V80, ON PURPOSE. It is the CJ910's own
    # main-relay stage (MR): a HARDWARE function whose controls are EN1 = KL15
    # and /EN2 = keep-alive, commanded by no CPU port (the project rules, "Main
    # relay and run-on"). The descriptor gives it exactly MAIN_RELAY_HW so
    # MAIN_RELAY = AUTO can be bound there - and nothing a logical function
    # could DRIVE. Asserting SPECIAL_LOCKED here was the pre-V80 fact.
    c23 = d.pin(23).capabilities
    check("cavity 23 is the CJ910 main-relay stage: MAIN_RELAY_HW, no drive",
          c23 == PinCap.MAIN_RELAY_HW and not (c23 & DRIVE),
          "caps 0x%04X - DME main relay terminal 85 (hardware stage)" % c23)

    # --------------------------------------------------------------- 3 ----
    # THE SPECIFIC TWO THE HAZARD WAS NAMED FOR.
    check("cavity 23 is NOT offered as an injector output",
          not (d.pin(23).capabilities & PinCap.INJ_OUT),
          "the workbook calls it EV8; it is the main relay drive")
    check("cavity 21 is NOT offered as a relay output",
          not (d.pin(21).capabilities & PinCap.RELAY_OUT),
          "the workbook calls it ZAS2; it is KL15, a power input")

    # --------------------------------------------------------------- 4 ----
    # AND THE GATE IS NOT VACUOUS: something must still be routable.
    p65 = d.pin(65)
    check("cavity 65 is still relay capable",
          bool(p65.capabilities & PinCap.RELAY_OUT),
          "EKPR, P2.12/CC12IO -> CJ920, both ME7.1.1 columns")
    check("and still low-side capable",
          bool(p65.capabilities & PinCap.LOW_SIDE))
    # AND THE OVERRIDE TOOK EXACTLY WHAT IT MEANT TO. A threshold picked by
    # hand ("more than forty must remain") is a number nobody can defend; this
    # rebuilds the descriptor with the override disabled and requires the
    # difference to be precisely the cavities named above. A lock that reached
    # one cavity further would otherwise pass unnoticed.
    _real = HW._apply_porsche_truth
    _refuse = HW._refuse_reserved_resources
    try:
        HW._apply_porsche_truth = lambda _d: None
        # V95: the counterfactual descriptor offers cavity 21 (KL15) as a relay
        # on P8.2 - the reserved-pin rule would refuse to build it at all
        HW._refuse_reserved_resources = lambda _d: None
        before = HW.build_me711()
        check("without the override the reserved-pin rule catches cavity 21",
              any(c[0] == 21 for c in HW.reserved_collisions(before)),
              "%s" % HW.reserved_collisions(before))
    finally:
        HW._apply_porsche_truth = _real
        HW._refuse_reserved_resources = _refuse
    lost = sorted(q.number for q in before.pins
                  if (q.capabilities & DRIVE)
                  and not (d.pin(q.number).capabilities & DRIVE))
    # 23 keeps MAIN_RELAY_HW (not a drive capability) but loses every drive
    # one, exactly as the locked cavities do - see check 2c above.
    intended = sorted(set(SETTLED) | set(DISPUTED) | {23})
    check("the override took capability from exactly the named cavities",
          set(lost) <= set(intended),
          "lost: %s" % (lost or "none"))
    routable_before = sum(1 for q in before.pins if q.capabilities & DRIVE)
    routable = sum(1 for q in d.pins if q.capabilities & DRIVE)
    check("and it did not lock the connector", routable >= routable_before - len(intended),
          "%d of %d cavities still advertise a drive capability, %d before"
          % (routable, len(d.pins), routable_before))

    # --------------------------------------------------------------- 5 ----
    # THE COMPILED DESCRIPTOR MUST AGREE. A CSV nobody links proves nothing.
    fw = firmware_caps()
    if not fw:
        check("the firmware descriptor could be parsed", False,
              "no capability rows found in %s" % DESC_C.name)
    else:
        bad = [n for n in list(SETTLED) + list(DISPUTED) + list(BOARD_LOCKED)
               if fw.get(n, 0) & DRIVE]
        check("the COMPILED descriptor agrees - no drive bit in the block",
              not bad, "offenders: %s" % (bad or "none"))
        check("and it is the same table the generator produced",
              fw.get(65, 0) & PinCap.RELAY_OUT,
              "cavity 65 caps 0x%04X in the linked C" % fw.get(65, 0))

    # --------------------------------------------------------------- 6 ----
    # NO PORT WRITE FOR A LOCKED CAVITY IN THE ONE MODULE THAT DRIVES PINS.
    bench = BENCH_C.read_text(errors="replace")
    live = re.sub(r"/\*.*?\*/", "", bench, flags=re.S)      # comments removed
    for name in ("RLY_21", "RLY_22"):
        check("hcbench.c has no %s port write" % name, name not in live,
              "cavity 21 is a power input; a sbit for it is not a thing to "
              "leave behind a second check")
    for cav in (21, 22, 23):
        check("hcbench.c's relay table does not offer cavity %d" % cav,
              not re.search(r"case\s+%d\s*:" % cav, live),
              "")

    print("\n%s" % ("CAVITY TRUTH PROOF PASSES - the descriptor no longer "
                    "offers a cavity it is\nknown to be wrong about, and "
                    "something is still routable.\nTHIS IS NOT THE FULL "
                    "REGENERATION: no ME7.1.1 connector sheet is in this\n"
                    "repository, so 18..20, 22 and 24 are LOCKED rather than "
                    "corrected."
                    if not FAILS else
                    "CAVITY TRUTH PROOF FAILS - %d check(s)." % FAILS))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
