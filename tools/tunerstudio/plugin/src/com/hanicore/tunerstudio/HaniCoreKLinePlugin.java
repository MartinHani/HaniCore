package com.hanicore.tunerstudio;

import com.efiAnalytics.plugin.ApplicationPlugin;
import com.efiAnalytics.plugin.ecu.ControllerAccess;

import javax.swing.*;
import java.awt.*;
import java.io.*;
import java.lang.reflect.*;
import java.util.*;
import java.util.List;
import java.util.concurrent.atomic.AtomicLong;

/**
 * HaniCore K-Line transport add-on for TunerStudio.
 *
 * It preserves TunerStudio's Standard Protocols Driver and adds a Connection Type
 * called "HaniCore K-Line".  Internally that connection delegates to TunerStudio's
 * normal JSSC RS232 implementation, but consumes a byte-for-byte TX echo before
 * exposing the ECU response to the protocol layer.
 *
 * 2.0.0: AUTO-CONNECT. Every time TunerStudio opens the connection, the plugin
 * first brings the ECU to TunerStudio's own baud on a JSSC handle of its own
 * ({@link AutoConnect} over {@link SerialPortLine}): a direct probe (the ECU
 * follows the host's rate), else the VAG vehicle path (5-baud 0x01, KWP,
 * IDENTIFY, GOFAST). Then the port is closed and TunerStudio opens it as
 * before. No helper script, no terminal. Settings (optional, one file):
 * ~/.efiAnalytics/HaniCore/kline.properties - mode=AUTO|DIRECT|VEHICLE|OFF.
 *
 * 2.3.0: A LOST REQUEST IS SENT AGAIN ({@link ReplyWatch}): no byte from the
 * ECU 300 ms after a complete request (it answers within ~30 ms) and the
 * request is repeated, twice at most - a collision on the shared OBD K-line
 * cost TunerStudio's 8 s blockReadTimeout plus a re-entry. And an echo that
 * comes back full length but DIFFERENT is our own request corrupted on the
 * wire: it is dropped, not handed to TunerStudio as if the ECU had sent it.
 * 2.2.0: ISO 14230 FAST INIT after a silent 5-baud attempt (the car's shared
 * K-line, the maintainer's design notes); short breaks timed by the
 * UART (one 0x00 at a low rate) instead of a sleep.
 * 2.1.0: RECOVERY. TunerStudio's own re-establish (A.f.r()) closes and reopens
 * inside its RS232 class; the proxy now re-enters the ECU between the two.
 * And a session that goes silent while TunerStudio keeps polling (SilenceWatch:
 * 8 s, >= 5 writes, at most every 20 s) is re-entered on TunerStudio's own open
 * port - bytes read through TunerStudio's listener stream, BREAK and baud on
 * the port - so an ECU power cycle behind a 5-baud-gated line recovers too.
 *
 * This uses reflection for TunerStudio's internal transport API so
 * failure on an incompatible TunerStudio build is graceful instead of preventing
 * plugin loading.
 */
public final class HaniCoreKLinePlugin implements ApplicationPlugin {
    private static final String CONNECTION_ID = "HaniCore K-Line";
    private static final String DESCRIPTION = "RS232 / KKL: HaniCore auto-connect (direct or VAG 5-baud) + K-Line echo filtering";
    private static final String VERSION = "2.3.0";

    private static volatile String lastConnect = "Not attempted yet";
    private static volatile String lastTrace = "";
    private static final AtomicLong autoOk = new AtomicLong();
    private static final AtomicLong autoFail = new AtomicLong();
    private static final AtomicLong recoveries = new AtomicLong();
    /* TunerStudio keeps polling a dead session on its open port; after 8 s of
       silence (and >= 5 writes) the link is re-entered, at most every 20 s. */
    static final long SILENCE_MS = 8000L, RECOVERY_INTERVAL_MS = 20000L;
    static final int SILENCE_WRITES = 5;
    /* a request with no reply byte for 300 ms is sent again, twice at most */
    static final long RESEND_MS = 300L;
    static final int RESENDS = 2;
    private static final AtomicLong resent = new AtomicLong();
    private static final AtomicLong echoCollisions = new AtomicLong();

