"""Observe linked task + CC25 + higher priority terminal ISR stack use.

This checks actual generated prologues/RETI against the linker allocation.
It is a bounded fixture, not a proof of every possible application call chain.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_deadline_proof as D
import me711_trigger_test as P
import me711_image as I
from me711_stack_proof import system_stack

def main():
    print(I.STEM,I.sha256())
    r=D.Rig();r.publish(1,1,5000,4000,absolute=True)
    sys_bot,sys_top=system_stack()
    system_origin=r.m.r16(0xfe12)
    minimum=[r.stack_top,system_origin];injected=[False]
    original=r.c.step
    arm=P.sym('hc_deadline_arm_f')
    def step():
        pc=(r.c.csp<<16)|r.c.ip
        if not injected[0] and pc==arm:
            r.m.w16(0xff72,0xf8);r.m.w16(0xff74,0xfc);injected[0]=True
        original()
        minimum[0]=min(minimum[0],r.c.gr(0));minimum[1]=min(minimum[1],r.m.r16(0xfe12))
    r.c.step=step
    r.publish(3,1,6000,4000,absolute=True);r.run(15000)
    user=r.stack_top-minimum[0];system=system_origin-minimum[1]
    D.check('higher priority SSC terminal interrupts preempt locked publication',injected[0] and r.c.irq_count.get(0x2d,0) and r.c.irq_count.get(0x2e,0),str(r.c.irq_count))
    D.check('observed task and nested IRQ stacks stay inside linker allocations',minimum[0]>=P.sym('?C_USRSTKBOT') and minimum[1]>=sys_bot,f'user {user}/{I.user_stack_size()} B, system depth {system} B from fixture SP {system_origin:04X}; allocated {sys_top-sys_bot} B')
    D.check('stack-stressed pulses close without task polling',r.dirs()==(0,0,0),str(r.log))
    print(f'{D.checks-D.fails}/{D.checks} PASS');return int(bool(D.fails))
if __name__=='__main__':raise SystemExit(main())
