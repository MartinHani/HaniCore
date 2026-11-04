"""Vehicle speed + gear core (firmware/sensors/hcvss.c) on gcc.

The Python side SIMULATES THE CAPTURE INTERRUPT (an edge counter and the
millisecond of the last edge, as hcvss711.c's ISR records them) for a pulse
train of a known speed, steps the core every 20 ms like the main loop, and
checks the result against its own arithmetic (km/h = Hz x 3600 / pulses per
km) - not against hcvss.c's formula. Gear detection is checked against the
per-gear speed-per-1000-rpm values and geometric-mean boundaries computed
here. Mutation controls must fail; a Keil MEDIUM compile checks for ?C_
helpers (the core is built into a far module).
"""
from __future__ import annotations

import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402

import host_c_test as H

SOURCE = H.HCP.find("hcvss.c")
TEST = H.HOST_TESTS / "test_hcvss.c"
KEIL = Path(r"C:\Keil\C166\BIN\C166.EXE")

CONTROLS = [
    ("k_3600", "k from 3 600 000 instead of 36 000 000",
     "return DIV32U(36000000uL, ppk);", "return DIV32U(3600000uL, ppk);"),
    ("no_timeout", "the standing timeout never fires",
     "        if (since >= tmo_ms) {", "        if (since >= 60000u) {"),
    ("no_cap", "no decay while the edges stop",
     "            if (s->raw_x10 > cap) {", "            if (0) {"),
    ("arith_boundary", "gear boundary at the arithmetic mean x2",
     "        if ((unsigned long)v * v < (unsigned long)g[i] * g[i + 1u]) {",
     "        if ((unsigned long)v * 2u < (unsigned long)g[i] + g[i + 1u]) {"),
    ("no_hold", "the current gear is not held inside its band",
     "            return cur;              /* held inside its band */",
     "            ;"),
]

PPK = 4345          # a VAG speed sender figure; any value >= 550 works
GEARS = [760, 1390, 2030, 2680, 3330]   # km/h per 1000 rpm x100, a 5-speed


