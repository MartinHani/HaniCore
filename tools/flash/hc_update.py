#!/usr/bin/env python3
r"""
hc_update.py - update a HaniCore ECU's firmware over the normal K-line, no
bootmode programmer, and keep the tune.

    py tools/flash/hc_update.py --self-test               # offline, no ECU
    py tools/flash/hc_update.py --image <_updater.bin> --port COMx
        [--baud 57600] [--out <dir>] [--old-ini <ini>] [--new-ini <ini>]
        [--no-restore] [--dry-run]

WHAT IT DOES (.scratch/firmware-update/spec.md)
-----------------------------------------------
The HOST (P4) side of the OBD updater. It parses a `--updater` image and checks
the app region against the 32-byte header the loader reads, then, over the
TS-framed protocol:

  1. identity: the ECU's signature ("HaniCore <board> <layout>"; images
     before 2026-10-31 add a "rusEFI " prefix, still accepted) and
     version text, and the image's own signature and version text, read out
     of the image. A wrong board is refused; so is an ECU whose firmware does
     not publish the updater status channel (flash an --updater image once by
     bootmode first).
  2. SAVES THE TUNE, always, before anything moves: the 4096-byte page ->
     <out>/page_before.bin, plus identity.json naming its layout and .ini.
  3. STAGE_BEGIN, the app in 64-byte WRITEs, SEAL (CRC-32), COMMIT - each
     step stop-and-wait on the updater status channel (OCH 478..491,
     hcupd711.h HC_UPD_OCH_*), because every '!' command answers TS_OK
     whatever it did. A WRITE is idempotent: the ECU's received-count says
     whether a chunk whose reply was lost has landed, so nothing is ever
     programmed (or folded into the CRC) twice.
  4. waits for the reboot (the resident loader copies STAGING over the APP)
     and checks that the ECU now reports the image's build id and signature.
  5. KEEPS THE TUNE (the rusEFI / TunerStudio model: by field identity):
       same layout id  -> the update never touched the store, so the tune is
                          still in the ECU; the page is read back and compared
                          with the saved one (and rewritten + Burned only if
                          it differs);
       layout changed  -> the new firmware refuses the old records and runs
                          its board default; the saved page is MIGRATED by
                          field name (me711_migrate_calibration.migrate():
                          old .ini -> new .ini, scale changes re-encoded, new
                          fields keep the NEW firmware's defaults - a new
                          knob comes up as the firmware ships it), written
                          with 'W', read back, validated by the firmware
                          (cfgValidation 0), then Burned.
     If any of that fails, page_before.bin and page_restored.bin stay in
     <out> for a manual restore - the tune never lives only in the ECU.

This tool speaks the ECU's tuning protocol over whatever serial port is given
and never switches power. The ECU must be powered with the engine stopped.
"""
from __future__ import annotations

import argparse
import binascii
import json
import re
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_migrate_calibration as MIG  # noqa: E402  (pure: parse_ini, migrate)

# ---- the app image header (hcloader.a66 HDR; build_hanicore_me711.py 8b) ----
# 32 bytes at file 0x030200 (CPU 0x830200), little-endian.
APP_BASE = 0x030000          # SA6: the app's vector table, header and code
HDR_OFF = 0x030200
HDR_MAGIC0 = 0x4348          # 'HC'
HDR_MAGIC1 = 0x5041          # 'AP'
HDR_SEAL = 0x5AA5
BOARD_CODE = {1: "porsche_me711", 2: "vag_me71_c4",
              3: "audi_4f_v8", 4: "vag_me75_dc", 5: "vag_me75_bfb"}
BOARD_NAME = {v: k for k, v in BOARD_CODE.items()}

# ---- the wire protocol (TS-framed; hcdiag711.c hc_target_cmd_cold) ----------
# The ECU reaches board commands through hcts.c's '!' frame: byte 0 '!', byte 1
# the command letter, the rest the payload. The updater letters are lowercase
# (the uppercase ones are taken):
#   '!u'                         STAGE_BEGIN  - erase STAGING (SA15..SA18)
#   '!w' + off(u32, big-endian)  STAGE_WRITE  - program <=64 bytes into STAGING
#                 + bytes            (length is implicit: frame length - 6)
#   '!x' + crc(u32, big-endian)  STAGE_SEAL   - CRC must match, then seal last
#   '!y'                         COMMIT       - request 'UP'/'DT', read back, SRST
# There is NO deferred reply: each command returns TS_OK at once and the host
# POLLS the updater status channel until the ECU is READY again before the
# next chunk. That matches every other hcts command ("the request is recorded;
# the verdict is published"). COMMIT does not answer at all: it resets.
CMD_STAGE_BEGIN = ord("u")
CMD_STAGE_WRITE = ord("w")
CMD_STAGE_SEAL = ord("x")
CMD_COMMIT = ord("y")
CMD_IDENTITY = ord("V")      # existing: version text (hcts.c)
# hcts.c RXMAX is 72 and the frame length is ONE byte, so a '!w' frame holds at
# most 72 - ('!' + 'w' + 4 offset bytes) = 66 data bytes. 64 (a round, word-
# aligned number) is the chunk. 256 was wrong: the firmware could never receive
# it. ~195 KiB / 64 B ~ 3150 chunks.
STAGE_CHUNK = 64             # bytes per WRITE (bounded by hcts.c RXMAX = 72)

# ---- the updater status channel (hcupd711.h HC_UPD_OCH_*), big-endian U16s --
UPD_OCH = 478
UPD_OCH_LEN = 18
UPD_MARKER = 0x5550          # 'UP' at 490: this image publishes the channel
ST_IDLE, ST_ERASING, ST_READY, ST_WRITING, ST_SEALED, ST_COMMIT, ST_FAILED = range(7)
ST_NAME = ("IDLE", "ERASING", "READY", "WRITING", "SEALED", "COMMIT", "FAILED")
ERR_NAME = ("NONE", "RAM", "VALIDATE (engine not stopped)", "STAGE", "ERASE",
            "PROGRAM", "VERIFY", "RETRIES", "LAYOUT", "FULL", "DEADLINE")
PAGE = 4096
SIG_RE = re.compile(rb"(?:rusEFI )?HaniCore (\w+) ([0-9A-F]{8})")
VER_RE = re.compile(rb"HaniCore V[^\0]*? build ([0-9A-F]{8})")


class ImageError(Exception):
    pass


def u16(b, o):
    return b[o] | (b[o + 1] << 8)


def u32(b, o):
    return b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)


