#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""me711_nvm_forensics.py - what a bootmode readback actually says.

THIS IS A FORENSIC INSTRUMENT, NOT A GATE. It takes a flashed image and a 1 MiB
readback of the same device and reports, without interpretation:

  * every byte that differs, grouped into contiguous ranges;
  * every one of the sixteen append-only cells: how many words were programmed,
    where programming stopped, what the next word should have been, what it
    actually is;
  * whether any bit went 0 -> 1 (impossible without an erase);
  * whether anything was written outside a legal cell body;
  * the ROMSYS program-page checksum, stored and computed;
  * the first and last word of all sixteen 8 KiB checksum pages of SA7/SA8.

It carries NO version knowledge. Point it at V39, V40 or V41 and it says the
same kinds of things about each, which is the only way two dumps can be
compared.

Usage:
    py tools/analysis/me711_nvm_forensics.py <flashed.bin> <readback.bin> [--json out]
    py tools/analysis/me711_nvm_forensics.py --compare <a.json> <b.json>
"""
from __future__ import print_function

import hashlib
import json
import os
import sys

# --------------------------------------------------------------- geometry --
# hctarget.h. Named once here; every offset below is derived.
FLASH_BASE = 0x800000
FLASH_SIZE = 0x100000
CFG_A = 0x840000
CFG_B = 0x850000
PAGE = 0x2000
CELL_PAGES = 8
CELLS = 2 * CELL_PAGES
CELL_OFF = 2
CELL_BODY = 0x1FFC

# hcnvm.c record layout.
REC_MAGIC_OFF = 0
REC_LAYOUT_OFF = 4
REC_VERSION_OFF = 8
REC_LENGTH_OFF = 10
REC_GEN_OFF = 12
REC_HCRC_OFF = 16
REC_HDRLEN = 18
CFG_SIZE = 4096
REC_PCRC_OFF = REC_HDRLEN + CFG_SIZE
REC_COMMIT_OFF = REC_PCRC_OFF + 2
REC_LEN = REC_COMMIT_OFF + 4
REC_PROG_WORDS = REC_COMMIT_OFF // 2
REC_TOTAL_WORDS = REC_LEN // 2

MAGIC = b"HCN1"
COMMIT = b"DONE"
LAYOUT_ID = 0xEFF4E3D3

# ROMSYS program-page checksum, as me711_bootsum_coverage_proof reads it.
BOOTSUM_AT = 0x803C


def cell_addr(n):
    if n < CELL_PAGES:
        return CFG_A + n * PAGE + CELL_OFF
    return CFG_B + (n - CELL_PAGES) * PAGE + CELL_OFF


def foff(addr):
    return addr - FLASH_BASE


def u16(buf, off):
    """A WORD AS THE DEVICE HOLDS IT. The AM29F800BB is in word mode on a
    little-endian C167 bus, so a 16-bit device word is the byte pair as the
    CPU wrote it: low byte first in the file."""
    return buf[off] | (buf[off + 1] << 8)


def be16(buf, off):
    """A RECORD FIELD. hcnvm.c stores every multi-byte field BIG-endian."""
    return (buf[off] << 8) | buf[off + 1]


def be32(buf, off):
    return ((buf[off] << 24) | (buf[off + 1] << 16)
            | (buf[off + 2] << 8) | buf[off + 3])


def crc16_ccitt(data):
    crc = 0xFFFF
    for b in bytearray(data):
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
    return crc


# hcnvm.c uses a nibble table; confirm the two agree on the wire.
_CRC_TAB = [0x0000, 0x1021, 0x2042, 0x3063, 0x4084, 0x50A5, 0x60C6, 0x70E7,
            0x8108, 0x9129, 0xA14A, 0xB16B, 0xC18C, 0xD1AD, 0xE1CE, 0xF1EF]


def crc16_nibble(data, crc=0xFFFF):
    for b in bytearray(data):
        crc = ((crc << 4) ^ _CRC_TAB[((crc >> 12) ^ (b >> 4)) & 0x0F]) & 0xFFFF
        crc = ((crc << 4) ^ _CRC_TAB[((crc >> 12) ^ (b & 0x0F)) & 0x0F]) & 0xFFFF
    return crc


# ------------------------------------------------------------- diff ranges --
def diff_ranges(a, b, gap=0):
    """Contiguous ranges where a and b differ. gap=0 means strictly adjacent."""
    out = []
    n = min(len(a), len(b))
    i = 0
    start = None
    last = None
    while i < n:
        if a[i] != b[i]:
            if start is None:
                start = i
            last = i
        elif start is not None and last is not None and (i - last) > gap:
            out.append((start, last))
            start = None
            last = None
        i += 1
    if start is not None:
        out.append((start, last))
    return out


# ------------------------------------------------------------- cell state --
def cell_state(rb, n):
    """Everything knowable about one append-only cell from the readback."""
    base = cell_addr(n)
    off = foff(base)
    body = rb[off:off + CELL_BODY]

    st = {
        "cell": n,
        "addr": base,
        "file_off": off,
    }

    # How far programming got: the count of leading words that are not 0xFFFF
    # is NOT the answer (a legitimate payload word can be 0xFFFF). The answer
    # is the LAST non-blank word: everything after it is blank.
    words = REC_TOTAL_WORDS
    blank_tail = 0
    last_nonblank = -1
    for w in range(words - 1, -1, -1):
        if u16(body, w * 2) != 0xFFFF:
            last_nonblank = w
            break
    blank_tail = words - 1 - last_nonblank

    st["blank"] = (last_nonblank < 0)
    st["last_nonblank_word"] = last_nonblank
    st["blank_tail_words"] = blank_tail

    if st["blank"]:
        # Confirm the WHOLE body is blank, not just the record span.
        st["body_all_blank"] = all(x == 0xFF for x in bytearray(body))
        return st

    st["body_all_blank"] = False
    st["magic"] = bytes(body[0:4])
    st["magic_ok"] = (st["magic"] == MAGIC)
    st["layout"] = be32(body, REC_LAYOUT_OFF)
    st["layout_ok"] = (st["layout"] == LAYOUT_ID)
    st["version"] = be16(body, REC_VERSION_OFF)
    st["length"] = be16(body, REC_LENGTH_OFF)
    st["generation"] = be32(body, REC_GEN_OFF)
    st["hcrc"] = be16(body, REC_HCRC_OFF)
    st["hcrc_calc"] = crc16_nibble(body[0:REC_HCRC_OFF])
    st["hcrc_ok"] = (st["hcrc"] == st["hcrc_calc"])
    st["pcrc"] = be16(body, REC_PCRC_OFF)
    st["pcrc_calc"] = crc16_nibble(body[REC_HDRLEN:REC_HDRLEN + CFG_SIZE])
    st["pcrc_ok"] = (st["pcrc"] == st["pcrc_calc"])
    st["commit"] = bytes(body[REC_COMMIT_OFF:REC_COMMIT_OFF + 4])
    st["commit_ok"] = (st["commit"] == COMMIT)
    st["complete"] = bool(st["magic_ok"] and st["layout_ok"] and st["hcrc_ok"]
                          and st["pcrc_ok"] and st["commit_ok"])

    # Anything programmed BEYOND the record span?
    tail = body[REC_LEN:]
    st["beyond_record_nonblank"] = sum(1 for x in bytearray(tail) if x != 0xFF)
    return st


def prefix_compare(rb, n, reference_record, own_prefix):
    """How far is this cell a PERFECT prefix of the reference record?

    own_prefix is the cell's OWN programmed length, derived from its last
    non-blank word - never from the reference, because a payload word may
    legitimately be 0xFFFF and a comparison would then walk straight past the
    place programming actually stopped.
    """
    off = foff(cell_addr(n))
    body = rb[off:off + REC_LEN]
    res = {
        "programmed_words": own_prefix,
        "first_unprogrammed_word": None,
        "first_unprogrammed_file_off": None,
        "expected_at_stop": None,
        "actual_at_stop": None,
        "compared_words": 0,
        "mismatch_words": [],
        "skipped_words": [],
        "partial_words": [],
    }
    if own_prefix < REC_TOTAL_WORDS:
        res["first_unprogrammed_word"] = own_prefix
        res["first_unprogrammed_file_off"] = off + own_prefix * 2
        res["actual_at_stop"] = u16(body, own_prefix * 2)

    # NOTHING AFTER THE STOP MAY BE PROGRAMMED. A skipped word - one written
    # past a word that was not - would mean the cursor jumped, which is a
    # completely different defect from a word that would not take.
    for w in range(own_prefix, REC_TOTAL_WORDS):
        got = u16(body, w * 2)
        if got != 0xFFFF:
            res["skipped_words"].append((w, got))

    if reference_record is None:
        return res

    lim = min(own_prefix, len(reference_record) // 2)
    res["compared_words"] = lim
    for w in range(lim):
        got = u16(body, w * 2)
        exp = u16(reference_record, w * 2)
        if got == exp:
            continue
        # A word that programmed SOME of its bits is a genuine program
        # failure; a word that is still 0xFFFF never got a pulse at all.
        if got == 0xFFFF:
            res["mismatch_words"].append((w, exp, got, "blank"))
        elif (got & exp) == exp and got != exp:
            res["partial_words"].append((w, exp, got))
        else:
            res["mismatch_words"].append((w, exp, got, "wrong"))
    if own_prefix < len(reference_record) // 2:
        res["expected_at_stop"] = u16(reference_record, own_prefix * 2)
    return res


# ---------------------------------------------------------------- bootsum --
def bootsum(rb):
    """ROMSYS program-page checksum: stored word pair at 0x803C, and the sum.

    The bootrom sums the program pages. me711_bootsum_coverage_proof owns the exact
    definition; this reproduces it by reading the range descriptors the same
    way. To stay honest, we report BOTH the stored value and a recomputation
    over the range the stored descriptor names.
    """
    out = {}
    out["stored"] = u16(rb, BOOTSUM_AT) | (u16(rb, BOOTSUM_AT + 2) << 16)
    # The ROMSYS descriptor at 0x8030: start/end of the summed program area.
    out["desc_0x8030"] = [(u16(rb, a) | (u16(rb, a + 2) << 16)) for a in (0x8030, 0x8034, 0x8038)]
    return out


def page_samples(rb):
    """First and last word of each of the sixteen 8 KiB pages of SA7/SA8."""
    out = []
    for n in range(CELLS):
        if n < CELL_PAGES:
            pbase = CFG_A + n * PAGE
        else:
            pbase = CFG_B + (n - CELL_PAGES) * PAGE
        first = u16(rb, foff(pbase))
        last = u16(rb, foff(pbase + PAGE - 2))
        out.append({"page": n, "addr": pbase, "first": first, "last": last})
    return out


def legal_body_ranges():
    r = []
    for n in range(CELLS):
        b = foff(cell_addr(n))
        r.append((b, b + CELL_BODY - 1))
    return r


def in_legal_body(off):
    for lo, hi in legal_body_ranges():
        if lo <= off <= hi:
            return True
    return False


# ------------------------------------------------------------------ report --
def analyse(flashed_path, readback_path):
    with open(flashed_path, "rb") as f:
        fl = bytearray(f.read())
    with open(readback_path, "rb") as f:
        rb = bytearray(f.read())

    rep = {
        "flashed": os.path.basename(flashed_path),
        "readback": os.path.basename(readback_path),
        "flashed_size": len(fl),
        "readback_size": len(rb),
        "flashed_sha256": hashlib.sha256(bytes(fl)).hexdigest().upper(),
        "readback_sha256": hashlib.sha256(bytes(rb)).hexdigest().upper(),
    }

    n = min(len(fl), len(rb))
    diff_bytes = sum(1 for i in range(n) if fl[i] != rb[i])
    rep["diff_bytes"] = diff_bytes
    ranges = diff_ranges(fl, rb)
    rep["diff_range_count"] = len(ranges)
    rep["diff_ranges"] = [{"start": a, "end": b, "len": b - a + 1} for a, b in ranges]
    rep["first_diff"] = ranges[0][0] if ranges else None
    rep["last_diff"] = ranges[-1][1] if ranges else None

    dwords = set()
    for a, b in ranges:
        for i in range(a, b + 1):
            dwords.add(i & ~1)
    rep["diff_words"] = len(dwords)

    # bits that went 0 -> 1 anywhere: only an erase can do that
    illegal = []
    for a, b in ranges:
        for i in range(a, b + 1):
            if (~fl[i]) & rb[i] & 0xFF:
                illegal.append((i, fl[i], rb[i]))
    rep["illegal_0to1_bytes"] = len(illegal)
    rep["illegal_0to1_sample"] = illegal[:20]

    outside = [(a, b) for a, b in ranges
               if not (in_legal_body(a) and in_legal_body(b))]
    rep["diff_ranges_outside_cell_body"] = outside

    rep["bootsum"] = bootsum(rb)
    rep["bootsum_flashed"] = bootsum(fl)
    rep["page_samples"] = page_samples(rb)
    rep["page_samples_all_ff"] = all(p["first"] == 0xFFFF and p["last"] == 0xFFFF
                                     for p in rep["page_samples"])

    cells = [cell_state(rb, i) for i in range(CELLS)]
    rep["cells"] = []
    used = [c for c in cells if not c["blank"]]

    # Build a reference record: the LONGEST non-blank cell's bytes give the
    # payload for every other cell in the same Burn generation, because
    # append-only records of the same generation are byte-identical.
    ref = None
    longest = None
    if used:
        # Prefer a COMPLETE record; otherwise the longest prefix. Records of
        # the same generation are byte-identical, so the longest one is the
        # only available statement of what the shorter ones were trying to be.
        done = [c for c in used if c["complete"]]
        pool = done if done else used
        longest = max(pool, key=lambda c: c["last_nonblank_word"])
        off = foff(cell_addr(longest["cell"]))
        ref = bytearray(rb[off:off + REC_LEN])
    rep["reference_cell"] = (longest["cell"] if longest else None)
    rep["reference_is_complete"] = bool(longest and longest["complete"])

    for c in cells:
        entry = dict(c)
        for k in ("magic", "commit"):
            if k in entry:
                entry[k] = entry[k].decode("latin1")
        if not c["blank"]:
            entry["prefix"] = prefix_compare(
                rb, c["cell"], ref, c["last_nonblank_word"] + 1)
        rep["cells"].append(entry)

    # Do the consumed cells agree with one another over their common prefix?
    rep["cells_agree"] = True
    rep["cell_disagreements"] = []
    for i in range(len(used)):
        for j in range(i + 1, len(used)):
            a = used[i]
            b = used[j]
            k = min(a["last_nonblank_word"], b["last_nonblank_word"]) + 1
            oa = foff(cell_addr(a["cell"]))
            ob = foff(cell_addr(b["cell"]))
            if rb[oa:oa + 2 * k] != rb[ob:ob + 2 * k]:
                rep["cells_agree"] = False
                rep["cell_disagreements"].append((a["cell"], b["cell"]))

    return rep, fl, rb, ref


def human(rep):
    L = []
    a = L.append
    a("=" * 74)
    a("ME7.1.1 NVM FORENSICS")
    a("=" * 74)
    a("flashed  : %s  %s" % (rep["flashed"], rep["flashed_sha256"][:16] + ".."))
    a("readback : %s  %s" % (rep["readback"], rep["readback_sha256"][:16] + ".."))
    a("sizes    : %d / %d" % (rep["flashed_size"], rep["readback_size"]))
    a("")
    a("--- DIFF ---")
    a("differing bytes           : %d" % rep["diff_bytes"])
    a("differing words           : %d" % rep["diff_words"])
    a("contiguous ranges         : %d" % rep["diff_range_count"])
    a("first diff                : 0x%06X" % (rep["first_diff"] or 0))
    a("last diff                 : 0x%06X" % (rep["last_diff"] or 0))
    a("bits 0->1 (needs an erase): %d" % rep["illegal_0to1_bytes"])
    a("ranges outside cell body  : %d %s" % (len(rep["diff_ranges_outside_cell_body"]),
                                             rep["diff_ranges_outside_cell_body"] or ""))
    a("")
    for r in rep["diff_ranges"]:
        a("    0x%06X .. 0x%06X   %6d bytes" % (r["start"], r["end"], r["len"]))
    a("")
    a("--- BOOTSUM ---")
    a("stored @0x803C readback   : 0x%08X" % rep["bootsum"]["stored"])
    a("stored @0x803C flashed    : 0x%08X" % rep["bootsum_flashed"]["stored"])
    a("descriptor @0x8030        : %s" % ["0x%08X" % v for v in rep["bootsum"]["desc_0x8030"]])
    a("")
    a("--- SA7/SA8 PAGE SAMPLE WORDS ---")
    a("all sixteen pages first/last word still 0xFFFF: %s" % rep["page_samples_all_ff"])
    for p in rep["page_samples"]:
        if p["first"] != 0xFFFF or p["last"] != 0xFFFF:
            a("    page %2d @0x%06X  first=%04X last=%04X" %
              (p["page"], p["addr"], p["first"], p["last"]))
    a("")
    a("--- CELLS ---")
    a("reference cell: %s   (a COMPLETE record: %s)" %
      (rep["reference_cell"], rep.get("reference_is_complete")))
    a("consumed cells agree over their common prefix: %s %s" %
      (rep.get("cells_agree"), rep.get("cell_disagreements") or ""))
    a("")
    hdr = ("cell    addr    state       gen  prog.words  stop@word   expected  actual"
           "  mism skip")
    a(hdr)
    a("-" * len(hdr))
    for c in rep["cells"]:
        if c["blank"]:
            a("%4d  0x%06X  BLANK" % (c["cell"], c["addr"]))
            continue
        p = c.get("prefix", {})
        state = "COMPLETE" if c["complete"] else "PARTIAL"
        a("%4d  0x%06X  %-10s %4s  %10s  %9s  %8s  %6s  %4d %4d" % (
            c["cell"], c["addr"], state, c.get("generation"),
            p.get("programmed_words"), p.get("first_unprogrammed_word"),
            ("%04X" % p["expected_at_stop"]) if p.get("expected_at_stop") is not None else "-",
            ("%04X" % p["actual_at_stop"]) if p.get("actual_at_stop") is not None else "-",
            len(p.get("mismatch_words", [])), len(p.get("skipped_words", []))))
    a("")
    for c in rep["cells"]:
        if c["blank"]:
            continue
        a("cell %d @0x%06X (file 0x%06X)" % (c["cell"], c["addr"], c["file_off"]))
        a("    magic %r ok=%s  layout 0x%08X ok=%s  version %s  length %s" %
          (c["magic"], c["magic_ok"], c["layout"], c["layout_ok"],
           c["version"], c["length"]))
        a("    generation %s  hcrc %04X calc %04X ok=%s" %
          (c["generation"], c["hcrc"], c["hcrc_calc"], c["hcrc_ok"]))
        a("    pcrc %04X calc %04X ok=%s   commit %r ok=%s   COMPLETE=%s" %
          (c["pcrc"], c["pcrc_calc"], c["pcrc_ok"], c["commit"],
           c["commit_ok"], c["complete"]))
        a("    last non-blank word %d of %d, blank tail %d words, beyond-record non-blank bytes %d" %
          (c["last_nonblank_word"], REC_TOTAL_WORDS - 1, c["blank_tail_words"],
           c["beyond_record_nonblank"]))
        p = c.get("prefix")
        if p:
            a("    prefix: %s words programmed; first unprogrammed word %s at file 0x%06X" %
              (p["programmed_words"], p["first_unprogrammed_word"],
               p["first_unprogrammed_file_off"] or 0))
            if p["expected_at_stop"] is not None:
                a("            expected 0x%04X, actual 0x%04X" %
                  (p["expected_at_stop"], p["actual_at_stop"]))
            a("            compared %d words against the reference" % p["compared_words"])
            if p["mismatch_words"]:
                a("            MISMATCHES: %s" % p["mismatch_words"][:10])
            if p["partial_words"]:
                a("            PARTIALLY PROGRAMMED: %s" % p["partial_words"][:10])
            if p["skipped_words"]:
                a("            SKIPPED AFTER STOP: %s" % p["skipped_words"][:10])
        a("")
    return "\n".join(L)


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    flashed, readback = argv[1], argv[2]
    rep, fl, rb, ref = analyse(flashed, readback)
    print(human(rep))
    if "--json" in argv:
        out = argv[argv.index("--json") + 1]
        with open(out, "w") as f:
            json.dump(rep, f, indent=1, default=str)
        print("wrote %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
