/*
 * hcknock.h - the knock-control strategy core (V97, SFR-free, host-tested).
 *
 * Input: one integrated knock-window value per ignition, per cylinder (the
 * CC195's integrator KI, read by the ADC: counts 0..1023). Output: an
 * ignition retard per cylinder. No hardware here: the window, gain, band
 * and sensor select are the driver's (the maintainer's design notes).
 *
 * The strategy is the Bosch ME7 KR one, whose structure and parameter set
 * are read from the Porsche ME7.1.1 sibling A2L + its own binary
 * (tools/an OEM-firmware analysis script (not published), SAME-FAMILY ECU REFERENCE), with rusEFI's
 * time-based reapply (knock_controller.cpp, SOFTWARE REFERENCE):
 *
 *   detection   ikr > rkr x kef           KRKE: KFKEF per cylinder, rkr the
 *                                         reference level, x FKENDY in
 *                                         dynamics
 *   reference   rkr += (ikr - rkr) / tp   KRFTP1 (16) / KRFTP2,3 (4) in
 *                                         dynamics; ONLY on a quiet ignition
 *                                         (a knock must not raise its own
 *                                         threshold); start REFINI
 *   retard      +step on a knock, <= max  KRFKN 2.25 deg, KRMXN 18 deg -
 *                                         PER CYLINDER (not rusEFI's global)
 *   reapply     -1 q every reapply_ms     KRVFN ignitions/step (~1.7..2.5 s
 *               of that cylinder's quiet  per 0.75 deg); rusEFI deg/s
 *   sensor      reference out of          KS diagnosis -> KRDWSN safety
 *   fault       [ref_min, ref_max]        retard (15 deg) on the sensor's
 *                                         cylinders, latched to reset
 *   at stop     stop_n knocks in a row    KRA (DKRAMX): retard at its
 *               at the ceiling            ceiling does not cure it; latched
 *
 * A knock is never learned into the reference - but a knock just BELOW the
 * threshold is (as in the OEM scheme): sustained borderline knock raises
 * the reference. The "at stop" flag and the ref_max diagnosis are the
 * guards, as in the OEM; neither is a substitute for a tuned threshold.
 *
 * Units: q = 0.25 deg crank; ikr and reference levels in ADC counts.
 * 16-bit arithmetic only (this module is far code; Keil's long helpers are
 * near): every product is split so it provably fits (hcknock.c).
 */
#ifndef HCKNOCK_H
#define HCKNOCK_H

#ifdef __C166__
#define HCKNOCK_FAR far
#define HCKNOCK_MEM huge      /* the state lives in external SRAM on ME7.1.1 */
#else
#define HCKNOCK_FAR
#define HCKNOCK_MEM
#endif

#define HCKNOCK_CYL   8u
#define HCKNOCK_SENS  4u
#define HCKNOCK_KEFN  6u          /* threshold-factor curve points (rusEFI 6) */

typedef struct {
    unsigned char cyls;                     /* 1..8                           */
    unsigned char sensor[HCKNOCK_CYL];      /* cylinder -> sensor 0..3        */
    unsigned int  rpm_min;                  /* NKRF / rusEFI: below = off     */
    unsigned char load_min;                 /* LKRN, % (rusEFI knockSuppressMinTps) */
    signed char   clt_min;                  /* TMKR, deg C                    */
    unsigned char tp, tp_dyn;               /* reference low pass, 1..32      */
    unsigned int  kef_rpm[HCKNOCK_KEFN];    /* ascending                      */
    unsigned char kef16[HCKNOCK_KEFN];      /* threshold factor x16, >= 16    */
    unsigned char kef_dyn16;                /* dynamics multiplier x16, >= 16 */
    unsigned int  ref_init;                 /* REFINI, counts                 */
    unsigned char learn;                    /* quiet ignitions/cyl before a
                                               knock can be detected          */
    unsigned char step_q;                   /* retard per knock               */
    unsigned char max_q;                    /* retard ceiling                 */
    unsigned char safe_q;                   /* sensor-fault retard            */
    unsigned int  reapply_ms;               /* ms per q of recovery, >= 1     */
    unsigned int  diag_rpm;                 /* sensor diagnosis above this    */
    unsigned int  ref_min, ref_max;         /* plausible reference, counts    */
    unsigned char diag_n;                   /* consecutive implausible ign.   */
    unsigned char stop_n;                   /* consecutive knocks AT the
                                               ceiling -> "at stop" (Bosch
                                               KRA, DKRAMX); 0 = off          */
} hcknock_cfg_t;

