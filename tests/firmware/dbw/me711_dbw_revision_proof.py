"""Focused linked-C167 DBW regressions; use --source-root for a V101 snapshot.

The physical plant reads GPIO direction/latches and PWM registers. Software
results do not qualify real motor current, spring return or reset transients.
"""
from pathlib import Path
import argparse
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

parser = argparse.ArgumentParser()
parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[3])
parser.add_argument('--quick', action='store_true', help='omit the two mechanical runs')
args = parser.parse_args()
sys.path.insert(0, str(args.source_root.resolve() / 'tools'))
import me711_etb_autocal_proof as E
import me711_dbw_control_proof as DC
import me711_bridge_model as M
import me711_image as PI

checks = 0
def check(label, ok, detail=''):
    global checks
    checks += 1
    print(('PASS ' if ok else 'FAIL ') + label + ' ' + str(detail), flush=True)
    assert ok, (label, detail)

def supply(b, dv):
    b.batt_dv = dv
    b.r.m.w16(E.T.sym('hc_tick_ms') & 65535, b.ms)
    # Exercise the whole accepted voltage interval, including above the
    # board's default 18 V divider full scale.
    b.r('cfg_set_u16', 62, 250)
    fs = b.r('cfg_u16', 62)
    raw = (dv * 1023 + fs - 1) // fs
    b.adc_set(5, raw)

def command(b, letter, value):
    for i, v in enumerate((33, ord(letter), value)):
        b.r.m.w8(E.AP.REQ+i, v)
    b.r('hcts_target_cmd', E.AP.REQ, 3)

def desired16(b, name):
    return b.u16d(E.AP.off(name))

print('LINKED IMAGE', PI.image(), PI.sha256(), flush=True)
b = E.Bench(); supply(b, 135)
signs = []
for direction in (0, 1, 0, 1):
    off = [False]; drove = [False]
    original = b.r.c.step
    def trace():
        result = original()
        value, di, _, _ = M.state(b.r.m)
        if di != 'L': off[0] = True
        if off[0] and di == 'L' and value:
            assert value * (1 if direction == 0 else -1) > 0
            drove[0] = True
        return result
    b.r.c.step = trace
    try: b.r('hc_dbw_drive', direction, 500)
    finally: b.r.c.step = original
    signs.append(M.state(b.r.m)[0])
    check('disable precedes each polarity change', off[0] and drove[0], direction)
check('requested A/B produce opposite physical polarity', signs == [.5, -.5, .5, -.5], signs)
b.r('hc_dbw_shutdown', 0)

for dv, fac in ((40,1800),(60,1800),(120,1125),(125,1080),(135,1000),(142,950),(200,700)):
    b = E.Bench(); supply(b,dv)
    b.r('hc_dbw_drive',0,400)
    actual = b.r('hc_dbw_duty_x10')
    check('normalized 40% authority and physical PWM at VBAT',
          actual == 400 * fac // 1000 and b.r('hc_dbw_term',4) == fac
          and abs(M.state(b.r.m)[0] - actual/1000) < .001, (dv,fac,actual))
    b.r('hc_cal_set_u16',E.AP.off('CFG_U_DBW_MAX_DUTY_X10'),450)
    b.r('hc_dbw_drive',0,65535)
    check('post-compensation ceiling cannot wrap',b.r('hc_dbw_duty_x10')<=450,(dv,b.r('hc_dbw_duty_x10')))
    b.r('hc_dbw_shutdown',0)

b=E.Bench(); supply(b,120)
b.r('hc_cal_set_u8',E.AP.off('CFG_U_DBW_BATT_COMP'),1)
b.r('hc_dbw_drive',0,400)
check('compensation Off preserves raw authority',b.r('hc_dbw_duty_x10')==400)
b.r('hc_dbw_shutdown',0)
for dv in (0,39,201):
    b=E.Bench(); supply(b,dv); b.r('hc_dbw_drive',0,500)
    check('invalid supply refuses and latches without division by zero',
          b.released() and b.r('hc_dbw_faults') & 0x200,dv)
    supply(b,135); b.r('hc_dbw_drive',0,500)
    check('fresh VBAT cannot silently recover latched supply fault',b.released(),dv)

b=E.Bench(); supply(b,135); b.r('hc_dbw_drive',0,500)
b.r('hc_hal_main_sample',5,0,0,b.ms)
b.r('hc_dbw_drive',0,500)
check('invalid ADC completion shuts down an energized motor',b.released() and b.r('hc_dbw_faults')&0x200)
b=E.Bench();b.tps();supply(b,135);b.r('hc_dbw_drive',0,300)
b.ms+=101;b.r.m.w16(E.T.sym('hc_tick_ms')&65535,b.ms);supply(b,135)
b.r('hc_fresh_service')
check('stale TPS releases direct/bench owner outside normal RUN',
      b.released() and b.r('hc_dbw_faults')&128)

