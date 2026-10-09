#!/usr/bin/env python3
r"""me711_idle_proof.py - idle speed control on the LINKED IMAGE (V97).

    py tests\firmware\engine\me711_idle_proof.py

The core (firmware/control/hcidle.c) is host-tested with its negative controls
(tests/host/test_hcidle_host.py). This gate runs what the image does, on the
booted image through me711_dbw_control_proof's rig (the real permission
layer, a real page in SRAM, real ADC counts):

  1  the HOOK: hc_dbw.c's target at 0 % pedal is the pedal map (0) with the
     floor 0 - and exactly the floor when hc_idle_floor_x10 is raised; a
     pedal demand above the floor wins (max, not sum)
  2  idleEnable 0: hc_idle_service() publishes floor 0 (the V96 behaviour)
  3  engine stopped: floor = the base curve at the coolant temperature
  4  running below target, after the post-start delay: closed loop, first
     step exactly base + P + I (kp 20, ki 5, e = 100 rpm -> 20 + 5)
  5  pedal pressed: P dropped, I held
  6  the DBW target follows the idle floor end to end
  7  (V97) the idle ignition-timing term: off -> 0; on -> P on the rpm
     error, summed into hc_ign_corr_x10; 0 with the pedal pressed; soft entry
  7  (V97) the idle ignition-timing term: off -> 0; on -> P on the rpm
     error, summed into hc_ign_corr_x10; 0 with the pedal pressed; soft entry
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_dbw_control_proof as D        # noqa: E402

FAIL = 0


def check(name, ok, detail=""):
    global FAIL
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<64} {detail}")
    FAIL += not ok


def ram16(r, name, v):
    r.mem.w16(D.sym(name) & 0xFFFF, v & 0xFFFF)


def ram8(r, name, v):
    r.mem.w8(D.sym(name) & 0xFFFF, v & 0xFF)


def rd16(r, name):
    return r.mem.r16(D.sym(name) & 0xFFFF)


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def idle_page(r, enable):
    r.set8("CAL_IDLE_ENABLE", enable)
    base_ax = D.gen_off("CAL_IDLE_BASE_AX")
    for i in range(8):
        ax = (-20 + 20 * i + 100) * 10                 # 0.1 C + bias
        for name, val in (("CAL_IDLE_TARGET_AX", ax), ("CAL_IDLE_BASE_AX", ax),
                          ("CAL_IDLE_TARGET_VAL", 800), ("CAL_IDLE_BASE_VAL", 65)):
            a = r.page_addr(D.gen_off(name) + 2 * i)
            r.mem.w8(a, (val >> 8) & 0xFF)
            r.mem.w8(a + 1, val & 0xFF)
    del base_ax
    r.set16("CAL_IDLE_KP", 20)
    r.set16("CAL_IDLE_KI", 5)
    r.set16("CAL_IDLE_RANGE_X10", 50)
    r.set16("CAL_IDLE_RPM_BAND", 400)
    r.set16("CFG_U_IDLE_PEDAL_X10", 0)                # -> 2.0 %
    r.set16("CFG_U_IDLE_START_MS", 0)                 # -> 1000 ms


def idle(r, ms=20):
    """hc_idle_service() takes the UPTIME (tick_ms) - the rig keeps it"""
    r.t = (getattr(r, "t", 0) + ms) & 0xFFFF
    r.call("hc_idle_service", (r.t,))
    return rd16(r, "hc_idle_floor_x10")


def main() -> int:
    print("=== idle speed control on the linked image ===")
    r = D.Rig()
    r.baseline()
    r.call("hc_idle_init")
    r.t = 0
    r.call("hc_idle_service", (0,))                    # the clock starts here
    t = r.steps(D.dbw_init_passes() + 4)
    s = r.s()
    check("DBW running at 0 % pedal, floor 0: target = the pedal map (0)",
          s["state"] == D.ST["RUN"] and s["target"] == 0, f"state {s['state']} target {s['target']}")
    ram16(r, "hc_idle_floor_x10", 80)
    t = r.steps(3, start=t)
    check("the hook: floor 8.0 % -> target 8.0 %", r.s()["target"] == 80,
          f"target {r.s()['target']}")
    r.pedal(500)
    t = r.steps(3, start=t)
    with_floor = r.s()["target"]
    ram16(r, "hc_idle_floor_x10", 0)
    t = r.steps(3, start=t)
    no_floor = r.s()["target"]
    check("... a pedal demand above the floor wins (max, not sum)",
          with_floor == no_floor and with_floor > 400,
          f"target {with_floor} with the floor, {no_floor} without")
    r.pedal(0)
    t = r.steps(3, start=t)                            # the DBW sees pedal 0

    # the idle service itself
    ram16(r, "eng_clt_dc", 1800)                       # 80.0 C
    ram16(r, "trg_rpm", 0)
    ram8(r, "eng_cranking", 0)
    idle_page(r, 0)
    check("idleEnable 0: floor 0", idle(r) == 0, f"floor {rd16(r, 'hc_idle_floor_x10')}")
    idle_page(r, 1)
    f = idle(r)
    check("engine stopped: floor = base 6.5 %", f == 65, f"floor {f}")
    ram16(r, "trg_rpm", 700)
    waited = [idle(r) for _ in range(50)]              # 1000 ms post-start delay
    check("running: the post-start delay holds the base for 1000 ms",
          all(w == 65 for w in waited), f"{sorted(set(waited))}")
    f = idle(r)
    trim = s16(r.mem.r16((D.sym("hc_idl") & 0xFFFF) + 8))   # hcidle_t.trim_x10
    check("closed loop, 700 rpm vs 800: floor = 65 + P 20 + I 5 = 90",
          f == 90 and trim == 25, f"floor {f} trim {trim}")
    r.pedal(500)
    t = r.steps(3, start=t)
    f = idle(r)
    check("pedal pressed: P dropped, I held -> 65 + 5 (+ one I step before)",
          f == 70, f"floor {f}")
    r.pedal(0)
    t = r.steps(3, start=t)
    f = idle(r)
    t = r.steps(3, start=t)
    tgt = r.s()["target"]
    check("end to end: the DBW target is the idle floor at 0 % pedal",
          tgt == f and f > 65, f"floor {f} target {tgt}")

    # V97: closed-loop idle ignition timing (hcidle_timing_step via
    # hcidle711.c, summed by hc_ign_corr_x10). The page's CLT/IAT timing
    # curves are 0 here, so the correction IS the idle term.
    def timing():
        return s16(r.call("hc_idle_timing_x10"))

    def corr():
        return s16(r.call("hc_ign_corr_x10", (1800, 10300)))

    r.set8("CFG_U_IDLE_TIM_EN", 0)
    r.set16("CFG_U_IDLE_TIM_KP", 50)                  # 5.0 deg per 100 rpm
    r.set16("CFG_U_IDLE_TIM_MIN", -100)
    r.set16("CFG_U_IDLE_TIM_MAX", 100)
    r.set16("CFG_U_IDLE_TIM_SOFT_MS", 0)
    idle(r)
    check("idle timing off: 0 in closed loop", timing() == 0 and corr() == 0,
          f"timing {timing()} corr {corr()}")
    r.set8("CFG_U_IDLE_TIM_EN", 1)
    idle(r)
    check("on, 700 vs 800 rpm: +5.0 deg, and hc_ign_corr_x10 carries it",
          timing() == 50 and corr() == 50, f"timing {timing()} corr {corr()}")
    ram16(r, "trg_rpm", 850)
    idle(r)
    check("above target (inside the band): retard, -2.5 deg",
          timing() == -25, f"timing {timing()}")
    ram16(r, "trg_rpm", 700)
    r.pedal(500)
    t = r.steps(3, start=t)
    idle(r)
    check("pedal pressed (loop not closed): 0", timing() == 0,
          f"timing {timing()}")
    r.set16("CFG_U_IDLE_TIM_SOFT_MS", 1000)
    r.pedal(0)
    t = r.steps(3, start=t)
    idle(r)
    first = timing()
    for _ in range(60):
        idle(r)
    check("soft entry 1 s: small at first, full after it",
          0 < first <= 2 and timing() == 50, f"{first} -> {timing()}")

    # V97: the dashpot (rusEFI iacByTpsTaper / hold / decay): after a
    # release the floor carries the adder, the trim held, then decays to 0
    r.set8("CFG_U_IDLE_TIM_EN", 0)
    r.set16("CFG_U_IDLE_DASH_X10", 30)
    r.set16("CFG_U_IDLE_DASH_HOLD_MS", 1000)
    r.set16("CFG_U_IDLE_DASH_DECAY_MS", 2000)
    state = lambda: r.mem.r8((D.sym("hc_idl") & 0xFFFF) + 17)   # noqa: E731 (hcidle_t.state)
    trim = lambda: s16(r.mem.r16((D.sym("hc_idl") & 0xFFFF) + 8))  # noqa: E731
    r.pedal(500)
    t = r.steps(3, start=t)
    idle(r)
    r.pedal(0)
    t = r.steps(3, start=t)
    f = idle(r)
    held = trim()
    check("dashpot: after a release floor = base + held trim + 3.0 %, state DASH",
          f == 65 + held + 30 and state() == 0x80,
          f"floor {f} trim {held} state 0x{state():02X}")
    for _ in range(100):                               # 2 s: half way down
        f = idle(r)
    check("... decaying after the 1 s hold (2.0 s: ~half the adder)",
          65 + held + 13 <= f <= 65 + held + 17 and trim() == held,
          f"floor {f} trim {trim()}")
    for _ in range(60):
        f = idle(r)
    check("... gone after hold + decay: closed loop again",
          state() & 0x20 != 0, f"floor {f} state 0x{state():02X}")

    print(f"\n{'IDLE PROOF PASSES' if not FAIL else 'IDLE PROOF FAILS'} - {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
