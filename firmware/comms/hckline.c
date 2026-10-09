/*
 * hckline.c - HaniCore VAG / KWP vehicle-mode bootstrap core. SHARED CORE.
 *
 * See hckline.h for the target/core boundary and the evidence classes. Every
 * non-obvious constant here is either OEM PROVEN (read out of the Porsche
 * ME7.1.1 image) or a documented HANICORE EXTENSION.
 *
 * Discipline this file keeps, and every host/image test enforces:
 *   - no SFR access, no <reg167.h>;
 *   - no dynamic allocation, no floating point;
 *   - no unbounded loop (every loop is bounded by a fixed buffer size);
 *   - no blocking - time is passed in, never read from hardware here;
 *   - no unsolicited transmit - the ECU answers, it never speaks first.
 */
#include "hckline.h"

/* The default IDENTIFY payload after 0xF0. "HANICORE" then a one-byte
   capability bitmap of the baud codes we will accept in a GOFAST request.
   A target may override cfg.sig to carry its layout id / version instead. */
static const unsigned char HCKLINE_DEFAULT_SIG[] = {
    'H','A','N','I','C','O','R','E',
    (unsigned char)(HCKLINE_BAUD_124800 | (HCKLINE_BAUD_57600 << 2) |
                    (HCKLINE_BAUD_10400 << 4))  /* informational */
};

/* --------------------------------------------------------------- helpers -- */
static unsigned long elapsed(unsigned long now, unsigned long since)
{
    /* Unsigned wrap is well defined and the deltas here are far below the
       32-bit range, so this is correct across a microsecond-counter wrap. */
    return (unsigned long)(now - since);
}

static void tx_reset(hckline_t *k)
{
    k->tx_head = 0u;
    k->tx_tail = 0u;
}

/* Append one byte to the output FIFO. Overflow is impossible for the frames
   this core sends (a KWP reply is a handful of bytes and the FIFO is 64), but
   it is checked rather than assumed: a dropped tail is counted, never wrapped
   silently over live data. */
static void tx_put(hckline_t *k, unsigned char b)
{
    unsigned char next = (unsigned char)((k->tx_head + 1u) % HCKLINE_TX_MAX);
    if (next == k->tx_tail) {
        k->frames_bad++;        /* would overflow: drop, do not corrupt */
        return;
    }
    k->tx[k->tx_head] = b;
    k->tx_head = next;
}

static void rx_reset(hckline_t *k)
{
    k->rx_len = 0u;
    k->rx_need = 0u;
}

static void enter(hckline_t *k, unsigned char st, unsigned long now)
{
    k->state = st;
    k->t_state = now;
}

/* ============================================================ KWP framing ==
 *
 * Accepted request format (ISO 14230, physical addressing only):
 *
 *     [fmt] [tgt] [src] [len?] [data ...] [cksum]
 *
 *   fmt   : bit7 set = addressed; bits5..0 = length, or 0 => a separate length
 *           byte follows src. bit6 (functional) is REJECTED - a broadcast must
 *           never make HaniCore act.
 *   tgt   : must equal cfg.ecu_addr (physical to us).
 *   src   : the tester; remembered for the reply.
 *   cksum : 8-bit sum of every preceding byte.
 *
 * The reply is built the same way with tgt/src swapped.
 */

/* How many bytes the buffered frame needs in total, or 0 if not yet known.
   Returns 0xFF if the header is malformed (caller drops the frame). */
static unsigned int frame_total(const hckline_t *k)
{
    unsigned char fmt;
    unsigned char len;

    if (k->rx_len < 1u) {
        return 0u;
    }
    fmt = k->rx[0];
    if ((fmt & 0x80u) == 0u) {
        return 0xFFu;           /* not addressed - not for us */
    }
    if ((fmt & 0x40u) != 0u) {
        return 0xFFu;           /* functional/broadcast - refused */
    }
    len = (unsigned char)(fmt & 0x3Fu);
    if (len != 0u) {
        /* fmt tgt src data[len] cksum */
        return (unsigned int)(3u + len + 1u);
    }
    /* length is in a separate byte after src: fmt tgt src len data[len] cksum */
    if (k->rx_len < 4u) {
        return 0u;              /* need the length byte first */
    }
    len = k->rx[3];
    if (len == 0u || len > (HCKLINE_RX_MAX - 5u)) {
        return 0xFFu;
    }
    return (unsigned int)(4u + len + 1u);
}

