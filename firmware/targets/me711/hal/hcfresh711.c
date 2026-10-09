#include "hcfarbridge.h"
#include <reg167.h>
#include "hctarget.h"
#include "hchal.h"
#include "hc_route.h"
#include "hc_pin_descriptor.h"
#include "hcfresh711.h"
#include "hcasicstart.h"
#include "hchal_me711.h"
#include "hc_dbw.h"
#include "hcetbcal.h"
#include "hcatomic.h"
extern unsigned int adc_raw[];
#define BOUND ((unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_ROUTE))
#define PHYS_NONE 0xFFu
#define S5500_N 16u
#define WIN_RAW(i) (((unsigned int huge *)(TGT_EXTRAM_BASE + TGT_RAM_S5500WIN))[(i)])
static const unsigned char PHYS[HC_AIN_COUNT] = {
    TGT_ADC_BATT_CH,      /* HC_AIN_VBAT      AN5  UBAT                     */
    HC_ADC_ASIC(0),       /* HC_AIN_CLT       ASIC AN0  TMOT, cavity 93     */
    HC_ADC_ASIC(1),       /* HC_AIN_IAT       ASIC AN1  TANS, cavity 26     */
    PHYS_NONE,            /* HC_AIN_MAP       ME7.1.1 is MAF-load; no MAP   */
    TGT_ADC_TPS1_CH,      /* HC_AIN_TPS1      AN1  IP1S                     */
    TGT_ADC_TPS2_CH,      /* HC_AIN_TPS2      AN3  IP2S                     */
    TGT_ADC_PEDAL1_CH,    /* HC_AIN_APP1      AN8  SPS1                     */
    TGT_ADC_PEDAL2_CH,    /* HC_AIN_APP2      AN9  SPS2                     */
    TGT_ADC_HFM_CH,       /* HC_AIN_MAF       AN0  HFM, analog on this ECU  */
    TGT_ADC_HFM2_CH,      /* HC_AIN_MAF2      AN13 HFM2                     */
    TGT_ADC_TPS1_AMP_CH,    /* HC_AIN_TPS1_AMP    AN2  IPV                      */
    TGT_ADC_LS1VK_CH,     /* HC_AIN_O2_1_PRE  AN6  LS1VK                    */
    TGT_ADC_LS1HK_CH,     /* HC_AIN_O2_1_POST AN7  LS1HK                    */
    TGT_ADC_LS2VK_CH,     /* HC_AIN_O2_2_PRE  AN4  LS2VK                    */
    TGT_ADC_LS2HK_CH,     /* HC_AIN_O2_2_POST AN10 LS2HK                    */
    TGT_ADC_KNOCK_CH      /* HC_AIN_KNOCK     AN15 KI                       */
};

extern unsigned int hc_tick_ms;
extern unsigned char far hc_dbw_bridge_on_f(void);
typedef char fresh_fits[((TGT_RAM_ADC_META - TGT_RAM_ROUTE + 76uL)
                       <= TGT_RAM_CJ_ACQ - TGT_RAM_ROUTE) ? 1 : -1];

/* Eight qualified samples per track cover rapid fixture sampling as well
   as the real adjacent AN1/AN3 sweep. No prediction or extrapolation. */
typedef struct {
    unsigned int raw[2][8], ms[2][8];
    unsigned int seq[2], pair[2], pair_ms;
    unsigned char head[2], n[2], valid;
} hc_tps_history_t;
#define H (*(hc_tps_history_t huge *)(TGT_EXTRAM_BASE + TGT_RAM_TPS_HISTORY))
typedef char history_fits[(sizeof(hc_tps_history_t) <= TGT_RAM_TPS_HISTORY_LIMIT) ? 1 : -1];
static unsigned char channel(unsigned char sem);

/* the 1 ms tick writes the MAIN samples (hc_hal_main_sample via
   adc_service), so every main-loop read-modify-write of MAIN_LIVE and every
   multi-entry read of the TPS history H takes the critical level
   (hcatomic.h). Single-word reads stay as they are. */
