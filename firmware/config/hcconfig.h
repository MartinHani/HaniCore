/*
 * hcconfig.h - the TunerStudio constants page.
 *
 * THE PORTABILITY CONTRACT, and the reason this file exists.
 *
 * The final HaniCore target is a Bosch ME7.1.1 (V8, turbo, DBW, two knock
 * sensors). The 1.8T AWT on the ME7.5 bench is the development engine. Neither
 * is allowed to be "the" target, so the split is:
 *
 *   hctarget.h   what the BOARD physically is. Which port pin is which CAPCOM
 *                channel, which ADC channel is wired to what, the clock, the
 *                trap numbers, the watchdog table. One file per ECU.
 *
 *   hcconfig     everything that SELECTS from that catalogue, and every
 *                calibration value. Cylinder count, firing order, trigger
 *                geometry, which output drives which cylinder, angles, dwell,
 *                limits. Identical across targets, and every byte of it is
 *                TunerStudio-writable.
 *
 * The rule that keeps them apart: **if a number could differ between the AWT
 * and the target vehicle for any reason other than the circuit board, it belongs
 * here, not in hctarget.h.**
 *
 * Consequences that are deliberate:
 *
 *   - Arrays are sized HC_MAX_CYL = 8 even on a four-cylinder board, so the
 *     page layout is byte-identical on every target. One .ini serves both, and
 *     the V8 port needs no new file - only different values.
 *   - Nothing about the engine is a compile-time constant. Changing the tooth
 *     count is a TunerStudio edit, not a rebuild.
 *   - The page is a flat BYTE ARRAY with explicit big-endian accessors, not a
 *     packed struct. TunerStudio wants big-endian (see `endianness = big` in
 *     the .ini) and the C167 is little-endian; doing the swap in one place
 *     beats discovering Keil's struct padding on the bench.
 *
 * Offsets below are the single source of truth. `tools/ts_ini_check.py`
 * asserts that the .ini agrees with them, the same way it already does for the
 * output channels.
 *
 * Defaults are for the 1.8T AWT - the first engine this will run - which means
 * a 60-2 crank wheel. The Funktionsrahmen names those two numbers SY_TEETH and
 * SY_GAP (`SY_TEETH = 60 bei 60-2 KW Geberrad`, `SY_GAP = 2`), and this file
 * keeps the Bosch names so the mapping to the documentation stays obvious on
 * the ME7.1.1 port, which uses the same function framework.
 */
#ifndef HCCONFIG_H
#define HCCONFIG_H

/* Eight, because the target vehicle is a V8. The AWT uses the first four. */
#define HC_MAX_CYL              8

/* ================================== the calibration page =================
 *
 * TWO REGIONS, ONE FLAT PAGE, exactly the shape Bosch Motorsport's MS 4 Sport
 * uses (see docs/ARCHITECTURE.md): all 675 of its calibration
 * parameters - 74 maps, 108 curves, 489 scalars - live in ONE contiguous 32 KB
 * page, mirrored between flash and RAM.
 *
 *   0 .. HC_CFG_CORE-1     the scalars, in NEAR ram as hc_cfg[]
 *   HC_CFG_CORE .. END     the tables, DIRECTLY in the battery-backed SRAM
 *
 * Why split at all: the scalars are a bench-proven path - written, burned, and
 * shown to survive a power cycle - and near RAM has about 1.7 KB in total, so
 * a page big enough for maps cannot live there. The tables therefore live in
 * the external SRAM they are already backed by, and nothing about the proven
 * half changes. TunerStudio sees one flat page and never knows.
 */
#define HC_CFG_CORE             128     /* scalars, mirrored in near RAM     */
#define HC_CFG_SIZE             4096    /* must match pageSize in the .ini   */

/* Table geometry. 16x16 is what fits a byte-per-cell map in 256 bytes and is
   what every tuner expects to see. */
#define CAL_AXIS_N              16
#define CAL_MAP_N               (CAL_AXIS_N * CAL_AXIS_N)
#define HC_CFG_VERSION          1

/* ---------------------------------------------------------------- layout --
 *
 * u8 = one byte, u16 = two bytes big-endian. Anything not listed is reserved
 * and reads as zero.
 *
 * The engine description follows **Bosch Motorsport's own MS 4 Sport model**
 * (`%ENGSETUP` in `FRM_40CSTX36.pdf`, a motorsport ECU on this same C167
 * hardware family, documented in English): a cylinder count plus an explicit
 * **TDC angle per cylinder**, measured from one reference - the second tooth
 * after the gap.
 *
 * That is strictly better than a firing-order list, which is what this page
 * carried first. A firing order plus one global offset only describes an
 * engine whose cylinders are evenly spaced. Per-cylinder TDC angles describe
 * inline engines, V engines, and V engines with two different firing
 * intervals, with no special cases - and the target vehicle V8 is exactly the case
 * that would have broken the simpler model.
 *
 * Bosch's A2L gives the types: `CYLNUMBER` U8 1..8, `TDCCYL_1..8` U16 0..720
 * degrees, `REV_MAX` and `REV_MIN` U16 rpm. Eight TDC entries, which is why
 * HC_MAX_CYL is 8 here too.
 *
 * **What is and is not taken from MS 4 Sport.** That ECU is a motorsport unit
 * and its architecture is NOT stock ME7 - it must not be treated as an
 * authority on how this ECU behaves. What is borrowed here is only the SHAPE
 * of the configuration data: how to describe an engine in a way that covers a
 * V8 with uneven firing, and the idea of a published validity flag with a
 * fail-safe. That reasoning stands on its own and does not depend on the two
 * ECUs sharing anything.
 *
 * Nothing else crosses over. No address, no timer constant, no memory layout,
 * and no claim about stock ME7 behaviour. Those come from the ME7
 * Funktionsrahmen, the schematic, and the bench - in that order.
 */
