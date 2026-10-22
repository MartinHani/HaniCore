#!/usr/bin/env python3
r"""
me711_kwp_connect_test.py - tools/vehicle/me711_kwp_connect.py against a FAKE ECU,
offline (no port, no bench). The fake follows the maintainer's design notes:
it decodes the 5-baud byte from the tool's BREAK timing, echoes every byte the
tool writes (a KKL does), answers the handshake, StartCommunication,
IDENTIFY and GOFAST, and a TunerStudio 'V' only at the negotiated rate.

    py tests\unit\me711_kwp_connect_test.py
"""
from __future__ import annotations

import binascii
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_kwp_connect as K          # noqa: E402

FAILS = 0
SIG = b"rusEFI HaniCore ME711 F26F2BF7"


def check(name, ok, detail=""):
    global FAILS
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


class FakeEcu:
    def __init__(self, mode="good"):
        self.mode = mode
        self.baudrate = 10400
        self.rx = bytearray()          # what the tool will read
        self._brk = []                 # (t, state)
        self.ecu_rate = 57600
        self.state = "idle"
        self.identified = False
        self.buf = bytearray()
        self.sync_at = None            # W1: the sync leaves 60 ms later

    # pyserial surface
    @property
    def break_condition(self):
        return bool(self._brk and self._brk[-1][1])

    @break_condition.setter
    def break_condition(self, v):
        self._brk.append((time.perf_counter(), bool(v)))
        if not v and len(self._brk) >= 3:
            self._decode()

    def reset_input_buffer(self):
        self.rx.clear()

    def read(self, n):
        if self.sync_at is not None and time.perf_counter() >= self.sync_at:
            self.sync_at = None
            self.rx.extend(b"\x55\xEF\x8F")
        out = bytes(self.rx[:n])
        del self.rx[:n]
        return out

    def write(self, data):
        self.rx.extend(data)           # the KKL echo
        if self.baudrate != self.ecu_rate:
            return len(data)           # garbage to the ECU
        self.buf.extend(data)
        self._serve()
        return len(data)

    # the ECU
    def _decode(self):
        t0 = self._brk[0][0]
        span = self._brk[-1][0] - t0
        if span < 9.5 * K.BIT_S:
            return
        bits = []
        for i in range(10):
            tc = t0 + (i + 0.5) * K.BIT_S
            st = False
            for t, s in self._brk:
                if t <= tc:
                    st = s
            bits.append(0 if st else 1)
        self._brk = []
        addr = sum(b << i for i, b in enumerate(bits[1:9]))
        if bits[0] == 0 and bits[9] == 1 and addr == 0x01:
            self.ecu_rate = 10400
            self.state = "compl"
            if self.mode != "nosync":
                self.sync_at = time.perf_counter() + 0.06   # W1

    def _reply(self, data):
        f = bytes([0x80 | len(data), 0xF1, 0x01]) + data
        self.rx.extend(f + bytes([sum(f) & 0xFF]))

    def _serve(self):
        if self.state == "compl":
            if self.buf[:1] == b"\x70":
                self.rx.extend(b"\xFE")
                self.state = "session"
            self.buf.clear()
            return
        if self.state == "session":
            if len(self.buf) < 1:
                return
            n = (self.buf[0] & 0x3F) + 4
            if len(self.buf) < n:
                return
            f, self.buf = bytes(self.buf[:n]), self.buf[n:]
            if (sum(f[:-1]) & 0xFF) != f[-1]:
                return
            d = f[3:-1]
            if d[0] == 0x81:
                self._reply(b"\xC1")
            elif d[0] == 0xB0 and d[1:3] == b"HC":
                self.identified = True
                self._reply(b"\xF0" + SIG)
            elif d[0] == 0xB1:
                if not self.identified:
                    self._reply(b"\x7F\xB1\x22")
                else:
                    self._reply(b"\xF1" + d[1:2])
                    self.ecu_rate = {1: 10400, 2: 57600, 3: 124800}[d[1]]
                    self.state = "private"
            return
        if self.state == "private":
            if len(self.buf) >= 7 and self.buf[2:3] == b"V":
                self.buf.clear()
                blob = b"\x00" + b"HaniCore V94 LINK / Bosch ME7.1.1\x00"
                crc = binascii.crc32(blob) & 0xFFFFFFFF
                self.rx.extend(len(blob).to_bytes(2, "big") + blob
                               + crc.to_bytes(4, "big"))


def main() -> int:
    K.BIT_S = 0.02
    print("=== me711_kwp_connect against a fake ECU ===")
    for rate in (124800, 57600):
        e = FakeEcu()
        r = K.attempt(K.Wire(e), rate, lambda s: None)
        check("full entry at %d: stage 7, identity read" % rate,
              r["ok"] and r["stage"] == 7 and "V94" in r.get("identity", ""),
              "stage %s" % r["stage"])
        check("... the IDENTIFY signature carries the layout id",
              r.get("signature", "").endswith("F26F2BF7"),
              r.get("signature", ""))
    e = FakeEcu(mode="nosync")
    r = K.attempt(K.Wire(e), 124800, lambda s: None)
    check("no sync from the ECU: stops at stage 1, not ok",
          not r["ok"] and r["stage"] == 1, "stage %s" % r["stage"])
    print()
    print("KWP CONNECT TOOL TEST %s - %d failed"
          % ("PASSES" if not FAILS else "FAILS", FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
