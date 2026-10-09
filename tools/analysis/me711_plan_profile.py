#!/usr/bin/env python3
r"""
me711_plan_profile.py - attribute every instruction of the WORST tooth to the
function that executed it.

    py tools\analysis\me711_plan_profile.py                 # 6 cylinders @ 12000 rpm
    py tools\analysis\me711_plan_profile.py 4 7500
    py tools\analysis\me711_plan_profile.py --callers walk_kind

WHY THIS EXISTS. me711_plan_cost_proof says the worst tooth costs N
instructions. It does not say WHERE, and every attempt to make N smaller
without knowing where has cost this project a reverted change:

  * "four cursor walks per tooth" - walk_kind() breaks out as soon as the next
    anchor is still ahead, so there is no scan to remove;
  * an O(1) early-out on the minimum staged epoch - which by definition cannot
    help the WORST tooth, the one that does the work;
  * caching the time->angle conversions - architecturally right, measured
    zero, reverted rather than spend near RAM for nothing.

Three changes, three measurements, three reverts. This tool is the measurement
those changes should have started from.

HOW IT ATTRIBUTES, and why the linker map is not enough. The map carries only
PUBLIC symbols, and every function that matters here - plan_tooth, walk_kind,
queue_event, stage_long_horizon - is `static`. So for the modules named in
PROFILE_MODULES this script re-runs C166 with the CODE option, parses the
`; FUNCTION <name> (BEGIN` / `(END` markers out of the assembly listing, and
rebases the module-relative offsets onto the section address the map gives.
Everything else is attributed from the map's PUBLIC labels, and anything that
falls in no known range is reported as an explicit `<unattributed>` bucket
rather than silently dropped - a profiler that loses instructions is a
profiler that invents a conclusion.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_image as PI              # noqa: E402
import me711_plan_cost_proof as COST
import me711_trigger_test as PT       # noqa: E402

TARGET_DIR = ROOT / "firmware/targets/me711"
BUILD_DIR = TARGET_DIR / "build"
import hcpaths as HCP                  # noqa: E402
C166 = Path("C:/Keil/C166/BIN/C166.EXE")

# module source -> the ?PR? section name the map gives it. Only modules whose
# STATIC functions are worth naming need to be here; everything else resolves
# from the map's PUBLIC labels.
PROFILE_MODULES = {
    "hcdeadline711.c": "?PR?HCDEADLINE711",
    "hcdeadline_plan711.c": "?PR?HCDEADLINE_PLAN711",
    "hcsched_dry.c": "?PR?HCSCHED_DRY",
    "hchal_me711.c": "?PR?HCHAL_ME711",
    "hctrig_me711.c": "?PR?HCTRIG_ME711",
}


def section_bases(map_path: Path) -> dict[str, int]:
    out = {}
    for m in re.finditer(
            r"^([0-9A-F]{6})H\s+([0-9A-F]{6})H\s+[0-9A-F]{6}H\s+CODE\s+"
            r".*?\s([A-Z][A-Z0-9_]*)\s+(\?\S+)\s*$",
            map_path.read_text(errors="replace"), re.M):
        out[m.group(4)] = (int(m.group(1), 16), int(m.group(2), 16))
    return out


def public_labels(map_path: Path) -> list[tuple[int, str]]:
    out = []
    for m in re.finditer(
            r"^\s+([0-9A-F]{6})H\s+PUBLIC\s+LABEL\s+\S+\s+\S+\s+(\S+)\s*$",
            map_path.read_text(errors="replace"), re.M):
        out.append((int(m.group(1), 16), m.group(2)))
    return out


def code_listing(src: str) -> Path:
    """Re-compile one module with CODE so the statics get addresses."""
    lst = BUILD_DIR / ("_prof_" + Path(src).stem + ".lst")
    obj = BUILD_DIR / ("_prof_" + Path(src).stem + ".obj")
    path = HCP.find(src)
    cmd = [str(C166), str(path), "MOD167", "MEDIUM" if src == "hcdeadline_plan711.c" else "SMALL", "CODE",
           f"OBJECT({obj})", f"PRINT({lst})",
           "INCDIR(%s)" % ";".join(map(str, HCP.include_dirs("me711")))]
    p = subprocess.run(cmd, cwd=TARGET_DIR, capture_output=True, text=True)
    if "0 ERROR(S)" not in (p.stdout + p.stderr):
        raise SystemExit(f"CODE listing failed for {src}:\n{p.stdout}{p.stderr}")
    return lst


def parse_functions(lst: Path, base: int) -> list[tuple[int, int, str]]:
    """(start, end, name) absolute ranges from the FUNCTION markers."""
    out = []
    cur = None
    last = None
    for line in lst.read_text(errors="replace").splitlines():
        m = re.match(r"\s*; FUNCTION (\S+) \(BEGIN", line)
        if m:
            cur, last = m.group(1), None
            continue
        m = re.match(r"\s*; FUNCTION (\S+) \(END", line)
        if m and cur:
            if last is not None:
                out.append((cur_start + base, last + base, cur))
            cur = None
            continue
        m = re.match(r"^([0-9A-F]{4})\s+[0-9A-F]{2}", line)
        if m and cur:
            off = int(m.group(1), 16)
            if last is None:
                cur_start = off
            last = off
    return out


def build_symbols(map_path: Path):
    secs = section_bases(map_path)
    ranges: list[tuple[int, int, str]] = []
    for src, sec in PROFILE_MODULES.items():
        if sec not in secs:
            continue
        base = secs[sec][0]
        ranges += parse_functions(code_listing(src), base)
    # PUBLIC labels fill in everything else; a label is a start, and it runs
    # until the next label or the end of its section.
    pubs = sorted(public_labels(map_path))
    covered = sorted(ranges)
    for i, (addr, name) in enumerate(pubs):
        end = pubs[i + 1][0] - 1 if i + 1 < len(pubs) else addr
        if any(s <= addr <= e for s, e, _ in covered):
            continue
        ranges.append((addr, end, name))
    # and the module itself, as the coarsest fallback
    for sec, (lo, hi) in secs.items():
        ranges.append((lo, hi, sec + " (module)"))
    return sorted(ranges, key=lambda r: (r[0], r[1] - r[0]))


def attribute(ranges, pc: int) -> str:
    best = None
    for s, e, name in ranges:
        if s <= pc <= e:
            if best is None or (e - s) < (best[1] - best[0]):
                best = (s, e, name)
    return best[2] if best else "<unattributed>"


def worst_tooth_trace(cylinders: int, rpm: int, teeth: int = 60,
                      skip: int = 0):
    """Same workload as me711_plan_cost_proof.measure(), but recording the PC
    of every instruction of the single worst hc_drysched_service().

    `skip` excludes the first `skip` teeth from the SELECTION - they are still
    executed, so the state the traced tooth starts from is unchanged. Tooth #1
    is the one after seed_cursors() and it is the most expensive of the
    revolution by a wide margin; --steady excludes it so the profile describes
    a tooth the engine spends its life on rather than the one it meets once per
    sync acquisition. Both numbers are real and they are different engineering
    quantities - the project rules."""
    dt = round(1_250_000 / rpm)
    c = COST.planning_fixture(cylinders, teeth)
    step = 3600 // teeth
    c.set_t1(1000)
    c.call("hc_drysched_tooth", 0, 1000, dt)
    c.call("hc_drysched_service", 1000, 3)

    worst, worst_k, stamp = 0, 0, 1000
    marks = []
    for k in range(1, teeth):
        stamp = (stamp + dt) & 0xFFFF
        c.set_t1(stamp)
        c.call("hc_drysched_tooth", (k * step) % 7200, stamp, dt)
        before = c.c.steps
        c.call("hc_drysched_service", stamp, 3)
        used = c.c.steps - before
        marks.append((k, stamp, used))
        if used > worst and k > skip:
            worst, worst_k = used, k

    # Replay from scratch and trace the tooth we now know is the worst.
    c2 = COST.planning_fixture(cylinders, teeth)
    c2.set_t1(1000)
    c2.call("hc_drysched_tooth", 0, 1000, dt)
    c2.call("hc_drysched_service", 1000, 3)
    stamp = 1000
    trace = []
    for k in range(1, teeth):
        stamp = (stamp + dt) & 0xFFFF
        c2.set_t1(stamp)
        c2.call("hc_drysched_tooth", (k * step) % 7200, stamp, dt)
        if k == worst_k:
            trace = trace_call(c2, "hc_drysched_service", stamp, 3)
        else:
            c2.call("hc_drysched_service", stamp, 3)
    return worst, worst_k, trace, marks


def trace_call(c, fn, *args):
    """me711_trigger_test.Call.call(), single-stepped, returning the PC of
    every instruction executed.

    THE FRAME SET-UP BELOW IS COPIED FROM Call.call() AND MUST STAY THAT WAY.
    The first version of this dropped the two words it pushes - the return
    segment and the 0xFFFE sentinel the loop watches for - so the callee
    returned into whatever was on the stack and `while True` never terminated.
    The bounded loop is the second half of that lesson: a profiler that hangs
    looks exactly like a profiler measuring something expensive."""
    a = PT.sym(fn)
    c.m.w16(c.c.cp(), c.stack_top)
    c.m.sfr[0xFE14], c.m.sfr[0xFE16] = 0xF200, 0xFE00
    sp = 0xF700
    for w in (a >> 16, 0xFFFE):
        sp = (sp - 2) & 0xFFFF
        c.m.w16(sp, w)
    c.m.sfr[0xFE12] = sp
    for i, v in enumerate(args):
        c.c.sr(8 + i, v & 0xFFFF)
    c.c.csp, c.c.ip = a >> 16, a & 0xFFFF
    saved_psw=c.m.r16(0xff10)
    c.m.w16(0xff10,saved_psw&~0x800)
    pcs = []
    for _ in range(80000):
        if c.c.ip == 0xFFFE:
            c.m.w16(0xff10,saved_psw)
            return pcs
        pcs.append((c.c.csp << 16) | c.c.ip)
        c.c.step()
    raise SystemExit(f"{fn} did not return inside 80000 steps while tracing")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cylinders", nargs="?", type=int, default=6)
    ap.add_argument("rpm", nargs="?", type=int, default=12000)
    ap.add_argument("--teeth", type=int, default=60)
    ap.add_argument("--steady", action="store_true",
                    help="ignore tooth #1, the seed_cursors() transient, when "
                         "choosing which tooth to trace")
    ap.add_argument("--top", type=int, default=0,
                    help="also print the N most expensive teeth and their "
                         "crank angles")
    args = ap.parse_args()

    map_path = ROOT / "bins/hanicore" / (PI.STEM + ".M66")
    if not map_path.exists():
        map_path = BUILD_DIR / "hani_me711.M66"
    ranges = build_symbols(map_path)

    worst, worst_k, trace, marks = worst_tooth_trace(
        args.cylinders, args.rpm, args.teeth, 1 if args.steady else 0)

    print("=== the worst tooth, instruction by instruction ===\n")
    print(f"  image      {PI.STEM}")
    print(f"  scenario   {args.cylinders} cylinders, {args.rpm} rpm, "
          f"{args.teeth} teeth")
    step = 3600 // args.teeth
    print(f"  worst      tooth #{worst_k} at "
          f"{(worst_k * step) % 7200 / 10.0:.1f} deg, {worst} instructions "
          f"({len(trace)} traced)"
          + ("   [steady state: tooth #1 excluded]" if args.steady else "")
          + "\n")
    if args.top:
        print("  the most expensive teeth of the revolution:")
        for k, _stamp, used in sorted(marks, key=lambda r: -r[2])[:args.top]:
            print(f"    tooth #{k:3d}  {(k * step) % 7200 / 10.0:7.1f} deg  "
                  f"{used:5d} instructions")
        print()

    counts: dict[str, int] = {}
    entries: dict[str, int] = {}
    prev = None
    memo: dict[int, str] = {}
    for pc in trace:
        name = memo.get(pc)
        if name is None:
            name = memo[pc] = attribute(ranges, pc)
        counts[name] = counts.get(name, 0) + 1
        if name != prev:
            entries[name] = entries.get(name, 0) + 1
        prev = name

    print(f"  {'function':42s} {'instr':>7s} {'%':>6s} {'entries':>8s}")
    total = len(trace) or 1
    for name, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {name:42s} {n:7d} {n * 100.0 / total:5.1f}% "
              f"{entries[name]:8d}")
    print(f"  {'-' * 42} {'-' * 7}")
    print(f"  {'TOTAL':42s} {total:7d}")
    if "<unattributed>" in counts:
        print("\n  NOTE: some instructions fell in no known range. The "
              "profile is incomplete, not merely coarse.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
