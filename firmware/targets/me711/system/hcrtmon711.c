/* FAR runtime monitoring: main-context stack scans and the bounded,
   independent tick supervisor. Engine edges preempt both contexts. */
#include <reg167.h>
#include "hctarget.h"
#include "hcsafety.h"
#include "hcrtmon711.h"
#include "hcdeadline711.h"
#include "hcdeadline_state.h"
#include "hcsched_dry.h"
#include "hctrigger.h"
#include "hcengine.h"       /* eng_batt_dv (reset witness) */
#include "hcasicstart.h"    /* the S5500 counters          */
#include "hcumkom.h"        /* the monitoring exchange     */

unsigned int hc_stack_hwm, hc_sysstack_hwm;

/* Lay the pattern down. Called from main() before anything deep runs, so the
   only frames above each stack's top - HC_STK_KEEP are main()'s own and this
   one. The user stack's GUARD BAND is primed with it: the band is outside
   every linker class, so nothing but an overflow ever writes it. */
void far hc_stack_prime(void)
{
    unsigned int volatile *p;
    unsigned int volatile *end=(unsigned int volatile *)(HC_SSTK_TOP-HC_STK_KEEP);
    /* Skip the retained user frames and the gap between the two stacks. */
    for(p=(unsigned int volatile *)HC_STK_GUARD_LO;p<end;p++) {
        if(p==(unsigned int volatile *)(HC_STK_TOP-HC_STK_KEEP))
            p=(unsigned int volatile *)HC_SSTK_BOT;
        *p=HC_STK_PATTERN;
    }
    hc_stack_hwm = 0;
    hc_sysstack_hwm = 0;
}

/* The deepest point a stack has reached, in bytes from its top, by scanning
   UPWARD from `lo` for the first word that is not the pattern. A frame that
   happened to store the pattern value reads as untouched, which can only
   UNDER-report; that is why the guard band is a separate question. A user
   stack that reached into the guard band reports more than HC_STK_SIZE. */
static unsigned int stack_used(unsigned int lo, unsigned int top, unsigned int *hwm)
{
    unsigned int volatile *p;
    unsigned int volatile *end=(unsigned int volatile *)(top-HC_STK_KEEP);
    unsigned int used;
    for(p=(unsigned int volatile *)lo;p<end;p++) if(*p!=HC_STK_PATTERN) break;
    used=(unsigned int)(top-(unsigned int)p);
    if(used>*hwm) *hwm=used;
    return used;
}

unsigned int far hc_stack_used(void)
{
    return stack_used(HC_STK_GUARD_LO,HC_STK_TOP,&hc_stack_hwm);
}

unsigned int far hc_sysstack_used(void)
{
    return stack_used(HC_SSTK_BOT,HC_SSTK_TOP,&hc_sysstack_hwm);
}

/* ======================================================= health record == */
static unsigned int rt_scan_ms;

/* ================================================== THE RESET WITNESS ==
 * (2026-10-11) The car reset with the engine running - long hardware reset,
 * KL15 on, 14 V, DBW active - and no record said why: the CJ91x drops /RST
 * only on a 5 V power-down (CJ911 product info), the S5500 resets the CPU
 * after 5 wrong or late monitoring answers (FR UMKOM 7.10 +3/-1, react at
 * 13). This record, in battery-backed SRAM (the startup zeroes IRAM, so the
 * health record above does not survive), is rewritten every main-loop pass
 * and copied to its second half at the next boot. Words: */
#define WT_MAGIC  0x5257u          /* 'RW' */
#define WT_N      32u
#define WT ((unsigned int huge *)(TGT_EXTRAM_BASE + TGT_RAM_RSTWIT))
typedef char hc_rtwit_fits[(2u * WT_N * 2u <= TGT_RAM_RSTWIT_LIMIT) ? 1 : -1];
extern unsigned int  far hc_nvm_state_f(void);
extern void far hc_rst_progress_f(unsigned int ms, unsigned int loops,
                                  unsigned int fv, unsigned int lv,
                                  unsigned int wdt, unsigned int *tgt);
