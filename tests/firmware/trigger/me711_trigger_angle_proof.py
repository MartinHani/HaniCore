#!/usr/bin/env python3
"""The V97 physical trigger angle drives the SAME crank events as V96's offset.

V96 stored the crank reference as trigOffsetX10, the decoder's internal
rotation (0..719.9; the AWT ran on 358.0). V97 stores the same slot as
trigAngleX10: where tooth #1 - the edge that ENDS the missing-tooth gap - is,
in 0.1 deg AFTER cylinder-1 TDC, signed (Speeduino's trigger angle; rusEFI's
globalTriggerAngleOffset is minus it). The one conversion is
hc_trig_rotation_x10() in hctrig_me711.c: angle mod 360. So 358.0 there is
-2.0 here, and the car must spark and inject at the same crank positions.
the maintainer's design notes.

On the LINKED image, in c167sim:

  A  hc_trig_rotation_x10 equals Python's (angle mod 3600) over the whole s16
     range at every tooth-sized step and at the edges (-32768, -3600, -1, 0,
     1799..1801, 3599, 3600, 32767);
  B  the published angle in force (OCH 706, trg_cfg_angle_x10) is the signed
     normalisation -179.9..180.0 of whatever was stored;
  C  EQUIVALENCE: an AWT-shaped 4-cylinder 60-2 (wasted spark, batch) run
     tooth by tooth with the stored value 3580 (V96 page, migrated verbatim by
     an old tool) and with -20 (the V97 preset) gives the IDENTICAL sequence of
     coil and injector transitions, clock for clock; the same for 2680 / -920
     (the V89 value that did not start), and for 36-1 and 60-2 with 900 / -2700;
  D  the sparks land where the car's record says 358.0 put them: TDC at
     physical 2.0 (tooth #1 is 2.0 deg before TDC), so advance 10 fires at
     physical 352 (mod 180, wasted COP) - and with -92.0 at physical 82;
  E  the cam frame: a cam edge seen at physical 114.0 (the AWT's equidistant
     CPU-falling edge) is engine 112.0 with -2.0, engine 22.0 with -92.0 -
     trg_engine_angle_x10 is the only path, the cam decoder and future knock
     windows read engine angles;
  F  continuity: over two synced revolutions the published engine angle only
     ever steps by one tooth (or the gap's own step) - no 90/180/360 jump at
     the 0/360 wrap or the 360/720 half - for -2.0, -92.0 and +90.0;
  G  sensitivity: 1.0 deg of difference in the stored angle DOES change the
     executed events (C cannot pass on a rig that ignores the field);
  H  the tuner's representation: the generated .ini declares the field S16
     at 2540, scale 0.1, -359.9..359.9; the AWT preset's bytes in
     hc_presets.c are the s16 two's complement of its value;
  I  hc_validate() on the AWT page accepts -359.9 / +359.9 / -2.0 and
     REFUSES +360.0, -360.0 and V96's 719.9, naming trigAngleX10;
  J  PER PIN, mod 360 (D is mod 180 and cannot see a pair swap): with the
     class permissions granted, the P2 PINS themselves (DP2 driven + latch
     LOW = dwell, release = spark) put cavity 102/94 (P2.0/P2.2, cylinders
     1/4) at physical (-angle - advance) mod 360 and 103/95 (P2.1/P2.3,
     cylinders 3/2) 180 deg later, for -78.0 and -2.0; and a MUTATION that
     swaps ignPin 102 <-> 103 moves P2.0 by 180 (the check sees wiring).

--control runs V96 (`HaniCore_ME711_v96_wideband`, frozen): it has no
hc_trig_rotation_x10, and stored -20 (0xFFEC) is 65516 % 3600 = 71.6 deg
there, so C must fail.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

CONTROL_STEM = "HaniCore_ME711_v96_wideband"
CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += 0 if ok else 1
    print("  [%s] %-60s %s" % ("PASS" if ok else "FAIL", name, detail))
    return ok


def s16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def py_rotation(angle_x10):
    return angle_x10 % 3600


def py_signed(angle_x10):
    r = angle_x10 % 3600
    return r - 3600 if r > 1800 else r


def events(k):
    """Every coil/injector transition, (clock, ign mask, inj mask)."""
    out, prev = [], None
    for c, ig, ij in k.log:
        if (ig, ij) != prev:
            out.append((c, ig, ij))
            prev = (ig, ij)
    return out


def pin_sparks(stored, ignpin=None, rpm=900, revs=5):
    """Per P2 pin 0..3: physical angles where the pin is RELEASED after being
    driven LOW (a spark), on the linked image with permissions granted."""
    import me711_gap_scheduler_proof as G

    class PinCrank(G.Crank):
        def service(self):
            for n in ("hc_ignition_allowed", "hc_injection_allowed"):
                self.x.m.w16(self.sym(n) & 0xFFFF, 1)
            self.x.m.w16(self.sym("hc_cfg_validation") & 0xFFFF, 0)
            super().service()

        def sample(self):
            m = self.x.m
            self.log.append((self.clock, m.r16(0xFFC0), m.r16(0xFFC2)))  # P2, DP2

    k = PinCrank(G.rig(), stored & 0xFFFF)
    if ignpin:
        for i, v in enumerate(ignpin):
            k.x.m.w8(0x380000 + 12 + 2563 + i, v)
    rev = k.sym("hc_cfg_active_rev") & 0xFFFF       # re-resolve the routes
    k.x.m.w16(rev, (k.x.m.r16(rev) + 1) & 0xFFFF)
    k.x.call("hc_hal_outputs_live")
    p = round(1_250_000 / rpm)
    for _ in range(revs):
        k.rev(p)
    out = {b: [] for b in range(4)}
    prev = None
    for c, p2, dp2 in k.log:
        on = {b: bool(dp2 >> b & 1) and not (p2 >> b & 1) for b in range(4)}
        if prev is not None:
            for b in range(4):
                if prev[b] and not on[b]:
                    a = G.phys_deg(c, k.gap_ends, p)
                    if a is not None:
                        out[b].append(a)
        prev = on
    return out


def spark_phys(k, p):
    import me711_gap_scheduler_proof as G
    out, prev = [], 0
    for c, ig, _ij in k.log:
        if prev & ~ig & 0xF:
            a = G.phys_deg(c, k.gap_ends, p)
            if a is not None:
                out.append(a)
        prev = ig
    return out


def ang_err(a, want, period):
    d = (a - want) % period
    return min(d, period - d)


class Wheel:
    """A generic N-M wheel on the same rig (36-1, 60-2 ...), 4 cylinders."""

    def __init__(self, PT, teeth, gap, stored):
        import me711_gap_scheduler_proof as G
        self.G = G
        k = G.Crank.__new__(G.Crank)
        k.PT, k.sym = PT, PT.sym
        x = k.x = PT.Call()
        PT.describe_engine(x, cylinders=4, teeth=teeth, gap=gap, soi_x10=3600,
                           tdc=[0, 5400, 1800, 3600], cam_refs=0)
        base = k.sym("hc_cfg") & 0xFFFF
        for i, v in enumerate([0, 3, 1, 2, 255, 255, 255, 255]):
            x.m.w8(base + 34 + i, v)
            x.m.w8(base + 42 + i, v)
        u = 0x380000 + 12
        uni = {2536: 0, 2537: 1, 2538: 1, 2539: 1, 2548: 82,
               2540: (stored >> 8) & 0xFF, 2541: stored & 0xFF}
        for i, v in enumerate([96, 89, 97, 88] + [255] * 8):
            uni[2551 + i] = v
        for i, v in enumerate([102, 95, 103, 94] + [255] * 8):
            uni[2563 + i] = v
        for o, v in uni.items():
            x.m.w8(u + o, v)
        x.call("trg_init")
        x.enable_deadlines()               # as G.Crank: the CC25 executor runs
        try:
            k.sym("hc_drysched_overdwell_service")
            k.ovd = True
        except SystemExit:
            k.ovd = False
        k.clock, k.t, k.gap_ends, k.log = 0, 1000, [], []
        k.edge(service=False)
        self.k, self.teeth, self.gap = k, teeth, gap

    def run(self, rpm, revs=6):
        k = self.k
        p = round(1_250_000 * 60 / (rpm * self.teeth))   # T1 ticks per tooth
        for _ in range(revs):
            for _ in range(self.teeth - self.gap - 1):
                k.wait(p)
            k.wait((self.gap + 1) * p, gap_end=True)
        return k, p


def main_one(stem: str) -> int:
    os.environ["HANICORE_ME711_STEM"] = stem
    import me711_gap_scheduler_proof as G
    PT = G.rig()
    print("=== physical trigger angle - %s ===" % stem)
    f0 = FAILS

    # ---- A: the conversion, exactly, on the linked code ----
    x = PT.Call()
    try:
        PT.sym("hc_trig_rotation_x10")
        have = True
    except SystemExit:
        have = False
    if check("A  hc_trig_rotation_x10 is linked", have):
        vals = list(range(-32768, 32768, 37)) + [
            -32768, -3601, -3600, -3599, -1801, -1800, -1799, -20, -1, 0, 1,
            1799, 1800, 1801, 3580, 3599, 3600, 3601, 7199, 32767]
        bad = [(v, x.call("hc_trig_rotation_x10", v & 0xFFFF), py_rotation(v))
               for v in vals
               if x.call("hc_trig_rotation_x10", v & 0xFFFF) != py_rotation(v)]
        check("A  rotation == angle mod 360 over %d values" % len(vals),
              not bad, "first mismatch %s" % (bad[:3],) if bad else "exact")

    # ---- B: the value in force, published signed ----
    try:
        PT.sym("trg_cfg_angle_x10")
        pub = "trg_cfg_angle_x10"
    except SystemExit:
        pub = None
    if check("B  trg_cfg_angle_x10 (OCH 706) is linked", pub is not None):
        bad = []
        for stored in (3580, -20, 2680, -920, 0, 1800, 1801, -1800, 7199, -32768):
            k = G.Crank(PT, stored & 0xFFFF)
            got = s16(k.u16(pub))
            if got != py_signed(stored):
                bad.append((stored, got, py_signed(stored)))
        check("B  published = signed normalisation (-179.9..180.0)",
              not bad, str(bad) if bad else "3580 -> -20, 2680 -> -920, 1801 -> -1799")

    # ---- C/D: equivalence and position of the executed events ----
    # The "new" value is what the MIGRATION TOOL makes of the old one, so C
    # proves that migrating a V96 page preserves its timing, end to end.
    import me711_migrate_calibration as MIG
    pairs = [(old, MIG._trig_angle_from_offset(old)) for old in (3580, 2680)]
    check("C  migration: 3580 -> %d, 2680 -> %d (V96 page -> V97)" % (pairs[0][1], pairs[1][1]),
          pairs == [(3580, -20), (2680, -920)])
    for old, new in pairs:
        for rpm in (200, 900):
            ka, p = G.run_case(PT, rpm, old & 0xFFFF)
            kb, _ = G.run_case(PT, rpm, new & 0xFFFF)
            ea, eb = events(ka), events(kb)
            first = next((i for i, (a, b) in enumerate(zip(ea, eb)) if a != b), None)
            check("C  60-2 %4d rpm: stored %d == stored %d, clock for clock"
                  % (rpm, old, new),
                  ea == eb and len(ea) > 20,
                  "%d transitions identical" % len(ea) if ea == eb else
                  "differ at #%s: %s vs %s" % (first, ea[first:first + 1] if first is not None else len(ea),
                                               eb[first:first + 1] if first is not None else len(eb)))
            sp = spark_phys(kb, p)
            want = (-(py_rotation(new) / 10.0) - G.ADV_X10 / 10.0) % 180.0
            errs = [ang_err(a, want, 180.0) for a in sp]
            tol = 2.0 if rpm <= 300 else 3.0   # polled execution, <= 0.5 ms
            check("D  %4d rpm, trigAngle %.1f: sparks at physical %.1f (mod 180)"
                  % (rpm, new / 10.0, want),
                  bool(errs) and max(errs) <= tol,
                  "worst %.2f deg over %d sparks" % (max(errs), len(errs)) if errs else "no sparks")
    # the AWT record: 358.0 -> TDC#1 at physical 2.0, advance 10 -> 352
    check("D  the car's 358.0 == tooth #1 at 2.0 BTDC: spark(adv 10) at 352",
          (-(py_rotation(-20) / 10.0) - 10.0) % 360.0 == 352.0)

    for teeth, gap, old, new in ((36, 1, 900, -2700), (60, 2, 900, -2700),
                                 (36, 1, 3580, -20)):
        wa = Wheel(PT, teeth, gap, old & 0xFFFF)
        ka, p = wa.run(600)
        wb = Wheel(PT, teeth, gap, new & 0xFFFF)
        kb, _ = wb.run(600)
        ea, eb = events(ka), events(kb)
        check("C  %d-%d 600 rpm: stored %d == stored %d" % (teeth, gap, old, new),
              ea == eb and len(ea) > 20,
              "%d transitions identical" % len(ea) if ea == eb else
              "%d vs %d transitions" % (len(ea), len(eb)))

    # ---- F: continuity across 0/360 and 360/720 ----
    for stored in (-20, -920, 900):
        k = G.Crank(PT, stored & 0xFFFF)
        seen = []
        orig = k.edge

        def edge(service=True, k=k, orig=orig, seen=seen):
            orig(service)
            if k.x.m.r8(k.sym("trg_state") & 0xFFFF) >= 3:     # TRG_SYNC_CRANK
                seen.append(k.u16("trg_engine_deg_x10"))
        k.edge = edge
        for _ in range(7):
            k.rev(round(1_250_000 / 600))
        steps = [(b - a) % 7200 for a, b in zip(seen, seen[1:])]
        odd = sorted({d for d in steps if d not in (60, 180)})
        wraps = sum(1 for a, b in zip(seen, seen[1:]) if b < a)          # 720 -> 0
        halves = sum(1 for a, b in zip(seen, seen[1:]) if a < 3600 <= b)  # 360 -> 360+
        check("F  trigAngle %6.1f: engine angle steps only 6/18 deg" % (stored / 10.0),
              len(steps) > 150 and not odd and wraps >= 1 and halves >= 1,
              "%d steps, %d x 720->0, %d x 0->360 crossings, other steps %s"
              % (len(steps), wraps, halves, odd or "none"))

    # ---- G: the equality above is not vacuous ----
    # 200 rpm: 1 deg = 0.83 ms, above the rig's 0.5 ms service quantum
    ka, _p = G.run_case(PT, 200, (-20) & 0xFFFF)
    kb, _p = G.run_case(PT, 200, (-30) & 0xFFFF)
    check("G  -2.0 vs -3.0 give DIFFERENT events (the field is read)",
          events(ka) != events(kb), "%d vs %d transitions" % (len(events(ka)), len(events(kb))))

    # ---- H: what TunerStudio and the preset store ----
    import re as _re
    import me711_image as PI
    inis = sorted((ROOT / "tunerstudio").glob(
        "hanicore_%s*.ini" % PI.STEM[len("HaniCore_"):].lower()))
    rows = []
    for f in inis:
        m = _re.search(r"^\s*trigAngleX10\s*=\s*scalar,\s*(\w+),\s*(\d+),\s*\"([^\"]*)\",\s*([\d.]+),\s*([\d.-]+),\s*([\d.-]+),\s*([\d.-]+)",
                       f.read_text(errors="replace"), _re.M)
        rows.append((f.name, m.groups() if m else None))
    ok = rows and all(g and g[0] == "S16" and g[1] == "2540" and float(g[3]) == 0.1
                      and float(g[5]) == -359.9 and float(g[6]) == 359.9 for _n, g in rows)
    check("H  every generated .ini: trigAngleX10 S16 @2540 x0.1 +-359.9", ok,
          "; ".join("%s %s" % (n, "ok" if g else "MISSING") for n, g in rows))
    pre = (ROOT / "firmware/generated/hc_presets.c").read_text(errors="replace")
    import importlib
    sys.path.insert(0, str(ROOT / "tools/config_source"))
    P = importlib.import_module("hanicore_presets")
    want = [p.values["trigAngleX10"].value for p in P.ENGINE_PRESETS
            if "trigAngleX10" in p.values]
    lits = [int(v) for v in _re.findall(r"\{\s*2540u,\s*(\d+)u,\s*2u\s*\}", pre)]
    check("H  preset values are stored as s16 two's complement",
          bool(want) and sorted(v & 0xFFFF for v in want) == sorted(lits)
          and all(v < 0x10000 for v in lits),
          "values %s -> hc_presets.c %s" % (want, lits))

    # ---- E: the cam frame ----
    ok = True
    det = []
    for ang, phys, want in ((-20, 1140, 1120), (-920, 1140, 220), (-20, 0, 3580)):
        rot = py_rotation(ang)
        got = x.call("trg_engine_angle_x10", phys, 0, rot)
        det.append("%d@%.1f -> %d" % (phys, ang / 10.0, got))
        ok &= got == want
    check("E  cam physical 114.0 -> engine 112.0 (-2.0) / 22.0 (-92.0)", ok, "; ".join(det))

    # ---- I: the validator's range, on the AWT page ----
    import me711_config_state_test as T
    names = {}
    for f in ("generated/hc_config_generated.h", "config/hcconfig.h"):
        for m in _re.finditer(r"#define\s+(CFG_[A-Z0-9_]+)\s+(\d+)u?",
                              (ROOT / "firmware" / f).read_text(errors="replace")):
            names.setdefault(int(m.group(2)), m.group(1))
    res = []
    for v, want_ok in ((-20, True), (-3599, True), (3599, True), (0, True),
                       (3600, False), (-3600, False), (7199, False)):
        r = T.boot()
        r("hc_preset_apply_engine_active", 3)
        base = 0x380000 + 12 + 2540
        r.m.w8(base, (v >> 8) & 0xFF)
        r.m.w8(base + 1, v & 0xFF)
        rc = r("hc_validate", T.VAL["HC_VAL_SRC_ACTIVE"]) & 0xFFFF
        off = r.g16("hc_val_first_bad_offset")
        good = (rc == 0) if want_ok else (rc != 0 and names.get(off) == "CFG_U_TRIG_ANGLE_X10")
        res.append((v, good, rc, names.get(off, off) if rc else "-"))
    check("I  hc_validate: +-359.9 accepted, +-360.0 / 719.9 refused on the field",
          all(g for _v, g, _r, _o in res),
          "; ".join("%.1f %s" % (v / 10.0, "ok" if g else "rc 0x%04X %s" % (rc, o))
                    for v, g, rc, o in res))

    # ---- J: per pin, mod 360 ----
    for stored in (-780, -20):
        sp = pin_sparks(stored)
        base = (-(py_rotation(stored) / 10.0) - G.ADV_X10 / 10.0) % 360.0
        want = {0: base, 2: base, 1: (base + 180) % 360, 3: (base + 180) % 360}
        errs = {b: max((ang_err(a, want[b], 360.0) for a in sp[b]), default=None)
                for b in range(4)}
        ok = all(len(sp[b]) >= 3 and errs[b] is not None and errs[b] <= 3.0
                 for b in range(4))
        check("J  trigAngle %.1f: P2.0/P2.2 (102/94) at %.1f, P2.1/P2.3 at %.1f"
              % (stored / 10.0, base, (base + 180) % 360), ok,
              "; ".join("P2.%d n=%d worst %s" % (b, len(sp[b]),
                        "-" if errs[b] is None else "%.1f" % errs[b])
                        for b in range(4)))
    sp = pin_sparks(-780, ignpin=[103, 95, 102, 94])
    base = (78.0 - G.ADV_X10 / 10.0) % 360.0
    moved = sp[0] and all(ang_err(a, (base + 180) % 360, 360.0) <= 3.0 for a in sp[0])
    check("J  MUTATION ignPin 102<->103: P2.0 moves to %.1f (the check sees it)"
          % ((base + 180) % 360), bool(moved),
          "P2.0 at %s" % sorted({round(a) for a in sp[0]}))
    return FAILS - f0


def main() -> int:
    if "--one" in sys.argv:
        stem = sys.argv[sys.argv.index("--one") + 1]
        f = main_one(stem)
        print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
        return 1 if f else 0
    import me711_image as PI
    env = dict(os.environ)
    rc = subprocess.call([sys.executable, __file__, "--one", PI.STEM], env=env)
    if "--control" not in sys.argv:
        return rc
    print()
    rc_c = subprocess.call([sys.executable, __file__, "--one", CONTROL_STEM], env=env)
    ok = rc == 0 and rc_c != 0
    print()
    print("CONTROL %s: the image %s, the V96 control %s"
          % ("PASS" if ok else "FAIL", "passes" if rc == 0 else "FAILS",
             "fails (as it must)" if rc_c != 0 else "PASSES (the gate is vacuous)"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
