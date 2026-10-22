/*
 * hctrans.h - transient fuel: the wall film, after-start and warm-up, on the
 * fuel ONE CYLINDER needs PER CYCLE. Target independent, SFR-free, far on
 * ME7.1.1 (HCTRANS_FAR), host-tested (tools/test_hctrans_host.py).
 *
 * WHY ON THE CYCLE'S FUEL (the maintainer's design notes). The scheduler
 * delivers a cycle's open time in one whole pulse (sequential) or two halves
 * (batch, semi-sequential, the sequential fallback). Correcting the CYCLE's
 * requirement means one model serves every injection mode, and the mode
 * switch conserves what this module asks for.
 *
 * THE WALL FILM - the X-tau model (Aquino; rusEFI wall_fuel.cpp):
 *   of every injected mass a fraction X lands on the port wall; the film
 *   gives a fraction alpha of itself to the cylinder each cycle,
 *       alpha = Tc / (tau + Tc),      Tc = one cycle's duration.
 *   To put the wanted mass M in the cylinder the injector must deliver
 *       I = (M - alpha * F) / (1 - X),   F <- F + X*I - alpha*F  per cycle.
 *   Steady state gives I = M exactly (no long-term bias); a step up in M
 *   injects more while the film fills; a step down injects less (to 0)
 *   while it drains; a fuel cut injects nothing and the film evaporates, so
 *   the RE-ENTRY after an overrun cut gets the film's rebuild automatically.
 *   Units: microseconds of injector open time (mass at the flow in force).
 *
 * AFTER-START: extra fuel right after cranking ends, decaying linearly to
 * none over a time (rusEFI postCrankingFactor / postCrankingDurationSec).
 *
 * Everything bounded: F <= FILM_MAX, I in 0..60000 us, no negative mass, no
 * division by a value that can be 0, no Keil long helper (16-bit products
 * into a long, one inline division each).
 */
#ifndef HCTRANS_H
#define HCTRANS_H

#ifdef __C166__
#define HCTRANS_FAR far
#define HCTRANS_MEM huge      /* the state lives in external SRAM on ME7.1.1 */
#else
#define HCTRANS_FAR
#define HCTRANS_MEM
#endif

#define HCTRANS_OUT_MAX   60000u      /* us, the per-cycle ceiling           */
#define HCTRANS_FILM_MAX  60000u      /* us                                  */
#define HCTRANS_X_MAX     900u        /* per mille: X above 90 % refused     */

typedef struct {
    unsigned int film;        /* fuel on the wall, us of open time         */
    unsigned int acc_ms;      /* time towards the next cycle update        */
    unsigned int as_ms;       /* ms since cranking ended (after-start)     */
    unsigned char was_crank;
    unsigned char pad;
    /* telemetry of the last step */
    unsigned int base;        /* what the steady model asked for           */
    unsigned int want;        /* base x after-start                        */
    unsigned int out;         /* what the injector is told (per cycle)     */
    int          corr;        /* out - want, signed (the film's share)     */
    unsigned int alpha;       /* per mille evaporating per cycle           */
    unsigned int as_pm;       /* after-start extra, per mille              */
} hctrans_t;

typedef struct {
    unsigned int base_us;     /* the steady model's open time per cycle    */
    unsigned int rpm;
    unsigned int dt_ms;       /* since the previous step (bounded 0..200)  */
    unsigned char cranking;   /* 1: no transient - the cranking table rules */
    unsigned char cut;        /* 1: a fuel cut - nothing injected          */
    unsigned int x_pm;        /* wall fraction, per mille (0 = no film)    */
    unsigned int tau_ms;      /* film time constant                        */
    unsigned int as_pm;       /* after-start extra at its start, per mille */
    unsigned int as_decay_ms; /* after-start decays to 0 over this         */
} hctrans_in_t;

void HCTRANS_FAR hctrans_reset(hctrans_t HCTRANS_MEM *s);
/* One step. Returns the open time per cycle to deliver (0 in a cut). */
unsigned int HCTRANS_FAR hctrans_step(hctrans_t HCTRANS_MEM *s,
                                      const hctrans_in_t *in);
/* Linear interpolation between (x0, v0) and (x1, v1) at x, clamped to the
   segment (the caller picks the segment of a u8 curve vs a u16 axis - the
   warm-up and transient curves vs coolant live in the page, which the
   target reads). x1 <= x0 returns v0. */
unsigned char HCTRANS_FAR hctrans_lerp8(unsigned int x0, unsigned int x1,
                                        unsigned char v0, unsigned char v1,
                                        unsigned int x);

#endif
