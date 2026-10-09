/*
 * hcfuelpump.c - the fuel pump relay lifecycle. Read hcfuelpump.h first.
 *
 * Written on the assumption that no C runtime initialisation happens:
 * hc_fuelpump_init() writes every item of private state explicitly and
 * commands the safe OFF state before anything else can ask for ON.
 */
#ifdef HC_FAR_BRIDGE
#include "hcfarbridge.h"  /* FIRST: FAR code on ME7.1.1 since V97 (NCODE relief) */
#endif
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hctrigger.h"
#include "hchal.h"
#include "hcfuelpump.h"

static unsigned char fp_state;
static unsigned char fp_cmd;
static unsigned int  fp_reason;
static unsigned int  fp_runs;
static unsigned int  fp_prime_t0;
static unsigned int  fp_prime_ms;      /* the clamped prime duration        */
static unsigned char fp_primed;        /* once per power cycle, not per stall */
static unsigned char fp_prime_run;     /* the prime timer has started       */
static unsigned char fp_ever_turned;   /* the engine has turned since boot  */
static unsigned char fp_ign_seen;      /* ignition has been on at least once */
static unsigned char fp_live;          /* the HAL permission the last pass saw */
static unsigned int  fp_last_ms;        /* the tick the last service pass saw */
static unsigned int  fp_last_rpm;       /* and the speed it saw with it       */

/* THE PRIME IS CLAMPED IN CODE. CAL_FUELPUMP_PRIME_MS is a 16-bit page value
   and a u16 is 65 seconds of pump into a rail whose pressure regulator may be
   the only thing holding it. A prime exists to fill a line; FP_PRIME_MAX_MS
   (hcfuelpump.h) does that on any pump this ECU was built for, and a page
   edit must not be able to ask for more. The page proposes, this clamps - the
   same rule hcbench.c applies to a pulse width, for the same reason. Since
   V75 the TunerStudio field carries the same ceiling, so the clamp is a
   second line and never a silent surprise. */

/* Applying the command through one function means the census counts state
   CHANGES rather than service passes, and it means there is exactly one place
   a port would eventually be written from. */
static void fp_command(unsigned char on)
{
    on = (unsigned char)(on ? 1u : 0u);
    if (on == fp_cmd) {
        return;
    }
    fp_cmd = on;
    if (on && fp_runs != 0xFFFFu) {
        fp_runs++;
    }
    hc_hal_out(HC_OUT_FUELPUMP, on);
}

void hc_fuelpump_init(void)
{
    fp_state = FP_OFF;
    fp_reason = FP_R_IGNOFF;
    fp_runs = 0u;
    fp_prime_t0 = 0u;
    fp_prime_ms = 0u;
    fp_primed = 0u;
    fp_prime_run = 0u;
    fp_ever_turned = 0u;
    fp_ign_seen = 0u;
    fp_live = 0u;
    fp_last_ms = 0u;
    fp_last_rpm = 0u;
    /* Not fp_command(): that would compare against an uninitialised fp_cmd.
       Set the shadow first, then drive the safe state unconditionally. */
    fp_cmd = 1u;
    fp_command(0u);
    fp_runs = 0u;                       /* the safe-state write is not a run */
}

/* THE DECISION. Everything the pump is ASKED to do, and nothing about whether
   the pin may do it - that is the HAL's answer, `live`, and the caller below
   follows it. `live` enters here only to start the prime timer. */
