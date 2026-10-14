#!/usr/bin/env python3
r"""me711_rx_resync_meaning_proof.py - rxResync counts abandoned frames, not pauses.

    py tests\firmware\comms\me711_rx_resync_meaning_proof.py [--control <bins dir>]

THE DEFECT (car 2026-10-10: rxResync 2 -> 13 in one run; bench 7 per 188
requests, every request answered). The PEC6 receive tick marks the first byte
that arrives after >= 20 ms of line silence (hcserial711.c SER.pad), and
hcts_rx_pop() reset the parser there - correct - but counted rx_resync on
EVERY such byte, also when the parser was idle between two requests. So the
counter measured how often the host paused, and the one diagnostic that
should say "the ECU threw a half-received request away" could not be read.

Simulator (linked image, c167sim, real main loop, PEC6 receive at 57600):
  A  20 complete 'O' requests, each after a 30 ms pause: all answered with a
     valid CRC, rx_resync unchanged;
  B  a request cut after 5 bytes, 30 ms of silence, then a complete one:
     the complete one is answered, rx_resync +1 exactly;
  C  10 requests back to back (no pause): answered, rx_resync unchanged.
--control on an older image: A must FAIL (it counts every pause).
"""
from __future__ import annotations

import binascii
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if "--control" in sys.argv:
    os.environ["HANICORE_ME711_BINS"] = sys.argv[sys.argv.index("--control") + 1]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402
import me711_runtime_stress as RS  # noqa: E402

FAILS = 0


def check(name, ok, detail=""):
    global FAILS
    FAILS += 0 if ok else 1
    print("  [%s] %-60s %s" % ("PASS" if ok else "FAIL", name, detail))


def env(payload):
    return (len(payload).to_bytes(2, "big") + payload
            + (binascii.crc32(payload) & 0xFFFFFFFF).to_bytes(4, "big"))


REQ = env(b"O" + (0).to_bytes(2, "big") + (32).to_bytes(2, "big"))


def reply_ok(s, mark, n_och=32, wait_us=60_000):
    """Run until a complete reply after tx index `mark`; True if CRC-valid."""
    t = 0
    while t < wait_us:
        s.run_us(2_000)
        t += 2_000
        tx = s.rig.tx[mark:]
        if len(tx) >= 2:
            want = 2 + ((tx[0][1] << 8) | tx[1][1]) + 4
            if len(tx) >= want:
                body = bytes(b for _t, b in tx[:want])
                L = want - 6
                crc = int.from_bytes(body[2 + L:6 + L], "big")
                return crc == (binascii.crc32(body[2:2 + L]) & 0xFFFFFFFF) and L == n_och + 1
    return False


def main() -> int:
    print("=== rxResync counts abandoned frames only (simulator) ===")
    print("  image", RS.PI.image())
    s = RS.Stress(RS.build_awt_page(dbw=False), ts=False)
    s.boot()
    s.run_us(50_000)
    r0 = s.r16("rx_resync")

    ok = 0
    for _ in range(20):
        s.run_us(30_000)                       # a host pause
        mark = len(s.rig.tx)
        s.rig.rxq.extend(REQ)
        ok += reply_ok(s, mark)
    r1 = s.r16("rx_resync")
    check("A 20 requests after 30 ms pauses all answered", ok == 20, "%d/20" % ok)
    check("A ... rx_resync unchanged by pauses", r1 == r0, "%d -> %d" % (r0, r1))

    s.run_us(30_000)
    s.rig.rxq.extend(REQ[:5])                  # a half-received request
    s.run_us(40_000)                           # silence on the wire
    mark = len(s.rig.tx)
    s.rig.rxq.extend(REQ)
    good = reply_ok(s, mark)
    r2 = s.r16("rx_resync")
    check("B the request after an abandoned half frame is answered", good)
    check("B ... the abandonment is counted exactly once", r2 == r1 + 1,
          "%d -> %d" % (r1, r2))

    ok = 0
    for _ in range(10):
        mark = len(s.rig.tx)
        s.rig.rxq.extend(REQ)
        ok += reply_ok(s, mark)
    r3 = s.r16("rx_resync")
    check("C 10 back-to-back requests answered, rx_resync unchanged",
          ok == 10 and r3 == r2, "%d/10, %d -> %d" % (ok, r2, r3))
    print("\nPASS" if not FAILS else "\n%d FAIL" % FAILS)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
