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
#define HCCJ110_F_CAL          1u   /* UA0 outside ULSUAMN..ULSUAMX          */
#define HCCJ110_F_CHIP         2u   /* UA at the chip-diagnosis level (2 s)  */

/* stock constants, 10-bit counts at 5 V (= the C167 ADC's own units) */
#define HCCJ110_UA0_MIN        287u /* ULSUAMN 1.4014 V                      */
#define HCCJ110_UA0_MAX        328u /* ULSUAMX 1.6016 V                      */
#define HCCJ110_UA0_NOM        307u /* USABGL  1.4990 V: the table's zero     */
#define HCCJ110_UA_DIAG        985u /* SULSUMX 4.81 V                        */
#define HCCJ110_DIAG_MS       2000u /* TVCJLSU 2.0 s                         */
#define HCCJ110_SETTLE_MS      200u
#define HCCJ110_CAL_SAMPLES      8u

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
} hccj110_t;

/* key-on: start in calibration (LA high). */
void hccj110_init(hccj110_t *c);

/* One step. ua = AN6 counts (0..1023); hot = the heater model says the
   sensor is at temperature; dt_ms = time since the previous step. */
void hccj110_step(hccj110_t *c, unsigned int ua, unsigned char hot,
                  unsigned int dt_ms);

/* The stock LALIUS curve: offset-corrected UA counts -> lambda x 1000
   (clamped to the table's ends). Exposed for the test and telemetry. */
unsigned int hccj110_lambda_x1000(unsigned int ua_corr);

#endif
