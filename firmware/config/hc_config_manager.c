/*
 * hc_config_manager.c - DESIRED / ACTIVE configuration, and the apply rules.
 *
 * Read hc_config_manager.h first: it carries the model. This file is the
 * mechanism, and the only things in it worth a comment are the ones that were
 * wrong before.
 */
#ifdef HC_FAR_BRIDGE
#include "hcfarbridge.h"  /* FIRST: this module is FAR code on ME7.1.1 */
#endif
#include <reg167.h>
#include "hctarget.h"
#include "hcconfig.h"
#include "hc_config_manager.h"
#include "hc_presets.h"
#include "hcts.h"   /* hcts_target_yield() */
#include "hc_pin_descriptor.h"
#if defined(TGT_ENGINE_RUNTIME)
#include "hcengctl711.h"   /* VE writes hold the closed loop */
#endif
#ifdef HC_FAR_BRIDGE
#include "hcfarinline.h"   /* AFTER hcconfig.h: call-free page reads */
#endif

/* Hold interrupts off across ONE field copy.
 *
 * Save-and-restore, not a bare IEN=0/IEN=1 pair: hc_cfg_mgr_apply_now() is
 * also reachable from init and from the tests with interrupts still globally
 * disabled, and a bare re-enable there would arm the interrupt system several
 * milliseconds before the startup means to. The longest field in the model is
 * a 32-byte axis, so the critical section is around 16 us at 40 MHz - three
 * orders below the 10 ms supervision raster this ECU is judged on. */
#ifdef TGT_ILVL_CFG_CRIT
/* NOT IEN. Clearing IEN also stops PEC, and the S5500 frame is a PEC
   transfer at 16 us a word - see TGT_ILVL_CFG_CRIT in hctarget.h for the
   measured 43 us window and the Receive Error it caused. Raising the CPU
   priority to TGT_ILVL_CFG_CRIT holds off every interrupt that reads the page
   (all at <= TGT_ILVL_ENGINE_MAX) and leaves the PEC levels 14/15 running.
   Never LOWERS the level: a caller already above it keeps its own. BFLDH is
   one instruction on the ILVL field only; the two NOPs cover the arbitration
   round the UM says may still accept a request after a PSW write. */
#include <intrins.h>
typedef char hc_cfg_crit_between_engine_and_pec[
    (TGT_ILVL_CFG_CRIT > TGT_ILVL_ENGINE_MAX && TGT_ILVL_CFG_CRIT < TGT_ILVL_ASIC_TX)
    ? 1 : -1];
#define HC_IRQ_SAVE(v)   do { (v) = (unsigned int)(PSW & 0xF000u);          \
        if ((v) < ((unsigned int)TGT_ILVL_CFG_CRIT << 12)) {                 \
            _bfld_(PSW, 0xF000u, (unsigned int)TGT_ILVL_CFG_CRIT << 12);     \
        }                                                                    \
        _nop_(); _nop_(); } while (0)
/* A plain read-modify-write of PSW is safe here: only a level-14/15 request
   can be accepted inside it, and RETI restores the PSW it interrupted. */
#define HC_IRQ_RESTORE(v) do {                                               \
        PSW = (unsigned int)((PSW & 0x0FFFu) | ((v) & 0xF000u)); } while (0)
#else
#define HC_IRQ_SAVE(v)   do { (v) = (unsigned int)IEN; IEN = 0; } while (0)
#define HC_IRQ_RESTORE(v) do { IEN = ((v) != 0u); } while (0)
#endif

/* The DESIRED image, in the battery-backed external SRAM.
 *
 * `huge` for the same measured reason hcconfig.c gives: the SMALL memory
 * model's default pointer is 16 bits and this lives at 0x385000. It is NOT a
 * near array - a 4096-byte object cannot exist in near RAM here, which has
 * 1792 bytes in total with the stack and every module's statics already in it.
 * The first version of this file declared `static unsigned char
 * s_staged_cfg[HC_CONFIG_TOTAL_SIZE]` with no memory qualifier, which the
 * linker cannot place; that it never failed to build is only because the file
 * was never compiled by any target.
 */
#define DESIRED  ((unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_CFGDESIRED))

unsigned int  hc_cfg_dirty_groups   = 0u;
unsigned int  hc_cfg_validation     = 0u;
/* 1 = the stored page did not VALIDATE at boot and the board defaults
   were seeded over it. Published, never silent. */
unsigned char hc_cfg_boot_fellback;
unsigned char hc_cfg_restart_pending = 0u;
unsigned int  hc_cfg_desired_rev    = 0u;
unsigned int  hc_cfg_active_rev     = 0u;
unsigned int  hc_cfg_apply_refused  = 0u;
unsigned char hc_cfg_migrated       = 0u;

/* ---------------------------------------------------------------- helpers */

/* Bounded seeded-page access, including one-byte serial reply jobs. */
unsigned char HC_COLD hc_cfg_mgr_peek_u8(unsigned int off)
{
    if (off >= HC_CFG_SIZE) {
        return 0u;
    }
    return DESIRED[(unsigned long)off];
}

static void des_set_u8(unsigned int off, unsigned char v)
{
    if (off < HC_CFG_SIZE) {
        DESIRED[(unsigned long)off] = v;
    }
}

/* True when any RESTART_REQUIRED field still differs between the two images.
 *
 * Recomputed rather than latched: a tuner who types a new cylinder count and
 * then types the old one back has no pending restart, and a sticky flag would
 * tell them otherwise for the rest of the session. */
static void recompute_restart_pending(void)
{
    unsigned int i, b;
    const hc_cfg_slot_t *s;

    hc_cfg_restart_pending = 0u;
    for (i = 0u; i < HC_CFG_SLOT_COUNT; i++) {
        if ((i & 15u) == 0u) {
            hcts_target_yield();        /* see hc_cfg_mgr_apply_now() */
        }
        s = &hc_cfg_slots[i];
        if (s->policy != (unsigned char)HC_APPLY_RESTART) {
            continue;
        }
        for (b = 0u; b < s->size; b++) {
            if (hc_cfg_mgr_peek_u8(s->offset + b) != hc_cal_u8(s->offset + b)) {
                hc_cfg_restart_pending = 1u;
                return;
            }
        }
    }
}

