#!/usr/bin/env python3
r"""
me711_kwp_entry_proof.py - the V94 VAG/KWP vehicle entry, executed out of the
LINKED image in c167sim (hckwp_me711.c + firmware/comms/hckline.c + hcts.c's hooks).

    py tests\firmware\comms\me711_kwp_entry_proof.py
    set HANICORE_ME711_STEM=HaniCore_ME711_v93_awt_commission
    py tests\firmware\comms\me711_kwp_entry_proof.py --control       V93 r2 must FAIL

THE TESTER, MODELLED. The heartbeat rig's ASC0 (echo on, the double-buffered
transmitter) plus the RXD0 PIN: the tester drives P3.11 for the 5-baud byte
(200 ms a bit, LSB first, start 0, stop 1) and the rig writes the level into
the simulated P3 - what the firmware samples. While the tester talks at a
rate the ECU is not at (S0BG), its bytes arrive as garbage with the framing
error raised, as in me711_link_rate_proof. Every KWP frame is built here from
ISO 14230 (fmt 0x80|len, target 0x01, source 0xF1, data, 8-bit sum).

  A  idle: a TunerStudio request at 57600 after a long quiet line is answered
     first time (the 5-baud decoder never takes a UART byte)
  B  5-baud 0x01 -> the ECU moves to 10400 and sends 55 EF 8F; the tester's
     complement 70 -> FE; StartCommunication -> C1
  C  GOFAST before IDENTIFY -> 7F B1 22 and no rate change (the gate)
  D  IDENTIFY B0 'HC' -> F0 + the TunerStudio signature (the layout id)
  E  GOFAST 124800 -> F1 03 at 10400, then the ECU is at 124800, LOCKED, and a
     TunerStudio request at 124800 is answered
  F  a wrong 5-baud address (0x33) opens nothing; kwpCounts counts it
  G  5-baud 0x01 and then no complement: one retry, then back to the hunt at
     57600 - and TunerStudio at 57600 works again
  H  OCH 844/846 publish the KWP state and counters

NOT PHYSICAL. The bench/vehicle steps are in the maintainer's design records.
"""
from __future__ import annotations

import argparse
import re
import binascii
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import c167sim as S                      # noqa: E402
import me711_heartbeat_gap_proof as HB   # noqa: E402
import me711_image as PI                 # noqa: E402

S0BG, S0CON, P3 = 0xFEB4, 0xFFB0, 0xFFC4
BG_RATE = {0x15: 57600, 0x0A: 115200, 0x09: 124800, 0x77: 10400}
FAILS = 0
SIG = b"rusEFI HaniCore ME711 "


