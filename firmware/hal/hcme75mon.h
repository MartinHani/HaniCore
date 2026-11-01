/*
 * hcme75mon.h - the ME7.5 DC's 68HC05K0 monitor (S5500 position): the
 * question/answer protocol on P2.5. SHARED CORE, SFR-FREE, NON-BLOCKING.
 *
 * P2.5 is one open-drain line. After a startup silence the ECU and the
 * monitor take turns in 20 ms slots: the ECU answers at the start of a TX
 * slot with a LOW pulse, the monitor asks with a LOW pulse whose WIDTH is the
 * question (16 bands) - any time after that answer and before the next TX
 * slot. Answers go through a two-deep pipeline (a question is answered two
 * TX slots later): ASync1 then ASync2 first, the defined-invalid width when
 * a frame brought no valid question.
 *
 * The target captures both edges of P2.5 (CC5) and calls hcme75mon_edge();
 * it calls hcme75mon_poll() at least every ms and, when it returns 1, drives
 * P2.5 LOW for *width ticks (a compare ends the pulse - never a busy wait).
 * When the pulse has ended and the line is released it calls
 * hcme75mon_listen(); edges before that (our own pulse) are ignored.
 *
 * BENCH (4B0906018DC, 2026-11-01): with an 18-slot startup the monitor reset
 * the ECU every 118 ms, before the first answer - its synchronisation timeout
 * is ~90..120 ms after reset (the archived Aug 2026 bench notes measured the
 * same: reset at 127 ms with 18 slots, a first answer ~57 ms after boot ran
 * without resets). The target therefore starts this core at the top of boot.
 *
 * Units: ticks of a 1.5 MHz timer (fCPU/16 at 24 MHz) - the 05.12 values.
 * Evidence: archive/me75_target_2026-10-06/tools/wd_ref/wd_table_0512.py
 * (extracted from 06A906032HS seg89:1D26, the 05.12 image the owner ran on
 * this 4B0906018DC) and the archived responder Interrupts.c that ran on the
 * DC (blocking - this core keeps its logic, not its waits).
 */
#ifndef HCME75MON_H
#define HCME75MON_H

#define HCME75MON_FRAME        0x754Cu  /* 20 ms slot                      */
#define HCME75MON_START_FRAMES 2u       /* startup silence: 2 slots ...    */
#define HCME75MON_START_REM    0x5DD6u  /* ... + 16 ms = first answer ~56 ms */
#define HCME75MON_ASYNC        0x1C36u  /* ASync1, the first answer        */
#define HCME75MON_ASYNC2       0x2150u  /* ASync2, the second              */
#define HCME75MON_INVALID      0x17C1u  /* the 05.12 DEFAULT_RESPONSE: a
                                           frame without a valid question  */
#define HCME75MON_WIN_LO       0x1872u  /* a question below this: invalid  */
#define HCME75MON_WIN_HI       0x38AEu  /* at or above this: invalid       */
#define HCME75MON_BAND_NONE    16u

#define HCME75MON_PH_START     0u
#define HCME75MON_PH_TX        1u
#define HCME75MON_PH_RX        2u

typedef struct {
    unsigned char phase;
    unsigned char frames;       /* startup slots counted                   */
    unsigned char sent;         /* this TX slot's pulse already started    */
    unsigned char got_q;        /* a valid question in this RX slot        */
    unsigned char low;          /* a falling edge is pending               */
    unsigned char listen;       /* our pulse is over: edges are questions  */
    unsigned char last_q;       /* last band, HCME75MON_BAND_NONE invalid  */
    unsigned int  t0;           /* start of the current slot / wait        */
    unsigned int  fall_t;
    unsigned int  cur;          /* the width the next TX slot sends        */
    unsigned int  next;         /* the width after that                    */
    unsigned int  answers, asyncs, invalid, timeouts;   /* telemetry       */
} hcme75mon_t;

void hcme75mon_init(hcme75mon_t *m, unsigned int now);

/* Our answer has ended and the line is released: questions from now. */
void hcme75mon_listen(hcme75mon_t *m);

/* A P2.5 edge: high = level after the edge, t = its capture time. */
void hcme75mon_edge(hcme75mon_t *m, unsigned char high, unsigned int t);

/* Returns 1 and *width when a LOW pulse must start now. */
unsigned char hcme75mon_poll(hcme75mon_t *m, unsigned int now,
                             unsigned int *width);

/* The question band of a LOW width, HCME75MON_BAND_NONE when invalid. */
unsigned char hcme75mon_band(unsigned int width);

/* The answer width of a band (0..15). */
unsigned int hcme75mon_response(unsigned char band);

#endif
