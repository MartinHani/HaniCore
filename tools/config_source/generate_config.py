#!/usr/bin/env python3
r"""
generate_config.py - emit the C and TunerStudio views of the configuration
model, and FAIL if any of them can disagree.

    py tools\config_source\generate_config.py            generate + check
    py tools\config_source\generate_config.py --check    check only, write nothing

Generates:

  firmware/generated/hc_config_generated.h    offsets, enums, the apply
                                                    policy API
  firmware/generated/hc_config_generated.c    the per-slot policy table
  firmware/generated/hc_pin_desc_bosch_me711.c
  firmware/generated/hc_pin_desc_me75_4b0906018dc.c
                                                    ONE descriptor per board
  build/generated/hc_config_model.csv                the merged model, for review

and exports `universal_ini_lines()`, which both .ini generators call so the
TunerStudio view of the universal block is emitted from the same model rather
than retyped.

WHAT "VALIDATED" MEANS HERE, since the previous version of this file printed
"Generation complete and validated" and performed no checks at all:

  1. every hcconfig.h layout slot has metadata, and every metadata entry names
     a real hcconfig.h slot                          (hanicore_config_def.resolve)
  2. no two fields overlap, nothing is misaligned, nothing runs past the page
  3. no two fields share a TunerStudio name
  4. the universal block fits inside CFG_UNIVERSAL_BASE's reservation
  5. the generated C offsets equal the hcconfig.h offsets, byte for byte
  6. every emitted TunerStudio line's offset equals the model's offset
  7. the page is FULLY COVERED: every one of the 4096 bytes is either a field
     or a declared reserved array

Any failure exits non-zero and writes nothing.
"""
from __future__ import annotations

import binascii
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import hanicore_config_def as MODEL  # noqa: E402
import hcconfig_layout  # noqa: E402
import hanicore_presets as PRESETS  # noqa: E402
import hw_descriptors as HW  # noqa: E402
from hanicore_config_schema import ApplyPolicy, EvidenceClass, PinCap  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FW = ROOT / "firmware"
GEN = FW / "generated"
GEN_DOCS = ROOT / "build/generated"

OUT_H = GEN / "hc_config_generated.h"
OUT_C = GEN / "hc_config_generated.c"
OUT_CSV = GEN_DOCS / "hc_config_model.csv"

TS_TYPE = {"u8": "U08", "u16": "U16", "s16": "S16"}
C_TYPE = {"u8": "unsigned char", "u16": "unsigned int", "s16": "int"}

POLICY_C = {
    ApplyPolicy.LIVE_APPLY: "HC_APPLY_LIVE",
    ApplyPolicy.RPM_ZERO_APPLY: "HC_APPLY_RPM_ZERO",
    ApplyPolicy.RESTART_REQUIRED: "HC_APPLY_RESTART",
}
POLICY_N = {ApplyPolicy.LIVE_APPLY: 0, ApplyPolicy.RPM_ZERO_APPLY: 1,
            ApplyPolicy.RESTART_REQUIRED: 2}


def macro(slot: str) -> str:
    """hcconfig.h already names its slots CFG_*/CAL_*; the generated header
    must NOT redefine those or the compiler sees two definitions. Universal
    fields keep their own CFG_U_* names, which hcconfig.h does not define."""
    return slot


def is_universal(slot: str) -> bool:
    return slot.startswith("CFG_U_")


# ==========================================================================
# checks
# ==========================================================================
def coverage(fields, page: int, uni_base: int, uni_size: int) -> list[str]:
    """Every byte of the page must be owned by a field or by one of the two
    declared reserved arrays. An unowned byte is a byte the .ini cannot
    account for and the config manager cannot classify."""
    owner = [None] * page
    for f in fields:
        for b in range(f.offset, min(f.end, page)):
            owner[b] = f.slot
    slots, consts = hcconfig_layout.parse()
    named = {s.name: s for s in slots}
    reserved = []
    core = consts["HC_CFG_CORE"]
    cfg_res = int(_define(consts, "CFG_RESERVED", 76))
    reserved.append(("cfgReserved", cfg_res, core - cfg_res))
    uni_used = MODEL.universal_size(uni_base)
    if uni_size > uni_used:
        reserved.append(("uniReserved", uni_base + uni_used, uni_size - uni_used))
    cal_res = named["CAL_RESERVED"].offset if "CAL_RESERVED" in named else None
    if cal_res is None:
        cal_res = _raw_define("CAL_RESERVED")
    reserved.append(("calReserved", cal_res, page - cal_res))
    for name, off, n in reserved:
        for b in range(off, off + n):
            if owner[b] is not None:
                return ["reserved array %s at %d overlaps %s at byte %d"
                        % (name, off, owner[b], b)]
            owner[b] = name
    gaps = [i for i, o in enumerate(owner) if o is None]
    if gaps:
        return ["page not fully covered: %d unowned bytes, first at %d"
                % (len(gaps), gaps[0])]
    return []


def _raw_define(name: str) -> int:
    import re
    text = (FW / "config/hcconfig.h").read_text(errors="replace")
    m = re.search(r"#define\s+%s\s+(\d+)" % name, text)
    if not m:
        raise SystemExit("hcconfig.h: %s not found" % name)
    return int(m.group(1))


def _define(consts, name, default):
    return consts.get(name, _raw_define(name))


def reserved_arrays(page: int, uni_base: int, uni_size: int):
    core = _raw_define("HC_CFG_CORE")
    cfg_res = _raw_define("CFG_RESERVED")
    cal_res = _raw_define("CAL_RESERVED")
    out = [("cfgReserved", cfg_res, core - cfg_res)]
    used = MODEL.universal_size(uni_base)
    if uni_size > used:
        out.append(("uniReserved", uni_base + used, uni_size - used))
    out.append(("calReserved", cal_res, page - cal_res))
    return out


# ==========================================================================
# C header
# ==========================================================================
# THE STORAGE ORDER OF EVERY 2-D TABLE ON THE PAGE (hc_cal_map, hcvvt711.c):
# a row is one LOAD, a column one RPM - TunerStudio's order for an `[NxM]`
# array with xBins = rpm and yBins = load (index = y * N + x), and rusEFI's
# (veTable[VE_LOAD_COUNT][VE_RPM_COUNT]). Part of the layout identity.
TABLE_ORDER = "load-major"

# THE VE TABLE'S UNIT (V98): one count = 1 % (0..255 %). Until V98 one count
# was 0.5 % (0..127.5 %) - the same bytes, half the meaning, so a record of
# the old unit must be REFUSED and migrated by value, never reread. Part of
# the layout identity, like TABLE_ORDER.
VE_UNIT = "u16-0.1pct"


def layout_id(fields, consts) -> int:
    """A machine-derived identity for the ON-DISK calibration layout.

    THE PROBLEM IT SOLVES. A calibration record in flash is a flat block of
    bytes with no self-description. If a later firmware moves one field by one
    byte and the record is loaded anyway, every table past that point is
    misread - and nothing complains, because the length and the CRC are both
    still right. A version number does not help either: it is maintained by
    hand, and this project has four recorded incidents of hand-maintained
    metadata drifting from the artefact it described.

    So the identity is DERIVED. It is a CRC32 over every field's slot name,
    offset, C type and element count, plus the page size and the near-RAM
    core size. Move a field, resize one, rename one, or change the page size,
    and the id changes - which makes an old flash record refuse to load
    instead of being silently reinterpreted.

    It deliberately does NOT include units, scaling, min/max, notes or
    TunerStudio names. Those change the presentation, not the byte layout, and
    a stored calibration written before such a change is still correct.

    V97: IT ALSO CARRIES TABLE_ORDER. The 2-D tables changed from [rpm][load]
    to [load][rpm] without moving a byte of any field, and a record written
    in the old order is exactly the "silently reinterpreted" case above -
    every VE and ignition cell transposed. The order is part of the layout.
    """
    parts = ["size=%d" % consts["HC_CFG_SIZE"], "core=%d" % consts["HC_CFG_CORE"],
             "tables=%s" % TABLE_ORDER, "ve=%s" % VE_UNIT]
    for f in sorted(fields, key=lambda x: (x.offset, x.slot)):
        parts.append("%s:%d:%s:%d" % (f.slot, f.offset, f.ctype, f.count))
    return binascii.crc32("|".join(parts).encode("ascii")) & 0xFFFFFFFF


