/*
 * hcdtc711.h - diagnostic trouble codes on ME7.1.1 (FCODE). See hcdtc711.c.
 */
#ifndef HCDTC711_H
#define HCDTC711_H

#include "hcdtc.h"

/* the core's state, in external SRAM (TGT_RAM_DTC) */
#define hc_dtc (*(hcdtc_t huge *)(TGT_EXTRAM_BASE + TGT_RAM_DTC))
extern unsigned int  hc_dtc_list[8];    /* active 0..3, stored 4..7       */
extern unsigned char hc_dtc_clear_req;   /* set by '!D', taken by the service */

void far hc_dtc_init(void);
/* every main-loop pass with the uptime (tick_ms); evaluates every 100 ms */
void far hc_dtc_service(unsigned int now_ms);
/* THE CHECK-ENGINE LAMP (diagnostics/hccel.c): the key-on lamp test
   (celTestEnable / OnMs / GapMs), then the MIL request; drives cavity 47
   (ASIC P7.0) when celEnable and pinMil = 47 (docs/ARCHITECTURE.md). */
void far hc_cel_service(unsigned int now_ms, unsigned char key_on);
unsigned int far hc_cel_state(void);   /* mode | cmd << 8 | mil << 9 */
unsigned char far hc_dtc_n(void);
/* the k-th code whose status has a bit of mask (HCDTC_S_*), 0 = none */
unsigned int far hc_dtc_code(unsigned char mask, unsigned char k);

#endif
