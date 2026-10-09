/*
 * hc_plan.h - where each cylinder's events sit on the cycle, as pure arithmetic.
 *
 * WHY THIS IS A MODULE OF PURE FUNCTIONS, and why it is SHARED.
 *
 * The Bosch dry scheduler used to compute its event angles like this:
 *
 *     for (i = 0; i < 8u; i++) {
 *         unsigned int fire = (unsigned int)(i * 900u);
 *         ...
 *         unsigned int inj_end = sub720(fire, 3600u);
 *     }
 *
 * Every number in that loop is a Cayenne V8. Eight cylinders. An even 90
 * degrees between them. A 720 degree cycle. Injection ending exactly 360
 * degrees before TDC. One event per cylinder per cycle, which is only true of
 * sequential ignition. HaniCore's whole premise is that none of those may be
 * compiled in - the configuration already carries CFG_CYLINDERS, CFG_STROKES,
 * a twelve-entry per-cylinder TDC table, CFG_U_INJ_STRATEGY,
 * CFG_U_IGN_STRATEGY and CFG_INJ_START_DEG_X10, and the scheduler read none of
 * them.
 *
 * IT ALSO CONTRADICTED THE OTHER TARGET ON A FIELD BOTH OF THEM READ.
 * hcinj.c on ME7.5 says, and has always said:
 *
 *     "Injection START is cfg_start_x10 BEFORE the cylinder's TDC."
 *
 * The Bosch scheduler used the same configuration word as an END angle. Two
 * targets, one 4096-byte page, two meanings for byte 58. The definition here
 * is ME7.5's, because it is the one that is written down, defaulted (3600 =
 * 360.0 deg BTDC) and generated into the .ini.
 *
 * So the geometry lives here, once, as functions that take every quantity as
 * an argument: no globals, no configuration reads, no statics. That is what
 * lets tools/me711_plan_golden.py check each one against an independent
 * reference instead of only inspecting the answer at the end - the same shape
 * hc_airfuel.c is in, and for the same reason.
 *
 * NO NEAR RAM. Not one byte of state is declared here, which matters: ME7.5
 * near RAM is a fixed 1792-byte window and this module compiles into both
 * targets.
 *
 * ANGLES. Everything is TENTHS OF A CRANK DEGREE, measured from the position
 * the decoder calls zero, increasing in the direction the engine turns. The
 * cycle is 7200 for a four-stroke and 3600 for a two-stroke, and it is passed
 * in rather than assumed, because half the point of this file is that 7200 is
 * a configuration value.
 */
#ifndef HC_PLAN_H
#define HC_PLAN_H

/* The widest engine the universal configuration describes. */
#define HC_PLAN_MAX_CYL     12u

/* A slot is a LOGICAL output index, 1-based, and it is not a cylinder number
   and not a pin. Cylinder -> slot is the strategy's job (below); slot -> pin
   is hc_route.c's. HC_PLAN_SLOT_ALL means every output of that kind fires
   together, which is what batch injection is. */
#define HC_PLAN_SLOT_ALL     0u

/* One crank revolution. Wasted spark and batch injection repeat on this
   period, not on the cycle, which is exactly why they need no cam. */
#define HC_PLAN_REV_X10   3600u

/* Cycle length for a stroke count. Four-stroke is two crank revolutions;
   anything else is treated as one, because a two-stroke fires every
   revolution and nothing else is describable by this configuration. */
unsigned int hc_plan_cycle_x10(unsigned char strokes);

/* a - b, wrapped into [0, cycle). Both arguments are reduced first, so a
   configuration holding a TDC angle above the cycle cannot produce a negative
   intermediate or an angle outside the wheel. */
unsigned int hc_plan_sub_x10(unsigned int a, unsigned int b,
                             unsigned int cycle_x10);

