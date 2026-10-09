/*
 * hc_plan.c - cylinder event geometry. Read hc_plan.h first.
 *
 * Every function is pure: same arguments, same answer, no globals, no
 * configuration reads, no statics. tools/me711_plan_golden.py compares each
 * one against an independent Python reference, and tests/test_plan_strategy.py
 * checks the strategy mapping exhaustively over every cylinder count the
 * configuration allows.
 *
 * NO DIVISION BY ANYTHING THAT COULD BE ZERO. The configuration is validated
 * before it is applied, but this code runs on whatever the page actually says,
 * so every divisor is checked here as well. Returning a defined, harmless
 * answer beats trapping in a scheduler.
 */
#include "hc_config_generated.h"
#include "hc_plan.h"


unsigned int hc_plan_cycle_x10(unsigned char strokes)
{
    /* Four-stroke: two crank revolutions per cycle. Anything else fires every
       revolution. CFG_STROKES is validated to 2 or 4, but a page that says 0
       must still produce a usable wheel rather than a zero divisor. */
    return (strokes == 4u) ? (unsigned int)(2u * HC_PLAN_REV_X10)
                           : HC_PLAN_REV_X10;
}


unsigned int hc_plan_sub_x10(unsigned int a, unsigned int b,
                             unsigned int cycle_x10)
{
    if (cycle_x10 == 0u) {
        return 0u;
    }
    /* Reduce BOTH first. A TDC angle above the cycle is a configuration fault
       that hc_validate() rejects, but if one arrives here it must not be able
       to produce an answer outside the wheel - a spark at 900 degrees would be
       staged as though it were somewhere real. */
    a %= cycle_x10;
    b %= cycle_x10;
    return (a >= b) ? (unsigned int)(a - b)
                    : (unsigned int)(a + cycle_x10 - b);
}


unsigned int hc_plan_sub_fast_x10(unsigned int a, unsigned int b,
                                  unsigned int cycle_x10)
{
    /* No modulo. The caller has already reduced both arguments - see the
       header for why that is worth stating rather than re-checking. The
       clamps below cost two compares and keep the answer inside the wheel
       even if the precondition is broken. */
    if (cycle_x10 == 0u) {
        return 0u;
    }
    if (a >= cycle_x10) {
        a = (unsigned int)(cycle_x10 - 1u);
    }
    if (b >= cycle_x10) {
        b = (unsigned int)(cycle_x10 - 1u);
    }
    return (a >= b) ? (unsigned int)(a - b)
                    : (unsigned int)(a + cycle_x10 - b);
}


unsigned int hc_plan_next_rev_x10(unsigned int a_x10, unsigned int cycle_x10)
{
    unsigned long n;

    if (cycle_x10 == 0u) {
        return 0u;
    }
    n = (unsigned long)a_x10 + (unsigned long)HC_PLAN_REV_X10;
    while (n >= (unsigned long)cycle_x10) {
        n -= (unsigned long)cycle_x10;
    }
    return (unsigned int)n;
}


unsigned int hc_plan_even_tdc_x10(unsigned char cyl, unsigned char cylinders,
                                  unsigned int cycle_x10)
{
    if (cylinders == 0u) {
        return 0u;
    }
    if (cyl >= cylinders) {
        cyl = (unsigned char)(cyl % cylinders);
    }
    /* 32-bit intermediate: 11 * 7200 = 79 200 does not fit in 16 bits, and a
       twelve-cylinder engine is inside the configuration's own limit. */
    return (unsigned int)(((unsigned long)cyl * (unsigned long)cycle_x10)
                          / (unsigned long)cylinders);
}


unsigned int hc_plan_soi_x10(unsigned int tdc_x10, unsigned int soi_btdc_x10,
                             unsigned int cycle_x10)
{
    return hc_plan_sub_x10(tdc_x10, soi_btdc_x10, cycle_x10);
}


unsigned int hc_plan_spark_x10(unsigned int tdc_x10, unsigned int adv_x10,
                               unsigned int cycle_x10)
{
    return hc_plan_sub_x10(tdc_x10, adv_x10, cycle_x10);
}


unsigned int hc_plan_tooth_x10(unsigned int teeth)
{
    /* The spacing is set by the WHEEL, so the total tooth count is used -
       missing teeth included. A 60-2 wheel has 58 physical teeth spaced 6
       degrees apart, not 58 teeth spaced 360/58. */
    if (teeth == 0u || teeth > HC_PLAN_REV_X10) {
        return 0u;
    }
    return (unsigned int)(HC_PLAN_REV_X10 / teeth);
}


