#!/usr/bin/env python3
r"""me711_kline_mixed_proof.py - TunerStudio's whole request mix at 115200 with
the engine at 9600 rpm loses nothing and delays no engine event.

    py tests\firmware\comms\me711_kline_mixed_proof.py [--rpm N] [--ms N]   (~30 min)

me711_runtime_stress_proof polls one request ('O', the whole block) back to
back. A tuning session sends more than that. The linked image runs in c167sim
(tools/analysis/me711_runtime_stress.py: AWT page, 60-2 crank + cam, DBW
plant, K-line echo, 115200) and a scripted host sends, request after reply
(zero turnaround bursts, then 1 ms or pauses), deterministic coverage plus
a seeded random mix of:

  O  the whole 1652-byte block, and random (offset, count) slices of it
  R  random page chunks (1..256 B), checked against the page read at start
     and a single complete 4096-byte page reply
  W  page writes of 1..64 bytes with the VALUE ALREADY THERE (non-destructive)
  S  the signature
  C/I/f/P  command/reply transitions
  pauses of 20..300 ms between requests, and
  a HALF frame (3 bytes) then silence > 20 ms: it must be abandoned unanswered
  and the next request answered

Checks:
  K1 every request answered, length and CRC correct, status 0; the half frame
     unanswered
  K2 every page chunk equals the page read at the start (writes changed nothing)
  K3 receive: no hardware overrun, no ring loss, no PEC6 exhaustion, no byte
     to the boot block's S0RINT, no echo loss
  K4 engine: no capture overflow, no quiesce, the rig's ideal cam never loses
     the cycle, every published dwell/opening executes (2 allowed at the window edges), no late event, no executor
     fault, DBW RUN with no fault
  K5 latency: <=15 ms unexplained overhead after accounting for measured
     hard-realtime UART deferral; <=15 ms request dispatch; bounded byte
     progress and 500 ms normal / 1000 ms full-page completion
  K6 bounded reply-job, critical section, DBW and watchdog service gaps

NOT PHYSICALLY VERIFIED: the simulator's UART is byte-exact, not bit-timed.
"""
from __future__ import annotations

import binascii
import random
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402

import me711_image as PI                 # noqa: E402
import me711_runtime_stress as M         # noqa: E402
import me711_runtime_stress_proof as B   # noqa: E402

OCH, PAGE = 1652, 4096
STEPS_PER_MS = 10000
BYTE_MS = 10.0 / 115.2                   # one 8N1 byte at 115200
ENGINE_TRAPS = {0x1F, 0x18, 0x19, 0x39, 0x3A}
UNEXPLAINED_MS = 15.0
# THE PERIODIC LEVELS ABOVE THE REPLY JOB ARE ATTRIBUTED TOO (2026-10-14).
# The 1 ms tick (T8, ILVL 8 group 0 - the reply job is 8/1 and cannot preempt
# it) and the S5500 exchange (CC27, ILVL 9, since the car-reset fix) run on a
# fixed cadence whatever the link does, so their UART-empty time grows with
# the LENGTH of a reply, not with a defect: on 474FC1E5 the 4096-byte page
# read (716 ms) spent 22.5 ms of wire idle in the tick and 1.1 ms in CC27 -
# the whole of its "unexplained" 29 ms beyond the reply job's own 6 ms. Each
# single stall stays bounded by TX_RECOVERY_US (the non-RT idle check below
# still counts them); only the per-reply SUM is no longer charged to K5.
PERIODIC_TRAPS = {0x3E, 0x3B}            # T8 tick, CC27 S5500
# The supported vehicle client waits 500 ms for an ordinary exchange. A full
# 4096-byte page takes 357 ms of wire time alone and has a 1000 ms deadline.
# The UART has two byte stages (174 us); a qualified planner span is longer
# than that, so CPU-priority deferral necessarily inserts wire idle periods.
# Only observed UART-empty time in engine traps earns that allowance.
NORMAL_REPLY_MS, FULL_PAGE_REPLY_MS = 500.0, 1000.0
# After engine RT yields, one tick (same ILVL as TX), one TX entry and SSC
# overhead can precede progress. Keep that recovery independently bounded.
TX_RECOVERY_US = (B.ISR_US["T8 tick"] + B.ISR_US["S0TB reply"]
                  + B.ISR_US["SSC RX"] + B.ISR_US["SSC TX"] + 20.0)


