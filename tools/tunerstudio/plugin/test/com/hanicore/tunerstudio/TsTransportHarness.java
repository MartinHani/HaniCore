package com.hanicore.tunerstudio;

import java.io.InputStream;
import java.io.OutputStream;
import java.lang.reflect.Field;
import java.lang.reflect.Method;

/**
 * The plugin's connection proxy around TunerStudio's REAL RS232 transport
 * (aD.a from the installed TunerStudioMS.jar), headless: set the port and
 * baud the way TunerStudio does, open() (= auto-connect), then poll the
 * signature through TunerStudio's own streams twice a second, printing one
 * line per poll ("t_ms ok|--"). tools/me711_plugin_qualify.py --ts-transport
 * switches the ECU off and on underneath it.
 *
 *   java -cp <plugin classes>;TunerStudioMS.jar com.hanicore.tunerstudio.TsTransportHarness COM3 115200 60
 */
public final class TsTransportHarness {

    public static void main(String[] a) throws Exception {
        String port = a[0];
        String baud = a[1];
        long seconds = Long.parseLong(a[2]);
        ClassLoader cl = TsTransportHarness.class.getClassLoader();
        Method mk = HaniCoreKLinePlugin.class.getDeclaredMethod("createConnectionProxy", ClassLoader.class);
        mk.setAccessible(true);
        Object conn = mk.invoke(null, cl);
        Class<?> f = Class.forName("A.f", false, cl);
        f.getMethod("a", String.class, Object.class).invoke(conn, "Com Port", port);
        f.getMethod("a", String.class, Object.class).invoke(conn, "Baud Rate", baud);
        f.getMethod("f").invoke(conn);                       /* open = auto-connect */
        System.out.println("open: " + status("lastConnect"));
        InputStream in = (InputStream) f.getMethod("i").invoke(conn);
        OutputStream out = (OutputStream) f.getMethod("j").invoke(conn);
        long t0 = System.currentTimeMillis();
        byte[] buf = new byte[1024];
        int ok = 0, polls = 0;
        String lastSeen = "";
        while (System.currentTimeMillis() - t0 < seconds * 1000L) {
            long t = System.currentTimeMillis() - t0;
            while (in.available() > 0) in.read(buf, 0, Math.min(buf.length, in.available()));
            out.write(HcProtocol.tsSignatureRequest());
            out.flush();
            int n = 0;
            long end = System.currentTimeMillis() + 300;
            boolean got = false;
            while (System.currentTimeMillis() < end && n < buf.length) {
                int av = in.available();
                if (av <= 0) { Thread.sleep(2); continue; }
                n += in.read(buf, n, Math.min(av, buf.length - n));
                if (HcProtocol.findSignature(buf, n)) { got = true; break; }
            }
            polls++;
            if (got) ok++;
            String st = status("lastConnect");
            System.out.println(t + " " + (got ? "ok" : "--") + (st.equals(lastSeen) ? "" : "  [" + st + "]"));
            lastSeen = st;
            long wait = 500 - (System.currentTimeMillis() - t0 - t);
            if (wait > 0) Thread.sleep(wait);
        }
        System.out.println("polls " + polls + " ok " + ok + " recoveries " + status("recoveries"));
        f.getMethod("g").invoke(conn);
        System.exit(0);
    }

    private static String status(String name) throws Exception {
        Field fl = HaniCoreKLinePlugin.class.getDeclaredField(name);
        fl.setAccessible(true);
        return String.valueOf(fl.get(null));
    }
}
