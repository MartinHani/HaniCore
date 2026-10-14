#!/usr/bin/env python3
r"""
me711_cj120_preempt_proof.py - a CJ120 byte that COMPLETES while an interrupt
holds the CPU between ssc_byte()'s flag test and its 64 us timer test must
NOT be counted as an SSC time-out.

    py tests\firmware\outputs\me711_cj120_preempt_proof.py [--control]

WHY (AWT car, 2026-10-10). cjTmo rose ~9x faster with the engine running
(0.19/s vs 0.022/s engine off) and every step cost seconds of lambda.
hcio711.c ssc_byte() runs at TASK level and tested the "byte done" flag,
then the timer - and never re-read the flag after the timer expired. Any
interrupt > 64 us (planner CC26, executor CC25, crank capture, tick, K-line
reply job) landing between the two turned an 8 us byte into a time-out.
Fixed 2026-10-11 (owner OK): the flag is re-read once before a time-out.

THE RIG (c167sim, me711_heartbeat_gap_proof's, LIVE SSC, both banks polled):
the byte's completion is held back until the CPU reaches ssc_byte's T7 read,
i.e. after a flag test that found it not complete; there it completes and T7
advances by PREEMPT_US - exactly what an interrupt of that length at that
instant does. CONTROL RUN (same image): no T7 advance, so the byte merely
completes late - no time-out may be counted either way.

  1. late completion, no interrupt: 0 time-outs, CJ120 transfers happen;
  2. completion during a 100 us interrupt: 0 time-outs, and the preempted
     bytes really occurred (the rig hit the window).
--control: the frozen 050CC11E (raw evidence store, SEMISEQ_WB_FIX_20261010/
image_050CC11E) has the old ssc_byte(): EVERY preempted byte becomes a
time-out (49/49 when measured) - check 2 must FAIL.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402

if "--control" in sys.argv:
    ev = Path(os.environ.get("HANICORE_RAW_EVIDENCE", str(ROOT.parent / "evidence")))
    bins = ev / "SEMISEQ_WB_FIX_20261010" / "image_050CC11E"
    if not (bins / "HaniCore_ME711_v102_dev.bin").exists():
        raise SystemExit("control image missing: %s" % bins)
    r = subprocess.run([sys.executable, __file__],
                       env=dict(os.environ, HANICORE_ME711_STEM="HaniCore_ME711_v102_dev",
                                HANICORE_ME711_BINS=str(bins)))
    ok = r.returncode != 0
    print("\nCONTROL (050CC11E, old ssc_byte): %s"
          % ("FAILS as it must" if ok else "PASSED - the gate cannot tell"))
    raise SystemExit(0 if ok else 1)

import c167sim as S                              # noqa: E402
import me711_heartbeat_gap_proof as HB           # noqa: E402
import me711_image as PI                         # noqa: E402
import me711_wideband_ssc_bound_proof as W       # noqa: E402

SSCRIC, T7 = 0xFF74, S.TIMERS["T7"][0]
PREEMPT_US = 100


def t7_read_pc(img: bytes) -> int:
    """ssc_byte's LOOP timer sample: the nearest MOV Rn,T7 (F2 Fn 50 F0)
    before the bound CMP Rn,#0x50 (80 T7 ticks = 64 us). Old code: sample /
    SUB / CMP after the flag test; fixed code: sample / SUB, flag test, then
    CMP - either way the hook goes on the loop's own sample (the entry
    `t0 = T7` is an earlier MOV). FCODE spans SA6 since V97: search from
    0x30000."""
    hits = []
    for m in re.finditer(rb"\x46[\xF0-\xFF]\x50\x00", img[0x30000:0x60000]):
        cmp_at = 0x30000 + m.start()
        win = img[cmp_at - 32:cmp_at]
        reads = [i for i in range(len(win) - 3)
                 if win[i] == 0xF2 and win[i + 1] >= 0xF0
                 and win[i + 2:i + 4] == b"\x50\xF0"]
        if reads:
            hits.append(cmp_at - 32 + reads[-1])
    if len(hits) != 1:
        raise SystemExit("ssc_byte's T7 bound found %d times - update "
                         "t7_read_pc()" % len(hits))
    return 0x800000 + hits[0]


def run(preempt_us: int) -> dict:
    img = PI.image()
    t7_pc = t7_read_pc(img.read_bytes())
    s1, s2 = W.gen_off("CFG_U_LAM1_SRC"), W.gen_off("CFG_U_LAM2_SRC")
    rig = HB.Rig(img, HB.ENTRY_CURRENT, HB.TICK_CURRENT, echo=True)
    st = {"pending": False, "hits": 0}
    r8, w8, w16 = rig._hooks

    def my_w16(s_, a, v, _o=w16):
        r = _o(s_, a, v)
        if (a & 0xFFFFFF) == HB.SSCTB:               # a CJ120 byte, LIVE SSC
            s_.sfr[SSCRIC] = s_.r16(SSCRIC) & ~0x0080   # not complete YET
            st["pending"] = True
        return r
    rig._hooks = (r8, w8, my_w16)
    cpu = rig.cpu
    step0 = cpu.step

    def step():
        if st["pending"] and ((cpu.csp << 16) | cpu.ip) == t7_pc:
            st["pending"] = False
            st["hits"] += 1
            rig.mem.sfr[SSCRIC] = rig.mem.r16(SSCRIC) | 0x0080   # completed
            if preempt_us:                                        # ...during
                cpu._sset(T7, (cpu._sget(T7) + preempt_us * 5 // 4) & 0xFFFF)
        return step0()
    cpu.step = step
    rig.run(3_000_000)
    t0 = cpu.steps
    at = t0 + 50_000
    for frame in (b"W" + s1.to_bytes(2, "big") + b"\x01",
                  b"W" + s2.to_bytes(2, "big") + b"\x01"):
        rig.queue_rx(at, W.env(frame))
        at += 400_000
    rig.run(at - t0 + 300_000)
    m = rig.mem
    w = lambda k: (m.r8(W.OCH + k) << 8) | m.r8(W.OCH + k + 1)   # noqa: E731
    x0 = w(756)
    rig.run(4_000_000)
    tmo = w(1014)
    return {"xfers": w(756) - x0, "tmo": (tmo & 0xFF) + (tmo >> 8),
            "preempted": st["hits"], "trap": rig.trap}


def check(name, ok, detail=""):
    print("  [%s] %s %s" % ("PASS" if ok else "FAIL", name, detail))
    return ok


def main() -> int:
    print("=== CJ120 byte completing during an interrupt - %s ===" % PI.STEM)
    late = run(0)
    race = run(PREEMPT_US)
    ok = check("late completion, no interrupt: no time-out, transfers happen",
               late["tmo"] == 0 and late["xfers"] >= 20 and late["trap"] is None,
               "time-outs %d, xfers %d" % (late["tmo"], late["xfers"]))
    ok &= check("completion during a %d us interrupt: NO time-out" % PREEMPT_US,
                race["preempted"] >= 10 and race["tmo"] == 0
                and race["trap"] is None,
                "%d of %d preempted bytes counted as time-outs"
                % (race["tmo"], race["preempted"]))
    print("RESULT: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
