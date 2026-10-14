#!/usr/bin/env python3
r"""
me711_vehicle_test_test.py - offline tests of tools\vehicle\me711_vehicle_test.py
against a FAKE ECU (no serial port, no hardware).

    py tests\unit\me711_vehicle_test_test.py

The fake speaks what the real ECU speaks (hcts.c envelope + K-line echo,
the VAG/KWP entry of hckline.c, the extended window with the event ring of
hcevlog711.c) closely enough to drive every code path of the tool:

  K1  OBD path answers a direct probe: KLINE PASS, kline.csv, quality soak
  K2  OBD path dead (echo only): "OBD K-LINE CONNECTION FAILED", the prompt,
      then the DIRECT ECU path PASSES in the same session; both recorded
  K3  the KWP stages are named: no init response / IDENTIFY / GOFAST /
      timeout after the transition
  K4  malformed replies (CRC) are counted, not fatal; port reconnect works
  A1  --autocal: direction A/B "STOP REACHED", AutoCal "NOT A STOP A" is
      reported WITH the numbers (moved / limit / distance) and etb_events.csv
  R1  --runtime: fast rows, monotonic timestamps, medium + slow rows, ring
      events decoded with their reason text, a ring overflow REPORTED (lost
      count), a torn record skipped, a K-line dropout recovered and recorded
  M1  V100 multi-rate: fast > medium > slow in rate, every group's channels /
      windows / measured rate in metadata, medium.csv and slow.csv written
  M2  V100 profiles: --profile reduced polls about a quarter as often and
      leaves the EVENT RING period alone; the profile is in metadata
  M3  V100 metadata: the whole engine configuration is reconstructable from
      the session alone (strategies, trigger, cam, lambda + heater policy,
      DBW calibration, VE/ignition axes)
  M4  V100 snapshots: one at session start; an ecuMs WRAP is not a reboot; a
      real rstBootCount change IS, and snapshots both sides
  M5  V100 on-change: a rare state channel that moves lands in onchange.csv
  M6  V100 a channel this .ini does not declare is reported as unavailable,
      not silently dropped
  M7  V100 --full: phase 2 and phase 3 no longer share fast.csv, so no CSV
      is written against a second header
  M8  V100 the K-line PHYSICAL mode is confirmed and recorded in EVERY
      session, including a --runtime-only one
  G1..G4 (2026-10-10) THE GUIDED SESSION against a CarEcu (a FakeEcu with a
      page, an engine, a pedal, a throttle, a wideband) and a scripted
      Operator that does what each prompt says: G1 a healthy car - every
      phase, the strategy comparison names the right cam level, never a Burn,
      the RAM change reverted at the end; G2 the 2026-10-10 bugs - phase 5
      FAILS naming the dead injector channels 2 and 4, phase 6 NAMES the
      protection fuel cut on the tip-in and its throttle-fault cause; G3
      Ctrl+C mid-drive sends '!X' and restores dbwEnable; G4 --phase / --resume.
"""
from __future__ import annotations

import binascii
import csv
import queue
import shutil
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_vehicle_capture as VC     # noqa: E402
import me711_vehicle_test as VT        # noqa: E402

# THE .ini OF THE IMAGE UNDER TEST, from the one place that names an image
# (tools/lib/me711_image.py). It was hardcoded to the V99 name, so a version
# bump left this suite testing the channel map of a stale .ini.
import me711_image as IMG                # noqa: E402
INI = hcpaths.TUNERSTUDIO / ("hanicore_%s.ini" % IMG.STEM.replace(
    "HaniCore_ME711_", "me711_").lower())
CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += 0 if ok else 1
    print("  [%s] %-62s %s" % ("PASS" if ok else "FAIL", name, detail))


def env(payload):
    return VT.envelope(payload)