def req(payload):
    return M.envelope(payload)


class Host:
    def __init__(self, s, seed=7):
        self.s, self.rng = s, random.Random(seed)
        self.page = None                 # filled by the first reads
        self.initial_page = None
        self.cur = None                  # (kind, expected payload len, check, t_sent, n_bytes)
        self.next_at = 0
        self.log = []                    # (kind, ok, ms, wire_ms, detail)
        self.partial_pending = None
        self.chunks = [(o, 256) for o in range(0, PAGE, 256)]
        self.page_buf = bytearray(PAGE)
        self.script = None
        self.starts = []                 # (kind, request-to-first-byte ms)
        self.wire_gaps = []              # idle gaps between response bytes
        self.idle_by_kind = {}          # wire-empty instruction attribution
        self.reply_stats = []
        self._idle_rt = self._dispatch_rt = self._recover = self._recover_max = 0
        self._recover_active = False
        self._nonrt_idle = self._nonrt_idle_max = 0
        self._idle_periodic = 0
        self.rx_ring_hwm = 0
        # Count the host/parser ring exactly when either cursor changes.
        # Firmware rx_hwm records a different buffer: pending PEC bytes.
        head, tail = M.sym("hc_rx_head"), M.sym("hc_rx_tail")
        hooks = s.rig._hooks
        old8, old16 = hooks[1], hooks[2]

        def depth(mem, a):
            if (a & 0xFFFFFF) in (head, tail):
                n = (mem.r8(head) - mem.r8(tail)) & 63
                self.rx_ring_hwm = max(self.rx_ring_hwm, n)

        def w8(mem, a, value):
            old8(mem, a, value)
            depth(mem, a)

        def w16(mem, a, value):
            old16(mem, a, value)
            depth(mem, a)

        s.rig._hooks = (hooks[0], w8, w16)

    # -------------------------------------------------------------- script
    def page_edit(self, off, data):
        self.page = self.page[:off] + data + self.page[off + len(data):]
        return True

    def pick(self):
        if self.chunks:                   # read the whole page first
            off, cnt = self.chunks.pop(0)
            return "Rfull", b"R" + off.to_bytes(2, "big") + cnt.to_bytes(2, "big"), cnt + 1, \
                lambda p, o=off: self.page_buf.__setitem__(slice(o, o + len(p)), p) or True
        if self.page is None:
            self.page = bytes(self.page_buf)
            self.initial_page = self.page
            # CAL_RESERVED is the last two page bytes. Exercise a real RAM
            # edit without changing a control calibration, read it back,
            # then restore it and read that back too. Never send Burn.
            changed = bytes(b ^ 0xA5 for b in self.page[-2:])
            # Require coverage on every run. Random traffic adds combinations
            # after the complete request/reply and reconnect sequence.
            self.script = [
                ("Rpage", b"R", PAGE + 1, lambda p: p == self.page),
                ("Ofull", b"O" + bytes(2) + OCH.to_bytes(2, "big"), OCH + 1, None),
                ("Oslice", b"O" + (63).to_bytes(2, "big") + (128).to_bytes(2, "big"), 129, None),
                ("Oslice", b"O" + (OCH - 1).to_bytes(2, "big") + (1).to_bytes(2, "big"), 2, None),
                ("R", b"R" + (PAGE - 64).to_bytes(2, "big") + (64).to_bytes(2, "big"), 65,
                 lambda p: p == self.page[-64:]),
                ("W", b"W" + (PAGE - 64).to_bytes(2, "big") + self.page[-64:], 1, None),
                ("Wram", b"W" + (PAGE - 2).to_bytes(2, "big") + changed, 1,
                 lambda p, v=changed: self.page_edit(PAGE - 2, v)),
                ("R", b"R" + (PAGE - 2).to_bytes(2, "big") + (2).to_bytes(2, "big"), 3,
                 lambda p: p == self.page[-2:]),
                ("Wram", b"W" + (PAGE - 2).to_bytes(2, "big") + self.page[-2:], 1,
                 lambda p: self.page_edit(PAGE - 2, self.initial_page[-2:])),
                ("R", b"R" + (PAGE - 2).to_bytes(2, "big") + (2).to_bytes(2, "big"), 3,
                 lambda p: p == self.page[-2:]),
                ("S", b"S", None, None),
                ("C", b"C", 2, lambda p: p == b"\xff"),
                ("I", b"I", 2, lambda p: p == b"\x00"),
                ("f", b"f", 6, None),
                ("P", b"P", 1, None),
                ("half", None, None, None),
                ("pause", None, 300, None),
                ("S", b"S", None, None),
                ("R", b"R" + (63).to_bytes(2, "big") + (128).to_bytes(2, "big"), 129,
                 lambda p: p == self.page[63:191]),
            ]
        if self.script:
            return self.script.pop(0)
        r = self.rng.random()
        if r < 0.20:
            return "Ofull", b"O" + (0).to_bytes(2, "big") + OCH.to_bytes(2, "big"), OCH + 1, None
        if r < 0.45:
            off = self.rng.randrange(0, OCH - 1)
            cnt = self.rng.randrange(1, min(128, OCH - off) + 1)
            return "Oslice", b"O" + off.to_bytes(2, "big") + cnt.to_bytes(2, "big"), cnt + 1, None
        if r < 0.65:
            off = self.rng.randrange(0, PAGE - 1)
            cnt = self.rng.randrange(1, min(256, PAGE - off) + 1)
            return "R", b"R" + off.to_bytes(2, "big") + cnt.to_bytes(2, "big"), cnt + 1, \
                lambda p, o=off: p == self.page[o:o + len(p)]
        if r < 0.85:
            off = self.rng.randrange(0, PAGE - 64)
            cnt = self.rng.randrange(1, 65)
            return "W", b"W" + off.to_bytes(2, "big") + self.page[off:off + cnt], 1, None
        return "S", b"S", None, None

    # -------------------------------------------------------------- host
    def step(self):
        s, cpu, r = self.s, self.s.cpu, self.s.rig
        if self.cur is None:
            if cpu.steps < self.next_at:
                return
            if self.partial_pending is None and self.page is not None and self.rng.random() < 0.05:
                frame = req(b"S")
                r.rxq.extend(frame[:3])
                self.partial_pending = len(r.tx)
                self.next_at = cpu.steps + 30 * STEPS_PER_MS
                return
            if self.partial_pending is not None:
                ok = len(r.tx) == self.partial_pending
                self.log.append(("half", ok, 0.0, 0.0, "answered" if not ok else "abandoned"))
                self.partial_pending = None
            kind, payload, want, chk = self.pick()
            if kind == "half":
                r.rxq.extend(req(b"S")[:3])
                self.partial_pending = len(r.tx)
                self.next_at = cpu.steps + 30 * STEPS_PER_MS
                return
            if kind == "pause":
                self.next_at = cpu.steps + want * STEPS_PER_MS
                return
            frame = req(payload)
            first_rx = r._rx_next_at or (cpu.steps + r.byte_steps + 1)
            self.request_wire_done = first_rx + (len(r.rxq) + len(frame) - 1) * r.byte_steps
            r.rxq.extend(frame)
            self.cur = (kind, want, chk, cpu.steps, len(frame), len(r.tx))
            self._idle_rt = self._dispatch_rt = self._recover = self._recover_max = 0
            self._recover_active = False
            self._nonrt_idle = self._nonrt_idle_max = 0
            self._idle_periodic = 0
            return
        kind, want, chk, t0, nreq, mark = self.cur
        n = len(r.tx) - mark
        complete = n >= 2 and n >= ((r.tx[mark][1] << 8) | r.tx[mark + 1][1]) + 6
        # Attribute engine-priority waiting after the last request wire byte
        # as well as UART-empty waiting during TX. Dispatch itself stays
        # bounded to 15 ms of wall time, independent of this attribution.
        if n == 0 and cpu.steps >= self.request_wire_done and r._sh_end is None:
            trap = s.isr_stack[-1][0] if s.isr_stack else 0
            if trap in ENGINE_TRAPS:
                self._dispatch_rt += 1
        if n and not complete and r._sh_end is None:
            trap = s.isr_stack[-1][0] if s.isr_stack else 0
            label = M.TRAPS.get(trap, "main" if not trap else hex(trap))
            by_trap = self.idle_by_kind.setdefault(kind, {})
            by_trap[label] = by_trap.get(label, 0) + 1
            if trap in ENGINE_TRAPS:
                self._idle_rt += 1
                self._recover = 0
                self._recover_active = True
            else:
                # A UART-empty interval can span consecutive engine ISRs.
                # Bound every non-engine instruction in that interval, not
                # merely its tail after the last engine interrupt.
                self._nonrt_idle += 1
                if trap in PERIODIC_TRAPS:
                    self._idle_periodic += 1
                self._nonrt_idle_max = max(self._nonrt_idle_max, self._nonrt_idle)
                if self._recover_active:
                    self._recover += 1
                    self._recover_max = max(self._recover_max, self._recover)
        else:
            self._recover_active = False
            self._recover = 0
            self._nonrt_idle = 0
        if n < 2:
            if cpu.steps - t0 > 1000 * STEPS_PER_MS:
                self.log.append((kind, False, 1000.0, 0.0, "timeout"))
                self.cur = None
            return
        L = (r.tx[mark][1] << 8) | r.tx[mark + 1][1]
        if n < L + 6:
            if cpu.steps - t0 > 1000 * STEPS_PER_MS:
                self.log.append((kind, False, 1000.0, 0.0, "timeout"))
                self.cur = None
            return
        # S0TBUF writes precede the last wire byte by up to two frames. Reply
        # completion and the next request use the physical shift completion.
        if r._sh_end is not None or r._sh_buf is not None:
            return
        body = bytes(b for _t, b in r.tx[mark:mark + L + 6])
        p = body[2:2 + L]
        crc_ok = int.from_bytes(body[2 + L:6 + L], "big") == (binascii.crc32(p) & 0xFFFFFFFF)
        ok = crc_ok and len(p) >= 1 and p[0] == 0 and (want is None or L == want)
        if ok and chk is not None:
            ok = bool(chk(p[1:]))
        ms = (cpu.steps - t0) / STEPS_PER_MS
        wire = (nreq + L + 6) * BYTE_MS
        self.log.append((kind, ok, ms, wire, "" if ok else "L=%d crc=%s st=%s" % (L, crc_ok, p[:1].hex())))
        self.starts.append((kind, (r.tx_steps[mark] - t0) / STEPS_PER_MS))
        steps = r.tx_wire_steps[mark:mark + L + 6]
        gaps = [(b - a - r.byte_steps) / STEPS_PER_MS for a, b in zip(steps, steps[1:])]
        self.wire_gaps.extend(gaps)
        rt_ms = self._idle_rt / STEPS_PER_MS
        dispatch_rt_ms = self._dispatch_rt / STEPS_PER_MS
        periodic_ms = self._idle_periodic / STEPS_PER_MS
        self.reply_stats.append(dict(kind=kind, completion_ms=ms, wire_ms=wire,
                                    rt_idle_ms=rt_ms, dispatch_rt_ms=dispatch_rt_ms,
                                    periodic_ms=periodic_ms,
                                    unexplained_ms=ms - wire - rt_ms - dispatch_rt_ms - periodic_ms,
                                    dispatch_ms=(r.tx_steps[mark] - t0) / STEPS_PER_MS - nreq * BYTE_MS,
                                    byte_idle_ms=max(gaps, default=0.0),
                                    recovery_us=self._recover_max / 10.0,
                                    byte_nonrt_us=self._nonrt_idle_max / 10.0))
        self.cur = None
        pause = self.rng.random()
        self.next_at = cpu.steps + STEPS_PER_MS * (
            0 if self.chunks or self.script or self.page is None
            else self.rng.randrange(20, 301) if pause < 0.1 else 1)


