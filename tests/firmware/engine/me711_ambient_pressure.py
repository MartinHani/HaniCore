#!/usr/bin/env python3
r"""
me711_ambient_pressure.py - where the ambient-pressure number comes from, and
the check that an A2L is only ever read against the binary it describes.

    py tests\firmware\engine\me711_ambient_pressure.py          derive, and prove the pairing

THE TARGET, BY ITS OWN EVIDENCE
===============================
The ECU on the bench identifies itself, in its own flash:

    0x8183F3   0261207696          Bosch part number
    0x81840F   022906032BT         Porsche / VAG software part number
    0x8183FD   1037371766          Bosch software number
    0x810005   "40/1/ME7.1.1/4/A1146//44F/DstBKo/070604/3/"   the EPK string

That EPK is quoted VERBATIM because the pairing rule below compares strings.
It is not the target's identity: the identity is the Bosch and Porsche part
numbers above, and the fifth field of that EPK is an obsolete label this
project discarded. Do not carry it into naming, documentation or reasoning.

THE DEFECT THIS EXISTS FOR
==========================
On 2026-09-05 real TunerStudio showed BARO = 1.22 bar while the local
barometric pressure was 1000.6 hPa - about +22 %. The .ini computed it as

    ambientPressure = { ((baroRaw * 6080.0) / 256.0 + 7040.0) * 0.0390625 }

with a comment saying

    DSUGRAD = 0x17C0 little-endian at OEM ME7.1.1 0x8299AE = 6080
    DSUOFS  = 0x1B80 little-endian at OEM ME7.1.1 0x8299B0 = 7040

Both words are really at that address in this ECU's own image. THE ADDRESS IS
NOT THIS ECU'S. It came from `the A1104F A2L`, whose
own header declares a different EPK -

    /begin PROJECT A1104F_44HE_0
    ADDR_EPK 0x810005
    EPK "41/1/ME7.1.1/4/A1104F//44HE/DstH0/100304/"

- and that string is NOT at 0x810005 in the image this ECU runs. The two
calibrations share 13 % of their calibration region byte for byte, so most
addresses land somewhere unrelated. Here one landed in the middle of a strictly
rising table:

    0x8299A2..0x8299D2   0010 0010 0AF0 0C80 10E0 1360 17C0 1B80 1F40 2710
                         2EE0 36B0 3E80 46A0 4E20 5640 5DC0 6590

`17C0 1B80` are cells fifteen and sixteen of that ramp. They are not a gradient
and an offset; they are two adjacent points on an axis for something else. Read
against the binary it IS a map of - `the sibling ME7.1.1 calibration A1104F`, same EPK, same
addresses - the same A2L gives isolated scalars there: 0x3F40 and 0x0000, a
gradient of 253.0 hPa/V and an offset of 0 hPa, which is the shape a
gradient/offset pair has.

    AN A2L IS A MAP OF ONE BINARY. Reading a second binary through it produces
    numbers that are real, plausible, and about nothing.

THE GATE, AND IT IS THE GENERAL FORM
====================================
`ADDR_EPK` and `EPK` are in every ME7 A2L, and the EPK string is in the image at
that address. So the rule has no exceptions and needs no judgement:

    an A2L address may be read from a binary ONLY IF that binary carries the
    A2L's own EPK at the A2L's own ADDR_EPK.

`main()` asserts both directions - the pairing that IS valid and the pairing
that is NOT - so neither can be quietly reversed later.

WHAT IS STILL NOT SETTLED, AND WHY THE NUMBER IS PUBLISHED AS AN ESTIMATE
=========================================================================
THE SCALING WAS NEVER THE WHOLE PROBLEM, and correcting it does not make the
reading trustworthy. THE FULL CHAIN, LINK BY LINK, WITH ITS CLASS:

  1. the physical sender - Bosch calls it the Hoehengeber, the altitude
     sender. WHERE IT ENTERS THE CONNECTOR IS NOT IN THIS REPOSITORY: the
     121-pin workbook `tools/config_source/data/me71_connector_121.csv` has no HOG row,
     because it is an ME7.1 C4 sheet and this is an ME7.1.1 signal.
     `NOT ESTABLISHED`;

  2. the front end and the ADC. Bosch's own port map is unambiguous:
     `tools/config_source/data/me711_iomap.csv` line 185, **ASIC-mC P5.8 / AN8 = HOG,
     "Eingang Hoehengeber"**, both ME7.1.1 columns agreeing. So the ambient
     sender is digitised BY THE PERIPHERAL ASIC, not by the main CPU - the main
     CPU's own P5.8/AN8 is SPS1/DKG, the first pedal track, which is exactly
     the kind of collision this project keeps paying for.
     `SAME-GENERATION BOSCH SCHEMATIC / OEM PORT MAP`;

  3. from the ASIC to us: the 118-word S5500 runtime frame. `hc_hal_ain_service()`
     copies a sixteen-word WINDOW out of it at `hc_s5500_base`, and `baroRaw`
     is the low ten bits of WINDOW SLOT 8;

  4. **whether window slot 8 is ASIC ADC channel 8 at all.** Each frame word
     carries its ADDAT channel index in its top nibble, and the HAL checks it:

         if (((w >> 12) & 0x000F) == i) hc_s5500_idx |= 1u << i;

     so `s5500Idx` bit 8 set means slot 8 really does carry channel 8, and
     `s5500Idx == 0xFFFF` means the whole window is aligned on the ADDAT block.
     `s5500Plaus` counts the snapshots where all sixteen agreed.
     **THE FIRMWARE ALREADY PUBLISHES THE ANSWER AND NOBODY HAS READ IT.**
     `PROBABLE, MEASURABLE WITHOUT A REFLASH`;

  5. the OEM conversion - `pu = DSUOFS + udsu_w[V] * DSUGRAD`, with every
     factor derived below from the A2L's own COMPU_METHODs rather than retyped;

  6. HaniCore's conversion, which is that formula with the A2L read against
     the binary it maps. `SAME-FAMILY ECU REFERENCE`, an ESTIMATE.

SO WHY DOES IT READ NEAR FULL SCALE? THAT IS NOT CONCLUDED HERE. 1.22 bar
through the old expression implies `baroRaw` about 1019 of 1023, and all that
proves is that THE SOURCE BEING READ is at or near full scale. At least three
things produce that and they are distinguished by one number:

    the window is not aligned, so slot 8 is some other frame word entirely
        -> s5500Idx bit 8 is CLEAR
    the window is aligned and ASIC AN8 itself is near full scale
        -> s5500Idx bit 8 is SET, and the question moves to the front end:
           no sender fitted, an open circuit, or a supply/divider fault
    the sender is fitted and working and the conversion is wrong
        -> ruled out by arithmetic: no offset/gradient pair reaches 1000 hPa
           from 1019 counts and also stays inside the sensor's own span

**READ `s5500Idx` FIRST.** It costs nothing, needs no reflash, and it is the
difference between "the wrong wire" and "the right wire with nothing on it".
Until it is read, `baroPlausible` says the number is outside a believable band
and the engine model uses `baroDefault`, which is what it has always used.
"""
from __future__ import annotations

