#!/usr/bin/env python3
r"""
me711_ramprobe_proof.py - the probe that answers the flash writer's one
                          unverified precondition really does what it claims.

    py tests\firmware\persistence\me711_ramprobe_proof.py

WHY THIS EXISTS.

`hc_nvm_payload()` cannot run from flash: the AM29F800BB is a single-bank
device with no read-while-write, so while a sector erases every read of that
chip returns status bits - and HaniCore's code, its `const` tables, its
compiler helpers and its interrupt vectors are all in that chip. So the
programmer copies itself into the external SRAM at TGT_RAM_FLASHRT and runs
there.

**THAT HAS ONLY EVER BEEN PROVEN IN A SIMULATOR.** No HaniCore image has
fetched one instruction from 0x380000 on a real A1146 board, and if the board
cannot do it, the first discovery would be a half-erased calibration sector.

`hc_nvm_ramtest()` is the same act with nothing at stake - no flash access, no
pin, no calibration change - so it can be run on the bench BEFORE any erase.
This gate proves the probe is worth trusting when it says PASS.

WHAT IS PROVEN, and every one of these EXECUTES THE LINKED IMAGE:

  1. the routine FITS the fixed 1024-byte relocation and the declared region;
  2. sending '!M' really transfers control INTO the external SRAM - counted
     instruction fetches with the PC in segment 0x38, against a positive
     control of an ordinary boot, where that count must be ZERO;
  3. it RETURNS - execution is back in the flash code segment afterwards, and
     the firmware carries on answering TunerStudio;
  4. the answer is CORRECT against an INDEPENDENT Python model of the
     transform, computed here and not read out of the firmware;
  5. the answer DEPENDS ON THE SEED - two seeds, two different correct
     answers, so a constant cannot pass;
  6. NOT ONE FLASH ERASE OR PROGRAM happens - this is the property that makes
     it safe to run first;
  7. and the firmware's own verdict is HCNV_RP_PASS.

WHY IT CANNOT PASS VACUOUSLY - two mutations of the linked image, each of
which must change the verdict:

  A. corrupt the transform constant inside the routine. The firmware compares
     against its own copy of the transform, computed from flash, so it must
     report WRONG - and this gate's independent model must disagree too;
  B. NOP the CALLS that enters the SRAM. Nothing runs, the signature is never
     written, and the firmware must report NOSIG rather than PASS.

Every address below is DERIVED from hctarget.h, hcnvm.c and the linker map.
Nothing here is written down twice.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import binascii                           # noqa: E402
import c167sim as S                       # noqa: E402
import me711_image as PI
from me711_nvm_geometry import GEO                  # noqa: E402
import me711_heartbeat_gap_proof as HB    # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
TDIR = ROOT / "firmware/targets/me711"
TGT_H = TDIR / "hctarget.h"
NVM_C = TDIR / "nvm/hcnvm.c"

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    if not ok:
        FAILS += 1
    print("  [%s] %-62s %s" % ("PASS" if ok else "FAIL", name, detail))
    return ok


# ------------------------------------------------------------- derivation ---
def define(text, name):
    m = re.search(r"^#define\s+%s\s+\(?([^)\s/]+)" % re.escape(name),
                  text, re.M)
    if not m:
        raise SystemExit("%s is not defined - this gate cannot guess it" % name)
    return int(m.group(1).rstrip("uUlL"), 0)


def probe_addresses():
    """NVM_RP and its field offsets, out of the sources that define them."""
    tgt = TGT_H.read_text(errors="replace")
    nvm = NVM_C.read_text(errors="replace")
    extram = define(tgt, "TGT_EXTRAM_BASE")
    ram_nvm = define(tgt, "TGT_RAM_NVM")
    # NVM_RP is written as (NVM_CB + 64uL); take the addend rather than the sum
    m = re.search(r"#define\s+NVM_RP\s+\(NVM_CB\s*\+\s*(\d+)uL\)", nvm)
    if not m:
        raise SystemExit("NVM_RP is not (NVM_CB + N) any more - update me")
    base = extram + ram_nvm + int(m.group(1))
    return {
        "base": base,
        "state": base + define(nvm, "RP_STATE"),
        "runs": base + define(nvm, "RP_RUNS"),
        "seed": base + define(nvm, "RP_SEED"),
        "result": base + define(nvm, "RP_RESULT"),
        "sig": base + define(nvm, "RP_SIG"),
        "sigval": define(nvm, "RP_SIG_VALUE"),
    }


def map_symbol(name):
    """A function's linked address, from the map, by name."""
    txt = PI.MAP.read_text(errors="replace")
    m = re.search(r"^\s*([0-9A-F]{6})H\s+%s\b" % re.escape(name.upper()),
                  txt, re.M | re.I)
    if not m:
        raise SystemExit("%s is not in the linker map - a gate that cannot "
                         "name what it checks is checking something else"
                         % name)
    return int(m.group(1), 16)


# ---------------------------------------------------- the model, in Python --
def mix(seed):
    """The transform, written HERE and owing nothing to the firmware."""
    r = seed & 0xFFFF
    for _ in range(16):
        if r & 0x8000:
            r = ((r << 1) ^ 0x1021) & 0xFFFF
        else:
            r = (r << 1) & 0xFFFF
    return r