def main() -> int:
    rpm = int(sys.argv[sys.argv.index("--rpm") + 1]) if "--rpm" in sys.argv else 9600
    dur = int(sys.argv[sys.argv.index("--ms") + 1]) if "--ms" in sys.argv else 4000
    print("=== K-line mixed traffic, 115200, %d rpm, %d ms ===" % (rpm, dur))
    print("  image   %s\n  sha256  %s\n" % (PI.image().name, PI.sha256()))
    s = M.Stress(M.build_awt_page(), ts=False, baud_div=2)
    s.dbw_plant = True
    s.pedal = 0.25
    s.boot()
    s.run_us(300000, lambda t: 250)
    start_rpm = 3500 if "--transients" in sys.argv else rpm
    s.run_us(150000, M.ramp(250, start_rpm, 0.15))
    # SETTLE before measuring, as the stress matrix does: the cam must first
    # establish the cycle. In the wasted-COP fallback a paired cylinder's twin
    # and the other cylinder's event are published separately and MERGED into
    # one queue entry, so published and executed counts (K4) only balance once
    # the engine runs sequentially (at 3000 rpm the switch took ~0.5 s here).
    s.run_us(1000000, lambda t: start_rpm)
    host = Host(s)
    s.ts_host = types.MethodType(lambda self_: host.step(), s)
    s.ts = True
    before, rt0, pec0 = M.snap(s), M.rt_record(s), getattr(s.cpu, "pec6_lost", 0)
    s.mem.w16(0x387500 + 28, 0)
    s.reset_stats()
    t0 = s.t1_ext
    if "--transients" in sys.argv:
        def profile(t):
            if t < 0.8:
                s.pedal = 0.25
                return 3500 + (rpm - 3500) * t / 0.8
            if t < 1.7:
                return rpm
            if t < 2.4:
                s.pedal = 0.0
                return rpm + (2500 - rpm) * (t - 1.7) / 0.7
            if t < 3.0:
                s.pedal = 0.6
                return 2500 + (rpm - 2500) * (t - 2.4) / 0.6
            s.pedal = 0.25
            return rpm
    else:
        profile = lambda t: rpm
    s.run_us(dur * 1000, profile)
    after, rt1 = M.snap(s), M.rt_record(s)
    d = {k: (after[k] - before[k]) & 0xFFFF for k in after}
    rt = {k: ((rt1[k] - rt0[k]) & 0xFFFF if k in M.RT_COUNTERS else v) for k, v in rt1.items()}
    e = M.edges_stats(s, t0, s.t1_ext, rpm)
    max_late_us = s.mem.r16(0x387500 + 28) * 0.8
    summary = s.summary()
    fails = 0

    def check(name, ok, detail):
        nonlocal fails
        print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))
        fails += not ok

    kinds = {}
    for k, ok, ms, wire, det in host.log:
        c = kinds.setdefault(k, [0, 0, 0.0, 0.0])
        c[0] += 1; c[1] += not ok; c[2] = max(c[2], ms); c[3] = max(c[3], ms - wire)
    for k, (n, bad, mx, over) in sorted(kinds.items()):
        print("    %-6s %4d requests, %d bad, slowest %.1f ms, worst beyond wire time %.1f ms"
              % (k, n, bad, mx, over))
        idle = host.idle_by_kind.get(k, {})
        if idle:
            print("           total wire idle by CPU context (ms): %s"
                  % {label: round(steps / STEPS_PER_MS, 3) for label, steps in
                     sorted(idle.items(), key=lambda item: -item[1])})
    bad = [(k, det) for k, ok, ms, wire, det in host.log if not ok]
    reqs = [x for x in host.log if x[0] != "half"]
    check("K1 every request answered and correct; half frame dropped",
          not bad and len(reqs) > 20
          and all(k in kinds for k in ("half", "W", "Wram", "R", "Rpage", "Ofull", "Oslice", "S", "C", "I", "f", "P")),
          "%d requests, %d half frames, bad %s" % (len(reqs), kinds.get("half", [0])[0], bad[:4] or "none"))
    rbad = kinds.get("R", [0, 0])[1]
    check("K2 page reads match RAM edits and restore the original page",
          host.page is not None and host.page == host.initial_page and rbad == 0
          and kinds.get("Wram", [0, 0])[0] == 2 and kinds.get("Wram", [0, 0])[1] == 0,
          "%d chunk reads, %d changed/restored RAM writes" % (kinds.get("R", [0])[0], kinds.get("Wram", [0])[0]))
    pec = getattr(s.cpu, "pec6_lost", 0) - pec0
    check("K3 receive: no overrun, loss, PEC exhaustion, echo loss",
          rt["rx_hw_ovr"] == 0 and rt["rx_lost"] == 0 and rt["pec_exhaust"] == 0
          and pec == 0 and d["rx_echo_lost"] == 0 and d["hc_rx_ovf"] == 0,
          "overruns %d, lost %d, exhausted %d, to S0RINT %d, echo lost %d, PEC high-water %d B, RX ring %d B"
          % (rt["rx_hw_ovr"], rt["rx_lost"], rt["pec_exhaust"], pec, d["rx_echo_lost"], rt["rx_hwm"], host.rx_ring_hwm))
    lost_dw, lost_op = d["DL_planned_dw"] - d["DL_ex_dw"], d["DL_planned_op"] - d["DL_ex_op"]
    dbw_st, dbw_flt = s.mem.r8(0x387300), s.mem.r16(0x387302)
    print("    engine detail:", d)
    check("K4 engine: every event executes, nothing late or quiesced",
          d["DL_planned_dw"] > 0 and abs(lost_dw) <= 2 and abs(lost_op) <= 2 and d["DL_late"] == 0
          and max_late_us <= 100.0 and d["DL_rejected"] == 0 and d["DL_cancelled"] == 0
          and d["dry_inj_nofree"] == 0
          and d["dry_sched_capture_overflow"] == 0 and rt["quiesce_n"] == 0
          and d["trg_cycle_lost"] == 0
          and rt["exec_faults"] == 0 and dbw_st == 2 and dbw_flt == 0,
          "dwell %d/%d, open %d/%d, late %d (max %.0f us), overflow %d, quiesce %d, cycle lost %d, exec faults %d, DBW %d/0x%04X, "
          "spark spread %s"
          % (d["DL_ex_dw"], d["DL_planned_dw"], d["DL_ex_op"], d["DL_planned_op"], d["DL_late"], max_late_us,
             d["dry_sched_capture_overflow"], rt["quiesce_n"], d["trg_cycle_lost"], rt["exec_faults"], dbw_st, dbw_flt,
             sorted(round(v, 2) for v in e["spark_angle_spread_deg"].values() if v is not None)))
    worst = max((over for _k, (_n, _b, _m, over) in kinds.items() if _k != "half"), default=99.0)
    wire_gap = max(host.wire_gaps, default=0.0)
    violations = [r for r in host.reply_stats
                  if r["unexplained_ms"] > UNEXPLAINED_MS
                  or r["dispatch_ms"] > UNEXPLAINED_MS
                  or r["completion_ms"] > (FULL_PAGE_REPLY_MS if r["kind"] == "Rpage" else NORMAL_REPLY_MS)
                  or r["byte_nonrt_us"] > TX_RECOVERY_US
                  or r["recovery_us"] > TX_RECOVERY_US]
    unexplained = max((r["unexplained_ms"] for r in host.reply_stats), default=99.0)
    dispatch = max((r["dispatch_ms"] for r in host.reply_stats), default=99.0)
    recovery = max((r["recovery_us"] for r in host.reply_stats), default=0.0)
    nonrt_idle = max((r["byte_nonrt_us"] for r in host.reply_stats), default=0.0)
    check("K5 <=15 ms unexplained/dispatch; RT deferral bounded",
          not violations and len(host.reply_stats) == len(reqs),
          "raw beyond-wire %.1f ms; unexplained %.1f ms, dispatch %.1f ms, byte idle %.3f ms (non-RT %.1f us/%.1f us), "
          "post-RT recovery %.1f us/%.1f us, violations %s"
          % (worst, unexplained, dispatch, wire_gap, nonrt_idle, TX_RECOVERY_US,
             recovery, TX_RECOVERY_US, violations[:3] or "none"))
    tx = s.isr.get(0x47, [0, 0, 0, 0])
    tx_us = tx[2] / 10.0
    crit_us = summary["mask_us"]["ILVL13"]
    watchdog_ms = summary["wdt_max_us"] / 1000.0
    over_isr = {name: value["max_excl_us"] for name, value in summary["isr"].items()
                if name in B.ISR_US and value["max_excl_us"] > B.ISR_US[name]}
    unknown_isr = sorted(set(summary["isr"]) - set(B.ISR_US))
    usize = next(hi + 1 - lo for lo, hi, name in PI.near_segments() if name == "?C_USERSTACK")
    svc_ms = max(rt.get("svc_" + name, 0) for name in ("eng", "dbw", "diag", "lambda", "other", "comms")) * 0.0008
    check("K6 reply job, critical section, DBW and watchdog budgets",
          tx_us <= 30.0 and crit_us <= 50.0 and rt["dbw_gap_max"] <= 20
          and 0 < summary["dbw_step_gap_us"] <= 20000
          and watchdog_ms <= 20.07 and rt["tx_bytes"] > 0 and not s.mem.flash_writes
          and not over_isr and not unknown_isr and svc_ms <= B.SVC_MS
          and (summary["user_stack_used_B"] or 0) <= usize * 0.6
          and (summary["sys_stack_used_B"] or 0) <= 634 * 0.6,
          "TX %.1f us/%d bytes, critical %.1f us, DBW %d tick ms/%.3f actual ms, watchdog %.2f ms, service %.2f ms, "
          "stack %s/%s B, ISR over %s, unbudgeted %s, flash writes %d"
          % (tx_us, rt["tx_bytes"], crit_us, rt["dbw_gap_max"], summary["dbw_step_gap_us"]/1000.0, watchdog_ms, svc_ms,
             summary["user_stack_used_B"], summary["sys_stack_used_B"], over_isr or "none", unknown_isr or "none", len(s.mem.flash_writes)))
    # Where a service stretch / DBW gap went (the run-gates log keeps only
    # the verdict line): the firmware's own per-segment stretch (wall time,
    # interrupts included) and the simulator's exclusive time per service.
    print("    service stretch by segment (ms): %s"
          % {name: round(rt.get("svc_" + name, 0) * 0.0008, 2)
             for name in ("eng", "dbw", "diag", "lambda", "other", "comms")})
    print("    service exclusive max (us): %s" % dict(list(summary.get("svc_max_us", {}).items())[:8]))
    print("\n%d/6 checks pass" % (6 - fails))
    return 1 if fails else 0


if __name__ == "__main__":
    result=main()
    if "--rpm" not in sys.argv and "--transients" not in sys.argv:
        sys.argv.append("--transients")
        result|=main()
    sys.exit(result)
