"""Target planner geometry at high duty and accumulated task captures.

APIs use an explicit clock and actual CC25 interrupts. Geometry does not
establish CPU throughput: the separate instruction-budget gate remains strict.
FULL is a synthetic cycle input, never physical phase qualification.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_plan_cost_proof as C
import me711_trigger_test as P
import me711_config_state_test as CFG
import me711_deadline_proof as D
import me711_image as I

def main():
    print(I.STEM,I.sha256())
    for mode,state,label in ((0,3,'batch'),(1,3,'paired'),(2,3,'sequential fallback'),(2,4,'synthetic FULL')):
      for rpm in (6000,12000):
        r=C.planning_fixture(4);r.call('hc_drysched_cancel',0)
        off=CFG.d(CFG._gen,'CFG_U_INJ_STRATEGY');r.m.w8(0x38000c+off,mode)
        a=P.sym('hc_cfg_active_rev')&65535;r.m.w16(a,r.m.r16(a)+1)
        r.m.w8(P.sym('trg_state')&65535,state)
        for name,value in (('eng_ti_base_us',65535),('eng_deadtime_us',1000)):
            r.m.w16(P.sym(name)&65535,value)
        dt=round(1250000/rpm);stamp=r.m.r16(0xfe52)
        for tooth in range(240):
            stamp=(stamp+dt)&65535;r.set_t1(stamp)
            r.call('hc_drysched_tooth',tooth*60%7200,stamp,dt)
            r.call('hc_drysched_service',stamp,state)
        spans=[r.m.r16(0x3872f0+2*b) for b in range(4)]
        expected=[3600,3600,7200,7200] if mode==1 else [3600]*4
        D.check(f'{label} {rpm}: actual repeated-output interval is precomputed',spans==expected,str(spans))
        accepted=[r.m.r16(0x387290+4*b)|(r.m.r16(0x387292+4*b)<<16) for b in range(4)]
        limit=(dt*(7200 if state==4 else 3600)//60-125)*4//5
        D.check(f'{label} {rpm}: accepted electrical width respects its active repetition',max(accepted)>0 and all(v<=limit for v in accepted),str((accepted,limit)))
        D.check(f'{label} {rpm}: requested high duty is reported clipped',r.m.r16(D.DIAG+22)>0)
        r.call('hc_drysched_cancel',0);r.advance_deadlines(40000)
        D.check(f'{label} {rpm}: cancel cannot leave a physical command',not (r.m.r16(0xffc2)&255 or r.m.r16(0xffd2)&0x70 or r.m.r16(0xffd6)&0xf8))
    r=C.planning_fixture(4);before=r.u16('hc_dl_generation');stamp=r.m.r16(0xfe52)
    # A logger/serial task pause accumulates more captures than the bounded
    # ring. Actual overflow must withdraw ownership, not reuse stale captures.
    for tooth in range(16):
        stamp=(stamp+200)&65535;r.set_t1(stamp)
        r.call('hc_drysched_tooth',tooth*60,stamp,200)
    D.check('capture backlog revokes the execution generation',r.u16('hc_dl_generation')!=before)
    r.call('hc_drysched_cancel',0);r.advance_deadlines(40000)
    D.check('serial/task backlog cannot strand or restart old outputs',not (r.m.r16(0xffc2)&255 or r.m.r16(0xffd2)&0x70 or r.m.r16(0xffd6)&0xf8))
    print(f'{D.checks-D.fails}/{D.checks} PASS');return int(bool(D.fails))
if __name__=='__main__':raise SystemExit(main())
