/*
 * hccan.c - the VAG drivetrain CAN engine messages, no hardware (2026-11-03).
 * See hccan.h. Bit positions: .scratch/can-bus/VAG_PQ_MESSAGES.md section 2.
 *
 * Built into the far module hccan711.c (MOD167 MEDIUM) and, alone, by the
 * host test with gcc. No library helper may be pulled in from far code:
 * multiplications are int x int -> long, divisions go through DIV32U with a
 * quotient bounded to 16 bits by a clamp in front of it.
 */
#include "hccan.h"

#ifndef DIV32U
#define DIV32U(n, d)  ((unsigned int)((unsigned long)(n) / (unsigned int)(d)))
#endif

/* 0.390625 % (100/256) per bit: raw = x10 * 256 / 1000 = x10 * 32 / 125 */
static unsigned char pct_byte(unsigned int x10)
{
    if (x10 > 9920u) {
        return 0xFEu;                       /* 0xFF is "error" on the bus  */
    }
    return (unsigned char)DIV32U((unsigned long)x10 * 32u, 125u);
}

unsigned char HCCAN_FAR hccan_temp_byte(unsigned int dc, unsigned char bad)
{
    /* dc = (C + 1000) x 10; raw = (C + 48) / 0.75 = (C x 10 + 480) x 2 / 15 */
    unsigned int v;
    if (bad) {
        return 0xFFu;
    }
    if (dc < 10000u - 480u) {
        return 0u;                          /* below -48 C                 */
    }
    v = (unsigned int)(dc - (10000u - 480u));          /* (C + 48) x 10   */
    if (v > 1905u) {
        return 0xFEu;                       /* above 142.5 C               */
    }
    return (unsigned char)DIV32U((unsigned long)v * 2u, 15u);
}

void HCCAN_FAR hccan_vag_reset(hccan_vag_state_t *s)
{
    s->mux2 = 0u;
    s->mux5 = 0u;
    s->fuel_ul = 0u;
    s->fuel_ovf = 0u;
    s->ctr6 = 0u;
}

/* the full-load torque, 0.1 % of MDNORM */
static unsigned int max_x10(const hccan_vag_id_t *id)
{
    if (id->mdnorm_nm == 0u) {
        return 0u;
    }
    if ((unsigned long)id->mdmax_nm * 1000u >= (unsigned long)id->mdnorm_nm * 2500u) {
        return 2500u;
    }
    return DIV32U((unsigned long)id->mdmax_nm * 1000u, id->mdnorm_nm);
}

unsigned int HCCAN_FAR hccan_torque_x10(const hccan_eng_t *e,
                                        const hccan_vag_id_t *id)
{
    /* The stock 1.8T's KFMIOP gives ~53 % of its 400 Nm MDNORM at rl 100 %
       (a2l_me75_torque_model.txt) = 212 Nm, 0.922 of its 230 Nm maximum.
       So: torque = rl x 0.922 x MDMAX, as a share of MDNORM. A first cut
       until the KFMIOP / ETADZW model (spec issue 04): it carries no spark
       efficiency, so a retard does not lower it. */
    unsigned int t;
    if (id->mdnorm_nm == 0u || e->rpm == 0u) {
        return 0u;
    }
    t = DIV32U((unsigned long)(e->rl_x10 > 3000u ? 3000u : e->rl_x10)
               * id->mdmax_nm, 1000u);                   /* Nm at rl, <= 6000 */
    /* 0.1 % of MDNORM = Nm x 0.922 x 1000 / MDNORM */
    if ((unsigned long)t * 922u >= (unsigned long)id->mdnorm_nm * 2500u) {
        return 2500u;
    }
    return DIV32U((unsigned long)t * 922u, id->mdnorm_nm);
}

