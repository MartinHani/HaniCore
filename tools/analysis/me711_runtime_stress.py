#!/usr/bin/env python3
r"""me711_runtime_stress.py - the real main loop under engine + DBW + K-line load.

    py tools\analysis\me711_runtime_stress.py [nots|ts57|ts115] [rpm,rpm,...]

Instrument behind tests/firmware/trigger/me711_runtime_stress_proof.py
(runtime-safety audit, 2026-10-06). Calibration: the crank ISR's own T1
measurement (trg_isr_ticks) reads a median of 25 ticks here and 25 ticks on
the AWT (V100 car log 2026-10-03), so the 8-instructions-per-tick model is
hardware-scaled for that path.

The LINKED image boots through main() in c167sim at 8 instructions per timer
tick (= 10 MIPS against the 1.25 MHz CAPCOM timers, the project's modelling
convention). The AWT preset page is preloaded into battery-backed SRAM so
hc_cfg_init() restores it. The harness then drives:

  * a 60-2 crank on CC15 (edges at exact extended-T1 times from an rpm
    profile, steady or ramping),
  * cam 1 on CC8 / P2.8: one edge per revolution, level alternating, which
    is what the LEVEL phase method (camPhaseMode 1) needs for cycle sync,
  * TunerStudio: back-to-back 'O' requests for the whole output-channel block,
    the next request a host turnaround after the previous reply ends.

Measured from the instruction stream (no firmware change):
  per-trap ISR spans (inclusive and exclusive of nested ISRs), longest
  IEN=0 / ILVL>=13 / ILVL>=12 stretches, hc_drysched_service spans,
  crank teeth outstanding between planner drains (capture ring backlog),
  main-loop pass interval (trg_service entries), watchdog service interval,
  CC7 drain interval, and every coil/injector port-direction edge, whose
  crank angle is computed from the injected tooth times.
"""
from __future__ import annotations

import binascii
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import hcpaths  # noqa: F401,E402
import c167sim as S                       # noqa: E402
import me711_image as PI                  # noqa: E402
import me711_heartbeat_gap_proof as HB    # noqa: E402

MAP = PI.MAP.read_text(errors="replace")


def sym(name):
    import re
    m = re.search(r"^\s*([0-9A-F]{6})H\s+%s\s" % re.escape(name), MAP, re.M)
    if not m:
        raise KeyError(name)
    return int(m.group(1), 16)


USTK_TOP = PI.user_stack_top()          # ?C_USERSTACK top (R0 start)
# STKUN, start_me711.a66: 0xF800 since 2026-10-06; before, the 256-byte user
# stack sat at 0xF700-0xF7FF and the system stack ended below it (0xF700)
SSTK_TOP = 0xF700 if USTK_TOP == 0xF800 else 0xF800
T1, T7 = 0xFE52, 0xF050
PSW, SP = 0xFF10, 0xFE12
P2, DP2, DP7, DP8 = 0xFFC0, 0xFFC2, 0xFFD2, 0xFFD6
TICKS_PER_S = 1_250_000
SPT = HB.STEPS_PER_TICK                    # 8 -> 10 MIPS
VECTOR_SEG = S.VECTOR_SEG

TRAPS = {0x1F: "CC15 crank", 0x18: "CC8 cam", 0x19: "CC9 cam2",
         0x17: "CC7 drain", 0x39: "CC25 deadline", 0x3E: "T8 tick",
         0x2E: "SSC RX", 0x2D: "SSC TX", 0x2F: "SSC err", 0x30: "CC16 knock",
         0x3A: "CC26 planner", 0x47: "S0TB reply",
         0x3B: "CC27 S5500"}   # the S5500 exchange level (2026-10-14)


def envelope(payload):
    return (len(payload).to_bytes(2, "big") + payload
            + (binascii.crc32(payload) & 0xFFFFFFFF).to_bytes(4, "big"))


