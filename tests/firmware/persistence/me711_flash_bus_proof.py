#!/usr/bin/env python3
r"""THE BUS CYCLES THE LINKED IMAGE ACTUALLY ISSUES TO THE AM29F800BB.

WHY THIS GATE EXISTS
====================

V40 was software-proven, flashed, and its FIRST resetless Burn on the real
Porsche ME7.1.1 failed with "a word would not program". It failed five times.
The 1 MiB bootmode readback taken from that exact state
(failedReadback/V40_FIRST_RESETLESS_BURN_FAIL.bin) says precisely what
happened, and it is not ambiguous:

    cell  words programmed   first unprogrammed word   its intended value
      0        797                    797                  0xC8BA
      1        792                    792                  0x4235
      2       1114                   1114                  0x9696
      3        686                    686                  0xE803
      4        874                    874                  0x0000

Every programmed word is byte-correct.  No word is skipped.  No word is
partially programmed.  The next word is 0xFFFF - the device never applied a
program pulse to it at all - and the payload value it was given is ordinary.

A data poll cannot produce a false match while the part is executing: DQ7
reads back as the COMPLEMENT of the datum's bit 7 for the whole embedded
algorithm, so a full-word compare cannot match early.  What the datasheet does
NOT promise is that the write state machine has released at the instant DQ7
goes true; and an AM29F800BB that has not released IGNORES EVERY COMMAND
WRITTEN TO IT.

Then read the two writers' generated code.  V39 - which programmed 4120 words
on THIS ECU with no failure - and V40 are the same instructions apart from
three, inserted immediately after the poll match:

    MOV   R6,#0F0H
    EXTS  R15,#01H
    MOV   [R14],R6          <- a FIFTH write cycle to the device, per word

The AMD program command sequence is FOUR write cycles.  V40 issued five, and
it issued the fifth one three instructions after the poll matched: the
earliest moment in the whole loop, and the one moment the part may not yet be
listening.  Swallowed, the F0 is harmless - but so are the AA/55/A0 that
follow it, and that is the word that stays 0xFFFF.

WHAT THIS GATE CHECKS, AND WHY IT CANNOT PASS VACUOUSLY
=======================================================

It executes the LINKED IMAGE against a modelled AM29F800BB and reads the bus
transactions the CPU really produced.  Nothing here is a source-text grep, and
every number is measured from the instruction stream:

  1. EXACTLY FOUR write cycles per programmed word.  V41: 4.00.  The frozen
     V40 binary: 5.00, and the gate prints it.
  2. TWO MARGINS, both measured from the moment the embedded algorithm
     actually FINISHES - not from the moment the firmware noticed, which is a
     property of the poll and not of the device:

       FIRST TOUCH  how long the part is left completely alone before ANY
                    write cycle reaches it.  This is the quantity the physical
                    failure implicates, and it is the one that differs by an
                    order of magnitude.
       SEQUENCE     how long before the next program command sequence STARTS.
                    A part still closed when the AA arrives loses the whole
                    sequence: the 55 and A0 land in state 0, and the datum
                    becomes a plain write to a NOR in read mode, which does
                    nothing.  The word stays 0xFFFF - exactly what the
                    bootmode readback shows.  The smallest sequence margin in
                    the record is the image's FAILURE THRESHOLD.

  3. THE REPRODUCTION.  The model is then given a release window ONE STEP past
     the frozen V40 image's own failure threshold - a number measured from the
     failing artefact, not chosen - and the Burn is run again.  V40 must fail
     the way the bench failed: an incomplete record with an unprogrammed word.
     V41 must still commit a whole record ending in DONE.

WHAT THIS GATE DELIBERATELY DOES NOT CLAIM.  It does not assert a documented
AM29F800BB behaviour that makes an early F0 fatal; the datasheet does not bound
the release interval at all, which is the whole problem.  The evidence chain is
PHYSICAL EXACT for the dump, EXACT COMPONENT DATASHEET for the AMD command set,
SOFTWARE REFERENCE IMPLEMENTATION for the M744 programmer's two-read poll, and
INFERENCE for the mechanism joining them.  What is NOT inferred is that V40
issued a fifth write cycle per word and V39 - which programmed 4120 words on
this ECU without a failure - did not.  That is measured twice: from the Keil
listing, and from the executed instruction stream.
  4. No runtime erase, no instruction fetched from a busy device, and the
     boot-checksum sample words untouched.

The mutation test is therefore the physical failure itself.

AND A SECOND CONTROL, FOR THE V60 PROTOCOL CHANGE.  Run this gate against the
frozen V59 binary and it must fail EXACTLY ONE check:

    HANICORE_ME711_STEM=HaniCore_ME711_v59_forensic_window py tests\firmware\persistence\me711_flash_bus_proof.py

    V60   24/24
    V59   23/24 - "a failed Burn puts NO bit-7 code on the wire", reply 0x83

V59 still PASSES "an unexpected cleared bit is rejected without a retry
command", because the firmware behaviour that check tests is identical on both
images; only the reply code changed, and that is its own check now.  If the two
images ever stop differing by exactly one check here, one of the two has
stopped testing what it says it tests.

RUNTIME.  Four rig runs, each simulating a whole Burn on a booted ECU.
MEASURED at 460 s inside the full gate run (then tools/me711_suite.py); standalone under CPU contention
it has taken twice that.  Tier 2 work, not something to re-run after an .ini
edit - and if it ever reports a TIMEOUT, re-run it alone before believing it
.
"""
from __future__ import annotations

