#!/usr/bin/env python3
r"""
me711_ts_gap_proof.py - prove that a REAL TunerStudio transaction cannot
starve the S5500 supervision raster on the Bosch ME7.1.1.

    py tests\firmware\comms\me711_ts_gap_proof.py

WHY THIS GATE EXISTS, in numbers rather than in prose.

hcts_tx() is baud-paced and BLOCKING: it writes S0TBUF and busy-waits for the
byte to leave, then waits again to swallow the K-line echo. At nominal 57600
8N1 one byte is about 174 us, so a reply costs roughly one third of the former
19200 timings. The exact window below comes from TGT_BAUD rather than prose:

    the bare signature reply           29 bytes  ->   15.1 ms
    the 208-byte output-channel block  215 bytes ->  112.0 ms
    a 256-byte calibration page read   263 bytes ->  137.0 ms

against a S5500 supervision raster of 10 ms that is serviced ONLY from the
main loop, by hc_asic_start_service(). Enabling TunerStudio on this board
without doing something about that would have reproduced the V15 defect
exactly - a ~127 ms blocking bench print starved the same state machine and
the ECU reset at ~140 ms every boot (the maintainer's design notes).

THE FIX UNDER TEST: hcts.c calls hcts_target_yield() from every bounded wait
it owns - the transmit wait, both echo waits, the CRC loop and hcts_stall().
On ME7.5 that hook is empty (its responder is on interrupts and a blocked main
loop costs it nothing). On this board it makes one tick-gated call into
hc_asic_start_service(), while the blocking reply owns the main loop. V26 also
anchors the next runtime deadline to the prior transfer's start timestamp;
using completion time silently adds transfer and polling latency to every
nominal 10 ms period.

THIS TOOL MEASURES THAT RATHER THAN ASSERTING IT. It drives the real linked
image in c167sim, feeds it genuine TunerStudio requests over the modelled
ASC0, and reports the worst observed gap between consecutive
hc_asic_start_service() entries across each transaction - including the
largest reply the server can be asked for.

A CONTROL IS INCLUDED AND IT MATTERS. The same transactions are replayed with
the yield hook suppressed (the call site is NOP'd in a scratch copy of the
image), which is what the firmware would do without the fix. If the control
does not blow the budget, this test is not measuring what it claims to and its
PASS means nothing - the same reasoning that made ts_rxgap_test.py run the
polled receiver as a control on the same image.
"""
from __future__ import annotations

import binascii
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_heartbeat_gap_proof as HB   # noqa: E402  the rig lives there
import me711_image as PI                 # noqa: E402
import c167sim as C167                   # noqa: E402  the shipped timebase default

ROOT = Path(__file__).resolve().parents[3]

BUDGET_MS = HB.BUDGET_MS
STEPS_PER_MS = HB.STEPS_PER_MS

# ============================================================================
# SIMULATED MILLISECONDS ARE NOT HARDWARE MILLISECONDS, AND THIS GATE USED TO
# CONFUSE THEM. Read this before touching a threshold below.
#
# c167sim advances every timer once per TWO simulated instructions
# (CPU.steps_per_tick = 2, and the simulator says in its own comment that this
# is "a modelling choice, not a hardware fact"). T7/T8 tick 1250 times per
# firmware millisecond, so the simulator executes about 2500 instructions per
# firmware millisecond - measured here at a median of 2521.
#
# The real part does far more than that in the same millisecond. fCPU is
# 40.000 MHz - TGT_FCPU_HZ, which this file READS rather than restates, and
# which hctarget.h establishes with five independent lines of evidence
# including two hardware measurements. (39.936 MHz appears in that header as
# the SUPERSEDED figure: it came from a baud derivation and a CAPCOM prescaler
# that were each wrong by a factor of two and cancelled. Do not cite it.)
# On the C166 core most instructions are one state time = two CPU clocks,
# which tools/analysis/me711_asic_cs_timing.py already uses as the project's conversion
# and correctly calls a FLOOR. Two clocks at 40 MHz is 50 ns, so the hardware
# executes roughly 20 000 instructions per millisecond.
#
#     hardware / simulator  =  19 900 / 2521  =  about 8x
#
# So a CPU-BOUND duration measured in simulated milliseconds overstates the
# hardware by about eight times. This gate used to compare exactly such a
# duration against the S5500's 10 ms raster, which is REAL time, and concluded
# that a 7 ms gap left only 3 ms of margin. The true figure was nearer 0.9 ms.
# That was a unit error, not a firmware problem.
#
# WHAT IS AND IS NOT AFFECTED:
#   - TIMER-DRIVEN quantities are unaffected. The runtime exchange cadence is
#     scheduled off T7/T8, so simulated milliseconds ARE milliseconds for it,
#     and the cadence checks below still read in ms.
#   - CPU-BOUND quantities - how long a stretch of code blocks the main loop -
#     must be measured in INSTRUCTIONS and converted with fCPU. That is what
#     the service-gap checks now do.
#
# The instruction count is the portable measurement. The conversion below is
# stated conservatively: CLOCKS_PER_INSTR is twice the architectural floor, to
# absorb taken branches, calls, and the external-SRAM wait states that
# BUSCON1 = 0x040D implies for the configuration layer's huge-pointer accesses.
# ============================================================================