void HCCAN_FAR hccan_motor1(const hccan_eng_t *e, const hccan_vag_id_t *id,
                            unsigned char *d)
{
    unsigned int f = e->flags, tq, rpm4, fric, wish, mx;
    unsigned char b = 0u;

    if (f & HCCAN_F_IDLE)      b |= 0x01u;    /* B_ll                      */
    if (f & HCCAN_F_PEDAL_BAD) b |= 0x02u;    /* E_fp                      */
    if (e->pedal_x10 >= 950u && !(f & HCCAN_F_PEDAL_BAD))
        b |= 0x04u;                           /* kickdown above 95 %       */
    /* bit 3 clutch, bit 4 brake-message timeout: 0 (not received)        */
    b |= 0x20u;    /* B_statbr: brake (ASR/MSR) torque requests not served */
    b |= 0x40u;    /* B_statgec: gearbox torque requests not served        */
    if (f & HCCAN_F_TQ_BAD)    b |= 0x80u;    /* B_statmdc                 */
    d[0] = b;

    tq = hccan_torque_x10(e, id);
    d[1] = (f & HCCAN_F_CUT) ? 0u : pct_byte(tq);       /* miistc          */
    rpm4 = (e->rpm > 16383u) ? 0xFFFCu : (unsigned int)(e->rpm * 4u);
    d[2] = (unsigned char)(rpm4 & 0xFFu);                /* nmot_w, 0.25 rpm */
    d[3] = (unsigned char)(rpm4 >> 8);
    d[4] = pct_byte(tq);                                 /* mifab           */
    d[5] = (f & HCCAN_F_PEDAL_BAD) ? 0xFFu
         : (unsigned char)((e->pedal_x10 > 1000u ? 1000u : e->pedal_x10) / 4u);
    /* friction (mdverlc): 3 % + 1 % per 1500 rpm of MDNORM - judgement
       until the KFMDS map lands (issue 04) */
    fric = (e->rpm == 0u) ? 0u : (unsigned int)(30u + e->rpm / 150u);
    d[6] = pct_byte(fric);
    /* driver's wish (mivbeg): the pedal's share of the full-load torque */
    mx = max_x10(id);
    wish = DIV32U((unsigned long)(e->pedal_x10 > 1000u ? 1000u : e->pedal_x10)
                  * mx, 1000u);
    d[7] = pct_byte(wish);
}

void HCCAN_FAR hccan_motor2(hccan_vag_state_t *s, const hccan_eng_t *e,
                            const hccan_vag_id_t *id, unsigned char *d)
{
    unsigned int f = e->flags, v, tq;
    unsigned char code = (unsigned char)(s->mux2 >> 2), info, b = 0u;

    switch (code) {                    /* each code 4 times in a row (FR)  */
    case 0u:  info = id->canvers; break;
    case 1u:  info = id->fmotc; break;
    case 2u:  info = id->cwgc; break;
    default:  v = id->mdnorm_nm / 10u; info = (unsigned char)(v > 63u ? 63u : v);
              break;
    }
    if (info > 63u) info = 63u;
    d[0] = (unsigned char)(info | (unsigned char)(code << 6));
    s->mux2 = (unsigned char)((s->mux2 + 1u) & 0x0Fu);

    d[1] = hccan_temp_byte(e->clt_dc, (unsigned char)((f & HCCAN_F_CLT_BAD) != 0u));
    if (f & HCCAN_F_BRAKE)      b |= 0x03u;  /* brake light + brake test  */
    if (f & HCCAN_F_CLT_BAD)    b |= 0x04u;  /* E_tm                      */
    if (f & HCCAN_F_RUNNING)    b |= 0x10u;  /* B_statnb normal operation */
    if (f & HCCAN_F_DTC_STORED) b |= 0x20u;
    d[2] = b;                                /* bits 22..23 cruise: off   */
    /* vehicle speed, 1.28 km/h: 0.1 km/h x 10 / 128 */
    v = (e->vss_x10 > 3250u) ? 3250u : e->vss_x10;
    d[3] = (unsigned char)DIV32U((unsigned long)v * 10u, 128u);
    d[4] = 0u;                               /* cruise set speed          */
    v = e->idle_rpm / 10u;
    d[5] = (unsigned char)(v > 254u ? 254u : v);          /* nstat, 10 rpm */
    d[6] = pct_byte(max_x10(id));                         /* mimax         */
    tq = hccan_torque_x10(e, id);
    d[7] = pct_byte((unsigned int)(tq - tq / 4u));        /* mizwmn: 75 %  */
}

