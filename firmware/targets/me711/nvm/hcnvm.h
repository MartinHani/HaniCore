/*
 * hcnvm.h - the calibration survives the battery coming off the car.
 *
 * READ THIS BEFORE hcnvm.c. The safety argument is here, and it is the reason
 * the file is shaped the way it is. The evidence behind every claim is in
 * the maintainer's design records; the implemented behaviour,
 * with the bench procedure, is in
 * the maintainer's design records.
 *
 * IMPORTANT CORRECTION, 2026-09-06: sections 3, 6 and 7 below describe the
 * superseded erase-and-alternate design. They are retained only as historical
 * rationale. The physical dump proved SA7/SA8 ARE boot-checksummed. Current
 * behaviour is sixteen append-only 8 KiB cells, page+2..page+1FFC,
 * PROGRAM-ONLY, with HCNV_ERR_FULL at exhaustion. The authoritative failure
 * record and replacement contract are the maintainer's design records.
 *
 * SECOND CORRECTION, V40, 2026-09-06 - THE COMMIT NO LONGER RESETS.
 *
 * Section 3's "it ends in SRST" and section 2's three references were right
 * about an ERASE. They are not right about what is left once the erase is
 * gone. Erasing is what forced a reset: a 64 KiB sector takes ~0.7 s, during
 * which a single-bank NOR answers every read with status, so the CPU cannot
 * execute, cannot take a vector, and cannot be left mid-anything - the only
 * honest way back is through reset. APPEND-ONLY PROGRAMMING IS NOT THAT
 * OPERATION. One word takes microseconds, so the device can be made busy for a
 * bounded slice, returned to read-array mode, and handed back to a running
 * main loop.
 *
 * V39 kept the reset anyway and TunerStudio paid for it: the Burn reply went
 * out, ~250 ms later the ECU asserted SRST, and the session died - disconnect,
 * reconnect, signature re-handshake, "Unable to get all pages", a controller
 * settings reload. THE MEASURE OF THIS FEATURE IS NOT "SRST REMOVED", IT IS
 * "THE SESSION SURVIVES THE BURN".
 *
 * So in V40:
 *
 *   - hc_nvm_payload() is a `far` routine CALLed in the external SRAM. It
 *     programs HCNV_PROG_CHUNK words, verifies each, writes the AMD F0
 *     read-array command, and RETURNS. It never resets;
 *   - fl_enter() clears IEN around that call and restores exactly the state it
 *     found. The device is single-bank, so no vector may fetch while it is
 *     busy; the window is bounded by the chunk, not by an erase;
 *   - hc_nvm_service() performs ONE such chunk per main-loop pass, so the
 *     supervision raster, the watchdog and the K-line all keep running;
 *   - the TunerStudio reply is DEFERRED (hcts_defer_response()) and released
 *     only when the DONE marker has been read back out of the device, the
 *     store rescanned and the live source reselected. TS_OK therefore means
 *     "it is in flash and this ECU is ready for your next request", which is
 *     what the tuner thought it meant all along;
 *   - hc_nvm_boot() is now RECOVERY ONLY - see the comment on it below.
 *
 * WHAT DID NOT CHANGE, and must not: the append-only geometry, the record
 * layout, the DONE marker programmed last, the rule that the old record stays
 * authoritative until DONE, and the untouched first/last page words the boot
 * checksum samples. V39's append-only behaviour is PHYSICALLY PROVEN on this
 * ECU (two burns, cells 0 and 1, generations 1 and 2, BOOTSUM 0x00E303CF
 * matching). V40 changes WHEN the programming happens, not WHAT is written.
 *
 * ===========================================================================
 * 1. WHAT WAS WRONG
 * ===========================================================================
 *
 * A TunerStudio burn wrote the page into the TC55257 external SRAM, and that
 * SRAM's VDD comes from VSTBY. So the calibration survived a reset, a
 * watchdog, and the key going off - and it did NOT survive the battery being
 * disconnected, going flat, or the ECU coming off the car. hcconfig.h has said
 * so in prose for months and hc_cfg_persist_class() has answered
 * HC_PERSIST_STANDBY honestly the whole time. This file is what finally makes
 * HC_PERSIST_NONVOL true.
 *
 * ===========================================================================
 * 2. WHAT BOSCH DOES, BECAUSE IT WAS READ BEFORE ANY OF THIS WAS DESIGNED
 * ===========================================================================
 *
 * Bosch Motorsport MS 4 Sport is a C167-family Bosch motorsport ECU with the
 * same flash family, so it is the right reference. Decoded out of its own
 * machine code (40CSTX36.bin) and its A2L:
 *
 *   - a 32 KiB RAM working page at 0x384000 that the tool edits directly;
 *   - a 32 KiB flash reference page at 0x010000, copied into RAM at boot
 *     (`RAM_INIT_BY_ECU`);
 *   - `TOOLFLASHBACK`, never `AUTOFLASHBACK` - NOTHING becomes permanent
 *     unless the user explicitly asks;
 *   - on that request: interrupts off, a 202-byte programmer copied into
 *     external RAM at 0x38C000 and CALLed there, one AMD sector erase with
 *     DQ7 polling, 0x4000 words programmed with a read-back compare on every
 *     word, SRVWDT inside both busy loops;
 *   - and then `SRST`. A deliberate software reset. That is what this project
 *     has been calling COPY2FLASH_RESET, and it is now proven in the
 *     instructions rather than quoted from documentation.
 *
 * The other standalone ME7.4.4 (`FlashHandler.c`) does the same three things:
 * copy the programmer to RAM, disable interrupts, come back through a reset.
 *
 * Three independent implementations, three resets. They agree because the
 * hardware leaves no choice: the 29F800BB is a single-bank device with no
 * read-while-write, so while a sector is busy every read of that chip returns
 * status instead of memory - and our code, our const tables and our interrupt
 * vectors ARE that chip.
 *
 * ===========================================================================
 * 3. WHERE ME7.1.1 IS DIFFERENT, AND IT IS THE WHOLE DESIGN
 * ===========================================================================
 *
 * MS4 can assume it owns the CPU for the second the erase takes. THIS BOARD
 * CANNOT. The S5500 monitoring module is a second C167; it supervises this CPU
 * over the SSC frame and it can assert SWRST_SM. There is no equivalent of the
 * ME7.5 board's P3.5 "disable the security module" - the ME7.1.1 reset path
 * runs from the monitoring module through the LM2901 network into RSTIN_FR and
 * no main-CPU pin gates it.
 *
 * Earlier HaniCore images that went silent were reset in ~310-420 ms. A 64 KiB
 * sector erase is typically ~0.7 s.
 *
 *     SO THE MONITORING MODULE WILL PROBABLY RESET US PART-WAY THROUGH THE
 *     ERASE, AND THE DESIGN SURVIVES THAT RATHER THAN HOPING TO BEAT IT.
 *
 * Everything below follows from that one sentence:
 *
 *   THE COMMIT RUNS IN THE BOOT PATH, before hc_asic_start_init() brings the
 *   supervision link up and before IEN = 1. Interrupts are not "disabled" -
 *   they have not been enabled yet, which is a stronger guarantee than any
 *   BCLR IEN, and it means no vector fetch can land on a busy device.
 *
 *   THE COMMIT IS RESTARTABLE. Its phase and its attempt count live in the
 *   battery-backed SRAM, so a reset mid-erase costs one boot and not the
 *   calibration. A NOR erase completes inside the device with or without the
 *   CPU **as long as the supply is present** - that is the SWRST_SM case, and
 *   it is the only case in which anything is assumed to finish by itself.
 *   NOR programming only ever clears bits, so re-programming the same words is
 *   idempotent. The machine converges.
 *
 *   ON A POWER CUT NOTHING FINISHES. The sector is left partially erased and
 *   indeterminate, and THE DESIGN ASSUMES EXACTLY THAT: correctness rests only
 *   on the target slot being REJECTED unless it is provably complete, and on
 *   the other slot being untouched. See the record layout below.
 *
 *   THERE ARE TWO SLOTS. SA7 and SA8, alternating - the reservation
 *   the maintainer's design notes made before any of this existed. The slot
 *   being written is never the slot being used, so at every instant of the
 *   whole operation at least one sector holds a complete, committed,
 *   CRC-checked record. This is the one place where MS4 is deliberately NOT
 *   copied: MS4 has one slot, no generation and no commit marker, and an
 *   interrupted flash-back there is unrecoverable in the field.
 *
 *   AND IT ENDS IN SRST, like all three references.
 *
 * ===========================================================================
 * 4. WHAT A BURN MEANS, EXACTLY
 * ===========================================================================
 *
 * Pressing Burn means: "make THIS calibration - the one in front of me right
 * now - the one that comes back after the battery is disconnected."
 *
 * So Burn takes a SNAPSHOT into TGT_RAM_FLASHBUF. Nothing edited afterwards
 * can ride along.
 *
 * THE COMMAND HANDLER ITSELF DOES ALMOST NOTHING. It records the request and
 * returns in microseconds; the record is built by hc_nvm_service(), 256 bytes
 * per main-loop pass. The first version built it inside the handler and took
 * 257 ms against a 10 ms supervision raster - the monitoring module reset the
 * ECU in the middle of the Burn reply and TunerStudio saw a truncated CRC.
 * Nothing in this file may go back to doing long work in a command handler.
 *
 * If a page write lands while the record is being built, staging RESTARTS -
 * so what is stored is always a whole calibration and never half of two. The
 * snapshot is therefore "the page as it was when staging last began", which is
 * within a few milliseconds of the button and cannot be a torn page.
 *
 * AND A BURN THAT WOULD CHANGE NOTHING DOES NOTHING. TunerStudio sends a Burn
 * whenever the user asks for one - the bench log of 2026-09-04 shows one with
 * `dirtyData.size(): 0` - and erasing a sector to store bytes that are already
 * in it is wear and an interruption for no reason. The staged payload's CRC is
 * compared with the committed record's; identical means the Burn is already
 * done.
 *
 *     page = A ; Burn ; page = B ; (no Burn)     ->  A becomes permanent
 *     page = A ; Burn ; page = B ; Burn ; C      ->  B becomes permanent
 *
 * The staging buffer was already reserved and unused, so the snapshot costs
 * ZERO additional RAM.
 *
 * ===========================================================================
 * 5. PRESSING BURN MUST NOT KILL A RUNNING ENGINE
 * ===========================================================================
 *
 * It cannot, because the request and the commit are separate things.
 *
 *   RPM == 0, safe        the commit is armed and the ECU resets into it
 *   engine running        the request is STAGED AND KEPT. Nothing is erased,
 *                         nothing is programmed, no reset happens, and the
 *                         engine does not notice. State = PENDING.
 *   key off while pending the staged record is in battery-backed SRAM. The
 *                         commit happens at the NEXT KEY-ON BOOT.
 *
 * That last line is why this design needs no power-after-run authority. MS4
 * holds its own main relay closed to finish an EEPROM write; on this ECU the
 * NLEN_FR run-on polarity is still INFERRED and unmeasured, and nothing here
 * depends on it.
 *
 * AND THE CONVERSE, which matters just as much: KEY-OFF IS NOT PERMISSION TO
 * SAVE. A page edited and never burned is never committed. Only
 * hc_nvm_request() stages a record, and only a staged record is ever written.
 *
 * ===========================================================================
 * 6. THE RECORD, AND WHY A HALF-WRITTEN ONE CANNOT BE MISTAKEN FOR GOOD
 * ===========================================================================
 *
 *      0   4  MAGIC     'HCN1'
 *      4   4  layout    HC_CFG_LAYOUT_ID - DERIVED from the field table
 *      8   2  version   HC_CFG_VERSION
 *     10   2  length    HC_CFG_SIZE
 *     12   4  generation
 *     16   2  header CRC16-CCITT over bytes 0..15
 *     18   N  payload   the 4096-byte page
 *   18+N   2  payload CRC16-CCITT
 *   20+N   4  COMMIT    'DONE'   <-- PROGRAMMED LAST, and only after every
 *                                    payload word has verified by read-back
 *
 * An erased sector is 0xFF everywhere and a program can only clear bits, so
 * every field is written after the erase and the commit marker cannot appear
 * before the thing it commits. A record without an intact commit marker is
 * never selected - not at boot, not ever. Cut power at any point and the OTHER
 * slot is still whole.
 *
 * HC_CFG_LAYOUT_ID is the part that stops the subtler failure. It is a CRC32
 * over every field's slot name, offset, C type and element count, emitted by
 * the generator - so a firmware that moved one field by one byte REFUSES an
 * older record instead of silently reinterpreting every table past it. A
 * length and a CRC would both still have matched.
 *
 * ===========================================================================
 * 7. WHAT IS STILL EXPOSED, SAID PLAINLY
 * ===========================================================================
 *
 * While the device is physically erasing, the CPU cannot fetch an instruction
 * from it. If the monitoring module resets us in that window the boot block
 * itself reads status bits and the ECU may reset a few more times before the
 * device finishes on its own. It is self-correcting - the sector map used here
 * is NOT in the bootrom's checksum inputs, so a blank or partial SA7 does not
 * stop a boot - but it is a real few seconds of reset activity and it is the
 * reason a burn requires the engine stopped.
 *
 * NOT PHYSICALLY VERIFIED, all of it: no HaniCore image has yet written one
 * byte of this ECU's flash, and none has yet fetched an instruction from the
 * external SRAM on real ME7.1.1 hardware.
 */