def universal_schema(fields, uni_base, uni_size) -> int:
    """A DERIVED version for the battery-backed universal block.

    THIS WAS THE LITERAL `1u`, AND IT IS THE SAME DEFECT AS EVERY OTHER
    HAND-MAINTAINED PIECE OF METADATA IN THIS PROJECT'S HISTORY.

    hc_config_manager.c keeps the universal block across a reset by checking
    CFG_U_MAGIC and CFG_U_SCHEMA and, if both match, USING THE BLOCK AS IT
    STANDS. Add a field and the schema does not move, so a page written by the
    previous firmware is accepted whole - and the bytes the new field occupies
    are whatever was in battery-backed SRAM. A timing mode is one byte. A page
    that happens to hold a 1 there is a page that commands fixed ignition
    timing at every speed, without anybody asking for it.

    So the schema is now a hash of the block's own layout - every field's slot
    name, offset, C type and element count, plus the block's base and size,
    exactly the inputs layout_id() uses for the whole page. Add, move, resize
    or rename a universal field and migrate_active() re-seeds instead of
    inheriting.

    Folded to 16 bits because CFG_U_SCHEMA is a u16, and forced non-zero so it
    can never coincide with erased SRAM."""
    parts = ["base=%d" % uni_base, "size=%d" % uni_size,
             "tables=%s" % TABLE_ORDER]      # the VVT targets live here
    for f in sorted(fields, key=lambda x: (x.offset, x.slot)):
        if uni_base <= f.offset < uni_base + uni_size:
            parts.append("%s:%d:%s:%d" % (f.slot, f.offset, f.ctype, f.count))
    v = binascii.crc32("|".join(parts).encode("ascii")) & 0xFFFFFFFF
    v = ((v >> 16) ^ (v & 0xFFFF)) & 0xFFFF
    return v or 1


def gen_header(fields, consts, uni_base, uni_size) -> str:
    w: list[str] = []
    a = w.append
    a("/*")
    a(" * hc_config_generated.h - GENERATED. Do not edit.")
    a(" *")
    a(" * Source: tools/config_source/generate_config.py, over the layout in")
    a(" * firmware/config/hcconfig.h and the metadata in")
    a(" * tools/config_source/hanicore_config_def.py.")
    a(" *")
    a(" * This header does NOT redefine hcconfig.h's offsets. hcconfig.h owns")
    a(" * the layout; everything here either comes from it or lives inside the")
    a(" * region it reserves as CFG_UNIVERSAL_BASE. The compile-time checks at")
    a(" * the bottom fail the BUILD if the two ever disagree, which is the")
    a(" * whole point: an offset that exists in two places is an offset that")
    a(" * will eventually differ in two places.")
    a(" */")
    a("#ifndef HC_CONFIG_GENERATED_H")
    a("#define HC_CONFIG_GENERATED_H")
    a("")
    a('#include "hcconfig.h"')
    a("")
    a("/* ---------------------------------------------------------- limits -- */")
    a("/* The universal model's ceiling. HC_MAX_CYL (%d) is what the LEGACY"
      % consts["HC_MAX_CYL"])
    a("   arrays in hcconfig.h are sized for; CFG_U_TDC_CYL_EXT and the")
    a("   universal pin arrays carry cylinders %d..%d, so nothing in the"
      % (consts["HC_MAX_CYL"] + 1, MODEL.MAX_CYL_UNIVERSAL))
    a("   architecture assumes 4, 6 or 8. */")
    a("#define HC_MAX_CYL_UNIVERSAL         %du" % MODEL.MAX_CYL_UNIVERSAL)
    a("#define HC_N_GENERIC_IO              %du" % MODEL.N_GENERIC)
    a("#define HC_PIN_NONE                  %du" % MODEL.PIN_NONE)
    a("#define HC_PHYSICAL_PIN_COUNT        %du" % HW.PIN_COUNT)
    a("/* DERIVED from the universal block's own layout - see")
    a("   universal_schema(). A literal here meant that adding a field")
    a("   left a battery-backed page from the previous firmware looking")
    a("   valid, with the new bytes holding whatever SRAM had. */")
    a("#define HC_UNIVERSAL_SCHEMA          0x%04Xu"
      % universal_schema(fields, uni_base, uni_size))
    a("#define HC_UNIVERSAL_MAGIC           0x4855u   /* 'HU' */")
    a("")
    a("/* ------------------------------------------------- layout identity -- */")
    a("/* DERIVED, never hand-maintained: a CRC32 over every field's slot name,")
    a("   offset, C type and element count, plus the page and core sizes. It is")
    a("   what a stored calibration record carries so that a firmware whose page")
    a("   layout has moved REFUSES the record instead of reinterpreting it. See")
    a("   layout_id() in tools/config_source/generate_config.py. */")
    a("#define HC_CFG_LAYOUT_ID             0x%08XuL" % layout_id(fields, consts))
    a("")
    a("/* -------------------------------------------------------- apply policy -- */")
    a("/* WHEN a validated change may reach the running engine. SAFETY_CRITICAL")
    a("   is NOT a member of this enum - it is an independent flag, because an")
    a("   oil-pressure shutdown threshold is LIVE_APPLY and safety critical at")
    a("   the same time and one enum cannot say both. */")
    a("typedef enum {")
    a("    HC_APPLY_LIVE     = 0,")
    a("    HC_APPLY_RPM_ZERO = 1,")
    a("    HC_APPLY_RESTART  = 2")
    a("} hc_apply_policy_t;")
    a("")
    a("/* The unit of atomicity for an RPM_ZERO_APPLY transaction. */")
    a("typedef enum {")
    for g in MODEL.ApplyGroup:
        a("    HC_GRP_%-18s = %d," % (g.name, g.value))
    a("    HC_GRP_COUNT")
    a("} hc_apply_group_t;")
    a("")
    a("/* Independent per-field flags. */")
    a("#define HC_FLAG_SAFETY_CRITICAL   0x01u")
    a("#define HC_FLAG_IS_PIN            0x02u   /* value is a physical pin */")
    a("")
    a("/* ------------------------------------------------- capability bits -- */")
    for name in ("AIN", "DIN", "FREQ_IN", "VR_IN", "HALL_IN", "LOW_SIDE",
                 "PWM_OUT", "INJ_OUT", "IGN_OUT", "DBW_HBRIDGE", "RELAY_OUT",
                 "MAIN_RELAY_HW",
                 "SPECIAL_LOCKED"):
        a("#define HC_PINCAP_%-14s 0x%04Xu" % (name, getattr(PinCap, name)))
    a("")
    a("/* ------------------------------------------------------------ enums -- */")
    for en in MODEL.ALL_ENUMS:
        a("/* %s: %s */" % (en.name, en.description.replace("\n", " ")))
        for val, ident, _label in en.options:
            a("#define HC_%-26s %du" % (ident, val))
        a("")
    a("/* ------------------------------- universal block field offsets -- */")
    a("/* Inside hcconfig.h's CFG_UNIVERSAL_BASE (%d, %d bytes reserved)."
      % (uni_base, uni_size))
    a("   %d bytes used." % MODEL.universal_size(uni_base))
    a("   Every one of these is an OFFSET INTO THE SAME 4096-byte page, so a")
    a("   TunerStudio write reaches them through the identical path as any")
    a("   calibration byte. */")
    for f in fields:
        if not is_universal(f.slot):
            continue
        cnt = ("[%d]" % f.count) if f.count > 1 else ""
        a("#define %-30s %4du /* %s%s %s */"
          % (f.slot, f.offset, f.ctype, cnt, f.meta.label))
    a("")
    a("/* ------------------------------------------------- the slot table -- */")
    a("/* One entry per configuration field, sorted by offset. The config")
    a("   manager classifies a written byte by BINARY SEARCH over this table:")
    a("   bounded, no allocation, no per-byte scan of the model. */")
    a("typedef struct {")
    a("    unsigned int  offset;      /* first byte                          */")
    a("    unsigned int  size;        /* bytes, including array elements     */")
    a("    unsigned char policy;      /* hc_apply_policy_t                   */")
    a("    unsigned char group;       /* hc_apply_group_t                    */")
    a("    unsigned char flags;       /* HC_FLAG_*                           */")
    a("    unsigned char elem;        /* bytes per element: 1 or 2           */")
    a("    unsigned int  pin_needs;   /* HC_PINCAP_* required, 0 if not a pin */")
    a("} hc_cfg_slot_t;")
    a("")
    a("#define HC_CFG_SLOT_COUNT   %du" % len(fields))
    a("extern const hc_cfg_slot_t hc_cfg_slots[HC_CFG_SLOT_COUNT];")
    a("")
    a("/* Slot covering `off`, or 0 when the byte belongs to a reserved area.")
    a("   Bounded: ceil(log2(HC_CFG_SLOT_COUNT)) iterations. */")
    a("const hc_cfg_slot_t *hc_cfg_slot_at(unsigned int off);")
    a("")
    a("/* Bit `g` set means apply group g contains at least one RPM_ZERO field. */")
    a("extern const unsigned int hc_cfg_rpm_zero_groups;")
    a("")
    # V98r2: the switch inputs, from hw_descriptors.SWITCH_INPUTS (the one
    # table): hc_hal_din() reads the ASIC ones by these arrays, and the
    # switchRaw output channel carries one bit per HC_SWITCH_CAV entry.
    sw = list(HW.SWITCH_INPUTS)
    asic = [c for c in sw if c in HW.SWITCH_INPUT_ASIC_BITS]
    lst = lambda xs: "{ " + ", ".join("%du" % x for x in xs) + " }"
    a("/* ------------------ switch inputs (hw_descriptors.SWITCH_INPUTS) -- */")
    a("#define HC_SWITCH_N          %du" % len(sw))
    a("#define HC_SWITCH_CAV        %s" % lst(sw))
    a("#define HC_SWITCH_ASIC_N     %du" % len(asic))
    a("#define HC_SWITCH_ASIC_CAV   %s" % lst(asic))
    a("#define HC_SWITCH_ASIC_WORD  %s"
      % lst(HW.SWITCH_INPUT_ASIC_BITS[c][0] for c in asic))
    a("#define HC_SWITCH_ASIC_BIT   %s"
      % lst(HW.SWITCH_INPUT_ASIC_BITS[c][1] for c in asic))
    a("")
    a("/* --------------------------------------------- compile-time checks -- */")
    a("/* If hcconfig.h moves a field, these stop the BUILD rather than letting")
    a("   a generated header describe a page that no longer exists. C89 has no")
    a("   static_assert, so this is the negative-array-size idiom. */")
    a("typedef char hc_cfg_assert_page_size[(HC_CFG_SIZE == %du) ? 1 : -1];"
      % consts["HC_CFG_SIZE"])
    a("typedef char hc_cfg_assert_uni_base[(CFG_UNIVERSAL_BASE == %du) ? 1 : -1];"
      % uni_base)
    a("typedef char hc_cfg_assert_uni_size[(CFG_UNIVERSAL_SIZE == %du) ? 1 : -1];"
      % uni_size)
    a("typedef char hc_cfg_assert_uni_fits[(%du <= CFG_UNIVERSAL_SIZE) ? 1 : -1];"
      % MODEL.universal_size(uni_base))
    a("typedef char hc_cfg_assert_max_cyl[(HC_MAX_CYL == %du) ? 1 : -1];"
      % consts["HC_MAX_CYL"])
    for f in fields:
        if is_universal(f.slot):
            continue
        a("typedef char hc_cfg_assert_%s[(%s == %du) ? 1 : -1];"
          % (f.slot.lower(), f.slot, f.offset))
    a("")
    a("#endif /* HC_CONFIG_GENERATED_H */")
    return "\n".join(w) + "\n"


