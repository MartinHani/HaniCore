"""Focused linked-C167 characterization safety/profile proof. No hardware claims."""
import argparse,shutil,tempfile
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_dbw_control_proof as D
# Freeze the image/map pair: a concurrent build must never retarget live calls.
import me711_image as PI
snapshot=Path(tempfile.mkdtemp(prefix='hc_sweep_proof_'))
for attr in ('IMG','MAP','MANIFEST'):
    src=getattr(PI,attr); dst=snapshot/src.name; shutil.copy2(src,dst); setattr(PI,attr,dst)
print('IMAGE',PI.sha256(),flush=True)
ap=argparse.ArgumentParser();ap.add_argument('--case');ap.add_argument('--cases',nargs='+');args=ap.parse_args()
def check(label, value, detail=''):
    print(('PASS ' if value else 'FAIL ')+label+' '+str(detail),flush=True)
    assert value,label

def rig():
    r=D.Rig();r.baseline()
    r.set8('CAL_DBW_ENABLE',0)
    r.set16('CAL_DBW_SF_MODE',D.hdr_int(D.GEN_H,'HC_DBW_SF_LOW_IS_FAULT'))
    r.mem.sfr[0xffc4]|=0x8000
    r.set16('CFG_U_DBW_DEADBAND_X10',0)
    r.set16('CAL_DBW_DEV_MS',5000)
    r.plate(100)
    r.service(1000);r.service(1005)
    # No physical pedal source. Invalid APP calibration is also permitted.
    r.set16('CAL_PEDAL1_MAX',100)
    r.stale.update((D.ADC_APP1,D.ADC_APP2))
    r.mem.w8(D.sym('trg_state')&65535,0)
    return r

def val(r,i):return r.call('hc_etbcal_value',(i,))
def status(r):return r.call('hc_etbcal_status')
def page(r):
    return tuple(r.mem.r8(r.page_addr(i)) for i in range(4096))

cases=['normal','abort','stale','pair','range','bridge','key','output','rpm','crank','timeout','uncal','rate']
for case in (args.cases or ([args.case] if args.case else cases)):
    r=rig();before=page(r)
    if case=='uncal':r.set16('CAL_TPS1_MAX',100);before=page(r)
    if case=='rate':r.set16('CFG_U_DBW_RATE_X10',250);before=page(r)
    r.call('hc_etbcal_request',(6,))
    seen=set();directions=set();requested=set();rate_gap=False
    # 59 dynamic segments (~63 s) then the break-away phase: give it 150 s.
    for ms in range(1010,151020,5):
        oldtarget=r.call('hc_dbw_target_x10')
        r.plate(oldtarget) # coherent ideal follower; classifier plant tests are separate
        age=ms-1010
        if age>=1000 and case not in ('normal','rate','uncal'):
            if case=='abort':r.call('hc_etbcal_request',(0,))
            elif case=='stale':r.stale.update((D.ADC_TPS1,D.ADC_TPS2))
            elif case=='pair':r.set_adc(D.ADC_TPS2,900)
            elif case=='range':r.set_adc(D.ADC_TPS1,1023)
            elif case=='bridge':r.mem.sfr[0xffc4]&=~0x8000
            elif case=='key':r.mem.sfr[0xffcc]&=~4
            elif case=='output':r.mem.w8(D.sym('hc_dbw_allowed')&65535,0)
            elif case=='crank':r.mem.w8(D.sym('trg_state')&65535,1)
        rpm=100 if case=='rpm' and age>=1000 else 0
        if case=='timeout' and age>=1000:ms=62000
        r.service(ms,rpm=rpm)
        s=status(r)
        if age%25==0:
            segment=val(r,20);seen.add(segment)
            if r.call('hc_dbw_bridge_on')&255:directions.add(r.call('hc_dbw_dir')&255)
            if segment>=38:
                demand=r.call('hc_dbw_pedal_x10');requested.add(demand)
                rate_gap|=abs(val(r,8)-r.call('hc_dbw_target_x10'))>10
        if (s&15) in (3,7):break
    check(case+' exits',s&15==(7 if case in ('normal','rate') else 3),hex(s))
    check(case+' bridge OFF',(r.call('hc_dbw_bridge_on')&255)==0 and r.call('hc_dbw_duty_x10')==0,r.s())
    check(case+' no calibration/PID writes',page(r)==before)
    # Verify the actual published split OCH buffer, not just its accessors.
    for part in (0,1,2):            # hc_io_publish(boost, part): every slice
        r.call('hc_io_publish',(0,part))
    for off,index in ((1522,30),(1524,31),(1526,32),(1528,33)):
        address=D.EXTRAM+D.hdr_int(D.HDR,'TGT_RAM_OCH2')+off-1024
        got=(r.mem.r8(address)<<8)|r.mem.r8(address+1)
        check(case+' published summary '+str(index),got==val(r,index),(got,val(r,index)))
    if case in ('normal','rate'):
        check(case+' all bounded/driver segments reached',seen.issuperset(range(1,60)),sorted(seen))
        check(case+' break-away phase ran (telemetry 60+)',any(x>=60 for x in seen),sorted(x for x in seen if x>=60))
        check(case+' both physical motor directions',directions=={0,1},directions)
        check(case+' normalized 0 and 100% APP demands used',requested.issuperset({0,1000}),requested)
    if case=='rate':
        check('production rate limit retained',rate_gap and val(r,31)&128,(rate_gap,val(r,31)))
    if case=='abort':
        r.set8('CAL_DBW_ENABLE',1);r.stale.clear();r.set16('CAL_PEDAL1_MAX',900)
        for later in range(5000,5100,5):r.service(later)
        check('normal DBW cannot restart after abort',(r.call('hc_dbw_bridge_on')&255)==0)
print('PASS focused linked characterization cases',flush=True)
