#!/usr/bin/env python3
r"""V50 gate: the live-Burn path may touch xxIE and NOTHING ELSE.

THE DEFECT THIS EXISTS TO PREVENT is physically proven, not theoretical. V48
and V49 saved each interrupt-control register, wrote the whole register to 0
and restored the whole stale word. The C167CR Derivatives User's Manual V3.1
(2000-03), section 5, register xxIC, settles what that does:

    "Modifying the Interrupt Request flag via software causes the same effects
     as if it had been set or cleared by hardware."

So the restored stale IR = 0 is an explicit CANCEL. On 2026-09-11 it destroyed
a CC7 and a T8 request inside the writer window on the real ECU; the tick died
permanently (hc_tick_isr reloaded T8 in software), the S5500 raster is clocked
by that tick, and 25.80 ms of supervision silence later the CPU took an
external NMI and was reset.

THIS GATE READS THE FINAL LINKED IMAGE, NOT THE C. The C source is intent; the
instruction stream is the artefact that runs. Every instruction FORM checked
here was taken from the compiler's own output - a probe was compiled and its
object code read - rather than assumed from the source text.

F2, inside ?PR?HCNVM (the live-Burn path):

  1  no `MOV <xxIC>, #data16`     (E6 rr ll hh)  - the V48/V49 masking write
  2  no `MOV <xxIC>, Rw` / `,mem` (F6/F2 forms)  - the V48/V49 stale restore
  3  every masking write is `AND <xxIC>, #0FFBFH`  - keeps bit 7 and bits 5..0
  4  every restoring write is `OR <xxIC>, Rw`      - OR can never clear a bit
  5  the immediates used cannot modify xxIR or ILVL/GLVL
  6  it FAILS against the frozen V49 binary - the negative control

F1, inside ?PR?HCMAIN_ME711:

  7  T8REL is programmed exactly once, with the right value, under EXTR
  8  hc_tick_isr contains no write to T8 at all
  9  the period the configured reload produces is exactly 1.000 ms

A gate that only grepped the C would have passed V40's five-write-cycle defect
too. See the project rules, "A GATE FOR THIS CLASS MUST READ BUS CYCLES, NOT SOURCE
TEXT."
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import c166_disasm as D          # noqa: E402
import me711_image               # noqa: E402

# THE NEGATIVE CONTROL IS A FIXED IN-TREE ARTEFACT.
#
# Both V50 gates assert an ABSENCE - "no whole-register write", "no request
# destroyed" - and an absence is the easiest thing in this repository to
# assert vacuously. The control is the frozen V49 binary that physically
# failed on 2026-09-11, sha256 B9158BD6...F71E94. If it is missing the gate
# FAILS rather than skipping: a run without the control proves nothing.
CONTROL_BIN = ROOT / ("bins/hanicore/"
                      "HaniCore_ME711_v49_live_burn_nmi_forensics.bin")
CONTROL_MAP = CONTROL_BIN.with_suffix(".M66")
CONTROL_SHA = "B9158BD621CD9D2FBF366A915B722FE75BC53F6A571C5D4828D62CEE80F71E94"

IC_SFR = {(a - 0xFE00) >> 1: n for a, n in D.SFR.items()
          if n.endswith("IC") and 0xFE00 <= a <= 0xFFDE}
IC_ESFR = {(a - 0xF000) >> 1: n for a, n in D.ESFR.items()
           if n.endswith("IC") and 0xF000 <= a <= 0xF1DE}
IC_ADDR = {a: n for a, n in list(D.SFR.items()) + list(D.ESFR.items())
           if n.endswith("IC")}

IE_BIT = 0x0040            # xxIC bit 6, per the UM diagram and HC_IC()
IR_BIT = 0x0080            # xxIC bit 7
MASK_IMM = 0xFFBF          # AND immediate that clears ONLY xxIE
SET_IMM = 0x0040           # OR immediate that sets ONLY xxIE

T8_ADDR, T8REL_ADDR, T78CON_ADDR = 0xF052, 0xF056, 0xFF20
FCPU_HZ = 40_000_000
TICK_RELOAD = 1250


def rng(name, m66):
    """[start, end) file offsets of a module CODE section, from the .M66 map.

    Rows look like:
      8E0400H  8E2D8FH  002990H  CODE  REL  WORD  ---  1  PUBL  NCODE  ?PR?HCNVM

    Falling back to "scan the whole image" here would sweep the retained Bosch
    boot block in with our code - which is exactly how an earlier revision of
    this gate reported a false failure - so a miss RAISES instead.
    """
    txt = Path(m66).read_text(errors="replace")
    best = None
    pat = (r"^\s*([0-9A-F]{6})H\s+([0-9A-F]{6})H\s+[0-9A-F]{6}H\s+CODE.*?"
           r"(\?PR\?\S+)\s*$")
    for mt in re.finditer(pat, txt, re.M):
        if mt.group(3).upper() != name.upper():
            continue
        lo_i, hi_i = int(mt.group(1), 16), int(mt.group(2), 16)
        s_fo = D.seg_off_to_file(lo_i >> 16, lo_i & 0xFFFF)
        e_fo = D.seg_off_to_file(hi_i >> 16, hi_i & 0xFFFF) + 1
        if best is None or s_fo < best[0]:
            best = (s_fo, e_fo)
    if best is None:
        raise SystemExit("section %s not found in %s - refusing to widen the "
                         "scan to the whole image" % (name, m66))
    return best


def sym(m66, name):
    """File offset of a LABEL in the .M66 map."""
    txt = Path(m66).read_text(errors="replace")
    m = re.search(r"^\s+([0-9A-F]{6})H\s+" + re.escape(name) + r"\s+LABEL",
                  txt, re.M)
    if not m:
        raise SystemExit("symbol %s not found in %s" % (name, m66))
    a = int(m.group(1), 16)
    return D.seg_off_to_file(a >> 16, a & 0xFFFF)


def scan(img, lo, hi):
    """Linear sweep of a code range, collecting every WRITE to an xxIC.

    Kinds:
      "imm"  E6/66/76 <short reg> #data16   - reg field names the xxIC
      "mem"  F2 <short reg> <addr>          - MOV <xxIC>, mem
      "reg"  F6/74/64 <Rw> <addr>           - MOV/OR/AND <xxIC>, Rw
    A READ of an xxIC is F6/F2 with the xxIC in the REGISTER field and an
    ordinary address in the memory field, and is classified by the register,
    so it never lands in this list.
    """
    out = []
    fo = lo
    esfr_left = 0
    while fo < hi - 3:
        op = img[fo]
        n = 4 if D.is4(op) else 2
        rr = img[fo + 1]
        imm = img[fo + 2] | (img[fo + 3] << 8)
        tbl = IC_ESFR if esfr_left > 0 else IC_SFR
        if op in (0xE6, 0x66, 0x76) and rr in tbl:
            out.append((fo, {0xE6: "MOV", 0x66: "AND", 0x76: "OR"}[op],
                        tbl[rr], "imm", imm))
        elif op == 0xF2 and rr in tbl:
            out.append((fo, "MOV", tbl[rr], "mem", imm))
        elif op in (0x74, 0x64, 0xF6) and imm in IC_ADDR:
            out.append((fo, {0x74: "OR", 0x64: "AND", 0xF6: "MOV"}[op],
                        IC_ADDR[imm], "reg", rr))
        if op == 0xD1 and (rr & 0xC0) == 0x80:        # EXTR #n
            esfr_left = ((rr >> 4) & 3) + 1
        elif esfr_left:
            esfr_left -= 1
        fo += n
    return out


def check_f2(tag, img, m66, expect_fixed):
    print("")
    print("=== %s ===" % tag)
    lo, hi = rng("?PR?HCNVM", m66)
    print("  hcnvm code %06X..%06X  (%d bytes)" % (lo, hi, hi - lo))
    writes = [a for a in scan(img, lo, hi) if a[3] in ("imm", "mem", "reg")]
    bad = []
    ands = ors = 0
    for fo, mnem, reg, kind, val in writes:
        if mnem == "MOV":
            shown = ("#%04X" % val) if kind == "imm" else (
                "mem" if kind == "mem" else "R%d" % (val - 0xF0))
            bad.append((fo, "MOV %s,%s  <-- WHOLE-REGISTER WRITE"
                        % (reg, shown)))
        elif mnem == "AND" and kind == "imm":
            if val != MASK_IMM:
                bad.append((fo, "AND %s,#%04X  <-- not #%04X"
                            % (reg, val, MASK_IMM)))
            else:
                ands += 1
        elif mnem == "OR" and kind == "imm":
            if val != SET_IMM:
                bad.append((fo, "OR %s,#%04X  <-- not #%04X"
                            % (reg, val, SET_IMM)))
            else:
                ors += 1
        elif mnem == "OR" and kind == "reg":
            ors += 1                      # OR with a register only ever SETS
        else:
            bad.append((fo, "%s %s (%s)  <-- unexpected form"
                        % (mnem, reg, kind)))

    print("  xxIC writes: %d   AND-mask %d   OR-restore %d   violations %d"
          % (len(writes), ands, ors, len(bad)))
    for fo, why in bad[:14]:
        print("     %06X  %s" % (fo, why))

    ok = (len(bad) == 0 and ands > 0 and ors > 0)
    if ok:
        assert MASK_IMM & IR_BIT, "AND mask must preserve xxIR"
        assert (MASK_IMM & 0x003F) == 0x003F, "AND mask must preserve ILVL/GLVL"
        assert (SET_IMM & ~IE_BIT) == 0, "OR immediate must touch only xxIE"
        print("  bit discipline: AND #%04X keeps IR + ILVL + GLVL; "
              "OR only ever sets IE" % MASK_IMM)
    print("  -> %s" % ("IE-ONLY DISCIPLINE HOLDS" if ok
                       else "WHOLE-REGISTER WRITES PRESENT"))
    return ok if expect_fixed else (not ok)


def check_f1(img, m66):
    """F1: the CAPCOM unit reloads T8, not the ISR.

    [DS] C167CR Derivatives UM V3.1, section 15 (The Capture/Compare Units):
    "When a timer overflows from FFFFH to 0000H it is reloaded with the value
    stored in its respective reload register TxREL."  Unconditional - the
    CAPCOM timers have no reload-enable bit - so programming T8REL once at
    init is enough, and a lost tick then costs 1 ms instead of 51.4 ms.
    """
    print("")
    print("=== F1: T8 hardware reload ===")
    ok = True
    want = (0 - TICK_RELOAD) & 0xFFFF
    rr_t8rel = (T8REL_ADDR - 0xF000) >> 1
    rr_t8 = (T8_ADDR - 0xF000) >> 1

    def movs(rr, lo, hi, esfr_wanted=True):
        """`MOV <reg>,#imm` sites where `reg` is short-address `rr`.

        THE EXTR WINDOW MUST BE TRACKED, NOT SNIFFED. Keil emits one `EXTR #3`
        covering three consecutive ESFR writes (T7, T8REL, T8), so looking only
        at the two bytes before an instruction reports "NO EXTR" for the second
        and third. Worse, without the window the SAME short address names a
        different register: `E6 29` is T8 inside the window and T1 outside it,
        which made an ordinary `MOV T1,#0` look like a stray T8 reload. Sweep
        linearly and carry the counter, exactly as scan() does.
        """
        out = []
        fo = lo
        esfr_left = 0
        while fo < hi - 3:
            op = img[fo]
            n = 4 if D.is4(op) else 2
            b1 = img[fo + 1]
            if op == 0xE6 and b1 == rr and (esfr_left > 0) == esfr_wanted:
                out.append((fo, img[fo + 2] | (img[fo + 3] << 8), esfr_left > 0))
            if op == 0xD1 and (b1 & 0xC0) == 0x80:
                esfr_left = ((b1 >> 4) & 3) + 1
            elif esfr_left:
                esfr_left -= 1
            fo += n
        return out

    mlo, mhi = rng("?PR?HCMAIN_ME711", m66)
    rel = movs(rr_t8rel, mlo, mhi)
    print("  MOV T8REL,#imm in hcmain: %d  %s"
          % (len(rel), ["%06X=#%04X%s" % (o, v, "" if e else " (NO EXTR!)")
                        for o, v, e in rel]))
    if len(rel) != 1 or rel[0][1] != want or not rel[0][2]:
        print("  !! T8REL must be programmed exactly once, with #%04X, "
              "under an EXTR prefix" % want)
        ok = False

    isr = sym(m66, "hc_tick_isr")
    isr_end = min(isr + 512, mhi)
    t8w = [fo for fo, _v, _e in movs(rr_t8, isr, isr_end)]
    t8w += [fo for fo in range(isr, isr_end - 3)
            if img[fo] == 0xF6 and (img[fo + 2] | (img[fo + 3] << 8)) == T8_ADDR]
    print("  hc_tick_isr at %06X; writes to T8 inside it: %d %s"
          % (isr, len(t8w), [hex(x) for x in t8w[:4]]))
    if t8w:
        print("  !! the ISR still reloads T8 - a lost request would cost a "
              "full 51.4 ms period")
        ok = False

    init_t8 = movs(rr_t8, mlo, mhi)
    print("  MOV T8,#imm in hcmain: %d  %s"
          % (len(init_t8), ["%06X=#%04X" % (o, v) for o, v, _ in init_t8]))

    t78con = None
    for fo in range(mlo, mhi - 3):
        if img[fo] == 0xE6 and img[fo + 1] == ((T78CON_ADDR - 0xFE00) >> 1):
            t78con = img[fo + 2] | (img[fo + 3] << 8)
            break
    if t78con is None:
        print("  !! T78CON is never programmed")
        return False
    t8i = (t78con >> 8) & 0x07
    t8m = (t78con >> 11) & 1
    t8r = (t78con >> 14) & 1
    period = (0x10000 - want) * (2 ** (t8i + 3)) / FCPU_HZ
    print("  T78CON = 0x%04X -> T8I = %d, T8M = %d (0 = timer), T8R = %d (run)"
          % (t78con, t8i, t8m, t8r))
    print("  PT8 = (65536 - %d) * 2^%d / %d Hz = %.6f ms"
          % (want, t8i + 3, FCPU_HZ, period * 1e3))
    if t8m != 0 or t8r != 1:
        print("  !! T8 is not an enabled timer")
        ok = False
    if abs(period - 1e-3) > 1e-9:
        print("  !! period is not exactly 1.000 ms")
        ok = False
    else:
        print("  period is EXACTLY 1.000 ms, and a lost tick now costs 1 ms "
              "instead of 51.4 ms")
    return ok


def verify_control(path):
    """The control must BE the frozen V49 binary, not just a file there."""
    p = Path(path)
    if not p.exists():
        raise SystemExit("negative control missing: %s - a run without it proves nothing, refusing" % p)
    got = hashlib.sha256(p.read_bytes()).hexdigest().upper()
    if got != CONTROL_SHA:
        raise SystemExit("negative control is not the frozen V49 binary: have %s want %s" % (got, CONTROL_SHA))
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", default=str(CONTROL_BIN),
                    help="frozen V49 binary, the negative control")
    ap.add_argument("--control-map", default=str(CONTROL_MAP))
    ap.add_argument("--skip-f1", action="store_true")
    a = ap.parse_args()
    verify_control(a.control)

    img_path = me711_image.image()
    img = img_path.read_bytes()
    m66 = Path(img_path).with_suffix(".M66")
    if not m66.exists():
        raise SystemExit("no .M66 map beside %s" % img_path)
    print("image under test: %s" % img_path)

    results = [("F2 IE-only discipline",
                check_f2("IMAGE UNDER TEST", img, str(m66), True))]
    if not a.skip_f1:
        results.append(("F1 T8 hardware reload", check_f1(img, str(m66))))
    if a.control:
        if not a.control_map:
            raise SystemExit("--control needs --control-map")
        results.append(
            ("negative control (frozen V49 must FAIL F2)",
             check_f2("FROZEN V49 CONTROL", Path(a.control).read_bytes(),
                      a.control_map, False)))

    print("")
    print("=" * 62)
    allok = True
    for name, ok in results:
        print("  %-50s %s" % (name, "PASS" if ok else "FAIL"))
        allok &= ok
    print("=" * 62)
    print("me711_burn_ir_preserve_proof: %s" % ("PASS" if allok else "FAIL"))
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
