/*
 * hcmainrelay.c - the logical MAIN_RELAY function. Read hcmainrelay.h first:
 * it explains why this is NOT the Porsche ECU's own supply, and which
 * cavities the HAL can and cannot drive it through.
 *
 * Mismatch is telemetry only. It never resets, shuts down, disarms or latches
 * a fault: unavailable feedback must not become a false alarm, and on this
 * board the feedback word is a static correlation the S5500 sweep has not
 * confirmed yet.
 *
 * This file assumes no C runtime initialisation. hc_main_relay_init() writes
 * every item of private state explicitly and commands the safe OFF state.
 */
#ifdef HC_FAR_BRIDGE
#include "hcfarbridge.h"  /* FIRST: FAR code on ME7.1.1 since V97 (NCODE relief) */
#endif
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hchal.h"
#include "hcmainrelay.h"

static unsigned char relay_mode;
static unsigned char relay_command;
static unsigned char relay_state;
static unsigned char relay_feedback_state;
static unsigned char relay_feedback_valid;
static unsigned char relay_mismatch;
static unsigned char relay_bound;
static unsigned char relay_mismatch_pending;
static unsigned int  relay_feedback_dv;
static unsigned int  relay_mismatch_since;
static unsigned int  relay_state_since;

/* ONE PLACE DECIDES THE REQUEST, and hc_main_relay_service() hands it to the
   HAL ONCE PER PASS, on every exit path. The HAL's permission (arming, the
   S5500 link, a valid page) is a LEVEL, so the request must be one too: an
   edge sent while the output was not yet permitted would never reach the pin,
   and a withdrawn permission must release it on the pass it is withdrawn.
   The HAL writes the port only when what it should drive differs from what
   it is driving, so a level call costs a compare and not a port write. */
static void command(unsigned char on)
{
    relay_command = (unsigned char)(on ? 1u : 0u);
}

static void enter(unsigned char st, unsigned int now_ms)
{
    if (relay_state != st) {
        relay_state = st;
        relay_state_since = now_ms;
    }
}

void hc_main_relay_init(void)
{
    relay_mode = MAIN_RELAY_OFF;
    relay_command = 1u;                 /* so command(0) below really writes */
    relay_state = 0xFFu;                /* so enter() really transitions     */
    relay_feedback_state = 0u;
    relay_feedback_valid = 0u;
    relay_mismatch = 0u;
    relay_bound = 0u;
    relay_mismatch_pending = 0u;
    relay_feedback_dv = 0u;
    relay_mismatch_since = 0u;
    relay_state_since = 0u;
    command(0u);
    hc_hal_main_relay_set(0u);          /* the HAL's safe state, explicitly */
    relay_state = MR_ST_INIT;
}

void hc_main_relay_set(unsigned char mode)
{
    if (mode > MAIN_RELAY_AUTO) {
        mode = MAIN_RELAY_OFF;
    }
    cfg_set_u8(CFG_MAIN_RELAY_MODE, mode);
}

