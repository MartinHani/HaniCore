/*
 * hcts.c - HaniCore's K-line transport and TunerStudio server. SHARED CORE.
 *
 * Shared by every HaniCore target; first developed and bench-proven with
 * TunerStudio at 57600 baud on the ME7.5 (4B0906018DC) target. The comments
 * record measurements: every non-obvious line here exists because a bench log
 * said so.
 *
 * The board reaches this file only through hctarget.h and hcts_target_cmd().
 */
#include <reg167.h>
#include "hctarget.h"
#include "hcconfig.h"
#include "hcts.h"
#if defined(TGT_RX_PEC) || defined(TGT_TX_ASYNC)
#include "hcserial711.h"   /* the ME7.1.1 PEC receive / interrupt transmit */
#endif

/* V45 is an observation-only Bosch build.  The hooks are compiled out for
 * every other target, so the shared transport's normal protocol remains
 * byte-for-byte and timing-for-timing unchanged there. */
#ifdef TGT_BURN_RESET_FORENSICS
#include "hcburnforensics.h"
#define BF_HCTS_INIT(b,w)       hc_bf_hcts_init((b),(w))
#define BF_B_RECEIVED()         hc_bf_b_received()
#define BF_REPLY_ARMED()        hc_bf_reply_armed()
#define BF_RESPONSE_SELECTED(c) hc_bf_response_selected(c)
#define BF_TX_ENTERED()         hc_bf_response_tx_entered()
#define BF_TX_COMPLETED()       hc_bf_response_completed()
#else
#define BF_HCTS_INIT(b,w)       ((void)0)
#define BF_B_RECEIVED()         ((void)0)
#define BF_REPLY_ARMED()        ((void)0)
#define BF_RESPONSE_SELECTED(c) ((void)0)
#define BF_TX_ENTERED()         ((void)0)
#define BF_TX_COMPLETED()       ((void)0)
#endif

#define PAGE_SIZE      HC_CFG_SIZE  /* must match pageSize in the .ini */
#ifndef TGT_OCH_READ_SIZE
#define TGT_OCH_READ_SIZE TGT_OCH_SIZE
#endif
#ifndef HCTS_TARGET_OCH_EXT_READ
#define HCTS_TARGET_OCH_EXT_READ(offset) 0u
#endif
/* The GROUP level of the receive path. A target that has not named one keeps
   the value this file has always used; a target whose crank capture shares
   TGT_ILVL_SERIAL must name BOTH, because two enabled sources at one ILVL may
   not share a GLVL. See the ME7.1.1 hctarget.h for the measurement. */
#ifndef TGT_GLVL_SERIAL
#define TGT_GLVL_SERIAL  2
#endif
#ifdef TGT_TX_PIPELINE
#define HCTS_TX_END()  hcts_tx_end()
#else
#define HCTS_TX_END()
#endif

static const char SIGNATURE[]      = TGT_SIGNATURE;
static const char VERSIONTXT[]     = TGT_VERSIONTXT;
/* rusEFI's TS_PROTOCOL. TunerStudio uses the F reply to pick the ini. */
static const char TS_PROTOCOL_TXT[] = "001";

static unsigned char rxb[RXMAX];
/* A zero-length reply still needs a pointer to pass. */
/* THE ZERO-LENGTH REPLY'S POINTER, AND IT IS rxb ON PURPOSE.
   hcts_send_response() is always called with n = 0 here, so the pointer is
   never dereferenced - it only has to be a valid unsigned char *. A dedicated
   one-byte array cost a byte of NEAR RAM, which on this target is 1792 bytes
   with a 192-byte engineering reserve that near_ram_hazard_proof enforces. */
#define no_data  rxb
static unsigned char deferred_response;

unsigned int  rx_echo_lost;
unsigned int  rx_hw_ovr;
unsigned int  rx_frame_err;
unsigned int  rx_resync;
unsigned int  rx_bytes;
unsigned int  rx_reqs;
unsigned int  rx_idle;
unsigned int  probe_bad;
unsigned int  probe_s0ric;
unsigned int  probe_psw;
unsigned int  probe_ir;
unsigned char rx_irq_ok;
unsigned char rx_tick_ok;
unsigned int  rx_ticks;
unsigned char rx_irq_mode;
unsigned char echo_seen;
#ifdef TGT_S0BG_ALT
unsigned char hc_link_rate;            /* see "THE LINK RATE" below */
unsigned char hc_link_locked;
unsigned char hc_link_switches;
#endif
unsigned int  cfg_writes;
unsigned int  cfg_burns;
unsigned int  hc_stalls;
unsigned char hc_stall_req;
unsigned char hc_trace_on;
/* 1 while the calibration page is quiet. Declared in hcconfig.h and defined
   HERE because it is the shared server that writes the page: TunerStudio sends
   a 16-bit value as two separate one-byte writes, and anything that reads a
   multi-byte page value live has to know it is looking at the seam. */
unsigned char hc_cfg_stable = 1;

/* Assigned, not (void)-cast: C166 warns "expression with possibly no effect"
   on a bare read, and a read the compiler drops would defeat the discard. The
   sink is a LOCAL at its one use site rather than a file-scope byte: the read
   still happens, and near RAM does not pay for the discarded value. */

extern unsigned int hc_badvec;
extern volatile unsigned char hc_s0r_trap;
extern volatile unsigned char hc_s0r_learn;

/* ---------------------------------------------------------------- watchdog */
#ifdef TGT_RSTDIAG_WDT_COUNT
unsigned int hc_wdt_services;
#endif

void hc_srvwdt(void)
{
#ifdef TGT_WDTCON_SERVICE
    /* The target value is not a guessed timeout. Bosch ME7.1.1 loads 0xCF01
       at both normal-runtime service sites before calling its
       MOV WDTCON,R12 / SRVWDT primitive. Keep the write adjacent to the
       protected instruction and verify the emitted sequence in disassembly. */
    WDTCON = TGT_WDTCON_SERVICE;
#endif
    __asm { SRVWDT }
#ifdef TGT_SRVWDT_HOOK
    TGT_SRVWDT_HOOK();
#endif
#ifdef TGT_RSTDIAG_WDT_COUNT
    if (hc_wdt_services != 0xFFFFu) {
        hc_wdt_services++;
    }
#endif
}

/* Deliberately do nothing for n milliseconds - the stall acceptance test.
 *
 * It services the on-chip C167 watchdog and NOTHING else - no serial, no
 * telemetry. That is exactly the condition this exists to survive: on a target
 * whose safety responder runs from interrupts, a dead main loop must not cost
 * a single answer.
 *
 * The yield below is what makes that sentence still true on BOTH boards, and
 * it does the right thing on each WITHOUT a target test here:
 *
 *   ME7.5    the yield is EMPTY, so this really is a dead main loop and the
 *            test still proves exactly what it always proved - the UMKOM
 *            responder is on CC5/T8 interrupts and does not need this loop.
 *   Bosch  the responder is the S5500 exchange and IS driven from the main
 *            loop, so a genuinely dead loop would reset the ECU. The yield
 *            keeps the 10 ms raster alive. The stall then proves something
 *            weaker on this board - that is a property of the hardware, not a
 *            weakened test, and it is better than a bench command that resets
 *            the ECU. */
void hcts_stall(unsigned int ms)
{
    unsigned int i;
    unsigned int start;
    unsigned int tick = (unsigned int)US_TO_TICKS(1000u);

    for (i = 0; i < ms; i++) {
        start = T7;
        while ((unsigned int)(T7 - start) < tick) {
            hc_srvwdt();
            hcts_target_yield();
        }
    }
    hc_stalls++;
}

