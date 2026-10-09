/* Central permission layer. It never drives a pin. BENCH_SAFE is an absolute
 * compile-time veto even if every runtime health input passes. There is no
 * user-facing arm (V84, hcsafety.h). */
#include "hctarget.h"
#include "hcsafety.h"
#include "hcsched_dry.h"         /* hc_tl_inhibit */
#include "hcdeadline711.h"
#include "hctrigger.h"           /* trg_state: recovery only at a standstill */
#include "hcrtmon711.h"
unsigned int hc_outputs_allowed, hc_dbw_allowed;
unsigned int hc_ignition_allowed, hc_injection_allowed, hc_safety_inhibits;

/* Every watchdog service, wherever it comes from (hcts.c hc_srvwdt via
   TGT_SRVWDT_HOOK): the longest gap between two, in ms of the tick. */
static unsigned int wdt_last_ms;
void hc_rt_wdt_mark(void)
{
    extern unsigned int hc_tick_ms;
    unsigned int t = hc_tick_ms;
    HC_RT_MAX(wdt_gap_max, (unsigned int)(t - wdt_last_ms));
    wdt_last_ms = t;
}

/* The alarm: the topmost guard-band word, the first one an overflow of the
   user stack writes. Nothing is corrupted yet - the band and the 192 bytes
   below it are unallocated - but the stack has exceeded its budget and the
   runtime supervisor latches HC_RT_F_USTACK on it. */
unsigned int hc_stack_overflowed(void)
{
    return (*(unsigned int volatile *)(HC_STK_GUARD_HI - 2u) != HC_STK_PATTERN)
        ? 1u : 0u;
}

volatile unsigned int hc_rt_fault;
unsigned int hc_rt_exec_faults;
unsigned char hc_rt_armed;   /* set at main-loop entry: everything is up */
void hc_safety_init(void)
{
    hc_rt_fault = 0u; hc_rt_exec_faults = 0u;
    hc_rt_armed = 0u;
    hc_outputs_allowed = 0; hc_dbw_allowed = 0;
    hc_ignition_allowed = 0; hc_injection_allowed = 0;
    hc_safety_inhibits = 0x003Fu;
}

void hc_safety_service(unsigned int healthy, unsigned int cal_ok,
                       unsigned int crank_ok, unsigned int cycle_ok,
                       unsigned int key_on)
{
    unsigned int inhibit = 0;
    unsigned int was_allowed = hc_ignition_allowed;
    if (!healthy) inhibit |= HC_INHIBIT_ASIC;
    if (!cal_ok) inhibit |= HC_INHIBIT_CAL;
    if (!crank_ok) inhibit |= HC_INHIBIT_NO_CRANK;
    if (!cycle_ok) inhibit |= HC_INHIBIT_NO_CYCLE;
    if (!key_on) inhibit |= HC_INHIBIT_KEYOFF;
    if (hc_tl_inhibit) inhibit |= HC_INHIBIT_TEST;       /* V92 '!K' */
#if defined(HANICORE_BENCH_SAFE)
    inhibit |= HC_INHIBIT_BENCH_SAFE;
#endif
    hc_safety_inhibits = inhibit;

    /* EACH CLASS IS JUDGED ON THE INHIBITS THAT APPLY TO IT.
     *
     * hc_outputs_allowed keeps the strictest reading - every inhibit clear -
     * because it is the umbrella answer a bench and the .ini both read.
     *
     * Spark and fuel are scheduled against an ENGINE ANGLE, so they need the
     * crank. The 720-degree requirement is NOT applied here: a wasted-spark
     * or batch-injection engine never needs to know which revolution it is
     * in, and hc_validate() already refuses SEQUENTIAL strategies that do.
     * Applying it here would have refused to run a perfectly valid
     * wasted-spark configuration for ever.
     *
     * The throttle is a POSITION, not an angle. It takes the ALWAYS set only,
     * which is what lets it hold a start position before the engine turns. */
    hc_outputs_allowed = (unsigned int)(inhibit == 0u);
    hc_dbw_allowed =
        (unsigned int)((inhibit & (unsigned int)HC_INHIBIT_ALWAYS) == 0u);
    hc_ignition_allowed =
        (unsigned int)((inhibit & (unsigned int)HC_INHIBIT_ANGLE) == 0u);
    hc_injection_allowed = hc_ignition_allowed;
    if (was_allowed && !hc_ignition_allowed) hc_drysched_cancel(0u);
}
