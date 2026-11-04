#!/usr/bin/env python3
r"""
me711_can_vag_frames_proof.py - the VAG engine messages leave the LINKED
image on the CAN module, at their rates, carrying the engine's own state
(2026-11-03, .scratch/can-bus/spec.md section 5, comms/hccan711.c).

    py tests\firmware\comms\me711_can_vag_frames_proof.py

WHAT RUNS. The board's image in c167sim with the runtime-stress rig
(tools/analysis/me711_runtime_stress.py: crank teeth, the ADC model, the
throttle plant), the board's preset page plus canEnable = 1, canVag = 1 and
the stock 1.8T identity. c167sim's CAN model (tools/lib/c167sim.py, Mem
can_tx) records every frame the module sends with the simulated time.

CHECKED, each against something the frame cannot fake:
  * Motor_1 / 2 / 3 every 10 ms, Motor_5 every 20 ms (simulated timer);
  * Motor_1 rpm decoded with opendbc vw_pq.dbc equals the rig's crank rpm
    at two operating points (1500 and 3000 rpm) within 2 %;
  * Motor_2 coolant equals the engine's own eng_clt_dc; its multiplex walks
    CANVERS / engine code / gearbox code / MDNORM, four frames each;
  * Motor_5 carries the XOR checksum and the identity multiplex;
  * CONTROL: the same page with canEnable = 0 sends nothing and writes no
    CAN register (the bit timing register stays at its reset value).

NOT PHYSICALLY VERIFIED: no CAN adapter on the bench (spec P0).
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402

import me711_runtime_stress as M        # noqa: E402
import me711_image as PI                # noqa: E402
sys.path.insert(0, str(ROOT / "tests" / "host"))
import test_hccan_host as DBC           # noqa: E402

FAILS = 0


def check(name, ok, detail=""):
    global FAILS
    print("  [%s] %-66s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


import re                               # noqa: E402
OCH = 0x380000 + int(re.search(
    r"#define\s+TGT_RAM_OCH\s+(0x[0-9A-Fa-f]+)",
    (ROOT / "firmware/targets/me711/hctarget.h").read_text()).group(1), 16)
# the CAN readouts (hccan711.c): 534..550, wheels 470/472/474/604, 606, 608
CAN_OCH = (534, 536, 538, 540, 542, 544, 546, 548, 550, 470, 472, 474, 604,
           606, 608)

IDENT = [("CFG_U_CAN_VERS", 10, 1), ("CFG_U_CAN_FMOTC", 34, 1),
         ("CFG_U_CAN_CWGC", 15, 1), ("CFG_U_CAN_MOTTYP", 4, 1),
         ("CFG_U_CAN_MDNORM", 400, 2), ("CFG_U_CAN_MDMAX", 230, 2),
         ("CFG_U_CAN_NMDMAX", 2000, 2), ("CFG_U_CAN_KVNPZ", 780, 2)]


def run(enable: int):
    page = M.build_engine_page(dbw=True, edits=[("CFG_U_CAN_ENABLE", enable, 1),
                                             ("CFG_U_CAN_VAG", 1, 1)] + IDENT
                            + [("CFG_U_CAN_CTX_ID", 0x600, 2),      # custom frame 1
                               ("CFG_U_CAN_CTX_RATE", 5, 1),        # 50 ms
                               ("CFG_U_CAN_CTX_CH", 1136, 2)])      # RPMValue
    s = M.Stress(page, ts=False)
    # stale output block (battery-backed SRAM after another image): every
    # CAN readout starts as garbage
    for a in CAN_OCH:
        s.mem.w8(OCH + a, 0x5A)
        s.mem.w8(OCH + a + 1, 0xA5)
    # the firmware's own 1 ms tick: the rates are its rates (the rig's
    # timer counts in its own units)
    s.mem.can_clock = lambda: s.r16("hc_tick_ms")
    s.dbw_plant = True
    s.pedal = 0.2
    s.boot()
    marks = {}
    tick = lambda: s.r16("hc_tick_ms")
    s.run_us(300000, lambda t: 250)                         # crank
    s.run_us(200000, M.ramp(250, 1500, 0.2))
    marks["1500"] = tick()
    s.run_us(300000, lambda t: 1500)
    marks["1500_end"] = tick()
    s.run_us(200000, M.ramp(1500, 3000, 0.2))
    marks["3000"] = tick()
    s.run_us(300000, lambda t: 3000)
    marks["3000_end"] = tick()
    return s, marks


def main() -> int:
    print("=== HaniCore - VAG engine messages on the CAN module (hccan711.c) ===")
    print("  image   %s" % PI.image().name)
    dbc = DBC.load_dbc()
    if dbc is None:
        print("SKIP: vw_pq.dbc not found")
        return 0
    tpms = 1.0                       # frame times are tick_ms

    s, marks = run(1)
    tx = s.mem.can_tx
    by = {}
    for t, ident, dlc, data in tx:
        by.setdefault(ident, []).append((t, data))
    check("frames sent: Motor_1 / 2 / 3 / 5",
          all(len(by.get(i, [])) > 20 for i in (0x280, 0x288, 0x380, 0x480)),
          " ".join("%03X:%d" % (i, len(by.get(i, []))) for i in (0x280, 0x288, 0x380, 0x480)))
    # THE MAIN-LOOP CONTRACT (hccan711.c): a payload per 10 ms slot, served
    # by the main loop - so never faster than the slot, and no slower than
    # one main-loop pass. With the engine turning a 24 MHz board's pass is
    # 14..16 ms (bench 2.7T: 61 passes/s under the rig), so the 10 ms frames
    # come every 10..16 ms and never more than 30 ms apart. Exactly 10 ms
    # needs the tick-slot service of spec section 3 (open item).
    for ident, want in ((0x280, 10.0), (0x288, 10.0), (0x380, 10.0), (0x480, 20.0)):
        ts = [t for t, _ in by.get(ident, []) if marks["1500"] <= t <= marks["3000_end"]]
        gaps = [(b - a) / tpms for a, b in zip(ts, ts[1:])]
        med = statistics.median(gaps) if gaps else 0.0
        mx = max(gaps) if gaps else 0
        check("0x%03X every %.0f ms (main loop: median <= %.0f, max <= %.0f)"
              % (ident, want, want * 1.6, want * 3),
              gaps and want - 1.0 <= med <= want * 1.6 and mx <= want * 3,
              "median %.2f ms, max %.1f ms, %d frames" % (med, mx, len(ts)))

    for rpm in (1500, 3000):
        lo, hi = marks[str(rpm)] + int(100 * tpms), marks["%d_end" % rpm]
        vals = [DBC.sig(dbc, 0x280, "Motordrehzahl", d)
                for t, d in by.get(0x280, []) if lo <= t <= hi]
        med = statistics.median(vals) if vals else 0.0
        check("Motor_1 rpm at the rig's %d rpm" % rpm, abs(med - rpm) <= rpm * 0.02,
              "median %.0f rpm over %d frames" % (med, len(vals)))

    clt = s.r16("eng_clt_dc")
    err = s.r16("eng_sensor_err")
    d2 = [d for t, d in by.get(0x288, [])]
    last = d2[-1] if d2 else bytes(8)
    if err & 0x0001:
        # the rig's coolant sensor is out of range: the frame must say so
        check("Motor_2 coolant: the engine's CLT fault -> 0xFF + fault bit",
              last[1] == 0xFF and DBC.sig(dbc, 0x288, "MO2_Sta_Kuehlm", last) == 1,
              "frame %s, eng_sensor_err 0x%04X" % (last.hex(), err))
    else:
        want_c = (clt - 10000) / 10.0
        got_c = DBC.sig(dbc, 0x288, "MO2_Kuehlm_T", last)
        check("Motor_2 coolant = eng_clt_dc", abs(got_c - want_c) <= 0.76,
              "frame %.2f C, engine %.1f C" % (got_c, want_c))
    codes = [DBC.sig(dbc, 0x288, "MO2_Mp_Code", d) for d in d2[:64]]
    runs, cur, n = [], None, 0
    for c in codes:
        if c == cur:
            n += 1
        else:
            if cur is not None:
                runs.append(n)
            cur, n = c, 1
    check("Motor_2 multiplex: each code 4 frames in a row",
          len(runs) > 4 and all(r == 4 for r in runs[1:]), "runs %s" % runs[:8])
    vals = {}
    for d in d2[:16]:
        c = int(DBC.sig(dbc, 0x288, "MO2_Mp_Code", d))
        name = {0: "MO2_CAN_Vers", 1: "MO2_Motor_Code", 2: "MO2_Getr_Code", 3: "MO2_max_Mo"}[c]
        vals[name] = DBC.sig(dbc, 0x288, name, d)
    check("Motor_2 identity CANVERS 10 / FMOTC 34 / CWGC 15 / MDNORM 400",
          vals == {"MO2_CAN_Vers": 10, "MO2_Motor_Code": 34, "MO2_Getr_Code": 15,
                   "MO2_max_Mo": 400}, str(vals))
    d5 = [d for t, d in by.get(0x480, [])]
    bad = [d.hex() for d in d5 if d[7] != (d[0] ^ d[1] ^ d[2] ^ d[3] ^ d[4] ^ d[5] ^ d[6])]
    check("Motor_5 XOR checksum on every frame", d5 and not bad,
          "%d frames, %d bad" % (len(d5), len(bad)))
    m5 = {int(DBC.sig(dbc, 0x480, "MO5_Mp_Code", d)): d for d in d5[:16]}
    check("Motor_5 identity: 230 Nm at 2000 rpm, type 4",
          0 in m5 and 1 in m5 and 2 in m5
          and DBC.sig(dbc, 0x480, "MO5_max_Moment", m5[0]) == 230
          and DBC.sig(dbc, 0x480, "MO5_Drehzahl", m5[1]) == 2000
          and DBC.sig(dbc, 0x480, "MO5_Motortyp", m5[2]) == 4)

    # custom frame 1: id 0x600 every 50 ms; frame 2 (id 0) never sent
    ts = [t for t, _ in by.get(0x600, []) if marks["1500"] <= t <= marks["3000_end"]]
    gaps = [(b - a) / tpms for a, b in zip(ts, ts[1:])]
    med = statistics.median(gaps) if gaps else 0.0
    check("custom frame 1 (0x600) every 50 ms", gaps and 49.0 <= med <= 66.0,
          "median %.1f ms, %d frames" % (med, len(ts)))
    check("custom frame 2 (identifier 0) is not sent", 0 not in by)

    s0, _ = run(0)
    btr = s0.mem.can[4] | (s0.mem.can[5] << 8)
    check("CONTROL canEnable 0: no frame, the module untouched",
          not s0.mem.can_tx and btr == 0,
          "%d frames, BTR 0x%04X" % (len(s0.mem.can_tx), btr))
    vals = {a: (s0.mem.r8(OCH + a) << 8) | s0.mem.r8(OCH + a + 1) for a in CAN_OCH}
    want = {a: (0xFFFF if a == 544 else 0) for a in CAN_OCH}
    check("CONTROL canEnable 0: the CAN readouts are defined (0 / speed none)",
          vals == want, " ".join("%d:%04X" % (a, v) for a, v in vals.items()
                                 if v != want[a]))

    print("\n%s" % ("ALL PASS" if not FAILS else "%d FAIL(S)" % FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
