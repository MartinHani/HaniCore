/* Bosch ME7.1.1 crank/cam acquisition, and a GENERIC engine position.
 *
 * WHAT IS BOARD-SPECIFIC HERE AND WHAT IS NOT.
 *
 * Board: KWDG=P2.15/CC15/trap 1F, NWDG1=P2.8/CC8/trap 18, NWDG2=P2.9/CC9/trap
 * 19, all three capturing into T1 at fCPU/32 = 1.25 MHz. Those are the only
 * facts in this file that belong to the Porsche ME7.1.1.
 *
 * Everything else - how many teeth the wheel has, how many are missing, which
 * edge is captured, how long an interval has to be before it is a gap, how
 * many good teeth buy sync, where the cam references are and whether they can
 * resolve the 720 degree cycle at all - IS CONFIGURATION, and it is read from
 * the calibration page.
 *
 * THAT IS NEW AT V55 AND IT IS THE POINT OF V55.
 *
 * Up to V54 this file held:
 *
 *     #define ME711_TEETH      60
 *     #define ME711_REAL_TEETH 58
 *     #define ME711_MIN_GOOD   30
 *     static const unsigned int ref[4] = {1220u, 3020u, 4820u, 6620u};
 *
 * - a 60-2 wheel and the Porsche V8's four cam references, compiled in, with
 * the gap ratio fixed at 2.0 and the capture hardware wired for falling edges
 * only. `syTeeth`, `syGap`, `trigEdge`, `trigGapRatio` and `trigMinTeeth` were
 * all in the page, all in the .ini, and all validated per decoder by
 * hc_validation.c - and NOTHING READ THEM. tools/me711_trigger_test.py even
 * wrote syTeeth and syGap into hc_cfg before every run, so the suite was green
 * about genericity it never exercised. A 36-1 wheel could not have been
 * decoded at all: its gap interval is exactly 2.0 tooth periods and the fixed
 * rule needs STRICTLY more than 2.0.
 *
 * THE OEM DECOMPOSITION IS KEPT. The three-interval rule below is still the
 * one recovered from OEM ME7.1.1 machine code at 85:8766 - a long interval is
 * a candidate, and it only becomes the reference when the FOLLOWING interval
 * confirms it, because two preceding intervals cannot reject an isolated
 * deceleration. The counters are still Bosch's %REVCALC names, and a
 * correction is still separated from a loss. What changed is that the ratio
 * the comparison uses, and the geometry the position is derived from, come
 * from the page instead of from three #defines.
 *
 * ONE DELIBERATE DEPARTURE FROM THE OEM MACHINE CODE, and it is recorded
 * rather than hidden. The OEM compares `(candidate >> 1) > neighbour`, which
 * is a fixed 2.0 ratio expressed as a shift; on an ODD candidate count that
 * differs from `candidate * 10 > 20 * neighbour` by one timer tick, 0.8 us at
 * 1.25 MHz. A real 60-2 gap is three tooth periods against one, so no gap
 * decision on any engine can turn on that tick. The ratio form is what lets
 * the same code decode a 36-1, and that is worth more than bit-exactness with
 * a wheel this ECU is not obliged to run.
 *
 * No ISR here divides, logs, transmits or calls an output driver.
 */
#include <reg167.h>
#include "hctarget.h"
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hc_config_manager.h"
#include "hchal.h"
#include "hctrigger.h"
#include "hcsched_dry.h"
#include "hctrig_angle_ref_me711.h"
#include "hccam.h"
#include "hcknock711.h"
#include "hcvvt711.h"
#include <intrins.h>

#define TRG_MAX_CAM_REFS   8u

/* THE PATTERN METHOD DECIDES IN THE MAIN LOOP, NOT IN THE ISR.
 *
 * The cam capture ISR only records, per bank, the angle of the last crank
 * tooth, the T1 time from that tooth to the cam capture and the tooth
 * period, into a 4-entry ring; trg_service() interpolates the angle (long
 * arithmetic, legal in this near module), hands it to the far pattern core
 * (engine/hccam.c, host-tested) and applies LOSE / FLIP / GRANT with the
 * capture interrupts held off. A FLIP moves the engine's half, so every edge
 * already in a ring carries the flip epoch it was captured in. */
#define CAMQ 4u
static unsigned int  camq_ang[2][CAMQ], camq_dt[2][CAMQ];
static int           camq_since[2][CAMQ];     /* signed: < 0 = captured before
                                                 the tooth the angle belongs to */
static unsigned char camq_ep[2][CAMQ];
static unsigned char camq_w[2], camq_r[2];   /* written by the ISR / the task */
static unsigned char cam_epoch;              /* bumped by every PATTERN flip  */
static unsigned char g_pat_ok[2];            /* hccam_init took the pattern   */
static unsigned char g_pat_decides[2];       /* this bank may move the cycle  */
static unsigned int  pat_seen_lost;          /* trg_synclost at the last drain */
typedef char hc_campat_numbers_are_hccam_p[
    (HC_CAMPAT_QUICKSTART == HCCAM_P_QUICKSTART
     && HC_CAMPAT_MIATA_NB == HCCAM_P_MIATA_NB
     && HC_CAMPAT_EQUAL == HCCAM_P_EQUAL) ? 1 : -1];
/* hc_config_manager.c's critical section: ILVL 13, above every capture
   source, below the PEC levels - never IEN (it would stop the S5500). */
#include "hcatomic.h"
#define TRG_IRQ_SAVE(v)    HC_ATOMIC_ENTER(v)   /* the one convention */
#define TRG_IRQ_RESTORE(v) HC_ATOMIC_EXIT(v)

unsigned char trg_state;
unsigned int trg_rpm, trg_tooth, trg_teeth_seen, trg_gaps;
unsigned int trg_synccorr, trg_synclost, trg_last_dt, trg_tooth_dt;
unsigned int trg_cam_edges, trg_cam_tooth, trg_rev, trg_toolow;
unsigned int trg_isr_ticks, trg_isr_max, trg_isr_headroom;
unsigned char trg_phase;
unsigned int trg_phsok_c, trg_phase_corr, trg_phase_lost, trg_sim_rpm;
unsigned int trg_loss_reason, trg_noise_edges, trg_gap_metric_x10;
unsigned int trg_gap_detected, trg_engine_deg_x10, trg_stall_state;
unsigned int trg_gap_pending;
/* reference marks accepted with a +/-1 tooth correction (Bosch
   Zahnkorrektur) instead of a sync loss. Also counted in trg_synccorr. */
unsigned int trg_tooth_corr;
unsigned long trg_crank_period;
/* The live-Burn scheduler uses this with T1 and the last validated tooth
   period to calculate an actual remaining crank horizon. */
unsigned int trg_last_edge_t1;
unsigned int trg_cam1_edges, trg_cam2_edges, trg_cam1_tooth, trg_cam2_tooth;
unsigned int trg_cam1_window, trg_cam2_window, trg_cam_error;
unsigned int trg_cam_loss_reason, trg_cam1_raw, trg_cam2_raw;
unsigned int trg_cam1_angle, trg_cam2_angle;
/* THE CYCLE, SEPARATED FROM THE CRANK.
 *
 *   trg_synclost      the CRANK position was withdrawn (unchanged meaning)
 *   trg_tooth_corr    a reference mark was accepted with a +/-1 correction
 *   trg_phase_corr    the cam moved the guessed half (no position was lost)
 *   trg_cycle_acq     the cycle became KNOWN (TRG_SYNC_CRANK -> FULL)
 *   trg_cycle_lost    the cycle was withdrawn (FULL -> CRANK) - the crank
 *                     position is kept; a cam can never take it away
 *   trg_ph_noalt      level checks that did NOT alternate (Bosch B_siph)
 *
 * trg_ph_status: bit 0 last sampled level, bit 1 it matched the half the
 * decoder believed, bit 2 the level alternated from the previous
 * revolution, bit 3 a check has been made since sync, bits 8..15 the run of
 * consistent checks. Published so a crank-only engine still shows what the
 * cam WOULD decide. */
unsigned int trg_cycle_acq, trg_cycle_lost, trg_ph_noalt, trg_ph_status;
/* in the LEVEL method both cam edges are captured; these are the last
   measured widths of the pin-LOW and pin-HIGH sectors, 0.1 crank degree,
   quantised to the tooth the angle was last published at. On the Bosch
   quick-start wheel one of the two alternates wide/narrow (140/40). */
unsigned int trg_cam_lo_w_x10, trg_cam_hi_w_x10;

/* WHAT THE DECODER BELIEVES IT IS DECODING, published so a bench can tell a
   wrong signal from a wrong configuration. Every physical trigger session
   before this one would have had to infer the firmware's geometry from its
   behaviour, because the geometry was three #defines in this file. */
/* THESE ARE THE WORKING VARIABLES, not copies of them. Publishing a mirror of
   a static the decoder already keeps costs near RAM twice, and near RAM is the
   scarcest resource on this board: 0x00F700-0x00FDFF less the PEC pointer file
   is 1728 bytes for the whole application, and near_ram_hazard_proof measures
   what is left. So the decoder reads and writes exactly the words the output
   channels publish. */
unsigned int trg_cfg_teeth;         /* N: teeth on a COMPLETE wheel          */
unsigned int trg_cfg_gap;           /* M: missing teeth                      */
unsigned int trg_cfg_ratio_x10;     /* gap detection ratio in force, x10     */
unsigned int trg_cfg_min_teeth;     /* good teeth before sync is granted     */
unsigned int trg_cfg_tooth_x10;     /* one tooth, 0.1 crank degrees          */
int trg_cfg_angle_x10;             /* trigAngleX10 in force, -179.9..180 */
unsigned int trg_cfg_cam_refs;      /* references per 720 degrees            */
unsigned int trg_cfg_cam_ref_x10;
unsigned int trg_cfg_cam_window_x10;
unsigned int trg_cfg_crank_edge;    /* 0 falling, 1 rising                   */
unsigned int trg_cfg_cam_edge;
/* 1 = the configured cam geometry can decide WHICH revolution this is. An
   even number of equally spaced references never can: the pattern is
   invariant under a 360 degree shift. */
unsigned int trg_cam_resolves;
/* Bumped every time the geometry below is re-read from the page, so a bench
   can prove a configuration change actually reached the decoder. */
unsigned int trg_cfg_generation;
unsigned int trg_cfg_capture_map;

/* ---- the geometry, resolved once in task context ------------------------
   None of this is read inside an interrupt: the universal block lives in the
   external SRAM and a far read per tooth is not something a capture ISR does. */
#define g_teeth       trg_cfg_teeth
#define g_gap         trg_cfg_gap
#define g_ratio_x10   trg_cfg_ratio_x10
#define g_min_teeth   trg_cfg_min_teeth
#define g_cam_refs    trg_cfg_cam_refs
#define g_cam_win_x10 trg_cfg_cam_window_x10
#define g_cam_resolves trg_cam_resolves