#ifndef HCNVM_H
#define HCNVM_H

/* ---------------------------------------------------------------- state --
 * Published to TunerStudio. "I pressed Burn - did it actually save?" has to
 * have an answer, and this is it. */
#define HCNV_ST_IDLE        0u  /* nothing staged                            */
#define HCNV_ST_DIRTY       1u  /* the page has changed since the last burn  */
#define HCNV_ST_PENDING     2u  /* burn staged, waiting for a safe state     */
#define HCNV_ST_ARMED       3u  /* burn staged and safe; live programming next */
#define HCNV_ST_COMMITTING  4u  /* bounded RAM-writer transaction is running */
#define HCNV_ST_DONE        5u  /* committed to flash and verified           */
#define HCNV_ST_FAILED      6u  /* gave up; the previous record still stands */
#define HCNV_ST_STAGING     7u  /* building the record, a chunk per pass     */

/* ---------------------------------------------------------------- phase --
 * Where a commit had got to when it was last interrupted. */
#define HCNV_PH_NONE        0u
#define HCNV_PH_PROGRAM     1u
#define HCNV_PH_COMMIT      2u

/* ---------------------------------------------------------------- error -- */
#define HCNV_ERR_NONE       0u
#define HCNV_ERR_RAM        1u  /* the external SRAM probe failed            */
#define HCNV_ERR_VALIDATE   2u  /* DESIRED does not describe a runnable engine */
#define HCNV_ERR_STAGE      3u  /* the staged record did not verify           */
#define HCNV_ERR_ERASE      4u  /* the sector would not go blank              */
#define HCNV_ERR_PROGRAM    5u  /* a word would not take                      */
#define HCNV_ERR_VERIFY     6u  /* it programmed and then did not read back   */
#define HCNV_ERR_RETRIES    7u  /* too many interrupted attempts; gave up     */
#define HCNV_ERR_LAYOUT     8u  /* a record from a different page layout      */
#define HCNV_ERR_FULL       9u  /* all append-only cells are consumed          */
#define HCNV_ERR_DEADLINE  10u  /* standard-B durable deadline could not be met */

