#!/usr/bin/env python3
"""Gate: the logger's window reads the logger's real lines the right way.
A wrong reading is a Continue that answers the wrong question."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402
import hc_logger_app as A  # noqa: E402

VECTORS = [
    ("[    0.00] >>> Where is the KKL plugged in RIGHT NOW?", ("log",)),
    ("[    0.00]       [Enter] = OBD        d = DIRECT ECU", ("cable", "OBD")),
    ("[    0.00]       [Enter] = DIRECT ECU        d = OBD", ("cable", "DIRECT ECU")),
    ("[   50.70] >>> SAFETY: gear in NEUTRAL (or P), handbrake ON, nobody near the engine bay or the throttle body.", ("warn",)),
    ("[   50.70] >>> THROTTLE TEST, ENGINE OFF: the throttle plate WILL MOVE to both stops. Hands clear - press ENTER to start (s + ENTER skips)",
     ("prompt", ("THROTTLE TEST, ENGINE OFF: the throttle plate WILL MOVE to both stops. Hands clear - click Continue to start", True))),
    ("[   50.70] >>> Press ENTER when the key is ON and the engine is OFF",
     ("prompt", ("Click Continue when the key is ON and the engine is OFF", False))),
    ("[   50.70] >>> Turn the KEY ON and START the engine, ENTER when it runs",
     ("prompt", ("Turn the KEY ON and START the engine, Continue when it runs", False))),
    ("[   50.70] >>> Turn the KEY OFF now and press ENTER (s skips)",
     ("prompt", ("Turn the KEY OFF now and click Continue", True))),
    ("[   21.44] >>> Press Enter to try OBD again (s + Enter: skip)",
     ("prompt", ("Click Continue to try OBD again", True))),
    ("[   50.70] PHASE 3: ELECTRONIC THROTTLE, ENGINE OFF", ("phase", "ELECTRONIC THROTTLE, ENGINE OFF")),
    ("[    6.23] === PHASE 3: ENGINE RUNTIME FLIGHT RECORDER ===", ("phase", "ENGINE RUNTIME FLIGHT RECORDER")),
    ("[   24.01] Throttle at key-on: FAIL - page dbwEnable On; FAULT, faults pedal range",
     ("check", ("Throttle at key-on", "FAIL", "page dbwEnable On; FAULT, faults pedal range"))),
    ("[   10.68] K-line: PASS - connected over OBD", ("check", ("K-line", "PASS", "connected over OBD"))),
    ("[   46.63] RUNTIME: PASS - profile max", ("check", ("RUNTIME", "PASS", "profile max"))),
    ("[   70.81] BURN (throttle calibration passed (phase 3)): OK - in flash",
     ("check", ("Burn: throttle calibration passed (phase 3)", "PASS", "OK - in flash"))),
    ("[   72.43] BURN (x): FAILED (not verified)", ("check", ("Burn: x", "FAIL", "FAILED (not verified)"))),
    ("[   52.61] AUTOCAL: PASS - DIRECTION A: POSITION CAPTURED", ("log",)),
    ("[    4.86] KLINE: OBD path PASS", ("log",)),
    ("[   51.17] ETB: AUTOCAL: REST", ("log",)),
    ("[   72.43]     START THE ENGINE NOW: crank until it runs (max 10 s per attempt).", ("info",)),
    ("SESSION ZIP (bring this back): guided.zip", ("zip", "guided.zip")),
    ("[    7.57] RUNTIME: recording - key-on, crank, run, stop: anything. Press ENTER (or Ctrl+C) to finish.", ("log",)),
]


def main() -> int:
    fails = 0
    for line, want in VECTORS:
        got = A.classify(line)
        ok = got[0] == want[0] and (len(want) == 1 or got[1] == want[1])
        fails += not ok
        print("  [%s] %-60s %s" % ("PASS" if ok else "FAIL", line[:60], "" if ok else got))
    # every prompt of a real session is a prompt: a missed one hangs the test
    real = ROOT.parent / "evidence/BENCH_20261105_DC/logger_kit_test2/guided.txt"
    if real.exists():
        lines = real.read_text(encoding="utf-8", errors="replace").splitlines()
        want = sum(">>> " in l and "SAFETY" not in l and "Where is the KKL" not in l for l in lines)
        got = sum(A.classify(l)[0] == "prompt" for l in lines)
        ok = want == got and want > 5
        fails += not ok
        print("  [%s] real session: %d prompts read of %d" % ("PASS" if ok else "FAIL", got, want))
    print("%d checks, %d failed" % (len(VECTORS), fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
