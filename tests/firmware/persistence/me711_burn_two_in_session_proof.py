#!/usr/bin/env python3
"""V40: TWO BURNS AND ORDINARY TRAFFIC IN ONE UNBROKEN ECU SESSION.

WHAT THIS EXISTS TO PROVE, AND WHY NOTHING ELSE PROVED IT
=========================================================

V39's Burn worked. It put the record in flash, it verified, and the bench
readback of a real ECU matched byte for byte. It also asserted SRST about
250 ms after the reply went out, so on the tuner's screen the ECU went
OFFLINE, TunerStudio reconnected, re-ran the signature handshake, reloaded the
controller settings and sometimes reported "Unable to get all pages".

So "SRST removed" is NOT the acceptance criterion. THE CRITERION IS THAT THE
SESSION SURVIVES THE BURN, and a session is not a single reply - it is a reply
followed by every request the tuner makes next. This gate drives ONE simulator
instance, with no reboot, no re-handshake and no rig surgery between steps:

    warm up -> edit -> BURN #1 -> V -> O -> R -> W -> BURN #2 -> R

and requires all nine to answer on the same CPU, plus the flash-level and
runtime-level facts each Burn is supposed to have produced.

IT CANNOT PASS VACUOUSLY. Every substantive claim is checked against the
modelled AM29F800BB inside the simulator rather than against source text:

  * fl_erases MUST BE EMPTY               - no runtime erase, at all
  * fl_programs MUST GROW BY THE RECORD   - a Burn that did nothing fails
  * fl_fetch_while_busy MUST BE ZERO      - no instruction fetched from the
                                            device while it was programming
  * the DONE marker must be the LAST      - the append-only commit contract
    thing written into the target cell
  * cell 0 must be byte-identical after   - the old record stays authoritative
    Burn #2 wrote cell 1
  * the two boot-checksum sample words    - the project rules protected words
    0x?1FFE / page+0 must stay 0xFFFF
  * the published generation must go 1, 2 LIVE, with no reboot in between

A trap of any kind, including SRST, fails the run outright.
"""
from __future__ import annotations

import binascii
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_heartbeat_gap_proof as HB  # noqa: E402
import me711_image as PI  # noqa: E402
import me711_ts_gap_proof as GAP  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]

# The append-only geometry, taken from the same constants me711_nvm_proof uses.
# GEOMETRY IS DERIVED - see tools/lib/me711_nvm_geometry.py. This line used to read
# 0x40000, 0x2000, 16, 2, 0x1FFC and V53 moved the store to SA9..SA18 with
# eighty cells, so it was checking the CODE sector for blank calibration cells.
from me711_nvm_geometry import GEO
CELL0, PAGE, CELLS = GEO.file_base, GEO.page, GEO.cells
OFF, BODY, REC_LEN = GEO.off, GEO.body, 4120
REC_WORDS = REC_LEN // 2

# The persistence test byte the operator card uses (Diagnostics -> Calibration
# storage -> "Persistence test byte (P3)"), read out of the shipped .ini rather
# than typed here, so a moved field fails the gate instead of testing nothing.
INI = ROOT / ("tunerstudio/hanicore_me711_%s.ini"
              % PI.STEM.replace("HaniCore_ME711_", ""))

# Output-channel offsets for the NVM block, likewise read from the .ini.
OCH_NAMES = ("nvmState", "nvmError", "nvmSource", "nvmGeneration",
             "nvmCommits", "nvmAttempts")

# The writer is linked in 8E:xxxx but executed from 38:6000.  C166 relative
# branches survive that copy unchanged; CADDR operands in CALLA/JMPA do not.
# This is intentionally checked against the runtime SRAM after Burn #1, not
# inferred from fl_prepare() source, because V42 once copied the bytes exactly
# and then executed a JMPA back-edge in the staging buffer.
WRITER_RT = 0x6000
WRITER_COPY = 1024

HCNV_ST_DONE = 5
HCNV_ERR_NONE = 0

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<62s} {detail}")
    if not ok:
        FAILS += 1


# ----------------------------------------------------------------- the wire
envelope = HB.envelope      # one definition: 16-bit length (see HB)


def find_reply(stream, start, matcher):
    """First CRC-valid reply envelope at or after `start`, and its end index."""
    for at in range(start, max(start, len(stream) - 6)):
        if stream[at] != 0:
            continue
        n = stream[at + 1]
        end = at + 2 + n + 4
        if end > len(stream):
            continue
        payload = stream[at + 2:at + 2 + n]
        got = int.from_bytes(stream[at + 2 + n:end], "big")
        if got == (binascii.crc32(payload) & 0xFFFFFFFF) and matcher(payload):
            return at, end, payload
    return None, None, None