/* ---------------------------------------------------------- what booted --
 * Where the ACTIVE calibration came from at this boot. Published, because a
 * tuner who has just been handed compiled defaults must be told. */
#define HCNV_SRC_DEFAULTS   0u  /* compiled-in                               */
#define HCNV_SRC_STANDBY    1u  /* the battery-backed SRAM page              */
#define HCNV_SRC_FLASH_A    2u
#define HCNV_SRC_FLASH_B    3u

/* hc_nvm_slot() is the STORE SECTOR holding the active record, 1..10, with 0
   for "no committed record". Up to V52 the store was two sectors and this was
   an A/B flag; V53 gave it ten, so it carries the index. HCNV_SLOT_A is kept
   as the name of sector 1 so nothing that tested "is there a record" breaks. */
#define HCNV_SLOT_NONE      0u
#define HCNV_SLOT_A         1u
#define HCNV_SLOT_B         2u
#define HCNV_SLOT_MAX       TGT_FLASH_SECTORS

/* Bounded, and the bound is the point: a commit that keeps being interrupted
   must eventually stop trying rather than turn the ECU into a reset loop. */
#define HCNV_MAX_ATTEMPTS   6u

/* --------------------------------------------------------------- the API -- */

/* Scan append-only cells, decide where the ACTIVE calibration comes from, and
   handle a prior interrupted intent conservatively. Called from main() AFTER
   hc_cfg_init()/hc_cfg_mgr_init() and BEFORE hc_asic_start_init() and IEN=1. */
