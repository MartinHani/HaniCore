#!/usr/bin/env python3
r"""me711_runtime_fault_proof.py - output safety when a real-time level dies.

    py tests\firmware\engine\me711_runtime_fault_proof.py [--control]

The linked image runs in c167sim (tools/analysis/me711_runtime_stress.py: AWT
page, 60-2 crank, DBW plant) at 3000 rpm, and an interrupt level is taken away
by refusing its delivery in the simulator - the register stays as the firmware
programmed it, exactly what a compare that never matches or a source that is
starved looks like to the code.

F  PLANNER STALL (CC26, ILVL 9) for 20 ms - a whole revolution of teeth:
   F1 the capture ring overflows and the executor QUIESCES (reason OVERFLOW)
   F2 no coil and no injector turns ON after the quiesce
   F3 active coils and injectors end within their respective dwell/pulse bounds
   F4 once the planner runs again, sparks resume within 100 ms, at the planned
      angle (spread <= 3 deg per coil), and no stale event fires

X  EXECUTOR STALL (CC25, ILVL 11) for 30 ms while running:
   X1 the tick supervisor reports EXEC_DEAD/LATE and counts one fault
   X2 every coil/injector that was ON when the executor stopped is released
      no later than 3.5 ms after its planned OFF (HC_DL_OVERDUE 2.5 ms + one
      1 ms tick): ON time <= longest normal dwell / pulse + 3.5 ms
   X3 nothing turns ON again while the engine turns - also after CC25 is back
   X4 the inhibit is held while the engine turns and clears only at
      standstill (TRG_NO_SIGNAL for 100 ms); the next start drives the coils

P  EXECUTOR PROGRESS STALL: CC25 keeps running and the beat
   keeps moving, but the OFF of one output never comes - while it is ON, its
   bit is cleared from every queued node that would end it (spark + MAXDWELL
   backstop, or the injector close): the nodes dispatch on time, so the head
   is never overdue, and drive nothing.
   Run AFTER X, so it is the second executor fault of the key cycle:
   P1 coil: the supervisor reports EXEC_STALL and releases it within
      HC_RT_COIL_MS + 2 ms of its ON
   P2 injector: EXEC_STALL, released within HC_RT_INJ_MS + 2 ms of its ON

S  CRANK SIGNAL DROPOUT: 3 consecutive crank edges missing at
   3000 rpm, mid-revolution (a false gap):
   S1 crank sync is lost (trg_synclost counts) and the executor quiesces
   S2 no coil or injector turns ON between the loss and the next crank sync
   S3 coils end within 1.5 x dwell + 0.3 ms, injectors within their pulse bound
   S4 sparks resume after resync, spread <= 3 deg per coil

Q/C/L  Corrupt queue head, queue time hidden in the future, compare mode,
   interrupt priority, and a grossly overdue event while an output is ON.
   Each must release physical commands, latch an observable fault, empty
   the queue, refuse ON until standstill recovery, and run on the next start.
   Diagnostic flags remain latched through every fault in the same key cycle.

F/S additionally snapshot owned OFF deadlines at the quiesce instruction:
   an active coil must end at its committed deadline, never early. Every
   scenario retains the <=50 us critical-section and ISR execution budgets.

Throughout (up to P):
   B1 no coil stays ON longer than 1.5 x the planned dwell + 0.3 ms
   B2 no injector stays open longer than the longest normal pulse + 3.5 ms

--control: the same run with hc_deadline_quiesce and hc_rt_supervise made to
return at once (the mutation is applied to the image in memory) must FAIL.
"""
from __future__ import annotations

import re
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402

import me711_image as PI                  # noqa: E402
import me711_runtime_stress as R          # noqa: E402

CC25IC, CC26IC = 0xF172, 0xF174
HC_RT = 0xF280                            # hcrtmon711.h TGT_RTMON_ADDR
RT_QUIESCE_N, RT_QUIESCE_LAST = HC_RT + 10, HC_RT + 12
RPM = 3000
TPS = 1_250_000                           # T1 ticks per second
CCM6 = 0xFF26
EXECUTOR_INHIBIT = 4
DEAD, LATE, CFG, STALL = 1, 2, 4, 8


def write8(s, name, value):
    s.mem.w8(R.sym(name) & 0xFFFFFF, value)


def write32(s, address, value):
    s.mem.w16(address, value & 0xFFFF)
    s.mem.w16(address + 2, (value >> 16) & 0xFFFF)


