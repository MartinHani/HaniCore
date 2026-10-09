#!/usr/bin/env python3
r"""
me711_boot_test.py - execute the CLEAN Bosch image in the C167 simulator
and check what a bench would check, before spending a flash cycle on it.

    py tests\firmware\build\me711_boot_test.py

It starts the CPU at the reset the boot block would hand over at - which the
image's own ROMSYS header names, so the entry is read out of the image rather
than typed here - and then asks the questions the first bench test asks:

    does it reach the main loop, or trap on the way?
    does the banner come out, and does CAL read what the clock says it should?
    does the 1 ms tick run?
    do interrupts land where HaniCore put them, or on a catch-all?
    does the TunerStudio server answer its signature, page and channels?
    does the ASIC link recover from a wedged SSC by re-initialising rather
      than waiting on it forever, while serial, timers, persistence and
      ADC service continue?

Anything that fails here would have failed on the bench.
"""
from __future__ import annotations

import os
import re
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import c167sim as S  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
import me711_image as PI  # ONE source of truth for the image under test
IMG = PI.image()
TGT = ROOT / "firmware/targets/me711/hctarget.h"

S0RBUF, S0RIC, S0TBUF, S0TIC = 0x00FEB2, 0x00FF6E, 0x00FEB0, 0x00FF6C
S0TBIC = 0x00F19C          # ESFR (C167CR UM V3.1: F19CH, E)
ADCON, ADDAT = 0x00FFA0, 0x00FEA0
S0CON = 0x00FFB0            # S0LB is bit 14 (sbit S0LB = S0CON^14, reg167.h)
S0LB_MASK = 0x4000
SSCCON = 0x00FFB2

_tgt = TGT.read_text(errors="replace")
_meta = PI.metadata()


def define(name, default=None):
    m = re.search(r"#define\s+%s\s+(0x[0-9A-Fa-f]+|\d+)" % name, _tgt)
    if not m:
        if default is not None:
            return default
        raise SystemExit(f"{name} not found in hctarget.h")
    return int(m.group(1), 0)


OCH_SIZE = int(_meta["och_size"])
BAUD = int(_meta["baud"])
TICKS_PER_MS_X10 = int(re.search(r"#define\s+TGT_TICKS_PER_MS_X10\s+(\d+)",
                                 _tgt).group(1))
SIGNATURE = _meta["signature"]
EXTRAM = define("TGT_EXTRAM_BASE")
RAM_OCH = define("TGT_RAM_OCH")
RAM_RSTLOG = define("TGT_RAM_RSTLOG")

# Fake but distinct ADC counts so a channel mix-up is visible.
ADC_TEST = {ch: 100 + ch * 37 for ch in range(16)}
ADC_TEST[5] = 800          # battery: 800/1023 * 17.0 V = 13.3 V

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<50s} {detail}")
    return ok


def frame(payload: bytes) -> bytes:
    return (len(payload).to_bytes(2, "big") + payload
            + zlib.crc32(payload).to_bytes(4, "big"))


def parse(stream: bytes):
    """Find the first CRC-valid reply anywhere in the stream.

    Not at offset 0, deliberately. The firmware emits free-running diagnostic
    text while nobody is talking to it, and a line started in the few hundred
    microseconds before a request is parsed lands in front of the reply. That
    is correct behaviour on a bench terminal and TunerStudio retries through it
    during detection - so the test scans, rather than pretending the wire is
    tidier than it is. The CRC is what makes the scan safe: a false start would
    have to produce a valid length AND a matching CRC32."""
    for i in range(0, max(0, len(stream) - 6)):
        n = int.from_bytes(stream[i:i + 2], "big")
        # A whole current OCH is 680 bytes plus the response status byte.
        # Keep the scanner bounded by the 4-KiB protocol page, not the obsolete
        # 512-byte OCH size that otherwise discards a CRC-valid full reply.
        if n == 0 or n > 4097 or len(stream) < i + 2 + n + 4:
            continue
        body = stream[i + 2:i + 2 + n]
        crc = int.from_bytes(stream[i + 2 + n:i + 6 + n], "big")
        if crc == zlib.crc32(body):
            return (body[0], body[1:], True), stream[i + 6 + n:]
    return None, stream


