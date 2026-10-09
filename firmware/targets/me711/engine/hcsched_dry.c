/* Crank-angle planner with a single-producer capture ring.
 *
 * The ISR-facing function only appends one three-word capture to a bounded
 * ring. The independent planner level converts angles to deadlines and
 * publishes complete owned pulses. CC25 exclusively executes output edges;
 * background service cadence cannot delay capture or planning.
 */
#include <reg167.h>
#include <intrins.h>
#include "hctarget.h"
#include "hcconfig.h"
#include "hc_config_manager.h"
#include "hc_plan.h"
#include "hcengine.h"
#include "hctrigger.h"
#include "hchal.h"          /* hc_hal_out - events reach outputs from V63 */
#include "hcsched_dry.h"
#include "hcdeadline711.h"
#include "hcdeadline_state.h"  /* hc_dl_owner: the spark ownership test */
#include "hcio711.h"         /* the boot history in the extended window */
#include "hcknock711.h"      /* knock retard per slot, geometry export  */
#include "hcengctl711.h"     /* firing order -> TDC (far)               */
#include "hcrtmon711.h"       /* runtime health record            */
#include "hcatomic.h"

/* V47..V54 were persistence qualification images. They had no injector or
 * ignition backend, and their live-word admission was allowed to treat output
 * deadlines as absent only because those targets proved them absent. The ABI
 * and the OCH fields stayed; the planner did not.
 *
 * THE SWITCH IS NOW POSITIVE AND IT IS ITS OWN. Gating the engine runtime on
 * TGT_LIVE_BURN_HYBRID_QUAL tied it to the burn-forensics instrumentation,
 * which is unrelated and whose other branch has rotted (it still names
 * TGT_RAM_NVM_FORENSICS, a symbol that no longer exists). Defining
 * TGT_ENGINE_RUNTIME brings the scheduler back without touching one byte of
 * the qualified persistence path. */
#if !defined(TGT_ENGINE_RUNTIME)
unsigned int dry_sched_queued, dry_sched_executed, dry_sched_cancelled;
unsigned int dry_sched_late, dry_sched_missed, dry_sched_max_latency;
unsigned int dry_sched_next_angle, dry_sched_last_angle;
unsigned int dry_sched_capture_overflow, dry_sched_catchup, dry_sched_rebases;
unsigned int dry_sched_pending, dry_sched_status, dry_sched_need_sync;
unsigned int dry_next_ign_slot, dry_next_inj_slot;
unsigned int dry_spark_advance_x10, dry_dwell_x100, dry_inj_pulse_us;
unsigned int dry_dwell_start_angle, dry_spark_angle, dry_inj_start_angle;
unsigned int dry_inj_end_angle;
unsigned int dry_sched_overdwell;
unsigned int hc_ign_ovd_latch;
unsigned char dry_seq_active;
unsigned int dry_seq_inj_mask, dry_seq_skips, dry_seq_enters, dry_seq_leaves;
unsigned int dry_inj_width_us, dry_inj_nofree;
unsigned char hc_tl_inhibit, hc_tl_active;
unsigned int hc_tl_state, hc_tl_revs, hc_tl_teeth;
void hc_tl_request(unsigned char m, unsigned int t) { if (m || t) return; }
void hc_tl_service(unsigned int t) { if (t) return; }
unsigned char hc_och_ext_byte(unsigned int o) { return hc_lf_export_byte(o); }

void hc_drysched_init(void) { dry_sched_need_sync = TRG_SYNC_CRANK; }
void hc_drysched_tooth(unsigned int a, unsigned int s, unsigned int d)
{ if (a || s || d) return; }
void hc_drysched_service(unsigned int n, unsigned int s) { if (n || s) return; }
void hc_drysched_time_service(unsigned int n) { if (n) return; }
void hc_drysched_overdwell_service(unsigned int n) { if (n) return; }
void hc_drysched_snap(void) { HC_KN711.snap_valid = 0u; }
void hc_drysched_cancel(unsigned int reason) { dry_sched_next_angle = reason; }
void hc_drysched_abort(unsigned int reason) { dry_sched_next_angle = reason; }
unsigned int hc_drysched_schedule_after(unsigned int a, unsigned char t,
                                        unsigned char s)
{ if (a || t || s) return 0u; return 0u; }
void hc_drysched_test_set_epoch(unsigned int h, unsigned int l)
{ if (h || l) return; }
unsigned int hc_drysched_test_epoch_hi(void) { return 0u; }
unsigned int hc_drysched_test_epoch_lo(void) { return 0u; }
void hc_drysched_test_anchor(unsigned int a) { if (a) return; }
void hc_drysched_test_advance(unsigned int a, unsigned int s, unsigned int d)
{ if (a || s || d) return; }

#else

#define CAP_N  8u
#define EV_N  16u
#define PLAN_N 16u
#define EV_NONE 0u

/* an event executed more than this after its deadline is "late". The
   executor is polled at least once a millisecond, so a quarter of that is
   the honest line between the polling quantum and a real delay. */
#define DRY_LATE_TICKS  ((unsigned int)(TGT_TICKS_PER_MS_X10 / 40uL))
/* PER-EVENT-KIND LATENESS. The aggregate counters cannot say how late
 * a SPARK was, which is what sets delivered ignition timing - the car's logs
 * carry one global high-water mark and nothing per kind
 * (14..16 % of events later than one tooth,
 * worst 1.98..2.11 ms = 18 deg at 1500 rpm against a commanded 10 deg).
 *
 * ponytail: per-kind WORST CASE and per-kind OVER-ONE-TOOTH COUNT, not a
 * histogram. NCODE is a single 64512-byte CGROUP with no room left
 * (linker_me711.lnp, docs/ARCHITECTURE.md) and a six-bucket
 * histogram's edge table and inner loop did not fit. These two numbers per
 * kind answer "was a spark late, and how late at worst" with three compares
 * and two increments. The full distribution belongs with the hardware-compare
 * executor that the project rules name as the next step, or on the host from ring
 * events - neither needs NCODE. */
#define DRY_LK_DWELL     0u
#define DRY_LK_SPARK     1u
#define DRY_LK_INJ       2u
#define DRY_LK_N         3u
/* ponytail: NOT IMPLEMENTED YET - these three kinds are the agreed shape and
   nothing more. The accounting needs ~60 bytes of NCODE and the image has
   14 (measured 2026-10-03: a single extra hcts_target_yield() in
   hcmain_me711.c already puts ?PR?HCASICDUMP outside the class). It lands
   with the code-space step in docs/ARCHITECTURE.md, or with the
   hardware-compare executor the project rules name as the next step - after
   which the aggregate counters may well be enough. Adding dead arrays that
   always read 0 would put a counter in the logs that means nothing, which
   is the defect class the bench measurements show. */

/* V93/V97: every fuel cut the injectors obey (rev limit, overrun, overboost,
   engine protection) */
#define DRY_FUEL_CUTS  ENG_CUT_ALL
/* the longest time-queued injector close. The executor's due test is
   signed 16-bit over T1 (1.25 MHz), so a delay must stay below 32768 ticks
   (26.2 ms); a longer pulse is held to 25.6 ms. */
#define DRY_INJ_MAX_TICKS   32000u

#define DRY_ST_ANGLE_VALID  0x0001u
#define DRY_ST_NEAR_ARMED   0x0002u
#define DRY_ST_SYNCED       0x0004u

unsigned int dry_sched_queued, dry_sched_executed, dry_sched_cancelled;
unsigned int dry_sched_late, dry_sched_missed, dry_sched_max_latency;
unsigned int dry_sched_next_angle, dry_sched_last_angle;
unsigned int dry_sched_capture_overflow;
unsigned int dry_sched_rebases;   /* epoch rebases - see DRY_EPOCH_WRAP */
unsigned int dry_sched_pending, dry_sched_status;
/* The sync level the CONFIGURED strategies require. Published so a
   bench can tell "no cam signal" from "nothing configured" without
   guessing which one it is looking at. */
unsigned int dry_sched_need_sync;
unsigned int dry_next_ign_slot, dry_next_inj_slot;
int dry_spark_advance_x10;                /* signed               */
unsigned int dry_dwell_x100, dry_inj_pulse_us;
/* see hcsched_dry.h */
unsigned char dry_skip_ratio, dry_rev_spark_cut;
unsigned int dry_rev_limit, dry_rev_hyst, dry_inj_phase_x10;
unsigned char hc_prime_on;
unsigned int dry_spark_skips;
unsigned int hc_plan_generation;
#define planner_generation hc_plan_generation
#define collect_during_plan hc_plan_collect_f
#define count_tooth hc_plan_count_tooth_f
#define advance_angle_epoch hc_plan_advance_epoch_f
unsigned int far hc_plan_advance_epoch_f(unsigned int angle);
void far hc_plan_collect_f(void);
void far hc_plan_count_tooth_f(unsigned int angle);
static unsigned int skip_lfsr;
unsigned int dry_dwell_start_angle, dry_spark_angle;
unsigned int dry_inj_start_angle, dry_inj_end_angle;
/* V97 sequential with fallback - see hcsched_dry.h */
unsigned char dry_seq_active;
unsigned int dry_seq_inj_mask, dry_seq_skips, dry_seq_enters, dry_seq_leaves;
unsigned int dry_inj_width_us, dry_inj_nofree;

unsigned int hc_plan_cap_angle[CAP_N], hc_plan_cap_stamp[CAP_N], cap_dt[CAP_N];
volatile unsigned char hc_plan_cap_head, hc_plan_cap_tail;
#define cap_angle hc_plan_cap_angle
#define cap_stamp hc_plan_cap_stamp
#define cap_head hc_plan_cap_head
#define cap_tail hc_plan_cap_tail
/* Physical deadlines/ownership now live in hcdeadline711.c, near RAM. */
static void publish_edge(unsigned int target, unsigned int stamp,
    unsigned int dt, unsigned long ahead, unsigned char type, unsigned char slot);

/* THE LONG-HORIZON TABLE LIVES IN EXTERNAL SRAM. See TGT_RAM_SCHEDPLAN.
   Macros rather than pointers so every use below reads exactly as it did when
   these were near arrays - the only thing that changed is where they are. */
#define PLANBUF     ((unsigned char huge *)(TGT_EXTRAM_BASE                                             + TGT_RAM_SCHEDPLAN))
#define plan_epoch  ((unsigned long huge *)PLANBUF)
#define plan_type   (PLANBUF + 4u * PLAN_N)
#define plan_slot   (PLANBUF + 5u * PLAN_N)
/* PLANBUF + 6 * PLAN_N .. + 4 * CAP_N is unused: the ring holds T1 stamps. */
#define ign_token   ((unsigned int huge *)(PLANBUF + 6u * PLAN_N + 4u * CAP_N))
#define SCHED_LOCK(p)   HC_ATOMIC_ENTER(p)   /* the one convention, hcatomic.h */
#define SCHED_UNLOCK(p) HC_ATOMIC_EXIT(p)
#define SCHED_SUPPRESS() do { unsigned int _sp; SCHED_LOCK(_sp); \
    if(HC_DL_DIAG.suppressed!=0xFFFFu) HC_DL_DIAG.suppressed++; SCHED_UNLOCK(_sp); } while(0)
unsigned long hc_plan_epoch;
#define angle_epoch hc_plan_epoch
static unsigned int angle_last;
static unsigned char angle_valid;
/* set by advance_angle_epoch() when the step it measured was a whole
   half-cycle plus an ordinary tooth - the decoder moved the half (a cam
   phase decision), not the crank. plan_tooth() consumes it. */
static unsigned char phase_shifted;

