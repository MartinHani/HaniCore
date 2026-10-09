#!/usr/bin/env python3
r"""
hc_logic_capture.py - drive the bench logic analyzer (Saleae Logic 2) from a
bench script, and turn its export into edges a script can reason about.

    py tools\bench\hc_logic_capture.py probe                 # is it there?
    py tools\bench\hc_logic_capture.py grab --seconds 2 --out <dir>

Logic 2 must be running with its automation server on port 10430:

    "C:\Program Files\Logic\Logic.exe" --automation --automationPort 10430

THE BENCH ANALYZER is the first-generation 8-channel Logic (device type LOGIC,
id E998E0B8555513BA): fixed input thresholds, 24 MS/s ceiling. Every event this
file exists for is millisecond-scale, so 1 MS/s is the default and 1 us is the
resolution.

TIME. The export is relative to the capture's own zero. `Capture.utc0` is the
host UTC taken the instant start_capture() returns, which is AFTER the device
started sampling by the USB start latency - so wall-clock correlation with a
session log is good to a few hundred ms and is used only to LABEL edges.
Every duration this tool reports is measured on the analyzer's own clock.
"""
from __future__ import annotations

import argparse
import csv
import time
from datetime import datetime, timezone
from pathlib import Path

PORT = 10430
RATE = 1_000_000


def utc() -> datetime:
    return datetime.now(timezone.utc)


class Capture:
    """One manual-mode capture. start() -> ... -> stop(out_dir) -> edges."""

    def __init__(self, channels=(0,), rate=RATE, port=PORT):
        from saleae import automation as a      # logic2-automation
        self.a = a
        self.channels = list(channels)
        self.rate = rate
        self.mgr = a.Manager.connect(port=port, connect_timeout_seconds=8)
        devs = [d for d in self.mgr.get_devices() if not d.is_simulation]
        if not devs:
            raise SystemExit("Logic 2 is running but no analyzer is attached")
        self.device_id = devs[0].device_id
        self.cap = None
        self.utc0 = None

    def start(self, max_seconds: float | None = None):
        a = self.a
        dev = a.LogicDeviceConfiguration(enabled_digital_channels=self.channels,
                                         digital_sample_rate=self.rate)
        mode = (a.TimedCaptureMode(duration_seconds=max_seconds)
                if max_seconds else a.ManualCaptureMode())
        self.cap = self.mgr.start_capture(
            device_id=self.device_id, device_configuration=dev,
            capture_configuration=a.CaptureConfiguration(capture_mode=mode))
        self.utc0 = utc()
        return self.utc0

    def stop(self, out: Path, name: str = "capture") -> Path:
        out.mkdir(parents=True, exist_ok=True)
        try:
            self.cap.stop()
        except Exception:                                  # noqa: BLE001
            pass                                           # timed mode ended
        self.cap.wait()
        self.cap.export_raw_data_csv(directory=str(out),
                                     digital_channels=self.channels)
        self.cap.save_capture(filepath=str(out / ("%s.sal" % name)))
        self.cap.close()
        self.cap = None
        csvp = out / "digital.csv"
        (out / "capture_utc0.txt").write_text(
            self.utc0.isoformat() + "\n", encoding="ascii")
        return csvp

    def close(self):
        try:
            if self.cap:
                self.cap.stop()
                self.cap.close()
        except Exception:                                  # noqa: BLE001
            pass
        self.mgr.close()


def edges(csv_path: Path, channel: int = 0):
    """[(t_seconds, level)] - the first row is the initial level at t=0,
    every later row is a transition on that channel."""
    out = []
    with open(csv_path, newline="") as fh:
        rd = csv.reader(fh)
        head = next(rd)
        col = head.index("Channel %d" % channel)
        last = None
        for row in rd:
            lvl = int(row[col])
            if lvl != last:
                out.append((float(row[0]), lvl))
                last = lvl
    return out


def runs(ev, end_t: float):
    """[(level, t_start, duration)] from edges()."""
    r = []
    for i, (t, lvl) in enumerate(ev):
        t2 = ev[i + 1][0] if i + 1 < len(ev) else end_t
        r.append((lvl, t, t2 - t))
    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("probe", "grab"))
    ap.add_argument("--seconds", type=float, default=1.0)
    ap.add_argument("--out", default="la_grab")
    ap.add_argument("--channels", default="0")
    a = ap.parse_args()
    ch = [int(x) for x in a.channels.split(",")]
    c = Capture(ch)
    try:
        print("analyzer %s, Logic %s" % (c.device_id, c.mgr.get_app_info().app_version))
        if a.action == "grab":
            c.start(a.seconds)
            time.sleep(a.seconds)
            p = c.stop(Path(a.out), "grab")
            for chn in ch:
                print("D%d edges: %s" % (chn, edges(p, chn)[:20]))
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
