"""Exact V101 page migration in retained SRAM, committed flash and restore tooling."""
import sys,hashlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_config_state_test as C
import me711_v101_compat as V
import me711_lkg_walkback_proof as K
import me711_store as R
import me711_image as I
checks=fails=0
def check(n,ok,d=''):
    global checks,fails
    checks+=1;fails+=not ok;print(f"[{'PASS' if ok else 'FAIL'}] {n}: {d}")
def page(r):return bytes(r.active(i) for i in range(4096))
def rec(payload,gen,layout=V.OLD_LAYOUT,done=True):
    b=bytearray(K.record(payload,gen));b[4:8]=layout.to_bytes(4,'big');b[16:18]=K.crc(b[:16]).to_bytes(2,'big')
    if not done:b[-4:]=b'\xff'*4
    return bytes(b)
def main():
    print(I.STEM,I.sha256())
    old=(I.ROOT/'tests/fixtures/v101_exact_page.bin').read_bytes()  # the V101 bench page (evidence V102_SOFTWARE)
    check('Fixture is exact V101 universal identity',V.known_identity(V.OLD_LAYOUT,old),hashlib.sha256(old).hexdigest())
    expected=V.migrate_v101(old)
    r=C.Rig();r('hc_cfg_init')
    for i,v in enumerate(old):r('hc_cal_set_u8',i,v)
    r('hc_cfg_commit');r('hc_cfg_init')
    check('Retained SRAM accepts the same exact V101 contract',r.g16('hc_cfg_source')==1 and page(r)==old)
    r('hc_cfg_migrate_v101');migrated=page(r)
    check('Linked migration equals restoration migration byte for byte',migrated==expected)
    allowed=set(range(V.value('CFG_U_FUEL_MODEL'),V.value('CFG_U_DBW_FRICTION_X10')+2))|{V.SCHEMA_OFF,V.SCHEMA_OFF+1,V.value('CFG_U_CRC'),V.value('CFG_U_CRC')+1}
    check('Every original calibration byte is preserved outside the declared extension/identity',all(a==b for i,(a,b) in enumerate(zip(old,migrated)) if i not in allowed))
    check('Migrated fuel mode is explicit Legacy, lean guard remains disabled',migrated[V.value('CFG_U_FUEL_MODEL')]==0 and migrated[V.value('CFG_U_LEAN_ENABLE')]==0)
    r('hc_cfg_init');check('Migrated retained page checksum survives reinitialization',r.g16('hc_cfg_source')==1 and page(r)==expected)
    r('hc_cal_set_u16',V.SCHEMA_OFF,0x1234);r('hc_cfg_commit');r('hc_cfg_init')
    check('Checksummed unknown SRAM semantic identity is rejected',r.g16('hc_cfg_source')!=1)
    for layout,schema,want in [(V.OLD_LAYOUT,V.OLD_SCHEMA,1),(V.LAYOUT,V.SCHEMA,1),(V.LAYOUT,V.OLD_SCHEMA,0),(V.OLD_LAYOUT,V.SCHEMA,0),(0x12345678,V.SCHEMA,0)]:
        check(f'Exact flash identity pair {layout:08x}/{schema:04x}',r.callb('hc_cfg_identity_known',layout>>16,layout&65535,schema)==want)
    base=I.image().read_bytes()
    b=K.Boot(K.place(base,{0:rec(old,10)}),steps=1_650_000)
    check('Full standby loss restores and migrates exact V101 committed flash',b.page()==expected and b.u8('hc_cfg_boot_fellback')==0)
    bad=bytearray(expected);bad[V.value('CFG_U_PIN_CRANK')]=29
    b=K.Boot(K.place(base,{0:rec(old,10),1:rec(bytes(bad),11,V.LAYOUT)}),steps=1_650_000)
    check('Semantic LKG walkback preserves older migratable V101 calibration',b.page()==expected and b.call('hc_nvm_lkg_steps')==1)
    b=K.Boot(K.place(base,{0:rec(old,10),1:rec(expected,11,V.LAYOUT,False)}),steps=1_650_000)
    check('Interrupted Burn without DONE cannot replace prior committed V101',b.page()==expected and b.u8('hc_cfg_boot_fellback')==0)
    dump=K.place(base,{0:rec(old,10),1:rec(expected,11,V.LAYOUT,False)})
    best,seen=R.newest_record(dump,V.LAYOUT,1)
    check('Restore tooling selects the same committed source and migration',best is not None and best[1]==10 and V.migrate_v101(best[2])==expected,str(seen))
    mismatched=K.place(base,{0:rec(old,12,V.LAYOUT)})
    check('Restore tooling refuses layout/schema cross-pairs',R.newest_record(mismatched,V.LAYOUT,1)[0] is None)
    print(f'{checks-fails}/{checks} PASS');return int(bool(fails))
if __name__=='__main__':raise SystemExit(main())
