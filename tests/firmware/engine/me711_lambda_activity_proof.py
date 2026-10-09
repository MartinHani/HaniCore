"""Linked lambda consumer contract: passive activity cannot gate STFT/VE.

Only the measurement-provider boundary is replaced in simulator memory.
The production lifecycle is tested separately by test_hcwb_host.py; this
fixture does not claim to exercise a physical LSU or its ASIC conversion.
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_config_state_test as T
import me711_preset_apply_proof as AP
import c166_disasm as D

def main():
    r=T.boot(); AP.press_apply(r,3); AP.service(r)
    tgt=(T.ROOT/'firmware/targets/me711/hctarget.h').read_text()
    base=T.d(tgt,'TGT_EXTRAM_BASE')
    cfg=base+T.d(tgt,'TGT_RAM_CFG')+T.d(T._cfg,'HC_CFG_HDR_LEN')
    def field(name):
        off=T.d(T._gen if name.startswith('CFG_U_') else T._cfg,name)
        return (T.sym('hc_cfg') & 65535)+off if off<T.CORE else cfg+off
    def u8(name,v): r.m.w8(field(name),v)
    def u16(name,v): r.m.w8(field(name),v>>8); r.m.w8(field(name)+1,v&255)
    u8('CFG_U_STFT_ENABLE',1); u8('CFG_U_STFT_DELAY',0)
    u16('CFG_U_STFT_MIN_CLT',10000)
    u8('CFG_U_LAM1_SRC',1); u8('CFG_U_LAM2_SRC',1)
    u8('CFG_U_STFT_AFTER_AE',0); u8('CFG_U_STFT_AFTER_DFCO',0)
    for name,v in [('trg_rpm',900),('eng_clt_dc',10800),('eng_sensor_err',0),
                   ('eng_fuelcut',0),('eng_accel_us',0),('eng_warmup_pct',100)]:
        r.m.w16(T.sym(name)&65535,v)
    r.m.w8(T.sym('eng_cranking')&65535,0)
    r('hc_ec_init'); r('hc_evlog_init',0,0)
    addr=T.sym('hc_io_lambda')-0x800000
    def measurement(lam):
        # MOV R4,#lam; RETS -- only this test's flash bytearray is patched.
        r.m.flash[addr:addr+6]=bytes((0xE6,0xF4,lam&255,lam>>8,0xDB,0))
    measurement(1040)
    t1=next(k for k,v in D.SFR.items() if v=='T1')
    tick=0
    for ms in range(0,90001,30):
        tick=(tick+37500)&65535; r.m.sfr[t1]=tick
        r('hc_lamdyn_step',0,1,307,1,ms&65535)
        r('hc_lamdyn_step',1,1,307,1,ms&65535)
        r('hc_ec_pre',900); r('hc_ec_target_lambda',900,500)
        r('hc_ec_post',900,500)
    r('hc_ec_publish',0)
    och2=base+T.d(tgt,'TGT_RAM_OCH2')
    def och(off):
        a=och2+off-1024
        return (r.m.r8(a)<<8)|r.m.r8(a+1)
    assert och(1166)&0xC0==0xC0
    assert och(1200)&255==8, och(1200)
    assert r('hc_ec_fuel',1000)>1000
    assert r('hc_lamdyn_alive',0)&255==0
    print('PASS: 90 s constant valid lambda, no activity flag, STFT active and VE-valid bits set')
    measurement(0); r('hc_ec_post',900,500); r('hc_ec_publish',0)
    assert och(1166)&0xC0==0 and och(1200)&255==4
    print('PASS: invalid provider withdraws both consumer valid bits and trim learning')
    return 0

if __name__=='__main__': raise SystemExit(main())
