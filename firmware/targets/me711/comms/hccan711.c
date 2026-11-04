/*
 * hccan711.c - the C167 on-chip CAN module and the VAG engine messages
 * (2026-11-03, .scratch/can-bus/spec.md P1 + P2 first cut).
 *
 * WHAT IT DOES. With canEnable = 1 (read at boot) the CAN module is set up
 * the way the stock ME7 does it (OEM 0x844C42 / 0x844D02, the BTR of each
 * board's clock: 500 kbit/s, 11-bit), and with canVag = 1 the engine sends
 * Motor_1 (0x280), Motor_2 (0x288), Motor_3 (0x380) every 10 ms and Motor_5
 * (0x480) every 20 ms - rpm, coolant, intake air, pedal, throttle, lamps,
 * fuel consumption, identity. Payloads: firmware/comms/hccan.c (host-tested
 * against opendbc vw_pq.dbc). With canEnable = 0 nothing here touches the
 * module: the pins stay in their reset state and the ECU is silent.
 *
 * MAIN LOOP, NOT THE TICK. The spec planned a 1 ms tick slot. This first
 * cut serves the objects from the main loop (owner 2026-11-03: engine
 * runtime first - nothing is added to an interrupt). The CAN module sends a
 * frame by itself once its object holds TXRQ; a long main-loop pass only
 * delays the next payload (the frame repeats its last content meanwhile on
 * no bus - a VAG frame is never resent by the module), it never delays the
 * engine.
 *
 * 2026-11-04: MESSAGE OBJECTS ARE ALLOCATED AT BOOT by what the page
 * enables, in priority order - engine frames, the receive list, ABS
 * emulation, Haldex (Allrad_1), wideband, OBD-II, custom frames - from the
 * 15 the module has (OBD-II takes MO15: its own mask hears 0x7DF and 0x7E0).
 * One that does not fit is not configured and OCH 1676 bit 7 says so;
 * nothing is silently dropped. New: ABS emulation (Bremse_1 / Bremse_3 from
 * the vehicle speed, suspended while a real Bremse_1 is on the bus), Haldex
 * control by the emulated rear wheel speeds (closed loop on Allrad_1),
 * wideband controllers over CAN (rusEFI / AEM) as lambda source 3, and
 * OBD-II mode 01 / 03 / 04 / 07 / 09 with ISO-TP multi-frame replies.
 *
 * Far module (MOD167 MEDIUM, HC_FAR_BRIDGE), state in battery-backed SRAM
 * (TGT_RAM_CANSTATE, cleared at boot), no ?C_ helper.
 */
#include "hcfarbridge.h"
#include <reg167.h>
#include "hctarget.h"
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hcfarinline.h"
#include "hctrigger.h"
#include "hcengine.h"
#include "hc_dbw.h"
#include "hcidle711.h"
#include "hcdtc.h"
#include "hcdtc711.h"
#include "hcxfn711.h"
#include "hccan711.h"
#include "hcio711.h"
#include "hcengctl711.h"
#include "hcvss711.h"
extern unsigned int hc_tick_ms;

#define DIV32U(n, d)  ((unsigned int)((unsigned long)(n) / (unsigned int)(d)))
#include "hccan.c"

/* ------------------------------------------------ the C167CR CAN module */
/* Keil CAN.H names, kept local (only what is used here) */
#define C1CSR   (*((unsigned int volatile sdata *) 0xEF00))
#define C1BTR   (*((unsigned int volatile sdata *) 0xEF04))
#define C1GMS   (*((unsigned int volatile sdata *) 0xEF06))
#define C1UGML  (*((unsigned int volatile sdata *) 0xEF08))
#define C1LGML  (*((unsigned int volatile sdata *) 0xEF0A))
#define C1UMLM  (*((unsigned int volatile sdata *) 0xEF0C))
#define C1LMLM  (*((unsigned int volatile sdata *) 0xEF0E))
/* message object n (1..15) at 0xEF00 + 0x10 n */
#define MO_MCR(n)   (*((unsigned int volatile sdata *) (0xEF00u + 0x10u * (n))))
#define MO_UAR(n)   (*((unsigned int volatile sdata *) (0xEF02u + 0x10u * (n))))
#define MO_LAR(n)   (*((unsigned int volatile sdata *) (0xEF04u + 0x10u * (n))))
#define MO_MCFG(n)  (*((unsigned char volatile sdata *) (0xEF06u + 0x10u * (n))))
#define MO_DATA(n)  ((unsigned char volatile sdata *) (0xEF07u + 0x10u * (n)))

#define CSR_INIT   0x0001u
#define CSR_CCE    0x0040u
#define CSR_EWRN   0x4000u
#define CSR_BOFF   0x8000u
#define MCR_TXRQ   0x2000u
#define MCR_ALL_RESET   0x5555u   /* every flag pair "reset"               */
#define MCR_VALID_ONLY  0x5595u   /* MSGVAL set, everything else reset     */
#define MCR_CPUUPD_SET  0xFBFFu   /* CPUUPD set, the rest unchanged        */
#define MCR_SEND        0xE6FFu   /* CPUUPD reset, NEWDAT + TXRQ set       */

/* BTR at 500 kbit/s, the OEM's own (spec section 3): 40 MHz 20 tq, 24 MHz
   12 tq, sample point 65 / 66.7 %. Only these two clocks exist. */
#if TGT_FCPU_HZ == 40000000uL
#define CAN_BTR_500K  0x6B01u
#elif TGT_FCPU_HZ == 24000000uL
#define CAN_BTR_500K  0x3601u
#elif TGT_FCPU_HZ == 32000000uL
/* the A4 B7 BFB (2026-11-04): BRP 1 -> tq = 4 / 32 MHz = 0.125 us; 1 + 10
   + 5 = 16 tq = 2 us (500 kbit/s), sample point 11/16 = 68.75 % - the same
   construction as 0x6B01 / 0x3601 (TSEG1 9, TSEG2 4, SJW 1). INFERENCE from
   the C167CR formula, not read from the BFB's stock image. */
#define CAN_BTR_500K  0x4901u
#else
#error "no CAN bit timing for this CPU clock"
#endif

/* -------------------------------------------- message object allocation */
#define MOI_M1      0u
#define MOI_M2      1u
#define MOI_M3      2u
#define MOI_M5      3u
#define MOI_M6      4u
#define MOI_CTX0    5u          /* custom frames 1 / 2: 5, 6               */
#define MOI_RX0     7u          /* the receive list: 7..13                 */
#define MOI_B1TX    14u         /* ABS emulation Bremse_1                  */
#define MOI_B3TX    15u         /* ABS emulation Bremse_3                  */
#define MOI_ALLRAD  16u         /* Haldex status                           */
#define MOI_WB0     17u         /* wideband controllers: 17, 18            */
#define MOI_WBST    19u         /* rusEFI wideband ECU status (29-bit TX)  */
#define MOI_OBDTX   20u
#define MOI_OBDRX   21u         /* always MO15                             */
#define MOI_N       22u
#define RX_N   7u
#define MCR_NEWDAT     0x0200u
#define MCR_MSGLST     0x0800u
#define MCR_RX_ACK     0xF5FFu   /* NEWDAT and MSGLST reset, the rest kept */