import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: E402  (puts every tools/ and tests/ module on sys.path)

A2L = ROOT / "reference/a2l me7.1.1 porsche/T44HEH0.a2l"
BIN_SIBLING = ROOT / "bins/a1104f_44HETL07.bin"          # what the A2L maps
BIN_TARGET = hcpaths.OEM_READ  # what is in the ECU

FLASH_BASE = 0x800000

# The C167's converter, and the only link in the chain that is not calibration:
# 10 bits over the 5 V reference. The A2L agrees - `spg_uw_q0p00488` is
# COEFFS 0 1024 0 0 0 5, i.e. volts = counts * 5 / 1024 - and that is derived
# below rather than trusted here.
ADC_BITS = 10


# ==========================================================================
# A2L reading. Small and targeted; this file needs four facts out of 8.5 MB.
# ==========================================================================
def _a2l_text():
    return A2L.read_text(encoding="latin-1")


def a2l_epk(text=None):
    """(address, epk string) the A2L says identifies its binary."""
    t = text if text is not None else _a2l_text()
    a = re.search(r"ADDR_EPK\s+(0x[0-9A-Fa-f]+)", t)
    e = re.search(r'EPK\s+"([^"]+)"', t)
    if not a or not e:
        raise SystemExit("this A2L declares no ADDR_EPK / EPK")
    return int(a.group(1), 16), e.group(1)