void hc_nvm_boot(void);

/* THE SEMANTIC HALF OF THE RECOVERY, and it is a separate call on purpose.
 *
 * hc_nvm_boot() restores the newest record that survives its CRC.
 * hc_nvm_lkg_walkback() then asks whether that record DESCRIBES SOMETHING
 * THAT CAN RUN, and steps back through older generations until one does or
 * the bound is reached. Called from main() between hc_nvm_boot() and
 * hc_cfg_mgr_init(), so the board-default floor in hc_cfg_mgr_init() is
 * unchanged and still catches the case where nothing in the store validates.
 *
 * hc_nvm_lkg_steps() is how many generations it had to go back: 0 is the
 * ordinary case and anything else is worth a tuner seeing. */
void hc_nvm_lkg_walkback(void);
unsigned int hc_nvm_lkg_steps(void);

/* A TunerStudio burn. Validates, commits to the standby page, and SNAPSHOTS
   the whole record into the staging buffer. Returns HCNV_ERR_*; never blocks,
   never touches flash, never stops an engine. */
unsigned int hc_nvm_request(void);

/* Called from the main loop. Moves PENDING -> ARMED when the engine is stopped
   and the ECU is safe, then performs one bounded RAM-writer chunk per pass.
   The deferred TS acknowledgement is sent only after DONE, scan and live
   source selection succeed. Takes facts as parameters so a gate can drive it. */
