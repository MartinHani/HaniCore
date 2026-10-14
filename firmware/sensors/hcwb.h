/*
 * hcwb.h - the onboard wideband (CJ120 + LSU 4.2): calibration, heater state
 * machine, pump-current enable and lambda validity. SHARED CORE, SFR-FREE.
 *
 * Like hckline.c this module never touches a register: the target hands it
 * what the CJ120 answered and what the converters read, and takes back the
 * INIT_REG1 mode the chip must hold, the heater duty and lambda. The same
 * object compiles into the C167 image (hcio711.c calls it) and into the host
 * test tests/host/test_hcwb.c on gcc - so every state, fault and timing
 * below is exercised deterministically without a sensor, an engine or a
 * bench. 16-bit arithmetic only (far code on the C167: no long helpers).
 *
 * The design and its evidence: docs/ARCHITECTURE.md.
 */
#ifndef HCWB_H
#define HCWB_H

/* CJ120 INIT_REG1 = x PA x RA x LA x VL (the Bosch CJ120 datasheet p6).
   PA IS ACTIVE LOW: PA = 0 pumps, PA = 1 holds the pump current off.
   PHYSICAL EXACT (AWT car, 2026-10-10, VEHICLE_CAPTURE_..154357Z/154904Z):
   a hot LSU (Ri held at 82.5 ohm, READY) read UA = the pump zero (308 vs
   307) for minutes in 0xC8; the moment the core fell back to 0x88 the same
   hot sensor in free air read UA 556 (Ip ~ +2.4 mA = air) and decayed as it
   cooled. SOFTWARE REFERENCE: rusEFI cj125.h "PA - Pump Current Control -
   Set to 0 to be active", normal mode 0x88. V96..V102 had it inverted:
   lambda was never a measurement (lambda ~ 1.01 = Ip 0). */
#define HCWB_PA            0x40u
#define HCWB_RA            0x10u
#define HCWB_LA            0x04u
#define HCWB_MODE_COLD     0xC8u   /* + PA: pump current held OFF (cold)    */
#define HCWB_MODE_PUMP     0x88u   /* PA = 0: pump current ON (sensor hot)  */
#define HCWB_MODE_CAL      0x9Cu   /* RA + LA: the calibration (bench-proven
                                      UA0 307 / URcal 187; LA makes UA the
                                      Ip = 0 point whatever the pump does)  */

/* heater states (lambdaStatus bits 2..4 / 5..7) */
#define HCWB_ST_OFF        0u
#define HCWB_ST_WAIT       1u
#define HCWB_ST_PREHEAT    2u
#define HCWB_ST_RAMP       3u
#define HCWB_ST_CLOSED     4u
#define HCWB_ST_READY      5u
#define HCWB_ST_FAULT      6u

/* latched faults (OCH 862: low byte bank 1, high byte bank 2) */
#define HCWB_F_NONE        0u
#define HCWB_F_HEATER_GND  1u   /* CJ120 DIAG heater 00: short to ground    */
#define HCWB_F_HEATER_OPEN 2u   /* 01: open load - no heater / no sensor     */
#define HCWB_F_HEATER_UB   3u   /* 10: short to battery                      */
#define HCWB_F_LINE_IAIP   4u   /* sensor pump lines shorted                 */
#define HCWB_F_LINE_UN     5u   /* Nernst line shorted                       */
#define HCWB_F_LINE_VM     6u   /* virtual ground shorted                    */
#define HCWB_F_CHIP        7u   /* CJ120 never verified (IDENT / INIT_REG1)  */
#define HCWB_F_CAL         8u   /* pump zero or Ri reference out of spec     */
#define HCWB_F_NO_HEAT     9u   /* not at temperature within 60 s            */
#define HCWB_F_OVERHEAT   10u   /* Ri < 0.70 x reference for 0.5 s           */
#define HCWB_F_UNDERHEAT  11u   /* Ri > 2.60 x reference for 0.5 s           */
#define HCWB_F_NO_RI      12u   /* UR (ASIC AN12/13) not readable            */
#define HCWB_F_OPEN_CELL  13u   /* Legacy name/number: UR stayed railed through
                                  commanded heating. An open cell is one
                                  possible cause, not a proven diagnosis.
                                  Actual H+ and heater current are not inputs;
                                  missing physical heating can look the same. */

/* WHY lambda is not a measurement right now (OCH 1010, low byte bank 1,
   high byte bank 2). Not latched - recomputed every step - so a log row says
   what withheld that row's lambda; the latched fault stays in fcode. */
#define HCWB_WHY_VALID     0u   /* lambda is a measurement                   */
#define HCWB_WHY_OFF       1u   /* source not on-board, or key off           */
#define HCWB_WHY_FAULT     2u   /* latched fault (fcode) until key-off or a
                                   trouble-code clear (hcwb_clear)          */