class Stress:
    def __init__(self, page: bytes, baud_div=1, ts=True, och_count=1652):
        img = PI.image()
        self.rig = HB.Rig(img, sym("hc_asic_start_service"), sym("hc_tick_ms"),
                          echo=True, steps_per_tick=SPT)
        r = self.rig
        # 115200 = half the byte time of the image's 57600 model.
        r.byte_ticks //= baud_div
        r.byte_steps = r.byte_ticks * r.steps_per_tick
        for i, b in enumerate(page):
            r.mem.w8(0x380000 + i, b)
        self.cpu, self.mem = r.cpu, r.mem
        # --- trap identification: step() runs past the vector, so record it
        cpu = self.cpu
        orig_check = cpu.check_irq
        def check_irq(_o=orig_check, _c=cpu, _s=self):
            n = _c.irq_taken
            _o()
            if _c.irq_taken != n:
                _s.last_trap = _c.ip >> 2
        cpu.check_irq = check_irq
        self.last_trap = None
        # --- ADC model: a consistent throttle pair, pedal, plant ----------
        self.throttle = 0.20          # plate fraction (DBW off: fixed)
        self.pedal = 0.20
        self.dbw_plant = False        # True: plate follows D.tgt (0x387304)
        self.adc = {}
        self.adc_t0 = None
        # channels whose conversions carry a wrong ADDAT tag: the HAL rejects
        # them (hc_hal_main_sample), so that sensor alone is "not sampled"
        self.adc_mute = set()
        self.dbw_flt_last = None
        self.dbw_flt_log = []
        self.dbw_step_last = None
        self.dbw_step_gap_steps = 0
        hk_r8, hk_w8, hk_w16 = r._hooks
        st = self
        def w16(s_, a, v, _o=hk_w16):
            _o(s_, a, v)
            if (a & 0xFFFFFF) == 0x00FFA0 and (v & 0x80):
                ch = v & 0x0F
                val = st.adc_value(ch)
                if val is not None:
                    s_.sfr[0xFEA0] = (ch << 12) | (val & 0x3FF)
        self.reason_hist = {}
        self.suppr_sites = {}
        self.watch_lo, self.watch_hi, self.watch_from = None, None, 0
        self.watch_log = []
        def watch(aa, v, width):
            if st.watch_lo is not None and st.watch_lo <= aa <= st.watch_hi and st.cpu.steps >= st.watch_from:
                c = st.cpu
                st.watch_log.append((c.steps, hex(aa), hex(v), where((c.csp << 16) | c.ip),
                                     hex(c.m.r16(c.m.sfr.get(0xFE10, 0xFC00))), hex(c.m.sfr.get(0xFE12, 0)), width))
                del st.watch_log[:-300]
        def w16b(s_, a, v, _o=w16):
            aa = a & 0xFFFFFF
            watch(aa, v, 16)
            # Linked hc_dbw_state_t.steps: count actual RUN step entries in
            # instruction time, independently of a delayed tick_ms raster.
            if aa == 0x38732C:
                if v and s_.r8(0x387300) == 2:
                    if st.dbw_step_last is not None:
                        st.dbw_step_gap_steps = max(st.dbw_step_gap_steps,
                                                   st.cpu.steps-st.dbw_step_last)
                    st.dbw_step_last = st.cpu.steps
                else:
                    st.dbw_step_last = None
            if aa == 0x38751E:
                st.reason_hist[v & 0xFFFF] = st.reason_hist.get(v & 0xFFFF, 0) + 1
            elif aa == 0x387512:
                k = where((st.cpu.csp << 16) | st.cpu.ip).split("+")[0]
                st.suppr_sites[k] = st.suppr_sites.get(k, 0) + 1
            return _o(s_, a, v)
        def w8b(s_, a, v, _o=hk_w8):
            aa = a & 0xFFFFFF
            watch(aa, v, 8)
            if aa in (0x38751E, 0x38751F):
                st.reason_hist["b%d" % (v & 0xFF)] = st.reason_hist.get("b%d" % (v & 0xFF), 0) + 1
            elif aa in (0x387512, 0x387513):
                k = where((st.cpu.csp << 16) | st.cpu.ip).split("+")[0]
                st.suppr_sites[k] = st.suppr_sites.get(k, 0) + 1
            return _o(s_, a, v)
        r._hooks = (hk_r8, w8b, w16b)
        self.ts = ts
        self.och_count = och_count
        self.a_plan = sym("hc_drysched_service")
        self.a_trg = sym("trg_service")
        self.a_dl_count = sym("hc_dl_count")
        self.a_dl_types = sym("hc_dl_q_type")
        self.svc_addr = {}
        for n in ['hc_diag_publish', 'eng_service', 'eng_acquire', 'eng_calculate', 'hc_io_lambda_service', 'hc_dbw_service', 'hc_boost_service', 'hc_cfg_mgr_service', 'hc_asic_start_service', 'hc_hal_ain_service', 'hcts_service', 'hc_nvm_service', 'hc_idle_service', 'hc_limp_service', 'hc_dtc_service', 'hc_knock_service', 'hc_vvt_service', 'hc_route_service', 'hc_fuelpump_service', 'hc_main_relay_service', 'hc_safety_service', 'hc_io_runon_service', 'hc_io_test_service', 'hc_cel_service', 'hcts_poll', 'asic_service', 'trg_service', 'hc_drysched_service']:
            try:
                self.svc_addr[sym(n)] = n
            except KeyError:
                pass
        self.svc_stack = []
        # time
        self.t1_ext = 0
        self.t1_last = 0
        # crank
        self.rpm_fn = None
        self.next_edge = None
        self.tooth = 0            # physical tooth index 0..59 of the NEXT edge
        self.rev = 0
        self.teeth_log = []       # (t1_ext, tooth index, rev)
        self.cam_level = 0
        # instrumentation
        self.prof = None          # {(trap, pc): steps} when profiling ISRs
        self.reset_stats()
        import collections
        self.hist = collections.deque(maxlen=400)
        self.isr_stack = []       # [trap, entry_step, entry_sp, nested_steps]
        self.isr_steps_total = 0
        self.plan_stack = []
        self.out_prev = None
        self.edges = []           # (t1_ext, dp2, dp7, dp8)
        # TS host
        self.req_at = None
        self.tx_mark = 0
        self.next_req_step = None

    def reset_stats(self):
        self.isr = {}             # trap -> [count, max_incl, max_excl, sum_excl]
        self.mask = {"IEN0": [0, 0, None], "ILVL13": [0, 0, None],
                     "ILVL12": [0, 0, None]}
        self.plan_max = 0
        self.plan_max_excl = 0
        self.plan_calls = 0
        self.plan_sum = 0
        self.outstanding = 0
        self.outstanding_max = 0
        self.trg_last = None
        self.loop_max = 0
        self.loop_n = 0
        # Preserve the executed service across segment boundaries. Watchdog
        # measurement must not alias the separate 64-instruction sampler.
        if not hasattr(self, "wdt_last"):
            self.wdt_last = None
            self.wdt_samples = []
            self.wdt_services = []
        self.wdt_max = 0
        self.wdt_max_samples = []
        self.wdt_max_services = []
        self.cpu_counts = {}
        self.dbw_step_gap_steps = 0
        self.cpu_module_samples = {}
        self.cc25_batches = {}
        self.dl_occupied_hwm = 0
        self.cc7_last = None
        self.cc7_max = 0
        self.crank_lat_max = 0
        if hasattr(self, "reason_hist"):
            self.reason_hist.clear(); self.suppr_sites.clear()
        self.backlog_sites = []
        self.sp_min = 0xFFFF
        self.svc_max = {}
        self.r0_min = 0xFFFF
        self.gap_max = 0
        self.gap_prof = []
        self.gap_samples = []
        self.gap_start = 0
        self.gap_armed = False
        self.gap_at = 0
        self.replies = 0
        self.reply_bad = 0
        self.reply_timeouts = 0
        self.reply_ms_max = 0.0
        self.seg_start_step = self.cpu.steps if hasattr(self, "cpu") else 0

    def adc_value(self, ch):
        if self.dbw_plant:
            tgt = self.mem.r16(0x387304) / 1000.0
            dt = (self.t1_ext - getattr(self, "_plant_t", self.t1_ext)) / TICKS_PER_S
            self._plant_t = self.t1_ext
            k = min(1.0, dt / 0.030)
            self.throttle += (min(max(tgt, 0.0), 1.0) - self.throttle) * k
        f, p = self.throttle, self.pedal
        return {1: int(102 + f * 852), 3: int(919 - f * 848),
                8: int(150 + p * 699), 9: int(75 + p * 349),
                5: 767,                  # 13.5 V (CFG_ADC_BATT_FS_DV 18.0 V)
                14: 378}.get(ch)         # 100 kPa (AWT G31 transfer)

    # ------------------------------------------------------------ helpers
    def r16(self, name):
        return self.mem.r16(sym(name) & 0xFFFFFF)

    def r8(self, name):
        return self.mem.r8(sym(name) & 0xFFFFFF)

    def boot(self):
        # Through the instrumented loop, so the ADC model is live from the
        # first conversion (DBW latches STALE otherwise, until a key cycle).
        ts, self.ts = self.ts, False
        self.t1_last = self.mem.r16(T1)
        self.run_us(1_200_000)
        self.ts = ts
        self.reset_stats()

    def ticks_per_tooth(self, rpm):
        return TICKS_PER_S * 60.0 / (rpm * 60.0)

    # ------------------------------------------------------------- run
    def run_us(self, us, rpm_fn=None):
        """Advance `us` microseconds of simulated time. rpm_fn(t_s) -> rpm,
        t_s relative to this call; None = engine stopped."""
        r, cpu, mem = self.rig, self.cpu, self.mem
        if S.Mem.r8 is r._restore[0]:
            S.Mem.r8, S.Mem.w8, S.Mem.w16 = r._hooks
        sfr = mem.sfr
        t_end = self.t1_ext + int(us * 1.25)
        t_base = self.t1_ext
        # Bootstrap precedes timer enable. This host escape bound allows 100 ms
        # for initialization; firmware wall-time budgets are checked separately.
        step_limit = cpu.steps + int(us * 10) + max(1_000_000, int(us))
        a_plan, a_trg = self.a_plan, self.a_trg
        isr_stack, plan_stack = self.isr_stack, self.plan_stack
        mask = self.mask
        hist = self.hist
        if rpm_fn and self.next_edge is None:
            self.next_edge = self.t1_ext + int(self.ticks_per_tooth(rpm_fn(0)))
        if not rpm_fn:
            self.next_edge = None
        try:
            while self.t1_ext < t_end:
                if cpu.steps > step_limit:
                    raise S.Trap("runtime timer stopped: bounded host instruction limit exceeded")
                # ---- host side (rig model) ----
                if r._pending_rx and cpu.steps >= r._pending_rx[0][0]:
                    r.rxq.extend(r._pending_rx.pop(0)[1])
                if r._sh_end is not None and cpu.steps >= r._sh_end:
                    r._shift_end()
                r.wire_step()
                if self.ts:
                    self.ts_host()
                # ---- crank / cam ----
                t = sfr.get(T1, 0)
                self.t1_ext += (t - self.t1_last) & 0xFFFF
                self.t1_last = t
                if self.next_edge is not None and self.t1_ext >= self.next_edge:
                    self.crank_edge(rpm_fn, t_base)
                # ---- CJ220 status flag P3.15: no bridge fault ----
                sfr[0xFFC4] = sfr.get(0xFFC4, 0) | 0x8000
                # ---- main-CPU ADC: ADST starts, ~10 us conversion ----
                con = sfr.get(0xFFA0, 0)
                if con & 0x80:
                    if self.adc_t0 is None:
                        self.adc_t0 = cpu.steps
                    elif cpu.steps - self.adc_t0 >= 100:
                        ch = con & 0x0F
                        v = self.adc_value(ch)
                        if v is None:
                            v = 100 + ch * 37
                        tag = ch ^ 0xF if ch in self.adc_mute else ch
                        sfr[0xFEA0] = (tag << 12) | (v & 0x3FF)
                        sfr[0xFFA0] = con & ~0x180
                        sfr[0xFF98] = sfr.get(0xFF98, 0) | 0x80
                        self.adc_t0 = None
                # ---- step with instrumentation ----
                pc = (cpu.csp << 16) | cpu.ip
                if cpu.ext is None:
                    if pc == a_plan:
                        plan_stack.append((cpu.steps, sfr.get(SP, 0), self.isr_steps_total))
                        self.outstanding = 0
                        g = cpu.steps - self.gap_start
                        if g > self.gap_max and self.gap_armed:
                            self.gap_max = g
                            self.gap_prof = self.gap_samples
                            self.gap_at = cpu.steps
                        self.gap_samples = []
                        self.gap_start = cpu.steps
                        self.gap_armed = True
                    if not isr_stack and not (cpu.steps & 63):
                        self.gap_samples.append(pc)
                    nm = self.svc_addr.get(pc)
                    if nm is not None and not isr_stack:
                        self.svc_stack.append((nm, cpu.steps, sfr.get(SP, 0), self.isr_steps_total))
                        if self.wdt_last is not None:
                            self.wdt_services.append(nm)
                    if not (cpu.steps & 63):
                        f = mem.r16(0x387302)
                        if f != self.dbw_flt_last:
                            self.dbw_flt_log.append((cpu.steps, f, where(pc)))
                            self.dbw_flt_last = f
                    if pc == a_trg:
                        if self.trg_last is not None:
                            d = cpu.steps - self.trg_last
                            if d > self.loop_max:
                                self.loop_max = d
                        self.trg_last = cpu.steps
                        self.loop_n += 1
                trap_now = isr_stack[-1][0] if isr_stack else 0
                self.cpu_counts[trap_now] = self.cpu_counts.get(trap_now, 0) + 1
                if not (cpu.steps & 63):
                    key = (trap_now, module(pc))
                    self.cpu_module_samples[key] = self.cpu_module_samples.get(key, 0) + 1
                    if self.wdt_last is not None:
                        self.wdt_samples.append((trap_now, pc))
                hist.append((pc, sfr.get(SP, 0), sfr.get(PSW, 0), cpu.steps))
                if self.prof is not None:
                    k = (isr_stack[-1][0] if isr_stack else 0, pc)
                    self.prof[k] = self.prof.get(k, 0) + 1
                taken = cpu.irq_taken
                serviced = cpu.srvwdt
                cpu.step()
                # Measure executed SRVWDT instructions, including any service
                # outside hc_srvwdt(), and any interrupt before its opcode.
                if cpu.srvwdt != serviced:
                    if self.wdt_last is not None:
                        d = cpu.steps - self.wdt_last
                        if d > self.wdt_max:
                            self.wdt_max = d
                            self.wdt_max_samples = self.wdt_samples
                            self.wdt_max_services = self.wdt_services
                    self.wdt_last = cpu.steps
                    self.wdt_samples = []
                    self.wdt_services = []
                sp = sfr.get(SP, 0)
                if cpu.irq_taken != taken:
                    trap = self.last_trap
                    queued0 = mem.r8(self.a_dl_count) if trap == 0x39 else None
                    if trap == 0x39:
                        occupied = sum(bool(mem.r8(self.a_dl_types + i)) for i in range(24))
                        self.dl_occupied_hwm = max(self.dl_occupied_hwm, occupied)
                    isr_stack.append([trap, cpu.steps, sp, 0, queued0])
                    if trap == 0x17:
                        if self.cc7_last is not None:
                            d = cpu.steps - self.cc7_last
                            if d > self.cc7_max:
                                self.cc7_max = d
                        self.cc7_last = cpu.steps
                    elif trap == 0x1F:
                        self.outstanding += 1
                        if self.outstanding > self.outstanding_max:
                            self.outstanding_max = self.outstanding
                        if self.outstanding >= 5:
                            ip = mem.r16(sp); csp = mem.r16(sp + 2)
                            self.backlog_sites.append((self.outstanding, (csp << 16) | ip, cpu.steps))
                        lat = (self.t1_ext - self.last_edge_t1) if hasattr(self, "last_edge_t1") else 0
                        if lat > self.crank_lat_max:
                            self.crank_lat_max = lat
                while isr_stack and sp >= isr_stack[-1][2] + 6:
                    trap, st, _sp, nested, queued0 = isr_stack.pop()
                    if queued0 is not None:
                        batch = (queued0 - mem.r8(self.a_dl_count)) & 0xFF
                        self.cc25_batches[batch] = self.cc25_batches.get(batch, 0) + 1
                    incl = cpu.steps - st
                    excl = incl - nested
                    s = self.isr.setdefault(trap, [0, 0, 0, 0])
                    s[0] += 1
                    if incl > s[1]:
                        s[1] = incl
                    if excl > s[2]:
                        s[2] = excl
                    s[3] += excl
                    if isr_stack:
                        isr_stack[-1][3] += incl
                    else:
                        self.isr_steps_total += incl
                svs = self.svc_stack
                while svs and sp > svs[-1][2] and not isr_stack:
                    nm, st, _sp, isr0 = svs.pop()
                    excl = cpu.steps - st - (self.isr_steps_total - isr0)
                    if excl > self.svc_max.get(nm, 0):
                        self.svc_max[nm] = excl
                while plan_stack and sp > plan_stack[-1][1]:
                    st, _sp, isr0 = plan_stack.pop()
                    incl = cpu.steps - st
                    excl = incl - (self.isr_steps_total - isr0)
                    self.plan_calls += 1
                    self.plan_sum += excl
                    if incl > self.plan_max:
                        self.plan_max = incl
                    if excl > self.plan_max_excl:
                        self.plan_max_excl = excl
                if sp and sp < self.sp_min:
                    self.sp_min = sp
                r0 = mem.r16(sfr.get(0xFE10, 0xFC00))
                if 0x8000 <= r0 < 0xC000:          # DPP2-relative near pointer
                    r0 = ((sfr.get(0xFE04, 2) & 0x3FF) << 14) | (r0 & 0x3FFF)
                if 0xF000 <= r0 < self.r0_min:
                    self.r0_min = r0
                    self.r0_min_ctx = (cpu.steps, where(pc), [TRAPS.get(f[0], f[0]) for f in isr_stack],
                                       [x[0] for x in self.svc_stack], len(plan_stack))
                psw = sfr.get(PSW, 0)
                lv = psw >> 12
                for key, cond in (("IEN0", not (psw & 0x0800)),
                                  ("ILVL13", lv >= 13), ("ILVL12", lv >= 12)):
                    m = mask[key]
                    if cond:
                        if m[0] == 0:
                            m[2] = pc
                        m[0] += 1
                        if m[0] > m[1]:
                            m[1] = m[0]
                            m.append(m[2])
                            del m[3:-1]
                    else:
                        m[0] = 0
                o = (sfr.get(DP2, 0) & 0xFF, sfr.get(DP7, 0) & 0x70, sfr.get(DP8, 0) & 0xF8)
                if o != self.out_prev:
                    self.edges.append((self.t1_ext, o))
                    self.out_prev = o
        except S.Trap as e:
            print("TRAP %s at step %d" % (e, cpu.steps))
            for pc_, sp_, psw_, st_ in list(hist)[-120:]:
                print("  %8d %06X %-28s SP %04X PSW %04X" % (st_, pc_, where(pc_), sp_, psw_))
            print("WATCH LOG (last writes into the watched range):")
            for w in self.watch_log[-60:]:
                print("  ", w)
            print("R0 now", hex(mem.r16(sfr.get(0xFE10, 0xFC00))), "CP", hex(sfr.get(0xFE10, 0)))
            raise SystemExit("TRAP")
        finally:
            S.Mem.r8, S.Mem.w8, S.Mem.w16 = r._restore

    def crank_edge(self, rpm_fn, t_base):
        cpu, mem = self.cpu, self.mem
        self.last_edge_t1 = self.next_edge
        tooth = self.tooth
        if tooth == 30:                      # cam edge once per revolution
            self.cam_level ^= 1
            v = mem.sfr.get(P2, 0)
            mem.sfr[P2] = (v | 0x0100) if self.cam_level else (v & ~0x0100)
            cpu.capture(8)
        if getattr(self, "drop_teeth", 0):
            self.drop_teeth -= 1             # a crank signal dropout
        else:
            cpu.capture(15)
        self.teeth_log.append((self.next_edge, tooth, self.rev))
        rpm = rpm_fn((self.next_edge - t_base) / TICKS_PER_S)
        tpt = self.ticks_per_tooth(rpm)
        # 60-2: physical teeth 0..57, then a 3-tooth interval back to 0
        if tooth == 57:
            self.next_edge += int(round(3 * tpt))
            self.tooth = 0
            self.rev += 1
        else:
            self.next_edge += int(round(tpt))
            self.tooth = tooth + 1

    # ------------------------------------------------------------ host
    def ts_host(self):
        r, cpu = self.rig, self.cpu
        if self.req_at is None:
            if self.next_req_step is None or cpu.steps >= self.next_req_step:
                req = envelope(b"O" + (0).to_bytes(2, "big")
                               + self.och_count.to_bytes(2, "big"))
                r.rxq.extend(req)
                self.req_at = cpu.steps
                self.tx_mark = len(r.tx)
                self.want = None
            return
        n = len(r.tx) - self.tx_mark
        if self.want is None and n >= 2:
            self.want = 2 + ((r.tx[self.tx_mark][1] << 8) | r.tx[self.tx_mark + 1][1]) + 4
        if self.want is not None and n >= self.want:
            body = bytes(b for _t, b in r.tx[self.tx_mark:self.tx_mark + self.want])
            L = self.want - 6
            payload = body[2:2 + L]
            crc = int.from_bytes(body[2 + L:6 + L], "big")
            self.replies += 1
            if crc != (binascii.crc32(payload) & 0xFFFFFFFF) or L != self.och_count + 1:
                self.reply_bad += 1
            ms = (cpu.steps - self.req_at) / 10000.0
            self.reply_ms_max = max(self.reply_ms_max, ms)
            self.req_at = None
            self.next_req_step = cpu.steps + 10000   # 1 ms host turnaround
            return
        if cpu.steps - self.req_at > 10000 * 1000:     # 1 s: give up
            self.reply_timeouts += 1
            self.req_at = None
            self.next_req_step = cpu.steps + 10000

    # ------------------------------------------------------------ analysis
    def tooth_angle_at(self, t):
        """Crank angle (deg, 0..360 from physical tooth 0) at extended T1 t,
        interpolated from the injected edges; None outside the log."""
        log = self.teeth_log
        lo, hi = 0, len(log) - 1
        if not log or t < log[0][0] or t >= log[-1][0]:
            return None
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if log[mid][0] <= t:
                lo = mid
            else:
                hi = mid
        t0, k0, rev0 = log[lo]
        t1, k1, _ = log[hi]
        span = 18.0 if k0 == 57 else 6.0
        return (rev0 * 360.0 + k0 * 6.0 + (t - t0) / (t1 - t0) * span)

    def summary(self):
        us = lambda steps: steps / 10.0     # 10 MIPS
        out = {}
        out["isr"] = {TRAPS.get(k, hex(k)): dict(n=v[0], max_incl_us=us(v[1]),
                                                 max_excl_us=us(v[2]),
                                                 mean_excl_us=us(v[3] / v[0]))
                      for k, v in self.isr.items()}
        out["mask_us"] = {k: us(v[1]) for k, v in self.mask.items()}
        out["mask_pc"] = {k: hex(v[-1]) if len(v) > 3 else None
                          for k, v in self.mask.items()}
        out["plan"] = dict(calls=self.plan_calls,
                           max_incl_us=us(self.plan_max),
                           max_excl_us=us(self.plan_max_excl),
                           mean_excl_us=us(self.plan_sum / max(1, self.plan_calls)))
        out["ring_outstanding_max"] = self.outstanding_max
        out["loop_max_us"] = us(self.loop_max)
        out["loop_passes"] = self.loop_n
        out["dbw_step_gap_us"] = us(self.dbw_step_gap_steps)
        out["reason_hist"] = {str(k): v for k, v in self.reason_hist.items()}
        out["suppr_sites"] = self.suppr_sites
        out["svc_max_us"] = {k: us(v) for k, v in sorted(self.svc_max.items(), key=lambda kv: -kv[1])}
        out["sys_stack_min_sp"] = hex(self.sp_min)
        out["sys_stack_used_B"] = SSTK_TOP - self.sp_min if self.sp_min != 0xFFFF else None
        out["user_stack_min_r0"] = hex(self.r0_min)
        out["user_stack_used_B"] = USTK_TOP - self.r0_min if self.r0_min != 0xFFFF else None
        out["user_stack_min_ctx"] = getattr(self, "r0_min_ctx", None)
        out["wdt_max_us"] = us(self.wdt_max)
        out["wdt_gap_service_path"] = self.wdt_max_services
        top = {}
        for trap, pc in self.wdt_max_samples:
            key = TRAPS.get(trap, "main") + ":" + module(pc)
            top[key] = top.get(key, 0) + 1
        out["wdt_gap_top_us"] = sorted(
            ((round(n * 64 / 10.0, 1), key) for key, n in top.items()), reverse=True)[:10]
        total = max(1, sum(self.cpu_counts.values()))
        out["cpu_percent"] = {TRAPS.get(k, "main"): round(100.0 * v / total, 3)
                              for k, v in self.cpu_counts.items()}
        # Module attribution is sampled; aggregate trap shares above count
        # every instruction. RX PEC CPU work lives in the tick's HCSERIAL711.
        n_samples = max(1, sum(self.cpu_module_samples.values()))
        out["cpu_module_percent"] = {
            TRAPS.get(trap, "main") + ":" + name: round(100.0 * n / n_samples, 3)
            for (trap, name), n in self.cpu_module_samples.items()}
        out["cc25_events_per_invocation"] = self.cc25_batches
        out["dl_occupied_hwm"] = self.dl_occupied_hwm
        out["cc7_max_us"] = us(self.cc7_max)
        out["ts"] = dict(replies=self.replies, bad=self.reply_bad,
                         timeouts=self.reply_timeouts,
                         reply_ms_max=self.reply_ms_max)
        return out


