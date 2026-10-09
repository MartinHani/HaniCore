"""Linked firmware TPS timing/source/serial acquisition regression."""
from pathlib import Path
import argparse
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
p=argparse.ArgumentParser()
p.add_argument('--source-root',type=Path,default=Path(__file__).resolve().parents[3])
a=p.parse_args()
sys.path.insert(0,str(a.source_root.resolve()/'tools'))
import me711_etb_autocal_proof as E
import me711_image as PI
import me711_dbw_control_proof as DC
n=0
def check(label,ok,detail=''):
    global n
    n+=1
    print(('PASS ' if ok else 'FAIL ')+label+' '+str(detail),flush=True)
    assert ok,(label,detail)
def clock(b,ms):
    b.ms=ms&65535
    b.r.m.w16(E.T.sym('hc_tick_ms')&65535,b.ms)
def pair(b):
    ptr=E.AP.REQ+32
    ok=b.r.callb('hc_fresh_tps_pair',ptr,ptr+2,ptr+4)
    return ok,*(b.r.m.r16(ptr+i) for i in (0,2,4))
print('LINKED IMAGE',PI.image(),PI.sha256(),flush=True)
b=E.Bench()
b.r('hc_fresh_init')
clock(b,1000)
check('routed track with no conversion has NEVER reason',b.r.callb('hc_fresh_reason',4)==2)
b.adc_set(1,500);b.adc_set(3,500)
check('stationary pair at a common timestamp',pair(b)==(1,500,500,1000),pair(b))
seq=b.r('hc_hal_main_seq',4)
b.r('hc_hal_main_sample',1,0x3000|500,1,1000)
check('wrong channel tag invalidates without renewing generation',
      b.r.callb('hc_fresh_reason',4)==4 and b.r('hc_hal_main_seq',4)==seq and not pair(b)[0])
b.adc_set(1,500)
clock(b,1101)
check('stale track retains real age and rejects pair',
      b.r.callb('hc_fresh_reason',4)==3 and b.r('hc_hal_ain_age',4)==101 and not pair(b)[0])
b.r('hc_fresh_bind',4,255)
check('unconfigured TPS cannot become valid via another physical source',
      b.r.callb('hc_fresh_reason',4)==1 and b.r('hc_hal_ain_age',4)==65535)
b.r('hc_fresh_bind',4,1)

# Both tracks describe the SAME linear motion, with a 3 ms channel skew
# and a 16 ms revisit period. The latest raw values differ by > tolerance.
b.r('hc_fresh_init')
for i in range(5):
    t=2000+16*i
    clock(b,t);b.adc_set(1,150+10*(t-2000))
    clock(b,t+3);b.adc_set(3,850-10*(t+3-2000))
    aligned=pair(b)
    if i:
        check('rapid opposing movement aligns at older acquisition time',
              aligned[0]==1 and abs(aligned[1]+aligned[2]-1000)<=1
              and aligned[3]==t,aligned)
clock(b,2100);b.adc_set(1,600);b.adc_set(3,600)
check('real disagreement remains visible after alignment',
      pair(b)[0] and pair(b)[1]+pair(b)[2]==1200,pair(b))
clock(b,2110);b.adc_set(1,500);b.adc_set(3,500)
original=b.r.c.step
ticks=[0]
def interrupt_tick():
    result=original()
    ticks[0]+=1
    if ticks[0]==120:
        b.r.m.w16(E.T.sym('hc_tick_ms')&65535,2111)
    return result
b.r.c.step=interrupt_tick
try:aligned=pair(b)
finally:b.r.c.step=original
check('tick interrupt during alignment cannot change comparison time',
      aligned==(1,500,500,2110),aligned)

# Same acquired motion through the actual normal controller: raw endpoint
# calibration gives opposite slopes but both normalize to increasing position.
r=DC.Rig();r.baseline()
r.set16('CAL_TPS2_MIN',900);r.set16('CAL_TPS2_MAX',100)
r.set16('CFG_U_TPS_TOL_X10',25)
r.set16('CAL_DBW_DEV_MS',2000)
r.call('hc_fresh_init')
def sample(ch,raw,ms):
    r.mem.w16(DC.sym('hc_tick_ms')&65535,ms)
    r.call('hc_hal_main_sample',(ch,(ch<<12)|raw,1,ms))
def service(ms):
    for ch in (5,8,9):sample(ch,767 if ch==5 else 500,ms)
    r.call('hc_dbw_service',(ms,0,1))
    r.call('eng_service')
