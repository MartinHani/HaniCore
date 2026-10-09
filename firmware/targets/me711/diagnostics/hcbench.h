/*
 * hcbench.h - bounded bench ACTUATOR TESTS, one output at a time.
 *
 * READ THIS BEFORE CHANGING ANYTHING IN hcbench.c.
 *
 * this header used to open "the ONLY code that may drive an engine
 * output" and "the engine runtime cannot energise anything". That stopped
 * being true at V63, when hchal_me711.c gained a real output back end that
 * the angle scheduler drives. Normal engine operation is now trigger and
 * scheduler driven with no user arm; THIS module is the
 * separate, deliberate test facility.
 *
 * What this module adds is a SEPARATE path, which exists for one reason: the
 * CPU port for every coil and injector is known from Bosch's own port sheet -
 * both ME7.1.1 columns agree - but the DRIVER STAGE is not. Its polarity, its
 * connector cavity, and whether it needs an enable are all unmeasured. Those
 * cannot be reasoned out of a document. They are measured by driving one pin,
 * briefly, with a scope on the connector and nothing else attached, which is
 * exactly what this module does and the only thing it does.
 *
 * EVERY ONE OF THESE MUST HOLD, SIMULTANEOUSLY, OR NOTHING MOVES:
 *
 *   trg_rpm == 0 AND the decoder reports no crank signal at all
 *   hc_cfg_faults() == 0                         - the page describes an engine
 *   the S5500 supervision link is running        - the platform is healthy
 *   an explicit '!T' arrived from the host       - a person pressed a button
 *   the mode has a PROVEN CPU port on this board - no guessed pin, ever
 *   the channel index is inside that mode's count
 *   the pulse width is inside a bound COMPILED IN, not one from the page
 *
 * and the run stops on the FIRST of: the pulse count, the timeout, an abort
 * command, or a crank edge appearing. A crank edge mid-test is treated as an
 * abort, not as a reason to finish the last pulse.
 *
 * THE BOUNDS ARE IN CODE, NOT IN THE CONFIGURATION. CFG_U_TEST_VALUE and
 * CFG_U_TEST_TIMEOUT_MS are read and then CLAMPED here. A page that asks for a
 * 500 ms injector pulse gets 20 ms, and a page cannot be edited into a
 * continuous energisation.
 *
 * ONE CHANNEL AT A TIME. There is a single active channel and a single active
 * mode. There is no "all injectors" command and there must never be one.
 *
 * THE FUEL PUMP USED TO BE REFUSED HERE, AND THAT WAS A DOCUMENTATION BUG,
 * not a hardware fact. This header said "no MAIN CPU port for these appears
 * in the Bosch port sheet's ME7.1.1 columns". EKP is on MAIN CPU P2.12 /
 * CC12IO, CPU pin 61, meaning "EKP-Ansteuerung", and BOTH ME7.1.1 columns
 * agree - it is row 68 of this repository's own generated
 * tools/config_source/data/me711_iomap.csv and has been since the map was extracted.
 * Nobody had looked. Corrected 2026-09-02; the evidence chain, including the
 * CJ920 driver and connector cavity 65, is in hctarget.h and
 * docs/ARCHITECTURE.md.
 *
 * WHAT IS DELIBERATELY REFUSED, and why refusing is the honest answer:
 *
 * ============================================== THE MAIN RELAY MODE =======
 *
 * HC_TEST_MAIN_RELAY, one channel, and it is the ONLY way to command the
 * logical MAIN_RELAY output for a measurement. Setting Main Relay Mode = ON
 * would latch it indefinitely, which is not a bench test - it is leaving a
 * relay energised and hoping somebody remembers.
 *
 * IT DRIVES THE CONFIGURED CAVITY, NOT A HARDCODED PIN. The cavity comes from
 * CFG_U_PIN_MAIN_RELAY, and the run is refused unless ALL of:
 *
 *   the cavity is assigned (not 255)
 *   hc_pin_can(cavity, HC_PINCAP_RELAY_OUT) - the descriptor agrees it can
 *     carry a relay, which after 2026-09-03 is a driver-stage judgement and
 *     not an OEM-name one
 *   the cavity appears in relay_port_of() below, which lists ONLY cavities
 *     whose MAIN CPU port this repository can quote from Bosch's own sheet
 *
 * Anything else is HCB_R_PIN. A cavity the descriptor likes but whose CPU
 * port nobody has written down is exactly the guessed pin this module exists
 * to avoid driving.
 *
 * TIMED IN MILLISECONDS, like the fuel pump and for the same reason: a relay
 * coil pulls in in 5-15 ms and a multimeter cannot see a microsecond pulse.
 * Three energisations of at most one second, a second apart, then it stops on
 * its own. There is no continuous mode and there must never be one.
 *
 * CAVITIES 21, 22 AND 24 ARE NOT AVAILABLE HERE ANY MORE, and this paragraph
 * used to say "DO CAVITY 24 FIRST ... before anything is asked of cavity 21".
 * That advice was built on `Steckerb. ME7.1.XLS`, a VW/Audi ME7.1 C4 connector
 * workbook, and against the ME7.1.1 sheet that workbook is wrong for the whole
 * 18..24 block: 21 is KL15 and not ZAS2, 23 is the main relay and not EV8, 19
 * is EV8, 18 is ZAS2, 22 is ZAS1. Only 24 = EV7 agrees.
 *
 * CAVITY 21 IS A POWER INPUT. It is the ignition-lock feed into the CJ910's
 * enable pin, settled by three agreeing sources, one of which is this ECU on
 * the bench: remove +12 V from cavity 21 while 3 and 62 stay powered and it
 * goes OFFLINE. This module used to hold a port write for it.
 *
 * The old paragraph even recorded the reason not to trust the pin - "variants
 * differ", B-Muster ZAS2, C-Muster CS_CJ120, so on some boards P8.2 is an SPI
 * chip select - and treated it as a reason to test something else first. It
 * was a reason not to carry the pin at all.
 *
 * SO THE MAIN RELAY DRIVES CAVITY 65 AND NOTHING ELSE: EKPR, MAIN CPU
 * P2.12/CC12IO, "EKP-Ansteuerung", BOTH ME7.1.1 port-map columns, out through
 * a CJ920 low-side driver. It is the best-evidenced relay-class output this
 * CPU definitely owns. hc_pin_can() refuses the rest independently, because
 * the descriptor now marks the whole block SPECIAL_LOCKED - but a port write
 * for a power input is not a thing to leave standing behind a second check.
 * tools/me711_cavity_truth_proof.py holds both halves.
 *
 *   main relay                   THERE IS NO OEM MAIN-RELAY OUTPUT ON THIS CPU,
 *                                and that is now a finding rather than a gap.
 *                                All 112 MAIN CPU rows were enumerated; the
 *                                only HR in the whole port sheet is ASIC
 *                                AN14, and Bosch's note on it is "Port nur
 *                                Input". The main CPU's power authority is
 *                                NLEN_FR (P3.12), which is hcpower.c's, not
 *                                this module's - it is a power-down veto and
 *                                not something you pulse on a bench.
 *   fan, boost, VVT, generic     unproven port. Same rule as ever.
 *
 * Each refusal is REPORTED with its reason rather than silently ignored, so a
 * bench operator can tell "not implemented" from "you got the invariants
 * wrong".
 *
 * ================================================ THE FUEL PUMP MODE =======
 *
 * HC_TEST_FUEL_PUMP, one channel. P2.12, out through the CJ920 to connector
 * cavity 65. It is TIMED IN MILLISECONDS, not microseconds, and it is the
 * only mode that is: a relay coil takes several milliseconds to pull in and a
 * multimeter cannot see a 200 us pulse at all. Three energisations of at most
 * one second each, a second apart. hcb_width_ms carries the clamped value and
 * hcb_width_us reads 0, so the two units can never be confused in telemetry.
 *
 * NOTHING MAY BE CONNECTED TO CAVITY 65. The measurement is of the ECU's own
 * driver stage. A relay - let alone a pump - attached to an output whose
 * polarity is the thing under test is how you find out by running a pump dry.
 *
 * ====================================================== THE DBW MODE =======
 *
 * HC_TEST_DBW, two channels: 1 and 2 are the two directions. This one has its
 * own invariants ON TOP of the common set, because it is the only mode that
 * can move something mechanical:
 *
 *   the two TPS tracks must agree, per CFG_U_TPS_CORR and CFG_U_TPS_TOL_X10,
 *     BEFORE the run starts - a throttle whose feedback is already
 *     inconsistent is not a throttle you energise
 *   the bridge fault pin SF (P3.15) must not be reading faulted at the start,
 *     per CAL_DBW_SF_MODE
 *   EGENFR (P2.11), the bridge enable, is asserted for the RUN and dropped on
 *     any exit path including an abort - so a hung service pass leaves the
 *     bridge disabled, not energised
 *   TPS1 is sampled before the first pulse and watched on every pass. Motion
 *     beyond a COMPILED-IN band aborts the run: that is the runaway guard,
 *     and it is what stands between a stuck-on bridge and a wide-open plate
 *   the pulse is a bounded NUDGE, at most 50 ms, three times. There is no
 *     continuous drive and there is no full-open command, because the first
 *     question a bench has to answer is only "which way does it move and at
 *     which cavity", and that question does not need travel.
 *
 * ED_RST CAN DISABLE THIS BRIDGE WITHOUT ASKING US. S8100 pin 13 is DI2, and
 * the net on it is ED_RST off the monitoring comparator network - the same
 * bundle as ESRST_SM, whose Bosch note is "Absch. EGAS+Endst.". If a run
 * commands motion and nothing moves while SF stays clean, that is a
 * legitimate outcome and it means the platform vetoed it. Report it; do not
 * design around it.
 */