unsigned int hc_plan_dur_to_angle_x10(unsigned long ticks,
                                      unsigned int tooth_dt,
                                      unsigned int tooth_x10,
                                      unsigned int cycle_x10)
{
    unsigned long a;

    if (tooth_dt == 0u || tooth_x10 == 0u) {
        /* No measured tooth period means no rate, and a rate of zero is the
           honest answer. Guessing one would put a dwell event at an angle
           derived from nothing. */
        return 0u;
    }
    /* Per tooth, twice: a 16x16 MULU and a native 32:16 DIVLU whenever the
       quotient fits 16 bits (Keil emits DIVLU for this shape), the long
       helper only for an angle beyond 6553.5 deg, which is clamped anyway. */
    if (ticks <= 65535uL) {
        a = (unsigned long)(unsigned int)ticks * tooth_x10;
        if ((unsigned int)(a >> 16) < tooth_dt) {
            a = (unsigned int)(a / tooth_dt);
        } else {
            a = 65535uL;
        }
    } else {
        a = (ticks * (unsigned long)tooth_x10) / (unsigned long)tooth_dt;
    }
    if (cycle_x10 != 0u && a > (unsigned long)cycle_x10) {
        /* Longer than a whole cycle. That is a configuration fault or a
           stalling engine, and either way the event cannot be placed - clamp
           rather than wrap, so it lands at the cycle boundary instead of
           somewhere that looks deliberate. */
        a = (unsigned long)cycle_x10;
    }
    if (a > 65535uL) {
        a = 65535uL;
    }
    return (unsigned int)a;
}


/* Half the cylinders, at least one. The pairing divisor for wasted spark and
   semi-sequential injection: cylinder i and cylinder i + n/2 share an output
   because on an even-firing engine their TDCs are 360 degrees apart. */
static unsigned char half_of(unsigned char cylinders)
{
    unsigned char h = (unsigned char)(cylinders / 2u);
    return (h == 0u) ? 1u : h;
}


unsigned char hc_plan_ign_cyls(unsigned char cylinders)
{
    /* NO STRATEGY ARGUMENT, and the asymmetry with hc_plan_inj_cyls() is the
       answer rather than an oversight: every ignition strategy walks every
       cylinder. Even a single-coil distributor does - one OUTPUT, but n
       distinct events per cycle, each at its own cylinder's advance, because
       the rotor decides which cylinder receives the spark. Sharing an output
       is not sharing an event. Batch injection is the only case in this file
       where cylinders genuinely collapse. */
    return (cylinders > HC_PLAN_MAX_CYL) ? HC_PLAN_MAX_CYL : cylinders;
}


unsigned char hc_plan_inj_cyls(unsigned char cylinders,
                               unsigned char inj_strategy)
{
    if (cylinders == 0u) {
        return 0u;
    }
    if (inj_strategy == HC_INJ_BATCH) {
        /* One bank event, not one per cylinder. Every injector opens together,
           so walking all of them would emit the same event n times and inflate
           the fuel by a factor of n - the kind of wrong that produces a
           plausible schedule and a hydrolocked engine. The angle comes from
           cylinder 0, and hc_plan_inj_repeats() supplies the second firing of
           the cycle. */
        return 1u;
    }
    return (cylinders > HC_PLAN_MAX_CYL) ? HC_PLAN_MAX_CYL : cylinders;
}


unsigned char hc_plan_ign_slot(unsigned char cyl, unsigned char cylinders,
                               unsigned char ign_strategy)
{
    if (cylinders == 0u) {
        return HC_PLAN_SLOT_ALL;
    }
    if (cyl >= cylinders) {
        cyl = (unsigned char)(cyl % cylinders);
    }
    switch (ign_strategy) {
    case HC_IGN_WASTED_PAIRED:
        /* One coil per PAIR. The pair is i and i + n/2, which on an even-fire
           engine are the two cylinders 360 degrees apart - the compression and
           exhaust strokes the one coil serves. An odd cylinder count has no
           such pairing at all, which is why hc_validation.c refuses
           WASTED_PAIRED on one. */
        return (unsigned char)((cyl % half_of(cylinders)) + 1u);
    case HC_IGN_DISTRIBUTOR:
        /* One coil for the whole engine. Every cylinder still gets its own
           event at its own angle - the rotor decides where the spark goes -
           so this is a shared SLOT and not a shared event. */
        return 1u;
    case HC_IGN_WASTED_COP:
    case HC_IGN_SEQUENTIAL_COP:
    default:
        return (unsigned char)(cyl + 1u);
    }
}


unsigned char hc_plan_inj_slot(unsigned char cyl, unsigned char cylinders,
                               unsigned char inj_strategy)
{
    if (cylinders == 0u) {
        return HC_PLAN_SLOT_ALL;
    }
    if (cyl >= cylinders) {
        cyl = (unsigned char)(cyl % cylinders);
    }
    switch (inj_strategy) {
    case HC_INJ_BATCH:
        /* Every injector, together: one bank, no per-cylinder identity. The
           loop only ever reaches cylinder 0 here - hc_plan_inj_cyls() returns
           1 for batch - so this slot is the bank and nothing else maps to it. */
        return HC_PLAN_SLOT_ALL;
    case HC_INJ_SEMI_SEQ:
        return (unsigned char)((cyl % half_of(cylinders)) + 1u);
    case HC_INJ_SEQUENTIAL:
    default:
        return (unsigned char)(cyl + 1u);
    }
}


