package com.hanicore.tunerstudio;

import java.io.IOException;
import java.util.HashMap;
import java.util.Map;

/**
 * The plugin's connect engine from a terminal - the SAME AutoConnect and
 * SerialPortLine classes TunerStudio runs, for bench qualification and
 * diagnosis (not the user workflow: in TunerStudio the plugin does this):
 *
 *   java -cp HaniCore_KLine_Transport.jar;<TunerStudio>\lib\jssc.jar
 *        com.hanicore.tunerstudio.AutoConnectCli COM3 115200 [AUTO|DIRECT|VEHICLE]
 *        [repeat] [quiet-ms]
 *
 * Prints one line per attempt and a histogram; exit 0 only if every attempt
 * connected. Memory is per run (AUTO's first attempt detects, the rest use
 * the remembered path, as the plugin would).
 */
public final class AutoConnectCli {

    public static void main(String[] a) throws Exception {
        if (a.length < 2) {
            System.out.println("usage: AutoConnectCli <port> <baud> [AUTO|DIRECT|VEHICLE] [repeat] [quiet-ms]");
            System.exit(2);
        }
        String port = a[0];
        int baud = Integer.parseInt(a[1]);
        AutoConnect.Mode mode = a.length > 2 ? AutoConnect.Mode.valueOf(a[2]) : AutoConnect.Mode.AUTO;
        int repeat = a.length > 3 ? Integer.parseInt(a[3]) : 1;
        int quiet = a.length > 4 ? Integer.parseInt(a[4]) : 1000;
        final Map<String, String> m = new HashMap<String, String>();
        AutoConnect.MemoryStore mem = new AutoConnect.MemoryStore() {
            public String get(String id) { return m.get(id); }
            public void put(String id, String v) { m.put(id, v); }
        };
        Map<String, Integer> hist = new HashMap<String, Integer>();
        int ok = 0;
        for (int i = 1; i <= repeat; i++) {
            long t0 = System.currentTimeMillis();
            AutoConnect.Result r;
            SerialPortLine line = null;
            try {
                line = new SerialPortLine(port, baud);
                r = new AutoConnect().connect(line, baud, mode, mem);
            } catch (IOException e) {
                System.out.println("attempt " + i + ": " + e);
                hist.merge("PORT", 1, Integer::sum);
                continue;
            } finally {
                if (line != null) line.close();
            }
            long ms = System.currentTimeMillis() - t0;
            String key = r.ok ? "OK " + r.mode : r.reason;
            hist.merge(key, 1, Integer::sum);
            if (r.ok) ok++;
            System.out.println("attempt " + i + ": " + key + " at " + r.baud + " in " + ms + " ms"
                    + (r.fromMemory ? " (remembered)" : "") + (r.ok ? " - " + r.signature : ""));
            if (!r.ok || i == 1) System.out.print(r.detail);
            if (i < repeat) Thread.sleep(quiet);
        }
        System.out.println("histogram " + hist + " ok " + ok + "/" + repeat);
        System.exit(ok == repeat ? 0 : 1);
    }
}
