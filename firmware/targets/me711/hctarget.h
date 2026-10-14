/*
 * hctarget.h - EVERYTHING that depends on which ECU this is built for.
 *
 *      TARGET: Bosch ME7.1.1, hardware 0261207696, software 1037371766,
 *              project OEM ME7.1.1, variant 44F, Bosch 8SE4AKN00000, V8.
 *              EPK 40/1/ME7.1.1/4/OEM ME7.1.1//44F/DstBKo/070604/3/
 *
 * The protocol, the calibration page, the scheduler and the TunerStudio server
 * are SHARED with the 4B0906018DC ME7.5 target. Only this file, the startup and
 * the ASIC transport are Bosch's. If a number could differ between the two
 * ECUs for any reason other than the circuit board, it does not belong here -
 * it belongs in hcconfig.h, where TunerStudio can reach it.
 *
 * EVIDENCE CLASSES used in the comments below:
 *   [OEM ME7.1.1]     read out of the target OEM firmware
 *   [BOSCH-PM]  the ME7.1.1 schematic set sheet "FR", column
 *               "Belegung ME7.1.1" - Bosch's own ME7.1.1 port map
 *   [BOSCH-SCH] the ME7.1.1 schematic set Rechnerkern.pdf
 *               and ...0.1.1- Ein-Ausgaenge.pdf
 *   [DS]        Infineon C167CR User's Manual V3.1, docs/c167cr_um.pdf
 *   [ME75]      carried over from the bench-proven 4B0906018DC firmware
 *   [INF]       inference, stated as such
 */
#ifndef HCTARGET_H
#define HCTARGET_H

/* =============================================== identity and build type == */

#define TGT_ID                0x0711      /* ME7.1.1, 0261207696 / 1037371766              */

/* THE OUTPUTS ARE NOW BUILT, so this veto is withdrawn - V63.
 *
 * The rule this replaced said removing HANICORE_BENCH_SAFE "is a deliberate
 * act and it is not enough on its own - the outputs also have to be built."
 * They are: hchal_me711.c carries a real output back end from V63, resolving
 * a configured cavity to a port bit for every injector, coil, the fuel pump
 * and the throttle bridge.
 *
 * WHAT NOW KEEPS AN ENGINE OUTPUT OFF is runtime conditions rather than a
 * compile switch, and all are required before one pin is driven ON:
 *
 *   1. the class is permitted      - hcsafety.c: spark and fuel need the
 *                                    crank; throttle, pump and relay need the
 *                                    S5500 link, a valid page and the key on.
 *                                    there is NO user-facing arm - the
 *                                    page byte CFG_OUTPUTS_ARMED is retired;
 *   2. hc_cfg_validation == 0      - a page hc_validate() refused can never
 *                                    reach a motor;
 *   3. the semantic is ROUTED      - an unassigned cavity drives nothing.
 *
 * A bench actuator test is a separate path (hcbench.c) whose deliberate act
 * is its own explicit, bounded command.
 *
 * AND THE RESTING STATE IS HIGH IMPEDANCE, NOT A LEVEL. hc_hal_outputs_safe()
 * runs first in hc_hal_init(), before the configuration is read, and puts
 * every engine output pin back to INPUT. That matters because the active
 * polarity of the CJ920/CJ420 stages is NOT established anywhere in this
 * repository - a resting level would be a guess and a wrong guess is an
 * injector held open by a parked ECU, while a resting direction drives
 * nothing whichever way the stage is wired.
 *
 * Define HANICORE_BENCH_SAFE again to force hc_hal_outputs_live() to 0 at
 * compile time. The back end stays linked; it simply becomes unreachable. */
/* #define HANICORE_BENCH_SAFE   1 */

/* The closed-loop throttle controller. It contains no pin, no port and no
   sbit - it computes a duty and a direction - so compiling it in cannot by
   itself move a plate; only the back end above can, and only when armed. */
#define TGT_DBW_CONTROLLER    1
#define TGT_DBW_MOTOR_PRIMITIVE 1

/* THE BURN FORENSICS AND THE ASIC DUMP, and why V63 does not carry them.
 *
 * C167 SMALL model caps code at 64 K. V62 finished at 64390 bytes of 64512 -
 * 122 free - so the engine back end this release exists to build had nowhere
 * to go. The alternatives were re-laying the image under a far-code memory
 * model or moving a module to another segment, and both put the QUALIFIED
 * live-Burn path back under re-qualification for a reason unrelated to the
 * burn. hcnvm.c is 13 364 of those bytes and me711_v48_live_burn_proof reads
 * its linked opcodes.
 *
 * So the 4204 bytes come from the two modules that are pure instrumentation:
 * hcliveforensics.c (2130) and hcasicdump.c (2074). They were built to
 * diagnose live-Burn resets, they did that job across V47..V50, and the
 * answer is frozen in V62 - which keeps them.
 *
 * WHAT AN IMAGE WITHOUT THIS GIVES UP, stated rather than glossed: it cannot
 * explain a live-Burn reset after the fact. The Burn itself is unchanged and
 * still refuses, still bounded, still CRC-checked. Define this to get them
 * back, at 4204 bytes. */
/* #define TGT_BURN_DIAGNOSTICS 1 */

#define TGT_SIGNATURE         "rusEFI HaniCore ME711 5AB824FA"
/* THE SIGNATURE CARRIES THE PAGE LAYOUT, AND UNTIL V60 IT DID NOT.

   It read "rusEFI Hanicore v1" from V21 to V59 - a frozen literal
   across thirty-eight releases, five of which MOVED THE CALIBRATION
   PAGE. TunerStudio has exactly one mechanism for refusing an .ini
   that does not describe the controller in front of it, and that
   mechanism is the signature. A constant one disables it.

   WHAT THAT COST, MEASURED ON THIS ECU 2026-09-16. V55 inserted eight
   bytes at offset 2540 - trigAngleX10 (V96: trigOffsetX10), camRefs, camPad, camRefX10,
   camWindowX10 - so every field above it moved. The V48 .ini and the
   V59 .ini declare the SAME signature and disagree about every one of
   them: V48 puts pinCrank at 2540, this firmware reads it at 2548. The
   operator ran the V48 .ini against V59 firmware, TunerStudio accepted
   it without a word, and the Trigger dialog showed a crank pin that
   was assigned while the byte the firmware validates read 0xFF. The
   Burn was refused - correctly - for a fault the tuner could not see
   and could not have fixed from that .ini.

   HC_CFG_LAYOUT_ID is already a CRC32 over every field's slot name,
   offset, C type and element count, and hcnvm.c already refuses a
   STORED record whose layout id does not match. A stored record was
   protected and a live tuning tool was not. It is the same question.

   The tag is HC_CFG_LAYOUT_ID in hex. It is not derivable by the C
   preprocessor from a numeric #define, so it is PROVEN instead:
   build_hanicore_me711.py refuses to emit an image whose signature tag
   disagrees with the generated layout id, and ts_signature_layout_proof
   is the gate. gen_ts_ini_me711.py reads the signature from this line,
   so the .ini cannot lag it.

   THE "rusEFI " PREFIX IS A TUNERSTUDIO COMPATIBILITY WORKAROUND, not a
   claim of identity: HaniCore is not rusEFI firmware. TunerStudio selects
   its rusEFI-protocol handling from that prefix, and every working
   HaniCore setup so far depends on it. Everything after it is HaniCore's.
   Do not rename it for branding without a proven supported alternative. */
/* WHAT THE ECU CALLS ITSELF, and it must name the build in the filename.

   ON THE BENCH, 2026-09-02, the frozen V29 image identified itself as
   "HaniCore V28 TRIGGER COMM". This literal was last edited for V28 and
   nothing bumped it for V29 or V30, so a hardware log recorded the wrong
   build against a real physical result - which is exactly what made six
   gates auditable against a stale binary before tools/me711_image.py, one
   layer up. An artefact that misreports its own identity turns every log
   about it into evidence for something else.

   tools/build_hanicore_me711.py now REFUSES to emit an image whose
   version string does not contain the version in its own output stem, so
   this cannot silently lag a build again. */
#define TGT_VERSIONTXT        "HaniCore V102 DEV / Bosch ME7.1.1"
/* + " build XXXXXXXX" (TGT_BUILD_SUFFIX): the source hash of THIS image,
   written by tools/build/build_hanicore_me711.py before every compile, so
   the 'V' reply names the exact build (2026-10-11). */
#include "build/hc_build_id.h"

/* HC_COLD marks the public functions of the modules compiled MOD167
   MEDIUM (FCODE, segment 0x85): validation, the config manager, the bench
   qualifier and analog routing. Their NCODE callees go through the far
   thunks in hcfar_me711.c - see hcfarbridge.h and docs/ARCHITECTURE.md. */
#define HC_COLD far
/* the generated preset item tables (~10 KB) live in HCONST, not in
   the 16 KB near-constant class NCONST, which they had filled - the u16 VE
   table's first use of a new constant failed the link (L115 DGROUP). huge,
   so an array may cross a 16 KB page; read only by an APPLY. */
#define HC_PRESET_MEM huge
/* Deliberate release identity, not a claim about a Git commit. The release
   manifest separately records the source-build and packaging commits. */
#define TGT_RELEASE_ID        0x446Eu    /* V102 = 17416 + 102. V100 was 0x446C,
                                          V98 0x446A, V97 0x4469. V81..V93 all
                                          shipped V80's 0x4458 (found by the
                                          V93 Tier 2 identity_proof).
                                          Deterministic development ID.
                                          V44 = 0x4434, V48 = 17464, V49 =
                                          0x4439, V50 = 0x443A, V51 = 0x443B,
                                          V52 = 0x443C, V53 = 0x443D: the
                                          series is 17416 + the version
                                          number, so V59 = 17475.

                                          V55 IS NOT REUSED. It was
                                          flashed and it is what found the
                                          cam-absent Burn block; that
                                          binary stays as the evidence of
                                          the failure.

                                          V54 IS NOT REUSED. The binary
                                          physically qualified on 2026-09-14 -
                                          80 Burns, 2 reclaims, zero resets -
                                          is D4B9A272..., kept in
                                          release/Porsche_ME711_V54_FLASH_FAULT_EXIT.
                                          V55 restores the crank-angle
                                          scheduler and the DBW controller that
                                          V47..V54 compiled out, and makes the
                                          trigger decoder read its wheel from
                                          the page, so it is a different image
                                          and it says so.

                                          V53 IS NOT REUSED. The binary that
                                          was physically qualified on
                                          2026-09-13 - 88 Burns, 3 reclaims,
                                          zero resets - is A90D17DE..., kept
                                          in release/Porsche_ME711_V53_ROTATION.
                                          Two firmware fixes have landed since
                                          (retry_target's wild cell read, and
                                          the writer returning into a busy
                                          device), so this is a different
                                          image and it says so. */
#define TGT_LIVE_BURN_HYBRID_QUAL 1
/* THE ENGINE RUNTIME IS BACK, AND IT IS ITS OWN SWITCH.
 *
 * V47..V54 stubbed out the crank-angle scheduler and the DBW controller by
 * gating them on TGT_LIVE_BURN_HYBRID_QUAL above - the same symbol that names
 * the burn-forensics instrumentation. That coupling is what made "resume the
 * engine runtime" look like "reopen the persistence work", which it is not.
 * TGT_ENGINE_RUNTIME compiles hcsched_dry.c's planner and hc_dbw.c's
 * controller; TGT_LIVE_BURN_HYBRID_QUAL keeps hcburnforensics.c exactly as
 * V54 shipped it. Neither module the persistence qualification depends on -
 * hcnvm.c, hcts.c, hcasic*.c, hcumkom.c - is touched by either symbol. */
#define TGT_ENGINE_RUNTIME 1
/* The DBW controller is a separate switch from the scheduler because it is a
   separate question: hc_dbw.c computes a duty and a direction and contains no
   pin, no port and no sbit, so compiling it cannot move a throttle plate -
   only hcbench.c can reach the bridge, under its own invariants.
 *
 * AND IT IS OFF AGAIN AT V56, DELIBERATELY. It costs 2632 bytes of NCODE, and
 * NCODE is one CGROUP with a hard 0x84FFFF ceiling (docs/ARCHITECTURE.md).
 * After the V56 cam-fault fix there were 36 bytes left - not enough to ship,
 * let alone to edit again.
 *
 * Nothing is lost by dropping it now. `dbwEnable` is 0, `armed` is 0, the HAL
 * is unbound, `hc_hal_out()` contains no port write, and only hcbench.c's
 * bounded nudge can reach the bridge - so the controller could not be
 * physically exercised in this release under any configuration. It was
 * restored in V55 speculatively, alongside the scheduler, because one symbol
 * gated both; it is not on the path to the engine running.
 *
 * It comes back with the FCODE work, which is what actually buys the room.
 * Until then this line is the single edit that restores it. */
/* TGT_DBW_CONTROLLER is defined in the identity block above. */
/* Retain the compact B-path forensic hooks; this compatibility symbol names
   instrumentation only, not an intentional reset policy. */
#define TGT_BURN_RESET_FORENSICS 1

/* The Bosch application does not use a bare SRVWDT in normal runtime. Its
   two ordinary service sites at OEM ME7.1.1 0x8223BA and 0x8231D8 load R12 with
   0xCF01 immediately before calling the primitive at 0x8076C2, which writes
   R12 to WDTCON and then executes SRVWDT. The C167 manual also advises
   rewriting WDTCON before every service. RESETDIAG_V1 reproduces that exact
   sequence; the former bare instruction left the boot-block-selected reload
   policy in force. The raw reset flags distinguish this internal mismatch
   from the independently proven ASIC reset output on the next bench run. */
/* THE WATCHDOG SERVICE VALUE, and why it is this one.
 *
 * [OEM ME7.1.1] 0x8076C2 is the OEM's whole watchdog service and it is two
 * instructions:
 *
 *     F6 FC AE FF    MOV WDTCON, R12
 *     A7 58 A7 A7    SRVWDT
 *
 * which is exactly what the datasheet advises: "For safety reasons, the user
 * is advised to rewrite WDTCON each time before the watchdog timer is
 * serviced" (C167CR UM 13.1). Callers pass R12 from a table at 0x0076B2 that
 * the boot block indexes with a clock/strap value read from ESFR 0xF108:
 *
 *     [0] 8501  [1] 6D01  [2] 3C01  [3] 0B01     <- the ~400 ms group
 *     [4] E701  [5] E201  [6] D801  [7] CF01     <- the ~80 ms group
 *
 * Every entry has WDTIN = 1, so the prescaler is fCPU/128 throughout. The two
 * groups are the same four ratios, five times apart: the table holds a
 * CONSTANT time across four clock options. Entry [3] gives 401.4 ms at 20 MHz
 * and entry [7] gives 80.3 ms.
 *
 * THE FIRST HARDWARE RUN RESET EVERY ~420 ms, and that is entry [3] plus the
 * ~19 ms the boot block and the banner take: the boot block installs a 401 ms
 * window and the first HaniCore image never held it off.
 *
 * RESETDIAG_V1 therefore uses 0x0B01 - the SAME window the boot block installs
 * - and NOT the OEM's 0xCF01 runtime value. A diagnostic build must not
 * tighten a deadline it is trying to measure: 0xCF01 would cut the window to
 * 80 ms, and a build that then reset would leave us unable to say whether the
 * service is working or whether the window simply got shorter. 0x0B01 changes
 * one variable and only one.
 *
 * Once the service is proven on hardware, 0xCF01 is the value to adopt for a
 * running engine, because 80 ms is a real supervision interval and 401 ms is
 * not. */
/* RESETDIAG_V1 ISOLATES THE ASIC LINK, and it is compiled out rather than
   merely not called. See the long note in hcasic.c: a routine that programs
   PEC pointers and sets SSCEN must be ABSENT from a build whose whole purpose
   is to test ONE reset hypothesis, and tools/me711_wdt_audit.py fails the
   build if those register writes appear in the final BIN. */
#define TGT_ASIC_ISOLATED     0

#define TGT_WDTCON_SERVICE    0x0B01u
#define TGT_WDTCON_OEM_RUN    0xCF01u   /* what a running ME7.1.1 uses */
#define TGT_RSTDIAG_WDT_COUNT 1
/* every SRVWDT also marks the runtime health record's
   watchdog-gap high-water (hcsafety.c hc_rt_wdt_mark). */
void hc_rt_wdt_mark(void);
#define TGT_SRVWDT_HOOK() hc_rt_wdt_mark()