/* ------------------------------------------------------- schema migration
 *
 * THE SEAM, and it is deliberately a seam and not a framework.
 *
 * hcconfig.h's CFG_UNIVERSAL_BASE region was reserved-and-zero in every image
 * built before this one, so a page restored from the battery-backed SRAM of an
 * ECU that ran one of those has a universal block full of zeroes: no magic, no
 * schema, every physical pin reading 0 - which is not HC_PIN_NONE and is not a
 * pin either. Reading that as configuration would produce a confident,
 * completely wrong answer, so hc_validate() refuses it outright on the magic.
 *
 * Migrating it means seeding it, once, with the defaults below. That is the
 * whole of "schema version 0 -> 1". Future migrations belong here too, one
 * `if` per step, oldest first - and a migration that cannot be performed must
 * fall back to defaults rather than guess, exactly as hc_cfg_init() already
 * does when the stored checksum does not match.
 *
 * NOTHING HERE INVENTS A PIN. Every physical-pin field is seeded to
 * HC_PIN_NONE. A pin number is a claim about a specific loom on a specific
 * ECU, and the only place in this firmware allowed to make that claim is a
 * preset with provenance - see hc_presets.c.
 *
 * AND THEN THE BOARD'S OWN DEFAULT PRESET IS APPLIED OVER THE TOP, WHICH IS
 * NOT A CONTRADICTION OF THE PARAGRAPH ABOVE.
 *
 * It used to end there, and the result was a fresh page whose pinCrank read
 * 0xFF. hc_validate() refuses any syncMode above NONE without a crank pin, so
 * a defaulted or migrated ECU could not run until somebody typed 82 into
 * TunerStudio - and 82 is not a number a tuner can be expected to know. It is
 * a property of THIS BOARD, this repository has the evidence for it, and
 * withholding it is not caution: it ships an ECU that does not work out of
 * the box and calls that a safety property.
 *
 * The distinction that matters is WHERE THE CLAIM COMES FROM. This function
 * still invents nothing. hc_preset_board_default_id() returns the id of the
 * preset that names THIS image's descriptor and is marked as its board
 * default, every value in it carries a source string in
 * tools/config_source/hanicore_presets.py, and me711_preset_routing_proof
 * fails the build if any of them names a cavity whose circuit cannot do the
 * job. A board with no such preset gets 0 and the old behaviour exactly.
 *
 * It is applied LAST so it overrides the HC_PIN_NONE sweep above, and BEFORE
 * the header, so a reset in the middle still leaves a block that reads as
 * absent rather than half-seeded.
 */
