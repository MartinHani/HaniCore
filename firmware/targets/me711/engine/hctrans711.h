/*
 * hctrans711.h - the ME7.1.1 side of transient fuel (engine/hctrans.c):
 * page curves, time base, telemetry. FAR (FCODE). V97.
 */
#ifndef HCTRANS711_H
#define HCTRANS711_H

#include "hctrans.h"

/* THE STATE LIVES IN EXTERNAL SRAM (TGT_RAM_TRANS): the on-chip XRAM that
   holds the far modules' data is full. */
typedef struct {
    hctrans_t m;
    unsigned int t_last, t_rem;       /* the T1 time base                  */
} hc_trans711_t;
#define HC_TRANS711 (*(hc_trans711_t huge *)(TGT_EXTRAM_BASE + TGT_RAM_TRANS))
#define hc_trans    (HC_TRANS711.m)

void          far hc_trans_init(void);
/* The per-cycle open time the steady model wants -> what to deliver. Called
   by eng_service() once per main-loop pass; steps on its own T1 time base. */
unsigned int  far hc_trans_fuel(unsigned int base_us, unsigned char cranking,
                                unsigned char cut);
/* The warm-up enrichment at this coolant, INTERPOLATED over the page's
   16-point curve (%, 100 = none; a 0 cell reads 100). */
unsigned char far hc_trans_warmup(unsigned int clt_dc);

#endif
