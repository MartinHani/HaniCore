package com.hanicore.tunerstudio;

import java.util.zip.CRC32;

/**
 * HaniCore wire-protocol helpers shared by the Auto-connect engine: the
 * TunerStudio CRC envelope (for the Direct signature probe and the post-switch
 * probe) and the KWP vehicle-mode frames (for the VEHICLE path).
 *
 * These match the ECU exactly:
 *   - the TS envelope matches hcts.c (request 00 len payload crc32; response
 *     len16 code data crc32; CRC32 is zlib/IEEE over the CRC'd span);
 *   - the KWP frames match hckline.c (addressed ISO 14230 fmt tgt src ... cksum,
 *     8-bit sum checksum; StartCommunication 0x81; private SIDs 0xB0 IDENTIFY
 *     'HC' -> 0xF0 + the TS signature, 0xB1 GOFAST <code> -> 0xF1 <code>).
 */
public final class HcProtocol {

    private HcProtocol() {}

    /* --- baud codes on the GOFAST wire (match hckline.h) --- */
    public static final int BAUD_10400 = 10400;
    public static final int BAUD_57600 = 57600;
    public static final int BAUD_115200 = 115200;
    public static final int BAUD_124800 = 124800;
    public static final int CODE_10400 = 0x01;
    public static final int CODE_57600 = 0x02;
    public static final int CODE_124800 = 0x03;
    public static final int CODE_115200 = 0x04;   /* V96 (hckline.h) */

    public static final int SID_IDENTIFY = 0xB0;
    public static final int SID_GOFAST = 0xB1;
    public static final int SID_START_COMM = 0x81;
    public static final int RESP_OFFSET = 0x40;
    public static final int SID_NEG = 0x7F;

    /* 5-baud handshake constants (OEM PROVEN, Porsche ME7.1.1). */
    public static final int SLOW_ADDR = 0x01;
    public static final int SYNC = 0x55;
    public static final int KB1 = 0xEF;
    public static final int KB2 = 0x8F;

    /** The substring that identifies a HaniCore ECU. It is in the TS
        signature ("rusEFI HaniCore ME711 <layout>") and, since the IDENTIFY
        (0xF0) payload IS that signature (hckwp_me711.c KW_SIG), in both. */
    public static final String IDENTITY = "HaniCore";

    /** The GOFAST code for a TunerStudio baud, or -1 when the ECU cannot be
        asked for that rate (it negotiates 57600, 115200 and 124800 only). */
    public static int baudToCode(int baud) {
        if (baud == BAUD_124800) return CODE_124800;
        if (baud == BAUD_115200) return CODE_115200;
        if (baud == BAUD_57600) return CODE_57600;
        return -1;
    }

    /** zlib/IEEE CRC-32 over data[off..off+len), the one hcts_crc32 produces. */
    public static long crc32(byte[] data, int off, int len) {
        CRC32 c = new CRC32();
        c.update(data, off, len);
        return c.getValue();
    }

    /* ---------------------------------------------------------- TS envelope -- */

    /** Build a TunerStudio CRC request envelope: 00, len, payload, crc32(BE). */
    public static byte[] tsRequest(byte[] payload) {
        int n = payload.length;
        byte[] out = new byte[2 + n + 4];
        out[0] = 0x00;
        out[1] = (byte) n;
        System.arraycopy(payload, 0, out, 2, n);
        long crc = crc32(payload, 0, n);
        putBE32(out, 2 + n, crc);
        return out;
    }

    /** The signature query request ('S' in a CRC envelope). */
    public static byte[] tsSignatureRequest() {
        return tsRequest(new byte[] { 'S' });
    }

    /**
     * Scan {@code buf[0..len)} for the first valid TS response envelope and
     * return its CRC'd span (code byte first), or null if none is present. This
     * tolerates a leading echo of the request, stale bytes and partial echo,
     * because it searches every offset for a self-consistent CRC frame - an echo
     * of the request never carries a valid RESPONSE CRC, so it can never be
     * mistaken for a reply.
     */
    public static byte[] findTsResponse(byte[] buf, int len) {
        for (int i = 0; i + 2 <= len; i++) {
            int l = ((buf[i] & 0xFF) << 8) | (buf[i + 1] & 0xFF);
            if (l < 1 || l > 512) continue;
            int end = i + 2 + l + 4;
            if (end > len) continue;
            long want = getBE32(buf, i + 2 + l);
            long have = crc32(buf, i + 2, l);
            if (want == have) {
                byte[] span = new byte[l];
                System.arraycopy(buf, i + 2, span, 0, l);
                return span;   // span[0] = code, span[1..] = data
            }
        }
        return null;
    }