def _fcpu_hz():
    """fCPU from hctarget.h, not from a number typed here."""
    h = (ROOT / "firmware/targets/me711/hctarget.h").read_text(errors="replace")
    import re as _re
    m = _re.search(r"#define\s+TGT_FCPU_HZ\s+(\d+)", h)
    if not m:
        raise SystemExit("TGT_FCPU_HZ not found in hctarget.h")
    return float(m.group(1))


FCPU_HZ = _fcpu_hz()
CLOCKS_PER_INSTR = 4.0       # 2 is the C166 floor; 4 is the conservative bound
US_PER_INSTR = (CLOCKS_PER_INSTR / FCPU_HZ) * 1e6


def _define_run_period():
    """TGT_ASIC_RUN_PERIOD_MS from hctarget.h - the nominal runtime raster."""
    h = (ROOT / "firmware/targets/me711/hctarget.h").read_text(errors="replace")
    import re as _re
    m = _re.search(r"#define\s+TGT_ASIC_RUN_PERIOD_MS\s+(\d+)", h)
    if not m:
        raise SystemExit("TGT_ASIC_RUN_PERIOD_MS not found in hctarget.h")
    return int(m.group(1))


def hw_ms(instructions):
    """Simulated instruction count -> milliseconds on the real part."""
    return instructions * US_PER_INSTR / 1000.0

# Let the platform reach its steady runtime exchange before asking anything of
# it: boot, banner, ASIC startup handshake, then runtime frames on the 10 ms
# raster. The V19 bench log puts LOOP well inside 200 ms.
SETTLE_MS = 300
# V38's ASIC live-start path performs its 96-word startup handshake before the
# first main-loop service.  The old 600k-step calibration window predated that
# path and ended during boot; `entries` was correctly empty, not a missing
# metric.  This explicit warmup is also used for each injected transaction.
#
# RAISED FOR V40, AND MEASURED RATHER THAN GUESSED. The first
# hc_asic_start_service entry of this image lands at simulator step 2461660:
# hc_nvm_boot()'s append-only scan reads all sixteen 8188-byte cells before the
# supervision link is brought up, which is 1.19M instructions on its own, and
# 1.5M steps ended inside it. That is not a regression - a CONTROL build with
# the two V40 yields removed reaches its first entry at step 2460017, 1643
# steps earlier - it is the V39 append-only geometry costing what it costs.
#
# The constant is a WARMUP, so making it too large only wastes simulator time,
# while making it too small silently ends during boot. 3.5M leaves ~37 service
# entries for the steps-per-ms fit and a full megastep of margin.
# ONE PLACE, and it is tools/lib/me711_image.py beside the stem - the same rule
# that keeps a gate from naming the image under test twice.
# AND THE WARMUP IS SCALED WITH IT, BECAUSE BOOT CONTAINS TIMED WAITS.
#
# PI.BOOT_STEPS is a MEASUREMENT - me711_boot_cost_proof owns it - but it was
# measured with c167sim's shipped timebase.  This gate runs the timers four
# times slower so that a simulated millisecond is a hardware millisecond, and
# every bounded wait in the boot path therefore costs four times as many
# instructions to expire.  Scaling by the same ratio keeps the warmup the same
# amount of FIRMWARE TIME it always was; the probe below still fails loudly if
# it nevertheless ended inside boot, so this is a derivation with a check
# behind it rather than a constant anybody has to trust.
BOOT_WARMUP_STEPS = (PI.BOOT_STEPS * HB.STEPS_PER_TICK
                     // C167.DEFAULT_STEPS_PER_TICK)
FAILS = 0


def check(name, ok, detail=""):
    global FAILS
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<56s} {detail}")
    if not ok:
        FAILS += 1