/* -------------------------------------------------------------- state */
typedef struct {
    hccan_vag_state_t v;
    unsigned int  next_ms;        /* the next 10 ms slot                   */
    unsigned int  tx;             /* frames handed to the module           */
    unsigned int  late;           /* a payload waited: TXRQ still pending  */
    unsigned int  boffs;          /* bus-off events                        */
    unsigned int  boff_ms;        /* when the current bus-off began        */
    unsigned int  fuel_res;       /* consumption remainder, 0.01 ul        */
    unsigned char on;             /* the module was set up at boot         */
    unsigned char vag;            /* engine messages enabled               */
    unsigned char slot;           /* 10 ms slot counter (Motor_5 on odd)   */
    unsigned char in_boff;
    /* receiving (2026-11-03) */
    unsigned char rx_on;          /* canRxMask at boot                     */
    unsigned char crash;          /* an airbag crash was seen: latched to boot */
    unsigned char rx_got;         /* bit per message: ever received        */
    unsigned char rx_lost;        /* MSGLST seen (a frame overwritten)     */
    unsigned int  rx_ms[RX_N];    /* when each message last arrived        */
    unsigned char rx[RX_N][8];    /* the last payload of each              */
    unsigned int  rx_frames;
    unsigned int  vss;            /* the CAN vehicle speed, 0xFFFF none    */
    unsigned int  ctx_ms[2];      /* custom frames: when each was last sent */
    unsigned char ctx_on;         /* bit per custom frame configured at boot */
    unsigned char off_pub;        /* CAN off: the readouts were cleared once */
    /* 2026-11-04 */
    unsigned char mo[MOI_N];      /* object per function, 0 = none          */
    unsigned char mo_next;        /* allocation cursor                      */
    unsigned char mo_short;       /* a wanted object did not fit            */
    unsigned char abs_emu;        /* ABS emulation configured               */
    unsigned char abs_susp;       /* ... suspended: a real Bremse_1 seen    */
    unsigned char b1_ctr;
    unsigned char hx_mode;        /* Haldex mode at boot                    */
    unsigned char wb_fmt;         /* wideband format at boot                */
    unsigned int  wb_lam[2];      /* lambda x1000, 0 = none                 */
    unsigned int  wb_ms[2];
    unsigned int  al_lock;        /* Allrad_1 actual lock, 0.1 %            */
    unsigned char al_st, al_got;
    unsigned int  al_ms;
    unsigned int  hx_want, hx_off;   /* wanted lock 0.1 %, rear offset 0.1 km/h */
    hccan_hx_t    hx;
    unsigned int  hx_ms;
    unsigned char obd_on;
    unsigned char obd_reqs;
    /* ISO-TP transmit of a multi-frame OBD reply */
    unsigned char tp_buf[24];
    unsigned char tp_len, tp_pos, tp_sn, tp_wait;
    unsigned int  tp_ms;
    unsigned int  run_ms, run_s;  /* engine running time (OBD PID 1F)      */
} hccan_rt_t;

#define CS (*(hccan_rt_t huge *)(TGT_EXTRAM_BASE + TGT_RAM_CANSTATE))
typedef char hccan_rt_fits[(sizeof(hccan_rt_t) <= TGT_RAM_CANSTATE_LIMIT) ? 1 : -1];

#define OCH1B ((unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_OCH))
#define OCH2B ((unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_OCH2))
#define OCH3B ((unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_OCH3))
static void och_c(unsigned int at, unsigned int v)
{
    OCH1B[at] = (unsigned char)(v >> 8);
    OCH1B[at + 1u] = (unsigned char)(v & 0xFFu);
}
static void och3(unsigned int at, unsigned int v)
{
    OCH3B[at - TGT_OCH_SPLIT2] = (unsigned char)(v >> 8);
    OCH3B[at - TGT_OCH_SPLIT2 + 1u] = (unsigned char)(v & 0xFFu);
}
/* one byte of the output block, whichever region holds it (hcts.h OCH_BYTE) */
static unsigned char och_rd(unsigned int at)
{
    if (at < TGT_OCH_SPLIT) return OCH1B[at];
    if (at < TGT_OCH_SPLIT2) return OCH2B[at - TGT_OCH_SPLIT];
    if (at < TGT_OCH_SIZE) return OCH3B[at - TGT_OCH_SPLIT2];
    return 0u;
}

static unsigned int u8v(unsigned int off) { return hc_cal_u8v(off); }

/* the multiplex / consumption state lives in battery-backed SRAM (huge);
   the encoders take a near pointer - copy in, copy out */
static void vload(hccan_vag_state_t *v)
{
    v->mux2 = CS.v.mux2;
    v->mux5 = CS.v.mux5;
    v->fuel_ul = CS.v.fuel_ul;
    v->fuel_ovf = CS.v.fuel_ovf;
    v->ctr6 = CS.v.ctr6;
}

static void vstore(const hccan_vag_state_t *v)
{
    CS.v.mux2 = v->mux2;
    CS.v.mux5 = v->mux5;
    CS.v.fuel_ul = v->fuel_ul;
    CS.v.fuel_ovf = v->fuel_ovf;
    CS.v.ctr6 = v->ctr6;
}

/* the next free object for function `which` (MO1..MO14; MO15 is OBD's) */
static unsigned char mo_take(unsigned char which)
{
    unsigned char n = CS.mo_next;
    if (n == 0u || n > 14u) {
        CS.mo_short = 1u;
        return 0u;
    }
    CS.mo[which] = n;
    CS.mo_next = (unsigned char)(n + 1u);
    return n;
}

/* identifier into the arbitration registers: 11-bit (lo16 = id), or 29-bit
   (id = hi13 << 16 | lo16; C167CR UM 18: UAR = ID28..21 | ID20..13 << 8,
   LAR = ID12..5 | ID4..0 << 11) */
static void mo_arb(unsigned char n, unsigned int hi13, unsigned int lo16, unsigned char ext)
{
    if (ext) {
        unsigned int id28_21 = (unsigned int)((hi13 >> 5) & 0xFFu);
        unsigned int id20_13 = (unsigned int)(((hi13 & 0x1Fu) << 3) | (lo16 >> 13));
        MO_UAR(n) = (unsigned int)(id28_21 | (id20_13 << 8));
        MO_LAR(n) = (unsigned int)(((lo16 >> 5) & 0xFFu) | ((lo16 & 0x1Fu) << 11));
    } else {
        MO_UAR(n) = (unsigned int)((lo16 >> 3) | ((lo16 & 7u) << 13));
        MO_LAR(n) = 0u;
    }
}

