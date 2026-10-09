#!/usr/bin/env python3
r"""
me711_migrate_calibration.py - carry a calibration across a PAGE LAYOUT
change, field by field, by name. ACTIVE only with --i-authorize-bench-power.

    py tools\calibration\me711_migrate_calibration.py --selftest
    py tools\calibration\me711_migrate_calibration.py --dump <bootmode readback.bin>
        --src-ini <the .ini of the firmware that WROTE the record>
        --dst-ini <the .ini of the firmware now in the ECU>
        --out <evidence dir> [--dry-run] [--set NAME=VALUE[,VALUE...] ...]
        --i-authorize-bench-power

WHY. me711_restore_calibration.py refuses a record from another layout, on
purpose: a byte copy would put values in the wrong fields. A new page field
(V97 onwards) changes HC_CFG_LAYOUT_ID, so the car calibration needs this.

THE RULES (migrate(), pure, --selftest):
  * the SOURCE page is the newest valid store record in the dump whose layout
    id is the one the source .ini's signature names;
  * the BASE is the page the ECU holds now (after a full flash: its board
    default), read over the link - every field the source cannot supply
    keeps that value;
  * a constant present in both .ini files with the same kind and shape:
      identical encoding (type, scale, translate) -> the raw bytes;
      scale/translate changed -> the PHYSICAL value, re-encoded, clamped to
        the new limits (reported when clamped);
      bits: the value moved to the new bit position; if the labels changed,
        mapped BY LABEL TEXT, else refused (base kept, reported);
  * kind or shape changed, or only in one file: base kept / dropped, reported;
  * V97 TABLE ORDER: every 2-D array is TRANSPOSED when the two .ini files
    declare different `; tableOrder =` (a file without the line is V96..V97's
    "rpm-major", [rpm][load]; the current one is "load-major", [load][rpm])
    - the same runtime lookup, cell for cell;
  * V97 PIN LABELS: a cavity selector whose label text changed ("93 TMOT" ->
    "93 - Coolant temperature") keeps its value when both labels name the
    same cavity number - the value IS the cavity;
  * V98 SEMANTICS (a source page without `firingOrder`, v98_semantics()):
      - crankPwVal: the batch pulse in us -> FUEL MASS per cylinder per
        cycle in 0.1 mg (2 pulses x open time x the source's injector flow,
        hc_af_flow_x100's 745/600 density) - the same fuel the car cranked on;
      - afrMap: AFR x 10 -> lambda x 147 by the source's stoichiometric ratio
        (the same bytes at 14.7);
      - lambdaRpmAx/lambdaLoadAx: the source's ignition axes (the lambda
        table was looked up on them until V98);
      - loadSource keeps its NUMBER (0 speed density, 1 alpha-N x inlet
        pressure = the V97 alpha-N); a speed-density page keeps the ignition
        and lambda tables on cylinder filling (V97's rl);
      - firingOrder: the named order whose TDC angles equal the page's, else
        CUSTOM (the angles stay);
      - newly LIVE features start where V97 behaved: revlimMode = fuel cut,
        motorsportEnable = 0, ETB rev limit off;
  * never migrated: cfgVersion, uMagic, uSchema - the page's own FORMAT
    identity, which the new firmware wrote and its validation checks
    (HC_VAL_FAULT_SCHEMA). V97's first live run copied V96's uSchema
    (0x925A over 0x03DD) and the firmware refused the page, correctly.
Then the live path is me711_restore_calibration.apply_page(): diffs written
with 'W', a full read-back compare, the firmware's own validation must pass,
Burn, power cycle, read-back again. Nothing is burned if anything differs.
"""
from __future__ import annotations

import argparse
import hashlib
import math
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

PAGE = 4096
NEVER = {"cfgVersion", "uMagic", "uSchema"}


def _trig_angle_from_offset(raw: int) -> int:
    """V96 trigOffsetX10 (u16, 0.1 deg, the decoder's rotation) -> V97
    trigAngleX10 (s16, tooth #1 in 0.1 deg ATDC, -179.9..180.0). The SAME
    crank position: the firmware takes both modulo 360 (hc_trig_rotation_x10),
    so 3580 -> -20, 2680 -> -920."""
    v = raw % 3600
    return v - 3600 if v > 1800 else v


# a field that was RENAMED with a new encoding: new name -> (old name, the
# conversion of the old RAW value into the new RAW value)
RENAMED = {"trigAngleX10": ("trigOffsetX10", _trig_angle_from_offset)}
# V98: a label RENAMED with the same meaning (old -> new)
LABEL_EQUIV = {"Grounded": "Active low (closed to ground = on)",
               "High": "Active high (open = on)"}
TYPES = {"U08": (1, False), "S08": (1, True), "U16": (2, False),
         "S16": (2, True), "U32": (4, False), "S32": (4, True)}