def queue(s):
    """Bounded fixture walk. Corrupt indexes are returned, never dereferenced."""
    head, seen = s.r8("hc_dl_q_head"), set()
    while head != 255:
        if head >= 24 or head in seen:
            raise AssertionError("invalid executor queue head/link: %d" % head)
        seen.add(head)
        yield head
        head = s.mem.r8((R.sym("hc_dl_q_next") & 0xFFFFFF) + head)


def observe_quiesce(s):
    """Snapshot committed coil endings at the actual quiesce instruction.

    A CK110 release creates a spark. Bounding dwell alone would accept an
    arbitrary early release, so compare each active coil against its own
    earliest committed SPARK/MAXDWELL deadline, including ownership/routing.
    """
    records = []
    read, write_byte, write_word = s.rig._hooks

    def write(m, address, value):
        if (address & 0xFFFFFF) == RT_QUIESCE_N:
            t7 = s.cpu._sget(R.T1)
            clock_address = R.sym("hc_dl_clock_ticks") & 0xFFFFFF
            now = (m.r16(clock_address) | m.r16(clock_address + 2) << 16)
            now += (t7 - s.r16("hc_dl_clock_last")) & 0xFFFF
            endings = {}
            try:
                nodes = list(queue(s))
            except AssertionError:
                nodes = []              # fault injection deliberately corrupts the list
            for node in nodes:
                ty = m.r8((R.sym("hc_dl_q_type") & 0xFFFFFF) + node) & 15
                if ty not in (2, 4, 5):
                    continue
                mask = m.r8((R.sym("hc_dl_q_mask") & 0xFFFFFF) + node)
                token = m.r16((R.sym("hc_dl_q_id") & 0xFFFFFF) + 2 * node)
                qa = (R.sym("hc_dl_q_time") & 0xFFFFFF) + 4 * node
                when = m.r16(qa) | m.r16(qa + 2) << 16
                kind, index = ("i", 8) if ty == 4 else ("c", 0)
                for bit in range(8):
                    if not (s.r8("hc_dl_on_inj" if index else "hc_dl_on_ign") & mask & (1 << bit)):
                        continue
                    if token != m.r16((R.sym("hc_dl_active_inj" if ty==4 else "hc_dl_owner") & 0xFFFFFF) + 2 * bit):
                        continue
                    physical = m.r8((R.sym("hc_hal_actuator_route") & 0xFFFFFF) + index + bit)
                    for pin in range(8):
                        if physical & (1 << pin):
                            end = s.t1_ext + ((when - now + 0x80000000) & 0xFFFFFFFF) - 0x80000000
                            key = (kind, pin + (12 if kind == "i" and pin < 3 else 0))
                            endings[key] = min(endings.get(key, end), end)
            records.append((s.t1_ext, s.edges[-1][1], endings))
        return write_word(m, address, value)
    s.rig._hooks = (read, write_byte, write)
    return records


def committed_releases(s, records):
    missing, early, late, count = [], [], [], 0
    for t_q, physical, endings in records:
        periods = active_at(s, t_q, s.t1_ext)
        for kind, bit, _on, off in periods:
            command = physical[0] if kind == "c" else (physical[1] << 8 | physical[2])
            if not (command & (1 << bit)):
                continue
            count += 1
            wanted = endings.get((kind, bit))
            if wanted is None or off is None:
                missing.append((bit, wanted, off))
            elif off < wanted - 1:       # one timer tick of observation alignment
                early.append((bit, (off - wanted) / 1.25))
            elif off > wanted + 125:    # strict normal engine lateness budget
                late.append((bit, (off - wanted) / 1.25))
    return count, missing, early, late


def block(cpu, ics):
    """Refuse delivery of these interrupt sources (IE hidden from arbitration
    only; the firmware still reads its own value back)."""
    orig = cpu.check_irq

    def chk():
        saved = []
        for ic in ics:
            v = cpu._sget(ic)
            if v & 0x40:
                cpu._sset(ic, v & ~0x40)
                saved.append(ic)
        orig()
        for ic in saved:
            cpu._sset(ic, cpu._sget(ic) | 0x40)
    cpu.check_irq = chk
    return lambda: setattr(cpu, "check_irq", orig)