def parse_app(image: bytes) -> dict:
    """Read and VALIDATE the app region of a 1 MiB --updater image: the header
    the loader reads, and the app bytes STAGING will receive. Raises
    ImageError with the reason if anything the loader/verifier checks is wrong,
    so a bad image is refused by the HOST before a byte reaches the ECU."""
    if len(image) != 0x100000:
        raise ImageError(f"image is {len(image)} bytes, not a 1 MiB ECU image")
    h = HDR_OFF
    if u16(image, h) != HDR_MAGIC0 or u16(image, h + 2) != HDR_MAGIC1:
        raise ImageError("no 'HCAP' app header at 0x030200 - not an --updater "
                         "image (build with --updater)")
    if u16(image, h + 30) != HDR_SEAL:
        raise ImageError("app header is not sealed (0x5AA5 missing)")
    board = u16(image, h + 4)
    if board not in BOARD_CODE:
        raise ImageError(f"app header board code {board} is not 1..4")
    entry = (u16(image, h + 8) << 16) | u16(image, h + 6)
    length = u32(image, h + 10)
    hdr_crc = u32(image, h + 14)
    build_id = u32(image, h + 18)
    if not (HDR_OFF - APP_BASE + 32 <= length <= 0x40000):
        raise ImageError(f"app length 0x{length:X} is not within (header, 4 sectors]")
    body = image[APP_BASE:APP_BASE + length]       # the bytes STAGING receives
    # CRC-32 over the app region EXCLUDING its own 32-byte header (the crc/seal/
    # build-id fields are written after the CRC, so they cannot be inside it).
    # Must match build_hanicore_me711.py section 8b and hcdiag711.c hc_upd_write.
    crc_body = image[APP_BASE:HDR_OFF] + image[HDR_OFF + 32:APP_BASE + length]
    crc = binascii.crc32(crc_body) & 0xFFFFFFFF
    if crc != hdr_crc:
        raise ImageError(f"app CRC-32 0x{crc:08X} != header 0x{hdr_crc:08X} "
                         "- the image is inconsistent with its own header")
    # The identity the ECU will report once it runs this app - read out of the
    # app region itself, so it cannot disagree with what is flashed.
    sig = SIG_RE.search(body)
    ver = VER_RE.search(body)
    if sig is None or ver is None:
        raise ImageError("no TunerStudio signature / version text in the app")
    if ver.group(1).decode() != "%08X" % build_id:
        raise ImageError("version text build %s != header build id %08X"
                         % (ver.group(1).decode(), build_id))
    return {"board": board, "board_name": BOARD_CODE[board], "entry": entry,
            "length": length, "crc": crc, "build_id": "%08X" % build_id,
            "body": body, "signature": sig.group(0).decode(),
            "sig_board": sig.group(1).decode(), "layout": sig.group(2).decode(),
            "version": ver.group(0).decode("latin1"),
            "board_text": board_text(ver.group(0).decode("latin1"))}


def board_text(version: str) -> str:
    """The board name in the version text ("... / Bosch ME7.1.1 4F build X").
    The signature's board token is shared by boards with one page layout (the
    Porsche and the 4F are both ME711), so this is what tells them apart."""
    m = re.search(r" / (.*?) build [0-9A-F]{8}", version)
    return m.group(1) if m else ""


def plan_chunks(length: int, chunk: int = STAGE_CHUNK):
    """The WRITE offsets/sizes that cover the whole app, word-aligned (the
    device programs words), never straddling a 64 KiB segment. The seal word
    is programmed by SEAL, not here."""
    off = 0
    out = []
    while off < length:
        n = min(chunk, length - off, 0x10000 - (off & 0xFFFF))
        if n & 1:
            n += 1                      # round up to a word; the tail is 0xFF
        out.append((off, n))
        off += n
    return out


# ================================ the ECU session ============================

class LinkError(Exception):
    pass


def envelope(payload: bytes) -> bytes:
    crc = binascii.crc32(payload) & 0xFFFFFFFF
    return bytes([0x00, len(payload)]) + payload + crc.to_bytes(4, "big")


class Link:
    """The TunerStudio CRC envelope over a K-line adapter. The adapter echoes
    what is sent (half duplex); the echo is stripped when it is there."""

    def __init__(self, port: str, baud: int, trace: Path | None = None):
        import serial  # pyserial
        self.ser = serial.Serial(port, baud, timeout=0.005, write_timeout=2.0)
        self.last_rx = 0.0
        self.base_baud = baud
        self.gap_s = 0.001
        self.trace = trace.open("a", encoding="ascii") if trace else None

    def kwp_enter(self, rate: int, say=print, tries: int = 3) -> int:
        """The vehicle path (OBD port, shared K-line): 5-baud 0x01, the ISO
        14230 handshake, HaniCore IDENTIFY and GOFAST to `rate` (the 2.7T
        refuses 115200 and gets 57600/124800) - tools/vehicle/
        me711_kwp_connect.py, the same entry the TunerStudio plugin makes.
        The ECU then runs a private TunerStudio session at that rate."""
        import me711_kwp_connect as K
        wire = K.Wire(self.ser)
        for n in range(tries):
            r = K.attempt(wire, rate, lambda m: say("  kwp:" + m))
            if r.get("ok"):
                self.base_baud = r["rate"]
                self.last_rx = time.monotonic()
                self.ser.reset_input_buffer()
                return r["rate"]
            time.sleep(2.5)         # the ECU drops back to KWP idle on silence
        raise LinkError("no KWP entry after %d tries" % tries)

    def set_baud(self, baud: int):
        self.ser.baudrate = baud
        self.ser.reset_input_buffer()
        self._t("BAUD", str(baud).encode())

    def close(self):
        self.ser.close()
        if self.trace:
            self.trace.close()

    def _t(self, tag, b):
        if self.trace:
            self.trace.write("%.4f %s %s\n" % (time.monotonic(), tag, b.hex()))

    def request(self, payload: bytes, data_len: int | None, timeout_s=2.0,
                idle_s=0.25) -> bytes:
        """Send one frame; return the response data (code stripped) or raise.
        data_len None = do not wait for a reply (COMMIT resets)."""
        # A short quiet gap after the last reply: the ECU drops one received
        # byte per byte it transmitted as its own echo, and the 1 ms tick must
        # have eaten the last of them before our first byte lands (hcserial711.c
        # hc_pecrx_tick). 20 ms (V97, before the PEC receive path) was 2/3 of
        # every chunk's time. 1 ms lost every other frame at 250 kbaud (bench
        # 2026-10-30, obd_update_16); 3 ms (--gap-ms) is the default.
        gap = self.gap_s - (time.monotonic() - self.last_rx)
        if gap > 0:
            time.sleep(gap)
        req = envelope(payload)
        self.ser.reset_input_buffer()
        self.ser.write(req)
        self.ser.flush()
        self._t("TX", req)
        if data_len is None:
            return b""
        want = len(req) + data_len + 7
        got = bytearray()
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline and len(got) < want:
            # ask for exactly what is still owed: read(512) waited out the
            # whole port timeout on every short reply (~75 ms a request). The
            # port timeout is a fixed 5 ms (set once - on Windows every
            # assignment reconfigures the port, ~8 ms), so a lost reply costs
            # about the caller's deadline, not more.
            part = self.ser.read(want - len(got))
            if part:
                got.extend(part)
                deadline = min(deadline, time.monotonic() + idle_s)
        self.last_rx = time.monotonic()
        raw = bytes(got)
        self._t("RX", raw)
        if raw.startswith(req) or len(raw) >= len(req) + 7:
            # the echo is our own frame; at 250 kbaud the adapter sometimes
            # garbles it while the ECU's reply behind it is intact - the
            # reply's CRC below decides, not the echo
            raw = raw[len(req):]
        if len(raw) < 7:
            raise LinkError("no reply to %r (%d bytes)" % (payload[:2], len(raw)))
        n = (raw[0] << 8) | raw[1]
        blob = raw[2:2 + n]
        if len(blob) != n or int.from_bytes(raw[2 + n:6 + n], "big") \
                != (binascii.crc32(blob) & 0xFFFFFFFF):
            raise LinkError("bad reply frame to %r" % payload[:2])
        if blob[0] != 0:
            raise LinkError("response code 0x%02X to %r" % (blob[0], payload[:2]))
        return blob[1:]

    def retry(self, payload, data_len, tries=4, **kw) -> bytes:
        last = None
        for _ in range(tries):
            try:
                return self.request(payload, data_len, **kw)
            except LinkError as e:
                last = e
                time.sleep(0.1)
        raise LinkError(str(last))

    def text(self, cmd: bytes) -> str:
        blob = self.retry(cmd, 80, idle_s=0.15)
        return blob.split(b"\0")[0].decode("latin1", "replace").strip()

    def och(self, off: int, n: int, timeout_s: float = 0.1) -> bytes:
        # an OCH reply takes a few ms; a lost one should cost little
        blob = self.retry(b"O" + off.to_bytes(2, "big") + n.to_bytes(2, "big"), n,
                          timeout_s=timeout_s, idle_s=0.02)
        if len(blob) != n:
            raise LinkError("OCH @%d returned %d of %d bytes" % (off, len(blob), n))
        return blob

    def status(self) -> dict:
        return decode_status(self.och(UPD_OCH, UPD_OCH_LEN))

    def page_read(self) -> bytes:
        out = bytearray()
        for off in range(0, PAGE, 256):
            blob = self.retry(b"R" + off.to_bytes(2, "big") + (256).to_bytes(2, "big"),
                              256, timeout_s=3.0)
            if len(blob) != 256:
                raise LinkError("page read @%d short" % off)
            out += blob
        return bytes(out)

    def page_write(self, off: int, data: bytes):
        self.retry(b"W" + off.to_bytes(2, "big") + data, 0)

    def burn(self):
        # the reply is deferred until the record is programmed (~3 s)
        return self.request(b"B", 0, timeout_s=20.0, idle_s=8.0)


