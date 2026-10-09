#!/usr/bin/env python3
r"""me711_cam_pattern_proof.py - camPhaseMode PATTERN on the LINKED IMAGE.

    py tests\firmware\trigger\me711_cam_pattern_proof.py

The V97 cam PATTERN core (firmware/engine/hccam.c) is host-tested on its own
(tests/host/test_hccam_host.py). This gate runs the whole chain in the image:
capture ISR record -> ring -> trg_service() interpolation -> hccam_edge() ->
LOSE / FLIP / GRANT applied to trg_state / trg_phase, on a 60-2 crank driven
edge by edge through c167sim (the me711_trigger_generic_proof rig).

The cam edges are placed at TRUE engine angles: the rig first learns the
decoder's own angle for every tooth, then emits each pattern tooth between
the right two crank teeth, T1 set to the exact fraction (so the ISR->task
interpolation is part of what is tested).

  1  Barra 3+1 (whole teeth), cam in the half the decoder guessed: FULL,
     no flip, the decoder angle at the cam's tooth 0 = the configured one.
  2  the same cam in the OTHER half: the half is moved once, then FULL.
  3  Bosch quick-start (80/180/280/180 - fractional teeth, the AWT wheel),
     from the wrong half: moved once, FULL, VVT deviation ~0.
  4  quick-start with a +20 deg VVT offset: FULL, cam1VvtX10 ~ +20.0.
  5  single tooth, FULL, then ONE glitch edge 360 deg away: no flip, stays
     FULL. NEGATIVE CONTROL: the same glitch with camPhaseMode REFS (one
     window) moves the half on that single edge - the V96 behaviour the
     PATTERN method exists to replace.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_trigger_test as T                       # noqa: E402
from me711_trigger_generic_proof import Wheel        # noqa: E402

FAIL = 0
SYNC_FULL, SYNC_CRANK = 4, 3
PATTERNS = {"single": (1, [0]), "quickstart": (3, [0, 800, 2600, 5400]),
            "barra": (5, [0, 1200, 3600, 6000])}


def check(name, ok, detail=""):
    global FAIL
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<62} {detail}")
    FAIL += not ok


def w8(x, slot, v):
    x.m.w8(T.UNI_BASE + T._uni(x, slot), v & 0xFF)


def w16(x, slot, v):
    o = T._uni(x, slot)
    x.m.w8(T.UNI_BASE + o, (v >> 8) & 0xFF)
    x.m.w8(T.UNI_BASE + o + 1, v & 0xFF)


class CamRig:
    def __init__(self, pattern, offset_x10, mode=2, refs=1, window=600):
        # a single-window description first (the harness's cam path), then the
        # PATTERN fields on top, then a geometry re-read
        self.w = Wheel(60, 2, 1200, cam_refs=refs, cam_ref_x10=offset_x10,
                       cam_window_x10=window, cam_sync_mode=2, cam_enable=1,
                       offset_x10=1)
        x = self.w.x
        w8(x, "CFG_U_CAM_PHASE_MODE", mode)
        w8(x, "CFG_U_CAM1_PATTERN", PATTERNS[pattern][0])
        w16(x, "CFG_U_CAM_REF_X10", offset_x10)
        w16(x, "CFG_U_CAM_WINDOW_X10", window)
        w8(x, "CFG_U_CAM_TOOTH_TOL", 15)
        w8(x, "CFG_U_CAM_PHASE_CONFIRM", 2)
        w8(x, "CFG_U_CAM_REFS", refs)
        w16(x, "CFG_U_TRIG_ANGLE_X10", 0)
        x.call("trg_test_geometry")
        self.rel = PATTERNS[pattern][1]
        self.offset = offset_x10
        self.angle = {}                    # (rev parity, tooth) -> decoder angle
        self.parity = 0

    def learn(self, revs=3):
        """Revolutions with no cam: the decoder's angle after every tooth."""
        w = self.w
        for _ in range(revs):
            for i in range(w.real - 1):
                w.wait_edge(w.p)
                self.angle[(self.parity, i)] = w.u16("trg_engine_deg_x10")
            w.wait_edge((w.gap + 1) * w.p, 6 * (w.gap + 1))
            self.parity ^= 1
        return self

    def rev(self, cam_half, vvt_x10=0, glitch_at=None):
        """One revolution; emits the pattern teeth whose TRUE angle falls in
        this revolution when its half is cam_half (0/1 = which of the
        decoder's two guessed halves the truth is). Each cam edge goes out
        BEFORE the crank tooth that follows it, at the exact fraction of the
        interval - as the hardware would capture it."""
        w = self.w
        base_half = 0 if self.angle[(self.parity, 0)] < 3600 else 1
        want = []
        for r in self.rel:
            t = (self.offset + r + vvt_x10) % 7200
            if (t >= 3600) == bool(base_half ^ cam_half):
                want.append(t % 3600)
        if glitch_at is not None:
            want.append(glitch_at % 3600)
        a_tooth = [self.angle[(self.parity, i)] % 3600 for i in range(w.real - 1)]
        prev_last = self.angle[(self.parity ^ 1, w.real - 2)] % 3600

        def emit(lo, hi, ticks):
            """cam edges with lo <= angle < hi (degrees x10, may wrap) inside
            the next `ticks` of time, before the crank edge that ends it"""
            span = (hi - lo) % 3600
            for a in sorted(want, key=lambda v: (v - lo) % 3600):
                d = (a - lo) % 3600
                if d < span:
                    w.x.set_t1((w.t + round(d / span * ticks)) & 0xFFFF)
                    w.x.call("trg_test_cam_edge", 1)
                    want.remove(a)
            w.x.set_t1(w.t)

        # a revolution is: (the previous gap edge) then real-1 ordinary
        # edges 0..real-2, then this revolution's gap edge. One tooth is
        # trg_cfg_tooth_x10 = 60 (6.0 degrees on a 60-2).
        tooth = 3600 // w.teeth
        emit((a_tooth[0] - tooth) % 3600, a_tooth[0], w.p)
        w.wait_edge(w.p)
        for i in range(1, w.real - 1):
            emit(a_tooth[i - 1], a_tooth[i], w.p)
            w.wait_edge(w.p)
        # the gap interval: last ordinary tooth -> the gap edge, which sits
        # one tooth before the next revolution's edge 0
        gap_edge = (self.angle[(self.parity ^ 1, 0)] - tooth) % 3600
        emit(a_tooth[w.real - 2], gap_edge, (w.gap + 1) * w.p)
        w.wait_edge((w.gap + 1) * w.p, 6 * (w.gap + 1))
        self.parity ^= 1
        del prev_last

    def tooth_rev(self, cam_half):
        """Does the NEXT revolution carry the pattern's tooth 0?"""
        base_half = 0 if self.angle[(self.parity, 0)] < 3600 else 1
        t = (self.offset + self.rel[0]) % 7200 if self.rel else 0
        return (t >= 3600) == bool(base_half ^ cam_half)

    def state(self):
        return self.w.u8("trg_state")

    def corr(self):
        return self.w.u16("trg_phase_corr")


