package com.hanicore.tunerstudio;

/**
 * Bounded exponential backoff for repeated reconnect attempts (a dropped
 * vehicle/private session must not become a reconnect storm - see the transport
 * rules in the HaniCore session notes). Delays double from {@code baseMs} up to
 * {@code maxMs}; a successful connect calls {@link #reset()}.
 */
public final class Backoff {
    private final long baseMs;
    private final long maxMs;
    private int n;

    public Backoff(long baseMs, long maxMs) {
        this.baseMs = Math.max(1L, baseMs);
        this.maxMs = Math.max(this.baseMs, maxMs);
        this.n = 0;
    }

    /** The delay to wait before the next attempt, then advance. */
    public long nextDelayMs() {
        int shift = (n > 20) ? 20 : n;      /* guard against overflow */
        long d = baseMs << shift;
        if (d > maxMs || d < 0L) d = maxMs;
        n++;
        return d;
    }

    /** Attempts made since the last reset. */
    public int attempts() { return n; }

    /** Called on a successful connect. */
    public void reset() { n = 0; }
}