# ------------------------------------------------------------- the .ini facts
def ini_offsets():
    text = INI.read_text(errors="replace")
    och = {}
    for m in re.finditer(r"^\s*(\w+)\s*=\s*scalar,\s*U16,\s*(\d+)", text, re.M):
        och[m.group(1)] = int(m.group(2))
    missing = [n for n in OCH_NAMES if n not in och]
    if missing:
        raise SystemExit(f"{INI.name} declares no U16 channel for {missing}")
    m = re.search(r"^\s*(\w*[Pp]3\w*|persistTestByte\w*)\s*=\s*scalar,\s*U08,"
                  r"\s*(\d+)", text, re.M)
    p3 = int(m.group(2)) if m else None
    if p3 is None:
        # Fall back to the documented operator-card field, but say so.
        p3 = 2427
    return och, p3


# ------------------------------------------------------------------ the flash
def cell_addr(i):
    return GEO.addr(i)


def cell_bytes(flash, i):
    a = cell_addr(i)
    return bytes(flash[a:a + REC_LEN])


def cell_blank(flash, i):
    a = cell_addr(i)
    return all(b == 0xFF for b in flash[a:a + BODY])


def cell_done(flash, i):
    return cell_bytes(flash, i)[-4:] == b"DONE"


def cell_gen(flash, i):
    a = cell_addr(i)
    return int.from_bytes(bytes(flash[a + 12:a + 16]), "big")


def symbol(name):
    map_path = PI.MAP
    match = re.search(r"^\s*([0-9A-F]{6})H\s+" + re.escape(name)
                      + r"\s+LABEL", map_path.read_text(), re.M)
    if not match:
        raise SystemExit("%s missing from %s" % (name, map_path.name))
    return int(match.group(1), 16)


def datum(name):
    match = re.search(r"^\s*([0-9A-F]{6})H\s+" + re.escape(name)
                      + r"\s+VAR", PI.MAP.read_text(), re.M)
    if not match:
        raise SystemExit("%s missing from %s" % (name, PI.MAP.name))
    return int(match.group(1), 16)


def relocated_writer(image):
    """Expected 1024-byte SRAM image and its documented CADDR rebases."""
    linked, end = symbol("hc_nvm_payload"), symbol("hc_nvm_payload_end")
    size = end - linked
    if not 0 < size <= WRITER_COPY:
        raise SystemExit("invalid linked writer span %d" % size)
    raw = bytearray(image[linked - 0x800000:linked - 0x800000 + WRITER_COPY])
    fixups = []
    i = 0
    while i < size:
        op = raw[i]
        n = 4 if (op & 0x0F) in (2, 3, 4, 5, 6, 7, 0x0A) else 2
        if i + n > size:
            raise SystemExit("writer instruction overruns its linked span")
        if op in (0xCA, 0xEA):
            target = raw[i + 2] | (raw[i + 3] << 8)
            if (linked & 0xFFFF) <= target < (end & 0xFFFF):
                rebased = WRITER_RT + target - (linked & 0xFFFF)
                raw[i + 2] = rebased & 0xFF
                raw[i + 3] = rebased >> 8
                fixups.append((i, op, target, rebased))
        i += n
    return linked, end, bytes(raw), fixups


