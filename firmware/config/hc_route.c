/*
 * hc_route.c - resolve a semantic channel to a physical pin, and check it.
 *
 * Read hc_route.h for what this layer is for and what it deliberately does
 * not do yet.
 */
#ifdef HC_FAR_BRIDGE
#include "hcfarbridge.h"  /* FIRST: this module is FAR code on ME7.1.1 */
#endif
#include "hctarget.h"
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hc_pin_descriptor.h"
#include "hc_route.h"
#include "hchal.h"
#include "hc_config_manager.h"
#ifdef HC_FAR_BRIDGE
#include "hcfarinline.h"   /* AFTER hcconfig.h: call-free page reads */
#endif

/* Which universal-block field holds the connector pin for each semantic
 * analog channel.
 *
 * GENERATED OFFSETS, not literals - CFG_U_PIN_* come out of
 * hc_config_generated.h, which the compiler has already checked against
 * hcconfig.h. 0xFFFF means "this semantic channel has no configuration field",
 * which is the honest answer for the four lambda and air-mass channels the
 * universal model does not route individually yet.
 *
 * The array is indexed by HC_AIN_*, so it is ordered by hchal.h and NOT by
 * anything in this file. If hchal.h gains a channel, the compile-time check at
 * the bottom fails until this table gains a row - which is the point.
 */
static const unsigned int AIN_PIN_FIELD[HC_AIN_COUNT] = {
    CFG_U_PIN_VBAT,      /* HC_AIN_VBAT      */
    CFG_U_PIN_CLT,       /* HC_AIN_CLT       */
    CFG_U_PIN_IAT,       /* HC_AIN_IAT       */
    CFG_U_PIN_MAP,       /* HC_AIN_MAP       */
    CFG_U_PIN_TPS1,      /* HC_AIN_TPS1      */
    CFG_U_PIN_TPS2,      /* HC_AIN_TPS2      */
    CFG_U_PIN_APP1,      /* HC_AIN_APP1      */
    CFG_U_PIN_APP2,      /* HC_AIN_APP2      */
    CFG_U_PIN_MAF,       /* HC_AIN_MAF       */
    0xFFFFu,             /* HC_AIN_MAF2      - no universal field             */
    0xFFFFu,             /* HC_AIN_TPS1_AMP    - amplified TPS1, diagnostic only  */
    CFG_U_PIN_LAMBDA1,   /* HC_AIN_O2_1_PRE  */
    0xFFFFu,             /* HC_AIN_O2_1_POST - no universal field             */
    CFG_U_PIN_LAMBDA2,   /* HC_AIN_O2_2_PRE  */
    0xFFFFu,             /* HC_AIN_O2_2_POST - no universal field             */
    0xFFFFu              /* HC_AIN_KNOCK     - conditioned by the knock IC    */
};

typedef char hc_route_assert_ain_count[
    (sizeof(AIN_PIN_FIELD) / sizeof(AIN_PIN_FIELD[0]) == HC_AIN_COUNT) ? 1 : -1];

unsigned char hc_route_ain_pin(unsigned char sem)
{
    unsigned int off;

    if (sem >= HC_AIN_COUNT) {
        return HC_PIN_NONE;
    }
    off = AIN_PIN_FIELD[sem];
    if (off == 0xFFFFu) {
        return HC_PIN_NONE;
    }
    /* ACTIVE, not DESIRED. What the runtime is using is what a routing check
       has to be about; a pending edit is by definition not routing yet. */
    return hc_cal_u8(off);
}

unsigned char hc_route_ain_adc(unsigned char sem)
{
    unsigned char pin = hc_route_ain_pin(sem);

    if (HC_PIN_IS_UNASSIGNED(pin)) {
        return HC_ADC_NONE;
    }
    /* The pin must actually be an analog input on this board before its ADC
       channel means anything. A cavity that is an injector driver has no
       business answering an analog question even if the descriptor happens to
       carry a channel number for it. */
    if (!hc_pin_can(pin, HC_PINCAP_AIN)) {
        return HC_ADC_NONE;
    }
    return hc_pin_adc_channel(pin);
}