/* ===================================================== reset-cause flags ==
 *
 * [DS] C167CR UM 13.1, WDTCON<15:8>: bit 4 LHWR, bit 3 SHWR, bit 2 SWR, bit 1
 * WDTR. There is no hardware PONR bit - "power-on" is not a flag the C167
 * itself latches. [OEM ME7.1.1] 0x807766 (the boot block, before its first SRVWDT)
 * folds one more bit INTO the value it hands this firmware in T0: every warm
 * reset on this bench reads RAW=0x001C (LHWR|SHWR|SWR), while the first boot
 * of a session - a genuine power-on - reads RAW=0x003C, exactly 0x0020 more.
 * See docs/ARCHITECTURE.md ("the reset mechanism NAMED"), hcpower.c and
 * hcasicstart.c, which independently document the same two observed values.
 * TGT_RESET_PONR names that boot-block-synthesized bit so it is declared
 * once, like every other shared layout constant in this file. */
#define TGT_RESET_PONR        0x0020u

/* The 96-word ASIC startup payload is not yet understood at field level.
   OEM copies a dedicated initialization block; the previous HaniCore build
   sent a runtime-style 0xBAA5/zero frame instead. RESETDIAG_V1 leaves P6.4
   deselected/input and the SSC pins as inputs, so this experiment cannot
   accidentally turn an opaque word into an output command. */
#define TGT_ASIC_DIAG_ISOLATE 1
/* 96 bytes of named diagnostics + 16 raw ADC counts = exactly 128. At 57600
   baud the whole block is one 24 ms reply, in ONE request - the shared core
   streams, so there is no reply-size ceiling to work around. */
/* 96 bytes of platform diagnostics + 16 raw ADC counts + the V20 runtime
   block (engine values, position, the HAL validity mask, the output census
   and the 16-word S5500 correlation window) = 208.
   THE SIZE HAS A COST AND IT IS NOT FREE: at 57600 baud a full read of this
   block is 208 + 7 bytes of envelope = ~37 ms on the wire, and hcts_tx() is
   blocking. That is survivable ONLY because hcts_target_yield() services the
   10 ms S5500 raster inside the transmit wait - see hcmain_me711.c. Do not
   grow it without re-running tools/me711_ts_gap_proof.py. */
/* 368, up from 336, to make room for the universal configuration's own state
   at 336..354. It is a TunerStudio contract change - ochBlockSize moves with
   it, and tools/gen_ts_ini_me711.py reads this define so the two cannot
   disagree - and it lengthens the output-channel reply by 32 bytes.
   me711_ts_gap_proof.py measures what that does to the S5500 service gap
   rather than assuming: the yield hook services the raster DURING the reply,
   so the worst gap is bounded by the yield period and not by the reply
   length. TGT_RAM_OCH_LIMIT is 1024, so the region has ample room. */
#define TGT_OCH_SIZE          1660    /* must match ochBlockSize in the .ini; +8 (1652..1659 trouble-code masks: stored, active - every code, not four slots); +16 (1636..1651 proposed bias axis); +36 (1600..1635 ETB friction band: midpoint, width, spread per position); +2 (1598 dbwPwmAppliedHz: the frequency the bridge is really switching at); V99 +24 (vehicle-test telemetry 1224..1247: ETB stop decision, lambda dynamics, spark skips, event ring head); V98 +92 (1132..1135 unused, the FAST BLOCK 1136..1199, engine control 1200..1223); V97 +20 (VVT 1112..1131); V97 +96 (knock 1024..1111, OCH2 region; 1016..1023 unused); V97 +6 (wideband reason / CJ120 link 1010..1015); V97 +2 (idle timing 1008); V97 +2 (ignition correction 1006); V97 +2 (check-engine lamp 1004); V97 +12 (transient fuel 992..1003); V97 +18 (sequential state, injection width, fuel per cycle, dead time 974..991); V97 +24 (DBW terms / battery factor / pending faults / commissioning verify 950..973); V97 +78 (lam1IpUa / lam2IpUa 872..875, cam PATTERN 876..891, boost 892..905, idle 906..913, DTC 914..945, limp 946..949); V96 +8 (wideband 850..870, with V95 linkDiag 848); V79 +30 (hcio711); V86 +12 (engine preset apply, 764..775); V90 +4 (ETB calibration 776, overdwell 778); V91 +4 (control CLT 780, 782 overdwell latch); V92 +40 (tooth profile, corrections, cycle, cam 784..804; ETB cal/autotune 806..820; 822 reserved); V93 +40 (ETB procedure telemetry 822..838, wideband/boot/load 840..862) */
/* V53 grew it by 16 bytes - eight channels - for the reclaim. The store is
   erased at runtime now, and that has never happened on this ECU; a bench
   that cannot see the slice count has no way to tell a slow erase from one
   that will never converge. TGT_RAM_OCH_LIMIT is 1024, so there is room. */
/* THE READ-ONLY FORENSIC VIEW, AND ITS SIZE IS DERIVED FOR THE SAME REASON
   ITS BASE IS.

   The offset/count output command serves everything at or above TGT_OCH_SIZE
   from hc_lf_export_byte(off - TGT_OCH_SIZE), so the live-Burn record starts
   where the ordinary block ends and the window has to cover BOTH.

   IT WAS THE LITERAL 1024, and 1024 is exactly 680 + 344 - the ordinary block
   as it stood at V48 plus HC_LF_BYTES. V53 grew the block to 696 and V55 to
   722, and this number did not move, so the last 21 words of the record
   stopped being reachable at all: LF_TICK_MAX_GAP, LF_WRITER_RESULT and
   LF_IR_DROPPED - the V49 and V50 starvation and interrupt-drop evidence -
   were off the end of the window while the .ini still claimed to publish
   them. Found 2026-09-16 by reading the record off the ECU and getting the
   "HC" magic out of a channel named lfCursor.

   344 is HC_LF_BYTES. It is spelled out because hcliveforensics.h includes
   THIS file, so the dependency cannot run the other way;
   me711_v49_forensics_proof checks the two against each other. */
/* AND THE TOOTH PROFILE AFTER IT. 60 u16 per-mille tooth periods
   (hcsched_dry.c, the '!K' test) are served from the same window, right
   after the 344-byte live-Burn record, so TunerStudio's ordinary poll does
   not grow by 120 bytes for data only the vehicle logger reads. */
#define TGT_TL_EXPORT_BYTES   120u
/* AND THE BOOT HISTORY after the profile: 8-byte header + 16 records of
   10 bytes (hcio711.h HC_BH_*), raw bytes in SRAM order. */
#define TGT_BH_EXPORT_BYTES   168u
/* AND THE EVENT RING after the boot history (hcevlog711.c): a 16-byte
   header + EV_N (90) records of 10 bytes. */
#define TGT_EV_EXPORT_BYTES   916u
/* AND THE RUNTIME HEALTH RECORD after the event ring
   (system/hcrtmon711.h, 32 big-endian words). */
#define TGT_RT_EXPORT_BYTES   64u
/* AND THE RESET WITNESS after the runtime health record (hcrtmon711.c,
   64 words: 32 live, 32 of the boot before - big-endian). */
#define TGT_WT_EXPORT_BYTES   128u
#define TGT_OCH_READ_SIZE     (TGT_OCH_SIZE + 344u + TGT_TL_EXPORT_BYTES + TGT_BH_EXPORT_BYTES + TGT_EV_EXPORT_BYTES + TGT_RT_EXPORT_BYTES + TGT_WT_EXPORT_BYTES)
unsigned char HC_COLD hc_lf_export_byte(unsigned int offset);
unsigned char HC_COLD hc_och_ext_byte(unsigned int offset);
#define HCTS_TARGET_OCH_EXT_READ(offset) hc_och_ext_byte(offset)

/* V48 live-burn admission constants.  The final AM29F800B data sheet gives
   tWHWH1(max)=500 us, while the RAM writer deliberately permits a full 1000 us
   before declaring a timeout.  Protect the code's REAL maximum path, not only
   a compliant part's programming time: 1100 us covers that timed poll plus
   unlock/program writes, the 8-us settle, two final reads, SRAM entry/exit and
   IC restoration.  PEC terminal interrupts may only remain enabled when the
   remaining transfer time is beyond this complete guard. */
#define TGT_LIVE_WORD_GUARD_US      1100u
/* V49 intentionally preserves V48's admission decision for a diagnostic A/B
   replay.  This 32-us value is NOT justified by the configured target clock:
   40 MHz / (2*(0x13+1)) is 1 MHz, or 16 us per 16-bit word.  The V49 gate
   proves that discrepancy and the retained PEC/IR snapshots distinguish a
   terminal collision; changing the threshold in the same build would change
   the experiment whose failure mechanism is being measured. */
#define TGT_LIVE_PEC_WORD_FLOOR_US    32u
/* PECCn's count can have the current word in the SSC shift path already.
   V48 derived 36 from the invalid 32-us premise above.  Retained unchanged in
   V49 solely so this forensic build can identify whether it mattered. */
#define TGT_LIVE_PEC_MIN_WORDS \
    ((TGT_LIVE_WORD_GUARD_US / TGT_LIVE_PEC_WORD_FLOOR_US) + 2u)
/* 3900 -> 6000 ms, AND THE REASON IS A MEASUREMENT, NOT A PREFERENCE.
 *
 * 3900 was sized when every Burn this project had ever performed ran with the
 * engine STOPPED, because no crank signal had reached this ECU until V55. At
 * rpm 0 live_admit()'s horizon is 0xFFFF - unbounded - every window is
 * admitted and the 2060-word record commits in 2.9 s with a second to spare.
 *
 * WITH THE CRANK TURNING IT IS A DIFFERENT PROBLEM, and the bench measured it
 * on 2026-09-15 at 199 rpm on a 60-2:
 *
 *     liveAdmission   5 (DEADLINE)     livePauseReason 0
 *     liveWindowsOk   24985            liveWindowsRejected 15709
 *     liveHorizonUs   2209             liveDeadlineMs  0
 *     liveWordsCompleted 1713 of 2060
 *
 * Nothing was blocked. 61 % of windows were admitted - the rest correctly
 * refused because the crank horizon had run down - and the record simply did
 * not fit: ~440 words/s against ~710 with the engine stopped, so 2060 words
 * need about 4690 ms. The Burn reached 83 % and was failed with
 * HCNV_ERR_DEADLINE, which TunerStudio shows as `Burn page 0 failed`.
 *
 * THE PER-WINDOW SAFETY IS UNCHANGED AND IT IS WHERE THE SAFETY LIVES. Each
 * window is still admitted only inside a bounded crank horizon discounted by
 * TGT_LIVE_HORIZON_ACCEL_DIV, still refused when the horizon is under
 * TGT_LIVE_WORD_GUARD_US, and IEN is still masked for at most
 * LF_MAX_WINDOW_T7. Raising this constant grows the TOTAL budget, not the
 * exposure of any one word - and at speeds where a tooth is too short the
 * horizon rule still refuses every window, which is the correct answer.
 *
 * THE CEILING IS TUNERSTUDIO'S. blockReadTimeout is 8000 ms and the Burn's
 * reply is deferred until the commit resolves; at 6000 ms the measured reply
 * lands near 6.2 s, leaving ~1.8 s of the host's budget. That is the number
 * this may not exceed, and it is why this is 6000 and not larger. */
#define TGT_LIVE_BURN_DEADLINE_MS   6000u
/* An admitted rotating-engine window discounts the last clean 60-2 tooth by
   20 percent before subtracting elapsed T1 time.  That is deliberately far
   larger than a one-tooth combustion acceleration; it also rejects a raw
   missing-tooth interval instead of converting its three-tooth duration into
   a false horizon.  The divisor form keeps the C166 arithmetic 16-bit. */
#define TGT_LIVE_HORIZON_ACCEL_DIV      5u
/* 450/452 are the endpoint-grab verdict and its counter. THE .ini AND THIS
   CONSTANT ARE THE PAIR THAT ONCE DISAGREED BY FOUR BYTES ON REAL HARDWARE
   - V29, a frozen binary against a regenerated .ini, 368 against 372. That
   is what me711_och_contract_proof exists for: it reads the put16() calls
   out of hcmain_me711.c and refuses a .ini that does not match them. */

/* ==================================================== the clock, DERIVED ==
 *
 * fCPU is not guessed and it is not copied from the ME7.5 board. It falls out
 * of two numbers that are both in the OEM ME7.1.1 image and one formula that is in
 * the datasheet.
 *
 *   [DS] C167CR UM 11.4, ASC0 baud rate generation:
 *
 *          B_async = fCPU / (16 * (2 + S0BRS) * (S0BRL + 1))
 *
 *        S0BRS is bit 13 of S0CON. Every S0CON the OEM ME7.1.1 writes (0x80D1 at
 *        0x83AB40, 0x805C at 0x823706) has it CLEAR, so the divisor is 32.
 *
 *   [OEM ME7.1.1] S0BG = 0x77 = 119, written beside S0CON = 0x80D1 at 0x83AB44.
 *        A K-line diagnostic ECU runs KWP2000 at 10400 baud, so:
 *
 *          fCPU = 10400 * 32 * 120 = 39 936 000 Hz
 *
 *   [OEM ME7.1.1] the SECOND baud the image uses, S0BG = 0x09 at 0x823FBE, then
 *        gives 39936000 / (32 * 10) = 124 800 baud exactly - the rate this
 *        family's flash loader runs at. Two independent constants, one clock.
 *
 * 39.936 MHz also identifies the part: a plain C167CR stops at 25 MHz, and the
 * reset stub at 0x007E10 writes SYSCON2, which is an ST10 register. This is an
 * ST10-class C166 at 40 MHz, not a 20 MHz C167CR. [INF, but doubly supported]
 *
 * THE SAME DERIVATION CORRECTS THE ME7.5 TARGET. There, S0BG = 0x47 at 10400
 * gives fCPU = 23.9616 MHz, and its two MEASURED CAPCOM rates then agree with
 * the datasheet exactly: fCPU/8 = 2.995 MHz at TxI=0 (measured 2.98) and
 * fCPU/16 = 1.4976 MHz at TxI=1 (measured 1.5014). The 11.98 MHz that
 * PROJECT_STATE carried came from a stopwatch reading of the on-chip watchdog
 * and is a factor of two out.
 */
/* CORRECTED 2026-08-27 BY HARDWARE, and the correction is a factor of two.
 *
 * This file previously said 39.936 MHz, derived from the C167CR manual's
 * `B_async = fCPU / (16 * (2 + S0BRS) * (S0BRL + 1))` and its Table 15-2
 * CAPCOM prescaler of fCPU/8. Both of those are off by two for THIS silicon,
 * and the first hardware run proved it:
 *
 *   the boot block installs WDTCON = 0x0B01 - WDTIN = 1, WDTREL = 0x0B, so
 *   62720 counts of fCPU/128 - and the ECU reset every ~420 ms. 62720 counts
 *   only take 401 ms at 20 MHz. At 40 MHz they take 201 ms.
 *
 * Two further checks agree and neither is a ratio that could hide a factor of
 * two: the datasheet's own Table 13-1 row "20 MHz / WDTIN=1 / WDTREL=00H ->
 * 419.4 ms", and the ME7.5 board's measured 10.93 ms watchdog period, which is
 * Table 13-1's "12 MHz / WDTIN=0 / WDTREL=00H -> 10.92 ms".
 *
 * CORRECTED 2026-08-28, and the correction matters. The relations above were
 * wrong by a factor of two in BOTH the baud divisor and the CAPCOM prescaler,
 * so they cancelled and every check appeared to pass. The C167CR manual is
 * unambiguous on both:
 *
 *   [DS UM 11.4]  "The baud rate generator is clocked with the CPU clock
 *                  divided by 2 (fCPU/2)" and provides "a clock with 16 times
 *                  the rate of the established baud rate"
 *                  ->  baud = fCPU / (32 * (S0BRL + 1))   for S0BRS = 0
 *   [DS UM 15]    T78CON: "Timer Mode: Input Frequency = fCPU / 2^(TxI + 3)"
 *                  ->  CAPCOM base is fCPU/8, so T7 at T7I=2 is fCPU/32
 *
 * With those, FIVE independent lines of evidence agree and none of them works
 * at 19.968 MHz:
 *
 *   1. [BOM] Q5000 = 8000k on S5000 = SAK-C167CR-4RM: fOSC = 8.000 MHz, and
 *      [DS Table 6-1] the PLL offers only 1.5/2/2.5/3/4/5, /2 and x1.
 *   2. [BIN] HaniCore WRITES S0BG = 0x40 (a write, so it is the RELOAD) and
 *      S0CON = 0x80D1, whose bit 13 S0BRS = 0. 19200 baud then needs
 *      fCPU = 19200*32*65 = 39.936 MHz -> the x5 factor, 40.000 MHz, giving
 *      19231 baud (+0.16%).
 *   3. [BIN] the OEM's OTHER baud constant, S0BG = 0x77, gives 10417 baud at
 *      40 MHz - that is 10400, the ISO 9141 / KWP2000 diagnostic rate. At
 *      20 MHz it would be 5208, which is not a rate anything uses.
 *   4. [HW] the 1 ms tick matches wall-clock time: V1's banner interval was
 *      PC-timestamped at 418.5 ms and the firmware called it ~420. At 20 MHz
 *      the tick would be 2 ms and the firmware would have said ~210.
 *   5. [HW] V5 measured a 96-word SSC block at X=1 ms. At 40 MHz the SSC is
 *      fCPU/(2*(0x13+1)) = 1.000 MHz, so 1536 bits take 1.536 ms. At 20 MHz it
 *      would have been 3.07 ms and X would have read 3.
 *
 * CAL=0x028A is consistent but could never have decided it: CAL =
 * 10*32*(S0BG+1)/(8*2^T7I) = 650 with fCPU cancelled out, exactly as before.
 */