/* ================================================ ASC0 receive ring ======
 *
 * The hardware has ONE receive register. At 57600 baud a byte must be taken
 * out of it within 174 us or the next one overwrites it and is gone, and a
 * request that loses one byte is a request TunerStudio never gets answered.
 *
 * That deadline was being missed on the bench, and the log says exactly where:
 * at 6000 rpm on a 60-tooth wheel a tooth is 172 us, so the main loop and the
 * serial byte were competing for the same microseconds. Every unanswered
 * request in a 145 second session sat between 5886 and 7200 rpm; none at all
 * sat below 65 rpm.
 *
 * So the register is emptied by an INTERRUPT and the bytes wait in a ring. The
 * main loop may now be milliseconds late without a byte being lost.
 *
 * Single producer, single consumer, no critical section anywhere: the
 * interrupt only ever advances hc_rx_head, the main loop only ever advances
 * hc_rx_tail, and a byte write is atomic on this core.
 *
 * hcts_rx_pump() is the SAME producer running from the main loop, and the two
 * can never overlap: it returns immediately unless rx_irq_mode is 0, which is
 * only true while the receive interrupt is disabled.
 */
void hcts_rx_pump(void)
{
    if (rx_irq_mode) {
        return;
    }
    while (S0RIC & 0x80) {
        hc_rx_store((unsigned char)S0RBUF);
        S0RIC &= 0x7F;
    }
}

static unsigned char ts_st, ts_i;

unsigned char hcts_rx_pop(unsigned char *b)
{
    if (hc_rx_tail == hc_rx_head) {
        return 0;
    }
#ifdef TGT_RX_PEC
    if (HC_PECRX_GAP == (unsigned char)(hc_rx_tail | 128u)) {
        HC_PECRX_GAP = 0u; ts_st = 0u; ts_i = 0u; rx_resync++;
    }
#endif
    *b = hc_rx_ring[hc_rx_tail];
    hc_rx_tail = (unsigned char)((hc_rx_tail + 1u) & (HC_RXRING - 1u));
    return 1;
}

/* The K-line is a single bidirectional wire, so everything we transmit comes
   straight back into our OWN receiver. Measured on the bench: the ECU read the
   0x51 byte of its own reply CRC as a plain 'Q' command and answered with the
   signature, which desynchronised TunerStudio and made it reconnect every few
   seconds.                                    (ts_bridge.log, 2026-08-23)

   So every transmitted byte waits for its own echo and drops it. That is
   deterministic - the echo is guaranteed on a shared wire - and needs no
   timing constant, unlike a settle delay.

   echo_seen makes it self-calibrating: if the first byte of a response never
   echoes back, this wiring does not loop transmit into receive and the wait is
   skipped for the rest of that response. Costs one bounded timeout, and cannot
   stall the port on hardware that behaves differently. */
#ifdef TGT_TX_PIPELINE
/* PIPELINED ECHO ACCOUNTING (V94, a target opts in with TGT_TX_PIPELINE).
 *
 * The wait-for-my-own-echo above is exact but it is a BUBBLE: the next byte
 * cannot start until this byte's echo has crossed the CC7 drain (40 us tick)
 * and the loop has seen it. MEASURED on the real ECU (V93 r2, 57600,
 * tools/me711_link_timing.py): 238.7 us per reply byte against 173.6 us of
 * wire time - x1.375; at 124800 the same bubble would be ~80 % of the wire
 * time. So once the receive path is interrupt-drained (rx_irq_mode) the next
 * byte goes out as soon as the transmitter takes it, and the echoes are
 * dropped BY COUNT as they arrive: echo_pending counts bytes sent and not yet
 * seen back. The accounting is the same one-for-one drop, with the same
 * precondition (the ring holds nothing but our echo while we transmit - a
 * half-duplex host is silent while it is being answered), it is only no longer
 * serialised against the wire. A reply ends in hcts_tx_end(), which waits
 * (bounded) for the last echo so nothing of ours is left to be parsed.
 * Wiring that does not echo shows as a lag that keeps growing: past
 * HCTS_ECHO_LAG_MAX the response stops counting (echo_seen = 0), exactly as
 * the serial wait's timeout used to decide, but after a few bytes instead of
 * one 8000-pass timeout per response. The polled boot path is unchanged.
 *
 * AND THE WAIT IS ON THE TRANSMIT BUFFER, NOT THE FRAME. C167CR UM V3.1
 * section 11 (ASC0): transmission is DOUBLE BUFFERED; S0TBIR is raised when
 * S0TBUF moves into the shift register, S0TIR "before the last bit of a frame
 * is transmitted". Waiting on S0TIR leaves ONE BIT TIME (17 us at 57600,
 * 8 us at 124800) to fetch, CRC and load the next byte before the line goes
 * idle, and the wait loop's own yield is longer than that - the simulator
 * measured x1.47 byte times per byte with the echo bubble already gone. So
 * the byte is loaded, and the wait ends when it has moved into the shifter:
 * the next byte is computed while this one is on the wire, and a whole frame
 * time is the margin instead of a bit. Nothing here enables the S0TB
 * interrupt; S0TBIC is polled exactly as S0TIC was. */
#define HCTS_ECHO_LAG_MAX 6u
static unsigned char echo_pending;

static void echo_drain(void)
{
    unsigned char b;

    while (echo_pending != 0u && hcts_rx_pop(&b)) {
        echo_pending--;
    }
}

void hcts_tx_end(void)
{
    unsigned int guard = 8000u;

    while (echo_pending != 0u && --guard) {
        echo_drain();
        if (echo_pending == 0u) {
            break;
        }
        hc_srvwdt();
        hcts_target_yield();
    }
    if (echo_pending != 0u) {
        echo_pending = 0u;
        echo_seen = 0;
        rx_echo_lost++;
    }
}
#endif

#ifdef TGT_TX_ASYNC
static void async_echo_drain(void);
/* A blocking byte (KWP, the boot path) never overtakes a reply job. */
static void tx_async_idle(void)
{
    unsigned int guard = 40000u;
    while (hc_tx_busy() && --guard) {
        hc_srvwdt();
        hcts_target_yield();
    }
}
#endif

void hcts_tx(unsigned char c)
{
    unsigned int guard = 40000u;
    unsigned char b;
#ifdef TGT_TX_ASYNC
    tx_async_idle();
#endif

#ifdef TGT_TX_PIPELINE
    if (rx_irq_mode) {
        S0TBIC &= 0x7F;             /* the buffer-free request */
        S0TBUF = c;
        if (echo_seen) {
            echo_pending++;
        }
        /* until c has moved into the shift register - at once if the line
           is idle, at the end of the previous byte if it is not */
        while (((S0TBIC & 0x80) == 0) && --guard) {
            echo_drain();
            hc_srvwdt();
            hcts_target_yield();
        }
        echo_drain();
        if (echo_pending > HCTS_ECHO_LAG_MAX) {
            echo_pending = 0u;         /* this wiring does not echo to us */
            echo_seen = 0;
            rx_echo_lost++;
        }
        return;
    }
#endif
    S0TIC &= 0x7F;
    S0TBUF = c;
    while (((S0TIC & 0x80) == 0) && --guard) {
        hc_srvwdt();
        hcts_target_yield();      /* the 10 ms platform raster - see hcts.h */
    }
    S0TIC &= 0x7F;

    if (echo_seen) {
        guard = 8000u;
        if (rx_irq_mode) {
            /* Something else owns the receive register, so the echo will be
               waiting in the ring. */
            while (--guard) {
                if (hcts_rx_pop(&b)) {
                    break;             /* our own byte, discarded */
                }
                hc_srvwdt();
                hcts_target_yield();
            }
        } else {
            /* The direct poll, and it is the direct poll for a MEASURED
               reason. Routing this wait through the ring cost 0.89 ms per byte
               instead of 0.47, which doubled the boot banner and pushed
               start-up from 34 ms to 68 ms - close enough to the monitoring
               module's patience that the ECU came up in a reset loop. Nothing
               is receiving during boot anyway; this wait exists only to
               swallow our own echo so it is not read back as a command. */
            while (((S0RIC & 0x80) == 0) && --guard) {
                hc_srvwdt();
                hcts_target_yield();
            }
            if (guard) {
                {
                    /* volatile so the initialiser cannot be optimised away -
                       the READ of S0RBUF is the whole point. An assignment to
                       a plain local followed by (void) earns C138 "expression
                       with possibly no effect", and this build treats a
                       warning as a failure. */
                    volatile unsigned char rx_sink = (unsigned char)S0RBUF;
                }
                S0RIC &= 0x7F;
            }
        }
        if (!guard) {
            echo_seen = 0;             /* this wiring does not echo to us */
            rx_echo_lost++;
        }
    }
}

