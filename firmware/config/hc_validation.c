/*
 * hc_validation.c - the configuration validation engine.
 *
 * Read hc_validation.h for the four rules this is built around. Below, only
 * the reasoning that is not obvious from the code.
 */
#ifdef HC_FAR_BRIDGE
#include "hcfarbridge.h"  /* FIRST: this module is FAR code on ME7.1.1 */
#endif
#include "hctarget.h"
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hccam.h"          /* camPhaseMode PATTERN */
#include "hc_pin_descriptor.h"
#include "hchal.h"
#include "hc_config_manager.h"
#include "hc_validation.h"
#include "hcts.h"
#if defined(TGT_ENGINE_RUNTIME)
#include "hcengctl711.h"     /* hc_fo_length */
#endif
#ifdef HC_FAR_BRIDGE
#include "hcfarinline.h"   /* AFTER hcconfig.h: call-free page reads */
#endif

unsigned int hc_val_warnings = 0u;
unsigned int hc_val_first_bad_offset = 0xFFFFu;

/* Which image this pass is reading. Set once per hc_validate() call; every
   accessor below goes through it, so there is exactly one implementation of
   every rule and it cannot drift between the two images. */
static unsigned char s_src;

/* EVERY PAGE READ THE VALIDATOR MAKES GOES THROUGH HERE, so this is where the
 * supervision yield belongs - not at the head of a few blocks, which is what
 * the first attempt did and which left a 14 ms gap inside the routing block
 * alone. The yield is TICK-GATED: it does real work at most once a
 * millisecond, so the worst service gap through a whole validation pass
 * becomes about one millisecond. It is taken every 32nd read, not every read -
 * see the counter below for why.
 *
 * MEASURED, and it is why this exists: a validation pass is 13.6 ms in the
 * linked ME7.1.1 image against a 10 ms S5500 raster, and every TunerStudio
 * Burn makes one. It returns immediately on any target whose ASIC state
 * machine is not armed yet, so it is safe at boot and free when unneeded. */

/* EVERY 32nd READ, not every read. A yield per byte was correct and far too
   expensive: hcts_target_yield() is tick-gated so it does real work at most
   once a millisecond, but the CALL is paid every time, and a validation pass
   is about four thousand reads. me711_v27_adversarial_test runs a great many
   passes and went from 10 seconds to a timeout. Every 32 reads still gives
   roughly a hundred yields across a pass - far more than the one per
   millisecond the gate needs - for a thirty-second of the overhead. */
#define VAL_YIELD_EVERY  32u

/* A BYTE, not a word, and it sits beside s_src deliberately: near RAM on this
   target holds a 192-byte engineering reserve and a word here cost 8 bytes of
   it after alignment. 256 is a whole number of 32s, so the wrap keeps the
   cadence exact. */
static unsigned char rd_count;

static unsigned char rd8(unsigned int off)
{
    rd_count = (unsigned char)(rd_count + 1u);
    if (((unsigned int)rd_count & (VAL_YIELD_EVERY - 1u)) == 0u) {
        hcts_target_yield();
    }
    return (s_src == HC_VAL_SRC_DESIRED) ? hc_cfg_mgr_read_u8(off)
                                         : hc_cal_u8(off);
}

static unsigned int rd16(unsigned int off)
{
    return (unsigned int)(((unsigned int)rd8(off) << 8) | rd8(off + 1u));
}

static void bad(unsigned int off)
{
    if (hc_val_first_bad_offset == 0xFFFFu) {
        hc_val_first_bad_offset = off;
    }
}

/* ---------------------------------------------------- cylinder addressing
 *
 * The legacy arrays in hcconfig.h are HC_MAX_CYL wide; cylinders above that
 * live in the universal block's extension arrays. Everything else in this
 * file asks through these two, so no rule has to know where the split is. */
static unsigned int tdc_of(unsigned int cyl)          /* 0-based */
{
    if (cyl < HC_MAX_CYL) {
        return rd16((unsigned int)(CFG_TDC_CYL + 2u * cyl));
    }
    return rd16((unsigned int)(CFG_U_TDC_CYL_EXT + 2u * (cyl - HC_MAX_CYL)));
}

static unsigned char inj_pin_of(unsigned int cyl)
{
    return rd8((unsigned int)(CFG_U_PIN_INJ + cyl));
}

static unsigned char ign_pin_of(unsigned int cyl)
{
    return rd8((unsigned int)(CFG_U_PIN_IGN + cyl));
}

/* ------------------------------------------------------------ pin checks */

/* One pin assignment. `need` is the FULL set of capabilities the function
   requires; hc_pin_can() demands all of them.
   HC_PIN_NONE is always acceptable here - "not routed" is a legal state, and
   whether a particular function is ALLOWED to be unrouted is a question for
   that function's own rule, not for the pin checker. */
static unsigned int check_pin(unsigned char pin, unsigned int need,
                              unsigned int off)
{
    const hc_pin_desc_t *d;

    if (HC_PIN_IS_UNASSIGNED(pin)) {
        return 0u;
    }
    d = hc_pin_desc(pin);
    if (d == (const hc_pin_desc_t *)0) {
        bad(off);
        return HC_VAL_FAULT_TARGET;     /* no such pin ON THIS ECU */
    }
    if (!hc_pin_can(pin, need)) {
        bad(off);
        return HC_VAL_FAULT_PIN_CAP;
    }
    /* The assignment is legal, but the evidence behind the capability is only
       PROBABLE. That is a warning, not a refusal: on the Bosch target every
       connector-side claim rests on Bosch's ME7.1 maximum-scope sheet, which
       is the right document and the wrong harness, and refusing all of them
       would mean refusing the whole board. */
    if (!hc_pin_can_verified(pin, need)) {
        hc_val_warnings |= HC_WARN_UNVERIFIED_PIN;
    }
    return 0u;
}

/* Exclusive-use scan. Two functions may not own one physical pin.
 *
 * Bounded and allocation-free: the claim list is a fixed 40 entries, which is
 * 12 injectors + 12 coils + crank + 2 cams + 8 sensors + 5 outputs, and the
 * only way to exceed it is to raise HC_MAX_CYL_UNIVERSAL - which would fail
 * the compile-time check below rather than overrun. */
#define CLAIM_MAX  48u

typedef struct {
    unsigned char pin[CLAIM_MAX];
    unsigned int  off[CLAIM_MAX];
    unsigned char n;
} claims_t;

typedef char hc_val_assert_claims[
    (2u * HC_MAX_CYL_UNIVERSAL + 16u <= CLAIM_MAX) ? 1 : -1];

/* STATIC, NOT A LOCAL - AND THIS IS THE USER STACK'S WHOLE PROBLEM.
 *
 * 48 pins + 48 offsets is 146 bytes, and as a local it made hc_validate()'s
 * frame 154 bytes: the largest in the image, sitting at the bottom of the
 * deepest chain there is (hc_validate -> rd8 -> hcts_target_yield -> ASIC +
 * TunerStudio), 184 of the 256-byte user stack with 8 bytes left over the
 * derived reserve. hc_validate() is not reentrant - it runs
 * from the main loop and boot, and nothing under its yield validates - so one
 * list serves every call. This module is compiled RENAMECLASS(NDATA0=XNDATA0),
 * so it lands in the on-chip XRAM (1 KB free at V82) and costs no near RAM. */
