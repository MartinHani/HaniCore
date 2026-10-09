#!/usr/bin/env python3
r"""
me711_baro_honesty_proof.py - the ambient-pressure conversion cannot quietly
go back to claiming more than it knows.

    py tests\firmware\engine\me711_baro_honesty_proof.py [path/to/hanicore_me711_*.ini]

WHY THIS EXISTS, AND WHY IT IS A GATE RATHER THAN A PARAGRAPH.

On 2026-09-05 real TunerStudio showed BARO = 1.22 bar against a local
barometric pressure of 1000.6 hPa - about +22 %. Three separate mistakes were
available and this project made two of them:

  1. THE WINDOW. The ASIC frame window sat four words early, so `baroRaw` was
     not the ambient channel at all. Fixed at V61; `s5500Base == 4` is the
     condition, and `baroWindowOk` publishes it.
  2. THE TRANSFER FUNCTION. The old expression
     `((baroRaw * 6080.0) / 256.0 + 7040.0) * 0.0390625` implied a `baroRaw`
     of about 1019 of 1023 - a sensor pinned at its rail - for an ordinary
     day. It was refuted, not tuned.
  3. THE ONE NOBODY HAS MADE AND THIS GATE EXISTS TO PREVENT: deriving the
     scale by matching raw counts to a number from a weather website.
     Sea-level pressure is not local absolute pressure, and a scale fitted to
     one reading on one day is a fiction that will read plausibly for ever.

The current scale comes from a SIBLING calibration (A1104F: DSUGRAD 16192 =
253.0 hPa/V, DSUOFS 0) and the project rules establish that **no A2L, DAMOS or
XDF in this repository maps the binary this ECU runs.** So the number is
defensible and it is NOT exact-target, and the .ini has to keep saying so.

WHAT THIS GATE CHECKS is that the honesty survives an edit: the mask, the
window condition, the plausibility band, the sibling-derived scale and - above
all - the words that mark it as not-exact. It does not check that the pressure
is CORRECT. Nothing can, until somebody measures this board against a
reference barometer.

The analysis that produced all of this is tests/firmware/engine/me711_ambient_pressure.py,
which is a document and is not run by anything. That is precisely why the
conclusions needed a gate.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_image as PI                     # noqa: E402

# The sibling-calibration scale, hPa per count: 253.0 hPa/V * (5/1024) V/count.
SIBLING_HPA_PER_COUNT = 253.0 * 5.0 / 1024.0     # 1.23535...
TOL = 0.001

# The refuted expression, kept so the negative control is the REAL defect
# rather than an invented one.
REFUTED = "((baroRaw * 6080.0) / 256.0 + 7040.0) * 0.0390625"

CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print("  [%s] %-56s %s" % ("PASS" if ok else "FAIL", name, detail))


def expr_of(text, name):
    """The { ... } body of an .ini expression channel, or None."""
    m = re.search(r"^\s*%s\s*=\s*\{([^}]*)\}" % re.escape(name), text, re.M)
    return m.group(1).strip() if m else None


def comment_of(text, name):
    m = re.search(r"^\s*%s\s*=.*?;(.*)$" % re.escape(name), text, re.M)
    return m.group(1).strip() if m else ""


def audit(text):
    """Every verdict, over one .ini's text. Separated from main() so the
    negative controls below can feed it a mutated file."""
    out = []

    raw = expr_of(text, "baroRaw")
    out.append(("baroRaw is masked to the ADC's real 10 bits",
                raw is not None and "1023" in raw,
                raw or "channel missing"))

    win = expr_of(text, "baroWindowOk")
    out.append(("the S5500 window position is published, not assumed",
                win is not None and "s5500Base" in win and "4" in win,
                win or "channel missing"))

    pl = expr_of(text, "baroPlausible")
    out.append(("a rail reading is called implausible rather than reported",
                pl is not None and "baroRaw" in pl
                and re.search(r"<\s*10[0-9][0-9]", pl) is not None,
                pl or "channel missing"))

    ap = expr_of(text, "ambientPressure")
    scale = None
    if ap:
        m = re.search(r"baroRaw\s*\*\s*([0-9]*\.?[0-9]+)", ap)
        if m:
            scale = float(m.group(1))
    out.append(("the scale is the SIBLING-derived one, to 0.001 hPa/count",
                scale is not None
                and abs(scale - SIBLING_HPA_PER_COUNT) < TOL,
                "%s (want %.6f)"
                % (scale if scale is not None else ap, SIBLING_HPA_PER_COUNT)))

    cm = comment_of(text, "ambientPressure")
    out.append(("...and the .ini SAYS it is a sibling, not this target",
                "SIBLING" in cm.upper() and "NOT exact-target" in cm,
                cm[:64] or "no comment"))

    out.append(("the refuted +22% expression is gone",
                REFUTED not in text and "7040.0" not in text,
                "the 2026-09-05 expression is absent"))

    return out


def main() -> int:
    ini = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if ini is None:
        ini = ROOT / "tunerstudio" / (PI.STEM.lower() + ".ini")
    if not ini.exists():
        print("no .ini: %s\n  generate it: py tools/tunerstudio/gen_ts_ini_me711.py" % ini)
        return 2
    text = ini.read_text(errors="replace")

    print("=== HaniCore ME7.1.1 - the ambient-pressure conversion is honest ===\n")
    print("  ini   %s\n" % ini.name)

    for name, ok, detail in audit(text):
        check(name, ok, detail)

    # ===================== NEGATIVE CONTROLS =========================
    #
    # Each re-creates a defect this project actually shipped or nearly
    # shipped, and the audit above must go red for it. Without these, every
    # check is satisfied by an .ini that happens to parse.
    print("\n  --- negative controls: each must FAIL the audit above ---")

    def fails_on(label, mutate):
        muted = mutate(text)
        bad = [n for n, ok, _ in audit(muted) if not ok]
        check("CONTROL: %s" % label, bool(bad),
              ("caught by: " + bad[0][:44]) if bad else "NOT CAUGHT")

    fails_on("the refuted +22% expression returns",
             lambda t: re.sub(r"(ambientPressure\s*=\s*\{)[^}]*\}",
                              r"\1 " + REFUTED + " }", t, count=1))
    fails_on("the scale is quietly fitted to a weather website",
             lambda t: re.sub(r"(ambientPressure\s*=\s*\{\s*baroRaw\s*\*\s*)"
                              r"[0-9.]+", r"\g<1>1.241000", t, count=1))
    fails_on("the sibling provenance is dropped from the comment",
             lambda t: re.sub(r"(ambientPressure\s*=\s*\{[^}]*\}\s*);[^\n]*",
                              r"\1; ambient pressure [hPa]", t, count=1))
    fails_on("the 10-bit mask is widened to the whole word",
             lambda t: re.sub(r"(baroRaw\s*=\s*\{[^}]*)1023", r"\g<1>65535",
                              t, count=1))
    fails_on("the plausibility band is opened to the rails",
             lambda t: re.sub(r"(baroPlausible\s*=\s*\{)[^}]*\}",
                              r"\1 baroRaw >= 0 }", t, count=1))

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("BARO HONESTY FAILS - the conversion is claiming something the "
              "evidence does not support, or has stopped saying what it is.")
        return 1
    print("BARO HONESTY PASSES - masked to 10 bits, window published, rails "
          "called implausible, sibling scale declared as a sibling.")
    print("THIS IS NOT A CLAIM THAT THE PRESSURE IS CORRECT. No reference "
          "barometer has been compared against this board.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