static unsigned int g_real;         /* N - M: teeth that physically exist    */
static unsigned int g_ang_num;      /* (3600*128 + N/2) / N - see slot_angle */
static int          g_offset_x10;   /* reference offset, 0.1 crank degrees   */
static unsigned int g_cam_ref[TRG_MAX_CAM_REFS];
static unsigned int g_cam_on;       /* the cam captures are armed at all     */
static unsigned int g_sync_bank;    /* 0 none, 1 cam1, 2 cam2, 3 either      */
/* Which cam banks the CONFIGURATION says this engine has, as the bits
   trg_cam_error uses for them: 4 = bank 1, 8 = bank 2. Derived once, so
   the service path is one AND instead of four comparisons. */
static unsigned int g_cam_expect;
static unsigned int g_crank_ccm;    /* CCMOD nibble for the crank capture    */
static unsigned int g_cam_ccm;      /* CCMOD nibble for both cam captures    */
static unsigned long g_sig;         /* geometry signature, for change detect */
/* the LEVEL cam-phase method, resolved in task context. */
#define CAMPH_REFS   0u
#define CAMPH_LEVEL  1u
#define CAMPH_PATTERN 2u             /* engine/hccam.c                   */
static unsigned char g_cam_mode;     /* CAMPH_*                               */
static unsigned char g_ph_level;     /* expected pin level at g_ph_angle      */
static unsigned char g_ph_confirm;   /* consistent checks before FULL         */
static unsigned char g_ph_decides;   /* the sync mode lets the cam decide     */
static unsigned int  g_ph_slot;      /* crank slot sampled, 0xFFFF = none     */
static unsigned int  g_ph_mask;      /* P2 bit of the cam that is sampled     */
static unsigned int  g_ph_angle;     /* engine angle of the check, 0..7199    */
static unsigned int  g_cam1_mask, g_cam2_mask;  /* P2 bits of the cam roles   */

/* ================= WHICH CAVITY OWNS WHICH CAPTURE CHANNEL, AND ITS JOB ====
 *
 * Until V62 this file armed CC15 as the crank and CC8/CC9 as the cams, always,
 * while `pinCrank`, `pinCam1` and `pinCam2` were validated by hc_validation.c
 * and then read by nothing. `pinCrank = 86` validated and the firmware went on
 * capturing cavity 82.
 *
 * Now the PAGE decides. hc_hal_capture_channel() turns each configured cavity
 * into one of this board's three capture channels, and g_role[] records what
 * that channel is for. The ISRs dispatch on it.
 *
 * THE DEFAULT RESOLUTION IS BIT-IDENTICAL TO WHAT THIS FILE ALWAYS DID.
 * The board default is pinCrank 82 -> CC15, pinCam1 86 -> CC8, pinCam2 87 ->
 * CC9, so a Porsche page arms exactly the channels, in exactly the modes, that
 * the physically proven V55..V61 images armed. That is deliberate: the VR
 * crank path is the one piece of engine input this project has actually
 * measured, and a routing rewrite is not allowed to move it. */
#define ROLE_NONE  0u
#define ROLE_CRANK 1u
#define ROLE_CAM1  2u
#define ROLE_CAM2  3u
static unsigned char g_role[TGT_CAPCH_COUNT];

/* The CCMOD nibble each channel must be programmed with, by role. */
static unsigned int role_ccm(unsigned char role)
{
    return (role == ROLE_CRANK) ? g_crank_ccm : g_cam_ccm;
}

/* The interrupt-control word a role runs at. THE PAIR FOLLOWS THE ROLE, not
   the channel - see TGT_GLVL_CAM1 in hctarget.h for why, and what breaks when
   it does not. Three distinct pairs, one channel per role, so no two enabled
   capture sources can share an (ILVL, GLVL) whatever the page routes. */
static unsigned int role_ic(unsigned char role)
{
    if (role == ROLE_CRANK) {
        return HC_IC(TGT_ILVL_CRANK, TGT_GLVL_CRANK);
    }
    if (role == ROLE_CAM1) {
        return HC_IC(TGT_ILVL_CAM, TGT_GLVL_CAM1);
    }
    return HC_IC(TGT_ILVL_CAM, TGT_GLVL_CAM2);
}

/* Resolve the three configured cavities onto this board's capture channels.
   Task context only, called from geometry_read(). */
static void roles_resolve(void)
{
    unsigned char i, ch;

    for (i = 0u; i < (unsigned char)TGT_CAPCH_COUNT; i++) {
        g_role[i] = ROLE_NONE;
    }
    ch = hc_hal_capture_channel(hc_cal_u8(CFG_U_PIN_CRANK));
    if (ch < (unsigned char)TGT_CAPCH_COUNT) g_role[ch] = ROLE_CRANK;
    if (g_cam_on) {
        ch = hc_hal_capture_channel(hc_cal_u8(CFG_U_PIN_CAM1));
        if (ch < (unsigned char)TGT_CAPCH_COUNT && g_role[ch] == ROLE_NONE) {
            g_role[ch] = ROLE_CAM1;
        }
        /* cam 2 only when used (hc_validation.c cam2_used) */
        i = hc_cal_u8(CFG_U_SYNC_MODE);
        if (i == HC_SYNC_CAM2_CYCLE || i == HC_SYNC_DUAL_CAM
            || (hc_cal_u8(CFG_U_CAM_PHASE_MODE) == 2u
                && hc_cal_u8(CFG_U_CAM2_PATTERN) != 0u)
            || hc_cal_u8((unsigned int)(CFG_U_VVT_MODE + 1u)) != 0u) {
            ch = hc_hal_capture_channel(hc_cal_u8(CFG_U_PIN_CAM2));
            if (ch < (unsigned char)TGT_CAPCH_COUNT && g_role[ch] == ROLE_NONE) {
                g_role[ch] = ROLE_CAM2;
            }
        }
    }
}

static unsigned int have_edge, last_t, prev1, prev2, good_teeth;
static unsigned int gap_pending_expected, gap_pending_count, slot;
/* 1 while the last reference mark was a +/-1 tooth correction. A
   second one in a row is a loss. */
static unsigned char corr_run;
/* A withdrawn position waiting to be COUNTED (trg_synclost): counted only
   once the crank has delivered more than one revolution of edges after it.
   A stall first means it was the engine stopping (see lose_sync()). */
static unsigned char loss_pend;
static unsigned int loss_mark;
static unsigned int disagreements, stall_mark, stall_t;
static unsigned long stall_ticks, stall_limit, rev_ticks;
static unsigned int min_edge_ticks, metric_num, metric_den, source_live;
static unsigned int cam1_last_rev, cam2_last_rev, seen_active_rev;
static unsigned char ph_last, ph_have_last;     /* V92 LEVEL method           */
static unsigned int  cam_last_fall, cam_last_rise; /* 0xFFFF = none yet       */

/* THE ONE CONVERSION from the tuner's physical reference to the
 * decoder's internal rotation. trigAngleX10 is where tooth #1 (the selected
 * edge that ENDS the missing-tooth gap - physical 0 below) sits, in 0.1 crank
 * degrees AFTER cylinder-1 TDC, signed (Speeduino's "trigger angle"; rusEFI's
 * globalTriggerAngleOffset is minus it). Engine angle = physical + rotation,
 * so the rotation is that angle modulo 360 - the SAME number the V96 page
 * called trigOffsetX10 (358.0 there is -2.0 here). Everything downstream -
 * the TDC table, spark and injection angles, cam references, knock windows -
 * is in engine degrees after cylinder-1 TDC and never sees this value.
 * It takes the STORED WORD (the s16's two's-complement bits) and decodes
 * the sign itself: C89 leaves % of a negative number implementation-defined,
 * and a host compiler's 32-bit int would read 0xFFEC as +65516. The
 * validator refuses anything outside -359.9..+359.9 (hc_validation.c). */
unsigned int hc_trig_rotation_x10(unsigned int stored)
{
    unsigned int n;

    stored &= 0xFFFFu;
    if (stored < 0x8000u) {
        return stored % 3600u;
    }
    n = ((0u - stored) & 0xFFFFu) % 3600u;      /* |angle| mod 360 */
    return n ? (unsigned int)(3600u - n) : 0u;
}

unsigned int trg_engine_angle_x10(unsigned int physical_angle_x10,
                                  unsigned char phase,
                                  int reference_offset_x10)
{
    int rotated;

    while (physical_angle_x10 >= 3600u) physical_angle_x10 -= 3600u;
    rotated = (int)physical_angle_x10 + reference_offset_x10;
    if (rotated >= 3600) rotated -= 3600;
    else if (rotated < 0) rotated += 3600;
    return (unsigned int)(rotated + ((phase & 1u) ? 3600 : 0));
}

/* The angle of an angular SLOT, 0..N-1, in 0.1 crank degrees.
 *
 * 3600/N is not an integer for every wheel, so the divide is done ONCE, in
 * task context, scaled by 128, and the per-tooth cost is a 16x16 multiply and
 * a shift. For every wheel whose tooth count divides 3600 - 60, 48, 40, 36,
 * 30, 24, 20, 18, 15, 12 and the rest - the result is EXACT: 60 teeth gives
 * g_ang_num 7680 and slot*7680>>7 is slot*60 with no error at all. For a
 * wheel that does not divide, the rounding error stays under a fifth of one
 * of its own teeth at the far end of a 200 tooth wheel. */
static unsigned int slot_angle_x10(unsigned int s)
{
    return (unsigned int)((((unsigned long)s * g_ang_num) + 64uL) >> 7);
}

/* THE HALF FLIPS WHERE THE ROTATED ANGLE WRAPS, NOT AT THE GAP.
 *
 * trg_engine_angle_x10() rotates the physical angle by the reference offset
 * inside one revolution and adds the half. Until V90 trg_phase flipped at the
 * gap - physical 0 - so with any offset other than 0 the published angle
 * jumped by 360 degrees twice a revolution: once at the gap (half flipped,
 * rotation had not wrapped) and once where the rotation wrapped (half had
 * not). The scheduler saw both as discontinuities. With the AWT's measured-
 * later offset (rusEFI VAG 60-2: TDC ~92 degrees after the gap) that is every
 * revolution. Flipping on the wrap of the ROTATED angle keeps the engine
 * angle continuous for every offset, and for offset 0 the wrap IS the gap, so
 * nothing changes there. The cam's phase correction in cam_edge() is
 * unaffected: it moves the half, not the rotation. */
static unsigned int last_rot;
static unsigned char rot_valid;

static void publish_angle(void)
{
    unsigned int rot = trg_engine_angle_x10(slot_angle_x10(slot), 0u,
                                            g_offset_x10);

    if (rot_valid && rot < last_rot) {
        trg_phase ^= 1u;
    }
    last_rot = rot;
    rot_valid = 1u;
    trg_engine_deg_x10 = (unsigned int)(rot + (trg_phase ? 3600u : 0u));
}

static void slot_advance(void)
{
    slot++;
    if (slot >= g_teeth) slot = 0u;
}

/* cand is longer than neighbour by at least the configured ratio.
   Both products are 16x16 widening multiplies; nothing here divides. */