#define CFG_VERSION             0       /* u16  firmware writes this        */
#define CFG_CYLINDERS           2       /* u8   CYLNUMBER, 1..HC_MAX_CYL    */
#define CFG_STROKES             3       /* u8   4 = four-stroke             */

/* TDCCYL_1..8: crank angle from the second tooth after the gap to each
   cylinder's TDC, in 0.1 degree, 0..7200. Eight entries on every target. */
#define CFG_TDC_CYL             4       /* u16[8], 4..19                    */

/* Crank trigger. SY_TEETH and SY_GAP are the Funktionsrahmen's names
   ("SY_TEETH = 60 bei 60-2 KW Geberrad", "SY_GAP = 2"). Kept explicit rather
   than Bosch Motorsport's single CRANKWHEEL36 selector, because a selector
   only supports the two wheels they chose to support. */
#define CFG_SY_TEETH            20      /* u16  60 for a 60-2               */
#define CFG_SY_GAP              22      /* u8   2  for a 60-2               */
#define CFG_TRIG_EDGE           23      /* u8   0 = falling, 1 = rising     */
#define CFG_TRIG_GAP_RATIO_X10  24      /* u16  gap detect ratio x10        */
#define CFG_TRIG_MIN_TEETH      26      /* u8   good teeth before sync      */
#define CFG_TRIG_TIMEOUT_MS     27      /* u8   no tooth for this -> stall  */

/* REV_MAX is what the scheduler must cope with, not the limiter. Bosch use it
   to bound the injection and ignition timing calculation. REV_MIN is their
   "engine speed minimum recognition value". */
#define CFG_REV_MAX             28      /* u16  rpm                         */
#define CFG_REV_MIN             30      /* u16  rpm                         */

/* Camshaft. */
#define CFG_CAM_ENABLE          32      /* u8   0 = wasted spark / batch    */
#define CFG_CAM_EDGE            33      /* u8   0 = falling, 1 = rising     */

/* Which board output drives which cylinder. The catalogue of outputs that
   exist is in hctarget.h; these pick from it, so a different loom is a
   TunerStudio edit. 0xFF = not used. */
#define CFG_INJ_CHANNEL         34      /* u8[8], 34..41                    */
#define CFG_IGN_CHANNEL         42      /* u8[8], 42..49                    */

/* Limits and basic fuelling. Enough for M5 and M6; the tables come later. */
#define CFG_REV_LIMIT           50      /* u16  fuel/spark cut point        */
#define CFG_CRANK_RPM_MAX       52      /* u16  below this = cranking       */
#define CFG_DWELL_MS_X100       54      /* u16  nominal dwell, 0.01 ms      */
#define CFG_INJ_DEADTIME_US     56      /* u16  at nominal battery voltage  */
#define CFG_INJ_START_DEG_X10   58      /* u16  injection start, 0.1 deg    */
#define CFG_IGN_ADVANCE_DEG_X10 60      /* u16  fixed advance until tables  */

/* Sensor scaling. Channel numbers are board facts and live in hctarget.h;
   what the counts MEAN is calibration and lives here. */
#define CFG_ADC_BATT_FS_DV      62      /* u16  full scale, 0.1 V           */
#define CFG_CLT_PULLUP_OHM      64      /* u16                              */
#define CFG_IAT_PULLUP_OHM      66      /* u16                              */

/* Bench and safety switches. */
#define CFG_OUTPUTS_ARMED       68      /* u8   0 = never drive an output   */
#define CFG_FLAGS               69      /* u8   spare bit flags             */

/* Bench only. There is no engine and no signal generator, so the trigger
   decoder is exercised by generating the wheel in software at this speed and
   feeding it to the same code a real capture feeds. 0 = off, and it is off
   unless somebody deliberately sets it. */
#define CFG_SIM_RPM             70      /* u16  synthetic crank speed, rpm  */

/* Which trigger input is allowed to be armed at all.
 *
 * 0 = the bench generator only. Nothing is armed unless CFG_SIM_RPM is set.
 * 1 = the real crank and cam captures on P2.15 / P2.8.
 *
 * MEASURED reason for it to exist: with no sensor connected, arming CC15 lets
 * a floating input generate captures. On the bench that read out as 20000 rpm
 * with syncState stuck at 1, and the interrupt load made the ECU stop
 * answering TunerStudio - which looked exactly like a serial fault and was
 * not. Default 0 means an existing burned page stays safe. */
#define CFG_TRIG_SOURCE         72      /* u8   0 = bench only, 1 = real    */

/* Generic ECU/main-power relay control. These consume bytes that were
   reserved in configuration version 1, so existing pages remain compatible.
   The Bosch HAL is deliberately UNBOUND until its electrical resources are
   proven; mode ON there is observable as a request but cannot drive a pin. */
#define CFG_MAIN_RELAY_MODE     73      /* u8   0 OFF, 1 ON, 2 AUTO         */
#define CFG_MAIN_RELAY_GRACE_MS 74      /* u16  mismatch debounce           */
#define CFG_RESERVED            76      /* to HC_CFG_CORE - 1               */