envelope = HB.envelope      # one definition: 16-bit length (see HB)


def och_request(off: int, cnt: int) -> bytes:
    return envelope(b"O" + off.to_bytes(2, "big") + cnt.to_bytes(2, "big"))


def page_request(off: int, cnt: int) -> bytes:
    return envelope(b"R" + off.to_bytes(2, "big") + cnt.to_bytes(2, "big"))


def transaction(name, rx, settle_steps, run_steps, nop_yield=False,
                img_path=None, map_path=None):
    """Run one transaction against the real image.

    Returns (worst service gap in whole SIMULATED ms, reply byte count,
    average runtime start cadence in ms, trap-or-None, worst service gap in
    INSTRUCTIONS).

    TWO DIFFERENT QUANTITIES COME BACK AND THEY ARE NOT INTERCHANGEABLE.

    The tick figure is the firmware's own hc_tick_ms, incremented by the T8
    interrupt. In the SIMULATOR that is an honest count of simulated
    milliseconds. It is the right unit for anything the TIMERS drive - the
    runtime exchange cadence, the raster - because those are scheduled off
    T7/T8 in both worlds.

    It is the WRONG unit for how long a stretch of code blocks the main loop,
    because c167sim gives the CPU only ~2500 instructions per simulated
    millisecond while the real part manages ~19 900. A CPU-bound gap expressed
    in simulated milliseconds is about eight times too large. That is why the
    instruction count is returned as well and why the service-gap checks use
    it. See the block at the top of this file.

    An earlier version of this file divided steps by a hardcoded 2500 steps/ms
    and was corrected to use tick_ms "so there is no ratio to get wrong". That
    removed one ratio and hid another: the ratio between simulated and real CPU
    throughput, which is 8 and which nothing was applying.

    The injection point is likewise expressed in STEPS and then translated
    into whatever tick_ms actually was at that moment, rather than assumed -
    the previous version filtered on `tick_ms >= 300` while the request was
    really delivered at tick ~230, so it discarded the entire reply and
    reported "0 bytes out".
    """
    mp = map_path if map_path is not None else PI.MAP
    src = img_path if img_path is not None else PI.image()
    img = _image_without_yield(src, mp) if nop_yield else src
    entry = _sym(mp, "hc_asic_start_service")
    tick = _sym(mp, "hc_tick_ms")
    run_tx = _sym(mp, "hc_asic_run_tx")
    rig = HB.Rig(img, entry, tick, echo=True, run_tx_addr=run_tx,
                 steps_per_tick=HB.STEPS_PER_TICK)
    rig.queue_rx(settle_steps, rx)
    rig.run(run_steps)

    if not rig.entries:
        return None, 0, None, rig.trap or "no supervision service ran"

    # What tick_ms was when the request went in - measured, not assumed.
    inj_tick = min(rig.entries, key=lambda e: abs(e[1] - settle_steps))[0]

    # Include the LAST service entry before injection. Filtering only entries
    # after injection drops the very gap the negative control is meant to
    # measure: in V21 the request arrived between two loop services, the first
    # post-injection entry was 139 ms later, and the old filter began there so
    # it reported only the later 6 ms steady-state gaps.
    before = [x for x in rig.entries if x[1] < settle_steps]
    after = [x for x in rig.entries if x[1] >= settle_steps]
    e = ([before[-1]] if before else []) + after
    gaps = [t1 - t0 for (t0, _), (t1, _) in zip(e, e[1:])]
    worst = max(gaps) if gaps else 0
    # THE PORTABLE MEASUREMENT. The step delta between two service entries is
    # the number of instructions the CPU executed without servicing the ASIC.
    # That number means the same thing in the simulator and on the part; the
    # simulated millisecond does not. See the block at the top of this file.
    instr_gaps = [s1 - s0 for (_, s0), (_, s1) in zip(e, e[1:])]
    worst_instr = max(instr_gaps) if instr_gaps else 0
    ntx = len([1 for t, _ in rig.tx if t >= inj_tick])
    reply_end = max((s for s in rig.tx_steps if s >= settle_steps),
                    default=settle_steps)
    # A tick_ms delta is quantised: two starts exactly 10.0 ms apart can read
    # as 11 ticks when the sampling instructions straddle tick boundaries.
    # Calibrate simulator steps from the firmware's own tick over this run,
    # then measure start-to-start in steps. This is the same correction the
    # service-gap proof above already makes for its transaction window.
    dtick = (rig.entries[-1][0] - rig.entries[0][0]) & 0xFFFF
    steps_per_ms = ((rig.entries[-1][1] - rig.entries[0][1]) / dtick
                    if dtick else 1.0)
    # A short/fast reply can end before a second runtime-start observation.
    # The run window deliberately includes 300 ms of post-reply margin, so use
    # at least 100 ms of that steady-state span for the cadence measurement.
    cadence_end = max(reply_end, settle_steps + int(100 * steps_per_ms))
    starts = [(t, s) for t, s, _ in rig.run_tx_events
              if settle_steps <= s <= cadence_end]
    cadence_steps = [b[1] - a[1] for a, b in zip(starts, starts[1:])]
    cadence = ((sum(cadence_steps) / len(cadence_steps)) / steps_per_ms
               if cadence_steps else None)
    return worst, ntx, cadence, rig.trap, worst_instr