# ==========================================================================
# C source
# ==========================================================================
def gen_source(fields) -> str:
    w: list[str] = []
    a = w.append
    a("/*")
    a(" * hc_config_generated.c - GENERATED. Do not edit.")
    a(" *")
    a(" * The slot table and the bounded lookup over it. Everything here is")
    a(" * `const`, so it lands in NCONST (program flash) and costs no RAM - the")
    a(" * near RAM on these boards is under 2 KB and the engine layer has to")
    a(" * fit in it.")
    a(" */")
    a('#include "hc_config_generated.h"')
    a("")
    a("const hc_cfg_slot_t hc_cfg_slots[HC_CFG_SLOT_COUNT] = {")
    for f in fields:
        elem = 1 if f.ctype == "u8" else 2
        flags = []
        if f.meta.safety_critical:
            flags.append("HC_FLAG_SAFETY_CRITICAL")
        if f.meta.is_pin:
            flags.append("HC_FLAG_IS_PIN")
        flag_s = "|".join(flags) if flags else "0u"
        needs = f.meta.pin_needs if f.meta.is_pin else 0
        a("    { %4du, %4du, %-19s, HC_GRP_%-18s, %-42s, %du, 0x%04Xu }, /* %s */"
          % (f.offset, f.size, POLICY_C[f.meta.apply], f.meta.group.name,
             flag_s, elem, needs, f.meta.ts))
    a("};")
    a("")
    groups = 0
    for f in fields:
        if f.meta.apply is ApplyPolicy.RPM_ZERO_APPLY:
            groups |= 1 << f.meta.group.value
    a("/* Apply groups that contain at least one RPM_ZERO field. A group not in")
    a("   this mask can never become dirty, so the manager never waits on it. */")
    a("const unsigned int hc_cfg_rpm_zero_groups = 0x%04Xu;" % groups)
    a("")
    a("const hc_cfg_slot_t *hc_cfg_slot_at(unsigned int off)")
    a("{")
    a("    unsigned int lo = 0u;")
    a("    unsigned int hi = HC_CFG_SLOT_COUNT;")
    a("")
    a("    /* Strictly bounded: the table is sorted by offset and the window")
    a("       halves every pass, so this cannot run longer than 9 iterations")
    a("       for %d slots. No recursion, no allocation, safe from a task or" % len(fields))
    a("       from an interrupt. */")
    a("    while (lo < hi) {")
    a("        unsigned int mid = lo + ((hi - lo) >> 1);")
    a("        const hc_cfg_slot_t *s = &hc_cfg_slots[mid];")
    a("        if (off < s->offset) {")
    a("            hi = mid;")
    a("        } else if (off >= s->offset + s->size) {")
    a("            lo = mid + 1u;")
    a("        } else {")
    a("            return s;")
    a("        }")
    a("    }")
    a("    return (const hc_cfg_slot_t *)0;   /* a reserved byte */")
    a("}")
    return "\n".join(w) + "\n"