#define MAIN_RELAY_OFF           0u
#define MAIN_RELAY_ON            1u
#define MAIN_RELAY_AUTO          2u

#define TRIG_SRC_BENCH          0
#define TRIG_SRC_REAL           1

/* ------------------------------------------------------- setup validity --
 *
 * Bosch publish `engsetupOK_b` and state the consequence plainly: "A valid
 * setup configuration is indicated by engsetupOK_b = TRUE. If the setup is not
 * accepted the injection is switched off for safety reasons."
 *
 * Same rule here. hc_cfg_faults() returns 0 when the configuration describes a
 * runnable engine, and a bit mask of what is wrong otherwise. Nothing may be
 * driven while it is non-zero - a page half-edited through a single-value
 * write protocol passes through states that would otherwise fire an injector
 * at the wrong time.
 */
#define CFG_FAULT_CYLINDERS     0x0001  /* count out of range               */
#define CFG_FAULT_STROKES       0x0002
#define CFG_FAULT_TEETH         0x0004  /* SY_TEETH/SY_GAP not sane         */
#define CFG_FAULT_TDC_RANGE     0x0008  /* a TDC angle beyond 720 deg       */
#define CFG_FAULT_TDC_DUP       0x0010  /* two cylinders at the same angle  */
#define CFG_FAULT_CHANNEL       0x0020  /* an output index that cannot exist */
#define CFG_FAULT_REV           0x0040  /* rev limits inconsistent          */
#define CFG_FAULT_VERSION       0x0080

unsigned int  hc_cfg_faults(void);

/* ================================ the tables ============================
 *
 * Laid out after the scalars. Axes are u16 so an rpm axis can say 7000 and a
 * temperature axis can say -400 (0.1 degC) without a second scaling rule.
 * Cells are u8 to keep a map in 256 bytes; each map's comment says what one
 * count means, and that is the ONLY place the scaling is written down.
 */
/* VE is u16, 0.1 % per count (rusEFI veTable U16 0.1) - a 1 % byte
   was a 100 % step at the 1 % closed-throttle cells of an alpha-N table.
   It took the old VE and ignition bytes (128..639); the fuel axes moved to
   640, the ignition map to the end of the page (CAL_IGN_MAP below). */
#define CAL_FUEL_MAP           128      /* u16[256] VE, 0.1 % per count     */
#define CAL_FUEL_RPM_AX        640      /* u16[16]  rpm                     */
#define CAL_FUEL_LOAD_AX       672      /* u16[16]  load, 0.1 %             */
#define CAL_IGN_RPM_AX         704      /* u16[16]  rpm                     */
#define CAL_IGN_LOAD_AX        736      /* u16[16]  load, 0.1 %             */
#define CAL_AFR_MAP            768      /* u8[256]  target AFR x 10         */
#define CAL_CLT_ENR_AX        1024      /* u16[16]  coolant, 0.1 degC + 1000 */
#define CAL_CLT_ENR_VAL       1056      /* u8[16]   enrichment %, 100 = none */
#define CAL_CRANK_PW_AX       1072      /* u16[8]   coolant, 0.1 degC + 1000 */
#define CAL_CRANK_PW_VAL      1088      /* u16[8]   cranking pulse, us      */
#define CAL_DWELL_BATT_AX     1104      /* u16[8]   battery, 0.01 V         */
#define CAL_DWELL_BATT_VAL    1120      /* u16[8]   dwell, 0.01 ms          */
#define CAL_DEADTIME_VAL      1136      /* u16[8]   deadtime us, same axis  */
#define CAL_CLT_SENS_AX       1152      /* u16[16]  ADC counts              */
#define CAL_CLT_SENS_VAL      1184      /* u16[16]  0.1 degC + 1000         */
#define CAL_MAP_SENS_OFF      1216      /* u16      kPa x 10 at 0 counts    */
#define CAL_MAP_SENS_GRD      1218      /* u16      kPa x 10 per 1000 counts */
#define CAL_TPS1_MIN          1220      /* u16      counts at closed        */
#define CAL_TPS1_MAX          1222      /* u16      counts at open          */
#define CAL_TPS2_MIN          1224      /* u16      counts at closed        */
#define CAL_TPS2_MAX          1226      /* u16      counts at open          */
#define CAL_PEDAL1_MIN        1228      /* u16      counts, pedal released  */
#define CAL_PEDAL1_MAX        1230      /* u16      counts, pedal floored   */
#define CAL_PEDAL2_MIN        1232      /* u16      counts, pedal released  */
#define CAL_PEDAL2_MAX        1234      /* u16      counts, pedal floored   */
#define CAL_LOAD_SOURCE       1236      /* u8 0 SD, 1 alpha-N x p, 2 alpha-N */
#define CAL_INJ_MODE          1237      /* u8  0 = batch, 1 = sequential    */
#define CAL_FUELPUMP_PRIME_MS 1238      /* u16 prime time at key-on         */

/* ---------------------------------------------------- the throttle -------
 * CAL_DBW_ENABLE defaults to 0 and must be set deliberately. Nothing about
 * the electronic throttle happens until somebody turns it on, on purpose,
 * with the engine in front of them. */
/* The two byte-wide settings are kept ADJACENT so every 16-bit value below
   stays even-aligned without a padding byte that nothing owns - the .ini has
   to account for every byte of the page, and an unowned one is a hole. */
