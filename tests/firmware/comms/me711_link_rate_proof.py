#!/usr/bin/env python3
r"""
me711_link_rate_proof.py - the V94 serial link, executed out of the LINKED
image in c167sim: pipelined echo accounting and the rate hunt
(hcts.c "PIPELINED ECHO ACCOUNTING", "THE LINK RATE").

    py tests\firmware\comms\me711_link_rate_proof.py             the image me711_image names
    set HANICORE_ME711_STEM=HaniCore_ME711_v93_awt_commission
    py tests\firmware\comms\me711_link_rate_proof.py --control   V93 r2 must FAIL (no hunt)

THE MODEL. The heartbeat rig's ASC0 (HB.Rig: echo loops every transmitted
byte back, S0TIC is the request latch) plus one thing it never needed: the
HOST'S RATE. The rig reads the ECU's S0BG; a request sent while the two
differ is delivered as what a receiver at the wrong rate DECODES from it -
tools/lib/uart_wire_model.py, a 16x-oversampled C167 ASC0 at the ECU's real rate
fed the host's real (FTDI) rate, pinned to the bench (V95): the framing-error
flag is raised only when the model says a stop bit was sampled low. Until V95
this gate raised it for EVERY wrong-rate request - an assumption, and exactly
the one the hardware broke: 115200 into 57600 decodes as clean bytes, and V94
never followed a 115200 host on the bench. The firmware never sees the host's
rate directly.

  A  boot: 57600, not locked; a 57600 request is answered first time and locks
  B  host moves between 57600 / 115200 / 124800 in EVERY ordered direction,
     and from a freshly booted (hunting) ECU to 115200: answered within
     LINK_BAD_LOCKED + 2 attempts, the ECU ends at the host's rate, locked
  C  a locked link survives two framing errors (noise) without moving
  D  while HUNTING a plain 'z' (the 200 ms stall) is ignored; once locked it
     is honoured
  E  pipelined echo: an 864-byte block is answered CRC-valid with the echo on
     and the NEXT request is answered too (no echo left in the ring);
     rxEchoLost does not move; with a wiring that does not echo, the reply
     is still valid
  F  linkState (OCH 842) publishes rate, lock and the change count

NOT PHYSICAL. Bench: tools\bench\me711_link_timing.py at each --baud.
"""
from __future__ import annotations

import argparse
import binascii
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_heartbeat_gap_proof as HB   # noqa: E402  the Rig
import me711_image as PI                 # noqa: E402
import uart_wire_model as UW             # noqa: E402

S0BG, S0CON = 0xFEB4, 0xFFB0
RATE = {0x15: 57600, 0x0A: 115200, 0x09: 124800}
FAILS = 0