def mutate(s, name):
    """First instruction of `name` = return (RET near / RETS far)."""
    mp = PI.MAP.read_text(errors="replace")
    m = re.search(r"^\s*([0-9A-F]{6})H\s+%s\s+LABEL\s+---\s+(\w+)" % name, mp, re.M)
    a = int(m.group(1), 16)
    op = 0xCB if m.group(2) == "NCODE" else 0xDB
    s.mem.flash[a - 0x800000] = op          # the code itself, not a flash
    s.mem.flash[a - 0x800000 + 1] = 0x00    # command cycle


def on_periods(s, t0, t1):
    """[(kind, bit, t_on, t_off)] from the recorded port edges; t_off None = still on."""
    out, on, prev = [], {}, None
    for t, o in s.edges:
        if t > t1:
            break
        if prev is not None:
            words = (("c", prev[0], o[0], 8), ("i", prev[1] << 8 | prev[2], o[1] << 8 | o[2], 16))
            for kind, was_w, now_w, n in words:
                for b in range(n):
                    was, now = (was_w >> b) & 1, (now_w >> b) & 1
                    if now and not was:
                        on[(kind, b)] = t
                    elif was and not now and (kind, b) in on:
                        ton = on.pop((kind, b))
                        if ton >= t0:
                            out.append((kind, b, ton, t))
        prev = o
    for (kind, b), ton in on.items():
        out.append((kind, b, ton, None))
    return out


def outputs_now(s):
    o = s.edges[-1][1] if s.edges else (0, 0, 0)
    return o[0] | o[1] | o[2]


def active_at(s, instant, end):
    return [p for p in on_periods(s, 0, end)
            if p[2] <= instant and (p[3] is None or p[3] >= instant)]


def run_until(s, us, rpm_fn, pred=None, step=100):
    t_end = s.t1_ext + int(us * 1.25)
    while s.t1_ext < t_end:
        s.run_us(step, rpm_fn)
        if pred and pred():
            return s.t1_ext
    return None


def fresh_coil(s, safe_tooth=False):
    previous = s.r8("hc_dl_on_ign")

    def new_charge():
        nonlocal previous
        now = s.r8("hc_dl_on_ign")
        rising, previous = now & ~previous, now
        return rising != 0 and (not safe_tooth or s.tooth not in (0, 1, 55, 56, 57))
    return run_until(s, 100000, lambda t: RPM, new_charge, step=20)


def restart(s):
    """Stop, wait for the executor inhibit to clear, crank and run at RPM."""
    t_stop = s.t1_ext
    t_clear = run_until(s, 2000000, None,
                        lambda: s.mem.r8(R.sym("hc_dl_inhibit") & 0xFFFFFF) == 0, step=5000)
    t_s = s.t1_ext
    s.run_us(300000, lambda t: 250)
    s.run_us(150000, R.ramp(250, RPM, 0.15))
    s.run_us(50000, lambda t: RPM)
    return t_stop, t_clear, t_s


def progress_stall(s, kind):
    """Wait for an output of `kind` to be ON, then, every 20 us, clear its bit
    from the mask of every queued node that would end it (a corrupt executor
    path: the nodes still dispatch - the beat moves, the head is never
    overdue - but drive nothing). Returns (t_on, t_off or None, fault)."""
    on_sym = "hc_dl_on_ign" if kind == "c" else "hc_dl_on_inj"
    ends = (2, 5) if kind == "c" else (4,)            # SPARK, MAXDWELL / CLOSE
    q_mask = R.sym("hc_dl_q_mask") & 0xFFFFFF
    q_type = R.sym("hc_dl_q_type") & 0xFFFFFF
    t_on = run_until(s, 100000, lambda t: RPM, lambda: s.r8(on_sym) != 0, step=20)
    if t_on is None:
        return None, None, 0, False
    bits = s.r8(on_sym) & -s.r8(on_sym)  # one deliberately stuck output
    beat = s.r16("hc_dl_beat")
    logical = bits.bit_length() - 1
    route = s.mem.r8((R.sym("hc_hal_actuator_route") & 0xFFFFFF)
                    + logical + (8 if kind == "i" else 0))
    physical = route.bit_length() - 1
    if kind == "i" and route & 7:
        physical += 12
    oldest = [p[2] for p in active_at(s, t_on, t_on)
              if p[0] == kind and p[1] == physical]
    t_on = min(oldest or [t_on])

    def hide():
        for i in queue(s):
            m = s.mem.r8(q_mask + i)
            if (s.mem.r8(q_type + i) & 15) in ends and m & bits:
                s.mem.w8(q_mask + i, m & ~bits)
        return not (s.r8(on_sym) & bits)
    hide()
    t_off = run_until(s, 300000, lambda t: RPM, hide, step=20)
    s.run_us(1000, lambda t: RPM)      # the flags are written after the release
    return t_on, t_off, s.r16("hc_rt_fault"), s.r16("hc_dl_beat") != beat


