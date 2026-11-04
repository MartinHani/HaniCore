/*
 * hcvss711.c - the vehicle-speed input and gear detection (2026-11-04).
 *
 * The capture interrupt (hctrig_me711.c: ROLE_VSS on a free cam capture,
 * or CC14 = cavity 54 on the VAG boards) only counts edges and stamps the
 * millisecond of the last one (hc_vss_rec_t at TGT_RAM_VSS). Every 20 ms
 * this module turns that into km/h (firmware/sensors/hcvss.c, host-tested)
 * and detects the gear from the speed per 1000 rpm.
 *
 * hc_vss_x10() is THE vehicle speed for the rest of the firmware: the
 * input when the page routes one (pinVss), else the CAN source
 * (canVssSource, hccan711.c), else none.
 *
 * Live data (OCH 1664..1671, TGT_RAM_OCH3): 1664 vehicle speed (0.1 km/h,
 * 0xFFFF none), 1666 gear, 1668 speed per 1000 rpm (0.01 km/h), 1670 the
 * raw edge counter.
 *
 * Far module (MOD167 MEDIUM, HC_FAR_BRIDGE), no ?C_ helper.
 */
#include "hcfarbridge.h"
#include <reg167.h>
#include "hctarget.h"
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hcfarinline.h"
#include "hctrigger.h"
#include "hchal.h"
#include "hc_pin_descriptor.h"
#include "hccan711.h"
#include "hcvss711.h"

#define DIV32U(n, d)  ((unsigned int)((unsigned long)(n) / (unsigned int)(d)))
#include "hcvss.c"

typedef struct {
    hc_vss_rec_t  rec;            /* the ISR's record (first, at RAM_VSS)  */
    hcvss_state_t st;
    unsigned int  last_ms;        /* the 20 ms grid                        */
    unsigned int  wire;           /* the input's speed, 0xFFFF none        */
    unsigned int  sel;            /* the selected speed                    */
    unsigned char routed;         /* pinVss reaches a capture on this board */
} vss_rt_t;

#define VS (*(vss_rt_t huge *)(TGT_EXTRAM_BASE + TGT_RAM_VSS))
/* the last 4 bytes are the trigger module's HC_VSS_CCM / HC_VSS_IC */
typedef char vss_rt_fits[(sizeof(vss_rt_t) <= TGT_RAM_VSS_LIMIT - 4u) ? 1 : -1];

#define OCH3B ((unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_OCH3))
static void och3(unsigned int at, unsigned int v)
{
    OCH3B[at - TGT_OCH_SPLIT2] = (unsigned char)(v >> 8);
    OCH3B[at - TGT_OCH_SPLIT2 + 1u] = (unsigned char)(v & 0xFFu);
}

static void st_load(hcvss_state_t *s)
{
    s->n_prev = VS.st.n_prev; s->ms_prev = VS.st.ms_prev;
    s->raw_x10 = VS.st.raw_x10; s->f_x10 = VS.st.f_x10;
    s->have = VS.st.have; s->gear = VS.st.gear;
}

static void st_store(const hcvss_state_t *s)
{
    VS.st.n_prev = s->n_prev; VS.st.ms_prev = s->ms_prev;
    VS.st.raw_x10 = s->raw_x10; VS.st.f_x10 = s->f_x10;
    VS.st.have = s->have; VS.st.gear = s->gear;
}

void far hc_vss_init(void)
{
    unsigned int k;
    unsigned char p;
    hcvss_state_t s;

    for (k = 0u; k < (unsigned int)sizeof(vss_rt_t); k++) {
        ((unsigned char huge *)&VS)[k] = 0u;
    }
    for (k = 0u; k < (unsigned int)TGT_RAM_OCH3_LIMIT; k++) {
        OCH3B[k] = 0u;
    }
    p = hc_cal_u8(CFG_U_PIN_VSS);
#if TGT_VSS_CC14_PIN
    /* a board with its own speed capture takes the speed there only */
    VS.routed = (unsigned char)(p == (unsigned char)TGT_VSS_CC14_PIN);
#else
    VS.routed = (unsigned char)(!HC_PIN_IS_UNASSIGNED(p)
                                && hc_hal_capture_channel(p) != HC_CAPCH_NONE);
#endif
    hcvss_reset(&s, 0u);
    st_store(&s);
    VS.wire = 0xFFFFu;
    VS.sel = 0xFFFFu;
}

