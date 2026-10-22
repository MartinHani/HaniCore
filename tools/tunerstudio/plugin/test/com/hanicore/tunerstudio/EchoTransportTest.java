package com.hanicore.tunerstudio;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 * The plugin's REAL echo transport (HaniCoreKLinePlugin.EchoTransport) on a
 * modelled K-line, driven the way TunerStudio drives it: write the request,
 * then poll available() every 5 ms until the reply is in or the time is up
 * (A.t.a in TunerStudioMS.jar). The line echoes every byte; per request it
 * answers, stays silent (the request was lost on the shared K-line) or echoes
 * it corrupted (a collision) and stays silent.
 *
 *   java -cp <plugin classes>;<TunerStudio jars>;<test classes> com.hanicore.tunerstudio.EchoTransportTest
 *
 * Exit 0 = every check passed. Run by tools/tunerstudio/plugin/build_plugin.py;
 * the published 2.2.0 jar must FAIL it (it waited TunerStudio's 8 s).
 */
public final class EchoTransportTest {

    enum Act { ANSWER, LOSE, COLLIDE }

    /** What TunerStudio's RS232 object exposes to the transport. */
    public static final class FakePort {
        final ArrayDeque<Byte> rx = new ArrayDeque<>();
        final List<Act> script = new ArrayList<>();
        final ByteArrayOutputStream frame = new ByteArrayOutputStream();
        int requests;
        final byte[] reply;

        FakePort(byte[] reply, Act... acts) {
            this.reply = reply;
            script.addAll(Arrays.asList(acts));
        }

        private synchronized void wire(byte[] b, int off, int len) {
            frame.write(b, off, len);
            byte[] f = frame.toByteArray();
            if (f.length < 2 || f.length < (((f[0] & 0xFF) << 8) | (f[1] & 0xFF)) + 6) {
                for (int i = 0; i < len; i++) rx.addLast(b[off + i]);   /* echo */
                return;
            }
            frame.reset();
            Act a = script.isEmpty() ? Act.ANSWER : script.remove(0);
            requests++;
            byte[] echo = Arrays.copyOfRange(b, off, off + len);
            if (a == Act.COLLIDE && echo.length > 3) {
                echo[echo.length - 1] ^= 0x5A;
                echo[echo.length - 2] ^= 0x33;
            }
            for (byte x : echo) rx.addLast(x);
            if (a == Act.ANSWER) for (byte x : reply) rx.addLast(x);
        }

        public InputStream i() {
            return new InputStream() {
                public int read() {
                    synchronized (FakePort.this) { return rx.isEmpty() ? -1 : rx.removeFirst() & 0xFF; }
                }
                public int read(byte[] b, int off, int len) {
                    synchronized (FakePort.this) {
                        int n = 0;
                        while (n < len && !rx.isEmpty()) b[off + n++] = rx.removeFirst();
                        return n;
                    }
                }
                public int available() {
                    synchronized (FakePort.this) { return rx.size(); }
                }
            };
        }

        public OutputStream j() {
            return new OutputStream() {
                public void write(int b) { wire(new byte[]{(byte) b}, 0, 1); }
                public void write(byte[] b, int off, int len) { wire(b, off, len); }
            };
        }

        public Object a(String key) { return "115200"; }
    }

    static int passed, failed;

    static void check(boolean ok, String what) {
        System.out.println((ok ? "  OK: " : "  FAIL: ") + what);
        if (ok) passed++; else failed++;
    }

    /** TunerStudio: write, then poll available() until n bytes or the time is up. */
    static byte[] exchange(FakePort port, byte[] req, int want, long waitMs) throws Exception {
        Class<?> et = Class.forName("com.hanicore.tunerstudio.HaniCoreKLinePlugin$EchoTransport");
        Constructor<?> c = et.getDeclaredConstructor(Object.class);
        c.setAccessible(true);
        Object t = c.newInstance(port);
        Method in = et.getDeclaredMethod("inputStream");
        Method out = et.getDeclaredMethod("outputStream");
        in.setAccessible(true);
        out.setAccessible(true);
        InputStream is = (InputStream) in.invoke(t);
        OutputStream os = (OutputStream) out.invoke(t);
        os.write(req, 0, req.length);
        os.flush();
        ByteArrayOutputStream got = new ByteArrayOutputStream();
        long end = System.currentTimeMillis() + waitMs;
        byte[] buf = new byte[256];
        while (got.size() < want && System.currentTimeMillis() < end) {
            int av = is.available();
            if (av <= 0) { Thread.sleep(5); continue; }
            int n = is.read(buf, 0, Math.min(av, buf.length));
            if (n > 0) got.write(buf, 0, n);
        }
        return got.toByteArray();
    }

    public static void main(String[] args) throws Exception {
        byte[] och = HcProtocol.tsRequest(new byte[]{'O', 0, 0, 0, 4});
        byte[] reply = {0x00, 0x05, 0x00, 1, 2, 3, 4, 9, 9, 9, 9};

        FakePort p = new FakePort(reply, Act.LOSE, Act.ANSWER);
        long t0 = System.currentTimeMillis();
        byte[] got = exchange(p, och, reply.length, 2000);
        long ms = System.currentTimeMillis() - t0;
        check(Arrays.equals(got, reply) && p.requests == 2 && ms < 1000,
                "a request lost on the line is sent again: reply in " + ms + " ms, "
                        + p.requests + " requests (TunerStudio would wait 8 s)");

        p = new FakePort(reply, Act.COLLIDE, Act.ANSWER);
        got = exchange(p, och, reply.length, 2000);
        check(Arrays.equals(got, reply) && p.requests == 2,
                "a request corrupted on the wire: its bad echo is dropped, the request "
                        + "sent again, TunerStudio reads exactly the reply (" + got.length + " bytes)");

        p = new FakePort(reply, Act.ANSWER);
        got = exchange(p, och, reply.length, 2000);
        Thread.sleep(800);
        check(Arrays.equals(got, reply) && p.requests == 1,
                "a request that is answered is sent once");

        byte[] burn = HcProtocol.tsRequest(new byte[]{'B', 0, 0});
        p = new FakePort(reply, Act.LOSE);
        got = exchange(p, burn, 3, 1200);
        check(got.length == 0 && p.requests == 1, "a Burn is never sent again");

        p = new FakePort(reply, Act.LOSE, Act.LOSE, Act.LOSE, Act.LOSE);
        got = exchange(p, och, reply.length, 2500);
        check(got.length == 0 && p.requests == 3,
                "a dead line: the request is sent twice more, then TunerStudio's timeout decides ("
                        + p.requests + " requests)");

        System.out.println((failed == 0 ? "PASS: " : "FAIL: ") + passed + " passed, "
                + failed + " failed - the plugin's echo transport on a lossy K-line");
        System.exit(failed == 0 ? 0 : 1);
    }
}
