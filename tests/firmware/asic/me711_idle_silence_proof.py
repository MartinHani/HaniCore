#!/usr/bin/env python3
r"""
me711_idle_silence_proof.py - prove K-line is SILENT from RESET onward, for
the Bosch ME7.1.1 image built with every unsolicited boot/debug/heartbeat
transmit removed.

    py tests\firmware\asic\me711_idle_silence_proof.py

V22 removed hb_service() (the once-per-second "H\n" bench heartbeat) and this
gate originally only checked the window AFTER the boot banner - which V22
still transmitted unsolicited. Real-hardware K-line tracing over a genuine
KKL cable (no host-side echo cancellation) then showed the boot banner ITSELF
- "HCRST B=...", "HC711 RELAYVxx CAL=...", "HCSTEP ST=...", and the
"HCE/HCDM/HCD/HCPM..." ASIC-dump lines - going out unsolicited too, which is
exactly what was competing with TunerStudio's F/Q detection and driving its
~4 s retry loop.

V23 removes those calls (reset_report(), banner(), step_line(),
hc_asicdump_print()) as well, so this gate now checks the FULL window: from
the very first simulated instruction (reset) through several seconds of idle
- zero bytes transmitted anywhere in that span unless a host request is
queued. F/Q are proven separately, on a fresh harness, to confirm they still
answer once something actually asks.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import c167sim as S  # noqa: E402
from me711_boot_test import Harness, IMG  # noqa: E402
import me711_image as PI  # noqa: E402

STEPS_PER_MS = 2500          # per tests/firmware/asic/me711_heartbeat_gap_proof.py
IDLE_SECONDS = 5
# BOOT_STEPS comes from tools/lib/me711_image.py, which is the one place a
# fact about the image under test is written down. It was a local
# 1 200 000 here, chosen before V39's append-only store made boot cost
# 2 482 756 steps - so this gate was interrogating an ECU that had not
# finished booting, and reporting that as a firmware failure.
BOOT_STEPS = PI.BOOT_STEPS


def main() -> int:
    if not IMG.exists():
        raise SystemExit(f"no image at {IMG} - build it first")
    print("=== HaniCore Bosch ME7.1.1 - reset-to-idle K-line silence proof ===")
    print(f"image: {IMG}")

    # ---- the FULL window: reset through boot through several idle seconds,
    # ONE continuous run, no host request queued anywhere in it. This is the
    # window V22's version of this gate did not cover - it only checked AFTER
    # the boot banner, which V22 still transmitted unsolicited. ----
    h = Harness(IMG, echo=True)
    total_steps = BOOT_STEPS + IDLE_SECONDS * 1000 * STEPS_PER_MS
    err = h.run(total_steps)
    tx = bytes(h.txb)
    ok = True

    if err is not None:
        print(f"  [FAIL] reset-to-idle window runs without a trap  {err}")
        ok = False
    else:
        print(f"  [PASS] reset-to-idle window runs without a trap")

    silent = len(tx) == 0
    print(f"  [{'PASS' if silent else 'FAIL'}] K-line silent from RESET "
          f"through {IDLE_SECONDS}s idle, no host request      "
          f"{len(tx)} byte(s) transmitted"
          + (f"  {tx[:64]!r}" if tx else ""))
    ok = ok and silent

    # ---- F/Q still answer, on a FRESH boot, once something actually asks ---
    h2 = Harness(IMG, echo=True)
    err2 = h2.run(BOOT_STEPS)
    if err2 is not None:
        print(f"  [FAIL] second boot (for F/Q) runs without a trap {err2}")
        ok = False
    # 2026-10-14 (the maintainer's design notes.1): on the car's
    # shared K-line a plain byte may be someone else's traffic, so a plain
    # F/Q is answered only once a CRC-valid request has LOCKED the link.
    h2.txb.clear()
    f0, _ = h2.send_raw(b"F", steps=400000)
    unl_ok = f0 == b""
    print(f"  [{'PASS' if unl_ok else 'FAIL'}] a plain F on an UNLOCKED line is not answered"
          f"{'':<6}{f0!r}")
    ok = ok and unl_ok
    sig, errS = h2.send(b"S")
    lock_ok = errS is None and b"HaniCore" in sig
    print(f"  [{'PASS' if lock_ok else 'FAIL'}] a CRC-valid 'S' is answered (locks the link)"
          f"{'':<5}{sig[:24]!r}")
    ok = ok and lock_ok
    h2.txb.clear()
    f_reply, errF = h2.send_raw(b"F", steps=400000)
    h2.txb.clear()
    q_reply, errQ = h2.send_raw(b"Q", steps=400000)

    f_ok = f_reply == b"001" and errF is None
    print(f"  [{'PASS' if f_ok else 'FAIL'}] F still answers \"001\" on the locked link"
          f"{'':<28}{f_reply!r}")
    ok = ok and f_ok

    q_ok = q_reply.rstrip(b"\x00") != b"" and errQ is None and q_reply.endswith(b"\x00")
    print(f"  [{'PASS' if q_ok else 'FAIL'}] Q still answers the signature (locked)"
          f"{'':<11}{q_reply!r}")
    ok = ok and q_ok

    print()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