class Const:
    def __init__(self, name, kind, typ, off, shape, scale, translate, lo, hi,
                 bits, labels):
        self.name, self.kind, self.typ, self.off = name, kind, typ, off
        self.shape, self.scale, self.translate = shape, scale, translate
        self.lo, self.hi, self.bits, self.labels = lo, hi, bits, labels

    @property
    def width(self):
        return TYPES[self.typ][0]

    @property
    def count(self):
        n = 1
        for d in self.shape:
            n *= d
        return n

    def encoding(self):
        return (self.typ, self.scale, self.translate)


def _num(t):
    t = t.strip()
    try:
        return float(t) if any(c in t for c in ".eE") else int(t, 0)
    except ValueError:
        return None


def strip_comment(raw: str) -> str:
    """The line up to its first ';' OUTSIDE a quoted string. V97: the
    strategy labels carry a ';' ("...once the cycle is known; two halves
    ..."), TunerStudio reads them whole (rusEFI's own .ini has quoted ';'),
    and a split at the first ';' dropped injStrategy / ignStrategy from the
    parse - the car page's wasted COP would have migrated to the board
    default."""
    q = False
    for i, ch in enumerate(raw):
        if ch == '"':
            q = not q
        elif ch == ";" and not q:
            return raw[:i]
    return raw


def parse_ini(text: str) -> dict:
    """[Constants] page 1 -> {name: Const}. Only what the page layout needs."""
    out, on = {}, False
    for raw in text.splitlines():
        line = strip_comment(raw).rstrip()
        s = line.strip()
        if s.startswith("["):
            on = s == "[Constants]"
            continue
        if not on or "=" not in s:
            continue
        name, _, rhs = s.partition("=")
        name = name.strip()
        parts = [p.strip() for p in re.split(r",(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", rhs)]
        if not parts or parts[0] not in ("scalar", "bits", "array"):
            continue
        kind, typ, off = parts[0], parts[1], int(parts[2])
        if kind == "bits":
            m = re.match(r"\[(\d+):(\d+)\]", parts[3])
            labels = [p.strip().strip('"') for p in parts[4:]]
            out[name] = Const(name, kind, typ, off, (), 1, 0, None, None,
                              (int(m.group(1)), int(m.group(2))), labels)
            continue
        if kind == "array":
            dims = tuple(int(x) for x in parts[3].strip("[]").split("x"))
            rest = parts[4:]
        else:
            dims = ()
            rest = parts[3:]
        scale = _num(rest[1]) if len(rest) > 1 else 1
        translate = _num(rest[2]) if len(rest) > 2 else 0
        lo = _num(rest[3]) if len(rest) > 3 else None
        hi = _num(rest[4]) if len(rest) > 4 else None
        out[name] = Const(name, kind, typ, off, dims, scale if scale is not None else 1,
                          translate if translate is not None else 0, lo, hi, None, None)
    return out


def table_order(text: str) -> str:
    """The page's 2-D table storage order, as the generator declares it.
    No declaration = the order every file before V97's fix had."""
    m = re.search(r"^;\s*tableOrder\s*=\s*([\w-]+)", text, re.M)
    return m.group(1) if m else "rpm-major"


def _cavity(label):
    m = re.match(r"(\d+)\b", label or "")
    return int(m.group(1)) if m else None


def signature_layout(text: str) -> int | None:
    m = re.search(r'signature\s*=\s*"[^"]*?([0-9A-F]{8})"', text)
    return int(m.group(1), 16) if m else None


def _get(page, off, w, signed):
    v = int.from_bytes(page[off:off + w], "big")
    if signed and v >= 1 << (8 * w - 1):
        v -= 1 << (8 * w)
    return v


def _put(page, off, w, v):
    v &= (1 << (8 * w)) - 1
    page[off:off + w] = v.to_bytes(w, "big")


