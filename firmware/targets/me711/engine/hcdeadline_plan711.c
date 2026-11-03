/* Interruptible publication/queue insertion in FCODE, called by the planner.
   Mutable hot queue state remains near. Commit/edge ownership at ILVL 13. */
#include <reg167.h>
#include <intrins.h>
#include "hctarget.h"
#include "hchal.h"            /* HC_OUT_* for the abort */
#include "hcengine.h"
#include "hctrigger.h"
#include "hcsched_dry.h"
#include "hcdeadline711.h"
#include "hcdeadline_state.h"
#include "hcrtmon711.h"
#include "hcatomic.h"
#define LOCK(p)   HC_ATOMIC_ENTER(p)       /* the one convention, hcatomic.h */
#define UNLOCK(p) HC_ATOMIC_EXIT(p)
#define INC(x) do { if ((x)!=0xFFFFu) (x)++; } while(0)
#define D HC_DL_DIAG
/* Current injector ownership is separate from its one pending next pulse.
   On-chip XRAM remains a bounded near access in the urgent edge path. */
unsigned int hc_dl_active_inj[8];

void HC_COLD hc_drysched_test_set_epoch(unsigned int hi, unsigned int lo)
{
    hc_plan_epoch = ((unsigned long)hi << 16) | (unsigned long)lo;
}

unsigned int HC_COLD hc_drysched_test_epoch_hi(void)
{
    return (unsigned int)(hc_plan_epoch >> 16);
}

unsigned int HC_COLD hc_drysched_test_epoch_lo(void)
{
    return (unsigned int)(hc_plan_epoch & 0xFFFFuL);
}



void far hc_plan_count_tooth_f(unsigned int angle)
{
    unsigned int step = hc_plan_advance_epoch_f(angle);
    if (step == 0u) hc_plan_acc_bad = 1u;
    hc_plan_acc = (unsigned int)(hc_plan_acc + step);
}

/* Publication can be preempted by several captures. Count intermediate
   teeth between event units while retaining the newest capture for the next
   full walk. The current walk keeps its sealed angle/stamp context. */
void far hc_plan_collect_f(void)
{
    unsigned char p,next,work=0u;
    unsigned int angle;
    while(work++<TGT_PLAN_CAP_N-1u && hc_plan_generation==hc_dl_generation) {
        p=hc_plan_cap_tail;next=(unsigned char)((p+1u)&(TGT_PLAN_CAP_N-1u));
        if(p==hc_plan_cap_head || next==hc_plan_cap_head) break;
        angle=hc_plan_cap_angle[p];
        hc_plan_cap_tail=next;
        hc_plan_count_tooth_f(angle);
    }
}

/* COINCIDING ANCHORS ARE ONE EVENT (2026-10-24, geometry_refresh() in
   hcsched_dry.c, cold: once per plan rebuild). Wasted COP and
   semi-sequential place a cylinder and its partner 360 degrees on at the SAME
   angle; as two anchors they cost two walks and two publications, which the
   queue then merged by searching for the identical pulse - and the two
   sparks stayed two nodes. One entry with both outputs' bits is the same
   electrical event. A sequential twin (HC_SLOT_TWIN) is never merged: it is
   dropped on its own once the cycle is known (the queue's exact-pulse merge
   still joins it with the coinciding primary until then). The merged entry
   keeps the slot of the cylinder whose own stroke it is (not
   HC_SLOT_REPEAT): its knock retard and telemetry. */
static unsigned char slot_bits(unsigned char s)
{
    s = (unsigned char)(s & HC_SLOT_MASK & ~HC_SLOT_REPEAT);
    if (s == 0u) return 255u;                 /* HC_PLAN_SLOT_ALL */
    return (unsigned char)((s <= 8u) ? (1u << (s - 1u)) : 0u);
}

void far hc_plan_merge_f(unsigned int *ang, unsigned char *slot,
                         unsigned char *msk, unsigned char *n)
{
    unsigned char i, j;
    for (i = 0u; i < *n; i++) msk[i] = slot_bits(slot[i]);
    for (i = 0u; (unsigned char)(i + 1u) < *n; ) {
        if (ang[i + 1u] != ang[i]) { i++; continue; }
        if ((slot[i] | slot[i + 1u]) & HC_SLOT_TWIN) {
            hc_plan_coincide = 1u; i++; continue;
        }
        msk[i] |= msk[i + 1u];
        if (slot[i] & HC_SLOT_REPEAT) slot[i] = slot[i + 1u];
        for (j = (unsigned char)(i + 1u); (unsigned char)(j + 1u) < *n; j++) {
            ang[j] = ang[j + 1u]; slot[j] = slot[j + 1u]; msk[j] = msk[j + 1u];
        }
        (*n)--;
    }
    for (i = 0u; i < *n; i++) slot[i] = (unsigned char)(slot[i] & ~HC_SLOT_REPEAT);
}

/* Paired/batch/fallback outputs may fire more than once per engine cycle.
   Clip each injector against its shortest configured interval - the
   shortest distance between two anchors that drive it - not an assumed 720
   degree period. Anchors are inside the cycle already. */
void far hc_plan_spans_f(unsigned char n)
{
    unsigned char i, j, k, ob;
    unsigned int span, a, b, delta;
    for (i = 0u; i < 8u; i++) {
        ob = (unsigned char)(1u << i);
        span = hc_plan_cycle;
        for (j = 0u; j < n; j++) if (hc_plan_inj_masks[j] & ob) {
            for (k = 0u; k < n; k++) if (k != j && (hc_plan_inj_masks[k] & ob)) {
                a = hc_plan_inj_anchors[k]; b = hc_plan_inj_anchors[j];
                delta = (a >= b) ? (unsigned int)(a - b)
                                 : (unsigned int)(a + hc_plan_cycle - b);
                if (delta && delta < span) span = delta;
            }
        }
        HC_DL_WIDTH.next_angle[i] = span;
    }
}