extern unsigned int loop_count, hc_firstvec, hc_lastvec, hc_wdt_services;
extern unsigned int hc_ssc_rx_vec, hc_ssc_err_vec, hc_tick_ms;
extern unsigned int  far hc_etbcal_status(void);

static void wt_boot(void)
{
    unsigned int i;
    if (WT[0] == WT_MAGIC) {
        for (i = 0u; i < WT_N; i++) WT[WT_N + i] = WT[i];
    } else {
        for (i = 0u; i < WT_N; i++) WT[WT_N + i] = 0u;
    }
    for (i = 0u; i < WT_N; i++) WT[i] = 0u;
    WT[0] = WT_MAGIC;
}

static void wt_update(unsigned int now_ms)
{
    /* WT[12]: ms without a good S5500 frame, worst since boot (kept in
       the SRAM record itself: this module's near data is at its reserve) */
    unsigned int g = (unsigned int)(now_ms - hc_asic_last_ok_ms);
    /* since 2026-10-13 the exchange (CC27 level) can stamp last_ok AFTER
       now_ms was read: a 'negative' gap is no gap (it read 65535) */
    if (hc_asic_run_ok != 0u && g < 0x8000u && g > WT[12]) WT[12] = g;
    WT[1]++;                                   /* seq                     */
    WT[2] = now_ms;                            /* uptime, ms              */
    WT[3] = trg_rpm;
    WT[4] = eng_batt_dv;                       /* 0.1 V                   */
    WT[5] = hc_etbcal_status();                /* ETB procedure / phase   */
    WT[6] = hc_asic_run_ok;
    WT[7] = hc_asic_run_csum_err;
    WT[8] = hc_asic_run_timeout;
    WT[9] = hc_umkom_mismatch;
    WT[10] = (unsigned int)(hc_umkom_health | ((unsigned int)hc_umkom_expect << 8));
    WT[11] = hc_umkom_last_rx;
    WT[13] = (unsigned int)(hc_nvm_state_f() | ((unsigned int)trg_state << 8));
    WT[14] = HC_RT.pass_max;                   /* T, main-loop pass worst */
    WT[15] = HC_RT.wdt_gap_max;                /* ms                      */
    WT[16] = HC_RT.beat_age_max;               /* ms                      */
    WT[17] = HC_RT.rt_fault;
    WT[18] = HC_RT.ustk_hwm;
    WT[19] = HC_RT.sstk_hwm;
    WT[20] = HC_RT.svc_dbw;                    /* T                       */
    WT[21] = HC_RT.svc_comms;                  /* T                       */
}

/* THE S5500 RUNTIME RASTER, START TO START (2026-10-13). The 2026-10-13 car
 * reset 9 times while running (long hardware reset 0x1C) and its raster
 * averaged 10.7-10.8 ms (asicTx / tickMs); WT[12] above has 1 ms and
 * main-loop-pass resolution. hcasicstart.c calls this at every runtime
 * frame start with T7 (0.8 us):
 *   WT[22] longest period, T7     WT[23] shortest period, T7
 *   WT[24..27] periods > 10.5 / 11 / 12 / 15 ms    WT[28] periods < 9.5 ms
 *   WT[29] the previous start's T7 (a period > 52 ms wraps: those are
 *          transfer timeouts, which WT[8] counts). */
#define WT_T7_MS(x10) ((unsigned int)((x10) * 125u))   /* 0.1 ms -> T7     */
void far hc_rtwit_frame_start(unsigned int t7)
{
    unsigned int per;
    if (WT[29] == 0u && WT[22] == 0u) {        /* the first runtime frame  */
        WT[29] = t7 | 1u;
        return;
    }
    per = (unsigned int)(t7 - WT[29]);
    WT[29] = t7 | 1u;
    if (per > WT[22]) WT[22] = per;
    if (WT[23] == 0u || per < WT[23]) WT[23] = per;
    if (per > WT_T7_MS(105u)) WT[24]++;
    if (per > WT_T7_MS(110u)) WT[25]++;
    if (per > WT_T7_MS(120u)) WT[26]++;
    if (per > WT_T7_MS(150u)) WT[27]++;
    if (per < WT_T7_MS(95u))  WT[28]++;
}

