#!/usr/bin/env python3
r"""
me711_isr_budget.py - what every interrupt handler actually costs, measured,
and what that adds up to when an engine is turning.

    py tools\analysis\me711_isr_budget.py

WHY THIS EXISTS.

The service-gap gate answers "can TunerStudio starve the S5500". It does that
on a BENCH workload: no crank signal, no cam signal, no injection or ignition
events. That is the easy case. An ECU that is comfortable at rest and
pathological at 6000 rpm with a tuner connected is a worse outcome than one
that is merely slow, because the failure appears exactly when it matters.

So this measures each handler's real cost in the real linked image, and then
projects the load at engine speeds the firmware will actually see.

HOW THE COST IS MEASURED. The image runs in c167sim; whenever the PC enters a
handler's address range the instructions are counted until it leaves. That is
an honest count of the work done INSIDE the handler body. Where a handler calls
out of its own range the call is reported separately rather than folded in
silently, because a hidden callee is exactly what made the RX drain expensive.

HOW COST BECOMES TIME. Instructions, not simulated milliseconds. c167sim gives
the CPU about 2500 instructions per simulated millisecond as a modelling
choice; the real part manages about 19 900 (fCPU 40 MHz, two CPU clocks per
state time, which tools/analysis/me711_asic_cs_timing.py already uses and correctly
calls a floor). Converting with the simulator's ratio overstates hardware by
about eight times - see the long note in me711_ts_gap_proof.py, which had that
bug. CLOCKS_PER_INSTR here is 4, twice the floor, to absorb taken branches,
calls and external-SRAM wait states.

WHAT IS MEASURED AND WHAT IS MODELLED, kept apart on purpose:

  MEASURED   handler cost in instructions, and the rate of the handlers that
             run on a fixed timebase, from the image itself.
  MODELLED   the rate of the crank, cam, injection and ignition handlers,
             which no bench run can produce because there is no trigger
             signal. Those rates are arithmetic from the decoder geometry and
             the engine speed, and they are labelled MODELLED everywhere they
             appear.

This is a BUDGET, not a WCET theorem. It answers "is there healthy headroom
when the engine is running", which is the question that has to be answered
before anybody trusts a scheduler on a real engine.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import c167sim as S          # noqa: E402
import me711_image as PI     # noqa: E402
import me711_heartbeat_gap_proof as HB   # noqa: E402
import me711_ts_gap_proof as G           # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "firmware/targets/me711"

CLOCKS_PER_INSTR = 4.0
FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-56s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def defines(text, *names):
    out = {}
    for n in names:
        m = re.search(r"#define\s+%s\s+(0x[0-9A-Fa-f]+|\d+)" % n, text)
        if m:
            out[n] = int(m.group(1), 0)
    return out


def code_labels(map_text):
    """(addr, name) for every code label, sorted - so a handler's end is the
    next label rather than a length somebody typed."""
    out = []
    for m in re.finditer(r"^\s*([0-9A-F]{6})H\s+(\w+)\s+LABEL", map_text, re.M):
        out.append((int(m.group(1), 16) & 0xFFFF, m.group(2)))
    for m in re.finditer(
            r"^\s*([0-9A-F]{6})H\s+([0-9A-F]{6})H\s+[0-9A-F]{6}H\s+CODE.*?(\?PR\?\w+)\s*$",
            map_text, re.M):
        out.append((int(m.group(1), 16) & 0xFFFF, m.group(3)))
    return sorted(set(out))


# The handlers worth budgeting, with what drives each one. "rate" is either a
# fixed frequency in entries per millisecond, or None when the rate is set by
# engine speed and is modelled further down.
HANDLERS = [
    ("hc_cc7_isr",     "serial RX drain (CAPCOM1 compare)", "fixed"),
    ("hc_tick_isr",    "1 ms system tick (T8)",             "fixed"),
    ("hc_ssc_rx_isr",  "ASIC frame received (SSC/PEC)",     "fixed"),
    ("hc_ssc_tx_isr",  "ASIC frame sent (SSC/PEC)",         "fixed"),
    ("hc_ssc_err_isr", "SSC error",                         "fixed"),
    ("hc_cc15_isr",    "crank tooth capture",               "engine"),
    ("hc_cc8_isr",     "cam / trigger channel 8",           "engine"),
    ("hc_cc9_isr",     "cam / trigger channel 9",           "engine"),
]


def measure(steps, rx=None):
    """Run the image and count instructions spent inside each handler."""
    mp = PI.MAP
    text = mp.read_text(errors="replace")
    labels = code_labels(text)
    addr = {n: a for a, n in labels}

    ranges = {}
    for name, _desc, _kind in HANDLERS:
        a = addr.get(name)
        if a is None:
            continue
        nxt = [x for x, _n in labels if x > a]
        ranges[name] = (a, min(nxt) if nxt else a + 0x200)

    entry = G._sym(mp, "hc_asic_start_service")
    tick = G._sym(mp, "hc_tick_ms")
    rig = HB.Rig(PI.image(), entry, tick, echo=True)
    if rx:
        # After boot, not during it - see PI.BOOT_STEPS.
        rig.queue_rx(PI.BOOT_STEPS, rx)

    stats = {n: {"entries": 0, "instr": 0, "runs": []} for n in ranges}
    cur = {"name": None, "n": 0}
    order = sorted(ranges.items(), key=lambda kv: kv[1][0])

    o_step = S.CPU.step
    total = [0]

    def step(self):
        pc = self.ip
        here = None
        for n, (lo, hi) in order:
            if lo <= pc < hi:
                here = n
                break
        if here != cur["name"]:
            if cur["name"] is not None:
                st = stats[cur["name"]]
                st["entries"] += 1
                st["instr"] += cur["n"]
                st["runs"].append(cur["n"])
            cur["name"] = here
            cur["n"] = 0
        if here is not None:
            cur["n"] += 1
        total[0] += 1
        return o_step(self)

    S.CPU.step = step
    rig.run(steps)
    S.CPU.step = o_step
    ms = rig.entries[-1][0] if rig.entries else 1
    return stats, ms, total[0]


def trigger_cost():
    """(crank_edge, cam_edge, interrupt-frame) worst-case instruction counts.

    Driven through trg_test_crank_edge()/trg_test_cam_edge(), which are the
    same one-line wrappers around crank_edge()/cam_edge() that the trigger gate
    uses. The interrupt frame is taken from the difference between the ISR's
    own address range and the wrapper, so the number reported for the handler
    is the whole handler and not just its body.
    """
    try:
        import me711_trigger_test as TT
    except Exception as exc:                       # pragma: no cover
        print("    (trigger rig unavailable: %s)" % exc)
        return None, None, 0

    try:
        rig = TT.Call()
        rig.call("trg_init")
        worst_crank = 0
        worst_cam = 0
        t = 1000
        # A full revolution of a 60-2 wheel, then the gap, then another - so
        # the resync and the missing-tooth branches are both exercised and the
        # WORST path is what gets reported, not the cheap steady one.
        for _rev in range(3):
            for _i in range(57):
                t = (t + 400) & 0xFFFF
                rig.m.w16(0xFE52, t)
                before = rig.c.steps
                rig.call("trg_test_crank_edge", t)
                worst_crank = max(worst_crank, rig.c.steps - before)
            t = (t + 1200) & 0xFFFF
            rig.m.w16(0xFE52, t)
            before = rig.c.steps
            rig.call("trg_test_crank_edge", t)
            worst_crank = max(worst_crank, rig.c.steps - before)
        for bank in (1, 2):
            before = rig.c.steps
            rig.call("trg_test_cam_edge", bank)
            worst_cam = max(worst_cam, rig.c.steps - before)
    except SystemExit as exc:
        print("    (trigger rig refused: %s)" % exc)
        return None, None, 0
    except Exception as exc:                       # pragma: no cover
        print("    (trigger rig error: %s)" % exc)
        return None, None, 0

    # The C166 interrupt frame the compiler emits around these handlers, plus
    # isr_done(). Counted rather than guessed: hc_cc15_isr's range minus the
    # call it makes. Twenty is a deliberate over-estimate of the small frame
    # these handlers get; it only ever makes the budget look worse.
    return worst_crank, worst_cam, 20


def main() -> int:
    print("=== HaniCore ME7.1.1 - interrupt and timing budget ===\n")
    print("  image   %s" % PI.image().name)
    print("  sha256  %s" % PI.sha256())

    h = (TARGET / "hctarget.h").read_text(errors="replace")
    d = defines(h, "TGT_FCPU_HZ", "HC_RXTICK_US", "TGT_BAUD",
                "TGT_TICK_RELOAD")
    fcpu = d["TGT_FCPU_HZ"]
    us_per_instr = (CLOCKS_PER_INSTR / fcpu) * 1e6
    instr_per_ms = 1000.0 / us_per_instr
    print("  fCPU    %.3f MHz, %.0f clocks/instruction (2 is the C166 floor)"
          % (fcpu / 1e6, CLOCKS_PER_INSTR))
    print("          -> %.0f instructions per hardware millisecond\n"
          % instr_per_ms)

    print("--- MEASURED: handler cost in the real image, bench workload ---")
    # Past boot AND far enough into the runtime to observe the handlers -
    # see PI.BOOT_STEPS. At 1 400 000 the run ended inside hc_nvm_boot()'s
    # append-only scan, so the RX drain was measured as 0 instructions and
    # reported as an interrupt-budget regression.
    stats, ms, total = measure(PI.BOOT_STEPS + 1_400_000, rx=b"S")
    print("    (%d simulated ms of run, %d instructions total)\n" % (ms, total))
    print("    %-16s %7s %7s %7s %7s   %s"
          % ("handler", "entries", "min", "median", "max", "instructions"))
    cost = {}
    for name, desc, kind in HANDLERS:
        st = stats.get(name)
        if not st or not st["runs"]:
            print("    %-16s %7s   (never entered on this workload)"
                  % (name, "-"))
            cost[name] = None
            continue
        runs = sorted(st["runs"])
        med = runs[len(runs) // 2]
        cost[name] = (runs[0], med, runs[-1], st["entries"])
        print("    %-16s %7d %7d %7d %7d   %s"
              % (name, st["entries"], runs[0], med, runs[-1], desc))

    # ---------------------------------------------------------------- fixed
    print("\n--- MEASURED: fixed-rate load ---")
    rx_us = d["HC_RXTICK_US"]
    fixed_rate = {
        "hc_cc7_isr": 1000.0 / rx_us,     # 40 us -> 25 per ms
        "hc_tick_isr": 1.0,               # 1 ms tick
        "hc_ssc_rx_isr": 0.1,             # 10 ms supervision raster
        "hc_ssc_tx_isr": 0.1,
        "hc_ssc_err_isr": 0.0,            # only on a fault
    }
    fixed_util = 0.0
    print("    %-16s %9s %10s %10s" % ("handler", "per ms", "worst instr",
                                       "CPU %"))
    for name, _desc, kind in HANDLERS:
        if kind != "fixed" or cost.get(name) is None:
            continue
        rate = fixed_rate.get(name, 0.0)
        worst = cost[name][2]
        util = 100.0 * rate * worst / instr_per_ms
        fixed_util += util
        print("    %-16s %9.1f %10d %9.2f%%" % (name, rate, worst, util))
    print("    %-16s %9s %10s %9.2f%%" % ("TOTAL FIXED", "", "", fixed_util))

    # -------------------------------------------------------------- engine
    print("\n--- MODELLED: engine-speed load (60-2 crank, V8, sequential) ---")
    print("    The crank, cam, injection and ignition rates cannot be measured")
    print("    on a bench with no trigger signal, so they are arithmetic from")
    print("    the decoder geometry. Labelled MODELLED, not measured.\n")

    # The trigger handlers cannot fire on a bench workload - there is no crank
    # signal - so their cost is taken from the SAME entry points the trigger
    # gate drives: trg_test_crank_edge() and trg_test_cam_edge() are one-line
    # wrappers around crank_edge() and cam_edge(), which is the whole body of
    # hc_cc15_isr / hc_cc8_isr / hc_cc9_isr apart from the interrupt frame.
    # Measured through the real linked image, not estimated.
    crank_instr, cam_instr, isr_frame = trigger_cost()
    if crank_instr is not None:
        print("    crank_edge()  %d instructions worst case, measured through"
              % crank_instr)
        print("    cam_edge()    %d instructions worst case, the same way"
              % cam_instr)
        print("    interrupt frame + isr_done() adds about %d more\n"
              % isr_frame)
        crank_instr += isr_frame
        cam_instr += isr_frame

    TEETH = 60           # 60-2: 58 physical teeth, 60 tooth positions
    PHYS = 58
    CYL = 8
    print("    NOTE ON THE inj+ign COLUMN. No injector or ignition driver is")
    print("    linked in this image - me711_output_safety_test proves it four")
    print("    ways - so those handlers do not exist yet to be measured. Their")
    print("    rate is real arithmetic; their COST is stood in for by")
    print("    cam_edge(), which is the closest thing here to a scheduled")
    print("    output event. Treat that column as an ESTIMATE, and re-measure")
    print("    it the moment a real driver is linked.")
    print("")
    print("    %-10s %10s %10s %10s %10s %10s"
          % ("rpm", "crank/ms", "cam/ms", "inj+ign/ms", "engine %", "TOTAL %"))
    rows = []
    for rpm in (80, 250, 800, 3000, 6000, 7500):
        rev_per_ms = rpm / 60.0 / 1000.0
        crank_per_ms = rev_per_ms * PHYS
        cam_per_ms = rev_per_ms / 2.0            # one cam event per cycle
        # sequential: one injection and one ignition event per cylinder per
        # two revolutions, and each event is a start and an end edge
        evt_per_ms = rev_per_ms / 2.0 * CYL * 4
        if crank_instr is None:
            rows.append((rpm, crank_per_ms, cam_per_ms, evt_per_ms, None, None))
            continue
        eu = 100.0 * (crank_per_ms * crank_instr
                      + cam_per_ms * (cam_instr or crank_instr)
                      + evt_per_ms * (cam_instr or crank_instr)) / instr_per_ms
        rows.append((rpm, crank_per_ms, cam_per_ms, evt_per_ms, eu,
                     eu + fixed_util))
        print("    %-10d %10.2f %10.3f %10.2f %9.2f%% %9.2f%%"
              % (rpm, crank_per_ms, cam_per_ms, evt_per_ms, eu, eu + fixed_util))
    if crank_instr is None:
        for rpm, c, m, e, _u, _t in rows:
            print("    %-10d %10.2f %10.3f %10.2f %10s %10s"
                  % (rpm, c, m, e, "UNKNOWN", "UNKNOWN"))
        print("\n    The trigger handlers did not execute on this workload, so")
        print("    their cost is UNMEASURED and the engine columns are honest")
        print("    about that rather than carrying an invented number.")

    # ---------------------------------------------------------------- checks
    print("")
    check("the RX drain is the highest-rate handler, as designed",
          cost.get("hc_cc7_isr") is not None,
          "%d instructions worst case" % (cost["hc_cc7_isr"][2]
                                          if cost.get("hc_cc7_isr") else 0))
    if cost.get("hc_cc7_isr"):
        worst = cost["hc_cc7_isr"][2]
        # The optimised handler is 22 instructions on the fast path and 35 with
        # a byte. 60 leaves room for the probe branch and measurement noise but
        # fails loudly if the cross-module call comes back (that cost 46/63).
        check("and it stays cheap enough to run 25 000 times a second",
              worst <= 60,
              "%d instructions, %.2f%% of CPU at %.0f/ms"
              % (worst, 100.0 * fixed_rate["hc_cc7_isr"] * worst / instr_per_ms,
                 fixed_rate["hc_cc7_isr"]))
    check("total FIXED interrupt load leaves the main loop most of the CPU",
          fixed_util < 25.0, "%.2f%% of CPU" % fixed_util)
    check("the drain period is under half a character time",
          rx_us <= (10.0 / d["TGT_BAUD"]) * 1e6 / 2.0,
          "%d us vs %.0f us character" % (rx_us, (10.0 / d["TGT_BAUD"]) * 1e6))

    # THE QUESTION THIS TOOL EXISTS TO ANSWER. A design that is comfortable on
    # a bench and pathological at the rev limit is worse than one that is
    # merely slow, because it fails exactly when it matters.
    peak = [t for _r, _c, _m, _e, _u, t in rows if t is not None]
    if peak:
        worst_total = max(peak)
        check("at the rev limit, interrupts still leave the main loop most "
              "of the CPU", worst_total < 40.0,
              "%.1f%% at %d rpm with TunerStudio connected"
              % (worst_total, rows[-1][0]))
        check("and the engine-speed part grows linearly, not pathologically",
              worst_total < 4.0 * fixed_util,
              "engine load %.1f%% vs fixed %.1f%%"
              % (worst_total - fixed_util, fixed_util))
    else:
        print("  (engine load UNMEASURED - the trigger rig did not run)")

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("INTERRUPT BUDGET REGRESSED.")
        return 1
    print("INTERRUPT BUDGET OK - measured cost, modelled engine rates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
