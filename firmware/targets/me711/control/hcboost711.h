/*
 * hcboost711.h - boost control on ME7.1.1 (FCODE). See hcboost711.c.
 */
#ifndef HCBOOST711_H
#define HCBOOST711_H

#include "hcldr.h"

extern hcldr_t      hc_ldr;              /* the core's state: telemetry     */
extern unsigned int hc_ldr_target_x10;   /* last target, 0.1 kPa            */
extern unsigned int hc_ldr_open_x10;     /* last open-loop duty, 0.1 %      */

void far hc_boost_init(void);
/* every main-loop pass with the uptime (tick_ms); steps the controller every
   20 ms, sets/clears ENG_CUT_BOOST and returns the valve duty (0.1 %) */
unsigned int far hc_boost_service(unsigned int now_ms, unsigned char keyoff);

#endif
