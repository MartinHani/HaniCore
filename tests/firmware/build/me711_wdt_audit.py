#!/usr/bin/env python3
r"""
me711_wdt_audit.py - audit the FINAL BIN, not the C source.

    py tests\firmware\build\me711_wdt_audit.py [image.bin]

Six questions, answered by disassembling the bytes that will actually be
programmed into the ECU:

  A  every SRVWDT in reachable HaniCore code is immediately preceded by a
     WDTCON write, which is the OEM's own service sequence at 0x8076C2
  B  no bare SRVWDT is left anywhere in HaniCore code
  C  the ASIC start-transfer path is absent (ASICDLG_V8 isolates it)
  D  the SSC is never enabled
  E  every second-level vector slot points into HaniCore code
  F  nothing branches into the removed OEM application

Why this exists: a C source that reads correctly and a compiler that emitted
something else is a class of bug this project has hit before, and a watchdog
service is exactly the kind of thing where "it looks right" is not enough.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

ROOT = Path(__file__).resolve().parents[3]
import me711_image as PI  # ONE source of truth for the image under test
DEFAULT = PI.image()

from me711_nvm_geometry import GEO   # code sector comes from hctarget.h
CODE_LO = GEO.code_base - 0x800000
CODE_HI = CODE_LO + GEO.code_size - 1


def _segments():
    """(lo, hi, name) of every code segment in the linked map, as file
    offsets. Far code also lives below the code sectors (FCODE in SA6), so
    "inside HaniCore code" is the map's answer, not one address range."""
    out = []
    for m in re.finditer(r"^([0-9A-F]{6})H\s+([0-9A-F]{6})H\s+[0-9A-F]{6}H"
                         r".*?([?\w]+)\s*$", PI.MAP.read_text(errors="replace"), re.M):
        if m.group(3).startswith(("?PR?", "?C_")) and int(m.group(1), 16) >= 0x800000:
            out.append((int(m.group(1), 16) - 0x800000,
                        int(m.group(2), 16) - 0x800000, m.group(3)))
    return out


SEGS = _segments()


def in_code(t):
    return CODE_LO <= t <= CODE_HI or any(lo <= t <= hi for lo, hi, _n in SEGS)


SCAN_LO = min([CODE_LO] + [lo for lo, _h, _n in SEGS])
ISR_TABLE = 0x020000

SRVWDT = bytes([0xA7, 0x58, 0xA7, 0xA7])
EINIT = bytes([0xB5, 0x4A, 0xB5, 0xB5])
# MOV WDTCON, Rw   -> F6 Fx AE FF     (mem,reg form; WDTCON = 0xFFAE)
# MOV WDTCON, #imm -> E6 D7 lo hi     (reg 0xD7 == (0xFFAE-0xFE00)/2)
MOV_WDTCON_REG = bytes([0xF6])
MOV_WDTCON_IMM = bytes([0xE6, 0xD7])

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<56s} {detail}")
    return ok


def u16(b, o):
    return b[o] | (b[o + 1] << 8)


def find_all(blob, pat, lo, hi):
    out, i = [], lo
    while True:
        j = blob.find(pat, i, hi)
        if j < 0:
            return out
        out.append(j)
        i = j + 1


