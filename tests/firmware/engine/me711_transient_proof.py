#!/usr/bin/env python3
r"""
me711_transient_proof.py - transient fuel in the LINKED image (c167sim):
hctrans711.c's page reads and T1 time base around the host-tested core
(tests/host/test_hctrans_host.py).

    py tests\firmware\engine\me711_transient_proof.py

  A  transEnable 0: hc_trans_fuel() returns its input (no film, no after-start)
  B  transEnable 1, steady: the delivered time converges to the wanted one
     (no long-term bias)
  C  a step up in the steady model: the first delivered time EXCEEDS the new
     want (the wall takes its share), then converges back
  D  a cut: 0 delivered; the re-entry delivers more than the want (film rebuild)
  E  after-start: +asPct at the end of cranking, decaying over asDecayMs
  F  warm-up is INTERPOLATED between curve points (15 C on the AWT curve:
     half-way between 131 % and 122 %), not the nearest cell below
The time base is T1 (1.25 MHz); the rig advances it 10 ms per call.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_config_state_test as T      # noqa: E402

CHECKS = FAILS = 0
T1 = 0xFE50 + 2          # T1 register (reg167.h: T1 at 0xFE52)


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += 0 if ok else 1
    print("  [%s] %-60s %s" % ("PASS" if ok else "FAIL", name, detail))


def off(name):
    """a page offset, from hcconfig.h or the generated header"""
    try:
        return T.d(T._cfg, name)
    except (SystemExit, AttributeError, TypeError):
        return T.d(T._gen, name)


class Rig:
    def __init__(self):
        self.r = T.boot()
        self.t = 1000
        self.r.m.w16(T1, self.t)
        self.r("hc_trans_init")

    def page8(self, name, v):
        self.r("hc_cal_set_u8", off(name), v)

    def page16(self, name, v):
        self.r("hc_cal_set_u16", off(name), v)

    def curve(self, name, vals):
        base = off(name)
        for i, v in enumerate(vals):
            self.r("hc_cal_set_u8", base + i, v)

    def fuel(self, base, rpm=2000, crank=0, cut=0, ms=10):
        self.t = (self.t + 1250 * ms) & 0xFFFF
        self.r.m.w16(T1, self.t)
        self.r.m.w16(T.sym("trg_rpm") & 0xFFFF, rpm)
        return self.r("hc_trans_fuel", base, crank, cut)


def main() -> int:
    import me711_image as PI
    print("=== transient fuel in the linked image - %s ===" % PI.STEM)
    k = Rig()
    ax = [9700 + 100 * i for i in range(16)]
    for i, a in enumerate(ax):
        k.r("hc_cal_set_u16", off("CAL_CLT_ENR_AX") + 2 * i, a)
    k.curve("CAL_CLT_ENR_VAL", [170, 160, 150, 140, 131, 122, 116, 111, 107,
                                104, 102, 100, 100, 100, 100, 100])
    k.curve("CFG_U_WW_X_PCT", [40] * 16)
    k.curve("CFG_U_WW_TAU_20MS", [20] * 16)            # 0.4 s
    k.curve("CFG_U_AS_PCT", [0] * 16)
    k.page16("CFG_U_AS_DECAY_MS", 0)
    k.r.m.w16(T.sym("eng_clt_dc") & 0xFFFF, 10800)     # 80 C

    k.page8("CFG_U_TRANS_ENABLE", 0)
    outs = {k.fuel(5000) for _ in range(20)}
    check("A transEnable 0: the input passes through", outs == {5000},
          str(sorted(outs)))

    k.page8("CFG_U_TRANS_ENABLE", 1)
    for _ in range(600):
        o = k.fuel(5000)
    check("B steady: delivered converges to the want (+/-1 %)",
          abs(o - 5000) <= 50, "%d us" % o)
    first = k.fuel(8000)
    for _ in range(400):
        o = k.fuel(8000)
    check("C step 5 -> 8 ms: first delivery above the want, then converges",
          first > 8000 and abs(o - 8000) <= 80, "first %d, settled %d" % (first, o))
    cut = [k.fuel(8000, cut=1) for _ in range(100)]
    reentry = k.fuel(8000)
    check("D cut: nothing delivered; the re-entry rebuilds the film",
          set(cut) == {0} and reentry > 8000, "re-entry %d" % reentry)

    k.page8("CFG_U_TRANS_ENABLE", 1)
    k.curve("CFG_U_WW_X_PCT", [0] * 16)
    k.curve("CFG_U_AS_PCT", [50] * 16)
    k.page16("CFG_U_AS_DECAY_MS", 2000)
    k.fuel(4000, crank=1)
    a0 = k.fuel(4000, crank=0, ms=10)
    for _ in range(99):
        mid = k.fuel(4000, crank=0, ms=10)
    for _ in range(150):
        end = k.fuel(4000, crank=0, ms=10)
    check("E after-start: +50 % at the end of cranking, ~half at 1 s, "
          "none after 2 s", 5900 <= a0 <= 6000 and 4900 <= mid <= 5100
          and end == 4000, "%d / %d / %d" % (a0, mid, end))

    w = k.r.callb("hc_trans_warmup", 10150)            # 15 C
    check("F warm-up interpolated: 15 C = half-way 131..122 % (126..127)",
          w in (126, 127), "%d %%" % w)
    print("\n%d checks, %d failed" % (CHECKS, FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
