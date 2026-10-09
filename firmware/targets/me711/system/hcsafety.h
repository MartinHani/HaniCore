#ifndef HCSAFETY_H
#define HCSAFETY_H
#define HC_INHIBIT_BENCH_SAFE 0x0001u
#define HC_INHIBIT_NO_CYCLE   0x0002u
#define HC_INHIBIT_ASIC       0x0004u
#define HC_INHIBIT_CAL        0x0008u
#define HC_INHIBIT_KEYOFF     0x0010u   /* was NOT_ARMED - see below */
#define HC_INHIBIT_NO_CRANK   0x0020u
/* an explicit engine TEST holds spark and fuel off - the '!K'
   compression profile (hcsched_dry.c). Released when the test ends, is
   aborted, or times out. A permission, not a fault. */
#define HC_INHIBIT_TEST       0x0040u

/* WHICH INHIBITS APPLY TO WHICH CLASS OF OUTPUT, and they are NOT the same
 * set. Until V63 every class used the union, which meant hc_dbw_allowed was
 * 0 until the engine had 720-degree sync - and a throttle that will not move
 * until the engine is running is a throttle that cannot help start it. The
 * union is still exactly right for spark and fuel.
 *
 *   ALWAYS      bench-safe veto, ASIC health, calibration, key-off.
 *   + CRANK     anything whose timing is an ENGINE ANGLE.
 *   + CYCLE     anything that must know WHICH revolution it is in, which is
 *               sequential injection and sequential COP - checked where the
 *               strategy is known, not here, because a wasted-spark engine
 *               needs no cycle at all.
 *
 * A throttle plate, a fuel pump and a main relay are positions and states,
 * not angles. They take the ALWAYS set and nothing more.
 *
 * THERE IS NO USER-FACING ARM. Bit 0x0010 used to be NOT_ARMED - the
 * page field CFG_OUTPUTS_ARMED - and every engine output, runtime-scheduled
 * events included, waited for a tuner to set it. That made normal engine
 * operation depend on a ceremony, which a standalone ECU must not (the project rules
 * 6; rusEFI has no such switch: the trigger and the scheduler ARE the
 * gating). The bit now means only what the runtime already knew: KL15 has
 * gone and the controlled key-off is in progress. The engine-angle classes
 * are gated by the crank, the positional classes by their own lifecycles,
 * and a bench actuator test by its own explicit bounded command. */
#define HC_INHIBIT_ALWAYS     (HC_INHIBIT_BENCH_SAFE | HC_INHIBIT_ASIC \
                               | HC_INHIBIT_CAL | HC_INHIBIT_KEYOFF)
#define HC_INHIBIT_ANGLE      (HC_INHIBIT_ALWAYS | HC_INHIBIT_NO_CRANK \
                               | HC_INHIBIT_TEST)

/* ================================ TWO STACKS, AND THE ORDER IS THE GUARD ===
 *
 * SYSTEM stack  0xF580-0xF7FF  SP, STKOV 0xF586 / STKUN 0xF800 (start_me711.a66).
 *                              Interrupt return frames and saved registers.
 *                              The CPU traps on overflow and underflow.
 * USER stack    0xF380-0xF57F  ?C_USERSTACK, R0. C call frames and every local
 *                              the compiler spills - including every ISR's
 *                              locals (Keil keeps ISR locals on R0).
 * GUARD BAND    0xF340-0xF37F  unallocated (linker_me711.lnp); an overflow of
 *                              the user stack lands here first.
 *
 * A user stack ABOVE the system stack (256 bytes, the earlier layout) let
 * an overflow run straight into the oldest interrupt return addresses: the
 * runtime audit measured 272 bytes under engine + TunerStudio load and caught
 * send_och() returning to 0x8401A9 (2026-10-06 runtime audit, finding
 * P0-1). The user stack now sits BELOW the system stack, so the worst an
 * overflow can do is write the guard band and the unallocated RAM under it -
 * it can no longer reach a return frame - and the size doubled.
 *
 * MARGIN POLICY (tests/firmware/build/me711_stack_budget_proof.py): the worst
 * depth measured under the full runtime stress matrix must leave at least
 * HC_STK_MARGIN_PCT of each stack unused, and the guard band must never be
 * touched. Both high-water marks are published (OCH 730 user, runtime health
 * block system), measured on the ECU by the same pattern scan. */
