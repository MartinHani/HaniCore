package com.hanicore.tunerstudio;

import java.util.HashMap;
import java.util.Map;

/**
 * AutoConnect against the REAL firmware KWP core: every test drives
 * tests/host/hckline_ecu_sim.c (shared/hckline.c + a modelled UART/5-baud
 * decoder/rate follower) through HcklineSimLine. A plain main() so it needs no
 * JUnit; exits nonzero on the first failure. Run by tools/test_plugin_auto.py
 * with -Dhc.sim=<path to the simulator>.
 */
public final class AutoConnectTests {

    private static int passed = 0;
    private static String SIM;

    private static void check(boolean cond, String name, AutoConnect.Result r) {
        if (!cond) {
            System.out.println("  FAIL: " + name);
            if (r != null) System.out.println(r.detail);
            throw new AssertionError(name);
        }
        System.out.println("  OK: " + name);
        passed++;
    }

    private static void check(boolean cond, String name) { check(cond, name, null); }

    private static AutoConnect.MemoryStore mem() {
        final Map<String, String> m = new HashMap<String, String>();
        return new AutoConnect.MemoryStore() {
            public String get(String id) { return m.get(id); }
            public void put(String id, String mode) { m.put(id, mode); }
        };
    }

    private static HcklineSimLine sim(String... cfg) throws Exception {
        HcklineSimLine l = new HcklineSimLine(SIM, "COM-SIM");
        for (int i = 0; i + 1 < cfg.length; i += 2) l.cfg(cfg[i], cfg[i + 1]);
        return l;
    }

    private static AutoConnect.Result run(Line l, int baud, AutoConnect.Mode m,
                                          AutoConnect.MemoryStore mem) {
        return new AutoConnect().connect(l, baud, m, mem);
    }

    private static boolean sigOk(AutoConnect.Result r) {
        return r.signature != null && r.signature.equals("rusEFI HaniCore ME711 F26F2BF7");
    }

    private static int stat(HcklineSimLine l, String key) throws Exception {
        for (String f : l.state().split(" ")) {
            if (f.startsWith(key + "=")) return Integer.parseInt(f.substring(key.length() + 1));
        }
        throw new AssertionError("no " + key);
    }