# ==========================================================================
# per-target pin descriptors
# ==========================================================================
PIN_DESC_H = '''/*
 * hc_pin_descriptor.h - the PHYSICAL ECU PIN model.
 *
 * The user-facing I/O contract: TunerStudio names connector pins 1..121 and
 * nothing else. No P2.x, no ADC channel number, no CAPCOM index, no ASIC pin.
 * Those are on the far side of this interface.
 *
 *      logical function  ->  physical connector pin  ->  target descriptor
 *                                                    ->  C167 / ASIC resource
 *
 * ONE DESCRIPTOR PER BOARD. A pin number means nothing until you say which
 * ECU it is on: connector pin 21 is the J271 main relay path on the ME7.5
 * board and "ZAS2_S, Zylinderabschaltung 2" on Bosch's ME7.1 sheet. Exactly
 * one hc_pin_desc_<target>.c is compiled into any image, and it is chosen by
 * the target's own build script.
 *
 * EVIDENCE IS PER CAPABILITY. `caps` is everything the pin's circuit is
 * believed to do; `caps_verified` is the subset supported at VERIFIED. A
 * caller that must not act on an inference tests caps_verified.
 *
 * GENERATED by tools/config_source/generate_config.py from
 * tools/config_source/hw_descriptors.py. Do not edit the .c files.
 */
#ifndef HC_PIN_DESCRIPTOR_H
#define HC_PIN_DESCRIPTOR_H

#include "hc_config_generated.h"
#include "hctarget.h"   /* HC_COLD: far on ME7.1.1 (V98r2: this module is FCODE) */
#ifndef HC_COLD
#define HC_COLD
#endif

typedef struct {
    unsigned int  caps;           /* every HC_PINCAP_* believed to apply     */
    unsigned int  caps_verified;  /* the subset supported at VERIFIED        */
    unsigned char routable;       /* 1 = a main-CPU resource exists for it   */
    unsigned char adc_ch;         /* this CPU's ADC channel, or HC_ADC_NONE  */
} hc_pin_desc_t;

/* The pin has no analog channel on THIS board's main CPU. It may still be an
   analog input electrically - the ME7.1.1's coolant and intake-air cavities
   are, but they land on the peripheral ASIC and reach this CPU only inside the
   SSC frame - so HC_ADC_NONE means "not readable by this CPU's converter",
   not "not a sensor". */
#define HC_ADC_NONE   0xFFu

/* Where the table lives: huge on ME7.1.1 (HCONST, 2026-10-14 - the
   near-constant class had no room left; only far code reads it). */
#ifndef HC_PIN_MEM
#define HC_PIN_MEM
#endif

/* V86: an analog input read by the PERIPHERAL ASIC's converter channel n
   (ME7.1.1: coolant cavity 93 = ASIC AN0, intake air cavity 26 = ASIC AN1).
   It is a real, routable resource - the board's HAL reads it out of the
   S5500 frame - but it is not this CPU's ADC, so it is coded apart from the
   0..15 main-CPU channels. A HAL that has no such path treats the code like
   any other channel it does not have. */
#define HC_ADC_ASIC(n)      ((unsigned char)(0xE0u | ((n) & 0x0Fu)))
#define HC_ADC_IS_ASIC(c)   (((c) & 0xF0u) == 0xE0u)

/* Provided by exactly one hc_pin_desc_<target>.c. */
extern const hc_pin_desc_t HC_PIN_MEM hc_pin_table[HC_PHYSICAL_PIN_COUNT];
extern const unsigned int  hc_pin_target_id;
extern const char          hc_pin_target_name[];

/* 0 for pin 0, pin > 121, or HC_PIN_NONE. */
const hc_pin_desc_t HC_PIN_MEM *HC_COLD hc_pin_desc(unsigned char pin);

/* 1 only when the pin exists, is ROUTABLE on this board, and its circuit
   provides EVERY bit in `need`.

   "Every bit", not "any bit". The first version of this test returned true on
   any overlap, so a pin advertising only LOW_SIDE satisfied a request for
   INJ_OUT|LOW_SIDE - and with ~60 pins defaulted to DIN|LOW_SIDE, almost any
   pin could be assigned as an injector driver.

   SPECIAL_LOCKED IS NOT TESTED HERE, AND THAT IS DELIBERATE. It marks a
   DEDICATED circuit, not an unusable one: connector pin 82 is the crank
   sensor's differential input through the CJ910, and 117/118 are the throttle
   motor's H-bridge terminals. Refusing every SPECIAL_LOCKED pin - which is
   what this function did first - meant the crank input could not be assigned
   to the crank pin, and hc_validate() reported PIN_CAP on a configuration
   that is the only correct one for the board.

   What actually protects a dedicated wire is its CAPABILITY SET. A power
   ground, a 5 V supply, a screen, the CAN pair and the K-line carry
   SPECIAL_LOCKED and NOTHING ELSE, so they satisfy no request at all. A pin
   that does have a capability has it because its circuit really provides it,
   and denying its own function on top of that protects nothing. */
unsigned char HC_COLD hc_pin_can(unsigned char pin, unsigned int need);

/* 1 when the pin is a DEDICATED circuit - one function, not repurposable.
   Advisory: a user interface should say so beside the assignment. Nothing in
   the validation engine refuses on it, for the reason above. */
unsigned char HC_COLD hc_pin_is_dedicated(unsigned char pin);

/* Same, but only counting VERIFIED capabilities. */
unsigned char HC_COLD hc_pin_can_verified(unsigned char pin, unsigned int need);

/* This CPU's ADC channel for the pin, or HC_ADC_NONE. This is the ONE place
   that turns a connector cavity into something the converter can read, and it
   is generated from Bosch's own port map rather than typed. */
unsigned char HC_COLD hc_pin_adc_channel(unsigned char pin);

/* HC_PIN_NONE is a legal value everywhere a pin is configured; it means the
   function is not routed. Distinguish it from a bad pin number. */
#define HC_PIN_IS_UNASSIGNED(p)   ((p) == HC_PIN_NONE)

#endif /* HC_PIN_DESCRIPTOR_H */
'''

PIN_DESC_C_BODY = '''/*
 * hc_pin_descriptor.c - queries over whichever descriptor was linked.
 */
#include "hc_pin_descriptor.h"

const hc_pin_desc_t HC_PIN_MEM *HC_COLD hc_pin_desc(unsigned char pin)
{
    if (pin == 0u || pin > HC_PHYSICAL_PIN_COUNT) {
        return (const hc_pin_desc_t HC_PIN_MEM *)0;
    }
    return &hc_pin_table[pin - 1u];
}

static unsigned char can(const hc_pin_desc_t HC_PIN_MEM *d, unsigned int have,
                         unsigned int need)
{
    if (d == (const hc_pin_desc_t HC_PIN_MEM *)0) {
        return 0u;
    }
    if (!d->routable) {
        return 0u;              /* no resource on this board drives it */
    }
    if (need == 0u) {
        /* "does this pin exist, and does its circuit do anything at all". A
           ground or a screen answers no here, because it carries
           SPECIAL_LOCKED and no capability bit beside it. */
        return (unsigned char)(((have & ~HC_PINCAP_SPECIAL_LOCKED) != 0u)
                               ? 1u : 0u);
    }
    /* EVERY requested bit, not any of them. See the note in the header for
       why SPECIAL_LOCKED is not a veto. */
    return (unsigned char)(((have & need) == need) ? 1u : 0u);
}

unsigned char HC_COLD hc_pin_is_dedicated(unsigned char pin)
{
    const hc_pin_desc_t HC_PIN_MEM *d = hc_pin_desc(pin);
    if (d == (const hc_pin_desc_t HC_PIN_MEM *)0) {
        return 0u;
    }
    return (unsigned char)((d->caps & HC_PINCAP_SPECIAL_LOCKED) ? 1u : 0u);
}

unsigned char HC_COLD hc_pin_can(unsigned char pin, unsigned int need)
{
    const hc_pin_desc_t HC_PIN_MEM *d = hc_pin_desc(pin);
    return can(d, d ? d->caps : 0u, need);
}

unsigned char HC_COLD hc_pin_can_verified(unsigned char pin, unsigned int need)
{
    const hc_pin_desc_t HC_PIN_MEM *d = hc_pin_desc(pin);
    return can(d, d ? d->caps_verified : 0u, need);
}

unsigned char HC_COLD hc_pin_adc_channel(unsigned char pin)
{
    const hc_pin_desc_t HC_PIN_MEM *d = hc_pin_desc(pin);
    if (d == (const hc_pin_desc_t HC_PIN_MEM *)0) {
        return HC_ADC_NONE;
    }
    return d->adc_ch;
}
'''


def gen_pin_desc(d) -> str:
    w: list[str] = []
    a = w.append
    a("/*")
    a(" * hc_pin_desc_%s.c - GENERATED. Do not edit." % d.target_id.lower())
    a(" *")
    a(" * %s" % d.name)
    a(" * Connector: %s" % d.connector)
    a(" *")
    a(" * Derived by tools/config_source/hw_descriptors.py from the sources")
    a(" * named in that file. A pin this evidence does not describe has NO")
    a(" * capabilities and routable = 0; there is deliberately no")
    a(" * \"spare I/O, digital in or low side\" default.")
    a(" *")
    a(" * Machine-readable review copy:")
    a(" *   build/generated/hc_hw_descriptor_%s.csv" % d.target_id.lower())
    a(" */")
    a('#include "hc_pin_descriptor.h"')
    a("")
    a("const unsigned int hc_pin_target_id = 0x%04Xu;"
      % (sum(ord(c) for c in d.target_id) & 0xFFFF))
    a('const char hc_pin_target_name[] = "%s";' % d.target_id)
    a("")
    a("const hc_pin_desc_t HC_PIN_MEM hc_pin_table[HC_PHYSICAL_PIN_COUNT] = {")
    for p in d.pins:
        ver = p.caps_at_least(EvidenceClass.VERIFIED)
        note = p.oem_name or "not assigned in the source document"
        m = re.search(r"AN(\d+)", p.hal_resource or "")
        adc = int(m.group(1)) if m else 0xFF
        if (m and (p.hal_resource or "").startswith("ASIC")
                and d.target_id == "BOSCH_ME711"):
            # V86: the PERIPHERAL ASIC's converter, not this CPU's - see
            # HC_ADC_ASIC() in hc_pin_descriptor.h. ME7.1.1 only: its HAL
            # reads ASIC AN0/AN1 from the S5500 frame. The deferred ME7.5
            # descriptor keeps its V85 encoding byte for byte.
            adc = 0xE0 | int(m.group(1))
        routable = bool(p.hal_resource)
        if d.target_id == "BOSCH_ME711" and p.hal_resource == "NOT_ON_MAIN_CPU":
            # V95: "NOT_ON_MAIN_CPU" is the ABSENCE of a resource, and the .ini
            # generator (gen_ts_ini_me711._pin_ok) has always read it so - the
            # firmware read it as routable. The validator then accepted e.g.
            # pinIat = 85 or a pump on 46 that no dropdown offered and no HAL
            # path reads or drives: a silent dead route. ME7.1.1 only; the
            # deferred ME7.5 table stays byte for byte.
            routable = False
        a("    { 0x%04Xu, 0x%04Xu, %du, 0x%02Xu }, /* %3d %s */"
          % (p.capabilities, ver, 1 if routable else 0, adc,
             p.number, note[:40]))
    a("};")
    return "\n".join(w) + "\n"


