#!/usr/bin/env python3
r"""
me711_heartbeat_gap_proof.py - prove the non-blocking bench heartbeat
("H\n" once per second, one byte per main-loop pass, T7-paced, never waited
on) works AND cannot widen the worst-case gap between calls to
hc_asic_start_service() past the 10 ms S5500 supervision budget.

    py tests\firmware\asic\me711_heartbeat_gap_proof.py

hc_asic_start_service() and hb_service() are each called exactly once per
iteration of the Bosch main loop, so between any two consecutive
hc_asic_start_service() entries there is exactly ONE hb_service() call - and
its body is loop-free and contains no wait, so the only thing it can add to a
gap is its own bounded instruction count.

S0TIC MODELLING. This tool - and tests/firmware/build/me711_boot_test.py - model S0TIC
bit 7 as the ASC0 transmit-interrupt REQUEST LATCH it actually is: hardware
raises it once, one byte time after an S0TBUF write; software clears it; it
does NOT act as a persistent "buffer free" level and does NOT re-assert on its
own. Modelling it as a level is exactly what hid the V18 defect, where
hb_service() gated the emit on `S0TIC & 0x80` - which after the boot banner is
0 forever - and therefore never transmitted a heartbeat on hardware. V19 paces
with T7 instead and never touches S0TIC.

PHASE A - conservative bound against the frozen V17 image (no heartbeat in
it): measure V17's hc_asic_start_service() gap distribution in c167sim
(2500 sim steps == 1 ms) and add HB_BODY_STEPS - a generous bound on
hb_service()'s loop-free body - to the single worst gap.

PHASE B - the current frozen RUNTIME_V20 image, run for real on a QUIET line
(the scenario the heartbeat affects; a TunerStudio reply blocks the loop in
V17 too - hcts_service()'s hcts_tx() - and V17's bench card §5h flags that as
a standing constraint unrelated to the heartbeat). Confirms: boots with no
trap; "H\n" actually goes out on a ~1 s cadence; hb_service() never blocks
(its own worst-case step span is tiny); the worst service gap is under 10 ms
with at least 2x margin; it stands down after one completed TunerStudio
request.  V17 remains the conservative pre-heartbeat baseline, not a
performance-equality requirement: V20 deliberately includes the runtime
layer that V17 did not.
"""
from __future__ import annotations

import binascii
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import c167sim as S  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
import me711_image as PI  # ONE source of truth for the image under test
V17 = ROOT / "bins/hanicore/HaniCore_ME711_A1146_umkom_responder_v17.bin"
CURRENT = PI.image()
TGT = ROOT / "firmware/targets/me711/hctarget.h"
MAP = PI.MAP

_t = TGT.read_text(errors="replace")



def envelope(payload: bytes) -> bytes:
    """A TunerStudio request envelope: 16-bit length, payload, CRC32 big-endian.

    THE LENGTH IS SIXTEEN BITS, AND ELEVEN COPIES OF THIS WROTE EIGHT.
    `bytes([0, len(payload)])` raises ValueError the moment a payload reaches
    256 bytes, so those gates could not construct a long request at all - the
    sending side of the exact defect the project rules record in frames() as the
    eighth instrument defect in this tree. Defined once, here, because 26
    gates already import this module.
    """
    return (len(payload).to_bytes(2, "big") + payload
            + (binascii.crc32(payload) & 0xFFFFFFFF).to_bytes(4, "big"))

def _define(n, default=None):
    m = re.search(r"#define\s+%s\s+(0x[0-9A-Fa-f]+|\d+)" % n, _t)
    if not m:
        if default is not None:
            return default
        raise SystemExit(f"{n} not in hctarget.h")
    return int(m.group(1), 0)


BAUD = _define("TGT_BAUD")
TPMS = int(re.search(r"#define\s+TGT_TICKS_PER_MS_X10\s+(\d+)", _t).group(1))
WORDS_START = _define("TGT_ASIC_WORDS_START")
WORDS_RUN = _define("TGT_ASIC_WORDS_RUN")
FRAMEA = _define("TGT_ASIC_FRAME")

