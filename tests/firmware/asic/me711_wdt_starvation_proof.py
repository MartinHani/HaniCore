#!/usr/bin/env python3
r"""THE ON-CHIP WATCHDOG IS A 200 ms DEADLINE, AND NOTHING IN THIS TREE MEASURED IT.

V51 was flashed on 2026-09-12 and its live Burn COMMITTED - 2060 of 2060 words,
zero retries, zero writer failures, the record complete in cell 0 ending in
DONE, nothing else in the 1 MiB touched, and after the reboot the ECU selected
that record with idlePad = 0x02 live and nvmSource = NONVOL.  And the ECU reset
once, with

    rstRawReset = 0x0006  =  SWR | WDTR

which C167CR UM V3.1 Table 13-2 names unambiguously: **Watchdog Timer Reset**.
Not an NMI (LF_NMI_STARTED = 0), not a trap (rstPreviousTrap = 0,
rstCurrentTrap = 0), not the S5500.  The C167's own watchdog timer overflowed.

WHY NO GATE SAW IT.  `c167sim` COUNTS SRVWDT instructions and models nothing
else about the watchdog - no counter, no reload, no overflow, no reset.  So
me711_burn_two_in_session_proof ran two complete Burns and passed 39/39 while the
hardware reset on the first one.  This gate closes that blind spot by
MEASURING the deadline instead of modelling the peripheral.

THE DEADLINE, derived not assumed:
    WDTCON = TGT_WDTCON_SERVICE = 0x0B01  ->  WDTIN = 1, WDTREL = 0x0B
    prescaler  2^(1 + 6*WDTIN) = 128                      [UM 13.1]
    after SRVWDT the counter starts at WDTREL << 8 = 0x0B00 = 2816
    overflow at 65536, so 62720 counts of TGT_FCPU_HZ / 128
    = 62720 * 128 / 40e6 = 200.7 ms

WHAT IS MEASURED: the longest interval between two consecutive SRVWDT
executions across a complete live Burn, in simulated milliseconds, plus the
program counters that consumed the worst one.  A gap at or beyond the period is
a reset on hardware.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_heartbeat_gap_proof as HB     # noqa: E402
import me711_image as PI                   # noqa: E402
import me711_ts_gap_proof as GAP           # noqa: E402
# THE WIRE FORMAT HAS ONE DEFINITION, AND IT IS NOT IN THIS FILE.
# The first version of this gate framed requests itself and called a
# transaction "replied" as soon as rig.tx grew - which the K-line ECHO does
# immediately. Both transactions reported "replied after 0 ms", the Burn never
# ran, and the gate printed PASS on a 0.4 ms worst gap it had measured over
# nothing at all. Reusing the session proof's envelope() and find_reply() makes
# that impossible: a reply is a CRC-valid envelope whose payload matches.
import me711_burn_two_in_session_proof as SP        # noqa: E402

ME = ROOT / "firmware/targets/me711"

SRVWDT_OP = 0xA7
IDLEPAD = 2427

# A tenth of the watchdog period. See the long note at the verdict.
WDT_MARGIN = 0.10


def image_symbols(img):
    """hc_asic_start_service and hc_tick_ms FROM THE MAP BESIDE THIS IMAGE.

    me711_heartbeat_gap_proof resolves ENTRY_CURRENT/TICK_CURRENT at import
    time from whatever the CURRENT build's map says.  Driving a different image
    with those addresses is the "a gate must name the image under test ONCE"
    defect in miniature - V51 and V52 do not share a code layout (hc_srvwdt
    alone moved from 0x8E7B50 to 0x8E7B54), so the warmup would look for the
    ASIC service entry at an address that is not it, find no entries, and every
    figure afterwards would be vacuous.  So both symbols come from the .M66
    that sits beside the image actually being measured.
    """
    m66 = Path(img).with_suffix(".M66")
    if not m66.exists():
        raise SystemExit("no .M66 beside %s - refusing to borrow another "
                         "image's symbol addresses" % img)
    txt = m66.read_text(errors="replace")
    out = {}
    for name in ("hc_asic_start_service", "hc_tick_ms"):
        m = re.search(r"^\s*([0-9A-F]{6})H\s+" + re.escape(name) + r"\s",
                      txt, re.M)
        if not m:
            raise SystemExit("%s not in %s" % (name, m66.name))
        out[name] = int(m.group(1), 16)
    return out["hc_asic_start_service"], out["hc_tick_ms"]


def wdt_period_ms():
    """Derived from hctarget.h and the manual, never typed."""
    tgt = (ME / "hctarget.h").read_text(errors="replace")
    import re
    m = re.search(r"#define\s+TGT_WDTCON_SERVICE\s+0x([0-9A-Fa-f]+)u", tgt)
    if not m:
        raise SystemExit("TGT_WDTCON_SERVICE not found in hctarget.h")
    wdtcon = int(m.group(1), 16)
    m = re.search(r"#define\s+TGT_FCPU_HZ\s+(\d+)", tgt)
    if not m:
        m = re.search(r"TGT_FCPU_HZ\s+\(?\s*(\d+)", tgt)
    fcpu = int(m.group(1)) if m else 40_000_000
    wdtin = wdtcon & 1
    wdtrel = (wdtcon >> 8) & 0xFF
    presc = 1 << (1 + 6 * wdtin)
    counts = 0x10000 - (wdtrel << 8)
    return wdtcon, fcpu, presc, counts, counts * presc / fcpu * 1000.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", type=Path, default=None,
                    help="measure this image instead of the current build, so "
                         "the same gate gives a BEFORE and an AFTER")
    ap.add_argument("--slice-ms", type=int, default=1)
    ap.add_argument("--burn-limit-ms", type=int, default=9000)
    a = ap.parse_args()

    wdtcon, fcpu, presc, counts, period = wdt_period_ms()
    print("me711_wdt_starvation_proof")
    print()
    import hashlib
    shown = a.image or PI.image()
    print("  image   %s" % Path(shown).name)
    print("  sha256  %s"
          % hashlib.sha256(Path(shown).read_bytes()).hexdigest().upper())
    print("  WDTCON  0x%04X -> WDTIN %d, WDTREL 0x%02X, prescaler /%d, "
          "%d counts" % (wdtcon, wdtcon & 1, (wdtcon >> 8) & 0xFF, presc,
                         counts))
    print("  fCPU    %d Hz" % fcpu)
    print("  WATCHDOG PERIOD  %.1f ms   <- the deadline every gap is judged "
          "against" % period)
    print()

    img = a.image or PI.image()
    entry, tickv = image_symbols(img)
    # V97: echo=True - THE K-LINE ALWAYS ECHOES. Since V94's
    # pipelined TX (hcts.c hcts_tx_end) a reply shorter than
    # HCTS_ECHO_LAG_MAX + 1 bytes waits for its echoes and drains them BY
    # COUNT, so on a rig that does not echo the host's NEXT request is
    # drained instead: this gate's Burn after a page write was eaten and
    # never answered (Tier 2, 2026-09-30). Not a firmware defect - no
    # K-line wiring fails to echo - so the rig models the wire.
    probe = HB.Rig(img, entry, HB.TICK_CURRENT,
                   echo=True, steps_per_tick=HB.STEPS_PER_TICK)
    probe.run(GAP.BOOT_WARMUP_STEPS)
    if len(probe.entries) < 2:
        raise SystemExit("warmup reached no ASIC service entries - every "
                         "figure below would be vacuous")
    f, l = probe.entries[0], probe.entries[-1]
    steps_per_ms = (l[1] - f[1]) / ((l[0] - f[0]) & 0xFFFF)
    print("  calibration: %.1f instructions per simulated ms" % steps_per_ms)

    rig = HB.Rig(img, entry, tickv,
                 echo=True, steps_per_tick=HB.STEPS_PER_TICK)
    rig.run(GAP.BOOT_WARMUP_STEPS + int(GAP.SETTLE_MS * steps_per_ms))
    cpu = rig.cpu

    # ---- instrument: every SRVWDT execution, and where the time goes -------
    state = {"last": cpu.steps, "worst": 0, "worst_at": 0, "count": 0,
             "sample": {}, "worst_sample": {}}
    orig_step = cpu.step

    def step():
        ip, csp = cpu.ip, cpu.csp
        try:
            op = rig.mem.r8((csp << 16) | ip)
        except Exception:
            op = 0
        if (cpu.steps & 0x3F) == 0:
            k = (csp << 16) | (ip & 0xFFC0)
            state["sample"][k] = state["sample"].get(k, 0) + 1
        orig_step()
        if op == SRVWDT_OP:
            gap = cpu.steps - state["last"]
            state["count"] += 1
            if gap > state["worst"]:
                state["worst"] = gap
                state["worst_at"] = cpu.steps
                state["worst_sample"] = state["sample"]
            state["last"] = cpu.steps
            state["sample"] = {}

    cpu.step = step

    def ms(n):
        return int(n * steps_per_ms)

    def transact(label, req, matcher, limit_ms):
        """Send, then advance in slices until a CRC-VALID MATCHING reply is on
        the wire. The echo is not a reply."""
        start = len(rig.tx)
        sent_at = cpu.steps + 1
        rig.queue_rx(sent_at, req)
        deadline = cpu.steps + ms(limit_ms)
        at = end = None
        while cpu.steps < deadline and rig.trap is None:
            rig.run(min(ms(a.slice_ms), deadline - cpu.steps))
            stream = bytes(v for _t, v in rig.tx)
            at, end, _payload = SP.find_reply(stream, start, matcher)
            if at is not None:
                break
        if at is None:
            print("  %-34s NO REPLY in %d ms (trap=%s)"
                  % (label, limit_ms, rig.trap))
            return False
        took = (rig.tx_steps[end - 1] - sent_at) / steps_per_ms
        print("  %-34s replied after %.1f ms" % (label, took))
        return True

    print()
    print("  -- a live Burn, with every SRVWDT timed --")
    ok_w = transact(
        "page write 0x02 @%d" % IDLEPAD,
        SP.envelope(b"W" + IDLEPAD.to_bytes(2, "big") + bytes([0x02])),
        lambda d: d == b"\0", 800)
    ok_b = transact("BURN", SP.envelope(b"B"),
                    lambda d: d == b"\0", a.burn_limit_ms)

    print()
    worst_ms = state["worst"] / steps_per_ms
    print("  SRVWDT executions during the run   %d" % state["count"])
    print("  WORST gap between services         %d instructions = %.1f ms"
          % (state["worst"], worst_ms))
    print("  watchdog period                    %.1f ms" % period)
    print()

    if state["worst_sample"]:
        print("  where the worst gap was spent (top PCs, 64-byte buckets):")
        tot = sum(state["worst_sample"].values())
        for k, n in sorted(state["worst_sample"].items(),
                           key=lambda kv: -kv[1])[:12]:
            print("     %02X:%04X..%04X  %6.2f %%  (%d samples)"
                  % (k >> 16, k & 0xFFFF, (k & 0xFFFF) + 0x3F,
                     100.0 * n / tot, n))
    print()

    # NON-VACUITY FIRST. A worst gap measured over a Burn that never ran is
    # not a result, and that is exactly how the first version of this gate
    # reported PASS.
    fails = []
    if not ok_w:
        fails.append("the page write never got a reply - nothing was staged")
    if not ok_b:
        fails.append("THE BURN NEVER ANSWERED - the gap below was measured "
                     "over no commit at all")
    if state["count"] < 100:
        fails.append("only %d SRVWDT executions seen - too few to be a "
                     "measurement" % state["count"])

    # THE THRESHOLD IS A MARGIN, NOT THE DEADLINE, AND THAT DISTINCTION IS THE
    # WHOLE GATE.
    #
    # The first version of this check asked only "is the worst gap under the
    # watchdog period".  Measured against the frozen V51 binary - THE IMAGE
    # THAT PHYSICALLY RESET THIS ECU ON 2026-09-12 - it answered 184.8 ms
    # against 200.7 ms and said PASS.  A gate that passes the artefact whose
    # failure it was written to explain is not a gate.
    #
    # 184.8 ms is 92.1 % of the deadline.  c167sim is not cycle accurate: its
    # clock is a calibrated 10003 instructions per simulated millisecond, and
    # real C167 timing moves with external-bus wait states, the SRAM and flash
    # access times and the actual instruction mix.  A 7.9 % margin is inside
    # that error bar, which is exactly why the hardware went over and the
    # model did not.
    #
    # So the requirement is a REAL margin.  hcts_target_yield() is tick-gated
    # at one millisecond, so once it services the watchdog the worst gap is a
    # millisecond plus the longest stretch between two yields - single-figure
    # milliseconds, not three.  WDT_MARGIN is set at a tenth of the period:
    # comfortably above what the fix achieves, far below what V51 measured, and
    # it fails the frozen V51 binary, which is the only proof that it can fail
    # at all.
    budget = period * WDT_MARGIN
    within = worst_ms < budget
    for f in fails:
        print("  VACUOUS: %s" % f)
    print("  margin budget                      %.1f ms  (%.0f %% of the "
          "period)" % (budget, WDT_MARGIN * 100.0))
    print("  %-66s %s"
          % ("the worst service gap stays well clear of the watchdog",
             "PASS" if within else "FAIL"))
    ok = within and not fails
    if not within:
        print()
        print("  %.1f ms is %.1f %% of a %.1f ms watchdog period."
              % (worst_ms, 100.0 * worst_ms / period, period))
        print("  The frozen V51 binary measures 184.8 ms here and it RESET THE")
        print("  ECU on hardware: rstRawReset = 0x0006 = SWR | WDTR.  A gap")
        print("  this close to the deadline is a reset, not a margin.")
    print()
    print("me711_wdt_starvation_proof: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