def decode_status(b: bytes) -> dict:
    w = [int.from_bytes(b[i:i + 2], "big") for i in range(0, UPD_OCH_LEN, 2)]
    return {"state": w[0], "error": w[1], "received": (w[2] << 16) | w[3],
            "seq": w[4] >> 8, "rc": w[4] & 0xFF, "sector": w[5] >> 8,
            "cmd": chr(w[5] & 0xFF) if w[5] & 0xFF else "", "marker": w[6],
            "pending": w[7] if len(w) > 7 else 0,
            "erased": w[8] if len(w) > 8 else 4}


def och_channels(ini_text: str) -> dict:
    """[OutputChannels] scalars -> {name: (offset, type)}."""
    out, on = {}, False
    for raw in ini_text.splitlines():
        line = MIG.strip_comment(raw).strip()
        if line.startswith("["):
            on = line == "[OutputChannels]"
            continue
        m = re.match(r"(\w+)\s*=\s*scalar\s*,\s*(\w+)\s*,\s*(\d+)", line) if on else None
        if m:
            out[m.group(1)] = (int(m.group(3)), m.group(2))
    return out


def find_ini(signature: str, given: str | None) -> Path | None:
    """The .ini whose signature is exactly this one. The signature carries the
    layout id, so it names the page layout. Newest file first."""
    if given:
        p = Path(given)
        if signature not in p.read_text(encoding="utf-8", errors="replace"):
            raise SystemExit("%s is not the .ini for %r" % (p, signature))
        return p
    pat = re.compile(r'^\s*signature\s*=\s*"%s"' % re.escape(signature), re.M)
    hits = []
    for p in list((ROOT / "tuning").glob("*.ini")) \
            + list((ROOT / "tuning" / "history").rglob("*.ini")):
        try:
            if pat.search(p.read_text(encoding="utf-8", errors="replace")):
                hits.append(p)
        except OSError:
            continue
    # the plain generated file before its forensic / fallback variants (same
    # page, same signature), then the newest
    hits.sort(key=lambda q: (("forensic" in q.name or "fallback" in q.name),
                             -q.stat().st_mtime))
    return hits[0] if hits else None