void HCCAN_FAR hccan_motor3(const hccan_eng_t *e, unsigned char *d)
{
    unsigned int f = e->flags;
    unsigned char b = 0u;

    if (f & HCCAN_F_PEDAL_BAD) b |= 0x10u;
    if (f & HCCAN_F_TPS_BAD)   b |= 0x20u;
    /* bit 6: ECU locked by the immobiliser - 0                             */
    if (f & HCCAN_F_IAT_BAD)   b |= 0x80u;
    d[0] = b;
    d[1] = hccan_temp_byte(e->iat_dc, (unsigned char)((f & HCCAN_F_IAT_BAD) != 0u));
    d[2] = (f & HCCAN_F_PEDAL_BAD) ? 0xFFu
         : (unsigned char)((e->pedal_x10 > 1000u ? 1000u : e->pedal_x10) / 4u);
    d[3] = 0u;                               /* wheel wish torque (AT): 0 */
    b = 0x80u;                               /* bit 39: no start-stop     */
    if (f & HCCAN_F_NO_DBW)    b |= 0x40u;   /* bit 38: no E-gas          */
    d[4] = b;
    d[5] = 0u;                               /* shift-speed influence     */
    d[6] = 0u;                               /* engine wish speed         */
    d[7] = (f & HCCAN_F_TPS_BAD) ? 0xFFu
         : (unsigned char)((e->tps_x10 > 1000u ? 1000u : e->tps_x10) / 4u);
}

void HCCAN_FAR hccan_motor6(hccan_vag_state_t *s, const hccan_eng_t *e,
                            const hccan_vag_id_t *id, unsigned int baro_x10,
                            unsigned char *d)
{
    unsigned int tq = hccan_torque_x10(e, id), alt;
    unsigned char t = (e->flags & HCCAN_F_CUT) ? 0u : pct_byte(tq);

    d[1] = t;                      /* target inner torque for the gearbox   */
    d[2] = t;                      /* actual inner torque for the gearbox   */
    /* altitude factor, 1.0 = 0x80 (0.0078 per bit): baro / 101.3 kPa */
    if (baro_x10 == 0u || baro_x10 > 1300u) {
        alt = 0x80u;
    } else {
        alt = DIV32U((unsigned long)baro_x10 * 128u, 1013u);
    }
    d[3] = (unsigned char)(alt > 255u ? 255u : alt);
    d[4] = 0xA6u;                  /* cruise target acceleration: 0 m/s2    */
    d[5] = 0u;
    d[6] = 0u;
    d[7] = (unsigned char)((s->ctr6 & 0x0Fu) << 4);   /* counter, bits 60..63 */
    s->ctr6 = (unsigned char)((s->ctr6 + 1u) & 0x0Fu);
    d[0] = (unsigned char)(d[1] ^ d[2] ^ d[3] ^ d[4] ^ d[5] ^ d[6] ^ d[7]);
}

void HCCAN_FAR hccan_fuel_add(hccan_vag_state_t *s, unsigned int ul)
{
    unsigned int n = (unsigned int)((s->fuel_ul + ul) & 0x7FFFu);
    if (n < s->fuel_ul || ul > 0x7FFFu) {
        s->fuel_ovf = 1u;
    }
    s->fuel_ul = n;
}

