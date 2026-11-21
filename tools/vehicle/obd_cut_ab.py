"""OBD line-cut A/B (2026-11-06, 018DC on the AWT car): does a LONG ECU reply cut
the line through the instrument cluster?

Car logs 05.11: the line was cut 3.0 s after every 1714-byte reply at 10400
(0.75 s at 57600) and stayed cut until a new 5-baud entry; seconds of short
replies (<= 263 B) before it were fine. TunerStudio, which held OBD on the
Porsche, never asked for more than 256 B.

    py tools\\vehicle\\obd_cut_ab.py --port COM3 [--rate 57600] [--entry 5baud|direct]

  A  SHORT: --short-s seconds of TunerStudio-sized reads (<= 25 ms on the wire)
  B  LONG:  one whole-block read, then short reads; time to the first silence
  (B is repeated --long-n times, re-entering by 5-baud after each cut)

Every exchange goes to <out>/ab.csv; the verdict is printed and written to
<out>/verdict.txt. Key on, engine off. Read-only: it never writes the ECU.
"""
import argparse
import binascii
import csv
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from me711_vehicle_test import SerialPort, envelope, RATE_CODE, EXT_KLSTAT, \
    KLSTAT_NAMES  # noqa: E402

BLOCK = 1696                    # ochBlockSize of the DC .ini (BBDC7743)


