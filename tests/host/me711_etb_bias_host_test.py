from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import host_c_test as H
import subprocess
import build_hanicore_me711 as B
cc=H.compiler()
if cc is None:
    print('SKIP: no host C compiler; bias qualification unavailable')
    raise SystemExit(0)
env=H.env_for(cc);exe=H.TMP/'etb_bias_test.exe'
H.build(cc,env,[H.HOST_TESTS/'test_hc_etb_bias.c'],H.SHARED,exe,flags=H.STRICT+('-Wno-unused-function',))
subprocess.run([str(exe)],check=True,env=env)
# Negative control: the first ETB bench image's map, whose 32-byte NCODE reserve
# the guard must reject. It is raw evidence (local), not part of a checkout.
old_map=hcpaths.RAW_EVIDENCE/'ETB_CHARACTERIZATION/bench_release/HaniCore_ME711_etb_characterization_bench.M66'
if old_map.exists():
    try:B.check_ncode_reserve(old_map.read_text())
    except SystemExit:print('PASS original 32-byte NCODE reserve rejected')
    else:raise AssertionError('NCODE guard failed to reject original image')
else:
    print('SKIP control: %s not present (raw evidence store)' % old_map)
B.check_ncode_reserve((H.ROOT/'bins/hanicore/HaniCore_ME711_v102_dev.M66').read_text())
