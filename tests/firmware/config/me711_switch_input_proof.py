#!/usr/bin/env python3
r"""
me711_switch_input_proof.py - the digital SWITCH INPUTS (launch, clutch /
flat shift, anti-lag, pit limiter): one table of readable cavities, the same
in the descriptor, the .ini dropdowns, the HAL and the validator - and the
runtime reads the selected input with the selected polarity.

    py tests\firmware\config\me711_switch_input_proof.py

WHY. Real TunerStudio, 2026-10-01: "Launch arming pin" offered only None -
the fields needed capability DIN and no ME7.1.1 cavity carried it.

THE ONE TABLE: hw_descriptors.SWITCH_INPUTS - 86/87 (CPU P2.8/P2.9, pull-up,
switch to ground) and the OEM switch inputs 38/39/40/55/56/57/75/76, read
from the S5500's port snapshot in reply words 55/56/59 (decoded from the
ASIC IROM, the A2L-mapped sibling A1104F and this binary's 0x88F62C; the
word position bench-confirmed 2026-10-01). Checks:
  1. hchal_me711.c hc_hal_din() reads exactly those cavities, each ASIC one
     at the decoded reply word / bit (source);
  2. every switch dropdown in the generated .ini offers exactly those plus
     NONE, value = cavity number (serialisation), and polarity is explicit;
  3. the LINKED image (c167sim, AWT preset): launch on 87, P2.9 LOW -> ON,
     HIGH -> OFF, "active high" reverses it, NONE -> never on; the clutch
     input 39 follows reply word 56 bit 4 and is OFF with the ASIC link
     down; the validator refuses a cavity with no read path (41), cam 1's
     cavity (86) and one input for two functions, and accepts 87 and 39.
NEGATIVE CONTROL: check 3 on V97 dev (no switch runtime) must FAIL.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
sys.path.insert(0, str(ROOT / "tools" / "config_source"))

CONTROL_STEM = "HaniCore_ME711_v97_dev"
FIELDS = ("pinLaunch", "pinFlatShift", "pinAntiLag", "pinPitLimiter")
P2 = 0xFFC0
FRAME = 0xE100                              # TGT_ASIC_FRAME (PEC buffer)
CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += 0 if ok else 1
    print("  [%s] %-64s %s" % ("PASS" if ok else "FAIL", name, detail))


def static_checks():
    import hw_descriptors as HW
    want = set(HW.SWITCH_INPUTS)
    hal = (ROOT / "firmware/targets/me711/hal/hchal_me711.c"
           ).read_text(errors="replace")
    body = re.search(r"unsigned char hc_hal_din\(unsigned char cav\)\s*\{(.*?)\n\}",
                     hal, re.S).group(1)
    cpu = {int(x) for x in re.findall(r"cav == (\d+)u", body)}

    # V98r2: the HAL's arrays are the GENERATED macros (generate_config
    # from this table) - read them where they are defined, and require the
    # HAL to use them rather than a retyped list
    gen = (ROOT / "firmware/generated/hc_config_generated.h"
           ).read_text(errors="replace")

    def arr(name):
        m = re.search(r"#define\s+%s\s+\{([^}]*)\}" % name, gen)
        return [int(x) for x in re.findall(r"(\d+)u", m.group(1))] if m else []
    cav, word, bit = (arr("HC_SWITCH_ASIC_CAV"), arr("HC_SWITCH_ASIC_WORD"),
                      arr("HC_SWITCH_ASIC_BIT"))
    check("hc_hal_din() uses the generated switch arrays",
          all(re.search(r"%s\[HC_SWITCH_ASIC_N\]\s*=\s*%s;" % (a, m), hal)
              for a, m in (("din_cav", "HC_SWITCH_ASIC_CAV"),
                           ("din_word", "HC_SWITCH_ASIC_WORD"),
                           ("din_bit", "HC_SWITCH_ASIC_BIT"))))
    asic = {c: (w, b) for c, w, b in zip(cav, word, bit)}
    check("hc_hal_din() reads exactly the descriptor's switch inputs",
          cpu | set(asic) == want and len(cav) == len(word) == len(bit),
          "HAL %s, descriptor %s" % (sorted(cpu | set(asic)), sorted(want)))
    check("...each ASIC input at the decoded reply word / bit",
          asic == HW.SWITCH_INPUT_ASIC_BITS, str(sorted(asic.items())))
    ini = (ROOT / "tunerstudio/hanicore_me711.ini").read_text(
        errors="replace")
    for f in FIELDS:
        m = re.search(r"^\s*%s\s*=\s*bits,\s*U08,\s*\d+,\s*\[0:7\],(.*)$" % f,
                      ini, re.M)
        labels = re.findall(r'"([^"]*)"', m.group(1)) if m else []
        offered = {i for i, s in enumerate(labels)
                   if s not in ("INVALID", "NONE")}
        named = all(labels[i].startswith("%d - " % i) and "Active " in labels[i]
                    for i in offered)
        check("%s dropdown: all switch inputs + None, value = cavity" % f,
              offered == want and len(labels) == 256 and labels[255] == "NONE"
              and named, "offered %s" % sorted(offered))
    for f in ("launchSwitchHigh", "flatShiftSwitchHigh", "antiLagSwitchHigh",
              "pitSwitchHigh"):
        m = re.search(r"^\s*%s\s*=\s*bits.*$" % f, ini, re.M)
        check("%s: explicit Active low / Active high" % f,
              bool(m) and "Active low" in m.group(0)
              and "Active high" in m.group(0))


def runtime(stem):
    os.environ["HANICORE_ME711_STEM"] = stem
    import me711_config_state_test as T
    import me711_alphan_start_proof as AS
    off = AS.off
    print("=== switch inputs at runtime - %s ===" % stem)
    r = AS.setup()

    def och(at):
        import me711_image as _PI
        a = _PI.och_addr(at)
        return (r.m.r8(a) << 8) | r.m.r8(a + 1)

    def settle(passes=12):
        # V98r2: the function state is debounced (10 ms of T1 time in
        # hcengctl711.c sw_deb) - enough passes to cover it
        for _ in range(passes):           # T1 + 2 ms (the sim does not run it)
            r.m.sfr[0xFE52] = (r.m.sfr.get(0xFE52, 0) + 2500) & 0xFFFF
            r("eng_service", steps=3_000_000)
        try:
            r("hc_ec_publish", 0)
        except SystemExit:
            return None
        return (och(1204) >> 12) & 1           # the launch switch bit

    def sense(level):
        p2 = r.m.sfr.get(P2, 0)
        r.m.sfr[P2] = (p2 | 0x0200) if level else (p2 & ~0x0200)
        return settle()

    import re as _re
    ASIC_RUNTIME_WAIT = int(_re.search(r"#define\s+HC_ASIC_ST_RUNTIME_WAIT\s+(\d+)",
        (T.ROOT / "firmware/targets/me711/asic/hcasicstart.h").read_text()).group(1))

    try:
        T.sym("hc_hal_ain_capture")
        has_capture = True
    except SystemExit:
        has_capture = False

    def frame(w56, alive=1):
        """V98r2: THE REAL PATH - the runtime exchange (hcasicstart.c)
        leaves the reply in the PEC frame (TGT_ASIC_FRAME 0xE100) and bumps
        hc_asic_run_ok; hc_hal_ain_service() snapshots the switch words on
        that edge. V98 forced hcasic.c's asic_alive here, which the ME7.1.1
        runtime never sets - every ASIC input read unreadable on the bench.
        An accepted frame is what hcasicstart.c leaves behind: the runtime
        exchange live and in a RUNTIME state (hc_asic_healthy()), the frame
        stamped now. alive=0: the link stopped (hc_asic_run_live 0)."""
        ok = T.sym("hc_asic_run_ok") & 0xFFFF
        live = T.sym("hc_asic_run_live") & 0xFFFF
        if alive:
            r.m.w16(FRAME + 2 * 56, w56)
            r.m.w8(live, 1)
            r.m.w8(T.sym("hc_asic_state") & 0xFFFF, ASIC_RUNTIME_WAIT)
            r.m.w16(T.sym("hc_asic_last_ok_ms") & 0xFFFF, r.g16("hc_tick_ms"))
            r.m.w16(ok, (r.m.r16(ok) + 1) & 0xFFFF)
        else:
            r.m.w8(live, 0)
        # 2026-10-13: the exchange runs in the 1 ms tick and the reply is
        # snapshotted AT THE ACCEPT (hcasicstart.c -> hc_hal_ain_capture);
        # images before that snapshot in hc_hal_ain_service().
        if alive and has_capture:
            r("hc_hal_ain_capture", steps=2_000_000)
        r("hc_hal_ain_service", steps=2_000_000)

    def asic(level, alive=1):
        frame(0x0010 if level else 0x0000, alive)
        return settle()

    try:
        r("hc_cal_set_u16", off("CFG_U_MS_ENABLE"), 0x0001)
    except SystemExit:
        check("the image has the switch runtime", False)
        return
    r("hc_cal_set_u8", off("CFG_U_PIN_LAUNCH"), 87)
    r("hc_cal_set_u8", off("CFG_U_MS_SWITCH_INV"), 0)
    lo, hi = sense(0), sense(1)
    check("launch on 87, active low: P2.9 LOW -> ON, HIGH -> OFF",
          lo == 1 and hi == 0, "low %s high %s" % (lo, hi))
    r("hc_cal_set_u8", off("CFG_U_MS_SWITCH_INV"), 1)
    lo, hi = sense(0), sense(1)
    check("active high: P2.9 HIGH -> ON, LOW -> OFF",
          lo == 0 and hi == 1, "low %s high %s" % (lo, hi))
    r("hc_cal_set_u8", off("CFG_U_PIN_LAUNCH"), 39)
    on, of = asic(1), asic(0)
    check("clutch input 39 (ASIC P3.4 = reply word 56 bit 4), active high: "
          "bit 1 -> ON, 0 -> OFF", on == 1 and of == 0,
          "1 -> %s, 0 -> %s" % (on, of))
    # V98r2: the raw level word (OCH 1132, bit = SWITCH_INPUTS order) - 39 is
    # the fourth entry - follows the wire whatever the function's polarity
    import hw_descriptors as HW
    bit = 1 << list(HW.SWITCH_INPUTS).index(39)
    asic(1)
    raw_on = och(1132) & 0xFFFF
    asic(0)
    raw_off = och(1132) & 0xFFFF
    check("switchRaw: cavity 39's bit follows the line, link-up bit clear",
          bool(raw_on & bit) and not (raw_off & bit)
          and not ((raw_on | raw_off) & 0x8000),
          "high 0x%04X low 0x%04X" % (raw_on, raw_off))
    # V98r2 debounce: a glitch shorter than 10 ms does not flip the state
    asic(1)
    frame(0x0000)
    glitch = settle(passes=1)
    held = asic(1)
    check("a one-pass glitch (< 10 ms) does not switch the function OFF",
          glitch == 1 and held == 1, "glitch %s, after %s" % (glitch, held))
    dead = asic(1, alive=0)
    check("...ASIC link down: the input is unreadable, so OFF", dead == 0,
          str(dead))
    r("hc_cal_set_u8", off("CFG_U_MS_SWITCH_INV"), 0)
    r("hc_cal_set_u8", off("CFG_U_PIN_LAUNCH"), 255)
    lo, hi = sense(0), sense(1)
    check("None: never armed, whatever the line does",
          lo == 0 and hi == 0, "low %s high %s" % (lo, hi))
    # the validator, on the desired page
    r.write(off("CFG_U_MS_ENABLE"), 0x00)
    r.write(off("CFG_U_MS_ENABLE") + 1, 0x01)

    def val(**pins):
        for k, v in pins.items():
            r.write(off(k), v)
        return r("hc_validate", 1)              # HC_VAL_SRC_DESIRED
    bad = val(CFG_U_PIN_LAUNCH=41)
    cam = val(CFG_U_PIN_LAUNCH=86)
    good = val(CFG_U_PIN_LAUNCH=87)
    clutch = val(CFG_U_PIN_LAUNCH=39)
    r.write(off("CFG_U_MS_ENABLE") + 1, 0x03)
    twice = val(CFG_U_PIN_LAUNCH=39, CFG_U_PIN_FLATSHIFT=39)
    split = val(CFG_U_PIN_LAUNCH=39, CFG_U_PIN_FLATSHIFT=87)
    check("validator: 41 (no read path) and 86 (cam 1's) refused; 87, 39 "
          "accepted; one input for two functions refused, two inputs "
          "accepted", bad != 0 and cam != 0 and good == 0 and clutch == 0
          and twice != 0 and split == 0,
          "41 %04X 86 %04X 87 %04X 39 %04X 39+39 %04X 39+87 %04X"
          % (bad, cam, good, clutch, twice, split))


def main() -> int:
    if "--one" in sys.argv:
        runtime(sys.argv[sys.argv.index("--one") + 1])
        print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
        return 1 if FAILS else 0
    print("=== motorsport switch inputs ===")
    static_checks()
    import me711_image as PI
    rc = subprocess.call([sys.executable, __file__, "--one", PI.STEM])
    rcc = subprocess.call([sys.executable, __file__, "--one", CONTROL_STEM])
    ok = not FAILS and rc == 0 and rcc != 0
    print("\nstatic %d/%d; CONTROL %s %s" % (CHECKS - FAILS, CHECKS,
          CONTROL_STEM, "FAILS, as it must" if rcc else "PASSES - gate blind"))
    print("SWITCH INPUT PROOF %s" % ("PASSES" if ok else "FAILS"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
