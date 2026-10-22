/*
 * hcnvm.c - READ hcnvm.h FIRST. The safety argument is there and it is the
 * reason every line below is shaped the way it is.
 *
 * The short version: two flash slots, a record with a commit marker written
 * last, a snapshot taken at the instant of Burn, and a commit that runs in the
 * boot path and is built to be RESTARTED by the monitoring module rather than
 * to outrun it.
 */
#include <reg167.h>
#include "hctarget.h"
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hc_config_manager.h"
#include "hc_validation.h"
#include "hcts.h"
#include "hcnvm.h"
#include "hc_validation.h"   /* the SEMANTIC half of the LKG walk-back */
#include "hcburnforensics.h"
#include "hcasic.h"
#include "hcasicstart.h"
#include "hctrigger.h"
#include "hcliveforensics.h"
#include "hcdeadline711.h"

extern unsigned int hc_tick_ms;

/* ============================== NOT ONE BYTE OF THIS MODULE IS IN NEAR RAM ==
 *
 * Every mutable value belongs to the external SRAM block declared as
 * TGT_RAM_NVM, and the published values are ACCESSOR FUNCTIONS rather than
 * globals. Two reasons, and the second is the better one:
 *
 *   near RAM on this target is 1792 bytes and near_ram_hazard_proof keeps a
 *   192-byte engineering reserve for the engine subsystems still to land. This
 *   module's first version took 45 of it for state that runs at boot and once
 *   per Burn - cold by this project's own definition, exactly like hc_dbw.c's
 *   controller state and hc_plan.c's staging table, both of which were moved
 *   out for the same measured reason;
 *
 *   and the control block HAS to survive a reset anyway. A near-RAM mirror of
 *   it would have been a SECOND COPY of the same facts, which is the shape
 *   this project has been bitten by four times. There is one copy, it is in
 *   the store that has to keep it, and it is CRC-protected.
 */
/* ===================================================== the memory map ==== */
/* Every address here comes from hctarget.h. Nothing in this file invents one -
   see feedback_one_place_for_shared_layout. */
#define NVM_CB       (TGT_EXTRAM_BASE + TGT_RAM_NVM)
#define NVM_STAGE    (TGT_EXTRAM_BASE + TGT_RAM_FLASHBUF)
#define NVM_RT       (TGT_EXTRAM_BASE + TGT_RAM_FLASHRT)

/* The programmer is copied to a FIXED address and entered with a literal
   JMPS, because the inline assembler takes a number and not a macro. These
   three lines are what keeps the literal and the declared map in agreement -
   the same guard the ME7.5 hcflash.c carries, and for the same reason. */
#if (TGT_EXTRAM_BASE != 0x380000uL)
#error "the JMPS below says segment 0x38 - fix both or neither"
#endif
#if (TGT_RAM_FLASHRT != 0x6000uL)
#error "the JMPS below says offset 0x6000 - fix both or neither"
#endif
#if (TGT_RAM_FLASHRT_LIMIT < 0x400uL)
#error "the relocation copies 1024 bytes; the region must hold them"
#endif

/* ------------------------------------------------------- the CONTROL BLOCK
 *
 * In the battery-backed SRAM, because it has to survive the reset the whole
 * design expects. All of bytes 0..13 are CRC-protected; byte 17 is the
 * handover FROM the RAM-resident programmer and is deliberately outside the
 * CRC, so that the programmer never has to compute one. A programmer that had
 * to run a CRC would need a loop over 4 KB of flash it is not allowed to read.
 *
 *    0   4   magic 'HCND'
 *    4   1   state          HCNV_ST_*
 *    5   1   phase          HCNV_PH_*
 *    6   1   cell           the TARGET of a commit, 0..TGT_FLASH_CELLS-1
 *    7   1   errcode        HCNV_ERR_*
 *    8   4   generation     the generation being written
 *   12   2   attempts
 *   14   2   crc16 over bytes 0..13
 *   ---- outside the CRC ----
 *   17   1   result         written by the PROGRAMMER
 *
 * THE MAGIC IS 'HCND' AND NOT 'HCNC', AND THAT IS LOAD-BEARING. A V37 ECU can
 * be sitting with a sealed 'HCNC' block that says COMMITTING, a target SLOT
 * number in byte 6 and do_erase in byte 16. Byte 6 now means a CELL and byte
 * 16 means nothing, so a build that accepted the old block would act on a
 * commit intent it cannot read. It does not: cb_load() sees a magic it does
 * not know, wipes both blocks, and the tuner presses Burn again.
 *
 * BYTE 16 IS GONE WITH THE ERASE. There is no runtime erase any more - see
 * hctarget.h - so there is nothing for a do_erase flag to say.
 */
#define CB_MAGIC      0uL
#define CB_STATE      4uL
#define CB_PHASE      5uL
#define CB_CELL       6uL
#define CB_ERR        7uL
#define CB_GEN        8uL
#define CB_ATTEMPTS  12uL
#define CB_CRC       14uL
#define CB_CRCLEN    14u
#define CB_RESULT    17uL
#define CB_POS       18uL
#define CB_LEN       20u

#define NVM_CB_MAGIC  0x48434E44uL      /* 'HCND' */

/* ------------------------------------------------------- the WORKING block
 *
 * Everything the module derives at boot and everything it publishes, at
 * NVM_CB + 32. NOT CRC-protected and it does not need to be: nvm_scan()
 * recomputes all of it from the flash device on every single boot, so a
 * corrupted byte here survives exactly one instruction. The two that DO carry
 * over - the commit counter and the arming timestamp - are zeroed together
 * with everything else whenever the control block fails its own CRC, which is
 * what a cold SRAM looks like.
 *
 * IT MUST STAY 32 BYTES. The RAM-probe block is at NVM_CB + 64 and the two
 * per-slot generations that used to live at 12 and 16 are gone with the
 * two-slot model: there are sixteen cells now, and carrying sixteen 32-bit
 * generations here would need 64 bytes this block does not have. One ACTIVE
 * generation is the only one anything asks for.
 *
 *   32  1  source        HCNV_SRC_*
 *   33  1  nonvol        1 when a committed record really is in the device
 *   34  1  scan_why      why NO cell was usable
 *   35  1  cell          the ACTIVE cell, 0..15, or 0xFF for none
 *   36  1  free          cells still blank
 *   37  1  slot          HCNV_SLOT_* - which SECTOR the active cell is in
 *   38  2  generation    low word of the ACTIVE record's generation
 *   40  2  commits       successful commits since standby power was last lost
 *   42  2  arm_ms        when the commit was armed
 *   44  4  best_gen      the ACTIVE record's full generation
 *   48  1  next          the next blank cell, or 0xFF when the store is full
 *   49  1  -
 *   50  2  reject        bitmask of cells whose PAYLOAD CRC failed this boot
 *   52  4  last_gen      the generation cell_head() last read
 *   56  2  staging step, position, rolling CRC, and the page revision it
 *   58  2  started from - so an edit that lands mid-staging restarts it
 *   60  2
 *   62  2
 */
#define NVW_BASE      (NVM_CB + 32uL)
#define W_SOURCE       0u
#define W_NONVOL       1u
#define W_SCANWHY      2u
#define W_CELL         3u
#define W_FREE         4u
#define W_SLOT         5u
#define W_GENERATION   6u
#define W_COMMITS      8u
#define W_ARM_MS      10u
#define W_BEST_GEN    12u
#define W_NEXT        16u
#define W_REJECT      18u
#define W_LAST_GEN    20u
/* The staging cursor. A Burn no longer does its work inside the command
   handler - see hc_nvm_request(). */
#define W_STG_STEP    24u   /* HCNV_STG_*                                    */
#define W_STG_POS     26u   /* how far through the 4096-byte payload         */
#define W_STG_CRC     28u   /* the rolling payload CRC                       */
#define W_STG_GEN      30u   /* cfg_writes + cfg_burns when staging began     */
/* V45 deliberately keeps the working block at 32 bytes.  V44 placed its
   trace at 38:6840 and overlapped the RAM-probe magic; forensic trace now
   lives only in the separate retained record at 38:68A0. */
#define W_LEN               32u

/* V47 transient live-burn qualification data.  This is intentionally outside
   the sealed commit control block: it is diagnostic/admission state, never a
   fact used to select a calibration after reset.  It occupies 48 bytes before
   the existing forensic region at NVM_CB+160. */
#define NVM_LIVE       (NVM_CB + 112uL)
#define L_MAGIC          0u
#define L_OWNER          4u
#define L_ADMISSION      5u
#define L_PAUSE          6u
#define L_WINDOWS_OK     8u
#define L_WINDOWS_NO    10u
#define L_WRITER_ENT    12u
#define L_WRITER_OK     14u
#define L_WRITER_FAIL   16u
#define L_VECTOR_BAD    18u
#define L_MASK          20u
#define L_PENDING_BEF  22u
#define L_PENDING_AFT  24u
#define L_HORIZON_US   26u
#define L_DEADLINE_MS  28u
#define L_PREDICT_MS   30u
#define L_MAX_WR_US    32u
#define L_TIMEOUTS     34u
#define L_MAGIC_VALUE  0x48434C42uL /* HCLB */

/* ================================================ THE RECLAIM CONTROL BLOCK ==
 *
 * Sixteen never-erased cells made the store terminal: HCNV_ERR_FULL, and the
 * only way back was a 1 MiB reflash. V53 moved the store above the bootrom's
 * page record, which is what makes erasing it survivable; this block is what
 * drives the erase.
 *
 * It lives in the battery-backed block with everything else this module owns,
 * so a reset mid-erase is a fact the next boot can read rather than infer.
 * BUT NOTHING DEPENDS ON IT BEING RIGHT: an interrupted erase is detected from
 * the DEVICE - a sector that is neither blank nor holds a valid record - and
 * re-erased. The block is for diagnosis and for bounding retries, not for
 * correctness. That distinction is the same one hc_nvm_boot() already makes.
 *
 * WHERE IT GOES, AND THE ONE THAT WAS WRONG. TGT_RAM_NVM is 256 bytes and it
 * is already crowded:
 *
 *     +0    NVM_CB      20    the sealed commit control block
 *     +32   NVW_BASE    32    the working block, cleared at every scan
 *     +64   NVM_RP      14    the RAM-probe result, survives a scan
 *     +80   NVM_DG      22    the programmer's diary
 *     +112  NVM_LIVE    36    live-burn admission counters
 *     +160  FORENSICS   64    hcburnforensics, and it COMPILE-TIME ASSERTS
 *                             that it is at exactly TGT_RAM_NVM + 0xA0
 *     +224  NVM_ER      24    this block
 *
 * The first version of this put NVM_ER at +160, straight on top of the V45
 * forensic record - the two would have overwritten each other every Burn. The
 * assert below is why that cannot happen again, and it is the same idiom the
 * RAM-probe block already uses. ONE PLACE FOR A SHARED LAYOUT is the rule; a
 * new block that does not state its neighbours is how it gets broken. */
#define NVM_ER         (NVM_CB + 224uL)
#define ER_MAGIC         0u   /* 4 : 'HCER'                                  */
#define ER_OP            4u   /* 1 : HCNV_EOP_*, what the next slice does    */
#define ER_SECTOR        5u   /* 1 : store sector being erased, CELL_NONE    */
#define ER_STATE         6u   /* 1 : HCNV_ER_*                               */
#define ER_RESULT        7u   /* 1 : HCNV_ERR_* from the last slice          */
#define ER_SLICES        8u   /* 2 : resume/suspend cycles, this erase       */
#define ER_TRIES        10u   /* 2 : erases attempted on this sector         */
#define ER_STARTMS      12u   /* 2 : main-loop ms when this erase began      */
#define ER_RECLAIMS     14u   /* 2 : sectors reclaimed, this battery         */
#define ER_FAILS        16u   /* 2 : erases abandoned, this battery          */
#define ER_SLICETK      18u   /* 2 : slice length in T7 TICKS, not us - a    */
                              /*     runtime US_TO_TICKS() is a 32-bit mul   */
                              /*     and div, i.e. a CALL, and the eraser    */
                              /*     may not call anything. Converted once,  */
                              /*     in ordinary C, in er_begin().           */
#define ER_LASTDQ       20u   /* 2 : the last status word the poll read      */
#define ER_LASTMS       22u   /* 2 : wall time the last completed erase took */
#define ER_LOADED       24u   /* 1 : HCNV_PAY_* currently in the shared slot  */
#define ER_LEN          26u
#define ER_MAGIC_VALUE  0x48434552uL   /* 'HCER' */

#if ((224uL + ER_LEN) > TGT_RAM_NVM_LIMIT)
#error "the reclaim control block does not fit TGT_RAM_NVM"
#endif
/* The V45 forensic record sits at TGT_RAM_NVM + 0xA0 and is HCBF_LEN = 64
   bytes, so it ends at +0xE0 = +224. hcburnforensics.c COMPILE-TIME ASSERTS
   its own base, so if it ever moves, that assert fires there; this one keeps
   THIS block from being the thing that moved onto it. Neither symbol is
   visible in this translation unit, which is why both are literals - and why
   they are written down together. */
#if (224uL < (0xA0uL + 64uL))
#error "the reclaim control block overlaps the V45 forensic record"
#endif

/* What the relocated routine should do on this entry. */
#define HCNV_EOP_START   0u   /* issue the six-cycle sector erase            */
#define HCNV_EOP_RESUME  1u   /* resume a suspended erase                    */

/* Where a reclaim has got to. */
#define HCNV_ER_IDLE     0u
#define HCNV_ER_RUNNING  1u   /* suspended between slices, sector indeterminate */
#define HCNV_ER_DONE     2u
#define HCNV_ER_FAILED   3u

/* WHICH PAYLOAD IS CURRENTLY IN THE RELOCATION SLOT.
 *
 * There is ONE slot and two routines, and they are never needed at the same
 * instant - a reclaim finishes before a Burn programs. Sharing the slot is
 * what lets fl_enter() stay BYTE-IDENTICAL to the V50/V52 window that is
 * physically proven: it still does one CALLS to one address, and the selector
 * lives in fl_prepare() instead. Re-preparing costs a 1024-byte SRAM copy. */
#define HCNV_PAY_WRITER  0u
#define HCNV_PAY_ERASER  1u

/* THE AMD ERASE SEQUENCE, and the two commands that make it liveable.
 *
 * Six write cycles: AA 55 80 AA 55 30, the last to the sector address. Read
 * straight off C167BootTool/Drivers/A29fx00Bx.a66, which is the
 * working routine for this family, and confirmed against the Am29F800B
 * datasheet's command table.
 *
 * ERASE SUSPEND IS NOT AN OPTIMISATION HERE, IT IS THE ONLY WAY THIS WORKS.
 * A sector erase is typ 1.0 s and max 15 s, and that figure EXCLUDES the
 * mandatory pre-program pass. The CPU cannot fetch from this device while it
 * is busy, so without suspending, the S5500 raster goes unserved for seconds
 * and the monitoring module asserts SWRST_SM - which on this board is wired to
 * the flash's own RESET pin and ABORTS THE ERASE. An un-suspended erase can
 * therefore never complete: every attempt is killed at ~310-420 ms and makes
 * no progress. That is why "erase at boot and accept the reset" is not an
 * option on this ECU, and it is why the plan that said so was wrong.
 *
 * Erase Suspend (B0) takes at most 20 us to take effect, after which the CPU
 * may read - and even program - any sector that is not the one being erased.
 * Erase Resume (30) continues it. Addresses are don't-care for both. */
#define FL_ERASE_SETUP   0x0080u
#define FL_ERASE_SECTOR  0x0030u
#define FL_ERASE_SUSPEND 0x00B0u
#define FL_ERASE_RESUME  0x0030u

/* How long one slice keeps the device busy with interrupts masked. The writer
   already holds a window of up to HCNV_POLL_US for a single word, so this is
   the same order and the same admission decides it.

   THE ONE NUMBER THE DATASHEET DOES NOT GIVE is how long an erase must run
   between resumes to make progress: AMD bounds the suspend LATENCY (20 us) but
   never the resume-to-suspend interval. So this is instrumented rather than
   asserted - ER_SLICES and ER_LASTMS are published, and the first real erase
   on the bench says whether it is enough. If it is not, the symptom is
   explicit (slices climbing with no completion) and the fix is this constant,
   not a redesign. */
#define HCNV_ERASE_SLICE_US   1000u
#define HCNV_ERASE_SUSPEND_US   25u   /* 20 us datasheet max, rounded up     */
/* An erase that will not finish must stop rather than hold the store hostage.
   At ~1 ms a slice a 15 s worst-case sector needs 15000; this is generous
   against that and still bounded. */
#define HCNV_ERASE_MAX_SLICES 40000u
#define HCNV_ERASE_MAX_TRIES      3u

/* Reclaim when free cells fall to this. One sector's worth, so a reclaim is
   started a whole sector before the store could run out and is NEVER on the
   critical path of a Burn. */
#define HCNV_RECLAIM_LOW      TGT_FLASH_CELL_PAGES

/* ================================ V50: MASK xxIE, NEVER TOUCH xxIR =========
 *
 * V48 and V49 saved each interrupt-control register, wrote the WHOLE register
 * to 0, and restored the WHOLE saved word afterwards.  On 2026-09-11 that was
 * physically proven to DESTROY every request that became pending inside the
 * writer window: the V49 record has lost_or = 3 (CC7 | T8), the tick stopped
 * permanently because hc_tick_isr() reloads T8 in software, and 25.80 ms of
 * S5500 silence later the CPU took an external NMI.
 *
 * THE MANUAL SAYS SO IN ONE SENTENCE.  C167CR Derivatives User's Manual V3.1,
 * 2000-03, section 5, register xxIC (xxIR is typed `rwh`):
 *
 *     "Modifying the Interrupt Request flag via software causes the same
 *      effects as if it had been set or cleared by hardware."
 *
 * So a stale IR = 0 in a restored word is not a no-op - it is an explicit
 * CANCEL, indistinguishable from the hardware clearing the request.
 *
 * xxIC layout, confirmed three ways: the UM register diagram (bit 7 xxIR,
 * bit 6 xxIE, bits 5..2 ILVL, bits 1..0 GLVL), this project's own
 * hardware-proven HC_IC(ilvl,glvl) = 0x40 | (ilvl<<2) | glvl, and the V49
 * physical record (save_cc7ic 0x72 = IE | ILVL 12 | GLVL 2).
 *
 * THE FIX IS THEREFORE: touch ONLY xxIE.
 *   mask     X &= HCNV_IE_CLR    Keil emits  AND X,#0FFBFH  - bits 7..5..0 kept
 *   restore  X |= (saved & HCNV_IE_BIT)  Keil emits  OR X,Rn - nothing cleared
 * Neither instruction can ever write a 0 into bit 7, so a pending request
 * cannot be destroyed, and ILVL/GLVL are never disturbed either - they are no
 * longer cleared, so they no longer need restoring.
 *
 * WHY NOT THE BIT INSTRUCTIONS.  Infineon Errata Sheet SAB 88C166 CC/ES-CC
 * Rel 1.0, Problem 25 "Bit Instructions on Interrupt Control Registers", warns
 * that BCLR/BSET/BFLDL/BFLDH/JBC/JNBS/BMOV/BAND/BOR/BXOR on xxIC can
 * erroneously vector to 100h.  Its Workaround 1 is literally "use instructions
 * with data type BYTE or WORD to access interrupt control registers xxIC".
 * Keil C166 7.53 compiles the two lines above to exactly that - single
 * word-typed AND/OR instructions, no bit instruction anywhere - which was
 * verified by compiling a probe and reading the generated object code, not
 * assumed.  tools/me711_v50_ir_preserve_proof.py re-proves it on the FINAL
 * LINKED IMAGE, because that is the only artefact that counts.
 *
 * WHY NOT IEN.  The same UM section: "Interrupt Enable bit IEN globally
 * enables or disables PEC operation and the acceptance of interrupts".  This
 * window deliberately lets an in-flight PEC keep moving the S5500 frame, so
 * IEN = 0 is not available as the masking primitive here. */
#define HCNV_IE_BIT     0x0040u   /* xxIE  - the only bit this code may write */
#define HCNV_IE_CLR     0xFFBFu   /* ~xxIE - preserves xxIR, ILVL and GLVL    */
#define HCNV_IR_BIT     0x0080u   /* xxIR  - READ ONLY for this module        */

#define HCNV_OWNER_NONE 0u
#define HCNV_OWNER_NVM  1u
#define HCNV_ADMIT_READY 1u
#define HCNV_ADMIT_ENGINE 2u
#define HCNV_ADMIT_ASIC 3u
#define HCNV_ADMIT_PEC 4u
#define HCNV_ADMIT_DEADLINE 5u

#define CELL_NONE     0xFFu

/* The staging step machine. Every step is BOUNDED so that no single main-loop
   pass can starve the S5500 raster - which is exactly what the first version
   did, and what the bench found. */
#define HCNV_STG_IDLE     0u
#define HCNV_STG_COMMIT   1u   /* validate DESIRED and commit the standby page */
#define HCNV_STG_COPY     2u   /* the payload, HCNV_STG_CHUNK bytes at a time  */
#define HCNV_STG_FINISH   3u

/* Bytes copied and CRC'd per main-loop pass. MEASURED, not chosen: 256 added
   about 6 ms to a pass whose baseline is already several, which is most of the
   S5500 raster on its own. 64 costs about 1.5 ms, and the whole 4096-byte
   payload is 64 passes - a few tens of milliseconds of wall time, and never
   one long stall. */
#define HCNV_STG_CHUNK   64u

#if ((32uL + W_LEN) > TGT_RAM_NVM_LIMIT)
#error "the NVM control and working blocks do not fit TGT_RAM_NVM"
#endif

/* ------------------------------------------------- the RAM-probe block ----
 * DELIBERATELY OUTSIDE THE WORKING BLOCK, because nvm_scan() clears that at
 * every boot and this has to survive one. If the board cannot execute from
 * external SRAM the CPU does not come back from the probe, and RP_STATE
 * reading RUNNING after the reset IS the diagnosis. It lives in the
 * battery-backed TC55257 like everything else here. */
#define NVM_RP        (NVM_CB + 64uL)
#define RP_MAGIC       0u   /* 4 : HCRP                                      */
#define RP_STATE       4u   /* 1 : HCNV_RP_*                                 */
#define RP_RUNS        6u   /* 2 : probes attempted, ever                    */
#define RP_SEED        8u   /* 2 : the seed this run used                    */
#define RP_RESULT     10u   /* 2 : what the routine in SRAM computed         */
#define RP_SIG        12u   /* 2 : 0x5A3C, written by the routine LAST       */
#define RP_LEN        14u

#define NVM_RP_MAGIC  0x48435250uL      /* HCRP */

#if ((64uL + RP_LEN) > TGT_RAM_NVM_LIMIT)
#error "the RAM-probe block does not fit TGT_RAM_NVM"
#endif

/* ------------------------------------------- the PROGRAMMER'S DIARY block --
 *
 * WHY IT IS A BLOCK OF ITS OWN AND NOT PART OF THE WORKING BLOCK: nvm_scan()
 * clears the working block at every boot, and the whole value of these numbers
 * is that they survive one. They are written by the RAM writer itself, in
 * external SRAM, while it is programming - so they cost no near RAM and no
 * flash read, and hc_nvm_payload() may touch them under its own rule.
 *
 * Nothing here is ever read back as truth about the calibration. It is
 * evidence for a human, and it is deliberately outside the record, outside the
 * control block's CRC, and outside anything a boot decision depends on. */
#define NVM_DG        (NVM_CB + 80uL)
#define DG_MAGIC       0u   /* 4 : 'HCDG'                                    */
#define DG_WORD        4u   /* 2 : the record word that would not take       */
#define DG_EXP         6u   /* 2 : the datum it was given                    */
#define DG_GOT1        8u   /* 2 : the first read the poll gave up on        */
#define DG_GOT2       10u   /* 2 : the second                                */
#define DG_FLAGS      12u   /* 2 : low HCNV_PF_*, high worst attempt count   */
#define DG_RETRIES    14u   /* 2 : command sequences re-issued, this commit  */
#define DG_POLLMIN    16u   /* 2 : shortest word poll seen, T7 ticks         */
#define DG_POLLMAX    18u   /* 2 : longest                                   */
#define DG_TRY        20u   /* 2 : attempts spent on the CURRENT word        */
#define DG_LEN        22u

#define NVM_DG_MAGIC  0x48434447uL      /* HCDG */

#if ((80uL + DG_LEN) > TGT_RAM_NVM_LIMIT)
#error "the programmer's diary block does not fit TGT_RAM_NVM"
#endif

