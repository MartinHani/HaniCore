/*
 * hcidle711.h - idle speed control on ME7.1.1 (FCODE). See hcidle711.c.
 */
#ifndef HCIDLE711_H
#define HCIDLE711_H

#include "hcidle.h"

extern hcidle_t     hc_idl;               /* the core's state: telemetry     */
extern unsigned int hc_idle_floor_x10;    /* the throttle floor hc_dbw.c uses */
extern unsigned int hc_idle_target_rpm;   /* last target from the CLT curve  */

void far hc_idle_init(void);
/* every main-loop pass with the uptime (tick_ms); steps every 20 ms */
void far hc_idle_service(unsigned int now_ms);
/* the idle ignition-timing correction, 0.1 deg (+ = advance); 0
   outside closed-loop idle. Added by hc_ign_corr_x10() while running. */
int far hc_idle_timing_x10(void);

#endif
