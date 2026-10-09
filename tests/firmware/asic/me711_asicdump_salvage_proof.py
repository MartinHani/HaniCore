#!/usr/bin/env python3
r"""
me711_asicdump_salvage_proof.py - execution-based proof of the four ordering/
provenance claims behind hc_asicdump_salvage(), against the REAL compiled
V12 image, not a description of it.

    py tests\firmware\asic\me711_asicdump_salvage_proof.py

WHAT THIS PROVES, each by actually running the compiled image from its real
reset entry point (?C_STARTUP, exactly as me711_v11_v12_equiv.py does) with
specific pre-conditions poked into memory before the first instruction, then
inspecting what the salvage record holds afterward:

  1. a PONR-SET boot (RAW=0x003C) never salvages, even when run_tx/run_rx
     already read 2/2 - the C167CR manual's power-on exception is honoured.
  2. a PONR-CLEAR boot (RAW=0x001C, the warm-reset value observed on every
     bench run so far) with run_tx==run_rx==2 DOES salvage.
  3. the salvaged payload is FRAME, read intact: 118 words poked with a
     distinctive pattern before boot come back byte-for-byte in the record.
  4. hc_asic_start_init() DOES go on to clear the live counters later in the
     same boot (proving the ordering risk is real) while the SALVAGED COPY,
     taken earlier, is untouched by that clear (proving the snapshot beat it).

A fifth scenario proves the build()-race close added on top of the approved
predicate: a boot that is otherwise identical to #2 but where FRAME[1..3]
still equal the last stashed TX prefix (tx_pre's fresh-image default, 0) is
REJECTED, exactly the "build() already ran for exchange #3" case the design
note in hcasicdump.c explains.

Addresses below come straight from build/hani_me711.M66 (the linker's
own symbol table) and hctarget.h, not from re-deriving offsets by hand.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import c167sim as S  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
V12 = ROOT / "bins/hanicore/HaniCore_ME711_A1146_salvage_v12.bin"
TGT = ROOT / "firmware/targets/me711/hctarget.h"
_t = TGT.read_text(errors="replace")


def _define(n):
    return int(re.search(r"#define\s+%s\s+(0x[0-9A-Fa-f]+|\d+)" % n,
                         _t).group(1), 0)


WORDS_START = _define("TGT_ASIC_WORDS_START")
WORDS_RUN = _define("TGT_ASIC_WORDS_RUN")
BAUD = _define("TGT_BAUD")
TPMS = int(re.search(r"#define\s+TGT_TICKS_PER_MS_X10\s+(\d+)", _t).group(1))

# --- ASC0 / SSC / PEC / ADC SFRs - same addresses me711_v11_v12_equiv.py
# uses, needed here for the SAME reason: without them cal_measure() and
# hcts_rx_learn() spin for well over a million steps waiting on hardware this
# bare harness never drives, and the ASIC startup handshake never completes
# at all - a bare, unhooked run gets stuck at RST_STAGE=5 (BOOT_CONFIG) by
# step 400,000 and is still stuck at RST_STAGE=7 (BOOT_PROBE) at step
# 3,000,000. Confirmed the hard way, by tracing RST_STAGE step by step before
# adding these.
S0RBUF, S0RIC, S0TBUF, S0TIC = 0x00FEB2, 0x00FF6E, 0x00FEB0, 0x00FF6C
SSCTIC, SSCRIC, SSCCON = 0x00FF72, 0x00FF74, 0x00FFB2
PECC0, PECC4 = 0x00FEC0, 0x00FEC8
ADCON, ADDAT = 0x00FFA0, 0x00FEA0
FRAMEA = 0xE100

RST_STAGE_ADDR = 0x380000 + 0x2400 + 6      # TGT_EXTRAM_BASE+TGT_RAM_RSTLOG+RST_STAGE
                                             # RST_STAGE(=6) is already a BYTE
                                             # offset (hcconfig.c: rst_u16()
                                             # takes off directly, no *2)
BOOT_ASIC_STAGE = 10

_PRISTINE = (S.Mem.r8, S.Mem.w8, S.Mem.w16)

# --- from build/hani_me711.M66 (PUBLIC symbol table) -----------------
HC_ASIC_RUN_TX = 0x00FA9C
HC_ASIC_RUN_RX = 0x00FA9E
HC_ASIC_RUN_OK = 0x00FAA8
HC_ASIC_STATE = 0x00FABE
HC_ASIC_ST_RUNTIME_TX = 6          # hcasicstart.h

# --- from hctarget.h --------------------------------------------------------
T0_SFR = 0xFE50                    # TIMERS["T0"][0] in c167sim, same register
TGT_RESET_PONR = 0x0020
FRAME = 0xE100
EXTRAM_BASE = 0x380000
RAM_ASICDUMP = 0x2A00
DUMP = EXTRAM_BASE + RAM_ASICDUMP

# --- from hcasicdump.c's own layout constants -------------------------------
G_SALV = 412
G_SALV_VALID, G_SALV_RUNTX, G_SALV_RUNRX = 0, 1, 2
G_SALV_RUNOK, G_SALV_STATE, G_SALV_RESETRAW, G_SALV_PAY = 3, 4, 5, 6

RAW_PONR_SET = 0x003C       # observed first-boot-of-session value
RAW_PONR_CLEAR = 0x001C     # observed on every warm reset on this bench

STEPS = 2_000_000           # me711_v11_v12_equiv.py runs 1.6M steps for
                             # SEVERAL full ASIC exchanges; reaching BOOT_ASIC
                             # here needs only cal_measure()/hc_cfg_init()/
                             # hcts_rx_learn() to finish, with no exchange
                             # required at all, so this is a generous budget.

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<62s} {detail}")


def _install_asic_model(mem, cpu):
    """The same modelled ASIC/ADC me711_v11_v12_equiv.py uses, so cal_
    measure()/hcts_rx_learn()/the startup handshake complete in thousands of
    steps instead of never. This proof does not care WHAT the model replies -
    only hc_asicdump_salvage()'s pre-seeded inputs matter - so unlike the
    equivalence tool this does not need to inspect the modelled traffic."""
    byte_ticks = int(10 * (TPMS / 10.0) * 1000 / BAUD)
    st = {"rxq": bytearray(), "tx_done": 0, "n": 0}
    S.Mem.r8, S.Mem.w8, S.Mem.w16 = _PRISTINE
    o8, ow8, ow16 = _PRISTINE

    def r8(s_, a, _o=o8):
        a &= 0xFFFFFF
        if a == S0RIC:
            return 0x80 if st["rxq"] else 0x00
        if a == S0TIC:
            t7 = cpu._sget(S.TIMERS["T7"][0])
            return 0x00 if ((st["tx_done"] - t7) & 0xFFFF) < byte_ticks else 0x80
        if a in (S0RIC + 1, S0TIC + 1, S0RBUF + 1):
            return 0x00
        if a == S0RBUF:
            return st["rxq"].pop(0) if st["rxq"] else 0
        return _o(s_, a)

    def w8(s_, a, v, _o=ow8):
        if (a & 0xFFFFFF) == S0TBUF:
            t7 = cpu._sget(S.TIMERS["T7"][0])
            st["tx_done"] = (t7 + byte_ticks) & 0xFFFF
            st["rxq"].append(v & 0xFF)
        return _o(s_, a, v)

    def w16(s_, a, v, _o=ow16):
        aa = a & 0xFFFFFF
        if aa == ADCON and (v & 0x80):
            s_.sfr[ADDAT] = ((v & 0x0F) << 12) | (100 + (v & 0x0F) * 37)
        if aa == SSCTIC and (v & 0x0080):
            n = s_.r16(PECC4) & 0x00FF or WORDS_START
            k = st["n"] = st["n"] + 1
            rx = [0] * n
            rx[0] = 0x7800 | (0x2E if n == WORDS_RUN else 0x1E)
            rx[1] = 0xA100 + k
            rx[2] = 0xB200 + k
            rx[3] = 0xC300 + k
            for i in range(4, n - 1):
                rx[i] = ((0x10 + k) << 8) | ((i * 7) & 0xFF)
            rx[n - 1] = sum(rx[:n - 1]) & 0xFFFF
            for i, w in enumerate(rx):
                _o(s_, FRAMEA + 2 * i, w)
            _o(s_, PECC0, s_.r16(PECC0) & 0xFF00)
            _o(s_, PECC4, s_.r16(PECC4) & 0xFF00)
            s_.sfr[SSCCON] = s_.r16(SSCCON) & ~0x1000
            s_.sfr[SSCTIC] = s_.r16(SSCTIC) | 0x0080
            s_.sfr[SSCRIC] = s_.r16(SSCRIC) | 0x0080
            cpu.irq_pending.add(SSCTIC)
            cpu.irq_pending.add(SSCRIC)
        return _o(s_, a, v)

    S.Mem.r8, S.Mem.w8, S.Mem.w16 = r8, w8, w16


def boot(pre, label="", max_steps=STEPS):
    """Load V12 fresh, install the modelled ASIC/ADC, apply `pre(mem)`, then
    run until RST_STAGE first reaches BOOT_ASIC(10) - the exact point in
    main() right after hc_asicdump_init()/hc_asicdump_salvage()/
    hc_power_hold_assert()/hc_asic_start_init() have ALL run and BEFORE the
    main loop gets a chance to attempt one single real exchange (stage(
    BOOT_ASIC) is the very next statement after hc_asic_start_init() in
    main()). That makes this the correct, unambiguous point to inspect both
    the salvage record and the live counters hc_asic_start_init() clears.

    CPU.__init__() unconditionally zeroes every TIMERS[] register, T0
    included, as its last step (modelling the bootblock's own timer state,
    not this firmware's). T0 is exactly the register `pre()` needs to seed
    (main()'s very first statement is `reset_raw = T0`), so the CPU MUST be
    constructed first and the seed applied after - seeding before is
    silently overwritten before the first instruction ever runs. Caught by
    this proof itself: an earlier version seeded before construction and
    every scenario read back as if RAW=0, not the intended value. """
    img = V12.read_bytes()
    off = img[0x8000] | (img[0x8001] << 8)
    seg = img[0x8002] | (img[0x8003] << 8)
    mem = S.Mem(img)
    cpu = S.CPU(mem, seg, off)
    _install_asic_model(mem, cpu)
    pre(mem)
    trapped = None
    steps_run = 0
    reached = False
    try:
        for _ in range(max_steps):
            cpu.step()
            steps_run += 1
            if rst_stage(mem) == BOOT_ASIC_STAGE:
                reached = True
                break
    except S.Trap as t:
        trapped = str(t)
    S.Mem.r8, S.Mem.w8, S.Mem.w16 = _PRISTINE
    if trapped:
        print(f"      [{label}] TRAPPED after {steps_run} steps: {trapped}")
    elif not reached:
        print(f"      [{label}] never reached BOOT_ASIC (RST_STAGE=10) in "
              f"{max_steps} steps - last RST_STAGE={rst_stage(mem)}")
    else:
        print(f"      [{label}] reached BOOT_ASIC after {steps_run} steps")
    return mem, cpu


def dump_word(mem, idx):
    return mem.r16(DUMP + 2 * idx)


def rst_stage(mem):
    """RST_STAGE is stored BIG-ENDIAN by two explicit byte stores in
       hcconfig.c (rst_set_u16), unlike the CPU's own little-endian word
       registers that Mem.r16() models - so it must be read byte-by-byte,
       not with r16()."""
    return (mem.r8(RST_STAGE_ADDR) << 8) | mem.r8(RST_STAGE_ADDR + 1)


def seed_common(mem, raw, run_tx=2, run_rx=2, run_ok=1,
                 state=HC_ASIC_ST_RUNTIME_TX, frame_pattern=None):
    mem.sfr[T0_SFR] = raw & 0xFFFF
    mem.w16(HC_ASIC_RUN_TX, run_tx)
    mem.w16(HC_ASIC_RUN_RX, run_rx)
    mem.w16(HC_ASIC_RUN_OK, run_ok)
    mem.w16(HC_ASIC_STATE, state)
    if frame_pattern is not None:
        for i in range(118):
            mem.w16(FRAME + 2 * i, frame_pattern(i))


def main():
    if not V12.exists():
        print(f"missing {V12} - run tools/build/build_hanicore_me711.py first")
        return 1

    print("=== 1. PONR SET never salvages, even with run_tx==run_rx==2 ===")
    mem, _ = boot(lambda m: seed_common(
        m, RAW_PONR_SET, frame_pattern=lambda i: 0x1000 + i), "scenario 1")
    check("PONR bit is actually set in the seeded RAW value",
          bool(RAW_PONR_SET & TGT_RESET_PONR), f"RAW=0x{RAW_PONR_SET:04X}")
    check("G_SALV_VALID stays 0 after a PONR-set boot",
          dump_word(mem, G_SALV + G_SALV_VALID) == 0,
          f"read {dump_word(mem, G_SALV + G_SALV_VALID)}")

    print()
    print("=== 2. PONR CLEAR + run_tx==run_rx==2 DOES salvage ===")
    pattern = lambda i: 0x9000 + i
    mem, _ = boot(lambda m: seed_common(m, RAW_PONR_CLEAR,
                                        frame_pattern=pattern), "scenario 2")
    valid = dump_word(mem, G_SALV + G_SALV_VALID)
    check("G_SALV_VALID becomes 1", valid == 1, f"read {valid}")
    check("G_SALV_RUNTX records the seeded 2",
          dump_word(mem, G_SALV + G_SALV_RUNTX) == 2)
    check("G_SALV_RUNRX records the seeded 2",
          dump_word(mem, G_SALV + G_SALV_RUNRX) == 2)
    check("G_SALV_RUNOK records the seeded 1",
          dump_word(mem, G_SALV + G_SALV_RUNOK) == 1)
    check("G_SALV_STATE records HC_ASIC_ST_RUNTIME_TX (6)",
          dump_word(mem, G_SALV + G_SALV_STATE) == HC_ASIC_ST_RUNTIME_TX)
    check("G_SALV_RESETRAW records the seeded RAW=0x001C",
          dump_word(mem, G_SALV + G_SALV_RESETRAW) == RAW_PONR_CLEAR)

    print()
    print("=== 3. the salvaged payload IS frame, read intact (118 words) ===")
    bad = [i for i in range(118)
           if dump_word(mem, G_SALV + G_SALV_PAY + i) != pattern(i)]
    check("all 118 payload words match the pre-boot FRAME pattern exactly",
          not bad, "byte-for-byte" if not bad else f"mismatch at {bad[:5]}")

    print()
    print("=== 4. hc_asic_start_init() clears the LIVE counters later in the")
    print("       same boot; the SALVAGED COPY, taken earlier, does not move ===")
    live_tx = mem.r16(HC_ASIC_RUN_TX)
    live_rx = mem.r16(HC_ASIC_RUN_RX)
    check("the LIVE hc_asic_run_tx is 0 by the end of this boot "
          "(proves hc_asic_start_init() really did clear it - the ordering "
          "risk hc_asicdump_salvage() exists to beat is real, not assumed)",
          live_tx == 0, f"live hc_asic_run_tx={live_tx}")
    check("the LIVE hc_asic_run_rx is 0 by the end of this boot",
          live_rx == 0, f"live hc_asic_run_rx={live_rx}")
    check("but the SALVAGED RUNTX/RUNRX still read the ORIGINAL 2/2 - the "
          "snapshot in DUMP[] was never touched by that later clear",
          dump_word(mem, G_SALV + G_SALV_RUNTX) == 2
          and dump_word(mem, G_SALV + G_SALV_RUNRX) == 2,
          f"DUMP still shows RUNTX={dump_word(mem, G_SALV + G_SALV_RUNTX)} "
          f"RUNRX={dump_word(mem, G_SALV + G_SALV_RUNRX)}")

    print()
    print("=== 5. bonus: the build()-race close rejects an AMBIGUOUS boot ===")
    print("    (FRAME[1..3] left at 0, matching tx_pre's fresh-image default -")
    print("     exactly what 'a build already ran for exchange #3' looks like)")
    mem2, _ = boot(lambda m: seed_common(m, RAW_PONR_CLEAR, frame_pattern=None), "scenario 5")
    v2 = dump_word(mem2, G_SALV + G_SALV_VALID)
    check("G_SALV_VALID stays 0 when FRAME[1..3] alias tx_pre's default",
          v2 == 0, f"read {v2} (FRAME left at its fresh-image zero default)")

    print()
    bad_names = [nm for nm, ok, _ in results if not ok]
    print(f"{len(results) - len(bad_names)}/{len(results)} checks pass")
    if bad_names:
        print("FAILED: " + "; ".join(bad_names))
        return 1
    print()
    print("PONR gates power-on correctly, a genuine warm-reset salvage carries")
    print("FRAME and the counters through intact, hc_asic_start_init()'s later")
    print("clear never reaches the copy, and the build()-race window is closed.")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
