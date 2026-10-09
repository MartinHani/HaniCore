#!/usr/bin/env python3
r"""
me711_knock_proof.py - the knock driver on the LINKED image (c167sim): the
CC195 window (MF = P8.0) opened and closed by the real CC16 handler at the
right crank angle for the right cylinder, the sensor select and gain on P3
before it, KI (AN15) attributed to that cylinder, the Bosch KR strategy, and
the retard reaching THAT cylinder's spark at the coil pin.

    py tests\firmware\engine\me711_knock_proof.py

THE ENGINE is me711_sequential_proof's AWT rig (4 cylinders, 1-3-4-2,
60-2, tooth #1 78 deg BTDC, quick-start cam LEVEL), sequential COP. The rig
knows the physical truth: cylinder 1's TDC at physical 78, 3's at 258, 4's
at 438, 2's at 618. T7 runs with T1 (both 1.25 MHz); a CC16 match is
delivered as an interrupt with a real RETI frame into hc_cc16_isr; the main
loop's hc_knock_service() runs once a simulated millisecond and
hc_knock_arm() on every step (the serial yield's role). AN15 reads what the
rig's knock model says for the cylinder whose window just closed.

CHECKS
  K1 every cylinder gets windows; each opens at its TDC + start and lasts
     the window length (+/- 1.5 deg), and the handler's cylinder is the one
     whose TDC it follows (720 deg attribution, both halves);
  K2 before each window the sensor select (KSA1/KSA2) and gain (G0..G2) on
     P3 are that cylinder's sensor's codes (sensor 1 -> 3, sensor 2 -> 2);
  K3 MONITOR: a knock on cylinder 3 is detected on cylinder 3 only and no
     spark moves;
  K4 ACTIVE: the same knock retards cylinder 3's spark by the step at the
     pin, every other cylinder's stays put; recovery returns it by time;
  K5 a dead sensor latches its fault and ONLY its cylinders take the
     safety retard; both dead - every cylinder;
  K6 knock Off: the CC195 lines are released (DP3.1..7, DP8.0 inputs) and
     nothing is retarded;
  K7 crank stops mid-window (the scheduler's snapshot goes stale): MF
     drops, nothing stays open or is armed from the stale tooth;
  K8 the window wraps 720 deg (cylinder 2's opens at 708): attribution and
     length hold across the wrap;
  K9 ACTIVE: cylinder 3's DWELL (coil on time) is unchanged while its spark
     is retarded - the retard delays dwell start and spark together; the
     retard never passes knockMaxQ;
  K10 crank sync lost (two consecutive tooth corrections) and recovered:
     no window stays open, and the windows after the new cycle sync are
     attributed to the right cylinder again.
CONTROL: the geometry the scheduler exports is rotated by one cylinder in
SRAM before K1 - the attribution check must FAIL.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_trigger_test as PT          # noqa: E402
import me711_trigger_scheduler_proof as V      # noqa: E402
import me711_sequential_proof as SQ      # noqa: E402

KN = 0x380000 + 0x1A00                   # TGT_RAM_KNOCK
OCH2 = 0x380000 + 0x1800                 # TGT_RAM_OCH2 (OCH offset 1024)
F_ST, F_CYL, F_LEN = 46, 47, 48          # hc_kn711_t (hcknock711.h)
F_GEOM_CYCLE, F_GEOM_TDC = 10, 12
P8, DP8, P3, DP3 = 0xFFD4, 0xFFD6, 0xFFC4, 0xFFC6
CC16, CC16IC, T7 = 0xFE60, 0xF160, 0xF050
ADDAT = 0xFEA0
PHYS_TDC = {0: 78.0, 1: 618.0, 2: 258.0, 3: 438.0}   # cylinder index -> phys
START_X10, LEN_X10 = 150, 300
STEP_Q_DEG = 3.0                                     # CFG_U_KNOCK_STEP_Q 12
CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += 0 if ok else 1
    print("  [%s] %-62s %s" % ("PASS" if ok else "FAIL", name, detail))
    return ok


class KnockRig(SQ.SeqRig):
    def __init__(self, mode=1, sync_mode=2, ikr=None, rotate=False,
                 start_x10=None, **ov):
        super().__init__(sync_mode=sync_mode, inj=2, ign=2)
        h = V.gen_h()
        self.page = lambda n: 0x380000 + 12 + V.uoff(n, h)
        self.start_x10 = START_X10 if start_x10 is None else start_x10
        self._set_knock_page(mode)
        for n, v in ov.items():            # CFG_U_KNOCK_<n> overrides
            (self.w16 if n in ("REF_MIN", "REF_MAX", "RPM_MIN",
                               "DIAG_RPM", "REAPPLY_MS", "REF_INIT")
             else self.w8)("CFG_U_KNOCK_" + n, v)
        self.ikr = ikr or (lambda cyl, n: 200 + (n * 7 + cyl * 13) % 21)
        self.rotate = rotate
        self.nwin = [0] * 4
        self.win = []          # (cyl, open phys, close phys, p3, trg_state)
        self.ms_next = 0
        self.mf = 0
        self.open_at = None
        self.aborted = 0
        self.x.call("hc_knock_init")

    # ---- page -------------------------------------------------------------
    def w8(self, n, v, i=0):
        self.x.m.w8(self.page(n) + i, v & 0xFF)

    def w16(self, n, v, i=0):
        a = self.page(n) + 2 * i
        self.x.m.w8(a, (v >> 8) & 0xFF)
        self.x.m.w8(a + 1, v & 0xFF)

    def _set_knock_page(self, mode):
        self.w8("CFG_U_KNOCK_MODE", mode)
        self.w8("CFG_U_KNOCK_BAND", 7)                      # 14 kHz
        for i, g in enumerate((2, 4, 2, 2)):                # sensor gains
            self.w8("CFG_U_KNOCK_GAIN", g, i)
        for i, s in enumerate((1, 1, 0, 0, 0, 0, 0, 0)):    # cyl 1,2 -> s2
            self.w8("CFG_U_KNOCK_SENSOR", s, i)
        for i in range(8):
            self.w16("CFG_U_KNOCK_RPM_AX", 800 + 800 * i, i)
            self.w16("CFG_U_KNOCK_WIN_START", self.start_x10, i)
            self.w16("CFG_U_KNOCK_WIN_LEN", LEN_X10, i)
        for i in range(6):
            self.w16("CFG_U_KNOCK_KEF_RPM", 1000 * (i + 1), i)
            self.w8("CFG_U_KNOCK_KEF", 40, i)                # 2.5 x
        self.w8("CFG_U_KNOCK_KEF_DYN", 18)
        self.w8("CFG_U_KNOCK_TP", 16)
        self.w8("CFG_U_KNOCK_TP_DYN", 4)
        self.w8("CFG_U_KNOCK_LOAD_MIN", 20)
        self.w16("CFG_U_KNOCK_RPM_MIN", 400)
        self.w16("CFG_U_KNOCK_CLT_MIN", 10390)
        self.w16("CFG_U_KNOCK_REF_INIT", 200)
        self.w16("CFG_U_KNOCK_REAPPLY_MS", 100)
        self.w16("CFG_U_KNOCK_DIAG_RPM", 400)
        self.w16("CFG_U_KNOCK_REF_MIN", 20)
        self.w16("CFG_U_KNOCK_REF_MAX", 1000)
        self.w8("CFG_U_KNOCK_LEARN", 8)
        self.w8("CFG_U_KNOCK_STOP_N", 0)
        self.w8("CFG_U_KNOCK_STEP_Q", 12)                    # 3.0 deg
        self.w8("CFG_U_KNOCK_MAX_Q", 72)
        self.w8("CFG_U_KNOCK_SAFE_Q", 40)                    # 10.0 deg
        self.w8("CFG_U_KNOCK_DIAG_N", 20)

    def set_mode(self, mode):
        self.w8("CFG_U_KNOCK_MODE", mode)

    # ---- the engine model the main loop would hold --------------------------
    def model(self):
        super().model()
        m = self.x.m
        for n, v in (("eng_rl_x10", 800), ("eng_clt_dc", 10900),
                     ("eng_tps_rate", 0)):
            m.w16(PT.sym(n) & 0xFFFF, v)

    # ---- hardware the harness has to provide --------------------------------
    def call_isr(self, fn):
        x = self.x
        a = PT.sym(fn)
        x.m.w16(x.c.cp(), x.stack_top)
        x.m.sfr[0xFE14], x.m.sfr[0xFE16] = 0xF200, 0xFE00
        sp = 0xF700
        for w in (0x0000, a >> 16, 0xFFFE):       # PSW, CSP, IP (RETI)
            sp = (sp - 2) & 0xFFFF
            x.m.w16(sp, w)
        x.m.sfr[0xFE12] = sp
        x.c.csp, x.c.ip = a >> 16, a & 0xFFFF
        for _ in range(20000):
            if x.c.ip == 0xFFFE:
                return
            x.c.step()
        raise SystemExit(fn + " did not return")

    def kn8(self, off):
        return self.x.m.r8(KN + off)

    def och2(self, off, n=2):
        a = OCH2 + off - 1024
        if n == 1:
            return self.x.m.r8(a)
        return (self.x.m.r8(a) << 8) | self.x.m.r8(a + 1)

    def knock_hw(self, t1, phys):
        m = self.x.m
        m.w16(T7, t1)
        if self.rotate and m.r16(KN + F_GEOM_CYCLE) == 7200:
            tdc = [m.r16(KN + F_GEOM_TDC + 2 * i) for i in range(4)]
            for i in range(4):
                m.w16(KN + F_GEOM_TDC + 2 * i, tdc[(i + 1) % 4])
            self.rotate = False
        self.x.call("hc_knock_arm")
        for _ in range(3):
            if not (m.r16(CC16IC) & 0x40):
                break
            d = (t1 - m.r16(CC16)) & 0xFFFF
            if d >= 0x8000:
                break                              # not yet
            st_before = self.kn8(F_ST)
            p3 = m.r16(P3)
            self.call_isr("hc_cc16_isr")
            mf = m.r16(P8) & 1
            cyl = self.kn8(F_CYL)
            if st_before == 1 and mf:
                self.open_at = (cyl, phys, p3,
                                m.r8(PT.sym("trg_state") & 0xFFFF))
            elif st_before == 2 and not mf and self.open_at:
                c, p0, p3o, sto = self.open_at
                self.win.append((c, p0, phys, p3o, sto))
                self.nwin[c] += 1
                m.sfr[ADDAT] = self.ikr(c, self.nwin[c]) & 0x3FF
                self.open_at = None
        if self.clock >= self.ms_next:
            self.ms_next = self.clock + 1250
            self.x.call("hc_knock_service", (self.clock // 1250) & 0xFFFF)
            self.serve_ki()

    def serve_ki(self):
        """The 1 ms tick owns the main ADC since 2026-10-07 (hcmain_me711.c
        adc_service): a KI request (hc_adc_ctl bit 4) is converted on the next
        tick and handed back in adc_raw[15] with bit 5. This rig has no tick,
        so it serves the request the same way, one service call later."""
        try:
            a = PT.sym("hc_adc_ctl") & 0xFFFF
        except (Exception, SystemExit):
            return                                 # an image before the change
        m = self.x.m
        c = m.r8(a)
        if (c & 0x30) == 0x10:
            m.w16((PT.sym("adc_raw") & 0xFFFF) + 30, m.sfr.get(ADDAT, 0) & 0x3FF)
            m.w8(a, (c & 0x0F) | 0x20)

    def service_to(self, ticks):
        n = max(2, ticks // 250)
        t0, c0, a0 = self.t, self.clock, self.cum
        span = 6.0 * ticks / self.p
        for q in range(1, n):
            t1 = (t0 + ticks * q // n) & 0xFFFF
            self.x.set_t1(t1)
            self.clock = c0 + ticks * q // n
            self.model()
            self.x.call("trg_service")
            ph = a0 + span * q / n
            self.knock_hw(t1, ph)
            self.rows.append((self.clock, self.x.call("hc_hal_out_mask_ign"),
                              self.x.call("hc_hal_out_mask_inj"), ph,
                              self.x.m.r8(PT.sym("trg_state") & 0xFFFF)))
        self.t = (t0 + ticks) & 0xFFFF
        self.clock = c0 + ticks
        self.cum = a0 + span


def adiff(a, b, m=720.0):
    d = (a - b) % m
    return min(d, m - d)


def spark_phys(r, cyl, since):
    """the cylinder's compression sparks after `since` (phys, cumulative)"""
    sp = r.sparks()
    return [ph for ph, st in sp[cyl]
            if ph > since and adiff(ph % 720.0, (PHYS_TDC[cyl] - 10.0) % 720.0) < 20]