def a2l_project(text=None):
    t = text if text is not None else _a2l_text()
    m = re.search(r"/begin PROJECT\s+(\S+)\s+\"([^\"]*)\"", t)
    return m.group(2) if m else "?"


def characteristic(name, text=None):
    """(address, conversion method) for a VALUE characteristic."""
    t = text if text is not None else _a2l_text()
    m = re.search(r"/begin CHARACTERISTIC\s+" + re.escape(name)
                  + r"\s+\"[^\"]*\"\s+VALUE\s+(0x[0-9A-Fa-f]+)\s+(\S+)\s+"
                  r"(\S+)\s+(\S+)", t)
    if not m:
        raise SystemExit("%s is not a VALUE CHARACTERISTIC in this A2L" % name)
    # groups after the address are (record layout)(max difference)
    # (conversion method) - ASAP2 1.3 CHARACTERISTIC order.
    return int(m.group(1), 16), m.group(4)


def compu_coeffs(name, text=None):
    """The six RAT_FUNC coefficients: INT = (a x^2 + b x + c)/(d x^2 + e x + f)
    where x is the PHYSICAL value. ASAP2 1.3."""
    t = text if text is not None else _a2l_text()
    m = re.search(r"/begin COMPU_METHOD\s+" + re.escape(name)
                  + r"\s.*?COEFFS\s+([-\d.eE+ ]+)\s*/end COMPU_METHOD",
                  t, re.S)
    if not m:
        raise SystemExit("no COMPU_METHOD named %s" % name)
    return [float(x) for x in m.group(1).split()]


def compu_units(name, text=None):
    t = text if text is not None else _a2l_text()
    m = re.search(r"/begin COMPU_METHOD\s+" + re.escape(name)
                  + r"\s+\"[^\"]*\"\s+RAT_FUNC\s+\"[^\"]*\"\s+\"([^\"]*)\"",
                  t, re.S)
    return m.group(1) if m else ""


def phys_per_bit(coeffs):
    """A linear RAT_FUNC only: INT = b*PHYS / f, so one bit is f/b."""
    a, b, c, d, e, f = coeffs
    if a or c or d or e:
        raise SystemExit("this COMPU_METHOD is not linear: %s" % coeffs)
    if not b:
        raise SystemExit("this COMPU_METHOD has no first-order term")
    return f / b


# ==========================================================================
# Binary reading, and the pairing rule.
# ==========================================================================
def epk_at(path: Path, addr: int, want: str):
    """Does this image carry that EPK at that address?"""
    d = path.read_bytes()
    off = addr - FLASH_BASE
    if off < 0 or off + len(want) > len(d):
        return False, ""
    got = d[off:off + len(want)].decode("ascii", "replace")
    return got == want, got


def image_epk(path: Path, addr: int, length: int = 48):
    """The EPK an image actually carries, as PRINTABLE ASCII.

    Stops at the first byte an EPK cannot contain - the rest of the sector is
    0xFF erase pattern, and printing that killed this gate on a cp1252 console,
    which is a gate that fails for a reason having nothing to do with what it
    is checking."""
    d = path.read_bytes()
    off = addr - FLASH_BASE
    out = []
    for b in d[off:off + length]:
        if b < 0x20 or b > 0x7E:
            break
        out.append(chr(b))
    return "".join(out).strip()


def word_at(path: Path, addr: int, signed=False):
    d = path.read_bytes()
    off = addr - FLASH_BASE
    return struct.unpack_from("<h" if signed else "<H", d, off)[0]


def words_around(path: Path, addr: int, n: int = 8):
    d = path.read_bytes()
    off = addr - FLASH_BASE - 2 * n
    return [struct.unpack_from("<H", d, off + 2 * i)[0] for i in range(2 * n)]