    private static volatile String status = "Not initialized";
    private static volatile boolean installed = false;
    private static volatile Throwable installFailure = null;
    private static final AtomicLong echoesCleared = new AtomicLong();
    private static final AtomicLong echoBytesCleared = new AtomicLong();
    private static final AtomicLong echoFallbacks = new AtomicLong();
    private static final AtomicLong echoTimeouts = new AtomicLong();
    private static final AtomicLong echoMismatches = new AtomicLong();
    private static final AtomicLong connectionsOpened = new AtomicLong();
    private static final AtomicLong connectionsClosed = new AtomicLong();
    private static volatile boolean connectionActive = false;
    private static volatile String lastConnectionDescription = "Not opened yet";
    private static volatile long lastEchoLatencyMs = 0L;
    private static volatile long maxEchoLatencyMs = 0L;

    static {
        installTransport();
    }

    public HaniCoreKLinePlugin() {
        installTransport();
    }

    @Override
    public void initialize(ControllerAccess controllerAccess) {
        installTransport();
    }

    private static synchronized void installTransport() {
        if (installed) return;
        try {
            final ClassLoader cl = HaniCoreKLinePlugin.class.getClassLoader();
            final Class<?> providerInterface = Class.forName("A.i", true, cl);
            final Class<?> providerRegistry = Class.forName("aV.w", true, cl);
            final Class<?> descriptorClass = Class.forName("A.q", true, cl);

            Method getProvider = providerRegistry.getMethod("c");
            final Object baseProvider = getProvider.invoke(null);
            if (baseProvider == null) throw new IllegalStateException("TunerStudio connection provider is null");

            // If an earlier instance already registered our descriptor, leave it alone.
            if (providerHasConnection(baseProvider, CONNECTION_ID)) {
                installed = true;
                status = CONNECTION_ID + " already registered";
                return;
            }

            final Object[] proxyHolder = new Object[1];
            InvocationHandler providerHandler = (proxy, method, args) -> {
                String name = method.getName();
                int count = method.getParameterCount();

                if (name.equals("a") && count == 0) {
                    Object result = invokeSame(method, baseProvider, args);
                    List<Object> out = new ArrayList<>();
                    if (result instanceof List) out.addAll((List<?>) result);
                    if (!descriptorListContains(out, CONNECTION_ID)) {
                        out.add(buildDescriptor(descriptorClass, providerInterface, proxyHolder[0]));
                    }
                    return out;
                }

                if (name.equals("a") && count == 2 && args != null && args.length == 2
                        && args[0] instanceof String && CONNECTION_ID.equals(args[0])) {
                    return createConnectionProxy(cl);
                }

                if (name.equals("a") && count == 3 && args != null && args.length == 3
                        && args[0] instanceof String && CONNECTION_ID.equals(args[0])) {
                    return createConnectionProxy(cl);
                }

                return invokeSame(method, baseProvider, args);
            };

            Object providerProxy = Proxy.newProxyInstance(cl, new Class<?>[]{providerInterface}, providerHandler);
            proxyHolder[0] = providerProxy;

            Method setProvider = providerRegistry.getMethod("a", providerInterface);
            setProvider.invoke(null, providerProxy);

            // Read it back and prove the descriptor is visible through the registry.
            Object readback = getProvider.invoke(null);
            if (!providerHasConnection(readback, CONNECTION_ID)) {
                throw new IllegalStateException("Provider setter returned without exposing " + CONNECTION_ID);
            }

            installed = true;
            status = CONNECTION_ID + " registered successfully";
            System.out.println("[HaniCore K-Line] " + status);
        } catch (Throwable t) {
            installFailure = unwrap(t);
            status = "Transport registration failed: " + installFailure;
            System.err.println("[HaniCore K-Line] " + status);
            installFailure.printStackTrace(System.err);
        }
    }