/* ------------------------------------------------------------- the RECORD
 *
 *    0   4   magic 'HCN1'
 *    4   4   HC_CFG_LAYOUT_ID
 *    8   2   HC_CFG_VERSION
 *   10   2   HC_CFG_SIZE
 *   12   4   generation
 *   16   2   header CRC16-CCITT over bytes 0..15
 *   18   N   the 4096-byte page
 * 18+N   2   payload CRC16-CCITT
 * 20+N   4   COMMIT 'DONE'  <-- PROGRAMMED LAST
 *
 * Every offset is even, because a 29F800 in word mode programs words.
 */
#define REC_MAGIC     0u
#define REC_LAYOUT    4u
#define REC_VERSION   8u
#define REC_LENGTH   10u
#define REC_GEN      12u
#define REC_HCRC     16u
#define REC_HDRLEN   18u
#define REC_PAYLOAD  REC_HDRLEN
/* No casts in any of these: they are tested by #if below, and the
   preprocessor cannot evaluate a cast. */
#define REC_PCRC     (REC_HDRLEN + HC_CFG_SIZE)
#define REC_COMMIT   (REC_PCRC + 2)
#define REC_LEN      (REC_COMMIT + 4)

#define NVM_REC_MAGIC   0x48434E31uL    /* 'HCN1' */
#define NVM_REC_COMMIT  0x444F4E45uL    /* 'DONE' */

/* Words the programmer writes before the commit marker, and the marker's own
   two words. Derived, never written twice. */
#define REC_PROG_WORDS  (REC_COMMIT / 2)
#define REC_TOTAL_WORDS (REC_LEN / 2)

#if ((REC_LEN & 1) != 0)
#error "the record must be an even number of bytes - the device programs words"
#endif
#if (REC_LEN > TGT_RAM_FLASHBUF_LIMIT)
#error "the staged record does not fit in TGT_RAM_FLASHBUF"
#endif
#if (REC_HDRLEN != 18)
#error "hcnvm.h documents an 18-byte record header - keep them in step"
#endif

/* ============================== THE RECORD MUST FIT INSIDE ONE CELL BODY ===
 *
 * This is the guard that would have stopped 2026-09-05 at compile time. A cell
 * body is the middle of an 8 KiB bootrom-checksum page: it starts two bytes in
 * so the page's FIRST sampled word is never programmed, and it must end before
 * the page's LAST sampled word. Break either end and the next Burn changes the
 * 0x00803C program-page sum and the ECU stops booting its application.
 *
 * tools/me711_bootsum_proof.py asserts the same thing about the LINKED IMAGE
 * after a simulated commit, because a constant that is right is not evidence
 * that the code using it is. */
#if (REC_LEN > TGT_FLASH_CELL_BODY)
#error "the record does not fit inside one checksum page's cell body"
#endif
#if ((TGT_FLASH_CELL_OFF + TGT_FLASH_CELL_BODY) > (TGT_FLASH_PAGE - 2uL))
#error "a cell body would reach the page's last checksum-sampled word"
#endif
#if (TGT_FLASH_CELL_OFF < 2uL)
#error "a cell body would cover the page's first checksum-sampled word"
#endif
#if ((TGT_FLASH_CELL_OFF & 1uL) != 0uL)
#error "a cell body must be word aligned - the device programs words"
#endif

/* ------------------------------------------------------- the AMD command set
 * Byte addresses 0xAAA and 0x554 inside the segment-0x80 window, which is the
 * pair the other standalone ME7.4.4 uses on this ECU family and the pair Bosch
 * Motorsport's own programmer uses (as 0xAAAA / 0x5554 within its 64 KB). */
#define FL_UNLOCK1   0x00AAu
#define FL_UNLOCK2   0x0055u
#define FL_PROGRAM   0x00A0u
#define FL_RESET     0x00F0u

/* ------------------------------------------- HOW MUCH WORK, AND FOR HOW LONG
 *
 * TWO SEPARATE BOUNDS, because they protect two different things, and the
 * first version of the V40 commit conflated them into one chunk per pass.
 *
 * HCNV_PROG_CHUNK bounds THE INTERRUPT-OFF WINDOW. fl_enter() clears IEN
 * around the RAM writer because the AM29F800BB is single-bank: while a word is
 * programming, every read of the device - including a vector fetch - returns
 * status instead of memory. The datasheet's word-program time is 11 us typical
 * and 360 us maximum, so eight words is 88 us typically and 2.88 ms in the
 * pathological case, against a 10 ms supervision raster. Sixteen would have
 * been 5.76 ms of that raster in the same case, which is more than this
 * project is willing to take from UMKOM.
 *
 * HCNV_PASS_US bounds HOW LONG hc_nvm_service() KEEPS THE MAIN LOOP.  The
 * staging path yields between chunks, but that is a second line of defence,
 * not permission to retain the loop for a whole S5500 raster: a timer edge can
 * land just after a yield.  Keep the complete service slice below one quarter
 * of the 10 ms supervision period so the ordinary main-loop service remains
 * available even in that alignment.  Interrupts are ON between chunks:
 * fl_enter() restores the state it found.
 *
 * WHY THIS IS SAFE TO HOLD THE LOOP FOR: a commit only ever begins with rpm 0,
 * no crank edges, no bench output running and a settled page. There is nothing
 * time-critical left in the loop to starve.
 *
 * AND WHY IT IS WORTH DOING AT ALL: one chunk per pass at the ~10 ms loop
 * cadence made a Burn take about 2.7 SECONDS end to end. The reply is now
 * deferred until the commit finishes, so that number is what TunerStudio has
 * to wait for on a single command - and a TunerStudio that gives up before it
 * arrives loses precisely the session this whole design exists to keep. */
#define HCNV_PROG_CHUNK  1u
#define HCNV_PASS_US      2500u

/* ----------------------------------------- HOW LONG ONE WORD MAY BE POLLED
 *
 * V40 SPUN 60000 TIMES, WHICH IS NOT A BOUND - it is about 30 ms of the main
 * CPU with IEN clear, ten times the supervision raster and 83 times the
 * datasheet's worst word. The note above claims the interrupt-off window is
 * bounded by HCNV_PROG_CHUNK at 2.88 ms; with a 60000-iteration poll THAT
 * CLAIM WAS FALSE on the one path where it mattered - the failure path - and
 * the first real Burn on the bench took exactly that path, five times.
 *
 * The bound is now a TIME, read from T7, and it comes from the device:
 * tWHWH1 is 11 us typical and 500 us maximum in the final AM29F800B data
 * sheet, so 1 ms is twice the worst word the part is allowed to take.  V48's
 * independently admitted one-word window protects this complete timeout path
 * with TGT_LIVE_WORD_GUARD_US; the timeout is intentionally longer than the
 * device limit so a marginal part fails visibly and returns to read-array.
 *
 * T7 is an SFR read: no call, no flash access, legal inside the RAM writer. */
#define HCNV_POLL_US     1000u
#define HCNV_POLL_TICKS  US_TO_TICKS(HCNV_POLL_US)

/* ==================================== V42: WHAT V41 GOT WRONG, AND IT WAS
 *                                      NOT THE BUS SEQUENCE
 *
 * V41 was flashed and its first Burn failed exactly as V40's had - "a word
 * would not program" - consuming cells 0 and 1 at words 477 and 864. So the
 * fifth-write-cycle explanation was at best incomplete, and the V41 bootmode
 * readback closes several doors that were open before it:
 *
 *   - the failing word is STILL completely erased, no word is skipped, no word
 *     is partially programmed, and NOTHING outside a cell body changed. The
 *     address was right, the cursor was right, and no program pulse was
 *     applied ANYWHERE in the device. The command sequence was not accepted;
 *   - V40 polled such a word for about 35 ms - 60000 iterations, a hundred
 *     times the datasheet's worst word - before giving up. The part was not
 *     slow. It was not listening;
 *   - and the writer that fails is BUS-IDENTICAL to the writer that works.
 *     V39 programmed 4120 words on this ECU without one failure, issuing the
 *     same four write cycles and using a WEAKER single-read poll.
 *
 * What is left is the ENVIRONMENT. V39 programmed a whole record in one
 * uninterrupted RAM call at boot, before IEN had ever been set, and ended in
 * SRST. V40 and V41 program eight words at a time, 258 times, with the main
 * loop, the supervision raster, the K-line and the ADC running in between.
 * That is the only difference the evidence leaves standing, and no bootmode
 * dump can say WHICH transient consequence of it refuses a command sequence
 * about once in eight hundred words.
 *
 * SO V42 STOPS TRYING TO OUTGUESS IT AND DOES THE TWO THINGS THAT ARE RIGHT
 * WHATEVER THE ANSWER TURNS OUT TO BE.
 *
 * 1. IT RE-ISSUES THE COMMAND SEQUENCE ONLY AFTER PROVING THAT IT IS LEGAL.
 *    NOR programming only clears bits. Before a retry the RAM writer reads the
 *    target twice after the prior F0: an erased word, a word partially changed
 *    ONLY towards its expected datum, or the datum itself is safe. Any bit that
 *    is zero in flash while the datum asks for one is an unexpected 0->1
 *    request, is NOT retried, and fails visibly. This is the distinction between
 *    idempotence and merely hoping a second command is harmless.
 *
 *    THE RETRY IS NOT A LOOP INSIDE THE RAM WRITER. The writer resets the
 *    device, leaves the cursor where it is, and RETURNS. The retry happens on
 *    the NEXT pass - interrupts on in between, raster serviced, and the part
 *    left completely alone for a whole main-loop iteration rather than for a
 *    few microseconds. It also leaves the interrupt-off window exactly what it
 *    was: seven good words plus one bounded poll.
 *
 *    AND IT IS BOUNDED AND COUNTED, so it cannot turn a dead device into a
 *    green light: HCNV_PROG_TRIES attempts on one word and the Burn fails with
 *    the whole context on the screen.
 *
 * 2. IT WRITES DOWN WHAT IT SAW - see hcnvm.h. A bench Burn now MEASURES the
 *    refusal rate instead of a third readback inferring it.
 *
 * One thing is tightened on the success path, at the cost of two reads and no
 * write cycles: after the poll matches, the device is left ALONE for
 * HCNV_SETTLE_TICKS with no bus cycle of any kind, and then read twice more. A
 * match that was really status which happened to equal the datum cannot
 * survive that - and hc_nvm_poll_min() says whether such a thing happens at
 * all. It also lengthens the quiet interval before the next unlock cycle,
 * which is the direction every piece of evidence in this file points. */
#define HCNV_PROG_TRIES   12u  /* total program commands allowed per word */
#define HCNV_SETTLE_US    8u
#define HCNV_SETTLE_TICKS US_TO_TICKS(HCNV_SETTLE_US)

/* HOW LONG THE WRITER WILL WAIT FOR THE PART TO COME BACK TO READ-ARRAY MODE
 * BEFORE IT RETURNS INTO FLASH AT ALL.
 *
 * The failure path issues FL_RESET. A write to an AM29F800B that has not
 * released is IGNORED - that is this project's own physically established V40
 * root cause, written down in the project rules - so issuing the command proves
 * nothing, and the instruction immediately after the RETS is fetched out of
 * the very device the command was meant to quieten. 2000 us is about 5.5x the
 * datasheet's 360 us worst-case word and well inside T7's 52.5 ms wrap, so the
 * unsigned subtraction cannot alias. A part still answering with status after
 * that is a part this CPU cannot execute from at all, and the bound exists to
 * make that outcome NAMED (HCNV_PF_STUCK) rather than a hang.
 */
#define HCNV_IDLE_US     2000u
#define HCNV_IDLE_TICKS  US_TO_TICKS(HCNV_IDLE_US)

/* Returned in CB_RESULT: no progress and no failure - come back and try the
   same word again. Distinct from every HCNV_ERR_* value on purpose. */
#define HCNV_RES_RETRY    0xFEu

/* THE DEVICE POINTER IS VOLATILE, AND THAT IS LOAD-BEARING.
 *
 * The poll below requires TWO SEPARATE READS of the same address to agree.
 * Without volatile, Keil is entitled to perform one read and reuse it - which
 * would silently turn the two-read rule back into the single-read data poll
 * that failed on the bench. tools/me711_flash_bus_proof.py reads the
 * generated listing and counts the reads; it does not assume them. */
#define FLW(a)  ((unsigned int volatile huge *)(a))

#define SRAMB(a)  ((unsigned char huge *)(a))
#define SRAMW(a)  ((unsigned int huge *)(a))

/* =========================================================== CRC16-CCITT ==
 *
 * NIBBLE-WISE, and that is not decoration. A burn stages 4096 bytes and
 * CRC-checks them inside the TunerStudio command handler, and the bitwise form
 * costs ~32768 iterations there - measurable against the 10 ms supervision
 * raster this board runs to. Two lookups a byte costs a fraction of that.
 *
 * The table is `const`, so it lives in flash. That is fine HERE: nothing in
 * this function ever runs while the device is busy. The programmer below
 * computes no CRC at all, for exactly that reason.
 */
static const unsigned int crc_tab[16] = {
    0x0000u, 0x1021u, 0x2042u, 0x3063u, 0x4084u, 0x50A5u, 0x60C6u, 0x70E7u,
    0x8108u, 0x9129u, 0xA14Au, 0xB16Bu, 0xC18Cu, 0xD1ADu, 0xE1CEu, 0xF1EFu
};

static unsigned int crc_step(unsigned int crc, unsigned char b)
{
    crc = (unsigned int)((crc << 4)
                         ^ crc_tab[((crc >> 12) ^ (b >> 4)) & 0x0Fu]);
    crc = (unsigned int)((crc << 4)
                         ^ crc_tab[((crc >> 12) ^ (b & 0x0Fu)) & 0x0Fu]);
    return crc;
}

/* ONE PASS OVER UP TO 4096 BYTES, AND IT NOW YIELDS.
 *
 * Until V40 every caller of this ran at boot, before IEN, where a long loop
 * costs nothing because there is no raster to starve yet. V40's commit
 * finishes LIVE: the pass that reads the DONE marker back runs cell_scan()
 * over the record's header AND its 4096-byte payload, and the nvm_scan() that
 * follows it re-reads all sixteen cells. Measured without this, one such pass
 * is tens of milliseconds against a 10 ms supervision raster.
 *
 * AN OUTER CHUNK LOOP, NOT A TEST INSIDE THE HOT ONE, and the difference was
 * measured rather than assumed. The first version wrote `if ((i & 31u) == 0u)`
 * in the byte loop; that test is paid on every byte, and nvm_scan() walks
 * 131008 of them at boot, so it added about a million instructions - 100 ms -
 * to a cold start that has a cost gate of its own. The chunked form leaves the
 * inner loop byte-for-byte what it was and pays the gate 16 times per block.
 *
 * THE INTERVAL COMES FROM THE RASTER, NOT FROM THE LOOP BODY - the project rules
 * standing rule, and this is the third time it has been the answer.
 * hcts_target_yield() is tick-gated, so it does real work at most once a
 * millisecond; 256 bytes is roughly 0.2 ms of this loop, which is five times
 * more often than the budget needs and cheap enough to disappear.
 *
 * AND THE SPAN IS ITS OWN FUNCTION, WHICH IS THE COMPILER TALKING AGAIN.
 * A CALL anywhere inside the walking loop makes Keil spill the huge pointer -
 * R8/R9 are argument registers, so they cannot survive one - and reload both
 * halves of it on every byte. Keeping the yield in the OUTER function leaves
 * the inner one exactly the shape it had before V40.
 *
 * The chunk bound is a local, so this costs no state - and this module owns no
 * near RAM by design (see the note at the top of the file). At boot
 * yield_armed is 0 and the call returns immediately. */
static unsigned int crc_span(unsigned int crc, unsigned char huge *p,
                             unsigned int n)
{
    unsigned int i;

    for (i = 0u; i < n; i++) {
        crc = crc_step(crc, p[i]);
    }
    return crc;
}

static unsigned int crc_block(unsigned char huge *p, unsigned int n)
{
    unsigned int crc = 0xFFFFu;
    unsigned int m;

    while (n != 0u) {
        hcts_target_yield();
        m = (unsigned int)((n > 256u) ? 256u : n);
        crc = crc_span(crc, p, m);
        p += m;
        n = (unsigned int)(n - m);
    }
    return crc;
}

/* ================================================== byte order, one place ==
 * Big-endian, like every other multi-byte field HaniCore stores. */
static unsigned int be16(unsigned char huge *p, unsigned int off)
{
    return (unsigned int)(((unsigned int)p[off] << 8) | p[off + 1u]);
}

static void set_be16(unsigned char huge *p, unsigned int off, unsigned int v)
{
    p[off] = (unsigned char)(v >> 8);
    p[off + 1u] = (unsigned char)(v & 0xFFu);
}

static unsigned long be32(unsigned char huge *p, unsigned int off)
{
    return ((unsigned long)p[off] << 24) | ((unsigned long)p[off + 1u] << 16)
         | ((unsigned long)p[off + 2u] << 8) | (unsigned long)p[off + 3u];
}

static void set_be32(unsigned char huge *p, unsigned int off, unsigned long v)
{
    p[off] = (unsigned char)(v >> 24);
    p[off + 1u] = (unsigned char)((v >> 16) & 0xFFuL);
    p[off + 2u] = (unsigned char)((v >> 8) & 0xFFuL);
    p[off + 3u] = (unsigned char)(v & 0xFFuL);
}

/* ============================ the control block, read and written IN PLACE ==
 *
 * There is no near-RAM mirror. `cb` is the block itself; every read and every
 * write goes to the SRAM that has to survive the reset this design expects.
 */
#define CB       SRAMB(NVM_CB)
#define NVW      SRAMB(NVW_BASE)

#define cb_state      (CB[CB_STATE])
#define cb_phase      (CB[CB_PHASE])
#define cb_cell       (CB[CB_CELL])
#define cb_err        (CB[CB_ERR])

static unsigned long cb_gen_get(void)
{
    return be32(CB, (unsigned int)CB_GEN);
}

static unsigned int cb_attempts_get(void)
{
    return be16(CB, (unsigned int)CB_ATTEMPTS);
}

/* WHY NEITHER SLOT WAS USABLE, kept separately from the control block's own
   error. The first version published it straight into hc_nvm_error() and the
   control block's HCNV_ERR_NONE then overwrote it - so a flash record written
   by a DIFFERENT PAGE LAYOUT was correctly rejected and reported as nothing at
   all. The gate caught it; a tuner staring at a defaults boot would not
   have. */
#define scan_why      (NVW[W_SCANWHY])

static void cb_seal(void)
{
    set_be32(CB, (unsigned int)CB_MAGIC, NVM_CB_MAGIC);
    set_be16(CB, (unsigned int)CB_CRC, crc_block(CB, CB_CRCLEN));
}

static void cb_reset(void)
{
    cb_state = (unsigned char)HCNV_ST_IDLE;
    cb_phase = (unsigned char)HCNV_PH_NONE;
    cb_cell = CELL_NONE;
    cb_err = (unsigned char)HCNV_ERR_NONE;
    set_be32(CB, (unsigned int)CB_GEN, 0uL);
    set_be16(CB, (unsigned int)CB_ATTEMPTS, 0u);
    cb_seal();
}

/* Validate what is there, and wipe BOTH blocks if it is not ours. Wiping the
   working block here is what makes a cold SRAM start with a zero commit
   counter and a zero arming timestamp - the only two values in it that are not
   recomputed from the flash device on every boot. */
static void cb_load(void)
{
    unsigned int i;

    if (be32(CB, (unsigned int)CB_MAGIC) == NVM_CB_MAGIC
        && be16(CB, (unsigned int)CB_CRC) == crc_block(CB, CB_CRCLEN)) {
        /* Anything the block cannot mean is treated as "start the commit
           over". A partially programmed cell is deliberately never retried. */
        if (cb_state > (unsigned char)HCNV_ST_STAGING) {
            cb_reset();
        }
        if (cb_state == (unsigned char)HCNV_ST_STAGING) {
            /* STAGING DOES NOT SURVIVE A RESET, and must not: the record was
               never finished, stage_clear() already invalidated the buffer,
               and the page it was being copied from may have changed. The
               tuner presses Burn again. */
            cb_reset();
        }
        if (cb_phase > (unsigned char)HCNV_PH_COMMIT) {
            cb_phase = (unsigned char)HCNV_PH_PROGRAM;
            cb_seal();
        }
        if (cb_cell >= TGT_FLASH_CELLS) {
            cb_cell = CELL_NONE;
            cb_seal();
        }
        return;
    }

    for (i = 0; i < W_LEN; i++) {
        NVW[i] = 0u;
    }
    cb_reset();
}

/* ===================================================== the staged record == */
/* Is what is in the staging buffer a complete, self-consistent record?
   The magic is written LAST when staging, so a burn interrupted part-way
   through building one leaves something that fails here rather than something
   that looks finished. */
/* THE CHEAP HALF: everything except the 4096-byte payload CRC.
 *
 * Walking the payload costs about 50 ms in this image - five S5500 rasters -
 * so it is done ONCE, at the instant the record is built, and again at BOOT,
 * where the buffer has crossed a reset and its integrity is genuinely in
 * question. In between, inside one power session, nothing but this module
 * writes that buffer and the header CRC and the commit marker are enough to
 * say it is still the record we made. */
static unsigned char stage_header_ok(void)
{
    unsigned char huge *p = SRAMB(NVM_STAGE);

    if (be32(p, REC_MAGIC) != NVM_REC_MAGIC) {
        return 0u;
    }
    if (be32(p, REC_LAYOUT) != (unsigned long)HC_CFG_LAYOUT_ID
        || be16(p, REC_VERSION) != (unsigned int)HC_CFG_VERSION
        || be16(p, REC_LENGTH) != (unsigned int)HC_CFG_SIZE) {
        return 0u;
    }
    if (be16(p, REC_HCRC) != crc_block(p, REC_HCRC)) {
        return 0u;
    }
    return (unsigned char)(be32(p, REC_COMMIT) == NVM_REC_COMMIT);
}

static unsigned char stage_valid(void)
{
    unsigned char huge *p = SRAMB(NVM_STAGE);

    if (be32(p, REC_MAGIC) != NVM_REC_MAGIC) {
        return 0u;
    }
    if (be32(p, REC_LAYOUT) != (unsigned long)HC_CFG_LAYOUT_ID) {
        return 0u;
    }
    if (be16(p, REC_VERSION) != (unsigned int)HC_CFG_VERSION) {
        return 0u;
    }
    if (be16(p, REC_LENGTH) != (unsigned int)HC_CFG_SIZE) {
        return 0u;
    }
    if (be16(p, REC_HCRC) != crc_block(p, REC_HCRC)) {
        return 0u;
    }
    if (be16(p, REC_PCRC) != crc_block(p + REC_PAYLOAD, HC_CFG_SIZE)) {
        return 0u;
    }
    return (unsigned char)(be32(p, REC_COMMIT) == NVM_REC_COMMIT);
}

static void stage_clear(void)
{
    /* The magic alone. Zeroing 4 KB would cost milliseconds and buy nothing:
       nothing reads a record whose magic is gone. */
    set_be32(SRAMB(NVM_STAGE), REC_MAGIC, 0uL);
}

/* ==================================================== BUILDING THE RECORD ==
 *
 * IN BOUNDED STEPS, FROM THE MAIN LOOP, and that is not a refinement - it is
 * the fix for a defect the bench found on 2026-09-04.
 *
 * The first version built the whole record inside the TunerStudio 'B' command
 * handler: validate, commit the standby page, copy 4096 bytes through
 * hc_cal_u8(), and CRC the result three times over. MEASURED IN THE LINKED
 * IMAGE, that took 257 ms - against a 10 ms S5500 supervision raster. The
 * monitoring module reset the CPU part-way through the reply, TunerStudio saw
 * a Burn response whose CRC read `D2 00 00 00` where `D2 02 EF 8D` was
 * calculated, and the page re-read that followed timed out with nothing at
 * all. It was not a transport fault; the ECU had gone away.
 *
 * me711_ts_gap_proof had never sent a 'B'. It sends every command the .ini can
 * now, which is the part of this that must not be undone.
 *
 * So: the command records a request and returns in microseconds, and every
 * step below is small enough to fit inside one main-loop pass.
 */
static void stage_begin_header(unsigned long generation)
{
    unsigned char huge *p = SRAMB(NVM_STAGE);

    set_be32(p, REC_MAGIC, 0uL);            /* invalid until it is finished */
    set_be32(p, REC_LAYOUT, (unsigned long)HC_CFG_LAYOUT_ID);
    set_be16(p, REC_VERSION, (unsigned int)HC_CFG_VERSION);
    set_be16(p, REC_LENGTH, (unsigned int)HC_CFG_SIZE);
    set_be32(p, REC_GEN, generation);
}

/* One chunk of the payload, with the CRC carried along rather than computed
   again at the end. Returns 1 when the payload is complete. */
