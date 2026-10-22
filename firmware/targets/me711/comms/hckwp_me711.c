/*
 * hckwp_me711.c - see hckwp_me711.h first. FAR, 16-BIT ARITHMETIC ONLY
 * (Keil's long multiply/divide helpers are near; the microsecond clock is
 * advanced by addition).
 */
#include "hcfarbridge.h"
#include <reg167.h>
#include "hctarget.h"
#include "hcts.h"
#include "hckline.h"
#include "hckwp_me711.h"
#include "hcserial711.h"   /* hc_tx_busy: our own echo is no break */

/* The IDENTIFY payload is the TunerStudio signature, so a tool that enters
   through the vehicle K-line learns the page layout (and the .ini it needs)
   before it switches rate. */
static const unsigned char KW_SIG[] = TGT_SIGNATURE;

static hckline_t    kw;
static hckline_cfg_t kw_cfg;
static unsigned char kw_on;           /* a KWP session owns the K-line */
static unsigned long kw_us;           /* microseconds, advanced by addition */
static unsigned int  kw_last_ms;

/* THE 5-BAUD DECODER RUNS IN THE 1 MS TICK (2026-10-14 evening, car).
   It sampled from the MAIN LOOP until then and threw the byte away when one
   pass exceeded 60 ms; its start bit had to be low on EVERY tick sample and
   three high main-loop samples aborted it. On the car (the K-line arrives
   through the instrument cluster) the ECU recognised NOTHING - 0 good and 0
   failed inits over two 5-baud attempts and a fast init - while the same
   image decodes the same sequence on the bench, clean or after garbled
   bursts. Now every millisecond is one sample, a bit is a majority vote over
   +-60 ms of its 200 ms, and the start bit needs 150 of its first 180 ms
   low: glitches and slow edges through the cluster cannot kill it, and the
   main loop's timing cannot either. What no 5-baud byte has - the ECU's OWN
   transmission (its echo held the line ~90 % low; bench, 2026-10-14) and a
   byte stream (a byte every millisecond) - is rejected explicitly. ISO
   9141's W5 (300 ms idle before the address) is the tester's obligation:
   20 ms of idle arms the decoder. */
#define FB_IDLE_MS      20u    /* line high this long before a start bit counts */
#define FB_START_MS     180u   /* the start bit is judged here ...              */
#define FB_START_LOW    150u   /* ... and needs this many low samples           */
#define FB_START_BYTES  24u    /* ... and at most this many received bytes      */
#define FB_WIN_MS       60u    /* majority window either side of a bit centre   */
static unsigned char fb_st;    /* 0 qualify idle, 1 armed, 2 start bit, 3 data
                                  and stop bits, 4 a byte is ready (main loop) */
static unsigned int  fb_hi_ms; /* consecutive high samples (the tick's)        */
static unsigned int  fb_t0;    /* ms since the falling edge of the start bit   */
static unsigned char fb_n, fb_hi, fb_i, fb_byte;

typedef char kl_fits[(sizeof(kl_t) <= TGT_RAM_KLINE_LIMIT) ? 1 : -1];
#define KL      HC_KL
#define KL_PV   0x80u
#define KL_PV_CLR  0x7Fu   /* byte mask: Keil truncates ~0x80u (C192) */
/* a fast-init wake-up: the tick measured a 20..30 ms low run (ISO 14230-2
   TiniL 25 +- 1 ms, margin for the 1 ms sample), finished at most KL_WUP_AGE_MS
   ago - the tester's StartCommunication follows its 25 ms high phase */
#define KL_WUP_MIN_MS   20u
#define KL_WUP_MAX_MS   30u
#define KL_WUP_AGE_MS   20u
/* GOFAST ON PROBATION (6.4): the new rate holds only if a CRC-valid request
   arrives at it within this time; otherwise the line goes back to 10400 -
   never assume 115200/124800 survive the cluster. */
