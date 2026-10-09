"""Compile and run the PEC6 RX ring host test (pure ring arithmetic only).

The test defines HC_PECRX_HOST_TEST and includes hcpecrx_me711.c directly, so it
builds the SFR-free ring functions without <reg167.h> or the target header.
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import host_c_test as H


MODULE_DIR = H.HCP.include_dirs("me711")


def main() -> int:
    H.run("hcpecrx", [H.HOST_TESTS / "test_hcpecrx.c"], MODULE_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
