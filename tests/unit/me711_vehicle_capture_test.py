#!/usr/bin/env python3
r"""
me711_vehicle_capture_test.py - the vehicle capture tool against a scripted
fake ECU on a virtual clock. No serial port, no hardware.

    py tests\unit\me711_vehicle_capture_test.py

Cases: ECU absent at start then appears; dropped responses below the offline
threshold; offline + reboot (boot counter moves); signature mismatch; V1.2's
observed ENGINE SESSION on a keyed car (crank -> catch -> run -> key off with
run-on and silence -> key on again with a reset -> a failed crank -> a stall),
attempt outcomes, counter deltas summed across the reset, syncState decoded
as trg_state;
CSV / JSONL / metadata integrity; Ctrl+C mid-session keeps a summary; the
tool refuses to send any command outside the read-only set; and the per-cycle
wire budget at 57600 baud.
"""
from __future__ import annotations

import binascii
import os
import csv
import json
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_vehicle_capture as V      # noqa: E402

# V1.2: the CURRENT image's .ini - the session checks need its channels
# (toothCorrections, cycleSync*, toothLogState).
import me711_image as _PI    # noqa: E402
INI = ROOT / "tunerstudio" / ("hanicore_me711_%s.ini"
                                    % _PI.STEM.split("HaniCore_ME711_", 1)[1])
# V87: run the same cases against another image's .ini / version text, e.g.
#   set HC_CAPTURE_INI=tunerstudio\history\hanicore_me711_v87_preset_apply.ini
#   set HC_CAPTURE_VER=HaniCore V87 PRESET APPLY / Bosch ME7.1.1
if os.environ.get("HC_CAPTURE_INI"):
    INI = Path(os.environ["HC_CAPTURE_INI"])
# the fake ECU announces the version text of the image built in this tree, so
# the identity lookup finds that build's manifest (build first)
VER = os.environ.get("HC_CAPTURE_VER") or (
    _PI.metadata().get("version_text", "") if _PI.MANIFEST.exists() else "")
CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class FakeECU:
    """Speaks the envelope; answers S, V, O, R. `script(t)` sets state."""

    def __init__(self, clock, ini, sig=None, ver=VER):
        self.c = clock
        self.ini = ini
        self.sig = sig or ini.signature
        self.ver = ver
        self.online = False
        self.drop_next = 0
        self.vals = {"rstBootCount": 1, "battDv": 125, "rpm": 0, "syncState": 0,
                     "runOn": 0, "tickMs": 0}
        self.out = b""
        self.sent = []
        self.script = None

    def blob(self, off, cnt):
        b = bytearray(self.ini.block)
        for n, v in self.vals.items():
            if n in self.ini.scalars:
                typ, o, *_ = self.ini.scalars[n]
                w = V.SIZES[typ]
                b[o:o + w] = int(v).to_bytes(w, "big", signed=typ[0] == "S")
        return bytes(b[off:off + cnt])

    def write(self, req):
        if self.script:
            self.script(self)
        # wire time: request out + its echo back
        self.c.t += len(req) * 10 / 57600.0
        n = (req[0] << 8) | req[1]
        pl = req[2:2 + n]
        self.sent.append(pl[:1])
        self.out = req                            # the K-line echo
        if not self.online:
            return
        if self.drop_next:
            self.drop_next -= 1
            return
        cmd = pl[:1]
        if cmd in (b"S", b"Q"):
            body = self.sig.encode() + b"\0"
        elif cmd == b"V":
            body = self.ver.encode() + b"\0"
        elif cmd == b"O":
            off = int.from_bytes(pl[1:3], "big")
            cnt = int.from_bytes(pl[3:5], "big")
            body = self.blob(off, cnt)
        elif cmd == b"R":
            body = bytes(int.from_bytes(pl[3:5], "big"))
        else:
            return
        blob = b"\0" + body
        self.out += (len(blob).to_bytes(2, "big") + blob
                     + (binascii.crc32(blob) & 0xFFFFFFFF).to_bytes(4, "big"))
        self.c.t += len(self.out) * 10 / 57600.0 + 0.002

    def read(self, n):
        if not self.out:
            self.c.t += 0.05
            return b""
        r, self.out = self.out[:n], self.out[n:]
        return r

    def close(self):
        pass


