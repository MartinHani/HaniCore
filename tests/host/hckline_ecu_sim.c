/*
 * hckline_ecu_sim.c - a virtual HaniCore ECU on a virtual K-line, driven over
 * stdin/stdout, so the TunerStudio plugin's Java AutoConnect engine can be
 * tested against the REAL firmware KWP core (firmware/comms/hckline.c) instead of a
 * Java re-statement of it (tools/plugin/test/.../HcklineSimLine.java).
 *
 * WHAT IS REAL AND WHAT IS A MODEL
 *   REAL   firmware/comms/hckline.c - handshake, KWP frames, IDENTIFY/GOFAST, P3,
 *          bad-burst session end: the object that is linked into the image.
 *   MODEL  the 5-baud decoder (the image's is GPT/port sampling in
 *          hckwp_me711.c, proven by me711_kwp_entry_proof and on the bench),
 *          the UART at a wrong rate (a byte sent at another rate arrives as a
 *          different byte, never as a framing error - V94 bench), the host
 *          adapter's echo, and the hcts rate follower (boot 57600 hunting; a
 *          hunting link follows after HUNT_FOLLOW bad requests, a locked one
 *          after LOCK_FOLLOW - the maintainer's design notes; the image's
 *          follower is proven by me711_link_rate_proof and physically).
 *
 * PROTOCOL (one command per line; every command answers exactly one line)
 *   cfg <key> <value>     echo 0|1, silent 0|1, stock 0|1, gate 0|1,
 *                         noslow 0|1 (ignore 5-baud; fast init still works),
 *                         boot <baud>, hunt_follow n, lock_follow n,
 *                         sig <text>
 *   reset                 the ECU power-cycles (boots hunting at 57600)
 *   brk <ms> / idle <ms>  the host holds the line low / high
 *   wr <baud> <hex>       the host transmits bytes at <baud>
 *   rd <baud> <ms>        wait up to <ms> for bytes; returns what the host's
 *                         receiver at <baud> sees (its own echo included)
 *   st                    state dump
 * Answers: "ok", "rx <hex>|-", "st ...", "err ...".
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "hckline.h"

#define US_PER_MS 1000uL

static hckline_t kw;
static hckline_cfg_t kw_cfg;
static unsigned char sig[HCKLINE_SIG_MAX + 1];
static unsigned long now_us;

/* the line / ECU model */
static int echo = 1, silent = 0, stock = 0;
static long ecu_baud = 57600;         /* the ECU UART rate                   */
static int kw_on = 0;                 /* a KWP session owns the UART (10400) */
static int locked = 0;                /* hcts: locked (1) or hunting (0)     */
static int hunt_follow = 1, lock_follow = 3, bad_reqs = 0;
static long last_host_baud = 0;
static int gate = 0, gate_open = 0;   /* a K-line that opens only after a
                                         valid 5-baud 0x01 (the case that
                                         makes the vehicle path necessary) */
static int noslow = 0;                /* 2026-10-13: the 5-baud entry is deaf */
static unsigned int lo_ms = 0;        /* the current low run (fast init)   */
static int gofasts = 0;               /* GOFAST requests the ECU acted on /
                                         received (stock)                   */
static unsigned char sk[64];          /* stock ECU: frame assembly          */
static int sk_n;

/* bytes waiting for the host: value and the rate they were sent at */
#define HQ 4096
static unsigned char hq_b[HQ];
static long hq_rate[HQ];
static int hq_n;

/* hcts request assembly (TS mode) */
static unsigned char req[600];
static int req_n;
static long req_rate;

/* 5-baud decoder model */
static int line_hi = 1;
static unsigned long hi_ms = 1000u;   /* line has been high this long         */
static int fb_st = 0;                 /* 0 idle, 1 in a byte (fb_i 9 = stop) */
static unsigned long fb_t;            /* ms since the falling edge            */
static int fb_byte, fb_i;