/* A BENCH EXPERIMENT, NOT A FEATURE: '!Z' ms every_ms holds the main loop
 * for `ms` (<= 50) every `every_ms` (0 = every pass) WITHOUT servicing the
 * S5500 - what does it tolerate before it resets MAIN? Engine stopped only
 * (rpm 0 is checked at every stall), WT[30] = ms | every_ms << 8, WT[31] the
 * last stall's tick. Both are in the witness, so EVERY boot clears them: a
 * reset ends the experiment. Interrupts keep running; the C167 watchdog
 * (200 ms) is not at risk. */
void far hc_rtwit_stall_set(unsigned char ms, unsigned char every_ms)
{
    if (ms > 50u) ms = 50u;
    WT[31] = 0u;
    WT[30] = (unsigned int)(ms | ((unsigned int)every_ms << 8));
}

void far hc_rtwit_stall_service(unsigned int now_ms)
{
    unsigned int ms = WT[30] & 0xFFu, t0, n;
    if (ms == 0u) return;
    if (trg_rpm != 0u) { WT[30] = 0u; return; }
    if ((unsigned int)(now_ms - WT[31]) < (WT[30] >> 8)) return;
    WT[31] = now_ms;
    n = (unsigned int)(ms * 1250u);            /* <= 62500 T7 < one wrap   */
    t0 = T7;
    while ((unsigned int)(T7 - t0) < n) { }
}

unsigned char far hc_rtwit_byte(unsigned int off)
{
    unsigned int w;
    if (off >= TGT_WT_EXPORT_BYTES) return 0u;
    w = WT[off >> 1];
    return (unsigned char)((off & 1u) ? w : (w >> 8));
}

void far hc_rtmon_init(void)
{
    unsigned int volatile *p = (unsigned int volatile *)&HC_RT;
    unsigned int i;
    wt_boot();
    for (i = 0; i < sizeof(hc_rt_t) / 2u; i++) p[i] = 0u;
    HC_RT.ver = HC_RT_VER;
    rt_scan_ms = 0u;
}

/* Main loop. The two stack scans are ~1300 instructions together; each
   runs ten times a second, ALTERNATING every 50 ms (2026-10-12: both in one
   pass were ~1.3 ms of the longest main-loop pass in c167sim,
   me711_pinwrite_gap_proof). WHICH stack is next is the low bit of
   rt_scan_ms (1 = the system stack): near RAM has no byte left for a flag,
   and a scan 1 ms early or late changes nothing. The mirrors are a few
   loads. */
void far hc_rtmon_service(unsigned int now_ms)
{
    wt_update(now_ms);
    if(HC_RT.abort_pending) hc_deadline_abort_history();
    HC_RT.rt_fault = hc_rt_fault;
    HC_RT.exec_faults = hc_rt_exec_faults;
    if ((unsigned int)(now_ms - rt_scan_ms) >= 50u) {
        if (rt_scan_ms & 1u) {
            (void)hc_sysstack_used();
            HC_RT.sstk_hwm = hc_sysstack_hwm;
        } else {
            (void)hc_stack_used();
            HC_RT.ustk_hwm = hc_stack_hwm;
        }
        rt_scan_ms = (unsigned int)((now_ms & ~1u) | ((rt_scan_ms & 1u) ^ 1u));
    }
}

unsigned char far hc_rt_byte(unsigned int off)
{
    unsigned int w;
    if (off >= TGT_RT_EXPORT_BYTES) return 0u;
    w = ((unsigned int volatile *)&HC_RT)[off >> 1];
    return (unsigned char)((off & 1u) ? w : (w >> 8));
}

/* ============================================ the runtime supervisor ==
   See hcsafety.h. FAR code, entered from the 1 ms tick ISR. */
static unsigned int sup_beat, sup_age, sup_ok;
/* The beat and the head-overdue check see a
   CC25 that stops; they cannot see one that keeps running while an output's
   OFF never comes (a corrupt queue time or link hides it behind a head that
   is not due). Every output the executor holds ON is timed here, from its ON
   bit alone - not from the queue that failed: a coil ON longer than the
   MAXDWELL backstop allows, an injector ON longer than the longest pulse the
   admission can produce (fuel + dead time, two u16 us, x 1.25 ticks), is an
   executor fault. Elapsed capture-clock ms per output, saturating; zero
   while OFF, or after a new actual injector OPEN following its own CLOSE. */