/* THE SAME SUBTRACTION, WITHOUT THE DEFENSIVE REDUCTION, for the hot path.
 *
 * hc_plan_sub_x10() reduces BOTH arguments modulo the cycle before
 * subtracting, which costs two 16-bit divisions. That is the right thing for a
 * function that runs on whatever a configuration page happens to say - but the
 * scheduler calls it about sixty times per TOOTH, and at 7500 rpm on a 60-2
 * wheel a tooth is 133 microseconds.
 *
 * MEASURED, on the linked image: planning one tooth for a V8 cost 2351
 * emulated instructions, against roughly 1330 available in a tooth period at
 * 10 MIPS. The defensive divisions were most of it, and they were re-proving
 * something the caller had already established.
 *
 * So this variant states the precondition instead of paying for it: BOTH
 * ARGUMENTS MUST ALREADY BE LESS THAN cycle_x10. hcsched_dry.c guarantees that
 * by reducing the TDC table once when the geometry is cached, and the advance
 * and the injection angle once per tooth rather than once per cylinder.
 *
 * If the precondition is violated the answer is still bounded - never outside
 * [0, cycle) - it is simply not the modular difference. That is deliberate: a
 * scheduler must not be able to produce an angle outside the wheel even when
 * something upstream is wrong. */
unsigned int hc_plan_sub_fast_x10(unsigned int a, unsigned int b,
                                  unsigned int cycle_x10);

/* Advance an already-reduced angle by ONE crank revolution, wrapped. The
   repeat step for wasted spark and batch injection, without the two divisions
   hc_plan_repeat_x10() pays to be safe on arbitrary input. */
unsigned int hc_plan_next_rev_x10(unsigned int a_x10, unsigned int cycle_x10);

/* Evenly spaced TDC for cylinder `cyl`, used ONLY when the configured TDC
   table is empty. cyl * cycle / cylinders - for a V8 on a four-stroke that is
   the 900 the old scheduler had compiled in, which is how this function is
   checked against the behaviour it replaces. An uneven-firing engine is
   described by the TDC table and never reaches this. */
unsigned int hc_plan_even_tdc_x10(unsigned char cyl, unsigned char cylinders,
                                  unsigned int cycle_x10);

/* Start of injection: `soi_btdc_x10` BEFORE this cylinder's TDC. That is
   CFG_INJ_START_DEG_X10's documented meaning on the ME7.5 target and now on
   both. */
unsigned int hc_plan_soi_x10(unsigned int tdc_x10, unsigned int soi_btdc_x10,
                             unsigned int cycle_x10);

/* Spark: `adv_x10` BEFORE this cylinder's TDC. Advance is reduced modulo the
   cycle first, so a nonsense advance cannot wrap the answer somewhere
   plausible. */
unsigned int hc_plan_spark_x10(unsigned int tdc_x10, unsigned int adv_x10,
                               unsigned int cycle_x10);

/* How far the crank turns, in 0.1 deg, while `ticks` timer counts elapse -
 * given that one tooth spans `tooth_x10` and took `tooth_dt` counts.
 *
 * This is the dwell-to-angle and pulse-to-angle conversion. It is a RATIO, so
 * the timer frequency cancels and the caller does not have to agree with this
 * file about what a tick is. Returns 0 on a zero tooth period rather than
 * dividing, and saturates at one whole cycle: a dwell longer than a cycle is a
 * configuration fault, not a reason to wrap. */
unsigned int hc_plan_dur_to_angle_x10(unsigned long ticks,
                                      unsigned int tooth_dt,
                                      unsigned int tooth_x10,
                                      unsigned int cycle_x10);

/* Tenths of a crank degree per tooth, from the wheel's total tooth count -
   INCLUDING the missing ones, because the wheel's geometry is what sets the
   spacing. 60 teeth gives 60. Returns 0 if the count is absurd. */
unsigned int hc_plan_tooth_x10(unsigned int teeth);

/* --------------------------------------------------- strategy mapping --
 *
 * THE CALLER'S LOOP IS ALWAYS THE SAME SHAPE, and that is the point:
 *
 *     n = hc_plan_ign_cyls(cylinders, strategy);
 *     for (i = 0; i < n; i++) {
 *         base = hc_plan_spark_x10(tdc_of(i), advance, cycle);
 *         slot = hc_plan_ign_slot(i, cylinders, strategy);
 *         for (r = 0; r < hc_plan_ign_repeats(strategy, strokes); r++)
 *             emit(slot, hc_plan_repeat_x10(base, r, cycle));
 *     }
 *
 * Three functions decide everything, and no strategy needs a special case in
 * the scheduler.
 *
 * HOW MANY CYLINDERS TO WALK. Every ignition strategy walks all of them,
 * because even a single-coil distributor fires once per cylinder at that
 * cylinder's own advance - the rotor decides where the spark goes, so the
 * events are distinct even though the output is shared. Batch injection is the
 * one case that does not: all injectors open together, so walking every
 * cylinder would emit the same bank event n times. It walks ONE. */