def args(**kw):
    a = types.SimpleNamespace(port="FAKE", baud=57600, ini=str(INI), out=None,
                              auto=True, steps=None, offline_wait=5.0)
    for k, v in kw.items():
        setattr(a, k, v)
    return a


def events(cap):
    return [json.loads(l) for l in
            (cap.dir / "events.jsonl").read_text().splitlines()]


def run_capture(tmp, ecu, clock, **kw):
    cap = V.Capture(args(**kw), transport=ecu, stdin_q=None, clock=clock,
                    sleep=clock.sleep, out_root=tmp)
    try:
        cap.run()
    except KeyboardInterrupt:
        cap.event("INTERRUPTED")
    finally:
        cap.meta["ended_utc"] = V.utc()
        cap.write_meta()
        (cap.dir / "summary.txt").write_text(V.summarize(cap))
        for f in (cap.csv, cap.full_csv):
            if f:
                f[0].close()
        for f in (cap.console, cap.frames, cap.events):
            f.close()
    return cap


def main() -> int:
    ini = V.Ini(INI)
    print("=== me711_vehicle_capture against a scripted fake ECU ===")
    print("  ini %s  block %d  %d scalars, %d computed\n"
          % (INI.name, ini.block, len(ini.scalars), len(ini.computed)))
    tmp = Path(tempfile.mkdtemp(prefix="vcap_test_"))

    # ---------------------------------------------- 1. a full auto session
    c = Clock()
    e = FakeECU(c, ini)
    t0 = c.t
    state = {"phase": 0}

    def script(ecu):
        t = c.t - t0
        ecu.online = t > 3.0 and not (state.get("gone"))
        ecu.vals["tickMs"] = int((t * 1000) % 65536)
        steps = [s["step"] for s in capture_ref[0].meta["steps"]] \
            if capture_ref[0] else []
        cur = steps[-1] if steps else None
        if cur == "sweep":
            ecu.vals["dbwApp1X10"] = int(abs(((t * 200) % 2000) - 1000))
        if cur == "session":
            # a keyed car: crank, catch, run, stop WITH THE KEY (run-on, then
            # silence), key on again (the ECU rebooted), a crank that does not
            # start, a start that stalls.
            k = t - state.setdefault("s_t0", t)
            ecu.online = not (10.5 < k < 13.0)
            v = ecu.vals
            v["runOn"] = 0x0101 if 8.0 < k < 13.0 else 0
            if 13.0 <= k and not state.get("rebooted"):
                state["rebooted"] = True
                v["rstBootCount"] = 2
                v["syncLossCount"] = 0
            if k < 0.5:
                v["rpm"] = 0
            elif k < 2.5:
                v["rpm"], v["syncState"], v["battDv"] = 180, 3, 98
            elif k < 8.0:
                v["rpm"], v["syncState"], v["battDv"] = 950, 3, 138
            elif k < 8.4:
                v["rpm"] = 300
            elif k < 14.0:
                v["rpm"], v["syncState"] = 0, 0
            elif k < 16.0:
                v["rpm"], v["syncState"] = 170, 3      # cranks, no start
            elif k < 17.0:
                v["rpm"], v["syncState"] = 0, 0
            elif k < 18.0:
                v["rpm"], v["syncState"] = 190, 3
            elif k < 20.0:
                v["rpm"] = 850                          # starts...
            elif k < 20.4:
                v["rpm"] = 250                          # ...and stalls
            else:
                v["rpm"], v["syncState"] = 0, 0
            # crank sync losses: 2 before the reboot, 1 after
            if 1.0 < k < 2.0:
                v["syncLossCount"] = 2
            if 17.5 < k:
                v["syncLossCount"] = 1
        # a dropped response in the baseline, below the offline threshold
        if cur == "baseline" and not state.get("dropped") and t > 5.0:
            state["dropped"] = True
            ecu.drop_next = 1

    capture_ref = [None]
    e.script = script
    cap = V.Capture(args(offline_wait=8.0), transport=e, stdin_q=None,
                    clock=c, sleep=c.sleep, out_root=tmp)
    # the session's auto length is its STEPS entry: 30 s covers the script
    capture_ref[0] = cap
    try:
        cap.run()
    finally:
        cap.write_meta()
        (cap.dir / "summary.txt").write_text(V.summarize(cap))
        for f in (cap.csv, cap.full_csv):
            f[0].close()
        for f in (cap.console, cap.frames, cap.events):
            f.close()
    ev = events(cap)
    kinds = [x["event"] for x in ev]
    check("ECU absent at start, then connects", "ECU_ONLINE" in kinds
          and cap.meta["connects"][0]["t_mono"] > t0 + 3.0,
          "connected at +%.1f s" % (cap.meta["connects"][0]["t_mono"] - t0))
    check("identity recorded: signature, version, local build sha",
          cap.meta["identity"]["local_build"] and
          cap.meta["identity"]["local_build"].get("sha256"),
          str(cap.meta["identity"]["local_build"])[:90])
    check("every step marker is in the event log",
          all(m in kinds for _, m, *_ in V.STEPS), "")
    check("a single dropped reply does NOT declare the ECU offline",
          kinds.count("ECU_OFFLINE") == 0 and any(
              not json.loads(l)["ok"] for l in
              (cap.dir / "frames.jsonl").read_text().splitlines()), "")
    states = [x["now"] for x in ev if x["event"] == "STATE"]
    ends = [(x["attempt"], x["outcome"]) for x in ev
            if x["event"] == "ATTEMPT_END"]
    check("session: CRANKING -> RUNNING -> RUNDOWN -> KEY_OFF -> OFFLINE",
          states[:6] == ["STOPPED", "CRANKING", "RUNNING", "RUNDOWN",
                         "KEY_OFF", "OFFLINE"], str(states[:8]))
    check("session: no 'stop cranking' prompt once the engine runs",
          "STOP CRANKING" not in (cap.dir / "console.log").read_text(), "")
    check("session: the ECU coming back after key-on is followed, not an error",
          "ECU_RESET" in kinds and kinds.count("ECU_ONLINE") >= 2
          and "GAVE_UP_WAITING" not in kinds, "")
    check("session: attempts STOPPED_BY_KEY, NO_START, STALL",
          ends == [(1, "STOPPED_BY_KEY"), (2, "NO_START"), (3, "STALL")],
          str(ends))
    check("syncState 3 is decoded as CRANK SYNC, not a cam state",
          any(x["event"] == "CHANGE" and x["channel"] == "syncState"
              and x["now"] == 3 and "CRANK SYNC" in x["text"] for x in ev), "")
    summ = (cap.dir / "summary.txt").read_text()
    check("counter delta summed across the ECU reset (2 + 1 = 3)",
          "syncLossCount  delta 3" in summ, "")
    check("summary reports each attempt with outcome and running rpm",
          "attempt 1: STOPPED_BY_KEY" in summ and "running rpm" in summ
          and "run-on" in summ, "")
    rows = list(csv.reader((cap.dir / "decoded.csv").open()))
    hdr = rows[0]
    check("decoded.csv: header + one row per fast sample, fixed width",
          len(rows) - 1 == len(cap.rows) and all(len(r) == len(hdr)
                                                 for r in rows[1:]),
          "%d rows x %d columns" % (len(rows) - 1, len(hdr)))
    i_l = hdr.index("lambda1X1000")
    first = rows[1]
    check("a value never received is an EMPTY cell, not 0",
          hdr.index("rpm") and (first[i_l] in ("", "0", "0.0")), "")
    for fn in ("frames.jsonl", "events.jsonl"):
        ok = all(json.loads(l) is not None for l in
                 (cap.dir / fn).read_text().splitlines())
        check("%s parses line by line" % fn, ok, "")
    md = json.loads((cap.dir / "metadata.json").read_text())
    check("metadata.json has steps with start/end times",
          len(md["steps"]) == len(V.STEPS)
          and all("end_mono" in s for s in md["steps"]), "")
    check("only read-only commands went on the wire",
          set(e.sent) <= {b"S", b"Q", b"V", b"O", b"R"},
          "sent %s" % sorted(set(x.decode() for x in e.sent)))

    # ------------------------------------------ 2. offline + reboot
    c = Clock()
    e = FakeECU(c, ini)
    e.online = True
    st2 = {"n": 0}

    def script2(ecu):
        st2["n"] += 1
        if 40 < st2["n"] < 60:
            ecu.online = False
        elif st2["n"] >= 60:
            ecu.online = True
            ecu.vals["rstBootCount"] = 2
    e.script = script2
    cap = run_capture(tmp, e, c, steps=["baseline", "released", "full"],
                      offline_wait=30.0)
    # (steps without the session: an ECU loss there still waits and resumes)
    kinds = [x["event"] for x in events(cap)]
    check("communication loss is ECU_OFFLINE (no key-off seen)",
          "ECU_OFFLINE" in kinds, "")
    check("the ECU returning with a new boot count is ECU_RESET",
          "ECU_RESET" in kinds and len(cap.meta["connects"]) >= 2, "")

    # ------------------------------------------ 3. signature mismatch
    c = Clock()
    e = FakeECU(c, ini, sig="rusEFI HaniCore ME711 DEADBEEF")
    e.online = True
    cap = V.Capture(args(), transport=e, stdin_q=None, clock=c, sleep=c.sleep,
                    out_root=tmp)
    ok = cap.try_connect()
    check("a signature no local .ini declares is refused, not guessed",
          not ok and not cap.online, "")

    # ------------------------------------------ 4. Ctrl+C mid-session
    c = Clock()
    e = FakeECU(c, ini)
    e.online = True
    cnt = {"n": 0}

    def script4(ecu):
        cnt["n"] += 1
        ecu.vals["lambda1X1000"] = 700 + cnt["n"]    # changes every request
        if cnt["n"] == 80:
            raise KeyboardInterrupt
    e.script = script4
    (tmp / "s4").mkdir()          # its own folder: a capture started in the
    cap = run_capture(tmp / "s4", e, c)   # same second would share one
    check("Ctrl+C mid-session still leaves a summary and flushed CSV",
          (cap.dir / "summary.txt").exists() and
          len((cap.dir / "decoded.csv").read_text().splitlines()) > 5, "")

    # ------------------------------------------ 4b. AUX interleave explicit
    import csv as _csv
    rows = [r for r in _csv.DictReader((cap.dir / "decoded.csv").open())
            if r.get("t_mono") != "t_mono"]        # a reconnect re-heads
    parts = [r["aux_part"] for r in rows if r.get("aux_part", "") != ""]
    in_step = all(int(r["aux_part"]) == (int(r["cycle"]) - 1) % V.AUX_SPLIT
                  for r in rows if r.get("aux_part", "") != "")
    meta = json.loads((cap.dir / "metadata.json").read_text())
    il = meta.get("aux_interleave", {})
    check("AUX interleave: aux_part rotates 0..%d and metadata names each "
          "slice's window" % (V.AUX_SPLIT - 1),
          len(parts) > 6 and set(parts) == {str(k) for k in range(V.AUX_SPLIT)}
          and in_step
          and il.get("slices") == V.AUX_SPLIT and len(il.get("windows", [])) == V.AUX_SPLIT,
          "parts %s, slices %s" % ("".join(parts[:9]), il.get("slices")))
    f2 = [r for r in rows if r.get("rtt_fast2_ms", "") != ""]
    check("FAST2 (DBW terms, sequential state, transient fuel) fresh on "
          "EVERY row, and its channels are columns",
          len(rows) > 6 and len(f2) == len(rows)
          and all(c in rows[0] for c in ("seqActive", "transCorrUs",
                                          "dbwTermP", "injWidthUs")),
          "%d of %d rows, window %s" % (len(f2), len(rows),
                                         meta.get("fast2_window")))
    f3 = meta.get("fast3_window")
    full3 = [r for r in rows if r.get("RPMValue", "") != ""
             and r.get("targetLambda", "") != ""]
    check("V1.8: the V98 fast block is read on EVERY row (rpm, target "
          "lambda, trims are columns with a value)",
          f3 == [V.FAST3_START, V.FAST3_END - V.FAST3_START] and len(rows) > 6
          and len(full3) == len(rows)
          and all(c in rows[0] for c in ("stftBank1", "engineFlags",
                                          "ignitionTiming")),
          "%d of %d rows, window %s" % (len(full3), len(rows), f3))
    need = [c for c in ("knockState", "knockCnt1", "knockRetardX10",
                        "vvt1State", "vvt2State", "celState")
            if c in V.Ini(INI)
                   .scalars]
    check("V1.7: knock, VVT and CEL channels are decoded.csv columns",
          len(need) == 6 and all(c in rows[0] for c in need),
          "declared %s, missing %s" % (need, [c for c in need
                                            if c not in rows[0]]))
    lam = [r.get("lambda1X1000", "") for r in rows]
    fresh = sum(1 for a, b in zip(lam, lam[1:]) if a != "" and a != b)
    check("V1.6: lambda (734..739) fresh on EVERY row, not one AUX slice in "
          "%d (the value the ECU changes differs row to row)" % V.AUX_SPLIT,
          len(rows) > 6 and fresh == len(rows) - 1
          and meta.get("lambda_window") == [734, 6]
          and all(c in rows[0] for c in ("lambda2X1000", "lambdaStatus")),
          "%d of %d row pairs changed, window %s"
          % (fresh, len(rows) - 1, meta.get("lambda_window")))
    ages = [float(r["aux_age_s"]) for r in rows[V.AUX_SPLIT + 2:]
            if r.get("aux_age_s", "") != ""]
    # 0 only on rows where the 2 s whole-block read refreshed every slice
    check("aux_age_s is the OLDEST slice's age (>= one cycle between full reads)",
          ages and min(ages) >= 0.0 and sum(1 for a in ages if a > 0) > len(ages) // 2,
          "%d of %d rows > 0, max %.3f s" % (sum(1 for a in ages if a > 0),
                                              len(ages), max(ages)) if ages else "none")

    # ------------------------------------------ 5. write commands refused
    lk = V.Link(FakeECU(Clock(), ini), open(tmp / "x.jsonl", "w"))
    refused = []
    for bad in (b"W\x00\x10\x01", b"B\x00\x00", b"!T\x01\x01", b"!X"):
        try:
            lk.request(bad, 0.1)
            refused.append(False)
        except RuntimeError:
            refused.append(True)
    check("W (page write), B (burn), !T (bench test), !X are refused in code",
          all(refused), str(refused))

    # ------------------------------------------ 6. wire budget
    # AUX runs to the END of the block since V1.1 - price the LARGEST block
    # of any generated .ini, not a number typed here.
    blocks = [V.Ini(pp).block for pp in V.TS_DIR.glob("hanicore_me711_v*.ini")
              if not pp.stem.endswith(("_forensic", "_fallback"))]
    # V1.7: price EVERY read of one cycle through the logger's own window
    # functions (until V1.6 this modelled FAST + one AUX third and never
    # counted FAST2 (V1.5) or the lambda window (V1.6)). Each read = its
    # bytes + 7 request + 11 envelope. The honest rate at 57600 is ~8 Hz
    # since V1.5; the link runs 115200 with the plugin.
    big = max((V.Ini(pp) for pp in V.TS_DIR.glob("hanicore_me711_v*.ini")
               if not pp.stem.endswith(("_forensic", "_fallback"))),
              key=lambda i: i.block)
    reads = [V.FAST[1], V.fast2_window(big)[1], V.fast3_window(big)[1],
             V.lam_window(big)[1],
             max(V.aux_window(big, k)[1] for k in range(V.AUX_SPLIT))]
    wire = sum(n + 18 for n in reads if n)
    cyc = wire * 10 / 115200.0
    # V1.8: the V98 fast block (88 bytes) is read every row too; at 57600
    # that is ~7 Hz, so the budget is stated at the plugin's 115200
    # (measured on the bench: 83 fast-block reads/s)
    check("one FAST+FAST2+FAST3+lambda+AUX cycle fits ~14 Hz at 115200 "
          "(block %d)" % big.block,
          cyc < 0.075, "%d bytes on the wire = %.0f ms/cycle at 115200, "
          "%.0f ms at 57600, reads %s" % (wire, cyc * 1000,
                                          wire * 10 / 57.6, reads))
    f3 = V.fast3_window(big)
    tail = [V.aux_window(big, k) for k in range(V.AUX1_SLICES + 1, V.AUX_SPLIT)]
    covered = [o for a, n in tail for o in range(a, a + n)]
    check("V1.9: the fast block (1136..1223, 88 bytes) is its own every-row "
          "window; OCH2 stops where it starts; the block tail is AUX, whole",
          f3 == (V.FAST3_START, 88) and V.FAST3_END == 1224
          and V.fast2_window(big)[0] + V.fast2_window(big)[1] <= V.OCH2_START
          and V.aux_window(big, V.AUX1_SLICES)
          == (V.OCH2_START, V.FAST3_START - V.OCH2_START)
          and covered == list(range(V.FAST3_END, big.block)),
          "fast3 %s, OCH2 slice %s, tail %s"
          % (f3, V.aux_window(big, V.AUX1_SLICES), tail))

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
