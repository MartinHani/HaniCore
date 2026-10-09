"""Linked C167 load/protection contracts. Injected samples are not hardware qualification."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_config_state_test as C
import me711_image as I

checks=fails=0
def check(name,ok,detail=''):
    global checks,fails
    checks+=1;fails+=not ok
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
O=lambda name:C.d(C._gen,'CFG_U_'+name)
BASE=0x381f00
NAMES='model role policy pressure pressure_age pressure_ok ambient ambient_source ambient_valid ambient_age_s effective ratio blend temperature axis flags last_ms dt_ms stopped_ms ambient_rem_ms lean_ms recovery_ms lean_latched lean_eligible lambda'.split()
class Rig(C.Rig):
    def __init__(self):
        super().__init__();self('hc_cfg_init');self('hc_cfg_mgr_init');self('hc_hal_init');self('hc_fresh_init')
        self('hc_fresh_bind',3,14);self('hc_load_init');self.ms=0
        self.put('eng_tps_x10',500);self.put('eng_rl_x10',1000);self.put('eng_iat_dc',10200)
    def put(self,n,v):self.m.w16(C.sym(n)&0xffff,v)
    def cfg(self,n,v,byte=False):self('hc_cal_set_u8' if byte else 'hc_cal_set_u16',O(n),v)
    def val(self,n):return self.m.r16(BASE+2*NAMES.index(n))
    def step(self,pressure=1000,rpm=3000,tps=500,valid=True,dt=20):
        self.ms=(self.ms+dt)&65535;self.put('hc_tick_ms',self.ms)
        self('hc_hal_main_sample',14,0xe000|500,1,self.ms)
        self.put('eng_sensor_err',0 if valid else C.d((C.SHARED/'engine/hcengine.h').read_text(),'ENG_ERR_MAP'));self.put('eng_map_kpa_x10',pressure if valid else 0)
        self.put('eng_tps_x10',tps);self('hc_load_select',rpm,tps)
    def model(self,model,role,policy):
        for n,v in [('FUEL_MODEL',model),('PRESSURE_ROLE',role),('DENSITY_POLICY',policy)]:self.cfg(n,v,True)

def main():
    print(I.STEM,I.sha256())
    r=Rig();r.model(1,0,0);r.step(valid=False)
    check('Pure Alpha-N requires no pressure input',r.val('effective')==1013 and r.val('axis')==500 and not(r.val('flags')&3),str([r.val(n) for n in ['effective','axis','flags']]))
    r('hc_load_protect',3000,1000);check('Pure Alpha-N pressure fault does not cut base fuel',not(r.g16('eng_fuelcut')&16))
    r.model(2,1,1);r.step(1800)
    check('Manifold SD uses measured manifold for axis and density once',r.val('effective')==1800 and r.val('axis')==1800 and r.val('pressure_ok')==1)
    r.model(2,2,1);v=r('hc_validate',0)
    check('Manifold SD refuses pre-throttle role',bool(v&C.VAL['HC_VAL_FAULT_STRATEGY']),hex(v))
    r.model(3,2,1);r.step(1800)
    check('Continuous charge Alpha-N uses TPS axis and upstream density',r.val('effective')==1800 and r.val('axis')==500)
    vals=[]
    for p in (600,1000,2000,4000):
        r.step(p);rho=r('hc_af_density_x1000',r.val('effective'),r.val('temperature'));vals.append(rho)
    check('Continuous pressure produces linear density, no pressure squared',abs(vals[2]/vals[1]-2)<.01 and abs(vals[3]/vals[1]-4)<.01,str(vals))
    r.model(3,2,2);r.cfg('BARO_SOURCE',1,True)
    for _ in range(51):r.step(900,rpm=0)
    check('Stopped valid pressure capture has explicit ambient provenance',r.val('ambient')==900 and r.val('ambient_source')==1 and r.val('ambient_valid')==1)
    results=[]
    for p in (899,900,949,950,951,1050,1149,1150,1151):
        r.step(p);results.append((p,r.val('effective'),r.val('blend')))
    reference=lambda p:900+max(p-900,0)*min(max((p-900-50)/200,0),1)
    check('Finite BARO-relative blend matches continuous independent reference',results[3][1]==900 and results[7][1]==1150 and all(abs(e-reference(p))<1.01 for p,e,w in results),str(results))
    r.cfg('BLEND_FULL',50);check('Equal blend thresholds are rejected',bool(r('hc_validate',0)&C.VAL['HC_VAL_FAULT_STRATEGY']))
    r.step(1050);check('Bad ordering cannot divide or emit a valid new model',r.val('effective')==0 and r.val('flags')&1)
    r.cfg('BLEND_FULL',250);r.cfg('BARO_MAX_AGE',1)
    for _ in range(52):r.step(1200,rpm=3000)
    check('Stopped ambient capture expires terminally into fixed fallback',r.val('ambient_valid')==0 and r.val('ambient_source')==0 and r.val('ambient')==1013)
    for _ in range(700):r.step(1200,rpm=3000,dt=100)
    check('Millisecond wrap cannot resurrect expired BARO',r.val('ambient_valid')==0 and r.val('ambient_source')==0)
    r.cfg('BARO_SOURCE',2,True);r.step(2000)
    check('Unqualified dedicated HOG is never authoritative',r.val('ambient_valid')==0 and r.val('ambient')==1013 and r.val('flags')&4)
    r.model(3,2,1);r.step(valid=False);r('hc_load_protect',3000,1000)
    check('Lost authoritative pressure cuts fuel under load',bool(r.g16('eng_fuelcut')&16))
    r.step(1013);r('hc_load_protect',3000,1000)
    check('Atmospheric valid pressure is distinguished from missing pressure',not(r.g16('eng_fuelcut')&16) and r.val('pressure_ok')==1)
    r('hc_boost_init');a=C.sym('hc_ldr')&65535
    r.m.w16(a+10,800);r.step(valid=False)
    check('Pressure loss revokes cached N75 duty before 20 ms cadence',r('hc_boost_service',1,0)==0 and r.m.r16(a+10)==0)
    r.model(1,0,0);r.step(1013);r.m.w16(a+10,800)
    check('No pressure role cannot carry boost authority in new fuel models',r('hc_boost_service',2,0)==0)
    r.model(3,2,1);r.step(1500);r.put('eng_fuelcut',32);r.m.w16(a+10,800)
    check('Lean torque cut revokes cached N75 duty immediately',r('hc_boost_service',3,0)==0)
    r.put('eng_fuelcut',0)
    r.cfg('LEAN_ENABLE',1,True);r.cfg('LAMBDA_QUALIFIED',0,True)
    for _ in range(30):r.step(1500);r('hc_load_protect',3000,1000)
    check('Unqualified lambda cannot trigger lean guard',r.val('lean_eligible')==0 and r.val('lean_latched')==0)
    r.cfg('LAMBDA_QUALIFIED',1,True)
    for _ in range(30):r.step(1500);r('hc_load_protect',3000,1000)
    check('Cold / unavailable lambda remains ineligible despite commissioning switch',r.val('lean_eligible')==0 and r.val('lean_latched')==0)
    # Actual linked decision core; nonzero input explicitly represents the
    # stricter acquisition provider's injected eligible measurement.
    for _ in range(14):r.step(1500);r('hc_load_lean_step',3000,1000,1150)
    check('Eligible lean deviation does not trip before persistence',r.val('lean_latched')==0 and r.val('lean_ms')==280)
    r.step(1500);r('hc_load_lean_step',3000,1000,1150)
    check('Eligible persistent lean trips at calibrated duration',r.val('lean_latched')==1)
    for _ in range(60):r.step(1500,tps=0);r('hc_load_lean_step',3000,1000,0)
    check('Stale / invalid signal cannot release a latched guard',r.val('lean_latched')==1 and r.val('recovery_ms')==0)
    for _ in range(49):r.step(1500,tps=0);r('hc_load_lean_step',3000,1000,990)
    check('Fresh unloaded recovery requires complete recovery duration',r.val('lean_latched')==1)
    r.step(1500,tps=0);r('hc_load_lean_step',3000,1000,990)
    check('Fresh unloaded recovered lambda releases guard',r.val('lean_latched')==0)
    r.step(1500,dt=400);r('hc_load_lean_step',3000,1000,1150)
    check('Task gap cannot count as continuously lean observation',r.val('lean_ms')==0 and r.val('lean_eligible')==0)
    r('hc_load_publish');r('hc_deadline_publish_diag')
    ochbase=0x380000+C.d(C._tgt,'TGT_RAM_OCH2')
    raw=lambda off:int.from_bytes(bytes(r.m.r8(ochbase+off-1024+i) for i in range(2)),'big')
    check('OCH values follow the actual linked load state',raw(1400)==2 and raw(1418)==1500 and raw(1442)==0)
    print(f'{checks-fails}/{checks} PASS');return int(bool(fails))
if __name__=='__main__':raise SystemExit(main())