static unsigned char ts_pending;      /* defined with the parser below */

#ifdef TGT_TX_ASYNC
/* THE ECHO OF A REPLY JOB. The transmit interrupt counts what it loads
   (hc_tx_sent); the main loop counts what it has dropped from the ring as
   that echo. Two counters, one writer each - never a shared read-modify-
   write across levels. The ring holds nothing but our echo while we transmit
   (TunerStudio is half-duplex), so dropping by count is exact; a wiring that
   does not echo shows as a debt that is still there ECHO_WAIT after the job
   ended, and the rest of that response stops counting (echo_seen = 0). */
#define ECHO_WAIT_US 5000u
#define echo_owed()  hc_tx_echo_owed()

static void async_echo_drain(void)
{
    unsigned int owed = echo_owed();
#ifndef TGT_RX_PEC
    unsigned char b;
    while (owed != 0u && hcts_rx_pop(&b)) {
        hc_tx_echo_ate(0u);
        owed--;
    }
#endif
    /* TGT_RX_PEC: the tick drops the echo before it reaches the ring
       (hcserial711.c hc_pecrx_tick); only the forgiveness is left here. */
    if (owed != 0u && !hc_tx_busy()
        && hc_tx_echo_age() > (unsigned int)US_TO_TICKS(ECHO_WAIT_US)) {
        hc_tx_echo_ate(1u);              /* forgive the debt: no echo here */
        echo_seen = 0;
        rx_echo_lost++;
    }
}
#endif

/* See hcts.h. 40 ms rather than a flag alone, because a flag cannot tell the
   difference between "nothing is happening" and "a request is halfway in". */
unsigned char hcts_quiet(void)
{
    if (!hc_trace_on) {
        return 0;
    }
    /* A request that has been PARSED but not yet answered is the worst moment
       of all to start a line of text: the reply would be transmitted with the
       text already in front of it. ts_pending covers exactly that window. */
    if (ts_pending) {
        return 0;
    }
    if (rx_bytes == 0u) {
        return 1;
    }
    return (unsigned char)((unsigned int)(T7 - rx_idle)
                           > (unsigned int)US_TO_TICKS(40000u));
}

void hcts_puts(const char *s)
{
    while (*s) {
        hcts_tx((unsigned char)*s++);
    }
    HCTS_TX_END();
}

void hcts_hex4(unsigned int v)
{
    const char *d = "0123456789ABCDEF";

    hcts_tx((unsigned char)d[(v >> 12) & 0x0F]);
    hcts_tx((unsigned char)d[(v >> 8) & 0x0F]);
    hcts_tx((unsigned char)d[(v >> 4) & 0x0F]);
    hcts_tx((unsigned char)d[v & 0x0F]);
    HCTS_TX_END();
}

/* ------------------------------------------- which trap is ASC0 receive? --
 *
 * C167 trap numbers are CHECKED here, never assumed. ASC0 has a LOOPBACK bit,
 * S0LB, which ties the transmitter to the receiver INSIDE the chip: transmit
 * one byte with nothing else enabled and whichever vector is entered is the
 * receive interrupt, and says so in hc_s0r_trap.
 *
 * Loopback rather than the K-line echo, and that is the point. The first
 * attempt used the wire and reported s0rTrap 0 on the bench - no interrupt at
 * all - while the same echo worked perfectly once TunerStudio was talking. At
 * boot the K-line depends on its pull-up to 12 V and on the KKL adapter being
 * powered, neither of which is ours. S0LB depends on nothing outside the chip.
 *
 * WHY THE PROBE CAN LEGITIMATELY FIND NOTHING, and it is not a fault:
 * on every ME7.x image in this repo the FIRST-LEVEL interrupt vector for
 * S0RINT (trap 0x2B) and S0EINT (0x2C) jumps into the Bosch boot block rather
 * than forwarding to the application vector table. The boot block's own
 * handler is three instructions - it sets S0EIR and returns - and it is how
 * the flash bootstrap loader receives. So a HaniCore handler placed in the
 * application table for those traps is unreachable by construction.
 * See docs/ARCHITECTURE.md, "first-level vector ownership".
 *
 * That is why the CAPCOM fallback below is not a fallback on those targets but
 * the ONLY receive path, and why being wrong here costs nothing.
 */
void hcts_rx_learn(void)
{
    unsigned int mark;
#ifdef TGT_RX_PEC
    /* Nothing to learn: PEC6 is the receive path (hcserial711.h), and the
       S0RINT vector belongs to the boot block whatever this probe finds. */
    rx_irq_ok = 0;
    rx_tick_ok = 0;
    hc_rx_head = 0;
    hc_rx_tail = 0;
    return;
#endif

    hc_rx_head = 0;
    hc_rx_tail = 0;
    hc_rx_ovf = 0;
    rx_irq_mode = 1;              /* keep hcts_rx_pump() off the register */
    hc_s0r_trap = 0;
    hc_s0r_learn = 1;

    S0RIC = HC_IC(TGT_ILVL_SERIAL, TGT_GLVL_SERIAL);
    IEN = 1;

    /* Inside the chip, so nothing about the wire can make this inconclusive. */
    S0LB = 1;

    S0TIC &= 0x7F;
    S0TBUF = 0x00;
    mark = T7;
    while (((S0TIC & 0x80) == 0)
           && (unsigned int)(T7 - mark) < (unsigned int)US_TO_TICKS(1000u)) {
        hc_srvwdt();
    }
    S0TIC &= 0x7F;

    /* Half a millisecond is three byte times - far more than the answer needs
       and far less than any monitoring module's patience. */
    mark = T7;
    probe_ir = 0;
    while ((hc_s0r_trap == 0)
           && (unsigned int)(T7 - mark) < (unsigned int)US_TO_TICKS(500u)) {
        if (S0RIC & 0x80) {
            probe_ir = 1;         /* the byte arrived; the rest is up to the
                                     interrupt system, not to the serial port */
        }
        hc_srvwdt();
    }
    probe_s0ric = S0RIC;
    probe_psw = PSW;

    S0LB = 0;
    IEN = 0;
    S0RIC = 0;
    hc_s0r_learn = 0;
    rx_irq_ok = (unsigned char)(hc_s0r_trap != 0);
    /* Evidence, captured BEFORE main() clears the vector counters. */
    probe_bad = hc_badvec;

    /* The insurance policy: a CAPCOM1 compare tick that empties the receive
       register on a fixed HC_RXTICK_US period. CAPCOM1 compares are proven on
       this board, so this does not depend on whatever is wrong with ASC0's own
       interrupt node.

       Checked, not assumed: arm it, wait, and see whether the tick moved. If
       it did not, it is disarmed again and the receiver goes back to polling
       exactly as before. */
    if (!rx_irq_ok) {
        unsigned int mark2;

        /* Compare mode 0 on CC7, read-modify-write so any capture channel
           sharing CCM1 is untouched. */
        CCM1 = (unsigned int)((CCM1 & ~0xF000u) | 0x4000u);
        rx_ticks = 0;
        CC7 = (unsigned int)(T0 + (unsigned int)US_TO_TICKS(HC_RXTICK_US));
        CC7IC = HC_IC(TGT_ILVL_SERIAL, TGT_GLVL_SERIAL);
        IEN = 1;

        mark2 = T7;
        while ((rx_ticks < 4u)
               && (unsigned int)(T7 - mark2) < (unsigned int)US_TO_TICKS(2000u)) {
            hc_srvwdt();
        }

        IEN = 0;
        rx_tick_ok = (unsigned char)(rx_ticks >= 4u);
        if (!rx_tick_ok) {
            CC7IC = 0;
            CCM1 &= (unsigned int)~0xF000u;
        }
    }

    /* Back to polling for the rest of the boot: the banner runs before
       anything is armed, and the drain is switched on with everything else. */
    rx_irq_mode = 0;
    hc_rx_head = 0;
    hc_rx_tail = 0;               /* drop the probe byte */
}

