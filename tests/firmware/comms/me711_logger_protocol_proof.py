#!/usr/bin/env python3
r"""
me711_logger_protocol_proof.py - TunerStudio's high-speed loggers ('l'),
against the BOOTED image in c167sim, with the exact bytes TunerStudio sends.

    py tests\firmware\comms\me711_logger_protocol_proof.py

THE CONTRACT (rusEFI TS_SET_LOGGER_SWITCH, tunerstudio.cpp; the generated
[LoggerDefinition]):
  l 0x01 composite on | l 0x07 primary-tooth on | l 0x02 off | l 0x03 read
  * every answer is TS_OK. AN EMPTY BUFFER IS TS_OK WITH NO DATA - never
    rusEFI's 0x84: TunerStudio ends the session on any code with bit 7 set
    (hcts.h, read from TunerStudioMS.jar);
  * a read returns whole 8-byte records - rusEFI composite_logger_s with
    its byte order reversed: [acr][injectors][coils][flags][time 32 BE] -
    the full buffer, or what there is once the engine has stopped; the
    buffer is then free (toothLogReady falls);
  * the records are the bytes the trigger ISRs wrote (the test writes a
    known pattern into TGT_RAM_TLOG and reads it back through the link).
NEGATIVE CONTROL: the same read against a 0x84-answering mutation of the
reply parser is refused by this file's own reply check (bit 7 = FAIL).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
from me711_boot_test import Harness, IMG, sym_addr  # noqa: E402
from me711_ts_query_collision_proof import envelope, parse_reply  # noqa: E402
import me711_image as PI  # noqa: E402

TLOG = 0x380000 + 0x7600          # TGT_EXTRAM_BASE + TGT_RAM_TLOG
CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += 0 if ok else 1
    print("  [%s] %-62s %s" % ("PASS" if ok else "FAIL", name, detail))


def ts_ok(reply):
    """(ok, data): a CRC-valid envelope whose code is TS_OK (0) - and, as
    its own guard, never a code with bit 7 set."""
    p = parse_reply(reply)
    if p is None:
        return False, None
    _n, code, data, crc = p
    return (crc and code == 0 and not code & 0x80), data


def main() -> int:
    print("=== HaniCore ME7.1.1 - TunerStudio logger protocol ('l') ===")
    print("image: %s\n" % IMG)
    # the reply check itself refuses rusEFI's empty-buffer code
    fake = envelope(bytes([0x84]))
    check("control: a 0x84 'empty' reply is refused by the reply check",
          not ts_ok(fake)[0], fake.hex(" "))

    h = Harness(IMG, echo=True)
    err = h.run(PI.BOOT_STEPS)
    check("boot completes without a trap", err is None, err or "")
    n_addr, on_addr = sym_addr("hc_tlog_n"), sym_addr("hc_tlog_on")
    check("the logger state is in the map", None not in (n_addr, on_addr))

    def cmd(sub, steps=800000):
        tx, _e = h.send_raw(envelope(b"l" + bytes([sub])), steps=steps)
        return ts_ok(tx)

    ok, data = cmd(3)
    check("read with NOTHING logged -> TS_OK, no data (never 0x84)",
          ok and data == b"", repr(data))
    ok, data = cmd(1)
    check("l 0x01 (composite on) -> TS_OK", ok and data == b"",
          "hc_tlog_on %s" % h.mem.r8(on_addr))
    check("...the composite logger is on", h.mem.r8(on_addr) == 1)
    ok, data = cmd(3)
    check("read while armed, nothing captured -> TS_OK, no data",
          ok and data == b"", repr(data))

    # three records as the ISRs write them (tlog_edge): byte 0 spare,
    # 1 injectors, 2 coils, 3 flags (pri, cam1, trigger, sync, -, cam2),
    # 4..7 time, big-endian
    recs = [bytes([0, 0x01, 0x02, 0x09, 0x00, 0x00, 0x12, 0x34]),
            bytes([0, 0x00, 0x00, 0x08, 0x00, 0x00, 0x56, 0x78]),
            bytes([0, 0x00, 0x04, 0x0E, 0x00, 0x01, 0x00, 0x10])]
    for i, rec in enumerate(recs):
        for j, v in enumerate(rec):
            h.mem.w8(TLOG + 8 * i + j, v)
    h.mem.w16(n_addr, len(recs))
    ok, data = cmd(3, steps=1_500_000)
    check("engine stopped, 3 records -> TS_OK + 24 bytes, byte-exact",
          ok and data == b"".join(recs),
          (data or b"").hex(" "))
    check("...and the buffer is free afterwards (hc_tlog_n = 0)",
          h.mem.r16(n_addr) == 0, str(h.mem.r16(n_addr)))
    ok, data = cmd(3)
    check("the next read -> TS_OK, no data", ok and data == b"", repr(data))
    ok, _ = cmd(7)
    check("l 0x07 (primary tooth on) -> TS_OK, mode 2",
          ok and h.mem.r8(on_addr) == 2, str(h.mem.r8(on_addr)))
    ok, _ = cmd(2)
    check("l 0x02 (off) -> TS_OK, logger off",
          ok and h.mem.r8(on_addr) == 0, str(h.mem.r8(on_addr)))
    ok, data = cmd(9)
    check("an unknown sub-command -> TS_OK, no data (never a bit-7 code)",
          ok and data == b"", repr(data))

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