#define KL_PROOF_MS     2000u
/* THE VEHICLE RATE IS PINNED (2026-10-15, car): once proven, the rate a
   vehicle entry negotiated stays held against the hunt - KL_PV is kept, not
   cleared - until the tester has sent no CRC-VALID request for KL_IDLE_MS (a
   host at another rate parses as garbage frames, never as valid ones; the KKL moved
   to the direct cable) or a new entry starts. On the car's shared line the
   cluster's traffic is framing errors and bad CRCs at any rate: three bursts
   moved a locked 115200 to 124800, and a locked 10400 - not a hunt rate -
   to 115200 for good. Every OBD session died that way every 20..40 s
   (linkState changes +3..5, failed inits 0).
   1.5 s, not 5 s (2026-10-20): a live tester sends a CRC-valid request
   every 100..200 ms (TunerStudio, the logger), and a Burn's deferred reply
   already blocks every rate move (hcts.c link_bad_seen). A tester that went
   silent longer - TunerStudio waiting 8 s for a reply lost on the line -
   comes back through the plugin's remembered path, which after an OBD
   session is the 5-baud / fast init entry: that works at whatever rate the
   ECU is on, so holding longer buys nothing, while 5 s stranded a host that
   reconnected directly at another rate (bench 783AE496: link qualify
   "GOFAST, host drops" / "never stranded", plugin lock_124800). */
#define KL_IDLE_MS      1500u
extern unsigned char hc_link_locked;      /* hcts.c: a CRC-valid frame here */

/* THE LOW RUN (fast init) AND THE 5-BAUD DECODER, once a millisecond from
   hc_tick_isr: `hi` = the RXD0 pin (P3.11), `rxp` = the low byte of DSTP6
   (a byte the UART received moves it).
   A low run ENDS AFTER THREE CONSECUTIVE HIGH SAMPLES - one or two glitches
   through the cluster do not split a 25 ms TiniL - and it is a break only
   with few bytes in it: a byte stream (the ECU's own 0x00-rich reply,
   echoed) moves DSTP6 every millisecond. The byte count lives in st's low
   7 bits (bit 7 is KL_PV): kl_t is full. The ECU's own transmission makes
   the run, and any 5-baud byte in progress, invalid. */
/* THE K-LINE CAPTURE (TGT_RAM_KLCAP, 256 bytes, C167 little-endian words):
     magic 'KC' 0x4B43, state 0 armed / 1 recording / 2 done, tick_ms of the
     trigger (the 3rd low ms), samples recorded, UART bytes received while
     recording, triggers since boot, link state at the trigger, spare;
   then KC_SAMPLES bits, 1 = line high, bit 0 of bits[0] first. */
typedef struct {
    unsigned int magic, st, t, n, bytes, trig, link;
    unsigned int good;              /* 1: a CRC-valid request since the last
                                       look (hctarget.h HCTS_TARGET_GOOD_FRAME,
                                       KL_IDLE_MS) - byte offset 14        */
    unsigned char bits[240];
} kc_t;
#define KC          (*(kc_t huge *)(TGT_EXTRAM_BASE + TGT_RAM_KLCAP))
#define KC_MAGIC    0x4B43u
#define KC_SAMPLES  1920u

