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
#if !TGT_BOARD_VAG_ME71_C4
    unsigned char buf[HC_TX_BUF_N];
#endif
    unsigned int rx_t;            /* silent tick observations, saturates at 20 */
    unsigned char nxt, have;      /* the next reply byte, already computed     */
} hc_ser_t;
#if !TGT_BOARD_VAG_ME71_C4
#define SER (*(hc_ser_t volatile *)0xF2C0u)
#define SER_BUF(k) (SER.buf[k])
#else
/* THE 2.7T's C167CR has no RAM at 0xF2C0 (hcsafety.h). The shared fields
   stay NEAR - XRAM 0xE580, kept out of every linker class - because the
   main loop and two interrupt levels update them with one instruction each:
   as a FAR object (2026-10-26, bench) the read-modify-writes split and the
   reply stream died mid-frame. Only the transmit buffer is far (external
   SRAM): the main loop fills it while the job is idle, the interrupt reads
   one byte at a time. */
#define SER (*(hc_ser_t volatile *)0xE580u)
#define SER_BUF(k) (((unsigned char volatile far *)                      (TGT_EXTRAM_BASE + TGT_RAM_C4SER))[k])
typedef char hc_ser_fits_c4[(sizeof(hc_ser_t) <= 0x20u) ? 1 : -1];
#endif
typedef char hc_ser_fits[(sizeof(hc_ser_t) <= 0x80u) ? 1 : -1];
typedef char hc_ser_gap_offset[(offsetof(hc_ser_t,pad)==23u)?1:-1];
typedef char hc_ser_st_offset[(offsetof(hc_ser_t,st)==18u)?1:-1];  /* HC_TX_BUSY_NOW */
#if TGT_TX_PEC
/* the PEC5 reply buffer and its state (see "REPLIES THROUGH PEC5" below):
   PEC reaches segment 0 only, so they are on-chip XRAM - defined in hcts.c,
   which is compiled RENAMECLASS(NDATA0=XNDATA0); this module's own near data
   is the IRAM class, which has no room. */
extern unsigned char volatile hc_txp_buf[];
extern unsigned char volatile hc_txp_pk[2];
extern unsigned char volatile hc_txp_cur, hc_txp_on, hc_txp_run, hc_txp_fin,
                              hc_txp_drained, hc_txp_filling;
extern unsigned int volatile hc_txp_fin_t;
static void tx_fill_tick(void);
#endif

#define ST_IDLE   0u
#define ST_LENHI  1u
#define ST_LENLO  2u
#define ST_CODE   3u
#define ST_DATA   4u
#define ST_CRC    5u              /* 5..8: the four CRC bytes               */
#define ST_LAST   9u              /* the final byte is loaded               */

/* ------------------------------------------------------------- CRC-32 --
   IEEE, reflected (zlib.crc32), a BYTE at a time (2026-11-04): one 32-bit
   shift and one table load per byte, against two shift-by-4 steps and two
   loads with the 16-entry nibble table - this runs in the transmit path for
   every byte the ECU sends (issue 05, candidate B). 1 KB of HCONST.
   Generated and checked against zlib.crc32 (tests/host/test_crc32_table.py). */
