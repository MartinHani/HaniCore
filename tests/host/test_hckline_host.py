"""Compile and run the isolated KWP vehicle-mode core host test.

firmware/comms/hckline.c against tests/host/test_hckline.c, through host_c_test.py.
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import host_c_test as H


def main() -> int:
    src = [H.HCP.find("hckline.c"), H.HOST_TESTS / "test_hckline.c"]
    got = H.run("hckline", src)
    if got:
        # the Audi 2.7T build (24 MHz: no 115200) compiles hckline.c with
        # HCKLINE_NO_115200 - the same core, GOFAST 115200 refused
        import subprocess
        cc, env = got
        exe = H.TMP / "hc_hckline_no115200_host.exe"
        H.build(cc, env, src, H.SHARED, exe,
                flags=list(H.STRICT) + ["-DHCKLINE_NO_115200"])
        subprocess.run([str(exe)], check=True, env=env)
        print("PASS: hckline host tests (HCKLINE_NO_115200)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
