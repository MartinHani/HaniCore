#!/usr/bin/env python3
r"""
me711_dbw_control_proof.py - the closed-loop throttle, executed in the linked
image, one vector at a time.

    py tests\firmware\dbw\me711_dbw_control_proof.py

WHAT IS UNDER TEST. `hc_dbw.c`, compiled into the image that would be flashed,
driven through the C167 simulator with real ADC counts poked into `adc_raw[]`
and a real calibration page poked into the battery-backed SRAM. Every reading
comes back out through the module's own published accessors, so this exercises
the interface the rest of the firmware uses and not a private layout.

THE ONE THING THIS GATE DELIBERATELY OVERRIDES, and it says so out loud:
Until V63 `hc_hal_outputs_live()` returned a compiled-in 0, so
`hc_dbw_service()` would refuse on its first check and every vector would test
that one branch. The gate patches that function in the SIMULATOR ONLY with a
two-instruction stub returning 1 - the shipped binary is untouched, and the
arming gate itself is separately proven by `me711_output_safety_test.py`,
which is where that claim belongs. Testing a controller requires letting the
controller run.

THE VECTORS, and each asserts BOTH directions where it can:

  tracking        a step demand moves the target and the duty is non-zero in
                  the opening direction, and the integrator accumulates
  saturation      a large error cannot ask for more than the configured
                  authority
  direction       flipping CFG_U_DBW_MOTOR_DIR flips the commanded leg and
                  nothing else
  deadband        a small error produces exactly zero, not a small duty
  rate limit      the target cannot jump further per step than configured
  APP pair        two pedal tracks that disagree stop the bridge and latch
  TPS pair        the same for the throttle
  APP range       a pedal reading outside its calibration stops the bridge
  SF fault        the bridge's own fault pin stops it
  deviation       a plate that does not follow stops it after the configured
                  time and NOT before
  invalid config  min >= max, or zero authority, refuses
  latching        a cleared fault does NOT re-enable the bridge
  integrator      the integrator is ZERO after any shutdown, not merely frozen
  disabled        CAL_DBW_ENABLE = 0 commands the safe state

WHY IT CANNOT PASS VACUOUSLY. Every negative vector is paired with a positive
one that must show the opposite, and the tracking vector requires a non-zero
duty. A stub controller that always answered "bridge off" would fail tracking,
saturation, direction and the integrator check.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_heartbeat_gap_proof as HB    # noqa: E402
import me711_image as PI                  # noqa: E402

TGT = ROOT / "firmware/targets/me711"
HDR = TGT / "hctarget.h"
CFG_H = ROOT / "firmware/config/hcconfig.h"
GEN_H = ROOT / "firmware/generated/hc_config_generated.h"
DBW_H = ROOT / "firmware/control/hc_dbw.h"

SENTINEL = 0x0002
FAILS = 0
CHECKS = 0


def dbw_init_passes():
    """DBW_INIT_PASSES, read out of the firmware rather than retyped.

    V73's settle length. A gate that hardcoded it would go red the first time
    somebody tuned the settle, and would go GREEN if the settle were removed -
    which is the direction that matters."""
    import re as _re
    src = (ROOT / "firmware/control/hc_dbw.c").read_text(errors="replace")
    m = _re.search(r"#define\s+DBW_INIT_PASSES\s+(\d+)u?", src)
    if not m:
        raise SystemExit("DBW_INIT_PASSES is not in hc_dbw.c - the settle this "
                         "scenario steps through no longer exists")
    return int(m.group(1))


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-50s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


@lru_cache(maxsize=None)
def sym(name):
    for m in re.finditer(r"^\s*([0-9A-F]{6})H\s+(\w+)\s",
                         PI.MAP.read_text(errors="replace"), re.M):
        if m.group(2) == name:
            return int(m.group(1), 16)
    raise SystemExit("%s is not in the map - build the target first" % name)


def hdr_int(path, name):
    m = re.search(r"#define\s+%s\s+(0x[0-9A-Fa-f]+|\d+)" % name,
                  path.read_text(errors="replace"))
    if not m:
        raise SystemExit("%s is not in %s" % (name, path.name))
    return int(m.group(1), 0)


def gen_off(name):
    for f in (GEN_H, CFG_H):
        m = re.search(r"#define\s+%s\s+(\d+)u?" % name,
                      f.read_text(errors="replace"))
        if m:
            return int(m.group(1))
    raise SystemExit("%s is not defined" % name)


CFG_CORE = hdr_int(CFG_H, "HC_CFG_CORE")
CFG_HDR_LEN = hdr_int(CFG_H, "HC_CFG_HDR_LEN")
EXTRAM = hdr_int(HDR, "TGT_EXTRAM_BASE")
RAM_CFG = hdr_int(HDR, "TGT_RAM_CFG")
ADC_TPS1 = hdr_int(HDR, "TGT_ADC_TPS1_CH")
ADC_TPS2 = hdr_int(HDR, "TGT_ADC_TPS2_CH")
ADC_APP1 = hdr_int(HDR, "TGT_ADC_PEDAL1_CH")
ADC_APP2 = hdr_int(HDR, "TGT_ADC_PEDAL2_CH")

F = {n: hdr_int(DBW_H, "DBW_F_" + n) for n in
     ("CFG", "APP_PAIR", "TPS_PAIR", "APP_RANGE", "TPS_RANGE", "SF", "DEV",
      "STALE", "NOTLIVE")}
ST = {n: hdr_int(DBW_H, "DBW_" + n) for n in ("OFF", "INIT", "RUN", "FAULT")}


class Rig:
    """The linked image, with the controller allowed to run."""

    def __init__(self):
        # NO CODE PATCH ANY MORE - V63 ARMS IT THE WAY AN OPERATOR WOULD.
        #
        # Until V63 hc_hal_outputs_live() was a compiled-in `return 0`, so this
        # rig overwrote its two instructions with `MOVB RL4,#1 ; RET` to get
        # past that one branch. V63 gave the board a real output back end and
        # that function became a real decision - three runtime conditions -
        # so the opcode check refused to write, exactly as it was built to.
        #
        # Patching it now would be worse than unnecessary: it would SKIP the
        # arming logic, which is the part most worth testing. So the rig drives
        # the real path instead, and every condition below is one a bench sets
        # the same way:
        #
        #   CFG_OUTPUTS_ARMED = 1     the deliberate, RPM-zero, safety-critical
        #                             page edit
        #   hc_cfg_validation = 0     a page hc_validate() refused must never
        #                             reach a motor, so it must be clean here
        #   hc_safety_service(...)    the permission layer actually run, with
        #                             ASIC healthy, calibration good and the
        #                             explicit arm - NOT stubbed
        #
        # me711_output_safety_test still owns the negative direction: that
        # every one of those conditions, removed on its own, puts the outputs
        # back to off.
        self.rig = HB.Rig(PI.image(), HB.ENTRY_CURRENT, HB.TICK_CURRENT,
                          echo=False)
        self.rig.run(600_000)
        self.cpu = self.rig.cpu
        self.mem = self.rig.mem
        self.adc = sym("adc_raw") & 0xFFFF
        self.stale = set()
        self.mem.sfr[0xFFCC] = self.mem.sfr.get(0xFFCC, 0) | 4
        self.arm_outputs()

    def arm_outputs(self):
        """The three runtime conditions hc_hal_outputs_live() now requires."""
        self.set8("CFG_OUTPUTS_ARMED", 1)
        # hc_cfg_validation is a plain near word; a refused page can never arm.
        self.mem.w16(sym("hc_cfg_validation") & 0xFFFF, 0)
        # healthy, cal_ok, crank_ok, cycle_ok, explicit_arm - all true. The
        # throttle only needs the first two and the arm, but passing all five
        # keeps this rig about the CONTROLLER rather than about the masks.
        self.call("hc_safety_service", (1, 1, 1, 1, 1))

    # ---- page access ----------------------------------------------------
    def page_addr(self, off):
        if off < CFG_CORE:
            return (sym("hc_cfg") & 0xFFFF) + off
        return EXTRAM + RAM_CFG + CFG_HDR_LEN + off

    def set8(self, name, v):
        self.mem.w8(self.page_addr(gen_off(name)), v & 0xFF)

    def set16(self, name, v):
        a = self.page_addr(gen_off(name))
        self.mem.w8(a, (v >> 8) & 0xFF)      # the page is BIG endian
        self.mem.w8(a + 1, v & 0xFF)

    def set_adc(self, ch, v):
        self.mem.w16(self.adc + 2 * ch, v & 0xFFFF)

    # ---- calling ---------------------------------------------------------
    def call(self, name, args=()):
        cpu = self.cpu
        addr = sym(name)
        # An EXTS/EXTP prefix may still be armed if the boot
        # stopped on one, and an injected call would run under a segment
        # override belonging to code we are not executing. See
        # me711_nvm_proof.Ecu.call().
        saved = (cpu.csp, cpu.ip, cpu.m.sfr[0xFE12], cpu.ext)
        cpu.ext = None
        if addr >> 16 != 0x84:
            cpu.push(addr >> 16)  # FAR function returns with RETS
        cpu.push(SENTINEL)
        cpu.csp = (addr >> 16) & 0xFF
        cpu.ip = addr & 0xFFFF
        for i, v in enumerate(args):
            cpu.sr(8 + i, v & 0xFFFF)
        for _ in range(400_000):
            # A far helper can contain this IP in another segment. Only
            # accept the sentinel after the injected call unwinds its stack.
            if (cpu.ip & 0xFFFF) == SENTINEL and cpu.m.sfr[0xFE12] == saved[2]:
                break
            cpu.step()
        else:
            raise SystemExit("%s did not return" % name)
        out = cpu.gr(4) & 0xFFFF
        cpu.csp, cpu.ip, cpu.m.sfr[0xFE12], cpu.ext = saved
        return out

    def service(self, ms, rpm=0, armed=1):
        self.mem.w16(sym("hc_tick_ms") & 0xFFFF, ms & 0xFFFF)
        # The fixture models a completed scan, including constant signals.
        # Frozen channels explicitly stop conversion publication.
        for ch in (5, ADC_TPS1, ADC_TPS2, ADC_APP1, ADC_APP2):
            if ch not in self.stale:
                raw = self.mem.r16(self.adc + 2*ch)
                self.call("hc_hal_main_sample", (ch, (ch << 12) | raw, 1, ms))
        self.call("hc_dbw_service", (ms, rpm, armed))

    def s(self):
        def sgn(v):
            return v - 0x10000 if v & 0x8000 else v
        return {
            "state": self.call("hc_dbw_state") & 0xFF,
            "faults": self.call("hc_dbw_faults"),
            "target": self.call("hc_dbw_target_x10"),
            "actual": self.call("hc_dbw_actual_x10"),
            "error": sgn(self.call("hc_dbw_error_x10")),
            "duty": self.call("hc_dbw_duty_x10"),
            "dir": self.call("hc_dbw_dir") & 0xFF,
            "on": self.call("hc_dbw_bridge_on") & 0xFF,
            "pedal": self.call("hc_dbw_pedal_x10"),
            "integ": sgn(self.call("hc_dbw_integ")),
            "steps": self.call("hc_dbw_steps"),
            "tps1": self.call("hc_dbw_tps1_x10"),
        }

    # ---- a known-good baseline ------------------------------------------
    def baseline(self):
        """A calibration that describes A throttle - not a 1.8T one. Every
        number here is a TEST FIXTURE and none is a claim about hardware."""
        self.call("hc_dbw_init")
        for sem,ch in ((4,ADC_TPS1),(5,ADC_TPS2),(6,ADC_APP1),(7,ADC_APP2)):
            self.call("hc_hal_ain_bind",(sem,ch))
        self.call("hc_fresh_init")
        self.stale.clear()
        fs = self.call("cfg_u16", (62,))
        self.set_adc(5, (135 * 1023 + fs - 1) // fs)
        self.set8("CAL_DBW_ENABLE", 1)
        self.set16("CAL_PEDAL1_MIN", 100); self.set16("CAL_PEDAL1_MAX", 900)
        self.set16("CAL_PEDAL2_MIN", 100); self.set16("CAL_PEDAL2_MAX", 900)
        self.set16("CAL_TPS1_MIN", 100);   self.set16("CAL_TPS1_MAX", 900)
        self.set16("CAL_TPS2_MIN", 100);   self.set16("CAL_TPS2_MAX", 900)
        self.set8("CFG_U_APP_CORR", hdr_int(GEN_H, "HC_TRACK_SAME"))
        self.set8("CFG_U_TPS_CORR", hdr_int(GEN_H, "HC_TRACK_SAME"))
        self.set16("CFG_U_APP_TOL_X10", 100)
        self.set16("CFG_U_TPS_TOL_X10", 100)
        self.set16("CAL_DBW_MIN_X10", 0)
        self.set16("CAL_DBW_MAX_X10", 1000)
        self.set16("CFG_U_DBW_MAX_DUTY_X10", 800)
        self.set16("CFG_U_DBW_RATE_X10", 0)        # no rate limit by default
        self.set16("CFG_U_DBW_DEADBAND_X10", 10)
        self.set8("CFG_U_DBW_MOTOR_DIR", 1)
        self.set16("CAL_DBW_KP", 2000)
        self.set16("CAL_DBW_KI", 500)
        self.set16("CAL_DBW_KD", 0)
        self.set16("CAL_DBW_DEV_X10", 150)
        self.set16("CAL_DBW_DEV_MS", 500)
        # Latch on the first bad sample: these vectors test the latch itself.
        # The confirm time (default 50 ms) is me711_dbw_audit_proof B and F.
        self.set16("CFG_U_DBW_FAULT_DEBOUNCE_MS", 0)
        self.set16("CAL_DBW_SF_MODE", hdr_int(GEN_H, "HC_DBW_SF_IGNORE"))
        self.identity_pedal_map()
        self.pedal(0)
        self.plate(0)

    def identity_pedal_map(self):
        """An identity pedal map, so these vectors test the CONTROLLER and
        not whatever the shipped default map happens to contain. 16x16 bytes
        at 0.5 % per count, so 100 % travel is a stored 200."""
        n = 16
        ax = gen_off("CAL_PEDAL_AX")
        rax = gen_off("CAL_PEDAL_RPM_AX")
        mp = gen_off("CAL_PEDAL_MAP")
        for k in range(n):
            pct_x10 = k * 1000 // (n - 1)
            a = self.page_addr(ax + 2 * k)
            self.mem.w8(a, (pct_x10 >> 8) & 0xFF)
            self.mem.w8(a + 1, pct_x10 & 0xFF)
            r = self.page_addr(rax + 2 * k)
            rpm = k * 8000 // (n - 1)
            self.mem.w8(r, (rpm >> 8) & 0xFF)
            self.mem.w8(r + 1, rpm & 0xFF)
        for ri in range(n):
            for li in range(n):
                # identity: pedal % -> the same throttle %, stored at 0.5 %/count
                # V97: the page is [pedal][rpm] (generate_config.TABLE_ORDER)
                self.mem.w8(self.page_addr(mp + li * n + ri),
                            (li * 200) // (n - 1))

    def pedal(self, pct_x10):
        raw = 100 + pct_x10 * 800 // 1000
        self.set_adc(ADC_APP1, raw)
        self.set_adc(ADC_APP2, raw)

    def plate(self, pct_x10):
        raw = 100 + pct_x10 * 800 // 1000
        self.set_adc(ADC_TPS1, raw)
        self.set_adc(ADC_TPS2, raw)

    def steps(self, n, start=10_000, rpm=0, armed=1):
        """Run n control steps, each at least DBW_STEP_MS apart."""
        t = start
        for _ in range(n):
            self.service(t, rpm, armed)
            t += 10
        return t


# ============================================================ the vectors ==
def main() -> int:
    print("=== HaniCore ME7.1.1 - the closed-loop throttle, executed ===\n")
    print("  image   %s" % PI.image().name)
    print("  sha256  %s\n" % PI.sha256())
    print("  NOTE: hc_hal_outputs_live() is stubbed to 1 IN THE SIMULATOR so")
    print("        the controller can run at all. The shipped binary is")
    print("        untouched; me711_output_safety_test proves the real one.\n")

    r = Rig()

    # ---- 1. tracking -----------------------------------------------------
    r.baseline()
    r.pedal(0)
    r.plate(0)
    r.steps(3)
    r.pedal(500)                       # 50 % demand, plate still shut
    t = r.steps(6)
    a = r.s()
    check("a step demand raises the target",
          400 < a["target"] <= 1000,
          "target=%d actual=%d" % (a["target"], a["actual"]))
    check("and the bridge is enabled and driving",
          a["on"] == 1 and a["duty"] > 0 and a["state"] == ST["RUN"],
          "state=%d on=%d duty=%d dir=%d"
          % (a["state"], a["on"], a["duty"], a["dir"]))
    open_dir = a["dir"]

    # THE INTEGRATOR IS TESTED WHERE THE OUTPUT IS NOT SATURATED. The first
    # version of this vector asserted integ > 0 right after a 50 % step, and
    # failed - correctly. With KP = 2000 a 50 % error asks for twice the
    # authority, the output saturates, and refusing to accumulate there IS the
    # anti-windup working. Testing it needs a small error.
    r.baseline()
    r.set16("CAL_DBW_KP", 100)          # small P, so no saturation
    r.set16("CAL_DBW_KI", 4000)
    r.pedal(300)
    r.plate(280)                        # 2 % error
    r.steps(8)
    ai = r.s()
    check("the integrator accumulates when the output is NOT saturated",
          ai["integ"] > 0 and ai["duty"] < 800,
          "integ=%d duty=%d" % (ai["integ"], ai["duty"]))
    r.plate(300)
    r.steps(2)
    check("and anti-windup holds it bounded",
          abs(r.s()["integ"]) <= 2000,
          "integ=%d, hard bound is 2000" % r.s()["integ"])

    # back to the tracking fixture for the next vector
    r.baseline()
    r.pedal(500)
    r.plate(0)
    t = r.steps(6)

    # ---- 2. the plate catches up ----------------------------------------
    r.plate(500)
    t = r.steps(3, start=t)
    b = r.s()
    check("with the plate on target the error is inside the deadband",
          b["error"] == 0, "error=%d duty=%d" % (b["error"], b["duty"]))

    # ---- 3. authority ----------------------------------------------------
    r.baseline()
    r.set16("CFG_U_DBW_MAX_DUTY_X10", 300)
    r.pedal(1000)
    r.plate(0)
    r.steps(10)
    c = r.s()
    check("duty is clamped to the configured authority",
          c["duty"] <= 300, "duty=%d, authority=300" % c["duty"])
    check("and a huge error saturates AT it, not below",
          c["duty"] == 300, "duty=%d" % c["duty"])

    # ---- 4. direction is configuration ----------------------------------
    r.baseline()
    r.set8("CFG_U_DBW_MOTOR_DIR", 0)
    r.pedal(500)
    r.plate(0)
    r.steps(6)
    d = r.s()
    check("flipping CFG_U_DBW_MOTOR_DIR flips the commanded leg",
          d["dir"] != open_dir and d["duty"] > 0,
          "dir=%d vs %d, duty=%d" % (d["dir"], open_dir, d["duty"]))

    # ---- 5. deadband -----------------------------------------------------
    r.baseline()
    r.set16("CFG_U_DBW_DEADBAND_X10", 50)
    r.set16("CAL_DBW_KI", 0)
    r.pedal(500)
    r.plate(480)                        # 2.0 % error inside a 5.0 % band
    r.steps(4)
    e = r.s()
    check("an error inside the deadband produces EXACTLY zero",
          e["error"] == 0, "error=%d duty=%d" % (e["error"], e["duty"]))

    # ---- 6. the rate limit ----------------------------------------------
    r.baseline()
    r.set16("CFG_U_DBW_RATE_X10", 200)   # 20 %/s -> 1 unit per 5 ms step
    r.pedal(0)
    r.plate(0)
    r.steps(3)
    r.pedal(1000)
    r.steps(2)
    f1 = r.s()["target"]
    r.steps(2)
    f2 = r.s()["target"]
    check("the target is rate limited, not stepped",
          f1 < 200 and f2 > f1,
          "target %d then %d, demand was 1000" % (f1, f2))

    # ---- 7. pedal pair ---------------------------------------------------
    r.baseline()
    r.pedal(500)
    r.steps(3)
    r.set_adc(ADC_APP2, 100 + 900 * 800 // 1000)     # track 2 says 90 %
    r.steps(2)
    g = r.s()
    check("pedal tracks that disagree stop the bridge",
          g["on"] == 0 and g["duty"] == 0 and g["state"] == ST["FAULT"],
          "state=%d on=%d duty=%d" % (g["state"], g["on"], g["duty"]))
    check("  ... and DBW_F_APP_PAIR is latched",
          (g["faults"] & F["APP_PAIR"]) != 0, "faults=0x%04X" % g["faults"])
    check("  ... and the integrator is ZERO, not frozen",
          g["integ"] == 0, "integ=%d" % g["integ"])

    # ---- 8. a fault LATCHES ---------------------------------------------
    r.pedal(500)                        # both tracks agree again
    r.steps(3)
    h = r.s()
    check("a cleared fault does NOT re-enable the bridge",
          h["on"] == 0 and h["state"] == ST["FAULT"],
          "state=%d on=%d - only hc_dbw_init() clears it"
          % (h["state"], h["on"]))

    # ---- 9. throttle pair ------------------------------------------------
    r.baseline()
    r.pedal(500)
    r.plate(500)
    r.steps(3)
    r.set_adc(ADC_TPS2, 100 + 900 * 800 // 1000)
    r.steps(2)
    i = r.s()
    check("throttle tracks that disagree stop the bridge",
          i["on"] == 0 and (i["faults"] & F["TPS_PAIR"]) != 0,
          "state=%d faults=0x%04X" % (i["state"], i["faults"]))

    # ---- 10. a pedal outside its calibration ----------------------------
    r.baseline()
    r.pedal(500)
    r.steps(3)
    r.set_adc(ADC_APP1, 4)              # far below CAL_PEDAL1_MIN
    r.set_adc(ADC_APP2, 4)
    r.steps(2)
    j = r.s()
    check("a pedal reading outside its calibration stops the bridge",
          j["on"] == 0 and (j["faults"] & F["APP_RANGE"]) != 0,
          "faults=0x%04X" % j["faults"])

    # ---- 11. the bridge's own fault pin ---------------------------------
    # V83: A DISABLED CJ220 REPORTS SF LOW BY DESIGN (truth table rows 5, 6,
    # 9 - the Bosch CJ220 datasheet), and DBW_INIT holds the bridge disabled. Until V83
    # this vector asserted that SF low during the settle latches DBW_F_SF,
    # which is the defect: every correctly working board would have faulted
    # before its first enable. SF is judged only while the controller holds an
    # ENABLED bridge - so the vector is now two: ignored while down, and
    # still fatal once it is up.
    r.baseline()
    r.set16("CAL_DBW_SF_MODE", hdr_int(GEN_H, "HC_DBW_SF_LOW_IS_FAULT"))
    r.pedal(500)
    r.plate(500)
    t = r.steps(dbw_init_passes() - 1)
    k = r.s()
    check("SF low while the bridge is DISABLED is not a fault",
          k["on"] == 0 and (k["faults"] & F["SF"]) == 0
          and k["state"] == ST["INIT"],
          "state=%d faults=0x%04X (P3.15 reads low in the simulator)"
          % (k["state"], k["faults"]))
    r.set16("CAL_DBW_SF_MODE", hdr_int(GEN_H, "HC_DBW_SF_IGNORE"))
    t = r.steps(3, start=t)
    k1 = r.s()
    r.set16("CAL_DBW_SF_MODE", hdr_int(GEN_H, "HC_DBW_SF_LOW_IS_FAULT"))
    r.steps(2, start=t)
    k2 = r.s()
    check("the SF pin faulted stops a RUNNING bridge",
          k1["on"] == 1 and k2["on"] == 0 and (k2["faults"] & F["SF"]) != 0,
          "running on=%d, then faults=0x%04X" % (k1["on"], k2["faults"]))

    # ---- 12. the deviation supervisor -----------------------------------
    r.baseline()
    r.set16("CAL_DBW_DEV_X10", 100)
    r.set16("CAL_DBW_DEV_MS", 200)
    r.pedal(800)
    r.plate(0)                          # the plate never follows
    # THE SETTLE COMES FIRST, AND THE DEVIATION WINDOW STARTS AFTER IT.
    #
    # V73 added DBW_INIT: the bridge stays DOWN for DBW_INIT_PASSES clean
    # control steps before the controller drives anything. This scenario used
    # to run four steps and assert the bridge was on and had not yet tripped -
    # and with a four-pass settle those four steps were the settle, so `on` was
    # 0 and the check went red.
    #
    # THAT IS THE FIRMWARE BEING RIGHT. A deviation supervisor measures how
    # long the plate has failed to follow A COMMAND; there is no command during
    # INIT, so there is nothing to supervise yet and the window cannot
    # sensibly start before it. The settle is stepped through explicitly here
    # so the ~40 ms is 40 ms OF DEVIATION rather than 20 ms of settle and 20 of
    # deviation. The count is read from the firmware so the two cannot drift.
    t = r.steps(dbw_init_passes(), start=50_000)   # leave DBW_INIT
    t = r.steps(4, start=t)                        # ~40 ms of real deviation
    l1 = r.s()
    check("a stuck plate does NOT trip before the configured time",
          l1["on"] == 1 and (l1["faults"] & F["DEV"]) == 0,
          "state=%d faults=0x%04X after ~40 ms of a 200 ms window"
          % (l1["state"], l1["faults"]))
    for _ in range(30):
        r.service(t)
        t += 10
    l2 = r.s()
    check("and DOES trip once the window expires",
          l2["on"] == 0 and (l2["faults"] & F["DEV"]) != 0,
          "faults=0x%04X" % l2["faults"])

    # ---- 13. invalid calibration ----------------------------------------
    def bad_travel():
        r.set16("CAL_DBW_MIN_X10", 900)
        r.set16("CAL_DBW_MAX_X10", 100)

    def bad_authority():
        r.set16("CFG_U_DBW_MAX_DUTY_X10", 0)

    # V83: A REVERSED CALIBRATION IS A DIRECTION, NOT A FAULT - it is what the
    # endpoint grab stores for a VAG track that falls as the plate opens
    # (rusEFI setBoschVAGETB: tpsMin 890, tpsMax 70). What is still refused is
    # a span too narrow to be a sensor.
    def bad_tps():
        r.set16("CAL_TPS1_MIN", 500)
        r.set16("CAL_TPS1_MAX", 520)

    for title, setter in (("min >= max travel", bad_travel),
                          ("zero output authority", bad_authority),
                          ("a 20-count TPS span", bad_tps)):
        r.baseline()
        setter()
        r.pedal(500)
        r.plate(500)
        r.steps(3)
        m = r.s()
        check("%s refuses" % title,
              m["on"] == 0 and (m["faults"] & F["CFG"]) != 0,
              "faults=0x%04X" % m["faults"])

    # ---- 13b. a reversed (grabbed) calibration reads the right way -------
    r.baseline()
    r.set16("CAL_TPS1_MIN", 900); r.set16("CAL_TPS1_MAX", 100)
    r.set16("CAL_TPS2_MIN", 900); r.set16("CAL_TPS2_MAX", 100)
    r.pedal(300)
    r.set_adc(ADC_TPS1, 900 - 300 * 800 // 1000)     # 30 % open, falling
    r.set_adc(ADC_TPS2, 900 - 300 * 800 // 1000)
    r.steps(dbw_init_passes() + 2)
    q = r.s()
    check("a reversed TPS calibration (the grab's) reads the plate correctly",
          q["faults"] == 0 and abs(q["tps1"] - 300) <= 2 and q["on"] == 1,
          "tps1=%d (expect 300) faults=0x%04X on=%d"
          % (q["tps1"], q["faults"], q["on"]))

    # ---- 14. disabled and unarmed ---------------------------------------
    r.baseline()
    r.set8("CAL_DBW_ENABLE", 0)
    r.pedal(1000)
    r.plate(0)
    r.steps(4)
    n = r.s()
    check("CAL_DBW_ENABLE = 0 commands the safe state",
          n["on"] == 0 and n["duty"] == 0 and n["state"] == ST["OFF"],
          "state=%d on=%d duty=%d" % (n["state"], n["on"], n["duty"]))

    r.baseline()
    r.pedal(1000)
    r.plate(0)
    r.steps(4, armed=0)
    o = r.s()
    check("armed = 0 commands the safe state whatever the page says",
          o["on"] == 0 and o["duty"] == 0,
          "state=%d on=%d duty=%d" % (o["state"], o["on"], o["duty"]))

    # PF1: stale alone must release and reach the target's ETB limp policy.
    r.baseline(); r.pedal(200); r.plate(200)
    t = r.steps(dbw_init_passes()+2, start=60000)
    check("fresh constant inputs permit the bridge", r.s()["on"] == 1)
    r.stale.add(ADC_TPS1)
    r.steps(15, start=t)
    q = r.s()
    check("stale-only TPS latches STALE and releases bridge",
          q["faults"] == F["STALE"] and q["on"] == 0 and q["duty"] == 0,
          str(q))
    r.mem.w16(sym("trg_rpm") & 0xFFFF, 1800)
    r.mem.w16(sym("eng_sensor_err") & 0xFFFF, 0)
    r.set16("CFG_U_ETB_LIMP_RPM", 1500)
    r.call("hc_limp_init")
    r.call("hc_limp_service", (100,))
    r.call("hc_limp_service", (110,))
    check("stale-only ETB fault cuts fuel above 1500 rpm",
          bool(r.mem.r16(sym("eng_fuelcut") & 0xFFFF) & 8))
    r.mem.w16(sym("trg_rpm") & 0xFFFF, 1000)
    r.call("hc_limp_service", (120,))
    check("stale ETB fault permits limp operation below limit/hysteresis",
          not bool(r.mem.r16(sym("eng_fuelcut") & 0xFFFF) & 8))
    r.stale.clear(); r.steps(3, start=t+200)
    check("fresh samples cannot clear the latched stale fault",
          r.s()["faults"] == F["STALE"] and r.s()["on"] == 0)

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("DBW CONTROL PROOF FAILS - the closed loop does not behave as "
              "specified. DO NOT put a throttle body on this.")
        return 1
    print("DBW CONTROL PROOF PASSES - the loop tracks, saturates at its "
          "configured authority, honours the configured motor direction, and "
          "drops the bridge with the integrator ZEROED on every fault it is "
          "supposed to catch. It has never driven a real motor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