class Core:
    def __init__(self, exe, env):
        self.p = subprocess.Popen([str(exe)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True, env=env)

    def q(self, line):
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()
        return int(self.p.stdout.readline())

    def cmd(self, line):
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()

    def close(self):
        self.p.stdin.close()
        self.p.wait()


def drive(core, k, profile, secs, filt=0, tmo=0, t0=0.0, state=None):
    """profile(t) -> km/h. Simulate edges at the pulse train's own times;
    the ISR stamps floor(ms). Step every 20 ms; return [(t, speed)]."""
    st = state or {"n": 0, "ms_edge": 0, "phase": 0.0}
    out = []
    t = t0
    dt = 0.0005
    while t < t0 + secs:
        v = profile(t)
        st["phase"] += v * PPK / 3600.0 * dt     # pulses
        while st["phase"] >= 1.0:
            st["phase"] -= 1.0
            st["n"] = (st["n"] + 1) & 0xFFFF
            st["ms_edge"] = int(t * 1000) & 0xFFFF
        t += dt
        if int(t * 1000) % 20 == 0 and int((t - dt) * 1000) % 20 != 0:
            now = int(t * 1000) & 0xFFFF
            out.append((t, core.q("step %d %d %d %d %d %d" % (st["n"], st["ms_edge"],
                                                             now, k, filt, tmo))))
    return out, st


def checks(exe, env) -> list[str]:
    fails = []

    def ok(c, what):
        if not c:
            fails.append(what)

    c = Core(exe, env)
    k = c.q("k %d" % PPK)
    ok(abs(k - 36e6 / PPK) < 1.0, "k = 36e6 / ppk (got %d)" % k)
    ok(c.q("k 500") == 0, "fewer than 550 pulses per km is unusable")
    ok(c.q("step 5 100 120 0 0 0") == 0xFFFF, "k 0 -> no speed")

    for kmh in (5.0, 30.0, 100.0, 250.0):
        c.cmd("reset 0")
        res, _ = drive(c, k, lambda t: kmh, 3.0)
        last = [v for t, v in res if t > 2.0]
        mean = sum(last) / len(last) / 10.0
        ok(abs(mean - kmh) <= max(0.012 * kmh, 0.3),
           "steady %.0f km/h reads %.2f" % (kmh, mean))

    # standing: the edges stop -> falls, 0 within the 0.8 s timeout + a step
    c.cmd("reset 0")
    res, st = drive(c, k, lambda t: 60.0, 2.0)
    res2, _ = drive(c, k, lambda t: 0.0, 1.2, t0=2.0, state=st)
    mid = [v for t, v in res2 if 2.3 < t < 2.5]
    ok(mid and max(mid) < 600, "no edges: the speed falls before the timeout (%s)" % mid[:3])
    ok(all(v == 0 for t, v in res2 if t > 2.0 + 0.82), "0 after 0.8 s without an edge")

    # filter: filt 12 reaches the target exactly, more slowly than filt 0
    c.cmd("reset 0")
    r0, _ = drive(c, k, lambda t: 80.0, 1.0, filt=0)
    c.cmd("reset 0")
    r12, _ = drive(c, k, lambda t: 80.0, 1.0, filt=12)
    t0_ = next((t for t, v in r0 if v >= 760), 9)
    t12 = next((t for t, v in r12 if v >= 760), 9)
    ok(t12 > t0_, "a filter slows the response (%.2f vs %.2f s)" % (t12, t0_))
    c.cmd("reset 0")
    r12b, _ = drive(c, k, lambda t: 80.0, 4.0, filt=12)
    ok(abs(r12b[-1][1] - 800) <= 10, "filtered speed reaches 80.0 (%d)" % r12b[-1][1])

    # gears
    def gear(vx10, rpm, band=0, mn=0, gs=GEARS):
        return c.q("gear %d %d %d %d %d %s" % (vx10, rpm, band, mn, len(gs),
                                              " ".join(map(str, gs))))
    for i, g in enumerate(GEARS):
        rpm = 3000
        v = round(g / 100.0 * rpm / 1000.0 * 10)
        c.cmd("reset 0")
        ok(gear(v, rpm) == i + 1, "gear %d at its own ratio" % (i + 1))
    # boundaries: just below / above the geometric mean of 2nd and 3rd
    gm = math.sqrt(GEARS[1] * GEARS[2]) / 100.0
    c.cmd("reset 0")
    ok(gear(round(gm * 0.97 * 3 * 10), 3000) == 2, "below the 2/3 geometric mean = 2nd")
    c.cmd("reset 0")
    ok(gear(round(gm * 1.03 * 3 * 10), 3000) == 3, "above the 2/3 geometric mean = 3rd")
    # between the geometric (1680) and the arithmetic (1710) mean: 3rd
    am = (GEARS[1] + GEARS[2]) / 200.0
    v_mid = round((gm + am) / 2 * 3 * 10)
    c.cmd("reset 0")
    ok(gear(v_mid, 3000) == 3, "between the geometric and arithmetic mean = 3rd "
       "(geometric boundary)")
    # hold: in 2nd, a ratio 8 % above 2nd (past the boundary is not needed)
    c.cmd("reset 0")
    gear(round(GEARS[1] / 100.0 * 3 * 10), 3000)
    v_hold = round(GEARS[1] * 1.08 / 100.0 * 3 * 10)
    ok(gear(v_hold, 3000) == 2, "2nd held 8 % above its ratio (band 10 %)")
    # without hold (fresh state) the same ratio is still 2nd if below the mean;
    # take one ABOVE the mean but inside 2nd's 25 % band
    v_hb = round(gm * 1.02 * 3 * 10)
    c.cmd("reset 0")
    gear(round(GEARS[1] / 100.0 * 3 * 10), 3000)
    ok(gear(v_hb, 3000, band=25) == 2, "hold band 25 % keeps 2nd past the mean")
    c.cmd("reset 0")
    ok(gear(v_hb, 3000, band=25) == 3, "...while a fresh detection says 3rd")
    # neutral / implausible
    c.cmd("reset 0")
    ok(gear(25, 3000) == 0, "below 3 km/h = 0")
    ok(gear(round(GEARS[0] / 100.0 / 1.6 * 3 * 10), 3000) == 0, "below 1st / 1.5 (clutch) = 0")
    ok(gear(round(GEARS[-1] / 100.0 * 1.6 * 3 * 10), 3000) == 0, "above top x 1.5 = 0")
    ok(gear(500, 300) == 0, "below 400 rpm = 0")
    ok(gear(500, 3000, gs=[760, 1390, 1390]) == 0, "gears not ascending = 0")
    ok(gear(500, 3000, gs=[]) == 0, "no gears = off")
    ok(c.q("v1000 1000 2500") == 4000, "100 km/h at 2500 rpm = 40.00 per 1000 rpm")
    c.close()
    return fails


def keil_check() -> bool:
    if not KEIL.exists():
        print("SKIP: Keil C166 not found - helper check not run")
        return True
    out = Path(tempfile.mkdtemp())
    target = H.ROOT / "firmware" / "targets" / "me711"
    r = subprocess.run([str(KEIL), str(SOURCE), "MOD167", "MEDIUM",
                        "RENAMECLASS(NDATA0=XNDATA0)",
                        "OBJECT(%s)" % (out / "hcvss.obj"),
                        "PRINT(%s)" % (out / "hcvss.lst"),
                        "INCDIR(%s)" % ";".join(map(str, H.HCP.include_dirs("me711"))), "CODE"],
                       cwd=str(target), capture_output=True, text=True)
    lst = (out / "hcvss.lst").read_text(errors="replace") if (out / "hcvss.lst").exists() else ""
    if "0 WARNING(S),  0 ERROR(S)" not in (r.stdout + lst):
        print("FAIL: Keil C166 did not compile hcvss.c cleanly")
        print(r.stdout[-1500:])
        return False
    helpers = sorted(set(re.findall(r"CALLS\s+SEG \((\?C_\w+)\)", lst)))
    if helpers:
        print("FAIL: hcvss.c (far) calls Keil runtime helpers: %s" % ", ".join(helpers))
        return False
    print("PASS: Keil C166 MEDIUM, 0 warnings, no ?C_ helper call")
    return True


def main() -> int:
    cc = H.compiler()
    if cc is None:
        print("SKIP: no C host compiler found")
        return 0
    env = H.env_for(cc)
    H.TMP.mkdir(parents=True, exist_ok=True)
    exe = H.TMP / "hc_hcvss_host.exe"
    H.build(cc, env, [SOURCE, TEST], H.SHARED, exe)
    fails = checks(exe, env)
    for f in fails:
        print("FAIL:", f)
    if fails:
        return 1
    print("PASS: speed from a simulated pulse train (5..250 km/h within 1.2 %), "
          "decay + 0.8 s standing, filter; gears at their ratios, geometric-mean "
          "boundaries, hold band, neutral cases")
    bad = 0
    src = SOURCE.read_text()
    for name, what, old, new in CONTROLS:
        assert src.count(old) == 1, "mutation point moved - update control " + name
        mutant = Path(tempfile.gettempdir()) / ("hcvss_mutant_%s.c" % name)
        mutant.write_text(src.replace(old, new))
        mexe = H.TMP / ("hc_hcvss_mutant_%s.exe" % name)
        H.build(cc, env, [mutant, TEST], H.SHARED, mexe, flags=("-w",))
        mf = checks(mexe, env)
        if not mf:
            print("FAIL: control %s - %s - passed the checks" % (name, what))
            bad += 1
        else:
            print("PASS: control %s - %s - fails (%s)" % (name, what, mf[0]))
    if not keil_check():
        bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