import binascii
import bisect
import re
import sys
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import c167sim as S                     # noqa: E402
import me711_heartbeat_gap_proof as HB  # noqa: E402
import me711_image as PI                # noqa: E402
import me711_ts_gap_proof as GAP        # noqa: E402

# The frozen artefact that failed on the bench.  Named once, here.
V40_BIN = (ROOT / "release/Porsche_ME711_V40_RESETLESS_BURN"
                  "/HaniCore_ME711_v40_resetless_burn.bin")
V40_SHA = "A618B49B2B86D0915BEE2842A57AE118D9EBD681E4A2BA453CD73A63588603CD"

# GEOMETRY IS DERIVED, NEVER RESTATED - tools/lib/me711_nvm_geometry.py records the
# incident. This line used to read 0x40000, 0x2000, 16, 2, 4120 and V53 moved
# the store to SA9..SA18 with eighty cells.
from me711_nvm_geometry import GEO
CELL0, PAGE, CELLS, OFF, REC_LEN = GEO.file_base, GEO.page, GEO.cells, GEO.off, 4120
REC_WORDS = REC_LEN // 2
P3_OFF = 2427

CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


# ======================================================== the modelled device
def _special(a):
    return (S.LRAM_LO <= a <= S.LRAM_HI or S.IRAM_LO <= a <= S.IRAM_HI
            or S.ESFR_LO <= a <= S.ESFR_HI or S.SFR_LO <= a <= S.SFR_HI
            or S.XRAM_LO <= a <= S.XRAM_HI or S.ASIC_LO <= a <= S.ASIC_HI)


TGT_UNLOCK1 = 0x800AAA
TGT_UNLOCK2 = 0x800554


def _is_flash(a):
    seg = (a >> 16) & 0xFF
    return (seg <= 0x0F or 0x80 <= seg <= 0x8F) and not _special(a)


def _off(a):
    return (((a >> 16) & 0x0F) << 16) | (a & 0xFFFF)


class Device:
    """An AM29F800BB that behaves the way the physical part behaves.

    prog_steps    how long the embedded program algorithm runs.  Reads return
                  data-poll status for this long: DQ7 = complement of the
                  datum's bit 7, DQ6 toggling, upper byte invalid.
    release_steps how much longer the WRITE STATE MACHINE stays closed after
                  the outputs already show true data.  This is the window the
                  datasheet does not bound and the one V40 wrote into.
                  Commands arriving inside it are ignored, exactly as they are
                  on silicon while an embedded algorithm is in progress.
    """

    def __init__(self, cpu, mem, prog_steps, release_steps=0,
                 drop_program_at=None, partial_program_at=None,
                 unsafe_program_at=None, dq5_program_at=None):
        self.cpu, self.mem = cpu, mem
        self.prog_steps = prog_steps
        self.release_steps = release_steps
        self.data_until = -1
        self.cmd_until = -1
        self.state = 0
        self.prog_data = 0
        self.toggle = 0
        self.programs = 0
        self.ignored_writes = 0
        self.fetch_while_busy = 0
        self.erases = []
        self.events = []          # (step, 'W'|'R', addr, value)
        # Deliberate fault injections used by the V42 regression. They model
        # distinct, observable NOR outcomes; none is asserted to be the V41
        # silicon mechanism. Each is one-shot so a successful retry has to be
        # caused by the candidate's own state machine, not by a version check.
        self.drop_program_at = drop_program_at
        self.partial_program_at = partial_program_at
        self.unsafe_program_at = unsafe_program_at
        self.dq5_program_at = dq5_program_at
        self.drop_injected = False
        self.partial_injected = False
        self.unsafe_injected = False
        self.dq5_injected = False
        self.dq5_active = False

    def outputs_busy(self):
        busy = self.cpu.steps < self.data_until
        if not busy:
            self.dq5_active = False
        return busy

    def cmds_closed(self):
        return self.cpu.steps < self.cmd_until