class Updater:
    """The stop-and-wait driver. `link` is a Link, or the self-test's FakeEcu."""

    def __init__(self, link, say=print, poll_s=0.005, chunk_timeout_s=2.0):
        self.k = link
        self.say = say
        self.poll_s = poll_s
        self.chunk_timeout_s = chunk_timeout_s
        self.last = None                    # the status that ended the last step

    fast = False                            # the link is at the bulk rate

    def status(self, budget_s: float = 30.0) -> dict:
        """The status, riding through a silent link. A lost status is
        harmless - nothing in the ECU moves without the next command. After
        0.4 s of silence at the bulk rate the ECU's link hunter has most
        likely left it (three bad requests move a locked link; 250 kbaud is
        not in its table, so it falls to 57600 / 124800): follow it down,
        then ask for the bulk rate again."""
        t_end = time.monotonic() + budget_s
        t0 = time.monotonic()
        pause = 0.02
        while True:
            try:
                st = self.k.status()
                if time.monotonic() - t0 > 1.0:
                    self.say("link back after %.1f s of silence" % (time.monotonic() - t0))
                return st
            except LinkError:
                if time.monotonic() > t_end:
                    raise
                if self.fast and time.monotonic() - t0 > 0.4:
                    self.recover_link()
                    continue
                time.sleep(pause)
                pause = min(pause * 2, 0.5)

    kwp = False                             # entered through the vehicle path

    def recover_link(self):
        """Find the ECU at the rates its hunter cycles through, then go back
        to the bulk rate. Each wrong-rate request is one piece of evidence that
        moves an unlocked ECU on, so a few requests per rate find it.

        On the vehicle path there is no hunt (the shared-bus rule holds the
        session's rate), so the session is re-entered instead: the ECU falls
        back to KWP idle on silence, and its update state is untouched. The
        bulk rate is not tried again there - one failure on a car's wiring is
        the answer."""
        self.fast = False
        if self.kwp:
            time.sleep(2.5)
            self.k.kwp_enter(self.k.base_baud, self.say)
            self.say("vehicle session re-entered at %d baud" % self.k.base_baud)
            self.want_fast = False
            return
        for _round in range(4):
            for baud in (self.k.base_baud, 57600):
                self.k.set_baud(baud)
                for _ in range(3):
                    try:
                        self.k.status()
                        self.say("link found again at %d baud" % baud)
                        if self.want_fast:
                            self.go_fast()
                        return
                    except LinkError:
                        pass
        raise LinkError("the ECU does not answer at %d or 57600" % self.k.base_baud)

    def _wait(self, cmd: str, seq0: int, until, timeout_s: float, what: str):
        """Poll until the ECU handled THIS command (seq moved, letter matches)
        and until(status) holds. A refusal or a FAILED state raises."""
        t_end = time.monotonic() + timeout_s
        st = None
        while time.monotonic() < t_end:
            try:
                st = self.k.status()
            except LinkError:
                time.sleep(0.05)
                continue
            if st["seq"] != seq0 and st["cmd"] == cmd:
                if st["rc"] != 0:
                    raise SystemExit("ECU REFUSED %s: %s (state %s)" % (
                        what, ERR_NAME[st["rc"]] if st["rc"] < len(ERR_NAME)
                        else st["rc"], ST_NAME[st["state"]]))
                if st["state"] == ST_FAILED:
                    raise SystemExit("ECU FAILED during %s: %s"
                                     % (what, ERR_NAME[st["error"]]))
                if until(st):
                    return st
            time.sleep(self.poll_s)
        raise TimeoutError("timeout waiting for %s (last status %r)" % (what, st))

    erase_seq = None
    want_fast = False

    def begin_erase(self, st: dict | None = None):
        """STAGE_BEGIN: erase STAGING (four sectors, sliced like a store
        reclaim). Started early so the tune is saved while it runs - the
        erase touches neither the store nor the page."""
        st = st or self.status()
        if st["marker"] != UPD_MARKER:
            raise SystemExit("the ECU publishes no updater status (OCH 490 = "
                             "0x%04X): it is not running an --updater image"
                             % st["marker"])
        if st["state"] in (ST_ERASING, ST_WRITING):
            raise SystemExit("an update is already in progress (%s)"
                             % ST_NAME[st["state"]])
        self.k.retry(b"!u", 0)
        self.erase_seq = st["seq"]
        self.erase_t0 = time.monotonic()

    def go_fast(self, baud: int = 250000) -> bool:
        """'!b': the ECU moves to 250 kbaud once the reply has left the wire
        (hcdiag711.c). Follow it, and prove it with a status read; if the line
        will not hold the rate, go back - the ECU's link hunter (it is
        UNLOCKED at the new rate) follows the host back down."""
        self.want_fast = True
        try:
            self.k.retry(b"!b", 0)
        except LinkError:
            return False
        time.sleep(0.03)
        self.k.set_baud(baud)
        t_end = time.monotonic() + 0.5
        while time.monotonic() < t_end:
            try:
                st = self.k.status()
                if st["cmd"] == "b" and st["rc"] == 0:
                    self.say("link at %d baud for the transfer" % baud)
                    self.fast = True
                    return True
            except LinkError:
                time.sleep(0.05)
        self.k.set_baud(self.k.base_baud)
        self.say("the line did not hold %d baud - staying at %d"
                 % (baud, self.k.base_baud))
        return False

    def stage(self, app: dict, progress=None):
        if self.erase_seq is None:          # not started early by the caller
            self.begin_erase()
        # wait for READY - judged by state, not by the last command letter
        # ('!b' may have followed the '!u')
        t_end = time.monotonic() + 120.0
        while True:
            st = self.status()
            if st["seq"] != self.erase_seq and st["state"] == ST_READY:
                break
            if st["state"] == ST_FAILED:
                raise SystemExit("ECU FAILED erasing STAGING: %s" % ERR_NAME[st["error"]])
            if st["seq"] != self.erase_seq and st["state"] == ST_IDLE:
                raise SystemExit("ECU REFUSED STAGE_BEGIN: %s" % ERR_NAME[st["rc"]])
            if time.monotonic() > t_end:
                raise SystemExit("timeout erasing STAGING (last status %r)" % st)
            time.sleep(0.02)
        self.last = st
        self.say("STAGING erased in %.1f s" % (time.monotonic() - self.erase_t0))
        body = app["body"]
        chunks = plan_chunks(app["length"])
        total = chunks[-1][0] + chunks[-1][1]
        t0 = time.monotonic()
        self.stream(body, chunks, progress)
        st = self._settle(total)
        self.say("STAGING written: %d bytes in %.1f s (%d resends)"
                 % (total, time.monotonic() - t0, self.resends))
        # SEAL: the ECU's running CRC must equal the image's
        self.k.retry(b"!x" + app["crc"].to_bytes(4, "big"), 0)
        self._wait("x", st["seq"], lambda s: s["state"] == ST_SEALED, 10.0, "SEAL")
        self.say("STAGING sealed: CRC-32 0x%08X matched on the ECU" % app["crc"])

    CHECK_EVERY = 32     # chunks between received-count checks (2 KiB)
    QUEUE_HIGH = 2048    # wait while the ECU holds more unprogrammed bytes

    def stream(self, body: bytes, chunks, progress=None):
        """Send the chunks back to back - one '!w' after another, no poll in
        between (the ECU queues a chunk that arrives while it still programs
        the last; hcdiag711.c hc_upd_write). The ECU accepts strictly in
        order, so every CHECK_EVERY chunks (and before each new 64 KiB
        segment, which it cannot append across) the host reads the received
        count and resends from there if anything was refused or lost. Nothing
        is ever programmed twice."""
        index = {off: i for i, (off, _n) in enumerate(chunks)}
        self.resends = 0
        i = 0
        since = 0
        shown = -1

        def drained_at() -> int:
            # one window = the ECU's job buffer (UPD_BUF_CAP): let it drain,
            # then return the chunk index the ECU wants next
            t_end = time.monotonic() + 5.0
            st = self.status()
            while st["state"] == ST_WRITING and time.monotonic() < t_end:
                st = self.status()
            if st["state"] == ST_FAILED:
                raise SystemExit("ECU FAILED while writing: %s" % ERR_NAME[st["error"]])
            if st["received"] == chunks[-1][0] + chunks[-1][1]:
                return len(chunks)
            if st["received"] not in index:
                raise SystemExit("ECU received %d bytes - not a chunk boundary"
                                 % st["received"])
            return index[st["received"]]

        def queued_at() -> int:
            t_end = time.monotonic() + 5.0
            st = self.status()
            while (st["state"] == ST_WRITING and st["pending"] > self.QUEUE_HIGH
                   and time.monotonic() < t_end):
                st = self.status()
            if st["state"] == ST_FAILED:
                raise SystemExit("ECU FAILED while writing: %s" % ERR_NAME[st["error"]])
            if st["received"] not in index:
                return drained_at()
            return index[st["received"]]

        while i < len(chunks):
            off, n = chunks[i]
            if since and off and (off & 0xFFFF) == 0:
                # a new 64 KiB segment cannot be appended to the old job
                since = 0
                j = drained_at()
                if j != i:
                    self.resends += i - j
                    i = j
                    continue
            if (off & 0xFFFF) == 0:
                # that STAGING sector may still be erasing in the background
                # (the ECU erases sectors 1..3 between chunks)
                t_end = time.monotonic() + 30.0
                st = self.status()
                while st["erased"] <= (off >> 16) and time.monotonic() < t_end:
                    if st["state"] == ST_FAILED:
                        raise SystemExit("ECU FAILED erasing STAGING: %s"
                                         % ERR_NAME[st["error"]])
                    time.sleep(0.01)
                    st = self.status()
            data = body[off:off + n]
            data = data + b"\xFF" * (n - len(data))
            lost = False
            try:
                # a reply takes ~8 ms (p90 8.5 at 250 kbaud): waiting longer
                # for one that is not coming cost more than the resend
                self.k.request(b"!w" + off.to_bytes(4, "big") + data, 0,
                               timeout_s=0.02, idle_s=0.01)
            except LinkError:
                lost = True                 # resync now, not at the window end:
                                            # every later chunk would be refused
            i += 1
            since += 1
            if lost or since >= self.CHECK_EVERY or i == len(chunks):
                # keep the ECU's queue (UPD_BUF_CAP 4 KiB) topped up instead of
                # draining it: wire and flash overlap. Resend from `received`
                # whenever it is not where this chunk ended.
                since = 0
                j = queued_at() if i < len(chunks) else drained_at()
                if j != i:
                    self.resends += i - j
                    i = j
            if progress and i != shown and (i % 512 == 0 or i == len(chunks)):
                shown = i
                progress(i, len(chunks), None)

    def _settle(self, end: int, timeout_s: float = 10.0) -> dict:
        """Wait until the ECU has programmed everything queued (READY) and has
        received exactly `end` bytes."""
        t_end = time.monotonic() + timeout_s
        while True:
            st = self.status()
            if st["state"] == ST_FAILED:
                raise SystemExit("ECU FAILED while writing: %s" % ERR_NAME[st["error"]])
            if st["state"] == ST_READY and st["received"] == end:
                return st
            if st["state"] == ST_READY and st["received"] != end:
                raise SystemExit("ECU is at byte %d, expected %d" % (st["received"], end))
            if time.monotonic() > t_end:
                raise SystemExit("ECU still %s at byte %d" % (ST_NAME[st["state"]],
                                                              st["received"]))
            time.sleep(self.poll_s)

    def commit(self):
        st = self.status()
        if st["state"] != ST_SEALED:
            raise SystemExit("not SEALED (%s) - refusing to commit"
                             % ST_NAME[st["state"]])
        self.k.request(b"!y", None)        # SRST: no reply