/* Capture ticks -> us with two native divisions and bounded quotients:
   floor(0.8 * ticks) at 1.25 MHz; floor(4/3 * ticks) = ticks + floor(ticks/3)
   at 0.75 MHz (the 2.7T - until 2026-10-25 it used the 0.8, so every width
   this returns read 40 % short there). */
unsigned long far hc_deadline_ticks_us_f(unsigned long w)
{
    unsigned int hi,qh,ql;
#if TGT_TICKS_PER_MS_X10 == 12500UL
    w+=4uL;hi=(unsigned int)(w>>16);qh=hi/5u;
    ql=(unsigned int)((((unsigned long)(unsigned int)(hi-qh*5u))<<16
                      |(unsigned int)w)/(unsigned int)5u);
    return w-4uL-(((unsigned long)qh<<16)|ql);
#elif TGT_TICKS_PER_MS_X10 == 7500UL
    hi=(unsigned int)(w>>16);qh=hi/3u;
    ql=(unsigned int)((((unsigned long)(unsigned int)(hi-qh*3u))<<16
                      |(unsigned int)w)/(unsigned int)3u);
    return w+(((unsigned long)qh<<16)|ql);
#elif TGT_TICKS_PER_MS_X10 == 10000UL
    /* 32 MHz BFB: 1.000 MHz capture clock, one tick is one us */
    hi=0u;qh=0u;ql=0u;
    return w;
#else
#error "hc_deadline_ticks_us_f: no conversion for this capture clock"
#endif
}

/* Live advance/dwell/phase changes apply only to an uncommitted event with
   enough publication lead. A new offset may not jump the next cursor behind
   the crank or inside its commit horizon. Keep its prior phase for this
   event, then apply the change to a later one. No deadline is retimed. */
unsigned int HC_COLD hc_deadline_plan_offset(unsigned int kind, unsigned int proposed)
{
    unsigned int huge *p=(unsigned int huge *)(TGT_EXTRAM_BASE+TGT_RAM_PLANOFF);
    unsigned int d,anchor,cycle;
    if(p[kind] != proposed) {
        /* An EOI change cannot move the next start across an owned pulse. */
        if(kind==2u) {
            if(hc_dl_reserved_inj & hc_plan_inj_masks[hc_plan_cursors[kind]]) return p[kind];
        }
        cycle=hc_plan_cycle;
        anchor=(kind<2u?hc_plan_ign_anchors:hc_plan_inj_anchors)[hc_plan_cursors[kind]];
        /* All angles are within a <=7200-count cycle, so this signed
           intermediate is bounded to [-7200,14400] without a division. */
        d=(unsigned int)(anchor+cycle-hc_plan_angle-proposed);
        if((int)d<0) d+=cycle;
        else if(d>=cycle) d-=cycle;
        if(d<hc_plan_ahead || d>=(cycle>>1)) return p[kind];
        p[kind]=proposed;
    }
    return proposed;
}

/* One channel per lock, shared by fuel cut and catastrophic cancellation. */
static void ended(unsigned char b, unsigned long n, unsigned int flags)
{
    unsigned int ps;
    unsigned long width;
    LOCK(ps);
    width = hc_deadline_ticks_us_f(n - D.inj[b].on_time);
    HC_DL_WIDTH.delivered[b] = width;
    D.inj[b].delivered_us = width > 65535uL ? 65535u : (unsigned int)width;
    D.inj[b].legal_time = n + HC_DL_OFF_TICKS;
    D.inj[b].next_legal = (unsigned int)(n + HC_DL_OFF_TICKS);
    D.inj[b].flags = flags;
    D.cooldown |= (unsigned int)(1u << b);
    UNLOCK(ps);
}

void HC_COLD hc_deadline_bench_stop(void)
{
    unsigned int ps;
    LOCK(ps);
    if (D.bench_type) hc_deadline_bench_port_f(D.bench_type, D.bench_mask, 0u);
    D.bench_type = 0u; D.bench_done = 1u;
    UNLOCK(ps);
}

void HC_COLD hc_deadline_fuel_cut(void)
{
    unsigned int ps;
    unsigned char b, on;
    unsigned long n;
    LOCK(ps);
    on = hc_dl_on_inj;
    hc_hal_deadline_ports_f(HC_OUT_INJ1, 255u, 255u, 0u);
    n = hc_deadline_now_f();
    hc_dl_owner[8] = hc_dl_owner[9] = hc_dl_owner[10] = hc_dl_owner[11] = 0u;
    hc_dl_owner[12] = hc_dl_owner[13] = hc_dl_owner[14] = hc_dl_owner[15] = 0u;
    hc_dl_reserved_inj = hc_dl_on_inj = 0u; hc_prime_on = 0u;
    for(b=0u;b<8u;b++) hc_dl_active_inj[b]=0u;
    UNLOCK(ps);
    /* Fuel permission was removed by the caller before this release.
       CC25 can finish pending OPEN history between these units; ignition
       keeps its own deadlines throughout the injection-only cut. */
    for (b = 0; on; b++, on >>= 1) if (on & 1u) ended(b, n, 12u);
}

/* Output release and queue-head invalidation precede these cold clears.
   No planner or ON command can run until cleanup completes. */
static void clear_slots(void)
{
    unsigned char i;
    for(i=0u;i<HC_DL_N;i++) hc_dl_q_type[i]=0u;
    for(i=0u;i<16u;i++) hc_dl_owner[i]=0u;
    for(i=0u;i<8u;i++) hc_dl_active_inj[i]=0u;
}

