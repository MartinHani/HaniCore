package com.hanicore.tunerstudio;

import java.io.IOException;

/**
 * The small serial abstraction the HaniCore Auto-connect engine runs against.
 *
 * It is deliberately tiny: everything AutoConnect needs and nothing that ties it
 * to TunerStudio or JSSC. The production plugin adapts TunerStudio's internal
 * RS232 transport to this interface (see HaniCoreKLinePlugin); the tests supply
 * MockLine. Because AutoConnect only ever touches a Line, the SAME production
 * state machine is exercised with no TunerStudio present.
 *
 * Byte values are 0..255 carried in int/byte as usual. All timings are in
 * milliseconds.
 */
public interface Line {

    /** Set the line rate. Takes effect immediately (mid-session on a switch). */
    void setBaud(int baud) throws IOException;

    /** The current line rate. */
    int getBaud();

    /** Discard anything buffered in both directions. */
    void purge() throws IOException;

    /**
     * Hold a serial BREAK (line low) for {@code ms}, then release to idle. This
     * is the primitive the 5-baud vehicle init is built from. Blocks for the
     * duration on real hardware; MockLine advances a virtual clock instead.
     */
    void sendBreak(int ms) throws IOException;

    /** Idle (mark/high) for {@code ms} - the complement of sendBreak. */
    void idle(int ms) throws IOException;

    /** Write raw bytes. On a K-line these echo back into the receiver. */
    void write(byte[] data) throws IOException;

    /**
     * Read up to {@code len} bytes into {@code buf} at {@code off}, waiting up to
     * {@code timeoutMs} for the first byte. Returns the number read (0 on
     * timeout with nothing available), or -1 if the line is closed.
     */
    int read(byte[] buf, int off, int len, int timeoutMs) throws IOException;

    /** Release the port. */
    void close();

    /**
     * A stable identity for the adapter/port, used to remember the last-good
     * connection mode. Two physically different adapters must not share it.
     */
    String id();
}