def install(rig, dev):
    r8, w8, w16 = S.Mem.r8, S.Mem.w8, S.Mem.w16

    def f_r8(s_, a, _o=r8):
        aa = a & 0xFFFFFF
        if _is_flash(aa):
            if dev.outputs_busy():
                if s_.fetching:
                    dev.fetch_while_busy += 1
                if aa & 1:
                    return 0x5A                 # DQ15..8 invalid while busy
                # DQ6 TOGGLES ONCE PER BUS CYCLE, AND THIS PART IS SIXTEEN BITS
                # WIDE. The model used to flip it inside every byte accessor,
                # so a 16-bit read - which c167sim serves as two r8 calls -
                # flipped it TWICE and handed the firmware back the same word
                # every time. DQ6 was therefore invisible to anything above the
                # bus, and the firmware's entire idle discipline, "two agreeing
                # reads prove read-array mode", was VACUOUS in every gate that
                # used this model: two reads of a busy part always agreed.
                #
                # That is what hid the DQ5 defect. The writer's failure path
                # issued FL_RESET into a device that was still driving status,
                # the write was swallowed exactly as V40's were, and it returned
                # into flash - and no check could see the state it returned
                # into, because the only bit that reports it did not move.
                #
                # Toggling on the LOW byte only gives one flip per word access,
                # which is what the physical part does on a 16-bit bus.
                # _dq6_is_observable() below fails this gate if it ever stops.
                dev.toggle ^= 0x40
                return (((~dev.prog_data) & 0x80) | dev.toggle | 0x0A
                        | (0x20 if dev.dq5_active else 0)) & 0xFF
            if not s_.fetching and (aa & 1) == 0:
                dev.events.append((dev.cpu.steps, "R", aa, 0))
            return s_.flash[_off(aa)]
        return _o(s_, a)

    def dev_write(a, v):
        dev.events.append((dev.cpu.steps, "W", a, v & 0xFFFF))
        if dev.cmds_closed():
            dev.ignored_writes += 1
            return
        off = _off(a)
        low = off & 0xFFF
        cmd = v & 0xFF
        st, dev.state = dev.state, 0
        if cmd == 0xF0:
            # Read/reset is a command in read-array mode too. While an
            # embedded operation is still running it was handled by the
            # cmds_closed path above and is deliberately ignored.
            return
        if st == 0:
            if low == 0xAAA and cmd == 0xAA:
                if (dev.drop_program_at is not None and not dev.drop_injected
                        and dev.programs == dev.drop_program_at):
                    # Command state machine not ready: swallow this whole
                    # sequence, then reopen well before the next main-loop
                    # pass. The word remains blank, matching V40/V41's dump.
                    dev.drop_injected = True
                    dev.cmd_until = dev.cpu.steps + 100
                    return
                dev.state = 1
        elif st == 1:
            if low == 0x554 and cmd == 0x55:
                dev.state = 2
        elif st == 2:
            if low == 0xAAA and cmd == 0xA0:
                dev.state = 10
            elif low == 0xAAA and cmd == 0x80:
                dev.state = 3
        elif st == 3:
            if low == 0xAAA and cmd == 0xAA:
                dev.state = 4
        elif st == 4:
            if low == 0x554 and cmd == 0x55:
                dev.state = 5
        elif st == 5:
            if cmd == 0x30:
                dev.erases.append(off)
                raise S.Trap("RUNTIME SECTOR ERASE @0x%06X" % a)
        elif st == 10:
            v16 = v & 0xFFFF
            if (dev.dq5_program_at is not None and not dev.dq5_injected
                    and dev.programs == dev.dq5_program_at):
                # Program timeout: no data bits change, DQ5 is observable
                # while DQ7 still disagrees, then the normal retry sees blank.
                dev.dq5_injected = True
                dev.dq5_active = True
                write16 = 0xFFFF
            elif (dev.partial_program_at is not None
                  and not dev.partial_injected
                  and dev.programs == dev.partial_program_at):
                # A legal partial program: only a subset of the datum's zero
                # bits is cleared. A retry may complete this word safely.
                dev.partial_injected = True
                write16 = v16 | 0x00FF
            elif (dev.unsafe_program_at is not None
                  and not dev.unsafe_injected
                  and dev.programs == dev.unsafe_program_at):
                # A bad partial state: clear one bit that the datum needs one.
                # The V42 predicate must reject this rather than retry it.
                dev.unsafe_injected = True
                write16 = v16 & (v16 - 1) if v16 else 0xFFFE
            else:
                write16 = v16
            dev.mem.flash[off] &= write16 & 0xFF
            dev.mem.flash[off + 1] &= (write16 >> 8) & 0xFF
            dev.programs += 1
            dev.prog_data = v16
            dev.data_until = dev.cpu.steps + dev.prog_steps
            dev.cmd_until = dev.data_until + dev.release_steps

    def f_w8(s_, a, v, _o=w8):
        if _is_flash(a & 0xFFFFFF):
            return
        return _o(s_, a, v)

    def f_w16(s_, a, v, _o=w16):
        aa = a & 0xFFFFFF
        if _is_flash(aa):
            dev_write(aa, v)
            return
        return _o(s_, a, v)

    S.Mem.r8, S.Mem.w8, S.Mem.w16 = f_r8, f_w8, f_w16
    rig._hooks = (f_r8, f_w8, f_w16)
    return dev


# ================================================================== the wire
envelope = HB.envelope      # one definition: 16-bit length (see HB)