static void mo_tx_cfg(unsigned char n, unsigned int hi13, unsigned int id,
                      unsigned char ext, unsigned char dlc)
{
    if (n == 0u) return;
    MO_MCR(n) = MCR_ALL_RESET;                       /* MSGVAL reset first */
    mo_arb(n, hi13, id, ext);
    MO_MCFG(n) = (unsigned char)((dlc << 4) | 0x08u | (ext ? 0x04u : 0u));
    MO_MCR(n) = MCR_VALID_ONLY;
}

static void mo_rx_cfg(unsigned char n, unsigned int hi13, unsigned int id,
                      unsigned char ext)
{
    if (n == 0u) return;
    MO_MCR(n) = MCR_ALL_RESET;
    mo_arb(n, hi13, id, ext);
    MO_MCFG(n) = (unsigned char)(ext ? 0x04u : 0x00u); /* receive */
    MO_MCR(n) = MCR_VALID_ONLY;
}

/* hand 8 bytes to an object (UM 18 note 2 order: CPUUPD, data, NEWDAT +
   TXRQ with CPUUPD reset). A payload whose previous frame is still pending
   waits for the next slot - never a busy wait. */
static void mo_send(unsigned char n, const unsigned char *d)
{
    unsigned char volatile sdata *p;
    unsigned char i;
    if (n == 0u) return;
    p = MO_DATA(n);
    if (MO_MCR(n) & MCR_TXRQ) {
        CS.late++;
        return;
    }
    MO_MCR(n) = MCR_CPUUPD_SET;
    for (i = 0u; i < 8u; i++) {
        p[i] = d[i];
    }
    MO_MCR(n) = MCR_SEND;
    CS.tx++;
}

/* a consistent copy of a receive object (UM 18 receive note): reset NEWDAT,
   copy, look at NEWDAT again - set = a newer frame arrived, copy again.
   Returns 1 when there was a new frame. */
static unsigned char mo_read(unsigned char n, unsigned char *d)
{
    unsigned char volatile sdata *p;
    unsigned char k, tries;
    if (n == 0u || !(MO_MCR(n) & MCR_NEWDAT)) return 0u;
    p = MO_DATA(n);
    for (tries = 0u; tries < 2u; tries++) {
        if (MO_MCR(n) & MCR_MSGLST) CS.rx_lost = 1u;
        MO_MCR(n) = MCR_RX_ACK;
        for (k = 0u; k < 8u; k++) d[k] = p[k];
        if (!(MO_MCR(n) & MCR_NEWDAT)) break;
    }
    CS.rx_frames++;
    return 1u;
}

static const unsigned int huge rx_id[RX_N] = {
    HCCAN_ID_BREMSE1, HCCAN_ID_BREMSE3, HCCAN_ID_GETRIEBE1, HCCAN_ID_KOMBI1,
    HCCAN_ID_KOMBI2, HCCAN_ID_AIRBAG1, HCCAN_ID_KLIMA1
};
#define RXI_BREMSE1 0u
#define RXI_BREMSE3 1u
#define RXI_GETR1   2u
#define RXI_KOMBI1  3u
#define RXI_KOMBI2  4u
#define RXI_AIRBAG  5u
#define RXI_KLIMA   6u

static void rx_service(unsigned int ms)
{
    unsigned char i, k, d[8];
    for (i = 0u; i < RX_N; i++) {
        if (!(CS.rx_on & (unsigned char)(1u << i))) continue;
        if (!mo_read(CS.mo[MOI_RX0 + i], d)) continue;
        for (k = 0u; k < 8u; k++) CS.rx[i][k] = d[k];
        CS.rx_ms[i] = ms;
        CS.rx_got |= (unsigned char)(1u << i);
    }
}

static unsigned char rx_fresh(unsigned char i, unsigned int ms)
{
    unsigned int tmo = (unsigned int)(u8v(CFG_U_CAN_RX_TMO) * 10u);
    if (tmo == 0u) tmo = 500u;
    return (unsigned char)((CS.rx_got & (unsigned char)(1u << i))
                           && (unsigned int)(ms - CS.rx_ms[i]) < tmo);
}

static void rx_copy(unsigned char i, unsigned char *d)
{
    unsigned char k;
    for (k = 0u; k < 8u; k++) d[k] = CS.rx[i][k];
}

/* the vehicle speed from the selected CAN source, 0.1 km/h; 0xFFFF = none.
   Never the ABS emulation's own frames (they are sent, not received). */
static unsigned int vss_now(unsigned int ms)
{
    unsigned char d[8], src = (unsigned char)u8v(CFG_U_CAN_VSS_SRC);
    unsigned int w[4];
    if (src == 1u && rx_fresh(RXI_BREMSE1, ms)) {
        hccan_bremse1_t b;
        rx_copy(RXI_BREMSE1, d); hccan_rx_bremse1(d, &b);
        return b.vss_x10;
    }
    if ((src == 2u || src == 3u) && rx_fresh(RXI_BREMSE3, ms)) {
        rx_copy(RXI_BREMSE3, d); hccan_rx_bremse3(d, w);
        return (src == 2u) ? (unsigned int)((w[0] + w[1]) / 2u)
                           : (unsigned int)((w[2] + w[3]) / 2u);
    }
    if (src == 4u && rx_fresh(RXI_KOMBI1, ms)) {
        hccan_kombi1_t k1;
        rx_copy(RXI_KOMBI1, d); hccan_rx_kombi1(d, &k1);
        return k1.vss_x10;
    }
    return 0xFFFFu;
}

unsigned int far hc_can_vss_x10(void) { return CS.on ? CS.vss : 0xFFFFu; }
unsigned char far hc_can_crash(void) { return CS.crash; }

/* lambda from a wideband controller on the bus, x1000; 0 = none / stale
   (100 ms: the main loop's own granularity, the controller sends every 10) */
unsigned int far hc_can_lambda(unsigned char b)
{
    b &= 1u;
    if (!CS.on || CS.wb_lam[b] == 0u
        || (unsigned int)(hc_tick_ms - CS.wb_ms[b]) > 100u) {
        return 0u;
    }
    return CS.wb_lam[b];
}

/* receive telemetry: 544 vehicle speed (0.1 km/h, 0xFFFF none), 546 gear
   | Bremse_1 flags << 8 (bit 8 brake, 9 ESP off, 10 ASR request, 11 MSR
   request), 548 fresh-message bits | crash << 8 | a frame lost << 9, 550
   frames received, 470/472/474/604 wheel speeds FL FR RL RR (0.1 km/h),
   606 oil temperature, 608 outside temperature (0.1 C + 1000 C, 0 = none) */