def wait_reboot(k: Link, build: str, auto_s=30.0, cycle_s=300.0, say=print,
                kwp: bool = False) -> str:
    """After COMMIT the ECU resets itself into the loader, which copies STAGING
    over the APP and starts it. If it is not back as the new build within
    auto_s, an ignition (key) cycle does the same: the commit request is in
    battery-backed SRAM and the loader acts on it at the next reset. Only a
    lost KL30 (battery off) drops the request - then the old build runs, the
    tune is untouched, and the update is simply run again."""
    if hasattr(k, "base_baud"):
        k.set_baud(k.base_baud)     # the reset boots the ECU at its default rate
    t_auto = time.monotonic() + auto_s
    t_end = t_auto + cycle_s
    asked = False
    last = ""
    time.sleep(1.0)
    while time.monotonic() < t_end:
        try:
            if kwp:
                # the reset ended the vehicle session: enter it again
                k.kwp_enter(k.base_baud, lambda m: None, tries=1)
            last = k.text(b"V")
            if "build " + build in last:
                return last
        except LinkError:
            pass
        if not asked and time.monotonic() > t_auto:
            say("the ECU is not back yet: switch the IGNITION OFF, wait 10 s, "
                "switch it ON (keep the battery connected)")
            asked = True
        time.sleep(0.5)
    raise SystemExit("the ECU did not come back as build %s (last %r). If it "
                     "reports the OLD build, the tune is untouched - run the "
                     "update again" % (build, last))


def diff_runs(have: bytes, want: bytes, limit: int = 16):
    diff = [i for i in range(PAGE) if have[i] != want[i]]
    runs, i = [], 0
    while i < len(diff):
        j = i
        while (j + 1 < len(diff) and diff[j + 1] == diff[j] + 1
               and diff[j + 1] - diff[i] < limit):
            j += 1
        runs.append((diff[i], diff[j] - diff[i] + 1))
        i = j + 1
    return diff, runs


def restore_page(k: Link, want: bytes, ini_text: str, say=print,
                 force_burn: bool = False) -> dict:
    """Write the bytes that differ, read back, require the firmware's own
    validation, Burn. Returns a result dict; raises on any refusal.

    force_burn: Burn even when nothing differs. After a LAYOUT change the
    page can come back intact from the battery-backed RAM while no flash
    record of the new layout exists yet (bench 2026-10-30: nvmSource 0x0101,
    generation 0) - a battery disconnect would then lose the tune."""
    have = k.page_read()
    diff, runs = diff_runs(have, want)
    res = {"bytes_differing": len(diff), "burned": False}
    if not diff and not force_burn:
        return res
    if diff:
        say("writing %d bytes in %d runs" % (len(diff), len(runs)))
        for off, n in runs:
            k.page_write(off, want[off:off + n])
        time.sleep(0.5)
    if k.page_read() != want:
        raise SystemExit("page read-back differs from the restored page - NOT burning")
    ch = och_channels(ini_text)
    val = int.from_bytes(k.och(ch["cfgValidation"][0], 2), "big")
    res["cfgValidation"] = val
    if val != 0:
        raise SystemExit("the firmware does not validate the restored page "
                         "(cfgValidation 0x%04X) - NOT burning" % val)
    k.burn()
    nvm = None
    for _ in range(60):
        nvm = int.from_bytes(k.och(ch["nvmState"][0], 2), "big")
        if nvm & 0xFF in (0, 5, 6):
            break
        time.sleep(0.5)
    res["nvmState"] = nvm
    if nvm is None or nvm & 0xFF not in (0, 5):
        raise SystemExit("Burn did not complete (nvmState 0x%04X)" % (nvm or 0))
    res["burned"] = True
    return res