# ------------------------------------------------------------ the driving ---
envelope = HB.envelope      # one definition: 16-bit length (see HB)


def run_probe(img_bytes, seed_byte, steps=7_000_000, send=True):
    """Boot the image, optionally send '!M', and report what happened.

    Returns (sram_fetches, flash_after_sram, erases, programs, mem).
    """
    tmp = ROOT / "bins/hanicore/.ramprobe_under_test.bin"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(img_bytes)
    try:
        rig = HB.Rig(tmp, HB.ENTRY_CURRENT, HB.TICK_CURRENT, echo=False)
        if send:
            # After boot - see PI.BOOT_STEPS. At 750 000 steps the '!M'
            # arrived while hc_nvm_boot() was still scanning the
            # append-only store, and nine checks reported a probe that
            # had never run.
            rig.queue_rx(PI.BOOT_STEPS,
                         envelope(b"!M" + bytes([seed_byte])))
        cpu = rig.cpu
        sram = 0
        after = 0
        seen_sram = False
        try:
            for _ in range(steps):
                if rig._pending_rx and cpu.steps >= rig._pending_rx[0][0]:
                    rig.rxq.extend(rig._pending_rx.pop(0)[1])
                if cpu.csp == 0x38:
                    sram += 1
                    seen_sram = True
                elif seen_sram:
                    after += 1
                # the PEC6 wire receiver runs per step inside rig.run(); this
                # loop steps the CPU itself, so it must deliver the bytes too
                rig.wire_step()
                cpu.step()
        except S.Trap:
            pass
        return sram, after, rig.mem
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def r16(mem, addr):
    return (mem.r8(addr) << 8) | mem.r8(addr + 1)


