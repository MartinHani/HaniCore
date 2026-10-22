"""Linked V101 acquisition completion, tag, age and wrap regressions.

ASIC fixtures represent already accepted transport frames; they do not
simulate or certify ADC completion inside the peripheral ASIC.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_config_state_test as T
import me711_preset_apply_proof as AP


def main():
    r=T.boot(); AP.press_apply(r,3); AP.service(r)
    r('hc_hal_init', steps=5_000_000); r('hc_dbw_init')
    r('hc_route_service', steps=5_000_000)
    r.m.sfr[0xFFCC] = r.m.sfr.get(0xFFCC,0) | 4
    tick=T.sym('hc_tick_ms') & 0xffff
    adc=T.sym('adc_raw') & 0xffff
    def now(t): r.m.w16(tick,t & 0xffff)
    def sample(ch,raw,t,done=1,tag=None):
        now(t)
        r.m.w16(adc+2*ch,raw)
        r('hc_hal_main_sample',ch,((ch if tag is None else tag)<<12)|raw,done,t)
    sample(1,350,65500)
    assert r.callb('hc_hal_ain_ok',4)==1
    seq=r('hc_hal_main_seq',4)
    sample(1,350,65501,done=0)
    assert r.callb('hc_hal_ain_ok',4)==0 and r('hc_hal_main_seq',4)==seq
    sample(1,350,65502,tag=3)
    assert r.callb('hc_hal_ain_ok',4)==0 and r('hc_hal_main_seq',4)==seq
    sample(1,350,65503)
    assert r.callb('hc_hal_ain_ok',4)==1 and r('hc_hal_main_seq',4)==(seq+1)&65535
    now(65580); r('hc_fresh_service')
    assert r('hc_hal_ain_age',4)==77
    for t in range(65630,276000,50):
        now(t); r('hc_fresh_service')
        assert r.callb('hc_hal_ain_ok',4)==0
    print('PASS: MAIN completion, wrong tag, recovery, terminal age across >3 wraps')

    run_ok=T.sym('hc_asic_run_ok') & 0xffff
    run_live=T.sym('hc_asic_run_live') & 0xffff
    last=T.sym('hc_asic_last_ok_ms') & 0xffff
    state=T.sym('hc_asic_state') & 0xffff
    def accepted(t,n):
        now(t); r.m.w8(run_live,1); r.m.w8(state,6)
        r.m.w16(last,t & 65535); r.m.w16(run_ok,n)
        for ch in range(16): r.m.w16(0xE100+2*(4+ch),(ch<<12)|400)
        # since 2026-10-13 the reply is snapshotted AT ITS ACCEPT (CC27
        # level, hcasicstart.c) and the service reads only that snapshot
        r('hc_hal_ain_capture')
        r('hc_hal_ain_service')
    r('hc_hal_s5500_window',4)
    accepted(65000,65535)
    assert r('hc_hal_asic_an',12)==400 and r.callb('hc_hal_ain_ok',1)==1
    r.m.w16(T.sym('hc_s5500_snaps') & 65535,65535)
    accepted(65010,0)
    assert r('hc_hal_asic_an',12)==400 and r('hc_hal_asic_age')==0
    r.m.w16(0xE100+2*16,0xD190)
    now(65011); r.m.w16(run_ok,1); r.m.w16(last,65011)
    r('hc_hal_ain_capture')
    r('hc_hal_ain_service')
    assert r('hc_hal_asic_an',12)==65535 and r('hc_hal_asic_an',13)==400
    r.m.w8(state,0)
    r('hc_asic_start_service',65070)
    assert r('hc_asic_healthy') & 255 == 0
    for t in range(65070,276000,50):
        now(t); r('hc_hal_ain_service')
        assert r('hc_hal_asic_an',13)==65535
    assert r('hc_asic_healthy') & 255 == 0
    r('eng_init'); r('eng_service',steps=5_000_000)
    err=r.m.r16(T.sym('eng_sensor_err') & 65535)
    assert err & 0x301 == 0x301
    print('PASS: ASIC tags, accepted-frame/snapshot counter wraps, stale cached values')
    print('PASS: stale VBAT/CLT/IAT produce consumer fallback error bits')
    from me711_etb_autocal_proof import Bench,status
    for keyoff in (False,True):
        b=Bench(); b.tps(); b.cmd(1)
        # AutoCal first measures the rest position with the bridge off (2 s);
        # step into the phase that drives it.
        for _ in range(1000):
            b.step()
            if not b.released(): break
        assert not b.released()
        if keyoff: b.r.m.sfr[0xFFCC] &= ~4
        b.r.m.w16(tick,(b.ms+101)&65535)
        # A yield runs freshness/safety only, without a new DBW control step.
        b.r('hc_fresh_service')
        assert b.released() and status(b.r)[0]==3
        assert status(b.r)[2] == (2 if keyoff else 26)   # NOTLIVE / STALE
    print('PASS: serial-yield release on expired TPS or raw KL15 loss')
    # Target frame boundary: direct normal duty without lifecycle ownership
    # is refused; the explicitly bounded bench override has a positive ON
    # vector and expires even if its main-loop test service never runs again.
    r('hc_io_init'); now(1000)
    r('hc_io_duty',5,1000); r('hc_io_frame')
    assert not (r('hc_io_word',6)&0x8000)
    assert r('hc_io_test_start',5,200,1000)&255==1
    r('hc_io_test_service',1000); r('hc_io_frame')
    assert r('hc_io_word',6)&0x8000
    now(1200); r('hc_io_frame')
    assert not (r('hc_io_word',6)&0x8000)
    for t in range(1250,211000,50):
        now(t); r('hc_io_frame')
        assert not (r('hc_io_word',6)&0x8000)
    r('hc_io_init'); now(2000)
    assert r('hc_io_test_start',5,200,2000)&255==1
    r('hc_io_test_service',2000); r('hc_io_frame')
    assert r('hc_io_word',6)&0x8000
    r.m.sfr[0xFFCC] &= ~4; r('hc_io_frame')
    assert not (r('hc_io_word',6)&0x8000)
    print('PASS: heater frame refusal, positive bounded pulse, terminal expiry and raw-key release')
    # Inspect the real adapter's argument at the unmodified core entry. The
    # engine's 12 V fallback must not become a heater supply qualification.
    supplies=[]; contexts=[]; original_step=r.c.step; pair_entry=T.sym('hcwb_pair_step')
    def capture_step():
        if (r.c.csp<<16)|r.c.ip == pair_entry:
            supplies.append(r.m.r16(r.c.mem_addr((r.c.gr(9)+2)&65535)))
            contexts.append(r.c.mem_addr(r.c.gr(8)))
        original_step()
    r.c.step=capture_step
    erraddr=T.sym('eng_sensor_err')&65535
    def adapter(t,running=1):
        # Keil puts the first five words in R8..R12 and the remaining
        # supply/running arguments on its software stack (linked disassembly).
        top=r.stack_top
        r.stack_top=top-4
        r.m.w16(top-4,120); r.m.w16(top-2,running)
        try:
            r('hc_io_lambda_service',t,307,600,307,600,steps=5_000_000)
        finally:
            r.stack_top=top
    try:
        r('hc_io_init'); r.m.sfr[0xFFCC] |= 4
        cfg=T.d(T._tgt,'TGT_EXTRAM_BASE')+T.d(T._tgt,'TGT_RAM_CFG')+T.d(T._cfg,'HC_CFG_HDR_LEN')
        r.m.w8(cfg+T.d(T._gen,'CFG_U_LAM1_SRC'),1)
        r.m.w8(cfg+T.d(T._gen,'CFG_U_LAM_HEAT_POLICY'),2)
        sample(5,500,2200); r.m.w16(erraddr,0)
        adapter(2200)
        assert supplies[-1]==120, ('fresh supply at adapter',supplies,r.callb('hc_hal_ain_ok',0))
        # C167's aligned 16-bit layout: permission at byte 59, tail at 60.
        # The linked pair loop independently confirms a 66-byte context stride.
        assert r.m.r8(contexts[-1]+59)==1
        sample(5,500,2201,done=0)
        adapter(2201)
        assert supplies[-1]==0
        assert r.m.r8(contexts[-1]+59)==0 and r.m.r16(contexts[-1]+60)==0, ('invalid supply retained grant',r.m.r8(contexts[-1]+59),r.m.r16(contexts[-1]+60))
        sample(5,500,2202); r.m.w16(erraddr,0x100)
        adapter(2202)
        assert supplies[-1]==0
        r.m.w16(erraddr,0)
        for t in range(2300,212300,1000):
            sample(5,500,t); adapter(t,0)
            assert r.m.r8(contexts[-1]+59)==0 and r.m.r16(contexts[-1]+60)==0
        r('hc_io_init'); sample(5,500,2200); adapter(2200)
        assert r.m.r8(contexts[-1]+59)==1
        # Frame refusal must end ownership too, not only the current duty.
        # Otherwise a core that resumes after a full clock wrap can reuse
        # the old, never-decremented 30 s tail while the engine is stopped.
        now(2350); r('hc_io_frame')
        assert r.m.r8(contexts[-1]+59)==0 and r.m.r16(contexts[-1]+60)==0, ('frame refusal retained grant',r.m.r8(contexts[-1]+59),r.m.r16(contexts[-1]+60))
        for t in range(2400,212400,1000):
            sample(5,500,t); r('hc_io_frame')
            assert r.m.r8(contexts[-1]+59)==0 and r.m.r16(contexts[-1]+60)==0
        adapter(212400,0)
        assert r.m.r8(contexts[-1]+59)==0
    finally:
        r.c.step=original_step
    print('PASS: adapter supply refusal, core revocation and paused-core frame expiry across >3 wraps')
    print('PHYSICAL QUALIFICATION PENDING: ASIC internal ADC scan provenance')
    return 0

if __name__=='__main__': raise SystemExit(main())
