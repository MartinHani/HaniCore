#!/usr/bin/env python3
r"""Generate hcvec.c - a catch-all interrupt handler for every unclaimed trap.

    py tools\build\gen_vector_probe.py

Why this exists
---------------

C167 trap numbers are not documented anywhere in this repo, and the standard
table people quote from memory is wrong for this silicon. The bench settled it
on 2026-08-23: with a handler declared `interrupt 0x31` for T8INT, hcTick never
moved while hcBadVec climbed steadily - interrupts were being delivered to
flash 0x020000 + N*4 and the catch-all was catching them, so the vector table
worked and only the trap number was wrong.

Giving every trap its own handler let the hardware name its own slot. With
exactly one source enabled, exactly one slot can fire:

    T8INT = trap 0x3E, vector 0x0F8      (measured; the standard table says
                                          0x0FC, and the standard table is
                                          wrong here)

That number is now in hctarget.h as TGT_TRAP_T8INT and hcmain.c declares the
real handler on it, so it is listed in CLAIMED below and skipped here.

What is left is the permanent value of this file: every trap the firmware does
NOT claim still lands on a counted handler that records its own number. So an
interrupt nobody asked for is reported rather than fatal, and the next unknown
source - M4b needs CC5INT confirmed, M5/M7/M8 need the CAPCOM channels - is one
bench reading away instead of one flash cycle per guess.

hc_firstvec vs hc_lastvec is the safety net: if they ever disagree, more than
one unclaimed source is firing.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
TARGETS = {
    "me711": ROOT / "firmware/targets/me711/generated/hcvec_me711.c",
}
STUBS = {
    "me711": ROOT / "firmware/targets/me711/generated/hcvecstub_me711.a66",
}

# Every unclaimed trap calls a common assembly entry and carries its number
# in the following word. The common body reads that word through its own code
# segment, saves the complete Keil scratch set, calls hc_vec_hit(), discards
# the near CALL's return word and returns through the original interrupt frame.
# The inline trap word is data and is never executed. A166 permits one TASK per
# module; the other vector slots target public labels through JMPS relocation.
# This keeps the full diary and register-preservation contract in six bytes per
# trap. me711_vector_diary_proof executes every stub and verifies its return.

# Trap 0 is reset. It is claimed by ?C_RESET in start_dh.a66, it belongs to the
# mask ROM, and its slot is restored from the donor by the build tool.
FIRST, LAST = 0x01, 0x7F

# Traps the firmware declares a real handler for itself. A second definition
# here would be a duplicate symbol, and worse, it would silently steal the
# vector from the handler that is meant to have it.
# Keep in step with the TGT_TRAP_* defines in hctarget.h.

# The Bosch ME7.1.1 bench-safe image claims only the two interrupts it
# actually enables. Everything else - including every engine vector - lands on
# a counted catch-all, which is the point: an image that arms nothing must
# still be able to say that something fired.
#
# Note what is NOT here and cannot be: traps 0x24-0x27, 0x2B, 0x2C and 0x38.
# Their FIRST-level vectors jump into the Bosch boot block rather than
# forwarding to the application table, so a handler on those slots is
# unreachable on this ECU family. See hctarget.h.
CLAIMED_BOSCH = {
    0x30: "CC16INT - hc_cc16_isr in hctrig_me711.c (knock window MF)",
    0x39: "CC25INT - deadline terminal ISR (V102)",
    0x3A: "CC26INT - hc_plan_isr in hcsched_dry.c (software-triggered planner)",
    0x02: "NMI - hc_v02 in hcnmi_v49.a66 (retained first-event snapshot)",
    0x3E: "T8INT  - hc_tick_isr in hcmain_me711.c (the 1 ms system tick)",
    0x47: "S0TBINT - hc_s0tb_isr in comms/hcserial711.c (reply transmit)",
    0x18: "CC8INT - hc_cc8_isr in hctrig_me711.c  (NWDG1 cam capture)",
    0x19: "CC9INT - hc_cc9_isr in hctrig_me711.c  (NWDG2 cam capture)",
    0x1F: "CC15INT - hc_cc15_isr in hctrig_me711.c (KWDG crank capture)",
    0x2B: "S0RINT - hc_s0r_isr below (UNREACHABLE here; kept so the probe is"
          " exhaustive)",
    # V4 ran the SSC with NO handlers on these three, and the hardware said so:
    # BV climbed steadily with FV=0x2D and LV=0x2E. When a PEC channel's COUNT
    # reaches zero the next request stops being a PEC transfer and becomes a
    # NORMAL vectored interrupt - so the end of every block transfer lands
    # here. The OEM has real handlers on all three (0x82352C, 0x8234E0,
    # 0x823530) and the TX one is literally "BCLR SSCTIE; RETI".
    0x2D: "SSCTINT - hc_ssc_tx_isr in hcasic.c (PEC0 block end)",
    0x2E: "SSCRINT - hc_ssc_rx_isr in hcasic.c (PEC4 block end = frame done)",
    0x2F: "SSCEINT - hc_ssc_err_isr in hcasic.c (SSC error, recovery)",
}

HEADER = '''/*
 * hcvec.c - GENERATED by tools/build/gen_vector_probe.py. Do not edit by hand.
 * Unclaimed C167 traps forward through the relocated table at seg82:N*4.
 * Compact assembly entries preserve the interrupted register bank, identify
 * the trap, and call the common diary/receive-probe body. The diary is written
 * inside the handler because a later diagnostic task might never run.
 * firstvec/lastvec must agree when exactly one unclaimed source is active.
 * Startup clears all state explicitly before interrupts: ?C_INIT does not run.
 */
#include <reg167.h>
#include "hctarget.h"
%%VEC_EXTRA_INCLUDE%%

unsigned int hc_badvec;
unsigned int hc_firstvec;      /* 0 = nothing has fired yet; trap 0 is reset */
unsigned int hc_lastvec;

/* During the boot receive probe, an unclaimed handler identifies ASC0's
   vector and takes its byte. Once PEC receive is armed, the tick owns the
   receive-ring head and the main parser owns its tail. Byte cursor updates
   are atomic; shared state is volatile so polling observes ISR publication. */
volatile unsigned char hc_s0r_trap;   /* 0 = the probe never saw an interrupt */
volatile unsigned char hc_s0r_learn;  /* 1 only during the boot probe         */
/* Where a probe byte is thrown away by a handler that is not the receiver's.
   Assigned rather than (void)-cast: C166 warns on a bare read, and a read the
   compiler drops would leave the byte in the register. */
volatile unsigned char hc_probe_sink;

volatile unsigned char hc_rx_ring[HC_RXRING];
volatile unsigned char hc_rx_head;    /* producer: this file                  */
volatile unsigned char hc_rx_tail;    /* consumer: the main loop              */
volatile unsigned int  hc_rx_ovf;     /* ring full - the MAIN LOOP fell behind */

/* Also used by hcmain.c's polled fallback, which is why it is not static. */
void hc_rx_store(unsigned char b)
{
    unsigned char h = (unsigned char)((hc_rx_head + 1u) & (HC_RXRING - 1u));

    if (h != hc_rx_tail) {
        hc_rx_ring[hc_rx_head] = b;
        hc_rx_head = h;
    } else {
        hc_rx_ovf++;
    }
}

/* Read first, then clear. Clearing first would risk clearing the flag of a
   byte that arrived in between, and a lost interrupt stops the port for good
   where a lost byte only costs one request. */
static void hc_rx_take(void)
{
    hc_rx_store((unsigned char)S0RBUF);
    S0RIC &= 0x7F;
}

%%VEC_EXTRA_DECL%%
/* The assembly stubs enter with the trap number in R8, the Keil argument
   register. Their common body preserves the interrupted register bank. */
void hc_vec_hit(unsigned char n)
{
    if (hc_s0r_learn) {
        hc_s0r_trap = n;
        hc_rx_take();
        return;
    }
    if (n == hc_s0r_trap) {
        hc_rx_take();
        return;
    }
    hc_lastvec = n;
    if (hc_firstvec == 0) {
        hc_firstvec = n;
    }
    hc_badvec++;
%%VEC_EXTRA_CALL%%}

/* The standard table's S0RINT. If it is the right one this is the whole
   receive path; if it is not, it simply never runs and the catch-all above
   carries the traffic instead. Either way the number that really fired is
   published as s0rTrap. */
void hc_s0r_isr(void) interrupt TGT_TRAP_S0RINT
{
    if (hc_s0r_learn) {
        hc_s0r_trap = TGT_TRAP_S0RINT;
    }
    hc_rx_take();
}

'''



# ==========================================================================
# WHAT EACH TARGET IS ALLOWED TO DO INSIDE A CATCH-ALL HANDLER.
#
# This file's own header explains the constraint and it is not a style
# preference: a Keil C166 `interrupt` function that CALLS A FUNCTION IN ANOTHER
# MODULE has to assume the worst about the register bank, so it saves all of
# it. That took each of the ~117 catch-alls from 26 bytes to 74 and the whole
# ?PR?HCVEC section from about 3 KB to 9 KB.
#
# On the BOSCH target that is affordable: NCODE there is one contiguous
# 0x8E1000-0x8EDFFF, 53 KB, and the timestamp is worth having because an NMI
# was once recorded on that ECU without the moment it happened.
#
# On the ME7.5 target it is NOT affordable and never was. That linker script
# has to dodge the words the bootrom's program-page checksum samples, so NCODE
# is a LIST of windows whose largest is 8188 bytes - and an 8618-byte
# ?PR?HCVEC fits in none of them. The linker emitted
#
#     *** WARNING L5: SECTION LOCATED OUTSIDE CLASS AREA
#         SECTION: ?PR?HCVEC   CLASS: NCODE
#
# and parked the section at 0x8A0000, outside the 0x890000-0x89FFFF range
# OH166 extracts - so the image was built WITHOUT the vector table's code in
# it. It also referenced `hc_tick_ms`, which that board does not have at all:
# hcmain.c states plainly that there is no periodic system tick there any more.
#
# ME7.5 loses nothing by leaving it out: hcmain.c already publishes hc_badvec,
# hc_firstvec and hc_lastvec as output channels 66, 72 and 74.
VEC_EXTRA = {
    "me711": {
        "include": '#include "hcconfig.h"',
        "decl": """/* Stamp the trap in the handler and use the reset diary's byte order.
   The shared body avoids a complete C interrupt prologue per vector. The
   assembly entries preserve the Keil scratch registers and interrupt frame;
   me711_vector_diary_proof executes every linked entry and checks both. */
