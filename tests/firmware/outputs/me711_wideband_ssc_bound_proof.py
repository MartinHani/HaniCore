#!/usr/bin/env python3
r"""
me711_wideband_ssc_bound_proof.py - a CJ120 exchange whose SSC never
completes cannot hold the main loop: the worst gap between two S5500
services with BOTH lambda banks polled is measured in c167sim with a live
SSC and with a DEAD one (no byte ever completes), over the real serial path.

    py tests\firmware\outputs\me711_wideband_ssc_bound_proof.py [--control]

WHY (HANDOFF_V97 E9). hcio711.c ssc_byte() polled SSCRIC for up to 2000
passes per byte, two bytes per 25 ms CJ120 slot: an SSC that stopped
completing cost ~6.4 ms of main loop per slot (the rig measured it before
the byte was modelled). V97 bounds each byte by T7 (64 us, 8x the 8 us wire
time at SSCBR 0x13) and aborts the transfer after a timed-out first byte.

THE CHECKS
  1. alive: both banks polled (cj120Xfers rises), no SSC timeout counted;
  2. dead:  the timeouts ARE counted on both chips (cjTmo) - the dead path
            ran, so the gap below was measured over it;
  3. dead:  both chips unverified (lambdaStatus bits 8/9 clear) - a dead SSC
            is never a verified chip;
  4. dead:  the worst service gap stays under LIMIT_MS and within
            MARGIN_MS of the live-SSC run.
--control patches the image's 64 us bound (80 T7 ticks) to 8000 ticks
(6.4 ms, the old pass-count cost) and requires check 4 to FAIL.
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
LIMIT_MS = 6.5            # me711_pinwrite/preset gap proofs' limit (10 ms S5500)
MARGIN_MS = 0.5           # what a dead SSC may add over a live one
OCH = 0x380000 + 0x2000   # TGT_EXTRAM_BASE + TGT_RAM_OCH
BOUND_TICKS = 80          # US_TO_TICKS(CJ_BYTE_TMO_US = 64) at 1.25 MHz
CONTROL_TICKS = 8000


def env(payload: bytes) -> bytes:
    crc = binascii.crc32(payload) & 0xFFFFFFFF
    return bytes([0, len(payload)]) + payload + crc.to_bytes(4, "big")


def gen_off(name: str) -> int:
    gen = (ROOT / "firmware/generated/hc_config_generated.h").read_text()
    return int(re.search(r"#define\s+%s\s+(\d+)u" % name, gen).group(1))


def bound_sites(img: bytes) -> list[int]:
    """The T7 comparison in ssc_byte(), read off the linked image (Keil):
        F2 Fn 50 F0   MOV  Rn, T7          (0xF050, reg167.h)
        20 xx         SUB  Rn, Rt0
        46 Fn 50 00   CMP  Rn, #0x0050     (80 ticks = 64 us)
    Found once, in FCODE (hcio711 is far). SEARCHED IN THE MODULE'S OWN
    CODE SECTION, read from the linked map (2026-10-11): the fixed window
    0x40000..0x60000 stopped containing it when FCODE grew into SA6 (V97;
    hcio711 links at 0x838010), and --control could no longer run."""
    out = []
    mm = re.search(r"^([0-9A-F]{6})H\s+([0-9A-F]{6})H\s+[0-9A-F]{6}H\s+CODE"
                   r".*\?PR\?HCIO711\s*$", PI.MAP.read_text(errors="replace"),
                   re.M)
    lo, hi = ((int(mm.group(1), 16) - 0x800000,
               int(mm.group(2), 16) - 0x800000 + 1) if mm else (0, len(img)))
    # Since the 2026-10-11 race fix the SSCRIC test sits between the T7
    # sample (MOV Rn,T7; SUB) and the CMP, so the compare is accepted when a
    # MOV Rn,T7 (F2 Fn 50 F0) precedes it within 32 bytes.
    pat = re.compile(rb"\x46[\xF0-\xFF]\x50\x00")
    t7 = re.compile(rb"\xF2[\xF0-\xFF]\x50\xF0")
    for m in pat.finditer(img, lo, hi):
        if t7.search(img, max(lo, m.start() - 32), m.start()):
            out.append(m.start())
    return out


def run(img_path: Path, dead: bool, label: str):
    s1, s2 = gen_off("CFG_U_LAM1_SRC"), gen_off("CFG_U_LAM2_SRC")
    rig = HB.Rig(img_path, HB.ENTRY_CURRENT, HB.TICK_CURRENT, echo=True)
    rig.ssc_dead = dead
    rig.run(3_000_000)
    t0 = rig.cpu.steps
    at = t0 + 50_000
    for frame in (b"W" + s1.to_bytes(2, "big") + b"\x01",
                  b"W" + s2.to_bytes(2, "big") + b"\x01"):
        rig.queue_rx(at, env(frame))
        at += 400_000
    rig.run(at - t0 + 300_000)                 # both writes applied
    base = len(rig.entries)
    m = rig.mem
    w = lambda k: (m.r8(OCH + k) << 8) | m.r8(OCH + k + 1)   # noqa: E731
    x0 = w(756)
    rig.run(4_000_000)                         # ~400 ms, 16 slots per chip
    e = list(rig.entries[base:])
    gaps = [b - a for (_, a), (_, b) in zip(e, e[1:])]
    worst = max(gaps) / HB.STEPS_PER_MS if gaps else 99.0
    r = {"worst": worst, "services": len(gaps), "xfers": w(756) - x0,
         "tmo": w(1014), "err": w(1012), "status": w(738),
         "mask": w(870), "trap": rig.trap}
    print("%-7s services %4d  worst gap %5.2f ms  CJ120 xfers %3d  "
          "cjTmo 0x%04X  cjErr 0x%04X  lambdaStatus 0x%04X  trap %s"
          % (label, r["services"], worst, r["xfers"], r["tmo"], r["err"],
             r["status"], r["trap"]))
    return r


def check(name, ok, detail=""):
    print("  [%s] %s %s" % ("PASS" if ok else "FAIL", name, detail))
    return ok


def verdict(img_path: Path) -> tuple[bool, bool]:
    live = run(img_path, False, "ALIVE")
    dead = run(img_path, True, "DEAD")
    ok = True
    ok &= check("alive: both chips polled, no SSC timeout",
                live["xfers"] >= 20 and live["tmo"] == 0
                and live["trap"] is None, "xfers %d" % live["xfers"])
    ok &= check("dead: timeouts counted on BOTH chips (the path ran)",
                (dead["tmo"] & 0xFF) >= 4 and (dead["tmo"] >> 8) >= 4,
                "cjTmo 0x%04X" % dead["tmo"])
    ok &= check("dead: neither chip verified",
                (dead["status"] & 0x0300) == 0,
                "lambdaStatus 0x%04X" % dead["status"])
    rel_ok = (dead["trap"] is None
              and dead["worst"] <= live["worst"] + MARGIN_MS)
    gap_ok = rel_ok and dead["worst"] <= LIMIT_MS
    ok &= check("dead: worst service gap bounded",
                gap_ok, "%.2f ms (live %.2f, limit %.1f, margin %.1f)"
                % (dead["worst"], live["worst"], LIMIT_MS, MARGIN_MS))
    # 5. WHAT THE BOUND PROTECTS IS THE LOOP (2026-10-11). Since the CJ120
    # slot only starts with >= 3 ms to the next S5500 frame, a long wait no
    # longer shows as a longer WORST gap in this rig; it shows as fewer
    # service passes in the same time. Measured: a 64 us bound 583 / 583,
    # the 6.4 ms control 479 / 583.
    loop_ok = dead["services"] >= 0.95 * live["services"]
    ok &= check("dead: the main loop keeps >= 95 % of its live service passes",
                loop_ok, "%d of %d" % (dead["services"], live["services"]))
    rel_ok = rel_ok and loop_ok
    # THE CONTROL JUDGES THE RELATIVE PART (2026-10-11): the absolute limit
    # also fails on the ordinary main-loop worst pass (~9.2 ms with a LIVE
    # SSC), so a control that only needed "the gap check fails" passed
    # whatever the bound was. What the bound protects is what a DEAD SSC adds.
    return ok, rel_ok


def main() -> int:
    img_path = PI.image()
    img = img_path.read_bytes()
    print("image %s" % img_path.name)
    sites = bound_sites(img)
    ok, _ = verdict(img_path)
    if "--control" in sys.argv:
        if len(sites) != 1:
            print("CONTROL: the ssc_byte bound was not found exactly once "
                  "(%d sites) - update bound_sites()" % len(sites))
            return 1
        at = sites[0]
        mut = bytearray(img)
        mut[at + 2:at + 4] = CONTROL_TICKS.to_bytes(2, "little")
        tmp = Path(PI.MAP).parent / "me711_ssc_bound_control.bin"
        tmp.write_bytes(bytes(mut))
        print("\nCONTROL: the bound at 0x%06X patched %d -> %d T7 ticks"
              % (at, BOUND_TICKS, CONTROL_TICKS))
        _, cgap = verdict(tmp)
        tmp.unlink()
        if cgap:
            print("CONTROL FAILED: a 6.4 ms byte bound added no more than "
                  "%.1f ms over a live SSC" % MARGIN_MS)
            return 1
        print("CONTROL: the long bound adds more than the margin - PASS")
    print("RESULT: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