#define HCWB_WHY_CHIP      3u   /* CJ120 not verified (no answer / IDENT)    */
#define HCWB_WHY_CAL       4u   /* key-on calibration running                */
#define HCWB_WHY_ENGINE    5u   /* waiting: engine not running               */
#define HCWB_WHY_SUPPLY    6u   /* waiting: supply outside 9.5..23 V         */
#define HCWB_WHY_PREHEAT   7u   /* condensation preheat (2 V)                */
#define HCWB_WHY_RAMP      8u   /* heating ramp 7 -> 12 V                    */
#define HCWB_WHY_SETTLE    9u   /* closed loop, Ri not yet stable 3 s        */
#define HCWB_WHY_PUMP     10u   /* pump current not verified ON for 1 s      */
#define HCWB_WHY_DIAG     11u   /* CJ120 DIAG not clean                      */
#define HCWB_WHY_UA       12u   /* UA outside the amplifier swing: pump
                                   current saturated / line fault           */
#define HCWB_WHY_UR       13u   /* Ri signal (UR) not tagged by the ASIC ADC */
#define HCWB_WHY_HOLD     14u   /* a bench mode hold owns the chip           */
#define HCWB_WHY_STUCK    15u   /* V99 (ME7.1.1 hcevlog711.c): READY, but the
                                   pump-current signal has not moved for 30 s
                                   of running - withdrawn, not a measurement */
#define HCWB_WHY_HELD     16u   /* 2026-10-10: lambda is the LAST measurement,
                                   HELD through an acquisition gap (< 600 ms,
                                   hcwb.c GAP_HOLD_MS; valid == 2). Shown, but
                                   nothing may learn from it (STFT, VE/WUE
                                   Analyze use only fresh samples, valid 1). */

/* HEATER POLICY (page `lambdaHeatPolicy`, and the one thing the target
   must turn into hcwb_in_t.heat_allow).
   rusEFI heater_control.cpp has NO engine-running term: GetNextState() takes
   a HeaterAllow (Unknown / Allowed / NotAllowed) plus the supply voltage, and
   HeaterAllow::Unknown PERMITS heating - a wideband warms as soon as it has
   power. V96..V99 required `trg_rpm != 0 && trg_state >= TRG_SYNC_CRANK`,
   which is both unlike the reference and useless for tuning: the sensor can
   only become READY ~40 s into a run that never lasted that long on the car.
   IGNITION is therefore the default and the recommended workflow. */
#define HCWB_HEAT_OFF      0u   /* never heat (a narrowband / no sensor)     */
#define HCWB_HEAT_IGNITION 1u   /* key on - warm before the start (default)  */
#define HCWB_HEAT_RUNNING  2u   /* only while the engine turns (V99's rule,
                                   kept for an unheated-exhaust install; the
                                   afterrun stops a stall discarding it)    */

/* calibration states */
#define HCWB_CAL_NEED      0u
#define HCWB_CAL_SETTLE    1u
#define HCWB_CAL_SAMPLE    2u
#define HCWB_CAL_OK        3u
#define HCWB_CAL_BAD       4u

/* the Ri reference: R1076 / R1056 = 82.5 ohm (the ME7.1.1 schematic) */
#define HCWB_RCAL_X10      825u
#define HCWB_UR_NONE       0xFFFFu

/* Acquisition contract: mode is the acknowledged mode that generated this
   conversion, never the requested mode. valid includes completed conversion,
   matching channel and bounded age. seq advances only on acquisition. */
typedef struct {
    unsigned int seq;
    unsigned char mode, valid;
} hcwb_sample_t;

/* One bank's inputs for one step (the target fills it every main-loop pass). */
typedef struct {
    unsigned int  ms;          /* free-running millisecond clock             */
    unsigned int  ua;          /* CJ120 UA, raw 10-bit (MAIN AN6 / AN4)      */
    unsigned int  ur;          /* CJ120 UR, raw 10-bit (ASIC AN12 / AN13) or
                                  HCWB_UR_NONE when the ADC did not tag it   */
    unsigned int  vbatt_dv;    /* supply, 0.1 V                              */
    unsigned char en;          /* lambda source = on-board CJ120             */
    unsigned char key_on;      /* KL15 on (run-on RUN)                       */
    unsigned char running;     /* engine turning under crank sync            */
    unsigned char heat_allow;  /* selected policy requests heating; the core
                                  additionally gates voltage and run-tail
                                  ownership, never a reusable timestamp     */
    unsigned char afterrun;    /* policy permits a bounded running afterrun */
    hcwb_sample_t ua_sample, ur_sample;
    unsigned char chip_ok;     /* IDENT verified and INIT_REG1 read back     */
    unsigned char reg1;        /* the INIT_REG1 the chip last read back      */
    unsigned char diag;        /* the CJ120 DIAG register                    */
    unsigned char hold;        /* a bench mode hold owns the chip            */
    unsigned char hold_mode;   /* ... and the mode it wants                  */
} hcwb_in_t;