#ifdef TGT_RAM_VALCLAIMS
/* IN THE EXTERNAL SRAM where the target provides a region. The
   list is scratch rebuilt on every call (n = 0 below), so battery-backed
   contents from a previous boot mean nothing, and it is read only at
   validation time - background work, not worth on-chip RAM (XRAM was full
   to the byte). docs/ARCHITECTURE.md, memory. */
#define CLAIMS_MEM huge
typedef char hc_val_claims_fit[
    (sizeof(claims_t) <= TGT_RAM_VALCLAIMS_LIMIT) ? 1 : -1];
#define s_claims (*(claims_t huge *)(TGT_EXTRAM_BASE + TGT_RAM_VALCLAIMS))
#else
#define CLAIMS_MEM
static claims_t s_claims;
#endif

static unsigned int claim(claims_t CLAIMS_MEM *c, unsigned char pin, unsigned int off)
{
    unsigned char i;

    if (HC_PIN_IS_UNASSIGNED(pin)) {
        return 0u;
    }
    for (i = 0u; i < c->n; i++) {
        if (c->pin[i] == pin) {
            bad(off);
            return HC_VAL_FAULT_PIN_CONFLICT;
        }
    }
    if (c->n < CLAIM_MAX) {
        c->pin[c->n] = pin;
        c->off[c->n] = off;
        c->n++;
    }
    return 0u;
}

/* ---------------------------------------------------------- axis checks */

/* A lookup axis must increase. hc_cal_curve16() and hc_cal_map() both binary-
   search their axis and CLAMP at the ends; fed a non-monotonic axis they
   return a value from the wrong cell rather than failing, which is the worst
   kind of wrong. Equal neighbours are allowed - a flat axis segment is a
   legitimate way to pin a region of a map. */
static unsigned int axis_ok(unsigned int off, unsigned int n)
{
    unsigned int i;
    unsigned int prev = rd16(off);      /* rd8: the yield cadence, the seed */
    unsigned int cur;

    /* ONE word read per element after the first. The axes are ~240 of
       the page's words, read through rd8 twice each (a call, the yield
       counter, the config manager's seed check) - the bulk of an apply's
       validation once V98 added six axes (me711_config_state_test budget).
       An axis is at most 16 words, far inside one yield interval - but the
       rd8 cadence no longer reaches the axes, so each axis yields once
       (tick-gated: a call, real work once a millisecond;
       me711_preset_gap_proof measured 7.3 ms without it). */
    hcts_target_yield();
    for (i = 1u; i < n; i++) {
        cur = (s_src == HC_VAL_SRC_DESIRED)
            ? hc_cfg_mgr_read_u16((unsigned int)(off + 2u * i))
            : hc_cal_u16((unsigned int)(off + 2u * i));
        if (cur < prev) {
            bad((unsigned int)(off + 2u * i));
            return HC_VAL_FAULT_AXIS;
        }
        prev = cur;
    }
    return 0u;
}

/* ------------------------------------------------------- trigger, per decoder */

static unsigned int check_trigger(void)
{
    unsigned int f = 0u;
    unsigned int teeth = rd16(CFG_SY_TEETH);
    unsigned int gap = rd8(CFG_SY_GAP);
    unsigned int ratio = rd16(CFG_TRIG_GAP_RATIO_X10);
    unsigned char dec = rd8(CFG_U_TRIG_DECODER);

    if (rd8(CFG_TRIG_TIMEOUT_MS) == 0u) {
        /* Common to every decoder: with no stall timeout, a stopped engine is
           never noticed and the scheduler keeps its last position for ever. */
        bad(CFG_TRIG_TIMEOUT_MS);
        f |= HC_VAL_FAULT_TRIGGER;
    }

    switch (dec) {
    case HC_TRIGDEC_MISSING_TOOTH:
        /* THESE RULES BELONG TO THIS DECODER AND TO NO OTHER. */
        if (teeth < 4u || teeth > 200u) {
            bad(CFG_SY_TEETH);
            f |= HC_VAL_FAULT_TRIGGER;
        }
        if (gap == 0u || gap >= teeth) {
            bad(CFG_SY_GAP);
            f |= HC_VAL_FAULT_TRIGGER;
        }
        if (ratio < 12u) {
            /* Below 1.2x the gap is not distinguishable from a tooth arriving
               late during hard acceleration. */
            bad(CFG_TRIG_GAP_RATIO_X10);
            f |= HC_VAL_FAULT_TRIGGER;
        }
        if (rd8(CFG_TRIG_MIN_TEETH) == 0u) {
            bad(CFG_TRIG_MIN_TEETH);
            f |= HC_VAL_FAULT_TRIGGER;
        }
        break;

    case HC_TRIGDEC_BOSCH_ME711:
        /* The OEM ME7.1.1 rule, recovered from exact OEM ME7.1.1 machine code at
           85:8766: a candidate long interval is accepted as the gap when
           (candidate >> 1) > previous1 AND (candidate >> 1) > previous2,
           strict unsigned - which is a fixed ratio of 2.0 and NOT a tunable.
           docs/ARCHITECTURE.md.

           So the ratio field is not free here, and the A2L-declared geometry
           is 60-2. Validating it against the generic missing-tooth range would
           accept a 36-1 on this decoder, which the recovered code does not
           implement. */
        if (teeth != 60u) {
            bad(CFG_SY_TEETH);
            f |= HC_VAL_FAULT_TRIGGER;
        }
        if (gap != 2u) {
            bad(CFG_SY_GAP);
            f |= HC_VAL_FAULT_TRIGGER;
        }
        if (ratio != 20u) {
            bad(CFG_TRIG_GAP_RATIO_X10);
            f |= HC_VAL_FAULT_TRIGGER;
        }
        break;

    case HC_TRIGDEC_EVEN_TOOTH:
        /* No gap exists, so gap and ratio carry no meaning and are NOT
           checked. The cam is the only reference, so it has to be there. */
        if (teeth < 1u || teeth > 200u) {
            bad(CFG_SY_TEETH);
            f |= HC_VAL_FAULT_TRIGGER;
        }
        if (rd8(CFG_CAM_ENABLE) == 0u) {
            bad(CFG_CAM_ENABLE);
            f |= HC_VAL_FAULT_TRIGGER;
        }
        break;

    case HC_TRIGDEC_CUSTOM:
    default:
        /* Nothing is asserted about a wheel nobody has described. */
        break;
    }
    return f;
}

/* ------------------------------------------- sync, per execution strategy */