static void seed_universal_defaults(void)
{
    unsigned int i;

    /* Every physical-pin field: unassigned. */
    hc_cal_set_u8(CFG_U_PIN_CRANK, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_CAM1, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_CAM2, HC_PIN_NONE);
    for (i = 0u; i < HC_MAX_CYL_UNIVERSAL; i++) {
        hc_cal_set_u8((unsigned int)(CFG_U_PIN_INJ + i), HC_PIN_NONE);
        hc_cal_set_u8((unsigned int)(CFG_U_PIN_IGN + i), HC_PIN_NONE);
        /* Bank 1 for every cylinder: an inline engine is right and a V engine
           is a preset or a tuner edit away. Zero would mean "no bank", which
           no cylinder can be. */
        hc_cal_set_u8((unsigned int)(CFG_U_CYL_BANK + i), HC_BANK_1);
    }
    hc_cal_set_u8(CFG_U_PIN_MAP, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_BARO, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_CLT, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_IAT, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_TPS1, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_TPS2, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_APP1, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_APP2, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_VBAT, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_OIL_PRESS, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_FUEL_PRESS, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_FLEX, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_MAF, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_LAMBDA1, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_LAMBDA2, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_MAIN_RELAY, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_FUEL_PUMP, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_TACHO, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_BOOST, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_CAM1_SOL, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_CAM2_SOL, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_LAUNCH, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_FLATSHIFT, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_ANTILAG, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_PITLIM, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_MAPSWITCH, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_PIN_VSS, HC_PIN_NONE);
    hc_cal_set_u8(CFG_U_TEST_PIN, HC_PIN_NONE);
    for (i = 0u; i < HC_N_GENERIC_IO; i++) {
        hc_cal_set_u8((unsigned int)(CFG_U_PIN_GEN_AIN + i), HC_PIN_NONE);
        hc_cal_set_u8((unsigned int)(CFG_U_PIN_GEN_PWM + i), HC_PIN_NONE);
        hc_cal_set_u8((unsigned int)(CFG_U_PIN_GEN_OUT + i), HC_PIN_NONE);
    }

    /* Strategy: the safest thing that is still a real engine. Batch fuel and
       paired wasted spark need crank position only, so a first start does not
       depend on cam geometry nobody has proven yet. */
    hc_cal_set_u8(CFG_U_INJ_STRATEGY, HC_INJ_BATCH);
    hc_cal_set_u8(CFG_U_IGN_STRATEGY, HC_IGN_WASTED_PAIRED);
    hc_cal_set_u8(CFG_U_SYNC_MODE, HC_SYNC_NONE);
    hc_cal_set_u8(CFG_U_TRIG_DECODER, HC_TRIGDEC_MISSING_TOOTH);

    /* Dual-track models. Both tracks of the ME7.5 throttle really do move in
       opposite directions and its I/O map says so, which is why OPPOSITE is
       the default - but it is a default, not an assumption the code makes. */
    hc_cal_set_u8(CFG_U_TPS_CORR, HC_TRACK_OPPOSITE);
    hc_cal_set_u8(CFG_U_APP_CORR, HC_TRACK_OPPOSITE);
    hc_cal_set_u16(CFG_U_TPS_TOL_X10, 100u);   /* 10.0 % */
    hc_cal_set_u16(CFG_U_APP_TOL_X10, 100u);

    /* Lambda: both channels OFF. An unproven controller must not come up live. */
    hc_cal_set_u8(CFG_U_LAM1_SRC, HC_LAMBDA_OFF);
    hc_cal_set_u8(CFG_U_LAM2_SRC, HC_LAMBDA_OFF);
    hc_cal_set_u8(CFG_U_LAM1_BANK, HC_BANK_1);
    hc_cal_set_u8(CFG_U_LAM2_BANK, HC_BANK_2);
    hc_cal_set_u8(CFG_U_LAM1_AUTH, 0u);
    hc_cal_set_u8(CFG_U_LAM2_AUTH, 0u);
    hc_cal_set_u16(CFG_U_LAM1_CYLMASK, 0u);
    hc_cal_set_u16(CFG_U_LAM2_CYLMASK, 0u);
    /* Gasoline. The ONE place AFR and lambda are related; every internal
       target is lambda and AFR is a display conversion through this. */
    hc_cal_set_u16(CFG_U_STOICH_X100, 1470u);

    /* Motorsport: every domain disarmed. */
    hc_cal_set_u16(CFG_U_MS_ENABLE, 0u);
    hc_cal_set_u16(CFG_U_LAUNCH_RPM, 0u);
    hc_cal_set_u16(CFG_U_LAUNCH_RETARD_X10, 0u);
    hc_cal_set_u16(CFG_U_FLATSHIFT_RPM, 0u);
    hc_cal_set_u16(CFG_U_FLATSHIFT_CUT_MS, 0u);
    hc_cal_set_u16(CFG_U_ANTILAG_RETARD_X10, 0u);
    hc_cal_set_u8(CFG_U_ANTILAG_FUEL_PCT, 0u);
    hc_cal_set_u8(CFG_U_PITLIM_RPM_PAD, 0u);
    hc_cal_set_u16(CFG_U_PITLIM_RPM, 0u);

    /* Protection thresholds off until a sensor is routed and a number chosen.
       A non-zero oil pressure limit with no sensor would cut the engine. */
    hc_cal_set_u16(CFG_U_OILP_MIN_KPA, 0u);
    hc_cal_set_u16(CFG_U_OILP_MIN_RPM, 0u);
    hc_cal_set_u16(CFG_U_CLT_MAX_X10, 0u);

    /* Bench test: off, and with a timeout that cannot be zero. A bench test
       that cannot time out is a stuck injector. */
    hc_cal_set_u8(CFG_U_TEST_MODE, HC_TEST_NONE);
    hc_cal_set_u16(CFG_U_TEST_VALUE, 0u);
    hc_cal_set_u16(CFG_U_TEST_TIMEOUT_MS, 2000u);

    /* Component data: unknown, because no datasheet exists in the tree. */
    hc_cal_set_u8(CFG_U_ENGINE_PRESET, 0u);
    hc_cal_set_u8(CFG_U_INJECTOR_PRESET, 0u);
    hc_cal_set_u8(CFG_U_COIL_PRESET, 0u);
    hc_cal_set_u8(CFG_U_MAP_PRESET, 0u);
    hc_cal_set_u16(CFG_U_INJ_FLOW_CCMIN, 0u);
    hc_cal_set_u16(CFG_U_INJ_REF_KPA, 0u);
    hc_cal_set_u16(CFG_U_CRANK_DWELL_X100, 400u);   /* 4.00 ms, cranking */
    hc_cal_set_u16(CFG_U_DISPLACEMENT_CC, 0u);
    for (i = 0u; i < (HC_MAX_CYL_UNIVERSAL - HC_MAX_CYL); i++) {
        hc_cal_set_u16((unsigned int)(CFG_U_TDC_CYL_EXT + 2u * i), 0u);
    }

    /* Ignition timing mode: DYNAMIC, and the fixed angle at a value that is
       safe to command by accident. A page that defaulted to FIXED would hold
       one angle at every speed the first time an engine turned, which is the
       one thing this mode must never do unasked. */
    hc_cal_set_u8(CFG_U_TIMING_MODE, 0u);           /* the map */
    hc_cal_set_u8(CFG_U_IGN_PAD, 0u);
    hc_cal_set_u16(CFG_U_FIXED_TIMING_X10, 100u);   /* 10.0 deg BTDC */

#if defined(TGT_ENGINE_RUNTIME)
    /* THE ENGINE MODEL BLOCK (hcengctl711.c). A fresh page gets the
       references' own defaults where one exists, and OFF where a function
       acts on the engine (closed loop, motorsport). */
    {
        static const unsigned char mapest_col[8] = {
            35u, 45u, 55u, 70u, 85u, 95u, 100u, 100u };
        static const unsigned int prime_mg[8] = {      /* rusEFI primeValues */
            800u, 420u, 200u, 105u, 62u, 47u, 45u, 45u };
        unsigned int r;

        hc_cal_set_u8(CFG_U_FIRING_ORDER, 0u);      /* custom: the TDC angles */
        hc_cal_set_u8(CFG_U_ALPHAN_IAT, 0u);
        hc_cal_set_u8(CFG_U_IGN_LOAD_MODE, 0u);
        hc_cal_set_u8(CFG_U_LAM_LOAD_MODE, 0u);
        for (i = 0u; i < CAL_AXIS_N; i++) {         /* lambda axes = ignition's */
            hc_cal_set_u16((unsigned int)(CFG_U_LAM_RPM_AX + 2u * i),
                           hc_cal_u16((unsigned int)(CAL_IGN_RPM_AX + 2u * i)));
            hc_cal_set_u16((unsigned int)(CFG_U_LAM_LOAD_AX + 2u * i),
                           hc_cal_u16((unsigned int)(CAL_IGN_LOAD_AX + 2u * i)));
        }
        for (i = 0u; i < 8u; i++) {
            hc_cal_set_u16((unsigned int)(CFG_U_MAPEST_RPM_AX + 2u * i),
                           (unsigned int)(800u + 900u * i));
            hc_cal_set_u16((unsigned int)(CFG_U_INJ_PHASE_RPM_AX + 2u * i),
                           (unsigned int)(800u + 900u * i));
            hc_cal_set_u16((unsigned int)(CFG_U_PRIME_MG + 2u * i),
                           (unsigned int)(prime_mg[i] * 10u));
        }
        {
            static const unsigned int tps_ax[8] = {
                0u, 50u, 100u, 200u, 350u, 500u, 750u, 1000u };
            static const unsigned int load_ax[8] = {
                200u, 400u, 600u, 800u, 1000u, 1300u, 1700u, 2200u };
            for (i = 0u; i < 8u; i++) {
                hc_cal_set_u16((unsigned int)(CFG_U_MAPEST_TPS_AX + 2u * i),
                               tps_ax[i]);
                hc_cal_set_u16((unsigned int)(CFG_U_INJ_PHASE_LOAD_AX + 2u * i),
                               load_ax[i]);
                for (r = 0u; r < 8u; r++) {
                    hc_cal_set_u8((unsigned int)(CFG_U_MAPEST + i * 8u + r),
                                  mapest_col[i]);
                    hc_cal_set_u16((unsigned int)(CFG_U_INJ_PHASE
                                                  + 2u * (i * 8u + r)),
                                   cfg_u16(CFG_INJ_START_DEG_X10));
                }
            }
        }
        hc_cal_set_u8(CFG_U_PRIME_DELAY, 5u);       /* 0.5 s: pump pressure */
        hc_cal_set_u8(CFG_U_DFCO_DELAY, 3u);        /* 0.3 s */
        hc_cal_set_u16(CFG_U_DFCO_MIN_CLT, 10600u); /* 60 C */
        hc_cal_set_u8(CFG_U_DFCO_MAP_MAX, 0u);
        hc_cal_set_u8(CFG_U_DFCO_RETARD, 0u);
        hc_cal_set_u8(CFG_U_DFCO_RAMP, 0u);
        hc_cal_set_u8(CFG_U_STFT_ENABLE, 0u);       /* off until a sensor is */
        hc_cal_set_u8(CFG_U_STFT_DELAY, 30u);
        hc_cal_set_u16(CFG_U_STFT_MIN_CLT, 10600u);
        hc_cal_set_u16(CFG_U_STFT_IDLE_RPM, 1000u); /* rusEFI stft defaults */
        hc_cal_set_u8(CFG_U_STFT_OVR_LOAD, 35u);
        hc_cal_set_u8(CFG_U_STFT_PWR_LOAD, 85u);
        hc_cal_set_u8(CFG_U_STFT_DEADBAND, 5u);     /* 0.5 % */
        hc_cal_set_u8(CFG_U_STFT_LAM_MIN, 82u);     /* AFR 12 */
        hc_cal_set_u8(CFG_U_STFT_LAM_MAX, 116u);    /* AFR 17 */
        hc_cal_set_u8(CFG_U_STFT_AFTER_DFCO, 20u);
        hc_cal_set_u8(CFG_U_STFT_AFTER_AE, 10u);
        for (i = 0u; i < 4u; i++) {
            hc_cal_set_u8((unsigned int)(CFG_U_STFT_ADD + i), 10u);
            hc_cal_set_u8((unsigned int)(CFG_U_STFT_REMOVE + i), 10u);
            hc_cal_set_u8((unsigned int)(CFG_U_STFT_TAU + i), 10u);   /* 1 s */
        }
        hc_cal_set_u8(CFG_U_REVLIM_HYST, 20u);      /* 200 rpm, as V93 */
        hc_cal_set_u8(CFG_U_REVLIM_SOFT_RETARD, 0u);
        hc_cal_set_u8(CFG_U_REVLIM_SOFT_FUEL, 0u);
        hc_cal_set_u8(CFG_U_INJ_PHASE_MODE, 0u);
        hc_cal_set_u8(CFG_U_IDLE_ETB_RANGE, 0u);
        /* the biased temperatures IN RANGE (10*C + 10000) - a raw 0
           is -1000 C in TunerStudio, outside each field's own limits */
        hc_cal_set_u16(CFG_U_ALS_CLT_MIN, 10000u);   /* 0 C               */
        hc_cal_set_u16(CFG_U_ALS_CLT_MAX, 11200u);   /* 120 C             */
        hc_cal_set_u16(CFG_U_VVT_MIN_CLT, 10000u);   /* 0 C               */
        hc_cal_set_u16(CFG_U_KNOCK_CLT_MIN, 10400u); /* 40 C, Bosch TMKR  */
        /* the cam pattern tolerance inside its own 2..40 deg limits: 0 made
           every PATTERN wheel unusable and the Burn was refused */
        hc_cal_set_u8(CFG_U_CAM_TOOTH_TOL, 10u);
        for (i = 0u; i < 8u; i++) {                  /* -20..120 C        */
            hc_cal_set_u16((unsigned int)(CFG_U_IGN_IAT_AX + 2u * i),
                           (unsigned int)(9800u + 200u * i));
        }
    }
#endif

    /* THE BOARD'S OWN DEFAULT ROUTING. See the header comment for why this
       is not "inventing a pin": every value carries provenance and is gated
       against the hardware descriptor by me711_preset_routing_proof. Returns
       0 on a board that declares no default, and applies nothing. */
    (void)hc_preset_apply_engine_active(hc_preset_board_default_id());

    /* The header LAST, so a reset in the middle of this leaves a block that
       still reads as absent rather than one that reads as valid and is half
       written. Same discipline a flash commit marker will need. */
    hc_cal_set_u16(CFG_U_GENERATION, 0u);
    hc_cfg_v102_defaults();
    hc_cal_set_u16(CFG_U_CRC, 0u);
    hc_cal_set_u16(CFG_U_SCHEMA, HC_UNIVERSAL_SCHEMA);
    hc_cal_set_u16(CFG_U_MAGIC, HC_UNIVERSAL_MAGIC);
}

