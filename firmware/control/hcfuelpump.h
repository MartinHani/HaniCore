/*
 * hcfuelpump.h - the electric fuel pump relay lifecycle, target independent.
 *
 * WHY A FUEL PUMP RELAY EXISTS AT ALL is the last state below, and everything
 * else is arranged around it: when the engine stops turning, the pump stops.
 * A crash that leaves a pump running against a broken line is the failure this
 * component is in the car to prevent, so STALL is not a corner case here - it
 * is the design centre, and it is the one transition that must be immediate
 * and unconditional.
 *
 * THE LIFECYCLE, and the request the ECU makes in each state:
 *
 *      OFF        ignition off, or the module has not been serviced yet
 *      PRIME      key-on: run for CAL_FUELPUMP_PRIME_MS and then STOP even if
 *                 the engine never turns. A bounded prime, never a latch.
 *      CRANKING   edges are arriving but sync is not established -> ON
 *      RUNNING    the engine is turning -> ON
 *      STOPPED    the engine WAS turning and has stopped -> OFF, immediately
 *      FAULT      the configuration stopped describing an engine, or the
 *                 caller reported a runtime fault -> OFF, and it latches
 *                 until the next hc_fuelpump_init()
 *
 * PRIME HAPPENS ONCE PER POWER CYCLE. Not once per stall: an engine that
 * stalls and is re-cranked does not get a second prime, because the second
 * prime is the one that runs a pump into a leak nobody noticed the first time.
 *
 * THE PRIME IS THE CONFIGURED TIME AT THE PIN, not a command that half
 * overlaps the ECU's own startup. CAL_FUELPUMP_PRIME_MS (TunerStudio
 * "Fuel pump prime") is read once per key cycle and clamped to
 * FP_PRIME_MAX_MS; the timer starts on the first pass the HAL PERMITS the
 * output (S5500 link up, page armed and valid). Until then the state is PRIME,
 * the request is ON and the reason reads FP_R_INHIBIT. A page armed later in
 * the key cycle therefore gets the one prime it has not had yet.
 *
 * STALL is the decoder's verdict: trg_state returning to TRG_NO_SIGNAL after
 * CFG_TRIG_TIMEOUT_MS (TunerStudio "Stall timeout") without a tooth. The pump
 * drops on that same pass. There is deliberately no second, pump-private
 * timeout stacked on top of it.
 *
 * WHAT THIS MODULE DOES NOT DO. It does not touch a port. It asks
 * hc_hal_out(HC_OUT_FUELPUMP, ...), and the HAL decides whether that reaches
 * cavity-65/P2.12 or whichever cavity the page routes the pump to. The HAL's
 * permission is LEVEL, and this module follows it: when the permission rises
 * the current request is re-issued, and when it falls the output is released
 * on the same pass. A request made before the output was permitted is never
 * silently lost, and a disarm never leaves the pin driven.
 *
 * WHAT IS STILL NOT PROVEN is the CJ920 stage's polarity at cavity 65. The
 * bounded measurement is hcbench.c's fuel-pump mode.
 *
 * The evidence for the pin itself is in hctarget.h under "EKP, the fuel pump"
 * and in docs/ARCHITECTURE.md: P2.12 / CC12IO, CPU pin 61, both ME7.1.1
 * columns of Bosch's own port sheet, into a CJ920 low-side driver, out at
 * connector cavity 65.
 */
#ifndef HCFUELPUMP_H
#define HCFUELPUMP_H

#include "hctarget.h"   /* HC_COLD: far on ME7.1.1 (FCODE, V97), empty elsewhere */
#ifndef HC_COLD
#define HC_COLD
#endif

#define FP_OFF        0u
#define FP_PRIME      1u
#define FP_CRANKING   2u
#define FP_RUNNING    3u
#define FP_STOPPED    4u
#define FP_FAULT      5u

/* Why the pump is not running, when it is not. One bit per reason, all of
   them evaluated - a bench operator who is told only "not primed" fixes that
   and is then told "not armed". */
#define FP_R_IGNOFF     0x0001u   /* hc_fuelpump_service saw ignition off   */
#define FP_R_PRIMEDONE  0x0002u   /* the bounded prime finished, no engine  */
#define FP_R_STALL      0x0004u   /* it was turning and stopped             */
#define FP_R_CFG        0x0008u   /* the page does not describe an engine   */
#define FP_R_FAULT      0x0010u   /* the caller reported a runtime fault    */
#define FP_R_DISABLED   0x0020u   /* prime time 0 AND never any engine      */
#define FP_R_INHIBIT    0x0040u   /* requested ON, the HAL refuses the pin:
                                     not armed, S5500 link down, page refused
                                     or the pump cavity unroutable. Not a
                                     fault - it clears when permission does */

/* The `fault` argument is a bit set, so the reason can say WHICH. Both latch. */
#define FP_FAULT_RUNTIME 0x01u    /* a runtime condition the caller judged unsafe */
#define FP_FAULT_CFG     0x02u    /* the SETTLED page no longer describes an
                                     engine - the caller debounces it, because
                                     TunerStudio writes a u16 as two bytes and
                                     the page is torn between them */

/* THE PRIME'S HARD CEILING. The page proposes the prime time, this bounds it;
   TunerStudio's field range is the same number, so a tuner cannot enter a
   value the firmware would silently cut. */
#define FP_PRIME_MAX_MS   5000u

void HC_COLD hc_fuelpump_init(void);

/*
 * Once per main-loop pass.
 *
 *   now_ms      the free-running millisecond tick
 *   ign_on      1 while the ECU considers the key on. On ME7.1.1 this is
 *               KL15_STAT (P6.2); a target with no such input passes 1 and
 *               the ignition-off transition simply never fires, which is
 *               honest rather than invented.
 *   rpm         trg_rpm
 *   trig_state  trg_state, so CRANKING and RUNNING can be told apart by
 *               SYNC and not by an rpm threshold that a slow crank crosses
 *               and re-crosses
 *   fault       FP_FAULT_* bits; non-zero LATCHES the pump off until
 *               hc_fuelpump_init()
 *
 * Never blocks. Makes one hc_hal_out() call per request change and one per
 * change of the HAL's permission, and none otherwise, so the request census
 * counts transitions, not passes.
 */
void HC_COLD hc_fuelpump_service(unsigned int now_ms, unsigned char ign_on,
                         unsigned int rpm, unsigned char trig_state,
                         unsigned char fault);

unsigned char HC_COLD hc_fuelpump_state(void);
unsigned char HC_COLD hc_fuelpump_command(void);   /* what was last asked of the HAL */
unsigned int HC_COLD  hc_fuelpump_reason(void);    /* FP_R_* when not commanded on   */
unsigned int HC_COLD  hc_fuelpump_runs(void);      /* OFF->ON transitions, ever      */
unsigned int HC_COLD  hc_fuelpump_rpm(void);       /* the rpm the last pass saw      */
unsigned int HC_COLD  hc_fuelpump_prime_left(void); /* ms remaining, 0 outside PRIME */
unsigned char HC_COLD hc_fuelpump_pin(void);        /* the CONFIGURED cavity         */
unsigned char HC_COLD hc_fuelpump_live(void);       /* the HAL permits the pin now   */

#endif /* HCFUELPUMP_H */