void HC_COLD hc_deadline_cancel(void)
{
    unsigned int ps;
    unsigned char i;
    unsigned long n;
    LOCK(ps);
    /* Keep publication refused until slot/owner cleanup is complete. A
       nested supervisor fault may strengthen this to EXECUTOR; never undo
       that latch when an ordinary abort resumes. */
    if (hc_dl_inhibit != HC_Q_EXECUTOR) hc_dl_inhibit = HC_Q_WITHDRAWN;
    /* Terminal generation exhaustion prevents suspended planner ABA. */
    if (hc_dl_generation != 0xFFFFu) hc_dl_generation++;
    hc_dl_revision++;
    D.cancelled = (hc_dl_count > (unsigned int)(0xFFFFu - D.cancelled))
        ? 0xFFFFu : (unsigned int)(D.cancelled + hc_dl_count);
    dry_sched_cancelled = D.cancelled;
    hc_dl_q_head = HC_DL_NONE; hc_dl_count = 0u; dry_sched_queued = 0u;
    hc_dl_done_head = HC_DL_NONE; hc_dl_corrupt = 0u;
    hc_dl_done_channel = hc_dl_cooldown_channel = 0u;
    hc_dl_stale_n = 0u;
    hc_dl_reserved_ign = hc_dl_reserved_inj = hc_dl_on_ign = hc_dl_on_inj = 0u;
    hc_prime_on = 0u;
    hc_hal_deadline_ports_f(HC_OUT_IGN1, 255u, 255u, 0u);
    hc_hal_deadline_ports_f(HC_OUT_INJ1, 255u, 255u, 0u);
    n = hc_deadline_now_f();
    UNLOCK(ps);
    hc_deadline_bench_stop();
    D.ovd_one = D.ovd_two = 0u;
    /* A lower-priority normal abort runs after pending CC25 history drains.
       Catastrophic failure discards unfinished history rather than trusting
       the damaged queue. Valid ON timestamps still mark truncated pulses. */
    if(hc_dl_inhibit == HC_Q_EXECUTOR) {
        /* Release and invalidate immediately; diagnostic history waits for
           main so a fault cannot turn the tick into a long engine blocker. */
        HC_RT.abort_time = n;
        HC_RT.abort_pending = 1u;
    } else {
        clear_slots();
        for(i=0u;i<8u;i++) if(D.inj[i].flags&1u) ended(i,n,12u);
    }
    LOCK(ps);
    CCM6 = (unsigned int)((CCM6 & 0xFF0Fu) | 0x0040u);
    hc_deadline_arm_f();
    if (hc_dl_inhibit != HC_Q_EXECUTOR) hc_dl_inhibit = 0u;
    UNLOCK(ps);
}

void HC_COLD hc_deadline_abort_history(void)
{
    unsigned char i;
    unsigned int ps;
    unsigned long n;
    LOCK(ps);n=HC_RT.abort_time;UNLOCK(ps);
    clear_slots();
    for(i=0u;i<8u;i++) if(D.inj[i].flags&1u) ended(i,n,12u);
    HC_RT.abort_pending=0u;
}

/* The runtime supervisor's view of the executor (hcsafety.c, 1 ms tick ISR -
   a different interrupt source, so it still runs when CC25 does not).
   Bit 0: the queue head is overdue by more than HC_DL_OVERDUE - CC25 is not
   being serviced. Bit 1: CC25 is not configured to run (mode, IE, level) -
   the class of fault that would leave a coil or injector on while every
   other part of the firmware, the watchdog service included, carries on. */
/* 2.5 ms in THIS board's ticks (2026-10-26: it was 3125uL, the 1.25 MHz count,
   so the 2.7T found a stalled executor 4.2 ms late, holding coils 7 ms -
   me711_runtime_fault_proof X2); dispatch latency is < 0.2 ms */
#define HC_DL_OVERDUE ((unsigned long)US_TO_TICKS(2500u))
unsigned char HC_COLD hc_deadline_health(void)
{
    unsigned int ps;
    unsigned char h = 0u;
    long delta;
    LOCK(ps);
    if ((hc_dl_corrupt & 1u) || (hc_dl_q_head != HC_DL_NONE && hc_dl_q_head >= HC_DL_N)
        || (hc_dl_q_head == HC_DL_NONE && hc_dl_count)) h |= 2u;
    if (hc_dl_corrupt & 2u) h |= 1u;
    if (hc_dl_q_head < HC_DL_N) {
        delta=(long)(hc_deadline_now_f()-hc_dl_q_time[hc_dl_q_head]);
        if(delta>(long)HC_DL_OVERDUE) h|=1u;
        if(delta<-(long)HC_DL_MAX_AHEAD) h|=2u;
    }
    if ((CC25IC & 0x7Fu) != HC_IC(TGT_ILVL_DEADLINE, TGT_GLVL_DEADLINE)
        || (CCM6 & 0x00F0u) != 0x0040u)
        h |= 2u;
    UNLOCK(ps);
    return h;
}

