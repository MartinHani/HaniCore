#!/usr/bin/env python3
"""
me711_commission.py - what the ACTIVE commissioning tools share.

    me711_dbw_vehicle_test.py      ETB endpoint calibration + PID autotune
    me711_trigger_vehicle_test.py  the compression profile ('!K1')

The general logger (me711_vehicle_capture.py) stays READ-ONLY; these tools
reuse its .ini decoder, transport and envelope parser and add, per tool, the
exact controller commands that tool may send - nothing else can leave.

Every tool writes one evidence folder: metadata.json, console.log,
events.jsonl, frames.jsonl (every request/reply), the CSVs of what it
measured, before/after pages and summary.txt.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_vehicle_capture as VC        # noqa: E402

BAUD = 57600


def utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def evidence_root() -> Path:
    """Next to the tool in a release package (VEHICLE_EVIDENCE), else the
    workspace evidence folder - the logger's own rule."""
    return VC.default_evidence_root()


def candidate_ports() -> list[str]:
    """Serial ports that could be the KKL, an RP2040 USB device (VID 2E8A)
    excluded - it speaks text and must never receive a TunerStudio frame."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return ["COM3", "COM2"]
    out = []
    for p in list_ports.comports():
        if getattr(p, "vid", None) == 0x2E8A or "pico" in (p.description or "").lower():
            continue
        out.append(p.device)
    return out or ["COM3", "COM2"]


class ActiveLink(VC.Link):
    """The logger's Link with a tool-specific whitelist."""

    def __init__(self, tr, frames_log, allowed: bytes, clock=time.monotonic):
        super().__init__(tr, frames_log, clock)
        self.allowed = frozenset(allowed)

    def command(self, body: bytes) -> bool:
        """'!' + letter + args; TS_OK is the only answer ('!' never refuses on
        the wire - the outcome is published in output channels)."""
        payload = b"!" + body
        rep, err, _ = self.request(payload, 0.6)
        return rep is not None


class Session:
    """Console, events and the evidence folder of one tool run."""

    def __init__(self, kind: str, root: Path | None = None, argv=None):
        self.dir = (root or evidence_root()) / ("%s_%s" % (kind, utc_stamp()))
        self.dir.mkdir(parents=True, exist_ok=True)
        self.console = (self.dir / "console.log").open("w", encoding="utf-8")
        self.events = (self.dir / "events.jsonl").open("w", encoding="utf-8")
        self.frames = (self.dir / "frames.jsonl").open("w", encoding="utf-8")
        self.meta = {"tool": kind, "started_utc": VC.utc(),
                     "argv": list(argv or sys.argv), "steps": []}
        self.t0 = time.monotonic()

    def say(self, s: str = ""):
        line = "%8.2f  %s" % (time.monotonic() - self.t0, s)
        print(s, flush=True)
        self.console.write(line + "\n")
        self.console.flush()

    def event(self, kind: str, **kw):
        rec = {"t": round(time.monotonic() - self.t0, 3), "utc": VC.utc(),
               "event": kind}
        rec.update(kw)
        self.events.write(json.dumps(rec) + "\n")
        self.events.flush()

    def write_meta(self):
        self.meta["ended_utc"] = VC.utc()
        (self.dir / "metadata.json").write_text(json.dumps(self.meta, indent=2))

    def close(self):
        self.write_meta()
        for f in (self.console, self.events, self.frames):
            try:
                f.close()
            except Exception:
                pass


class Reader:
    """Reads only the output-channel windows a tool needs, as fast as the
    K-line allows, and decodes them through the .ini."""

    def __init__(self, link: ActiveLink, ini: VC.Ini, names: list[str]):
        self.link, self.ini = link, ini
        offs = []
        for n in names:
            if n in ini.scalars:
                typ, o = ini.scalars[n][0], ini.scalars[n][1]
                offs.append((o, o + VC.SIZES[typ]))
        offs.sort()
        # merge into windows, bridging gaps < 48 bytes (one request each)
        self.windows = []
        for a, b in offs:
            if self.windows and a - self.windows[-1][1] < 48:
                self.windows[-1][1] = max(self.windows[-1][1], b)
            else:
                self.windows.append([a, b])

    def read(self) -> dict | None:
        raw = {}
        for a, b in self.windows:
            blob, err, _ = self.link.och(a, b - a)
            if blob is None:
                return None
            raw.update(self.ini.decode(blob, a))
        comp = self.ini.evaluate(raw)
        out = dict(raw)
        out.update(comp)
        return out


def connect(port: str | None, ini_override: str | None, sess: Session,
            allowed: bytes):
    """Open the KKL (auto: every candidate port), identify the ECU, choose
    the .ini whose signature and version match. Returns (link, ini, sig, ver)
    or raises SystemExit with the reason."""
    ports = [port] if port and port != "auto" else candidate_ports()
    last = None
    for p in ports:
        try:
            tr = VC.SerialTransport(p, BAUD)
        except Exception as e:      # port absent / busy
            last = "%s: %s" % (p, e)
            continue
        link = ActiveLink(tr, sess.frames, allowed)
        sig = link.text(b"S")
        if not sig or "HaniCore" not in sig:
            tr.close()
            last = "%s: no HaniCore answer (%r)" % (p, sig)
            continue
        ver = link.text(b"V") or ""
        ini = VC.Ini(VC.pick_ini(sig, ver, ini_override))
        if ini.signature != sig:
            tr.close()
            raise SystemExit("the .ini %s declares %r but the ECU answers %r"
                             % (ini.path.name, ini.signature, sig))
        sess.meta.update({"port": p, "signature": sig, "version": ver,
                          "ini": str(ini.path), "ini_block": ini.block})
        sess.say("ECU on %s: %s / %s" % (p, ver, sig))
        sess.say("TunerStudio file: %s (output block %d)" % (ini.path.name,
                                                             ini.block))
        sess.event("CONNECTED", port=p, signature=sig, version=ver,
                   ini=ini.path.name)
        return link, ini, sig, ver
    raise SystemExit("no HaniCore ECU found (%s). Close TunerStudio, key ON, "
                     "check the KKL; pass --port COMx." % (last or ports))


def page_diff(ini_path: Path, before: bytes, after: bytes) -> list[str]:
    """Named fields that differ between two pages (the .ini's [Constants])."""
    import re
    txt = ini_path.read_text(encoding="utf-8", errors="replace")
    body = txt.split("[Constants]", 1)[1]
    body = re.split(r"^\[", body, maxsplit=1, flags=re.M)[0]
    out = []
    for line in body.splitlines():
        m = re.match(r"\s*(\w+)\s*=\s*(scalar|bits)\s*,\s*([US]\d\d)\s*,"
                     r"\s*(\d+)\s*,", line)
        if not m:
            continue
        name, typ, off = m.group(1), m.group(3), int(m.group(4))
        w = VC.SIZES[typ]
        a = int.from_bytes(before[off:off + w], "big", signed=typ[0] == "S")
        b = int.from_bytes(after[off:off + w], "big", signed=typ[0] == "S")
        if a != b:
            out.append("%s: %d -> %d" % (name, a, b))
    return out