static unsigned char stage_copy_chunk(void)
{
    unsigned char huge *p = SRAMB(NVM_STAGE);
    unsigned int pos = be16(NVW, W_STG_POS);
    unsigned int crc = be16(NVW, W_STG_CRC);
    unsigned int end = (unsigned int)(pos + HCNV_STG_CHUNK);
    unsigned char v;

    if (end > (unsigned int)HC_CFG_SIZE) {
        end = (unsigned int)HC_CFG_SIZE;
    }
    while (pos < end) {
        v = hc_cal_u8(pos);
        p[REC_PAYLOAD + pos] = v;
        crc = crc_step(crc, v);
        pos++;
    }
    set_be16(NVW, W_STG_POS, pos);
    set_be16(NVW, W_STG_CRC, crc);
    return (unsigned char)(pos >= (unsigned int)HC_CFG_SIZE);
}

/* The header CRC and the magic, in that order and LAST - so a reset part-way
   through staging leaves something that fails its own validity test rather
   than something that looks finished. */
static void stage_finish(void)
{
    unsigned char huge *p = SRAMB(NVM_STAGE);

    set_be16(p, REC_PCRC, be16(NVW, W_STG_CRC));
    set_be32(p, REC_COMMIT, NVM_REC_COMMIT);
    set_be32(p, REC_MAGIC, NVM_REC_MAGIC);
    set_be16(p, REC_HCRC, crc_block(p, REC_HCRC));
    set_be32(p, REC_MAGIC, NVM_REC_MAGIC);
}

/* ======================================================== the flash cells ==
 *
 * SIXTEEN CELLS, APPEND-ONLY, NEVER ERASED. Cell i is the body of the i'th
 * 8 KiB bootrom-checksum page across SA7 and SA8, offset two bytes in so the
 * page's sampled words are never touched. hctarget.h carries the evidence.
 *
 * WHY A MACRO AND NOT THE OBVIOUS HELPER FUNCTION, still:
 *
 *     static unsigned long slot_base(unsigned int which)
 *     {
 *         return (which == 0u) ? TGT_FLASH_CFG_A : TGT_FLASH_CFG_B;
 *     }
 *
 * Keil C166 7.53 emits that correctly on its own - CMP R8,#0, two arms, 0x84
 * and 0x85 - and then, at its call site inside this module, INLINES IT AND
 * KEEPS ONLY THE `which == 0` ARM:
 *
 *     0460  E004      MOV  R4,#00H
 *     0462  E6F58400  MOV  R5,#084H      <- unconditional. `which` is ignored.
 *     0466  F0E4      MOV  R14,R4
 *     0468  F0F5      MOV  R15,R5
 *
 * No CMP and no CALL, so the second sector would never be read. REPRODUCED
 * TWICE, DELIBERATELY, and NOT reproducible in a two-function file - it is a
 * register-allocation interaction inside the full module, not a rule anybody
 * can carry in their head. Read the listing; do not reason about it.
 *
 * AND THE ARITHMETIC IS DELIBERATELY 16-BIT. ((i & 7) << 13) is at most
 * 0xE000 and fits an unsigned int, so no 32-bit multiply appears and Keil has
 * no reason to call ?C_LMUL. That matters because hc_nvm_payload() computes a
 * cell address with the same shape and MAY NOT CALL ANYTHING.
 */
/* THE CELL ADDRESS, AND WHY IT IS SHAPED LIKE THIS.
 *
 * Cell i is page (i & 7) of store sector (i >> 3), and the store begins at
 * TGT_FLASH_CFG_A = 0x870000 (SA10, since 2026-10-15). Nine sectors,
 * seventy-two cells.
 *
 * IT IS BUILT FROM TWO 16-BIT HALVES ON PURPOSE. The obvious
 *
 *     TGT_FLASH_CFG_A + (unsigned long)(i >> 3) * TGT_FLASH_SECTOR_SIZE
 *
 * is a 32-BIT MULTIPLY, which Keil implements as a CALL into ?C_LMUL - and
 * hc_nvm_payload() computes a cell address with this same macro and MAY NOT
 * CALL ANYTHING, because the device it is writing is the device the call
 * would be fetched from. Sector stride is 0x10000, so the sector index is
 * simply added to the SEGMENT and the page offset is a 16-bit shift of at
 * most 0xE000. No 32-bit arithmetic appears at all beyond the final join.
 *
 * tools/me711_flash_busy_proof.py reads the generated listing and fails the
 * build if a CALL ever appears in the writer, so this is checked and not
 * merely intended.
 *
 * AND THE TERNARY IS GONE, which removes the hazard the old two-slot version
 * had to warn about: Keil 7.53 inlined `(which == 0) ? A : B` inside this
 * module and KEPT ONLY THE FIRST ARM, so the second sector was unreachable
 * and the A/B alternation had silently become A-only. There is no ternary
 * here to mis-inline. */
#define CELL_SEG(i)     ((unsigned int)(TGT_FLASH_CFG_SEG + ((i) >> 3)))
#define CELL_PAGEOFF(i) ((unsigned int)(((i) & 7u) << 13))
#define CELL_ADDR(i)    (((unsigned long)CELL_SEG(i) << 16)                          + (unsigned long)CELL_PAGEOFF(i) + TGT_FLASH_CELL_OFF)
#define CELL_PTR(i)     SRAMB(CELL_ADDR(i))

/* The base of the erase sector a cell lives in, and the first cell of it. */
#define CELL_SECTOR_BASE(i) (((unsigned long)CELL_SEG(i)) << 16)
#define SECTOR_FIRST_CELL(s) ((unsigned int)((s) * TGT_FLASH_CELL_PAGES))

/* The generation of the cell last scanned. cell_scan() RETURNS its reason and
 * leaves the generation here rather than taking two out-parameters - one thing
 * to get right instead of two.
 *
 * A WARNING WORTH LEAVING, because chasing it cost most of a day. The first
 * version used an out-parameter into nvm_scan()'s own frame and the reason
 * appeared to vanish; so did a later `why_b` local. BOTH were the SIMULATOR,
 * not this code and not the compiler: c167sim did not set N and Z on
 * `MOV Rw,[Rw]`, so the `JMPR cc_NZ` that follows a reload from the user stack
 * branched on stale flags. The firmware was right the whole time.
 * tools/sim_flag_test.py now fails against that simulator - ten of its eleven
 * checks - and it is the fourth c167sim defect in this project to present as a
 * firmware bug.
 *
 * The rule that found it, and the one to use next time: when a value is
 * demonstrably right but the branch on it is wrong, SUSPECT THE FLAGS, and
 * trace the instruction stream rather than re-reading the C. */
#define cell_last_gen_get()   be32(NVW, W_LAST_GEN)
#define cell_last_gen_set(v)  set_be32(NVW, W_LAST_GEN, (v))

/* HCNV_ERR_NONE when the slot holds a record this build may use, and the
   reason otherwise. An empty slot answers HCNV_ERR_STAGE - "there is nothing
   here" - which is a different fact from "there is something here and it is
   wrong", and a bench operator needs them apart.

   ORDERING MATTERS. The commit marker is tested before anything that could
   fail for a second reason, and the layout id before the CRCs - so a record
   written by a firmware with a different page layout is reported as LAYOUT and
   not as corruption. Those two need different answers from a human: one means
   "this ECU was updated", the other means "this flash is damaged". */
static unsigned int cell_scan(unsigned int which)
{
    unsigned char huge *p;

    p = CELL_PTR(which);
    cell_last_gen_set(0uL);

    if (be32(p, REC_MAGIC) != NVM_REC_MAGIC) {
        return HCNV_ERR_STAGE;
    }
    if (be32(p, REC_COMMIT) != NVM_REC_COMMIT) {
        /* Programmed but never committed: an interrupted write, and exactly
           the case the marker exists to catch. */
        return HCNV_ERR_VERIFY;
    }
    if (!hc_cfg_identity_known(be16(p,REC_LAYOUT),be16(p,REC_LAYOUT+2u),be16(p+REC_PAYLOAD,CFG_U_SCHEMA))
        || be16(p+REC_PAYLOAD,CFG_U_MAGIC) != HC_UNIVERSAL_MAGIC
        || be16(p, REC_VERSION) != (unsigned int)HC_CFG_VERSION
        || be16(p, REC_LENGTH) != (unsigned int)HC_CFG_SIZE) {
        return HCNV_ERR_LAYOUT;
    }
    if (be16(p, REC_HCRC) != crc_block(p, REC_HCRC)) {
        return HCNV_ERR_VERIFY;
    }
    if (be16(p, REC_PCRC) != crc_block(p + REC_PAYLOAD, HC_CFG_SIZE)) {
        return HCNV_ERR_VERIFY;
    }
    cell_last_gen_set(be32(p, REC_GEN));
    return HCNV_ERR_NONE;
}

/* A target is writable only when its COMPLETE body is erased. A partial record
   is consumed forever: NOR can clear bits only, and retrying it could make a
   torn header look like a valid record. */
/* THE HOT SPAN, AND IT CONTAINS NO CALL ON PURPOSE - see cell_blank(). */
static unsigned char span_blank(unsigned char huge *p, unsigned int n)
{
    unsigned int i;

    for (i = 0u; i < n; i++) {
        if (p[i] != 0xFFu) {
            return 0u;
        }
    }
    return 1u;
}

static unsigned char cell_blank(unsigned int which)
{
    unsigned char huge *p = CELL_PTR(which);
    unsigned int left = (unsigned int)TGT_FLASH_CELL_BODY;
    unsigned int n;

    /* Chunked exactly like crc_block() above, and split for the same measured
       reason: span_blank() contains no call, so Keil keeps the huge pointer in
       R8/R9 and closes the loop with CMPI1 - the six-instruction form the
       V39 build had. Writing the yield INTO this walk cost four extra
       instructions on each of the 131008 bytes nvm_scan() reads at boot, a
       measured million instructions and about 100 ms of cold start.

       A BLANK cell is the worst case here because it never short-circuits,
       and the nvm_scan() that ends a LIVE commit walks fourteen of them. */
    while (left != 0u) {
        hcts_target_yield();
        n = (unsigned int)((left > 512u) ? 512u : left);
        if (!span_blank(p, n)) {
            return 0u;
        }
        p += n;
        left = (unsigned int)(left - n);
    }
    return 1u;
}

/* Is this cell a CANDIDATE for writing? Four bytes, not 8188.
 *
 * WHY THE CHEAP TEST IS ENOUGH HERE, and where the real one lives.
 *
 * Up to V52 the scan called cell_blank() on every cell - 16 x 8188 bytes of
 * huge reads at every boot, already about 1.19 M instructions and the reason
 * me711_ts_gap_proof's warmup had to be raised to 3.5 M. V53 has EIGHTY cells.
 * The same scan would read 655040 bytes, roughly 6 M instructions, and put
 * about six tenths of a second into cold start for information that is only
 * ever acted on for ONE cell.
 *
 * So the scan asks the cheap question - "is the magic word erased?" - and the
 * expensive one is asked exactly once, of the chosen target, in nvm_commit()'s
 * entry pass, where it was already being asked. Nothing is programmed on the
 * strength of this test.
 *
 * AND THE CASE IT DELIBERATELY DOES NOT DECIDE: a half-erased sector can leave
 * a cell whose magic reads 0xFFFF.. while bytes further in are still 0x00,
 * because the device's embedded erase pre-programs the whole sector to zero
 * and the order it clears pages in is not specified. Such a cell looks like a
 * candidate here and is REJECTED by cell_blank() at commit time, which then
 * steps to the next candidate instead of failing the Burn. That is the
 * behaviour an interrupted reclaim needs. */
static unsigned char cell_candidate(unsigned int which)
{
    return (unsigned char)(be32(CELL_PTR(which), REC_MAGIC) == 0xFFFFFFFFuL);
}

/* The next candidate-free cell strictly after `from`, or CELL_NONE. */
static unsigned int next_candidate(unsigned int from)
{
    unsigned int i;

    for (i = from + 1u; i < TGT_FLASH_CELLS; i++) {
        if (cell_candidate(i)) {
            return i;
        }
    }
    return (unsigned int)CELL_NONE;
}

/* The generation in a cell's header, when the header looks like a committed
   record at all. Sixteen bytes, no CRC. */
static unsigned char cell_header_gen(unsigned int which, unsigned long *gen)
{
    unsigned char huge *p = CELL_PTR(which);

    if (be32(p, REC_MAGIC) != NVM_REC_MAGIC
        || be32(p, REC_COMMIT) != NVM_REC_COMMIT) {
        return 0u;
    }
    *gen = be32(p, REC_GEN);
    return 1u;
}

/* THE SCAN, AND WHY IT VALIDATES ONE RECORD AND NOT EIGHTY.
 *
 * THIS IS A BOOT-TIME BUDGET, AND IT WAS MEASURED, NOT ESTIMATED. The span
 * from entering hc_nvm_boot() to leaving it, executed in c167sim:
 *
 *              0 records   1 record   2 records   4 records
 *     V52       475 ms      577 ms      612 ms      682 ms
 *     V53 first   3.3 ms    135 ms      199 ms      329 ms
 *
 * The V52 column is the explanation for a bench observation nobody had
 * accounted for: on 2026-09-12 the SECOND KL30 cycle produced TWO boots and
 * ended on warm-reset signature 0x001C. It had two committed records where the
 * first cycle had one, and 612 ms of silence before the supervision link comes
 * up is inside the window in which the monitoring module resets a quiet CPU.
 * The store scan WAS the second boot.
 *
 * V53's cheap blank probe fixed most of that - and then the eighty-cell store
 * put it straight back at scale. Every NON-blank cell still cost a full
 * 4120-byte double CRC, about 80 ms each, so a store with seventy records
 * would have spent SECONDS in hc_nvm_boot() and reset itself every time.
 * The row above is the whole reason this function looks like it does.
 *
 * So the scan reads HEADERS - magic, commit marker, generation, sixteen bytes -
 * picks the newest, and CRC-checks THAT ONE. A record whose header survives but
 * whose body does not is rare and is handled by falling to the next-newest,
 * bounded, rather than by checking all eighty every time. Correctness is
 * unchanged: nothing is ever SELECTED without a full cell_scan(), which is the
 * only property that ever mattered.
 */
static void nvm_scan(void)
{
    unsigned int i;
    unsigned int why;
    unsigned int sec;
    unsigned int best;
    unsigned long best_gen = 0uL;
    unsigned long gen;
    unsigned char have;
    unsigned int tries;
    unsigned char bounded = 0u;
    unsigned long ceiling = 0uL;

    NVW[W_SLOT] = (unsigned char)HCNV_SLOT_NONE;
    NVW[W_CELL] = CELL_NONE;
    NVW[W_NEXT] = CELL_NONE;
    NVW[W_FREE] = 0u;
    set_be16(NVW, W_REJECT, 0u);
    set_be16(NVW, W_GENERATION, 0u);
    set_be32(NVW, W_BEST_GEN, 0uL);
    scan_why = (unsigned char)HCNV_ERR_NONE;

    /* PASS 1: the cheap inventory - free cells, and which cells carry a
       plausible header. Nothing here is trusted enough to be selected. */
    for (i = 0u; i < TGT_FLASH_CELLS; i++) {
        hcts_target_yield();
        if (cell_candidate(i)) {
            NVW[W_FREE]++;
            if (NVW[W_NEXT] == CELL_NONE) NVW[W_NEXT] = (unsigned char)i;
            continue;
        }
        if (!cell_header_gen(i, &gen)) {
            /* Not blank and not even a committed header: an interrupted write
               or a half-erased sector. W_REJECT IS A SECTOR MASK - it was
               `1u << i` over sixteen cells, and with eighty that shift is
               undefined past bit 15 and would report nonsense while looking
               healthy. A sector is also the unit a human acts on. */
            sec = (unsigned int)(i / TGT_FLASH_CELL_PAGES);
            set_be16(NVW, W_REJECT,
                     (unsigned int)(be16(NVW, W_REJECT) | (1u << sec)));
            if (scan_why == HCNV_ERR_NONE) {
                scan_why = (unsigned char)HCNV_ERR_STAGE;
            }
        }
    }

    /* PASS 2: validate the newest header, and fall to the next newest only if
       it does not hold up. Bounded, so a store full of damaged records cannot
       turn a boot into a CRC marathon. */
    for (tries = 0u; tries < 4u; tries++) {
        best = (unsigned int)CELL_NONE;
        have = 0u;
        for (i = 0u; i < TGT_FLASH_CELLS; i++) {
            if (cell_candidate(i)) {
                continue;
            }
            if (!cell_header_gen(i, &gen)) {
                continue;
            }
            if (bounded && (long)(gen - ceiling) >= 0L) {
                continue;               /* already tried this one or newer */
            }
            if (!have || (long)(gen - best_gen) >= 0L) {
                best_gen = gen;
                best = i;
                have = 1u;
            }
        }
        if (!have) {
            break;
        }
        hcts_target_yield();
        why = cell_scan(best);
        if (why == HCNV_ERR_NONE) {
            NVW[W_CELL] = (unsigned char)best;
            set_be32(NVW, W_BEST_GEN, cell_last_gen_get());
            set_be16(NVW, W_GENERATION,
                     (unsigned int)(cell_last_gen_get() & 0xFFFFuL));
            NVW[W_SLOT] = (unsigned char)
                ((best / TGT_FLASH_CELL_PAGES) + 1u);
            break;
        }
        /* The header said record, the body said otherwise. Report it against
           its sector and look at the next newest. */
        sec = (unsigned int)(best / TGT_FLASH_CELL_PAGES);
        set_be16(NVW, W_REJECT,
                 (unsigned int)(be16(NVW, W_REJECT) | (1u << sec)));
        if (scan_why == HCNV_ERR_NONE || scan_why == HCNV_ERR_STAGE) {
            scan_why = (unsigned char)why;
        }
        ceiling = best_gen;
        bounded = 1u;
    }

    if (NVW[W_CELL] == CELL_NONE && scan_why == HCNV_ERR_STAGE) {
        /* "there is nothing here" is not an error on a virgin store. */
        scan_why = HCNV_ERR_NONE;
    }
    NVW[W_NONVOL] = (unsigned char)(NVW[W_SLOT] != (unsigned char)HCNV_SLOT_NONE);
    hc_cfg_set_nonvol(NVW[W_NONVOL]);
}

static unsigned int active_index(void)
{
    return (unsigned int)NVW[W_CELL];
}

/* ==================================================== THE PROGRAMMER =======
 *
 * EVERYTHING IN fl_payload RUNS FROM THE EXTERNAL SRAM, and it is written to
 * one rule:
 *
 *     it may not call anything, and it may not read anything out of flash.
 *
 * Not the C library, not another function of ours, not a `const` table - all
 * of those live in flash, and flash is the device being erased. One `CALLA` in
 * the generated code would jump into a chip that is answering with status bits
 * instead of instructions. That is why the CRC table above is never touched
 * here and why every address in this function is a compile-time constant:
 * there is nothing to pass in but the slot, and that arrives as one byte in
 * the control block.
 *
 * It rules out 32-bit multiply and divide too, which Keil implements as calls
 * into `?C_LMUL` and friends. Only 16-bit arithmetic and huge pointers appear.
 * tools/me711_flash_busy_proof.py reads the generated listing and FAILS THE
 * BUILD if a later edit ever makes Keil emit a call, and it runs the linked
 * image against a modelled 29F800BB that counts every instruction fetch
 * landing on a busy device.
 *
 * ===========================================================================
 * FOUR WRITE CYCLES PER WORD. THE FIFTH ONE COST A BENCH BURN.
 * ===========================================================================
 *
 * V40's first Burn on the real ECU failed with "a word would not program",
 * five times, and the 1 MiB bootmode readback
 * (failedReadback/V40_FIRST_RESETLESS_BURN_FAIL.bin) says exactly what
 * happened: cells 0..4 each hold a PERFECT PREFIX of the record - 686, 792,
 * 797, 874 and 1114 words, every one of them byte-correct, no skipped word,
 * no partially programmed word - and the very next word is 0xFFFF. Untouched.
 * The device never applied a program pulse to it.
 *
 * A data poll cannot produce a false match while the part is busy: DQ7 reads
 * back as the COMPLEMENT of the datum's bit 7 throughout the embedded
 * algorithm, so a full-word compare can only match once DQ7 has flipped to
 * true data. What the datasheet does NOT promise is that the write state
 * machine has released at that instant - it says the opposite, that the
 * outputs settle across successive read cycles - and an AM29F800BB that is
 * still busy IGNORES EVERY COMMAND WRITTEN TO IT.
 *
 * Now compare the generated code. V39's writer, which programmed 4120 words
 * on THIS ECU without one failure, and V40's are the same instructions except
 * for three:
 *
 *     0A86  E6F6F000   MOV   R6,#0F0H
 *     0A8A  DC0F       EXTS  R15,#01H
 *     0A8C  B86E       MOV   [R14],R6      <- a FIFTH write cycle, per word
 *
 * The AMD program sequence is FOUR write cycles. V40 issued five, and it
 * issued the extra one three instructions after the poll matched - the
 * earliest possible moment, deep inside the window where the part may not yet
 * have released. Swallowed by a busy device, the F0 is harmless; the AA/55/A0
 * that follow it are swallowed too, and THAT is the word that stays 0xFFFF.
 * V39 escaped it because its second look at the word was a READ, and a read
 * disturbs nothing.
 *
 * So V41:
 *
 *   - the success path issues EXACTLY the four AMD write cycles per word and
 *     nothing else, which makes it bus-identical to the writer that is
 *     physically proven on this ECU;
 *   - the poll requires TWO AGREEING READS that both equal the datum. That is
 *     the rule the M744 standalone's own working 29F800 programmer uses
 *     (the M744 stand-alone ECU project .../FlashHandler.c reads the word twice
 *     and loops while they differ), strengthened with the data check;
 *   - the reset command is written ONLY on the failure path, where the device
 *     state really is unknown. On the success path read-array is not asserted,
 *     it is PROVEN - by the two array reads that just came out of the part;
 *   - the poll is bounded by T7 against the datasheet's 500 us maximum, not by
 *     60000 iterations of a loop, which was 30 ms of IEN-off.
 *
 * tools/me711_flash_bus_proof.py counts the write cycles the LINKED IMAGE
 * actually issues per programmed word, against a modelled AM29F800BB that
 * ignores commands while busy. It fails against the frozen V40 binary.
 *
 * THE ON-CHIP WATCHDOG IS SERVICED THROUGHOUT. A sector erase takes about a
 * second and the C167's own watchdog period is milliseconds, so without a
 * service in the poll loops the CPU would reset in the middle of every erase -
 * which the design survives, but there is no reason to make it happen on
 * purpose.
 *
 * AND EVERY SERVICE REWRITES WDTCON FIRST, exactly like hc_srvwdt() and
 * exactly like the OEM's own two-instruction service at 0x8076C2. The C167CR
 * manual asks for it - "the user is advised to rewrite WDTCON each time before
 * the watchdog timer is serviced" (13.1) - and validate_me711_image proves it
 * of every SRVWDT opcode in the linked image. The first version of this file
 * used a bare SRVWDT in all four poll loops and that gate is what caught it.
 * WDTCON is an SFR write: no call, no flash read, safe here.
 *
 * It returns after a small, bounded chunk.  Every word is verified and the
 * NOR is explicitly returned to read-array mode before the far return makes
 * ordinary flash code executable again.
 */