void HCCAN_FAR hccan_motor5(hccan_vag_state_t *s, const hccan_eng_t *e,
                            const hccan_vag_id_t *id, unsigned char *d)
{
    unsigned int f = e->flags, v;
    unsigned char code = (unsigned char)(s->mux5 >> 2), info, b = 0u, x;
    unsigned char dbl = (unsigned char)(id->mdnorm_nm > 630u);

    switch (code) {
    case 0u:  v = dbl ? id->mdmax_nm / 20u : id->mdmax_nm / 10u; break;
    case 1u:  v = id->nmdmax_rpm / 100u; break;
    case 2u:  v = id->mottyp; break;
    default:  v = id->kvnpz / 20u; break;
    }
    info = (unsigned char)(v > 63u ? 63u : v);
    d[0] = (unsigned char)(info | (unsigned char)(code << 6));
    s->mux5 = (unsigned char)((s->mux5 + 1u) & 0x0Fu);

    if (f & HCCAN_F_EPC) b |= 0x04u;          /* bit 10 EPC lamp          */
    if (f & HCCAN_F_MIL) b |= 0x08u;          /* bit 11 MIL               */
    if (f & HCCAN_F_HOT) b |= 0x10u;          /* bit 12 overheat lamp     */
    d[1] = b;
    d[2] = (unsigned char)(s->fuel_ul & 0xFFu);           /* bits 16..23   */
    d[3] = (unsigned char)(((s->fuel_ul >> 8) & 0x7Fu)    /* bits 24..30   */
                           | (s->fuel_ovf ? 0x80u : 0u)); /* bit 31        */
    v = (unsigned int)e->fan_pct * 10u / 4u;              /* 0.4 %         */
    d[4] = (unsigned char)(v > 254u ? 254u : v);
    d[5] = 0u;
    b = 0u;
    if (f & HCCAN_F_STOPPED) b |= 0x01u;      /* bit 48 starter enable    */
    if (f & HCCAN_F_RUNNING) b |= 0x02u;      /* bit 49 starter disengage */
    if (dbl)                 b |= 0x08u;      /* bit 51 double torque     */
    d[6] = b;
    x = (unsigned char)(d[0] ^ d[1] ^ d[2] ^ d[3] ^ d[4] ^ d[5] ^ d[6]);
    d[7] = x;                                 /* XOR of bytes 0..6 (FR)   */
}

/* ================================================= RECEIVE (2026-11-03) == */
/* 15-bit speeds in 0.01 km/h -> 0.1 km/h */
static unsigned int kmh_x10(unsigned int raw15)
{
    return (unsigned int)(raw15 / 10u);
}

void HCCAN_FAR hccan_rx_bremse1(const unsigned char *d, hccan_bremse1_t *o)
{
    /* bits 17..31: byte 2 bits 1..7 (7 bits) + byte 3 (8 bits) */
    unsigned int raw = (unsigned int)(((unsigned int)d[2] >> 1)
                                      | ((unsigned int)d[3] << 7));
    o->vss_x10 = kmh_x10(raw);
    o->asr_req = (unsigned char)(d[0] & 0x01u);
    o->msr_req = (unsigned char)((d[0] >> 1) & 0x01u);
    o->brake = (unsigned char)((d[1] >> 3) & 0x01u);          /* bit 11 */
    o->asr_slow = d[4];
    o->asr_fast = d[5];
    o->msr = d[6];
    o->counter = (unsigned char)(d[7] & 0x0Fu);               /* 56..59 */
    o->esp_off = (unsigned char)((d[7] >> 5) & 0x01u);        /* bit 61 */
}

void HCCAN_FAR hccan_rx_bremse3(const unsigned char *d, unsigned int *w4)
{
    /* each wheel: bits 1..15 of its 16-bit word (bit 0 = direction / quality) */
    w4[0] = kmh_x10((unsigned int)(((unsigned int)d[0] >> 1) | ((unsigned int)d[1] << 7)));
    w4[1] = kmh_x10((unsigned int)(((unsigned int)d[2] >> 1) | ((unsigned int)d[3] << 7)));
    w4[2] = kmh_x10((unsigned int)(((unsigned int)d[4] >> 1) | ((unsigned int)d[5] << 7)));
    w4[3] = kmh_x10((unsigned int)(((unsigned int)d[6] >> 1) | ((unsigned int)d[7] << 7)));
}

void HCCAN_FAR hccan_rx_getriebe1(const unsigned char *d, hccan_getriebe1_t *o)
{
    o->ac_off = (unsigned char)((d[0] >> 2) & 0x01u);
    o->tq_valid = (unsigned char)((d[0] >> 7) & 0x01u);
    o->gear = (unsigned char)(d[1] & 0x0Fu);                  /* 8..11 */
    o->selector = (unsigned char)(d[1] >> 4);                 /* 12..15 */
    o->tq_req = d[3];                                         /* 24..31 */
    o->cooling = (unsigned char)((d[5] >> 4) & 0x03u);        /* 44..45 */
    o->mil = (unsigned char)((d[5] >> 7) & 0x01u);            /* 47 */
}