void hcts_rx_arm(void)
{
#ifdef TGT_RX_PEC
    hc_rx_head = 0;
    hc_rx_tail = 0;
    hc_pecrx_arm();
    rx_irq_mode = 1;              /* PEC6 owns S0RBUF from here */
    return;
#endif
    if (!(rx_irq_ok || rx_tick_ok)) {
        return;                   /* stay polled - the behaviour it replaces */
    }
    hc_rx_head = 0;
    hc_rx_tail = 0;
    rx_irq_mode = 1;              /* something other than the loop owns S0RBUF */
    if (rx_irq_ok) {
        S0RIC = HC_IC(TGT_ILVL_SERIAL, TGT_GLVL_SERIAL);
    } else {
        CC7 = (unsigned int)(T0 + (unsigned int)US_TO_TICKS(HC_RXTICK_US));
        CC7IC = HC_IC(TGT_ILVL_SERIAL, TGT_GLVL_SERIAL);
    }
}

/* The fallback drain. See TGT_TRAP_CC7INT in hctarget.h for why it exists.
 * It reprograms its own compare, so the interval is exact and independent of
 * anything the main loop does.
 *
 * THIS IS THE HIGHEST-RATE HANDLER IN THE SYSTEM: HC_RXTICK_US is 40 us, so it
 * runs 25 times every millisecond. Everything it costs is multiplied by 25 000
 * per second, which is why the register cost below is worth a paragraph.
 *
 * WHY THE RING STORE IS WRITTEN OUT HERE INSTEAD OF CALLING hc_rx_store().
 * hc_rx_store() lives in the target's hcvec module, so calling it is a
 * cross-module call. Keil cannot see the callee's register usage, so it must
 * assume the worst and emit RMASK = @0x7FFF: the generated prologue was
 *
 *     SCXT DPP3 / PUSH DPP0 / SCXT MDC / PUSH MDH / PUSH MDL / PUSH R1..R12
 *
 * - 17 instructions in, 18 out, 35 of context save and restore wrapped around
 * an 11-instruction fast path. Three quarters of the handler was spent saving
 * registers for a callee that touches four of them, and MDC/MDH/MDL were
 * saved for a multiply-divide unit nothing on this path uses.
 *
 * Written inline the compiler can see the whole handler and saves only what it
 * really uses. The logic is IDENTICAL to hc_rx_store(), deliberately: same
 * bounded ring, same head/tail discipline, same overflow counter. That
 * function stays where it is for its other two callers - the polled fallback
 * in this file and hc_rx_take() in the vector module - because neither runs at
 * 25 kHz and neither is worth duplicating code for.
 *
 * If you change the ring discipline, change it in BOTH places.
 * tests/test_rx_drain_isr.py fails if these two ever disagree. */
#ifndef TGT_RX_PEC
void hc_cc7_isr(void) interrupt TGT_TRAP_CC7INT
{
    HC_PROBE_CLAIM(TGT_TRAP_CC7INT);

    CC7 = (unsigned int)(CC7 + (unsigned int)US_TO_TICKS(HC_RXTICK_US));
    /* If that moment has already passed - this handler ran late behind a crank
       interrupt - the compare would not match again until T0 wrapped 43.7 ms
       later and the drain would simply STOP. Catch up to real time instead.
       EQUAL IS ALSO PASSED: a compare fires when T0 is incremented TO the
       value - C167CR UM ch. 15 - so CC7 == T0 here, a handler exactly one
       tick period late, waits a whole wrap: 52.4 ms. Under engine + K-line
       load the stress rig measured exactly that gap; the regression is
       tests/firmware/comms/me711_rx_drain_rearm_proof.py. */
    if ((int)(CC7 - T0) <= 0) {
        CC7 = (unsigned int)(T0 + (unsigned int)US_TO_TICKS(HC_RXTICK_US));
    }
    if (S0RIC & 0x80) {
        /* Read FIRST, then clear. Clearing first would risk clearing the flag
           of a byte that arrived in between, and a lost interrupt stops the
           port for good where a lost byte only costs one request. */
        unsigned char b = (unsigned char)S0RBUF;
        unsigned char h = (unsigned char)((hc_rx_head + 1u)
                                          & (HC_RXRING - 1u));

        if (h != hc_rx_tail) {
            hc_rx_ring[hc_rx_head] = b;
            hc_rx_head = h;
        } else {
            hc_rx_ovf++;          /* the MAIN LOOP fell behind, not this ISR */
        }
        S0RIC &= 0x7F;
    }
    rx_ticks++;
}
#endif /* !TGT_RX_PEC */

/* ------------------------------------------------------------------- CRC32 */
/* Standard IEEE CRC-32, reflected, init/final 0xFFFFFFFF - the same one
   zlib.crc32 produces. One byte at a time, so a reply can be CRC'd AS IT IS
   TRANSMITTED and never has to be assembled in a buffer first. That is what
   lets the output-channel block be answered in ONE request instead of three. */
static unsigned long crc32_byte(unsigned long crc, unsigned char b)
{
    unsigned char k;

    crc ^= (unsigned long)b;
    for (k = 0; k < 8; k++) {
        if (crc & 1uL) {
            crc = (crc >> 1) ^ 0xEDB88320uL;
        } else {
            crc >>= 1;
        }
    }
    return crc;
}

unsigned long hcts_crc32(unsigned char *p, unsigned int n)
{
    unsigned long crc = 0xFFFFFFFFuL;
    unsigned int i;
#ifdef TGT_TX_ASYNC
    /* <= RXMAX bytes through the nibble table: no wait, no yield needed */
    for (i = 0; i < n; i++) {
        crc = hc_crc32_update(crc, p[i]);
    }
    return crc ^ 0xFFFFFFFFuL;
#else
    unsigned char k;

    for (i = 0; i < n; i++) {
        crc ^= (unsigned long)p[i];
        for (k = 0; k < 8; k++) {
            if (crc & 1uL) {
                crc = (crc >> 1) ^ 0xEDB88320uL;
            } else {
                crc >>= 1;
            }
        }
        hc_srvwdt();
        hcts_target_yield();
    }
    return crc ^ 0xFFFFFFFFuL;
#endif
}

/* ---------------------------------------------------------------- response */
/* The reply is CRC'd and transmitted in one pass, straight out of the caller's
   buffer. It used to be copied into a txb[] first, which put a hard ceiling on
   a reply and forced TunerStudio to read the channel block in THREE requests
   of 64. Streaming removes the ceiling and the buffer with it. */
#ifdef TGT_TX_ASYNC
/* START A REPLY AND RETURN (hcserial711.h). The main loop runs on while the
   transmit interrupt streams it; hcts_service() takes no new request until it
   is out and its echo is home. echo_seen is re-armed per response, as the
   blocking path always did. */
static void tx_async(unsigned char kind, unsigned char code, unsigned int off,
                     unsigned int n, const unsigned char *src)
{
    echo_seen = 1;
    tx_async_idle();
    (void)hc_tx_start(kind, code, off, n, src);
}
#endif

