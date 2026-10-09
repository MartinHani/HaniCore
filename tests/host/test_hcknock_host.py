"""Compile and run the knock-control core (hcknock.c) host test, plus
negative controls, through host_c_test.py.

Each control removes ONE property of the core; the same test must then
fail - otherwise the tests do not depend on that property.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import host_c_test as H


SOURCE = H.HCP.find("hcknock.c")
TEST = H.HOST_TESTS / "test_hcknock.c"

CONTROLS = [
    ("learn_on_knock", "a knocking ignition also raises the reference",
     "        k->quiet_ms[cyl] = 0u;\n        return 1u;",
     "        k->quiet_ms[cyl] = 0u;\n        learn(k, cyl, ikr, tp);\n        return 1u;"),
    ("truncating_filter", "the low pass drops its remainder",
     "    k->rem[cyl] = (signed char)(acc - step * (int)tp);",
     "    k->rem[cyl] = 0;"),
    ("no_settle", "detection from the first ignition",
     "    if (k->seen[cyl] < cfg->learn) {",
     "    if (0) {"),
    ("no_dyn_factor", "no threshold factor in dynamics",
     "    if (in->dyn) {                                    /* 255 * 32 = 8160      */",
     "    if (0) {"),
    ("global_retard", "a knock retards every cylinder (rusEFI's global retard)",
     "        k->quiet_ms[cyl] = 0u;\n        return 1u;",
     "        { unsigned char j; for (j = 0u; j < cfg->cyls; j++) k->ret_q[j] = k->ret_q[cyl]; }\n"
     "        k->quiet_ms[cyl] = 0u;\n        return 1u;"),
    ("fault_all", "a sensor fault retards every cylinder",
     "    if ((k->fault >> cfg->sensor[cyl]) & 1u) {",
     "    if (k->fault) {"),
    ("stale_stop", "reset leaves the at-stop latch (found while writing the tests)",
     "    k->stop = 0u;\n",
     ""),
    ("kef_product", "the threshold product in one 16-bit multiply",
     "    return r4 * (unsigned int)(kef16 >> 4) + ((r4 * (unsigned int)(kef16 & 15u)) >> 4);",
     "    return (unsigned short)(r4 * kef16) >> 4;"),
]


def main() -> int:
    ran = H.run("hcknock", [SOURCE, TEST])
    if ran is None:
        return 0
    cc, env = ran
    src = SOURCE.read_text()
    bad = 0
    for name, what, old, new in CONTROLS:
        assert src.count(old) == 1, "mutation point moved - update control " + name
        mutant = Path(tempfile.gettempdir()) / ("hcknock_mutant_%s.c" % name)
        mutant.write_text(src.replace(old, new))
        exe = H.TMP / ("hc_hcknock_mutant_%s.exe" % name)
        H.build(cc, env, [mutant, TEST], H.SHARED, exe, flags=("-w",))
        r = subprocess.run([str(exe)], env=env, capture_output=True, text=True)
        if r.returncode == 0:
            print("FAIL: control %s - %s - passed the tests" % (name, what))
            bad += 1
        else:
            first = [ln for ln in (r.stdout + r.stderr).splitlines()
                     if "Assertion" in ln or "stalls" in ln][:1]
            print("PASS: control %s - %s - fails (%s)"
                  % (name, what, first[0].strip() if first else "exit %d" % r.returncode))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
