#!/usr/bin/env python3
r"""
me711_boot_cost_proof.py - how long the image takes to reach the first ASIC
exchange, measured, with a budget.

    py tests\firmware\build\me711_boot_cost_proof.py

WHY THIS GATE EXISTS.

Every hardware failure this project has chased on the ME7.1.1 has been the
S5500 supervision being starved. The runtime side of that is measured by
me711_ts_gap_proof.py. NOTHING measured the BOOT side - how much work the
firmware does before it first talks to the ASIC - and that is where a
regression hid:

    V27A   first ASIC exchange at step 1 270 901
    V29    first ASIC exchange at step 1 340 488     (+69 587, about 27 ms)

The cause was a 4096-byte DESIRED-image copy written straight into
hc_cfg_mgr_init(). It was correct, it was cheap-looking, and it pushed the
first exchange 27 ms later on every boot. Nothing named that quantity, so it
could only be inferred from whatever broke downstream.

A CORRECTION, AND IT IS THE POINT OF THIS PARAGRAPH. This gate was first
written believing that the same copy also caused six me711_boot_test failures
whose symptoms were "completed transfers are detected: start_rx=0" and
"reaches the 118-word runtime state: state=2". IT DID NOT. Raising the boot
test's step budget from 1.5M to 2.6M changed nothing, which killed that
theory. The real cause was in the LINKER: hc_asic_state had been allocated at
0xFCE2, which is DSTP0, so every PEC-driven SSC transfer overwrote the ASIC
state machine's state with the low byte of a buffer address. See
tests/firmware/build/near_ram_hazard_proof.py, which is the gate that actually catches it.

Two different defects with one shared symptom, and the plausible one was
wrong. That is why this gate measures its quantity DIRECTLY and reports the
number, instead of being satisfied that some downstream test went green.

WHAT THE BUDGET IS. The reference is V27A, the last image before the universal
configuration layer, measured in this same simulator. The allowance is
BUDGET_MS of extra pre-ASIC work. That is not a number pulled from the air: it
is roughly two S5500 rasters, so an image inside it cannot have moved the first
exchange by a whole supervision window.

WHAT IT MEASURES IS THE WORST CASE, AND THAT IS DELIBERATE. The simulator
starts with the external SRAM blank, so every run is a FIRST boot: the stored
page carries no universal-block magic, hc_cfg_mgr_init() has to migrate it, and
the ~170 seeded fields are paid for. On a real ECU that happens once, on the
first boot after flashing; every boot after it finds the magic and skips
straight past. So the number this gate prints is the most expensive boot the
image can have, which is the one worth guarding.

THIS IS A SIMULATOR MEASUREMENT and the step-to-millisecond ratio comes from
the firmware's own tick, not from a constant. It is a REGRESSION gate - it
answers "did this image get slower to start talking" - and it is not a claim
about absolute hardware timing.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import c167sim as S        # noqa: E402
import me711_image as PI   # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
BINS = ROOT / "bins/hanicore"

REFERENCE_STEM = "HaniCore_ME711_A1146_v27a_trigger_audit_fix"
BUDGET_MS = 20.0
# The append-only store scan's own bound - see the check that uses it. The
# measured value is ~470 ms and its size is fixed by the geometry, so this
# leaves room for noise and fails if the scan is ever made to do more.
NVM_SCAN_BUDGET_MS = 520.0

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<56s} {detail}")
    if not ok:
        FAILS += 1


def symbols(map_path):
    out = {}
    for m in re.finditer(r"^\s*([0-9A-F]{6})H\s+(\w+)",
                         map_path.read_text(errors="replace"), re.M):
        out.setdefault(m.group(2), int(m.group(1), 16))
    return out


def measure(img_path, map_path, limit=4_000_000):
    """(step of the first ASIC transfer, steps per firmware millisecond)."""
    sym = symbols(map_path)
    tx = sym.get("hc_asic_start_tx")
    tick = sym.get("hc_tick_ms")
    if tx is None or tick is None:
        raise SystemExit(f"{map_path.name}: no hc_asic_start_tx / hc_tick_ms")
    # THE STORE SCAN IS MEASURED SEPARATELY, and that is the point of these
    # two symbols. Boot stopped being one quantity at V39: the append-only
    # calibration store is scanned before the supervision link comes up -
    # sixteen cells, and a BLANK one has its whole 8188-byte body read,
    # because "usable as a target" means "completely erased" - which is over a
    # million instructions on its own. Summing that with the rest of boot and
    # comparing the total against a PRE-PERSISTENCE reference asks no
    # answerable question: V27A could not store a calibration at all. So the
    # span from entering hc_nvm_boot() to entering the call that follows it,
    # hc_cfg_mgr_init(), is taken out and reported on its own. Interrupts are
    # not enabled yet there, so the span is the scan and nothing else. An
    # image with no hc_nvm_boot reports 0, which is the truth about it.
    nvm_pc = sym.get("hc_nvm_boot")
    cfg_pc = sym.get("hc_cfg_mgr_init")
    mem = S.Mem(img_path.read_bytes())
    mem._cbank = bytearray(0x10000)
    # THE ENTRY SEGMENT IS DERIVED. It was the literal 0x8E, which V53's move
    # of the code sector to SA7 made wrong - and wrong in the quiet way: the
    # CPU would have started executing blank flash rather than ?C_STARTUP.
    # The ROMSYS header names the entry the boot block jumps through, and the
    # builder writes it, so it is the image's own answer rather than a literal.
    img = img_path.read_bytes()
    entry = ((img[0x8002] | (img[0x8003] << 8)) << 16) | (img[0x8000] | (img[0x8001] << 8))
    cpu = S.CPU(mem, (entry >> 16) & 0xFF, entry & 0xFFFF)
    tx &= 0xFFFF
    tick &= 0xFFFF
    first = None
    t_lo = t_hi = None
    nvm_in = nvm_out = None
    n = 0
    while n < limit:
        if nvm_pc is not None and nvm_out is None:
            pc = (cpu.csp << 16) | cpu.ip
            if nvm_in is None:
                if pc == nvm_pc:
                    nvm_in = n
            elif pc == cfg_pc:
                nvm_out = n
        cpu.step()
        n += 1
        if first is None and mem.r16(tx) > 0:
            first = n
        t = mem.r16(tick)
        if t_lo is None and t >= 10:
            t_lo = n
        if t_hi is None and t >= 110:
            t_hi = n
        if first is not None and t_hi is not None:
            break
    if first is None:
        raise SystemExit(f"{img_path.name}: no ASIC transfer within {limit} steps")
    # 100 firmware milliseconds of steady main loop is the ruler.
    per_ms = ((t_hi - t_lo) / 100.0) if (t_lo and t_hi) else None
    span = (nvm_out - nvm_in) if (nvm_in is not None and nvm_out is not None) else 0
    return first, per_ms, span


def main() -> int:
    print("=== HaniCore ME7.1.1 - boot cost to the first ASIC exchange ===\n")
    img, mp = PI.image(), PI.MAP
    print(f"  image     {img.name}")
    print(f"  sha256    {PI.sha256()}")

    ref_img = BINS / f"{REFERENCE_STEM}.bin"
    ref_map = BINS / f"{REFERENCE_STEM}.M66"
    if not (ref_img.exists() and ref_map.exists()):
        print(f"\n  reference {REFERENCE_STEM} is absent - cannot compare.")
        print("  This gate is a COMPARISON. Without the reference it has no")
        print("  opinion, and saying so is better than inventing a threshold.")
        return 0

    cur, per_ms, nvm_span = measure(img, mp)
    ref, ref_per_ms, _ = measure(ref_img, ref_map)
    ruler = per_ms or ref_per_ms
    print(f"  reference {REFERENCE_STEM}")
    print(f"  ruler     {ruler:.0f} simulator steps per firmware millisecond\n")

    nvm_ms = nvm_span / ruler if ruler else 0.0
    delta = (cur - nvm_span) - ref
    delta_ms = delta / ruler if ruler else 0.0
    print(f"  reference first ASIC exchange : step {ref}")
    print(f"  this image                    : step {cur}")
    print(f"  of which hc_nvm_boot()        : {nvm_span} steps "
          f"= {nvm_ms:.1f} ms")
    print(f"  the rest, vs the reference    : {delta:+d} steps "
          f"= {delta_ms:+.1f} ms\n")

    check("the image reaches its first ASIC exchange at all", cur > 0,
          f"step {cur}")
    check(f"boot OUTSIDE the store scan is within {BUDGET_MS:.0f} ms of the "
          f"reference", delta_ms <= BUDGET_MS,
          f"{delta_ms:+.1f} ms of a {BUDGET_MS:.0f} ms allowance")
    # AND THE STORE SCAN, ON ITS OWN TERMS AND WITH ITS OWN EVIDENCE.
    #
    # It is a deliberate cost of a fixed size: sixteen cells of 8188 bytes,
    # every blank one read to the end. It is also PHYSICALLY VALIDATED - V39
    # carries this exact scan, was flashed to the real ECU, booted, connected
    # and committed two calibrations (cells 0 and 1, generations 1 and 2,
    # BOOTSUM 0x00E303CF matching a full 1 MiB bootmode readback). So this
    # bound is not a guess about what the S5500 will tolerate before the link
    # is up; it is a REGRESSION guard that the scan has not grown past the
    # shape that actually ran on the part.
    check("and the append-only store scan has not grown past its measured "
          "shape", nvm_ms <= NVM_SCAN_BUDGET_MS,
          f"{nvm_ms:.1f} ms of a {NVM_SCAN_BUDGET_MS:.0f} ms bound")

    # A image that got FASTER is fine, but a huge negative jump usually means
    # the reference or the symbol resolution is wrong rather than that the
    # firmware improved by 50 ms.
    check("and the comparison looks sane, not like a broken measurement",
          delta_ms > -50.0, f"{delta_ms:+.1f} ms")

    print(f"\n{CHECKS - FAILS}/{CHECKS} checks pass")
    if FAILS:
        print("BOOT COST REGRESSED - something new runs before the ASIC does.\n"
              "Look for work added to hc_cfg_init(), hc_cfg_mgr_init(), or\n"
              "anything else on the path from reset to hc_asic_start_service().")
        return 1
    print("BOOT COST PROOF PASSES - the first ASIC exchange is not "
          "meaningfully later than the reference.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