unsigned char HC_COLD hc_deadline_flash_admit(unsigned int guard_ticks)
{
    unsigned int ps;
    unsigned char ok;
    unsigned long n;
    LOCK(ps); n=hc_deadline_now_f();
    ok=(unsigned char)(!hc_dl_corrupt && hc_dl_done_head==HC_DL_NONE
        && (hc_dl_q_head==HC_DL_NONE || (hc_dl_q_head<HC_DL_N
        && (long)(hc_dl_q_time[hc_dl_q_head]-n)>(long)guard_ticks)));
    UNLOCK(ps);return ok;
}
static unsigned char packed(unsigned char type,unsigned char mask)
{
    unsigned char b=1u;
    /* EVERY LANE (batch injection, an all-coil group): CC25 takes the
       routed lanes from the route table itself. Until 2026-10-24 only a board
       with all eight lanes routed got this tag; the 2.7T's six injectors
       went through the per-lane loop, ~600 instructions at ILVL 13. */
    if(mask==255u && type<=HC_DL_MAXDWELL) return (unsigned char)(type|0xf0u);
    if(mask && !(mask&(mask-1u))) {
        while(!(mask&1u)) { mask>>=1; b++; }
        return (unsigned char)(type|(b<<4));
    }
    return type;
}
unsigned long HC_COLD hc_deadline_inj_request(unsigned char mask,unsigned int fuel,unsigned int dead,unsigned long period)
{
    /* us -> capture ticks: x 1.25 (Porsche), x 0.75 (2.7T). Until 2026-10-25
       the 2.7T used the 1.25 too: every injector pulse 1.67 x too long,
       found by me711_sequential_proof made board-aware. */
#if TGT_TICKS_PER_MS_X10 == 12500UL
    unsigned long requested=(unsigned long)fuel+dead,duration=requested+(requested>>2);
#elif TGT_TICKS_PER_MS_X10 == 7500UL
    unsigned long requested=(unsigned long)fuel+dead,duration=requested-(requested>>2);
#elif TGT_TICKS_PER_MS_X10 == 10000UL
    unsigned long requested=(unsigned long)fuel+dead,duration=requested;   /* 1.000 MHz */
#else
#error "hc_deadline_inj_request: no conversion for this capture clock"
#endif
    unsigned char bits,clipped;
    unsigned int ps,req16,fl;
    hc_dl_inj_t huge *q=&D.inj[0];
    if(period<=HC_DL_OFF_TICKS*2u) {
        clipped=(unsigned char)(duration!=0uL);duration=0uL;
    } else {
        period-=HC_DL_OFF_TICKS*2u;
        clipped=(unsigned char)(duration>period);
        if(clipped) duration=period;
    }
    /* computed once, written per lane through one pointer (2026-10-24:
       the indexed huge accesses were ~120 instructions a lane) */
    req16=requested>65535uL?65535u:(unsigned int)requested;
    fl=(unsigned int)((clipped?2u:0u)|(requested>65535uL?16u:0u));
    for(bits=mask;bits;q++,bits>>=1) if(bits&1u) {
        LOCK(ps);
        q->fuel_us=fuel; q->dead_us=dead; q->requested_us=req16;
        q->flags=(unsigned int)((q->flags&13u)|fl);
        UNLOCK(ps);
    }
    if(clipped) INC(D.clipped);
    return duration;
}
unsigned int HC_COLD hc_deadline_inj_admitted(unsigned char mask,unsigned int id,unsigned int generation,unsigned long duration)
{
    unsigned char b,bits;
    unsigned int ps,scheduled;
    unsigned long width=hc_deadline_ticks_us_f(duration);
    hc_dl_inj_t huge *q=&D.inj[0];
    scheduled=width>65535uL?65535u:(unsigned int)width;
    for(b=0u,bits=mask;bits;b++,q++,bits>>=1) if(bits&1u) {
        LOCK(ps);
        if(id && generation==hc_dl_generation) {
            q->scheduled_us=scheduled;
            HC_DL_WIDTH.accepted[b]=width; q->flags&=(unsigned int)~32u;
            HC_DL_WIDTH.accepted_ticket[b]=id;
        } else q->flags|=32u;
        UNLOCK(ps);
    }
    return id && generation==hc_dl_generation ? scheduled : 0u;
}
static void diag_put(unsigned int o,unsigned int v)
{
    unsigned char huge *p=(unsigned char huge *)(TGT_EXTRAM_BASE+TGT_RAM_OCH2+(unsigned int)(o-1024u));
    p[0]=(unsigned char)(v>>8); p[1]=(unsigned char)v;
}
void HC_COLD hc_deadline_publish_diag(void)
{
    unsigned int i,b;
    unsigned int huge *p=(unsigned int huge *)&D;
    for(i=0;i<19u;i++) diag_put((unsigned int)(1248u+2u*i),p[i]);
    for(b=0;b<8u;b++) {
        p=(unsigned int huge *)&D.inj[b];
        for(i=0;i<6u;i++) diag_put((unsigned int)(1286u+14u*b+2u*i),p[i]);
        diag_put((unsigned int)(1298u+14u*b),D.inj[b].flags);
    }
    diag_put(1450u,hc_dl_generation);
    diag_put(1452u,(unsigned int)(hc_dl_on_ign|((unsigned int)hc_dl_on_inj<<8)));
    diag_put(1454u,(unsigned int)(hc_dl_reserved_ign|((unsigned int)hc_dl_reserved_inj<<8)));
    diag_put(1456u,hc_dl_count);
    /* Full widths have explicit high words: no duration cap for telemetry. */
    for(b=0;b<8u;b++) {
        unsigned int ps;
        unsigned long a,d;
        LOCK(ps); a=HC_DL_WIDTH.accepted[b];d=HC_DL_WIDTH.delivered[b];UNLOCK(ps);
        diag_put((unsigned int)(1458u+8u*b),(unsigned int)(a>>16));
        diag_put((unsigned int)(1460u+8u*b),(unsigned int)a);
        diag_put((unsigned int)(1462u+8u*b),(unsigned int)(d>>16));
        diag_put((unsigned int)(1464u+8u*b),(unsigned int)d);
    }
}
/* Queue order: earlier time first; OFF before ON at equal time; FIFO within
   the same edge class. INLINE (2026-10-24): it was a far call per queue node,
   ~30 instructions a node and a quarter of the planner level on the 2.7T at
   24 MHz; the new event's class is now computed once per walk. `d` is the
   caller's long scratch. Same order as the function it replaces. */
#define DL_ON_CLASS(t) \
    (((((t) & 15u) == HC_DL_SPARK) || (((t) & 15u) >= HC_DL_CLOSE)) ? 0u : 1u)
