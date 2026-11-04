/*
 * hcasicframe.c - HaniCore's own 96-word ASIC startup frame.
 *
 * Pure computation on a caller's buffer: no SFR, no SSC, no PEC, no P6.4.
 * That is deliberate and it is what lets tests/host/ compile and run THIS
 * module on the host rather than a copy of it.
 *
 * WHERE THE CONTENT COMES FROM. The OEM startup frame is not a flash constant:
 * 0x8BE244 returns the near pointer 0x813E, and DPP2 = 0x00E0 in all 22 of its
 * initialisations, so the frame lives at PHYSICAL 0x38013E - battery-backed
 * SRAM. Exactly one routine fills it, 0x8B189C..0x8B1BB0, and it is
 * straight-line code. tools/an OEM-firmware analysis script (not published) decodes it into
 * build/generated/me711_asic_startup_frame.csv; the table below is that
 * decode.
 *
 *   w0..w3    0055 003B 0000 0020   header, identical every boot
 *   w4..w34   zero
 *   w35..w42  0x0888 x 8
 *   w43..w57  (cal & mask) | (default & ~mask), cal 0x828A08+, masks 0x828A34+
 *   w58..w94  mostly zero; 00BF@60, 434A@79 and 82, 006F@84, 006E@88,
 *             and 0001@92 - written as two BYTE stores, see below
 *   w95       additive sum of words 0..94, written at send time
 *
 * Word 93 alone is never written by the OEM builder - it keeps whatever the
 * battery-backed SRAM held. HaniCore sends zero and says so.
 *
 * ============================ WHY THIS TRANSMITS THE OEM VALUES VERBATIM ====
 *
 * An earlier revision of this file zeroed words 35..42 because eight identical
 * slots on a V8 look like per-cylinder configuration. That was the right
 * instinct and the wrong answer, for four reasons:
 *
 * 1. THE ASIC VALIDATES WHAT IT RECEIVES AND RESETS US IF IT IS WRONG. The
 *    ASIC IROM checks one's-complement pairs across the received frame and, on
 *    ANY mismatch, executes
 *        0x007878  BCLR P1H.2   ESRST_SM - kill EGAS and the output stages
 *        0x00787A  BCLR P1H.3   SWRST_SM - reset the main computer
 *    A frame we have "made safer" by altering fields is a frame that can fail
 *    validation, and the failure action is the very reset we are trying to
 *    stop. Sending a mutilated frame is not the cautious option; it is the
 *    option that guarantees no information.
 *
 * 2. THIS IS THE OEM'S OWN POWER-ON FRAME. It is built by a dispatch-table
 *    init routine from compile-time constants, before the engine can turn and
 *    before any sensor has been read. If these values enabled actuators, every
 *    ME7.1.1 would energise something at key-on.
 *
 * 3. 0x0888 EXISTS NOWHERE ELSE. In the whole 1 MiB image the constant appears
 *    exactly eight times, consecutively, in this one builder. MAIN never
 *    computes with it, never compares against it, and never re-sends it. It is
 *    not a runtime actuator command.
 *
 * 4. THE ACTUATORS ARE NOT ON THE ASIC'S SIDE OF THE FENCE. Coils are P2.0-7
 *    and injectors P7.4-7 / P8.3-7 - MAIN CPU pins. HaniCore's startup drives
 *    every one of them low and leaves them INPUTS, and the engine layer is not
 *    compiled into this build at all. The ASIC's ESRST_SM can only *inhibit*
 *    those stages; removing an inhibit on a pin nothing is driving does not
 *    move current. That is the second of the two layers.
 *
 * So: transmit what the OEM transmits, and keep MAIN's own pins dead. If a
 * future finding shows a specific word is an output enable whose OFF value is
 * known, change THAT word and say why.
 *
 * HC_ASICFRAME_SUPPRESS_UNCLASSIFIED restores the old zeroing behaviour for
 * offline diffing and experiments. It is off by default and the frame it
 * produces is NOT expected to pass ASIC validation.
 */
