/* hcserial711.c - ME7.1.1 K-line receive (PEC6) and interrupt-streamed
 * replies. FAR code. See hcserial711.h for why both exist. */
#include "hcfarbridge.h"      /* FIRST: FAR module reaching near code */
#include <reg167.h>
#include <intrins.h>
#include <stddef.h>
#include "hctarget.h"
#include "hcconfig.h"
#include "hcts.h"
#include "hc_config_manager.h"
#include "hcserial711.h"
#include "hcrtmon711.h"
#include "hcatomic.h"

extern volatile unsigned char hc_rx_ring[HC_RXRING];
extern volatile unsigned char hc_rx_head, hc_rx_tail;
extern volatile unsigned int hc_rx_ovf;
unsigned char hc_tlog_byte(unsigned int i);

/* ------------------------------------------------------- shared state -- *
 * NEAR, at a fixed address in the unallocated IRAM block between the
 * runtime health record and the user stack's guard band (linker_me711.lnp):
 * both the main loop and the two interrupt levels touch it, and a near
 * operand is one short instruction. 0xF2C0..0xF33F. */
typedef struct {
    unsigned int pec_rd;          /* next PEC-ring byte the tick takes      */
    unsigned int sent;            /* bytes loaded into S0TBUF (wraps)       */
    unsigned int eaten;           /* echo bytes the tick dropped            */
    unsigned int echo_t;          /* T7: last echo progress / job activity  */
    unsigned int off, n, i;
    unsigned long crc;
    unsigned char st, kind, code, hold, hold_ok, pad;
    unsigned char buf[HC_TX_BUF_N];
    unsigned int rx_t;            /* silent tick observations, saturates at 20 */
    unsigned char nxt, have;      /* the next reply byte, already computed     */
} hc_ser_t;
#define SER (*(hc_ser_t volatile *)0xF2C0u)
typedef char hc_ser_fits[(sizeof(hc_ser_t) <= 0x80u) ? 1 : -1];
typedef char hc_ser_gap_offset[(offsetof(hc_ser_t,pad)==23u)?1:-1];

#define ST_IDLE   0u
#define ST_LENHI  1u
#define ST_LENLO  2u
#define ST_CODE   3u
#define ST_DATA   4u
#define ST_CRC    5u              /* 5..8: the four CRC bytes               */
#define ST_LAST   9u              /* the final byte is loaded               */

/* ------------------------------------------------------------- CRC-32 --
   IEEE, reflected (zlib.crc32), a nibble at a time: 64 bytes of table and
   ~20 instructions a byte, against ~50 for the bit loop - this runs for
   every byte the ECU transmits. */
static const unsigned long crc_nib[16] = {
    0x00000000uL, 0x1DB71064uL, 0x3B6E20C8uL, 0x26D930ACuL,
    0x76DC4190uL, 0x6B6B51F4uL, 0x4DB26158uL, 0x5005713CuL,
    0xEDB88320uL, 0xF00F9344uL, 0xD6D6A3E8uL, 0xCB61B38CuL,
    0x9B64C2B0uL, 0x86D3D2D4uL, 0xA00AE278uL, 0xBDBDF21CuL
};

unsigned long far hc_crc32_update(unsigned long crc, unsigned char b)
{
    unsigned int n;
    crc ^= b;
    for(n=0u;n<2u;n++) crc=(crc>>4)^crc_nib[(unsigned char)crc&15u];
    return crc;
}

/* Main-loop service boundaries only. Calling from a yield inside page
   validation/copy/write work would let another request re-enter the parser
   or change DESIRED before the current operation has finished. */
void far hc_serial_boundary(void)
{
    /* Poll empty RX too: partial-frame abandonment must progress during silence. */
    if (!hc_tx_busy()) {
        unsigned int start = T7;
        hcts_poll();
        hcts_service();
        HC_RT_MAX(svc_comms, (unsigned int)(T7 - start));
    }
}

/* ============================================================ RECEIVE == */
#define PEC_BUF   TGT_PECRX_BUF
#define PEC_SIZE  TGT_PECRX_SIZE
#define PEC_HALF  (PEC_SIZE / 2u)
#define PEC_CARRY 8u              /* untaken bytes a restart moves down     */
#define PECC_BYTE_DSTINC 0x0300u  /* BWT byte, INC dst: C167CR UM 5.x, OEM */

