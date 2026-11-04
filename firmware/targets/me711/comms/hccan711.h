/*
 * hccan711.h - the C167 CAN module and the VAG engine messages (2026-11-03).
 * hccan711.c; payloads firmware/comms/hccan.c; settings the page extension
 * (canEnable, canVag, identity). Live data OCH 534..543.
 */
#ifndef HCCAN711_H
#define HCCAN711_H

void far hc_can_init(void);                  /* once at boot, after the page */
void far hc_can_service(unsigned int ms);    /* every main-loop pass         */
unsigned int  far hc_can_vss_x10(void);      /* 0.1 km/h, 0xFFFF = no speed  */
unsigned char far hc_can_crash(void);        /* airbag crash, latched to boot */
/* lambda from a wideband controller on the bus (canWbFormat), x1000;
   0 = none / older than 100 ms (2026-11-04: lambda source 3) */
unsigned int  far hc_can_lambda(unsigned char bank);

#endif
