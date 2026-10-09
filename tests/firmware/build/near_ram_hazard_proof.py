#!/usr/bin/env python3
r"""
near_ram_hazard_proof.py - no ordinary C variable may be allocated on top of a
C167 register, and no data segment may even SPAN one.

    py tests\firmware\build\near_ram_hazard_proof.py

WHY THIS GATE EXISTS.

The C167's address space is not uniformly RAM, and the parts that are not RAM
sit inside or beside the windows the compiler allocates near data from. L166
protects exactly one of them by itself - the GPR bank, because
?C_MAINREGISTERS is a REGDEF segment it can see. Everything else is protected
only if the linker script's CLASSES ranges say so.

WHAT THAT COST BEFORE THIS FILE EXISTED. hc_asic_state was allocated at
0x00FCE2, which is DSTP0. asic_start_transfer() programs the PEC destination
pointer before every SSC block transfer, so every transfer overwrote the ASIC
state machine's own state with the low byte of a buffer address: 0xF0B0 ->
state 176, a value no case in the switch matches. The startup handshake could
never reach its runtime state. me711_boot_test lost six checks to it, and every
symptom pointed somewhere else - at the ASIC, at checksum rejection, at the
serial path. Two plausible theories were tried and disproven by measurement
before anybody read the linker map.

The defect was OLDER than the image that exposed it. V26, the only physically
verified image, places nothing in that window. V27A already placed sixteen
engine variables there and passed every gate it had, because silently
corrupting eng_ti_us is invisible to a suite that never runs an engine. That is
precisely why this gate checks ADDRESS RANGES and not "did some other test go
green": the other test only noticed by luck.

WHERE THE REGIONS COME FROM. They are PARSED OUT OF reg167.h at run time -
Infineon's own register header, in the M744 stand-alone ECU project  - not typed
in here. The architectural page bounds around those registers are stated below
with the evidence for each, and the gate re-checks every span against the
header on every run, so the list cannot rot silently.

WHAT IT READS. The .M66 map L166 itself produced. This is evidence about the
real image, not a simulation.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths as HCP  # noqa: E402
REG167 = HCP.REG167        # the toolchain header the ME7.1.1 build includes

# ---------------------------------------------------------------- the regions
#
# (first, last, name, why this whole span and not only the addresses reg167.h
# happens to name).
#
# The spans are ARCHITECTURAL PAGES, not the min/max of the parsed addresses.
# On the C166 core the SFR and ESFR areas are 512-byte pages, and locations
# inside them that no register uses are RESERVED, not RAM. Reserving the page
# is therefore not over-reservation, it is the hardware. Each span is checked
# against what reg167.h actually contains before anything else runs.
ARCH_REGIONS = [
    (0xF000, 0xF1FF, "ESFR page",
     "512-byte extended-SFR page; reg167.h spreads DP0L..CC31IC across it"),
    (0xFCE0, 0xFCFF, "PEC pointer file SRCP0..DSTP7",
     "16 word registers, reg167.h SRCP0=0xFCE0 .. DSTP7=0xFCFE"),
    (0xFE00, 0xFFFF, "SFR page",
     "512-byte SFR page; reg167.h spreads DPP0..the last SFR across it"),
]

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def reg167_addresses():
    """Every register address reg167.h names. The header is the authority."""
    if not REG167.exists():
        return None
    src = REG167.read_text(errors="replace")
    out = {}
    for m in re.finditer(
            r"^\s*(?:sfr|sfrbit|bit)\s+(\w+)\s*=\s*0x([0-9A-Fa-f]{4})",
            src, re.M):
        out.setdefault(int(m.group(2), 16), m.group(1))
    for m in re.finditer(
            r"^\s*#define\s+(\w+)\s*\(\*\(\(.*?\)\s*0x([0-9A-Fa-f]{4})\)\)",
            src, re.M):
        out.setdefault(int(m.group(2), 16), m.group(1))
    return out


# ------------------------------------------------------------------- the maps
TARGETS = [
    ("ME7.1.1 bosch_me711",
     "firmware/targets/me711/build/hani_me711.M66",
     "firmware/targets/me711/linker_me711.lnp"),
]

# A KNOWN, MEASURED, ACCEPTED overlap. Printed in full and never hidden; it
# just does not fail the gate, because a permanently red gate stops anybody
# noticing the NEXT regression. An entry must say what makes the overlap
# harmless ON THAT TARGET, and the gate re-verifies that reason where it can.
ACCEPTED: dict = {}   # the ME7.5 waiver left with the ME7.5 target (2026-10)

# The map lists a symbol twice: in the segment listing, and in the PUBLICS
# table where the column order puts the literal word PUBLIC where the name
# goes. Accept both shapes and keep the real name.
VAR = re.compile(
    r"^\s*([0-9A-F]{6})H\s+(?:PUBLIC\s+VAR\s+\S+\s+\S+\s+(\w+)"
    r"|(\w+)\s+VAR\s)", re.M)

# A located segment line: start, end, size, kind, ... , name last.
SEG = re.compile(
    r"^\s*([0-9A-F]{6})H\s+([0-9A-F]{6})H\s+([0-9A-F]{6})H\s+(\w+)\s.*?(\S+)\s*$",
    re.M)

CLASSRANGE = re.compile(r"^\s*(NDATA0?|SDATA0?|IDATA0?)\s*\(([^)]*)\)", re.M)


def variables(text):
    out = set()
    for m in VAR.finditer(text):
        name = m.group(2) or m.group(3)
        if name and name != "PUBLIC":
            out.add((int(m.group(1), 16), name))
    return out


def data_segments(text):
    out = []
    for m in SEG.finditer(text):
        if m.group(4) != "DATA":
            continue
        out.append((int(m.group(1), 16), int(m.group(2), 16), m.group(5)))
    return out


def declared_ranges(lnp_text):
    out = []
    for m in CLASSRANGE.finditer(lnp_text):
        for part in m.group(2).split(","):
            r = re.match(r"\s*0x([0-9A-Fa-f]+)\s*-\s*0x([0-9A-Fa-f]+)\s*$",
                         part)
            if r:
                out.append((int(r.group(1), 16), int(r.group(2), 16)))
    return sorted(set(out))


def overlap(a0, a1, b0, b1):
    return not (a1 < b0 or a0 > b1)


XRAM_RESERVE = 64     # bytes; docs/ARCHITECTURE.md


def near_ram_headroom():
    """How much near RAM is left, and whether that is a healthy amount.

    A BUILD WITH ONE BYTE LEFT IS NOT AS HEALTHY AS ONE WITH HUNDREDS, and
    until this check existed nothing said so - the linker is happy either way.
    Near RAM on this part is 1792 bytes, of which 32 are the GPR bank and 32
    the PEC pointer file, leaving 1728 for everything.

    WHERE THE TWO THRESHOLDS COME FROM. They are sized against the subsystems
    that still have to land, estimated from the ones already here:

        injector + ignition runtime   8 cylinders of slot, deadline and state,
                                      about 96 bytes on the pattern hcsched_dry
                                      already uses for its event table
        DBW critical state            two tracks, target, error, fault latch,
                                      about 30
        lambda controllers            two of them, about 40
        knock runtime                 windows and per-cylinder retard, about 30

    That is roughly 200 bytes of planned work, so:

        FAIL below 192 bytes   the engineering reserve is exhausted
        FAIL below  64 bytes   the next single module does not fit, and a
                               relink that happens to grow will silently start
                               pushing data into whatever is beyond 0xFDFF

    These are engineering reserves, not architectural limits, and they are
    stated here so that raising one is a visible decision rather than a quiet
    edit. User/system stacks are separately bounded against their 512/634-byte
    reservations by the static and measured stack gates.
    """
    print("")
    print("--- near RAM headroom ---")
    mp = ROOT / TARGETS[0][1]
    if not mp.exists():
        check("the ME7.1.1 map exists to measure headroom from", False, "")
        return
    text = mp.read_text(errors="replace")
    # 2026-10-07: COUNT THE HOLES, NOT ONLY THE TOP. Since the stacks moved
    # (0xF380/0xF580) the near-data class is three ranges (linker_me711.lnp
    # NDATA0) and data is freed inside them (register banks shared, cold data
    # moved to XRAM). Free = every byte of those ranges no located DATA
    # section (register banks included) and no architectural region covers.
    lnp = (ROOT / "firmware/targets/me711/linker_me711.lnp").read_text(errors="replace")
    ranges = []
    for m in CLASSRANGE.finditer(lnp):
        if m.group(1) != "NDATA0":
            continue
        for part in m.group(2).split(","):
            r = re.match(r"\s*0x([0-9A-Fa-f]+)\s*-\s*0x([0-9A-Fa-f]+)\s*$", part)
            if r:
                ranges.append((int(r.group(1), 16), int(r.group(2), 16)))
    used = set()
    for m in re.finditer(r"^([0-9A-F]{6})H\s+([0-9A-F]{6})H\s+[0-9A-F]{6}H\s+DATA\s",
                         text, re.M):
        lo, hi = int(m.group(1), 16), int(m.group(2), 16)
        if hi <= 0xFFFF:
            used.update(range(lo, hi + 1))
    if not ranges:
        check("the NDATA0 class ranges were located", False, "none found")
        return
    free = 0
    for lo, hi in ranges:
        hole = sum(1 for a in range(lo, hi + 1) if a not in used
                   and not any(l2 <= a <= h2 for l2, h2, _w, _y in ARCH_REGIONS))
        print("    NDATA0 0x%04X-0x%04X: %d bytes free" % (lo, hi, hole))
        free += hole

    # XRAM (cold modules' near data, RENAMECLASS NDATA0=XNDATA0): its own
    # floor, so the next cold module fails here instead of an L5 in the link.
    xr = []
    for m in re.finditer(r"XNDATA0\s*\(([^)]*)\)", lnp):
        for part in m.group(1).split(","):
            r = re.match(r"\s*0x([0-9A-Fa-f]+)\s*-\s*0x([0-9A-Fa-f]+)\s*$", part)
            if r:
                xr.append((int(r.group(1), 16), int(r.group(2), 16)))
    xfree = sum(1 for lo, hi in xr for a in range(lo, hi + 1) if a not in used)
    print("    XNDATA0 %s: %d bytes free" % (", ".join("0x%04X-0x%04X" % r for r in xr), xfree))
    check("XRAM keeps its reserve for the next cold module", bool(xr) and xfree >= XRAM_RESERVE,
          "%d bytes free - reserve is %d" % (xfree, XRAM_RESERVE))
    check("near RAM has not run out", free >= 64,
          "%d bytes free - hard floor is 64" % free)
    check("and it still has room for the planned engine subsystems",
          free >= 192,
          "%d bytes free - engineering reserve is 192" % free)


def external_sram_map():
    """The 32 KB external SRAM is carved into named regions by hand, in
    hctarget.h, with no linker to catch a collision. Two regions that overlap
    would corrupt each other silently - and one of them holds the DESIRED
    configuration image, another the calibration page, another the flash
    buffer. Nothing checked this until now.

    The regions are PARSED from hctarget.h, so adding one puts it under the
    check automatically instead of needing a list here."""
    print("\n--- ME7.1.1 external SRAM region map (hctarget.h) ---")
    h = (ROOT / "firmware/targets/me711/hctarget.h").read_text(errors="replace")

    base = re.search(r"#define\s+TGT_EXTRAM_BASE\s+(0x[0-9A-Fa-f]+)", h)
    size = re.search(r"#define\s+TGT_EXTRAM_SIZE\s+(0x[0-9A-Fa-f]+)", h)
    if not (base and size):
        check("hctarget.h states the external SRAM base and size", False, "")
        return
    total = int(size.group(1), 16)

    starts, limits = {}, {}
    for m in re.finditer(
            r"#define\s+TGT_RAM_(\w+?)(_LIMIT)?\s+(0x[0-9A-Fa-f]+)uL", h):
        name, is_lim, val = m.group(1), m.group(2), int(m.group(3), 16)
        (limits if is_lim else starts)[name] = val

    regions = []
    for name, off in sorted(starts.items(), key=lambda kv: kv[1]):
        lim = limits.get(name)
        if lim is None:
            check("region TGT_RAM_%s has a _LIMIT" % name, False,
                  "no size - it cannot be checked for overlap")
            continue
        regions.append((off, off + lim - 1, name))

    for a, b, n in regions:
        print("    0x%04X-0x%04X  %5d B  %s" % (a, b, b - a + 1, n))

    clashes = []
    for i, (a0, a1, n0) in enumerate(regions):
        for b0, b1, n1 in regions[i + 1:]:
            if overlap(a0, a1, b0, b1):
                clashes.append("%s/%s" % (n0, n1))
    check("no two external SRAM regions overlap", not clashes,
          "%d regions, all disjoint" % len(regions) if not clashes
          else ", ".join(clashes))

    over = [n for _a, b, n in regions if b >= total]
    check("every region fits inside the %d KB chip" % (total // 1024),
          not over,
          "highest ends at 0x%04X of 0x%04X" % (max(b for _a, b, _n in regions),
                                                total)
          if not over else ", ".join(over))

    # The two that matter most for Project 2A: the DESIRED image and the
    # calibration page it is copied from must be separate, or the state
    # machine has no state to speak of.
    if "CFG" in starts and "CFGDESIRED" in starts:
        a0, a1 = starts["CFG"], starts["CFG"] + limits["CFG"] - 1
        b0, b1 = (starts["CFGDESIRED"],
                  starts["CFGDESIRED"] + limits["CFGDESIRED"] - 1)
        check("DESIRED and the ACTIVE calibration page are separate regions",
              not overlap(a0, a1, b0, b1),
              "ACTIVE 0x%04X-0x%04X, DESIRED 0x%04X-0x%04X"
              % (a0, a1, b0, b1))


# V77. The modules whose near data the linker places in the on-chip XRAM
# (build_me711.bat compiles them RENAMECLASS(NDATA0=XNDATA0)). A WHITELIST, so
# a hot module - the decoder, the scheduler, the HAL output route - cannot be
# moved out of IRAM by a one-word edit to the batch file without this gate
# saying so. linker_me711.lnp carries the argument for each property checked.
XRAM_NEAR_LO, XRAM_NEAR_HI = 0xE200, 0xE7FF
# V97: the class also has 0xE000-0xE09F (linker_me711.lnp); 0xE0A0-0xE0FF is
# kept for the OEM's K-line PEC receive ring (0xE0A2, hcpecrx_me711.c).
XRAM_NEAR_RANGES = ((0xE000, 0xE09F), (XRAM_NEAR_LO, XRAM_NEAR_HI))
PECRX_RESERVED = (0xE0A0, 0xE0FF)
XRAM_COLD_MODULES = {
    # 2026-10-07: the TunerStudio request ring, its indices and the catch-all
    # diary - written by the 1 ms tick and read by the main loop, background
    # data that cost 77 bytes of IRAM.
    "HCVEC_ME711",
    # V102: tooth profile reporting is task-only; capture/deadline ownership
    # remains near. These 15 bytes are profile status and publication clocks.
    "HCPROFILE711",
    "HCTS", "HCMAIN_ME711", "HCBENCH", "HCASICSTART", "HCASIC", "HCUMKOM",
    "HCFUELPUMP", "HCMAINRELAY", "HC_CONFIG_MANAGER", "HC_VALIDATION",
    # V79: the ASIC images, run-on, CJ120 and LSU state - main loop and the
    # 10 ms frame build, never the tooth ISR.
    "HCIO711",
    # V94: the KWP vehicle entry - the 5-baud decoder and the KWP core run
    # from the main loop at millisecond granularity, never per tooth.
    "HCKWP_ME711", "HCKLINE",
    # V97: the wideband core's two-bank step (hcwb_pair_step's static input
    # block) - called only from hc_io_lambda_service in the main loop.
    "HCWB",
    # V97: the cam pattern core and its two instances - trg_service in the
    # main loop, never the capture ISRs (they only fill a ring).
    "HCCAM",
    "HCLDR",
    "HCBOOST711",
    "HCIDLE",
    "HCIDLE711",
    "HCDTC",
    "HCDTC711",
    "HCLIMP",
    "HCLIMP711",
    # Main-loop event exporter; never called from capture/compare ISRs.
    "HCEVLOG711",
    # Only cfg_rev is static near state. CC16 ISR shares HC_KN711 in
    # explicit external SRAM, not this module's ?ND0? segment.
    "HCKNOCK711",
    # Active injector tickets are bounded word accesses in on-chip XRAM.
    "HCDEADLINE_PLAN711",
}


def xram_near_data():
    """Cold near data in XRAM: inside 0xE200-0xE7FF, clear of the ASIC PEC
    frame, only whitelisted modules, and the user stack where the linker pins it."""
    print("\n--- V77: cold near data in the on-chip XRAM ---")
    mp = ROOT / TARGETS[0][1]
    if not mp.exists():
        return
    text = mp.read_text(errors="replace")
    tgt = (ROOT / "firmware/targets/me711/hctarget.h"
           ).read_text(errors="replace")
    fr = int(re.search(r"#define\s+TGT_ASIC_FRAME\s+0x([0-9A-Fa-f]+)", tgt)
             .group(1), 16)
    frn = int(re.search(r"#define\s+TGT_ASIC_FRAME_MAX\s+(\d+)", tgt).group(1))
    segs = [s for s in data_segments(text) if 0xE000 <= s[0] <= 0xE7FF]
    names = [n for _a, _b, n in segs]
    check("every XRAM data segment lies inside %s"
          % " or ".join("0x%04X-0x%04X" % r for r in XRAM_NEAR_RANGES),
          all(any(lo <= a and b <= hi for lo, hi in XRAM_NEAR_RANGES)
              for a, b, _n in segs),
          "%d segments, %d bytes" % (len(segs),
                                     sum(b - a + 1 for a, b, _n in segs)))
    check("and none meets the PEC receive ring reservation 0x%04X-0x%04X"
          % PECRX_RESERVED,
          not any(overlap(a, b, PECRX_RESERVED[0], PECRX_RESERVED[1])
                  for a, b, _n in segs), "")
    check("and none meets the ASIC PEC frame 0x%04X-0x%04X"
          % (fr, fr + frn - 1),
          not any(overlap(a, b, fr, fr + frn - 1) for a, b, _n in segs), "")
    alien = [n for n in names
             if n.replace("?ND0?", "") not in XRAM_COLD_MODULES]
    check("only the whitelisted modules live there", not alien,
          ", ".join(alien) if alien else ", ".join(
              n.replace("?ND0?", "") for n in names))
    stk = re.search(r"^([0-9A-F]{6})H\s+[0-9A-F]{6}H\s+[0-9A-F]+H\s+DATA.*"
                    r"\?C_USERSTACK", text, re.M)
    # 2026-10-06: the stack moved 0xF700 -> 0xF380 (512 B, guard band below
    # it, hcsafety.h). The invariant is that it sits where the linker script
    # PINS it, not a typed address.
    lnp = (ROOT / "firmware/targets/me711/linker_me711.lnp").read_text(errors="replace")
    pin = re.search(r"\?C_USERSTACK%NDATA\s*\((0x[0-9A-Fa-f]+)\)", lnp)
    want = int(pin.group(1), 16) if pin else None
    check("the user stack is where linker_me711.lnp pins it (0x%04X)" % (want or 0),
          stk is not None and want is not None and int(stk.group(1), 16) & 0xFFFF == want,
          "at 0x%s" % (stk.group(1) if stk else "?"))


def near_segments_do_not_overlap():
    """Two located DATA segments that overlap corrupt each other. L166 will not
    normally do this, but a hand-written CLASSES range with a typo can, and the
    consequence is indistinguishable from a wild pointer."""
    print("\n--- located data segments must not overlap each other ---")
    for label, map_rel, _lnp in TARGETS:
        mp = ROOT / map_rel
        if not mp.exists():
            continue
        segs = sorted(data_segments(mp.read_text(errors="replace")))
        clash = []
        for i, (a0, a1, n0) in enumerate(segs):
            for b0, b1, n1 in segs[i + 1:]:
                if overlap(a0, a1, b0, b1):
                    clash.append("%s/%s" % (n0, n1))
        check("%s: %d segments, none overlapping" % (label.split(" (")[0],
                                                     len(segs)),
              not clash, "disjoint" if not clash else ", ".join(clash[:3]))


def main() -> int:
    print("=== HaniCore - C167 near-memory hazard proof ===\n")

    regs = reg167_addresses()
    if regs is None:
        print("  reg167.h not found at %s" % REG167)
        print("  This gate DERIVES its regions from that header. Without it it")
        print("  has no authority, and saying so is better than inventing one.")
        return 1
    print("  authority  reg167.h: %d register addresses, 0x%04X..0x%04X\n"
          % (len(regs), min(regs), max(regs)))

    for lo, hi, what, _why in ARCH_REGIONS:
        inside = sorted(a for a in regs if lo <= a <= hi)
        check("reg167.h backs the %s span 0x%04X-0x%04X" % (what, lo, hi),
              len(inside) > 0,
              "%d registers, e.g. %s" % (
                  len(inside), ", ".join(regs[a] for a in inside[:3])))
    unclaimed = sorted(a for a in regs
                       if not any(lo <= a <= hi
                                  for lo, hi, _, _ in ARCH_REGIONS))
    check("every register reg167.h names falls inside a known span",
          not unclaimed,
          "all accounted for" if not unclaimed else
          ", ".join("%s@0x%04X" % (regs[a], a) for a in unclaimed[:6]))


    for label, map_rel, lnp_rel in TARGETS:
        mp, lnp = ROOT / map_rel, ROOT / lnp_rel
        print("\n--- %s" % label)
        if not mp.exists():
            print("    (not built: %s)" % map_rel)
            continue
        # A map is only as current as the last SUCCESSFUL link. Say when it was
        # made, so nobody reads a pass here as a statement about source that
        # has changed since - the ME7.5 full target, for one, does not
        # currently compile (m0_build\ADC.C wants NUM_ADC_CHANNELS, which is
        # M744 reference source and predates this work), so its map is older
        # than its sources and this line is the only warning of that.
        import datetime as _dt
        stamp = _dt.datetime.fromtimestamp(mp.stat().st_mtime)
        newest_src = 0.0
        for pat in ("*.c", "*.h", "*.a66", "*.lnp"):
            for f in (ROOT / Path(lnp_rel).parent).glob(pat):
                newest_src = max(newest_src, f.stat().st_mtime)
        stale = newest_src > mp.stat().st_mtime
        print("    map built %s%s" % (stamp.strftime("%Y-%m-%d %H:%M"),
                                      "   *** OLDER THAN ITS SOURCES ***"
                                      if stale else ""))
        text = mp.read_text(errors="replace")
        vs = variables(text)
        segs = data_segments(text)

        # The GPR bank is read FROM THE MAP, not assumed to be at 0xFC00: CP is
        # loaded from ?C_MAINREGISTERS and the linker is what places it.
        gpr = [(a, b) for a, b, n in segs if "MAINREGISTERS" in n]
        if gpr:
            g0, g1 = gpr[0]
            bad = sorted((a, n) for a, n in vs if g0 <= a <= g1)
            check("0x%04X-0x%04X GPR bank (located from the map)" % (g0, g1),
                  not bad,
                  "clear" if not bad else
                  ", ".join("%s@0x%04X" % (n, a) for a, n in bad[:5]))
        else:
            check("the map locates a GPR bank at all", False,
                  "no ?C_MAINREGISTERS segment found")

        for lo, hi, what, _why in ARCH_REGIONS:
            bad = sorted((a, n) for a, n in vs if lo <= a <= hi)
            waiver = ACCEPTED.get((mp.name, lo))
            detail = ("clear" if not bad else
                      ", ".join("%s@0x%04X" % (n, a) for a, n in bad[:6])
                      + (" (+%d more)" % (len(bad) - 6) if len(bad) > 6 else ""))
            if bad and waiver:
                print("  [KNOWN] 0x%04X-0x%04X %-40s %s" % (lo, hi, what, detail))
                for wl in waiver:
                    print("         %s" % wl)
                continue
            check("0x%04X-0x%04X %s" % (lo, hi, what), not bad, detail)

        # STRONGER THAN THE PER-VARIABLE CHECK. A named variable is not the
        # only thing a segment can hold; a segment that merely SPANS a register
        # region has put something there whether the map names it or not.
        for lo, hi, what, _why in ARCH_REGIONS:
            if ACCEPTED.get((mp.name, lo)):
                continue
            crossing = [(a, b, n) for a, b, n in segs
                        if "MAINREGISTERS" not in n and overlap(a, b, lo, hi)]
            check("  ...and no DATA segment spans 0x%04X-0x%04X" % (lo, hi),
                  not crossing,
                  "none" if not crossing else
                  ", ".join("%s 0x%04X-0x%04X" % (n, a, b)
                            for a, b, n in crossing[:3]))

        # A bad linker script is caught BEFORE a build happens to place
        # something in the hazardous window.
        if lnp.exists():
            rngs = declared_ranges(lnp.read_text(errors="replace"))
            offered = [(r, (lo, hi, what)) for r in rngs
                       for lo, hi, what, _ in ARCH_REGIONS
                       if overlap(r[0], r[1], lo, hi)]
            waived = any(ACCEPTED.get((mp.name, lo))
                         for _, (lo, _h, _w) in offered)
            detail = ("no class range offers register space" if not offered else
                      "; ".join("0x%04X-0x%04X covers %s" % (r[0], r[1], w)
                                for r, (_l, _h, w) in offered[:3]))
            if offered and waived:
                print("  [KNOWN] the linker script's class ranges  %s" % detail)
            else:
                check("the linker script's class ranges avoid register space",
                      not offered, detail)

    external_sram_map()
    near_segments_do_not_overlap()
    near_ram_headroom()
    xram_near_data()

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("\nORDINARY DATA IS ON, OR CAN REACH, A C167 REGISTER.\n"
              "Fix the CLASSES ranges in that target's linker script so the\n"
              "region is carved out, e.g.\n"
              "    NDATA0 (0xF700-0xFCDF, 0xFD00-0xFDFF)\n"
              "Do NOT 'fix' this by moving the variable - the next relink\n"
              "moves it back.")
        return 1
    print("NEAR RAM PROOF PASSES - no ordinary data sits on, or spans, a "
          "C167 register.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