static unsigned char sup_on_ms[16];
static unsigned int sup_live;   /* outputs ON at the previous supervision */
static const unsigned char sup_limit[16]={
    HC_RT_COIL_MS,HC_RT_COIL_MS,HC_RT_COIL_MS,HC_RT_COIL_MS,
    HC_RT_COIL_MS,HC_RT_COIL_MS,HC_RT_COIL_MS,HC_RT_COIL_MS,
    HC_RT_INJ_MS,HC_RT_INJ_MS,HC_RT_INJ_MS,HC_RT_INJ_MS,
    HC_RT_INJ_MS,HC_RT_INJ_MS,HC_RT_INJ_MS,HC_RT_INJ_MS};

/* See hcsafety.h. Bounded 16-output scan in the 1 ms tick ISR (ILVL 8). */
void far hc_rt_supervise(void)
{
    unsigned int f = 0u;
    unsigned char h;
    unsigned int b,elapsed,t=T1;
    unsigned long ticks;

    if (!hc_rt_armed) {
        sup_beat = hc_dl_beat; sup_age = 0u; sup_ok = 0u; sup_live = 0u;
        HC_RT.clock_last=t;HC_RT.clock_frac=0u;
        for (b = 0u; b < 16u; b++) sup_on_ms[b] = 0u;
        return;
    }
    /* Tick entries can be delayed; output ages use elapsed capture-clock
       time, including a fractional millisecond, rather than entry count. */
    ticks=(unsigned long)(unsigned int)(t-HC_RT.clock_last)+HC_RT.clock_frac;
    HC_RT.clock_last=t;
    elapsed=(unsigned int)(ticks/(unsigned int)(TGT_TICKS_PER_MS_X10/10u));
    HC_RT.clock_frac=(unsigned int)((unsigned int)ticks-elapsed*(TGT_TICKS_PER_MS_X10/10u));
    h = hc_deadline_health();
    b = hc_dl_beat;

    if (b != sup_beat) {
        sup_beat = b;
        sup_age = 0u;
    } else {
        sup_age+=elapsed;
        if(sup_age>HC_RT_BEAT_MS) f|=HC_RT_F_EXEC_DEAD;
    }
    HC_RT_MAX(beat_age_max, sup_age);
    if (h & 1u) f |= HC_RT_F_EXEC_LATE;
    if (h & 2u) f |= HC_RT_F_EXEC_CFG;
    {
        unsigned int on = hc_dl_on_ign | ((unsigned int)hc_dl_on_inj << 8);
        /* Only outputs ON now or at the previous pass can have a nonzero
           age; every other age is already zero. */
        unsigned int m = on | sup_live;
        sup_live = on;
        for (b = 0u; m; b++, on >>= 1, m >>= 1) {
            if (!(m & 1u)) continue;
            if (!(on & 1u)) sup_on_ms[b] = 0u;
            else if(b>=8u && hc_dl_active_inj[b-8u]
                    && HC_DL_WIDTH.progress_ticket[b-8u]!=hc_dl_active_inj[b-8u]) {
                /* A new NONZERO active ticket follows an actual OPEN with its
                   prior output OFF. Queue tickets or a heartbeat cannot do
                   this. A ticket that drops to zero is no progress: a CLOSE
                   node whose lane bit was lost clears it without releasing
                   the port, and must not restart the ON age. */
                HC_DL_WIDTH.progress_ticket[b-8u]=hc_dl_active_inj[b-8u];
                sup_on_ms[b]=0u;
            } else {
                if(sup_on_ms[b]>255u-elapsed) sup_on_ms[b]=255u;
                else sup_on_ms[b]=(unsigned char)(sup_on_ms[b]+elapsed);
                if (sup_on_ms[b] > sup_limit[b])
                    f |= HC_RT_F_EXEC_STALL;
            }
        }
    }
    if (f) {
        /* Latched diagnostic flags must not suppress a later fault episode
           in the same key cycle. Each episode releases and inhibits anew. */
        if (hc_dl_inhibit != HC_Q_EXECUTOR) {
            if (hc_rt_exec_faults != 0xFFFFu) hc_rt_exec_faults++;
            /* Latch before cancellation unlocks between cleanup units:
               planner/CC25 may preempt this lower-priority supervisor. */
            hc_dl_inhibit = HC_Q_EXECUTOR;
            hc_deadline_cancel();          /* release now, re-arm CC25 */
        }
        hc_rt_fault |= f;
        hc_dl_inhibit = HC_Q_EXECUTOR;
        sup_age = 0u;
        sup_ok = 0u;
    } else if (hc_dl_inhibit == HC_Q_EXECUTOR) {
        if (trg_state != TRG_NO_SIGNAL) {
            sup_ok = 0u;
        } else {
            sup_ok+=elapsed;
            if(sup_ok>HC_RT_RECOVER_MS && !HC_RT.abort_pending) hc_dl_inhibit=0u;
        }
    }
    if (*(unsigned int volatile *)(HC_STK_GUARD_HI - 2u) != HC_STK_PATTERN)
        hc_rt_fault |= HC_RT_F_USTACK;   /* = hc_stack_overflowed() */
}

