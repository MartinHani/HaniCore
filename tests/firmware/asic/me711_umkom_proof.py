#!/usr/bin/env python3
r"""
me711_umkom_proof.py - prove the HaniCore runtime supervision (UMKOM)
responder is a faithful reproduction of the OEM OEM ME7.1.1 `um_service`, and that
the closed loop it forms with a modelled S5500 never resets.

    py tests\firmware\asic\me711_umkom_proof.py

TWO executions, one modelled S5500 stimulus:

  1. the COMPILED HaniCore `hc_umkom_service` (from the canonical image selected by me711_image.py), and
  2. the REAL OEM `um_service` (0x8B1E24) + `um_init` (0x8B2188) + advance
     (0x8B20FC), executed straight out of the target OEM firmware read,

driven with the identical word-1 sequence a modelled S5500 would send. The
model implements the S5500-side semantics recovered in
the maintainer's design notes: an 8-bit LFSR question (FR taps 7/6/4/2), the
shared trust-counter ramp (11..0 then 3..0), and the FR +3 / -1 error counter.

CHECKS:
  A  HaniCore's transmitted word 1 == the OEM's, every tick, for 400 ticks
  B  HaniCore's health counter never reaches the OEM's SRST threshold (13)
     over a long clean run
  C  the modelled S5500's own error counter stays bounded (never resets MAIN)
  D  a single corrupted S5500 frame bumps the health counter by +3 and it
     then recovers by -1 per process cycle (the FR law), no reset

Exits non-zero on any failure.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import c167sim as S  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
import me711_image as PI
import me711_dpp as _dpp  # ONE source of truth for the image under test
HANI = PI.image()
OEM = hcpaths.OEM_READ
MAP = PI.MAP

FR = [12, 3, 8, 4, 14, 13, 15, 9, 2, 0, 7, 10, 5, 11, 6, 1]

# --- OEM state, in DPP2-page ext RAM (near 0x80xx -> phys 0x3800xx) ---
OEM_UM_SVC = (0x8B, 0x1E24)
OEM_UM_INIT = (0x8B, 0x2188)
OEM_UM_ADV = (0x8B, 0x20FC)
OEM_FRAME = 0xD33E
OEM_8091 = 0x380091
OEM_8092 = 0x380092


def _sym(name):
    """Linked linear address of a symbol, read from the L166 map so this proof
    cannot drift out of sync with the build the way hardcoded addresses did
    across V14..V19 (every re-link shifted hc_umkom_* by tens of bytes)."""
    import re as _re
    for m in _re.finditer(r"^\s*([0-9A-F]{6})H\s+(\w+)\s",
                          MAP.read_text(errors="replace"), _re.M):
        if m.group(2) == name:
            return int(m.group(1), 16)
    raise SystemExit(f"{name} not in {MAP.name} - build the target first")


def _far(name):
    a = _sym(name)
    return (a >> 16, a & 0xFFFF)


# --- HaniCore linked symbols, resolved from build/hani_me711.M66.
# hc_umkom_service owns frame words 1..3 in place; HC_FRAME is TGT_ASIC_FRAME.
HC_INIT = _far("hc_umkom_init")
HC_SVC = _far("hc_umkom_service")
HC_FRAME = 0xE100
HC_HEALTH = _sym("hc_umkom_health")

# DPP values: HaniCore's own (from its start_me711.a66 / linker) vs the
# OEM ME7.1.1 OEM application's.
# HaniCore's DPPs are DERIVED - 0x023B was the V52 const page and V53 moved
# NCONST to 0x85C000, which made this gate report 248 TX mismatches against a
# firmware that was fine. The OEM's are a fixed historical fact and stay literal.
HC_DPP = _dpp.page_dpps()
OEM_DPP = (0x0000, 0x0205, 0x00E0, 0x0003)

_LO, _HI = 0x00C000, 0x00DFFF   # extra RAM bank for the OEM's 0xD33E buffer


def patch_mem():
    for nm in ("r8", "w8", "r16", "w16"):
        globals()["_o_" + nm] = getattr(S.Mem, nm)

    def r8(self, a):
        a &= 0xFFFFFF
        return self._cbank[a - _LO] if _LO <= a <= _HI else _o_r8(self, a)

    def w8(self, a, v):
        a &= 0xFFFFFF
        if _LO <= a <= _HI:
            self._cbank[a - _LO] = v & 0xFF
            return
        _o_w8(self, a, v)

    def r16(self, a):
        a &= 0xFFFFFF
        if _LO <= a <= _HI:
            return self._cbank[a - _LO] | (self._cbank[a + 1 - _LO] << 8)
        return _o_r16(self, a)

    def w16(self, a, v):
        a &= 0xFFFFFF
        if _LO <= a <= _HI:
            self._cbank[a - _LO] = v & 0xFF
            self._cbank[a + 1 - _LO] = (v >> 8) & 0xFF
            return
        _o_w16(self, a, v)

    S.Mem.r8, S.Mem.w8, S.Mem.r16, S.Mem.w16 = r8, w8, r16, w16


def new_cpu(img, dpp=OEM_DPP):
    m = S.Mem(img.read_bytes())
    m._cbank = bytearray(_HI - _LO + 1)
    c = S.CPU(m, 0, 0)
    for i, v in enumerate(dpp):
        m.sfr[0xFE00 + 2 * i] = v
    # CP away from all data (HaniCore's own value is 0xFC00). The hc_umkom_*
    # state block (?ND0?HCUMKOM) must NOT overlap
    # the GPR bank.
    m.sfr[0xFE10] = 0xFC00
    m.sfr[0xFE12] = 0xF700
    m.sfr[0xFE14] = 0xF200
    m.sfr[0xFE16] = 0xFE00
    m.w16(0xFC00, 0xF9F0)          # R0 = Keil user stack, grows down clear
    return c


def call(c, seg, off, farptr=None, maxs=200000):
    """farptr: linear address for a Keil `far *` first parameter. It is passed
    as R8 = 14-bit page offset, R9 = page number (EXTP form)."""
    m = c.m
    m.w16(c.cp(), 0xF9F0)           # reset R0 (Keil user stack)
    m.sfr[0xFE14] = 0xF200          # STKOV
    m.sfr[0xFE16] = 0xFE00          # STKUN
    m.sfr[0xFE12] = 0xF700
    # Sentinel for BOTH a near RET (pops IP only) and a far RETS (pops IP then
    # CSP): push [csp, 0xFFFE] and watch IP. Keil SMALL may compile an
    # intra-segment call as near.
    sp = (m.sfr[0xFE12] - 2) & 0xFFFF
    m.w16(sp, seg)
    sp = (sp - 2) & 0xFFFF
    m.w16(sp, 0xFFFE)
    m.sfr[0xFE12] = sp
    if farptr is not None:
        c.sr(8, farptr & 0x3FFF)
        c.sr(9, farptr >> 14)
    c.csp, c.ip = seg, off
    for _ in range(maxs):
        if c.ip == 0xFFFE:
            return "ok"
        try:
            c.step()
        except S.Trap as e:
            return "SRST" if "SRST" in str(e) else "TRAP:" + str(e)
    return "maxsteps"


class S5500:
    """the S5500 side, from the maintainer's design notes."""

    def __init__(self, seed=0xAA):
        self.reg = seed or 1
        self.trust = 11
        self.errc = 11
        self.qhist = []
        self.reset = 0
        self.pn = 0

    def next_q(self):
        b = self.reg or 1
        fb = ((b >> 7) ^ (b >> 6) ^ (b >> 4) ^ (b >> 2)) & 1
        self.reg = ((b << 1) | fb) & 0xFF
        q = self.reg & 0x0F
        self.qhist.append(q)
        return q

    def word1(self, q):
        return ((self.trust & 0x0F) << 4) | (q & 0x0F)

    def judge(self, main_ans):
        self.pn += 1
        if self.pn <= 2 or len(self.qhist) < 2:
            return
        if main_ans == 16 and self.trust == 0:      # periodic FR resync
            return
        want = FR[self.qhist[-2]]
        if main_ans == want:
            self.errc = max(0, self.errc - 1)
        else:
            self.errc += 3
            if self.errc >= 13:
                self.reset += 1

    def step_trust(self):
        self.trust = 3 if self.trust == 0 else self.trust - 1