class Harness:
    """The image, with ASC0 and the ADC modelled.

    echo reproduces the K-line: one shared wire, so everything the ECU
    transmits comes straight back into its own receiver. The CJ910 does this on
    the Bosch board exactly as the ME7.5 board's transceiver does, and the
    protocol has to be proven with it ON.
    """

    def __init__(self, path, echo=True):
        self.img = open(path, "rb").read()
        # The entry comes out of the image's own header, so this harness cannot
        # drift away from what the boot block would really do.
        off = self.img[0x8000] | (self.img[0x8001] << 8)
        seg = self.img[0x8002] | (self.img[0x8003] << 8)
        self.entry = (seg << 16) | off
        self.mem = S.Mem(self.img)
        self.cpu = S.CPU(self.mem, seg, off)
        self.echo = echo
        self.rxq = bytearray()
        self.txb = bytearray()
        # A transmitted byte takes a byte time, and modelling it as instant is
        # not harmless: cal_measure() measures T7 ticks BETWEEN two
        # transmit-complete events, and an instant UART would make CAL read 4.
        self.byte_ticks = int(10 * (TICKS_PER_MS_X10 / 10.0) * 1000 / BAUD)
        self.tx_done_at = 0
        # S0TIC bit 7 modelled as the ASC0 transmit-interrupt REQUEST LATCH it
        # actually is: hardware raises it ONCE, byte_ticks after an S0TBUF
        # write (the buffer->shifter transfer event); software clears it by
        # writing the register with bit 7 low; it does NOT behave as a
        # persistent "buffer free" level and does NOT re-assert on its own
        # while the transmitter is idle. Modelling it as a level is exactly
        # what hid the V18 heartbeat defect (hb_service() gated on S0TIC&0x80,
        # which after the boot banner is 0 forever).
        self._tx_ir = 0            # current latched S0TIC.7
        self._tx_evt_at = None     # T7 at which a pending transfer raises it
        # V94: the transmitter is DOUBLE BUFFERED (C167CR UM V3.1 11) and
        # S0TBIC.7 (S0TBIR) rises when S0TBUF moves into the shift register:
        # at once on an idle line, else when the shifting frame ends. Same
        # model as me711_heartbeat_gap_proof.Rig; the latch lives in the ESFR
        # dictionary so bit and byte accesses agree. Up to V93 nothing loads
        # a second byte early, so for those images nothing changes.
        self._sh_end = None
        self._sh_buf = None
        orig_r8, orig_w8, orig_w16 = S.Mem.r8, S.Mem.w8, S.Mem.w16
        h = self

        def _s0tic_byte(self_):
            t7 = h.cpu._sget(S.TIMERS["T7"][0])
            if (h._tx_evt_at is not None
                    and ((t7 - h._tx_evt_at) & 0xFFFF) >= h.byte_ticks):
                h._tx_ir = 0x80
                h._tx_evt_at = None
            return (self_.sfr.get(S0TIC, 0) & 0x7F) | h._tx_ir

        def r8(self_, a, _o=orig_r8):
            a &= 0xFFFFFF
            if a == S0RIC:
                return 0x80 if h.rxq else 0x00
            if a == S0RIC + 1:
                return 0x00
            if a == S0TIC:
                return _s0tic_byte(self_)
            if a == S0TIC + 1:
                return 0x00
            if a == S0RBUF:
                return h.rxq.pop(0) if h.rxq else 0
            if a == S0RBUF + 1:
                return 0
            return _o(self_, a)

        def w16(self_, a, v, _o=orig_w16):
            if (a & 0xFFFFFF) == ADCON and (v & 0x80):
                ch = v & 0x0F
                self_.sfr[ADDAT] = (ch << 12) | ADC_TEST[ch]
            return _o(self_, a, v)

        def w8(self_, a, v, _o=orig_w8):
            aa = a & 0xFFFFFF
            if aa == S0TBUF:
                # S0LB (S0CON bit 14) is the ASC0 INTERNAL loopback the
                # firmware already relies on in hcts_rx_learn() and, since
                # V23, in cal_measure(): hardware-documented (see
                # docs/ARCHITECTURE.md) to tie the transmitter to
                # the receiver INSIDE the chip and keep the byte off the
                # wire. Model that distinction, or this harness cannot tell
                # "goes out on K-line" from "stays on-chip" - which is
                # exactly what tests/firmware/asic/me711_idle_silence_proof.py needs.
                s0lb = bool(h.mem.sfr.get(S0CON, 0) & S0LB_MASK)
                if not s0lb:
                    h.txb.append(v & 0xFF)
                t7 = h.cpu._sget(S.TIMERS["T7"][0])
                h.tx_done_at = (t7 + h.byte_ticks) & 0xFFFF
                h._tx_evt_at = t7      # HW will raise S0TIC.7 byte_ticks later
                h._tx_ir = 0
                if h._sh_end is None:
                    h._shift_start(h.cpu.steps)
                else:
                    h._sh_buf = v & 0xFF
                if h.echo or s0lb:
                    h.rxq.append(v & 0xFF)
            elif aa == S0TIC:
                if v & 0x80:
                    h._tx_ir = 0x80    # e.g. hcts_init()'s S0TIC |= 0x80
                else:
                    h._tx_ir = 0       # software cleared the request
                    h._tx_evt_at = None
            return _o(self_, a, v)

        S.Mem.r8, S.Mem.w8, S.Mem.w16 = r8, w8, w16

    def _shift_start(self, at):
        self._sh_end = at + self.byte_ticks * self.cpu.steps_per_tick
        self.mem.esfr[S0TBIC] = self.mem.esfr.get(S0TBIC, 0) | 0x80

    def run(self, steps):
        try:
            for _ in range(steps):
                self.cpu.step()
                if self._sh_end is not None and self.cpu.steps >= self._sh_end:
                    at, self._sh_end = self._sh_end, None
                    if self._sh_buf is not None:
                        self._sh_buf = None
                        self._shift_start(at)
        except S.Trap as e:
            return str(e)
        return None

    def send(self, payload: bytes, steps=1500000):
        self.txb.clear()
        self.rxq.extend(frame(payload))
        err = self.run(steps)
        return bytes(self.txb), err

    def send_raw(self, data: bytes, steps=800000):
        self.txb.clear()
        self.rxq.extend(data)
        err = self.run(steps)
        return bytes(self.txb), err

    def och(self, off, n):
        """Read the output-channel block straight out of the modelled SRAM."""
        base = EXTRAM + RAM_OCH + off
        return bytes(self.mem.r8(base + i) for i in range(n))



