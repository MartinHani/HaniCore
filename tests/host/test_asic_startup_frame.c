/*
 * test_asic_startup_frame.c - host tests for the Bosch ASIC startup frame.
 *
 * Compiles and links the REAL hcasicframe.c, not a transcription of it. That
 * module deliberately touches no SFR so this is possible; if someone later
 * adds hardware access to it, this test stops building, which is the point.
 *
 *   gcc -std=c99 -Wall -Wextra -o test tests/host/test_asic_startup_frame.c \
 *       firmware/targets/me711/asic/hcasicframe.c \
 *       -Ifirmware/targets/me711
 */
#include <stdio.h>
#include <string.h>
#include "hcasicframe.h"

static int fails = 0;
static int total = 0;

static void check(const char *name, int ok, const char *detail)
{
    total++;
    if (!ok) fails++;
    printf("  [%s] %-58s %s\n", ok ? "PASS" : "FAIL", name, detail ? detail : "");
}

int main(void)
{
    unsigned short f[HC_ASICFRAME_WORDS];
    unsigned short g[HC_ASICFRAME_WORDS];
    unsigned int suppressed, i;
    unsigned long sum;
    char buf[128];

    printf("=== Bosch ME7.1.1 ASIC startup frame - host tests ===\n\n");

    memset(f, 0xA5, sizeof f);
    suppressed = hc_asic_build_safe_startup_frame(f);

    /* --- the frame is well formed ------------------------------------- */
    sprintf(buf, "0x%04X", f[0]);
    check("word 0 is the OEM header 0x0055", f[0] == HC_ASICFRAME_HDR0, buf);
    sprintf(buf, "0x%04X", f[1]);
    check("word 1 is the OEM header 0x003B", f[1] == HC_ASICFRAME_HDR1, buf);
    sprintf(buf, "0x%04X", f[3]);
    check("word 3 is the OEM header 0x0020", f[3] == HC_ASICFRAME_HDR3, buf);

    sum = 0;
    for (i = 0; i < HC_ASICFRAME_CKSUM_WORD; i++) sum += f[i];
    sprintf(buf, "stored 0x%04X, computed 0x%04X",
            f[HC_ASICFRAME_CKSUM_WORD], (unsigned short)(sum & 0xFFFF));
    check("word 95 is the additive checksum of words 0..94",
          f[HC_ASICFRAME_CKSUM_WORD] == (unsigned short)(sum & 0xFFFF), buf);

    check("hc_asicframe_valid accepts what the builder produced",
          hc_asicframe_valid(f) == 1, NULL);

    /* --- the policy: OEM values verbatim ------------------------------- */
    sprintf(buf, "%u words", suppressed);
    check("nothing is suppressed by default", suppressed == 0u, buf);
    {
        int n = 0;
        for (i = HC_ASICFRAME_UNSAFE_LO; i <= HC_ASICFRAME_UNSAFE_HI; i++)
            if (f[i] == HC_ASICFRAME_OEM_UNSAFE) n++;
        sprintf(buf, "%d of 8", n);
        check("the eight 0x0888 slots carry the OEM value", n == 8, buf);
    }
    {
        /* CORRECTED for V9. w92 is NOT unwritten: the OEM builds it with two
           BYTE stores, which a word-only decoder never saw -
             0x8B1BA8  MOVB RL4,#1h
             0x8B1BAA  MOVB 81F6,RL4     w92 low  = 0x01
             0x8B1BAE  MOVB 81F7,ZEROS   w92 high = 0x00
           so the OEM value is 0x0001 and every image up to V8 sent 0x0000.
           w94 is written as a plain ZEROS at 0x8B1BB2. w93 is the ONE word the
           builder never touches. */
        sprintf(buf, "w92=%04X w93=%04X w94=%04X", f[92], f[93], f[94]);
        check("w92 carries the OEM value 0x0001", f[92] == 0x0001u, buf);
        check("w93, the only word the OEM never writes, is zero",
              f[93] == 0x0000u, buf);
        check("w94 is the OEM's hard zero", f[94] == 0x0000u, buf);
    }

    /* --- streaming and buffered builders must agree -------------------- */
    {
        int same = 1;
        for (i = 0; i < HC_ASICFRAME_WORDS; i++) {
            unsigned short w = hc_asicframe_word(i);
            if (i == HC_ASICFRAME_CKSUM_WORD) continue;
            if (w != f[i]) same = 0;
        }
        check("hc_asicframe_word matches the buffered build word for word",
              same, "the firmware streams; the tests buffer");
    }
    {
        /* Stream it exactly as hcasicstart.c does and compare the checksum. */
        unsigned long sum = 0;
        for (i = 0; i < HC_ASICFRAME_CKSUM_WORD; i++)
            sum += hc_asicframe_word(i);
        sprintf(buf, "streamed 0x%04X vs built 0x%04X",
                (unsigned short)(sum & 0xFFFF), f[HC_ASICFRAME_CKSUM_WORD]);
        check("the streamed checksum equals the buffered one",
              (unsigned short)(sum & 0xFFFF) == f[HC_ASICFRAME_CKSUM_WORD],
              buf);
    }

    /* --- the reply test MAIN actually performs ------------------------- */
    check("a reply whose word 95 matches its own sum is accepted",
          hc_asicframe_reply_ok(f) == 1, "checksum only, as 0x8BE7EC does");
    {
        unsigned short g2[HC_ASICFRAME_WORDS];
        memcpy(g2, f, sizeof g2);
        g2[7] ^= 0x0040u;
        check("a corrupted reply is rejected",
              hc_asicframe_reply_ok(g2) == 0, NULL);
    }

    /* --- the OEM values are still available for diffing ---------------- */
    check("the OEM table still reports 0x0888 at word 35",
          hc_asicframe_oem_word(35) == HC_ASICFRAME_OEM_UNSAFE, NULL);
    check("out-of-range OEM lookups return 0, not garbage",
          hc_asicframe_oem_word(HC_ASICFRAME_WORDS) == 0u, NULL);

    /* --- calibration-driven words are reproduced ----------------------- */
    sprintf(buf, "w45=0x%04X w46=0x%04X w47=0x%04X", f[45], f[46], f[47]);
    check("the calibration-driven block 43..57 is reproduced",
          f[45] == 0x00FDu && f[46] == 0x7079u && f[47] == 0x0100u
          && f[57] == 0x00FFu, buf);

    /* --- determinism ---------------------------------------------------- */
    memset(g, 0x00, sizeof g);
    hc_asic_build_safe_startup_frame(g);
    check("the builder is deterministic and independent of prior buffer state",
          memcmp(f, g, sizeof f) == 0, NULL);

    /* --- the validator actually rejects --------------------------------- */
    g[10] ^= 0x0001u;
    check("a single flipped payload bit fails validation",
          hc_asicframe_valid(g) == 0, NULL);
    hc_asic_build_safe_startup_frame(g);
    g[0] = 0x0000u;
    g[HC_ASICFRAME_CKSUM_WORD] = hc_asicframe_checksum(g);
    check("a correct checksum over a WRONG header still fails validation",
          hc_asicframe_valid(g) == 0, "header is checked separately");

    printf("\n%d/%d checks pass\n", total - fails, total);
    if (fails) { printf("HOST TESTS FAILED\n"); return 1; }
    printf("HOST TESTS PASS - and as of ASICLIVE_V4 this frame IS transmitted\n");
    return 0;
}