S0RBUF, S0RIC, S0TBUF, S0TIC = 0x00FEB2, 0x00FF6E, 0x00FEB0, 0x00FF6C
S0TBIC = 0x00F19C          # ESFR (C167CR UM V3.1: F19CH, E)
SSCTIC, SSCRIC, SSCCON = 0x00FF72, 0x00FF74, 0x00FFB2
SSCTB, SSCRB = 0x00F0B0, 0x00F0B2       # reg167.h
PECC0, PECC4, PECC6 = 0x00FEC0, 0x00FEC8, 0x00FECC
DSTP6 = 0x00FCFA                      # PEC pointer file (reg167.h), IRAM space
S0CON, PSW_SFR = 0x00FFB0, 0x00FF10
S0RIC_PEC6 = 0x7E                     # IE | ILVL 15 | GLVL 2 -> PEC channel 6
ADCON, ADDAT = 0x00FFA0, 0x00FEA0

BUDGET_MS = 10.0
HB_BODY_STEPS = 128                   # generous bound on hb_service()'s body

# ============================ THE SIMULATED MILLISECOND, DERIVED NOT CHOSEN ==
#
# Every number this rig produces is an INSTRUCTION COUNT, and both gates that
# use it convert instructions to hardware milliseconds at fCPU / clocks. For
# that conversion to mean anything the SIMULATOR's timers must advance on the
# same basis, or a gate ends up holding two different milliseconds at once.
#
# The ratio is a hardware fact, not a modelling choice:
#
#     CAPCOM timer   TGT_TICKS_PER_MS_X10 / 10 * 1000  =  1.25 MHz
#     instructions   TGT_FCPU_HZ / CLOCKS_PER_INSTR    =  10 MIPS
#     ------------------------------------------------------------
#     instructions per timer tick                      =  8
#
# and with T8's 1250-tick reload that is 10 000 instructions per hc_tick_ms -
# exactly the millisecond me711_ts_gap_proof.hw_ms() reports.
#
# c167sim ships 2, which makes simulated time run four times too fast against
# the instruction stream. CLOCKS_PER_INSTR is 4 here for the same reason it is
# 4 there: twice the C166 architectural floor, to absorb taken branches, calls
# and BUSCON1's external-SRAM wait states.
CLOCKS_PER_INSTR = 4
_TIMER_HZ = TPMS * 100.0                       # 12500 -> 1.25 MHz
STEPS_PER_TICK = int(round((_define("TGT_FCPU_HZ") / CLOCKS_PER_INSTR)
                           / _TIMER_HZ))
if STEPS_PER_TICK < 1:
    raise SystemExit("derived STEPS_PER_TICK is nonsense: %r" % STEPS_PER_TICK)
# One T8 period must equal one reported hardware millisecond, or the two halves
# of every latency check below have drifted apart again.
_T8_INSTR = _define("TGT_TICK_RELOAD") * STEPS_PER_TICK
_HW_MS_INSTR = _define("TGT_FCPU_HZ") / CLOCKS_PER_INSTR / 1000.0
if abs(_T8_INSTR - _HW_MS_INSTR) > 1.0:
    raise SystemExit("the simulated millisecond (%d instructions) and the "
                     "reported hardware millisecond (%d) disagree"
                     % (_T8_INSTR, _HW_MS_INSTR))

STEPS_BOUND = 3_600_000              # ~1.4 s - Phase A (V17), 1 beat window
STEPS_REAL = 7_000_000              # ~2.8 s - Phase B, room for 2+ beats
WARMUP_MS = 40
STEPS_PER_MS = 2500                   # c167sim: 2 steps/tick, 1250 ticks/ms


def sym(name):
    for m in re.finditer(r"^\s*([0-9A-F]{6})H\s+(\w+)\s",
                          MAP.read_text(errors="replace"), re.M):
        if m.group(2) == name:
            return int(m.group(1), 16)
    raise SystemExit(f"{name} not in {MAP.name} - build the target first")


# V17 is a frozen archived image, so its addresses are constants (they match
# the V17 bench card). The
# current image's addresses come
# from the live linker map.
ENTRY_V17, TICK_V17 = 0x8E669E, 0x00FA86
ENTRY_CURRENT, TICK_CURRENT = sym("hc_asic_start_service"), sym("hc_tick_ms")


