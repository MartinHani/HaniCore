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
#define FB_IDLE_MS      300u   /* line high this long before a start bit counts */
#define FB_START_MS     180u   /* the start bit must stay low this long ...     */
#define FB_ABORT_HIGH   3u     /* ... and 3 high samples in it abort (UART bytes)*/
#define FB_WIN_MS       40u    /* majority window either side of a bit centre   */
#define FB_GAP_MS       60u    /* no sample this long inside a byte: unwatched  */
static unsigned char fb_st;    /* 0 qualify idle, 1 armed, 2 start bit, 3 bits,
                                  4 wait for the end of the stop bit           */
static unsigned int  fb_hi_ms;
static unsigned int  fb_t0;    /* ms of the falling edge */
static unsigned char fb_n, fb_hi, fb_i, fb_byte;

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
}

unsigned char far hc_kwp_active(void)
{
    return (unsigned char)(kw_on || fb_st >= 3u);
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
    if (!kw_on) {
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
        if (code == HCKLINE_BAUD_124800) {
            hcts_link_force(TGT_S0BG_ALT2, 1u);
        } else if (code == HCKLINE_BAUD_115200) {
            hcts_link_force(TGT_S0BG_ALT, 1u);  /* V96 */
        } else if (code == HCKLINE_BAUD_57600) {
            hcts_link_force(TGT_S0BG, 1u);
        } else {
            hcts_link_force(0x77u, 1u);         /* TunerStudio at 10400 */
        }
        hckline_enter_private(&kw);
        kw_on = 0u;
        fb_reset();
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