def attribution(r, wins):
    bad, twin_ok, full = [], 0, [0] * 4
    for c, p0, p1, _p3, st in wins:
        want = (PHYS_TDC[c] + r.start_x10 / 10.0) % 720.0
        if st >= 4:
            full[c] += 1
            if adiff(p0 % 720.0, want) > 1.5:
                bad.append("cyl %d opened at %.1f want %.1f" % (c + 1, p0 % 720, want))
        elif adiff(p0 % 360.0, want % 360.0) > 1.5:
            # crank sync only: the cylinder OR its 360-deg twin (by design)
            bad.append("cyl %d (crank only) opened at %.1f" % (c + 1, p0 % 720))
        else:
            twin_ok += 1
        if abs((p1 - p0) - LEN_X10 / 10.0) > 1.5:
            bad.append("cyl %d length %.1f" % (c + 1, p1 - p0))
    return bad, twin_ok, full


def k1_k2(rotate=False):
    r = KnockRig(mode=1, rotate=rotate)
    r.start(12)
    ok_all = True
    bad, twin_ok, full = attribution(r, r.win)
    ok_all = check("K1: every cylinder windowed after cycle sync"
                   + (" (CONTROL)" if rotate else ""),
                   min(full) >= 3, "full-sync windows per cylinder %s" % full)
    ok_all &= check("K1: open at TDC + start, length as set, right cylinder"
                    + (" (CONTROL)" if rotate else ""),
                    not bad and len(r.win) >= 16,
                    "%d windows (%d before cycle sync, cylinder-or-twin); %s"
                    % (len(r.win), twin_ok, "; ".join(bad[:3])))
    if rotate:
        return ok_all
    sel_bad = []
    for c, _p0, _p1, p3, _st in r.win:
        sens = 1 if c in (0, 1) else 0
        sel = 3 if sens == 0 else 2
        gain = {0: 2, 1: 5}[sens]       # step 2 -> code 2, step 4 -> code 5
        got_sel = ((p3 >> 4) & 1) | (((p3 >> 7) & 1) << 1)
        got_gain = (p3 >> 1) & 7
        if got_sel != sel or got_gain != gain or p3 & 0x60:
            sel_bad.append("cyl %d P3 0x%04X" % (c + 1, p3))
    check("K2: sensor select + gain on P3 before each window",
          not sel_bad, "; ".join(sel_bad[:3]))
    check("K2: CC195 lines driven (DP3.1..7 + DP8.0 outputs)",
          (r.x.m.r16(DP3) & 0xFE) == 0xFE and (r.x.m.r16(DP8) & 1) == 1,
          "DP3 0x%04X DP8 0x%04X" % (r.x.m.r16(DP3), r.x.m.r16(DP8)))
    check("K2: band 14 kHz = code 3 in the ASIC P1 image (bits 12..15)",
          (r.och2(1044) & 0xFF) == 3, "knockCodes 0x%04X" % r.och2(1044))
    return ok_all