# ------------------------------------------------------------------ main ----
def main() -> int:
    print("=== HaniCore Bosch ME7.1.1 - external-SRAM execution probe ===\n")
    img_path = PI.image()
    base = img_path.read_bytes()
    print("  image  %s" % img_path.name)

    RP = probe_addresses()
    tgt = TGT_H.read_text(errors="replace")
    rt_off = define(tgt, "TGT_RAM_FLASHRT")
    rt_lim = define(tgt, "TGT_RAM_FLASHRT_LIMIT")
    extram = define(tgt, "TGT_EXTRAM_BASE")
    rt_addr = extram + rt_off
    print("  probe block 0x%06X, relocation target 0x%06X\n"
          % (RP["base"], rt_addr))

    # ---- 1. it fits -------------------------------------------------------
    start = map_symbol("hc_nvm_ramprobe")
    end = map_symbol("hc_nvm_ramprobe_end")
    length = end - start
    check("the routine is a sane size and the marker follows it",
          0 < length < 1024, "%d bytes" % length)
    check("it fits the FIXED 1024-byte relocation the caller copies",
          length <= 1024, "%d <= 1024" % length)
    check("and it fits the declared TGT_RAM_FLASHRT region",
          length <= rt_lim, "%d <= %d" % (length, rt_lim))

    # ---- 2/3/4/6/7. it runs there, returns, and is right ------------------
    seed_a = 0x5A
    sram, after, mem = run_probe(base, seed_a)
    check("'!M' transfers control INTO the external SRAM",
          sram > 0, "%d instruction fetches with the PC in segment 0x38" % sram)
    check("and it RETURNS - the firmware carries on out of flash afterwards",
          after > 1000, "%d instructions executed after it came back" % after)

    got_seed = r16(mem, RP["seed"])
    got_res = r16(mem, RP["result"])
    got_sig = r16(mem, RP["sig"])
    state = mem.r8(RP["state"])
    check("the routine wrote its signature LAST, and it is there",
          got_sig == RP["sigval"],
          "0x%04X, want 0x%04X" % (got_sig, RP["sigval"]))
    check("the seed the run used carries the host's byte",
          (got_seed >> 8) == seed_a,
          "seed 0x%04X, host byte 0x%02X" % (got_seed, seed_a))
    check("THE ANSWER MATCHES AN INDEPENDENT MODEL OF THE TRANSFORM",
          got_res == mix(got_seed),
          "got 0x%04X, model 0x%04X, from seed 0x%04X"
          % (got_res, mix(got_seed), got_seed))
    check("and the firmware's own verdict is PASS",
          state == 2, "ramProbe state = %d" % state)
    check("NOT ONE FLASH ERASE OR PROGRAM - this is why it is safe first",
          not mem.fl_erases and mem.fl_programs == 0,
          "erases=%s programs=%d" % (mem.fl_erases, mem.fl_programs))

    # ---- POSITIVE CONTROL: the counter is not always non-zero -------------
    # The POSITIVE CONTROL: an ordinary boot that is never sent a probe must
    # fetch nothing from segment 0x38. It has to get past boot to mean
    # anything, so it gets the same budget the probe runs do.
    sram0, _after0, _m0 = run_probe(base, 0,
                                    steps=PI.BOOT_STEPS + 1_000_000,
                                    send=False)
    check("CONTROL - an ordinary boot fetches NOTHING from the SRAM",
          sram0 == 0, "%d fetches in segment 0x38 with no '!M' sent" % sram0)

    # ---- 5. the answer depends on the seed --------------------------------
    seed_b = 0xA5
    _s, _a, mem_b = run_probe(base, seed_b)
    res_b = r16(mem_b, RP["result"])
    seed_b_full = r16(mem_b, RP["seed"])
    check("a DIFFERENT seed gives a different answer, also correct",
          res_b == mix(seed_b_full) and res_b != got_res,
          "0x%04X vs 0x%04X" % (res_b, got_res))

    # ---- MUTATION A: corrupt the transform inside the routine -------------
    #
    # The 0x1021 the routine XORs with, located INSIDE the routine's own bytes
    # in the linked image. The firmware compares the result against its own
    # copy of the transform - which lives in flash and is not mutated - so it
    # must notice.
    # THE CODE SECTOR IS DERIVED, NOT 0x8E. This was `start - 0x8E0000 +
    # 0x0E0000`, a hand-written CPU-address-to-file-offset translation for
    # SA17; V53 moved the code to SA7 and it silently addressed the wrong
    # 64 KiB, so MUTATION B found "0 site(s)" and the gate failed a firmware
    # that was fine.
    off = start - GEO.code_base + (GEO.code_base - 0x800000)
    body = base[off:off + length]
    idx = body.find(bytes((0x21, 0x10)))          # 0x1021, little-endian
    check("MUTATION A - the transform constant is findable in the routine",
          idx >= 0, "at +%d" % idx if idx >= 0 else "not found")
    if idx >= 0:
        bad = bytearray(base)
        bad[off + idx] ^= 0xFF
        _s, _a, mem_m = run_probe(bytes(bad), seed_a)
        st = mem_m.r8(RP["state"])
        rs = r16(mem_m, RP["result"])
        check("MUTATION A - a corrupted routine is reported WRONG, not PASS",
              st == 3, "ramProbe state = %d" % st)
        check("MUTATION A - and this gate's own model disagrees with it too",
              rs != mix(r16(mem_m, RP["seed"])),
              "got 0x%04X, model 0x%04X"
              % (rs, mix(r16(mem_m, RP["seed"]))))

    # ---- MUTATION B: never enter the SRAM at all --------------------------
    #
    # CALLS #038H, #06000H is DA 38 00 60. NOP it out and the routine never
    # runs, so the signature is never written.
    #
    # EVERY OCCURRENCE, NOT THE FIRST ONE. Until V40 there was exactly one call
    # into TGT_RAM_FLASHRT and .find() was unambiguous. V40's resetless Burn
    # added a second: fl_enter() CALLS the same address to run the flash
    # writer, and being in hcnvm.c ahead of hc_nvm_ramprobe it links FIRST. So
    # this mutation was neutering the flash writer - which this gate never
    # invokes - and leaving the probe running, then reporting 133 fetches in
    # segment 0x38 and a PASS verdict as a failure of the FIRMWARE.
    #
    # A mutation that no longer hits what it names has stopped testing
    # anything, so it now removes EVERY path into the SRAM - which is what the
    # check claims, and is the stronger statement.
    callsite = bytes((0xDA, 0x38, (rt_off & 0xFF), (rt_off >> 8) & 0xFF))
    sites = []
    # THE SEARCH WINDOW IS DERIVED. It was 0x0E0200..0x0F0000, the SA17 code
    # sector, so after V53 moved the code to SA7+SA8 this mutation searched
    # blank flash, found "0 site(s)", and failed a firmware it never looked at.
    _clo = GEO.code_base - 0x800000 + 0x200     # past the parked vector table
    _chi = GEO.code_base - 0x800000 + GEO.code_size
    at = base.find(callsite, _clo, _chi)
    while at >= 0:
        sites.append(at)
        at = base.find(callsite, at + 4, _chi)
    check("MUTATION B - EVERY CALLS into the SRAM is findable in the image",
          len(sites) >= 1,
          "%d site(s): %s" % (len(sites),
                              " ".join("0x%06X" % s for s in sites)))
    if sites:
        bad = bytearray(base)
        for pos in sites:
            bad[pos:pos + 4] = b"\xCC\x00" * 2       # NOP NOP
        s2, _a2, mem_n = run_probe(bytes(bad), seed_a)
        st = mem_n.r8(RP["state"])
        check("MUTATION B - with the call gone nothing runs in the SRAM",
              s2 == 0, "%d fetches in segment 0x38" % s2)
        check("MUTATION B - and the firmware reports NOSIG, not PASS",
              st == 4, "ramProbe state = %d" % st)

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("RAM PROBE PROOF FAILED (%d check(s))" % FAILS)
        return 1
    print("RAM PROBE PROOF PASSES - the probe really executes from the")
    print("external SRAM, really returns, and its PASS means something.")
    print("IN SIMULATION. Whether THIS BOARD can do it is exactly what the")
    print("probe exists to find out, and that answer comes from the bench.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
