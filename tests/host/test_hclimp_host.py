"""Compile and run the engine protection core (hclimp.c) host test, its negative
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


SOURCE = H.HCP.find("hclimp.c")
TEST = H.HOST_TESTS / "test_hclimp.c"
KEIL = Path(r"C:\Keil\C166\BIN\C166.EXE")
TARGET = H.ROOT / "firmware" / "targets" / "me711"

CONTROLS = [
    ("no_hysteresis", "the rev-limit cuts release at the limit",
     "    if (was && (unsigned long)rpm + HCLIMP_HYST_RPM >= (unsigned long)lim) return 1u;",
     "    (void)was;"),
    ("judge_bad_clt", "a faulted coolant sensor is still judged",
     "    if (c->clt_max_x10 != 0 && in->clt_ok && in->clt_x10 > c->clt_max_x10",
     "    if (c->clt_max_x10 != 0 && in->clt_x10 > c->clt_max_x10"),
    ("oil_unlatched", "the oil cut releases when pressure returns",
     "    if (l->cut & HCLIMP_OIL && in->rpm != 0u) cut |= HCLIMP_OIL;",
     "    ;"),
    ("duty_unlatched", "the duty cut releases as soon as the duty drops",
     "        if (trip || ((l->cut & HCLIMP_DUTY) && in->duty_x10 >= 200u))",
     "        if (trip)"),
    ("flood_running", "flood clear also while running",
     "    if (c->flood_x10 != 0u && !running && in->pedal_x10 > c->flood_x10)",
     "    if (c->flood_x10 != 0u && in->pedal_x10 > c->flood_x10)"),
]


def keil_check() -> bool:
    if not KEIL.exists():
        print("SKIP: Keil C166 not found - helper check not run")
        return True
    out = Path(tempfile.mkdtemp())
    r = subprocess.run([str(KEIL), str(SOURCE), "MOD167", "MEDIUM",
                        "RENAMECLASS(NDATA0=XNDATA0)",
                        "OBJECT(%s)" % (out / "hclimp.obj"),
                        "PRINT(%s)" % (out / "hclimp.lst"), "INCDIR(%s)" % ";".join(map(str, H.HCP.include_dirs("me711"))), "CODE"],
                       cwd=str(TARGET), capture_output=True, text=True)
    lst = (out / "hclimp.lst").read_text(errors="replace") if (out / "hclimp.lst").exists() else ""
    if "0 WARNING(S),  0 ERROR(S)" not in (r.stdout + lst):
        print("FAIL: Keil C166 did not compile hclimp.c cleanly")
        return False
    helpers = sorted(set(re.findall(r"CALLS\s+SEG \((\?C_\w+)\)", lst)))
    if helpers:
        print("FAIL: hclimp.c (far) calls Keil runtime helpers: %s" % ", ".join(helpers))
        return False
    size = re.search(r"CODE SIZE\s+=\s+(\d+)", lst)
    print("PASS: Keil C166 MEDIUM, 0 warnings, no ?C_ helper call (%s bytes)"
          % (size.group(1) if size else "?"))
    return True


def main() -> int:
    ran = H.run("hclimp", [SOURCE, TEST])
    if ran is None:
        return 0
    cc, env = ran
    src = SOURCE.read_text()
    bad = 0
    for name, what, old, new in CONTROLS:
        assert src.count(old) == 1, "mutation point moved - update control " + name
        mutant = Path(tempfile.gettempdir()) / ("hclimp_mutant_%s.c" % name)
        mutant.write_text(src.replace(old, new))
        exe = H.TMP / ("hc_hclimp_mutant_%s.exe" % name)
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
