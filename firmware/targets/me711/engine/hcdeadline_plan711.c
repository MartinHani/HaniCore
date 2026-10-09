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
    while(work++<8u-1u && hc_plan_generation==hc_dl_generation) {
        p=hc_plan_cap_tail;next=(unsigned char)((p+1u)&(8u-1u));
        if(p==hc_plan_cap_head || next==hc_plan_cap_head) break;
        angle=hc_plan_cap_angle[p];
        hc_plan_cap_tail=next;
        hc_plan_count_tooth_f(angle);
    }
}

/* floor(0.8 * ticks), with two native divisions and bounded quotients. */
unsigned long far hc_deadline_ticks_us_f(unsigned long w)
{
    unsigned int hi,qh,ql;
    w+=4uL;hi=(unsigned int)(w>>16);qh=hi/5u;
    ql=(unsigned int)((((unsigned long)(unsigned int)(hi-qh*5u))<<16
                      |(unsigned int)w)/(unsigned int)5u);
    return w-4uL-(((unsigned long)qh<<16)|ql);
}

/* Live advance/dwell/phase changes apply only to an uncommitted event with
   enough publication lead. A new offset may not jump the next cursor behind
   the crank or inside its commit horizon. Keep its prior phase for this
   event, then apply the change to a later one. No deadline is retimed. */
