#!/usr/bin/env python3
r"""
me75_dc_runtime_proof.py - the ME7.5 DC image (4B0906018DC) runs its CC650 +
68HC05 monitor service: EXECUTE the linked image in c167sim.

    set HANICORE_BOARD=vag_me75_dc
    py tests\firmware\asic\me75_dc_runtime_proof.py

THE QUESTION. The DC has no S5500. hcasicstart.c is compiled from
asic/hcasicstart_dc.inc for this board: the CC650 bus ASIC at 0x480000 gets
the stock 4B0906018DC boot and setup sequences, its output shadows are
refreshed, its analog bytes reach the HAL's tagged window, and the monitor
line P2.5 carries the answer pulses as CC5 compare-mode-1 toggles.

CHECKS
  A  the image boots to the main loop (bootStage = BOOT_LOOP)
  B  the first 20 CC650 writes are the stock boot (0x096D3C) + setup
     (0x070960) sequences, value for value, in order
  C  the shadows keep being refreshed after the setup (>= 1 write per ms)
  D  the CC650 analog bytes (IAT 0x1E, ambient 0x16) reach the HAL window
     as tagged samples on channels 1 and 8 (x4, 10-bit)
  E  P2.5: the first answer ~56 ms after the timers start (2 x 20 ms + 16 ms
     startup silence - the monitor resets the CPU ~90 ms after reset without
     one, bench 2026-11-01), ASync1 (0x1C36 at 1.5 MHz = 3611 T1 ticks), then
     ASync2 (0x2150), then the defined-invalid width (0x17C1 - this model
     never asks a question), one per TX slot (two 20 ms slots apart)

WHY IT CANNOT PASS VACUOUSLY: B compares against the stock bytes read out
of the DC's own image at the cited offsets (the gate re-reads them), D sets
values the firmware cannot invent, E measures pulse edges the CC5 compare
hardware model makes only when the firmware programs it.
NOT PHYSICALLY VERIFIED: c167sim; the CC650 is modelled as plain registers.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("HANICORE_BOARD", "vag_me75_dc")
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402
import c167sim as S  # noqa: E402
import me711_image as PI  # noqa: E402
import me711_boot_test as B  # noqa: E402

STOCK = ROOT / "reference/ME7Sum/bins/4B0906018DC.bin"
FAILS = 0


def check(name, ok, detail=""):
    global FAILS
    FAILS += not ok
    print("  [%s] %-66s %s" % ("PASS" if ok else "FAIL", name, detail))


def stock_sequences():
    """The stock CC650 boot + setup writes, read from the DC image itself:
    every `MOVB RLx,#v ; MOV R10,#reg ; ... ; MOVB [R10],RLx` in the two
    routines, in program order (the stock literals, not retyped)."""
    import c166_disasm as D
    import re
    img = STOCK.read_bytes()
    out = []
    for lo, hi in ((0x096D3C, 0x096D84), (0x070960, 0x070ACA)):
        fo, last, zf = lo, {}, None
        while fo < hi:
            n, t = D.decode(img, fo)
            # the ONE branch in the setup: 0x3E = 0xF1 if the calibration
            # byte 0x8195C3 is 0xF0, else 0x01 - follow the DC's own path
            m = re.match(r"MOVB\s+(RL\d), 15C3$", t)
            if m:
                last[m.group(1)] = img[0x195C3]
            m = re.match(r"CMPB\s+(RL\d), #([0-9A-F]+)h", t)
            if m and m.group(1) in last:
                zf = last[m.group(1)] == int(m.group(2), 16)
            m = re.match(r"JMPR\s+cc_(NZ|UC), 0x([0-9A-F]+)", t)
            if m and (m.group(1) == "UC" or zf is False):
                fo = int(m.group(2), 16)
                continue
            m = re.match(r"MOVB?\s+(R[LH]?\d+), #([0-9A-F]+)h", t)
            if m:
                last[m.group(1)] = int(m.group(2), 16)
            m = re.match(r"MOV\s+M:(FD[0-9A-F]{2}), ZEROS$", t)
            if m:                                   # shadow = 0
                last["M:" + m.group(1)] = 0
            m = re.match(r"MOV\s+M:(FD[0-9A-F]{2}), (R\d+)", t)
            if m and m.group(2) in last:            # shadow = value
                last["M:" + m.group(1)] = last[m.group(2)]
            m = re.match(r"MOVB\s+(RL\d), M:(FD[0-9A-F]{2})", t)
            if m and ("M:" + m.group(2)) in last:   # RLx = shadow (low byte)
                last[m.group(1)] = last["M:" + m.group(2)] & 0xFF
            m = re.match(r"MOVB\s+\[R10\], (RL\d)", t)
            if m:
                out.append((last.get("R10"), last.get(m.group(1))))
            fo += n
    return out


def main() -> int:
    img = B.IMG
    if not img.exists():
        print("SKIP: %s not built" % img.name)
        return 0
    print("=== ME7.5 DC: CC650 + monitor service in c167sim ===")
    print("  image  %s\n" % img.name)

    writes = []                      # (reg, value, step)
    toggles = []                     # (T1, P2.5 after the toggle)
    h = B.Harness(img, echo=True)
    orig_w8 = S.Mem.w8
    orig_cc = S.CPU.check_compares

    def w8(self_, a, v, _o=orig_w8):
        a &= 0xFFFFFF
        if S.ASIC_LO <= a <= S.ASIC_HI:
            writes.append((a - S.ASIC_LO, v & 0xFF, h.cpu.steps))
        return _o(self_, a, v)

    def check_compares(self_, _o=orig_cc):
        n0 = len(self_.cc_toggles)
        _o(self_)
        for ch, _st in self_.cc_toggles[n0:]:
            if ch == 5:
                toggles.append((self_._sget(S.TIMERS["T1"][0]),
                                (self_._sget(0xFFC0) >> 5) & 1))

    S.Mem.w8 = w8
    S.CPU.check_compares = check_compares
    # the CC650's analog registers, as the bus would read them
    h.mem.asic[0x1E] = 0x80          # IAT byte  -> 0x200 in the window
    h.mem.asic[0x16] = 0xCD          # ambient   -> 0x334

    err = h.run(PI.BOOT_STEPS)
    blk = h.och(0, 8)
    stage = B.u16(blk, 2)
    check("A  boots to the main loop", err is None and stage == B.define("BOOT_LOOP"),
          "bootStage=%d %s" % (stage, err or ""))

    want = stock_sequences()
    got = [(r, v) for r, v, _s in writes[:len(want)]]
    # a stock value that comes from a RAM shadow (not a literal) is None:
    # any value matches it, the register must still be the stock one
    first_bad = next((i for i, (a, b) in enumerate(zip(got, want))
                      if a[0] != b[0] or (b[1] is not None and a[1] != b[1])),
                     None)
    if len(got) < len(want):
        first_bad = len(got)
    check("B  the first %d CC650 writes == the stock boot + setup" % len(want),
          len(want) >= 20 and first_bad is None,
          "first difference at %s: got %s want %s" % (
              first_bad, got[first_bad] if first_bad is not None else "-",
              want[first_bad] if first_bad is not None else "-")
          if first_bad is not None else "02=00 26=4A 2A=FF 2B=FF 02=20 3A=%02X ... 52=02"
          % (got[5][1] if len(got) > 5 else 0))

    # run on: the monitor's startup silence + several TX slots
    t1_0 = h.cpu._sget(S.TIMERS["T1"][0])
    tick0 = h.sym_u16("hc_tick_ms")
    w0 = len(writes)
    err = h.run(12_000_000)
    tick1 = h.sym_u16("hc_tick_ms")
    ms = ((tick1 - tick0) & 0xFFFF) if tick0 is not None and tick1 is not None else None
    n_ref = len(writes) - w0
    check("C  shadows refreshed after the setup (>= 1 write per ms)",
          err is None and ms and n_ref >= ms,
          "%d writes in %s ms" % (n_ref, ms))

    base = B.EXTRAM + B.define("TGT_RAM_S5500WIN")
    idx = h.sym_u16("hc_s5500_idx")
    v1 = h.mem.r16(base + 2 * (16 + 1)) if base else None
    v8 = h.mem.r16(base + 2 * (16 + 8)) if base else None
    check("D  CC650 IAT / ambient reach the HAL window (ch 1, ch 8)",
          idx is not None and (idx & 0x0102) == 0x0102 and v1 == 0x200 and v8 == 0x334,
          "idx=0x%04X ch1=%s ch8=%s" % (idx or 0, hex(v1) if v1 is not None else None,
                                         hex(v8) if v8 is not None else None))

    lows = [(t, lvl) for t, lvl in toggles]
    pulses = []
    for (ta, la), (tb, lb) in zip(lows, lows[1:]):
        if la == 0 and lb == 1:
            pulses.append((ta, (tb - ta) & 0xFFFF))
    a1, a2, inv = 0x1C36 >> 1, 0x2150 >> 1, 0x17C1 >> 1
    want = [a1, a2] + [inv] * max(0, len(pulses) - 2)
    widths_ok = len(pulses) > 10 and all(
        abs(w - x) <= 2 for (_t, w), x in zip(pulses, want))
    alternate = all(la != lb for (_a, la), (_b, lb) in zip(toggles, toggles[1:]))
    gaps = [((b - a) & 0xFFFF) for (a, _w), (b, _w2) in zip(pulses, pulses[1:])]
    gaps_ok = gaps and all(29000 <= g <= 31100 for g in gaps)
    # T1 starts at 0 with the timers; 2 slots + 16 ms + the 1.5 ms lead is
    # ~57.5 ms = 43100 ticks. The old 18-slot silence lands at 19900 here.
    first_ok = bool(pulses) and 40000 <= pulses[0][0] <= 47000
    check("E  monitor answers: ASync1, ASync2, then invalid, one per TX slot",
          bool(widths_ok and gaps_ok and alternate and first_ok),
          "%d pulses, first at T1 %s, widths %s, gaps %s, alternating %s" % (
              len(pulses), pulses[0][0] if pulses else None,
              [w for _t, w in pulses[:4]], sorted(set(gaps))[:4], alternate))
    S.Mem.w8, S.CPU.check_compares = orig_w8, orig_cc
    print("\n%s" % ("ALL PASS" if FAILS == 0 else "%d FAILED" % FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