static void send_page(unsigned int off, unsigned int n)
{
    unsigned long c;
    unsigned int i;
    unsigned char b;
#ifdef TGT_TX_ASYNC
    tx_async(HC_TXK_PAGE, TS_OK, off, n, (const unsigned char *)0);
    return;
#endif

    echo_seen = 1;

    hcts_tx((unsigned char)(((n + 1) >> 8) & 0xFF));
    hcts_tx((unsigned char)((n + 1) & 0xFF));

    c = 0xFFFFFFFFuL;
    c = crc32_byte(c, TS_OK);
    hcts_tx(TS_OK);
    for (i = 0; i < n; i++) {
        b = hcts_cfg_read((unsigned int)(off + i));
        c = crc32_byte(c, b);
        hcts_tx(b);
    }
    c ^= 0xFFFFFFFFuL;

    hcts_tx((unsigned char)((c >> 24) & 0xFF));
    hcts_tx((unsigned char)((c >> 16) & 0xFF));
    hcts_tx((unsigned char)((c >> 8) & 0xFF));
    hcts_tx((unsigned char)(c & 0xFF));
    HCTS_TX_END();
}

#ifdef HCTS_TARGET_LOGGER
static unsigned char send_tlog;   /* send_och() serves the tooth log */
#endif

static void send_och(unsigned int off, unsigned int n)
{
    unsigned long c;
    unsigned int i;
    unsigned char b;
#ifdef TGT_TX_ASYNC
#ifdef HCTS_TARGET_LOGGER
    if (send_tlog) {
        tx_async(HC_TXK_TLOG, TS_OK, off, n, (const unsigned char *)0);
        return;
    }
#endif
    tx_async(HC_TXK_OCH, TS_OK, off, n, (const unsigned char *)0);
    return;
#endif

    echo_seen = 1;

    hcts_tx((unsigned char)(((n + 1) >> 8) & 0xFF));
    hcts_tx((unsigned char)((n + 1) & 0xFF));

    c = 0xFFFFFFFFuL;
    c = crc32_byte(c, TS_OK);
    hcts_tx(TS_OK);
    for (i = 0; i < n; i++) {
#ifdef HCTS_TARGET_LOGGER
        if (send_tlog) {
            b = (unsigned char)HCTS_TARGET_TLOG_BYTE((unsigned int)(off + i));
        } else
#endif
        if ((unsigned int)(off + i) < (unsigned int)TGT_OCH_SIZE) {
            b = OCH_BYTE((unsigned int)(off + i));
        } else {
            b = (unsigned char)HCTS_TARGET_OCH_EXT_READ(
                (unsigned int)(off + i - TGT_OCH_SIZE));
        }
        c = crc32_byte(c, b);
        hcts_tx(b);
    }
    c ^= 0xFFFFFFFFuL;

    hcts_tx((unsigned char)((c >> 24) & 0xFF));
    hcts_tx((unsigned char)((c >> 16) & 0xFF));
    hcts_tx((unsigned char)((c >> 8) & 0xFF));
    hcts_tx((unsigned char)(c & 0xFF));
    HCTS_TX_END();
}

void hcts_send_response(unsigned char code, unsigned char *data, unsigned int n)
{
    unsigned long c;
    unsigned int i;
#ifdef TGT_TX_ASYNC
    if (n <= HC_TX_BUF_N) {
        tx_async(HC_TXK_BUF, code, 0u, n, data);
        return;
    }
#endif

    echo_seen = 1;            /* re-test the wiring on every response */

    hcts_tx((unsigned char)(((n + 1) >> 8) & 0xFF));
    hcts_tx((unsigned char)((n + 1) & 0xFF));

    c = 0xFFFFFFFFuL;
    c = crc32_byte(c, code);
    hcts_tx(code);
    for (i = 0; i < n; i++) {
        c = crc32_byte(c, data[i]);
        hcts_tx(data[i]);
    }
    c ^= 0xFFFFFFFFuL;

    hcts_tx((unsigned char)((c >> 24) & 0xFF));
    hcts_tx((unsigned char)((c >> 16) & 0xFF));
    hcts_tx((unsigned char)((c >> 8) & 0xFF));
    hcts_tx((unsigned char)(c & 0xFF));
    HCTS_TX_END();
}

static void send_text(const char *s)
{
    unsigned char tmp[64];
    unsigned int n = 0;

    while (s[n] && n < sizeof(tmp)) {
        tmp[n] = (unsigned char)s[n];
        n++;
    }
    hcts_send_response(TS_OK, tmp, n);
}

/* -------------------------------------------------- plain legacy commands */
/* While TunerStudio is still detecting the ECU it sends bare single-byte
   commands with no envelope and expects a bare answer. Only after that does it
   switch to the CRC envelope. Measured on the bench: TunerStudio repeated 'F'
   then 'S' every ~8 s and never got past detection, because this firmware
   answered nothing but envelopes.

   rusEFI's own firmware makes exactly this split - see
   rusEFI firmware/console/binary/tunerstudio.cpp,
   TunerStudio::handlePlainCommand(): a first byte of 0x00 is the high byte of
   an envelope length, anything else is a legacy plain command. Our payloads
   are far below 256 bytes, so that high byte is always 0. */
static void send_plain(const char *s, unsigned char with_nul)
{
#ifdef TGT_TX_ASYNC
    unsigned char tmp[HC_TX_BUF_N];
    unsigned int n = 0u;
    while (s[n] && n < HC_TX_BUF_N - 1u) {
        tmp[n] = (unsigned char)s[n];
        n++;
    }
    if (with_nul) tmp[n++] = 0u;            /* rusEFI: strlen + 1 */
    tx_async(HC_TXK_PLAIN, 0u, 0u, n, tmp);
    return;
#endif
    echo_seen = 1;
    while (*s) {
        hcts_tx((unsigned char)*s++);
    }
    if (with_nul) {
        hcts_tx(0);              /* rusEFI sends strlen(signature) + 1 */
    }
    HCTS_TX_END();
}

static void handle_plain(unsigned char cmd)
{
    switch (cmd) {
    case 'S':
    case 'Q':               /* TunerStudio hardcodes 'Q' when scanning ports */
        send_plain(SIGNATURE, 1);
        return;
    case 'C':
    case 'T':
        send_plain(VERSIONTXT, 0);
        return;
    case 'F':
        send_plain(TS_PROTOCOL_TXT, 0);
        return;
    case 'z':
#ifdef TGT_S0BG_ALT
        /* A byte received at another rate is 0x7A often enough to matter
           while the link hunts; a 200 ms stall is a bench act, so it needs a
           link that has carried a CRC-valid frame. */
        if (!hc_link_locked) {
            return;
        }
#endif
        /* Bench diagnostic: ask the main loop to stall. Only a REQUEST is set
           here - this runs from inside wait loops, and a stall taken there
           would sit inside the serial handler rather than in the main loop
           proper. The main loop consumes it at the top of its next pass. */
        hc_stall_req = 200;
        send_plain("stall", 0);
        return;
    default:
        return;             /* unknown plain command: stay silent, resync */
    }
}

