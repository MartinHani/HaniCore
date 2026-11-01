#!/usr/bin/env python3
r"""
xdf_read.py - read a TunerPro XDF definition and the values it names in a
binary. Only what the ME7 XDFs here use: XDFCONSTANT and XDFTABLE with
EMBEDDEDDATA axes, 8/16-bit elements, the signed (0x01) / little-endian
(0x02) / column-major (0x04) type flags, and MATH equations of the form
`a * X`, `a * X + b`, `a * X - b`, `X * a`, `X / a`.

    py tools\lib\xdf_read.py <file.xdf> <file.bin> NAME [NAME ...]

The equation is parsed, never eval'd: an XDF is downloaded data. A title
that occurs more than once (ME7 XDFs carry e.g. 8-bit and 16-bit-axis
variants of KFZW) is returned in file order; pick by index.
"""
from __future__ import annotations

import re
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_NUM = r"([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"
_EQ = [
    (re.compile(r"^%s\*X$" % _NUM), lambda m: (float(m[1]), 0.0)),
    (re.compile(r"^X\*%s$" % _NUM), lambda m: (float(m[1]), 0.0)),
    (re.compile(r"^X/%s$" % _NUM), lambda m: (1.0 / float(m[1]), 0.0)),
    (re.compile(r"^%s\*X([-+])%s$" % (_NUM, _NUM)),
     lambda m: (float(m[1]), float(m[3]) * (1 if m[2] == "+" else -1))),
    (re.compile(r"^\(%s\*X\)([-+])%s$" % (_NUM, _NUM)),
     lambda m: (float(m[1]), float(m[3]) * (1 if m[2] == "+" else -1))),
    (re.compile(r"^X$"), lambda m: (1.0, 0.0)),
]


def parse_eq(eq: str):
    """(scale, offset) of a linear XDF equation, or ValueError."""
    s = eq.replace(" ", "")
    for rx, f in _EQ:
        m = rx.match(s)
        if m:
            return f(m)
    raise ValueError("unsupported XDF equation %r" % eq)


def _elems(b: bytes, el, n: int):
    """n raw integers from an EMBEDDEDDATA element."""
    addr = int(el.get("mmedaddress"), 16)
    bits = int(el.get("mmedelementsizebits", "8"))
    fl = int(el.get("mmedtypeflags", "0"), 16)
    signed, little = bool(fl & 0x01), True   # every ME7 file here is LSB first
    w = bits // 8
    fmt = {1: "b" if signed else "B", 2: "h" if signed else "H"}[w]
    return [struct.unpack_from(("<" if little else ">") + fmt, b, addr + w * i)[0]
            for i in range(n)], addr, fl


class Item:
    def __init__(self, title, desc, kind):
        self.title, self.desc, self.kind = title, desc, kind
        self.x = self.y = self.z = None    # physical values
        self.raw = None
        self.addr = None

    def __repr__(self):
        return "<%s %s @0x%X>" % (self.kind, self.title, self.addr or 0)


def _math(node):
    m = node.find("MATH")
    return parse_eq(m.get("equation")) if m is not None else (1.0, 0.0)


def read(xdf: Path, binary: Path) -> dict[str, list[Item]]:
    b = Path(binary).read_bytes()
    root = ET.fromstring(Path(xdf).read_text(encoding="latin-1"))
    out: dict[str, list[Item]] = {}
    for node in root:
        if node.tag not in ("XDFCONSTANT", "XDFTABLE"):
            continue
        title = (node.findtext("title") or "").strip()
        it = Item(title, (node.findtext("description") or "").strip(), node.tag)
        try:
            if node.tag == "XDFCONSTANT":
                el = node.find("EMBEDDEDDATA")
                (raw,), it.addr, _ = _elems(b, el, 1)
                a, o = _math(node)
                it.raw, it.z = raw, raw * a + o
            else:
                axes = {ax.get("id"): ax for ax in node.findall("XDFAXIS")}
                zx = axes["z"]
                zel = zx.find("EMBEDDEDDATA")
                rows = int(zel.get("mmedrowcount", "1"))
                cols = int(zel.get("mmedcolcount", "1"))
                for k in ("x", "y"):
                    ax = axes.get(k)
                    if ax is None or ax.find("EMBEDDEDDATA") is None \
                            or ax.find("EMBEDDEDDATA").get("mmedaddress") is None:
                        continue
                    n = int(ax.findtext("indexcount") or 0)
                    raw, _, _ = _elems(b, ax.find("EMBEDDEDDATA"), n)
                    a, o = _math(ax)
                    setattr(it, k, [r * a + o for r in raw])
                raw, it.addr, fl = _elems(b, zel, rows * cols)
                a, o = _math(zx)
                if fl & 0x04:       # column major -> row major
                    raw = [raw[c * rows + r] for r in range(rows) for c in range(cols)]
                it.raw = [raw[r * cols:(r + 1) * cols] for r in range(rows)]
                it.z = [[v * a + o for v in row] for row in it.raw]
        except (ValueError, KeyError, struct.error, TypeError) as e:
            it.kind += " (unreadable: %s)" % e
        out.setdefault(title, []).append(it)
    return out


def _selfcheck():
    assert parse_eq("0.750000 * X") == (0.75, 0.0)
    assert parse_eq("0.75 * X - 48") == (0.75, -48.0)
    assert parse_eq("X / 4") == (0.25, 0.0)
    try:
        parse_eq("__import__('os')")
    except ValueError:
        pass
    else:
        raise AssertionError("an arbitrary expression was accepted")


if __name__ == "__main__":
    _selfcheck()
    if len(sys.argv) < 4:
        print("xdf_read self-check OK; usage: xdf_read.py file.xdf file.bin NAME...")
        raise SystemExit(0)
    items = read(Path(sys.argv[1]), Path(sys.argv[2]))
    for name in sys.argv[3:]:
        for i, it in enumerate(items.get(name, [])):
            print("%s[%d] %s @0x%X  %s" % (name, i, it.kind, it.addr or 0, it.desc[:60]))
            if it.x:
                print("  x", [round(v, 3) for v in it.x])
            if it.y:
                print("  y", [round(v, 3) for v in it.y])
            if isinstance(it.z, list):
                for row in it.z:
                    print("   ", [round(v, 3) for v in row])
            else:
                print("  =", it.z)