def injected_episode(s, name, mutation, expected, restore=None, hold=False, evidence_bit=0):
    """A queue/config fault while an actuator is on, then normal recovery.

    No diagnostic latch is cleared by the fixture: repeated episodes must
    release outputs and increment the episode count with old flags present.
    """
    res = []
    active = run_until(s, 100000, lambda t: RPM,
                       lambda: outputs_now(s) != 0 and s.r8("hc_dl_q_head") < 24
                       and s.r8("hc_dl_inhibit") == 0, step=20)
    assert active is not None, (name, "fixture needs active output and live queue",
                               s.r8("hc_dl_inhibit"), s.r8("hc_dl_q_head"),
                               s.r16("hc_rt_fault"), s.r8("trg_state"))
    start = s.t1_ext
    before_faults, before_flags = s.r16("hc_rt_exec_faults"), s.r16("hc_rt_fault")
    evidence = []
    saved_hooks = s.rig._hooks
    if evidence_bit:
        read, write_byte, write_word = saved_hooks
        target = R.sym("hc_dl_corrupt") & 0xFFFFFF

        def record(m, address, value):
            if (address & 0xFFFFFF) == target:
                evidence.append(value)
            return write_byte(m, address, value)
        s.rig._hooks = (read, record, write_word)
    mutation(s)

    def released():
        if hold and s.r16("hc_rt_exec_faults") == before_faults:
            mutation(s)
        return (s.r16("hc_rt_exec_faults") == before_faults + 1 and outputs_now(s) == 0
                and bool(s.r16("hc_rt_fault") & expected))

    end = run_until(s, 180000, lambda t: RPM, released, step=20)
    s.rig._hooks = saved_hooks
    if restore:
        restore(s)
    flags = s.r16("hc_rt_fault")
    res.append(("%s fault/release: flags 0x%04X -> 0x%04X, episodes %d -> %d, release %.2f ms"
                % (name, before_flags, flags, before_faults, s.r16("hc_rt_exec_faults"),
                   ((end - start) / 1250.0) if end is not None else -1),
                active is not None and end is not None and (flags & expected) != 0
                and flags & before_flags == before_flags))
    if evidence_bit:
        res.append(("%s dispatch preserves fault evidence before tick: %s" % (name, evidence),
                    any(value & evidence_bit for value in evidence)))
    after = s.t1_ext
    run_until(s, 20000, lambda t: RPM)
    stale_on = [p for p in on_periods(s, after, s.t1_ext)]
    res.append(("%s recovery held while turning: new ON %d, queue %d, inhibit %d"
                % (name, len(stale_on), s.r8("hc_dl_count"), s.r8("hc_dl_inhibit")),
                end is not None and not stale_on and outputs_now(s) == 0
                and s.r8("hc_dl_count") == 0 and s.r8("hc_dl_inhibit") == EXECUTOR_INHIBIT
                and s.r16("hc_rt_exec_faults") == before_faults + 1))
    stop, clear, start_again = restart(s)
    sparks = R.edges_stats(s, start_again, s.t1_ext, RPM)["sparks"]
    res.append(("%s deterministic standstill recovery: %.0f ms, restarted %d sparks"
                % (name, ((clear - stop) / 1250.0) if clear else -1, sparks),
                clear is not None and clear - stop >= 100 * 1250 and sparks > 0
                and s.r8("hc_dl_inhibit") == 0))
    if "-v" in sys.argv:
        for detail, passed in res:
            print("[%s] %s" % ("PASS" if passed else "FAIL", detail), flush=True)
    return res


def corrupt_future(s):
    head = s.r8("hc_dl_q_head")
    assert head < 24, "fault fixture needs a live queue head"
    address = (R.sym("hc_dl_q_time") & 0xFFFFFF) + 4 * head
    now_address = R.sym("hc_dl_clock_ticks") & 0xFFFFFF
    now = s.mem.r16(now_address) | s.mem.r16(now_address + 2) << 16
    write32(s, address, (now + TPS) & 0xFFFFFFFF)