def check(name, ok, detail=""):
    global FAILS
    print("  [%s] %-62s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def kwp(data: bytes) -> bytes:
    f = bytes([0x80 | len(data), 0x01, 0xF1]) + data
    return f + bytes([sum(f) & 0xFF])


def envelopes(tx: bytes):
    out, i = [], 0
    while i + 6 <= len(tx):
        n = (tx[i] << 8) | tx[i + 1]
        if 1 <= n <= 4097 and i + 6 + n <= len(tx):
            body = tx[i + 2:i + 2 + n]
            if int.from_bytes(tx[i + 2 + n:i + 6 + n], "big") == \
                    (binascii.crc32(body) & 0xFFFFFFFF):
                out.append(body)
                i += 6 + n
                continue
        i += 1
    return out


class Tester:
    def __init__(self):
        self.rig = HB.Rig(PI.image(), HB.ENTRY_CURRENT, HB.TICK_CURRENT,
                          echo=True)
        self.ms = int(HB.TPMS / 10 * self.rig.steps_per_tick)  # steps / ms
        self.level = 1
        # P3.11 IS AN INPUT PIN: a read returns the PIN, whatever the output
        # latch holds (C167 ports). The simulator keeps P3 as one register, so
        # any firmware write to the P3 latch would otherwise show up as the
        # tester's line - the first version of this proof lost a start bit
        # exactly that way. Every read path is overridden: byte/word reads
        # (Mem.r8, which Mem.r16 uses) and the direct SFR read bit
        # instructions use (CPU._sget).
        tester = self
        r8h, w8h, w16h = self.rig._hooks

        def r8(s_, a, _o=r8h):
            v = _o(s_, a)
            if (a & 0xFFFFFF) == P3 + 1:            # high byte: bit 3 = P3.11
                v = (v | 0x08) if tester.level else (v & ~0x08)
            return v
        self.rig._hooks = (r8, w8h, w16h)
        S.Mem.r8, S.Mem.w8, S.Mem.w16 = self.rig._hooks
        orig_sget = S.CPU._sget

        def sget(cpu_, a, _o=orig_sget):
            v = _o(cpu_, a)
            if a == P3:
                v = (v | 0x0800) if tester.level else (v & ~0x0800)
            return v
        S.CPU._sget = sget
        self.run(PI.BOOT_STEPS + 750_000)

    def pin(self, hi):
        self.level = 1 if hi else 0
        v = self.rig.mem.sfr.get(P3, 0)
        self.rig.mem.sfr[P3] = (v | 0x0800) if hi else (v & ~0x0800)

    def run(self, steps):
        while steps > 0:
            n = min(steps, 50_000)
            self.rig.run(n)
            self.pin(self.level)        # firmware writes to P3 keep bit 11
            steps -= n

    def run_ms(self, ms):
        self.run(int(ms * self.ms))

    def rate(self):
        return BG_RATE.get(self.rig.mem.r16(S0BG) & 0x1FFF)

    def five_baud(self, addr):
        bits = [0] + [(addr >> i) & 1 for i in range(8)] + [1]
        for b in bits:
            self.pin(b)
            self.run_ms(200)
        self.pin(1)

    def send(self, raw: bytes, host_rate: int):
        if host_rate == self.rate():
            self.rig.queue_rx(self.rig.cpu.steps + 1, raw)
        else:
            self.rig.queue_rx(self.rig.cpu.steps + 1,
                              bytes(((b * 7 + 0x35) & 0xFF) | 0x80
                                    for b in raw))
            self.rig.mem.sfr[S0CON] = self.rig.mem.r16(S0CON) | 0x0200

    def tx_since(self, mark):
        return bytes(b for _t, b in self.rig.tx[mark:])

    def mark(self):
        return len(self.rig.tx)

    def ask(self, payload, host_rate, ms=120):
        m = self.mark()
        self.send(HB.envelope(payload), host_rate)
        self.run_ms(ms)
        return envelopes(self.tx_since(m))

    def och16(self, off):
        a = 0x382000 + off
        return (self.rig.mem.r8(a) << 8) | self.rig.mem.r8(a + 1)


OCH8 = b"O" + (0).to_bytes(2, "big") + (8).to_bytes(2, "big")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", action="store_true")
    a = ap.parse_args()
    print("=== V94 VAG/KWP vehicle entry ===")
    print("  image %s  sha256 %s\n" % (PI.image().name, PI.sha256()))

    T = Tester()
    T.run_ms(600)                                   # a long quiet line
    got = T.ask(OCH8, 57600)
    check("A  quiet line, then TunerStudio at 57600: answered first time",
          bool(got), "%d envelopes" % len(got))

    # I (V97): a request whose own low bits ARM the 5-baud decoder (the real
    # wire does: the decoder samples RXD once per main-loop pass), then the
    # whole output-channel block - a reply longer than the 180 ms start bit,
    # during which the sampler does not run - then the next request. Until
    # the fix the decoder "qualified" a start bit it never watched and
    # swallowed that next request (bench 2026-09-29: 8 of 20 lost).
    och = int(re.search(r"#define\s+TGT_OCH_SIZE\s+(\d+)", (Path(__file__).resolve()
              .parents[3] / "firmware/targets/me711/hctarget.h")
              .read_text()).group(1))
    # The block itself (950 bytes, ~190 ms) only just crosses 180 ms - the
    # bench lost 1 in 4, the simulator's pass phase lands under it - so the
    # read reaches 300 bytes into the extended window (~220 ms), which the
    # ECU serves: no pass phase can hide the defect then.
    big = och + 300
    lost = 0
    seen = []
    for _ in range(3):
        T.run_ms(400)                               # > 300 ms idle: armed
        # the request's leading bits are on the wire while a main-loop pass
        # samples RXD (a pass ~1.7 ms, a request 1.9 ms on the wire): LOW
        T.pin(0)
        T.run_ms(3)
        T.pin(1)
        m = T.mark()
        T.send(HB.envelope(b"O" + (0).to_bytes(2, "big") + big.to_bytes(2, "big")),
               57600)
        # the long reply goes out: WAIT FOR IT (V98: 1524 bytes take ~265 ms
        # on the wire, longer in the simulator's short millisecond; a fixed
        # 400 ms sent the next request into the reply's tail)
        full = []
        for _ in range(30):
            T.run_ms(50)
            full = [e for e in envelopes(T.tx_since(m)) if len(e) == big + 1]
            if full:
                break
        T.run_ms(20)
        got = T.ask(OCH8, 57600)
        lost += (not full) + (not got)
        seen.append("%s/%s" % ("full" if full else "NO-REPLY(%d env %s)" % (
            len(envelopes(T.tx_since(m))),
            [len(e) for e in envelopes(T.tx_since(m))][:3]),
            "next" if got else "NO-NEXT"))
    check("I  after a %d-byte reply that followed an arming request, the next "
          "request is answered (3 of 3)" % big, lost == 0,
          "%d lost %s" % (lost, seen))

    # B: 5-baud 0x01, then the handshake at 10400
    T.run_ms(400)
    m = T.mark()
    T.five_baud(0x01)
    # V96: a tester REACTS to the keybytes (ISO 14230: W1 <= 300 ms, then the
    # complement within W4). A fixed 120 ms wait passed or failed on the
    # simulated main-loop phase: V96 put 8F at 130 ms (bench V95: 69 ms).
    t_sync = None
    for i in range(30):
        T.run_ms(10)
        if T.tx_since(m).endswith(b"\x55\xEF\x8F"):
            t_sync = (i + 1) * 10
            break
    tx = T.tx_since(m)
    check("B  keybytes inside W1 max (300 ms)", t_sync is not None,
          "55 EF 8F complete at %s ms" % t_sync)
    check("B  5-baud 0x01 moves the ECU to 10400", T.rate() == 10400,
          "rate %s" % T.rate())
    check("B  ... and it sends sync + keybytes 55 EF 8F",
          tx.endswith(b"\x55\xEF\x8F"), tx.hex())
    m = T.mark()
    T.send(b"\x70", 10400)
    T.run_ms(30)
    check("B  tester complement 70 -> ECU complement FE",
          T.tx_since(m) == b"\xFE", T.tx_since(m).hex())
    m = T.mark()
    T.send(kwp(b"\x81"), 10400)
    T.run_ms(60)
    r = T.tx_since(m)
    check("B  StartCommunication -> positive C1",
          r[3:4] == b"\xC1", r.hex())

    # C: GOFAST before IDENTIFY
    m = T.mark()
    T.send(kwp(b"\xB1\x03"), 10400)
    T.run_ms(60)
    r = T.tx_since(m)
    check("C  GOFAST before IDENTIFY -> 7F B1 22, no rate change",
          r[3:6] == b"\x7F\xB1\x22" and T.rate() == 10400,
          "%s rate %s" % (r.hex(), T.rate()))

    # D: IDENTIFY
    m = T.mark()
    T.send(kwp(b"\xB0\x48\x43"), 10400)
    T.run_ms(120)
    r = T.tx_since(m)
    check("D  IDENTIFY 'HC' -> F0 + the TunerStudio signature",
          r[3:4] == b"\xF0" and SIG in r, r[:40])

    # E: GOFAST 124800
    m = T.mark()
    T.send(kwp(b"\xB1\x03"), 10400)
    T.run_ms(60)
    r = T.tx_since(m)
    check("E  GOFAST 124800 -> F1 03 (sent at 10400)",
          r[3:5] == b"\xF1\x03", r.hex())
    T.run_ms(20)
    locked = T.rig.mem.r8(HB.sym("hc_link_locked")) if not a.control else 0
    check("E  ... then the ECU is at 124800 and locked",
          T.rate() == 124800 and locked == 1,
          "rate %s locked %s" % (T.rate(), locked))
    got = T.ask(OCH8, 124800)
    check("E  ... and TunerStudio at 124800 is answered", bool(got))

    # F: a wrong address
    T.run_ms(400)
    cnt0 = T.och16(846)
    T.five_baud(0x33)
    T.run_ms(200)
    cnt1 = T.och16(846)
    check("F  5-baud 0x33 opens nothing (rate unchanged, still locked)",
          T.rate() == 124800, "rate %s" % T.rate())
    check("F  ... and is counted as a wrong address",
          (cnt1 & 0xFF) == ((cnt0 & 0xFF) + 1) & 0xFF,
          "%04X -> %04X" % (cnt0, cnt1))

    # G: 5-baud 0x01, no complement
    T.run_ms(400)
    T.five_baud(0x01)
    T.run_ms(400)                   # W4 50 ms, one retry, W4 again, idle
    check("G  no complement: one retry, then back to the hunt at 57600",
          T.rate() == 57600, "rate %s" % T.rate())
    got = T.ask(OCH8, 57600)
    check("G  ... and TunerStudio at 57600 works again", bool(got))

    st, cn = T.och16(844), T.och16(846)
    check("H  kwpState: 1 good init, idle; kwpCounts: 1 failed, 1 wrong addr",
          (st >> 8) == 1 and (st & 15) == 0 and cn == 0x0101,
          "844=%04X 846=%04X" % (st, cn))

    print()
    if a.control:
        if FAILS:
            print("CONTROL (%s): FAILS as it must (%d)" % (PI.STEM, FAILS))
            return 0
        print("CONTROL PASSED - the gate cannot tell an image without KWP")
        return 1
    print("KWP ENTRY PROOF %s - %d failed" % ("PASSES" if not FAILS else
                                               "FAILS", FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