/* Can the configured geometry RESOLVE which revolution the engine is in?
 *
 * THIS USED TO ASK ONLY WHAT MODE WAS SELECTED, and that was not the same
 * question. geometry_read() in hctrig_me711.c clears g_sync_bank whenever
 * CFG_U_CAM_REFS is 0, and computes
 *
 *     g_cam_resolves = (g_sync_bank != 0 && (g_cam_refs & 1))
 *
 * so a cam cycle mode with no references, or with an EVEN number of them,
 * never promotes TRG_SYNC_CRANK to TRG_SYNC_FULL. The engine holds at
 * 360-degree sync for ever and says nothing.
 *
 * Meanwhile this function returned 1 for the mode alone, so the strategy
 * rules below ACCEPTED SEQUENTIAL INJECTION and sequential COP against a
 * configuration that can never deliver the cycle they require. It failed
 * safe - the scheduler gates on the sync state it really has - but the
 * validator was agreeing to something it had not checked, and the 1.8T
 * preset is exactly that shape.
 *
 * THE EVEN COUNT IS NOT A DETAIL. An even, equally spaced set of references
 * maps onto itself under a 360-degree shift, so a match is equally consistent
 * with either half of the cycle. The Porsche V8 donor's four references are
 * precisely that case. An ODD count - and in particular the single-window
 * Hall cam a 1.8T arrives with - is unambiguous.
 *
 * So this now asks the same question the runtime asks, in the same terms. */
/* V97 PATTERN (camPhaseMode 2): the answer engine/hccam.c gives the runtime -
   hccam_check() runs the same hccam_init() on a scratch - for the cam on
   input `bank` (0 = cam 1). 0 unusable, 1 cannot decide the half, 2 does. */
static unsigned char pattern_check(unsigned char bank)
{
    static hccam_cfg_t pc;               /* static: the user stack is 256 bytes */
    unsigned char conf = rd8(CFG_U_CAM_PHASE_CONFIRM);
    unsigned int win = rd16(CFG_U_CAM_WINDOW_X10);

    pc.pattern = rd8(bank ? CFG_U_CAM2_PATTERN : CFG_U_CAM1_PATTERN);
    pc.equal_n = rd8(CFG_U_CAM_REFS);
    pc.offset_x10 = rd16(bank ? CFG_U_CAM2_REF_X10 : CFG_U_CAM_REF_X10);
    pc.tol_x10 = (unsigned int)(rd8(CFG_U_CAM_TOOTH_TOL) * 10u);
    pc.auth_x10 = (win < 10u || win > 1800u) ? 300u : win;   /* as the runtime */
    pc.confirm = (unsigned char)((conf < 1u) ? 1u : (conf > 8u) ? 8u : conf);
    pc.errlimit = 3u;
    if (pc.offset_x10 >= 7200u) return 0u;
    return hccam_check(&pc);
}

/* is cam 2's input USED? Its cavity is an input - checked, claimed
   and given a capture role (hctrig_me711.c roles_resolve, the same rule) -
   only when cam-2 / dual-cam sync, a PATTERN wheel on cam 2 or VVT 2 reads
   it. A stale pinCam2 with nothing using it claimed cavity 87 against a
   motorsport switch. */
static unsigned char cam2_used(void)
{
    unsigned char s = rd8(CFG_U_SYNC_MODE);

    return (unsigned char)(s == HC_SYNC_CAM2_CYCLE || s == HC_SYNC_DUAL_CAM
        || (rd8(CFG_U_CAM_PHASE_MODE) == 2u && rd8(CFG_U_CAM2_PATTERN) != 0u)
        || rd8((unsigned int)(CFG_U_VVT_MODE + 1u)) != 0u);
}

static unsigned char pattern_resolves(unsigned char sync)
{
    return (unsigned char)(
        ((sync == HC_SYNC_CAM1_CYCLE || sync == HC_SYNC_DUAL_CAM)
         && pattern_check(0u) == 2u)
        || ((sync == HC_SYNC_CAM2_CYCLE || sync == HC_SYNC_DUAL_CAM)
            && pattern_check(1u) == 2u));
}

static unsigned char has_cycle_position(void)
{
    unsigned char m = rd8(CFG_U_SYNC_MODE);
    unsigned char refs;

    if (m != HC_SYNC_CAM1_CYCLE && m != HC_SYNC_CAM2_CYCLE
        && m != HC_SYNC_DUAL_CAM) {
        return 0u;
    }
    if (!rd8(CFG_CAM_ENABLE)) {
        return 0u;
    }
    /* THE LEVEL METHOD (camPhaseMode 1, the Bosch quick-start wheel)
       decides the half from the cam LEVEL at one crank angle and never
       counts reference edges, so camRefs does not apply to it - the same
       rule hctrig_me711.c geometry_read() uses. */
    if (rd8(CFG_U_CAM_PHASE_MODE) == 1u) {
        return 1u;
    }
    if (rd8(CFG_U_CAM_PHASE_MODE) == 2u) {
        return pattern_resolves(m);
    }
    refs = rd8(CFG_U_CAM_REFS);
    return (unsigned char)((refs != 0u && (refs & 1u)) ? 1u : 0u);
}