#define TGT_FCPU_HZ           40000000uL

/* [DS] C167CR UM Table 15-2: a CAPCOM timer's input is fCPU/8 at TxI = 0 and
   fCPU/(8 * 2^TxI) generally. T7I = T8I = T0I = 2 puts all three on the same
   1.248 MHz, which is what US_TO_TICKS() below assumes:

     resolution  0.80 us        wrap  52.5 ms

   The wrap matters. Every "has enough time passed" test in the shared core is
   a 16-bit T7 difference, and the longest of them is the 20 ms mid-frame
   resync in hcts_poll(). 52.5 ms leaves that a factor of two of headroom;
   T7I = 1 would have left 26 ms, which is too close to be comfortable. */
/* T7 = fCPU / 2^(T7I+3) = 40 MHz / 32 = 1.250 MHz. UNCHANGED IN EFFECT by the
   fCPU correction: the old figure said 1.248 MHz from 19.968/16, the new one
   says 1.250 MHz from 40/32, and 0.16 % apart is why every timing this
   firmware has ever produced was right even while the clock was wrong. */
#define TGT_TICKS_PER_MS_X10  12500UL       /* 1.250 MHz x 10 per ms */
#define TGT_T78CON            0x4242u       /* T7I=2,T7R / T8I=2,T8R */
#define TGT_T01CON            0x0042u       /* V26 baseline: T0 runs, T1 stopped */
#define TGT_T1CON_RUNNING     0x4200u       /* T1 internal, /32, running          */
#define TGT_TICK_RELOAD       1250u         /* T8 reload for a 1 ms tick */

#define TGT_PWM_SLOW_HZ       (TGT_FCPU_HZ / 64uL)

#define US_TO_TICKS(us)   ((unsigned int)(((unsigned long)(us) * \
                            TGT_TICKS_PER_MS_X10) / 10000UL))

/* ============================================================ ASC0 / K-line ==
 *
 * baud = fCPU / (32 * (S0BG + 1)) = 1 248 000 / (S0BG + 1). What that clock
 * can hit EXACTLY, and nothing else is exact:
 *
 *      S0BG   0x81   0x77    0x40    0x13     0x09
 *      baud   9600  10400   19200   62400   124800
 *
 * 57600 needs an ideal reload of 20.70. The nearest integer reload is 0x14:
 * 59,524 baud (+3.34%), while 0x15 gives 56,818 baud (-1.36%). The latter is
 * the production default because its error is comfortably inside ordinary
 * asynchronous UART tolerance and the user's K-line hardware is proven at
 * nominal 57600. Exact 19200 (0x40) remains a trivial diagnostic fallback.
 */
#define TGT_S0BG              0x15
#define TGT_BAUD              57600
/* reply bytes go out back to back and the K-line echo is dropped by
   count (hcts.c, "PIPELINED ECHO ACCOUNTING"). Measured V93 r2: 238.7 us per
   byte at 57600 with the per-byte echo wait, 173.6 us of wire time. */
#define TGT_TX_PIPELINE       1
/* the ECU also answers at 115200 nominal (0x0A = 113,454 baud, -1.52 %,
   the same class of error as the 57600 default's -1.36 %; TunerStudio's own
   list offers 115200) and at 124800 (0x09, exact - the KKL runs the flash
   loader at it). It boots at TGT_S0BG and follows the host on evidence
   (hcts.c, "THE LINK RATE"). */
#define TGT_S0BG_ALT          0x0A
#define TGT_S0BG_ALT2         0x09
/* THE CAR'S K-LINE IS SHARED (cluster + tester, ME711_OBD_KLINE.md): answer
   no plain byte and no error reply until a CRC-valid request has locked
   the link (hcts.c HCTS_MAY_ANSWER_NOISE). 2026-10-13. */
#define TGT_KLINE_SHARED_BUS  1
/* the VAG/KWP vehicle entry (hckwp_me711.c + comms/hckline.c): a
   5-baud 0x01 on RXD0 opens a KWP session at 10400; a HaniCore GOFAST hands
   the line to TunerStudio at 57600 or 124800. While it owns the line the
   TunerStudio parser does not see its bytes and the rate hunt holds. */
#define TGT_KWP               1
extern unsigned char far hc_kwp_rx_take(unsigned char b);
extern unsigned char far hc_kwp_active(void);
#define HCTS_TARGET_RX_TAKE(b)   hc_kwp_rx_take(b)
#define HCTS_TARGET_LINK_HOLD()  hc_kwp_active()

/* The complete K-line electrical path [BOSCH-SCH, Ein-Ausgaenge sheet]:
 *
 *     P3.10 / TXD0  (CPU pin 77)  ->  S4000 "CJ910" pin 29  TX
 *     P3.11 / RXD0  (CPU pin 78)  <-  S4000 "CJ910" pin 31  RX
 *     S4000 pin 30  RT  -- R4011 / R4010 -->  connector pin 43, net B_D_DIAK
 *
 * THERE IS NO TRANSCEIVER ENABLE TO DRIVE. The K-line transceiver is inside
 * the CJ910, which is the ECU's main power-supply ASIC: it is alive whenever
 * the ECU has power, and no CPU pin gates it. That removes a whole class of
 * first-bench failure, and it is why this target has no "kline_enable".
 *
 * The CJ910 loops TX back into RX exactly as the ME7.5 board does, so the
 * shared core's echo handling and tools/ts_kline_bridge.py both apply
 * unchanged. */
#define TGT_KLINE_ECU_PIN     43        /* connector pin, ME7.1 121-pin SKE */

/* ================================================== C167 interrupt traps ==
 *
 * [DS] C167CR UM Table 5-1, pages 5-3/5-4. The full table, and it is right -
 * every trap number the ME7.5 target measured on the bench (CC5 0x15, T8 0x3E,
 * CC23 0x37, CC28 0x3C, CC29 0x44, CC30 0x45) matches it exactly. The note in
 * PROJECT_STATE that "the standard table is wrong here" was a mis-remembered
 * table, not wrong silicon.
 *
 *   CC0..CC15   0x10..0x1F      T0 0x20  T1 0x21   T2 0x22  T3 0x23
 *   CC16..CC28  0x30..0x3C      T4 0x24  T5 0x25   T6 0x26  CR 0x27
 *   CC29 0x44   CC30 0x45       T7 0x3D  T8 0x3E   PWM 0x3F
 *   CC31 0x46                   ADC 0x28 ADE 0x29
 *   S0T 0x2A  S0R 0x2B  S0E 0x2C          S0TB 0x47
 *   SSCT 0x2D SSCR 0x2E SSCE 0x2F
 *   XP0(CAN1) 0x40  XP1 0x41  XP2 0x42  XP3(PLL/OWD) 0x43
 *
 * ------------------------------------------------------------------------
 * BUT: SEVEN TRAPS ARE NOT OURS TO CLAIM, AND THIS IS THE FINDING THAT
 * EXPLAINS A BENCH RESULT ON THE OTHER TARGET.
 *
 * Interrupts on this family are vectored TWICE. The C167's own table at flash
 * 0x000000 holds 128 `JMPS` slots; 105 of them forward to seg82:N*4 = flash
 * 0x020000 + N*4, which is the table HaniCore owns. The rest jump into the
 * Bosch boot block at flash 0x0000-0x7FFF, which HaniCore does not replace:
 *
 *   trap 0x24 T4    -> 0x000F4C     trap 0x2B S0RINT -> 0x003576
 *   trap 0x25 T5    -> 0x001AE0     trap 0x2C S0EINT -> 0x0034D6
 *   trap 0x26 T6    -> 0x00138C     trap 0x38 CC24   -> 0x003526
 *   trap 0x27 CRINT -> 0x000FB6
 *   trap 0x02 NMI / 0x04 STKOF / 0x06 STKUF / 0x0A class-B trap go to a
 *     boot-block wrapper that DOES forward to seg82 - but only while the RAM
 *     byte at 0xE2BA reads 0x88; otherwise it executes SRST.
 *   trap 0x3D T7INT forwards to seg82:0x0108, which is second-level slot 0x42
 *     and NOT slot 0x3D. A T7 handler placed on its own slot never runs.
 *
 * The boot block's S0RINT handler is three instructions - `EXTR #1 / BSET
 * S0EIR / RETI` - which hands the byte to its own S0EINT receiver. That is the
 * flash bootstrap loader, and it owns the ASC0 receive interrupt permanently.
 *
 * SO: the ASC0 receive interrupt CANNOT be used on this ECU family. The ME7.5
 * bench run on 2026-08-25 reported `s0rTrap 0, probeBad 0` - no interrupt
 * delivered anywhere, with the vector table verified correct in the image - and
 * this is why. It was not a fault to be found; it is the architecture.
 *
 * The receive register is therefore drained by a CAPCOM1 COMPARE TICK, which
 * forwards cleanly. On this target that is the primary path, not a fallback.
 * ------------------------------------------------------------------------ */
#define TGT_TRAP_CC7INT       0x17    /* serial drain tick, CAPCOM1 compare  */
#define TGT_TRAP_CC8INT       0x18    /* [OEM ME7.1.1 82:4BD4] NWDG1 / cam bank 1 */
#define TGT_TRAP_CC9INT       0x19    /* [OEM ME7.1.1 82:4C34] NWDG2 / cam bank 2 */
#define TGT_TRAP_CC15INT      0x1F    /* [OEM ME7.1.1 82:431A] KWDG / crank       */
#define TGT_DEADLINE_EXECUTOR 1
#define TGT_TRAP_CC25INT 0x39
#define TGT_ILVL_DEADLINE 11
#define TGT_GLVL_DEADLINE 1
#define TGT_RAM_DEADLINE 0x7500uL
#define TGT_RAM_DEADLINE_LIMIT 0x0100uL
#define TGT_TRAP_CC16INT      0x30    /* [OEM ME7.1.1 0x0200C0 -> 89:4C1C] knock
                                         window MF (P8.0), CAPCOM2 compare    */
/* THE PLANNER IS AN INTERRUPT LEVEL, NOT A MAIN-LOOP SERVICE.
 *
 * The crank ISR records a tooth and REQUESTS this software interrupt; the
 * planner turns the tooth into compare deadlines at its own priority, so
 * nothing in task context - telemetry, a TunerStudio reply, DBW - can delay
 * engine-event planning. The runtime audit measured 3-4.7 ms planner-free
 * gaps in task context and dropped/late events from 1000 rpm.
 *
 * It is what the OEM does: the ME7.1.1 crank ISR (82:431A) latches the
 * capture and ends with `BSET CC11IR` (82:437E), deferring tooth work to a
 * lower software-triggered level; CC26/CC27 (89:4CC8 / 82:22F6) are further
 * software task levels. HaniCore uses CAPCOM2 channel 26: its compare mode
 * stays 0 (disabled, CCM6 bits 8..11), so only software ever sets its
 * request, and trap 0x3A forwards to the application table (hctarget.h list
 * above). C167CR UM 5.x: "Modifying the Interrupt Request flag via software
 * causes the same effects as if it had been set or cleared by hardware."
 *
 * ILVL 9: below every capture (crank/cams 12) and the deadline executor
 * (11, body 13), above the 1 ms tick (8) and all task work. */
#define TGT_TRAP_PLAN         0x3A    /* CC26INT, software-triggered        */
#define TGT_ILVL_PLAN         9
#define TGT_GLVL_PLAN         0
#define TGT_PLAN_IC           CC26IC
#define TGT_PLAN_IR           CC26IR
/* THE S5500 EXCHANGE LEVEL (2026-10-13). The 2026-10-13 car reset 9 times
 * while running (long hardware reset 0x1C): the exchange was clocked by the
 * main loop, whose passes stretch under engine interrupt load, and the S5500
 * resets MAIN on frames later than ~25 ms (bench: a 20 ms main-loop hold
 * every 100 ms -> 0x1C in 0.8 s, 0 monitoring mismatches). The 1 ms tick
 * REQUESTS this software interrupt, which runs hc_asic_start_service() - the
 * OEM's 10 ms OS task, as a level. CAPCOM2 channel 27, compare mode 0 like
 * CC26: only software sets its request. ILVL 9 = the planner's level, GROUP 1:
 * the two never nest (same level), so the worst stack nest keeps the
 * planner's 168 B and the planner (group 0) is taken first when both wait. */
#define TGT_TRAP_ASICX        0x3B    /* CC27INT, software-triggered        */
#define TGT_ILVL_ASICX        9
#define TGT_GLVL_ASICX        1
#define TGT_ASICX_IC          CC27IC
#define TGT_ASICX_IR          CC27IR
/* How far past the next delivered tooth the planner publishes (hcsched_dry.c
   plan_tooth): 2500 T1 ticks = 2.0 ms, the publication allowance that covers
   the walk period and the planner level's own latency. */
#define HC_PLAN_HORIZON_TICKS 2500u
/* ...and the full per-cylinder walk runs at most this often (0.4 ms); every
   capture still advances the angle epoch. Must stay well under the horizon. */
#define HC_PLAN_PERIOD_TICKS  500u
typedef char hc_plan_period_ok[(HC_PLAN_PERIOD_TICKS * 2u < HC_PLAN_HORIZON_TICKS) ? 1 : -1];
#define TGT_TRAP_T8INT        0x3E    /* the 1 ms system tick                */
#define TGT_TRAP_SSCRINT      0x2E    /* ASIC frame complete (PEC4 exhausted) */
#define TGT_TRAP_SSCTINT      0x2D
#define TGT_TRAP_SSCEINT      0x2F
/* Declared so the shared core compiles; the probe will never find it, for the
   reason above, and being wrong costs nothing. */
#define TGT_TRAP_S0RINT       0x2B    /* [DS] and UNREACHABLE - see above    */

/* One nominal 57600 8N1 byte is 174 us. Drain four times per byte so a short
   higher-priority ASIC PEC completion cannot make ASC0 overrun. (Only for a
   build without TGT_RX_PEC.) */
#define HC_RXTICK_US          40u

/* THE K-LINE IS PEC-RECEIVED AND INTERRUPT-TRANSMITTED
   (comms/hcserial711.h). ASC0 receive -> PEC6 -> a 96-byte XRAM ring at
   0xE0A0 (linker_me711.lnp keeps every class out of it); the 1 ms tick moves
   it on. Replies stream from S0TBINT, trap 0x47 - forwarded to the
   application table (list above), unused by the OEM image (82:011C self). */
#define TGT_RX_PEC            1
#define TGT_PECRX_BUF         0xE0A0u /* the OEM's own K-line ring (0xE0A2) */
#define TGT_PECRX_SIZE        96u     /* ~4 ms of tick delay at 115200 before the count runs out */
#define TGT_TX_ASYNC          1
#define TGT_TRAP_S0TBINT      0x47
/* the tick's level, its own group: a reply byte never needs to pre-empt the
   tick (one level fewer in the nest - see TGT_ILVL_CAM) */
#define TGT_ILVL_SERIAL_TX    8
#define TGT_GLVL_SERIAL_TX    1

/* How many received bytes may wait for the main loop. A TunerStudio request is
   11 bytes, so 64 gives the loop 11 ms of slack at 57600 baud. Must be a power
   of two: head and tail wrap by masking, which is what makes them atomic
   without a critical section. */
#define HC_RXRING             64u

/* hcvec_me711.c IS THE ONE MODULE COMPILED `MOD167 MEDIUM`, and this is the
   one declaration that has to know. See linker_me711.lnp's FCODE class and
   docs/ARCHITECTURE.md: far code moves the 117 unclaimed-trap
   catch-alls out of the single 64 KiB NCODE CGROUP into segment 0x85, which is
   the sector already reserved for exactly this. The module calls NOTHING
   outside itself, so it is the cheapest possible module to move - the only
   cross-model edge in the whole image is hc_rx_store(), declared in hcts.h.
   Any target that leaves hcvec SMALL simply never defines this. */