static unsigned int longer(unsigned int cand, unsigned int neighbour)
{
    return (unsigned int)(((unsigned long)cand * 10u)
                          > ((unsigned long)neighbour * g_ratio_x10));
}

/* A STALL IS NOT A SYNC LOSS, and until V77 it was counted as one.
 *
 * Measured on the bench ECU, V76, 2026-09-25: syncLossCount went up by
 * exactly one at every `signal stop`, always with syncLossReason 1 (STALL),
 * and never at 150, 1000, 3000 or 6000 rpm while the wheel turned. So every
 * increment a tuner would ever see was a key-off or a stall, and a real loss
 * - an early or missing gap, a cam out of its window - was indistinguishable
 * from switching the engine off. The engine stopping is still reported,
 * exactly as before, by syncLossReason 1 and stallState; the counter now
 * means only "the decoder withdrew a position it had".
 *
 * NOR IS THE LAST REVOLUTION OF A STOPPING ENGINE (2026-10-11). On the AWT
 * (2026-10-10, both car sessions) every key-off and every cranking stop
 * ended with syncLossReason 2: the crank slows at a compression TDC and
 * speeds up after it, which is a long interval between two shorter ones -
 * a gap, out of position - so P0335 and the MIL came on at every stop. The
 * position is still withdrawn AT ONCE (the scheduler is cancelled here, as
 * before); only the COUNT waits until the crank has delivered more than one
 * revolution of edges after the loss (crank_edge()). An engine that is
 * stopping never does - the stall comes first and drops the pending count -
 * while a real gap error on a turning engine is counted one revolution
 * later (20 ms at 3000 rpm). */
static void lose_sync(unsigned int reason)
{
    if (reason == TRG_LOSS_STALL) {
        loss_pend = 0u;
    } else if (trg_state >= TRG_SYNC_CRANK && !loss_pend) {
        loss_pend = 1u;
        loss_mark = trg_teeth_seen;
    }
    trg_state = TRG_COUNTING;
    trg_loss_reason = reason;
    trg_stall_state = (unsigned int)(reason == TRG_LOSS_STALL);
    trg_phsok_c = 0;
    if (trg_phase_lost != 0xFFFFu) trg_phase_lost++;
    good_teeth = 0;
    disagreements = 0;
    corr_run = 0u;
    ph_have_last = 0u;
    trg_ph_status = 0u;
    hc_drysched_cancel(reason);
}

static void trigger_hw(unsigned int on)
{
    if (on) {
        /* Claim T1/CCM only when real capture is explicitly selected. V27
           started T1 and programmed CC8/9/15 even with triggerSource=off,
           the only live peripheral delta from the physically stable V26.

           AND THE CAM CAPTURES ARE ONLY ARMED WHEN A CAM IS CONFIGURED. With
           no sensor connected a floating input generates captures; that is
           the measured reason CFG_TRIG_SOURCE exists at all, and it applies
           to NWDG1/NWDG2 exactly as it applies to KWDG. Until V55 both cam
           channels were armed unconditionally whenever the crank was. */
        CC15IC = 0; CC8IC = 0; CC9IC = 0;
        T1 = 0;
        T01CON = (unsigned int)((T01CON & 0x00FFu) | TGT_T1CON_RUNNING);
        /* EACH CHANNEL IS ARMED FOR THE ROLE ITS CONFIGURED CAVITY GAVE IT,
           and a channel no cavity claimed is left disarmed with its CCMOD
           cleared. Bit 3 of each nibble selects T1; the low three bits are
           CCMOD - 010 latches on a negative transition, 001 on a positive one.
           A channel's EDGE now comes from its ROLE, so a crank moved onto CC8
           gets the crank edge setting and not the cam's.

           An unconnected input makes its own edges - that is the measured
           reason CFG_TRIG_SOURCE exists - so a disarmed channel really must be
           disarmed, not merely ignored in the ISR. */
        CCM3 = (unsigned int)(CCM3 & 0x0FFFu);
        CCM2 = (unsigned int)(CCM2 & 0xFF00u);
        if (g_role[TGT_CAPCH_CC15] != ROLE_NONE) {
            CCM3 = (unsigned int)((CCM3 & 0x0FFFu)
                                  | (role_ccm(g_role[TGT_CAPCH_CC15]) << 12));
            CC15IC = role_ic(g_role[TGT_CAPCH_CC15]);
        }
        if (g_role[TGT_CAPCH_CC8] != ROLE_NONE) {
            CCM2 = (unsigned int)(CCM2 | role_ccm(g_role[TGT_CAPCH_CC8]));
            CC8IC = role_ic(g_role[TGT_CAPCH_CC8]);
        }
        if (g_role[TGT_CAPCH_CC9] != ROLE_NONE) {
            CCM2 = (unsigned int)(CCM2
                                  | (role_ccm(g_role[TGT_CAPCH_CC9]) << 4));
            CC9IC = role_ic(g_role[TGT_CAPCH_CC9]);
        }
        hc_hal_trig_arm();
    } else {
        CC15IC = 0; CC8IC = 0; CC9IC = 0;
        CCM3 = (unsigned int)(CCM3 & 0x0FFFu);
        CCM2 = (unsigned int)(CCM2 & 0xFF00u);
        T01CON = (unsigned int)(T01CON & 0x00FFu);
        hc_hal_trig_disarm();
    }
    source_live = on;
}

/* Read the wheel, the edges and the cam out of the page and derive everything
   the interrupt path needs. Task context only. Returns a signature so the
   caller can tell whether anything actually moved.

   EVERY CLAMP HERE IS A FALLBACK, NOT A VALIDATION. hc_validation.c is what
   tells a tuner their page is wrong, per decoder, with the offending offset;
   this only guarantees that whatever is in the page cannot make the decoder
   divide by zero or index past g_cam_ref. A page that fails validation cannot
   arm an output in the first place. */