    private static Object buildDescriptor(Class<?> descriptorClass, Class<?> providerInterface, Object providerProxy) throws Exception {
        Object q = descriptorClass.getConstructor().newInstance();
        descriptorClass.getMethod("a", String.class).invoke(q, CONNECTION_ID);
        descriptorClass.getMethod("b", String.class).invoke(q, DESCRIPTION);
        descriptorClass.getMethod("a", providerInterface).invoke(q, providerProxy);
        return q;
    }

    private static boolean providerHasConnection(Object provider, String id) {
        try {
            Method listMethod = provider.getClass().getMethod("a");
            Object result = listMethod.invoke(provider);
            if (!(result instanceof List)) return false;
            return descriptorListContains((List<?>) result, id);
        } catch (Throwable ignored) {
            return false;
        }
    }

    private static boolean descriptorListContains(List<?> list, String id) {
        for (Object q : list) {
            if (q == null) continue;
            try {
                Method idMethod = q.getClass().getMethod("a");
                Object value = idMethod.invoke(q);
                if (id.equals(value)) return true;
            } catch (Throwable ignored) {
            }
        }
        return false;
    }

    private static Object createConnectionProxy(ClassLoader cl) throws Exception {
        final Class<?> connectionInterface = Class.forName("A.f", true, cl);
        final Class<?> rs232Class = Class.forName("aD.a", true, cl);
        final Object rs232 = rs232Class.getConstructor().newInstance();

        // Normal HaniCore target (115200 is in TunerStudio's list; the ECU
        // follows it). TunerStudio overrides this from the project settings.
        try {
            rs232Class.getMethod("a", String.class, Object.class)
                    .invoke(rs232, "Baud Rate", "115200");
        } catch (Throwable ignored) {
        }

        final EchoTransport echo = new EchoTransport(rs232);

        InvocationHandler connectionHandler = (proxy, method, args) -> {
            String name = method.getName();
            int count = method.getParameterCount();

            if (name.equals("f") && count == 0) { // open
                autoConnect(rs232);
                Object r = invokeSame(method, rs232, args);
                echo.resetStreams();
                echo.watch.reset(System.currentTimeMillis());
                connectionActive = true;
                connectionsOpened.incrementAndGet();
                try {
                    Object raw = rs232.getClass().getMethod("n").invoke(rs232);
                    lastConnectionDescription = String.valueOf(raw);
                } catch (Throwable ignored) {
                    lastConnectionDescription = CONNECTION_ID;
                }
                return r;
            }
            if (name.equals("r") && count == 0) { // re-establish: its own close + open
                // aD.a.r() closes and reopens INSIDE itself, bypassing this
                // proxy's open(): close first, re-enter the ECU, then let it run.
                try { rs232.getClass().getMethod("g").invoke(rs232); } catch (Throwable ignored) { }
                echo.resetStreams();
                autoConnect(rs232);
                Object r = invokeSame(method, rs232, args);
                echo.resetStreams();
                echo.watch.reset(System.currentTimeMillis());
                return r;
            }
            if (name.equals("g") && count == 0) { // close
                echo.resetStreams();
                try {
                    return invokeSame(method, rs232, args);
                } finally {
                    connectionActive = false;
                    connectionsClosed.incrementAndGet();
                }
            }
            if (name.equals("h") && count == 0) { // connection type/name
                return CONNECTION_ID;
            }
            if (name.equals("i") && count == 0) { // InputStream
                return echo.inputStream();
            }
            if (name.equals("j") && count == 0) { // OutputStream
                return echo.outputStream();
            }
            if (name.equals("n") && count == 0) { // human-readable connection description
                Object raw = invokeSame(method, rs232, args);
                return CONNECTION_ID + " / " + String.valueOf(raw);
            }

            return invokeSame(method, rs232, args);
        };

        return Proxy.newProxyInstance(cl, new Class<?>[]{connectionInterface}, connectionHandler);
    }