#define HC_RX_STORE_FAR       far

/* ==================================================== interrupt priorities ==
 *
 * ILVL 14 and 15 select PEC service on this core, and on THIS target that is
 * deliberate rather than forbidden: the ASIC link is a PEC transfer and Bosch
 * drives it exactly that way [OEM ME7.1.1 0x8233A6]:
 *
 *     SSCRIC = 0x007C  ->  ILVL 15, GLVL 0  ->  PEC4, RX
 *     SSCTIC = 0x00F8  ->  ILVL 14, GLVL 0  ->  PEC0, TX, IR pre-set to start
 *
 * A PEC transfer is one stolen bus cycle, not a handler, so it starves
 * nothing. The ILVL-15 interrupt that arrives when PEC4's count reaches zero
 * IS a handler, and it is a short one.
 *
 * The ME7.5 rule - "nothing above the safety responder" - is not violated,
 * because on this ECU the safety responder IS the ASIC link. The Ueberwachungs-
 * modul here is a second C167 talking over SSC, not a pulse on P2.5: [BOSCH-PM]
 * puts P2.5 on ZDG6, the sixth ignition coil.
 */
#define TGT_ILVL_ASIC         15      /* SSC receive / PEC4 completion       */
#define TGT_ILVL_ASIC_TX      14      /* SSC transmit / PEC0                 */
#ifdef TGT_RX_PEC
/* ASC0 receive IS PEC channel 6 (15/2, the OEM's S0RIC 0x3E, hcserial711.c):
   no receive or drain-tick interrupt exists in this build. */
#define TGT_ILVL_SERIAL       15
#else
#define TGT_ILVL_SERIAL       12      /* the drain tick                      */
#endif
#define TGT_ILVL_TICK         8       /* the 1 ms system tick                */
#define TGT_ILVL_ENGINE_MAX   12      /* ceiling for anything added later    */
#define TGT_ILVL_CRANK        12
#define TGT_ILVL_ANGLE        11
/* the cams share the crank's level (distinct GLVL 2/1): a cam
   capture never needs to pre-empt the crank or vice versa (each handler is
   tens of us and its capture register holds the edge), and every distinct
   level is one more frame in the worst-case interrupt nest on the system
   stack (tools/analysis/me711_stack_static.py). */
#define TGT_ILVL_CAM          12
/* the knock measurement window (CAPCOM2 CC16 compare on T7 -> MF on
   P8.0, hcknock711.c). Its own (ILVL, GLVL): 11/0 - nothing else is enabled
   at 11 (TGT_ILVL_ANGLE is declared and unused). Below the crank and the
   serial drain on purpose: a 25 us drain handler moves a window edge by
   < 1 crank degree at 6000 rpm, a lost drain slot costs a K-line byte. */
#define TGT_ILVL_KNOCK        11
#define TGT_GLVL_KNOCK         0

/* V83. THE CONFIGURATION APPLY'S CRITICAL SECTION RAISES THE CPU TO THIS LEVEL
 * INSTEAD OF CLEARING IEN.
 *
 * IEN = 0 "globally enables or disables PEC operation" [C167CR UM V3.1 5.x],
 * and the S5500 frame is moved by PEC0/PEC4 at 16 us per 16-bit word. The
 * apply copied each field with IEN = 0 through far thunks: 430 instructions
 * (~43 us) for the 12-byte injector/coil pin maps, measured in c167sim on V82.
 * Any IEN = 0 window longer than one word time while a frame is on the wire
 * lets a second word land on an unread SSCRB - a Receive Error, "the old data
 * ... is unretrievably lost" [UM 12.x] - so PEC4 never reaches zero and the
 * frame times out. That is V81/V82's residual ~0.3 asicTimeouts per routing
 * write, and why c167sim (whose S5500 completes inside the kicking write)
 * never reproduced it.
 *
 * 13 is above every source that reads the page (TGT_ILVL_ENGINE_MAX = 12:
 * crank, serial drain, angle, cam, tick) and below the two PEC levels, so a
 * field still cannot be torn and the S5500 transfer keeps running. */
#define TGT_ILVL_CFG_CRIT     13

/* ============================ AND THE GROUP LEVEL IS NOT DECORATION =========
 *
 * TWO ENABLED SOURCES AT THE SAME ILVL MUST NOT SHARE A GLVL. The ME7.5
 * target's own header has said so since it was written - "GLVL 2 keeps it
 * distinct from CC15's 12/3, so simultaneous requests still arbitrate
 * deterministically" - and the ME7.1.1 port lost the distinction: the drain
 * tick was CC7IC = 12/2 and the crank capture was CC15IC = 12/2.
 *
 * MEASURED ON THE ECU, 2026-09-16, V57, with NO Burn running at all - the
 * drain tick's own rate, taken over a window short enough that the 16-bit
 * rx_ticks counter cannot lap:
 *
 *     generator OFF, capture ON     25003 ticks/s   period 40.0 us   hwOvr 0
 *     200 rpm,       capture ON     20510 ticks/s   period 48.8 us   hwOvr 46
 *     200 rpm,       capture OFF    24996 ticks/s   period 40.0 us   hwOvr 0
 *
 * The middle two rows have the SAME signal on the SAME wire and differ only
 * in whether CC15's capture interrupt is enabled. Eighteen per cent of the
 * drain's 40 us slots disappear, the ASC0 receive register overruns, and the
 * K-line loses about three per cent of the bytes it is sent - which then
 * costs `echo_seen`, floods the 64-byte ring and loses whole requests.
 *
 *
 * THE CRANK KEEPS THE HIGHER GROUP, as it does on ME7.5. Equal ILVL does not
 * preempt on this core, so the loser of the tie waits exactly one handler -
 * the crank's is a measured 32 T1 ticks, 25.6 us - which is well inside a
 * 174 us byte at 57600 baud in either direction. What the tie must not be is
 * UNDEFINED. */
#define TGT_GLVL_SERIAL        2      /* CC7 drain tick / ASC0 receive       */
#define TGT_GLVL_CRANK         3      /* CC15 capture - distinct from it     */

/* THE GROUP LEVEL FOLLOWS THE CAPTURE ROLE, NOT THE CHANNEL - V62.
 *
 * Until V62 the crank was always CC15 and the cams always CC8/CC9, so a group
 * level per CHANNEL and per ROLE were the same thing. They are not any more:
 * the page decides which channel carries which role, so the (ILVL, GLVL) pair
 * has to travel with the ROLE or two channels can end up sharing one.
 *
 * Exactly one channel holds each role at a time, so three DISTINCT pairs make
 * a collision impossible whatever the page routes:
 *
 *     crank   TGT_ILVL_CRANK 12 / TGT_GLVL_CRANK 3
 *     cam 1   TGT_ILVL_CAM   12 / TGT_GLVL_CAM1  2   
 *     cam 2   TGT_ILVL_CAM   12 / TGT_GLVL_CAM2  1
 *
 * THE CRANK SHARES ILVL 12 WITH THE SERIAL DRAIN, so its GLVL must differ
 * from TGT_GLVL_SERIAL. That is the V57 defect - measured as eighteen per cent
 * of the K-line's 40 us drain slots lost whenever the crank turned - and
 * me711_irq_priority_proof reproduces it by forcing these two equal. */
#define TGT_GLVL_CAM1          2      /* cam 1 capture, whichever channel    */
#define TGT_GLVL_CAM2          1      /* cam 2 capture, whichever channel    */

#define HC_IC(ilvl, glvl)     ((unsigned int)(0x40u | ((ilvl) << 2) | (glvl)))

/* ===================================================== external memory map ==
 *
 * [OEM ME7.1.1] the second-stage application entry at 0x8C09B8 writes
 * ADDRSEL1 = 0x3803 / BUSCON1 = 0x040D: region at 0x380000, RGSZ 3 = 32 KB.
 * [BOSCH-SCH] the part is a TC55257 32K x 8 on CS1/P6.1, and its VDD comes from
 * VSTBY - BATTERY BACKED, exactly like the ME7.5 board, which is what makes a
 * TunerStudio burn meaningful before flash persistence exists.
 * The A1104F A2L declares the same window as external RAM. Three sources.
 */
#define TGT_EXTRAM_BASE       0x380000uL
#define TGT_EXTRAM_SIZE       0x8000uL

/* The map of that 32 KB. EVERY user takes its address from here - on the ME7.5
   target two files each picked a "clearly free" offset, they collided, and the
   reset log was being overwritten by telemetry several hundred times a second.
   One place, once. */
#define TGT_RAM_CFG           0x0000uL    /* header + the calibration page   */
#define TGT_RAM_CFG_LIMIT     0x1180uL    /* page + probe end at 0x110D;
                                             OCH2 follows at 0x1180 */
/* THE UNUSED TAIL OF THE CALIBRATION REGION, 0x1800..0x1FFF - nothing
   ever read or wrote it (hcconfig.c's #error bounds the page + probe +
   persistence flag at 0x110D).
   OCH2: output channels at offsets 1024.. (the 1 KB OCH region is full);
   hcts.c serves an offset >= TGT_OCH_SPLIT from here.
   KNOCK: the knock driver + strategy state (hcknock711.c, far).
   VVT: the cam-phaser control state (hcvvt711.c, far). */
/* THE ENGINE EVENT RING (hcevlog711.c): transitions of sync, cuts,
   overdwell, the ETB procedures, lambda and the link, timestamped and
   sequence-numbered, battery-backed like the page it follows. */
#define TGT_RAM_EVLOG         0x1400uL
#define TGT_RAM_EVLOG_LIMIT   0x0400uL
#define TGT_RAM_ETBBIAS       0x1800uL
#define TGT_RAM_ETBBIAS_LIMIT 0x0200uL
#define TGT_RAM_OCH2          0x1180uL
#define TGT_RAM_OCH2_LIMIT    0x0280uL
#define TGT_OCH_SPLIT         1024u
#if (TGT_OCH_SIZE - TGT_OCH_SPLIT) > TGT_RAM_OCH2_LIMIT
#error "output-channel tail exceeds OCH2 SRAM"
#endif
#define TGT_RAM_KNOCK         0x1A00uL
#define TGT_RAM_KNOCK_LIMIT   0x0200uL
#define TGT_RAM_VVT           0x1C00uL
#define TGT_RAM_VVT_LIMIT     0x0100uL
/* the trouble-code state (hcdtc711.c) - out of the far XRAM, which
   the knock/VVT/wideband additions filled */
#define TGT_RAM_DTC           0x1D00uL
#define TGT_RAM_DTC_LIMIT     0x0100uL
/* the engine-control layer's state (hcengctl711.c, far): DFCO,
   closed loop, motorsport, priming - and the priming key-cycle counter,
   which must survive a power cycle like rusEFI's backup-RAM copy. */
#define TGT_RAM_ENGCTL        0x1E00uL
#define TGT_RAM_ENGCTL_LIMIT  0x0100uL
#define TGT_RAM_LOAD          0x1F00uL
#define TGT_RAM_LOAD_LIMIT    0x0100uL
#if ((TGT_RAM_ENGCTL + TGT_RAM_ENGCTL_LIMIT) > TGT_RAM_LOAD) || ((TGT_RAM_LOAD + TGT_RAM_LOAD_LIMIT) > 0x2000uL)
#error "load state overlaps calibration-tail SRAM"
#endif
#if ((TGT_RAM_CFG + TGT_RAM_CFG_LIMIT) > TGT_RAM_OCH2)     || ((TGT_RAM_OCH2 + TGT_RAM_OCH2_LIMIT) > TGT_RAM_EVLOG)     || ((TGT_RAM_EVLOG + TGT_RAM_EVLOG_LIMIT) > TGT_RAM_ETBBIAS) || ((TGT_RAM_ETBBIAS + TGT_RAM_ETBBIAS_LIMIT) > TGT_RAM_KNOCK)     || ((TGT_RAM_KNOCK + TGT_RAM_KNOCK_LIMIT) > TGT_RAM_VVT)     || ((TGT_RAM_VVT + TGT_RAM_VVT_LIMIT) > TGT_RAM_DTC)     || ((TGT_RAM_DTC + TGT_RAM_DTC_LIMIT) > TGT_RAM_ENGCTL)     || ((TGT_RAM_ENGCTL + TGT_RAM_ENGCTL_LIMIT) > 0x2000uL)
#error "the calibration-tail SRAM regions overlap"
#endif
#define TGT_RAM_OCH           0x2000uL    /* TunerStudio output channels     */
#define TGT_RAM_OCH_LIMIT     0x0400uL
#define TGT_RAM_RSTLOG        0x2400uL    /* the reset log                   */
#define TGT_RAM_RSTLOG_LIMIT  0x0100uL
#define TGT_RAM_ASICLOG       0x2500uL    /* last accepted ASIC frames       */
#define TGT_RAM_ASICLOG_LIMIT 0x0300uL
#define TGT_RAM_FLASHBUF      0x3000uL
#define TGT_RAM_FLASHBUF_LIMIT 0x1400uL    /* was 0x2000; the Burn
                                              record is ~0x1018 (hcnvm.c
                                              checks REC_LEN against this) -
                                              the top 3 KB is the preset undo
                                              log, TGT_RAM_PRESETUNDO */
/* The NMI post-mortem. Its own region on purpose: hcconfig's reset log is
   SHARED with the 4B0906018DC, and a Bosch-only snapshot must not push that
   layout around. See feedback_one_place_for_shared_layout - every SRAM region
   this target owns is declared here and nowhere else. NOT USED BY V2. */
/* The A/B condition cell for RESETDIAG_V3. ONE byte pair, deliberately not
   inside the reset log: the STARTUP has to read it before EINIT, in assembly,
   and parsing hcconfig's 32-bit magic there would be a second implementation
   of a shared format. Instead C writes the NEXT boot's condition here and the
   startup only has to compare two bytes.
        +0  marker 0xA5   (anything else -> treat as BASE)
        +1  condition     0 = BASE, 1 = NLEN
   start_me711.a66 hardcodes 0x2900/0x2901 because A166 cannot read a C
   header - tools/me711_wdt_audit.py checks the emitted bytes against these
   values so the two cannot drift apart silently, which is exactly how the
   WDTCON mismatch happened. */
#define TGT_RAM_ABFLAG        0x2900uL
#define TGT_RAM_ABFLAG_LIMIT  0x0100uL
#define TGT_ABFLAG_MARKER     0xA5u
#define TGT_AB_BASE           0u
#define TGT_AB_NLEN           1u

/* The frozen ASIC reply capture. ITS OWN REGION, and that is the whole point.
   V6 and V7 both put it at TGT_RAM_ASICLOG, which hcasic.c's RXSNAP already
   owned - and asic_init() zeroes 118 words of RXSNAP on every boot and every
   SSC re-initialisation. That wiped the capture's D_VALID, D_CALC and D_RECV
   (words 1, 6, 7) and its whole payload, while leaving G_MAGIC at word 224
   outside the cleared range - so hc_asicdump_init() saw a valid magic, never
   re-initialised, and the "frozen" frame was silently re-captured on every
   single boot. Chunks printed across boots therefore came from DIFFERENT
   exchanges, and the metadata from a different one again.
   This is exactly what feedback_one_place_for_shared_layout exists to stop:
   two modules hardcoding the same base. Every region this target owns is
   declared HERE and nowhere else. */
#define TGT_RAM_ASICDUMP      0x2A00uL
#define TGT_RAM_ASICDUMP_LIMIT 0x0600uL

#define TGT_RAM_NMISNAP       0x2800uL
#define TGT_RAM_NMISNAP_LIMIT 0x0100uL

/* The HAL output-request census and the S5500 correlation window. In the
   EXTERNAL SRAM for the same measured reason as the ME7.5 board: near RAM here
   is 1792 bytes and the engine layer has to fit in it. 0x7000 is clear of
   every region above - FLASHRT ends at 0x6800 and the chip is 32 KB. */
#define TGT_RAM_HALCENSUS     0x7000uL
#define TGT_RAM_HALCENSUS_LIMIT 0x0100uL
#define TGT_RAM_S5500WIN      0x7100uL
#define TGT_RAM_S5500WIN_LIMIT 0x0100uL

/* The closed-loop throttle's state. OUT OF NEAR RAM, for the reason
   PROJECT_STATE records twice already: near RAM here is 1792 bytes and
   near_ram_hazard_proof reported 153 free - under its 192-byte reserve -
   the moment hc_dbw.c landed. The controller runs on a 5 ms raster and is
   not the tooth path, so its state is cold by this project's own
   definition. 0x7200 is clear of every region above and the chip is
   32 KB. 0x7200 is SCHEDPLAN - near_ram_hazard_proof caught that
   collision the moment it was written, which is what one declared map is
   for. */