def _sym(map_path, name):
    import re
    text = map_path.read_text(errors="replace")
    m = re.search(r"^\s*([0-9A-F]{6})H\s+%s\s" % re.escape(name),
                  text, re.M)
    if not m:
        raise SystemExit(f"{name} not in {map_path.name}")
    return int(m.group(1), 16)


_NOYIELD = {}


def _image_without_yield(src=None, mp=None):
    """A scratch copy of an image with the CALL to hcts_target_yield() inside
    hcts_tx()'s transmit wait replaced by NOPs - the control condition.

    Located by pattern rather than by address so it survives a re-link: the
    yield is a far call (CALLS) to the linked hcts_target_yield.
    """
    src = Path(src) if src is not None else PI.image()
    mp = mp if mp is not None else PI.MAP
    if src in _NOYIELD:
        return _NOYIELD[src]
    data = bytearray(src.read_bytes())
    off = _sym(mp, "hcts_target_yield") & 0xFFFF
    # Keil SMALL compiles this as a NEAR call, because hcts.c and
    # hcmain_me711.c both link into segment 0x8E:
    #     CALLA cc_UC, addr  =  CA 00 <lo> <hi>
    # (verified against the linked image - the function itself ends in
    # RET = CB 00, not RETS, which is the same evidence.) All linked call sites
    # are patched rather than trusting a stale hardcoded count.
    pat = bytes((0xCA, 0x00, off & 0xFF, (off >> 8) & 0xFF))
    n = 0
    start = 0
    while True:
        i = data.find(pat, start)
        if i < 0:
            break
        data[i:i + 4] = b"\xCC\x00" * 2          # NOP NOP
        n += 1
        start = i + 4
    if n == 0:
        raise SystemExit("control: no CALLS to hcts_target_yield found - "
                         "the hook is not linked, so this proof is vacuous")
    p = ROOT / f"bins/hanicore/_scratch_{src.stem}_{len(_NOYIELD)}_noyield.bin"
    p.write_bytes(bytes(data))
    print(f"  (control image {src.name}: {n} CALLS to hcts_target_yield NOP'd)")
    _NOYIELD[src] = p
    return p