/* Firing position of cylinder `c`: how many cylinders fire before it. */
static unsigned char fire_pos(const unsigned int *tdc, unsigned char c,
                              unsigned char n)
{
    unsigned char j, p = 0u;

    for (j = 0u; j < n; j++) {
        if (tdc[j] < tdc[c] || (tdc[j] == tdc[c] && j < c)) {
            p++;
        }
    }
    return p;
}

unsigned char hc_plan_pair_lead(const unsigned int *tdc, unsigned char cyl,
                                unsigned char cylinders)
{
    unsigned char j, want;

    if (cylinders == 0u) {
        return 0u;
    }
    if (cylinders > HC_PLAN_MAX_CYL) {
        cylinders = HC_PLAN_MAX_CYL;
    }
    if (cyl >= cylinders) {
        cyl = (unsigned char)(cyl % cylinders);
    }
    want = (unsigned char)(fire_pos(tdc, cyl, cylinders) % half_of(cylinders));
    for (j = 0u; j < cylinders; j++) {
        if (fire_pos(tdc, j, cylinders) == want) {
            return j;
        }
    }
    return cyl;
}


unsigned char hc_plan_ign_repeats(unsigned char ign_strategy,
                                  unsigned char strokes)
{
    if (strokes != 4u) {
        /* The cycle IS a revolution: there is no second TDC to waste a spark
           at, and every repeat count collapses to one. */
        return 1u;
    }
    switch (ign_strategy) {
    case HC_IGN_WASTED_COP:
        /* One coil per cylinder, fired at its own compression TDC and again on
           the exhaust stroke 360 degrees later. Nothing else is mapped to this
           slot, so the second spark has to come from a repeat.

           WASTED_PAIRED IS NOT HERE, and that is not an oversight. Its second
           event is generated by the OTHER cylinder of the pair, at that
           cylinder's own TDC - which is the same 360 degrees away on an
           even-firing engine and is still CORRECT on one that is not. Adding a
           repeat as well would double every spark. */
        return 2u;
    case HC_IGN_WASTED_PAIRED:
    case HC_IGN_SEQUENTIAL_COP:
    case HC_IGN_DISTRIBUTOR:
    default:
        return 1u;
    }
}


unsigned char hc_plan_inj_repeats(unsigned char inj_strategy,
                                  unsigned char strokes)
{
    if (strokes != 4u) {
        return 1u;
    }
    switch (inj_strategy) {
    case HC_INJ_BATCH:
        /* Half a charge per revolution, twice a cycle. hc_plan_inj_cyls()
           walks ONE cylinder for batch, so this repeat is the whole of the
           second firing. */
        return 2u;
    case HC_INJ_SEMI_SEQ:
        /* Twice a cycle as well - but the second firing is the PAIRED
           cylinder's own event, exactly as for wasted-paired ignition, so no
           repeat. */
    case HC_INJ_SEQUENTIAL:
    default:
        return 1u;
    }
}


unsigned int hc_plan_repeat_x10(unsigned int base_x10, unsigned char n,
                                unsigned int cycle_x10)
{
    unsigned long a;

    if (cycle_x10 == 0u) {
        return 0u;
    }
    a = (unsigned long)(base_x10 % cycle_x10)
        + ((unsigned long)n * (unsigned long)HC_PLAN_REV_X10);
    return (unsigned int)(a % (unsigned long)cycle_x10);
}


unsigned char hc_plan_needs_cycle(unsigned char inj_strategy,
                                  unsigned char ign_strategy)
{
    /* THE COIL AND INJECTOR COUNTS ARE NOT ASKED, deliberately. An engine with
       one coil per cylinder can be run wasted-COP, which repeats every 360
       degrees and starts with no cam at all - a genuinely useful configuration
       for getting an unknown engine running before the cam signal is trusted.
       Confusing "has individual coils" with "must run sequentially" would make
       that impossible for no reason. */
    if (inj_strategy == HC_INJ_SEQUENTIAL) {
        return 1u;
    }
    if (ign_strategy == HC_IGN_SEQUENTIAL_COP) {
        return 1u;
    }
    /* A DISTRIBUTOR DOES NOT NEED A CAM, and the first version of this file
       said it did. One coil fires n times per cycle at the cylinders' own
       advances; on an even-firing engine those n angles repeat every 360
       degrees, so crank position alone puts every spark in the right place and
       the rotor decides which cylinder receives it. hc_validation.c has always
       classified it that way - "runs on crank position alone: batch and
       semi-sequential injection, wasted spark paired, WASTED COP,
       distributor" - and the runtime must not be stricter than the validator
       that already told the tuner the configuration was legal. */
    return 0u;
}