# ==========================================================================
# presets
# ==========================================================================
PRESET_H = R"""/*
 * hc_presets.h - engine and component presets.
 *
 * A PRESET IS ONLY A FUNCTION THAT FILLS IN ORDINARY CONFIGURATION FIELDS.
 * Once validated, every value goes through hc_cfg_mgr_write_u8(), so it obeys
 * the same apply policy as if a tuner had typed it, and every value stays editable
 * afterwards. There is deliberately no runtime state saying which preset was
 * applied and NO runtime code may branch on one - an
 * `if (preset == ME711_V8)` in a control path is the thing this whole
 * architecture exists to prevent.
 *
 * WHAT IS NOT HERE. Component presets ship with nothing but CUSTOM. Not one
 * injector, coil or pressure-sensor datasheet exists in this repository, and
 * the previous version's dead-time and dwell curves were arithmetic sequences
 * labelled VERIFIED. An empty field costs a tuner five minutes; a fabricated
 * dead-time curve runs a cylinder lean. See
 * tools/config_source/hanicore_presets.py for the full list of what was
 * removed and why.
 *
 * GENERATED by tools/config_source/generate_config.py. Do not edit.
 */
#ifndef HC_PRESETS_H
#define HC_PRESETS_H

#include "hc_config_generated.h"
#include "hctarget.h"   /* HC_COLD: far on ME7.1.1 (FCODE, V98), empty elsewhere */
#ifndef HC_COLD
#define HC_COLD
#endif
#ifndef HC_PRESET_MEM
#define HC_PRESET_MEM   /* huge on ME7.1.1: the tables live in HCONST */
#endif

/* A PRESET IS A LIST OF BYTE RUNS (2026-10-11). Each run is: page offset
   (high byte, low byte), a length n (1..255), then the n page bytes in page
   order - a u16 field's value is its two big-endian page bytes, exactly what
   hc_cal_set_u16() and the transaction stage. Items that follow each other
   in the page share one run; item order is kept, so a later value still
   wins. The 6-byte {offset, value, width} item it replaces spent 10.5 KB of
   HCONST on 1755 values; the bytes and their order are unchanged. */
typedef struct {
    unsigned char id;
    const unsigned char HC_PRESET_MEM *runs;
    unsigned int  n_items;    /* values set (fields x elements), for tools */
    unsigned int  target_id;  /* 0 = any board; else hc_pin_target_id */
    unsigned char board_default; /* 1 = this board's fresh-page routing */
    unsigned int  n_bytes;    /* length of runs[] */
} hc_preset_t;

extern const hc_preset_t hc_engine_presets[];
extern const unsigned char hc_engine_preset_count;

/* THE BOARD'S OWN DEFAULT ROUTING, or 0 if this board declares none.
 *
 * It is an ordinary preset - the id of the one marked `board_default` in
 * tools/config_source/hanicore_presets.py whose target is this image's board.
 * Nothing branches on it at runtime and every value it writes stays editable.
 * What it is FOR is the seed: see hc_preset_apply_engine_active(). */
unsigned char HC_COLD hc_preset_board_default_id(void);

/* Apply a preset to the ACTIVE calibration page rather than to DESIRED.
 *
 * WHY THERE ARE TWO OF THESE AND NOT ONE WITH A FLAG. hc_preset_apply_engine()
 * is what a TUNER's preset button does: it writes DESIRED, which is then
 * validated and applied under the ordinary apply-policy rules. This one is for
 * hc_cfg_mgr_init()'s SEED, which runs before DESIRED exists - it is building
 * the page that DESIRED will be copied FROM. Writing through the config
 * manager there would be writing into a buffer that is about to be
 * overwritten by the thing it is seeding.
 *
 * Same table, same values, same provenance; different destination. */
unsigned char HC_COLD hc_preset_apply_engine_active(unsigned char id);

/* What a TUNER's "Apply engine preset" button does (TunerStudio `!E`,
 * serviced from the main loop - never inside the command handler).
 *
 * ONE TRANSACTION, V86. Every value is staged into DESIRED, the WHOLE
 * resulting page is validated, and only then does anything go through the
 * ordinary apply policy (LIVE across at once, RPM_ZERO groups applied now -
 * the engine is stopped by precondition - RESTART pending). If the page does
 * not validate, every staged byte is put back: nothing is half-applied,
 * not even a LIVE calibration field. It never Burns.
 *
 * Until V86 this function wrote field by field through hc_cfg_mgr_write_u8()
 * - LIVE fields reaching ACTIVE before the rest was validated - and NOTHING
 * CALLED IT: no command reached it, so selecting a preset in TunerStudio only
 * ever changed the enginePreset byte. */
#define HC_PRESET_APPLIED       0u
#define HC_PRESET_NO_SUCH       1u  /* no preset with that id            */
#define HC_PRESET_WRONG_BOARD   2u  /* carries another ECU's pin numbers */
#define HC_PRESET_NOT_STOPPED   3u  /* rpm != 0                          */
#define HC_PRESET_PAGE_INVALID  4u  /* hc_validate refused the result -
                                       hc_cfg_txn_faults says why, and
                                       nothing was changed               */
unsigned char HC_COLD hc_preset_apply_engine(unsigned char id, unsigned int rpm);

#endif /* HC_PRESETS_H */
"""

PRESET_C_TAIL = R"""
unsigned char HC_COLD hc_preset_board_default_id(void)
{
    unsigned char i;

    for (i = 0u; i < hc_engine_preset_count; i++) {
        if (hc_engine_presets[i].board_default
            && hc_engine_presets[i].target_id == hc_pin_target_id) {
            return hc_engine_presets[i].id;
        }
    }
    return 0u;
}

static const hc_preset_t *preset_for(unsigned char id)
{
    unsigned char i;

    for (i = 0u; i < hc_engine_preset_count; i++) {
        if (hc_engine_presets[i].id == id) {
            return &hc_engine_presets[i];
        }
    }
    return 0;
}

unsigned char HC_COLD hc_preset_apply_engine_active(unsigned char id)
{
    unsigned int k;
    const hc_preset_t *p = preset_for(id);

    if (p == 0) {
        return 1u;
    }
    if (p->target_id != 0u && p->target_id != hc_pin_target_id) {
        return 2u;
    }
    for (k = 0u; k < p->n_bytes; ) {
        unsigned int off = ((unsigned int)p->runs[k] << 8) | p->runs[k + 1u];
        unsigned char n = p->runs[k + 2u];
        k += 3u;
        while (n--) {
            hc_cal_set_u8(off++, p->runs[k++]);
        }
    }
    hc_cal_set_u8(CFG_U_ENGINE_PRESET, id);
    return 0u;
}

unsigned char HC_COLD hc_preset_apply_engine(unsigned char id, unsigned int rpm)
{
    unsigned int k;
    const hc_preset_t *p = preset_for(id);

    if (p == 0) {
        return HC_PRESET_NO_SUCH;
    }
    if (p->target_id != 0u && p->target_id != hc_pin_target_id) {
        /* The preset names physical connector pins, and a connector pin means
           nothing until you say which ECU it is on. Applying an ME7.5 preset
           to a Bosch board would route injectors by number onto whatever
           those numbers happen to be over there. */
        return HC_PRESET_WRONG_BOARD;
    }
    if (rpm != 0u) {
        return HC_PRESET_NOT_STOPPED;
    }
    /* ONE TRANSACTION (V86). Every value is staged into DESIRED with its old
       byte logged; the WHOLE resulting page is validated; a refusal puts
       every staged byte back, so nothing - not DESIRED, not ACTIVE, not a
       LIVE calibration field - is left half-applied. Only a page that
       validates goes through the ordinary per-field apply policy. Never a
       Burn: that stays the tuner's own action. */
    hc_cfg_mgr_txn_begin();
    for (k = 0u; k < p->n_bytes; ) {
        unsigned int off = ((unsigned int)p->runs[k] << 8) | p->runs[k + 1u];
        unsigned char n = p->runs[k + 2u];
        k += 3u;
        while (n--) {
            hc_cfg_mgr_txn_put_u8(off++, p->runs[k++]);
        }
    }
    /* The preset id is itself a configuration field, so a page tells you what
       it was seeded from. Nothing reads it back except the user interface. */
    hc_cfg_mgr_txn_put_u8(CFG_U_ENGINE_PRESET, id);
    if (hc_cfg_mgr_txn_commit(rpm) != HC_VAL_OK) {
        return HC_PRESET_PAGE_INVALID;
    }
    return HC_PRESET_APPLIED;
}
"""


