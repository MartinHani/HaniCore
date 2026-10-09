#!/usr/bin/env python3
r"""
sim_compare_timebase_test.py - a CAPCOM COMPARE runs against the timer its CCM
nibble selects, not against the one a table declares.

    py tests\simulator\sim_compare_timebase_test.py

WHY THIS EXISTS. `c167sim` resolved the timebase-select bit for CAPTURES and
not for COMPARES. `capture()` has read bit 3 of the CCM nibble since the
ME7.1.1 decoder needed it - the crank and cams latch T1 - while
`check_compares()` took the timebase from `CC_CHAN`'s declaration, which says
T0 for every CAPCOM1 channel.

**Every compare this simulator has ever served happened to be on T0** - an
ME7.5 coil or the ME7.1.1 serial drain tick - so the asymmetry was invisible.

It stops being invisible the moment the ME7.1.1 angle scheduler programs a coil
compare, because **its deadlines are T1 values**: `ev_deadline` is derived from
the crank capture stamp and the crank capture runs against T1
(`hctrig_me711.c`, `TGT_T1CON_RUNNING`). A model comparing that value against
T0 would never match, and *"the compare never fires"* is indistinguishable from
the firmware getting the mode encoding wrong.

**That is the ninth time a gap in this simulator would have been read as a
defect in the ECU**, and the list is in the project rules: the MOV flags, the inlined
slot-B helper, `Rig.run()` uninstalling its own hooks, the DQ6 byte accessor,
the missing watchdog, the SSC error flags taught to read clean, the 8-bit frame
length, and the K-line driver that scored replies by CRC alone.

THIS TEST FAILS AGAINST THE MODEL AS IT STOOD, and that was demonstrated end
to end rather than asserted - `cc_timebase()` was monkeypatched back to
`lambda self, ch, declared: declared`, which is exactly what `check_compares()`
used to do, and the run scored:

    5/9, with the four bit3-SET checks failing and nothing else

It is a simulator regression, not a firmware gate: it pokes SFRs directly and
loads no image.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import c167sim as S                       # noqa: E402

CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print("  [%s] %-52s %s" % ("PASS" if ok else "FAIL", name, detail))


def rig():
    m = S.Mem(bytes(0x100000))
    return S.CPU(m, 0, 0)


def arm_compare(c, ch, alt, value):
    """Put channel `ch` in compare mode 4, timebase select = `alt`, CCx =
    `value`, and clear any standing request."""
    ccx, ccic, _ = S.CC_CHAN[ch]
    reg, shift = c.CCM_OF[ch]
    nib = 0x04 | (0x08 if alt else 0x00)          # mode 4, interrupt only
    cur = c._sget(reg) & ~(0x0F << shift)
    c._sset(reg, cur | (nib << shift))
    c._sset(ccx, value)
    c._sset(ccic, 0x0000)


def fired(c, ch):
    _ccx, ccic, _ = S.CC_CHAN[ch]
    return bool(c._sget(ccic) & 0x80)


def case(ch, alt, base, other, label):
    """Set the channel's OWN timer to the compare value and the other timer of
    the same unit to something else, then ask whether the match was seen."""
    c = rig()
    arm_compare(c, ch, alt, 0x1234)
    c._sset(S.TIMERS[base][0], 0x1234)            # the timer it should watch
    c._sset(S.TIMERS[other][0], 0x9999)           # the one it should not
    c.check_compares()
    check(label, fired(c, ch),
          "CC%d nibble bit3=%d -> must match %s" % (ch, 1 if alt else 0, base))

    # ...and the negative half: with ONLY the other timer at the compare value
    # there must be no request at all. Without this a model that fires on any
    # timer would pass the row above.
    c = rig()
    arm_compare(c, ch, alt, 0x1234)
    c._sset(S.TIMERS[base][0], 0x4321)
    c._sset(S.TIMERS[other][0], 0x1234)
    c.check_compares()
    check("...and NOT on %s" % other, not fired(c, ch),
          "the wrong timer reaching the compare value must do nothing")


def main() -> int:
    print("=== c167sim - a compare watches the timer its CCM nibble picks "
          "===\n")

    # CAPCOM1. CC0 is a coil on both targets; bit 3 picks T1 over T0.
    case(0, False, "T0", "T1", "CC0 with bit3 CLEAR runs against T0")
    case(0, True, "T1", "T0", "CC0 with bit3 SET runs against T1")

    # CAPCOM2 has its own pair, and the declaration in CC_CHAN says T7.
    case(30, False, "T7", "T8", "CC30 with bit3 CLEAR runs against T7")
    case(30, True, "T8", "T7", "CC30 with bit3 SET runs against T8")

    # ===================== THE CONTROL ON THE CONTROL =====================
    #
    # Everything above could be satisfied by a model that fires whenever any
    # timer matches. This says the mode gate still works: a channel in a
    # CAPTURE mode must not raise a compare request however the timers sit.
    c = rig()
    ccx, ccic, _ = S.CC_CHAN[0]
    reg, shift = c.CCM_OF[0]
    c._sset(reg, (c._sget(reg) & ~(0x0F << shift)) | (0x02 << shift))
    c._sset(ccx, 0x1234)
    c._sset(ccic, 0x0000)
    c._sset(S.TIMERS["T0"][0], 0x1234)
    c._sset(S.TIMERS["T1"][0], 0x1234)
    c.check_compares()
    check("a CAPTURE-mode channel raises no compare", not fired(c, 0),
          "modes 1-3 are captures; only 4-7 compare")

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("COMPARE TIMEBASE FAILS - c167sim is comparing against a timer "
              "the firmware did not select. A compare that never fires looks "
              "exactly like a firmware fault.")
        return 1
    print("COMPARE TIMEBASE PASSES - captures and compares resolve the CCM "
          "nibble's timebase bit the same way.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