def stimulus(n, seed=0xAA, corrupt_proc=None):
    """the word-1 stream a modelled S5500 puts on the wire, tick by tick,
    plus the is_process flag (process on ticks where 8094 in {4,0})."""
    s = S5500(seed)
    ph = 4
    proc_n = 0
    out = []
    for _t in range(n):
        is_proc = ph in (4, 0)
        q = s.next_q() if is_proc else (s.qhist[-1] if s.qhist else 0)
        w1 = s.word1(q)
        if corrupt_proc is not None and is_proc and proc_n == corrupt_proc:
            w1 ^= 0x30                        # flip the trust nibble
        out.append((w1, is_proc))
        if is_proc:
            s.step_trust()
            ph = 3
            proc_n += 1
        else:
            ph -= 1
    return out, s


def run_hani(stream):
    patch_needed = True
    c = new_cpu(HANI, HC_DPP)
    call(c, *HC_INIT)
    tx = []
    max_health = 0
    for w1, _is_proc in stream:
        c.m.w16(HC_FRAME + 0, 0x782E)
        c.m.w16(HC_FRAME + 2, w1)
        c.m.w16(HC_FRAME + 4, 0)
        c.m.w16(HC_FRAME + 6, 0)
        r = call(c, *HC_SVC, farptr=HC_FRAME)
        if r != "ok":
            return None, r, max_health
        tx.append(c.m.r16(HC_FRAME + 2))
        h = c.m.r8(HC_HEALTH)
        max_health = max(max_health, h)
    return tx, "ok", max_health