import re as _re
_LABELS = sorted((int(m.group(1), 16), m.group(2)) for m in
                 _re.finditer(r"^\s*([0-9A-F]{6})H\s+(\w+)\s+LABEL", MAP, _re.M))
_SECS = sorted((int(m.group(1), 16), int(m.group(2), 16), m.group(3)) for m in
               _re.finditer(r"^([0-9A-F]{6})H\s+([0-9A-F]{6})H\s+[0-9A-F]{6}H\s+CODE.*?\s(\?\S+)\s*$", MAP, _re.M))


def module(pc):
    for lo, hi, n in _SECS:
        if lo <= pc <= hi:
            return n[4:] if n.startswith("?PR?") else n.strip("?")
    return hex(pc)


def gap_histogram(samples):
    h = {}
    for pc in samples:
        k = module(pc)
        h[k] = h.get(k, 0) + 1
    return sorted(((v * 64 / 10.0, k) for k, v in h.items()), reverse=True)


def where(pc):
    import bisect
    i = bisect.bisect_right(_LABELS, (pc, "~")) - 1
    return "%s+0x%x" % (_LABELS[i][1], pc - _LABELS[i][0]) if i >= 0 else hex(pc)


# ------------------------------------------------------------ the page
def build_awt_page(dbw=True):
    """The AWT preset page as battery-backed SRAM bytes (header + 4096):
    APPLY preset 3, a Burn's commit (RESTART fields into ACTIVE), and two
    TEST-ONLY edits: rev limit 9900 (the run goes to 9600) and, with dbw,
    dbwEnable 1. Function-call rig on the same image."""
    import me711_config_state_test as T
    import me711_preset_apply_proof as AP
    r = T.boot()
    AP.press_apply(r, 3)
    AP.service(r)
    assert AP.och(r, 764) & 0xFF == 1, "APPLY refused"
    assert r("hc_cfg_mgr_commit_burn", 1, steps=60_000_000) == 0
    for name, v in (("CFG_REV_MAX", 10000), ("CFG_REV_LIMIT", 9900)):
        AP.set_active(r, AP.off(name), v, 2)
    # TEST-ONLY fuel data (the preset ships none): with flow 0 no injector
    # event would be published.
    AP.install_test_fuel(r)
    if dbw:
        AP.set_active(r, AP.off("CAL_DBW_ENABLE"), 1)
    r("hc_cfg_mgr_init")
    r("hc_cfg_commit", steps=20_000_000)
    blob = bytes(r.m.r8(0x380000 + i) for i in range(12 + 4096))
    o = AP.off("CFG_U_DISPLACEMENT_CC")
    assert (blob[12 + o] << 8) | blob[13 + o] == 1781, "displacement lost"
    assert blob[12 + AP.off("CFG_TRIG_SOURCE")] == 1, "preset disabled capture timer"
    return blob


