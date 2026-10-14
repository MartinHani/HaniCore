#!/usr/bin/env python3
r"""me711_tacho_proof.py - the rev-counter output on cavity 37 (P2.13 / CC13).

    py tests\firmware\outputs\me711_tacho_proof.py [--control <bins dir>]

WHAT (2026-10-11): the instrument cluster's engine-speed signal. Cavity 37
A_T_TN is driven by a CJ920 low side from main CPU P2.13 (hctarget.h
TGT_TACHO_*). SOFTWARE-TOGGLED since the car session of 2026-10-11 (the
needle did not move with the CC13 hardware-compare version, proven only
against a simulator model written from the same assumption): the 1 ms tick
writes P2.13 with BSET/BCLR when a half-period of T1 has elapsed - as the
stock 022906032BT drives it. Frequency = rpm x cylinders / 120 (FR TN 3.20).

Simulator (linked image in c167sim, real main loop + tick, the AWT preset
page, 60-2 crank + cam). The PIN is sampled every 100 us (c167sim keeps the
port latch), so this measures the port, not an internal counter:
  T1 at 900 / 3000 / 6000 rpm: P2.13 is an output and its edges run at
     rpm x 4 / 120 Hz within 2 % (first-to-last edge over 300 ms; a single
     edge may be one tick late, the average may not drift);
  T2 engine stopped: within 0.6 s the pin is an INPUT again, no edges;
  T3 pinTacho unrouted (255): at 3000 rpm never an output, no edges;
  T4 the rev-counter TEST ('!N' state, engine stopped): 3000 rpm = 100 Hz
     within 2 %, released again after its 6 s.
--control <bins dir> on the 2026-10-11 car image (EF8582E6, hardware
compare): T1 must FAIL in this pin-level measurement only if c167sim does
not model compare mode 1; it DOES, so the control is the test mode T4,
which that image does not have.
SIMULATOR ONLY - the stage and the cluster: press "Test rev counter" in
TunerStudio with the engine stopped and watch the needle.
"""
from __future__ import annotations

import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if "--control" in sys.argv:
    os.environ["HANICORE_ME711_BINS"] = sys.argv[sys.argv.index("--control") + 1]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402
import me711_runtime_stress as M  # noqa: E402

DP2 = 0xFFC2
BIT = 1 << 13
FAILS = 0


def check(name, ok, detail=""):
    global FAILS
    FAILS += 0 if ok else 1
    print("  [%s] %-62s %s" % ("PASS" if ok else "FAIL", name, detail))


def page(tacho):
    """The AWT preset page (as me711_runtime_stress.build_awt_page), with
    pinTacho set explicitly."""
    import me711_config_state_test as T
    import me711_preset_apply_proof as AP
    r = T.boot()
    AP.press_apply(r, 3)
    AP.service(r)
    assert AP.och(r, 764) & 0xFF == 1, "APPLY refused"
    assert r("hc_cfg_mgr_commit_burn", 1, steps=60_000_000) == 0
    AP.install_test_fuel(r)
    AP.set_active(r, AP.off("CFG_U_PIN_TACHO"), tacho, 1)
    r("hc_cfg_mgr_init")
    r("hc_cfg_commit", steps=20_000_000)
    return bytes(r.m.r8(0x380000 + i) for i in range(12 + 4096))


P2 = 0xFFC0
TACHO_SRAM = 0x380000 + 0x6F60          # hctarget.h TGT_RAM_TACHO
SAMPLE_US = 100


def window(s, us, rpm):
    """Run `us` at `rpm` (None = stopped) sampling P2.13 every SAMPLE_US;
    return the edge times (us) and whether the pin was ever an output."""
    out = False
    edges = []
    t = 0
    last = bool(s.mem.sfr.get(P2, 0) & BIT)
    fn = (lambda _t, r=rpm: r) if rpm else None
    while t < us:
        s.run_us(SAMPLE_US, fn)
        t += SAMPLE_US
        o = bool(s.mem.sfr.get(DP2, 0) & BIT)
        out |= o
        lv = bool(s.mem.sfr.get(P2, 0) & BIT)
        if o and lv != last:
            edges.append(t)
        last = lv
    return edges, out


def freq(edges):
    if len(edges) < 6:
        return None
    return (len(edges) - 1) / (2.0 * (edges[-1] - edges[0]) * 1e-6)


def main() -> int:
    print("=== tacho output, cavity 37 (simulator) ===")
    print("  image", M.PI.image())
    s = M.Stress(page(37), ts=False)
    s.boot()
    M.segment(s, "crank 250", 300_000, lambda t: 250, 250, [])
    prev = 250
    for rpm in (900, 3000, 6000):
        M.segment(s, "ramp", 200_000, M.ramp(prev, rpm, 0.2), rpm, [])
        window(s, 200_000, rpm)                      # settle the filter
        tg, out = window(s, 300_000, rpm)
        f, want = freq(tg), rpm * 4 / 120.0
        check("T1 %d rpm: P2.13 toggles at rpm x 4 / 120 = %.1f Hz (+-2 %%)"
              % (rpm, want), f is not None and out and abs(f - want) <= 0.02 * want,
              "%s Hz, %d toggles, output %s" % (None if f is None else round(f, 2),
                                                len(tg), out))
        prev = rpm
    window(s, 600_000, None)                         # stall timeout
    tg, out = window(s, 300_000, None)
    check("T2 stopped: P2.13 released (input) and no toggles",
          not out and not tg and not (s.mem.sfr.get(DP2, 0) & BIT),
          "toggles %d, output %s" % (len(tg), out))
    # T4: the rev-counter test, engine stopped (hc_tacho_test's own state:
    # test_ms at +6, test_rpm at +8 of hc_tacho_t)
    s.mem.w16(TACHO_SRAM + 8, 3000)
    s.mem.w16(TACHO_SRAM + 6, 6000)
    window(s, 100_000, None)
    tg, out = window(s, 300_000, None)
    f = freq(tg)
    ok = f is not None and out and abs(f - 100.0) <= 2.0
    window(s, 6_000_000, None)
    tg2, out2 = window(s, 300_000, None)
    check("T4 test: 3000 rpm = 100 Hz with the engine stopped, released after",
          ok and not tg2 and not (s.mem.sfr.get(DP2, 0) & BIT),
          "%s Hz, output %s; after: %d edges" % (None if f is None else round(f, 2),
                                                out, len(tg2)))

    u = M.Stress(page(255), ts=False)
    u.boot()
    M.segment(u, "crank 250", 300_000, lambda t: 250, 250, [])
    M.segment(u, "ramp", 200_000, M.ramp(250, 3000, 0.2), 3000, [])
    tg, out = window(u, 300_000, 3000)
    check("T3 unrouted: never an output, never toggles at 3000 rpm",
          not out and not tg, "toggles %d, output %s" % (len(tg), out))
    print("\nPASS" if not FAILS else "\n%d FAIL" % FAILS)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
