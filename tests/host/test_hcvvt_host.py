"""Compile and run the VVT core (hcvvt.c) host test, its negative
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


SOURCE = H.HCP.find("hcvvt.c")
TEST = H.HOST_TESTS / "test_hcvvt.c"
KEIL = Path(r"C:\Keil\C166\BIN\C166.EXE")
TARGET = H.ROOT / "firmware" / "targets" / "me711"

CONTROLS = [
    ("plain_windup", "the integrator integrates into saturation",
     "    if (!((u >= (long)hi && di > 0L) || (u <= (long)lo && di < 0L))) {",
     "    if (1) {"),
    ("keep_on_nopos", "no position keeps the integrator (no reset)",
     "    if (!in->pos_ok) {                              /* rusEFI: unexpected -> 0 */\n"
     "        pid_reset(v);",
     "    if (!in->pos_ok) {"),
    ("ignore_invert", "the invert setting is ignored",
     "        if (c->invert) ev = -ev;",
     "        ;"),
    ("d_on_error", "D acts on the error",
     "        long dm = (long)in->pos_x10 - (long)v->last_pos;",
     "        long dm = ((long)in->pos_x10 - (long)in->target_x10) - ((long)v->last_pos);"),
    ("no_delay", "no activation delay",
     "        || v->run_ms < c->delay_ms) {",
     "        ) {"),
]


def keil_check() -> bool:
    if not KEIL.exists():
        print("SKIP: Keil C166 not found - helper check not run")
        return True
    out = Path(tempfile.mkdtemp())
    r = subprocess.run([str(KEIL), str(SOURCE), "MOD167", "MEDIUM",
                        "RENAMECLASS(NDATA0=XNDATA0)",
                        "OBJECT(%s)" % (out / "hcvvt.obj"),
                        "PRINT(%s)" % (out / "hcvvt.lst"), "INCDIR(%s)" % ";".join(map(str, H.HCP.include_dirs("me711"))), "CODE"],
                       cwd=str(TARGET), capture_output=True, text=True)
    lst = (out / "hcvvt.lst").read_text(errors="replace") if (out / "hcvvt.lst").exists() else ""
    if "0 WARNING(S),  0 ERROR(S)" not in (r.stdout + lst):
        print("FAIL: Keil C166 did not compile hcvvt.c cleanly")
        return False
    helpers = sorted(set(re.findall(r"CALLS\s+SEG \((\?C_\w+)\)", lst)))
    if helpers:
        print("FAIL: hcvvt.c (far) calls Keil runtime helpers: %s" % ", ".join(helpers))
        return False
    size = re.search(r"CODE SIZE\s+=\s+(\d+)", lst)
    print("PASS: Keil C166 MEDIUM, 0 warnings, no ?C_ helper call (%s bytes)"
          % (size.group(1) if size else "?"))
    return True


def main() -> int:
    ran = H.run("hcvvt", [SOURCE, TEST])
    if ran is None:
        return 0
    cc, env = ran
    src = SOURCE.read_text()
    bad = 0
    for name, what, old, new in CONTROLS:
        assert src.count(old) == 1, "mutation point moved - update control " + name
        mutant = Path(tempfile.gettempdir()) / ("hcvvt_mutant_%s.c" % name)
        mutant.write_text(src.replace(old, new))
        exe = H.TMP / ("hc_hcvvt_mutant_%s.exe" % name)
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