#define CAL_DBW_ENABLE        1240      /* u8  0 = the motor never moves    */
#define CAL_IAT_CHANNEL       1241      /* u8  0xFF = no sensor             */
#define CAL_DBW_KP            1242      /* u16 proportional gain, x100      */
#define CAL_DBW_KI            1244      /* u16 integral gain, x100          */
#define CAL_DBW_DEV_X10       1246      /* u16 allowed deviation, 0.1 %     */
#define CAL_DBW_DEV_MS        1248      /* u16 how long it may deviate, ms  */
#define CAL_DBW_LIMP_X10      1250      /* u16 limp-home position, 0.1 %    */

/* --------------------------------------------------- air temperature -----
 * The intake air sensor is wired to connector pin 85, which on this board
 * goes to the CG650 ASIC and NOT to the C167's own converter. There is no
 * read path for the ASIC and the stock image gave no evidence of one, so
 * rather than guess at a peripheral protocol this is a CHANNEL SELECTOR:
 *
 *   0xFF  no sensor - the error bit is set and IAT reads -40 C (V97;
 *         CAL_IAT_DEFAULT is stored but no longer read)
 *   0..15 the analog channel the sensor is actually wired to
 *
 * Connector pin 17 is `TMOT2` on AN13, a second temperature input this car
 * does not use. Moving the intake air sensor there makes it work with no
 * further change: set CAL_IAT_CHANNEL to 13 and calibrate the curve. */
#define CAL_IAT_DEFAULT       1252      /* u16 0.1 degC + CAL_TEMP_BIAS     */
#define CAL_IAT_SENS_AX       1254      /* u16[16] ADC counts               */
#define CAL_IAT_SENS_VAL      1286      /* u16[16] 0.1 degC + bias          */

/* ------------------------------------------------- ambient pressure ------
 * Also on the ASIC (an ADF4 sensor on the board itself, PXAN5). But it does
 * not need to be read at all: with the engine stopped the manifold IS at
 * ambient, so the manifold sensor measures barometric pressure directly at
 * key-on. That is ordinary practice and it needs no hardware we do not have. */
#define CAL_BARO_DEFAULT      1318      /* u16 0.1 kPa, if never captured   */

/* How to read the H-bridge's fault output on P2.9.
 *
 * I DO NOT KNOW THE POLARITY. The schematic shows `SF` going from the CJ220 to
 * P2.9 and nothing states which level means "fault", so rather than guess at
 * it - and this project has a rule about guessing at a peripheral - the mode is
 * calibratable and the raw pin is published as `dbwSfPin`.
 *
 * Determine it on the bench in one minute: enable the bridge with everything
 * healthy and read `dbwSfPin`; that level is HEALTHY. Then set this to the
 * other one.
 *
 *   0 = ignore the pin entirely (default - it cannot cause a false refusal)
 *   1 = a LOW level means the bridge has faulted
 *   2 = a HIGH level means the bridge has faulted
 */
#define CAL_DBW_SF_MODE       1320      /* u16 0 ignore, 1 low, 2 high      */

/* ============================ the throttle, the way rusEFI does it =======
 *
 * The first version of this module was a bare PI loop against a pedal, with
 * the travel limits typed in by hand off the raw ADC channels. rusEFI's
 * `electronic_throttle.cpp` does three things that are better, and all three
 * are here now.
 *
 * 1. THE ENDPOINTS ARE MEASURED, NOT TYPED. Autocal drives the motor open,
 *    waits, records both tracks; drives it closed, waits, records both tracks;
 *    and refuses the whole thing if the plate did not actually move. Two
 *    minutes of reading ADC counts off a screen becomes one button.
 *
 * 2. A FEED-FORWARD BIAS CURVE CARRIES THE LOAD. This is the part that makes
 *    an electronic throttle easy instead of hard. The plate has a return
 *    spring and a limp-home detent, so the duty needed to HOLD a position is a
 *    strongly non-linear function of that position - and it is the same
 *    function every time. Look it up, and the closed loop is left with a small
 *    correction rather than the whole job. rusEFI ships a measured curve for
 *    the Bosch VAG body, which is the one on this car, and it is the default.
 *
 * 3. THE GAINS ARE MEASURED TOO. Autotune runs the Astrom-Hagglund relay
 *    method: bang the duty plus and minus a fixed amplitude around 50 % open,
 *    let the plate oscillate, measure the period and amplitude of the limit
 *    cycle, and read Ku and Tu straight off it. Kp/Ki/Kd follow. The
 *    alternative is turning knobs on a bench until it stops buzzing.
 */
#define CAL_DBW_KD            1322      /* u16 derivative gain, x100        */
#define CAL_DBW_MIN_X10       1324      /* u16 never command below this     */
#define CAL_DBW_MAX_X10       1326      /* u16 never command above this     */
#define CAL_DBW_REVLIM_RPM    1328      /* u16 taper shut from here, 0 = off */
#define CAL_DBW_REVLIM_RANGE  1330      /* u16 rpm over which it fully shuts */

/* The bias curve. Position in, duty out - and the duty is SIGNED, so it is
   stored with a +1000 offset: 1000 means zero, 1200 means +20 %. Below the
   limp-home detent the throttle has to be pushed SHUT, which is a negative
   duty, and a curve that could not express that would fight the spring.
   Defaults are rusEFI's Bosch VNH2SP30 / VAG pair. */
#define CAL_DBW_BIAS_AX       1332      /* u16[8]  position, 0.1 %          */
#define CAL_DBW_BIAS_VAL      1348      /* u16[8]  duty + 1000              */

