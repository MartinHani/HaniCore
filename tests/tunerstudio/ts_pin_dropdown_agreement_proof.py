#!/usr/bin/env python3
"""Every cavity a TunerStudio pin dropdown offers is one the ECU will accept.

THE REQUIREMENT THIS IMPLEMENTS is "avoid duplicate independent pin databases
in firmware, validator and INI generation". There are three consumers of the
same hardware facts:

    hw_descriptors.py  ->  hc_pin_desc_bosch_me711.c   the firmware's table
                       ->  generate_config.py          the .ini's dropdowns
                       ->  hc_validation.c             what apply() refuses

They are generated from one source today, which is the right architecture and
is NOT self-enforcing: the dropdown applies its own capability rule in Python
and the firmware applies `can()` in C, and those two rules have to say the same
thing about every cavity. If they drift, a tuner is offered a cavity the ECU
then refuses - which is the V12K/5b defect wearing different clothes, and that
one survived for eleven releases because nothing compared the two halves.

So this compares them, cavity by cavity, for every pin field in the shipped
.ini, and it models `can()` from the C rather than from memory:

    not routable                 -> refused, whatever the capabilities say
    need == 0                    -> accepted if any bit BESIDE SPECIAL_LOCKED
    need != 0                    -> accepted if EVERY requested bit is present

**SPECIAL_LOCKED IS DELIBERATELY NOT A VETO** and this gate must not "fix"
that. Cavity 82, the one crank input this board has, is
`VR_IN|FREQ_IN|SPECIAL_LOCKED`; a veto would make the crank unselectable. The
firmware says so in its own header and the dropdown agrees with it. What the
gate pins is that they go on agreeing.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
sys.path.insert(0, str(ROOT / "tools" / "config_source"))

import hw_descriptors as HW                      # noqa: E402
import generate_config as GEN                    # noqa: E402
from hanicore_config_schema import PinCap        # noqa: E402

CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print("  [%s] %-56s %s" % ("PASS" if ok else "FAIL", name, detail))


def firmware_can(pin, need):
    """hc_pin_descriptor.c's can(), modelled from the C it is taken from."""
    routable = bool(pin.hal_resource) and pin.hal_resource != "NOT_ON_MAIN_CPU"
    if not routable:
        return False
    have = pin.capabilities
    if need == 0:
        return (have & ~PinCap.SPECIAL_LOCKED) != 0
    return (have & need) == need


def output_binding_rule():
    """V95/V96: hc_validation.c ALSO refuses an output cavity the HAL cannot
    drive (hc_hal_out_bindable(), the project rules) - modelled from the C, like
    can(): which fields the validator binds, which fields the HAL function
    drives at all, and the one cavity boost can take (TGT_LDR_CAV)."""
    val = (ROOT / "firmware/config/hc_validation.c").read_text(errors="replace")
    m = re.search(r"out_off\[\]\s*=\s*\{([^}]*)\}", val)
    bound = set(re.findall(r"CFG_U_PIN_\w+", m.group(1))) if m else set()
    hal = (ROOT / "firmware/targets/me711/hal/hchal_me711.c"
           ).read_text(errors="replace")
    m = re.search(r"unsigned char hc_hal_out_bindable\(unsigned int field,"
                  r"[^)]*\)\s*\{(.*?)\n\}", hal, re.S)
    body = m.group(1) if m else ""
    driven = set(re.findall(r"field == (CFG_U_PIN_\w+)", body))
    tgt = (ROOT / "firmware/targets/me711/hctarget.h"
           ).read_text(errors="replace")

    def cav_value(tok):
        if tok.isdigit():
            return int(tok)
        return int(re.search(r"#define\s+%s\s+(\d+)" % tok, tgt).group(1))

    # Per field, the fixed cavities its `if (field == ...)` block returns
    # true for (`cav == 104`, `cav == TGT_MIL_CAV`, ...). A field whose block
    # tests no fixed cavity is bound by capability and port alone.
    only = {}
    for cond, blk in re.findall(r"if \((.*?)\)\s*\{(.*?)\n    \}", body, re.S):
        cavs = {cav_value(t) for t in re.findall(r"cav == (\w+?)u?\b", blk)}
        if cavs:
            for f in re.findall(r"field == (CFG_U_PIN_\w+)", cond):
                only[f] = only.get(f, set()) | cavs
    return bound, driven, only


def ini_path():
    """The SHIPPED .ini, not the UserDefined fallback beside it.

    The fallback sorts last and is a different file for a different
    TunerStudio version; testing it instead of the real one is how a gate
    quietly stops describing what an operator loads."""
    c = sorted(f for f in (ROOT / "tunerstudio").glob("hanicore_me711_v*.ini")
               if "fallback" not in f.name and "forensic" not in f.name)
    if not c:
        raise SystemExit("no generated .ini in tools/tunerstudio")
    return c[-1]


