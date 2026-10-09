"""Linked ME7.1.1 CRC primitive agrees with IEEE/zlib for every byte."""
import binascii
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools/lib"))
import hcpaths  # noqa: F401,E402
import me711_trigger_test as T  # noqa: E402
import me711_image as I  # noqa: E402


def update(r, state, byte):
    r.call("hc_crc32_update", state & 0xFFFF, state >> 16, byte)
    return r.c.gr(4) | (r.c.gr(5) << 16)


def main():
    print("image", I.sha256())
    r = T.Call()
    failures = []
    for state in (0, 0xFFFFFFFF, 0x12345678):
        for byte in range(256):
            expected = binascii.crc32(bytes([byte]), state ^ 0xFFFFFFFF) ^ 0xFFFFFFFF
            if update(r, state, byte) != expected:
                failures.append((state, byte))
    crc = 0xFFFFFFFF
    for byte in b"123456789":
        crc = update(r, crc, byte)
    vector_ok = crc ^ 0xFFFFFFFF == 0xCBF43926
    print("[%s] all 768 byte/state combinations conform: %s" % ("PASS" if not failures else "FAIL", failures[:4]))
    print("[%s] standard 123456789 vector: %08X" % ("PASS" if vector_ok else "FAIL", crc ^ 0xFFFFFFFF))
    address = T.sym("hc_crc32_update") - 0x800000
    r.m.flash[address:address + 2] = bytes([0xDB, 0])
    r.c.sr(4, 0x1357); r.c.sr(5, 0x2468)
    crc = 0xFFFFFFFF
    for byte in b"123456789":
        crc = update(r, crc, byte)
    negative_ok = crc ^ 0xFFFFFFFF != 0xCBF43926
    print("[%s] bypassed CRC is rejected by the same vector" % ("PASS" if negative_ok else "FAIL"))
    return 0 if not failures and vector_ok and negative_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
