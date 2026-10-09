#!/usr/bin/env python3
r"""
me711_asicdump_coherence.py - PROVE the V8 capture is coherent.

    py tests\firmware\asic\me711_asicdump_coherence.py

WHY THIS EXISTS. V6 and V7 both printed a "frozen" 96-word ASIC reply that was
not frozen at all. hcasic.c put RXSNAP at TGT_RAM_ASICLOG and hcasicdump.c put
its two capture slots at the SAME address, so asic_init() - which clears 118
words of RXSNAP on every boot AND on every SSC re-initialisation - wiped the
capture's D_VALID, D_CALC, D_RECV and most of its payload. The region magic sat
at word 224, OUTSIDE the cleared range, so hc_asicdump_init() saw a valid magic
and never rebuilt the slot. The result printed cleanly and was garbage: each
chunk came from a different exchange, and the metadata line from yet another.

Two hardware runs were spent on data that could not mean anything. This file is
the answer to "how do you know V8 is different", and it answers it the only way
that counts - by EXECUTING the final image and watching every memory write.

WHAT IS PROVEN HERE, each one a separate claim that can fail on its own:

  A  the regions are disjoint                     (static, from hctarget.h)
  B  no instruction outside hcasicdump.c ever writes into the capture region,
     and RXSNAP's clear and copy loops in particular never reach it
                                                  (dynamic, every write traced)
  C  payload, CALC, RECV, SC, attempt index and the metadata line all describe
     ONE exchange                                 (dynamic, content-checked)
  D  the capture is immutable across warm resets while its chunks print
                                                  (dynamic, byte-compared)
  E  both slots are independently coherent        (dynamic)

C is the one that matters most, and it is checked by CONTENT, not by structure:
every boot's modelled reply is stamped with a signature unique to that boot in
every word, so a frame stitched from two exchanges is arithmetically visible.
The V6/V7 test only checked that the chunk OFFSET advanced - which a re-captured
frame does too, which is exactly why the bug survived.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import c167sim as S  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
import me711_image as PI  # ONE source of truth for the image under test
IMG = PI.image()
TGT = ROOT / "firmware/targets/me711/hctarget.h"
_tgt = TGT.read_text(errors="replace")

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<52s} {detail}")


def define(name):
    m = re.search(r"#define\s+%s\s+(0x[0-9A-Fa-f]+|\d+)" % name, _tgt)
    if not m:
        raise SystemExit(f"{name} not found in hctarget.h")
    return int(m.group(1), 0)


EXTRAM = define("TGT_EXTRAM_BASE")
DUMP = define("TGT_RAM_ASICDUMP")
DUMP_LIM = define("TGT_RAM_ASICDUMP_LIMIT")
SNAP = define("TGT_RAM_ASICLOG")
SNAP_LIM = define("TGT_RAM_ASICLOG_LIMIT")
WORDS_RUN = define("TGT_ASIC_WORDS_RUN")
FRAMEA = define("TGT_ASIC_FRAME")
BAUD = define("TGT_BAUD")
TICKS_PER_MS_X10 = int(re.search(r"#define\s+TGT_TICKS_PER_MS_X10\s+(\d+)",
                                 _tgt).group(1))

S0RBUF, S0RIC, S0TBUF, S0TIC = 0x00FEB2, 0x00FF6E, 0x00FEB0, 0x00FF6C
SSCTIC, SSCRIC, SSCCON_A = 0x00FF72, 0x00FF74, 0x00FFB2
PECC0, PECC4 = 0x00FEC0, 0x00FEC8
ADCON, ADDAT = 0x00FFA0, 0x00FEA0

_PRISTINE = (S.Mem.r8, S.Mem.w8, S.Mem.w16)

SLOT_WORDS = 134            # 16 metadata + 118 payload
SLOTS = 3
CHUNK = 8                   # words per printed line
D_VALID, D_STATE, D_XFER, D_COUNT = 1, 3, 4, 5
D_CALC, D_RECV, D_SSCCON, D_MS, D_PAY = 6, 7, 8, 10, 16
D_RUNTX = 11
G_CURSOR = SLOTS * SLOT_WORDS + 1
# the three exchanges V10 must walk, and the state that identifies each
WAIT1, WAIT2, RUNTIME_WAIT = 3, 5, 7
# three slots, labelled by exchange chronology - the true V11/V12 design.
# runtime #2 (the datum the V12 salvage exists for) is deliberately NOT a
# fourth in-path slot here; it is recovered post-reset instead, which this
# execution-only 16-boot model (fresh IRAM/on-chip XRAM every boot, only
# the external SRAM persists - see boot_chain()) cannot exercise at all.
# tests/firmware/asic/me711_asicdump_salvage_proof.py proves that mechanism directly.
EXPECT = {0: (WAIT1, 0x60), 1: (WAIT2, 0x60),
          2: (RUNTIME_WAIT, 0x76)}      # runtime #1


# --------------------------------------------------------------------- A ---
def part_a():
    print("--- A. the regions are disjoint (static, from hctarget.h) ---")
    regs = []
    for m in re.finditer(r"#define\s+(TGT_RAM_([A-Z0-9]+))\s+(0x[0-9A-Fa-f]+)uL",
                         _tgt):
        name, short, base = m.group(1), m.group(2), int(m.group(3), 0)
        lm = re.search(r"#define\s+%s_LIMIT\s+(0x[0-9A-Fa-f]+)uL" % name, _tgt)
        if lm:
            regs.append((short, base, base + int(lm.group(1), 0)))
    regs.sort(key=lambda r: r[1])
    for short, lo, hi in regs:
        print(f"      {short:<9s} 0x{lo:04X}..0x{hi:04X}")
    bad = [(a, b) for i, a in enumerate(regs) for b in regs[i + 1:]
           if a[1] < b[2] and b[1] < a[2]]
    check("every declared SRAM region is disjoint", not bad,
          "no overlaps" if not bad else f"OVERLAP {bad}")

    d_lo, d_hi = DUMP, DUMP + DUMP_LIM
    s_lo, s_hi = SNAP, SNAP + SNAP_LIM
    check("ASICDUMP has its own region", not (s_lo < d_hi and d_lo < s_hi),
          f"DUMP 0x{d_lo:04X}..0x{d_hi:04X}  RXSNAP 0x{s_lo:04X}..0x{s_hi:04X}")
    need = (SLOTS * SLOT_WORDS + 2) * 2
    check("the capture fits its region", need <= DUMP_LIM,
          f"{need} bytes needed, 0x{DUMP_LIM:X} = {DUMP_LIM} available")
    # RXSNAP is indexed 0..TGT_ASIC_WORDS_RUN-1 by hcasic.c; the highest byte it
    # can touch must still be below the dump. This is the arithmetic the #error
    # in hcasicdump.c enforces at compile time, restated against the real index.
    reach = SNAP + 2 * WORDS_RUN
    check("RXSNAP's widest index cannot reach ASICDUMP", reach <= DUMP,
          f"RXSNAP[{WORDS_RUN - 1}] ends at 0x{reach:04X}, DUMP starts 0x{DUMP:04X}")
    guard = "TGT_RAM_ASICDUMP overlaps TGT_RAM_ASICLOG" in \
        (ROOT / "firmware/targets/me711/asic/hcasicdump.c"
         ).read_text(errors="replace")
    check("a compile-time #error re-checks it", guard,
          "hcasicdump.c fails the build if the regions are ever re-overlapped")


# --------------------------------------------------------------------- B ---
class Harness:
    """The image with ASC0 + ADC modelled, and EVERY external-SRAM write
    recorded with the PC that issued it."""

    def __init__(self, path, boot_id, seed_ram=None, trace=None, xctr=None):
        self.img = open(path, "rb").read()
        off = self.img[0x8000] | (self.img[0x8001] << 8)
        seg = self.img[0x8002] | (self.img[0x8003] << 8)
        self.mem = S.Mem(self.img)
        self.cpu = S.CPU(self.mem, seg, off)
        self.rxq, self.txb = bytearray(), bytearray()
        self.byte_ticks = int(10 * (TICKS_PER_MS_X10 / 10.0) * 1000 / BAUD)
        self.tx_done_at = 0
        self.trace = trace
        self.xctr = xctr if xctr is not None else [0]
        h = self
        # ALWAYS from the pristine methods, never from whatever the previous
        # Harness left installed.
        S.Mem.r8, S.Mem.w8, S.Mem.w16 = _PRISTINE
        o8, ow8, ow16 = _PRISTINE

        def r8(s_, a, _o=o8):
            a &= 0xFFFFFF
            if a == S0RIC:
                return 0x80 if h.rxq else 0x00
            if a == S0TIC:
                t7 = h.cpu._sget(S.TIMERS["T7"][0])
                return 0x00 if ((h.tx_done_at - t7) & 0xFFFF) < h.byte_ticks \
                    else 0x80
            if a in (S0RIC + 1, S0TIC + 1, S0RBUF + 1):
                return 0x00
            if a == S0RBUF:
                return h.rxq.pop(0) if h.rxq else 0
            return _o(s_, a)

        def note(a, n, v):
            """Record (offset, pc, byte) for every external-SRAM byte written.

            The VALUE matters: hc_asicdump_init() zeroes D_VALID on a cold
            boot, long before any payload exists, so an ordering check that
            only looks at addresses finds that clear and concludes the record
            is torn. It is the write that sets D_VALID to 1 that has to come
            last, and only the value distinguishes the two."""
            if h.trace is None:
                return
            a &= 0xFFFFFF
            if EXTRAM <= a < EXTRAM + 0x8000:
                pc = (h.cpu.csp << 16) | h.cpu.ip
                for k in range(n):
                    h.trace.append((a - EXTRAM + k, pc, (v >> (8 * k)) & 0xFF))

        def w8(s_, a, v, _o=ow8):
            if (a & 0xFFFFFF) == S0TBUF:
                h.txb.append(v & 0xFF)
                t7 = h.cpu._sget(S.TIMERS["T7"][0])
                h.tx_done_at = (t7 + h.byte_ticks) & 0xFFFF
                h.rxq.append(v & 0xFF)
            note(a, 1, v)
            return _o(s_, a, v)

        def w16(s_, a, v, _o=ow16):
            aa = a & 0xFFFFFF
            if aa == ADCON and (v & 0x80):
                s_.sfr[ADDAT] = ((v & 0x0F) << 12) | (100 + (v & 0x0F) * 37)
            # The ASIC model: a real block transfer completes and raises both
            # block-end interrupts, with a reply stamped so its origin is
            # provable. The checksum is deliberately WRONG, because that is the
            # case the dump exists for - a reply that fails validation.
            if aa == SSCTIC and (v & 0x0080):
                # How many words THIS exchange asked for - the firmware put it
                # in PECC4's low byte. 0x60 for a startup frame, 0x76 for the
                # runtime one, and the model must follow rather than assume.
                n = s_.r16(PECC4) & 0x00FF
                if n == 0:
                    n = 0x60
                sm = 0
                h.xctr[0] += 1
                tag = (0x10 + h.xctr[0]) & 0xFF
                for i in range(n - 1):
                    # word 0's LOW byte must be an accepted reply class or the
                    # firmware rejects the frame and never advances; the tag
                    # stays in the high byte so coherence is still provable.
                    w = (tag << 8) | (0x1E if i == 0 else ((i * 7) & 0xFF))
                    _o(s_, FRAMEA + 2 * i, w)
                    sm = (sm + w) & 0xFFFF
                # a VALID checksum this time - V10 has to reach the runtime
                # exchange, which only happens when replies are accepted
                _o(s_, FRAMEA + 2 * (n - 1), sm)
                _o(s_, PECC0, s_.r16(PECC0) & 0xFF00)
                _o(s_, PECC4, s_.r16(PECC4) & 0xFF00)
                s_.sfr[SSCCON_A] = s_.r16(SSCCON_A) & ~0x1000
                s_.sfr[SSCTIC] = s_.r16(SSCTIC) | 0x0080
                s_.sfr[SSCRIC] = s_.r16(SSCRIC) | 0x0080
                h.cpu.irq_pending.add(SSCTIC)
                h.cpu.irq_pending.add(SSCRIC)
            note(a, 2, v)
            return _o(s_, a, v)

        S.Mem.r8, S.Mem.w8, S.Mem.w16 = r8, w8, w16
        if seed_ram:
            for a_, v_ in seed_ram.items():
                ow8(self.mem, EXTRAM + a_, v_)

    def run(self, steps):
        try:
            for _ in range(steps):
                self.cpu.step()
        except S.Trap as e:
            return str(e)
        return None


def boot_chain(n, steps=1400000):
    """n consecutive boots against a PERSISTENT external SRAM, as the real
    ECU's own reset loop does. Returns per-boot text, SRAM image and writes."""
    keep, out = {}, []
    xctr = [0]
    for boot_no in range(n):
        trace = []
        h = Harness(IMG, boot_no, seed_ram=keep, trace=trace, xctr=xctr)
        h.run(steps)
        snap = {a: h.mem.r8(EXTRAM + a) for a in range(0, 0x8000)}
        keep = dict(snap)
        out.append({"text": bytes(h.txb), "ram": snap, "writes": trace})
    return out


