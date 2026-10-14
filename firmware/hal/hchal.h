/*
 * hchal.h - the HaniCore hardware abstraction layer, semantic channels.
 *
 * The common runtime (hcengine.c, the hctrigger.c decoder core, and later
 * hcsched.c / hcinj.c / hcdbw.c / hcboost.c) calls the functions below and
 * NEVER learns whether a signal comes:
 *
 *      directly from the C167's own ADC / capture units / GPIO
 *   or
 *      through the ME7.1.1 S5500 monitoring module's 118-word runtime frame.
 *
 * One implementation file per target sits under it:
 *
 *      hchal_me75.c      4B0906018DC - 16 C167 ADC channels, CC15/CC8 capture,
 *                        direct pin drive
 *      hchal_me711.c   OEM ME7.1.1 / 44F - a SUBSET of the C167 ADC, plus the
 *                        S5500 frame for CLT / IAT / TMOT2, plus a bench-safe
 *                        output sink
 *
 * See docs/ARCHITECTURE.md for the port matrix.
 *
 * THREE RULES ARE BAKED INTO THIS INTERFACE:
 *
 * 1. hc_hal_ain() returns a RAW 10-bit count. All sensor scaling, plausibility
 *    windows, substitute values and per-sensor error flags stay in hcengine.c,
 *    so ONE calibration page serves both ECUs. If the HAL returned degrees C
 *    the Bosch path would need its own copy of that logic.
 *
 * 2. hc_hal_ain_ok() lets hcengine.c fall back to its substitute value when a
 *    channel has no backing source on this board (no MAP sensor on ME7.1.1) or
 *    no fresh data yet (an S5500-backed channel before the runtime frame is
 *    flowing). That is the honest state, and it is NOT a guessed mapping.
 *
 * 3. On ANY build with HANICORE_BENCH_SAFE defined, every hc_hal_out*() call
 *    is a counting no-op. Common logic starting to run cannot energise a coil,
 *    an injector, a throttle motor or a boost valve.
 */
#ifndef HCHAL_H
#define HCHAL_H

/* ======================================================= analog inputs ==== *
 *
 * Semantic index. hchal_<target>.c maps each to either a physical C167 ADC
 * channel, an S5500 frame slot, or nothing at all. Keep HC_AIN_COUNT last;
 * hc_hal_ain_mask() returns a bit per channel, so this must stay <= 16.
 */
#define HC_AIN_VBAT        0u
#define HC_AIN_CLT         1u    /* coolant    - S5500-backed on ME7.1.1     */
#define HC_AIN_IAT         2u    /* intake air - S5500-backed on ME7.1.1     */
#define HC_AIN_MAP         3u    /* manifold / charge-air pressure           */
#define HC_AIN_TPS1        4u    /* throttle position, track 1               */
#define HC_AIN_TPS2        5u    /* throttle position, track 2               */
#define HC_AIN_APP1        6u    /* accelerator pedal, track 1               */
#define HC_AIN_APP2        7u    /* accelerator pedal, track 2               */
#define HC_AIN_MAF         8u    /* air mass meter 1 (analog on ME7.1.1)     */
#define HC_AIN_MAF2        9u    /* air mass meter 2                         */
#define HC_AIN_TPS1_AMP     10u    /* AN2/IPV: amplified TPS1, not independent */
#define HC_AIN_O2_1_PRE   11u    /* lambda bank 1, before cat                */
#define HC_AIN_O2_1_POST  12u    /* lambda bank 1, after cat                 */
#define HC_AIN_O2_2_PRE   13u    /* lambda bank 2, before cat                */
#define HC_AIN_O2_2_POST  14u    /* lambda bank 2, after cat                 */
#define HC_AIN_KNOCK      15u    /* knock input (pre-conditioning)           */
#define HC_AIN_COUNT      16u

/* Raw conversion result, 0..1023. A channel with no backing source on this
   target returns 0 and hc_hal_ain_ok() returns 0. */
unsigned int  hc_hal_ain(unsigned char sem);

/* 0 = no backing source on this board, or the source is stale. hcengine.c
   must then use its substitute value and set that sensor's error bit. Always
   1 for a live C167 ADC channel that exists on this target. */
unsigned char hc_hal_ain_ok(unsigned char sem);
/* a switch input by connector cavity: 0/1, 0xFF = not readable here */
unsigned char hc_hal_din(unsigned char cav);
unsigned char hc_hal_din_ok(unsigned char cav);   /* has a read path */

/* One bit per HC_AIN_*, set when hc_hal_ain_ok() would return 1. Published to
   TunerStudio so a bench operator can see at a glance which sensors this board
   actually has and which are waiting on the S5500. */
unsigned int  hc_hal_ain_mask(void);

/* WHICH converter channel the HAL reads for a semantic channel (the bound
   one, else the board's own), or 0xFF when none. The pin router compares the
   CONFIGURED connector pin against it. Reporting only; it binds nothing. */
unsigned char hc_hal_ain_phys(unsigned char sem);
unsigned char hc_hal_ain_bound(unsigned char sem);