/* V101 migration changes only newly owned bytes and schema identity. */
void hc_cfg_v102_defaults(void)
{
    unsigned int i;
    static const unsigned int defaults[13] = {1013u,50u,250u,3600u,100u,2000u,200u,2500u,200u,600u,100u,300u,1000u};
    for(i=CFG_U_FUEL_MODEL;i<CFG_U_PRESSURE_REF;i++) hc_cal_set_u8(i,0u);
    for(i=0;i<13u;i++) hc_cal_set_u16((unsigned int)(CFG_U_PRESSURE_REF+2u*i),defaults[i]);
#if defined(TGT_DEADLINE_EXECUTOR)
    /* Installation fact only; Legacy still uses CAL_LOAD_SOURCE unchanged. */
    hc_cal_set_u8(CFG_U_PRESSURE_ROLE,2u);
#endif
    /* The two throttle words appended after the fuel-model block. A V101
       page has zero there, and a 0 Hz bridge frequency is refused by
       hc_validate(), so a migrated page fell back to the board default.
       2000 Hz is the board default's own value; friction 0 = off. */
    hc_cal_set_u16(CFG_U_DBW_PWM_HZ,2000u);
    hc_cal_set_u16(CFG_U_DBW_FRICTION_X10,0u);
}
unsigned char hc_cfg_identity_known(unsigned int hi,unsigned int lo,unsigned int schema)
{
    return (unsigned char)((hi==(unsigned int)(HC_CFG_LAYOUT_ID>>16) && lo==(unsigned int)HC_CFG_LAYOUT_ID && schema==HC_UNIVERSAL_SCHEMA)
        || (hi==(unsigned int)(HC_V101_LAYOUT>>16) && lo==(unsigned int)HC_V101_LAYOUT && schema==HC_V101_SCHEMA));
}
unsigned char hc_cfg_page_known(void)
{
    unsigned int schema=hc_cal_u16(CFG_U_SCHEMA);
    return (unsigned char)(hc_cal_u16(CFG_U_MAGIC)==HC_UNIVERSAL_MAGIC
        && (schema==HC_UNIVERSAL_SCHEMA || schema==HC_V101_SCHEMA));
}
unsigned char hc_cfg_migrate_v101(void)
{
    if(hc_cal_u16(CFG_U_MAGIC)!=HC_UNIVERSAL_MAGIC || hc_cal_u16(CFG_U_SCHEMA)!=HC_V101_SCHEMA) return 0u;
    hc_cfg_v102_defaults();
    /* V101 never persisted physical sensor role. Migration cannot infer an
       installation from its cavity number. Legacy arithmetic is unchanged;
       commission an explicit role before selecting a new pressure model. */
    hc_cal_set_u8(CFG_U_PRESSURE_ROLE,0u);
    hc_cal_set_u16(CFG_U_CRC,0u);
    hc_cal_set_u16(CFG_U_SCHEMA,HC_UNIVERSAL_SCHEMA);
    hc_cfg_migrated=1u;
    hc_cfg_commit();
    return 1u;
}
/* Unknown semantic identity is never reinterpreted as an older calibration. */
static unsigned char migrate_active(void)
{
    if (hc_cal_u16(CFG_U_MAGIC) == HC_UNIVERSAL_MAGIC
        && hc_cal_u16(CFG_U_SCHEMA) == HC_UNIVERSAL_SCHEMA) {
        return 0u;
    }
    if(hc_cfg_migrate_v101()) return 1u;
    if(hc_cfg_source==0u || hc_cfg_source==2u) { seed_universal_defaults(); return 1u; }
    return 0u; /* validation refuses unknown retained/flash semantics */
}

/* ------------------------------------------------- the DESIRED image copy
 *
 * WHY THIS IS NOT A LOOP IN hc_cfg_mgr_init().
 *
 * DESIRED starts as a byte-for-byte copy of ACTIVE - 4096 bytes. Done in the
 * boot path that cost 69 587 emulated steps, and MEASURED against V27A in the
 * simulator it pushed the FIRST ASIC EXCHANGE from step 1 270 901 to
 * 1 340 488: twenty-seven milliseconds later. On this ECU that is not a
 * cosmetic number. Every failure this project has chased on real hardware has
 * been the S5500 supervision being starved, and the boot path is the last
 * place to spend 27 ms because a memcpy was written where it was convenient.
 *
 * So the copy is SPREAD. hc_cfg_mgr_service() moves one chunk per main-loop
 * pass; at HC_SEED_CHUNK bytes a pass it is finished inside a handful of
 * milliseconds of loop time, none of it in the boot path, and no single pass
 * holds the loop for more than a chunk.
 *
 * CORRECTNESS DOES NOT DEPEND ON THE SPREADING FINISHING FIRST. Every host
 * access and every apply calls seed_finish() before it looks at DESIRED, so a
 * TunerStudio read that arrives during the first millisecond gets the fully
 * copied image - it just pays for the remainder itself, once. In practice the
 * host cannot arrive that early: TunerStudio's own detection takes seconds.
 */