#define TGT_RAM_DBW           0x7300uL
#define TGT_RAM_DBW_LIMIT     0x0080uL
#define TGT_RAM_TPS_HISTORY   (TGT_RAM_DBW + 0x80uL)
#define TGT_RAM_TPS_HISTORY_LIMIT 0x0080uL

/* THE RESOLVED I/O ROUTE TABLE - the configured cavity, turned into hardware.
 *
 * V62 inverts the binding hc_route.h deliberately left alone: hc_hal_ain() now
 * reads the ADC channel the CONFIGURED CAVITY resolves to, and the crank/cam
 * captures are armed on the channel their configured cavity resolves to,
 * instead of on a compile-time table. That needs somewhere to keep the
 * resolution.
 *
 * IT IS OUT HERE AND NOT IN NEAR RAM ON PURPOSE. near_ram_hazard_proof reports
 * 129 bytes free against a 192-byte engineering reserve and already fails on
 * it; spending twenty more bytes of near data to make routing real would be
 * taking the honest number and making it worse to pay for a feature that does
 * not need the speed. Nothing here is on the tooth path - the table is READ by
 * hc_hal_ain(), which eng_service() calls a handful of times per cycle, and
 * WRITTEN only when the configuration moves. */
/* The capture channels this board has, as opaque ids. Shared code compares
   them; only hctrig_me711.c knows which CAPCOM register each one is. */
#define TGT_CAPCH_CC15        0u    /* P2.15, KWDG  - the CJ910 crank path */
#define TGT_CAPCH_CC8         1u    /* P2.8,  NWDG1 - cam 1, logic level   */
#define TGT_CAPCH_CC9         2u    /* P2.9,  NWDG2 - cam 2, logic level   */
#define TGT_CAPCH_COUNT       3u

#define TGT_RAM_ROUTE         0x7400uL
#define TGT_RAM_ROUTE_LIMIT   0x0100uL
/* MAIN acquisition metadata shares the route region after its 16 bindings.
   Per channel: acquisition-start timestamp and sequence. */
#define TGT_RAM_ADC_META      (TGT_RAM_ROUTE + 0x20uL)
#define TGT_ADC_FRESH_MS       100u
#define TGT_ASIC_FRESH_MS       50u
#define TGT_RAM_CJ_ACQ        (TGT_RAM_ROUTE + 0x80uL)

/* The angle scheduler's EVENT QUEUE, out of near RAM. V63.
 *
 * 160 bytes: ev_deadline/ev_origin/ev_angle/ev_period as u16[16] and
 * ev_type/ev_slot as u8[16]. It is the single largest movable block in the
 * largest near-RAM segment (?ND0?HCSCHED_DRY, 412 bytes of 1626).
 *
 * WHY THIS ONE AND NOT THE CAPTURE RING. cap_angle/cap_stamp/cap_dt are the
 * only part of this module the CRANK ISR touches - hc_drysched_tooth() does
 * nothing but push three words into that ring, and the ring is drained in the
 * main loop. Everything that reads ev_* - plan_tooth(), advance_angle_epoch(),
 * hc_drysched_time_service() - is TASK context. So this relocation costs
 * main-loop cycles and NOT per-tooth interrupt latency, and the 48-byte ring
 * stays where it is.
 *
 * MEASURED: near RAM had 125 bytes free against near_ram_hazard_proof's
 * 192-byte engineering reserve, i.e. 67 short, with a hard floor of 64 that
 * was never breached. Moving these 160 bytes clears the reserve with margin
 * instead of lowering it. */
/* the unused SCHEDEV reservation is now TGT_RAM_DEADLINE diagnostics.
   Interrupt-visible queue and owner data remain in internal near RAM. */

/* The angle scheduler's LONG-HORIZON staging table, out of near RAM.
 *
 * NOT the tooth path. plan_epoch/plan_type/plan_slot hold events staged more
 * than one tooth ahead - the interface the eventual ignition and injection
 * planners use - and stage_long_horizon() returns immediately when none is
 * staged. So the far access is paid only when something is actually pending,
 * while the 96 bytes were being paid always.
 *
 * MEASURED, not stylistic: near RAM on this target is 1504 bytes and after
 * the pre-resolved cycle plan and the bench qualifier it had 97 free against
 * near_ram_hazard_proof's 192-byte engineering reserve for the engine
 * subsystems still to come. PROJECT_STATE's standing instruction after the
 * last overflow is to move data OUT rather than shrink the user stack. */
#define TGT_RAM_SCHEDPLAN     0x7200uL
#define TGT_RAM_SCHEDPLAN_LIMIT 0x0100uL

/* The DESIRED configuration image, 4 KB - the whole TunerStudio page again.
 *
 * WHY IT EXISTS. TunerStudio writes must not reach a running engine byte by
 * byte. A tuner who changes an injector routing from A to B to C to D while
 * the engine turns must have the engine keep running A, and must get D - not
 * B then C then D - the moment it stops. That needs two images: this one, which
 * the host reads and writes, and the ACTIVE page, which the runtime reads.
 *
 * hc_config_manager.c owns it. LIVE_APPLY fields are written to both images at
 * once; RPM_ZERO_APPLY fields land only here until RPM reaches zero, when the
 * whole dirty apply group is validated and copied across in one pass;
 * RESTART_REQUIRED fields are never copied across at all and reach the runtime
 * only through persistence and the next boot.
 *
 * 0x5000 is clear of every region above: FLASHBUF ends at 0x4FFF and FLASHRT
 * starts at 0x6000. One place, once - see feedback_one_place_for_shared_layout.
 */
#define TGT_RAM_CFGDESIRED    0x5000uL
#define TGT_RAM_CFGDESIRED_LIMIT 0x1000uL

#define TGT_RAM_FLASHRT       0x6000uL
#define TGT_RAM_FLASHRT_LIMIT 0x0800uL

/* The nonvolatile-store control block: 32 bytes of it, in its own 256-byte
   region because it has to be read and written by BOTH ordinary C and the
   RAM-resident flash programmer, and it has to SURVIVE A RESET.

   Surviving a reset is the whole design. On this board the S5500 monitoring
   module can assert SWRST_SM while the flash is busy - an AM29F800 sector
   erase is ~0.7 s and a silent CPU is reset in ~310-420 ms - so the commit is
   built to be RESTARTED rather than to beat the clock. What tells the next
   boot that a commit was in progress, which slot it was writing and how many
   attempts it has already had, is this block. It is in the battery-backed
   TC55257, so it survives the reset it is designed for and it forgets when
   the battery does, which is exactly the right lifetime for it.

   0x6800 is clear of every region above: FLASHRT ends at 0x67FF and
   HALCENSUS starts at 0x7000. One place, once - see
   feedback_one_place_for_shared_layout. */
/* the engine-preset transaction's undo log (hc_config_manager.c,
   hc_cfg_mgr_txn_*): three bytes per staged byte. V89: 0x0A00 = 853 entries,
   to the top of the SRAM - the 1.8T preset stages ~630 bytes once it carries
   its VE table. Nothing else lives above 0x7600. */
/* 0x0C00 at 0x4400, the unused top of TGT_RAM_FLASHBUF. The u16 VE
   table took the AWT preset to 2284 staged bytes in 41 runs (~2.6 KB of
   log with its index) - past the old 0x0A00 at 0x7600, and '!E' refused
   the preset (me711_v98_engine_proof). */
#define TGT_RAM_PRESETUNDO       0x4400uL
#define TGT_RAM_PRESETUNDO_LIMIT 0x0C00uL
#if ((TGT_RAM_FLASHBUF + TGT_RAM_FLASHBUF_LIMIT) > TGT_RAM_PRESETUNDO)     || ((TGT_RAM_PRESETUNDO + TGT_RAM_PRESETUNDO_LIMIT) > TGT_RAM_CFGDESIRED)
#error "preset undo log overlaps the Burn buffer or DESIRED"
#endif
/* the TunerStudio tooth / composite logger buffer, 200 records x 8
   bytes (rusEFI composite_logger_s, big-endian on the wire). It shared the
   undo log's region until V98r2; it has 0x7600.. to itself now. */
#define TGT_RAM_TLOG             0x7600uL
#define TGT_RAM_TLOG_LIMIT       0x0A00uL
#define TGT_TLOG_N               200u
#if (TGT_TLOG_N * 8u) > TGT_RAM_TLOG_LIMIT
#error "the tooth log does not fit its region"
#endif
unsigned int  hc_tlog_cmd(unsigned char sub);     /* hctrig_me711.c */
extern unsigned char hc_tlog_on;                  /* 0 off, 1 composite, 2 tooth */
extern unsigned int  hc_tlog_n;                   /* records in the buffer      */
unsigned char hc_tlog_byte(unsigned int i);
#define HCTS_TARGET_LOGGER(sub)   hc_tlog_cmd(sub)
#define HCTS_TARGET_TLOG_BYTE(i)  hc_tlog_byte(i)
#if ((TGT_RAM_TLOG + TGT_RAM_TLOG_LIMIT) > TGT_EXTRAM_SIZE)
#error "the tooth log runs off the external SRAM"
#endif
#define TGT_RAM_NVM           0x6800uL
#define TGT_RAM_NVM_LIMIT     0x0100uL
/* V49's first-event live-Burn forensic record.  Native aligned word stores
   keep the writer/NMI paths short; the TunerStudio export converts the fixed
   344-byte record to the target protocol's big-endian byte order. */
#define TGT_RAM_LIVEFORENSICS       0x6900uL
#define TGT_RAM_LIVEFORENSICS_LIMIT 0x0158uL
/* The phase offsets in force for the four cursor kinds (the close kind is
   unused): hc_deadline_plan_offset() holds a live timing change back while
   the next event is inside the publication horizon. */
#define TGT_RAM_PLANOFF       0x6A58uL
#define TGT_RAM_PLANOFF_LIMIT 0x0008uL
/* hc_validation.c's claim list (scratch, 146 B), kept out of XRAM. */
#define TGT_RAM_VALCLAIMS           0x6A60uL
#define TGT_RAM_VALCLAIMS_LIMIT     0x00A0uL
/* the tooth-period profile (hcsched_dry.c): 60 u32 sums, 60 u16
   counts, 60 u16 published per-mille values. 480 of 512 bytes. Written only
   in task context while a '!K' profile is being taken. */
#define TGT_RAM_TOOTHLOG            0x6B00uL
#define TGT_RAM_TOOTHLOG_LIMIT      0x0200uL
/* the ETB endpoint calibration / PID autotune state (hcetbcal.c, far
   code). Cold: written only while a procedure runs. */
#define TGT_RAM_ETBCAL              0x6D00uL
#define TGT_RAM_ETBCAL_LIMIT        0x0100uL
/* the BOOT HISTORY - one record per boot (raw reset cause, KL15 at
   boot, how long the previous boot lived, what run-on was doing when it
   ended, the lowest battery it saw), a ring the vehicle logger reads after
   a key-off. Battery-backed like the rest of this chip, so a reset storm
   around key-off leaves its own trail. */
#define TGT_RAM_BOOTHIST            0x6E00uL
#define TGT_RAM_BOOTHIST_LIMIT      0x0100uL
/* the transient-fuel state (hctrans711.c, far): the wall film, the
   after-start clock, its T1 time base. The on-chip XRAM that holds the far
   modules' data is full. */
#define TGT_RAM_TRANS               0x6F00uL
#define TGT_RAM_TRANS_LIMIT         0x0040uL
#if ((TGT_RAM_BOOTHIST + TGT_RAM_BOOTHIST_LIMIT) > TGT_RAM_TRANS)
#error "boot-history and transient-fuel SRAM regions overlap"
#endif
/* the check-engine lamp policy (diagnostics/hccel.c via hcdtc711.c) */
#define TGT_RAM_CEL                 0x6F40uL
#define TGT_RAM_CEL_LIMIT           0x0010uL
#if ((TGT_RAM_TRANS + TGT_RAM_TRANS_LIMIT) > TGT_RAM_CEL)
#error "transient-fuel and lamp SRAM regions overlap"
#endif
/* the idle ignition-timing state (control/hcidle.c via hcidle711.c) */
#define TGT_RAM_IGNIDLE             0x6F50uL
#define TGT_RAM_IGNIDLE_LIMIT       0x0010uL
#if ((TGT_RAM_CEL + TGT_RAM_CEL_LIMIT) > TGT_RAM_IGNIDLE)
#error "lamp and idle-timing SRAM regions overlap"
#endif
/* the tacho output state (hal/hcroutes711.c, 2026-10-11) */
#define TGT_RAM_TACHO               0x6F60uL
#define TGT_RAM_TACHO_LIMIT         0x0010uL
#if ((TGT_RAM_IGNIDLE + TGT_RAM_IGNIDLE_LIMIT) > TGT_RAM_TACHO)
#error "idle-timing and tacho SRAM regions overlap"
#endif
/* the Burn owed since the engine ran (hc_config_manager.c, 2026-10-11) */
#define TGT_RAM_BURNDEFER           0x6F70uL
#define TGT_RAM_BURNDEFER_LIMIT     0x0008uL   /* 6 used; 0x10 until 2026-10-13 */
#if ((TGT_RAM_TACHO + TGT_RAM_TACHO_LIMIT) > TGT_RAM_BURNDEFER)
#error "tacho and Burn-defer SRAM regions overlap"
#endif
/* THE RESET WITNESS (hcrtmon711.c, 2026-10-11): what the ECU saw last
   before a reset - 32 words live, 32 words copied at the next boot. The car
   reset with the engine running (long hardware reset, KL15 on, 14 V) and
   nothing said why; IRAM is zeroed by the startup, this SRAM is not. */
#define TGT_RAM_RSTWIT              0x6F80uL
#define TGT_RAM_RSTWIT_LIMIT        0x0080uL
/* THE SHARED-BUS K-LINE ENTRY (hckwp_me711.c, 2026-10-13): the ISO 14230
   fast-init wake-up detector and the GOFAST proof timer - 8 bytes the far
   modules' XRAM no longer has (docs/ARCHITECTURE.md). */
#define TGT_RAM_KLINE               0x6F78uL
#define TGT_RAM_KLINE_LIMIT         0x0008uL
#if ((TGT_RAM_BURNDEFER + TGT_RAM_BURNDEFER_LIMIT) > TGT_RAM_KLINE)
#error "Burn-defer and K-line SRAM regions overlap"
#endif
#if ((TGT_RAM_KLINE + TGT_RAM_KLINE_LIMIT) > TGT_RAM_RSTWIT)
#error "K-line and reset-witness SRAM regions overlap"
#endif
#if ((TGT_RAM_RSTWIT + TGT_RAM_RSTWIT_LIMIT) > TGT_RAM_HALCENSUS)
#error "reset-witness and HAL-census SRAM regions overlap"
#endif
/* THE TACHO OUTPUT (2026-10-11). Cavity 37 A_T_TN <- CJ920 S6500 IN 39
   "TN_P213" -> OUT 38, pulled up to UBR by R6540..R6542 (the ME7.1.1 schematic p1, the
   Audi W12 ME7.1.1: SAME-GENERATION BOSCH SCHEMATIC); main CPU P2.13 /
   CC13IO = "TN, tN-Signal (Drehzahlausgang)" in BOTH ME7.1.1 columns of the
   Bosch port map (tools/config_source/data/me711_iomap.csv: SAME-FAMILY);
   rusEFI hellen121vag (the VAG 121-pin harness): cavity 37 = "Tach Out",
   low side (SOFTWARE REFERENCE). Polarity ACTIVE LOW by INFERENCE: the same
   CJ920 drives the fuel pump from P2.12, MEASURED active LOW on this ECU
   (V76). A square wave's frequency does not depend on it; the RESTING state
   does, and resting is a released pin (stage off, line at UBR). NOT
   physically qualified: a logic analyser on cavity 37 is the bench test. */
