#!/usr/bin/env python3
r"""
me711_trigger_vehicle_test.py - the COMPRESSION PROFILE on the car: where is
compression TDC relative to the 60-2 gap, measured by the crank itself.

    py me711_trigger_vehicle_test.py

Close TunerStudio first (same COM port). Key ON, engine OFF.

WHAT HAPPENS
  1. Identifies the ECU and the matching .ini; proves the engine is stopped.
  2. Arms the compression profile ('!K1'): SPARK AND FUEL ARE HELD OFF by the
     firmware (HC_INHIBIT_TEST) until the crank stops or 30 s pass; the tool
     checks the inhibit is really set before telling you to crank.
  3. You crank ~5 s. The tool counts synchronised revolutions and tells you
     when it has enough (>= 8). Let go of the key: the profile completes when
     the crank stops.
  4. It fetches the 60-bin tooth-period profile, saves it raw and decoded,
     fits the compression harmonic, and prints the TDC estimate, the
     trigAngleX10 it implies (tooth #1, deg ATDC), and a confidence verdict.

PLUGS-OUT MODE (--plugs-out 1,4) - THE ONE THAT DECIDES WHICH PAIR IS WHICH.
  With every plug in, a four compresses twice per revolution and the profile
  cannot tell the 1/4 lobe from the 2/3 lobe (both 180 deg apart). Take the
  spark plugs of cylinders 1 AND 4 out (coils unplugged), and only the 2/3
  lobe is left: TDC#1 is then that lobe + 180 deg - measured by the crank,
  independent of the coil wiring and of every reference. (--plugs-out 2,3
  mirrors it; a single plug gives a half-height lobe and is also decided.)
  an OEM-firmware analysis script (not published) prints what each answer means.

It changes NOTHING in the calibration and never burns. The engine cannot
start during the test (spark and fuel inhibited). Timing-light work is not
part of this tool.

Since V93 the profile survives a reset/key-off (the V92 card lost it), so a
test taken earlier can also be fetched later: --fetch-only.

EVIDENCE: VEHICLE_EVIDENCE\TRIGGER_VEHICLE_TEST_<UTC>\ beside this tool -
metadata.json, profile_raw.bin, profile.csv, samples.csv, events.jsonl,
frames.jsonl, console.log, summary.txt.
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_commission as MC             # noqa: E402

TOOL_VERSION = "1.1 (V97)"
ALLOWED = b"SQVOR!"
TL_EXT_OFF = 344
TL_BINS = 60
TL_ARMED, TL_RUN, TL_DONE, TL_REFUSED, TL_ABORTED, TL_TIMEOUT = 1, 2, 3, 4, 5, 6
INHIBIT_TEST = 0x0040
ENOUGH_REVS = 8
FIELDS = ["rpm", "syncState", "battDv", "cfgValidation", "safetyInhibits",
          "outputAuthority", "runOn", "toothLogState", "toothLogRevs",
          "toothLogTeeth", "crankEdges", "crankGaps", "syncLossCount",
          "toothCorrections", "trigCfgAngleX10"]
# Independent geometry for the gap-end tooth, deg BTDC (evidence/
# V92_VEHICLE_20260927 F7).
GEOMETRY = [("rusEFI vw.cpp / hellen121vag", 93),
            ("rusEFI vw_b6.cpp", 90),
            ("stock AWT grundwert 72 + 6 (4B0906018DC)", 78),
            ("aftermarket 1.8T setups", 78)]


PAIRS = ({1, 4}, {2, 3})          # an inline four's wasted pairs (1-3-4-2, 1-2-4-3)


def parse_plugs(text):
    """'1,4' -> {1, 4}; refuses anything that is not cylinders 1..4."""
    if not text:
        return set()
    out = {int(s) for s in text.replace(" ", "").split(",") if s}
    if not out or not out <= {1, 2, 3, 4}:
        raise SystemExit("--plugs-out takes cylinders 1..4, e.g. 1,4")
    return out


def pair_decision(bins, offset_x10, plugs_out):
    """The plugs-out profile: which pair's compression lobe is missing.

    Fits the ONCE-per-revolution harmonic. With the plugs of one pair out,
    the remaining pair still compresses once per revolution, so the slowest
    point of that harmonic is just before the REMAINING pair's TDC. The pair
    with more plugs out is the weaker lobe; if both pairs lost the same number
    the test cannot decide and says so."""
    off = ((offset_x10 or 0) / 10.0) % 360.0
    pts = []
    for b, v in enumerate(bins):
        if v:
            pts.append((((b * 6 + (off % 6)) - off) % 360.0, v))
    if len(pts) < 40:
        return {"valid": False, "why": "only %d of 60 bins filled" % len(pts)}
    out_a = len(plugs_out & PAIRS[0])
    out_b = len(plugs_out & PAIRS[1])
    if out_a == out_b:
        return {"valid": False,
                "why": "plugs %s leave both pairs equal - nothing to decide"
                       % sorted(plugs_out)}
    m = sum(v for _, v in pts) / len(pts)

    def harm(k):
        c = sum((v - m) * math.cos(math.radians(k * p)) for p, v in pts) * 2 / len(pts)
        s = sum((v - m) * math.sin(math.radians(k * p)) for p, v in pts) * 2 / len(pts)
        return (math.degrees(math.atan2(s, c)) / k) % (360.0 / k), math.hypot(c, s)

    ph1, a1 = harm(1)
    _ph2, a2 = harm(2)
    lobe_tdc = (ph1 + 7.5) % 360.0            # the pair that still compresses
    remaining_is_14 = out_b > out_a
    tdc1 = lobe_tdc if remaining_is_14 else (lobe_tdc + 180.0) % 360.0
    angle = round(((180.0 - tdc1) % 360.0) - 180.0, 1)
    ratio = a1 / a2 if a2 > 0 else float("inf")
    conf = ("HIGH" if a1 >= 30 and ratio >= 1.5 else
            "MEDIUM" if a1 >= 15 and ratio >= 0.8 else "LOW")
    return {"valid": True, "plugs_out": sorted(plugs_out),
            "remaining_pair": "1/4" if remaining_is_14 else "2/3",
            "lobe_tdc_phys": round(lobe_tdc, 1), "tdc1_phys": round(tdc1, 1),
            "angle_x10": int(round(angle * 10)),
            "rev_harmonic_permille": round(a1, 1),
            "half_rev_harmonic_permille": round(a2, 1),
            "confidence": conf}


def analyse(bins, offset_x10, cylinders=4):
    """60 per-mille bins (ENGINE angle / 6, mod 360) -> TDC estimate.

    Cranking with spark and fuel off, the crank is slowest just BEFORE each
    compression TDC (the starter stalls where gas torque beats it) and
    compression TDC lies 0..15 deg after the slowest point. A four has two
    compressions per revolution, so the fitted harmonic is cylinders/2 and
    its maximum repeats every 180 deg: TDC#1 is one of the two candidates;
    which one, the geometry decides (the profile cannot tell cylinders
    apart)."""
    # the trigger angle (tooth #1, deg ATDC, signed); only mod 360 matters -
    # it IS the decoder's rotation (hc_trig_rotation_x10)
    off = ((offset_x10 or 0) / 10.0) % 360.0
    k = max(1, int(cylinders) // 2)
    pts = []
    rows = []
    for b, v in enumerate(bins):
        eng = b * 6 + (off % 6)
        phys = (eng - off) % 360.0
        rows.append((b, round(eng, 1), round(phys, 1), v))
        if v:
            pts.append((phys, v))
    res = {"rows": rows, "valid": False}
    if len(pts) < 40:
        res["why"] = "only %d of 60 bins filled" % len(pts)
        return res
    m = sum(v for _, v in pts) / len(pts)
    var = sum((v - m) ** 2 for _, v in pts) / len(pts)

    def fit(sel):
        c = sum((v - m) * math.cos(math.radians(k * p)) for p, v in sel) * 2 / len(sel)
        s = sum((v - m) * math.sin(math.radians(k * p)) for p, v in sel) * 2 / len(sel)
        return (math.degrees(math.atan2(s, c)) / k) % (360.0 / k), math.hypot(c, s)

    ph, amp = fit(pts)
    # variance the harmonic explains
    model = [amp * math.cos(math.radians(k * (p - ph))) for p, _ in pts]
    resid = sum((v - m - mm) ** 2 for (p, v), mm in zip(pts, model)) / len(pts)
    explained = 1.0 - resid / var if var > 0 else 0.0
    # the two half-revolutions separately: their slow points must be 180 apart
    h1 = [(p, v) for p, v in pts if (p - ph + 90) % 360 < 180]
    h2 = [(p, v) for p, v in pts if (p - ph + 90) % 360 >= 180]

    def slowest(sel):
        return max(sel, key=lambda pv: pv[1])[0] if sel else float("nan")

    s1, s2 = slowest(h1), slowest(h2)
    lobe_gap = abs(((s2 - s1) % 360) - 180) if h1 and h2 else 999
    tdc = [(ph + 7.5 + i * 360.0 / k) % 360 for i in range(k)]
    # tooth #1 at physical 0 and TDC#1 at physical t: tooth #1 is t BTDC,
    # i.e. the trigger angle is -t (normalised to -180..180)
    cands = [(t, round(((180.0 - t) % 360.0) - 180.0, 1)) for t in tdc]
    # which candidate does the geometry support
    geo = []
    for name, btdc in GEOMETRY:
        best = min(cands, key=lambda c: min(abs(c[0] - btdc), 360 - abs(c[0] - btdc)))
        d = min(abs(best[0] - btdc), 360 - abs(best[0] - btdc))
        geo.append((name, btdc, best[1], round(d, 1)))
    pick = min(cands, key=lambda c: min(abs(c[0] - 85), 360 - abs(c[0] - 85)))
    score = 0
    reasons = []
    if amp >= 30:
        score += 1
    else:
        reasons.append("ripple amplitude only %.0f per mille" % amp)
    if explained >= 0.5:
        score += 1
    else:
        reasons.append("harmonic explains only %.0f %% of the variance"
                       % (100 * explained))
    if lobe_gap <= 15:
        score += 1
    else:
        reasons.append("the two compression lobes are %.0f deg from 180 apart"
                       % lobe_gap)
    conf = ("HIGH" if score == 3 else "MEDIUM" if score == 2 else "LOW")
    res.update({
        "valid": True, "slowest_phys": round(ph, 1),
        "amplitude_permille": round(amp, 1),
        "explained": round(explained, 3), "lobe_error_deg": round(lobe_gap, 1),
        "tdc_candidates_phys": [round(t, 1) for t in tdc],
        "angle_candidates_x10": [int(round(c[1] * 10)) for c in cands],
        "tdc1_phys": round(pick[0], 1),
        "angle_suggested_x10": int(round(pick[1] * 10)),
        "angle_current_x10": int(offset_x10 or 0),
        "geometry": geo, "confidence": conf, "confidence_reasons": reasons,
    })
    return res


class TriggerTest:
    def __init__(self, a, sess):
        self.a, self.s = a, sess
        self.plugs = parse_plugs(getattr(a, "plugs_out", None))
        self.link, self.ini, self.sig, self.ver = MC.connect(
            a.port, a.ini, sess, ALLOWED)
        if "toothLogState" not in self.ini.scalars:
            raise SystemExit("this ECU/.ini has no tooth profile (V92+ needed)")
        self.rd = MC.Reader(self.link, self.ini, FIELDS)
        pg = self.link.page_read()
        self.cfg = MC.VC.page_config(self.ini.path, pg) if pg else {}
        if pg:
            (sess.dir / "page.bin").write_bytes(pg)
        sess.meta["page_config"] = self.cfg

    def sample(self):
        for _ in range(3):
            v = self.rd.read()
            if v is not None:
                return v
        return None

    def preflight(self) -> bool:
        s = self.s
        v = self.sample()
        if v is None:
            s.say("PREFLIGHT: no telemetry")
            return False
        ok = True

        def c(cond, text):
            nonlocal ok
            ok = ok and cond
            s.say("  [%s] %s" % ("OK  " if cond else "STOP", text))

        s.say("PREFLIGHT")
        c(v["rpm"] == 0 and v["syncState"] == 0,
          "engine stopped (rpm %d, syncState %d)" % (v["rpm"], v["syncState"]))
        c(v["cfgValidation"] == 0, "configuration valid")
        c(not ((v.get("runOn", 0) >> 8) & 1), "key on")
        b = v["battDv"] / 10.0
        c(b >= self.a.battery_min, "battery %.1f V >= %.1f V (a weak battery "
          "stalls the starter at compression)"
          % (b, self.a.battery_min))
        s.say("  config: %s cylinders, %s-%s wheel, trigAngleX10 %s (tooth #1 "
              "%.1f deg ATDC as configured)"
              % (self.cfg.get("cylinders"), self.cfg.get("syTeeth"),
                 self.cfg.get("syGap"), self.cfg.get("trigAngleX10"),
                 (self.cfg.get("trigAngleX10") or 0) / 10.0))
        s.meta["steps"].append({"step": "preflight", "ok": ok})
        return ok

    def fetch(self, v):
        off = self.ini.block + TL_EXT_OFF
        body, err, _ = self.link.och(off, 2 * TL_BINS)
        if body is None or len(body) != 2 * TL_BINS:
            self.s.say("  profile read failed: %s" % err)
            return None
        (self.s.dir / "profile_raw.bin").write_bytes(body)
        return [int.from_bytes(body[2 * i:2 * i + 2], "big")
                for i in range(TL_BINS)]

    def report(self, bins, v):
        s = self.s
        res = analyse(bins, self.cfg.get("trigAngleX10"),
                      self.cfg.get("cylinders") or 4)
        pd = None
        if self.plugs:
            pd = pair_decision(bins, self.cfg.get("trigAngleX10"), self.plugs)
            s.meta["pair_decision"] = pd
        with (s.dir / "profile.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["bin", "engine_deg", "physical_deg", "permille"])
            w.writerows(res["rows"])
        res.pop("rows")
        res.update({"revs": v.get("toothLogRevs"), "teeth": v.get("toothLogTeeth"),
                    "state": v.get("toothLogState")})
        s.meta["result"] = res
        lines = []
        if not res["valid"]:
            lines.append("RESULT: NO ESTIMATE - %s" % res.get("why"))
        else:
            lines += [
                "RESULT: compression profile, %s revolutions, %s teeth"
                % (res["revs"], res["teeth"]),
                "  slowest crank angle        physical %.1f deg after the gap-end tooth"
                % res["slowest_phys"],
                "  compression TDC candidates physical %s (TDC 0..15 deg after the "
                "slowest point, centre used)" % res["tdc_candidates_phys"],
                "  TDC#1 (geometry picks)     physical %.1f deg -> gap-end tooth "
                "%.1f deg BTDC" % (res["tdc1_phys"], res["tdc1_phys"]),
                "  trigAngleX10 implied       %d   (current %d; the other "
                "candidate %s is 180 deg away)" % (
                    res["angle_suggested_x10"], res["angle_current_x10"],
                    [c for c in res["angle_candidates_x10"]
                     if c != res["angle_suggested_x10"]]),
                "  CONFIDENCE: %s  (ripple %.0f per mille, harmonic explains "
                "%.0f %%, lobes %.0f deg off 180)" % (
                    res["confidence"], res["amplitude_permille"],
                    100 * res["explained"], res["lobe_error_deg"]),
            ]
            for r in res["confidence_reasons"]:
                lines.append("    - %s" % r)
            lines.append("  geometry references (gap-end tooth deg BTDC -> "
                         "the candidate nearest, distance):")
            for name, btdc, cand, d in res["geometry"]:
                lines.append("    %-42s %3d deg -> %5.1f  (%.1f deg)" % (
                    name, btdc, cand / 1.0, d))
            if pd is not None:
                if pd["valid"]:
                    lines += [
                        "PLUGS-OUT %s: the lobe left is cylinders %s, TDC at "
                        "physical %.1f" % (pd["plugs_out"], pd["remaining_pair"],
                                           pd["lobe_tdc_phys"]),
                        "  => TDC#1 at physical %.1f -> trigAngleX10 %d "
                        "(no geometry reference used)" % (pd["tdc1_phys"],
                                                          pd["angle_x10"]),
                        "  PAIR CONFIDENCE: %s (once-per-rev ripple %.0f, "
                        "twice-per-rev %.0f per mille)" % (
                            pd["confidence"], pd["rev_harmonic_permille"],
                            pd["half_rev_harmonic_permille"]),
                        "  Compare it with the coil continuity result."]
                else:
                    lines.append("PLUGS-OUT: NO PAIR DECISION - %s" % pd["why"])
            lines.append("  NOTHING WAS CHANGED. Enter a new trigAngleX10 only "
                         "after reviewing this with the evidence.")
        for ln in lines:
            s.say(ln)
        return lines

    def run(self) -> list[str]:
        s = self.s
        v = self.sample()
        st = (v or {}).get("toothLogState", 0)
        if self.a.fetch_only:
            if (st & 0xFF) != TL_DONE:
                return ["NO FINISHED PROFILE IN THE ECU (toothLogState 0x%04X)" % st]
            bins = self.fetch(v)
            return self.report(bins, v) if bins else ["PROFILE READ FAILED"]
        if not self.preflight():
            return ["PREFLIGHT FAILED - nothing was armed"]
        if not self.a.yes:
            input("\nPress ENTER to ARM the compression profile (spark and fuel "
                  "will be held OFF) ... ")
        self.link.command(b"K\x01")
        s.event("ARM_SENT")
        time.sleep(0.3)
        v = self.sample() or {}
        st = v.get("toothLogState", 0)
        inh = v.get("safetyInhibits", 0)
        if (st & 0xFF) != TL_ARMED or ((st >> 8) & 0x3F) != 1:
            return ["ARM REFUSED (toothLogState 0x%04X) - the engine must be "
                    "stopped" % st]
        if not inh & INHIBIT_TEST:
            self.link.command(b"K\x00")
            return ["ABORTED: the firmware did not report spark/fuel inhibited "
                    "(safetyInhibits 0x%04X) - test cancelled" % inh]
        s.say("\nARMED - spark and fuel are OFF (safetyInhibits 0x%04X)." % inh)
        s.say(">>> CRANK THE ENGINE NOW for about 5 seconds. It will not start. <<<")
        s.event("ARMED", inhibits=inh)
        f = (s.dir / "samples.csv").open("w", newline="", encoding="utf-8")
        w = csv.writer(f)
        w.writerow(["t", "state", "revs", "teeth", "rpm", "syncState", "batt_v",
                    "syncLoss", "toothCorr", "inhibits"])
        t0 = time.monotonic()
        told = False
        try:
            while True:
                v = self.sample()
                if v is None:
                    s.say("  telemetry lost")
                    break
                t = time.monotonic() - t0
                st = v["toothLogState"]
                w.writerow([round(t, 2), st, v["toothLogRevs"], v["toothLogTeeth"],
                            v["rpm"], v["syncState"], v["battDv"] / 10.0,
                            v["syncLossCount"], v["toothCorrections"],
                            v["safetyInhibits"]])
                if v["toothLogRevs"] >= ENOUGH_REVS and not told:
                    s.say(">>> ENOUGH (%d revolutions) - RELEASE THE KEY. <<<"
                          % v["toothLogRevs"])
                    s.event("ENOUGH", revs=v["toothLogRevs"])
                    told = True
                if (st & 0xFF) in (TL_DONE, TL_ABORTED, TL_TIMEOUT, TL_REFUSED):
                    break
                if t > 45:
                    self.link.command(b"K\x00")
                    s.say("  tool limit - aborted")
                    break
                time.sleep(0.1)
        except KeyboardInterrupt:
            self.link.command(b"K\x00")
            s.say("  Ctrl-C - aborted (spark/fuel inhibit released)")
        f.close()
        v = self.sample() or v or {}
        st = v.get("toothLogState", 0)
        s.event("FINISHED", state=st, revs=v.get("toothLogRevs"))
        if (st & 0xFF) != TL_DONE:
            names = {TL_TIMEOUT: "armed 30 s and never cranked",
                     TL_ABORTED: "aborted", TL_REFUSED: "refused"}
            return ["NO PROFILE: %s (toothLogState 0x%04X)"
                    % (names.get(st & 0xFF, "state %d" % (st & 0xFF)), st)]
        if (v.get("toothLogRevs") or 0) < 4:
            s.say("  only %s revolutions - the estimate will be weak"
                  % v.get("toothLogRevs"))
        bins = self.fetch(v)
        return self.report(bins, v) if bins else ["PROFILE READ FAILED"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", default="auto")
    ap.add_argument("--ini", default=None)
    ap.add_argument("--yes", action="store_true", help="arm without the ENTER")
    ap.add_argument("--fetch-only", action="store_true",
                    help="read a finished profile, arm nothing")
    ap.add_argument("--battery-min", type=float, default=11.5)
    ap.add_argument("--plugs-out", default=None,
                    help="cylinders whose spark plugs are OUT, e.g. 1,4 - "
                         "decides which wasted pair is TDC#1")
    ap.add_argument("--evidence", default=None)
    a = ap.parse_args(argv)
    sess = MC.Session("TRIGGER_VEHICLE_TEST",
                      Path(a.evidence) if a.evidence else None, argv)
    sess.meta["tool_version"] = TOOL_VERSION
    sess.say("HaniCore trigger vehicle test %s -> %s" % (TOOL_VERSION, sess.dir))
    try:
        t = TriggerTest(a, sess)
        lines = t.run()
        (sess.dir / "summary.txt").write_text(
            "HaniCore trigger vehicle test %s\n%s\n%s / %s\n\n%s\n" % (
                TOOL_VERSION, sess.dir, t.ver, t.sig, "\n".join(lines)),
            encoding="utf-8")
        sess.say("\n".join([""] + lines + ["", "Evidence: %s" % sess.dir]))
        ok = bool(lines) and lines[0].startswith("RESULT: compression")
    finally:
        sess.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