def corrupt_overdue(s):
    head = s.r8("hc_dl_q_head")
    assert head < 24, "fault fixture needs a live queue head"
    address = (R.sym("hc_dl_q_time") & 0xFFFFFF) + 4 * head
    now_address = R.sym("hc_dl_clock_ticks") & 0xFFFFFF
    now = s.mem.r16(now_address) | s.mem.r16(now_address + 2) << 16
    write32(s, address, (now - 12500) & 0xFFFFFFFF)


def consumed_overdue(s):
    """Make an owned OFF grossly overdue and dispatch before the next tick.

    A late OFF still needs immediate release; consuming that queue entry
    must not erase the independent supervisor's evidence of executor failure.
    """
    for node in queue(s):
        ty = s.mem.r8((R.sym("hc_dl_q_type") & 0xFFFFFF) + node) & 15
        if ty not in (2, 4, 5):
            continue
        on = s.r8("hc_dl_on_inj" if ty == 4 else "hc_dl_on_ign")
        mask = s.mem.r8((R.sym("hc_dl_q_mask") & 0xFFFFFF) + node)
        token = s.mem.r16((R.sym("hc_dl_q_id") & 0xFFFFFF) + 2 * node)
        owned = any(on & mask & (1 << bit)
                    and token == s.mem.r16((R.sym("hc_dl_active_inj" if ty==4 else "hc_dl_owner") & 0xFFFFFF)
                                          + 2 * bit)
                    for bit in range(8))
        if owned:
            write8(s, "hc_dl_q_head", node)
            corrupt_overdue(s)
            s.cpu._sset(CC25IC, s.cpu._sget(CC25IC) | 0x80)
            return
    raise AssertionError("fault fixture needs an owned OFF for an active output")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control", action="store_true")
    parser.add_argument("-v", action="store_true")
    parser.add_argument("--only", choices=("normal", "progress", "corruption"),
                        help="focused diagnosis; the default runs every scenario")
    args = parser.parse_args()
    control = args.control
    res = []
    s = R.Stress(R.build_awt_page(), ts=False)
    s.dbw_plant = True
    s.pedal = 0.25
    quiesces = observe_quiesce(s)
    print("image %s SHA256 %s" % (PI.STEM, PI.sha256()), flush=True)
    if control:
        mutate(s, "hc_deadline_quiesce")
        mutate(s, "hc_rt_supervise")
    s.boot()
    s.run_us(300000, lambda t: 250)
    s.run_us(150000, R.ramp(250, RPM, 0.15))
    t_ref = s.t1_ext
    s.run_us(100000, lambda t: RPM)
    st = R.edges_stats(s, t_ref, s.t1_ext, RPM)
    dwell = st["dwell_ms"][1] if st["dwell_ms"] else 3.0
    inj_max = st["inj_ms"][1] if st["inj_ms"] else 5.0
    print("baseline 3000 rpm: %s" % st, flush=True)
    run_ok = st["sparks"] > 0

    # ---------------------------------------------------------- F: planner
    if args.only in ("progress", "corruption"):
        return focused(s, args)
    # Without recovery, chained corruption episodes have no live queue for
    # the next injection. The control exercises normal withdrawal and stall.
    if args.only != "normal" and not control:
        res.extend(corruption_cases(s))
    t_bound_start = s.t1_ext
    normal_quiesces = []
    f_q_start = len(quiesces)
    f_charge = fresh_coil(s)
    q0 = s.mem.r16(RT_QUIESCE_N)
    t_stall = s.t1_ext
    unblock = block(s.cpu, [CC26IC])
    t_q = run_until(s, 20000, lambda t: RPM, lambda: s.mem.r16(RT_QUIESCE_N) != q0)
    if t_q is not None:
        run_until(s, max(0, 20000 - (t_q - t_stall) / 1.25), lambda t: RPM)
    unblock()
    t_back = s.t1_ext
    res.append(("F1 planner stalled: quiesce %s (reason %d, 2 = OVERFLOW), %.1f ms after the stall"
                % ("seen" if t_q else "NOT seen", s.mem.r16(RT_QUIESCE_LAST),
                   ((t_q - t_stall) / 1250.0) if t_q else -1),
                f_charge is not None and t_q is not None and s.mem.r16(RT_QUIESCE_LAST) == 2))
    per = on_periods(s, t_stall, t_back)
    late_on = [p for p in per if t_q is not None and p[2] > t_q]
    res.append(("F2 outputs turned ON after the quiesce: %d" % len(late_on), t_q is not None and not late_on))
    lim = int((1.5 * dwell + 0.3) * 1250)
    still = [p for p in active_at(s, t_q, t_back)
             if t_q is not None and (p[3] is None or p[3] > t_q + (lim if p[0] == "c" else int((inj_max + 0.3) * 1250)))] if t_q else [None]
    res.append(("F3 outputs exceed their coil/pulse release bound after quiesce: %d" % len(still), t_q is not None and not still))
    normal_quiesces.extend(quiesces[f_q_start:])
    run_until(s, 100000, lambda t: RPM)
    t_r = s.t1_ext
    s.run_us(50000, lambda t: RPM)
    st2 = R.edges_stats(s, t_r, s.t1_ext, RPM)
    spread = [v for v in st2["spark_angle_spread_deg"].values() if v is not None]
    res.append(("F4 after the planner returns: %d sparks in 50 ms, spread %s deg"
                % (st2["sparks"], spread), st2["sparks"] >= 4 and spread and max(spread) <= 3.0))

    # ---------------------------------------------------------- X: executor
    run_until(s, 100000, lambda t: RPM, lambda: outputs_now(s) != 0, step=20)
    f0 = s.r16("hc_rt_exec_faults")
    t_x = s.t1_ext
    unblock = block(s.cpu, [CC25IC])
    t_rel = run_until(s, 30000, lambda t: RPM, lambda: s.r16("hc_rt_fault") & 3 and outputs_now(s) == 0)
    if args.v:
        print("X: beat %d irq39 %s fault 0x%x inhibit %d out 0x%x cc25ic 0x%x" % (
            s.r16("hc_dl_beat"), s.cpu.irq_count.get(0x39), s.r16("hc_rt_fault"),
            s.mem.r8(R.sym("hc_dl_inhibit") & 0xFFFFFF), outputs_now(s), s.cpu._sget(CC25IC)))
    run_until(s, 30000 - ((t_rel or s.t1_ext) - t_x) / 1.25, lambda t: RPM)
    unblock()
    run_until(s, 50000, lambda t: RPM)
    t_x_end = s.t1_ext
    flt = s.r16("hc_rt_fault")
    res.append(("X1 executor stalled: hc_rt_fault 0x%04X, faults %d -> %d" % (flt, f0, s.r16("hc_rt_exec_faults")),
                (flt & 3) != 0 and s.r16("hc_rt_exec_faults") == f0 + 1))
    span = active_at(s, t_x, t_x_end)
    over = [p for p in span if p[3] is None
            or (p[3] - p[2]) > ((dwell if p[0] == "c" else inj_max) + 3.5) * 1250]
    res.append(("X2 %d output(s) ON at the stall, released %.2f ms after it; over plan + 3.5 ms: %d"
                % (len(span), ((t_rel - t_x) / 1250.0) if t_rel else -1, len(over)),
                t_rel is not None and bool(span) and not over))
    again = [p for p in on_periods(s, t_x, t_x_end) if t_rel is not None and p[2] > t_rel]
    res.append(("X3 outputs ON again while the engine turns (CC25 back for 50 ms): %d" % len(again),
                t_rel is not None and not again))
    held_turning = s.mem.r8(R.sym("hc_dl_inhibit") & 0xFFFFFF)
    t_stop = s.t1_ext
    t_clear = run_until(s, 2000000, None,
                        lambda: s.mem.r8(R.sym("hc_dl_inhibit") & 0xFFFFFF) == 0, step=5000)
    nosig = s.r8("trg_state")
    held = s.mem.r8(R.sym("hc_dl_inhibit") & 0xFFFFFF)
    t_s = s.t1_ext
    s.run_us(300000, lambda t: 250)
    s.run_us(150000, R.ramp(250, RPM, 0.15))
    s.run_us(50000, lambda t: RPM)
    st3 = R.edges_stats(s, t_s, s.t1_ext, RPM)
    res.append(("X4 inhibit %d while turning, cleared %.0f ms after the stop (trg_state %d), restart drives %d sparks"
                % (held_turning, ((t_clear - t_stop) / 1250.0) if t_clear else -1, nosig, st3["sparks"]),
                held_turning == 4 and t_clear is not None and nosig == 0 and held == 0
                and st3["sparks"] > 0))

    # ---------------------------------------------------------- S: dropout
    s_q_start = len(quiesces)
    lost0, q0 = s.r16("trg_synclost"), s.mem.r16(RT_QUIESCE_N)
    # Both loss and recovery are real crank-decoder transitions. Ensure an
    # output is active at the dropout so the policy is exercised.
    s_charge = fresh_coil(s, safe_tooth=True)
    t_d = s.t1_ext
    s.drop_teeth = 3
    # 2026-10-12: THE LOSS IS THE WITHDRAWAL (trg_state below crank sync).
    # trg_synclost COUNTS it only after the crank has delivered another
    # revolution (2026-10-11 overnight: a stall first is the engine
    # stopping, not a P0335), so it no longer moves inside this 20 ms
    # window; S1b below checks that it counts once the engine runs on.
    t_l = run_until(s, 20000, lambda t: RPM, lambda: s.r8("trg_state") < 3, step=20)
    t_sync = run_until(s, 500000, lambda t: RPM, lambda: s.r8("trg_state") >= 3, step=20)
    t_s_end = s.t1_ext
    res.append(("S1 dropout: crank position withdrawn %s (reason %d), quiesces %d -> %d"
                % ("after %.2f ms" % ((t_l - t_d) / 1250.0) if t_l else "NOT",
                   s.r16("trg_loss_reason"), q0, s.mem.r16(RT_QUIESCE_N)),
                s_charge is not None and t_l is not None and s.mem.r16(RT_QUIESCE_N) != q0))
    late_on = [p for p in on_periods(s, t_d, t_s_end)
               if t_l is not None and t_sync is not None and t_l < p[2] < t_sync]
    res.append(("S2 outputs ON between the loss and crank resync (%.1f ms): %d"
                % (((t_sync - t_l) / 1250.0) if (t_l and t_sync) else -1, len(late_on)),
                t_l is not None and t_sync is not None and not late_on))
    still = [p for p in active_at(s, t_l, t_s_end)
             if p[3] is None or p[3] > t_l + (lim if p[0] == "c" else int((inj_max + 0.3) * 1250))] if t_l else [None]
    res.append(("S3 outputs exceed their coil/pulse release bound after the loss: %d" % len(still), t_l is not None and not still))
    run_until(s, 150000, lambda t: RPM)
    t_r = s.t1_ext
    s.run_us(60000, lambda t: RPM)
    st4 = R.edges_stats(s, t_r, s.t1_ext, RPM)
    spread = [v for v in st4["spark_angle_spread_deg"].values() if v is not None]
    res.append(("S4 after resync: %d sparks in 60 ms, spread %s deg" % (st4["sparks"], spread),
                st4["sparks"] >= 4 and spread and max(spread) <= 3.0))
    res.append(("S1b ...and the loss IS counted once the crank runs on (trg_synclost %d -> %d)"
                % (lost0, s.r16("trg_synclost")), s.r16("trg_synclost") == lost0 + 1))
    normal_quiesces.extend(quiesces[s_q_start:])
    count, missing, early, late = committed_releases(s, normal_quiesces)
    res.append(("F/S committed coil/injector releases: %d checked; missing %s, early %s, late %s"
                % (count, missing, early, late), count > 0 and not missing and not early and not late))

    # ---------------------------------------------------------- bounds
    allp = on_periods(s, t_bound_start, s.t1_ext)
    longc = [p for p in allp if p[0] == "c" and p[3] is not None and (p[3] - p[2]) > lim]
    # the executor-stall case (X2) may hold an open injector up to its plan
    # + 3.5 ms; anything beyond that is an injector left open
    limi = int((inj_max + 3.5) * 1250)
    longi = [p for p in allp if p[0] == "i" and p[3] is not None and (p[3] - p[2]) > limi]
    res.append(("B1 coil ON > %.2f ms: %d (max %.2f ms)" % (lim / 1250.0, len(longc),
                max([(p[3] - p[2]) / 1250.0 for p in allp if p[0] == "c" and p[3]] or [0])), not longc))
    res.append(("B2 injector open > %.2f ms: %d" % (limi / 1250.0, len(longi)), not longi))

    # ---------------------------------------------------------- P: progress
    if args.only != "normal":
        res.extend(progress_cases(s))

    res.extend(timing_results(s))
    return report(res, control, run_ok)