#define TGT_TACHO_CAV               37u
#define TGT_TACHO_BIT               13u
#define TGT_TACHO_ACTIVE_HIGH       0
#if ((TGT_RAM_IGNIDLE + TGT_RAM_IGNIDLE_LIMIT) > TGT_RAM_HALCENSUS)
#error "idle-timing and HAL-census SRAM regions overlap"
#endif
#if ((TGT_RAM_TOOTHLOG + TGT_RAM_TOOTHLOG_LIMIT) > TGT_RAM_ETBCAL)
#error "tooth-log and ETB-calibration SRAM regions overlap"
#endif
#if ((TGT_RAM_LIVEFORENSICS + TGT_RAM_LIVEFORENSICS_LIMIT) > TGT_RAM_VALCLAIMS) || ((TGT_RAM_VALCLAIMS + TGT_RAM_VALCLAIMS_LIMIT) > TGT_RAM_TOOTHLOG)
#error "TGT_RAM_VALCLAIMS overlaps its neighbours"
#endif
#if ((TGT_RAM_BOOTHIST + TGT_RAM_BOOTHIST_LIMIT) > TGT_RAM_HALCENSUS)
#error "boot-history and HAL-census SRAM regions overlap"
#endif
/* the ETB calibration and autotune are the far module hcetbcal.c. */
#define TGT_ETBCAL_FAR              1
/* Set only for the frozen characterization bench image. */
#define TGT_ETB_DIAGNOSTIC_BENCH    0
#if ((TGT_RAM_NVM + TGT_RAM_NVM_LIMIT) > TGT_RAM_LIVEFORENSICS)
#error "NVM and live-forensic SRAM regions overlap"
#endif
#if ((TGT_RAM_LIVEFORENSICS + TGT_RAM_LIVEFORENSICS_LIMIT) > TGT_RAM_HALCENSUS)
#error "live-forensic and HAL-census SRAM regions overlap"
#endif
/* V47 has no retained V45 Burn diary alias in this region.  Architecture-D
   live telemetry is transient at NVM_LIVE and reset/NMI diagnostics retain
   their independently bounded regions; leaving a dead sub-region declaration
   here would make the SRAM-map proof certify an object with no owner. */

/* --------------------------------------------- segment-0 RAM, and why ----
 *
 * The PEC's source and destination pointers are 16 bits, so an ASIC frame
 * buffer must live in segment 0. What in segment 0 is really RAM is not a
 * guess: the boot block TESTS it and executes SRST if it fails, walking
 *
 *     0x00FDFA down to 0x00F200      [OEM ME7.1.1 0x7788-0x7810]
 *     0x00E7FE down to 0x00E000      [OEM ME7.1.1 0x77D6-0x7814]
 *
 * The upper block is where Keil's near data and the system stack go. The lower
 * 2 KB is XRAM (SYSCON.XPEN is set in both the 0xE244 and 0xE644 the startup
 * writes) and nothing else in this firmware wants it, so the ASIC frame lives
 * there.
 *
 * The OEM put its frame at 0xD33E. That is a Bosch SOFTWARE CHOICE and not a
 * hardware requirement - the transfer primitive at 0x8233A6 takes the buffer
 * address in R13 and would work with any segment-0 address - so HaniCore owns
 * its own instead, which is what stops a removed OEM layout from reaching into
 * a HaniCore image. */
#define TGT_XRAM_BASE         0xE000u
#define TGT_XRAM_SIZE         0x0800u
#define TGT_ASIC_FRAME        0xE100u     /* 236 bytes, in-place TX and RX   */
#define TGT_ASIC_FRAME_MAX    236u

/* --------------------------------------------------- the program flash ----
 *
 * [A1104F A2L] and [OEM ME7.1.1]: 1 MB at 0x800000-0x8FFFFF. AMD 29F800-class,
 * word mode, CS0/P6.0 [BOSCH-PM]. File offset X is CPU address 0x800000 + X.
 *
 * Sector layout of a 29F800BB (bottom boot): SA0 16 KB, SA1/SA2 8 KB, SA3
 * 32 KB, SA4..SA18 64 KB each. HaniCore's own layout is designed AROUND those
 * boundaries - see build/generated/me711_hanicore_clean_flash_map.csv.
 */
#define TGT_FLASH_WINDOW      0x800000uL
#define TGT_FLASH_UNLOCK1     0x800AAAuL
#define TGT_FLASH_UNLOCK2     0x800554uL
#define TGT_FLASH_CAL_SECTOR  0x8F0000uL   /* SA18, the last 64 KB, no code  */
#define TGT_FLASH_CAL_AT      0x8F0004uL
#define TGT_FLASH_PAGE        0x2000uL
#define TGT_FLASH_SECTOR_SIZE 0x10000uL

/* -------------------------------- the APPEND-ONLY calibration record ----
 *
 * SA7 and SA8. Not a free choice - docs/PLATFORM.md reserved
 * exactly these two sectors for persistent configuration before any of it
 * existed, and reserved 0x020200-0x03FFFF for a resident update loader that
 * must stay reachable when the application sector is erased. Persistent
 * configuration therefore starts at 0x040000 and not one byte lower.
 *
 * =========================================================================
 * RETRACTED, 2026-09-06, BY THE ECU ITSELF. The text that stood here said:
 *
 *     "THE BOOTROM DOES NOT CHECKSUM THESE SECTORS, and that is not an
 *      assumption: both are 0xFF in V26 and in V29, and both of those images
 *      have booted on real hardware. A checksum record over a blank sector
 *      would have stopped them."
 *
 * EVERY WORD OF THAT IS WRONG, and the argument inverts. 0xFF in both sectors
 * is exactly the state the stored checksum was COMPUTED FOR. Blank sectors
 * booting proves the record is CONSISTENT with blank, not that the record
 * ignores them.
 *
 * tools/build_hanicore_me711.py::program_page_sum() - in this repository, and
 * older than the sentence it contradicts - sums the FIRST AND LAST WORD OF
 * EVERY 8 KiB PAGE over 0x00000-0x0FFFF and 0x20000-0xFFFFF and stores the
 * result in the ROMSYS header at 0x00803C. 0x040000 and 0x050000 are both
 * page-boundary words inside that range.
 *
 * On 2026-09-05 the first real Burn programmed a complete, valid record at
 * 0x040000. word[0x040000] went 0xFFFF -> 0x4348 ('HC'), the stored sum
 * 0x00E2448E stopped matching the computed one, and the ECU never ran its
 * application again - bootmode only, until a full reflash. The evidence is
 * failedReadback/FAILED_BURN_DUMP.bin and
 * the maintainer's design records.
 *
 * SO THE RULE, AND IT IS A BOARD FACT, NOT A PREFERENCE:
 *
 *     NO RUNTIME FLASH WRITE MAY EVER CHANGE THE FIRST OR THE LAST WORD OF
 *     ANY 8 KiB PAGE IN 0x800000-0x80FFFF OR 0x820000-0x8FFFFF.
 *
 * The ME7.5 target has obeyed this for months - docs/PLATFORM.md
 * says its linker script "has to dodge the words the bootrom's program-page
 * checksum samples". This target now dodges them too.
 * =========================================================================
 *
 * HOW IT DODGES THEM: a record CELL is one 8 KiB checksum page, and the cell
 * body starts at page + 2 and is at most TGT_FLASH_CELL_BODY bytes long. The
 * page's first word (page + 0) and last word (page + 0x1FFE) are therefore
 * never programmed and stay 0xFF for the life of the device.
 *
 * AND THERE IS NO RUNTIME ERASE. An erase cannot be made checksum-safe: the
 * AM29F800BB's embedded erase begins by PRE-PROGRAMMING the whole sector, so
 * an erase that is interrupted clears bits everywhere in it - including both
 * sampled words. That is not a hypothesis either: the failed-Burn dump shows
 * sector SA8 with ~5 % of all 524288 bits cleared, uniformly, no byte fully
 * 0x00 - the signature of an aborted embedded erase - and three of SA8's
 * sixteen sampled words damaged with it.
 *
 * So the store is APPEND-ONLY. Sixteen cells, written in order, newest valid
 * generation wins, nothing is ever erased. When the last cell is used, a Burn
 * REFUSES and says so; reclaiming space needs an erase, and an erase on this
 * board is an unproven, operator-supervised bench action that does not exist
 * yet.
 *
 * NOT PHYSICALLY VERIFIED: the 29F800BB sector map is the datasheet's for the
 * part the BOM names (S5200, AM29F800BB-70SE). PHYSICALLY VERIFIED as of
 * programming a 4120-byte record at 0x840000 works, word by word,
 * with read-back - the failed dump's SA7 differs from the known-good image in
 * exactly those 4120 bytes and nowhere else.
 */
/* ===================== THE STORE, AND WHY IT MOVED AT V53 ==============
 *
 * SA9..SA18, ten whole erase sectors, eighty 8 KiB cells - and, crucially,
 * ENTIRELY OUTSIDE THE BOOTROM'S PROGRAM-PAGE RECORD.
 *
 * Until V53 the store was SA7/SA8 and it was INSIDE that record, which is why
 * it was append-only, never erased, and hard-capped at sixteen Burns. That cap
 * was not a design preference. Three facts made reclaiming it dangerous:
 *
 *   1. the boot block REFUSES to enter HaniCore when the stored page record
 *      stops matching - proven on 2026-09-05 by one programmed word at
 *      0x040000, which cost a bootmode reflash;
 *   2. an AMD embedded erase PRE-PROGRAMS the whole sector to 0x00 before
 *      erasing it, so every sampled word in that sector is wrong for the ~2 s
 *      the erase takes (Am29F800B: sector erase typ 1.0 s / max 15 s, and
 *      that figure EXCLUDES the pre-program pass);
 *   3. this board ties the 29F800's hardware RESET pin - 44-pin SO pin 44 -
 *      to RSTIN_FR (schematic: RSTIN_FR == RST_FLASH -> CPU pin 140, flash
 *      pin 44, SRAM CE2 pin 30). The datasheet is explicit that a hardware
 *      reset TERMINATES an embedded algorithm and leaves the affected
 *      locations indeterminate. So SWRST_SM does not merely interrupt the
 *      CPU mid-erase - it ABORTS THE ERASE.
 *
 * Fact 3 also RETRACTS what hcnvm.h used to say - "a NOR erase completes
 * inside the device with or without the CPU as long as the supply is present,
 * that is the SWRST_SM case". It does not, on this board.
 *
 * WHAT CHANGED IS NOT THE RISK APPETITE, IT IS THE COVERAGE. The record's
 * range is not hardcoded in the boot block: it is read out of the ROMSYS
 * header this build generates. header+0x14 is the second range's limit and it
 * has exactly ONE consumer in the whole boot block (0x72D2). Lowering it to
 * 0x85FFFF removes SA9..SA18 from the record, so nothing up here is sampled,
 * an aborted erase changes no word the boot block looks at, and reclaiming a
 * sector is an ordinary NVM event.
 *
 * Bosch does the same thing one sector lower: SA4 sits in the HOLE between the
 * two summing loops and carries its own two-word record. This is that pattern.
 *
 * The loop offers two ranges, so the excluded region has to be contiguous at
 * the top - which is why TGT_CODE_BASE came down to SA7. Every executable byte
 * is still covered, and tools/me711_bootsum_coverage_proof.py proves it by
 * EXECUTING the Bosch routine rather than by modelling it.
 *
 * ENDURANCE IS NOT A CONSTRAINT AND MUST NOT BE DESIGNED FOR. The Am29F800B
 * guarantees a MINIMUM 100,000 erase cycles per sector. Eighty cells over ten
 * sectors is 100000 * 80 = EIGHT MILLION Burns before the guaranteed endurance
 * of the first sector is reached. There is no case for wear levelling here.
 */
#define TGT_FLASH_CFG_A       0x860000uL   /* SA9,  first store sector       */
#define TGT_FLASH_CFG_SEG     0x0086u      /* its segment, for 16-bit maths  */
#define TGT_FLASH_SECTORS     10u          /* SA9..SA18                      */

/* One cell per 8 KiB checksum page; eight pages per 64 KiB sector.
   The page geometry is kept even though these pages are no longer sampled:
   an 8 KiB cell is one record with room to spare, the arithmetic stays 16-bit
   (see CELL_PAGEOFF in hcnvm.c), and a future move back under the record
   would not need the layout rethought. */
#define TGT_FLASH_CELL_PAGES  8u
#define TGT_FLASH_CELLS       (TGT_FLASH_SECTORS * TGT_FLASH_CELL_PAGES)

/* The offset of a cell body inside its page, and the most it may occupy.
   Retained from the pre-V53 geometry: the cost is four bytes a cell and it
   keeps every record clear of a page boundary. */
#define TGT_FLASH_CELL_OFF    2uL
#define TGT_FLASH_CELL_BODY   0x1FFCuL

/* Sector n of the store, and the cell range it holds. */
#define TGT_FLASH_SECTOR_OF(cell)  ((cell) / TGT_FLASH_CELL_PAGES)
#define TGT_FLASH_SECTOR_BASE(s)   (TGT_FLASH_CFG_A                                     + (unsigned long)(s) * TGT_FLASH_SECTOR_SIZE)

/* Where HaniCore's own code is linked. SA7: clear of the boot contract and the
   update-loader reservation below it, clear of the persistence store above it,
   inside the bootrom page record, and one whole erase sector so a re-flash of
   the firmware never touches anything else. SA8 above it is reserved for code
   growth and is also inside the record, so code may spill one sector without
   the record boundary - and therefore the store - having to move again. */
#define TGT_CODE_BASE         0x840000uL
/* SA7 AND SA8. V53 started with code in SA7 alone and SA8 reserved beside it;
   the reclaim needed about 1.8 KiB more than SA7 had left, so the reservation
   was spent - which is what it was for. Both sectors are inside the bootrom
   page record, so this changed nothing about the record's boundary and nothing
   about the store above it. It does mean an application update erases TWO
   sectors rather than one. linker_me711.lnp records the move. */
#define TGT_CODE_SIZE         0x20000uL

/* ======================================================= the ASIC link ====
 *
 * The ME7.1.1 monitoring module is a SECOND C167 [BOSCH-PM sheet "ASIC",
 * "Ressourcen SAB C167; Pinbelegung Peripherie-ASIC"], and it is not a
 * passenger: its P1H.2 is ESRST_SM, "Abschaltung EGAS + Endstufen", and its
 * P1H.3 is SWRST_SM, "Abschaltung SG-Rechner" - it can shut the output stages
 * down and it can RESET THIS CPU. [BOSCH-SCH] shows both arriving at the
 * LM2901 comparator network that drives RSTIN_FR.
 *
 * The link itself, all [OEM ME7.1.1] unless marked:
 *
 *   MAIN  P3.9  MTSR ->  ASIC P3.8 MRST        SSDO/SSDI [BOSCH-PM]
 *   MAIN  P3.8  MRST <-  ASIC P3.9 MTSR
 *   MAIN  P3.13 SCLK ->  ASIC P3.13 SCLK
 *   MAIN  P6.4  CS-ASIC ->  ASIC P2.9, which gates its transfer ISR
 *                           [reference IROM 0x1906]
 *
 *   init at 0x82325E:  SSCCON = 0x461F idle / 0xC61F running, SSCBR = 0x13
 *   transfer at 0x8233A6: PEC4 RX SSCRB->buffer, PEC0 TX buffer->SSCTB
 *   startup frame  0x60 words = 192 bytes, checksum in word 95
 *   runtime frame  0x76 words = 236 bytes, checksum in word 117
 *   header word 0 = 0xBAA5 [0x8BE2B6 writes A5 BA]
 *   reply class byte accepted: 0x1E or 0x2E [parser 0x8BE4E8]
 *   checksum: 16-bit additive word sum [0x8BEB34]
 */
/* How long to hold the chip select LOW before the first SSC clock, in T7
   ticks (T7 = 1.250 MHz, so 0.8 us per tick).

   79 ticks = 63.2 us. That reproduces the OEM's own behaviour: between
   BCLR P6.4 [0x8BE760] and the PEC start [0x8BE7B4] the OEM ME7.1.1 executes at
   least 1270 instructions - a 96-word copy, a 95-word checksum, an SSC init -
   and then explicitly waits for T4 to advance. ~63 us at MAIN's confirmed
   40 MHz is that same class of delay.

   It is deliberately NOT derived from the S5500's instruction count: that
   part's CLKCFG is strapped on P0H at reset and its ROM never writes SYSCON,
   so its fCPU is not known here and MAIN's 40 MHz does not apply to it. The
   OEM master's measured behaviour is the authoritative figure. */
#define TGT_ASIC_CS_ARM_TICKS 79u

#define TGT_ASIC_SSCCON_IDLE  0x461Fu
#define TGT_ASIC_SSCCON_RUN   0xC61Fu
#define TGT_ASIC_SSCBR        0x0013u
#define TGT_ASIC_WORDS_START  0x60u
#define TGT_ASIC_WORDS_RUN    0x76u
/* TWO headers, and they are NOT the same frame.
   [BIN] the RUNTIME packer 0x8BE2B6 writes them as two BYTE immediates -
   MOVB #A5h into byte 0 and MOVB #BAh into byte 1 - so word 0 = 0xBAA5. A
   16-bit search for that constant finds nothing, which is how it came to be
   doubted; it is written bytewise.
   [BIN] the STARTUP frame's word 0 is 0x0055, decoded from the OEM builder at
   0x8B189C, and the ASIC IROM compares a received byte against 0x55. */
