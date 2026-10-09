"""Compile and run the isolated wideband core (hcwb.c) host tests - one bank
(test_hcwb.c) and both banks through hcwb_pair_step (test_hcwb_dual.c) -
plus a negative control for each, through host_c_test.py.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import host_c_test as H


SOURCE = H.HCP.find("hcwb.c")
TEST = H.HOST_TESTS / "test_hcwb.c"
DUAL = H.HOST_TESTS / "test_hcwb_dual.c"
DYN = H.HOST_TESTS / "test_hcwb_dyn.c"     # V99: signal path + dynamics
WARM = H.HOST_TESTS / "test_hcwb_warmup.c" # V100: warm-up lifetime
LIFECYCLE = H.HOST_TESTS / "test_hcwb_lifecycle.c"
AUDIT = H.HOST_TESTS / "test_hcwb_v101_controls.c"
# hcwb_model.h is shared by both tests; each uses only part of it
DUAL_FLAGS = H.STRICT + ("-Wno-unused-function",)


def mutant_fails(cc, env, name, old, new, test) -> bool:
    mutant = Path(tempfile.gettempdir()) / ("hcwb_mutant_%s.c" % name)
    src = SOURCE.read_text()
    assert src.count(old) == 1, "mutation point moved - update the control"
    mutant.write_text(src.replace(old, new))
    mexe = H.TMP / ("hc_hcwb_mutant_%s.exe" % name)
    H.build(cc, env, [mutant, test], H.SHARED, mexe, flags=("-w",))
    r = subprocess.run([str(mexe)], env=env, capture_output=True, text=True)
    return r.returncode != 0


def main() -> int:
    ran = H.run("hcwb", [SOURCE, TEST])
    if ran is None:
        return 0
    cc, env = ran
    exe = H.TMP / "hc_hcwb_dual_host.exe"
    H.build(cc, env, [SOURCE, DUAL], H.SHARED, exe, flags=DUAL_FLAGS)
    subprocess.run([str(exe)], check=True, env=env)
    audit_exe = H.TMP / "hc_hcwb_v101_audit.exe"
    H.build(cc, env, [SOURCE, AUDIT], H.SHARED, audit_exe, flags=DUAL_FLAGS)
    for case in ("0", "1"):
        subprocess.run([str(audit_exe), case], check=True, env=env)
    if "--v100-source" in sys.argv:
        original = Path(sys.argv[sys.argv.index("--v100-source") + 1])
        # Copy to a directory without the old header: both implementations
        # receive exactly the same asynchronous model and metadata contract.
        control = H.TMP / "hcwb_v100_audit_control.c"
        control.write_bytes(original.read_bytes())
        H.build(cc, env, [control, AUDIT], H.SHARED, audit_exe, flags=("-w",))
        for case, name in (("0", "L1"), ("1", "N1")):
            result = subprocess.run([str(audit_exe), case], env=env,
                                    capture_output=True, text=True)
            print(result.stdout.strip())
            if result.returncode != 1 or name + " reproduced:" not in result.stdout:
                raise SystemExit("V100 control did not reproduce " + name)
        print("PASS: original task-start V100 reproduces L1 and N1")
    print("PASS: hcwb two-bank host tests")
    exe = H.TMP / "hc_hcwb_dyn_host.exe"
    H.build(cc, env, [SOURCE, DYN], H.SHARED, exe, flags=DUAL_FLAGS)
    subprocess.run([str(exe)], check=True, env=env)
    # V100: the warm-up LIFETIME and the open-cell / still-cold split
    exe = H.TMP / "hc_hcwb_warmup_host.exe"
    H.build(cc, env, [SOURCE, WARM], H.SHARED, exe, flags=DUAL_FLAGS)
    subprocess.run([str(exe)], check=True, env=env)
    exe = H.TMP / "hc_hcwb_lifecycle_host.exe"
    H.build(cc, env, [SOURCE, LIFECYCLE], H.SHARED, exe, flags=DUAL_FLAGS)
    subprocess.run([str(exe)], check=True, env=env)
    # NEGATIVE CONTROL (V100): the V96..V99 behaviour - an engine stop resets
    # the machine to WAIT and kills the heater. That defect is why lambda read
    # 0.000 in every row of the whole AWT session.
    if not mutant_fails(cc, env, "runreset",
                        "!in->heat_allow && w->permission == 0u",
                        "!in->heat_allow", WARM):
        print("FAIL: control - discarding the warm-up on a stop passed")
        return 1
    print("PASS: control - discarding the warm-up on an engine stop fails")
    # NEGATIVE CONTROL (V100): a core that cannot tell an open Nernst cell
    # from a merely cold one (V99: both reported NO_HEAT) must fail.
    if not mutant_fails(cc, env, "nocell",
                        "w->ur_live ? HCWB_F_NO_HEAT",
                        "1u ? HCWB_F_NO_HEAT", WARM):
        print("FAIL: control - conflating an open cell with a cold one passed")
        return 1
    print("PASS: control - conflating an open cell with a cold one fails")
    # NEGATIVE CONTROL 1: the V79..V95 behaviour - the pump never enabled
    # (the chip held without PA) - must fail the one-bank tests.
    if not mutant_fails(cc, env, "no_pa", "? HCWB_MODE_PUMP : HCWB_MODE_COLD",
                        "? HCWB_MODE_COLD : HCWB_MODE_COLD", TEST):
        print("FAIL: control - a core that never pumps passed the tests")
        return 1
    print("PASS: control - a core that never enables the pump fails")
    # NEGATIVE CONTROL 2: bank 2 reading bank 1's chip - the cross-wiring the
    # two-bank tests exist to catch - must fail them.
    if not mutant_fails(cc, env, "crosswire", "b_in.chip_ok = in->chip_ok[b];",
                        "b_in.chip_ok = in->chip_ok[0];", DUAL):
        print("FAIL: control - a cross-wired pair step passed the two-bank tests")
        return 1
    print("PASS: control - a pair step that gives bank 2 bank 1's chip fails")
    # NEGATIVE CONTROL 3 (V97): lambda published with the pump current out of
    # the amplifier swing - a saturated UA read as a mixture - must fail.
    if not mutant_fails(cc, env, "uaswing",
                        "&& in->ua >= UA_MIN_RAW && in->ua <= UA_MAX_RAW\n"
                        "        && in->ur",
                        "&& in->ur", DUAL):
        print("FAIL: control - lambda from a saturated pump current passed")
        return 1
    print("PASS: control - lambda from a saturated pump current fails")
    # NEGATIVE CONTROL 4 (V97): a reason that calls a withheld row VALID
    if not mutant_fails(cc, env, "why", "return HCWB_WHY_UA;         /*",
                        "return HCWB_WHY_VALID;      /*", DUAL):
        print("FAIL: control - a reason that hides the withheld row passed")
        return 1
    print("PASS: control - a reason that hides a withheld row fails")
    return 0


if __name__ == "__main__":
    sys.exit(main())