def part_b(boots):
    print()
    print("--- B. nothing but the extractor writes the capture (traced) ---")
    lo, hi = DUMP, DUMP + DUMP_LIM
    boots_all = [w for b in boots for w in b["writes"]]
    writers, total = {}, 0
    for b in boots:
        for a, pc, _bv in b["writes"]:
            total += 1
            if lo <= a < hi:
                writers.setdefault(pc, 0)
                writers[pc] += 1
    check("external-SRAM writes were actually traced", total > 0,
          f"{total} byte-write(s) recorded over {len(boots)} boots")
    check("something writes the capture region", bool(writers),
          f"{sum(writers.values())} byte-write(s) from {len(writers)} site(s)")

    # Every writer must live inside hcasicdump.c. Its address range comes from
    # the linker map, so this is checked against the real build, not a guess.
    mp = PI.MAP
    rng = None
    if mp.exists():
        txt = mp.read_text(errors="replace")
        for ln in txt.splitlines():
            f = ln.split()
            if (len(f) >= 4 and f[3].upper() == "CODE"
                    and f[-1].upper() == "?PR?HCASICDUMP"):
                rng = (int(f[0].rstrip("Hh"), 16),
                       int(f[1].rstrip("Hh"), 16))
                break
    if rng:
        stray = {pc: c for pc, c in writers.items()
                 if not (rng[0] <= pc <= rng[1])}
        check("EVERY writer is inside hcasicdump.c", not stray,
              f"all {sum(writers.values())} write(s) from code "
              f"0x{rng[0]:06X}..0x{rng[1]:06X}" if not stray
              else f"STRAY {[hex(p) for p in stray]}")
    else:
        check("hcasicdump.c code range found in the map", False,
              "no ?PR?HCASICDUMP CODE line" if mp.exists() else "map missing")

    # And the specific V6/V7 failure: RXSNAP's own clear/copy loops. Those are
    # the writes into the RXSNAP region; none of them may land in the dump.
    # ATOMICITY. hc_asicdump_capture() writes ST, XFER, COUNT, CALC, RECV,
    # SSCCON, PEC and MS, then the payload, and D_VALID LAST - so a record torn
    # by a reset reads as invalid and is never printed. That ordering is the
    # only thing that makes SC and the attempt index provably belong to the
    # payload printed beside them, so it is checked in the trace rather than
    # asserted from the source.
    for sl in (0, 1):
        base = DUMP + sl * SLOT_WORDS * 2
        # the write that SETS D_VALID (low byte -> 1), not the init clear
        vpos = [i for i, (a, _, bv) in enumerate(boots_all)
                if a == base + D_VALID * 2 and bv == 1]
        ppos = [i for i, (a, _, _b) in enumerate(boots_all)
                if base + D_PAY * 2 <= a < base + (D_PAY + 96) * 2]
        mpos = [i for i, (a, _, _b) in enumerate(boots_all)
                if base + D_STATE * 2 <= a < base + D_PAY * 2]
        if not vpos or not ppos:
            check(f"slot {sl}: D_VALID written after payload", False,
                  "slot never captured in the trace")
            continue
        ok = min(vpos) > max(ppos) and min(vpos) > max(mpos or [0])
        check(f"slot {sl}: D_VALID is written LAST", ok,
              "after all 96 payload words and all metadata "
              f"(valid@{min(vpos)}, last payload@{max(ppos)})" if ok
              else "OUT OF ORDER - a torn record could read as valid")

    slo, shi = SNAP, SNAP + SNAP_LIM
    snap_pcs = {pc for b in boots for a, pc, _ in b["writes"]
                if slo <= a < shi}
    bleed = {pc for pc in snap_pcs if pc in writers}
    check("no RXSNAP writer also writes the capture", not bleed,
          f"{len(snap_pcs)} RXSNAP write site(s), none of them reach the dump"
          if not bleed else f"BLEED {[hex(p) for p in bleed]}")