/* Every interrupt control register cleared before IEN goes up - the comment
   is at its call site in hcmain_me711.c main(). Moved here from hcmain (near)
   on 2026-10-13: boot-only, and NCODE needed the room. */
void far hc_irq_disable_all(void)
{
    CC0IC  = 0; CC1IC  = 0; CC2IC  = 0; CC3IC  = 0;
    CC4IC  = 0; CC5IC  = 0; CC6IC  = 0; CC7IC  = 0;
    CC8IC  = 0; CC9IC  = 0; CC10IC = 0; CC11IC = 0;
    CC12IC = 0; CC13IC = 0; CC14IC = 0; CC15IC = 0;
    CC16IC = 0; CC17IC = 0; CC18IC = 0; CC19IC = 0;
    CC20IC = 0; CC21IC = 0; CC22IC = 0; CC23IC = 0;
    CC24IC = 0; CC25IC = 0; CC26IC = 0; CC27IC = 0;
    CC28IC = 0; CC29IC = 0; CC30IC = 0; CC31IC = 0;
    T0IC   = 0; T1IC   = 0; T2IC   = 0; T3IC   = 0;
    T4IC   = 0; T5IC   = 0; T6IC   = 0; T7IC   = 0;
    T8IC   = 0;
    ADCIC  = 0; ADEIC  = 0;
    S0TIC  = 0; S0RIC  = 0; S0EIC  = 0; S0TBIC = 0;
    SSCTIC = 0; SSCRIC = 0; SSCEIC = 0;
    CRIC   = 0; PWMIC  = 0;
    XP0IC  = 0; XP1IC  = 0; XP2IC  = 0; XP3IC  = 0;
}

/* THE FIVE TARGET WORDS of the persistent reset log, every 10 ms from the
   main loop (moved here from hcmain_me711.c, 2026-10-14: NCODE). On this ECU
   they are the ASIC link's state - the S5500 is the only thing besides the
   watchdog that can reset the CPU: how far the handshake got, whether the
   ASIC ever answered, and when. */
void far hc_rst_publish(void)
{
    unsigned int t[5];

    t[0] = (unsigned int)((hc_asic_state & 0x00FFu)
                          | ((hc_asic_reinits & 0xFFu) << 8));
    t[1] = (unsigned int)((hc_asic_start_tx & 0x00FFu)
                          | ((hc_asic_start_rx & 0xFFu) << 8));
    t[2] = (unsigned int)((hc_ssc_rx_vec & 0x00FFu)
                          | ((hc_ssc_err_vec & 0xFFu) << 8));
    t[3] = (unsigned int)((hc_asic_pec_tx_end & 0x00FFu)
                          | ((hc_asic_pec_rx_end & 0xFFu) << 8));
    t[4] = hc_asic_reply_w0;
    hc_rst_progress_f(hc_tick_ms, loop_count, hc_firstvec, hc_lastvec,
                      hc_wdt_services, t);
}
