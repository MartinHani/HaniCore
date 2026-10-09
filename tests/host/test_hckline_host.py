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
    H.run("hckline", [H.HCP.find("hckline.c"), H.HOST_TESTS / "test_hckline.c"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