#define DL_BEFORE(d, a, acls, b, bt) \
    (((d) = (long)((a) - (b))) != 0L ? ((d) < 0L) : ((acls) < DL_ON_CLASS(bt)))

/* Task only. Prepare payload/position unlocked, then commit one pointer pair.
   Crank cancellation/compare dispatch increments hc_dl_revision before returning.
   Slots remain invisible (type=0) until the successful critical commit. */
static unsigned char insert(unsigned int generation, unsigned long when,
    unsigned char type, unsigned char mask, unsigned int id)
{
    unsigned char retry, i, p, prev, walked;
    unsigned char tag=packed(type,mask), cls=DL_ON_CLASS(type);
    unsigned int rev, ps;
    long d;
    for (retry = 0; retry < 4u; retry++) {
        rev = hc_dl_revision;
        if (generation != hc_dl_generation || generation == 0xFFFFu) return 0u;
        for (i = 0; i < HC_DL_N && hc_dl_q_type[i] != 0u; i++) { }
        if (i == HC_DL_N) return 0u;
        prev = HC_DL_NONE;
        p = hc_dl_q_head;
        walked = 0u;
        while (p < HC_DL_N && walked++ < HC_DL_N
               && !DL_BEFORE(d, when, cls, hc_dl_q_time[p], hc_dl_q_type[p])) {
            prev = p;
            p = hc_dl_q_next[p];
            if (rev != hc_dl_revision) break;
        }
        if (p != HC_DL_NONE && p >= HC_DL_N) return 0u;
        LOCK(ps);
        if (walked <= HC_DL_N && rev == hc_dl_revision && generation == hc_dl_generation) {
            hc_dl_q_time[i] = when; hc_dl_q_id[i] = id; hc_dl_q_mask[i] = mask; hc_dl_q_next[i] = p;
            hc_dl_q_type[i] = tag;
            if (prev == HC_DL_NONE) hc_dl_q_head = i; else hc_dl_q_next[prev] = i;
            hc_dl_count++; hc_dl_revision++;
            dry_sched_queued = hc_dl_count;
            HC_RT_MAX(dlq_hwm, hc_dl_count);
            INC(D.armed);
            hc_deadline_arm_f();
            UNLOCK(ps);
            return 1u;
        }
        UNLOCK(ps);
    }
    return 0u;
}

/* Publish a complete pulse in one revision-checked commit. OFF ordering is
   established before ON becomes visible; no partial pair or second rearm.
   The task walks the existing list once. Critical work is constant size. */
static unsigned char insert_pair(unsigned int generation, unsigned long start,
    unsigned long end, unsigned char type, unsigned char mask, unsigned int id)
{
    unsigned char retry, i, j, p, prev, sp, sn, ep, en, seen, walked;
    unsigned char ending = (unsigned char)(type == HC_DL_DWELL ? HC_DL_MAXDWELL : HC_DL_CLOSE);
    unsigned char start_tag=packed(type,mask),end_tag=packed(ending,mask);
    unsigned char scls=DL_ON_CLASS(type), ecls=DL_ON_CLASS(ending);
    unsigned int rev, ps;
    long d;
    for (retry = 0; retry < 4u; retry++) {
        rev = hc_dl_revision;
        if (generation != hc_dl_generation || generation == 0xFFFFu) return 0u;
        for (i = 0; i < HC_DL_N && hc_dl_q_type[i]; i++) { }
        for (j = (unsigned char)(i + 1u); j < HC_DL_N && hc_dl_q_type[j]; j++) { }
        if (j >= HC_DL_N) return 0u;
        p = hc_dl_q_head; prev = HC_DL_NONE; seen = walked = 0u;
        while (p < HC_DL_N && walked++ < HC_DL_N) {
            /* Before the start's place is found the end cannot come first:
               end > start (duration > 0), so a node the start does not
               precede the end does not precede either - one test per node
               there, not two (2026-10-24). */
            if (!seen) {
                if (DL_BEFORE(d, start, scls, hc_dl_q_time[p], hc_dl_q_type[p])) {
                    sp = prev; sn = p; seen = 1u;
                    if (DL_BEFORE(d, end, ecls, hc_dl_q_time[p], hc_dl_q_type[p])) break;
                }
            } else if (DL_BEFORE(d, end, ecls, hc_dl_q_time[p], hc_dl_q_type[p])) break;
            prev = p; p = hc_dl_q_next[p];
            if (rev != hc_dl_revision) break;
        }
        if (p != HC_DL_NONE && p >= HC_DL_N) return 0u;
        ep = prev; en = p;
        if (!seen) { sp = ep; sn = en; }
        /* Invisible slot payloads can be prepared with crank IRQ enabled. */
        hc_dl_q_time[i] = start; hc_dl_q_id[i] = id; hc_dl_q_mask[i] = mask;
        hc_dl_q_time[j] = end; hc_dl_q_id[j] = id; hc_dl_q_mask[j] = mask;
        LOCK(ps);
        if (walked <= HC_DL_N && rev == hc_dl_revision && generation == hc_dl_generation) {
            hc_dl_q_next[j] = en;
            hc_dl_q_next[i] = (sp == ep && sn == en) ? j : sn;
            hc_dl_q_type[j] = end_tag; hc_dl_q_type[i] = start_tag;
            if (ep == HC_DL_NONE) hc_dl_q_head = j; else hc_dl_q_next[ep] = j;
            if (sp == HC_DL_NONE) hc_dl_q_head = i; else hc_dl_q_next[sp] = i;
            hc_dl_count += 2u; hc_dl_revision++;
            dry_sched_queued = hc_dl_count; INC(D.armed); INC(D.armed);
            HC_RT_MAX(dlq_hwm, hc_dl_count);
            hc_deadline_arm_f(); UNLOCK(ps); return 1u;
        }
        UNLOCK(ps);
    }
    return 0u;
}

