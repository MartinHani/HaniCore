#!/usr/bin/env python3
r"""
sim_flag_test.py - does c167sim set N and Z where the real core does?

    py tests\simulator\sim_flag_test.py

WHY THIS EXISTS, AND IT COST A DAY. On the C166 core **every MOV and MOVB sets
N and Z from the value moved**. c167sim set them for some forms and not for
others - `MOV Rw,[Rw]` (0xA8) among the ones it did not - so a

    MOV   R4,[R0]        ; load a local off the user stack
    JMPR  cc_NZ,...      ; branch on it

pair branched on WHATEVER FLAGS THE PREVIOUS INSTRUCTION HAPPENED TO LEAVE.

The firmware was correct. The simulator was not. It looked exactly like two
different C bugs in `hcnvm.c`, was chased as such twice, and was only found by
tracing the instruction stream and noticing that the value loaded and the
branch taken disagreed.

That is the FOURTH c167sim defect in this project to present as a firmware bug
(after the shift-pair decode, the `NEG` borrow, and the `w16` range test), and
it is why `tools/sim_math_test.py` exists and why this file now sits beside it.
**When the simulator and the firmware disagree, suspect BOTH** - and when a
value is right but the branch on it is wrong, suspect the flags.

WHAT IS TESTED. Each case hand-assembles a tiny program, runs it, and asserts
the flag state the C166 manual specifies. Every one of them FAILS against the
simulator as it was before 2026-09-03.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import c167sim as S                       # noqa: E402

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-56s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def run(prog, steps, setup=None):
    """One hand-assembled program at 0x8E0000, with the DPPs and the register
    bank the real startup leaves behind."""
    img = bytearray(b"\xFF" * 0x100000)
    img[0xE0000:0xE0000 + len(prog)] = bytes(prog)
    m = S.Mem(bytes(img))
    for i, v in enumerate((0, 1, 2, 3)):
        m.sfr[0xFE00 + 2 * i] = v
    m.sfr[0xFE12] = 0xFC00          # SP
    m.sfr[0xFE14] = 0xF600          # STKUN
    m.sfr[0xFE10] = 0xFC00          # CP - the register bank
    cpu = S.CPU(m, 0x8E, 0x0000)
    if setup:
        setup(cpu, m)
    for _ in range(steps):
        cpu.step()
    return cpu, m


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=== does the simulator set N and Z where the C166 core does? ===\n")

    # --- the exact pair that caused the incident -------------------------
    #   MOV  R0,#0F800h ; SUB R0,#4 ; MOV R4,#1 ; MOV [R0],R4   (non-zero)
    #   MOV  R4,#0                                              (Z now set)
    #   MOV  R4,[R0]                                            (loads 1)
    # After the load, Z MUST be clear - the value moved is 1.
    cpu, _ = run([
        0xE6, 0xF0, 0x00, 0xF8,     # MOV R0,#0F800h
        0x28, 0x04,                 # SUB R0,#4
        0xE0, 0x14,                 # MOV R4,#1
        0xB8, 0x40,                 # MOV [R0],R4
        0xE0, 0x04,                 # MOV R4,#0     <- leaves Z SET
        0xA8, 0x40,                 # MOV R4,[R0]   <- moves 1: Z must CLEAR
    ], 6)
    check("MOV Rw,[Rw] loading a NON-ZERO clears Z",
          cpu.z == 0 and cpu.gr(4) == 1, "Z=%d R4=%04X" % (cpu.z, cpu.gr(4)))

    cpu, _ = run([
        0xE6, 0xF0, 0x00, 0xF8,
        0x28, 0x04,
        0xE0, 0x04,                 # MOV R4,#0
        0xB8, 0x40,                 # MOV [R0],R4   (store 0)
        0xE0, 0x14,                 # MOV R4,#1     <- leaves Z CLEAR
        0xA8, 0x40,                 # MOV R4,[R0]   <- moves 0: Z must SET
    ], 6)
    check("MOV Rw,[Rw] loading a ZERO sets Z",
          cpu.z == 1 and cpu.gr(4) == 0, "Z=%d R4=%04X" % (cpu.z, cpu.gr(4)))

    # --- and the branch that depends on it -------------------------------
    #   ... MOV R4,[R0] ; JMPR cc_NZ,+2 ; MOV R6,#1 ; ... ; MOV R6,#2
    cpu, _ = run([
        0xE6, 0xF0, 0x00, 0xF8,
        0x28, 0x04,
        0xE0, 0x04,                 # MOV R4,#0
        0xB8, 0x40,                 # MOV [R0],R4
        0xE0, 0x14,                 # MOV R4,#1      (Z clear)
        0xA8, 0x40,                 # MOV R4,[R0]    (moves 0 -> Z set)
        0x3D, 0x01,                 # JMPR cc_NZ,+1  (must NOT be taken)
        0xE0, 0x16,                 # MOV R6,#1
        0xCC, 0x00,                 # NOP
    ], 8)
    check("and a JMPR cc_NZ after it branches on the LOADED value",
          cpu.gr(6) == 1, "R6=%04X (1 = fell through, as it must)" % cpu.gr(6))

    # --- the other forms, one assertion each ------------------------------
    cpu, _ = run([0xE0, 0x14, 0xE0, 0x04], 2)          # MOV R4,#1 ; MOV R4,#0
    check("MOV Rw,#data4 sets Z", cpu.z == 1, "Z=%d" % cpu.z)

    cpu, _ = run([0xE6, 0xF4, 0x01, 0x00, 0xE6, 0xF4, 0x00, 0x00], 2)
    check("MOV reg,#data16 sets Z", cpu.z == 1, "Z=%d" % cpu.z)

    cpu, _ = run([0xE0, 0x14, 0xE0, 0x05, 0xF0, 0x45], 3)   # R4=1;R5=0;R4=R5
    check("MOV Rw,Rw sets Z", cpu.z == 1, "Z=%d" % cpu.z)

    cpu, _ = run([0xE6, 0xF4, 0x00, 0x80], 1)               # MOV R4,#8000h
    check("MOV reg,#data16 sets N from bit 15", cpu.n == 1, "N=%d" % cpu.n)

    cpu, _ = run([0xE1, 0x18, 0xE1, 0x08], 2)               # MOVB RL4,#1;#0
    check("MOVB Rb,#data4 sets Z", cpu.z == 1, "Z=%d" % cpu.z)

    cpu, _ = run([0xE7, 0xF8, 0x80, 0x00], 1)               # MOVB RL4,#80h
    check("MOVB sets N from bit 7, not bit 15", cpu.n == 1, "N=%d" % cpu.n)

    # PUSH and POP are MOV-class on this core and set N and Z too.
    cpu, _ = run([0xE6, 0xF4, 0x01, 0x00, 0xE6, 0xF5, 0x00, 0x00,
                  0xEC, 0xF5], 3)                            # PUSH R5 (=0)
    check("PUSH sets Z", cpu.z == 1, "Z=%d" % cpu.z)

    cpu, _ = run([0xE6, 0xF4, 0x00, 0x00, 0xEC, 0xF4,        # PUSH 0
                  0xE6, 0xF6, 0x01, 0x00,                    # MOV R6,#1 (Z clear)
                  0xFC, 0xF6], 4)                            # POP R6 (=0)
    check("POP sets Z", cpu.z == 1 and cpu.gr(6) == 0,
          "Z=%d R6=%04X" % (cpu.z, cpu.gr(6)))

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("\nSIM FLAG TEST FAILS - %d check(s). Every simulator-based "
              "proof in this\nproject rests on these." % FAILS)
        return 1
    print("\nSIM FLAG TEST PASSES - a MOV sets the flags the next branch "
          "reads.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