class Rig:
    """One image, ASC0 + ADC modelled, a persistent modelled S5500 keeping the
    runtime SSC exchange flowing. The K-line is QUIET unless rx bytes are
    injected; every transmitted byte is captured with its tick_ms."""

    def __init__(self, img_path, entry_pc, tick_ms, echo=False,
                 run_tx_addr=None, steps_per_tick=None):
        img = img_path.read_bytes()
        off = img[0x8000] | (img[0x8001] << 8)
        seg = img[0x8002] | (img[0x8003] << 8)
        self.mem = S.Mem(img)
        self.cpu = S.CPU(self.mem, seg, off)
        # KL15 IS ON. P6.2 is the CJ910's KL15_STAT input, and since V79 a LOW
        # there is a KEY-OFF: outputs inhibited, run-on engaged. The simulator
        # resets P6 to 0, which is an ECU whose key has just been turned off.
        # Every rig built on this one models a running ECU, so the pin is set
        # the way the bench measured it (V78 baseline: outputPins bit 7 = 1).
        # The startup only BSETs P6.3/P6.4, so this bit survives it.
        self.mem.w16(0xFFCC, self.mem.r16(0xFFCC) | 0x0004)
        # ONE MILLISECOND, NOT TWO.
        #
        # This rig exists to measure how long the main loop can go without
        # servicing the 10 ms S5500 raster, and both gates that use it convert
        # the answer to hardware milliseconds at fCPU/CLOCKS_PER_INSTR.  The
        # simulator's own millisecond has to be that same millisecond or the
        # measurement compares two different units - which is exactly what it
        # did until V49: c167sim's default of 2 instructions per timer tick
        # makes a simulated millisecond 2500 instructions while the gates call
        # a millisecond 10000, a factor of four.
        #
        # The consequence was not a constant offset, which would have been
        # noticed.  A tick-gated yield services once per hc_tick_ms change, so
        # with the tick running four times too fast the service pattern becomes
        # hypersensitive to where each yield call lands relative to a tick
        # edge.  V49's added instrumentation shifted those phases by a few
        # thousand instructions and all sixteen yields of one 4096-byte
        # crc_block fell inside already-consumed tick windows, reporting a
        # 123934-instruction gap for firmware that is FASTER than V48.
        # Corrected, V48 measures 2.75 ms and V49 2.34 ms - and both agree with
        # the closed-form bound of two 256-byte chunks.
        # OPT-IN, because nineteen gates share this rig and only two of them
        # measure a TIME BUDGET.  Pass steps_per_tick=STEPS_PER_TICK to get a
        # simulated millisecond that equals the hardware millisecond those two
        # report; leave it None and the shipped c167sim modelling default is
        # untouched, so no other gate is silently re-baselined.
        if steps_per_tick is not None:
            self.cpu.steps_per_tick = steps_per_tick
        self.steps_per_tick = self.cpu.steps_per_tick
        self.entry_pc = entry_pc
        self.tick_ms = tick_ms
        self.echo = echo
        # hb_service() is static (not in the map). It is the only function in
        # ?PR?HCMAIN_BOSCH that starts by loading rx_reqs (0x00F9EE, DPP2
        # form 0xB9EE): MOV R4, B9EE  ==  F2 F4 EE B9.
        pat = bytes((0xF2, 0xF4, 0xEE, 0xB9))
        # Link order moves this private function as modules are added. The
        # identifying load is unique across the complete HaniCore sector; a
        # hardcoded V20 window made V21 report zero calls while "H\n" was
        # visibly present on the simulated wire.
        i = img.find(pat, 0x0E0200, 0x0F0000)
        self.hb_pc = (0x8E0000 | (i - 0x0E0000)) if i >= 0 else None
        self._hb_in = None
        self.hb_span = 0        # worst instruction span of one hb_service call
        self.hb_calls = 0
        self.byte_ticks = int(10 * (TPMS / 10.0) * 1000 / BAUD)
        self.rxq = bytearray()
        self.entries = []        # (tick_ms, step) at each hc_asic_start_service
        self.tx = []             # (tick_ms, byte) for every S0TBUF write
        self.tx_steps = []       # matching simulator step for each TX byte
        self.run_tx_addr = run_tx_addr
        self.run_tx_events = []  # (tick_ms, step, count) at each runtime TX
        self._run_tx_last = (self.mem.r16(run_tx_addr)
                             if run_tx_addr is not None else None)
        self._pending_rx = []     # (deliver_at_step, bytes)
        # S0TIC bit 7 = the ASC0 transmit-interrupt REQUEST LATCH (see the
        # module docstring and tests/firmware/build/me711_boot_test.py): raised by HW once,
        # byte_ticks after an S0TBUF write; cleared by a software write with
        # bit 7 low; never a persistent "buffer free" level.
        self._tx_ir = 0
        self._tx_evt_at = None
        # V94: THE TRANSMITTER IS DOUBLE BUFFERED (C167CR UM V3.1 11): a byte
        # loaded while the shift register is idle moves into it at once and
        # S0TBIC.7 (S0TBIR) is raised; loaded while a byte is shifting, it
        # waits in S0TBUF and moves (raising S0TBIR) when that frame ends.
        # The latch lives in the simulator's own ESFR dictionary, so bit
        # instructions and byte accesses see the same flag; this model only
        # ever SETS it. tx_wire_steps is when each byte started on the wire
        # (tx_steps stays the S0TBUF write). Firmware up to V93 never loads
        # a second byte early, so for it this changes nothing.
        self.byte_steps = self.byte_ticks * self.steps_per_tick
        # 2026-10-06: THE WIRE RECEIVER, modelled once the firmware arms PEC6
        # (S0RIC = 0x7E). Before that, and for every image that never arms it,
        # the old model stands: S0RBUF pops rxq at once. Armed, rxq is the
        # LINE: one byte completes every byte_steps into the single S0RBUF; a
        # byte that completes while the previous one is still there sets S0OE
        # and overwrites it (C167CR UM 11, overrun); a pending byte is moved by
        # PEC6 only while the CPU runs below level 15 with IEN set, to DSTP6,
        # counting PECC6 down (COUNT 0xFF = continuous); at COUNT 0 the request
        # is a normal interrupt, which on this ECU is the boot block's S0RINT -
        # the byte is gone (c167sim CPU.pec6_lost).
        self._rbuf = 0
        self._rbuf_full = False
        self._rx_next_at = None
        self.rx_overruns = 0
        self._sh_end = None       # step at which the byte shifting ends
        self._sh_buf = None       # a byte waiting in S0TBUF
        self.tx_wire_steps = []
        h = self
        o8, ow8, ow16 = S.Mem.r8, S.Mem.w8, S.Mem.w16

        def r8(s_, a, _o=o8):
            a &= 0xFFFFFF
            if a == S0RIC:
                if (s_.sfr.get(S0RIC, 0) & 0x7F) == S0RIC_PEC6:
                    return S0RIC_PEC6 | (0x80 if h._rbuf_full else 0)
                # The REGISTER reads back whole (IE/ILVL/GLVL as written) with
                # the request bit. Returning the request bit alone made the
                # flash routine's restore `S0RIC |= IE` (after its masked
                # window) write 0xC0 over 0x7E: PEC6 never re-armed and the
                # rig stopped receiving after every Burn (2026-10-09).
                return (s_.sfr.get(S0RIC, 0) & 0x7F) | (0x80 if h.rxq else 0x00)
            if a == S0TIC:
                t7 = h.cpu._sget(S.TIMERS["T7"][0])
                if (h._tx_evt_at is not None
                        and ((t7 - h._tx_evt_at) & 0xFFFF) >= h.byte_ticks):
                    h._tx_ir = 0x80
                    h._tx_evt_at = None
                return (s_.sfr.get(S0TIC, 0) & 0x7F) | h._tx_ir
            if a in (S0RIC + 1, S0TIC + 1, S0RBUF + 1):
                return 0x00
            if a == S0RBUF:
                if (s_.sfr.get(S0RIC, 0) & 0x7F) == S0RIC_PEC6:
                    h._rbuf_full = False
                    return h._rbuf
                return h.rxq.pop(0) if h.rxq else 0
            return _o(s_, a)

        def w8(s_, a, v, _o=ow8):
            aa = a & 0xFFFFFF
            if aa == S0TBUF:
                t7 = h.cpu._sget(S.TIMERS["T7"][0])
                h._tx_evt_at = t7
                h._tx_ir = 0
                if h._sh_end is None:
                    h._shift_start(h.cpu.steps)
                else:
                    h._sh_buf = v & 0xFF
                h.tx.append((h.mem.r16(h.tick_ms), v & 0xFF))
                h.tx_steps.append(h.cpu.steps)
                if h.echo:                    # K-line loops TX back to RX
                    h.rxq.append(v & 0xFF)
            elif aa == S0TIC:
                if v & 0x80:
                    h._tx_ir = 0x80
                else:
                    h._tx_ir = 0
                    h._tx_evt_at = None
            return _o(s_, a, v)

        def w16(s_, a, v, _o=ow16):
            aa = a & 0xFFFFFF
            if aa == ADCON and (v & 0x80):
                s_.sfr[ADDAT] = ((v & 0x0F) << 12) | (100 + (v & 0x0F) * 37)
            if aa == SSCTIC and (v & 0x0080):
                n = (s_.r16(PECC4) & 0x00FF) or WORDS_START
                rx = [0] * n
                rx[0] = 0x7800 | (0x2E if n == WORDS_RUN else 0x1E)
                rx[n - 1] = sum(rx[:n - 1]) & 0xFFFF
                if getattr(h, "asic_mute", False):
                    # 2026-10-07: an S5500 that is not answering yet (late
                    # ASIC start): a frame whose checksum is wrong (an
                    # all-zero frame sums to its own zero checksum and is
                    # ACCEPTED - acceptance is the checksum, hcasicstart.c).
                    rx = [0] * n
                    rx[n - 1] = 0x5A5A
                for i, w in enumerate(rx):
                    _o(s_, FRAMEA + 2 * i, w)
                _o(s_, PECC0, s_.r16(PECC0) & 0xFF00)
                _o(s_, PECC4, s_.r16(PECC4) & 0xFF00)
                # SSCCON bits 8..11 are error ENABLES while SSCEN=0, but
                # become TE/RE/PE/BE status flags while SSCEN=1.  The old
                # model carried the programmed 0x0600 enables into operating
                # mode as two permanent errors, which made V47/V48 live-Burn
                # admission reject every otherwise-idle window.  A successful
                # modelled exchange has neither BUSY nor an error status.
                #
                # READ THAT PARAGRAPH AGAIN BEFORE TRUSTING THIS RIG ABOUT
                # ADMISSION.  The simulator reproduced the V50 stall two
                # releases EARLY, and the response was to change the MODEL
                # until it stopped happening rather than to ask whether the
                # firmware should be reading those bits at all.  On hardware
                # nothing clears them - C167CR UM V3.1 section 12.7 says
                # software must, and SSCEIC is left with SSCEIE = 0 - so V50
                # programmed 36 of 2060 words and was refused 4993 times.
                # See the maintainer's design records.
                #
                # AND THIS EXCHANGE COSTS NO SIMULATED TIME.  The whole frame
                # lands inside the single w16 that writes SSCTIC's request
                # bit, so `in_flight` clears at once where the real part holds
                # it for TGT_ASIC_WORDS_RUN = 118 words = 1.89 ms of a 10 ms
                # raster.  THIS RIG THEREFORE READS ADMISSION OPTIMISTICALLY
                # AND CANNOT PREDICT THE REAL DUTY CYCLE.  It is a liveness
                # and regression rig, not a duty-cycle measurement.
                s_.sfr[SSCCON] = s_.r16(SSCCON) & ~0x1F00
                s_.sfr[SSCTIC] = s_.r16(SSCTIC) | 0x0080
                s_.sfr[SSCRIC] = s_.r16(SSCRIC) | 0x0080
                h.cpu.irq_pending.add(SSCTIC)
                h.cpu.irq_pending.add(SSCRIC)
            if aa == SSCTB and getattr(h, "ssc_dead", False):
                # V97 me711_wideband_ssc_bound_proof: an SSC that never
                # completes a CJ120 byte (no SSCRIC) - the firmware's own
                # bound is all that ends the wait.
                return _o(s_, a, v)
            if aa == SSCTB:
                # V97: A SINGLE SSC BYTE (hcio711.c cj_xfer(), the CJ120's
                # 8-bit exchanges, polled with SSCRIE off). Until V97 this rig
                # modelled only the S5500 frame, so every CJ120 byte ran
                # ssc_byte()'s whole 2000-pass timeout - 6.4 ms of simulated
                # main-loop time per transfer that the part spends in 8 us
                # (SSCBR 0x13 = 1 MHz, 8 bits) - and a page with lambda on
                # read as an 8.8 ms S5500 gap. Instrument, not firmware. The
                # byte completes at once (as the frame above does); no chip
                # is modelled, so SSCRB reads 0x00 and the CJ120 state
                # machine keeps restarting - which costs the same per slot.
                _o(s_, SSCRB, 0x0000)
                s_.sfr[SSCRIC] = s_.r16(SSCRIC) | 0x0080
            return _o(s_, a, v)

        S.Mem.r8, S.Mem.w8, S.Mem.w16 = r8, w8, w16
        self._hooks = (r8, w8, w16)
        self._restore = (o8, ow8, ow16)

    def _shift_start(self, at):
        self._sh_end = at + self.byte_steps
        self.tx_wire_steps.append(at)
        self.mem.esfr[S0TBIC] = self.mem.esfr.get(S0TBIC, 0) | 0x80
        self.cpu.irq_pending.add(S0TBIC)      # S0TBINT, if S0TBIE (2026-10-06)

    def wire_step(self):
        """The PEC6 wire receiver (see __init__). Called every step."""
        sfr = self.mem.sfr
        if (sfr.get(S0RIC, 0) & 0x7F) != S0RIC_PEC6:
            return
        steps = self.cpu.steps
        if self._rx_next_at is None:
            if self.rxq:
                self._rx_next_at = steps + self.byte_steps
        elif steps >= self._rx_next_at:
            b = self.rxq.pop(0) if self.rxq else 0
            if self._rbuf_full:
                sfr[S0CON] = sfr.get(S0CON, 0) | 0x0400   # S0OE
                self.rx_overruns += 1
            self._rbuf = b
            self._rbuf_full = True
            self._rx_next_at = (steps + self.byte_steps) if self.rxq else None
        # The transfer itself is c167sim's (CPU.check_irq, PEC6), through
        # the S0RIC/S0RBUF hooks above: the same model every harness uses.

    def _shift_end(self):
        at = self._sh_end
        self._sh_end = None
        if self._sh_buf is not None:
            self._sh_buf = None
            self._shift_start(at)

    def queue_rx(self, at_step, data):
        self._pending_rx.append((at_step, bytes(data)))

    def run(self, steps):
        # ADVANCE THE CPU. SAFE TO CALL MORE THAN ONCE ON THE SAME RIG.
        #
        # THE HOOKS ARE CLASS-LEVEL MONKEY PATCHES ON S.Mem, installed by
        # __init__ and removed by the LAST LINE of this function. Until
        # 2026-09-06 they were not re-installed here, so a rig driven by a
        # SECOND run() call executed against a bare Mem: no ASC0, no S0RBUF,
        # no transmit capture, no ADC, no modelled S5500. Every gate in the
        # tree happened to call run() exactly once per rig, so nothing
        # noticed.
        #
        # It surfaced as a firmware bug, which is this project's recurring
        # shape for a simulator defect - the fifth time. V40's Burn no longer
        # ends in a reset, so proving it means sending a command, ADVANCING
        # IN SMALL SLICES until the deferred reply appears, and then sending
        # the next one on the same CPU. That is the first test in the tree to
        # drive a rig incrementally, and it reported that the ECU never
        # answered a Burn. The ECU never RECEIVED one: the bytes were queued
        # into a receive model that was no longer connected.
        #
        # ONLY WHEN NOTHING ELSE OWNS THEM, which is the other half of this.
        # me711_output_safety_test wraps S.Mem.w8/w16 around the rig's hooks to
        # take a census of port writes, and an unconditional re-install here
        # threw its wrappers away and reported zero writes - the same class of
        # silent failure, one layer up. If r8 is still the ORIGINAL then the
        # last run() uninstalled and this rig has to put them back; if it is
        # anything else, somebody is deliberately in the chain and it is left
        # exactly as it is.
        if S.Mem.r8 is self._restore[0]:
            S.Mem.r8, S.Mem.w8, S.Mem.w16 = self._hooks
        cpu, mem = self.cpu, self.mem
        hb_lo = self.hb_pc or -1
        hb_hi = (self.hb_pc + 0x90) if self.hb_pc else -1
        try:
            for _ in range(steps):
                if self._pending_rx and cpu.steps >= self._pending_rx[0][0]:
                    self.rxq.extend(self._pending_rx.pop(0)[1])
                if self._sh_end is not None and cpu.steps >= self._sh_end:
                    self._shift_end()
                self.wire_step()
                pc = (cpu.csp << 16) | cpu.ip
                if self.run_tx_addr is not None:
                    run_tx = mem.r16(self.run_tx_addr)
                    if run_tx != self._run_tx_last:
                        self.run_tx_events.append(
                            (mem.r16(self.tick_ms), cpu.steps, run_tx))
                        self._run_tx_last = run_tx
                if cpu.ext is None and pc == self.entry_pc:
                    self.entries.append((mem.r16(self.tick_ms), cpu.steps))
                if pc == self.hb_pc:
                    self._hb_in = cpu.steps
                    self.hb_calls += 1
                elif self._hb_in is not None and not (hb_lo <= pc < hb_hi):
                    self.hb_span = max(self.hb_span, cpu.steps - self._hb_in)
                    self._hb_in = None
                cpu.step()
        except S.Trap as e:
            self.trap = str(e)
            # AN INSTRUMENT GAP IS NEVER SILENT (V97). An unimplemented
            # opcode stopped V97's first image 300k steps into boot and the
            # OCH gate reported "no valid envelope" - a firmware-shaped
            # symptom of a simulator hole. Every gate on this rig now says so.
            if "UNIMPLEMENTED" in self.trap:
                print("SIMULATOR GAP (not a firmware result): %s at step %d"
                      % (self.trap, self.cpu.steps), file=sys.stderr)
        else:
            self.trap = None
        S.Mem.r8, S.Mem.w8, S.Mem.w16 = self._restore

    def gap_steps(self):
        e = [x for x in self.entries if x[0] >= WARMUP_MS]
        return [s1 - s0 for (_, s0), (_, s1) in zip(e, e[1:])]

    def worst_gap_ms(self):
        g = self.gap_steps()
        return (max(g) / STEPS_PER_MS) if g else 0.0


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p / 100.0))]


