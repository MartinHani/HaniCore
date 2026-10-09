#!/usr/bin/env python3
r"""
me711_config_state_test.py - execute the DESIRED/ACTIVE configuration state
machine out of the real linked image and prove its semantics.

    py tests\firmware\config\me711_config_state_test.py

WHAT THIS IS DEFENDING, in one sentence: a TunerStudio write must never reach a
running engine through a state that describes no engine at all.

Everything below is EXECUTED from the linked flash image in c167sim - the same
harness me711_hal_test.py uses - not reasoned about from the source. The
functions under test are hc_cfg_mgr_write_u8(), hc_cfg_mgr_apply_now(),
hc_validate() and hc_pin_can(), and the reads that check them are hc_cal_u8()
(the ACTIVE image the runtime reads) and hc_cfg_mgr_read_u8() (the DESIRED
image the host reads).

THE FIVE THINGS THE PREVIOUS IMPLEMENTATION GOT WRONG, each with a check here
that FAILS against it:

  1. It copied the ENTIRE staged 4096-byte page into the active page at RPM
     zero, restart-required fields included - so a cylinder count edit reached
     the running scheduler the moment the engine stopped. See
     `restart_required_never_reaches_active`.
  2. It classified a write by testing the offset against hand-written ranges
     in get_policy(); the policy is now per field, generated from the model.
     See `policy_comes_from_the_generated_table`.
  3. Its pin capability test returned true on ANY overlap, so a pin
     advertising only LOW_SIDE satisfied a request for INJ_OUT|LOW_SIDE. See
     `a_pin_needs_every_capability_not_any`.
  4. It ran a whole-configuration validation on EVERY byte written. See
     `a_page_burn_does_not_validate_per_byte`.
  5. It applied a failed transaction's dirty mask away. See
     `a_refused_apply_leaves_active_untouched`.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import c167sim as S        # noqa: E402
import me711_image as PI
import me711_dpp as _dpp  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
TDIR = ROOT / "firmware/targets/me711"
SHARED = ROOT / "firmware"

_tgt = (TDIR / "hctarget.h").read_text(errors="replace")
_cfg = (SHARED / "config/hcconfig.h").read_text(errors="replace")
_gen = (SHARED / "generated/hc_config_generated.h").read_text(errors="replace")
_val = (SHARED / "config/hc_validation.h").read_text(errors="replace")

MAP_FILE = PI.MAP
FAILS = 0
CHECKS = 0


def d(txt, name):
    m = re.search(r"#define\s+%s\s+(0x[0-9A-Fa-f]+|\d+)u?" % name, txt)
    if not m:
        raise SystemExit(f"{name} not found")
    return int(m.group(1), 0)


PAGE = d(_cfg, "HC_CFG_SIZE")
CORE = d(_cfg, "HC_CFG_CORE")
MAX_CYL = d(_cfg, "HC_MAX_CYL")
UNI_BASE = d(_cfg, "CFG_UNIVERSAL_BASE")
UNI_SIZE = d(_cfg, "CFG_UNIVERSAL_SIZE")
MAGIC = d(_gen, "HC_UNIVERSAL_MAGIC")
SCHEMA = d(_gen, "HC_UNIVERSAL_SCHEMA")
PIN_NONE = d(_gen, "HC_PIN_NONE")

# Offsets, from the generated header - never retyped.
# CFG_CAM_ENABLE is a CORE field declared in hcconfig.h, so it comes
# from there rather than from the universal-block header.
CAM_ENABLE_OFF = d(_cfg, "CFG_CAM_ENABLE")
O = {n: d(_gen, n) for n in (
    # V63: a cam cycle mode needs GEOMETRY, not just a mode and a pin.
    "CFG_U_CAM_REFS",
    "CFG_U_MAGIC", "CFG_U_SCHEMA", "CFG_U_PIN_INJ", "CFG_U_PIN_IGN",
    "CFG_U_PIN_CRANK", "CFG_U_PIN_CAM1", "CFG_U_PIN_CAM2", "CFG_U_SYNC_MODE",
    "CFG_U_INJ_STRATEGY", "CFG_U_IGN_STRATEGY", "CFG_U_TRIG_DECODER",
    "CFG_U_STOICH_X100", "CFG_U_TEST_MODE", "CFG_U_LAM1_SRC",
    "CFG_U_LAM2_SRC", "CFG_U_LAM1_CYLMASK", "CFG_U_LAM2_CYLMASK",
    "CFG_U_TPS_CORR", "CFG_U_TPS_TOL_X10", "CFG_U_APP_TOL_X10",
    "CFG_U_PIN_TPS1", "CFG_U_PIN_TPS2", "CFG_U_PIN_APP1", "CFG_U_PIN_APP2",
    "CFG_U_MS_ENABLE", "CFG_U_PIN_LAUNCH", "CFG_U_PIN_BOOST",
)}
for n in ("CFG_CYLINDERS", "CFG_STROKES", "CFG_SY_TEETH", "CFG_SY_GAP",
          "CFG_TRIG_GAP_RATIO_X10", "CFG_TRIG_TIMEOUT_MS", "CFG_TRIG_MIN_TEETH",
          "CFG_REV_MAX", "CFG_REV_LIMIT", "CFG_CRANK_RPM_MAX", "CFG_VERSION",
          "CAL_FUEL_MAP", "CAL_FUEL_RPM_AX", "CAL_IGN_MAP", "CAL_DBW_ENABLE",
          "CAL_TPS1_MIN", "CAL_TPS1_MAX", "CAL_PEDAL1_MIN", "CAL_PEDAL1_MAX",
          "CAL_RESERVED", "CFG_OUTPUTS_ARMED", "CAL_REVLIM_MODE",
          "CAL_REVLIM_PATTERN", "CAL_DBW_DEV_X10", "CAL_DBW_DEV_MS",
          "CAL_DBW_MIN_X10", "CAL_DBW_MAX_X10", "CAL_LOAD_SOURCE"):
    O[n] = d(_cfg, n)

VAL = {n: d(_val, n) for n in (
    "HC_VAL_OK", "HC_VAL_FAULT_SCHEMA", "HC_VAL_FAULT_CYLINDERS",
    "HC_VAL_FAULT_TDC", "HC_VAL_FAULT_TRIGGER", "HC_VAL_FAULT_SYNC",
    "HC_VAL_FAULT_PIN_CAP", "HC_VAL_FAULT_PIN_CONFLICT", "HC_VAL_FAULT_REV",
    "HC_VAL_FAULT_DBW", "HC_VAL_FAULT_AXIS", "HC_VAL_FAULT_LAMBDA",
    "HC_VAL_FAULT_STRATEGY", "HC_VAL_FAULT_TARGET",
    "HC_VAL_FAULT_NOT_STOPPED", "HC_VAL_SRC_ACTIVE", "HC_VAL_SRC_DESIRED",
)}
CAP = {n: d(_gen, "HC_PINCAP_" + n) for n in
       ("AIN", "DIN", "FREQ_IN", "VR_IN", "HALL_IN", "LOW_SIDE", "PWM_OUT",
        "INJ_OUT", "IGN_OUT", "DBW_HBRIDGE", "RELAY_OUT", "SPECIAL_LOCKED")}
E = {n: d(_gen, "HC_" + n) for n in
     ("INJ_BATCH", "INJ_SEMI_SEQ", "INJ_SEQUENTIAL", "IGN_WASTED_PAIRED",
      "IGN_WASTED_COP", "IGN_SEQUENTIAL_COP", "IGN_DISTRIBUTOR",
      "SYNC_NONE", "SYNC_CRANK_ONLY", "SYNC_CAM1_CYCLE", "SYNC_DUAL_CAM",
      "TRIGDEC_CUSTOM", "TRIGDEC_MISSING_TOOTH", "TRIGDEC_EVEN_TOOTH",
      "TRIGDEC_BOSCH_ME711", "LAMBDA_OFF", "LAMBDA_EXTERNAL_ANALOG",
      "TRACK_OPPOSITE", "TRACK_SCALED")}

GRP = {m.group(2): int(m.group(3))
       for m in re.finditer(r"(HC_GRP_(\w+))\s*=\s*(\d+)", _gen)}


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<62s} {detail}")
    if not ok:
        FAILS += 1


_SYMS = None


def sym(name):
    global _SYMS
    if _SYMS is None:
        _SYMS = {}
        for m in re.finditer(r"^\s*([0-9A-F]{6})H\s+(\w+)\s",
                             MAP_FILE.read_text(errors="replace"), re.M):
            _SYMS.setdefault(m.group(2), int(m.group(1), 16))
    if name not in _SYMS:
        raise SystemExit(f"{name} not in the map - build the target first")
    return _SYMS[name]


class Rig:
    """Enough of a C167 to execute one Keil SMALL function and read R4.

    Keil passes the first word arguments in R8, R9, ... - verified against the
    CODE listing of hc_cfg_mgr_write_u8(), where `off` lands in R8 and `v` in
    R9 - so positional arguments here are positional arguments there."""

    def __init__(self):
        img = PI.image().read_bytes()
        self.m = S.Mem(img)
        self.m._cbank = bytearray(0x10000)
        self.c = S.CPU(self.m, 0, 0)
        # DPP1 WAS A LITERAL AND IT WAS THE V52 PAGE. See tools/lib/me711_dpp.py.
        _dpp.apply(self.m)
        self.m.sfr[0xFE10] = 0xFC00
        # R0 = Keil's software stack. This used to be a literal address, and
        # hc_cfg is at 0xF98C: the harness was writing its own call frames over
        # the first hundred bytes of the very configuration page this gate
        # exists to test, and passing 76 of 77 checks anyway. CFG_CYLINDERS is
        # at offset 2 and read back 251. See the note in me711_image.py - this
        # is the third time one literal stack address has imitated a firmware
        # defect.
        self.stack_top = PI.user_stack_top()
        self.m.w16(0xFC00, self.stack_top)
        # Opt-in: publish adc_raw and the S5500 window as accepted samples
        # before every eng_service() (see publish_samples()).
        self.publish_on_service = False

    # THE HAL ACCEPTS A SENSOR ONLY AS A SAMPLE. Since the acquisition-
    # freshness layer (hcfresh711.c) a main channel is valid only when the
    # 1 ms tick has published a tagged conversion through hc_hal_main_sample()
    # less than TGT_ADC_FRESH_MS ago, and an ASIC channel only inside an
    # accepted S5500 frame less than TGT_ASIC_FRESH_MS old. A function-call rig
    # runs neither the tick nor the frame exchange, so a value poked into
    # adc_raw or the window read as a stale sensor (CLT -40 C, MAP 0, no air).
    # This does what the main loop guarantees before eng_service() runs.
    ADC_META = 0x380000 + 0x7400 + 0x20       # TGT_RAM_ROUTE + 0x20
    ADC_CH_COUNT = 16

    def publish_samples(self):
        tick = self.g16("hc_tick_ms")
        adc = sym("adc_raw") & 0xFFFF
        for ch in range(self.ADC_CH_COUNT):
            raw = self.m.r16(adc + 2 * ch) & 0x3FF
            self("hc_hal_main_sample", ch, (ch << 12) | raw, 1, tick)
        self.m.w16(self.ADC_META + 2 * 33, tick)      # ASIC_SAMPLE_MS
        self.m.w16(self.ADC_META + 2 * 34, 1)         # ASIC_SAMPLE_LIVE
        self.m.w8(sym("hc_asic_run_live") & 0xFFFF, 1)

    def __call__(self, fn, *args, steps=400000):
        if fn == "eng_service" and self.publish_on_service:
            self.publish_samples()
        a = sym(fn)
        self.m.w16(self.c.cp(), self.stack_top)
        self.m.sfr[0xFE14], self.m.sfr[0xFE16] = 0xF200, 0xFE00
        sp = 0xF700
        for w in (a >> 16, 0xFFFE):
            sp = (sp - 2) & 0xFFFF
            self.m.w16(sp, w)
        self.m.sfr[0xFE12] = sp
        for i, v in enumerate(args):
            self.c.sr(8 + i, v & 0xFFFF)
        self.c.csp, self.c.ip = a >> 16, a & 0xFFFF
        for _ in range(steps):
            if self.c.ip == 0xFFFE:
                return self.c.gr(4) & 0xFFFF
            self.c.step()
        raise SystemExit(f"{fn} did not return within {steps} steps")

    def callb(self, fn, *args):
        """A function whose C return type is `unsigned char`.

        Keil returns a byte in RL4 and LEAVES RH4 ALONE, so reading R4 as a
        word gives the byte with whatever the function last happened to put in
        the high half. hc_pin_can(40, INJ_OUT) really returns 0 and reads back
        as 0x6900 if you forget - which looked exactly like a switch input
        being accepted as an injector driver, and was a bug in this file."""
        return self(fn, *args) & 0xFF

    # --- the two images -------------------------------------------------
    def active(self, off):
        return self.callb("hc_cal_u8", off)

    def desired(self, off):
        return self.callb("hc_cfg_mgr_read_u8", off)

    def write(self, off, val):
        self("hc_cfg_mgr_write_u8", off, val)

    def g16(self, name):
        return self.m.r16(sym(name) & 0xFFFF)

    def g8(self, name):
        return self.m.r8(sym(name) & 0xFFFF) & 0xFF


def boot():
    """A rig with hc_cfg_init() and hc_cfg_mgr_init() already run."""
    r = Rig()
    r("hc_cfg_init")
    r("hc_cfg_mgr_init")
    return r


def make_valid(r):
    """Write a configuration into DESIRED that validates cleanly, using only
    pins this board's own descriptor says can do the job. Returns the injector
    pins used."""
    # A four-cylinder, batch fuel, paired wasted spark, crank-only engine on
    # the ME7.1.1's own EV/ZUE connector pins.
    inj = [96, 97, 88, 89]      # EV1..EV4 - Bosch's own connector sheet
    ign = [102, 103, 94, 95]    # ZUE1..ZUE4
    r.write(O["CFG_CYLINDERS"], 4)
    r.write(O["CFG_STROKES"], 4)
    for i in range(MAX_CYL):
        ang = (0, 5400, 1800, 3600, 900, 2700, 4500, 6300)[i]
        r.write(O["CFG_TDC_CYL"] if False else d(_cfg, "CFG_TDC_CYL") + 2 * i,
                (ang >> 8) & 0xFF)
        r.write(d(_cfg, "CFG_TDC_CYL") + 2 * i + 1, ang & 0xFF)
    for i in range(12):
        r.write(O["CFG_U_PIN_INJ"] + i, inj[i] if i < 4 else PIN_NONE)
        r.write(O["CFG_U_PIN_IGN"] + i, ign[i] if i < 4 else PIN_NONE)
    r.write(O["CFG_U_PIN_CRANK"], 82)
    r.write(O["CFG_U_PIN_CAM1"], 86)
    r.write(O["CFG_U_PIN_CAM2"], PIN_NONE)
    r.write(O["CFG_U_SYNC_MODE"], E["SYNC_CRANK_ONLY"])
    r.write(O["CFG_U_INJ_STRATEGY"], E["INJ_BATCH"])
    r.write(O["CFG_U_IGN_STRATEGY"], E["IGN_WASTED_PAIRED"])
    r.write(O["CFG_U_TRIG_DECODER"], E["TRIGDEC_MISSING_TOOTH"])
    r.write(O["CFG_SY_TEETH"], 0)
    r.write(O["CFG_SY_TEETH"] + 1, 60)
    r.write(O["CFG_SY_GAP"], 2)
    r.write(O["CFG_TRIG_GAP_RATIO_X10"], 0)
    r.write(O["CFG_TRIG_GAP_RATIO_X10"] + 1, 25)
    r.write(O["CFG_TRIG_MIN_TEETH"], 6)
    r.write(O["CFG_TRIG_TIMEOUT_MS"], 200)
    return inj, ign


def _hw_instr_per_ms(clocks_per_instr=4.0):
    """Instructions the real part executes in one millisecond.

    fCPU comes from hctarget.h. Four clocks per instruction is twice the C166
    floor of two (one state time), which tools/analysis/me711_asic_cs_timing.py uses and
    correctly calls a floor; doubling it absorbs taken branches, calls and the
    external-SRAM wait states BUSCON1 = 0x040D implies for the configuration
    layer's huge-pointer accesses. Erring high on cost means erring low on
    margin, which is the safe direction for a budget check.
    """
    import re as _re
    h = (ROOT / "firmware/targets/me711/hctarget.h").read_text(errors="replace")
    m = _re.search(r"#define\s+TGT_FCPU_HZ\s+(\d+)", h)
    if not m:
        raise SystemExit("TGT_FCPU_HZ not found in hctarget.h")
    return float(m.group(1)) / clocks_per_instr / 1000.0


def main() -> int:
    print("=== HaniCore Bosch ME7.1.1 - configuration state machine ===\n")
    print(f"  image  {PI.image().name}")
    print(f"  sha256 {PI.sha256()}\n")

    # ================================================================== 1
    print("--- the two images exist and start equal ---")
    r = boot()
    diff = [o for o in range(0, PAGE, 7) if r.active(o) != r.desired(o)]
    check("after init, DESIRED is an exact copy of ACTIVE", not diff,
          "sampled every 7th byte of 4096" if not diff
          else f"{len(diff)} differ, first at {diff[0]}")
    check("nothing is dirty at boot", r.g16("hc_cfg_dirty_groups") == 0,
          f"mask 0x{r.g16('hc_cfg_dirty_groups'):04X}")
    check("no restart is pending at boot",
          r.g8("hc_cfg_restart_pending") == 0)
    check("the universal block was migrated into schema %d" % SCHEMA,
          (r.active(O["CFG_U_MAGIC"]) << 8 | r.active(O["CFG_U_MAGIC"] + 1))
          == MAGIC
          and (r.active(O["CFG_U_SCHEMA"]) << 8
               | r.active(O["CFG_U_SCHEMA"] + 1)) == SCHEMA,
          f"magic 0x{MAGIC:04X}, migrated={r.g8('hc_cfg_migrated')}")

    unassigned = all(r.active(O["CFG_U_PIN_INJ"] + i) == PIN_NONE
                     for i in range(12))
    check("and the migration invented NO pin assignment", unassigned,
          "all 12 injector pins are HC_PIN_NONE")

    # ================================================================== 2
    print("\n--- LIVE_APPLY: calibration reaches the runtime at once ---")
    r = boot()
    before = r.active(O["CAL_FUEL_MAP"])
    r.write(O["CAL_FUEL_MAP"], (before + 37) & 0xFF)
    check("a fuel map cell is LIVE and lands in ACTIVE immediately",
          r.active(O["CAL_FUEL_MAP"]) == (before + 37) & 0xFF,
          f"{before} -> {r.active(O['CAL_FUEL_MAP'])}")
    check("and it marks NO apply group dirty",
          r.g16("hc_cfg_dirty_groups") == 0)

    # A LIVE write with the engine TURNING must still land: that is what
    # "live" means, and a policy model that gated it on RPM would make every
    # table untunable on a running engine.
    r.write(O["CAL_IGN_MAP"], 200)
    check("a LIVE write lands even though nothing has said RPM is zero",
          r.active(O["CAL_IGN_MAP"]) == 200)

    # ================================================================== 3
    print("\n--- RPM_ZERO_APPLY: staged while turning, atomic at zero ---")
    r = boot()
    make_valid(r)
    # Everything above is RPM_ZERO, so the active image must still be the
    # boot image for those fields.
    check("a routing write does NOT reach ACTIVE while staged",
          r.active(O["CFG_U_PIN_INJ"]) == PIN_NONE
          and r.desired(O["CFG_U_PIN_INJ"]) == 96,
          f"ACTIVE={r.active(O['CFG_U_PIN_INJ'])} "
          f"DESIRED={r.desired(O['CFG_U_PIN_INJ'])}")
    dirty = r.g16("hc_cfg_dirty_groups")
    check("and it marked the injector-routing group dirty",
          dirty & (1 << GRP["INJECTOR_ROUTING"]),
          f"mask 0x{dirty:04X}")

    rc = r("hc_cfg_mgr_apply_now", 1200)
    check("an apply is REFUSED while the engine turns",
          rc == VAL["HC_VAL_FAULT_NOT_STOPPED"], f"rc=0x{rc:04X}")
    check("and ACTIVE is still untouched",
          r.active(O["CFG_U_PIN_INJ"]) == PIN_NONE)

    rc = r("hc_cfg_mgr_apply_now", 0)
    check("at RPM zero the transaction applies", rc == VAL["HC_VAL_OK"],
          f"rc=0x{rc:04X} faults=0x{r.g16('hc_cfg_validation'):04X}")
    landed = [r.active(O["CFG_U_PIN_INJ"] + i) for i in range(4)]
    check("and every injector pin is now in ACTIVE", landed == [96, 97, 88, 89],
          str(landed))
    check("the dirty mask is clear", r.g16("hc_cfg_dirty_groups") == 0)
    check("the active revision counter advanced",
          r.g16("hc_cfg_active_rev") == 1)

    # ================================================================== 4
    print("\n--- LATEST STATE, not a replay: A -> B -> C -> D applies D ---")
    r = boot()
    make_valid(r)
    r("hc_cfg_mgr_apply_now", 0)
    seen = []
    for pin in (97, 88, 112):          # B, C, D - all real EV pins
        r.write(O["CFG_U_PIN_INJ"], pin)
        seen.append(r.active(O["CFG_U_PIN_INJ"]))
    check("the runtime saw NONE of the intermediate values",
          seen == [96, 96, 96],
          f"ACTIVE stayed {seen} while DESIRED went 97, 88, 112")
    r("hc_cfg_mgr_apply_now", 0)
    check("and the apply installs the LAST one, not the first",
          r.active(O["CFG_U_PIN_INJ"]) == 112,
          f"ACTIVE = {r.active(O['CFG_U_PIN_INJ'])}")
    check("exactly one apply happened, not three",
          r.g16("hc_cfg_active_rev") == 2,
          f"active_rev={r.g16('hc_cfg_active_rev')}")

    # ================================================================== 5
    print("\n--- RESTART_REQUIRED never reaches the running system ---")
    r = boot()
    make_valid(r)
    r("hc_cfg_mgr_apply_now", 0)
    was = r.active(O["CFG_CYLINDERS"])
    r.write(O["CFG_CYLINDERS"], 6)
    check("a cylinder-count write does not reach ACTIVE",
          r.active(O["CFG_CYLINDERS"]) == was
          and r.desired(O["CFG_CYLINDERS"]) == 6,
          f"ACTIVE={r.active(O['CFG_CYLINDERS'])} DESIRED=6")
    check("and it is reported as restart-pending",
          r.g8("hc_cfg_restart_pending") == 1)
    check("it marks NO apply group dirty - it is not an RPM-zero change",
          r.g16("hc_cfg_dirty_groups") == 0,
          f"mask 0x{r.g16('hc_cfg_dirty_groups'):04X}")
    r("hc_cfg_mgr_apply_now", 0)
    check("AND AN RPM-ZERO APPLY STILL DOES NOT INSTALL IT",
          r.active(O["CFG_CYLINDERS"]) == was,
          "this is the check the previous whole-image copy failed")

    # setting it back clears the pending flag rather than latching it
    r.write(O["CFG_CYLINDERS"], was)
    check("typing the old value back clears restart-pending",
          r.g8("hc_cfg_restart_pending") == 0)

    # ================================================================== 6
    print("\n--- a refused transaction changes nothing ---")
    r = boot()
    make_valid(r)
    r("hc_cfg_mgr_apply_now", 0)
    good = r.active(O["CFG_U_PIN_INJ"])
    # Pin 1 is EL_MA, a power ground: SPECIAL_LOCKED, no injector capability.
    r.write(O["CFG_U_PIN_INJ"], 1)
    rc = r("hc_cfg_mgr_apply_now", 0)
    check("an injector on a power ground is REFUSED",
          rc & VAL["HC_VAL_FAULT_PIN_CAP"], f"faults=0x{rc:04X}")
    check("ACTIVE keeps the previous working routing",
          r.active(O["CFG_U_PIN_INJ"]) == good, f"still {good}")
    check("the dirty mask is KEPT so the tuner can fix and retry",
          r.g16("hc_cfg_dirty_groups") != 0,
          f"mask 0x{r.g16('hc_cfg_dirty_groups'):04X}")
    check("and the refusal is counted",
          r.g16("hc_cfg_apply_refused") == 1)
    # fix it and retry - the SAME transaction must go through
    r.write(O["CFG_U_PIN_INJ"], 96)
    rc = r("hc_cfg_mgr_apply_now", 0)
    check("fixing the value lets the same transaction complete",
          rc == VAL["HC_VAL_OK"] and r.active(O["CFG_U_PIN_INJ"]) == 96)

    # ================================================================== 6a
    print("\n--- and it is not re-validated on every main-loop pass ---")
    #
    # THE V57 REGRESSION, AND IT WAS FOUND ON THE REAL ECU RATHER THAN HERE.
    #
    # hc_cfg_mgr_service() is called from the main loop every pass. Until V57
    # it called hc_cfg_mgr_apply_now() every pass while a staged RPM_ZERO
    # transaction was waiting, and apply_now() begins with hc_validate() over
    # the whole 4096-byte DESIRED image - cylinders, TDC duplicates, every
    # pin, every capability. A transaction that cannot be applied is refused
    # for ever, so that ran for ever.
    #
    # MEASURED ON THE ECU, 2026-09-15: writing syncMode = 1 while pinCrank was
    # unassigned took the main loop from 1364 to 175 passes per second. The
    # live Burn programs one flash word per admitted window and takes its
    # windows from those passes, so every Burn after such an edit inherited
    # the same factor - past the 6000 ms live-Burn deadline and past
    # TunerStudio's 8000 ms blockReadTimeout.
    #
    #
    # THE CONTROL IS THE FIRST MEASUREMENT: `first` is what one validation
    # costs, and it is thousands of steps. A firmware without the fix scores
    # the same number on the second pass. That is what this distinguishes.
    r = boot()
    make_valid(r)
    r("hc_cfg_mgr_service", 0)
    quiet = _steps(r, "hc_cfg_mgr_service", 0)
    check("service() is cheap while nothing is staged", quiet < 200,
          f"{quiet} steps")

    r.write(O["CFG_U_PIN_INJ"], 1)          # an injector on a power ground
    first = _steps(r, "hc_cfg_mgr_service", 0)
    check("the pass after the edit really does validate", first > 2000,
          f"{first} steps")
    dirty = r.g16("hc_cfg_dirty_groups")
    check("the group is still staged so the tuner can fix it",
          dirty & 0x7FFF, f"mask 0x{dirty:04X}")
    check("and the refusal is now RECORDED in bit 15", dirty & 0x8000,
          f"mask 0x{dirty:04X}")

    again = _steps(r, "hc_cfg_mgr_service", 0)
    check("the NEXT pass does not validate the same bytes again",
          again < 200, f"{again} steps against {first} for the first")
    refused = r.g16("hc_cfg_apply_refused")
    for _ in range(20):
        _steps(r, "hc_cfg_mgr_service", 0)
    check("twenty more passes cost nothing and count nothing",
          r.g16("hc_cfg_apply_refused") == refused,
          f"refused {refused} -> {r.g16('hc_cfg_apply_refused')}")

    r.write(O["CFG_U_PIN_INJ"], 96)         # the tuner fixes it
    check("a new write clears the blocked bit",
          (r.g16("hc_cfg_dirty_groups") & 0x8000) == 0,
          f"mask 0x{r.g16('hc_cfg_dirty_groups'):04X}")
    retry = _steps(r, "hc_cfg_mgr_service", 0)
    check("the next pass validates again and the transaction lands",
          retry > 2000 and r.active(O["CFG_U_PIN_INJ"]) == 96
          and r.g16("hc_cfg_dirty_groups") == 0,
          f"{retry} steps, ACTIVE={r.active(O['CFG_U_PIN_INJ'])}, "
          f"mask 0x{r.g16('hc_cfg_dirty_groups'):04X}")

    # AND A TURNING ENGINE STILL DEFERS RATHER THAN BLOCKS. A write made while
    # the engine turns must be picked up the moment it stops, which means the
    # rpm branch may not consume the retry.
    # Identity writes keep the geometry revision stable. A different valid
    # cavity still stages a transaction, which must wait for standstill.
    rev=r.g16("hc_cfg_desired_rev")
    active_rev=r.g16("hc_cfg_active_rev")
    r.write(O["CFG_U_PIN_INJ"], 96)
    check("identical writes do not stage work or invalidate geometry",
          r.g16("hc_cfg_dirty_groups")==0 and r.g16("hc_cfg_desired_rev")==rev
          and r.g16("hc_cfg_active_rev")==active_rev)
    r.write(O["CFG_U_PIN_INJ"], 112)
    check("a write while the engine turns stages the group",
          r.g16("hc_cfg_dirty_groups") & 0x7FFF,
          f"mask 0x{r.g16('hc_cfg_dirty_groups'):04X}")
    spin = _steps(r, "hc_cfg_mgr_service", 1200)
    check("service() at 1200 rpm does not validate at all", spin < 200,
          f"{spin} steps")
    check("and does not mark the transaction blocked",
          (r.g16("hc_cfg_dirty_groups") & 0x8000) == 0,
          f"mask 0x{r.g16('hc_cfg_dirty_groups'):04X}")
    stopped = _steps(r, "hc_cfg_mgr_service", 0)
    check("stopping the engine applies it on the next pass",
          stopped > 2000 and r.g16("hc_cfg_dirty_groups") == 0
          and r.active(O["CFG_U_PIN_INJ"]) == 112,
          f"{stopped} steps, mask "
          f"0x{r.g16('hc_cfg_dirty_groups'):04X}")

    # ================================================================== 7
    print("\n--- a pin needs EVERY capability, not any of them ---")
    r = boot()
    # pin 96 is EV1: INJ_OUT|LOW_SIDE. pin 40 is AC_S: DIN only.
    check("pin 96 (EV1) satisfies INJ_OUT",
          r.callb("hc_pin_can", 96, CAP["INJ_OUT"]) == 1)
    check("pin 96 does NOT satisfy INJ_OUT|AIN",
          r.callb("hc_pin_can", 96, CAP["INJ_OUT"] | CAP["AIN"]) == 0,
          "all bits, not any")
    check("pin 40 (AC_S, a switch input) does NOT satisfy INJ_OUT",
          r.callb("hc_pin_can", 40, CAP["INJ_OUT"]) == 0)
    check("pin 1 (EL_MA, power ground) satisfies nothing",
          r.callb("hc_pin_can", 1, CAP["DIN"]) == 0
          and r.callb("hc_pin_can", 1, CAP["LOW_SIDE"]) == 0,
          "SPECIAL_LOCKED")
    check("pin 121 has no capability at all - Bosch's sheet leaves it blank",
          r.callb("hc_pin_can", 121, CAP["RELAY_OUT"]) == 0
          and r.callb("hc_pin_can", 121, 0) == 0,
          "not a secondary power feed")
    # THIS ASSERTION HAS NOW BEEN WRITTEN BOTH WAYS, AND BOTH TIMES THE
    # REASONING WAS SOUND. It is worth keeping the whole story.
    #
    # First it said "pin 21 is not a relay output - it is ZAS2_S", which was
    # the defect the project rules forbid: an OEM signal name is not an
    # electrical property. So it was inverted to "pin 21 IS relay capable",
    # on the ground that cavity 21 is a CJ420 smart low-side channel on the
    # same die as EV7 and EV8, TVS clamped - the right driver class for a
    # relay coil.
    #
    # THAT WAS THE RIGHT RULE APPLIED TO THE WRONG DATA. The die, the TVS and
    # the name all came from `Steckerb. ME7.1.XLS`, a VW/Audi ME7.1 C4
    # connector workbook, and against the ME7.1.1 sheet that workbook is wrong
    # for the whole 18..24 block. Cavity 21 on THIS board is KL15 - the
    # ignition-lock feed into the CJ910's enable pin - settled by three
    # agreeing sources, one of which is this ECU on the bench: remove +12 V
    # from cavity 21 while 3 and 62 stay powered and it goes OFFLINE.
    #
    # The rule stands. The data under it did not. See
    # tests/firmware/config/me711_cavity_truth_proof.py.
    check("cavity 21 is a POWER INPUT and advertises no drive capability",
          r.callb("hc_pin_can", 21, CAP["RELAY_OUT"]) == 0
          and r.callb("hc_pin_can", 21, CAP["LOW_SIDE"]) == 0,
          "KL15 - removing it takes this ECU offline, measured")
    # AND THE REST OF THE BLOCK IS NO LONGER LOCKED WHOLESALE.
    #
    # This required cavities 18..24 to advertise NOTHING, because the block was
    # locked pending ME7.1.1 evidence - the project rules: "no cavity in
    # 18..24 may be routed or bench-commanded until the descriptor is
    # regenerated against ME7.1.1 evidence."
    #
    # That evidence is in the tree now. `the ME7.1.1 schematic` names
    # A_S_ZAS2 on 18, A_T_EV8 on 19, A_S_ZAS1 on 22 and A_T_EV7 on 24, and
    # me711_iomap.csv gives each a MAIN CPU CAPCOM channel with both ME7.1.1
    # columns agreeing on EV7 and EV8. So the assertion becomes the SPECIFIC
    # one, which is stronger than a blanket refusal: these four carry the
    # capability the sheet gives them, and 20/21/23 still carry none.
    check("cavities 19 and 24 ARE injector outputs", 
          r.callb("hc_pin_can", 19, CAP["INJ_OUT"]) == 1
          and r.callb("hc_pin_can", 24, CAP["INJ_OUT"]) == 1,
          "EV8 on 19 and EV7 on 24 - so this board has EIGHT injectors")
    # V96 LOCKED 18 AND 22 AGAIN, on better evidence: on THIS board P8.2 /
    # P8.1 are the CJ120 chip selects (the ME7.1.1 schematic nets CS_CJ120_ZAS1_P81 /
    # ..ZAS2_P82 via bridges B1073 / B1053), driven HIGH at startup, and
    # hw_descriptors.RESERVED_CPU_PINS refuses any routable cavity that names
    # a board-owned pin. A relay routed there would deselect
    # or select a wideband chip. This gate still expected the V62 relay
    # capability and went red on V96 and V97 alike.
    check("cavities 18 and 22 are LOCKED (the CJ120 chip selects, V96)",
          r.callb("hc_pin_can", 18, CAP["RELAY_OUT"]) == 0
          and r.callb("hc_pin_can", 22, CAP["RELAY_OUT"]) == 0
          and r.callb("hc_pin_can", 18, CAP["LOW_SIDE"]) == 0
          and r.callb("hc_pin_can", 22, CAP["LOW_SIDE"]) == 0,
          "P8.2 / P8.1 = CS_CJ120 on this board")
    check("and 20, 21 and 23 are STILL locked",
          all(r.callb("hc_pin_can", n, CAP["RELAY_OUT"]) == 0
              and r.callb("hc_pin_can", n, CAP["INJ_OUT"]) == 0
              for n in (20, 21, 23)),
          "20 is not named on the sheet; 21 is KL15; 23 is the main relay")
    check("cavity 23 is not offered as an injector output",
          r.callb("hc_pin_can", 23, CAP["INJ_OUT"]) == 0,
          "the workbook calls it EV8; it is the DME main relay drive")
    # AND THE LOCK DID NOT EAT THE CONNECTOR. Cavity 65 is what MAIN_RELAY
    # actually routes to, and it is the best-evidenced relay output the main
    # CPU owns: EKPR, P2.12/CC12IO through a CJ920, both ME7.1.1 columns.
    check("cavity 65 is STILL relay capable",
          r.callb("hc_pin_can", 65, CAP["RELAY_OUT"]) == 1
          and r.callb("hc_pin_can", 65, CAP["LOW_SIDE"]) == 1,
          "EKPR - the MAIN_RELAY and FUEL_PUMP default")
    check("pin 0 and pin 122 do not exist",
          r.callb("hc_pin_can", 0, CAP["AIN"]) == 0
          and r.callb("hc_pin_can", 122, CAP["AIN"]) == 0)

    # ================================================================== 8
    print("\n--- two functions may not own one pin ---")
    r = boot()
    make_valid(r)
    r.write(O["CFG_U_PIN_IGN"], 96)      # coil 1 onto injector 1's pin
    rc = r("hc_cfg_mgr_apply_now", 0)
    check("the same pin for an injector and a coil is a CONFLICT",
          rc & VAL["HC_VAL_FAULT_PIN_CONFLICT"], f"faults=0x{rc:04X}")

    # ================================================================== 9
    print("\n--- trigger validation is PER DECODER ---")
    r = boot()
    make_valid(r)
    # 36-1 on the generic missing-tooth decoder: legal.
    r.write(O["CFG_SY_TEETH"], 0)
    r.write(O["CFG_SY_TEETH"] + 1, 36)
    r.write(O["CFG_SY_GAP"], 1)
    rc = r("hc_validate", VAL["HC_VAL_SRC_DESIRED"])
    check("36-1 is accepted by the generic missing-tooth decoder",
          not (rc & VAL["HC_VAL_FAULT_TRIGGER"]), f"faults=0x{rc:04X}")
    # the same 36-1 on the OEM OEM ME7.1.1 decoder: refused, because the recovered
    # machine code implements 60-2 with a fixed ratio of 2.0 and nothing else.
    r.write(O["CFG_U_TRIG_DECODER"], E["TRIGDEC_BOSCH_ME711"])
    rc = r("hc_validate", VAL["HC_VAL_SRC_DESIRED"])
    check("and REFUSED by the OEM OEM ME7.1.1 decoder, which implements 60-2 only",
          rc & VAL["HC_VAL_FAULT_TRIGGER"], f"faults=0x{rc:04X}")
    # 60-2 with the recovered ratio: accepted.
    r.write(O["CFG_SY_TEETH"] + 1, 60)
    r.write(O["CFG_SY_GAP"], 2)
    r.write(O["CFG_TRIG_GAP_RATIO_X10"], 0)
    r.write(O["CFG_TRIG_GAP_RATIO_X10"] + 1, 20)
    rc = r("hc_validate", VAL["HC_VAL_SRC_DESIRED"])
    check("60-2 with the recovered ratio 2.0 is accepted",
          not (rc & VAL["HC_VAL_FAULT_TRIGGER"]), f"faults=0x{rc:04X}")
    # a decoder with no gap must not be judged by a gap rule
    r.write(O["CFG_U_TRIG_DECODER"], E["TRIGDEC_EVEN_TOOTH"])
    r.write(O["CFG_SY_GAP"], 0)
    r.write(O["CFG_TRIG_GAP_RATIO_X10"] + 1, 0)
    rc = r("hc_validate", VAL["HC_VAL_SRC_DESIRED"])
    check("an evenly-spaced wheel with NO gap is not judged by a gap rule",
          not (rc & VAL["HC_VAL_FAULT_TRIGGER"]),
          "gap 0, ratio 0, still valid")
    r.write(O["CFG_U_TRIG_DECODER"], E["TRIGDEC_CUSTOM"])
    r.write(O["CFG_SY_TEETH"] + 1, 3)
    rc = r("hc_validate", VAL["HC_VAL_SRC_DESIRED"])
    check("and a CUSTOM decoder asserts nothing about a wheel nobody described",
          not (rc & VAL["HC_VAL_FAULT_TRIGGER"]), "3 teeth, accepted")

    # ================================================================= 10
    print("\n--- sync validation follows the STRATEGY, not the coil count ---")
    r = boot()
    make_valid(r)
    r.write(O["CFG_U_SYNC_MODE"], E["SYNC_CRANK_ONLY"])

    r.write(O["CFG_U_IGN_STRATEGY"], E["IGN_WASTED_COP"])
    rc = r("hc_validate", VAL["HC_VAL_SRC_DESIRED"])
    check("WASTED COP runs on crank position alone - accepted",
          not (rc & VAL["HC_VAL_FAULT_SYNC"]),
          "individual coils, no cam needed")

    r.write(O["CFG_U_IGN_STRATEGY"], E["IGN_SEQUENTIAL_COP"])
    rc = r("hc_validate", VAL["HC_VAL_SRC_DESIRED"])
    check("SEQUENTIAL COP without cycle position - refused",
          rc & VAL["HC_VAL_FAULT_SYNC"], f"faults=0x{rc:04X}")

    r.write(O["CFG_U_IGN_STRATEGY"], E["IGN_WASTED_PAIRED"])
    r.write(O["CFG_U_INJ_STRATEGY"], E["INJ_SEQUENTIAL"])
    rc = r("hc_validate", VAL["HC_VAL_SRC_DESIRED"])
    check("SEQUENTIAL injection without cycle position - refused",
          rc & VAL["HC_VAL_FAULT_SYNC"])

    r.write(O["CFG_U_INJ_STRATEGY"], E["INJ_SEMI_SEQ"])
    rc = r("hc_validate", VAL["HC_VAL_SRC_DESIRED"])
    check("SEMI-SEQUENTIAL injection on crank only - accepted",
          not (rc & VAL["HC_VAL_FAULT_SYNC"]))

    # A MODE IS NOT A CYCLE, AND FROM V63 THE VALIDATOR KNOWS IT.
    #
    # This case used to select SYNC_CAM1_CYCLE and nothing else, and it passed
    # - which is precisely the hole V63 closed. geometry_read() clears
    # g_sync_bank when CFG_U_CAM_REFS is 0, so that configuration could never
    # promote TRG_SYNC_CRANK to TRG_SYNC_FULL, and sequential injection was
    # being accepted against a cycle that would never arrive.
    #
    # So the case now describes a cam that can actually resolve one: enabled,
    # and an ODD reference count. Odd because an even, equally spaced set maps
    # onto itself under a 360-degree shift and proves nothing about which
    # revolution this is. The refusals for the two bad shapes are asserted
    # immediately below, which is what makes this an acceptance rather than a
    # test that accepts everything.
    r.write(O["CFG_U_INJ_STRATEGY"], E["INJ_SEQUENTIAL"])
    r.write(O["CFG_U_SYNC_MODE"], E["SYNC_CAM1_CYCLE"])
    r.write(CAM_ENABLE_OFF, 1)
    r.write(O["CFG_U_CAM_REFS"], 1)
    rc = r("hc_validate", VAL["HC_VAL_SRC_DESIRED"])
    check("SEQUENTIAL injection WITH a cam that can RESOLVE the cycle - accepted",
          not (rc & VAL["HC_VAL_FAULT_SYNC"]), f"faults=0x{rc:04X}")

    # THE TWO NEGATIVE CONTROLS FOR THAT ACCEPTANCE.
    r.write(O["CFG_U_CAM_REFS"], 0)
    rc = r("hc_validate", VAL["HC_VAL_SRC_DESIRED"])
    check("...a cam cycle mode with NO references is refused",
          rc & VAL["HC_VAL_FAULT_SYNC"], f"faults=0x{rc:04X}")

    r.write(O["CFG_U_CAM_REFS"], 2)
    rc = r("hc_validate", VAL["HC_VAL_SRC_DESIRED"])
    check("...and an EVEN count is refused - it maps onto itself at 360 deg",
          rc & VAL["HC_VAL_FAULT_SYNC"], f"faults=0x{rc:04X}")

    r.write(O["CFG_U_CAM_REFS"], 1)

    r.write(O["CFG_U_PIN_CAM1"], PIN_NONE)
    rc = r("hc_validate", VAL["HC_VAL_SRC_DESIRED"])
    check("a cam cycle mode with no camshaft pin - refused",
          rc & VAL["HC_VAL_FAULT_SYNC"])

    # ================================================================= 11
    print("\n--- a table axis a lookup will binary-search must increase ---")
    r = boot()
    make_valid(r)
    rc = r("hc_validate", VAL["HC_VAL_SRC_DESIRED"])
    check("the shipped fuel RPM axis is monotonic",
          not (rc & VAL["HC_VAL_FAULT_AXIS"]), f"faults=0x{rc:04X}")
    # element 5 below element 4
    r.write(O["CAL_FUEL_RPM_AX"] + 10, 0)
    r.write(O["CAL_FUEL_RPM_AX"] + 11, 1)
    rc = r("hc_validate", VAL["HC_VAL_SRC_DESIRED"])
    check("a descending step is caught", rc & VAL["HC_VAL_FAULT_AXIS"],
          f"faults=0x{rc:04X}")

    # ================================================================= 12
    print("\n--- DBW: the correlation model is configured, not assumed ---")
    r = boot()
    make_valid(r)
    # UNROUTE THEM EXPLICITLY. This check used to rely on a fresh page having
    # no throttle or pedal pins, which was true while the seed left every pin
    # HC_PIN_NONE. V61's board default routes all four, so the state this
    # check is ABOUT had stopped existing and the check silently became "DBW
    # with the pins routed - refused", which is the opposite question. A test
    # that needs a precondition should build it rather than inherit it.
    for off in ("CFG_U_PIN_TPS1", "CFG_U_PIN_TPS2",
                "CFG_U_PIN_APP1", "CFG_U_PIN_APP2"):
        r.write(O[off], PIN_NONE)
    r.write(O["CAL_DBW_ENABLE"], 1)
    rc = r("hc_validate", VAL["HC_VAL_SRC_DESIRED"])
    check("DBW with no throttle or pedal pins routed - refused",
          rc & VAL["HC_VAL_FAULT_DBW"], f"faults=0x{rc:04X}")
    for off, pin in ((O["CFG_U_PIN_TPS1"], 92), (O["CFG_U_PIN_TPS2"], 84),
                     (O["CFG_U_PIN_APP1"], 35), (O["CFG_U_PIN_APP2"], 34)):
        r.write(off, pin)
    for off, val in ((O["CAL_TPS1_MIN"], 100), (O["CAL_TPS1_MAX"], 900),
                     (O["CAL_PEDAL1_MIN"], 120), (O["CAL_PEDAL1_MAX"], 880)):
        r.write(off, (val >> 8) & 0xFF)
        r.write(off + 1, val & 0xFF)
    rc = r("hc_validate", VAL["HC_VAL_SRC_DESIRED"])
    check("with both tracks routed and calibrated - accepted",
          not (rc & VAL["HC_VAL_FAULT_DBW"]), f"faults=0x{rc:04X}")

    r.write(O["CFG_U_TPS_CORR"], E["TRACK_SCALED"])
    rc = r("hc_validate", VAL["HC_VAL_SRC_DESIRED"])
    check("SAME-DIRECTION/SCALED tracks are a legal model, not a fault",
          not (rc & VAL["HC_VAL_FAULT_DBW"]),
          "opposite is a default, not a law")

    r.write(O["CFG_U_TPS_TOL_X10"], 0)
    r.write(O["CFG_U_TPS_TOL_X10"] + 1, 0)
    rc = r("hc_validate", VAL["HC_VAL_SRC_DESIRED"])
    check("a zero track tolerance is refused - it could never be satisfied",
          rc & VAL["HC_VAL_FAULT_DBW"])

    # ================================================================= 13
    print("\n--- lambda 1 and lambda 2 are both first class ---")
    r = boot()
    make_valid(r)
    r.write(O["CFG_U_LAM1_SRC"], E["LAMBDA_OFF"])
    r.write(O["CFG_U_LAM2_SRC"], E["LAMBDA_EXTERNAL_ANALOG"])
    r.write(O["CFG_U_PIN_LAMBDA2"] if "CFG_U_PIN_LAMBDA2" in O
            else d(_gen, "CFG_U_PIN_LAMBDA2"), 108)
    r.write(O["CFG_U_LAM2_CYLMASK"], 0)
    r.write(O["CFG_U_LAM2_CYLMASK"] + 1, 0x0F)
    rc = r("hc_validate", VAL["HC_VAL_SRC_DESIRED"])
    check("lambda 2 alone, with lambda 1 off, is a valid arrangement",
          not (rc & VAL["HC_VAL_FAULT_LAMBDA"]), f"faults=0x{rc:04X}")

    r.write(O["CFG_U_LAM1_SRC"], E["LAMBDA_EXTERNAL_ANALOG"])
    r.write(d(_gen, "CFG_U_PIN_LAMBDA1"), 109)
    r.write(O["CFG_U_LAM1_CYLMASK"], 0)
    r.write(O["CFG_U_LAM1_CYLMASK"] + 1, 0x0C)   # overlaps lambda 2
    rc = r("hc_validate", VAL["HC_VAL_SRC_DESIRED"])
    check("two controllers trimming the same cylinder - refused",
          rc & VAL["HC_VAL_FAULT_LAMBDA"], f"faults=0x{rc:04X}")

    r.write(O["CFG_U_LAM1_CYLMASK"] + 1, 0x03)
    r.write(O["CFG_U_LAM2_CYLMASK"] + 1, 0x0C)
    rc = r("hc_validate", VAL["HC_VAL_SRC_DESIRED"])
    check("disjoint cylinder masks - accepted",
          not (rc & VAL["HC_VAL_FAULT_LAMBDA"]))

    r.write(O["CFG_U_LAM1_CYLMASK"] + 1, 0xF3)  # cylinders 5..8 on a 4-cyl
    rc = r("hc_validate", VAL["HC_VAL_SRC_DESIRED"])
    check("a mask naming cylinders the engine does not have - refused",
          rc & VAL["HC_VAL_FAULT_LAMBDA"])

    r.write(O["CFG_U_LAM1_CYLMASK"] + 1, 0x03)
    r.write(O["CFG_U_STOICH_X100"], 0)
    r.write(O["CFG_U_STOICH_X100"] + 1, 0)
    rc = r("hc_validate", VAL["HC_VAL_SRC_DESIRED"])
    check("a zero stoichiometric ratio - refused (every AFR display divides "
          "by it)", rc & VAL["HC_VAL_FAULT_LAMBDA"])

    # ================================================================= 14
    print("\n--- the schema gate ---")
    r = boot()
    make_valid(r)
    r.write(O["CFG_U_MAGIC"], 0)
    r.write(O["CFG_U_MAGIC"] + 1, 0)
    rc = r("hc_validate", VAL["HC_VAL_SRC_DESIRED"])
    check("a page with no universal block is refused on the SCHEMA, and the "
          "pass stops", rc & VAL["HC_VAL_FAULT_SCHEMA"], f"faults=0x{rc:04X}")

    # ================================================================= 15
    print("\n--- reserved bytes and boundaries ---")
    r = boot()
    res = O["CAL_RESERVED"] + 1          # V98r2: the tail is 2 bytes
    was = r.active(res)
    r.write(res, (was + 1) & 0xFF)
    check("a reserved byte is stored in DESIRED but NOT copied to ACTIVE",
          r.desired(res) == (was + 1) & 0xFF and r.active(res) == was,
          "a reserved byte has no policy, so it gets none")
    check("and it marks nothing dirty", r.g16("hc_cfg_dirty_groups") == 0)

    check("hc_cfg_slot_at() finds the first byte of the page",
          r("hc_cfg_slot_at", 0) != 0)
    check("hc_cfg_slot_at() finds the last byte of the last field",
          r("hc_cfg_slot_at", d(_cfg, "CAL_PWM_PAD")) != 0)
    check("hc_cfg_slot_at() returns null for a reserved byte",
          r("hc_cfg_slot_at", O["CAL_RESERVED"] + 1) == 0)
    check("hc_cfg_slot_at() returns null past the end of the page",
          r("hc_cfg_slot_at", PAGE) == 0)

    r.write(PAGE, 0xAA)          # must be ignored, not wrap
    r.write(PAGE + 100, 0xAA)
    check("a write past the end of the page is ignored",
          r.desired(0) == r.active(0), "no wrap into offset 0")

    # ================================================================= 16
    print("\n--- a page burn does not validate per byte ---")
    #
    # The previous implementation called the whole-configuration validator on
    # EVERY byte written. Measured here rather than argued: a 256-byte block of
    # LIVE writes must cost roughly 256 x (one write), not 256 x (one write +
    # one full validation). The ratio is what matters, not the absolute number.
    r = boot()
    # The FIRST host access forces the deferred DESIRED copy to finish, so it
    # carries a one-time cost that has nothing to do with per-byte validation.
    # Measure the steady state, which is the property that matters: a 4096-byte
    # page burn must not run 4096 whole-configuration validations.
    first = _steps(r, "hc_cfg_mgr_write_u8", O["CAL_FUEL_MAP"], 1)
    one = _steps(r, "hc_cfg_mgr_write_u8", O["CAL_FUEL_MAP"] + 1, 2)
    val = _steps(r, "hc_validate", VAL["HC_VAL_SRC_DESIRED"])
    check("one LIVE byte write is far cheaper than one validation",
          one * 8 < val,
          f"write {one} steps, validate {val} steps "
          f"(first write {first}, which completes the deferred copy)")

    rz = _steps(r, "hc_cfg_mgr_write_u8", O["CFG_U_PIN_INJ"], 96)
    check("and an RPM-zero byte write is cheap too - it only sets a bit",
          rz * 8 < val, f"staged write {rz} steps")

    # A whole 256-byte block of LIVE writes, the shape of a real page burn.
    burn = 0
    for i in range(256):
        burn += _steps(r, "hc_cfg_mgr_write_u8", O["CAL_FUEL_MAP"] + i,
                       (i * 7) & 0xFF)
    check("a 256-byte page burn costs far less than 256 validations",
          burn < val * 8,
          f"{burn} steps vs {val * 256} if it validated every byte")

    # ================================================================= 17
    print("\n--- the apply is bounded ---")
    r = boot()
    make_valid(r)
    n = _steps(r, "hc_cfg_mgr_apply_now", 0)
    # HARDWARE milliseconds, derived, not a constant somebody measured once.
    #
    # This used to read `ms_steps = 7557  # measured by me711_ts_gap_proof.py`.
    # That number matched nothing: c167sim executes about 2521 instructions per
    # SIMULATED millisecond, and the real part about 19 900 per REAL one. A
    # hardcoded ratio between the two is exactly what PROJECT_STATE warns
    # about, and it made every millisecond figure in this section meaningless.
    #
    # An instruction count means the same thing in both worlds. Convert it with
    # fCPU from hctarget.h at four clocks per instruction - twice the C166
    # floor, so the answer errs towards pessimism.
    ms_steps = _hw_instr_per_ms()
    check("a whole RPM-zero transaction fits well inside the 10 ms raster",
          n < ms_steps * 5,
          f"{n} instr = {n / ms_steps:.1f} ms on the part")

    # AN APPLY DOES NOT HAPPEN IN ISOLATION. hc_cfg_mgr_apply_now() runs from
    # hc_cfg_mgr_service(), in the main loop, so its cost STACKS on whatever
    # the loop was already doing between two supervision services.
    # me711_ts_gap_proof measures that baseline at 10 790 instructions on this
    # image; the two together are the real worst case a tuner can provoke, and
    # it is the number that has to stay inside the raster.
    BASELINE_GAP_INSTR = 10790
    combined = n + BASELINE_GAP_INSTR
    check("and stacked on the measured baseline gap it is still inside it",
          combined < ms_steps * 10,
          f"{n} + {BASELINE_GAP_INSTR} = {combined} instr "
          f"= {combined / ms_steps:.1f} ms of a 10 ms raster")

    # THE DEFERRED COPY IS NOT DRIVEN BY service() ANY MORE, so these checks
    # name hc_cfg_mgr_seed_step(). They used to call service() and, once the
    # seeding moved out of it, went quietly vacuous - they reported "the
    # seeding completes in 1 pass" because service() was no longer seeding at
    # all. A check that stops exercising the thing it names is worse than no
    # check, so the function under test is spelled out here.
    #
    # The bound is the point: no single main-loop iteration may carry the whole
    # 4096-byte copy, because that copy in the boot path is what put the first
    # ASIC exchange 27 ms late.
    r = boot()
    chunk = _steps(r, "hc_cfg_mgr_seed_step", 0)
    check("while seeding, one seed_step() pass carries only a bounded chunk",
          chunk < ms_steps * 2, f"{chunk} steps = {chunk / ms_steps:.1f} ms")

    passes = 1
    while passes < 200 and _steps(r, "hc_cfg_mgr_seed_step", 0) > 500:
        passes += 1
    check("and the seeding completes in a bounded number of passes",
          1 < passes < 64, f"{passes} passes of ~{chunk} steps")
    check("and it really did take more than one pass - the copy IS spread",
          passes > 1,
          f"{passes} passes; one pass would mean the deferral is not working")

    idle = _steps(r, "hc_cfg_mgr_seed_step", 0)
    check("once seeded, seed_step() costs almost nothing",
          idle < 200, f"{idle} steps")

    # And service() itself must be cheap whether or not seeding is going on -
    # it is called every main-loop pass regardless.
    svc = _steps(r, "hc_cfg_mgr_service", 0)
    check("service() is cheap once nothing is dirty",
          svc < 200, f"{svc} steps")

    print(f"\n{CHECKS - FAILS}/{CHECKS} checks pass")
    if FAILS:
        print("CONFIGURATION STATE MACHINE FAILED")
        return 1
    print("CONFIGURATION STATE MACHINE PASSES - desired and active are "
          "genuinely separate,\nthe latest state is what applies, and "
          "restart-required stays out of the runtime.")
    return 0


def _steps(rig, fn, *args):
    """How many simulator steps one call takes. Same rig, so the measurement
    includes whatever state the previous calls left."""
    a = sym(fn)
    rig.m.w16(rig.c.cp(), rig.stack_top)
    rig.m.sfr[0xFE14], rig.m.sfr[0xFE16] = 0xF200, 0xFE00
    sp = 0xF700
    for w in (a >> 16, 0xFFFE):
        sp = (sp - 2) & 0xFFFF
        rig.m.w16(sp, w)
    rig.m.sfr[0xFE12] = sp
    for i, v in enumerate(args):
        rig.c.sr(8 + i, v & 0xFFFF)
    rig.c.csp, rig.c.ip = a >> 16, a & 0xFFFF
    n = 0
    while n < 2000000:
        if rig.c.ip == 0xFFFE:
            return n
        rig.c.step()
        n += 1
    raise SystemExit(f"{fn} did not return")


if __name__ == "__main__":
    raise SystemExit(main())