def _target_expr(target):
    if not target:
        return "0u"
    return "0x%04Xu" % (sum(ord(c) for c in target) & 0xFFFF)


def gen_presets(fields):
    """C for the engine presets, from hanicore_presets.py.

    Every value is resolved against the MODEL, so a preset naming a field that
    does not exist is a generation failure rather than a silent no-op."""
    idx = {f.meta.ts: f for f in fields}
    w = []
    a = w.append
    a("/*")
    a(" * hc_presets.c - GENERATED. Do not edit.")
    a(" *")
    a(" * Provenance for every value below is in")
    a(" * tools/config_source/hanicore_presets.py, and the gaps - the values a")
    a(" * preset deliberately does NOT set because this repository cannot prove")
    a(" * them - are listed there too. Run")
    a(" *   py tools\\config_source\\hanicore_presets.py --gaps")
    a(" */")
    a("#ifdef HC_FAR_BRIDGE")
    a('#include "hcfarbridge.h"  /* FIRST: FAR code on ME7.1.1 (V98 NCODE relief) */')
    a("#endif")
    a('#include "hc_presets.h"')
    a('#include "hc_config_manager.h"')
    a('#include "hc_pin_descriptor.h"')
    a("")
    problems = []
    counts = {}
    nbytes_of = {}
    for pr in PRESETS.ENGINE_PRESETS:
        items = []
        for key, val in pr.values.items():
            f = idx.get(key)
            if f is None:
                problems.append("preset %s sets %s, which is not a field in "
                                "the model" % (pr.key, key))
                continue
            width = 1 if f.ctype == "u8" else 2
            vals = val.value if isinstance(val.value, list) else [val.value]
            if len(vals) > f.count:
                problems.append("preset %s gives %d values for %s, which is %d "
                                "wide" % (pr.key, len(vals), key, f.count))
                continue
            # V93: A PRESET VALUE OUTSIDE ITS FIELD'S DECLARED RANGE IS A
            # GENERATION FAILURE. V92 shipped cltEnrAx 700..2200 (10*C+1000)
            # into a field whose raw range is 9500..12000 (10*C+10000): every
            # axis point sat below any real coolant temperature and warm-up
            # enrichment was 100 % on the car at 17 C
            #. 255 on a pin field is
            # the "no pin" sentinel, not a value.
            lo, hi = getattr(f.meta, "lo", None), getattr(f.meta, "hi", None)
            for n, v in enumerate(vals):
                if (lo is not None and hi is not None
                        and not (getattr(f.meta, "is_pin", False) and v == 255)
                        and not (lo <= int(v) <= hi)):
                    problems.append("preset %s sets %s[%d] = %d, outside the "
                                    "field's range %d..%d" % (pr.key, key, n,
                                                              int(v), lo, hi))
            for n, v in enumerate(vals):
                items.append((f.offset + n * width, int(v), width,
                              ("%s[%d]" % (key, n)) if f.count > 1 else key))
        counts[pr.key] = len(items)
        if problems:
            continue
        a("/* %s */" % pr.name)
        if items:
            # THE ITEM LISTING stays in the file as comments (one ITEM line
            # per value, the old row format) - gates and readers parse it;
            # the compiled table is the byte runs that follow it.
            runs = []                 # [offset, bytearray]
            for off, v, wdt, why in items:
                # a signed field's negative value is stored as its two's
                # complement in the field's width (V97: trigAngleX10 -20 =
                # 0xFFEC)
                u = v & ((1 << (8 * wdt)) - 1)
                if v < 0:
                    a("/* ITEM { %4du, %5du, %du } %s = %d */" % (off, u, wdt, why, v))
                else:
                    a("/* ITEM { %4du, %5du, %du } %s */" % (off, u, wdt, why))
                b = bytes([u >> 8, u & 0xFF]) if wdt == 2 else bytes([u])
                if (runs and runs[-1][0] + len(runs[-1][1]) == off
                        and len(runs[-1][1]) + wdt <= 255):
                    runs[-1][1].extend(b)
                else:
                    runs.append([off, bytearray(b)])
            a("static const unsigned char HC_PRESET_MEM runs_%s[] = {"
              % pr.key.lower())
            nbytes = 0
            for off, b in runs:
                a("    0x%02Xu, 0x%02Xu, %du, /* offset %d */"
                  % (off >> 8, off & 0xFF, len(b), off))
                for i in range(0, len(b), 12):
                    a("        " + ", ".join("0x%02Xu" % x for x in b[i:i + 12]) + ",")
                nbytes += 3 + len(b)
            a("};")
            a("")
            nbytes_of[pr.key] = nbytes
    if problems:
        raise SystemExit("preset generation refused:\n  " + "\n  ".join(problems))
    a("const hc_preset_t hc_engine_presets[] = {")
    for pr in PRESETS.ENGINE_PRESETS:
        n = counts[pr.key]
        bd = 1 if getattr(pr, "board_default", False) else 0
        if n:
            a("    { %du, runs_%s, %du, %s, %du, %du }, /* %s%s */"
              % (pr.ident, pr.key.lower(), n, _target_expr(pr.target), bd,
                 nbytes_of[pr.key], pr.name, " - BOARD DEFAULT" if bd else ""))
        else:
            a("    { %du, 0, 0u, 0u, %du, 0u }, /* %s - populates nothing by design */"
              % (pr.ident, bd, pr.name))
    a("};")
    a("")
    a("const unsigned char hc_engine_preset_count = %du;"
      % len(PRESETS.ENGINE_PRESETS))
    a("")
    # THE BOARD DEFAULT IS A FLAG IN THE TABLE, NOT A CONSTANT EXPRESSION.
    #
    # The first version emitted `(hc_pin_target_id == 0x02F9) ? 2u : 0u` as a
    # file-scope initialiser. `hc_pin_target_id` is a const OBJECT, and a const
    # object is not a constant expression in C - the C166 compiler is entitled
    # to reject it, and one hc_presets.c is linked against whichever descriptor
    # the target build chose, so the answer genuinely is not known until link
    # time. A one-line scan at seed time costs nothing and is correct.
    boards = [pr for pr in PRESETS.ENGINE_PRESETS
              if getattr(pr, "board_default", False)]
    per_target = {}
    for pr in boards:
        per_target.setdefault(pr.target, []).append(pr.key)
    dupes = {t_: k for t_, k in per_target.items() if len(k) > 1}
    if dupes:
        raise SystemExit("more than one board_default preset per target: %s"
                         % dupes)
    a(PRESET_C_TAIL)
    return "\n".join(w) + "\n"