def migrate(src_page: bytes, src: dict, base_page: bytes, dst: dict,
            src_order: str = "load-major", dst_order: str = "load-major"):
    """(page, report) - see the module docstring for the rules."""
    page = bytearray(base_page)
    rep = {"copied": [], "converted": [], "clamped": [], "bits_moved": [],
           "by_label": [], "by_cavity": [], "transposed": [],
           "new_default": [], "dropped": [], "refused": [], "never": []}
    transpose = src_order != dst_order
    for name, d in sorted(dst.items(), key=lambda kv: kv[1].off):
        if name in NEVER:
            rep["never"].append(name)
            continue
        s = src.get(name)
        if s is None and name in RENAMED and RENAMED[name][0] in src:
            old, conv = RENAMED[name]
            so = src[old]
            raw = _get(src_page, so.off, so.width, TYPES[so.typ][1])
            _put(page, d.off, d.width, conv(raw))
            rep["converted"].append("%s <- %s" % (name, old))
            continue
        if s is None:
            rep["new_default"].append(name)
            continue
        if s.kind != d.kind or s.shape != d.shape:
            rep["refused"].append("%s: %s%s -> %s%s" % (name, s.kind, s.shape,
                                                        d.kind, d.shape))
            continue
        if d.kind == "bits":
            lo_s, hi_s = s.bits
            lo_d, hi_d = d.bits
            ws, wd = s.width, d.width
            v = (_get(src_page, s.off, ws, False) >> lo_s) & ((1 << (hi_s - lo_s + 1)) - 1)
            if s.labels != d.labels:
                lab = s.labels[v] if v < len(s.labels) else None
                if (lab is not None and v < len(d.labels)
                        and _cavity(lab) is not None
                        and _cavity(lab) == _cavity(d.labels[v])):
                    rep["by_cavity"].append(name)   # the value IS the cavity
                elif (lab in LABEL_EQUIV and v < len(d.labels)
                      and d.labels[v] == LABEL_EQUIV[lab]):
                    rep["by_label"].append(name)    # renamed, same meaning
                elif lab is None or lab not in d.labels or lab == "INVALID":
                    rep["refused"].append("%s: value %s (%r) has no label in the new "
                                          "list" % (name, v, lab))
                    continue
                else:
                    v = d.labels.index(lab)
                    rep["by_label"].append(name)
            if v >= 1 << (hi_d - lo_d + 1):
                rep["refused"].append("%s: value %d does not fit [%d:%d]"
                                      % (name, v, lo_d, hi_d))
                continue
            mask = ((1 << (hi_d - lo_d + 1)) - 1) << lo_d
            cur = _get(page, d.off, wd, False)
            _put(page, d.off, wd, (cur & ~mask) | (v << lo_d))
            if (lo_s, hi_s, s.off, s.typ) != (lo_d, hi_d, d.off, d.typ):
                rep["bits_moved"].append(name)
            else:
                rep["copied"].append(name)
            continue
        ws, sgs = TYPES[s.typ]
        wd, sgd = TYPES[d.typ]
        # element i of the destination comes from element order[i] of the
        # source: identity, or the transpose of a 2-D table
        order = list(range(d.count))
        if transpose and d.kind == "array" and len(d.shape) == 2:
            nx, ny = d.shape            # TunerStudio [x x y]: index y*nx + x
            order = [x * ny + y for y in range(ny) for x in range(nx)]
            rep["transposed"].append(name)
        if s.encoding() == d.encoding():
            for i, j in enumerate(order):
                page[d.off + i * wd:d.off + (i + 1) * wd] = \
                    src_page[s.off + j * ws:s.off + (j + 1) * ws]
            rep["copied"].append(name)
            continue
        clamped = False
        for i in range(d.count):
            raw = _get(src_page, s.off + order[i] * ws, ws, sgs)
            phys = (raw + s.translate) * s.scale
            if d.lo is not None and phys < d.lo:
                phys, clamped = d.lo, True
            if d.hi is not None and phys > d.hi:
                phys, clamped = d.hi, True
            # half UP, not Python's half-to-even: a V97 VE of 0.5 % (one
            # 0.5 % count) must stay fuel (1 %), never become 0 %
            new = int(math.floor(phys / d.scale - d.translate + 0.5))
            _put(page, d.off + i * wd, wd, new)
        rep["converted"].append(name)
        if clamped:
            rep["clamped"].append(name)
    rep["dropped"] = sorted(set(src) - set(dst)
                            - {old for old, _c in RENAMED.values()})
    if "firingOrder" in dst and "firingOrder" not in src:
        v98_semantics(src_page, src, page, dst, rep)
    return bytes(page), rep


# ------------------------------------------------------ V98 semantics --
def firing_orders() -> dict:
    """{rusEFI id: (cylinder numbers in firing order)} - parsed from the
    firmware's own table (hcengctl711.c fo_tab), so the two cannot differ."""
    c = (ROOT / "firmware/targets/me711/engine/hcengctl711.c"
         ).read_text(errors="replace")
    body = re.search(r"fo_tab\[\]\s*=\s*\{(.*?)\};", c, re.S).group(1)
    nums = [int(x, 0) for x in re.findall(r"0x[0-9A-Fa-f]+|\d+", re.sub(
        r"/\*.*?\*/", "", body, flags=re.S))]
    out, i = {}, 0
    while i < len(nums) and nums[i] != 0xFF:
        n = nums[i + 1]
        out[nums[i]] = tuple(nums[i + 2:i + 2 + n])
        i += 2 + n
    return out