#define CAL_DBW_AUTOCAL_MS    1364      /* u16 hold each stop this long     */
#define CAL_DBW_AUTOCAL_DUTY  1366      /* u16 duty while calibrating, 0.1 % */
#define CAL_DBW_TUNE_AMP      1368      /* u16 relay amplitude, 0.1 %       */

/* Pedal to throttle, over rpm. Not a straight follow: the same pedal angle
   should not mean the same plate angle at idle and at 6000 rpm, and this is
   where drivability lives. One count = 0.5 % of throttle travel. */
#define CAL_PEDAL_MAP         1370      /* u8[256] target, 0.5 % per count  */
#define CAL_PEDAL_RPM_AX      1626      /* u16[16] rpm                      */
#define CAL_PEDAL_AX          1658      /* u16[16] pedal, 0.1 %             */

/* ================================ boost control =========================
 *
 * `N75` on `P7.1`, connector pin 104 - and P7.1 is `POUT1`, so the valve runs
 * on the same hardware PWM unit as the throttle and costs no interrupt.
 *
 * rusEFI's structure, because it is the right one: an OPEN LOOP DUTY MAP over
 * rpm and driver demand does most of the work, a target map says what boost
 * that should produce, and a PID trims the difference. A pure closed loop from
 * zero duty is slow to build and overshoots; a pure open loop cannot hold a
 * target across temperature and altitude. Both together is neither.
 *
 * CAL_BOOST_ENABLE defaults to 0. Nothing moves until somebody turns it on.
 */
#define CAL_BOOST_ENABLE      1690      /* u8  0 = the valve never moves    */
#define CAL_BOOST_MODE        1691      /* u8  0 = open loop, 1 = closed    */
#define CAL_BOOST_DUTY_MAP    1692      /* u8[256] open-loop duty, 0.5 %    */
#define CAL_BOOST_RPM_AX      1948      /* u16[16] rpm                      */
#define CAL_BOOST_TPS_AX      1980      /* u16[16] throttle, 0.1 %          */
#define CAL_BOOST_TGT_MAP     2012      /* u8[256] target, 1 kPa absolute   */
#define CAL_BOOST_TGT_RPM_AX  2268      /* u16[16] rpm                      */
#define CAL_BOOST_TGT_TPS_AX  2300      /* u16[16] throttle, 0.1 %          */
#define CAL_BOOST_KP          2332      /* u16 x100                         */
#define CAL_BOOST_KI          2334      /* u16 x100                         */
#define CAL_BOOST_KD          2336      /* u16 x100                         */
#define CAL_BOOST_MIN_RPM     2338      /* u16 below this the valve is idle */
#define CAL_BOOST_MIN_TPS_X10 2340      /* u16 below this the valve is idle */
#define CAL_BOOST_FREQ_HZ     2342      /* u16 valve frequency              */
#define CAL_BOOST_CUT_KPA     2344      /* u16 0.1 kPa absolute - OVERBOOST */
#define CAL_BOOST_CUT_HYST    2346      /* u16 0.1 kPa to come back         */
#define CAL_BOOST_CLT_AX      2348      /* u16[8]  coolant, 0.1 degC + bias */
#define CAL_BOOST_CLT_MUL     2364      /* u16[8]  duty multiplier, x100    */
#define CAL_BOOST_IAT_AX      2380      /* u16[8]  intake air               */
#define CAL_BOOST_IAT_MUL     2396      /* u16[8]  duty multiplier, x100    */

/* ==================== the four things a running engine still wanted =====
 *
 * Each of these was listed as missing and each is small. Together they are the
 * difference between an engine that runs on a bench and one that drives.
 */

/* Acceleration enrichment. A throttle opening faster than the manifold can
   fill leaves the mixture lean for a moment, and the fix is extra fuel
   proportional to how fast it is opening. Scaled by the warm-up factor, so a
   cold engine gets more without a second table. */
#define CAL_ACCEL_THRESH_X10  2412      /* u16 0.1 %/s before it triggers   */
#define CAL_ACCEL_GAIN        2414      /* u16 us of fuel per 1 %/s         */
#define CAL_ACCEL_DECAY_MS    2416      /* u16 how fast the shot decays     */

/* Overrun cut. Closed throttle above a speed means the driver has lifted;
   burning fuel into it achieves nothing. Resumes at a LOWER rpm than it cuts
   at, or it would chatter at the boundary. */
#define CAL_OVERRUN_RPM       2418      /* u16 cut above this, 0 = off      */
#define CAL_OVERRUN_TPS_X10   2420      /* u16 throttle below this = closed */
#define CAL_OVERRUN_RESUME    2422      /* u16 fuel back below this rpm     */

/* The rev limiter, and it is TWO different mechanisms on purpose.
 *
 * It used to cut SPARK ONLY, which pumps a raw charge into the exhaust on
 * every cut event and is how a limiter destroys a catalyst. So the DEFAULT is
 * now FUEL ONLY (mode 1): hcinj.c withholds valves on a rotating pattern -
 * MS 4 Sport's idea - so the cut is shared across cylinders and nothing
 * unburnt leaves the engine.
 *
 * SPARK, when selected (mode 0 or 2), is cut WHOLE rather than on a pattern.
 * That is not a preference, it is what could be demonstrated: the scheduler
 * offers each coil its dwell start about four times for every spark that
 * actually happens, so a six-in-eight pattern still let 97 % of the sparks
 * through while every counter said the limiter was working. A limiter that
 * "mostly" limits is worse than one that plainly does.
 *
 * CAL_REVLIM_PATTERN therefore applies to FUEL: how many events out of eight
 * are withheld. */