static unsigned int check_strategy(unsigned int n_cyl)
{
    unsigned int f = 0u;
    unsigned char inj = rd8(CFG_U_INJ_STRATEGY);
    unsigned char ign = rd8(CFG_U_IGN_STRATEGY);
    unsigned char sync = rd8(CFG_U_SYNC_MODE);
    unsigned int i;
    unsigned int n_inj = 0u;
    unsigned int n_ign = 0u;
    unsigned int trig = rd16(CFG_U_TRIG_ANGLE_X10);

    /* the trigger angle is a PHYSICAL crank angle - tooth #1 in 0.1 deg
       after cylinder-1 TDC, stored as s16 - and only -359.9..+359.9 is one.
       Compared as the stored word so the test means the same on the 16-bit
       target and a 32-bit host: 3600..61936 is +360.0..-360.0 and beyond.
       (V96's trigOffsetX10 allowed 0..719.9; the migration converts it.) */
    if (trig > 3599u && trig < 61937u) {
        bad(CFG_U_TRIG_ANGLE_X10);
        f |= HC_VAL_FAULT_SYNC;
    }

    /* SYNC_NONE is the bench state. Nothing may be driven, and that is
       enforced where outputs are driven, not here - a bench configuration is
       a perfectly valid configuration. */
    if (sync == HC_SYNC_NONE) {
        return 0u;
    }

    /* Rule 2 from the header, in one place.

       Needs a 720-degree cycle position:  sequential injection,
                                           sequential COP ignition.
       Runs on crank position alone:       batch and semi-sequential
                                           injection, wasted spark paired,
                                           WASTED COP, distributor.

       Wasted COP is the case that makes "COP requires cam sync" wrong: it
       drives one coil per cylinder and fires each of them twice per cycle,
       once into a cylinder on compression and once into one on exhaust. It
       needs no more position than a wasted-spark pair does. */
    if (inj == HC_INJ_SEQUENTIAL && !has_cycle_position()) {
        bad(CFG_U_INJ_STRATEGY);
        f |= HC_VAL_FAULT_SYNC;
    }
    if (ign == HC_IGN_SEQUENTIAL_COP && !has_cycle_position()) {
        bad(CFG_U_IGN_STRATEGY);
        f |= HC_VAL_FAULT_SYNC;
    }

    /* A cam cycle mode has to name a camshaft input. */
    if (sync == HC_SYNC_CAM1_CYCLE || sync == HC_SYNC_DUAL_CAM) {
        if (HC_PIN_IS_UNASSIGNED(rd8(CFG_U_PIN_CAM1))) {
            bad(CFG_U_PIN_CAM1);
            f |= HC_VAL_FAULT_SYNC;
        }
    }

    /* AND IT HAS TO HAVE THE GEOMETRY, which is a different thing from the
       pin. A cam that is wired but not described cannot resolve a cycle, and
       the field that is wrong is the reference count - so name THAT, not the
       pin, or a tuner goes looking at the wiring. See has_cycle_position(). */
    if (sync == HC_SYNC_CAM1_CYCLE || sync == HC_SYNC_CAM2_CYCLE
        || sync == HC_SYNC_DUAL_CAM) {
        unsigned char refs = rd8(CFG_U_CAM_REFS);
        if (!rd8(CFG_CAM_ENABLE)) {
            bad(CFG_CAM_ENABLE);
            f |= HC_VAL_FAULT_SYNC;
        } else if (rd8(CFG_U_CAM_PHASE_MODE) == 1u) {
            /* V92 LEVEL: the check angle must be inside the cycle. */
            if (rd16(CFG_U_CAM_PHASE_ANGLE_X10) >= 7200u) {
                bad(CFG_U_CAM_PHASE_ANGLE_X10);
                f |= HC_VAL_FAULT_SYNC;
            }
        } else if (rd8(CFG_U_CAM_PHASE_MODE) == 2u) {
            /* V97 PATTERN: every cam the mode names must be a usable pattern,
               and at least one of them must decide the half. The field named
               is the wheel - or the tolerance, when the wheel is known but the
               tolerance leaves no room below its closest teeth. */
            unsigned char b;
            for (b = 0u; b < 2u; b++) {
                if (b == 0u && sync == HC_SYNC_CAM2_CYCLE) continue;
                if (b == 1u && sync == HC_SYNC_CAM1_CYCLE) continue;
                if (pattern_check(b) == 0u) {
                    bad(rd8(b ? CFG_U_CAM2_PATTERN : CFG_U_CAM1_PATTERN)
                        ? CFG_U_CAM_TOOTH_TOL
                        : (b ? CFG_U_CAM2_PATTERN : CFG_U_CAM1_PATTERN));
                    f |= HC_VAL_FAULT_SYNC;
                }
            }
            if (!pattern_resolves(sync)) {
                bad(sync == HC_SYNC_CAM2_CYCLE ? CFG_U_CAM2_PATTERN
                                               : CFG_U_CAM1_PATTERN);
                f |= HC_VAL_FAULT_SYNC;
            }
        } else if (refs == 0u || (refs & 1u) == 0u) {
            bad(CFG_U_CAM_REFS);
            f |= HC_VAL_FAULT_SYNC;
        }
    }
    if (sync == HC_SYNC_CAM2_CYCLE || sync == HC_SYNC_DUAL_CAM) {
        if (HC_PIN_IS_UNASSIGNED(rd8(CFG_U_PIN_CAM2))) {
            bad(CFG_U_PIN_CAM2);
            f |= HC_VAL_FAULT_SYNC;
        }
    }
    /* Any mode above SYNC_NONE needs a crank input. */
    if (HC_PIN_IS_UNASSIGNED(rd8(CFG_U_PIN_CRANK))) {
        bad(CFG_U_PIN_CRANK);
        f |= HC_VAL_FAULT_SYNC;
    }

    /* Output count against strategy. Counting routed pins rather than
       assuming: a half-wired engine is a configuration error, not a crash. */
    for (i = 0u; i < n_cyl; i++) {
        if (!HC_PIN_IS_UNASSIGNED(inj_pin_of(i))) {
            n_inj++;
        }
        if (!HC_PIN_IS_UNASSIGNED(ign_pin_of(i))) {
            n_ign++;
        }
    }
    if (inj == HC_INJ_SEQUENTIAL && n_inj != 0u && n_inj != n_cyl) {
        bad(CFG_U_PIN_INJ);
        f |= HC_VAL_FAULT_STRATEGY;
    }
    if ((ign == HC_IGN_SEQUENTIAL_COP || ign == HC_IGN_WASTED_COP)
        && n_ign != 0u && n_ign != n_cyl) {
        bad(CFG_U_PIN_IGN);
        f |= HC_VAL_FAULT_STRATEGY;
    }
    if (ign == HC_IGN_WASTED_PAIRED && n_ign != 0u && (n_cyl & 1u) != 0u) {
        /* Paired wasted spark needs cylinders in pairs 360 degrees apart. */
        bad(CFG_U_IGN_STRATEGY);
        f |= HC_VAL_FAULT_STRATEGY;
    }
    return f;
}

/* --------------------------------------------------------------- the DBW */

static unsigned int check_dbw(void)
{
    unsigned int f = 0u;
    unsigned int t1min, t1max, a1min, a1max;
    unsigned char corr;

    /* THE BRIDGE PWM FREQUENCY IS CHECKED WHETHER OR NOT NORMAL DBW IS ON.
     * The ETB commissioning procedures own the bridge with dbwEnable 0, so a
     * frequency the hardware cannot switch would reach the motor during
     * AutoCal and characterization even on a page that never runs closed-loop
     * throttle.
     *
     * THE RANGE IS THE CJ220'S, NOT A GUESS. Its datasheet timing table
     * (the Bosch CJ220 datasheet, EXACT COMPONENT
     * DATASHEET) rates the PWM frequency by supply: 20 kHz at 8..12 V, 10 kHz
     * at 7..8 V, 5 kHz at 6..7 V, with a 1 kHz entry for the 33 nF charge-pump
     * capacitor. Below 1 kHz the charge pump's hold time, not the switch,
     * becomes the limit; above 10 kHz the part is out of rating the moment the
     * rail leaves 8 V, and 20 kHz is already physically refuted on this car
     * (V92: Auto Calibrate at 50 % duty produced "two very small twitches"
     * because the high side cannot enhance its gate at that rate). PP2 also
     * has to hold the period: 40 MHz / 65536 = 611 Hz is the register floor,
     * so 1 kHz clears it with room. */
    if (rd16(CFG_U_DBW_PWM_HZ) < 1000u || rd16(CFG_U_DBW_PWM_HZ) > 10000u) {
        bad(CFG_U_DBW_PWM_HZ);
        f |= HC_VAL_FAULT_DBW;
    } else if (rd16(CFG_U_DBW_PWM_HZ) > 5000u) {
        hc_val_warnings |= HC_WARN_DBW_PWM_SAG;
    }
    /* Friction compensation is bounded well inside the integrator's own
       30 % so it can never be the larger authority. */
    if (rd16(CFG_U_DBW_FRICTION_X10) > 300u) {
        bad(CFG_U_DBW_FRICTION_X10);
        f |= HC_VAL_FAULT_DBW;
    }

    if (rd8(CAL_DBW_ENABLE) == 0u) {
        return f;                   /* the motor never moves; nothing more */
    }

    t1min = rd16(CAL_TPS1_MIN);
    t1max = rd16(CAL_TPS1_MAX);
    a1min = rd16(CAL_PEDAL1_MIN);
    a1max = rd16(CAL_PEDAL1_MAX);

    /* An uncalibrated endpoint pair makes the position unknowable, and an
       unknown position with a live H-bridge is the one failure this project
       must not ship. */
    if (t1min == t1max || a1min == a1max) {
        bad(CAL_TPS1_MIN);
        f |= HC_VAL_FAULT_DBW;
    }
    /* Both tracks of both sensors have to exist. The whole point of two tracks
       is that they can be compared; one track cannot detect its own failure. */
    if (HC_PIN_IS_UNASSIGNED(rd8(CFG_U_PIN_TPS1))
        || HC_PIN_IS_UNASSIGNED(rd8(CFG_U_PIN_TPS2))
        || HC_PIN_IS_UNASSIGNED(rd8(CFG_U_PIN_APP1))
        || HC_PIN_IS_UNASSIGNED(rd8(CFG_U_PIN_APP2))) {
        bad(CFG_U_PIN_TPS1);
        f |= HC_VAL_FAULT_DBW;
    }

    /* The correlation MODEL is configured, not assumed.
     *
     * The ME7.5 pair really does move in opposite directions and its own I/O
     * map says so - but that is a fact about one throttle body, not a law.
     * A same-direction pair with different gains is ordinary, and a model that
     * hard-codes "opposite" declares such a body permanently faulty. What the
     * engine checks is that a model IS selected and that its tolerance is a
     * number an agreement test can use. */
    corr = rd8(CFG_U_TPS_CORR);
    if (corr > HC_TRACK_SCALED) {
        bad(CFG_U_TPS_CORR);
        f |= HC_VAL_FAULT_DBW;
    }
    corr = rd8(CFG_U_APP_CORR);
    if (corr > HC_TRACK_SCALED) {
        bad(CFG_U_APP_CORR);
        f |= HC_VAL_FAULT_DBW;
    }
    if (rd16(CFG_U_TPS_TOL_X10) == 0u || rd16(CFG_U_APP_TOL_X10) == 0u) {
        /* A zero tolerance can never be satisfied by two real potentiometers,
           so the bridge would be disabled for ever - which looks like a
           hardware fault and is a configuration one. */
        bad(CFG_U_TPS_TOL_X10);
        f |= HC_VAL_FAULT_DBW;
    }
    if (rd16(CAL_DBW_DEV_MS) == 0u || rd16(CAL_DBW_DEV_X10) == 0u) {
        bad(CAL_DBW_DEV_X10);
        f |= HC_VAL_FAULT_DBW;
    }
    if (rd16(CAL_DBW_MIN_X10) >= rd16(CAL_DBW_MAX_X10)) {
        bad(CAL_DBW_MIN_X10);
        f |= HC_VAL_FAULT_DBW;
    }
    return f;
}