/* MEASURED, and 64 was TRIED AND IS WORSE - which is worth writing down,
   because "smaller chunk = smoother" is the obvious wrong answer here.

   A host page read calls seed_finish(), which completes whatever is left of
   the copy IN ONE PASS, because a read has to return the whole DESIRED image
   and cannot return half of it. So the chunk size does not bound the worst
   case; it decides how much is still OUTSTANDING when a host request lands.
   Bigger chunks finish the seeding sooner and make seed_finish() a no-op by
   the time TunerStudio asks for anything.

   At 256: me711_ts_gap_proof reports a 7 ms worst gap on all four
   transactions. At 64: the calibration page read jumps to 22 ms, well past
   the 10 ms S5500 raster, because the read now arrives mid-seed. */
#define HC_SEED_CHUNK  256u

static unsigned int  seed_at;      /* next byte to copy */
static unsigned char seed_done;

/* The copy is bounded, but "bounded" is not the same as "short enough". Every
   byte is a huge-pointer read out of external SRAM and a huge-pointer write
   back, and a 256-byte span costs about 3 ms - measured: with this loop
   running blind, me711_ts_gap_proof reported a 7 ms worst service gap where
   V26 and V27A both report 4 ms, against a 10 ms S5500 raster.

   So it yields, the same way every bounded wait in hcts.c does. The hook
   services the ASIC exchange, which is the only thing in this system that
   must not be made to wait. HC_SEED_YIELD is the stride: small enough that no
   uninterrupted run of copying approaches the raster, large enough that the
   call overhead does not dominate the copy. */
#define HC_SEED_YIELD  32u

static void seed_span(unsigned int from, unsigned int to)
{
    unsigned int i;

    for (i = from; i < to; i++) {
        if ((i % HC_SEED_YIELD) == 0u) {
            hcts_target_yield();
        }
        DESIRED[(unsigned long)i] = hc_cal_u8(i);
    }
}

/* Copy whatever is left, now. Cheap once the spreading has finished. */
static void seed_finish(void)
{
    if (seed_done) {
        return;
    }
    seed_span(seed_at, HC_CFG_SIZE);
    seed_at = HC_CFG_SIZE;
    seed_done = 1u;
}

/* One chunk. Returns 1 while there is still work to do. */
static unsigned char seed_progress(void)
{
    unsigned int end;

    if (seed_done) {
        return 0u;
    }
    end = seed_at + HC_SEED_CHUNK;
    if (end > HC_CFG_SIZE) {
        end = HC_CFG_SIZE;
    }
    seed_span(seed_at, end);
    seed_at = end;
    if (seed_at >= HC_CFG_SIZE) {
        seed_done = 1u;
        return 0u;
    }
    return 1u;
}

/* ------------------------------------------------------------- lifecycle */

void hc_cfg_mgr_init(void)
{
    if(migrate_active()) hc_cfg_migrated = 1u;

    /* ============================ THE RESTORED PAGE IS VALIDATED, NOT JUST
     * CHECKSUMMED.
     *
     * hc_cfg_init() accepts a page out of the battery-backed SRAM on four
     * tests - magic, version, size and checksum - and hc_nvm_boot() accepts a
     * flash record on its own magic, layout id, length and two CRC16s. Every
     * one of those asks "are these bytes intact". NONE of them asks "does this
     * configuration describe something that can run", and until V64 nothing
     * did until a host tried to apply an edit.
     *
     * So an ECU could come up on a STRUCTURALLY PERFECT page that hc_validate()
     * would refuse - a crank pin on a cavity with no capture unit, two
     * position inputs on one channel, a sequential strategy with no cycle -
     * and say nothing at all. It would simply never run, and the reason was
     * one apply away from being visible.
     *
     * The floor beneath it is safe because V61 made it so: the board default
     * is a RUNNABLE configuration rather than an inert one, so falling back to
     * it leaves an ECU that answers, syncs and can be re-tuned.
     *
     * WHAT THIS IS NOT, and the rest is recorded in the V64 evidence: it does
     * NOT yet walk back through older stored generations looking for the
     * newest one that validates. The append-only store already keeps eighty
     * of them and nvm_scan() already falls to the next-newest on a CRC
     * failure; extending that to a SEMANTIC failure is the other half and it
     * needs code space this image does not have.
     *
     * COST: one hc_validate() pass in the boot path. Measured elsewhere at
     * about 5 ms - the V57 refused-apply measurement puts a full 4096-byte
     * validation at roughly that - against the ~310 ms the supervisor allows a
     * quiet CPU. It is behind the same tick-gated yield every other long boot
     * operation uses. */
    hc_cfg_boot_fellback = 0u;
    if (hc_validate(HC_VAL_SRC_ACTIVE) != HC_VAL_OK) {
        seed_universal_defaults();
        hc_cfg_boot_fellback = 1u;
    }

    /* ACTIVE is whatever hc_cfg_init() decided - a burned page out of the
       battery-backed SRAM, or the built-in defaults - plus any migration the
       line above had to perform. DESIRED starts as an exact copy of it, so
       nothing is dirty at boot and the first thing the host reads is the
       truth.
     *
     * WHY THIS IS TWO POINTER LOOPS AND NOT `for (i) DESIRED[i] =
     * hc_cal_u8(i)`. MEASURED, in the simulator, against the V27a image: the
     * obvious version costs 131 000 emulated steps, which at the 2520
     * steps/ms this firmware runs at is FIFTY-TWO MILLISECONDS added to every
     * boot - a call, a range test and a 24-bit index computation, 4096 times.
     * This ECU's whole history is starvation resets, and boot is not the place
     * to spend 52 ms because a copy was written the lazy way. Pointer
     * increments over a `huge` pointer are a byte move and an add.
     *
     * The split at HC_CFG_CORE is hcconfig's, not a new one: below it the
     * page lives in the near array hc_cfg[], above it it is already in this
     * same external SRAM chip, so the second loop is SRAM to SRAM.
     */
    /* The copy is NOT done here. See seed_progress below: doing it in the
       boot path put the first ASIC exchange 27 ms later, MEASURED, and this
       ECU's entire failure history is supervision starvation. */
    seed_done = 0u;
    seed_at = 0u;

    hc_cfg_dirty_groups = 0u;
    hc_cfg_restart_pending = 0u;
    hc_cfg_apply_refused = 0u;
    hc_cfg_desired_rev = 0u;
    hc_cfg_active_rev = 0u;
    /* Validation reads DESIRED, so it waits for the copy. The main loop
       reaches hc_cfg_mgr_validate() long before any host does. */
    hc_cfg_validation = HC_VAL_OK;
}

/* ------------------------------------------------------------ host access */

unsigned char hc_cfg_mgr_read_u8(unsigned int off)
{
    seed_finish();
    return hc_cfg_mgr_peek_u8(off);
}

unsigned int hc_cfg_mgr_read_u16(unsigned int off)
{
    if (off + 1u >= HC_CFG_SIZE) {
        return 0u;
    }
    return (unsigned int)(((unsigned int)hc_cfg_mgr_peek_u8(off) << 8) | hc_cfg_mgr_peek_u8(off + 1u));
}

