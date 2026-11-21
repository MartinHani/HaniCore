/*
 * hccj110.h - the analog wideband controller CJ110 (Bosch 30345) + LSU 4.2,
 * as on the ME7.5 DC board (4B0906018DC). SHARED CORE, SFR-FREE.
 *
 * The CJ110 has no SPI (unlike the CJ120 behind hcwb.c): the target hands
 * this core the UA conversion (C167 AN6, 10-bit, 5 V reference) and whether
 * the heater has brought the sensor to temperature, and takes back the LA
 * line (HIGH = the chip's adjustment mode) and lambda. 16-bit arithmetic only.
 *
 * Evidence (.scratch/me75-reverse/WIDEBAND_CJ110.md):
 *   EXACT COMPONENT DATASHEET  the ME7.1.1 schematic set
 *     the Bosch CJ110 datasheet: UA = 0.3 Vccs + 17 x V(shunt 61.9 ohm); LA HIGH =
 *     adjustment mode, LOW/open = measurement; on a chip diagnosis UA is
 *     driven to >= VCC - 0.175 V.
 *   EXACT TARGET BINARY  4B0906018DC: ULSUAMN/ULSUAMX/USABGL = 287/328/307
 *     counts at 0x813A68; LALIUS (UA -> lambda, 22 points) at 0x813A08.
 *     SULSUMX 985 counts and TVCJLSU 2.0 s from the same lineage (X505P).
 *   EXACT TARGET VEHICLE DOCUMENT  1.8T ME7.5 Funktionsrahmen GGLSU 5.30
 *     (funktionsrahmen/Audi_R4-5V_T_132kW_ME7.pdf p441): the
 *     adjustment runs only while UA is plausible (ULSUAMN..ULSUAMX) - an
 *     implausible UA is no fault, the stored correction stays; it runs at
 *     key-on and again after start (TABGS). A cold or MISSING sensor reads
 *     lambda = 1 after the adjustment; readiness is set only once lambda
 *     has left 1 by SDLAB for TSTBB, with the heater active (2026-11-05:
 *     a DC with no LSU fitted read a valid lambda 1.00).
 *     X505P values: SDLAB 0.010, TSTBB 0.20 s, TABGS 5.0 s.
 */
#ifndef HCCJ110_H
#define HCCJ110_H

/* states */
#define HCCJ110_ST_CAL_SETTLE  0u   /* LA high, waiting for UA to settle     */
#define HCCJ110_ST_CAL_SAMPLE  1u   /* LA high, averaging UA0                */
#define HCCJ110_ST_MEASURE     2u   /* LA low, lambda when the sensor is hot */
#define HCCJ110_ST_FAULT       3u   /* latched until hccj110_init()          */

/* latched faults */
#define HCCJ110_F_NONE         0u
#define HCCJ110_F_CAL          1u   /* not raised since 2026-11-05 (GGLSU:
                                       an implausible UA0 only skips it)    */
#define HCCJ110_F_CHIP         2u   /* UA at the chip-diagnosis level (2 s)  */
#define HCCJ110_F_NOSIG        3u   /* hot for HCCJ110_NOSIG_MS and lambda
                                       never left 1: no sensor / no signal  */

/* stock constants, 10-bit counts at 5 V (= the C167 ADC's own units) */
#define HCCJ110_UA0_MIN        287u /* ULSUAMN 1.4014 V                      */
#define HCCJ110_UA0_MAX        328u /* ULSUAMX 1.6016 V                      */
#define HCCJ110_UA0_NOM        307u /* USABGL  1.4990 V: the table's zero     */
#define HCCJ110_UA_DIAG        985u /* SULSUMX 4.81 V                        */
#define HCCJ110_DIAG_MS       2000u /* TVCJLSU 2.0 s                         */
#define HCCJ110_SETTLE_MS      200u
#define HCCJ110_CAL_SAMPLES      8u
#define HCCJ110_SDLAB_X1000     10u /* SDLAB 0.010                           */
#define HCCJ110_TSTBB_MS       200u /* TSTBB 0.20 s                          */
#define HCCJ110_NOSIG_MS     60000u /* judgement: a minute hot, never ready  */

typedef struct {
    unsigned char st;       /* HCCJ110_ST_*                                  */
    unsigned char fcode;    /* HCCJ110_F_*                                   */
    unsigned char la;       /* OUT: drive the CJ110 LA line high             */
    unsigned char valid;    /* OUT: lambda is a measurement                  */
    unsigned int  lambda;   /* OUT: lambda x 1000, 0 when not valid          */
    unsigned int  ua0;      /* calibrated pump-current zero, counts          */
    unsigned int  t_ms;     /* time in the current state / diagnosis timer   */
    unsigned int  sum;      /* calibration accumulator                       */
    unsigned char n;        /* calibration samples taken                     */
    unsigned char cal_ok;   /* a plausible adjustment this key cycle         */
    unsigned char ready;    /* readiness (B_sbblsu): lambda has left 1       */
    unsigned int  rdy_ms;   /* time away from 1 (TSTBB)                      */
    unsigned int  wait_ms;  /* time hot and not ready (NOSIG)                */
} hccj110_t;

/* key-on: start in calibration (LA high). */
void hccj110_init(hccj110_t *c);

/* the adjustment again (after start, TABGS): LA high for one calibration,
   then back to measuring; readiness is kept. Ignored while faulted. */
void hccj110_recal(hccj110_t *c);

/* One step. ua = AN6 counts (0..1023); hot = the heater model says the
   sensor is at temperature; dt_ms = time since the previous step. */
void hccj110_step(hccj110_t *c, unsigned int ua, unsigned char hot,
                  unsigned int dt_ms);

/* The stock LALIUS curve: offset-corrected UA counts -> lambda x 1000
   (clamped to the table's ends). Exposed for the test and telemetry. */
unsigned int hccj110_lambda_x1000(unsigned int ua_corr);

#endif
