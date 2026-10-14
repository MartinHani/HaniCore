#!/usr/bin/env python3
r"""
ts_ini_ux_contract_proof.py - the TunerStudio UX defects found in REAL
TunerStudio use (2026-10-01), held mechanically against the generated .ini.

    py tests\tunerstudio\ts_ini_ux_contract_proof.py [<ini>]

  1. TUNE ANALYZE: a veAnalyzeMap / wueAnalyzeMap activeCondition may name
     only PAGE settings ([Constants]), never an output channel. With
     `{ lambda1Valid }` TunerStudio re-evaluated the condition on switching
     analyzers, found no active VE map without a valid lambda, and greyed the
     VE tab for good. rusEFI's condition is a page setting
     (useLambdaOnInterface); HaniCore's is `lambda1Source != 0`.
  2. VE RANGE: the VE table holds at least 255 % (it stopped at 127.5 % - a
     U08 at 0.5 % per count).
  3. TROUBLE CODES: one list - no ACTIVE / STORED panel pair, each row a
     status + "Pxxxx - description" in ONE full-width indicator (split
     columns shrank the code text to unreadable in TunerStudio 3.3.01), and
     the freeze frame's code as a P-code, not the raw number. 2026-10-11:
     ONE ROW PER CODE the firmware can set (ts_dtc_me711.DTC_PATHS), shown
     while its bit of dtcStoredMask is set - four slots hid every code after
     the fourth (owner: "more than ~5 are not visible").
Each check has a mutation control: the defect put back into a copy of the
.ini must be caught.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INI = ROOT / "tunerstudio/hanicore_me711.ini"


def sections(text):
    out, cur = {}, None
    for line in text.splitlines():
        s = line.split(";")[0].strip()
        m = re.match(r"^\[(\w+)\]$", s)
        if m:
            cur = m.group(1)
            out.setdefault(cur, [])
        elif cur and s:
            out[cur].append(s)
    return out


def names(sec, kinds):
    got = set()
    for s in sec:
        m = re.match(r"^(\w+)\s*=\s*(\w+)", s)
        if m and (kinds is None or m.group(2) in kinds):
            got.add(m.group(1))
    return got


def audit(text):
    sec = sections(text)
    consts = names(sec.get("Constants", []), {"scalar", "bits", "array",
                                              "string"})
    chans = names(sec.get("OutputChannels", []), None)
    bad = []
    # 1. analyzer activeConditions
    for part in ("VeAnalyze", "WueAnalyze"):
        maps = [s for s in sec.get(part, []) if s.startswith(
            ("veAnalyzeMap", "wueAnalyzeMap"))]
        if not maps:
            bad.append("%s: no analyze map" % part)
        for s in maps:
            conds = re.findall(r"\{([^}]*)\}", s)
            used = set(re.findall(r"[A-Za-z_]\w*", " ".join(conds)))
            live = sorted(u for u in used if u in chans or u not in consts)
            if live:
                bad.append("%s activeCondition names %s - not a page setting"
                           % (part, live))
    # 2. VE range
    ve = [s for s in sec.get("Constants", []) if s.startswith("veTable ")]
    if not ve:
        bad.append("veTable not declared")
    else:
        f = [x.strip() for x in ve[0].split(",")]
        typ, scale, hi = f[1], float(f[5]), float(f[8])
        top = scale * (255 if typ.startswith("U08") else 65535)
        if hi < 255 or top < 255:
            bad.append("veTable reaches only %.1f %% (max %s, scale %s)"
                       % (min(hi, top), hi, scale))
        # V98r2: the AWT alpha-N table holds 0.6..9 % cells at a closed
        # throttle; a 1 % count is a 10..100 % step there
        if scale > 0.1:
            bad.append("veTable step %.2f %% is coarser than 0.1 %%" % scale)
    # 3. the DTC dialog
    ui = "\n".join(sec.get("UiDialogs", []))
    m = re.search(r"dialog = hcDiagDtc,.*?(?=\n\s*dialog =|\Z)", ui, re.S)
    dlg = m.group(0) if m else ""
    if not dlg:
        bad.append("no hcDiagDtc dialog")
    if re.search(r'"ACTIVE"|"STORED', ui):
        bad.append("an ACTIVE / STORED panel pair is back")
    sys.path.insert(0, str(ROOT / "tools" / "tunerstudio"))
    import ts_dtc_me711 as DTC
    # 2026-10-12 (owner, real TunerStudio: an EMPTY list): every code has an
    # ALWAYS-VISIBLE row - the code lit while stored, ACTIVE NOW while
    # present - tested with & and a literal mask (rusEFI's INIs use no >>).
    for i, code in enumerate(DTC.DTC_PATHS):
        w, k = ("0", i) if i < 16 else ("1", i - 16)
        if not re.search(r'indicator = \{\s*\(dtcStoredMask%s & %d\) != 0\s*\},'
                         r'\s*"P%04d - ' % (w, 1 << k, code), ui):
            bad.append("no row for stored code P%04d (path %d)" % (code, i))
            break
        if not re.search(r"indicator = \{\s*\(dtcActiveMask%s & %d\) != 0"
                         % (w, 1 << k), ui):
            bad.append("no ACTIVE cell for code P%04d (path %d)" % (code, i))
            break
    # NO dialog panel/field may be SHOWN on a live (ECU-sent) channel:
    # TunerStudio does not evaluate that, the panel never appears (the
    # empty DTC list). Command buttons and indicators are evaluated live.
    raw = names(sec.get("OutputChannels", []), {"scalar", "bits"})
    derived = {}
    for s in sec.get("OutputChannels", []):
        m = re.match(r"^(\w+)\s*=\s*\{(.*)\}", s)
        if m:
            derived[m.group(1)] = m.group(2)

    def live(n, seen=()):
        if n in consts:
            return False
        if n in raw:
            return True
        if n in derived and n not in seen:
            return any(live(x, seen + (n,))
                       for x in re.findall(r"[A-Za-z_]\w*", derived[n]))
        return False
    for s in sec.get("UiDialogs", []):
        if not re.match(r"(panel|field)\s*=", s):
            continue
        for cond in re.findall(r"\{([^}]*)\}", s):
            ln = [n for n in set(re.findall(r"[A-Za-z_]\w*", cond)) if live(n)]
            if ln:
                bad.append("a dialog element is shown on live channel(s) %s: %s"
                           % (sorted(ln), s[:70]))
                break
    if "bitStringValue(hcDtcList, dtcFfIdx)" not in ui:
        bad.append("the freeze frame's code is not shown as a P-code")
    if "dtcFfCodeGauge" in ui:
        bad.append("the freeze frame's raw code gauge is shown")
    return bad


def main() -> int:
    ini = Path(sys.argv[1]) if len(sys.argv) > 1 else INI
    text = ini.read_text(errors="replace")
    print("=== TunerStudio UX contract (real-TunerStudio findings) ===")
    bad = audit(text)
    for b in bad:
        print("  [FAIL] " + b)
    muts = [
        ("analyze activeCondition on a live channel",
         re.sub(r"(veAnalyzeMap = [^\n{]*)\{[^}\n]*\}", r"\1{ lambda1Valid }",
                text, count=1)),
        ("VE back to 0.5 % a count",
         re.sub(r'(veTable\s*=\s*array,\s*)U16(,\s*\d+,\s*\[16x16\],\s*"%",\s*)'
                r'0\.1,(\s*0,\s*0,\s*)400(\.0)?', r'U08\g<2>0.5,\g<3>127.5',
                text, count=1)),
        ("VE back to 1 % a count (V98)",
         re.sub(r'(veTable\s*=\s*array,\s*)U16(,\s*\d+,\s*\[16x16\],\s*"%",\s*)'
                r'0\.1,(\s*0,\s*0,\s*)400(\.0)?', r'U08\g<2>1,\g<3>255',
                text, count=1)),
        ("DTC list shown on a live channel again",
         re.sub(r"(\n\s*panel = hcDtcBoard)", r"\1, {1}, { dtcStoredN > 0 }",
                text, count=1)),
        ("DTC list back to four rows",
         re.sub(r'\n\s*indicator = \{\s*\(dtcStoredMask1[^\n]*', "", text)),
        ("DTC freeze frame as a raw number",
         text.replace("bitStringValue(hcDtcList, dtcFfIdx)", "dtcFfCode")),
    ]
    ctl_ok = True
    for name, mtext in muts:
        caught = mtext != text and len(audit(mtext)) > len(bad)
        ctl_ok &= caught
        print("  control: %-44s %s" % (name, "CAUGHT" if caught
                                       else "NOT CAUGHT - gate blind"))
    ok = not bad and ctl_ok
    print("UX CONTRACT PROOF %s" % ("PASSES" if ok else "FAILS"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