static void fp_decide(unsigned int now_ms, unsigned char ign_on,
                      unsigned char trig_state, unsigned char fault,
                      unsigned char live)
{
    unsigned char turning;

    /* FAULT LATCHES. A pump that switches itself back on because the fault bit
       flickered is worse than one that stays off until somebody looks. Only
       hc_fuelpump_init() clears it. */
    if (fp_state == FP_FAULT) {
        fp_command(0u);
        return;
    }

    /* The page verdict arrives from the caller, SETTLED. This module used to
       call hc_cfg_faults() itself on every pass, which read the page while
       TunerStudio was half way through writing a u16 - and a torn value is
       exactly the transient that must never latch a running engine's pump
       off. The main loop already debounces it for everything else. */
    if (fault) {
        fp_state = FP_FAULT;
        fp_reason = (fault & FP_FAULT_CFG) ? FP_R_CFG : FP_R_FAULT;
        fp_command(0u);
        return;
    }

    /* MODE OFF NEVER COMMANDS THE PUMP, and it is checked before anything
       that could turn it on. There is deliberately no latching ON: a page
       setting that energises a fuel pump indefinitely is exactly what a fuel
       pump relay is fitted to prevent. hcbench.c's mode is the explicit test
       path and it is bounded, finite and gated on RPM zero. */
    if (hc_cal_u8(CFG_U_FUEL_PUMP_MODE) != HC_PUMP_AUTO) {
        fp_state = FP_OFF;
        fp_reason = FP_R_DISABLED;
        fp_primed = 0u;
        fp_prime_run = 0u;
        fp_ign_seen = 0u;
        fp_command(0u);
        return;
    }

    /* IGNITION OFF IS UNCONDITIONAL AND IT RE-ARMS THE PRIME. A key cycle is
       the one event that legitimately allows the next prime; a stall is not. */
    if (!ign_on) {
        fp_state = FP_OFF;
        fp_reason = FP_R_IGNOFF;
        fp_primed = 0u;
        fp_prime_run = 0u;
        fp_ever_turned = 0u;
        fp_ign_seen = 0u;
        fp_command(0u);
        return;
    }

    /* "Turning" is deliberately NOT an rpm threshold. trg_rpm goes to zero
       between two teeth of a barely-moving engine, and a pump that drops out
       there is a pump that makes starting harder. The decoder's own state is
       the authority: anything past NO_SIGNAL means edges are arriving. */
    turning = (unsigned char)(trig_state != TRG_NO_SIGNAL);
    if (turning) {
        fp_ever_turned = 1u;
    }

    /* First service pass with the key on selects the one prime of this power
       cycle. The duration is read here, once, and clamped here. */
    if (!fp_ign_seen) {
        fp_ign_seen = 1u;
        fp_prime_run = 0u;
        fp_prime_ms = hc_cal_u16(CAL_FUELPUMP_PRIME_MS);
        if (fp_prime_ms > FP_PRIME_MAX_MS) {
            fp_prime_ms = FP_PRIME_MAX_MS;
        }
        if (fp_prime_ms != 0u) {
            fp_state = FP_PRIME;
            fp_primed = 0u;
        } else {
            fp_state = FP_OFF;
            fp_primed = 1u;
            fp_reason = FP_R_DISABLED;
        }
    }

    if (turning) {
        /* Sync tells CRANKING from RUNNING. Both command the pump on; the
           distinction exists so a bench log says which one it was. */
        fp_state = (unsigned char)((trig_state >= TRG_SYNC_CRANK)
                                   ? FP_RUNNING : FP_CRANKING);
        fp_primed = 1u;                 /* the engine took over from the prime */
        fp_reason = 0u;
        fp_command(1u);
        return;
    }

    /* Not turning. Either the prime is still running, or the engine has
       stopped, or it never started. */
    if (fp_state == FP_PRIME && !fp_primed) {
        /* THE TIMER STARTS WHEN THE PIN CAN MOVE. Counted from the first
           service pass, the prime used to spend its first few hundred
           milliseconds - the S5500 handshake - requesting a pin the HAL would
           not yet drive, and that request was then never re-issued: a 2 s
           prime put NOTHING on the wire. The configured time is the time at
           the pin. */
        if (!fp_prime_run && live) {
            fp_prime_run = 1u;
            fp_prime_t0 = now_ms;
        }
        if (!fp_prime_run
            || (unsigned int)(now_ms - fp_prime_t0) < fp_prime_ms) {
            fp_reason = 0u;
            fp_command(1u);
            return;
        }
        fp_primed = 1u;
        fp_state = FP_OFF;
        fp_reason = FP_R_PRIMEDONE;
        fp_command(0u);
        return;
    }

    /* THE TRANSITION THIS MODULE EXISTS FOR. It was turning, it is not now,
       so the pump stops on this pass - not after a timeout, not after a
       confirmation, and not only if some other subsystem agrees. */
    if (fp_ever_turned) {
        fp_state = FP_STOPPED;
        fp_reason = FP_R_STALL;
    } else if (fp_reason == 0u || fp_reason == FP_R_INHIBIT) {
        fp_reason = FP_R_PRIMEDONE;
    }
    fp_command(0u);
}

void hc_fuelpump_service(unsigned int now_ms, unsigned char ign_on,
                         unsigned int rpm, unsigned char trig_state,
                         unsigned char fault)
{
    unsigned char live;

    fp_last_ms = now_ms;

    /* rpm is RECORDED but is deliberately NOT the running/stopped authority -
       see the "turning" comment in fp_decide(). It stays in the signature
       because every caller already has it, because a bench log wants to see
       what speed the pump decision was made at, and because the day somebody
       decides the pump should drop out above a rev limit, this is where that
       belongs. Recorded rather than cast to void: C166 rejects `(void)x;` as
       an expression with no effect and this build treats a warning as a
       failure. */
    fp_last_rpm = rpm;

    live = (unsigned char)(hc_hal_out_class_live(HC_OUT_FUELPUMP) ? 1u : 0u);
    fp_decide(now_ms, ign_on, trig_state, fault, live);

    /* FOLLOW THE HAL'S PERMISSION, BOTH WAYS. fp_command() speaks only when
       the REQUEST changes, and the HAL drives only what it is permitted to -
       so without this, an ON asked for before arming (or before the S5500
       link was up) never reached the pin, and a disarm under an ON request
       left the pin exactly as it was. Re-issuing on the permission EDGE keeps
       the census counting transitions, not passes. */
    if (live != fp_live) {
        fp_live = live;
        hc_hal_out(HC_OUT_FUELPUMP, (unsigned char)(fp_cmd && live));
    }
    if (fp_cmd && !live) {
        fp_reason = FP_R_INHIBIT;
    }
}

unsigned char hc_fuelpump_state(void)   { return fp_state; }
unsigned char hc_fuelpump_command(void) { return fp_cmd; }
unsigned int  hc_fuelpump_reason(void)  { return fp_reason; }
unsigned int  hc_fuelpump_runs(void)    { return fp_runs; }
unsigned int  hc_fuelpump_rpm(void)     { return fp_last_rpm; }
unsigned char hc_fuelpump_live(void)    { return fp_live; }

/* The CONFIGURED cavity, 1..121, 255 = unassigned. Reporting only. */
unsigned char hc_fuelpump_pin(void)
{
    return hc_cal_u8(CFG_U_PIN_FUEL_PUMP);
}

/* Computed from the tick the last service pass saw, not from a fresh read of
   a timer this module does not own. One clock source per module. A prime
   waiting for permission has all of its time left. */
unsigned int hc_fuelpump_prime_left(void)
{
    unsigned int gone;

    if (fp_state != FP_PRIME || fp_primed) {
        return 0u;
    }
    if (!fp_prime_run) {
        return fp_prime_ms;
    }
    gone = (unsigned int)(fp_last_ms - fp_prime_t0);
    if (gone >= fp_prime_ms) {
        return 0u;
    }
    return (unsigned int)(fp_prime_ms - gone);
}
