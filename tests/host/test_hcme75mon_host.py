"""Compile and run the ME7.5 DC monitor core (hcme75mon.c) host test through
host_c_test.py, plus mutation controls, plus a cross-check of the C tables
against the archived 05.12 decode (wd_table_0512.py) when it is present.
"""
from __future__ import annotations

import re
import runpy
import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import host_c_test as H


SOURCE = H.HCP.find("hcme75mon.c")
TEST = H.HOST_TESTS / "test_hcme75mon.c"
DECODE = (H.ROOT.parent / "archive" / "me75_target_2026-10-06" / "tools" /
          "wd_ref" / "wd_table_0512.py")

MUTANTS = {
    # answer in the next TX slot instead of two later (one-deep pipeline)
    "one_deep": ("    m->next = resp[q];                          /* sent two TX slots later */",
                 "    m->cur = resp[q];"),
    # edges accepted before our pulse ended (our own pulse would be a question)
    "edges_any_slot": ("    if (!m->listen) return;                     /* our own pulse, startup */",
                       "    if (0) return;"),
    # ASync1 twice instead of ASync1, ASync2 (what ran on the bench in 2026-08)
    "no_async2": ("    m->next = HCME75MON_ASYNC2;", "    m->next = HCME75MON_ASYNC;"),
    # a question right after our answer is lost (listen only in the RX slot)
    "rx_slot_only": ("    if (m->phase == HCME75MON_PH_START) return;\n    m->listen = 1u;",
                     "    if (m->phase == HCME75MON_PH_START) return;\n    m->listen = 0u;"),
    # no startup silence
    "no_silence": ("        if (el < HCME75MON_START_REM) return 0u;", "        ;"),
    # window upper edge inclusive
    "window_edge": ("w >= HCME75MON_WIN_HI) return", "w > HCME75MON_WIN_HI) return"),
}


def cross_check_decode() -> bool:
    if not DECODE.exists():
        print("SKIP: archived decode not present (%s)" % DECODE)
        return True
    d = runpy.run_path(str(DECODE))
    src = SOURCE.read_text()
    resp = [int(x, 16) for x in re.findall(r"0x([0-9A-F]{4})u",
            src.split("resp[16] = {")[1].split("};")[0])]
    want = [d["RESPONSE"][n] for n in range(1, 17)]
    ok = resp == want
    hdr = (SOURCE.parent / "hcme75mon.h").read_text()
    for name, key in (("WIN_LO", "BAND_MIN"), ("WIN_HI", "BAND_MAX")):
        m = re.search(r"HCME75MON_%s\s+0x([0-9A-F]+)u" % name, hdr)
        ok = ok and m is not None and int(m.group(1), 16) == d[key]
    print(("PASS" if ok else "FAIL") + ": C tables vs archived 05.12 decode")
    return ok


def mutant_fails(cc, env, name, old, new) -> bool:
    mutant = Path(tempfile.gettempdir()) / ("hcme75mon_mutant_%s.c" % name)
    src = SOURCE.read_text()
    assert src.count(old) == 1, "mutation point moved - update the control: %s" % name
    mutant.write_text(src.replace(old, new))
    exe = H.TMP / ("hc_hcme75mon_mutant_%s.exe" % name)
    H.build(cc, env, [mutant, TEST], H.SHARED, exe, flags=("-w",))
    r = subprocess.run([str(exe)], env=env, capture_output=True, text=True)
    return r.returncode != 0


def main() -> int:
    if not cross_check_decode():
        return 1
    ran = H.run("hcme75mon", [SOURCE, TEST])
    if ran is None:
        return 0
    cc, env = ran
    bad = [n for n, (o, w) in MUTANTS.items() if not mutant_fails(cc, env, n, o, w)]
    if bad:
        print("FAIL: mutants not detected: %s" % ", ".join(bad))
        return 1
    print("PASS: %d mutation controls fail as they must" % len(MUTANTS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
