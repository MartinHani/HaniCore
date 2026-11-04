#!/usr/bin/env python3
r"""me711_vss_proof.py - the vehicle-speed input and gear detection on the
LINKED IMAGE in c167sim (2026-11-04: control/hcvss711.c, hctrig_me711.c
ROLE_VSS / hc_cc14_isr, sensors/hcvss.c).

    set HANICORE_BOARD=27t & py tests\firmware\engine\me711_vss_proof.py

The rig turns the engine (60-2 crank at a set rpm) and drives a speed pulse
train of a KNOWN speed into the board's speed capture: CC14 (cavity 54) on
the VAG boards, CC9 (cavity 87, cam 2 unused) on the others - the real
interrupt path, nothing called directly. Checks (expected values computed
here from km/h = Hz x 3600 / pulses per km and the gear table):

  1 the published speed (OCH 1664) within 1.5 % of the pulse train's
  2 the detected gear (OCH 1666 low byte) at the gear the rpm/speed ratio is
  3 another gear after the speed steps at the same rpm
  4 the speed falls to 0 within 1 s of the last pulse
  5 CONTROL: pinVss NONE - the same pulse train counts nothing, the speed
    reads 'none' (0xFFFF): the input is really the routed capture
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402
import me711_runtime_stress as M        # noqa: E402
import me711_image as PI                # noqa: E402

TGT = (ROOT / "firmware/targets/me711/hctarget.h").read_text()
SPARE_C = int(re.search(r"#define TGT_RAM_SPARE_C\s+(0x[0-9A-Fa-f]+)", TGT).group(1), 16)
OCH3_OFF = int(re.search(r"#define TGT_RAM_OCH3\s+\(TGT_RAM_SPARE_C \+ (0x[0-9A-Fa-f]+)uL\)",
                         TGT).group(1), 16)
OCH3 = 0x380000 + SPARE_C + OCH3_OFF
PPK = 4345
GEARS = [760, 1390, 2030, 2680, 3330]       # km/h per 1000 rpm x100
FAILS = 0


def check(name, ok, detail=""):
    global FAILS
    print("  [%s] %-62s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def och3(s, off):
    a = OCH3 + off - 1664
    return (s.mem.r8(a) << 8) | s.mem.r8(a + 1)


def board_input():
    """(cavity, CAPCOM channel) of this board's speed input"""
    import hc_board                              # the VAG boards (2.7T, 18T, BFB)
    return (54, 14) if hc_board.IS_C4 else (87, 9)


def run(pin, ch):
    edits = [("CFG_U_PIN_VSS", pin, 1), ("CFG_U_VSS_PPK", PPK, 2),
             ("CFG_U_GEAR_N", len(GEARS), 1)]
    edits += [("CFG_U_GEAR_V", g, 2, i) for i, g in enumerate(GEARS)]
    page = M.build_engine_page(dbw=True, edits=edits)
    s = M.Stress(page, ts=False)
    s.dbw_plant = True
    s.pedal = 0.2
    s.boot()
    st = {"kmh": 0.0, "phase": 0.0, "t": None, "n": 0}

    def hook(t1):
        if st["t"] is None:
            st["t"] = t1
            return
        dt = (t1 - st["t"]) / M.TICKS_PER_S
        st["t"] = t1
        st["phase"] += st["kmh"] * PPK / 3600.0 * dt
        if st["phase"] >= 1.0:
            st["phase"] -= 1.0
            st["n"] += 1
            s.cpu.capture(ch)
    s.edge_hook = hook
    out = {}
    s.run_us(300000, lambda t: 250)                         # crank
    s.run_us(300000, M.ramp(250, 3000, 0.3))
    v3 = GEARS[2] / 100.0 * 3.0                             # 3rd at 3000 rpm
    st["kmh"] = v3
    s.run_us(2500000, lambda t: 3000)
    out["v3"] = (v3, och3(s, 1664), och3(s, 1666))
    v4 = GEARS[3] / 100.0 * 3.0
    st["kmh"] = v4
    s.run_us(2000000, lambda t: 3000)
    out["v4"] = (v4, och3(s, 1664), och3(s, 1666))
    st["kmh"] = 0.0
    s.run_us(1100000, lambda t: 3000)
    out["stop"] = (0.0, och3(s, 1664), och3(s, 1666))
    out["edges_fw"] = och3(s, 1670)
    out["edges_rig"] = st["n"]
    return out


def main() -> int:
    print("=== HaniCore - vehicle speed input + gears (hcvss711.c) ===")
    print("  image   %s" % PI.image().name)
    pin, ch = board_input()
    print("  input   cavity %d -> CC%d" % (pin, ch))
    r = run(pin, ch)
    want, got, gs = r["v3"]
    check("speed at %.1f km/h (3rd, 3000 rpm)" % want,
          abs(got / 10.0 - want) <= 0.015 * want, "%.1f km/h" % (got / 10.0))
    check("gear 3 detected", gs & 0xFF == 3, "gear %d, bits 0x%03X" % (gs & 0xFF, gs))
    check("... and the input reported routed + reading", (gs & 0x300) == 0x300)
    want, got, gs = r["v4"]
    check("speed at %.1f km/h (4th ratio)" % want,
          abs(got / 10.0 - want) <= 0.015 * want, "%.1f km/h" % (got / 10.0))
    check("gear 4 detected after the step", gs & 0xFF == 4, "gear %d" % (gs & 0xFF))
    _, got, gs = r["stop"]
    check("0 km/h within 1.1 s of the last pulse, no gear", got == 0 and gs & 0xFF == 0,
          "%.1f km/h gear %d" % (got / 10.0, gs & 0xFF))
    check("every rig pulse counted by the interrupt",
          abs(r["edges_fw"] - (r["edges_rig"] & 0xFFFF)) <= 1,
          "fw %d rig %d" % (r["edges_fw"], r["edges_rig"]))
    c = run(255, ch)
    check("CONTROL pinVss NONE: no edge counted, speed 'none'",
          c["edges_fw"] == 0 and c["v3"][1] == 0xFFFF,
          "edges %d speed 0x%04X" % (c["edges_fw"], c["v3"][1]))
    print("\n%s" % ("ALL PASS" if not FAILS else "%d FAIL(S)" % FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