import json  # noqa: E402

COUNTERS = ("dry_sched_capture_overflow", "dry_sched_cancelled", "dry_sched_missed",
            "dry_sched_executed", "hc_rx_ovf", "trg_synclost", "dry_sched_overdwell",
            "dry_spark_skips", "dry_seq_skips", "dry_inj_nofree", "rx_echo_lost",
            "trg_cycle_lost")
DLW = dict(planned_dw=0, planned_sp=1, planned_op=2, planned_cl=3, ex_dw=4, ex_sp=5, ex_op=6,
           ex_cl=7, suppressed=9, cancelled=10, clipped=11, rejected=12, late=13)

def snap(s):
    out = {n: s.r16(n) for n in COUNTERS}
    for k, i in DLW.items(): out["DL_" + k] = s.mem.r16(0x387500 + 2*i)
    return out

def edges_stats(s, t0, t1, rpm):
    """Coil/injector edges inside [t0, t1): spark angle spread, dwell, pulse."""
    ev = [(t, o) for t, o in s.edges if t0 <= t < t1]
    prev = None
    on = {}
    sparks, dwells, pulses, spark_ang = {}, [], [], {}
    for t, o in ev:
        if prev is not None:
            for b in range(8):
                was, now = (prev[0] >> b) & 1, (o[0] >> b) & 1
                if now and not was: on[("c", b)] = t
                if was and not now:
                    sparks[b] = sparks.get(b, 0) + 1
                    if ("c", b) in on: dwells.append((t - on.pop(("c", b))) / 1250.0)
                    a = s.tooth_angle_at(t)
                    if a is not None: spark_ang.setdefault(b, []).append(a % 720.0)
            inj = (prev[1] << 8 | prev[2], o[1] << 8 | o[2])
            for b in range(16):
                was, now = (inj[0] >> b) & 1, (inj[1] >> b) & 1
                if now and not was: on[("i", b)] = t
                if was and not now and ("i", b) in on: pulses.append((t - on.pop(("i", b))) / 1250.0)
        prev = o
    def spread(v):
        if len(v) < 2: return None
        # circular spread on 720: unwrap around the first value
        ref = v[0]; u = [((x - ref + 360.0) % 720.0) - 360.0 for x in v]
        return round(max(u) - min(u), 2)
    revs = (t1 - t0) / 1_250_000 * rpm / 60.0
    return dict(revs=round(revs, 2), sparks=sum(sparks.values()), sparks_per_rev=round(sum(sparks.values()) / revs, 2) if revs else None,
                spark_angle_spread_deg={b: spread(v) for b, v in spark_ang.items()},
                dwell_ms=(round(min(dwells), 3), round(max(dwells), 3)) if dwells else None,
                inj_pulses=len(pulses), inj_ms=(round(min(pulses), 3), round(max(pulses), 3)) if pulses else None)

