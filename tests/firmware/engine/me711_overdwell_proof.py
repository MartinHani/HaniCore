#!/usr/bin/env python3
r"""
me711_overdwell_proof.py - the maximum-dwell watch on a RUNNING engine, on
the LINKED image (c167sim), measured at the coil pins.

    py tests\firmware\engine\me711_overdwell_proof.py               the image me711_image names
    py tests\firmware\engine\me711_overdwell_proof.py --control     V98r2 (9BF22D32, the car
                                                    image): must FAIL

THE CAR (2026-10-02, V98r2 on the AWT): "when the throttle is opened more
sharply and the rpm rises, the engine begins dying as if the ignition were
being cut". The chain this gate reproduces:

  * the AWT runs alpha-N, so the ignition table's load is the THROTTLE: a
    sharp tip-in drops the advance by 20+ degrees at once;
  * a coil whose dwell already started is released at the NEW (later) spark
    angle, so its charge lasts dwell + the retard's time - at 1500 rpm 25 deg
    is 2.8 ms on a 2.7 ms dwell, beyond the 1.5 x dwell watch (4.05 ms);
  * the watch released it (correct - rusEFI auto-fires there) and V91..V98
    then LATCHED that coil OFF until the next sync loss (hc_ign_ovd_latch):
    every coil that charged across the step went dead, and only a stall
    (the cancel) brought it back.

CASES
  O1  steady 1500 rpm, wasted COP, 30 deg: every coil sparks every revolution,
      no overdwell.
  O2a a 25 deg retard step mid-dwell: MEASURED, the dwell is kept (the spark
      is queued by time from the dwell) - a tip-in's retard is NOT how this
      scheduler overdwells.
  O2b ONE overdwell (a single late release): the watch auto-fires once and
      afterwards EVERY coil keeps sparking - no latch (V98r2 latches the coil
      OFF until the engine stalls - the control fails here).
  O3  the protection that the latch exists for is kept: a coil that is driven
      ON again and again with no spark between (the V89 class: spark events
      missing) is released each time and LATCHED after the third.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

CONTROL_STEM = "HaniCore_ME711_v98_dev"
if "--control" in sys.argv:
    env = dict(os.environ, HANICORE_ME711_STEM=CONTROL_STEM)
    r = subprocess.run([sys.executable, __file__], env=env)
    ok = r.returncode != 0
    print("\nCONTROL (%s, V98r2): %s" % (CONTROL_STEM,
          "FAILS as it must" if ok else "PASSED - the gate cannot tell"))
    raise SystemExit(0 if ok else 1)

import me711_trigger_test as PT          # noqa: E402
import me711_trigger_scheduler_proof as V      # noqa: E402

CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += 0 if ok else 1
    print("  [%s] %-62s %s" % ("PASS" if ok else "FAIL", name, detail))
    return ok


class Rig(V.Rig):
    def __init__(self, rpm=1500):
        super().__init__(PT, sync_mode=1, cam_level=False)
        h = V.gen_h()
        u = 0x380000 + 12
        self.x.m.w8(u + V.uoff("CFG_U_INJ_STRATEGY", h), 0)   # batch
        self.x.m.w8(u + V.uoff("CFG_U_IGN_STRATEGY", h), 1)   # wasted COP
        self.x.call("trg_init")
        self.x.call("trg_test_geometry")
        self.p = round(1_250_000 / rpm)
        self.adv = 300
        self.force = 0           # coil bits driven ON every service step

    def model(self):
        m = self.x.m
        for n, v in (("eng_adv_x10", self.adv), ("eng_dwell_x100", 270),
                     ("eng_ti_base_us", 6000), ("eng_deadtime_us", 0),
                     ("eng_fuelcut", 0)):
            m.w16(PT.sym(n) & 0xFFFF, v)
        for n in ("hc_ignition_allowed", "hc_injection_allowed"):
            m.w16(PT.sym(n) & 0xFFFF, 1)
        m.w16(PT.sym("hc_cfg_validation") & 0xFFFF, 0)
        if self.force:
            self.x.call("hc_hal_out_group", 0, self.force, 1)

    def service_to(self, ticks):
        # finer than the base rig: the watch runs once a millisecond
        n = max(2, ticks // 250)
        t0, c0 = self.t, self.clock
        for q in range(1, n):
            self.x.set_t1((t0 + ticks * q // n) & 0xFFFF)
            self.clock = c0 + ticks * q // n
            self.model()
            self.x.call("trg_service")
            # the main loop's 1 ms-gated watch (hcmain_me711.c), on T1
            self.x.call("hc_drysched_overdwell_service",
                        (t0 + ticks * q // n) & 0xFFFF)
            self.log.append((self.clock, self.x.call("hc_hal_out_mask_ign"),
                             0, None))
        self.t = (t0 + ticks) & 0xFFFF
        self.clock = c0 + ticks

    def u(self, n):
        return self.x.m.r16(PT.sym(n) & 0xFFFF)

    def sparks_since(self, i0):
        """falling edges per coil bit in log[i0:]"""
        out = [0, 0, 0, 0]
        prev = self.log[i0][1] if i0 < len(self.log) else 0
        for _c, ig, _e, _p in self.log[i0 + 1:]:
            for b in range(4):
                if prev & (1 << b) and not ig & (1 << b):
                    out[b] += 1
            prev = ig
        return out


def main() -> int:
    import me711_image as PI
    print("=== overdwell watch on a running engine - %s ===" % PI.STEM)
    r = Rig(1500)
    r.start(6)
    i0 = len(r.log)
    for _ in range(6):
        r.rev()
    s = r.sparks_since(i0)
    check("O1 steady 1500 rpm wasted COP: every coil sparks every rev",
          r.u16("trg_state") >= 3 and all(n >= 5 for n in s),
          "sparks per coil in 6 revs %s" % s)
    check("O1 ... no overdwell", r.u("dry_sched_overdwell") == 0,
          "overdwell %d" % r.u("dry_sched_overdwell"))

    # O2a: the tip-in - the alpha-N table drops the advance 25 deg at once,
    # mid-dwell (physical 216: cylinder 3's coil, TDC 258, is charging).
    # MEASURED: this scheduler queues the spark BY TIME from the dwell, so
    # a retard does not stretch a dwell that has begun (rusEFI does the
    # same) - the step is NOT the overdwell's cause.
    for _ in range(35):
        r.tooth()
    r.adv = 50
    for _ in range(22):
        r.tooth()
    r.service_to(3 * r.p)
    r.c = (r.c + 18) % 720
    r.edge()
    check("O2a a 25 deg retard step mid-dwell keeps the dwell (no overdwell)",
          r.u("dry_sched_overdwell") == 0 and r.u("hc_ign_ovd_latch") == 0,
          "overdwell %d" % r.u("dry_sched_overdwell"))

    # O2b: ONE overdwell - a release that came late once (a long main-loop
    # pass, a missed event): coil 3's bit held ON for ~6 ms, once.
    for _ in range(10):
        r.tooth()
    r.force = 0x04
    t_end = r.clock + int(6.0 * 1250)
    while r.clock < t_end:
        r.tooth()
    r.force = 0
    r.to_gap()                    # realign rev() (no sync loss / cancel)
    ovd = r.u("dry_sched_overdwell")
    check("O2b one late release: the watch fires once (auto-fire)",
          ovd >= 1, "overdwell releases %d" % ovd)
    i1 = len(r.log)
    for _ in range(8):
        r.rev()
    s = r.sparks_since(i1)
    latch = r.u("hc_ign_ovd_latch")
    check("O2b ... and EVERY coil keeps sparking afterwards (no latch)",
          latch == 0 and all(n >= 7 for n in s)
          and r.u("trg_synclost") == 0,
          "latch 0x%02X, sparks per coil in 8 revs %s (V98r2: the coil is "
          "dead until the engine stalls)" % (latch, s))

    # O3: the V89 class - a coil commanded ON with no spark event after it
    r.force = 0x08                 # coil 4's bit (cylinder 4, slot 4)
    for _ in range(3):
        r.rev()
    r.force = 0
    latch = r.u("hc_ign_ovd_latch")
    check("O3 a coil re-charged with no spark between: latched after 3",
          latch & 0x08 and r.u("dry_sched_overdwell") >= ovd + 3,
          "latch 0x%02X overdwell %d" % (latch, r.u("dry_sched_overdwell")))
    i2 = len(r.log)
    for _ in range(3):
        r.rev()
    s = r.sparks_since(i2)
    check("O3 ... the latched coil stays OFF, the others keep sparking",
          s[3] == 0 and all(n >= 2 for n in s[:3]), "sparks %s" % s)

    print("\n%d checks, %d failed" % (CHECKS, FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