def main():
    print("=== HaniCore Bosch ME7.1.1 - V40 resetless-Burn SESSION proof ===\n")
    print(f"  image  {PI.image().name}")
    print(f"  sha256 {PI.sha256()}")

    och, p3_off = ini_offsets()
    print(f"  .ini   nvmState @{och['nvmState']}, "
          f"persistence test byte @{p3_off}\n")

    # ---- one rig, one session, from here to the end of the function ----
    # V97: echo=True - THE K-LINE ALWAYS ECHOES. Since V94's
    # pipelined TX (hcts.c hcts_tx_end) a reply shorter than
    # HCTS_ECHO_LAG_MAX + 1 bytes waits for its echoes and drains them BY
    # COUNT, so on a rig that does not echo the host's NEXT request is
    # drained instead: this gate's Burn after a page write was eaten and
    # never answered (Tier 2, 2026-09-30). Not a firmware defect - no
    # K-line wiring fails to echo - so the rig models the wire.
    probe = HB.Rig(PI.image(), HB.ENTRY_CURRENT, HB.TICK_CURRENT,
                   echo=True, steps_per_tick=HB.STEPS_PER_TICK)
    probe.run(GAP.BOOT_WARMUP_STEPS)
    if len(probe.entries) < 2:
        raise SystemExit(
            "REGRESSION: warmup reached no usable hc_asic_start_service "
            "entries; every timing figure below would be vacuous")
    first, last = probe.entries[0], probe.entries[-1]
    steps_per_ms = (last[1] - first[1]) / ((last[0] - first[0]) & 0xFFFF)
    ms = lambda n: int(n * steps_per_ms)                       # noqa: E731

    rig = HB.Rig(PI.image(), HB.ENTRY_CURRENT, HB.TICK_CURRENT,
                 echo=True, steps_per_tick=HB.STEPS_PER_TICK)
    rig.run(GAP.BOOT_WARMUP_STEPS + ms(GAP.SETTLE_MS))
    mem = rig.mem
    check("the session reaches steady runtime supervision",
          len(rig.entries) >= 2, f"{len(rig.entries)} service entries")

    # THESE ARE LIVENESS DEADLINES, NOT TIMING CLAIMS, and the difference
    # matters. This gate drives the rig in 1 ms slices so that a command can
    # be sent AFTER the previous reply on the same CPU; that pacing costs
    # roughly 190 ms of simulated time for a transaction the service-gap proof
    # measures at 1.15 ms of actual main-loop occupancy. The number that has
    # to be inside the 10 ms raster is that one, and me711_ts_gap_proof owns
    # it. What THIS gate asks is only "did the ECU answer at all, without a
    # reset and without a reconnect", so the deadlines are set well clear of
    # the rig's own pacing and tightened by nothing.
    BURN_LIMIT_MS = 8000
    PLAIN_LIMIT_MS = 800

    def transact(label, request, matcher, limit_ms):
        """Send, then advance in 1 ms slices until the reply is on the wire."""
        start = len(rig.tx)
        sent_at = rig.cpu.steps + 1
        rig.queue_rx(sent_at, request)
        deadline = rig.cpu.steps + ms(limit_ms)
        at = None
        while rig.cpu.steps < deadline and rig.trap is None:
            rig.run(min(ms(1), deadline - rig.cpu.steps))
            stream = bytes(v for _t, v in rig.tx)
            at, end, payload = find_reply(stream, start, matcher)
            if at is not None:
                break
        if at is None:
            check(label, False,
                  f"no reply in {limit_ms} ms (trap={rig.trap})")
            pc = (rig.cpu.csp << 16) | rig.cpu.ip
            debug_names = ("hc_rx_head", "hc_rx_tail", "hc_rx_ovf",
                           "rx_irq_mode", "rx_tick_ok", "rx_ticks",
                           "rx_reqs")
            debug = {n: mem.r16(datum(n)) for n in debug_names}
            print("  protocol stall: pc=%06X psw=%04X CC7IC=%04X "
                  "CC7=%04X T0=%04X rxq=%d pendingIRQ=%s vars=%s"
                  % (pc, rig.cpu._sget(0xFF10), rig.cpu._sget(0xFF86),
                     rig.cpu._sget(0xFE8E), rig.cpu._sget(0xFE80),
                     len(rig.rxq), sorted(rig.cpu.irq_pending), debug))
            return None
        done_step = rig.tx_steps[end - 1]
        check(label, rig.trap is None,
              f"replied after {(done_step - sent_at) / steps_per_ms:.1f} ms")
        return payload

    def och_read():
        lo = min(och[n] for n in OCH_NAMES)
        hi = max(och[n] for n in OCH_NAMES) + 2
        req = envelope(b"O" + lo.to_bytes(2, "big")
                       + (hi - lo).to_bytes(2, "big"))
        p = transact("output-channel read", req,
                     lambda d: len(d) == hi - lo + 1 and d[0] == 0,
                     PLAIN_LIMIT_MS)
        if p is None:
            return None
        body = p[1:]
        return {n: int.from_bytes(body[och[n] - lo:och[n] - lo + 2], "big")
                for n in OCH_NAMES}

    def version_text():
        # the image's own 'V' text (TGT_VERSIONTXT + " build <id>" since
        # 2026-10-11), as its build manifest records it
        import me711_image as _PI
        v = _PI.metadata().get("version_text")
        if not v:
            raise SystemExit("version_text missing from the manifest")
        return v.encode()

    def burn(label, limit_ms=BURN_LIMIT_MS):
        return transact(label, envelope(b"B"), lambda d: d == b"\0", limit_ms)

    def edit(value):
        return transact(
            f"calibration page write 0x{value:02X} @{p3_off}",
            envelope(b"W" + p3_off.to_bytes(2, "big") + bytes([value])),
            lambda d: d == b"\0", PLAIN_LIMIT_MS)

    def page_read():
        return transact(
            f"calibration page read @{p3_off}",
            envelope(b"R" + p3_off.to_bytes(2, "big") + b"\0\1"),
            lambda d: len(d) == 2 and d[0] == 0, PLAIN_LIMIT_MS)

    # ================================================== BEFORE ANY BURN =====
    print("\n  --- the session before any Burn ---")
    before = och_read()
    programs0 = mem.fl_programs
    check("the store starts virgin - every cell blank",
          all(cell_blank(mem.flash, i) for i in range(CELLS)),
          f"{sum(cell_blank(mem.flash, i) for i in range(CELLS))}/{CELLS} blank")

    # ===================================================== FIRST BURN =======
    print("\n  --- edit, then BURN #1 ---")
    edit(0x11)
    burn("BURN #1 answers TS_OK - and only after the commit")

    # Keep the live-window post-mortem in the gate output.  This turned the
    # V47 physical failure's apparently contradictory counters into the ABI
    # diagnosis, and it makes a post-Burn protocol stall equally inspectable.
    live = bytes(mem.xram[0x6870:0x6870 + 36])
    be = lambda o: (live[o] << 8) | live[o + 1]       # noqa: E731
    print("  live post-Burn: owner=%d admission=%d pause=%d windows=%d/%d "
          "writer=%d/%d/%d mask=%04X pending=%04X/%04X maxT7=%d"
          % (live[4], live[5], live[6], be(8), be(10), be(12), be(14),
             be(16), be(20), be(22), be(24), be(32)))

    check("BURN #1 did not reset or trap the CPU", rig.trap is None,
          str(rig.trap))
    check("NO ERASE WAS ISSUED AT RUNTIME", not mem.fl_erases,
          f"fl_erases={mem.fl_erases}")
    check("it really programmed a whole record (not a no-op)",
          mem.fl_programs - programs0 >= REC_WORDS,
          f"{mem.fl_programs - programs0} words programmed, "
          f"record is {REC_WORDS}")
    check("no instruction was fetched from the busy device",
          mem.fl_fetch_while_busy == 0,
          f"{mem.fl_fetch_while_busy} fetches")
    check("cell 0 holds a complete record ending in DONE",
          cell_done(mem.flash, 0) and not cell_blank(mem.flash, 0),
          f"generation {cell_gen(mem.flash, 0)}")
    check("cells 1..15 are still byte-identical blank",
          all(cell_blank(mem.flash, i) for i in range(1, CELLS)))

    linked, end, expected_rt, fixups = relocated_writer(PI.image().read_bytes())
    actual_rt = bytes(mem.xram[WRITER_RT:WRITER_RT + WRITER_COPY])
    check("the 1024-byte writer copy reaches SRAM without truncation or corruption",
          actual_rt == expected_rt,
          "%02X:%04X..%04X -> 38:%04X (%d bytes, %d CADDR rebases)"
          % (linked >> 16, linked & 0xFFFF, end & 0xFFFF, WRITER_RT,
             end - linked, len(fixups)))
    check("only in-span absolute CADDR branches are rebased for SRAM execution",
          len(fixups) == 4
          and all(op in (0xCA, 0xEA)
                  and (linked & 0xFFFF) <= src < (end & 0xFFFF)
                  and dst == WRITER_RT + src - (linked & 0xFFFF)
                  for _at, op, src, dst in fixups),
          ", ".join("+%03X %02X:%04X->38:%04X" %
                    (at, op, src, dst) for at, op, src, dst in fixups))
    cell0_after_first = cell_bytes(mem.flash, 0)

    # ============================ THE SESSION MUST STILL BE A SESSION =======
    print("\n  --- ordinary traffic IMMEDIATELY after BURN #1, no reconnect ---")
    transact("version command still answers", envelope(b"V"),
             lambda d: d == b"\0" + version_text(), PLAIN_LIMIT_MS)
    # 2026-10-12: the status words are PUBLISHED in slices, one cycle every
    # 40 ms (hcdiag711.c hc_diag_publish_step, 13 slices): read them one
    # cycle after the Burn, not in the same breath as its reply. The
    # record itself is checked in flash above, at once.
    rig.run(ms(60))
    after = och_read()
    p = page_read()
    check("the burned byte reads back from the live page",
          p is not None and p[1] == 0x11,
          f"0x{p[1]:02X}" if p else "no reply")

    if before and after:
        check("nvmState went to BURNED (5) live, with no reboot",
              (after["nvmState"] & 0xFF) == HCNV_ST_DONE,
              f"0x{after['nvmState']:04X} -> low byte "
              f"{after['nvmState'] & 0xFF}")
        check("nvmError reports no persistence error",
              (after["nvmError"] & 0xFF) == HCNV_ERR_NONE,
              f"0x{after['nvmError']:04X}")
        check("the published generation is 1 after the first Burn",
              after["nvmGeneration"] == 1,
              f"{before['nvmGeneration']} -> {after['nvmGeneration']}")
        check("the commit counter moved without a reboot",
              after["nvmCommits"] == before["nvmCommits"] + 1,
              f"{before['nvmCommits']} -> {after['nvmCommits']}")
        check("persistence class became NON-VOLATILE (2)",
              (after["nvmSource"] >> 8) == 2,
              f"class {after['nvmSource'] >> 8}, "
              f"source {after['nvmSource'] & 0xFF}")

    # ==================================================== SECOND BURN =======
    print("\n  --- a second edit and BURN #2, still the same session ---")
    programs1 = mem.fl_programs
    edit(0x5A)
    burn("BURN #2 answers TS_OK in the same session")

    check("BURN #2 did not reset or trap the CPU", rig.trap is None,
          str(rig.trap))
    check("still no erase anywhere in the run", not mem.fl_erases)
    check("BURN #2 programmed a second whole record",
          mem.fl_programs - programs1 >= REC_WORDS,
          f"{mem.fl_programs - programs1} words")
    check("it consumed the NEXT cell, cell 1",
          cell_done(mem.flash, 1) and not cell_blank(mem.flash, 1),
          f"generation {cell_gen(mem.flash, 1)}")
    check("cell 0 is BYTE-IDENTICAL - the old record was never touched",
          cell_bytes(mem.flash, 0) == cell0_after_first)
    check("the generation advanced 1 -> 2 in the record itself",
          cell_gen(mem.flash, 0) == 1 and cell_gen(mem.flash, 1) == 2,
          f"{cell_gen(mem.flash, 0)} then {cell_gen(mem.flash, 1)}")
    check("cells 2..15 are still blank",
          all(cell_blank(mem.flash, i) for i in range(2, CELLS)))

    # THE BOOT-CHECKSUM SAMPLE WORDS. the project rules: the physical readback proved
    # SA7/SA8 are boot-checksummed, and the append-only geometry exists so the
    # first and last word of every page stay erased.
    # THE PAGES ARE DERIVED. These were the literals 0x040000, 0x042000,
    # 0x050000, 0x052000 - SA7/SA8, which V53 turned into the CODE sector, so
    # the check was asserting that compiled code is 0xFFFF.
    #
    # AND THE CLAIM ITSELF CHANGED. Since V53 the store is ABOVE the bootrom's
    # page record, so these words are no longer boot-checksummed at all. The
    # property that still matters - and the one the append-only geometry was
    # built for - is that a cell body never touches the first or last word of
    # its own 8 KiB page, so they are still checked, just against the right
    # pages and under the right name.
    protected = {}
    for base in [GEO.page_base(c) for c in range(min(4, GEO.cells))]:
        protected[base] = int.from_bytes(bytes(mem.flash[base:base + 2]), "little")
        protected[base + 0x1FFE] = int.from_bytes(
            bytes(mem.flash[base + 0x1FFE:base + 0x2000]), "little")
    check("every cell page's first and last word is still 0xFFFF",
          all(v == 0xFFFF for v in protected.values()),
          " ".join(f"{a:06X}={v:04X}" for a, v in sorted(protected.items())))

    print("\n  --- and the session is still alive after all of it ---")
    p = page_read()
    check("the second burned byte reads back live",
          p is not None and p[1] == 0x5A,
          f"0x{p[1]:02X}" if p else "no reply")
    rig.run(ms(60))                # one publication cycle (see above)
    final = och_read()
    if final:
        check("the published generation is 2 after the second Burn",
              final["nvmGeneration"] == 2, f"{final['nvmGeneration']}")
        check("nvmError is still clean at the end of the session",
              (final["nvmError"] & 0xFF) == HCNV_ERR_NONE,
              f"0x{final['nvmError']:04X}")

    check("NO CPU RESET OR TRAP ANYWHERE IN THE WHOLE SESSION",
          rig.trap is None, str(rig.trap))
    check("no instruction was ever fetched from a busy device",
          mem.fl_fetch_while_busy == 0, f"{mem.fl_fetch_while_busy}")

    print(f"\n{CHECKS - FAILS}/{CHECKS} session checks pass")
    if FAILS:
        print("V40 SESSION PROOF FAILED (%d check(s))" % FAILS)
    return int(bool(FAILS))


if __name__ == "__main__":
    raise SystemExit(main())