    /* ------------------------------------------------------ auto-connect -- */

    private static File settingsDir() {
        return new File(System.getProperty("user.home"), ".efiAnalytics" + File.separator + "HaniCore");
    }

    private static Properties readProps(File f) {
        Properties p = new Properties();
        if (f.isFile()) {
            try (InputStream in = new FileInputStream(f)) { p.load(in); } catch (IOException ignored) { }
        }
        return p;
    }

    /** Remembered last-good path per port, in its own small file. */
    private static final AutoConnect.MemoryStore MEMORY = new AutoConnect.MemoryStore() {
        private final File f = new File(settingsDir(), "autoconnect-memory.properties");
        public synchronized String get(String id) {
            return readProps(f).getProperty("path." + id);
        }
        public synchronized void put(String id, String mode) {
            Properties p = readProps(f);
            if (mode.equals(p.getProperty("path." + id))) return;
            p.setProperty("path." + id, mode);
            f.getParentFile().mkdirs();
            try (OutputStream out = new FileOutputStream(f)) {
                p.store(out, "HaniCore K-Line: the last path that connected, per port");
            } catch (IOException ignored) { }
        }
    };

    private static String setting(Object rs232, String key) {
        try {
            Object v = rs232.getClass().getMethod("a", String.class).invoke(rs232, key);
            return v == null ? null : String.valueOf(v).trim();
        } catch (Throwable t) {
            return null;
        }
    }

    /**
     * Leave the ECU talking at TunerStudio's baud, then return (TunerStudio
     * opens the port next). Never throws: a failed auto-connect leaves
     * TunerStudio's own "not responding" path in charge, and the reason is in
     * the Tools panel and the log.
     */
    private static AutoConnect.Mode configuredMode() {
        Properties cfg = readProps(new File(settingsDir(), "kline.properties"));
        String modeText = cfg.getProperty("mode", "AUTO").trim().toUpperCase(Locale.ROOT);
        if (modeText.equals("OFF")) return null;
        try { return AutoConnect.Mode.valueOf(modeText); } catch (RuntimeException e) { return AutoConnect.Mode.AUTO; }
    }

    private static int tsBaud(Object rs232) {
        try { return Integer.parseInt(setting(rs232, "Baud Rate")); } catch (RuntimeException e) { return 115200; }
    }

    /**
     * Leave the ECU talking at TunerStudio's baud, then return (TunerStudio
     * opens the port next). Never throws: a failed auto-connect leaves
     * TunerStudio's own "not responding" path in charge, and the reason is in
     * the Tools panel and the log.
     */
    private static void autoConnect(Object rs232) {
        AutoConnect.Mode mode = configuredMode();
        if (mode == null) {
            lastConnect = "Auto-connect OFF (kline.properties)";
            return;
        }
        String port = setting(rs232, "Com Port");
        if (port == null || port.isEmpty()) port = setting(rs232, "2nd Com Port");
        int baud = tsBaud(rs232);
        if (port == null || port.isEmpty()) {
            lastConnect = "NO COM PORT SET";
            return;
        }
        SerialPortLine line = null;
        try {
            line = new SerialPortLine(port, baud);
            report("auto-connect " + port, line, baud, mode);
        } catch (IOException e) {
            lastConnect = "PORT BUSY / MISSING: " + port;
            lastTrace = String.valueOf(e);
            autoFail.incrementAndGet();
            System.err.println("[HaniCore K-Line] auto-connect: " + e);
        } finally {
            if (line != null) line.close();
        }
    }