static unsigned long crc32(const unsigned char *p, int n)
{
    unsigned long c = 0xFFFFFFFFuL;
    int i, k;
    for (i = 0; i < n; i++) {
        c ^= p[i];
        for (k = 0; k < 8; k++)
            c = (c & 1uL) ? (c >> 1) ^ 0xEDB88320uL : (c >> 1);
    }
    return c ^ 0xFFFFFFFFuL;
}

static void to_host(unsigned char b, long rate)
{
    if (hq_n < HQ) { hq_b[hq_n] = b; hq_rate[hq_n] = rate; hq_n++; }
}

/* a byte sent at one rate and sampled at another: deterministic garbage */
static unsigned char garble(unsigned char b, long from, long to)
{
    return (unsigned char)(b ^ 0xA5u ^ (unsigned char)((from ^ to) & 0xFF));
}

static void ts_reply_signature(void)
{
    unsigned char out[80];
    int n = (int)strlen((const char *)sig), i;
    unsigned long c;
    out[0] = 0; out[1] = (unsigned char)(n + 1);
    out[2] = 0x00;                       /* TS_OK */
    memcpy(out + 3, sig, (size_t)n);
    c = crc32(out + 2, n + 1);
    out[3 + n] = (unsigned char)(c >> 24); out[4 + n] = (unsigned char)(c >> 16);
    out[5 + n] = (unsigned char)(c >> 8);  out[6 + n] = (unsigned char)c;
    for (i = 0; i < n + 7; i++) to_host(out[i], ecu_baud);
}

/* the end of a host burst in TS mode: answer, or count rate evidence */
static void ts_burst_end(void)
{
    int ok = 0;
    if (req_n == 0) return;
    if (gate && !gate_open) { req_n = 0; return; }   /* never reached the ECU */
    if (req_rate == ecu_baud && req_n >= 7 && req[0] == 0x00) {
        int n = req[1];
        if (n >= 1 && req_n >= n + 6) {
            unsigned long c = crc32(req + 2, n);
            unsigned long w = ((unsigned long)req[2 + n] << 24)
                | ((unsigned long)req[3 + n] << 16)
                | ((unsigned long)req[4 + n] << 8) | req[5 + n];
            ok = (c == w);
            if (ok && (req[2] == 'S' || req[2] == 'Q' || req[2] == 'V')) {
                ts_reply_signature();
                locked = 1;
                bad_reqs = 0;
            }
        }
    }
    if (!ok && req_rate != ecu_baud
        && (req_rate == 57600 || req_rate == 115200 || req_rate == 124800)) {
        if (++bad_reqs >= (locked ? lock_follow : hunt_follow)) {
            ecu_baud = req_rate;         /* the follower lands on the host */
            locked = 0;
            bad_reqs = 0;
        }
    }
    req_n = 0;
}

