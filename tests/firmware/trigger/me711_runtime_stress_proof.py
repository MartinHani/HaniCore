#!/usr/bin/env python3
r"""
me711_runtime_stress_proof.py - the real-time budgets hold with the engine at
speed AND TunerStudio, DBW and wideband running at the same time.

    py tests\firmware\trigger\me711_runtime_stress_proof.py [ts115|ts57|nots]   (~1 h)

WHAT RUNS. tools/analysis/me711_runtime_stress.py boots the LINKED image
through main() in c167sim at the hardware-calibrated 8 instructions per
1.25 MHz tick, with the AWT preset page in battery-backed SRAM (rev limit
9900 and dbwEnable 1 are the only test edits). It injects a 60-2 crank on
CC15, the quick-start cam level/edge on CC8/P2.8, a throttle that follows
the DBW target, consistent TPS/pedal/battery/MAP readings, and back-to-back
TunerStudio 'O' requests for the whole 1652-byte block (default 115200 baud)
with the K-line echo. Profile: crank 250, ramps and 150 ms steady points at
1000 / 3000 / 5000 / 7000 / 8500 / 9600 rpm, a decel and a tip-in.

THE BUDGETS (docs/ARCHITECTURE.md), each a property a
running engine needs:
  * no wild execution (an unimplemented opcode = a corrupted return);
  * MEASURED stacks <= 60 % of each (the static bound, every path, is
    me711_stack_budget_proof's: <= 85 %);
  * the crank capture ring never overflows and the executor never quiesces;
  * every dwell and injector opening the planner published executes;
  * DBW stays in RUN with no fault bit and engine protection never cuts fuel
    (the 2026-10-06 failure: TPS samples starved by a slow main loop);
  * the critical level (ILVL >= 13) is never held longer than 50 us
    (half a 60-2 tooth at 9600 rpm), and every handler stays inside its
    measured execution budget;
  * no single background service stretch exceeds 12 ms of wall time, and
    the DBW control step never waits more than 20 ms while running;
  * the K-line loses nothing: no PEC6 exhaustion, no byte to the boot
    block's S0RINT, no echo loss, every reply complete and CRC-correct;
  * the watchdog is serviced within 10 % of its 200.7 ms period;
  * the executor supervisor never faults (CC25 heartbeat, health check).

VACUITY: each steady point must have PUBLISHED dwell and injection events,
or the engine was not running and the event checks would prove nothing.

NOT PHYSICALLY VERIFIED: a simulator with modelled sensors and an
instantaneous S5500 exchange. The crank ISR's timing matches the car's.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402

import me711_image as PI                 # noqa: E402
import me711_runtime_stress as M         # noqa: E402

POINTS = (1000, 3000, 5000, 7000, 8500, 9600)
ENG_CUT_LIMP = 0x0008
# The longest ILVL >= 13 section may delay the crank capture; it must stay
# well under one tooth at the highest tested speed (104 us at 9600 rpm on a
# 60-2), so a second edge can never overwrite the latched first: <= half.
CRIT_US = 50.0
# Measured worst case + margin, per handler, exclusive of nested levels (us).
ISR_US = {"CC15 crank": 40.0, "CC8 cam": 20.0, "CC9 cam2": 20.0,
          "CC26 planner": 1200.0, "CC25 deadline": 160.0, "T8 tick": 120.0, "S0TB reply": 30.0,
          "SSC RX": 10.0, "SSC TX": 10.0}
# One background service stretch (wall time, all preemption included) and
# the DBW control cadence it allows (nominal 5 ms, supervision 100 ms).
SVC_MS = 12.0
DBW_GAP_MS = 20
FAILS = 0


def check(name, ok, detail=""):
    global FAILS
    print("  [%s] %-62s %s" % ("PASS" if ok else "FAIL", name, detail))
    FAILS += not ok


def main() -> int:
    global FAILS
    FAILS=0
    mode = next((a for a in sys.argv[1:] if a in ("ts115", "ts57", "nots")), "ts115")
    print("=== runtime budgets: engine + DBW + %s ===" % mode)
    print("  image   %s" % PI.image().name)
    print("  sha256  %s\n" % PI.sha256())
    trap = None
    results = []
    try:
        _s, results = M.run_matrix(mode, points=POINTS)
    except SystemExit as e:                      # the rig's TRAP exit
        trap = str(e)
        results = getattr(M, "LAST_RESULTS", results)
    print()
    steady = [r for r in results if r["segment"].startswith("steady")]
    check("no wild execution (corrupted return / opcode trap)", trap is None,
          trap or "%d segments" % len(results))
    if not results:
        print("\nno segment completed")
        return 1
    used = max((r["runtime"].get("user_stack_used_B") or 0) for r in results)
    usize = next(hi + 1 - lo for lo, hi, n in PI.near_segments() if n == "?C_USERSTACK")
    check("user stack measured <= 60 %% of %d B" % usize, used <= 0.6 * usize,
          "deepest %d B" % used)
    sused = max((r["runtime"].get("sys_stack_used_B") or 0) for r in results)
    check("system stack measured <= 60 % of 634 B", sused <= 0.6 * 634,
          "deepest %d B" % sused)
    ovf = sum(r["fw_delta"]["dry_sched_capture_overflow"] for r in results)
    q = sum((r.get("rt") or {}).get("quiesce_n", 0) for r in results)
    check("the crank capture ring never overflows, nothing quiesces", ovf == 0 and q == 0,
          "%d overflows, %d quiesces; worst backlog %d teeth"
          % (ovf, q, max(r["runtime"]["ring_outstanding_max"] for r in results)))
    batches = max((int(k) for r in results
                   for k in r["runtime"].get("cc25_events_per_invocation", {})), default=0)
    check("CC25 handles at most four urgent edges per invocation", batches <= 4,
          "largest batch %d" % batches)
    occupied = max(r["runtime"].get("dl_occupied_hwm", 0) for r in results)
    check("urgent edges plus pending history never fill the 24 slots",
          0 < occupied < 24, "maximum occupied %d" % occupied)
    # The rig's cam is ideal: a withdrawn cycle can only be the firmware (or
    # a port write clobbering the simulated cam input, as the byte-complement
    # P2 write once did - me711_port_mask_proof).
    lost = {r["segment"]: r["fw_delta"].get("trg_cycle_lost", 0) for r in results
            if r["fw_delta"].get("trg_cycle_lost", 0)}
    check("the ideal cam never loses the cycle in any segment", not lost,
          str(lost) if lost else "0 in %d segments" % len(results))
    for r in steady:
        d = r["fw_delta"]
        check("VACUITY %s: dwell and injection were published" % r["segment"],
              d["DL_planned_dw"] > 0 and d["DL_planned_op"] > 0,
              "dwell %d, open %d" % (d["DL_planned_dw"], d["DL_planned_op"]))
        e = r["edges"]
        spreads = [v for v in e["spark_angle_spread_deg"].values() if v is not None]
        if spreads and max(spreads) < 5.0:
            # sequential established: every coil at one angle per cycle
            lost_dw = d["DL_planned_dw"] - d["DL_ex_dw"]
            lost_op = d["DL_planned_op"] - d["DL_ex_op"]
            check("%s: every published dwell and opening executes" % r["segment"],
                  lost_dw <= 2 and lost_op <= 2,
                  "dwell %d/%d, open %d/%d executed (2 allowed at the window edges)"
                  % (d["DL_ex_dw"], d["DL_planned_dw"], d["DL_ex_op"], d["DL_planned_op"]))
        else:
            # still switching from the wasted fallback, one cylinder at its own
            # twin event (ME711_SEQUENTIAL.md): the superseded twin is
            # published and then dropped BY DESIGN, so counts cannot match.
            # What must hold: each coil sparks at its angle or its twin's,
            # dwell bounded, nothing late.
            twin_ok = all(s < 5.0 or 355.0 < s < 365.0 for s in spreads)
            dw = e["dwell_ms"] or (0, 0)
            check("%s (fallback -> sequential switch): every spark at its angle "
                  "or its twin, dwell bounded, nothing late" % r["segment"],
                  bool(spreads) and twin_ok and dw[1] <= 1.5 * dw[0]
                  and d["DL_late"] == 0,
                  "spreads %s deg, dwell %s ms, late %d"
                  % (sorted(round(s, 1) for s in spreads), dw, d["DL_late"]))
    late_n = sum(r["fw_delta"]["DL_late"] for r in results)
    max_late = max(r["dl_max_late_us"] for r in results)
    check("all steady and transient engine edges <= 100 us late",
          late_n == 0 and max_late <= 100.0,
          "%d gross late events; maximum %.1f us" % (late_n, max_late))
    rejected = sum(r["fw_delta"]["DL_rejected"] for r in results)
    cancelled = sum(r["fw_delta"]["DL_cancelled"] for r in results)
    nofree = sum(r["fw_delta"]["dry_inj_nofree"] for r in results)
    check("supported operation has no queue rejection or cancellation",
          rejected == 0 and cancelled == 0 and nofree == 0,
          "%d rejected, %d cancelled, %d injector admission failures"
          % (rejected, cancelled, nofree))
    bad_dbw = [r["segment"] for r in results if r["segment"] != "crank 250"
               and (r["state"]["dbw_st"] != 2 or r["state"]["dbw_flt"] != 0)]
    limp = [r["segment"] for r in results if r["state"]["fuelcut"] & ENG_CUT_LIMP]
    check("DBW stays RUN with no fault; no protection fuel cut", not bad_dbw and not limp,
          "DBW off/faulted in %s; limp cut in %s" % (bad_dbw or "none", limp or "none"))
    crit = max(r["runtime"]["mask_us"].get(k, 0) for r in results
               for k in ("ILVL13", "IEN0"))
    check("the critical level is held <= %.0f us" % CRIT_US, crit <= CRIT_US,
          "longest %.1f us" % crit)
    worst = {}
    for r in results:
        for k, v in r["runtime"]["isr"].items():
            worst[k] = max(worst.get(k, 0.0), v["max_excl_us"])
    over = {k: round(v, 1) for k, v in worst.items() if k in ISR_US and v > ISR_US[k]}
    unknown = sorted(set(worst) - set(ISR_US))
    check("every observed ISR has an explicit execution budget", not unknown,
          "unbudgeted %s" % (unknown or "none"))
    planner_runs = sum((r.get("rt") or {}).get("plan_runs", 0) for r in results)
    planner_lat = max((r.get("rt") or {}).get("plan_lat_max", 0) for r in results)
    check("planner progresses within its 1.2 ms planning horizon",
          planner_runs > 0 and planner_lat <= 1500,
          "%d runs, maximum request latency %.1f us" % (planner_runs, planner_lat * 0.8))
    check("every handler inside its execution budget", not over,
          "over: %s; worst %s" % (over or "none",
                                  {k: round(v, 1) for k, v in sorted(worst.items()) if k in ISR_US}))
    svc = max(max((r.get("rt") or {}).get(f, 0) for f in ("svc_eng", "svc_dbw", "svc_diag",
                                                          "svc_lambda", "svc_other", "svc_comms"))
              for r in results) * 0.0008
    check("no background service stretch exceeds %.0f ms" % SVC_MS, svc <= SVC_MS,
          "longest %.1f ms (wall)" % svc)
    gap = max((r.get("rt") or {}).get("dbw_gap_max", 0) for r in results)
    wall_gap = max(r["runtime"]["dbw_step_gap_us"] for r in results) / 1000.0
    check("the DBW control step never waits more than %d ms in RUN" % DBW_GAP_MS,
          0 < gap <= DBW_GAP_MS and 0 < wall_gap <= DBW_GAP_MS,
          "largest gap %d tick ms, %.3f actual ms" % (gap,wall_gap))
    pec = sum(r.get("pec6_lost", 0) for r in results)
    exh = sum((r.get("rt") or {}).get("pec_exhaust", 0) for r in results)
    lost = sum(r["fw_delta"]["rx_echo_lost"] for r in results)
    rx_lost = sum((r.get("rt") or {}).get("rx_lost", 0) for r in results)
    hw_ovr = sum((r.get("rt") or {}).get("rx_hw_ovr", 0) for r in results)
    ring_ovf = sum(r["fw_delta"]["hc_rx_ovf"] for r in results)
    bad = sum(r["runtime"]["ts"]["bad"] + r["runtime"]["ts"]["timeouts"] for r in results)
    check("the K-line loses nothing; every reply complete and correct",
          pec == 0 and exh == 0 and lost == 0 and bad == 0
          and rx_lost == 0 and hw_ovr == 0 and ring_ovf == 0,
          "%d bytes to S0RINT, %d PEC exhaustions, %d echo losses, %d bad/timed out; "
          "%d ring losses, %d hardware overruns, %d RX overflows"
          % (pec, exh, lost, bad, rx_lost, hw_ovr, ring_ovf))
    wdt = max(r["runtime"]["wdt_max_us"] for r in results)
    check("the watchdog is serviced within 10 % of 200.7 ms", wdt <= 20070,
          "worst %.1f ms" % (wdt / 1000))
    ef = sum((r.get("rt") or {}).get("exec_faults", 0) for r in results)
    check("the executor supervisor never faults", ef == 0, "%d faults" % ef)
    print("\n%s" % ("RUNTIME BUDGETS HOLD" if not FAILS else
                    "RUNTIME BUDGETS FAIL - see docs/firmware/RUNTIME_ARCHITECTURE.md"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