/* Called once per main-loop pass, AFTER the target's own ADC round-robin and
   AFTER the platform's frame service. Snapshots any frame-backed channels.
   A no-op on ME7.5. NEVER BLOCKS - it must not, it runs next to a 10 ms
   supervision raster. */
void          hc_hal_ain_service(void);
void          hc_hal_ain_capture(void);   /* ME7.1.1: at the S5500 reply accept */

/* ===================== THE CAPTURE ROUTE - a cavity, into real hardware ====
 *
 * Which capture channel, if any, a PHYSICAL CONNECTOR CAVITY reaches on this
 * board. HC_CAPCH_NONE means the board has no edge-capture resource behind
 * that cavity, whatever its capability bits say.
 *
 * WHY THIS EXISTS. Until V62 the crank capture was compiled to CC15 and the
 * cams to CC8/CC9, while `pinCrank`, `pinCam1` and `pinCam2` were validated
 * against the descriptor and then ignored. Setting pinCrank = 86 VALIDATED -
 * cavity 86 really does carry HALL_IN - and the firmware went on capturing
 * cavity 82. The tuner was told the configuration was accepted and the ECU
 * read a different wire.
 *
 * The channel id is OPAQUE and deliberately not a CAPCOM number: shared code
 * compares it to HC_CAPCH_NONE and for equality against other cavities, and
 * has no business knowing what silicon is behind it. The project rules -
 * the tuner sees cavities, never CAPCOM indices. */
/* ================= THE ANALOG BINDING - configuration over compile time ====
 *
 * hc_hal_ain(sem) used to read a channel named by a compile-time PHYS[] table,
 * so `pinMap`, `pinClt`, `pinTps1` and the rest were validated against the
 * descriptor and then ignored - the analog twin of the crank defect below.
 *
 * hc_route.c has always been able to resolve a configured cavity into this
 * CPU's ADC channel, and its own header said why it did not act on it: the
 * binding "can silently move a live sensor reading", so it should not be
 * inverted in the image that introduces the mechanism. It also named the
 * precondition - hc_route_check() must be clean - and V61 measured that as
 * ZERO on the board default.
 *
 * So the router now BINDS. hc_route_service() calls this for every semantic
 * channel whenever the active configuration moves; an unrouted channel binds
 * to HC_ADC_NONE and hc_hal_ain() falls back to the target's own default,
 * which is what makes a Porsche page behave exactly as V61 did.
 *
 * The HAL keeps the table, because the HAL owns the converter. */
void          hc_hal_ain_bind(unsigned char sem, unsigned char adc_ch);

#define HC_CAPCH_NONE 0xFFu
unsigned char hc_hal_capture_channel(unsigned char pin);

/* 1 when this build's HAL DRIVES the output that page field `field` (a
 * CFG_U_PIN_* offset) configures, on cavity `cav`. A capability bit says what
 * a circuit COULD do; this says what the firmware does with it - the output
 * twin of hc_hal_capture_channel(). hc_validate() refuses an assignment that
 * answers 0, so a route that would drive nothing is never accepted in
 * silence: until V95 a tacho or relay routed to a capable cavity with no HAL
 * path (18/22, 37, 81, ...) validated and moved nothing. */
unsigned char hc_hal_out_bindable(unsigned int field, unsigned char cav);

/* ==================================================== position inputs ===== *
 *
 * The hctrigger.c decoder CORE (sync / gap / 720 phase / correction-vs-loss
 * counters / rpm) is already pattern-independent and target-independent. Only
 * the front end lives here: arming the right capture units, and disarming
 * them. The capture ISRs themselves stay in hcvec_<target>.c and call the
 * trigger entry points directly - they are too hot to route through a
 * dispatch, and the ME7.5 board measured the cost of getting that wrong.
 *
 * Both are safe to call repeatedly; hctrigger.c drives them live from
 * CFG_TRIG_SOURCE so connecting a sensor does not need a power cycle.
 */
void          hc_hal_trig_arm(void);      /* arm crank + cam captures        */
void          hc_hal_trig_disarm(void);   /* and take them down again        */

/* 1 once hc_hal_trig_arm() has actually enabled a capture on this board. */
extern unsigned char hc_hal_trig_armed;

/* ========================================================= outputs ======== *
 *
 * Semantic output index. Per-cylinder outputs are always 8 long on every
 * target (the portability contract), so telemetry and the .ini are
 * byte-identical everywhere. Keep HC_OUT_COUNT last.
 */
#define HC_OUT_IGN1        0u    /* .. HC_OUT_IGN1 + 7 = coil 8             */
#define HC_OUT_INJ1        8u    /* .. HC_OUT_INJ1 + 7 = injector 8         */
#define HC_OUT_THR_PWM    16u    /* throttle H-bridge PWM magnitude          */
#define HC_OUT_THR_DIR    17u    /* throttle H-bridge direction              */
#define HC_OUT_THR_EN     18u    /* throttle H-bridge enable                 */
#define HC_OUT_CAMSOL1    19u
#define HC_OUT_CAMSOL2    20u
#define HC_OUT_FUELPUMP   21u
#define HC_OUT_BOOST      22u
#define HC_OUT_COUNT      23u