def update_over_serial(args, app) -> int:
    try:
        import serial  # pyserial  # noqa: F401
    except ImportError:
        print("pyserial is not installed (py -m pip install pyserial)")
        return 2
    out = Path(args.out or ("hc_update_%s" % datetime.now(timezone.utc)
                            .strftime("%Y%m%d_%H%M%S")))
    out.mkdir(parents=True, exist_ok=True)
    logf = (out / "update.log").open("a", encoding="utf-8")

    def say(m):
        line = "%s  %s" % (datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3], m)
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    k = Link(args.port, args.baud, out / "kline_trace.txt" if args.trace else None)
    k.gap_s = args.gap_ms / 1000.0
    try:
        if args.kwp:
            say("entering through the vehicle (KWP) path...")
            say("vehicle session at %d baud" % k.kwp_enter(args.baud, say))
        try:
            sig = k.text(b"S")
        except LinkError:
            if args.baud == 57600:
                raise
            # the ECU follows the host's rate on evidence (hcts.c link hunter);
            # give it a few frames at this rate, then fall back to 57600
            sig = None
            for _ in range(6):
                try:
                    sig = k.text(b"S")
                    break
                except LinkError:
                    time.sleep(0.2)
            if sig is None:
                k.close()
                k = Link(args.port, 57600, out / "kline_trace.txt" if args.trace else None)
                sig = k.text(b"S")
                say("link at 57600 (no answer at %d)" % args.baud)
        ver = k.text(b"V")
        m = re.match(r"(?:rusEFI )?HaniCore (\w+) ([0-9A-F]{8})$", sig)
        if not m:
            raise SystemExit("not a HaniCore ECU: signature %r" % sig)
        say("ECU   : %s | %s" % (sig, ver))
        say("image : %s | %s" % (app["signature"], app["version"]))
        if m.group(1) != app["sig_board"] or board_text(ver) != app["board_text"]:
            raise SystemExit("WRONG BOARD: the ECU is %r, the image is for %r"
                             % (board_text(ver) or m.group(1), app["board_text"]))
        same_layout = m.group(2) == app["layout"]
        say("page layout %s -> %s: %s" % (m.group(2), app["layout"],
            "SAME - the tune stays in the ECU" if same_layout
            else "CHANGED - the tune will be migrated by field name"))
        old_ini = find_ini(sig, args.old_ini)
        new_ini = find_ini(app["signature"], args.new_ini)
        if new_ini is None:
            raise SystemExit("no .ini for the image's signature %r (give --new-ini)"
                             % app["signature"])
        if not same_layout and old_ini is None and not args.no_restore:
            raise SystemExit("the layout changes and no .ini decodes the ECU's "
                             "page (%r): give --old-ini, or --no-restore" % sig)
        st = k.status()
        if st["marker"] != UPD_MARKER:
            raise SystemExit("the ECU's firmware has no OBD updater (OCH 490 = "
                             "0x%04X): flash an --updater image once by bootmode"
                             % st["marker"])

        u = Updater(k, say)
        u.kwp = args.kwp
        if not args.dry_run:
            u.begin_erase(st)       # STAGING only; the tune is read meanwhile
            if args.fast and getattr(k, "base_baud", 0) >= 124800:
                u.go_fast()
        # ---- 1. save the tune, always, before anything is written ---------
        page_before = k.page_read()
        (out / "page_before.bin").write_bytes(page_before)
        (out / "identity.json").write_text(json.dumps({
            "ecu_signature": sig, "ecu_version": ver,
            "ecu_ini": str(old_ini) if old_ini else None,
            "image": str(args.image), "image_signature": app["signature"],
            "image_build": app["build_id"], "image_ini": str(new_ini)}, indent=1))
        say("tune saved: %s (decodes with %s)" % (out / "page_before.bin",
                                                  old_ini.name if old_ini else "?"))
        if args.dry_run:
            say("--dry-run: nothing sent to the flash")
            return 0

        # ---- 2. stage, seal, commit -------------------------------------
        t_stage = time.monotonic()
        u.stage(app, progress=lambda i, n, _dt: say(
            "  %4d/%d chunks  %5.1f s" % (i, n, time.monotonic() - t_stage)))
        u.commit()
        say("COMMIT sent - the ECU resets into the loader")
        say("ECU is back: %s" % wait_reboot(k, app["build_id"], say=say, kwp=args.kwp))
        if args.watch_boot:
            # diagnostic: does the page the ECU serves change in the first
            # seconds after the loader's reset? (bench 2026-10-30: one read
            # 0.6 s after reboot saw board defaults where the tune was stored)
            import hashlib
            last = None
            t_w = time.monotonic()
            while time.monotonic() - t_w < args.watch_boot:
                try:
                    src = int.from_bytes(k.och(12, 2), "big")
                    pg = k.page_read()
                except LinkError:
                    continue
                h = hashlib.sha256(pg).hexdigest()[:12]
                if (h, src) != last:
                    say("watch-boot +%.2f s: page %s cfgSource %d" % (time.monotonic() - t_w, h, src))
                    (out / ("boot_page_%s.bin" % h)).write_bytes(pg)
                    last = (h, src)
        sig2 = k.text(b"S")
        if sig2 != app["signature"]:
            raise SystemExit("ECU signature %r != image %r" % (sig2, app["signature"]))

        # ---- 3. keep the tune --------------------------------------------
        result = {"same_layout": same_layout, "new_build": app["build_id"]}
        if args.no_restore:
            say("--no-restore: the saved page is in %s" % out)
        else:
            new_text = new_ini.read_text(encoding="utf-8", errors="replace")
            base = k.page_read()
            (out / "page_after_update.bin").write_bytes(base)
            if same_layout:
                want = page_before
                result["kept_without_writes"] = base == page_before
                say("tune after the update %s the saved page"
                    % ("EQUALS" if base == page_before else "DIFFERS FROM"))
            else:
                old_text = old_ini.read_text(encoding="utf-8", errors="replace")
                want, rep = MIG.migrate(page_before, MIG.parse_ini(old_text), base,
                                        MIG.parse_ini(new_text),
                                        MIG.table_order(old_text),
                                        MIG.table_order(new_text))
                (out / "migration_report.json").write_text(json.dumps(rep, indent=1))
                say("migrated by field name: %d copied, %d converted, %d new "
                    "(firmware default), %d dropped, %d refused"
                    % (len(rep["copied"]), len(rep["converted"]),
                       len(rep["new_default"]), len(rep["dropped"]),
                       len(rep["refused"])))
            (out / "page_restored.bin").write_bytes(want)
            r = restore_page(k, want, new_text, say, force_burn=not same_layout)
            result.update(r)
            if r["burned"]:
                ch = och_channels(new_text)
                src = int.from_bytes(k.och(ch["nvmSource"][0], 2), "big")
                gen = int.from_bytes(k.och(ch["nvmGeneration"][0], 2), "big")
                result.update(nvmSource=src, nvmGeneration=gen)
                say("store: nvmSource 0x%04X, generation %d" % (src, gen))
            say("tune %s" % ("restored and Burned" if r["burned"]
                             else "kept - nothing to write"))
        (out / "result.json").write_text(json.dumps(result, indent=1))
        say("UPDATE COMPLETE: build %s" % app["build_id"])
        return 0
    finally:
        k.close()
        logf.close()


