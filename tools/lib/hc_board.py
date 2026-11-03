#!/usr/bin/env python3
r"""
hc_board.py - WHICH BOARD of the ME7.1x target family a tool is talking about.

    set HANICORE_BOARD=vag_me71_c4      (default: porsche_me711)

One source tree builds two boards (firmware/targets/me711/hctarget.h,
"THE BOARD"): the Porsche ME7.1.1 and the Audi 2.7T ME7.1 C4. A tool that
reads hctarget.h with a regex sees the Porsche value first - every board
value is written `#if !TGT_BOARD_VAG_ME71_C4 <Porsche> #else <C4>`. Tools
that must describe the 2.7T read board_text() instead, which drops the
inactive branch exactly as the compiler does for that one macro.

me711_image.py takes its default stem from this, so
`set HANICORE_BOARD=vag_me71_c4` points the image locator - and every gate
built on it - at bins/hanicore/HaniCore_ME71_27T_v102_dev.bin.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOARDS = ("porsche_me711", "vag_me71_c4", "audi_4f_v8", "vag_me75_dc",
          "vag_me75_bfb")
BOARD = os.environ.get("HANICORE_BOARD", "porsche_me711")
if BOARD not in BOARDS:
    raise SystemExit("HANICORE_BOARD=%r: one of %s" % (BOARD, ", ".join(BOARDS)))
# the ME7.5 DC (2026-10-28) is built ON the 2.7T branch (24 MHz C167CR,
# 05.12 mask-ROM boot) with TGT_BOARD_VAG_ME75_DC swapping the S5500 path
# for the CC650 + 68HC05 monitor (.scratch/me75-reverse/PORT_SPEC.md):
# every `#if TGT_BOARD_VAG_ME71_C4` branch applies to it as well
# the A4 B7 BFB ME7.5 (2026-11-02, 8E0909518AQ) is the DC's hardware on its
# own ROMSYS variant and identity: every DC branch applies to it as well
IS_BFB = BOARD == "vag_me75_bfb"
IS_DC = BOARD in ("vag_me75_dc", "vag_me75_bfb")
IS_C4 = BOARD in ("vag_me71_c4", "vag_me75_dc", "vag_me75_bfb")
# the 4F (2026-10-27) is Porsche code on its own boot region: IS_C4 False,
# every Porsche branch applies; only its image name and boot region differ
IS_4F = BOARD == "audi_4f_v8"
STEM = {"porsche_me711": None, "vag_me71_c4": "HaniCore_ME71_27T_v102_dev",
        "audi_4f_v8": "HaniCore_ME711_4F_v102_dev",
        "vag_me75_dc": "HaniCore_ME75_DC_v102_dev",
        "vag_me75_bfb": "HaniCore_ME75_BFB_v102_dev"}[BOARD]
# the image whose TunerStudio files this board uses: the 4F has the
# Porsche's layout and signature, so it shares the Porsche's file family
# (a second hanicore_me711_* family made the forensic lookup ambiguous)
INI_STEM = "HaniCore_ME711_v102_dev" if IS_4F else STEM
INI = {"porsche_me711": "hanicore_me711.ini", "audi_4f_v8": "hanicore_me711.ini",
       "vag_me71_c4": "hanicore_me71_27t.ini",
       "vag_me75_dc": "hanicore_me75_dc.ini",
       "vag_me75_bfb": "hanicore_me75_bfb.ini"}[BOARD]
# the Gauge Cluster is bound to the board's signature (firmwareSignature)
DASH = {"porsche_me711": "HaniCore.dash", "audi_4f_v8": "HaniCore.dash",
        "vag_me71_c4": "HaniCore_ME71C4.dash",
        "vag_me75_dc": "HaniCore_ME75DC.dash",
        "vag_me75_bfb": "HaniCore_ME75BFB.dash"}[BOARD]
HCTARGET = ROOT / "firmware/targets/me711/hctarget.h"

# RELEASE FILE NAMES (owner, 2026-11-02): HaniCore_<board>_<ECU part
# number>_<build id>.bin / .ini - the ECU a file is for and the exact build,
# readable without opening it. The development stems above stay what gates
# and tools look up; the build also writes the release names (bins/release/).
RELEASE_BOARD = {"porsche_me711": ("Porsche", "022906032BT"),
                 "vag_me71_c4": ("27T", "4B0907551F"),
                 "audi_4f_v8": ("4F", "4F0910560"),
                 "vag_me75_dc": ("18T", "4B0906018DC"),
                 "vag_me75_bfb": ("BFB", "8E0909518AQ")}
RELEASE_DIR = ROOT / "bins/release"


def release_stem(build_id: str, board: str | None = None,
                 plain: bool = False) -> str:
    """HaniCore_27T_4B0907551F_32F5BF30 - the published (--updater) image
    and its .ini; `plain` marks the build without the updater (not
    published)."""
    tag, part = RELEASE_BOARD[board or BOARD]
    return "HaniCore_%s_%s_%s%s" % (tag, part, build_id.upper(),
                                     "_plain" if plain else "")


def board_text(path: Path, is_c4: bool | None = None,
               is_dc: bool | None = None) -> str:
    # (`#if TGT_BOARD_VAG_ME75_BFB` blocks follow IS_BFB the same way)
    """`path` with the inactive branch of every `#if !TGT_BOARD_VAG_ME71_C4`
    / `#if TGT_BOARD_VAG_ME71_C4` ... `#else` ... `#endif` removed - and the
    same for `#if TGT_BOARD_VAG_ME75_DC` (the DC builds on the C4 branch and
    overrides a few values at the end of hctarget.h: an active `#undef X`
    drops every earlier `#define X`, so a regex reads the DC's value). Other
    conditionals are left alone."""
    c4 = IS_C4 if is_c4 is None else is_c4
    dc = (IS_DC if is_c4 is None else False) if is_dc is None else is_dc
    f4 = IS_4F if is_c4 is None else False
    bfb = IS_BFB if is_c4 is None else False
    out, stack = [], []          # (is_board_conditional, active)
    for line in Path(path).read_text(errors="replace").splitlines(keepends=True):
        s = line.strip()
        m = re.match(r"#\s*if\s+(!?)\s*TGT_BOARD_VAG_ME71_C4\b", s)
        if m:
            stack.append((True, (m.group(1) == "!") != c4))
            continue
        m = re.match(r"#\s*if\s+(!?)\s*TGT_BOARD_VAG_ME75_DC\b", s)
        if m:
            stack.append((True, (m.group(1) == "!") != dc))
            continue
        m = re.match(r"#\s*if\s+(!?)\s*TGT_BOARD_VAG_ME75_BFB\b", s)
        if m:
            stack.append((True, (m.group(1) == "!") != bfb))
            continue
        # the 4F's own block (2026-10-29): `#ifdef TGT_BOARD_AUDI_4F` used to
        # fall through as an ordinary conditional, ACTIVE - its `#undef
        # TGT_VERSIONTXT` then gave the Porsche manifest the 4F's text
        # (me711_identity_proof: "ME7.1.1 4F" expected in the Porsche image)
        m = re.match(r"#\s*(ifdef|ifndef|if\s+(!?)\s*defined\s*\(?|if\s+(!?))\s*"
                     r"TGT_BOARD_AUDI_4F\b", s)
        if m:
            neg = s.startswith("#ifndef") or "!" in s.split("TGT_BOARD_AUDI_4F")[0]
            stack.append((True, neg != f4))
            continue
        m = re.match(r"#\s*undef\s+(\w+)", s)
        if m and all(a for b, a in stack if b):
            pat = re.compile(r"\s*#\s*define\s+%s\b" % m.group(1))
            out = [x for x in out if not pat.match(x)]
            continue
        if re.match(r"#\s*if", s):
            stack.append((False, True))
        elif re.match(r"#\s*else\b", s) and stack and stack[-1][0]:
            stack[-1] = (True, not stack[-1][1])
            continue
        elif re.match(r"#\s*endif\b", s) and stack:
            if stack.pop()[0]:
                continue
        if all(a for b, a in stack if b):
            out.append(line)
    return "".join(out)


def target_text() -> str:
    return board_text(HCTARGET)


def define_int(name: str) -> int:
    """An integer `#define` of hctarget.h as THIS board's build sees it."""
    m = re.search(r"#define\s+%s\s+(0[xX][0-9A-Fa-f]+|\d+)" % re.escape(name), target_text())
    return int(m.group(1), 0)


def s0bg_rates() -> dict:
    """S0BG -> nominal baud for THIS board's K-line rates, from its header:
    the default (57600), the 10400 KWP rate, 124800 and - only on the 40 MHz
    Porsche - 115200. (24 MHz: 0x0C / 0x47 / 0x05; 32 MHz BFB: 0x10 / 0x5F /
    0x07; 40 MHz: 0x15 / 0x77 / 0x09 and 0x0A.)"""
    r = {define_int("TGT_S0BG"): 57600, define_int("TGT_S0BG_10400"): 10400}
    if IS_C4:
        r[define_int("TGT_S0BG_ALT")] = 124800          # no 115200 on these CPUs
    else:
        r[define_int("TGT_S0BG_ALT")] = 115200
        r[define_int("TGT_S0BG_ALT2")] = 124800
    return r


def fcpu_hz() -> int:
    """This board's CPU clock, read from hctarget.h the way the build sees it
    (an active `#undef` drops the earlier define). Tests that need a clock-
    derived figure take it from here, never from a per-board literal: the
    BFB's 32 MHz was missed for exactly that reason (2026-11-02)."""
    m = re.search(r"#define\s+TGT_FCPU_HZ\s+(\d+)", target_text())
    return int(m.group(1))


if __name__ == "__main__":
    # self-check: the two boards differ where they must and agree elsewhere
    p, c = board_text(HCTARGET, False), board_text(HCTARGET, True)
    def d(t, n):
        return re.search(r"#define\s+%s\s+(\S+)" % n, t).group(1)
    assert d(p, "TGT_FCPU_HZ") == "40000000uL", d(p, "TGT_FCPU_HZ")
    assert d(c, "TGT_FCPU_HZ") == "24000000uL", d(c, "TGT_FCPU_HZ")
    assert fcpu_hz() == {"vag_me75_bfb": 32_000_000, "porsche_me711": 40_000_000,
                         "audi_4f_v8": 40_000_000}.get(BOARD, 24_000_000), fcpu_hz()
    assert d(p, "TGT_ASIC_WORDS_RUN") == "0x76u"
    assert d(c, "TGT_ASIC_WORDS_RUN") == "0x60u"
    assert d(p, "TGT_OCH_SIZE") == d(c, "TGT_OCH_SIZE")
    assert "ME71C4 " in re.search(r'TGT_SIGNATURE\s+"([^"]+)"', c).group(1)
    print("hc_board self-check OK (%s)" % BOARD)
