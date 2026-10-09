/*
 * hclimp711.h - engine protection on ME7.1.1 (FCODE). See hclimp711.c.
 */
#ifndef HCLIMP711_H
#define HCLIMP711_H

#include "hclimp.h"

extern hclimp_t     hc_limp;             /* cut reasons: telemetry, DTCs     */
extern unsigned int hc_limp_duty_x10;    /* the injector duty it judged      */

void far hc_limp_init(void);
/* every main-loop pass with the uptime (tick_ms); decides every 10 ms and owns
   ENG_CUT_LIMP in eng_fuelcut */
void far hc_limp_service(unsigned int now_ms);

#endif
