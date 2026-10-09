#!/usr/bin/env python3
r"""me711_vvt_proof.py - cam phase control (VVT) on the LINKED IMAGE (c167sim).

    py tests\firmware\engine\me711_vvt_proof.py

The core (firmware/control/hcvvt.c) is host-proven with its controls
(tests/host/test_hcvvt_host.py). This gate runs the image's hc_vvt_service()
(hcvvt711.c, FCODE) with the page, the trigger's cam state (hccam_bank[b]
.cls / .sync_dev_x10, HC_VVT711.syncs[b]) and the engine values it reads,
and judges what reaches the MAIN CPU's PWM units (POUT0 -> cavity 115,
POUT1 -> cavity 120) and the telemetry (OCH 1112..1131). c167sim does not
generate the PWM waveform: the gate reads the registers the unit would run
from (PWMCON0/1, PPx, PWx, DP7, P7), resolved from reg167.h.

  V1  Off: both units stopped and released (DP7 input), duty 0
  V2  SWITCH, cam 1 on 115: target > 0 -> ON duty at the page frequency
      (PP0 = 62500/f*10 - 1, PW0 = duty x period), cam 2's unit untouched;
      target 0 -> released
  V3  CLOSED, cam 2 on 120: target -> position -> error -> duty; the error
      sign drives the duty the right way; duty clamped to min..max; invert
      reverses the direction; cam 1 (Off) stays released
  V4  no fresh position: duty 0 at once, NO CAM POSITION latched after
      2 x vvtFbMs, released; the latch holds until the engine stops
  V5  stuck: |error| > vvtErrMax for vvtErrMs -> STUCK / SLOW, released
  V6  the tooth outside the VVT authority (cls OFFSET) -> OUT OF AUTHORITY
  V7  enabled with no stage routed -> NO STAGE ROUTED, no unit touched
  V8  rpm 0 re-arms every latch
  V9  the route moved while the unit ran: the old unit is released
      (CONTROL: before the fix in hc_vvt_service the old unit kept its duty)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_trigger_test as T                       # noqa: E402

GEN = (ROOT / "firmware/generated/hc_config_generated.h").read_text()
pass  # (bootstrap above)
import hcpaths as HCP  # noqa: E402
_REG = HCP.REG167.read_text(errors="replace")
FAIL = 0

VV = 0x380000 + 0x1C00          # TGT_RAM_VVT
OCH2 = 0x380000 + 0x1800        # TGT_RAM_OCH2 = OCH 1024
# hc_vvt711_t (hcvvt711.h): hcvvt_t v[2] (14 bytes each), then syncs[2]
VV_SYNCS, VV_UNIT_ON = 28, 58
# hccam_t (hccam.h), C166 word alignment: cls @67, sync_dev_x10 @72, 84 bytes
CAM_CLS, CAM_DEV, CAM_SIZE = 67, 72, 84
HCCAM_C_SAME, HCCAM_C_OFFSET = 1, 5
S_OFF, S_NOPOS, S_SWITCH, S_CLOSED = 0x01, 0x04, 0x08, 0x10


def sfr(n):
    return int(re.search(r"^\s*sfr\s+%s\s*=\s*(0x[0-9A-Fa-f]+);" % n,
                         _REG, re.M).group(1), 16)


PWMCON0, PWMCON1 = sfr("PWMCON0"), sfr("PWMCON1")
PP0, PP1, PW0, PW1 = sfr("PP0"), sfr("PP1"), sfr("PW0"), sfr("PW1")
DP7 = sfr("DP7")


def off(name):
    return int(re.search(r"#define\s+%s\s+(\d+)u?\b" % name, GEN).group(1))


def check(name, ok, detail=""):
    global FAIL
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<66} {detail}")
    FAIL += not ok
    return ok


class Rig:
    def __init__(self):
        x = self.x = T.Call()
        self.ms = 0
        for b in (0, 1):
            self.pg8("CFG_U_VVT_MODE", 0, b)
            self.pg8("CFG_U_VVT_INVERT", 0, b)
            self.pg16("CFG_U_VVT_KP", 300, b)          # 3.00
            self.pg16("CFG_U_VVT_KI", 20, b)
            self.pg16("CFG_U_VVT_KD", 0, b)
            self.pg16("CFG_U_VVT_DUTY_MIN", 100, b)    # 10.0 %
            self.pg16("CFG_U_VVT_DUTY_MAX", 900, b)    # 90.0 %
            self.pg16("CFG_U_VVT_DUTY_ON", 700, b)     # 70.0 %
        self.pg16("CFG_U_VVT_FREQ_HZ", 250)
        self.pg16("CFG_U_VVT_MIN_RPM", 500)
        self.pg16("CFG_U_VVT_MIN_CLT", 10000)          # 0 C
        self.pg16("CFG_U_VVT_DELAY_MS", 0)
        self.pg16("CFG_U_VVT_ERR_MAX", 100)            # 10.0 deg
        self.pg16("CFG_U_VVT_ERR_MS", 1000)
        self.pg16("CFG_U_VVT_FB_MS", 200)
        for i in range(8):
            self.pg16("CFG_U_VVT_RPM_AX", 1000 * (i + 1), i)
            self.pg16("CFG_U_VVT_LOAD_AX", 200 * i, i)
        self.target(0, 0)
        self.target(1, 0)
        self.pg8("CFG_U_PIN_CAM1_SOL", 115)
        self.pg8("CFG_U_PIN_CAM2_SOL", 120)
        self.ram16("trg_rpm", 2000)
        self.ram16("eng_clt_dc", 10900)                # 90 C
        self.ram16("eng_rl_x10", 500)
        x.m.w16(PWMCON0, 0)
        x.m.w16(PWMCON1, 0)
        x.m.w16(DP7, 0)
        self.cam_base = T.sym("hccam_bank")
        for b in (0, 1):
            self.cam_state(b, HCCAM_C_SAME, 0)
        x.call("hc_vvt_init")
        x.call("hc_vvt_service", 0)

    # ---- page / ram ---------------------------------------------------------
    def pg8(self, name, v, i=0):
        self.x.m.w8(T.UNI_BASE + off(name) + i, v & 0xFF)

    def pg16(self, name, v, i=0):
        a = T.UNI_BASE + off(name) + 2 * i
        self.x.m.w8(a, (v >> 8) & 0xFF)                # the page is big endian
        self.x.m.w8(a + 1, v & 0xFF)

    def target(self, b, v):
        for i in range(64):
            self.pg16("CFG_U_VVT_TARGET%d" % (b + 1), v, i)

    def ram16(self, name, v):
        self.x.m.w16(T.sym(name) & 0xFFFF, v & 0xFFFF)

    def cam_state(self, b, cls, dev_x10):
        a = (self.cam_base + CAM_SIZE * b) & 0xFFFF
        self.x.m.w8(a + CAM_CLS, cls)
        self.x.m.w16(a + CAM_DEV, dev_x10 & 0xFFFF)

    # ---- run ----------------------------------------------------------------
    def run(self, ms, fresh=(True, True)):
        """ms of main loop in 20 ms service steps; a fresh cam = tooth 0
        identified again every step (the trigger's syncs[] counter)"""
        for _ in range(max(1, ms // 20)):
            for b in (0, 1):
                if fresh[b]:
                    a = VV + VV_SYNCS + 2 * b
                    self.x.m.w16(a, (self.x.m.r16(a) + 1) & 0xFFFF)
            self.ms = (self.ms + 20) & 0xFFFF
            self.x.call("hc_vvt_service", self.ms)

    def och(self, b, k):
        a = OCH2 + 1112 + 10 * b + 2 * k - 1024
        v = (self.x.m.r8(a) << 8) | self.x.m.r8(a + 1)
        return v - 0x10000 if k in (0, 1, 2) and v >= 0x8000 else v

    def cam(self, b):
        st = self.och(b, 4)
        return {"target": self.och(b, 0), "pos": self.och(b, 1),
                "err": self.och(b, 2), "duty": self.och(b, 3),
                "state": st & 0xFF, "fault": (st >> 8) & 0x7F,
                "unit": (st >> 15) & 1}

    def unit(self, u):
        m = self.x.m
        bit = 1 << u
        return {"run": bool(m.r16(PWMCON0) & bit),
                "pin": bool(m.r16(PWMCON1) & bit) and bool(m.r16(DP7) & bit),
                "pp": m.r16(PP1 if u else PP0), "pw": m.r16(PW1 if u else PW0),
                "on": m.r8(VV + VV_UNIT_ON + u)}

    def released(self, u):
        s = self.unit(u)
        return not s["run"] and not s["pin"] and not s["on"]


def main() -> int:
    import me711_image as PI
    print("image %s" % PI.image().name)

    print("\n-- V1 off --")
    r = Rig()
    r.run(200)
    c0, c1 = r.cam(0), r.cam(1)
    check("V1: Off - both units released, duty 0, state OFF",
          r.released(0) and r.released(1) and c0["duty"] == c1["duty"] == 0
          and c0["state"] & S_OFF and c1["state"] & S_OFF,
          "cam1 %s cam2 %s" % (c0, c1))

    print("\n-- V2 switch, cam 1 -> 115 --")
    r = Rig()
    r.pg8("CFG_U_VVT_MODE", 1, 0)
    r.target(0, 100)
    r.run(200, fresh=(False, False))            # SWITCH needs no position
    u0 = r.unit(0)
    check("V2: target > 0 -> ON duty on POUT0 (115) at 250 Hz",
          u0["run"] and u0["pin"] and u0["pp"] == 2499 and u0["pw"] == 1750
          and r.cam(0)["duty"] == 700 and r.cam(0)["state"] & S_SWITCH,
          "unit0 %s, cam1 %s" % (u0, r.cam(0)))
    check("V2: cam 2's unit (120) untouched", r.released(1), str(r.unit(1)))
    r.pg16("CFG_U_VVT_FREQ_HZ", 100)
    r.run(40, fresh=(False, False))
    check("V2: the page frequency reaches the period (100 Hz -> PP0 6249)",
          r.unit(0)["pp"] == 6249 and r.unit(0)["pw"] == 4375, str(r.unit(0)))
    r.target(0, 0)
    r.run(40, fresh=(False, False))
    check("V2: target 0 -> duty 0, POUT0 released", r.released(0)
          and r.cam(0)["duty"] == 0, str(r.unit(0)))

    print("\n-- V3 closed loop, cam 2 -> 120 --")
    r = Rig()
    r.pg8("CFG_U_VVT_MODE", 2, 1)
    r.target(1, 200)                            # 20.0 deg advance
    r.cam_state(1, HCCAM_C_SAME, -100)          # tooth 10.0 deg early = +10
    r.run(100)
    c = r.cam(1)
    u1 = r.unit(1)
    check("V3: target 20.0, position 10.0, error +10.0 at OCH",
          c["target"] == 200 and c["pos"] == 100 and c["err"] == 100
          and c["state"] & S_CLOSED, str(c))
    check("V3: advance wanted -> duty up, on POUT1 (120), within min..max",
          u1["run"] and u1["pin"] and 100 <= c["duty"] <= 900
          and u1["pw"] == c["duty"] * 2500 // 1000, "duty %d, unit1 %s"
          % (c["duty"], u1))
    d_adv = c["duty"]
    check("V3: cam 1 (Off) stays released - the cams are independent",
          r.released(0) and r.cam(0)["duty"] == 0, str(r.unit(0)))
    r.cam_state(1, HCCAM_C_SAME, -300)          # now 30.0: 10 past target
    r.run(100)
    check("V3: past the target -> duty lower", r.cam(1)["err"] == -100
          and r.cam(1)["duty"] < d_adv, "duty %d -> %d"
          % (d_adv, r.cam(1)["duty"]))
    r.target(1, 3000)                           # 300 deg: saturate high
    r.run(400)
    hi = r.cam(1)["duty"]
    r.target(1, -3000)
    r.run(600)
    lo = r.cam(1)["duty"]
    check("V3: duty clamped to vvtDutyMin..vvtDutyMax (10.0..90.0 %)",
          hi == 900 and lo == 100, "high %d low %d" % (hi, lo))
    ri = Rig()
    ri.pg8("CFG_U_VVT_MODE", 2, 1)
    ri.pg8("CFG_U_VVT_INVERT", 1, 1)
    ri.target(1, 200)
    ri.cam_state(1, HCCAM_C_SAME, -100)
    ri.run(100)
    check("V3: invert - the same +10 error drives the duty DOWN",
          ri.cam(1)["duty"] < d_adv and ri.cam(1)["err"] == 100,
          "inverted %d vs %d" % (ri.cam(1)["duty"], d_adv))

    print("\n-- V4 no position --")
    r = Rig()
    r.pg8("CFG_U_VVT_MODE", 2, 0)
    r.target(0, 200)
    r.cam_state(0, HCCAM_C_SAME, -100)
    r.run(100)
    was = r.cam(0)["duty"]
    r.run(220, fresh=(False, True))             # past vvtFbMs, < 2x
    a = r.cam(0)
    r.run(300, fresh=(False, True))             # past 2 x vvtFbMs
    b = r.cam(0)
    check("V4: stale position -> duty 0 (NOPOS) before any latch",
          was > 0 and a["duty"] == 0 and a["state"] & S_NOPOS
          and a["fault"] == 0, "duty %d -> %d, %s" % (was, a["duty"], a))
    check("V4: 2 x vvtFbMs -> NO CAM POSITION latched, POUT0 released",
          b["fault"] == 1 and r.released(0), "%s %s" % (b, r.unit(0)))
    r.run(200)                                  # the position is back
    check("V4: the latch holds while the engine runs",
          r.cam(0)["fault"] == 1 and r.cam(0)["duty"] == 0
          and r.released(0), str(r.cam(0)))
    r.ram16("trg_rpm", 0)
    r.run(40)
    r.ram16("trg_rpm", 2000)
    r.run(100)
    check("V8: rpm 0 re-arms it; control resumes",
          r.cam(0)["fault"] == 0 and r.cam(0)["duty"] > 0, str(r.cam(0)))

    print("\n-- V5 stuck / slow --")
    r = Rig()
    r.pg8("CFG_U_VVT_MODE", 2, 0)
    r.target(0, 300)
    r.cam_state(0, HCCAM_C_SAME, 0)             # never moves: error 30.0
    r.run(800)
    early = r.cam(0)["fault"]
    r.run(400)
    check("V5: |error| > vvtErrMax for vvtErrMs -> STUCK / SLOW, released",
          early == 0 and r.cam(0)["fault"] == 2 and r.released(0)
          and r.cam(0)["duty"] == 0, "at 0.8 s %d, %s" % (early, r.cam(0)))

    print("\n-- V6 out of authority --")
    r = Rig()
    r.pg8("CFG_U_VVT_MODE", 2, 0)
    r.target(0, 100)
    r.cam_state(0, HCCAM_C_OFFSET, 0)
    r.run(100)
    check("V6: tooth outside the authority -> OUT OF AUTHORITY, released",
          r.cam(0)["fault"] == 3 and r.released(0), str(r.cam(0)))

    print("\n-- V7 no stage routed --")
    r = Rig()
    r.pg8("CFG_U_VVT_MODE", 2, 1)
    r.pg8("CFG_U_PIN_CAM2_SOL", 255)
    r.target(1, 100)
    r.run(100)
    check("V7: enabled with no stage -> NO STAGE ROUTED, no unit driven",
          r.cam(1)["fault"] == 4 and r.released(0) and r.released(1),
          str(r.cam(1)))

    print("\n-- V9 the route moves while the unit runs --")
    r = Rig()
    r.pg8("CFG_U_VVT_MODE", 1, 0)
    r.target(0, 100)
    r.run(100)
    ran = r.unit(0)["run"]
    r.pg8("CFG_U_PIN_CAM1_SOL", 120)
    r.pg8("CFG_U_PIN_CAM2_SOL", 255)
    r.run(100)
    check("V9: cam 1 moved 115 -> 120: POUT1 runs, POUT0 released",
          ran and r.unit(1)["run"] and r.released(0),
          "unit0 %s unit1 %s" % (r.unit(0), r.unit(1)))

    print("\nVVT PROOF %s - %d failed" % ("PASSES" if not FAIL else "FAILS",
                                         FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
