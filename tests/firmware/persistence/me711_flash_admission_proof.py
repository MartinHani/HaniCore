#!/usr/bin/env python3
r"""V51: the flash-window admission test asks the SSC the RIGHT question.

This gate does not re-implement live_admit().  It EXECUTES THE SHIPPED
INSTRUCTIONS of the admission decision, in place in the linked image, and
supplies only the two things the hardware supplies: the SSCCON word and the
SSC driver's own frame-in-flight byte.  It then reports which way the shipped
code branched.

WHY THE OLD RULE HAD TO GO
  V47..V50 rejected a flash window on  (SSCEN && (SSCCON & 0x0F00)).
  In operating mode those bits are the ERROR STATUS FLAGS SSCTE/RE/PE/BE
  [C167CR Derivatives UM V3.1, section 12, "Register SSCCON (Operating Mode)"],
  and section 12.7 says they "are not reset automatically upon entry into the
  error interrupt service routine, but must be cleared by software".  Nothing
  in HaniCore clears them: SSCEIC is left with SSCEIE = 0 so hc_ssc_err_isr()
  never runs, and a write with SSCEN low targets the control bits, not the
  flags.  So the rule was SELF-POISONING - the writer's own 116 us interrupt
  mask stops PEC4 servicing SSCRB, that sets SSCRE ("reception completed
  before the receive buffer was read"), and from then on every window is
  refused for the rest of the boot.

  PHYSICALLY, on this ECU, 2026-09-11 (V50_BURN_20260911T223758Z):
      SSCCON preflight   0xC00F     flags clear
      SSCCON post-Burn   0xC60F     SSCPE | SSCRE latched
      SSCCON final       0xC60F     still latched 7759 rasters later
      liveWindowsOk 36 / liveWindowsRejected 4993 / livePauseReason 4
  Those two words are used verbatim below.  They are measurements, not cases
  invented to make a point.

WHAT THE NEW RULE ASKS
  The flash bus and the SSC share nothing - the SSC is on-chip, the AM29 is on
  the external bus, and the SSC's PEC endpoints are SSCTB/SSCRB and
  TGT_ASIC_FRAME in external SRAM, so no SSC activity can read a busy device.
  The real hazard is the other direction: masking interrupts across a frame
  that is ALREADY on the wire loses supervision data.  So V51 rejects on
  hc_asic_frame_in_flight(), and on SSCBSY as a hardware cross-check.

THE MATRIX IS THE GATE, AND IT CUTS BOTH WAYS
  V51 must stop rejecting the harmless thing (a latched historical flag) AND
  start rejecting the real one (a frame in flight) that V50 admitted.

NON-VACUOUS BY CONSTRUCTION: every row is run against BOTH the frozen V50
binary that physically failed and the V51 image under test, and the gate fails
unless they disagree on exactly the rows the fix is about.
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
import c167sim as S              # noqa: E402
import me711_image               # noqa: E402

CONTROL_BIN = ROOT / ("bins/hanicore/"
                      "HaniCore_ME711_v50_ir_preserving_mask.bin")
CONTROL_SHA = ("12FA12B9F267B711941BAFEB48E32CC7"
               "C834F2BAD93FD00871139E75F5FB4E47")

SSCCON_SFR = 0xFFB2

# The two words this ECU actually reported, and the two hazard states.
CLEAN = 0xC00F        # PHYSICAL: V50 preflight
LATCHED = 0xC60F      # PHYSICAL: V50 post-Burn, SSCPE | SSCRE
BUSY = 0xD00F         # CLEAN + SSCBSY (bit 12), a frame on the wire
PROG_MODE = 0x461F    # TGT_ASIC_SSCCON_IDLE, SSCEN low

ADMIT, REJECT = "ADMIT", "REJECT"

ROWS = (
    ("clean_idle",       "clean idle",        CLEAN,     0),
    ("latched",          "PE|RE latched",     LATCHED,   0),
    ("sscbsy",           "SSCBSY set",        BUSY,      0),
    ("frame_in_flight",  "frame in flight",   CLEAN,     1),
    ("prog_mode",        "programming mode",  PROG_MODE, 0),
)


def sym(m66, name):
    t = Path(m66).read_text(errors="replace")
    m = re.search(r"^\s+([0-9A-F]{6})H\s+" + re.escape(name) + r"\s+LABEL",
                  t, re.M)
    if not m:
        raise SystemExit("symbol %s not found in %s" % (name, m66))
    return int(m.group(1), 16)


def data_section(m66, sect):
    t = Path(m66).read_text(errors="replace")
    m = re.search(r"^\s*([0-9A-F]{6})H\s+([0-9A-F]{6})H\s+[0-9A-F]{6}H\s+"
                  r"DATA.*?" + re.escape(sect) + r"\s*$", t, re.M)
    if not m:
        raise SystemExit("data section %s not found in %s" % (sect, m66))
    return int(m.group(1), 16), int(m.group(2), 16)


def code_section(m66, sect):
    t = Path(m66).read_text(errors="replace")
    best = None
    pat = (r"^\s*([0-9A-F]{6})H\s+([0-9A-F]{6})H\s+[0-9A-F]{6}H\s+CODE.*?"
           r"(\?PR\?\S+)\s*$")
    for mt in re.finditer(pat, t, re.M):
        if mt.group(3).upper() != sect.upper():
            continue
        lo, hi = int(mt.group(1), 16), int(mt.group(2), 16)
        if best is None or lo < best[0]:
            best = (lo, hi)
    if best is None:
        raise SystemExit("code section %s not found in %s" % (sect, m66))
    return best


def calla_bytes(target):
    """CALLA cc_UC, addr  =  CA 00 <lo> <hi>."""
    return bytes([0xCA, 0x00, target & 0xFF, (target >> 8) & 0xFF])


def find_decision(img, m66):
    """Locate the admission decision inside ?PR?HCNVM, by SYMBOL.

    start   the CALLA to hc_ssc_sscon() the admission uses - the one
            immediately followed by MOV R14,R4 (F0 E4), which is how the
            compiler keeps the word across the following call
    admit   the CALLA to hc_ssc_pec_tx_left(), the next thing live_admit()
            does once the SSC test has passed
    reject  the MOVB RL6,#3h that writes HCNV_ADMIT_ASIC
    """
    lo, hi = code_section(m66, "?PR?HCNVM")
    s_fo = D.seg_off_to_file(lo >> 16, lo & 0xFFFF)
    e_fo = D.seg_off_to_file(hi >> 16, hi & 0xFFFF) + 1
    blk = img[s_fo:e_fo]

    sscon_call = calla_bytes(sym(m66, "hc_ssc_sscon") & 0xFFFF)
    pec_call = calla_bytes(sym(m66, "hc_ssc_pec_tx_left") & 0xFFFF)

    starts = [i for i in range(len(blk) - 6)
              if blk[i:i + 4] == sscon_call
              and blk[i + 4:i + 6] == b"\xF0\xE4"]
    if len(starts) != 1:
        raise SystemExit("expected exactly one admission sscon call, got %d"
                         % len(starts))
    start = starts[0]

    admits = [i for i in range(start, len(blk) - 4)
              if blk[i:i + 4] == pec_call]
    if not admits:
        raise SystemExit("no hc_ssc_pec_tx_left call after the sscon call")
    admit = admits[0]

    rejects = [i for i in range(start, admit) if blk[i:i + 2] == b"\xE1\x3C"]
    if not rejects:
        raise SystemExit("no MOVB RL6,#3h (HCNV_ADMIT_ASIC) in the decision")
    reject = rejects[0]

    base = lo & 0xFFFF
    return {"seg": lo >> 16, "start": base + start, "admit": base + admit,
            "reject": base + reject, "span": admit - start}


def const(m66, name):
    """A linker CONST value, e.g. ?C_PAGEDPP2."""
    t = Path(m66).read_text(errors="replace")
    m = re.search(r"^\s+([0-9A-F]{6})H\s+" + re.escape(name) + r"\s+CONST",
                  t, re.M)
    if not m:
        raise SystemExit("const %s not found in %s" % (name, m66))
    return int(m.group(1), 16)


def dpps(m66):
    """THE DATA PAGE POINTERS THIS FIRMWARE ACTUALLY RUNS WITH, derived.

    c167sim's CPU constructor seeds DPP0..3 with the ME7.5 05.12 bootblock's
    values (0x0000, 0x0205, 0x00E0, 0x0003) - correct for a gate that starts
    at the reset vector and lets start_me711.a66 install its own, and WRONG
    for one that jumps into the middle of the code, which is what this gate
    does.  With the ME7.5 DPP2 = 0x00E0 the accessor's operand 0xBAD7 resolves
    to 0x383AD7 in external SRAM instead of 0x00FAD7 in near RAM, the seeded
    byte is never read, and the gate reports a false PASS on the in-flight row.
    It did, on its first run.

    start_me711.a66 loads DPP0..2 from ?C_PAGEDPPn and DPP3 with the literal 3
    (the system/SFR page), so both halves come from artefacts, not memory.
    hcnmi_v49.a66 records the same trap: "Declaring them through DPP2 would
    silently read 38:BAxx instead of 00:FAxx."
    """
    return (const(m66, "?C_PAGEDPP0"), const(m66, "?C_PAGEDPP1"),
            const(m66, "?C_PAGEDPP2"), 3)


def in_flight_addr(img, m66):
    """The linear address of hcasic.c's `in_flight`, DECODED from the
    accessor's own instruction, translated through the firmware's OWN DPPs,
    and CHECKED against the map's HCASIC near-data block.  Nothing here is
    typed in from memory."""
    a = sym(m66, "hc_asic_frame_in_flight")
    fo = D.seg_off_to_file(a >> 16, a & 0xFFFF)
    op = img[fo:fo + 4]
    if op[0] != 0xF3:
        raise SystemExit("hc_asic_frame_in_flight does not start with "
                         "MOVB reg,mem: %s" % op.hex().upper())
    a16 = op[2] | (op[3] << 8)
    dpp = dpps(m66)[a16 >> 14]
    lin = dpp * 0x4000 + (a16 & 0x3FFF)
    dlo, dhi = data_section(m66, "?ND0?HCASIC")
    if not (dlo <= lin <= dhi):
        raise SystemExit("in_flight operand 0x%04X resolved through DPP%d=%d "
                         "to 0x%06X, outside ?ND0?HCASIC 0x%06X..0x%06X"
                         % (a16, a16 >> 14, dpp, lin, dlo, dhi))
    return lin


def run_case(img, d, dp, ifa, sscon, flight, limit=400):
    """Execute the shipped decision once and say which way it went."""
    m = S.Mem(bytes(img))
    cpu = S.CPU(m, d["seg"], d["start"])

    # AFTER the constructor, which installs the ME7.5 bootblock's DPPs.
    for i, v in enumerate(dp):
        m.sfr[0xFE00 + 2 * i] = v
    # The block really does CALL/RET, so the stack bounds have to be right:
    # 0xFE10 is CP, not STKUN.  STKUN is 0xFE16.
    m.sfr[0xFE12] = 0xFB00                  # SP
    m.sfr[0xFE14] = 0xF600                  # STKOV
    m.sfr[0xFE16] = 0xFB00                  # STKUN
    m.sfr[SSCCON_SFR] = sscon               # THE HARDWARE'S CONTRIBUTION
    if ifa is not None:
        m.w8(ifa, flight)                   # ... and the driver's own state

    for r in range(16):
        cpu.sr(r, 0)
    cpu.sr(0, 0xF800)                       # R0 = the frame pointer

    for _ in range(limit):
        if cpu.ip == d["admit"]:
            return ADMIT
        if cpu.ip == d["reject"]:
            return REJECT
        cpu.step()
    return "RANAWAY"


def analyse(path, tag, has_flight):
    img = Path(path).read_bytes()
    m66 = Path(path).with_suffix(".M66")
    d = find_decision(img, m66)
    dp = dpps(m66)
    ifa = in_flight_addr(img, m66) if has_flight else None
    print("  %-4s %s" % (tag, Path(path).name))
    print("       decision seg%02X:%04X..%04X (%d bytes), reject @%04X"
          % (d["seg"], d["start"], d["admit"], d["span"], d["reject"]))
    print("       DPP0..3 = %s (from ?C_PAGEDPPn)"
          % " ".join("0x%04X" % v for v in dp))
    if ifa is not None:
        print("       in_flight resolved to 0x%06X (inside ?ND0?HCASIC)" % ifa)
    out = {}
    for key, label, sscon, flight in ROWS:
        r = run_case(img, d, dp, ifa, sscon, flight)
        out[key] = r
        print("       %-18s SSCCON=0x%04X in_flight=%d  ->  %s"
              % (label, sscon, flight, r))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", type=Path, default=None)
    a = ap.parse_args()

    img_path = a.image or me711_image.image()
    print("me711_flash_admission_proof")
    print()

    if not CONTROL_BIN.exists():
        raise SystemExit("negative control missing: %s - a run without it "
                         "proves nothing, refusing" % CONTROL_BIN)
    got = hashlib.sha256(CONTROL_BIN.read_bytes()).hexdigest().upper()
    if got != CONTROL_SHA:
        raise SystemExit("negative control is not the frozen V50 binary:\n"
                         "  have %s\n  want %s" % (got, CONTROL_SHA))
    print("  negative control sha256 %s... OK" % CONTROL_SHA[:16])
    print()

    ctl = analyse(CONTROL_BIN, "V50", has_flight=False)
    print()
    utt = analyse(img_path, "V51", has_flight=True)
    print()

    fails = []

    def check(label, cond):
        print("  %-66s %s" % (label, "PASS" if cond else "FAIL"))
        if not cond:
            fails.append(label)

    # --- the control reproduces the physical failure -----------------------
    check("V50 admits a clean idle SSC", ctl["clean_idle"] == ADMIT)
    check("V50 REJECTS on latched SSCPE|SSCRE - the physical defect",
          ctl["latched"] == REJECT)
    check("V50 ADMITS while SSCBSY is set - it never saw the real hazard",
          ctl["sscbsy"] == ADMIT)

    # --- the fix -----------------------------------------------------------
    check("V51 admits a clean idle SSC", utt["clean_idle"] == ADMIT)
    check("V51 ADMITS with SSCPE|SSCRE latched - the flag is history",
          utt["latched"] == ADMIT)
    check("V51 REJECTS while SSCBSY is set", utt["sscbsy"] == REJECT)
    check("V51 REJECTS while an S5500 frame is in flight",
          utt["frame_in_flight"] == REJECT)
    check("V51 admits in programming mode (SSCEN low, no transfer possible)",
          utt["prog_mode"] == ADMIT)

    # --- and the two images must actually DIFFER ---------------------------
    check("the images disagree on the latched-flag row",
          ctl["latched"] != utt["latched"])
    check("the images disagree on the SSCBSY row",
          ctl["sscbsy"] != utt["sscbsy"])

    print()
    if fails:
        print("FAILED %d check(s):" % len(fails))
        for f in fails:
            print("   - %s" % f)
        return 1
    print("me711_flash_admission_proof: 10/10 PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
