r"""
me711_cal_u16_proof.py - hc_cal_u16() returns hc_cal_u8(off) << 8 | hc_cal_u8(off + 1)
at EVERY page offset, on the linked image in c167sim.

hc_cal_u16() reads a word inside one part of the page (near scalars, the SRAM
tables) directly since 2026-11-04 (issue 05: it was two hc_cal_u8() calls, a
sixth of the 2.7T's main loop at 6500 rpm) and falls back to the byte reads
for a word that straddles a part boundary or leaves the page. The page is
filled with a pattern no two neighbouring bytes share, so a swapped, shifted
or wrong-part read cannot pass.

    py tests\firmware\config\me711_cal_u16_proof.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402

import me711_config_state_test as T  # noqa: E402


def main() -> int:
    r = T.boot()
    size = int(re.search(r"#define\s+HC_CFG_SIZE\s+(\d+)",
                         (ROOT / "firmware/config/hcconfig.h").read_text()).group(1))
    pat = lambda o: (o * 7 + 3 + (o >> 8)) & 0xFF          # noqa: E731
    for o in range(size):
        r("hc_cal_set_u8", o, pat(o))
    bad = []
    for o in range(size + 2):
        hi = r("hc_cal_u8", o) & 0xFF
        lo = r("hc_cal_u8", o + 1) & 0xFF
        w = r("hc_cal_u16", o) & 0xFFFF
        if w != ((hi << 8) | lo):
            bad.append((o, w, hi, lo))
    ok_fill = all((r("hc_cal_u8", o) & 0xFF) == pat(o) for o in (0, 127, 128, 4095, 4096, size - 1))
    print("  [%s] the pattern reached every part of the page" % ("PASS" if ok_fill else "FAIL"))
    print("  [%s] hc_cal_u16 == the two byte reads at %d offsets%s"
          % ("PASS" if not bad else "FAIL", size + 2,
             "" if not bad else "  first bad: off %d word %04X bytes %02X %02X" % bad[0]))
    return 0 if ok_fill and not bad else 1


if __name__ == "__main__":
    sys.exit(main())
