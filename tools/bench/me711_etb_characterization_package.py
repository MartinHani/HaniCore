#!/usr/bin/env python3
"""Freeze a bench-only image with normal DBW inhibited and the existing journal unchanged."""
from pathlib import Path
import argparse,hashlib,json,shutil,subprocess,sys,tempfile
ROOT=Path(__file__).resolve().parents[2]
def sha(b):return hashlib.sha256(b).hexdigest().upper()
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--backup',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    old=a.backup.read_bytes();assert len(old)==0x100000
    sys.path.insert(0, str(ROOT / "tools" / "lib"))
    import me711_store as R
    import me711_v101_compat as V
    best,seen=R.newest_record(old,V.LAYOUT,R.hdr(R.CFG_H,'HC_CFG_VERSION',10));assert best,'No known valid calibration journal'
    a.out.mkdir(parents=True,exist_ok=True)
    (a.out/'journal_audit.json').write_text(json.dumps(dict(records=seen,selected_cell=best[0],generation=best[1],backup_sha256=sha(old)),indent=2))
    (a.out/'pre_flash_page.bin').write_bytes(best[2])
    target=ROOT/'firmware/targets/me711/hctarget.h'
    original=target.read_bytes();assert b'#define TGT_ETB_DIAGNOSTIC_BENCH    0' in original
    saved=Path(tempfile.mkdtemp(prefix='hc_sweep_generic_'))
    files=list((ROOT/'bins/hanicore').glob('HaniCore_ME711_v102_dev.*'))
    for p in files:shutil.copy2(p,saved/p.name)
    try:
        target.write_bytes(original.replace(b'#define TGT_ETB_DIAGNOSTIC_BENCH    0',b'#define TGT_ETB_DIAGNOSTIC_BENCH    1'))
        proc=subprocess.run([sys.executable,str(ROOT/'tools/build/build_hanicore_me711.py')],cwd=ROOT,capture_output=True,text=True)
        (a.out/'bench_build.log').write_text(proc.stdout+proc.stderr)
        if proc.returncode:raise RuntimeError('Bench build failed; see bench_build.log')
        stem=ROOT/'bins/hanicore/HaniCore_ME711_v102_dev'
        image=bytearray(stem.with_suffix('.bin').read_bytes());image[0x60000:]=old[0x60000:]
        assert bytes(image[0x60000:])==old[0x60000:]
        dest=a.out/'HaniCore_ME711_etb_characterization_bench.bin';dest.write_bytes(image)
        shutil.copy2(stem.with_suffix('.M66'),dest.with_suffix('.M66'))
        manifest=json.loads(stem.with_suffix('.json').read_text());manifest.update(sha256=sha(image),bench_only=True,normal_dbw_inhibited=True,calibration_journal_sha256=sha(old[0x60000:]),calibration_journal_unchanged=True)
        dest.with_suffix('.json').write_text(json.dumps(manifest,indent=2))
        for suffix in ('','_forensic','_userdefined_fallback'):
            shutil.copy2(ROOT/f'tunerstudio/hanicore_me711_v102_dev{suffix}.ini',a.out/f'hanicore_me711_etb_characterization_bench{suffix}.ini')
        print('Frozen bench candidate',dest,'SHA256',sha(image),flush=True)
        print('Existing journal preserved byte-for-byte; no calibration Burn.',flush=True)
    finally:
        target.write_bytes(original)
        for p in files:shutil.copy2(saved/p.name,p)
    return 0
if __name__=='__main__':raise SystemExit(main())
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