void hc_nvm_service(unsigned int now_ms, unsigned int rpm,
                    unsigned char trig_turning, unsigned char outputs_busy,
                    unsigned char page_stable);

/* Mark the page as edited since the last burn. Cheap; called from the write
   path. */
void hc_nvm_mark_dirty(void);

/* THE PROGRAMMER ITSELF, and the marker that gives its length.
 *
 * Public ONLY so that me711_flash_busy_proof can name them: a static function
 * does not appear in the linker map, and a gate that cannot name what it is
 * checking is checking something else. NOTHING may call hc_nvm_payload() -
 * it runs from a COPY of itself in external SRAM while the NOR is busy, then
 * restores read-array and returns. Only the NVM module enters it. */
void far hc_nvm_payload(void);
void far hc_nvm_payload_end(void);

/* ------------------------------------------------------------- published --
 *
 * FUNCTIONS AND NOT GLOBALS. Every mutable value this module owns lives in the
 * external SRAM block TGT_RAM_NVM, so the module costs ZERO near RAM - near
 * RAM on this target is 1792 bytes and near_ram_hazard_proof keeps a 192-byte
 * engineering reserve for the engine subsystems still to land. This is the
 * same decision hc_dbw.c and hc_plan.c made for the same measured reason, and
 * it has a second benefit: the control block has to survive a reset anyway, so
 * a near-RAM mirror would have been a SECOND COPY of the same facts.
 *
 * Each one answers honestly when the SRAM is unusable - hc_nvm_error() then
 * reads HCNV_ERR_RAM and the rest read their idle value.
 */