static void rx_publish(unsigned int ms)
{
    unsigned char d[8], i, fresh = 0u;
    unsigned int g = 0u, w[4], amb = 0u, oil = 0u;
    w[0] = 0u; w[1] = 0u; w[2] = 0u; w[3] = 0u;
    for (i = 0u; i < RX_N; i++) {
        if (rx_fresh(i, ms)) fresh |= (unsigned char)(1u << i);
    }
    if (fresh & (1u << RXI_GETR1)) {
        hccan_getriebe1_t t;
        rx_copy(RXI_GETR1, d); hccan_rx_getriebe1(d, &t);
        g = t.gear;
    }
    if (fresh & (1u << RXI_BREMSE1)) {
        hccan_bremse1_t b;
        rx_copy(RXI_BREMSE1, d); hccan_rx_bremse1(d, &b);
        if (b.brake) g |= 0x100u;
        if (b.esp_off) g |= 0x200u;
        if (b.asr_req) g |= 0x400u;
        if (b.msr_req) g |= 0x800u;
    }
    if (fresh & (1u << RXI_BREMSE3)) {
        rx_copy(RXI_BREMSE3, d); hccan_rx_bremse3(d, w);
    }
    if (fresh & (1u << RXI_KOMBI2)) {
        rx_copy(RXI_KOMBI2, d); hccan_rx_kombi2(d, &amb, &oil);
    }
    och_c(544u, CS.vss);
    och_c(546u, g);
    och_c(548u, (unsigned int)((unsigned int)fresh | (CS.crash ? 0x100u : 0u)
                               | (CS.rx_lost ? 0x200u : 0u)));
    och_c(550u, CS.rx_frames);
    och_c(470u, w[0]); och_c(472u, w[1]); och_c(474u, w[2]); och_c(604u, w[3]);
    och_c(606u, oil);
    och_c(608u, amb);
}

/* CUSTOM FRAMES (2026-11-03): four 16-bit words of the live-data block
   per frame, at the frame's own period - for an aftermarket dash or
   logger. The values are the raw OCH words (the .ini scales them). */
static void ctx_service(unsigned int ms)
{
    unsigned char k, j, d[8], le = (unsigned char)u8v(CFG_U_CAN_CTX_LE);
    for (k = 0u; k < 2u; k++) {
        unsigned int per = (unsigned int)(u8v(CFG_U_CAN_CTX_RATE + k) * 10u);
        if (!(CS.ctx_on & (unsigned char)(1u << k))) continue;
        if (per == 0u) per = 100u;
        if ((unsigned int)(ms - CS.ctx_ms[k]) < per) continue;
        CS.ctx_ms[k] = ms;
        for (j = 0u; j < 4u; j++) {
            unsigned int at = hc_cal_u16(CFG_U_CAN_CTX_CH + 2u * (unsigned int)(4u * k + j));
            unsigned char hi = 0u, lo = 0u;
            if (at < (unsigned int)(TGT_OCH_SIZE - 1u)) {
                hi = och_rd(at);
                lo = och_rd((unsigned int)(at + 1u));
            }
            if (le & (unsigned char)(1u << k)) {
                d[2u * j] = lo; d[2u * j + 1u] = hi;
            } else {
                d[2u * j] = hi; d[2u * j + 1u] = lo;
            }
        }
        mo_send(CS.mo[MOI_CTX0 + k], d);
    }
}

void far hc_can_init(void)
{
    unsigned char i, wbn;
    unsigned int k;

    for (k = 0u; k < (unsigned int)sizeof(hccan_rt_t); k++) {
        ((unsigned char huge *)&CS)[k] = 0u;
    }
    if (u8v(CFG_U_CAN_ENABLE) == 0u) {
        return;                       /* the module is not touched at all */
    }
    C1CSR = (unsigned int)(CSR_INIT | CSR_CCE);
    C1BTR = CAN_BTR_500K;
    C1GMS = 0xE0FFu;                  /* all-care, as the OEM             */
    C1UGML = 0xFFFFu;
    C1LGML = 0xFFFFu;
    C1UMLM = 0xFFFFu;
    C1LMLM = 0xFFFFu;
    for (i = 1u; i <= 15u; i++) {
        MO_MCR(i) = MCR_ALL_RESET;    /* every object invalid             */
    }
    CS.mo_next = 1u;
    CS.vss = 0xFFFFu;
    /* 1. the engine frames */
    CS.vag = (unsigned char)(u8v(CFG_U_CAN_VAG) == 1u);
    if (CS.vag) {
        mo_tx_cfg(mo_take(MOI_M1), 0u, HCCAN_ID_MOTOR1, 0u, 8u);
        mo_tx_cfg(mo_take(MOI_M2), 0u, HCCAN_ID_MOTOR2, 0u, 8u);
        mo_tx_cfg(mo_take(MOI_M3), 0u, HCCAN_ID_MOTOR3, 0u, 8u);
        mo_tx_cfg(mo_take(MOI_M5), 0u, HCCAN_ID_MOTOR5, 0u, 8u);
        mo_tx_cfg(mo_take(MOI_M6), 0u, HCCAN_ID_MOTOR6, 0u, 8u);
    }
    /* 2. the receive list (ABS emulation needs Bremse_1 to see a real ABS) */
    CS.abs_emu = (unsigned char)(u8v(CFG_U_CAN_ABS_EMU) != 0u);
    CS.rx_on = (unsigned char)((u8v(CFG_U_CAN_RX_MASK) & 0x7Fu)
                               | (CS.abs_emu ? 0x01u : 0u));
    for (i = 0u; i < RX_N; i++) {
        if (CS.rx_on & (unsigned char)(1u << i)) {
            mo_rx_cfg(mo_take((unsigned char)(MOI_RX0 + i)), 0u, rx_id[i], 0u);
        }
    }
    /* 3. ABS emulation and Haldex */
    if (CS.abs_emu) {
        mo_tx_cfg(mo_take(MOI_B1TX), 0u, HCCAN_ID_BREMSE1, 0u, 8u);
        mo_tx_cfg(mo_take(MOI_B3TX), 0u, HCCAN_ID_BREMSE3, 0u, 8u);
    }
    CS.hx_mode = (unsigned char)u8v(CFG_U_HX_MODE);
    if (CS.hx_mode > 3u) CS.hx_mode = 0u;
    if (CS.hx_mode != 0u) {
        mo_rx_cfg(mo_take(MOI_ALLRAD), 0u, HCCAN_ID_ALLRAD1, 0u);
    }
    /* 4. wideband controllers: one per lambda source "over CAN" */
    CS.wb_fmt = (unsigned char)u8v(CFG_U_CAN_WB_FMT);
    if (CS.wb_fmt > 2u) CS.wb_fmt = 0u;
    if (CS.wb_fmt != 0u) {
        unsigned int idx = u8v(CFG_U_CAN_WB_IDX);
        wbn = 0u;
        for (i = 0u; i < 2u; i++) {
            if (hc_cal_u8v(i ? CFG_U_LAM2_SRC : CFG_U_LAM1_SRC) != HC_LAMBDA_CAN) continue;
            if (CS.wb_fmt == 1u) {
                mo_rx_cfg(mo_take((unsigned char)(MOI_WB0 + i)), 0u,
                          (unsigned int)(HCCAN_ID_WB_RUSEFI + 2u * (idx + i)), 0u);
            } else {
                mo_rx_cfg(mo_take((unsigned char)(MOI_WB0 + i)), 0u,
                          (unsigned int)(HCCAN_ID_WB_AEM + idx + i), 1u);
            }
            wbn++;
        }
        if (CS.wb_fmt == 1u && wbn != 0u) {
            /* the rusEFI controller heats only when the ECU says so:
               0x0EF50000 (29-bit), 2 bytes, every 10 ms */
            mo_tx_cfg(mo_take(MOI_WBST), 0x0EF5u, 0x0000u, 1u, 2u);
        }
    }
    /* 5. OBD-II: replies on 0x7E8; requests on MO15, whose own mask
       ignores the low 6 identifier bits (0x7C0..0x7FF, filtered below) */
    CS.obd_on = (unsigned char)(u8v(CFG_U_CAN_OBD) != 0u);
    if (CS.obd_on) {
        mo_tx_cfg(mo_take(MOI_OBDTX), 0u, HCCAN_ID_OBD_RESP, 0u, 8u);
        C1UMLM = 0x00F8u;             /* care ID10..6 only               */
        C1LMLM = 0x0000u;
        mo_rx_cfg(15u, 0u, HCCAN_ID_OBD_FUNC, 0u);
        CS.mo[MOI_OBDRX] = 15u;
    }
    /* 6. the custom frames */
    for (i = 0u; i < 2u; i++) {
        unsigned int id = hc_cal_u16(CFG_U_CAN_CTX_ID + 2u * (unsigned int)i);
        if (id != 0u && id <= 0x7FFu) {
            mo_tx_cfg(mo_take((unsigned char)(MOI_CTX0 + i)), 0u, id, 0u, 8u);
            if (CS.mo[MOI_CTX0 + i] != 0u) CS.ctx_on |= (unsigned char)(1u << i);
        }
    }
    C1CSR = 0u;                       /* INIT and CCE off: on the bus      */
    CS.on = 1u;
}