void far hc_fresh_init(void)
{
    unsigned char i;
    unsigned int ps;
    HC_ATOMIC_ENTER(ps);
    for (i = 0u; i < 38u; i++) ADC_META[i] = 0u;
    H.head[0] = 0u; H.head[1] = 0u; H.n[0] = 0u; H.n[1] = 0u;
    H.seq[0] = 0u; H.seq[1] = 0u; H.pair[0] = 0u; H.pair[1] = 0u;
    H.pair_ms = 0u; H.valid = 0u;
    for (i = 0u; i < 8u; i++) {
        H.raw[0][i] = 0u; H.raw[1][i] = 0u;
        H.ms[0][i] = 0u; H.ms[1][i] = 0u;
    }
    HC_ATOMIC_EXIT(ps);
}

void far hc_fresh_service(void)
{
    unsigned char i;
    unsigned int ps;
    for (i = 0u; i < TGT_ADC_CH_COUNT; i++) {
        HC_ATOMIC_ENTER(ps);
        if ((MAIN_LIVE & (unsigned int)(1u << i))
            && (unsigned int)(hc_tick_ms - ADC_META[2u * i]) > TGT_ADC_FRESH_MS) {
            MAIN_LIVE &= (unsigned int)~(1u << i);
        }
        HC_ATOMIC_EXIT(ps);
    }
    if (ASIC_SAMPLE_LIVE
        && (unsigned int)(hc_tick_ms - ASIC_SAMPLE_MS) > TGT_ASIC_FRESH_MS) {
        ASIC_SAMPLE_LIVE = 0u;
    }
    /* Control ownership has a deadline even if ADC scans keep completing
       while serial work delays the ordinary control raster. */
    /* This service also runs from serial yields. It only releases existing
       ownership; main-loop and serial yields share the guarded control raster. */
    if (!(P6 & (1u << TGT_KL15STAT_PORT_BIT))) {
        if (!hc_etbcal_supervise(ETB_WHY_NOTLIVE)
            && (hc_dbw_bridge_on_f() || hc_dbw_state() != DBW_OFF)) hc_dbw_shutdown(0u);
    } else if (!hc_fresh_ok(HC_AIN_TPS1) || !hc_fresh_ok(HC_AIN_TPS2)) {
        if (!hc_etbcal_supervise(hc_fresh_tps_why())
            && hc_dbw_bridge_on_f()) hc_dbw_shutdown(DBW_F_STALE);
    } else if ((hc_etbcal_status() & 0x00F0u) == 0u
               && hc_dbw_state() == DBW_RUN
               && hc_dbw_term(DBW_T_OVR) == 0xFFFFu   /* the pedal owns the target */
               && (!hc_fresh_ok(HC_AIN_APP1) || !hc_fresh_ok(HC_AIN_APP2))) {
        hc_dbw_shutdown(DBW_F_STALE);
    } else if (hc_dbw_bridge_on_f() && !hc_fresh_ok(HC_AIN_VBAT)) {
        hc_dbw_shutdown(DBW_F_VBAT);
        hc_etbcal_supervise(ETB_WHY_V_FAULT);
    } else if (hc_dbw_state() == DBW_RUN && hc_dbw_bridge_on_f()
               && (hc_etbcal_status() & 0x00F0u) == 0u
               && (unsigned int)(hc_tick_ms - hc_dbw_term(DBW_T_CONTROL_MS)) > 100u) {
        hc_dbw_shutdown(DBW_F_STALE);
    }
    hc_etbcal_supervise(ETB_WHY_NONE);
}

void far hc_hal_main_sample(unsigned char ch, unsigned int word,
                            unsigned char done, unsigned int ms)
{
    unsigned int sample_mask;
    unsigned char track, j;
    if (ch >= TGT_ADC_CH_COUNT) return;
    sample_mask = (unsigned int)(1u << ch);
    if (!done || (unsigned char)(word >> 12) != ch) {
        MAIN_LIVE &= (unsigned int)~sample_mask;
        MAIN_BAD |= sample_mask;
        H.valid = 0u;
        return;
    }
    /* Publish the value and its qualification as one transaction. The old
       MAIN path qualified first, then wrote adc_raw separately. */
    adc_raw[ch] = (unsigned int)(word & 0x03FFu);
    MAIN_SEEN |= sample_mask; MAIN_BAD &= (unsigned int)~sample_mask;
    for (track = 0u; track < 2u; track++) {
        if (ch == channel((unsigned char)(HC_AIN_TPS1 + track))) {
            j = H.head[track];
            H.raw[track][j] = adc_raw[ch]; H.ms[track][j] = ms;
            H.head[track] = (unsigned char)((j + 1u) & 7u);
            if (H.n[track] < 8u) H.n[track]++;
        }
    }
    ADC_META[2u * ch] = ms;
    ADC_META[2u * ch + 1u]++;
    MAIN_LIVE |= sample_mask;
}