void hc_cfg_mgr_write_u8(unsigned int off, unsigned char v)
{
    const hc_cfg_slot_t *s;

    if (off >= HC_CFG_SIZE) {
        return;
    }

    seed_finish();
    /* A byte equal in both views is not a new configuration. Transaction
       commit also uses this API to install staged LIVE values, so equality
       in DESIRED alone is insufficient: ACTIVE may still hold the old value. */
    if(hc_cfg_mgr_peek_u8(off) == v && hc_cal_u8(off) == v) return;
    des_set_u8(off, v);
    hc_cfg_desired_rev++;
#if defined(TGT_ENGINE_RUNTIME)
    /* a VE cell written (Tune Analyze Live) holds the closed loop for
       20 s, rusEFI isTuningVeNow() - the two must not fight. */
    if (off >= CAL_FUEL_MAP
        && off < (unsigned int)(CAL_FUEL_MAP + 2u * CAL_MAP_N)) {  /* u16 */
        hc_ec_ve_written();
    }
#endif

    s = hc_cfg_slot_at(off);
    if (s == (const hc_cfg_slot_t *)0) {
        /* A reserved byte. It is part of the page, the host may write it, and
           it means nothing to anybody. Deliberately NOT treated as LIVE: a
           reserved byte that reached the active image would become a silent
           dependency the moment the region is given a meaning. */
        return;
    }

    /* ANY NEW BYTE CAN CHANGE THE ANSWER, so any write unblocks a refused
       transaction - not only an RPM_ZERO one. V79 measured the hole on the
       ECU: pinMainRelay = 23 written with the mode still OFF was refused
       (PIN_CAP at offset 73, the mode), and writing mode AUTO - a LIVE field
       - fixed DESIRED but left it BLOCKED for ever. Still at most one
       re-validation per pass, and only after a write. */
    hc_cfg_dirty_groups &= (unsigned int)~HC_CFG_DIRTY_BLOCKED;

    switch (s->policy) {
    case (unsigned char)HC_APPLY_LIVE:
        /* Calibration. One byte, straight across.

           No whole-configuration validation here. The first version called
           hc_validate() on every single byte written, which for a 4096-byte
           page burn is 4096 full validations - each one walking cylinders,
           pins and duplicate checks - against a 10 ms supervision raster that
           is serviced from the main loop. Validation belongs at APPLY time,
           where it is a bounded once-per-transaction cost, and at commit. */
        hc_cal_set_u8(off, v);
        break;

    case (unsigned char)HC_APPLY_RPM_ZERO:
        /* Stage it. The dirty bit records that the GROUP has moved, not what
           moved in it: the apply copies whatever DESIRED holds at the time,
           which is what makes A->B->C->D apply D and never replay B or C.

           AND IT UNBLOCKS A REFUSED TRANSACTION. HC_CFG_DIRTY_BLOCKED says
           "this configuration has already been validated and refused"; a new
           write is the only thing that can change that answer, so it is the
           only thing that clears the bit. See hc_config_manager.h. */
        hc_cfg_dirty_groups |= (unsigned int)(1u << s->group);
        break;

    case (unsigned char)HC_APPLY_RESTART:
    default:
        /* Deliberately nothing. The active image is not touched, no group is
           marked dirty, and no RPM_ZERO pass will pick it up - the apply loop
           below skips any slot whose policy is not RPM_ZERO. That is the whole
           difference between "requires a restart" and "requires the engine to
           be stopped", and the first version of this file erased it by copying
           the entire 4096-byte staged image into the active page at RPM zero,
           restart-required fields included. */
        recompute_restart_pending();
        break;
    }
}

void hc_cfg_mgr_write_u16(unsigned int off, unsigned int v)
{
    hc_cfg_mgr_write_u8(off, (unsigned char)(v >> 8));
    hc_cfg_mgr_write_u8((unsigned int)(off + 1u), (unsigned char)(v & 0xFFu));
}

/* ------------------------------------------------------------- the apply */

unsigned int hc_cfg_mgr_apply_now(unsigned int rpm)
{
    unsigned int faults;
    unsigned int i, b;
    unsigned int ien;
    const hc_cfg_slot_t *s;

    if ((hc_cfg_dirty_groups & (unsigned int)HC_CFG_DIRTY_GROUPS) == 0u) {
        return HC_VAL_OK;
    }
    if (rpm != 0u) {
        return HC_VAL_FAULT_NOT_STOPPED;
    }
    seed_finish();

    /* Validate the WHOLE desired configuration, not just the dirty group. A
       group is only sound in the context of the rest: an injector routing is
       valid or not depending on the cylinder count, and the sync requirement
       depends on the execution strategy in another group entirely. */
    faults = hc_validate(HC_VAL_SRC_DESIRED);
    hc_cfg_validation = faults;
    if (faults != HC_VAL_OK) {
        /* ACTIVE is untouched and the dirty mask is KEPT, so the tuner can fix
           the problem and the same transaction applies. Losing the staged
           edits here would be a worse failure than not applying them.

           BUT THE ANSWER IS NOW REMEMBERED. hc_validate() walks every
           cylinder, every pin and every duplicate check over the whole
           4096-byte DESIRED image; running it again on the next main-loop
           pass, against the same bytes, can only produce the same faults.
           See hc_config_manager.h for what that cost, measured. */
        hc_cfg_apply_refused++;
        hc_cfg_dirty_groups |= (unsigned int)HC_CFG_DIRTY_BLOCKED;
        return faults;
    }

    for (i = 0u; i < HC_CFG_SLOT_COUNT; i++) {
        /* V82. THE APPLY WAS ~6 ms WITHOUT A YIELD. Measured in c167sim
           (tools/me711_pinwrite_gap_proof.py): one injector-routing write
           left a 6.0 ms gap between S5500 services on V80 and V82 alike, and
           when the apply shares a main-loop pass with a frame build the gap
           reached 8.1-8.3 ms of the 10 ms budget; the real ECU logged ~4
           asicTimeouts per 12 such writes. Tick-gated, between fields only -
           never inside the interrupt-off copy of one field below. */
        if ((i & 15u) == 0u) {
            hcts_target_yield();
        }
        s = &hc_cfg_slots[i];
        if (s->policy != (unsigned char)HC_APPLY_RPM_ZERO) {
            continue;                       /* LIVE is already across;
                                               RESTART must never be */
        }
        if ((hc_cfg_dirty_groups & (unsigned int)(1u << s->group)) == 0u) {
            continue;
        }
        /* One field at a time, with interrupts held off across the field.
           A field is the smallest thing the runtime reads as a unit - a u16
           angle, an eight-entry channel map - so a field torn in half is the
           observable defect, and a whole group copied under one long critical
           section would hold off the 10 ms supervision raster. */
        HC_IRQ_SAVE(ien);
        for (b = 0u; b < s->size; b++) {
            hc_cal_set_u8(s->offset + b, hc_cfg_mgr_peek_u8(s->offset + b));
        }
        HC_IRQ_RESTORE(ien);
    }

    hc_cfg_dirty_groups = 0u;
    hc_cfg_active_rev++;
    recompute_restart_pending();
    return HC_VAL_OK;
}

unsigned char hc_cfg_mgr_seed_step(void)
{
    return seed_progress();
}