/* Pointers into a validated frame. */
static unsigned char frame_data_off(const hckline_t *k)
{
    unsigned char fmt = k->rx[0];
    return (unsigned char)(((fmt & 0x3Fu) != 0u) ? 3u : 4u);
}

static unsigned char frame_data_len(const hckline_t *k)
{
    unsigned char fmt = k->rx[0];
    if ((fmt & 0x3Fu) != 0u) {
        return (unsigned char)(fmt & 0x3Fu);
    }
    return k->rx[3];
}

static unsigned char checksum(const unsigned char *p, unsigned int n)
{
    unsigned int i;
    unsigned char c = 0u;
    for (i = 0u; i < n; i++) {
        c = (unsigned char)(c + p[i]);
    }
    return c;
}

/* Queue a reply carrying the given service payload. Addressed form, length in a
   separate byte when it does not fit in the format nibble. */
static void send_reply(hckline_t *k, const unsigned char *data, unsigned char n)
{
    /* STATIC, not a local: on the ME7.1.1 the user stack is 256 bytes with a
       margin of tens (me711_stack_proof), and this core is not re-entrant. */
    static unsigned char frame[HCKLINE_TX_MAX];
    unsigned int idx = 0u;
    unsigned int i;

    if (n <= 0x3Fu && (unsigned int)(3u + n + 1u) <= HCKLINE_TX_MAX) {
        frame[idx++] = (unsigned char)(0x80u | n);
        frame[idx++] = k->cfg.tester_addr;   /* reply target = tester */
        frame[idx++] = k->cfg.ecu_addr;       /* reply source = us     */
    } else if ((unsigned int)(4u + n + 1u) <= HCKLINE_TX_MAX) {
        frame[idx++] = 0x80u;                 /* addressed, len in byte */
        frame[idx++] = k->cfg.tester_addr;
        frame[idx++] = k->cfg.ecu_addr;
        frame[idx++] = n;
    } else {
        k->frames_bad++;
        return;
    }
    for (i = 0u; i < n; i++) {
        frame[idx++] = data[i];
    }
    frame[idx] = checksum(frame, idx);
    idx++;

    for (i = 0u; i < idx; i++) {
        tx_put(k, frame[i]);
    }
}

static void send_negative(hckline_t *k, unsigned char sid, unsigned char nrc)
{
    unsigned char d[3];
    d[0] = HCKLINE_SID_NEG;
    d[1] = sid;
    d[2] = nrc;
    send_reply(k, d, 3u);
    k->nak_sent++;
}

