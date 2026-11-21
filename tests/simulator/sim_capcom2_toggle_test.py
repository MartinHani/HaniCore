r"""
sim_capcom2_toggle_test.py - c167sim's compare mode 1 on CAPCOM2 and the
double-register mode (2026-11-04, groundwork for the hardware-compare
executor, the maintainer's design notes).

    py tests\simulator\sim_capcom2_toggle_test.py

C167CR UM 15-16..15-19: compare mode 1 toggles the channel's own port latch on
every match - CC16..CC23 are P8.0..P8.7, CC28..CC31 are P7.4..P7.7, CC24..CC27
have no pin. A bank-2 register (CC8..15 / CC24..31) in compare mode 0 whose
bank-1 partner is in mode 1 toggles the PARTNER's pin on its own match.
The rows for CC23/28/29/30 named other registers until this change, so the
register addresses are checked against Keil's reg167.h too.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402

import c167sim as S  # noqa: E402

P7, P8, P2 = 0xFFD0, 0xFFD4, 0xFFC0
FAILS = 0


def check(name, ok, detail=""):
    global FAILS
    FAILS += not ok
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))


def rig():
    return S.CPU(S.Mem(bytes(0x100000)), 0, 0)


def arm(c, ch, mode, value):
    ccx, ccic, _ = S.CC_CHAN[ch]
    reg, shift = c.CCM_OF[ch]
    c._sset(reg, (c._sget(reg) & ~(0x0F << shift)) | (mode << shift))
    c._sset(ccx, value)
    c._sset(ccic, 0)


def main() -> int:
    print("=== c167sim - CAPCOM2 compare mode 1 and double-register mode ===\n")
    reg = Path(r"C:\Keil\C166\INC\reg167.h")
    if reg.exists():
        sfr = dict((m.group(1), int(m.group(2), 16)) for m in re.finditer(
            r"^sfr\s+(\w+)\s*=\s*0x([0-9A-Fa-f]+);", reg.read_text(errors="replace"), re.M))
        bad = [ch for ch in (4, 19, 20, 21, 22, 23, 28, 29, 30)
               if S.CC_CHAN[ch][:2] != (sfr["CC%d" % ch], sfr["CC%dIC" % ch])]
        check("CC_CHAN register/IC addresses equal reg167.h", not bad, "wrong: %s" % bad)
    else:
        print("  [SKIP] reg167.h not found - address check not run")

    # 1. each CAPCOM2 lane toggles its own pin, once per match, both ways
    for ch, port, bit in ((19, P8, 3), (23, P8, 7), (28, P7, 4), (30, P7, 6)):
        c = rig()
        arm(c, ch, 0x5, 0x1234)                 # mode 1, T7
        c._sset(S.TIMERS["T7"][0], 0x1234)
        c.check_compares()
        one = (c._sget(port) >> bit) & 1
        c.check_compares()
        two = (c._sget(port) >> bit) & 1
        check("CC%d mode 1 toggles %s.%d on each match" % (ch, "P8" if port == P8 else "P7", bit),
              one == 1 and two == 0 and len(c.cc_toggles) == 2,
              "after 1: %d, after 2: %d, toggles %d" % (one, two, len(c.cc_toggles)))

    # 2. mode 0 (interrupt only) never moves a pin
    c = rig()
    arm(c, 23, 0x4, 0x1234)
    c._sset(S.TIMERS["T7"][0], 0x1234)
    c.check_compares()
    check("CC23 mode 0 raises its request and leaves P8 alone",
          (c._sget(S.CC_CHAN[23][1]) & 0x80) and c._sget(P8) == 0 and not c.cc_toggles)

    # 3. double-register: CC8 in mode 0, CC0 in mode 1 -> CC8's match toggles P2.0
    c = rig()
    arm(c, 0, 0x5, 0x2000)
    arm(c, 8, 0x4, 0x1234)
    c._sset(S.TIMERS["T0"][0], 0x1234)
    c.check_compares()
    check("double register: CC8 (mode 0) toggles CC0's pin P2.0",
          (c._sget(P2) & 1) == 1 and c.cc_toggles == [(0, c.steps)])
    #    ...and not when the partner is not in mode 1 (the negative half)
    c = rig()
    arm(c, 0, 0x4, 0x2000)
    arm(c, 8, 0x4, 0x1234)
    c._sset(S.TIMERS["T0"][0], 0x1234)
    c.check_compares()
    check("...but not when CC0 is in mode 0", (c._sget(P2) & 1) == 0 and not c.cc_toggles)

    print("\n%s" % ("ALL PASS" if not FAILS else "%d FAILED" % FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
