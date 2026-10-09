/*
 * hc_validation.h - the configuration validation engine.
 *
 * ONE implementation, callable against either image, from every place that
 * needs an answer: a staged apply, a commit, boot, a preset application, a
 * wizard finishing. Bosch state the consequence plainly in the Funktionsrahmen
 * and hcconfig.h already quotes it - "if the setup is not accepted the
 * injection is switched off for safety reasons" - so the answer has to mean
 * the same thing wherever it is asked.
 *
 * FOUR RULES THIS ENGINE IS BUILT AROUND, each of which the first version
 * broke:
 *
 * 1. TRIGGER VALIDATION IS PER DECODER. "teeth >= 4", "missing < teeth" and
 *    "gap ratio >= 1.2" describe a MISSING-TOOTH wheel. Enforcing them against
 *    a decoder that has no gap rejects a configuration that is perfectly
 *    sound. Each decoder's rules live in its own branch.
 *
 * 2. SYNC VALIDATION IS PER EXECUTION STRATEGY, NOT PER COIL COUNT. "COP
 *    requires cam sync" is false: wasted-COP fires an individual coil on every
 *    revolution and needs no cycle position at all. What needs cycle position
 *    is SEQUENTIAL injection and SEQUENTIAL COP ignition. The question is what
 *    the strategy does, not how many coils are bolted on.
 *
 * 3. A PIN MUST HAVE EVERY CAPABILITY THE FUNCTION NEEDS, NOT ANY OF THEM.
 *    See hc_pin_can().
 *
 * 4. A WARNING IS NOT AN ERROR. "Launch enabled with no arming source" should
 *    tell the tuner something is missing; it must not refuse to apply an
 *    injector routing.
 *
 * BOUNDED. No allocation, no recursion, every loop counted by a configuration
 * value that is itself range-checked first. Worst case is O(cylinders^2) for
 * the duplicate scans with cylinders <= 12, plus one pass over each axis.
 */
#ifndef HC_VALIDATION_H
#define HC_VALIDATION_H

#include "hctarget.h"   /* HC_COLD: far on ME7.1.1 (FCODE), empty elsewhere */
#ifndef HC_COLD
#define HC_COLD
#endif

/* Which image to validate. */
#define HC_VAL_SRC_ACTIVE       0u
#define HC_VAL_SRC_DESIRED      1u

/* ------------------------------------------------------------- errors ----
 * An error means the configuration does not describe a runnable engine.
 * Nothing may be driven while any of these is set. */
#define HC_VAL_OK                   0x0000u
#define HC_VAL_FAULT_SCHEMA         0x0001u  /* page version / universal magic */
#define HC_VAL_FAULT_CYLINDERS      0x0002u  /* count out of range             */
#define HC_VAL_FAULT_TDC            0x0004u  /* TDC angle out of range or dup  */
#define HC_VAL_FAULT_TRIGGER        0x0008u  /* decoder-specific geometry      */
#define HC_VAL_FAULT_SYNC           0x0010u  /* strategy needs position it has
                                                no configured way to get       */
#define HC_VAL_FAULT_PIN_CAP        0x0020u  /* pin cannot do what is asked    */
#define HC_VAL_FAULT_PIN_CONFLICT   0x0040u  /* one pin, two exclusive owners  */
#define HC_VAL_FAULT_REV            0x0080u  /* speed limits inconsistent      */
#define HC_VAL_FAULT_DBW            0x0100u  /* throttle cannot be driven safely */
#define HC_VAL_FAULT_AXIS           0x0200u  /* a table axis is not monotonic  */
#define HC_VAL_FAULT_LAMBDA         0x0400u  /* lambda channels inconsistent   */
#define HC_VAL_FAULT_STRATEGY       0x0800u  /* output count vs cylinder count */
#define HC_VAL_FAULT_TARGET         0x1000u  /* pin does not exist on THIS ECU */
#define HC_VAL_FAULT_NOT_STOPPED    0x2000u  /* returned by an apply, not by a
                                                validation - the engine is
                                                still turning                  */

/* ----------------------------------------------------------- warnings ---
 * A warning means something is probably not what the tuner intended. It never
 * blocks an apply. */
#define HC_WARN_NONE                0x0000u
#define HC_WARN_NO_LAMBDA           0x0001u  /* closed loop impossible         */
#define HC_WARN_LAUNCH_NO_SOURCE    0x0002u  /* enabled, no arming pin         */
#define HC_WARN_ANTILAG_NO_SOURCE   0x0004u
#define HC_WARN_FLATSHIFT_NO_SOURCE 0x0008u
#define HC_WARN_PITLIM_NO_SOURCE    0x0010u
#define HC_WARN_NO_MAP_SENSOR       0x0020u  /* load source is MAP, no pin     */
#define HC_WARN_BOOST_NO_PIN        0x0040u  /* boost enabled, valve unrouted  */
#define HC_WARN_OILP_NO_SENSOR      0x0080u  /* protection set, no sensor      */
#define HC_WARN_UNVERIFIED_PIN      0x0100u  /* assignment rests on a PROBABLE
                                                hardware claim                 */
#define HC_WARN_OUTPUTS_ARMED       0x0200u  /* live outputs are armed         */
/* a THROTTLE-keyed table whose load axis leaves 0..100 % (top past
   100.0 %: dead rows) or starts at 10 % or more (idle clamps into a part-
   load row). TunerStudio's VE Table Generator wrote a 15..160 kPa axis on
   the alpha-N car page. */
#define HC_WARN_VE_AXIS             0x0400u
#define HC_WARN_IGN_AXIS            0x0800u
#define HC_WARN_LAM_AXIS            0x1000u
/* The configured bridge PWM frequency is inside the range this board will
   accept, but above what the CJ220 is rated for on a SAGGED rail. Its
   datasheet derates by supply - 20 kHz at 8..12 V, 10 kHz at 7..8 V,
   5 kHz at 6..7 V - and a cranking rail reaches 5.7 V on this car.
   Above 5 kHz the plate keeps full authority on a healthy battery and
   loses some of it while cranking, so this is advice, not a refusal. */
#define HC_WARN_DBW_PWM_SAG         0x2000u

/* Validate one image. Returns the ERROR mask; the warnings from the same pass
   are left in hc_val_warnings. */
unsigned int HC_COLD hc_validate(unsigned char src);

/* Warnings from the most recent hc_validate(). */
extern unsigned int hc_val_warnings;

/* The first field offset that failed, or 0xFFFF. Turns "PIN_CAP" into "pin
   assignment at offset N", which is what a tuner needs to fix it. */
extern unsigned int hc_val_first_bad_offset;

#endif /* HC_VALIDATION_H */