# All four literal UI commands -> handler -> ACTIVE + DESIRED -> refresh.
# Old opposite endpoints deliberately conflict with new captured values.
b=E.Bench(); supply(b,135)
for what, vals, names, corr in (
    (1,(915,107),('CAL_TPS1_MIN','CAL_TPS2_MIN'),'CFG_U_TPS_CORR'),
    (2,(65,957),('CAL_TPS1_MAX','CAL_TPS2_MAX'),'CFG_U_TPS_CORR'),
    (3,(200,100),('CAL_PEDAL1_MIN','CAL_PEDAL2_MIN'),'CFG_U_APP_CORR'),
    (4,(800,400),('CAL_PEDAL1_MAX','CAL_PEDAL2_MAX'),'CFG_U_APP_CORR')):
    for ch,val in zip((1,3) if what<3 else (8,9),vals): b.adc_set(ch,val)
    command(b,'G',what)
    check('Grab updates both tracks and requests UI refresh',
          E.AP.och(b.r,450)==(what<<8)|7 and E.AP.och(b.r,452)==what
          and [desired16(b,n) for n in names]==list(vals)
          and [b.r('hc_cal_u16',E.AP.off(n)) for n in names]==list(vals)
          and b.r.desired(E.AP.off(corr))==1 and E.AP.och(b.r,770)==1,what)
check('Grab never commits to flash',b.r('hc_nvm_commits')==0)
snapshot=bytes(b.r.desired(i) for i in range(E.T.PAGE))
b.r('hc_hal_main_sample',1,0,0,b.ms); command(b,'G',1)
check('Grab rejects stale TPS without modifying page',
      E.AP.och(b.r,450)&255==3 and snapshot==bytes(b.r.desired(i) for i in range(E.T.PAGE)))
b.tps(); b.r('hc_dbw_drive',0,300); command(b,'G',1)
check('Grab refuses while motor is energized',E.AP.och(b.r,450)&255==2 and snapshot==bytes(b.r.desired(i) for i in range(E.T.PAGE)))
b.r('hc_dbw_shutdown',0)

# Fresh ADC scans during a delayed control raster must not extend a hold.
b=E.Bench(); supply(b,135); b.tps(); b.cmd(1)
for _ in range(450): b.step()
check('calibration actually drives before deadline test',M.state(b.r.m)[1]=='L')
b.ms+=101; b.r.m.w16(E.T.sym('hc_tick_ms')&65535,b.ms); b.tps(); supply(b,135)
b.r('hc_fresh_service')
check('serial-yield control deadline cancels calibration despite fresh TPS',
      b.released() and E.status(b.r)==(3,0,29) and b.r('hc_dbw_faults')&128,E.status(b.r))

r=DC.Rig(); r.baseline(); r.pedal(400); r.plate(350)
for ms in range(10000,10080,10): r.service(ms)
check('normal loop drives before deadline test',r.s()['on']==1)
ms=10200; r.mem.w16(DC.sym('hc_tick_ms')&65535,ms)
for ch in (5,DC.ADC_TPS1,DC.ADC_TPS2,DC.ADC_APP1,DC.ADC_APP2):
    raw=r.mem.r16(r.adc+ch*2); r.call('hc_hal_main_sample',(ch,(ch<<12)|raw,1,ms))
r.call('hc_fresh_service')
check('serial-yield deadline releases normal DBW despite fresh sensors',r.s()['on']==0 and r.s()['faults']&128,r.s())

# Reset from a driven state cannot inherit motor ownership or relay history.
b=E.Bench(); supply(b,135); b.r('hc_dbw_drive',1,500)
b.r('hc_dbw_init')
check('watchdog-style software reinitialization forces OFF and clears ownership',b.released() and E.status(b.r)==(0,0,0))

# Latched bridge/deviation/TPS faults are never cleared by calibration entry.
for bit in (4,16,32,64,128,512):
    b=E.Bench(); supply(b,135); b.r('hc_dbw_shutdown',bit)
    b.cmd(2)
    for _ in range(550): b.step()
    check('PID request preserves critical fault and cannot energize',
          b.r('hc_dbw_faults')&bit and all(not on for _,_,on,_ in b.log),bit)

if not args.quick:
    for reverse,delay in ((False,0),(True,900)):
        b=E.Bench(reversed_motor=reverse)
        b.r('hc_dbw_shutdown',10) # Already-latched APP pair/range faults.
        old=b.plant; started=[None]; phases=set()
        def plant():
            ph=E.status(b.r)[1]; phases.add(ph)
            if ph==5 and started[0] is None: started[0]=b.ms
            pos=b.pos; old()
            if started[0] is not None and ((b.ms-started[0])&65535)<delay and M.state(b.r.m)[1]!='L':
                b.pos=pos; b.vel=0; b.tps()
        b.plant=plant
        result=b.run(arg=3,max_ms=18000)
        check('full AutoCal settles and completes private PID verification',
              result==(5,0,0) and b.released() and {9,10,11}.issubset(phases),(reverse,delay,result,sorted(phases)))
        check('pedal latches survive calibration and restore normal refusal',
              b.r('hc_dbw_faults')&10==10 and b.r.callb('hc_dbw_state')==3,
              b.r('hc_dbw_faults'))
    b=E.Bench(); b.batt_dv=120
    result=b.run(arg=2)
    check('standalone PID also uses shared motor-off settle at 12V',result==(4,0,0) and b.released(),result)

print(f'{checks}/{checks} focused linked checks PASS',flush=True)