#define TGT_ASIC_HEADER       0xBAA5u    /* runtime, 118 words */
#define TGT_ASIC_HEADER_START 0x0055u    /* startup, 96 words  */

/* [BIN] 0x8BE7CC / 0x8BE88A: the OEM waits at most 0xA5 T4 ticks for a
   transfer to complete before treating it as failed. HaniCore measures the
   same deadline in its own milliseconds instead, because T4's prescaler is
   written from a table rather than an immediate and is therefore not
   recoverable offline.
   THE CLOCK IN THIS NOTE WAS WRONG AND THE CONSTANT IS NOT. It read "96 words
   at SSCBR=0x13 is 499.2 kHz -> 3.077 ms". SSCBR = 0x13 with TGT_FCPU_HZ gives
   f/(2*(0x13+1)) = 1 MHz, so a 16-bit word is 16 us: the 96-word startup frame
   is 1.54 ms and the 118-word runtime frame 1.89 ms - HALF what was written
   here. 8 ms was generous against the overstated figure and is more generous
   against the real one, so the budget stands unchanged; only the arithmetic
   that justified it is corrected. The ACTUAL measured duration is published as
   hc_asic_last_xfer_ms and in the V49 forensic slots, so the bench replaces
   this estimate with a fact rather than inheriting either number. */
#define TGT_ASIC_XFER_TIMEOUT_MS  8u

/* [BIN] 0x8BE7FE / 0x8BE8BC: the OEM retries and, after the counter passes
   0x10, gives up and marks startup done ANYWAY rather than hanging. HaniCore
   keeps retrying instead - there is no application to proceed to - but it
   counts them so a bench log shows whether the ASIC ever answered. */
#define TGT_ASIC_START_RETRY_MAX  17u

/* Milliseconds between startup attempts. DECLARED, not recovered: the OEM
   cadence lives in a boot-block dispatch table (see ME711_ASIC.md).
   20 ms is comfortably longer than one exchange plus its timeout - 1.54 ms on
   the corrected 1 MHz SSC model, see TGT_ASIC_XFER_TIMEOUT_MS. */
#define TGT_ASIC_START_PERIOD_MS  20u
/* CORRECTED 2026-08-30, from a placeholder to an OEM-derived value.
 *
 * This was 20u, DECLARED rather than recovered, for every image through
 * SALVAGE_V12. The A1104F A2L (the A1104F A2L)
 * names ECU address 0xC022 - independently identified from the OEM ME7.1.1 binary
 * itself as the scheduler slot owning the ASIC runtime service, see
 * docs/ARCHITECTURE.md "the runtime raster PINNED" - as `r10msCtr`,
 * "10ms-Raster-Zaehler der Funktion", one of four distinctly-addressed
 * siblings (r2msCtr=0xC028, r5msCtr=0xC02C, r10msCtr=0xC022, r20msCtr=0xC026:
 * no ambiguity). Confirmed by direct disassembly of the OEM ME7.1.1 binary, not
 * merely the address match: the unconditional CALLS block starting at
 * 0x822C0C - the same address tied to that scheduler slot - calls 0x8BEAB4
 * (checksums the buffer, compares against word 117, calls the reply parser
 * 0x8BE4E8 on match) every time it runs; the sibling block at 0x822E78/
 * 0x822FBA calls 0x8BEAE8, which does `BCLR P6.4` and builds+sends the next
 * runtime frame (0x8BE2B6, 0x8BE308). The OEM re-arms the runtime exchange
 * on a 10 ms raster, not 20 ms - the thirteenth hardware result (zero
 * salvage across ~180 boots, the maintainer's hardware-session record
 * is consistent with HaniCore's own attempt landing one raster tick late. */
#define TGT_ASIC_RUN_PERIOD_MS    10u
#define TGT_ASIC_REPLY_A      0x1Eu
#define TGT_ASIC_REPLY_B      0x2Eu
#define TGT_ASIC_CS_PORT_BIT  4         /* P6.4 */

/* NLEN_FR, the power hold. [BOSCH-PM] me7_port.xls sheet FR, BHE/WRH/P3.12,
   CPU pin 79 - BOTH ME7.1.1 columns say NLEN_FR. [BOSCH-SCH] Rechnerkern
   confirms the net at S5000 pin 79, and it reaches the CJ910's NL input (pin
   26) after being ANDed with the ASIC's NLEN_AS. [BOSCH-BIN] the OEM asserts
   it in its port init at seg8C:0DCC (MOV P3,#BF01h then MOV DP3,#35FEh),
   called from seg8C:0B4A, four calls before EINIT at seg8C:0B62.
   Usable as a GPIO only because SYSCON has BYTDIS set, which the HaniCore
   startup already does in both ROMEN branches. Asserted on the NLEN half of
   the RESETDIAG_V3 A/B, from the STARTUP, before EINIT. */
#define TGT_NLEN_FR_PORT_BIT  12        /* P3.12 */

/* ============================================ the power path, in full =====
 *
 * CORRECTIONS (2026-10-06) - this block is the 2026-09-02 derivation and is
 * kept as written; three of its statements were overturned later:
 *   - KL15 enters on connector CAVITY 21 (U_U_KL15 -> R4000 -> CJ910 EIN),
 *     not cavity 3. Cavity 3 is U_U_UBR, the relay-switched feed IN.
 *     Measured: removing +12 V from 21 takes the ECU offline.
 *   - CJ910 pin 16 is the main-relay stage MR and drives cavity 23
 *     (A_S_HR) - see the 2026-09-25 block below; it is not unconnected.
 *   - run-on WORKS and is pre-armed: since V80 NLEN_FR (P3.12) is held
 *     LOW for the whole key-on while MAIN_RELAY is on the native stage and
 *     released when the store is idle and mainRelayHoldMs has passed
 *     (measured on the bench). The "permanent veto" below describes
 *     the builds before run-on existed.
 * Current pinout: docs/PINOUT.md.
 *
 * WHAT THE MAIN CPU CAN AND CANNOT DO TO ITS OWN POWER. Established
 * 2026-09-02 from the vector geometry of the Rechnerkern and Ein-Ausgaenge
 * sheets, not from reading pixels; docs/PLATFORM.md carries the
 * derivation and the segment coordinates.
 *
 *   KL15 (connector cavity 3) --R4000--> CJ910 pin 21 EIN     "turn on"
 *   KL30 (connector cavity 62) --D4000--> CJ910 pin 20 UBATT  the feed
 *   CJ910 pin 16 HR ......................  net NC_4000_16    NOT CONNECTED
 *   CJ910 pin 26 NL <-- R5600 <-- S5600 (74ACT00, on VSTBY)
 *
 * and that 74ACT00 is TWO gates, not one, which changes the meaning:
 *
 *   gate A  pins 1+2 TIED    -> pin 3  = NOT(NLEN_FR)      R5602 pulls
 *                                                          NLEN_FR to VCC_CPU
 *   gate B  pin 4 = gate A out
 *           pin 5 = NLEN_AS  -> pin 6  = NAND(/NLEN_FR, NLEN_AS)
 *                                                          R5601 pulls
 *                                                          NLEN_AS to GND
 *
 *      NL  =  NLEN_FR  OR  NOT(NLEN_AS)
 *      NL is LOW  <=>  NLEN_FR is LOW  AND  NLEN_AS is HIGH
 *
 * So NL falls only when the FUNKTIONSRECHNER has released AND the ASIC has
 * asserted. Every reset state - both ports high-Z, NLEN_FR pulled up,
 * NLEN_AS pulled down - leaves NL HIGH.
 *
 * WHICH WAY ROUND NL MEANS "STAY ALIVE" IS INFERRED, NOT READ OFF A
 * DATASHEET, and the inference is worth writing down because the other
 * reading would be a battery-drain hazard:
 *
 *   - the OEM sets NLEN_FR HIGH in port init, BEFORE EINIT, and holds it
 *     there while running. `BCLR P3.12` appears only on its shutdown paths.
 *   - HaniCore has done exactly the same since RESETDIAG_V3, and across
 *     sixteen hardware sessions this ECU has always powered down with KL15.
 *
 * If NL HIGH meant "run-on requested" the bench would have found an ECU that
 * would not switch off. It never has. So NL is ACTIVE LOW and means "run-on
 * requested": HIGH is the ordinary state, and asserting run-on needs BOTH
 * processors - the FR to release NLEN_FR and the ASIC to drive NLEN_AS. A
 * hung processor can neither hold the car's ECU alive nor take its power
 * away. That is the safety property, and it is why holding P3.12 HIGH is
 * correct: it permanently VETOES run-on, which is the safest state a build
 * with no run-on logic can be in. It is a veto, not a hold - the function
 * name hc_power_hold_assert() predates this derivation.
 *
 * TO CONFIRM IT: meter on connector cavity 3 (KL15) and on the ECU's own
 * VCC while the key drops. See docs/PLATFORM.md, measurement 3.
 *
 * THERE IS NO MAIN-RELAY OUTPUT ON THIS CPU. All 112 MAIN CPU rows of
 * tools/config_source/data/me711_iomap.csv were enumerated: no HR, no HRS, nothing
 * relay-shaped. The only main-relay signal anywhere in the port sheet is ASIC
 * P5.14/AN14 "HR / Hauptrelaisansteuerung", and Bosch's own note on that row
 * is "Port nur Input" - the ASIC MEASURES the relay rail, it does not drive
 * it. The A2L agrees: wubr_w is "Batteriespannung ueber Hauptrelais;
 * ADC-Wert". Command is not ours; monitoring is.
 */
#define TGT_NL_HIGH           1u
#define TGT_NL_LOW            0u

/* THE MAIN RELAY STAGE EXISTS, AND IT IS THE CJ910's, NOT THIS CPU's (2026-09-25).
 *
 * The paragraph above is right that no MAIN CPU port commands a main relay,
 * and wrong only in what it implies. Cavity 23 = A_S_HR <- CJ910 pin 16 HR
 * (the ME7.1.1 schematic, and the Porsche service pinout: DME main relay terminal 85).
 * the Bosch CJ911 product information, the pin-for-pin sibling: pin 16 MR "Main relay
 * stage output", low side, and the part's ONLY controls for it are EN1 =
 * KL15 ("control for all switchable outputs") and /EN2 = keep-alive. So the
 * relay closes with the key and opens with it, and this CPU's one lever is
 * run-on through NLEN_FR, which it vetoes. HaniCore routes MAIN_RELAY to it
 * as a HARDWARE function (descriptor cap MAIN_RELAY_HW); the HAL writes
 * nothing and reports KL15_STAT below as the stage's predicted state.
 *
 * KL15_STAT: CJ910 pin 25 ST (CJ911 "IGN, 5 V ignition signal output"), MAIN
 * P6.2 / CPU pin 3, both ME7.1.1 port-map columns. Read, never driven. */
#define TGT_MAIN_RELAY_CAV    23
/* cavity 104 = LDR, the boost valve (AWT N75 lands on the same cavity):
   ASIC P7.2, family workbook SRU1_S|LDR_S, port map ASIC P7.2 = LDR
   (B-Muster). Driven through the S5500 frame's P7 image - hcio711.c. */
#define TGT_LDR_CAV           104
/* cavity 47 = the check-engine lamp stage: ASIC P7.0 through a CJ920
   low side (two outputs paralleled, 2.2 A) - the ME7.1.1 schematic W12 sheet (net
   LUES2_PX70 -> S6500 pins 9 -> 4/5 -> 47 "A_S_LUES2 / A_S_SPOEKUE /
   A_S_MIL"), SAME-GENERATION SCHEMATIC; the family table's 47 MIL_S; the
   AWT ME7.5 map's MIL lamp on 47. THIS ECU's binary actuator-tests the
   same port-image bit (FDE8.0, 0x08F8C6/CA: BSET off / BCLR on - the LDR
   pattern), so it is an output, ACTIVE LOW. Not yet on a meter. */
#define TGT_MIL_CAV           47
#define TGT_KL15STAT_PORT_BIT 2         /* P6.2 */

/* ==================================================== EKP, the fuel pump ==
 *
 * [BOSCH-PM] me7_port.xls sheet "FR", P2.12 / CC12IO, CPU pin 61, signal EKP,
 * meaning "EKP-Ansteuerung". BOTH ME7.1.1 columns agree - the same standard
 * of evidence the injector and coil pins rest on, in the same document.
 *
 * [BOSCH-SCH] Ein-Ausgaenge sheet, and this part is STRONGER than what the
 * injectors have: the net EKP arrives at S6500, a CJ920 quad low-side driver
 * marked "0,6A 40V", on inputs 13 AND 14 in parallel. Its outputs 15 and 16,
 * also paralleled, pass through D6502 (a GF1G) and leave the ECU at
 * connector cavity 65, net A_S_EKPR - "Relais fuer elektrische
 * Kraftstoffpumpe" in Bosch's own Steckerbelegung.
 *
 * THE PREDICTION WAS WRONG, AND A LOGIC ANALYZER SETTLED IT (2026-09-25).
 * The CJ920 is drawn with a NON-INVERTING buffer symbol, so a HIGH on P2.12
 * was expected to turn the stage on. Measured on the bench ECU running V75,
 * cavity 65 pulled up to 3.3 V into logic analyzer D0:
 *
 *   P2.12 an INPUT (reset, released)    cavity 65 OPEN     (D0 high)
 *   P2.12 driven HIGH (V75's "ON")      cavity 65 OPEN     (D0 high)
 *   P2.12 driven LOW  (V75's 13-14 us   cavity 65 SINKING  (D0 low)
 *     release window, "!act" written
 *     before the direction dropped)
 *
 * So THE EKP STAGE IS ACTIVE-LOW AT THE CPU PIN: a LOW sinks cavity 65, and a
 * released pin leaves it open - the safe resting state 12M/1 chose a
 * direction for. V75 never energised anything while "ON" and pulsed the
 * stage for ~13 us on every release.
 *
 * This is a fact about THIS BOARD's driver stage, not a tuner choice, which
 * is why it lives here and not on the page. Cavity 65 is LOW_SIDE|RELAY_OUT
 * in the descriptor: it can sink or be open, it cannot source, so there is no
 * "active high" wiring a tuner could select that the stage can honour.
 *
 * WHY THE DIRECTION REGISTER IS WRITTEN EXPLICITLY. After reset P2.12 is an
 * input, and the measurement above shows the stage is OFF with the pin
 * released. The startup leaves it an input; nothing but the HAL and the
 * bench mode ever makes it an output.
 */
#define TGT_EKP_PORT_BIT      12        /* P2.12 / CC12IO, CPU pin 61 */
#define TGT_EKP_CONN_PIN      65        /* A_S_EKPR - VW ME7.1 Steckerbelegung,
                                           CONFIRM continuity on this ECU */
#define TGT_EKP_ACTIVE_HIGH   0         /* MEASURED: P2.12 LOW = cavity 65
                                           sinks. Logic analyzer, 2026-09-25 */

/* THE COIL AND INJECTOR STAGES ARE ACTIVE-LOW, from the exact target's own
 * machine code. NOT YET MEASURED AT A CAVITY - see below.
 *
 * [BIN seg8C:0DCC] the OEM power-on port init of THIS ECU's software
 * (022906032BT, the target OEM firmware cc95e3af...) writes
 *
 *     P2 = 0xC7FF   DP2 = 0x38FF    coils ZDG1..8 (P2.0-7) OUTPUTS, HIGH
 *                                   EKP (P2.12)           OUTPUT,  LOW
 *     P7 = 0x00F4   DP7 = 0x00FF    EV1..EV3 (P7.6/5/4)   OUTPUTS, HIGH
 *     P8 = 0x00FF   DP8 = 0x00FF    EV4..EV8 (P8.7..3)    OUTPUTS, HIGH
 *
 * at key-on, before the engine can turn. No ECU holds eight injectors open
 * and eight coils in dwell from key-on, so HIGH is OFF. THE SAME READING
 * PREDICTS EKP LOW = pump ON - the key-on prime - and that is exactly what the
 * logic analyzer measured on cavity 65 (TGT_EKP_ACTIVE_HIGH 0), so the method
 * is checked against a measurement, not merely plausible. Two more agree: the
 * ME7.1.1 sheet draws every input of the S8620 "Zuendtreiber" (ZUE1..6) with
 * an inversion bubble, and the injectors sit on CJ920 packages, the family
 * whose EKP channel measured inverting under a NON-inverting symbol. The
 * startup's section 2 has latched these pins HIGH as "off" on the same OEM
 * evidence for many releases.
 *
 * Until V77 the HAL used ONE compile-time OUT_ACTIVE_HIGH = 1 for both, so
 * an armed engine would have driven HIGH (off) for every ON and written LOW
 * (on) for microseconds before each release - V75's EKP signature on sixteen
 * outputs. Nothing was connected or armed, so nothing was driven.
 *
 * A BOARD FACT PER CLASS, NOT A PAGE FIELD (12Z). STILL NOT PHYSICALLY
 * QUALIFIED: a logic analyzer on one EV and one ZUE cavity is the
 * measurement, and until it is made no injector or coil may be connected. */
