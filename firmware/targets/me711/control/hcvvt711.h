/*
 * hcvvt711.h - camshaft phase control (VVT) on ME7.1.1: the shared
 * core control/hcvvt.c, the cam PATTERN core's measured position
 * (hccam_bank[b].sync_dev_x10), a target table per cam, and the MAIN CPU's
 * own PWM units POUT0 -> cavity 115 / POUT1 -> cavity 120 (the ME7.1.1 schematic p1:
 * KNWS1_P70 / KNWS2_P71 -> CJ920 low sides with freewheel diodes; the OEM
 * key-on PWM init [BIN 0x8C0D78] 250 Hz). the maintainer's design notes.
 *
 * State in external SRAM (TGT_RAM_VVT): the far XRAM is full. The trigger
 * (hctrig_me711.c) counts the identified tooth-0 edges into syncs[] - the
 * freshness of the position the controller closes on.
 */
#ifndef HCVVT711_H
#define HCVVT711_H

#include "hcvvt.h"

/* latched per cam until the engine stops (then re-armed) */
#define VVT_F_NONE      0u
#define VVT_F_NOFB      1u     /* closed loop, running, no cam position     */
#define VVT_F_SLOW      2u     /* |error| over the limit for too long:
                                  stuck or slow phaser                     */
#define VVT_F_RANGE     3u     /* the cam tooth outside the VVT authority   */
#define VVT_F_ROUTE     4u     /* enabled but no solenoid stage routed      */

typedef struct {
    hcvvt_t       v[2];
    unsigned int  syncs[2];        /* written by the trigger (task context)  */
    unsigned int  seen[2];
    unsigned int  fresh_ms[2];     /* since the last fresh position          */
    unsigned int  err_ms[2];
    int           target[2];       /* 0.1 deg advance                        */
    int           pos[2];          /* 0.1 deg advance (- cam deviation)      */
    unsigned int  pw[2];           /* PWM compare in force, 0 = released     */
    unsigned char fault[2];
    unsigned char unit_on[2];
    unsigned int  acc_ms, last_ms;
    unsigned char have_ms, pad;
} hc_vvt711_t;

#define HC_VVT711 (*(hc_vvt711_t huge *)(TGT_EXTRAM_BASE + TGT_RAM_VVT))

void far hc_vvt_init(void);
void far hc_vvt_service(unsigned int now_ms);
/* the latched fault of cam b (hcdtc711.c) */
unsigned char far hc_vvt_fault(unsigned char b);
/* '!D' (2026-10-15): both phasers re-armed, as at an engine stop */
void far hc_vvt_clear_faults(void);

#endif