unsigned int far hc_hal_asic_age(void)
{
    return (ASIC_SAMPLE_LIVE && hc_asic_run_live)
        ? (unsigned int)(hc_tick_ms - ASIC_SAMPLE_MS) : 0xFFFFu;
}

static unsigned char channel(unsigned char sem)
{
    unsigned char p = BOUND[sem];
    if (p >= TGT_ADC_CH_COUNT && !HC_ADC_IS_ASIC(p)
        && sem != HC_AIN_TPS1 && sem != HC_AIN_TPS2
        && sem != HC_AIN_APP1 && sem != HC_AIN_APP2) p = PHYS[sem];
    return p;
}

unsigned int far hc_hal_ain_age(unsigned char sem)
{
    unsigned char p;
    if (sem >= HC_AIN_COUNT) return 0xFFFFu;
    p = channel(sem);
    if (p >= TGT_ADC_CH_COUNT && !HC_ADC_IS_ASIC(p)) return 0xFFFFu;
    if (p < TGT_ADC_CH_COUNT && !(MAIN_SEEN & (1u << p))) return 0xFFFFu;
    return HC_ADC_IS_ASIC(p) ? hc_hal_asic_age()
        : (unsigned int)(hc_tick_ms - ADC_META[2u * p]);
}

unsigned int far hc_hal_main_seq(unsigned char sem)
{
    unsigned char p;
    if (sem >= HC_AIN_COUNT) return 0u;
    p = channel(sem);
    return p < TGT_ADC_CH_COUNT ? ADC_META[2u * p + 1u] : 0u;
}

static unsigned char s5500_sample(unsigned char code, unsigned int *v)
{
    unsigned char ch, i;
    unsigned int w;

    /* keyed on the ASIC channel the BINDING names, not on the semantic,
       so IAT routed to cavity 93 reads ASIC AN0 - which hc_route_check()
       then reports as a disagreement - instead of quietly reading AN1. Only
       AN0 and AN1 are established in the runtime frame. */
    if (!HC_ADC_IS_ASIC(code)) {
        return 0u;
    }
    ch = (unsigned char)(code & 0x0Fu);
    if (ch > 1u) {
        return 0u;
    }
    /* ASIC channel ch lives in frame word 4 + ch; the window starts at
       hc_s5500_base, which the bench can move. */
    if ((unsigned char)(4u + ch) < hc_s5500_base) {
        return 0u;
    }
    i = (unsigned char)(4u + ch - hc_s5500_base);
    if (i >= (unsigned char)S5500_N || hc_hal_asic_age() > TGT_ASIC_FRESH_MS) {
        return 0u;
    }
    w = WIN_RAW(i);
    if ((unsigned int)((w >> 12) & 0x000Fu) != (unsigned int)ch) {
        return 0u;
    }
    *v = (unsigned int)(w & 0x03FFu);
    return 1u;
}
void far hc_fresh_bind(unsigned char sem, unsigned char adc_ch)
{
    unsigned int ps;
    if (sem < HC_AIN_COUNT) {
        HC_ATOMIC_ENTER(ps);
        if (BOUND[sem] != adc_ch && (sem == HC_AIN_TPS1 || sem == HC_AIN_TPS2)) {
            H.n[0] = 0u; H.n[1] = 0u; H.valid = 0u;
        }
        BOUND[sem] = adc_ch;
        HC_ATOMIC_EXIT(ps);
    }
}

unsigned char far hc_fresh_bound(unsigned char sem)
{
    return (sem < HC_AIN_COUNT) ? BOUND[sem] : HC_ADC_NONE;
}

unsigned int far hc_fresh_asic_an(unsigned char ch)
{
    unsigned char i;
    unsigned int w;

    if (ch > 15u || (unsigned char)(4u + ch) < hc_s5500_base) {
        return 0xFFFFu;
    }
    i = (unsigned char)(4u + ch - hc_s5500_base);
    if (i >= (unsigned char)S5500_N || hc_hal_asic_age() > TGT_ASIC_FRESH_MS) {
        return 0xFFFFu;
    }
    w = WIN_RAW(i);
    if ((unsigned int)((w >> 12) & 0x000Fu) != (unsigned int)ch) {
        return 0xFFFFu;
    }
    return (unsigned int)(w & 0x03FFu);
}