static void ecu_ms(void)
{
    unsigned char b, code;
    now_us += US_PER_MS;
    /* 5-baud decoder: falling edge after >= 300 ms high, sample bit centres */
    if (fb_st == 0) {
        /* hckwp_me711.c FB_IDLE_MS: 20 ms since 2026-10-13 (300 before) */
        if (!line_hi && hi_ms >= 20u) { fb_st = 1; fb_t = 0; fb_byte = 0; fb_i = 0; }
    } else {
        fb_t++;
        if (fb_t == 100u && line_hi) fb_st = 0;          /* not a start bit */
        else if (fb_i < 9 && fb_t >= 300u && ((fb_t - 300u) % 200u) == 0u) {
            if (fb_i < 8) { if (line_hi) fb_byte |= 1 << fb_i; fb_i++; }
            else if (!line_hi) fb_st = 0;                /* framing error */
            else fb_i = 9;                               /* stop bit good */
        } else if (fb_i == 9 && fb_t >= 2000u) {
            /* hckwp_me711.c fb_ms state 4: the address is handed to hckline
               at the END of the stop bit, not at its centre */
            {
                fb_st = 0;
                if (!silent && !noslow) {
                    ts_burst_end();
                    req_n = 0;
                    if (fb_byte == 0x01) gate_open = 1;
                    hckline_on_slow_init(&kw, (unsigned char)fb_byte, now_us);
                    if (kw.state != HCKLINE_ST_IDLE) {
                        kw_on = 1; ecu_baud = 10400; sk_n = 0;
                    }
                }
            }
        }
    }
    /* ISO 14230 FAST INIT (hckwp_me711.c kl_wakeup: the tick measures the
       low run; 20..30 ms opens the core's StartCommunication window) */
    if (line_hi) {
        if (lo_ms >= 20u && lo_ms <= 30u && !kw_on && !silent && !stock) {
            ts_burst_end();
            req_n = 0;
            gate_open = 1;
            hckline_on_fast_init(&kw, now_us);
            kw_on = 1; ecu_baud = 10400; sk_n = 0;
        }
        lo_ms = 0u;
    } else if (lo_ms < 60000u) {
        lo_ms++;
    }
    hi_ms = line_hi ? hi_ms + 1u : 0u;
    if (!kw_on) return;
    hckline_tick(&kw, now_us);
    while (hckline_tx_pop(&kw, &b)) to_host(b, 10400);
    if (hckline_take_baud(&kw, &code)) {
        ecu_baud = code == HCKLINE_BAUD_124800 ? 124800
                 : code == HCKLINE_BAUD_115200 ? 115200
                 : code == HCKLINE_BAUD_57600 ? 57600 : 10400;
        hckline_enter_private(&kw);
        kw_on = 0; locked = 1; bad_reqs = 0;
        gofasts++;
    } else if (kw.state == HCKLINE_ST_IDLE) {
        kw_on = 0; locked = 0;           /* failed / timed out: hunt again  */
    }
}

/* A stock ECU after the (identical, OEM) handshake: StartCommunication is
   answered, everything else "service not supported" - IDENTIFY gets 7F B0 11. */
static void stock_rx(unsigned char b)
{
    int dl, total, i;
    unsigned char out[6], sum = 0;
    if (sk_n < (int)sizeof sk) sk[sk_n++] = b;
    if ((sk[0] & 0xC0u) != 0x80u) { sk_n = 0; return; }
    dl = sk[0] & 0x3F;
    if (dl == 0 || sk_n < 3 + dl + 1) return;
    total = 3 + dl + 1;
    for (i = 0; i < total - 1; i++) sum = (unsigned char)(sum + sk[i]);
    if (sum == sk[total - 1] && sk[1] == 0x01u) {
        if (sk[3] == HCKLINE_SID_GOFAST) gofasts++;
        out[0] = 0x83; out[1] = 0xF1; out[2] = 0x01;
        if (sk[3] == HCKLINE_SID_START_COMM) {     /* C1 + its key bytes */
            out[3] = 0xC1; out[4] = 0xEF; out[5] = 0x8F;
        } else {
            out[3] = HCKLINE_SID_NEG; out[4] = sk[3];
            out[5] = HCKLINE_NRC_SVC_NOT_SUPP;
        }
        sum = 0;
        for (i = 0; i < 6; i++) { to_host(out[i], 10400); sum = (unsigned char)(sum + out[i]); }
        to_host(sum, 10400);
    }
    sk_n = 0;
}

static void advance(unsigned long ms)
{
    while (ms--) ecu_ms();
}