# ================================== self-test ================================

class FakeEcu:
    """A model of the ECU side of the status contract (hcdiag711.c): enough to
    prove the host's stop-and-wait, refusal and lost-reply handling. It models
    OUR protocol, not the flash - the flash path is proven on the bench."""

    def __init__(self, drop_every=0, lose_reply_every=0, refuse_begin=False,
                 busy_every=0):
        self.state, self.err, self.recv, self.seq, self.rc, self.cmd = ST_IDLE, 0, 0, 0, 0, 0
        self.crc = 0xFFFFFFFF
        self.erase_polls = 0
        self.writing_polls = 0
        self.mem = bytearray(b"\xFF" * 0x40000)
        self.n = 0
        self.drop_every, self.lose_reply_every = drop_every, lose_reply_every
        self.refuse_begin = refuse_begin
        self.writes = 0
        self.sealing = False
        self.wn = 0
        self.busy_every = busy_every

    def _note(self, cmd, rc):
        self.cmd, self.rc, self.seq = ord(cmd), rc, (self.seq + 1) & 0xFF

    def status(self):
        if self.state == ST_ERASING:
            self.erase_polls += 1
            if self.erase_polls > 3:
                self.state = ST_READY
        elif self.state == ST_WRITING:
            self.writing_polls += 1
            if self.writing_polls > 1:
                self.state = ST_SEALED if self.sealing else ST_READY
        w = [self.state, self.err, self.recv >> 16, self.recv & 0xFFFF,
             (self.seq << 8) | self.rc, self.cmd, UPD_MARKER, 0, 4]
        return decode_status(b"".join(v.to_bytes(2, "big") for v in w))

    def request(self, payload, data_len, **kw):
        self.n += 1
        if self.drop_every and self.n % self.drop_every == 0:
            raise LinkError("frame lost")
        c, p = chr(payload[1]), payload[2:]
        if c == "u":
            if self.refuse_begin:
                self._note("u", 2)
            else:
                self.state, self.erase_polls, self.recv = ST_ERASING, 0, 0
                self.crc = 0xFFFFFFFF
                self._note("u", 0)
        elif c == "w":
            off = int.from_bytes(p[:4], "big")
            data = p[4:]
            self.wn += 1
            busy = self.busy_every and self.wn % self.busy_every == 0
            if (self.state not in (ST_READY, ST_WRITING) or self.sealing
                    or off != self.recv or busy):
                self._note("w", 3)          # refused: out of order / full
            else:
                self.writes += 1
                self.mem[off:off + len(data)] = data
                for i, b in enumerate(data):
                    if not (0x200 <= off + i < 0x220):
                        self.crc = binascii.crc32(bytes([b]), self.crc ^ 0xFFFFFFFF) ^ 0xFFFFFFFF
                self.recv += len(data)
                self.state, self.writing_polls, self.sealing = ST_WRITING, 0, False
                self._note("w", 0)
        elif c == "x":
            if (self.crc ^ 0xFFFFFFFF) != int.from_bytes(p[:4], "big"):
                self.state, self.err = ST_FAILED, 3
                self._note("x", 3)
            else:
                self.state, self.writing_polls, self.sealing = ST_WRITING, 0, True
                self._note("x", 0)
        elif c == "y":
            self.state = ST_COMMIT
        if self.lose_reply_every and self.n % self.lose_reply_every == 0:
            raise LinkError("reply lost")
        return b""

    def retry(self, payload, data_len, tries=4, **kw):
        for _ in range(tries):
            try:
                return self.request(payload, data_len)
            except LinkError:
                pass
        raise LinkError("gave up")