    /** Run the engine on a line and publish the outcome. */
    private static AutoConnect.Result report(String what, Line line, int baud, AutoConnect.Mode mode) {
        long t0 = System.currentTimeMillis();
        AutoConnect.Result r = new AutoConnect().connect(line, baud, mode, MEMORY);
        long ms = System.currentTimeMillis() - t0;
        lastTrace = r.detail;
        String tag = what.startsWith("recovery") ? "RECOVERED " : "";
        if (r.ok) {
            autoOk.incrementAndGet();
            lastConnect = tag + (r.mode == AutoConnect.Mode.VEHICLE ? "VEHICLE (5-baud KWP)" : "DIRECT")
                    + " at " + r.baud + (r.fromMemory ? ", remembered" : "") + ", " + ms + " ms - "
                    + r.signature;
        } else {
            autoFail.incrementAndGet();
            lastConnect = (tag.isEmpty() ? "" : "RECOVERY ") + "FAILED: " + r.reason + " (" + ms + " ms)";
        }
        System.out.println("[HaniCore K-Line] " + what + ": " + lastConnect);
        System.out.println(r.detail);
        return r;
    }

    /** TunerStudio's own open jssc.SerialPort inside its RS232 object. */
    private static jssc.SerialPort tsPort(Object rs232) {
        for (Class<?> c = rs232.getClass(); c != null; c = c.getSuperclass()) {
            for (java.lang.reflect.Field f : c.getDeclaredFields()) {
                if (f.getType() == jssc.SerialPort.class) {
                    try {
                        f.setAccessible(true);
                        return (jssc.SerialPort) f.get(rs232);
                    } catch (Throwable ignored) {
                        return null;
                    }
                }
            }
        }
        return null;
    }

    /**
     * The session went silent while TunerStudio kept polling (ECU power cycle
     * on a line that needs the 5-baud way in, a KWP tool that grabbed the
     * ECU, ...): re-enter the ECU on TunerStudio's own open port, leave it at
     * TunerStudio's baud, and let TunerStudio's next request through.
     */
    private static void recoverOnTsPort(Object rs232, InputStream tsIn) {
        AutoConnect.Mode mode = configuredMode();
        if (mode == null || tsIn == null) return;
        jssc.SerialPort sp = tsPort(rs232);
        if (sp == null || !sp.isOpened()) return;
        int baud = tsBaud(rs232);
        recoveries.incrementAndGet();
        SerialPortLine line = new SerialPortLine(sp, tsIn, baud);
        try {
            report("recovery " + sp.getPortName(), line, baud, mode);
        } finally {
            try {
                line.setBaud(baud);
                line.purge();
            } catch (IOException e) {
                System.err.println("[HaniCore K-Line] recovery: restoring the port: " + e);
            }
        }
    }

    private static Object invokeSame(Method interfaceMethod, Object target, Object[] args) throws Throwable {
        try {
            return interfaceMethod.invoke(target, args);
        } catch (InvocationTargetException e) {
            throw e.getCause();
        }
    }

    private static Throwable unwrap(Throwable t) {
        while (t instanceof InvocationTargetException && ((InvocationTargetException) t).getCause() != null) {
            t = ((InvocationTargetException) t).getCause();
        }
        return t;
    }

    /** Handles the one behavior the stock RS232 transport lacks: local K-Line echo. */
    private static final class EchoTransport {
        private final Object rs232;
        private final Object ioLock = new Object();
        final SilenceWatch watch = new SilenceWatch(SILENCE_MS, RECOVERY_INTERVAL_MS,
                SILENCE_WRITES, System.currentTimeMillis());
        final ReplyWatch reply = new ReplyWatch(RESEND_MS, RESENDS);
        private final ArrayDeque<Byte> replay = new ArrayDeque<>();
        private InputStream rawIn;
        private OutputStream rawOut;
        private InputStream filteredIn;
        private OutputStream filteredOut;

        EchoTransport(Object rs232) {
            this.rs232 = rs232;
        }

