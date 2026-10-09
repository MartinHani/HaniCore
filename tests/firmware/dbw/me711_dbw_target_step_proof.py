from pathlib import Path
import argparse,sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
ROOT=Path(__file__).resolve().parents[3]
ap=argparse.ArgumentParser()
ap.add_argument('--source-root',type=Path,default=ROOT)
ap.add_argument('--baseline',action='store_true')
args=ap.parse_args()
sys.path.insert(0,str(args.source_root.resolve()/'tools'))
import me711_dbw_control_proof as D
import me711_image as PI
baseline=args.baseline
if baseline:
    old=hcpaths.RAW_EVIDENCE/'DBW_CAL_CONTROL_REVISION/HaniCore_ME711_dbw_revision_bench'
    PI.IMG=old.with_suffix('.bin'); PI.MAP=old.with_suffix('.M66')
    PI.MANIFEST=old.with_suffix('.json')

def signed(v): return v-65536 if v&32768 else v
def term(r,n): return signed(r.call('hc_dbw_term',(n,)))
def check(label,ok,data):
    print(('PASS ' if ok else 'FAIL ')+label+' '+str(data),flush=True)
    assert ok

print('IMAGE',PI.sha256(),flush=True)
r=D.Rig(); r.baseline()
r.set16('CAL_DBW_KP',5750); r.set16('CAL_DBW_KI',45635)
r.set16('CAL_DBW_KD',23658); r.set16('CFG_U_DBW_DEADBAND_X10',0)
r.call('hc_dbw_override',(500,)); r.plate(500)
for ms in range(10000,10050,5):r.service(ms)
for target in (200,600,200,40,150):
    r.call('hc_dbw_override',(target,)); r.service(ms+5); ms+=5
    value=term(r,1)
    check('old target jump kicks' if baseline else 'stationary plate target jump has no derivative kick',
          value!=0 if baseline else value==0,(target,value))
    # Move the input by 5% with a constant target. Derivative must brake it.
    r.plate(550); r.service(ms+5); ms+=5
    value=term(r,1)
    check('opening plate receives closing derivative',value<0,value)
    r.plate(500); r.service(ms+5); ms+=5
    value=term(r,1)
    check('closing plate receives opening derivative',value>0,value)
r.call('hc_dbw_shutdown',(0,))
check('release zeroes derivative and integral',term(r,1)==0 and r.s()['integ']==0,r.s())
print('PASS controller target-step regressions',flush=True)

r.baseline(); r.set16('CAL_DBW_KP',500); r.set16('CAL_DBW_KI',10000)
r.set16('CAL_DBW_KD',0); r.set16('CFG_U_DBW_DEADBAND_X10',0)
r.call('hc_dbw_override',(550,)); r.plate(500)
for ms in range(20000,21000,5):r.service(ms)
r.set16('CAL_DBW_KP',5750); r.set16('CAL_DBW_KI',45635)
r.call('hc_dbw_override',(200,)); r.service(21000)
before=r.s()
r.service(21005); after=r.s()
check('old closing saturation winds positive integral' if baseline else 'closing saturation freezes positive integral',
      before['duty']==800 and before['integ']>0
      and (after['integ']<before['integ'] if baseline else after['integ']==before['integ']),
      (before,after))

if not baseline:
    r.baseline();r.set16('CAL_DBW_KP',0);r.set16('CAL_DBW_KI',0)
    r.set16('CAL_DBW_KD',1000);r.set16('CFG_U_DBW_DEADBAND_X10',0)
    r.call('hc_dbw_override',(500,));r.plate(500)
    for ms in range(30000,30050,5):r.service(ms)
    r.plate(550);r.service(30065)
    check('derivative uses a 20 ms acquisition interval',term(r,1)==-12,term(r,1))
    r.stale.update((D.ADC_TPS1,D.ADC_TPS2));r.service(30070)
    check('cached pair retains velocity without re-differentiating',term(r,1)==-12,term(r,1))
    r.stale.clear();r.service(30075)
    check('new stationary acquisition zeros velocity',term(r,1)==0,term(r,1))
    r.set16('CAL_DBW_KD',65535);r.plate(0);r.service(30080)
    check('native derivative division clamps before quotient overflow',term(r,1)==32000,term(r,1))

if not baseline:
    r.baseline();r.set16('CAL_DBW_KP',500);r.set16('CAL_DBW_KI',45635)
    r.set16('CAL_DBW_KD',0);r.set16('CFG_U_DBW_DEADBAND_X10',0)
    r.call('hc_dbw_override',(500,));r.plate(500)
    for ms in range(40000,40050,5):r.service(ms)
    r.call('hc_dbw_override',(200,));r.service(40050)
    for ms,position in zip(range(40055,40075,5),(450,400,350,300)):
        r.plate(position);r.service(ms)
    check('large moving step preserves holding integral',r.s()['integ']==0,r.s())
    for ms in range(40075,40125,5):r.service(ms)
    check('stationary large error resumes integral after bounded wait',r.s()['integ']<0,r.s())
    r.plate(230);r.service(40125);before=r.s()['integ'];r.service(40130)
    check('near-target error continues integral recovery',r.s()['integ']<before,(before,r.s()))
