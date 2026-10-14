#include "hcfarbridge.h"
#include <reg167.h>
#include "hctarget.h"
#include "hcconfig.h"
#include "hctrigger.h"
#include "hcsched_dry.h"
#include "hcio711.h"
#include "hcrtmon711.h"

/* Cold profile arithmetic: retain full 32-bit quotient semantics without
   near Keil library calls from FCODE. Divisor nonzero at all call sites. */
static unsigned long profile_div(unsigned long n, unsigned long d)
{
    unsigned long q=0uL, r=0uL;
    unsigned char i;
    for (i=0; i<32u; i++) {
        unsigned char carry=(unsigned char)(r >> 31);
        r=(r << 1) | (n >> 31); n <<= 1; q <<= 1;
        if (carry || r >= d) { r -= d; q |= 1uL; }
    }
    return q;
}
static unsigned long profile_mul(unsigned long n, unsigned int m)
{
    unsigned long v=0uL;
    while(m) { if(m & 1u) v += n; m >>= 1; n <<= 1; }
    return v;
}
/* ======================================== V92: THE TOOTH PROFILE ==========
 * See hcsched_dry.h. Task context only: the samples are the teeth this
 * module already drains from the capture ring, so the crank ISR pays
 * nothing and a tooth pays one byte test while no profile is running. */
#define TL_BINS   60u
#define TLBUF     ((unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_TOOTHLOG))
#define tl_sum    ((unsigned long huge *)TLBUF)
#define tl_cnt    ((unsigned int huge *)(TLBUF + 4u * TL_BINS))
#define tl_prof   ((unsigned int huge *)(TLBUF + 6u * TL_BINS))
/* THE SEAL - a finished profile survives a reset. The V92 operator card
   said: run '!K' in TunerStudio, key OFF, start the logger; the key-off
   rebooted the ECU and hc_drysched_init() zeroed the profile before anything
   could read it. tl_finish() now
   seals it (magic, state, revs, teeth, additive checksum) behind the
   profile; init restores a valid seal and publishes it as DONE with
   HC_TL_RESTORED. A new request breaks the seal first. */
#define tl_seal   ((unsigned int huge *)(TLBUF + 8u * TL_BINS))
#define TL_MAGIC  0x544Bu              /* "TK" */
typedef char tl_seal_fits[(8u * 60u + 10u <= TGT_RAM_TOOTHLOG_LIMIT) ? 1 : -1];
#define TL_ARM_MS      30000u   /* compression: crank within 30 s        */
#define TL_RUN_REVS    64u      /* running profile length                */
#define TL_PUBLISH_MS  250u

unsigned char hc_tl_inhibit, hc_tl_active;
unsigned int hc_tl_state, hc_tl_revs, hc_tl_teeth;
static unsigned int tl_t0, tl_pub, tl_rev0;
static unsigned char tl_mode;

void HC_COLD hc_tl_add(unsigned int angle, unsigned int dt, unsigned int tooth)
{
    unsigned int tx = tooth ? tooth : 60u;
    unsigned int b = (unsigned int)((angle % 3600u) / tx);

    if (b >= TL_BINS) {
        return;
    }
    tl_sum[b] += (unsigned long)dt;
    if (tl_cnt[b] != 0xFFFFu) tl_cnt[b]++;
    if (hc_tl_teeth != 0xFFFFu) hc_tl_teeth++;
}

/* Per mille of the mean of the filled bins; 0 = no sample in that bin (the
   gap tooth and the missing teeth). */
static void tl_publish(void)
{
    unsigned char i;
    unsigned long tot = 0uL, m;
    unsigned int nb = 0u;

    for (i = 0u; i < TL_BINS; i++) {
        if (tl_cnt[i]) {
            tot += profile_div(tl_sum[i], tl_cnt[i]);
            nb++;
        }
    }
    for (i = 0u; i < TL_BINS; i++) {
        if (!tl_cnt[i] || !tot) {
            tl_prof[i] = 0u;
            continue;
        }
        m = profile_div(tl_sum[i], tl_cnt[i]);
        m = profile_div(profile_mul(profile_mul(m, 1000u), nb), tot);
        tl_prof[i] = (unsigned int)((m > 65535uL) ? 65535uL : m);
    }
}

static unsigned int tl_sum16(void)
{
    unsigned char i;
    unsigned int s = (unsigned int)(TL_MAGIC + tl_seal[1] + tl_seal[2]
                                    + tl_seal[3]);
    for (i = 0u; i < TL_BINS; i++) {
        s = (unsigned int)(s + tl_prof[i]);
    }
    return s;
}

static void tl_finish(unsigned int state)
{
    hc_tl_active = 0u;
    hc_tl_inhibit = 0u;
    tl_publish();
    hc_tl_state = (unsigned int)(state | ((unsigned int)tl_mode << 8));
    if (state == HC_TL_DONE) {
        tl_seal[1] = hc_tl_state;
        tl_seal[2] = hc_tl_revs;
        tl_seal[3] = hc_tl_teeth;
        tl_seal[4] = tl_sum16();
        tl_seal[0] = TL_MAGIC;           /* last: the seal is valid now */
    }
}

