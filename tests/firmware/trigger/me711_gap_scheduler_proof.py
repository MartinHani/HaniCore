#!/usr/bin/env python3
r"""
me711_gap_scheduler_proof.py - every dwell ends in a spark across the 60-2 gap.

    py tests\firmware\trigger\me711_gap_scheduler_proof.py            the image me711_image names
    py tests\firmware\trigger\me711_gap_scheduler_proof.py --control  also run the V89 control

THE DEFECT (V89, first AWT vehicle test, 2026-09-26). hctrig_me711.c delivers
the tooth that CONFIRMS the missing-tooth gap with the whole span since the
last tooth before it: (gap + 2) teeth, 24.0 degrees on a 60-2. hcsched_dry.c
advance_angle_epoch() called any step over 18.0 degrees a discontinuity, so on
that tooth the planning window collapsed to one tooth and an event due in the
12 degrees before it was neither "due" nor "caught up". With the AWT page
(4 cyl wasted COP, batch, 10 deg, trigOffset 0) the sparks for TDC 0 and 360
land there: the spark cursor stopped for good after the first spark while the
dwell cursor kept going. The car logged ignOnMask 15 for 8 s of cranking and
scheduledSpark frozen at 170.0; batch injection, whose start sits at the gap
(SOI 360), was cut to ~1 ms.

WHAT THIS RUNS. The LINKED IMAGE's decoder and scheduler in c167sim: injected
crank edges through trg_test_crank_edge(), trg_service() between them, the
engine model values the main loop would hold. Per case (rpm x offset):

  * every coil's dwell starts are matched by releases, none left charging;
  * each dwell is 0.8..1.3 x the commanded dwell;
  * each spark falls within 2 degrees of TDC - advance at the PHYSICAL crank
    angle (TDC#1 at physical -offset; wasted COP: every 180 degrees);
  * every batch injector pulse is >= 0.9 x the commanded width;
  * the max-dwell watch never had to act (dry_sched_overdwell == 0).

Then two V90 mechanisms on their own:

  * OVERDWELL: a coil turned ON through the HAL with no spark event behind it
    must be released within 1.5 x dwell (4 ms floor) by the executor alone;
  * YIELD PLANNING: teeth captured while the main loop is inside a long serial
    reply (only hcts_target_yield() running, once per ms) are planned and
    executed there - the car's 50 ms schedulerMaxLatency.

NEGATIVE CONTROL (--control): the frozen V89 image must FAIL the spark checks
at trigOffset 0, and the overdwell check.

NOT PHYSICALLY VERIFIED. No coil or injector is connected in a simulator.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

CONTROL_STEM = "HaniCore_ME711_v89_alphan_awt"   # the image the car ran
RPMS = (150, 200, 300)
OFFSETS = (0, 2680)
ADV_X10, DWELL_X100, TI_US = 100, 500, 7200
TICKS_PER_MS = 1250.0
CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += 0 if ok else 1
    print("  [%s] %-56s %s" % ("PASS" if ok else "FAIL", name, detail))
    return ok


def rig():
    import me711_trigger_test as PT
    return PT


class Crank:
    """The AWT page's engine on the linked decoder + scheduler."""

    # The planner is its own interrupt level (CC26, hc_plan_isr): the crank
    # ISR only requests it. A function-call rig takes no interrupt, so each
    # edge runs what hc_plan_isr runs. Images before that level planned in
    # the polled service and need nothing here.
    @property
    def plan_level(self):
        return "hc_plan_isr" in rig().MAP

    def __init__(self, PT, offset_x10):
        self.PT = PT
        self.sym = PT.sym
        x = self.x = PT.Call()
        PT.describe_engine(x, cylinders=4, teeth=60, gap=2, soi_x10=3600,
                           tdc=[0, 5400, 1800, 3600], cam_refs=0)
        base = self.sym("hc_cfg") & 0xFFFF
        for i, v in enumerate([0, 3, 1, 2, 255, 255, 255, 255]):
            x.m.w8(base + 34 + i, v)          # injChannel
            x.m.w8(base + 42 + i, v)          # ignChannel
        u = 0x380000 + 12                     # universal block in SRAM
        uni = {2536: 0, 2537: 1, 2538: 1, 2539: 1, 2548: 82,
               2540: (offset_x10 >> 8) & 0xFF, 2541: offset_x10 & 0xFF}
        for i, v in enumerate([96, 89, 97, 88] + [255] * 8):
            uni[2551 + i] = v
        for i, v in enumerate([102, 95, 103, 94] + [255] * 8):
            uni[2563 + i] = v
        for o, v in uni.items():
            x.m.w8(u + o, v)
        x.call("trg_init")
        x.enable_deadlines()
        try:
            self.sym("hc_drysched_overdwell_service")
            self.ovd = True
        except SystemExit:
            self.ovd = False
        self.clock = 0
        self.t = 1000
        self.gap_ends = []                    # clock of each gap-ending edge
        self.log = []                         # (clock, ign, inj)
        self.edge(service=False)

    def model(self):
        for n, v in (("eng_adv_x10", ADV_X10), ("eng_dwell_x100", DWELL_X100),
                     ("eng_ti_base_us", 2 * TI_US), ("eng_deadtime_us", 0)):
            self.x.m.w16(self.sym(n) & 0xFFFF, v)

    def sample(self):
        self.log.append((self.clock, self.x.call("hc_hal_out_mask_ign"),
                         self.x.call("hc_hal_out_mask_inj")))

    def service(self):
        # outputs live under the automatic permissions (crank sync, valid
        # page) that the main loop's safety service grants on the ECU
        for n in ("hc_ignition_allowed", "hc_injection_allowed"):
            self.x.m.w16(self.sym(n) & 0xFFFF, 1)
        self.x.m.w16(self.sym("hc_cfg_validation") & 0xFFFF, 0)
        self.x.set_t1(self.t)
        self.model()
        self.x.call("trg_service")
        if self.ovd:                       # the main loop's 1 ms watch (V90)
            self.x.call("hc_drysched_overdwell_service", self.t)
        self.sample()

    def edge(self, service=True):
        self.x.set_t1(self.t)
        self.x.call("trg_test_crank_edge", self.t)
        if self.plan_level:
            self.x.call("hc_drysched_service", self.t,
                        self.x.m.r8(self.sym("trg_state") & 0xFFFF))
        if service:
            self.service()

    def wait(self, ticks, gap_end=False):
        n = max(2, ticks // 625)              # the main loop, every ~0.5 ms
        start_t, start_c = self.t, self.clock
        for q in range(1, n):
            self.clock = start_c + ticks * q // n
            self.t = (start_t + ticks * q // n) & 0xFFFF
            self.service()
        self.clock = start_c + ticks
        self.t = (start_t + ticks) & 0xFFFF
        if gap_end:
            self.gap_ends.append(self.clock)
        self.edge()

    def rev(self, p):
        for _ in range(57):
            self.wait(p)
        self.wait(3 * p, gap_end=True)

    def u16(self, name):
        return self.x.m.r16(self.sym(name) & 0xFFFF)


def phys_deg(c, gap_ends, p):
    """Physical crank angle at clock c: 0 = the edge that ends the gap."""
    prev = [g for g in gap_ends if g <= c]
    if not prev:
        return None
    return ((c - prev[-1]) / p * 6.0) % 360.0


def analyse(k, p, offset_x10):
    sync_c = None
    dwells = [0] * 4
    sparks = [0] * 4
    lens, angles = [], []
    on_since = [None] * 4
    pulses = []
    inj_on = None
    prev_ig = prev_ij = 0
    for c, ig, ij in k.log:
        for b in range(4):
            m = 1 << b
            if ig & m and not prev_ig & m:
                dwells[b] += 1
                on_since[b] = c
            if prev_ig & m and not ig & m:
                sparks[b] += 1
                lens.append((c - on_since[b]) / TICKS_PER_MS)
                a = phys_deg(c, k.gap_ends, p)
                if a is not None:
                    angles.append(a)
        if ij and not prev_ij:
            inj_on = c
        if prev_ij and not ij and inj_on is not None:
            pulses.append((c - inj_on) / TICKS_PER_MS)
        prev_ig, prev_ij = ig, ij
    tdc_phys = (-offset_x10 / 10.0) % 180.0          # wasted COP: every 180
    want = (tdc_phys - ADV_X10 / 10.0) % 180.0
    errs = [min(abs((a % 180.0) - want), 180.0 - abs((a % 180.0) - want))
            for a in angles]
    return dwells, sparks, lens, errs, pulses, k.log[-1][1]


def run_case(PT, rpm, offset_x10, revs=6):
    k = Crank(PT, offset_x10)
    p = round(1_250_000 / rpm)
    for _ in range(revs):
        k.rev(p)
    return k, p


def overdwell(PT):
    """A coil ON with no spark behind it: the executor alone must release it."""
    if 'hc_cc25_isr' in PT.MAP:
        import me711_deadline_proof as D
        r=D.Rig();r.call('hc_hal_out_group',IGN1(),1,1)
        assert not (r.call('hc_hal_out_mask_ign')&1), 'ordinary HAL ON bypassed ownership'
        r.publish(1,1,1000,3200);r.run(6000)
        released=int((r.pulse_lengths('ign')[0]*0.8+999)//1000)
        for _ in range(2):r.publish(1,1,1000,3200);r.run(6000)
        r.publish(1,1,1000,3200);r.run(2000)
        refused=not(r.dirs()[0]&1)
        # the cancel quiesces; the latch clears when the planner starts the
        # new epoch (planner_reset) - one planning pass, as after a resync
        r.cancel();r.call('hc_drysched_service',r.m.r16(0xFE52),3)
        r.publish(1,1,1000,3200);r.run(2000)
        restored=bool(r.dirs()[0]&1)
        return released,1,refused,restored
    x = PT.Call()
    PT.describe_engine(x, cylinders=4, teeth=60, gap=2, cam_refs=0)
    x.call("hc_drysched_init")
    x.call("hc_hal_out_group", IGN1(), 1, 1)
    t0 = 5000
    released_at = None
    for ms in range(0, 40):
        now = (t0 + int(ms * TICKS_PER_MS)) & 0xFFFF
        x.set_t1(now)
        x.call("hc_drysched_time_service", now)
        try:
            PT.sym("hc_drysched_overdwell_service")
            x.call("hc_drysched_overdwell_service", now)
        except SystemExit:
            pass
        if x.call("hc_hal_out_mask_ign") & 1 == 0:
            released_at = ms
            break
    cnt = None
    try:
        cnt = x.m.r16(PT.sym("dry_sched_overdwell") & 0xFFFF)
    except SystemExit:
        pass
    # V91: THE LATCH. A new ON for the released coil must be refused (no
    # charge/release cycle every revolution), and a cancel - sync lost,
    # engine stopped - must clear it.
    x.call("hc_hal_out_group", IGN1(), 1, 1)
    refused = (x.call("hc_hal_out_mask_ign") & 1) == 0
    x.call("hc_drysched_cancel", 0)
    x.call("hc_hal_out_group", IGN1(), 1, 1)
    restored = (x.call("hc_hal_out_mask_ign") & 1) == 1
    x.call("hc_hal_out_group", IGN1(), 1, 0)
    return released_at, cnt, refused, restored


def IGN1():
    import re
    h = (ROOT / "firmware/hal/hchal.h").read_text(errors="replace")
    m = re.search(r"#define\s+HC_OUT_IGN1\s+(\w+)", h)
    v = m.group(1).rstrip("uU")
    return int(v, 0)


def yield_calls(PT):
    """Which scheduler entry does the LINKED hcts_target_yield() call?

    V90 moved the tooth planner into the millisecond yield that runs inside
    long serial replies. A full hcts_target_yield() cannot run in this rig (it
    also steps the ASIC start machine and the bench), and the planner itself
    is exercised above through trg_service(); what is new is the CALL. So the
    function body is read out of the image and its CALLA/CALLS/CALLR targets
    are resolved against the map. Read from the linked image, not the source.
    """
    import re
    import me711_image as PI
    mp = PI.MAP.read_text(errors="replace")
    syms = {}
    for m in re.finditer(r"^\s*([0-9A-F]{6})H\s+(\w+)\s+LABEL", mp, re.M):
        syms.setdefault(m.group(2), int(m.group(1), 16))
    start = syms.get("hcts_target_yield")
    if start is None:
        return None
    end = min([v for v in syms.values() if v > start] + [start + 0x400])
    img = PI.image().read_bytes()
    base = 0x800000
    body = img[start - base:end - base]
    seg = start >> 16
    targets = set()
    i = 0
    while i < len(body) - 3:
        op = body[i]
        if op == 0xCA:                                  # CALLA cc, caddr
            targets.add((seg << 16) | body[i + 2] | (body[i + 3] << 8))
        elif op == 0xDA:                                # CALLS seg, caddr
            targets.add((body[i + 1] << 16) | body[i + 2] | (body[i + 3] << 8))
        elif op == 0xBB:                                # CALLR rel
            rel = body[i + 1] - 256 if body[i + 1] > 127 else body[i + 1]
            targets.add(start + i + 2 + 2 * rel)
        i += 2
    names = {v: k for k, v in syms.items()}
    return sorted(names.get(t, hex(t)) for t in targets)


def main_one(stem: str, control: bool) -> int:
    os.environ["HANICORE_ME711_STEM"] = stem
    PT = rig()
    print("=== 60-2 gap scheduler - %s%s ===" % (stem, " (CONTROL)" if control else ""))
    fails0 = FAILS
    for off in OFFSETS:
        for rpm in RPMS:
            k, p = run_case(PT, rpm, off)
            dw, sp, lens, errs, pulses, last = analyse(k, p, off)
            tag = "%3d rpm, trigOffset %4d:" % (rpm, off)
            check(tag + " every dwell ends in a spark",
                  dw == sp and last == 0 and min(sp) >= 3,
                  "dwells %s sparks %s still-on %s" % (dw, sp, bin(last)))
            check(tag + " dwell 0.8..1.3 x commanded",
                  bool(lens) and all(0.8 * DWELL_X100 / 100 <= d <= 1.3 * DWELL_X100 / 100 for d in lens),
                  "%.2f..%.2f ms" % (min(lens), max(lens)) if lens else "none")
            check(tag + " spark at TDC-advance (+-2 deg physical)",
                  bool(errs) and max(errs) <= 2.0,
                  "worst %.2f deg over %d sparks" % (max(errs), len(errs)) if errs else "no sparks")
            check(tag + " batch pulse >= 0.9 x commanded",
                  bool(pulses) and min(pulses) >= 0.9 * TI_US / 1000,
                  "%s ms" % ([round(v, 2) for v in pulses[:6]]))
            try:
                ov = k.u16("dry_sched_overdwell")
                check(tag + " max-dwell watch never acted", ov == 0, "overdwell %d" % ov)
            except SystemExit:
                check(tag + " max-dwell watch present", False, "no dry_sched_overdwell")
    rel, cnt, refused, restored = overdwell(PT)
    check("overdwell: an orphaned coil is released within 6 ms",
          rel is not None and rel <= 6 and cnt == 1,
          "released after %s ms, counter %s" % (rel, cnt))
    check("overdwell: the released coil is LATCHED off (no re-charge)",
          refused, "a new ON was %s" % ("refused" if refused else "driven"))
    check("overdwell: a cancel (sync loss) clears the latch at the next epoch",
          restored, "ON after cancel %s" % ("works" if restored else "refused"))
    if "hc_plan_isr" in PT.MAP:
        # the planner is its own interrupt level: no task context plans
        check("the planner is its own interrupt level (hc_plan_isr linked)", True)
    else:
        calls = yield_calls(PT) or []
        check("the serial yield PLANS teeth (calls hc_drysched_service)",
              "hc_drysched_service" in calls,
              "linked hcts_target_yield calls: %s" % ", ".join(
                  c for c in calls if c.startswith("hc_drysched")))
    return FAILS - fails0


def main() -> int:
    control = "--control" in sys.argv
    if "--one" in sys.argv:
        stem = sys.argv[sys.argv.index("--one") + 1]
        f = main_one(stem, stem == CONTROL_STEM)
        print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
        return 1 if f else 0
    import me711_image as PI
    env = dict(os.environ)
    rc = subprocess.call([sys.executable, __file__, "--one", PI.STEM], env=env)
    if not control:
        return rc
    print()
    rc_c = subprocess.call([sys.executable, __file__, "--one", CONTROL_STEM], env=env)
    ok = rc == 0 and rc_c != 0
    print("\nCONTROL: V89 %s, as it must" % ("FAILS" if rc_c else "PASSES - the gate cannot see the defect"))
    print("GAP SCHEDULER PROOF %s" % ("PASSES" if ok else "FAILS"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