        void resetStreams() {
            synchronized (ioLock) {
                rawIn = null;
                rawOut = null;
                filteredIn = null;
                filteredOut = null;
                replay.clear();
                reply.received();           /* nothing outstanding on a new port */
            }
        }

        /* Under ioLock, from TunerStudio's own read loop (it polls available()
           every 5..25 ms while it waits): the request it is waiting for never
           reached the ECU - send it again. */
        private void resendIfDue() throws IOException {
            byte[] r = reply.due(System.currentTimeMillis());
            if (r == null || rawOut == null || rawIn == null) return;
            rawOut.write(r);
            rawOut.flush();
            clearExactEcho(r);
            resent.incrementAndGet();
            System.err.println("[HaniCore K-Line] no reply in " + RESEND_MS
                    + " ms; request sent again: " + hex(r));
        }

        InputStream inputStream() throws Exception {
            synchronized (ioLock) {
                ensureStreams();
                return filteredIn;
            }
        }

        OutputStream outputStream() throws Exception {
            synchronized (ioLock) {
                ensureStreams();
                return filteredOut;
            }
        }

        private void ensureStreams() throws Exception {
            InputStream in = (InputStream) rs232.getClass().getMethod("i").invoke(rs232);
            OutputStream out = (OutputStream) rs232.getClass().getMethod("j").invoke(rs232);
            if (in == null || out == null) return;
            if (in == rawIn && out == rawOut && filteredIn != null && filteredOut != null) return;

            rawIn = in;
            rawOut = out;
            filteredIn = new FilteredInputStream();
            filteredOut = new EchoClearingOutputStream();
        }

        private int baudRate() {
            try {
                Object value = rs232.getClass().getMethod("a", String.class).invoke(rs232, "Baud Rate");
                return Integer.parseInt(String.valueOf(value));
            } catch (Throwable ignored) {
                return 57600;
            }
        }

        private long echoDeadlineMs(int byteCount) {
            int baud = Math.max(1200, baudRate());
            long wireMs = (long) Math.ceil((byteCount * 10.0 * 1000.0) / baud);
            long timeout = wireMs + 75L;
            if (timeout < 80L) timeout = 80L;
            if (timeout > 2000L) timeout = 2000L;
            return timeout;
        }

        private void clearExactEcho(byte[] expected) throws IOException {
            if (expected.length == 0 || rawIn == null) return;

            ByteArrayOutputStream captured = new ByteArrayOutputStream(expected.length);
            long deadline = System.currentTimeMillis() + echoDeadlineMs(expected.length);
            byte[] tmp = new byte[Math.min(256, Math.max(1, expected.length))];

            while (captured.size() < expected.length && System.currentTimeMillis() < deadline) {
                int available = rawIn.available();
                if (available <= 0) {
                    try { Thread.sleep(1L); } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                        break;
                    }
                    continue;
                }
                int want = Math.min(Math.min(available, tmp.length), expected.length - captured.size());
                int n = rawIn.read(tmp, 0, want);
                if (n < 0) break;
                if (n > 0) captured.write(tmp, 0, n);
            }

            byte[] got = captured.toByteArray();
            long latencyMs = Math.max(0L, System.currentTimeMillis() - (deadline - echoDeadlineMs(expected.length)));
            lastEchoLatencyMs = latencyMs;
            if (latencyMs > maxEchoLatencyMs) maxEchoLatencyMs = latencyMs;

            if (got.length == expected.length && Arrays.equals(got, expected)) {
                echoesCleared.incrementAndGet();
                echoBytesCleared.addAndGet(got.length);
                return;
            }