static unsigned long geometry_read(void)
{
    unsigned int max_rpm, i, r, space, mode;
    unsigned long sig;

    g_teeth = cfg_u16(CFG_SY_TEETH);
    if (g_teeth < 4u || g_teeth > 200u) g_teeth = 60u;
    g_gap = cfg_u8(CFG_SY_GAP);
    if (g_gap == 0u || g_gap + 3u > g_teeth) g_gap = 2u;
    g_real = (unsigned int)(g_teeth - g_gap);

    /* A ratio the tuner has not set, or one that cannot work on this wheel,
       is derived from the geometry rather than guessed: the gap interval is
       (M+1) tooth periods and an ordinary one is 1, so the midpoint between
       them leaves the most margin on either side. For a 60-2 that is exactly
       the OEM's 2.0; for a 36-1 it is 1.5, and the fixed 2.0 this file used
       to carry could never have seen that gap at all. */
    g_ratio_x10 = cfg_u16(CFG_TRIG_GAP_RATIO_X10);
    /* The upper bound is STRICT, and the strictness matters. The real gap is
       exactly (M+1) tooth periods, and the comparison needs the candidate to
       be MORE than ratio times its neighbour - so a ratio of exactly (M+1)
       can never fire, and a tuner who types 3.0 on a 60-2 would get a decoder
       that silently never syncs. Out of range means the geometry decides. */
    if (g_ratio_x10 < 12u || g_ratio_x10 >= (unsigned int)((g_gap + 1u) * 10u))
        g_ratio_x10 = (unsigned int)((g_gap + 2u) * 5u);

    g_min_teeth = cfg_u8(CFG_TRIG_MIN_TEETH);
    if (g_min_teeth < 2u) g_min_teeth = 2u;
    if (g_min_teeth > g_real) g_min_teeth = g_real;

    g_ang_num = (unsigned int)(((3600uL * 128uL) + (unsigned long)(g_teeth / 2u))
                               / (unsigned long)g_teeth);

    g_offset_x10 = (int)hc_trig_rotation_x10(hc_cal_u16(CFG_U_TRIG_ANGLE_X10));

    /* 0 = falling, 1 = rising. Bit 3 of the nibble keeps T1 as the source. */
    g_crank_ccm = (unsigned int)(cfg_u8(CFG_TRIG_EDGE) ? 0x9u : 0xAu);
    g_cam_ccm = (unsigned int)(cfg_u8(CFG_CAM_EDGE) ? 0x9u : 0xAu);
    g_cam_on = (unsigned int)(cfg_u8(CFG_CAM_ENABLE) != 0u);

    g_cam_refs = hc_cal_u8(CFG_U_CAM_REFS);
    if (g_cam_refs > TRG_MAX_CAM_REFS) g_cam_refs = TRG_MAX_CAM_REFS;
    g_cam_win_x10 = hc_cal_u16(CFG_U_CAM_WINDOW_X10);
    if (g_cam_win_x10 < 10u || g_cam_win_x10 > 1800u) g_cam_win_x10 = 300u;
    r = hc_cal_u16(CFG_U_CAM_REF_X10);
    if (r >= 7200u) r = 0u;
    space = g_cam_refs ? (unsigned int)(7200u / g_cam_refs) : 7200u;
    for (i = 0u; i < TRG_MAX_CAM_REFS; i++) {
        if (i < g_cam_refs) {
            unsigned int v = (unsigned int)(r + i * space);
            while (v >= 7200u) v -= 7200u;
            g_cam_ref[i] = v;
        } else {
            g_cam_ref[i] = 0xFFFFu;
        }
    }

    /* Which input is allowed to decide the cycle. A cam that is only there to
       be watched must never rotate the engine's idea of where it is. */
    mode = hc_cal_u8(CFG_U_SYNC_MODE);
    if (!g_cam_on || g_cam_refs == 0u) g_sync_bank = 0u;
    else if (mode == HC_SYNC_CAM1_CYCLE) g_sync_bank = 1u;
    else if (mode == HC_SYNC_CAM2_CYCLE) g_sync_bank = 2u;
    else if (mode == HC_SYNC_DUAL_CAM) g_sync_bank = 3u;
    else g_sync_bank = 0u;

    /* AN EVEN NUMBER OF EQUALLY SPACED REFERENCES PROVES NOTHING ABOUT WHICH
       REVOLUTION THIS IS. Shift the set by 360 degrees and it maps onto
       itself, so a match is equally consistent with either half of the cycle.
       The Porsche V8 donor's four references are exactly that case, and V54
       was right to refuse to claim cycle sync from them - it just said so in
       a comment instead of in a value anyone could read. An ODD count, and in
       particular the ordinary single-window Hall cam the first 1.8T will
       arrive with, is unambiguous. */
    /* the LEVEL method resolves the cycle with ANY reference count:
       it never looks at camRefs. The mode byte is clamped, not validated -
       hc_validation.c is what tells the tuner. */
    g_cam_mode = hc_cal_u8(CFG_U_CAM_PHASE_MODE);
    if (g_cam_mode != CAMPH_LEVEL && g_cam_mode != CAMPH_PATTERN) {
        g_cam_mode = CAMPH_REFS;
    }
    if (g_cam_mode != CAMPH_REFS && g_cam_on && !g_sync_bank
        && (mode == HC_SYNC_CAM1_CYCLE || mode == HC_SYNC_CAM2_CYCLE
            || mode == HC_SYNC_DUAL_CAM)) {
        /* A cycle mode whose refs count is 0 cleared the bank above; the
           LEVEL method does not need refs, so the bank comes back. */
        g_sync_bank = (mode == HC_SYNC_CAM2_CYCLE) ? 2u
                    : (mode == HC_SYNC_DUAL_CAM) ? 3u : 1u;
    }
    if (g_cam_mode == CAMPH_LEVEL) {
        g_cam_resolves = (unsigned int)(g_sync_bank != 0u);
        /* Both edges: the sector widths are the evidence that the wheel is
           the one configured (CCMOD 011 = either transition, bit 3 = T1). */
        g_cam_ccm = 0xBu;
    } else if (g_cam_mode == CAMPH_PATTERN) {
        /* each cam's wheel from the library; the cycle is claimed only
           through a bank the sync mode names AND whose pattern resolves the
           half across the configured VVT authority (camWindowX10). */
        static hccam_cfg_t pc;          /* static: the user stack is 256 bytes */
        unsigned char b, conf = hc_cal_u8(CFG_U_CAM_PHASE_CONFIRM);
        g_cam_resolves = 0u;
        for (b = 0u; b < 2u; b++) {
            pc.pattern = hc_cal_u8(b ? CFG_U_CAM2_PATTERN : CFG_U_CAM1_PATTERN);
            pc.equal_n = (unsigned char)g_cam_refs;
            pc.offset_x10 = hc_cal_u16(b ? CFG_U_CAM2_REF_X10 : CFG_U_CAM_REF_X10);
            if (pc.offset_x10 >= 7200u) pc.offset_x10 = 0u;
            pc.tol_x10 = (unsigned int)(hc_cal_u8(CFG_U_CAM_TOOTH_TOL) * 10u);
            pc.auth_x10 = g_cam_win_x10;
            pc.confirm = (unsigned char)((conf < 1u) ? 1u : (conf > 8u) ? 8u : conf);
            pc.errlimit = 3u;
            g_pat_ok[b] = hccam_init(&hccam_bank[b], &pc);
            g_pat_decides[b] = (unsigned char)(g_pat_ok[b]
                && hccam_bank[b].resolves
                && (g_sync_bank == 3u || g_sync_bank == (unsigned int)(b + 1u)));
            if (g_pat_decides[b]) g_cam_resolves = 1u;
            camq_r[b] = camq_w[b];
        }
    } else {
        g_cam_resolves = (unsigned int)(g_sync_bank != 0u && (g_cam_refs & 1u));
    }
    g_ph_decides = (unsigned char)(g_cam_resolves != 0u);
    g_ph_level = (unsigned char)(hc_cal_u8(CFG_U_CAM_PHASE_LEVEL) ? 1u : 0u);
    g_ph_confirm = hc_cal_u8(CFG_U_CAM_PHASE_CONFIRM);
    if (g_ph_confirm < 1u) g_ph_confirm = 1u;
    if (g_ph_confirm > 8u) g_ph_confirm = 8u;
    g_ph_angle = hc_cal_u16(CFG_U_CAM_PHASE_ANGLE_X10);
    if (g_ph_angle >= 7200u) g_ph_angle = 0u;
    g_cam_expect = 0u;
    if (g_sync_bank == 1u || g_sync_bank == 3u) g_cam_expect |= 4u;
    if (g_sync_bank == 2u || g_sync_bank == 3u) g_cam_expect |= 8u;

    max_rpm = cfg_u16(CFG_REV_MAX);
    if (max_rpm < 1000u) max_rpm = 7500u;
    /* One whole tooth period at the declared ceiling. An edge closer than
       that to the last VALID one cannot be a tooth of this wheel. 75e6 is
       1.25 MHz x 60 s, so this is ticks-per-tooth at max_rpm - the same
       number V54 computed, except that it now follows the configured tooth
       count instead of assuming sixty of them. */
    min_edge_ticks = (unsigned int)(75000000uL
                                    / ((unsigned long)g_teeth
                                       * (unsigned long)max_rpm));
    if (min_edge_ticks < 40u) min_edge_ticks = 40u;

    stall_limit = (unsigned long)cfg_u8(CFG_TRIG_TIMEOUT_MS)
                * (TGT_TICKS_PER_MS_X10 / 10uL);
    if (stall_limit < 62500uL) stall_limit = 250000uL;

    trg_cfg_tooth_x10 = slot_angle_x10(1u);
    trg_cfg_angle_x10 = (g_offset_x10 > 1800) ? (int)(g_offset_x10 - 3600)
                                              : g_offset_x10;
    trg_cfg_cam_ref_x10 = g_cam_refs ? g_cam_ref[0] : 0xFFFFu;
    trg_cfg_crank_edge = (unsigned int)(g_crank_ccm == 0x9u);
    trg_cfg_cam_edge = (unsigned int)(g_cam_ccm == 0x9u);
    /* RESOLVE FIRST, THEN PUBLISH. This assignment used to sit above the
       roles_resolve() call down in the signature block, so it published a
       g_role[] that had not been filled in yet and trigCfgCaptureMap read
       0x0000 on every boot - which looks exactly like "nothing is routed". */
    roles_resolve();

    /* the P2 bit of each cam role, and the crank SLOT at which the
       LEVEL method samples. The slot is the nearest DELIVERED tooth
       (1 .. N-M-1; the edge that ends the gap is only a candidate and is
       published one tooth short) to the configured engine angle, through
       the same offset publish_angle() applies. None of this runs in the
       ISR. */
    {
        unsigned int ch, rot, phys, s, tx;

        g_cam1_mask = 0u; g_cam2_mask = 0u;
        for (ch = 0u; ch < TGT_CAPCH_COUNT; ch++) {
            unsigned int m = (ch == TGT_CAPCH_CC15) ? 0x8000u
                           : (ch == TGT_CAPCH_CC8) ? 0x0100u : 0x0200u;
            if (g_role[ch] == ROLE_CAM1) g_cam1_mask = m;
            if (g_role[ch] == ROLE_CAM2) g_cam2_mask = m;
        }
        g_ph_mask = (g_sync_bank == 2u) ? g_cam2_mask : g_cam1_mask;
        g_ph_slot = 0xFFFFu;
        tx = slot_angle_x10(1u);
        if (g_cam_mode == CAMPH_LEVEL && g_cam_on && g_ph_mask && tx) {
            rot = (unsigned int)(g_ph_angle % 3600u);
            phys = (rot >= (unsigned int)g_offset_x10)
                 ? (unsigned int)(rot - (unsigned int)g_offset_x10)
                 : (unsigned int)(rot + 3600u - (unsigned int)g_offset_x10);
            s = (unsigned int)((phys + tx / 2u) / tx);
            if (s == 0u || s >= g_real) s = 1u;
            g_ph_slot = s;
        }
    }

    /* THE RESOLVED ROUTE, PUBLISHED. A bench can now tell "the page says 86"
       from "the hardware is capturing 86" without a reflash, which is the
       same reason the thirteen trigCfg* channels exist. */
    trg_cfg_capture_map = (unsigned int)(g_role[TGT_CAPCH_CC15]
                                         | (g_role[TGT_CAPCH_CC8] << 4)
                                         | (g_role[TGT_CAPCH_CC9] << 8));

    /* WHICH CAVITY EACH CAPTURE CHANNEL SERVES IS PART OF THE GEOMETRY NOW.
       roles_resolve() has to run before the signature is taken, and the roles
       have to be IN the signature - otherwise moving pinCrank from 82 to 86
       would change nothing that geometry_refresh() can see, the captures would
       never be re-armed, and the edit would look accepted while the ECU went
       on reading the old cavity. That is the defect this whole change exists
       to remove, and it would have come straight back in through the change
       detector. roles_resolve() has already run, just above the publish. */
    sig = (unsigned long)g_teeth;
    sig = (sig << 8) | (unsigned long)(g_gap & 0xFFu);
    sig = (sig << 8) | (unsigned long)(g_ratio_x10 & 0xFFu);
    sig = (sig << 8) | (unsigned long)((g_crank_ccm << 4) | g_cam_ccm);
    sig ^= ((unsigned long)g_cam_refs << 25)
         ^ ((unsigned long)g_cam_win_x10 << 12)
         ^ (unsigned long)trg_cfg_cam_ref_x10
         ^ ((unsigned long)g_sync_bank << 6)
         ^ ((unsigned long)(unsigned int)g_offset_x10 << 3)
         ^ ((unsigned long)g_min_teeth << 17)
         ^ ((unsigned long)g_cam_on << 2)
         ^ ((unsigned long)g_role[TGT_CAPCH_CC15] << 20)
         ^ ((unsigned long)g_role[TGT_CAPCH_CC8] << 22)
         ^ ((unsigned long)g_role[TGT_CAPCH_CC9] << 28)
         ^ ((unsigned long)g_ph_angle << 9)
         ^ ((unsigned long)((g_cam_mode << 4) | (g_ph_level << 3)
                            | g_ph_confirm) << 26)
         /* V97 PATTERN: the wheels, cam 2's angle and the tolerance */
         ^ ((unsigned long)hc_cal_u8(CFG_U_CAM1_PATTERN) << 3)
         ^ ((unsigned long)hc_cal_u8(CFG_U_CAM2_PATTERN) << 13)
         ^ ((unsigned long)hc_cal_u16(CFG_U_CAM2_REF_X10) << 5)
         ^ ((unsigned long)hc_cal_u8(CFG_U_CAM_TOOTH_TOL) << 24);
    return sig;
}