typedef struct {
    /* outputs. valid: 0 not a measurement, 1 a FRESH measurement, 2 the
       last measurement HELD through an acquisition gap (why HCWB_WHY_HELD) */
    unsigned char state, fcode, want, veff_dv, valid;
    unsigned int  duty_x10;    /* heater duty, 0.1 %                         */
    unsigned int  lambda;      /* x1000, 0 = not a measurement               */
    unsigned int  ri_x10;      /* 0 = not computable, 60000 = open / cold    */
    unsigned int  ua0, urc;    /* calibration: pump zero, Ri reference (raw) */
    unsigned char cal_st, cal_why;
    unsigned char why;         /* HCWB_WHY_*, recomputed every step     */
    unsigned int  pa_ms;       /* pump verified ON for this long             */
    int           ip_ua;       /* pump current, uA (+ lean, - rich) from
                                  UA - UA0; the RAW measurement, published
                                  whether or not lambda is valid; 0 until the
                                  calibration is OK or with UA out of swing  */
    /* internal */
    unsigned char cal_n, ur_miss, supply_ok;
    int           integ;       /* 0.1 mV                                     */
    unsigned int  last_ms, mark, step, chip_mark, cal_mark, supply_mark;
    unsigned int  ur_seen, over_mark, under_mark, ready_ms, ua_sum, ur_sum;
    unsigned char started;
    unsigned int  diag_mark;   /* a DIAG failure has persisted since (was the
                                  unused V100 run_mark: same size, XRAM full) */
    unsigned char ur_live;     /* qualified UR has left its rail this warm-up */
    unsigned char permission;  /* 0 expired/never granted, 1 allowed, 2 tail */
    unsigned int tail_ms, cal_seq, cal_ua_seq;
} hcwb_t;

void hcwb_init(hcwb_t *w);
void hcwb_step(hcwb_t *w, const hcwb_in_t *in);
/* A trouble-code clear: a latched fault is forgotten and the bank starts
   again from the key-on calibration (a real fault latches again). */
void hcwb_clear(hcwb_t *w);

/* BOTH BANKS, the glue that was target code. Bank b (0 = bank 1,
   cavities 70/51/71/52 + heater 5; 1 = bank 2, 13/12/14/15 + heater 4) gets
   only its own chip / converter inputs; the supply, key, engine and bench
   hold are shared (one ECU). Each bank is an independent hcwb_t: nothing a
   bank does - fault, calibration, heater - reaches the other. */
typedef struct {
    unsigned int  ms, vbatt_dv;
    unsigned char en_mask;     /* bit b: bank b's source is the on-board CJ120 */
    unsigned char key_on, running, hold, hold_mode;
    unsigned char heat_allow;  /* the heater policy's verdict (shared) */
    unsigned char afterrun;
    hcwb_sample_t ua_sample[2], ur_sample[2];
    unsigned int  ua[2], ur[2];
    unsigned char chip_ok[2], reg1[2], diag[2];
} hcwb_pair_in_t;

/* Steps both banks; returns lambdaStatus (OCH 738): bit 0/1 bank valid,
   bits 2..4 / 5..7 heater state, bit 8/9 chip verified, bit 10/11 READY,
   bit 12/13 pump ON (PA verified), bit 14/15 calibration OK. */
unsigned int hcwb_pair_step(hcwb_t w[2], const hcwb_pair_in_t *in);

/* Ip (uA) -> lambda x1000, LSU 4.2, clamped 0.700..2.000 */
unsigned int hcwb_lambda_ip(int ip_ua);
/* the V79..V95 fixed-zero conversion (1.5 V = Ip 0), kept for the gates */
unsigned int hcwb_lambda_raw(unsigned int ua_raw);
/* Ri (0.1 ohm) from UR against the reference measurement */
unsigned int hcwb_ri_x10(unsigned int ur, unsigned int urc);

/* Passive activity telemetry only. Historical field names alive/stuck
   denote variation observed/sustained low variation. Neither certifies
   sensor response; stable healthy exhaust and noisy failed sensors exist.
   Never gate lambda validity, STFT or VE acceptance on these bits.
   Invalid acquisition resets this advisory history. */
#define HCWB_DYN_WIN_MS   5000u
#define HCWB_DYN_ALIVE      12u
#define HCWB_DYN_FROZEN      3u
#define HCWB_DYN_FROZEN_N    6u
#define HCWB_DYN_RECOVER     8u

typedef struct {
    unsigned int  t0, umin, umax, span;
    unsigned char alive, stuck, frozen, on;
} hcwb_dyn_t;

/* -> 1 for sustained low variation (advisory only) */
unsigned char hcwb_dyn_step(hcwb_dyn_t *d, unsigned char valid,
                                     unsigned int ua, unsigned char running,
                                     unsigned int ms);

#endif /* HCWB_H */