def knock_on(cyl, after):
    def f(c, n):
        if c == cyl and n > after:
            return 800
        return 200 + (n * 7 + c * 13) % 21
    return f


FAST = dict(LEARN=2, TP=4)


def k3_k4():
    base = KnockRig(mode=1, **FAST)
    base.start(14)
    s_ref = {c: spark_phys(base, c, base.cum - 1440) for c in range(4)}
    r = KnockRig(mode=1, ikr=knock_on(2, 2), **FAST)
    r.start(14)
    cnt = [r.och2(1102 + i, 1) for i in range(4)]
    check("K3 MONITOR: knock on cylinder 3 detected there only",
          cnt[2] >= 3 and cnt[0] == cnt[1] == cnt[3] == 0, "counts %s" % cnt)
    s_mon = {c: spark_phys(r, c, r.cum - 1440) for c in range(4)}
    same = all(s_mon[c] and s_ref[c]
               and abs((s_mon[c][-1] - s_ref[c][-1])) < 1.0 for c in range(4))
    check("K3 MONITOR: no spark moved (retard 0 at the scheduler)",
          same and r.och2(1050) == 0,
          "knockRetardX10 %d" % r.och2(1050))

    a = KnockRig(mode=2, ikr=knock_on(2, 2), **FAST)
    a.start(14)
    s_act = {c: spark_phys(a, c, a.cum - 1440) for c in range(4)}
    ret = [a.och2(1094 + i, 1) for i in range(4)]
    d3 = (s_act[2][-1] - s_ref[2][-1]) if s_act[2] and s_ref[2] else None
    others = [abs(s_act[c][-1] - s_ref[c][-1]) if s_act[c] and s_ref[c] else 99
              for c in (0, 1, 3)]
    want = ret[2] * 0.25
    # the knock goes on every window, so the last spark fired with the
    # retard BEFORE the latest step (3.0 deg) was added: between the two
    check("K4 ACTIVE: cylinder 3's spark later by its retard, at the pin",
          d3 is not None and ret[2] > 0
          and want - 3.0 - 1.0 <= d3 <= want + 1.0 and d3 >= 2.0,
          "retard now %.2f deg (one step later than the spark), spark moved "
          "%s deg" % (want, None if d3 is None else round(d3, 2)))
    check("K4 ACTIVE: every other cylinder's spark unchanged",
          max(others) < 1.0 and ret[0] == ret[1] == ret[3] == 0,
          "moves %s, retards %s" % ([round(o, 2) for o in others], ret))
    a.ikr = lambda c, n: 200 + (n * 7 + c * 13) % 21
    q0 = ret[2]
    a.runrevs(6)                      # ~0.8 s quiet, 100 ms per 0.25 deg
    q1 = a.och2(1094 + 2, 1)
    check("K4 ACTIVE: recovery returns the retard by time",
          q1 < q0, "q %d -> %d" % (q0, q1))