def main() -> int:
    print("=== HaniCore Bosch ME7.1.1 - TunerStudio service-gap proof ===\n")
    print(f"  image  {PI.image().name}")
    print(f"  sha256 {PI.sha256()}")
    print(f"  budget {BUDGET_MS:.0f} ms (the S5500 runtime raster)\n")

    och_size = int(PI.metadata()["och_size"])
    page = 256

    # Measured on this image rather than assumed: ~3264 simulator steps per
    # firmware millisecond. Sizing the window off the wrong constant is what
    # truncated every transaction in the first version of this file.
    probe = HB.Rig(PI.image(), HB.ENTRY_CURRENT, HB.TICK_CURRENT, echo=True,
                   steps_per_tick=HB.STEPS_PER_TICK)
    probe.run(BOOT_WARMUP_STEPS)
    if len(probe.entries) < 2:
        raise SystemExit("REGRESSION: V38 warmup reached no usable "
                         "hc_asic_start_service entries; transaction gap "
                         "measurement would be vacuous")
    first, last = probe.entries[0], probe.entries[-1]
    dtick = (last[0] - first[0]) & 0xFFFF
    if dtick == 0:
        raise SystemExit("REGRESSION: service entries did not advance hc_tick_ms")
    steps_per_ms = (last[1] - first[1]) / dtick
    print(f"  measured {steps_per_ms:.0f} simulator steps per firmware ms")

    def steps(ms):
        return int(ms * steps_per_ms)

    SETTLE = BOOT_WARMUP_STEPS + steps(SETTLE_MS)

    def window(nbytes):
        """Long enough for the settle, the request, the whole reply on the
        wire at the target baud, and a margin."""
        return SETTLE + steps(nbytes * (10_000.0 / HB.BAUD) + 300)

    # One-word-per-window V48 takes about 7.5 s in this instruction-paced
    # model.  This is a completion allowance; the service-gap measurement
    # below remains the maximum distance between consecutive raster entries.
    BURN_RUN_MS = 9000

    # EVERY COMMAND THE .INI CAN SEND, and that is the point of the last two.
    #
    # On 2026-09-04 V35 was flashed, TunerStudio read the whole page, and then
    # a Burn came back with a truncated CRC - `D2 00 00 00` where `D2 02 EF 8D`
    # was calculated - followed by a page read that timed out with nothing at
    # all. The ECU had not answered badly; it had gone away. The Burn handler
    # was blocking the main loop for 257 ms against this 10 ms raster and the
    # monitoring module reset the CPU in the middle of the reply.
    #
    # THIS FILE HAD NEVER SENT A 'B'. It measured 'S', 'V', 'O' and 'R' - the
    # cheap commands - and called the transport safe. The most expensive
    # command in the firmware was the one nobody measured.
    #
    # 'W' is here for the same reason: it is the other command a tuner sends
    # thousands of times, and it too reaches the configuration manager.
    cases = [
        # 2026-10-14: an ENVELOPE 'S'. A plain byte is answered only on a
        # link a CRC-valid request has locked (shared-bus discipline,
        # the maintainer's design notes.1).
        ("signature 'S'", envelope(b"S"), window(48)),
        ("envelope version 'V'", envelope(b"V"), window(48)),
        ("output channels, WHOLE block", och_request(0, och_size),
         window(och_size + 7)),
        ("calibration page read, 256 B", page_request(0, page),
         window(page + 7)),
        ("calibration page WRITE, one byte",
         envelope(b"W" + (2427).to_bytes(2, "big") + bytes([0x40])),
         window(40)),
        # V40's Burn is not a request with a reply 400 ms later - it is a
        # request whose reply waits for the WHOLE append-only commit: staging,
        # 2060 programmed words in bounded RAM-resident chunks, the DONE
        # readback, a rescan and the live source reselect. The window has to
        # cover all of it or the measurement stops mid-commit and reports a
        # missing reply as a firmware fault.
        ("BURN - the whole record, staged and COMMITTED", envelope(b"B"),
         window(40) + steps(BURN_RUN_MS)),
    ]
    # V40 returns Burn's acknowledgement only after DONE is visible and then
    # keeps executing. A successful Burn must therefore be as trap-free as
    # every ordinary TunerStudio transaction.
    EXPECT_TRAP = set()

    print(f"  conversion  fCPU {FCPU_HZ/1e6:.3f} MHz, "
          f"{CLOCKS_PER_INSTR:.0f} clocks/instruction (2 is the floor)"
          f"  ->  {1000.0/US_PER_INSTR:.0f} instructions per hardware ms")
    print("  --- with the yield hook (the shipped firmware) ---")
    live = {}
    for name, rx, run_steps in cases:
        worst, ntx, cadence, trap, winstr = transaction(
            name, rx, SETTLE, run_steps)
        live[name] = winstr
        ok = ((trap is None or (name in EXPECT_TRAP and "SRST" in str(trap)))
              and winstr is not None
              and hw_ms(winstr) < BUDGET_MS and ntx > 0)
        check(name, ok,
              f"{winstr:6d} instr = {hw_ms(winstr):.2f} ms hw, "
              f"{ntx:4d} bytes out"
              + (f", cadence {cadence:.2f} ms" if cadence is not None else "")
              + (f", TRAP {trap}" if trap else ""))

    # 2026-10-14: THE EXCHANGE NO LONGER DEPENDS ON THE YIELD HOOK. It runs at
    # its own interrupt level (CC27, requested by the 1 ms tick) - so the
    # property under test is now that THIS image holds the budget even with
    # every hook call NOP'd, and the control that proves the measurement can
    # see starvation is the last image that still needed the hook (12B46583,
    # the 2026-10-13 car image), run the same way: it must blow the budget.
    print("\n  --- THIS IMAGE with the yield hook NOP'd (must still hold) ---")
    held = 0
    for name, rx, run_steps in cases:
        worst, ntx, cadence, trap, winstr = transaction(name, rx, SETTLE,
                                                        run_steps,
                                                        nop_yield=True)
        ok_ = winstr is not None and hw_ms(winstr) < BUDGET_MS
        held += 1 if ok_ else 0
        print(f"         {name:<40s} {winstr if winstr is not None else -1:7d} instr  "
              f"{'' if ok_ else '<-- OVER BUDGET'}")
    check("the exchange holds without the serial yield (interrupt level)",
          held == len(cases),
          f"{held} of {len(cases)} transactions inside {BUDGET_MS:.0f} ms")

    ctl = ROOT.parent / "evidence/CAR_20261011_REVIEW/image_12B46583/HaniCore_ME711_v102_dev.bin"
    if ctl.exists():
        print("\n  --- CONTROL: 12B46583 (exchange in the main loop), hook NOP'd ---")
        blown = 0
        for name, rx, run_steps in cases:
            worst, ntx, cadence, trap, winstr = transaction(
                name, rx, SETTLE, run_steps, nop_yield=True,
                img_path=ctl, map_path=ctl.with_suffix(".M66"))
            over = winstr is not None and hw_ms(winstr) >= BUDGET_MS
            blown += 1 if over else 0
            print(f"         {name:<40s} {winstr if winstr is not None else -1:7d} instr  "
                  f"{'<-- OVER BUDGET' if over else ''}")
        check("the control (a main-loop exchange without the hook) blows the budget",
              blown > 0, f"{blown} of {len(cases)} transactions exceed "
              f"{BUDGET_MS:.0f} ms of HARDWARE time")
    else:
        print("  (control image 12B46583 absent - the control is not run)")

    worst_live = max(v for v in live.values() if v is not None)
    # THE BURN IS A DIFFERENT CLASS OF TRANSACTION AND IT IS SEPARATED HERE.
    # Every absolute bound below still applies to it - it is part of
    # worst_live - but the RELATIVE bound further down compares against a
    # plain 'S' on the V27A image, which had no persistence at all. Holding a
    # flash commit to "no more than 2x an image that could not commit" is not
    # a regression test, it is a category error, so the commit gets its own
    # stated multiple instead of being quietly folded in or quietly dropped.
    BURN_CASE = "BURN - the whole record, staged and COMMITTED"
    worst_ordinary = max(v for k, v in live.items()
                         if v is not None and k != BURN_CASE)
    worst_burn = live.get(BURN_CASE)
    worst_ms = hw_ms(worst_live)
    print("")
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # THE BURN REPLY, BYTE FOR BYTE, WITH NO RESET AFTER IT.
    #
    # This is the direct regression test for what the bench saw on
    # 2026-09-04: TunerStudio reported the Burn response CRC as
    # `D2 00 00 00` where it had calculated `D2 02 EF 8D`. That value is
    # crc32 of the single OK byte - so the payload TunerStudio expected was
    # right, and the ECU got the first CRC byte out and then stopped. It had
    # been reset in the middle of its own reply.
    #
    # So: the reply must be a COMPLETE, CRC-valid envelope after the real
    # commit work, and the continuous simulator session must not trap.
    burn_rig = HB.Rig(PI.image(), HB.ENTRY_CURRENT, HB.TICK_CURRENT,
                      steps_per_tick=HB.STEPS_PER_TICK,
                      echo=False)
    burn_rig.queue_rx(SETTLE, envelope(bytes([0x42])))
    # Long enough for the WHOLE commit, not just the request. A V40 Burn is
    # staging, 2060 programmed words, the DONE readback, a rescan and the live
    # source reselect.  V48's independently admitted one-word windows take
    # about 7.5 s in this simulator, so share the same explicit completion
    # allowance as the transaction census above.
    burn_rig.run(SETTLE + steps(BURN_RUN_MS))
    btx = bytes(b for _t, b in burn_rig.tx)
    ok_payload = bytes([0x00])
    want = (bytes([0x00, 0x01]) + ok_payload
            + (binascii.crc32(ok_payload) & 0xFFFFFFFF).to_bytes(4, "big"))
    # The boot path writes a few bytes of its own before any request arrives,
    # so the envelope is LOCATED in the stream rather than assumed to start it.
    at = btx.find(want)
    check("the Burn reply is the complete 7-byte envelope, CRC and all",
          at >= 0,
          ("found at byte %d of %d" % (at, len(btx))) if at >= 0
          else "stream %s does not contain %s"
               % (btx.hex(" ").upper(), want.hex(" ").upper()))
    check("and it leaves the CPU running after the completed commit",
          at >= 0 and (at + len(want)) <= len(btx)
          and burn_rig.trap is None,
          "%d bytes out, envelope ends at %d, trap=%s"
          % (len(btx), at + len(want) if at >= 0 else -1, burn_rig.trap))

    print(f"  worst service gap across every transaction: "
          f"{worst_live} instructions = {worst_ms:.2f} ms on the part")
    print("")

    check("worst gap across EVERY transaction is inside the raster",
          worst_ms < BUDGET_MS,
          f"{worst_ms:.2f} ms < {BUDGET_MS:.0f} ms")
    check("and it keeps at least half the raster in reserve",
          worst_ms <= BUDGET_MS / 2.0,
          f"{BUDGET_MS - worst_ms:.2f} ms spare")
    check("even at the pessimistic 6 clocks per instruction",
          worst_live * (6.0 / FCPU_HZ) * 1e3 < BUDGET_MS,
          f"{worst_live * (6.0 / FCPU_HZ) * 1e3:.2f} ms < {BUDGET_MS:.0f} ms")

    # A RELATIVE BOUND AS WELL AS AN ABSOLUTE ONE.
    #
    # The absolute check above has a lot of headroom, and headroom hides
    # drift: the configuration layer could double the work between services
    # and still pass. So the same measurement is also compared against the
    # last image before that layer existed. This is the check that would have
    # caught the V29 growth on its own terms - as "this image does 75 % more
    # work between supervision services than V27A", which is a fact worth
    # knowing even when the absolute margin is fine.
    ref = ROOT / "bins/hanicore/HaniCore_ME711_A1146_v27a_trigger_audit_fix"
    if ref.with_suffix(".bin").exists() and ref.with_suffix(".M66").exists():
        _w, _n, _c, _t, ref_instr = transaction(
            "V27A reference", b"S", SETTLE, window(40),
            img_path=ref.with_suffix(".bin"), map_path=ref.with_suffix(".M66"))
        ratio = worst_ordinary / ref_instr if ref_instr else 0.0
        check("ordinary transactions: no more than 2x the pre-config-layer "
              "reference",
              ratio <= 2.0,
              f"{worst_ordinary} vs {ref_instr} instructions = {ratio:.2f}x")
        # AND THE COMMIT, ON ITS OWN TERMS. It is allowed to cost more than a
        # signature request - it stages 4096 bytes, validates them, programs
        # 2060 words through a RAM-resident writer, reads the DONE marker back
        # and rescans the store - but not unboundedly more, and it still has
        # to leave half the raster free. Five times the reference is 5x8785 =
        # ~44k instructions = 4.4 ms; the measured commit is well under that
        # and a doubling of commit work would fail here before it failed the
        # absolute bound.
        if worst_burn is not None:
            bratio = worst_burn / ref_instr if ref_instr else 0.0
            check("the flash COMMIT: no more than 5x that reference",
                  bratio <= 5.0,
                  f"{worst_burn} vs {ref_instr} instructions = {bratio:.2f}x")
    else:
        print("  (V27A reference absent - the relative bound is not checked)")

    # Regression control for the physical defect fixed here. V25 is immutable
    # and schedules the next runtime deadline from completion, adding transfer
    # and polling latency to every nominal period. The current image anchors
    # that deadline to the prior start and must remove the cumulative slip.
    v25 = ROOT / "bins/hanicore/HaniCore_ME711_A1146_mainrelay_v25.bin"
    v25_map = ROOT / "bins/hanicore/HaniCore_ME711_A1146_mainrelay_v25.M66"
    if v25.exists() and v25_map.exists():
        old_worst, old_ntx, old_cadence, old_trap, _oi = transaction(
            "V25 cadence control", page_request(0, page), SETTLE,
            window(page + 7), img_path=v25, map_path=v25_map)
        _, _, new_cadence, _, _ = transaction(
            "current cadence", page_request(0, page), SETTLE,
            window(page + 7))
        # A cadence of None means the run window held fewer than two runtime
        # starts, so there was nothing to average. That is a MEASUREMENT that
        # did not happen, not a slip of 0 ms - and formatting it eagerly with
        # ":.2f" crashed the whole gate with a TypeError instead of failing
        # the one check, which is how a green suite turns into a traceback.
        def ms(v):
            return "not measured" if v is None else "%.2f ms" % v

        # ANCHORED TO THE FIRMWARE'S NOMINAL PERIOD, NOT TO TWO CALIBRATED
        # NUMBERS.
        #
        # These two checks used to read "V25 cadence > 10.5 ms" and "the
        # current image removes >= 0.5 ms of slip". Both constants were
        # calibrated against c167sim's shipped timebase, and correcting that
        # timebase moved them: V25 now measures 10.43 ms and the removed slip
        # 0.45 ms, so both tripped while the property they stand for still
        # held perfectly.
        #
        # THE MAGNITUDE OF THE MODELLED SLIP IS NOT PHYSICAL AND NEVER WAS.
        # On the part the slip is a real SSC frame - 118 words at the
        # corrected 1 MHz is 1.888 ms, and V25's physical telemetry showed
        # ~11.9 ms per runtime start against a 10 ms nominal. The simulator
        # completes an SSC transfer on an instruction count instead of a shift
        # rate, so it reproduces neither 1.9 ms nor any timebase-independent
        # figure. What IS invariant, and what this control exists to prove, is
        # the DIRECTION: V25 anchors the next deadline to completion and
        # therefore runs LONG, while the current image anchors it to the prior
        # start and therefore runs AT nominal.
        #
        # So both are now stated against TGT_ASIC_RUN_PERIOD_MS. They are not
        # looser - the current image must land within 0.15 ms of nominal,
        # which is tighter than "0.5 ms better than V25" ever was, and it is
        # the half that would actually regress if the anchor moved back.
        nominal = float(_define_run_period())
        check("V25 control reproduces completion-relative cadence",
              old_trap is None and old_ntx == page + 7
              and old_cadence is not None
              and old_cadence >= nominal + 0.25,
              "V25 %s vs %0.2f ms nominal" % (ms(old_cadence), nominal))
        check("the current image holds the nominal runtime period",
              new_cadence is not None
              and abs(new_cadence - nominal) <= 0.15,
              "current %s vs %0.2f ms nominal" % (ms(new_cadence), nominal))
        check("and it is measurably tighter than the completion-anchored V25",
              old_cadence is not None and new_cadence is not None
              and old_cadence - new_cadence >= 0.25,
              "removed %s of slip"
              % ("not measured" if old_cadence is None or new_cadence is None
                 else "%.2f ms" % (old_cadence - new_cadence)))

    print()
    if FAILS:
        print(f"TS GAP PROOF FAILED ({FAILS} check(s))")
        return 1
    print("TS GAP PROOF PASSES - TunerStudio cannot starve the S5500 raster.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
