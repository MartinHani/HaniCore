"""Compare complete linked engine-service results with the frozen exact V101.

Both workers receive the same ADC completion fixtures and legacy calibration.
New policy diagnostics are intentionally separate from fuel/advance results.

2026-10-12: THE THROTTLE LOAD CHANGED ON PURPOSE for the throttle load
sources (1 alpha-N x pressure, 2 pure alpha-N). V101 fuelled from the 1/16-
per-pass filtered throttle (a second, unstable lag - the car's quick-press
stumble); the image now takes the throttle itself through the FR BGSRM
filling model (hcengctl711.c hc_ec_load_lag, me711_tipin_fill_proof). For
those sources the transient frames differ by design, so they are compared
ONCE V101's filter has settled (SETTLE passes): the same fuel, advance and
every other field for the same settled throttle. Source 0 (speed density)
still matches frame by frame.
"""
import json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

SETTLE = 140      # V101's 1/16 filter: 312 * (15/16)^140 < 0.1 count
THROTTLE_LOAD = (1, 2)


def worker():
    import me711_config_state_test as C
    import me711_image as I
    results=[]
    for source in range(3):
      for faults in ((),(14,),(6,),(1,3)):
       for rpm in (200,3000):
        r=C.Rig()
        for fn in ('hc_cfg_init','hc_cfg_mgr_init','hc_hal_init','hc_fresh_init','eng_init','hc_ec_init','hc_trans_init'):
            r(fn)
        r('hc_cal_set_u8',C.O['CAL_LOAD_SOURCE'],source)
        tick=C.sym('hc_tick_ms')&65535;adc=C.sym('adc_raw')&65535
        for sem,ch in ((0,5),(1,0),(2,6),(3,14),(4,1),(5,3),(6,8),(7,9)):
            r('hc_fresh_bind',sem,ch)
        r.m.w16(C.sym('trg_rpm')&65535,rpm)
        r.m.w8(C.sym('trg_state')&65535,3)
        frame=[]
        for k in range(SETTLE):
            ms=20*(k+1);r.m.w16(tick,ms)
            for ch,v in ((5,650),(0,400),(6,400),(14,600),(1,350),(3,650),(8,350),(9,650)):
                r.m.w16(adc+2*ch,v);r('hc_hal_main_sample',ch,(ch<<12)|v,int(ch not in faults),ms)
            r('eng_service')
            names=('eng_sensor_err','eng_air_mg_x10','eng_rl_x10','eng_ve_x10','eng_ve_load_x10','eng_load','eng_ti_base_us','eng_ti_us','eng_deadtime_us','eng_dwell_x100','eng_adv_x10','eng_warmup_pct','eng_fuelcut')
            if k < 10 or k == SETTLE - 1:
                frame.append([r.g16(n) for n in names])
        results.append([source,list(faults),rpm,frame])
    print(json.dumps({'sha256':I.sha256(),'results':results}))

def main():
    if '--worker' in sys.argv:worker();return 0
    rows=[]
    for stem in ('HaniCore_ME711_v101_dev','HaniCore_ME711_v102_dev'):
        env=dict(os.environ,HANICORE_ME711_STEM=stem)
        p=subprocess.run([sys.executable,__file__,'--worker'],env=env,capture_output=True,text=True)
        if p.returncode:print(p.stdout,p.stderr);return 1
        rows.append(json.loads(p.stdout));print(stem,rows[-1]['sha256'])
    a,b=rows
    # Diagnostics added after V101 are policy, not engine results: the TPS
    # pair check (eng_sensor_err 0x0040) flags this fixture's two tracks.
    # Every other field, and every other error bit, must match exactly.
    NEW_DIAG=0x0040
    def norm(res):
        fr=[[f[0]&~NEW_DIAG]+f[1:] for f in res[3]]
        if res[0] in THROTTLE_LOAD:
            fr=fr[-1:]               # the settled frame only (see the top)
        return [res[0],res[1],res[2],fr]
    bad=[i for i,(old,new) in enumerate(zip(a['results'],b['results'])) if norm(old)!=norm(new)]
    print(f"Legacy engine-service cases {len(a['results'])-len(bad)}/{len(a['results'])}, ten complete frames each (throttle-load sources: the settled frame)")
    for i in bad:print('FAIL',i,a['results'][i],b['results'][i])
    return int(bool(bad))
if __name__=='__main__':raise SystemExit(main())