#define CAL_REVLIM_MODE       2424      /* u8 0 spark, 1 fuel, 2 both       */
#define CAL_REVLIM_PATTERN    2425      /* u8 events cut out of 8, 1..8     */

/* Idle, through the throttle. There is no idle valve on this engine - the
   electronic throttle IS the idle actuator, which is half the reason an ETB is
   fitted at all. The base position comes from a curve against coolant and a PI
   trims it to the target; the trim is bounded by CAL_IDLE_RANGE_X10 so a
   runaway integrator cannot open the throttle. */
#define CAL_IDLE_ENABLE       2426      /* u8  0 = no idle control          */
#define CAL_IDLE_PAD          2427      /* u8  keeps the u16s even-aligned  */
#define CAL_IDLE_TARGET_AX    2428      /* u16[8] coolant, 0.1 degC + bias  */
#define CAL_IDLE_TARGET_VAL   2444      /* u16[8] target rpm                */
#define CAL_IDLE_BASE_AX      2460      /* u16[8] coolant, 0.1 degC + bias  */
#define CAL_IDLE_BASE_VAL     2476      /* u16[8] base throttle, 0.1 %      */
#define CAL_IDLE_KP           2492      /* u16 x100                         */
#define CAL_IDLE_KI           2494      /* u16 x100                         */
#define CAL_IDLE_RANGE_X10    2496      /* u16 how far it may trim, 0.1 %   */
#define CAL_IDLE_RPM_BAND     2498      /* u16 rpm above target to engage   */

/* WHICH WAY ROUND THE PWM UNIT DRIVES ITS PIN.
 *
 * The C167 PWM has no output polarity bit - PWMCON1 carries enable, mode,
 * burst and single-shot and nothing else - and I could not establish from the
 * documentation in this repo whether POUTx is high while the timer is BELOW
 * the pulse-width register or above it. Both the throttle bridge and the boost
 * valve hang off that unit.
 *
 * For the throttle a wrong guess is merely useless: the plate would overshoot
 * and the deviation guard would latch. For the BOOST VALVE a wrong guess is
 * dangerous - 0 % commanded would be 100 % delivered, which is a wastegate
 * held shut. So it is not guessed. Put a scope on P7.1, command 20 %, and set
 * this to 1 if you measure 80 %.
 */
#define CAL_PWM_INVERT        2500      /* u8  1 = the unit drives inverted */
#define CAL_PWM_PAD           2501      /* u8  keeps the next u16 even      */

/* ==================== the universal configuration block =================
 *
 * ONE reserved region, generated. Everything above this line is the layout
 * this firmware has always had, and NOT ONE BYTE OF IT MOVES: every image
 * already flashed, the frozen V26 bench bundle and every .ini shipped with
 * them keep working exactly as they did.
 *
 * What lives here is the part of the configuration that describes the ENGINE
 * AND THE LOOM rather than the calibration - physical connector pins per
 * cylinder, execution strategy, sync mode, decoder selection, bank map, both
 * lambda channels, the dual-track correlation models, motorsport arming and
 * the bench test selector. The individual field offsets are NOT written here:
 * they are generated into generated/hc_config_generated.h from
 * tools/config_source/hanicore_config_def.py, and
 * tools/config_source/generate_config.py refuses to emit if the generated
 * block does not fit inside this reservation or if any field in it collides
 * with anything above.
 *
 * 512 bytes reserved against 168 currently used. The slack is deliberate: a
 * new universal field must never be a reason to move a calibration offset.
 * 1024 - knock, the lamp and VVT took the block past 512 (804). The
 * extra 512 came out of CAL_RESERVED, which nothing reads; no offset below
 * moved.
 * 1536 - the engine model block (firing order, load axes, lambda axes,
 * MAP estimate, priming, DFCO, closed-loop fuel, rev limit, motorsport,
 * injection timing table) took it to 1208. Again out of CAL_RESERVED; no
 * offset moved. 58 bytes stay reserved at the end of the page.
 * 1336 - the u16 VE table displaced the ignition map, which moved
 * to CAL_IGN_MAP at the end of the page (the old CAL_RESERVED tail and the
 * top 200 bytes of this reservation). 128 bytes stay free here.
 *
 * Read tools/config_source/hcconfig_layout.py for why the direction of
 * authority runs from THIS FILE outwards and never back.
 */
#define CFG_UNIVERSAL_BASE    2502      /* u8[1336] generated universal block */
#define CFG_UNIVERSAL_SIZE    1336

#define CAL_IGN_MAP           3838      /* u8[256]  advance, 0.5 deg, -20 offset */
#define CAL_RESERVED          4094      /* to HC_CFG_SIZE - 1               */

#define DBW_SF_IGNORE         0u
#define DBW_SF_FAULT_LOW      1u
#define DBW_SF_FAULT_HIGH     2u

#define CAL_IAT_NONE          0xFFu

#define CAL_LOAD_MAP            0
#define CAL_LOAD_TPS            1
#define CAL_LOAD_ALPHAN         2   /* pure alpha-N, 101.325 kPa */

/* Temperatures are stored with a +1000 bias so a u16 can hold -100.0 degC.
   One place, one rule. */
#define CAL_TEMP_BIAS          1000