/* Digital on/off. On a HANICORE_BENCH_SAFE build this only records the
   request and returns - no port, no latch, no direction register is touched. */
void          hc_hal_out(unsigned char sem, unsigned char on);

/* A duty cycle in 0.1 %, for the PWM-driven outputs. Same bench-safe rule. */
void          hc_hal_out_duty(unsigned char sem, unsigned int duty_x10);

/* THE THROTTLE BRIDGE'S OWN FAULT PIN, asked as a question rather than as a
 * pin. On ME7.1.1 it is S8100's SF on P3.15 - open drain with a pull-up, so
 * "asserted" is LOW - but CAL_DBW_SF_MODE decides which level counts as a
 * fault, because a board that wires it the other way must be a configuration
 * change and not a code change.
 *
 * IT LIVES IN THE HAL BECAUSE THE PIN DOES. hcbench.c had its own copy and
 * hc_dbw.c would have been a third; the ME7.5 hcdbw.c has `SF_PIN = P2^9`,
 * which on ME7.1.1 is the second cam input. One implementation, one pin
 * reference, taken from hctarget.h.
 *
 * A target with no bridge returns 0. That is honest: it cannot report a fault
 * it has no way to see, and hc_dbw.c refuses for other reasons anyway. */
unsigned char hc_hal_dbw_sf_faulted(void);

/* The raw SF pin level, 0 or 1, whatever the configured polarity. Published
   so a bench can measure the polarity instead of assuming it. */
unsigned char hc_hal_dbw_sf_level(void);

#if defined(TGT_DBW_MOTOR_PRIMITIVE)
/* One target-owned motor transaction, including safe direction transitions. */
void far hc_hal_dbw_motor(unsigned char on, unsigned char dir, unsigned int duty);
#endif

/* 0 whenever HANICORE_BENCH_SAFE is defined or the automatic output
   permissions (hcsafety.c) are not met. The output paths check this IN
   ADDITION to their own class permission - defence in depth. */
unsigned char hc_hal_outputs_live(void);

/* Every engine output to high impedance, unconditionally and without reading
   the configuration. Safe to call before the page exists, and called from
   hc_hal_init() before anything else. */
void          hc_hal_outputs_safe(void);

/* Per-class permission. Narrower than hc_hal_outputs_live(): a throttle may
   hold a position before the crank is synchronised, a coil may not fire. */
unsigned char hc_hal_out_class_live(unsigned char sem);

/* What the scheduler has COMMANDED ON right now, one bit per slot. Updated
   before the permission is checked, so a refused request still shows - which
   is what separates "nothing asked" from "asked and refused". */
unsigned int  hc_hal_out_mask_ign(void);
unsigned int  hc_hal_out_mask_inj(void);

/* Drive a whole class in one call. `base` is HC_OUT_IGN1 or HC_OUT_INJ1 and
   `which` is a bitmask of slots, so this serves one slot, a wasted-spark pair
   and a full batch alike - with the permission checked once and at most one
   read-modify-write per port. */
void          hc_hal_out_group(unsigned char base, unsigned int which,
                               unsigned char on);

/* ===================================================== main power relay == *
 *
 * Platform boundary for the ECU/main-power relay. The generic state machine
 * owns OFF/ON/AUTO, grace timing and telemetry; a target owns only the
 * electrical binding. A target with no proven binding MUST report unbound
 * and implement set() as a no-op. That is the Bosch V21 starting point.
 */
void          hc_hal_main_relay_set(unsigned char on);
unsigned char hc_hal_main_relay_bound(void);
unsigned int  hc_hal_main_relay_feedback_dv(void); /* 0.1 V */
unsigned char hc_hal_main_relay_feedback_valid(void);
unsigned char hc_hal_main_relay_feedback_state(void);

/* THE REQUEST CENSUS, and it is accessors rather than arrays on purpose.
 *
 * Incremented on every hc_hal_out*() call whether or not a pin was actually
 * driven, so a bench run can prove the common logic is asking for the right
 * things - the right cylinder, the right number of times - while nothing can
 * move. That is the only way to test engine logic on an ECU whose outputs are
 * compiled out.
 *
 * The storage lives in each board's EXTERNAL SRAM (TGT_RAM_HALCENSUS),
 * not in near RAM. That is MEASURED, not stylistic: as plain near arrays the
 * census took the ME7.5 build to 1819 bytes of near data against the 1792 its
 * NDATA window holds. PROJECT_STATE's standing instruction after the last
 * overflow was to move data OUT rather than shrink the user stack again.
 * Hiding it behind accessors is what let the storage move without touching a
 * single caller. */
unsigned int  hc_hal_out_reqs(unsigned char sem);   /* calls for this output */
unsigned int  hc_hal_out_value(unsigned char sem);  /* last state / duty     */

/* Total requests across all outputs, so ONE telemetry word says "the common
   engine logic is running and asking for things". */
extern unsigned int  hc_hal_out_calls;

/* One-time init. Zeroes the census and puts the back end in its off state.
   NOTHING here may assume static zero-initialisation: no HaniCore startup runs
   Keil's ?C_INIT. */
void          hc_hal_init(void);

#endif /* HCHAL_H */
