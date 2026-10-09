#!/usr/bin/env python3
r"""me711_och_snapshot.py - one decoded output-channel block from the live ECU.

    py tools\bench\me711_och_snapshot.py --ini release\...\x.ini --out evidence\...\s.json

Every other physical driver in this tree open-codes its own small subset of the
channel map (WANT tuples, hand-written offsets).  That was fine while a run
cared about six numbers.  The real-TunerStudio Burn investigation cares about
ALL of them either side of every operation, so the decode is done ONCE here,
straight out of the .ini the firmware was released with, and nothing is
hand-listed.

Read-only.  It sends one 'O' and nothing else.
"""
from __future__ import annotations

import argparse
import binascii
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import serial

KKL_PORT, KKL_BAUD = "COM3", 57600


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def envelope(payload: bytes) -> bytes:
    crc = binascii.crc32(payload) & 0xFFFFFFFF
    return bytes([0x00, len(payload)]) + payload + crc.to_bytes(4, "big")


class OchMap:
    """The [OutputChannels] scalars of one .ini, by name."""

    SIZES = {"U08": 1, "S08": 1, "U16": 2, "S16": 2, "U32": 4, "S32": 4}

    def __init__(self, ini: Path):
        txt = ini.read_text(encoding="utf-8", errors="replace")
        body = txt.split("[OutputChannels]", 1)[1]
        body = re.split(r"^\[", body, maxsplit=1, flags=re.M)[0]
        self.block = int(re.search(r"^\s*ochBlockSize\s*=\s*(\d+)",
                                   body, re.M).group(1))
        self.fields = []
        for m in re.finditer(r"^\s*(\w+)\s*=\s*scalar,\s*([US]\d\d),\s*(\d+)",
                             body, re.M):
            name, typ, off = m.group(1), m.group(2), int(m.group(3))
            if typ in self.SIZES:
                self.fields.append((name, typ, off))

    def decode(self, blob: bytes) -> dict:
        out = {}
        for name, typ, off in self.fields:
            n = self.SIZES[typ]
            if off + n > len(blob):
                continue
            v = int.from_bytes(blob[off:off + n], "big",
                               signed=typ[0] == "S")
            out[name] = v
        return out


def read_och(port: str, baud: int, count: int, tries: int = 4,
             transcript: Path | None = None):
    pl = b"O" + (0).to_bytes(2, "big") + count.to_bytes(2, "big")
    req = envelope(pl)
    ser = serial.Serial(port, baud, timeout=0.2, write_timeout=2.0)
    try:
        why = "not attempted"
        for _ in range(tries):
            ser.reset_input_buffer()
            ser.write(req)
            ser.flush()
            got = bytearray()
            want = len(req) + count + 7
            deadline = time.monotonic() + 12.0
            while time.monotonic() < deadline:
                part = ser.read(512)
                if part:
                    got.extend(part)
                    deadline = min(deadline, time.monotonic() + 1.0)
                if len(got) >= want:
                    break
            raw = bytes(got)
            if transcript:
                with transcript.open("a", encoding="ascii") as fh:
                    fh.write("%s TX %s\n%s RX %s\n"
                             % (stamp(), req.hex(), stamp(), raw.hex()))
            # SCAN FOR THE FRAME, NEVER ASSUME IT STARTS AFTER THE ECHO.
            #
            # The first version took the reply to begin exactly len(req) bytes
            # in, and reported `crc BAD` four times running on a link that was
            # working - the very first transaction after a long idle had one
            # extra byte in front of it, and every byte after that was read one
            # position late. An instrument that mis-reads a good link is worse
            # than one that fails, because this tool's output is EVIDENCE.
            #
            # So do what a host really does: walk the stream, and take the
            # first envelope whose length, code and CRC32 all agree. That is
            # the same rule me711_burn_session_proof.frames() uses.
            blob = None
            for at in range(0, max(0, len(raw) - 6)):
                n = (raw[at] << 8) | raw[at + 1]
                if n != count + 1 or at + 6 + n > len(raw):
                    continue
                cand = raw[at + 2:at + 2 + n]
                crc = int.from_bytes(raw[at + 2 + n:at + 6 + n], "big")
                if cand[0] == 0 and crc == (binascii.crc32(cand) & 0xFFFFFFFF):
                    blob = cand
                    break
            if blob is not None:
                return blob[1:], "ok"
            why = ("no CRC-valid %d-byte frame in %d received bytes"
                   % (count + 1, len(raw)))
            time.sleep(0.6)
        return None, why
    finally:
        ser.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ini", type=Path, required=True)
    ap.add_argument("--port", default=KKL_PORT)
    ap.add_argument("--baud", type=int, default=KKL_BAUD)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--tag", default="")
    ap.add_argument("--transcript", type=Path)
    a = ap.parse_args()

    m = OchMap(a.ini)
    blob, why = read_och(a.port, a.baud, m.block, transcript=a.transcript)
    res = {"utc": stamp(), "tag": a.tag, "ini": str(a.ini),
           "ochBlockSize": m.block, "parsed": why}
    if blob is not None:
        res["channels"] = m.decode(blob)
        res["raw"] = blob.hex()
    print(json.dumps(res, indent=2, sort_keys=True))
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n",
                         encoding="ascii")
    return 0 if blob is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
