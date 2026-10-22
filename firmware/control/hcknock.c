/*
 * hcknock.c - the knock-control strategy core. See hcknock.h for the
 * strategy and its sources; tests/host/test_hcknock.c for the proof;
 * the maintainer's design notes for the hardware it will sit behind.
 *
 * 16-bit arithmetic only. Every bound that makes a product fit is stated
 * where the product is formed; ikr is clamped to 1023 on entry, so every
 * reference is <= 1023 counts (ref16 <= 16368, r4 <= 4092).
 */
#include "hcknock.h"

#define IKR_MAX   1023u
#define REF16_MAX (IKR_MAX * 16u)

unsigned int HCKNOCK_FAR hcknock_thr4(unsigned int r4, unsigned char kef16)
{
    /* floor(r4 * kef16 / 16) = r4*kh + floor(r4*kl/16), kef16 = 16kh + kl:
       r4 <= 4092, kh <= 15, kl <= 15 -> 61380 + 3836 = 65216 < 65536 */
    if (r4 > 4092u) r4 = 4092u;
    return r4 * (unsigned int)(kef16 >> 4) + ((r4 * (unsigned int)(kef16 & 15u)) >> 4);
}

static unsigned char kef_at(const hcknock_cfg_t HCKNOCK_MEM *cfg, unsigned int rpm)
{
    unsigned char i;
    unsigned int d, x, frac;
    unsigned char k0, k1;

    if (rpm <= cfg->kef_rpm[0]) return cfg->kef16[0];
    for (i = 1u; i < HCKNOCK_KEFN; i++) {
        if (rpm < cfg->kef_rpm[i]) break;
    }
    if (i == HCKNOCK_KEFN) return cfg->kef16[HCKNOCK_KEFN - 1u];
    d = cfg->kef_rpm[i] - cfg->kef_rpm[i - 1u];
    x = rpm - cfg->kef_rpm[i - 1u];          /* 0 <= x < d                   */
    while (d > 255u) { d >>= 1; x >>= 1; }   /* same ratio, d fits a byte    */
    if (d == 0u) return cfg->kef16[i];
    frac = (x << 8) / d;                     /* x <= 255 -> <= 65280; < 256  */
    k0 = cfg->kef16[i - 1u];
    k1 = cfg->kef16[i];
    /* (k difference <= 255) * (frac < 256) < 65536 */
    if (k1 >= k0) return (unsigned char)(k0 + (((unsigned int)(k1 - k0) * frac) >> 8));
    return (unsigned char)(k0 - (((unsigned int)(k0 - k1) * frac) >> 8));
}

unsigned char HCKNOCK_FAR hcknock_check(const hcknock_cfg_t HCKNOCK_MEM *cfg)
{
    unsigned char i;

    if (cfg->cyls < 1u || cfg->cyls > HCKNOCK_CYL) return HCKNOCK_E_CYLS;
    for (i = 0u; i < cfg->cyls; i++) {
        if (cfg->sensor[i] >= HCKNOCK_SENS) return HCKNOCK_E_SENSOR;
    }
    if (cfg->tp < 1u || cfg->tp > 32u || cfg->tp_dyn < 1u || cfg->tp_dyn > 32u)
        return HCKNOCK_E_TP;
    for (i = 0u; i < HCKNOCK_KEFN; i++) {
        if (cfg->kef16[i] < 16u) return HCKNOCK_E_KEF;
        if (i && cfg->kef_rpm[i] < cfg->kef_rpm[i - 1u]) return HCKNOCK_E_KEF;
    }
    if (cfg->kef_dyn16 < 16u || cfg->kef_dyn16 > 32u) return HCKNOCK_E_KEF;
    if (cfg->step_q < 1u || cfg->max_q < cfg->step_q) return HCKNOCK_E_RETARD;
    if (cfg->reapply_ms < 1u) return HCKNOCK_E_REAPPLY;
    if (cfg->ref_init > IKR_MAX || cfg->ref_max > IKR_MAX || cfg->ref_min > cfg->ref_max)
        return HCKNOCK_E_REF;
    return 0u;
}

void HCKNOCK_FAR hcknock_reset(hcknock_t HCKNOCK_MEM *k,
                              const hcknock_cfg_t HCKNOCK_MEM *cfg)
{
    unsigned char i;
    unsigned int init = cfg->ref_init > IKR_MAX ? IKR_MAX : cfg->ref_init;

    for (i = 0u; i < HCKNOCK_CYL; i++) {
        k->ref16[i] = init * 16u;
        k->rem[i] = 0;
        k->seen[i] = 0u;
        k->ret_q[i] = 0u;
        k->quiet_ms[i] = 0u;
        k->level16[i] = 0u;
        k->kcount[i] = 0u;
        k->maxrun[i] = 0u;
    }
    k->stop = 0u;
    for (i = 0u; i < HCKNOCK_SENS; i++) k->bad[i] = 0u;
    k->knocks = 0u;
    k->at_max = 0u;
    k->fault = 0u;
    k->fault_hi = 0u;
    k->active = 0u;
}

/* ref16 += (x16 - ref16) / tp, exactly: the remainder is carried, so the
   reference reaches its target (a truncating filter stalls up to tp/16
   counts short - the V89 filt() defect class). |acc| <= 16368 + 31. */