/* ------------------------------------------------------- service dispatch -- */
static void service(hckline_t *k, unsigned long now)
{
    unsigned char off = frame_data_off(k);
    unsigned char len = frame_data_len(k);
    const unsigned char *d = &k->rx[off];
    unsigned char sid;
    static unsigned char resp[HCKLINE_SIG_MAX + 2u];   /* not on the stack */
    const unsigned char *sig;
    unsigned char sig_len;
    unsigned int i;

    if (len < 1u) {
        k->frames_bad++;
        return;
    }
    sid = d[0];

    switch (sid) {
    case HCKLINE_SID_START_COMM:
        /* Comms already up via 5-baud; acknowledge idempotently. */
        resp[0] = (unsigned char)(HCKLINE_SID_START_COMM + HCKLINE_RESP_OFFSET);
        send_reply(k, resp, 1u);
        break;

    case HCKLINE_SID_START_DIAG:
        resp[0] = (unsigned char)(HCKLINE_SID_START_DIAG + HCKLINE_RESP_OFFSET);
        /* echo the session sub-function if present */
        if (len >= 2u) {
            resp[1] = d[1];
            send_reply(k, resp, 2u);
        } else {
            send_reply(k, resp, 1u);
        }
        break;

    case HCKLINE_SID_TESTER_PRES:
        resp[0] = (unsigned char)(HCKLINE_SID_TESTER_PRES + HCKLINE_RESP_OFFSET);
        send_reply(k, resp, 1u);
        break;

    case HCKLINE_SID_IDENTIFY:
        /* Require the "HC" magic so this cannot answer on a partial match. */
        if (len < 3u || d[1] != 'H' || d[2] != 'C') {
            send_negative(k, sid, HCKLINE_NRC_FMT);
            break;
        }
        sig = (k->cfg.sig != 0) ? k->cfg.sig : HCKLINE_DEFAULT_SIG;
        sig_len = (k->cfg.sig != 0) ? k->cfg.sig_len
                                    : (unsigned char)sizeof(HCKLINE_DEFAULT_SIG);
        if (sig_len > HCKLINE_SIG_MAX) {
            sig_len = HCKLINE_SIG_MAX;
        }
        resp[0] = (unsigned char)(HCKLINE_SID_IDENTIFY + HCKLINE_RESP_OFFSET);
        for (i = 0u; i < sig_len; i++) {
            resp[1u + i] = sig[i];
        }
        send_reply(k, resp, (unsigned char)(1u + sig_len));
        k->identified = 1u;     /* the identity gate is now open */
        break;

    case HCKLINE_SID_GOFAST:
        /* Identity gate: never switch baud on an unidentified ECU. */
        if (!k->identified) {
            send_negative(k, sid, HCKLINE_NRC_COND_WRONG);
            break;
        }
        if (len < 2u) {
            send_negative(k, sid, HCKLINE_NRC_FMT);
            break;
        }
        if (d[1] != HCKLINE_BAUD_10400 && d[1] != HCKLINE_BAUD_57600 &&
            d[1] != HCKLINE_BAUD_124800 && d[1] != HCKLINE_BAUD_115200) {
            send_negative(k, sid, HCKLINE_NRC_SUBF_NOT_SUP);
            break;
        }
        /* Positive response at the OLD baud, THEN (once drained) the switch. */
        resp[0] = (unsigned char)(HCKLINE_SID_GOFAST + HCKLINE_RESP_OFFSET);
        resp[1] = d[1];
        send_reply(k, resp, 2u);
        k->baud_pending = 1u;
        k->baud_code = d[1];
        break;

    case HCKLINE_SID_STOP_COMM:
        resp[0] = (unsigned char)(HCKLINE_SID_STOP_COMM + HCKLINE_RESP_OFFSET);
        send_reply(k, resp, 1u);
        /* Return to idle after the reply drains; the target sees tx go empty
           and the state is already SESSION->IDLE-bound. Simplest correct
           behaviour: go idle now; the queued reply still drains from the FIFO. */
        enter(k, HCKLINE_ST_IDLE, now);
        k->identified = 0u;
        break;

    default:
        send_negative(k, sid, HCKLINE_NRC_SVC_NOT_SUPP);
        break;
    }
}

/* One bad frame in SESSION. Only a complete, addressed, checksum-valid
   frame refreshes P3 now; a run of HCKLINE_BAD_RUN_MAX bad ones means the
   tester is gone or talking at another rate, and the session ends at once so
   the target can give the line back to TunerStudio. */
static void session_bad(hckline_t *k, unsigned long now)
{
    rx_reset(k);
    k->frames_bad++;
    if (k->bad_run != 0u && elapsed(now, k->t_bad) < HCKLINE_BAD_BURST_US) {
        return;                 /* the same burst */
    }
    k->t_bad = now;
    if (++k->bad_run >= HCKLINE_BAD_RUN_MAX) {
        k->bad_run = 0u;
        k->identified = 0u;
        k->sess_drops++;
        enter(k, HCKLINE_ST_IDLE, now);
    }
}

