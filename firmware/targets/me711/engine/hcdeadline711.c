/* One ordered intrusive queue, task insertion / bounded CC25 dispatch.
   SSC/PEC at 14/15 remain enabled while CPU priority is temporarily 13.
   Queue walks occur with engine interrupts enabled: hc_dl_revision-checked commit.
   All queue/output ownership is near RAM. Diagnostic history is external. */
#include <reg167.h>
#include <intrins.h>
#include "hctarget.h"
#include "hchal.h"
#include "hcengine.h"
#include "hctrigger.h"
#include "hcsafety.h"
#include "hcsched_dry.h"
#include "hcdeadline711.h"
#include "hcdeadline_state.h"
#include "hcrtmon711.h"

#include "hcatomic.h"
#define LOCK(p)   HC_ATOMIC_ENTER(p)       /* the one convention, hcatomic.h */
#define UNLOCK(p) HC_ATOMIC_EXIT(p)
#define INC(x) do { if ((x) != 0xFFFFu) (x)++; } while (0)
#define D HC_DL_DIAG
#define FUEL_CUTS ENG_CUT_ALL

volatile unsigned long hc_dl_q_time[HC_DL_N];
volatile unsigned int hc_dl_q_id[HC_DL_N];
/* Per-slot timing history is deferred with the completed slot. */
unsigned int hc_dl_q_late[HC_DL_N];
volatile unsigned char hc_dl_q_type[HC_DL_N], hc_dl_q_mask[HC_DL_N], hc_dl_q_next[HC_DL_N];
volatile unsigned char hc_dl_q_head;
volatile unsigned int hc_dl_revision;
unsigned int hc_dl_token, hc_dl_owner[16];
unsigned char hc_dl_reserved_ign, hc_dl_reserved_inj, hc_dl_on_ign, hc_dl_on_inj;
unsigned long hc_dl_clock_ticks;
unsigned int hc_dl_clock_last;
volatile unsigned int hc_dl_generation;
volatile unsigned char hc_dl_count;
volatile unsigned char hc_dl_inhibit;
/* Quiesce: the hc_dl_stale_n entries queued when the
   planner lost integrity carry tokens up to hc_dl_stale_id; dispatch refuses
   their ON edges and executes their OFF and backstop edges. Everything
   published after it - the new generation - is admitted at once. The token
   compare is only consulted while such entries exist (<= HC_DL_MAX_AHEAD),
   so the 16-bit token cannot lap it. */
unsigned int hc_dl_stale_id;
unsigned char hc_dl_stale_n;
volatile unsigned int hc_dl_beat;
/* Completed slots stay allocated until their history is consumed. Reusing
   the queue payload avoids a second event buffer and preserves FIFO history. */
unsigned char hc_dl_done_head, hc_dl_done_tail;
volatile unsigned char hc_dl_corrupt;
unsigned char hc_dl_done_channel, hc_dl_cooldown_channel;
#define done_channel hc_dl_done_channel
#define cooldown_channel hc_dl_cooldown_channel
typedef char dl_diag_fits[(sizeof(hc_dl_diag_t) <= TGT_RAM_DEADLINE_LIMIT) ? 1 : -1];

/* Called only under LOCK; a compare checkpoint runs even with an empty queue.
   Therefore a paused main loop cannot lose the capture-clock wrap epoch. */
static unsigned long now_ticks(void)
{
    unsigned int t = T1;
    hc_dl_clock_ticks += (unsigned int)(t - hc_dl_clock_last);
    hc_dl_clock_last = t;
    return hc_dl_clock_ticks;
}

unsigned long hc_deadline_capture_time(void)
{
    unsigned int ps;
    unsigned long n;
    LOCK(ps); n = now_ticks(); UNLOCK(ps);
    return n;
}

static void arm_next(void)
{
    unsigned long n = now_ticks();
    long left = (hc_dl_q_head >= HC_DL_N) ? HC_DL_CHECKPOINT
                                      : (long)(hc_dl_q_time[hc_dl_q_head] - n);
    unsigned int delay;
    CC25IE = 0;
    CC25IR = 0;
    if (left > HC_DL_CHECKPOINT) delay = HC_DL_CHECKPOINT;
    else if (left <= HC_DL_GUARD) delay = HC_DL_GUARD;
    else delay = (unsigned int)left;
    CC25 = (unsigned int)(T7 + delay);
    D.compare_tick = CC25;
    CC25IC = HC_IC(TGT_ILVL_DEADLINE, TGT_GLVL_DEADLINE);
    /* Timer may pass CC25 while it is programmed, or head was already due.
       Request software service instead of waiting an entire timer wrap. */
    if (!hc_dl_corrupt && (hc_dl_done_head != HC_DL_NONE || left <= HC_DL_GUARD
        || (int)(CC25 - T7) <= 0)) CC25IR = 1;
}