def progress_cases(s):
    res = []
    for kind, cap, name in (("c", 25, "P1 coil"), ("i", 140, "P2 injector")):
        n0 = s.r16("hc_rt_exec_faults")
        latched = s.r16("hc_rt_fault")
        t_on, t_off, flt, heartbeat_moves = progress_stall(s, kind)
        held_ms = ((t_off - t_on) / 1250.0) if (t_on and t_off) else -1
        res.append(("%s: its OFF hidden, fault 0x%04X, released %.1f ms after ON (cap %d ms), faults %d -> %d"
                    % (name, flt & 0xFFFF, held_ms, cap, n0, s.r16("hc_rt_exec_faults")),
                    t_off is not None and (flt & STALL) != 0 and heartbeat_moves
                    and flt & latched == latched and outputs_now(s) == 0
                    and held_ms <= cap + 2 and s.r16("hc_rt_exec_faults") == n0 + 1))
        after = s.t1_ext
        s.run_us(20000, lambda t: RPM)
        res.append(("%s stale ON prevented while turning" % name,
                    not on_periods(s, after, s.t1_ext)
                    and s.r8("hc_dl_inhibit") == EXECUTOR_INHIBIT))
        stop, clear, started = restart(s)
        res.append(("%s standstill recovery and next start" % name,
                    clear is not None and clear - stop >= 100 * 1250
                    and R.edges_stats(s, started, s.t1_ext, RPM)["sparks"] > 0))
    return res


