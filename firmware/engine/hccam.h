/*
 * hccam.h - camshaft PATTERN decoding: which tooth of a known cam wheel an
 * edge is, which half of the 720 degree cycle the engine is in, and how far
 * the cam sits from its nominal position (VVT). SHARED CORE, SFR-FREE.
 *
 * WHY SPACING IN CRANK DEGREES. A cam is only decoded once the crank is
 * synchronised, so every cam edge arrives with an engine angle (the crank's
 * 0..720, correct up to the unknown half). The SPACING between two cam edges
 * in crank degrees is exact at any speed and under any acceleration, and a
 * cam phaser moves every tooth by the same amount, so it leaves the spacing
 * alone. The last few spacings therefore identify the tooth; the tooth's
 * measured angle against its nominal angle then says both the half (a
 * 360 degree difference) and the VVT deviation (a small one).
 * rusEFI (SOFTWARE REFERENCE IMPLEMENTATION, trigger_central.cpp
 * handleVvtCamSignal) decodes the cam wheel by TIME gap ratios and then aligns
 * the engine phase at the cam's sync tooth; the tooth angles of the pattern
 * library come from its decoders (trigger_universal.cpp, trigger_honda.cpp,
 * trigger_misc.cpp, trigger_nissan.cpp, trigger_mazda.cpp).
 *
 * WHAT IT NEVER DOES. It never moves the half on one tooth: CONFIRM
 * consecutive identified teeth must agree first, and once a whole cycle has
 * agreed on a half, more than a whole cycle of the other half. A window that
 * a single glitch can explain is read without the glitch - in the
 * established half first. Evidence for the OTHER half
 * withdraws a known cycle at once (a sequential engine must stop firing on a
 * stroke that may be wrong) and moves it only when confirmed. A pattern error
 * (an unidentifiable spacing: noise, a lost edge, a wrong pattern) costs the
 * cycle only after ERRLIMIT in a row, and never the crank - the caller keeps
 * crank sync whatever this says.
 *
 * The same object compiles into the C167 image and into the host tests
 * (tests/host/test_hccam.c), 16-bit arithmetic only.
 */
#ifndef HCCAM_H
#define HCCAM_H

/* The C167 image calls these from the near crank module into FCODE (this file
   is compiled MOD167 MEDIUM, its data renamed into the on-chip XRAM); the
   host test compiles them as ordinary functions. */
#ifdef __C166__
#define HCCAM_FAR far
#else
#define HCCAM_FAR
#endif

#define HCCAM_MAX_TEETH  8u
#define HCCAM_HIST       5u      /* spacings compared per identification     */
#define HCCAM_CYCLE      7200u   /* 720.0 degrees, 0.1 degree units           */
#define HCCAM_HALF       3600u

/* The pattern library (camPattern). Angles are CPU-pin edges of the
   configured polarity, crank degrees x10, relative to tooth 0. */
#define HCCAM_P_NONE          0u
#define HCCAM_P_SINGLE        1u   /* one tooth per cycle (Hall single window) */
#define HCCAM_P_EQUAL         2u   /* N equal teeth, N = equal_n (camRefs)     */
#define HCCAM_P_QUICKSTART    3u   /* Bosch quick-start (VAG 1.8T AWT, ...)    */
#define HCCAM_P_HONDA_K_4P1   4u   /* Honda K exhaust 4+1                      */
#define HCCAM_P_BARRA_3P1     5u   /* Ford Barra 3+1                           */
#define HCCAM_P_TOYOTA_4M1    6u   /* 4-1 (Toyota VVT)                         */
#define HCCAM_P_NISSAN_VQ     7u   /* Nissan VQ intake                         */
#define HCCAM_P_MIATA_NB      8u   /* Mazda Miata NB                           */
#define HCCAM_P_COUNT         9u

/* hccam_edge() actions - the caller applies them, in this order */
#define HCCAM_A_LOSE     0x01u   /* withdraw the cycle (FULL -> CRANK)        */
#define HCCAM_A_FLIP     0x02u   /* the engine is in the other half: +/-360   */
#define HCCAM_A_GRANT    0x04u   /* the cycle is known (CRANK -> FULL)        */

