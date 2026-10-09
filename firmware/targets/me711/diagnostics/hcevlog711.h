/*
 * hcevlog711.h - V99: the engine event ring + lambda dynamics (FAR code,
 * hcevlog711.c). Event records are exported after the boot history in the
 * extended output-channel window (TGT_EV_EXPORT_BYTES); the vehicle test
 * tool (tools/me711_vehicle_test.py) decodes them by these numbers.
 */
#ifndef HCEVLOG711_H
#define HCEVLOG711_H

#define EV_N            90u      /* records in the ring                      */

/* record types: arg / v1 / v2 */
#define EV_BOOT          1u      /* -         / boots      / raw reset cause */
#define EV_SYNC          2u      /* new state / rpm        / old<<8 | loss reason */
#define EV_SYNC_LOSS     3u      /* reason    / rpm        / crank losses    */
#define EV_CYCLE         4u      /* 1 acq 0 lost / rpm     / acq n | cam loss reason */
#define EV_PHASE_CORR    5u      /* -         / rpm        / corrections     */
#define EV_ENGINE        6u      /* 0 stop 1 crank 2 run / rpm / battery x10 */
#define EV_FLAGS         7u      /* -         / rpm        / engineFlags & 0x7E20 */
#define EV_FUELCUT       8u      /* -         / rpm        / fuelCut bits    */
#define EV_OVERDWELL     9u      /* latch mask / rpm       / releases        */
#define EV_SPARK_SKIP   10u      /* -         / rpm        / skips (cut ratio) */
#define EV_SCHED_MISSED 11u      /* -         / rpm        / missed events   */
#define EV_SEQ          12u      /* seqActive / rpm        / twin skips      */
#define EV_ETB          13u      /* phase     / status word / detail         */
#define EV_DBW          14u      /* state     / rpm        / faults          */
#define EV_LAMBDA       15u      /* -         / lambdaStatus / lamWhy        */
#define EV_LIMP         16u      /* -         / rpm        / limp cut bits   */
#define EV_LAMDYN       17u      /* lamDyn low byte / rpm  / bank-1 span     */
#define EV_KLINE        18u      /* counter 0 resync 1 hw ovr 2 frame 3 ovf
                                    4 echo lost / rpm / its value           */

void          far hc_evlog_init(unsigned int boots, unsigned int reset_raw);
void          far hc_evlog_service(unsigned int ms);
unsigned char far hc_evlog_byte(unsigned int off);
/* 1 = sustained low variation; advisory, never withdraw a measurement */
unsigned char far hc_lamdyn_step(unsigned char b, unsigned char valid,
                                 unsigned int ua, unsigned char running,
                                 unsigned int ms);
unsigned char far hc_lamdyn_alive(unsigned char b);

#endif