/* the engine's state for the encoders */
static void eng_state(hccan_eng_t *e)
{
    unsigned int f = 0u, err = eng_sensor_err, hot, vs = hc_vss_x10();
    unsigned char dbw = (unsigned char)(hc_cal_u8v(CAL_DBW_ENABLE) != 0u);
    unsigned char epc = (unsigned char)u8v(CFG_U_CAN_EPC_SRC);

    e->rpm = trg_rpm;
    e->clt_dc = eng_clt_dc;
    e->iat_dc = eng_iat_dc;
    e->pedal_x10 = dbw ? hc_dbw_pedal_x10() : eng_pedal_x10;
    e->tps_x10 = eng_tps_x10;
    e->rl_x10 = eng_rl_x10;
    e->idle_rpm = hc_idle_target_rpm;
    e->vss_x10 = (vs == 0xFFFFu) ? 0u : vs;
    e->fan_pct = 0u;
    if (e->pedal_x10 < 10u)                                  f |= HCCAN_F_IDLE;
    if (err & (ENG_ERR_PEDAL1 | ENG_ERR_PEDAL2 | ENG_ERR_PED_DIFF)) f |= HCCAN_F_PEDAL_BAD;
    if (err & (ENG_ERR_TPS1 | ENG_ERR_TPS2 | ENG_ERR_TPS_DIFF))     f |= HCCAN_F_TPS_BAD;
    if (err & ENG_ERR_CLT)                                   f |= HCCAN_F_CLT_BAD;
    if (err & ENG_ERR_IAT)                                   f |= HCCAN_F_IAT_BAD;
    if (trg_rpm == 0u)                                       f |= HCCAN_F_STOPPED;
    else if (trg_rpm > hc_cal_u16(CFG_CRANK_RPM_MAX))        f |= HCCAN_F_RUNNING;
    if (hc_dtc.mil)                                          f |= HCCAN_F_MIL;
    if (hc_dtc.n_stored != 0u)                               f |= HCCAN_F_DTC_STORED;
    if (((epc & 1u) && dbw && hc_dbw_faults() != 0u)
        || ((epc & 2u) && hc_x_limp_why() != 0u))            f |= HCCAN_F_EPC;
    hot = hc_cal_u16(CFG_U_CAN_HOT_CLT);
    if (hot != 0u && !(err & ENG_ERR_CLT) && eng_clt_dc > hot) f |= HCCAN_F_HOT;
    if (eng_fuelcut != 0u)                                   f |= HCCAN_F_CUT;
    if (err & (ENG_ERR_MAP | ENG_ERR_TPS1 | ENG_ERR_TPS_DIFF)) f |= HCCAN_F_TQ_BAD;
    if (!dbw)                                                f |= HCCAN_F_NO_DBW;
    e->flags = f;
}

static void id_state(hccan_vag_id_t *id)
{
    id->canvers = (unsigned char)u8v(CFG_U_CAN_VERS);
    id->fmotc = (unsigned char)u8v(CFG_U_CAN_FMOTC);
    id->cwgc = (unsigned char)u8v(CFG_U_CAN_CWGC);
    id->mottyp = (unsigned char)u8v(CFG_U_CAN_MOTTYP);
    id->mdnorm_nm = hc_cal_u16(CFG_U_CAN_MDNORM);
    id->mdmax_nm = hc_cal_u16(CFG_U_CAN_MDMAX);
    id->nmdmax_rpm = hc_cal_u16(CFG_U_CAN_NMDMAX);
    id->kvnpz = hc_cal_u16(CFG_U_CAN_KVNPZ);
}

/* injected fuel of the last 10 ms, into the Motor_5 counter (ul) */
static void fuel_10ms(void)
{
    unsigned int mgc, afr = eng_afr_x10, rpm = trg_rpm, ul, corr;
    unsigned char cyl = (unsigned char)u8v(CFG_CYLINDERS);
    unsigned long n;

    if (rpm == 0u || eng_fuelcut != 0u || afr < 50u || cyl == 0u) {
        return;
    }
    /* fuel per cylinder per cycle, 0.01 mg = air 0.1 mg x 100 / AFR x10 x 10 */
    n = (unsigned long)eng_air_mg_x10 * 100u;
    if (n >= (unsigned long)afr * 60000u) return;           /* > 600 mg    */
    mgc = DIV32U(n, afr);
    if (mgc > (unsigned int)(65535u / cyl)) mgc = (unsigned int)(65535u / cyl);
    /* x cylinders x cycles in 10 ms (rpm / 2 / 60 / 100 = rpm / 12000) */
    n = (unsigned long)(unsigned int)(mgc * cyl) * (rpm > 9000u ? 9000u : rpm);
    if (n >= 60000uL * 12000uL) return;
    ul = DIV32U(n, 12000u);                                  /* 0.01 mg    */
    /* 0.745 mg/ul (HaniCore's petrol density); 0.01 ul */
    n = (unsigned long)ul * 1000u;
    if (n >= 60000uL * 745uL) return;
    ul = DIV32U(n, 745u);
    corr = u8v(CFG_U_CAN_FUEL_CORR);
    if (corr != 0u && corr != 100u) {
        n = (unsigned long)ul * corr;
        if (n >= 60000uL * 100uL) return;
        ul = DIV32U(n, 100u);
    }
    CS.fuel_res += ul;
    if (CS.fuel_res >= 100u) {
        hccan_vag_state_t v;
        vload(&v);
        hccan_fuel_add(&v, CS.fuel_res / 100u);
        vstore(&v);
        CS.fuel_res = (unsigned int)(CS.fuel_res % 100u);
    }
}