static const unsigned long crc_tab[256] = {
    0x00000000uL, 0x77073096uL, 0xEE0E612CuL, 0x990951BAuL,
    0x076DC419uL, 0x706AF48FuL, 0xE963A535uL, 0x9E6495A3uL,
    0x0EDB8832uL, 0x79DCB8A4uL, 0xE0D5E91EuL, 0x97D2D988uL,
    0x09B64C2BuL, 0x7EB17CBDuL, 0xE7B82D07uL, 0x90BF1D91uL,
    0x1DB71064uL, 0x6AB020F2uL, 0xF3B97148uL, 0x84BE41DEuL,
    0x1ADAD47DuL, 0x6DDDE4EBuL, 0xF4D4B551uL, 0x83D385C7uL,
    0x136C9856uL, 0x646BA8C0uL, 0xFD62F97AuL, 0x8A65C9ECuL,
    0x14015C4FuL, 0x63066CD9uL, 0xFA0F3D63uL, 0x8D080DF5uL,
    0x3B6E20C8uL, 0x4C69105EuL, 0xD56041E4uL, 0xA2677172uL,
    0x3C03E4D1uL, 0x4B04D447uL, 0xD20D85FDuL, 0xA50AB56BuL,
    0x35B5A8FAuL, 0x42B2986CuL, 0xDBBBC9D6uL, 0xACBCF940uL,
    0x32D86CE3uL, 0x45DF5C75uL, 0xDCD60DCFuL, 0xABD13D59uL,
    0x26D930ACuL, 0x51DE003AuL, 0xC8D75180uL, 0xBFD06116uL,
    0x21B4F4B5uL, 0x56B3C423uL, 0xCFBA9599uL, 0xB8BDA50FuL,
    0x2802B89EuL, 0x5F058808uL, 0xC60CD9B2uL, 0xB10BE924uL,
    0x2F6F7C87uL, 0x58684C11uL, 0xC1611DABuL, 0xB6662D3DuL,
    0x76DC4190uL, 0x01DB7106uL, 0x98D220BCuL, 0xEFD5102AuL,
    0x71B18589uL, 0x06B6B51FuL, 0x9FBFE4A5uL, 0xE8B8D433uL,
    0x7807C9A2uL, 0x0F00F934uL, 0x9609A88EuL, 0xE10E9818uL,
    0x7F6A0DBBuL, 0x086D3D2DuL, 0x91646C97uL, 0xE6635C01uL,
    0x6B6B51F4uL, 0x1C6C6162uL, 0x856530D8uL, 0xF262004EuL,
    0x6C0695EDuL, 0x1B01A57BuL, 0x8208F4C1uL, 0xF50FC457uL,
    0x65B0D9C6uL, 0x12B7E950uL, 0x8BBEB8EAuL, 0xFCB9887CuL,
    0x62DD1DDFuL, 0x15DA2D49uL, 0x8CD37CF3uL, 0xFBD44C65uL,
    0x4DB26158uL, 0x3AB551CEuL, 0xA3BC0074uL, 0xD4BB30E2uL,
    0x4ADFA541uL, 0x3DD895D7uL, 0xA4D1C46DuL, 0xD3D6F4FBuL,
    0x4369E96AuL, 0x346ED9FCuL, 0xAD678846uL, 0xDA60B8D0uL,
    0x44042D73uL, 0x33031DE5uL, 0xAA0A4C5FuL, 0xDD0D7CC9uL,
    0x5005713CuL, 0x270241AAuL, 0xBE0B1010uL, 0xC90C2086uL,
    0x5768B525uL, 0x206F85B3uL, 0xB966D409uL, 0xCE61E49FuL,
    0x5EDEF90EuL, 0x29D9C998uL, 0xB0D09822uL, 0xC7D7A8B4uL,
    0x59B33D17uL, 0x2EB40D81uL, 0xB7BD5C3BuL, 0xC0BA6CADuL,
    0xEDB88320uL, 0x9ABFB3B6uL, 0x03B6E20CuL, 0x74B1D29AuL,
    0xEAD54739uL, 0x9DD277AFuL, 0x04DB2615uL, 0x73DC1683uL,
    0xE3630B12uL, 0x94643B84uL, 0x0D6D6A3EuL, 0x7A6A5AA8uL,
    0xE40ECF0BuL, 0x9309FF9DuL, 0x0A00AE27uL, 0x7D079EB1uL,
    0xF00F9344uL, 0x8708A3D2uL, 0x1E01F268uL, 0x6906C2FEuL,
    0xF762575DuL, 0x806567CBuL, 0x196C3671uL, 0x6E6B06E7uL,
    0xFED41B76uL, 0x89D32BE0uL, 0x10DA7A5AuL, 0x67DD4ACCuL,
    0xF9B9DF6FuL, 0x8EBEEFF9uL, 0x17B7BE43uL, 0x60B08ED5uL,
    0xD6D6A3E8uL, 0xA1D1937EuL, 0x38D8C2C4uL, 0x4FDFF252uL,
    0xD1BB67F1uL, 0xA6BC5767uL, 0x3FB506DDuL, 0x48B2364BuL,
    0xD80D2BDAuL, 0xAF0A1B4CuL, 0x36034AF6uL, 0x41047A60uL,
    0xDF60EFC3uL, 0xA867DF55uL, 0x316E8EEFuL, 0x4669BE79uL,
    0xCB61B38CuL, 0xBC66831AuL, 0x256FD2A0uL, 0x5268E236uL,
    0xCC0C7795uL, 0xBB0B4703uL, 0x220216B9uL, 0x5505262FuL,
    0xC5BA3BBEuL, 0xB2BD0B28uL, 0x2BB45A92uL, 0x5CB36A04uL,
    0xC2D7FFA7uL, 0xB5D0CF31uL, 0x2CD99E8BuL, 0x5BDEAE1DuL,
    0x9B64C2B0uL, 0xEC63F226uL, 0x756AA39CuL, 0x026D930AuL,
    0x9C0906A9uL, 0xEB0E363FuL, 0x72076785uL, 0x05005713uL,
    0x95BF4A82uL, 0xE2B87A14uL, 0x7BB12BAEuL, 0x0CB61B38uL,
    0x92D28E9BuL, 0xE5D5BE0DuL, 0x7CDCEFB7uL, 0x0BDBDF21uL,
    0x86D3D2D4uL, 0xF1D4E242uL, 0x68DDB3F8uL, 0x1FDA836EuL,
    0x81BE16CDuL, 0xF6B9265BuL, 0x6FB077E1uL, 0x18B74777uL,
    0x88085AE6uL, 0xFF0F6A70uL, 0x66063BCAuL, 0x11010B5CuL,
    0x8F659EFFuL, 0xF862AE69uL, 0x616BFFD3uL, 0x166CCF45uL,
    0xA00AE278uL, 0xD70DD2EEuL, 0x4E048354uL, 0x3903B3C2uL,
    0xA7672661uL, 0xD06016F7uL, 0x4969474DuL, 0x3E6E77DBuL,
    0xAED16A4AuL, 0xD9D65ADCuL, 0x40DF0B66uL, 0x37D83BF0uL,
    0xA9BCAE53uL, 0xDEBB9EC5uL, 0x47B2CF7FuL, 0x30B5FFE9uL,
    0xBDBDF21CuL, 0xCABAC28AuL, 0x53B39330uL, 0x24B4A3A6uL,
    0xBAD03605uL, 0xCDD70693uL, 0x54DE5729uL, 0x23D967BFuL,
    0xB3667A2EuL, 0xC4614AB8uL, 0x5D681B02uL, 0x2A6F2B94uL,
    0xB40BBE37uL, 0xC30C8EA1uL, 0x5A05DF1BuL, 0x2D02EF8DuL
};