typedef struct {
    unsigned int  ikr;                      /* counts 0..1023                 */
    unsigned int  rpm;
    unsigned char load;                     /* %                              */
    signed char   clt;                      /* deg C                          */
    unsigned char dyn;                      /* load/speed dynamics            */
} hcknock_in_t;

typedef struct {
    unsigned int  ref16[HCKNOCK_CYL];       /* reference x16                  */
    signed char   rem[HCKNOCK_CYL];         /* low-pass remainder (exact)     */
    unsigned char seen[HCKNOCK_CYL];        /* quiet ignitions, sat. learn    */
    unsigned char ret_q[HCKNOCK_CYL];       /* knock retard                   */
    unsigned int  quiet_ms[HCKNOCK_CYL];    /* since the last change          */
    unsigned char level16[HCKNOCK_CYL];     /* last ikr/ref x16, sat 255      */
    unsigned char kcount[HCKNOCK_CYL];      /* knocks, saturating             */
    unsigned int  knocks;                   /* all cylinders, wrapping        */
    unsigned int  at_max;                   /* knocks at the ceiling (KRA)    */
    unsigned char bad[HCKNOCK_SENS];        /* implausible run per sensor     */
    unsigned char fault;                    /* bit per sensor, latched        */
    unsigned char fault_hi;                 /* bit per sensor: too loud       */
    unsigned char maxrun[HCKNOCK_CYL];      /* consecutive knocks at ceiling  */
    unsigned char stop;                     /* bit per cylinder, latched: the
                                               retard cannot cure it (a real
                                               problem, or a reference that
                                               cannot learn - DTC material)   */
    unsigned char active;                   /* last ignition was evaluated    */
} hcknock_t;

/* 0 = usable, else a HCKNOCK_E_* naming the first bad field */
#define HCKNOCK_E_CYLS    1u
#define HCKNOCK_E_SENSOR  2u
#define HCKNOCK_E_TP      3u
#define HCKNOCK_E_KEF     4u
#define HCKNOCK_E_RETARD  5u
#define HCKNOCK_E_REAPPLY 6u
#define HCKNOCK_E_REF     7u

unsigned char HCKNOCK_FAR hcknock_check(const hcknock_cfg_t HCKNOCK_MEM *cfg);
void HCKNOCK_FAR hcknock_reset(hcknock_t HCKNOCK_MEM *k,
                              const hcknock_cfg_t HCKNOCK_MEM *cfg);
/* one ignition of cylinder cyl (0-based firing cylinder); returns 1 on a
   detected knock. An out-of-range cylinder is ignored. */
unsigned char HCKNOCK_FAR hcknock_ignition(hcknock_t HCKNOCK_MEM *k,
                                           const hcknock_cfg_t HCKNOCK_MEM *cfg,
                                           unsigned char cyl, const hcknock_in_t *in);
/* elapsed time; recovery runs whether or not knock control is active */
void HCKNOCK_FAR hcknock_tick(hcknock_t HCKNOCK_MEM *k,
                             const hcknock_cfg_t HCKNOCK_MEM *cfg, unsigned int ms);
/* the retard to apply to cylinder cyl, q: max(knock retard, fault retard) */
unsigned char HCKNOCK_FAR hcknock_retard(const hcknock_t HCKNOCK_MEM *k,
                                         const hcknock_cfg_t HCKNOCK_MEM *cfg,
                                         unsigned char cyl);
/* exposed for the exhaustive bounds test: floor(r4 * kef16 / 16) in 16 bits */
unsigned int HCKNOCK_FAR hcknock_thr4(unsigned int r4, unsigned char kef16);

#endif