#ifndef HCBENCH_H
#define HCBENCH_H

#include "hctarget.h"   /* HC_COLD: far on ME7.1.1 (FCODE), empty elsewhere */
#ifndef HC_COLD
#define HC_COLD
#endif

/* Run state. Published so TunerStudio shows what actually happened rather
   than what was asked for. */
#define HCB_IDLE      0u
#define HCB_RUNNING   1u
#define HCB_DONE      2u
#define HCB_REFUSED   3u
#define HCB_ABORTED   4u

/* Why a request was refused. One bit per unmet invariant, all of them
   evaluated - so the answer names EVERY reason at once and a bench operator
   is not sent round the loop fixing them one at a time. */
#define HCB_R_RPM         0x0001u  /* the engine is not demonstrably stopped */
#define HCB_R_ARMED       0x0002u  /* RETIRED V84, never set (was: page arm) */
#define HCB_R_CFG         0x0004u  /* hc_cfg_faults() is non-zero           */
#define HCB_R_MODE        0x0008u  /* no proven port for that mode here     */
#define HCB_R_CHANNEL     0x0010u  /* channel index outside the mode        */
#define HCB_R_BUSY        0x0020u  /* a run is in progress, or the pump/relay
                                      lifecycle owns the output       */
#define HCB_R_SUPERVISOR  0x0040u  /* the S5500 link is not running         */
#define HCB_R_TPSPAIR     0x0080u  /* DBW: the two TPS tracks disagree      */
#define HCB_R_SF          0x0100u  /* DBW: the bridge already reports fault */
#define HCB_R_PIN         0x0200u  /* the configured cavity is unusable here */
/* DBW - closed-loop DBW, an ETB calibration or the autotune already owns
   the bridge. Two owners of one H-bridge is a fight, not a test. */