static const unsigned char plan_slot_mask[16]={255u,1u,2u,4u,8u,16u,32u,64u,128u,0u,0u,0u,0u,0u,0u,0u};
unsigned int HC_COLD hc_deadline_plan_offset(unsigned int kind, unsigned int proposed)
{
    unsigned int huge *p=(unsigned int huge *)(TGT_EXTRAM_BASE+TGT_RAM_PLANOFF);
    unsigned int d,anchor,cycle;
    if(p[kind] != proposed) {
        /* An EOI change cannot move the next start across an owned pulse. */
        if(kind==2u) {
            unsigned char slot=(unsigned char)(hc_plan_inj_slots[hc_plan_cursors[kind]]&15u);
            if(hc_dl_reserved_inj & plan_slot_mask[slot]) return p[kind];
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
#define HC_DL_OVERDUE 3125uL     /* 2.5 ms; dispatch latency is < 0.2 ms */
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
    if(mask==255u && type<=HC_DL_MAXDWELL) {
        unsigned char i,physical=0u,index=(type==HC_DL_OPEN || type==HC_DL_CLOSE)?8u:0u;
        for(i=0;i<8u;i++) physical|=hc_hal_actuator_route[index+i];
        if(physical==255u) return (unsigned char)(type|0xf0u);
    }
    if(mask && !(mask&(mask-1u))) {
        while(!(mask&1u)) { mask>>=1; b++; }
        return (unsigned char)(type|(b<<4));
    }
    return type;
}
unsigned long HC_COLD hc_deadline_inj_request(unsigned char mask,unsigned int fuel,unsigned int dead,unsigned long period)
{
    unsigned long requested=(unsigned long)fuel+dead,duration=requested+(requested>>2);
    unsigned char b,bits,clipped;
    unsigned int ps;
    if(period<=HC_DL_OFF_TICKS*2u) {
        clipped=(unsigned char)(duration!=0uL);duration=0uL;
    } else {
        period-=HC_DL_OFF_TICKS*2u;
        clipped=(unsigned char)(duration>period);
        if(clipped) duration=period;
    }
    for(b=0u,bits=mask;bits;b++,bits>>=1) if(bits&1u) {
        LOCK(ps);
        D.inj[b].fuel_us=fuel; D.inj[b].dead_us=dead;
        D.inj[b].requested_us=requested>65535uL?65535u:(unsigned int)requested;
        D.inj[b].flags=(unsigned int)((D.inj[b].flags&13u)|(clipped?2u:0u)|(requested>65535uL?16u:0u));
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
    scheduled=width>65535uL?65535u:(unsigned int)width;
    for(b=0u,bits=mask;bits;b++,bits>>=1) if(bits&1u) {
        LOCK(ps);
        if(id && generation==hc_dl_generation) {
            D.inj[b].scheduled_us=scheduled;
            HC_DL_WIDTH.accepted[b]=width; D.inj[b].flags&=(unsigned int)~32u;
            HC_DL_WIDTH.accepted_ticket[b]=id;
        } else D.inj[b].flags|=32u;
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
static unsigned char before(unsigned long a, unsigned char at,
                             unsigned long b, unsigned char bt)
{
    long delta = (long)(a - b);
    at &= 15u; bt &= 15u;
    if (delta != 0) return (unsigned char)(delta < 0);
    /* OFF before ON at equal time; FIFO within the same edge class. */
    return (unsigned char)(((at == HC_DL_SPARK || at >= HC_DL_CLOSE) ? 0u : 1u)
        < ((bt == HC_DL_SPARK || bt >= HC_DL_CLOSE) ? 0u : 1u));
}

/* Task only. Prepare payload/position unlocked, then commit one pointer pair.
   Crank cancellation/compare dispatch increments hc_dl_revision before returning.
   Slots remain invisible (type=0) until the successful critical commit. */
static unsigned char insert(unsigned int generation, unsigned long when,
    unsigned char type, unsigned char mask, unsigned int id)
{
    unsigned char retry, i, p, prev, walked;
    unsigned char tag=packed(type,mask);
    unsigned int rev, ps;
    for (retry = 0; retry < 4u; retry++) {
        rev = hc_dl_revision;
        if (generation != hc_dl_generation || generation == 0xFFFFu) return 0u;
        for (i = 0; i < HC_DL_N && hc_dl_q_type[i] != 0u; i++) { }
        if (i == HC_DL_N) return 0u;
        prev = HC_DL_NONE;
        p = hc_dl_q_head;
        walked = 0u;
        while (p < HC_DL_N && walked++ < HC_DL_N && !before(when, type, hc_dl_q_time[p], hc_dl_q_type[p])) {
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
    unsigned int rev, ps;
    for (retry = 0; retry < 4u; retry++) {
        rev = hc_dl_revision;
        if (generation != hc_dl_generation || generation == 0xFFFFu) return 0u;
        for (i = 0; i < HC_DL_N && hc_dl_q_type[i]; i++) { }
        for (j = (unsigned char)(i + 1u); j < HC_DL_N && hc_dl_q_type[j]; j++) { }
        if (j >= HC_DL_N) return 0u;
        p = hc_dl_q_head; prev = HC_DL_NONE; seen = walked = 0u;
        while (p < HC_DL_N && walked++ < HC_DL_N) {
            if (!seen && before(start, type, hc_dl_q_time[p], hc_dl_q_type[p])) {
                sp = prev; sn = p; seen = 1u;
            }
            if (before(end, ending, hc_dl_q_time[p], hc_dl_q_type[p])) break;
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
            for(i=0u,bits=mask;bits;i++,bits>>=1) if(bits&1u) {
                LOCK(ps);D.inj[i].flags|=64u;UNLOCK(ps);
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
        for (i=0,bits=mask;bits;i++,bits>>=1) if ((bits&1u)
            && (D.inj[i].flags & 8u) && (long)(when - D.inj[i].legal_time) < 0) {
            D.reason = HC_DL_OVERLAP; INC(D.suppressed); UNLOCK(ps); return 0u;
        }
    }
    if (opening) {
        hc_dl_token++; if (hc_dl_token == 0u) hc_dl_token++;
        id = hc_dl_token;
        if (type == HC_DL_DWELL) hc_dl_reserved_ign |= mask; else hc_dl_reserved_inj |= mask;
        for (i=0,bits=mask;bits;i++,bits>>=1) if(bits&1u) hc_dl_owner[(type == HC_DL_DWELL ? 0u : 8u) + i] = id;
    } else {
        /* OFF carries its own publication identity, never a live-hc_dl_owner lookup. */
        id = (unsigned int)duration;
        if (id == 0u) { UNLOCK(ps); return 0u; }
    }
    UNLOCK(ps);
    if (opening) {
        unsigned int merged = merge_pair(generation, when, when + duration, type, mask);
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
    us=(unsigned int)(((unsigned long)t8*32u)/5u);
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