void hc_cfg_mgr_service(unsigned int rpm)
{
    /* The seeding is NOT driven from here. See hc_cfg_mgr_seed_step(). */
    if ((hc_cfg_dirty_groups & (unsigned int)HC_CFG_DIRTY_GROUPS) == 0u) {
        return;
    }
    if (rpm != 0u) {
        /* Deliberately WITHOUT consuming the blocked bit: an edit made while
           the engine turned is picked up the moment it stops, exactly as
           before. */
        return;
    }
    if ((hc_cfg_dirty_groups & (unsigned int)HC_CFG_DIRTY_BLOCKED) != 0u) {
        return;         /* same bytes, same answer - see the header */
    }
    (void)hc_cfg_mgr_apply_now(rpm);
}

/* ------------------------------------------------------------- validation */

unsigned int hc_cfg_mgr_validate(void)
{
    seed_finish();
    hc_cfg_validation = hc_validate(HC_VAL_SRC_DESIRED);
    return hc_cfg_validation;
}

/* THE BURN PERSISTS WHAT TUNERSTUDIO SHOWS.
 *
 * MEASURED on V89 (c167sim, then the AWT's own page): APPLY preset 3 put
 * displacementCc 1781 in DESIRED - RESTART_REQUIRED, so correctly not in
 * ACTIVE - and the Burn validated DESIRED but persisted ACTIVE
 * (hc_cfg_commit() mirrors hc_cfg; hcnvm's staging copies hc_cal_u8). After
 * the key cycle both images read 0. Every restart-required value a tuner or a
 * preset had ever set was silently thrown away by the one act meant to keep
 * it, and the car ran alpha-N with a zero swept volume: no running fuel.
 *
 * With the engine STOPPED a Burn is now also the restart point: pending
 * engine-stopped groups are applied (the ordinary apply, whole DESIRED
 * validated first) and every RESTART_REQUIRED field is copied into ACTIVE,
 * field by field with interrupts held off, before the page is committed. A
 * stopped engine is exactly the state a restart would bring these up in, and
 * everything that caches geometry re-reads it on hc_cfg_active_rev. With the
 * engine TURNING the old behaviour stands - ACTIVE is burned and the restart
 * stays pending (hc_cfg_restart_pending, published) - because changing the
 * cylinder count under a running engine is what the class exists to stop. */
unsigned int hc_cfg_mgr_commit_burn(unsigned char stopped)
{
    unsigned int faults;
    unsigned int i, b;
    unsigned int ien;
    unsigned char moved = 0u;
    const hc_cfg_slot_t *s;

    seed_finish();
    faults = hc_validate(HC_VAL_SRC_DESIRED);
    hc_cfg_validation = faults;
    if (faults != HC_VAL_OK) {
        return faults;
    }
    if (stopped) {
        if ((hc_cfg_dirty_groups & (unsigned int)HC_CFG_DIRTY_GROUPS) != 0u) {
            hc_cfg_dirty_groups &= (unsigned int)~HC_CFG_DIRTY_BLOCKED;
            faults = hc_cfg_mgr_apply_now(0u);
            if (faults != HC_VAL_OK) {
                return faults;
            }
        }
        for (i = 0u; i < HC_CFG_SLOT_COUNT; i++) {
            s = &hc_cfg_slots[i];
            if (s->policy != (unsigned char)HC_APPLY_RESTART) {
                continue;
            }
            HC_IRQ_SAVE(ien);
            for (b = 0u; b < s->size; b++) {
                if (hc_cfg_mgr_peek_u8(s->offset + b) != hc_cal_u8(s->offset + b)) {
                    hc_cal_set_u8(s->offset + b, hc_cfg_mgr_peek_u8(s->offset + b));
                    moved = 1u;
                }
            }
            HC_IRQ_RESTORE(ien);
        }
        if (moved) {
            hc_cfg_active_rev++;
            recompute_restart_pending();
        }
    }
    hc_cfg_commit();
    return HC_VAL_OK;
}

/* -------------------------------------- the Burn deferred to engine stop */
/* In the battery-backed SRAM (near XRAM is at its reserve): a Burn owed
   when the key went off is still owed - and still started - at the next
   stopped engine. */
typedef struct {
    unsigned char wait;             /* 1 = a flash Burn is owed             */
    unsigned char seen;             /* the stop has been seen once          */
    unsigned int  stop_ms;          /* when                                 */
    unsigned int  magic;            /* BURN_OWED_MAGIC with wait == 1: SRAM */
} hc_burn_defer_t;                  /* after a battery loss is random       */
#define BURN_OWED_MAGIC 0xB0D1u
#if defined(TGT_RAM_BURNDEFER)
#define BD (*(hc_burn_defer_t huge *)(TGT_EXTRAM_BASE + TGT_RAM_BURNDEFER))
typedef char hc_burn_defer_fits[(sizeof(hc_burn_defer_t)
                                 <= TGT_RAM_BURNDEFER_LIMIT) ? 1 : -1];
#else
static hc_burn_defer_t bd_ram;
#define BD bd_ram
#endif
#define burn_wait      BD.wait
#define burn_stop_seen BD.seen
#define burn_stop_ms   BD.stop_ms
#define burn_magic     BD.magic
#define burn_owed()    (burn_wait == 1u && burn_magic == BURN_OWED_MAGIC)

unsigned int hc_cfg_mgr_burn_defer(void)
{
    unsigned int faults = hc_cfg_mgr_commit();   /* validate + standby */
    if (faults == HC_VAL_OK) {
        burn_wait = 1u;
        burn_stop_seen = 0u;
        burn_magic = BURN_OWED_MAGIC;
    }
    return faults;
}

unsigned char hc_cfg_mgr_burn_due(unsigned int now_ms, unsigned char stopped)
{
    if (!burn_owed()) {
        burn_wait = 0u;             /* no ?C_INIT: anything else is "none" */
        burn_magic = 0u;
        return 0u;
    }
    if (!stopped) {
        burn_stop_seen = 0u;
        return 0u;
    }
    if (!burn_stop_seen) {
        burn_stop_seen = 1u;
        burn_stop_ms = now_ms;
        return 0u;
    }
    if ((unsigned int)(now_ms - burn_stop_ms) < HC_BURN_STOP_MS) {
        return 0u;
    }
    burn_wait = 0u;
    burn_magic = 0u;
    return 1u;
}

unsigned char hc_cfg_mgr_burn_pending(void)
{
    return (unsigned char)burn_owed();
}

unsigned int hc_cfg_mgr_commit(void)
{
    unsigned int faults;

    seed_finish();
    faults = hc_validate(HC_VAL_SRC_DESIRED);
    hc_cfg_validation = faults;
    if (faults != HC_VAL_OK) {
        return faults;
    }
    /* hc_cfg_commit() is hcconfig's own store. What it is worth on this
       hardware is documented at hc_cfg_persist_state() - it is battery-backed
       SRAM, not flash, and it does not survive a disconnected battery. */
    hc_cfg_commit();
    return HC_VAL_OK;
}