unsigned long far hc_crc32_update(unsigned long crc, unsigned char b)
{
    return (crc >> 8) ^ crc_tab[(unsigned char)((unsigned char)crc ^ b)];
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
#if TGT_TX_PEC
    hc_txp_on = 0u; hc_txp_run = 0u; hc_txp_fin = 0u; hc_txp_drained = 0u; hc_txp_filling = 0u;
    hc_txp_pk[0] = 0u; hc_txp_pk[1] = 0u; hc_txp_cur = 0u;
#endif
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
    unsigned int ps, d, rd, ate;
    unsigned char h, cnt;

    PEC_LOCK(ps);
    d = DSTP6;
    cnt = (unsigned char)PECC6;
    PEC_UNLOCK(ps);
    if (cnt == 0u) {
        HC_RT_INC(pec_exhaust);
    }
    HC_RT_MAX(rx_hwm, (unsigned int)(d - SER.pec_rd));
    /* AN ECHO NOBODY WILL PAY IS FORGIVEN HERE (2026-11-06), 5 ms after the
       job ended - not by the main loop: on the 018DC a pass is 24..41 ms, and
       until the loop forgave it every byte the tester sent was eaten as our
       echo (its next request lost). Same level as the transmit interrupt. */
    if ((unsigned int)(SER.sent - SER.eaten) != 0u && SER.st == ST_IDLE
        && (unsigned int)(T7 - SER.echo_t) > (unsigned int)US_TO_TICKS(5000u)) {
        SER.eaten = SER.sent;
        HC_KLSTAT_INC(3);
    }
    if (SER.st != ST_IDLE) {
        HC_KLSTAT_INC(6);
        if (HC_KLSTAT(6) > HC_KLSTAT(4)) HC_KLSTAT(4) = HC_KLSTAT(6);
    } else {
        HC_KLSTAT(6) = 0u;
    }
    if(d != SER.pec_rd) {
        if(SER.rx_t >= 20u && !SER.pad) SER.pad=(unsigned char)(hc_rx_head|128u);
        SER.rx_t = 0u;
    } else if(SER.rx_t < 20u) SER.rx_t++;
    ate = 0u;
    for (rd = SER.pec_rd; rd != d; rd++) {
        if ((unsigned int)(SER.sent - SER.eaten) != 0u) {
            SER.eaten++;                         /* our own echo */
            SER.echo_t = T7;
            ate++;
            continue;
        }
        h = (unsigned char)((hc_rx_head + 1u) & (HC_RXRING - 1u));
        if (h == hc_rx_tail) {
            break;                               /* the main loop is behind */
        }
        hc_rx_ring[hc_rx_head] = *(unsigned char volatile *)rd;
        hc_rx_head = h;
    }
    /* the receive accounts: once per tick, not per byte - a far SRAM
       read-modify-write per echo byte held this level (the transmit
       interrupt's) long enough to open gaps in a 124800 reply */
    if (rd != SER.pec_rd) {
        HC_KLSTAT(0) += (unsigned int)(rd - SER.pec_rd);
        HC_KLSTAT(1) += ate;
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
#if TGT_TX_PEC
    tx_fill_tick();
#endif
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
        return SER_BUF(i);
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
            SER.crc = (SER.crc >> 8)
                      ^ crc_tab[(unsigned char)((unsigned char)SER.crc ^ b)];
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
#if !TGT_TX_PEC
static void emit(void)
{
    if (echo_seen) SER.sent++;
    HC_RT_INC(tx_bytes);
    S0TBUF = SER.nxt;
    /* ST_LAST: that was the job's final byte; nothing more to prepare. */
    SER.have = (unsigned char)(SER.st != ST_LAST);
    if (SER.have) prep();
}
#endif

#if TGT_TX_PEC
/* REPLIES THROUGH PEC5 (2026-11-06, M0 on the 018DC). One transmit interrupt
   per byte cost ~36 us of CPU a reply byte (with the echo): LibreTune's polling
   at 124800 took ~17 % of the CPU and the main loop's pass went from 26 to
   46 ms at 3000 rpm (the maintainer's records).
   Now the reply is generated 32 bytes at a time into one half of buf (the
   1 ms tick, level 8, ~15 instructions a byte) and PEC5 moves it to S0TBUF on
   each buffer-empty request with no CPU; S0TBIC is ILVL 15 GLVL 1 = PEC5
   (C167CR UM 5.x; 0/4 are the SSC, 6 the K-line receive). When a half's COUNT
   goes 1 -> 0 the request stays set and the interrupt below runs: it switches
   to the other half, or stops (drained) until the tick has filled it, or - the
   last byte in S0TBUF - waits for one more request, which ends the job as the
   per-byte interrupt did (the job is idle once its last byte has moved on).
   The echo debt is published per half before its bytes go out. Long replies
   and BUF/PLAIN jobs (their source is buf itself) keep the per-byte path. */
#define TX_HALF            16u
#define PECC_BYTE_SRCINC   0x0500u   /* BWT byte, INC source: C167CR UM 5.x */
/* PEC pointers are PHYSICAL segment-0 addresses; a near pointer carries the
   DPP selector in bits 15..14 (0xA24E = DPP2:0x224E). The XRAM is in page 3. */
#define TXP_PHYS(p)        ((unsigned int)(0xC000u | ((unsigned int)(p) & 0x3FFFu)))

static unsigned char tx_gen(unsigned char h)
{
    unsigned char k = 0u;
    unsigned int o = h ? TX_HALF : 0u;
    while (k < TX_HALF && SER.have) {
        hc_txp_buf[o + k] = SER.nxt;
        k++;
        SER.have = (unsigned char)(SER.st != ST_LAST);
        if (SER.have) prep();
    }
    return k;
}

/* also inlined in the level-15 interrupt (TX_ARM): a call there would save
   every register on the system stack */
static void tx_arm(unsigned char h)
{
    unsigned char k = hc_txp_pk[h];
    unsigned int t = HC_RT.tx_bytes;
    hc_txp_cur = h;
    SRCP5 = TXP_PHYS(&hc_txp_buf[h ? TX_HALF : 0u]);   /* on-chip XRAM, segment 0 */
    DSTP5 = 0xFEB0u;                              /* S0TBUF */
    PECC5 = (unsigned int)(PECC_BYTE_SRCINC | k);
    if (echo_seen) SER.sent += k;
    HC_RT.tx_bytes = (unsigned int)((t > (unsigned int)(0xFFFFu - k)) ? 0xFFFFu : (t + k));
}

/* PEC5 STOPPED (no half was ready): restart on the filled half, two byte
   times after the stop - S0TBUF is empty then, and its buffer-empty request
   may have been used up by the stop itself, so the request is set by
   software (as at the start of a job). S0TBIE is 0 meanwhile: no race. */
static void tx_restart(void)
{
    unsigned char h = (unsigned char)(hc_txp_cur ^ 1u);
    if (!hc_txp_drained || hc_txp_pk[h] == 0u) return;
    if ((unsigned int)(T7 - hc_txp_fin_t) <= (unsigned int)US_TO_TICKS(2000u)) return;
    hc_txp_drained = 0u;
    tx_arm(h);
    S0TBIC = (unsigned int)(HC_IC(TGT_ILVL_SERIAL_TXPEC, TGT_GLVL_SERIAL_TXPEC) | 0x0080u);
}

/* the tick (level 8): the free half, if the job has more bytes */
static void tx_fill_tick(void)
{
    unsigned char h, k;
    if (hc_txp_fin) {
        if ((unsigned int)(T7 - hc_txp_fin_t) > (unsigned int)US_TO_TICKS(2000u)) {
            hc_txp_fin = 0u; hc_txp_run = 0u; hc_txp_on = 0u;
            SER.echo_t = T7;
            SER.st = ST_IDLE;          /* the job ends; S0TBIE is already 0 */
        }
        return;
    }
    if (hc_txp_drained && hc_txp_pk[hc_txp_cur ^ 1u] != 0u) {
        tx_restart();
        return;
    }
    if (!hc_txp_run || !SER.have) return;
    h = (unsigned char)(hc_txp_cur ^ 1u);
    if (hc_txp_pk[h] != 0u) return;
    hc_txp_filling = 1u;
    k = tx_gen(h);
    hc_txp_pk[h] = k;
    hc_txp_filling = 0u;
    tx_restart();
}
#endif

/* Level TGT_ILVL_SERIAL_TX: the previous byte moved into the shift register,
   so the buffer takes the next one - a whole frame of slack before the line
   would go idle. Bounded: one byte per entry. */
/* The tick's register bank: the same ILVL (8), so the two never nest
   (32 bytes of IRAM). */
#if TGT_TX_PEC
/* no register bank: in a PEC job this runs at level 15, above the tick that
   owns TICKBANK */
void hc_s0tb_isr(void) interrupt TGT_TRAP_S0TBINT
#else
void hc_s0tb_isr(void) interrupt TGT_TRAP_S0TBINT using TICKBANK
#endif
{
#if TGT_TX_PEC
    if (hc_txp_on) {
        unsigned char h, k;
        hc_txp_pk[hc_txp_cur] = 0u;          /* its last byte is in S0TBUF */
        h = (unsigned char)(hc_txp_cur ^ 1u);
        k = hc_txp_pk[h];
        if (k != 0u) {
            hc_txp_cur = h;
            SRCP5 = TXP_PHYS(&hc_txp_buf[h ? TX_HALF : 0u]);
            PECC5 = (unsigned int)(PECC_BYTE_SRCINC | k);
            if (echo_seen) SER.sent += k;
            return;
        }
        if (SER.have || hc_txp_filling) {
            hc_txp_drained = 1u;          /* the tick fills and restarts */
            hc_txp_fin_t = T7;
            S0TBIE = 0;
            return;
        }
        /* THE LAST BYTE IS IN S0TBUF - or already in the shift register:
           onto an idle line it moves at once and its buffer-empty request IS
           this interrupt, so no further request may ever come (the KWP sync
           byte, 2026-11-06 sim). The tick ends the job two byte times later
           (2 ms covers 10400), when S0TBUF is certainly empty again. */
        hc_txp_fin_t = T7;
        hc_txp_fin = 1u;
        S0TBIE = 0;
        return;
    }
    /* not a job: a stray request - stop it */
    S0TBIE = 0;
#else
    if (SER.st == ST_IDLE || !SER.have) {
        /* End-of-job activity, for the bounded no-echo forgiveness wait. */
        SER.echo_t = T7;
        S0TBIE = 0;
        SER.st = ST_IDLE;
        return;
    }
    emit();
#endif
}

/* Main loop. 0 if a job is still running (the caller waits for it - replies
   are half-duplex and never overlap). BUF/PLAIN copy src (<= HC_TX_BUF_N). */
unsigned char far hc_tx_start(unsigned char kind, unsigned char code,
                              unsigned int off, unsigned int n,
                              const unsigned char *src)
{
    unsigned int k;
    if (SER.st != ST_IDLE) return 0u;
    /* src 0: the bytes are already in the job buffer (hc_tx_stage) */
    if ((kind == HC_TXK_BUF || kind == HC_TXK_PLAIN) && src != 0) {
        if (n > HC_TX_BUF_N) n = HC_TX_BUF_N;
        for (k = 0u; k < n; k++) SER_BUF(k) = src[k];
    }
    if (kind == HC_TXK_PAGE) {
        (void)hc_cfg_mgr_read_u8(0u);        /* finish the DESIRED seed copy */
    }
    if (kind == HC_TXK_PLAIN && n == 0u) return 1u;
    SER.kind = kind; SER.code = code; SER.off = off; SER.n = n; SER.i = 0u;
    SER.hold_ok = 0u;
    SER.st = (kind == HC_TXK_PLAIN) ? ST_DATA : ST_LENHI;
#if TGT_TX_PEC
    /* EVERY job: the C4 layout's job buffer (SER_BUF, external SRAM) is not
       the PEC buffer, so BUF / PLAIN replies are generated into it too */
    {
        S0TBIC = 0u;                   /* no request, no PEC while staged */
        prep();
        SER.have = 1u;
        hc_txp_pk[0] = tx_gen(0u);
        hc_txp_pk[1] = tx_gen(1u);
        hc_txp_fin = 0u; hc_txp_drained = 0u; hc_txp_filling = 0u;
        hc_txp_on = 1u;
        tx_arm(0u);
        hc_txp_run = 1u;
        /* enabled with the request set: S0TBUF is empty, PEC5 moves byte 0 */
        S0TBIC = (unsigned int)(HC_IC(TGT_ILVL_SERIAL_TXPEC, TGT_GLVL_SERIAL_TXPEC) | 0x0080u);
        return 1u;
    }
#else
    /* Levels set, no request, not enabled while the first byte goes out and
       the second is prepared; then enable without touching the request the
       first byte's transfer has raised. */
    S0TBIC = (unsigned int)(HC_IC(TGT_ILVL_SERIAL_TX, TGT_GLVL_SERIAL_TX) & ~0x40u);
    prep();
    emit();
    S0TBIE = 1;
    return 1u;
#endif
}

/* KWP replies (hckwp_me711.c, 2026-10-28): staged straight into the job
   buffer while it is idle, then one HC_TXK_PLAIN job with src 0. Sent byte by
   byte through hcts_tx() at 10400 baud, the 36-byte IDENTIFY reply held the
   main loop 35 ms at every KWP entry (stability issue 03, bench 2.7T). */
unsigned char far hc_tx_stage(unsigned char k, unsigned char b)
{
    if (SER.st != ST_IDLE || k >= HC_TX_BUF_N) return 0u;
    SER_BUF(k) = b;
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
