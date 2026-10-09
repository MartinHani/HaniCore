#!/usr/bin/env python3
r"""
me711_hal_test.py - execute the Bosch HAL out of the real linked image and
check that it routes every semantic channel to the right place, and that it
refuses to invent the ones it does not know.

    py tests\firmware\outputs\me711_hal_test.py

WHAT THIS IS DEFENDING. hcengine.c is now shared between two ECUs whose sensor
wiring genuinely differs: on the ME7.5 board coolant is adc_raw[10]; on the
ME7.1.1 it is not on this CPU at all - Bosch's own port map puts TMOT on the
S5500's AN0, reachable only inside the 118-word runtime frame. The HAL is what
lets one hcengine.c serve both, so the HAL's routing table IS the wiring, and a
wrong entry is a wrong sensor reading with no other symptom.

THE HARD RULE THIS ENFORCES, and it is the reason the file exists:

    hc_hal_ain_ok() MUST return 0 for CLT, IAT and MAP on this board.

Not because those sensors are missing - CLT and IAT are physically there - but
because their POSITION IN THE RUNTIME FRAME IS NOT PROVEN. The V9 hardware
capture proved the STARTUP reply carries a 16-channel ADDAT block at words
4..19; nothing has proven the runtime reply does. Until it is measured,
hcengine.c must use its substitute value and set the sensor's error bit. A
test that let a plausible offset become a live coolant reading would be
undoing the one rule this project protects hardest.

Every function below is EXECUTED from the linked image in c167sim, not read.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import c167sim as S       # noqa: E402
import me711_image as PI
import me711_dpp as _dpp  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
TDIR = ROOT / "firmware/targets/me711"
SHARED = ROOT / "firmware"

_tgt = (TDIR / "hctarget.h").read_text(errors="replace")
_hal = (SHARED / "hal/hchal.h").read_text(errors="replace")


def d(txt, name):
    m = re.search(r"#define\s+%s\s+(0x[0-9A-Fa-f]+|\d+)" % name, txt)
    if not m:
        raise SystemExit(f"{name} not found")
    return int(m.group(1), 0)


AIN = {n: d(_hal, "HC_AIN_" + n) for n in
       ("VBAT", "CLT", "IAT", "MAP", "TPS1", "TPS2", "APP1", "APP2",
        "MAF", "MAF2", "TPS1_AMP", "O2_1_PRE", "O2_1_POST", "O2_2_PRE",
        "O2_2_POST", "KNOCK")}
AIN_COUNT = d(_hal, "HC_AIN_COUNT")
EXTRAM = d(_tgt, "TGT_EXTRAM_BASE")
S5500WIN = d(_tgt, "TGT_RAM_S5500WIN")
FRAME = d(_tgt, "TGT_ASIC_FRAME")
WORDS_RUN = d(_tgt, "TGT_ASIC_WORDS_RUN")

# Bosch's own ME7.1.1 port map, from hctarget.h - the routing this test asserts.
EXPECT_PHYS = {
    "VBAT": d(_tgt, "TGT_ADC_BATT_CH"),
    "TPS1": d(_tgt, "TGT_ADC_TPS1_CH"),
    "TPS2": d(_tgt, "TGT_ADC_TPS2_CH"),
    "APP1": d(_tgt, "TGT_ADC_PEDAL1_CH"),
    "APP2": d(_tgt, "TGT_ADC_PEDAL2_CH"),
    "MAF": d(_tgt, "TGT_ADC_HFM_CH"),
    "MAF2": d(_tgt, "TGT_ADC_HFM2_CH"),
    "TPS1_AMP": d(_tgt, "TGT_ADC_TPS1_AMP_CH"),
    "O2_1_PRE": d(_tgt, "TGT_ADC_LS1VK_CH"),
    "O2_1_POST": d(_tgt, "TGT_ADC_LS1HK_CH"),
    "O2_2_PRE": d(_tgt, "TGT_ADC_LS2VK_CH"),
    "O2_2_POST": d(_tgt, "TGT_ADC_LS2HK_CH"),
    "KNOCK": d(_tgt, "TGT_ADC_KNOCK_CH"),
}
# Not on this board, or not proven. These MUST report unavailable.
EXPECT_UNAVAILABLE = ("CLT", "IAT", "MAP")

MAP_FILE = PI.MAP
FAILS = 0


def check(name, ok, detail=""):
    global FAILS
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<58s} {detail}")
    if not ok:
        FAILS += 1


def sym(name):
    for m in re.finditer(r"^\s*([0-9A-F]{6})H\s+(\w+)\s",
                         MAP_FILE.read_text(errors="replace"), re.M):
        if m.group(2) == name:
            return int(m.group(1), 16)
    raise SystemExit(f"{name} not in the map - build the target first")


class Call:
    """Enough of a C167 to execute one Keil SMALL function and read R4."""

    def __init__(self):
        img = PI.image().read_bytes()
        self.m = S.Mem(img)
        self.m._cbank = bytearray(0x10000)
        self.c = S.CPU(self.m, 0, 0)
        # DPP1 WAS A LITERAL AND IT WAS THE V52 PAGE. See tools/lib/me711_dpp.py.
        _dpp.apply(self.m)
        self.m.sfr[0xFE10] = 0xFC00          # CP, clear of all data
        self.m.w16(0xFC00, 0xF9F0)           # R0 = Keil user stack

    def __call__(self, fn, *args):
        a = sym(fn)
        self.m.w16(self.c.cp(), PI.user_stack_top())
        self.m.sfr[0xFE14], self.m.sfr[0xFE16] = 0xF200, 0xFE00
        sp = 0xF700
        for w in (a >> 16, 0xFFFE):
            sp = (sp - 2) & 0xFFFF
            self.m.w16(sp, w)
        self.m.sfr[0xFE12] = sp
        for i, v in enumerate(args):        # Keil passes the first args in R8..
            self.c.sr(8 + i, v & 0xFFFF)
        self.c.csp, self.c.ip = a >> 16, a & 0xFFFF
        for _ in range(60000):
            if self.c.ip == 0xFFFE:
                if fn in ("hc_hal_ain_ok", "hc_hal_ain_phys", "hc_hal_ain_bound"):
                    # Keil byte returns leave RH4 unspecified.
                    return self.c.gr(4) & 0xFF
                return self.c.gr(4) & 0xFFFF
            self.c.step()
        raise SystemExit(f"{fn} did not return")


def main() -> int:
    print("=== HaniCore Bosch ME7.1.1 - HAL channel routing ===\n")
    print(f"  image  {PI.image().name}")
    print(f"  sha256 {PI.sha256()}\n")

    adc_raw = sym("adc_raw")

    # --- 1. the S5000-direct channels resolve to Bosch's own AN numbers ---
    # Each physical channel gets a distinct marker so a routing swap is
    # visible; reading channel N back as anything but N*7+3 is a wrong route.
    rig = Call()
    rig("hc_hal_init")
    check("boot has no completed MAIN acquisition", rig("hc_hal_ain_mask") == 0)
    # Throttle and pedal tracks have no compile-time fallback: they are read
    # only where the configuration binds them (hc_route_service). Bind them
    # to the board's own channels, as the board default does.
    for name in ("TPS1", "TPS2", "APP1", "APP2"):
        rig("hc_hal_ain_bind", AIN[name], EXPECT_PHYS[name])
    for ch in range(16):
        rig.m.w16((adc_raw & 0xFFFF) + 2 * ch, ch * 7 + 3)
        rig("hc_hal_main_sample", ch, (ch << 12) | (ch * 7 + 3), 1, 0)

    wrong = []
    for name, phys in EXPECT_PHYS.items():
        got = rig("hc_hal_ain", AIN[name])
        if got != phys * 7 + 3:
            wrong.append(f"{name}: expected AN{phys} ({phys * 7 + 3}), "
                         f"got {got}")
    check("every S5000-direct channel routes to Bosch's own AN number",
          not wrong, f"{len(EXPECT_PHYS)} channels" if not wrong
          else "; ".join(wrong))

    ok_wrong = [n for n in EXPECT_PHYS if rig("hc_hal_ain_ok", AIN[n]) != 1]
    check("and every one of them reports available", not ok_wrong,
          "all available" if not ok_wrong else str(ok_wrong))

    # --- 2. THE RULE: unproven channels must report UNAVAILABLE ----------
    bad = [n for n in EXPECT_UNAVAILABLE if rig("hc_hal_ain_ok", AIN[n]) != 0]
    check("CLT / IAT / MAP report UNAVAILABLE, as they must", not bad,
          "hcengine.c will substitute and flag" if not bad
          else f"LIVE BUT UNPROVEN: {bad}")

    zero = [n for n in EXPECT_UNAVAILABLE if rig("hc_hal_ain", AIN[n]) != 0]
    check("and they return 0 rather than a plausible-looking number",
          not zero, "0" if not zero else str(zero))

    # --- 3. the validity mask agrees with the per-channel answers --------
    mask = rig("hc_hal_ain_mask")
    want = 0
    for i in range(AIN_COUNT):
        if rig("hc_hal_ain_ok", i):
            want |= 1 << i
    check("hc_hal_ain_mask() agrees with hc_hal_ain_ok(), channel by channel",
          mask == want, f"0x{mask:04X}")
    check("the mask says 13 of 16 channels are available on this board",
          bin(mask).count("1") == len(EXPECT_PHYS),
          f"{bin(mask).count('1')} available, "
          f"{AIN_COUNT - bin(mask).count('1')} not")

    # --- 4. the S5500 ADDAT window decodes the V9 hardware capture -------
    #
    # These are the ACTUAL sixteen words the ASIC returned on the bench on
    # 2026-08-28 (the maintainer's hardware-session record).
    # If hc_hal_ain_service() cannot decode the real capture, the decode is
    # wrong however good it looks on synthetic data.
    V9 = [0x03BF, 0x13BF, 0x2200, 0x301D, 0x43FF, 0x53FF, 0x63FF, 0x71B6,
          0x8334, 0x93FF, 0xA3FB, 0xB005, 0xC3F3, 0xD3F4, 0xE053, 0xF3BF]
    V9_VALUES = [959, 959, 512, 29, 1023, 1023, 1023, 438,
                 820, 1023, 1019, 5, 1011, 1012, 83, 959]

    rig2 = Call()
    rig2("hc_hal_init")
    base = rig2.m.r16((sym("hc_s5500_base") & 0xFFFF)) & 0xFF
    for i, w in enumerate(V9):
        rig2.m.w16(FRAME + 2 * (base + i), w)
    # hc_asic_run_ok != the snapshot's last value -> take a snapshot
    rig2.m.w16(sym("hc_asic_run_ok") & 0xFFFF, 7)
    rig2.m.w8(sym("hc_asic_run_live") & 0xFFFF, 1)
    rig2.m.w8(sym("hc_asic_state") & 0xFFFF, 6)
    rig2("hc_hal_ain_service")

    vals = [rig2("hc_s5500_val", i) for i in range(16)]
    raws = [rig2("hc_s5500_raw", i) for i in range(16)]
    idx = rig2.m.r16(sym("hc_s5500_idx") & 0xFFFF)

    check("the window defaults to the frame word the V9 capture used",
          base == 4, f"base = {base}")
    check("hc_s5500_raw() returns the captured words unchanged",
          raws == V9, "16/16" if raws == V9 else f"{raws[:4]}...")
    check("hc_s5500_val() extracts the V9 hardware ADC values exactly",
          vals == V9_VALUES,
          "16/16 match the bench capture" if vals == V9_VALUES
          else f"{vals[:6]}... vs {V9_VALUES[:6]}...")
    check("hc_s5500_idx reports all sixteen ADDAT indices self-consistent",
          idx == 0xFFFF, f"0x{idx:04X} (0xFFFF = the V9 signature)")
    check("and the plausible-snapshot counter caught it",
          rig2.m.r16(sym("hc_s5500_plausible") & 0xFFFF) == 1,
          "1 plausible snapshot")

    # --- 5. a WRONG window must NOT look plausible -----------------------
    # If it did, the sweep the bench does to find the real offset would give a
    # false positive, which is worse than no mechanism at all.
    rig3 = Call()
    rig3("hc_hal_init")
    for i in range(WORDS_RUN):
        rig3.m.w16(FRAME + 2 * i, (i * 0x1111) & 0xFFFF)
    rig3.m.w16(sym("hc_asic_run_ok") & 0xFFFF, 3)
    rig3.m.w8(sym("hc_asic_run_live") & 0xFFFF, 1)
    rig3.m.w8(sym("hc_asic_state") & 0xFFFF, 6)
    rig3("hc_hal_ain_service")
    idx3 = rig3.m.r16(sym("hc_s5500_idx") & 0xFFFF)
    check("a frame that is NOT an ADDAT block does not read as one",
          idx3 != 0xFFFF and
          rig3.m.r16(sym("hc_s5500_plausible") & 0xFFFF) == 0,
          f"idx 0x{idx3:04X}, 0 plausible")

    # --- 6. the window is bounded --------------------------------------
    rig3("hc_hal_s5500_window", 250)
    b = rig3.m.r16(sym("hc_s5500_base") & 0xFFFF) & 0xFF
    check("hc_hal_s5500_window() clamps inside the 118-word frame",
          b + 16 <= WORDS_RUN, f"asked 250, clamped to {b}")

    print()
    if FAILS:
        print(f"HAL TEST FAILED ({FAILS} check(s))")
        return 1
    print("HAL TEST PASSES - routing is Bosch's own map, and nothing "
          "unproven is live.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
