#!/usr/bin/env python3
"""Deterministic host-side KKL echo/fragment/reconnect tests."""
from __future__ import annotations

import io
from unittest.mock import patch
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

from ts_kline_bridge import Bridge


class FakeSerial:
    def __init__(self):
        self.rx = bytearray()
        self.tx = bytearray()

    @property
    def in_waiting(self):
        return len(self.rx)

    def write(self, data):
        self.tx.extend(data)

    def flush(self):
        pass

    def read(self, n):
        out = bytes(self.rx[:n])
        del self.rx[:n]
        return out

    def reset_input_buffer(self):
        self.rx.clear()


def main() -> int:
    passed = 0
    total = 0

    def check(name, condition):
        nonlocal passed, total
        total += 1
        passed += bool(condition)
        print("  [%s] %s" % ("PASS" if condition else "FAIL", name))

    ser = FakeSerial()
    bridge = Bridge(ser, logfile=io.StringIO())

    bridge.to_ecu(b"Q")
    ser.rx.extend(b"QHaniCore")
    check("present echo is stripped", bridge.from_ecu() == b"HaniCore")

    bridge.to_ecu(b"Q")
    check("delayed reply may arrive after empty polls", bridge.from_ecu() == b"")
    ser.rx.extend(b"HaniCore")
    check("absent echo preserves the ECU reply", bridge.from_ecu() == b"HaniCore")

    request = bytes.fromhex("00 05 4f 00 00 00 de")
    reply = bytes.fromhex("00 03 00 12 34 aa bb cc dd")
    bridge.to_ecu(request)
    ser.rx.extend(request[:3])
    check("split echo prefix is held", bridge.from_ecu() == b"")
    ser.rx.extend(request[3:] + reply)
    check("split echo completes before reply", bridge.from_ecu() == reply)

    bridge.to_ecu(b"R\x00\x10")
    ser.rx.extend(b"R\x00")
    check("partial read can be held", bridge.from_ecu() == b"")
    with patch("ts_kline_bridge.time.time", return_value=bridge.echo_since + 0.25):
        check("stale partial prefix is released", bridge.from_ecu() == b"R\x00")

    bridge.to_ecu(b"F")
    ser.rx.extend(b"orphan")
    bridge.reset()
    check("reconnect clears stale serial and echo state",
          not ser.rx and not bridge.pending_echo and not bridge.echo_probe)

    bridge.to_ecu(b"Q")
    ser.rx.extend(b"Qsig")
    first = bridge.from_ecu()
    bridge.to_ecu(b"F")
    ser.rx.extend(b"F001")
    second = bridge.from_ecu()
    check("back-to-back requests stay aligned", first == b"sig" and second == b"001")

    print("\n%d/%d checks pass" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