unsigned int  hc_nvm_state(void);        /* HCNV_ST_*                        */
unsigned int  hc_nvm_phase(void);        /* HCNV_PH_*                        */
unsigned int  hc_nvm_error(void);        /* HCNV_ERR_*                       */
unsigned int  hc_nvm_slot(void);         /* HCNV_SLOT_* - the ACTIVE record  */
unsigned int  hc_nvm_source(void);       /* HCNV_SRC_*                       */
unsigned int  hc_nvm_generation(void);   /* low word of the active record    */
unsigned int  hc_nvm_attempts(void);
unsigned int  hc_nvm_commits(void);      /* successful commits, this battery */
unsigned int  hc_nvm_words_total(void);
unsigned int  hc_nvm_words_completed(void);
unsigned int  hc_nvm_words_remaining(void);
unsigned int  hc_nvm_live_owner(void);
unsigned int  hc_nvm_live_admission(void);
unsigned int  hc_nvm_live_pause_reason(void);
unsigned int  hc_nvm_live_windows_ok(void);
unsigned int  hc_nvm_live_windows_rejected(void);
unsigned int  hc_nvm_live_deadline_ms(void);
unsigned int  hc_nvm_live_horizon_us(void);
unsigned int  hc_nvm_live_predicted_ms(void);
unsigned int  hc_nvm_live_writer_entries(void);
unsigned int  hc_nvm_live_writer_success(void);
unsigned int  hc_nvm_live_writer_failures(void);
unsigned int  hc_nvm_live_mask(void);
unsigned int  hc_nvm_live_pending_before(void);
unsigned int  hc_nvm_live_pending_after(void);
unsigned int  hc_nvm_live_vector_violations(void);
/* The ASIC transfer launcher queries this before changing SSC/PEC state.
   It is true only for the short, admitted AM29 busy ownership interval. */
unsigned char hc_nvm_word_owned(void);

/* ------------------------------------------------------- the RAM probe -----
 *
 * THE ONE PRECONDITION OF THE FLASH PROGRAMMER THAT NOTHING HAS EVER TESTED ON
 * THIS BOARD: that this C167 can fetch instructions from the external SRAM at
 * TGT_RAM_FLASHRT and return from them. Every proof of it in this repository
 * is a simulator proof.
 *
 * hc_nvm_ramtest() answers it with nothing at stake. It copies a small routine
 * into exactly that region, CALLs it across the segment boundary, and checks
 * that it did real work and came back:
 *
 *   - the routine reads a SEED the caller chose this run, so a stale or
 *     hardcoded answer cannot pass;
 *   - it runs a LOOP WITH A CONDITIONAL BRANCH, so a board that can fetch
 *     straight-line code from SRAM but not branch in it fails;
 *   - it writes its 0x5A3C signature LAST, so a routine that ran only part of
 *     the way is distinguishable from one that never ran;
 *   - it returns with RETS - it is declared `void far`, so the compiler emits
 *     the segmented return and a matching prologue itself - which is what
 *     makes this a test of RETURNING and not just of jumping.
 *
 * IT TOUCHES NO FLASH, DRIVES NO PIN AND CHANGES NO CALIBRATION, so it is safe
 * to run before any erase - which is the whole point of having it.
 *
 * If the board cannot do this, the CPU does not come back. hc_nvm_ram_state()
 * is written to HCNV_RP_RUNNING BEFORE the call and lives in battery-backed
 * SRAM, so after the reset it still reads RUNNING and that is the diagnosis.
 */
