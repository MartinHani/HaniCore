#!/usr/bin/env python3
r"""Echo-stripping bridge between TunerStudio and the ECU's K-line.

A KKL cable is a single bidirectional wire, so everything the PC transmits
comes straight back into the PC's own receiver before the ECU's answer. KWP
tools expect that and discard it; TunerStudio does not, and reports only
"Protocol Error".

This bridge sits in the middle. It counts every byte it writes to the K-line
and discards exactly that many bytes on the way back, so TunerStudio sees a
clean, echo-free stream.

Two ways to attach TunerStudio:

  TCP (no driver install)
      py tools\bench\ts_kline_bridge.py --port COM3
      TunerStudio -> Communications -> Connection Type: TCP/IP,
      host 127.0.0.1, port 29000

  Virtual serial pair (if you prefer a COM port; needs com0com installed)
      py tools\bench\ts_kline_bridge.py --port COM3 --serve-serial COM11
      TunerStudio then opens the other half of the pair, e.g. COM12.

The echo counter is cumulative rather than per-request on purpose: TunerStudio
may split a request across several writes, and counting bytes survives that.
"""
from __future__ import annotations

import argparse
import select
import socket
import sys
import threading
import time

try:
    import serial
except ImportError:
    print("pyserial is required:  py -m pip install pyserial")
    sys.exit(2)


class Bridge:
    def __init__(self, ser, verbose=False, logfile=None):
        self.ser = ser
        self.verbose = verbose
        self.logfile = logfile
        self.pending_echo = bytearray()
        self.echo_probe = bytearray()
        self.echo_since = 0.0        # when the outstanding echo was booked
        self.banner_hits = 0
        self.banner_warned = False
        self.lock = threading.Lock()

    def to_ecu(self, data: bytes) -> None:
        with self.lock:
            self.pending_echo.extend(data)
            self.echo_since = time.time()
        self.ser.write(data)
        self.ser.flush()
        if self.verbose:
            print(f"  -> ECU  {data.hex(' ')}")
        self.log(f"-> ECU  {data.hex(' ')}")

    def reset(self) -> None:
        """Drop stale bytes and forget any echo we never collected.

        Without this the echo counter stays misaligned forever: TunerStudio
        connects, queries, then disconnects before reading the answer, and that
        orphaned answer sits in the serial buffer and gets counted as echo on
        the next connection.
        """
        with self.lock:
            self.pending_echo.clear()
            self.echo_probe.clear()
        self.ser.reset_input_buffer()

    def from_ecu(self) -> bytes:
        """Read whatever is waiting, minus our own echo.

        Never blocks. It used to fall back to a one-byte read, and with the
        port opened at timeout=0.01 that parked the whole bridge for 10 ms
        every time the ECU had nothing to say - on top of another 10 ms
        waiting on the socket. MEASURED in ts_bridge.log: a median of 29 ms
        between a request going out and the first answer byte coming back,
        when the ECU itself answers in well under a millisecond. That is not a
        dropped connection, but it holds TunerStudio to about eleven updates a
        second and it stretches the gap between the two halves of a 16-bit
        write, which the ECU sees as a torn value.
        """
        n = self.ser.in_waiting
        if not n:
            # An echo can never legitimately still be outstanding after a
            # couple of hundred milliseconds - it comes back within one byte
            # time on a shared wire. If it is, something ate it (an ECU that
            # reset mid-transfer, a cable pulled), and holding the count would
            # make the bridge swallow the FRONT of every reply from then on.
            with self.lock:
                if (self.pending_echo
                        and time.time() - self.echo_since > 0.2):
                    # If bytes matched only a PREFIX of the expected echo,
                    # they may instead be a no-echo adapter's delayed ECU
                    # reply. Preserve them. An entirely absent echo has no
                    # bytes to preserve and simply expires.
                    held = bytes(self.echo_probe)
                    self.log("--- expiring %d echo byte(s); releasing %d "
                             "held byte(s) ---"
                             % (len(self.pending_echo), len(held)))
                    self.pending_echo.clear()
                    self.echo_probe.clear()
                    return held
            return b""
        chunk = self.ser.read(n)
        if not chunk:
            return b""
        self._watch_for_resets(chunk)
        with self.lock:
            if self.pending_echo:
                candidate = bytes(self.echo_probe) + chunk
                expect = bytes(self.pending_echo)
                common = 0
                limit = min(len(candidate), len(expect))
                while common < limit and candidate[common] == expect[common]:
                    common += 1

                if common < limit:
                    # The first incoming bytes are not our request echo. This
                    # is either a no-echo adapter or an ECU reply arriving
                    # after a missing echo. Preserve every byte.
                    self.pending_echo.clear()
                    self.echo_probe.clear()
                    chunk = candidate
                elif len(candidate) < len(expect):
                    # A split USB read containing only part of the echo.
                    self.echo_probe[:] = candidate
                    chunk = b""
                else:
                    # The complete echoed request is at the front; discard it
                    # and forward any ECU response bytes after it.
                    if self.verbose:
                        print(f"  xx echo {expect.hex(' ')}")
                    chunk = candidate[len(expect):]
                    self.pending_echo.clear()
                    self.echo_probe.clear()
        if chunk and self.verbose:
            print(f"  <- ECU  {chunk.hex(' ')}")
        if chunk:
            self.log(f"<- ECU  {chunk.hex(' ')}")
        return chunk

    def _watch_for_resets(self, chunk: bytes) -> None:
        """Say it out loud when the ECU is rebooting.

        The boot banner on the wire is the single most informative thing this
        bridge ever sees, and it is easy to miss among the hex. A banner that
        repeats means the ECU is being reset - by the monitoring module if it
        is not being answered in time - and NOTHING about the protocol matters
        until that stops. It cost a bench round to notice it by eye.
        """
        if b"HaniCore DC" not in chunk:
            return
        self.banner_hits += 1
        if self.banner_hits == 1:
            print("  ECU booted (banner seen)")
            self.log("--- ECU banner seen ---")
        elif self.banner_hits in (3, 10, 30, 100) or not self.banner_warned:
            self.banner_warned = True
            print("  *** THE ECU IS RESETTING - banner seen %d times. ***"
                  % self.banner_hits)
            print("      Nothing about TunerStudio matters until this stops.")
            self.log("--- ECU RESET LOOP: banner seen %d times ---"
                     % self.banner_hits)

    def log(self, line: str) -> None:
        if self.logfile:
            self.logfile.write("%.3f  %s%s" % (time.time(), line, chr(10)))
            self.logfile.flush()