def find_reply(stream, start, matcher):
    for at in range(start, max(start, len(stream) - 6)):
        if stream[at] != 0:
            continue
        n = stream[at + 1]
        end = at + 2 + n + 4
        if end > len(stream):
            continue
        pay = stream[at + 2:at + 2 + n]
        if (int.from_bytes(stream[at + 2 + n:end], "big")
                == (binascii.crc32(pay) & 0xFFFFFFFF)) and matcher(pay):
            return at, end, pay
    return None, None, None


def syms(img):
    """hc_asic_start_service and hc_tick_ms FOR THIS image, from ITS OWN map.

    The heartbeat rig exports the addresses of the CURRENT build.  This gate
    drives two different binaries, and feeding V41's entry address to the V40
    image reports "no supervision entries" - which reads exactly like a dead
    ECU.  Each image's addresses come from the map that was linked with it.
    """
    m = img.with_suffix(".M66")
    if not m.exists():
        m = ROOT / "bins/hanicore" / (img.stem + ".M66")
    if not m.exists():
        raise SystemExit("no linker map beside %s - cannot resolve its "
                         "symbols, and guessing them is how a gate ends up "
                         "auditing the wrong addresses" % img.name)
    text = m.read_text(errors="replace")
    out = {}
    for mm in re.finditer(r"^\s*([0-9A-F]{6})H\s+(\w+)\s", text, re.M):
        if mm.group(2) in ("hc_asic_start_service", "hc_tick_ms"):
            out.setdefault(mm.group(2), int(mm.group(1), 16))
    if len(out) != 2:
        raise SystemExit("%s does not name both rig symbols" % m.name)
    return out["hc_asic_start_service"], out["hc_tick_ms"]


def _dq6_is_observable():
    """Two successive WORD reads of a BUSY part must differ, and of an idle
    part must agree.

    The firmware proves the device is in read-array mode by reading one address
    twice and requiring the two to agree. That proof is only worth anything if
    the model can actually fail it, so ask the model directly, with no firmware
    and no rig involved: programme a word, read it twice while the device is
    busy, then twice more after it has released.
    """
    class _CPU:
        steps = 0
        csp = 0
        ip = 0

    class _Rig:
        pass

    mem = S.Mem(bytes(0x100000))
    mem.fetching = False
    cpu = _CPU()
    dev = Device(cpu, mem, prog_steps=1000)
    rig = _Rig()
    rig.mem, rig.cpu = mem, cpu
    install(rig, dev)

    at = 0x800000 + CELL0            # the cell base as the CPU addresses it

    def word():
        return mem.r8(at) | (mem.r8(at + 1) << 8)

    mem.w16(TGT_UNLOCK1, 0x00AA)
    mem.w16(TGT_UNLOCK2, 0x0055)
    mem.w16(TGT_UNLOCK1, 0x00A0)
    mem.w16(at, 0x1234)
    busy = (word(), word())
    cpu.steps = dev.data_until + 1
    idle = (word(), word())
    return busy[0] != busy[1], idle[0] == idle[1], busy, idle