void far hc_nvm_payload(void)
{
    unsigned int volatile huge *unl1 = FLW(TGT_FLASH_UNLOCK1);
    unsigned int volatile huge *unl2 = FLW(TGT_FLASH_UNLOCK2);
    unsigned char huge *cb = SRAMB(NVM_CB);
    unsigned char huge *dg = SRAMB(NVM_DG);
    unsigned int volatile huge *p;
    unsigned int volatile huge *cellp;
    unsigned int huge *src = SRAMW(NVM_STAGE);
    unsigned int huge *s;
    unsigned int pos;
    unsigned int words;
    unsigned int v;
    unsigned int a;
    unsigned int b;
    unsigned int t0;
    unsigned int el;
    unsigned int fl;
    unsigned int dq5;
    unsigned int sa;
    unsigned int sb;
    unsigned int volatile far *lf =
        (unsigned int volatile far *)HC_LF_ADDR;
    if (cb[CB_CELL] >= TGT_FLASH_CELLS) {
        cb[CB_RESULT] = (unsigned char)HCNV_ERR_STAGE;
        return;
    }
    /* THE LOW BYTE. DG_FLAGS is a BIG-ENDIAN 16-bit field - "low HCNV_PF_*,
       high worst attempt count" - so the PF bits live at DG_FLAGS+1 and the
       attempt count at DG_FLAGS+0.

       This writer used to read and write dg[DG_FLAGS], i.e. the ATTEMPT-COUNT
       byte, so every flag it raised was reported one byte too high and every
       attempt count nvm_commit() had written was destroyed. HCNV_PF_DQ5 is
       0x01 and the diary read back 0x0100, which is exactly what
       me711_flash_bus_proof saw and reported as "the DQ5 path does not work".
       The path worked; nobody could see it. */
    fl = (unsigned int)dg[DG_FLAGS + 1u];
    pos = (unsigned int)(((unsigned int)cb[CB_POS] << 8) | cb[CB_POS + 1u]);

    /* CHUNK ENTRY: PROVE THE DEVICE IS SETTLED BEFORE THE FIRST COMMAND.
     *
     * Two reads of the target, no write of any kind. On an AM29F800BB that is
     * still running an embedded algorithm DQ6 toggles between successive
     * reads, so two agreeing reads are the cheapest honest evidence that the
     * part is in read-array mode - and the part has by now been left alone for
     * a whole main-loop pass, so the only way they disagree is that something
     * between chunks disturbed it. That is worth knowing, and worth resetting.
     *
     * A read costs the device nothing. This is why it is here and why V40's
     * post-poll WRITE was not. */
    /* THE CELL BASE, COMPUTED ONCE. It was worked out twice - here and again
       inside the word loop - and with V53's ten-sector CELL_ADDR that second
       copy pushed the linked writer to 1052 bytes. It changes no bus cycle:
       the same address is formed, just not twice. */
    cellp = FLW(CELL_ADDR(cb[CB_CELL]));
    p = cellp + pos;
    /* No word has been chosen yet, and the shared exit below reads `v` when it
       decides whether a bit that must be SET has come back clear. Zero makes
       that predicate vacuously false, which is the right answer here: nothing
       has been asked of this word. */
    v = 0u;
    a = *p;
    b = *p;
    if (a != b) {
        /* A read pair that toggles is NOT permission to issue AA/55/A0. The
           main-loop retry path records the detail and proves the target is
           safe before it ever lets this RAM writer re-issue a command. */
        fl |= HCNV_PF_NOTIDLE;
        goto reset_and_return;
    }

    for (words = 0u; words < HCNV_PROG_CHUNK && pos < REC_TOTAL_WORDS;
         words++) {
        p = cellp + pos;
        s = src + pos;
        v = *s;

        lf[LF_COMMAND_SEQ] = (unsigned int)(pos + 1u);
        lf[LF_COMMAND_T7] = (unsigned int)T7;

        /* EXACTLY FOUR WRITE CYCLES PER WORD, AND NOT ONE MORE. */
        *unl1 = FL_UNLOCK1;
        *unl2 = FL_UNLOCK2;
        *unl1 = FL_PROGRAM;
        *p = v;

        /* TWO AGREEING READS. A single matching read is not proof that the
           embedded algorithm has released the device, and V40 acted on one.
           DQ5 is consulted ONLY while DQ7 still disagrees with the datum -
           that is the datasheet's own ordering, and it matters because bit 5
           of ordinary array data is data. */
        a = (unsigned int)~v;
        b = a;
        dq5 = 0u;
        t0 = (unsigned int)T7;
        for (;;) {
            WDTCON = TGT_WDTCON_SERVICE;
            __asm { SRVWDT }
            a = *p;
            b = *p;
            if (a == v && b == v) {
                break;
            }
            if (((unsigned int)(a ^ v) & 0x0080u) != 0u
                && (a & 0x0020u) != 0u) {
                /* DQ7 is still status and DQ5 is set: the device ran its own
                   timer out. Re-read once, because DQ5 and DQ7 may go true
                   together, and then stop - continuing to poll a part that has
                   said no is just IEN-off time. */
                a = *p;
                b = *p;
                dq5 = 1u;
                break;
            }
            if ((unsigned int)((unsigned int)T7 - t0)
                >= (unsigned int)HCNV_POLL_TICKS) {
                break;
            }
        }
        el = (unsigned int)((unsigned int)T7 - t0);

        if (a == v && b == v) {
            /* SETTLE, THEN CONFIRM. No bus cycle of any kind for
               HCNV_SETTLE_TICKS, then read twice more. A poll match that was
               really status which happened to equal the datum cannot survive
               this, and it lengthens the quiet interval before the next unlock
               cycle - the direction all of this file's evidence points. */
            t0 = (unsigned int)T7;
            while ((unsigned int)((unsigned int)T7 - t0)
                   < (unsigned int)HCNV_SETTLE_TICKS) {
                WDTCON = TGT_WDTCON_SERVICE;
                __asm { SRVWDT }
            }
            a = *p;
            b = *p;
            if (a != v || b != v) {
                fl |= HCNV_PF_SETTLE;
            }
        }

        if (a != v || b != v) {
            /* THE WORD DID NOT TAKE. Leave the cursor where it is, name what
               the poll saw, and go out through the shared exit - the only
               place in this routine that hands control back to code in flash,
               and the only place that proves it may. nvm_commit() re-enters,
               so the retry gets a whole main-loop pass of quiet and the
               interrupt-off window stays exactly what it was. */
            if (dq5 != 0u) {
                fl |= HCNV_PF_DQ5;
            }
            goto reset_and_return;
        }

        /* THE VERIFIED-COMPLETION STAMP, AND IT IS THE WRITER'S OWN.
         *
         * With HCNV_PROG_CHUNK == 1 the C bookkeeping in fl_enter() runs a
         * few instructions after RETS - which is exactly the IC-restoration
         * boundary this build exists to measure. A "this word verified" flag
         * that only C can publish would report a command issued into an
         * unsafe flash interval for a word the device had in fact finished.
         *
         * SO THE DISCRIMINATOR IS A TIME, NOT A SECOND SEQUENCE NUMBER, AND
         * THAT IS A MEASURED DECISION. Stamping lf[LF_VERIFY_SEQ] here as
         * well cost 18 bytes and took the linked writer to 1032 of the fixed
         * 1024-byte relocation - it did not fit, and the relocation length is
         * not something to widen for instrumentation. It does not need to:
         * this word's LF_VERIFY_T7 lands 14 T7 ticks after its LF_COMMAND_T7
         * (a nominal 11 us word), at most HCNV_POLL_US + HCNV_SETTLE_US if
         * the poll ran long, whereas a VERIFY_T7 left over from the PREVIOUS
         * word is a whole main-loop pass earlier - thousands of ticks, and
         * unsigned it reads as nearly a full 65536-tick wrap. T7 wraps every
         * 52.5 ms, far longer than one pass, so the two cases cannot be
         * confused. Both halves of the comparison are written HERE, by the
         * relocated writer, before it returns; the decoder does the subtract.
         */
        lf[LF_VERIFY_T7] = (unsigned int)T7;

        /* THE POLL DURATION IS THE MEASUREMENT THIS PROJECT NEVER TOOK. A
           normal word is 11 us - about 14 T7 ticks. A minimum near zero would
           mean the poll is matching on status, which is a hypothesis two bench
           runs have carried and neither has tested. */
        if (el > (unsigned int)(((unsigned int)dg[DG_POLLMAX] << 8)
                                | dg[DG_POLLMAX + 1u])) {
            dg[DG_POLLMAX] = (unsigned char)(el >> 8);
            dg[DG_POLLMAX + 1u] = (unsigned char)el;
        }
        if (el < (unsigned int)(((unsigned int)dg[DG_POLLMIN] << 8)
                                | dg[DG_POLLMIN + 1u])) {
            dg[DG_POLLMIN] = (unsigned char)(el >> 8);
            dg[DG_POLLMIN + 1u] = (unsigned char)el;
        }
        pos++;
    }
    dg[DG_FLAGS + 1u] = (unsigned char)fl;
    cb[CB_POS] = (unsigned char)(pos >> 8);
    cb[CB_POS + 1u] = (unsigned char)pos;
    cb[CB_RESULT] = (unsigned char)HCNV_ERR_NONE;
    return;

reset_and_return:
    /* THE WRITER MAY NOT RETURN INTO A DEVICE IT HAS NOT PROVED IT CAN FETCH
     * FROM. THIS IS THE DQ5 DEFECT, AND IT IS MEASURED, NOT ARGUED.
     *
     * DQ5 does not mean the part has finished. It means the part's own timer
     * expired, and the device then STAYS in that state, answering every read
     * with status, until it is given a reset command. The old code issued
     * FL_RESET and returned on the spot. Under me711_flash_bus_proof's DQ5
     * injection the bus log shows that reset written at step 16098685 into a
     * device busy until 16098758 - swallowed, exactly as V40's program commands
     * were - and the CPU then took FORTY instruction fetches out of a part that
     * was answering with status, executed them, wandered into segment 1 and
     * died on an illegal opcode. The Burn did not fail; it never came back, and
     * the host got no reply at all.
     *
     * SO THE COMMAND IS REISSUED AND THE PART IS MADE TO PROVE IT WORKED. Two
     * reads of one address, required to AGREE: a device running an embedded
     * algorithm toggles DQ6 on every read cycle and cannot hold still for two,
     * while one in read-array mode cannot do anything else. That is the same
     * discipline the chunk entry and the word poll already use, applied to the
     * one exit that did not have it.
     *
     * BOUNDED at HCNV_IDLE_TICKS and NAMED on expiry. A part that will not come
     * back is one this CPU cannot execute from at all, so there is nothing
     * better to return to; what the bound buys is that the outcome is a
     * recorded HCNV_PF_STUCK and a counted retry instead of a hang, and the
     * commit is bounded above by HCNV_PROG_TRIES either way. The record being
     * written is never the record in use, so a supervisor reset here costs the
     * calibration nothing.
     *
     * AND ONLY NOW MAY THE UNRECOVERABLE-BIT PREDICATE BE APPLIED. `a` and `b`
     * are whatever the poll last saw, which on this path may be STATUS - the
     * DQ5 case reported got1 = got2 = 0x5AEA and the writer duly raised
     * HCNV_PF_UNSAFE on it, condemning a perfectly good word on the strength of
     * a status byte. The test belongs on array data, so it is taken from the
     * settled read, and it is skipped entirely when the part never settled. */
    sa = 0u;
    sb = 1u;
    t0 = (unsigned int)T7;
    for (;;) {
        WDTCON = TGT_WDTCON_SERVICE;
        __asm { SRVWDT }
        *unl1 = FL_RESET;
        sa = *p;
        sb = *p;
        if (sa == sb) {
            break;
        }
        if ((unsigned int)((unsigned int)T7 - t0)
            >= (unsigned int)HCNV_IDLE_TICKS) {
            fl |= HCNV_PF_STUCK;
            break;
        }
    }
    if (a != b) {
        fl |= HCNV_PF_DISAGREE;
    }
    if ((fl & HCNV_PF_STUCK) == 0u && (unsigned int)(sa & v) != v) {
        fl |= HCNV_PF_UNSAFE;
    }
    dg[DG_WORD] = (unsigned char)(pos >> 8);
    dg[DG_WORD + 1u] = (unsigned char)pos;
    dg[DG_EXP] = (unsigned char)(v >> 8);
    dg[DG_EXP + 1u] = (unsigned char)v;
    dg[DG_GOT1] = (unsigned char)(a >> 8);
    dg[DG_GOT1 + 1u] = (unsigned char)a;
    dg[DG_GOT2] = (unsigned char)(b >> 8);
    dg[DG_GOT2 + 1u] = (unsigned char)b;
    dg[DG_FLAGS + 1u] = (unsigned char)fl;
    cb[CB_POS] = (unsigned char)(pos >> 8);
    cb[CB_POS + 1u] = (unsigned char)pos;
    cb[CB_RESULT] = (unsigned char)HCNV_RES_RETRY;
}

/* AN ADDRESS MARKER AND NOTHING ELSE.
 *
 * me711_flash_busy_proof takes (hc_nvm_payload_end - hc_nvm_payload) as the
 * programmer's length so it can scan exactly those bytes of the LINKED IMAGE,
 * and so it can assert the relocation's fixed 1024-byte copy is big enough.
 * Deriving the length beats writing it down twice: this project has four
 * recorded incidents of hand-maintained metadata drifting from the artefact it
 * described.
 *
 * It is also the reason hc_nvm_payload is not static. A static function is not
 * in the linker map at all, and a gate that cannot name the thing it is
 * checking is checking something else. */
void far hc_nvm_payload_end(void)
{
}

/* ===================================================== THE SECTOR ERASER ====
 *
 * SAME RULES AS hc_nvm_payload(): it runs from a copy of itself in external
 * SRAM, it may not call anything, and it may not read anything out of flash.
 * The device it is erasing is the device an instruction fetch would come from.
 *
 * IT IS A SEPARATE ROUTINE ON PURPOSE. hc_nvm_payload() is the writer that
 * programmed a whole record on this ECU without one failure, and its bus
 * behaviour - exactly four write cycles per word, a poll that needs two
 * agreeing reads - was bought with two bench failures and a 1 MiB forensic
 * dump. Growing it to carry an erase would put all of that back in play for
 * no reason. The two share the relocation SLOT, never the code.
 *
 * ONE ENTRY DOES ONE SLICE:
 *
 *   START   six write cycles, then run the slice
 *   RESUME  one write cycle, then run the slice
 *
 * and the slice ends in exactly one of three ways: DQ7 true (the erase is
 * finished and the device has already returned to read mode by itself), DQ5
 * set (the device gave up - reset it and say so), or the slice timer expiring
 * (suspend, wait out the 20 us latency, and return with the device readable).
 *
 * WHY DQ7 AND NOT A BLANK CHECK: while the device is erasing, every read
 * returns status, so there is nothing to blank-check yet. The blank check is
 * done afterwards in ordinary C, where reading flash is legal again, and it is
 * what actually decides the sector is reclaimed.
 */
void far hc_nvm_eraser(void)
{
    unsigned int volatile huge *unl1 = FLW(TGT_FLASH_UNLOCK1);
    unsigned int volatile huge *unl2 = FLW(TGT_FLASH_UNLOCK2);
    unsigned int volatile huge *sec;
    unsigned char huge *cb = SRAMB(NVM_CB);
    unsigned char huge *er = SRAMB(NVM_ER);
    unsigned int slice;
    unsigned int t0;
    unsigned int a;
    unsigned int seg;
    unsigned int done = 0u;
    unsigned int failed = 0u;

    if (er[ER_SECTOR] >= (unsigned char)TGT_FLASH_SECTORS) {
        er[ER_RESULT] = (unsigned char)HCNV_ERR_ERASE;
        cb[CB_RESULT] = (unsigned char)HCNV_ERR_ERASE;
        return;
    }

    /* The sector base, built from two 16-bit halves for the same reason
       CELL_ADDR is - a 32-bit multiply here would be a CALL to ?C_LMUL. */
    seg = (unsigned int)(TGT_FLASH_CFG_SEG + (unsigned int)er[ER_SECTOR]);
    sec = (unsigned int volatile huge *)(((unsigned long)seg << 16));

    slice = (unsigned int)(((unsigned int)er[ER_SLICETK] << 8)
                           | er[ER_SLICETK + 1u]);
    if (slice == 0u) {
        slice = (unsigned int)US_TO_TICKS(HCNV_ERASE_SLICE_US);
    }

    if (er[ER_OP] == (unsigned char)HCNV_EOP_START) {
        *unl1 = FL_UNLOCK1;
        *unl2 = FL_UNLOCK2;
        *unl1 = FL_ERASE_SETUP;
        *unl1 = FL_UNLOCK1;
        *unl2 = FL_UNLOCK2;
        *sec  = FL_ERASE_SECTOR;
    } else {
        *sec = FL_ERASE_RESUME;
    }

    t0 = (unsigned int)T7;
    for (;;) {
        WDTCON = TGT_WDTCON_SERVICE;
        __asm { SRVWDT }
        a = *sec;
        if ((a & 0x0080u) != 0u) {
            /* DQ7 true: the embedded erase is complete and the part has
               already put itself back in read-array mode. */
            done = 1u;
            break;
        }
        if ((a & 0x0020u) != 0u) {
            /* DQ5: the device ran its own timer out. Read once more - DQ5 and
               DQ7 can go true together - and stop either way. */
            a = *sec;
            if ((a & 0x0080u) != 0u) {
                done = 1u;
            } else {
                failed = 1u;
            }
            break;
        }
        if ((unsigned int)((unsigned int)T7 - t0) >= slice) {
            break;
        }
    }

    er[ER_LASTDQ] = (unsigned char)(a >> 8);
    er[ER_LASTDQ + 1u] = (unsigned char)a;

    if (failed != 0u) {
        *unl1 = FL_RESET;
        er[ER_STATE] = (unsigned char)HCNV_ER_FAILED;
        er[ER_RESULT] = (unsigned char)HCNV_ERR_ERASE;
        cb[CB_RESULT] = (unsigned char)HCNV_ERR_ERASE;
        return;
    }
    if (done != 0u) {
        er[ER_STATE] = (unsigned char)HCNV_ER_DONE;
        er[ER_RESULT] = (unsigned char)HCNV_ERR_NONE;
        cb[CB_RESULT] = (unsigned char)HCNV_ERR_NONE;
        return;
    }

    /* SUSPEND, AND WAIT OUT THE LATENCY BEFORE RETURNING. The far return is an
       instruction fetch from this same device: coming back before the part has
       actually suspended would fetch status. 20 us is the datasheet maximum
       and this waits 25. */
    *sec = FL_ERASE_SUSPEND;
    t0 = (unsigned int)T7;
    while ((unsigned int)((unsigned int)T7 - t0)
           < (unsigned int)US_TO_TICKS(HCNV_ERASE_SUSPEND_US)) {
        WDTCON = TGT_WDTCON_SERVICE;
        __asm { SRVWDT }
    }
    er[ER_STATE] = (unsigned char)HCNV_ER_RUNNING;
    er[ER_OP] = (unsigned char)HCNV_EOP_RESUME;
    er[ER_RESULT] = (unsigned char)HCNV_ERR_NONE;
    cb[CB_RESULT] = (unsigned char)HCNV_ERR_NONE;
}

/* An address marker, exactly as for hc_nvm_payload: the relocation length is
   DERIVED from the pair rather than written down a second time. */
void far hc_nvm_eraser_end(void)
{
}

/* --------------------------------------------------------- the relocation -- */
/* WHICH payload goes into the one relocation slot. Re-preparing is a
   1024-byte SRAM copy and it is the price of leaving fl_enter() - the
   IR-preserving window that V50 bought and V52 proved on the bench - byte for
   byte as it is. A second CALLS site would have meant a second copy of the
   save/mask/restore discipline, and that discipline is exactly what V48 and
   V49 got wrong. */
static void fl_prepare_sel(unsigned char which)
{
    unsigned char huge *dst = SRAMB(NVM_RT);
    unsigned char huge *code;
    unsigned int i;
    unsigned int begin;
    unsigned int end;
    unsigned int target;
    unsigned char op;

    /* A near function pointer is an offset inside the one code segment, so the
       huge address is TGT_CODE_BASE plus that offset.

       A FIXED length rather than a measured one: copying more than the
       function is harmless - the extra bytes are never executed - and it
       removes any dependence on how the linker ordered the module.
       me711_flash_busy_proof asserts the function is smaller than this. */
    if (which == (unsigned char)HCNV_PAY_ERASER) {
        begin = (unsigned int)&hc_nvm_eraser;
        end = (unsigned int)&hc_nvm_eraser_end;
    } else {
        begin = (unsigned int)&hc_nvm_payload;
        end = (unsigned int)&hc_nvm_payload_end;
    }
    /* WHICH ROUTINE IS IN THE SLOT IS A FACT THAT MUST SURVIVE A RESET.
       The slot lives in the battery-backed SRAM, so after a reset it still
       holds whatever was last copied there - and nvm_commit() only prepares
       the writer on its ENTRY pass, which a RESUMED commit skips. A commit
       resumed after a reset that interrupted a reclaim would therefore have
       CALLED THE ERASER. Recording it here is what lets both paths check. */
    SRAMB(NVM_ER)[ER_LOADED] = which;
    code = SRAMB(TGT_CODE_BASE + (unsigned long)begin);
    /* THE SLOT IS THE WHOLE RESERVATION, 2048 BYTES, because the writer and
       the eraser SHARE it - only one is ever loaded. Copying more than the
       routine is harmless; the extra bytes are never executed. */
    for (i = 0u; i < (unsigned int)TGT_RAM_FLASHRT_LIMIT; i++) {
        dst[i] = code[i];
    }

    /* THE COPY IS BYTE-FOR-BYTE, BUT C166 `JMPA`/`CALLA` CADDRESSES ARE
       ABSOLUTE WITHIN CSP. Keil emitted four JMPA back-edges in this routine.
       Leaving their 0x30xx operands untouched after moving the code to
       38:6000 makes them branch into the staging buffer at 38:30xx instead
       of the corresponding instruction at 38:60xx. Patch only those two
       documented four-byte forms, only when their target lies inside the
       linked writer span. Relative branches need no change; external targets
       must never be rebased. The linked-size gate proves end-begin <= 1024. */
    for (i = 0u; (unsigned int)(i + 3u) < (unsigned int)(end - begin); ) {
        op = dst[i];
        if (op == 0xCAu || op == 0xEAu) {
            target = (unsigned int)((unsigned int)dst[i + 2u]
                                    | ((unsigned int)dst[i + 3u] << 8));
            if (target >= begin && target < end) {
                target = (unsigned int)(TGT_RAM_FLASHRT + target - begin);
                dst[i + 2u] = (unsigned char)target;
                dst[i + 3u] = (unsigned char)(target >> 8);
            }
        }
        switch (op & 0x0Fu) {
        case 0x02u: case 0x03u: case 0x04u: case 0x05u:
        case 0x06u: case 0x07u: case 0x0Au:
            i = (unsigned int)(i + 4u);
            break;
        default:
            i = (unsigned int)(i + 2u);
            break;
        }
    }

}

/* V47's admission is deliberately separate from the SRAM writer.  The writer
   does one AM29 word and knows no scheduler, ASIC or interrupt policy; all
   potentially-flash-backed vector producers are dealt with BEFORE IEN returns
   high.  An in-flight PEC transfer is permitted only when both terminal
   vectors are farther than WORD_GUARD from their terminal request. */
static void live_init(void)
{
    unsigned char huge *lb = SRAMB(NVM_LIVE);
    unsigned int i;

    if (be32(lb, L_MAGIC) != L_MAGIC_VALUE) {
        for (i = 0u; i < 36u; i++) lb[i] = 0u;
        set_be32(lb, L_MAGIC, L_MAGIC_VALUE);
    }
}

