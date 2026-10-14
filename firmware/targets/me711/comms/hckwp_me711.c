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

/* The IDENTIFY payload is the TunerStudio signature, so a tool that enters
   through the vehicle K-line learns the page layout (and the .ini it needs)
   before it switches rate. */
static const unsigned char KW_SIG[] = TGT_SIGNATURE;

static hckline_t    kw;
static hckline_cfg_t kw_cfg;
static unsigned char kw_on;           /* a KWP session owns the K-line */
static unsigned long kw_us;           /* microseconds, advanced by addition */
static unsigned int  kw_last_ms;

/* 5-baud decoder */
/* ARMING IDLE 20 ms, NOT 300 (2026-10-13, ME711_OBD_KLINE.md 6.3): on the
   car's shared K-line the cluster's own traffic seldom leaves 300 ms of idle,
   so the decoder never armed. ISO 9141's W5 (300 ms idle before the address)
   is the TESTER's obligation; what qualifies a 5-baud byte here is the 180 ms
   start bit with < 3 high samples, the 8 voted data bits and the stop bit -
   which no UART byte can imitate. */
#define FB_IDLE_MS      20u    /* line high this long before a start bit counts */
#define FB_START_MS     180u   /* the start bit must stay low this long ...     */
#define FB_ABORT_HIGH   3u     /* ... and 3 high samples in it abort (UART bytes)*/
#define FB_WIN_MS       40u    /* majority window either side of a bit centre   */
#define FB_GAP_MS       60u    /* no sample this long inside a byte: unwatched  */
/* THE START BIT IS QUALIFIED BY THE 1 MS TICK TOO (2026-10-14): the pin must
   have been low on every tick sample (HC_KL.lowcnt) for this long. With the
   20 ms arming, the main loop's sparse samples took the ECU's OWN output-
   channel reply - mostly 0x00 bytes, the line ~90 % low - for a start bit
   (bench: 10 false inits in a 30 s 57600 soak, TunerStudio requests eaten).
   No UART byte at any rate holds the line low through 160 consecutive 1 ms
   samples - every byte's stop bit is high. */
#define FB_START_TICKS  160u
static unsigned char fb_st;    /* 0 qualify idle, 1 armed, 2 start bit, 3 bits,
                                  4 wait for the end of the stop bit           */
static unsigned int  fb_hi_ms;
static unsigned int  fb_t0;    /* ms of the falling edge */
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
extern unsigned char hc_link_locked;      /* hcts.c: a CRC-valid frame here */

/* A LOW RUN ENDS AT A HIGH SAMPLE OR AT A RECEIVED BYTE (2026-10-14): one
   sample a ms cannot see a stop bit, and the ECU's OWN reply - echoed onto
   RXD0, an output-channel block full of 0x00 bytes - kept the line low on
   every sample for 20..30 ms: a fast-init wake-up mid-session, the rate
   forced to 10400 (bench: the 57600 soak went silent). A real break
   (TiniL, a 5-baud bit) delivers at most one framing-error byte at its
   start; a byte stream moves DSTP6 every ms. */