/* Raise to level 15 for the four instructions that read and move the PEC
   pointer: a PEC6 transfer between them would be lost. SSC PEC (14/15) waits
   those few cycles; nothing else is held. */
#define PEC_LOCK(p)   do { (p) = PSW & 0xF000u; _bfld_(PSW, 0xF000u, 0xF000u); \
                           _nop_(); } while (0)
#define PEC_UNLOCK(p) do { PSW = (unsigned int)((PSW & 0x0FFFu) | (p)); } while (0)

void far hc_pecrx_arm(void)
{
    volatile unsigned char sink;
    S0RIC = 0u;
    sink = (unsigned char)S0RBUF;            /* a stale byte, if any    */
    S0CON = (unsigned int)(S0CON & ~0x0700u); /* sticky error flags      */
    SRCP6 = 0xFEB2u;                          /* S0RBUF, fixed source    */
    DSTP6 = PEC_BUF;
    PECC6 = (unsigned int)(PECC_BYTE_DSTINC | (PEC_SIZE - 2u));
    SER.pec_rd = PEC_BUF;
    SER.rx_t = 0u;
    SER.pad = 0u;
    SER.st = ST_IDLE;
    SER.sent = 0u;
    SER.eaten = 0u;
    SER.echo_t = T7;
    /* ILVL 15 GLVL 2 selects PEC channel 6 - the OEM's S0RIC 0x3E, enabled. */
    S0RIC = HC_IC(TGT_ILVL_SERIAL, TGT_GLVL_SERIAL);   /* 15 / 2 */
}

void far hc_pecrx_flush(void)
{
    unsigned int ps;
    PEC_LOCK(ps);
    SER.pec_rd = DSTP6;
    SER.pad = 0u;
    PEC_UNLOCK(ps);
}

/* The 1 ms tick: every byte PEC has stored goes into hcts.c's ring (as many
   as fit - the rest wait in the PEC ring), and once the pointer is past half
   the ring it is moved back to the start. At 115200 a millisecond is 11.5
   bytes, so the tick may be ~11 ms late before the count runs out; if it ever
   does, the boot block's S0RINT takes the bytes and pec_exhaust says so.

   THE K-LINE ECHO IS DROPPED HERE, not in the main loop: every
   byte we transmit comes back on the shared wire, and a 1652-byte reply is
   1652 echo bytes. While the main loop ate them, a long main-loop pass at
   high rpm let them fill hcts.c's ring, then the PEC ring, until the count ran
   out (simulator, 9600 rpm + TunerStudio 115200: pec_exhaust 97). The
   transport counts what it sent, so it knows how many bytes are owed back -
   half-duplex: nothing else arrives while a reply is owed. */