void trg_init(void)
{
    trg_state = TRG_NO_SIGNAL;
    trg_rpm = 0; trg_tooth = 0; trg_teeth_seen = 0; trg_gaps = 0;
    trg_synccorr = 0; trg_synclost = 0; trg_last_dt = 0; trg_tooth_dt = 0;
    trg_cam_edges = 0; trg_cam_tooth = 0xFFFFu; trg_rev = 0; trg_toolow = 0;
    trg_isr_ticks = 0; trg_isr_max = 0; trg_isr_headroom = 0xFFFFu;
    trg_phase = 0; trg_phsok_c = 0; trg_phase_corr = 0;
    last_rot = 0; rot_valid = 0;
    trg_phase_lost = 0; trg_sim_rpm = 0; trg_loss_reason = TRG_LOSS_NONE;
    trg_noise_edges = 0; trg_gap_metric_x10 = 0; trg_gap_detected = 0;
    trg_gap_pending = 0; trg_last_edge_t1 = 0; trg_tooth_corr = 0;
    corr_run = 0u; gap_pending_count = 0; loss_pend = 0u; loss_mark = 0u;
    trg_engine_deg_x10 = 0; trg_stall_state = 1; trg_crank_period = 0;
    trg_cam1_edges = 0; trg_cam2_edges = 0;
    trg_cam1_tooth = 0xFFFFu; trg_cam2_tooth = 0xFFFFu;
    trg_cam1_window = 0xFFFFu; trg_cam2_window = 0xFFFFu;
    trg_cam_error = 0; trg_cam_loss_reason = TRG_LOSS_NONE;
    trg_cam1_raw = 0; trg_cam2_raw = 0;
    trg_cam1_angle = 0xFFFFu; trg_cam2_angle = 0xFFFFu;
    trg_cfg_generation = 0;
    have_edge = 0; last_t = 0; prev1 = 0; prev2 = 0; good_teeth = 0;
    gap_pending_expected = 0; slot = 0;
    disagreements = 0; stall_mark = 0; stall_t = T1; stall_ticks = 0;
    rev_ticks = 0; metric_num = 0; metric_den = 0; source_live = 0;
    cam1_last_rev = 0; cam2_last_rev = 0;
    trg_cycle_acq = 0; trg_cycle_lost = 0; trg_ph_noalt = 0; trg_ph_status = 0;
    trg_cam_lo_w_x10 = 0; trg_cam_hi_w_x10 = 0;
    ph_last = 0; ph_have_last = 0;
    cam_last_fall = 0xFFFFu; cam_last_rise = 0xFFFFu;
    seen_active_rev = hc_cfg_active_rev;
    g_sig = geometry_read();
    trigger_hw((unsigned int)(cfg_u8(CFG_TRIG_SOURCE) == TRIG_SRC_REAL));
    hc_drysched_init();
}

/* WITHDRAW THE CYCLE, KEEP THE CRANK.
   A cam that disagrees, goes missing or stops alternating can take away
   what only the cam knew - which revolution this is - and nothing else.
   V91 called lose_sync() for a cam edge outside its window, which threw
   away a crank position that was still perfectly valid and counted it as a
   crank sync loss. hc_drysched_service() cancels whatever a strategy that
   needs the cycle had pending; batch and wasted strategies are untouched. */
static void cycle_lose(unsigned int reason)
{
    if (trg_state == TRG_SYNC_FULL) {
        trg_state = TRG_SYNC_CRANK;
        if (trg_cycle_lost != 0xFFFFu) trg_cycle_lost++;
    }
    trg_cam_loss_reason = reason;
}

/* THE LEVEL CHECK - one port read on one tooth per revolution.
 *
 * The published engine angle says which half the decoder believes. If it
 * is within 180 degrees of the configured check angle, the cam must read
 * g_ph_level; 360 degrees away it must read the other level. Bosch expects
 * the level to ALTERNATE at the reference mark every revolution (B_siph);
 * a level that repeats says nothing about the half and is counted, not
 * trusted. The crank is never touched: a wrong half is corrected by moving
 * the half (trg_phase, +/-360 degrees - the scheduler recognises that step
 * and remaps rather than re-seeding), and only a cam that CAN decide
 * (g_ph_decides, a cycle sync mode) may move it or grant TRG_SYNC_FULL. */
static void cam_phase_sample(void)
{
    unsigned int a = trg_engine_deg_x10;
    unsigned int d = (a >= g_ph_angle) ? (unsigned int)(a - g_ph_angle)
                                       : (unsigned int)(g_ph_angle - a);
    unsigned char lvl = (unsigned char)((P2 & g_ph_mask) ? 1u : 0u);
    unsigned char want;
    unsigned int good = (unsigned int)(trg_ph_status >> 8);
    unsigned int st;

    if (d > 3600u) d = (unsigned int)(7200u - d);
    want = (unsigned char)((d < 1800u) ? g_ph_level : !g_ph_level);
    st = (unsigned int)(lvl | 0x0008u);

    if (ph_have_last && lvl == ph_last) {
        if (trg_ph_noalt != 0xFFFFu) trg_ph_noalt++;
        trg_cam_error |= 0x0010u;
        good = 0u;
        if (g_ph_decides) cycle_lose(TRG_LOSS_CAM_PATTERN);
    } else {
        if (ph_have_last) st |= 0x0004u;
        trg_cam_error &= 0xFFEFu;
        if (lvl == want) {
            st |= 0x0002u;
            if (good < 255u) good++;
        } else if (g_ph_decides) {
            /* The other half. Move it, count it; a cycle that was already
               claimed was wrong and is withdrawn first. */
            if (trg_state == TRG_SYNC_FULL) cycle_lose(TRG_LOSS_CAM_PHASE);
            trg_phase ^= 1u;
            trg_engine_deg_x10 = (a >= 3600u) ? (unsigned int)(a - 3600u)
                                              : (unsigned int)(a + 3600u);
            if (trg_phase_corr != 0xFFFFu) trg_phase_corr++;
            st |= 0x0002u;
            good = 1u;
        } else {
            good = 0u;
        }
        /* Only a check that followed an alternating one counts towards the
           cycle: the first check after sync has nothing to alternate from. */
        if (g_ph_decides && trg_state == TRG_SYNC_CRANK && ph_have_last
            && good >= g_ph_confirm) {
            trg_state = TRG_SYNC_FULL;
            if (trg_cycle_acq != 0xFFFFu) trg_cycle_acq++;
        }
    }
    ph_last = lvl;
    ph_have_last = 1u;
    trg_ph_status = (unsigned int)(st | (good << 8));
}

/* Bounded crank ISR core. */
static void crank_edge(unsigned int t)
{
    unsigned int dt;

    trg_teeth_seen++;
    if (loss_pend && (unsigned int)(trg_teeth_seen - loss_mark) > g_real) {
        loss_pend = 0u;                 /* still turning: a real loss */
        if (trg_synclost != 0xFFFFu) trg_synclost++;
    }
    if (!have_edge) {
        have_edge = 1; last_t = t; trg_last_edge_t1 = t; trg_state = TRG_COUNTING;
        trg_stall_state = 0;
        return;
    }
    dt = (unsigned int)(t - last_t);
    if (prev1 && dt < min_edge_ticks) {
        if (trg_noise_edges != 0xFFFFu) trg_noise_edges++;
        trg_loss_reason = TRG_LOSS_EXTRA_EDGE;
        return;                         /* retain last VALID timestamp */
    }
    last_t = t; trg_last_edge_t1 = t; trg_last_dt = dt; trg_stall_state = 0;
    rev_ticks += (unsigned long)dt;

    if (!prev1) {
        prev1 = dt; prev2 = dt; trg_tooth_dt = dt; good_teeth++; trg_tooth++;
        slot_advance();
        publish_angle();
        hc_drysched_tooth(trg_engine_deg_x10, t, dt);
        return;
    }

    /* The OEM ME7.1.1 85:886C decomposition, with the fixed 2.0 shift
       replaced by the configured ratio. Exactly three consecutive intervals
       participate: the candidate, its predecessor and its successor. Waiting
       for the successor is what rejects an isolated elongation, and it is why
       position stays provisional for one tooth after a long interval. */
    if (trg_gap_pending && longer(prev1, dt) && longer(prev1, prev2)) {
        unsigned int expected = gap_pending_expected;

        trg_gap_detected = 1;
        if (trg_gaps != 0xFFFFu) trg_gaps++;
        metric_num = prev1; metric_den = (unsigned int)((dt + prev2) >> 1);
        if (trg_state == TRG_COUNTING) {
            trg_state = TRG_GAP_SEEN;
        } else if (expected) {
            disagreements = 0;
            corr_run = 0u;
            if (trg_state == TRG_GAP_SEEN && good_teeth >= g_min_teeth)
                trg_state = TRG_SYNC_CRANK;
            else if (trg_state >= TRG_SYNC_CRANK && trg_rev != 0xFFFFu)
                trg_rev++;
            trg_crank_period = rev_ticks;
        } else if (trg_state >= TRG_SYNC_CRANK && corr_run == 0u
                   && (gap_pending_count + 1u == g_real
                       || gap_pending_count == g_real + 1u)) {
            /* ONE TOOTH TOO FEW OR TOO MANY IS A CORRECTION, NOT A LOSS.
             *
             * The confirmed gap IS the physical reference; the count is
             * only our bookkeeping of the teeth since the last one. Bosch
             * treats a +/-1 disagreement at the reference mark as a tooth
             * correction (ME7.5 A2L: B_fbm "Bezugsmarkenfehler => mindestens
             * 1 Zahn zuviel oder zuwenig", counters CORTINC/CORTMX) and
             * re-anchors. V91 dropped sync instead: on the AWT (2026-09-27)
             * every crank sync loss was exactly one crank edge missing in
             * that revolution while cranking at 6-9 V - four times, each
             * withdrawing fuel and spark for a revolution.
             *
             * BOUNDED: a correction is accepted only if the previous
             * reference was clean (corr_run == 0). A second disagreement in
             * a row is a real loss and takes the path below. The
             * revolution's period is NOT published: it spanned 57 or 59
             * delivered teeth and is still one revolution of crank, so it
             * is kept for rpm, but the tooth count behind it was wrong. */
            corr_run = 1u;
            disagreements = 0;
            /* An EXTRA tooth was already counted as a correction when the
               count passed g_real (the missing-gap check below); a MISSING
               one is counted here. Either way it is one correction. */
            if (gap_pending_count + 1u == g_real && trg_synccorr != 0xFFFFu)
                trg_synccorr++;
            if (trg_tooth_corr != 0xFFFFu) trg_tooth_corr++;
            if (trg_rev != 0xFFFFu) trg_rev++;
            trg_crank_period = rev_ticks;
        } else {
            if (trg_synccorr != 0xFFFFu) trg_synccorr++;
            /* A plausible but out-of-position marker invalidates position
               immediately.  V27 retained CRANK_SYNC while rephasing here. */
            lose_sync(TRG_LOSS_EARLY_GAP);
            trg_state = TRG_GAP_SEEN;
        }
        rev_ticks = 0;
        /* the half now flips inside publish_angle(), on the wrap of the
           rotated angle - which for offset 0 is exactly here. */
        trg_tooth = 1u;
        slot = 1u;
        publish_angle();
        if (slot == g_ph_slot && trg_state >= TRG_SYNC_CRANK) cam_phase_sample();
        prev1 = dt; prev2 = dt; trg_tooth_dt = dt;
        trg_gap_pending = 0; gap_pending_expected = 0;
        if (good_teeth != 0xFFFFu) good_teeth++;
        hc_drysched_tooth(trg_engine_deg_x10, t, dt);
        return;
    }

    if (trg_gap_pending) {
        /* A one-sided elongation is only a candidate. If its successor does
           not confirm it, it was an ordinary interval: retain sync, phase and
           tooth progression. This is the frozen-V27 false-3x regression. */
        trg_gap_pending = 0; gap_pending_expected = 0;
    }

    /* Remember a one-sided long interval, but do not call it a reference
       until the next edge supplies the second independent neighbour. */
    if (longer(dt, prev1)) {
        trg_gap_pending = 1;
        gap_pending_count = (unsigned int)(trg_tooth + 1u);
        gap_pending_expected = (unsigned int)(gap_pending_count == g_real);
        prev2 = prev1; prev1 = dt;
        trg_tooth++;
        slot_advance();
        publish_angle();
        return;
    }

    trg_gap_detected = 0; prev2 = prev1; prev1 = dt; trg_tooth_dt = dt;
    if (good_teeth != 0xFFFFu) good_teeth++;
    trg_tooth++;
    slot_advance();
    if (trg_tooth >= g_real && trg_state >= TRG_GAP_SEEN) {
        if (trg_synccorr != 0xFFFFu) trg_synccorr++;
        disagreements++; trg_loss_reason = TRG_LOSS_MISSING_GAP;
        if (disagreements >= 2u) lose_sync(TRG_LOSS_MISSING_GAP);
    }
    publish_angle();
    if (slot == g_ph_slot && trg_state >= TRG_SYNC_CRANK) cam_phase_sample();
    hc_drysched_tooth(trg_engine_deg_x10, t, dt);
}

