/*
 * hcpower.c - NLEN_FR (P3.12), the Bosch ME7.1.1 power hold.
 *
 * WHAT THIS PIN IS, and every link in the chain is a primary source:
 *
 *  1. Bosch's own port map, the ME7.1.1 schematic set sheet "FR",
 *     row for BHE/WRH/P3.12, CPU pin 79: BOTH ME7.1.1 columns (B-Muster VW,
 *     C-Muster AUDI) read NLEN_FR. The ME7.2 (Bosch) column still had the
 *     stock SG-SIZE there, so this is an ME7.1.1-generation change.
 *
 *  2. The Rechnerkern sheet shows the same thing at the silicon: S5000
 *     FUNKTIONS-RECHNER pin 79 is labelled P3.12/BHE/WRH and the net leaving
 *     it is NLEN_FR.
 *
 *  3. NLEN_FR and NLEN_AS (the ASIC's own, its P1L.3, ASIC pin 121) meet at
 *     S5600, a 74ACT00 powered from VSTBY, and come out as one net NL through
 *     R5600.
 *
 *     THIS COMMENT USED TO SAY "two NAND gates in series = AND, so NL needs
 *     BOTH processors to agree". THAT WAS WRONG, and the correction matters
 *     because it changes which direction needs agreement. The two gates are
 *     not in series on one input pair. Read off the PDF's own line segments
 *     (docs/PLATFORM.md lists the coordinates, and the gaps
 *     between them are what proves the four wires are separate nets):
 *
 *       gate A   pins 1 and 2 TIED TOGETHER, fed by NLEN_FR, which R5602
 *                pulls up to VCC_CPU.        pin 3 = NOT(NLEN_FR)
 *       gate B   pin 4 = gate A's output
 *                pin 5 = NLEN_AS, which R5601 pulls down to GND
 *                                            pin 6 = NAND(/NLEN_FR, NLEN_AS)
 *
 *          NL  =  NLEN_FR  OR  NOT(NLEN_AS)
 *          NL is LOW  <=>  NLEN_FR LOW  AND  NLEN_AS HIGH
 *
 *     So driving NLEN_FR HIGH forces NL HIGH on its own - the main CPU can
 *     VETO the low state single-handed. What needs both processors is pulling
 *     NL LOW, and every reset and every default leaves it HIGH.
 *     hc_power_nl_predict() below is that table in code so a gate can test it.
 *
 *     AND WHICH LEVEL MEANS "STAY ALIVE" IS INFERRED, NOT READ. The CJ910
 *     datasheet is not in this repository. Two things point the same way:
 *     the OEM holds NLEN_FR HIGH while running and only clears it on its
 *     shutdown paths, and HaniCore has held it HIGH since RESETDIAG_V3
 *     across sixteen hardware sessions during which this ECU has always
 *     powered down with KL15. Were HIGH the "hold my power on" level, the
 *     bench would have met an ECU that would not switch off. So NL is
 *     ACTIVE LOW - "run-on requested" - and holding P3.12 HIGH is a
 *     PERMANENT VETO of run-on, which is exactly what a build with no run-on
 *     logic should be doing. The function is still called
 *     hc_power_hold_assert() because renaming it would break the audit that
 *     checks no instruction can un-assert it; the name predates this
 *     derivation and the behaviour is unchanged and correct.
 *
 *  4. NL lands on S4000 pin 26. S4000 is a CJ910 (1267360147) and it is not
 *     just the K-line transceiver - it is the ECU's power supply. Pin 20 is
 *     UBATT, pin 21 EIN comes from KL15 through R4000, pin 24 VCC is the 5 V
 *     rail that feeds VCC_IN / VCC_CPU / VREF, pin 28 STBY is VSTBY, and pin
 *     27 RES is the RESET net.
 *
 *  5. That RESET net goes back to the Rechnerkern sheet into the LM2901
 *     comparator network (S5400, through D5402) whose open-collector outputs
 *     are wired-OR onto NMI_FR / RSTIN_FR / RSTIN_SM / ESRST_SM / RST_FLASH /
 *     ED_RST. So the supply's own reset request arrives at the CPU as
 *     "NMI, then a long hardware reset" - which is the exact signature the
 *     bench recorded: TR=0002 then RAW=001C with WDTR clear.
 *
 * WHAT THE OEM DOES. In OEM ME7.1.1 there is exactly ONE register write to P3 in
 * the whole 1 MiB image, and it is inside the port-init routine at
 * seg8C:0DCC:
 *
 *      MOV ODP3, #0B01h        ; open drain
 *      MOV P3,   #BF01h        ; latch  - bit 12 SET
 *      MOV DP3,  #35FEh        ; direction - bit 12 SET, so it drives
 *
 * Latch before direction. That routine is called from seg8C:0B4A, and EINIT
 * is at seg8C:0B62 - four calls later. The OEM therefore asserts NLEN_FR
 * before interrupts are even enabled.
 *
 * Everywhere else P3.12 appears it is BSET/BCLR, and the sites read exactly
 * as a power hold should:
 *      0x8B162E   BSET P3.12 ; JMPR $        - hold power, then hang
 *      0x8B7B80   BSET P3.12 ; MOV SP,#F700h ; CALLS 0x000320 - hold, restart
 *      0x8B5088   BCLR P3.12                 - shutdown paths
 *
 * WHAT THE HARDWARE SAID. RESETDIAG_V3 A/B-ed this pin on the real ECU and
 * the answer was NULL: asserted or not, the reset stayed at PT=0x0134 with
 * RAW=0x001C and TR=0x0002, bit for bit.
 *
 * It also explained itself. The BASE half reported NL=0001/0000 - latch 0,
 * direction INPUT, and the bit reading 1. On the C167 a port bit configured as
 * an input reads the PIN, not the latch, so P3.12 was sitting HIGH with
 * nothing driving it: the net is externally pulled up (R5601, 10k, on the
 * S5600 gate input is the obvious candidate). NLEN_FR was never missing, so
 * asserting it could not change anything.
 *
 * WHY IT IS STILL ASSERTED. Because the OEM does it, in port init, before
 * EINIT, and correct platform state costs nothing to keep. It makes the line
 * deterministic and push-pull instead of dependent on a pull-up. It is NOT
 * claimed to solve anything.
 *
 * AND ONE THING THE SAME RUN PROVED ABOUT THE SUPPLY. Every reset reports
 * RAW=0x001C - LHWR|SHWR|SWR - with PONR CLEAR, while the first boot of a
 * session reports 0x3C. The flags nest on this part, so a genuine power-on
 * always sets PONR. It never does. The 5 V rail is therefore NOT cycling, and
 * the whole class of "the CJ910 shut us down" explanations - including the one
 * this module was written to test - is ruled out by the ECU's own flags.
 *
 * BYTDIS. P3.12's alternate function is BHE, and the latch would be inert
 * with BHE enabled. HaniCore's startup already writes SYSCON 0xE644 / 0xE244,
 * both of which have BYTDIS (bit 9) set, so the pin is free. Nothing needs to
 * change for this to take effect.
 */
