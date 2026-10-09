package com.hanicore.tunerstudio;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.io.Writer;

/**
 * A {@link Line} whose other end is tests/host/hckline_ecu_sim.c: the REAL
 * firmware KWP core (shared/hckline.c) behind a modelled UART / 5-baud decoder
 * / rate follower. Time is virtual: a read's timeout is simulated milliseconds,
 * a BREAK is simulated milliseconds, so a full 5-baud entry costs no wall time.
 */
public final class HcklineSimLine implements Line {

    private final Process proc;
    private final Writer out;
    private final BufferedReader in;
    private final String id;
    private int baud = 10400;
    private final byte[] pend = new byte[8192];
    private int pHead, pTail;
    public int breaks;          /* BREAKs sent (a 5-baud attempt makes two) */
    public int writes;

    public HcklineSimLine(String exe, String id) throws IOException {
        this.id = id;
        proc = new ProcessBuilder(exe).redirectErrorStream(true).start();
        out = new OutputStreamWriter(proc.getOutputStream(), "US-ASCII");
        in = new BufferedReader(new InputStreamReader(proc.getInputStream(), "US-ASCII"));
    }

    public String cmd(String c) throws IOException {
        out.write(c + "\n");
        out.flush();
        String r = in.readLine();
        if (r == null) throw new IOException("simulator died");
        if (r.startsWith("err")) throw new IOException("simulator: " + r + " for " + c);
        return r;
    }

    public void cfg(String key, Object v) throws IOException { cmd("cfg " + key + " " + v); }

    public String state() throws IOException { return cmd("st"); }

    public void setBaud(int b) { baud = b; }
    public int getBaud() { return baud; }
    public void purge() throws IOException { pHead = pTail = 0; }
    public String id() { return id; }

    public void sendBreak(int ms) throws IOException { breaks++; cmd("brk " + ms); }
    public void idle(int ms) throws IOException { cmd("idle " + ms); }

    public void write(byte[] data) throws IOException {
        writes++;
        StringBuilder sb = new StringBuilder("wr " + baud + " ");
        for (byte b : data) sb.append(String.format("%02X", b & 0xFF));
        cmd(sb.toString());
    }

    public int read(byte[] buf, int off, int len, int timeoutMs) throws IOException {
        if (pHead == pTail) {
            String r = cmd("rd " + baud + " " + Math.max(0, timeoutMs));
            String hex = r.substring(3).trim();
            if (!hex.equals("-")) {
                for (int i = 0; i + 1 < hex.length(); i += 2) {
                    pend[pTail++] = (byte) Integer.parseInt(hex.substring(i, i + 2), 16);
                }
            }
        }
        int n = 0;
        while (n < len && pHead < pTail) buf[off + n++] = pend[pHead++];
        if (pHead == pTail) pHead = pTail = 0;
        return n;
    }

    public void close() {
        try { out.close(); } catch (IOException ignored) { }
        proc.destroy();
    }
}