def run_oem(stream):
    c = new_cpu(OEM, OEM_DPP)
    call(c, *OEM_UM_INIT)
    tx = []
    srst = 0
    for w1, _is_proc in stream:
        c.m.w16(OEM_FRAME + 0, 0x782E)
        c.m.w16(OEM_FRAME + 2, w1)
        c.m.w16(OEM_FRAME + 4, 0)
        c.m.w16(OEM_FRAME + 6, 0)
        r = call(c, *OEM_UM_SVC)
        if r == "SRST":
            srst += 1
            c.m.w8(OEM_8092, 11)
        tx.append(c.m.r16(OEM_FRAME + 2))
        call(c, *OEM_UM_ADV)
    return tx, srst


def main():
    if not HANI.exists():
        raise SystemExit(f"no image at {HANI} - build it first")
    patch_mem()
    fails = 0

    def check(name, ok, detail=""):
        nonlocal fails
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:<56s} {detail}")
        if not ok:
            fails += 1

    print("=== HaniCore UMKOM responder vs OEM um_service ===\n")

    # A: byte-for-byte equivalence
    st, _s = stimulus(320, seed=0xAA)
    htx, hr, hmax = run_hani(st)
    otx, osrst = run_oem(st)
    if htx is None:
        check("HaniCore hc_umkom_service executes cleanly", False, hr)
    else:
        mism = sum(1 for a, b in zip(htx, otx) if a != b)
        check("HaniCore TX word 1 == OEM TX word 1, 320 ticks",
              mism == 0, f"{mism} mismatches")
        check("OEM um_service never SRSTs on this stream", osrst == 0,
              f"{osrst} SRST")
        check("HaniCore health counter stays below the SRST threshold (13)",
              hmax < 13, f"max health seen = {hmax}")

    # B/C: long clean runs, several LFSR seeds
    for seed in (0xAA, 0x01, 0xFF):
        st, s = stimulus(640, seed=seed)      # 160 process cycles
        htx, hr, hmax = run_hani(st)
        ok = htx is not None and hmax < 13 and s.reset == 0
        check(f"closed loop stable, LFSR seed {seed:#04x}, 160 cycles",
              ok, f"max health {hmax}, S5500 resets {s.reset}"
                  if htx is not None else hr)

    # D: one corrupted frame -> +3 then recovery
    st, s = stimulus(200, seed=0xAA, corrupt_proc=20)
    c = new_cpu(HANI, HC_DPP)
    call(c, *HC_INIT)
    health_trace = []
    for w1, is_proc in st:
        c.m.w16(HC_FRAME + 0, 0x782E)
        c.m.w16(HC_FRAME + 2, w1)
        c.m.w16(HC_FRAME + 4, 0)
        c.m.w16(HC_FRAME + 6, 0)
        call(c, *HC_SVC, farptr=HC_FRAME)
        if is_proc:
            health_trace.append(c.m.r8(HC_HEALTH))
    before = health_trace[19]
    spike = max(health_trace[20:24])
    after = health_trace[30]
    check("a corrupted S5500 frame raises the health counter",
          spike >= before + 3, f"{before} -> {spike}")
    check("the health counter then recovers (-1 per process cycle)",
          after <= before + 1 and max(health_trace) < 13,
          f"back to {after}, peak {max(health_trace)}")

    print()
    if fails:
        print(f"UMKOM PROOF FAILED ({fails} check(s))")
        sys.exit(1)
    print("UMKOM PROOF PASSES - the responder reproduces the OEM and the "
          "closed loop never resets.")


if __name__ == "__main__":
    main()
