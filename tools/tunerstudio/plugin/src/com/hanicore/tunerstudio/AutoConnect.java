package com.hanicore.tunerstudio;

import java.io.IOException;

/**
 * The HaniCore connect engine: everything the TunerStudio plugin does before it
 * hands the serial port to TunerStudio, so the user never runs a helper.
 *
 * It runs entirely against {@link Line}; the plugin drives it over JSSC
 * ({@link SerialPortLine}), the tests over MockLine and over the REAL firmware
 * KWP core compiled for the host (HcklineSimLine + tests/host/hckline_ecu_sim.c).
 *
 * The target rate is TunerStudio's own "Baud Rate" setting; the engine's job
 * is to leave the ECU talking at that rate:
 *
 *   DIRECT   probe the TunerStudio signature at the target rate. The ECU boots
 *            hunting at 57600 and follows a host at 57600 / 115200 / 124800
 *            (a hunting link after one bad request, a locked one after three -
 *            V95/V96, physically qualified), so a few probes are enough on the
 *            bench and on a plain wire to cavity 43.
 *   VEHICLE  the VAG way in (docs/ARCHITECTURE.md): 5-baud 0x01 at
 *            10400, 55 EF 8F, tester 70, ECU FE, StartCommunication 81 -> C1,
 *            IDENTIFY B0 'HC' -> F0 + the TS signature, GOFAST B1 <code> ->
 *            F1 <code>, then the port moves to the target rate and one probe
 *            proves the ECU followed.
 *
 * AUTO = the remembered path for this port first (one attempt), then DIRECT,
 * then VEHICLE. Nothing here writes the page or Burns; every step is bounded.
 */
public final class AutoConnect {

    public enum Mode { AUTO, DIRECT, VEHICLE }

    /** Remembered last-good path, keyed by the port identity. */
    public interface MemoryStore {
        String get(String adapterId);
        void put(String adapterId, String mode);
    }

    public static final MemoryStore NO_MEMORY = new MemoryStore() {
        public String get(String adapterId) { return null; }
        public void put(String adapterId, String mode) { }
    };

    /** Short, user-facing failure reasons (the trace carries the detail). */
    public static final String R_NO_ECU = "NO ECU REPLY";
    public static final String R_NO_SYNC = "5-BAUD: NO SYNC";
    public static final String R_HANDSHAKE = "5-BAUD: HANDSHAKE";
    public static final String R_NOT_HANICORE = "NOT HANICORE";
    public static final String R_GOFAST = "GOFAST REFUSED";
    public static final String R_NO_FOLLOW = "NO REPLY AFTER GOFAST";
    public static final String R_BAUD = "BAUD NOT NEGOTIABLE";
    public static final String R_IO = "SERIAL I/O ERROR";

    public static final class Result {
        public boolean ok;
        public Mode mode;          /* the path that connected (or last tried) */
        public int baud;           /* the rate the ECU now talks at            */
        public boolean fromMemory;
        public String signature;   /* the ECU's TunerStudio signature          */
        public String reason;      /* short failure reason, null on success    */
        public String detail;      /* the full trace                           */
        Result(boolean ok, Mode mode, int baud, String reason) {
            this.ok = ok; this.mode = mode; this.baud = baud; this.reason = reason;
        }
    }

    /* Tunables. Defaults are for real hardware (USB adapter latency included). */
    private int directAttempts = 8;     /* covers boot 57600 -> 124800 with laps */
    private int probeTimeoutMs = 150;   /* 'S' reply: ~40 bytes + ECU latency    */
    private int kwpTimeoutMs = 400;     /* P2 50 ms + adapter latency + echo     */
    private int syncTimeoutMs = 500;    /* W1 max 300 ms after the stop bit      */
    private int w4Ms = 30;              /* ISO W4 25..50 ms before our 70        */
    private int initAttempts = 2;       /* one full re-init after a failure      */
    private int w5Ms = 300;             /* ISO W5: idle before a 5-baud retry    */

    private final StringBuilder log = new StringBuilder();
    private String lastSignature;

    public AutoConnect directAttempts(int v) { directAttempts = v; return this; }
    public AutoConnect probeTimeoutMs(int v) { probeTimeoutMs = v; return this; }
    public AutoConnect kwpTimeoutMs(int v) { kwpTimeoutMs = v; return this; }

    private void log(String s) { log.append(s).append('\n'); }

    public String lastLog() { return log.toString(); }

    /* ---------------------------------------------------------- entry point -- */