#define KL_BREAK_BYTES  8u
#define KL_GLITCH_MS    3u     /* consecutive highs that end a low run */
void far hc_kl_tick(unsigned char hi, unsigned char rxp, unsigned int now)
{
    kl_t huge *k = &HC_KL;
    unsigned char moved = (unsigned char)(rxp != k->rxp);
    unsigned char own = (unsigned char)HC_TX_BUSY_NOW();
    unsigned int c;
    k->rxp = rxp;
    if (hi) {
        if (fb_hi_ms != 0xFFFFu) {
            fb_hi_ms++;
        }
    } else {
        fb_hi_ms = 0u;
    }
    if (own) {
        k->st |= KL_PV_CLR;                 /* this run is our own echo */
    }
    if (!hi) {
        if (k->lowcnt != 0xFFu) {
            k->lowcnt++;
        }
        if (moved && (k->st & KL_PV_CLR) != KL_PV_CLR) {
            k->st++;
        }
    } else if (fb_hi_ms >= KL_GLITCH_MS) {
        if (k->lowcnt != 0u) {
            k->run = (unsigned char)(((k->st & KL_PV_CLR) > KL_BREAK_BYTES)
                                     ? 0xFFu : k->lowcnt);
            k->run_t = (unsigned char)now;
            k->lowcnt = 0u;
        }
        k->st &= KL_PV;                     /* a new run: no bytes yet */
    }

    /* the K-line capture: one bit a millisecond once triggered */
    if (KC.st == 1u) {
        c = KC.n;
        if (c < KC_SAMPLES) {
            unsigned char m = (unsigned char)(1u << (c & 7u));
            if (hi) KC.bits[c >> 3] |= m;
            else    KC.bits[c >> 3] &= (unsigned char)~m;
            KC.n = c + 1u;
            KC.bytes += moved;
        } else {
            KC.st = 2u;
        }
    } else if (KC.st == 0u && k->lowcnt == 3u && !own) {
        KC.t = now;
        KC.n = 0u;
        KC.bytes = 0u;
        KC.trig++;
        KC.link = hcts_link_state();
        KC.st = 1u;
    }

    /* the 5-baud decoder */
    if (own && fb_st >= 1u && fb_st <= 3u) {
        fb_st = 0u;
        return;
    }
    switch (fb_st) {
    case 0u:
        if (fb_hi_ms >= FB_IDLE_MS) {
            fb_st = 1u;
        }
        break;
    case 1u:
        if (!hi) {
            fb_st = 2u;
            fb_t0 = 0u;
            fb_n = 1u;                      /* this sample is low */
            fb_hi = 0u;                     /* bytes received in the bit */
        }
        break;
    case 2u:
        fb_t0++;
        if (!hi) {
            fb_n++;
        }
        if (moved && fb_hi != 0xFFu) {
            fb_hi++;
        }
        if ((unsigned int)(fb_t0 + 1u - fb_n) > (FB_START_MS - FB_START_LOW)) {
            fb_st = 0u;                     /* too much high: not a start bit */
            break;
        }
        if (fb_t0 >= FB_START_MS - 1u) {
            if (fb_hi > FB_START_BYTES) {
                fb_st = 0u;                 /* a byte stream, not a break */
                break;
            }
            fb_st = 3u;
            fb_i = 0u; fb_n = 0u; fb_hi = 0u; fb_byte = 0u;
        }
        break;
    case 3u:
        fb_t0++;
        c = (unsigned int)(300u + 200u * (unsigned int)fb_i);   /* centre */
        if (fb_t0 + FB_WIN_MS >= c) {
            fb_n++;
            if (hi) {
                fb_hi++;
            }
        }
        if (fb_t0 >= c + FB_WIN_MS) {
            hi = (unsigned char)(fb_hi * 2u > fb_n);
            fb_n = 0u; fb_hi = 0u;
            if (fb_i < 8u) {
                if (hi) {
                    fb_byte |= (unsigned char)(1u << fb_i);
                }
                fb_i++;
            } else {
                fb_st = (unsigned char)(hi ? 4u : 0u);  /* stop bit */
            }
        }
        break;
    default:
        break;                              /* 4: the main loop takes it */
    }
}

static void fb_reset(void)
{
    fb_st = 0u;
    fb_hi_ms = 0u;
}

void far hc_kwp_init(void)
{
    hckline_default_cfg(&kw_cfg);
    kw_cfg.sig = KW_SIG;
    kw_cfg.sig_len = (unsigned char)(sizeof(KW_SIG) - 1u);
    hckline_init(&kw, &kw_cfg);
    kw_on = 0u;
    kw_us = 0uL;
    kw_last_ms = 0u;
    fb_reset();
    fb_t0 = 0u;
    fb_n = 0u; fb_hi = 0u; fb_i = 0u; fb_byte = 0u;
    KL.st = 0u; KL.lowcnt = 0u; KL.run = 0u; KL.asic_prep = 0u;
    /* the K-line capture re-arms at every boot (the owner keeps the key ON
       while moving the KKL from OBD to cavity 43, so it survives that) */
    KC.magic = KC_MAGIC;
    KC.st = 0u;
    KC.trig = 0u;
    KL.run_t = 0u; KL.rxp = 0u; KL.t_pv = 0u;
}

unsigned char far hc_kwp_active(void)
{
    /* the rate hunt is held while a 5-baud byte is decoded, a KWP session
       (or a fast-init window) owns the line, and while a GOFAST rate is on
       probation - noise must not move the rate the host was told to use */
    /* ... and while the line is HELD low (>= 3 ms, a break, not a byte at
       another rate): a 5-baud start bit or a TiniL must never move the rate */
    return (unsigned char)(kw_on || fb_st >= 3u || (KL.st & KL_PV)
                           || KL.lowcnt >= 3u);
}

unsigned char far hc_kwp_rx_take(unsigned char b)
{
    if (kw_on) {
        hckline_on_rx(&kw, b, kw_us);
        return 1u;
    }
    /* inside a qualified 5-baud byte the UART sees break garbage */
    return (unsigned char)(fb_st >= 3u);
}

/* The fast-init wake-up: a finished low run of 20..30 ms, fresh. Taken once.
   -> 1 when one ended just now (the caller opens the window). */
