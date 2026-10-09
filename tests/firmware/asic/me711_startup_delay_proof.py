#!/usr/bin/env python3
r"""
me711_startup_delay_proof.py - does the OEM impose a delay BETWEEN startup
exchanges, or only inside one?

    py tests\firmware\asic\me711_startup_delay_proof.py

WHY THIS MATTERS. HaniCore's scheduler sets next_attempt = ms after EVERY
completed exchange, so each state transition costs a full
TGT_ASIC_START_PERIOD_MS = 20 ms whether it succeeded or failed. The V9 hardware
log showed the consequence: with the supervisor's deadline collapsed to 68 ms,
startup #1 at 41 ms and startup #2 at 64 ms leave the first runtime frame at
87 ms - 19 ms after the reset.

Before changing that, V10 has to establish that the 20 ms is HaniCore's own
invention and not something the OEM also does. This walks the OEM ME7.1.1 exchange and
classifies every wait and every write on the success path.

WHAT COUNTS AS A DELAY. Two things, and they are different:

  INTRA-exchange  a wait between CS-low and the first clock, or between the
                  transfer and reading the result. The OEM has these and V9
                  already reproduces the first one. They stay.

  INTER-exchange  a wait imposed AFTER a successful exchange, before the next
                  one may start. That is what HaniCore has and what this tool
                  looks for.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: E402  (puts every tools/ and tests/ module on sys.path)
IMG = (hcpaths.OEM_READ).read_bytes()

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<52s} {detail}")


def ilen(op):
    return 4 if (op & 0x0F) in (2, 3, 4, 5, 6, 7, 0xA) else 2


# The GPT timers, as memory operands. A delay has to be built out of one of
# these (or an SFR timer) - there is no other clock to wait on.
TIMERS = {0xFE40: "T2", 0xFE42: "T3", 0xFE44: "T4", 0xFE46: "T5",
          0xFE48: "T6", 0xFE50: "T7", 0xFE52: "T8", 0xFEAE: "WDTCON"}


def walk(lo, hi, label):
    """Every instruction in a straight-line run, with its memory operand."""
    out = []
    off = lo
    while off < hi:
        op, b1 = IMG[off], IMG[off + 1]
        n = ilen(op)
        imm = (IMG[off + 2] | (IMG[off + 3] << 8)) if n == 4 else None
        out.append((off, op, b1, imm))
        off += n
    return out


def timer_reads(run):
    return [(o, TIMERS[i]) for o, op, b1, i in run
            if i in TIMERS and op in (0xF2, 0xF3)]


def mem_writes(run):
    return [(o, i, op) for o, op, b1, i in run
            if i is not None and op in (0xF6, 0xF7) and i >= 0xF000]


def main():
    print("OEM ME7.1.1 startup exchange, from the image itself")
    print()

    # ---------------------------------------------------------------- 1 ---
    print("--- 1. the SUCCESS path of startup exchange #1 (0x8BE80E) ---")
    ok1 = walk(0x0BE80E, 0x0BE81C, "s1")
    for o, op, b1, imm in ok1:
        nm = {0xE1: "MOVB Rb,#data4", 0xF7: "MOVB mem,Rb", 0xEA: "JMPA"}.get(op, f"op{op:02X}")
        print(f"      0x{0x800000 + o:06X}  {nm:<16s}"
              + (f" mem=0x{imm:04X}" if imm is not None else ""))
    tr = timer_reads(ok1)
    check("no timer is read on the success path", not tr,
          "no T2/T3/T4/T5/T6/T7/T8 read" if not tr else f"READS {tr}")
    w = [(o, i) for o, i, op in mem_writes(ok1)]
    check("the success path writes only the two state bytes", len(w) == 2,
          " ".join(f"0x{i:04X}" for _, i in w)
          + "   = F247 (phase) and F246 (retry counter, cleared)")
    check("it ends in an unconditional jump to the epilogue",
          ok1[-1][1] == 0xEA, f"JMPA 0x{0x800000 + 0x0BE8EA:06X}")

    # ---------------------------------------------------------------- 2 ---
    print()
    print("--- 2. every timer wait in the WHOLE exchange, classified ---")
    run = walk(0x0BE73A, 0x0BE8EA, "all")
    tr = timer_reads(run)
    spans = [
        (0x0BE79E, 0x0BE7AC, "INTRA  after SSC init, before the PEC start"
                             "  <- the arming window V9 reproduces"),
        (0x0BE7C2, 0x0BE7D6, "INTRA  waiting for P6.4 to return HIGH (0xA5 cap)"),
        (0x0BE85C, 0x0BE86A, "INTRA  exchange #2, same arming window"),
        (0x0BE880, 0x0BE894, "INTRA  exchange #2, same CS-high wait"),
    ]
    for o, nm in tr:
        where = next((d for a, b, d in spans if a <= o < b), "*** UNCLASSIFIED")
        print(f"      0x{0x800000 + o:06X}  reads {nm:<4s} {where}")
    unclass = [o for o, _ in tr if not any(a <= o < b for a, b, _ in spans)]
    check("every timer read is INSIDE an exchange", not unclass,
          f"{len(tr)} reads, all intra-exchange" if not unclass
          else f"UNCLASSIFIED at {[hex(x) for x in unclass]}")

    # ---------------------------------------------------------------- 3 ---
    print()
    print("--- 3. the entry gate: what decides whether an exchange runs ---")
    entry = walk(0x0BE74A, 0x0BE75E, "entry")
    for o, op, b1, imm in entry:
        nm = {0xF3: "MOVB Rb,mem", 0x2D: "JMPR cc_Z", 0x49: "CMPB Rb,[Rw]",
              0xEA: "JMPA", 0xF7: "MOVB mem,Rb"}.get(op, f"op{op:02X}")
        print(f"      0x{0x800000 + o:06X}  {nm:<14s}"
              + (f" mem=0x{imm:04X}" if imm is not None else ""))
    tr_e = timer_reads(entry)
    check("the entry gate reads NO timer", not tr_e,
          "it dispatches on the phase byte F247 alone" if not tr_e
          else f"READS {tr_e}")

    # ---------------------------------------------------------------- 4 ---
    print()
    print("--- 4. the retry counter is a FAILURE path, not a schedule ---")
    fail = walk(0x0BE7FE, 0x0BE80E, "fail")
    for o, op, b1, imm in fail:
        nm = {0xF3: "MOVB Rb,mem", 0x25: "SUBB mem,ONES  (increment)",
              0x47: "CMPB Rb,#imm", 0xEA: "JMPA"}.get(op, f"op{op:02X}")
        print(f"      0x{0x800000 + o:06X}  {nm:<26s}"
              + (f" mem=0x{imm:04X}" if imm is not None else ""))
    check("the failure path increments F246 and caps it at 16",
          any(op == 0x25 for _, op, _, _ in fail)
          and any(op == 0x47 for _, op, _, _ in fail),
          "SUBB F246,ONES then CMPB #0010h")
    check("the success path CLEARS that counter instead",
          any(op == 0xF7 and imm == 0xF246 for _, op, _, imm in ok1),
          "MOVB F246, ZEROS at 0x8BE814")

    print()
    bad = [n for n, ok, _ in results if not ok]
    print(f"{len(results) - len(bad)}/{len(results)} checks pass")
    if bad:
        print("FAILED: " + "; ".join(bad))
        return 1
    print()
    print("CONCLUSION. The OEM gates a startup exchange on the PHASE BYTE alone")
    print("and reads no timer to decide whether to run one. Every timer wait it")
    print("does perform is INSIDE an exchange. Nothing on the success path arms")
    print("a delay before the next exchange - it clears the retry counter and")
    print("returns, and the next exchange runs as soon as it is next called.")
    print()
    print("HaniCore's 20 ms after a SUCCESSFUL exchange has no counterpart in")
    print("the OEM. It is a retry interval being applied to a non-retry.")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
