"""Focused diagnostic classifier tests using measured-style engineering traces."""
import math,unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
from me711_etb_characterization_analyze import metric,classify,analyze

def trace(target=40,origin=20,mode='normal',direction=1,segment=3):
    target,origin=(target,origin) if direction>0 else (origin,target)
    rows=[];actual=origin
    for k in range(81):
        t=k*.02
        tau=.055 if mode!='slow' else .3
        actual+=(target-actual)*(.02/tau)
        if mode=='overshoot':actual=target+(origin-target)*math.exp(-t*4)*math.cos(t*40)
        if mode=='steady':actual=target-4+(origin-target+4)*math.exp(-t*12)
        if mode=='saturation':actual=origin+(target-origin)*min(1,t/4)
        duty=18+(target-actual)*.5
        ii=0;dd=0
        if mode=='bias':ii=target*4;duty=18+ii/10
        if mode=='asymmetric':duty=35 if direction>0 else 5
        if mode=='saturation':duty=80
        if mode=='windup':ii=-direction*200 if t<.35 else 0;actual=origin if t<.3 else target+direction*7*math.exp(-(t-.3)*2)
        if mode=='d_chatter':dd=30*(-1)**k;duty=dd+18
        r=dict(time=t,sweepSegment=segment,dbwTargetX10=target,dbwActualX10=actual,
            sweepSignedDuty=duty,dbwInteg=ii,dbwTermP=(target-actual)*2,dbwTermD=dd,
            dbwTermFf=18,battDv=12.5,sweepPairWorst=.2,tpsSampleAgeMs=3,dbwFaults=0)
        if mode=='rate':r['sweepRequested']=100;r['dbwTargetX10']=20+min(80,t*30);r['dbwActualX10']=r['dbwTargetX10']-.5
        rows.append(r)
    return rows
class Tests(unittest.TestCase):
    def codes(self,segments):return {f['code'] for f in classify(segments)['findings']}
    def fixtures(self,mode):return [metric(trace(x,mode=mode,segment=i+1)) for i,x in enumerate((20,40,60,80))]
    def test_normal_both_directions(self):
        for d in (1,-1):
            m=metric(trace(direction=d));self.assertIsNotNone(m['rise_fall_10_90_s']);self.assertLess(m['overshoot_pct'],.1)
            self.assertIn('PASS / GOOD',self.codes([m]))
    def test_slow_spare_authority(self):self.assertIn('LIKELY PID P',self.codes(self.fixtures('slow')))
    def test_authority_is_not_pid(self):
        c=self.codes(self.fixtures('saturation'));self.assertIn('OUTPUT AUTHORITY',c);self.assertFalse(any(x.startswith('LIKELY PID') for x in c))
    def test_bias_before_pid(self):
        c=self.codes(self.fixtures('bias'));self.assertIn('FEEDFORWARD/BIAS',c);self.assertNotIn('LIKELY PID I',c)
    def test_persistent_error(self):self.assertIn('LIKELY PID I',self.codes(self.fixtures('steady')))
    def test_overshoot_not_automatically_pid(self):
        c=self.codes(self.fixtures('overshoot'));self.assertTrue('LIKELY PID P' in c or 'INCONCLUSIVE' in c);self.assertNotIn('LIKELY PID I',c)
    def test_windup_requires_integral_evidence(self):self.assertIn('LIKELY PID I',self.codes(self.fixtures('windup')))
    def test_dominated_chatter(self):self.assertIn('LIKELY PID D',self.codes(self.fixtures('d_chatter')))
    def test_asymmetry(self):
        ms=[metric(trace(40,mode='asymmetric',direction=d,segment=3)) for d in (1,1,1,-1,-1,-1)]
        # Closing fixture's matching hold target must be the same position.
        for m in ms:m['target_end_pct']=40
        self.assertIn('MECHANICAL/STICTION',self.codes(ms))
    def test_rate_limited(self):
        c=self.codes([metric(trace(mode='rate',segment=34))]);self.assertIn('TARGET RATE LIMIT',c);self.assertNotIn('OUTPUT AUTHORITY',c)
    def test_sensor_fault_blocks_pid(self):
        ms=self.fixtures('slow');ms[0]['fault_bits']=4
        c=self.codes(ms);self.assertIn('TPS/SENSOR',c);self.assertNotIn('LIKELY PID P',c)
    def test_low_resolution_is_inconclusive(self):
        rows=trace()[::8];c=self.codes([metric(rows)]);self.assertIn('INCONCLUSIVE',c);self.assertNotIn('MECHANICAL/STICTION',c)
    def test_small_signal_quantization_is_not_stiction(self):
        ms=[]
        for seg in range(19,24):
            rows=trace(21,20,segment=seg)
            for i,r in enumerate(rows):r['dbwActualX10']=21+(.2 if i%2 else -.2)
            ms.append(metric(rows))
        self.assertNotIn('MECHANICAL/STICTION',self.codes(ms))
    def test_separate_slam_report_and_voltage_retention(self):
        r=analyze(trace(segment=3)+[{**x,'time':x['time']+2} for x in trace(mode='rate',segment=34)])
        self.assertEqual(set(r['sections']),{'bounded','pedal_slam'});self.assertEqual(r['segments'][0]['vbat_mean_v'],12.5)
        self.assertFalse(r['complete_profile']);self.assertEqual(r['sections']['bounded']['voltage_compensation'],'NOT JUDGED FROM SINGLE RUN')
if __name__=='__main__':unittest.main()