/* ------------------------------------------------------ the CRC envelope --*/
static void handle(unsigned char *p, unsigned int n)
{
    unsigned char cap[5];
    unsigned char burn_code;
    unsigned int i;
    unsigned int off;
    unsigned int cnt;

    switch (p[0]) {
    case 'S':
    case 'Q':
        send_text(SIGNATURE);
        return;
    case 'V':
        send_text(VERSIONTXT);
        return;
    case 'F':
        send_text(TS_PROTOCOL_TXT);
        return;
    case 'C':
        cap[0] = 0xFF;
        hcts_send_response(TS_OK, cap, 1);
        return;
    case 'I':
        cap[0] = 0;
        hcts_send_response(TS_OK, cap, 1);
        return;
    case 'f':
        cap[0] = 2;
        cap[1] = (BLOCKING >> 8) & 0xFF;
        cap[2] = BLOCKING & 0xFF;
        cap[3] = (BLOCKING >> 8) & 0xFF;
        cap[4] = BLOCKING & 0xFF;
        hcts_send_response(TS_OK, cap, 5);
        return;
#ifdef HCTS_TARGET_LOGGER
    case 'l':
        /* TUNERSTUDIO'S HIGH SPEED LOGGERS (rusEFI TS_SET_LOGGER_SWITCH:
           1 composite on, 7 primary-tooth on, 2 off, 3 read). Every answer
           is TS_OK - an EMPTY buffer is TS_OK with no data, never rusEFI's
           0x84: any bit-7 code ends the TunerStudio session (hcts.h). */
        cnt = HCTS_TARGET_LOGGER((unsigned char)((n >= 2u) ? p[1] : 0u));
        send_tlog = 1u;
        send_och(0u, cnt);
        send_tlog = 0u;
        if (cnt != 0u) {
            (void)HCTS_TARGET_LOGGER(0x80u);       /* read: buffer free */
        }
        return;
#endif
    case 'O':
    case 'A':
        /* Serve the block as it stands. It used to call the telemetry composer
           first, which meant a full ADC sweep before every reply - 30 ms of
           latency on a 4 ms reply, and a blocked loop that dropped the NEXT
           request. The block is refreshed once per frame in the main loop
           instead, so it is at most a frame stale, which is what rusEFI does.

           ochGetCommand is "O%2o%2c", so TunerStudio always names an offset
           and a length. Honour them instead of always returning the whole
           block: a project still holding an older .ini asks for fewer bytes
           than we publish, and answering with more is a protocol error that
           made TunerStudio drop and reconnect forever.
                                              (ts_bridge.log, 2026-08-23) */
        off = 0;
        cnt = TGT_OCH_SIZE;
        if (n >= 5) {
            off = ((unsigned int)p[1] << 8) | p[2];
            cnt = ((unsigned int)p[3] << 8) | p[4];
        }
        if (off > TGT_OCH_READ_SIZE) {
            off = TGT_OCH_READ_SIZE;
        }
        if (cnt > (unsigned int)(TGT_OCH_READ_SIZE - off)) {
            cnt = (unsigned int)(TGT_OCH_READ_SIZE - off);
        }
        send_och(off, cnt);
        return;
    case 'W':
        /* pageValueWrite is "W%2o%v": a 16-bit offset then the value, whose
           length TunerStudio takes from the field's type in the .ini. The page
           is stored big-endian precisely so this is a straight byte copy.

           Note 'C' is NOT used for pageChunkWrite: TunerStudio already uses
           'C' as test comms, so the .ini deliberately omits chunk writes and
           every edit arrives one value at a time. Slower, unambiguous. */
        if (n >= 4) {
            off = ((unsigned int)p[1] << 8) | p[2];
            cnt = n - 3;
            if (off < PAGE_SIZE) {
                if (cnt > (unsigned int)(PAGE_SIZE - off)) {
                    cnt = (unsigned int)(PAGE_SIZE - off);
                }
                for (i = 0; i < cnt; i++) {
                    hcts_cfg_write((unsigned int)(off + i), p[3 + i]);
                }
                cfg_writes++;
            }
        }
        hcts_send_response(TS_OK, no_data, 0);
        return;
    case 'B':
        /* Burn. The target snapshots and validates the calibration, then holds
           this reply until its bounded append-only flash transaction has
           reached DONE and the runtime is ready for the next command. */
        /* The staging snapshot keys itself to this generation.  Advance it
           before the target records the request, otherwise the first staging
           pass needlessly discards and restarts a perfectly good snapshot. */
        BF_B_RECEIVED();
        cfg_burns++;
        burn_code = hcts_cfg_burn();
        if (deferred_response == 0u) {
            /* ANSWERED WITH WHAT THE TARGET SAID, NOT WITH A LITERAL.
               A Burn the target declines on the spot - no external SRAM, so
               nothing can be staged - was answered TS_OK from here because
               this line said TS_OK, not because anything had decided it
               should. The choice belongs to the target, which is the only
               thing that knows what happened.

               It still emits 0x00 today, and deliberately: TS_REFUSED IS
               TS_OK, because TunerStudio ends the session on every response
               code with bit 7 set and there is no other kind (hcts.h). So
               this changes who decides, not what goes out - and when the
               protocol one day has somewhere to put a refusal, one line in
               the target is where it goes. */
            BF_RESPONSE_SELECTED(burn_code);
            BF_TX_ENTERED();
            hcts_send_response(burn_code, no_data, 0);
            BF_TX_COMPLETED();
        }
        return;
    case '!':
        /* Everything that is a deliberate, one-off action rather than a
           setting. The letter is '!' and not something readable because every
           readable one is already TunerStudio's. Board specific, so it goes
           out to the target. */
        hcts_target_cmd(p, n);
        hcts_send_response(TS_OK, no_data, 0);
        return;
    case 'P':   /* page select - there is only one */
        hcts_send_response(TS_OK, no_data, 0);
        return;
    case 'R':
    case 'p':
        /* The real configuration page. TunerStudio reads it in blockingFactor
           sized chunks, so honour the offset and count it asks for and clamp
           to what actually exists - answering with more bytes than requested
           is what made it reconnect in a loop on the output channels. */
        off = 0;
        cnt = PAGE_SIZE;
        if (n >= 5) {
            off = ((unsigned int)p[1] << 8) | p[2];
            cnt = ((unsigned int)p[3] << 8) | p[4];
        }
        if (off > PAGE_SIZE) {
            off = PAGE_SIZE;
        }
        if (cnt > (unsigned int)(PAGE_SIZE - off)) {
            cnt = (unsigned int)(PAGE_SIZE - off);
        }
        send_page(off, cnt);
        return;
    default:
        /* THE ONLY TS_BAD_CMD IN THE FIRMWARE, and it must stay that way.
           0x83 is TS_RESPONSE_UNRECOGNIZED_COMMAND and it says the command
           BYTE is unknown. A command this switch has an arm for is never
           unrecognised, however badly it goes - see hcts.h. */
        hcts_send_response(TS_BAD_CMD, no_data, 0);
        return;
    }
}

/* ============================================ non-blocking TunerStudio RX ==
 *
 * The serial server used to block in a byte-wait loop, which is fine on its
 * own but fatal next to a watchdog: the hard rule is that serial must never
 * delay watchdog timing. So receiving is a state machine fed one byte at a
 * time from whatever wait loop happens to be running.
 */
/* BOUNDED BY RXMAX (72) AND BY 4, so these are bytes and not words - the
   parser rejects any length above RXMAX before ts_len is assigned. Two bytes
   of near RAM, which is the difference between meeting this target's
   192-byte engineering reserve and not. */
static unsigned char ts_len;
static unsigned long ts_got;
static unsigned char ts_plain_cmd;

#ifdef TGT_S0BG_ALT
/* THE LINK RATE (V94, a target opts in with TGT_S0BG_ALT/_ALT2).
 *
 * One ECU image answers at 57600 (TGT_S0BG, the proven default it boots at),
 * at 115200 nominal (TGT_S0BG_ALT: the value TunerStudio's own baud list
 * offers) and at 124800 (TGT_S0BG_ALT2: exact on this clock, the rate the
 * KKL already runs the flash loader at). The HOST picks the rate; the ECU
 * follows it on evidence, so plain TunerStudio needs no plugin and a link
 * that cannot hold a fast rate falls back by setting the host slower.
 *
 *   LOCKED   a request arrived with a VALID CRC32 at this rate. Nothing but
 *            evidence of a different rate moves it: LINK_BAD_LOCKED framing
 *            errors or bad CRCs with no good frame in between.
 *   HUNTING  (at boot, and after a lock broke) ONE framing error or bad CRC
 *            moves to the next rate. A byte sent at another rate cannot pass
 *            the envelope's CRC32, and it almost always breaks framing
 *            (124800 into a 57600 receiver samples its stop bit 2.2 bytes
 *            in; 57600 into 124800 samples it mid-byte) - so hunting costs
 *            the host at most two retried requests per rate change.
 *
 * Never while a reply is being sent or held (hcts_poll runs between replies,
 * and a deferred Burn reply blocks it). A switch drops the ring and the
 * half-parsed frame: they were received at the wrong rate. The rate is
 * published (hcts_link_state) so a log says which one a session ran at. */