/* ------------------------------------------------------------- lambda ---- */

static unsigned int check_lambda(unsigned int n_cyl)
{
    unsigned int f = 0u;
    unsigned char s1 = rd8(CFG_U_LAM1_SRC);
    unsigned char s2 = rd8(CFG_U_LAM2_SRC);
    unsigned int m1 = rd16(CFG_U_LAM1_CYLMASK);
    unsigned int m2 = rd16(CFG_U_LAM2_CYLMASK);
    unsigned int valid = (unsigned int)((n_cyl >= 16u)
                                        ? 0xFFFFu : ((1u << n_cyl) - 1u));

    if (s1 > HC_LAMBDA_CAN) {
        bad(CFG_U_LAM1_SRC);
        f |= HC_VAL_FAULT_LAMBDA;
    }
    if (s2 > HC_LAMBDA_CAN) {
        bad(CFG_U_LAM2_SRC);
        f |= HC_VAL_FAULT_LAMBDA;
    }
    /* Both channels are first class: neither is "the" sensor, and lambda 2
       may be enabled with lambda 1 off - a single sensor on bank 2 is a real
       arrangement. */
    if (s1 != HC_LAMBDA_OFF && (m1 & ~valid) != 0u) {
        bad(CFG_U_LAM1_CYLMASK);
        f |= HC_VAL_FAULT_LAMBDA;
    }
    if (s2 != HC_LAMBDA_OFF && (m2 & ~valid) != 0u) {
        bad(CFG_U_LAM2_CYLMASK);
        f |= HC_VAL_FAULT_LAMBDA;
    }
    if (s1 != HC_LAMBDA_OFF && s2 != HC_LAMBDA_OFF && (m1 & m2) != 0u) {
        /* Two closed-loop controllers trimming the same cylinder fight each
           other. Sharing is expressed with HC_BANK_BOTH on one channel, not by
           overlapping masks on two. */
        bad(CFG_U_LAM2_CYLMASK);
        f |= HC_VAL_FAULT_LAMBDA;
    }
    if (s1 == HC_LAMBDA_EXTERNAL_ANALOG
        && HC_PIN_IS_UNASSIGNED(rd8(CFG_U_PIN_LAMBDA1))) {
        bad(CFG_U_PIN_LAMBDA1);
        f |= HC_VAL_FAULT_LAMBDA;
    }
    if (s2 == HC_LAMBDA_EXTERNAL_ANALOG
        && HC_PIN_IS_UNASSIGNED(rd8(CFG_U_PIN_LAMBDA2))) {
        bad(CFG_U_PIN_LAMBDA2);
        f |= HC_VAL_FAULT_LAMBDA;
    }
    /* The one place AFR and lambda are related. A zero here would make every
       AFR display divide by zero. */
    {
        unsigned int st = rd16(CFG_U_STOICH_X100);
        if (st < 500u || st > 2500u) {
            bad(CFG_U_STOICH_X100);
            f |= HC_VAL_FAULT_LAMBDA;
        }
    }
    if (s1 == HC_LAMBDA_OFF && s2 == HC_LAMBDA_OFF) {
        hc_val_warnings |= HC_WARN_NO_LAMBDA;
    }
    return f;
}

/* -------------------------------------------------------------- warnings */

/* 1 when a table looked up on THROTTLE has an axis outside 0..100 %: mode is
   the table's ENUM_LOAD_AXIS (0 = the fuel load, 2 = throttle). */
static unsigned char tps_axis_bad(unsigned int ax_off, unsigned char mode)
{
    if (!(mode == 2u || (mode == 0u && (rd8(CFG_U_FUEL_MODEL)==0u
        ? rd8(CAL_LOAD_SOURCE)!=CAL_LOAD_MAP : rd8(CFG_U_FUEL_MODEL)!=2u)))) {
        return 0u;
    }
    return (unsigned char)(rd16(ax_off) >= 100u
                           || rd16((unsigned int)(ax_off + 2u * (CAL_AXIS_N - 1u)))
                              > 1000u);
}

