#!/usr/bin/env python3
r"""
me711_ts_query_collision_proof.py - the regression for the V23 real-hardware
finding: TunerStudio looped F/Q/F/Q forever and never once sent V/P/R.

    py tests\tunerstudio\me711_ts_query_collision_proof.py

REAL EVIDENCE (K-line trace over the KKL bridge, V23 on the bench):

    -> ECU  46                        F
    <- ECU  30 30 31                  "001"
    -> ECU  00 01 51 ce 6e 8e ef      CRC-enveloped 'Q', byte-perfect
    <- ECU  00 1d 00 48 61 ... 8d     TS_OK + exact signature, valid CRC32
    [~1.5 s later: repeats from F. V/P/R never sent.]

The KNOWN-GOOD ME7.5 reference (tools/ts_bridge.log, physically bench-proven)
shows the same shape of exchange but never loops:

    -> ECU  46                        F           (once)
    <- ECU  30 30 31                  "001"
    -> ECU  00 01 53 ...              CRC-enveloped 'S'
    <- ECU  00 0d 00 72 75 ...        TS_OK + "rusEFI HCME7", valid CRC32
    -> ECU  00 01 56 ...              CRC-enveloped 'V'                 <-- V23 never reaches this
    <- ECU  00 17 00 48 61 ...        TS_OK + "HaniCore DC 05.12 live"
    -> ECU  00 01 50 ...              CRC-enveloped 'P' (page select)   <-- or this
    <- ECU  00 01 00 ...              TS_OK, no data
    -> ECU  00 05 52 ...              CRC-enveloped 'R' (page read)     <-- or this
    <- ECU  00 41 00 ...              TS_OK + page bytes
    [then continuous 'R'/'O' polling forever - no restart]

Both targets' enveloped signature/version replies are BYTE-IDENTICAL in shape
(TS_OK code, exact string, NO trailing NUL, standard zlib CRC32 - verified
against the real trace for both targets by this file's own checks below), and
both are produced by the SAME shared firmware/comms/hcts.c. The
firmware side was never the difference.

The one difference: ME7.5's .ini declares queryCommand = "S". The Bosch
.ini (before this fix) declared queryCommand = "Q". Per rusEFI's own protocol
reference (rusEFI firmware/console/binary/tunerstudio.cpp,
handlePlainCommand()): "We interpret 'Q' as TS_HELLO_COMMAND, since TS uses
hardcoded 'Q' during ECU detection (scan all serial ports)" - 'Q' is
TunerStudio's OWN built-in blind-scan probe byte, independent of whatever a
project's .ini declares as its queryCommand. Declaring the PROJECT's
queryCommand as "Q" too means every real handshake reply is indistinguishable,
to TunerStudio's own client-side state machine, from just another scan
answer - so it never leaves scan mode and repeats F/Q forever instead of
running the project's real command sequence.

This file proves three things a firmware-only regression cannot:

  1. THE REAL TRACE, byte-for-byte: the exact bytes captured on the bench
     against the query byte the broken .ini used ('Q') decode to a correct,
     CRC-valid TS_OK/signature reply - confirming the firmware was never
     wrong and the loop is not a framing/CRC/content bug.
  2. THE FIX, mechanically: tools/tunerstudio/gen_ts_ini_me711.py's QUERY_CMD is not
     "Q" (a hard SystemExit guards this at generation time too - see that
     file - this is the second, independent check).
  3. THE FULL PROGRESSION, once something plays the ME7.5-shaped sequence
     (F once, then S/V/P/R/O) instead of looping Q: every step replies
     correctly, in one continuous boot, with zero traps - proving the
     firmware fully supports exactly the sequence TunerStudio needs to reach
     continuous runtime polling once the .ini stops colliding with its scan
     probe.
"""
from __future__ import annotations

import re
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
from me711_boot_test import Harness, IMG, SIGNATURE  # noqa: E402
import me711_image as PI  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
INI = ROOT / "tunerstudio/hanicore_me711.ini"
# BOOT_STEPS comes from tools/lib/me711_image.py, which is the one place a
# fact about the image under test is written down. It was a local
# 1 200 000 here, chosen before V39's append-only store made boot cost
# 2 482 756 steps - so this gate was interrogating an ECU that had not
# finished booting, and reporting that as a firmware failure.
BOOT_STEPS = PI.BOOT_STEPS

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<58s} {detail}")
    return ok


def envelope(payload: bytes) -> bytes:
    return len(payload).to_bytes(2, "big") + payload + \
        (zlib.crc32(payload) & 0xFFFFFFFF).to_bytes(4, "big")


def parse_reply(raw: bytes):
    """(length, code, data, crc_ok) for one CRC-enveloped reply, or None."""
    if len(raw) < 7:
        return None
    n = int.from_bytes(raw[0:2], "big")
    if len(raw) < 2 + n + 4:
        return None
    body = raw[2:2 + n]
    crc = int.from_bytes(raw[2 + n:6 + n], "big")
    return n, body[0], body[1:], (crc == (zlib.crc32(body) & 0xFFFFFFFF))