#define HC_STK_BOT      0xF380u
#define HC_STK_TOP      0xF580u
#define HC_STK_SIZE     (HC_STK_TOP - HC_STK_BOT)
#define HC_STK_GUARD_LO 0xF340u
#define HC_STK_GUARD_HI 0xF380u
#define HC_SSTK_BOT     0xF586u            /* STKOV                        */
#define HC_SSTK_TOP     0xF800u            /* STKUN                        */
#define HC_STK_MARGIN_PCT 40u
/* The top 64 bytes are LIVE when hc_stack_prime() runs - it is called from
   main(), which is itself a frame - so they are never written. That bounds
   what this can see: depths below 64 bytes read as "not yet measurable",
   which is exactly the range nobody is worried about. */
#define HC_STK_KEEP     64u
#define HC_STK_PATTERN  0x5A5Au

/* hcrtmon711.c - FAR (cold) */
void far hc_stack_prime(void);
unsigned int far hc_stack_used(void);
unsigned int far hc_sysstack_used(void);
/* hcsafety.c - near, one compare: the supervisor's check */
unsigned int hc_stack_overflowed(void);
extern unsigned int hc_stack_hwm, hc_sysstack_hwm;

/* ============================== THE RUNTIME SUPERVISOR ======
 *
 * hc_rt_supervise() runs in the 1 ms tick ISR - a different interrupt source
 * from the CC25 deadline executor - and checks what the watchdog cannot see:
 * the main loop can keep feeding the watchdog while CC25, the ONLY thing
 * that turns coils and injectors OFF, has stopped (runtime audit P1-4).
 *
 *   EXEC_DEAD  hc_dl_beat did not move for HC_RT_BEAT_MS (the executor's
 *              empty-queue checkpoint is 12.8 ms, so a live CC25 always does)
 *   EXEC_LATE  the queue head is overdue by > 2.5 ms
 *   EXEC_CFG   CC25 mode / IE / priority not what the executor programs
 *   EXEC_STALL an output the executor holds ON outlived the longest ON the
 *              planner can produce (coil HC_RT_COIL_MS, injector
 *              HC_RT_INJ_MS) - the executor runs but its OFF never comes
 *   USTACK     the user stack reached its guard band
 *
 * An EXEC fault releases every coil and injector at once (hc_deadline_cancel -
 * with the executor dead, a charging coil would otherwise stay on: the
 * release is the lesser harm), re-arms CC25, and holds every coil charge and
 * injector opening refused (hc_dl_inhibit = HC_Q_EXECUTOR) until the engine
 * has stopped and the heartbeat has been regular for HC_RT_RECOVER_MS.
 * The flags stay latched in hc_rt_fault for diagnosis; recovery clears only
 * the inhibit. If the TICK itself stops, hcmain_me711.c stops feeding the
 * watchdog (the layer below this one). */
#define HC_RT_F_EXEC_DEAD 0x0001u
#define HC_RT_F_EXEC_LATE 0x0002u
#define HC_RT_F_EXEC_CFG  0x0004u
#define HC_RT_F_EXEC_STALL 0x0008u
#define HC_RT_F_EXEC      0x000Fu
#define HC_RT_F_USTACK    0x0010u
#define HC_RT_BEAT_MS     20u
#define HC_RT_RECOVER_MS  100u
#define HC_RT_COIL_MS     25u    /* MAXDWELL backstop OVD_MAX 20 ms + 5 ms     */
#define HC_RT_INJ_MS      140u   /* longest admissible pulse 131 ms + 9 ms     */
extern volatile unsigned int hc_rt_fault;
extern unsigned int hc_rt_exec_faults;
extern unsigned char hc_rt_armed;
void far hc_rt_supervise(void);       /* hcrtmon711.c */
void hc_rt_wdt_mark(void);

void hc_safety_init(void);
void hc_safety_service(unsigned int healthy, unsigned int cal_ok,
                       unsigned int crank_ok, unsigned int cycle_ok,
                       unsigned int key_on);
extern unsigned int hc_outputs_allowed, hc_dbw_allowed;
extern unsigned int hc_ignition_allowed, hc_injection_allowed;
extern unsigned int hc_safety_inhibits;
#endif