#include "hcasicframe.h"

/* The OEM frame, decoded. Index == frame word. */
#ifdef HC_ASICFRAME_C4
/* THE AUDI 2.7T ME7.1 C4 STARTUP FRAME (2026-10-27), decoded from its OWN
   builder 4B0907551F 0x871872..0x871BA6 into 0x380194 (returned by
   0x87666A as the startup source) with tools/analysis/
   an OEM-firmware analysis script (not published) pointed at it; words 43..57 are the
   (cal & mask) | (default & ~mask) fields evaluated from the stock page
   0x81E212.. [EXACT TARGET BINARY]. Different from the Porsche's in w0
   (0x005F - the only header the C4 IROM accepts, 0x0019E4), 45/46/48/50/51
   and 60; w92..w94 are written by nothing in the C4 image (0 here). The
   Porsche frame sent here before made the real S5500 ignore the startup,
   never ask a monitoring question, and reset MAIN after ~300 ms. */
static const unsigned short HCAF_HUGE oem_frame[HC_ASICFRAME_WORDS] = {   /* HCONST: NCONST relief 2026-11-03 */
    0x005Fu, 0x003Bu, 0x0000u, 0x0020u, 0x0000u, 0x0000u, 0x0000u, 0x0000u,
    0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u,
    0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u,
    0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u,
    0x0000u, 0x0000u, 0x0000u, 0x0888u, 0x0888u, 0x0888u, 0x0888u, 0x0888u,
    0x0888u, 0x0888u, 0x0888u, 0x0000u, 0x0000u, 0x00F1u, 0x4869u, 0x0100u,
    0x0011u, 0x0000u, 0x00F1u, 0x008Du, 0x0200u, 0x2000u, 0x0000u, 0x0000u,
    0x0000u, 0x00FFu, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u,
    0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u,
    0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x434Au,
    0x0000u, 0x0000u, 0x434Au, 0x0000u, 0x006Fu, 0x0000u, 0x0000u, 0x0000u,
    0x006Eu, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u
};
#else
static const unsigned short HCAF_HUGE oem_frame[HC_ASICFRAME_WORDS] = {   /* HCONST: NCONST relief 2026-11-03 */
    0x0055u, 0x003Bu, 0x0000u, 0x0020u, 0x0000u, 0x0000u, 0x0000u, 0x0000u,
    0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u,
    0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u,
    0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u,
    0x0000u, 0x0000u, 0x0000u, 0x0888u, 0x0888u, 0x0888u, 0x0888u, 0x0888u,
    0x0888u, 0x0888u, 0x0888u, 0x0000u, 0x0000u, 0x00FDu, 0x7079u, 0x0100u,
    0x00D1u, 0x0000u, 0x00FFu, 0x00DDu, 0x0200u, 0x2000u, 0x0000u, 0x0000u,
    0x0000u, 0x00FFu, 0x0000u, 0x0000u, 0x00BFu, 0x0000u, 0x0000u, 0x0000u,
    0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u,
    0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x0000u, 0x434Au,
    0x0000u, 0x0000u, 0x434Au, 0x0000u, 0x006Fu, 0x0000u, 0x0000u, 0x0000u,
    0x006Eu, 0x0000u, 0x0000u, 0x0000u, 0x0001u, 0x0000u, 0x0000u, 0x0000u
    /*                                     ^w92                              */
};
#endif

#ifdef HC_ASICFRAME_SUPPRESS_UNCLASSIFIED
static unsigned char word_is_unclassified(unsigned int i)
{
    if (i >= HC_ASICFRAME_UNSAFE_LO && i <= HC_ASICFRAME_UNSAFE_HI) return 1u;
    if (i == 93u) return 1u;
    return 0u;
}
#endif