/* THE GAP IS A TOOTH STEP, NOT A DISCONTINUITY.
 *
 * The decoder does not deliver the edge that ENDS the missing-tooth interval
 * (it is only a candidate); the next edge confirms it and is delivered with
 * the whole span since the last tooth before the gap: (gap + 2) teeth, 24.0
 * degrees on a 60-2. V89 treated any step over 18.0 degrees as a decoder
 * discontinuity, so on that one tooth per revolution the window collapsed to
 * one tooth and every event due in the 12 degrees before it was neither due
 * nor caught up - the spark cursor stopped there for good while the dwell
 * cursor kept going. On the AWT (first vehicle test, 2026-09-26) that held all
 * four coils ON for the whole crank and cut batch injection to ~1 ms.
 *
 * g_gap_step is that confirming step, g_pre_gap the ENGINE angle (mod 360) of
 * the last tooth before the gap: from that tooth the next delivered tooth is
 * g_gap_step away, so it looks that far ahead instead of one tooth. Both are
 * derived from the page with the decoder's own arithmetic in
 * geometry_refresh(); 0xFFFF = no gap tooth known. */
static unsigned int g_gap_step;
/* THE WHEEL'S TOOTH WIDTH IN TENTHS OF A DEGREE - see the note above
   queue_event(); declared here since V92 because the epoch step limit uses it. */
static unsigned int  g_tooth_x10;
static unsigned int g_pre_gap;

/* V90 overdwell watch and planner reentry guard - see hc_drysched_overdwell_service(). */
static unsigned char rev_cut;
#define REV_HYST_RPM 200u
static unsigned int ovd_last;
unsigned int dry_sched_overdwell;           /* releases it had to make      */
/* coils the watch released and the HAL now refuses to turn ON, until
   the next hc_drysched_cancel() (sync lost / engine stopped) or boot. A
   scheduler that keeps starting dwells with no spark would otherwise get a
   charge-release cycle - a spark at an angle nobody chose - every
   revolution. Recovery is deterministic: stop, re-sync, run.
   V99: ONLY AFTER THREE IN A ROW. V91 latched on the FIRST overdwell, and a
   running engine produces single ones legitimately: a sharp tip-in drops
   the alpha-N ignition advance by 20+ deg while coils are already charging,
   the spark angle moves later and the charge outlasts 1.5 x dwell (at
   1500 rpm 20 deg is 2.2 ms). Each such coil was then dead until the engine
   STALLED (the cancel) - the car's "dies on a sharp throttle as if the
   ignition were cut" (2026-10-02, V98r2). rusEFI auto-fires and charges the
   next event normally ([tag:overdwell]); so does this now. A coil that
   overdwells on THREE consecutive charges with no normal spark between them
   is the V89 defect class (events missing) and is latched exactly as
   before. ovd_c1/ovd_c2: the coils with one / two consecutive overdwells. */
unsigned int hc_ign_ovd_latch;

static unsigned char sched_busy;            /* reentry guard, see service() */

/* ============================================ EVENTS REACH REAL OUTPUTS ==
 *
 * V63. Until now this module was, in its own words, "deliberately
 * counting-only ... the timing foundation, not an output backend", and every
 * consumer of dry_spark_angle and dry_inj_start_angle was the TunerStudio
 * publisher. These two functions are the backend.
 *
 * THE MAPPING IS SLOT -> SEMANTIC, AND NOTHING HERE KNOWS A PIN. A slot is a
 * logical 1-based output index that the STRATEGY chose (hc_plan.c); the
 * semantic is what the HAL understands; the HAL turns the semantic into a
 * configured cavity and the cavity into a port bit. Three layers, and this
 * file is the first of them, so a wasted-spark engine and a sequential one
 * differ here only in which slot arrives.
 *
 * HC_PLAN_SLOT_ALL is 0 and means every output of that kind together, which
 * is exactly what batch injection and a paired wasted spark are.
 *
 * THE PERMISSION LAYER IS NOT CONSULTED HERE. hc_hal_out() asks it, per class,
 * on every call - so a coil cannot fire before the crank is synchronised even
 * if an event somehow reached this point. Checking it twice in two places is
 * how the two copies eventually disagree.
 */
static unsigned int sub720(unsigned int a, unsigned int b)
{
    return (a >= b) ? (unsigned int)(a - b)
                    : (unsigned int)(a + 7200u - b);
}

/* THE EPOCH IS AN UNBOUNDED ANGLE ACCUMULATOR AND IT USED TO WRAP AT 2^32.
 *
 * angle_epoch counts tenths of a crank degree since sync and never decreases.
 * At 7500 rpm that is 450 000 counts a second, so a 32-bit accumulator reaches
 * its end in 2 hours 39 minutes; at idle it takes about a day. An endurance
 * run or a long dyno session reaches it.
 *
 * TWO THINGS BROKE THERE, and neither announced itself.
 *
 * 1. plan_epoch[i] is angle_epoch plus a horizon of at most 7200, so near the
 *    end it wrapped to a small number while angle_epoch was still huge. Every
 *    plain `plan_epoch[i] < angle_epoch` test then read "already past" and
 *    cancelled the event. At 7500 rpm that is a ~16 ms burst of dropped
 *    ignition and injection events - a misfire, once every few hours, which is
 *    the hardest kind of fault to ever reproduce.
 *
 * 2. Worse, and permanent: ev_angle is plan_epoch % 7200, and 2^32 is NOT a
 *    whole number of 720-degree cycles - 2^32 mod 7200 = 1696. So after a wrap
 *    every scheduled angle was off by 169.6 degrees until the next resync.
 *
 * THE FIX IS TWO PARTS.
 *
 * The accumulator is rebased at DRY_EPOCH_WRAP, which IS a whole number of
 * cycles, so the modulo stays aligned across the rebase. Every live plan is
 * shifted by the same amount, so all relative distances survive exactly.
 * Anything already behind the epoch is cancelled first, which is what would
 * have happened to it anyway and guarantees the subtraction cannot underflow.
 *
 * And the ordering test in stage_long_horizon() is a SIGNED difference, which
 * is correct for any horizon under 2^31 counts - the real horizon is 7200 -
 * and would have survived even the old 2^32 wrap.
 *
 * The rebase costs one pass over 16 plan entries roughly every two hours.
 * dry_sched_rebases counts them, so the bench can see it happen instead of
 * taking this comment's word for it.
 */
#define DRY_EPOCH_WRAP  (7200uL * 500000uL)   /* 3 600 000 000 = 500 000 cycles */

static void epoch_rebase(void)
{
    unsigned int i;

    for (i = 0; i < PLAN_N; i++) {
        if (plan_type[i] != EV_NONE && plan_epoch[i] < angle_epoch) {
            plan_type[i] = EV_NONE;
            if (dry_sched_pending) dry_sched_pending--;
            if (dry_sched_missed != 0xFFFFu) dry_sched_missed++;
        }
    }
    angle_epoch -= DRY_EPOCH_WRAP;
    for (i = 0; i < PLAN_N; i++) {
        if (plan_type[i] != EV_NONE) {
            plan_epoch[i] -= DRY_EPOCH_WRAP;
        }
    }
    if (dry_sched_rebases != 0xFFFFu) dry_sched_rebases++;
}

/* Returns the step just taken, in 0.1 deg, or 0 if there is no previous tooth
   to measure from. plan_tooth() uses it as the staging WINDOW, which is what
   removed the last 60-2 constant from that function. */
unsigned int far advance_angle_epoch(unsigned int angle)
{
    unsigned int step = 0u;

    if (!angle_valid) {
        angle_epoch = angle;
        angle_last = angle;
        angle_valid = 1;
        dry_sched_status |= DRY_ST_ANGLE_VALID;
    } else {
        step = sub720(angle, angle_last);
        /* A PHASE MOVE IS NOT A DISCONTINUITY. The cam decided the
           other half: the angle jumped by 360 degrees plus the ordinary
           tooth step. The crank did not move 366 degrees; it moved one
           tooth, and every 360-degree-periodic plan (batch, wasted) is
           exactly where it was. */
        if (step > 3600u
            && (unsigned int)(step - 3600u) <= (unsigned int)(g_gap_step + g_tooth_x10)) {
            step = (unsigned int)(step - 3600u);
            phase_shifted = 1u;
        }
        /* A 60-2 capture advances 6 degrees, or 24 on the tooth that confirms
           the gap (see g_gap_step). Anything past the wheel's own gap step is
           a decoder discontinuity rather than a tooth, and cancellation is
           owned by the caller. V89 had 180 here - smaller than the gap step
           the decoder actually delivers. */
        /* + ONE TOOTH, for a reference mark accepted with a +/-1
           tooth correction (hctrig_me711.c): the confirming edge then
           re-anchors a position that was one tooth behind, and the step is
           the gap step plus that tooth. Treating it as a discontinuity
           would stall a cursor for a whole cycle - the V89 failure mode. */
        if (step <= (unsigned int)(g_gap_step + g_tooth_x10)) {
            angle_epoch += (unsigned long)step;
        } else {
            step = 0u;
        }
        if (angle_epoch >= DRY_EPOCH_WRAP) {
            epoch_rebase();
        }
        angle_last = angle;
    }
    return step;
}

unsigned int hc_drysched_schedule_after(unsigned int angle_x10,
                                        unsigned char type,
                                        unsigned char slot)
{
    unsigned int i, ps, generation = hc_dl_generation;
    if (!angle_valid || angle_x10 > 7200u || type == EV_NONE) return 0u;
    for (i = 0; i < PLAN_N; i++) if (plan_type[i] == EV_NONE) {
        SCHED_LOCK(ps);
        if (generation != hc_dl_generation || !angle_valid || plan_type[i] != EV_NONE) {
            SCHED_UNLOCK(ps); return 0u;
        }
        plan_epoch[i] = angle_epoch + (unsigned long)angle_x10;
        plan_slot[i] = slot;
        plan_type[i] = type;
        if (dry_sched_pending != 0xFFFFu) dry_sched_pending++;
        SCHED_UNLOCK(ps);
        return 1u;
    }
    if (dry_sched_missed != 0xFFFFu) dry_sched_missed++;
    return 0u;
}

/* THE CALLER PASSES THE DELTA, and that is not a micro-optimisation.
 *
 * This used to compute `sub720(target, start)` itself - with 7200 COMPILED IN,
 * which is a four-stroke. On a two-stroke the cycle is 3600 and every angle
 * past 3600 would have wrapped against the wrong modulus, silently, on a
 * scheduler that had just been made configurable in every other respect.
 *
 * Passing the delta fixes that (the caller knows hc_plan_cycle), removes a
 * duplicate modular subtract per event, and lets the caller reject an event
 * without a call at all. */
/* The tooth context, shared by plan_tooth(), walk_kind() and queue_event()
   through file statics rather than through six more arguments. Keil passes
   the first few in registers and spills the rest, and walk_kind() is called
   four times per tooth.

   DECLARED HERE, ABOVE queue_event(), rather than next to walk_kind() where
   it used to sit: queue_event() now reads w_stamp/w_dt/w_window itself. */
unsigned int hc_plan_angle, w_stamp, w_dt, w_window;
/* how far AHEAD this tooth stages - the distance to the next tooth the
   decoder will deliver. w_window stays the step just TAKEN, which is what
   the catch-up ("just behind") test needs. They differ on exactly two
   teeth per revolution: the last tooth before the gap (ahead = gap step)
   and the tooth that confirms it (behind = gap step). */
unsigned int hc_plan_ahead;
/* THE KNOCK RETARD OF THE EVENT BEING STAGED, 0.1 deg, set by
   walk_kind() for an ignition kind (0 for injection) and added to the delta
   AFTER queue_event()'s window test. A retard only ever DELAYS an event, so
   the cursor still finds it at the shared offset (the list stays sorted and
   the due test is unchanged) and it is staged that much later; the dwell
   start and the spark of one slot move together, so the dwell time holds.
   HC_KN711.slot_ret[] is written by hcknock711.c in the main loop (a byte:
   no torn read). */
static unsigned int w_extra;
#define KN_RET(s)  ((unsigned int)HC_KN711.slot_ret[(s) & 0x0Fu])

/* THE WHEEL'S TOOTH WIDTH IN TENTHS OF A DEGREE, hc_plan_tooth_x10(teeth).
   Declared here rather than with the other geometry statics below because
   queue_event() and stage_long_horizon() scale angle to time with it, and C
   wants it in scope first. geometry_refresh() is what assigns it. */
