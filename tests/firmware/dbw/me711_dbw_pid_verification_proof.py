"""Linked verification grader tests with prescribed coherent TPS traces.

The identification phase uses the existing simulated plant. Verification
uses explicit input traces to test acceptance, refusal and stale sources; it
does not claim that these traces model the physical throttle.

2026-10-11: NO DAMPING RETRIES. Each retry used to halve KP/KD and retest,
so the published gains were the relay rule /1, /2, /4 or /8 depending on the
run (the owner's "P 1.x one time, 3.x the next"). The candidate now carries
ONE fixed derating and the verify accepts it or refuses it: one candidate,
never a second; a refusal publishes nothing.
"""
from pathlib import Path
import argparse,sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
ap=argparse.ArgumentParser()
ap.add_argument('--source-root',type=Path,default=Path(__file__).resolve().parents[3])
ap.add_argument('--case',choices=['clean','one_overshoot','all_overshoots','stale','unsettled'])
args=ap.parse_args()
sys.path.insert(0,str(args.source_root.resolve()/'tools'))
import me711_etb_autocal_proof as E
import me711_image as PI
checks=0
def check(label,ok,data):
 global checks
 checks+=1;print(('PASS ' if ok else 'FAIL ')+label+' '+str(data),flush=True)
 assert ok,label
print('IMAGE',PI.sha256(),flush=True)
for mode in ([args.case] if args.case else ('clean','one_overshoot','all_overshoots','stale','unsettled')):
 b=E.Bench();old=b.plant;gains=[];start=[None];oldstep=[0];injected=[0]
 original=[b.u16d(E.AP.off(n)) for n in ('CAL_DBW_KP','CAL_DBW_KI','CAL_DBW_KD')]
 # This fixture supplies its own 1 ms clock; prevent a second timer clock
 # from advancing time during the additional diagnostic accessor calls.
 b.r.m.esfr[0xf17c]=b.r.m.esfr.get(0xf17c,0)&~0x40
 def plant():
  if E.status(b.r)[1]!=10:
   old();return
  fs=b.r('cfg_u16',62)
  b.adc_set(5,(b.batt_dv*1023+fs-1)//fs)
  k=tuple(b.r('hc_etbcal_value',i) for i in (10,11,12))
  if not gains or k!=gains[-1]:gains.append(k)
  step=b.r('hc_etbcal_value',20)&127
  desired=([.2,.6,.2,.04,.15][step-1] if step else
           (.5 if b.r('hc_dbw_bridge_on') else E.LIMP))
  if mode=='unsettled' and step==0 and b.r('hc_dbw_bridge_on'):
   desired=.45 if b.ms%20<10 else .55
  if step==1 and oldstep[0]!=1:start[0]=b.ms
  oldstep[0]=step
  elapsed=0 if start[0] is None else (b.ms-start[0])&65535
  if mode=='stale' and step==1:
   b.stale_ch=1
  elif step==1 and 200<=elapsed<220 and mode in ('one_overshoot','all_overshoots'):
   desired=.08;injected[0]+=1
  # Exactly ONE publication per ms: a second call would shorten the
  # fixture's TPS2 delay queue while still tagging that sample 3 ms old.
  b.pos+=max(-.02,min(.02,desired-b.pos));b.vel=0;b.tps()
 b.plant=plant
 result=b.run(arg=3,max_ms=E.AT_MAX_MS)
 published=[b.u16d(E.AP.off(n)) for n in ('CAL_DBW_KP','CAL_DBW_KI','CAL_DBW_KD')]
 if mode=='clean':
  check('a clean response passes on the first candidate and publishes it',
        result==(5,0,0) and len(gains)==1 and published==list(gains[-1]),(result,gains))
 else:
  want={'one_overshoot':22,'all_overshoots':22,'unsettled':21}.get(mode)
  check('a refused response ends safely, publishes nothing',
        result[0]==3 and b.released() and published==original
        and (want is None or result[2]==want),(mode,result,gains))
  check('one candidate only - never a damped second one',
        len(gains)==1,(mode,result,gains))
print(f'PASS {checks} PID verification checks',flush=True)