static const unsigned char link_bg[3] = { TGT_S0BG, TGT_S0BG_ALT,
                                          TGT_S0BG_ALT2 };
#define LINK_BAD_LOCKED 3u
static unsigned char link_bad;

/* ONE PIECE OF EVIDENCE PER BURST, AND A SWITCH DROPS THE REST OF IT.
 *
 * Measured on the bench (V94, 2026-09-28): a host at 115200 was NEVER
 * followed. Its bytes, seen by a 57600 receiver, mostly carry NO framing
 * error - a 'V' request decodes as 18 CF 58 FD, four clean bytes - and the
 * parser took each as an unknown plain command and dropped it silently, so
 * the rate never moved (rxFrameErr stayed 0 over 36 requests). The simulator
 * gate had modelled every wrong-rate byte WITH a framing error. So bytes that
 * cannot start a request at the right rate - an unknown plain command, an
 * impossible length - are evidence now, like a framing error or a bad CRC.
 *
 * Once a request yields evidence its remaining bytes would yield more; the
 * burst counts ONCE (link_hold 1), and after a switch its tail, received at
 * the new rate as noise, is dropped rather than parsed (link_hold 2). Both
 * end when the line has been quiet LINK_QUIET_US. A locked link therefore
 * needs LINK_BAD_LOCKED separate bad requests to move, and a hunting one
 * moves one rate per request. */
#define LINK_QUIET_US   2000u
static unsigned char link_hold;
static unsigned char link_evid;         /* published: hcts_link_evid() */

static void link_set(unsigned char r)
{
    unsigned int w;

    hc_link_rate = r;
    w = S0CON;
    S0CON = (unsigned int)(w & ~0x8000u);      /* S0R = 0: S0BG may change */
    S0BG = link_bg[r];
    S0CON = (unsigned int)((w & ~0x0700u) | 0x8000u);
}

/* One piece of evidence that the host is at another rate. -> 1 if the
   rate moved (the caller must not answer: the answer would leave at the new
   rate, as noise). */
static unsigned char link_bad_seen(void)
{
    if (deferred_response != 0u) {
        return 0u;
    }
#ifdef TGT_TX_ASYNC
    if (hc_tx_busy()) {
        return 0u;
    }
#endif
#ifdef HCTS_TARGET_LINK_HOLD
    if (HCTS_TARGET_LINK_HOLD()) {
        return 0u;          /* a 5-baud byte / KWP session owns the line */
    }
#endif
    if (link_hold != 0u) {
        return 0u;          /* this burst has already been counted */
    }
    link_hold = 1u;
    rx_idle = T7;           /* the quiet timer starts at the evidence */
    link_bad++;
    link_evid++;
    if (hc_link_locked && link_bad < LINK_BAD_LOCKED) {
        return 0u;
    }
    link_set((unsigned char)((hc_link_rate + 1u) % 3u));
    hc_link_locked = 0u;
    link_bad = 0u;
    link_hold = 2u;         /* and drop the rest of it */
    /* AND RESTART THE QUIET TIMER HERE. The switch empties the ring, so
       no byte is popped and rx_idle still dated from the PREVIOUS request:
       the 2 ms test passed on the next poll, the rest of this same request -
       arriving at the new rate as garbage - counted as fresh evidence and
       the hunt lapped all three rates (V95 bench: a locked 115200 -> 124800
       change took 4 switches instead of 1; 2 of 36 host changes needed more
       than 8 requests). */
    rx_idle = T7;
    hc_link_switches++;
#ifdef TGT_RX_PEC
    hc_pecrx_flush();
#endif
    hc_rx_tail = hc_rx_head;                   /* bytes of the old rate */
    ts_st = 0;
    ts_i = 0;
    return 1u;
}

/* A target puts the line at a rate it negotiated some other way (the KWP
   vehicle entry: 10400 for the handshake, then the GOFAST rate) - LOCKED or
   not. A rate outside link_bg[] reports as 3. */
void hcts_link_force(unsigned char bg, unsigned char locked)
{
    unsigned char i;
    unsigned int w;

    for (i = 0u; i < 3u && link_bg[i] != bg; i++) {
    }
    hc_link_rate = i;
    w = S0CON;
    S0CON = (unsigned int)(w & ~0x8000u);
    S0BG = bg;
    S0CON = (unsigned int)((w & ~0x0700u) | 0x8000u);
    hc_link_locked = locked;
    link_bad = 0u;
    link_hold = 0u;
    hc_link_switches++;
#ifdef TGT_RX_PEC
    hc_pecrx_flush();
#endif
    hc_rx_tail = hc_rx_head;
    ts_st = 0;
    ts_i = 0;
}

/* Back to the boot rate, hunting. */
void hcts_link_hunt(void)
{
    link_set(0u);
    hc_link_locked = 0u;
    link_bad = 0u;
    link_hold = 0u;
    hc_link_switches++;
#ifdef TGT_RX_PEC
    hc_pecrx_flush();
#endif
    hc_rx_tail = hc_rx_head;
    ts_st = 0;
    ts_i = 0;
}

unsigned char hcts_link_evid(void)
{
    return link_evid;
}

unsigned int hcts_link_state(void)
{
    return (unsigned int)(((unsigned int)hc_link_switches << 8)
                          | (hc_link_locked ? 0x10u : 0u)
                          | (hc_link_rate & 3u));
}
#define LINK_FE_SEEN()  (void)link_bad_seen()
#define LINK_JUNK_SEEN() (void)link_bad_seen()
#else
#define LINK_FE_SEEN()
#define LINK_JUNK_SEEN()
unsigned int hcts_link_state(void)
{
    return 0u;
}

unsigned char hcts_link_evid(void)
{
    return 0u;
}
#endif

void hcts_defer_response(void)
{
    deferred_response = 1u;
    BF_REPLY_ARMED();
}

void hcts_finish_deferred_response(unsigned char code)
{
    if (deferred_response != 0u) {
        deferred_response = 0u;
        BF_RESPONSE_SELECTED(code);
        BF_TX_ENTERED();
        hcts_send_response(code, no_data, 0u);
        BF_TX_COMPLETED();
    }
}

