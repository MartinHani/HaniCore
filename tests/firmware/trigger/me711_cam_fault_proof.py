#!/usr/bin/env python3
r"""
me711_cam_fault_proof.py - the Quick-Start LEVEL cam decoder under the faults
a real cam produces, on the LINKED image in c167sim.

    py tests\firmware\trigger\me711_cam_fault_proof.py

The V92 proof (me711_trigger_scheduler_proof) establishes acquisition from either
half, 720-degree continuity, wasted spark across a phase move and the stuck
cam. This gate adds what the physical cam can do that those do not cover:

  K  a ONE-revolution level glitch at the check tooth after full sync: the
     cycle may be withdrawn, the crank is never lost, full sync returns
     within confirm + 3 revolutions, and TDC#1 is still where it was (no
     half left wrong by a single bad sample)
  L  cam ABSENT from key-on (constant level, no edges): crank sync only,
     never full, no crank loss
  M  the cam RETURNS after L: full sync within confirm + 3 revolutions, on
     the right half
  N  a noise PULSE between checks (two edges, level restored before the
     check tooth) every revolution: full sync kept, no cycle loss, no
     half correction
  O  acquisition time: from the first crank sync to full sync, revolutions
  P  THE ASSIGNMENT DECIDES THE HALF: with camPhaseLevel inverted the
     decoder still acquires - on the OTHER half (TDC#1 360 degrees off).
     Nothing in the signal can tell the two apart; the assignment is a
     physical fact to be measured (tests/physical/me711_cam_qualify.py), and until
     it is, the AWT preset must stay crank-only (batch + wasted spark).

Geometry and the AWT pattern are the V92 proof's (rusEFI quick-start sectors
anchored on the car's observed edges at physical 114/294). NOT PHYSICAL.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_trigger_scheduler_proof as V      # noqa: E402

CHECK_PHYS = 204          # PHASE_ANGLE_X10 1260 = engine 126.0 = rev X phys 204
CONFIRM = 2
CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += 0 if ok else 1
    print("  [%s] %-62s %s" % ("PASS" if ok else "FAIL", name, detail))
    return ok


class Rig(V.Rig):
    def __init__(self, PT, level_cfg=0, **kw):
        super().__init__(PT, **kw)
        self.flip = set()        # physical cycle angles whose level is inverted
        self.pulse = False       # a noise pulse after every tooth at phys 30
        if level_cfg:
            h = V.gen_h()
            self.x.m.w8(0x380000 + 12 + V.uoff("CFG_U_CAM_PHASE_LEVEL", h), 1)
            self.x.call("trg_init")
            self.x.call("trg_test_geometry")

    def set_cam(self, c):
        low = V.cam_low(c) if self.stuck is None else self.stuck
        if c % 720 in self.flip:
            low = not low
        v = self.x.m.sfr.get(V.P2, 0)
        self.x.m.sfr[V.P2] = (v & ~V.CAM_BIT) if low else (v | V.CAM_BIT)
        return low

    def edge(self):
        super().edge()
        if self.pulse and self.c % 360 == 30 and self.stuck is None:
            # two cam edges well away from the check tooth, level restored
            lvl = self.cam
            v = self.x.m.sfr.get(V.P2, 0)
            self.x.m.sfr[V.P2] = (v | V.CAM_BIT) if lvl else (v & ~V.CAM_BIT)
            self.x.call("trg_test_cam_edge", 1)
            self.x.m.sfr[V.P2] = (v & ~V.CAM_BIT) if lvl else (v | V.CAM_BIT)
            self.x.call("trg_test_cam_edge", 1)

    def tdc_ok(self):
        """rev X physical 84 must be engine 6.0 (TDC#1 compression at 78)."""
        while self.c % 720 != 84:
            self.tooth()
        return self.u16("trg_engine_deg_x10")

    def revs_until(self, pred, limit=12):
        for n in range(1, limit + 1):
            self.rev()
            if pred():
                return n
        return None


def run(PT):
    if "trg_ph_status" not in PT.MAP:
        check("LEVEL cam method present", False, "no trg_ph_status symbol")
        return
    full = lambda r: r.u16("trg_state") == 4          # noqa: E731

    # O: acquisition time
    r = Rig(PT, sync_mode=2, cam_level=True)
    r.edge()
    n_crank = r.revs_until(lambda: r.u16("trg_state") >= 3)
    n_full = r.revs_until(lambda: full(r))
    check("O acquisition: crank sync, then full sync within confirm + 3 revs",
          n_crank is not None and n_full is not None and n_full <= CONFIRM + 3,
          "crank after %s rev, full %s rev later" % (n_crank, n_full))

    # K: one-revolution glitch at the check tooth
    r.rev(); r.rev()
    lost0, crank0 = r.u16("trg_cycle_lost"), r.u16("trg_synclost")
    r.flip = {CHECK_PHYS, CHECK_PHYS + 360}
    r.rev()
    r.flip = set()
    n = r.revs_until(lambda: full(r))
    check("K glitch: crank never lost", r.u16("trg_synclost") == crank0,
          "crankLost %d" % r.u16("trg_synclost"))
    check("K glitch: full sync back within confirm + 3 revs",
          n is not None and n <= CONFIRM + 3,
          "after %s rev, cycleLost +%d" % (n, r.u16("trg_cycle_lost") - lost0))
    r.rev()
    eng = r.tdc_ok()
    check("K glitch: TDC#1 still on the right half", eng == 60,
          "engine %.1f at rev X phys 84" % (eng / 10))

    # L / M: cam absent from key-on, then returning
    r = Rig(PT, sync_mode=2, cam_level=True)
    r.stuck = False                     # constant HIGH at the CPU, no edges
    r.start(6)
    check("L absent: crank sync kept, never full",
          r.u16("trg_state") == 3 and r.u16("trg_cycle_acq") == 0,
          "state %d acq %d" % (r.u16("trg_state"), r.u16("trg_cycle_acq")))
    check("L absent: no crank loss", r.u16("trg_synclost") == 0)
    r.stuck = None
    n = r.revs_until(lambda: full(r))
    check("M returns: full sync within confirm + 3 revs",
          n is not None and n <= CONFIRM + 3, "after %s rev" % n)
    r.rev()
    eng = r.tdc_ok()
    check("M returns: on the right half", eng == 60,
          "engine %.1f" % (eng / 10))

    # N: noise pulses between checks
    r = Rig(PT, sync_mode=2, cam_level=True)
    r.start(6)
    lost0 = r.u16("trg_cycle_lost")
    corr0 = r.u16("trg_phase_corr")
    r.pulse = True
    for _ in range(6):
        r.rev()
    check("N noise pulses: full sync kept", full(r),
          "state %d" % r.u16("trg_state"))
    check("N noise pulses: no cycle loss, no half correction",
          r.u16("trg_cycle_lost") == lost0 and r.u16("trg_phase_corr") == corr0,
          "cycleLost +%d corr +%d" % (r.u16("trg_cycle_lost") - lost0,
                                      r.u16("trg_phase_corr") - corr0))

    # P: the assignment decides the half
    r = Rig(PT, level_cfg=1, sync_mode=2, cam_level=True)
    r.start(6)
    check("P inverted assignment: still acquires full sync", full(r),
          "state %d" % r.u16("trg_state"))
    eng = r.tdc_ok()
    check("P inverted assignment: TDC#1 lands 360 deg away (signal cannot "
          "tell)", eng == 3660, "engine %.1f at rev X phys 84" % (eng / 10))


def main():
    import me711_trigger_test as PT
    print("=== Quick-Start LEVEL cam under faults ===")
    run(PT)
    print("\n%d checks, %d failed" % (CHECKS, FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
