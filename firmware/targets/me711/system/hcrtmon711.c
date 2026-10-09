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

void far hc_rtmon_init(void)
{
    unsigned int volatile *p = (unsigned int volatile *)&HC_RT;
    unsigned int i;
    for (i = 0; i < sizeof(hc_rt_t) / 2u; i++) p[i] = 0u;
    HC_RT.ver = HC_RT_VER;
    rt_scan_ms = 0u;
}

/* Main loop. The two stack scans are ~1300 instructions together, so they
   run ten times a second; the mirrors are a few loads. */
void far hc_rtmon_service(unsigned int now_ms)
{
    if(HC_RT.abort_pending) hc_deadline_abort_history();
    HC_RT.rt_fault = hc_rt_fault;
    HC_RT.exec_faults = hc_rt_exec_faults;
    if ((unsigned int)(now_ms - rt_scan_ms) >= 100u) {
        rt_scan_ms = now_ms;
        (void)hc_stack_used();
        (void)hc_sysstack_used();
        HC_RT.ustk_hwm = hc_stack_hwm;
        HC_RT.sstk_hwm = hc_sysstack_hwm;
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