void far hc_pecrx_tick(void)
{
    unsigned int ps, d, rd;
    unsigned char h, cnt;

    PEC_LOCK(ps);
    d = DSTP6;
    cnt = (unsigned char)PECC6;
    PEC_UNLOCK(ps);
    if (cnt == 0u) {
        HC_RT_INC(pec_exhaust);
    }
    HC_RT_MAX(rx_hwm, (unsigned int)(d - SER.pec_rd));
    if(d != SER.pec_rd) {
        if(SER.rx_t >= 20u && !SER.pad) SER.pad=(unsigned char)(hc_rx_head|128u);
        SER.rx_t = 0u;
    } else if(SER.rx_t < 20u) SER.rx_t++;
    for (rd = SER.pec_rd; rd != d; rd++) {
        if ((unsigned int)(SER.sent - SER.eaten) != 0u) {
            SER.eaten++;                         /* our own echo */
            SER.echo_t = T7;
            continue;
        }
        h = (unsigned char)((hc_rx_head + 1u) & (HC_RXRING - 1u));
        if (h == hc_rx_tail) {
            break;                               /* the main loop is behind */
        }
        hc_rx_ring[hc_rx_head] = *(unsigned char volatile *)rd;
        hc_rx_head = h;
    }
    SER.pec_rd = rd;
    if ((unsigned int)(rd - PEC_BUF) >= PEC_HALF
        && (unsigned int)(d - rd) <= PEC_CARRY) {
        /* Past half: restart at the bottom, CARRYING the bytes that are not
           taken yet (normally none or one). Under the PEC lock (level 15) no
           transfer can land in between. this used to restart only
           if nothing at all had arrived since the tick read DSTP6 - during a
           115200 reply the echo streams without a gap, the restart lost that
           race tick after tick and the pointer walked to the end of the
           buffer: a byte to the boot block's S0RINT (simulator trace). */
        unsigned int k = 0u;
        PEC_LOCK(ps);
        for (d = DSTP6; rd != d && k < PEC_CARRY + 4u; rd++, k++) {
            *(unsigned char volatile *)(PEC_BUF + k) = *(unsigned char volatile *)rd;
        }
        DSTP6 = (unsigned int)(PEC_BUF + k);
        PECC6 = (unsigned int)(PECC_BYTE_DSTINC | (PEC_SIZE - 2u - k));
        SER.pec_rd = PEC_BUF;
        PEC_UNLOCK(ps);
    } else if (cnt != 0u && cnt < (unsigned char)(PEC_SIZE / 4u)) {
        /* Not empty and getting close to the end: top the count up so the
           PEC keeps the remaining buffer (it never passes PEC_BUF + SIZE-2). */
        PEC_LOCK(ps);
        d = DSTP6;
        PECC6 = (unsigned int)(PECC_BYTE_DSTINC
                               | (unsigned int)(PEC_BUF + PEC_SIZE - 2u - d));
        PEC_UNLOCK(ps);
    }
}

/* =========================================================== TRANSMIT == */
static unsigned char payload(unsigned int i)
{
    unsigned int o = (unsigned int)(SER.off + i);
    unsigned char b;
    switch (SER.kind) {
    case HC_TXK_OCH:
        if (o < (unsigned int)TGT_OCH_SIZE) {
            /* ONE CHANNEL, ONE INTERRUPT: the high byte and the low byte of an
               even-aligned 16-bit channel are read together, here, so the
               main loop's publication can never land between them. */
            if (SER.hold_ok) {
                SER.hold_ok = 0u;
                if(o&1u) return SER.hold;
            }
            b = OCH_BYTE(o);
            if (!(o & 1u) && (unsigned int)(o + 1u) < (unsigned int)TGT_OCH_SIZE) {
                SER.hold = OCH_BYTE((unsigned int)(o + 1u));
                SER.hold_ok = 1u;
            }
            return b;
        }
        return (unsigned char)HCTS_TARGET_OCH_EXT_READ(
            (unsigned int)(o - (unsigned int)TGT_OCH_SIZE));
    case HC_TXK_PAGE:
        return hc_cfg_mgr_peek_u8(o);
    case HC_TXK_TLOG:
        return hc_tlog_byte(o);
    default:
        return SER.buf[i];
    }
}

/* Compute the next job byte into SER.nxt (bounded payload/CRC work). It is
   written by emit() at the NEXT buffer-empty request, so after an engine
   interrupt has let the line run dry the wire restarts after one store, not
   after this computation. */
static void prep(void)
{
    unsigned char b;
    switch (SER.st) {
    case ST_LENHI:
        SER.st = ST_LENLO;
        b = (unsigned char)((SER.n + 1u) >> 8);
        break;
    case ST_LENLO:
        SER.st = ST_CODE;
        b = (unsigned char)(SER.n + 1u);
        break;
    case ST_CODE:
        SER.crc = hc_crc32_update(0xFFFFFFFFuL, SER.code);
        SER.st = SER.n ? ST_DATA : ST_CRC;
        if (!SER.n) SER.crc ^= 0xFFFFFFFFuL;
        b = SER.code;
        break;
    case ST_DATA:
        b = payload(SER.i);
        if (SER.kind != HC_TXK_PLAIN) {
            /* hc_crc32_update() inline: this runs for every reply byte
               (11 520/s at 115200) and the far call was a third of it. */
            unsigned long c = SER.crc ^ b;
            c = (c >> 4) ^ crc_nib[(unsigned char)c & 15u];
            c = (c >> 4) ^ crc_nib[(unsigned char)c & 15u];
            SER.crc = c;
        }
        if (++SER.i >= SER.n) {
            if (SER.kind == HC_TXK_PLAIN) {
                SER.st = ST_LAST;
            } else {
                SER.crc ^= 0xFFFFFFFFuL;
                SER.st = ST_CRC;
            }
        }
        break;
    default:                                 /* ST_CRC .. ST_CRC + 3 */
        b = (unsigned char)(SER.crc >> 24);
        SER.crc <<= 8;
        SER.st++;
        break;
    }
    SER.nxt = b;
}