unsigned char far hc_vss_cam_channel(void)
{
    unsigned char p = hc_cal_u8(CFG_U_PIN_VSS), ch;
    if (HC_PIN_IS_UNASSIGNED(p) || (TGT_VSS_CC14_PIN != 0u && p == (unsigned char)TGT_VSS_CC14_PIN)) {
        return 0xFFu;
    }
    ch = hc_hal_capture_channel(p);
    return (ch == TGT_CAPCH_CC8 || ch == TGT_CAPCH_CC9) ? ch : 0xFFu;
}

#if TGT_VSS_CC14_PIN
void far hc_vss_arm(unsigned char on)
{
    /* the VAG boards' own speed capture: CC14 / P2.14, cavity 54, armed
       only when the page routes the speed input there (an unconnected input
       makes its own edges). Bit 3 of the nibble = T1, low three = the edge. */
    CC14IC = 0;
    CCM3 = (unsigned int)(CCM3 & 0xF0FFu);
    if (on && hc_cal_u8(CFG_U_PIN_VSS) == (unsigned char)TGT_VSS_CC14_PIN) {
        CCM3 = (unsigned int)(CCM3 | (HC_VSS_CCM << 8));
        CC14IC = HC_IC(TGT_ILVL_VSS, TGT_GLVL_VSS);
    }
}
#endif

unsigned int far hc_vss_wire_x10(void) { return VS.wire; }
unsigned int far hc_vss_x10(void) { return VS.sel; }
unsigned char far hc_vss_gear(void) { return VS.st.gear; }

void far hc_vss_service(unsigned int ms)
{
    hcvss_state_t s;
    unsigned int n, me, g[HCVSS_GEARS], k;
    unsigned char i, ng;

    if ((unsigned int)(ms - VS.last_ms) < 20u) {
        return;
    }
    VS.last_ms = ms;
    st_load(&s);
    if (VS.routed) {
        /* a consistent pair: the ISR writes n then ms */
        do {
            n = VS.rec.n;
            me = VS.rec.ms;
        } while (n != VS.rec.n);
        k = hcvss_k(hc_cal_u16(CFG_U_VSS_PPK));
        VS.wire = hcvss_step(&s, n, me, ms, k,
                             (unsigned char)hc_cal_u8v(CFG_U_VSS_FILTER),
                             (unsigned int)(hc_cal_u8v(CFG_U_VSS_TMO) * 10u));
    } else {
        VS.wire = 0xFFFFu;
    }
    VS.sel = (VS.wire != 0xFFFFu) ? VS.wire : hc_can_vss_x10();

    ng = (unsigned char)hc_cal_u8v(CFG_U_GEAR_N);
    if (ng > HCVSS_GEARS) {
        ng = 0u;
    }
    for (i = 0u; i < ng; i++) {
        g[i] = hc_cal_u16v((unsigned int)(CFG_U_GEAR_V + 2u * (unsigned int)i));
    }
    (void)hcvss_gear(&s, VS.sel, trg_rpm, g, ng,
                     (unsigned char)hc_cal_u8v(CFG_U_GEAR_BAND),
                     (unsigned int)(hc_cal_u8v(CFG_U_GEAR_MIN) * 10u));
    st_store(&s);

    och3(1664u, VS.sel);
    och3(1666u, (unsigned int)s.gear | (VS.routed ? 0x100u : 0u)
                | ((VS.wire != 0xFFFFu) ? 0x200u : 0u));
    och3(1668u, hcvss_v1000(VS.sel, trg_rpm));
    och3(1670u, VS.rec.n);
}