RT_FIELDS = ("ver", "plan_lat_max", "plan_run_max", "cap_hwm", "dlq_hwm", "quiesce_n",
             "quiesce_last", "beat_age_max", "rt_fault", "exec_faults", "ustk_hwm",
             "sstk_hwm", "pass_max", "wdt_gap_max", "svc_eng", "svc_dbw", "svc_diag",
             "svc_lambda", "svc_other", "rx_hw_ovr", "rx_hwm", "rx_lost", "tx_bytes",
             "plan_runs", "pec_exhaust", "dbw_gap_max", "svc_comms")
RT_COUNTERS = ("quiesce_n", "exec_faults", "rx_hw_ovr", "rx_lost", "tx_bytes",
               "plan_runs", "pec_exhaust")


def rt_record(s):
    """The firmware's own health record (hcrtmon711.h), when the image has one."""
    try:
        a = sym("hc_rt_byte")   # noqa: F841 - present only with the record
    except Exception:
        return None
    return {f: s.mem.r16(0xF280 + 2 * i) for i, f in enumerate(RT_FIELDS)}


def segment(s, name, us, rpm_fn, rpm_end, results):
    before = snap(s); s.mem.w16(0x387500 + 28, 0)   # D.max_late
    rt0 = rt_record(s)
    pec0 = getattr(s.cpu, "pec6_lost", 0)
    s.reset_stats(); t0 = s.t1_ext
    s.run_us(us, rpm_fn)
    after = snap(s)
    d = {k: (after[k] - before[k]) & 0xFFFF for k in after}
    sm = s.summary()
    sm["gap_max_us"] = s.gap_max / 10.0
    sm["gap_top"] = [(round(us_, 1), m) for us_, m in gap_histogram(s.gap_prof)[:6]]
    sm["backlog_sites"] = sorted({module(pc) for n, pc, _ in s.backlog_sites if n >= 7})
    res = dict(segment=name, rpm=rpm_end, fw_delta=d, dl_max_late_us=s.mem.r16(0x387500 + 28) * 0.8,
               state=dict(trg_state=s.r8("trg_state"), trg_rpm=s.r16("trg_rpm"),
                          fuelcut=s.r16("eng_fuelcut"), seq=s.r8("dry_seq_active"),
                          ti_us=s.r16("eng_ti_base_us"), dbw_st=s.mem.r8(0x387300),
                          dbw_flt=s.mem.r16(0x387302), ovd_latch=s.r16("hc_ign_ovd_latch")),
               runtime=sm, edges=edges_stats(s, t0, s.t1_ext, rpm_end))
    rt1 = rt_record(s)
    if rt1 is not None:
        res["rt"] = {k: ((rt1[k] - rt0[k]) & 0xFFFF if k in RT_COUNTERS else v)
                     for k, v in rt1.items()}
    res["pec6_lost"] = getattr(s.cpu, "pec6_lost", 0) - pec0
    res["dbw_flt_log"] = s.dbw_flt_log[-6:]
    res["echo_seen"] = s.mem.r8(sym("echo_seen") & 0xFFFFFF)
    results.append(res)
    print(json.dumps(res), flush=True)