static void collect_warnings(void)
{
    unsigned int ms = rd16(CFG_U_MS_ENABLE);

    if (tps_axis_bad(CAL_FUEL_LOAD_AX, 0u)) {
        hc_val_warnings |= HC_WARN_VE_AXIS;
    }
    if (tps_axis_bad(CAL_IGN_LOAD_AX, rd8(CFG_U_IGN_LOAD_MODE))) {
        hc_val_warnings |= HC_WARN_IGN_AXIS;
    }
    if (tps_axis_bad(CFG_U_LAM_LOAD_AX, rd8(CFG_U_LAM_LOAD_MODE))) {
        hc_val_warnings |= HC_WARN_LAM_AXIS;
    }

    if ((ms & 0x0001u) && HC_PIN_IS_UNASSIGNED(rd8(CFG_U_PIN_LAUNCH))) {
        hc_val_warnings |= HC_WARN_LAUNCH_NO_SOURCE;
    }
    if ((ms & 0x0002u) && HC_PIN_IS_UNASSIGNED(rd8(CFG_U_PIN_FLATSHIFT))) {
        hc_val_warnings |= HC_WARN_FLATSHIFT_NO_SOURCE;
    }
    if ((ms & 0x0004u) && HC_PIN_IS_UNASSIGNED(rd8(CFG_U_PIN_ANTILAG))) {
        hc_val_warnings |= HC_WARN_ANTILAG_NO_SOURCE;
    }
    if ((ms & 0x0008u) && HC_PIN_IS_UNASSIGNED(rd8(CFG_U_PIN_PITLIM))) {
        hc_val_warnings |= HC_WARN_PITLIM_NO_SOURCE;
    }
    if (rd8(CAL_LOAD_SOURCE) == CAL_LOAD_MAP
        && HC_PIN_IS_UNASSIGNED(rd8(CFG_U_PIN_MAP))) {
        hc_val_warnings |= HC_WARN_NO_MAP_SENSOR;
    }
    if (rd8(CAL_BOOST_ENABLE) && HC_PIN_IS_UNASSIGNED(rd8(CFG_U_PIN_BOOST))) {
        hc_val_warnings |= HC_WARN_BOOST_NO_PIN;
    }
    if (rd16(CFG_U_OILP_MIN_KPA) != 0u
        && HC_PIN_IS_UNASSIGNED(rd8(CFG_U_PIN_OIL_PRESS))) {
        hc_val_warnings |= HC_WARN_OILP_NO_SENSOR;
    }
    if (rd8(CFG_OUTPUTS_ARMED)) {
        hc_val_warnings |= HC_WARN_OUTPUTS_ARMED;
    }
}

/* ============================================================ the engine */