#define TGT_IGN_ACTIVE_HIGH   0         /* ZUE1..8, P2.0-P2.7 */
#define TGT_INJ_ACTIVE_HIGH   0         /* EV1..8, P7.4-P7.6 and P8.3-P8.7 */

/* ============================================== DVE, the throttle bridge ==
 *
 * [BOSCH-SCH] Ein-Ausgaenge sheet, device S8100. Four signals in, one fault
 * out, two motor terminals:
 *
 *   S8100 pin  3  IN1  <- DVE1    MAIN P7.2  / POUT2 , CPU pin 21
 *   S8100 pin 19  IN2  <- DVE2    MAIN P7.7  / CC31  , CPU pin 26
 *   S8100 pin 18  DI1  <- EGENFR  MAIN P2.11 / CC11  , CPU pin 60
 *   S8100 pin 13  DI2  <- ED_RST  NOT A CPU PIN - the monitoring net,
 *                                 drawn with an inversion bubble
 *   S8100 pin  2  SF   -> SF      MAIN P3.15         , CPU pin 81,
 *                                 open drain, R8100 pulls it to VCC_OUT
 *   S8100 pins 6,7   OU1 -> connector cavity 117, ESBM+
 *   S8100 pins 14,15 OU2 -> connector cavity 118, ESBM-
 *
 * READ DI2 AGAIN. ED_RST comes off the LM2901 comparator network on the
 * Rechnerkern sheet, in the same bundle as RSTIN_FR / RSTIN_SM / ESRST_SM -
 * and ESRST_SM is the ASIC's P1H.2, whose Bosch note is "Absch. EGAS+Endst.".
 * THE MONITORING HARDWARE CAN DISABLE THIS BRIDGE WITHOUT ASKING THE MAIN CPU.
 * A HaniCore DBW that finds the throttle limp when it commanded motion must
 * report that, not fight it.
 *
 * SF IS ON A DIFFERENT PIN HERE THAN ON THE ME7.5 BOARD. The 4B0906018DC
 * hcdbw.c has `sbit SF_PIN = P2 ^ 9`. On ME7.1.1 P2.9 is NWDG2, the SECOND CAM
 * INPUT. Linking that file here unchanged would have driven a cam capture pin
 * and called it a bridge fault. SF comes from here, never from a literal.
 *
 * P3.15's alternate function is CLKOUT, which would make it useless as an
 * input. It is free: the startup writes SYSCON 0xE644 (ROMEN set) or 0xE244
 * (clear) and CLKEN is bit 8 - clear in both. tools/me711_dbw_bench_proof.py
 * checks that against the linked image rather than trusting this comment.
 */
#define TGT_DBW_PWM_PORT_BIT   2        /* P7.2  -> S8100 IN1 */
#define TGT_DBW_DIR_PORT_BIT   7        /* P7.7  -> S8100 IN2 */
#define TGT_DBW_EN_PORT_BIT   11        /* P2.11 -> S8100 DI1 */
#define TGT_DBW_SF_PORT_BIT   15        /* P3.15 <- S8100 SF  */

/* V83. EGENFR IS ACTIVE LOW. THE BRIDGE IS PERMITTED ONLY WHILE P2.11 IS LOW.
 *
 *   EGENFR_P211 -> S8100 pin 18 "DI1"      SAME-GENERATION BOSCH SCHEMATIC,
 *                                          the ME7.1.1 schematic p1 read at 700 dpi 2026-09-25
 *   CJ220 pin 18 = DI "Disable": DI = H -> outputs Z, SF = L; DI = Z (open)
 *                  -> outputs Z, SF = L     EXACT COMPONENT DATASHEET,
 *                                          the Bosch CJ220 datasheet truth table rows 5, 9
 *   pin 13 "DI2" is drawn with an inversion bubble = CJ220 EN (L disables),
 *                  driven by ED_RST, not by this CPU
 *   OEM: P2 = 0xC7FF with DP2.11 set at key-on -> P2.11 driven LOW [BIN
 *        seg8C:0DCC]; runtime `JB FD56.5 -> BSET P2.11 else BCLR P2.11`
 *        [BIN 0x88EE2E], the same shape as its EKP write two lines earlier
 *        (P2.12 HIGH = pump OFF, MEASURED V76)
 *
 * UNTIL V83 hc_hal_out(THR_EN, 1) DROVE P2.11 HIGH - DISABLE - so the bridge
 * could never have conducted, and SF would have read LOW (the CJ220 reports a
 * disabled bridge as a flag) which the controller latched as DBW_F_SF. Released
 * (input) stays the safe rest: the datasheet's "DI disconnected" row is
 * disabled. NOT PHYSICALLY QUALIFIED: SF HIGH with the bridge armed at zero
 * duty is the motor-free bench proof. */
#define TGT_DBW_EN_ACTIVE_HIGH 0
#define TGT_DBW_CONN_PIN_P   117        /* ESBM+ */
#define TGT_DBW_CONN_PIN_M   118        /* ESBM- */
#define TGT_SYSCON_CLKEN_BIT   8        /* SYSCON.8; 0 = P3.15 is a GPIO */

/* The PWM period for the throttle bridge, in f_CPU counts: 20000 = 2.000 kHz,
   THE OEM's OWN FREQUENCY FOR THIS BRIDGE.

   V63..V92 used 2000 (20 kHz) on the belief that it was "far below the
   S8100's switching limit". It is not: the CJ220 datasheet's timing table
   (the Bosch CJ220 datasheet, EXACT COMPONENT
   DATASHEET) rates the PWM frequency by supply - 5 kHz at 6-7 V, 10 kHz at
   7-8 V, 20 kHz at 8-12 V, with a 1 kHz entry for the 33 nF charge-pump
   capacitor. 20 kHz is the absolute limit on a healthy battery and beyond it
   during any sag; the high side's charge pump then cannot enhance the gate
   and the bridge delivers far less than the commanded duty.
   The OEM ME7.1.1 port init programs exactly this (EXACT TARGET BINARY,
   the target OEM firmware @0xC0D96: EXTR #2; MOV PT2,#0;
   MOV PP2,#4E1Fh; MOV PW2,#0; ... MOV PWMCON0,#00BFh = PTI2 0 -> f_CPU):
   PP2 = 19999 -> 40 MHz / 20000 = 2 kHz. (Same routine: channels 0/1 at
   f_CPU/64 with PP 2499 = the known 250 Hz on cavities 115/120, which
   checks the decoding.)
   PHYSICAL SYMPTOM (AWT, 2026-09-27, V92): Auto Calibrate at 50 % duty
   produced "two very small twitches"; rusEFI drives this same Bosch body to
   both stops with 50 %.
   20000 still divides a 0.1 % duty step into an integer count (20). */
#define TGT_DBW_PWM_PERIOD  20000

/* ===================================================== analog inputs ======
 *
 * [BOSCH-PM] sheet "FR", columns "Belegung ME7.1.1 B-Muster" and
 * "ME7.1.1 C-Muster, AUDI". They agree on every channel below.
 *
 * READ THIS BEFORE LOOKING FOR A COOLANT SENSOR: on ME7.1.1 the engine
 * temperature sensors are NOT on this CPU. The ASIC sheet puts TMOT on ASIC
 * AN0, TANS on ASIC AN1 and TMOT2 on ASIC AN15, and they reach the main CPU
 * inside the 118-word frame. That is the single biggest structural difference
 * from the ME7.5 board and it is why the ASIC link is not optional for engine
 * control - only for a bench proof-of-life.
 */
#define TGT_ADC_HFM_CH         0      /* air mass, ANALOG here (not a freq)  */
#define TGT_ADC_TPS1_CH        1      /* IP1S  throttle position track 1     */
#define TGT_ADC_TPS1_AMP_CH      2      /* IPV   TPS1 amplified approximately 4.16x */
#define TGT_ADC_TPS2_CH        3      /* IP2S  throttle position track 2     */
#define TGT_ADC_LS2VK_CH       4      /* lambda 2 before cat                 */
#define TGT_ADC_BATT_CH        5      /* UBAT                                */
#define TGT_ADC_LS1VK_CH       6      /* lambda 1 before cat                 */
#define TGT_ADC_LS1HK_CH       7      /* lambda 1 after cat                  */
#define TGT_ADC_PEDAL1_CH      8      /* SPS1 / DKG                          */
#define TGT_ADC_PEDAL2_CH      9      /* SPS2                                */
#define TGT_ADC_LS2HK_CH      10      /* lambda 2 after cat                  */
#define TGT_ADC_AUX11_CH      11      /* IAGR (B-Muster) / CP (C-Muster)     */
#define TGT_ADC_DMTL_CH       12
#define TGT_ADC_HFM2_CH       13      /* C-Muster only; unused on B-Muster   */
#define TGT_ADC_AUX14_CH      14      /* TAGR (B) / DSS (C)                  */
#define TGT_ADC_KNOCK_CH      15      /* KI                                  */

/* Full scale: the battery voltage that reads 1023 counts.
 *
 * THIS WAS 170 AND IT WAS AN ME7.5 GUESS. The comment said so - "[ME75, INF]",
 * the ME7.5 divider ratio "until a bench reading says otherwise". The bench
 * reading came: on V29 the ECU reported about 12.1 V while a multimeter on the
 * same terminals read about 12.9 V. That is a 6 % under-read, in the direction
 * a too-small full scale produces, and it is now traced rather than trimmed.
 *
 * A SAME-FAMILY A2L SETTLES THE QUANTISATION, and a bench measurement
 * corroborates it. `the A1104F A2L` is NOT a map
 * of this binary - its EPK is not the one at 0x810005 in the image this ECU
 * runs, so none of its ADDRESSES may be read here. Its COMPU_METHODs are a
 * different matter: a quantisation is a family property, and this one
 * gives the OEM's own quantisation for the battery channel:
 *
 *     ub        "Batteriespannung"                UBYTE  spg_ubatt
 *     spg_ubatt   RAT_FUNC  COEFFS 0 1 0 0 0 0.0704   ->  0.0704 V per count
 *     spg_ubatt_w RAT_FUNC  COEFFS 0 1 0 0 0 0.0176   ->  0.0176 V per count
 *
 * Bosch forms the byte from the 10-bit word by >>2, and 4 x 0.0176 = 0.0704
 * exactly, so the two agree and the WORD is the converter's own resolution:
 * one count is 0.0176 V, and 1023 counts is 18.0 V. The divider is built so
 * 5.00 V at the pin means 18.0 V at the terminal.
 *
 * AND THE ARITHMETIC CLOSES ON THE MEASUREMENT, which is why this is a root
 * cause and not another constant. At a true 12.9 V the converter sees
 * 12.9/18.0 x 1023 = 733 counts. Through the old full scale that reads
 * 733 x 170 / 1023 / 10 = 12.18 V - the 12.1 V the bench saw. Through this one
 * it reads 733 x 180 / 1023 / 10 = 12.90 V.
 *
 * NOT PHYSICALLY VERIFIED YET on this board with this firmware. `battDv` and
 * the raw count `adc05_UBAT` are both published, so one reading against a
 * multimeter closes it - and if it does not close, the raw count says whether
 * the fault is the divider or the scaling, which is the whole reason both are
 * on the same dialog.
 *
 *   A2L quantisation                SAME-FAMILY ECU REFERENCE. A COMPU_METHOD
 *                                   is a platform property, not a per-binary
 *                                   address, so the pairing rule does not bite
 *   the arithmetic closing on 12.9 V PHYSICAL, one bench observation
 *   the divider on the A1146 board  NOT PROVEN - one meter reading settles it
 */
#define TGT_ADC_BATT_FS_DV    180  /* 1023 cnt = 18.0 V [same-family A2L] */
#define TGT_ADC_CH_COUNT      16

/* ================================================ board output catalogue ==
 *
 * WHAT EXISTS ON THIS BOARD [BOSCH-PM, ME7.1.1 columns]. Which output drives
 * which cylinder is a TunerStudio setting, not a build-time fact.
 *
 *   ignition   ZDG1 P2.0/CC0   ZDG2 P2.1/CC1   ZDG3 P2.2/CC2   ZDG4 P2.3/CC3
 *              ZDG5 P2.4/CC4   ZDG6 P2.5/CC5   ZDG7 P2.6/CC6   ZDG8 P2.7/CC7
 *   injectors  EV1 P7.6/CC30   EV2 P7.5/CC29   EV3 P7.4/CC28   EV4 P8.7/CC23
 *              EV5 P8.6/CC22   EV6 P8.5/CC21   EV7 P8.4/CC20   EV8 P8.3/CC19
 *   throttle   DVE1 P7.2/POUT2   DVE2 P7.7/CC31   EGENFR P2.11   SF P3.15
 *   cam sol.   NWS1 P7.0/POUT0   NWS2 P7.1/POUT1
 *   crank      KWDG  P2.15/CC15  and  P3.0/T0IN   (both, on this board)
 *   cam        NWDG1 P2.8/CC8    NWDG2 P2.9/CC9
 *   CAN1       P4.5 RX / P4.6 TX      CAN2  P4.4 RX / P4.7 TX
 *   KL15STAT   P6.2                   NLEN_FR P3.12
 *
 * The first four ignition and injector channels are the SAME PINS as the
 * 4B0906018DC ME7.5 board. That is not a coincidence and it is the whole
 * reason the port is a configuration change: it is one Bosch platform.
 *
 * hc_hal_outputs_safe() in startup releases every one of these pins (high
 * impedance) before anything else runs. A build with HANICORE_BENCH_SAFE
 * defined (not the default) leaves the output backends as counting no-ops.
 */
#define TGT_N_IGN             8
#define TGT_N_INJ             8

/* ======================================================= the status word ==
 * One 16-bit summary for the TunerStudio front page. Counters answer "how
 * many"; this answers "what is it doing right now". */
#define HC_ST_ARMED           0x0001u  /* retired (V84), never set           */
#define HC_ST_BENCHSAFE       0x0002u  /* HANICORE_BENCH_SAFE build only     */
#define HC_ST_TICK            0x0004u  /* the 1 ms tick is running           */
#define HC_ST_RXTICK          0x0008u  /* the serial drain tick is running   */
#define HC_ST_ASIC_INIT       0x0010u  /* SSC configured                     */
#define HC_ST_ASIC_START      0x0020u  /* startup frame accepted             */
#define HC_ST_ASIC_RUN        0x0040u  /* runtime frames flowing             */
#define HC_ST_ASIC_ERR        0x0080u  /* checksum, class or timeout         */
#define HC_ST_SETUPFAULT      0x0100u  /* the page does not describe an engine */
#define HC_ST_RAMBAD          0x0200u  /* the external SRAM probe failed     */
#define HC_ST_RXLOSS          0x0400u  /* a serial byte was lost             */
#define HC_ST_BADVEC          0x0800u  /* an interrupt nobody asked for      */
#define HC_ST_TUNESTORED      0x1000u  /* the page came from battery SRAM    */
#define HC_ST_WDT             0x2000u  /* the on-chip watchdog is being fed  */

/* Every claimed interrupt handler starts with this. During the boot probe it
   makes the handler name itself instead of doing its own job, so a receive
   interrupt landing on a trap this firmware has ALREADY claimed cannot hide.
   Outside the probe it is one volatile byte test. */
#define HC_PROBE_CLAIM(trap)  do {                                          \
        if (hc_s0r_learn) {                                                 \
            hc_s0r_trap = (unsigned char)(trap);                            \
            hc_probe_sink = (unsigned char)S0RBUF;                          \
            S0RIC &= 0x7F;                                                  \
            return;                                                         \
        }                                                                   \
    } while (0)

extern volatile unsigned char hc_s0r_learn;
extern volatile unsigned char hc_s0r_trap;
extern volatile unsigned char hc_probe_sink;

/* ================================================ boot-stage numbering ====
 * Published as bootStage AND written into the reset log, so ONE bench reading
 * says how far the last boot got even if it never got far enough to answer
 * TunerStudio. See docs/ARCHITECTURE.md. */
#define BOOT_ENTRY            1
#define BOOT_RAM              2
#define BOOT_WDT              3
#define BOOT_SERIAL           4
#define BOOT_CONFIG           5
#define BOOT_TIMERS           6
#define BOOT_PROBE            7
#define BOOT_BANNER           8
#define BOOT_IRQ              9
#define BOOT_ASIC             10
#define BOOT_LOOP             11

#endif /* HCTARGET_H */
