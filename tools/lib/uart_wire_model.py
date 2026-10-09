#!/usr/bin/env python3
"""uart_wire_model.py - what an asynchronous receiver at one rate decodes from
8N1 bytes sent back to back at another. For gates that must model a HOST AT
THE WRONG RATE without assuming what the firmware will see.

THE RECEIVER (C167CR UM V3.1 ch. 11, ASC0 asynchronous mode): the input is
sampled at 16x the bit rate; a falling edge starts a frame; each bit is the
majority of the samples at 7, 8 and 9 sixteenths; a start bit that is not
low at its centre is a false start; the stop bit sampled low is a FRAMING
ERROR and the byte is still delivered (S0RBUF loaded, S0FE set). After a
frame the receiver waits for a new falling edge.

PINNED TO THE BENCH (V94, 2026-09-28, evidence V94_BENCH_20260928): an FTDI
host at 115200 (115 385 baud) into the ECU at 57600 (S0BG 0x15 = 56 818)
produced NO framing error over 36 'V' requests - this model decodes that
request as 18 CF 58 FD, all four clean - while a host at 124800 (125 000)
raised framing errors from the first request, as the model does too.
`selftest()` asserts both; a gate that imports the model runs it first.

THE RATES are the real ones, not the nominal ones: the ECU's from its S0BG
(fCPU = 40 MHz, baud = fCPU / (32 (S0BG+1))), the FT232's from its 3 MHz
divisor (the KKL on COM3 is an FTDI 0403:6001).
"""
from __future__ import annotations

import binascii

FCPU = 40_000_000


def ecu_baud(s0bg: int) -> float:
    return FCPU / (32.0 * (s0bg + 1))


FTDI = {57600: 3e6 / 52, 115200: 3e6 / 26, 124800: 3e6 / 24, 10400: 3e6 / 288.5}


def host_baud(nominal: int) -> float:
    return FTDI.get(nominal, float(nominal))


def receive(raw: bytes, tx_baud: float, rx_baud: float):
    """-> [(byte, framing_error)] as the receiver at rx_baud decodes raw."""
    bits = []
    for b in raw:
        bits += [0] + [(b >> i) & 1 for i in range(8)] + [1]
    T = 1.0 / tx_baud

    def level(t):
        if t < 0:
            return 1
        i = int(t / T)
        return bits[i] if i < len(bits) else 1

    tick = 1.0 / (16 * rx_baud)
    t, prev, out = 0.0, 1, []
    end = len(bits) * T + 20.0 / rx_baud
    while t < end:
        v = level(t)
        if prev == 1 and v == 0:
            t0 = t

            def samp(i):
                s = [level(t0 + (i * 16 + k) * tick) for k in (7, 8, 9)]
                return 1 if sum(s) >= 2 else 0
            if samp(0) != 0:
                prev = v
                t += tick
                continue
            b = 0
            for i in range(8):
                b |= samp(i + 1) << i
            out.append((b, samp(9) == 0))
            t = t0 + (9 * 16 + 9) * tick
            prev = level(t)
            continue
        prev = v
        t += tick
    return out


def envelope(p: bytes) -> bytes:
    return (bytes([0, len(p)]) + p
            + (binascii.crc32(p) & 0xFFFFFFFF).to_bytes(4, "big"))


def selftest() -> None:
    v = envelope(b"V")
    got = receive(v, host_baud(115200), ecu_baud(0x15))
    assert [b for b, _ in got] == [0x18, 0xCF, 0x58, 0xFD], got
    assert not any(fe for _, fe in got), "bench: 115200 into 57600 raised no FE"
    got = receive(v, host_baud(124800), ecu_baud(0x15))
    assert any(fe for _, fe in got), "bench: 124800 into 57600 raised FE"
    for bg, nom in ((0x15, 57600), (0x0A, 115200), (0x09, 124800)):
        same = receive(v, host_baud(nom), ecu_baud(bg))
        assert [b for b, _ in same] == list(v) and not any(f for _, f in same)


if __name__ == "__main__":
    selftest()
    print("uart_wire_model selftest: PASS")
