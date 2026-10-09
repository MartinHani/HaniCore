#!/usr/bin/env python3
r"""Bound CC25 slices and prove an edge due during history wins at once.

    py tests\firmware\trigger\me711_executor_slice_proof.py [--control]

The linked-image rig publishes a four-channel injector pulse longer than one
16-bit timer wrap. Around its close, independently owned coil events become
due at successive offsets. This covers multichannel width history, the native
long-width division path, and a deadline arriving during bookkeeping. No main
loop runs and no task dispatches outputs.

Every handler invocation is <=160 us, every critical section is <=50 us, and
all commanded edges are <=100 us late. The accepted injector width is preserved
and no output stays ON. --control adds 200 us of real simulated instructions
at the first close's return from the critical level; it must break both the
handler and edge budgets. It models the unsliced history defect.

This proves software command timing only, not electrical timing.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402
import me711_image as I  # noqa: E402
import me711_deadline_proof as D  # noqa: E402

CC25 = 0x39
T7, PSW, SP = 0xF050, 0xFF10, 0xFE12


class SliceRig(D.Rig):
    def __init__(self, control=False):
        super().__init__()
        self.control = control
        self.isr_max_steps = 0
        self.critical_max_steps = 0
        self.n = 0
        self.delayed = False
        self.m.w8(0xE900, 0x0D)
        self.m.w8(0xE901, 0xFF)  # JMPR cc_UC,-1: a real instruction delay

    def run(self, ticks):
        end = self.wall + ticks
        prev = (self.m.r16(0xFFC2) & 0xFF, self.m.r16(0xFFD2) & 0x70,
                self.m.r16(0xFFD6) & 0xF8)
        last = self.m.r16(T7)
        entry = None
        critical = 0
        delay = None
        close_seen = False
        for _ in range(ticks * 12 + 20000):
            taken = self.c.irq_taken
            self.c.step()
            sp = self.m.r16(SP)
            if self.c.irq_taken != taken:
                assert entry is None, "an unexpected interrupt nested the fixture"
                assert self.c.irq_count.get(CC25, 0) > self.n
                entry = (self.c.steps, sp)
                self.n += 1
            if entry is not None and sp >= entry[1] + 6:
                self.isr_max_steps = max(self.isr_max_steps, self.c.steps - entry[0])
                entry = None
            lv = self.m.r16(PSW) >> 12
            if lv >= 13:
                critical += 1
                self.critical_max_steps = max(self.critical_max_steps, critical)
            else:
                critical = 0
            now = (self.m.r16(0xFFC2) & 0xFF, self.m.r16(0xFFD2) & 0x70,
                   self.m.r16(0xFFD6) & 0xF8)
            if (prev[1] or prev[2]) and not (now[1] or now[2]):
                close_seen = True
            if self.control and close_seen and not self.delayed and lv == 11:
                delay = (self.c.steps + 2000, self.c.csp, self.c.ip)
                self.c.csp, self.c.ip = 0, 0xE900
                self.delayed = True
            if delay is not None and self.c.steps >= delay[0]:
                self.c.csp, self.c.ip = delay[1], delay[2]
                delay = None
            t = self.m.r16(T7)
            self.wall += (t - last) & 0xFFFF
            last = t
            if now != prev:
                self.log.append((self.wall, t, now))
                prev = now
            if self.wall >= end and self.c.ip == 0xE800 and self.c.csp == 0:
                return
        raise AssertionError("idle/ISR did not reach the fixture time bound")


def scenario(offset, control):
    r = SliceRig(control)
    # Function publication advances timers. Absolute deadlines remove that
    # setup cost from the intended relationship between independent edges.
    start, width_us = 4000, 60000
    close = start + width_us * 5 // 4
    injector = r.publish(3, 15, start, width_us, absolute=True)
    assert injector, "fixture injector admission failed"
    # Advance into the long pulse so its close is less than one timer wrap
    # ahead; publication still uses the real admission/queue code throughout.
    r.run(40000)
    coil = r.publish(1, 1, (close + offset) & 0xFFFF, 1000, absolute=True)
    assert coil, "fixture coil admission failed"
    r.run(close + 4000 - r.wall)
    late_us = r.diag(14) * 0.8
    width = r.m.r16(D.DIAG + 38 + 8)
    coil_edges = []
    previous = 0
    for _, t, ports in r.log:
        if ports[0] & 1 and not previous:
            coil_edges.append(t)
        previous = ports[0] & 1
    ok = (r.isr_max_steps <= 1600 and r.critical_max_steps <= 500
          and late_us <= 100 and r.diag(13) == 0 and len(coil_edges) == 1
          and abs(width - width_us) <= 100 and r.dirs() == (0, 0, 0))
    return ok, dict(offset=offset, cc25_us=r.isr_max_steps / 10,
                    critical_us=r.critical_max_steps / 10, late_us=late_us,
                    injector_us=width, coil_edges=len(coil_edges),
                    final_directions=r.dirs(), control_delay=r.delayed)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--control", action="store_true")
    args = ap.parse_args()
    print("image", I.sha256())
    results = [scenario(offset, args.control) for offset in (0, 16, 32, 48, 64, 80, 96)]
    for ok, detail in results:
        print("[%s]" % ("PASS" if ok else "FAIL"), detail)
    if args.control:
        failed = any(not ok and d["control_delay"] and d["cc25_us"] > 160
                     and d["late_us"] > 100 for ok, d in results)
        print("CONTROL", "PASS" if failed else "FAIL")
        return 0 if failed else 1
    return 0 if all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