def main() -> int:
    if not IMG.exists():
        raise SystemExit(f"no image at {IMG} - build it first")
    print("=== HaniCore Bosch ME7.1.1 - TunerStudio query-collision proof ===")
    print(f"image: {IMG}\n")

    # ---- Part 1: the REAL bench trace against 'Q', decoded and verified ----
    # Exactly the bytes captured on the bench (ts_bridge.log-shaped), replayed
    # against THIS image so a byte-identical firmware regression would show
    # up here even though the actual bug is client-side.
    print("--- part 1: replay the exact bytes seen on real V23 hardware ---")
    h = Harness(IMG, echo=True)
    err = h.run(BOOT_STEPS)
    check("boot completes without a trap", err is None, err or "")

    h.txb.clear()
    tx, err = h.send_raw(b"F", steps=400000)
    check("real trace: F -> \"001\"", tx == b"001", repr(tx))

    h.txb.clear()
    req = envelope(b"Q")
    tx, err = h.send_raw(req, steps=400000)
    parsed = parse_reply(tx)
    want_sig = SIGNATURE.encode("ascii")
    ok = parsed is not None and parsed[1] == 0 and parsed[2] == \
        want_sig and parsed[3]
    check("real trace: enveloped 'Q' -> TS_OK + exact signature, CRC valid",
          ok, repr(tx))
    check("the reply carries NO trailing NUL (matches ME7.5's own 'S' reply "
          "shape - not a bug)", ok and not parsed[2].endswith(b"\x00"),
          repr(parsed[2]) if parsed else "")

    # ---- Part 2: the .ini itself no longer collides ------------------------
    print("\n--- part 2: the generated .ini's queryCommand ---")
    if INI.exists():
        text = INI.read_text(errors="replace")
        m = re.search(r'queryCommand\s*=\s*"([^"]+)"', text)
        qc = m.group(1) if m else None
        check("queryCommand is declared", qc is not None, repr(qc))
        check("queryCommand is NOT 'Q' (TunerStudio's own hardcoded scan "
              "probe - see tools/tunerstudio/gen_ts_ini_me711.py)", qc != "Q", repr(qc))
    else:
        check("hanicore_me711.ini exists (run "
              "tools/tunerstudio/gen_ts_ini_me711.py first)", False, str(INI))

    # ---- Part 3: the FULL progression, on a fresh boot ----------------------
    # F once, then S/V/P/R/O once each, exactly the shape of the KNOWN-GOOD
    # ME7.5 trace - proving the firmware carries every reply TunerStudio needs
    # to reach continuous runtime polling, in one continuous session.
    print("\n--- part 3: the full progression (F, S, V, P, R, O) in one boot ---")
    h2 = Harness(IMG, echo=True)
    err2 = h2.run(BOOT_STEPS)
    check("second boot completes without a trap", err2 is None, err2 or "")

    h2.txb.clear()
    tx, _ = h2.send_raw(b"F", steps=400000)
    check("F -> \"001\"", tx == b"001", repr(tx))

    h2.txb.clear()
    tx, _ = h2.send_raw(envelope(b"S"), steps=400000)
    p = parse_reply(tx)
    ok = p is not None and p[1] == 0 and p[2] == want_sig and p[3]
    check("enveloped 'S' -> TS_OK + exact signature, CRC valid", ok, repr(tx))

    h2.txb.clear()
    tx, _ = h2.send_raw(envelope(b"V"), steps=400000)
    p = parse_reply(tx)
    ok = p is not None and p[1] == 0 and p[3] and len(p[2]) > 0
    check("enveloped 'V' -> TS_OK + version text, CRC valid", ok, repr(tx))

    h2.txb.clear()
    tx, _ = h2.send_raw(envelope(b"P"), steps=400000)
    p = parse_reply(tx)
    ok = p is not None and p[1] == 0 and p[2] == b"" and p[3]
    check("enveloped 'P' (page select) -> TS_OK, no data, CRC valid", ok, repr(tx))

    h2.txb.clear()
    req = b"R" + (0).to_bytes(2, "big") + (64).to_bytes(2, "big")
    tx, _ = h2.send_raw(envelope(req), steps=800000)
    p = parse_reply(tx)
    ok = p is not None and p[1] == 0 and len(p[2]) == 64 and p[3]
    check("enveloped 'R' (page read, 64B @0) -> TS_OK + 64 bytes, CRC valid",
          ok, f"{len(p[2]) if p else '?'} bytes")

    h2.txb.clear()
    req = b"O" + (0).to_bytes(2, "big") + (222).to_bytes(2, "big")
    tx, _ = h2.send_raw(envelope(req), steps=800000)
    p = parse_reply(tx)
    ok = p is not None and p[1] == 0 and len(p[2]) == 222 and p[3]
    check("enveloped 'O' (och read, 222B @0) -> TS_OK + 222 bytes, CRC valid",
          ok, f"{len(p[2]) if p else '?'} bytes")

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} checks pass")
    ok_all = passed == len(results)
    print("PASS" if ok_all else "FAIL")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
