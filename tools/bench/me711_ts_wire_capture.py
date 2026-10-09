#!/usr/bin/env python3
r"""me711_ts_wire_capture.py - a timestamped K-line transcript of one sequence.

    py tools\bench\me711_ts_wire_capture.py --script burn --out evidence\...\dir

Every byte in and out, with a monotonic timestamp, decoded into frames
afterwards.  It is deliberately NOT a protocol client: it writes the bytes a
host would write and records everything that comes back, including bytes that
arrive long after the reply was supposed to, which is the whole point.

Read-only apart from the exact commands named on the command line.
"""
from __future__ import annotations

import argparse
import binascii
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import serial

RESP = {0x00: "TS_OK", 0x04: "TS_BURN_OK", 0x80: "TS_UNDERRUN",
        0x81: "TS_OVERRUN", 0x82: "TS_BAD_CRC", 0x83: "TS_BAD_CMD",
        0x84: "TS_OUT_OF_RANGE", 0x8D: "TS_FRAMING_ERROR"}


def env(p: bytes) -> bytes:
    return bytes([0, len(p)]) + p + (binascii.crc32(p) & 0xFFFFFFFF).to_bytes(4, "big")


class Wire:
    def __init__(self, port, baud, out: Path):
        self.ser = serial.Serial(port, baud, timeout=0.02, write_timeout=2.0)
        self.t0 = time.monotonic()
        self.ev = []
        self.out = out

    def t(self):
        return round((time.monotonic() - self.t0) * 1000.0, 3)

    def note(self, what, **kw):
        e = {"ms": self.t(), "ev": what}
        e.update(kw)
        self.ev.append(e)
        print("%9.3f  %-10s %s" % (e["ms"], what,
                                   " ".join("%s=%s" % (k, v) for k, v in kw.items())),
              flush=True)

    def tx(self, data: bytes, label=""):
        self.ser.write(data)
        self.ser.flush()
        self.note("TX", label=label, hex=data.hex())

    def listen(self, seconds: float, label=""):
        end = time.monotonic() + seconds
        buf = bytearray()
        while time.monotonic() < end:
            p = self.ser.read(256)
            if p:
                self.note("RX", label=label, n=len(p), hex=p.hex())
                buf.extend(p)
        return bytes(buf)

    def close(self):
        self.ser.close()
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "wire_events.json").write_text(
            json.dumps(self.ev, indent=2) + "\n", encoding="ascii")


def decode(stream: bytes, echo: bytes):
    """What a HOST sees: the echo it must skip, then framed replies."""
    out = []
    i = 0
    if stream.startswith(echo):
        out.append({"kind": "own-echo", "hex": echo.hex()})
        i = len(echo)
    while i + 6 <= len(stream):
        n = (stream[i] << 8) | stream[i + 1]
        if n == 0 or i + 2 + n + 4 > len(stream):
            break
        blob = stream[i + 2:i + 2 + n]
        crc = int.from_bytes(stream[i + 2 + n:i + 6 + n], "big")
        ok = crc == (binascii.crc32(blob) & 0xFFFFFFFF)
        out.append({"kind": "frame", "len": n, "code": blob[0],
                    "code_name": RESP.get(blob[0], "0x%02X" % blob[0]),
                    "payload": blob[1:].hex(), "crc_ok": ok,
                    "hex": stream[i:i + 6 + n].hex()})
        i += 6 + n
    if i < len(stream):
        out.append({"kind": "trailing", "hex": stream[i:].hex()})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--baud", type=int, default=57600)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--script", default="burn",
                    choices=["burn", "burn-poll", "reconnect", "sig"])
    ap.add_argument("--listen", type=float, default=8.0)
    a = ap.parse_args()

    w = Wire(a.port, a.baud, a.out)
    res = {"utc": datetime.now(timezone.utc).isoformat(), "script": a.script}
    try:
        w.ser.reset_input_buffer()
        if a.script == "sig":
            q = env(b"S")
            w.tx(q, "query S")
            res["decoded"] = decode(w.listen(2.0, "S"), q)

        elif a.script == "burn":
            b = env(b"B")
            w.tx(b, "BURN")
            raw = w.listen(a.listen, "burn")
            res["decoded"] = decode(raw, b)
            # what the NEXT request sees - this is reconnect #1's first move
            time.sleep(0.2)
            q = env(b"S")
            w.tx(q, "query S after burn")
            res["after"] = decode(w.listen(2.0, "after"), q)

        elif a.script == "burn-poll":
            b = env(b"B")
            w.tx(b, "BURN")
            time.sleep(0.5)
            o = env(b"O" + (0).to_bytes(2, "big") + (722).to_bytes(2, "big"))
            w.tx(o, "OCH poll during burn")
            raw = w.listen(a.listen, "burn+poll")
            res["decoded"] = decode(raw, b)
            time.sleep(0.2)
            q = env(b"S")
            w.tx(q, "query S after burn")
            res["after"] = decode(w.listen(2.0, "after"), q)

        elif a.script == "reconnect":
            for cmd, lbl in ((b"S", "sig"), (b"Q", "query"), (b"V", "ver"),
                             (b"F", "proto"), (b"S", "sig2")):
                q = env(cmd)
                w.tx(q, lbl)
                res.setdefault("steps", []).append(
                    {"cmd": cmd.decode(), "decoded": decode(w.listen(1.5, lbl), q)})
    finally:
        w.close()
    (a.out / ("decoded_%s.json" % a.script)).write_text(
        json.dumps(res, indent=2) + "\n", encoding="ascii")
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