/* ============================================================= public API == */
void hckline_default_cfg(hckline_cfg_t *cfg)
{
    cfg->addr        = 0x01u;   /* OEM PROVEN: the only slow-init record here  */
    cfg->sync        = 0x55u;   /* OEM PROVEN                                  */
    cfg->kb1         = 0xEFu;   /* OEM PROVEN                                  */
    cfg->kb2         = 0x8Fu;   /* OEM PROVEN                                  */
    cfg->ecu_addr    = 0x01u;   /* physical KWP address of the engine ECU      */
    cfg->tester_addr = 0xF1u;   /* conventional external-tester address        */

    cfg->w1_us       = 60000uL; /* ISO 14230 W1 min                           */
    cfg->w2_us       = 5000uL;  /* ISO 14230 W2 min                           */
    cfg->w3_us       = 1000uL;  /* ISO 14230 W3 (0..20 ms); small             */
    cfg->w4_us       = 50000uL; /* ISO 14230 W4 max window for the complement  */
    cfg->p2_us       = 50000uL; /* generous request->response ceiling         */
    cfg->p3_us       = 5000000uL;/* 5 s session inactivity -> idle             */

    cfg->retries     = 1u;      /* OEM does one complement retry               */

    cfg->sig         = 0;       /* use HCKLINE_DEFAULT_SIG                     */
    cfg->sig_len     = 0u;
}

void hckline_init(hckline_t *k, const hckline_cfg_t *cfg)
{
    unsigned int i;
    unsigned char *p = (unsigned char *)k;
    for (i = 0u; i < sizeof(*k); i++) {
        p[i] = 0u;              /* no ?C_INIT on target: clear explicitly */
    }
    k->cfg = *cfg;
    k->state = HCKLINE_ST_IDLE;
}

void hckline_reset(hckline_t *k)
{
    k->state = HCKLINE_ST_IDLE;
    k->t_state = 0u;
    k->t_rx = 0u;
    rx_reset(k);
    tx_reset(k);
    k->identified = 0u;
    k->retry_used = 0u;
    k->baud_pending = 0u;
    k->baud_code = 0u;
}

void hckline_on_slow_init(hckline_t *k, unsigned char addr, unsigned long now_us)
{
    if (addr != k->cfg.addr) {
        k->wrong_addr++;
        return;                 /* not our address: stay dormant */
    }
    /* A fresh 5-baud attempt always restarts the handshake, even mid-session:
       the tester has power-cycled its adapter. */
    tx_reset(k);
    rx_reset(k);
    k->identified = 0u;
    k->retry_used = 0u;
    k->baud_pending = 0u;
    enter(k, HCKLINE_ST_SYNC, now_us);
}

void hckline_on_rx(hckline_t *k, unsigned char b, unsigned long now_us)
{
    unsigned int total;

    if (k->state == HCKLINE_ST_COMPL) {
        /* Expect the tester complement of keybyte 2. */
        if (b == (unsigned char)(~k->cfg.kb2)) {
            enter(k, HCKLINE_ST_ECU_COMPL, now_us);   /* send ~addr in tick */
        } else {
            /* Wrong complement: one retry (restart the handshake) then fail. */
            if (!k->retry_used && k->cfg.retries > 0u) {
                k->retry_used = 1u;
                enter(k, HCKLINE_ST_SYNC, now_us);
            } else {
                k->init_fail++;
                enter(k, HCKLINE_ST_IDLE, now_us);
            }
        }
        return;
    }

    if (k->state != HCKLINE_ST_SESSION) {
        /* Bytes arriving in any handshake state other than COMPL are noise
           (or our own un-swallowed echo, which the target must not feed us).
           Ignore them; do not let noise advance the machine. */
        return;
    }

    /* SESSION: assemble a KWP frame. */
    if (k->rx_len != 0u && elapsed(now_us, k->t_byte) > HCKLINE_STALE_US) {
        session_bad(k, now_us); /* a stale partial frame */
        if (k->state != HCKLINE_ST_SESSION) {
            return;
        }
    }
    k->t_byte = now_us;
    if (k->rx_len >= HCKLINE_RX_MAX) {
        session_bad(k, now_us); /* oversize: drop and resync */
        return;
    }
    k->rx[k->rx_len++] = b;

    total = frame_total(k);
    if (total == 0xFFu) {
        session_bad(k, now_us); /* malformed header (functional, bad len) */
        return;
    }
    if (total == 0u) {
        return;                 /* header not complete yet */
    }
    k->rx_need = (unsigned char)total;
    if (k->rx_len < k->rx_need) {
        return;                 /* still gathering */
    }

    /* Complete frame. Validate address and checksum. */
    if (k->rx[1] != k->cfg.ecu_addr) {
        rx_reset(k);            /* not addressed to us */
        return;
    }
    if (checksum(k->rx, (unsigned int)(k->rx_need - 1u)) != k->rx[k->rx_need - 1u]) {
        session_bad(k, now_us);
        return;
    }

    k->frames_ok++;
    k->bad_run = 0u;
    k->t_rx = now_us;           /* P3 runs from the last VALID frame */
    service(k, now_us);
    rx_reset(k);
}