def burn_run(img, release_steps, **faults):
    """Warm one rig, edit the persistence byte, press Burn, keep the bus log."""
    entry, tick = syms(img)
    # V97: echo=True - THE K-LINE ALWAYS ECHOES. Since V94's
    # pipelined TX (hcts.c hcts_tx_end) a reply shorter than
    # HCTS_ECHO_LAG_MAX + 1 bytes waits for its echoes and drains them BY
    # COUNT, so on a rig that does not echo the host's NEXT request is
    # drained instead: this gate's Burn after a page write was eaten and
    # never answered (Tier 2, 2026-09-30). Not a firmware defect - no
    # K-line wiring fails to echo - so the rig models the wire.
    probe = HB.Rig(img, entry, tick, echo=True)
    probe.run(GAP.BOOT_WARMUP_STEPS)
    if len(probe.entries) < 2:
        raise SystemExit("warmup reached no supervision entries - vacuous")
    (t0, s0), (t1, s1) = probe.entries[0], probe.entries[-1]
    spm = (s1 - s0) / ((t1 - t0) & 0xFFFF)

    def ms(n):
        return int(n * spm)

    # THIS GATE MEASURES A TIME BUDGET, SO IT MUST OPT IN TO THE HARDWARE
    # TIMEBASE. c167sim ships steps_per_tick = 2; the real part manages ~8
    # instructions per timer tick, and me711_heartbeat_gap_proof derives
    # STEPS_PER_TICK = 8 from TGT_FCPU_HZ for exactly that reason. It is
    # opt-in "because nineteen gates share this rig and only two of them
    # measure a TIME BUDGET" - and this is a third. The live Burn has a
    # budget of its own, HCNV_ERR_DEADLINE, and at the shipped default the
    # firmware gets a QUARTER of the instructions per millisecond of that
    # deadline that it gets on the ECU.
    #
    # MEASURED 2026-09-12, V50, this harness, one Burn:
    #   steps_per_tick = 2   384 of 2060 words, nvmError = 10 (ERR_DEADLINE),
    #                        liveDeadlineMs = 0, liveWriterFail = 0,
    #                        nvmFailWord = 0xFFFF - nothing failed, the
    #                        firmware simply ran out of its own time
    #   steps_per_tick = 8   2060 of 2060 words, liveBurnError = 0,
    #                        liveDeadlineMs = 2170 - 2.17 s to spare
    #
    # AND WHY THIS WAS NEVER NOTICED: V49 and earlier DESTROYED the T8 and CC7
    # requests that arose inside the writer window, so the 1 ms tick and the
    # S5500 raster effectively stalled for the duration of a Burn and the Burn
    # ran unimpeded. Their 2060-word pass at the wrong timebase was an artefact
    # of the very defect V50 fixes. The moment the tick genuinely runs during a
    # Burn, the deadline is genuinely consumed, and the timebase starts to
    # matter. Same shape as the frozen-instrumentation lesson in the project rules.
    #
    # The per-word BUS-CYCLE measurements this gate was built for - write
    # cycles per programmed word, and both margins - are timebase independent,
    # which is why V41's five-write-cycle defect was caught correctly at the
    # shipped default.
    rig = HB.Rig(img, entry, tick, echo=True,
                 steps_per_tick=HB.STEPS_PER_TICK)
    spm = float(HB.STEPS_PER_TICK * 1250)
    dev = Device(rig.cpu, rig.mem, max(1, int(spm * 11.0 / 1000.0)),
                 release_steps, **faults)
    install(rig, dev)
    rig.run(GAP.BOOT_WARMUP_STEPS + ms(GAP.SETTLE_MS))

    def transact(req, matcher, limit_ms):
        start = len(rig.tx)
        rig.queue_rx(rig.cpu.steps + 1, req)
        deadline = rig.cpu.steps + ms(limit_ms)
        while rig.cpu.steps < deadline and rig.trap is None:
            rig.run(min(ms(1), deadline - rig.cpu.steps))
            at, _e, pay = find_reply(bytes(v for _t, v in rig.tx), start,
                                     matcher)
            if at is not None:
                return pay
        return None

    transact(envelope(b"W" + P3_OFF.to_bytes(2, "big") + bytes([3])),
             lambda d: d == b"\0", 800)
    dev.events.clear()
    dev.programs = 0
    reply = transact(envelope(b"B"), lambda d: len(d) == 1, int(__import__("os").environ.get("HC_BURN_LIMIT_MS", "9000")))
    # V97: THE DIARY IS PUBLISHED ONCE PER FRAME (hc_io_publish), so read it
    # a few frames AFTER the reply, as an operator's next poll would. A Burn
    # refused at word 0 (the unsafe-partial case) answers before the next
    # publish, and sampling at the reply read the pre-Burn diary (flags 0,
    # word 0xFFFF) although the writer had raised HCNV_PF_UNSAFE. The device
    # facts are read from the modelled part and do not depend on this.
    if reply is not None and rig.trap is None:
        rig.run(ms(50))
    return rig, dev, reply, spm


def analyse(dev):
    """Write cycles per programmed word, and the MARGIN, from the bus.

    A "word" is one complete AMD program command sequence: AA at 0xAAA, 55 at
    0x554, A0 at 0xAAA, then the datum.  The cycle count is every write cycle
    the device received from the end of the previous word's datum up to and
    including this one's - so an extra command written anywhere in the loop
    shows up here, which is the whole point.
    """
    per_word, prog_steps = [], []
    cur, state = 0, 0
    for step, kind, a, v in dev.events:
        if kind != "W":
            continue
        cur += 1
        low = _off(a) & 0xFFF
        cmd = v & 0xFF
        if state == 0 and low == 0xAAA and cmd == 0xAA:
            state = 1
        elif state == 1 and low == 0x554 and cmd == 0x55:
            state = 2
        elif state == 2 and low == 0xAAA and cmd == 0xA0:
            state = 3
        elif state == 3:
            state = 0
            prog_steps.append(step)
            per_word.append(cur)
            cur = 0
        else:
            state = 1 if (low == 0xAAA and cmd == 0xAA) else 0

    # TWO MARGINS, and telling them apart is what makes this gate mean
    # something.  Both are measured from the moment the embedded algorithm
    # actually COMPLETES - not from the moment the firmware noticed, which is
    # a property of the poll and not of the device.
    #
    #   FIRST TOUCH   how long the part is left completely alone before ANY
    #                 write cycle reaches it.  This is the number the physical
    #                 failure implicates: V40 touches the device 2.75 us after
    #                 it finishes, V39 and V41 leave it alone for ~23 us.
    #
    #   SEQUENCE      how long before the next program command sequence
    #                 STARTS.  A part that is still closed when the AA arrives
    #                 loses the whole sequence - the 55 and A0 land in state 0
    #                 and the datum becomes a plain write to a NOR in read
    #                 mode, which does nothing.  The word stays 0xFFFF, which
    #                 is exactly what the bootmode readback shows.
    #
    # An image's FAILURE THRESHOLD is the smallest SEQUENCE margin anywhere in
    # the record: a release window larger than that costs a word, and one lost
    # word fails the Burn.  The first-touch margin is reported beside it
    # because it is the quantity that differs by an order of magnitude, and
    # the one the fix is actually about.
    writes = [(st, _off(a) & 0xFFF, v & 0xFF)
              for st, k, a, v in dev.events if k == "W"]
    steps_only = [w[0] for w in writes]
    first_touch, sequence = [], []
    for ps in prog_steps:
        done = ps + dev.prog_steps
        wi = bisect.bisect_right(steps_only, ps)
        if wi >= len(writes):
            continue
        first_touch.append(writes[wi][0] - done)
        for j in range(wi, len(writes)):
            st, low, cmd = writes[j]
            if low == 0xAAA and cmd == 0xAA:
                sequence.append(st - done)
                break
    return per_word, first_touch, sequence


