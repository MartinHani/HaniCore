/*
 * hcasicframe.h - HaniCore's own 96-word ASIC startup frame.
 *
 * NOT COMPILED INTO RESETDIAG_V2. Pure computation on a caller's buffer: no
 * SFRs, no SSC, no PEC, no P6.4. That is what lets the host tests compile the
 * real module rather than a copy of it.
 */
#ifndef HCASICFRAME_H
#define HCASICFRAME_H

#define HC_ASICFRAME_WORDS       96u
#define HC_ASICFRAME_CKSUM_WORD  95u     /* additive sum of words 0..94 */

/* The header, fixed by the exchange and identical on every OEM startup. */
#define HC_ASICFRAME_HDR0        0x0055u
#define HC_ASICFRAME_HDR1        0x003Bu
#define HC_ASICFRAME_HDR3        0x0020u

/* The eight identical 0x0888 slots. Eight of anything on a V8 is per-cylinder
   or per-output-stage until proven otherwise, so this build zeroes them. */
#define HC_ASICFRAME_UNSAFE_LO   35u
#define HC_ASICFRAME_UNSAFE_HI   42u
#define HC_ASICFRAME_OEM_UNSAFE  0x0888u

/* Build the startup frame. Returns how many words were SUPPRESSED; with the
   default policy that is 0, because the frame the ASIC validates has to be
   the frame the OEM sends - see the long comment in hcasicframe.c for why
   zeroing fields is the LESS safe option here. */
unsigned int  hc_asic_build_safe_startup_frame(unsigned short *frame);

/* The additive checksum over words 0..94. */
unsigned short hc_asicframe_checksum(const unsigned short *frame);

/* Header and checksum well-formed? */
unsigned char hc_asicframe_valid(const unsigned short *frame);

/* Does a received reply pass MAIN's own acceptance test? [BIN] 0x8BE7EC:
   checksum words 0..94 and compare against word 95. Nothing else. */
unsigned char hc_asicframe_reply_ok(const unsigned short *frame);

/* One word of the frame under the current policy. Streaming beats buffering
   here: a 96-word local array is 192 bytes against a 250-byte system stack. */
unsigned short hc_asicframe_word(unsigned int i);

/* The OEM value for one word, for diffing offline. */
unsigned short hc_asicframe_oem_word(unsigned int i);

#endif