#define HCB_R_ETB         0x0400u
/* DBW - the throttle output class is not permitted (key off, S5500 link,
   page; hc_hal_out_class_live). The shared motor primitive would refuse
   every enable, so the run would report DONE having driven nothing. */
#define HCB_R_PERMIT      0x0800u

/* Why a run stopped early. */
#define HCB_A_HOST        0x0001u  /* '!X' from the host                    */
#define HCB_A_CRANK       0x0002u  /* a crank edge arrived mid-test         */
#define HCB_A_CFG         0x0004u  /* the page stopped being valid          */
#define HCB_A_TIMEOUT     0x0008u  /* the overall guard expired             */
#define HCB_A_SF          0x0010u  /* DBW: the bridge asserted its fault pin */
#define HCB_A_TPSMOVE     0x0020u  /* DBW: the plate moved past the band    */
#define HCB_A_TPSPAIR     0x0040u  /* DBW: the tracks stopped agreeing      */
#define HCB_A_SUPERVISOR  0x0080u  /* the S5500 link stopped mid-run        */

/* Modes that HAVE a proven port on this board. Anything else is refused with
   HCB_R_MODE. The values are HC_TEST_* from hc_config_generated.h; they are
   not redefined here, they are simply the subset this target can honour. */

void HC_COLD hcbench_init(void);

/* Request a run. mode is HC_TEST_*, ch is 1-based within that mode.
   Returns 1 if it started, 0 if it was refused - and hcb_refuse then says
   why, with every reason set at once. */
unsigned char HC_COLD hcbench_start(unsigned char mode, unsigned char ch);

/* Stop immediately and put the pin back. Safe to call at any time, from any
   state, including when nothing is running. */
void HC_COLD hcbench_abort(unsigned int reason);

/* Once per main-loop pass, with the millisecond tick. Never blocks. */
void HC_COLD hcbench_service(unsigned int tick_ms);
/* Ends a DUE pulse from hcts_target_yield(), inside long K-line replies. */
void HC_COLD hcbench_yield_service(unsigned int tick_ms);

/* Published state - see hcmain_me711.c's put16() block. */
extern unsigned int hcb_state;
extern unsigned int hcb_mode;
extern unsigned int hcb_channel;
extern unsigned int hcb_refuse;      /* HCB_R_* of the LAST request         */
extern unsigned int hcb_abort;       /* HCB_A_* of the LAST early stop      */
extern unsigned int hcb_pulses;      /* completed pulses of the current run */
extern unsigned int hcb_requests;    /* '!T' commands received, ever        */
extern unsigned int hcb_runs;        /* runs that actually started          */
extern unsigned int hcb_port;        /* the PORT this run drives: 2, 7 or 8 */
extern unsigned int hcb_bit;         /* and the bit within it               */
extern unsigned int hcb_width_us;    /* the CLAMPED width, MICROSECOND modes */
extern unsigned int hcb_width_ms;    /* the CLAMPED width, MILLISECOND modes */
extern unsigned int hcb_conn_pin;    /* the connector cavity to put a probe on */
extern unsigned int hcb_tps_start;   /* DBW: TPS1 counts before the first pulse */
extern unsigned int hcb_tps_now;     /* DBW: TPS1 counts on the last pass    */
extern unsigned int hcb_sf_level;    /* DBW: the raw SF pin, 0 or 1          */

#endif /* HCBENCH_H */