def self_test() -> int:
    """Offline proof of the host-side contract against every built --updater
    image, plus the stop-and-wait driver against FakeEcu. No ECU, no serial."""
    import glob
    checks = fails = 0

    def ck(name, ok, detail=""):
        nonlocal checks, fails
        checks += 1
        fails += not ok
        print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))

    print("=== hc_update.py host-side contract (offline) ===\n")

    # 1. plan_chunks covers the whole image, word-aligned, no gaps/overlaps,
    #    never straddling a 64 KiB segment (hc_upd_write refuses that)
    for length in (0x220, 0x221, 0x1000, 0x308A8, 0x3121E, 0x40000):
        ch = plan_chunks(length)
        covered = ch[-1][0] + ch[-1][1]
        contiguous = all(ch[i][0] == ch[i - 1][0] + ch[i - 1][1]
                         for i in range(1, len(ch)))
        aligned = all((o % 2 == 0 and n % 2 == 0) for o, n in ch)
        in_seg = all((o >> 16) == ((o + n - 1) >> 16) for o, n in ch)
        ck(f"plan_chunks covers 0x{length:X} contiguously, word-aligned",
           covered >= length and contiguous and aligned and in_seg and ch[0][0] == 0,
           f"{len(ch)} chunks -> 0x{covered:X}")

    # 2. a wrong-board / unsealed / bad-CRC image is refused
    good = bytearray(b"\xFF" * 0x100000)
    for o, v in ((HDR_OFF, HDR_MAGIC0), (HDR_OFF + 2, HDR_MAGIC1),
                 (HDR_OFF + 4, 2)):
        good[o:o + 2] = struct.pack("<H", v)
    good[HDR_OFF + 6:HDR_OFF + 10] = struct.pack("<HH", 0x0200, 0x0084)
    length = 0x1000
    good[HDR_OFF + 10:HDR_OFF + 14] = struct.pack("<I", length)
    good[HDR_OFF + 18:HDR_OFF + 22] = struct.pack("<I", 0x12345678)
    good[HDR_OFF + 30:HDR_OFF + 32] = struct.pack("<H", HDR_SEAL)
    ident = b"HaniCore ME71C4 83D8361E\0HaniCore V1 / X build 12345678\0"
    ck("an ECU on an older image (signature 'rusEFI HaniCore ...') is still recognised",
       SIG_RE.search(b"rusEFI HaniCore ME711 83D8361E\0") is not None
       and SIG_RE.search(b"HaniCore ME711 83D8361E\0").group(1) == b"ME711")
    good[APP_BASE + 0x400:APP_BASE + 0x400 + len(ident)] = ident
    crc = binascii.crc32(bytes(good[APP_BASE:HDR_OFF])
                         + bytes(good[HDR_OFF + 32:APP_BASE + length])) & 0xFFFFFFFF
    good[HDR_OFF + 14:HDR_OFF + 18] = struct.pack("<I", crc)
    try:
        a = parse_app(bytes(good))
        ck("a self-consistent synthetic image parses (signature, layout)",
           a["sig_board"] == "ME71C4" and a["layout"] == "83D8361E")
    except ImageError as e:
        ck("a self-consistent synthetic image parses", False, str(e))
    bad = bytearray(good)
    bad[HDR_OFF + 30] = 0
    ck("an unsealed image is refused", _refused(bytes(bad)))
    bad = bytearray(good)
    bad[APP_BASE + 0x10] ^= 0xFF            # corrupt a body byte -> CRC moves
    ck("a corrupted body (CRC mismatch) is refused", _refused(bytes(bad)))

    # 3. the stop-and-wait driver against the status-channel model
    syn = parse_app(bytes(good))
    quiet = lambda *_: None                 # noqa: E731
    for name, ecu in (("clean link", FakeEcu()),
                      ("every 7th frame lost", FakeEcu(drop_every=7)),
                      ("every 5th reply lost (chunk landed)", FakeEcu(lose_reply_every=5)),
                      ("every 11th chunk refused (queue full)", FakeEcu(busy_every=11))):
        try:
            Updater(ecu, quiet, poll_s=0, chunk_timeout_s=0.05).stage(syn)
            ok = (ecu.state == ST_SEALED and ecu.mem[:length] == syn["body"][:length]
                  and ecu.writes == len(plan_chunks(length)))
            ck("driver stages + seals, " + name, ok,
               "%d writes for %d chunks" % (ecu.writes, len(plan_chunks(length))))
        except (SystemExit, LinkError) as e:
            ck("driver stages + seals, " + name, False, str(e))
    try:
        Updater(FakeEcu(refuse_begin=True), quiet, poll_s=0).stage(syn)
        ck("a refused STAGE_BEGIN (engine running) stops the host", False)
    except SystemExit as e:
        ck("a refused STAGE_BEGIN (engine running) stops the host",
           "VALIDATE" in str(e), str(e)[:40])
    wrong = dict(syn, crc=syn["crc"] ^ 1)
    try:
        Updater(FakeEcu(), quiet, poll_s=0).stage(wrong)
        ck("a CRC the ECU does not match refuses the SEAL", False)
    except SystemExit as e:
        ck("a CRC the ECU does not match refuses the SEAL", "REFUSED SEAL" in str(e))

    # 4. every built --updater image parses, its CRC and identity agree
    imgs = sorted(glob.glob(str(ROOT / "bins/hanicore/*_updater.bin")))
    if not imgs:
        print("  (no --updater image built yet; skipping the live-image check)")
    for p in imgs:
        try:
            a = parse_app(Path(p).read_bytes())
            ini = find_ini(a["signature"], None)
            ck(f"{Path(p).name}: {a['board_name']} crc 0x{a['crc']:08X} "
               f"layout {a['layout']} build {a['build_id']}", ini is not None,
               "ini " + (ini.name if ini else "MISSING"))
        except ImageError as e:
            ck(f"{Path(p).name} parses", False, str(e))

    # 5. the tune-keep branch: migrating a page to its OWN layout is identity
    #    (same layout = keep), and migration keeps a set field across a
    #    synthetic layout move (a field shifted by a new one before it).
    ini_p = find_ini(syn["signature"], None)
    if ini_p is not None:
        t = ini_p.read_text(encoding="utf-8", errors="replace")
        c = MIG.parse_ini(t)
        page = bytes((i * 7) & 0xFF for i in range(PAGE))
        same, _rep = MIG.migrate(page, c, b"\0" * PAGE, c,
                                 MIG.table_order(t), MIG.table_order(t))
        def field(pg, d):
            if d.kind == "bits":
                lo, hi = d.bits
                return (int.from_bytes(pg[d.off:d.off + d.width], "big") >> lo)                     & ((1 << (hi - lo + 1)) - 1)
            return pg[d.off:d.off + d.width * d.count]
        mism = [n for n, d in c.items() if n not in MIG.NEVER
                and field(same, d) != field(page, d)]
        ck("same layout: migrate() returns every field unchanged", not mism,
           "%d fields" % len(c))
        name = "displacementCc" if "displacementCc" in c else sorted(c)[0]
        f = c[name]
        moved = {name: MIG.Const(f.name, f.kind, f.typ, f.off + 2, f.shape, f.scale,
                                f.translate, f.lo, f.hi, f.bits, f.labels)}
        out_p, rep = MIG.migrate(page, c, b"\0" * PAGE, moved)
        w = f.width * f.count
        ck(f"layout move: '{name}' follows its field to the new offset",
           out_p[f.off + 2:f.off + 2 + w] == page[f.off:f.off + w])

    print(f"\n{checks - fails}/{checks} checks pass")
    return 1 if fails else 0


def _refused(image: bytes) -> bool:
    try:
        parse_app(image)
        return False
    except ImageError:
        return True


def main() -> int:
    ap = argparse.ArgumentParser(description="update a HaniCore ECU over K-line")
    ap.add_argument("--self-test", action="store_true",
                    help="offline proof of the image contract; no ECU")
    ap.add_argument("--image", help="the --updater .bin to flash")
    ap.add_argument("--port", help="serial port (e.g. COM3)")
    ap.add_argument("--baud", type=int, default=124800,
                    help="link rate; 124800 (default) falls back to 57600")
    ap.add_argument("--out", help="folder for the saved tune and the log "
                                  "(default hc_update_<UTC time>)")
    ap.add_argument("--old-ini", help="the .ini of the firmware now in the ECU "
                                      "(default: found by its signature)")
    ap.add_argument("--new-ini", help="the .ini of the image (default: found "
                                      "by its signature)")
    ap.add_argument("--no-restore", action="store_true",
                    help="flash only; leave the saved page for a manual restore")
    ap.add_argument("--dry-run", action="store_true",
                    help="identify and save the tune; flash nothing")
    ap.add_argument("--watch-boot", type=float, default=0.0, metavar="S",
                    help="diagnostic: after the reboot, log every change of the "
                         "served page / cfgSource for S seconds")
    ap.add_argument("--kwp", action="store_true",
                    help="enter through the car's OBD port (5-baud KWP, then the "
                         "HaniCore GOFAST) instead of a direct TunerStudio link")
    ap.add_argument("--gap-ms", type=float, default=1.0,
                    help="quiet time after each ECU reply before the next request")
    ap.add_argument("--no-fast", dest="fast", action="store_false",
                    help="stay at --baud for the transfer (no 250 kbaud '!b')")
    ap.add_argument("--trace", action="store_true",
                    help="write every TX/RX frame to <out>/kline_trace.txt")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if not args.image:
        ap.error("--image is required (or use --self-test)")
    try:
        app = parse_app(Path(args.image).read_bytes())
    except ImageError as e:
        print(f"REFUSED: {e}")
        return 1
    print(f"image OK: {app['board_name']} (board {app['board']}), build "
          f"{app['build_id']}, {app['length']} bytes, crc 0x{app['crc']:08X}, "
          f"layout {app['layout']}")
    if not args.port:
        print("no --port: nothing sent (image validated only)")
        return 0
    return update_over_serial(args, app)


if __name__ == "__main__":
    raise SystemExit(main())
