package com.hanicore.tunerstudio;

/**
 * When is a TunerStudio session dead enough to re-enter the ECU?
 *
 * TunerStudio re-establishes a silent connection INSIDE its RS232 class
 * (aD.a.r() calls its own close/open), and while it waits it simply keeps
 * sending on the open port - the plugin's open() never runs again. On a
 * direct wire that is fine (the ECU follows the host's rate after a power
 * cycle), but a line that only opens after a 5-baud init would stay shut
 * until the user pressed Disconnect / Connect. The watch says "recover" when
 * TunerStudio has written at least {@code minWrites} times over at least
 * {@code silenceMs} with no byte from the ECU, and not within
 * {@code intervalMs} of the last recovery. Pure logic: time is passed in.
 */
public final class SilenceWatch {

    private final long silenceMs, intervalMs;
    private final int minWrites;
    private long lastRx, lastRecovery = Long.MIN_VALUE / 2;
    private int writes;

    public SilenceWatch(long silenceMs, long intervalMs, int minWrites, long now) {
        this.silenceMs = silenceMs;
        this.intervalMs = intervalMs;
        this.minWrites = minWrites;
        this.lastRx = now;
    }

    /** Bytes from the ECU (after echo removal) reached TunerStudio. */
    public synchronized void received(long now) { lastRx = now; writes = 0; }

    /** TunerStudio is about to write; true = recover the link first. */
    public synchronized boolean beforeWrite(long now) {
        writes++;
        if (writes < minWrites) return false;
        if (now - lastRx < silenceMs) return false;
        if (now - lastRecovery < intervalMs) return false;
        lastRecovery = now;
        return true;
    }

    /** A recovery ran (successful or not): restart the silence measurement. */
    public synchronized void recovered(long now) { lastRx = now; writes = 0; }

    /** A fresh connection (open / re-establish). */
    public synchronized void reset(long now) { lastRx = now; writes = 0; }
}
