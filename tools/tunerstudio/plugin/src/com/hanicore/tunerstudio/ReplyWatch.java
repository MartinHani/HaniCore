package com.hanicore.tunerstudio;

import java.io.ByteArrayOutputStream;

/**
 * A request the ECU never received is sent again, at once - not after
 * TunerStudio's 8 s blockReadTimeout.
 *
 * On the car's shared K-line (OBD pin 7 through the instrument cluster) a
 * byte from another module can land on top of a request: the ECU sees a bad
 * CRC and stays silent (an error reply would end the TunerStudio session),
 * and TunerStudio waits blockReadTimeout - 8000 ms, the HaniCore .ini, sized
 * for a Burn's deferred reply - before it re-establishes the link
 * (TunerStudioAppDebug 2026-10-15: "Timeout after:8001ms").
 *
 * The watch assembles TunerStudio's msEnvelope requests (u16 length, payload,
 * CRC32) from what it writes. When a complete request has had no byte from the
 * ECU for {@code resendMs}, {@link #due} hands it back to be sent again, at
 * most {@code maxResends} times. The ECU answers within a main-loop pass
 * (~30 ms worst), so silence that long means it never got the request.
 * Only requests that are safe to repeat are re-sent: reads, and value writes
 * (the same bytes to the same offset). Never a Burn (its reply is deferred for
 * seconds), a '!' action or a logger read (it frees the buffer).
 * Pure logic: time is passed in.
 */
public final class ReplyWatch {

    private final long resendMs;
    private final int maxResends;
    private final ByteArrayOutputStream frame = new ByteArrayOutputStream();
    private byte[] armed;
    private long since;
    private int resends;
    private long total;

    public ReplyWatch(long resendMs, int maxResends) {
        this.resendMs = resendMs;
        this.maxResends = maxResends;
    }

    /** TunerStudio wrote these bytes (before the echo is taken). */
    public synchronized void wrote(byte[] b, int off, int len, long now) {
        armed = null;                       /* a new request: forget the old one */
        frame.write(b, off, len);
        byte[] f = frame.toByteArray();
        if (f.length < 2) return;
        int n = ((f[0] & 0xFF) << 8) | (f[1] & 0xFF);
        if (n == 0 || f.length > n + 6) {   /* not an envelope (or a stray) */
            frame.reset();
            return;
        }
        if (f.length < n + 6) return;       /* written in pieces: wait */
        frame.reset();
        if (!resendable(f[2])) return;
        armed = f;
        since = now;
        resends = 0;
    }

    /** A byte from the ECU arrived: the request was received. */
    public synchronized void received() {
        armed = null;
    }

    /** -> the request to send again now, or null. */
    public synchronized byte[] due(long now) {
        if (armed == null || now - since < resendMs) return null;
        if (resends >= maxResends) {
            armed = null;                   /* TunerStudio's own timeout decides */
            return null;
        }
        resends++;
        total++;
        since = now;
        return armed.clone();
    }

    /** Requests sent again since the watch was made. */
    public synchronized long resent() { return total; }

    static boolean resendable(byte cmd) {
        switch (cmd) {
            case 'S': case 'Q': case 'V': case 'F': case 'C': case 'I': case 'f':
            case 'O': case 'A': case 'P': case 'R': case 'p': case 'W':
                return true;
            default:
                return false;               /* 'B' Burn, '!' actions, 'l' logger */
        }
    }
}