extern unsigned int hc_tick_ms;

#define HC_VEC_RSTLOG ((unsigned char volatile far *) \\
                       (TGT_EXTRAM_BASE + TGT_RAM_CFG + TGT_RAM_RSTLOG))

static void hc_vec_trap_at(unsigned int vector, unsigned int ms)
{
    HC_VEC_RSTLOG[RST_TRAP] = (unsigned char)(vector >> 8);
    HC_VEC_RSTLOG[RST_TRAP + 1u] = (unsigned char)(vector & 0xFFu);
    HC_VEC_RSTLOG[RST_TRAP_MS] = (unsigned char)(ms >> 8);
    HC_VEC_RSTLOG[RST_TRAP_MS + 1u] = (unsigned char)(ms & 0xFFu);
}

""",
        "call": "    hc_vec_trap_at((unsigned int)n, hc_tick_ms);\n",
    },
}


def main() -> None:
    import sys

    which = sys.argv[1] if len(sys.argv) > 1 else "me711"
    if which not in TARGETS:
        raise SystemExit("usage: %s [%s]"
                         % (pathlib.Path(__file__).name, "|".join(TARGETS)))
    OUT = TARGETS[which]
    CLAIMED = CLAIMED_BOSCH

    lines = [HEADER]
    for trap, why in sorted(CLAIMED.items()):
        lines.append("/* trap 0x%02X is claimed by the firmware: %s */\n"
                     % (trap, why))
    lines.append("\n/* Every other trap enters an assembly stub in hcvecstub_me711.a66\n"
                 "   that calls hc_vec_hit(n) - tools/build/gen_vector_probe.py. */\n")
    made = 0
    # ONE interrupt procedure (A166: one TASK per module, and instructions
    # must sit inside a PROC): the BADVEC_TRAP stub is its entry, every
    # other stub a public label inside it, then the common body.
    nums = [n for n in range(FIRST, LAST + 1) if n not in CLAIMED]
    made = len(nums)
    stubs = [STUB_HEAD]
    stubs += ["PUBLIC  hc_v%02X\n" % n for n in nums]
    stubs.append(STUB_SECTION)
    stubs.append(STUB_TASK.format(n=LAST))
    stubs += [STUB_ONE.format(n=n) for n in nums if n != LAST]
    ids=[LAST]+[n for n in nums if n!=LAST]
    table="hc_vec_ids:\n"+"".join("        DB      "+",".join("%03XH"%n for n in ids[i:i+16])+"\n" for i in range(0,len(ids),16))
    stubs.append(STUB_TAIL.replace("?C_HCVEC ENDP",table+"?C_HCVEC ENDP"))
    STUBS[which].write_text("".join(stubs), encoding="ascii", newline="\n")
    text = "".join(lines)
    extra = VEC_EXTRA[which]
    text = text.replace("%%VEC_EXTRA_INCLUDE%%", extra["include"])
    text = text.replace("%%VEC_EXTRA_DECL%%\n", extra["decl"])
    text = text.replace("%%VEC_EXTRA_DECL%%", extra["decl"])
    text = text.replace("%%VEC_EXTRA_CALL%%", extra["call"])
    if "%%VEC_EXTRA" in text:
        raise SystemExit("gen_vector_probe: a %%VEC_EXTRA%% placeholder was "
                         "left in the output - refusing to write a file the "
                         "compiler would reject in a confusing way")
    OUT.write_text(text, encoding="ascii", newline="\n")
    print("wrote %s (%d handlers over traps 0x%02X-0x%02X, %d claimed elsewhere)"
          % (OUT, made, FIRST, LAST, len(CLAIMED)))


STUB_HEAD = """$MOD167
$CASE
$SEGMENTED
$INCLUDE (REG167.INC)
; GENERATED by tools/build/gen_vector_probe.py - do not edit.
; A near CALL identifies its fixed-width stub through the saved return word.
; The common body saves the scratch set, indexes the byte trap table in its
; own segment, far-calls hc_vec_hit(n), and restores the interrupt frame.
NAME    HCVECSTUB_ME711
EXTRN   hc_vec_hit:FAR
ASSUME  DPP3:SYSTEM
"""
STUB_SECTION = """?PR?HCVECSTUB_ME711 SECTION CODE WORD 'FCODE'
"""
STUB_ONE = """hc_v{n:02X}:
        CALLA   cc_UC,hc_vec_common
