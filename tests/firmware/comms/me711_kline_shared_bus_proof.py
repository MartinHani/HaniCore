#!/usr/bin/env python3
r"""
me711_kline_shared_bus_proof.py - HaniCore on the car's SHARED K-line
(docs/ARCHITECTURE.md), executed out of the
LINKED image in c167sim with the tester modelled by me711_kwp_entry_proof.

    py tests\firmware\comms\me711_kline_shared_bus_proof.py
    py tests\firmware\comms\me711_kline_shared_bus_proof.py --control   12B46583 must FAIL

  S1  silent to noise: a plain 'S' on an unlocked line gets NO reply
      (the 12B46583 car image blurts the ~40-byte signature onto the bus)
  S2  silent to noise: a frame with a bad CRC on an unlocked line gets no
      reply either
  S3  a CRC-valid request is answered (and locks the link); a plain 'S' on
      the LOCKED link is then answered - direct TunerStudio is unchanged
  F1  ISO 14230 fast init: 25 ms low + 25 ms high, then StartCommunication
      81 01 F1 81 F4 at 10400 -> 83 F1 01 C1 EF 8F <cs>
  F2  ... and the session is real: IDENTIFY 'HC' -> F0 + the signature
  F3  a 60 ms low is not a wake-up: StartCommunication after it is ignored
  F4  a 25 ms low while bytes stream in (the ECU's own 0x00-rich reply,
      echoed) is not a wake-up: the locked rate stays
  P1  GOFAST 115200 with no request at 115200 for 2.5 s -> back at 10400
  R1  a 5-baud 0x01 that follows only 30 ms after line traffic is decoded
      (the decoder arms after 20 ms of idle, no longer 300 ms)
  R2  a line held mostly low by 0x00-rich traffic (the ECU's own reply) is
      NOT a 5-baud start bit (the 1 ms tick must see it low throughout)

NOT PHYSICAL: the bench steps are tests/physical/me711_kline_shared_bus_qualify.py.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402

CONTROL_BINS = ROOT.parent / "evidence" / "CAR_20261011_REVIEW" / "image_12B46583"
if "--control" in sys.argv:
    os.environ["HANICORE_ME711_BINS"] = str(CONTROL_BINS)

import me711_kwp_entry_proof as G       # noqa: E402
import me711_heartbeat_gap_proof as HB  # noqa: E402,F401
import me711_image as PI                # noqa: E402

FAILS = 0
KEYBYTES = bytes([0x55, 0xEF, 0x8F])


def check(name, ok, detail=""):
    global FAILS
    print("  [%s] %-64s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def kwp(data: bytes, tgt=0x01, fmt=None) -> bytes:
    f = bytes([(fmt if fmt is not None else 0x80) | len(data), tgt, 0xF1]) + data
    return f + bytes([sum(f) & 0xFF])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", action="store_true")
    a = ap.parse_args()
    print("=== HaniCore on a shared K-line ===")
    print("  image %s  sha256 %s\n" % (PI.image(), PI.sha256()))
    T = G.Tester()
    T.run_ms(600)

    # S1 / S2: the line is unlocked after boot
    m = T.mark()
    T.send(b"S", 57600)
    T.run_ms(80)
    tx = T.tx_since(m)
    check("S1 a plain 'S' on an unlocked line: no reply", tx == b"",
          "%d bytes sent" % len(tx))
    m = T.mark()
    T.send(b"\x00\x01S\x00\x00\x00\x00", 57600)   # length 1, CRC wrong
    T.run_ms(80)
    tx = T.tx_since(m)
    check("S2 a bad-CRC frame on an unlocked line: no reply", tx == b"",
          "%d bytes sent" % len(tx))

    # S3: a real request locks it; then plain bytes are served again
    got = T.ask(G.OCH8, T.rate() or 57600)
    rate = T.rate()
    check("S3 a CRC-valid request is answered", bool(got), "rate %s" % rate)
    m = T.mark()
    T.send(b"S", rate)
    T.run_ms(80)
    tx = T.tx_since(m)
    check("S3 ... and on the LOCKED link a plain 'S' is answered",
          G.SIG in tx, tx[:30])

    # F3: a 60 ms low is not a wake-up
    T.run_ms(100)
    T.pin(0); T.run_ms(60); T.pin(1); T.run_ms(25)
    m = T.mark()
    T.send(kwp(b"\x81"), 10400)
    T.run_ms(80)
    r = T.tx_since(m)
    check("F3 a 60 ms low is not a wake-up (StartCommunication ignored)",
          b"\xC1" not in r, r.hex())

    # F1: the ISO 14230 wake-up
    T.run_ms(400)
    T.pin(0); T.run_ms(25); T.pin(1); T.run_ms(25)
    m = T.mark()
    T.send(kwp(b"\x81"), 10400)
    T.run_ms(80)
    r = T.tx_since(m)
    want = bytes([0x83, 0xF1, 0x01, 0xC1, 0xEF, 0x8F])
    want += bytes([sum(want) & 0xFF])
    check("F1 fast init + StartCommunication -> 83 F1 01 C1 EF 8F cs",
          r == want, "%s (rate %s)" % (r.hex(), T.rate()))

    # F2: the session is real
    m = T.mark()
    T.send(kwp(b"\xB0HC"), 10400)
    T.run_ms(150)
    r = T.tx_since(m)
    check("F2 ... and IDENTIFY 'HC' -> F0 + the signature",
          r[3:4] == b"\xF0" and G.SIG in r, r[:32])

    # P1: GOFAST on probation
    m = T.mark()
    T.send(kwp(b"\xB1\x04"), 10400)
    T.run_ms(80)
    r = T.tx_since(m)
    T.run_ms(20)
    at_new = T.rate()
    T.run_ms(2500)
    check("P1 GOFAST 115200 -> F1 04, the rate moves (%s)" % at_new,
          r[3:5] == b"\xF1\x04" and at_new == 115200, r.hex())
    check("P1 ... no request at 115200 for 2.5 s -> back at 10400",
          T.rate() == 10400, "rate %s" % T.rate())

    # R1: 5-baud 30 ms after bus traffic. The traffic is put ON THE PIN (the
    # tester's UART bytes do not toggle the modelled P3.11): 2 ms of each
    # 4 ms low for 400 ms - a cluster talking - then 30 ms of idle.
    T.run_ms(400)
    for _ in range(100):
        T.pin(0); T.run_ms(2); T.pin(1); T.run_ms(2)
    T.run_ms(30)
    m = T.mark()
    T.five_baud(0x01)
    sync = None
    for i in range(30):
        T.run_ms(10)
        if T.tx_since(m).endswith(KEYBYTES):
            sync = (i + 1) * 10
            break
    check("R1 5-baud 0x01 only 30 ms after traffic -> 55 EF 8F",
          sync is not None, "after %s ms, %s" % (sync, T.tx_since(m).hex()))

    # R2 (2026-10-14, a bench finding): the ECU's OWN long reply full of 0x00
    # bytes keeps the line ~90 % low. Modelled on the pin as 9 ms low / 1 ms
    # high for 1.8 s after a long idle (which arms even a 300 ms decoder),
    # then idle - the reply ends, so a sparse sampler sees a "start bit",
    # eight low "data bits" and a high "stop bit" = a 5-baud 0x00. It must NOT
    # be taken for a 5-baud byte at all - no keybytes, no new count.
    T.run_ms(1500)
    cnt0 = T.och16(846)
    m = T.mark()
    for _ in range(180):
        T.pin(0); T.run_ms(9); T.pin(1); T.run_ms(1)
    T.run_ms(800)
    cnt1 = T.och16(846)
    tx = T.tx_since(m)
    check("R2 0x00-like traffic (9 ms low / 1 ms high) is not a 5-baud byte",
          KEYBYTES not in tx and cnt0 == cnt1,
          "kwpCounts %04X -> %04X, tx %s" % (cnt0, cnt1, tx[:12].hex()))

    # F4 (2026-10-14, a bench finding): the ECU's OWN reply full of 0x00
    # bytes, echoed onto RXD0, holds the pin low on every 1 ms sample for
    # 20..30 ms - the 1 ms tick took it for a fast-init wake-up and forced
    # 10400 in the middle of a 57600 session. Modelled as the pin held low
    # for 25 ms while bytes stream in (they move DSTP6), then high: the
    # locked 57600 link must stay, and no wake-up window may open.
    T.run_ms(400)
    T.ask(G.OCH8, rate)         # locked again at the TunerStudio rate
    rate = T.rate()
    T.pin(0)
    for _ in range(5):
        T.send(b"\x00" * 20, rate)
        T.run_ms(5)
    T.pin(1)
    T.run_ms(25)
    m = T.mark()
    T.send(kwp(b"\x81"), 10400)
    T.run_ms(80)
    r = T.tx_since(m)
    check("F4 a low line WITH bytes flowing is not a wake-up (no 10400)",
          T.rate() != 10400 and b"\xC1" not in r,
          "rate %s, %s" % (T.rate(), r[:12].hex()))

    print()
    if a.control:
        if FAILS:
            print("CONTROL (12B46583): FAILS as it must (%d)" % FAILS)
            return 0
        print("CONTROL PASSED - the gate cannot tell the car image apart")
        return 1
    print("SHARED-BUS K-LINE PROOF %s - %d failed"
          % ("PASSES" if not FAILS else "FAILS", FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