def serve_tcp(bridge, host, port):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    # Backlog of 1 is not enough: TunerStudio probes the port several times in
    # quick succession, and once one connection is queued Windows refuses the
    # rest - which TunerStudio reports as "connection lost Stream closed", i.e.
    # it looks exactly like a bridge fault.
    srv.listen(5)
    print(f"Bridge ready. Point TunerStudio at TCP {host}:{port}")
    print("Connection Type = TCP/IP (not RS232). Ctrl+C to stop.")
    while True:
        try:
            conn, addr = srv.accept()
        except OSError as exc:
            print(f"accept failed: {exc}")
            continue
        print(f"TunerStudio connected from {addr}")
        bridge.reset()
        bridge.log(f"--- client {addr} connected, buffers reset ---")
        try:
            # A TIMEOUT, not full non-blocking: sendall() on a non-blocking
            # socket can raise BlockingIOError, and the handler below would
            # then close a connection that was merely busy for a moment.
            conn.settimeout(0.5)
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            # One short wait covering BOTH directions, instead of two long ones
            # in series. 2 ms is well under a single byte time at 57600 (174
            # us x 11 for a whole request), so nothing waits on the bridge any
            # more.
            while True:
                ready, _w, _x = select.select([conn], [], [], 0.002)
                if ready:
                    data = conn.recv(4096)
                    if not data:
                        break
                    bridge.to_ecu(data)
                out = bridge.from_ecu()
                if out:
                    conn.sendall(out)
        except Exception as exc:                 # never let one client kill us
            bridge.log(f"--- client error: {exc!r} ---")
        finally:
            try:
                conn.close()
            except OSError:
                pass
            print("TunerStudio disconnected")


def serve_serial(bridge, name, baud):
    # Same reasoning as the TCP path: a long blocking read here shows up as
    # latency on every single request.
    with serial.Serial(name, baud, timeout=0.002) as host:
        print(f"Bridge ready on {name}. Open the paired port in TunerStudio.")
        while True:
            data = host.read(4096)
            if data:
                bridge.to_ecu(data)
            out = bridge.from_ecu()
            if out:
                host.write(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True, help="ECU K-line port, e.g. COM3")
    # 57600 is the normal project rate. The ST10 reload is 0x15, producing
    # 56,818 baud (-1.36%), which a host port configured for 57600 accepts.
    ap.add_argument("--baud", type=int, default=57600)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--tcp-port", type=int, default=29000)
    ap.add_argument("--serve-serial", metavar="COMxx",
                    help="serve on a virtual serial port instead of TCP")
    ap.add_argument("--probe-echo", action="store_true",
                    help="with ECU physically disconnected, test whether the adapter echoes")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--log", metavar="FILE", default="ts_bridge.log",
                    help="record all traffic here (default ts_bridge.log)")
    args = ap.parse_args()

    logfile = open(args.log, "w") if args.log else None
    with serial.Serial(args.port, args.baud, timeout=0) as ser:
        ser.reset_input_buffer()
        if args.probe_echo:
            probe = bytes.fromhex("55 aa a5")
            ser.write(probe)
            ser.flush()
            time.sleep(0.10)
            got = ser.read(ser.in_waiting)
            if got.startswith(probe):
                print("ADAPTER ECHO PRESENT: " + got.hex(" "))
            else:
                print("ADAPTER ECHO NOT OBSERVED: " + (got.hex(" ") or "<no bytes>"))
            print("This result is valid only with the ECU physically disconnected.")
            return 0
        bridge = Bridge(ser, args.verbose, logfile)
        if args.serve_serial:
            serve_serial(bridge, args.serve_serial, args.baud)
        else:
            serve_tcp(bridge, args.host, args.tcp_port)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nstopped")