    public Result connect(Line line, int targetBaud, Mode requested, MemoryStore mem) {
        if (mem == null) mem = NO_MEMORY;
        if (requested == null) requested = Mode.AUTO;
        log.setLength(0);
        log("target " + targetBaud + " baud, mode " + requested + ", port " + line.id());

        Result r;
        if (requested != Mode.AUTO) {
            r = tryMode(line, requested, targetBaud);
        } else {
            Mode remembered = parse(mem.get(line.id()));
            r = null;
            if (remembered != null) {
                log("remembered path " + remembered + ": one attempt");
                r = tryMode(line, remembered, targetBaud);
                if (r.ok) r.fromMemory = true;
                else log("remembered path failed; full detection");
            }
            if (r == null || !r.ok) {
                Mode[] order = { Mode.DIRECT, Mode.VEHICLE };
                for (Mode m : order) {
                    if (m == remembered) continue;
                    r = tryMode(line, m, targetBaud);
                    if (r.ok) break;
                }
            }
        }
        if (r.ok) mem.put(line.id(), r.mode.name());
        r.detail = log.toString();
        return r;
    }

    private Result tryMode(Line line, Mode m, int baud) {
        try {
            return m == Mode.VEHICLE ? vehicle(line, baud) : direct(line, baud);
        } catch (IOException e) {
            log(m + ": I/O error " + e.getMessage());
            return new Result(false, m, 0, R_IO);
        }
    }

    private static Mode parse(String s) {
        if (s == null) return null;
        try {
            Mode m = Mode.valueOf(s);
            return m == Mode.AUTO ? null : m;
        } catch (RuntimeException e) { return null; }
    }

    /* -------------------------------------------------------------- DIRECT -- */

    private Result direct(Line line, int baud) throws IOException {
        line.setBaud(baud);
        for (int attempt = 1; attempt <= directAttempts; attempt++) {
            line.purge();
            if (probe(line)) {
                log("DIRECT " + baud + ": HaniCore on attempt " + attempt
                        + " (" + lastSignature + ")");
                return success(Mode.DIRECT, baud);
            }
        }
        log("DIRECT " + baud + ": no HaniCore reply in " + directAttempts + " attempts");
        return new Result(false, Mode.DIRECT, baud, R_NO_ECU);
    }

    private Result success(Mode m, int baud) {
        Result r = new Result(true, m, baud, null);
        r.signature = lastSignature;
        return r;
    }

    /** One TS signature request; true on a CRC-valid TS_OK HaniCore reply. An
        echo of the request never passes (its code byte is 'S', not TS_OK). */
    private boolean probe(Line line) throws IOException {
        line.write(HcProtocol.tsSignatureRequest());
        byte[] acc = new byte[1024];
        int n = 0;
        long end = System.nanoTime() + probeTimeoutMs * 1000000L;
        int wait = probeTimeoutMs;
        while (n < acc.length) {
            int got = line.read(acc, n, acc.length - n, wait);
            if (got < 0) break;
            n += Math.max(got, 0);
            String sig = HcProtocol.signatureText(acc, n);
            if (sig != null) { lastSignature = sig; return true; }
            if (got == 0) break;
            wait = remaining(end);
            if (wait <= 0) break;
        }
        return false;
    }

    private static int remaining(long endNanos) {
        long ms = (endNanos - System.nanoTime()) / 1000000L;
        return ms <= 0 ? 0 : (int) ms;
    }

    /* ------------------------------------------------------------- VEHICLE -- */

    private Result vehicle(Line line, int baud) throws IOException {
        int code = HcProtocol.baudToCode(baud);
        if (code < 0) {
            log("VEHICLE: TunerStudio baud " + baud + " cannot be negotiated"
                    + " (use 115200 or 57600)");
            return new Result(false, Mode.VEHICLE, 0, R_BAUD);
        }
        String reason = R_NO_SYNC;
        for (int attempt = 1; attempt <= initAttempts; attempt++) {
            if (attempt > 1) {
                line.setBaud(HcProtocol.BAUD_10400);
                line.idle(w5Ms);
            }
            reason = slowInit(line);
            if (reason != null) { log("VEHICLE attempt " + attempt + ": " + reason); continue; }
            log("VEHICLE: 5-baud 0x01 -> 55 EF 8F / 70 -> FE");

            byte[] d = kwp(line, new byte[] { (byte) HcProtocol.SID_START_COMM });
            if (d == null || (d[0] & 0xFF) != HcProtocol.SID_START_COMM + HcProtocol.RESP_OFFSET) {
                reason = R_HANDSHAKE;
                log("VEHICLE: StartCommunication: " + hex(d));
                continue;
            }
            d = kwp(line, new byte[] { (byte) HcProtocol.SID_IDENTIFY, 'H', 'C' });
            if (d == null || (d[0] & 0xFF) != HcProtocol.SID_IDENTIFY + HcProtocol.RESP_OFFSET) {
                /* A stock ECU answers 7F B0 11: never send it a GOFAST. */
                log("VEHICLE: IDENTIFY: " + hex(d) + " - not HaniCore, no GOFAST sent");
                return new Result(false, Mode.VEHICLE, HcProtocol.BAUD_10400, R_NOT_HANICORE);
            }
            byte[] sig = new byte[d.length - 1];
            System.arraycopy(d, 1, sig, 0, sig.length);
            if (!HcProtocol.containsAscii(sig, HcProtocol.IDENTITY)) {
                log("VEHICLE: IDENTIFY payload '" + HcProtocol.ascii(sig) + "' is not HaniCore");
                return new Result(false, Mode.VEHICLE, HcProtocol.BAUD_10400, R_NOT_HANICORE);
            }
            log("VEHICLE: IDENTIFY '" + HcProtocol.ascii(sig) + "'");

            d = kwp(line, new byte[] { (byte) HcProtocol.SID_GOFAST, (byte) code });
            if (d == null || d.length < 2
                    || (d[0] & 0xFF) != HcProtocol.SID_GOFAST + HcProtocol.RESP_OFFSET
                    || (d[1] & 0xFF) != code) {
                reason = R_GOFAST;
                log("VEHICLE: GOFAST " + baud + ": " + hex(d));
                continue;
            }
            /* The ECU switches once its reply (and its echo) has left the wire;
               we have the whole reply, so the line is quiet now. */
            line.idle(20);
            line.setBaud(baud);
            for (int p = 1; p <= 4; p++) {
                line.purge();
                if (probe(line)) {
                    log("VEHICLE: HaniCore at " + baud + " on probe " + p
                            + " (" + lastSignature + ")");
                    return success(Mode.VEHICLE, baud);
                }
            }
            reason = R_NO_FOLLOW;
            log("VEHICLE: no TunerStudio reply at " + baud + " after GOFAST");
        }
        return new Result(false, Mode.VEHICLE, 0, reason);
    }