/* Which configured reference, if any, this engine angle falls on. The table
   was built in task context; nothing here divides or reads the page. */
static unsigned int cam_window(unsigned int angle)
{
    unsigned int i, d;

    for (i = 0u; i < g_cam_refs; i++) {
        d = (angle > g_cam_ref[i]) ? (unsigned int)(angle - g_cam_ref[i])
                                   : (unsigned int)(g_cam_ref[i] - angle);
        if (d > 3600u) d = (unsigned int)(7200u - d);
        if (d <= g_cam_win_x10) return i;
    }
    return 0xFFFFu;
}

static void cam_edge(unsigned int bank, unsigned int stamp)
{
    unsigned int a = trg_engine_deg_x10;
    unsigned int w, decides;

    /* V97 PATTERN: RECORD, NEVER DECIDE, in the ISR. The crank ISR (level
       12) can preempt this one (10) between reading the tooth's angle and
       its time, so the pair is re-read once if the tooth moved under it. */
    if (g_cam_mode == CAMPH_PATTERN) {
        unsigned char q = (unsigned char)(bank - 1u), i;
        unsigned int t0;

        trg_cam_edges++; trg_cam_tooth = trg_tooth;
        if (bank == 1u) {
            trg_cam1_edges++; trg_cam1_tooth = trg_tooth; trg_cam1_angle = a;
            cam1_last_rev = trg_rev; trg_cam_error &= 0xFFFAu;
        } else {
            trg_cam2_edges++; trg_cam2_tooth = trg_tooth; trg_cam2_angle = a;
            cam2_last_rev = trg_rev; trg_cam_error &= 0xFFF5u;
        }
        if (trg_state < TRG_SYNC_CRANK
            || (unsigned char)(camq_w[q] - camq_r[q]) >= CAMQ) {
            return;
        }
        t0 = trg_last_edge_t1;
        a = trg_engine_deg_x10;
        if (t0 != trg_last_edge_t1) {
            t0 = trg_last_edge_t1;
            a = trg_engine_deg_x10;
        }
        i = (unsigned char)(camq_w[q] & (CAMQ - 1u));
        camq_ang[q][i] = a;
        /* signed: when the crank ISR preempted between the cam capture and
           here, the capture is BEFORE the tooth the angle belongs to */
        camq_since[q][i] = (int)(stamp - t0);
        camq_dt[q][i] = trg_tooth_dt;
        camq_ep[q][i] = cam_epoch;
        camq_w[q]++;
        return;
    }

    /* THE LEVEL METHOD DOES NOT MATCH EDGES AGAINST WINDOWS - the half
       is decided by cam_phase_sample() on a crank tooth. An edge here is
       counted, keeps the missing-cam watch alive, and measures the sector
       it closes: both transitions are captured, the pin level after the
       edge says which one this was. */
    if (g_cam_mode == CAMPH_LEVEL) {
        unsigned int m = (bank == 1u) ? g_cam1_mask : g_cam2_mask;
        unsigned char hi = (unsigned char)((P2 & m) ? 1u : 0u);

        trg_cam_edges++; trg_cam_tooth = trg_tooth;
        if (bank == 1u) {
            trg_cam1_edges++; trg_cam1_tooth = trg_tooth; trg_cam1_angle = a;
            trg_cam1_raw = hi; cam1_last_rev = trg_rev;
            trg_cam_error &= 0xFFFAu;       /* seen: not missing, no window */
        } else {
            trg_cam2_edges++; trg_cam2_tooth = trg_tooth; trg_cam2_angle = a;
            trg_cam2_raw = hi; cam2_last_rev = trg_rev;
            trg_cam_error &= 0xFFF5u;
        }
        if (m == g_ph_mask && trg_state >= TRG_SYNC_CRANK) {
            if (hi) {
                if (cam_last_fall != 0xFFFFu)
                    trg_cam_lo_w_x10 = (a >= cam_last_fall)
                        ? (unsigned int)(a - cam_last_fall)
                        : (unsigned int)(a + 7200u - cam_last_fall);
                cam_last_rise = a;
            } else {
                if (cam_last_rise != 0xFFFFu)
                    trg_cam_hi_w_x10 = (a >= cam_last_rise)
                        ? (unsigned int)(a - cam_last_rise)
                        : (unsigned int)(a + 7200u - cam_last_rise);
                cam_last_fall = a;
            }
        }
        return;
    }
    w = cam_window(a);
    decides = (unsigned int)(g_cam_resolves
                             && (g_sync_bank == 3u || g_sync_bank == bank));

    trg_cam_edges++; trg_cam_tooth = trg_tooth;

    /* THE OTHER HALF OF THE CYCLE. The crank alone cannot know which
       revolution it is in, so trg_phase starts as a guess and flips at every
       gap. When the cam geometry CAN resolve the cycle and the edge does not
       land on a reference, try the angle 360 degrees away before calling it
       an error: a match there means the guess was simply the wrong half, and
       that is a phase CORRECTION - Bosch's phsok_b acquiring - not a fault. */
    if (w == 0xFFFFu && decides && trg_state >= TRG_SYNC_CRANK) {
        unsigned int b = (a >= 3600u) ? (unsigned int)(a - 3600u)
                                      : (unsigned int)(a + 3600u);
        w = cam_window(b);
        if (w != 0xFFFFu) {
            trg_phase ^= 1u;
            trg_engine_deg_x10 = b;
            a = b;
            if (trg_phase_corr != 0xFFFFu) trg_phase_corr++;
        }
    }

    /* A CAM WITH NO CONFIGURED GEOMETRY CANNOT BE OUT OF ITS WINDOW, because
       it has no windows. With CFG_U_CAM_REFS at 0 - which is what a freshly
       flashed page holds - cam_window() returns 0xFFFF for every edge, and
       calling that a fault would raise camError against a cam nobody has
       described. The edge is still counted and still reported; what it is not
       is evidence of anything being wrong. */
    if (bank == 1u) {
        trg_cam1_edges++; trg_cam1_tooth = trg_tooth; trg_cam1_window = w;
        trg_cam1_angle = a;
        trg_cam1_raw = (unsigned int)((P2 & 0x0100u) != 0); cam1_last_rev = trg_rev;
        /* Seeing THIS bank clears its missing bit as well as its window bit. */
        trg_cam_error &= 0xFFFBu;
        if (w == 0xFFFFu && g_cam_refs) trg_cam_error |= 1u;
        else trg_cam_error &= 0xFFFEu;
    } else {
        trg_cam2_edges++; trg_cam2_tooth = trg_tooth; trg_cam2_window = w;
        trg_cam2_angle = a;
        trg_cam2_raw = (unsigned int)((P2 & 0x0200u) != 0); cam2_last_rev = trg_rev;
        trg_cam_error &= 0xFFF7u;
        if (w == 0xFFFFu && g_cam_refs) trg_cam_error |= 2u;
        else trg_cam_error &= 0xFFFDu;
    }

    if (w == 0xFFFFu) {
        if (g_cam_refs) {
            /* demote, never lose the crank (cycle_lose()). */
            cycle_lose(TRG_LOSS_CAM_WINDOW);
        }
        return;
    }
    if (trg_phsok_c != 0xFFFFu) trg_phsok_c++;
    /* Cycle sync is granted ONLY by geometry that can prove which revolution
       this is, and only once the crank itself is synchronised. */
    if (decides && trg_state == TRG_SYNC_CRANK) {
        trg_state = TRG_SYNC_FULL;
        if (trg_cycle_acq != 0xFFFFu) trg_cycle_acq++;
    }
}

static void isr_done(unsigned int entry)
{
    unsigned int took = (unsigned int)(T1 - entry);
    trg_isr_ticks = took;
    if (took > trg_isr_max) trg_isr_max = took;
    if (trg_tooth_dt) trg_isr_headroom = (took < trg_tooth_dt)
        ? (unsigned int)(trg_tooth_dt - took) : 0u;
}

/* THE THREE ISRs DISPATCH ON THE ROLE THEIR CAVITY GAVE THEM.
 *
 * The cost is one byte load and up to two compares per edge. At 6000 rpm on a
 * 60-2 that is 5800 edges a second, and the crank handler already measures
 * itself into trg_isr_ticks / trg_isr_max - so if this ever stopped being
 * free, the ECU would say so rather than this comment having to promise it.
 *
 * A channel whose role is ROLE_NONE is never armed (see trigger_hw), so the
 * default arm in these handlers is genuinely unreachable; it is written out
 * anyway because an unreachable default that does nothing is cheaper than an
 * unconnected input that makes edges nobody expected. */
/* ===================== V98: THE TUNERSTUDIO TOOTH / COMPOSITE LOGGER =====
 *
 * rusEFI's composite_logger_s, 8 bytes per edge, written in WIRE order
 * (big-endian, "the whole order of all packet bytes is reversed"): byte 0
 * spare, 1 injectors ON, 2 coils ON, 3 flags (bit0 crank level, bit1 cam 1
 * level, bit2 the edge was a cam, bit3 crank sync, bit5 cam 2 level), 4..7
 * the T1 time extended to 32 bits (0.8 us per count - the .ini scales it).
 * A level TOGGLES at each captured edge: one edge per tooth is captured, so
 * each record is a transition, which is what TunerStudio draws.
 *
 * COST: one byte test per edge while off; ~40 instructions while logging;
 * nothing once the buffer is full (it waits for TunerStudio's read). */
#define TLOG ((unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_TLOG))
unsigned char hc_tlog_on;
unsigned int  hc_tlog_n;
static unsigned int  tlog_hi, tlog_last;
static unsigned char tlog_lvl;