void hc_main_relay_service(unsigned int now_ms, unsigned char run_request,
                           unsigned char fault)
{
    unsigned int grace, hold;

    /* A LATCHED FAULT IS FINAL until hc_main_relay_init(). A relay that
       re-closes because a fault bit flickered is worse than one that stays
       open until somebody looks. */
    if (relay_state == MR_ST_FAULT) {
        command(0u);
        hc_hal_main_relay_set(0u);
        relay_bound = hc_hal_main_relay_bound();
        return;
    }
    if (fault) {
        command(0u);
        hc_hal_main_relay_set(0u);
        enter(MR_ST_FAULT, now_ms);
        relay_bound = hc_hal_main_relay_bound();
        return;
    }

    relay_mode = cfg_u8(CFG_MAIN_RELAY_MODE);
    if (relay_mode > MAIN_RELAY_AUTO) {
        relay_mode = MAIN_RELAY_OFF;
    }

    /* OFF AND ON BYPASS THE LIFECYCLE. They are manual overrides, and a
       manual override that had to wait for a state machine would not be one.
       The lifecycle exists for AUTO. */
    if (relay_mode == MAIN_RELAY_OFF) {
        command(0u);
        enter(MR_ST_RELEASED, now_ms);
    } else if (relay_mode == MAIN_RELAY_ON) {
        command(1u);
        enter(MR_ST_RUNNING, now_ms);
    } else {
        switch (relay_state) {
        case MR_ST_INIT:
        case MR_ST_RELEASED:
            if (run_request) {
                command(1u);
                enter(MR_ST_REQUEST, now_ms);
            } else {
                command(0u);
            }
            break;

        case MR_ST_REQUEST:
            if (run_request) {
                /* RUNNING means the request has actually had time to close
                   a relay, or feedback says it did. Without that distinction
                   "commanded" and "closed" would be the same word, which is
                   how a mismatch check ends up comparing a value to
                   itself. */
                if ((relay_feedback_valid && relay_feedback_state)
                    || (unsigned int)(now_ms - relay_state_since)
                       >= MR_SETTLE_MS) {
                    enter(MR_ST_RUNNING, now_ms);
                }
                break;
            }
            /* THE REQUEST DROPPED BEFORE IT SETTLED. Until V75 this entered
               SHUTDOWN and broke out, so with the hold at 0 the relay was
               released one pass LATE - exactly the case the RUNNING branch
               below falls through to avoid. Same rule here: enter SHUTDOWN
               and evaluate it in this pass. */
            enter(MR_ST_SHUTDOWN, now_ms);
            /* no break - through RUNNING's drop path into SHUTDOWN */

        case MR_ST_RUNNING:
            if (!run_request) {
                enter(MR_ST_SHUTDOWN, now_ms);
                /* FALL THROUGH, deliberately. With CFG_U_MAIN_RELAY_HOLD_MS
                   at 0 "no hold" must mean no hold, not "released on the
                   next service pass". Entering and evaluating in the same
                   pass is what makes the zero case exact. */
            } else {
                break;
            }
            /* no break */

        case MR_ST_SHUTDOWN:
            /* The request coming back cancels the shutdown. A key touched
               twice must not drop the relay half a second later. */
            if (run_request) {
                enter(MR_ST_RUNNING, now_ms);
                break;
            }
            hold = hc_cal_u16(CFG_U_MAIN_RELAY_HOLD_MS);
            if ((unsigned int)(now_ms - relay_state_since) >= hold) {
                command(0u);
                enter(MR_ST_RELEASED, now_ms);
            }
            break;

        default:
            enter(MR_ST_INIT, now_ms);
            break;
        }
    }

    hc_hal_main_relay_set(relay_command);
    relay_bound = hc_hal_main_relay_bound();
    relay_feedback_valid = hc_hal_main_relay_feedback_valid();
    relay_feedback_dv = hc_hal_main_relay_feedback_dv();
    relay_feedback_state = relay_feedback_valid
        ? hc_hal_main_relay_feedback_state() : 0u;

    if (!relay_feedback_valid
        || relay_feedback_state == relay_command) {
        relay_mismatch_pending = 0u;
        relay_mismatch = 0u;
        relay_mismatch_since = now_ms;
        return;
    }
    if (!relay_mismatch_pending) {
        relay_mismatch_pending = 1u;
        relay_mismatch_since = now_ms;
        relay_mismatch = 0u;
        return;
    }
    grace = cfg_u16(CFG_MAIN_RELAY_GRACE_MS);
    if ((unsigned int)(now_ms - relay_mismatch_since) >= grace) {
        relay_mismatch = 1u;
    }
}

unsigned char hc_main_relay_get_mode(void) { return relay_mode; }
unsigned char hc_main_relay_get_command(void) { return relay_command; }
unsigned char hc_main_relay_get_state(void) { return relay_state; }
unsigned int hc_main_relay_get_feedback_dv(void) { return relay_feedback_dv; }
unsigned char hc_main_relay_get_feedback_state(void)
{
    return relay_feedback_state;
}
unsigned char hc_main_relay_get_feedback_valid(void)
{
    return relay_feedback_valid;
}
unsigned char hc_main_relay_get_mismatch(void) { return relay_mismatch; }
unsigned char hc_main_relay_get_bound(void) { return relay_bound; }

/* THE CONFIGURED CAVITY, 1..121, and 255 for unassigned. Reporting only: the
   routing is the page's and the electrical binding is the HAL's. Published so
   a bench can see WHICH cavity a command was meant for without inferring it
   from a preset. */
unsigned char hc_main_relay_get_pin(void)
{
    return hc_cal_u8(CFG_U_PIN_MAIN_RELAY);
}
