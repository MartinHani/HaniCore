#!/usr/bin/env python3
r"""me711_stack_static.py - the worst-case stack depth of the LINKED image.

    py tools\analysis\me711_stack_static.py [--verbose] [--json]

Static, from the image and its map - no simulation, so it answers for every
path, not only for the ones a workload happened to take (the runtime audit's
256-byte stack overflowed under a load the old proof never ran).

For every function (each map LABEL in a code class, plus every CALL target,
plus every interrupt handler the vector table names) it sweeps the code up to
the next entry and accumulates:

  USER stack (R0)   SUB/ADD R0,#n, MOV/MOVB [-R0],Rx      locals, Keil spills
  SYSTEM stack (SP) PUSH, SCXT, PCALL, and the return address of every call
                    (CALLA/CALLR 2 bytes, CALLS 4)

and builds the call graph (CALLA, CALLR, CALLS, PCALL, and JMPA/JMPS that
leave the function - a tail call). Depth(f) = own frame + the deepest callee.
An indirect call (CALLI) or a cycle is reported: the bound would not hold.

Interrupts NEST BY LEVEL: one handler per distinct ILVL can be active on top
of the main loop (a level cannot interrupt itself, C167CR UM 5). So

  worst = depth(main) + sum over levels L of max(depth(handler at L)) + 6 B
          of PSW/CSP/IP per level on the system stack.

The linear sweep over-approximates (a push in a loop counts once; pushes on
two exclusive paths both count) - the safe direction for a bound.

The levels come from hctarget.h (TGT_ILVL_*) - the same defines the firmware
programs, so a priority change moves the bound. Catch-all stubs for traps the
firmware never enables are not counted; NMI and the hardware traps are.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import hcpaths  # noqa: F401,E402
import me711_image as PI  # noqa: E402
from c166_disasm import is4  # noqa: E402

TARGET = hcpaths.ROOT / "firmware/targets/me711/hctarget.h"
START = hcpaths.ROOT / "firmware/targets/me711/system/start_me711.a66"
VEC = 0x020000            # the second-level table HaniCore owns (file offset)


def stack_sizes(map_text=None):
    """(user, system) bytes: ?C_USERSTACK's length from the map, STKUN - STKOV
    from the startup code - what the image really has, never a typed copy."""
    if map_text is None:
        map_text = PI.MAP.read_text(errors="replace")
    m = re.search(r"^[0-9A-F]{6}H\s+[0-9A-F]{6}H\s+([0-9A-F]{6})H\s+DATA.*\?C_USERSTACK\s*$", map_text, re.M)
    s = START.read_text(errors="replace")
    ov = int(re.search(r"MOV\s+STKOV,#0?([0-9A-F]+)H", s).group(1), 16)
    un = int(re.search(r"MOV\s+STKUN,#0?([0-9A-F]+)H", s).group(1), 16)
    return int(m.group(1), 16), un - ov


def _defines():
    t = TARGET.read_text(errors="replace")
    d = {}
    for m in re.finditer(r"#define\s+(TGT_\w+)\s+(0x[0-9A-Fa-f]+|\d+)u?\b", t):
        d[m.group(1)] = int(m.group(2), 0)
    return d


def handler_levels():
    """trap -> ILVL for every handler the firmware enables."""
    d = _defines()
    pairs = (("CC15INT", "CRANK"), ("CC8INT", "CAM"), ("CC9INT", "CAM"),
             ("CC25INT", "DEADLINE"), ("CC16INT", "KNOCK"), ("T8INT", "TICK"),
             ("SSCRINT", "ASIC"), ("SSCTINT", "ASIC_TX"), ("PLAN", "PLAN"),
             ("S0TBINT", "SERIAL_TX"))
    if "TGT_RX_PEC" not in d:             # the CC7 drain exists only without PEC
        pairs += (("CC7INT", "SERIAL"),)
    lv = {d["TGT_TRAP_" + t]: d["TGT_ILVL_" + lvl] for t, lvl in pairs
          if "TGT_TRAP_" + t in d and "TGT_ILVL_" + lvl in d}
    lv[0x02] = 16                       # NMI: above every level
    return lv


class Image:
    def __init__(self):
        self.b = PI.image().read_bytes()
        self.map = PI.MAP.read_text(errors="replace")
        self.labels = {}
        for m in re.finditer(r"^\s*([0-9A-F]{6})H\s+(\w+)\s+LABEL", self.map, re.M):
            self.labels.setdefault(int(m.group(1), 16), m.group(2))
        self.secs = sorted((int(m.group(1), 16), int(m.group(2), 16), m.group(3)) for m in
                           re.finditer(r"^([0-9A-F]{6})H\s+([0-9A-F]{6})H\s+[0-9A-F]{6}H\s+CODE.*?\s(\?\S+)\s*$",
                                        self.map, re.M))

    def sec_of(self, a):
        for lo, hi, n in self.secs:
            if lo <= a <= hi:
                return lo, hi, n
        return None

    def name(self, a):
        return self.labels.get(a, "fn_%06X" % a)

    def byte(self, a):
        return self.b[a - 0x800000] if a >= 0x800000 else self.b[a]


def sweep(img, entry, end):
    """Own frame and outgoing edges of the code in [entry, end)."""
    user = sysb = 0
    calls = []      # (target, return-address bytes)
    indirect = 0
    a = entry
    seg = entry & 0xFF0000
    while a < end:
        op = img.byte(a)
        n = 4 if is4(op) else 2
        b1 = img.byte(a + 1)
        lo = img.byte(a + 2) if n == 4 else 0
        hi = img.byte(a + 3) if n == 4 else 0
        w = lo | (hi << 8)
        if op == 0xEC:                                  # PUSH reg
            sysb += 2
        elif op in (0xC6, 0xD6):                        # SCXT
            sysb += 2
        elif op == 0x88 and (b1 & 0x0F) == 0:           # MOV [-R0],Rn
            user += 2
        elif op == 0x89 and (b1 & 0x0F) == 0:           # MOVB [-R0],Rbn
            user += 1
        elif op == 0x28 and (b1 & 0xF0) == 0x00 and not (b1 & 0x08):
            user += b1 & 0x07                           # SUB R0,#data3
        elif op == 0x26 and b1 == 0xF0:                 # SUB R0,#data16
            user += w
        elif op == 0x06 and b1 == 0xF0 and w >= 0x8000:  # ADD R0,#-n
            user += 0x10000 - w
        elif op == 0xCA:                                # CALLA cc,caddr
            calls.append((seg | w, 2))
        elif op == 0xBB:                                # CALLR rel
            rel = b1 - 256 if b1 >= 128 else b1
            calls.append((a + 2 + 2 * rel, 2))
        elif op == 0xDA:                                # CALLS seg,caddr
            calls.append((0x800000 | ((b1 & 0x0F) << 16) | w if b1 >= 0x80 else (b1 << 16) | w, 4))
        elif op == 0xE2:                                # PCALL reg,caddr
            sysb += 2
            calls.append((seg | w, 2))
        elif op == 0xAB:                                # CALLI cc,[Rw]
            indirect += 1
        elif op == 0xEA:                                # JMPA cc,caddr
            if not (entry <= (seg | w) < end):
                calls.append((seg | w, 0))              # leaves: a tail call
        elif op == 0xFA:                                # JMPS seg,caddr
            t = (0x800000 | ((b1 & 0x0F) << 16) | w) if b1 >= 0x80 else (b1 << 16) | w
            if not (entry <= t < end):
                calls.append((t, 0))
        a += n
    return user, sysb, calls, indirect


def analyse(verbose=False, sizes=None):
    img = Image()
    user_size, sys_size = sizes or stack_sizes(img.map)
    vec_targets = {}
    for n in range(1, 0x80):
        e = img.b[VEC + 4 * n: VEC + 4 * n + 4]
        if e[0] == 0xFA:
            t = (0x800000 | ((e[1] & 0x0F) << 16) | (e[2] | (e[3] << 8)))
            vec_targets[n] = t
    levels = handler_levels()
    main = next(a for a, nm in img.labels.items() if nm == "main")
    entries = set(a for a in img.labels if img.sec_of(a))
    entries |= set(vec_targets.values())
    entries.add(main)
    # discover call targets transitively
    frames = {}
    todo = sorted(entries)
    known = set(entries)
    def bounds(a):
        s = img.sec_of(a)
        if s is None:
            return None
        nxt = [e for e in known if a < e <= s[1]]
        return a, (min(nxt) if nxt else s[1] + 1)
    changed = True
    while changed:
        changed = False
        for a in sorted(known):
            bb = bounds(a)
            if bb is None:
                continue
            u, s, calls, ind = sweep(img, *bb)
            for t, _r in calls:
                if t not in known and img.sec_of(t):
                    known.add(t)
                    changed = True
    for a in sorted(known):
        bb = bounds(a)
        if bb is None:
            continue
        frames[a] = sweep(img, *bb)
    memo = {}
    problems = []

    def depth(a, path=()):
        if a in memo:
            return memo[a]
        if a in path:
            problems.append("recursion: " + " -> ".join(img.name(x) for x in path + (a,)))
            return (0, 0, [])
        if a not in frames:
            return (0, 0, [])          # outside any code section (boot ROM)
        u, s, calls, ind = frames[a]
        if ind:
            problems.append("indirect call in %s" % img.name(a))
        bu = bs = 0
        bchain = []
        for t, ret in calls:
            cu, cs, ch = depth(t, path + (a,))
            if cu + cs + ret > bu + bs:
                pass
            if cu > bu:
                bu = cu
            if cs + ret > bs:
                bs = cs + ret
                bchain = ch
        memo[a] = (u + bu, s + bs, [img.name(a)] + bchain)
        return memo[a]

    mu, ms, mch = depth(main)
    per_level = {}
    for trap, a in vec_targets.items():
        if trap not in levels:
            continue
        L = levels[trap]
        u, s, ch = depth(a)
        s += 6                                          # PSW, CSP, IP
        cur = per_level.get(L)
        if cur is None or u > cur[0] or s > cur[1]:
            per_level[L] = (max(u, cur[0] if cur else 0), max(s, cur[1] if cur else 0),
                            "%s(0x%02X)" % (img.name(a), trap))
    total_u = mu + sum(v[0] for v in per_level.values())
    total_s = ms + sum(v[1] for v in per_level.values())
    out = dict(user_main=mu, sys_main=ms, main_chain=mch[:12],
               levels={str(k): dict(user=v[0], sys=v[1], handler=v[2]) for k, v in sorted(per_level.items())},
               user_worst=total_u, sys_worst=total_s, user_size=user_size, sys_size=sys_size,
               problems=problems[:20])
    return out


def main():
    out = analyse("--verbose" in sys.argv)
    if "--json" in sys.argv:
        print(json.dumps(out, indent=1))
        return
    print("main: user %d B, system %d B   %s" % (out["user_main"], out["sys_main"], " -> ".join(out["main_chain"])))
    for L, v in out["levels"].items():
        print("  ILVL %-2s user %3d B, system %3d B   %s" % (L, v["user"], v["sys"], v["handler"]))
    print("worst case nested: USER %d of %d B (%.0f%%), SYSTEM %d of %d B (%.0f%%)"
          % (out["user_worst"], out["user_size"], 100.0 * out["user_worst"] / out["user_size"],
             out["sys_worst"], out["sys_size"], 100.0 * out["sys_worst"] / out["sys_size"]))
    for p in out["problems"]:
        print("  !", p)


if __name__ == "__main__":
    main()