static void tlog_edge(unsigned int t, unsigned char kind)
{
    unsigned int i = hc_tlog_n;
    unsigned char huge *p;

    if (t < tlog_last) {
        tlog_hi++;                         /* T1 wrapped since the last edge */
    }
    tlog_last = t;
    if (i >= TGT_TLOG_N) {
        return;
    }
    tlog_lvl ^= (unsigned char)((kind == 0u) ? 0x01u
                                             : ((kind == 1u) ? 0x02u : 0x20u));
    p = TLOG + (unsigned int)(i << 3);
    p[0] = 0u;
    p[1] = (unsigned char)hc_hal_out_mask_inj();
    p[2] = (unsigned char)hc_hal_out_mask_ign();
    p[3] = (unsigned char)(tlog_lvl | ((kind != 0u) ? 0x04u : 0u)
                           | ((trg_state >= TRG_SYNC_CRANK) ? 0x08u : 0u));
    p[4] = (unsigned char)(tlog_hi >> 8);
    p[5] = (unsigned char)tlog_hi;
    p[6] = (unsigned char)(t >> 8);
    p[7] = (unsigned char)t;
    hc_tlog_n = (unsigned int)(i + 1u);
}

/* Task context (hcts.c 'l'). Returns the bytes to send for a read: the
   full buffer, or what there is once the engine has stopped (a stall never
   fills it); 0 otherwise - an EMPTY TS_OK reply, never an error code. */
unsigned int hc_tlog_cmd(unsigned char sub)
{
    switch (sub) {
    case 1u:                               /* composite logger on      */
    case 7u:                               /* primary tooth logger on  */
        hc_tlog_on = 0u;
        hc_tlog_n = 0u;
        hc_tlog_on = (unsigned char)((sub == 1u) ? 1u : 2u);
        return 0u;
    case 2u:
        hc_tlog_on = 0u;
        return 0u;
    case 3u:
        if (hc_tlog_n >= TGT_TLOG_N || (hc_tlog_n != 0u && trg_rpm == 0u)) {
            return (unsigned int)(hc_tlog_n << 3);
        }
        return 0u;
    case 0x80u:                            /* the read went out        */
        hc_tlog_n = 0u;
        return 0u;
    default:
        return 0u;
    }
}

unsigned char hc_tlog_byte(unsigned int i)
{
    return TLOG[i];
}

/* The logger follows the ROLE, not the channel - the capture map is
   routable. The crank source is the highest capture level;
   a cam record is written at the config critical level so the crank ISR
   cannot claim the same slot between the read and the increment. */
static void tlog_role(unsigned char role, unsigned int t)
{
    if (role == ROLE_CRANK) {
        tlog_edge(t, 0u);
    } else if (hc_tlog_on == 1u && (role == ROLE_CAM1 || role == ROLE_CAM2)) {
        unsigned int sv;

        TRG_IRQ_SAVE(sv);
        tlog_edge(t, (role == ROLE_CAM1) ? 1u : 2u);
        TRG_IRQ_RESTORE(sv);
    }
}

void hc_cc15_isr(void) interrupt TGT_TRAP_CC15INT using CRANKBANK
{
    unsigned int entry = T1;
    unsigned char role = g_role[TGT_CAPCH_CC15];
    HC_PROBE_CLAIM(TGT_TRAP_CC15INT);
    if (role == ROLE_CRANK) {
        crank_edge(CC15);
        if (hc_tlog_on) tlog_role(role, CC15);
        isr_done(entry);
        return;
    } else if (role == ROLE_CAM1) {
        cam_edge(1u, CC15);
    } else if (role == ROLE_CAM2) {
        cam_edge(2u, CC15);
    }
    if (hc_tlog_on) tlog_role(role, CC15);
}

/* The cams share the crank's register bank: one ILVL (12), so none of the
   three ever preempts another (32 bytes of IRAM). */
void hc_cc8_isr(void) interrupt TGT_TRAP_CC8INT using CRANKBANK
{
    unsigned int entry = T1;
    unsigned char role = g_role[TGT_CAPCH_CC8];
    HC_PROBE_CLAIM(TGT_TRAP_CC8INT);
    if (role == ROLE_CAM1) {
        cam_edge(1u, CC8);
    } else if (role == ROLE_CRANK) {
        crank_edge(CC8);
        if (hc_tlog_on) tlog_role(role, CC8);
        isr_done(entry);
        return;
    } else if (role == ROLE_CAM2) {
        cam_edge(2u, CC8);
    }
    if (hc_tlog_on) tlog_role(role, CC8);
}

void hc_cc9_isr(void) interrupt TGT_TRAP_CC9INT using CRANKBANK
{
    unsigned int entry = T1;
    unsigned char role = g_role[TGT_CAPCH_CC9];
    HC_PROBE_CLAIM(TGT_TRAP_CC9INT);
    if (role == ROLE_CAM2) {
        cam_edge(2u, CC9);
    } else if (role == ROLE_CRANK) {
        crank_edge(CC9);
        if (hc_tlog_on) tlog_role(role, CC9);
        isr_done(entry);
        return;
    } else if (role == ROLE_CAM1) {
        cam_edge(1u, CC9);
    }
    if (hc_tlog_on) tlog_role(role, CC9);
}

/* THE KNOCK MEASUREMENT WINDOW, MF = P8.0 (CC195 pin 27, the ME7.1.1 schematic).
 *
 * The OEM runs it the same way [BIN 89:4C1C]: a CAPCOM2 CC16 compare on the
 * opening edge sets MF and adds the window length to CC16; the closing match
 * clears MF and the integrator (KI, AN15) is read. HaniCore's CC16 runs in
 * compare mode 0 (interrupt only) against T7 and this handler drives the pin
 * with one bit instruction, so no port read-modify-write can race it (the
 * HAL's P8 group write is two single-instruction ops since V97). The main
 * loop (hcknock711.c) arms it and samples KI; this only moves the edges. The
 * state it shares lives in external SRAM (HC_KN711). */
sbit KN_MF = P8 ^ 0;
void hc_cc16_isr(void) interrupt TGT_TRAP_CC16INT
{
    HC_PROBE_CLAIM(TGT_TRAP_CC16INT);
    if (HC_KN711.st == KN_ST_ARMED) {
        KN_MF = 1;
        CC16 = (unsigned int)(CC16 + HC_KN711.len_ticks);
        HC_KN711.t_open = T7;
        HC_KN711.st = KN_ST_OPEN;
    } else {
        KN_MF = 0;
        CC16IE = 0;
        if (HC_KN711.st == KN_ST_OPEN) {
            HC_KN711.t_close = T7;
            HC_KN711.st = KN_ST_CLOSED;
        }
    }
}

/* Re-read the geometry if it has moved, and only while the engine is stopped.
   Returns 1 if anything changed. */
static unsigned int geometry_refresh(void)
{
    unsigned long sig = geometry_read();

    if (sig == g_sig) return 0u;
    g_sig = sig;
    if (trg_cfg_generation != 0xFFFFu) trg_cfg_generation++;
    /* A NEW WHEEL MAKES THE OLD POSITION MEANINGLESS, so it is discarded
       rather than carried across. The state goes to NO_SIGNAL directly and
       not through lose_sync(): nothing was lost, the question changed, and
       counting a synclost here would put a fault in front of a tuner who
       simply corrected their tooth count. The scheduler is told, because a
       pending event was planned against angles that no longer exist. */
    slot = 0u; trg_tooth = 0u; good_teeth = 0u;
    have_edge = 0u; prev1 = 0u; prev2 = 0u;
    trg_gap_pending = 0u; gap_pending_expected = 0u; corr_run = 0u;
    ph_have_last = 0u; trg_ph_status = 0u;
    cam_last_fall = 0xFFFFu; cam_last_rise = 0xFFFFu;
    trg_state = TRG_NO_SIGNAL;
    trg_rpm = 0u; trg_crank_period = 0uL; trg_stall_state = 1u;
    trg_engine_deg_x10 = 0u;
    hc_drysched_cancel(TRG_LOSS_STALL);
    return 1u;
}

/* apply one core decision. The crank ISR writes trg_state and the
   angle too, so the test-and-set happens with it held off. */
static void pattern_apply(unsigned char b, unsigned char act)
{
    unsigned int psw;
    unsigned char flipped = 0u;

    if (!g_pat_decides[b]) {
        /* a watched cam never moves the cycle; a FLIP it made alone moved
           only its own history - make it relearn in the engine's half */
        if (act & HCCAM_A_FLIP) hccam_reset(&hccam_bank[b]);
        return;
    }
    TRG_IRQ_SAVE(psw);
    if (act & HCCAM_A_LOSE) {
        cycle_lose((hccam_bank[b].cls == HCCAM_C_OTHER) ? TRG_LOSS_CAM_PHASE
                                                         : TRG_LOSS_CAM_PATTERN);
    }
    if ((act & HCCAM_A_FLIP) && trg_state >= TRG_SYNC_CRANK) {
        trg_phase ^= 1u;
        trg_engine_deg_x10 = (trg_engine_deg_x10 >= 3600u)
            ? (unsigned int)(trg_engine_deg_x10 - 3600u)
            : (unsigned int)(trg_engine_deg_x10 + 3600u);
        cam_epoch++;
        if (trg_phase_corr != 0xFFFFu) trg_phase_corr++;
        flipped = 1u;
    }
    if ((act & HCCAM_A_GRANT) && trg_state == TRG_SYNC_CRANK) {
        trg_state = TRG_SYNC_FULL;
        if (trg_cycle_acq != 0xFFFFu) trg_cycle_acq++;
    }
    TRG_IRQ_RESTORE(psw);
    /* the other cam's history is in the old half now */
    if (flipped && g_pat_ok[b ^ 1u]) hccam_reset(&hccam_bank[b ^ 1u]);
}

static void pattern_service(void)
{
    unsigned char b, r, n;
    unsigned int ang, dt, step;
    int since;

    if (trg_state < TRG_SYNC_CRANK || trg_synclost != pat_seen_lost) {
        /* no crank position, or a new one: nothing queued or remembered was
           measured in it */
        pat_seen_lost = trg_synclost;
        for (b = 0u; b < 2u; b++) {
            camq_r[b] = camq_w[b];
            if (g_pat_ok[b]) hccam_reset(&hccam_bank[b]);
        }
        if (trg_state < TRG_SYNC_CRANK) return;
    }
    for (b = 0u; b < 2u; b++) {
        if (!g_pat_ok[b]) {
            camq_r[b] = camq_w[b];
            continue;
        }
        for (n = 0u; n < CAMQ && camq_r[b] != camq_w[b]; n++) {
            r = (unsigned char)(camq_r[b] & (CAMQ - 1u));
            since = camq_since[b][r];
            dt = camq_dt[b][r];
            ang = camq_ang[b][r];
            if (dt != 0u) {
                /* at most three teeth either way (a 60-2 gap is three) */
                unsigned long mag = (unsigned long)(since < 0 ? -since : since);
                if (mag > 3uL * dt) mag = 3uL * dt;
                step = (unsigned int)((mag
                    * (unsigned long)trg_cfg_tooth_x10) / (unsigned long)dt);
                ang = (since < 0) ? (unsigned int)(ang + 7200u - step)
                                  : (unsigned int)(ang + step);
            }
            if ((unsigned char)(cam_epoch - camq_ep[b][r]) & 1u) ang += 3600u;
            while (ang >= 7200u) ang -= 7200u;
            camq_r[b]++;
            pattern_apply(b, hccam_edge(&hccam_bank[b], ang, 1u,
                                        (unsigned char)(trg_state == TRG_SYNC_FULL)));
            /* a fresh cam position (tooth 0 identified) for the VVT
               control's feedback watch - hcvvt711.c */
            if (hccam_bank[b].tooth == 0u) {
                HC_VVT711.syncs[b]++;
            }
        }
    }
}