void hckline_tick(hckline_t *k, unsigned long now_us)
{
    switch (k->state) {
    case HCKLINE_ST_SYNC:
        if (elapsed(now_us, k->t_state) >= k->cfg.w1_us) {
            tx_put(k, k->cfg.sync);
            enter(k, HCKLINE_ST_KB1, now_us);
        }
        break;

    case HCKLINE_ST_KB1:
        if (elapsed(now_us, k->t_state) >= k->cfg.w2_us) {
            tx_put(k, k->cfg.kb1);
            enter(k, HCKLINE_ST_KB2, now_us);
        }
        break;

    case HCKLINE_ST_KB2:
        if (elapsed(now_us, k->t_state) >= k->cfg.w3_us) {
            tx_put(k, k->cfg.kb2);
            enter(k, HCKLINE_ST_COMPL, now_us);
        }
        break;

    case HCKLINE_ST_COMPL:
        if (elapsed(now_us, k->t_state) >= k->cfg.w4_us) {
            /* No complement in time: one retry, else fail to idle. */
            if (!k->retry_used && k->cfg.retries > 0u) {
                k->retry_used = 1u;
                enter(k, HCKLINE_ST_SYNC, now_us);
            } else {
                k->init_fail++;
                enter(k, HCKLINE_ST_IDLE, now_us);
            }
        }
        break;

    case HCKLINE_ST_ECU_COMPL:
        /* Send the ECU complement of the address (~addr), then the session is
           open. No W-timer here: the OEM sends it as soon as it has the tester
           complement. */
        tx_put(k, (unsigned char)(~k->cfg.addr));
        k->init_ok++;
        rx_reset(k);
        k->t_rx = 0u;           /* P3 from the session's start until a frame */
        k->bad_run = 0u;
        enter(k, HCKLINE_ST_SESSION, now_us);
        break;

    case HCKLINE_ST_SESSION:
        /* P3 inactivity: if nothing has been received for p3_us, drop to idle.
           t_rx is 0 until the first byte; guard with t_state so a silent
           session still times out from when it opened. */
        {
            unsigned long ref = (k->t_rx != 0u) ? k->t_rx : k->t_state;
            if (elapsed(now_us, ref) >= k->cfg.p3_us) {
                k->identified = 0u;
                enter(k, HCKLINE_ST_IDLE, now_us);
            }
        }
        break;

    default:
        break;                  /* IDLE, PRIVATE: nothing scheduled */
    }
}

unsigned char hckline_tx_pop(hckline_t *k, unsigned char *b)
{
    if (k->tx_tail == k->tx_head) {
        return 0u;
    }
    *b = k->tx[k->tx_tail];
    k->tx_tail = (unsigned char)((k->tx_tail + 1u) % HCKLINE_TX_MAX);
    return 1u;
}

unsigned char hckline_tx_busy(const hckline_t *k)
{
    return (unsigned char)(k->tx_tail != k->tx_head);
}

unsigned char hckline_take_baud(hckline_t *k, unsigned char *code)
{
    if (!k->baud_pending) {
        return 0u;
    }
    if (hckline_tx_busy(k)) {
        return 0u;              /* answer + echo must leave the wire first */
    }
    *code = k->baud_code;
    k->baud_pending = 0u;
    return 1u;
}

void hckline_enter_private(hckline_t *k)
{
    /* The UART is now at the negotiated rate and the K-line carries raw
       HaniCore/TunerStudio framing. The core stops touching the wire. */
    rx_reset(k);
    tx_reset(k);
    k->state = HCKLINE_ST_PRIVATE;
}
