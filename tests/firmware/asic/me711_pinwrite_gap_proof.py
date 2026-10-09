#!/usr/bin/env python3
r"""
me711_pinwrite_gap_proof.py - the worst gap between two S5500 services
(hc_asic_start_service entries) while TunerStudio writes an injector ROUTING
byte, in c167sim, for the image HANICORE_ME711_STEM names.

    set HANICORE_ME711_STEM=HaniCore_ME711_v80_runon & py tests\firmware\asic\me711_pinwrite_gap_proof.py
    set HANICORE_ME711_STEM=HaniCore_ME711_v81_far_cold & py tests\firmware\asic\me711_pinwrite_gap_proof.py

WHY. On the real ECU (2026-09-25, V81) twelve injector-pin writes raised
asicTimeouts by ~4 each burst while every other write added none. A routing
write revalidates the routing, and V81 moved that code into FCODE behind far
thunks. The S5500 budget is 10 ms; this measures the gap directly on both
images with the same bytes.
"""
from __future__ import annotations

import binascii
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_heartbeat_gap_proof as HB     # noqa: E402
import me711_image as PI                   # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
LIMIT_MS = 6.5


def env(payload: bytes) -> bytes:
    crc = binascii.crc32(payload) & 0xFFFFFFFF
    return bytes([0, len(payload)]) + payload + crc.to_bytes(4, "big")


def main() -> int:
    gen = (ROOT / "firmware/generated/hc_config_generated.h").read_text()
    inj = int(re.search(r"#define\s+CFG_U_PIN_INJ\s+(\d+)u", gen).group(1))
    rig = HB.Rig(PI.image(), HB.ENTRY_CURRENT, HB.TICK_CURRENT, echo=False)
    boot = 3_000_000
    rig.run(boot)
    base = len(rig.entries)
    t0 = rig.cpu.steps
    for k in range(3):
        rig.queue_rx(t0 + 50_000 + k * 400_000,
                     env(b"W" + (inj + k).to_bytes(2, "big") + b"\xFF"))
    rig.run(1_400_000)
    e = [x for x in rig.entries[base:]]
    gaps = [s1 - s0 for (_, s0), (_, s1) in zip(e, e[1:])]
    worst = max(gaps) / HB.STEPS_PER_MS if gaps else 0.0
    over = sum(1 for g in gaps if g / HB.STEPS_PER_MS > 10.0)
    print("image %s\n  services after the writes: %d, worst gap %.2f ms, "
          "gaps over 10 ms: %d, trap %s" % (PI.image().name, len(gaps), worst,
                                           over, rig.trap))
    # V82 measured 5.14 ms (the apply yields); V81 8.29 ms and V80 6.00 ms
    # (both unyielded - V80 only by phase luck). 6.5 ms leaves room for an
    # ordinary frame-build pass and fails the unyielded apply.
    ok = rig.trap is None and worst <= LIMIT_MS
    print("RESULT: %s (limit %.1f ms)" % ("PASS" if ok else "FAIL", LIMIT_MS))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
