/*
 * hcxfn711.h - the functions added 2026-11-03 after the Ignitron study
 * (throttle safety, ignition-first idle, starting, overrun, closed-loop
 * extras, knock strength / adaptation, boost limits, limp mode, throttle
 * shaping, traction). Settings: the page EXTENSION (hcconfig.h
 * HC_CFG_MAIN, tools/config_source/hanicore_ext_fields.py). Runtime state:
 * TGT_RAM_XSTATE (battery-backed SRAM). FCODE, MOD167 MEDIUM.
 *
 * Every hook is written so that a page with the extension all 0 behaves
 * exactly as before: each function returns its input unchanged.
 */
#ifndef HCXFN711_H
#define HCXFN711_H

/* the engine cut reasons this module owns (ENG_CUT_SAFE: fuel AND spark) */
#define HCX_CUT_DEV    0x01u   /* plate off target too long         */
#define HCX_CUT_PAIR   0x02u   /* throttle sensor pair fault        */
#define HCX_CUT_OIL    0x04u   /* start delay: no oil pressure yet  */
#define HCX_CUT_LIMP   0x08u   /* (not a cut: limp mode is active)  */
#define HCX_CUT_CRASH  0x10u   /* CAN airbag crash, until the key cycle */

#define HCX_LIMP_LEAN  0x01u
#define HCX_LIMP_MAP   0x02u
#define HCX_LIMP_CLT   0x04u
#define HCX_LIMP_KNOCK 0x08u

#define HCX_MAGIC      0x5844u /* 'XD': the learned values are valid */

typedef struct {
    /* KEPT across a reset (battery-backed, guarded by magic) */
    unsigned int  magic;
    int           idle_adapt[2];    /* 0.01 % throttle, A/C off / on      */
    unsigned char kad[16];          /* knock adaptation, 0.25 deg, [load][rpm] */
    /* cleared at boot */
    unsigned int  kad_ms;           /* decay clock                        */
    unsigned char cut_why;          /* HCX_CUT_*                          */
    unsigned char limp_why;         /* HCX_LIMP_*, latched to the stop    */
    unsigned int  dev_ms, lean_ms, map_ms, clt_ms;
    unsigned int  crank_ms;         /* this crank                         */
    unsigned int  revs_x100;        /* revolutions since crank sync, x100 */
    unsigned int  crank_pct;        /* cranking fuel factor in force      */
    long          ign_i;            /* idle spark integral, 0.1 deg x1000 */
    int           ign_out;          /* idle spark correction, 0.1 deg     */
    int           ign_from;         /* the fade starts here               */
    unsigned int  fade_ms;
    unsigned char closed_last;
    unsigned char kick_done;        /* bit per kick level                 */
    int           corr_x100;        /* throttle corrector, 0.01 %         */
    unsigned int  corr_ms;
    unsigned int  kick_x10;         /* throttle kicks in force, 0.1 %     */
    unsigned int  stall_x10;        /* anti-stall throttle, 0.1 %         */
    unsigned int  adapt_ms;
    unsigned int  dfco_pm;          /* fuel during the cut fade, per mille */
    unsigned int  rest_ms;          /* since the cut ended (restore)      */
    unsigned char dfco_hard, dfco_was;
    unsigned char o2sat[2];
    unsigned int  o2rec_ms[2];
    unsigned int  stft_act_ms;      /* closed loop active this long       */
    unsigned int  last_rpm;
    int           rpm_rate;         /* rpm/s, filtered                    */
    unsigned int  rate_ms;
    unsigned int  tc_ms;            /* traction hold                      */
    unsigned char tc;
    unsigned char have_ms;
    unsigned int  acc_ms, last_ms;
    unsigned int  wu_lam;           /* warm-up lambda x1000 (0 = off)     */
    unsigned int  blim_x10;         /* boost ceiling in force, kPa x10    */
    unsigned int  fuel_pm;          /* dfco fade / restore factor          */
    unsigned char kad_cell, kstr;    /* kstr: last knock strength x10 */
} hcx_t;

#define HCX (*(hcx_t huge *)(TGT_EXTRAM_BASE + TGT_RAM_XSTATE))

void          far hc_x_init(void);
void          far hc_x_service(unsigned int now_ms);     /* main loop      */
void          far hc_x_pre(unsigned int rpm, unsigned int dt_ms);  /* hc_ec_pre */
void          far hc_x_clear(void);                      /* '!D'           */
void          far hc_x_idle_adapt_clear(void);           /* AutoCal PASS   */

/* idle (hcidle711.c) */
unsigned int  far hc_x_idle_air(unsigned int floor_x10, unsigned int target,
                                unsigned char released, unsigned char closed,
                                unsigned int ms);
int           far hc_x_idle_timing(int p_x10, unsigned char closed,
                                   unsigned int target, unsigned int ms);
/* fuel / spark / lambda (hcengine.c, hcengctl711.c) */
unsigned int  far hc_x_crank_fuel(unsigned int mg_x10);
unsigned int  far hc_x_lambda(unsigned int lam_x1000);
int           far hc_x_spark(int adv_x10);
unsigned int  far hc_x_fuel_pm(void);
unsigned char far hc_x_dfco(unsigned char want, unsigned int dt_ms);
unsigned char far hc_x_o2_sat(unsigned char bank, unsigned int lam_x1000,
                              unsigned int dt_ms);
unsigned char far hc_x_stft_lean_locked(void);
int           far hc_x_stft_p(unsigned char region, int err_pm);
unsigned char far hc_x_tc_skip(void);
/* boost (hcboost711.c) */
unsigned int  far hc_x_boost_target(unsigned int tgt_x10);
unsigned char far hc_x_boost_off(void);
void          far hc_x_boost_ilim(long *integ100);
/* throttle (hc_dbw.c, hcetbcal.c) */
unsigned int  far hc_x_dbw_want(unsigned int want_x10);
unsigned int  far hc_x_dbw_slew(unsigned int prev_x10, unsigned int next_x10,
                                unsigned int step_ms);
unsigned int  far hc_x_dbw_gain(unsigned int pos_x10);   /* percent        */
unsigned char far hc_x_etbcal_check(unsigned int t1c, unsigned int t1o,
                                    unsigned int t2c, unsigned int t2o);
/* knock (hcknock711.c) */
unsigned char far hc_x_knock_q(unsigned char level16, unsigned int rpm);
void          far hc_x_knock_learn(unsigned char q, unsigned char ncyl);

unsigned char far hc_x_cut_why(void);
unsigned char far hc_x_limp_why(void);

#endif
