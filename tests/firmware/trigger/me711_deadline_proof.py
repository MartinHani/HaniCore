"""Execute the linked CC25 backend with actual C167 timer/interrupt delivery.

This is command-edge software qualification, never physical pin measurement.
The CPU instruction/timer ratio is explicitly 8. No task polling dispatches.
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_trigger_test as P
import me711_image as I

DIAG = 0x387500
checks = fails = 0

def check(name, ok, detail=''):
    global checks, fails
    checks += 1; fails += not ok
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")

class Rig(P.Call):
    def __init__(self, timer=0):
        super().__init__()
        self.call('hc_hal_init')
        P.describe_engine(self, cylinders=4, teeth=60, gap=2,
                          soi_x10=3600, tdc=[0,5400,1800,3600], cam_refs=0)
        cfg=P.sym('hc_cfg') & 0xffff
        for i,v in enumerate([0,3,1,2,255,255,255,255]):
            self.m.w8(cfg+34+i,v); self.m.w8(cfg+42+i,v)
        for off,values in [(2551,[96,89,97,88]),(2563,[102,95,103,94])]:
            for i,v in enumerate(values+[255]*8): self.m.w8(0x38000c+off+i,v)
        self.m.w8(0x38000c+2548,82)
        self.call('trg_init')
        self.m.w8(P.sym('trg_state') & 0xffff, 3)
        self.m.w16(P.sym('hc_cfg_validation') & 0xffff,0)
        self.call('hc_safety_service',1,1,1,0,1)
        self.call('hc_hal_out_group',0,255,0) # task resolves routes
        self.call('hc_hal_out_group',8,255,0)
        self.m.w16(0xF050,timer); self.m.w16(0xFE52,timer)
        self.call('hc_deadline_init')
        self.c.steps_per_tick=8
        self.m.w16(0xFF20,0x0042); self.m.w16(0xFF50,0x4200)
        self.m.w16(0xFF10,0x0800)
        self.log=[]; self.levels=[]; self.wall=0
        # Idle task executes a single JMPR loop from internal XRAM. Real
        # vector forwarding and RETI return to this interrupted instruction.
        self.m.w8(0xE800,0x0D); self.m.w8(0xE801,0xFF)
        self.idle()

    def idle(self):
        self.c.csp=0; self.c.ip=0xE800
        self.m.w16(self.c.cp(),self.stack_top)
        self.m.w16(0xFE12,0xF700)

    def publish_args(self, kind, mask, delay, width, gen=None, absolute=False):
        stamp=self.m.r16(0xFE52)
        ahead=(delay-stamp)&65535 if absolute else delay
        duration=width*5//4 if kind in (1,3) else width
        return (self.u16('hc_dl_generation') if gen is None else gen,
                stamp,ahead&65535,ahead>>16,kind), (mask,duration&65535,duration>>16)

    def publish(self, kind, mask, delay, width, gen=None, absolute=False):
        regs, words=self.publish_args(kind,mask,delay,width,gen,absolute)
        # C166 passes the first five words in R8..R12. Remaining arguments
        # occupy the caller's user stack. Exercise the production API itself.
        top=self.stack_top
        self.stack_top-=6
        for i,w in enumerate(words):self.m.w16(self.stack_top+2*i,w)
        try:out=self.call('hc_deadline_publish',*regs)
        finally:self.stack_top=top
        self.idle()
        return out

    def set_clock(self, hi, lo):
        assert self.u8('hc_dl_count')==0
        a=P.sym('hc_dl_clock_ticks')
        self.m.w16(a,lo);self.m.w16(a+2,hi)
        self.m.w16(P.sym('hc_dl_clock_last'),lo)
        self.m.w16(0xF050,lo);self.m.w16(0xFE52,lo)
        self.call('hc_deadline_arm_f')
        self.idle()

    def run(self,ticks):
        end=self.wall+ticks
        prev=(self.m.r16(0xFFC2)&0xff,self.m.r16(0xFFD2)&0x70,self.m.r16(0xFFD6)&0xf8)
        last=self.m.r16(0xF050)
        for _ in range(ticks*12+20000):
            self.c.step()
            t=self.m.r16(0xF050)
            self.wall += (t-last)&0xffff; last=t
            now=(self.m.r16(0xFFC2)&0xff,self.m.r16(0xFFD2)&0x70,self.m.r16(0xFFD6)&0xf8)
            if now != prev:
                self.log.append((self.wall,self.m.r16(0xFE52),now));prev=now
                self.levels.append(tuple(self.m.r16(a) for a in (0xFFC0,0xFFD0,0xFFD4)))
            if self.wall >= end and self.c.ip==0xE800 and self.c.csp==0: return
        raise AssertionError('idle/ISR did not reach time bound')

    def cancel(self):
        self.call('hc_drysched_cancel',0)
        self.idle()

    def prime_real_sync_loss(self):
        self.m.w16(0xFF10,0); self.m.w16(0xFF20,0); self.m.w16(0xFF50,0)
        self.call('trg_test_geometry')
        for t in (0,1000):
            self.m.w16(0xFE52,t); self.call('trg_test_crank_edge',t)
        self.m.w8(P.sym('trg_state')&0xffff,3)
        self.m.w16(P.sym('trg_tooth')&0xffff,58)
        self.m.w16(0xFE52,2000); self.call('trg_test_crank_edge',2000)
        self.set_clock(0,3000)
        self.m.w16(0xFF20,0x0042); self.m.w16(0xFF50,0x4200); self.m.w16(0xFF10,0x0800)
        self.idle()

    def request_real_sync_loss(self):
        # The second missing-gap disagreement goes through actual CC15,
        # crank decoding, lose_sync and the generation withdrawal.
        self.m.w16(0xFE9E,3000); self.m.w16(0xFF96,0xF3)

    def dirs(self):
        return tuple(self.m.r16(a) for a in (0xFFC2,0xFFD2,0xFFD6))

    def diag(self,word): return self.m.r16(DIAG+word*2)

    def pulse_lengths(self, group):
        opened=None; lengths=[]
        for wall,t,ports in self.log:
            on = bool(ports[0]) if group=='ign' else bool(ports[1] or ports[2])
            if on and opened is None: opened=wall
            elif not on and opened is not None:
                lengths.append(wall-opened); opened=None
        return lengths

def future_pulse_tests():
    def transitions(r):
        ports=[];previous=False
        for _,t,p in r.log:
            on=bool(p[1] or p[2])
            if on!=previous:ports.append((t,on));previous=on
        return ports
    def widths(ports):
        return [((ports[i+1][0]-ports[i][0])&65535)
                for i in range(0,len(ports)-1,2)]
    for mask in (1,3,255):
        r=Rig();first=r.publish(3,mask,1000,5000);r.run(2000)
        close=next(r.m.r16(P.sym('hc_dl_q_time')+4*i)
                   for i in range(24) if r.m.r8(P.sym('hc_dl_q_type')+i)&15==4
                   and r.m.r16(P.sym('hc_dl_q_id')+2*i)==first)
        following=(close+500)&65535
        second=r.publish(3,mask,following,2000,absolute=True)
        check('following injector pulse admitted while current is ON',bool(second),str(mask))
        third=r.publish(3,mask,(following+5000)&65535,1000,absolute=True)
        check('only one following OPEN can be pending',third==0,str(mask))
        r.run(14000)
        ports=transitions(r);lens=widths(ports)
        check('current CLOSE retains its own deadline and width',
              lens and abs(lens[0]-6250)<=125,str(lens))
        check('following pulse has its own owner and CLOSE',
              len(lens)==2 and abs(lens[1]-2500)<=125 and r.dirs()==(0,0,0),str(lens))
        ports=transitions(r)
        releases=[t for t,on in ports if not on]
        opens=[t for t,on in ports if on]
        check('following command preserves at least 100 us physical OFF',
              len(opens)==2 and len(releases)==2 and ((opens[1]-releases[0])&65535)>=125,str(ports))
    r=Rig();first=r.publish(3,1,1000,5000);r.run(2000)
    close=next(r.m.r16(P.sym('hc_dl_q_time')+4*i)
               for i in range(24) if r.m.r8(P.sym('hc_dl_q_type')+i)&15==4
               and r.m.r16(P.sym('hc_dl_q_id')+2*i)==first)
    r.publish(3,1,(close+500)&65535,2000,absolute=True)
    r.call('hc_deadline_quiesce',1);r.idle();r.run(14000)
    ports=transitions(r);lens=widths(ports)
    check('quiesce retains current CLOSE and refuses the pending next OPEN',
          len(lens)==1 and abs(lens[0]-6250)<=125 and r.dirs()==(0,0,0),str(lens))
    for overlap, admitted in ((500, True), (3000, False)):
        r=Rig();first=r.publish(3,1,1000,5000);r.run(2000)
        close=next(r.m.r16(P.sym('hc_dl_q_time')+4*i)
                   for i in range(24) if r.m.r8(P.sym('hc_dl_q_type')+i)&15==4
                   and r.m.r16(P.sym('hc_dl_q_id')+2*i)==first)
        second=r.publish(3,1,(close-overlap)&65535,2000,absolute=True)
        check('physical-overlap phase adjustment stays inside 2 ms',
              bool(second)==admitted,str((overlap,second)))
        if admitted:
            start=next(r.m.r16(P.sym('hc_dl_q_time')+4*i)
                       for i in range(24) if r.m.r8(P.sym('hc_dl_q_type')+i)&15==3
                       and r.m.r16(P.sym('hc_dl_q_id')+2*i)==second)
            check('adjusted OPEN retains the predecessor CLOSE and OFF reserve',
                  ((start-close)&65535)==250,str((close,start)))
        r.run(14000)
        ports=transitions(r);lens=widths(ports)
        check('overlap handling preserves each admitted pulse width',
              len(lens)==(2 if admitted else 1) and abs(lens[0]-6250)<=125
              and (not admitted or abs(lens[1]-2500)<=125),str(lens))

def main():
    print(I.STEM, I.sha256())
    if "--control" in sys.argv:
        address=P.sym('hc_dl_active_inj');original=P.S.Mem.w16
        def dropped_ticket(mem,a,v):
            if address<=a<address+16 and v: return
            return original(mem,a,v)
        P.S.Mem.w16=dropped_ticket
        try:future_pulse_tests()
        finally:P.S.Mem.w16=original
        print('CONTROL OK: missing actual command tickets rejected' if fails
              else 'CONTROL BROKEN: missing actual command tickets accepted')
        return int(not fails)
    future_pulse_tests()
    if "--future-only" in sys.argv:
        print(f"{checks-fails}/{checks} PASS")
        return int(bool(fails))
    r=Rig(); token=r.publish(1,1,1000,4000)
    check('dwell admitted with reserved max release',bool(token))
    r.run(7000)
    check('compare ISR fires while task is stalled',r.c.irq_count.get(0x39,0)>0,str(r.c.irq_count))
    check('coil command released without main loop',r.call('hc_hal_out_mask_ign')==0,str(r.log))
    check('independent max dwell counted',r.u16('dry_sched_overdwell')==1)
    check('single overdwell preserves the V99 consecutive-fault policy',r.u16('hc_ign_ovd_latch')==0)
    check('real active-low coil command polarity', bool(r.log) and not(r.levels[0][0]&1)
          and (r.levels[1][0]&1) and abs(r.pulse_lengths('ign')[0]-5000)<125,str(r.levels))
    for _ in range(2): r.publish(1,1,1000,4000); r.run(7000)
    check('three consecutive max releases latch a coil fault',r.u16('hc_ign_ovd_latch')&1)
    for start in (0,0x7ff0,0xff00):
        r=Rig(start); token=r.publish(3,1,1000,30000)
        check(f'30 ms injector admitted at timer {start:04x}',bool(token))
        r.run(41000)
        lens=r.pulse_lengths('inj')
        check('extended close survives half range and full timer wrap', len(lens)==1 and abs(lens[0]-37500)<125,str(lens))
        check('delivered width uses extended command timestamps',abs(r.m.r16(DIAG+38+8)-30000)<100,str(r.m.r16(DIAG+38+8)))
    r=Rig(); first=r.publish(1,1,1000,8000)
    r.publish(2,1,5000,first)
    r.run(6000)
    check('normal spark owns and ends dwell',r.pulse_lengths('ign') and abs(r.pulse_lengths('ign')[0]-4000)<125,str(r.log))
    second=r.publish(1,1,1000,4000)
    r.publish(2,1,2000,first) # deliberately stale same-generation release
    r.run(3500)
    check('old release cannot truncate a newer coil owner',r.dirs()[0]&1,str(r.log))
    r.run(4000)
    check('old maximum deadline cannot clear newer reservation',r.u16('dry_sched_overdwell')==1,str(r.log))
    r=Rig(); old=r.u16('hc_dl_generation'); r.publish(3,1,1000,5000);r.cancel()
    check('cancelled generation cannot publish ON',r.publish(3,1,1000,5000,old)==0)
    fresh=r.publish(3,1,1000,5000);r.run(3000)
    check('new generation can own a fresh pulse',r.dirs()[1]&0x40,str(r.log))
    check('old generation close publication is rejected',r.publish(4,1,1000,fresh,old)==0)
    # 2026-10-07: a WITHDRAWAL (sync loss, permission - hc_drysched_cancel) is
    # a quiesce: an output that is ON keeps its committed OFF and ends at its
    # own time (a coil released early IS a spark), nothing new turns ON. The
    # ABORT (route change - hc_drysched_abort -> hc_deadline_cancel) still
    # releases at once; both are asserted.
    r.cancel()
    check('withdrawal during a pulse keeps the committed close',bool(r.dirs()[1]&0x70),str(r.log))
    r.run(8000)
    lens=r.pulse_lengths('inj')
    check('... which ends the pulse at its planned width, nothing after',
          not (r.dirs()[1]&0x70) and lens and abs(lens[-1]-6250)<125,str(lens))
    r=Rig(); r.publish(3,1,1000,5000); r.run(3000)
    r.call('hc_drysched_abort',0)
    check('abort during pulse releases physical command',not (r.dirs()[1]&0x70),str(r.log))
    r=Rig(); first=r.publish(3,1,1000,5000)
    check('pending overlap refused',r.publish(3,1,2000,5000)==0)
    r.run(4000)
    close=next(r.m.r16(P.sym('hc_dl_q_time')+4*i)
               for i in range(24) if r.m.r8(P.sym('hc_dl_q_type')+i)&15==4)
    check('active overlap beyond phase-adjustment bound refused',
          r.publish(3,1,(close-3000)&65535,5000,absolute=True)==0)
    r.run(4000)
    second=r.publish(3,1,1000,5000)
    check('next legal pulse accepted after close/off separation',bool(second))
    r.publish(4,1,2000,first);r.run(4000)
    check('old injector close cannot truncate new pulse',r.dirs()[1]&0x40,str(r.log))
    r.run(5000);check('each accepted injector has its own close',len(r.pulse_lengths('inj'))==2,str(r.log))
    for delay in (32767,32768,65535):
        r=Rig(0xff00);r.publish(3,1,delay,1000);r.run(delay+4000)
        wanted=r.diag(16)
        check(f'future deadline {delay} ticks is never early',r.log and 0<=((r.log[0][1]-wanted)&0xffff)<=125,str(r.log))
    r=Rig();r.set_clock(0xffff,0xf000);r.idle()
    r.publish(3,1,1000,5000);r.run(9000)
    check('extended 32-bit clock rollover preserves ordering',r.pulse_lengths('inj') and abs(r.pulse_lengths('inj')[0]-6250)<125,str(r.log))
    r=Rig();r.publish(3,2,3000,1000);r.publish(3,1,1000,1000);r.run(6000)
    check('deadline order is independent of allocation slot',r.log and r.log[0][2][1]==0x40,str(r.log))
    r=Rig();ids=[r.publish(1,1<<b,2000,4000,absolute=True) for b in range(4)]
    r.run(2000)
    check('simultaneous edges dispatch in deterministic bounded batches',r.dirs()[0]&15==15,str(r.log))
    edges=[next((t for _,t,ports in r.log if ports[0] & (1<<b)),None) for b in range(4)]
    check('four simultaneous coil edge error <=100 us in fixture',all(t is not None and 0<=t-2000<=125 for t in edges),str(r.log))
    r.run(6000)
    check('simultaneous max dwell releases every owned coil',r.dirs()[0]&15==0,str(r.log))
    r=Rig()
    for kind,mask in ((1,1),(3,1),(1,2),(3,2)): r.publish(kind,mask,3000,4000,absolute=True)
    r.run(3000)
    critical=[next((t for _,t,ports in r.log if ports[port]&bit),None) for port,bit in ((0,1),(0,8),(1,0x40),(2,0x80))]
    check('mixed coil/injector burst executes every owned channel',all(t is not None for t in critical),str(r.log))
    check('mixed coil/injector burst critical command error <=100 us',all(t is not None and 0<=t-3000<=125 for t in critical),str(r.log))
    r=Rig();r.publish(3,1,1000,1);r.run(2000)
    check('ON and ending due in one interrupt cannot strand a short pulse',r.dirs()==(0,0,0) and r.u8('hc_dl_count')==0,str(r.log))
    r=Rig(); accepted=[]
    for kind in (1,3):
        for b in range(8): accepted.append(r.publish(kind,1<<b,30000,30000))
    check('queue saturation is explicit',any(not v for v in accepted) and r.diag(12)>0,str(accepted))
    r.cancel();r.run(50000)
    check('queue pressure/cancel cannot strand or restart outputs',r.dirs()==(0,0,0),str(r.dirs()))
    r=Rig();r.publish(3,1,1000,5000);r.m.w16(P.sym('eng_fuelcut')&0xffff,1);r.run(9000)
    check('fuel cut before compare suppresses injector ON',not r.log,str(r.log))
    # An OPEN refused for lateness (> 100 us) must still give its channel back:
    # its CLOSE matched no active ticket and the reservation stayed set for good.
    r=Rig();r.publish(3,1,300,2000)
    r.m.w16(0xFF10,0xC800);r.run(600);r.m.w16(0xFF10,0x0800);r.run(4000)
    check('late OPEN is refused, not executed',not r.log and r.diag(13)==1,str((r.log,r.diag(13))))
    again=r.publish(3,1,1000,2000);r.run(5000)
    check('a refused late OPEN releases its channel for the next pulse',
          bool(again) and len(r.pulse_lengths('inj'))==1 and r.u8('hc_dl_reserved_inj')==0,
          str((again,r.pulse_lengths('inj'),r.u8('hc_dl_reserved_inj'))))
    r=Rig();r.publish(1,1,1000,4000);r.m.w8(P.sym('trg_state')&0xffff,0);r.run(7000)
    check('cached HAL permission cannot bypass live sync withdrawal',not r.log,str(r.log))
    r=Rig();r.prime_real_sync_loss();r.publish(3,1,1000,5000)
    before=r.u16('hc_dl_generation');r.request_real_sync_loss();r.run(9000)
    check('real CC15 missing-gap loss withdraws pending injector ownership',r.u16('trg_synclost')==1 and r.u16('hc_dl_generation')!=before and not r.log,str(r.c.irq_count))
    r=Rig();r.publish(3,1,1000,5000);r.run(3000);r.call('hc_deadline_fuel_cut');r.idle();r.run(6000)
    check('fuel cut truncates active pulse and clears its owner',not(r.dirs()[1]&0x70) and r.m.r16((P.sym('hc_dl_owner')&0xffff)+16)==0)
    r=Rig();r.publish(3,1,5000,5000);r.call('hc_deadline_fuel_cut');r.idle();r.run(13000)
    check('cut withdrawn before due cannot resurrect an old pulse',not r.log)
    r=Rig();r.m.w16(P.sym('hc_dl_generation')&0xffff,0xffff)
    check('generation exhaustion refuses ON rather than ABA wrap',not r.publish(3,1,1000,1000))
    r=Rig();r.m.w16(P.sym('hc_dl_token')&0xffff,0xfffe)
    a=r.publish(3,1,1000,5000);b=r.publish(3,2,1500,5000)
    r.publish(4,2,2000,a);r.run(4000)
    check('token rollover skips zero and stale token cannot close new owner',a==0xffff and b==1 and bool(r.dirs()[2]&0x80),str(r.log))
    for ch in range(1,9):
        r=Rig();r.m.w8(P.sym('trg_state')&0xffff,0)
        admitted=r.call('hc_deadline_bench_start',7,ch,1250);r.idle()
        actual=r.dirs();want=(0,1<<(7-ch),0) if ch<=3 else (0,0,1<<(11-ch))
        check(f'bench injector driver {ch} exact port direction',admitted and actual==want,str(actual))
        r.run(3000)
        check(f'bench injector driver {ch} releases during task stall',r.dirs()==(0,0,0) and r.m.r16(DIAG+250)==1,str(r.dirs()))
    print(f'{checks-fails}/{checks} PASS')
    return int(bool(fails))

if __name__=='__main__': raise SystemExit(main())
