"""Compile and run the cam pattern core (hccam.c) host test, plus negative
controls, through host_c_test.py.

Each control removes ONE of the core's safeguards; the same test (its
wrong-half fuzz, or a deterministic case) must then fail - otherwise the
safeguard is not what the tests depend on.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import host_c_test as H


SOURCE = H.HCP.find("hccam.c")
TEST = H.HOST_TESTS / "test_hccam.c"

CONTROLS = [
    ("confirm", "the half moves on ONE tooth (no confirmation)",
     "        if (c->other_run >= (c->est ? (unsigned char)(c->n + 1u > c->cfg.confirm\n"
     "                                                      ? c->n + 1u : c->cfg.confirm)\n"
     "                                    : c->cfg.confirm)) {",
     "        if (c->other_run >= 1u) {"),
    ("glitch_pref", "no glitch preference in an established half",
     "            || (c->est && j.n_same == 0u))) {",
     "            || (0 && j.n_same == 0u))) {"),
    ("noise_swap", "the NEWER of two too-close edges is always the noise",
     "            && c->cls != HCCAM_C_ALIVE) {",
     "            && c->cls != HCCAM_C_ALIVE && 0) {"),
    ("missing", "no missing-edge recovery",
     "    if (c->est && c->resolves && j.n_same == 0u && c->n > 1u",
     "    if (0 && c->est && c->resolves && j.n_same == 0u && c->n > 1u"),
]


def main() -> int:
    ran = H.run("hccam", [SOURCE, TEST])
    if ran is None:
        return 0
    cc, env = ran
    src = SOURCE.read_text()
    bad = 0
    for name, what, old, new in CONTROLS:
        assert src.count(old) == 1, "mutation point moved - update control " + name
        mutant = Path(tempfile.gettempdir()) / ("hccam_mutant_%s.c" % name)
        mutant.write_text(src.replace(old, new))
        exe = H.TMP / ("hc_hccam_mutant_%s.exe" % name)
        H.build(cc, env, [mutant, TEST], H.SHARED, exe, flags=("-w",))
        r = subprocess.run([str(exe)], env=env, capture_output=True, text=True)
        if r.returncode == 0:
            print("FAIL: control %s - %s - passed the tests" % (name, what))
            bad += 1
        else:
            first = [ln for ln in (r.stdout + r.stderr).splitlines()
                     if "WRONG CLAIM" in ln or "Assertion" in ln][:1]
            print("PASS: control %s - %s - fails (%s)"
                  % (name, what, first[0].strip() if first else "exit %d" % r.returncode))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
