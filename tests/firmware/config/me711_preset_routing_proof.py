#!/usr/bin/env python3
r"""
me711_preset_routing_proof.py - every preset value that names a physical
cavity must be a cavity that can actually do the job.

    py tests\firmware\config\me711_preset_routing_proof.py

WHAT THIS EXISTS FOR, IN ONE SENTENCE: a preset is applied to the DESIRED page
and then validated, so a preset carrying an impossible pin does not produce a
warning - it produces a configuration the ECU refuses WHOLE, and the operator
is left reading `cfgFirstBadOffset` to find out why a factory preset does not
work.

THE DEFECT THIS WAS WRITTEN FOR, AND IT WAS LIVE
================================================
`VAG_18T_ME711` carried `pinMainRelay = 21`. Cavity 21 on this Porsche board is
KL15 - a POWER INPUT - settled in `hw_descriptors._PORSCHE_TRUTH` from three
agreeing sources, and therefore SPECIAL_LOCKED with no capability bits at all.
`hc_pin_can(21, RELAY_OUT)` is 0, so `hc_validate()` answers `PIN_CAP` and
refuses the whole page, not just that field.

The value was correct against the VW/Audi ME7.1 C4 family workbook, where 21 is
`ZAS2_S` on a CJ420 smart low-side die. The Porsche override layer landed after
it and nothing re-checked the presets, because THE TWO TABLES HAD NO GATE
BETWEEN THEM. That is the actual bug: not a wrong integer, but two authorities
for one fact and no test that they agree.

WHY THIS IS A GENERATOR-SIDE GATE AND NOT A FIRMWARE ONE
========================================================
Both inputs are generator source. `hw_descriptors.py` builds the capability
table the firmware compiles in, and `hanicore_presets.py` builds the preset
table beside it. Checking them against each other needs no ECU, no image and no
bench - and it catches the drift BEFORE it is baked into a release.

THE NEGATIVE CONTROL IS THE DEFECT ITSELF
=========================================
A gate that only reports "all presets are fine" proves nothing: it would read
exactly the same if the capability lookup silently returned True. So the run
ALSO re-injects `pinMainRelay = 21` into the 1.8T preset and REQUIRES that the
check fail on it. If that control ever stops failing, this gate has stopped
testing what it says it tests, and the run is a FAIL either way.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools/config_source"))

import hanicore_config_def as MODEL          # noqa: E402
import hanicore_presets as PRESETS           # noqa: E402
import hw_descriptors as HW                  # noqa: E402
from hanicore_config_schema import PinCap    # noqa: E402

PIN_NONE = 255

CAP_NAME = {v: k for k, v in vars(PinCap).items()
            if isinstance(v, int) and not k.startswith("_")}


def cap_names(bits):
    out = [n for b, n in sorted(CAP_NAME.items()) if b and (bits & b) == b]
    return "|".join(out) if out else "NONE"


def descriptors():
    d = {}
    for build in (HW.build_me711, HW.build_me75):
        desc = build()
        d[desc.target_id] = desc
    return d


def pin_can(desc, pin, need, mode=None):
    """The generator-side twin of hc_pin_descriptor.c:hc_pin_can().

    It must answer exactly what the firmware will answer, so it repeats the
    firmware's two rules rather than inventing a friendlier one: the cavity has
    to be ROUTABLE on this board, and its circuit has to provide EVERY bit
    requested, not merely overlap them."""
    if pin == PIN_NONE:
        return True                      # unassigned is always legal
    if pin < 1 or pin > HW.PIN_COUNT:
        return False
    p = desc.pin(pin)
    caps = p.capabilities
    routable = bool(p.hal_resource) and p.hal_resource != "NOT_ON_MAIN_CPU"
    if not routable:
        return False
    if need == 0:
        return (caps & ~PinCap.SPECIAL_LOCKED) != 0
    if mode == ANY:
        return (caps & need) != 0
    return (caps & need) == need


# ==========================================================================
# WHAT THE FIRMWARE ACTUALLY ASKS, WHICH IS NOT ALWAYS WHAT `pin_needs` SAYS
# ==========================================================================
#
# `Meta.pin_needs` is a UI hint, and for MOST fields it is a single capability
# bit that hc_validation.c passes straight to hc_pin_can() - a conjunction.
# TWO fields carry more than one bit and the firmware does NOT treat either of
# them as a conjunction:
#
#   pinCrank  hc_validation.c:619-624 tests VR_IN, then HALL_IN, then FREQ_IN
#             and fails only if ALL THREE are absent. That is deliberate and
#             the code says why: "VR and Hall are different circuits, so the
#             crank pin is asked for either, not for both." Cavity 82 is
#             VR_IN|FREQ_IN and has no HALL_IN, so a conjunction would refuse
#             the one crank cavity this board actually has.
#
#   pinMaf    metadata says AIN|FREQ_IN; hc_validation.c:644 passes plain
#             HC_PINCAP_AIN for every entry of its analog table, MAF included.
#
# A GATE THAT MODELLED pin_needs AS A CONJUNCTION WOULD FAIL EVERY CORRECT
# PRESET IN THE TREE, which is exactly what the first version of this file did.
# So the rule below mirrors the firmware, and `_unmodelled()` fails the run if
# a NEW multi-bit field ever appears without an explicit decision here - the
# ambiguity cannot come back silently.
ANY = "any"     # at least one of these bits
ALL = "all"     # every one of these bits

FIRMWARE_RULE = {
    "pinCrank": (ANY, PinCap.VR_IN | PinCap.HALL_IN | PinCap.FREQ_IN),
    "pinMaf":   (ALL, PinCap.AIN),
    # V78: hc_validation.c accepts MAIN_RELAY on a CPU-driven RELAY_OUT OR on
    # the supply IC's own stage (MAIN_RELAY_HW, ME7.1.1 cavity 23) - and only
    # in AUTO there, which hc_validate checks and me711_preset_validates_proof
    # executes.
    "pinMainRelay": (ANY, PinCap.RELAY_OUT | PinCap.MAIN_RELAY_HW),
}


def effective_rule(ts_name, pin_needs):
    if ts_name in FIRMWARE_RULE:
        return FIRMWARE_RULE[ts_name]
    return (ALL, pin_needs)


def _unmodelled(pins):
    """Multi-bit pin_needs fields with no explicit firmware rule recorded."""
    out = []
    for name, f in pins.items():
        n = f.meta.pin_needs
        if n and (n & (n - 1)) and name not in FIRMWARE_RULE:
            out.append("%s (pin_needs %s)" % (name, cap_names(n)))
    return out


FAILS = 0
CHECKS = 0


def ck(ok, name, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    if not ok:
        FAILS += 1
    print("  [%s] %-60s %s" % ("PASS" if ok else "FAIL", name, detail))


def pin_fields():
    fields, _consts, problems = MODEL.resolve()
    if problems:
        raise SystemExit("the configuration model does not resolve:\n  "
                         + "\n  ".join(problems))
    return {f.meta.ts: f for f in fields
            if f.meta is not None and getattr(f.meta, "is_pin", False)}


def audit(presets, descs, pins):
    """Every pin-valued preset entry, against the descriptor of ITS OWN board."""
    bad = []
    for pr in presets:
        if not pr.target:
            continue
        desc = descs.get(pr.target)
        if desc is None:
            bad.append("%s names target %s, which has no descriptor"
                       % (pr.key, pr.target))
            continue
        for key, val in pr.values.items():
            f = pins.get(key)
            if f is None:
                continue              # not a pin field; other gates cover it
            mode, need = effective_rule(key, f.meta.pin_needs)
            vals = val.value if isinstance(val.value, list) else [val.value]
            for n, v in enumerate(vals):
                v = int(v)
                if pin_can(desc, v, need, mode):
                    continue
                p = desc.pin(v) if 1 <= v <= HW.PIN_COUNT else None
                where = "%s[%d]" % (key, n) if len(vals) > 1 else key
                bad.append(
                    "%s: %s = cavity %d needs %s %s, but that cavity is %s "
                    "(caps %s, hal %r)"
                    % (pr.key, where, v, mode.upper(), cap_names(need),
                       (p.meaning or p.oem_name) if p else "not a cavity",
                       cap_names(p.capabilities) if p else "-",
                       p.hal_resource if p else "-"))
    return bad


def main():
    descs = descriptors()
    pins = pin_fields()

    print("=== presets vs the hardware descriptor they name ===\n")
    print("  descriptors: %s" % ", ".join(sorted(descs)))
    print("  pin-valued configuration fields: %d\n" % len(pins))

    n_vals = 0
    for pr in PRESETS.ENGINE_PRESETS:
        for k, v in pr.values.items():
            if k in pins:
                n_vals += len(v.value) if isinstance(v.value, list) else 1

    un = _unmodelled(pins)
    ck(not un, "every multi-bit pin_needs field has an explicit firmware rule",
       "; ".join(un) if un
       else "%d modelled: %s" % (len(FIRMWARE_RULE), ", ".join(FIRMWARE_RULE)))

    bad = audit(PRESETS.ENGINE_PRESETS, descs, pins)
    ck(not bad, "every preset routes only to cavities that can do the job",
       "%d preset pin values checked" % n_vals)
    for b in bad:
        print("         %s" % b)

    # ---- the board default has to be RUNNABLE, not merely legal -----------
    #
    # hc_validate() refuses any syncMode above NONE whose crank pin is
    # unassigned. A board default that seeds a page which cannot run is the
    # exact thing this default exists to prevent, so it is checked here rather
    # than left to the first person who flashes it.
    defaults = [p for p in PRESETS.ENGINE_PRESETS
                if getattr(p, "board_default", False)]
    by_target = {}
    for p in defaults:
        by_target.setdefault(p.target, []).append(p)
    ck(all(len(v) == 1 for v in by_target.values()),
       "at most one board default per target",
       ", ".join("%s=%s" % (t, [p.key for p in v])
                 for t, v in by_target.items()) or "none declared")
    ck(bool(defaults), "a board default exists",
       ", ".join("%s -> %s" % (p.target, p.key) for p in defaults))

    for p in defaults:
        vals = {k: v.value for k, v in p.values.items()}
        sync = int(vals.get("syncMode", 0))
        crank = int(vals.get("pinCrank", PIN_NONE))
        ck(sync == 0 or crank != PIN_NONE,
           "board default %s is runnable as seeded" % p.key,
           "syncMode %d, pinCrank %s"
           % (sync, "UNASSIGNED" if crank == PIN_NONE else crank))
        ck(crank == PIN_NONE
           or pin_can(descs[p.target], crank, *reversed(
               effective_rule("pinCrank", 0))),
           "board default %s crank cavity can capture position" % p.key,
           "cavity %d" % crank)

    # ---- THE NEGATIVE CONTROL --------------------------------------------
    print("\n  --- negative control: re-inject the defect, require a FAIL ---")
    ctrl = copy.deepcopy(PRESETS.ENGINE_PRESETS)
    tgt = None
    for pr in ctrl:
        if pr.key == "VAG_18T_ME711":
            tgt = pr
            break
    if tgt is None:
        ck(False, "the control preset VAG_18T_ME711 still exists", "renamed?")
    else:
        tgt.values["pinMainRelay"] = PRESETS.Value(
            21, PRESETS.EvidenceClass.PROBABLE, "negative control")
        hit = [b for b in audit(ctrl, descs, pins) if "pinMainRelay" in b]
        ck(bool(hit),
           "the removed pinMainRelay = 21 is REJECTED when re-injected",
           hit[0] if hit else "NOT REJECTED - this gate proves nothing")

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("\nPRESET ROUTING PROOF FAILS.")
        print("A preset names a cavity whose circuit cannot do the job. Fix the")
        print("PRESET, or - if the DESCRIPTOR is what is wrong - fix the")
        print("descriptor and say which source settles it. Do not widen a")
        print("capability to make a preset fit.")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