static unsigned char live_admit(unsigned int now_ms, unsigned int rpm,
                                unsigned char trig_turning,
                                unsigned char outputs_busy,
                                unsigned char page_stable)
{
    unsigned char huge *lb = SRAMB(NVM_LIVE);
    unsigned int elapsed;
    unsigned int safe_dt;
    unsigned int horizon_ticks;
    unsigned int horizon_us;
    unsigned int tx_left;
    unsigned int rx_left;
    unsigned int sscon;
    unsigned int min_pec_words;
    unsigned int remaining;

    live_init();
    elapsed = (unsigned int)(now_ms - be16(NVW, W_ARM_MS));
    if (elapsed >= (unsigned int)TGT_LIVE_BURN_DEADLINE_MS) {
        lb[L_ADMISSION] = (unsigned char)HCNV_ADMIT_DEADLINE;
        set_be16(lb, L_DEADLINE_MS, 0u);
        if (be16(lb, L_WINDOWS_NO) != 0xFFFFu) {
            set_be16(lb, L_WINDOWS_NO, (unsigned int)(be16(lb, L_WINDOWS_NO) + 1u));
        }
        return 0u;
    }
    set_be16(lb, L_DEADLINE_MS,
             (unsigned int)(TGT_LIVE_BURN_DEADLINE_MS - elapsed));

    if (outputs_busy != 0u || page_stable == 0u || IEN == 0
        || !hc_deadline_flash_admit((unsigned int)((TGT_LIVE_WORD_GUARD_US*5u+3u)/4u))) {
        lb[L_ADMISSION] = (unsigned char)HCNV_ADMIT_ENGINE;
        lb[L_PAUSE] = 1u;
        goto reject;
    }

    /* A running 60-2 decoder may use a horizon only from a clean, ordinary
       tooth.  `trg_last_dt` is intentionally NOT used: it is the raw last
       interval and can span the missing-tooth region.  Discount the clean
       period for an adverse one-tooth acceleration, then subtract time
       already elapsed since the edge.  A pending gap, uncertain crank sync,
       or cam-window error has no independently bounded next edge and is an
       explicit reject, never an optimistic estimate. */
    horizon_us = 0xFFFFu;
    if (rpm != 0u || trig_turning != 0u) {
        if (trg_state < TRG_SYNC_CRANK || trg_tooth_dt == 0u
            || trg_gap_pending != 0u || trg_cam_error != 0u) {
            set_be16(lb, L_HORIZON_US, 0u);
            lb[L_ADMISSION] = (unsigned char)HCNV_ADMIT_ENGINE;
            lb[L_PAUSE] = 2u;
            goto reject;
        }
        safe_dt = (unsigned int)(trg_tooth_dt
                   - (trg_tooth_dt / TGT_LIVE_HORIZON_ACCEL_DIV));
        elapsed = (unsigned int)(T1 - trg_last_edge_t1);
        horizon_ticks = (elapsed >= safe_dt) ? 0u
                      : (unsigned int)(safe_dt - elapsed);
        /* T1 is 1.250 MHz; multiply by 0.8 without a 32-bit helper. */
        horizon_us = (unsigned int)(horizon_ticks - (horizon_ticks / 5u));
        set_be16(lb, L_HORIZON_US, horizon_us);
        if (horizon_us <= (unsigned int)TGT_LIVE_WORD_GUARD_US) {
            lb[L_ADMISSION] = (unsigned char)HCNV_ADMIT_ENGINE;
            lb[L_PAUSE] = 3u;
            goto reject;
        }
    } else {
        set_be16(lb, L_HORIZON_US, horizon_us);
    }

    /* No new ASIC transfer starts once the claim above is held (the 1 ms
       tick starts them since 2026-10-13).  An active PEC transfer
       may continue stealing its hardware cycles, but neither PEC terminal
       vector may become pending inside the flash-busy interval. */
    /* V51.  THE FLASH BUS AND THE SSC DO NOT SHARE ANYTHING, so the exclusion
       here is not about the AM29 at all.
     *
     * The writer's real requirement is that nothing FETCHES from the flash
     * while it is busy, and that is met twice over: the routine runs from a
     * copy of itself in external SRAM, and IEN is 0 across the busy window so
     * no vector is fetched from the flash-resident table.  The SSC is on-chip
     * on P3.8/P3.9/P3.13, and its PEC endpoints are SSCTB/SSCRB and
     * TGT_ASIC_FRAME in external SRAM - NEITHER IS IN FLASH.  So no SSC
     * activity can read a busy device.
     *
     * The coupling runs the other way.  IEN = 0 for up to
     * LF_MAX_WINDOW_T7 = 145 T7 ticks = 116 us stops PEC4 servicing SSCRB,
     * and at SSCBR = 0x13 a word arrives every 16 us - so masking across a
     * frame loses supervision data and sets SSCRE, "reception completed
     * before the receive buffer was read" [C167CR UM V3.1 section 12].  A
     * runtime frame is TGT_ASIC_WORDS_RUN = 118 words = 1.89 ms of a 10 ms
     * raster, and a frame cannot START inside the window because
     * asic_start_transfer() is task level and already refuses while
     * hc_nvm_word_owned().  So the whole hazard is "a frame is ALREADY on the
     * wire", and hc_asic_frame_in_flight() is exactly that question.
     *
     * WHAT THIS REPLACES, AND WHY IT HAD TO GO.  V47..V50 rejected on
     * (SSCEN && (SSCCON & 0x0F00)) - the error status flags.  Those flags are
     * HISTORY, not a hazard: SSCAREN is 0, the SSC keeps running with them set
     * (V50's raster advanced asicRunOk 1618 -> 9377 with SSCPE|SSCRE latched),
     * and they say nothing about whether a frame is on the wire now.  Worse,
     * the rule was SELF-POISONING.  The manual is explicit that the flags
     * "are not reset automatically upon entry into the error interrupt service
     * routine, but must be cleared by software"; SSCEIC is left at SSCEIE = 0
     * so hc_ssc_err_isr() never runs (V50 measured SSCEIC = 0x0080, request
     * pending and enable clear); and a write with SSCEN low targets the
     * control bits, not the flags.  Nothing clears them.  So the FIRST window
     * that straddled a frame set SSCRE and denied every window after it:
     * V50 programmed all 36 of its words inside 79 ms and was refused 4993
     * times over the next 3.9 s, then died on the deadline. */
    /* CLAIM FIRST (2026-10-13): the S5500 exchange is started by the 1 ms
       tick now, so a frame could launch between the in-flight test below
       and a later claim. Claimed here, asic_start_transfer() refuses any
       start from this point; a frame that started before it is seen by
       the test. Every reject below releases the claim. */
    lb[L_OWNER] = (unsigned char)HCNV_OWNER_NVM;
    sscon = hc_ssc_sscon();
    /* ... or a runtime frame is due within a millisecond: the frame goes
       first (2026-10-14; read from the tick itself, `now_ms` may be a
       pass old). A word claimed across the due time cost the raster a
       whole period on 5248F4C9 - me711_burn_raster_proof. */
    if (hc_asic_frame_in_flight() != 0u
        || (unsigned int)(hc_tick_ms - hc_asic_next_attempt)
           >= (unsigned int)(TGT_ASIC_RUN_PERIOD_MS - 1u)
        || ((sscon & 0x8000u) != 0u && (sscon & 0x1000u) != 0u)) {
        /* SSCBSY is bit 12 and only in operating mode; in programming mode
           that bit is SSCAREN, which TGT_ASIC_SSCCON_IDLE leaves clear, so the
           SSCEN guard keeps the test honest in both modes. */
        lb[L_ADMISSION] = (unsigned char)HCNV_ADMIT_ASIC;
        lb[L_PAUSE] = 4u;
        goto reject;
    }
    tx_left = hc_ssc_pec_tx_left();
    rx_left = hc_ssc_pec_rx_left();
    min_pec_words = (unsigned int)TGT_LIVE_PEC_MIN_WORDS;
    if (SSCBSY && (tx_left < min_pec_words || rx_left < min_pec_words)) {
        lb[L_ADMISSION] = (unsigned char)HCNV_ADMIT_PEC;
        lb[L_PAUSE] = 5u;
        goto reject;
    }

    remaining = (unsigned int)(REC_TOTAL_WORDS - be16(CB, CB_POS));
    set_be16(lb, L_PREDICT_MS,
             (unsigned int)(remaining / 2u)); /* 500 us/word data-sheet max */
    lb[L_ADMISSION] = (unsigned char)HCNV_ADMIT_READY;
    lb[L_PAUSE] = 0u;
    set_be16(lb, L_WINDOWS_OK, (unsigned int)(be16(lb, L_WINDOWS_OK) + 1u));
    hc_lf_admit(now_ms, (unsigned int)T7, be16(CB, CB_POS),
                HCNV_ADMIT_READY, sscon, (unsigned int)PECC0,
                (unsigned int)PECC4,
                (unsigned int)(((unsigned int)DP6 << 8) | P6),
                (unsigned int)T8REL, (unsigned int)T8,
                (unsigned int)T0, (unsigned int)CC7);
    return 1u;

reject:
    lb[L_OWNER] = (unsigned char)HCNV_OWNER_NONE;
    set_be16(lb, L_WINDOWS_NO, (unsigned int)(be16(lb, L_WINDOWS_NO) + 1u));
    return 0u;
}

/* V50. `dur` is xxIC read after the writer returned and before the restore;
   `aft` is the same register read after it.  IEN is 0 across both, so no ISR
   entry and no PEC service can have cleared xxIR in between: a bit that was
   set and is now clear was cleared BY THE RESTORE.  That is the V48/V49
   defect, and it is what must read zero on V50. */
static unsigned int ir_dropped(unsigned int dur, unsigned int aft,
                               unsigned int mask_value)
{
    return (unsigned int)(((dur & HCNV_IR_BIT) != 0u
                           && (aft & HCNV_IR_BIT) == 0u) ? mask_value : 0u);
}

static void fl_enter(void)
{
    unsigned char huge *lb = SRAMB(NVM_LIVE);
    unsigned char ien;
    unsigned int cc7, cc8, cc9, cc15, cc16, cc25, t8, s0r, s0e, ssct, sscr, ssce;
    unsigned int cc26, s0tb, cc27;
    unsigned int pending_before;
    unsigned int pending_after;
    unsigned char pec_in_flight = (unsigned char)(SSCBSY != 0);
    unsigned int t0;
    unsigned int dur_cc7, dur_t8, dur_ssct, dur_sscr, dur_ssce;
    unsigned int aft_cc7, aft_t8, aft_ssct, aft_sscr, aft_ssce;
    unsigned int dropped;
    unsigned int elapsed;
    unsigned char lf_guard;
    unsigned int lf_g24, lf_g25, lf_g26, lf_g27;

    /* THE RELOCATED WRITER STAMPS FOUR WORDS WITH NO CONDITION ON THEM.
       It cannot afford one: the whole programmer must stay inside the fixed
       1024-byte relocation, and a per-word test of the record's flags is
       instructions it does not have. So the condition lives HERE, outside
       the copy, where it costs nothing that matters.
       Without it a SECOND Burn - one this build's procedure forbids, but
       which nothing in the firmware prevents - would write over the frozen
       first-event evidence and break its seal. Save the four words the
       writer owns before entering it and put them back afterwards, so a
       frozen record survives byte for byte. */
    lf_guard = (unsigned char)(hc_lf_active() ? 0u : 1u);
    lf_g24 = HC_LF_WORD(LF_COMMAND_SEQ);
    lf_g25 = HC_LF_WORD(LF_VERIFY_SEQ);
    lf_g26 = HC_LF_WORD(LF_COMMAND_T7);
    lf_g27 = HC_LF_WORD(LF_VERIFY_T7);

    /* The only IEN=0 region is ownership and IC save/mask setup.  It ends
       BEFORE the CALLS that reaches the AM29 command.  The generated-listing
       gate verifies this ordering against the final image. */
    ien = (unsigned char)IEN;
    IEN = 0;
    cc7 = CC7IC; cc8 = CC8IC; cc9 = CC9IC; cc15 = CC15IC; t8 = T8IC;
    cc16 = CC16IC; cc25 = CC25IC;
    cc26 = TGT_PLAN_IC; s0tb = S0TBIC; cc27 = TGT_ASICX_IC;
    s0r = S0RIC; s0e = S0EIC;
    ssct = SSCTIC; sscr = SSCRIC; ssce = SSCEIC;
    pending_before = (unsigned int)(((cc7 & 0x80u) ? 1u : 0u)
                     | ((cc8 & 0x80u) ? 2u : 0u)
                     | ((cc9 & 0x80u) ? 4u : 0u)
                     | ((cc15 & 0x80u) ? 8u : 0u)
                     | ((t8 & 0x80u) ? 16u : 0u)
                     | ((ssct & 0x80u) ? 32u : 0u)
                     | ((sscr & 0x80u) ? 64u : 0u)
                     | ((ssce & 0x80u) ? 128u : 0u)
                     | ((s0r & 0x80u) ? 256u : 0u)
                     | ((s0e & 0x80u) ? 512u : 0u)
                     | ((cc16 & 0x80u) ? 1024u : 0u)
                     | ((cc25 & 0x80u) ? 2048u : 0u)
                     | ((cc26 & 0x80u) ? 4096u : 0u)
                     | ((s0tb & 0x80u) ? 8192u : 0u)
                     | ((cc27 & 0x80u) ? 16384u : 0u));
    /* clear ONLY xxIE.  xxIR is never written, so a request that becomes
       pending inside the window survives; ILVL/GLVL are never cleared, so they
       never have to be restored.  See the HCNV_IE_* note at the top. */
    CC7IC &= HCNV_IE_CLR; CC8IC &= HCNV_IE_CLR; CC9IC &= HCNV_IE_CLR;
    CC15IC &= HCNV_IE_CLR; T8IC &= HCNV_IE_CLR;
    /* CC25 runs clock checkpoints even with no queued actuator events.
       Both V102 handlers are flash-backed: preserve their requests while
       preventing a vector fetch during the RAM programmer's busy window.
       Admission already excludes actuator deadlines inside the guard. */
    CC16IC &= HCNV_IE_CLR; CC25IC &= HCNV_IE_CLR;
    /* the planner level (CC26, requested by the crank ISR) and
       the reply job (S0TBINT) are flash-backed handlers too. */
    TGT_PLAN_IC &= HCNV_IE_CLR; S0TBIC &= HCNV_IE_CLR;
    /* the S5500 exchange level (CC27, requested by the tick, 2026-10-13) */
    TGT_ASICX_IC &= HCNV_IE_CLR;
    /* ASC0 receive/error requests enter the flash-backed first-level vector
       path even where the Bosch boot block owns their final handler. */
    S0RIC &= HCNV_IE_CLR; S0EIC &= HCNV_IE_CLR; SSCEIC &= HCNV_IE_CLR;
    if (!pec_in_flight) { SSCTIC &= HCNV_IE_CLR; SSCRIC &= HCNV_IE_CLR; }
    /* bits 0..4 CC7/8/9/15,T8; 5..7 SSC TX/RX/ERR; 8..9 ASC RX/ERR;
       10..11 CC16/CC25; 12..13 CC26 planner / S0TB reply job; 14 CC27
       S5500 exchange.
       With PEC in flight only its terminal ordinary vectors remain enabled,
       so TX/RX are intentionally not represented as suppressed. */
    set_be16(lb, L_MASK, (unsigned int)(0x7F9Fu | (pec_in_flight ? 0u : 0x0060u)));
    set_be16(lb, L_PENDING_BEF, pending_before);

    /* IEN=1 before the command, through DQ polling, until the RAM writer has
       read back the word and returned the AM29 to read-array mode. */
    IEN = 1;
    t0 = (unsigned int)T7;
    HC_LF_WORD(LF_WR_ENTRY) = (unsigned int)(HC_LF_WORD(LF_WR_ENTRY) + 1u);
    /* V47's opaque inline CALLS hid the separately compiled writer's register
       use from Keil.  In the final V47 image, fl_enter kept lb in R12:R13,
       t0 in R1 and SSCEIC in R3, while the writer returned with R12=CB_POS
       and also clobbered R1/R3.  Preserve all exposed general registers here;
       R0 is the stack pointer and the writer itself preserves R13-R15. */
    __asm {
        PUSH R1
        PUSH R2
        PUSH R3
        PUSH R4
        PUSH R5
        PUSH R6
        PUSH R7
        PUSH R8
        PUSH R9
        PUSH R10
        PUSH R11
        PUSH R12
        CALLS #038H, #06000H
        POP R12
        POP R11
        POP R10
        POP R9
        POP R8
        POP R7
        POP R6
        POP R5
        POP R4
        POP R3
        POP R2
        POP R1
    }
    /* RETS is only reached after the writer has restored read-array. */
    IEN = 0;
    elapsed = (unsigned int)((unsigned int)T7 - t0);
    if (elapsed > be16(lb, L_MAX_WR_US)) {
        set_be16(lb, L_MAX_WR_US, elapsed);
    }
    dur_cc7 = CC7IC; dur_t8 = T8IC;
    dur_ssct = SSCTIC; dur_sscr = SSCRIC; dur_ssce = SSCEIC;
    /* V50 restore: set ONLY xxIE, and only where it was set at save time.
       Blindly ORing HCNV_IE_BIT would ENABLE a source the caller had found
       disabled - save_ssctic was 0xB8 and save_sscric 0x3C on the V49 event,
       both with IE already 0. */
    CC7IC  |= (cc7  & HCNV_IE_BIT);
    CC8IC  |= (cc8  & HCNV_IE_BIT);
    CC9IC  |= (cc9  & HCNV_IE_BIT);
    CC15IC |= (cc15 & HCNV_IE_BIT);
    CC16IC |= (cc16 & HCNV_IE_BIT);
    CC25IC |= (cc25 & HCNV_IE_BIT);
    TGT_PLAN_IC |= (cc26 & HCNV_IE_BIT);
    TGT_ASICX_IC |= (cc27 & HCNV_IE_BIT);
    S0TBIC |= (s0tb & HCNV_IE_BIT);
    T8IC   |= (t8   & HCNV_IE_BIT);
    S0RIC  |= (s0r  & HCNV_IE_BIT);
    S0EIC  |= (s0e  & HCNV_IE_BIT);
    SSCTIC |= (ssct & HCNV_IE_BIT);
    SSCRIC |= (sscr & HCNV_IE_BIT);
    SSCEIC |= (ssce & HCNV_IE_BIT);
    /* THE DISCRIMINATOR.  IEN is still 0 here, so between the reads above and
       the reads below no interrupt and no PEC transfer can clear an xxIR.  A
       request that was pending before the restore and is gone after it was
       destroyed BY the restore - which is exactly the V48/V49 defect, and
       exactly what must now read zero.  lost_or keeps its old meaning: a
       request AROSE while masked, which is legitimate and expected. */
    aft_cc7 = CC7IC; aft_t8 = T8IC;
    aft_ssct = SSCTIC; aft_sscr = SSCRIC; aft_ssce = SSCEIC;
    pending_after = (unsigned int)(((CC7IC & 0x80u) ? 1u : 0u)
                    | ((CC8IC & 0x80u) ? 2u : 0u)
                    | ((CC9IC & 0x80u) ? 4u : 0u)
                    | ((CC15IC & 0x80u) ? 8u : 0u)
                    | ((T8IC & 0x80u) ? 16u : 0u)
                    | ((SSCTIC & 0x80u) ? 32u : 0u)
                    | ((SSCRIC & 0x80u) ? 64u : 0u)
                    | ((SSCEIC & 0x80u) ? 128u : 0u)
                    | ((S0RIC & 0x80u) ? 256u : 0u)
                    | ((S0EIC & 0x80u) ? 512u : 0u)
                    | ((CC16IC & 0x80u) ? 1024u : 0u)
                    | ((CC25IC & 0x80u) ? 2048u : 0u)
                    | ((TGT_PLAN_IC & 0x80u) ? 4096u : 0u)
                    | ((S0TBIC & 0x80u) ? 8192u : 0u)
                    | ((TGT_ASICX_IC & 0x80u) ? 16384u : 0u));
    set_be16(lb, L_PENDING_AFT, pending_after);
    set_be16(lb, L_WRITER_ENT, (unsigned int)(be16(lb, L_WRITER_ENT) + 1u));
    if (SRAMB(NVM_CB)[CB_RESULT] == (unsigned char)HCNV_ERR_NONE) {
        set_be16(lb, L_WRITER_OK, (unsigned int)(be16(lb, L_WRITER_OK) + 1u));
    } else {
        set_be16(lb, L_WRITER_FAIL, (unsigned int)(be16(lb, L_WRITER_FAIL) + 1u));
    }
    lb[L_OWNER] = (unsigned char)HCNV_OWNER_NONE;
    IEN = ien;
    if (lf_guard != 0u) {
        HC_LF_WORD(LF_COMMAND_SEQ) = lf_g24;
        HC_LF_WORD(LF_VERIFY_SEQ)  = lf_g25;
        HC_LF_WORD(LF_COMMAND_T7)  = lf_g26;
        HC_LF_WORD(LF_VERIFY_T7)   = lf_g27;
        return;
    }
    dropped = ir_dropped(dur_cc7, aft_cc7, 0x0001u)
            | ir_dropped(dur_t8,  aft_t8,  0x0002u)
            | ir_dropped(dur_ssct, aft_ssct, 0x0004u)
            | ir_dropped(dur_sscr, aft_sscr, 0x0008u)
            | ir_dropped(dur_ssce, aft_ssce, 0x0010u);
    hc_lf_ir_after(dropped, be16(CB, CB_POS));
    hc_lf_writer_return((unsigned int)T7, elapsed);
    hc_lf_restore((unsigned int)T7, be16(CB, CB_POS),
                  cc7, t8, ssct, sscr, ssce,
                  dur_cc7, dur_t8, dur_ssct, dur_sscr, dur_ssce,
                  (unsigned int)SRAMB(NVM_CB)[CB_RESULT]);
}

/* ======================================================== THE RAM PROBE =====
 *
 * THE FLASH PROGRAMMER'S ONE UNVERIFIED PRECONDITION, TESTED WITH NOTHING AT
 * STAKE.
 *
 * hc_nvm_payload() runs from a copy of itself in the external SRAM at
 * TGT_RAM_FLASHRT, because the device it erases is the device the CPU normally
 * fetches from. Every gate in this repository proves that IN SIMULATION. No
 * HaniCore image has ever fetched one instruction from 0x380000 on a real
 * A1146 board - and if this board cannot do it, the first discovery would
 * otherwise be a half-erased calibration sector.
 *
 * So: copy a small routine into exactly that region, CALL it across the
 * segment boundary, have it do real work - a memory read, a loop, a
 * conditional branch, two memory writes - and RETURN. It touches no flash,
 * drives no pin, and changes no calibration.
 *
 * WHY IT IS NOT IN hcbench.c: that module's whole contract is that it is the
 * only code that may drive an engine output, and every invariant it carries is
 * about ports, cavities, pulse widths and channel counts. This drives nothing.
 * It belongs to the module whose precondition it is.
 *
 * WHY INTERRUPTS STAY ENABLED. The programmer runs with them off, which is the
 * stricter condition - but it runs before IEN = 1, and this does not. A probe
 * that hangs with interrupts disabled hangs the supervision link with it, and
 * a hang is one of the outcomes being tested for. With them on, a board that
 * cannot execute from SRAM produces a reset, and RP_STATE still says RUNNING
 * afterwards.
 *
 * WHY THE SEED IS NOT A CONSTANT. A probe that returns the same number
 * whatever happened proves nothing: the answer has to depend on an input the
 * caller chose this run. The transform is deliberately a loop with a branch in
 * it, so a board that can fetch straight-line code but not take a branch from
 * SRAM fails rather than passes.
 */
#define RP_SIG_VALUE  0x5A3Cu

/* The transform, computed HERE - from flash - as the expected answer. The
   authoritative independent model is the Python one in me711_ramprobe_proof;
   this copy only lets the ECU report pass or fail without a host. */
static unsigned int ram_mix(unsigned int seed)
{
    unsigned int r = seed;
    unsigned int i;

    for (i = 0u; i < 16u; i++) {
        if ((r & 0x8000u) != 0u) {
            r = (unsigned int)((r << 1) ^ 0x1021u);
        } else {
            r = (unsigned int)(r << 1);
        }
    }
    return r;
}

/* THE ROUTINE THAT RUNS FROM SRAM.
 *
 * `far` IS THE WHOLE TRICK, AND THE FIRST ATTEMPT GOT IT WRONG. It is entered
 * with CALLS, which pushes CSP and IP, so it has to leave with RETS - and an
 * ordinary near function ends in RET, which would pop one word and leave the
 * segment on the stack. Writing `__asm { RETS }` at the end of a near function
 * looks like it works and is a trap: the compiler may have pushed registers in
 * a prologue that the hand-written return never unwinds.
 *
 * Keil said so itself, which is why this is not that:
 *
 *     WARNING C195 IN LINE 1016 OF hcnvm.c:
 *         inline-asm: 'far' return in 'near' function
 *
 * `void far` makes C166 emit `PROC FAR` and its own RETS, with a prologue and
 * epilogue that match by construction. Verified in the compiler's own output -
 * the project's standing rule, and this project has been caught four times by
 * not doing it.
 *
 * It is not static: a static function is not in the linker map, and a gate
 * that cannot name what it is checking is checking something else. */
void far hc_nvm_ramprobe(void)
{
    unsigned char huge *rp = SRAMB(NVM_RP);
    unsigned int r;
    unsigned int i;

    r = (unsigned int)(((unsigned int)rp[RP_SEED] << 8) | rp[RP_SEED + 1u]);
    for (i = 0u; i < 16u; i++) {
        if ((r & 0x8000u) != 0u) {
            r = (unsigned int)((r << 1) ^ 0x1021u);
        } else {
            r = (unsigned int)(r << 1);
        }
    }
    rp[RP_RESULT]      = (unsigned char)(r >> 8);
    rp[RP_RESULT + 1u] = (unsigned char)r;
    /* the signature LAST, so a routine that ran only half way is detectable */
    rp[RP_SIG]         = (unsigned char)(RP_SIG_VALUE >> 8);
    rp[RP_SIG + 1u]    = (unsigned char)RP_SIG_VALUE;
}

/* An address marker, exactly as for hc_nvm_payload: the gate derives the
   routine length rather than being told it twice. It is far for the same
   reason its neighbour is - so the linker orders them together and the
   difference really is the routine length. */
void far hc_nvm_ramprobe_end(void)
{
}

/* THE CALL, ON ITS OWN, AND THAT IS NOT COSMETIC.
 *
 * A bare __asm CALLS inside hc_nvm_ramtest() would be invisible to the
 * compiler's register allocator, which would happily keep a pointer or a loop
 * counter live in a register across it while the routine in SRAM used the same
 * one. Putting it in its own function makes it an ordinary C call at the point
 * of use, so the caller saves what it needs by the normal convention. */