def corruption_cases(s):
    res = []
    res.extend(injected_episode(s, "Q1 corrupt head", lambda st: write8(st, "hc_dl_q_head", 254), CFG))
    res.extend(injected_episode(s, "Q2 corrupt future time", corrupt_future, CFG | STALL, hold=True))
    res.extend(injected_episode(s, "C1 compare configuration",
                               lambda st: st.cpu._sset(CCM6, st.cpu._sget(CCM6) & ~0x00F0), CFG))
    # Inject priority corruption repeatedly until the independent tick sees
    # it: ordinary compare re-arm legitimately repairs the priority register.
    res.extend(injected_episode(s, "C2 interrupt priority",
                               lambda st: st.cpu._sset(CC25IC, (st.cpu._sget(CC25IC) & ~0x3F) | 0x04),
                               CFG, hold=True))
    # Grossly overdue queue time with a still-running executor is injected
    # while its delivery is withheld, preventing the test from racing its
    # own mutation against a legitimate dispatch before the next tick.
    res.extend(injected_episode(s, "L2 consumed grossly overdue", consumed_overdue, LATE, evidence_bit=2))
    # First acquire a live output/queue, then stop delivery. Blocking before
    # acquisition can prevent the very ON command the fixture needs.
    release = []
    def overdue_while_blocked(st):
        release.append(block(st.cpu, [CC25IC]))
        corrupt_overdue(st)
    res.extend(injected_episode(s, "L1 grossly overdue", overdue_while_blocked, LATE,
                               restore=lambda st: release[0]()))
    return res