def main() -> int:
    ini = ini_path()
    print("=== HaniCore - the pin dropdowns and the ECU agree ===\n")
    print("  ini   %s\n" % ini.name)
    text = ini.read_text(errors="replace")
    d = HW.build_me711()

    # Every pin field the model declares, with the capability it asks for.
    model_fields, _consts, _problems = GEN.MODEL.resolve()
    fields = [(f.meta.ts, f.meta.pin_needs or 0, f.slot)
              for f in model_fields if f.meta.is_pin]
    bound, driven, only = output_binding_rule()
    check("the output-binding rule was read from the C",
          {"CFG_U_PIN_BOOST", "CFG_U_PIN_TACHO"} <= bound
          and "CFG_U_PIN_BOOST" in driven and only.get("CFG_U_PIN_BOOST"),
          "bound %s, driven %s, fixed cavities %s"
          % (sorted(bound), sorted(driven),
             {k[10:]: sorted(v) for k, v in sorted(only.items())}))
    check("the model declares pin fields", len(fields) >= 20,
          "%d pin fields" % len(fields))

    offered_total = 0
    mismatches = []
    checked = 0
    for ts, need, slot in fields:
        m = re.search(r"^\s*%s\s*=\s*bits,\s*U08,\s*\d+,\s*\[0:7\],\s*(.+)$"
                      % re.escape(ts), text, re.M)
        if not m:
            continue                       # not a dropdown; covered elsewhere
        labels = re.findall(r'"([^"]*)"', m.group(1))
        if len(labels) != 256:
            mismatches.append("%s has %d labels, not 256" % (ts, len(labels)))
            continue
        offered = {i for i, s in enumerate(labels)
                   if s not in ("INVALID", "NONE")}
        offered_total += len(offered)
        checked += 1

        # The SAME rule the generator uses, which mirrors hc_validation.c.
        mode, n = "all", need
        if ts in GEN._PIN_RULE_ANY:
            mode, n = "any", GEN._PIN_RULE_ANY[ts]
        elif ts in GEN._PIN_RULE_ALL:
            mode, n = "all", GEN._PIN_RULE_ALL[ts]

        accepted = set()
        for cav in range(1, HW.PIN_COUNT + 1):
            p = d.pin(cav)
            if mode == "any":
                routable = (bool(p.hal_resource)
                            and p.hal_resource != "NOT_ON_MAIN_CPU")
                ok = routable and (p.capabilities & n) != 0
            else:
                ok = firmware_can(p, n)
            # AND hc_validation.c ADDS A RULE hc_pin_can() DOES NOT KNOW.
            #
            # V62 refuses a crank or cam cavity that has no CAPTURE CHANNEL on
            # this board, whatever its capability bits say. Cavity 29 is the
            # case that found this: SRD_S/HFM_S is AIN|FREQ_IN on P5.0/AN0, so
            # hc_pin_can(29, FREQ_IN) is TRUE and the dropdown still - rightly
            # - does not offer it, because Port 5 is the analog block and has
            # no CAPCOM unit behind it. Modelling only hc_pin_can() reported
            # the .ini as hiding a cavity the ECU accepts; the ECU does not.
            if ok and ts in GEN._CAPTURE_FIELDS:
                ok = cav in GEN._CAPTURE_CAVITIES
            # Capable is not enough - the HAL must drive it there
            # (hc_hal_out_bindable: boost only on 104, the lamp only on 47,
            # cam solenoids only on POUT0/POUT1; tacho has no output path).
            if ok and slot in bound:
                if slot not in driven:
                    ok = False
                elif slot in only:
                    ok = cav in only[slot]
            if ok:
                accepted.add(cav)

        if offered != accepted:
            only_ini = sorted(offered - accepted)
            only_ecu = sorted(accepted - offered)
            mismatches.append(
                "%s: offered-but-refused %s ; accepted-but-hidden %s"
                % (ts, only_ini or "-", only_ecu or "-"))

    check("every dropdown was compared against the firmware rule",
          checked >= 20, "%d dropdowns, %d cavities offered in total"
          % (checked, offered_total))
    check("NO cavity is offered that the ECU would refuse, and none hidden "
          "that it would accept", not mismatches,
          "; ".join(mismatches[:3]) if mismatches else "all agree")

    # ------------------------------------------------- the things that matter
    def offered_for(ts):
        m = re.search(r"^\s*%s\s*=\s*bits,\s*U08,\s*\d+,\s*\[0:7\],\s*(.+)$"
                      % re.escape(ts), text, re.M)
        labels = re.findall(r'"([^"]*)"', m.group(1))
        return {i for i, s in enumerate(labels) if s not in ("INVALID", "NONE")}

    check("the crank dropdown offers cavity 82", 82 in offered_for("pinCrank"),
          "SPECIAL_LOCKED is deliberately not a veto - a veto would make the "
          "one crank input on this board unselectable")
    check("the cam dropdowns offer only 86 and 87",
          offered_for("pinCam1") == {86, 87}, sorted(offered_for("pinCam1")))
    inj = offered_for("injPin1")
    check("the injector dropdown offers exactly the eight injector cavities",
          inj == {19, 24, 88, 89, 96, 97, 112, 113}, sorted(inj))
    ign = offered_for("ignPin1")
    check("the ignition dropdown offers exactly the eight coil cavities",
          ign == {7, 8, 94, 95, 102, 103, 110, 111}, sorted(ign))

    # NEGATIVE CONTROL: the comparison must be able to fail. Ask for a
    # capability no cavity on this board has and require an empty accept set.
    bogus = {c for c in range(1, HW.PIN_COUNT + 1)
             if firmware_can(d.pin(c), PinCap.DBW_HBRIDGE | PinCap.INJ_OUT)}
    check("NEGATIVE CONTROL - an impossible capability pair accepts nothing",
          not bogus, "no cavity is both an H-bridge leg and an injector stage")

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        return 1
    print("PIN DROPDOWN AGREEMENT PASSES - the .ini offers exactly what the "
          "firmware accepts, from one descriptor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
