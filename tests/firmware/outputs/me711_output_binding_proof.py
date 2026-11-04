#!/usr/bin/env python3
r"""
me711_output_binding_proof.py - an OUTPUT route is accepted only where this
build actually drives it, and no connector route names a CPU pin an on-board
function owns (V95).

    py tests\firmware\outputs\me711_output_binding_proof.py            the image me711_image names
    py tests\firmware\outputs\me711_output_binding_proof.py --control  frozen V93 r2: must FAIL

WHY. Until V95 the descriptor offered cavities 18 and 22 as RELAY_OUT |
LOW_SIDE on P8.2 / P8.1 - on this board the CJ120 chip selects - and
hc_validate() accepted any output route to a CAPABLE cavity: a tacho or relay
on 18/22, a boost valve on 37 or 81, a cam solenoid anywhere VALIDATED and
drove nothing, and the .ini offered the same. The generated pin table also
marked the family sheet's "NOT_ON_MAIN_CPU" as routable, so pinIat = 85 or a
pump on 46 validated with no HAL path behind them.

WHAT IT CHECKS
  1 descriptor: 18/22 are SPECIAL_LOCKED with no resource; no routable cavity
    names a RESERVED_CPU_PINS pin; the rule catches the V93 descriptor
    (a mutation puts 18 back and must be refused)
  2 the generated C pin table: 18/22 offer nothing; every NOT_ON_MAIN_CPU
    cavity is routable = 0
  3 EXECUTED: hc_hal_out_bindable(field, cavity) in the linked image, for the
    six output fields x cavities 1..121, equals generate_config's
    _OUT_BIND_CAVITIES (the table the dropdowns are built from)
  4 EXECUTED: hc_validate() refuses the routes V93 accepted in silence and
    still accepts the car's own (pump 65, boost 104, main relay 23, IAT 26)
  5 the generated .ini offers exactly the bindable cavities for those fields
The control (V93 r2, its own map) has no hc_hal_out_bindable and accepts the
bad routes: it must fail 3 and 4.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
sys.path.insert(0, str(ROOT / "tools" / "config_source"))

import me711_config_state_test as T      # noqa: E402  the rig
import me711_image as PI                 # noqa: E402
import hw_descriptors as HW              # noqa: E402
import generate_config as GC             # noqa: E402
from hanicore_config_schema import PinCap  # noqa: E402

CONTROL = (ROOT / "release/Porsche_ME711_V93_AWT_COMMISSION"
           / "HaniCore_ME711_v93_awt_commission.bin")
DESC_C = ROOT / "firmware/generated/hc_pin_desc_bosch_me711.c"
FIELDS = {"pinFuelPump": "CFG_U_PIN_FUEL_PUMP", "pinMainRelay": "CFG_U_PIN_MAIN_RELAY",
          "pinBoost": "CFG_U_PIN_BOOST", "pinTacho": "CFG_U_PIN_TACHO",
          "pinCam1Sol": "CFG_U_PIN_CAM1_SOL", "pinCam2Sol": "CFG_U_PIN_CAM2_SOL",
          "pinMil": "CFG_U_PIN_MIL",
          "pinIdleValve": "CFG_U_PIN_IDLE_VALVE",
          "pinIdleValve2": "CFG_U_PIN_IDLE_VALVE2"}
FAILS = 0
MAIN_RELAY_HW = int(PinCap.MAIN_RELAY_HW)


def ck(name, ok, detail=""):
    global FAILS
    print("  [%s] %-62s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def off(name):
    for src in (T._gen, T._cfg):
        try:
            return T.d(src, name)
        except (SystemExit, KeyError, AttributeError, TypeError, ValueError):
            continue
    raise SystemExit("%s is not a page offset" % name)


class using_image:
    """Image, map and symbol cache move together (the rig calls by address)."""

    def __init__(self, img):
        self.img, self.map = img, img.with_suffix(".M66")

    def __enter__(self):
        self.saved = (PI.IMG, PI.MAP, PI.MANIFEST, T.MAP_FILE, T._SYMS)
        PI.IMG, PI.MAP = self.img, self.map
        PI.MANIFEST = self.map.with_name("__no_manifest__.json")
        T.MAP_FILE, T._SYMS = self.map, None
        return self

    def __exit__(self, *exc):
        PI.IMG, PI.MAP, PI.MANIFEST, T.MAP_FILE, T._SYMS = self.saved
        return False


def static_checks():
    d = HW.build_me711()
    for n in (18, 22):
        p = d.pin(n)
        ck("descriptor: cavity %d is locked with no resource" % n,
           p.capabilities == PinCap.SPECIAL_LOCKED and not p.hal_resource,
           "%s %r" % (HW.cap_names(p.capabilities), p.hal_resource))
    ck("descriptor: no routable cavity names a reserved CPU pin",
       not HW.reserved_collisions(d), "%s" % (HW.reserved_collisions(d) or "none"))
    # the rule itself must catch the V93 state
    p = d.pin(18)
    d.pins[17] = HW.PhysicalPin(18, p.oem_name, "V93 mutation",
                                (HW.PinProperty(PinCap.RELAY_OUT | PinCap.LOW_SIDE,
                                                HW.EvidenceClass.PROBABLE, "x"),),
                                "P8.2/CC18IO")
    col = HW.reserved_collisions(d)
    ck("mutation: the V93 cavity-18 entry is caught as a collision",
       col == [(18, "P8.2", HW.RESERVED_CPU_PINS["P8.2"][0])], "%s" % col)

    txt = DESC_C.read_text(errors="replace")
    rows = {}
    for m in re.finditer(r"\{\s*0x([0-9A-F]+)u,\s*0x([0-9A-F]+)u,\s*(\d)u,"
                         r"\s*0x([0-9A-F]+)u\s*\},\s*/\*\s*(\d+)", txt):
        rows[int(m.group(5))] = (int(m.group(1), 16), int(m.group(3)))
    for n in (18, 22):
        caps, _rt = rows.get(n, (None, None))
        ck("generated table: cavity %d offers nothing" % n,
           caps is not None and (caps & ~PinCap.SPECIAL_LOCKED) == 0,
           "caps 0x%04X" % (caps or 0))
    d = HW.build_me711()
    noc = [p.number for p in d.pins if p.hal_resource == "NOT_ON_MAIN_CPU"]
    bad = [n for n in noc if rows.get(n, (0, 1))[1] != 0]
    ck("generated table: NOT_ON_MAIN_CPU cavities are routable = 0",
       bool(noc) and not bad, "%d cavities %s; offenders %s" % (len(noc), noc, bad or "none"))


def executed_checks():
    r = T.boot()
    # near in hchal_me711.c until 2026-11-04, far (hcroutes711.c, the far
    # bridge's _f name) since: either is the same function
    fn = None
    for name in ("hc_hal_out_bindable", "hc_hal_out_bindable_f"):
        try:
            T.sym(name)
            fn = name
            break
        except SystemExit:
            pass
    have = fn is not None
    ck("the image has hc_hal_out_bindable()", have)
    if have:
        # What the validator ACCEPTS: the HAL drives it there (bindable)
        # AND the circuit has the capability the field needs (hc_pin_can) -
        # both executed in the image. That set is what the dropdown offers.
        cap = {"pinFuelPump": [T.CAP["RELAY_OUT"]],
               "pinMainRelay": [T.CAP["RELAY_OUT"], MAIN_RELAY_HW],
               "pinBoost": [T.CAP["PWM_OUT"]], "pinTacho": [T.CAP["LOW_SIDE"]],
               "pinCam1Sol": [T.CAP["PWM_OUT"]], "pinCam2Sol": [T.CAP["PWM_OUT"]],
               "pinMil": [T.CAP["LOW_SIDE"]],
               "pinIdleValve": [T.CAP["PWM_OUT"]],
               "pinIdleValve2": [T.CAP["PWM_OUT"]]}
        diff = {}
        for ts, slot in FIELDS.items():
            got = {c for c in range(1, 122)
                   if (r.callb(fn, off(slot), c) & 0xFF)
                   and any(r.callb("hc_pin_can", c, need) & 0xFF
                           for need in cap[ts])}
            if got != GC.out_bind_cavities()[ts]:
                diff[ts] = (sorted(got), sorted(GC.out_bind_cavities()[ts]))
        ck("EXECUTED bindable AND capable == _OUT_BIND_CAVITIES (9 x 121)",
           not diff, "%s" % (diff or "all agree"))

    def val(pins):
        rr = T.boot()
        for slot, v in pins.items():
            rr("hc_cal_set_u8", off(slot), v)
        return rr("hc_validate", T.VAL["HC_VAL_SRC_ACTIVE"])

    CAP = T.VAL["HC_VAL_FAULT_PIN_CAP"]
    import hc_board
    common = (("fuel pump on 18", {"CFG_U_PIN_FUEL_PUMP": 18}),
              ("main relay on 22", {"CFG_U_PIN_MAIN_RELAY": 22}),
              ("boost on 81 (P2.10, no PWM path)", {"CFG_U_PIN_BOOST": 81}),
              ("boost on 37 (P2.13, no PWM path)", {"CFG_U_PIN_BOOST": 37}),
              ("fuel pump on 46 (NOT_ON_MAIN_CPU)", {"CFG_U_PIN_FUEL_PUMP": 46}))
    if hc_board.IS_DC:
        # the ME7.5 DC (its own descriptor): no 120, no cavity-23 relay
        # stage; the cam valve 115 through the CC650's N205 bit
        board = (("cam solenoid 1 on 120 (not on this board)", {"CFG_U_PIN_CAM1_SOL": 120}),
                 ("idle valve on 115 (on/off bit, no PWM unit)",
                  {"CFG_U_IDLE_ACTUATOR": 1, "CFG_U_PIN_IDLE_VALVE": 115}),
                 ("main relay on 23 (no relay stage on this board)",
                  {"CFG_U_PIN_MAIN_RELAY": 23, "CFG_MAIN_RELAY_MODE": 2}))
        own = ({"CFG_U_PIN_FUEL_PUMP": 65, "CFG_U_PIN_BOOST": 104,
                "CFG_U_PIN_CAM1_SOL": 115, "CFG_U_PIN_TACHO": 37},
               "pump 65, boost 104, cam valve 115 (CC650), tacho 37")
    elif hc_board.IS_C4:
        # the C4 board: 120 is not assigned, 26 only bridged to TANS 85,
        # cavity 23 carries no relay stage (run-on is internal)
        board = (("cam solenoid 1 on 120 (not assigned here)", {"CFG_U_PIN_CAM1_SOL": 120}),
                 ("IAT on 26 (bridged to 85, no capability)", {"CFG_U_PIN_IAT": 26}),
                 ("main relay on 23 (no relay stage on this board)",
                  {"CFG_U_PIN_MAIN_RELAY": 23, "CFG_MAIN_RELAY_MODE": 2}))
        own = ({"CFG_U_PIN_FUEL_PUMP": 65, "CFG_U_PIN_BOOST": 104,
                "CFG_U_PIN_CAM1_SOL": 115, "CFG_U_PIN_IAT": 85},
               "pump 65, boost 104, cam valve 115, IAT 85")
    else:
        board = (("tacho on 18 (CJ120 CS P8.2)", {"CFG_U_PIN_TACHO": 18}),
                 ("tacho on 22 (CJ120 CS P8.1)", {"CFG_U_PIN_TACHO": 22}),
                 ("cam solenoid 1 on 104", {"CFG_U_PIN_CAM1_SOL": 104}),
                 ("IAT on 85 (NOT_ON_MAIN_CPU)", {"CFG_U_PIN_IAT": 85}))
        # mainRelayMode AUTO (2), as on the car page: cavity 23 is the CJ910's
        # hardware stage and honours AUTO only, so the board default's mode
        # would be refused for a reason that has nothing to do with binding
        own = ({"CFG_U_PIN_FUEL_PUMP": 65, "CFG_U_PIN_BOOST": 104,
                "CFG_U_PIN_MAIN_RELAY": 23, "CFG_MAIN_RELAY_MODE": 2,
                "CFG_U_PIN_IAT": 26}, "pump 65, boost 104, MR 23, IAT 26")
    for label, pins in common + board:
        rc = val(pins)
        ck("refused: %s" % label, bool(rc & CAP), "rc 0x%04X" % rc)
    rc = val(own[0])
    ck("accepted: the car's own routes (%s)" % own[1],
       not (rc & CAP), "rc 0x%04X" % rc)


def ini_checks():
    ini = PI.INI
    if not ini.exists():
        ck("the image's generated .ini exists", False, str(ini))
        return
    txt = ini.read_text(errors="replace")
    for ts in FIELDS:
        m = re.search(r"^\s*%s\s*=\s*bits,\s*U08,\s*\d+,\s*\[0:7\],(.*)$" % ts, txt, re.M)
        if not m:
            ck(".ini: %s is a dropdown" % ts, False)
            continue
        labels = [s.strip().strip('"') for s in m.group(1).split('",')]
        offered = {i for i, s in enumerate(labels) if s not in ("INVALID", "NONE")}
        ck(".ini: %s offers exactly the bindable cavities" % ts,
           offered == GC.out_bind_cavities()[ts],
           "offered %s" % sorted(offered))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", action="store_true",
                    help="run the executed checks on frozen V93 r2; must FAIL")
    a = ap.parse_args()
    print("=== output routes bind only where the HAL drives them (V95) ===\n")
    if a.control:
        print("  CONTROL image %s\n" % CONTROL.name)
        with using_image(CONTROL):
            executed_checks()
        if FAILS:
            print("\nCONTROL (V93 r2): FAILS as it must (%d)" % FAILS)
            return 0
        print("\nCONTROL PASSED - the gate cannot tell V93 from the fix")
        return 1
    print("  image %s\n" % PI.image().name)
    static_checks()
    executed_checks()
    ini_checks()
    print("\nOUTPUT BINDING PROOF %s - %d failed" % ("PASSES" if not FAILS else
                                                   "FAILS", FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