unsigned short HCAF_FAR hc_asicframe_checksum(const unsigned short *frame)
{
    unsigned short sum = 0u;
    unsigned int i;
    for (i = 0u; i < HC_ASICFRAME_CKSUM_WORD; i++)
        sum = (unsigned short)(sum + frame[i]);
    return sum;
}

unsigned int HCAF_FAR hc_asic_build_safe_startup_frame(unsigned short *frame)
{
    unsigned int i;
    unsigned int suppressed = 0u;

    for (i = 0u; i < HC_ASICFRAME_WORDS; i++) {
        if (i == HC_ASICFRAME_CKSUM_WORD) {
            frame[i] = 0u;                  /* filled in below */
#ifdef HC_ASICFRAME_SUPPRESS_UNCLASSIFIED
        } else if (word_is_unclassified(i)) {
            frame[i] = 0u;
            suppressed++;
#endif
        } else if (i == 93u) {
            /* w93 @0x81F8 is the ONE word the OEM builder never writes - its
               only apparent reference, 0x81E4DC, lies inside a misaligned DB
               run. The OEM therefore transmits whatever the battery-backed
               SRAM happens to hold, so it cannot be validated strictly and
               zero is as defensible as any value.

               w92 is NOT in this class any more. It is built by two BYTE
               stores, which a word-only decoder never saw:
                 0x8B1BA8  MOVB RL4,#1h
                 0x8B1BAA  MOVB 81F6,RL4     w92 low  = 0x01
                 0x8B1BAE  MOVB 81F7,ZEROS   w92 high = 0x00
               so the OEM value is 0x0001 and every image before V9 sent 0. */
            frame[i] = 0u;
        } else {
            frame[i] = oem_frame[i];
        }
    }

    frame[HC_ASICFRAME_CKSUM_WORD] = hc_asicframe_checksum(frame);
    return suppressed;
}

unsigned char HCAF_FAR hc_asicframe_valid(const unsigned short *frame)
{
    if (frame[0] != HC_ASICFRAME_HDR0) return 0u;
    if (frame[1] != HC_ASICFRAME_HDR1) return 0u;
    if (frame[3] != HC_ASICFRAME_HDR3) return 0u;
    return (unsigned char)(frame[HC_ASICFRAME_CKSUM_WORD]
                           == hc_asicframe_checksum(frame));
}

/* The reply arrives in the SAME buffer - the exchange is in place. MAIN's own
   acceptance test, [BIN] 0x8BE7EC..0x8BE7FC, is exactly this: checksum words
   0..94 and compare against word 95. It does NOT check the reply's header,
   which is why this does not either. */
unsigned char HCAF_FAR hc_asicframe_reply_ok(const unsigned short *frame)
{
    return (unsigned char)(frame[HC_ASICFRAME_CKSUM_WORD]
                           == hc_asicframe_checksum(frame));
}

/* One word of the startup frame under the current policy, WITHOUT building
   the whole thing first. This exists because the obvious API - fill a caller's
   96-word array - puts 192 bytes on the stack, and the C167's system stack
   here is 250 bytes total (0xF606..0xF700). The simulator caught exactly that
   as a STACK OVERFLOW; the honest fix is not a bigger stack but not needing
   the buffer. The caller streams words straight into the PEC frame and
   accumulates the checksum as it goes. */
unsigned short HCAF_FAR hc_asicframe_word(unsigned int i)
{
    if (i >= HC_ASICFRAME_WORDS) return 0u;
    if (i == HC_ASICFRAME_CKSUM_WORD) return 0u;   /* caller supplies the sum */
#ifdef HC_ASICFRAME_SUPPRESS_UNCLASSIFIED
    if (word_is_unclassified(i)) return 0u;
#endif
    if (i == 93u) return 0u;      /* the only word the OEM never writes */
    return oem_frame[i];
}

unsigned short HCAF_FAR hc_asicframe_oem_word(unsigned int i)
{
    return (i < HC_ASICFRAME_WORDS) ? oem_frame[i] : 0u;
}
