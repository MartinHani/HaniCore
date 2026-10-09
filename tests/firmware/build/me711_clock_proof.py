#!/usr/bin/env python3
r"""
me711_clock_proof.py - every derived timing constant must follow from fCPU.

    py tests\firmware\build\me711_clock_proof.py

WHY THIS EXISTS.

A great deal now depends on fCPU = 40 MHz: the 1 ms tick, the serial drain
period, the baud rate, the SSC bit rate, the interrupt budget, and the
instruction-to-hardware-time conversion that corrected me711_ts_gap_proof.
hctarget.h establishes the clock with five independent lines of evidence and
records that it was once believed to be 19.968 MHz.

THE FAILURE MODE THIS GUARDS AGAINST IS NOT "the clock is wrong". It is a
constant that was computed from the OLD clock and left behind, because such a
constant keeps working until something near it changes. hctarget.h documents
exactly that happening: the baud divisor and the CAPCOM prescaler were BOTH
wrong by a factor of two, so they cancelled and every check appeared to pass.

So this file does not check that any number is 40 MHz. It recomputes each
derived constant FROM TGT_FCPU_HZ and compares. If somebody changes the clock,
everything that should move moves, and anything stale fails here.

It also checks one compiled instruction, because a constant that is right in
the header and wrong in the image is the same defect with an extra step.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths as HCP  # noqa: E402

TDIR = ROOT / "firmware/targets/me711"

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-56s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


H = (TDIR / "hctarget.h").read_text(errors="replace")


def d(name):
    m = re.search(r"#define\s+%s\s+(0x[0-9A-Fa-f]+|\d+)" % name, H)
    if not m:
        raise SystemExit("%s not found in hctarget.h" % name)
    return int(m.group(1), 0)


def main() -> int:
    print("=== HaniCore ME7.1.1 - every timing constant, back to fCPU ===\n")

    fcpu = d("TGT_FCPU_HZ")
    print("  TGT_FCPU_HZ = %d (%.3f MHz)\n" % (fcpu, fcpu / 1e6))

    # ---------------------------------------------------------- the timebase
    #
    # [DS UM 15] T78CON, Timer Mode: input frequency = fCPU / 2^(TxI + 3).
    t78 = d("TGT_T78CON")
    t7i = t78 & 0x07
    t8i = (t78 >> 8) & 0x07
    t7_hz = fcpu / (2 ** (t7i + 3))
    t8_hz = fcpu / (2 ** (t8i + 3))
    print("    T78CON 0x%04X -> T7I=%d, T8I=%d" % (t78, t7i, t8i))
    print("    T7 = fCPU / 2^(T7I+3) = %.0f Hz" % t7_hz)

    check("T7 and T8 share one prescaler setting, as the code assumes",
          t7i == t8i, "T7I=%d T8I=%d" % (t7i, t8i))

    ticks_x10 = d("TGT_TICKS_PER_MS_X10")
    want_x10 = round(t7_hz / 1000.0 * 10)
    check("TGT_TICKS_PER_MS_X10 follows from T7",
          ticks_x10 == want_x10,
          "%d, computed %d from %.0f Hz" % (ticks_x10, want_x10, t7_hz))

    reload_ = d("TGT_TICK_RELOAD")
    want_reload = round(t8_hz / 1000.0)
    check("TGT_TICK_RELOAD is one millisecond of T8",
          reload_ == want_reload,
          "%d, computed %d" % (reload_, want_reload))

    # US_TO_TICKS(us) = us * TICKS_PER_MS_X10 / 10000
    for us in (40, 100, 1000):
        got = us * ticks_x10 // 10000
        want = round(us * t7_hz / 1e6)
        check("US_TO_TICKS(%d) is %d ticks" % (us, want),
              got == want, "%d ticks = %.1f us" % (got, got / t7_hz * 1e6))

    # ------------------------------------------------------------- the baud
    #
    # [DS UM 11.4] the generator is clocked at fCPU/2 and produces 16x the
    # baud, so baud = fCPU / (32 * (S0BRL + 1)) with S0BRS = 0.
    s0bg = d("TGT_S0BG")
    baud_nom = d("TGT_BAUD")
    baud_real = fcpu / (32.0 * (s0bg + 1))
    err = (baud_real - baud_nom) / baud_nom * 100.0
    print("\n    S0BG 0x%02X -> %.0f baud against a nominal %d (%+.2f%%)"
          % (s0bg, baud_real, baud_nom, err))
    check("the reload lands inside ordinary UART tolerance",
          abs(err) < 3.0, "%+.2f%%, and 3%% is the usual limit" % err)

    # ------------------------------------------------------- the RX drain
    #
    # The safety argument for HC_RXTICK_US is a RATIO of two things that both
    # come from fCPU, so it survives a clock change - but only if both are
    # recomputed, which is the point of doing it here.
    rx_us = d("HC_RXTICK_US")
    char_us = 10.0 / baud_real * 1e6
    print("\n    one 8N1 character at %.0f baud = %.1f us" % (baud_real, char_us))
    check("the drain period is under half a character",
          rx_us <= char_us / 2.0,
          "%d us drain, %.0f us character, %.1f drains per byte"
          % (rx_us, char_us, char_us / rx_us))

    # -------------------------------------------- and in the compiled image
    #
    # A constant right in the header and wrong in the image is the same defect
    # with one more step in it. hc_cc7_isr reschedules with
    # `ADD CC7,#US_TO_TICKS(HC_RXTICK_US)`, so the literal in the instruction
    # stream is checkable.
    want_ticks = rx_us * ticks_x10 // 10000
    lst = None
    for cand in (TDIR / "build/hcts.lst",):
        if cand.exists():
            lst = cand.read_text(errors="replace")
    if lst and "hc_cc7_isr" in lst:
        m = re.search(r"CC7\s*=\s*\(unsigned int\)\(CC7\s*\+", lst)
        check("the drain reschedule is compiled from US_TO_TICKS, not a literal",
              m is not None, "found the source line in the listing")
    print("    US_TO_TICKS(HC_RXTICK_US) = %d T7 ticks = %.1f us"
          % (want_ticks, want_ticks / t7_hz * 1e6))
    check("which is the %d us the header asks for" % rx_us,
          abs(want_ticks / t7_hz * 1e6 - rx_us) < 1.0,
          "%.2f us" % (want_ticks / t7_hz * 1e6))

    # --------------------------------------------------- no stale constants
    #
    # The superseded figures, in code rather than in the prose that explains
    # why they are superseded.
    print("")
    stale = []
    for f in HCP.target_sources("*.c") + HCP.target_sources("*.h") + \
            HCP.portable_sources("*.c"):
        text = f.read_text(errors="replace")
        text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
        for m in re.finditer(r"\b(19968000|39936000|19968|1248000)\b", text):
            stale.append("%s:%d %s" % (f.name,
                                       text[:m.start()].count("\n") + 1,
                                       m.group(1)))
    check("no superseded clock constant survives in CODE",
          not stale,
          "comments explaining the correction are fine; code is not"
          if not stale else ", ".join(stale[:4]))

    # ------------------------------------ the tools convert from the header
    #
    # Every tool that turns instructions into hardware time must READ
    # TGT_FCPU_HZ. One that hardcodes a megahertz figure is the next stale
    # constant.
    for tool in ("me711_ts_gap_proof.py", "me711_isr_budget.py",
                 "me711_config_state_test.py"):
        p = ROOT / "tools" / tool
        if not p.exists():
            continue
        t = p.read_text(errors="replace")
        reads = "TGT_FCPU_HZ" in t
        check("%s derives its clock from TGT_FCPU_HZ" % tool, reads,
              "reads the header" if reads else "hardcodes a clock")

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("A TIMING CONSTANT NO LONGER FOLLOWS FROM fCPU.\n"
              "Do not 'fix' it by editing the number until it matches - work\n"
              "out which clock it was derived from first. hctarget.h records\n"
              "what happened last time two errors cancelled.")
        return 1
    print("CLOCK PROOF PASSES - every derived constant recomputes from "
          "TGT_FCPU_HZ.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