/* ================================== the reset log ========================
 *
 * Bosch Motorsport's MS 4 Sport keeps a counter per RESET SOURCE - including
 * TASKLIST_DEADLINE_RESET, a missed task deadline - so that after a reset the
 * ECU can say why. HaniCore had nothing: on 2026-08-25 a whole bench round
 * went into diagnosing a reset loop by reading the shape of a truncated banner
 * off the wire, because there was no other evidence at all.
 *
 * The external SRAM is battery-backed, so it survives the reset that destroyed
 * everything else. This is the smallest thing that would have answered that
 * question in one glance: how many times we have booted, and HOW FAR the last
 * boot got before it stopped.
 */
#define RST_MAGIC_VAL   0x48435247uL    /* "HCRG" */
#define RST_BOOTS       4u              /* u16  boots since the log was made */
#define RST_STAGE       6u              /* u16  stage the current run reached*/
#define RST_MAXSTAGE    8u              /* u16  furthest ever reached        */
#define RST_TRAP       10u              /* u16  current last unclaimed vector*/

/* RESETDIAG_V1 expands the record without moving its original four fields.
   At ENTRY, the current-run fields are copied to PREV before they are
   cleared. The reset flags captured from the boot block then describe the
   reset which terminated that PREV run, so the two halves form one coherent
   post-mortem even when the ECU resets before a terminal can receive a line. */
#define RST_PREV_STAGE 12u
#define RST_RESET_RAW  14u              /* boot block's pre-SRVWDT WDTCON   */
#define RST_MS         16u              /* last persisted current tick      */
#define RST_LOOP       18u              /* last persisted main-loop count   */
#define RST_FIRSTVEC   20u
#define RST_LASTVEC    22u
/* FIVE GENERIC TARGET WORDS, and they are generic on purpose.
 *
 * These slots first appeared named RST_ASIC_STATE, RST_ASIC_TX and so on. That
 * was Bosch leaking into shared code: the 4B0906018DC has no ASIC, so on
 * that board the names would have been a lie and the ME7.5 target would have
 * had to pass dummies to satisfy a signature written for another ECU.
 *
 * hcconfig owns the LOG - its magic, its boot count, its stages, its layout.
 * What a board chooses to record in its own five words is the board's
 * business, and each target documents its own meaning beside the call. */
#define RST_TGT0       24u
#define RST_TGT1       26u
#define RST_TGT2       28u
#define RST_PREV_MS    30u
#define RST_PREV_LOOP  32u
#define RST_PREV_FIRSTVEC 34u
#define RST_PREV_LASTVEC  36u
#define RST_PREV_TRAP     38u
#define RST_PREV_TGT0     40u
#define RST_PREV_TGT1     42u
#define RST_PREV_TGT2     44u
#define RST_WDT_COUNT       46u
#define RST_MARKER          48u
#define RST_TGT3            50u
#define RST_TGT4            52u
#define RST_PREV_WDT_COUNT  54u
#define RST_PREV_MARKER     56u
#define RST_PREV_TGT3       58u
#define RST_PREV_TGT4       60u
/* Added for the A/B reset experiment. TRAP_MS is written from INSIDE the trap
   handler, beside the trap number, because the 10 ms progress raster never
   runs again after a reset arrives - which is exactly what happened on the
   second Bosch hardware run, where TR was captured and FV/LV were not.
   COND is whatever condition the target is running this boot under. */
#define RST_TRAP_MS         64u
#define RST_PREV_TRAP_MS    66u
#define RST_COND            68u
#define RST_PREV_COND       70u
#define RST_LAYOUT          62u              /* layout stamp, see below      */
#define RST_LAYOUT_V1       0xD101u          /* RESETDIAG_V1                 */
#define RST_LAYOUT_V2       0xD102u          /* + TRAP_MS and COND           */
#define RST_LAYOUT_CUR      RST_LAYOUT_V2
#define RST_LAST            RST_PREV_COND    /* highest offset in the record */
#define RST_TGT_WORDS        5u

/* Boot stages, in order. A repeating boot that always stops at the same one
   says exactly where to look. */
#define RST_ST_ENTRY    1u              /* main() entered                    */
#define RST_ST_SERIAL   2u              /* ASC0 up                           */
#define RST_ST_CONFIG   3u              /* calibration loaded                */
#define RST_ST_TIMERS   4u              /* um_init, trigger, scheduler       */
#define RST_ST_CAL      5u              /* T7 calibrated                     */
#define RST_ST_PROBE    6u              /* receive-interrupt probe done      */
#define RST_ST_BANNER   7u              /* banner fully transmitted          */
#define RST_ST_ARMED    8u              /* responder armed, interrupts on    */
#define RST_ST_LOOP     9u              /* main loop entered                 */

void          hc_rst_stage(unsigned int stage);
void          hc_rst_reset_raw(unsigned int raw);
/* tgt points at RST_TGT_WORDS words whose meaning belongs to the target. */
void          hc_rst_progress(unsigned int ms, unsigned int loops,
                              unsigned int firstvec, unsigned int lastvec,
                              unsigned int wdt_count,
                              unsigned int *tgt);
void          hc_rst_marker(unsigned int marker);
void          hc_rst_vector(unsigned int vector);
/* Same, but timestamped - call it from inside a trap handler. */
void          hc_rst_vector_at(unsigned int vector, unsigned int ms);
/* Which experimental condition this boot is running. */
void          hc_rst_cond(unsigned int cond);
unsigned int  hc_rst_get(unsigned int off);