            // A FULL-LENGTH echo that still mostly matches is our own request
            // corrupted on the wire (a collision on the shared K-line): the
            // ECU got garbage and stays silent, so these bytes are not its
            // reply - drop them; ReplyWatch sends the request again. (An
            // adapter without echo delivers the ECU's reply here instead,
            // which matches the request in few places: replayed below.)
            if (got.length == expected.length && sameBytes(got, expected) * 2 >= expected.length) {
                echoFallbacks.incrementAndGet();
                echoMismatches.incrementAndGet();
                echoCollisions.incrementAndGet();
                System.err.println("[HaniCore K-Line] echo corrupted on the line (collision); dropped. TX="
                        + hex(expected) + " RX=" + hex(got));
                return;
            }
            // Never silently throw away an incomplete prefix (an adapter
            // without echo can deliver the ECU's reply here). Replay it to TS,
            // and never send the request again on top of what may be a reply.
            for (byte b : got) replay.addLast(b);
            if (got.length > 0) reply.received();
            echoFallbacks.incrementAndGet();
            if (got.length < expected.length) {
                echoTimeouts.incrementAndGet();
            } else {
                echoMismatches.incrementAndGet();
            }
            System.err.println("[HaniCore K-Line] Echo mismatch/timeout; replaying " + got.length
                    + " byte(s) instead of discarding them. TX=" + hex(expected) + " RX-prefix=" + hex(got));
        }

        private static int sameBytes(byte[] a, byte[] b) {
            int n = 0;
            for (int i = 0; i < Math.min(a.length, b.length); i++) if (a[i] == b[i]) n++;
            return n;
        }

        private static String hex(byte[] data) {
            StringBuilder sb = new StringBuilder();
            int max = Math.min(data.length, 64);
            for (int i = 0; i < max; i++) {
                if (i != 0) sb.append(' ');
                sb.append(String.format("%02X", data[i] & 0xFF));
            }
            if (data.length > max) sb.append(" ...(").append(data.length).append(" bytes)");
            return sb.toString();
        }

        private final class EchoClearingOutputStream extends OutputStream {
            @Override
            public void write(int b) throws IOException {
                byte[] one = {(byte) b};
                write(one, 0, 1);
            }

            @Override
            public void write(byte[] b) throws IOException {
                write(b, 0, b.length);
            }

            @Override
            public void write(byte[] b, int off, int len) throws IOException {
                if (off < 0 || len < 0 || off + len > b.length) throw new IndexOutOfBoundsException();
                byte[] sent = Arrays.copyOfRange(b, off, off + len);
                synchronized (ioLock) {
                    if (rawOut == null || rawIn == null) throw new IOException("Serial streams are not open");
                    if (watch.beforeWrite(System.currentTimeMillis())) {
                        replay.clear();
                        recoverOnTsPort(rs232, rawIn);
                        watch.recovered(System.currentTimeMillis());
                    }
                    reply.wrote(b, off, len, System.currentTimeMillis());
                    rawOut.write(b, off, len);
                    rawOut.flush();
                    clearExactEcho(sent);
                }
            }

            @Override
            public void flush() throws IOException {
                synchronized (ioLock) {
                    if (rawOut != null) rawOut.flush();
                }
            }
        }

        private final class FilteredInputStream extends InputStream {
            @Override
            public int read() throws IOException {
                synchronized (ioLock) {
                    if (!replay.isEmpty()) return replay.removeFirst() & 0xFF;
                    if (rawIn == null) return -1;
                    int v = rawIn.read();
                    if (v >= 0) {
                        watch.received(System.currentTimeMillis());
                        reply.received();
                    }
                    return v;
                }
            }

            @Override
            public int read(byte[] b, int off, int len) throws IOException {
                if (off < 0 || len < 0 || off + len > b.length) throw new IndexOutOfBoundsException();
                if (len == 0) return 0;
                synchronized (ioLock) {
                    int count = 0;
                    while (count < len && !replay.isEmpty()) {
                        b[off + count++] = replay.removeFirst();
                    }
                    if (count == len) return count;
                    if (rawIn == null) return count == 0 ? -1 : count;
                    int n = rawIn.read(b, off + count, len - count);
                    if (n < 0) return count == 0 ? -1 : count;
                    if (count + n > 0) watch.received(System.currentTimeMillis());
                    if (n > 0) reply.received();
                    return count + n;
                }
            }