void trg_service(void)
{
    unsigned int now = T1;
    unsigned int elapsed = (unsigned int)(now - stall_t);
    unsigned int want = (unsigned int)(cfg_u8(CFG_TRIG_SOURCE) == TRIG_SRC_REAL);
    stall_t = now;

    /* A GEOMETRY EDIT MUST REACH THE DECODER, AND ONLY WHEN IT IS SAFE.
     *
     * hc_config_manager stages the wheel bytes as RPM_ZERO_APPLY, so by the
     * time they are in the page the engine is stopped - but until V55 nothing
     * re-read them, so a tuner could change the tooth count and watch nothing
     * happen until the next power cycle.
     *
     * THE TRIGGER IS hc_cfg_active_rev, NOT A TIMER. The config manager
     * already counts every transaction it commits to the ACTIVE page, so a
     * re-read is needed exactly when that number moves and at no other time.
     * The first version of this polled the page every 64 service calls, which
     * meant two 32-bit divides and ten external-SRAM reads fifteen times a
     * second, for ever, to discover that nothing had changed. A counter that
     * is already maintained is cheaper than any interval, and it reacts on
     * the first main loop after the apply instead of up to 64 loops later.
     *
     * The seen-value is only advanced when the re-read is actually allowed to
     * happen, so a transaction that lands while the engine is turning is
     * picked up the moment it stops rather than missed. */
    if (hc_cfg_active_rev != seen_active_rev
        && (trg_state == TRG_NO_SIGNAL || trg_rpm == 0u)) {
        seen_active_rev = hc_cfg_active_rev;
        if (geometry_refresh() && source_live) {
            trigger_hw(1u);                    /* re-arm on the new edge */
        }
    }

    if (want != source_live) {
        if (!want && trg_state >= TRG_SYNC_CRANK)
            lose_sync(TRG_LOSS_STALL);
        trigger_hw(want);
        stall_t = T1;
    }
    if (metric_den) {
        trg_gap_metric_x10 = (unsigned int)(((unsigned long)metric_num * 10uL)
                                           / (unsigned long)metric_den);
        metric_den = 0;
    }
    if (trg_teeth_seen == stall_mark && trg_state != TRG_NO_SIGNAL) {
        stall_ticks += elapsed;
        if (stall_ticks >= stall_limit) {
            lose_sync(TRG_LOSS_STALL); trg_state = TRG_NO_SIGNAL;
            trg_rpm = 0; trg_stall_state = 1; have_edge = 0;
            prev1 = 0; prev2 = 0; stall_ticks = 0;
            /* AND THE PERIOD THE RPM IS DERIVED FROM, or the assignment
               below puts the rpm straight back.
               
               MEASURED ON THE BENCH 2026-09-15: crank generator stopped,
               syncState 0, stallState 1, and `rpm` still reading 199 for ever.
               Four lines down this function does
               `if (trg_crank_period) trg_rpm = 75000000uL / trg_crank_period;`
               unconditionally, so clearing trg_rpm here and leaving the period
               standing lasted exactly until the end of the same call.
               
               AN ECU THAT PERMANENTLY BELIEVES IT IS TURNING IS NOT A COSMETIC
               FAULT. rpm == 0 is the precondition for applying an
               RPM_ZERO_APPLY configuration edit (hc_cfg_mgr_service), for
               every bounded bench output mode, for the fuel-pump lifecycle,
               and for hcnvm.c's live_admit(), which consults the crank horizon
               and the cam only while `rpm != 0 || trig_turning != 0`. With the
               rpm stuck, a single burst of crank signal disabled the Burn for
               the rest of the power cycle - which is what the bench measured:
               four Burns refused with HCNV_ERR_DEADLINE after the generator
               had already been switched off.
               
               This is as old as the decoder and it has never been reachable:
               no crank signal had reached this ECU before V55, so trg_rpm had
               never been non-zero to begin with. */
            /* No snapshot needed here: have_edge was cleared above, so the
               crank ISR cannot write the period again before this does. */
            trg_crank_period = 0uL; trg_tooth_dt = 0u; rev_ticks = 0uL;
        }
    } else {
        stall_mark = trg_teeth_seen; stall_ticks = 0;
    }
    /* THE PERIOD IS 32 BITS AND THE CRANK ISR WRITES IT, so it is read as one
       snapshot above the crank's level. Two plain word loads let the ISR land
       between them: across a 65536-tick boundary (1144 rpm on a 60-2) the
       torn value read 57792 or 572 rpm for one pass
       (tests/firmware/trigger/me711_crank_period_atomic_proof.py). */
    {
        unsigned long period;
        HC_ATOMIC_COPY(period, trg_crank_period);
        if (period) trg_rpm = (unsigned int)(75000000uL / period);
    }
    /* ---- ONLY A CAM THE CONFIGURATION SAYS EXISTS CAN BE MISSING ---------
     *
     * THIS IS THE V55 BURN REGRESSION, AND IT IS WORTH THE PARAGRAPH.
     *
     * Until V55 no crank signal had ever reached this ECU, so trg_state never
     * got past TRG_COUNTING, this block never ran, and trg_cam_error was 0 for
     * the whole life of the project. hcnvm.c's live_admit() has rejected every
     * flash window on `trg_cam_error != 0` since V51 and that clause had never
     * once been reachable.
     *
     * V55 is the first build whose crank actually turns. On the bench, with no
     * cam connected, the old code set bits 2 and 3 after five synced
     * revolutions - a MISSING CAM fault for a cam nobody had described - the
     * bits latched for the rest of the power cycle because nothing cleared
     * them, and from that moment every live Burn was refused while the crank
     * turned. TunerStudio reported `Burn page 0 failed`, and after several of
     * those the deferred replies that never came left the session reconnecting.
     * A Burn at rpm 0 still worked, because live_admit() only consults the cam
     * when `rpm != 0 || trig_turning != 0`.
     *
     * Three things were wrong and all three are this file's:
     *
     *   1. the fault was raised for a cam that is switched off or has no
     *      configured references;
     *   2. it was raised for BOTH banks on an engine described as having one;
     *   3. it latched - only trg_init() ever cleared it.
     *
     * g_sync_bank is the configuration's own statement of which cam inputs
     * this engine has: it is non-zero only when the cam is enabled AND has
     * references AND a sync mode names it. A cam that is merely watched is
     * deliberately not faulted here - being absent is not a failure of
     * something nobody said was present.
     *
     * hcnvm.c IS NOT TOUCHED. The admission rule is V51's, physically
     * qualified through V54, and it is right to refuse a flash window when the
     * engine position is genuinely in doubt. What was wrong was this file
     * telling it that it was. */
    if (trg_state < TRG_SYNC_CRANK) {
        /* NO CRANK SYNC MEANS NO REVOLUTION COUNT, so "revolutions since the
           last cam edge" has no meaning and must not be left standing. The
           reference restarts with the revolution counter.

           The test is on SYNC alone and not on `!(synced && rev > 4)`: folding
           the two put the early post-sync revolutions through the reset as
           well, which walked cam1_last_rev forward and pushed the first
           missing-cam report from the fifth revolution out to the eighth. The
           fault's timing is V55's; only its conditions changed. */
        trg_cam_error &= 0xFFF3u;
        cam1_last_rev = trg_rev; cam2_last_rev = trg_rev;
    } else if (trg_rev > 4u) {
        unsigned int miss = 0u;
        if ((unsigned int)(trg_rev - cam1_last_rev) > 3u) miss |= 4u;
        if ((unsigned int)(trg_rev - cam2_last_rev) > 3u) miss |= 8u;
        miss &= g_cam_expect;
        trg_cam_error = (unsigned int)((trg_cam_error & 0xFFF3u) | miss);
        if (miss) {
            trg_cam_loss_reason = TRG_LOSS_CAM_MISSING;
            /* AND GIVE UP THE CYCLE, WHICH UNTIL NOW WAS THE MISSING HALF.
             *
             * V55 raised these bits and V56 stopped them being raised for a
             * cam nobody described. Neither ever DEMOTED trg_state, so a
             * decoder whose cam had been dead for ten revolutions went on
             * publishing TRG_SYNC_FULL and a 720-degree angle that nothing
             * had confirmed since the last edge. Measured, ten revolutions
             * after the cam stopped: state=4, camError=0x0004, deg
             * alternating 348.0 / 708.0 for ever.
             *
             * hc_drysched_service() was ALREADY written for this and was
             * waiting for a signal that never came - its own comment says
             * "cancelling on the way down is the point: losing the cam must
             * withdraw pending SEQUENTIAL events, not merely stop planning
             * new ones". It compares sync_state against what the configured
             * STRATEGY needs, so a sequential engine now falls back and a
             * wasted-spark one is untouched (g_cam_expect is zero unless a
             * sync mode actually names the bank).
             *
             * DEMOTE, DO NOT lose_sync(). lose_sync() drops to TRG_COUNTING
             * and throws away the CRANK as well, which on a running engine
             * means re-finding the gap - a dead cam must not stop an engine
             * that still knows exactly where the crank is. The 360-degree
             * position was never in doubt and is kept.
             *
             * Re-acquisition needs no code: cam_edge() already promotes
             * TRG_SYNC_CRANK back to TRG_SYNC_FULL on the next edge that
             * decides the cycle. */
            cycle_lose(TRG_LOSS_CAM_MISSING);
            /* a cam that comes back starts a fresh pattern window */
            if (g_cam_mode == CAMPH_PATTERN) {
                if ((miss & 4u) && g_pat_ok[0]) hccam_reset(&hccam_bank[0]);
                if ((miss & 8u) && g_pat_ok[1]) hccam_reset(&hccam_bank[1]);
            }
        }
    }
    if (g_cam_mode == CAMPH_PATTERN) pattern_service();
    /* No planner call here any more: the crank ISR requests the planner's
       own interrupt level (hc_drysched_tooth, TGT_TRAP_PLAN). */
}

void trg_sim_service(void)
{
    /* Host regression injects exact CC15/CC8/CC9 captures. */
}

/* Instruction-level host regression entry points. They enter the same static
   cores as the capture ISRs and have no protocol binding or output path.
   trg_test_geometry() is the one addition: a rig that changes the page needs
   a deterministic way to make the decoder re-read it without counting out
   sixty-four service calls, and it returns the generation so the rig can
   assert that the re-read really happened. */
void trg_test_crank_edge(unsigned int stamp) { crank_edge(stamp); }
void trg_test_cam_edge(unsigned int bank) { cam_edge(bank, T1); }

unsigned int trg_test_geometry(void)
{
    geometry_refresh();
    return trg_cfg_generation;
}