/* last classification (published) */
#define HCCAM_C_NONE     0u      /* learning / no crank sync                  */
#define HCCAM_C_SAME     1u      /* identified, this half                     */
#define HCCAM_C_OTHER    2u      /* identified, the other half                */
#define HCCAM_C_ALIVE    3u      /* seen, pattern cannot tell the half        */
#define HCCAM_C_ERROR    4u      /* spacing matches no tooth                  */
#define HCCAM_C_OFFSET   5u      /* tooth identified, angle outside authority */
#define HCCAM_C_NOISE    6u      /* closer than any tooth pair: ignored       */

typedef struct {
    unsigned char pattern;       /* HCCAM_P_*                                  */
    unsigned char equal_n;       /* teeth for HCCAM_P_EQUAL (1..8)             */
    unsigned int  offset_x10;    /* engine angle of tooth 0 at zero VVT        */
    unsigned int  tol_x10;       /* spacing match tolerance                    */
    unsigned int  auth_x10;      /* VVT authority: |deviation| accepted        */
    unsigned char confirm;       /* consistent teeth before a cycle decision   */
    unsigned char errlimit;      /* consecutive pattern errors before LOSE     */
} hccam_cfg_t;

typedef struct {
    hccam_cfg_t   cfg;
    /* the resolved pattern */
    unsigned char n;             /* teeth per cycle, 0 = no pattern            */
    unsigned int  rel[HCCAM_MAX_TEETH];
    unsigned int  sp[HCCAM_MAX_TEETH];  /* spacing ENDING at tooth i          */
    unsigned int  min_sp;
    unsigned char k;             /* spacings compared, min(n, HCCAM_HIST)      */
    unsigned char resolves;      /* the pattern can tell the half              */
    /* history of accepted edge angles (current-half coordinates) */
    unsigned int  hist[HCCAM_HIST + 2u];   /* k+1 for the window, +1 so an
                                              isolated glitch can be taken out */
    unsigned char hn;
    /* decision state */
    unsigned char same_run, other_run, err_run;
    unsigned char est;           /* a whole cycle has agreed on this half      */
    /* outputs */
    unsigned char cls;           /* HCCAM_C_* of the last edge                 */
    unsigned char tooth;         /* identified tooth, 0xFF none                */
    int           dev_x10;       /* last identified tooth: measured - nominal  */
    int           sync_dev_x10;  /* the same at tooth 0 (VVT position)         */
    unsigned int  errors, noise, glitches, missed, flips;
} hccam_t;

/* Resolve cfg into the pattern tables. Returns 0 when the configuration is
   unusable (unknown pattern, equal_n out of range, tolerance too wide for the
   pattern's closest teeth). */
unsigned char HCCAM_FAR hccam_init(hccam_t *c, const hccam_cfg_t *cfg);

/* The crank lost sync (or a reset): forget the history, keep the counters. */
void HCCAM_FAR hccam_reset(hccam_t *c);

/* One cam edge at engine angle a_x10 (0..7199, the half the crank decoder
   currently believes). crank_ok: the crank is synchronised; cycle_known:
   the cycle is currently claimed (FULL). Returns HCCAM_A_* flags. After
   HCCAM_A_FLIP the core has already moved its own history by 360 degrees:
   the NEXT angle it is given must be in the flipped coordinate. */
unsigned char HCCAM_FAR hccam_edge(hccam_t *c, unsigned int a_x10,
                         unsigned char crank_ok, unsigned char cycle_known);

/* For the validator: 0 = the configuration is unusable, 1 = usable but the
   pattern cannot decide the half across the configured VVT authority, 2 =
   it resolves the cycle. Uses a scratch of its own, never the live cams. */
unsigned char HCCAM_FAR hccam_check(const hccam_cfg_t *cfg);

/* The pattern's teeth (for the .ini help, tools and tests). */
unsigned char HCCAM_FAR hccam_pattern_teeth(unsigned char pattern, unsigned char equal_n,
                                  unsigned int *rel_out);

/* The image's two cams (index 0 = cam input 1). Defined in hccam.c so they
   live in XRAM with the core, not in the crank module's near RAM. */
extern hccam_t hccam_bank[2];

#endif /* HCCAM_H */