void HCCAN_FAR hccan_rx_kombi1(const unsigned char *d, hccan_kombi1_t *o)
{
    /* speed bits 25..39: byte 3 bits 1..7 + byte 4 (8 bits) */
    unsigned int raw = (unsigned int)(((unsigned int)d[3] >> 1)
                                      | ((unsigned int)d[4] << 7));
    o->vss_x10 = kmh_x10(raw);
    o->oil_warn = (unsigned char)(((d[0] >> 2) | (d[0] >> 3)) & 0x01u);
    o->clt_low = (unsigned char)((d[0] >> 4) & 0x01u);
    o->fuel_l = (unsigned char)(d[2] & 0x7Fu);                /* 16..22 */
    o->fuel_low = (unsigned char)(d[2] >> 7);                 /* 23 */
}

void HCCAN_FAR hccan_rx_kombi2(const unsigned char *d, unsigned int *amb_dc,
                               unsigned int *oil_dc)
{
    /* ambient: raw x 0.5 - 50 C -> (C + 1000) x 10 = raw x 5 + 9500 */
    *amb_dc = (unsigned int)((unsigned int)d[1] * 5u + 9500u);
    /* oil: raw - 60 C -> raw x 10 + 9400 */
    *oil_dc = (unsigned int)((unsigned int)d[3] * 10u + 9400u);
}

unsigned char HCCAN_FAR hccan_rx_airbag1(const unsigned char *d)
{
    if ((unsigned char)(d[0] ^ d[1] ^ d[2] ^ d[3]) != 0u) {
        return 2u;                            /* checksum: never a crash */
    }
    return (unsigned char)((d[0] & 0x80u) ? 1u : 0u);
}

void HCCAN_FAR hccan_rx_klima1(const unsigned char *d, hccan_klima1_t *o)
{
    o->idle_up = (unsigned char)(d[0] & 0x01u);
    o->compressor = (unsigned char)((d[0] >> 4) & 0x01u);
    o->load_x4 = d[3];                                        /* 24..31 */
    o->fan_x4 = d[5];                                         /* 40..47 */
    o->ac_switch = (unsigned char)((d[6] >> 1) & 0x01u);      /* 49 */
}

/* ======================== 2026-11-04: emulation, wideband, Haldex, OBD == */
/* 0.1 km/h -> the 15-bit 0.01 km/h field, saturated */
static unsigned int kmh_raw15(unsigned int x10)
{
    if (x10 > 3276u) {
        x10 = 3276u;
    }
    return (unsigned int)(x10 * 10u);
}

void HCCAN_FAR hccan_tx_bremse1(unsigned int vss_x10, unsigned char brake,
                                unsigned char ctr, unsigned char *d)
{
    unsigned int raw = kmh_raw15(vss_x10);
    unsigned char i;
    for (i = 0u; i < 8u; i++) {
        d[i] = 0u;
    }
    d[1] = (unsigned char)(brake ? 0x08u : 0u);               /* bit 11 */
    d[2] = (unsigned char)((raw & 0x7Fu) << 1);               /* bits 17..23 */
    d[3] = (unsigned char)(raw >> 7);                         /* bits 24..31 */
    d[7] = (unsigned char)(ctr & 0x0Fu);                      /* 56..59 */
}

void HCCAN_FAR hccan_tx_bremse3(const unsigned int *w4, unsigned char *d)
{
    unsigned char i;
    for (i = 0u; i < 4u; i++) {
        unsigned int raw = kmh_raw15(w4[i]);
        d[2u * i] = (unsigned char)((raw & 0x7Fu) << 1);      /* bit 0 = 0 */
        d[2u * i + 1u] = (unsigned char)(raw >> 7);
    }
}

