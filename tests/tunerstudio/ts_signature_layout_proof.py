#!/usr/bin/env python3
r"""ts_signature_layout_proof.py - two .ini files that describe different pages
may not answer to the same signature.

    py tests\tunerstudio\ts_signature_layout_proof.py

WHY THIS GATE EXISTS, AND IT IS THE MOST EXPENSIVE ONE IN THE FILE
=================================================================
TunerStudio has exactly ONE mechanism for refusing an .ini that does not
describe the controller in front of it, and that mechanism is the signature
string. It compares what the .ini declares against what the ECU answers to `S`,
and if they match it trusts every offset in the file.

`TGT_SIGNATURE` was the frozen literal `"rusEFI Hanicore v1"` from V21 to V59.
**Five releases moved the calibration page underneath it.** V55 alone inserted
eight bytes at offset 2540 - `trigAngleX10` (V96: `trigOffsetX10`), `camRefs`, `camPad`, `camRefX10`,
`camWindowX10` - so everything above it shifted:

    field        V48 .ini says        V59 firmware reads
    pinCrank          2540                   2548
    pinCam1           2541                   2549
    injPin[0]         2543                   2551

MEASURED ON THE ECU, 2026-09-16. The operator ran the V48 .ini against V59
firmware. TunerStudio accepted it without a word, because the signatures match.
The Trigger dialog showed a crank pin that was assigned - byte 2540, which
really did hold 0x00 - while the byte the firmware validates, 2548, read 0xFF.
`cfgFirstBadOffset` said 2548 and the .ini in front of the tuner had no field
there at all. **The Burn was refused for a fault that was invisible and
unfixable from the file they were using.**

`HC_CFG_LAYOUT_ID` already exists: a CRC32 over every field's slot name,
offset, C type and element count, emitted by the config generator, and
`hcnvm.c` has refused a STORED record whose layout id does not match since V39.
A calibration in flash was protected from this and a live tuning tool was not.
It is the same question, and the answer is to put the layout id in the
signature so an .ini for another layout CANNOT connect.

WHAT IS CHECKED
---------------
1. the firmware's signature begins `rusEFI ` - TunerStudio's rusEFI identity;
2. it carries `HC_CFG_LAYOUT_ID`, so it moves when the page moves;
3. every generated .ini declares exactly that signature, in both
   `[MegaTune]` and `[TunerStudio]`, and the generated `.dash` agrees;
4. `blockReadTimeout` outwaits `TGT_LIVE_BURN_DEADLINE_MS`;
5. THE CONTROL: the frozen V48 and V59 .ini files disagree about a real page
   offset AND declare the same signature - the defect, reproduced from the two
   artefacts that actually met on the bench - while the current .ini's
   signature matches neither of them.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

ROOT = Path(__file__).resolve().parents[2]
TGT = ROOT / "firmware/targets/me711/hctarget.h"
GEN = ROOT / "firmware/generated/hc_config_generated.h"
INI_DIR = ROOT / "tunerstudio"
DASH = INI_DIR / "HaniCore.dash"

# The two files that met on the bench on 2026-09-16. Frozen artefacts, named
# by path: the point of the control is that these exact files exist and that
# this gate fails if they ever stop disagreeing.
V48_INI = (ROOT / "release/Porsche_ME711_V48_LIVE_BURN_CALL_CLOBBER_FIX"
           / "hanicore_me711_v48_live_burn_call_clobber_fix.ini")
V59_INI = (ROOT / "release/Porsche_ME711_V59_FORENSIC_WINDOW"
           / "hanicore_me711_v59_forensic_window.ini")

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-66s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def ini_signatures(path):
    """Every `signature =` in the file, by the section it appears in."""
    out = {}
    sec = ""
    for line in path.read_text(errors="replace").splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            sec = s[1:-1]
            continue
        m = re.match(r'signature\s*=\s*"([^"]*)"', s)
        if m:
            out[sec] = m.group(1)
    return out


def page_offsets(path):
    """name -> page offset, for every Constants entry in one .ini."""
    out = {}
    txt = path.read_text(errors="replace")
    body = txt.split("[Constants]", 1)[1]
    body = re.split(r"^\[Output", body, maxsplit=1, flags=re.M)[0]
    for m in re.finditer(r"^\s*(\w+)\s*=\s*(?:scalar|bits|array),\s*[SU]\d\d,"
                         r"\s*(\d+)", body, re.M):
        out.setdefault(m.group(1), int(m.group(2)))
    return out


def main():
    print("=== the signature must move when the calibration page moves ===\n")

    tgt = TGT.read_text(errors="replace")
    sig = re.search(r'#define\s+TGT_SIGNATURE\s+"([^"]*)"', tgt).group(1)
    deadline = int(re.search(r"#define\s+TGT_LIVE_BURN_DEADLINE_MS\s+(\d+)",
                             tgt).group(1))
    layout = re.search(r"#define\s+HC_CFG_LAYOUT_ID\s+0x([0-9A-Fa-f]{8})uL",
                       GEN.read_text(errors="replace")).group(1).upper()

    print("  TGT_SIGNATURE      %r" % sig)
    print("  HC_CFG_LAYOUT_ID   %s" % layout)
    print("  live-Burn deadline %d ms\n" % deadline)

    check("the signature is a rusEFI identity", sig.startswith("rusEFI "), sig)
    check("the signature CARRIES the page layout id", layout in sig.upper(),
          "carries %s" % layout if layout in sig.upper()
          else "%s NOT in %r" % (layout, sig))

    # ------------------------------------------- every generated .ini agrees
    # ANY .ini THE GENERATOR CURRENTLY WRITES must declare THIS signature.
    # The generator's own output stems are derived from TGT_VERSIONTXT, so the
    # set is read from the generator rather than guessed, and the historical
    # files beside them - which are frozen evidence of older builds - are left
    # exactly alone.
    import gen_ts_ini_me711 as G                                # noqa: E402
    generated = [G.OUT, G.OUT_VERSIONED, G.OUT_FORENSIC, G.OUT_FALLBACK]
    seen = 0
    for p in generated:
        if not p.exists():
            check("the generator's own output %s exists" % p.name, False,
                  "run py tools/tunerstudio/gen_ts_ini_me711.py")
            continue
        sigs = ini_signatures(p)
        if not sigs:
            continue
        seen += 1
        check("%s declares the firmware's signature in every section" % p.name,
              set(sigs.values()) == {sig},
              " / ".join("%s=%r" % kv for kv in sorted(sigs.items())))
        m = re.search(r"^\s*blockReadTimeout\s*=\s*(\d+)",
                      p.read_text(errors="replace"), re.M)
        if m:
            check("%s outwaits the live-Burn deadline" % p.name,
                  int(m.group(1)) > deadline,
                  "blockReadTimeout %s ms vs deadline %d ms"
                  % (m.group(1), deadline))
    check("there was at least one generated .ini to check", seen > 0,
          "%d checked" % seen)

    if DASH.exists():
        m = re.search(r'firmwareSignature="([^"]*)"',
                      DASH.read_text(errors="replace"))
        check("the generated .dash is bound to the same signature",
              bool(m) and m.group(1) == sig,
              m.group(1) if m else "no firmwareSignature")

    # ------------------------------------------------------------ the control
    print("\n  --- the control: the two files that met on the bench ---")
    if not (V48_INI.exists() and V59_INI.exists()):
        check("both frozen .ini files are present", False,
              "%s / %s" % (V48_INI.name, V59_INI.name))
    else:
        a, b = page_offsets(V48_INI), page_offsets(V59_INI)
        moved = {k: (a[k], b[k]) for k in a if k in b and a[k] != b[k]}
        check("V48 and V59 really do disagree about page offsets",
              len(moved) > 0, "%d fields moved" % len(moved))
        check("and pinCrank is one of them - the field that refused the Burn",
              moved.get("pinCrank") is not None,
              "V48 %s -> V59 %s" % moved.get("pinCrank", ("?", "?")))
        sa = ini_signatures(V48_INI).get("TunerStudio")
        sb = ini_signatures(V59_INI).get("TunerStudio")
        check("THE DEFECT: they declared the SAME signature anyway",
              sa == sb and sa is not None, "%r / %r" % (sa, sb))
        check("and the current signature matches NEITHER, so neither can "
              "connect", sig not in (sa, sb),
              "%r vs %r" % (sig, sa))

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("SIGNATURE/LAYOUT PROOF FAILED")
        return 1
    print("SIGNATURE/LAYOUT PROOF PASSES - an .ini generated for a different "
          "page\nlayout cannot answer to this firmware's signature.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