/* (declared above, with g_gap_step: advance_angle_epoch() needs it) */

/* FOUR ARGUMENTS, NOT SEVEN, AND THAT IS A REGISTER-PRESSURE DECISION.
 *
 * stamp, dt and window were passed in by both call sites as w_stamp, w_dt and
 * w_window - THE FILE STATICS THIS FUNCTION CAN SIMPLY READ. Passing them
 * meant walk_kind() had to keep three more values live across the call, and
 * with ang, slt, n, want, c and guard already live the C166 compiler ran out
 * of registers and spilled the loop's whole working set to a stack frame.
 * Reading them here costs the same loads in one place instead of marshalling
 * them at every call. */
static void queue_event(unsigned int target, unsigned int delta,
                        unsigned char type, unsigned char slot)
{
    unsigned long ahead;
    unsigned int span;
    if (delta >= hc_plan_ahead) return;
    span = (unsigned int)(delta + w_extra);
    ahead = (unsigned long)w_dt * span;          /* 16x16 MULU */
    /* Native 32:16 DIVLU whenever the quotient fits 16 bits - every case but
       a stalling crank - instead of the ?C_ long-division helper per event. */
    if ((unsigned int)(ahead >> 16) < g_tooth_x10)
        ahead = (unsigned int)(ahead / (unsigned int)g_tooth_x10);
    else
        ahead /= g_tooth_x10;
    publish_edge(target, w_stamp, w_dt, ahead, type, slot);
}

static void stage_long_horizon(unsigned int stamp, unsigned int dt,
                               unsigned int window)
{
    unsigned int i;
    unsigned int tx = g_tooth_x10 ? g_tooth_x10 : 60u;
    /* NOTHING STAGED MEANS NOTHING TO SCAN. dry_sched_pending is exactly the
       number of live plan entries - every path that sets or clears plan_type[]
       maintains it - so this is not a cached duplicate of the array, it is the
       array's own count. Sixteen iterations per tooth at 7500 rpm is 120 000
       loop passes a second spent proving an empty table is empty. */
    if (dry_sched_pending == 0u) {
        return;
    }
    for (i = 0; i < PLAN_N; i++) if (plan_type[i] != EV_NONE) {
        /* SIGNED difference, not `plan < epoch`. The horizon is at most 7200
           counts, so a signed 32-bit difference is exact and stays exact
           across any wrap of the accumulator. See DRY_EPOCH_WRAP above. */
        long ahead = (long)(plan_epoch[i] - angle_epoch);
        if (ahead < 0) {
            plan_type[i] = EV_NONE;
            if (dry_sched_pending) dry_sched_pending--;
            if (dry_sched_missed != 0xFFFFu) dry_sched_missed++;
        } else {
            unsigned long delta = (unsigned long)ahead;
            if (delta < (unsigned long)window) {
                unsigned int angle = (unsigned int)(plan_epoch[i] % 7200uL);
                publish_edge(angle, stamp, dt, ((unsigned long)dt * delta) / tx,
                             plan_type[i], plan_slot[i]);
                plan_type[i] = EV_NONE;
                if (dry_sched_pending) dry_sched_pending--;

            }
        }
    }
}

/* Linked-image regression hooks. They use the same epoch/staging core but do
   not create the recurring V8 plan, allowing exhaustive horizon tests to
   isolate one event at a time. They have no protocol binding or output path. */
/* Drive the accumulator to just below its rebase point. 3.6 billion counts
   cannot be simulated one tooth at a time, and a defect that only appears
   after two hours of running is exactly the one that needs a test. */
/* Two words rather than one long, so nothing depends on how the compiler
   happens to split a 32-bit argument across a register pair - a test hook
   whose calling convention has to be guessed is not evidence. */
void hc_drysched_test_anchor(unsigned int angle_x10)
{
    angle_valid = 0;
    planner_generation = hc_dl_generation;
    (void)advance_angle_epoch((unsigned int)(angle_x10 % 7200u));
}

void hc_drysched_test_advance(unsigned int angle_x10, unsigned int stamp,
                              unsigned int tooth_dt)
{
    planner_generation = hc_dl_generation;
    (void)advance_angle_epoch((unsigned int)(angle_x10 % 7200u));
    /* 60 is this HOOK'S scenario - a 6.0 degree tooth - and it is the WINDOW
       argument, which is unrelated to the V68 divisor: stage_long_horizon()
       scales by g_tooth_x10, so the hook's arithmetic is unchanged. */
    stage_long_horizon(stamp, tooth_dt, 60u);
}

/* ------------------------------------------------- the engine's geometry --
 *
 * WHAT THIS REPLACED. Until now the loop below read:
 *
 *     for (i = 0; i < 8u; i++) {
 *         unsigned int fire = (unsigned int)(i * 900u);
 *         unsigned int inj_end = sub720(fire, 3600u);
 *
 * Eight cylinders, evenly spaced 90 degrees apart, on a 720 degree cycle, one
 * event each, with injection ending 360 degrees before TDC. That is a Cayenne
 * V8 with sequential ignition, compiled in - in a firmware whose stated
 * premise is that the engine is configuration. Every one of those numbers has
 * been in the universal configuration the whole time: CFG_CYLINDERS,
 * CFG_STROKES, the twelve-entry CFG_TDC_CYL/CFG_U_TDC_CYL_EXT table,
 * CFG_U_INJ_STRATEGY, CFG_U_IGN_STRATEGY and CFG_INJ_START_DEG_X10.
 *
 * IT ALSO READ CFG_INJ_START_DEG_X10 BACKWARDS - or rather, it did not read
 * the field at all and hardcoded 3600 as an END angle, while hcinj.c on the
 * ME7.5 board has always used the same word as a START angle before TDC. One
 * page, one byte offset, two meanings. hc_plan.h now carries the one
 * definition and both targets are on it.
 *
 * WHY IT IS CACHED. The geometry is read per TOOTH, and at 7500 rpm on a 60-2
 * wheel that is 7500 teeth a second. Twelve TDC words live partly above
 * HC_CFG_CORE, so re-reading the table every tooth would put a measurable
 * percentage of the CPU into configuration decoding for values that only
 * change while the engine is stopped.
 *
 * Every cached field is RPM_ZERO_APPLY or RESTART_REQUIRED - checked against
 * build/generated/hc_config_model.csv, not assumed - so hc_cfg_active_rev,
 * which increments exactly when a group is copied into ACTIVE, is a sufficient
 * and correct invalidation signal. CFG_INJ_START_DEG_X10 is LIVE_APPLY and is
 * therefore deliberately NOT cached: it is read every tooth, which costs one
 * near-RAM word because it lives below HC_CFG_CORE.
 */
static unsigned int  g_rev;              /* hc_cfg_active_rev this was built at */
static unsigned char g_valid;
unsigned int  hc_plan_cycle;
/* g_tooth_x10 is DECLARED ABOVE queue_event(), with the rest of this block
   left here: the angle-to-time conversion needs the wheel's tooth width and
   sits four hundred lines earlier in the file. */
static unsigned char g_cyl;
static unsigned char g_ign_cyls, g_inj_cyls;
static unsigned char g_ign_rep, g_inj_rep;
static unsigned char g_ign_strat, g_inj_strat;
/* the strategy is SEQUENTIAL on a four-stroke - its anchors carry a
   twin 360 degrees later (HC_SLOT_TWIN) that fires only without cycle sync. */
static unsigned char g_ign_seq, g_inj_seq;
/* injTimingMode 1 = the injection angle is where the pulse ENDS */
static unsigned char g_inj_eoi;

/* ------------------------------------------- the pre-resolved cycle plan --
 *
 * THE MEASUREMENT THAT FORCED THIS. plan_tooth() used to re-plan the WHOLE
 * cycle on EVERY tooth: for each cylinder, for each repeat, compute the spark
 * angle, the dwell angle, the injection start and end, call
 * hc_plan_ign_slot()/hc_plan_inj_slot(), and throw away everything outside one
 * tooth window. tools/me711_plan_cost_proof.py executed that out of the linked
 * image and measured, at 7500 rpm on a 60-tooth wheel against ~1330 available
 * instructions:
 *
 *      4 cylinders   1262      6 cylinders   1584
 *      8 cylinders   1814     12 cylinders   2412
 *
 * A V8 was therefore inside its own tooth period only below about 5500 rpm.
 * That is a scheduler that cannot run this engine, and no amount of arithmetic
 * tuning fixes an O(cylinders) search performed 7500 times a second to place
 * at most a couple of events.
 *
 * WHAT IS ACTUALLY CONSTANT, AND WHAT IS NOT. Split the event angle:
 *
 *      event angle = ANCHOR - OFFSET
 *
 * The ANCHOR is the cylinder's TDC (plus one revolution per repeat). It
 * depends only on the configuration and changes only when the page changes.
 * The OFFSET is shared by every event of one KIND on the whole engine:
 *
 *      dwell start   advance + dwell angle      spark   advance
 *      inj start     injection angle BTDC       inj end (that - pulse angle)
 *
 * So there are exactly FOUR offsets per tooth, not four per cylinder - and the
 * per-cylinder part is a fixed, sorted list built once at apply time.
 *
 * THE HOT PATH IS THEN A CURSOR, NOT A SEARCH. The lists are sorted ascending
 * and the crank only ever advances, so the next event of each kind is the one
 * the cursor points at. Per tooth each kind costs one modular add, one modular
 * subtract and one compare; a cursor step happens only when an event actually
 * fires, so the total cursor movement over a revolution is the number of
 * events in that revolution. That is O(1) amortised per tooth against
 * O(cylinders) before, and it is measured by the same gate.
 *
 * NOTHING HERE IS ENGINE-SPECIFIC. Cylinder count, stroke count, the TDC
 * table, both strategies, their repeat counts and the slot mapping all still
 * come from the page; they are simply read at the CONFIGURATION boundary
 * instead of inside the tooth. hc_plan.c is still the only place that knows
 * what any of it means.
 */
/* Kinds, and they index hc_plan_cursors[] - not the HC_DRY_* wire values. */
#define K_DWELL   0u
#define K_SPARK   1u
#define K_INJ_ON  2u
#define K_INJ_OFF 3u

/* THE TWO LISTS ARE NOT THE SAME LENGTH, and the asymmetry is hc_plan.c's.
 *
 * IGNITION walks every cylinder whatever the strategy - even a distributor
 * does, because each cylinder gets its own event at its own advance - and
 * WASTED COP repeats each one 360 degrees later. Twelve cylinders x two
 * repeats = 24.
 *
 * INJECTION never reaches that. hc_plan_inj_repeats() returns 2 for exactly
 * one strategy, BATCH, and hc_plan_inj_cyls() walks exactly ONE cylinder for
 * batch - so batch is 1 x 2 = 2. Every other strategy repeats once, so the
 * worst case is twelve cylinders x one = 12. Sizing this 24 "to match" would
 * cost twelve words of near RAM to hold entries nothing can generate. */
#define IGLIST_N    (HC_PLAN_MAX_CYL * 2u)   /* wasted COP repeats each one  */
/* SEQUENTIAL injection now plans each cylinder AND its fallback twin
   (x2), which is at most 8 x 2 on this board - it has eight injector
   drivers (ev_drive() takes slots 1..8), so a sequential engine with more
   cylinders than that cannot be routed. Semi-sequential still walks every
   cylinder once (12). 16 covers both; list_insert() refuses beyond it. */
#define INLIST_N    16u

unsigned int  hc_plan_ign_anchors[IGLIST_N];    /* ignition anchors, ASCENDING */
static unsigned char ig_slot[IGLIST_N];
static unsigned char ig_n;
unsigned int  hc_plan_inj_anchors[INLIST_N];    /* injection anchors, ASCENDING */
unsigned char hc_plan_inj_slots[INLIST_N];
static unsigned char in_n;

unsigned char hc_plan_cursors[4];
static unsigned char cursors_valid;

