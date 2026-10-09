"""Standalone endpoint/abort checks complement the combined AutoCal gate."""
from pathlib import Path
import argparse,sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
p=argparse.ArgumentParser()
p.add_argument('--source-root',type=Path,default=Path(__file__).resolve().parents[3])
a=p.parse_args();sys.path.insert(0,str(a.source_root.resolve()/'tools'))
import me711_etb_autocal_proof as E
import me711_image as PI
n=0
def check(label,ok,detail=''):
    global n
    n+=1;print(('PASS ' if ok else 'FAIL ')+label+' '+str(detail),flush=True)
    assert ok,(label,detail)
print('LINKED IMAGE',PI.image(),PI.sha256(),flush=True)
for reverse,dv in ((False,120),(True,142)):
    b=E.Bench(reversed_motor=reverse);b.batt_dv=dv
    st=b.run(arg=1)
    check('standalone endpoint capture completes at supply',st==(2,0,0) and b.released(),(reverse,dv,st))
    got=[b.u16d(E.AP.off(x)) for x in ('CAL_TPS1_MIN','CAL_TPS1_MAX','CAL_TPS2_MIN','CAL_TPS2_MAX')]
    check('standalone endpoints retain calibrated raw slopes',
          all(abs(g-w)<=4 for g,w in zip(got,(102,954,919,71))),got)
b=E.Bench();b.cmd(1)
for i in range(450):b.step()
check('operator abort starts from an energized calibration',not b.released())
b.cmd(0);b.step()
check('operator abort releases bridge and records its own reason',
      b.released() and E.status(b.r)==(3,0,10),E.status(b.r))
print('PASS',n,'standalone endpoint/abort checks',flush=True)