static void ram_enter(void)
{
    __asm { CALLS #038H, #06000H }
}

unsigned int hc_nvm_ramtest(unsigned int seed, unsigned char safe)
{
    unsigned char huge *rp = SRAMB(NVM_RP);
    unsigned char huge *dst = SRAMB(NVM_RT);
    unsigned char huge *code;
    unsigned int i;

    if (hc_ram_bad) {
        return (unsigned int)HCNV_RP_REFUSED;
    }
    /* A REFUSAL, NOT A SILENT NO-OP. If this board cannot execute from SRAM
       the probe ends in a reset, and a reset is not something to hand an
       engine that might be turning. */
    if (safe == 0u) {
        rp[RP_STATE] = (unsigned char)HCNV_RP_UNSAFE;
        return (unsigned int)HCNV_RP_UNSAFE;
    }
    if (seed == 0u) {
        seed = 0xACE1u;             /* 0 shifts to 0 and would prove nothing */
    }

    set_be32(rp, RP_MAGIC, NVM_RP_MAGIC);
    set_be16(rp, RP_RUNS, (unsigned int)(be16(rp, RP_RUNS) + 1u));
    set_be16(rp, RP_SEED, seed);
    set_be16(rp, RP_RESULT, 0u);
    set_be16(rp, RP_SIG, 0u);
    /* PUBLISHED BEFORE THE JUMP. If the CPU does not come back, this is the
       only thing that will say why, and it survives the reset. */
    rp[RP_STATE] = (unsigned char)HCNV_RP_RUNNING;

    code = SRAMB(TGT_CODE_BASE
                 + (unsigned long)(unsigned int)&hc_nvm_ramprobe);
    for (i = 0u; i < 1024u; i++) {
        dst[i] = code[i];
    }

    ram_enter();

    if (be16(rp, RP_SIG) != RP_SIG_VALUE) {
        rp[RP_STATE] = (unsigned char)HCNV_RP_NOSIG;
    } else if (be16(rp, RP_RESULT) != ram_mix(seed)) {
        rp[RP_STATE] = (unsigned char)HCNV_RP_WRONG;
    } else {
        rp[RP_STATE] = (unsigned char)HCNV_RP_PASS;
    }
    return (unsigned int)rp[RP_STATE];
}

unsigned int hc_nvm_ram_state(void)
{
    return (unsigned int)SRAMB(NVM_RP)[RP_STATE];
}

unsigned int hc_nvm_ram_runs(void)
{
    return be16(SRAMB(NVM_RP), RP_RUNS);
}

unsigned int hc_nvm_ram_seed(void)
{
    return be16(SRAMB(NVM_RP), RP_SEED);
}

unsigned int hc_nvm_ram_result(void)
{
    return be16(SRAMB(NVM_RP), RP_RESULT);
}

/* ================================================ the programmer's diary ===
 *
 * Written by hc_nvm_payload() while it programs, and by nvm_commit() around
 * it. NOT CRC-protected, never read back as truth, and outside every boot
 * decision: it is evidence for a human. See hcnvm.h.
 */
#define DGB      SRAMB(NVM_DG)
#define NVM_RETRY_ISSUE  0xFDu

static unsigned int dg16(unsigned int off)
{
    return be16(DGB, off);
}

static void dg_set16(unsigned int off, unsigned int v)
{
    set_be16(DGB, off, v);
}

/* Cleared at the START of every commit, so the numbers a bench reads always
   belong to the Burn in front of it and never to the one before. */
static void dg_begin(void)
{
    unsigned int i;

    for (i = 0u; i < (unsigned int)DG_LEN; i++) {
        DGB[i] = 0u;
    }
    set_be32(DGB, (unsigned int)DG_MAGIC, NVM_DG_MAGIC);
    dg_set16((unsigned int)DG_WORD, 0xFFFFu);   /* no word has failed yet */
    dg_set16((unsigned int)DG_POLLMIN, 0xFFFFu);
}

/* This runs only after the failed RAM invocation has sent F0 and returned to
   ordinary flash code. nvm_commit() deliberately returned for a whole
   main-loop pass before calling it. It is therefore the right place for the
   retry predicate: it keeps the RAM writer small enough for the fixed 1 KiB
   relocation while proving the actual NOR word can only move 1->0. */
static void dg_observe(unsigned int pos, unsigned int v,
                       unsigned int a, unsigned int b, unsigned int flags)
{
    dg_set16((unsigned int)DG_WORD, pos);
    dg_set16((unsigned int)DG_EXP, v);
    dg_set16((unsigned int)DG_GOT1, a);
    dg_set16((unsigned int)DG_GOT2, b);
    dg_set16((unsigned int)DG_FLAGS,
             (unsigned int)(dg16((unsigned int)DG_FLAGS) | flags));
}

/* HCNV_ERR_NONE: target is already the desired datum; HCNV_ERR_PROGRAM:
   unexpected zero bit, never retry; NVM_RETRY_ISSUE: safely reissue; and
   HCNV_RES_RETRY: still not a stable read-array result, consume one bounded
   recovery pass before looking again. */
static unsigned int retry_target(void)
{
    unsigned int volatile huge *p;
    unsigned int huge *s;
    unsigned int pos;
    unsigned int a;
    unsigned int b;
    unsigned int v;
    unsigned int cell;

    /* READ THE CELL INDEX ONCE, INTO A LOCAL, AND CHECK IT BEFORE FORMING AN
     * ADDRESS FROM IT. Both halves of that sentence are load-bearing.
     *
     * THE CODEGEN HALF. CELL_ADDR() expands its argument THREE times - once in
     * CELL_SEG, once in CELL_PAGEOFF - and `cb_cell` is CB[CB_CELL], a byte
     * behind a huge pointer into the battery-backed SRAM at 0x386806. With the
     * macro written straight into the 32-bit address expression, Keil C166
     * 7.53 emitted the duplicated byte loads WITHOUT their EXTS #38h segment
     * override:
     *
     *     0x84090C  EXTS #38h + MOVB RL4,[6806]   correct
     *     0x8422F2            MOVB RL4,[6806]     <- here, no prefix
     *     0x842300            MOVB RL4,[6806]     <- here, no prefix
     *     0x84246E  EXTS #38h + MOVB RL4,[6806]   correct
     *     0x842596  EXTS #38h + MOVB RL4,[6806]   correct
     *     0x84358E  EXTS #38h + MOVB RL4,[6806]   correct
     *
     * A bare 0x6806 resolves through DPP1, which points at NCONST, so these
     * two read a CONSTANT BYTE - 0xFF as it happens - instead of the cell
     * index. Four of six sites are right and two are wrong, in one function.
     * Read the listing; do not reason about it.
     *
     * WHY IT NEVER SHOWED UP BEFORE, and why it is NOT a V53 defect: this
     * function only runs when a word fails to program, and on this ECU no word
     * ever has - 88 physical Burns, nvmRetries 0, nvmProgFlags 0, every word
     * taken first time. V52 carried the identical miscompile; its two-sector
     * CELL_ADDR clamped ANY index to CFG_A or CFG_B, so the garbage produced a
     * MAPPED address, it read the wrong word, and the burn limped on. V53's
     * ten-sector CELL_SEG turns 0xFF into segment 0xA5, which is not mapped at
     * all - so the same latent bug finally became visible, as a hang.
     *
     * THE RANGE HALF. An index that cannot be a cell must be REFUSED, not
     * turned into an address. That is what makes this deterministic whatever a
     * future compiler does with the expression. */
    cell = (unsigned int)cb_cell;
    if (cell >= (unsigned int)TGT_FLASH_CELLS) {
        dg_observe(0u, 0u, 0u, 0u, HCNV_PF_UNSAFE);
        return HCNV_ERR_PROGRAM;
    }
    pos = be16(CB, (unsigned int)CB_POS);
    p = FLW(CELL_ADDR(cell)) + pos;
    s = SRAMW(NVM_STAGE) + pos;
    v = *s;
    a = *p;
    b = *p;
    dg_observe(pos, v, a, b, 0u);
    if (a != b) {
        *FLW(TGT_FLASH_UNLOCK1) = FL_RESET;
        dg_observe(pos, v, a, b, HCNV_PF_NOTIDLE | HCNV_PF_DISAGREE);
        return HCNV_RES_RETRY;
    }
    if (a == v) {
        /* Two independent, stable reads after F0 and a complete service pass
           are a physical verification. A late completion needs no second
           program command. */
        return HCNV_ERR_NONE;
    }
    if ((unsigned int)(a & v) != v) {
        dg_observe(pos, v, a, b, HCNV_PF_UNSAFE);
        return HCNV_ERR_PROGRAM;
    }
    dg_set16((unsigned int)DG_RETRIES,
             (unsigned int)(dg16((unsigned int)DG_RETRIES) + 1u));
    return NVM_RETRY_ISSUE;
}

/* Called only in ordinary flash code: immediately before/after fl_enter(),
 * and before nvm_fail() clears state.  It deliberately does not run from the
 * SRAM writer or with IEN cleared. */
static void forensic_snapshot(unsigned char writer_result)
{
    unsigned int have_diary = (unsigned int)(be32(DGB, (unsigned int)DG_MAGIC)
                                             == NVM_DG_MAGIC);
    hc_bf_nvm_snapshot(cb_state, cb_phase, SRAMB(NVM_CB)[CB_RESULT], cb_cell,
                       be16(CB, (unsigned int)CB_POS),
                       be16(CB, (unsigned int)CB_ATTEMPTS), cb_err,
                       writer_result,
                       have_diary ? dg16((unsigned int)DG_RETRIES) : 0u,
                       have_diary ? dg16((unsigned int)DG_WORD) : 0xFFFFu,
                       have_diary ? dg16((unsigned int)DG_EXP) : 0u,
                       have_diary ? dg16((unsigned int)DG_GOT1) : 0u,
                       have_diary ? dg16((unsigned int)DG_GOT2) : 0u,
                       have_diary ? dg16((unsigned int)DG_POLLMIN) : 0xFFFFu,
                       have_diary ? dg16((unsigned int)DG_POLLMAX) : 0u);
}

/* Commit-stage trace values, visible in TS via OCH.
 * stage is the current point; lastStage only rises through meaningful reached
 * points; failStage snapshots lastStage at terminal failure. A new request is
 * the only normal reset, so retries and idle service preserve the evidence. */
#define CST_IDLE           0u
#define CST_ENTRY          1u   /* entered nvm_commit first-entry block      */
#define CST_STAGE_VALID    2u   /* stage_valid() passed                      */
#define CST_CELL_BLANK     3u   /* cell_blank() passed                       */
#define CST_ATTEMPTS_INC   4u   /* cb_attempts incremented                   */
#define CST_STATE_COMMIT   5u   /* cb_state = COMMITTING                     */
#define CST_DG_BEGIN       6u   /* dg_begin() done                           */
#define CST_FL_PREPARE     7u   /* fl_prepare() done (writer copied)         */
#define CST_WRITER_LOOP    8u   /* entered fl_enter() writer loop            */
#define CST_WORD_DONE      9u   /* one word programmed successfully          */
#define CST_RETRY_HANDLED 10u   /* HCNV_RES_RETRY handled                    */
#define CST_RETRY_TARGET  11u   /* retry_target() executed                   */
#define CST_DONE_VERIFY   12u   /* DONE verified, scan complete              */

static void trace_begin(void)
{
    /* hc_bf_b_received() begins the retained trace before this request is
       accepted.  Keeping this no-op prevents the V44 working-block alias
       from returning through a maintenance call site. */
}

static void trace_stage(unsigned char stage)
{
    /* V44 stage numbers were writer implementation details.  V45 maps only
       executable transaction boundaries to the forensic contract. */
    switch (stage) {
    case CST_STATE_COMMIT:
        hc_bf_stage(HCBF_ST_COMMITTING);
        break;
    case CST_FL_PREPARE:
        hc_bf_stage(HCBF_ST_PREPARED);
        break;
    case CST_WRITER_LOOP:
        hc_bf_stage(HCBF_ST_WRITER_ENTER);
        break;
    case CST_WORD_DONE:
        hc_bf_stage(HCBF_ST_PROGRESS);
        break;
    case CST_RETRY_HANDLED:
    case CST_RETRY_TARGET:
        hc_bf_stage(HCBF_ST_RETRY);
        break;
    case CST_DONE_VERIFY:
        hc_bf_stage(HCBF_ST_DONE);
        break;
    default:
        break;
    }
}

static void trace_fail(void)
{
    /* nvm_fail() records reason and stage before it clears the control block. */
}

/* ============================================================ the failure == */
static void nvm_fail(unsigned int why)
{
    forensic_snapshot((unsigned char)SRAMB(NVM_CB)[CB_RESULT]);
    hc_bf_fail((unsigned char)why);
    trace_fail();
    cb_state = (unsigned char)HCNV_ST_FAILED;
    cb_phase = (unsigned char)HCNV_PH_NONE;
    cb_err = (unsigned char)why;
    set_be16(CB, (unsigned int)CB_ATTEMPTS, 0u);
    stage_clear();          /* stop retrying - the OLD record still stands */
    cb_seal();
    hc_lf_recover((unsigned int)cb_state, why, be16(CB, CB_POS),
                  HC_LF_WORD(LF_RESET_RAW));
    /* A FAILED BURN IS NOT AN UNRECOGNISED COMMAND, AND SAYING SO COST THE
     * TUNERSTUDIO SESSION.
     *
     * This answered TS_BAD_CMD from V40 until V59. 0x83 is
     * TS_RESPONSE_UNRECOGNIZED_COMMAND, and TunerStudio 3.3.01 said what it
     * thought of that in its own log: `Controller Reported a Unrecognized
     * Command!`, `call failed protocol validation`, `Going offline before all
     * changes were permanently saved`, and then four reconnects.
     *
     * AND THE FIRST FIX FOR IT WAS ALSO WRONG, WHICH IS WHY THIS COMMENT IS
     * LONG. TS_OUT_OF_RANGE looked right - it is what rusEFI answers a Burn it
     * cannot perform with, tunerstudio.cpp:540 - and TunerStudio treats it
     * EXACTLY the same. Read out of TunerStudioMS.jar, class J/f: every code
     * with bit 7 set fails the packet and ends the session, all eleven of
     * them, and a code with bit 7 clear is accepted without being looked at.
     * There is no soft error code in this protocol. See hcts.h.
     *
     * So the reply says "I am finished with your request" and the OUTCOME is
     * published where a tuner can read it and act on it: cb_state is
     * HCNV_ST_FAILED, cb_err is the reason, and hc_cfg_validation and
     * hc_val_first_bad_offset name the setting that has to change. The old
     * record still stands, which is the whole point of the append-only store.
     *
     * MEASURED ON THIS ECU, 2026-09-16, V59, with the page left in exactly the
     * state 12I's A/B/A table describes - syncMode = 1 with pinCrank
     * unassigned. Four Burns, four `00 01 83 A6 B3 3D 17` replies at 22-58 ms,
     * and rstBootCount never moved: no reset, no lost byte, no parser residue.
     * It was only ever the response code.
     * bench measurements */
    hcts_finish_deferred_response(TS_REFUSED);
}

/* ============================================================== the commit ==
 *
 * Called only from hc_nvm_boot(), only before the supervision link is up and
 * only before IEN = 1.
 *
 * The state machine is driven by EVIDENCE READ OUT OF THE DEVICE, not by a
 * flag the programmer had to leave behind: "did the last attempt work" is
 * answered by asking whether the target slot now holds a valid record with the
 * staged generation. That is the strongest available test and it is immune to
 * the programmer being reset before it could write anything down.
 */
static void nvm_select(void);

static void nvm_commit(unsigned int now_ms, unsigned int rpm,
                       unsigned char trig_turning,
                       unsigned char outputs_busy,
                       unsigned char page_stable)
{
    unsigned int target;
    unsigned int t0;
    unsigned int r;
    unsigned int tries;

    /* A completed transaction is recognised from the flash record, not from a
       transient RAM result. This is also the recovery path after power loss. */
    trace_stage(CST_ENTRY);
    target = (unsigned int)cb_cell;
    if (target >= TGT_FLASH_CELLS) {
        nvm_fail(HCNV_ERR_FULL);
        return;
    }
    if (cell_scan(target) == HCNV_ERR_NONE
        && cell_last_gen_get() == cb_gen_get()) {
        cb_state = (unsigned char)HCNV_ST_DONE;
        cb_phase = (unsigned char)HCNV_PH_NONE;
        cb_err = (unsigned char)HCNV_ERR_NONE;
        set_be16(CB, (unsigned int)CB_ATTEMPTS, 0u);
        stage_clear();
        cb_seal();
        set_be16(NVW, W_COMMITS,
                 (unsigned int)(be16(NVW, W_COMMITS) + 1u));
        nvm_scan();                 /* the new record is now the active one */
        nvm_select();               /* publish FLASH_A/B live, no reboot */
        trace_stage(CST_DONE_VERIFY);
        hc_bf_stage(HCBF_ST_OK_PENDING);
        forensic_snapshot((unsigned char)SRAMB(NVM_CB)[CB_RESULT]);
        hc_lf_durable(now_ms, be16(CB, CB_POS));
        hcts_finish_deferred_response(TS_OK);
        return;
    }

    if (cb_state != (unsigned char)HCNV_ST_COMMITTING) {
        /* THE ENTRY PASS, AND EVERYTHING EXPENSIVE HAPPENS ONLY HERE.
         *
         * stage_valid() walks the whole 4096-byte payload and cell_blank()
         * walks the whole 8188-byte cell body. The first version of the V40
         * live commit ran BOTH on every programming chunk, and the service-gap
         * proof measured the result exactly: 322991 instructions = 32.3 ms of
         * hardware time in ONE main-loop pass, against a 10 ms raster, times
         * the ~129 passes a record takes. That is the V35 defect one level up
         * - the long work had moved out of the command handler and into a loop
         * that runs it again for every 16 words.
         *
         * Hoisting them is SOUND and not merely cheaper: the staged record
         * cannot change while COMMITTING. A TunerStudio page write lands in
         * the calibration page at TGT_RAM_CFG, never in TGT_RAM_FLASHBUF, and
         * hc_nvm_request() - the only thing that rebuilds the buffer - moves
         * the state to STAGING, which this function is never called in. The
         * cell cannot un-blank either: this writer is the only thing that
         * programs it. */
        if (!stage_valid()) {
            nvm_fail(HCNV_ERR_STAGE);
            return;
        }
        trace_stage(CST_STAGE_VALID);
        if (!cell_blank(target)) {
            /* THE CELL IS CONSUMED. A reset after any program command leaves
               one like this, and so does a half-erased sector whose magic word
               came back to 0xFFFF ahead of its body - see cell_candidate().
               Either way it may NEVER be programmed: NOR only clears bits, so
               writing a record over a dirty cell could make a torn header look
               valid.
               
               UP TO V52 THIS FAILED THE BURN, and with sixteen never-erased
               cells that was defensible. With a store that is reclaimed it is
               not: one damaged cell would refuse every Burn until a reflash.
               So step to the next candidate and let the next pass try it. The
               attempt counter bounds this, so a store full of damaged cells
               still terminates instead of looping. */
            unsigned int nxt = next_candidate(target);
            set_be16(CB, (unsigned int)CB_ATTEMPTS,
                     (unsigned int)(cb_attempts_get() + 1u));
            if (nxt >= (unsigned int)TGT_FLASH_CELLS
                || cb_attempts_get() > (unsigned int)HCNV_MAX_ATTEMPTS) {
                nvm_fail(HCNV_ERR_PROGRAM);
                return;
            }
            cb_cell = (unsigned char)nxt;
            cb_seal();
            return;
        }
        trace_stage(CST_CELL_BLANK);
        set_be16(CB, (unsigned int)CB_ATTEMPTS,
                 (unsigned int)(cb_attempts_get() + 1u));
        trace_stage(CST_ATTEMPTS_INC);
        if (cb_attempts_get() > (unsigned int)HCNV_MAX_ATTEMPTS) {
            /* Bounded on purpose. A commit that keeps being interrupted must
               stop trying rather than leave the ECU rebooting forever - and
               the old record is untouched, so stopping is safe. */
            nvm_fail(HCNV_ERR_RETRIES);
            return;
        }
        cb_state = (unsigned char)HCNV_ST_COMMITTING;
        trace_stage(CST_STATE_COMMIT);
        cb_phase = (unsigned char)HCNV_PH_PROGRAM;
        set_be16(CB, (unsigned int)CB_POS, 0u);
        cb_seal();
        SRAMB(NVM_CB)[CB_RESULT] = 0xFFu;
        dg_begin();
        trace_stage(CST_DG_BEGIN);
        fl_prepare_sel((unsigned char)HCNV_PAY_WRITER);
        trace_stage(CST_FL_PREPARE);
} else if (SRAMB(NVM_CB)[CB_RESULT] != 0xFFu
               && SRAMB(NVM_CB)[CB_RESULT] != (unsigned char)HCNV_ERR_NONE
               && SRAMB(NVM_CB)[CB_RESULT] != (unsigned char)HCNV_RES_RETRY) {
        /* A bounded RAM invocation reported a program or verify failure. */
        nvm_fail((unsigned int)SRAMB(NVM_CB)[CB_RESULT]);
        return;
    }

    /* retry_target() can also ask for another recovery pass when the two
       read-array samples still toggle. Account that pre-existing result before
       inspecting it again, so a dead or permanently busy device is bounded. */
    if (SRAMB(NVM_CB)[CB_RESULT] == (unsigned char)HCNV_RES_RETRY) {
        trace_stage(CST_RETRY_HANDLED);
        tries = (unsigned int)(dg16((unsigned int)DG_TRY) + 1u);
        dg_set16((unsigned int)DG_TRY, tries);
        if (tries > (unsigned int)((dg16((unsigned int)DG_FLAGS) >> 8)
                                   & 0x00FFu)) {
            dg_set16((unsigned int)DG_FLAGS,
                     (unsigned int)((dg16((unsigned int)DG_FLAGS)
                                     & 0x00FFu)
                                    | ((tries & 0x00FFu) << 8)));
        }
        if (tries >= (unsigned int)HCNV_PROG_TRIES) {
            dg_set16((unsigned int)DG_FLAGS,
                     (unsigned int)(dg16((unsigned int)DG_FLAGS)
                                    | HCNV_PF_GAVEUP));
            nvm_fail((be16(CB, (unsigned int)CB_POS)
                      < (unsigned int)REC_PROG_WORDS)
                     ? HCNV_ERR_PROGRAM : HCNV_ERR_VERIFY);
            return;
        }
        SRAMB(NVM_CB)[CB_RESULT] = 0xFFu;
        return;
    }

    /* The first failure was accounted by the previous pass and made it return.
       On this later main-loop pass, prove the actual NOR target is retry-safe
       before any new AA/55/A0 sequence. */
    if (dg16((unsigned int)DG_TRY) != 0u) {
        trace_stage(CST_RETRY_TARGET);
        r = retry_target();
        if (r == (unsigned int)HCNV_ERR_NONE) {
            set_be16(CB, (unsigned int)CB_POS,
                     (unsigned int)(be16(CB, (unsigned int)CB_POS) + 1u));
            dg_set16((unsigned int)DG_FLAGS,
                     (unsigned int)(dg16((unsigned int)DG_FLAGS)
                                    | HCNV_PF_RETRY_OK));
            dg_set16((unsigned int)DG_TRY, 0u);
            SRAMB(NVM_CB)[CB_RESULT] = (unsigned char)HCNV_ERR_NONE;
            return;
        }
        if (r == (unsigned int)HCNV_ERR_PROGRAM) {
            nvm_fail(HCNV_ERR_PROGRAM);
            return;
        }
        if (r == (unsigned int)HCNV_RES_RETRY) {
            /* Still not a stable read-array result: consume a bounded recovery
               pass, without a command or cursor movement. */
            SRAMB(NVM_CB)[CB_RESULT] = (unsigned char)HCNV_RES_RETRY;
            return;
        }
        /* NVM_RETRY_ISSUE: blank or only-progress-towards-v; the RAM writer
           below may now emit the same legal four-cycle program sequence. */
    }

    /* ONE INDEPENDENTLY ADMITTED AM29 WORD PER WINDOW, AND AS MANY WINDOWS AS
     * HCNV_PASS_US ALLOWS.
     *
     * V47 (138b6cc) made this exactly one word per MAIN-LOOP PASS and left
     * the paragraph on HCNV_PASS_US standing above - the one that says, in
     * this file's own words, that one chunk per pass "made a Burn take about
     * 2.7 SECONDS end to end" and that "a TunerStudio that gives up before it
     * arrives loses precisely the session this whole design exists to keep".
     * The rationale stayed and the bound went with it.
     *
     * TWO THINGS WERE CONFLATED AND ONLY ONE OF THEM IS SAFETY.
     *   - a fresh engine/ASIC/PEC admission before EVERY word is V48's rule
     *     and it is kept EXACTLY: the loop re-enters live_admit() at the top,
     *     so the crank horizon, TGT_LIVE_WORD_GUARD_US and the frame-phase
     *     test are evaluated again for every single word.
     *   - returning to the main loop after every word is NOT a safety
     *     property. It is what made the Burn's wall time a multiple of the
     *     main-loop period: 2060 words x 0.71 ms of ordinary runtime that
     *     nothing in the writer needed.
     *
     * MEASURED ON THE ECU, 2026-09-16: 2.93 s stopped and 5.0 s at 199 rpm
     * on V56, against a 6000 ms deadline and TunerStudio's 8000 ms
     * blockReadTimeout. The budget was being spent on the scheduler, not on
     * the flash.
     *
     * WHAT BOUNDS IT NOW IS WHAT BOUNDED IT AT V40: HCNV_PASS_US, one quarter
     * of the S5500 raster, with hcts_target_yield() between words - which
     * since V52 services the watchdog as well as the raster. Interrupts are
     * ON between words; fl_enter() restores the state it found. The retry
     * path still returns immediately, because that boundary IS a safety
     * property and is documented where it is taken. */
    t0 = (unsigned int)T7;
    trace_stage(CST_WRITER_LOOP);
    for (;;) {
        if (!live_admit(now_ms, rpm, trig_turning, outputs_busy, page_stable)) {
            if (SRAMB(NVM_LIVE)[L_ADMISSION] == (unsigned char)HCNV_ADMIT_DEADLINE) {
                nvm_fail(HCNV_ERR_DEADLINE);
            }
            return;
        }
        /* THE SLOT MUST HOLD THE WRITER. See fl_prepare_sel(): a commit
           resumed after a reset skips the entry pass that would have loaded
           it, and if that reset interrupted a reclaim the eraser is still
           there. Re-preparing is a 2048-byte SRAM copy and it happens at most
           once per resumed commit. */
        if (SRAMB(NVM_ER)[ER_LOADED] != (unsigned char)HCNV_PAY_WRITER) {
            fl_prepare_sel((unsigned char)HCNV_PAY_WRITER);
        }
        forensic_snapshot((unsigned char)0xFFu);
        hc_bf_stage(HCBF_ST_WRITER_ENTER);
        fl_enter();
        r = (unsigned int)SRAMB(NVM_CB)[CB_RESULT];
        forensic_snapshot((unsigned char)r);
        hc_bf_stage(HCBF_ST_WRITER_RETURN);
        if (r == (unsigned int)HCNV_RES_RETRY) {
            /* A WORD DID NOT TAKE, AND THAT IS NOT YET A FAILURE.
             *
             * The writer has already reset the device and left the cursor on
             * that word. Re-entering programs it again - NOR only clears bits
             * and the word is verifiably still erased, so re-issuing the
             * command sequence is idempotent - and it does so after a whole
             * main-loop pass with interrupts on, which is far more quiet time
             * than any loop inside the writer could give it.
             *
             * BOUNDED AND COUNTED, so this cannot turn a dead device into a
             * green light: after HCNV_PROG_TRIES attempts on one word the Burn
             * fails and hc_nvm_fail_*() say exactly what was seen. */
            tries = (unsigned int)(dg16((unsigned int)DG_TRY) + 1u);
            dg_set16((unsigned int)DG_TRY, tries);
            if (tries > (unsigned int)((dg16((unsigned int)DG_FLAGS) >> 8)
                                       & 0x00FFu)) {
                dg_set16((unsigned int)DG_FLAGS,
                         (unsigned int)((dg16((unsigned int)DG_FLAGS)
                                         & 0x00FFu)
                                        | ((tries & 0x00FFu) << 8)));
            }
            if (tries >= (unsigned int)HCNV_PROG_TRIES) {
                dg_set16((unsigned int)DG_FLAGS,
                         (unsigned int)(dg16((unsigned int)DG_FLAGS)
                                        | HCNV_PF_GAVEUP));
                nvm_fail((be16(CB, (unsigned int)CB_POS)
                          < (unsigned int)REC_PROG_WORDS)
                          ? HCNV_ERR_PROGRAM : HCNV_ERR_VERIFY);
                return;
            }
            /* This return is the retry's safety boundary. In particular, do
               NOT let the HCNV_PASS_US loop immediately CALLS back into RAM:
               the next command gets the rest of this main-loop pass, all
               ordinary services, and the next pass with interrupts enabled. */
            SRAMB(NVM_CB)[CB_RESULT] = 0xFFu;
            hc_bf_stage(HCBF_ST_RETRY);
            return;
        } else if (r != (unsigned int)HCNV_ERR_NONE) {
            nvm_fail(r);
            return;
        } else if (dg16((unsigned int)DG_TRY) != 0u) {
            /* It took on a re-issued sequence. Say so - this is the single
               most useful thing a bench Burn can report. */
            dg_set16((unsigned int)DG_FLAGS,
                     (unsigned int)(dg16((unsigned int)DG_FLAGS)
                                    | HCNV_PF_RETRY_OK));
            dg_set16((unsigned int)DG_TRY, 0u);
        }
        trace_stage(CST_WORD_DONE);
        /* The platform, between every word: the 10 ms supervision raster and
           the 200.7 ms watchdog, both behind the tick gate. */
        hcts_target_yield();
        if (be16(CB, (unsigned int)CB_POS)
            >= (unsigned int)REC_TOTAL_WORDS) {
            /* Every word is in. The DONE marker is only BELIEVED once it has
               been read back out of the device, which is the next pass's job
               and not this loop's. */
            return;
        }
        if ((unsigned int)((unsigned int)T7 - t0)
            >= (unsigned int)US_TO_TICKS(HCNV_PASS_US)) {
            return;
        }
        /* Round again - and the next word takes its OWN fresh admission at
           the top of this loop, which is the whole of V48's rule. */
    }
}

/* ================================================== boot-time selection ==== */
static void nvm_select(void)
{
    unsigned char huge *p;
    unsigned int i;

    if (NVW[W_SLOT] == (unsigned char)HCNV_SLOT_NONE) {
        NVW[W_SOURCE] = (unsigned char)((hc_cfg_source == 1u)
                                        ? HCNV_SRC_STANDBY
                                        : HCNV_SRC_DEFAULTS);
        return;
    }

    if (hc_cfg_source == 1u) {
        /* The battery-backed page survived its own header check, so it stays.
         *
         * AND IT IS THE LAST BURN, not some half-edited intermediate. That is
         * worth spelling out because it is not obvious: hc_cfg_init() only
         * accepts the standby page when cfg_sum() matches the stored header
         * sum, and the ONLY thing that recomputes that sum is hc_cfg_commit()
         * - which is what a burn calls. A page edited live and never burned
         * therefore fails its own checksum at the next boot and is discarded,
         * exactly as if it had never been written. Standby and flash cannot
         * diverge. */
        NVW[W_SOURCE] = (unsigned char)HCNV_SRC_STANDBY;
        return;
    }

    /* No usable standby page - a cold ECU, or a corrupted one. THIS is the
       case the whole file exists for.
     *
     * AND SINCE V40 IT ALSO RUNS LIVE, which is why the copy is now yielded.
     * Until the Burn stopped resetting, every caller of this function was in
     * the boot path with no raster to starve. A live commit ends here, and
     * 4096 hc_cal_set_u8() calls is about 120000 instructions - measured by
     * me711_ts_gap_proof as a 12.09 ms hole in a 10 ms supervision raster,
     * the single worst gap in the whole V40 transaction set. Chunked and
     * tick-gated like crc_block() above; at boot yield_armed is 0. */
    p = CELL_PTR(active_index()) + REC_PAYLOAD;
    for (i = 0; i < (unsigned int)HC_CFG_SIZE; i++) {
        if ((i & 255u) == 0u) {
            hcts_target_yield();
        }
        hc_cal_set_u8(i, p[i]);
    }
    (void)hc_cfg_migrate_v101();
    hc_cfg_commit();                /* make the standby page agree */
    hc_cfg_source = 3u;             /* restored from NON-VOLATILE storage */
    /* HCNV_SRC_FLASH_A means "a committed record out of the device" and it no
       longer distinguishes a sector - hc_nvm_slot() does that. The VALUE is
       deliberately unchanged: the P3 bench card reads nvmSource's low byte and
       expects 2 after a Burn, and there is no reason to invalidate a
       procedure that is already physically proven. */
    NVW[W_SOURCE] = (unsigned char)HCNV_SRC_FLASH_A;
}


/* ============================ THE LAST-KNOWN-GOOD WALK-BACK ==============
 *
 * WHAT WAS ALREADY HERE, AND WHAT WAS NOT. nvm_scan()'s PASS 2 already falls
 * to the next-newest record when the newest one fails its CRC - it has done
 * so since the store became append-only. That covers a record that is
 * DAMAGED. It does nothing at all for a record that is INTACT AND WRONG: a
 * byte-perfect page with a crank pin on a cavity that has no capture unit
 * passes every checksum in this file and describes an ECU that cannot run.
 *
 * V64 made that page visible - hc_cfg_mgr_init() validates the restored page
 * and seeds the board default over it when it does not hold up - but the
 * floor it fell to was the COMPILED DEFAULT, skipping every older generation
 * the store was keeping for exactly this. A tuner who burns one bad page lost
 * their whole calibration and got a board default back.
 *
 * So: validate, and on a SEMANTIC failure load the next-older record and
 * validate that, bounded. The board default stays underneath as the floor and
 * hc_cfg_mgr_init() still applies it unchanged - this runs BEFORE it and
 * simply improves what it finds, which is why no shared code moved.
 *
 * THE BOUND IS FOUR, and it is a boot-time cost argument rather than a
 * correctness one: each step is a 4096-byte payload copy plus a full
 * hc_validate() pass, about 5 ms, and a store where the last four burns are
 * all semantically broken is a store whose owner needs the board default and
 * a TunerStudio session, not a longer search.
 *
 * AND THE STANDBY PAGE IS THE FIRST THING TRIED, NOT AN EXCEPTION TO IT.
 * nvm_select() leaves the battery-backed page in place when it survived its
 * own header check, and never reads flash at all in that case. If THAT page
 * is the semantically broken one, the first walk-back step has to load the
 * NEWEST flash record rather than an older one - lkg_from_flash tracks
 * whether anything has been taken out of the device yet. */
#define HCNV_LKG_TRIES  4u

/* Diagnostics, published through hc_nvm_lkg_steps(). Nothing here starts at a
   known value - start_me711.a66 runs no ?C_INIT - so both are written before
   they are read, in hc_nvm_lkg_walkback(). */
static unsigned char lkg_steps;
static unsigned char lkg_from_flash;

/* Select the newest committed, CRC-valid cell whose generation is STRICTLY
   OLDER than `ceiling`, or the newest of all when `bounded` is 0, and publish
   it as the active cell. Returns 0 when there is no such cell.

   This is PASS 2 of nvm_scan() over one iteration. It is deliberately a
   separate function rather than a flag threaded through that one: nvm_scan()
   also rebuilds the free-cell inventory and the reject mask, and re-running
   all of that to move one generation back would rewrite state the caller is
   in the middle of using. */
static unsigned char lkg_select_older(unsigned char bounded,
                                      unsigned long ceiling)
{
    unsigned int i;
    unsigned int best = (unsigned int)CELL_NONE;
    unsigned long best_gen = 0uL;
    unsigned long gen;
    unsigned char have = 0u;

    for (i = 0u; i < TGT_FLASH_CELLS; i++) {
        hcts_target_yield();
        if (cell_candidate(i)) {
            continue;                       /* blank */
        }
        if (!cell_header_gen(i, &gen)) {
            continue;                       /* not a committed header */
        }
        if (bounded && (long)(gen - ceiling) >= 0L) {
            continue;                       /* this one or newer, already had */
        }
        if (!have || (long)(gen - best_gen) >= 0L) {
            best_gen = gen;
            best = i;
            have = 1u;
        }
    }
    if (!have) {
        return 0u;
    }
    hcts_target_yield();
    if (cell_scan(best) != HCNV_ERR_NONE) {
        /* Damaged as well as old. Report it and let the caller ask again -
           the next call will step past this generation too. */
        set_be32(NVW, W_BEST_GEN, best_gen);
        return 2u;                          /* "try again from here" */
    }
    NVW[W_CELL] = (unsigned char)best;
    set_be32(NVW, W_BEST_GEN, cell_last_gen_get());
    set_be16(NVW, W_GENERATION,
             (unsigned int)(cell_last_gen_get() & 0xFFFFuL));
    NVW[W_SLOT] = (unsigned char)((best / TGT_FLASH_CELL_PAGES) + 1u);
    return 1u;
}

/* Copy the active cell's payload over the working calibration page. The same
   loop nvm_select() uses, with the same 256-byte yield stride, because the
   page it writes is the one the S5500 raster's own service reads around. */
static void lkg_load_active(void)
{
    unsigned char huge *p;
    unsigned int i;

    p = CELL_PTR(active_index()) + REC_PAYLOAD;
    for (i = 0; i < (unsigned int)HC_CFG_SIZE; i++) {
        if ((i & 255u) == 0u) {
            hcts_target_yield();
        }
        hc_cal_set_u8(i, p[i]);
    }
    (void)hc_cfg_migrate_v101();
    hc_cfg_commit();                /* make the standby page agree */
    hc_cfg_source = 3u;             /* restored from NON-VOLATILE storage */
    NVW[W_SOURCE] = (unsigned char)HCNV_SRC_FLASH_A;
    lkg_from_flash = 1u;
}

unsigned int hc_nvm_lkg_steps(void)
{
    return (unsigned int)lkg_steps;
}

void hc_nvm_lkg_walkback(void)
{
    unsigned int tries;
    unsigned char got;
    unsigned long ceiling;

    lkg_steps = 0u;
    (void)hc_cfg_migrate_v101();
    lkg_from_flash = (unsigned char)((hc_cfg_source == 3u) ? 1u : 0u);

    if (hc_ram_bad) {
        /* No SRAM: there is no calibration page to validate and nowhere to
           put a replacement. hc_cfg_mgr_init()'s own floor still applies. */
        return;
    }

    for (tries = 0u; tries < HCNV_LKG_TRIES; tries++) {
        if (hc_validate(HC_VAL_SRC_ACTIVE) == HC_VAL_OK) {
            return;                 /* this generation runs */
        }
        /* It does not. Step back one generation - or, if nothing has come out
           of the device yet because the standby page was accepted, take the
           newest record there is. */
        if (!lkg_from_flash) {
            got = lkg_select_older(0u, 0uL);
        } else {
            ceiling = be32(NVW, W_BEST_GEN);
            got = lkg_select_older(1u, ceiling);
        }
        if (got == 0u) {
            break;                  /* nothing older survives - the floor */
        }
        if (got == 1u) {
            lkg_load_active();
            lkg_steps++;
        }
        /* got == 2: header was fine, body was not. W_BEST_GEN now names it,
           so the next pass steps past it without loading anything. */
    }
    /* Falling out of here leaves ACTIVE holding the last thing tried.
       hc_cfg_mgr_init() validates once more and seeds the board default over
       it if it still does not hold up, which is the floor V61 made runnable. */
}

/* ==================================================== the public entries === */
void hc_nvm_boot(void)
{
    /* Explicitly, because nothing here starts at a known value:
       start_me711.a66 hands straight to main() and never runs Keil's
       ?C_INIT, and this flag is battery-backed besides. */
    hc_cfg_set_nonvol(0u);

    if (hc_ram_bad) {
        /* NO SRAM means no control block, no working block and no staging
           buffer - so there is nothing this module can do and nothing it can
           honestly say. The flash may well still hold a record, but its
           payload could only be copied into a calibration page that lives in
           the same dead SRAM, so loading it would achieve nothing. Every
           accessor below answers for this case on its own: hc_nvm_error()
           reads HCNV_ERR_RAM and the rest read their idle value. */
        return;
    }

    /* Ownership is a transient runtime lock, never durable state.  If an
       external reset interrupts a word window, the retained VSTBY byte may
       still say NVM.  V47 left that value set and permanently denied every
       post-reset ASIC launch.  Preserve the forensic fields, but recover the
       lock before the ASIC startup state machine can run. */
    live_init();
    SRAMB(NVM_LIVE)[L_OWNER] = (unsigned char)HCNV_OWNER_NONE;

    cb_load();
    nvm_scan();

    /* V47 never resumes a write during boot.  A previous fully committed
       record is rediscovered by nvm_scan(); any incomplete retained intent is
       terminally failed and its partial cell remains consumed. */
    if (cb_state == (unsigned char)HCNV_ST_ARMED
        || cb_state == (unsigned char)HCNV_ST_COMMITTING) {
        hc_lf_recover((unsigned int)cb_state,
                      (unsigned int)SRAMB(NVM_CB)[CB_RESULT],
                      be16(CB, CB_POS), HC_LF_WORD(LF_RESET_RAW));
        cb_state = (unsigned char)HCNV_ST_FAILED;
        cb_phase = (unsigned char)HCNV_PH_NONE;
        cb_err = (unsigned char)HCNV_ERR_PROGRAM;
        cb_seal();
    }
    nvm_select();
}

/* THE COMMAND HANDLER, and it does almost nothing on purpose.
 *
 * It records that a Burn was asked for and returns. Everything expensive -
 * validation, the standby commit, the 4096-byte copy and the CRCs - happens in
 * hc_nvm_service(), one bounded step per main-loop pass. See the note above
 * stage_begin_header(): doing it here cost 257 ms of a 10 ms raster and the
 * monitoring module reset the ECU in the middle of the reply. */
unsigned int hc_nvm_request(void)
{
    if (hc_ram_bad) {
        return HCNV_ERR_RAM;
    }

    /* The buffer stops being a record the instant a new Burn is asked for, so
       a reset during staging cannot commit a half-built one. */
    stage_clear();
    trace_begin();                  /* only a genuine new Burn clears evidence */

    cb_state = (unsigned char)HCNV_ST_STAGING;
    cb_phase = (unsigned char)HCNV_PH_NONE;
    cb_err = (unsigned char)HCNV_ERR_NONE;
    set_be16(CB, (unsigned int)CB_ATTEMPTS, 0u);
    NVW[W_STG_STEP] = (unsigned char)HCNV_STG_COMMIT;
    set_be16(NVW, W_STG_POS, 0u);
    set_be16(NVW, W_STG_CRC, 0xFFFFu);
    set_be16(NVW, W_STG_GEN, (unsigned int)(cfg_writes + cfg_burns));
    set_be16(NVW, W_ARM_MS, hc_tick_ms);
    cb_seal();
    live_init();
    hc_lf_arm(hc_tick_ms,
              be16(SRAMB(NVM_LIVE), L_WINDOWS_OK),
              be16(SRAMB(NVM_LIVE), L_WRITER_ENT),
              be16(SRAMB(NVM_LIVE), L_WRITER_OK),
              be16(SRAMB(NVM_LIVE), L_WRITER_FAIL));
    hc_bf_request_accepted();
    forensic_snapshot((unsigned char)0xFFu);
    return HCNV_ERR_NONE;
}

/* Does the flash ALREADY hold this exact calibration?
 *
 * TunerStudio sends a Burn whenever the user asks for one, and the bench log
 * of 2026-09-04 shows it doing so with `dirtyData.size(): 0` - nothing had
 * changed. Erasing a sector and resetting the ECU to store bytes that are
 * already there is pure wear and a pointless interruption, so it does not
 * happen: the staged payload's CRC is compared with the committed record's,
 * and an identical one completes the Burn without touching the device. */
static unsigned char stage_matches_flash(void)
{
    unsigned char huge *rec;
    unsigned int which;

    if (NVW[W_SLOT] == (unsigned char)HCNV_SLOT_NONE) {
        return 0u;                       /* nothing in flash to match */
    }
    which = active_index();
    rec = CELL_PTR(which);
    if (be32(rec, REC_LAYOUT) != (unsigned long)HC_CFG_LAYOUT_ID
        || be16(rec, REC_VERSION) != (unsigned int)HC_CFG_VERSION
        || be16(rec, REC_LENGTH) != (unsigned int)HC_CFG_SIZE) {
        return 0u;
    }
    return (unsigned char)(be16(rec, REC_PCRC)
                           == be16(SRAMB(NVM_STAGE), REC_PCRC));
}

/* ONE BOUNDED STEP of the staging machine. */
static void stage_step(void)
{
    unsigned long gen;
    unsigned int faults;

    /* A page write that lands mid-staging means the snapshot would be torn -
       half the old calibration and half the new. Start again rather than
       store something that was never a calibration. A tuner cannot type fast
       enough to livelock this: the whole payload is sixteen passes. */
    if (be16(NVW, W_STG_GEN) != (unsigned int)(cfg_writes + cfg_burns)) {
        NVW[W_STG_STEP] = (unsigned char)HCNV_STG_COMMIT;
        set_be16(NVW, W_STG_POS, 0u);
        set_be16(NVW, W_STG_CRC, 0xFFFFu);
        set_be16(NVW, W_STG_GEN, (unsigned int)(cfg_writes + cfg_burns));
        return;
    }

    switch (NVW[W_STG_STEP]) {
    case (unsigned char)HCNV_STG_COMMIT:
        /* The same call the burn has always made: validate DESIRED and refuse
           to store a configuration that does not describe a runnable engine.
           A page that cannot run must not reach flash either. */
        /* stopped = the restart point (hc_cfg_mgr_commit_burn()). */
        faults = hc_cfg_mgr_commit_burn((unsigned char)(trg_rpm == 0u
                                        && trg_state == TRG_NO_SIGNAL));
        if (faults != HC_VAL_OK) {
            nvm_fail(HCNV_ERR_VALIDATE);
            return;
        }
        gen = 0uL;
        if (NVW[W_SLOT] != (unsigned char)HCNV_SLOT_NONE) {
            gen = be32(NVW, W_BEST_GEN);
        }
        gen++;
        set_be32(CB, (unsigned int)CB_GEN, gen);
        stage_begin_header(gen);
        set_be16(NVW, W_STG_POS, 0u);
        set_be16(NVW, W_STG_CRC, 0xFFFFu);
        NVW[W_STG_STEP] = (unsigned char)HCNV_STG_COPY;
        cb_seal();
        hc_bf_stage(HCBF_ST_SNAPSHOT);
        forensic_snapshot((unsigned char)0xFFu);
        return;

    case (unsigned char)HCNV_STG_COPY:
        if (stage_copy_chunk()) {
            NVW[W_STG_STEP] = (unsigned char)HCNV_STG_FINISH;
        }
        return;

    default:
        stage_finish();
        hc_lf_stage_done(hc_tick_ms);
        NVW[W_STG_STEP] = (unsigned char)HCNV_STG_IDLE;
        /* stage_header_ok(), not stage_valid(): the payload CRC in the record
           IS the rolling one this machine just computed byte by byte, so
           walking all 4096 again would cost 50 ms to confirm arithmetic that
           has not left the building. */
        if (!stage_header_ok()) {
            nvm_fail(HCNV_ERR_STAGE);
            return;
        }
        if (stage_matches_flash()) {
            /* Nothing to do, and saying so is better than doing it. */
            cb_state = (unsigned char)HCNV_ST_DONE;
            cb_err = (unsigned char)HCNV_ERR_NONE;
            stage_clear();
            cb_seal();
            trace_stage(CST_DONE_VERIFY);
            hc_bf_stage(HCBF_ST_OK_PENDING);
            forensic_snapshot((unsigned char)SRAMB(NVM_CB)[CB_RESULT]);
            hc_lf_durable(hc_tick_ms, be16(CB, CB_POS));
            hcts_finish_deferred_response(TS_OK);
            return;
        }
        cb_state = (unsigned char)HCNV_ST_PENDING;
        /* THE TARGET CELL IS CHOSEN HERE WHEN ONE IS FREE, AND DEFERRED WHEN
           NONE IS. Up to V52 a full store failed the Burn right here; now a
           full store is a reason to RECLAIM, and a reclaim is far too much
           work for a command handler - er_victim() reads and CRC-checks every
           consumed cell in the store. So the request is simply left PENDING
           with no cell, and hc_nvm_service() picks one up once space exists.

           NO LONG WORK IN A COMMAND HANDLER. EVER. That is the V35 rule, and
           this is exactly the shape of edit that broke it the first time. */
        cb_cell = (NVW[W_NEXT] == CELL_NONE) ? CELL_NONE : NVW[W_NEXT];
        cb_seal();
        hc_bf_stage(HCBF_ST_TARGET);
        return;
    }
}

void hc_nvm_mark_dirty(void)
{
    if (cb_state == (unsigned char)HCNV_ST_IDLE
        || cb_state == (unsigned char)HCNV_ST_DONE) {
        cb_state = (unsigned char)HCNV_ST_DIRTY;
        /* Deliberately NOT written through to the SRAM control block. This is
           called from the TunerStudio write path, once per byte; a CRC and a
           store on every keystroke would be pure cost, and "the page has been
           edited" is not a fact that has to survive a reset. */
    }
}

/* ======================================================= THE RECLAIM ========
 *
 * WHAT THIS EXISTS TO DELETE: HCNV_ERR_FULL. Sixteen never-erased cells meant
 * sixteen Burns and then a 1 MiB reflash, and first engine setup is exactly
 * when a tuner burns hard.
 *
 * THE INVARIANT, AND NOTHING HERE MAY BREAK IT:
 *
 *     the sector being erased never holds the newest valid record.
 *
 * So at every instant of a reclaim - including a power cut in the middle of
 * one - a complete, CRC-checked, DONE-marked record sits in a sector nothing
 * is touching. That is the property the old A/B alternation relied on; it is
 * now enforced over ten sectors instead of two.
 *
 * AND THE FAILURE THAT USED TO BE UNSURVIVABLE IS NOW ORDINARY. An interrupted
 * erase leaves its sector indeterminate. Before V53 that meant the bootrom's
 * page record stopped matching and the ECU would not start at all; the store
 * is outside that record now, so the next scan simply sees a sector that is
 * neither blank nor valid and erases it again. The recovery is derived from
 * the DEVICE, never remembered in RAM.
 */
#define ERB   SRAMB(NVM_ER)

static void er_init(void)
{
    unsigned char huge *er = ERB;
    unsigned int i;

    if (be32(er, ER_MAGIC) == ER_MAGIC_VALUE) {
        return;
    }
    for (i = 0u; i < (unsigned int)ER_LEN; i++) {
        er[i] = 0u;
    }
    set_be32(er, ER_MAGIC, ER_MAGIC_VALUE);
    er[ER_SECTOR] = CELL_NONE;
    er[ER_STATE] = (unsigned char)HCNV_ER_IDLE;
}

/* Does this sector hold the newest valid record? */
static unsigned char er_sector_is_active(unsigned int sector)
{
    return (unsigned char)(NVW[W_CELL] != CELL_NONE
                           && (unsigned int)(NVW[W_CELL]
                                             / TGT_FLASH_CELL_PAGES) == sector);
}

/* Is every cell in this sector already erased, as far as the cheap test can
   tell? A wholly blank sector is nothing to reclaim. */
static unsigned char er_sector_blank(unsigned int sector)
{
    unsigned int i;
    unsigned int lo = (unsigned int)(sector * TGT_FLASH_CELL_PAGES);

    for (i = lo; i < lo + (unsigned int)TGT_FLASH_CELL_PAGES; i++) {
        if (!cell_candidate(i)) {
            return 0u;
        }
    }
    return 1u;
}

/* WHICH SECTOR TO RECLAIM, and the rule is deliberately conservative.
 *
 * Take the one holding the OLDEST records - the lowest maximum generation -
 * among sectors that are neither blank nor holding the newest record. Oldest
 * first keeps the store rotating evenly with no wear-levelling machinery,
 * which the endurance figure says is unnecessary: eighty cells at a guaranteed
 * MINIMUM 100,000 erase cycles per sector is eight million Burns.
 *
 * A sector with NO valid record in it at all - half-erased, or full of
 * rejects - sorts oldest and is reclaimed first. That is what makes an
 * interrupted reclaim self-healing.
 *
 * Returns TGT_FLASH_SECTORS when there is nothing safe to erase. */
static unsigned int er_victim(void)
{
    unsigned int sec;
    unsigned int cell;
    unsigned int best = (unsigned int)TGT_FLASH_SECTORS;
    unsigned long best_gen = 0uL;
    unsigned long gen;
    unsigned char have;
    unsigned char best_have = 0u;

    /* NEVER erase while there is no committed record to fall back on. A virgin
       store has nothing to reclaim anyway, and this makes "a valid calibration
       is always recoverable" true by construction rather than by argument. */
    if (NVW[W_CELL] == CELL_NONE) {
        return (unsigned int)TGT_FLASH_SECTORS;
    }

    for (sec = 0u; sec < (unsigned int)TGT_FLASH_SECTORS; sec++) {
        if (er_sector_is_active(sec) || er_sector_blank(sec)) {
            continue;
        }
        have = 0u;
        gen = 0uL;
        for (cell = sec * TGT_FLASH_CELL_PAGES;
             cell < (sec + 1u) * TGT_FLASH_CELL_PAGES; cell++) {
            unsigned char huge *q = CELL_PTR(cell);
            unsigned long g;
            /* THE HEADER ONLY - NOT cell_scan(). Choosing a victim needs to
               know how OLD a sector is, and the generation is in the header.
               cell_scan() would CRC 4120 bytes of every consumed cell in the
               store to answer that, which is both a lot of code and, at
               seventy-two cells, a lot of main-loop time for a decision that
               a sixteen-byte read settles.

               It does not have to be trustworthy, either: choosing the wrong
               victim cannot lose data, because er_sector_is_active() below is
               what protects the newest record and that comes from nvm_scan(),
               which DOES verify. The worst a mis-read does here is reclaim a
               sector in a slightly different order. */
            if (be32(q, REC_MAGIC) != NVM_REC_MAGIC
                || be32(q, REC_COMMIT) != NVM_REC_COMMIT) {
                continue;
            }
            g = be32(q, REC_GEN);
            if (!have || (long)(g - gen) > 0L) {
                gen = g;
            }
            have = 1u;
        }
        if (best >= (unsigned int)TGT_FLASH_SECTORS
            || (best_have && !have)
            || (best_have == have && (long)(gen - best_gen) < 0L)) {
            best = sec;
            best_gen = gen;
            best_have = have;
        }
    }
    return best;
}

/* Start a reclaim on `sector`. */
static void er_begin(unsigned int sector, unsigned int now_ms)
{
    unsigned char huge *er = ERB;

    er[ER_SECTOR] = (unsigned char)sector;
    er[ER_OP] = (unsigned char)HCNV_EOP_START;
    er[ER_STATE] = (unsigned char)HCNV_ER_RUNNING;
    er[ER_RESULT] = (unsigned char)HCNV_ERR_NONE;
    set_be16(er, ER_SLICES, 0u);
    set_be16(er, ER_STARTMS, now_ms);
    set_be16(er, ER_TRIES, (unsigned int)(be16(er, ER_TRIES) + 1u));
    /* Converted to T7 ticks HERE, in ordinary C: the relocated routine may not
       call the 32-bit multiply and divide US_TO_TICKS() compiles to. */
    set_be16(er, ER_SLICETK, (unsigned int)US_TO_TICKS(HCNV_ERASE_SLICE_US));
    fl_prepare_sel((unsigned char)HCNV_PAY_ERASER);
}

/* One slice. Returns 1 while the reclaim is still running. */
static unsigned char er_step(unsigned int now_ms, unsigned int rpm,
                             unsigned char trig_turning,
                             unsigned char outputs_busy,
                             unsigned char page_stable)
{
    unsigned char huge *er = ERB;
    unsigned int sector = (unsigned int)er[ER_SECTOR];
    unsigned int i;

    if (er[ER_STATE] != (unsigned char)HCNV_ER_RUNNING) {
        return 0u;
    }
    if (sector >= (unsigned int)TGT_FLASH_SECTORS) {
        er[ER_STATE] = (unsigned char)HCNV_ER_IDLE;
        return 0u;
    }

    /* THE SAME ADMISSION THE WRITER USES, for the same reason: the window must
       not land where the SSC frame needs the CPU. If it is refused this pass
       the erase simply stays suspended, which is a state the device will sit
       in indefinitely at no cost. */
    if (!live_admit(now_ms, rpm, trig_turning, outputs_busy, page_stable)) {
        return 1u;
    }

    if (er[ER_LOADED] != (unsigned char)HCNV_PAY_ERASER) {
        fl_prepare_sel((unsigned char)HCNV_PAY_ERASER);
    }
    fl_enter();
    set_be16(er, ER_SLICES, (unsigned int)(be16(er, ER_SLICES) + 1u));

    if (er[ER_STATE] == (unsigned char)HCNV_ER_DONE) {
        /* THE DEVICE SAYING IT FINISHED IS NOT THE SECTOR BEING BLANK, and
           only one of those is worth believing. Read it. */
        for (i = sector * TGT_FLASH_CELL_PAGES;
             i < (sector + 1u) * TGT_FLASH_CELL_PAGES; i++) {
            hcts_target_yield();
            if (!cell_blank(i)) {
                er[ER_STATE] = (unsigned char)HCNV_ER_FAILED;
                er[ER_RESULT] = (unsigned char)HCNV_ERR_ERASE;
                break;
            }
        }
    }

    if (er[ER_STATE] == (unsigned char)HCNV_ER_DONE) {
        set_be16(er, ER_LASTMS, (unsigned int)(now_ms - be16(er, ER_STARTMS)));
        set_be16(er, ER_RECLAIMS, (unsigned int)(be16(er, ER_RECLAIMS) + 1u));
        set_be16(er, ER_TRIES, 0u);
        er[ER_SECTOR] = CELL_NONE;
        er[ER_STATE] = (unsigned char)HCNV_ER_IDLE;
        nvm_scan();                  /* the reclaimed cells are free now */
        fl_prepare_sel((unsigned char)HCNV_PAY_WRITER);
        return 0u;
    }

    if (er[ER_STATE] == (unsigned char)HCNV_ER_FAILED
        || be16(er, ER_SLICES) > (unsigned int)HCNV_ERASE_MAX_SLICES) {
        /* BOUNDED, AND THE BOUND IS THE HONEST PART. The datasheet gives no
           minimum resume-to-suspend interval, so nothing here can PROMISE that
           a sliced erase converges. If it does not, this stops: the store goes
           on using the cells it still has, the counters say exactly what
           happened, and no calibration was ever at risk. */
        set_be16(er, ER_FAILS, (unsigned int)(be16(er, ER_FAILS) + 1u));
        er[ER_STATE] = (unsigned char)HCNV_ER_IDLE;
        er[ER_SECTOR] = CELL_NONE;
        fl_prepare_sel((unsigned char)HCNV_PAY_WRITER);
        return 0u;
    }
    return 1u;
}

/* Should a reclaim start? Only with the engine stopped, no Burn in flight, and
   the store genuinely running low. */
static unsigned char er_wanted(unsigned int rpm, unsigned char trig_turning,
                               unsigned char outputs_busy)
{
    if (rpm != 0u || trig_turning != 0u || outputs_busy != 0u) {
        return 0u;
    }
    if (NVW[W_FREE] > (unsigned char)HCNV_RECLAIM_LOW) {
        return 0u;
    }
    if (be16(ERB, ER_TRIES) >= (unsigned int)HCNV_ERASE_MAX_TRIES) {
        return 0u;
    }
    return 1u;
}

void hc_nvm_service(unsigned int now_ms, unsigned int rpm,
                    unsigned char trig_turning, unsigned char outputs_busy,
                    unsigned char page_stable)
{
    unsigned int t0;

    if (hc_ram_bad) {
        return;                 /* nothing to read the request out of */
    }

    /* THE RECLAIM RUNS BEFORE ANYTHING ELSE IS CONSIDERED, and it runs to
       completion. A reclaim and a record write both want the one relocation
       slot, so they are serialised - and because reclaim starts a whole sector
       before the store could run out, a Burn effectively never waits for one.

       IT IS NOT ON THE BURN'S CRITICAL PATH BY CONSTRUCTION: er_wanted() fires
       at HCNV_RECLAIM_LOW free cells, which is eight, so there are eight more
       Burns' worth of space in hand while it works. */
    er_init();
    if (ERB[ER_STATE] == (unsigned char)HCNV_ER_RUNNING) {
        /* A BURN OUTRANKS A RECLAIM, ALWAYS.
         *
         * The reclaim is bounded only by the device, and a sector erase is
         * seconds. TGT_LIVE_BURN_DEADLINE_MS is 3900, so a Burn that arrived
         * while a reclaim was running and had to wait for it would fail with
         * HCNV_ERR_DEADLINE - the tuner would be told their calibration did
         * not save, because the ECU was tidying up. That is not acceptable and
         * it is not necessary.
         *
         * So the reclaim simply STOPS RESUMING. The device is already
         * suspended between slices; leaving it there costs nothing, and the
         * sector is left partially erased - which V53 made an ORDINARY state.
         * The next scan sees a sector that is neither blank nor valid, it
         * sorts oldest in er_victim(), and it is erased again from the start.
         * A wasted erase is the whole price, and only when the two collide.
         *
         * NOTE WHAT IS NOT DONE HERE: the datasheet does permit programming a
         * non-erasing sector while an erase is suspended, so the two COULD
         * overlap. They do not, because that would mean swapping the shared
         * relocation slot underneath a live commit, and the value of keeping
         * fl_enter() byte-identical is worth more than a rare wasted erase. */
        if (cb_state == (unsigned char)HCNV_ST_PENDING
            || cb_state == (unsigned char)HCNV_ST_ARMED
            || cb_state == (unsigned char)HCNV_ST_COMMITTING
            || cb_state == (unsigned char)HCNV_ST_STAGING) {
            ERB[ER_STATE] = (unsigned char)HCNV_ER_IDLE;
            ERB[ER_SECTOR] = CELL_NONE;
            fl_prepare_sel((unsigned char)HCNV_PAY_WRITER);
        } else if (er_step(now_ms, rpm, trig_turning, outputs_busy,
                           page_stable)) {
            return;
        }
    } else if (cb_state == (unsigned char)HCNV_ST_IDLE
               || cb_state == (unsigned char)HCNV_ST_DIRTY
               || cb_state == (unsigned char)HCNV_ST_DONE
               || cb_state == (unsigned char)HCNV_ST_FAILED) {
        if (er_wanted(rpm, trig_turning, outputs_busy)) {
            unsigned int victim = er_victim();
            if (victim < (unsigned int)TGT_FLASH_SECTORS) {
                er_begin(victim, now_ms);
                return;
            }
        }
    }

    if ((cb_state == (unsigned char)HCNV_ST_PENDING
         || cb_state == (unsigned char)HCNV_ST_ARMED
         || cb_state == (unsigned char)HCNV_ST_COMMITTING
         || cb_state == (unsigned char)HCNV_ST_STAGING)
        && (unsigned int)(now_ms - be16(NVW, W_ARM_MS))
           >= (unsigned int)TGT_LIVE_BURN_DEADLINE_MS) {
        live_init();
        SRAMB(NVM_LIVE)[L_ADMISSION] = (unsigned char)HCNV_ADMIT_DEADLINE;
        set_be16(SRAMB(NVM_LIVE), L_DEADLINE_MS, 0u);
        nvm_fail(HCNV_ERR_DEADLINE);
        return;
    }

    if (cb_state == (unsigned char)HCNV_ST_STAGING) {
        /* Bounded by the same service-slice budget that protects the
           programmer.  The 4096-byte snapshot is 64 small chunks; each is
           about 1.5 ms and the total slice is capped at HCNV_PASS_US, so a
           staging pass cannot consume a supervision raster. */
        t0 = (unsigned int)T7;
        while (cb_state == (unsigned char)HCNV_ST_STAGING) {
            stage_step();
            hcts_target_yield();
            if ((unsigned int)((unsigned int)T7 - t0)
                >= (unsigned int)US_TO_TICKS(HCNV_PASS_US)) {
                break;
            }
        }
        return;
    }

    if (cb_state == (unsigned char)HCNV_ST_ARMED
        || cb_state == (unsigned char)HCNV_ST_COMMITTING) {
        nvm_commit(now_ms, rpm, trig_turning, outputs_busy, page_stable);
        return;
    }

    if (cb_state != (unsigned char)HCNV_ST_PENDING) {
        return;
    }

    if (!stage_header_ok()) {
        nvm_fail(HCNV_ERR_STAGE);
        return;
    }

    /* PICK THE CELL NOW IF THE REQUEST COULD NOT. A reclaim may have run since
       the button was pressed, so ask the scan again rather than trusting what
       was true at request time. */
    if (cb_cell >= (unsigned char)TGT_FLASH_CELLS) {
        if (NVW[W_NEXT] == CELL_NONE) {
            /* Still nothing. er_wanted() above will have asked for a reclaim
               if one is possible; if it is not - every sector blank or holding
               the newest record, which ten sectors make unreachable - then the
               store really is full and the tuner must be told. */
            if (er_victim() >= (unsigned int)TGT_FLASH_SECTORS
                || be16(ERB, ER_TRIES) >= (unsigned int)HCNV_ERASE_MAX_TRIES) {
                nvm_fail(HCNV_ERR_FULL);
            }
            return;             /* stay PENDING while the reclaim runs */
        }
        cb_cell = NVW[W_NEXT];
    }
    cb_state = (unsigned char)HCNV_ST_ARMED;
    set_be16(CB, (unsigned int)CB_ATTEMPTS, 0u);
    cb_seal();
}

/* ================================================== what TunerStudio reads ==
 *
 * FUNCTIONS AND NOT GLOBALS, so that this module owns no near RAM at all - see
 * the note at the top of the file. Each one answers honestly when the external
 * SRAM is unusable: there is then no control block, no working block and no
 * staging buffer, so the only true thing to say is HCNV_ERR_RAM.
 */
unsigned int hc_nvm_state(void)
{
    return hc_ram_bad ? HCNV_ST_IDLE : (unsigned int)cb_state;
}

unsigned int hc_nvm_phase(void)
{
    return hc_ram_bad ? HCNV_PH_NONE : (unsigned int)cb_phase;
}

unsigned int hc_nvm_error(void)
{
    if (hc_ram_bad) {
        return HCNV_ERR_RAM;
    }
    /* The control block's own error outranks the scan's: a failed commit is a
       more specific thing to say than "there is nothing to load". */
    if (cb_err != (unsigned char)HCNV_ERR_NONE) {
        return (unsigned int)cb_err;
    }
    return (unsigned int)scan_why;
}

unsigned int hc_nvm_slot(void)
{
    return hc_ram_bad ? HCNV_SLOT_NONE : (unsigned int)NVW[W_SLOT];
}

unsigned int hc_nvm_source(void)
{
    return hc_ram_bad ? HCNV_SRC_DEFAULTS : (unsigned int)NVW[W_SOURCE];
}

unsigned int hc_nvm_generation(void)
{
    return hc_ram_bad ? 0u : be16(NVW, W_GENERATION);
}

unsigned int hc_nvm_attempts(void)
{
    return hc_ram_bad ? 0u : cb_attempts_get();
}

unsigned int hc_nvm_commits(void)
{
    return hc_ram_bad ? 0u : be16(NVW, W_COMMITS);
}

unsigned int hc_nvm_words_total(void) { return (unsigned int)REC_TOTAL_WORDS; }
unsigned int hc_nvm_words_completed(void)
{
    return hc_ram_bad ? 0u : be16(CB, CB_POS);
}
unsigned int hc_nvm_words_remaining(void)
{
    unsigned int done = hc_nvm_words_completed();
    return (done >= (unsigned int)REC_TOTAL_WORDS) ? 0u
                                                  : (unsigned int)(REC_TOTAL_WORDS - done);
}

static unsigned int live16(unsigned int off)
{
    unsigned char huge *lb = SRAMB(NVM_LIVE);
    return (unsigned int)((!hc_ram_bad && be32(lb, L_MAGIC) == L_MAGIC_VALUE)
                          ? be16(lb, off) : 0u);
}

static unsigned int live8(unsigned int off)
{
    unsigned char huge *lb = SRAMB(NVM_LIVE);
    return (unsigned int)((!hc_ram_bad && be32(lb, L_MAGIC) == L_MAGIC_VALUE)
                          ? lb[off] : 0u);
}

unsigned int hc_nvm_live_owner(void) { return live8(L_OWNER); }
unsigned int hc_nvm_live_admission(void) { return live8(L_ADMISSION); }
unsigned int hc_nvm_live_pause_reason(void) { return live8(L_PAUSE); }
unsigned int hc_nvm_live_windows_ok(void) { return live16(L_WINDOWS_OK); }
unsigned int hc_nvm_live_windows_rejected(void) { return live16(L_WINDOWS_NO); }
unsigned int hc_nvm_live_deadline_ms(void) { return live16(L_DEADLINE_MS); }
unsigned int hc_nvm_live_horizon_us(void) { return live16(L_HORIZON_US); }
unsigned int hc_nvm_live_predicted_ms(void) { return live16(L_PREDICT_MS); }
unsigned int hc_nvm_live_writer_entries(void) { return live16(L_WRITER_ENT); }
unsigned int hc_nvm_live_writer_success(void) { return live16(L_WRITER_OK); }
unsigned int hc_nvm_live_writer_failures(void) { return live16(L_WRITER_FAIL); }
unsigned int hc_nvm_live_mask(void) { return live16(L_MASK); }
unsigned int hc_nvm_live_pending_before(void) { return live16(L_PENDING_BEF); }
unsigned int hc_nvm_live_pending_after(void) { return live16(L_PENDING_AFT); }
unsigned int hc_nvm_live_vector_violations(void) { return live16(L_VECTOR_BAD); }
unsigned char hc_nvm_word_owned(void)
{
    return (unsigned char)(SRAMB(NVM_LIVE)[L_OWNER]
                           == (unsigned char)HCNV_OWNER_NVM);
}

unsigned char hc_nvm_nonvol(void)
{
    return (unsigned char)(hc_ram_bad ? 0u : NVW[W_NONVOL]);
}

/* ------------------------------------------------ the programmer's diary --
 * Honest when the SRAM is unusable, like every accessor above: there is then
 * no diary either, and 0 / 0xFFFF is what "nothing was measured" looks like.
 * The magic is checked so a cold or corrupted block reads as nothing measured
 * rather than as a measurement. */
static unsigned char dg_ok(void)
{
    return (unsigned char)(!hc_ram_bad
                           && be32(DGB, (unsigned int)DG_MAGIC)
                              == NVM_DG_MAGIC);
}

unsigned int hc_nvm_prog_retries(void)
{
    return dg_ok() ? dg16((unsigned int)DG_RETRIES) : 0u;
}

unsigned int hc_nvm_poll_min(void)
{
    return dg_ok() ? dg16((unsigned int)DG_POLLMIN) : 0xFFFFu;
}

unsigned int hc_nvm_poll_max(void)
{
    return dg_ok() ? dg16((unsigned int)DG_POLLMAX) : 0u;
}

unsigned int hc_nvm_fail_word(void)
{
    return dg_ok() ? dg16((unsigned int)DG_WORD) : 0xFFFFu;
}

unsigned int hc_nvm_fail_exp(void)
{
    return dg_ok() ? dg16((unsigned int)DG_EXP) : 0u;
}

unsigned int hc_nvm_fail_got(void)
{
    return dg_ok() ? dg16((unsigned int)DG_GOT1) : 0u;
}

unsigned int hc_nvm_fail_got2(void)
{
    return dg_ok() ? dg16((unsigned int)DG_GOT2) : 0u;
}

unsigned int hc_nvm_prog_flags(void)
{
    return dg_ok() ? dg16((unsigned int)DG_FLAGS) : 0u;
}

unsigned int hc_nvm_commit_stage(void)
{
    return hc_bf_stage_current();
}

unsigned int hc_nvm_commit_last_stage(void)
{
    return hc_bf_stage_last();
}

unsigned int hc_nvm_commit_fail_stage(void)
{
    return hc_bf_stage_fail();
}

/* ============================================ WHAT THE RECLAIM PUBLISHES ====
 *
 * The reclaim is the one thing in this module that has never run on silicon,
 * and the one thing whose convergence the datasheet does not promise. So it
 * reports enough for a bench to tell the three outcomes apart WITHOUT a
 * forensic dump: it worked, it is still working, or it gave up and said why.
 *
 * hc_nvm_erase_slices() is the number that matters most. If a sliced erase
 * does not converge on this part, the symptom is that it climbs and
 * hc_nvm_reclaims() never does.
 */
unsigned int hc_nvm_free_cells(void)
{
    return hc_ram_bad ? 0u : (unsigned int)NVW[W_FREE];
}

unsigned int hc_nvm_cells_total(void) { return (unsigned int)TGT_FLASH_CELLS; }

/* Low byte HCNV_ER_*, high byte the store sector being erased (0xFF none). */
unsigned int hc_nvm_erase_state(void)
{
    if (hc_ram_bad) {
        return 0u;
    }
    return (unsigned int)(((unsigned int)ERB[ER_SECTOR] << 8)
                          | ERB[ER_STATE]);
}

unsigned int hc_nvm_erase_slices(void)
{
    return hc_ram_bad ? 0u : be16(ERB, ER_SLICES);
}

unsigned int hc_nvm_erase_ms(void)
{
    return hc_ram_bad ? 0u : be16(ERB, ER_LASTMS);
}

unsigned int hc_nvm_reclaims(void)
{
    return hc_ram_bad ? 0u : be16(ERB, ER_RECLAIMS);
}

unsigned int hc_nvm_erase_fails(void)
{
    return hc_ram_bad ? 0u : be16(ERB, ER_FAILS);
}

/* Low byte the attempts spent on the CURRENT sector, high byte the reject
   mask's population - "how many sectors hold something the scan refused". */
unsigned int hc_nvm_erase_tries(void)
{
    unsigned int m;
    unsigned int n = 0u;

    if (hc_ram_bad) {
        return 0u;
    }
    m = be16(NVW, W_REJECT);
    while (m != 0u) {
        n = (unsigned int)(n + (m & 1u));
        m = (unsigned int)(m >> 1);
    }
    return (unsigned int)((n << 8) | (be16(ERB, ER_TRIES) & 0x00FFu));
}

/* The last status word the erase poll read out of the device. 0xFFFF after a
   completed erase - that is erased array data, not status. */
unsigned int hc_nvm_erase_status(void)
{
    return hc_ram_bad ? 0u : be16(ERB, ER_LASTDQ);
}