/* Exact simultaneous pulses can share a ticket and their reserved ending.
   Search unlocked; commit two masks/owners only after revision validation.
   No rounding of deadlines or durations and no merging active pulses. */
static unsigned int merge_pair(unsigned int generation, unsigned long start,
    unsigned long end, unsigned char type, unsigned char mask)
{
    unsigned char p, first = HC_DL_NONE, last = HC_DL_NONE, walked = 0u, b,bits;
    unsigned char ending = type == HC_DL_DWELL ? HC_DL_MAXDWELL : HC_DL_CLOSE;
    unsigned int rev = hc_dl_revision, ps, id;
    for (p = hc_dl_q_head; p < HC_DL_N && walked++ < HC_DL_N; p = hc_dl_q_next[p]) {
        /* time-ordered: past the pulse's end nothing can match (2026-10-24) */
        if ((long)(hc_dl_q_time[p] - end) > 0L) break;
        if ((hc_dl_q_type[p]&15u) == type && hc_dl_q_time[p] == start) first = p;
        if ((hc_dl_q_type[p]&15u) == ending && hc_dl_q_time[p] == end) {
            if (first != HC_DL_NONE && hc_dl_q_id[p] == hc_dl_q_id[first]) { last = p; break; }
        }
        if (rev != hc_dl_revision) return 0u;
    }
    if (last == HC_DL_NONE) return 0u;
    LOCK(ps);
    if (rev != hc_dl_revision || generation != hc_dl_generation) { UNLOCK(ps); return 0u; }
    id = hc_dl_q_id[first];
    hc_dl_q_mask[first] |= mask; hc_dl_q_mask[last] |= mask;
    hc_dl_q_type[first]=type;hc_dl_q_type[last]=ending; /* group owns several channels */
    for (b=0u,bits=mask;bits;b++,bits>>=1) if(bits&1u) hc_dl_owner[(type == HC_DL_DWELL ? 0u : 8u) + b] = id;
    hc_dl_revision++; INC(D.armed); INC(D.armed);
    UNLOCK(ps); return id;
}

/* A following pulse may be planned while the current pulse is still ON.
   Its current CLOSE keeps its ticket. No second pending OPEN or overlap is
   admitted. Walks are interruptible, with bounded revision retries. */
static unsigned char future_fits(unsigned char mask, unsigned long *when)
{
    unsigned int attempt,p,walked,b,bits,lane,seen;
    unsigned int rev;
    unsigned long at,end;
    for(attempt=0u;attempt<4u;attempt++) {
        rev=hc_dl_revision;seen=0u;at=*when;
        for(p=hc_dl_q_head,walked=0u;p<HC_DL_N && walked++<HC_DL_N;p=hc_dl_q_next[p]) {
            bits=(unsigned char)(hc_dl_q_mask[p]&mask);
            if((hc_dl_q_type[p]&15u)==HC_DL_OPEN && bits) return 0u;
            if(bits && (hc_dl_q_type[p]&15u)==HC_DL_CLOSE) {
                end=hc_dl_q_time[p]+HC_DL_OFF_TICKS*2u;
                for(b=0u,lane=1u;bits;bits>>=1,b++,lane<<=1)
                    if((bits&1u) && hc_dl_q_id[p]==hc_dl_owner[8u+b]) {
                        seen|=lane;
                        if((long)(end-at)>0) at=end;
                    }
            }
        }
        if(rev==hc_dl_revision) {
            /* CLOSE may finish during this interruptible walk. A channel
               whose reservation is gone needs no surviving CLOSE node. */
            seen|=(unsigned char)(mask&~hc_dl_reserved_inj);
            if((long)(at-*when)>(long)HC_PLAN_HORIZON_TICKS) return 0u;
            if(seen==mask) *when=at;
            return seen;
        }
    }
    return 0u;
}