/* -------------------------------------------------- wideband + Haldex */
static void wb_service(unsigned int ms)
{
    unsigned char i, d[8];
    for (i = 0u; i < 2u; i++) {
        if (!mo_read(CS.mo[MOI_WB0 + i], d)) continue;
        CS.wb_lam[i] = (CS.wb_fmt == 1u) ? hccan_rx_wb_rusefi(d) : hccan_rx_wb_aem(d);
        CS.wb_ms[i] = ms;
    }
}

/* a 4-point curve from the page: x ascending (u8 axis x ax_scale), y u8 */
static unsigned int curve4(unsigned int x, unsigned int ax_off, unsigned int ax_scale,
                           unsigned int y_off)
{
    unsigned char i;
    unsigned int x0, x1, y0, y1;
    x0 = (unsigned int)(u8v(ax_off) * ax_scale);
    if (x <= x0) return u8v(y_off);
    for (i = 1u; i < 4u; i++) {
        x1 = (unsigned int)(u8v(ax_off + i) * ax_scale);
        if (x <= x1) {
            y0 = u8v(y_off + i - 1u);
            y1 = u8v(y_off + i);
            if (x1 <= x0) return y1;
            if (y1 >= y0)
                return (unsigned int)(y0 + DIV32U((unsigned long)(y1 - y0) * (x - x0), x1 - x0));
            return (unsigned int)(y0 - DIV32U((unsigned long)(y0 - y1) * (x - x0), x1 - x0));
        }
        x0 = x1;
    }
    return u8v(y_off + 3u);
}

/* the wanted Haldex lock, 0.1 %: throttle curve, rpm limit, maximum, brake
   and launch overrides */
static unsigned int hx_wanted(void)
{
    unsigned int w = (unsigned int)(curve4(eng_tps_x10, CFG_U_HX_TPS_AX, 10u,
                                           CFG_U_HX_TPS_LOCK) * 10u);
    unsigned int lim = (unsigned int)(curve4(trg_rpm, CFG_U_HX_RPM_AX, 100u,
                                             CFG_U_HX_RPM_LIMIT) * 10u);
    unsigned int mx = (unsigned int)(u8v(CFG_U_HX_MAX) * 10u);
    if (lim != 0u && w > lim) w = lim;
    if (mx == 0u) mx = 1000u;
    if (HC_EC.launch && u8v(CFG_U_HX_LAUNCH) != 0u) w = (unsigned int)(u8v(CFG_U_HX_LAUNCH) * 10u);
    if (w > mx) w = mx;
    if (u8v(CFG_U_HX_BRAKE) != 0u && (OCH1B[546] & 0x01u)) w = 0u;   /* brake */
    return w;
}

static void hx_service(unsigned int ms)
{
    unsigned char d[8];
    unsigned int no, full, dt;
    if (mo_read(CS.mo[MOI_ALLRAD], d)) {
        unsigned int lk;
        unsigned char st;
        hccan_rx_allrad1(d, &lk, &st);
        CS.al_lock = lk;
        CS.al_st = st;
        CS.al_got = 1u;
        CS.al_ms = ms;
    }
    CS.hx_want = hx_wanted();
    if (CS.hx_mode == 1u || CS.hx_mode == 2u) {
        hccan_hx_t h;
        unsigned char ok = (unsigned char)(CS.al_got && (unsigned int)(ms - CS.al_ms) < 500u);
        no = curve4(trg_rpm, CFG_U_HX_RPM_AX, 100u, CFG_U_HX_NO_LOCK);
        full = curve4(trg_rpm, CFG_U_HX_RPM_AX, 100u, CFG_U_HX_FULL_LOCK);
        dt = (unsigned int)(ms - CS.hx_ms);
        CS.hx_ms = ms;
        h.integ_x100 = CS.hx.integ_x100;
        CS.hx_off = hccan_hx_offset(&h, CS.hx_want, CS.al_lock, ok, no, full,
                                    (unsigned char)u8v(CFG_U_HX_KP),
                                    (unsigned char)u8v(CFG_U_HX_KI),
                                    (unsigned char)u8v(CFG_U_HX_DEADBAND), dt);
        CS.hx.integ_x100 = h.integ_x100;
    } else {
        CS.hx_off = 0u;
    }
}

/* ABS emulation: Bremse_1 + Bremse_3 every 10 ms from the vehicle speed;
   the rear axle slower by the Haldex offset. Suspended for good (until the
   next boot) the moment a real Bremse_1 is received. */
static void abs_send(void)
{
    unsigned char d[8];
    unsigned int v = hc_vss_x10(), w[4];
    if (CS.rx_got & (1u << RXI_BREMSE1)) {
        CS.abs_susp = 1u;
    }
    if (CS.abs_susp) return;
    if (v == 0xFFFFu) v = 0u;
    hccan_tx_bremse1(v, 0u, CS.b1_ctr, d);
    CS.b1_ctr = (unsigned char)((CS.b1_ctr + 1u) & 0x0Fu);
    mo_send(CS.mo[MOI_B1TX], d);
    w[0] = v; w[1] = v;
    w[2] = (v > CS.hx_off) ? (unsigned int)(v - CS.hx_off) : 0u;
    w[3] = w[2];
    hccan_tx_bremse3(w, d);
    mo_send(CS.mo[MOI_B3TX], d);
}

/* ------------------------------------------------------------- OBD-II */
/* start an ISO-TP reply: one frame if it fits, else the first frame and
   the rest after the tester's flow control */
static void obd_reply(const unsigned char *pl, unsigned char n)
{
    unsigned char d[8], i;
    if (n <= 7u) {
        d[0] = n;
        for (i = 0u; i < 7u; i++) d[1u + i] = (unsigned char)(i < n ? pl[i] : 0x55u);
        mo_send(CS.mo[MOI_OBDTX], d);
        return;
    }
    if (n > (unsigned char)sizeof(CS.tp_buf)) n = (unsigned char)sizeof(CS.tp_buf);
    for (i = 0u; i < n; i++) CS.tp_buf[i] = pl[i];
    CS.tp_len = n;
    d[0] = 0x10u;
    d[1] = n;
    for (i = 0u; i < 6u; i++) d[2u + i] = pl[i];
    CS.tp_pos = 6u;
    CS.tp_sn = 1u;
    CS.tp_wait = 1u;              /* until the flow control */
    CS.tp_ms = hc_tick_ms;
    mo_send(CS.mo[MOI_OBDTX], d);
}

