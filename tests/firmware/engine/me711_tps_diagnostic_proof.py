"""Calibration fault reasons exercised in the linked firmware."""
from pathlib import Path
import argparse,sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
p=argparse.ArgumentParser()
p.add_argument('--source-root',type=Path,default=Path(__file__).resolve().parents[3])
a=p.parse_args();sys.path.insert(0,str(a.source_root.resolve()/'tools'))
import me711_etb_autocal_proof as E
import me711_image as PI
print('LINKED IMAGE',PI.image(),PI.sha256(),flush=True)
b=E.Bench()
n=0
for mode,why,bit in (('source',11,128),('never',30,128),('rejected',27,128),
                     ('stale',26,128),('rail',4,16),('pair',17,4)):
    b.r('hc_dbw_init');b.r('hc_fresh_init')
    b.ms=2000;b.r.m.w16(E.T.sym('hc_tick_ms')&65535,b.ms)
    b.r('hc_fresh_bind',4,1);b.r('hc_fresh_bind',5,3)
    b.adc_set(1,500);b.adc_set(3,500);b.adc_set(5,767)
    if mode=='source':b.r('hc_fresh_bind',4,255)
    if mode=='never':b.r('hc_fresh_init');b.adc_set(3,500);b.adc_set(5,767)
    if mode=='rejected':b.r('hc_hal_main_sample',1,0x3000|500,1,b.ms)
    if mode=='stale':b.ms+=101
    if mode=='rail':b.adc_set(1,0)
    if mode=='pair':
        for name,v in (('CAL_TPS1_MIN',102),('CAL_TPS1_MAX',954),
                       ('CAL_TPS2_MIN',919),('CAL_TPS2_MAX',71),
                       ('CFG_U_TPS_TOL_X10',50)):
            b.r('hc_cal_set_u16',E.AP.off(name),v)
        b.r('hc_cal_set_u8',E.AP.off('CFG_U_TPS_CORR'),1)
        b.adc_set(3,800)
    b.r.m.w16(E.T.sym('hc_tick_ms')&65535,b.ms)
    b.cmd(2 if mode=='pair' else 1)
    b.r('hc_dbw_service',b.ms,0,1)
    b.ms+=5;b.r.m.w16(E.T.sym('hc_tick_ms')&65535,b.ms)
    b.r('hc_dbw_service',b.ms,0,1)
    st=E.status(b.r)
    ok=st==(3,0,why) and b.released() and b.r('hc_dbw_faults')&bit
    n+=1;print(('PASS ' if ok else 'FAIL ')+mode+' '+str(st),flush=True)
    assert ok,(mode,st,b.r('hc_dbw_faults'))
    frozen=[b.r('hc_etbcal_value',i) for i in (22,23,24)]
    b.adc_set(1,500);b.adc_set(3,500);b.r('hc_fresh_service')
    ok=E.status(b.r)==st and [b.r('hc_etbcal_value',i) for i in (22,23,24)]==frozen
    n+=1;print(('PASS ' if ok else 'FAIL ')+'fresh samples retain failure evidence '+str(frozen),flush=True)
    assert ok
print('PASS',n,'TPS diagnostic checks',flush=True)
