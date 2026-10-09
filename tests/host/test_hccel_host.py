"""Compile and run the check-engine lamp policy (hccel.c) host test, its
negative controls, and a Keil check (far, no ?C_ helper)."""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import host_c_test as H

SOURCE = H.HCP.find("hccel.c")
TEST = H.HOST_TESTS / "test_hccel.c"
KEIL = Path(r"C:\Keil\C166\BIN\C166.EXE")
TARGET = H.ROOT / "firmware" / "targets" / "me711"

CONTROLS = [
    ("no_gap", "the dark second is skipped when a MIL is present",
     "        if (el < c->end_ms) {",
     "        if (el < c->end_ms && !mil_req) {"),
    ("no_retest", "a key-off does not end the test cycle (no re-test)",
     "    if (!key_on) {\n        c->key = 0u;",
     "    if (!key_on) {\n        ;"),
    ("wrap_retest", "the uptime wrap re-arms the test",
     "        c->testing = 0u;                  /* done: never re-armed by a wrap */",
     "        ;"),
    ("off_by_one", "the test ends at 3.001 s",
     "        if (el < c->on_ms) {",
     "        if (el <= c->on_ms) {"),
    ("test_always", "the lamp test runs although it is disabled",
     "        c->testing = c->test_en;",
     "        c->testing = 1u;"),
]


def keil_check() -> bool:
    if not KEIL.exists():
        print("SKIP: Keil not found")
        return True
    out = Path(tempfile.mkdtemp())
    r = subprocess.run([str(KEIL), str(SOURCE), "MOD167", "MEDIUM",
                        "RENAMECLASS(NDATA0=XNDATA0)",
                        "OBJECT(%s)" % (out / "hccel.obj"),
                        "PRINT(%s)" % (out / "hccel.lst"), "INCDIR(%s)" % ";".join(map(str, H.HCP.include_dirs("me711"))), "CODE"],
                       cwd=str(TARGET), capture_output=True, text=True)
    lst = (out / "hccel.lst").read_text(errors="replace") \
        if (out / "hccel.lst").exists() else ""
    if "0 WARNING(S),  0 ERROR(S)" not in (r.stdout + lst):
        print("FAIL: Keil did not compile hccel.c cleanly")
        return False
    if re.findall(r"CALLS\s+SEG \((\?C_\w+)\)", lst):
        print("FAIL: hccel.c calls a Keil runtime helper")
        return False
    print("PASS: Keil C166 MEDIUM, 0 warnings, no ?C_ helper")
    return True


def main() -> int:
    ran = H.run("hccel", [SOURCE, TEST])
    if ran is None:
        return 0
    cc, env = ran
    src = SOURCE.read_text()
    bad = 0
    for name, what, old, new in CONTROLS:
        assert src.count(old) == 1, "mutation point moved: " + name
        mutant = Path(tempfile.gettempdir()) / ("hccel_mutant_%s.c" % name)
        mutant.write_text(src.replace(old, new))
        exe = H.TMP / ("hc_hccel_mutant_%s.exe" % name)
        H.build(cc, env, [mutant, TEST], H.SHARED, exe, flags=("-w",))
        r = subprocess.run([str(exe)], env=env, capture_output=True, text=True)
        if r.returncode == 0:
            print("FAIL: control %s - %s - passed" % (name, what))
            bad += 1
        else:
            print("PASS: control %s - %s - fails" % (name, what))
    if not keil_check():
        bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