unsigned int hc_route_ain_routed_mask(void)
{
    unsigned int m = 0u;
    unsigned char i;

    for (i = 0u; i < HC_AIN_COUNT; i++) {
        if (hc_route_ain_adc(i) != HC_ADC_NONE) {
            m |= (unsigned int)(1u << i);
        }
    }
    return m;
}

unsigned int hc_route_check(void)
{
    unsigned int bad = 0u;
    unsigned char i;
    unsigned char want;

    for (i = 0u; i < HC_AIN_COUNT; i++) {
        if (HC_PIN_IS_UNASSIGNED(hc_route_ain_pin(i))) {
            /* Not routed. A fresh universal block routes nothing, and that is
               the correct starting state rather than sixteen faults. */
            continue;
        }
        want = hc_route_ain_adc(i);
        if (want == HC_ADC_NONE) {
            /* Configured to a pin this board cannot read as an analog input.
               That IS a disagreement: the configuration asks for something the
               hardware descriptor refuses. */
            bad |= (unsigned int)(1u << i);
            continue;
        }
        /* Whether a sample has arrived yet is the sensor's state (sensorErr,
           halAinMask), not the route's: a check that asked it ran before the
           first samples and cached "every routed channel disagrees". */
        if (want != hc_hal_ain_phys(i)) {
            bad |= (unsigned int)(1u << i);
        }
    }
    return bad;
}

unsigned char hc_route_pin_ok(unsigned char pin, unsigned int need)
{
    return hc_pin_can(pin, need);
}

/* ---- the cached diagnostic pair -------------------------------------------
 *
 * hc_route_check() and hc_route_ain_routed_mask() each resolve all sixteen
 * semantic channels, and each resolution reads the ACTIVE configuration out of
 * external SRAM through a huge pointer and then walks the far descriptor
 * table. Calling both from update_live() - which runs on every output-channel
 * frame - cost about 3 ms of a single main-loop pass. Measured, not guessed:
 * me711_ts_gap_proof reported a 7 ms worst service gap where V26 and V27A both
 * report 4 ms, and the S5500 raster is 10 ms. Supervision starvation is the
 * one failure mode that has actually reset this ECU, so 3 ms of avoidable
 * main-loop work in the ASIC's own loop is not acceptable for a diagnostic.
 *
 * The answer can only change when the ACTIVE configuration changes, so it is
 * recomputed when hc_cfg_active_rev moves and cached otherwise. A revision of
 * zero is a real starting value, so validity is tracked separately rather than
 * inferred from it.
 */
static unsigned int  route_bad_cache;
static unsigned int  route_mask_cache;
static unsigned int  route_cache_rev;
static unsigned char route_cache_valid;

/* Startup invalidates HAL bindings even when the retained configuration
   revision has not changed. C startup initialisers do not run on this ECU. */
void HC_COLD hc_route_init(void)
{
    route_cache_valid = 0u;
}

void hc_route_service(void)
{
    if (route_cache_valid && route_cache_rev == hc_cfg_active_rev) {
        return;
    }

    /* AND NOW IT BINDS, which is what changed at V62.
     *
     * Up to V61 this function resolved and REPORTED and the HAL went on
     * reading its own compile-time table, so a configured cavity was checked
     * against the descriptor and then ignored. hc_route.h said why - inverting
     * the binding "can silently move a live sensor reading" - and named the
     * precondition: hc_route_check() clean. It is.
     *
     * A channel the configuration does not route binds HC_ADC_NONE, and
     * hc_hal_ain() then falls back to the target default. That is what keeps
     * an unconfigured page, and the Porsche board default, behaving exactly
     * as they did before. */
    {
        unsigned char s;
        for (s = 0u; s < (unsigned char)HC_AIN_COUNT; s++) {
            hc_hal_ain_bind(s, hc_route_ain_adc(s));
        }
    }
    /* Checked AFTER binding: the question is whether the HAL now reads what
       the configuration names. */
    route_bad_cache  = hc_route_check();
    route_mask_cache = hc_route_ain_routed_mask();

    route_cache_rev  = hc_cfg_active_rev;
    route_cache_valid = 1u;
}

unsigned int hc_route_check_cached(void)
{
    return route_cache_valid ? route_bad_cache : 0u;
}

unsigned int hc_route_routed_mask_cached(void)
{
    return route_cache_valid ? route_mask_cache : 0u;
}