/* An event that had to be issued immediately because the angle moved under
   the cursor - a large advance or dwell change between two teeth. Not an
   error; a number, so a bench can see how often it happens. */
unsigned int dry_sched_catchup;

/* Insertion into a sorted list. PLANLIST_N is 24 and this runs once per
   configuration change, so the O(n^2) is 576 operations on a stopped engine
   and buys a hot path that never sorts anything. */
static void list_insert(unsigned int *ang, unsigned char *slot,
                        unsigned char *n, unsigned char cap,
                        unsigned int a, unsigned char s)
{
    unsigned char i, j;

    if (*n >= cap) {
        return;
    }
    for (i = 0u; i < *n; i++) {
        if (ang[i] > a) {
            break;
        }
    }
    for (j = *n; j > i; j--) {
        ang[j] = ang[j - 1u];
        slot[j] = slot[j - 1u];
    }
    ang[i] = a;
    slot[i] = s;
    (*n)++;
}

static void geometry_refresh(void)
{
    unsigned char i, r;
    unsigned char strokes;
    unsigned int teeth;
    unsigned int any_tdc = 0u;
    /* LOCAL, not a static cache. Nothing outside this function needs the TDC
       table once the anchor lists exist, and twelve words of near RAM are
       worth more to the rest of the firmware than to a table read once per
       configuration change. */
    unsigned int g_tdc[HC_PLAN_MAX_CYL];
    unsigned char fo = hc_cal_u8(CFG_U_FIRING_ORDER);   /* V98 */

    ig_n = 0u;
    in_n = 0u;
    cursors_valid = 0u;

    /* THE GAP, IN THE DECODER'S OWN ARITHMETIC (hctrig_me711.c
       geometry_read() and slot_angle_x10(), same clamps, same rounding), so
       g_pre_gap equals the angle the decoder really delivers for the last
       tooth before the gap. Computed before the cylinder check: the epoch
       step limit needs it even when no engine is described. */
    {
        unsigned int n = cfg_u16(CFG_SY_TEETH);
        unsigned int gp = cfg_u8(CFG_SY_GAP);
        unsigned long num;
        unsigned int pre, one;

        if (n < 4u || n > 200u) n = 60u;
        if (gp == 0u || gp + 3u > n) gp = 2u;
        num = ((3600uL * 128uL) + (unsigned long)(n / 2u)) / (unsigned long)n;
        pre = (unsigned int)(((unsigned long)(n - gp - 1u) * num + 64uL) >> 7);
        one = (unsigned int)((num + 64uL) >> 7);
        g_gap_step = (unsigned int)(one + 3600u - pre);
        g_pre_gap = (unsigned int)((pre + hc_trig_rotation_x10(
                                    hc_cal_u16(CFG_U_TRIG_ANGLE_X10)))
                                   % 3600u);
    }

    g_rev = hc_cfg_active_rev;
    g_cyl = cfg_u8(CFG_CYLINDERS);
    if (g_cyl == 0u || g_cyl > HC_PLAN_MAX_CYL) {
        /* An unconfigured or absurd cylinder count. Publish NO geometry rather
           than a guessed one: geometry_valid() then keeps the scheduler idle,
           which is the honest state for an engine nobody has described. */
        g_valid = 0u;
        return;
    }
    strokes = cfg_u8(CFG_STROKES);
    hc_plan_cycle = hc_plan_cycle_x10(strokes);

    teeth = cfg_u16(CFG_SY_TEETH);
    g_tooth_x10 = hc_plan_tooth_x10(teeth);
    if (g_tooth_x10 == 0u) {
        g_tooth_x10 = hc_plan_tooth_x10(60u);   /* the decoder's own default */
    }

    g_ign_strat = hc_cal_u8(CFG_U_IGN_STRATEGY);
    g_inj_strat = hc_cal_u8(CFG_U_INJ_STRATEGY);
    g_ign_cyls = hc_plan_ign_cyls(g_cyl);
    g_inj_cyls = hc_plan_inj_cyls(g_cyl, g_inj_strat);
    g_ign_rep = hc_plan_ign_repeats(g_ign_strat, strokes);
    g_inj_rep = hc_plan_inj_repeats(g_inj_strat, strokes);
    /* SEQUENTIAL = the cylinder's event + a fallback twin 360 later */
    g_ign_seq = (unsigned char)(g_ign_strat == HC_IGN_SEQUENTIAL_COP
                                && strokes == 4u);
    g_inj_seq = (unsigned char)(g_inj_strat == HC_INJ_SEQUENTIAL
                                && strokes == 4u);
    if (g_ign_seq) g_ign_rep = 2u;
    if (g_inj_seq) g_inj_rep = 2u;
    g_inj_eoi = (unsigned char)(hc_cal_u8(CFG_U_INJ_TIMING_MODE) == 1u);

    for (i = 0u; i < HC_PLAN_MAX_CYL; i++) {
        /* CFG_TDC_CYL is eight wide and CFG_U_TDC_CYL_EXT carries 9..12, which
           is how twelve cylinders were added without moving one existing byte.
           hc_cal_u16 for the extension, NOT cfg_u16: it lives above
           HC_CFG_CORE and cfg_u16 takes an unsigned char offset, which is the
           truncation defect tests/test_config_access_types.py now guards. */
        g_tdc[i] = (i < 8u)
                 ? cfg_u16((unsigned char)(CFG_TDC_CYL + 2u * i))
                 : hc_cal_u16((unsigned int)(CFG_U_TDC_CYL_EXT
                                             + 2u * (unsigned int)(i - 8u)));
        /* REDUCED HERE, ONCE. The per-tooth loops use hc_plan_sub_fast_x10(),
           whose precondition is that both angles are already inside the cycle.
           This is where that becomes true, and it costs one division per
           cylinder per configuration change rather than two per cylinder per
           tooth. */
        /* A NAMED FIRING ORDER PLACES THE CYLINDERS (rusEFI
           engine_cylinder.cpp: cycle x position / cylinders), here at apply
           time and never per tooth. Custom (0) keeps the TDC angles. The
           validator refuses an order whose length is not the cylinder
           count; an unknown position falls back to the angle. */
        if (fo != 0u && i < g_cyl) {
            unsigned char pos = hc_fo_position(fo, (unsigned char)i,
                                               (unsigned char)g_cyl);
            if (pos != 0xFFu) {
                g_tdc[i] = (unsigned int)(((unsigned long)hc_plan_cycle * pos)
                                          / g_cyl);
            }
        }
        if (hc_plan_cycle != 0u) {
            g_tdc[i] %= hc_plan_cycle;
        }
        if (i < g_cyl && g_tdc[i] != 0u) {
            any_tdc = 1u;
        }
    }
    if (!any_tdc) {
        /* AN EMPTY TABLE IS NOT AN ENGINE WITH EVERY CYLINDER AT ZERO. A page
           whose TDC angles have never been filled in reads as all zeros, and
           taking that literally would stack every cylinder's events on top of
           each other at the same angle. Even spacing is the sane default, and
           it reproduces exactly what the hardcoded loop did for a V8:
           7200/8 = 900. */
        for (i = 0u; i < HC_PLAN_MAX_CYL; i++) {
            g_tdc[i] = hc_plan_even_tdc_x10(i, g_cyl, hc_plan_cycle);
        }
    }

    /* THE ANCHOR LISTS. This is the whole of the per-cylinder work that used
       to happen inside every tooth: which cylinders are walked, which logical
       slot each maps to, and where its repeats land. Sorted ascending so the
       hot path can use a cursor. */
    /* A PAIR IS TWO CYLINDERS 360 DEGREES APART IN THE FIRING ORDER,
       not cylinder index i and i + n/2 - that pairs 1/3 and 2/4 on a 1-3-4-2
       engine, whose TDCs are 180 apart (docs/ARCHITECTURE.md). The pair
       drives the output of its cylinder EARLIER in the firing order, as
       rusEFI's getIgnitionPinForIndex() does (1/4 on cylinder 1's output,
       3/2 on cylinder 3's). */
    HC_KN711.geom_n = 0u;         /* V97 knock: invalid while rebuilt */
    HC_KN711.geom_cycle = hc_plan_cycle;
    for (i = 0u; i < g_ign_cyls; i++) {
        unsigned int a = g_tdc[i];
        unsigned char s = hc_plan_ign_slot(i, g_cyl, g_ign_strat);
        if (g_ign_strat == HC_IGN_WASTED_PAIRED) {
            s = (unsigned char)(hc_plan_pair_lead(g_tdc, i, g_cyl) + 1u);
        }
        if (i < 8u) {             /* the knock driver's geometry */
            HC_KN711.geom_tdc[i] = a;
            HC_KN711.geom_slot[i] = s;
        }
        for (r = 0u; r < g_ign_rep; r++) {
            if (r) {
                a = hc_plan_next_rev_x10(a, hc_plan_cycle);
            }
            list_insert(hc_plan_ign_anchors, ig_slot, &ig_n, (unsigned char)IGLIST_N, a,
                        (unsigned char)(s | ((r && g_ign_seq) ? HC_SLOT_TWIN
                                                             : 0u)));
        }
    }
    for (i = 0u; i < g_inj_cyls; i++) {
        unsigned int a = g_tdc[i];
        unsigned char s = hc_plan_inj_slot(i, g_cyl, g_inj_strat);
        if (g_inj_strat == HC_INJ_SEMI_SEQ) {
            s = (unsigned char)(hc_plan_pair_lead(g_tdc, i, g_cyl) + 1u);
        }
        for (r = 0u; r < g_inj_rep; r++) {
            if (r) {
                a = hc_plan_next_rev_x10(a, hc_plan_cycle);
            }
            list_insert(hc_plan_inj_anchors, hc_plan_inj_slots, &in_n, (unsigned char)INLIST_N, a,
                        (unsigned char)(s | ((r && g_inj_seq) ? HC_SLOT_TWIN
                                                             : 0u)));
        }
    }
    HC_KN711.geom_n = (unsigned char)((g_ign_cyls > 8u) ? 8u : g_ign_cyls);
    /* Cold configuration work, once per plan rebuild. Paired/batch/fallback
       outputs may fire more than once per engine cycle. Clip against their
       shortest actual configured interval, not an assumed 720 degree period. */
    for (i=0;i<8u;i++) {
        unsigned char j,k;
        unsigned int span=hc_plan_cycle;
        for(j=0;j<in_n;j++) if(!(hc_plan_inj_slots[j]&HC_SLOT_MASK) || (hc_plan_inj_slots[j]&HC_SLOT_MASK)==i+1u) {
            for(k=0;k<in_n;k++) if(k!=j && (hc_plan_inj_slots[k]&HC_SLOT_MASK)==(hc_plan_inj_slots[j]&HC_SLOT_MASK)) {
                unsigned int delta=hc_plan_sub_x10(hc_plan_inj_anchors[k],hc_plan_inj_anchors[j],hc_plan_cycle);
                if(delta<span) span=delta;
            }
        }
        HC_DL_WIDTH.next_angle[i]=span;
    }
    g_valid = 1u;
}

/* the last planned tooth, for the knock driver's window arming (far,
   through hcfar_me711.c). Engine angle x10 at T1 stamp, one tooth's period
   and width; valid only while the geometry is and a tooth was planned. */
void hc_drysched_snap(void)
{
    unsigned int ps;
    /* Main loop vs the planner level: the four words are ONE tooth. */
    SCHED_LOCK(ps);
    HC_KN711.snap_valid = (unsigned char)(g_valid && cursors_valid
                                          && w_dt != 0u);
    HC_KN711.snap_angle = hc_plan_angle;
    HC_KN711.snap_stamp = w_stamp;
    HC_KN711.snap_dt = w_dt;
    HC_KN711.snap_tooth = g_tooth_x10;
    SCHED_UNLOCK(ps);
}

static unsigned char geometry_valid(void)
{
    if (!g_valid || g_rev != hc_cfg_active_rev) {
        geometry_refresh();
    }
    return g_valid;
}