def _och_offset(name):
    """An output-channel offset out of the .ini this build generated.

    DERIVED, not typed. The diary words below are literals from V42 and have
    survived only because nothing moved them; the whole V60 campaign exists
    because a hand-copied offset drifted eight bytes and nobody could see it.
    """
    ini = ROOT / "tunerstudio/hanicore_me711.ini"
    body = ini.read_text(errors="replace").split("[OutputChannels]", 1)[1]
    m = re.search(r"^\s*%s\s*=\s*scalar,\s*U16,\s*(\d+)" % name, body, re.M)
    if not m:
        raise SystemExit("%s is not an output channel in %s" % (name, ini.name))
    return int(m.group(1))


def diary(rig):
    """The eight V42 diary words as update_live() publishes them in OCH,
    plus nvmState - published once per frame, so it is STALE here and is
    printed for context only. See the unsafe-word check for what that cost."""
    base = 0x2000
    out = {}
    for name, off in (('word', 454), ('exp', 456), ('got', 458),
                      ('got2', 460), ('flags', 462), ('retries', 464),
                      ('pollmin', 466), ('pollmax', 468),
                      ('nvmstate', _och_offset("nvmState"))):
        i = base + off
        out[name] = (rig.mem.xram[i] << 8) | rig.mem.xram[i + 1]
    return out