class FakeEcu:
    """One fake ECU behind one fake KKL. `mode`: 'ok' (answers), 'dead'
    (echo only), 'kwp' (needs the 5-baud entry first), and KWP faults."""

    def __init__(self, mode="ok", kwp_fault=None, crc_every=0):
        ini = VC.Ini(INI)
        self.ini = ini
        self.block = ini.block
        self.mode = mode
        self.kwp_fault = kwp_fault
        self.crc_every = crc_every
        self.n_reply = 0
        self.baud = 115200
        self.ecu_rate = 115200 if mode == "ok" else 57600
        self.rx = bytearray()
        self.kwp_stage = 0
        self.och = bytearray(self.block + VT.EXT_WITNESS + 128)
        self.page = bytes(4096)
        self.sig = ini.signature
        self.etb = None              # (sub, reads left)
        self.drop = 0                # replies to drop (dropout)
        self.seq = 0
        self.ms = 1000
        hdr = self.block + VT.EXT_RING
        self.och[hdr:hdr + 2] = b"HE"
        self.och[hdr + 2:hdr + 4] = (1).to_bytes(2, "big")
        self.och[hdr + 6:hdr + 8] = (90).to_bytes(2, "big")
        self.och[hdr + 8:hdr + 10] = (10).to_bytes(2, "big")
        self.set("RPMValue", 0)
        self.set("ecuMs", self.ms)
        # 2026-10-12: the reset witness's live half (hcrtmon711.c)
        w = self.block + VT.EXT_WITNESS
        live = {"magic": 0x5257, "uptime_ms": 4321, "rpm": 850,
                "batt_dv": 138, "asic_csum_err": 3, "s5500_gap_max_ms": 11}
        for k, v in live.items():
            i = VT.WT_FIELDS.index(k)
            self.och[w + 2 * i:w + 2 * i + 2] = v.to_bytes(2, "big")
        # ... and the half copied at boot (the boot BEFORE this one). Until
        # 2026-10-13 the rig left it empty, so the "no record" branch was the
        # only one tested and the printed record crashed every car session
        # (format with 13 fields, 12 values).
        prev = {"magic": 0x5257, "uptime_ms": 3856, "batt_dv": 120,
                "asic_run_ok": 13278, "s5500_gap_max_ms": 13,
                "main_pass_max_T": 11651, "wdt_gap_max_ms": 2}
        for k, v in prev.items():
            i = 32 + VT.WT_FIELDS.index(k)
            self.och[w + 2 * i:w + 2 * i + 2] = v.to_bytes(2, "big")

    # ---- the OCH image ----
    def set(self, name, v):
        typ, off = self.ini.scalars[name][0], self.ini.scalars[name][1]
        w = VC.SIZES[typ]
        self.och[off:off + w] = int(v & ((1 << (8 * w)) - 1)).to_bytes(w, "big")

    def event(self, typ, arg, v1, v2, torn=False):
        base = self.block + VT.EXT_RING
        i = self.seq % 90
        r = base + 16 + i * 10
        seq = 0xFFFF if torn else self.seq
        self.och[r:r + 10] = (seq.to_bytes(2, "big") + self.ms.to_bytes(2, "big")
                              + bytes([typ, arg]) + v1.to_bytes(2, "big")
                              + v2.to_bytes(2, "big"))
        self.seq += 1
        self.och[base + 4:base + 6] = (self.seq & 0xFFFF).to_bytes(2, "big")

    # ---- the port interface the tool uses ----
    def set_baud(self, b):
        self.baud = b

    def reset_input(self):
        self.rx.clear()

    def close(self):
        pass

    def read(self, n, timeout):
        out = bytes(self.rx[:n])
        del self.rx[:n]
        return out

    def five_baud(self, addr):
        self.baud = 10400
        self.rx.clear()
        if self.mode in ("kwp", "ok") \
                and self.kwp_fault not in ("noinit", "noslow") \
                and addr == 0x01:
            self.rx += b"\x55\xEF\x8F"
            self.kwp_stage = 1

    def wakeup(self):
        """ISO 14230 fast init: the session opens at StartCommunication."""
        self.baud = 10400
        self.rx.clear()
        if self.mode in ("kwp", "ok") and self.kwp_fault != "noinit":
            self.kwp_stage = 1

    def write(self, data: bytes):
        self.rx += data                       # the K-line echo
        if self.mode == "dead":
            return
        if self.kwp_stage and self.baud == 10400:
            self.kwp(data)
            return
        if self.baud != self.ecu_rate:
            if self.mode == "ok":
                self.ecu_rate = self.baud     # the ECU follows the host
            return
        self.ts(data)

    def kwp(self, data):
        if data == b"\x70":
            self.rx += b"\xFE"
            return
        svc = data[3:3 + (data[0] & 0x3F)]

        def reply(d):
            f = bytes([0x80 | len(d), 0xF1, 0x01]) + d
            self.rx += f + bytes([sum(f) & 0xFF])
        if svc[:1] == b"\x81":
            reply(b"\xC1\xEF\x8F")
        elif svc[:1] == b"\xB0":
            if self.kwp_fault == "identify":
                reply(b"\x7F\xB0\x11")
            else:
                reply(b"\xF0" + self.sig.encode())
        elif svc[:1] == b"\xB1":
            if self.kwp_fault == "gofast":
                return
            reply(b"\xF1")
            if self.kwp_fault != "after":
                self.ecu_rate = {1: 10400, 2: 57600, 3: 124800,
                                 4: 115200}[svc[1]]
            else:
                self.ecu_rate = 1        # never answers again
            self.kwp_stage = 0

    def ts(self, data):
        if len(data) < 7:
            return
        n = (data[0] << 8) | data[1]
        p = bytes(data[2:2 + n])
        if self.drop:
            self.drop -= 1
            return
        c = p[:1]
        if c in (b"S", b"Q"):
            body = self.sig.encode() + b"\0"
        elif c == b"V":
            body = IMG.metadata()["version_text"].encode() + b"\0"
        elif c == b"O":
            off = int.from_bytes(p[1:3], "big")
            cnt = int.from_bytes(p[3:5], "big")
            self.tick(off <= 776 < off + cnt)
            body = bytes(self.och[off:off + cnt])
        elif c == b"R":
            off = int.from_bytes(p[1:3], "big")
            cnt = int.from_bytes(p[3:5], "big")
            body = self.page[off:off + cnt]
        elif c == b"!":
            if p[1:2] == b"C":
                self.etb = (p[2], 6)
            body = b""
        elif c == b"l":
            # the composite logger: 200 records of 8 bytes on a read
            body = b""
            if p[1:2] == b"\x03":
                body = b"".join(bytes([0, 1, 1 << (i % 4), (i & 1) | 8])
                                + (i * 625).to_bytes(4, "big")
                                for i in range(200))
        else:
            body = b""
        blob = b"\x00" + body
        self.n_reply += 1
        crc = binascii.crc32(blob) & 0xFFFFFFFF
        if self.crc_every and self.n_reply % self.crc_every == 0:
            crc ^= 1
        self.rx += len(blob).to_bytes(2, "big") + blob + crc.to_bytes(4, "big")

    def tick(self, status_read=False):
        self.ms = (self.ms + 20) & 0xFFFF
        self.set("ecuMs", self.ms)
        if self.etb and status_read:      # one procedure step per status read
            sub, left = self.etb
            if left > 3:
                self.set("etbCalStatus", 1 | (2 << 4))      # RUN, DRIVE A
            elif left > 0:
                self.set("etbCalStatus", 1 | (7 << 4))      # RUN, CHECK STOP A
            else:
                if sub in (4, 5):
                    self.set("etbCalStatus", 6)             # STOP REACHED
                    self.set("etbCalA1" if sub == 4 else "etbCalB1",
                             973 if sub == 4 else 72)
                elif sub == 3:
                    self.set("etbCalStatus", 3 | (14 << 8))  # FAIL NOT A STOP A
                    self.set("etbStopMoved", 145)
                    self.set("etbStopLimit", 108)
                    self.set("etbStopDisp", 650)
                else:
                    self.set("etbCalStatus", 2 if sub == 1 else 4)
                self.etb = None
                return
            self.etb = (sub, left - 1)


class Args:
    def __init__(self, out, **kw):
        self.port = "FAKE"
        self.baud = 115200
        self.out = None if out is None else str(out)
        self.ini = None
        self.duration = None
        self.kline = self.autocal = self.runtime = False
        self.direct = False
        self.no_prompt = True
        self.analyze = False
        self.quiet = True
        self.profile = "max"
        self.reduced = False
        for k, v in kw.items():
            setattr(self, k, v)


class Answers:
    """stdin for the tool's prompts; on_get runs before each answer."""

    def __init__(self, answers, on_get=None):
        self.a = list(answers)
        self.on_get = on_get

    def get(self):
        if self.on_get:
            self.on_get()
        return self.a.pop(0) if self.a else ""


