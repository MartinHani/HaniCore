/*
 * hcpower.h - NLEN_FR, the Bosch ME7.1.1 power hold.
 *
 * NOT COMPILED INTO RESETDIAG_V2. This is prepared source for the image after
 * it. See docs/ARCHITECTURE.md for the evidence chain.
 */
#ifndef HCPOWER_H
#define HCPOWER_H

/* Assert NLEN_FR: latch HIGH first, then turn the pin into an output - the
   order the OEM uses, and the only order that never emits a low glitch on a
   line that gates the ECU's own 5 V regulator. Safe to call before EINIT. */
void hc_power_hold_assert(void);

/* 1 when the latch is commanded high AND the pin is an output. Reads the
   latch, not the pin: P3.12 has no external drive to sense. */
unsigned char hc_power_hold_state(void);

/* Non-zero once hc_power_hold_assert() has run. Published so a bench log can
   distinguish "asserted" from "never reached the call". */
extern unsigned char hc_power_hold_done;

/* The S5600 74ACT00 network, as a pure function of the two processors' request
   lines, so the schematic reading in hcpower.c is a thing a gate can execute:

       NL = NLEN_FR OR NOT(NLEN_AS)

   Returns TGT_NL_HIGH / TGT_NL_LOW. NL LOW needs BOTH - the FR released and
   the ASIC asserting - and no reset state produces it. */
unsigned char hc_power_nl_predict(unsigned char nlen_fr, unsigned char nlen_as);

#endif