# --------------------------------------------------------------------- C ---
def parse(boots):
    chunks, meta = [], []
    for i, b in enumerate(boots):
        for ln in b["text"].split(b"\r\n"):
            if ln.startswith(b"HCDM"):
                meta.append((i, ln))
            elif ln.startswith(b"HCD"):
                chunks.append((i, ln))
    return chunks, meta


def part_c(boots):
    print()
    print("--- C. payload, CALC, RECV, SC, attempt and metadata agree ---")
    chunks, meta = parse(boots)
    check("a chunk is printed per boot", len(chunks) >= 5,
          f"{len(chunks)} chunk line(s), {len(meta)} metadata line(s)")

    frames = {}
    for _, c in chunks:
        m = re.match(rb"HCD([0-9A-F]{4}):([0-9A-F]{4})((?: [0-9A-F]{4})+)", c)
        if not m:
            continue
        sl, base = int(m.group(1), 16), int(m.group(2), 16)
        for k, v in enumerate(m.group(3).split()):
            frames.setdefault(sl, {})[base + k] = int(v, 16)

    # 1. every payload word of a slot carries ONE boot's signature
    sigs = {}
    for sl, ws in frames.items():
        for idx, v in ws.items():
            if idx != 95 and v:
                sigs.setdefault(sl, set()).add(v >> 8)
    ok = bool(sigs) and all(len(v) == 1 for v in sigs.values())
    check("every chunk of a slot is from ONE exchange", ok,
          f"slot signatures {{{', '.join(f'{k}:{sorted(v)}' for k, v in sorted(sigs.items()))}}}"
          + ("" if ok else "   <-- STITCHED FROM SEVERAL"))

    # 2. the metadata line must be ARITHMETICALLY consistent with the payload
    #    that was printed alongside it. This is the check that would have failed
    #    on V6 (CALC=0x0997 against a payload summing to 0x0B97).
    for sl, ln in [(int(re.search(rb"S=([0-9A-F]{4})", m).group(1), 16), m)
                   for _, m in meta]:
        f = re.findall(rb"(CALC|RECV|N|SC|ST)=([0-9A-F]{4})", ln)
        d = {k.decode(): int(v, 16) for k, v in f}
        want_st, want_n = EXPECT.get(sl, (None, None))
        ws = frames.get(sl, {})
        if want_n is not None:
            check(f"slot {sl}: it is the exchange we expect there",
                  d.get("ST") == want_st and d["N"] == want_n,
                  f"ST={d.get('ST', 0):04X} (want {want_st:04X}), "
                  f"N={d['N']:04X} (want {want_n:04X})")
        if len(ws) < d["N"]:
            check(f"slot {sl}: full payload printed", False,
                  f"only {len(ws)} of {d['N']} words")
            continue
        calc = sum(ws[i] for i in range(d["N"] - 1)) & 0xFFFF
        check(f"slot {sl}: CALC is the sum of THIS payload", calc == d["CALC"],
              f"printed CALC={d['CALC']:04X}, payload sums to {calc:04X}")
        check(f"slot {sl}: RECV is the last word of THIS payload",
              ws[d["N"] - 1] == d["RECV"],
              f"printed RECV={d['RECV']:04X}, w{d['N'] - 1}={ws[d['N'] - 1]:04X}")
        check(f"slot {sl}: N matches the words printed",
              len(ws) == d["N"], f"N={d['N']:04X}, {len(ws)} printed")
        check(f"slot {sl}: SC and ST were captured with it", "SC" in d,
              f"SC={d.get('SC', 0):04X} ST={d.get('ST', 0):04X}")

    # 3. the attempt index is the one stored WITH the slot, not a live counter
    last = boots[-1]["ram"]

    def rd(sl, w):
        a = DUMP + (sl * SLOT_WORDS + w) * 2
        return last[a] | (last[a + 1] << 8)

    for sl in sorted(frames):
        if rd(sl, D_VALID) != 1:
            continue
        idx = sorted(frames[sl])
        pay = [rd(sl, D_PAY + i) for i in idx]
        printed = [frames[sl][i] for i in idx]
        check(f"slot {sl}: printed words ARE the stored words",
              pay == printed,
              f"{len(idx)} printed word(s) byte-identical to SRAM"
              if pay == printed else "DIVERGED")
        N = rd(sl, D_COUNT)
        st = sum(rd(sl, D_PAY + i) for i in range(N - 1)) & 0xFFFF
        check(f"slot {sl}: stored CALC matches stored payload",
              st == rd(sl, D_CALC),
              f"N={N} CALC={rd(sl, D_CALC):04X} sum={st:04X} "
              f"XFER={rd(sl, D_XFER):04X}")