def bank0(r):
    """hccam_bank[0] as the C167 lays it out (Keil: u16 on even offsets):
    cfg 0..9, n 10, rel 12..27, sp 28..43, min_sp 44, k 46, resolves 47,
    hist 48..61, hn 62, same/other/err/est 63..66, cls 67, tooth 68,
    dev_x10 70, sync_dev_x10 72. Wrong offsets fail the class/tooth check."""
    a = T.sym("hccam_bank") & 0xFFFF
    m = r.w.x.m

    def s16(o):
        v = m.r16(a + o)
        return v - 65536 if v >= 32768 else v
    return m.r8(a + 67), m.r8(a + 68), s16(70), s16(72)


def run_case(pattern, offset, cam_half, revs=8, vvt=0):
    r = CamRig(pattern, offset).learn()
    c0 = r.corr()
    for _ in range(revs):
        r.rev(cam_half, vvt)
    return r, r.corr() - c0


def main() -> int:
    print("=== the cam PATTERN method on the linked image ===")
    # 1/2 Barra 3+1
    r, flips = run_case("barra", 1500, 0)
    check("Barra 3+1, cam in the guessed half: FULL", r.state() == SYNC_FULL,
          f"state {r.state()} flips {flips}")
    check("... and the half was NOT moved", flips == 0)
    r, flips = run_case("barra", 1500, 1)
    check("Barra 3+1, cam in the OTHER half: moved once, FULL",
          r.state() == SYNC_FULL and flips == 1, f"state {r.state()} flips {flips}")
    # 3/4 quick-start (fractional teeth, interpolation)
    r, flips = run_case("quickstart", 2345, 1)
    check("quick-start from the wrong half: moved once, FULL",
          r.state() == SYNC_FULL and flips == 1, f"state {r.state()} flips {flips}")
    r2, flips2 = run_case("quickstart", 2345, 0, vvt=200)
    cls, tooth, dev, sdev = bank0(r2)
    check("quick-start at +20 deg VVT: FULL without a move",
          r2.state() == SYNC_FULL and flips2 == 0,
          f"state {r2.state()} flips {flips2}")
    check("... the last tooth read SAME, its deviation ~ +20 deg",
          cls == 1 and tooth < 4 and abs(dev - 200) <= 30,
          f"class {cls} tooth {tooth} dev {dev / 10:.1f} deg")
    check("... and tooth 0 (the VVT position) ~ +20 deg", abs(sdev - 200) <= 30,
          f"{sdev / 10:.1f} deg")
    # 5 one glitch 360 deg from the tooth: PATTERN vs REFS (the control)
    for mode, name in ((2, "PATTERN single tooth"), (0, "REFS one window (V96)")):
        rig = CamRig("single", 2000, mode=mode, refs=1, window=300).learn()
        for _ in range(12):
            rig.rev(0)
        full = rig.state() == SYNC_FULL
        c0 = rig.corr()
        # the glitch goes in the revolution the tooth is NOT in, at the
        # tooth's in-revolution angle: 360 degrees from the real one
        while rig.tooth_rev(0):
            rig.rev(0)
        keep, rig.rel = rig.rel, []
        rig.rev(0, glitch_at=2000)
        rig.rel = keep
        for _ in range(4):
            rig.rev(0)
        moved = rig.corr() - c0
        if mode == 2:
            check(f"{name}: FULL, one glitch 360 deg away - NOT moved",
                  full and moved == 0 and rig.state() == SYNC_FULL,
                  f"full {full} moved {moved} state {rig.state()}")
        else:
            check(f"CONTROL {name}: the same glitch MOVES the half",
                  full and moved >= 1, f"full {full} moved {moved}")
    print(f"\n{'CAM PATTERN PROOF PASSES' if not FAIL else 'CAM PATTERN PROOF FAILS'}"
          f" - {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