void HCCAN_FAR hccan_rx_allrad1(const unsigned char *d, unsigned int *lock_x10,
                                unsigned char *status)
{
    /* rear clutch stiffness: byte 4, 0.7874 % per bit (100 / 127) */
    *lock_x10 = DIV32U((unsigned long)d[4] * 1000u, 127u);
    if (*lock_x10 > 1000u) {
        *lock_x10 = 1000u;
    }
    *status = (unsigned char)(d[0] & 0x7Fu);
}

unsigned int HCCAN_FAR hccan_rx_wb_rusefi(const unsigned char *d)
{
    unsigned int raw;
    if (d[0] < HCCAN_WB_VERSION || d[0] > HCCAN_WB_VERSION || !(d[1] & 1u)) {
        return 0u;
    }
    raw = (unsigned int)((unsigned int)d[2] | ((unsigned int)d[3] << 8));
    return (unsigned int)((raw + 5u) / 10u);
}

unsigned int HCCAN_FAR hccan_rx_wb_aem(const unsigned char *d)
{
    unsigned int raw;
    if (!(d[6] & 0x80u) || (d[7] & 0x40u)) {
        return 0u;
    }
    raw = (unsigned int)(((unsigned int)d[0] << 8) | (unsigned int)d[1]);
    return (unsigned int)((raw + 5u) / 10u);
}

void HCCAN_FAR hccan_hx_reset(hccan_hx_t *h)
{
    h->integ_x100 = 0;
}

unsigned int HCCAN_FAR hccan_hx_offset(hccan_hx_t *h, unsigned int want_x10,
                                       unsigned int act_x10,
                                       unsigned char act_ok,
                                       unsigned int no_x10, unsigned int full_x10,
                                       unsigned char kp100, unsigned char ki100,
                                       unsigned char deadband_pct,
                                       unsigned int dt_ms)
{
    unsigned int ff, e, p = 0u, d_i;
    unsigned char neg;
    int out;

    if (want_x10 > 1000u) {
        want_x10 = 1000u;
    }
    /* feed-forward: between the 0 % and the 100 % offset */
    if (full_x10 >= no_x10) {
        ff = (unsigned int)(no_x10
                            + DIV32U((unsigned long)(full_x10 - no_x10) * want_x10, 1000u));
    } else {
        ff = (unsigned int)(no_x10
                            - DIV32U((unsigned long)(no_x10 - full_x10) * want_x10, 1000u));
    }
    if (act_ok) {
        neg = (unsigned char)(act_x10 > want_x10);
        e = neg ? (unsigned int)(act_x10 - want_x10) : (unsigned int)(want_x10 - act_x10);
        if (e > (unsigned int)deadband_pct * 10u) {
            p = DIV32U((unsigned long)kp100 * e, 10u);              /* 0.01 km/h */
            if (p > 6000u) {
                p = 6000u;
            }
            if (dt_ms > 200u) {
                dt_ms = 200u;
            }
            /* ki x e x dt / 10000 in two int x int -> long steps */
            d_i = DIV32U((unsigned long)ki100 * e, 100u);           /* <= 2550 */
            d_i = DIV32U((unsigned long)d_i * dt_ms, 100u);
            if (neg) {
                h->integ_x100 = (int)(h->integ_x100 - (int)d_i);
                if (h->integ_x100 < -3000) h->integ_x100 = -3000;
            } else {
                h->integ_x100 = (int)(h->integ_x100 + (int)d_i);
                if (h->integ_x100 > 3000) h->integ_x100 = 3000;
            }
        } else {
            neg = 0u;
        }
    } else {
        neg = 0u;
    }
    if (ff > 600u) {
        ff = 600u;
    }
    out = (int)(ff * 10u) + h->integ_x100 + (neg ? -(int)p : (int)p);
    if (out < 0) {
        out = 0;
    }
    if (out > 6000) {
        out = 6000;
    }
    return (unsigned int)((unsigned int)out / 10u);
}

/* ---------------------------------------------------------------- OBD-II */
static unsigned char obd_byte(unsigned int x10_pct)      /* 0.1 % -> A*100/255 */
{
    if (x10_pct >= 1000u) {
        return 255u;
    }
    return (unsigned char)DIV32U((unsigned long)x10_pct * 255u + 500u, 1000u);
}