/* time -> timer ticks, cached on the value it was computed from */
static unsigned int  cvt_dwell_src, cvt_inj_src;
static unsigned long cvt_dwell_ticks, cvt_inj_ticks;

/* Point every cursor at the next anchor of its kind.
 *
 * Called once, when the cursors have no meaning: at init, after a cancel,
 * after a resync, and whenever the configuration changed the lists. O(n) per
 * kind, on an engine that has just gained or regained position - never per
 * tooth.
 *
 * The trailing adjustment matters. If the nearest anchor is BEHIND the current
 * position by less than one tooth, seeding onto it would fire that event
 * immediately on the sync tooth - a spark commanded the instant position is
 * established, from an event the engine has already turned past. Skip it; the
 * next cycle places it correctly.
 */
/* The modular distance hc_plan_sub_fast_x10() computes, WITHOUT THE CALL.
 *
 * THE CALL WAS THE COST, NOT THE ARITHMETIC. walk_kind() calls it up to three
 * times per iteration, and because those are calls the C166 compiler must
 * assume the worst about its register bank across each one. With `ang`, `slt`,
 * `n`, `want`, `c` and `guard` all live across a call it ran out of registers
 * and emitted `ADD R0,#0FFF0H` - a sixteen-byte stack frame with every one of
 * those locals spilled to `[R0+n]` and re-read on each use. That spill, not
 * the subtraction, is why walk_kind() measured 449 instructions of a
 * 1431-instruction tooth for four invocations.
 *
 * IT IS THE SAME ARITHMETIC. The function clamps a and b into the cycle before
 * subtracting; both clamps are kept here. `cyc` must be non-zero, which is the
 * one precondition the function checks and this macro does not - plan_tooth()
 * returns before reaching any caller when hc_plan_cycle is 0, and
 * me711_plan_golden pins the two against each other.
 *
 * Arguments are used more than once, so every caller below passes plain
 * variables - never ang[c++] or a call. */
#define SUB_FAST(dst, a, b, cyc)                                        \
    do {                                                                \
        unsigned int _a = (a), _b = (b);                                \
        if (_a >= (cyc)) _a = (unsigned int)((cyc) - 1u);                \
        if (_b >= (cyc)) _b = (unsigned int)((cyc) - 1u);                \
        (dst) = (_a >= _b) ? (unsigned int)(_a - _b)                     \
                           : (unsigned int)(_a + (cyc) - _b);            \
    } while (0)

static void seed_cursors(unsigned int angle, unsigned int off_dw,
                         unsigned int off_sp, unsigned int off_is,
                         unsigned int off_ie)
{
    unsigned char k, i, best;
    unsigned int want, d, bestd;
    unsigned int *ang;
    unsigned char n;

    for (k = 0u; k < 4u; k++) {
        if (k < K_INJ_ON) {
            ang = hc_plan_ign_anchors;
            n = ig_n;
        } else {
            ang = hc_plan_inj_anchors;
            n = in_n;
        }
        hc_plan_cursors[k] = 0u;
        if (n == 0u) {
            continue;
        }
        switch (k) {
        case K_DWELL:   want = off_dw; break;
        case K_SPARK:   want = off_sp; break;
        case K_INJ_ON:  want = off_is; break;
        default:        want = off_ie; break;
        }
        ((unsigned int huge *)(TGT_EXTRAM_BASE+TGT_RAM_PLANOFF))[k]=want;
        want = (unsigned int)(angle + want);
        if (want >= hc_plan_cycle) {
            want = (unsigned int)(want - hc_plan_cycle);
        }
        best = 0u;
        bestd = 0xFFFFu;
        for (i = 0u; i < n; i++) {
            unsigned int a_i = ang[i];
            SUB_FAST(d, a_i, want, hc_plan_cycle);
            if (d < bestd) {
                bestd = d;
                best = i;
            }
        }
        /* STEP PAST ANY ANCHOR THE NEXT TOOTH HAS ALREADY PASSED, and until
         * V69 this only stepped past one that was BEHIND.
         *
         * An anchor `bestd` ahead of `want` sits at engine angle
         * `angle + bestd`, so anything with `bestd < w_window` falls inside
         * THE SEEDING TOOTH'S OWN WINDOW - and this tooth deliberately
         * schedules nothing ("this tooth establishes the cursors"). One tooth
         * later `want` has moved a whole window and that anchor is in the
         * past, so walk_kind() issued it through the CATCH-UP branch with
         * delta forced to 0.
         *
         * MEASURED, 6 cylinders at 12000 rpm: THREE of the four kinds landed
         * inside the first window - dwell 37 ahead, injection start 0 ahead,
         * injection end 5 ahead - so the tooth after seeding staged three
         * events and executed all three at once. That burst is the whole
         * difference between the worst tooth of a revolution and the steady
         * one: 1364 against 780, and it is what me711_plan_cost_proof fails
         * on. bench measurements.
         *
         * THE SAFETY DIRECTION IS THE RIGHT WAY ROUND, and that is why this is
         * allowed to skip an event at all. off_dw > off_sp, so dwell A always
         * precedes spark A in angle. If spark A is close enough to be skipped,
         * dwell A is further in the past and is skipped too. If dwell A is
         * skipped, spark A is a whole dwell_angle ahead - 216 crank degrees at
         * this operating point - and is KEPT. So "dwell kept, spark skipped",
         * the pairing that leaves a coil charging with nothing to end it, is
         * unreachable; the reachable case is a spark on a coil that was never
         * charged, which is no spark and no harm.
         *
         * Bounded by n. Anchors are `cycle / cylinders` apart - 600 tenths at
         * twelve cylinders - so more than one inside a window needs a wheel
         * coarser than any this decoder accepts, but a seeding path that could
         * loop is not worth the argument. */
        for (i = 0u; i < n; i++) {
            if (bestd >= hc_plan_ahead
                && bestd < (unsigned int)(hc_plan_cycle - w_window)) {
                break;                  /* more than a window ahead: keep it */
            }
            best = (unsigned char)(best + 1u);
            if (best >= n) {
                best = 0u;
            }
            SUB_FAST(bestd, ang[best], want, hc_plan_cycle);
        }
        hc_plan_cursors[k] = best;
    }
    cursors_valid = 1u;
}

/* Distance of the next cursor eligible for this publication window. A
   behind-angle catch-up ranks first; unavailable kinds rank last. */
static unsigned int due_distance(unsigned char kind,unsigned int off)
{
    unsigned int want,d;
    unsigned int *anchors=kind<K_INJ_ON?hc_plan_ign_anchors:hc_plan_inj_anchors;
    if(!(kind<K_INJ_ON?ig_n:in_n)) return 0xFFFFu;
    want=(unsigned int)(hc_plan_angle+off);
    if(want>=hc_plan_cycle) want-=hc_plan_cycle;
    SUB_FAST(d,anchors[hc_plan_cursors[kind]],want,hc_plan_cycle);
    if(d>=(unsigned int)(hc_plan_cycle-w_window)) return 0u;
    return d<hc_plan_ahead?d:0xFFFFu;
}

/* One kind of event, one cursor, one tooth.
 *
 * `off` is how far BEFORE its anchor this kind of event happens, already
 * reduced modulo the cycle. `emit` is 0 when the kind is configured away (no
 * dwell, no pulse width) - the cursor still advances, so that turning the kind
 * back on does not leave a cursor a whole cycle out of date.
 */
static void walk_kind(unsigned char k, unsigned int off, unsigned char type,
                      unsigned char emit)
{
    unsigned int *ang;
    unsigned char *slt;
    unsigned char n, c, guard;
    unsigned int want, d, target, a_c;

    if (k < K_INJ_ON) {
        ang = hc_plan_ign_anchors;
        slt = ig_slot;
        n = ig_n;
    } else {
        ang = hc_plan_inj_anchors;
        slt = hc_plan_inj_slots;
        n = in_n;
    }
    if (n == 0u) {
        return;
    }

    /* Both terms are already inside the cycle, so one conditional subtract is
       the whole reduction - no division in the tooth path. */
    want = (unsigned int)(hc_plan_angle + off);
    if (want >= hc_plan_cycle) {
        want = (unsigned int)(want - hc_plan_cycle);
    }

    c = hc_plan_cursors[k];
    for (guard = 0u; guard < n; guard++) {
        a_c = ang[c];
        SUB_FAST(d, a_c, want, hc_plan_cycle);
        if (d < hc_plan_ahead) {
            if (emit) {
                SUB_FAST(target, a_c, off, hc_plan_cycle);
                w_extra = (k < K_INJ_ON) ? KN_RET(slt[c] & HC_SLOT_MASK) : 0u;
                queue_event(target, d, type, slt[c]);
            }
        } else if (d >= (unsigned int)(hc_plan_cycle - w_window)) {
            /* THE ANCHOR IS BEHIND US, by less than one tooth. The offset
               moved further than the crank did between two teeth - a large
               advance or dwell change - and stepped over this event. Replanning
               it for bounded publication is the safe answer: skipping it is a misfire and a
               missed injection, and waiting a whole cycle is worse. */
            if (emit) {
                SUB_FAST(target, a_c, off, hc_plan_cycle);
                w_extra = (k < K_INJ_ON) ? KN_RET(slt[c] & HC_SLOT_MASK) : 0u;
                queue_event(target, 0u, type, slt[c]);
                if (dry_sched_catchup != 0xFFFFu) dry_sched_catchup++;
            }
        } else {
            break;                  /* still ahead: nothing more this tooth */
        }
        c = (unsigned char)(c + 1u);
        if (c >= n) {
            c = 0u;
        }
    }
    hc_plan_cursors[k] = c;
}

/* MOVE EVERY CURSOR TO THE SAME EVENT, 360 DEGREES ON.
 *
 * After the half moves, the anchor each cursor points at is 360 degrees
 * away from where the crank now is. On a batch or wasted plan every anchor
 * has a twin 360 degrees on with the same slot, and that twin is the same
 * physical event: point the cursor there and nothing is skipped or
 * repeated. On a sequential plan there is no twin - the events were aimed
 * at the wrong cylinders - so the cursors are re-seeded, and
 * hc_drysched_service() has already cancelled whatever was pending when
 * the cycle was withdrawn. Runs only on the tooth after a phase decision. */
static void remap_cursors_360(void)
{
    unsigned char k, j, n;
    unsigned int *ang;
    unsigned char *slt;
    unsigned int want;

    if (!cursors_valid || hc_plan_cycle != 7200u) {
        return;
    }
    for (k = 0u; k < 4u; k++) {
        if (k < K_INJ_ON) { ang = hc_plan_ign_anchors; slt = ig_slot; n = ig_n; }
        else              { ang = hc_plan_inj_anchors; slt = hc_plan_inj_slots; n = in_n; }
        if (n == 0u) {
            continue;
        }
        want = (unsigned int)(ang[hc_plan_cursors[k]] + 3600u);
        if (want >= 7200u) want = (unsigned int)(want - 7200u);
        /* a sequential plan HAS the twin now (the same slot with
           HC_SLOT_TWIN), so it remaps like a wasted one: the event 360 on is
           the same cylinder's other stroke. Only its role changes. */
        for (j = 0u; j < n; j++) {
            if (ang[j] == want
                && ((slt[j] ^ slt[hc_plan_cursors[k]]) & HC_SLOT_MASK) == 0u) {
                break;
            }
        }
        if (j >= n) {
            cursors_valid = 0u;          /* no twin: re-seed on this tooth */
            return;
        }
        hc_plan_cursors[k] = j;
    }
}

/* A TOOTH THE PLANNER ONLY COUNTS. Every capture advances the
   angle epoch - its continuity is the reference for every staged event - but
   the per-cylinder walk runs on the newest capture and at most once per
   HC_PLAN_PERIOD_TICKS (hc_drysched_service). Events are staged a whole
   HC_PLAN_HORIZON_TICKS ahead, so nothing can come due between two walks.
   plan_acc carries the angle the skipped teeth covered into the next walk's
   catch-up window; plan_acc_bad marks a discontinuity among them. */
