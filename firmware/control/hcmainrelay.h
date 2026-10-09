/*
 * hcmainrelay.h - the LOGICAL main relay: a universal, routed output with an
 * explicit lifecycle.
 *
 * READ THIS FIRST, BECAUSE TWO DIFFERENT THINGS ARE CALLED "MAIN RELAY".
 *
 *   THE DONOR ECU'S OWN SUPPLY is not this. On Porsche ME7.1.1, KL30 feeds
 *   the ECU, KL15 enables the CJ910, and NLEN_FR/NLEN_AS meet in a 74ACT00
 *   whose output is the CJ910's run-on input. There is no OEM
 *   main-CPU-controlled main relay in that topology at all. hcpower.c owns
 *   it and this file has nothing to do with it.
 *   See docs/PLATFORM.md.
 *
 *   THIS FILE is HaniCore's own logical MAIN_RELAY function - the external
 *   ECU/main relay a standalone installation needs. The first one is a
 *   VW/Audi 1.8T, which requires it regardless of what Porsche did. It is
 *   routed to a CONFIGURABLE physical cavity through CFG_U_PIN_MAIN_RELAY,
 *   validated to need HC_PINCAP_RELAY_OUT, and it is not bound to any OEM
 *   signal name.
 *
 * WHERE IT CAN BE DRIVEN. CFG_U_PIN_MAIN_RELAY names the cavity and
 * the HAL drives it only when that cavity resolves to a MAIN CPU port this
 * build can write - on ME7.1.1 today that is cavity 65 (EKPR, P2.12, CJ920
 * low side) and nothing else; hc_hal_main_relay_bound() says which. Cavity 23
 * is the OEM main-relay drive: the CJ910's own MR stage, enabled by KL15 (EN1)
 * and run-on (/EN2) and by nothing else (CJ911 sibling datasheet). V78 routes
 * MAIN_RELAY to it as a HARDWARE function - bound = 2, AUTO only, nothing
 * written - and that is the 1.8T default (the AWT J271 wire lands on 23);
 * cavity 21 is KL15, a power input; cavity 18 (ZAS2, P8.2, CJ420) is
 * relay-class on the ME7.1.1 sheet but the port map's two variants disagree
 * about P8.2 (ZAS2 vs CS_CJ120), so it is not bound until a power-off trace
 * settles it.
 *
 * WHAT THE RELAY'S OWN POWER LOSS DOES. On this board KL15 is what keeps the
 * CPU alive (CJ910 EIN) and HaniCore never asserts run-on (NLEN_FR held HIGH),
 * so "KL15 off" is "this CPU stops, P2 tri-states, the stage releases". The
 * AUTO run request is therefore "this CPU is running", and HOLD_MS can only
 * matter on a target whose ECU outlives its ignition.
 *
 * ==================================================== THE LIFECYCLE =======
 *
 *   MR_ST_INIT      power-up, before the first service pass
 *   MR_ST_REQUEST   the ECU wants power and has asked for it
 *   MR_ST_RUNNING   the request has stood for the settle time, or feedback
 *                   confirms the relay closed
 *   MR_ST_SHUTDOWN  the run request has dropped; holding for
 *                   CFG_U_MAIN_RELAY_HOLD_MS
 *   MR_ST_RELEASED  the command has been removed
 *   MR_ST_FAULT     a runtime fault forced a safe release. It LATCHES.
 *
 * OFF and ON are manual overrides and bypass the lifecycle entirely - OFF
 * releases now, ON requests now. AUTO runs the machine above.
 *
 * THE HOLD IS A RELEASE DELAY AND NOT AN AFTER-RUN PROGRAMME. Nothing here
 * schedules fans, purge or an EEPROM write. When run-on is really
 * implemented it gets its own design; overbuilding it now would put
 * behaviour behind a relay that has never been measured.
 */
#ifndef HCMAINRELAY_H
#define HCMAINRELAY_H

#include "hctarget.h"   /* HC_COLD: far on ME7.1.1 (FCODE, V97), empty elsewhere */
#ifndef HC_COLD
#define HC_COLD
#endif

#define MR_ST_INIT      0u
#define MR_ST_REQUEST   1u
#define MR_ST_RUNNING   2u
#define MR_ST_SHUTDOWN  3u
#define MR_ST_RELEASED  4u
#define MR_ST_FAULT     5u

/* How long a request must stand before REQUEST becomes RUNNING when there is
   no usable feedback. Compiled in: it describes relay physics, not a tune. */
#define MR_SETTLE_MS  200u

void HC_COLD          hc_main_relay_init(void);

/*
 * Once per main-loop pass.
 *
 *   now_ms        the free-running millisecond tick
 *   run_request   1 while the ECU wants to be powered. In AUTO this is what
 *                 drives the lifecycle; the caller decides what it means
 *                 (ignition on, or the engine turning, or both).
 *   fault         non-zero for any runtime condition that must release the
 *                 relay. It LATCHES until hc_main_relay_init().
 */
void HC_COLD          hc_main_relay_service(unsigned int now_ms,
                                    unsigned char run_request,
                                    unsigned char fault);

void HC_COLD          hc_main_relay_set(unsigned char mode);
unsigned char HC_COLD hc_main_relay_get_mode(void);
unsigned char HC_COLD hc_main_relay_get_command(void);
unsigned char HC_COLD hc_main_relay_get_state(void);
unsigned int HC_COLD  hc_main_relay_get_feedback_dv(void);
unsigned char HC_COLD hc_main_relay_get_feedback_state(void);
unsigned char HC_COLD hc_main_relay_get_feedback_valid(void);
unsigned char HC_COLD hc_main_relay_get_mismatch(void);
unsigned char HC_COLD hc_main_relay_get_bound(void);
unsigned char HC_COLD hc_main_relay_get_pin(void);   /* the CONFIGURED cavity, 1..121 */

#endif /* HCMAINRELAY_H */