static void obd_tp_service(unsigned int ms)
{
    unsigned char d[8], i;
    if (CS.tp_len == 0u || CS.tp_wait) {
        if (CS.tp_len != 0u && (unsigned int)(ms - CS.tp_ms) > 1000u) CS.tp_len = 0u;
        return;
    }
    if (MO_MCR(CS.mo[MOI_OBDTX]) & MCR_TXRQ) return;     /* one at a time */
    d[0] = (unsigned char)(0x20u | (CS.tp_sn & 0x0Fu));
    for (i = 0u; i < 7u; i++) {
        unsigned char k = (unsigned char)(CS.tp_pos + i);
        d[1u + i] = (unsigned char)(k < CS.tp_len ? CS.tp_buf[k] : 0x55u);
    }
    mo_send(CS.mo[MOI_OBDTX], d);
    CS.tp_sn++;
    CS.tp_pos = (unsigned char)(CS.tp_pos + 7u);
    if (CS.tp_pos >= CS.tp_len) CS.tp_len = 0u;
}

static void obd_dtc_bytes(unsigned int code, unsigned char *a, unsigned char *b)
{
    /* the codes are decimal digits (105 = P0105): one BCD nibble per digit */
    unsigned int d1 = (unsigned int)(code / 1000u), r = (unsigned int)(code % 1000u);
    unsigned int d2 = (unsigned int)(r / 100u), d3 = (unsigned int)((r % 100u) / 10u);
    *a = (unsigned char)(((d1 & 3u) << 4) | d2);
    *b = (unsigned char)((d3 << 4) | (r % 10u));
}

static const char huge obd_name[] = "HaniCore ME7";
static const char huge obd_hex[] = "0123456789ABCDEF";

static void obd_service(unsigned int ms)
{
    unsigned char d[8], pl[24], n = 0u, i, mode;
    unsigned int id, uar;
    if (CS.mo[MOI_OBDRX] == 0u || !(MO_MCR(15u) & MCR_NEWDAT)) {
        obd_tp_service(ms);
        return;
    }
    uar = MO_UAR(15u);
    id = (unsigned int)(((uar & 0xFFu) << 3) | (uar >> 13));
    (void)mo_read(15u, d);
    if (id != HCCAN_ID_OBD_FUNC && id != HCCAN_ID_OBD_REQ) {
        obd_tp_service(ms);
        return;
    }
    if ((d[0] & 0xF0u) == 0x30u) {           /* flow control for our reply */
        CS.tp_wait = 0u;
        obd_tp_service(ms);
        return;
    }
    if (d[0] < 1u || d[0] > 7u) return;      /* single frames only */
    CS.obd_reqs++;
    mode = d[1];
    pl[0] = (unsigned char)(mode | 0x40u);
    if (mode == 0x01u) {
        hccan_obd_t o;
        o.rpm = trg_rpm;
        o.vss_x10 = hc_vss_x10();
        o.clt_dc = eng_clt_dc;
        o.iat_dc = eng_iat_dc;
        o.map_x10 = eng_map_kpa_x10;
        o.baro_x10 = eng_baro_kpa_x10;
        o.tps_x10 = eng_tps_x10;
        o.adv_x10 = (int)eng_adv_x10;
        o.load_x10 = eng_rl_x10 > 1000u ? 1000u : eng_rl_x10;
        o.lam_x1000 = hc_io_lambda(0u);
        o.vbat_mv = (unsigned int)(eng_batt_dv * 100u);
        o.run_s = CS.run_s;
        o.mil = hc_dtc.mil;
        o.n_dtc = hc_dtc.n_stored;
        pl[1] = d[2];
        n = hccan_obd_pid(d[2], &o, &pl[2]);
        if (n == 0u) return;                  /* unsupported: no reply (J1979) */
        n = (unsigned char)(n + 2u);
    } else if (mode == 0x03u || mode == 0x07u) {
        unsigned char mask = (mode == 0x03u) ? HCDTC_S_STORED : HCDTC_S_ACTIVE;
        unsigned char k = 0u;
        n = 2u;
        for (i = 0u; i < 10u; i++) {
            unsigned int c = hc_dtc_code(mask, i);
            if (c == 0u) break;
            obd_dtc_bytes(c, &pl[n], &pl[n + 1u]);
            n = (unsigned char)(n + 2u);
            k++;
        }
        pl[1] = k;
    } else if (mode == 0x04u) {
        if (trg_rpm != 0u) {                  /* engine stopped only */
            pl[0] = 0x7Fu; pl[1] = 0x04u; pl[2] = 0x22u;   /* conditions not correct */
            n = 3u;
        } else {
            hc_dtc_clear_req = 1u;
            n = 1u;
        }
    } else if (mode == 0x09u) {
        pl[1] = d[2];
        if (d[2] == 0x00u) {                  /* supported: 04 CALID, 0A name */
            pl[2] = 0x10u; pl[3] = 0x40u; pl[4] = 0u; pl[5] = 0u;
            n = 6u;
        } else if (d[2] == 0x04u) {
            /* calibration ID: "HC" + the page layout id + the board tag */
            unsigned int hi = (unsigned int)(HC_CFG_LAYOUT_ID >> 16);
            unsigned int lo = (unsigned int)(HC_CFG_LAYOUT_ID & 0xFFFFu);
            pl[2] = 1u;
            pl[3] = 'H'; pl[4] = 'C'; pl[5] = '-';
            n = 6u;
            for (i = 0u; i < 4u; i++) {             /* constant shifts only */
                pl[n++] = (unsigned char)obd_hex[(hi >> 12) & 0xFu];
                hi = (unsigned int)(hi << 4);
            }
            for (i = 0u; i < 4u; i++) {
                pl[n++] = (unsigned char)obd_hex[(lo >> 12) & 0xFu];
                lo = (unsigned int)(lo << 4);
            }
            while (n < 3u + 16u) pl[n++] = 0u;
        } else if (d[2] == 0x0Au) {
            pl[2] = 1u;
            n = 3u;
            for (i = 0u; obd_name[i] != 0; i++) pl[n++] = (unsigned char)obd_name[i];
            while (n < 3u + 20u) pl[n++] = 0u;
        } else {
            return;
        }
    } else {
        if (id == HCCAN_ID_OBD_FUNC) return;  /* functional: stay silent */
        pl[0] = 0x7Fu; pl[1] = mode; pl[2] = 0x11u;          /* service not supported */
        n = 3u;
    }
    obd_reply(pl, n);
}