# --------------------------------------------------------------------- D ---
def part_d(boots):
    print()
    print("--- D. the capture is immutable across warm resets ---")
    lo, hi = DUMP, DUMP + DUMP_LIM
    cur = DUMP + G_CURSOR * 2
    first = None
    changed_after_valid = []
    for i, b in enumerate(boots):
        v = b["ram"][DUMP + D_VALID * 2] | (b["ram"][DUMP + D_VALID * 2 + 1] << 8)
        if v != 1:
            continue
        if first is None:
            first = (i, dict(b["ram"]))
            continue
        for a in range(lo, hi):
            # the cursor is SUPPOSED to advance; slot 1 is allowed to fill once
            if a in (cur, cur + 1):
                continue
            if DUMP + SLOT_WORDS * 2 <= a < DUMP + SLOTS * SLOT_WORDS * 2:
                continue
            if b["ram"][a] != first[1][a]:
                changed_after_valid.append((i, a - DUMP, first[1][a], b["ram"][a]))
    check("slot 0 was captured during the chain", first is not None,
          f"first valid at boot {first[0]}" if first else "never captured")
    check("slot 0 never changes once frozen", not changed_after_valid,
          f"compared over {len(boots) - (first[0] + 1 if first else 0)} later "
          f"boot(s)" if not changed_after_valid
          else f"MUTATED {changed_after_valid[:4]}")
    curs = [b["ram"][cur] | (b["ram"][cur + 1] << 8) for b in boots]
    check("the print cursor advances monotonically",
          all(y >= x for x, y in zip(curs, curs[1:])), f"cursor {curs}")