def check(name, ok, detail=""):
    global FAILS
    print("  [%s] %-62s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def envelope(payload: bytes) -> bytes:
    return HB.envelope(payload)


class Link:
    def __init__(self, echo=True):
        self.rig = HB.Rig(PI.image(), HB.ENTRY_CURRENT, HB.TICK_CURRENT,
                          echo=echo)
        self.rig.run(PI.BOOT_STEPS + 750_000)

    def ecu_rate(self):
        return RATE.get(self.rig.mem.r16(S0BG) & 0x1FFF)

    def sym8(self, name):
        try:
            return self.rig.mem.r8(HB.sym(name))
        except SystemExit:
            return None

    def och16(self, off):
        """big endian, as put16() writes it (OCH = 0x380000 + 0x2000)"""
        a = 0x382000 + off
        return (self.rig.mem.r8(a) << 8) | self.rig.mem.r8(a + 1)

    def send(self, raw: bytes, host_rate: int, steps: int):
        """Put raw on the wire at host_rate; -> the envelopes transmitted."""
        start = len(self.rig.tx)
        if host_rate == self.ecu_rate():
            self.rig.queue_rx(self.rig.cpu.steps + 1, raw)
        else:
            dec = UW.receive(raw, UW.host_baud(host_rate),
                             UW.ecu_baud(self.rig.mem.r16(S0BG) & 0x1FFF))
            if dec:
                self.rig.queue_rx(self.rig.cpu.steps + 1,
                                  bytes(b for b, _fe in dec))
            if any(fe for _b, fe in dec):       # S0FE is sticky: one flag
                self.rig.mem.sfr[S0CON] = self.rig.mem.r16(S0CON) | 0x0200
        got = []
        done = 0
        while done < steps:
            self.rig.run(100_000)
            done += 100_000
            got = envelopes(bytes(b for _t, b in self.rig.tx[start:]))
            if got:
                self.rig.run(100_000)            # let the last echo settle
                break
        return got, bytes(b for _t, b in self.rig.tx[start:])

    def ask(self, payload: bytes, host_rate: int, steps=900_000):
        got, _ = self.send(envelope(payload), host_rate, steps)
        return got

    def until_answered(self, payload, host_rate, tries=8):
        """Attempts until a GOOD answer: TS_OK, the content the request asks
        for, sent while the ECU is at the host's rate. Until V95 any envelope
        counted - including a TS_BAD_CRC sent at the wrong rate, which the
        host would have received as noise."""
        for n in range(1, tries + 1):
            got = self.ask(payload, host_rate)
            if (got and self.ecu_rate() == host_rate
                    and got[-1][:1] == b"\x00" and good_body(payload, got[-1])):
                return n
        return None


def envelopes(tx: bytes):
    out = []
    i = 0
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


OCH8 = b"O" + (0).to_bytes(2, "big") + (8).to_bytes(2, "big")
# The bench's own request (me711_link_timing ident): its wrong-rate decode
# at 57600 is four CLEAN bytes, the case V94 never followed.
VREQ = b"V"


def good_body(payload: bytes, body: bytes) -> bool:
    if payload == VREQ:
        return b"HaniCore" in body
    if payload[:1] == b"O":
        return len(body) == 1 + int.from_bytes(payload[3:5], "big")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", action="store_true",
                    help="the image under test is one WITHOUT the hunt; "
                         "the gate must FAIL")
    a = ap.parse_args()
    print("=== V94 serial link: pipelined echo + rate hunt ===")
    print("  image %s  sha256 %s\n" % (PI.image().name, PI.sha256()))

    UW.selftest()                   # the wire model still matches the bench
    # from boot, hunting, straight to 115200 - the bench's first failure
    Hn = Link(echo=True)
    sw0 = Hn.sym8("hc_link_switches") or 0
    n = Hn.until_answered(VREQ, 115200)
    sw = ((Hn.sym8("hc_link_switches") or 0) - sw0) & 0xFF
    check("B  a booted (hunting) ECU follows a host at 115200: exactly 2 "
          "attempts, 1 switch",
          n == 2 and sw == 1 and Hn.ecu_rate() == 115200,
          "attempts %s, switches %d, ECU %s" % (n, sw, Hn.ecu_rate()))
    del Hn

    L = Link(echo=True)
    r0 = L.ecu_rate()
    check("A  boots at 57600", r0 == 57600, "S0BG rate %s" % r0)
    check("A  not locked before a valid request", L.sym8("hc_link_locked") == 0,
          "locked=%s" % L.sym8("hc_link_locked"))
    got = L.ask(OCH8, 57600)
    check("A  a 57600 request is answered first time",
          bool(got) and got[-1][:1] == b"\x00" and len(got[-1]) == 9,
          "%d envelopes" % len(got))
    check("A  ... and locks the link", L.sym8("hc_link_locked") == 1)

    # every ordered change: 57600->115200->124800->57600->124800->115200->57600
    # V96: EXACT, not "within 5". A locked link needs LINK_BAD_LOCKED (3)
    # bad requests, the third switches; each further rate costs one request;
    # then the answer. Switches = the distance in the rate ring. V95 passed
    # "within 5" while its hunt lapped past the right rate (bench: a locked
    # 115200 -> 124800 change took 4 switches) - a bound that loose hid it.
    ring = (57600, 115200, 124800)
    for host in (115200, 124800, 57600, 124800, 115200, 57600):
        before = L.ecu_rate()
        dist = (ring.index(host) - ring.index(before)) % 3
        want_n = 3 + (dist - 1) + 1
        sw0 = L.sym8("hc_link_switches") or 0
        n = L.until_answered(VREQ, host)
        sw = ((L.sym8("hc_link_switches") or 0) - sw0) & 0xFF
        check("B  host %6d (ECU was %6s): exactly %d attempts, %d switch(es)"
              % (host, before, want_n, dist), n == want_n and sw == dist,
              "attempts %s, switches %d" % (n, sw))
        check("B  ... the ECU is at %d and locked" % host,
              L.ecu_rate() == host and L.sym8("hc_link_locked") == 1,
              "ECU %s locked %s" % (L.ecu_rate(), L.sym8("hc_link_locked")))

    # C: two framing errors on a locked link, then a request at its rate
    host = L.ecu_rate()
    for _ in range(2):
        L.rig.mem.sfr[S0CON] = L.rig.mem.r16(S0CON) | 0x0200
        L.rig.run(200_000)
    check("C  two framing errors do not move a locked link",
          L.ecu_rate() == host, "ECU %s" % L.ecu_rate())
    check("C  ... and the next request is answered",
          bool(L.ask(OCH8, host)))

    # D: force a hunt (one bad request at another rate breaks nothing yet on
    # a locked link, so break the lock with LINK_BAD_LOCKED of them)
    other = 57600 if host != 57600 else 124800
    for _ in range(3):
        # spaced like a host's retries: FE is STICKY, so errors that land
        # between two polls of S0CON are one piece of evidence, not two
        L.send(envelope(OCH8), other, 900_000)
    hunting = L.sym8("hc_link_locked") == 0
    check("D  three bad requests break the lock (hunting)", hunting,
          "locked=%s" % L.sym8("hc_link_locked"))
    _, tx = L.send(b"z", L.ecu_rate(), 300_000)
    check("D  while hunting a plain 'z' is ignored",
          b"stall" not in tx and (L.sym8("hc_stall_req") or 0) == 0,
          "tx %r stall_req %s" % (tx[:12], L.sym8("hc_stall_req")))
    L.ask(OCH8, L.ecu_rate())
    _, tx = L.send(b"z", L.ecu_rate(), 300_000)
    check("D  once locked, 'z' is honoured", b"stall" in tx, "tx %r" % tx[:12])
    L.rig.run(3_000_000)                         # let the stall pass

    # E: a whole block with the echo on, then another request
    lost0 = L.rig.mem.r16(HB.sym("rx_echo_lost"))
    rate = L.ecu_rate()
    got = L.ask(b"O" + (0).to_bytes(2, "big") + (864).to_bytes(2, "big"),
                rate, steps=6_000_000)
    check("E  an 864-byte block with the echo on is CRC-valid",
          bool(got) and len(got[-1]) == 865, "%s" % [len(g) for g in got])
    # the interval between bytes STARTING ON THE WIRE (the rig's double-
    # buffered transmitter), in simulator steps, against its byte time: any
    # per-byte wait in the firmware shows as a bubble on top
    st = L.rig.tx_wire_steps[-(865 + 6):]
    gaps = sorted(st[i + 1] - st[i] for i in range(len(st) - 1))
    med = gaps[len(gaps) // 2] if gaps else 0
    byte_steps = L.rig.byte_ticks * L.rig.steps_per_tick
    ratio = med / byte_steps if byte_steps else 0.0
    print("       reply inter-byte interval: median %d steps, byte time %d "
          "steps (x%.3f)" % (med, byte_steps, ratio))
    check("E  bytes leave back to back (median interval <= 1.05 byte times)",
          0 < ratio <= 1.05, "x%.3f" % ratio)
    got2 = L.ask(OCH8, rate)
    check("E  ... and the next request is answered (ring clean)", bool(got2))
    lost1 = L.rig.mem.r16(HB.sym("rx_echo_lost"))
    check("E  rxEchoLost did not move with the echo present",
          lost1 == lost0, "%d -> %d" % (lost0, lost1))

    N = Link(echo=False)
    got = N.ask(OCH8, 57600)
    check("E  no-echo wiring: the reply is still valid", bool(got))
    got = N.ask(OCH8, 57600)
    check("E  ... and so is the next", bool(got))

    # F: the published word
    L.rig.run(300_000)                           # one more publish pass
    ls = L.och16(842)
    sw = L.sym8("hc_link_switches")
    want = None
    if sw is not None and L.ecu_rate() in (57600, 115200, 124800):
        want = ((sw << 8) | (0x10 if L.sym8("hc_link_locked") else 0)
                | {57600: 0, 115200: 1, 124800: 2}[L.ecu_rate()])
    check("F  linkState (OCH 842) = rate | lock<<4 | switches<<8",
          want is not None and ls == want,
          "0x%04X want %s, switches %s" % (ls, want, sw))

    print()
    if a.control:
        if FAILS:
            print("CONTROL (%s): FAILS as it must (%d)" % (PI.STEM, FAILS))
            return 0
        print("CONTROL PASSED - the gate cannot tell an image without the hunt")
        return 1
    print("LINK RATE PROOF %s - %d failed" % ("PASSES" if not FAILS else
                                                "FAILS", FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