#define HCNV_RP_IDLE     0u   /* never run on this battery                   */
#define HCNV_RP_RUNNING  1u   /* called, and it has not come back yet        */
#define HCNV_RP_PASS     2u   /* returned, signature present, answer correct */
#define HCNV_RP_WRONG    3u   /* returned and signed, but computed rubbish   */
#define HCNV_RP_NOSIG    4u   /* returned without the signature              */
#define HCNV_RP_REFUSED  5u   /* the SRAM itself is unusable                 */
#define HCNV_RP_UNSAFE   6u   /* asked for while the engine could be turning */

/* Runs the probe and returns the resulting HCNV_RP_*.
 *
 * seed: the caller chooses it, so a stale or hardcoded answer cannot pass. 0
 *       is replaced, because 0 shifts to 0 and would prove nothing.
 * safe: the caller asserts rpm 0, no crank signal and no bench output running.
 *       The facts come in as parameters exactly as they do for
 *       hc_nvm_service(), because this module does not read the engine. When
 *       it is 0 the probe REFUSES AND SAYS SO - HCNV_RP_UNSAFE - rather than
 *       doing nothing quietly. */
unsigned int  hc_nvm_ramtest(unsigned int seed, unsigned char safe);

unsigned int  hc_nvm_ram_state(void);    /* HCNV_RP_*                        */
unsigned int  hc_nvm_ram_runs(void);     /* probes attempted, ever           */
unsigned int  hc_nvm_ram_seed(void);     /* the seed the last run used       */
unsigned int  hc_nvm_ram_result(void);   /* what the routine in SRAM computed */

/* 1 when a valid, committed flash record exists. This is the ONE thing that
   lets hc_cfg_persist_class() answer HC_PERSIST_NONVOL, and it is set from
   evidence read out of the device rather than from a build-time constant. */
unsigned char hc_nvm_nonvol(void);

/* ================================================ THE PROGRAMMER'S DIARY ===
 *
 * V42. TWO BENCH BURNS FAILED WITH "a word would not program" AND NEITHER
 * DUMP COULD SAY WHY, so the next one says it on the screen.
 *
 * What the V40 and V41 bootmode readbacks proved, and it is not ambiguous:
 * the failing word was NEVER PULSED - all sixteen bits still erased - no word
 * was skipped, no word was partially programmed, and nothing was written
 * anywhere else in the 1 MiB device. The four-cycle command sequence was not
 * accepted, and V40 polled the word for about 35 ms before giving up, so the
 * part was not merely slow. What the dump CANNOT say is which of half a dozen
 * transient reasons it was, and a 1 MiB readback will never say it either -
 * the evidence is in the microseconds, not in the bytes.
 *
 * So these values are recorded BY THE RAM WRITER ITSELF, as it happens, into
 * the battery-backed block, and published. They cost no near RAM and they are
 * the difference between another forensic cycle and an answer.
 *
 *   hc_nvm_prog_retries()  how many times a command sequence had to be
 *                          re-issued for the WHOLE commit. This is the
 *                          measurement the project has never had: the rate at
 *                          which this hardware refuses a program command.
 *   hc_nvm_poll_min()      the SHORTEST word-program poll seen, in T7 ticks
 *                          of 0.8 us. A normal word is 11 us, about 14 ticks.
 *                          A minimum near ZERO would mean the poll is
 *                          matching on status that happens to look like the
 *                          datum - a hypothesis that has been carried for two
 *                          bench runs and never measured.
 *   hc_nvm_poll_max()      the longest, same units.
 *   hc_nvm_fail_word()     the record word index that would not take,
 *                          0xFFFF when none has.
 *   hc_nvm_fail_exp()      the datum it was given.
 *   hc_nvm_fail_got()/2()  the two reads the poll gave up on. 0xFFFF twice
 *                          means the device was answering with erased array
 *                          data - it never started. Anything else is status.
 *   hc_nvm_prog_flags()    low byte HCNV_PF_*, high byte the attempts the
 *                          worst word needed.
 */