unsigned int hc_validate(unsigned char src)
{
    unsigned int f = HC_VAL_OK;
    unsigned int n_cyl;
    unsigned int i, j;
    claims_t CLAIMS_MEM *c = &s_claims;

    s_src = src;
    rd_count = 0u;
    hc_val_warnings = HC_WARN_NONE;
    hc_val_first_bad_offset = 0xFFFFu;
    c->n = 0u;

    /* 1. Schema. A page from a different layout must be migrated, not read. */
    if (rd16(CFG_VERSION) != HC_CFG_VERSION) {
        bad(CFG_VERSION);
        f |= HC_VAL_FAULT_SCHEMA;
    }
    if (rd16(CFG_U_MAGIC) != HC_UNIVERSAL_MAGIC
        || rd16(CFG_U_SCHEMA) != HC_UNIVERSAL_SCHEMA) {
        /* No universal block, or one from another schema. Every rule below
           that reads CFG_U_* would be reading somebody else's bytes, so stop
           here rather than produce confident nonsense. */
        bad(CFG_U_MAGIC);
        return f | HC_VAL_FAULT_SCHEMA;
    }

    /* 2. Cylinder count bounds EVERY loop below, so it is checked first and
          the pass stops if it is wrong. */
    n_cyl = rd8(CFG_CYLINDERS);
    if (n_cyl < 1u || n_cyl > HC_MAX_CYL_UNIVERSAL) {
        bad(CFG_CYLINDERS);
        return f | HC_VAL_FAULT_CYLINDERS;
    }
    if (rd8(CFG_STROKES) != 2u && rd8(CFG_STROKES) != 4u) {
        bad(CFG_STROKES);
        f |= HC_VAL_FAULT_CYLINDERS;
    }

    /* 3. Per-cylinder TDC angles: in range, and distinct. Two cylinders at the
          same angle is a configuration in which one of them never fires.
          V98: a NAMED FIRING ORDER places the cylinders itself (the
          scheduler ignores the angles then) and must name exactly as many
          cylinders as the engine has (rusEFI CUSTOM_OBD_WRONG_FIRING_ORDER). */
#if defined(TGT_ENGINE_RUNTIME)
    if (rd8(CFG_U_FIRING_ORDER) != 0u) {
        if (hc_fo_length(rd8(CFG_U_FIRING_ORDER)) != n_cyl) {
            bad(CFG_U_FIRING_ORDER);
            f |= HC_VAL_FAULT_TDC;
        }
    } else
#endif
    for (i = 0u; i < n_cyl; i++) {
        unsigned int a = tdc_of(i);
        if (a > 7200u) {
            bad(CFG_TDC_CYL);
            f |= HC_VAL_FAULT_TDC;
        }
        for (j = 0u; j < i; j++) {
            if (a == tdc_of(j)) {
                bad(CFG_TDC_CYL);
                f |= HC_VAL_FAULT_TDC;
            }
        }
    }

    /* 4. Trigger, per decoder. */
    f |= check_trigger();

    /* 5. Strategy and sync. */
    f |= check_strategy(n_cyl);

    /* 6. Physical routing. Injectors and coils first, because those are the
          two the tuner is most likely to get wrong and the first bad offset
          is more useful pointing at one of them. */
    for (i = 0u; i < n_cyl; i++) {
        unsigned int off = (unsigned int)(CFG_U_PIN_INJ + i);
        f |= check_pin(inj_pin_of(i), HC_PINCAP_INJ_OUT, off);
        f |= claim(c, inj_pin_of(i), off);
    }
    for (i = 0u; i < n_cyl; i++) {
        unsigned int off = (unsigned int)(CFG_U_PIN_IGN + i);
        f |= check_pin(ign_pin_of(i), HC_PINCAP_IGN_OUT, off);
        f |= claim(c, ign_pin_of(i), off);
    }
    {
        /* Position inputs. VR and Hall are different circuits, so the crank
           pin is asked for either, not for both. */
        unsigned char p = rd8(CFG_U_PIN_CRANK);
        unsigned char c1 = rd8(CFG_U_PIN_CAM1);
        unsigned char c2 = cam2_used() ? rd8(CFG_U_PIN_CAM2) : HC_PIN_NONE;
        if (!HC_PIN_IS_UNASSIGNED(p)
            && !hc_pin_can(p, HC_PINCAP_VR_IN)
            && !hc_pin_can(p, HC_PINCAP_HALL_IN)
            && !hc_pin_can(p, HC_PINCAP_FREQ_IN)) {
            bad(CFG_U_PIN_CRANK);
            f |= HC_VAL_FAULT_PIN_CAP;
        }
        f |= claim(c, p, CFG_U_PIN_CRANK);
        f |= check_pin(c1, HC_PINCAP_HALL_IN, CFG_U_PIN_CAM1);
        f |= claim(c, c1, CFG_U_PIN_CAM1);
        f |= check_pin(c2, HC_PINCAP_HALL_IN, CFG_U_PIN_CAM2);
        f |= claim(c, c2, CFG_U_PIN_CAM2);

        /* AND THE CAVITY MUST REACH A CAPTURE UNIT ON THIS BOARD.
         *
         * A capability bit says what a circuit could do; hc_hal_capture_channel()
         * says what this board actually wired to an edge-capture resource. Those
         * are different questions and only the second one can be honoured.
         *
         * Before V62 the capture was compiled to CC15/CC8/CC9 whatever the page
         * said, so a crank pin on a cavity with FREQ_IN and no capture unit
         * VALIDATED and the ECU went on reading the old wire. Now the binding is
         * real, so an unroutable cavity has to be REFUSED rather than silently
         * resolved to nothing - otherwise the same edit would simply disarm the
         * engine's position input and report success.
         *
         * PIN_CAP is the right fault: the board cannot do what was asked. */
        if (!HC_PIN_IS_UNASSIGNED(p)
            && hc_hal_capture_channel(p) == HC_CAPCH_NONE) {
            bad(CFG_U_PIN_CRANK);
            f |= HC_VAL_FAULT_PIN_CAP;
        }
        if (!HC_PIN_IS_UNASSIGNED(c1)
            && hc_hal_capture_channel(c1) == HC_CAPCH_NONE) {
            bad(CFG_U_PIN_CAM1);
            f |= HC_VAL_FAULT_PIN_CAP;
        }
        if (!HC_PIN_IS_UNASSIGNED(c2)
            && hc_hal_capture_channel(c2) == HC_CAPCH_NONE) {
            bad(CFG_U_PIN_CAM2);
            f |= HC_VAL_FAULT_PIN_CAP;
        }
        /* Two position inputs on ONE capture channel is not a routing, it is
           one of them silently losing. claim() already catches the same cavity
           twice; this catches two DIFFERENT cavities that land on the same
           unit, which claim() cannot see. */
        if (!HC_PIN_IS_UNASSIGNED(p) && !HC_PIN_IS_UNASSIGNED(c1)
            && hc_hal_capture_channel(p) == hc_hal_capture_channel(c1)) {
            bad(CFG_U_PIN_CAM1);
            f |= HC_VAL_FAULT_PIN_CONFLICT;
        }
        if (!HC_PIN_IS_UNASSIGNED(p) && !HC_PIN_IS_UNASSIGNED(c2)
            && hc_hal_capture_channel(p) == hc_hal_capture_channel(c2)) {
            bad(CFG_U_PIN_CAM2);
            f |= HC_VAL_FAULT_PIN_CONFLICT;
        }
        if (!HC_PIN_IS_UNASSIGNED(c1) && !HC_PIN_IS_UNASSIGNED(c2)
            && hc_hal_capture_channel(c1) == hc_hal_capture_channel(c2)) {
            bad(CFG_U_PIN_CAM2);
            f |= HC_VAL_FAULT_PIN_CONFLICT;
        }
    }
    {
        /* Analog sensors. One table, so adding a sensor is one line and can
           never forget the conflict scan. */
        static const unsigned int ain_off[] = {
            CFG_U_PIN_MAP, CFG_U_PIN_BARO, CFG_U_PIN_CLT, CFG_U_PIN_IAT,
            CFG_U_PIN_TPS1, CFG_U_PIN_TPS2, CFG_U_PIN_APP1, CFG_U_PIN_APP2,
            CFG_U_PIN_VBAT, CFG_U_PIN_OIL_PRESS, CFG_U_PIN_FUEL_PRESS,
            CFG_U_PIN_LAMBDA1, CFG_U_PIN_LAMBDA2
        };
        for (i = 0u; i < (sizeof(ain_off) / sizeof(ain_off[0])); i++) {
            unsigned char p = rd8(ain_off[i]);
            f |= check_pin(p, HC_PINCAP_AIN, ain_off[i]);
            f |= claim(c, p, ain_off[i]);
        }
    }
    {
        /* CFG_U_PIN_MAIN_RELAY WAS MISSING FROM THIS LIST. The fuel pump
           was validated and the main relay was not, so MAIN_RELAY could be
           routed to an analog input and nothing would say so. It needs
           RELAY_OUT, exactly as the fuel pump does. */
        static const unsigned int out_off[] = {
            CFG_U_PIN_FUEL_PUMP, CFG_U_PIN_BOOST,
            CFG_U_PIN_TACHO,
            CFG_U_PIN_CAM1_SOL, CFG_U_PIN_CAM2_SOL,
            CFG_U_PIN_MIL                 /* V97 */
        };
        static const unsigned int out_need[] = {
            HC_PINCAP_RELAY_OUT, HC_PINCAP_PWM_OUT,
            HC_PINCAP_LOW_SIDE,
            HC_PINCAP_PWM_OUT, HC_PINCAP_PWM_OUT,
            HC_PINCAP_LOW_SIDE
        };
        unsigned char mr = rd8(CFG_U_PIN_MAIN_RELAY);
        for (i = 0u; i < (sizeof(out_off) / sizeof(out_off[0])); i++) {
            unsigned char p = rd8(out_off[i]);
            f |= check_pin(p, out_need[i], out_off[i]);
            /* capable is not enough - the HAL must drive it there. */
            if (!HC_PIN_IS_UNASSIGNED(p) && !hc_hal_out_bindable(out_off[i], p)) {
                bad(out_off[i]);
                f |= HC_VAL_FAULT_PIN_CAP;
            }
            f |= claim(c, p, out_off[i]);
        }
        /* MAIN_RELAY: a CPU-driven RELAY_OUT, or the supply IC's own relay
           stage (MAIN_RELAY_HW - ME7.1.1 cavity 23, the CJ910's MR, which
           follows KL15 in hardware and has no CPU port). That stage cannot
           be switched OFF with the key on, nor held ON after it, so the only
           mode it can honour is AUTO; OFF and ON are refused rather than
           shown and ignored. */
        if (!HC_PIN_IS_UNASSIGNED(mr) && hc_pin_can(mr, HC_PINCAP_MAIN_RELAY_HW)) {
            f |= check_pin(mr, HC_PINCAP_MAIN_RELAY_HW, CFG_U_PIN_MAIN_RELAY);
            if (rd8(CFG_MAIN_RELAY_MODE) != MAIN_RELAY_AUTO) {
                bad(CFG_MAIN_RELAY_MODE);
                f |= HC_VAL_FAULT_PIN_CAP;
            }
        } else {
            f |= check_pin(mr, HC_PINCAP_RELAY_OUT, CFG_U_PIN_MAIN_RELAY);
            if (!HC_PIN_IS_UNASSIGNED(mr)
                && !hc_hal_out_bindable(CFG_U_PIN_MAIN_RELAY, mr)) {
                bad(CFG_U_PIN_MAIN_RELAY);      /* capable, not driven */
                f |= HC_VAL_FAULT_PIN_CAP;
            }
        }
        f |= claim(c, mr, CFG_U_PIN_MAIN_RELAY);
    }

    /* 7. Speed limits. Ordered, and only the orderings that are actually
          required - a soft limiter equal to the hard one is a valid way to
          say "no soft limiter". */
    {
        unsigned int rev_max = rd16(CFG_REV_MAX);
        unsigned int rev_lim = rd16(CFG_REV_LIMIT);
        unsigned int crank = rd16(CFG_CRANK_RPM_MAX);

        if (rev_max == 0u || rev_lim == 0u) {
            bad(CFG_REV_MAX);
            f |= HC_VAL_FAULT_REV;
        }
        if (rev_lim > rev_max) {
            /* The scheduler's calculations are bounded by REV_MAX; a limiter
               above it is a limiter the scheduler was never sized for. */
            bad(CFG_REV_LIMIT);
            f |= HC_VAL_FAULT_REV;
        }
        if (crank >= rev_lim) {
            bad(CFG_CRANK_RPM_MAX);
            f |= HC_VAL_FAULT_REV;
        }
        if (rd8(CAL_REVLIM_MODE) > 2u
            || rd8(CAL_REVLIM_PATTERN) < 1u || rd8(CAL_REVLIM_PATTERN) > 8u) {
            bad(CAL_REVLIM_MODE);
            f |= HC_VAL_FAULT_REV;
        }
    }

#if defined(TGT_ENGINE_RUNTIME)
    /* 7b. V98: the fuel load strategy, and the motorsport switches - a switch
           must be on a cavity the HAL can READ (hc_hal_din), and it owns its
           cavity like any other function. */
    if (rd8(CAL_LOAD_SOURCE) > CAL_LOAD_ALPHAN) {
        bad(CAL_LOAD_SOURCE);
        f |= HC_VAL_FAULT_STRATEGY;
    }
    {
        unsigned char model=rd8(CFG_U_FUEL_MODEL),role=rd8(CFG_U_PRESSURE_ROLE),policy=rd8(CFG_U_DENSITY_POLICY);
        unsigned char invalid=(unsigned char)(model>3u||role>2u||policy>2u||rd8(CFG_U_BARO_SOURCE)>2u
            || rd8(CFG_U_AMBIENT_CORR)>1u||rd8(CFG_U_IAT_POLICY)>1u||rd8(CFG_U_LEAN_ENABLE)>1u
            || rd8(CFG_U_LAMBDA_QUALIFIED)>1u||rd8(CFG_U_PRESSURE_GUARD)>1u);
        if(model==1u && policy!=0u) invalid=1u;
        if(model==2u && (role!=1u||policy!=1u)) invalid=1u;
        if(model==3u && (role!=2u||(policy!=1u&&policy!=2u))) invalid=1u;
        if(model==2u||model==3u) {
            if(HC_PIN_IS_UNASSIGNED(rd8(CFG_U_PIN_MAP))) invalid=1u;
        }
        if(model || rd8(CFG_U_LEAN_ENABLE)||rd8(CFG_U_PRESSURE_GUARD)) {
            if(rd16(CFG_U_PRESSURE_REF)<500u||rd16(CFG_U_PRESSURE_REF)>1200u
                || rd16(CFG_U_BARO_MAX_AGE)==0u||rd16(CFG_U_PRESSURE_TIMEOUT)<10u||rd16(CFG_U_PRESSURE_TIMEOUT)>1000u
                || rd16(CFG_U_GUARD_TPS)>1000u||rd16(CFG_U_LEAN_TPS)>1000u
                || rd16(CFG_U_LEAN_DEVIATION)==0u||rd16(CFG_U_LEAN_DEVIATION)>1000u
                || rd16(CFG_U_LEAN_PERSIST)==0u||rd16(CFG_U_LEAN_PERSIST)>10000u
                || rd16(CFG_U_LEAN_RECOVERY)==0u||rd16(CFG_U_LEAN_RECOVERY)>30000u) invalid=1u;
        }
        if(model==3u && policy==2u && (rd16(CFG_U_BLEND_FULL)<=rd16(CFG_U_BLEND_START)
            || rd16(CFG_U_BLEND_FULL)>4000u)) invalid=1u;
        if(invalid) { bad(CFG_U_FUEL_MODEL); f|=HC_VAL_FAULT_STRATEGY; }
    }
    {
        static const unsigned int sw_off[4] = {
            CFG_U_PIN_LAUNCH, CFG_U_PIN_FLATSHIFT, CFG_U_PIN_ANTILAG,
            CFG_U_PIN_PITLIM
        };
        unsigned int ms = rd16(CFG_U_MS_ENABLE);

        for (i = 0u; i < 4u; i++) {
            /* only an ENABLED function owns its switch cavity */
            unsigned char p = (ms & (1u << i)) ? rd8(sw_off[i]) : HC_PIN_NONE;
            if (!HC_PIN_IS_UNASSIGNED(p) && !hc_hal_din_ok(p)) {
                bad(sw_off[i]);
                f |= HC_VAL_FAULT_PIN_CAP;
            }
            f |= claim(c, p, sw_off[i]);
        }
    }
#endif

    /* 8. Throttle. */
    f |= check_dbw();

    /* 9. Lambda. */
    f |= check_lambda(n_cyl);

    /* 10. Every axis a lookup will binary-search. */
    f |= axis_ok(CAL_FUEL_RPM_AX, CAL_AXIS_N);
    f |= axis_ok(CAL_FUEL_LOAD_AX, CAL_AXIS_N);
    f |= axis_ok(CAL_IGN_RPM_AX, CAL_AXIS_N);
    f |= axis_ok(CAL_IGN_LOAD_AX, CAL_AXIS_N);
    f |= axis_ok(CAL_CLT_ENR_AX, CAL_AXIS_N);
    f |= axis_ok(CAL_CLT_SENS_AX, CAL_AXIS_N);
    f |= axis_ok(CAL_IAT_SENS_AX, CAL_AXIS_N);
    f |= axis_ok(CAL_PEDAL_RPM_AX, CAL_AXIS_N);
    f |= axis_ok(CAL_PEDAL_AX, CAL_AXIS_N);
    f |= axis_ok(CAL_BOOST_RPM_AX, CAL_AXIS_N);
    f |= axis_ok(CAL_BOOST_TPS_AX, CAL_AXIS_N);
    f |= axis_ok(CAL_BOOST_TGT_RPM_AX, CAL_AXIS_N);
    f |= axis_ok(CAL_BOOST_TGT_TPS_AX, CAL_AXIS_N);
    f |= axis_ok(CAL_CRANK_PW_AX, 8u);
    f |= axis_ok(CAL_DWELL_BATT_AX, 8u);
    f |= axis_ok(CAL_DBW_BIAS_AX, 8u);
    f |= axis_ok(CAL_IDLE_TARGET_AX, 8u);
    f |= axis_ok(CAL_IDLE_BASE_AX, 8u);
    f |= axis_ok(CAL_BOOST_CLT_AX, 8u);
    f |= axis_ok(CAL_BOOST_IAT_AX, 8u);
#if defined(TGT_ENGINE_RUNTIME)
    f |= axis_ok(CFG_U_LAM_RPM_AX, CAL_AXIS_N);         /* V98 */
    f |= axis_ok(CFG_U_LAM_LOAD_AX, CAL_AXIS_N);
    /* only the axes of a table the configuration reads: the apply is
       budgeted (me711_config_state_test), and pure alpha-N never reads
       the MAP estimate, the single injection angle never the table */
    if (rd8(CAL_LOAD_SOURCE) != CAL_LOAD_ALPHAN) {
        f |= axis_ok(CFG_U_MAPEST_RPM_AX, 8u);
        f |= axis_ok(CFG_U_MAPEST_TPS_AX, 8u);
    }
    if (rd8(CFG_U_INJ_PHASE_MODE) != 0u) {
        f |= axis_ok(CFG_U_INJ_PHASE_RPM_AX, 8u);
        f |= axis_ok(CFG_U_INJ_PHASE_LOAD_AX, 8u);
    }
#endif

    collect_warnings();
    return f;
}
