"""Compile and run the CJ110 wideband core (hccj110.c, ME7.5 DC) host test
through host_c_test.py, plus mutation controls: each mutant must FAIL the
test, or the test cannot see that defect.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import host_c_test as H


SOURCE = H.HCP.find("hccj110.c")
TEST = H.HOST_TESTS / "test_hccj110.c"

MUTANTS = {
    # calibration ignored: the stock zero instead of the measured one
    "no_offset": ("corr = (unsigned int)(ua + HCCJ110_UA0_NOM - c->ua0);",
                  "corr = ua;"),
    # lambda published while the sensor is cold
    "cold_valid": ("if (!hot) {", "if (0) {"),
    # the calibration window not enforced
    "no_window": ("if (c->ua0 < HCCJ110_UA0_MIN || c->ua0 > HCCJ110_UA0_MAX) {",
                  "if (0) {"),
    # chip diagnosis latched at once instead of after TVCJLSU
    "diag_at_once": ("if (c->t_ms >= HCCJ110_DIAG_MS) fault(c, HCCJ110_F_CHIP);",
                     "fault(c, HCCJ110_F_CHIP);"),
}


def mutant_fails(cc, env, name, old, new) -> bool:
    mutant = Path(tempfile.gettempdir()) / ("hccj110_mutant_%s.c" % name)
    src = SOURCE.read_text()
    assert src.count(old) == 1, "mutation point moved - update the control"
    mutant.write_text(src.replace(old, new))
    exe = H.TMP / ("hc_hccj110_mutant_%s.exe" % name)
    H.build(cc, env, [mutant, TEST], H.SHARED, exe, flags=("-w",))
    r = subprocess.run([str(exe)], env=env, capture_output=True, text=True)
    return r.returncode != 0


def main() -> int:
    ran = H.run("hccj110", [SOURCE, TEST])
    if ran is None:
        return 0
    cc, env = ran
    bad = [n for n, (o, w) in MUTANTS.items() if not mutant_fails(cc, env, n, o, w)]
    if bad:
        print("FAIL: mutants not detected: %s" % ", ".join(bad))
        return 1
    print("PASS: %d mutation controls fail as they must" % len(MUTANTS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