FAILS = 0


def check(name, ok, detail=""):
    global FAILS
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<58s} {detail}")
    if not ok:
        FAILS += 1


def phase_a():
    print("=== PHASE A - conservative bound, frozen V17 image (no heartbeat) ===\n")
    rig = Rig(V17, ENTRY_V17, TICK_V17)
    rig.run(STEPS_BOUND)
    gaps = rig.gap_steps()
    check("V17 boots and runs cleanly (no trap)",
          rig.trap is None and len(gaps) > 500,
          f"{len(rig.entries)} service calls, trap={rig.trap}")

    base_max = max(gaps)
    base_ms = base_max / STEPS_PER_MS
    hb_ms = (base_max + HB_BODY_STEPS) / STEPS_PER_MS
    print(f"\n  V17 gap      median {pct(gaps, 50)} / p99 {pct(gaps, 99)} / "
          f"max {base_max} steps = {base_ms:.2f} ms")
    print(f"  + hb_service body (<= {HB_BODY_STEPS} steps)  ->  {hb_ms:.2f} ms\n")
    check("bound: worst gap + hb_service body stays under the 10 ms budget",
          hb_ms < BUDGET_MS, f"{hb_ms:.2f} ms < {BUDGET_MS:.0f} ms")
    check("and with at least 2x margin",
          hb_ms < BUDGET_MS / 2.0, f"{BUDGET_MS - hb_ms:.2f} ms spare")
    return base_ms