def k5():
    diag = dict(LEARN=2, TP=1, DIAG_N=3)
    dead1 = KnockRig(mode=2, ikr=lambda c, n: 0 if c in (0, 1) else 210,
                     **diag)
    dead1.start(10)
    f = dead1.och2(1046)
    ret = [dead1.och2(1094 + i, 1) for i in range(4)]
    mx = dead1.och2(1050)
    check("K5: dead sensor 2 (cylinders 1, 2) latches ITS fault only",
          (f >> 8) & 0xF == 0x2, "knockSelFault 0x%04X" % f)
    slot = [dead1.kn8(i) for i in range(9)]
    check("K5: only its cylinders' slots carry the safety retard",
          mx == 100 and sorted(slot[1:5]) == [0, 0, 100, 100],
          "slot_ret %s" % slot[:5])
    both = KnockRig(mode=2, ikr=lambda c, n: 0, **diag)
    both.start(10)
    f2 = both.och2(1046)
    s2 = [both.kn8(i) for i in range(1, 5)]
    check("K5: both dead - every cylinder takes the safety retard",
          (f2 >> 8) & 0xF == 0x3 and s2 == [100] * 4,
          "fault 0x%04X slots %s" % (f2, s2))


def k6():
    r = KnockRig(mode=1)
    r.start(4)
    r.set_mode(0)
    r.runrevs(2)
    m = r.x.m
    check("K6: Off releases the CC195 lines and retards nothing",
          (m.r16(DP3) & 0xFE) == 0 and (m.r16(DP8) & 1) == 0
          and (m.r16(P8) & 1) == 0 and all(r.kn8(i) == 0 for i in range(9)),
          "DP3 0x%04X DP8 0x%04X" % (m.r16(DP3), m.r16(DP8)))


