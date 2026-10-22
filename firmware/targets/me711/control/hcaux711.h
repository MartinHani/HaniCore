/*
 * hcaux711.h - the auxiliary functions on ME7.1.1 (2026-10-14):
 *
 *   cooling fan      on at fanOnTemp, off at fanOffTemp (hysteresis), with
 *                    the A/C compressor (fanWithAc), off while cranking and
 *                    optionally with the engine stopped (fanStoppedOff); a
 *                    failed coolant sensor runs the fan (rusEFI FanControl)
 *   A/C              request switch (pinAcRequest, acRequestActive) ->
 *                    compressor relay (pinAcClutch) after acDelay, only
 *                    with the engine running between acMinRpm and acMaxRpm,
 *                    below acMaxTps and acMaxClt; the request raises the
 *                    idle floor by acIdleUpX10 and the idle target by
 *                    acIdleRpm (hcidle711.c)
 *   outputs 1 / 2    Speeduino "programmable outputs": condition A and an
 *                    optional B (a source, above / below a threshold, a
 *                    hysteresis), AND / OR, an on delay
 *   oil pressure     pinOilPress (any analog cavity this ECU reads: main
 *                    ADC or S5500), a linear sensor (oilSensLoMv -> 0 kPa,
 *                    oilSensHiMv -> oilSensHiKpa); feeds the protection in
 *                    hclimp711.c (control/hclimp.c, rusEFI limp manager)
 *
 * OUTPUTS: the CPU's spare low sides, cavity 115 (P7.0/POUT0) and 120
 * (P7.1/POUT1) through the CJ920 - the stages the cam solenoids use, so a
 * routed VVT owns them instead (the validator refuses two owners). ON = the
 * pin an OUTPUT at LOW (the CJ920 inverts, as hcvvt711.c's PWM: stage on
 * while the pin is low); OFF = released (input), the stage's own bias is
 * off. Permission: the ALWAYS set (page valid, S5500 link, key on - as the
 * fuel pump); not while a bench output test runs.
 *
 * FCODE (MOD167 MEDIUM, hcfarbridge.h first); the state is in external SRAM
 * (TGT_RAM_AUX) - the far modules' XRAM is full.
 */
#ifndef HCAUX711_H
#define HCAUX711_H

/* auxStatus (OCH 1660) */
#define AUX_S_FAN       0x0001u
#define AUX_S_AC_REQ    0x0002u   /* the request switch is active          */
#define AUX_S_AC_ON     0x0004u   /* compressor relay commanded on         */
#define AUX_S_GP1       0x0008u
#define AUX_S_GP2       0x0010u
#define AUX_S_OIL_OK    0x0020u   /* oil pressure reading valid            */
#define AUX_S_HOLD      0x0040u   /* outputs not permitted (key off, page,
                                     S5500 link) or a bench test runs      */
#define AUX_S_OIL_ROUTED 0x0080u  /* an oil pressure sensor is configured  */
/* bits 8..11 carry the A/C why (below); 12..13 the rail pressure sensor */
#define AUX_S_FUEL_OK    0x1000u  /* fuel rail pressure reading valid      */
#define AUX_S_FUEL_ROUTED 0x2000u /* a rail pressure sensor is configured  */
/* why the compressor is off while requested, bits 8..11 (OCH 1660) */
#define AUX_AC_WHY_SHIFT 8u
#define AUX_AC_WHY_NONE  0u
#define AUX_AC_WHY_STOP  1u       /* engine not running / below acMinRpm   */
#define AUX_AC_WHY_RPM   2u       /* above acMaxRpm                        */
#define AUX_AC_WHY_TPS   3u       /* above acMaxTps                        */
#define AUX_AC_WHY_CLT   4u       /* above acMaxClt, or coolant failed     */
#define AUX_AC_WHY_DELAY 5u       /* waiting acDelay                       */

typedef struct {
    unsigned int  last_ms;
    unsigned int  acc_ms;
    unsigned int  run_ms;         /* engine running, ms (saturates)         */
    unsigned int  run_s;          /* engine running, s                      */
    unsigned int  ac_ms;          /* request held                           */
    unsigned int  gp_ms[2];       /* conditions held                        */
    unsigned int  oil_kpa;
    unsigned int  fuel_kpa;       /* rail above the atmosphere (sensed mode) */
    unsigned int  status;         /* AUX_S_* | why << 8                     */
    unsigned char have_ms;
    unsigned char cond[2];        /* hysteresis memory: bit0 A, bit1 B      */
    unsigned char on;             /* bit0 fan, 1 A/C, 2 out 1, 3 out 2      */
    unsigned char drv;            /* bit0 cavity 115, bit1 120: this module
                                     owns the pin (releases it on a move)   */
} hc_aux711_t;

#define HC_AUX711 (*(hc_aux711_t huge *)(TGT_EXTRAM_BASE + TGT_RAM_AUX))

void         far hc_aux_init(void);
void         far hc_aux_service(unsigned int now_ms);   /* hc_idle_service */
unsigned int far hc_aux_idle_up_x10(void);   /* throttle %, 0.1 */
unsigned int far hc_aux_idle_rpm(void);      /* target rpm added */
unsigned int far hc_aux_oil_kpa(void);
unsigned char far hc_aux_oil_ok(void);
/* the rail pressure sensor (injPressMode 3): kPa above the atmosphere,
   and whether that is a valid reading now */
unsigned int far hc_aux_fuel_kpa(void);
unsigned char far hc_aux_fuel_ok(void);

#endif