static unsigned char kl_wakeup(unsigned int ms)
{
    unsigned char r = KL.run;
    if (r == 0u) {
        return 0u;
    }
    KL.run = 0u;
    return (unsigned char)(r >= KL_WUP_MIN_MS && r <= KL_WUP_MAX_MS
                           && (unsigned char)((unsigned char)ms - KL.run_t)
                              <= KL_WUP_AGE_MS);
}

void far hc_kwp_service(unsigned int ms)
{
    unsigned int d = (unsigned int)(ms - kw_last_ms);
    unsigned char b, sent, code;

    if (d == 0u) {
        return;
    }
    kw_last_ms = ms;
    if (d > 50u) {
        d = 50u;                  /* a long stall: time moves, bounded work */
    }
    while (d--) {
        kw_us += 1000uL;
    }
    if (KL.st & KL_PV) {
        if (!hc_link_locked) {
            if ((unsigned int)(ms - KL.t_pv) >= KL_PROOF_MS) {
                /* back to 10400 and LOCKED (and pinned) there: the tester
                   that asked for a rate the line (the cluster) cannot carry
                   is still talking at 10400 - not one of the hunt's rates */
                hcts_link_force(0x77u, 1u);
                KL.t_pv = ms;
                KC.good = 0u;
            }
        } else if (KC.good) {
            KC.good = 0u;           /* the tester is still there */
            KL.t_pv = ms;
        } else if ((unsigned int)(ms - KL.t_pv) >= KL_IDLE_MS) {
            KL.st &= KL_PV_CLR;     /* gone: evidence may move the rate */
        }
    }
    if (!kw_on) {
        if (kl_wakeup(ms) && fb_st < 3u) {
            /* ISO 14230 FAST INIT: 10400 now - the tester's StartCommunication
               follows the 25 ms high phase - and the core's window opens */
            hcts_link_force(0x77u, 1u);
            hckline_on_fast_init(&kw, kw_us);
            kw_on = 1u;
            KL.st &= KL_PV_CLR;
            fb_reset();
            return;
        }
        if (fb_st == 4u) {
            /* a 5-baud byte from the tick's decoder (stop bit just ended) */
            b = fb_byte;
            fb_reset();
            hckline_on_slow_init(&kw, b, kw_us);
            if (kw.state == HCKLINE_ST_SYNC) {
                kw_on = 1u;
                hcts_link_force(0x77u, 1u);     /* 10400 = 1 248 000 / 120 */
            }
        }
        return;
    }
    hckline_tick(&kw, kw_us);
    sent = 0u;
    while (hckline_tx_pop(&kw, &b)) {
        hcts_tx(b);
        sent = 1u;
    }
    if (sent) {
        hcts_tx_end();
    }
    if (hckline_take_baud(&kw, &code)) {
        /* UNLOCKED: the rate is on probation until a CRC-valid request
           arrives at it (KL_PV below, 2026-10-13) */
        if (code == HCKLINE_BAUD_124800) {
            hcts_link_force(TGT_S0BG_ALT2, 0u);
        } else if (code == HCKLINE_BAUD_115200) {
            hcts_link_force(TGT_S0BG_ALT, 0u);  /* V96 */
        } else if (code == HCKLINE_BAUD_57600) {
            hcts_link_force(TGT_S0BG, 0u);
        } else {
            hcts_link_force(0x77u, 0u);         /* TunerStudio at 10400 */
        }
        hckline_enter_private(&kw);
        kw_on = 0u;
        fb_reset();
        /* ON PROBATION: unlocked (the first CRC-valid request locks it) and
           held against the hunt; no proof in KL_PROOF_MS -> 10400 */
        KL.st |= KL_PV;
        KL.t_pv = ms;
    } else if (kw.state == HCKLINE_ST_IDLE) {
        kw_on = 0u;                             /* failed / timed out */
        KL.st &= KL_PV_CLR;
        hcts_link_hunt();
        fb_reset();
    }
}

unsigned int far hc_kwp_state(void)
{
    return (unsigned int)(((unsigned int)(kw.init_ok & 0xFFu) << 8)
                          | ((unsigned int)(fb_st & 7u) << 4)
                          | (kw.state & 0x0Fu));
}

unsigned char far hc_kwp_drops(void)
{
    return (unsigned char)(kw.sess_drops & 0xFFu);
}

unsigned int far hc_kwp_counts(void)
{
    return (unsigned int)(((unsigned int)(kw.init_fail & 0xFFu) << 8)
                          | (kw.wrong_addr & 0xFFu));
}