unsigned int hc_deadline_publish(unsigned int generation, unsigned int stamp,
    unsigned long ahead, unsigned char type, unsigned char mask,
    unsigned long duration)
{
    unsigned long when, n,requested;
    unsigned int ps, elapsed, id = 0u;
    unsigned char fits,i,bits, opening = (unsigned char)(type == HC_DL_DWELL || type == HC_DL_OPEN);
    if (type < 1u || type > 4u || mask == 0u) return 0u;
    INC(D.planned[type - 1u]);
    /* The executor supervisor's latch (hcrtmon711.c): nothing new is
       admitted until the engine has stopped. A planner quiesce does not
       refuse here - it refuses only the stale entries (hcdeadline711.c). */
    if (hc_dl_inhibit) { D.reason = HC_DL_INHIBIT; return 0u; }
    if(type==HC_DL_OPEN) INC(D.planned[HC_DL_CLOSE-1u]); /* paired ending intention */
    hc_hal_deadline_prepare_f(); /* task-only route resolution/publication */
    LOCK(ps);
    n = hc_deadline_now_f();
    /* The extended clock and captured stamp share T1: identical pulse
       times remain identical through queue publication and exact merging. */
    elapsed = (unsigned int)(hc_dl_clock_last - stamp);
    when = n + ahead - elapsed;
    if (generation != hc_dl_generation || generation == 0xFFFFu) {
        D.reason = HC_DL_STALE; UNLOCK(ps); return 0u;
    }
    if (ahead > HC_DL_MAX_AHEAD || elapsed >= 32768u
        || (opening && duration > HC_DL_MAX_AHEAD)) {
        D.reason = HC_DL_HORIZON; INC(D.rejected); UNLOCK(ps); return 0u;
    }
    if (opening && ((type == HC_DL_DWELL ? hc_dl_reserved_ign : hc_dl_reserved_inj) & mask)) {
        UNLOCK(ps);requested=when;
        fits=type==HC_DL_OPEN?future_fits(mask,&when):0u;
        if(fits==mask && when!=requested) {
            /* Real overlap during acceleration shifts the uncommitted start,
               never its predecessor's CLOSE. Each flag update is bounded. */
            INC(D.clipped);
            {
                hc_dl_inj_t huge *q=&D.inj[0];
                for(bits=mask;bits;q++,bits>>=1) if(bits&1u) {
                    LOCK(ps);q->flags|=64u;UNLOCK(ps);
                }
            }
        }
        LOCK(ps);n=hc_deadline_now_f();
        if(fits!=mask || generation!=hc_dl_generation || hc_dl_inhibit) {
            D.reason=HC_DL_OVERLAP;INC(D.suppressed);UNLOCK(ps);return 0u;
        }
    }
    if (opening && duration == 0uL) { UNLOCK(ps); return 0u; }
    if (opening && (long)(when - n) < -125L) {
        D.reason = HC_DL_LATE; INC(D.suppressed); UNLOCK(ps); return 0u;
    }
    if (type == HC_DL_OPEN) {
        /* A lane whose last CLOSE already executed keeps its 100 us OFF
           reserve: the start moves to the latest legal time - the same
           policy as future_fits() while that CLOSE is still queued - and is
           refused only beyond the publication horizon (2026-10-25: it was
           refused outright, one lost injection in a high-duty transient). */
        hc_dl_inj_t huge *q=&D.inj[0];
        requested=when;
        for (bits=mask;bits;q++,bits>>=1) if ((bits&1u)
            && (q->flags & 8u) && (long)(q->legal_time - requested) > 0)
            requested=q->legal_time;
        if (requested != when) {
            if ((long)(requested - when) > (long)HC_PLAN_HORIZON_TICKS) {
                D.reason = HC_DL_OVERLAP; INC(D.suppressed); UNLOCK(ps); return 0u;
            }
            when=requested; INC(D.clipped);
        }
    }
    if (opening) {
        hc_dl_token++; if (hc_dl_token == 0u) hc_dl_token++;
        id = hc_dl_token;
        if (type == HC_DL_DWELL) hc_dl_reserved_ign |= mask; else hc_dl_reserved_inj |= mask;
        {
            unsigned int *o = &hc_dl_owner[type == HC_DL_DWELL ? 0u : 8u];
            for (bits=mask;bits;o++,bits>>=1) if(bits&1u) *o = id;
        }
    } else {
        /* OFF carries its own publication identity, never a live-hc_dl_owner lookup. */
        id = (unsigned int)duration;
        if (id == 0u) { UNLOCK(ps); return 0u; }
    }
    UNLOCK(ps);
    if (opening) {
        /* a plan with all anchors distinct never publishes one pulse twice
           (hcsched_dry.c hc_plan_coincide) */
        unsigned int merged = hc_plan_coincide
            ? merge_pair(generation, when, when + duration, type, mask) : 0u;
        if (merged) { id = merged; goto admitted; }
        if (!insert_pair(generation, when, when + duration, type, mask, id)) goto refused;
    } else if (!insert(generation, when, type, mask, id)) goto refused;
admitted:
    D.requested_tick = (unsigned int)when;
    D.reason = HC_DL_OK;
    return id;
refused:
    LOCK(ps);
    if (generation == hc_dl_generation && opening) {
        if (type == HC_DL_DWELL) hc_dl_reserved_ign &= (unsigned char)~mask;
        else hc_dl_reserved_inj=(unsigned char)((hc_dl_reserved_inj&~mask)|(hc_dl_on_inj&mask));
        for (i=0,bits=mask;bits;i++,bits>>=1) if(bits&1u)
            hc_dl_owner[(type==HC_DL_DWELL?0u:8u)+i]=type==HC_DL_DWELL?0u:hc_dl_active_inj[i];
    }
    D.reason = HC_DL_FULL; INC(D.rejected);
    UNLOCK(ps);
    return 0u;
}


/* ===================== COLD PLANNER ROUTINES, FAR (2026-10-24) ==========
   Moved verbatim from hcsched_dry.c to give NCODE room for the 2.7T's hot
   path: they run at a resync, a cam phase decision, a configuration change
   or once in ~2 hours (the epoch rebase), always on the planner level, and
   read the planner's state through the names hcsched_dry.c uses. */
#define PLAN_N 16u
#define EV_NONE 0u
#define K_DWELL   0u
#define K_SPARK   1u
#define K_INJ_ON  2u
#define K_INJ_OFF 3u
#define PLANBUF     ((unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_SCHEDPLAN))
#define plan_epoch  ((unsigned long huge *)PLANBUF)
#define plan_type   (PLANBUF + 4u * PLAN_N)
#define plan_slot   (PLANBUF + 5u * PLAN_N)
#define SCHED_LOCK(p)   HC_ATOMIC_ENTER(p)
#define SCHED_UNLOCK(p) HC_ATOMIC_EXIT(p)
#define DRY_EPOCH_WRAP  (7200uL * 500000uL)
#define angle_epoch   hc_plan_epoch
#define angle_valid   hc_plan_angle_valid
#define ig_n          hc_plan_ig_n
#define in_n          hc_plan_in_n
#define ig_mask       hc_plan_ign_masks
#define cursors_valid hc_plan_cursors_valid
#define epoch_rebase  hc_plan_epoch_rebase_f
#define seed_cursors  hc_plan_seed_f
#define remap_cursors_360 hc_plan_remap360_f
#define SUB_FAST(dst, a, b, cyc)                                        \
    do {                                                                \
        unsigned int _a = (a), _b = (b);                                \
        if (_a >= (cyc)) _a = (unsigned int)((cyc) - 1u);                \
        if (_b >= (cyc)) _b = (unsigned int)((cyc) - 1u);                \
        (dst) = (_a >= _b) ? (unsigned int)(_a - _b)                     \
                           : (unsigned int)(_a + (cyc) - _b);            \
    } while (0)

