"""Linked V102 widths, flash admission, full board routing and IRQ priority.

Explicit eight-instruction/tick command timing; terminal SSC interrupts are
real target handlers. This does not model a complete physical PEC exchange.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_deadline_proof as D
import me711_trigger_test as P
import me711_image as I

def all_routes(r):
    for off,values in [(2551,[96,97,88,89,112,113,24,19]),(2563,[102,103,94,95,110,111,8,7])]:
        for b,v in enumerate(values+[255]*4):r.m.w8(0x38000c+off+b,v)
    a=P.sym('hc_cfg_active_rev')&65535;r.m.w16(a,(r.m.r16(a)+1)&65535)
    r.call('hc_hal_out_group',0,255,0);r.call('hc_hal_out_group',8,255,0)
    r.idle()

def main():
    print(I.STEM,I.sha256())
    r=D.Rig();r.publish(3,1,1000,5000)
    D.check('flash write guard rejects near armed deadline',not (r.call('hc_deadline_flash_admit',1375)&255))
    r=D.Rig();r.publish(3,1,5000,5000)
    D.check('flash write guard admits adequate deadline margin',bool(r.call('hc_deadline_flash_admit',1375)&255))
    r.cancel();D.check('empty engine queue admits live word guard',bool(r.call('hc_deadline_flash_admit',1375)&255))
    for rpm,cycle in [(6000,3600),(9000,7200),(12000,3600)]:
        r=D.Rig();period=round(1250000/rpm)*cycle//60
        # Actual task width metadata and publisher; deliberately high duty.
        ticks=r.call('hc_deadline_inj_request',1,50000,1000,period&65535,period>>16)
        # C167 returns unsigned long in r4/r5.
        ticks=r.c.gr(4)|(r.c.gr(5)<<16)
        width=ticks-(ticks+4)//5
        # the OFF separation is reserved on both sides of the pulse within its
        # repetition period (hcdeadline_plan711.c: period - 2 x HC_DL_OFF_TICKS)
        off=int(__import__('re').search(r'#define\s+HC_DL_OFF_TICKS\s+(\d+)u',
            (I.ROOT/'firmware/targets/me711/engine/hcdeadline711.h').read_text()).group(1))
        D.check(f'{rpm} RPM width reserves 2 x {off*4//5} us OFF separation',ticks==period-2*off and r.m.r16(D.DIAG+38+16)&2,str((ticks,period)))
        ticket=r.publish(3,1,2000,width)
        r.call('hc_deadline_inj_admitted',1,ticket,r.u16('hc_dl_generation'),ticks&65535,ticks>>16);r.idle()
        D.check(f'{rpm} RPM accepted width reflects clipped schedule',(r.m.r16(0x387290)|(r.m.r16(0x387292)<<16))==width)
        r.run(2000+ticks+2500)
        D.check(f'{rpm} RPM delivered width reflects commanded interval',abs((r.m.r16(0x3872b0)|(r.m.r16(0x3872b2)<<16))-width)<100,str((r.m.r16(0x3872b0)|(r.m.r16(0x3872b2)<<16))))
    r=D.Rig();all_routes(r)
    r.publish(1,255,5000,4000,absolute=True);r.publish(3,255,5000,4000,absolute=True);r.run(5000)
    D.check('eight coil and injector channels command exact board ports',r.dirs()==(255,0x70,0xf8),str(r.log))
    D.check('full board burst command error <=100 us',r.log and max(t-5000 for _,t,ports in r.log)<=125,str(r.log))
    r.run(6000);D.check('full board burst releases all channels without task service',r.dirs()==(0,0,0))
    D.check('full board release burst command error <=100 us',r.log and all(t-10000<=125 for _,t,ports in r.log if t>=10000),str(r.log))
    # Arm real SSC terminal priorities just before CC25; preserve vector flow.
    r=D.Rig();r.publish(3,1,5000,1000,absolute=True)
    r.m.w16(0xff72,0x78);r.m.w16(0xff74,0x7c)
    while r.m.r16(0xf050)<5000:r.c.step()
    r.m.w16(0xff72,0xf8);r.m.w16(0xff74,0xfc)
    r.run(4000)
    D.check('SSC receive/transmit terminal IRQs retain priority above CC25',r.c.irq_count.get(0x2e,0)>0 and r.c.irq_count.get(0x2d,0)>0,str(r.c.irq_count))
    D.check('SSC preemption cannot strand injector command',r.dirs()==(0,0,0),str(r.log))
    print(f'{D.checks-D.fails}/{D.checks} PASS');return int(bool(D.fails))
if __name__=='__main__':raise SystemExit(main())