/* ------------------------------------------------------------ service */
void far hc_can_service(unsigned int ms)
{
    hccan_eng_t e;
    hccan_vag_id_t id;
    hccan_vag_state_t v;
    unsigned char d[8];
    unsigned int csr;

    if (!CS.on) {
        /* CAN OFF: publish defined readouts once - the output block is in
           battery-backed SRAM and would otherwise show whatever an earlier
           image left there (bench 2026-11-03: 3859 km/h, 4440 km/h wheels) */
        if (!CS.off_pub) {
            CS.off_pub = 1u;
            CS.vss = 0xFFFFu;
            och_c(536u, 0u); och_c(538u, 0u); och_c(540u, 0u); och_c(542u, 0u);
            rx_publish(ms);
            for (csr = 1672u; csr < 1688u; csr = (unsigned int)(csr + 2u)) och3(csr, 0u);
        }
        och_c(534u, 0u);
        return;
    }
    csr = C1CSR;
    /* bus-off: the module sets INIT itself; restart after 200 ms (FR) */
    if (csr & CSR_BOFF) {
        if (!CS.in_boff) {
            CS.in_boff = 1u;
            CS.boffs++;
            CS.boff_ms = ms;
        } else if ((unsigned int)(ms - CS.boff_ms) >= 200u) {
            C1CSR = 0u;                    /* clear INIT: the module waits
                                              128 x 11 recessive bits     */
            CS.in_boff = 0u;
        }
    } else {
        CS.in_boff = 0u;
    }

    /* engine running time (OBD PID 1F) */
    if (trg_rpm != 0u) {
        if ((unsigned int)(ms - CS.run_ms) >= 1000u) {
            CS.run_ms = (unsigned int)(CS.run_ms + 1000u);
            if ((unsigned int)(ms - CS.run_ms) >= 1000u) CS.run_ms = ms;
            if (CS.run_s != 0xFFFFu) CS.run_s++;
        }
    } else {
        CS.run_ms = ms;
        CS.run_s = 0u;
    }

    if (CS.ctx_on && !(csr & CSR_BOFF)) {
        ctx_service(ms);
    }
    if (CS.rx_on) {
        rx_service(ms);
        CS.vss = vss_now(ms);
        /* the crash: checksum-checked, latched until the next boot (a key
           cycle restarts the ECU) */
        if (u8v(CFG_U_CAN_CRASH_CUT) != 0u && rx_fresh(RXI_AIRBAG, ms)) {
            rx_copy(RXI_AIRBAG, d);
            if (hccan_rx_airbag1(d) == 1u) CS.crash = 1u;
        }
    }
    if (CS.wb_fmt != 0u) wb_service(ms);
    if (CS.hx_mode != 0u) hx_service(ms);
    if (CS.obd_on && !(csr & CSR_BOFF)) obd_service(ms);
    if ((unsigned int)(ms - CS.next_ms) < 0x8000u) {
        /* a slot is due. The cadence is anchored to the planned slot, so a
           late pass does not add up; a pass more than one slot late
           re-anchors to now instead of sending a burst. */
        if ((unsigned int)(ms - CS.next_ms) >= 10u) {
            CS.next_ms = (unsigned int)(ms + 10u);
        } else {
            CS.next_ms = (unsigned int)(CS.next_ms + 10u);
        }
        if (CS.vag && !(csr & CSR_BOFF)) {
            eng_state(&e);
            id_state(&id);
            fuel_10ms();
            /* Haldex mode 2: the Haldex is told a fixed rpm (the Motor_1 copy
               sent, never the engine's own value) */
            if (CS.hx_mode == 2u && CS.abs_emu && !CS.abs_susp && trg_rpm != 0u) {
                unsigned int fix = (unsigned int)(u8v(CFG_U_HX_RPM_FIX) * 100u);
                e.rpm = fix ? fix : 2500u;
            }
            hccan_motor1(&e, &id, d);  mo_send(CS.mo[MOI_M1], d);
            e.rpm = trg_rpm;
            vload(&v);
            hccan_motor2(&v, &e, &id, d);  mo_send(CS.mo[MOI_M2], d);
            hccan_motor3(&e, d);       mo_send(CS.mo[MOI_M3], d);
            hccan_motor6(&v, &e, &id, eng_baro_kpa_x10, d);  mo_send(CS.mo[MOI_M6], d);
            if (CS.slot & 1u) {
                hccan_motor5(&v, &e, &id, d);  mo_send(CS.mo[MOI_M5], d);
            }
            vstore(&v);
            CS.slot++;
        }
        if (CS.abs_emu && !(csr & CSR_BOFF)) {
            abs_send();
        }
        if (CS.mo[MOI_WBST] != 0u && !(csr & CSR_BOFF)) {
            /* rusEFI wideband ECU status: battery x10 V, heater allowed
               once the engine runs */
            unsigned int vb = eng_batt_dv;
            d[0] = (unsigned char)(vb > 255u ? 255u : vb);
            d[1] = (unsigned char)(trg_rpm > hc_cal_u16(CFG_CRANK_RPM_MAX) ? 1u : 0u);
            d[2] = 0u; d[3] = 0u; d[4] = 0u; d[5] = 0u; d[6] = 0u; d[7] = 0u;
            mo_send(CS.mo[MOI_WBST], d);
        }
    }
    /* telemetry: 534 state (bit 0 on, 1 engine messages, 2 bus-off now,
       3 error warning, high byte the module's status byte), 536 frames,
       538 late payloads, 540 bus-off events, 542 consumption counter */
    och_c(534u, (unsigned int)(1u | (CS.vag ? 2u : 0u)
                               | ((csr & CSR_BOFF) ? 4u : 0u)
                               | ((csr & CSR_EWRN) ? 8u : 0u)
                               | (csr & 0xFF00u)));
    och_c(536u, CS.tx);
    och_c(538u, CS.late);
    och_c(540u, CS.boffs);
    och_c(542u, CS.v.fuel_ul);
    rx_publish(ms);
    /* 2026-11-04: 1672/1674 CAN wideband lambda 1/2 (x1000, 0 none),
       1676 extension state (bit 0/1 wideband 1/2 fresh, 2 ABS emulation
       sending, 3 ABS emulation suspended - a real ABS is on the bus, 4 OBD
       on, 5 Haldex control active, 6 Allrad_1 fresh, 7 an object did not
       fit; high byte the Haldex status bits), 1678 OBD requests answered,
       1680 Haldex wanted lock (0.1 %), 1682 actual (0.1 %), 1684 rear
       offset (0.1 km/h), 1686 objects used */
    {
        unsigned int st = 0u;
        if (hc_can_lambda(0u)) st |= 0x01u;
        if (hc_can_lambda(1u)) st |= 0x02u;
        if (CS.abs_emu && !CS.abs_susp) st |= 0x04u;
        if (CS.abs_susp) st |= 0x08u;
        if (CS.obd_on) st |= 0x10u;
        if ((CS.hx_mode == 1u || CS.hx_mode == 2u) && CS.abs_emu && !CS.abs_susp) st |= 0x20u;
        if (CS.al_got && (unsigned int)(ms - CS.al_ms) < 500u) st |= 0x40u;
        if (CS.mo_short) st |= 0x80u;
        st |= (unsigned int)CS.al_st << 8;
        och3(1672u, hc_can_lambda(0u));
        och3(1674u, hc_can_lambda(1u));
        och3(1676u, st);
        och3(1678u, CS.obd_reqs);
        och3(1680u, CS.hx_want);
        och3(1682u, CS.al_lock);
        och3(1684u, CS.hx_off);
        och3(1686u, (unsigned int)(CS.mo_next - 1u) + (CS.obd_on ? 1u : 0u));
    }
}