unsigned int far hc_fresh_ain(unsigned char sem)
{
    unsigned char p;
    unsigned int v;

    if (sem >= HC_AIN_COUNT) {
        return 0u;
    }
    /* THE CONFIGURED CAVITY FIRST, the board's own default second. */
    p = channel(sem);
    if (p < TGT_ADC_CH_COUNT) {
        return adc_raw[p];
    }
    /* S5500-backed: only a sample the ADC tagged as the right channel - see
       s5500_sample(). Anything else returns 0 and hc_hal_ain_ok() says so. */
    if (s5500_sample(p, &v)) {
        return v;
    }
    return 0u;
}

unsigned char far hc_fresh_phys(unsigned char sem)
{
    unsigned char p;

    if (sem >= HC_AIN_COUNT) {
        return 0xFFu;
    }
    /* the channel hc_hal_ain() reads: the bound one, else the board's own */
    p = channel(sem);
    return (p < TGT_ADC_CH_COUNT || HC_ADC_IS_ASIC(p)) ? p : 0xFFu;
}

unsigned char far hc_fresh_ok(unsigned char sem)
{
    unsigned char p;

    if (sem >= HC_AIN_COUNT) {
        return 0u;
    }
    /* Same resolution order as hc_hal_ain(), or eng_service() would substitute
       a default for a channel the configuration DID route - and the reading
       would be honest while the ok flag lied about it. */
    p = channel(sem);
    if (HC_ADC_IS_ASIC(p)) {
        unsigned int v;
        return s5500_sample(p, &v);
    }
    return (unsigned char)(p < TGT_ADC_CH_COUNT
        && (MAIN_LIVE & (unsigned int)(1u << p)) != 0u
        && (unsigned int)(hc_tick_ms - ADC_META[2u * p]) <= TGT_ADC_FRESH_MS);
}

unsigned char far hc_fresh_reason(unsigned char sem)
{
    unsigned char p;
    unsigned int mask;
    if (sem >= HC_AIN_COUNT) return HC_FRESH_NO_SOURCE;
    p = channel(sem);
    if (HC_ADC_IS_ASIC(p)) return hc_fresh_ok(sem) ? HC_FRESH_OK : HC_FRESH_STALE;
    if (p >= TGT_ADC_CH_COUNT) return HC_FRESH_NO_SOURCE;
    mask = (unsigned int)(1u << p);
    if (MAIN_BAD & mask) return HC_FRESH_REJECTED;
    if (!(MAIN_SEEN & mask)) return HC_FRESH_NEVER;
    if (!(MAIN_LIVE & mask)
        || (unsigned int)(hc_tick_ms - ADC_META[2u * p]) > TGT_ADC_FRESH_MS)
        return HC_FRESH_STALE;
    return HC_FRESH_OK;
}

/* Raw interpolation at a sample time bracketed by qualified observations.
   Divide into quotient/remainder before multiplication: every intermediate
   fits 16 bits (delta <= 1023, time <= 100). No Keil near-long helper in FCODE. */
static unsigned char aligned(unsigned char track, unsigned int age,
                              unsigned int now, unsigned int *raw)
{
    unsigned char j, k, older = 0u, newer = 0u;
    unsigned int a, ao = 0xFFFFu, an = 0u, vo = 0u, vn = 0u;
    unsigned int dt, span, delta, move;
    for (j = 0u; j < H.n[track]; j++) {
        k = (unsigned char)((H.head[track] + 7u - j) & 7u);
        a = (unsigned int)(now - H.ms[track][k]);
        if (a > TGT_ADC_FRESH_MS) continue;
        if (a >= age && (!older || a < ao)) {
            older = 1u; ao = a; vo = H.raw[track][k];
        }
        if (a <= age && (!newer || a > an)) {
            newer = 1u; an = a; vn = H.raw[track][k];
        }
    }
    if (!older || !newer) return 0u;
    if (ao == an) { *raw = vo; return 1u; }
    span = (unsigned int)(ao - an); dt = (unsigned int)(ao - age);
    delta = (vo > vn) ? (unsigned int)(vo - vn) : (unsigned int)(vn - vo);
    move = (unsigned int)((delta / span) * dt + ((delta % span) * dt) / span);
    *raw = vn >= vo ? (unsigned int)(vo + move) : (unsigned int)(vo - move);
    return 1u;
}