def looks_like_a_ramp(words, need=8):
    """A run of strictly increasing words through the middle of the window.

    Two scalars that happen to be a gradient and an offset do not sit inside
    a monotonic sequence. This is the SECOND, INDEPENDENT witness that the
    A1146 read is landing in a table - it does not depend on the EPK at all."""
    best = run = 1
    for i in range(1, len(words)):
        run = run + 1 if words[i] > words[i - 1] else 1
        best = max(best, run)
    return best >= need, best


# ==========================================================================
# The published transfer function.
# ==========================================================================
# The derived result, pinned so the .ini generator runs in a clone without the
# local A2L and sibling binary. When they are present, main() re-derives it and
# fails if it no longer equals this.
PINNED = {
    "a2l_project": "A1104F",
    "a2l_epk": "41/1/ME7.1.1/4/A1104F//44HE/DstH0/100304/",
    "addr_epk": 0x810005,
    "sibling_epk": "41/1/ME7.1.1/4/A1104F//44HE/DstH0/100304/",
    "target_epk": "40/1/ME7.1.1/4/A1146//44F/DstBKo/070604/3/",
    "dsugrad_addr": 0x8299AE, "dsuofs_addr": 0x8299B0,
    "dsugrad_int": 16192, "dsuofs_int": 0,
    "hpa_per_v_bit": 0.015625, "hpa_bit": 0.0390625, "v_bit": 0.0048828125,
    "gradient_hpa_per_v": 253.0,
    "offset_hpa": 0.0,
    "hpa_per_count": 1.2353515625,
    "volts_per_count": 0.0048828125,
    "units": "hPa",
}


def transfer():
    """Everything the .ini needs, plus where each number came from."""
    if not (A2L.exists() and BIN_SIBLING.exists()):
        return dict(PINNED)
    t = _a2l_text()
    addr_epk, epk = a2l_epk(t)

    g_addr, g_conv = characteristic("DSUGRAD", t)
    o_addr, o_conv = characteristic("DSUOFS", t)
    v_conv = "spg_uw_q0p00488"          # udsu_w's own conversion

    hpa_per_v_bit = phys_per_bit(compu_coeffs(g_conv, t))   # DSUGRAD LSB
    hpa_bit = phys_per_bit(compu_coeffs(o_conv, t))         # DSUOFS  LSB
    v_bit = phys_per_bit(compu_coeffs(v_conv, t))           # ADC LSB, volts

    ok, _got = epk_at(BIN_SIBLING, addr_epk, epk)
    if not ok:
        raise SystemExit("the A2L's own binary does not carry its EPK - the "
                         "reference pair in this repository is broken")

    g_int = word_at(BIN_SIBLING, g_addr)
    o_int = word_at(BIN_SIBLING, o_addr, signed=True)

    gradient = g_int * hpa_per_v_bit        # hPa per volt
    offset = o_int * hpa_bit                # hPa
    # hPa per ADC count, which is what the .ini expression needs.
    per_count = gradient * v_bit

    return {
        "a2l_project": a2l_project(t),
        "a2l_epk": epk,
        "addr_epk": addr_epk,
        "sibling_epk": image_epk(BIN_SIBLING, addr_epk),
        "target_epk": image_epk(BIN_TARGET, addr_epk),
        "dsugrad_addr": g_addr, "dsuofs_addr": o_addr,
        "dsugrad_int": g_int, "dsuofs_int": o_int,
        "hpa_per_v_bit": hpa_per_v_bit, "hpa_bit": hpa_bit, "v_bit": v_bit,
        "gradient_hpa_per_v": gradient,
        "offset_hpa": offset,
        "hpa_per_count": per_count,
        "volts_per_count": v_bit,
        "units": compu_units(o_conv, t) or "hPa",
    }


def ini_expression(tr=None):
    """The [OutputChannels] expression, and its provenance comment."""
    tr = tr or transfer()
    expr = "{ baroRaw * %.6f + %.4f }" % (tr["hpa_per_count"], tr["offset_hpa"])
    note = ("ambient pressure, SIBLING CALIBRATION %s: DSUGRAD %d = %.1f hPa/V, "
            "DSUOFS %d = %.1f hPa. NOT exact-target - see "
            "tests/firmware/engine/me711_ambient_pressure.py"
            % (tr["a2l_project"], tr["dsugrad_int"],
               tr["gradient_hpa_per_v"], tr["dsuofs_int"], tr["offset_hpa"]))
    return expr, note


