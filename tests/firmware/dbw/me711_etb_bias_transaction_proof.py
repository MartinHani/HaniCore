"""Linked RAM Save transaction fixture; no claim of physical eligibility.

Injects the result of a qualified estimator, then executes the real command
consumer/validator. Estimator qualification itself is tested separately.
"""
from pathlib import Path
import shutil,tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_image as I
import me711_dbw_control_proof as D

def main():
    snap=Path(tempfile.mkdtemp(prefix='hc_bias_txn_'))
    for attr in ('IMG','MAP','MANIFEST'):
        p=getattr(I,attr);q=snap/p.name;shutil.copy2(p,q);setattr(I,attr,q)
    r=D.Rig();r.baseline();r.set8('CAL_DBW_ENABLE',0)
    r.set16('CAL_DBW_SF_MODE',D.hdr_int(D.GEN_H,'HC_DBW_SF_LOW_IS_FAULT'))
    r.mem.sfr[0xffc4]|=0x8000;r.plate(100);r.service(1000);r.service(1005)
    # The controller-only rig does not run engine ADC publication. Publish its
    # healthy sensor-summary input explicitly; the live Save guard still runs.
    r.mem.w16(D.sym('eng_sensor_err')&65535,0)
    # C166 int=16, long=32, alignment=2: assert the fixture through the public
    # getters rather than trusting a host compiler's different struct layout.
    b=0x381800;e=0x386d00
    r.mem.w8(e,0);r.mem.w8(e+2,7);r.mem.w8(e+8,6)
    rev=r.mem.r16(D.sym('hc_cfg_desired_rev')&65535)
    # hc_bias_t (hc_etb_bias.h) on C166: revision +248, state +266,
    # proposed[8] +158, pax[8] (proposed axis) +174 - each asserted below
    # through its public getter, so a stale offset cannot pass silently.
    r.mem.w16(b+248,rev);r.mem.w8(b+266,1)
    assert r.call('hc_etbcal_value',(34,))==1
    off=D.gen_off('CAL_DBW_BIAS_VAL');axo=D.gen_off('CAL_DBW_BIAS_AX')
    before=bytes(r.mem.r8(r.page_addr(i)) for i in range(4096))
    for j in range(8):
        value=int.from_bytes(before[off+2*j:off+2*j+2],'big')+10
        r.mem.w16(b+158+2*j,value)
        assert r.call('hc_etbcal_value',(35+j,))==value
        # the proposed AXIS: interior points moved by one count (still rising)
        ax=int.from_bytes(before[axo+2*j:axo+2*j+2],'big')+(1 if 0<j<7 else 0)
        r.mem.w16(b+174+2*j,ax)
        assert r.call('hc_etbcal_value',(87+j,))==ax
    commits=r.call('hc_nvm_commits');generation=r.call('hc_nvm_generation')
    r.call('hc_etbcal_request',(7,));r.call('hc_etbcal_bias_service',(1010,))
    state=r.call('hc_etbcal_value',(34,));assert state==2,('Save refused',state,r.s())
    after=bytes(r.mem.r8(r.page_addr(i)) for i in range(4096))
    changed={i for i,(x,y) in enumerate(zip(before,after)) if x!=y}
    assert changed and changed<=set(range(axo,off+16)),changed
    assert changed&set(range(axo,axo+16)) and changed&set(range(off,off+16)),changed
    assert r.call('hc_nvm_commits')==commits and r.call('hc_nvm_generation')==generation
    assert r.call('hc_nvm_state')==1,'Save should mark dirty, never request Burn'
    r.call('hc_etbcal_request',(6,));r.service(1015)
    assert r.call('hc_etbcal_status')&15==1,'rerun must start immediately'
    print('PASS linked Save changes only the 32 bias-curve bytes (axis + values); PID/TPS/VBAT preserved')
    print('PASS RAM dirty, no commit/generation change, immediate rerun accepted')
    return 0
if __name__=='__main__':raise SystemExit(main())
