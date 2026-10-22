#!/usr/bin/env python3
r"""
me711_kwp_connect.py - enter HaniCore through the VAG/KWP vehicle path with a
KKL: 5-baud 0x01, the ISO 14230 handshake, HaniCore IDENTIFY and GOFAST, then
one TunerStudio request at the negotiated rate. Read-only: nothing is written
to the ECU's page, nothing is Burned.

    py tools\vehicle\me711_kwp_connect.py [--port COM3] [--rate 124800|57600]
        [--repeat N] [--out <dir>]

WHAT IT CHECKS, per attempt (the firmware side: hckwp_me711.c,
firmware/comms/hckline.c; the wire spec: the maintainer's design notes):
  1  5-baud 0x01 by the adapter's BREAK (200 ms a bit, LSB first)
  2  at 10400: 55 EF 8F from the ECU within W1 + 3 bytes
  3  our complement 70 -> the ECU's FE
  4  StartCommunication -> C1
  5  IDENTIFY B0 'HC' -> F0 + signature (names the page layout / .ini)
  6  GOFAST B1 <rate> -> F1 <rate> at 10400; then the port moves
  7  a TunerStudio 'V' request at the new rate: a CRC-valid answer
--repeat runs the whole sequence N times (the ECU returns to the hunt when
the tool closes the port and the line goes quiet) and prints a histogram.

The KKL echoes what it sends; every read skips our own bytes first.
"""
from __future__ import annotations

import argparse
import binascii
import json
import sys
import time
from pathlib import Path

RATE_CODE = {10400: 0x01, 57600: 0x02, 124800: 0x03, 115200: 0x04}  # 0x04: V96
BIT_S = 0.2          # 5 baud; the offline test shortens it


def kwp(data: bytes) -> bytes:
    f = bytes([0x80 | len(data), 0x01, 0xF1]) + data
    return f + bytes([sum(f) & 0xFF])


def envelope(payload: bytes) -> bytes:
    crc = binascii.crc32(payload) & 0xFFFFFFFF
    return bytes([0x00, len(payload)]) + payload + crc.to_bytes(4, "big")


class Wire:
    """The KKL, or anything with pyserial's surface (tests pass a fake)."""

    def __init__(self, ser):
        self.ser = ser

    def five_baud(self, addr: int, bit_s: float = 0.2):
        self.ser.baudrate = 10400
        bits = [0] + [(addr >> i) & 1 for i in range(8)] + [1]
        t = time.perf_counter()
        for i, b in enumerate(bits):
            self.ser.break_condition = (b == 0)
            t_next = t + (i + 1) * bit_s
            while time.perf_counter() < t_next:
                time.sleep(0.001)
        self.ser.break_condition = False
        self.ser.reset_input_buffer()

    def read(self, n: int, timeout: float) -> bytes:
        got = bytearray()
        t_end = time.perf_counter() + timeout
        while len(got) < n and time.perf_counter() < t_end:
            part = self.ser.read(n - len(got))
            if part:
                got.extend(part)
        return bytes(got)

    def send(self, data: bytes, timeout: float = 0.5) -> bool:
        """write, and swallow the adapter's echo of it"""
        self.ser.write(data)
        echo = self.read(len(data), timeout)
        return echo == data

    def kwp_request(self, data: bytes, timeout: float = 0.3):
        self.send(kwp(data))
        head = self.read(3, timeout)
        if len(head) < 3:
            return None
        n = head[0] & 0x3F
        extra = 0
        if n == 0:
            ln = self.read(1, timeout)
            if not ln:
                return None
            n, extra = ln[0], 1
            head += ln
        rest = self.read(n + 1, timeout)
        frame = head + rest
        if len(rest) < n + 1 or (sum(frame[:-1]) & 0xFF) != frame[-1]:
            return None
        return frame[3 + extra:3 + extra + n]


def attempt(wire: Wire, rate: int, log) -> dict:
    r = {"stage": 0, "ok": False}
    wire.five_baud(0x01, BIT_S)
    r["stage"] = 1
    sync = wire.read(3, 0.4)
    r["sync"] = sync.hex()
    if sync != b"\x55\xEF\x8F":
        log("  no sync: %s" % sync.hex())
        return r
    r["stage"] = 2
    time.sleep(0.03)                       # W4: 25..50 ms
    wire.send(b"\x70")
    fe = wire.read(1, 0.2)
    if fe != b"\xFE":
        log("  no ECU complement: %s" % fe.hex())
        return r
    r["stage"] = 3
    d = wire.kwp_request(b"\x81")
    if not d or d[0] != 0xC1:
        log("  StartCommunication: %s" % (d.hex() if d else None))
        return r
    r["stage"] = 4
    d = wire.kwp_request(b"\xB0\x48\x43", 0.6)
    if not d or d[0] != 0xF0:
        log("  IDENTIFY: %s" % (d.hex() if d else None))
        return r
    r["signature"] = d[1:].decode("latin1", "replace")
    r["stage"] = 5
    d = wire.kwp_request(bytes([0xB1, RATE_CODE[rate]]))
    if not d or d[:2] != bytes([0xF1, RATE_CODE[rate]]):
        log("  GOFAST: %s" % (d.hex() if d else None))
        return r
    r["stage"] = 6
    time.sleep(0.02)                       # the ECU switches after its reply
    wire.ser.baudrate = rate
    wire.ser.reset_input_buffer()
    req = envelope(b"V")
    wire.send(req)
    body = wire.read(3, 0.5)
    if len(body) >= 2:
        n = (body[0] << 8) | body[1]
        body += wire.read(n + 6 - len(body), 0.5)
        blob = body[2:2 + n]
        if len(body) >= n + 6 and int.from_bytes(body[2 + n:6 + n], "big") \
                == (binascii.crc32(blob) & 0xFFFFFFFF):
            r["identity"] = blob[1:].split(b"\0")[0].decode("latin1",
                                                            "replace")
            r["stage"] = 7
            r["ok"] = True
    if not r["ok"]:
        log("  no TunerStudio answer at %d: %s" % (rate, body.hex()))
    return r


def main() -> int:
    import serial
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--rate", type=int, default=124800,
                    choices=(57600, 115200, 124800))
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--quiet-s", type=float, default=6.0,
                    help="pause between attempts (P3 5 s ends a session)")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    out = Path(a.out) if a.out else None
    if out:
        out.mkdir(parents=True, exist_ok=True)

    def log(s):
        print(s, flush=True)

    rows = []
    for i in range(a.repeat):
        ser = serial.Serial(a.port, 10400, timeout=0.02,
                            write_timeout=1.0)
        try:
            r = attempt(Wire(ser), a.rate, log)
        finally:
            ser.close()
        rows.append(r)
        log("attempt %d: %s stage %d %s" % (i + 1, "OK " if r["ok"] else
                                            "FAIL", r["stage"],
                                            r.get("identity", "")))
        if i + 1 < a.repeat:
            time.sleep(a.quiet_s)
    hist = {}
    for r in rows:
        k = "ok" if r["ok"] else "stage%d" % r["stage"]
        hist[k] = hist.get(k, 0) + 1
    res = {"rate": a.rate, "attempts": len(rows), "histogram": hist,
           "rows": rows}
    print(json.dumps({"rate": a.rate, "histogram": hist}))
    if out:
        (out / "kwp_connect.json").write_text(json.dumps(res, indent=1))
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