def k7():
    r = KnockRig(mode=1)
    r.start(6)
    # stop the crank mid-cycle: no teeth for 120 ms of main loop - the
    # decoder (trg_service) and the knock service keep running
    for _ in range(120):
        r.clock += 1250
        r.t = (r.t + 1250) & 0xFFFF
        r.x.set_t1(r.t)
        r.model()
        r.x.call("trg_service")
        r.knock_hw(r.t, r.cum)
    st = r.kn8(F_ST)
    check("K7: a stopped crank leaves no window open (MF low, idle)",
          (r.x.m.r16(P8) & 1) == 0 and st == 0,
          "state %d, windows %d, aborted %d" % (st, r.och2(1026), r.och2(1032)))


def k8_wrap():
    r = KnockRig(mode=1, start_x10=900)       # cylinder 2: 618 + 90 = 708
    r.start(12)
    bad, _twin, full = attribution(r, r.win)
    wrapped = [w for w in r.win if w[4] >= 4 and w[0] == 1]
    check("K8: a window across 720 deg: right cylinder, right length",
          not bad and min(full) >= 3 and wrapped,
          "full-sync windows %s, cylinder 2's %d; %s"
          % (full, len(wrapped), "; ".join(bad[:3])))


def dwells(r, bit, since_clock):
    out, on, prev = [], None, 0
    for clock, ig, _ij, _ph, _st in r.rows:
        m = 1 << bit
        if ig & m and not prev & m:
            on = clock
        if prev & m and not ig & m and on is not None:
            if on >= since_clock:
                out.append((clock - on) / 1.25)
            on = None
        prev = ig
    return out