/* Echo debt is published before the port command: a higher engine level can
   preempt the main-loop first byte until its echo has already arrived. */
static void emit(void)
{
    if (echo_seen) SER.sent++;
    HC_RT_INC(tx_bytes);
    S0TBUF = SER.nxt;
    /* ST_LAST: that was the job's final byte; nothing more to prepare. */
    SER.have = (unsigned char)(SER.st != ST_LAST);
    if (SER.have) prep();
}

/* Level TGT_ILVL_SERIAL_TX: the previous byte moved into the shift register,
   so the buffer takes the next one - a whole frame of slack before the line
   would go idle. Bounded: one byte per entry. */
/* The tick's register bank: the same ILVL (8), so the two never nest
   (32 bytes of IRAM). */
void hc_s0tb_isr(void) interrupt TGT_TRAP_S0TBINT using TICKBANK
{
    if (SER.st == ST_IDLE || !SER.have) {
        /* End-of-job activity, for the bounded no-echo forgiveness wait. */
        SER.echo_t = T7;
        S0TBIE = 0;
        SER.st = ST_IDLE;
        return;
    }
    emit();
}

/* Main loop. 0 if a job is still running (the caller waits for it - replies
   are half-duplex and never overlap). BUF/PLAIN copy src (<= HC_TX_BUF_N). */
unsigned char far hc_tx_start(unsigned char kind, unsigned char code,
                              unsigned int off, unsigned int n,
                              const unsigned char *src)
{
    unsigned int k;
    if (SER.st != ST_IDLE) return 0u;
    if (kind == HC_TXK_BUF || kind == HC_TXK_PLAIN) {
        if (n > HC_TX_BUF_N) n = HC_TX_BUF_N;
        for (k = 0u; k < n; k++) SER.buf[k] = src[k];
    }
    if (kind == HC_TXK_PAGE) {
        (void)hc_cfg_mgr_read_u8(0u);        /* finish the DESIRED seed copy */
    }
    if (kind == HC_TXK_PLAIN && n == 0u) return 1u;
    SER.kind = kind; SER.code = code; SER.off = off; SER.n = n; SER.i = 0u;
    SER.hold_ok = 0u;
    SER.st = (kind == HC_TXK_PLAIN) ? ST_DATA : ST_LENHI;
    /* Levels set, no request, not enabled while the first byte goes out and
       the second is prepared; then enable without touching the request the
       first byte's transfer has raised. */
    S0TBIC = (unsigned int)(HC_IC(TGT_ILVL_SERIAL_TX, TGT_GLVL_SERIAL_TX) & ~0x40u);
    prep();
    emit();
    S0TBIE = 1;
    return 1u;
}

unsigned char far hc_tx_busy(void)
{
    return (unsigned char)(SER.st != ST_IDLE);
}

unsigned int far hc_tx_sent(void)
{
    return SER.sent;
}

/* Echo accounting for hcts.c: `sent` is the TX interrupt's, `eaten` the
   tick's (both level TGT_ILVL_SERIAL_TX/TICK = 8, so they never preempt each
   other). The main loop only FORGIVES a debt that no echo will pay (wiring
   without echo) - under the critical level, so it cannot land inside the
   tick's increment. */
unsigned int far hc_tx_echo_owed(void)
{
    return (unsigned int)(SER.sent - SER.eaten);
}

void far hc_tx_echo_ate(unsigned char all)
{
    unsigned int ps;
    HC_ATOMIC_ENTER(ps);
    if (all) SER.eaten = SER.sent;
    else SER.eaten++;
    SER.echo_t = T7;
    HC_ATOMIC_EXIT(ps);
}

unsigned int far hc_tx_echo_age(void)
{
    return (unsigned int)(T7 - SER.echo_t);
}
