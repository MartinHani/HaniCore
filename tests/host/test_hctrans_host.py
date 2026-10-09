"""Compile and run the transient-fuel core (hctrans.c) host test against a
floating-point wall-film plant, its negative controls, and a Keil check that
the far module calls no ?C_ runtime helper.
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


SOURCE = H.HCP.find("hctrans.c")
TEST = H.HOST_TESTS / "test_hctrans.c"
KEIL = Path(r"C:\Keil\C166\BIN\C166.EXE")
TARGET = H.ROOT / "firmware" / "targets" / "me711"

CONTROLS = [
    ("no_film_share", "the injector ignores what the film gives back",
     "        unsigned long af = (unsigned long)s->alpha * s->film;",
     "        unsigned long af = 0uL;"),
    ("no_wall_loss", "the injector ignores what the wall takes",
     "        unsigned int den = (unsigned int)(1000u - x);",
     "        unsigned int den = 1000u;"),
    ("film_never_dries", "the film does not evaporate",
     "    unsigned int ev = DIV32U((unsigned long)s->alpha * s->film, 1000u);",
     "    unsigned int ev = 0u;"),
    ("as_no_decay", "the after-start never decays",
     "                              * (unsigned int)(in->as_decay_ms - s->as_ms),",
     "                              * (unsigned int)(in->as_decay_ms),"),
    ("cut_injects", "a fuel cut still injects",
     "    if (in->cut) {\n        out = 0u;",
     "    if (0) {\n        out = 0u;"),
]


def keil_check() -> bool:
    if not KEIL.exists():
        print("SKIP: Keil C166 not found - helper check not run")
        return True
    out = Path(tempfile.mkdtemp())
    r = subprocess.run([str(KEIL), str(SOURCE), "MOD167", "MEDIUM",
                        "RENAMECLASS(NDATA0=XNDATA0)",
                        "OBJECT(%s)" % (out / "hctrans.obj"),
                        "PRINT(%s)" % (out / "hctrans.lst"), "INCDIR(%s)" % ";".join(map(str, H.HCP.include_dirs("me711"))), "CODE"],
                       cwd=str(TARGET), capture_output=True, text=True)
    lst = (out / "hctrans.lst").read_text(errors="replace") \
        if (out / "hctrans.lst").exists() else ""
    if "0 WARNING(S),  0 ERROR(S)" not in (r.stdout + lst):
        print("FAIL: Keil C166 did not compile hctrans.c cleanly")
        print(r.stdout[-1500:])
        return False
    helpers = sorted(set(re.findall(r"CALLS\s+SEG \((\?C_\w+)\)", lst)))
    if helpers:
        print("FAIL: hctrans.c (far) calls Keil runtime helpers: %s"
              % ", ".join(helpers))
        return False
    size = re.search(r"CODE SIZE\s+=\s+(\d+)", lst)
    print("PASS: Keil C166 MEDIUM, 0 warnings, no ?C_ helper call (%s bytes)"
          % (size.group(1) if size else "?"))
    return True


def main() -> int:
    ran = H.run("hctrans", [SOURCE, TEST])
    if ran is None:
        return 0
    cc, env = ran
    src = SOURCE.read_text()
    bad = 0
    for name, what, old, new in CONTROLS:
        assert src.count(old) == 1, "mutation point moved - update control " + name
        mutant = Path(tempfile.gettempdir()) / ("hctrans_mutant_%s.c" % name)
        mutant.write_text(src.replace(old, new))
        exe = H.TMP / ("hc_hctrans_mutant_%s.exe" % name)
        H.build(cc, env, [mutant, TEST], H.SHARED, exe, flags=("-w",))
        r = subprocess.run([str(exe)], env=env, capture_output=True, text=True)
        if r.returncode == 0:
            print("FAIL: control %s - %s - passed the tests" % (name, what))
            bad += 1
        else:
            first = [ln for ln in (r.stdout + r.stderr).splitlines()
                     if "Assertion" in ln][:1]
            print("PASS: control %s - %s - fails (%s)"
                  % (name, what, first[0].strip() if first else "exit %d" % r.returncode))
    if not keil_check():
        bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