/* Bench channel means the board driver index, independent of engine routing.
   Preserve that contract, but give its release to the same CC25 executor. */
/* Bench port mapping is independent of engine logical routing. A volatile
   standard-SFR pointer shares the bounded ON/OFF sequence across all ports. */
void far hc_deadline_bench_port_f(unsigned char type, unsigned char mask, unsigned char on)
{
    unsigned int volatile *port;
    unsigned int m=mask;   /* widen first: ~ on a char is CPLB, low byte only */
    if(type==HC_DL_BENCH_IGN) port=(unsigned int volatile *)0xFFC0u;
    else if(type==HC_DL_BENCH_INJ) port=(unsigned int volatile *)0xFFD0u;
    else port=(unsigned int volatile *)0xFFD4u;
    if(on) { *port&=~m;port[1]|=m; }
    else { *port|=m;port[1]&=~m; }
}

/* Immediate release is the cold abort path. Sync loss and planner overload
   quiesce: committed releases retain their deadlines. */

/* See hcdeadline711.h. Constant time at ILVL 13: no queue walk, no port
   write. The generation step makes every publication planned before it STALE
   and tells the planner to discard its own state at its next tooth. */
void hc_deadline_quiesce(unsigned char reason)
{
    unsigned int ps;
    unsigned char b;
    LOCK(ps);
    if (hc_dl_generation != 0xFFFFu) hc_dl_generation++;
    hc_dl_revision++;
    HC_RT_INC(quiesce_n);
    HC_RT.quiesce_last = reason;
    /* Every entry queued now is stale; an executor fault (the runtime
       supervisor's hc_dl_inhibit) is a separate, latched matter. */
    hc_dl_stale_id = hc_dl_token;
    hc_dl_stale_n = hc_dl_count;
    /* A channel that is not physically ON gives up its reservation and its
       owner ticket: its queued ON will be refused, its stale OFF then owns
       nothing, and the new generation may claim it at once. A channel that
       IS on keeps both, so its committed spark / close executes. */
    hc_dl_reserved_ign &= hc_dl_on_ign;
    hc_dl_reserved_inj &= hc_dl_on_inj;
    for (b = 0u; b < 8u; b++) {
        if (!(hc_dl_on_ign & (unsigned char)(1u << b))) hc_dl_owner[b] = 0u;
        hc_dl_owner[8u+b]=(hc_dl_on_inj&(1u<<b))?hc_dl_active_inj[b]:0u;
    }
    UNLOCK(ps);
}

/* One history unit: counters, one injector channel, or one cooldown check.
   No unit contains a per-output width loop or a long division helper. */
static void bookkeeping(void)
{
    unsigned char i=hc_dl_done_head,type,actual,b,bits;
    unsigned long n,width;
    unsigned int late;
    if(i==HC_DL_NONE) {
        b=cooldown_channel;cooldown_channel=(unsigned char)((b+1u)&7u);
        if((D.cooldown&(1u<<b)) && (long)(hc_deadline_capture_time()-D.inj[b].legal_time)>=0) {
            D.inj[b].flags&=(unsigned int)~8u;D.cooldown&=(unsigned int)~(1u<<b);
        }
        return;
    }
    type=(unsigned char)(hc_dl_q_type[i]&15u);actual=hc_dl_q_mask[i];
    n=hc_dl_q_time[i];
    if((hc_dl_q_type[i]&0xf0u)==0xd0u) {
        late=hc_dl_q_late[i];
        if(late>D.max_late) D.max_late=late;
        if(late>125u) INC(D.late);
        D.command_tick=(unsigned int)n;
        if(actual) {
            if(type<=4u) INC(D.executed[type-1u]);
            INC(dry_sched_executed);
        } else INC(D.suppressed);
        if(type==HC_DL_MAXDWELL && actual) {
            hc_ign_ovd_latch|=(unsigned char)(actual&D.ovd_two);
            D.ovd_two|=(unsigned char)(actual&D.ovd_one);D.ovd_one|=actual;
            INC(dry_sched_overdwell);D.reason=HC_DL_OVERDWELL;
        } else if(type==HC_DL_SPARK && actual) {
            D.ovd_one&=(unsigned char)~actual;D.ovd_two&=(unsigned char)~actual;
        }
        hc_dl_q_type[i]=(unsigned char)(0xe0u|type);done_channel=0u;
        if((type==HC_DL_OPEN || type==HC_DL_CLOSE) && actual) return;
    } else {
        b=done_channel;
        bits=(unsigned char)(actual>>b);
        while(!(bits&1u) && b<7u) { bits>>=1;b++; }
        done_channel=(unsigned char)(b+1u);
        hc_dl_q_mask[i]=(unsigned char)(actual&~(1u<<b));
        if(type==HC_DL_OPEN) {
            D.inj[b].token=hc_dl_q_id[i];D.inj[b].on_stamp=(unsigned int)n;
            D.inj[b].on_time=n;D.inj[b].flags|=1u;
        } else {
            width=hc_deadline_ticks_us_f(n-D.inj[b].on_time);
            HC_DL_WIDTH.delivered[b]=width;
            D.inj[b].delivered_us=width>65535uL?65535u:(unsigned int)width;
            D.inj[b].flags=(unsigned int)((D.inj[b].flags&~1u)|8u);
            D.cooldown|=(unsigned int)(1u<<b);
            D.inj[b].next_legal=(unsigned int)(n+HC_DL_OFF_TICKS);
            D.inj[b].legal_time=n+HC_DL_OFF_TICKS;
        }
        if(hc_dl_q_mask[i]) return;
    }
    hc_dl_done_head=hc_dl_q_next[i];hc_dl_q_type[i]=0u;
}