    /**
     * True iff {@code buf[0..len)} contains a CRC-valid TS response whose code is
     * TS_OK (0x00) AND whose payload contains the HaniCore identity string.
     *
     * This is the whole "echo must never count" rule in one place. The request
     * we send is {@code 00 01 'S' crc32('S')}; echoed back verbatim it IS a
     * self-consistent CRC frame, but its code byte is 'S' (0x53), not TS_OK, and
     * it carries no signature - so it is rejected. Only a genuine reply from a
     * HaniCore ECU passes. The scan continues past a non-matching valid frame,
     * so an echo prefix ahead of the real reply does not hide it.
     */
    public static boolean findSignature(byte[] buf, int len) {
        for (int i = 0; i + 2 <= len; i++) {
            int l = ((buf[i] & 0xFF) << 8) | (buf[i + 1] & 0xFF);
            if (l < 1 || l > 512) continue;
            int end = i + 2 + l + 4;
            if (end > len) continue;
            if (crc32(buf, i + 2, l) != getBE32(buf, i + 2 + l)) continue;
            if ((buf[i + 2] & 0xFF) != 0x00) continue;          /* must be TS_OK */
            byte[] span = new byte[l - 1];
            System.arraycopy(buf, i + 3, span, 0, l - 1);
            if (containsAscii(span, IDENTITY)) return true;
        }
        return false;
    }

    /** The signature text of the first CRC-valid TS_OK reply that carries the
        HaniCore identity, or null (same rules as findSignature). */
    public static String signatureText(byte[] buf, int len) {
        for (int i = 0; i + 2 <= len; i++) {
            int l = ((buf[i] & 0xFF) << 8) | (buf[i + 1] & 0xFF);
            if (l < 1 || l > 512) continue;
            if (i + 2 + l + 4 > len) continue;
            if (crc32(buf, i + 2, l) != getBE32(buf, i + 2 + l)) continue;
            if ((buf[i + 2] & 0xFF) != 0x00) continue;
            byte[] span = new byte[l - 1];
            System.arraycopy(buf, i + 3, span, 0, l - 1);
            if (containsAscii(span, IDENTITY)) return ascii(span);
        }
        return null;
    }

    /** Printable ASCII up to the first NUL. */
    public static String ascii(byte[] b) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < b.length && b[i] != 0; i++) {
            int c = b[i] & 0xFF;
            sb.append(c >= 0x20 && c < 0x7F ? (char) c : '?');
        }
        return sb.toString();
    }

    /* ------------------------------------------------------------ KWP frame -- */

    /** Build an addressed KWP request tgt<-ecu from src=tester carrying data. */
    public static byte[] kwpFrame(int ecuAddr, int testerAddr, byte[] data) {
        int n = data.length;
        byte[] out;
        int idx = 0;
        if (n <= 0x3F) {
            out = new byte[3 + n + 1];
            out[idx++] = (byte) (0x80 | n);
            out[idx++] = (byte) ecuAddr;
            out[idx++] = (byte) testerAddr;
        } else {
            out = new byte[4 + n + 1];
            out[idx++] = (byte) 0x80;
            out[idx++] = (byte) ecuAddr;
            out[idx++] = (byte) testerAddr;
            out[idx++] = (byte) n;
        }
        System.arraycopy(data, 0, out, idx, n);
        idx += n;
        int sum = 0;
        for (int i = 0; i < idx; i++) sum += (out[i] & 0xFF);
        out[idx] = (byte) sum;
        return out;
    }

    /**
     * Scan for a valid KWP response addressed to the tester and return its data
     * bytes (service id first), or null. Validates the format byte, that the
     * frame is addressed to us (tgt == testerAddr), and the 8-bit sum checksum -
     * so a K-line echo of our own request (addressed to the ECU) is rejected.
     */
    public static byte[] findKwpResponse(byte[] buf, int len, int ecuAddr, int testerAddr) {
        for (int i = 0; i < len; i++) {
            int fmt = buf[i] & 0xFF;
            if ((fmt & 0x80) == 0 || (fmt & 0x40) != 0) continue;  /* addressed, not functional */
            int dl = fmt & 0x3F;
            int hdr = (dl != 0) ? 3 : 4;
            if (i + hdr > len) continue;
            if (dl == 0) dl = buf[i + 3] & 0xFF;
            if (dl < 1) continue;
            int total = hdr + dl + 1;
            if (i + total > len) continue;
            if ((buf[i + 1] & 0xFF) != testerAddr) continue;       /* reply is to us */
            int sum = 0;
            for (int j = 0; j < total - 1; j++) sum += (buf[i + j] & 0xFF);
            if ((sum & 0xFF) != (buf[i + total - 1] & 0xFF)) continue;
            byte[] data = new byte[dl];
            System.arraycopy(buf, i + hdr, data, 0, dl);
            return data;
        }
        return null;
    }

    static void putBE32(byte[] b, int off, long v) {
        b[off] = (byte) ((v >> 24) & 0xFF);
        b[off + 1] = (byte) ((v >> 16) & 0xFF);
        b[off + 2] = (byte) ((v >> 8) & 0xFF);
        b[off + 3] = (byte) (v & 0xFF);
    }

    static long getBE32(byte[] b, int off) {
        return (((long) (b[off] & 0xFF)) << 24)
             | (((long) (b[off + 1] & 0xFF)) << 16)
             | (((long) (b[off + 2] & 0xFF)) << 8)
             | ((long) (b[off + 3] & 0xFF));
    }

    public static boolean containsAscii(byte[] data, String needle) {
        if (data == null) return false;
        byte[] n = needle.getBytes();
        if (n.length == 0 || data.length < n.length) return false;
        for (int i = 0; i + n.length <= data.length; i++) {
            int j = 0;
            while (j < n.length && data[i + j] == n[j]) j++;
            if (j == n.length) return true;
        }
        return false;
    }
}
