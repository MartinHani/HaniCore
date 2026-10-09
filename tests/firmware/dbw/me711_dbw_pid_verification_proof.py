"""Linked verification grader tests with prescribed coherent TPS traces.

The identification phase uses the existing simulated plant. Verification
uses explicit input traces to test acceptance, retries, exhaustion and stale
sources; it does not claim that these traces model the physical throttle.
"""
from pathlib import Path
import argparse,sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
ap=argparse.ArgumentParser()
ap.add_argument('--source-root',type=Path,default=Path(__file__).resolve().parents[3])
ap.add_argument('--case',choices=['one_overshoot','all_overshoots','stale','unsettled'])
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
for mode in ([args.case] if args.case else ('one_overshoot','all_overshoots','stale','unsettled')):
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
  elif step==1 and 200<=elapsed<220 and (mode=='all_overshoots' or len(gains)==1):
   desired=.08;injected[0]+=1
  # Exactly ONE publication per ms: a second call would shorten the
  # fixture's TPS2 delay queue while still tagging that sample 3 ms old.
  b.pos+=max(-.02,min(.02,desired-b.pos));b.vel=0;b.tps()
 b.plant=plant
 result=b.run(arg=3,max_ms=28000)
 if mode=='one_overshoot':
  check('full AutoCal retries overshoot and passes all response targets',
        result==(5,0,0) and len(gains)>1 and injected[0]>0,(result,gains,injected))
  check('overshoot retry reduces P/D and preserves integral recovery',
        gains[1][0]==gains[0][0]//2 and gains[1][2]==gains[0][2]//2
        and gains[1][1]==gains[0][1],gains)
  check('successful AutoCal publishes verified gains only',
        [b.u16d(E.AP.off(n)) for n in ('CAL_DBW_KP','CAL_DBW_KI','CAL_DBW_KD')]==list(gains[-1]),gains)
 else:
  check('exhaustion or stale source ends safely without publishing gains',
        result[0]==3 and b.released()
        and [b.u16d(E.AP.off(n)) for n in ('CAL_DBW_KP','CAL_DBW_KI','CAL_DBW_KD')]==original,
        (mode,result,gains))
  # An unsettled 50 % approach is damped and retried like an overshoot, on
  # the same budget (hcetbcal.c VFY_RETRIES), and ends unsettled (21) when
  # the budget is spent; a stale source is never retried.
  check('candidate reductions are bounded; stale input never retries',
        len(gains)==(4 if mode in ('all_overshoots','unsettled') else 1)
        and (mode!='unsettled' or result==(3,0,21)),(mode,result,gains))
print(f'PASS {checks} PID verification checks',flush=True)
