/*
 * hccel.h - the check-engine lamp POLICY: what the lamp should show,
 * separate from any output driver. Pure, SFR-free, host-tested
 * (tools/test_hccel_host.py). docs/ARCHITECTURE.md "The lamp".
 *
 * The required lamp behaviour:
 *     0.0 .. 3.0 s after key-on   ON        (the lamp test: ECU alive,
 *                                            firmware running, path works)
 *     3.0 .. 4.0 s                OFF       (so a real fault reads ON-OFF-ON)
 *     from 4.0 s                  = the DTC system's MIL request, at once
 * The test runs on every key-on edge (a key cycle inside the run-on hold is
 * not a reset), whatever the DTCs say. Key off: OFF.
 *
 * The DTC system owns the MIL REQUEST (hcdtc.c: only MIL-class codes set
 * it); this owns the lamp STATE. Modes are an enum so FLASH_SLOW / FLASH_FAST
 * (protection warnings) can be added later without touching callers.
 */
#ifndef HCCEL_H
#define HCCEL_H

#ifdef __C166__
#define HCCEL_FAR far
#define HCCEL_MEM huge        /* the state lives in external SRAM on ME7.1.1 */
#else
#define HCCEL_FAR
#define HCCEL_MEM
#endif

#define HCCEL_OFF        0u
#define HCCEL_ON         1u      /* a MIL request                         */
#define HCCEL_TEST_ON    2u      /* key-on lamp test, 0..3 s              */
#define HCCEL_TEST_GAP   3u      /* the separating dark second, 3..4 s    */
/* 4, 5 reserved: FLASH_SLOW, FLASH_FAST */

#define HCCEL_TEST_ON_MS   3000u
#define HCCEL_TEST_END_MS  4000u

typedef struct {
    unsigned int  t0;        /* key-on edge, ms                           */
    unsigned char key;       /* key as last seen                          */
    unsigned char testing;   /* 1 until the test sequence has completed   */
    unsigned char mode;      /* HCCEL_*                                   */
    unsigned char cmd;       /* 1 = lamp ON                               */
    /* the page's lamp test (celTestEnable / celTestOnMs / celTestGapMs);
       hccel_reset() sets the 3 s ON + 1 s OFF */
    unsigned char test_en;
    unsigned int  on_ms, end_ms;
} hccel_t;

void HCCEL_FAR hccel_reset(hccel_t HCCEL_MEM *c);
/* the key-on lamp test from the page: enable, ON time, dark gap. A
   change takes effect at the next key-on edge (a running test keeps the
   times it started with only if they did not change - it reads them live). */
void HCCEL_FAR hccel_config(hccel_t HCCEL_MEM *c, unsigned char test_en,
                            unsigned int on_ms, unsigned int gap_ms);
/* Returns the lamp command (1 = ON). now_ms is a free-running uptime. */
unsigned char HCCEL_FAR hccel_step(hccel_t HCCEL_MEM *c, unsigned int now_ms,
                                   unsigned char key_on, unsigned char mil_req);

#endif