unsigned int hc_plan_acc;
unsigned char hc_plan_acc_bad;
#define plan_acc hc_plan_acc
#define plan_acc_bad hc_plan_acc_bad
static unsigned int plan_last;

static void plan_tooth(unsigned int angle, unsigned int stamp, unsigned int dt)
{
    unsigned long dwell_ticks, inj_ticks;
    unsigned int dwell_angle, inj_angle, soi_x10, adv_x10;
    unsigned int off_dw, off_sp, off_is, off_ie;
    unsigned int window;

    if (!dt) return;

    /* THE WINDOW IS THE STEP THE DECODER JUST TOOK, not a pattern match.
     *
     * It used to be `((angle % 3600u) == 3420u) ? 180u : 60u`: six degrees per
     * tooth, eighteen across the gap, and 342.0 degrees as the place a 60-2
     * wheel's gap lands. Three facts about one wheel, inside a scheduler whose
     * whole design is to outlive the decoder. advance_angle_epoch() already
     * measures the actual advance, so asking it is both decoder-independent
     * and more accurate: a different tooth count, a different gap width or two
     * gaps needs no change here at all. */
    /* Geometry first, because the window's fallback is the wheel's tooth
       spacing and that comes from the configuration. The epoch and the
       long-horizon staging still run even when no engine is described - they
       are about the crank, not about the cylinders - so only the per-cylinder
       planning below is skipped. */
    (void)geometry_valid();

    window = advance_angle_epoch(angle);
    if (window != 0u && !plan_acc_bad) {
        window = (unsigned int)(window + plan_acc);
    } else {
        window = 0u;
    }
    plan_acc = 0u; plan_acc_bad = 0u; plan_last = stamp;
    /* Teeth that arrived since this capture are counted now, after its own
       epoch step, so the ring is drained before the conversions below. */
    collect_during_plan();
    dry_sched_need_sync = (g_valid && hc_plan_needs_cycle(g_inj_strat, g_ign_strat))
                          ? TRG_SYNC_FULL : TRG_SYNC_CRANK;
    dry_seq_active = (unsigned char)((g_inj_seq && dry_seq_inj_mask != 0u)
                                     || (g_ign_seq && trg_state >= TRG_SYNC_FULL));
    if (phase_shifted) {
        phase_shifted = 0u;
        remap_cursors_360();
    }
    if (window == 0u) {
        /* No previous tooth to measure against: the first capture after sync,
           or after a discontinuity. One nominal tooth is the honest estimate. */
        window = g_tooth_x10 ? g_tooth_x10 : 60u;
    }
    /* LOOK AHEAD TO THE NEXT DELIVERED TOOTH. One tooth everywhere
       except the last tooth before the gap, whose successor is g_gap_step
       away: an event inside the missing teeth is staged from HERE, by time,
       instead of being found late by the catch-up on the far side. */
    {
        unsigned int a = (angle >= 3600u) ? (unsigned int)(angle - 3600u)
                                          : angle;
        unsigned int h;
        hc_plan_ahead = (a == g_pre_gap) ? g_gap_step
                                   : (g_tooth_x10 ? g_tooth_x10 : 60u);
        /* Look past the next capture by the publication allowance. Across
           a wheel gap, taking only max(tooth, allowance) leaves events near
           the next capture without time for the planner to publish them. */
        if (dt > 1u && g_tooth_x10 != 0u) {
            h = (unsigned int)(((unsigned long)HC_PLAN_HORIZON_TICKS
                                * (unsigned int)g_tooth_x10)
                               / (unsigned int)dt);
            if (h > (unsigned int)(hc_plan_cycle >> 2) && hc_plan_cycle != 0u)
                h = (unsigned int)(hc_plan_cycle >> 2);
            hc_plan_ahead = (unsigned int)(hc_plan_ahead + h);
        }
    }
    stage_long_horizon(stamp, dt, hc_plan_ahead);

    if (!g_valid || hc_plan_cycle == 0u) {
        return;                 /* no engine described: schedule nothing */
    }

    dry_spark_advance_x10 = eng_adv_x10;
    dry_dwell_x100 = eng_dwell_x100;
    /* THE FUEL CUTS REACH THE INJECTORS HERE - the rev limiter
       (decided once a millisecond in hc_drysched_overdwell_service(), not on
       the tooth: rpm changes once a revolution) and the overrun cut that
       eng_service() has always decided (fuelCut bit 0) but nothing on this
       board applied. A cut plans every injector event undriven (pulse 0: ON
       events queued with drive off, OFF events still release). */
    /* + the overboost cut (hcboost711.c).
     *
     * THE NOMINAL PULSE of the mode in force: eng_ti_base_us is the
     * cylinder's open time per CYCLE (hcengine.c), delivered in two halves
     * (batch, semi-sequential, the sequential fallback) or whole (true
     * sequential), plus the dead time per pulse. It places the injection
     * START in end-of-injection mode and is published; each event's OWN
     * width is sealed at publication, so a phase transition cannot alter an
     * already admitted electrical pulse. A cut plans
     * nothing (pulse 0: no ON event, so no injector opens). */
    if ((eng_fuelcut & DRY_FUEL_CUTS) != 0u || eng_ti_base_us == 0u) {
        dry_inj_pulse_us = 0u;
    } else {
        unsigned int te = eng_ti_base_us;
        unsigned long p;
        if (!(g_inj_seq && dry_seq_inj_mask != 0u)) {
            te = (unsigned int)(te >> 1);
        }
        p = (unsigned long)te + (unsigned long)eng_deadtime_us;
        dry_inj_pulse_us = (unsigned int)((p > 60000uL) ? 60000uL : p);
    }
    /* Board facts, and they stay on the board's side of the seam:
       hc_plan_dur_to_angle_x10() is a ratio in which the tick rate cancels, so
       it never has to agree with this file about what a tick is.
     *
     * TIME -> TICKS IS CACHED ON ITS SOURCE, and that is exact rather than
     * approximate: eng_dwell_x100 and eng_ti_us are written by eng_service()
     * in the MAIN LOOP, so between two teeth they are the same number and the
     * conversion is the same 32-bit division being performed again. At 7500
     * rpm that is two library divisions 7500 times a second to re-derive a
     * value that changed at most a thousand times a second. The cache is keyed
     * on the input, so a change is picked up on the very next tooth. */
    if (dry_dwell_x100 != cvt_dwell_src) {
        cvt_dwell_src = dry_dwell_x100;
#if TGT_TICKS_PER_MS_X10 == 12500UL
        /* 40 MHz capture clock: 12.5 ticks per 0.01 ms. */
        cvt_dwell_ticks = ((unsigned long)dry_dwell_x100 * 25u) >> 1;
#else
        cvt_dwell_ticks = ((unsigned long)dry_dwell_x100 * TGT_TICKS_PER_MS_X10) / 1000uL;
#endif
    }
    if (dry_inj_pulse_us != cvt_inj_src) {
        cvt_inj_src = dry_inj_pulse_us;
#if TGT_TICKS_PER_MS_X10 == 12500UL
        /* us x 1.25, exactly, without a long division per change */
        cvt_inj_ticks = (unsigned long)dry_inj_pulse_us
                        + (unsigned int)(dry_inj_pulse_us >> 2);
#else
        cvt_inj_ticks = ((unsigned long)dry_inj_pulse_us * TGT_TICKS_PER_MS_X10) / 10000uL;
#endif
    }
    dwell_ticks = cvt_dwell_ticks;
    inj_ticks = cvt_inj_ticks;
    /* g_tooth_x10 AND NOT `window`, AND THE DIFFERENCE WAS MEASURED RATHER
     * THAN REASONED ABOUT - see queue_event(), which makes the same choice
     * for the same reason.
     *
     * hc_plan_dur_to_angle_x10() computes ticks * angle / dt, so its third
     * argument must be the angle THE PERIOD dt SPANNED. `window` is not that:
     * it is how far the crank moved since the last DELIVERED tooth, which on
     * the tooth after a 60-2 gap is 24.0 degrees while dt is still one 6.0
     * degree tooth. Passing `window` here would have made every duration on
     * that tooth four times too large in angle. */
    dwell_angle = hc_plan_dur_to_angle_x10(dwell_ticks, dt, g_tooth_x10,
                                           hc_plan_cycle);
    inj_angle = hc_plan_dur_to_angle_x10(inj_ticks, dt, g_tooth_x10,
                                         hc_plan_cycle);
    /* hc_plan_dur_to_angle_x10() clamps AT the cycle; the offset arithmetic
       below needs both strictly inside it so that one conditional subtract is
       a complete reduction. */
    if (dwell_angle >= hc_plan_cycle) dwell_angle = (unsigned int)(hc_plan_cycle - 1u);
    if (inj_angle >= hc_plan_cycle) inj_angle = (unsigned int)(hc_plan_cycle - 1u);

    /* THE INJECTION ANGLE IS HANDED OVER by hcengctl711.c (the single
       angle, or the injection-phase table) - one near load, not a page read
       per tooth. */
    soi_x10 = dry_inj_phase_x10 % hc_plan_cycle;
    /* SIGNED SPARK. An angle after TDC is an offset of (cycle - |adv|)
       BEFORE the anchor - the same event one cycle on, which on a periodic
       engine is the same instant. |adv| <= 30 deg (hc_ec_spark clamps), so
       no reduction is needed. */
    if (dry_spark_advance_x10 >= 0) {
        adv_x10 = (unsigned int)dry_spark_advance_x10;
        if (adv_x10 >= hc_plan_cycle) adv_x10 = (unsigned int)(hc_plan_cycle - 1u);
    } else {
        adv_x10 = (unsigned int)(hc_plan_cycle
                                 - (unsigned int)(-dry_spark_advance_x10));
    }

    /* FOUR OFFSETS PER TOOTH, not four per cylinder. Each is "how far before
       its anchor this kind of event happens", and every cylinder of that kind
       shares it - which is the whole reason the per-cylinder list can be
       pre-sorted and walked with a cursor. See the note on the anchor lists. */
    off_sp = adv_x10;
    off_dw = (unsigned int)(adv_x10 + dwell_angle);
    if (off_dw >= hc_plan_cycle) off_dw = (unsigned int)(off_dw - hc_plan_cycle);
    /* THE INJECTION ANGLE IS WHERE THE PULSE STARTS, or where it ENDS
       (injTimingMode 1, Bosch KFWEE / rusEFI's default: the end is what
       places the fuel relative to the intake valve, whatever the pulse
       length). For an end angle the start is that angle plus the nominal
       pulse's angle at the current speed. The injector CLOSES BY TIME
       either way, so the width - and the mass - is exact; only the end
       angle moves with acceleration during the pulse. */
    off_is = soi_x10;
    if (g_inj_eoi) {
        off_is = (unsigned int)(soi_x10 + inj_angle);
        if (off_is >= hc_plan_cycle) off_is = (unsigned int)(off_is - hc_plan_cycle);
    }
    off_ie = off_is;       /* no angle-based close (kind unused) */

    hc_plan_angle = angle;
    w_stamp = stamp;
    w_dt = dt;
    w_window = window;

    if (!cursors_valid) {
        seed_cursors(angle, off_dw, off_sp, off_is, off_ie);
        return;      /* this tooth establishes the cursors; it schedules none */
    }

    off_dw=hc_deadline_plan_offset(K_DWELL,off_dw);
    off_sp=hc_deadline_plan_offset(K_SPARK,off_sp);
    off_is=hc_deadline_plan_offset(K_INJ_ON,off_is);
    collect_during_plan();

    /* Earlier publications outrank later kinds. Fixed kind ordering can
       consume a short injector lead while preparing a later dwell/spark. */
    {
        unsigned int dw=due_distance(K_DWELL,off_dw);
        unsigned int sp=due_distance(K_SPARK,off_sp);
        unsigned int inj=due_distance(K_INJ_ON,off_is);
        unsigned int best,off;
        unsigned char unit,kind,type,emit;
        for(unit=0u;unit<3u;unit++) {
            kind=K_DWELL;best=dw;
            if(sp<best) {kind=K_SPARK;best=sp;}
            if(inj<best) {kind=K_INJ_ON;best=inj;}
            if(best==0xFFFFu) break;
            if(kind==K_DWELL) {
                dw=0xFFFFu;off=off_dw;type=HC_DRY_DWELL_START;
                emit=(unsigned char)(dwell_angle!=0u);
            } else if(kind==K_SPARK) {
                sp=0xFFFFu;off=off_sp;type=HC_DRY_SPARK;emit=1u;
            } else {
                inj=0xFFFFu;off=off_is;type=HC_DRY_INJ_START;
                emit=(unsigned char)(dry_inj_pulse_us!=0u);
            }
            walk_kind(kind,off,type,emit);
        }
    }

}