def focused(s, args):
    res = progress_cases(s) if args.only == "progress" else corruption_cases(s)
    res.extend(timing_results(s))
    return report(res, args.control, True)


def timing_results(s):
    from me711_runtime_stress_proof import CRIT_US, ISR_US
    crit = s.mask["ILVL13"][1] / 10.0
    res = [("fault-matrix critical section %.1f us <= %.1f us" % (crit, CRIT_US), crit <= CRIT_US)]
    for trap, name in ((0x39, "CC25 deadline"), (0x3E, "T8 tick")):
        value = s.isr.get(trap, [0, 0, 0, 0])[2] / 10.0
        res.append(("fault-matrix %s exclusive WCET %.1f us <= %.1f us" % (name, value, ISR_US[name]),
                    value <= ISR_US[name]))
    return res


def report(res, control, run_ok):

    nf = 0
    if not run_ok:
        res.insert(0, ("baseline: the engine did not spark", False))
    for n, ok in res:
        print("  [%s] %s" % ("PASS" if ok else "FAIL", n))
        nf += not ok
    if control:
        if nf:
            print("CONTROL OK: %d check(s) fail without quiesce and supervisor" % nf)
            return 0
        print("CONTROL BROKEN: the gate passes without its safety paths")
        return 1
    print("%d/%d checks pass" % (len(res) - nf, len(res)))
    return 1 if nf else 0


if __name__ == "__main__":
    sys.exit(main())