def main():
    # Builds can run while this lengthy qualification executes. Freeze the
    # binary and its map once; later cases must not reopen a different build.
    original = PI.image()
    if '--candidate-only' in sys.argv:
        pos=sys.argv.index('--candidate-only')
        if len(sys.argv)>pos+1:original=Path(sys.argv[pos+1]).resolve()
    frozen=Path(tempfile.mkdtemp(prefix='hc_flash_bus_'))/original.name
    shutil.copy2(original,frozen)
    shutil.copy2(original.with_suffix('.M66'),frozen.with_suffix('.M66'))
    if '--candidate-only' in sys.argv:
        print('FROZEN CANDIDATE',PI.sha256(frozen),flush=True)
        r,d,reply,_=burn_run(frozen,0)
        g,_,_=analyse(d)
        check('edited Burn replies without trap',reply==b'\0' and r.trap is None,str(r.trap))
        check('complete journal record',d.programs>=REC_WORDS and bytes(r.mem.flash[CELL0+OFF+REC_LEN-4:CELL0+OFF+REC_LEN])==b'DONE',str(d.programs))
        check('four program cycles per word',bool(g) and min(g)==max(g)==4)
        check('no instruction fetch from busy flash',d.fetch_while_busy==0,str(d.fetch_while_busy))
        print(f'{CHECKS-FAILS}/{CHECKS} candidate bus checks pass',flush=True)
        return int(bool(FAILS))
    print("=== HaniCore ME7.1.1 - AM29F800BB BUS-CYCLE proof "
          "(the V40 root cause) ===\n")
    v42 = frozen
    print("  under test  %s" % v42.name)
    print("              %s" % PI.sha256(v42))
    if not V40_BIN.exists():
        raise SystemExit("the frozen V40 artefact is missing: %s" % V40_BIN)
    got40 = PI.sha256(V40_BIN)
    print("  frozen V40  %s\n              %s" % (V40_BIN.name, got40))
    check("the frozen V40 artefact is the one that failed on the bench",
          got40 == V40_SHA, got40[:16] + "...")

    # ---------------------------------------------------------- run A: V40
    print("\n  --- the FROZEN V40 binary, on a quiescent device ---")
    _r40, d40, rep40, spm = burn_run(V40_BIN, 0)

    def us(steps):
        return steps / spm * 1000.0

    g40, m40, q40 = analyse(d40)
    check("V40 does program the record when the device never hesitates",
          d40.programs >= REC_WORDS,
          "%d words, reply %r" % (d40.programs, rep40))
    w40 = (sum(g40) / len(g40)) if g40 else 0.0
    check("V40 issues FIVE write cycles per word, not AMD's four",
          abs(w40 - 5.0) < 0.01, "%.2f cycles/word" % w40)
    touch40 = min(m40) if m40 else 0
    seq40 = min(q40) if q40 else 0
    print("        V40 after the algorithm finishes: FIRST TOUCH %.2f us "
          "(%d steps)," % (us(touch40), touch40))
    print("            next SEQUENCE starts %.2f us (%d steps) later, "
          "over %d words" % (us(seq40), seq40, len(q40)))

    # ---------------------------------------------------------- run B: V41
    print("\n  --- the candidate, on a quiescent device ---")
    r41, d41, rep41, spm41 = burn_run(v42, 0)

    def us41(steps):
        return steps / spm41 * 1000.0

    g41, m41, q41 = analyse(d41)
    check("the Burn answered, with no trap and no reset",
          rep41 == b"\0" and r41.trap is None,
          "reply %r trap %s" % (rep41, r41.trap))
    check("a whole record was programmed", d41.programs >= REC_WORDS,
          "%d words of %d" % (d41.programs, REC_WORDS))
    w41 = (sum(g41) / len(g41)) if g41 else 0.0
    check("EXACTLY FOUR write cycles per word - the AMD program sequence",
          bool(g41) and max(g41) == 4 and min(g41) == 4,
          "%.2f cycles/word, min %d max %d"
          % (w41, min(g41) if g41 else 0, max(g41) if g41 else 0))
    touch41 = min(m41) if m41 else 0
    seq41 = min(q41) if q41 else 0
    print("        V41 after the algorithm finishes: FIRST TOUCH %.2f us "
          "(%d steps)," % (us41(touch41), touch41))
    print("            next SEQUENCE starts %.2f us (%d steps) later, "
          "over %d words" % (us41(seq41), seq41, len(q41)))
    check("the device is left alone far longer than by the image that failed",
          touch41 >= 5 * max(1, touch40),
          "first touch %.2f us vs V40's %.2f us"
          % (us41(touch41), us(touch40)))
    # SAY THE SMALL NUMBER OUT LOUD. The two sequence margins are three
    # instructions apart, so "the next AA gets swallowed" cannot be what
    # separates these two images - the FIRST TOUCH can, and it differs by a
    # factor of eight. The first version of this gate reproduced the failure
    # the other way round and the measurement contradicted it; that is what a
    # model is for.
    check("its failure threshold is higher too - but only just, and that "
          "is the point",
          seq41 > seq40,
          "sequence margin %.2f us vs V40's %.2f us (%d steps apart)"
          % (us41(seq41), us(seq40), seq41 - seq40))

    # THE CLOSED WINDOW, COMPUTED FROM THE BUS STREAMS ALREADY RECORDED.
    # Anywhere strictly between the two images' first-touch margins, the frozen
    # V40 binary is writing a command into a device that has not released and
    # the candidate is not touching it at all. No extra simulation is needed to
    # say so: every margin is in the event log.
    win_touch = (touch40 + touch41) // 2
    v40_in = sum(1 for m in m40 if m < win_touch)
    v41_in = sum(1 for m in m41 if m < win_touch)
    print("")
    print("        with the device modelled as closed for %.2f us after it "
          "finishes" % us(win_touch))
    print("        - between the two images' own first-touch margins, so "
          "bracketed by")
    print("        the artefacts rather than picked:")
    check("V40 writes into a device that is not listening, EVERY word",
          v40_in >= len(m40) - 1, "%d of %d words" % (v40_in, len(m40)))
    check("V41 never touches it - not one write inside that window",
          v41_in == 0, "%d of %d words" % (v41_in, len(m41)))
    check("no runtime erase was issued", not d41.erases, str(d41.erases))
    check("no instruction was fetched from a busy device",
          d41.fetch_while_busy == 0, str(d41.fetch_while_busy))
    fl = r41.mem.flash
    a0 = CELL0 + OFF
    check("cell 0 holds a record ending in DONE",
          bytes(fl[a0 + REC_LEN - 4:a0 + REC_LEN]) == b"DONE")
    prot = {}
    for base in range(CELL0, CELL0 + CELLS * PAGE, PAGE):
        prot[base] = int.from_bytes(bytes(fl[base:base + 2]), "little")
        prot[base + 0x1FFE] = int.from_bytes(
            bytes(fl[base + 0x1FFE:base + 0x2000]), "little")
    check("every boot-checksum sample word is still 0xFFFF",
          all(v == 0xFFFF for v in prot.values()),
          "%d damaged of %d"
          % (sum(v != 0xFFFF for v in prot.values()), len(prot)))

    # ----------------------------------------- runs C and D: the reproduction
    win = seq40 + 1
    print("\n  --- the reproduction: a device whose write state machine stays")
    print("      closed for %.2f us past the end of the algorithm - ONE STEP"
          % us(win))
    print("      past the FROZEN V40 image's own smallest sequence margin, a")
    print("      number measured from the artefact that failed ---")
    _rc, dc, repc, _sc = burn_run(V40_BIN, win)
    check("V40 FAILS, exactly as it failed on the bench",
          dc.programs < REC_WORDS and repc != b"\0",
          "%d of %d words, reply %r, %d command writes swallowed"
          % (dc.programs, REC_WORDS, repc, dc.ignored_writes))
    rd, dd, repd, _sd = burn_run(v42, win)
    fld = rd.mem.flash
    check("V41 COMMITS A WHOLE RECORD ON THAT SAME DEVICE",
          dd.programs >= REC_WORDS and repd == b"\0"
          and bytes(fld[a0 + REC_LEN - 4:a0 + REC_LEN]) == b"DONE",
          "%d words, reply %r, %d swallowed"
          % (dd.programs, repd, dd.ignored_writes))

    # --------------------------------------------------- V42 fault matrix ---
    # These are intentionally fault *classes*, not an asserted explanation of
    # V41. Each forces a real linked V42 image through the state it claims to
    # handle, then reads the OCH diary the operator will see on the bench.
    print("\n  --- V42 retry / status fault matrix ---")
    _tog, _still, _busy, _idle = _dq6_is_observable()
    check("the modelled part TOGGLES DQ6 between two word reads while busy",
          _tog, "busy reads 0x%04X 0x%04X" % _busy)
    check("and holds still once it has released - so agreement means something",
          _still, "idle reads 0x%04X 0x%04X" % _idle)

    def fault(name, **kw):
        rr, dev, reply, _ = burn_run(v42, 0, **kw)
        d = diary(rr)
        done = bytes(rr.mem.flash[a0 + REC_LEN - 4:a0 + REC_LEN]) == b"DONE"
        print("        %-18s reply=%r programs=%d diary=%s" %
              (name, reply, dev.programs, d))
        return rr, dev, reply, done, d

    _rf, df, repf, donef, diagf = fault("swallowed command",
                                        drop_program_at=400)
    check("a swallowed AA/55/A0/DATA sequence retries the SAME word and commits",
          df.drop_injected and repf == b"\0" and donef
          and diagf['retries'] >= 1 and (diagf['flags'] & 0x10),
          "retries=%d flags=0x%04X" % (diagf['retries'], diagf['flags']))
    check("swallowed-command retry leaves no busy-flash instruction fetch",
          df.fetch_while_busy == 0, str(df.fetch_while_busy))

    _rp, dp, repp, donep, diagp = fault("legal partial word",
                                        partial_program_at=0)
    check("a partial 1->0-only word is retried and fully verifies",
          dp.partial_injected and repp == b"\0" and donep
          and diagp['retries'] >= 1 and (diagp['flags'] & 0x10),
          "retries=%d flags=0x%04X" % (diagp['retries'], diagp['flags']))

    _rdq, ddq, repdq, donedq, diagdq = fault("DQ5 timeout", dq5_program_at=0)
    check("DQ5 while DQ7 disagrees resets, records, retries, and commits",
          ddq.dq5_injected and repdq == b"\0" and donedq
          and diagdq['retries'] >= 1 and (diagdq['flags'] & 0x01)
          and (diagdq['flags'] & 0x10),
          "retries=%d flags=0x%04X" % (diagdq['retries'], diagdq['flags']))

    _ru, du, repu, doneu, diagu = fault("unsafe partial word",
                                        unsafe_program_at=0)
    # THIS USED TO READ `repu != b"\0"`, AND THAT WAS THE PRE-V60 CONTRACT.
    #
    # A failed Burn answered TS_BAD_CMD until V59, so the reply byte carried
    # the verdict and this check could read it off the wire. It also ENDED THE
    # TUNERSTUDIO SESSION - every response code with bit 7 set does, and this
    # protocol has no soft error code at all. A refused or
    # failed Burn now answers TS_REFUSED, which IS TS_OK, and the verdict moved
    # to nvmState / nvmError / cfgValidation, where it can name a reason
    # instead of carrying one bit of "no".
    #
    # So the question splits in two, and both halves are stronger than the one
    # they replace: the reply must be SESSION-SAFE, and the ECU must SAY the
    # Burn failed.
    check("a failed Burn puts NO bit-7 code on the wire",
          len(repu) == 1 and not (repu[0] & 0x80), "reply=%r" % repu)
    # AND THE VERDICT IS THE DEVICE, NOT nvmState - MEASURED, NOT ASSUMED.
    #
    # The obvious replacement for the reply byte was nvmState, since that is
    # where a Burn's verdict lives from V60 on. It does not work HERE:
    # update_live() publishes the output-channel block once per frame, and this
    # harness samples it as soon as the reply lands. Measured on both images
    # and in every case, successful ones included, it reads 0x0104 -
    # COMMITTING, phase program - never 5 or 6. A stale channel is not a
    # verdict.
    #
    # What IS authoritative here is the DEVICE, which is what a bus proof is
    # for: no DONE marker was programmed (one word written, not 2061), the
    # writer raised HCNV_PF_UNSAFE, and it issued no retry command.
    check("an unexpected cleared bit is rejected without a retry command",
          du.unsafe_injected and not doneu
          and diagu['retries'] == 0 and (diagu['flags'] & 0x40),
          "done=%s retries=%d flags=0x%04X"
          % (doneu, diagu['retries'], diagu['flags']))

    print("\n%d/%d bus-cycle checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("FLASH BUS PROOF FAILED (%d check(s))" % FAILS)
    return int(bool(FAILS))


if __name__ == "__main__":
    raise SystemExit(main())