void hc_deadline_dispatch(void)
{
    unsigned int ps,id,late,elapsed;
    unsigned long n,command;
    unsigned char total=0u,worked=0u,i,tag,next,type,mask,actual,b,index,bits,c,route,allowed,physical,released,stale;
    unsigned int *owner;
    unsigned char *routing;
    hc_dl_beat++;
    /* Drain due heads before history. After one history unit, check again.
       At most four units (each an edge or one history unit) per entry; pending history or
       another due head requests immediate continuation at the same level.
       Each edge has its own lock; crank/cam can preempt between edges. */
    if((CC25IC&0x7fu)!=HC_IC(TGT_ILVL_DEADLINE,TGT_GLVL_DEADLINE)
        || (CCM6&0x00f0u)!=0x0040u) hc_dl_corrupt=1u;
    while(total<4u) {
        i=hc_dl_q_head;
        /* Only this executor changes the head above planner priority. */
        if(hc_dl_corrupt || (i!=HC_DL_NONE && (i>=HC_DL_N || !hc_dl_count
            || !(type=(unsigned char)((tag=hc_dl_q_type[i])&15u)) || type>HC_DL_BENCH_INJ_P8
            || (tag>=0x90u && tag<0xf0u)
            || ((next=hc_dl_q_next[i])!=HC_DL_NONE && next>=HC_DL_N)))) {
            if(!hc_dl_corrupt) hc_dl_corrupt=1u;
            hc_dl_inhibit=HC_Q_WITHDRAWN;break;
        }
        LOCK(ps);
        n=now_ticks();
        if(i==HC_DL_NONE || (long)(command=n-hc_dl_q_time[i])<0) {
            UNLOCK(ps);
            if(worked && hc_dl_done_head==HC_DL_NONE) break;
            bookkeeping();worked=1u;total++;
            continue;
        }
        b=(unsigned char)(tag>>4);
        mask=hc_dl_q_mask[i];id=hc_dl_q_id[i];
        /* Invalidate planner walks for a queue mutation, not an empty
           heartbeat or history-only continuation. */
        hc_dl_revision++;
        hc_dl_q_head=next;
        hc_dl_count--;
        stale=(unsigned char)(hc_dl_stale_n && (int)(id-hc_dl_stale_id)<=0);
        if(stale) hc_dl_stale_n--;
        if(type>=HC_DL_BENCH_IGN) {
            if(D.bench_type==type && D.bench_token==id) {
                hc_deadline_bench_port_f(type,D.bench_mask,0u);
                D.command_tick=T7;D.bench_type=0u;D.bench_done=1u;
            }
            hc_dl_q_type[i]=0u;
            UNLOCK(ps);
            total++;
            continue;
        }
        c=(unsigned char)(type==HC_DL_MAXDWELL?1u:type-1u);
        index=(unsigned char)(c&2u?8u:0u);
        owner=c==3u?hc_dl_active_inj:&hc_dl_owner[index];
        allowed=255u;
        if(!(c&1u)) {
            if(command>125uL || (trg_state<TRG_SYNC_CRANK && !hc_prime_on)
                || hc_dl_inhibit || stale
                || (eng_fuelcut&ENG_CUT_LIMP) || (type==HC_DL_OPEN && (eng_fuelcut&FUEL_CUTS))) allowed=0u;
            else if(!index) allowed=(unsigned char)~hc_ign_ovd_latch;
            if(c==2u) allowed&=(unsigned char)~hc_dl_on_inj;
        } else allowed=index?hc_dl_on_inj:hc_dl_on_ign;
        actual=physical=released=0u;
        /* Complete routing was sealed by the task, every ticket still checked. */
        if(b && b<=8u) {
            b--;
            if(id && owner[b]==id) {
                if(c&1u) { owner[b]=0u;if(!index || hc_dl_owner[index+b]==id) released=mask; }
                else released=mask;
                route=hc_hal_actuator_route[index+b];
                if((allowed&mask) && route) { actual=mask;physical=route; }
            }
        } else if(b==15u && allowed==255u && id
            && owner[0]==id && owner[1]==id
            && owner[2]==id && owner[3]==id
            && owner[4]==id && owner[5]==id
            && owner[6]==id && owner[7]==id) {
            actual=physical=255u;
            if(c&1u) {
                owner[0]=owner[1]=owner[2]=owner[3]=0u;
                owner[4]=owner[5]=owner[6]=owner[7]=0u;
                if(!index) released=255u;
                else for(b=0u;b<8u;b++) if(hc_dl_owner[8u+b]==id) released|=(unsigned char)(1u<<b);
            } else released=255u;
        } else {
            b=0u;bits=mask;mask=1u;
            if(!id) bits=0u;
            routing=&hc_hal_actuator_route[index+b];
            for(;bits;owner++,routing++,bits>>=1,mask<<=1,b++) if((bits&1u) && *owner==id) {
                if(c&1u) { *owner=0u;if(!index || hc_dl_owner[index+b]==id) released|=mask; }
                else released|=mask;
                route=*routing;
                if((allowed&mask) && route) { actual|=mask;physical|=route; }
            }
        }
        if(actual) {
            actual=(unsigned char)hc_hal_deadline_ports((unsigned char)(index?HC_OUT_INJ1:HC_OUT_IGN1),actual,physical,(unsigned char)(!(c&1u)));
        }
        elapsed=(unsigned int)(T1-(unsigned int)n);
        n+=elapsed;command+=elapsed;
        if(c==0u) hc_dl_on_ign|=actual;
        else if(c==2u) {
            /* released: every lane this OPEN owned. A lane refused here (late,
               cut, inhibited) while OFF still adopts this ticket as a pulse of
               zero width, so its own CLOSE releases the reservation; otherwise
               that CLOSE matches no active ticket and the channel stays
               reserved for good. A still-ON lane cannot reach this (its next
               OPEN is published >= 200 us after the owned CLOSE). */
            for(b=0u,bits=(unsigned char)(released&~hc_dl_on_inj);bits;bits>>=1,b++) if(bits&1u) hc_dl_active_inj[b]=id;
            hc_dl_on_inj|=actual;
        }
        else if(c==1u) { hc_dl_on_ign&=(unsigned char)~actual;hc_dl_reserved_ign&=(unsigned char)~released; }
        else { hc_dl_on_inj&=(unsigned char)~actual;hc_dl_reserved_inj&=(unsigned char)~released;if(actual) hc_prime_on=0u; }
        UNLOCK(ps);
        /* Fixed-size trace and history-link commit; only this level writes
           the completed FIFO. No width calculation precedes the next edge. */
        late=command>65535uL?65535u:(unsigned int)command;
        hc_dl_q_late[i]=late;
        if(late>3125u) { hc_dl_corrupt|=2u;hc_dl_inhibit=HC_Q_WITHDRAWN; }
        hc_dl_q_time[i]=n;hc_dl_q_mask[i]=actual;
        hc_dl_q_type[i]=(unsigned char)(0xd0u|type);hc_dl_q_next[i]=HC_DL_NONE;
        if(hc_dl_done_head==HC_DL_NONE) hc_dl_done_head=i;
        else hc_dl_q_next[hc_dl_done_tail]=i;
        hc_dl_done_tail=i;total++;
    }
    dry_sched_queued=hc_dl_count;
    if(!hc_dl_count) hc_dl_stale_n=0u;
    dry_sched_max_latency=D.max_late;dry_sched_late=D.late;
    LOCK(ps);arm_next();UNLOCK(ps);
}

void hc_cc25_isr(void) interrupt TGT_TRAP_CC25INT using DLBANK
{
    hc_deadline_dispatch();
}

unsigned long far hc_deadline_now_f(void) { return now_ticks(); }
void far hc_deadline_arm_f(void) { arm_next(); }


