#!/usr/bin/env python3
r"""Probe the TunerStudio protocol on the real ECU over the K-line.

TunerStudio only ever says "Protocol Error", which does not distinguish
between three very different faults:

  1. the ECU never received the request      -> nothing comes back at all
  2. the K-line echoed our own request back  -> the reply is prefixed by the
     request bytes, and TunerStudio chokes on the leading garbage
  3. the ECU replied but the content is bad  -> a parseable frame with a bad
     code or CRC

This prints the raw bytes and says which of the three it is.

    py tools\bench\ts_serial_probe.py --port COM3
"""
from __future__ import annotations

import argparse
import sys
import time
import zlib

try:
    import serial
except ImportError:
    print("pyserial is required:  py -m pip install pyserial")
    sys.exit(2)


def frame(payload: bytes) -> bytes:
    return (len(payload).to_bytes(2, "big") + payload
            + zlib.crc32(payload).to_bytes(4, "big"))


def show(tag: str, data: bytes) -> None:
    if not data:
        print(f"  {tag}: <nothing>")
        return
    print(f"  {tag}: {len(data)} bytes")
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        hexs = " ".join(f"{b:02X}" for b in chunk)
        txt = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print(f"    {i:04X}  {hexs:<47}  {txt}")


def probe(port: str, baud: int, payload: bytes, label: str) -> None:
    print(f"\n=== {label}: sending {payload!r} ===")
    req = frame(payload)
    show("request", req)

    with serial.Serial(port, baud, timeout=0.4) as s:
        s.reset_input_buffer()
        s.write(req)
        s.flush()
        got = bytearray()
        deadline = time.time() + 2.0
        while time.time() < deadline:
            chunk = s.read(64)
            if chunk:
                got.extend(chunk)
                deadline = time.time() + 0.4
    show("received", bytes(got))

    if not got:
        print("  VERDICT: nothing came back. The ECU is not receiving, or its")
        print("           reply is not reaching the PC. This is fault (1).")
        return

    echoed = bytes(got).startswith(req)
    if echoed:
        print("  VERDICT: the first bytes are OUR OWN REQUEST echoed back by the")
        print("           K-line. This is fault (2) - TunerStudio cannot strip")
        print("           this, so the ECU must not answer until the echo has")
        print("           passed, or the echo must be suppressed.")
        rest = bytes(got)[len(req):]
    else:
        rest = bytes(got)
    show("after echo", rest)

    if len(rest) >= 7:
        n = int.from_bytes(rest[:2], "big")
        if len(rest) >= 2 + n + 4:
            body = rest[2:2 + n]
            crc = int.from_bytes(rest[2 + n:6 + n], "big")
            ok = crc == zlib.crc32(body)
            print(f"  parsed: code=0x{body[0]:02X} len={n - 1} "
                  f"crc={'ok' if ok else 'BAD'} data={body[1:]!r}")
            return
    print("  VERDICT: bytes came back but they are not a complete envelope.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=10400)
    args = ap.parse_args()

    print("Power-cycle the ECU now if you want to catch the boot banner.")
    print("Listening 3 s for the banner first...")
    with serial.Serial(args.port, args.baud, timeout=0.4) as s:
        banner = bytearray()
        end = time.time() + 3.0
        while time.time() < end:
            banner.extend(s.read(64))
    show("banner", bytes(banner))

    probe(args.port, args.baud, b"S", "signature query")
    probe(args.port, args.baud, b"O" + (0).to_bytes(2, "big")
          + (16).to_bytes(2, "big"), "output channels")
    return 0


if __name__ == "__main__":
    sys.exit(main())