void HC_COLD hc_tl_request(unsigned char mode, unsigned int tick_ms)
{
    unsigned char i;

    if (mode == 0u) {
        if (hc_tl_active || hc_tl_inhibit) {
            tl_finish(HC_TL_ABORTED);
        }
        return;
    }
    if (mode > 2u) {
        return;
    }
    tl_mode = mode;
    /* The compression profile inhibits spark and fuel, so it may only be
       ARMED on a stopped engine: never withdraw them from a running one. */
    if (mode == 1u && (trg_rpm != 0u || trg_state >= TRG_SYNC_CRANK)) {
        hc_tl_active = 0u;
        hc_tl_inhibit = 0u;
        hc_tl_state = (unsigned int)(HC_TL_REFUSED | (1u << 8));
        return;
    }
    tl_seal[0] = 0u;       /* a test that STARTS breaks the old seal */
    for (i = 0u; i < TL_BINS; i++) {
        tl_sum[i] = 0uL; tl_cnt[i] = 0u; tl_prof[i] = 0u;
    }
    hc_tl_revs = 0u; hc_tl_teeth = 0u;
    tl_t0 = tick_ms; tl_pub = tick_ms; tl_rev0 = trg_rev;
    hc_tl_inhibit = (unsigned char)(mode == 1u);
    hc_tl_active = 1u;
    hc_tl_state = (unsigned int)(((mode == 1u) ? HC_TL_ARMED : HC_TL_RUN)
                                 | ((unsigned int)mode << 8));
}

void HC_COLD hc_tl_service(unsigned int tick_ms)
{
    unsigned int st = (unsigned int)(hc_tl_state & 0x00FFu);

    if (!hc_tl_active) {
        return;
    }
    if (trg_state >= TRG_SYNC_CRANK) {
        hc_tl_revs = (unsigned int)(trg_rev - tl_rev0);
    } else {
        tl_rev0 = (unsigned int)(trg_rev - hc_tl_revs);
    }
    if (st == HC_TL_ARMED) {
        if (trg_rpm != 0u) {
            hc_tl_state = (unsigned int)(HC_TL_RUN | (1u << 8));
        } else if ((unsigned int)(tick_ms - tl_t0) > TL_ARM_MS) {
            tl_finish(HC_TL_TIMEOUT);
        }
        return;
    }
    /* RUN: done when the crank stops (compression), or after the running
       revolutions; a live copy is published four times a second. */
    if (trg_rpm == 0u && hc_tl_teeth != 0u) {
        tl_finish(HC_TL_DONE);
        return;
    }
    if (tl_mode == 2u && hc_tl_revs >= TL_RUN_REVS) {
        tl_finish(HC_TL_DONE);
        return;
    }
    if ((unsigned int)(tick_ms - tl_pub) >= TL_PUBLISH_MS) {
        tl_pub = tick_ms;
        tl_publish();
    }
}

/* The extended output-channel window: the 344-byte live-Burn record, then
   the 60-word profile (big-endian, as every channel). */
unsigned char HC_COLD hc_och_ext_byte(unsigned int offset)
{
    unsigned int w;

    if (offset < 344u) {
        return hc_lf_export_byte(offset);
    }
    offset = (unsigned int)(offset - 344u);
    if (offset >= 2u * TL_BINS) {
        /* the boot history follows the profile (hcio711.c, far). */
        offset = (unsigned int)(offset - 2u * TL_BINS);
        /* the runtime health record follows the event ring. */
        if (offset >= TGT_BH_EXPORT_BYTES + TGT_EV_EXPORT_BYTES) {
            offset = (unsigned int)(offset - TGT_BH_EXPORT_BYTES
                                    - TGT_EV_EXPORT_BYTES);
            /* and the reset witness after it (hcrtmon711.c) */
            if (offset >= TGT_RT_EXPORT_BYTES) {
                return hc_rtwit_byte((unsigned int)(offset
                                                    - TGT_RT_EXPORT_BYTES));
            }
            return hc_rt_byte(offset);
        }
        return hc_io_boothist_byte(offset);
    }
    w = tl_prof[offset >> 1];
    return (unsigned char)(((offset & 1u) == 0u) ? (w >> 8) : w);
}


void HC_COLD hc_tl_init(void)
{
    unsigned int i;
    /* No TEST survives a reset (nothing stays inhibited). V93: a FINISHED
       profile does - a valid seal is published again as DONE | RESTORED. */
    hc_tl_inhibit = 0u; hc_tl_active = 0u; hc_tl_state = HC_TL_IDLE;
    hc_tl_revs = 0u; hc_tl_teeth = 0u; tl_mode = 0u;
    tl_t0 = 0u; tl_pub = 0u; tl_rev0 = 0u;
    if (tl_seal[0] == TL_MAGIC && tl_seal[4] == tl_sum16()
        && (tl_seal[1] & 0x00FFu) == HC_TL_DONE) {
        hc_tl_state = (unsigned int)(tl_seal[1] | HC_TL_RESTORED);
        hc_tl_revs = tl_seal[2];
        hc_tl_teeth = tl_seal[3];
    } else {
        tl_seal[0] = 0u;
        for (i = 0; i < TL_BINS; i++) tl_prof[i] = 0u;
    }
}
