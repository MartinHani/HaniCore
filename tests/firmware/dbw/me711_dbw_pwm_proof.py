#!/usr/bin/env python3
r"""
me711_dbw_pwm_proof.py - the throttle bridge is DRIVEN THE WAY THE CJ220 READS
IT, executed from the linked image.

    py tests\firmware\dbw\me711_dbw_pwm_proof.py

THE PART. S8100 on the ME7.1.1 sheet is a CJ220 (pins 6/7 OU1, 14/15 OU2,
17 CP, 18 DI1 <- EGENFR_P211, 13 DI2 with an inversion bubble). Its truth
table, the Bosch CJ220 datasheet:

    DI  EN  IN1 IN2   OU1 OU2
    L   H   H   L     H   L    forward
    L   H   L   H     L   H    reverse
    L   H   L   L     L   L    free-wheeling low
    L   H   H   H     H   H    free-wheeling high
    H   X   X   X     Z   Z    disable      (SF = L)
    Z   X   X   X     Z   Z    DI open      (SF = L)
    L   H   X   Z     X   H    IN2 open reads HIGH

THE C167 PWM, mode 0 [C167CR UM V3.1 ch.16]: the pin is HIGH while PT >= PW,
so the HIGH time of an N-count period (PP = N-1) is N - PW; and the pin is the
PWM signal XOR the port latch.

WHAT THIS GATE DOES. Boots the image in c167sim, opens the three permission
gates in RAM (page armed, validation clean, hc_dbw_allowed), then calls the
HAL exactly as hc_dbw.c's apply() and hc_dbw_shutdown() do and decodes P2/DP2,
P7/DP7, PWMCON1, PP2 and PW2 into the bridge state and the drive fraction.

THE NEGATIVE CONTROL IS V82, a real frozen image. It must fail: its enable
drove P2.11 HIGH (= DISABLE), its duty was PW = N*duty (IN1 high for 1-duty),
and its zero duty in reverse was the reverse row at full current.

NOT PHYSICALLY VERIFIED: no throttle motor has been driven by this ECU.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import c167sim as S                          # noqa: E402
import me711_heartbeat_gap_proof as HB       # noqa: E402

BINS = ROOT / "bins/hanicore"
TGT = ROOT / "firmware/targets/me711/hctarget.h"
GEN = ROOT / "firmware/generated/hc_config_generated.h"
CANDIDATE = os.environ.get("HANICORE_ME711_STEM", "HaniCore_ME711_v83_first_start")
CONTROL = "HaniCore_ME711_v82_asic_io"

P2, DP2, P7, DP7 = 0xFFC0, 0xFFC2, 0xFFD0, 0xFFD2
PWMCON1 = 0xFF32
PP2, PW2 = 0xF03C, 0xFE34
SENTINEL = 0x0002


def define(path, name):
    m = re.search(r"#define\s+%s\s+(\S+)" % name, path.read_text(errors="replace"))
    if not m:
        raise SystemExit("%s not in %s" % (name, path.name))
    return int(m.group(1).rstrip("uU"), 0)


EN_BIT = define(TGT, "TGT_DBW_EN_PORT_BIT")
PWM_BIT = define(TGT, "TGT_DBW_PWM_PORT_BIT")
DIR_BIT = define(TGT, "TGT_DBW_DIR_PORT_BIT")
PERIOD = define(TGT, "TGT_DBW_PWM_PERIOD")
OUT_ARMED = define(ROOT / "firmware/config/hcconfig.h", "CFG_OUTPUTS_ARMED")
SEM = {n: define(ROOT / "firmware/hal/hchal.h", n)
       for n in ("HC_OUT_THR_PWM", "HC_OUT_THR_DIR", "HC_OUT_THR_EN")}


class Img:
    def __init__(self, stem):
        self.stem = stem
        self.bin = BINS / (stem + ".bin")
        self.map = (BINS / (stem + ".M66")).read_text(errors="replace")

    def sym(self, name):
        m = re.search(r"^\s*([0-9A-F]{6})H\s+%s\s" % re.escape(name), self.map, re.M)
        if not m:
            raise SystemExit("%s: symbol %s not in map" % (self.stem, name))
        return int(m.group(1), 16)


def call(rig, img, name, *args):
    cpu = rig.cpu
    addr = img.sym(name)
    saved = (cpu.csp, cpu.ip, cpu.m.sfr[0xFE12], cpu.ext)
    cpu.ext = None
    cpu.push(SENTINEL)
    cpu.csp, cpu.ip = (addr >> 16) & 0xFF, addr & 0xFFFF
    for i, v in enumerate(args):
        cpu.sr(8 + i, v & 0xFFFF)
    for _ in range(200_000):
        if (cpu.ip & 0xFFFF) == SENTINEL:
            break
        cpu.step()
    else:
        raise SystemExit("%s did not return" % name)
    cpu.csp, cpu.ip, cpu.m.sfr[0xFE12], cpu.ext = saved


def sfr(rig, a):
    return rig.mem.r16(a)


def state(rig):
    """Decode the bridge from the port and PWM registers.

    Returns (di, in1_high_fraction, in2) where di is 'L' (permitted), 'H'
    (disabled, driven) or 'Z' (released = disabled per the datasheet), in2 is
    'L'/'H'/'Z' (Z reads HIGH on a CJ220)."""
    p2, dp2 = sfr(rig, P2), sfr(rig, DP2)
    p7, dp7 = sfr(rig, P7), sfr(rig, DP7)
    en_m, pwm_m, dir_m = 1 << EN_BIT, 1 << PWM_BIT, 1 << DIR_BIT
    di = ("H" if p2 & en_m else "L") if dp2 & en_m else "Z"
    in2 = ("H" if p7 & dir_m else "L") if dp7 & dir_m else "Z"
    latch = 1 if p7 & pwm_m else 0
    if not dp7 & pwm_m:
        in1 = None                                     # released: reads HIGH
    elif sfr(rig, PWMCON1) & (1 << PWM_BIT):
        n = sfr(rig, PP2) + 1
        pw = sfr(rig, PW2)
        hi = max(0, min(n, n - pw)) / n                # mode 0: high PT >= PW
        in1 = (1.0 - hi) if latch else hi              # XOR the latch
    else:
        in1 = float(latch)
    return di, in1, in2


def drive(di, in1, in2):
    """(forward fraction, reverse fraction) per the CJ220 truth table."""
    if di != "L":
        return 0.0, 0.0
    in2_hi = in2 in ("H", "Z")
    f1 = 1.0 if in1 is None else in1
    if in2_hi:
        return 0.0, 1.0 - f1                           # L/H reverse
    return f1, 0.0                                     # H/L forward


def run(stem):
    img = Img(stem)
    rig = HB.Rig(img.bin, img.sym("hc_asic_start_service"), img.sym("hc_tick_ms"),
                 echo=False)
    rig.run(1_400_000)
    mem = rig.mem
    cfg = img.sym("hc_cfg") & 0xFFFF
    mem.w8(cfg + OUT_ARMED, 1)
    rev = img.sym("hc_cfg_active_rev") & 0xFFFF
    mem.w16(rev, (mem.r16(rev) + 1) & 0xFFFF)
    mem.w16(img.sym("hc_cfg_validation") & 0xFFFF, 0)
    allowed = img.sym("hc_dbw_allowed") & 0xFFFF
    results = []

    def step(label, seq, want_fwd, want_rev, want_di):
        for fn, a in seq:
            mem.w8(allowed, 1)
            call(rig, img, fn, *a)
        di, in1, in2 = state(rig)
        fwd, rev_ = drive(di, in1, in2)
        ok = (abs(fwd - want_fwd) < 0.01 and abs(rev_ - want_rev) < 0.01
              and di == want_di)
        results.append((label, ok, "DI=%s IN1=%s IN2=%s -> forward %.0f%% reverse %.0f%%"
                        % (di, "Z" if in1 is None else "%.2f" % in1, in2,
                           fwd * 100, rev_ * 100)))

    E, D, W = SEM["HC_OUT_THR_EN"], SEM["HC_OUT_THR_DIR"], SEM["HC_OUT_THR_PWM"]
    apply = lambda on, d, duty: [("hc_hal_out", (E, on)), ("hc_hal_out", (D, d)),
                                 ("hc_hal_out_duty", (W, duty))]
    step("enable, forward, 25 %", apply(1, 0, 250), 0.25, 0.0, "L")
    step("forward, 90 %", apply(1, 0, 900), 0.90, 0.0, "L")
    step("forward, 100 %", apply(1, 0, 1000), 1.00, 0.0, "L")
    step("reverse, 25 %", apply(1, 1, 250), 0.0, 0.25, "L")
    step("reverse, zero duty is a FREEWHEEL", apply(1, 1, 0), 0.0, 0.0, "L")
    step("forward, zero duty is a FREEWHEEL", apply(1, 0, 0), 0.0, 0.0, "L")
    step("shutdown order: duty 0, EN off, DIR 0",
         apply(1, 1, 300) + [("hc_hal_out_duty", (W, 0)), ("hc_hal_out", (E, 0)),
                             ("hc_hal_out", (D, 0))], 0.0, 0.0, "Z")
    dp7 = sfr(rig, DP7)
    results.append(("after shutdown the direction leg is RELEASED",
                    not dp7 & (1 << DIR_BIT), "DP7=0x%04X" % dp7))
    return results


def main() -> int:
    print("=== HaniCore ME7.1.1 - the throttle bridge, per the CJ220 truth table ===\n")
    print("  EGENFR P2.%d  IN1 P7.%d/POUT2  IN2 P7.%d  period %d counts\n"
          % (EN_BIT, PWM_BIT, DIR_BIT, PERIOD))
    fails = 0
    for stem, must_pass in ((CANDIDATE, True), (CONTROL, False)):
        if not (BINS / (stem + ".bin")).exists():
            print("  %s absent" % stem)
            return 2
        res = run(stem)
        allok = all(ok for _, ok, _ in res)
        print("  %s (%s)" % (stem, "candidate" if must_pass else "NEGATIVE CONTROL"))
        for label, ok, detail in res:
            print("    [%s] %-40s %s" % ("ok " if ok else "BAD", label, detail))
        verdict = allok == must_pass
        fails += not verdict
        print("  [%s] %s must %s\n" % ("PASS" if verdict else "FAIL", stem,
                                       "drive the bridge correctly" if must_pass
                                       else "FAIL at least one row"))
    print("RESULT: %s" % ("PASS" if fails == 0 else "FAIL"))
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