class AB:
    def __init__(self, port, rate, out):
        self.p = SerialPort(port, rate)
        self.rate = rate
        self.t0 = time.perf_counter()
        os.makedirs(out, exist_ok=True)
        self.out = out
        self.f = open(os.path.join(out, "ab.csv"), "w", newline="")
        self.w = csv.writer(self.f)
        self.w.writerow(["t", "phase", "baud", "cmd", "asked", "ok", "got",
                         "ms", "note"])
        self.log_lines = []
        self.cut_kind = []
        self.switches = None

    def t(self):
        return time.perf_counter() - self.t0

    def say(self, s):
        line = "[%7.2f] %s" % (self.t(), s)
        print(line, flush=True)
        self.log_lines.append(line)

    def row(self, *r):
        self.w.writerow(["%.3f" % self.t()] + list(r))
        self.f.flush()

    def ts(self, payload, phase, asked=0, timeout=0.6):
        """One CRC-enveloped request. -> body or None."""
        req = envelope(payload)
        timeout *= max(1.0, 57600.0 / self.p.baud) + asked * 10.0 / self.p.baud
        self.p.reset_input()
        t0 = time.perf_counter()
        self.p.write(req)
        buf = bytearray()
        end = t0 + timeout
        body = None
        while time.perf_counter() < end:
            buf += self.p.read(4096, 0.005)
            d = bytes(buf)
            if d.startswith(req):
                d = d[len(req):]
            elif len(d) < len(req):
                continue
            if len(d) >= 2:
                n = (d[0] << 8) | d[1]
                if len(d) >= n + 6:
                    blob = d[2:2 + n]
                    crc = int.from_bytes(d[2 + n:6 + n], "big")
                    if crc == binascii.crc32(blob) & 0xFFFFFFFF and blob[:1] == b"\0":
                        body = blob[1:]
                    break
        ms = (time.perf_counter() - t0) * 1e3
        got = len(buf) - len(req) if bytes(buf).startswith(req) else len(buf)
        self.row(phase, self.p.baud, payload[:1].decode("latin1"), asked,
                 int(body is not None), got, round(ms, 1),
                 "" if body is not None else ("echo only" if got <= 0 else "cut mid-reply"))
        return body

    def och(self, off, cnt, phase):
        return self.ts(b"O" + off.to_bytes(2, "big") + cnt.to_bytes(2, "big"),
                       phase, cnt)

    def kwp(self, data):
        f = bytes([0x80 | len(data), 0x01, 0xF1]) + data
        f += bytes([sum(f) & 0xFF])
        self.p.write(f)
        self.p.read(len(f), 0.3)
        h = self.p.read(1, 0.6)
        if not h:
            return None
        rest = self.p.read(2 + (h[0] & 0x3F) + 1, 0.3)
        return (h + rest)[3:-1]

    def enter_5baud(self):
        time.sleep(2.6)                       # VW: >= 2.6 s between slow inits
        self.p.five_baud(0x01)
        sync = self.p.read(3, 0.8)
        if sync != b"\x55\xEF\x8F":
            self.say("5-baud: sync %s (want 55ef8f)" % sync.hex())
            return False
        time.sleep(0.02)
        self.p.write(b"\x70")
        self.p.read(1, 0.3)
        if self.p.read(1, 0.3) != b"\xFE":
            self.say("5-baud: no complement")
            return False
        time.sleep(0.03)
        if (self.kwp(b"\x81") or b"")[:1] != b"\xC1":
            self.say("5-baud: StartCommunication failed")
            return False
        if (self.kwp(b"\xB0HC") or b"")[:1] != b"\xF0":
            self.say("5-baud: IDENTIFY failed")
            return False
        d = self.kwp(bytes([0xB1, RATE_CODE[self.rate]]))
        if (d or b"")[:1] != b"\xF1":
            self.say("5-baud: GOFAST %d refused %r" % (self.rate, d))
            return False
        time.sleep(0.03)
        self.p.set_baud(self.rate)
        for _ in range(6):
            if self.ts(b"S", "entry") is not None:
                self.say("entered by 5-baud at %d" % self.rate)
                return True
            time.sleep(0.05)
        self.say("5-baud: no answer at %d after GOFAST" % self.rate)
        return False

    def enter_direct(self):
        self.p.set_baud(self.rate)
        for _ in range(8):
            if self.ts(b"S", "entry") is not None:
                self.say("entered DIRECT at %d" % self.rate)
                return True
            time.sleep(0.1)
        return False

    def enter(self, how):
        if how == "direct" and self.enter_direct():
            return True
        for _ in range(3):
            if self.enter_5baud():
                return True
        return False

    def accounts(self, tag):
        b = self.och(BLOCK + EXT_KLSTAT, 12, "accounts")
        if b and len(b) >= 12:
            v = [int.from_bytes(b[i:i + 2], "big") for i in range(0, 12, 2)]
            self.say("ECU K-line accounts (%s): %s" % (
                tag, ", ".join("%s %d" % kv for kv in zip(KLSTAT_NAMES, v))))
        # hcdiag711.c: rxBytes 16, rxReqs 18, rxResync 20, rxFrameErr 24,
        # rxEchoLost 28; linkState 842 (bits 0..1 rate, 4 locked, 8..15
        # rate changes since boot), kwpState 844 (8..15 good inits)
        r = self.och(16, 14, "accounts")
        s = self.och(842, 4, "accounts")
        if r and s and len(r) >= 14 and len(s) >= 4:
            w = lambda b, i: int.from_bytes(b[i:i + 2], "big")
            ls = w(s, 0)
            self.switches = ls >> 8
            self.say("ECU link (%s): rate %s %s, rate changes %d, good KWP inits %d | "
                     "rxBytes %d rxReqs %d rxResync %d rxFrameErr %d rxEchoLost %d" % (
                         tag, {0: "57600", 1: "124800/115200", 2: "124800", 3: "10400"}[ls & 3],
                         "locked" if ls & 0x10 else "hunting", ls >> 8, w(s, 2) >> 8,
                         w(r, 0), w(r, 2), w(r, 4), w(r, 8), w(r, 12)))

    def which_rate(self):
        """After a cut, before any entry: does the ECU answer at another rate
        (it moved its rate - ECU side) or at none (the line beyond it closed)?"""
        time.sleep(0.3)
        # LISTEN FIRST (2026-11-06 car): is anyone else talking on the line?
        # 10400 is what other modules use; our side sends nothing
        for rate in (10400, self.rate):
            self.p.set_baud(rate)
            heard = self.p.read(512, 1.0)
            self.row("listen", rate, "-", 0, int(bool(heard)), len(heard), 1000,
                     heard.hex()[:200])
            if heard:
                self.say("after cut: heard %d byte(s) at %d with nobody asking: %s"
                         % (len(heard), rate, heard.hex()[:64]))
        # ... and EVERY rate, 10400 included: the ECU's own link state read
        # 10400 after two of the 06.11 car cuts, and this probe never tried it
        for rate in dict.fromkeys((self.rate, 57600, 124800, 10400)):
            self.p.set_baud(rate)
            for _ in range(2):
                if self.ts(b"S", "after cut") is not None:
                    self.p.set_baud(self.rate)
                    return rate
                time.sleep(0.05)
        self.p.set_baud(self.rate)
        return None

    def recover(self, tag):
        r = self.which_rate()
        if r is None:
            self.say("%s: silent at every rate - the LINE closed (not the ECU's rate)" % tag)
        else:
            self.say("%s: the ECU answers at %d%s" % (
                tag, r, " - it MOVED its rate" if r != self.rate else
                " again without an entry"))
        before = self.switches
        if r is not None:
            if r != self.rate:
                self.p.set_baud(r)
                self.accounts(tag)
                self.p.set_baud(self.rate)
            ok = r == self.rate or self.enter("5baud")
        else:
            ok = self.enter("5baud")
        if ok:
            self.accounts("after " + tag)
        moved = None
        if before is not None and self.switches is not None and r is not None:
            # an entry adds rate changes itself; without one the count is the ECU's own
            moved = (self.switches - before) & 0xFF if r == self.rate else None
        self.cut_kind.append((tag, r, moved))
        if moved:
            self.say("%s: the ECU changed its rate %d time(s) by itself (noise on the line)" % (tag, moved))
        return ok

    def cap(self):
        return max(16, min(256, self.p.baud * 25 // 10000 // 16 * 16))

    def short(self, seconds, phase):
        """TunerStudio-sized reads for `seconds`. -> time of the first
        silence or None."""
        end = time.perf_counter() + seconds
        off, n = 0, 0
        while time.perf_counter() < end:
            c = min(self.cap(), BLOCK - off)
            if self.och(off, c, phase) is None and \
                    self.och(off, c, phase) is None:        # plugin: re-send once
                return self.t()
            n += 1
            off = (off + c) % BLOCK
            time.sleep(0.004)                 # TunerStudio's median gap
        self.say("%s: %d short reads, no cut" % (phase, n))
        return None


FINDER = (                          # (label, entry, session rate)
    # FROM A FRESH KEY-ON, NO 5-BAUD YET: plugin 2.3.0's AUTO went DIRECT
    # first and never sent a 5-baud once DIRECT answered; every car session
    # in the logs that died had been entered by 5-baud (2026-11-06 night)
    ("DIRECT 57600, no 5-baud", "direct", 57600),
    ("DIRECT 124800, no 5-baud", "direct", 124800),
    ("5-baud, stay at 10400", "5baud", 10400),      # what VCDS does
    ("5-baud, then 57600", "5baud", 57600),
    ("5-baud, then 124800", "5baud", 124800),
    # and DIRECT again: does a 5-baud earlier in this key cycle spoil it?
    ("DIRECT 57600 after 5-baud", "direct", 57600),
)


def finder(ab, hold_s, v):
    """Every complete way in, two tries each: how long does a session hold
    with TunerStudio-sized reads? (2026-11-06: one car visit must find the
    way that works.)"""
    best = None
    for label, how, rate in FINDER:
        ab.rate = rate
        held = []
        for k in range(2):
            ab.say("=== %s, try %d ===" % (label, k + 1))
            ok = ab.enter_direct() if how == "direct" else any(
                ab.enter_5baud() for _ in range(3))
            if not ok:
                held.append(None)
                ab.say("%s: NO ENTRY" % label)
                continue
            t0 = ab.t()
            cut = ab.short(hold_s, label)
            held.append(hold_s if cut is None else round(cut - t0, 1))
            time.sleep(3.0)                       # the line alone before the next
        txt = ", ".join("no entry" if h is None else
                        ("HELD %.0f s" % h if h >= hold_s else "cut after %.1f s" % h)
                        for h in held)
        v.append("%-26s %s" % (label + ":", txt))
        worst = min((h for h in held if h is not None), default=None)
        if worst is not None and (best is None or worst > best[1]):
            best = (label, worst)
    lt = {57600: "57600", 124800: "124800", 10400: "10400"}
    if best is None:
        v.append("=> NO WAY IN WORKED")
    elif best[1] >= hold_s:
        rate = [r for l, h, r in FINDER if l == best[0]][0]
        v.append("=> USE: %s (held %d s twice)" % (best[0], hold_s))
        v.append("   LibreTune: Connection K-line, Cable connected to: Car OBD socket, "
                 "%s baud (it goes DIRECT first, 5-baud only at 10400)" % lt[rate])
    else:
        v.append("=> nothing held %d s; longest: %s (%.1f s)" % (hold_s, best[0], best[1]))


def main():
    a = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    a.add_argument("--finder", action="store_true",
                   help="try every way in (DIRECT, 5-baud + 10400/57600/124800), "
                        "two tries each, --hold-s seconds of short reads each")
    a.add_argument("--hold-s", type=float, default=90.0)
    a.add_argument("--port", required=True)
    a.add_argument("--rate", type=int, default=57600, choices=(57600, 124800, 10400))
    a.add_argument("--entry", default="5baud", choices=("5baud", "direct"))
    a.add_argument("--short-s", type=float, default=90.0)
    a.add_argument("--long-n", type=int, default=3)
    a.add_argument("--sweep", action="store_true",
                   help="instead of A/B: one read of 256, 512, 768, 1024, 1696 B, "
                        "each followed by 8 s of short reads - where do cuts start?")
    a.add_argument("--out", default=os.path.join(os.getcwd(), "obd_ab_" + time.strftime("%Y%m%d_%H%M%S")))
    o = a.parse_args()
    ab = AB(o.port, o.rate, o.out)
    v = []
    if o.finder:
        try:
            finder(ab, o.hold_s, v)
        except KeyboardInterrupt:
            v.append("interrupted")
        text = "\n".join(ab.log_lines + [""] + v) + "\n"
        print("\n".join([""] + v))
        with open(os.path.join(o.out, "verdict.txt"), "w") as f:
            f.write(text)
        ab.f.close()
        ab.p.close()
        print("\nfolder: %s" % o.out)
        return
    try:
        if not ab.enter(o.entry):
            v.append("NO ENTRY - nothing tested (ignition on? KKL in the OBD socket?)")
            return
        ab.accounts("start")
        if o.sweep:
            for size in (256, 512, 768, 1024, BLOCK):
                t_long = ab.t()
                ok = ab.och(0, size, "sweep %d" % size) is not None
                cut = ab.short(8.0, "after %d" % size)
                v.append("SWEEP %4d B (%3.0f ms on the wire): %s%s" % (
                    size, (size + 7) * 10000.0 / ab.p.baud,
                    "" if ok else "read failed, ",
                    "no cut in 8 s" if cut is None
                    else "CUT %.2f s after it started" % (cut - t_long)))
                if cut is not None and not ab.recover("cut after %d" % size):
                    v.append("no re-entry after %d" % size)
                    return
            return
        cut = ab.short(o.short_s, "A short")
        v.append("A SHORT reads %.0f s: %s" % (o.short_s, "NO CUT" if cut is None
                                                 else "CUT at %.1f s" % cut))
        if cut is not None and not ab.recover("cut in A"):
            v.append("no re-entry after the A cut")
            return
        for i in range(o.long_n):
            t_long = ab.t()
            whole = ab.och(0, BLOCK, "B long")
            ab.say("B%d: whole block (%d B, %.0f ms on the wire) %s" % (
                i + 1, BLOCK, (BLOCK + 7) * 10000.0 / ab.p.baud,
                "read" if whole else "FAILED"))
            cut = ab.short(10.0, "B%d after long" % (i + 1))
            v.append("B%d LONG read then short reads: %s" % (
                i + 1, "no cut in 10 s" if cut is None
                else "CUT %.2f s after the long reply started" % (cut - t_long)))
            if cut is not None and not ab.recover("cut after B%d" % (i + 1)):
                v.append("no re-entry after B%d" % (i + 1))
                return
    except KeyboardInterrupt:
        v.append("interrupted")
    finally:
        a_ok = any(s.startswith("A SHORT") and "NO CUT" in s for s in v)
        b_cut = sum("CUT" in s for s in v if s.startswith("B"))
        for tag, r, moved in ab.cut_kind:
            v.append("  %s: %s" % (tag, "LINE CLOSED (silent at every rate)" if r is None
                                   else "ECU answered at %d%s" % (
                                       r, ", it had MOVED its rate %d time(s)" % moved if moved else "")))
        if o.sweep:
            pass
        elif a_ok and b_cut:
            v.append("=> LONG REPLIES CUT THE LINE, short ones do not (fix confirmed: "
                     "LibreTune / logger read <= 25 ms per reply on OBD)")
        elif a_ok:
            v.append("=> no cut at all here - the long-reply cause NOT reproduced")
        else:
            v.append("=> short reads were cut too - another cause; bring ab.csv back")
        text = "\n".join(ab.log_lines + [""] + v) + "\n"
        print("\n".join([""] + v))
        with open(os.path.join(o.out, "verdict.txt"), "w") as f:
            f.write(text)
        ab.f.close()
        ab.p.close()
        print("\nfolder: %s" % o.out)


if __name__ == "__main__":
    main()