/* ------------------------------------------------------------ accessors -- */
extern unsigned char hc_cfg[HC_CFG_CORE];

unsigned int  cfg_u16(unsigned char off);
void          cfg_set_u16(unsigned char off, unsigned int v);
#define cfg_u8(off)         (hc_cfg[(off)])
#define cfg_set_u8(off, v)  (hc_cfg[(off)] = (unsigned char)(v))

/* The WHOLE page, scalars and tables alike. Anything above HC_CFG_CORE lands
   in the external SRAM; below it, in hc_cfg[]. TunerStudio and every table
   lookup go through these and never need to know where the byte lives. */
unsigned char hc_cal_u8(unsigned int off);
void          hc_cal_set_u8(unsigned int off, unsigned char v);
unsigned int  hc_cal_u16(unsigned int off);
void          hc_cal_set_u16(unsigned int off, unsigned int v);

/* Interpolation. Both clamp at the ends rather than extrapolating - an axis
   that stops at 7000 rpm must not invent a value at 8000. */
unsigned int  hc_cal_curve16(unsigned int ax_off, unsigned int val_off,
                             unsigned char n, unsigned int x);
unsigned char hc_cal_map(unsigned int map_off, unsigned int rpm_ax_off,
                         unsigned int load_ax_off,
                         unsigned int rpm, unsigned int load);
/* the same lookup over u16 cells (CAL_FUEL_MAP) */
unsigned int  hc_cal_map16(unsigned int map_off, unsigned int rpm_ax_off,
                           unsigned int load_ax_off,
                           unsigned int rpm, unsigned int load);

/* ------------------------------------------------------------- lifecycle --
 *
 * hc_cfg_init() decides where the live configuration comes from:
 *
 *   - the battery-backed external SRAM, if what is there carries our magic,
 *     our version, our size and a matching checksum;
 *   - otherwise the compiled-in defaults, which are then written to SRAM.
 *
 * hc_cfg_commit() is what a TunerStudio BURN does today: it recomputes the
 * checksum and writes the page back to the standby SRAM, so the edit survives
 * a reset. Flash persistence is a later milestone; the SRAM is battery-backed
 * (schematic: TC55257 powered from VSTBY), so this is real persistence as long
 * as the battery stays connected.
 */
void          hc_cfg_init(void);
void          hc_cfg_commit(void);

/* Diagnostics, published in the output channels so the bench can see what
   happened without guessing. */
extern unsigned int hc_cfg_source;      /* 0 defaults 1 SRAM 2 no store
                                           3 restored from FLASH            */
extern unsigned int hc_ram_bad;         /* external SRAM test failures      */

/* Called by whatever non-volatile store a target actually has, and by nothing
   else. Whether this ECU has a usable calibration in a non-volatile device is
   a fact READ OUT OF THE DEVICE at boot, never a property of the build - so it
   is set at runtime, and a target with no such store simply never calls this
   and hc_cfg_persist_class() keeps answering HC_PERSIST_STANDBY, which is the
   truth on that board. The flag itself lives in the external SRAM, not in near
   RAM; see the note beside NONVOL_OFF in hcconfig.c. */
void hc_cfg_set_nonvol(unsigned char present);

/* ------------------------------------------------- WHAT "PERSISTENT" MEANS
 *
 * Say it out loud, because a configuration system that quietly believes its
 * storage is non-volatile will one day hand somebody a factory-reset engine
 * after a battery change.
 *
 * A burn on these boards writes the page into the TC55257 external SRAM. That
 * part's VDD comes from the supply ASIC's VSTBY rail [BOSCH-SCH], so the page
 * survives KL15 off, a watchdog reset and a software reset. IT DOES NOT
 * SURVIVE A DISCONNECTED BATTERY, a flat battery, or the ECU being taken off
 * the car - the moment VSTBY goes away the SRAM forgets, hc_cfg_init() finds
 * no magic and the ECU comes up on its built-in defaults.
 *
 * That is a real and useful class of persistence and it is what makes a
 * TunerStudio burn meaningful today. It is NOT flash, and no part of HaniCore
 * may claim it is.
 *
 * ON THE ME7.1.1 TARGET THAT SENTENCE NOW HAS AN EXCEPTION, and this function
 * is the one place that knows about it. hcnvm.c keeps an A/B record in flash
 * sectors SA7/SA8 - magic, derived layout id, version, length, generation, two
 * CRCs and a commit marker written LAST - and calls hc_cfg_set_nonvol() when a
 * valid, committed one is actually present in the device. Only then does this
 * function answer HC_PERSIST_NONVOL. On any target without such a store
 * nothing ever calls it and the old, honest answer stands.
 */
#define HC_PERSIST_NONE       0u  /* nothing survives even a reset          */
#define HC_PERSIST_STANDBY    1u  /* survives reset and KL15 off; NOT a
                                     disconnected battery                   */
#define HC_PERSIST_NONVOL     2u  /* survives loss of all power             */

unsigned int hc_cfg_persist_class(void);

/* How far into the external SRAM the page itself starts: the header sits in
   front of it. hcflash.c needs this to checksum the page as one block. */
#define HC_CFG_HDR_LEN      12u

/* 1 while the page has stopped changing. TunerStudio writes a 16-bit value as
   two SEPARATE one-byte writes, so anything that reads a multi-byte page value
   live must wait for this - otherwise it can act on half of the old value and
   half of the new one. Maintained by main(). */
extern unsigned char hc_cfg_stable;

#endif /* HCCONFIG_H */