void hcts_poll(void)
{
    unsigned char b;
    unsigned int w;

#ifdef TGT_S0BG_ALT
    if (link_hold != 0u
        && (unsigned int)(T7 - rx_idle) > (unsigned int)US_TO_TICKS(LINK_QUIET_US)) {
        link_hold = 0u;     /* the burst is over */
    }
#endif
    /* The error flags are sticky, so one look per pass cannot miss one. Clear
       only the three error bits and write the rest of S0CON back unchanged. */
    w = S0CON;
    if (w & 0x0700u) {
        if (w & 0x0400u) {
            rx_hw_ovr++;            /* a byte was destroyed in the register */
        }
        if (w & 0x0200u) {
            rx_frame_err++;         /* the wire, not us */
        }
        S0CON = (unsigned int)(w & ~0x0700u);
        if ((w & 0x0200u) && !ts_pending) {
            LINK_FE_SEEN();         /* or a host at another rate */
        }
    }

    /* Non-PEC links expire a partial frame during idle. PEC publishes a
       quiet-gap marker at the RX ring boundary; hcts_rx_pop resets before
       taking the first following byte, even if the parser missed the silence. */
    hcts_rx_pump();
#ifndef TGT_RX_PEC
    if (ts_st != 0 && !ts_pending && hc_rx_tail == hc_rx_head
        && (unsigned int)(T7 - rx_idle) > (unsigned int)US_TO_TICKS(20000u)) {
        ts_st = 0;
        ts_i = 0;
        rx_resync++;
    }
#endif

    /* Bytes come out of the ring, never off the hardware - and never while
       an echo of ours is still owed (a sender that forgot hcts_tx_end). */
    HCTS_TX_END();
#ifdef TGT_TX_ASYNC
    async_echo_drain();
    while (!ts_pending && !hc_tx_busy() && echo_owed() == 0u) {
#else
    while (!ts_pending) {
#endif
        hcts_rx_pump();
        if (!hcts_rx_pop(&b)) {
            break;
        }
        rx_bytes++;
        rx_idle = T7;
#ifdef HCTS_TARGET_RX_TAKE
        if (HCTS_TARGET_RX_TAKE(b)) {
            continue;       /* the target's (KWP) byte, not a request */
        }
#endif
#ifdef TGT_S0BG_ALT
        if (link_hold == 2u) {
            continue;       /* the tail of the burst that moved the rate */
        }
#endif
        switch (ts_st) {
        case 0:
            if (b != 0x00) {
                if (b == 'S' || b == 'Q' || b == 'C' || b == 'T' || b == 'F'
                    || b == 'z') {
                    ts_plain_cmd = b;       /* handle_plain()'s whole list */
                    ts_pending = 2;
                    hc_trace_on = 0;
                } else {
                    LINK_JUNK_SEEN();       /* no request starts like this */
                }
            } else {
                ts_st = 1;
                hc_trace_on = 0;
            }
            break;
        case 1:
            if (b == 0 || b > RXMAX) {
                ts_st = 0;                     /* resync */
                LINK_JUNK_SEEN();              /* an impossible length */
            } else {
                ts_len = b;
                ts_i = 0;
                ts_st = 2;
            }
            break;
        case 2:
            rxb[ts_i++] = b;
            if (ts_i >= ts_len) {
                ts_i = 0;
                ts_got = 0;
                ts_st = 3;
            }
            break;
        default:
            ts_got = (ts_got << 8) | (unsigned long)b;
            if (++ts_i >= 4) {
                ts_st = 0;
                ts_pending = 1;
                rx_reqs++;
            }
            break;
        }
    }

    /* A HELD REPLY MUST LEAVE THE RING EMPTY, AND THIS IS THE DEFECT THAT
     * COST THE TUNERSTUDIO SESSION.
     *
     * hcts_tx() drops exactly one ring byte per transmitted byte as its own
     * echo - see the comment above it, and the 2026-08-23 bench trace that
     * put it there. That accounting is only true while the ring holds
     * nothing BUT the echo, and every ordinary reply satisfies it because it
     * follows its request within a millisecond.
     *
     * A BURN'S REPLY IS THE ONE REPLY IN THIS PROTOCOL THAT IS SENT SECONDS
     * AFTER ITS REQUEST. Anything the host puts on the wire in that window
     * sits in the ring AHEAD of the echo, and the echo-drop then eats the
     * host's bytes instead - leaving our own reply in the ring to be parsed
     * back out as a command.
     *
     * MEASURED ON THE REAL ECU, 2026-09-16, V56: one 11-byte output-channel
     * request sent 0.5 s into a 2.9 s Burn. The Burn's seven reply bytes ate
     * the request's first seven; the remaining four were read as plain
     * commands; and the reply's own echo - 00 01 00 D2 02 EF 8D - then
     * parsed as a length-1 frame with a VALID CRC32 and command byte 0x00,
     * which is not a command, so the ECU answered TS_BAD_CMD. An unsolicited
     * 0x83 on the K-line is precisely what makes TunerStudio drop and
     * reconnect. bench measurements
     *
     * The loop above has already taken ONE complete request out of the ring
     * and parked it in ts_pending, so a host that polls during a Burn still
     * gets answered - after the Burn's own reply, in order. Everything past
     * that cannot be served at all and must not be left where the echo
     * accounting will find it. Dropping it is the honest outcome: the host
     * will retry, and rx_resync says it happened. */
    if (deferred_response != 0u) {
        hcts_rx_pump();
#ifdef TGT_RX_PEC
        hc_pecrx_flush();
#endif
        if (hc_rx_tail != hc_rx_head) {
            hc_rx_tail = hc_rx_head;
            if (ts_st != 0u) {
                ts_st = 0;
                ts_i = 0;
            }
            rx_resync++;
        }
    }
}

void hcts_service(void)
{
    if (ts_pending == 0) {
        return;
    }
#ifdef TGT_TX_ASYNC
    /* Half duplex: the previous reply, and its echo, first. */
    if (hc_tx_busy() || echo_owed() != 0u) {
        return;
    }
#endif
    /* A request parsed while a Burn's reply is held is ANSWERED AFTER IT, not
       instead of it. Serving it here would put a second reply in front of the
       one the host is already waiting for. */
    if (deferred_response != 0u) {
        return;
    }
    if (ts_pending == 2) {
        handle_plain(ts_plain_cmd);
        ts_pending = 0;
        return;
    }
    if (hcts_crc32(rxb, ts_len) != ts_got) {
#ifdef TGT_S0BG_ALT
        if (!link_bad_seen())
#endif
        {
            hcts_send_response(TS_BAD_CRC, no_data, 0);
        }
    } else {
#ifdef TGT_S0BG_ALT
        hc_link_locked = 1u;        /* a valid frame: this IS the rate */
        link_bad = 0u;
#endif
        handle(rxb, ts_len);
    }
    ts_pending = 0;
}

/* --------------------------------------------------------------- bring-up */
void hcts_init(void)
{
    /* Snapshot BEFORE these volatile counters are reset.  On V45 this proves
       whether a B command reached cfg_burns before startup/reinitialization. */
    BF_HCTS_INIT(cfg_burns, cfg_writes);
    S0BG  = TGT_S0BG;    /* see hctarget.h */
#ifdef TGT_S0BG_ALT
    hc_link_rate = 0u;     /* boots at the proven default, hunts on evidence */
    hc_link_locked = 0u;
    hc_link_switches = 0u;
    link_bad = 0u;
    link_hold = 0u;
    link_evid = 0u;
#endif
    S0CON = 0x80D1;      /* 8N1, receiver enabled */
    S0TIC |= 0x80;
    S0RIC &= 0x7F;

    /* Must be armed before the very first hcts_tx(): the banner echoes back
       too, and an unconsumed banner echo is read as a stream of plain
       commands. */
    echo_seen = 1;
#ifdef TGT_TX_PIPELINE
    echo_pending = 0u;
#endif

    /* Nothing here starts at a known value: no target's startup runs Keil's
       ?C_INIT, so every counter is set explicitly. The bench read cfgEdits as
       3 out of reset before this was done. */
    rx_echo_lost = 0;
    rx_hw_ovr = 0;
    rx_frame_err = 0;
    rx_resync = 0;
    rx_bytes = 0;
    rx_reqs = 0;
    rx_idle = 0;
    rx_irq_mode = 0;
    rx_irq_ok = 0;
    rx_tick_ok = 0;
    rx_ticks = 0;
    cfg_writes = 0;
    cfg_burns = 0;
    hc_stalls = 0;
    hc_stall_req = 0;
    deferred_response = 0;
    /* OFF by default, and the target opts in.
     *
     * This used to be set to 1 here, which looked harmless and was not: on the
     * 4B0906018DC the UMKOM trace flag had never actually been 1 at runtime -
     * it was a `static ... = 1` in a firmware whose startup does not run
     * Keil's ?C_INIT, so it held whatever the RAM held, which was zero. Setting
     * it deterministically turned a trace that had never run into one that
     * always ran, and free-running text on a half-duplex wire eats the front
     * of the next request. A bench-proven target must not change what it puts
     * on the wire because another board wanted a diagnostic. */
    hc_trace_on = 0;
    hc_cfg_stable = 1;
    ts_st = 0;
    ts_i = 0;
    ts_len = 0;
    ts_got = 0;
    ts_pending = 0;
#ifdef TGT_TX_ASYNC
    hc_tx_echo_ate(1u);
#endif
}