static unsigned char obd_temp(unsigned int dc)            /* 0.1 C + 1000 C -> A - 40 */
{
    unsigned int c;
    if (dc < 10000u - 400u) {
        return 0u;
    }
    c = (unsigned int)((dc - (10000u - 400u)) / 10u);         /* C + 40 */
    return (unsigned char)(c > 255u ? 255u : c);
}

unsigned char HCCAN_FAR hccan_obd_pid(unsigned char pid, const hccan_obd_t *o,
                                      unsigned char *out)
{
    unsigned int v;
    switch (pid) {
    case 0x00u:   /* 01 04 05 0B 0C 0D 0E 0F 11 1C 1F 20 */
        out[0] = 0x98u; out[1] = 0x3Eu; out[2] = 0x80u; out[3] = 0x13u;
        return 4u;
    case 0x01u:
        out[0] = (unsigned char)((o->mil ? 0x80u : 0u)
                                 | (o->n_dtc > 127u ? 127u : o->n_dtc));
        out[1] = 0u; out[2] = 0u; out[3] = 0u;
        return 4u;
    case 0x04u:
        out[0] = obd_byte(o->load_x10);
        return 1u;
    case 0x05u:
        out[0] = obd_temp(o->clt_dc);
        return 1u;
    case 0x0Bu:
        v = (unsigned int)((o->map_x10 + 5u) / 10u);
        out[0] = (unsigned char)(v > 255u ? 255u : v);
        return 1u;
    case 0x0Cu:
        v = (o->rpm > 16383u) ? 65535u : (unsigned int)(o->rpm * 4u);
        out[0] = (unsigned char)(v >> 8); out[1] = (unsigned char)(v & 0xFFu);
        return 2u;
    case 0x0Du:
        v = (o->vss_x10 == 0xFFFFu) ? 0u : (unsigned int)((o->vss_x10 + 5u) / 10u);
        out[0] = (unsigned char)(v > 255u ? 255u : v);
        return 1u;
    case 0x0Eu: {
        int a = o->adv_x10 / 5 + 128;      /* (deg + 64) x 2 */
        out[0] = (unsigned char)(a < 0 ? 0 : (a > 255 ? 255 : a));
        return 1u;
    }
    case 0x0Fu:
        out[0] = obd_temp(o->iat_dc);
        return 1u;
    case 0x11u:
        out[0] = obd_byte(o->tps_x10);
        return 1u;
    case 0x1Cu:
        out[0] = 5u;                       /* not OBD compliant */
        return 1u;
    case 0x1Fu:
        out[0] = (unsigned char)(o->run_s >> 8); out[1] = (unsigned char)(o->run_s & 0xFFu);
        return 2u;
    case 0x20u:   /* 33 34 40 */
        out[0] = 0u; out[1] = 0u; out[2] = 0x30u; out[3] = 0x01u;
        return 4u;
    case 0x33u:
        v = (unsigned int)((o->baro_x10 + 5u) / 10u);
        out[0] = (unsigned char)(v > 255u ? 255u : v);
        return 1u;
    case 0x34u:
        if (o->lam_x1000 == 0u) {
            return 0u;
        }
        v = (o->lam_x1000 >= 2000u) ? 65535u
            : DIV32U((unsigned long)o->lam_x1000 * 32768u, 1000u);
        out[0] = (unsigned char)(v >> 8); out[1] = (unsigned char)(v & 0xFFu);
        out[2] = 0x80u; out[3] = 0u;       /* current: 0 mA */
        return 4u;
    case 0x40u:   /* 42 51 */
        out[0] = 0x40u; out[1] = 0u; out[2] = 0x80u; out[3] = 0u;
        return 4u;
    case 0x42u:
        out[0] = (unsigned char)(o->vbat_mv >> 8); out[1] = (unsigned char)(o->vbat_mv & 0xFFu);
        return 2u;
    case 0x51u:
        out[0] = 1u;                       /* gasoline */
        return 1u;
    default:
        return 0u;
    }
}