def ramp(a, b, dur):
    return lambda t: a + (b - a) * min(1.0, t / dur)


LAST_RESULTS = []      # what completed, also when a trap ends the run


def run_matrix(tag, points=(1000, 3000, 5000, 7000, 8500, 9600),
               steady_us=150000, page=None):
    ts = tag.startswith("ts")
    s = Stress(page or build_awt_page(), ts=ts, baud_div=2 if "115" in tag else 1)
    s.dbw_plant = True
    s.pedal = 0.25
    s.boot()
    global LAST_RESULTS
    results = LAST_RESULTS = []
    segment(s, "crank 250", 300000, lambda t: 250, 250, results)
    prev = 250
    for rpm in points:
        segment(s, "ramp %d->%d" % (prev, rpm), 150000, ramp(prev, rpm, 0.15), rpm, results)
        # Retain settling as a fully gated transient, then measure steady angles.
        segment(s, "settle %d" % rpm, steady_us, lambda t, r=rpm: r, rpm, results)
        segment(s, "steady %d" % rpm, steady_us, lambda t, r=rpm: r, rpm, results)
        prev = rpm
    s.pedal = 0.0
    segment(s, "decel %d->1000 pedal 0" % prev, 300000, ramp(prev, 1000, 0.3), 1000, results)
    s.pedal = 0.6
    segment(s, "tip-in 1000->4000 pedal 60", 200000, ramp(1000, 4000, 0.2), 4000, results)
    return s, results


if __name__ == "__main__":
    _tag = sys.argv[1] if len(sys.argv) > 1 else "ts115"
    _pts = (tuple(int(x) for x in sys.argv[2].split(","))
            if len(sys.argv) > 2 else (1000, 3000, 5000, 7000, 8500, 9600))
    run_matrix(_tag, _pts)