static void learn(hcknock_t HCKNOCK_MEM *k, unsigned char cyl, unsigned int ikr, unsigned char tp)
{
    int acc = (int)(ikr * 16u) - (int)k->ref16[cyl] + (int)k->rem[cyl];
    int step;

    if (acc >= 0) step = acc / (int)tp;
    else          step = -((-acc) / (int)tp);   /* C89: no sign-rounding rule */
    k->rem[cyl] = (signed char)(acc - step * (int)tp);
    k->ref16[cyl] = (unsigned int)((int)k->ref16[cyl] + step);
}

static void diagnose(hcknock_t HCKNOCK_MEM *k,
                     const hcknock_cfg_t HCKNOCK_MEM *cfg, unsigned char cyl,
                     unsigned int rpm)
{
    unsigned char s = cfg->sensor[cyl];
    unsigned char mask = (unsigned char)(1u << s);
    unsigned int r = k->ref16[cyl] >> 4;

    if (cfg->diag_n == 0u || rpm < cfg->diag_rpm) return;
    if (r >= cfg->ref_min && r <= cfg->ref_max) {
        k->bad[s] = 0u;
        return;
    }
    if (k->bad[s] < 255u) k->bad[s]++;
    if (k->bad[s] >= cfg->diag_n) {
        k->fault |= mask;
        if (r > cfg->ref_max) k->fault_hi |= mask;
    }
}

unsigned char HCKNOCK_FAR hcknock_ignition(hcknock_t HCKNOCK_MEM *k,
                                           const hcknock_cfg_t HCKNOCK_MEM *cfg,
                                           unsigned char cyl, const hcknock_in_t *in)
{
    unsigned int ikr, r4, lvl;
    unsigned char kef, tp;

    if (cyl >= cfg->cyls || cyl >= HCKNOCK_CYL) return 0u;
    ikr = in->ikr > IKR_MAX ? IKR_MAX : in->ikr;

    r4 = k->ref16[cyl] >> 2;                          /* <= 4092              */
    lvl = r4 ? (ikr * 64u) / r4 : 255u;               /* ikr*64 <= 65472      */
    k->level16[cyl] = (unsigned char)(lvl > 255u ? 255u : lvl);

    k->active = (unsigned char)(in->rpm >= cfg->rpm_min && in->load >= cfg->load_min
                                && in->clt >= cfg->clt_min);
    if (!k->active) return 0u;

    tp = in->dyn ? cfg->tp_dyn : cfg->tp;
    if (k->seen[cyl] < cfg->learn) {                  /* settling: learn only */
        k->seen[cyl]++;
        learn(k, cyl, ikr, tp);
        return 0u;
    }

    kef = kef_at(cfg, in->rpm);
    if (in->dyn) {                                    /* 255 * 32 = 8160      */
        unsigned int kd = ((unsigned int)kef * cfg->kef_dyn16) >> 4;
        kef = (unsigned char)(kd > 255u ? 255u : kd);
    }
    if (ikr * 4u > hcknock_thr4(r4, kef)) {           /* ikr*4 <= 4092        */
        k->knocks++;
        if (k->kcount[cyl] < 255u) k->kcount[cyl]++;
        if (k->ret_q[cyl] >= cfg->max_q) {
            k->at_max++;
            k->ret_q[cyl] = cfg->max_q;
            if (k->maxrun[cyl] < 255u) k->maxrun[cyl]++;
            if (cfg->stop_n && k->maxrun[cyl] >= cfg->stop_n)
                k->stop |= (unsigned char)(1u << cyl);
        } else {
            unsigned int n = (unsigned int)k->ret_q[cyl] + cfg->step_q;
            k->ret_q[cyl] = (unsigned char)(n > cfg->max_q ? cfg->max_q : n);
        }
        k->quiet_ms[cyl] = 0u;
        return 1u;                                    /* never learns a knock */
    }
    k->maxrun[cyl] = 0u;
    learn(k, cyl, ikr, tp);
    diagnose(k, cfg, cyl, in->rpm);
    return 0u;
}

void HCKNOCK_FAR hcknock_tick(hcknock_t HCKNOCK_MEM *k,
                             const hcknock_cfg_t HCKNOCK_MEM *cfg, unsigned int ms)
{
    unsigned char i;

    for (i = 0u; i < cfg->cyls && i < HCKNOCK_CYL; i++) {
        if (k->ret_q[i] == 0u) {
            k->quiet_ms[i] = 0u;
            continue;
        }
        k->quiet_ms[i] = (k->quiet_ms[i] > 65535u - ms) ? 65535u : k->quiet_ms[i] + ms;
        while (k->ret_q[i] && k->quiet_ms[i] >= cfg->reapply_ms) {
            k->ret_q[i]--;
            k->quiet_ms[i] -= cfg->reapply_ms;
        }
        if (k->ret_q[i] == 0u) k->quiet_ms[i] = 0u;
    }
}

unsigned char HCKNOCK_FAR hcknock_retard(const hcknock_t HCKNOCK_MEM *k,
                                         const hcknock_cfg_t HCKNOCK_MEM *cfg,
                                         unsigned char cyl)
{
    unsigned char r;

    if (cyl >= cfg->cyls || cyl >= HCKNOCK_CYL) return 0u;
    r = k->ret_q[cyl];
    if ((k->fault >> cfg->sensor[cyl]) & 1u) {
        if (cfg->safe_q > r) r = cfg->safe_q;
    }
    return r;
}