# ==========================================================================
# TunerStudio view of the universal block
# ==========================================================================
def universal_ini_lines() -> list[str]:
    """The [Constants] lines for the universal block, emitted from the model.

    Both .ini generators call this instead of retyping offsets. Returns plain
    strings with no leading newline."""
    fields, consts, problems = MODEL.resolve()
    if problems:
        raise SystemExit("model does not resolve; run generate_config.py:\n  "
                         + "\n  ".join(problems))
    uni_base = _raw_define("CFG_UNIVERSAL_BASE")
    uni_size = _raw_define("CFG_UNIVERSAL_SIZE")
    out: list[str] = []
    out.append("   ; ---- the universal configuration block ---------------------------")
    out.append("   ; GENERATED from tools/config_source/hanicore_config_def.py by")
    out.append("   ; generate_config.py:universal_ini_lines(). Every offset below is")
    out.append("   ; the model's own, and the model's offsets are hcconfig.h's, so")
    out.append("   ; there is no third place for them to drift in.")
    for f in fields:
        if not is_universal(f.slot):
            continue
        m = f.meta
        t = TS_TYPE[f.ctype]
        if f.count > 1:
            out.append('   %-22s = array,  %s, %4d, [%d], "%s", %s, %s, %s, %s, %d'
                       % ((m.ts, t, f.offset, f.count, m.units)
                          + ts_scaling(m) + (m.digits,)))
        elif m.is_pin:
            # A PIN IS A CHOICE FROM THIS BOARD, NOT A NUMBER TO TYPE.
            #
            # These were `scalar, U08, off, "", 1, 0, 0, 255, 0` - free numeric
            # entry over 0..255, on fields where all but a handful of values are
            # electrically impossible. the project rules name it: "NEVER SHOW
            # A RAW NUMBER FOR A SEMANTIC VALUE", and every injector and coil pin
            # was on that list.
            #
            # The label list is generated from the SAME hardware descriptor that
            # hc_validate() and the runtime router use, filtered by the SAME
            # capability rule, so the dropdown cannot offer something the ECU
            # would refuse. The stored encoding is unchanged - `bits` maps an
            # existing integer - so no firmware and no layout moves.
            out.append('   %-22s = bits,   %s, %4d, [0:7], %s'
                       % (m.ts, t, f.offset, _pin_labels(m.pin_needs, m.ts)))
        elif m.enum is not None:
            labels = _enum_labels(m.enum)
            out.append('   %-22s = bits,   %s, %4d, [0:%d], %s'
                       % (m.ts, t, f.offset, _bits_for(m.enum), labels))
        else:
            out.append('   %-22s = scalar, %s, %4d, "%s", %s, %s, %s, %s, %d'
                       % ((m.ts, t, f.offset, m.units)
                          + ts_scaling(m) + (m.digits,)))
    for name, off, n in reserved_arrays(consts["HC_CFG_SIZE"], uni_base, uni_size):
        if name == "uniReserved":
            out.append('   %-22s = array,  U08, %4d, [%d], "", 1, 0, 0, 255, 0'
                       % (name, off, n))
    return out


def _num(v: float) -> str:
    if float(v) == int(v):
        return str(int(v))
    return repr(round(float(v), 6))


def ts_scaling(m) -> tuple[str, str, str, str]:
    """(scale, translate, lo, hi) as TunerStudio must be told them.

    THE METADATA AND TUNERSTUDIO DISAGREE ABOUT WHAT "translate" MEANS, and
    this is the one place that converts. A Meta says display = raw*scale +
    translate, with lo/hi in RAW counts - that is how every note in
    hanicore_config_def.py reasons. TunerStudio computes
        userValue = (msValue + translate) * scale
    with min/max in USER units (Speeduino .../speeduino.ini
    lines 193-194 state it). Emitting the Meta's translate unconverted made
    the ignition map, decoded by hcengine.c as (cell - 40) * 0.5 deg, display
    (cell - 20) * 0.5 - TEN DEGREES more advance than the ECU fires - and put
    coolant at 1070 C. Identity for scale 1 / translate 0, which is most
    fields."""
    s = float(m.scale) if m.scale else 1.0
    t = float(m.translate)
    return (_num(s), _num(t / s), _num(m.lo * s + t), _num(m.hi * s + t))


def _bits_for(en) -> int:
    top = max(v for v, _i, _l in en.options)
    n = 1
    while (1 << n) - 1 < top:
        n += 1
    return n - 1


# THE CAPABILITY RULE, MIRRORED FROM hc_validation.c.
#
# `pin_needs` is a UI hint and is NOT always a conjunction. hc_validation.c:619
# tests the crank pin for VR_IN, then HALL_IN, then FREQ_IN and fails only if
# ALL THREE are absent - deliberately, because cavity 82 is VR_IN|FREQ_IN with
# no Hall and a conjunction would refuse the one crank cavity this board has.
# pinMaf declares AIN|FREQ_IN and the firmware passes plain AIN.
#
# A dropdown that disagreed with the validator would be worse than a number
# field: it would offer a cavity the ECU then refuses. Same table as
# me711_preset_routing_proof, same reason.
_PIN_RULE_ANY = {
    "pinCrank": PinCap.VR_IN | PinCap.HALL_IN | PinCap.FREQ_IN,
    # a CPU-driven relay output, OR the supply IC's own main-relay stage -
    # hc_validation.c accepts the same two for CFG_U_PIN_MAIN_RELAY only.
    "pinMainRelay": PinCap.RELAY_OUT | PinCap.MAIN_RELAY_HW,
}
_PIN_RULE_ALL = {
    "pinMaf": PinCap.AIN,
}

# A CAPABILITY IS NOT A CAPTURE UNIT.
#
# Cavity 29 carries FREQ_IN and is routable (it is the air-mass input on AN0),
# so a capability-only filter offered it as a CRANK - and V62's hc_validate()
# REFUSES it, because hc_hal_capture_channel(29) is HC_CAPCH_NONE. A dropdown
# that offers what the ECU rejects is worse than a number field.
#
# These are the three cavities hchal_me711.c:hc_hal_capture_channel() maps, and
# me711_routing_binding_proof asserts this list and that function still agree.
_CAPTURE_CAVITIES = {82, 86, 87}

# Fields whose value must reach an edge-capture unit, not merely a capable pin.
_CAPTURE_FIELDS = {"pinCrank", "pinCam1", "pinCam2"}

# A CAPABILITY IS NOT A DRIVE PATH EITHER (V95).
#
# Until V95 hc_validate() accepted any output route to a capable cavity, and
# the dropdowns offered the same: pinTacho on 18/22 (the CJ120 chip selects),
# pinBoost on 37 or 81 (CAPCOM pins this build never drives as PWM), the cam
# solenoids anywhere - all VALIDATED and drove nothing. Now hc_validate()
# asks hchal_me711.c:hc_hal_out_bindable(), and these are the cavities it
# answers 1 for, per field. me711_output_binding_proof executes that function
# in the linked image for every cavity and fails if the two disagree.
#   pinFuelPump   65 (P2.12) - the one relay-class stage out_port_of() drives
#   pinMainRelay  23 (the CJ910's own MR stage, a hardware function) or 65
#   pinBoost      104 - the ASIC LDR stage through the frame image
#   pinTacho      37 (P2.13 / CC13 compare mode 1, hcroutes711.c, 2026-10-11)
_OUT_BIND_CAVITIES = {
    "pinFuelPump": {65},
    "pinMainRelay": {23, 65},
    "pinBoost": {104},
    "pinTacho": {37},
    "pinCam1Sol": {115, 120},  # V97: POUT0 / POUT1 (hcvvt711.c)
    "pinCam2Sol": {115, 120},
    "pinMil": {47},            # V97: the ASIC P7.0 lamp stage
}

# A CAPABILITY IS NOT A READ PATH (V98). A switch field offers the cavities
# hchal_me711.c:hc_hal_din() reads - hw_descriptors.SWITCH_INPUT_CAVITIES, the
# one list - and hc_validate() refuses any other (me711_switch_input_proof).
_DIN_FIELDS = {"pinLaunch", "pinFlatShift", "pinAntiLag", "pinPitLimiter"}

_PIN_DESC_CACHE = {}


def _pin_desc():
    """The descriptor for the board this .ini is generated for."""
    if "d" not in _PIN_DESC_CACHE:
        _PIN_DESC_CACHE["d"] = HW.build_me711()
    return _PIN_DESC_CACHE["d"]


def _pin_ok(p, need, mode) -> bool:
    caps = p.capabilities
    routable = bool(p.hal_resource) and p.hal_resource != "NOT_ON_MAIN_CPU"
    if not routable:
        return False
    if not need:
        return (caps & ~PinCap.SPECIAL_LOCKED) != 0
    if mode == "any":
        return (caps & need) != 0
    return (caps & need) == need