static int hexval(int c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static void host_write(long baud, const char *hex)
{
    unsigned long bit_us = 1000000uL / (unsigned long)baud;
    unsigned long acc = 0;
    last_host_baud = baud;
    if (req_n && req_rate != baud) ts_burst_end();
    while (hexval(hex[0]) >= 0 && hexval(hex[1]) >= 0) {
        unsigned char b = (unsigned char)(hexval(hex[0]) * 16 + hexval(hex[1]));
        hex += 2;
        if (echo) to_host(b, baud);      /* the adapter hears itself */
        if (!silent) {
            if (kw_on && stock && kw.state == HCKLINE_ST_SESSION) {
                stock_rx(baud == 10400 ? b : garble(b, baud, 10400));
            } else if (kw_on) {
                hckline_on_rx(&kw, baud == 10400 ? b : garble(b, baud, 10400),
                              now_us);
            } else {
                if (req_n < (int)sizeof(req)) req[req_n++] = b;
                req_rate = baud;
            }
        }
        acc += 10uL * bit_us;
        while (acc >= US_PER_MS) { acc -= US_PER_MS; ecu_ms(); }
    }
}

static void host_read(long baud, unsigned long ms)
{
    unsigned long t;
    int i, any = 0;
    ts_burst_end();                      /* the host stopped sending */
    for (t = 0; t < ms && hq_n == 0; t++) ecu_ms();
    if (hq_n) advance(3);                /* let the rest of the reply arrive */
    for (i = 0; i < hq_n; i++) {
        unsigned char b = hq_rate[i] == baud ? hq_b[i]
                        : garble(hq_b[i], hq_rate[i], baud);
        if (!any) { printf("rx "); any = 1; }
        printf("%02X", b);
    }
    hq_n = 0;
    printf(any ? "\n" : "rx -\n");
}

int main(void)
{
    char line[2048], cmd[16], arg[2048];
    long v;
    strcpy((char *)sig, "rusEFI HaniCore ME711 F26F2BF7");
    hckline_default_cfg(&kw_cfg);
    kw_cfg.sig = sig;
    kw_cfg.sig_len = (unsigned char)strlen((const char *)sig);
    hckline_init(&kw, &kw_cfg);
    while (fgets(line, sizeof line, stdin)) {
        arg[0] = 0; v = 0;
        if (sscanf(line, "%15s %2047[^\n]", cmd, arg) < 1) continue;
        if (!strcmp(cmd, "cfg")) {
            char key[32], val[256];
            if (sscanf(arg, "%31s %255[^\n]", key, val) != 2) { printf("err cfg\n"); continue; }
            v = atol(val);
            if (!strcmp(key, "echo")) echo = (int)v;
            else if (!strcmp(key, "silent")) silent = (int)v;
            else if (!strcmp(key, "stock")) stock = (int)v;
            else if (!strcmp(key, "gate")) gate = (int)v;
            else if (!strcmp(key, "noslow")) noslow = (int)v;
            else if (!strcmp(key, "boot")) ecu_baud = v;
            else if (!strcmp(key, "hunt_follow")) hunt_follow = (int)v;
            else if (!strcmp(key, "lock_follow")) lock_follow = (int)v;
            else if (!strcmp(key, "sig")) {
                strncpy((char *)sig, val, HCKLINE_SIG_MAX);
                sig[HCKLINE_SIG_MAX] = 0;
                kw_cfg.sig_len = (unsigned char)strlen((const char *)sig);
                hckline_init(&kw, &kw_cfg);
            } else { printf("err key\n"); continue; }
            printf("ok\n");
        } else if (!strcmp(cmd, "brk") || !strcmp(cmd, "idle")) {
            ts_burst_end();
            line_hi = !strcmp(cmd, "idle");
            advance((unsigned long)atol(arg));
            printf("ok\n");
        } else if (!strcmp(cmd, "wr")) {
            char *sp = strchr(arg, ' ');
            if (!sp) { printf("err wr\n"); continue; }
            *sp = 0;
            host_write(atol(arg), sp + 1);
            printf("ok\n");
        } else if (!strcmp(cmd, "rd")) {
            long b = 0, ms = 0;
            sscanf(arg, "%ld %ld", &b, &ms);
            host_read(b, (unsigned long)ms);
        } else if (!strcmp(cmd, "reset")) {
            hckline_init(&kw, &kw_cfg);
            ecu_baud = 57600; kw_on = 0; locked = 0; bad_reqs = 0;
            hq_n = 0; req_n = 0; sk_n = 0; gate_open = 0; fb_st = 0;
            printf("ok\n");
        } else if (!strcmp(cmd, "st")) {
            printf("st baud=%ld locked=%d kw_on=%d state=%u init_ok=%u "
                   "init_fail=%u drops=%u gofast=%d ms=%lu\n", ecu_baud, locked,
                   kw_on, kw.state, kw.init_ok, kw.init_fail, kw.sess_drops,
                   gofasts, now_us / 1000uL);
        } else {
            printf("err cmd\n");
        }
        fflush(stdout);
    }
    return 0;
}
