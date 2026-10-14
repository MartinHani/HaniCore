"""Inject real CC15 loss around each linked queue/owner/priority mutation.

The selected boundaries come from executing the target, then are replayed
one instruction before, at and after. Cancellation is actually decoded by
the crank ISR; neither queue state nor output permission is reset by Python.
"""
import copy,sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_deadline_proof as D
import me711_trigger_test as P
import me711_image as I

def setup_call(r,fn,args):
    a=P.sym(fn);top=r.stack_top
    if fn=='hc_deadline_publish':
        args,words=r.publish_args(*args)
        top-=6
        for i,w in enumerate(words):r.m.w16(top+2*i,w)
    r.m.w16(r.c.cp(),top)
    r.m.w16(0xfe14,0xf200);r.m.w16(0xfe16,0xfe00)
    sp=0xf700
    for w in (a>>16,0xfffe):sp-=2;r.m.w16(sp,w)
    r.m.w16(0xfe12,sp)
    for i,v in enumerate(args):r.c.sr(8+i,v&65535)
    r.c.csp=a>>16;r.c.ip=a&65535

def state(r):
    values=[]
    for n,w in [('hc_dl_generation',2),('hc_dl_revision',2),('hc_dl_count',1),('hc_dl_q_head',1),('hc_dl_reserved_ign',1),('hc_dl_reserved_inj',1),('hc_dl_on_ign',1),('hc_dl_on_inj',1),('hc_dl_owner',32),('hc_dl_q_type',24),('hc_dl_q_mask',24),('hc_dl_q_next',24),('hc_dl_q_time',96),('hc_dl_q_id',48)]:
        a=P.sym(n)&65535;values.extend(r.m.r8(a+i) for i in range(w))
    values.extend(r.m.r8(0x387200+i) for i in range(96))
    return tuple(values)+(r.m.r16(0xff10)&0xf800,)+r.dirs()

def execute(r,limit,inject=None,trace=False,idle_end=False):
    old=state(r) if trace else None;points=set();lost=False;bad=False;minimum=r.stack_top;sysmin=0xf700
    initial=r.u16('hc_dl_generation');prev=r.dirs()
    for k in range(limit):
        if k==inject:r.request_real_sync_loss()
        r.c.step()
        minimum=min(minimum,r.c.gr(0));sysmin=min(sysmin,r.m.r16(0xfe12))
        if r.u16('hc_dl_generation')!=initial:lost=True
        current=r.dirs()
        if lost and any(new&~before for before,new in zip(prev,current)):bad=True
        prev=current
        if trace:
            new=state(r)
            if new!=old:points.add(k);old=new
        if ((idle_end and r.c.csp==0 and r.c.ip==0xe800) or (not idle_end and r.c.ip==0xfffe)) and (inject is None or k>=inject and lost):return points,k+1,minimum,sysmin,lost,bad
    raise AssertionError('call failed to return')

def main():
    print(I.STEM,I.sha256())
    base=D.Rig();base.prime_real_sync_loss()
    staged=copy.deepcopy(base);staged.call('hc_drysched_service',3000,3);staged.cancel()
    staged.call('hc_drysched_tooth',0,3000,1000);staged.call('hc_drysched_service',3000,3);staged.idle()
    staged.call('hc_drysched_test_anchor',0);staged.idle()
    scenarios=[('publication',base,'hc_deadline_publish',(3,1,1000,5000),False),
               ('angle staging',staged,'hc_drysched_schedule_after',(1800,1,1),False)]
    dispatch=copy.deepcopy(base)
    dispatch.publish(1,1,5000,4000,absolute=True);dispatch.publish(3,1,5000,4000,absolute=True)
    for _ in range(50000):
        dispatch.c.step()
        if ((dispatch.c.csp<<16)|dispatch.c.ip)==P.sym('hc_cc25_isr'):break
    else:raise AssertionError('CC25 did not enter')
    scenarios.append(('ON dispatch',copy.deepcopy(dispatch),None,(),True))
    execute(dispatch,20000,idle_end=True)
    for _ in range(70000):
        dispatch.c.step()
        if ((dispatch.c.csp<<16)|dispatch.c.ip)==P.sym('hc_cc25_isr'):break
    else:raise AssertionError('closing CC25 did not enter')
    scenarios.append(('OFF dispatch',dispatch,None,(),True))
    failures=0;count=0;user_min=D.Rig().stack_top;system_min=0xf700
    for name,prepared,fn,args,idle_end in scenarios:
        probe=copy.deepcopy(prepared)
        if fn:setup_call(probe,fn,args)
        points,used,umin,smin,*_=execute(probe,20000,trace=True,idle_end=idle_end)
        assert points, name+' fixture did not exercise a mutation'
        positions=sorted({p+d for p in points for d in (-1,0,1) if 0<=p+d<used})
        for offset in positions:
            r=copy.deepcopy(prepared)
            if fn:setup_call(r,fn,args)
            _,_,umin,smin,lost,bad=execute(r,40000,inject=offset,idle_end=idle_end)
            before=r.dirs();r.idle();r.run(12000)
            # 2026-10-12: the crank position WITHDRAWN (trg_state below crank
            # sync), not trg_synclost: since the stop-time fix (2026-10-11) the
            # counter moves only after the crank has run another revolution,
            # and this rig stops after the loss (me711_runtime_fault_proof S1b
            # checks the count).
            ok=(r.u8('trg_state')<3 and r.u16('hc_dl_generation')!=prepared.u16('hc_dl_generation') and r.dirs()==(0,0,0) and not bad)
            # Owned OFF deadlines survive normal withdrawal. Only a newly
            # asserted command after withdrawal is forbidden during the stall.
            for _,_,ports in r.log:
                if any(new&~old for old,new in zip(before,ports)):ok=False
                before=ports
            if r.u8('hc_dl_on_ign') or r.u8('hc_dl_on_inj'):ok=False
            failures+=not ok;count+=1;user_min=min(user_min,umin);system_min=min(system_min,smin)
            if not ok:print('[FAIL]',name,offset,lost,bad,r.dirs(),r.log)
        print(f"{name}: {len(points)} mutations / {len(positions)} adjacent boundaries, {used} instructions; tested")
    print(f"boundary cases {count-failures}/{count}; observed user stack {base.stack_top-user_min} bytes, system stack {0xf700-system_min} bytes")
    return int(bool(failures))
if __name__=='__main__':raise SystemExit(main())