    /** 5-baud 0x01 and the key-byte handshake; null on success, else a reason. */
    private String slowInit(Line line) throws IOException {
        line.setBaud(HcProtocol.BAUD_10400);
        line.purge();
        send5Baud(line, HcProtocol.SLOW_ADDR);
        line.purge();                     /* whatever the break left behind */
        /* An adapter may deliver break noise first; look for the sync. */
        if (!waitForByte(line, HcProtocol.SYNC, syncTimeoutMs)) return R_NO_SYNC;
        if (!waitForByte(line, HcProtocol.KB1, 100)) return R_HANDSHAKE;
        if (!waitForByte(line, HcProtocol.KB2, 100)) return R_HANDSHAKE;
        line.idle(w4Ms);
        line.write(new byte[] { (byte) ((~HcProtocol.KB2) & 0xFF) });
        /* waitForByte skips our own echoed 70 on its way to the FE */
        if (!waitForByte(line, (~HcProtocol.SLOW_ADDR) & 0xFF, 200)) return R_HANDSHAKE;
        return null;
    }

    /** The address byte at 5 baud, LSB first, 8N1: BREAK for a 0, idle for a
        1, 200 ms a bit, equal bits coalesced. For 0x01: break 200 ms (start),
        idle 200 ms (bit 0), break 1400 ms (bits 1..7), idle (stop). */
    static void send5Baud(Line line, int addr) throws IOException {
        int[] bits = new int[10];
        bits[0] = 0;
        for (int i = 0; i < 8; i++) bits[1 + i] = (addr >> i) & 1;
        bits[9] = 1;
        line.idle(300);                   /* the ECU wants >= 300 ms of idle first */
        int i = 0;
        while (i < 10) {
            int level = bits[i], run = 0;
            while (i < 10 && bits[i] == level) { run++; i++; }
            if (level == 0) line.sendBreak(run * 200); else line.idle(run * 200);
        }
    }

    /** One KWP request; returns the reply's data (service id first) or null.
        Reads until a frame addressed to the tester parses - the echo of our
        own request (addressed to the ECU) is skipped by findKwpResponse. */
    private byte[] kwp(Line line, byte[] data) throws IOException {
        line.purge();
        line.write(HcProtocol.kwpFrame(HcProtocol.SLOW_ADDR, 0xF1, data));
        byte[] acc = new byte[512];
        int n = 0;
        long end = System.nanoTime() + kwpTimeoutMs * 1000000L;
        while (n < acc.length) {
            int wait = remaining(end);
            if (wait <= 0) break;
            int got = line.read(acc, n, acc.length - n, wait);
            if (got < 0) break;
            if (got == 0) break;
            n += got;
            byte[] r = HcProtocol.findKwpResponse(acc, n, HcProtocol.SLOW_ADDR, 0xF1);
            if (r != null) return r;
        }
        return null;
    }

    /** Wait for a byte value, skipping at most 64 others (echo, stale bytes,
        break glitches). */
    private boolean waitForByte(Line line, int value, int timeoutMs) throws IOException {
        byte[] one = new byte[1];
        long end = System.nanoTime() + timeoutMs * 1000000L;
        for (int i = 0; i < 64; i++) {
            int wait = remaining(end);
            if (wait <= 0) return false;
            int got = line.read(one, 0, 1, wait);
            if (got <= 0) return false;
            if ((one[0] & 0xFF) == (value & 0xFF)) return true;
        }
        return false;
    }

    static String hex(byte[] d) {
        if (d == null) return "no reply";
        StringBuilder sb = new StringBuilder();
        for (byte b : d) sb.append(String.format("%02X ", b & 0xFF));
        return sb.toString().trim();
    }
}