#define HCNV_PF_DQ5        0x01u  /* the device itself reported a failure    */
#define HCNV_PF_DISAGREE   0x02u  /* two reads of one address disagreed      */
#define HCNV_PF_SETTLE     0x04u  /* it read back right, then read back wrong */
#define HCNV_PF_NOTIDLE    0x08u  /* the device was not settled at chunk entry */
#define HCNV_PF_RETRY_OK   0x10u  /* a re-issued sequence DID take           */
#define HCNV_PF_GAVEUP     0x20u  /* every attempt on one word failed        */
#define HCNV_PF_UNSAFE     0x40u  /* retry target had an unexpected 0 bit    */
#define HCNV_PF_STUCK      0x80u  /* it would not return to read-array mode  */

unsigned int  hc_nvm_prog_retries(void);
unsigned int  hc_nvm_poll_min(void);
unsigned int  hc_nvm_poll_max(void);
unsigned int  hc_nvm_fail_word(void);
unsigned int  hc_nvm_fail_exp(void);
unsigned int  hc_nvm_fail_got(void);
unsigned int  hc_nvm_fail_got2(void);
unsigned int  hc_nvm_prog_flags(void);
/* V45 retained forensic trace.  Values are in hcburnforensics' separate
   38:68A0 record, never in the RAM-probe block: 0 idle, 1 B parsed,
   2 request accepted, 3 snapshot, 4 target selected, 5 COMMITTING,
   6 writer prepared, 7 immediately before writer, 8 writer returned,
   9 progress, 10 retry, 11 DONE verified, 12 TS_OK pending,
   13 terminal TX entered, 14 terminal TX completed. */
unsigned int  hc_nvm_commit_stage(void);
unsigned int  hc_nvm_commit_last_stage(void);
unsigned int  hc_nvm_commit_fail_stage(void);

/* ------------------------------------------------- the reclaim, published --
 * V53. The store is reclaimed by erasing a sector, and that has never run on
 * silicon. These exist so a bench can tell "it worked", "it is still working"
 * and "it gave up, here is why" apart without a 1 MiB dump.
 *
 * hc_nvm_erase_slices() is the one to watch: the Am29F800B datasheet bounds
 * the Erase Suspend LATENCY but never the resume-to-suspend interval, so
 * nothing can promise a sliced erase converges. If it does not, the symptom is
 * that the slice count climbs and hc_nvm_reclaims() never moves. */
unsigned int  hc_nvm_free_cells(void);    /* blank cells the last scan found  */
unsigned int  hc_nvm_cells_total(void);   /* TGT_FLASH_CELLS                  */
unsigned int  hc_nvm_erase_state(void);   /* low HCNV_ER_*, high sector       */
unsigned int  hc_nvm_erase_slices(void);  /* suspend/resume cycles, this erase */
unsigned int  hc_nvm_erase_ms(void);      /* wall time the last erase took    */
unsigned int  hc_nvm_reclaims(void);      /* sectors reclaimed, this battery  */
unsigned int  hc_nvm_erase_fails(void);   /* erases abandoned, this battery   */
unsigned int  hc_nvm_erase_tries(void);   /* low tries, high rejected sectors */
unsigned int  hc_nvm_erase_status(void);  /* last status word the poll read   */

#endif /* HCNVM_H */