#include <reg167.h>
#include "hctarget.h"
#include "hcpower.h"

/* Bit-addressed on purpose. P3 also carries MRST/MTSR/SSCLK (P3.8/9/13), TXD0
   and RXD0 (P3.10/11) and T0IN (P3.0). A read-modify-write of the whole port
   would disturb the K-line, which is the one thing on this ECU known to work. */
sbit NLEN_FR_LATCH = P3  ^ TGT_NLEN_FR_PORT_BIT;
sbit NLEN_FR_DIR   = DP3 ^ TGT_NLEN_FR_PORT_BIT;

unsigned char hc_power_hold_done = 0;

void hc_power_hold_assert(void)
{
    NLEN_FR_LATCH = 1;     /* drive value first ... */
    NLEN_FR_DIR   = 1;     /* ... then enable the driver. Never the reverse. */
    hc_power_hold_done = 1;
}

/* hc_power_hold_release() is deliberately NOT built. It existed so the run-on
   story would be complete, but nothing calls it, and tools/me711_wdt_audit.py
   check H requires that no instruction in the image can un-assert NLEN_FR. A
   dead routine that clears the ECU's own power hold is exactly the kind of
   thing that should not be one stray call away. It comes back when run-on is
   actually implemented, and the audit will be updated in the same commit. */

unsigned char hc_power_hold_state(void)
{
    return (unsigned char)(NLEN_FR_DIR && NLEN_FR_LATCH);
}

/* The S5600 network as a function, so the derivation above is testable rather
   than merely written down. Pure: no port, no state, no side effect.

        NL = NAND( NOT(nlen_fr), nlen_as )

   Call it with the RESET defaults - nlen_fr 1 (R5602 pulls up), nlen_as 0
   (R5601 pulls down) - and it must answer 1. If it ever answers 0 for that
   pair, either this function or the schematic reading is wrong, and
   tools/me711_power_path_proof.py fails rather than the ECU switching itself
   off on a bench. */
unsigned char hc_power_nl_predict(unsigned char nlen_fr, unsigned char nlen_as)
{
    unsigned char a = (unsigned char)(nlen_fr ? 0u : 1u);   /* gate A */
    unsigned char as = (unsigned char)(nlen_as ? 1u : 0u);
    return (unsigned char)((a && as) ? TGT_NL_LOW : TGT_NL_HIGH);
}