void far hc_kl_tick(unsigned char hi, unsigned char rxp, unsigned int now)
{
    kl_t huge *k = &HC_KL;
    unsigned char moved = (unsigned char)(rxp != k->rxp);
    k->rxp = rxp;
    if (hi || moved) {
        if (k->lowcnt != 0u) {
            k->run = k->lowcnt;
            k->run_t = (unsigned char)now;
            k->lowcnt = 0u;
        }
    } else if (k->lowcnt != 0xFFu) {
        k->lowcnt++;
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
    KL.run_t = 0u; KL.rxp = 0u; KL.t_pv = 0u;
}

unsigned char far hc_kwp_active(void)
{
    /* the rate hunt is held while a 5-baud byte is decoded, a KWP session
       (or a fast-init window) owns the line, and while a GOFAST rate is on
       probation - noise must not move the rate the host was told to use */
    return (unsigned char)(kw_on || fb_st >= 3u || (KL.st & KL_PV));
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

/* the 5-baud decoder, once per main-loop pass that saw the tick move: `d`
   milliseconds have passed since the last sample (a pass can be several ms
   long - timing is ALWAYS absolute ms, never a sample count) */
static void fb_ms(unsigned int ms, unsigned char hi, unsigned int d)
{
    unsigned int e = (unsigned int)(ms - fb_t0);
    unsigned int c;

    /* A START BIT OR A DATA BIT MUST BE WATCHED, NOT INFERRED FROM THE
       CLOCK. While the ECU transmits a TunerStudio reply the main loop - and
       this sampler - does not run; a 950-byte output-channel reply is ~190
       ms. A request's own low bits could arm state 2, the reply then
       "qualified" a start bit nobody had seen (e >= 180 ms at the first
       sample after it), hc_kwp_rx_take() swallowed the host's NEXT request
       as 5-baud break garbage, and the decoder later counted a foreign
       5-baud address. Bench, 2026-09-29, V97 dev: 8 of 20 requests after a
       950-byte read lost, kwpCounts +8; the V96 872-byte reply stayed under
       180 ms. A pass is 20-30 ms at worst, so a sampling gap beyond
       FB_GAP_MS means the line was not watched: start over - also before a
       byte, where an unwatched gap (our own transmission) must not count
       as the 300 ms of idle that arms the decoder. */
    if (fb_st <= 3u && d > FB_GAP_MS) {
        fb_reset();
        return;
    }

    switch (fb_st) {
    case 0u:
        if (hi) {
            fb_hi_ms = (unsigned int)(fb_hi_ms + d);
            if (fb_hi_ms >= FB_IDLE_MS) {
                fb_st = 1u;
            }
        } else {
            fb_hi_ms = 0u;
        }
        break;
    case 1u:
        if (!hi) {
            fb_st = 2u;
            fb_t0 = ms;
            fb_hi = 0u;
        }
        break;
    case 2u:
        /* THE START BIT QUALIFIES BY TIME, NOT BY A SAMPLE LANDING IN A
           WINDOW: a main-loop pass can be 20-30 ms long, and the first
           version waited for a sample between 180 and 200 ms - missing it
           turned the next (high) data bit into the "UART byte" abort. */
        if (e < FB_START_MS) {
            if (hi && ++fb_hi >= FB_ABORT_HIGH) {
                fb_reset();                     /* a UART byte, not 5 baud */
            }
            break;
        }
        if (HC_KL.lowcnt < FB_START_TICKS) {
            fb_reset();                 /* a tick saw it high: not a start bit */
            break;
        }
        fb_st = 3u;
        fb_i = 0u; fb_n = 0u; fb_hi = 0u; fb_byte = 0u;
        /* this sample already belongs to the data bits */
        /* fall through */
    case 3u:
        for (;;) {                  /* at most 9 passes: each decides a bit */
            unsigned char lvl;

            c = (unsigned int)(300u + 200u * (unsigned int)fb_i);  /* centre */
            if (e + FB_WIN_MS < c) {
                break;                          /* before this bit's window */
            }
            if (e <= c + FB_WIN_MS) {
                fb_n++;                         /* inside it: vote */
                if (hi) {
                    fb_hi++;
                }
                break;
            }
            if (fb_n != 0u) {
                lvl = (unsigned char)(fb_hi * 2u > fb_n);
            } else if (e < c + 100u) {
                lvl = hi;                       /* no vote, still in the bit */
            } else {
                fb_reset();                     /* a whole bit unseen: no guess */
                break;
            }
            if (fb_i < 8u) {
                if (lvl) {
                    fb_byte |= (unsigned char)(1u << fb_i);
                }
                fb_i++;
                fb_n = 0u; fb_hi = 0u;
                continue;
            }
            if (lvl) {
                fb_st = 4u;                     /* stop bit good */
            } else {
                fb_reset();                     /* framing: not a 5-baud byte */
            }
            break;
        }
        break;
    case 4u:
        if (e >= 2000u) {                       /* the end of the stop bit */
            hckline_on_slow_init(&kw, fb_byte, kw_us);
            if (kw.state == HCKLINE_ST_SYNC) {
                kw_on = 1u;
                hcts_link_force(0x77u, 1u);     /* 10400 = 1 248 000 / 120 */
            }
            fb_reset();
        }
        break;
    default:
        fb_reset();
        break;
    }
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

void far hc_kwp_service(unsigned int ms, unsigned char rxd_high)
{
    unsigned int d = (unsigned int)(ms - kw_last_ms);
    unsigned int gap;
    unsigned char b, sent, code;

    if (d == 0u) {
        return;
    }
    kw_last_ms = ms;
    gap = d;                      /* the raw sampling gap, for fb_ms() */
    if (d > 50u) {
        d = 50u;                  /* a long stall: time moves, bounded work */
    }
    while (d--) {
        kw_us += 1000uL;
    }
    if (KL.st & KL_PV) {
        if (hc_link_locked) {
            KL.st &= KL_PV_CLR;     /* proven: the rate holds */
        } else if ((unsigned int)(ms - KL.t_pv) >= KL_PROOF_MS) {
            KL.st &= KL_PV_CLR;
            hcts_link_force(0x77u, 0u);         /* back to 10400 */
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
        fb_ms(ms, rxd_high, gap);
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
