#!/usr/bin/env python3
r"""me711_can_ext_proof.py - the 2026-11-04 CAN functions on the LINKED IMAGE
in c167sim (comms/hccan711.c): ABS emulation, Haldex control, wideband over
CAN, OBD-II over CAN, the per-boot object allocation.

    set HANICORE_BOARD=27t & py tests\firmware\comms\me711_can_ext_proof.py

The rig runs the engine, drives a vehicle-speed pulse train into the board's
speed capture (as me711_vss_proof) and injects bus frames at fixed times;
everything the ECU sends is decoded with opendbc vw_pq.dbc or the published
frame layouts written here. Checks:

  ABS emulation  Bremse_1 / Bremse_3 every slot carry the pulse train's speed
                 (DBC), and stop for good once a REAL Bremse_1 is received
                 (OCH 1676 bit 3)
  Haldex mode 1  with Allrad_1 reporting 0 % lock against a wanted lock the
                 emulated rear wheels are slower than the front ones
  wideband       rusEFI frames (0x190, lambda 0.950) -> OCH 1672 = 950, and
                 the 29-bit ECU status frame 0x0EF50000 is sent
  OBD-II         mode 01 PID 0C on 0x7DF -> 0x7E8 "04 41 0C" + rpm x 4;
                 mode 09 PID 04 -> an ISO-TP first frame, then (after the
                 tester's flow control) consecutive frames; reassembled
                 = "HC-" + the page layout id
  CONTROL        the same page with everything off sends none of it
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
import test_hccan_host as DBC           # noqa: E402

TGT = (ROOT / "firmware/targets/me711/hctarget.h").read_text()
GEN = (ROOT / "firmware/generated/hc_config_generated.h").read_text()
SPARE_C = int(re.search(r"#define TGT_RAM_SPARE_C\s+(0x[0-9A-Fa-f]+)", TGT).group(1), 16)
OCH3_OFF = int(re.search(r"#define TGT_RAM_OCH3\s+\(TGT_RAM_SPARE_C \+ (0x[0-9A-Fa-f]+)uL\)",
                         TGT).group(1), 16)
OCH3 = 0x380000 + SPARE_C + OCH3_OFF
LAYOUT = int(re.search(r"#define HC_CFG_LAYOUT_ID\s+0x([0-9A-F]+)uL", GEN).group(1), 16)
PPK = 4345
FAILS = 0


def check(name, ok, detail=""):
    global FAILS
    print("  [%s] %-62s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def och3(s, off):
    a = OCH3 + off - 1664
    return (s.mem.r8(a) << 8) | s.mem.r8(a + 1)


def speed_input():
    import hc_board                              # the VAG boards (2.7T, 18T, BFB)
    return (54, 14) if hc_board.IS_C4 else (87, 9)


def run(on: bool):
    pin, ch = speed_input()
    edits = [("CFG_U_CAN_ENABLE", 1, 1), ("CFG_U_CAN_VAG", 1, 1),
             ("CFG_U_PIN_VSS", pin, 1), ("CFG_U_VSS_PPK", PPK, 2)]
    if on:
        edits += [("CFG_U_CAN_ABS_EMU", 1, 1), ("CFG_U_HX_MODE", 1, 1),
                  ("CFG_U_HX_TPS_LOCK", 60, 1, 0), ("CFG_U_HX_TPS_LOCK", 60, 1, 1),
                  ("CFG_U_HX_TPS_LOCK", 60, 1, 2), ("CFG_U_HX_TPS_LOCK", 60, 1, 3),
                  ("CFG_U_HX_TPS_AX", 0, 1, 0), ("CFG_U_HX_TPS_AX", 30, 1, 1),
                  ("CFG_U_HX_TPS_AX", 60, 1, 2), ("CFG_U_HX_TPS_AX", 100, 1, 3),
                  ("CFG_U_HX_NO_LOCK", 0, 1, 0), ("CFG_U_HX_NO_LOCK", 0, 1, 1),
                  ("CFG_U_HX_NO_LOCK", 0, 1, 2), ("CFG_U_HX_NO_LOCK", 0, 1, 3),
                  ("CFG_U_HX_FULL_LOCK", 50, 1, 0), ("CFG_U_HX_FULL_LOCK", 50, 1, 1),
                  ("CFG_U_HX_FULL_LOCK", 50, 1, 2), ("CFG_U_HX_FULL_LOCK", 50, 1, 3),
                  ("CFG_U_HX_KP", 20, 1), ("CFG_U_HX_KI", 20, 1),
                  ("CFG_U_CAN_WB_FMT", 1, 1), ("CFG_U_CAN_WB_IDX", 0, 1),
                  ("CFG_U_LAM1_SRC", 3, 1), ("CFG_U_CAN_OBD", 1, 1)]
    page = M.build_engine_page(dbw=True, edits=edits)
    s = M.Stress(page, ts=False)
    s.mem.can_clock = lambda: s.r16("hc_tick_ms")
    s.dbw_plant = True
    s.pedal = 0.2
    s.boot()
    st = {"kmh": 0.0, "phase": 0.0, "t": None, "ms_wb": None, "ms_al": None}

    def hook(t1):
        if st["t"] is None:
            st["t"] = t1
            return
        dt = (t1 - st["t"]) / M.TICKS_PER_S
        st["t"] = t1
        st["phase"] += st["kmh"] * PPK / 3600.0 * dt
        if st["phase"] >= 1.0:
            st["phase"] -= 1.0
            s.cpu.capture(ch)
        # the rig's own clock (a symbol read per simulated step is too slow)
        tick10 = int(10e-3 * M.TICKS_PER_S)
        if st.get("wb") and (st["ms_wb"] is None or t1 - st["ms_wb"] >= tick10):
            st["ms_wb"] = t1
            raw = 9500
            s.mem.can_inject(0x190, bytes([0xA0, 1, raw & 0xFF, raw >> 8, 0x2C, 3, 0, 0]))
        if st.get("al") and (st["ms_al"] is None or t1 - st["ms_al"] >= tick10):
            st["ms_al"] = t1
            s.mem.can_inject(0x2C0, bytes([0, 0, 0, 0, 0]))          # 0 % lock
    s.edge_hook = hook
    s.run_us(300000, lambda t: 250)
    s.run_us(300000, M.ramp(250, 2500, 0.3))
    st["kmh"] = 50.0
    st["wb"] = True
    st["al"] = True
    s.run_us(1500000, lambda t: 2500)
    out = {"t_speed": s.r16("hc_tick_ms"), "ext": och3(s, 1676),
           "lam1": och3(s, 1672), "objs": och3(s, 1686), "hxoff": och3(s, 1684)}
    # OBD mode 01 PID 0C, then mode 09 PID 04 (multi-frame) + flow control
    mark = len(s.mem.can_tx)
    s.mem.can_inject(0x7DF, bytes([2, 0x01, 0x0C, 0, 0, 0, 0, 0]))
    s.run_us(100000, lambda t: 2500)
    out["obd01"] = [f for f in s.mem.can_tx[mark:] if f[1] == 0x7E8]
    out["rpm_now"] = s.r16("trg_rpm")
    mark = len(s.mem.can_tx)
    s.mem.can_inject(0x7DF, bytes([2, 0x09, 0x04, 0, 0, 0, 0, 0]))
    s.run_us(60000, lambda t: 2500)
    ff = [f for f in s.mem.can_tx[mark:] if f[1] == 0x7E8]
    s.mem.can_inject(0x7E0, bytes([0x30, 0, 0, 0, 0, 0, 0, 0]))
    s.run_us(150000, lambda t: 2500)
    out["obd09"] = [f for f in s.mem.can_tx[mark:] if f[1] == 0x7E8]
    out["obd09_ff_only"] = ff
    # a REAL ABS appears: the emulation must stop
    s.mem.can_inject(0x1A0, bytes(8))
    s.run_us(200000, lambda t: 2500)
    mark = len(s.mem.can_tx)
    s.run_us(300000, lambda t: 2500)
    out["b1_after"] = [f for f in s.mem.can_tx[mark:] if f[1] == 0x1A0]
    out["ext_after"] = och3(s, 1676)
    out["tx"] = list(s.mem.can_tx)
    return out


def main() -> int:
    print("=== HaniCore - CAN: ABS emulation, Haldex, wideband, OBD-II (hccan711.c) ===")
    print("  image   %s" % PI.image().name)
    dbc = DBC.load_dbc()
    r = run(True)
    tx = r["tx"]
    b1 = [f for f in tx if f[1] == 0x1A0 and f[0] <= r["t_speed"] and f[0] >= r["t_speed"] - 500]
    b3 = [f for f in tx if f[1] == 0x4A0 and f[0] <= r["t_speed"] and f[0] >= r["t_speed"] - 500]
    sp = [DBC.sig(dbc, 416, "BR1_Rad_kmh", f[3]) for f in b1]
    check("ABS emulation: Bremse_1 sent with the input's speed (50 km/h)",
          len(sp) >= 10 and abs(sorted(sp)[len(sp) // 2] - 50.0) <= 1.0,
          "%d frames, median %.1f km/h" % (len(sp), sorted(sp)[len(sp) // 2] if sp else -1))
    if b3:
        f = b3[-1][3]
        vl = DBC.sig(dbc, 1184, "Radgeschw__VL_4_1", f)
        hl = DBC.sig(dbc, 1184, "Radgeschw__HL_4_1", f)
        check("Haldex mode 1: Allrad 0 pct < wanted -> rear slower than front",
              vl > 45 and hl < vl - 0.5, "front %.2f rear %.2f km/h, offset %.1f"
              % (vl, hl, r["hxoff"] / 10.0))
    else:
        check("Bremse_3 sent", False)
    check("wideband: rusEFI lambda 0.950 -> OCH 1672", r["lam1"] == 950, "%d" % r["lam1"])
    st_frames = [f for f in tx if f[1] == 0x0EF50000]
    check("wideband: ECU status 0x0EF50000 sent (29-bit, battery + heater)",
          len(st_frames) >= 10 and st_frames[-1][2] == 2,
          "%d frames, dlc %s" % (len(st_frames), st_frames[-1][2] if st_frames else "-"))
    o1 = r["obd01"]
    want = (r["rpm_now"] * 4) & 0xFFFF
    ok01 = bool(o1) and o1[0][3][:3] == bytes([4, 0x41, 0x0C])
    got = ((o1[0][3][3] << 8) | o1[0][3][4]) if ok01 else -1
    check("OBD-II mode 01 PID 0C answered on 0x7E8 (rpm x 4)",
          ok01 and abs(got - want) <= 4 * 50, "%s rpm %d" % (o1[0][3].hex() if o1 else "-", got // 4))
    ff = r["obd09_ff_only"]
    check("OBD-II mode 09 PID 04: first frame, then waits for flow control",
          len(ff) == 1 and ff[0][3][0] == 0x10, "%d frames before FC" % len(ff))
    o9 = r["obd09"]
    data = b""
    if o9 and o9[0][3][0] == 0x10:
        n = o9[0][3][1]
        data = o9[0][3][2:]
        for f in o9[1:]:
            data += f[3][1:]
        data = data[:n]
    calid = data[3:].split(b"\0")[0].decode(errors="replace") if data else ""
    check("... consecutive frames after FC, reassembled CALID = HC-%08X" % LAYOUT,
          data[:3] == bytes([0x49, 0x04, 1]) and calid == "HC-%08X" % LAYOUT,
          "%r" % calid)
    check("a REAL Bremse_1 suspends the emulation (none sent after, bit 3)",
          not r["b1_after"] and (r["ext_after"] & 0x08), "%d sent, ext 0x%04X"
          % (len(r["b1_after"]), r["ext_after"]))
    check("objects: allocated within the 15, none short", r["objs"] <= 15 and not (r["ext"] & 0x80),
          "%d in use, ext 0x%04X" % (r["objs"], r["ext"]))
    c = run(False)
    ids = {f[1] for f in c["tx"]}
    check("CONTROL all off: no Bremse / status / OBD frame",
          not ids & {0x1A0, 0x4A0, 0x0EF50000, 0x7E8} and c["lam1"] == 0,
          "ids %s" % sorted(hex(i) for i in ids))
    print("\n%s" % ("ALL PASS" if not FAILS else "%d FAIL(S)" % FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
