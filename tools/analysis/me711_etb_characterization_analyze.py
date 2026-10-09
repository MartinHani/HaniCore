#!/usr/bin/env python3
"""Read-only ETB characterization log analysis and voltage-run comparison.

Accepts TS .msl (tab-separated, header plus units row) or CSV. Engineering
units are percent/volts/seconds; dbwInteg retains firmware 0.1%-duty units.
No calibration writes. Raw JSON segment metrics remain useful when a verdict
is inconclusive. Sampling resolution bounds every inferred transient metric.
"""
from __future__ import annotations
import argparse,csv,json,math,statistics
from pathlib import Path

# 0-based driver-demand segments whose APP demand is a ramp (hc_etb_sweep.h)
SLAM_RAMPS=set(range(48,54))
def mean(v):return statistics.fmean(v) if v else 0.0
def peak(v):return max(map(abs,v),default=0.0)
def changes(v, threshold=0.5):
    signs=[1 if x>threshold else -1 if x < -threshold else 0 for x in v]
    signs=[x for x in signs if x]
    return sum(a!=b for a,b in zip(signs,signs[1:]))

def metric(rows, limit=80.0, noise=0.4, extended=False):
    t=[r['time'] for r in rows];target=[r['dbwTargetX10'] for r in rows]
    actual=[r['dbwActualX10'] for r in rows];duty=[r['sweepSignedDuty'] for r in rows]
    err=[a-b for a,b in zip(target,actual)]
    dt=[b-a for a,b in zip(t,t[1:])];duration=t[-1]-t[0] if len(t)>1 else 0
    weights=dt+[statistics.median(dt) if dt else 0]
    total=sum(weights)
    wmean=lambda a:sum(x*w for x,w in zip(a,weights))/total if total else mean(a)
    tail=[i for i,x in enumerate(t) if x>=t[-1]-0.15]
    p=[r.get('dbwTermP',0) for r in rows];ii=[r.get('dbwInteg',0)/10 for r in rows]
    dd=[r.get('dbwTermD',0) for r in rows];ff=[r.get('dbwTermFf',0) for r in rows]
    seg0=int(rows[0]['sweepSegment'])-1
    ramp=(16<=seg0<22 or seg0 in SLAM_RAMPS) if extended else (11<=seg0<17)
    direction=1 if target[-1]>=actual[0] else -1
    velocity=[(b-a)/d if d>0 else 0 for a,b,d in zip(actual,actual[1:],dt)]
    commanded=[(b-a)/d if d>0 else 0 for a,b,d in zip(target,target[1:],dt)]
    settled=None
    for i in range(len(t)):
        if t[-1]-t[i]>=0.10 and all(abs(x)<=2 for x in err[i:]):
            settled=t[i]-t[0];break
    def crossing(frac):
        amount=(target[-1]-actual[0])*frac
        for i,a in enumerate(actual):
            if direction*(a-actual[0])>=direction*amount:return t[i]-t[0]
        return None
    lo,hi=crossing(.1),crossing(.9)
    reversal=next((t[i]-t[0] for i in range(1,len(t))
        if direction*(actual[i]-actual[0])>noise and direction*(actual[i]-actual[i-1])>noise/2),None)
    pairs=[]
    for r in rows:
        # Coherent pair max comes directly from ECU (opposing tracks normalized there).
        if 'sweepPairWorst' in r:pairs.append(r['sweepPairWorst'])
    ages=[r.get('tpsSampleAgeMs',0) for r in rows]
    physical_saturated=[abs(x)>=limit-0.1 for x in duty]
    requested_saturated=[abs(a+b+c+d)>=limit-.1 for a,b,c,d in zip(p,ii,dd,ff)]
    saturated=[a or b for a,b in zip(physical_saturated,requested_saturated)]
    longest=run=0.0
    for w,sat in zip(weights,saturated):
        run=run+w if sat else 0;longest=max(longest,run)
    motion=abs(target[-1]-actual[0])
    deadband=None
    if not ramp and noise*3<motion<=3:
        for i in range(len(t)-2):
            if all(abs(a-actual[0])>noise for a in actual[i:i+3]):
                deadband=abs(duty[i]-duty[0]);break
    return dict(segment=int(rows[0]['sweepSegment']),section='pedal_slam' if int(rows[0]['sweepSegment'])>=(38 if extended else 33) else 'bounded',
        samples=len(t),duration_s=duration,sample_gap_max_s=max(dt,default=0),
        target_start_pct=target[0],target_end_pct=target[-1],actual_end_pct=actual[-1],
        motion_pct=motion,ramp=ramp,direction='opening' if direction>0 else 'closing',
        max_error_pct=peak(err),rms_error_pct=math.sqrt(wmean([e*e for e in err])),
        steady_error_pct=mean([err[i] for i in tail]),settle_s=settled,
        rise_fall_10_90_s=hi-lo if lo is not None and hi is not None and motion>=5 else None,
        overshoot_pct=max([max(0,direction*(a-b)) for a,b in zip(actual,target)],default=0),
        undershoot_pct=max([max(0,direction*(b-a)) for a,b in zip(actual,target)],default=0),
        peak_duty_pct=peak(duty),mean_abs_duty_pct=wmean(list(map(abs,duty))),
        holding_duty_pct=mean([duty[i] for i in tail]),
        saturation_pct=100*wmean([int(x) for x in saturated]),
        physical_pwm_saturation_pct=100*wmean([int(x) for x in physical_saturated]),
        requested_command_saturation_pct=100*wmean([int(x) for x in requested_saturated]),
        longest_saturation_s=longest,
        saturation_s=sum(w for w,s in zip(weights,saturated) if s),
        holding_i_pct=mean([ii[i] for i in tail]),holding_ff_pct=mean([ff[i] for i in tail]),
        holding_p_pct=mean([p[i] for i in tail]),holding_d_pct=mean([dd[i] for i in tail]),
        peak_i_pct=peak(ii),peak_p_pct=peak(p),peak_d_pct=peak(dd),peak_ff_pct=peak(ff),
        peak_velocity_pct_s=peak(velocity),peak_commanded_velocity_pct_s=peak(commanded),
        mean_velocity_pct_s=mean(velocity),mean_commanded_velocity_pct_s=mean(commanded),
        reversal_delay_s=reversal,deadband_command_change_pct=deadband,
        ringing_crossings=changes(err[2:],noise),duty_reversals=changes(duty,2),
        d_reversals=changes(dd,2),duty_delta_rms_pct=math.sqrt(mean([(b-a)**2 for a,b in zip(duty,duty[1:])])),
        i_opposes_step_pct=max([max(0,-direction*x) for x in ii[:max(1,len(ii)//3)]],default=0),
        vbat_mean_v=wmean([r.get('battDv',0) for r in rows]),
        vbat_min_v=min([r.get('battDv',0) for r in rows]),vbat_max_v=max([r.get('battDv',0) for r in rows]),
        tps_worst_pair_pct=max(pairs,default=0),tps_age_max_ms=max(ages,default=0),
        fault_bits=max([int(r.get('dbwFaults',r.get('ETB faults',0))) & ~10 for r in rows],default=0),
        target_slew_gap_pct=max([abs(r.get('sweepRequested',r['dbwTargetX10'])-r['dbwTargetX10']) for r in rows]),
        aborted=any(int(r.get('etbCalStatus',0))&15==3 for r in rows))

def classify(segments, noise=0.4):
    findings=[]
    def add(code,reason):
        if not any(f['code']==code for f in findings):findings.append(dict(code=code,reason=reason,confidence='candidate'))
    holds=[s for s in segments if not s['ramp'] and s['samples']>=5]
    poor=not segments or any(s['sample_gap_max_s']>.05 or s['samples']<5 for s in segments)
    sensor=any(s['fault_bits']&(4|16|128) or s['tps_age_max_ms']>100 or s['tps_worst_pair_pct']>5 for s in segments)
    if sensor:add('TPS/SENSOR','TPS/freshness evidence invalidates actuator and PID inference.')
    if any(s['aborted'] or s['fault_bits'] for s in segments):add('INCONCLUSIVE','Run aborted or production supervision terminated it; inspect stop reason.')
    if poor:add('INCONCLUSIVE','Log resolution is insufficient for confident transient/deadband classification.')
    if any(s['target_slew_gap_pct']>2 for s in segments if s['section']=='pedal_slam'):
        add('TARGET RATE LIMIT','Production target differs from mapped/clamped request; compare actual against effective target.')
    authority=any(s['i_opposes_step_pct']<10 and s['saturation_pct']>5 and s['longest_saturation_s']>=.2 and (abs(s['steady_error_pct'])>2 or s['settle_s'] is None or s['settle_s']>.5) for s in segments)
    if authority:add('OUTPUT AUTHORITY','Duty reaches configured ceiling while effective target remains unfollowed.')
    biased=[s for s in holds if abs(s['holding_i_pct'])>8 and abs(s['steady_error_pct'])<2]
    corrections=[s['holding_i_pct'] for s in holds]
    if len(biased)>=3 or (len(corrections)>=4 and max(corrections)-min(corrections)>12):
        add('FEEDFORWARD/BIAS','Repeatable/position-dependent integral holding correction; check bias before changing PID.')
    asymmetry=[]
    for a in holds:
        for b in holds:
            if a['direction']=='opening' and b['direction']=='closing' and abs(a['target_end_pct']-b['target_end_pct'])<.5:
                asymmetry.append(abs(a['holding_duty_pct']-b['holding_duty_pct']))
    dead=[s['deadband_command_change_pct'] for s in holds if s['deadband_command_change_pct'] is not None]
    if not poor and not sensor and ((len(dead)>=4 and statistics.median(dead)>8) or (len(asymmetry)>=3 and statistics.median(asymmetry)>15)):
        add('MECHANICAL/STICTION','Repeatable direction-dependent holding/deadband evidence. Friction, spring and bias remain confounded.')
    blocked=sensor or poor or authority or any(f['code'] in ('FEEDFORWARD/BIAS','MECHANICAL/STICTION') for f in findings)
    if not blocked:
        if any(s['motion_pct']>=5 and (s['settle_s'] is None or s['settle_s']>.5) and s['overshoot_pct']<3
               and abs(s['steady_error_pct'])<2 and s['peak_duty_pct']<70 and not s['ramp'] and s['target_slew_gap_pct']<2 for s in holds):
            add('LIKELY PID P','Slow large steps with spare authority and little overshoot; P too low candidate.')
        if sum(s['ringing_crossings']>=3 and s['overshoot_pct']>3 and s['peak_p_pct']>s['peak_d_pct']+s['peak_i_pct'] for s in holds)>=2:
            add('LIKELY PID P','Repeated overshoot/ringing with dominant P; aggressive P candidate.')
        if any(s['i_opposes_step_pct']>10 and (s['reversal_delay_s'] or 0)>.15 and s['overshoot_pct']>3 for s in holds):
            add('LIKELY PID I','Delayed reversal/overshoot associated with integral opposing the step; windup candidate.')
        elif sum(abs(s['steady_error_pct'])>2 and abs(s['holding_duty_pct'])<70 and abs(s['holding_p_pct']+s['holding_i_pct']+s['holding_d_pct']+s['holding_ff_pct'])<70 for s in holds)>=3:
            add('LIKELY PID I','Persistent hold error with spare authority; check integral recovery and bias together.')
        if sum(s['d_reversals']>=4 and s['duty_reversals']>=4 and s['duty_delta_rms_pct']>8 and s['peak_d_pct']>s['peak_p_pct'] for s in holds)>=2:
            add('LIKELY PID D','D-dominated duty chatter; acquisition noise and excessive derivative gain are alternatives.')
    if any(s['overshoot_pct']>5 or s['ringing_crossings']>=3 for s in holds) and not any(f['code'].startswith('LIKELY PID') for f in findings):
        add('INCONCLUSIVE','Overshoot/ringing requires term/velocity inspection; insufficient evidence to isolate P, I or D.')
    if not findings:findings=[dict(code='PASS / GOOD',reason='No measured issue within this profile and recording resolution.',confidence='profile-limited')]
    return dict(findings=findings,holding_asymmetry_pct=max(asymmetry,default=None),
        deadband_estimate_pct=statistics.median(dead) if len(dead)>=4 and not poor else None,
        voltage_compensation='NOT JUDGED FROM SINGLE RUN',
        recommended_next_action='Inspect TPS/stop reason first.' if sensor else 'Correct/re-characterize bias before PID.' if biased else 'Inspect effective target, signed duty and controller-term traces before adjusting gains.')

def analyze(rows,limit=80.0,noise=.4):
    profile=max([int(r.get('sweepProfile',0)) for r in rows],default=0)
    extended=profile>=42 or any(37<int(r.get('sweepSegment',0))<=59 for r in rows)
    count=profile if profile>=42 else 42 if extended else 37
    groups=[]
    for row in rows:
        if not 1<=int(row.get('sweepSegment',0))<=count:continue
        if int(row.get('etbCalStatus',1))&15==7:continue
        if 'etbProc' in row and int(row['etbProc'])&15!=6:continue
        if not groups or groups[-1][0]['sweepSegment']!=row['sweepSegment']:groups.append([])
        groups[-1].append(row)
    segments=[metric(g,limit,noise,extended=extended) for g in groups]
    sections={name:classify([s for s in segments if s['section']==name],noise) for name in ('bounded','pedal_slam')}
    return dict(segments=segments,sections=sections,complete_profile=set(s['segment'] for s in segments)==set(range(1,count+1)) and any(int(r.get('etbCalStatus',0))&15==7 for r in rows),
        limits=dict(duty_limit_pct=limit,motion_noise_floor_pct=noise),
        limitations=['Sampled rise/settle/reversal times have uncertainty of at least one sample interval.',
        'ADC quantization and residual pair skew cannot prove mechanical deadband.',
        'One voltage cannot prove compensation; supply, motor, spring and bias can produce similar symptoms.',
        'ENGINE-OFF observations cannot certify stability with engine airflow/load or all failure modes.'])

def read_log(path):
    lines=path.read_text(encoding='utf-8-sig',errors='replace').splitlines()
    start=next((i for i,l in enumerate(lines) if 'sweepSegment' in l and ('dbwActualX10' in l or 'sweepActual' in l)),None)
    if start is None:raise ValueError('No characterization channel header; use the matching generated INI and start a new data log.')
    delim='\t' if '\t' in lines[start] else ','
    result=[]
    for row in csv.DictReader(lines[start:],delimiter=delim):
        try:r={k:float(v) for k,v in row.items() if k and v not in ('',None)}
        except (ValueError,TypeError):continue # TS units row
        for src,dest in (('sweepTarget','dbwTargetX10'),('sweepActual','dbwActualX10'),('sweepMotor','sweepSignedDuty'),('sweepP','dbwTermP'),('sweepD','dbwTermD'),('sweepFf','dbwTermFf')):
            if src in r:r[dest]=r[src]
        if 'sweepI' in r:r['dbwInteg']=r['sweepI']*10
        r['time']=r.get('time',r.get('Time',r.get('Time(s)',float('nan'))))
        if math.isfinite(r['time']):result.append(r)
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('logs',nargs='+',type=Path)
    p.add_argument('--duty-limit',type=float,required=True,help='Configured dbwMaxDuty, in percent')
    p.add_argument('--noise-floor',type=float,default=.4,help='Conservative minimum reliable motion in percent')
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();runs=[]
    for path in a.logs:
        report=analyze(read_log(path),a.duty_limit,a.noise_floor);report['source']=str(path);runs.append(report)
    comparison=[dict(source=r['source'],complete=r['complete_profile'],
        vbat_mean_v=mean([s['vbat_mean_v'] for s in r['segments']]),
        segments=[{k:s[k] for k in ('segment','target_end_pct','rise_fall_10_90_s','settle_s','holding_duty_pct','holding_i_pct','holding_ff_pct','peak_p_pct','peak_d_pct','peak_i_pct','saturation_pct','vbat_mean_v')} for s in r['segments']]) for r in runs]
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(dict(runs=runs,voltage_comparison=comparison),indent=2)+'\n')
    for r in runs:
        print(r['source'],'COMPLETE' if r['complete_profile'] else 'INCOMPLETE')
        for section,result in r['sections'].items():
            print(section,', '.join(f['code'] for f in result['findings']),result['recommended_next_action'])
    return 0
if __name__=='__main__':raise SystemExit(main())
