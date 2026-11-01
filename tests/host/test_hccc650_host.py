"""Compile and run the CC650 core (hccc650.c, ME7.5 DC) host test through
host_c_test.py, plus mutation controls: each mutant must FAIL the test.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import host_c_test as H


SOURCE = H.HCP.find("hccc650.c")
TEST = H.HOST_TESTS / "test_hccc650.c"

MUTANTS = {
    # MIL polarity inverted (the lamp would light when it should not)
    "mil_active_high": ("0u, 0u, 0u, 0u, 0u, 1u, 1u, 1u, 0u, 1u, 1u",
                        "0u, 0u, 0u, 1u, 0u, 1u, 1u, 1u, 0u, 1u, 1u"),
    # shutdown in the wrong order: mode off before run-on off
    "shutdown_order": ("*reg = 0x44u; *val = 0x00u;     /* run-on off first             */",
                       "*reg = 0x02u; *val = 0x00u;"),
    # the mode byte written before the configuration
    "boot_order": ("{ 0x02u, 0x00u }, { 0x26u, 0x4Au }",
                   "{ 0x02u, 0x20u }, { 0x26u, 0x4Au }"),
    # no periodic refresh: a lost bus write would never heal
    "no_refresh": ("        i = c->cur;\n        c->cur = (unsigned char)((c->cur + 1u) % HCCC650_N_SH);",
                   "        i = 0u;"),
}


def mutant_fails(cc, env, name, old, new) -> bool:
    mutant = Path(tempfile.gettempdir()) / ("hccc650_mutant_%s.c" % name)
    src = SOURCE.read_text()
    assert src.count(old) == 1, "mutation point moved - update the control: %s" % name
    mutant.write_text(src.replace(old, new))
    exe = H.TMP / ("hc_hccc650_mutant_%s.exe" % name)
    H.build(cc, env, [mutant, TEST], H.SHARED, exe, flags=("-w",))
    r = subprocess.run([str(exe)], env=env, capture_output=True, text=True)
    return r.returncode != 0


def main() -> int:
    ran = H.run("hccc650", [SOURCE, TEST])
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