            @Override
            public int available() throws IOException {
                synchronized (ioLock) {
                    int n = replay.size() + (rawIn == null ? 0 : rawIn.available());
                    if (n == 0) resendIfDue();
                    return n;
                }
            }
        }
    }

    @Override
    public String getIdName() { return "hanicoreKLineTransport"; }

    @Override
    public int getPluginType() { return PERSISTENT_DIALOG_PANEL; }

    @Override
    public String getDisplayName() { return "HaniCore K-Line Transport"; }

    @Override
    public String getDescription() {
        return "Adds a HaniCore K-Line connection type: automatic ECU entry (direct or VAG 5-baud KWP) and KKL echo filtering.";
    }

    @Override
    public boolean displayPlugin(String controllerSignature) { return true; }

    @Override
    public boolean isMenuEnabled() { return true; }

    @Override
    public String getAuthor() { return "HaniCore"; }

    @Override
    public JComponent getPluginPanel() {
        installTransport();
        JPanel panel = new JPanel(new BorderLayout(8, 8));
        JTextArea text = new JTextArea();
        text.setEditable(false);
        text.setLineWrap(true);
        text.setWrapStyleWord(true);

        Runnable refresh = () -> text.setText(
                "HaniCore K-Line Transport " + VERSION + "\n\n" +
                "Transport registration: " + status + "\n" +
                "Connection active: " + (connectionActive ? "YES" : "NO") + "\n" +
                "Last connection: " + lastConnectionDescription + "\n\n" +
                "Echo frames cleared: " + echoesCleared.get() + "\n" +
                "Echo bytes cleared: " + echoBytesCleared.get() + "\n" +
                "Echo fallbacks: " + echoFallbacks.get() + "\n" +
                "  - incomplete/timeout: " + echoTimeouts.get() + "\n" +
                "  - full-prefix mismatch: " + echoMismatches.get() + "\n" +
                "  - corrupted on the line (dropped): " + echoCollisions.get() + "\n" +
                "Requests sent again (no reply in " + RESEND_MS + " ms): " + resent.get() + "\n" +
                "Last echo latency: " + lastEchoLatencyMs + " ms\n" +
                "Max echo latency: " + maxEchoLatencyMs + " ms\n" +
                "Connections opened/closed: " + connectionsOpened.get() + "/" + connectionsClosed.get() + "\n\n" +
                "Auto-connect: " + lastConnect + "\n" +
                "Auto-connect OK/failed: " + autoOk.get() + "/" + autoFail.get()
                        + ", silent-session recoveries: " + recoveries.get() + "\n\n" +
                "Setup (once):\n" +
                "  Driver: Standard Protocols Driver\n" +
                "  Connection Type: HaniCore K-Line\n" +
                "  Port: the KKL COM port\n" +
                "  Baud: 115200 (or 57600)\n" +
                "Then just connect - bench, direct wire or the car's OBD port.\n\n" +
                "Last auto-connect trace:\n" + lastTrace + "\n" +
                (installFailure == null ? "" : "Compatibility error: " + installFailure + "\n")
        );
        refresh.run();
        javax.swing.Timer timer = new javax.swing.Timer(750, e -> refresh.run());
        timer.setRepeats(true);
        timer.start();

        panel.add(new JScrollPane(text), BorderLayout.CENTER);
        panel.setPreferredSize(new Dimension(620, 420));
        return panel;
    }

    @Override
    public void close() { }

    @Override
    public String getHelpUrl() { return "https://www.tunerstudio.com/"; }

    @Override
    public String getVersion() { return VERSION; }

    @Override
    public double getRequiredPluginSpec() { return 1.0; }
}