unsigned char hc_plan_ign_cyls(unsigned char cylinders);
unsigned char hc_plan_inj_cyls(unsigned char cylinders,
                               unsigned char inj_strategy);

/* Cylinder -> logical slot. Two cylinders that SHARE an output map to the same
 * slot, and their two events - 360 degrees apart on an even-firing engine -
 * are exactly the two firings that output needs per cycle. That is why a
 * wasted-spark pair and a semi-sequential injector pair need no repeat count
 * and no special case: the second cylinder in the pair generates the second
 * event, at its own angle, which is also correct on an UNEVEN-firing engine
 * where "+360 degrees" would not have been. */
unsigned char hc_plan_ign_slot(unsigned char cyl, unsigned char cylinders,
                               unsigned char ign_strategy);
unsigned char hc_plan_inj_slot(unsigned char cyl, unsigned char cylinders,
                               unsigned char inj_strategy);

/* THE PAIR A PAIRED OUTPUT SERVES, BY FIRING ORDER. Two cylinders share
 * a wasted-spark coil or a semi-sequential injector when their TDCs are 360
 * degrees apart - positions p and p + n/2 in the FIRING order. The pair
 * functions above assumed cylinder index == firing position, which is false
 * for 1-3-4-2 (they paired 1/3, whose TDCs are 180 apart). Returns the
 * cylinder INDEX (0-based) at firing position (position of `cyl`) mod n/2 -
 * the earlier cylinder of the pair, whose output the pair drives (rusEFI
 * getIgnitionPinForIndex). Positions come from the TDC table (ascending
 * TDC, ties by index). */
unsigned char hc_plan_pair_lead(const unsigned int *tdc, unsigned char cyl,
                                unsigned char cylinders);

/* How many times a WALKED cylinder's event repeats within the cycle, at one
 * revolution's spacing.
 *
 * Only two strategies need this, and for the same reason: they have no second
 * cylinder mapped to the slot to supply the second event.
 *
 *   WASTED COP     one coil per cylinder, fired at its own compression TDC
 *                  and again 360 degrees later on the exhaust stroke. That
 *                  second spark is what removes the need for a cam.
 *   BATCH          one bank event per revolution, half a charge each time.
 *
 * Wasted PAIRED, semi-sequential, sequential and distributor all return 1: for
 * the first two the pair supplies the second event, and the last two genuinely
 * fire once per cycle. On a two-stroke the cycle IS a revolution and every
 * count collapses to one. */
unsigned char hc_plan_ign_repeats(unsigned char ign_strategy,
                                  unsigned char strokes);
unsigned char hc_plan_inj_repeats(unsigned char inj_strategy,
                                  unsigned char strokes);

/* The angle of repeat `n` of an event whose first occurrence is at `base_x10`:
   base + n * one revolution, wrapped. */
unsigned int hc_plan_repeat_x10(unsigned int base_x10, unsigned char n,
                                unsigned int cycle_x10);

/* Does this pair of strategies need to know WHICH revolution the engine is on?
 *
 * 1 only if something is sequential. Everything else repeats every 360 degrees
 * and runs on crank sync alone. THE COIL COUNT DOES NOT DECIDE THIS: an engine
 * with eight individual coils can be driven wasted-COP and started without a
 * cam signal, which is a real and useful configuration, so the question is
 * asked of the STRATEGY and never of the hardware. hc_validation.c enforces
 * the same rule at configuration time; this is the runtime half of it. */
unsigned char hc_plan_needs_cycle(unsigned char inj_strategy,
                                  unsigned char ign_strategy);

#endif /* HC_PLAN_H */
