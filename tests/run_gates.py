#!/usr/bin/env python3
r"""
run_gates.py - run the HaniCore gates, by tier, kind or subsystem.

    py tests\run_gates.py fast              minutes: host, unit, simulator + quick image gates
    py tests\run_gates.py tier1             ~10 min: regenerate the .ini/dash, then the
                                            TunerStudio-vs-image milestone gates
    py tests\run_gates.py full              hours: every offline gate (never 'physical')
    py tests\run_gates.py --tag dbw         every gate tagged dbw (any tier)
    py tests\run_gates.py --kind firmware --tag trigger
    py tests\run_gates.py -k nvm            gates whose name contains 'nvm'
    py tests\run_gates.py --list [...]      show the selection, run nothing
    py tests\run_gates.py --audit [...]     what evidence each selected gate rests on

The gate list is the directory tree under tests/ (tests/catalog.py). Physical
qualification scripts (tests/physical/) are listed but never run from here:
each needs hardware and its own authorisation flag.

The runner does not build. Build first if the firmware changed:
    py tools\build\build_hanicore_me711.py

Exit code = number of failing gates, capped at 125. A TIMEOUT under CPU
contention is not a firmware verdict - rerun that gate alone.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: E402,F401
import catalog as CAT  # noqa: E402


# ------------------------------------------------- level conditions (SKIP_IF)
def conditions() -> dict:
    """Questions about the TREE AS IT IS NOW. A gate whose subject is compiled
    out, or that pairs with a frozen image that is no longer the one under
    test, skips - it is not deleted and it does not go red."""
    import me711_image as IMG
    tgt = (hcpaths.ME711 / "hctarget.h").read_text(errors="replace")
    main_c = hcpaths.find("hcmain_me711.c").read_text(errors="replace")
    return {
        # hcsched_dry.c compiles its angle planner out without TGT_ENGINE_RUNTIME
        "planner_absent": re.search(r"^#define\s+TGT_ENGINE_RUNTIME\s+1", tgt, re.M) is None,
        # the planner is its own interrupt level (CC26), invoked when a walk is
        # due rather than once per tooth: a per-call tooth budget no longer
        # describes it - me711_runtime_stress_proof measures its real share
        "planner_on_own_level": re.search(r"^#define\s+TGT_ILVL_PLAN\s", tgt, re.M) is not None,
        # the image under test carries HaniCore's own boot region (the default
        # build): no OEM boot block executes, so a gate that measures what the
        # OEM boot block reads has nothing to measure (me711_owned_boot_proof
        # covers the owned region's header and sums)
        "owned_boot": (IMG.MANIFEST.exists()
                       and IMG.metadata().get("boot_region") == "hanicore_owned"),
        # hc_dbw.c stubs to zeros without TGT_DBW_CONTROLLER
        "dbw_absent": re.search(r"^#define\s+TGT_DBW_CONTROLLER\s+1", tgt, re.M) is None,
        # burn forensics / ASIC dump are instrumentation behind TGT_BURN_DIAGNOSTICS
        "diag_absent": re.search(r"^#define\s+TGT_BURN_DIAGNOSTICS\s+1", tgt, re.M) is None,
        # the build refuses to rebuild a stem that is frozen under release/
        "image_frozen": any((ROOT / "release").glob("*/%s.bin" % IMG.STEM)),
        # the unsolicited heartbeat was retired in V22: hb_service() is never called
        "heartbeat_retired": re.search(r"^\s*hb_service\(\s*\)\s*;", main_c, re.M) is None,
        # pairing proofs against the frozen V37 image in a V37 ECU
        "not_v37": IMG.STEM != "HaniCore_ME711_v37_ram_probe",
        # K-line receive is PEC6 (hcserial711.c): the CC7 drain tick is compiled out
        "rx_pec": re.search(r"^#define\s+TGT_RX_PEC\s+1", tgt, re.M) is not None,
        # gates whose subject IS the local material: the reference corpora
        # (rusEFI, A2L), this ECU's own OEM reads, the frozen release files.
        # A public clone has none of them.
        "local_corpus_absent": not ((ROOT / "reference").is_dir()
                                    and (hcpaths.OEM_READ).exists()
                                    and (ROOT / "release").is_dir()),
    }


REASON = {
    "planner_absent": "the angle planner is compiled out (TGT_ENGINE_RUNTIME)",
    "planner_on_own_level": "the planner runs on its own interrupt level when due, not per tooth; "
                            "its budget is me711_runtime_stress_proof",
    "owned_boot": "the image boots from HaniCore's own boot region; no OEM boot block "
                  "runs (me711_owned_boot_proof covers the region)",
    "dbw_absent": "the DBW controller is compiled out (TGT_DBW_CONTROLLER)",
    "diag_absent": "burn forensics / ASIC dump compiled out (TGT_BURN_DIAGNOSTICS)",
    "image_frozen": "the image under test is frozen under release/ - bump the stem",
    "heartbeat_retired": "the heartbeat is retired (main loop never calls hb_service)",
    "not_v37": "pairs with the frozen V37 image; the image under test is newer",
    "rx_pec": "K-line receive is PEC6 (TGT_RX_PEC); the CC7 drain tick is compiled out",
    "local_corpus_absent": "needs the local reference corpora / OEM reads / frozen releases",
}


def select(args) -> list:
    gates = CAT.gates()
    if args.tier == "tier1":
        order = {n: i for i, n in enumerate(CAT.TIER1)}
        return sorted([g for g in gates if g.tier1], key=lambda g: order[g.name])
    if args.tier == "fast":
        gates = [g for g in gates if g.fast and g.kind != "physical"]
    elif args.tier == "full":
        gates = [g for g in gates if g.kind != "physical"]
    elif not (args.tag or args.kind or args.k):
        gates = [g for g in gates if g.fast and g.kind != "physical"]
    if args.kind:
        gates = [g for g in gates if g.kind in args.kind]
    if args.tag:
        gates = [g for g in gates if set(args.tag) & set(g.tags)]
    if args.k:
        gates = [g for g in gates if args.k in g.name]
    return gates


def run_one(cmd, timeout):
    try:
        r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 99, "TIMEOUT after %ds" % timeout


def tier1_prelude() -> list:
    """The old Tier 1 regenerated the .ini and the dashboard first, so the gates
    judge what the generators produce NOW, and ran the semantics self-check."""
    steps = [("regenerate the .ini", [sys.executable, str(hcpaths.script("gen_ts_ini_me711"))]),
             ("ts_semantics_me711", [sys.executable, str(hcpaths.script("ts_semantics_me711"))]),
             ("regenerate the dashboard", [sys.executable, str(hcpaths.script("gen_hanicore_dash"))])]
    failed = []
    for what, cmd in steps:
        t0 = time.time()
        rc, out = run_one(cmd, 600)
        print("  [%s] %-46s %6.1fs  %s" % ("PASS" if rc == 0 else "FAIL", what, time.time() - t0,
                                          (out.strip().splitlines() or [""])[-1][:60]))
        if rc:
            failed.append((what, out))
    return failed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tier", nargs="?", choices=("fast", "tier1", "full"))
    ap.add_argument("--tag", action="append", default=[])
    ap.add_argument("--kind", action="append", default=[], choices=CAT.KINDS)
    ap.add_argument("-k", default="", help="substring of the gate name")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--timeout", type=int, default=1800)
    args = ap.parse_args()
    gates = select(args)

    if args.list:
        for g in gates:
            print("  %-12s %-46s %-4s %s" % (g.kind, g.name, "fast" if g.fast else "", g.rel))
        print("  %d gate(s)" % len(gates))
        return 0
    if args.audit:
        import audit_gates
        return audit_gates.audit(gates)

    physical = [g for g in gates if g.kind == "physical"]
    gates = [g for g in gates if g.kind != "physical"]
    cond = conditions()
    print("=== HaniCore gates: %s - %d gate(s) ===\n"
          % (args.tier or "selection", len(gates)))
    failed, skipped = [], []
    t_all = time.time()
    if args.tier == "tier1":
        failed += tier1_prelude()
    for g in gates:
        if g.skip_if and cond.get(g.skip_if):
            print("  [SKIP] %-46s   -    %s" % (g.name, REASON[g.skip_if]))
            skipped.append(g.name)
            continue
        cmd = ([sys.executable, "-m", "pytest", "-q", g.rel] if g.pytest
               else [sys.executable, str(g.path)])
        t0 = time.time()
        rc, out = run_one(cmd, max(args.timeout, g.timeout))
        lines = [ln.rstrip() for ln in out.splitlines() if ln.strip()]
        print("  [%s] %-46s %6.1fs  %s" % ("PASS" if rc == 0 else "FAIL", g.name,
                                          time.time() - t0, (lines[-1] if lines else "")[:64]))
        sys.stdout.flush()
        if rc:
            failed.append((g.name, out))
    for g in physical:
        print("  [----] %-46s   -    physical: run by hand (%s)" % (g.name, g.rel))

    ran = len(gates) - len(skipped)
    print("\n  %d/%d pass in %.0fs (%d skipped)" % (ran - sum(1 for f in failed if f[0] in {g.name for g in gates}),
                                                     ran, time.time() - t_all, len(skipped)))
    for name, out in failed:
        print("\n--- %s ---" % name)
        for ln in out.splitlines():
            if "FAIL" in ln or "Error" in ln or "Traceback" in ln:
                print("    " + ln.rstrip()[:160])
    return min(125, len(failed))


if __name__ == "__main__":
    raise SystemExit(main())