for i in range(12):
    t=10000+16*i
    pos=min(800,100+20*(t-10000))
    sample(1,100+pos*800//1000,t)
    # Three milliseconds of real movement gives a 6% latest-value error,
    # exceeding the 2.5% fixture tolerance without any physical mismatch.
    sample(3,900-min(800,pos+60)*800//1000,t+3)
    service(t+3)
check('moving time-aligned pair never trips normal controller',
      not r.s()['faults'] and r.s()['state']==2,r.s())
check('TunerStudio engine-side moving pair uses aligned comparison',
      not r.mem.r16(DC.sym('eng_sensor_err')&65535)&64)
sample(1,500,10200);sample(3,750,10200);service(10200)
check('genuine disagreement immediately disables bridge before debounce',
      r.s()['on']==0,r.s())
check('TunerStudio engine-side diagnostic detects real disagreement',
      r.mem.r16(DC.sym('eng_sensor_err')&65535)&64)
for t in range(10210,10370,10):
    sample(1,500,t);sample(3,750,t);service(t)
check('sustained disagreement latches TPS pair fault',r.s()['faults']&4,r.s())

# Run only the real serial yield; no direct calls renew samples or service
# DBW. Peripheral model completes each channel with its actual tag next ms.
# Reuse the fully booted main-loop CPU from the normal-controller fixture.
# T.Rig alone deliberately executes only injected functions and cannot arm
# hcmain's serial-yield startup gate.
adapter=E.T.Rig()
adapter.m,adapter.c=r.mem,r.cpu
# This fixture advances hc_tick_ms explicitly. Disable only the simulator's
# competing timer interrupt so it cannot advance that same clock mid-call
# and then be rewound by the next fixture millisecond. T1/SSC still run.
adapter.m.esfr[0xF17C]=adapter.m.esfr.get(0xF17C,0)&~0x40
adapter.c.irq_pending.discard(0xF17C)
old_boot=E.T.boot
E.T.boot=lambda:adapter
try:b=E.Bench()
finally:E.T.boot=old_boot
# The plant computes mechanics from actual GPIO/PWM. THE 1 MS TICK OWNS THE
# ADC (hcmain_me711.c adc_service): it completes one conversion per tick and
# publishes it through hc_hal_main_sample(). The tick interrupt is off in this
# fixture (it would fight the explicit clock), so each fixture millisecond
# publishes what the tick would: the TPS pair (AN1/AN3, 1 ms apart in the
# rotation) and the battery. Nothing in the serial yield samples any more.
b.adc_set=lambda *args,**kwargs:None
seen=set()
for ms in range(1000,4300):
    clock(b,ms)
    b.plant()
    # Match the operator's TPS PAIR OK precondition: complete a few real
    # sweeps before requesting motor ownership.
    if ms==1040:b.cmd(1)
    for ch,raw in ((1,round(102+852*b.pos)),(3,round(919-848*b.pos)),(5,767)):
        b.r('hc_hal_main_sample',ch,(ch<<12)|raw,1,ms)
    b.r('hcts_target_yield',steps=3_000_000)
    st=E.status(b.r)
    seen.add(st[1])
    if st[0]==3:break
    if st[1]==4 and ms>2900:break
print('SERIAL STATE',ms,seen,E.status(b.r),'faults',b.r('hc_dbw_faults'),
      'allowed',b.r.m.r8(E.T.sym('hc_dbw_allowed')&65535),flush=True)
check('the tick acquisition renews both TPS generations throughout',
      b.r('hc_hal_main_seq',4)>100 and b.r('hc_hal_main_seq',5)>100,
      (b.r('hc_hal_main_seq',4),b.r('hc_hal_main_seq',5)))
check('continuous acquisition survives DRIVE A and DRIVE B without pedal',
      {2,4}.issubset(seen) and E.status(b.r)[2] not in (11,26,27,28,29,30),
      (seen,E.status(b.r)))
# The acquisition stops (no conversion completes). The serial yield alone
# must not renew either track.
seqs=[b.r('hc_hal_main_seq',s) for s in (4,5)]
for ms in range(b.ms+1,b.ms+111):
    clock(b,ms);b.r.m.sfr[0xFFA0]|=0x100
    b.r('hcts_target_yield',steps=3_000_000)
check('without completed conversions neither track renews',
      seqs==[b.r('hc_hal_main_seq',s) for s in (4,5)])
check('genuinely stale acquisition releases bridge and reports STALE',
      b.released() and E.status(b.r)[2]==26 and b.r('hc_dbw_faults')&128,
      E.status(b.r))
check('failure ages and source reasons remain frozen',
      max(b.r('hc_etbcal_value',22),b.r('hc_etbcal_value',23))>100
      and b.r('hc_etbcal_value',24) in (3,48,51),
      (b.r('hc_etbcal_value',22),b.r('hc_etbcal_value',23),b.r('hc_etbcal_value',24)))
print('PASS',n,'TPS lifecycle checks',flush=True)