void hc_drysched_init(void)
{
    unsigned int i;
    dry_sched_queued = 0; dry_sched_executed = 0; dry_sched_cancelled = 0;
    dry_sched_late = 0; dry_sched_missed = 0; dry_sched_max_latency = 0;
    dry_sched_next_angle = 0; dry_sched_last_angle = 0;
    dry_sched_capture_overflow = 0; dry_sched_pending = 0;
    dry_sched_status = 0; dry_next_ign_slot = 0;
    dry_sched_need_sync = TRG_SYNC_CRANK;
    dry_next_inj_slot = 0; dry_spark_advance_x10 = 0; dry_dwell_x100 = 0;
    dry_inj_pulse_us = 0; dry_dwell_start_angle = 0; dry_spark_angle = 0;
    dry_inj_start_angle = 0; dry_inj_end_angle = 0;
    TGT_PLAN_IC = 0u;          /* no request while the state is rebuilt */
    cap_head = 0; cap_tail = 0; angle_epoch = 0; angle_last = 0;
    angle_valid = 0; phase_shifted = 0u;
    g_valid = 0; g_rev = 0;
    /* No ?C_INIT on this target: the V90 gap statics are set here, and
       properly by geometry_refresh() on the first tooth. */
    g_gap_step = 240u; g_pre_gap = 0xFFFFu; hc_plan_ahead = 60u;
    ovd_last = 0u; sched_busy = 0u;
    for (i = 0; i < 8u; i++) ign_token[i] = 0u;
    hc_ign_ovd_latch = 0u;
    dry_sched_overdwell = 0u;
    dry_sched_catchup = 0;
    cvt_dwell_src = 0xFFFFu; cvt_inj_src = 0xFFFFu;
    rev_cut = 0u;
    dry_skip_ratio = 0u; dry_rev_spark_cut = 0u; dry_spark_skips = 0u;
    dry_rev_limit = 0u; dry_rev_hyst = REV_HYST_RPM; dry_inj_phase_x10 = 0u;
    hc_prime_on = 0u;
    skip_lfsr = 0xACE1u;
    g_ign_seq = 0u; g_inj_seq = 0u; g_inj_eoi = 0u;
    dry_seq_active = 0u; dry_seq_inj_mask = 0u; dry_seq_skips = 0u;
    dry_seq_enters = 0u; dry_seq_leaves = 0u; dry_inj_width_us = 0u;
    dry_inj_nofree = 0u;
    cvt_dwell_ticks = 0; cvt_inj_ticks = 0;
    /* The cursors mean nothing until an engine and a position exist. */
    cursors_valid = 0; ig_n = 0; in_n = 0;
    hc_plan_cursors[0] = 0; hc_plan_cursors[1] = 0; hc_plan_cursors[2] = 0; hc_plan_cursors[3] = 0;
    hc_deadline_init();
    planner_generation = hc_dl_generation;
    for (i = 0; i < PLAN_N; i++) plan_type[i] = EV_NONE;
    TGT_PLAN_IC = HC_IC(TGT_ILVL_PLAN, TGT_GLVL_PLAN);

    hc_tl_init();
}

/* Crank ISR (ILVL 12): record the tooth, then REQUEST THE PLANNER LEVEL when
   this capture makes a full walk due (the walk rule in hc_drysched_service:
   a slow tooth, HC_PLAN_PERIOD_TICKS since the last walk, no cursors) or
   PLAN_BATCH teeth wait. The teeth in between are counted in order when it
   runs; requesting it for each of them cost one interrupt entry and drain
   pass per tooth - a tenth of the CPU at 9600 rpm. The planner (hc_plan_isr,
   ILVL 9) runs as soon as nothing above it is running. */
#define PLAN_BATCH 4u
void hc_drysched_tooth(unsigned int angle, unsigned int stamp, unsigned int dt)
{
    unsigned char n = (unsigned char)((cap_head + 1u) & (CAP_N - 1u));
    if (n == cap_tail) {
        if (dry_sched_capture_overflow != 0xFFFFu) dry_sched_capture_overflow++;
        /* The planner fell CAP_N - 1 teeth behind. Its angle accumulator can
           no longer be trusted, so integrity is WITHDRAWN - no new charge or
           opening - while every committed OFF still executes. A cancel
           here would release every charging coil
           from this ISR: an extra spark at an unplanned angle. */
        hc_deadline_quiesce(HC_Q_OVERFLOW);
        return;
    }
    cap_angle[cap_head] = angle; cap_stamp[cap_head] = stamp;
    cap_dt[cap_head] = dt;
    cap_head = n;
    n = (unsigned char)((n - cap_tail) & (CAP_N - 1u));
    HC_RT_MAX(cap_hwm, n);
    if (n >= PLAN_BATCH || !cursors_valid || dt >= HC_PLAN_PERIOD_TICKS
        || (unsigned int)(stamp - plan_last) >= HC_PLAN_PERIOD_TICKS)
        TGT_PLAN_IR = 1;
}

/* Any context. A sync loss, a permission that fell, a strategy that lost the
   cycle: QUIESCE, not release (hcdeadline711.h hc_dl_inhibit). The planner
   discards its own state at its next run, on the generation step. */
void hc_drysched_cancel(unsigned int reason)
{
    dry_sched_next_angle = reason; /* retained until the next queued event */
    hc_deadline_quiesce(HC_Q_WITHDRAWN);
}

/* Any context: release every output NOW. Only where nothing can be turning
   and a pending edge would act on stale routing (hchal_me711.c), or where the
   executor itself cannot be trusted (the runtime supervisor). */
void hc_drysched_abort(unsigned int reason)
{
    dry_sched_next_angle = reason;
    hc_deadline_cancel();
}

/* Planner context only. A RESYNC IS A NEW EXECUTION EPOCH: the cursors and
   the angle accumulator described where the engine was, and re-seeding them
   on the first tooth of the new epoch is what stops a stale cursor firing an
   event from before the loss. */
static void planner_reset(void)
{
    unsigned int i;
    planner_generation = hc_dl_generation;
    hc_ign_ovd_latch = 0u;
    dry_seq_inj_mask = 0u;
    for (i = 0; i < 8u; i++) ign_token[i] = 0u;
    for (i = 0; i < PLAN_N; i++) plan_type[i] = EV_NONE;
    dry_sched_pending = 0;
    dry_sched_status = 0;
    angle_valid = 0;
    cursors_valid = 0;
    plan_acc = 0u; plan_acc_bad = 0u;
    cap_tail = cap_head;
}

/* ================================ V90: THE HARD MAXIMUM DWELL ===========
 *
 * NO COIL MAY STAY CHARGED BECAUSE AN EVENT WENT MISSING. V89 on the AWT held
 * all four coils ON for eight seconds of cranking: the dwell events ran, the
 * spark events never did (the gap defect above), and nothing else in the
 * firmware looked at how long a coil had been on.
 *
 * Every dwell is published with its own MAXDWELL release (publish_edge): the
 * predicted dwell plus a deceleration margin of max(dwell / 8, two teeth),
 * never more than rusEFI's 1.5 x dwell ([tag:overdwell], spark_logic.cpp) and
 * never more than 20 ms. It is also the spark when planning is withdrawn
 * before the coil's spark was committed, so it is kept close to the planned
 * angle rather than a fixed half-dwell late. A release IS a spark, at an
 * angle nobody chose; with the scheduler right it never fires before the
 * planned spark. dry_sched_overdwell counts every release.
 *
 * WHAT "ON" IS PHYSICALLY (V90 audit, CK110 product information): the CK110
 * is INVERTING - input LOW activates the current source (cavity high: the
 * smart coil charges), input HIGH or an open input (internal pull-up) the
 * low-side switch (cavity low). ON = P2.x driven LOW; OFF = released to
 * high impedance = low-side = the falling edge that fires the coil.
 *
 * this historical task watch no longer owns physical releases.
 * CC25 owns the independent maximum deadline. The compatibility millisecond
 * service below decides rev cut and withdraws injector ownership only. */
#define OVD_MAX_TICKS  ((unsigned int)((20uL * TGT_TICKS_PER_MS_X10) / 10uL))

/* NOT PART OF THE TOOTH PATH. It first ran inside the executor and
   me711_plan_cost_proof measured it: the worst 4-cylinder tooth went from 659
   to 1195 instructions. It is supervision, so it is its own service, gated to
   once a millisecond, called from the main loop and the serial yield. */
#define OVD_PERIOD_TICKS  ((unsigned int)(TGT_TICKS_PER_MS_X10 / 10uL))

void hc_drysched_overdwell_service(unsigned int now)
{
    if ((unsigned int)(now - ovd_last) < OVD_PERIOD_TICKS) {
        return;
    }
    ovd_last = now;
    /* THE REV LIMITER - a FUEL CUT, rusEFI's rpmHardLimit with
       cutFuelOnHardLimit. Until V93 revLimit was validated against revMax
       and enforced by nothing on this board (ENG_CUT_REV was never set).
       Above revLimit plan_tooth() plans every injector event undriven; fuel
       returns 200 rpm below it, so the cut cannot chatter at the boundary.
       Spark continues (no unburnt charge is made). Never while cranking;
       revLimit 0 disables it. Here, once a millisecond, and not on the
       tooth: me711_plan_cost_proof measured +28 instructions per tooth for
       the per-tooth version. The bit is this module's own in the shared
       word (task context, like eng_service()). */
    /* the limit and its hysteresis come from hcengctl711.c (the pit
       limiter lowers the limit, revLimitHyst sets the drop), and revlimMode
       chooses what is cut - rusEFI cutFuelOnHardLimit / cutSparkOnHardLimit:
       0 spark, 1 fuel, 2 both; a spark cut skips revlimPattern of every 8
       sparks (8 = all). */
    {
        unsigned int lim = dry_rev_limit;
        unsigned char mode = hc_cal_u8(CAL_REVLIM_MODE);
        if (lim == 0u || eng_cranking) {
            rev_cut = 0u;
        } else if (trg_rpm > lim) {
            rev_cut = 1u;
        } else if ((unsigned int)(trg_rpm + dry_rev_hyst) < lim) {
            rev_cut = 0u;
        }
        eng_fuelcut = (unsigned int)((eng_fuelcut & ~ENG_CUT_REV)
                                     | ((rev_cut && mode != 0u) ? ENG_CUT_REV
                                                                : 0u));
        dry_rev_spark_cut = (unsigned char)(rev_cut && mode != 1u);
    }
    /* The independent CC25 max-dwell edge owns release. */
    if (eng_fuelcut & DRY_FUEL_CUTS) hc_deadline_fuel_cut();
}

/* ONE DECISION PER SPARK - skip it or not - from a 16-bit LFSR
   (rusEFI SoftSparkLimiter draws a random number the same way). The rev
   limiter's spark cut skips revlimPattern of every 8 (8 = every spark). */