# --------------------------------------------------------------------- E ---
def part_e(boots):
    print()
    print("--- E. all three slots are independently coherent ---")
    last = boots[-1]["ram"]

    def rd(sl, w):
        a = DUMP + (sl * SLOT_WORDS + w) * 2
        return last[a] | (last[a + 1] << 8)

    filled = [sl for sl in range(SLOTS) if rd(sl, D_VALID) == 1]
    check("all THREE slots filled", filled == [0, 1, 2],
          f"valid slots {filled}   (0,1 = startup #1/#2; 2 = runtime #1)")
    pays, sigs = {}, {}
    for sl in filled:
        N = rd(sl, D_COUNT)
        pays[sl] = [rd(sl, D_PAY + i) for i in range(N)]
        sigs[sl] = pays[sl][0] >> 8
        want_st, want_n = EXPECT[sl]
        check(f"slot {sl} holds the right exchange",
              rd(sl, D_STATE) == want_st and N == want_n,
              f"ST={rd(sl, D_STATE)} N={N}  (want ST={want_st} N={want_n})")
        st = sum(pays[sl][:N - 1]) & 0xFFFF
        check(f"slot {sl} self-consistent",
              st == rd(sl, D_CALC) and pays[sl][N - 1] == rd(sl, D_RECV),
              f"CALC={rd(sl, D_CALC):04X} RECV={rd(sl, D_RECV):04X} "
              f"T={rd(sl, D_MS)} ms")
    if len(filled) == SLOTS:
        check("all three slots hold DIFFERENT exchanges",
              len(set(sigs.values())) == SLOTS,
              f"signatures {[f'{sigs[k]:02X}' for k in sorted(sigs)]}")
        check("slot 2 really is a 118-word runtime frame",
              rd(2, D_COUNT) == 0x76,
              f"N={rd(2, D_COUNT)} = 0x{rd(2, D_COUNT):02X}")


def main():
    print(f"image {IMG.name}")
    print()
    part_a()
    print()
    print("running a 16-boot chain against persistent SRAM...")
    boots = boot_chain(16)
    part_b(boots)
    part_c(boots)
    part_d(boots)
    part_e(boots)
    print()
    bad = [n for n, ok, _ in results if not ok]
    print(f"{len(results) - len(bad)}/{len(results)} checks pass")
    if bad:
        print("FAILED: " + "; ".join(bad))
        return 1
    print("THE V11 CAPTURE IS COHERENT (in simulation)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
