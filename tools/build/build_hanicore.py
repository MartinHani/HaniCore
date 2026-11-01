#!/usr/bin/env python3
r"""
build_hanicore.py - build the firmware for one ECU, the way it is released.

    py tools\build\build_hanicore.py --board 4B0907551F
    py tools\build\build_hanicore.py --board all

--board is the ECU part number (022906032BT Porsche, 4B0907551F Audi 2.7T,
4F0910560 Audi 4F, 4B0906018DC VAG 1.8T ME7.5) or porsche / 27t / 4f / 18t,
or `all`. Writes bins\release\HaniCore_<board>_<part>_<build id>.bin and the
.ini for exactly that image. Every image carries the K-line updater: build
order is the .ini, the resident loader, then the image
(build_hanicore_me711.py --updater, which also runs the linked checks).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (translates --board aliases / part numbers)
import hc_board  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ORDER = ("porsche_me711", "audi_4f_v8", "vag_me71_c4", "vag_me75_dc")


def run(board: str, *cmd: str) -> None:
    env = dict(os.environ, HANICORE_BOARD=board)
    r = subprocess.run([sys.executable, *cmd], cwd=ROOT, env=env)
    if r.returncode:
        raise SystemExit("%s failed for %s" % (cmd[0], board))


def build(board: str) -> None:
    tag, part = hc_board.RELEASE_BOARD[board]
    print("=== %s %s ===" % (tag, part), flush=True)
    run(board, "tools/tuning/gen_ts_ini_me711.py")
    run(board, "tools/build/build_loader.py", "--board", board)
    run(board, "tools/build/build_hanicore_me711.py", "--board", board,
        "--updater")
    for f in sorted(hc_board.RELEASE_DIR.glob("HaniCore_%s_%s_*" % (tag, part))):
        print("  " + str(f.relative_to(ROOT)))


def main() -> int:
    if "--board" not in sys.argv or sys.argv.index("--board") + 1 >= len(sys.argv):
        print(__doc__)
        return 2
    want = sys.argv[sys.argv.index("--board") + 1]
    if want.lower() == "all":
        boards = ORDER          # the Porsche first: the 4F's checks use its map
    elif want in hc_board.RELEASE_BOARD:
        boards = (want,)
    else:
        raise SystemExit("--board %s: a part number (022906032BT, 4B0907551F, "
                         "4F0910560, 4B0906018DC), porsche/27t/4f/18t or all"
                         % want)
    for b in boards:
        build(b)
    return 0


if __name__ == "__main__":
    sys.exit(main())