"""
STUB_TASK = """?C_HCVEC PROC TASK HCVT{n:02X} INTNO HCVI{n:02X} = {n:03X}H
hc_v{n:02X}:
        CALLA   cc_UC,hc_vec_common
"""
STUB_TAIL = """hc_vec_common:
        PUSH    R8
        PUSH    R1
        PUSH    R4
        MOV     R1,SP
        ADD     R1,#6
        MOV     R8,[R1]
        SUB     R8,#(hc_v7F+4)
        SHR     R8,#2
        ADD     R8,#hc_vec_ids
        EXTS    #SEG hc_vec_common,#1
        MOVB    RL4,[R8]
        MOVBZ   R8,RL4
        PUSH    R2
        PUSH    R3
        PUSH    R5
        PUSH    R6
        PUSH    R7
        PUSH    R9
        PUSH    R10
        PUSH    R11
        PUSH    R12
        PUSH    MDH
        PUSH    MDL
        PUSH    MDC
        CALLS   SEG hc_vec_hit,hc_vec_hit
        POP     MDC
        POP     MDL
        POP     MDH
        POP     R12
        POP     R11
        POP     R10
        POP     R9
        POP     R7
        POP     R6
        POP     R5
        POP     R3
        POP     R2
        POP     R4
        POP     R1
        POP     R8
        ADD     SP,#2
        RETI
?C_HCVEC ENDP
?PR?HCVECSTUB_ME711 ENDS
        END
"""


if __name__ == "__main__":
    main()