def read_csv(p):
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ============================================ the GUIDED session (2026-10-10)
class CarEcu(FakeEcu):
    """A FakeEcu with a CAR behind it: a page (W writes it, R reads it), an
    engine that cranks / runs / stops when the scripted operator acts, a
    pedal, a throttle, the wideband, per-channel injector telemetry - and the
    two faults the 2026-10-10 car showed: `semi_bug` (semi-sequential leaves
    injector channels 2 and 4 dead) and `tip_cut` (a fast tip-in trips the
    throttle-fault protection fuel cut)."""

    def __init__(self, semi_bug=False, tip_cut=False, tip_drop=False,
                 lam_drop=False, no_cam=False):
        super().__init__("ok")
        self.no_cam = no_cam
        self.tip_drop = tip_drop
        self.lam_drop, self.lam_was_out, self.cj_tmo = lam_drop, False, 0
        import types
        self.C = VT.Ecu.constants(types.SimpleNamespace(ini_path=INI,
                                                        _consts=None))
        self.page = bytearray(4096)
        for n, v in (("cylinders", 4), ("injStrategy", 1), ("ignStrategy", 1),
                     ("syncMode", 2), ("lambda1Source", 1), ("dbwEnable", 0),
                     ("camPhaseLevel", 0), ("injFlowCcMin", 301)):
            self.pset(n, v)
        for i, (a, b) in enumerate(zip([96, 89, 97, 88] + [255] * 8,
                                       [102, 95, 103, 94] + [255] * 8)):
            self.page[self.C["injPin"][3] + i] = a
            self.page[self.C["ignPin"][3] + i] = b
        self.semi_bug, self.tip_cut = semi_bug, tip_cut
        self.engine, self.t_state = "off", 0.0
        self.pedal_fn, self.t_pedal = (lambda t: 0.0), 0.0
        self.burns, self.cmds = 0, []
        self.burned = bytes(4096)
        self.cut_logged = False
        self.clt = 60.0
        for n, v in (("VBatt", 138), ("battDv", 138), ("intake", 10250),
                     ("mapKpaX10", 1012), ("s5500w08", 820),
                     ("rstBootCount", 5), ("lamWhy", 0x0108),
                     ("targetLambda", 1000), ("lambdaTarget", 1000)):
            self.set(n, v)

    def pset(self, name, v):
        kind, _s, w, off, lo, hi, _n = self.C[name]
        if kind == "bits":
            raw = int.from_bytes(self.page[off:off + w], "big")
            m = ((1 << (hi - lo + 1)) - 1) << lo
            v = (raw & ~m) | ((v << lo) & m)
        self.page[off:off + w] = int(v).to_bytes(w, "big")

    def pget(self, name):
        kind, _s, w, off, lo, hi, _n = self.C[name]
        v = int.from_bytes(self.page[off:off + w], "big")
        return (v >> lo) & ((1 << (hi - lo + 1)) - 1) if kind == "bits" else v

    def ts(self, data):
        if len(data) >= 7:
            n = (data[0] << 8) | data[1]
            p = bytes(data[2:2 + n])
            if p[:1] == b"W":
                off = int.from_bytes(p[1:3], "big")
                self.page[off:off + len(p) - 3] = p[3:]
                return self._ok()
            if p[:1] == b"B":
                self.burns += 1
                self.burned = bytes(self.page)       # what is in flash now
                self.set("nvmCommits", self.burns)
                return self._ok()
            if p[:1] == b"!":
                self.cmds.append(p)
                if p[:3] == b"!C\x01":      # the TPS endpoint calibration
                    self.pset("tps1Min", self.pget("tps1Min") + 3)
        return super().ts(data)

    def _ok(self):
        blob = b"\x00"
        self.rx += len(blob).to_bytes(2, "big") + blob + (
            binascii.crc32(blob) & 0xFFFFFFFF).to_bytes(4, "big")

    def go(self, state):
        import time as _t
        self.engine, self.t_state = state, _t.monotonic()

    def pedal(self, fn):
        import time as _t
        self.pedal_fn, self.t_pedal = fn, _t.monotonic()

    def tick(self, status_read=False):
        import time as _t
        super().tick(status_read)
        now = _t.monotonic()
        seq_bad = (self.pget("injStrategy") == 2 and self.pget("camPhaseLevel") == 1
                   and not self.no_cam)
        if self.engine == "crank" and now - self.t_state > 0.05 and not seq_bad:
            self.engine = "run"
        run = self.engine == "run"
        p = max(0.0, min(100.0, self.pedal_fn(now - self.t_pedal)))
        rpm = {"off": 0, "keyoff": 0, "crank": 200}.get(self.engine, 0)
        cut = self.tip_cut and run and p >= 30
        en = self.pget("dbwEnable")
        # 2026-10-11: a fast press reads as a suspect pedal pair and the
        # throttle bridge drops (DBW INIT, nothing latched)
        drop = self.tip_drop and run and en and p >= 30
        # overrun fuel cut only right after the "release from 3000 rpm"
        dfco = run and p == 0 and now - self.t_pedal < self.overrun_until
        if run:
            rpm = 900 + (self.n_reply % 7) - 3 + int(p * 20)
            if cut:
                rpm = 650
            if drop:
                rpm = 700
        self.set("RPMValue", rpm)
        self.set("rpm", rpm)
        self.set("engineFlags", (1 if run else (2 if self.engine == "crank"
                                                else 0)) | (32 if dfco else 0))
        self.set("syncState", (3 if self.no_cam else 4) if run
                 else (3 if self.engine == "crank" else 0))
        # true sequential only with the cycle (no cam: the wasted fallback)
        self.set("seqActive", 1 if run and not self.no_cam
                 and self.pget("injStrategy") == 2 else 0)
        self.set("fuelCutFlags", 8 if cut else (1 if dfco else 0))
        self.set("limpCut", 2 if cut else 0)
        self.set("dbwFaults", 64 if cut else 0)
        if cut and not self.cut_logged:
            self.event(8, 0, 1600, 8)
            self.event(16, 0, 1600, 2)
            self.cut_logged = True
        if not cut:
            self.cut_logged = False
        for n in range(1, 5):
            dead = self.semi_bug and self.pget("injStrategy") == 1 and n in (2, 4)
            self.set("inj%dDeliveredUs" % n, 2700 if run and not dead else 0)
            self.set("inj%dRequestedUs" % n, 2700 if run else 0)
        self.set("ignOnMask", (1 << (self.n_reply % 4)) if run else 0)
        lam = 1700 if (run and self.semi_bug) else 1000
        lam_out = run and self.lam_drop and (self.n_reply // 15) % 4 == 3
        if lam_out and not self.lam_was_out:
            self.cj_tmo += 1                 # each dropout starts at a timeout
        self.lam_was_out = lam_out
        self.set("cjTmo", self.cj_tmo)
        self.set("lamWhy", (0x010D if lam_out else 0x0100) if run else 0x0108)
        self.set("lambdaValue", lam if run else 0)
        self.set("lambda1X1000", lam if run else 0)
        self.set("dbwApp1X10", int(p * 10))
        self.set("dbwApp2X10", int(p * 10))
        self.set("pedalX10", int(p * 10))
        self.set("pedal2X10", int(p * 10))
        tps = (6.0 if drop else p) if en else 5.0
        for n in ("dbwTps1X10", "dbwTps2X10", "dbwTargetX10", "dbwActualX10"):
            self.set(n, int(tps * 10))
        self.set("dbwState", (1 if drop else 2) if en else 0)
        self.set("dbwPendFaults", 2 if drop else 0)
        self.set("cfgDirtyGroups", 0)
        self.set("runOn", 1 if self.engine == "keyoff" else 0)
        self.clt = min(90.0, self.clt + (0.01 if run else 0.0))
        self.set("coolant", int(self.clt * 10) + 10000)
        self.set("ignitionTiming", 100)

    overrun_until = 0.0


class Operator:
    """The person in the car, scripted: reads each prompt and does what it
    says to the CarEcu, then presses ENTER (or answers a question)."""

    def __init__(self, ecu, strategy="n", interrupt_on=None):
        self.e, self.strategy, self.interrupt_on = ecu, strategy, interrupt_on
        self.prompts = []

    def get(self):                      # the K-line cable question
        return ""

    def answer(self, prompt):
        e = self.e
        self.prompts.append(prompt)
        if self.interrupt_on and self.interrupt_on in prompt:
            raise KeyboardInterrupt
        if "Foot OFF" in prompt:
            e.pedal(lambda t: 0.0)
        elif "FULLY DOWN" in prompt:
            e.pedal(lambda t: 100.0)
        elif "SLOWLY press" in prompt:
            e.pedal(lambda t: min(100.0, t * 400.0))
        elif "Stab" in prompt:
            e.pedal(lambda t: 100.0 if int(t * 50) % 2 else 0.0)
        elif "PID AUTOTUNE" in prompt:
            return "n"
        elif "OPTIONAL strategy" in prompt:
            return self.strategy
        elif prompt.startswith("ENGINE START") or "START THE ENGINE" in prompt \
                or "KEY ON and START" in prompt:
            e.pedal(lambda t: 0.0)
            e.go("crank")
        elif "STOP THE ENGINE" in prompt:
            e.go("off")
        elif "KEY OFF" in prompt:
            e.go("keyoff")
        elif "FAST tip-in" in prompt:
            e.pedal(lambda t: 50.0 if 0.03 <= t <= 0.08 else 0.0)
        elif "SLOWLY raise" in prompt:
            e.pedal(lambda t: min(40.0, t * 300.0))
        elif "release the pedal FULLY" in prompt:
            e.pedal(lambda t: 40.0 if t < 0.04 else 0.0)
            e.overrun_until = 0.15
            return ""
        elif "Hold" in prompt or "blip" in prompt or "tip-in" in prompt:
            e.overrun_until = 0.0
        elif "blip" in prompt:
            e.pedal(lambda t: 40.0 if t < 0.03 else 0.0)
        elif "Hold ~2500" in prompt:
            e.pedal(lambda t: 30.0)
        return ""


def guided_checks(tmp):
    import json
    print("G1 the GUIDED session, a healthy car (fixed firmware)")
    car = CarEcu()
    op = Operator(car, strategy="y")
    out = tmp / "g1"
    rc = VT.run(Args(out, guided=True, no_prompt=False, time_scale=0.02,
                     phase=None, resume=None), open_port=lambda b: car,
                stdin_q=op)
    rep = (out / "report.md").read_text(encoding="utf-8")
    st = json.loads((out / "guided_state.json").read_text())
    res = {r["system"]: r["status"] for r in st["results"]}
    check("G1 rc 0, every phase ran and a report.md was written",
          rc == 0 and all(p in st["done"] for p in VT.GUIDED_PHASES
                          if p != "report") and "| system | result |" in rep,
          (rc, st["done"]))
    check("G1 the systems PASS: start, injectors, idle, wideband, tip-in, "
          "throttle",
          all(res.get(k) == "PASS" for k in (
              "Engine start", "Injectors", "Idle stability", "Wideband",
              "Tip-in response", "Throttle, engine off", "Pedal")),
          {k: res.get(k) for k in ("Engine start", "Injectors",
                                   "Idle stability", "Wideband",
                                   "Tip-in response", "Pedal",
                                   "Throttle, engine off")})
    check("G1 every phase prints a safety condition before driving anything",
          "SAFETY: gear in NEUTRAL" in (out / "console.log").read_text())
    check("G1 the strategy comparison names the right cam level (0: level 1 "
          "never starts on this car)",
          any(r["system"] == "Strategy comparison" and r["status"] == "PASS"
              and "cam level 0' is right" in r["reason"] for r in st["results"]),
          [r["reason"] for r in st["results"]
           if r["system"] == "Strategy comparison"])
    # FULLY AUTOMATIC (owner, 2026-10-11): the passed calibration is burned
    # in phase 3, the passed drive test keeps the throttle ON and is burned
    # at the end; the strategy / cam-level experiments are put back first.
    check("G1 two verified Burns (phase 3 calibration, end: throttle ON); "
          "dbwEnable 1 IN FLASH; strategies back as they were",
          car.burns == 2 and car.pget("dbwEnable") == 1
          and car.burned[car.C["dbwEnable"][3]] & 1 == 1
          and car.pget("injStrategy") == 1 and car.pget("ignStrategy") == 1
          and car.pget("camPhaseLevel") == 0
          and all(b["ok"] for b in st["info"].get("burns", [])),
          (car.burns, car.pget("dbwEnable"), st["info"].get("burns")))
    check("G1 the console asks only for physical actions - no [y/N] or "
          "keep/revert question",
          "[y/N]" not in (out / "console.log").read_text()
          and "keep or revert" not in (out / "console.log").read_text().lower())
    check("G1 the composite logger was captured at the crank and at idle",
          (out / "toothlog_crank.csv").exists()
          and (out / "toothlog_idle.csv").exists()
          and len(read_csv(out / "toothlog_idle.csv")) == 200)
    check("G1 ONE session ZIP beside the folder holds the report",
          out.with_suffix(".zip").exists() and
          any(n.endswith("report.md") for n in __import__("zipfile").ZipFile(
              out.with_suffix(".zip")).namelist()))
    check("G1 rows carry the phase and the step marker",
          any(r.get("marker") == "drive:tipin_1" for r in
              read_csv(out / "fast.csv")))

    print("G2 the 2026-10-10 bugs: semi-sequential dead injectors + a "
          "tip-in fuel cut")
    car = CarEcu(semi_bug=True, tip_cut=True)
    op = Operator(car, strategy="n")
    out = tmp / "g2"
    VT.run(Args(out, guided=True, no_prompt=False, time_scale=0.02),
           open_port=lambda b: car, stdin_q=op)
    st = json.loads((out / "guided_state.json").read_text())
    last = {}
    for r in st["results"]:
        last[r["system"]] = r
    inj = last.get("Injectors", {})
    check("G2 phase 5 FAILS on the dead injector channels and names 2 and 4",
          inj.get("status") == "FAIL" and "2, 4" in inj.get("reason", "")
          and "semi-sequential" in inj.get("reason", ""), inj)
    tip = last.get("Tip-in response", {})
    check("G2 phase 6 FAILS the tip-in and NAMES the protection fuel cut and "
          "its throttle-fault cause",
          tip.get("status") == "FAIL" and "PROTECTION fuel cut" in
          tip.get("reason", "") and "THROTTLE FAULT" in tip.get("reason", "")
          and "OFF TARGET TOO LONG" in tip.get("reason", ""), tip)
    check("G2 a FAILED drive test leaves the throttle OFF and burns only the "
          "phase-3 calibration", car.pget("dbwEnable") == 0 and car.burns == 1
          and car.burned[car.C["dbwEnable"][3]] & 1 == 0,
          (car.pget("dbwEnable"), car.burns))
    check("G2 the mixture is called LEAN (half the cylinders unfuelled)",
          last.get("Mixture", {}).get("status") == "FAIL"
          and "LEAN" in last.get("Mixture", {}).get("reason", ""),
          last.get("Mixture"))
    check("G2 report.md lists what does NOT work",
          "## Does NOT work" in (out / "report.md").read_text()
          and "Injectors" in (out / "report.md").read_text())

    print("G6 the fast-pedal cut-out: the throttle bridge drops on a "
          "suspect pedal pair (no latched fault)")
    car = CarEcu(tip_drop=True)
    op = Operator(car, strategy="n")
    out = tmp / "g6"
    VT.run(Args(out, guided=True, no_prompt=False, time_scale=0.02),
           open_port=lambda b: car, stdin_q=op)
    st = json.loads((out / "guided_state.json").read_text())
    last = {r["system"]: r for r in st["results"]}
    tip = last.get("Tip-in response", {})
    check("G6 phase 6 FAILS the tip-in and NAMES the bridge drop and the "
          "pedal pair", tip.get("status") == "FAIL"
          and "BRIDGE DROPPED" in tip.get("reason", "")
          and "pedal pair" in tip.get("reason", ""), tip)

    print("G7 the 2026-10-10 lambda dropouts: a CJ120 timeout withdraws the "
          "measurement every few seconds")
    car = CarEcu(lam_drop=True)
    op = Operator(car, strategy="n")
    out = tmp / "g7"
    VT.run(Args(out, guided=True, no_prompt=False, time_scale=0.02),
           open_port=lambda b: car, stdin_q=op)
    st = json.loads((out / "guided_state.json").read_text())
    wb = [r for r in st["results"] if r["system"] == "Wideband"]
    check("G7 the idle Wideband verdict is not PASS and names the dropouts "
          "and the CJ120 timeouts",
          bool(wb) and wb[0]["status"] in ("WARN", "FAIL")
          and "DROPPED OUT" in wb[0]["reason"]
          and "CJ120 timeout" in wb[0]["reason"], wb)

    print("G8 the cam never gives the cycle: the cam-level answer is "
          "INCONCLUSIVE, never a guess")
    car = CarEcu(no_cam=True)
    op = Operator(car, strategy="y")
    out = tmp / "g8"
    VT.run(Args(out, guided=True, no_prompt=False, time_scale=0.02),
           open_port=lambda b: car, stdin_q=op)
    st = json.loads((out / "guided_state.json").read_text())
    sc = [r for r in st["results"] if r["system"] == "Strategy comparison"]
    check("G8 strategy comparison says INCONCLUSIVE and names the missing "
          "cycle, and does not claim a cam level",
          bool(sc) and "INCONCLUSIVE" in sc[0]["reason"]
          and "never gave" in sc[0]["reason"]
          and "is right" not in sc[0]["reason"], sc)

    print("G3 Ctrl+C in the middle of the drive phase")
    car = CarEcu()
    op = Operator(car, interrupt_on="FAST tip-in 2")
    out = tmp / "g3"
    rc = VT.run(Args(out, guided=True, no_prompt=False, time_scale=0.02),
                open_port=lambda b: car, stdin_q=op)
    con = (out / "console.log").read_text()
    check("G3 Ctrl+C: '!X' sent, dbwEnable RESTORED to its original 0, only "
          "the phase-3 Burn (before the drive test), data kept",
          rc == 130 and b"!X" in car.cmds and car.pget("dbwEnable") == 0
          and car.burns == 1 and "SAFETY STOP" in con
          and (out / "fast.csv").exists(),
          (rc, car.cmds[-3:], car.pget("dbwEnable"), car.burns))

    print("G4 --phase and --resume")
    car = CarEcu()
    op = Operator(car)
    out = tmp / "g4"
    VT.run(Args(out, guided=True, no_prompt=False, time_scale=0.02,
                phase="preflight"), open_port=lambda b: car, stdin_q=op)
    st1 = json.loads((out / "guided_state.json").read_text())
    n1 = len(read_csv(out / "fast.csv"))
    VT.run(Args(None, guided=True, no_prompt=False, time_scale=0.02,
                resume=str(out)), open_port=lambda b: car, stdin_q=op)
    st2 = json.loads((out / "guided_state.json").read_text())
    check("G4 --phase preflight runs only that phase",
          st1["done"] == ["preflight"], st1["done"])
    check("G4 --resume continues the SAME folder: preflight not repeated, "
          "the rest done, rows appended",
          st2["done"].count("preflight") == 1 and "idle" in st2["done"]
          and len(read_csv(out / "fast.csv")) > n1
          and "Battery" in (out / "report.md").read_text(),
          st2["done"])
    print("G5 the ECU names its image; the preflight compares it with the kit")
    man = {"build_id": "1A2B3C4D", "sha256": "050cc11e" + "0" * 56}
    base = "HaniCore V102 DEV / Bosch ME7.1.1"
    ok = VT.image_identity(base + " build 1A2B3C4D", man)
    bad = VT.image_identity(base + " build 99999999", man)
    old = VT.image_identity(base, man)
    check("G5 same build PASS; another build FAIL naming both; an image "
          "without an id (323FFF9F / 050CC11E) FAIL",
          ok[0] == "PASS" and bad[0] == "FAIL" and "99999999" in bad[1]
          and "1A2B3C4D" in bad[1] and old[0] == "FAIL", (ok, bad, old))
    g1 = json.loads((tmp / "g1" / "guided_state.json").read_text())
    check("G5 the guided preflight reported the identity of the image under "
          "test", any(r["system"] == "ECU identity" and r["status"] == "PASS"
                      for r in g1["results"]),
          [r for r in g1["results"] if r["system"] == "ECU identity"])
    check("G4 no flags = the guided session; --recorder = the old recorder",
          VT.parse(["--port", "COM2"]).guided
          and not VT.parse(["--port", "COM2", "--recorder"]).guided
          and VT.parse(["--port", "COM2", "--recorder"]).runtime)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="hc_vt_"))
    try:
        # K1 -------------------------------------------------------------
        print("K1 OBD path answers")
        ecu = FakeEcu("ok")
        out = tmp / "k1"
        rc = VT.run(Args(out, kline=True), open_port=lambda b: ecu,
                    stdin_q=Answers(["s"]))
        summ = (out / "summary.txt").read_text()
        check("K1 rc 0, KLINE PASS on the OBD path", rc == 0
              and "KLINE    PASS     OBD path" in summ, summ.splitlines()[-3:])
        rows = read_csv(out / "kline.csv")
        check("K1 kline.csv has the passive listen + probes",
              any(r["stage"] == "passive listen" for r in rows)
              and any(r["stage"] == "direct probe" for r in rows), len(rows))
        check("K1 the soak measured a read rate", "rows/s" in summ)

        # K2 -------------------------------------------------------------
        print("K2 OBD path dead, then the direct ECU path")
        ecu = FakeEcu("dead")

        # V100: the cable is moved when the operator answers the "connect the
        # KKL" prompt - NOT when they answer the physical-connection question
        # that now precedes it. The fixture fires on_get for every prompt, so
        # the first one must not already connect the ECU or the OBD attempt
        # would succeed and the fallback this case exists to test never runs.
        prompts = []

        # 2026-10-11: two more prompts precede the move - "Ignition ON"
        # (2nd) and "try OBD again" (3rd, answered "s") - so the cable moves
        # at the 4th.
        def connect_direct():
            prompts.append(1)
            if len(prompts) >= 4:
                ecu.mode = "ok"
        out = tmp / "k2"
        a = Args(out, kline=True, no_prompt=False)
        # V100: the FIRST answer is the physical-connection confirmation
        # ("" = keep OBD); only the SECOND one is the "I moved the KKL"
        # Enter, which is what may make the direct path answer. The tool asks
        # about the cable because V99 inferred it from a flag and then
        # recorded "OBD path PASS" over wiring that had never carried OBD
        #.
        rc = VT.run(a, open_port=lambda b: ecu,
                    stdin_q=Answers(["", "", "s", "", "s"], on_get=connect_direct))
        con = (out / "console.log").read_text()
        summ = (out / "summary.txt").read_text()
        check("K2 asks for the ignition ON before the K-line test",
              "Ignition ON (engine off)" in con)
        check("K2 asks which connection is physically in place",
              "Where is the KKL plugged in RIGHT NOW?" in con)
        check("K2 says OBD K-LINE CONNECTION FAILED and asks for the KKL",
              "OBD K-LINE CONNECTION FAILED" in con
              and "Connect the KKL directly to the ECU K-line" in con)
        check("K2 OBD FAIL (stage NO INIT RESPONSE) and DIRECT ECU PASS, one "
              "session", "OBD path: stage NO INIT RESPONSE" in summ
              and "DIRECT ECU path:" in summ and rc == 0, summ.splitlines()[-4:])
        # V100: and the move is RECORDED, with the physical mode it ended in
        import json as _j
        md = _j.loads((out / "metadata.json").read_text())
        ph = md["phases"]["kline"]["physical"]
        check("K2 records the OBD -> DIRECT ECU cable move",
              ph["mode"] == "DIRECT ECU"
              and any(t["from"] == "OBD" and t["to"] == "DIRECT ECU"
                      for t in ph["transitions"]), ph)

        # K2b ------------------------------------------------------------
        # THE CAR, 2026-10-11: the first OBD attempt ran with the ignition
        # OFF (ECU unpowered, only the KKL echoed). The operator switches it
        # on at the retry prompt: OBD answers, the cable never moved.
        print("K2b OBD silent with the ignition off, the retry answers")
        ecu = FakeEcu("dead")
        prompts2 = []

        def ignition_on():
            prompts2.append(1)
            if len(prompts2) >= 3:          # the "try OBD again" Enter
                ecu.mode = "ok"
        out = tmp / "k2b"
        a = Args(out, kline=True, no_prompt=False)
        rc = VT.run(a, open_port=lambda b: ecu,
                    stdin_q=Answers(["d", "", "", "s"], on_get=ignition_on))  # K2 left DIRECT remembered: "d" = OBD
        con = (out / "console.log").read_text()
        md = _j.loads((out / "metadata.json").read_text())
        ph = md["phases"]["kline"]["physical"]
        check("K2b states what failed (no blame) and retries OBD",
              "did not answer the 5-baud address" in con
              and "try OBD again" in con and "ignition being OFF" not in con)
        check("K2b the retry passes on OBD; no cable move, no direct prompt",
              rc == 0 and ph["mode"] == "OBD"
              and not any(t["from"] == "OBD" for t in ph["transitions"])
              and "Connect the KKL directly" not in con, ph)

        # K3 -------------------------------------------------------------
        print("K3 the KWP stages")
        for fault, want in (("noinit", "NO INIT RESPONSE"),
                            ("identify", "IDENTIFY FAILED"),
                            ("gofast", "GOFAST FAILED"),
                            ("after", "TIMEOUT AFTER TRANSITION")):
            ecu = FakeEcu("kwp", kwp_fault=fault)
            out = tmp / ("k3_" + fault)
            rc = VT.run(Args(out, kline=True), open_port=lambda b, e=ecu: e,
                        stdin_q=Answers([]))
            summ = (out / "summary.txt").read_text()
            check("K3 %-10s -> stage %s" % (fault, want),
                  rc == 2 and ("stage %s" % want) in summ,
                  [l for l in summ.splitlines() if "KLINE" in l][:1])
        ecu = FakeEcu("kwp")
        out = tmp / "k3_ok"
        rc = VT.run(Args(out, kline=True), open_port=lambda b: ecu,
                    stdin_q=Answers(["s"]))
        summ = (out / "summary.txt").read_text()
        check("K3 KWP entry -> GOFAST 115200 -> PASS", rc == 0
              and "KWP 5-baud -> GOFAST 115200" in summ)
        # 2026-10-13: a silent 5-baud entry falls back to ISO 14230 fast init
        ecu = FakeEcu("kwp", kwp_fault="noslow")
        out = tmp / "k3_fast"
        rc = VT.run(Args(out, kline=True), open_port=lambda b: ecu,
                    stdin_q=Answers(["s"]))
        summ = (out / "summary.txt").read_text()
        check("K3 5-baud silent -> fast init -> GOFAST 115200 -> PASS",
              rc == 0 and "KWP fast init -> GOFAST 115200" in summ,
              [l for l in summ.splitlines() if "KLINE" in l][:1])

        # K4 -------------------------------------------------------------
        print("K4 malformed replies, reconnect")
        ecu = FakeEcu("ok", crc_every=7)
        out = tmp / "k4"
        rc = VT.run(Args(out, kline=True), open_port=lambda b: ecu,
                    stdin_q=Answers(["s"]))
        meta = (out / "metadata.json").read_text()
        import json
        q = json.loads(meta)["phases"]["kline"]["quality"]
        check("K4 CRC errors counted in the soak, not fatal",
              q["soak"]["crc_errors"] >= 10 and rc == 0, q["soak"])
        check("K4 port reconnect OK", q["reconnect"]["ok"], q["reconnect"])

        # A1 -------------------------------------------------------------
        print("A1 --autocal")
        ecu = FakeEcu("ok")
        out = tmp / "a1"
        rc = VT.run(Args(out, autocal=True), open_port=lambda b: ecu,
                    stdin_q=Answers([]))
        summ = (out / "summary.txt").read_text()
        check("A1 direction A and B: POSITION CAPTURED",
              summ.count("POSITION CAPTURED") >= 2, summ.count("POSITION CAPTURED"))
        check("A1 AutoCal NOT A STOP A explained with the numbers",
              "NOT A STOP A" in summ and "moved TPS1 145 counts, limit 108"
              in summ and "refused as not a stop" in summ
              and "SPRING EQUILIBRIUM" not in summ)
        ev = read_csv(out / "etb_events.csv")
        check("A1 etb_events.csv: stop-check phase explicitly identified, results retained",
              any("STOP CHECK A" in r["phase"] for r in ev)
              and any(r["event"].startswith("RESULT") for r in ev), len(ev))

        # R1 -------------------------------------------------------------
        print("R1 --runtime")
        ecu = FakeEcu("ok")
        ecu.set("RPMValue", 850)
        ecu.set("engineFlags", 1)
        for i in range(3):                 # history before the session
            ecu.event(6, 2, 850, 135)
        out = tmp / "r1"

        def inject():
            import time
            time.sleep(0.4)
            ecu.event(2, 3, 180, (2 << 8) | 0)       # crank sync
            ecu.event(8, 0, 1600, 8)                 # fuel cut: protection
            ecu.event(16, 0, 1600, 2)                # limp: throttle fault
            ecu.event(14, 3, 1500, 64)               # DBW FAULT off target
            ecu.event(9, 0, 3000, 1, torn=True)      # torn record
            time.sleep(0.3)
            for _ in range(120):                     # overflow the ring
                ecu.event(10, 0, 4000, 7)
            # V100: eight dropped replies - a fast read gives up after two
            # attempts on its FIRST window and the recorder reconnects after
            # three consecutive failures, so six is the minimum and eight has
            # margin. V99 used twelve, which spent ~5 s in request timeouts
            # and made the rest of the case depend on when they landed.
            ecu.drop = 8
            ecu.set("cfgWarnings", 0x0040)           # an ON_CHANGE channel
        th = threading.Thread(target=inject)
        th.start()
        rc = VT.run(Args(out, runtime=True, duration=4.0),
                    open_port=lambda b: ecu, stdin_q=Answers([]))
        th.join()
        fast = read_csv(out / "fast.csv")
        ts = [float(r["t"]) for r in fast]
        check("R1 fast rows written, timestamps monotonic",
              len(fast) > 20 and all(b >= a for a, b in zip(ts, ts[1:])),
              "%d rows" % len(fast))
        med, slow = read_csv(out / "medium.csv"), read_csv(out / "slow.csv")
        check("R1 medium and slow rows written", len(med) >= 2
              and len(slow) >= 2, "medium %d, slow %d" % (len(med), len(slow)))
        wit = read_csv(out / "witness.csv")
        check("R1 the live reset witness is logged every slow cycle",
              len(wit) >= 1 and wit[0].get("s5500_gap_max_ms") == "11"
              and wit[0].get("asic_csum_err") == "3",
              "%d witness rows %s" % (len(wit), wit[:1]))
        evs = read_csv(out / "events.csv")
        texts = " | ".join(r["text"] for r in evs)
        check("R1 ring events decoded with reasons (limp, DBW fault, sync)",
              "THROTTLE FAULT rev limit" in texts
              and "OFF TARGET TOO LONG" in texts and "CRANK ACQUIRED" in texts,
              len(evs))
        con = (out / "console.log").read_text()
        check("R1 the previous boot's witness record is PRINTED",
              "RESET WITNESS (start) - the last state BEFORE this boot: "
              "uptime 3856 ms" in con and "worst S5500 gap 13 ms" in con,
              [l for l in con.splitlines() if "WITNESS" in l][:2])
        check("R1 ring overflow REPORTED with a lost count",
              "RING OVERFLOW" in con and "records lost" in con)
        meta = json.loads((out / "metadata.json").read_text())
        rt = meta["phases"]["runtime"]
        check("R1 torn record skipped and counted", rt.get("ring_torn", 0) >= 1,
              rt.get("ring_torn"))
        check("R1 K-line dropout recovered and recorded",
              rt["drops"] >= 1 and rt["reconnects"] >= 1
              and "KLINE: RECONNECTED" in con,
              (rt["drops"], rt["reconnects"]))
        check("R1 ring split by subject: trigger / injection / etb / lambda / "
              "faults", all((out / n).exists() for n in (
                  "trigger_events.csv", "etb_ring_events.csv", "faults.csv")))

        # M1 -------------------------------------------------------------
        print("M1 V100 multi-rate groups")
        g = rt["groups"]
        check("M1 fast > medium > slow in measured rate",
              g["fast"]["rows_per_s"] > g["medium"]["rows_per_s"]
              > g["slow"]["rows_per_s"],
              {n: g[n]["rows_per_s"] for n in g})
        check("M1 every group reports channels, windows, bytes and rtt",
              all(g[n]["exchanges_per_row"] >= 1 and g[n]["bytes_per_row"] > 0
                  and g[n]["channels"] for n in ("fast", "medium", "slow")),
              {n: (g[n]["channels"], g[n]["exchanges_per_row"],
                   g[n]["bytes_per_row"]) for n in g})
        check("M1 SLOW is the WHOLE block, so no channel is unrecorded",
              g["slow"]["windows"] == [[0, ecu.block]]
              and g["slow"]["channels"] == "whole block", g["slow"]["windows"])
        check("M1 FAST carries the scheduler, trigger, masks, cuts and ETB "
              "together on one row",
              all(k in fast[0] for k in (
                  "schedulerExecuted", "schedulerLate", "schedulerMissed",
                  "schedulerMaxLatency", "syncState", "toothCorrections",
                  "camPhaseCorrections", "ignOnMask", "injOnMask",
                  "schedOverdwell", "sparkSkips", "veValue", "engLoad",
                  "etbTarget", "etbActual", "dbwDutyX10", "dbwFaults",
                  "fuelCut", "limpCut", "VBatt")),
              [k for k in ("schedulerLate", "ignOnMask", "limpCut", "VBatt")
               if k not in fast[0]])
        check("M1 MEDIUM carries the lambda chain, corrections and raw ADCs",
              all(k in med[0] for k in (
                  "lambdaValue", "lamWhy", "lamFault", "lam1RiX10",
                  "lam1IpUa", "lamVeff", "heaterDuty", "stftBank1",
                  "warmupEnrich", "fuelCorrection", "adc02_IPV",
                  "coolant", "intake", "knockState", "vvt1State")),
              [k for k in ("lam1RiX10", "lamVeff", "adc02_IPV")
               if k not in med[0]])

        # M2 -------------------------------------------------------------
        print("M2 V100 --profile reduced")
        ecu2 = FakeEcu("ok")
        ecu2.set("RPMValue", 850)
        ecu2.set("engineFlags", 1)
        out2 = tmp / "m2"
        VT.run(Args(out2, runtime=True, duration=2.0, profile="reduced"),
               open_port=lambda b: ecu2, stdin_q=Answers([]))
        m2 = json.loads((out2 / "metadata.json").read_text())
        r2 = m2["phases"]["runtime"]
        check("M2 --reduced is the operator's shorthand for --profile reduced",
              VT.parse(["--port", "COM2", "--runtime", "--reduced"]).profile
              == "reduced"
              and VT.parse(["--port", "COM2", "--full"]).profile == "max")
        check("M2 the profile is recorded in metadata",
              m2["logging_profile"] == "reduced"
              and r2["profile"] == "reduced", m2["logging_profile"])
        check("M2 reduced polls about a quarter as often",
              0 < r2["groups"]["fast"]["rows_per_s"] <= 3.0
              and r2["rates_configured_s"]["fast"] == 0.4,
              r2["groups"]["fast"]["rows_per_s"])
        check("M2 the EVENT RING period is NOT reduced",
              r2["rates_configured_s"]["ring"]
              == rt["rates_configured_s"]["ring"] == 0.2,
              r2["rates_configured_s"])

        # M3 -------------------------------------------------------------
        print("M3 V100 the configuration is in the session")
        cfg = meta["engine_config"]
        want = ("firingOrder", "injStrategy", "ignStrategy", "syncMode",
                "camPhaseMode", "camPhaseLevel", "cam1Pattern", "trigAngleX10",
                "syTeeth", "syGap", "loadSource", "lambda1Source",
                "lambda2Source", "lambdaHeatPolicy", "dbwEnable", "dbwKp",
                "dbwDevX10", "dbwDevMs", "dbwAutocalDuty", "tps1Min",
                "tps1Max", "etbLimpRpm", "injFlowCcMin", "revLimit",
                "fuelLoadAx", "fuelRpmAx", "ignLoadAx", "ignRpmAx")
        check("M3 every configuration fact needed to read the log back",
              all(k in cfg for k in want), [k for k in want if k not in cfg])
        check("M3 the VE axes are the real 16-bin arrays",
              len(cfg["fuelLoadAx"]) == 16 and len(cfg["fuelRpmAx"]) == 16,
              (len(cfg.get("fuelLoadAx", [])), len(cfg.get("fuelRpmAx", []))))
        check("M3 a bits field carries BOTH its label and its raw index",
              "_loadSource" in cfg and isinstance(cfg["loadSource"], str),
              (cfg.get("loadSource"), cfg.get("_loadSource")))
        check("M3 the logging rates and the K-line mode are in metadata too",
              meta["rates_configured_s"]["fast"] == 0.0
              and meta["kline_physical"]["mode"] in ("OBD", "DIRECT ECU"),
              meta.get("kline_physical"))

        # M4 -------------------------------------------------------------
        print("M4 V100 snapshots, and a wrap is not a reboot")
        snaps = read_csv(out / "snapshots.csv")
        check("M4 a snapshot at session start, with its reason",
              any(r["reason"] == "session start" for r in snaps), len(snaps))
        check("M4 the whole block is in the snapshot row",
              snaps and "rstBootCount" in snaps[0] and "nvmGeneration"
              in snaps[0] and "lam1RiX10" in snaps[0])
        check("M4 an ecuMs WRAP is not reported as a reboot",
              rt.get("uptime_wraps", 0) >= 1 and rt["reboots"] == 0,
              (rt.get("uptime_wraps"), rt["reboots"]))
        check("M4 a reconnect is snapshotted too (it may be a power cycle)",
              any(r["reason"] == "reconnect" for r in snaps),
              [r["reason"] for r in snaps])
        # a REAL reboot, on its own ECU so nothing else can absorb it
        ecu5 = FakeEcu("ok")
        ecu5.set("RPMValue", 850)
        ecu5.set("engineFlags", 1)
        out5 = tmp / "m4b"

        def reboot():
            import time
            time.sleep(0.6)
            ecu5.set("rstBootCount", 7)
        th5 = threading.Thread(target=reboot)
        th5.start()
        VT.run(Args(out5, runtime=True, duration=3.0),
               open_port=lambda b: ecu5, stdin_q=Answers([]))
        th5.join()
        r5 = json.loads((out5 / "metadata.json").read_text())["phases"]["runtime"]
        s5 = read_csv(out5 / "snapshots.csv")
        check("M4 a real rstBootCount change IS a reboot, and is snapshotted",
              r5["reboots"] >= 1
              and any(r["reason"] == "reboot" for r in s5)
              and "ECU REBOOTED" in (out5 / "console.log").read_text(),
              (r5["reboots"], [r["reason"] for r in s5]))

        # M5 -------------------------------------------------------------
        print("M5 V100 on-change capture")
        oc = read_csv(out / "onchange.csv")
        check("M5 a rare state channel that moved is in onchange.csv",
              any(r["channel"] == "cfgWarnings" and r["to"] == "64"
                  for r in oc) and rt["onchange"] >= 1,
              [(r["channel"], r["from"], r["to"]) for r in oc][:6])

        # M6 -------------------------------------------------------------
        print("M6 V100 an undeclared channel is reported, not dropped")
        ini = VC.Ini(INI)
        w, missing = VT.windows(ini, ["rpm", "notAChannelAtAll", "veValue"],
                                ini.block)
        check("M6 windows() names what the .ini does not declare",
              missing == ["notAChannelAtAll"] and w, (w, missing))
        check("M6 every declared FAST/MEDIUM channel exists in this .ini",
              not VT.windows(ini, VT.GROUPS["fast"], ini.block)[1]
              and not VT.windows(ini, VT.GROUPS["medium"], ini.block)[1],
              (VT.windows(ini, VT.GROUPS["fast"], ini.block)[1],
               VT.windows(ini, VT.GROUPS["medium"], ini.block)[1]))

        # M7 -------------------------------------------------------------
        print("M7 V100 --full: phase 2 and phase 3 do not share fast.csv")
        ecu3 = FakeEcu("ok")
        out3 = tmp / "m7"
        VT.run(Args(out3, autocal=True, runtime=True, duration=1.0),
               open_port=lambda b: ecu3, stdin_q=Answers([]))
        m3 = json.loads((out3 / "metadata.json").read_text())
        f3 = read_csv(out3 / "fast.csv")
        a3 = read_csv(out3 / "autocal.csv")
        check("M7 autocal.csv holds phase 2, fast.csv holds phase 3",
              a3 and f3 and "test" in a3[0] and "test" not in f3[0]
              and "wall" in f3[0], (list(a3[0])[:3], list(f3[0])[:3]))
        check("M7 no CSV was written against a second header",
              "csv_header_conflict" not in m3,
              m3.get("csv_header_conflict"))
        check("M7 every fast row has the same number of columns as the header",
              all(None not in r.values() for r in f3), len(f3))

        # M8 -------------------------------------------------------------
        print("M8 V100 the physical K-line mode in a --runtime-only session")
        con = (out / "console.log").read_text()
        check("M8 the physical mode is stated even without phase 1",
              "K-LINE PHYSICAL:" in con
              and meta["kline_physical"]["software_path_attempted"]
              in ("OBD", "DIRECT ECU"), meta["kline_physical"])
        ecu4 = FakeEcu("ok")
        out4 = tmp / "m8"
        # the remembered mode is the DEFAULT the question offers; 'd' takes
        # the other one, whichever that is in this evidence tree
        remembered = (tmp / VT.Kline.STATE).read_text(encoding="utf-8").strip()
        other = "OBD" if remembered == "DIRECT ECU" else "DIRECT ECU"
        VT.run(Args(out4, runtime=True, duration=0.5, no_prompt=False),
               open_port=lambda b: ecu4, stdin_q=Answers(["d"]))
        m4 = json.loads((out4 / "metadata.json").read_text())
        check("M8 the operator's answer overrides the remembered mode, is "
              "CONFIRMED and the change is recorded as a transition",
              m4["kline_physical"]["mode"] == other
              and m4["kline_physical"]["confirmed"]
              and any(t["from"] == remembered and t["to"] == other
                      for t in m4["kline_physical"]["transitions"]),
              (remembered, m4["kline_physical"]))
        check("M8 and it is REMEMBERED for the next session in this tree",
              (tmp / VT.Kline.STATE).read_text(encoding="utf-8").strip()
              == other)

        # M9 -------------------------------------------------------------
        # The one check neither tool can make on its own: a session this
        # recorder really wrote must be readable by the real analyser.
        print("M9 V100 the recorder's own output goes through the analyser")
        import me711_log_analyze as LA
        rc = LA.main([str(out)])
        an = json.loads((out / "analysis.json").read_text())
        S = an.get("subjects") or {}
        check("M9 the analyser reads a real multi-rate session",
              rc == 0 and an["rows"] > 20
              and S["logging"]["groups"]["fast"]["rows_per_s"] > 0
              and S["logging"]["groups"]["slow"]["channels"] == "whole block",
              (an["rows"], (S.get("logging") or {}).get("profile")))
        check("M9 it reads the configuration, the K-line mode and the "
              "scheduler out of that session",
              S["config"]["cylinders"] is not None
              and S["kline"]["physical_mode"] in ("OBD", "DIRECT ECU")
              and "scheduler" in S, list(S))
        check("M9 --compare runs over two recorder-written sessions",
              LA.compare([str(out), str(out2)], out=str(tmp)) == 0
              and (tmp / "scheduler_compare.md").exists())

        guided_checks(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d checks, %d failed" % (CHECKS, FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
