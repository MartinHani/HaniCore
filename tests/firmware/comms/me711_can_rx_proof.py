#!/usr/bin/env python3
r"""
me711_can_rx_proof.py - CAN RECEIVE on the LINKED image (2026-11-03,
comms/hccan711.c): frames injected into c167sim's CAN model reach the engine.

    py tests\firmware\comms\me711_can_rx_proof.py

Checked end to end, on what the firmware DOES with a received frame:
  * Bremse_1 at 87.6 km/h (vehicle speed source "ABS") comes back out in the
    engine's own Motor_2 (byte 3, 1.28 km/h per bit = 68) - received,
    decoded, selected and re-sent;
  * when Bremse_1 stops arriving, the speed in Motor_2 falls to 0 after the
    receive timeout (stale data is no data);
  * an Airbag_1 crash frame (front crash, intensity 5, checksum right) sets
    the engine's fuel-and-spark cut (ENG_CUT_SAFE in eng_fuelcut);
  * CONTROL: the same crash frame with a wrong checksum cuts nothing.

NOT PHYSICALLY VERIFIED: no CAN adapter on the bench.
"""
from __future__ import annotations

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
ENG_CUT_SAFE = 0x0040


def check(name, ok, detail=""):
    global FAILS
    print("  [%s] %-66s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def rig(dbc):
    page = M.build_engine_page(dbw=True, edits=[
        ("CFG_U_CAN_ENABLE", 1, 1), ("CFG_U_CAN_VAG", 1, 1),
        ("CFG_U_CAN_RX_MASK", 1 | 32, 1), ("CFG_U_CAN_VSS_SRC", 1, 1),
        ("CFG_U_CAN_CRASH_CUT", 1, 1), ("CFG_U_CAN_RX_TMO", 0, 1)])
    s = M.Stress(page, ts=False)
    s.mem.can_clock = lambda: s.r16("hc_tick_ms")
    s.dbw_plant = True
    s.pedal = 0.2
    s.boot()
    s.run_us(300000, lambda t: 250)
    s.run_us(200000, M.ramp(250, 1500, 0.2))
    return s


def last_m2(s, since):
    d = [d for t, i, n, d in s.mem.can_tx if i == 0x288 and t >= since]
    return d[-1] if d else None


def main() -> int:
    print("=== HaniCore - CAN receive reaches the engine (hccan711.c) ===")
    print("  image   %s" % PI.image().name)
    dbc = DBC.load_dbc()
    if dbc is None:
        print("SKIP: vw_pq.dbc not found")
        return 0
    br1 = bytes.fromhex(DBC.encode(dbc, 416, {"BR1_Rad_kmh": 87.6}))

    s = rig(dbc)
    for _ in range(40):                                # 400 ms of Bremse_1
        s.mem.can_inject(0x1A0, br1)
        s.run_us(10000, lambda t: 1500)
    t_now = s.r16("hc_tick_ms")
    d = last_m2(s, t_now - 30)
    check("Bremse_1 87.6 km/h -> Motor_2 vehicle speed byte 68 (1.28 km/h)",
          d is not None and d[3] == 68, "byte %s" % (d[3] if d else None))
    s.run_us(800000, lambda t: 1500)                   # no Bremse_1: stale
    d = last_m2(s, s.r16("hc_tick_ms") - 30)
    check("Bremse_1 gone longer than the timeout -> speed 0",
          d is not None and d[3] == 0, "byte %s" % (d[3] if d else None))

    def crash_frame(good):
        b = bytearray(8)
        b[0] = 0x01 | (5 << 5)
        b[2] = 0x30
        b[3] = b[0] ^ b[1] ^ b[2]
        if not good:
            b[3] ^= 0x01
        return bytes(b)

    for _ in range(5):
        s.mem.can_inject(0x050, crash_frame(False))
        s.run_us(10000, lambda t: 1500)
    cut = s.r16("eng_fuelcut")
    check("CONTROL: a crash frame with a wrong checksum cuts nothing",
          not (cut & ENG_CUT_SAFE), "eng_fuelcut 0x%04X" % cut)
    for _ in range(5):
        s.mem.can_inject(0x050, crash_frame(True))
        s.run_us(10000, lambda t: 1500)
    s.run_us(50000, lambda t: 1500)
    cut = s.r16("eng_fuelcut")
    check("Airbag_1 crash (checksum right) -> fuel and spark cut",
          bool(cut & ENG_CUT_SAFE), "eng_fuelcut 0x%04X" % cut)
    s.run_us(300000, lambda t: 1500)
    cut = s.r16("eng_fuelcut")
    check("... and the cut stays (latched until the key cycle)",
          bool(cut & ENG_CUT_SAFE), "eng_fuelcut 0x%04X" % cut)

    print("\n%s" % ("ALL PASS" if not FAILS else "%d FAIL(S)" % FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