# ==========================================================================
# The gate.
# ==========================================================================
FAILS = 0


def ck(name, ok, detail=""):
    global FAILS
    print("  [%s] %-56s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def main():
    global FAILS
    for p in (A2L, BIN_SIBLING, BIN_TARGET):
        if not p.exists():
            print("missing: %s" % p)
            return 1

    ck("the derived transfer equals the pinned one the .ini generator uses",
       transfer() == PINNED, "re-derived from the A2L and its binary")

    t = _a2l_text()
    addr_epk, epk = a2l_epk(t)
    print("=== the A2L, and which binary it is a map of ===\n")
    print("  A2L        %s" % A2L.name)
    print("  PROJECT    %s" % a2l_project(t))
    print("  ADDR_EPK   0x%06X" % addr_epk)
    print("  EPK        %s\n" % epk)
    print("  the A2L's own binary")
    print("    %-30s EPK %s" % (BIN_SIBLING.name,
                                image_epk(BIN_SIBLING, addr_epk)))
    print("  THE ECU ON THE BENCH - Bosch 0261207696 / Porsche 022906032BT")
    print("    %-30s EPK %s\n" % (BIN_TARGET.name,
                                  image_epk(BIN_TARGET, addr_epk)))

    # THE TARGET NAMES ITSELF. Asserted, not assumed - a gate that reasons
    # about "the ECU on the bench" while pointed at some other file is the
    # stale-image defect this project has paid for four times.
    tgt = BIN_TARGET.read_bytes()
    for want, where in ((b"0261207696", "Bosch part number"),
                        (b"022906032BT", "Porsche software part number"),
                        (b"1037371766", "Bosch software number")):
        ck("the image carries %s" % where, want in tgt,
           want.decode())

    ok_s, _ = epk_at(BIN_SIBLING, addr_epk, epk)
    ck("the A2L's EPK IS in bins/a1104f_44HETL07.bin", ok_s,
       "so its addresses may be read from that image")

    ok_t, _ = epk_at(BIN_TARGET, addr_epk, epk)
    ck("the A2L's EPK is NOT in this ECU's own OEM image", not ok_t,
       "so its addresses may not be read from THIS binary - the defect")

    g_addr, _g_conv = characteristic("DSUGRAD", t)
    tgt_words = words_around(BIN_TARGET, g_addr, 9)
    ramp, run = looks_like_a_ramp(tgt_words)
    ck("and the read into THIS binary lands inside a monotonic table", ramp,
       "longest rising run through 0x%06X is %d words" % (g_addr, run))

    sib_words = words_around(BIN_SIBLING, g_addr, 9)
    sib_ramp, sib_run = looks_like_a_ramp(sib_words)
    ck("while the read into the A2L's own binary does not", not sib_ramp,
       "longest rising run there is %d words" % sib_run)

    ck("the two words a wrongly-paired read produced",
       word_at(BIN_TARGET, g_addr) == 6080
       and word_at(BIN_TARGET, g_addr + 2) == 7040,
       "0x%04X 0x%04X - cells of that ramp, published for weeks as "
       "DSUGRAD/DSUOFS" % (word_at(BIN_TARGET, g_addr),
                           word_at(BIN_TARGET, g_addr + 2)))

    # ---------------------------------------------------------------- GGPU
    # THE BLOCK IS FOUR WORDS, AND ONLY TWO WERE EVER USED.
    #
    # the A1104F A2L's function GGPU declares DSUGRAD DSUOFS TDDU UDSUMN UDSUMX,
    # and four of those sit contiguously:
    #
    #   0x8299AE  DSUGRAD  u16   gradient
    #   0x8299B0  DSUOFS   s16   offset
    #   0x8299B2  UDSUMN   u16   min diagnostic voltage, q = 0.00488 V
    #   0x8299B4  UDSUMX   u16   max diagnostic voltage, q = 0.00488 V
    #
    # 0.00488 V is 5/1024, so UDSUMN and UDSUMX are RAW 10-BIT ADC COUNTS on a
    # 5 V rail. That makes them the sharpest test available for "is this block
    # really GGPU": a diagnostic window has a low rail, a high rail near full
    # scale, low < high, and BOTH inside 0..1023. Random calibration data does
    # not land in that shape, and a value above 1023 cannot be a threshold for
    # a converter that cannot produce it.
    ADC_FULL = 1023
    mn = word_at(BIN_SIBLING, g_addr + 4)
    mx = word_at(BIN_SIBLING, g_addr + 6)
    ck("the A2L's own binary carries a real diagnostic window after the pair",
       0 < mn < mx <= ADC_FULL,
       "UDSUMN %d counts = %.3f V, UDSUMX %d counts = %.3f V - a 10-bit "
       "window on a 5 V rail" % (mn, mn * 5.0 / 1024.0, mx, mx * 5.0 / 1024.0))
    ck("and it sits near the rails, as an under/over-range test must",
       mn <= 120 and mx >= 900,
       "%.3f V .. %.3f V" % (mn * 5.0 / 1024.0, mx * 5.0 / 1024.0))

    # THE CANDIDATE THIS KILLS, SO IT CANNOT COME BACK.
    #
    # A search of THIS ECU's image for the sibling's (DSUGRAD, DSUOFS) word
    # pair found exactly one hit per megabyte, at 0x81EE12, and in the sibling
    # the unique hit IS the right address. That was a real uniqueness argument
    # and it was still wrong, because it assumed the Porsche calibration uses
    # the sibling's gradient and a zero offset. Reading two words further
    # settles it: the window would be 25600 and 10240 counts, on a converter
    # whose largest possible output is 1023, with the minimum ABOVE the
    # maximum. DO NOT RESURRECT 0x81EE12.
    CAND = 0x81EE12
    cmn = word_at(BIN_TARGET, CAND + 4)
    cmx = word_at(BIN_TARGET, CAND + 6)
    ck("the 0x81EE12 candidate is REFUTED by the two words nobody read",
       not (0 < cmn < cmx <= ADC_FULL),
       "UDSUMN would be %d counts and UDSUMX %d, against a 10-bit maximum of "
       "%d - impossible, so the (DSUGRAD, DSUOFS) match there is coincidence"
       % (cmn, cmx, ADC_FULL))

    # THE CONTROL FOR THAT TEST: the same three-part shape must ACCEPT the
    # block that is known to be right, or it is rejecting everything and
    # proving nothing.
    ck("negative control - the same test ACCEPTS the known-good block",
       0 < mn < mx <= ADC_FULL,
       "the test discriminates rather than refusing every address")

    tr = transfer()
    print()
    ck("the ADC conversion is the A2L's own", abs(tr["v_bit"] - 5.0 / 1024) < 1e-9,
       "spg_uw_q0p00488 -> %.9f V/count" % tr["v_bit"])
    ck("DSUGRAD's unit is hPa/V", abs(tr["hpa_per_v_bit"] - 1 / 64.0) < 1e-9,
       "dgrad_uw_q0p015 -> %.6f (hPa/V)/bit" % tr["hpa_per_v_bit"])
    ck("DSUOFS's unit is hPa", abs(tr["hpa_bit"] - 10.0 / 256) < 1e-9,
       "p_sw_q0p039 -> %.7f hPa/bit" % tr["hpa_bit"])

    print("\n  sibling transfer function:")
    print("    gradient  %8.3f hPa/V   (DSUGRAD %d)"
          % (tr["gradient_hpa_per_v"], tr["dsugrad_int"]))
    print("    offset    %8.3f hPa     (DSUOFS  %d)"
          % (tr["offset_hpa"], tr["dsuofs_int"]))
    print("    per count %8.6f hPa" % tr["hpa_per_count"])

    # Physical sanity, at points nobody chose to make it pass: the sensor must
    # be monotonic, must read something breathable across its span, and must
    # not put sea level outside its own range.
    def pu(c):
        return c * tr["hpa_per_count"] + tr["offset_hpa"]

    print("\n  what it says at four counts:")
    for c in (204, 512, 819, 1023):
        print("    %4d counts  %5.3f V  %7.1f hPa"
              % (c, c * tr["volts_per_count"], pu(c)))

    ck("monotonic", pu(0) < pu(512) < pu(1023))
    ck("sea level is inside the sensor's span",
       pu(0) < 1013.25 < pu(1023),
       "1013.25 hPa needs %.0f counts" % ((1013.25 - tr["offset_hpa"])
                                          / tr["hpa_per_count"]))
    ck("full scale is a pressure a pressure sensor could have",
       500.0 < pu(1023) < 2500.0, "%.0f hPa at 1023 counts" % pu(1023))

    # And the thing the .ini must never do again.
    old = ((1019 * 6080.0) / 256.0 + 7040.0) * 0.0390625
    ck("the OLD expression explains the bench reading",
       abs(old - 1220.0) < 15.0,
       "count 1019 -> %.0f hPa = %.2f bar, and the bench saw 1.22 bar"
       % (old, old / 1000.0))
    # WHAT A NEAR-FULL-SCALE READING DOES AND DOES NOT PROVE.
    #
    # It proves the SOURCE BEING READ is near full scale. It does not say which
    # source that is, and this module used to assert "an unconnected analog
    # input on a bench" as though it did. Three explanations fit, and ONE
    # PUBLISHED NUMBER separates them - see the docstring's chain, link 4.
    implied = (1220.0 / 0.0390625 - 7040.0) * 256.0 / 6080.0
    ck("the reading implies a raw count near full scale",
       1000 < implied < 1023,
       "1.22 bar through the old expression needs %.0f of 1023" % implied)

    # The one thing arithmetic CAN rule out: no offset/gradient pair reads
    # 1000.6 hPa at that count and also keeps the sensor inside its own span.
    need = 1000.6 / implied
    ck("and no plausible transfer function rescues it",
       not (0.9 < need * 1023 / 1265.0 < 1.1),
       "%.0f counts would have to mean 1000.6 hPa, i.e. %.3f hPa/count, "
       "against %.3f derived - full scale would be %.0f hPa"
       % (implied, need, tr["hpa_per_count"], need * 1023))

    # SO THE NEXT STEP IS A READING, NOT A CONSTANT. Bosch's own port map puts
    # the ambient sender on the PERIPHERAL ASIC, and the HAL already tags every
    # window word with the ADDAT channel it claims to be.
    hal = (ROOT / "firmware/targets/me711/hal/hchal_me711.c").read_text(errors="replace")
    ck("the HAL tags each window slot with its ADDAT channel",
       "(w >> 12) & 0x000Fu) == (unsigned int)i" in hal,
       "s5500Idx bit i = slot i really carries channel i")
    iomap = (ROOT / "tools/config_source/data/me711_iomap.csv").read_text(errors="replace")
    ck("Bosch's port map puts HOG on the ASIC's AN8, not the main CPU",
       any(r.startswith("ASIC-mC") and ",HOG," in r
           for r in iomap.splitlines()),
       "Eingang Hoehengeber - the main CPU's own AN8 is SPS1/DKG, pedal 1")

    print("\n  WHY IT READS HIGH IS NOT SETTLED HERE, AND ONE NUMBER SETTLES IT:")
    print("    read s5500Idx.")
    print("      bit 8 CLEAR  -> the window is not aligned and baroRaw is some")
    print("                      other frame word entirely: WRONG SOURCE")
    print("      bit 8 SET    -> slot 8 really is ASIC AN8 = HOG, and the")
    print("                      question moves to the front end - no sender")
    print("                      fitted, an open circuit, or a supply fault")
    print("      0xFFFF       -> the whole window is on the ADDAT block")
    print("    No reflash. It is already published, beside baroRaw.")

    expr, note = ini_expression(tr)
    print("\n  the .ini expression:\n    ambientPressure = %s\n    ; %s"
          % (expr, note))

    print("\n%s" % ("AMBIENT PRESSURE: the pairing rule holds and the transfer "
                    "function read\nfrom the A2L's OWN binary is "
                    "self-consistent - published as an ESTIMATE.\nThe SOURCE "
                    "is not proven, and which of the three explanations "
                    "applies\nis a bench reading of s5500Idx, not a "
                    "constant."
                    if not FAILS else "AMBIENT PRESSURE PROOF FAILS - %d check(s)."
                    % FAILS))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