void far epoch_rebase(void)
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

unsigned int HC_COLD hc_drysched_schedule_after(unsigned int angle_x10,
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

void far seed_cursors(unsigned int angle, unsigned int off_dw,
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

void far remap_cursors_360(void)
{
    unsigned char k, j, n;
    unsigned int *ang;
    unsigned char *msk;
    unsigned int want;

    if (!cursors_valid || hc_plan_cycle != 7200u) {
        return;
    }
    for (k = 0u; k < 4u; k++) {
        if (k < K_INJ_ON) { ang = hc_plan_ign_anchors; msk = ig_mask; n = ig_n; }
        else              { ang = hc_plan_inj_anchors; msk = hc_plan_inj_masks; n = in_n; }
        if (n == 0u) {
            continue;
        }
        want = (unsigned int)(ang[hc_plan_cursors[k]] + 3600u);
        if (want >= 7200u) want = (unsigned int)(want - 7200u);
        /* a sequential plan HAS the twin now (the same slot with
           HC_SLOT_TWIN), so it remaps like a wasted one: the event 360 on is
           the same cylinder's other stroke. Only its role changes. A merged
           wasted / semi-sequential anchor's twin drives the same outputs
           (its primary cylinder is the partner) - compare the outputs. */
        for (j = 0u; j < n; j++) {
            if (ang[j] == want && msk[j] == msk[hc_plan_cursors[k]]) {
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


void HC_COLD hc_deadline_init(void)
{
    unsigned char huge *p = (unsigned char huge *)&D;
    unsigned int i;
    CC25IC = 0u;
    for (i = 0; i < sizeof(hc_dl_diag_t); i++) p[i] = 0u;
    p=(unsigned char huge *)&HC_DL_WIDTH;
    for(i=0;i<sizeof(hc_dl_width_t);i++) p[i]=0u;
    hc_dl_clock_last = T1; hc_dl_clock_ticks = hc_dl_clock_last;
    hc_dl_token = 0u; hc_dl_generation = 0u; hc_dl_revision = 0u; hc_dl_count = 0u;
    hc_dl_inhibit = 0u; hc_dl_beat = 0u; hc_dl_stale_n = 0u; hc_dl_stale_id = 0u;
    hc_dl_q_head = HC_DL_NONE;
    for (i = 0; i < HC_DL_N; i++) hc_dl_q_type[i] = 0u;
    /* CC17 remains mode 0/disabled, so no double-register output is enabled.
       Only CC25's nibble is changed: ACC25=0 (T7), mode=4. */
    CCM6 = (unsigned int)((CCM6 & 0xFF0Fu) | 0x0040u);
    hc_deadline_cancel();
}


/* Key-on priming (hcengctl711.c, main loop): one batch pulse, engine stopped.
   FCODE beside its three callees. */
unsigned char HC_COLD hc_drysched_prime(unsigned int t8)
{
    unsigned int gen, id, us, dead;
    if (!t8 || hc_prime_on || hc_dl_count || trg_rpm || trg_state != TRG_NO_SIGNAL) return 0u;
    gen = hc_dl_generation;
    /* t8 = capture ticks / 8: 6.4 us at 1.25 MHz, 10.67 us at 0.75 MHz */
#if TGT_TICKS_PER_MS_X10 == 12500UL
    us=(unsigned int)(((unsigned long)t8*32u)/5u);
#elif TGT_TICKS_PER_MS_X10 == 10000UL
    us=(unsigned int)((unsigned long)t8*8u);          /* 1.000 MHz: 8 us */
#else
    us=(unsigned int)(((unsigned long)t8*32u)/3u);
#endif
    dead=eng_deadtime_us>us?us:eng_deadtime_us;
    (void)hc_deadline_inj_request(255u,(unsigned int)(us-dead),dead,HC_DL_MAX_AHEAD);
    hc_prime_on = 1u;
    id=hc_deadline_publish(gen,T1,64uL,HC_DL_OPEN,255u,(unsigned long)t8*8uL);
    hc_deadline_inj_admitted(255u,id,gen,(unsigned long)t8*8uL);
    if (!id) {
        hc_prime_on = 0u; return 0u;
    }
    return 1u;
}

unsigned int HC_COLD hc_deadline_bench_start(unsigned char type, unsigned char channel, unsigned int ticks)
{
    unsigned int ps;
    unsigned char mask;
    if (channel < 1u || channel > 8u || !ticks || ticks > 25000u
        || (type != HC_DL_BENCH_IGN && type != HC_DL_BENCH_INJ)) return 0u;
    mask = type == HC_DL_BENCH_IGN ? (unsigned char)(1u << (channel - 1u))
        : (unsigned char)(1u << (channel <= 3u ? 7u - channel : 11u - channel));
    if (type == HC_DL_BENCH_INJ && channel > 3u) type = HC_DL_BENCH_INJ_P8;
    LOCK(ps);
    if (hc_dl_count || hc_dl_generation == 0xFFFFu || trg_rpm || trg_state != TRG_NO_SIGNAL) {
        UNLOCK(ps); return 0u;
    }
    hc_dl_token++; if (!hc_dl_token) hc_dl_token++;
    D.bench_token = hc_dl_token; D.bench_type = type; D.bench_mask = mask; D.bench_done = 0u;
    hc_dl_q_id[0] = hc_dl_token; hc_dl_q_mask[0] = mask; hc_dl_q_type[0] = type;
    hc_dl_q_next[0] = HC_DL_NONE; hc_dl_q_head = 0u; hc_dl_count = 1u; hc_dl_revision++;
    hc_deadline_bench_port_f(type, mask, 1u);
    hc_dl_q_time[0] = hc_deadline_now_f() + ticks;
    hc_deadline_arm_f(); UNLOCK(ps); return 1u;
}