def hcts_trace_on(h):
    """hc_trace_on lives in near RAM; find it through the linker map."""
    import re as _re
    mp = PI.MAP
    m = _re.search(r"^\s*([0-9A-F]{6})H\s+hc_trace_on",
                   mp.read_text(errors="replace"), _re.M)
    if not m:
        return 0
    return h.mem.r8(int(m.group(1), 16))

_MAPCACHE = {}


def sym_addr(name):
    """Address of a firmware symbol, from the linker map."""
    import re as _re
    if not _MAPCACHE:
        mp = PI.MAP
        for m in _re.finditer(r"^\s*([0-9A-F]{6})H\s+(\w+)",
                              mp.read_text(errors="replace"), _re.M):
            _MAPCACHE.setdefault(m.group(2), int(m.group(1), 16))
    return _MAPCACHE.get(name)


def _sym_u16(self, name):
    a = sym_addr(name)
    return self.mem.r16(a) if a is not None else None


def _sym_u8(self, name):
    a = sym_addr(name)
    return self.mem.r8(a) if a is not None else None


Harness.sym_u16 = _sym_u16
Harness.sym_u8 = _sym_u8


def u16(b, o):
    return (b[o] << 8) | b[o + 1]


def main() -> int:
    if not IMG.exists():
        raise SystemExit(f"no image at {IMG} - build it first")
    print("=== HaniCore Bosch ME7.1.1 - boot and protocol, in the simulator ===")
    h = Harness(IMG, echo=True)
    print(f"entry taken from the image header: 0x{h.entry:06X}")
    print(f"one byte at {BAUD} baud = {h.byte_ticks} T7 ticks\n")

    # --- boot ------------------------------------------------------------
    # PI.BOOT_STEPS, not a literal. This was 1 200 000, chosen before V39's
    # append-only calibration store made hc_nvm_boot() cost 1 187 437
    # instructions before the supervision link comes up. The run ended
    # inside that scan and eight checks reported a firmware that had never
    # reached its main loop - bootStage=0, tick=0, loops=0 - which is a
    # true statement about a question asked too early.
    err = h.run(PI.BOOT_STEPS)
    banner = bytes(h.txb)
    check("boot completes without a trap", err is None, err or "no trap")
    check("reset-to-idle K-line is silent", banner == b"",
          f"{len(banner)} unsolicited byte(s)")
    # INVERTED in V17. "HCL T=" (alive_line()) used to be asserted PRESENT;
    # it is now asserted ABSENT, permanently. alive_line() was ~127 ms of
    # pure blocking K-line transmission, called from the same main loop as
    # hc_asic_start_service() - the runtime ASIC exchange's own state
    # machine - and its first call landed at ~T=107-128 ms on every boot,
    # which is where the S5500 reset HaniCore regardless of UMKOM answer
    # content (docs/ARCHITECTURE.md/§5h). The function is
    # deleted, not merely uncalled, so this checks the fix stays in place
    # rather than being silently re-added.
    check("the liveness line stays REMOVED (V17 fix)", b"HCL T=" not in banner,
          "alive_line() must not reappear - see §5h before restoring it")

    # --- the live block ---------------------------------------------------
    blk = h.och(0, OCH_SIZE)
    status, stage = u16(blk, 0), u16(blk, 2)
    tick, loops = u16(blk, 4), u16(blk, 6)
    cal = u16(blk, 10)
    want = int(10 * (TICKS_PER_MS_X10 / 10.0) * 1000 / BAUD)
    check("CAL matches the derived timer rate",
          abs(cal - want) <= max(4, want // 20),
          f"CAL={cal} ticks, expected about {want}")
    check("boot reached the main loop", stage == define("BOOT_LOOP"),
          f"bootStage={stage}")
    check("the 1 ms tick is running", tick > 0, f"tick={tick} ms")
    check("the main loop is turning", loops > 0, f"loops={loops}")

    rst = bytes(h.mem.r8(EXTRAM + RAM_RSTLOG + i) for i in range(64))
    check("persistent fine marker reached the main loop",
          u16(rst, 48) == 0x0B01, f"marker=0x{u16(rst, 48):04X}")
    check("watchdog services are counted persistently",
          u16(rst, 46) > 0, f"wdtCount={u16(rst, 46)}")

    badvec, firstvec = u16(blk, 40), u16(blk, 42)
    check("no interrupt landed on a catch-all", badvec == 0,
          f"badvec={badvec}" + (f" first trap 0x{firstvec:02X}" if badvec else ""))

    HC_ST_BENCHSAFE = 0x0002
    HC_ST_ARMED = 0x0001
    check("a normal build does not report BENCH_SAFE",
          not (status & HC_ST_BENCHSAFE), f"status=0x{status:04X}")
    check("outputs are NOT armed", not (status & HC_ST_ARMED),
          f"status=0x{status:04X}")

    # --- the receive path -------------------------------------------------
    rx_irq_ok, rx_tick_ok = u16(blk, 32), u16(blk, 34)
    # 2026-10-06: the ME7.1.1 receives by PEC channel 6 (S0RIC = IE|15|2,
    # hcserial711.h) - read from the CPU, not from a published flag, and
    # proven to carry traffic by every TunerStudio check below.
    rx_pec6 = (h.mem.sfr.get(S0RIC, 0) & 0x7F) == 0x7E
    check("a receive path came up",
          rx_irq_ok or rx_tick_ok or rx_pec6,
          "ASC0 interrupt" if rx_irq_ok else
          ("CAPCOM drain tick" if rx_tick_ok else
           ("PEC6 into the IRAM ring" if rx_pec6 else "NEITHER - polled only")))

    # --- TunerStudio ------------------------------------------------------
    #
    # Quiet the ECU first, exactly as TunerStudio does. While nobody has talked
    # to it, this build transmits a liveness line every 100 ms - and on a
    # K-line every transmitted byte echoes back into our own receiver, so
    # tx() drops one received byte per byte sent. A request that arrives in the
    # middle of a line therefore has its first bytes eaten as if they were
    # echoes, and is lost.
    #
    # That is not a defect to fix in the firmware: it is what a shared
    # single-wire bus does, and it is why hc_trace_on stops the text on the
    # FIRST byte received. TunerStudio's detection phase repeats 'Q' until it
    # gets an answer, which is precisely this. So the test does the same rather
    # than pretending one perfectly-timed request should always land.
    print()
    for _ in range(4):
        out, err = h.send_raw(b"Q", steps=400000)
        if SIGNATURE.encode() in out:
            break
    check("the ECU goes quiet once something talks to it",
          not hcts_trace_on(h), "hc_trace_on cleared")

    out, err = h.send(b"S")
    r, _ = parse(out)
    check("signature over the CRC envelope",
          r is not None and r[2] and r[1] == SIGNATURE.encode(),
          repr(r[1]) if r else f"nothing ({err})")

    out, err = h.send(b"F")
    r, _ = parse(out)
    check("protocol reply", r is not None and r[2] and r[1] == b"001",
          repr(r[1]) if r else "nothing")

    # A complete 680-byte response needs more simulator instructions than the
    # historical 1.5M default (which was sized for the old, smaller OCH).  This
    # is a liveness allowance, not a changed wire-timing claim.
    out, err = h.send(b"O" + (0).to_bytes(2, "big")
                      + OCH_SIZE.to_bytes(2, "big"), steps=3_000_000)
    r, _ = parse(out)
    check("the whole output-channel block in ONE request",
          r is not None and r[2] and len(r[1]) == OCH_SIZE,
          f"{len(r[1]) if r else 0} of {OCH_SIZE} bytes")

    out, err = h.send(b"R" + (0).to_bytes(2, "big") + (16).to_bytes(2, "big"))
    r, _ = parse(out)
    check("the calibration page reads", r is not None and r[2] and len(r[1]) == 16,
          r[1].hex(" ") if r else "nothing")

    out, err = h.send_raw(b"Q")
    check("the plain legacy probe answers",
          SIGNATURE.encode() in out, repr(out[:40]))

    bad = b"\x00\x01Z\x00\x00\x00\x00"
    out, err = h.send_raw(bad)
    r, _ = parse(out)
    check("a bad CRC is rejected, not obeyed",
          r is not None and r[0] == 0x82, f"code=0x{r[0]:02X}" if r else "nothing")

    # Transport abuse representative of USB serial buffering. These use the
    # linked firmware parser, not a host-side protocol reimplementation.
    slow = frame(b"V")
    h.txb.clear()
    for byte in slow:
        h.rxq.append(byte)
        h.run(10000)                 # split/slow, but well below 20 ms timeout
    err = h.run(800000)
    r, _ = parse(bytes(h.txb))
    check("split/slow serial reads complete one request",
          err is None and r is not None
          and r[1] == _meta["version_text"].encode(),
          repr(r[1]) if r else "nothing (err %s, tx %r)"
          % (err, bytes(h.txb[:40])))

    # Back-to-back on a half-duplex K-line means request/reply followed
    # immediately by the next request. Injecting request 2 before reply 1 has
    # left the one wire is a collision, not TunerStudio behaviour.
    out1, err1 = h.send(b"F", steps=150000)
    out2, err2 = h.send(b"Q", steps=800000)
    r1, _ = parse(out1)
    r2, _ = parse(out2)
    check("back-to-back TunerStudio requests stay framed",
          err1 is None and err2 is None
          and r1 is not None and r1[1] == b"001"
          and r2 is not None and r2[1] == SIGNATURE.encode(),
          "%r then %r" % (r1[1] if r1 else None, r2[1] if r2 else None))

    resync_before = h.sym_u16("rx_resync")
    h.txb.clear()
    h.rxq.extend(frame(b"F")[:3])   # length + payload, CRC never arrives
    h.run(300000)                    # >20 ms: parser must abandon it
    out, err = h.send(b"F", steps=900000)
    r, _ = parse(out)
    check("partial-frame timeout resynchronises the next request",
          err is None and h.sym_u16("rx_resync") > resync_before
          and r is not None and r[1] == b"001",
          "rxResync %d->%d, reply %r" %
          (resync_before, h.sym_u16("rx_resync"), r[1] if r else None))

    # ================================================== the ASIC, modelled ==
    #
    # The simulator has no PEC and no second processor, so a live handshake
    # would otherwise just time out forever. This models the ASIC well enough
    # to exercise every branch the firmware has: a completed exchange, a reply
    # that passes MAIN's checksum test, a reply that fails it, and silence.
    #
    # The trigger is the same one the hardware uses - a write to SSCTIC with
    # the interrupt-request bit set is what kicks PEC0 into moving word 0.
    print()
    print("--- the ASIC handshake, against a modelled ASIC ---")

    SSCTIC = 0x00FF72
    SSCRIC = 0x00FF74
    SSCEIC = 0x00FF76
    SSCCON_A = 0x00FFB2
    PECC0 = 0x00FEC0
    PECC4 = 0x00FEC8
    FRAMEA = define("TGT_ASIC_FRAME")

    # The ASIC handshake needs a whole number of 10 ms rasters AFTER boot, so
    # this budget is "boot + enough rasters", not an absolute. It is
    # overridable because when an image's boot cost changes, the useful
    # question is "does the handshake still work given time" and not "does it
    # fit in a constant somebody picked in 2026".
    # me711_boot_cost_proof.py is what guards the boot cost itself.
    _ASIC_STEPS = int(os.environ.get("HANICORE_ASIC_STEPS", "1500000"))

    def run_asic(mode, steps=_ASIC_STEPS, seed=None):
        """Model the ASIC and the SSC block transfer.

        mode: 'good' | 'badsum' | 'silent' | 'ssc_error' | 'stuck_busy'

        This models what V4's hardware run proved matters: a PEC block ends by
        raising the node as an ORDINARY interrupt, so the firmware's real
        SSC ISRs must run. The model therefore decrements the PEC counts to
        zero and raises SSCTIC/SSCRIC, rather than quietly faking completion.
        """
        h2 = Harness(IMG, echo=True)
        if seed:
            for a_, v_ in seed.items():
                h2.mem.w8(a_, v_)
        st = {"xfers": 0}
        o16 = S.Mem.w16

        def w16(self_, a, v, _o=o16):
            r = _o(self_, a, v)
            aa = a & 0xFFFFFF
            if aa == SSCCON_A and mode == "stuck_busy":
                # A peripheral wedged busy: exactly the state V4 could never
                # recover from, because it rewrote SSCCON with SSCEN already
                # set and the control bits silently ignored the write.
                #
                # SSCBSY IS STICKY ACROSS EVERY WRITE. It used to be re-asserted
                # only when a write SET SSCEN, which meant
                # asic_abort_transfer()'s `SSCCON = 0x461F` - no SSCBSY bit -
                # silently un-wedged the modelled peripheral on every transfer
                # timeout. The firmware then never saw three consecutive busy
                # refusals and the escalation path was never exercised:
                # refusals=0, tx=7, timeouts=7.
                #
                # V10 passed this check by accident. A second state machine,
                # asic_service(), was still being called from the main loop and
                # kept setting SSCEN independently, re-wedging the model between
                # hcasicstart's attempts. Standing that machine down for V11
                # removed the accident and exposed the model.
                #
                # A genuinely wedged peripheral stays busy whatever the firmware
                # writes. That is what this now models, and it is a STRICTER
                # test than any version before V11 ran.
                self_.sfr[SSCCON_A] = v | 0x1000        # SSCBSY stuck
            if aa == SSCTIC and (v & 0x0080) and mode not in ("silent",
                                                              "stuck_busy"):
                n = 0x60
                if mode == "ssc_error":
                    # An SSC error: flags set, error node raised, no data.
                    self_.w16(SSCCON_A, (self_.r16(SSCCON_A) | 0x0800))
                    self_.sfr[SSCEIC] = 0x00D5      # IE+IR, ILVL 5
                    h2.cpu.irq_pending.add(SSCEIC)
                    st["xfers"] += 1
                    return r
                sum_ = 0
                for i in range(n - 1):
                    w = (0x1E00 + i) & 0xFFFF if i else 0x001E
                    self_.w16(FRAMEA + 2 * i, w)
                    sum_ = (sum_ + w) & 0xFFFF
                if mode == "badsum":
                    sum_ ^= 0x0001
                self_.w16(FRAMEA + 2 * (n - 1), sum_)
                # The PEC blocks drain: both counts reach zero ...
                self_.w16(PECC0, self_.r16(PECC0) & 0xFF00)
                self_.w16(PECC4, self_.r16(PECC4) & 0xFF00)
                self_.sfr[SSCCON_A] = self_.r16(SSCCON_A) & ~0x1000  # not busy
                # ... and the nodes then fire as ORDINARY interrupts. The
                # HARDWARE sets the request bit; queueing the node without it
                # is not the same thing, and the RX ISR never ran until this
                # model wrote IR the way the peripheral would.
                self_.sfr[SSCTIC] = self_.r16(SSCTIC) | 0x0080
                self_.sfr[SSCRIC] = self_.r16(SSCRIC) | 0x0080
                h2.cpu.irq_pending.add(SSCTIC)
                h2.cpu.irq_pending.add(SSCRIC)
                st["xfers"] += 1
            return r

        S.Mem.w16 = w16
        h2.run(steps)
        S.Mem.w16 = o16
        return h2, bytes(h2.txb), st

    hG, txG, stG = run_asic("good")
    a_state = hG.sym_u8("hc_asic_state")
    check("the handshake starts transfers",
          hG.sym_u16("hc_asic_start_tx") > 0,
          f"start_tx={hG.sym_u16('hc_asic_start_tx')}")
    check("the modelled ASIC saw them", stG["xfers"] > 0,
          f"{stG['xfers']} exchange(s)")
    check("the SSC RX node fires as a real interrupt at block end",
          hG.sym_u16("hc_ssc_rx_vec") > 0,
          f"rx_vec={hG.sym_u16('hc_ssc_rx_vec')}")
    check("the SSC TX node fires too", hG.sym_u16("hc_ssc_tx_vec") > 0,
          f"tx_vec={hG.sym_u16('hc_ssc_tx_vec')}")
    check("NEITHER lands on the catch-all any more",
          hG.sym_u16("hc_badvec") == 0,
          f"badvec={hG.sym_u16('hc_badvec')}  (V4 hardware: 0x1B..0x2D)")
    check("completed transfers are detected",
          hG.sym_u16("hc_asic_start_rx") > 0,
          f"start_rx={hG.sym_u16('hc_asic_start_rx')}")
    check("a good reply is ACCEPTED", hG.sym_u16("hc_asic_start_ok") >= 2,
          f"start_ok={hG.sym_u16('hc_asic_start_ok')}")
    check("and it reaches the 118-word runtime state", a_state in (6, 7),
          f"state={a_state}")
    check("both PEC blocks drained to zero",
          hG.sym_u16("hc_asic_pec_tx_end") == 0
          and hG.sym_u16("hc_asic_pec_rx_end") == 0,
          f"tx_left={hG.sym_u16('hc_asic_pec_tx_end')}, "
          f"rx_left={hG.sym_u16('hc_asic_pec_rx_end')}")
    check("the K-line stays idle-silent with the ASIC running",
          txG == b"", f"{len(txG)} unsolicited byte(s)")

    hB, txB, _ = run_asic("badsum")
    check("a BAD checksum is rejected, not accepted",
          hB.sym_u16("hc_asic_start_csum_err") > 0
          and hB.sym_u16("hc_asic_start_ok") == 0,
          f"csum_err={hB.sym_u16('hc_asic_start_csum_err')}")
    check("a bad checksum still produces no stray vectors",
          hB.sym_u16("hc_badvec") == 0, "badvec=0")

    hS, txS, _ = run_asic("silent")
    check("a SILENT ASIC times out instead of blocking",
          hS.sym_u16("hc_asic_start_timeout") > 0,
          f"timeouts={hS.sym_u16('hc_asic_start_timeout')}")
    check("the K-line stays idle-silent with a silent ASIC", txS == b"",
          f"{len(txS)} unsolicited byte(s)")

    hE, txE, _ = run_asic("ssc_error")
    check("an SSC ERROR is caught by its own handler",
          hE.sym_u16("hc_ssc_err_vec") > 0,
          f"err_vec={hE.sym_u16('hc_ssc_err_vec')}")
    check("and it is counted as an SSC error, not a checksum failure",
          hE.sym_u16("hc_asic_ssc_errors") > 0,
          f"ssc_errors={hE.sym_u16('hc_asic_ssc_errors')}")
    check("the error does not become a vector storm",
          hE.sym_u16("hc_badvec") == 0, "badvec=0")
    check("the K-line stays idle-silent after an SSC error", txE == b"",
          f"{len(txE)} unsolicited byte(s)")

    # THE WARM-RESET CASE. V4's hardware signature: the first cold boot
    # transmitted twice and every warm boot afterwards reported TX=0000/0000
    # forever, because a wedged SSC was never re-initialised.
    # 3M steps, not the default 1.5M. Recovery from a wedge is bounded in
    # TIME - an 8 ms transfer timeout, then THREE busy refusals one
    # TGT_ASIC_START_PERIOD_MS apart - so the scenario has to be given at
    # least ~70 ms of simulated time to reach it. V10 happened to get there
    # inside the default budget only because a second, now-retired state
    # machine was also cycling the transport and clearing in_flight sooner.
    hW, txW, _ = run_asic("stuck_busy", steps=3_000_000)
    check("a wedged SSC is RE-INITIALISED rather than waited on",
          hW.sym_u16("hc_asic_reinits") > 0,
          f"reinits={hW.sym_u16('hc_asic_reinits')} "
          f"refusals={hW.sym_u16('hc_asic_busy_refusals')} "
          f"tx={hW.sym_u16('hc_asic_start_tx')} "
          f"timeouts={hW.sym_u16('hc_asic_start_timeout')} "
          f"sscerr={hW.sym_u16('hc_asic_ssc_errors')} "
          f"state={hW.sym_u16('hc_asic_state')}  "
          f"(V4 would sit here forever)")
    check("the firmware keeps trying after a wedge",
          hW.sym_u16("hc_asic_busy_refusals") < 3,
          "refusal counter is bounded and resets")
    check("the K-line stays idle-silent with a wedged SSC", txW == b"",
          f"{len(txW)} unsolicited byte(s)")

    # ---- the one-flash frame extractor ------------------------------------
    #
    # V5 could only report the FIRST reply word. This freezes a whole reply in
    # battery SRAM and prints one chunk per boot, so the ECU's own reset loop
    # walks the frame out. The property that matters is COHERENCE: every chunk
    # must come from the same frozen frame, not from whichever transfer
    # happened last.
    print()
    print("--- the frozen-frame extractor ---")
    ASICLOG = EXTRAM + define("TGT_RAM_ASICDUMP")

    def boot_chain(n, mode="good"):
        boot_id = 0
        """Run n consecutive boots against a persistent SRAM image, the way
        the real ECU's reset loop does."""
        keep = {}
        texts = []
        for boot_no in range(n):
            boot_id = boot_no
            h3 = Harness(IMG, echo=True)
            for a_, v_ in keep.items():
                h3.mem.w8(a_, v_)
            st = {"x": 0}
            o16 = S.Mem.w16

            def w16(self_, a2, v2, _o=o16):
                r = _o(self_, a2, v2)
                if (a2 & 0xFFFFFF) == SSCTIC and (v2 & 0x0080):
                    nn = 0x60
                    sm = 0
                    for i in range(nn - 1):
                        w = ((0x10 + boot_id) << 8) | ((i * 7) & 0xFF)
                        self_.w16(FRAMEA + 2 * i, w)
                        sm = (sm + w) & 0xFFFF
                    self_.w16(FRAMEA + 2 * (nn - 1), sm ^ 0x0001)  # bad on purpose
                    self_.w16(PECC0, self_.r16(PECC0) & 0xFF00)
                    self_.w16(PECC4, self_.r16(PECC4) & 0xFF00)
                    self_.sfr[SSCCON_A] = self_.r16(SSCCON_A) & ~0x1000
                    self_.sfr[SSCTIC] = self_.r16(SSCTIC) | 0x0080
                    self_.sfr[SSCRIC] = self_.r16(SSCRIC) | 0x0080
                    h3.cpu.irq_pending.add(SSCTIC)
                    h3.cpu.irq_pending.add(SSCRIC)
                    st["x"] += 1
                return r

            S.Mem.w16 = w16
            h3.run(1400000)
            S.Mem.w16 = o16
            texts.append(bytes(h3.txb))
            for off in range(0, 0x600, 1):
                keep[ASICLOG + off] = h3.mem.r8(ASICLOG + off)
        return texts

    # V23 deliberately removed hc_asicdump_print(); the battery-backed capture
    # remains, but it must never be pushed onto K-line at boot. The dedicated
    # me711_asicdump_salvage_proof.py owns the multi-boot content/coherence test.
    # Keep two persistent-SRAM boots here only to enforce the silence contract.
    ts = boot_chain(2)
    check("the persistent extractor remains silent across warm boots",
          all(t == b"" for t in ts),
          f"unsolicited bytes per boot: {[len(t) for t in ts]}")

    print()
    bad_n = sum(1 for _, ok, _ in results if not ok)
    print(f"{len(results) - bad_n}/{len(results)} checks pass")
    if bad_n:
        print("SOMETHING FAILED")
        return 1
    print("ALL CHECKS PASS (in simulation - the bench is still the bench)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