static unsigned char tps_pair(unsigned int *r1, unsigned int *r2,
                              unsigned int *sample_ms);
/* One consistent view of both tracks' history WITHOUT a lock: the tick
   appends a sample and THEN bumps that channel's sequence word
   (hc_hal_main_sample), so a pass that saw both sequences unchanged across
   the whole computation read a history nothing wrote into. Holding the
   critical level for it instead measured 103 us - a whole tooth at 9600 rpm
   for the crank capture to wait. A sample lands at most once a millisecond,
   so a retry is rare and three are plenty; giving up reads as "not aligned"
   (DBW stays in INIT for that pass). */
static unsigned int tps_seqs(void)
{
    unsigned char a = channel(HC_AIN_TPS1), b = channel(HC_AIN_TPS2);
    if (a >= TGT_ADC_CH_COUNT || b >= TGT_ADC_CH_COUNT) return 0u;
    return (unsigned int)(ADC_META[2u * a + 1u] + ADC_META[2u * b + 1u]);
}

unsigned char far hc_fresh_tps_pair(unsigned int *r1, unsigned int *r2,
                                    unsigned int *sample_ms)
{
    unsigned char ok, tries;
    unsigned int s;
    for (tries = 0u; tries < 3u; tries++) {
        s = tps_seqs();
        ok = tps_pair(r1, r2, sample_ms);
        if (s == tps_seqs()) return ok;
    }
    H.valid = 0u;
    return 0u;
}

static unsigned char tps_pair(unsigned int *r1, unsigned int *r2,
                              unsigned int *sample_ms)
{
    unsigned int a, b, age, seq1, seq2, now = hc_tick_ms;
    /* This history records MAIN samples only. Reject unsupported sources
       without indexing MAIN metadata with an ASIC/absent-source tag. */
    if (channel(HC_AIN_TPS1) >= TGT_ADC_CH_COUNT
        || channel(HC_AIN_TPS2) >= TGT_ADC_CH_COUNT) return 0u;
    if (!hc_fresh_ok(HC_AIN_TPS1) || !hc_fresh_ok(HC_AIN_TPS2)) {
        H.valid = 0u;
        return 0u;
    }
    seq1 = hc_hal_main_seq(HC_AIN_TPS1); seq2 = hc_hal_main_seq(HC_AIN_TPS2);
    if (!H.valid || (seq1 != H.seq[0] && seq2 != H.seq[1])) {
        a = (unsigned int)(now - ADC_META[2u * channel(HC_AIN_TPS1)]);
        b = (unsigned int)(now - ADC_META[2u * channel(HC_AIN_TPS2)]);
        age = a > b ? a : b;
        if (!aligned(0u, age, now, r1) || !aligned(1u, age, now, r2)) {
            H.valid = 0u;
            return 0u;
        }
        H.pair[0] = *r1; H.pair[1] = *r2;
        H.pair_ms = (unsigned int)(now - age);
        H.seq[0] = seq1; H.seq[1] = seq2; H.valid = 1u;
    }
    if ((unsigned int)(now - H.pair_ms) > TGT_ADC_FRESH_MS) {
        H.valid = 0u;
        return 0u;
    }
    *r1 = H.pair[0]; *r2 = H.pair[1]; *sample_ms = H.pair_ms;
    return 1u;
}

/* Preserve the source/qualification cause instead of folding all failures
   into NO TPS INPUT. Per-track reason nibbles are captured by AutoCal. */
unsigned char far hc_fresh_tps_why(void)
{
    unsigned char a = hc_fresh_reason(HC_AIN_TPS1);
    unsigned char b = hc_fresh_reason(HC_AIN_TPS2);
    if (a == HC_FRESH_NO_SOURCE || b == HC_FRESH_NO_SOURCE) return ETB_WHY_NOTPS;
    if (a == HC_FRESH_REJECTED || b == HC_FRESH_REJECTED) return ETB_WHY_ADC;
    if (a == HC_FRESH_NEVER || b == HC_FRESH_NEVER) return ETB_WHY_NOSAMPLE;
    return ETB_WHY_STALE;
}
