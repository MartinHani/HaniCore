#!/usr/bin/env python3
r"""Linked C167 ETB commissioning with spring, hard endpoints, bridge disable,
reversed motor, track faults, amplifier clipping and asynchronous ADC samples.
A bounded capture is a software candidate; this gate cannot certify a real
mechanical stop or establish available motor torque on the fitted body.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

CONTROL_STEM = "HaniCore_ME711_v92_awt_runtime"
if "--control-v98" in sys.argv:
    env = dict(os.environ, HANICORE_ME711_STEM="HaniCore_ME711_v98_dev",
               HC_ETB_PROOF_V98="1")
    r = subprocess.run([sys.executable, __file__], env=env)
    ok = r.returncode != 0
    print("\nCONTROL (V98r2): %s" % ("FAILS as it must" if ok
                                     else "PASSED - the gate cannot tell"))
    raise SystemExit(0 if ok else 1)
if "--control" in sys.argv:
    env = dict(os.environ, HANICORE_ME711_STEM=CONTROL_STEM,
               HC_ETB_PROOF_CONTROL="1")
    r = subprocess.run([sys.executable, __file__], env=env)
    ok = r.returncode != 0
    print("\nCONTROL (%s): %s" % (CONTROL_STEM,
          "FAILS as it must" if ok else "PASSED - the gate cannot tell"))
    raise SystemExit(0 if ok else 1)

import me711_config_state_test as T      # noqa: E402
import me711_preset_apply_proof as AP    # noqa: E402
import me711_bridge_model as MOTOR      # noqa: E402

LEGACY = os.environ.get("HC_ETB_PROOF_CONTROL") == "1"
V98 = os.environ.get("HC_ETB_PROOF_V98") == "1"      # no '!C4'/'!C5' there
P3 = 0xFFC4
CHECKS = FAILS = 0
BIAS_AX = [0, 1, 5, 7, 14, 65, 66, 100]
BIAS_V = [-15, -15, -10, 0, 19, 20, 26, 28]
LIMP = 0.07


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += 0 if ok else 1
    print("  [%s] %-60s %s" % ("PASS" if ok else "FAIL", name, detail))


def bias(p):
    x = p * 100.0
    if x <= BIAS_AX[0]:
        return BIAS_V[0]
    for i in range(1, len(BIAS_AX)):
        if x <= BIAS_AX[i]:
            a0, a1, v0, v1 = BIAS_AX[i - 1], BIAS_AX[i], BIAS_V[i - 1], BIAS_V[i]
            return v0 + (v1 - v0) * (x - a0) / (a1 - a0)
    return BIAS_V[-1]


# 2026-10-11: two relay measurements (they must agree) + the verify
AT_MAX_MS = 45000


def rule(a_x10, tu, amp=200):
    """rusEFI's relay rule of the published a/Tu with the firmware's ONE fixed
    derating: KP and KD at half (= the rule of 2a), KI at the rule."""
    if not (a_x10 and tu):
        return []
    a2 = min(0xFFFF, 2 * a_x10)
    return [min(65535, (178254 * amp // 200) // a2),
            min(65535, (127323954 // 200 * amp) // (a_x10 * tu)),
            min(65535, ((8149 * amp // 200) * tu) // a2)]


def status(r):
    if LEGACY:
        s = r("hc_dbw_cal_status")
        return s & 0xFF, (s >> 8) & 0xF, (s >> 12) & 0xF
    s = r("hc_etbcal_status")
    return s & 0xF, (s >> 4) & 0xF, (s >> 8) & 0xFF


class Bench:
    def __init__(self, reversed_motor=False, stuck=False, strength=1.0,
                 tps2_dead=False, comp=0.0, noise=0, seed=1):
        r = self.r = T.boot()
        AP.press_apply(r, 3)
        AP.service(r)
        r("hc_hal_init", steps=5_000_000)
        r("hc_route_service", steps=5_000_000)
        r("hc_dbw_init", steps=2_000_000)
        r.m.w8(T.sym("hc_dbw_allowed") & 0xFFFF, 1)
        r.m.sfr[0xFFCC] = r.m.sfr.get(0xFFCC, 0) | 4
        r.m.sfr[P3] = r.m.sfr.get(P3, 0) | 0x8000 if isinstance(r.m.sfr, dict) \
            else (r.m.sfr[P3] | 0x8000)
        self.adc = T.sym("adc_raw") & 0xFFFF
        self.ipv_force = None
        self.stale_ch = None
        self.key_live = True
        self.batt_dv = 135
        self.skew = []
        self.tps2_delay = 3
        self.amp_clipped = False
        self.pos, self.vel = LIMP, 0.0
        self.spring_bias = bias
        self.tracks = (102, 954, 919, 71)
        self.rev, self.stuck, self.k = reversed_motor, stuck, strength
        self.tps2_dead = tps2_dead
        # V99: the CAR plant - wind-up at a stop (travel per % of duty
        # pushed into it beyond the spring) and PWM noise on each sample
        import random
        self.comp, self.noise = comp, noise
        self.rng = random.Random(seed)
        MOTOR.attach(r.m)
        self.shown = self.pos
        self.ms = 1000
        self.log = []                   # (ms, pos, on, duty)
        self.seen = {}                  # OCH offset -> set of values

    def sf(self, asserted):
        v = self.r.m.sfr[P3]
        self.r.m.sfr[P3] = (v & ~0x8000) if asserted else (v | 0x8000)

    def adc_set(self, ch, v, age=0):
        if ch == self.stale_ch: return
        v = min(1023, max(0, v))
        self.r.m.w16(self.adc + 2 * ch, v)
        if not LEGACY and not V98:
            self.r("hc_hal_main_sample", ch, (ch << 12) | v, 1, (self.ms-age)&65535)


    def tps(self, n1=0, n2=0):
        p = self.shown if self.comp else self.pos
        self.skew.append(p)
        if len(self.skew) > 16: self.skew.pop(0)
        p2 = self.skew[max(0,len(self.skew)-1-self.tps2_delay)]
        pa = self.skew[max(0,len(self.skew)-8)]
        c1, o1, c2, o2 = self.tracks
        self.adc_set(1, int(round(c1 + (o1-c1) * p)) + n1)
        self.adc_set(3, 500 if self.tps2_dead
                     else int(round(c2 + (o2-c2) * p2)) + n2, self.tps2_delay)
        tps1 = int(round(c1 + (o1-c1) * pa)) + n1
        ipv = min(1023, int(round(4.16 * tps1)))
        self.amp_clipped |= ipv == 1023
        self.adc_set(2, ipv if self.ipv_force is None else self.ipv_force, 7)

    def cmd(self, arg):
        self.r.m.w8(T.sym("hc_dbw_allowed") & 0xFFFF, int(self.key_live))
        self.r.m.w8(AP.REQ, ord("!"))
        self.r.m.w8(AP.REQ + 1, ord("C"))
        self.r.m.w8(AP.REQ + 2, arg)
        self.r("hcts_target_cmd", AP.REQ, 3)

    def plant(self):
        r = self.r
        fs = r("cfg_u16", 62)
        self.adc_set(5, (self.batt_dv * 1023 + fs - 1) // fs)
        signed, di, in1, in2 = MOTOR.state(r.m)
        on = int(di == 'L')
        duty = int(round(abs(signed) * 1000))
        eff = self.k * signed * 100.0 * self.batt_dv / 135.0 * (-1 if self.rev else 1)
        net = eff - self.spring_bias(self.pos)
        if abs(net) <= 3.0:
            vt = 0.0
        else:
            vt = (net - (3.0 if net > 0 else -3.0)) * 0.00014
        if self.stuck:
            vt = 0.0
        self.vel += (vt - self.vel) / 20.0
        self.pos = min(1.0, max(0.0, self.pos + self.vel))
        if self.pos in (0.0, 1.0):
            self.vel = 0.0
        self.shown = self.pos
        if self.comp and on and duty:
            if self.pos >= 1.0 and eff > bias(1.0):
                self.shown = 1.0 + self.comp * (eff - bias(1.0))
            elif self.pos <= 0.0 and eff < bias(0.0):
                self.shown = -self.comp * (bias(0.0) - eff)
        n = self.noise if (on and duty) else 0
        self.tps(self.rng.randint(-n, n), self.rng.randint(-n, n))
        self.log.append((self.ms, self.pos, on, duty))

    def step(self, rpm=0):
        if not LEGACY and not V98:
            self.r.m.w16(T.sym("hc_tick_ms") & 0xFFFF, self.ms)
            self.r("hc_fresh_service")
        self.r.m.w8(T.sym("hc_dbw_allowed") & 0xFFFF, int(self.key_live))
        self.plant()
        self.r("hc_dbw_service", self.ms, rpm, 1, steps=2_000_000)
        # V97: THE MAIN LOOP'S HAND-OFF, as on the ECU: a PASS reaches
        # DESIRED (hc_preset_cmd_service -> hc_etbcal_take/tune_take) and the
        # config manager makes it ACTIVE with the engine stopped. The
        # commission's VERIFY uses private candidates until its final PASS; a
        # failed run must leave the complete DESIRED page unchanged.
        if not LEGACY and self.ms % 10 == 0:
            self.r("hc_preset_cmd_service", steps=60_000_000)
            self.r("hc_cfg_mgr_service", rpm, steps=60_000_000)
        self.ms = (self.ms + 1) & 0xFFFF

    def run(self, arg=1, max_ms=16000, hook=None, watch=()):
        self.tps()
        self.cmd(arg)
        for i in range(max_ms):
            if hook:
                hook(self, i)
            self.step()
            if i % 25 == 0:
                for o in watch:     # ETBV_* index, the firmware's accessor
                    self.seen.setdefault(o, set()).add(
                        self.r("hc_etbcal_value", o))
            res, _ph, _why = status(self.r)
            if res in (2, 3, 4, 5) and i > 5:
                break
        for _ in range(5):
            self.step()
        return status(self.r)

    def released(self):
        r = self.r
        physical, di, _, _ = MOTOR.state(r.m)
        return (physical == 0 and di != 'L'
                and r.callb("hc_dbw_bridge_on") == 0 and r("hc_dbw_duty_x10") == 0)

    def u16d(self, o):
        return (self.r.desired(o) << 8) | self.r.desired(o + 1)

    def och_publish(self):
        # the OCH writer, so the published telemetry is the firmware's own
        self.r("hc_preset_cmd_service", steps=60_000_000)


def main() -> int:
    import me711_image as PI
    print("=== ETB endpoint calibration + PID autotune - %s%s ==="
          % (PI.STEM, " (LEGACY V92 CONTROL)" if LEGACY else ""))

    # ---------------------------------------------------------- healthy
    b = Bench()
    res, ph, why = b.run()
    check("healthy bridge, normal motor: PASS", res == 2,
          "result %d why %d" % (res, why))
    check("bridge released at the end", b.released())
    dur = len(b.log)
    check("finished within 5 s", dur <= 5100, "%d ms" % dur)
    b.och_publish()
    got = [b.u16d(o) for o in (1220, 1222, 1224, 1226)]
    want = [102, 954, 919, 71]
    check("endpoints in DESIRED within 4 counts (tps1 c/o, tps2 c/o)",
          all(abs(g - w) <= 4 for g, w in zip(got, want)),
          "got %s want %s" % (got, want))
    check("motor direction Normal, tpsCorrelation SAME",
          b.r.desired(2679) == 0 and b.r.desired(2620) == 1,
          "dir %d corr %d" % (b.r.desired(2679), b.r.desired(2620)))
    check("dbwEnable NOT turned on", b.r.desired(1240) == 0
          and b.r.active(1240) == 0)
    check("TunerStudio told to re-read the page", AP.och(b.r, 770) == 1)

    b = Bench(reversed_motor=True)
    res, ph, why = b.run()
    b.och_publish()
    check("healthy bridge, reversed motor: PASS with direction Reversed",
          res == 2 and b.r.desired(2679) == 1,
          "result %d dir %d" % (res, b.r.desired(2679)))

    b = Bench()
    b.adc_set(8, 0)
    b.adc_set(9, 1023)
    res, ph, why = b.run()
    check("garbage pedal inputs: still PASS (no APP needed)", res == 2,
          "result %d why %d" % (res, why))

    # Bounded acquisition does not infer a hard stop from stationary ADC.
    # A torque-limited equilibrium may pass a span check: explicitly retain
    # physical qualification as a separate prerequisite, as rusEFI does.
    b = Bench(strength=0.6)
    res, ph, why = b.run()
    check("reduced torque: bounded capture/release, no physical stop claim",
          res in (2, 3) and b.released() and len(b.log) < 5100,
          "result %d why %d" % (res, why))
    b = Bench(strength=0.35)
    res, ph, why = b.run()
    check("weak bridge: endpoint span capture, no inferred torque verdict",
          res in (2, 3) and b.released(),
          "result %d why %d" % (res, why))

    b = Bench(stuck=True)
    res, ph, why = b.run()
    check("stuck plate: FAIL 'never moved', released",
          res == 3 and why == 5 and b.released(),
          "result %d why %d" % (res, why))

    b = Bench()
    res, ph, why = b.run(hook=lambda bb, i: bb.sf(i >= 120))
    check("SF asserted mid-run: FAIL 'H-bridge fault', released",
          res == 3 and why == 3 and b.released(),
          "result %d why %d" % (res, why))

    b = Bench()
    b.tps()
    b.cmd(1)
    for i in range(150):
        b.step()
    for _ in range(3):
        b.step(rpm=200)
    res, ph, why = status(b.r)
    check("engine turning mid-run: FAIL 'engine is turning', released",
          res == 3 and why == 1 and b.released(),
          "result %d why %d" % (res, why))

    b = Bench()
    res, ph, why = b.run(hook=lambda bb, i: bb.cmd(0) if i == 300 else None)
    check("'!C\\x00' mid-run: FAIL 'aborted', released",
          res == 3 and why == 10 and b.released(),
          "result %d why %d" % (res, why))

    if not LEGACY:
        b = Bench(tps2_dead=True)
        res, ph, why = b.run()
        check("TPS2 not following: FAIL (span or tracks), released",
              res == 3 and why in (7, 17) and b.released(),
              "result %d why %d" % (res, why))

        # ---------------------------------------------------- autotune
        b = Bench()
        res, ph, why = b.run(arg=2, max_ms=AT_MAX_MS, watch=(9, 10))  # cycles, Kp
        b.och_publish()
        # the page offsets of dbwKp/Ki/Kd, from the generated header
        offs = [T.d(T._cfg, n) for n in ("CAL_DBW_KP", "CAL_DBW_KI",
                                         "CAL_DBW_KD")]
        gains = [b.u16d(o) for o in offs]
        a_x10, tu = b.r("hc_etbcal_value", 6), b.r("hc_etbcal_value", 7)
        exp = rule(a_x10, tu)
        check("autotune, healthy: PID PASS", res == 4,
              "result %d why %d a %d.%d%% Tu %d ms"
              % (res, why, a_x10 // 10, a_x10 % 10, tu))
        check("  gains in DESIRED = rusEFI's rule of the published a/Tu, "
              "KP/KD x 0.5", bool(exp) and gains == exp,
              "page %s expect %s" % (gains, exp))
        clipmask = sum(1 << i for i, e in enumerate(exp) if e == 65535)
        det = b.r("hc_etbcal_value", 8)
        check("  a gain limited by its page field is SAID (detail 0x8000|mask)",
              det == ((0x8000 | clipmask) if clipmask else 0),
              "detail 0x%04X clipped mask %d" % (det, clipmask))
        check("  dbwEnable NOT turned on, page refresh raised",
              b.r.desired(1240) == 0 and AP.och(b.r, 770) == 1)
        check("  bridge released at the end", b.released())
        check("  live telemetry moved while it ran (cycles, candidate Kp)",
              len(b.seen.get(9, ())) > 5 and len(b.seen.get(10, ())) > 2,
              "cycles %d values, Kp %d values"
              % (len(b.seen.get(9, ())), len(b.seen.get(10, ()))))

        # THE OWNER'S COMPLAINT (2026-10-11): "P 1.x one time, 3.x the
        # next". The same body must give the same gains: two runs with
        # different sensor noise agree within 10 %. (Before: a verify retry
        # halved KP/KD up to three times - /1, /2, /4 or /8 per run.)
        runs = []
        for seed in (11, 12):
            b2 = Bench(noise=2, seed=seed)
            res2, _ph, why2 = b2.run(arg=2, max_ms=AT_MAX_MS)
            runs.append((res2, why2, [b2.u16d(o) for o in offs]))
        g1, g2 = runs[0][2], runs[1][2]
        agree = all(runs[i][0] == 4 for i in (0, 1)) and all(
            abs(x - y) * 10 <= max(x, y) for x, y in zip(g1, g2))
        check("autotune repeatable: two noisy runs PASS, gains within 10 %",
              agree, "runs %s" % [(r_[0], r_[1], r_[2]) for r_ in runs])

        # A plant that changes between the two measurements (here: the
        # motor loses half its torque) is NOT a repeatable result: FAIL
        # 'not repeatable' (31), nothing written, released.
        b = Bench(noise=2, seed=13)
        before = [b.u16d(o) for o in offs]
        st = {"last": 0, "hit": False}

        def weaken(bb, i):
            if i % 25 or st["hit"]:
                return
            c = bb.r("hc_etbcal_value", 9)
            if c < st["last"]:             # cycles restarted: 2nd measurement
                bb.k = 0.65    # still oscillates, differently
                st["hit"] = True
            st["last"] = c
        res, ph, why = b.run(arg=2, max_ms=AT_MAX_MS, hook=weaken)
        check("autotune, plant changes between the two measurements: FAIL "
              "'not repeatable', nothing written",
              st["hit"] and res == 3 and why == 31 and b.released()
              and [b.u16d(o) for o in offs] == before,
              "switched %s result %d why %d" % (st["hit"], res, why))

        b = Bench(strength=0.35)
        res, ph, why = b.run(arg=2)
        check("autotune, 35 % bridge: FAIL 'never reached 50 %', released",
              res == 3 and why == 18 and b.released(),
              "result %d why %d detail %d" % (res, why,
                                              b.r("hc_etbcal_value", 8)))

        b = Bench()
        # ACTIVE directly: validation would (rightly) refuse this page
        b.r("hc_cal_set_u16", T.d(T._cfg, "CAL_TPS1_MIN"), 500)
        b.r("hc_cal_set_u16", T.d(T._cfg, "CAL_TPS1_MAX"), 500)
        res, ph, why = b.run(arg=2)
        # V93: the stored-endpoint check (NO ENDPOINTS, 20) runs first
        check("autotune, TPS 1 uncalibrated: FAIL 'no endpoints'",
              res == 3 and why == 20 and b.released(),
              "result %d why %d" % (res, why))

    if not LEGACY:
        # ------------------------------------------------ V93 commission
        offs = [T.d(T._cfg, n) for n in ("CAL_DBW_KP", "CAL_DBW_KI",
                                         "CAL_DBW_KD")]

        def proc(b):
            return b.r("hc_etbcal_proc")

        b = Bench()
        b.r("hc_cal_set_u16", T.d(T._cfg, "CAL_TPS2_MIN"), 600)  # stale cal
        b.r("hc_cal_set_u16", T.d(T._cfg, "CAL_TPS2_MAX"), 400)
        res, ph, why = b.run(arg=3)
        b.och_publish()
        pr = proc(b)
        got = [b.u16d(o) for o in (1220, 1222, 1224, 1226)]
        gains = [b.u16d(o) for o in offs]
        check("commission (!C3), healthy: COMMISSION PASS in one run",
              res == 5 and (pr & 15) == 3 and (pr >> 8) & 1 == 1,
              "result %d why %d proc 0x%04X" % (res, why, pr))
        check("  endpoints AND gains reached DESIRED (stale TPS2 cal overwritten)",
              all(abs(g - w) <= 4 for g, w in zip(got, [102, 954, 919, 71]))
              and gains != [5120, 47000, 17600],
              "tps %s gains %s" % (got, gains))
        check("  bridge released, DBW not enabled",
              b.released() and b.r.desired(1240) == 0)
        if not LEGACY:
            vs = [b.r("hc_etbcal_value", i) for i in (17, 18, 19, 20)]
            check("  V97 VERIFY: all five steps, settle <= 350 ms, "
                  "overshoot <= 5 %, offset <= 1.5 %",
                  vs[3] == 0x0105 and vs[0] <= 350 and vs[1] <= 50
                  and vs[2] <= 15,
                  "settle %d ms over %d err %d step 0x%X" % tuple(vs))

            # NEGATIVE: the verify must SEE a controller that cannot hold.
            # Gains are zeroed in ACTIVE once the VERIFY phase has started
            # (after the hand-off), so only the feed-forward is left.
            def sabotage(bb, _i):
                if (bb.r("hc_etbcal_status") >> 4) & 15 == 10:
                    bb.stuck = True
            b = Bench()
            res, ph, why = b.run(arg=3, hook=sabotage)
            check("  VERIFY with a jammed plate: FAIL in VERIFY, released",
                  res == 3 and why in (21, 22, 23, 24) and b.released(),
                  "result %d why %d" % (res, why))

        # 2026-10-12: the failure comes as LATE as possible - the plate jams
        # in VERIFY, after the endpoints and the gains exist in RAM - so a
        # partial publication would show. (The old trigger, a 5 % relay
        # amplitude, commissions legitimately since the relay noise band.)
        def jam_in_verify(bb, _i):
            if (bb.r("hc_etbcal_status") >> 4) & 15 == 10:
                bb.stuck = True
        b = Bench()
        before = bytes(b.r.desired(i) for i in range(T.PAGE))
        res, ph, why = b.run(arg=3, max_ms=AT_MAX_MS, hook=jam_in_verify)
        b.och_publish()
        check("failed combined commissioning publishes no endpoints or gains",
              res == 3 and b.released()
              and before == bytes(b.r.desired(i) for i in range(T.PAGE)),
              "result %d why %d" % (res, why))

        b = Bench(strength=0.35)
        # Endpoint capture now succeeds; include its time PLUS the relay's
        # 15 s timeout rather than stopping the harness at 16 s total.
        res, ph, why = b.run(arg=3, max_ms=23000)
        pr = proc(b)
        cyc = b.r("hc_etbcal_value", 9)
        check("commission, weak bridge: unusable commissioning rejected/released",
              res == 3 and b.released(),
              "result %d why %d proc 0x%04X cycles %d" % (res, why, pr, cyc))

        b = Bench()
        b.r("hc_cal_set_u16", T.d(T._cfg, "CAL_TPS2_MIN"), 500)
        b.r("hc_cal_set_u16", T.d(T._cfg, "CAL_TPS2_MAX"), 520)
        res, ph, why = b.run(arg=2)
        check("autotune only without valid stored endpoints: NO ENDPOINTS",
              res == 3 and why == 20 and b.released(),
              "result %d why %d" % (res, why))

    if not LEGACY:
        v99_cases()
    print("\n%d checks, %d failed" % (CHECKS, FAILS))
    return 1 if FAILS else 0


def v99_cases():
    """The first car session (V98r2, 2026-10-02) and its fix."""
    print("\n--- V99: the car plant (wind-up + PWM noise), the direction tests")
    car = dict(comp=0.001, noise=3)
    b = Bench(**car)
    res, ph, why = b.run()
    b.och_publish()
    tel = [b.r("hc_etbcal_value", i) for i in range(21, 27)] if not V98 else []
    got = [b.u16d(o) for o in (1220, 1222, 1224, 1226)]
    check("CAR plant (geared stop winds up, PWM noise): AutoCal PASS",
          res == 2, "result %d why %d detail %d (V98r2 on the car: FAIL why 14"
          " 'NOT A STOP A')" % (res, why, b.r("hc_etbcal_value", 8)))
    check("  endpoints within the stops' wind-up (35 counts)",
          res == 2 and all(abs(g - w) <= 35
                           for g, w in zip(got, [102, 954, 919, 71])),
          "page %s" % got)
    if not V98:
        # V101 repurposed slots 22..24 (hcetbcal.h): TPS1 / TPS2 sample AGE
        # in ms at the last step and the freshness reason nibbles. There is
        # no push verdict any more; a healthy capture has fresh samples
        # (well inside the 100 ms deadline - the plant's TPS2 lags 3 ms) and
        # no freshness reason.
        h1, age1, age2, moved, hold_ms, disp = tel
        check("capture telemetry: fixed hold, fresh samples, no fault reason",
              h1 > 0 and hold_ms >= 1000 and age1 <= 20 and age2 <= 20
              and moved == 0, "telemetry %s" % (tel,))
    for arg, label, want, k in ((4, "direction A ('!C4')", 954, 1),
                                (5, "direction B ('!C5')", 102, 2)):
        b = Bench(**car)
        res, ph, why = b.run(arg=arg)
        pos = b.r("hc_etbcal_value", k)
        check("%s: bounded position captured, released" % label,
              res == 6 and abs(pos - want) <= 40 and b.released(),
              "result %d why %d tps1 %d (stop %d)" % (res, why, pos, want))
    b = Bench(**car)
    res, ph, why = b.run()
    check("4.16x TPS1 amplifier clips normally: endpoint capture proceeds",
          res == 2 and b.amp_clipped and b.released())
    # It is a same-track amplifier, not a third safety sensor. Its absence
    # must not replace healthy independent AN1/AN3 acquisition.
    b = Bench(); b.ipv_force = 0
    res, ph, why = b.run()
    check("AN2 unavailable with healthy AN1/AN3: no fake reference veto", res == 2)
    for ch in (1, 3):
        b = Bench()
        before = bytes(b.r.desired(i) for i in range(T.PAGE))
        def stale(bb, i):
            if i == 150: bb.stale_ch = ch
        res, ph, why = b.run(hook=stale)
        check("stale independent TPS channel %d: abort/release/no publication" % ch,
              res == 3 and why == 26 and b.released()
              and before == bytes(b.r.desired(i) for i in range(T.PAGE)),
              "result %d why %d (26 = ETB_WHY_STALE, the dedicated reason)" % (res, why))
    b = Bench()
    res, ph, why = b.run(hook=lambda bb, i: setattr(bb, "key_live", False) if i == 150 else None)
    check("key off: abort and release", res == 3 and why == 2 and b.released())
    b.key_live = True
    for _ in range(400): b.step()  # let the released plate reach its spring rest
    res, ph, why = b.run()
    check("procedure restarts after key-off failure", res == 2 and b.released())

    b = Bench(reversed_motor=True)
    res, ph, why = b.run(arg=4)
    pos = b.r("hc_etbcal_value", 1)
    check("direction A on a reversed motor: the CLOSED stop (it says where)",
          res == 6 and abs(pos - 102) <= 10, "result %d tps1 %d" % (res, pos))
    b = Bench(stuck=True)
    res, ph, why = b.run(arg=4)
    check("direction A, jammed plate: bounded capture only, released",
          res == 6 and why == 0
          and b.released(), "result %d why %d" % (res, why))


if __name__ == "__main__":
    raise SystemExit(main())
