/*
 * hcvss.h - vehicle speed from an edge input, and gear detection.
 *
 * SFR-free and host-tested (tests/host/test_hcvss_host.py); built into the
 * target's far module (targets/me711/control/hcvss711.c).
 *
 * SPEED (Bosch GGVFZG pattern, rusEFI / Speeduino conversions - references
 * in the maintainer's design records, no code copied):
 *   the capture interrupt only COUNTS edges and stamps the millisecond of
 *   the last one; this core, called every 20 ms, turns "n edges between two
 *   stamped edges dt ms apart" into km/h:
 *       km/h x10 = edges x k / dt,   k = 36 000 000 / pulses per km
 *   (36e6 = 3600 s/h x 1000 ms/s x 10). The window is at least
 *   HCVSS_WIN_MS so one millisecond of stamp resolution is <= 1 %. With no
 *   edge the speed is bounded by "one edge since the last one" (it falls
 *   smoothly to zero) and is 0 after the timeout (Bosch: 0.8 s).
 *
 * GEAR: from the speed per 1000 rpm (0.01 km/h units) against a per-gear
 *   value, ascending (1st smallest). A gear holds while the ratio stays
 *   inside +/- band % of its value (Bosch BBGANG keeps the last gear inside
 *   its band); otherwise the boundaries are the geometric means of
 *   neighbouring gears (rusEFI GearDetector). 0 = neutral / stopped /
 *   implausible: below the minimum speed, below 400 rpm, below 1st / 1.5 or
 *   above top x 1.5, or gear values not ascending.
 */
#ifndef HCVSS_H
#define HCVSS_H

#ifndef HCVSS_FAR
#define HCVSS_FAR
#endif

#define HCVSS_NONE      0xFFFFu   /* no speed (input off / not configured) */
#define HCVSS_GEARS     8u
#define HCVSS_WIN_MS    100u      /* shortest window a speed is measured over */
#define HCVSS_TMO_MS    800u      /* default: no edge this long = standing */

typedef struct {
    unsigned int  n_prev;     /* edge counter at the window start          */
    unsigned int  ms_prev;    /* stamp of the edge that started the window  */
    unsigned int  raw_x10;    /* last measured speed, 0.1 km/h              */
    unsigned int  f_x10;      /* filtered speed, 0.1 km/h                   */
    unsigned char have;       /* a window start exists                     */
    unsigned char gear;       /* 0 = neutral / unknown, 1..8               */
} hcvss_state_t;

/* reset (input just armed, or the configuration changed) */
void HCVSS_FAR hcvss_reset(hcvss_state_t *s, unsigned int n_now);

/* k for hcvss_step(): 36 000 000 / pulses per km; 0 = unusable
   (fewer than 550 pulses per km - k would not fit 16 bits) */
unsigned int HCVSS_FAR hcvss_k(unsigned int pulses_per_km);

/* one service step. n = the interrupt's edge counter, ms_edge = the
   millisecond of its last edge, now = the millisecond now (all wrapping
   16-bit). filt 0..15 (0 = none; each step moves (16 - filt) / 16 of the
   way), tmo_ms (0 = HCVSS_TMO_MS). Returns the filtered speed, 0.1 km/h,
   or HCVSS_NONE when k is 0. */
unsigned int HCVSS_FAR hcvss_step(hcvss_state_t *s, unsigned int n,
                                  unsigned int ms_edge, unsigned int now,
                                  unsigned int k, unsigned char filt,
                                  unsigned int tmo_ms);

/* speed per 1000 rpm, 0.01 km/h; 0 when it cannot be formed */
unsigned int HCVSS_FAR hcvss_v1000(unsigned int vss_x10, unsigned int rpm);

/* the gear (0 = neutral / unknown). g[] = speed per 1000 rpm of each gear
   (0.01 km/h), ascending; n gears (0 = off); band_pct (0 = 10 %); min_x10 =
   below this speed the gear is 0 (0 = 3.0 km/h). */
unsigned char HCVSS_FAR hcvss_gear(hcvss_state_t *s, unsigned int vss_x10,
                                   unsigned int rpm, const unsigned int *g,
                                   unsigned char n, unsigned char band_pct,
                                   unsigned int min_x10);

#endif