    public static void main(String[] args) throws Exception {
        SIM = System.getProperty("hc.sim");
        if (SIM == null) throw new IllegalStateException("-Dhc.sim=<hckline_ecu_sim.exe>");
        System.out.println("AutoConnect vs the firmware KWP core (hckline.c)");

        /* ---------- DIRECT: the ECU boots hunting at 57600 and follows ---- */
        for (int baud : new int[] { 57600, 115200, 124800 }) {
            HcklineSimLine l = sim();
            AutoConnect.Result r = run(l, baud, AutoConnect.Mode.AUTO, mem());
            check(r.ok && r.mode == AutoConnect.Mode.DIRECT && r.baud == baud && sigOk(r)
                    && l.breaks == 0,
                    "DIRECT " + baud + " from boot: signature, no 5-baud sent", r);
            l.close();
        }

        /* A link locked at 124800 (an earlier session) moves to 115200 only
           after three bad requests: still inside the direct budget. */
        {
            HcklineSimLine l = sim();
            check(run(l, 124800, AutoConnect.Mode.DIRECT, mem()).ok, "lock at 124800");
            AutoConnect.Result r = run(l, 115200, AutoConnect.Mode.AUTO, mem());
            check(r.ok && r.mode == AutoConnect.Mode.DIRECT && r.baud == 115200,
                    "locked 124800 -> TunerStudio 115200 followed directly", r);
            l.close();
        }

        /* ---------- VEHICLE: a K-line that opens only after 5-baud 0x01 --- */
        for (int baud : new int[] { 57600, 115200, 124800 }) {
            HcklineSimLine l = sim("gate", "1");
            AutoConnect.Result r = run(l, baud, AutoConnect.Mode.AUTO, mem());
            check(r.ok && r.mode == AutoConnect.Mode.VEHICLE && r.baud == baud && sigOk(r)
                    && stat(l, "gofast") == 1 && stat(l, "baud") == baud,
                    "gated line, TunerStudio " + baud + ": DIRECT fails, VEHICLE connects", r);
            l.close();
        }

        /* the remembered path is tried first, so the car connects without the
           direct probes the second time; a stale memory costs one attempt */
        {
            AutoConnect.MemoryStore m = mem();
            HcklineSimLine l = sim("gate", "1");
            check(run(l, 115200, AutoConnect.Mode.AUTO, m).ok, "first connect (VEHICLE)");
            l.cmd("reset");                       /* key cycle */
            int w0 = l.writes;
            AutoConnect.Result r = run(l, 115200, AutoConnect.Mode.AUTO, m);
            check(r.ok && r.fromMemory && r.mode == AutoConnect.Mode.VEHICLE,
                    "after a key cycle the remembered VEHICLE path connects first", r);
            check(l.writes - w0 == 1 + 3 + 1,
                    "... with no direct probes (70, 81, B0, B1, one probe)", r);
            l.close();

            HcklineSimLine d = sim();              /* now a plain wire */
            r = run(d, 115200, AutoConnect.Mode.AUTO, m);
            check(r.ok && r.mode == AutoConnect.Mode.VEHICLE && r.fromMemory,
                    "remembered VEHICLE still works on a plain wire", r);
            d.close();
        }
        {
            AutoConnect.MemoryStore m = mem();
            m.put("COM-SIM", "DIRECT");
            HcklineSimLine l = sim("gate", "1");
            AutoConnect.Result r = run(l, 115200, AutoConnect.Mode.AUTO, m);
            check(r.ok && !r.fromMemory && r.mode == AutoConnect.Mode.VEHICLE
                    && "VEHICLE".equals(m.get("COM-SIM")),
                    "stale remembered DIRECT falls through to VEHICLE and is replaced", r);
            l.close();
        }

        /* ---------- 2.2.0: the 5-baud entry is deaf -> ISO 14230 fast init */
        for (int baud : new int[] { 57600, 115200 }) {
            HcklineSimLine l = sim("gate", "1", "noslow", "1");
            AutoConnect.Result r = run(l, baud, AutoConnect.Mode.AUTO, mem());
            check(r.ok && r.mode == AutoConnect.Mode.VEHICLE && r.baud == baud && sigOk(r)
                    && stat(l, "gofast") == 1,
                    "5-baud ignored, TunerStudio " + baud + ": fast init connects", r);
            l.close();
        }

        /* ---------- a stock ECU never gets a GOFAST ----------------------- */
        {
            HcklineSimLine l = sim("gate", "1", "stock", "1");
            AutoConnect.Result r = run(l, 115200, AutoConnect.Mode.AUTO, mem());
            check(!r.ok && AutoConnect.R_NOT_HANICORE.equals(r.reason)
                    && stat(l, "gofast") == 0,
                    "stock ECU (7F B0 11): NOT HANICORE, no GOFAST sent", r);
            l.close();
        }
        {
            HcklineSimLine l = sim("gate", "1", "sig", "Bosch ME7 0261207696");
            AutoConnect.Result r = run(l, 115200, AutoConnect.Mode.VEHICLE, mem());
            check(!r.ok && AutoConnect.R_NOT_HANICORE.equals(r.reason)
                    && stat(l, "gofast") == 0,
                    "positive IDENTIFY without 'HaniCore': refused, no GOFAST", r);
            l.close();
        }

        /* ---------- refusals with a reason -------------------------------- */
        {
            HcklineSimLine l = sim("gate", "1");
            AutoConnect.Result r = run(l, 38400, AutoConnect.Mode.AUTO, mem());
            check(!r.ok && AutoConnect.R_BAUD.equals(r.reason) && l.breaks == 0,
                    "TunerStudio at 38400: BAUD NOT NEGOTIABLE, no 5-baud sent", r);
            l.close();
        }
        {
            HcklineSimLine l = sim("silent", "1");
            AutoConnect.Result r = run(l, 115200, AutoConnect.Mode.AUTO, mem());
            check(!r.ok && AutoConnect.R_NO_SYNC.equals(r.reason),
                    "no ECU: DIRECT then two 5-baud attempts, NO SYNC", r);
            /* 2.2.0: each attempt is a 5-baud byte (2 BREAKs) and, when no
               sync comes back, one fast-init wake-up (1 BREAK) */
            check(l.breaks == 6, "... exactly two attempts: 5-baud + fast init (6 BREAKs)", r);
            l.close();
        }
        {
            HcklineSimLine l = sim("gate", "1");
            AutoConnect.Result r = run(new AdapterLine(l, AdapterLine.Echo.FULL, 0, true),
                    115200, AutoConnect.Mode.VEHICLE, mem());
            check(!r.ok && AutoConnect.R_IO.equals(r.reason),
                    "adapter without BREAK: SERIAL I/O ERROR, not a hang", r);
            l.close();
        }

        /* ---------- adapter echo / stale bytes, both paths ---------------- */
        for (AdapterLine.Echo e : AdapterLine.Echo.values()) {
            for (int gate = 0; gate <= 1; gate++) {
                HcklineSimLine l = sim("echo", "0", "gate", "" + gate);
                AutoConnect.Result r = run(new AdapterLine(l, e, 3, false), 115200,
                        AutoConnect.Mode.AUTO, mem());
                check(r.ok && r.mode == (gate == 1 ? AutoConnect.Mode.VEHICLE
                        : AutoConnect.Mode.DIRECT) && sigOk(r),
                        "echo " + e + " + stale bytes, " + (gate == 1 ? "VEHICLE" : "DIRECT"), r);
                l.close();
            }
        }

        /* ---------- recovery ---------------------------------------------- */
        /* An abandoned KWP session (a tool killed after IDENTIFY): TunerStudio's
           probes arrive as garbage in the 10400 session; hckline ends it after
           three bad bursts (V95) and the link follows TunerStudio. */
        {
            HcklineSimLine l = sim();
            AutoConnect.send5Baud(l, 0x01);
            l.setBaud(10400);
            byte[] b = new byte[64];
            l.read(b, 0, 64, 500);                 /* 55 EF 8F */
            l.idle(30);
            l.write(new byte[] { 0x70 });
            l.read(b, 0, 64, 200);                 /* echo + FE */
            l.write(HcProtocol.kwpFrame(1, 0xF1, new byte[] { (byte) 0xB0, 'H', 'C' }));
            l.read(b, 0, 64, 300);
            check(stat(l, "kw_on") == 1, "session abandoned open after IDENTIFY");
            AutoConnect.Result r = run(l, 115200, AutoConnect.Mode.AUTO, mem());
            check(r.ok && r.mode == AutoConnect.Mode.DIRECT && stat(l, "drops") == 1,
                    "abandoned session ends on TunerStudio's garbage; DIRECT connects", r);
            l.close();
        }
        /* P3: a session left idle for 5 s closes by itself */
        {
            HcklineSimLine l = sim("gate", "1");
            AutoConnect.send5Baud(l, 0x01);
            l.setBaud(10400);
            byte[] b = new byte[64];
            l.read(b, 0, 64, 500);
            l.idle(30);
            l.write(new byte[] { 0x70 });
            l.read(b, 0, 64, 200);
            l.idle(5100);
            check(stat(l, "kw_on") == 0, "P3: an idle session returns to the hunt");
            AutoConnect.Result r = run(l, 115200, AutoConnect.Mode.AUTO, mem());
            check(r.ok, "... and the next connect works", r);
            l.close();
        }
        /* the ECU power-cycles mid-session: it boots at 57600; reconnect */
        for (int gate = 0; gate <= 1; gate++) {
            AutoConnect.MemoryStore m = mem();
            HcklineSimLine l = sim("gate", "" + gate);
            check(run(l, 124800, AutoConnect.Mode.AUTO, m).ok, "session up (gate " + gate + ")");
            l.cmd("reset");
            AutoConnect.Result r = run(l, 124800, AutoConnect.Mode.AUTO, m);
            check(r.ok && r.baud == 124800 && stat(l, "baud") == 124800,
                    "ECU power cycle -> reconnect at 124800 (gate " + gate + ")", r);
            l.close();
        }
        /* re-entry through 5-baud from a live 124800 session (the ECU's 5-baud
           decoder listens whenever no KWP session owns the line) */
        {
            HcklineSimLine l = sim();
            check(run(l, 124800, AutoConnect.Mode.DIRECT, mem()).ok, "live 124800 session");
            AutoConnect.Result r = run(l, 57600, AutoConnect.Mode.VEHICLE, mem());
            check(r.ok && r.baud == 57600 && stat(l, "baud") == 57600,
                    "VEHICLE re-entry from a live 124800 session to 57600", r);
            l.close();
        }

        /* ---------- silent-session recovery (the plugin's SilenceWatch) ---- */
        {
            SilenceWatch w = new SilenceWatch(8000, 20000, 5, 0);
            boolean early = false;
            for (int i = 1; i <= 4; i++) early |= w.beforeWrite(9000 + i);
            check(!early, "watch: fewer than 5 writes never recovers");
            check(w.beforeWrite(9100), "watch: 5th write after 8 s of silence recovers");
            w.recovered(9100);
            boolean again = false;
            for (int i = 0; i < 20; i++) again |= w.beforeWrite(9100 + 8000 + i);
            check(!again, "watch: not again within the 20 s interval");
            w.received(30000);
            boolean live = false;
            for (int i = 0; i < 50; i++) live |= w.beforeWrite(30000 + i * 100);
            check(!live, "watch: a session that answers is never touched");
        }
        /* TunerStudio's session on a GATED line: the ECU power-cycles, the
           session goes silent while TunerStudio polls, the watch fires and the
           engine re-enters on the SAME port; the polls are answered again. */
        {
            HcklineSimLine l = sim("gate", "1");
            AutoConnect.MemoryStore m = mem();
            check(run(l, 115200, AutoConnect.Mode.AUTO, m).ok, "TS session up (gated)");
            l.cmd("reset");
            SilenceWatch w = new SilenceWatch(8000, 20000, 5, 0);
            long t = 0;
            int recovered = 0, answeredAfter = 0;
            byte[] buf = new byte[512];
            for (int poll = 0; poll < 40; poll++) {
                t += 500;                               /* TS polls twice a second */
                if (w.beforeWrite(t)) {
                    AutoConnect.Result r = run(l, 115200, AutoConnect.Mode.AUTO, m);
                    w.recovered(t);
                    if (r.ok) recovered++;
                }
                l.setBaud(115200);
                l.purge();
                l.write(HcProtocol.tsSignatureRequest());
                int n = l.read(buf, 0, buf.length, 100);
                if (n > 0 && HcProtocol.findSignature(buf, n)) {
                    w.received(t);
                    if (recovered > 0) answeredAfter++;
                }
            }
            check(recovered == 1 && answeredAfter > 10,
                    "gated line + ECU power cycle mid-session: one recovery, polls answered", null);
            l.close();
        }

        System.out.println("PASS: " + passed + " AutoConnect checks");
    }
}
