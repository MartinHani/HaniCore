package com.hanicore.tunerstudio;

import java.io.IOException;
import java.io.InputStream;

import jssc.SerialPort;
import jssc.SerialPortException;

/**
 * The production {@link Line}: a JSSC serial port of its own, opened by the
 * plugin BEFORE TunerStudio opens the same port and closed before TunerStudio
 * does (the order me711_kwp_connect.py proved on the bench: helper, close,
 * TunerStudio). JSSC is the library TunerStudio itself uses (lib/jssc.jar).
 *
 * BREAK is SetCommBreak / sleep / ClearCommBreak inside jssc's sendBreak -
 * the primitive pyserial's break_condition used for the physically qualified
 * 5-baud entry (V95: 10/10 at 124800, 5/5 at 57600).
 */
public final class SerialPortLine implements Line {

    private final String name;
    private final SerialPort port;
    private final boolean borrowed;   /* TunerStudio's own open port: never closed here */
    private final InputStream in;     /* borrowed: TunerStudio's listener stream (aD.d
                                         drains the port on every serial event, so
                                         bytes must be read where it puts them) */
    private int baud;

    public SerialPortLine(String name, int initialBaud) throws IOException {
        this.name = name;
        this.port = new SerialPort(name);
        this.borrowed = false;
        this.in = null;
        try {
            port.openPort();
            port.setParams(initialBaud, 8, 1, 0);
            baud = initialBaud;
        } catch (SerialPortException e) {
            close();
            throw new IOException("cannot open " + name + ": " + e.getExceptionType(), e);
        }
    }

    /**
     * TunerStudio's OWN open port (aD.a's jssc.SerialPort), for a recovery in
     * the middle of its session. setBaud uses the same 4-argument setParams
     * TunerStudio uses (RTS/DTR asserted, as jssc does for that overload), so
     * the port is left exactly as TunerStudio configured it once the engine
     * has moved it back to TunerStudio's baud.
     */
    public SerialPortLine(SerialPort open, InputStream tsIn, int currentBaud) {
        this.name = open.getPortName();
        this.port = open;
        this.borrowed = true;
        this.in = tsIn;
        this.baud = currentBaud;
    }

    public void setBaud(int b) throws IOException {
        try {
            port.setParams(b, 8, 1, 0);
            baud = b;
        } catch (SerialPortException e) {
            throw new IOException("set " + b + " baud: " + e.getExceptionType(), e);
        }
    }

    public int getBaud() { return baud; }

    public void purge() throws IOException {
        try {
            port.purgePort(SerialPort.PURGE_RXCLEAR | SerialPort.PURGE_TXCLEAR);
        } catch (SerialPortException e) {
            throw new IOException("purge: " + e.getExceptionType(), e);
        }
        if (in != null) {
            byte[] junk = new byte[256];
            for (int i = 0; i < 64 && in.available() > 0; i++) {
                if (in.read(junk, 0, Math.min(junk.length, in.available())) <= 0) break;
            }
        }
    }

    public void sendBreak(int ms) throws IOException {
        try {
            port.sendBreak(ms);
        } catch (SerialPortException e) {
            throw new IOException("break: " + e.getExceptionType(), e);
        }
    }

    public void idle(int ms) {
        try { Thread.sleep(Math.max(0, ms)); }
        catch (InterruptedException e) { Thread.currentThread().interrupt(); }
    }

    public void write(byte[] data) throws IOException {
        try {
            port.writeBytes(data);
        } catch (SerialPortException e) {
            throw new IOException("write: " + e.getExceptionType(), e);
        }
    }

    public int read(byte[] buf, int off, int len, int timeoutMs) throws IOException {
        long end = System.nanoTime() + Math.max(0, timeoutMs) * 1000000L;
        if (in != null) {
            try {
                while (in.available() <= 0) {
                    if (System.nanoTime() >= end) return 0;
                    Thread.sleep(1L);
                }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return 0;
            }
            return in.read(buf, off, Math.min(len, in.available()));
        }
        try {
            int avail;
            while ((avail = port.getInputBufferBytesCount()) <= 0) {
                if (System.nanoTime() >= end) return 0;
                Thread.sleep(1L);
            }
            byte[] got = port.readBytes(Math.min(len, avail));
            if (got == null) return 0;
            System.arraycopy(got, 0, buf, off, got.length);
            return got.length;
        } catch (SerialPortException e) {
            throw new IOException("read: " + e.getExceptionType(), e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return 0;
        }
    }

    public void close() {
        if (borrowed) return;
        try { if (port.isOpened()) port.closePort(); } catch (SerialPortException ignored) { }
    }

    public String id() { return name; }
}
