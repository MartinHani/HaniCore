/*
 * hclimp.h - engine protection / limp decisions (V97, SFR-free,
 * host-tested). Each protection is a FUEL cut, with its own reason bit;
 * the target ORs "any" into its fuel-cut word.
 *
 * rusEFI limp_manager.cpp is the model (SOFTWARE REFERENCE):
 *   coolant       rusEFI cltRevLimitRpm (a curve): above clt_max the rev
 *                 limit drops to clt_rpm (a fuel cut above it, 200 rpm
 *                 hysteresis like the V93 rev limiter)
 *   ETB fault     reportEtbJammed(): a 1500 rpm fault rev limit
 *                 (etb_rpm; the plate is on its limp spring)
 *   oil           minOilPressureAfterStart (no pressure within 5 s of
 *                 starting) and enableOilPressureProtect (below the
 *                 minimum above oil_rpm for oil_ms): fuel cut, LATCHED
 *                 until the engine stops
 *   injector duty maxInjectorDutyInstant / Sustained(+Timeout): cut, and
 *                 released only below 20 % (rusEFI's hysteresis)
 *   flood clear   isCylinderCleanupEnabled: not running and the pedal
 *                 above 90 % -> no fuel while cranking
 *
 * A protection whose threshold is 0 is off. An input that is not a
 * measurement (sensor fault / not fitted) never trips its protection - it
 * cannot be judged; the DTC layer reports the sensor instead.
 */
#ifndef HCLIMP_H
#define HCLIMP_H

#ifdef __C166__
#define HCLIMP_FAR far
#else
#define HCLIMP_FAR
#endif

typedef struct {
    int           clt_max_x10;     /* deg C x10; 0 = off                    */
    unsigned int  clt_rpm;         /* rev limit while hot                   */
    unsigned int  etb_rpm;         /* rev limit on an ETB fault; 0 = off    */
    unsigned int  oil_min_kpa;     /* 0 = off                               */
    unsigned int  oil_rpm;         /* the minimum applies above this        */
    unsigned int  oil_ms;          /* below the minimum this long           */
    unsigned int  oil_start_ms;    /* pressure must appear within this      */
    unsigned int  duty_inst_x10;   /* 0 = off                               */
    unsigned int  duty_sust_x10;   /* 0 = off                               */
    unsigned int  duty_sust_ms;
    unsigned int  flood_x10;       /* pedal for flood clear; 0 = off        */
} hclimp_cfg_t;

typedef struct {
    unsigned int  rpm;
    unsigned char cranking;
    int           clt_x10;
    unsigned char clt_ok;
    unsigned int  oil_kpa;
    unsigned char oil_ok;
    unsigned char etb_fault;
    unsigned int  duty_x10;        /* injector duty the fuel model requests */
    unsigned int  pedal_x10;
} hclimp_in_t;

#define HCLIMP_CLT    0x01u
#define HCLIMP_ETB    0x02u
#define HCLIMP_OIL    0x04u
#define HCLIMP_DUTY   0x08u
#define HCLIMP_FLOOD  0x10u

#define HCLIMP_HYST_RPM 200u

typedef struct {
    unsigned char cut;             /* HCLIMP_* bits active now              */
    unsigned int  run_ms;          /* since the engine started running      */
    unsigned int  low_ms;          /* oil below the minimum                 */
    unsigned int  sust_ms;         /* duty above the sustained limit        */
    unsigned char had_oil;         /* pressure seen since the start         */
} hclimp_t;

void HCLIMP_FAR hclimp_reset(hclimp_t *l);
/* returns the HCLIMP_* bits: any set = fuel cut */
unsigned char HCLIMP_FAR hclimp_step(hclimp_t *l, const hclimp_cfg_t *c,
                                     const hclimp_in_t *in, unsigned int ms);

#endif
