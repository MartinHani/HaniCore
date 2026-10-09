package com.hanicore.tunerstudio;

import java.io.IOException;
import java.util.ArrayDeque;

/**
 * Adapter faults in front of any {@link Line} (run the inner line with its own
 * echo off): the echo a KKL produces - full, none, partial, corrupted - stale
 * bytes ahead of every read burst, and an adapter without BREAK.
 */
public final class AdapterLine implements Line {

    public enum Echo { FULL, NONE, PARTIAL, CORRUPT }

    private final Line inner;
    private final Echo echo;
    private final int stale;
    private final boolean noBreak;
    private final ArrayDeque<Byte> local = new ArrayDeque<Byte>();

    public AdapterLine(Line inner, Echo echo, int staleBytes, boolean noBreak) {
        this.inner = inner; this.echo = echo; this.stale = staleBytes; this.noBreak = noBreak;
    }

    public void setBaud(int b) throws IOException { inner.setBaud(b); }
    public int getBaud() { return inner.getBaud(); }
    public void purge() throws IOException { local.clear(); inner.purge(); }
    public String id() { return inner.id(); }
    public void close() { inner.close(); }
    public void idle(int ms) throws IOException { inner.idle(ms); }

    public void sendBreak(int ms) throws IOException {
        if (noBreak) throw new IOException("BREAK not supported by this adapter");
        inner.sendBreak(ms);
    }

    public void write(byte[] data) throws IOException {
        for (int i = 0; i < stale; i++) local.add((byte) (0xA5 ^ i));
        for (int i = 0; i < data.length; i++) {
            byte b = data[i];
            switch (echo) {
                case FULL: local.add(b); break;
                case PARTIAL: if ((i & 1) == 0) local.add(b); break;
                case CORRUPT: local.add((byte) (b ^ 0x20)); break;
                default: break;
            }
        }
        inner.write(data);
    }

    public int read(byte[] buf, int off, int len, int timeoutMs) throws IOException {
        if (local.isEmpty()) return inner.read(buf, off, len, timeoutMs);
        int n = 0;
        while (n < len && !local.isEmpty()) buf[off + n++] = local.poll();
        return n;
    }
}