def k9_dwell_max():
    base = KnockRig(mode=2, **FAST)
    base.start(14)
    a = KnockRig(mode=2, ikr=knock_on(2, 2), **FAST)
    a.start(14)
    dref = dwells(base, 2, 0)
    dact = dwells(a, 2, 0)
    moved = spark_phys(a, 2, a.cum - 1440)[-1] - spark_phys(base, 2,
                                                            base.cum - 1440)[-1]
    # The retard delays dwell start and spark by the same angle, so the
    # dwell TIME holds. A retard step that lands between a dwell's start and
    # its spark stretches THAT one dwell by at most the step's time (the
    # spark is later, the charge began earlier) - bounded, and inside the
    # 1.5 x overdwell guard. Contract: every dwell equals the reference
    # (+/- 1 rig sample), except at most one per retard step, which may be
    # longer by no more than one step (3.0 deg at this speed).
    ref = sorted(dref)[len(dref) // 2]
    step_us = (STEP_Q_DEG / 6.0) * a.p / 1.25
    exact = [d for d in dact if abs(d - ref) <= 125.0]
    longer = [d for d in dact if d - ref > 125.0]
    check("K9 ACTIVE: cylinder 3's dwell holds while its spark is retarded",
          dref and dact and moved >= 2.0 and all(abs(d - ref) <= 1.0
                                                 for d in dref)
          and len(exact) >= len(dact) - 2
          and all(d - ref <= step_us + 125.0 for d in longer),
          "dwells %s us (ref %.0f), spark moved %.1f deg; a step "
          "mid-dwell may add <= %.0f us" % ([round(d) for d in dact], ref,
                                           moved, step_us))
    a.runrevs(16)                      # knocking every cycle: to the clamp
    q = a.och2(1094 + 2, 1)
    check("K9 ACTIVE: the retard stops at knockMaxQ (72 = 18.0 deg)",
          60 <= q <= 72 and a.och2(1050) <= 180,
          "q %d, knockRetardX10 %d" % (q, a.och2(1050)))


def k10_sync_loss():
    r = KnockRig(mode=2, ikr=knock_on(2, 2), **FAST)
    r.start(10)
    n0, loss0 = len(r.win), r.u("trg_synclost")
    # two missing edges in consecutive revolutions = a crank sync LOSS
    # (me711_trigger_scheduler_proof case D); one would be a correction
    r.rev(skip_at=20)
    r.rev(skip_at=20)
    r.rev()          # the second disagreement is judged on this rev's tooth
    n1, lost = len(r.win), r.u("trg_synclost") - loss0
    r.runrevs(10)
    during = r.win[n0:n1]
    longw = [w for w in during if (w[2] - w[1]) > LEN_X10 / 10.0 + 1.5]
    after = [w for w in r.win[n1:] if w[4] >= 4]
    bad, _twin, _full = attribution(r, after)
    check("K10: two missing edges -> crank sync lost",
          lost >= 1, "syncLossCount +%d" % lost)
    check("K10: nothing stays open across the loss (no window longer "
          "than set)", not longw,
          "%d windows during, %d too long" % (len(during), len(longw)))
    check("K10: after the new cycle sync every window is the right cylinder",
          len(after) >= 8 and not bad,
          "%d windows after re-sync; %s" % (len(after), "; ".join(bad[:3])))


def main() -> int:
    import me711_image as PI
    print("image %s" % PI.image().name)
    print("\n-- control: the exported geometry rotated by one cylinder --")
    ctrl = k1_k2(rotate=True)
    global CHECKS, FAILS
    CHECKS, FAILS = 0, 0
    print("  control %s" % ("FAILS as it must" if not ctrl
                            else "PASSED - the attribution check cannot tell"))
    print("\n-- K1/K2 windows, attribution, CC195 codes --")
    k1_k2()
    print("\n-- K3/K4 monitor vs active, per-cylinder retard, recovery --")
    k3_k4()
    print("\n-- K5 sensor faults --")
    k5()
    print("\n-- K6 off --")
    k6()
    print("\n-- K7 crank stops mid-window --")
    k7()
    print("\n-- K8 720-degree wrap --")
    k8_wrap()
    print("\n-- K9 dwell under retard, max retard --")
    k9_dwell_max()
    print("\n-- K10 sync loss and recovery --")
    k10_sync_loss()
    ok = FAILS == 0 and not ctrl
    print("\n%d checks, %d failed; control %s -> %s"
          % (CHECKS, FAILS, "fails" if not ctrl else "PASSES",
             "PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