def _pin_label_name(p) -> str:
    """What to call a cavity in a dropdown: its FUNCTION in words.

    V97 (2026-09-30): hw_descriptors.FRIENDLY_CAVITY_NAMES, "93 - Coolant
    temperature" rather than "93 TMOT". A cavity the selector would offer
    with no friendly name stops the generator - it never falls back to a
    Bosch mnemonic. The Bosch name stays in the descriptor.

    (V96 and before, the rule below - still what the descriptor says:)
    `meaning` FIRST, because oem_name is the ME7.1 C4 family workbook's label
    and it is WRONG for the 18..24 block: it calls cavity 19 `TAUS_S` when the
    ME7.1.1 sheet says `A_T_EV8`, and offering an injector output under the
    name of a temperature input is the sort of friendly-wrong label the project rules
    section 10 says is worse than a raw integer."""
    name = HW.FRIENDLY_CAVITY_NAMES.get(p.number)
    if name:
        return name
    raise SystemExit("cavity %d is offered in a pin dropdown but has no "
                     "entry in hw_descriptors.FRIENDLY_CAVITY_NAMES"
                     % p.number)
    m = (p.meaning or "").strip()
    if m and not m.startswith("LOCKED"):
        # The meanings come in two shapes: the sheet layer writes
        # "EV8 - Einspritzventil 8" and the family derivation writes
        # "LS2VK_H = LSF vor Kat. 2 | ...". Take the head of either, so the
        # dropdown reads "96 EV1" and not "96 EV1 = Einspritzventil".
        head = m.split(" - ")[0].split(" = ")[0].split("|")[0]
        return head.split(",")[0].strip()[:20]
    return (p.oem_name or "").split("|")[0].strip() or "cavity"


def _pin_labels(need: int, ts_name: str) -> str:
    """256 labels: the cavities that can do this job, and INVALID for the rest.

    255 is NONE and is always offered - an unrouted function is a legitimate
    configuration, and hc_validate() only objects when something else depends
    on it."""
    mode, n = "all", need
    if ts_name in _PIN_RULE_ANY:
        mode, n = "any", _PIN_RULE_ANY[ts_name]
    elif ts_name in _PIN_RULE_ALL:
        mode, n = "all", _PIN_RULE_ALL[ts_name]
    d = _pin_desc()
    out = []
    for v in range(256):
        if v == 255:
            out.append("NONE")
        elif (1 <= v <= HW.PIN_COUNT and _pin_ok(d.pin(v), n, mode)
              and (ts_name not in _CAPTURE_FIELDS or v in _CAPTURE_CAVITIES)
              and (ts_name not in _DIN_FIELDS
                   or v in HW.SWITCH_INPUT_CAVITIES)
              and (ts_name not in _OUT_BIND_CAVITIES
                   or v in _OUT_BIND_CAVITIES[ts_name])):
            if ts_name in _DIN_FIELDS:
                # V98: the switch-input table names the input, its wiring and
                # the polarity that wiring needs (hw_descriptors.SWITCH_INPUTS)
                _path, wiring, name, _ev = HW.SWITCH_INPUTS[v]
                pol = ("Active low" if ("ground" in wiring
                                        or "inverted" in wiring)
                       else "Active high")
                out.append("%d - %s (%s: %s)" % (v, name,
                                                 wiring.split(",")[0], pol))
            else:
                out.append("%d - %s" % (v, _pin_label_name(d.pin(v))))
        else:
            out.append("INVALID")
    return ", ".join('"%s"' % s for s in out)


def _enum_labels(en) -> str:
    top = (1 << (_bits_for(en) + 1))
    by_val = {v: lbl for v, _i, lbl in en.options}
    return ", ".join('"%s"' % by_val.get(i, "INVALID") for i in range(top))


# ==========================================================================
# main
# ==========================================================================
def main() -> int:
    check_only = "--check" in sys.argv
    fields, consts, problems = MODEL.resolve()
    uni_base = _raw_define("CFG_UNIVERSAL_BASE")
    uni_size = _raw_define("CFG_UNIVERSAL_SIZE")

    problems += coverage(fields, consts["HC_CFG_SIZE"], uni_base, uni_size)

    # The generated offsets must equal hcconfig.h's, for every legacy field.
    slots, _ = hcconfig_layout.parse()
    hdr = {s.name: s.offset for s in slots}
    for f in fields:
        if is_universal(f.slot):
            if not (uni_base <= f.offset and f.end <= uni_base + uni_size):
                problems.append("universal field %s at %d is outside the "
                                "reservation %d..%d"
                                % (f.slot, f.offset, uni_base,
                                   uni_base + uni_size - 1))
            continue
        if hdr.get(f.slot) != f.offset:
            problems.append("offset drift: %s is %s in hcconfig.h and %d in the "
                            "model" % (f.slot, hdr.get(f.slot), f.offset))

    # The emitted TunerStudio lines must carry the model's offsets.
    try:
        ini_lines = universal_ini_lines()
    except SystemExit as exc:
        problems.append(str(exc))
        ini_lines = []
    import re
    ini_off = {}
    for line in ini_lines:
        m = re.match(r"\s+(\w+)\s*=\s*(?:scalar|array|bits),\s*\w+,\s*(\d+)", line)
        if m:
            ini_off[m.group(1)] = int(m.group(2))
    for f in fields:
        if not is_universal(f.slot):
            continue
        if ini_off.get(f.meta.ts) != f.offset:
            problems.append("the .ini line for %s says %s, the model says %d"
                            % (f.meta.ts, ini_off.get(f.meta.ts), f.offset))

    if problems:
        print("GENERATION REFUSED - %d problem(s):" % len(problems))
        for p in problems:
            print("   " + p)
        return 1

    print("model resolves: %d fields, page %d, universal block %d/%d bytes used"
          % (len(fields), consts["HC_CFG_SIZE"],
             MODEL.universal_size(uni_base), uni_size))
    print("  every hcconfig.h slot has metadata and every metadata entry has a slot")
    print("  no overlaps, no misalignment, no duplicate TunerStudio names")
    print("  all %d bytes of the page are owned by a field or a declared reserve"
          % consts["HC_CFG_SIZE"])
    print("  generated C offsets == hcconfig.h offsets")
    print("  generated .ini offsets == model offsets")

    if check_only:
        return 0

    OUT_H.write_text(gen_header(fields, consts, uni_base, uni_size),
                     encoding="ascii", newline="\n")
    print("wrote %s" % OUT_H)
    OUT_C.write_text(gen_source(fields), encoding="ascii", newline="\n")
    print("wrote %s" % OUT_C)
    (GEN / "hc_pin_descriptor.h").write_text(PIN_DESC_H, encoding="ascii",
                                                newline="\n")
    (GEN / "hc_pin_descriptor.c").write_text(PIN_DESC_C_BODY, encoding="ascii",
                                                newline="\n")
    print("wrote %s / .c" % (GEN / "hc_pin_descriptor.h"))
    (GEN / "hc_presets.h").write_text(PRESET_H, encoding="ascii",
                                         newline="\n")
    (GEN / "hc_presets.c").write_text(gen_presets(fields),
                                         encoding="ascii", newline="\n")
    print("wrote %s / .c" % (GEN / "hc_presets.h"))
    for key, build in HW.DESCRIPTORS.items():
        d = build()
        path = GEN / ("hc_pin_desc_%s.c" % key.lower())
        path.write_text(gen_pin_desc(d), encoding="ascii", newline="\n")
        print("wrote %s" % path)
        HW.write_csv(d)

    GEN_DOCS.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        wr = csv.writer(fh)
        wr.writerow(["slot", "offset", "type", "count", "bytes", "ts_name",
                     "apply", "group", "safety_critical", "is_pin", "units",
                     "scale", "translate", "min", "max", "category", "note"])
        for f in fields:
            m = f.meta
            wr.writerow([f.slot, f.offset, f.ctype, f.count, f.size, m.ts,
                         m.apply.value, m.group.name, int(m.safety_critical),
                         int(m.is_pin), m.units, m.scale, m.translate, m.lo,
                         m.hi, m.category, m.note.replace("\n", " ")])
    print("wrote %s" % OUT_CSV)
    return 0


if __name__ == "__main__":
    sys.exit(main())