/* ------------------------------------------- the many-field transaction
 *
 * V86. See hc_config_manager.h. What it exists for is the engine preset:
 * before V86 a preset reached DESIRED field by field through
 * hc_cfg_mgr_write_u8(), so its LIVE calibration fields were in ACTIVE before
 * anybody had asked whether the page it built could run.
 *
 * THE LOG IS AN UNDO LOG, NOT A COPY OF THE PAGE. A copy would be 4096 bytes
 * moved twice per apply; the log holds the old DESIRED byte of every byte
 * actually staged, and a rollback replays it backwards so a byte staged
 * twice ends on its ORIGINAL value.
 *
 * THE LOG IS RUN-LENGTH. V86..V91 spent three bytes per staged byte
 * (offset high, offset low, old byte): 853 bytes in the 0xA00 region. The
 * V92 AWT preset carries the stock-derived ignition, lambda, warm-up and
 * pedal maps - 1604 bytes - so the transaction overflowed and '!E' refused
 * the preset with HC_VAL_FAULT_SCHEMA (me711_preset_apply_proof). A preset
 * is a few dozen contiguous runs (a table is one), so the log is now
 *
 *   data, growing UP from 0:     per run  off_hi off_lo len  old[len]
 *   run index, growing DOWN:     per run  the run header's position (2 bytes)
 *
 * one byte per staged byte plus five per run (len <= 255: a longer run is
 * split). The region is unchanged; the index is what lets the rollback walk
 * runs backwards. */
#ifndef TGT_RAM_PRESETUNDO
#error "hc_config_manager.c: this target has no TGT_RAM_PRESETUNDO region"
#endif
#define TXN_LOG  ((unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_PRESETUNDO))
/* 16-bit position arithmetic: this module is FAR code and Keil's long
   multiply helper is near. Every position is < TXN_LIM. */
#define TXN_LIM  ((unsigned int)TGT_RAM_PRESETUNDO_LIMIT)
#define TXN_AT(i) ((unsigned long)(unsigned int)(i))
#define TXN_IDX(r) ((unsigned int)(TXN_LIM - 2u - (unsigned int)((r) << 1)))

unsigned int  hc_cfg_txn_faults = 0u;
static unsigned int  txn_n;        /* bytes staged (the yield cadence)     */
static unsigned int  txn_pos;      /* next free data byte                  */
static unsigned int  txn_runs;     /* runs opened                          */
static unsigned int  txn_hdr;      /* the open run's header position       */
static unsigned int  txn_run_off;  /* the open run's first page offset     */
static unsigned int  txn_run_len;  /* the open run's length                */
static unsigned char txn_overflow;

static unsigned int txn_rd16(unsigned int pos)
{
    return (unsigned int)(((unsigned int)TXN_LOG[TXN_AT(pos)] << 8)
                          | TXN_LOG[TXN_AT(pos + 1u)]);
}

void hc_cfg_mgr_txn_begin(void)
{
    seed_finish();                 /* DESIRED must be whole before staging */
    txn_n = 0u;
    txn_pos = 0u;
    txn_runs = 0u;
    txn_run_len = 0u;
    txn_overflow = 0u;
}

void hc_cfg_mgr_txn_put_u8(unsigned int off, unsigned char v)
{
    /* MEASURED, V86 (tools/me711_preset_gap_proof.py): staging ~240 bytes
       of external SRAM through huge pointers with no yield left a 12.4 ms
       S5500 service gap against a 10 ms budget. Tick-gated, so the common
       case is one compare. */
    if ((txn_n & 15u) == 0u) {
        hcts_target_yield();
    }
    if (off >= HC_CFG_SIZE || txn_overflow) {
        /* Refuse the whole transaction rather than stage a value that could
           not be undone. */
        txn_overflow = 1u;
        return;
    }
    if (txn_runs != 0u && off == (unsigned int)(txn_run_off + txn_run_len)
        && txn_run_len < 255u) {
        /* Extends the open run: one data byte, below the index. */
        if ((unsigned int)(txn_pos + 1u) > TXN_IDX(txn_runs - 1u)) {
            txn_overflow = 1u;
            return;
        }
        txn_run_len++;
        TXN_LOG[TXN_AT(txn_hdr + 2u)] = (unsigned char)txn_run_len;
    } else {
        /* A new run: header + one data byte, and one index entry. */
        if (txn_runs >= (unsigned int)(TXN_LIM / 8u)
            || (unsigned int)(txn_pos + 4u) > TXN_IDX(txn_runs)) {
            txn_overflow = 1u;
            return;
        }
        txn_hdr = txn_pos;
        txn_run_off = off;
        txn_run_len = 1u;
        TXN_LOG[TXN_AT(TXN_IDX(txn_runs))]      = (unsigned char)(txn_hdr >> 8);
        TXN_LOG[TXN_AT(TXN_IDX(txn_runs) + 1u)] = (unsigned char)(txn_hdr & 0xFFu);
        txn_runs++;
        TXN_LOG[TXN_AT(txn_pos)]      = (unsigned char)(off >> 8);
        TXN_LOG[TXN_AT(txn_pos + 1u)] = (unsigned char)(off & 0xFFu);
        TXN_LOG[TXN_AT(txn_pos + 2u)] = 1u;
        txn_pos = (unsigned int)(txn_pos + 3u);
    }
    TXN_LOG[TXN_AT(txn_pos)] = hc_cfg_mgr_peek_u8(off);
    txn_pos++;
    txn_n++;
    des_set_u8(off, v);
}

unsigned int hc_cfg_mgr_txn_commit(unsigned int rpm)
{
    unsigned int faults;
    unsigned int r, h, o, j, len;

    if (txn_overflow) {
        faults = HC_VAL_FAULT_SCHEMA;
    } else if (rpm != 0u) {
        faults = HC_VAL_FAULT_NOT_STOPPED;
    } else {
        faults = hc_validate(HC_VAL_SRC_DESIRED);
    }
    hc_cfg_txn_faults = faults;

    if (faults != HC_VAL_OK) {
        /* Backwards, run by run and byte by byte, so the first-logged
           (original) byte wins. Nothing was marked dirty and nothing reached
           ACTIVE, so this is all. */
        r = txn_runs;
        while (r > 0u) {
            r--;
            hcts_target_yield();
            h = txn_rd16(TXN_IDX(r));
            o = txn_rd16(h);
            len = TXN_LOG[TXN_AT(h + 2u)];
            j = len;
            while (j > 0u) {
                j--;
                if ((j & 31u) == 0u) {
                    hcts_target_yield();
                }
                des_set_u8((unsigned int)(o + j), TXN_LOG[TXN_AT(h + 3u + j)]);
            }
        }
        txn_n = 0u;
        txn_runs = 0u;
        return faults;
    }

    /* Accepted. Each staged byte now takes the ORDINARY path - LIVE across,
       RPM_ZERO marked dirty, RESTART left pending - exactly as if TunerStudio
       had written it, so the preset has no apply rule of its own. */
    for (r = 0u; r < txn_runs; r++) {
        h = txn_rd16(TXN_IDX(r));
        o = txn_rd16(h);
        len = TXN_LOG[TXN_AT(h + 2u)];
        for (j = 0u; j < len; j++) {
            if ((j & 15u) == 0u) {
                hcts_target_yield();
            }
            hc_cfg_mgr_write_u8((unsigned int)(o + j),
                                hc_cfg_mgr_peek_u8((unsigned int)(o + j)));
        }
    }
    txn_n = 0u;
    txn_runs = 0u;
    faults = hc_cfg_mgr_apply_now(rpm);
    hc_cfg_txn_faults = faults;
    return faults;
}