def firing_order_id(tdc_x10: list, ncyl: int) -> int:
    """The rusEFI id whose even-fire TDCs (cycle x position / n, 0.1 deg,
    firmware geometry_refresh) equal the page's angles relative to
    cylinder 1; 0 (CUSTOM) when none does."""
    rel = [(t - tdc_x10[0]) % 7200 for t in tdc_x10[:ncyl]]
    for fid, order in sorted(firing_orders().items()):
        if len(order) != ncyl:
            continue
        want = [7200 * order.index(c + 1) // ncyl for c in range(ncyl)]
        if want == rel:
            return fid
    return 0


def v98_semantics(src_page, src, page, dst, rep):
    def sget(name, i=0):
        s = src[name]
        return _get(src_page, s.off + i * s.width, s.width, TYPES[s.typ][1])

    def dput(name, v, i=0):
        d = dst[name]
        _put(page, d.off + i * d.width, d.width, v)

    def drop(name):
        for k in ("copied", "converted", "clamped", "new_default", "refused",
                  "by_label", "transposed"):
            rep[k] = [x for x in rep[k] if x != name
                      and not x.startswith(name + ":")]

    notes = rep.setdefault("v98", [])
    # cranking fuel: us per batch pulse -> 0.1 mg per cylinder per cycle
    if "crankPwVal" in src and "injFlowCcMin" in src:
        flow = sget("injFlowCcMin")
        mg = []
        for i in range(dst["crankPwVal"].count):
            us = sget("crankPwVal", i)
            v = int(round(2 * us * flow * 745 / 600 / 100 / 1000 * 10))
            v = max(0, min(v, 20000))
            dput("crankPwVal", v, i)
            mg.append(v / 10)
        drop("crankPwVal")
        notes.append("crankPwVal: us -> mg per cycle at %d cc/min: %s"
                     % (flow, mg))
    # target table: AFR x 10 -> lambda x 147
    if "afrMap" in src:
        st = sget("stoichAfrX100") if "stoichAfrX100" in src else 1470
        st = st or 1470
        for i in range(dst["afrMap"].count):
            j = i
            s, d = src["afrMap"], dst["afrMap"]
            if i == 0 and s.shape != d.shape:
                break
            raw = sget("afrMap", j)
            dput("afrMap", max(59, min(220, int(round(raw * 1470 / st)))), i)
        drop("afrMap")
        notes.append("afrMap: AFR x10 -> lambda x147 at stoich %.2f" % (st / 100))
    # the lambda table's own axes = the ignition axes it used
    for new, old in (("lambdaRpmAx", "ignRpmAx"), ("lambdaLoadAx", "ignLoadAx")):
        if new in dst and old in src:
            for i in range(min(dst[new].count, src[old].count)):
                dput(new, sget(old, i), i)
            drop(new)
            notes.append("%s <- %s" % (new, old))
    # the load strategy keeps its number
    if "loadSource" in src:
        ls = sget("loadSource") & 0xFF
        d = dst["loadSource"]
        lo, hi = d.bits
        cur = _get(page, d.off, d.width, False)
        mask = ((1 << (hi - lo + 1)) - 1) << lo
        _put(page, d.off, d.width, (cur & ~mask) | ((ls & 0x3) << lo))
        drop("loadSource")
        notes.append("loadSource kept: %d (%s)" % (ls, d.labels[ls]))
        if ls == 0:
            for name in ("ignLoadMode", "lambdaLoadMode"):
                if name in dst:
                    dput(name, 3)
                    notes.append("%s = 3 (cylinder filling, the V97 rl)" % name)
    # firing order
    if "tdcCylDegX10" in src and "cylinders" in src:
        n = sget("cylinders") & 0xFF
        tdc = [sget("tdcCylDegX10", i) for i in range(min(n, 8))]
        fid = firing_order_id(tdc, n) if 0 < n <= 8 else 0
        dput("firingOrder", fid)
        drop("firingOrder")
        notes.append("firingOrder = %d (%s) from TDC %s" % (
            fid, dst["firingOrder"].labels[fid]
            if fid < len(dst["firingOrder"].labels) else "?", tdc))
    # features that start reading their fields in V98: V97 behaviour
    for name, v, why in (("revlimMode", 1, "fuel cut, as V93..V97"),
                         ("motorsportEnable", 0, "new runtime starts OFF"),
                         ("dbwRevlimRpm", 0, "ETB rev limit off, as V97")):
        if name in dst:
            dput(name, v)
            drop(name)
            notes.append("%s = %d (%s)" % (name, v, why))


# ------------------------------------------------------------- self-test --
def selftest() -> int:
    ini = (ROOT / "tunerstudio/hanicore_me711.ini").read_text(
        encoding="utf-8", errors="replace")
    src = parse_ini(ini)
    import random
    rnd = random.Random(7)
    src_page = bytes(rnd.randrange(256) for _ in range(PAGE))
    base = bytes(PAGE)
    bad = 0

    def check(name, ok):
        nonlocal bad
        print("  %s %s" % ("OK  " if ok else "FAIL", name))
        bad += not ok

    check("the .ini parses into constants (%d)" % len(src), len(src) > 150)
    # 1. identity: the same layout reproduces every byte that is a field
    page, rep = migrate(src_page, src, base, src)
    fields = set()
    for c in src.values():
        if c.name in NEVER:
            continue
        if c.kind == "bits":
            fields |= {c.off + i for i in range(c.width)}
        else:
            fields |= {c.off + i for i in range(c.count * c.width)}
    diff = [i for i in fields if page[i] != src_page[i]
            and not any(c.kind == "bits" and c.off <= i < c.off + c.width
                        for c in src.values())]
    check("same layout: every scalar/array byte carried over", not diff)
    bitsok = all(((_get(page, c.off, c.width, False) >> c.bits[0])
                  & ((1 << (c.bits[1] - c.bits[0] + 1)) - 1))
                 == ((_get(src_page, c.off, c.width, False) >> c.bits[0])
                     & ((1 << (c.bits[1] - c.bits[0] + 1)) - 1))
                 for c in src.values() if c.kind == "bits")
    check("same layout: every bit field carried over", bitsok)
    # 2. a synthetic new layout: a field moved, one rescaled, one new, one
    #    dropped, a bit field moved, an enum relabelled
    dst = {k: Const(**vars(v)) for k, v in src.items()}
    name_scalar = next(k for k, c in dst.items() if c.kind == "scalar"
                       and c.typ == "U16" and c.scale == 1 and c.translate == 0
                       and c.hi and c.hi >= 1000)
    moved = dst[name_scalar]
    moved.off = 3720          # inside the universal block's free tail
    name_rescale = next(k for k, c in dst.items() if c.kind == "scalar"
                        and c.typ == "U16" and c.scale == 0.1 and c.translate == 0
                        and k != name_scalar)
    dst[name_rescale].scale = 0.01
    dst[name_rescale].hi = 1e9
    dst["brandNewField"] = Const("brandNewField", "scalar", "U08", 3730, (), 1,
                                 0, 0, 255, None, None)
    gone = next(k for k, c in dst.items() if c.kind == "array")
    del dst[gone]
    bits_name = next(k for k, c in dst.items() if c.kind == "bits"
                     and c.bits == (0, 0) and len(c.labels) == 2)
    dst[bits_name].off, dst[bits_name].bits = 3740, (3, 3)
    enum_name = next(k for k, c in dst.items() if c.kind == "bits"
                     and c.bits[1] - c.bits[0] >= 1 and len(set(c.labels)) >= 3
                     and "INVALID" not in c.labels[:3] and k != bits_name)
    dst[enum_name].labels = list(reversed(dst[enum_name].labels))
    base2 = bytearray(PAGE)
    base2[3730] = 0x5A
    page, rep = migrate(src_page, src, bytes(base2), dst)
    check("a moved U16 lands at its new offset (%s)" % name_scalar,
          page[3720:3722] == src_page[src[name_scalar].off:src[name_scalar].off + 2])
    sv = _get(src_page, src[name_rescale].off, 2, False)
    check("a rescaled field keeps its PHYSICAL value (%s x10)" % name_rescale,
          _get(page, dst[name_rescale].off, 2, False) == (sv * 10) & 0xFFFF
          or name_rescale in rep["clamped"])
    check("a new field keeps the board default", page[3730] == 0x5A
          and "brandNewField" in rep["new_default"])
    check("a removed field is reported dropped (%s)" % gone, gone in rep["dropped"])
    # V97: a ';' inside a quoted label is text, not a comment
    q = parse_ini('[Constants]\n   enumSemi = bits, U08, 10, [0:1], "A", '
                  '"B; still B", "C", "D" ; a real comment\n')
    check("a ';' inside a quoted label does not cut the line",
          "enumSemi" in q and q["enumSemi"].labels == ["A", "B; still B", "C", "D"])
    vb = (src_page[src[bits_name].off] >> 0) & 1
    check("a bit field moves to its new byte and bit (%s)" % bits_name,
          ((page[3740] >> 3) & 1) == vb and bits_name in rep["bits_moved"])
    sc = src[enum_name]
    v = (_get(src_page, sc.off, sc.width, False) >> sc.bits[0]) & (
        (1 << (sc.bits[1] - sc.bits[0] + 1)) - 1)
    dc = dst[enum_name]
    got = (_get(page, dc.off, dc.width, False) >> dc.bits[0]) & (
        (1 << (dc.bits[1] - dc.bits[0] + 1)) - 1)
    lab_ok = (v < len(sc.labels) and sc.labels[v] != "INVALID"
              and dc.labels[got] == sc.labels[v]) or enum_name in " ".join(rep["refused"])
    check("a relabelled enum maps by label text (%s)" % enum_name, lab_ok)
    check("cfgVersion is never migrated", "cfgVersion" in rep["never"])
    # V97: the renamed trigger reference - the same crank position
    for old_raw, want in ((3580, -20), (2680, -920), (0, 0), (900, 900),
                          (1800, 1800), (1801, -1799), (7199, -1)):
        check("trigOffsetX10 %d -> trigAngleX10 %d" % (old_raw, want),
              _trig_angle_from_offset(old_raw) == want)
    if "trigAngleX10" in dst:
        d = dst["trigAngleX10"]
        old = Const("trigOffsetX10", "scalar", "U16", d.off, (), 0.1, 0.0,
                    0, 719.9, None, None)
        src2 = {k: v for k, v in dst.items() if k != "trigAngleX10"}
        src2["trigOffsetX10"] = old
        sp = bytearray(PAGE)
        sp[d.off:d.off + 2] = (3580).to_bytes(2, "big")
        pg, rp = migrate(bytes(sp), src2, bytes(PAGE), dst)
        got = int.from_bytes(pg[d.off:d.off + 2], "big", signed=True)
        check("a V96 page's trigOffsetX10 3580 arrives as trigAngleX10 -20",
              got == -20 and "trigOffsetX10" not in rp["dropped"])
    for n in ("uMagic", "uSchema"):
        if n in src and n in dst:
            check("%s (format identity) is never migrated" % n, n in rep["never"])
    # V97: THE TABLE ORDER. A source page in [rpm][load] arrives [load][rpm]:
    # cell (rpm r, load l) keeps its value; a same-order migration does not
    # transpose; a non-square 2-D array transposes by its own dimensions.
    ve = src["veTable"]
    w = ve.width
    sp = bytearray(PAGE)
    for i in range(256):
        _put(sp, ve.off + w * i, w, i)

    def cell(pg, i):
        return _get(pg, ve.off + w * i, w, False)
    pg, rp = migrate(bytes(sp), src, bytes(PAGE), src, "rpm-major", "load-major")
    check("rpm-major -> load-major: veTable (rpm 3, load 11) moves [3][11] "
          "-> [11][3]",
          cell(pg, 11 * 16 + 3) == 3 * 16 + 11 and "veTable" in rp["transposed"])
    check("...every cell, and the 8x8 VVT targets are transposed too",
          all(cell(pg, ld * 16 + r) == r * 16 + ld for r in range(16)
              for ld in range(16))
          and ("vvtTarget1" not in src or "vvtTarget1" in rp["transposed"]))
    pg, rp = migrate(bytes(sp), src, bytes(PAGE), src)
    check("same order: nothing transposed", not rp["transposed"]
          and [cell(pg, i) for i in range(256)] == list(range(256)))
    tt = {"t": Const("t", "array", "U08", 100, (4, 2), 1, 0, 0, 255, None, None)}
    sp = bytearray(PAGE)
    sp[100:108] = bytes(range(8))       # source [4x2] in the other order
    pg, _r = migrate(bytes(sp), tt, bytes(PAGE), tt, "rpm-major", "load-major")
    check("a [4x2] array transposes by its own dimensions",
          list(pg[100:108]) == [0, 2, 4, 6, 1, 3, 5, 7])
    # V97: pin labels renamed, same cavity -> same value
    pins = [k for k, c in src.items() if k.startswith("pin") and c.kind == "bits"
            and any(_cavity(lb) for lb in c.labels)]
    check("the .ini has cavity pin selectors (%d)" % len(pins), len(pins) > 5)
    for pn in pins[:3]:
        c = src[pn]
        v = next(i for i, lb in enumerate(c.labels) if _cavity(lb))
        d2 = {k: Const(**vars(x)) for k, x in src.items()}
        d2[pn].labels = [("%d - Friendly name" % _cavity(lb)) if _cavity(lb)
                         else lb for lb in c.labels]
        sp = bytearray(PAGE)
        _put(sp, c.off, c.width, v << c.bits[0])
        pg, rp = migrate(bytes(sp), src, bytes(PAGE), d2)
        got = (_get(pg, c.off, c.width, False) >> c.bits[0]) & (
            (1 << (c.bits[1] - c.bits[0] + 1)) - 1)
        check("a renamed pin label keeps the cavity (%s = %d)" % (pn, v),
              got == v and pn in rp["by_cavity"])
    check("table_order() reads the declaration, else rpm-major",
          table_order("; tableOrder = load-major\n") == "load-major"
          and table_order("[Constants]\n") == "rpm-major")

    # V98 SEMANTICS: a V97 page (layout 5819ED6C, the tracked V97 .ini) into
    # the current layout - the meanings that changed, not just the bytes
    v97_path = ROOT / "tunerstudio/history/hanicore_me711_v97_dev.ini"
    if v97_path.exists() and "firingOrder" in src:
        v97 = parse_ini(v97_path.read_text(encoding="utf-8", errors="replace"))
        sp = bytearray(PAGE)

        def put(name, vals):
            c = v97[name]
            for i, v in enumerate(vals if isinstance(vals, list) else [vals]):
                _put(sp, c.off + i * c.width, c.width, v)

        def setbits(name, v):
            c = v97[name]
            if c.kind != "bits":
                return put(name, v)
            lo, hi = c.bits
            m = ((1 << (hi - lo + 1)) - 1) << lo
            cur = _get(sp, c.off, c.width, False)
            _put(sp, c.off, c.width, (cur & ~m) | (v << lo))

        for name, c in v97.items():          # a real page: unrouted = NONE
            if ((name.startswith(("pin", "testPin")) or "Pin" in name)
                    and c.kind == "bits" and c.bits[1] - c.bits[0] == 7):
                setbits(name, 255)
        # the AWT's routing (V98r2: the injector / coil labels changed text,
        # "96 - Injector 1" -> "96 - Injector output 1"; the cavity carries)
        for name, cav in (("injPin1", 96), ("injPin2", 89), ("injPin3", 97),
                          ("injPin4", 88), ("ignPin1", 102), ("ignPin2", 95),
                          ("ignPin3", 103), ("ignPin4", 94)):
            if name in v97:
                setbits(name, cav)
        put("injFlowCcMin", 301)
        put("crankPwVal", [4000] * 8)
        put("afrMap", [147] * 255 + [121])
        put("stoichAfrX100", 1470)
        setbits("cylinders", 4)
        put("tdcCylDegX10", [0, 5400, 1800, 3600])
        setbits("loadSource", 1)
        setbits("revlimMode", 0)
        put("motorsportEnable", 0x000F)
        put("dbwRevlimRpm", 6000)
        put("ignRpmAx", [500 + 400 * i for i in range(16)])
        put("ignLoadAx", [60 * i for i in range(16)])
        put("veTable", [171, 1, 254])          # 85.5 %, 0.5 %, 127 % (0.5 %)
        page, rep = migrate(bytes(sp), v97, bytes(PAGE), src,
                            "load-major", "load-major")

        def get(name, i=0):
            c = src[name]
            if c.kind == "bits":
                lo, hi = c.bits
                return (_get(page, c.off, c.width, False) >> lo) \
                    & ((1 << (hi - lo + 1)) - 1)
            return _get(page, c.off + i * c.width, c.width,
                        TYPES[c.typ][1])

        mg = get("crankPwVal")     # 2 x 4000 us x 301 cc/min x 745/600
        check("V98: cranking 4000 us -> %.1f mg per cycle (= 29.9)" % (mg / 10),
              abs(mg - 299) <= 1)
        check("V98: afrMap bytes kept (lambda x 147 = AFR x 10 at 14.7)",
              get("afrMap") == 147 and get("afrMap", 255) == 121)
        check("V98: the lambda table gets the ignition axes it was read on",
              [get("lambdaRpmAx", i) for i in range(16)]
              == [500 + 400 * i for i in range(16)]
              and get("lambdaLoadAx", 15) == 900)
        check("V98: TDC 0/540/180/360 -> firing order 1 (1-3-4-2)",
              get("firingOrder") == 1)
        check("V98: load source keeps its NUMBER (1 = alpha-N x pressure)",
              get("loadSource") == 1)
        check("V98: newly live features start as V97 behaved (fuel-cut "
              "limiter, motorsport off, ETB rev limit off)",
              get("revlimMode") == 1 and get("motorsportEnable") == 0
              and get("dbwRevlimRpm") == 0)
        check("V98r2: VE 0.5 %% counts -> 0.1 %% u16, exact (85.5, 0.5, "
              "127.0 %%): %s" % [get("veTable", i) for i in range(3)],
              [get("veTable", i) for i in range(3)] == [855, 5, 1270])
        check("V98: nothing refused %s" % rep["refused"][:3], not rep["refused"])
        check("V98r2: injector / coil cavities carried across the relabel "
              "(%s)" % [get("injPin%d" % i) for i in range(1, 5)],
              [get("injPin%d" % i) for i in range(1, 5)] == [96, 89, 97, 88]
              and [get("ignPin%d" % i) for i in range(1, 5)]
              == [102, 95, 103, 94])

    # V98r2: a V98 page (layout C22837DF, VE one BYTE per 1 %) into the u16
    # 0.1 % layout. The two layouts carry different ids in the signature,
    # so neither firmware accepts the other's record; the migration reads
    # each byte with its OWN .ini's scale - 9 (9 %) becomes 90, never 9.
    v98_path = ROOT / "tunerstudio/history/hanicore_me711_v98_C22837DF.ini"
    if v98_path.exists() and src.get("veTable") is not None \
            and src["veTable"].typ == "U16":
        t98 = v98_path.read_text(encoding="utf-8", errors="replace")
        v98 = parse_ini(t98)
        sp = bytearray(PAGE)
        c = v98["veTable"]
        for i, v in enumerate([9, 1, 255, 85, 150]):
            _put(sp, c.off + i, 1, v)
        page, rep = migrate(bytes(sp), v98, bytes(PAGE), src)
        d = src["veTable"]
        got = [_get(page, d.off + 2 * i, 2, False) for i in range(5)]
        check("V98r2: V98 VE 1 %% bytes -> 0.1 %% u16 by physical value "
              "(9, 1, 255, 85, 150 %% -> %s)" % got,
              got == [90, 10, 2550, 850, 1500]
              and "veTable" in rep["converted"])
        check("V98r2: the C22837DF signature differs from this layout's",
              signature_layout(t98) == 0xC22837DF
              and signature_layout(t98) != signature_layout(
                  (ROOT / "tunerstudio/history/hanicore_me711_v98_dev.ini")
                  .read_text(errors="replace")))
    print("SELFTEST %s" % ("PASS" if not bad else "FAIL"))
    return 1 if bad else 0


# ------------------------------------------------------------------ live --
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dump")
    # V98r2: a 4096-byte page file (e.g. an evidence migrated_page.bin) as
    # the source instead of the dump's newest record - for when the newest
    # Burn is not the calibration to carry (2026-10-02: gen 4 held a VE
    # Table Generator table; 2DE693C8 is the AWT one)
    ap.add_argument("--src-page")
    ap.add_argument("--src-ini")
    ap.add_argument("--dst-ini")
    ap.add_argument("--out")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
    ap.add_argument("--i-authorize-bench-power", action="store_true", dest="auth")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not ((a.dump or a.src_page) and a.src_ini and a.dst_ini and a.out):
        ap.error("--dump or --src-page, --src-ini, --dst-ini and --out are "
                 "required")
    if not a.auth:
        raise SystemExit("REFUSING: --i-authorize-bench-power is required")
    import me711_store as R
    src_text = Path(a.src_ini).read_text(encoding="utf-8", errors="replace")
    dst_text = Path(a.dst_ini).read_text(encoding="utf-8", errors="replace")
    src, dst = parse_ini(src_text), parse_ini(dst_text)
    layout = signature_layout(src_text)
    if layout is None:
        raise SystemExit("the source .ini has no layout in its signature")
    if a.src_page:
        src_page = Path(a.src_page).read_bytes()
        if len(src_page) != PAGE:
            raise SystemExit("--src-page is %d bytes, not %d"
                             % (len(src_page), PAGE))
        cell, gen = -1, -1
        print("source: page file %s sha256 %s (layout %08X by the "
              "operator's word: a page file carries no header)"
              % (a.src_page, hashlib.sha256(src_page).hexdigest().upper(),
                 layout))
    else:
        dump = Path(a.dump).read_bytes()
        version = R.hdr(R.CFG_H, "HC_CFG_VERSION", 10)
        best, seen = R.newest_record(dump, layout, version)
        if best is None:
            raise SystemExit("no record of layout %08X in the dump: %s"
                             % (layout, seen))
        cell, gen, src_page = best
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    src_order, dst_order = table_order(src_text), table_order(dst_text)
    print("table order: %s -> %s%s" % (src_order, dst_order,
          " (2-D tables TRANSPOSED)" if src_order != dst_order else ""))

    def plan(base: bytes) -> bytes:
        page, rep = migrate(src_page, src, base, dst, src_order, dst_order)
        page = bytearray(page)
        for spec in a.set:
            name, _, val = spec.partition("=")
            c = dst[name]
            w = c.width
            # V98: NAME=v1,v2,... writes array elements in order (raw)
            for i, v in enumerate(val.split(",")):
                if i >= c.count:
                    raise SystemExit("--set %s: more than %d values"
                                     % (name, c.count))
                _put(page, c.off + i * w, w, int(v, 0))
            rep.setdefault("overrides", []).append(spec)
        (out / "migration_report.json").write_text(json.dumps(
            {"source_layout": "%08X" % layout, "source_cell": cell,
             "source_gen": gen,
             "source_sha256": hashlib.sha256(src_page).hexdigest().upper(),
             "report": rep}, indent=1))
        (out / "migrated_page.bin").write_bytes(bytes(page))
        return bytes(page)

    try:
        import me711_restore_calibration as A
    except ImportError:
        raise SystemExit("writing a page to an ECU needs the bench write tool "
                         "(me711_restore_calibration.py), which is not part of "
                         "this repository")
    return A.apply_page(a.out, a.dst_ini, plan, a.dry_run,
                        "migrate from layout %08X, cell %d gen %d"
                        % (layout, cell, gen))


if __name__ == "__main__":
    raise SystemExit(main())