def phase_b(v17_ms):
    print(f"\n=== PHASE B - selected {PI.EXPECTED_BUILD} image, run for real ===\n")
    rig = Rig(CURRENT, ENTRY_CURRENT, TICK_CURRENT, echo=True)
    print(f"  hb_service() located at 0x{rig.hb_pc:06X}" if rig.hb_pc
          else "  hb_service() NOT LOCATED")
    rig.run(STEPS_REAL)
    gaps = rig.gap_steps()

    check(f"{PI.EXPECTED_BUILD} boots and runs cleanly, quiet line (no trap)",
          rig.trap is None and len(gaps) > 500,
          f"{len(rig.entries)} service calls, trap={rig.trap}")
    check("hb_service() is reached every main-loop pass",
          rig.hb_calls > 1000, f"{rig.hb_calls} calls")

    # "H\n" on the wire (boot text is done well before tick_ms 300)
    hb = [(t, b) for (t, b) in rig.tx if t > 300]
    text = bytes(b for _, b in hb)
    hs = [t for (t, b) in hb if b == ord('H')]
    check("\"H\\n\" actually goes out on the quiet line", b"H\n" in text,
          f"{text[:16]!r} ...  'H' at tick_ms {hs}")
    check("at least two heartbeats went out (cadence measurable)",
          len(hs) >= 2, f"{len(hs)} beats")
    if len(hs) >= 2:
        sp = [hs[i + 1] - hs[i] for i in range(len(hs) - 1)]
        check("heartbeat cadence is ~1000 ms",
              all(900 <= s <= 1100 for s in sp), f"gaps {sp} ms")

    # no blocking wait: hb_service()'s own worst-case instruction span
    check("hb_service() never blocks (worst-case body span is tiny)",
          0 < rig.hb_span <= 400,
          f"worst span {rig.hb_span} steps (a blocking wait would be 1000s)")

    current_ms = rig.worst_gap_ms()
    print(f"\n  V17 quiet worst gap  {v17_ms:.2f} ms")
    print(f"  {PI.EXPECTED_BUILD} quiet worst gap  {current_ms:.2f} ms   "
          f"(delta {current_ms - v17_ms:+.2f} ms; selected image includes runtime)\n")
    check("selected image's measured worst service gap is under the 10 ms budget",
          current_ms < BUDGET_MS, f"{current_ms:.2f} ms")
    check("selected image's measured gap retains at least 2x margin",
          current_ms < BUDGET_MS / 2.0,
          f"{current_ms:.2f} ms, {BUDGET_MS - current_ms:.2f} ms spare")

    # stand-down once a TunerStudio request completes
    rig2 = Rig(CURRENT, ENTRY_CURRENT, TICK_CURRENT, echo=True)
    import zlib
    env = (1).to_bytes(2, "big") + b"S" + zlib.crc32(b"S").to_bytes(4, "big")
    rig2.queue_rx(int(600 * STEPS_PER_MS), env)
    rig2.run(int(1600 * STEPS_PER_MS))
    check("the request is answered (signature on the wire)",
          b"HaniCore ME711" in bytes(b for _, b in rig2.tx), "signature present")
    stray = [t for (t, b) in rig2.tx if t > 950 and b in (ord('H'), ord('\n'))]
    check("the heartbeat stands down after one completed request (rx_reqs)",
          not stray, "silent after rx_reqs>0" if not stray
          else f"{len(stray)} stray byte(s) at {stray}")


def main():
    if not V17.exists() or not MAP.exists():
        raise SystemExit("need the V17 image and the current linker map")
    v17_ms = phase_a()
    if CURRENT.exists():
        phase_b(v17_ms)
    else:
        print("\n(PHASE B skipped - no current image found)")

    print()
    if FAILS:
        print(f"HEARTBEAT PROOF FAILED ({FAILS} check(s))")
        return 1
    print("HEARTBEAT PROOF PASSES - 'H\\n' goes out once per second, "
          "hb_service() never blocks,")
    print("and the hc_asic_start_service() service gap stays well under the "
          "10 ms supervision budget.")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
