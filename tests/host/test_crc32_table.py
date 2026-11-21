#!/usr/bin/env python3
"""test_crc32_table.py - the K-line reply CRC table in hcserial711.c IS zlib.crc32.

The table is read out of the C source (all 256 entries), the byte-at-a-time
update the firmware uses is run over test data with it, and the result must
equal zlib.crc32. A wrong entry, a truncated table or a changed update rule
fails here before the ECU's replies would fail every TunerStudio/LibreTune CRC.
"""
import os
import re
import sys
import zlib
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "firmware/targets/me711/comms/hcserial711.c"


def main() -> int:
    text = SRC.read_text(errors="replace")
    m = re.search(r"crc_tab\[256\]\s*=\s*\{(.*?)\};", text, re.S)
    if not m:
        print("FAIL: crc_tab[256] not found in", SRC.name)
        return 1
    tab = [int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{8})uL", m.group(1))]
    if len(tab) != 256:
        print("FAIL: crc_tab has %d entries" % len(tab))
        return 1

    def crc(data: bytes) -> int:
        c = 0xFFFFFFFF
        for b in data:
            c = (c >> 8) ^ tab[(c ^ b) & 0xFF]
        return c ^ 0xFFFFFFFF

    for data in (b"", b"O", b"123456789", bytes(range(256)), os.urandom(4096)):
        if crc(data) != zlib.crc32(data):
            print("FAIL: crc mismatch on %d bytes" % len(data))
            return 1
    print("PASS: crc_tab (256 entries) reproduces zlib.crc32")
    return 0


if __name__ == "__main__":
    sys.exit(main())
