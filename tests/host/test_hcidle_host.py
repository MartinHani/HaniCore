"""Compile and run the idle speed control core (hcidle.c) host test, its negative
controls, and a Keil check that the far module calls no ?C_ runtime helper
.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import host_c_test as H


SOURCE = H.HCP.find("hcidle.c")
TEST = H.HOST_TESTS / "test_hcidle.c"
KEIL = Path(r"C:\Keil\C166\BIN\C166.EXE")
TARGET = H.ROOT / "firmware" / "targets" / "me711"

CONTROLS = [
    ("integrate_on_coast", "the PI runs above target + band (coast-down)",
     "    if (over) {",
     "    if (0) {"),
    # 2026-10-15 (car): a positive trim opens the throttle above the band
    ("air_above_band", "a positive trim is applied above target + band",
     "    held = (over && d->i_x10 > 0) ? 0 : d->i_x10;",
     "    held = d->i_x10;"),
    ("closed_in_crank", "closed loop while cranking",
     "    if (in->cranking) {",
     "    if (0) {"),
    ("no_start_wait", "closed loop from the first running step",
     "    if (d->run_ms < c->start_ms) {",
     "    if (0) {"),
    ("reset_on_pedal", "the learned trim is dropped when the pedal is pressed",
     "        (void)place(d, in, d->i_x10, range, HCIDLE_S_PEDAL);",
     "        d->integ1000 = 0L; d->i_x10 = 0;\n"
     "        (void)place(d, in, 0, range, HCIDLE_S_PEDAL);"),
    ("no_i_clamp", "the I part is not bounded by the authority",
     "        if (d->integ1000 > lim) d->integ1000 = lim;",
     "        if (d->integ1000 > 1000000L) d->integ1000 = 1000000L;"),
    ("i_on_shrinking_error", "I integrates a transient (error already shrinking)",
     "    if (d->have_last && ((e < 0 && in->rpm < d->last_rpm)",
     "    if (0 && d->have_last && ((e < 0 && in->rpm < d->last_rpm)"),
    ("keep_on_stop", "the trim survives an engine stop",
     "        d->integ1000 = 0L;\n        d->run_ms = 0u;\n        d->p_x10 = 0;\n"
     "        d->i_x10 = 0;\n        return place(d, in, 0, range, HCIDLE_S_STOPPED);",
     "        return place(d, in, d->i_x10, range, HCIDLE_S_STOPPED);"),
    # V97: the dashpot
    ("dash_no_decay", "the adder never decays",
     "    if (t >= c->dash_decay_ms) return 0u;", "    if (0) return 0u;"),
    ("dash_no_hold", "the decay starts at the release",
     "    if (d->dash_ms <= c->dash_hold_ms) return a;",
     "    if (d->dash_ms <= 0u) return a;"),
    ("dash_after_start", "the dashpot fires after a start",
     "        d->dash_ms = 0xFFFFu;\n        d->run_ms = 0u;",
     "        d->dash_ms = 0u;\n        d->run_ms = 0u;"),
    ("dash_not_in_floor", "the adder is not added to the floor",
     "            return with_dash(d, add);", "            return with_dash(d, 0u);"),
    # V97: idle ignition timing
    ("timing_outside_closed", "the timing term acts outside closed-loop idle",
     "    if (!c->enabled || !closed) {", "    if (!c->enabled) {"),
    ("timing_no_soft", "no soft entry",
     "    if (c->soft_ms != 0u && t->closed_ms < c->soft_ms)", "    if (0)"),
    ("timing_no_clamp", "the advance is not bounded by max",
     "    if (out > c->max_x10)", "    if (0 && out > c->max_x10)"),
    ("timing_wrong_sign", "retard below target",
     "    out = below ? (int)mag : -(int)mag;", "    out = below ? -(int)mag : (int)mag;"),
]


def keil_check() -> bool:
    if not KEIL.exists():
        print("SKIP: Keil C166 not found - helper check not run")
        return True
    out = Path(tempfile.mkdtemp())
    r = subprocess.run([str(KEIL), str(SOURCE), "MOD167", "MEDIUM",
                        "RENAMECLASS(NDATA0=XNDATA0)",
                        "OBJECT(%s)" % (out / "hcidle.obj"),
                        "PRINT(%s)" % (out / "hcidle.lst"), "INCDIR(%s)" % ";".join(map(str, H.HCP.include_dirs("me711"))), "CODE"],
                       cwd=str(TARGET), capture_output=True, text=True)
    lst = (out / "hcidle.lst").read_text(errors="replace") if (out / "hcidle.lst").exists() else ""
    if "0 WARNING(S),  0 ERROR(S)" not in (r.stdout + lst):
        print("FAIL: Keil C166 did not compile hcidle.c cleanly")
        return False
    helpers = sorted(set(re.findall(r"CALLS\s+SEG \((\?C_\w+)\)", lst)))
    if helpers:
        print("FAIL: hcidle.c (far) calls Keil runtime helpers: %s" % ", ".join(helpers))
        return False
    size = re.search(r"CODE SIZE\s+=\s+(\d+)", lst)
    print("PASS: Keil C166 MEDIUM, 0 warnings, no ?C_ helper call (%s bytes)"
          % (size.group(1) if size else "?"))
    return True


def main() -> int:
    ran = H.run("hcidle", [SOURCE, TEST])
    if ran is None:
        return 0
    cc, env = ran
    src = SOURCE.read_text()
    bad = 0
    for name, what, old, new in CONTROLS:
        assert src.count(old) == 1, "mutation point moved - update control " + name
        mutant = Path(tempfile.gettempdir()) / ("hcidle_mutant_%s.c" % name)
        mutant.write_text(src.replace(old, new))
        exe = H.TMP / ("hc_hcidle_mutant_%s.exe" % name)
        H.build(cc, env, [mutant, TEST], H.SHARED, exe, flags=("-w",))
        r = subprocess.run([str(exe)], env=env, capture_output=True, text=True)
        if r.returncode == 0:
            print("FAIL: control %s - %s - passed the tests" % (name, what))
            bad += 1
        else:
            first = [ln for ln in (r.stdout + r.stderr).splitlines() if "Assertion" in ln][:1]
            print("PASS: control %s - %s - fails (%s)"
                  % (name, what, first[0].strip() if first else "exit %d" % r.returncode))
    if not keil_check():
        bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