static unsigned char spark_skip(void)
{
    unsigned char r = dry_skip_ratio;

    if (dry_rev_spark_cut) {
        unsigned char p = hc_cal_u8(CAL_REVLIM_PATTERN);
        unsigned char q = (unsigned char)((p >= 8u) ? 255u
                                          : (unsigned char)(p << 5));
        if (q > r) r = q;
    }
    if (r == 0u) {
        return 0u;
    }
    if (r == 255u) {
        return 1u;
    }
    skip_lfsr = (unsigned int)((skip_lfsr >> 1)
                               ^ ((skip_lfsr & 1u) ? 0xB400u : 0u));
    if (skip_lfsr == 0u) skip_lfsr = 0xACE1u;
    return (unsigned char)((unsigned char)(skip_lfsr >> 8) < r);
}

/* Task-side edge decisions; no tables/calculations run in CC25. */
static void publish_edge(unsigned int target, unsigned int stamp,
    unsigned int dt, unsigned long ahead, unsigned char type, unsigned char slot)
{
    unsigned char s = (unsigned char)(slot & HC_SLOT_MASK), b, whole = 0u;
    unsigned char mask = 255u;
    unsigned int id = 0u, sm = 0u, fuel;
    unsigned long duration = 0uL, period;
    if (s) {
        if (s > 8u) return;
        sm = 1u; sm <<= (unsigned char)(s - 1u);
        mask = (unsigned char)sm;
    }
    if (planner_generation != hc_dl_generation) return;
    dry_sched_next_angle = target;
    if (type == HC_DRY_DWELL_START) {
        if (((slot & HC_SLOT_TWIN) && g_ign_seq && trg_state >= TRG_SYNC_FULL)
            || spark_skip()) {
            if (dry_spark_skips != 0xFFFFu) dry_spark_skips++;
            SCHED_SUPPRESS();
            return;
        }
        /* Reserve the predicted spark plus a bounded deceleration margin.
           A refined spark can release earlier; the backstop bounds charge
           even when normal planning is withdrawn. */
        {
            unsigned long m = cvt_dwell_ticks >> 3;
            unsigned long two = (unsigned long)dt << 1;
            if (two > m) m = two;
            duration = cvt_dwell_ticks + m;
            if (duration > cvt_dwell_ticks + (cvt_dwell_ticks >> 1))
                duration = cvt_dwell_ticks + (cvt_dwell_ticks >> 1);
            if (duration > OVD_MAX_TICKS) duration = OVD_MAX_TICKS;
            if (duration <= cvt_dwell_ticks) duration = cvt_dwell_ticks + 1u;
        }
    } else if (type == HC_DRY_SPARK) {
        for (b = 0; b < 8u; b++) if (mask & (1u << b)) { id = ign_token[b]; break; }
        /* A spark whose dwell no longer owns the coil - the sequential twin of
           a coil that already fired, or a dwell refused at publication - is a
           no-op at execution (CC25's owner check). An owner only ever changes
           to a NEW token, so it cannot match later: do not queue it. */
        if (b >= 8u || !id || hc_dl_owner[b] != id) return;
        duration = id;
    } else if (type == HC_DRY_INJ_START) {
        if (g_inj_seq && sm) {
            if (slot & HC_SLOT_TWIN) {
                if (trg_state >= TRG_SYNC_FULL) {
                    if (!(dry_seq_inj_mask & sm)) { dry_seq_inj_mask |= sm; if (dry_seq_enters != 0xFFFFu) dry_seq_enters++; }
                    if (dry_seq_skips != 0xFFFFu) dry_seq_skips++;
                    SCHED_SUPPRESS();
                    return;
                }
                if (dry_seq_inj_mask & sm) { dry_seq_inj_mask &= (unsigned int)~sm; if (dry_seq_leaves != 0xFFFFu) dry_seq_leaves++; }
            } else if (dry_seq_inj_mask & sm) whole = 1u;
        }
        if ((eng_fuelcut & DRY_FUEL_CUTS) || eng_ti_base_us == 0u) return;
        fuel = whole ? eng_ti_base_us : (unsigned int)(eng_ti_base_us >> 1);
        period = (unsigned long)dt * (whole?hc_plan_cycle:HC_DL_WIDTH.next_angle[s?s-1u:0u]);
        /* Normal running periods fit the native DIVLU quotient. Preserve
           the long-period fallback for cranking or a stalling engine. */
        if((unsigned int)(period>>16)<g_tooth_x10)
            period=(unsigned int)(period/(unsigned int)g_tooth_x10);
        else period/=g_tooth_x10;
        if (!whole && g_inj_rep > 1u) period /= g_inj_rep;
        duration=hc_deadline_inj_request(mask,fuel,eng_deadtime_us,period);
    } else return;
    /* A changed offset can put a previously uncommitted event behind its
       tooth. Catch-up requests the earliest bounded publication point after
       arithmetic has finished. Already committed OFF deadlines retain their
       ownership and time; the executor's 100 us tolerance is unchanged. */
    if(ahead == 0uL) { stamp=T1; ahead=250uL; }
    id=hc_deadline_publish(planner_generation,stamp,ahead,type,mask,duration);
    if(type==HC_DRY_INJ_START) {
        dry_inj_width_us=hc_deadline_inj_admitted(mask,id,planner_generation,duration);
        if (!id) { dry_inj_width_us = 0u; if (dry_inj_nofree != 0xFFFFu) dry_inj_nofree++; }
        dry_next_inj_slot = slot; dry_inj_start_angle = target;
    } else {
        if(type==HC_DRY_DWELL_START) {
            if (id) for (b = 0; b < 8u; b++) if (mask & (1u << b)) ign_token[b] = id;
            dry_dwell_start_angle = target;
        } else dry_spark_angle = target;
        dry_next_ign_slot = slot;
    }
    if (hc_dl_count) dry_sched_status |= DRY_ST_NEAR_ARMED;
    collect_during_plan();
}

/* Compatibility entry: task/yield can plan; physical execution is CC25 only. */
void hc_drysched_time_service(unsigned int now)
{
    if (now) return;
}

void hc_drysched_service(unsigned int now, unsigned int sync_state)
{
    /* THE SYNC THIS ENGINE NEEDS IS A PROPERTY OF ITS STRATEGY, not a constant.
     *
     * This used to require TRG_SYNC_CRANK and nothing more, whatever the page
     * said - so a sequentially-injected engine would have been scheduled on
     * 360-degree position alone, putting every second cycle's fuel into the
     * exhaust stroke. hc_validation.c has always refused that CONFIGURATION;
     * the runtime was not enforcing the same rule, and validation covers what
     * a tuner types, not what an engine does when a cam signal disappears
     * while it is running.
     *
     * And the rule is not "COP needs a cam". Wasted COP drives one coil per
     * cylinder and fires each of them twice per cycle - once into compression,
     * once into exhaust - so it runs on crank position alone, which is a
     * genuinely useful way to start an engine whose cam signal is not trusted
     * yet. hc_plan_needs_cycle() asks the STRATEGY and never the hardware, and
     * it is the same function hc_validation.c's rule is written from.
     *
     * Cancelling on the way down is the point: losing the cam must withdraw
     * pending SEQUENTIAL events, not merely stop planning new ones. */
    unsigned int need = TRG_SYNC_CRANK;

    /* THIS NOW ALSO RUNS FROM hcts_target_yield(), once a millisecond
       inside a long serial reply - before V90 only the executor did, so a
       45 ms output-channel reply left every captured tooth unplanned and the
       car logged schedulerMaxLatency 62700 ticks (50 ms). Nothing below
       yields, so it cannot re-enter itself, but the guard makes that a fact
       rather than a property of today's call graph. */
    if (sched_busy) {
        return;
    }
    sched_busy = 1u;
    /* A quiesce or an abort stepped the generation since the last run: the
       angle accumulator, the cursors and the long-horizon plans describe an
       epoch that has ended. Discard them HERE, in the one context that owns
       them, rather than from whichever interrupt withdrew integrity. */
    if (planner_generation != hc_dl_generation) {
        planner_reset();
    }
    /* A SEQUENTIAL STRATEGY RUNS ON CRANK SYNC, IN ITS FALLBACK.
     * Until V97 the planner required TRG_SYNC_FULL for it and CANCELLED
     * everything when the cycle went - a sequential engine whose cam
     * glitched stalled, and one whose cam had not yet been seen never
     * started. Now its twins (HC_SLOT_TWIN) carry it on crank position
     * alone: wasted COP and two half pulses per cylinder, both of which are
     * right on either revolution. dry_sched_need_sync still publishes what
     * the strategy PREFERS (FULL = it becomes truly sequential once the
     * cycle is known); the validator still requires a resolvable cam for a
     * sequential page (hc_validation.c). */
    /* dry_sched_need_sync / dry_seq_active (main-loop telemetry
       and the limp duty model) are refreshed by the per-cylinder walk, not on
       every tooth - see plan_tooth(). */
    if (sync_state < need) {
        /* Withdraw only what was committed; a waiting capture is simply
           dropped below. (Every pre-sync tooth used to step the generation.) */
        if (!hc_dl_inhibit && dry_sched_queued)
            hc_drysched_cancel(TRG_LOSS_NONE);
        cap_tail = cap_head;            /* nothing below the need is planned */
        sched_busy = 0u;
        return;
    }
    dry_sched_status |= DRY_ST_SYNCED;
    if (cap_tail != cap_head) {
        unsigned char walked=0u,full=0u;
        while (cap_tail != cap_head && walked++<CAP_N && !full) {
            unsigned char p;
            unsigned int a, s, d, age;
            /* SINGLE PRODUCER, SINGLE CONSUMER, NO LOCK: the crank ISR (12)
               fills a slot completely before it advances cap_head, and only
               this level advances cap_tail. A capture older than 26 ms is a
               planner that was held off that long - the ring (7 teeth) has
               overflowed first at any speed above ~135 rpm - so the 16-bit
               T1 stamp's age is the whole test. */
            if (planner_generation != hc_dl_generation) break;
            p = cap_tail;
            a = cap_angle[p]; s = cap_stamp[p]; d = cap_dt[p];
            cap_tail = (unsigned char)((p + 1u) & (CAP_N - 1u));
            age = (unsigned int)(T1 - s);
            if (age >= 32768u) {
                hc_deadline_quiesce(HC_Q_STALE);
                planner_reset();
                break;
            }
            /* The full walk on the newest capture only, and only once per
               HC_PLAN_PERIOD_TICKS - every tooth below ~2500 rpm, every
               fourth at 9600. Seeding (no cursors) always walks. */
            if (cursors_valid && cap_tail != cap_head) {
                count_tooth(a);
            } else if (cursors_valid && d < HC_PLAN_PERIOD_TICKS
                       && (unsigned int)(s - plan_last) < HC_PLAN_PERIOD_TICKS
                       && plan_acc < (unsigned int)(hc_plan_ahead >> 1)) {
                count_tooth(a);
            } else {
                /* The capture whose stamp the walk's deadlines use. */
                HC_RT_MAX(plan_lat_max, age);
                plan_tooth(a, s, d);
                full=1u;
            }
            /* A capture ISR may have withdrawn integrity while this tooth was
               being planned. Its partial angle/cursor writes must not seed the
               next execution epoch. */
            if (planner_generation != hc_dl_generation) {
                planner_reset();
                break;
            }
            if (hc_tl_active && (hc_tl_state & 0x00FFu) == HC_TL_RUN) {
                hc_tl_add(a, d, g_tooth_x10);
            }
        }
        /* EXECUTE AGAINST THE TIME NOW, not the time the caller
           sampled before the ring was drained (see
           hc_drysched_time_service()). */
        now = T1;
    }
    sched_busy = 0u;
    if(cap_tail!=cap_head) CC26IR=1;
}

/* THE PLANNER LEVEL. Requested by hc_drysched_tooth() from the
   crank ISR; see TGT_TRAP_PLAN in hctarget.h for the priority and the OEM
   precedent. Every capture waiting in the ring is planned in one run. */
void hc_plan_isr(void) interrupt TGT_TRAP_PLAN using PLANBANK
{
    unsigned int t0 = T1;
    hc_drysched_service(t0, trg_state);
    HC_RT_MAX(plan_run_max, (unsigned int)(T1 - t0));
    HC_RT_INC(plan_runs);
}
#endif /* !TGT_ENGINE_RUNTIME */