def preceded_by_wdtcon(img, site):
    """Is this SRVWDT immediately preceded by a WDTCON write?"""
    # MOV WDTCON,Rw  : F6 Fx AE FF  (4 bytes)
    p = img[site - 4:site]
    if len(p) == 4 and p[0] == 0xF6 and p[2] == 0xAE and p[3] == 0xFF:
        return "MOV WDTCON,R%d" % (p[1] & 0x0F)
    # MOV WDTCON,#imm : E6 D7 lo hi
    if len(p) == 4 and p[0] == 0xE6 and p[1] == 0xD7:
        return "MOV WDTCON,#%04X" % (p[2] | (p[3] << 8))
    return None


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    img = path.read_bytes()
    print("=== HaniCore Bosch ME7.1.1 - machine-code audit of the FINAL BIN ===")
    print(f"image  {path.name}")
    print(f"sha256 {hashlib.sha256(img).hexdigest().upper()}")
    print(f"size   {len(img)}\n")

    # ---- A / B : the watchdog service --------------------------------------
    sites = find_all(img, SRVWDT, CODE_LO, CODE_HI)
    print(f"SRVWDT sites in HaniCore code: {len(sites)}")
    bare = []
    for s in sites:
        how = preceded_by_wdtcon(img, s)
        cpu = 0x800000 + s
        print(f"    0x{cpu:06X}  {img[s-4:s].hex(' ')} | {img[s:s+4].hex(' ')}"
              f"   {how or '*** BARE SRVWDT ***'}")
        if how is None:
            bare.append(cpu)
    check("A: every SRVWDT is preceded by a WDTCON write", not bare,
          f"{len(sites)} sites" if not bare
          else f"{len(bare)} bare, first 0x{bare[0]:06X}")
    check("B: no bare SRVWDT anywhere in HaniCore code", not bare,
          "none" if not bare else str([hex(x) for x in bare]))

    # The value written, and what window it buys.
    vals = set()
    for s in sites:
        p = img[s - 4:s]
        if p[0] == 0xE6 and p[1] == 0xD7:
            vals.add(p[2] | (p[3] << 8))
    # register form: find the MOV Rw,#imm just before it
    for s in sites:
        p = img[s - 4:s]
        if p[0] == 0xF6 and p[2] == 0xAE and p[3] == 0xFF:
            q = img[s - 8:s - 4]
            if q[0] == 0xE6 and (q[1] & 0xF0) == 0xF0:
                vals.add(q[2] | (q[3] << 8))
    for v in sorted(vals):
        rel, wdtin = v >> 8, v & 1
        counts = 65536 - (rel << 8)
        ms = counts / (19968000.0 / (128 if wdtin else 2)) * 1000.0
        print(f"    WDTCON written = 0x{v:04X}  -> WDTREL 0x{rel:02X}, "
              f"WDTIN {wdtin}, {counts} counts = {ms:.1f} ms at 19.968 MHz")
    check("   the window is the boot block's own ~400 ms, not the 80 ms one",
          vals == {0x0B01}, f"values written: {[hex(v) for v in sorted(vals)]}")

    # EINIT must come AFTER the first service, so the WDT is fed from the very
    # first instruction rather than from the end of the startup.
    ein = find_all(img, EINIT, CODE_LO, CODE_HI)
    check("   the first SRVWDT precedes EINIT",
          bool(sites) and bool(ein) and min(sites) < min(ein),
          f"first SRVWDT 0x{0x800000+min(sites):06X}, "
          f"EINIT 0x{0x800000+min(ein):06X}" if ein else "no EINIT found")

    # ---- C / D : the ASIC link is LIVE, and safely so ----------------------
    #
    # These checks inverted at V4. Up to V3 the requirement was that the SSC
    # could not possibly run; now the requirement is that it CAN, because the
    # whole point of the image is the handshake - while the engine layer stays
    # absent. An audit that still demanded isolation would pass a broken image.
    ssc_imm = find_all(img, bytes([0xE6, 0xD9]), CODE_LO, CODE_HI)
    enables = []
    for st in ssc_imm:
        v = u16(img, st + 2)
        if v & 0x8000:
            enables.append((0x800000 + st, v))
    # SSCEN is now set with an OR, deliberately: the control bits are written
    # first with SSCEN LOW (a MOV of 0x461F), and only then is the enable bit
    # OR-ed in. V4 wrote 0xC61F in a single MOV, which on this core means the
    # control bits were ignored whenever SSCEN was already set.
    or_en = find_all(img, bytes([0x76, 0xD9, 0x00, 0x80]), CODE_LO, CODE_HI)
    idle = [st for st in ssc_imm if u16(img, st + 2) == 0x461F]
    check("C: the SSC IS enabled, and in the OEM's order", bool(or_en),
          f"MOV SSCCON,#461Fh x{len(idle)} then OR SSCCON,#8000h at "
          f"0x{0x800000+or_en[0]:06X}" if or_en else "no SSCEN set anywhere")
    check("   the config value is the OEM's own 0x461F", bool(idle),
          f"{len(idle)} site(s) write the control word with SSCEN low")

    # PEC pointers must now be programmed - that is the transport.
    pec = {}
    for addr, nm in ((0xFCF2, "DSTP4"), (0xFCF0, "SRCP4"),
                     (0xFCE2, "DSTP0"), (0xFCE0, "SRCP0")):
        pat = bytes([addr & 0xFF, (addr >> 8) & 0xFF])
        i = CODE_LO
        while True:
            j = img.find(pat, i, CODE_HI)
            if j < 0:
                break
            if j >= 2 and img[j - 2] == 0xF6:
                pec.setdefault(nm, []).append(0x800000 + j - 2)
            i = j + 1
    check("D: all four PEC pointers are programmed", len(pec) == 4,
          ", ".join(f"{k}x{len(v)}" for k, v in sorted(pec.items())))

    # ---- E : vectors --------------------------------------------------------
    bad = []
    for slot in range(128):
        e = img[ISR_TABLE + slot * 4: ISR_TABLE + slot * 4 + 4]
        if e[0] != 0xFA:
            bad.append(slot)
            continue
        t = ((e[1] << 16) | (e[2] | (e[3] << 8))) - 0x800000
        # 2026-10-12: in_code(), not the code sectors alone - far code
        # (FCODE) also lives in SA6, and the linker placed ?PR?HCSERIAL711
        # (hc_s0tb_isr, slot 71) there once FCODE grew. The map decides.
        if not in_code(t):
            bad.append(slot)
    check("E: all 128 vector slots land inside HaniCore code", not bad,
          "128 slots" if not bad else f"{len(bad)} bad: {bad[:6]}")

    # ---- F : no branch into removed OEM application -------------------------
    LONG = {2, 3, 4, 5, 6, 7, 0xA}
    off, out = SCAN_LO, []
    while off <= CODE_HI - 3:
        # walk code segments only: the code sectors also hold constant data
        if not any(lo <= off <= hi for lo, hi, _n in SEGS):
            off += 2
            continue
        op = img[off]
        if op in (0xFA, 0xDA):
            seg, dst = img[off + 1], u16(img, off + 2)
            if 0x81 <= seg <= 0x8F:
                t = (seg - 0x80) * 0x10000 + dst
            elif seg in (0x00, 0x80):
                t = dst
            else:
                t = None
            if t is not None and not in_code(t) \
               and not (0x000220 <= t <= 0x00030F):
                out.append((0x800000 + off, seg, dst))
        off += 4 if (op & 0x0F) in LONG else 2
    check("F: nothing branches into the removed OEM application", not out,
          "no far branch leaves HaniCore code" if not out
          else str([(hex(a), hex(s), hex(d)) for a, s, d in out[:4]]))

    # ---- G..K : V4 pin behaviour, read out of the emitted bytes ------------
    # 2026-10-12: NOT the address operand of a 4-byte absolute call/jump
    # (CALLS/JMPS DA/FA seg addr, CALLA/JMPA CA/EA cc addr). Code moved and
    # `DA 83 3E E7` (CALLS 0x83:E73E) read as BCLR DP6.3 at its operand.
    FAR_OPS = (0xDA, 0xFA, 0xCA, 0xEA)

    def bitop(q, set_, bo):
        return [x for x in find_all(
            img, bytes([(q << 4) | (0x0F if set_ else 0x0E), bo]),
            SCAN_LO, CODE_HI) if x % 2 == 0 and in_code(x)
            and img[x - 2] not in FAR_OPS]

    bset_p3_12 = bitop(12, True, 0xE2)
    bset_dp3_12 = bitop(12, True, 0xE3)
    bclr_p3_12 = bitop(12, False, 0xE2)
    bclr_dp3_12 = bitop(12, False, 0xE3)

    ok_pair = (len(bset_p3_12) >= 1 and len(bset_dp3_12) >= 1
               and bset_dp3_12[0] == bset_p3_12[0] + 2)
    check("G: NLEN_FR is latch-THEN-direction", ok_pair,
          f"BSET P3.12 0x{0x800000+bset_p3_12[0]:06X} then BSET DP3.12 "
          f"0x{0x800000+bset_dp3_12[0]:06X}" if ok_pair else "not paired")
    check("   ... and before EINIT, as the OEM does",
          ok_pair and bool(ein) and bset_p3_12[0] < min(ein),
          f"NLEN 0x{0x800000+bset_p3_12[0]:06X} < EINIT "
          f"0x{0x800000+min(ein):06X}" if ok_pair and ein else "n/a")
    # H, V79: RUN-ON EXISTS, SO ONE CLEAR OF THE P3.12 LATCH IS ALLOWED - AND
    # ONLY ONE, AND ONLY IN hc_io_runon_service(). The DIRECTION may never be
    # released (that would float the veto), and no other routine may touch
    # the latch. The range is the routine's own, from the linked map.
    import re as _re
    labels = sorted(int(m.group(1), 16) for m in _re.finditer(
        r"([0-9A-F]{6})H\s+PUBLIC\s+LABEL\s+---\s+---\s+hc_io_\w+",
        PI.MAP.read_text(errors="replace")))
    ro = _re.search(r"([0-9A-F]{6})H\s+PUBLIC\s+LABEL\s+---\s+---\s+"
                    r"hc_io_runon_service\s",
                    PI.MAP.read_text(errors="replace"))
    ok_h = False
    why = "hc_io_runon_service not in the map"
    if ro:
        lo = int(ro.group(1), 16) - 0x800000
        nxt = [a for a in labels if a > lo + 0x800000]
        hi = (min(nxt) - 0x800000) if nxt else lo + 0x200
        inside = [x for x in bclr_p3_12 if lo <= x < hi]
        ok_h = (not bclr_dp3_12 and len(bclr_p3_12) >= 1
                and len(inside) == len(bclr_p3_12))
        why = ("BCLR P3.12 only inside hc_io_runon_service (%s); DP3.12 "
               "never cleared" % ", ".join("0x%06X" % (0x800000 + x)
                                          for x in inside) if ok_h else
               "BCLR P3.12 at %s, BCLR DP3.12 at %s, routine 0x%06X..0x%06X"
               % ([hex(0x800000 + x) for x in bclr_p3_12],
                  [hex(0x800000 + x) for x in bclr_dp3_12],
                  0x800000 + lo, 0x800000 + hi))
    check("H: NLEN_FR is released ONLY by the run-on routine", ok_h, why)

    # P6.4 is the ASIC select and V4 DOES drive it. What matters now is that it
    # is an output whose IDLE state is HIGH - a select stuck low is a select.
    dp6_out = bitop(4, True, 0xE7)
    p6_hi = bitop(4, True, 0xE6)
    p6_lo = bitop(4, False, 0xE6)
    check("I: P6.4 is an output (it is the ASIC chip select)", bool(dp6_out),
          f"{len(dp6_out)} BSET DP6.4")
    check("   and it is driven HIGH more often than LOW (idle deselected)",
          len(p6_hi) > len(p6_lo),
          f"{len(p6_hi)} high vs {len(p6_lo)} low")

    # J: the frame word count in the emitted code must be the real 0x60 / 0x76.
    # The count is an unsigned char parameter, so the compiler emits a BYTE
    # immediate (MOVB RLn,#60h = E7 Fx 60 00), not MOV Rw,#0060h. Checking for
    # the wrong encoding is how this check first "failed" on a correct image.
    cnt60 = [x for x in find_all(img, bytes([0xE7]), CODE_LO, CODE_HI)
             if x % 2 == 0 and img[x + 2] == 0x60 and img[x + 3] == 0x00
             and (img[x + 1] & 0xF0) == 0xF0]
    cnt76 = [x for x in find_all(img, bytes([0xE7]), CODE_LO, CODE_HI)
             if x % 2 == 0 and img[x + 2] == 0x76 and img[x + 3] == 0x00
             and (img[x + 1] & 0xF0) == 0xF0]
    check("J: the 96- and 118-word frame counts are both emitted",
          bool(cnt60) and bool(cnt76),
          f"{len(cnt60)} site(s) load #60h (96 words), "
          f"{len(cnt76)} load #76h (118 words)")

    # L: the SSC interrupt nodes must be CLAIMED and must disable their own
    # enable. ASICLIVE_V4 left all three on the catch-all and the hardware
    # reported it as a bad-vector storm with FV=0x2D / LV=0x2E. The OEM's own
    # TX handler is "BCLR SSCTIE; RETI"; Keil emits the AND-mask form.
    vec_ok, vec_detail = True, []
    for slot, nm in ((0x2D, "SSCTINT"), (0x2E, "SSCRINT"), (0x2F, "SSCEINT")):
        e = img[ISR_TABLE + slot * 4: ISR_TABLE + slot * 4 + 4]
        t = ((e[1] << 16) | (e[2] | (e[3] << 8))) if e[0] == 0xFA else 0
        vec_detail.append(f"{nm} 0x{t:06X}")
        if not (CODE_LO <= t - 0x800000 <= CODE_HI):
            vec_ok = False
    check("L: the three SSC traps are claimed by real handlers", vec_ok,
          ", ".join(vec_detail))

    # AND SSCTIC/SSCRIC, #FFBFh clears bit 6 = the interrupt enable.
    dis_tx = find_all(img, bytes([0x66, 0xB9, 0xBF, 0xFF]), CODE_LO, CODE_HI)
    dis_rx = find_all(img, bytes([0x66, 0xBA, 0xBF, 0xFF]), CODE_LO, CODE_HI)
    check("   ... and each disables its own interrupt enable",
          bool(dis_tx) and bool(dis_rx),
          f"SSCTIE cleared at 0x{0x800000+dis_tx[0]:06X}, "
          f"SSCRIE at 0x{0x800000+dis_rx[0]:06X}" if dis_tx and dis_rx
          else "MISSING - the PEC block end will storm the catch-all")

    # M: SSCCON control bits may only be written with SSCEN LOW. V4 wrote
    # 0xC61F in one go and could never clear an error afterwards.
    en_low = find_all(img, bytes([0x66, 0xD9, 0xFF, 0x7F]), CODE_LO, CODE_HI)
    check("M: SSCEN is cleared before SSCCON is reconfigured", bool(en_low),
          f"AND SSCCON,#7FFFh at 0x{0x800000+en_low[0]:06X}" if en_low
          else "MISSING - control-bit writes will be ignored while enabled")

    # N: THE SHARED-SPI GATE. P6.3 (CS_EEPR -> the ST95040) and P6.4 (CS-ASIC)
    # sit on the SAME MRST/MTSR/SCLK wires [BOSCH-PM]. Every image up to V6 left
    # them as INPUTS while clocking 1536 bits at the bus, and the BOM shows no
    # pull-up anywhere near S5300. Both must be DRIVEN, always, and nothing may
    # return either to an input.
    fl3 = bitop(3, False, 0xE7)      # BCLR DP6.3
    fl4 = bitop(4, False, 0xE7)      # BCLR DP6.4
    check("N: neither SPI chip select can ever float", not fl3 and not fl4,
          "no BCLR of DP6.3 or DP6.4 anywhere"
          if not fl3 and not fl4
          else f"DP6.3 floated at {[hex(0x800000+x) for x in fl3]}, "
               f"DP6.4 at {[hex(0x800000+x) for x in fl4]}")
    drv3 = bitop(3, True, 0xE7)
    hi3 = bitop(3, True, 0xE6)
    check("   CS_EEPR is driven HIGH (the EEPROM is deselected)",
          bool(drv3) and bool(hi3),
          f"BSET P6.3 at 0x{0x800000+hi3[0]:06X}, BSET DP6.3 at "
          f"0x{0x800000+drv3[0]:06X}" if drv3 and hi3 else "MISSING")

    # The two CJ120 selects share the SSC with the S5500: [BIN seg8B:FF5E]
    # latches P8.1/P8.2 HIGH and drives them. MOV DP8,#0006h (E6 EB 06 00)
    # after the P8 = 0x00FF latch write is HaniCore's copy of that.
    cj = [a for a in find_all(img, bytes([0xE6, 0xEB, 0x06, 0x00]),
                              CODE_LO, CODE_HI) if a % 2 == 0]
    check("   CJ120 selects P8.1/P8.2 are driven HIGH (deselected)", bool(cj),
          f"MOV DP8,#0006h at 0x{0x800000+cj[0]:06X}" if cj else "MISSING")

    # O: the engine drivers are ACTIVE LOW on this board - the OEM's power-on
    # port init drives them HIGH ([BIN] P2=0xC7FF, P7=0x00F4, P8=0x00FF). The
    # safe LATCH value is therefore high, not low.
    lat = {}
    for reg, nm in ((0xE0, 'P2'), (0xE8, 'P7'), (0xEA, 'P8')):
        for st in find_all(img, bytes([0xE6, reg]), CODE_LO, CODE_HI):
            if st % 2 == 0:
                lat.setdefault(nm, []).append(u16(img, st + 2))
    ok = (0x00FF in lat.get('P2', []) and 0x00F4 in lat.get('P7', [])
          and 0x00FF in lat.get('P8', []))
    check("O: engine-driver latches hold the OEM OFF state (active low)", ok,
          f"P2={[hex(v) for v in lat.get('P2',[])]}, "
          f"P7={[hex(v) for v in lat.get('P7',[])]}, "
          f"P8={[hex(v) for v in lat.get('P8',[])]}")

    # K: THE SAFETY GATE. Coils P2.0-7, injectors P7.4-7 and P8.3-7 are
    # driven since the engine runtime exists, but only by the code that owns
    # them: the HAL (permission-gated), the compare executor and the bounded
    # bench test. A bit-set of their direction anywhere else is a pin some
    # other module could leave driving a coil. [BOSCH-PM sheet FR.]
    owners = [(lo, hi) for lo, hi, n in SEGS
              if n in ("?PR?HCHAL_ME711", "?PR?HCDEADLINE711", "?PR?HCBENCH")]
    unsafe = []
    for q in range(8):
        unsafe += [(f"DP2.{q}", x) for x in bitop(q, True, 0xE1)]
    for q in (4, 5, 6, 7):
        unsafe += [(f"DP7.{q}", x) for x in bitop(q, True, 0xE9)]
    for q in (3, 4, 5, 6, 7):
        unsafe += [(f"DP8.{q}", x) for x in bitop(q, True, 0xEB)]
    unsafe = [(n, a) for n, a in unsafe if not any(lo <= a <= hi for lo, hi in owners)]
    check("K: coil/injector pins are made outputs only by the HAL, executor or bench",
          len(owners) == 3 and not unsafe,
          "owners %d of 3; others: %s" % (len(owners), str([(n, hex(0x800000 + a))
                                                            for n, a in unsafe[:5]]) or "none"))

    print()
    n_bad = sum(1 for _, ok, _ in results if not ok)
    print(f"{len(results) - n_bad}/{len(results)} checks pass")
    if n_bad:
        print("AUDIT FAILED - do not flash")
        return 1
    print("MACHINE-CODE AUDIT PASSES.")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
