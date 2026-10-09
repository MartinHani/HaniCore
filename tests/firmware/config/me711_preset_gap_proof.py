#!/usr/bin/env python3
r"""
me711_preset_gap_proof.py - the worst gap between two S5500 services while
TunerStudio selects the 1.8T preset and presses APPLY ENGINE PRESET, in
c167sim, over the real serial path (framed 'W' then framed '!E').

    py tests\firmware\config\me711_preset_gap_proof.py

WHY. The preset apply (V86) is the heaviest single configuration pass this
firmware runs: ~240 staged bytes, two whole-page validations and a full group
apply in one main-loop call. Every part of it sits behind the tick-gated
hcts_target_yield(), and this measures that it does, with the same 6.5 ms
limit me711_pinwrite_gap_proof uses against the 10 ms S5500 budget. It also
reads the verdict word back, so a run in which the apply never happened
cannot pass on a quiet loop.
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
OCH = 0x380000 + 0x2000                    # TGT_EXTRAM_BASE + TGT_RAM_OCH


def env(payload: bytes) -> bytes:
    crc = binascii.crc32(payload) & 0xFFFFFFFF
    return bytes([0, len(payload)]) + payload + crc.to_bytes(4, "big")


def run(pre: list[bytes], expect: int, label: str) -> bool:
    gen = (ROOT / "firmware/generated/hc_config_generated.h").read_text()
    sel = int(re.search(r"#define\s+CFG_U_ENGINE_PRESET\s+(\d+)u",
                        gen).group(1))
    # echo=True: the K-line loops every transmitted byte back, and hcts_tx()
    # drops one ring byte per byte sent - without the echo that drop eats the
    # NEXT request (the second frame here was lost that way).
    rig = HB.Rig(PI.image(), HB.ENTRY_CURRENT, HB.TICK_CURRENT, echo=True)
    rig.run(3_000_000)
    base = len(rig.entries)
    t0 = rig.cpu.steps
    at = t0 + 50_000
    for frame in pre + [b"W" + sel.to_bytes(2, "big") + b"", b"!E"]:
        rig.queue_rx(at, env(frame))
        at += 400_000
    rig.run(at - t0 + 2_600_000)
    e = list(rig.entries[base:])
    gaps = [s1 - s0 for (_, s0), (_, s1) in zip(e, e[1:])]
    worst = max(gaps) / HB.STEPS_PER_MS if gaps else 0.0
    over = sum(1 for g in gaps if g / HB.STEPS_PER_MS > 10.0)
    m = rig.mem
    verdict = (m.r8(OCH + 764) << 8) | m.r8(OCH + 765)
    ok = (rig.trap is None and worst <= LIMIT_MS and verdict == expect)
    print("%-9s services %d, worst gap %.2f ms, over 10 ms %d, trap %s, "
          "verdict 0x%04X (want 0x%04X)  %s"
          % (label, len(gaps), worst, over, rig.trap, verdict, expect,
             "PASS" if ok else "FAIL"))
    return ok


def boot_poison() -> bool:
    """V86 bench finding: OCH 764..775 are battery-backed SRAM and read 0xFF03
    at power-up on the real ECU. Pre-load a stale PENDING request for the 1.8T
    preset and a garbage verdict, boot the whole image, and require that the
    boot cleared them and applied NOTHING."""
    gen = (ROOT / "firmware/generated/hc_config_generated.h").read_text()
    clt = int(re.search(r"#define\s+CFG_U_PIN_CLT\s+(\d+)u", gen).group(1))
    rig = HB.Rig(PI.image(), HB.ENTRY_CURRENT, HB.TICK_CURRENT, echo=True)
    m = rig.mem
    for k, v in ((764, 0xFF), (765, 0x03), (772, 0x01), (773, 0x03),
                 (770, 0x00), (771, 0x01)):
        m.w8(OCH + k, v)
    rig.run(4_000_000)
    w = lambda k: (m.r8(OCH + k) << 8) | m.r8(OCH + k + 1)   # noqa: E731
    des_clt = m.r8(0x385000 + clt)
    ok = w(764) == 0 and w(772) == 0 and w(770) == 0 and des_clt != 93
    print("BOOT      poisoned 772=0x0103 764=0xFF03 -> verdict 0x%04X pending "
          "0x%04X refresh %d, DESIRED pinClt %d  %s"
          % (w(764), w(772), w(770), des_clt, "PASS" if ok else "FAIL"))
    return ok


def main() -> int:
    gen = (ROOT / "firmware/generated/hc_config_generated.h").read_text()
    oil = int(re.search(r"#define\s+CFG_U_PIN_OIL_PRESS\s+(\d+)u",
                        gen).group(1))
    print("image %s   limit %.1f ms" % (PI.image().name, LIMIT_MS))
    a = run([], 0x0301, "APPLIED")
    # oil pressure on cavity 93 first: the preset's CLT = 93 then conflicts,
    # so the whole transaction is refused and every staged byte rolled back.
    b = run([b"W" + oil.to_bytes(2, "big") + b"]"], 0x0305, "REFUSED")
    c = boot_poison()
    print("RESULT: %s" % ("PASS" if a and b and c else "FAIL"))
    return 0 if a and b and c else 1


if __name__ == "__main__":
    sys.exit(main())
