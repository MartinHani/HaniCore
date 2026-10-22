/*
 * hc_config_manager.h - the DESIRED / ACTIVE configuration state machine.
 *
 * THE PROBLEM IT SOLVES. TunerStudio writes one page byte at a time. A tuner
 * who changes an injector routing from A to B to C to D while the engine turns
 * must have the engine keep running A the whole time, and must get D - not B,
 * then C, then D - the instant it stops. A byte-at-a-time write straight into
 * the running configuration passes through states that describe no engine at
 * all, and one of them fires an injector at the wrong time.
 *
 * TWO IMAGES, ONE PAGE LAYOUT:
 *
 *   DESIRED   TGT_RAM_CFGDESIRED, 4 KB of the battery-backed external SRAM.
 *             What the host writes and reads back. Always the latest thing
 *             the tuner typed.
 *
 *   ACTIVE    hcconfig's own storage - hc_cfg[] plus the calibration region.
 *             What the runtime reads, through the hc_cal_* accessors it has
 *             always used. NOT ONE RUNTIME READ SITE CHANGES.
 *
 * and three policies, generated per field from the model rather than inferred
 * from an offset range:
 *
 *   LIVE_APPLY        written to both images at once. Calibration.
 *   RPM_ZERO_APPLY    written to DESIRED only. The first time the engine is
 *                     stopped, the whole dirty apply GROUP is validated and
 *                     copied across in one pass. Not a queue: the copy takes
 *                     whatever DESIRED holds now, so A->B->C->D applies D and
 *                     never replays B or C.
 *   RESTART_REQUIRED  written to DESIRED only, and NEVER copied across. It
 *                     reaches the runtime through persistence and the next
 *                     boot. hc_cfg_restart_pending says so; nothing else
 *                     happens.
 *
 * ATOMICITY IS PER GROUP. A group is validated as a whole and then copied as
 * a whole with interrupts disabled around each field, so the runtime cannot
 * observe half of a new cylinder-to-output map. If validation fails, NOTHING
 * is copied and the previous ACTIVE configuration stays exactly as it was.
 *
 * WHAT THIS DOES NOT DO. It does not know about K-line, or about TunerStudio.
 * hcts.c calls hc_cfg_mgr_write_u8() where it used to call hc_cal_set_u8();
 * a CAN or USB transport would call the same function. The transport is not
 * part of the configuration semantics.
 */
#ifndef HC_CONFIG_MANAGER_H
#define HC_CONFIG_MANAGER_H

#include "hctarget.h"   /* HC_COLD: far on ME7.1.1 (FCODE), empty elsewhere */
#ifndef HC_COLD
#define HC_COLD
#endif

#include "hc_config_generated.h"
#include "hc_validation.h"

#define HC_V101_SCHEMA 0x30D2u
#define HC_V101_LAYOUT 0x332F8D11uL
unsigned char HC_COLD hc_cfg_page_known(void);
unsigned char HC_COLD hc_cfg_identity_known(unsigned int layout_hi, unsigned int layout_lo, unsigned int schema);
unsigned char HC_COLD hc_cfg_migrate_v101(void);
void HC_COLD hc_cfg_v102_defaults(void);
void HC_COLD hc_cfg_aux_defaults(void);      /* 2026-10-14, hcaux711.c */

/* Copy ACTIVE into DESIRED and clear every pending state. Call once, after
   hc_cfg_init() has decided where ACTIVE came from. */
void HC_COLD hc_cfg_mgr_init(void);

/* Call from the main loop with the current engine speed. Does nothing at all
   unless something is dirty AND rpm is zero. Bounded: it walks the generated
   slot table once, not the 4096 bytes of the page. */
void HC_COLD hc_cfg_mgr_service(unsigned int rpm);

/* A BURN WITH THE ENGINE TURNING (2026-10-11 car). The flash store can only
   take a word inside a gap between crank teeth longer than the flash word
   guard (~727 rpm on a 60-2), so a Burn at idle could never finish: it ran
   to the 6 s deadline and failed - after the standby page had already been
   committed (flash and SRAM then disagreed). Now: the page is validated and
   committed to the battery-backed standby page at once (it survives a key
   cycle), the request is remembered, and the flash Burn runs when the
   engine has been stopped for HC_BURN_STOP_MS. _defer returns the
   validation result (HC_VAL_OK = accepted); _due returns 1 once, when the
   target should start the flash Burn now; _pending reads the flag. */
#define HC_BURN_STOP_MS  500u
unsigned int  HC_COLD hc_cfg_mgr_burn_defer(void);
unsigned char HC_COLD hc_cfg_mgr_burn_due(unsigned int now_ms,
                                          unsigned char stopped);
unsigned char HC_COLD hc_cfg_mgr_burn_pending(void);

/* Move the deferred DESIRED copy along by one bounded chunk. Returns 1 while
   there is still work to do.

   THE CALLER DECIDES WHEN THIS IS SAFE, and on the ME7.1.1 that means AFTER
   the ASIC startup handshake has reached its runtime state. This is not
   defensive coding, it is a measured result: with the copy running during the
   handshake - whether all at once in init or spread a chunk per main-loop
   pass - me711_boot_test fails six checks, because every chunk is a main-loop
   pass that does not poll the serial port or service the exchange. The
   supervision link comes up first; the configuration layer does its bulk work
   afterwards. Nothing needs the copy before then: the only things that read
   DESIRED force it to completion themselves. */
unsigned char HC_COLD hc_cfg_mgr_seed_step(void);

/* The host's view of the page. Reads see DESIRED, so a tuner reads back what
   they typed even while the engine is still running the old value. */
unsigned char HC_COLD hc_cfg_mgr_read_u8(unsigned int off);
/* DESIRED as it stands, without finishing the deferred seed copy: for the
   serial transmit interrupt, after hc_cfg_mgr_read_u8() finished it. */
unsigned char HC_COLD hc_cfg_mgr_peek_u8(unsigned int off);
void HC_COLD          hc_cfg_mgr_write_u8(unsigned int off, unsigned char v);

/* Big-endian, matching the page's own convention and `endianness = big` in
   the .ini. */
unsigned int HC_COLD  hc_cfg_mgr_read_u16(unsigned int off);
void HC_COLD          hc_cfg_mgr_write_u16(unsigned int off, unsigned int v);

/* Force the pending RPM_ZERO groups to be considered now. Returns the
   validation result; HC_VAL_OK means they were applied. Used by a bench
   command and by the tests; the main loop uses hc_cfg_mgr_service(). */
unsigned int HC_COLD hc_cfg_mgr_apply_now(unsigned int rpm);

/* Validate DESIRED and, if it is sound, hand it to the persistence layer.
   Returns the validation mask; HC_VAL_OK means the commit was attempted.
   See hc_cfg_persist_state() for what "persisted" is actually worth on this
   hardware - it is NOT the same as flash. */
unsigned int HC_COLD hc_cfg_mgr_commit(void);
/* the Burn's commit - see hc_config_manager.c. stopped = engine
   demonstrably stopped: pending groups applied and RESTART_REQUIRED
   fields promoted into ACTIVE before the page is persisted. */
unsigned int HC_COLD hc_cfg_mgr_commit_burn(unsigned char stopped);

/* Re-validate DESIRED without applying anything. */
unsigned int HC_COLD hc_cfg_mgr_validate(void);

/* ------------------------------------------------ a many-field transaction
 *
 * V86, for the engine preset (hc_preset_apply_engine). A preset changes a
 * hundred-odd bytes across every apply group, LIVE calibration included, and
 * must land whole or not at all:
 *
 *   txn_begin()        open; forget any previous log
 *   txn_put_u8(o, v)   log DESIRED[o]'s current byte, then write v to
 *                      DESIRED ONLY - no policy, no ACTIVE, no dirty bit
 *   txn_commit(rpm)    validate the WHOLE resulting DESIRED page. Refused (or
 *                      rpm != 0, or the log overflowed): put every logged
 *                      byte back in reverse order and return the faults -
 *                      DESIRED is as it was and ACTIVE was never touched.
 *                      Accepted: re-issue every staged byte through
 *                      hc_cfg_mgr_write_u8() - the ordinary policy - then
 *                      hc_cfg_mgr_apply_now(rpm). Never Burns.
 *
 * The log lives in external SRAM (TGT_RAM_PRESETUNDO): run-length since
 * V92, one byte per staged byte plus five per contiguous run.
 * Main-loop context only: the commit validates twice (~5 ms each, behind the
 * same tick-gated yield as every other long configuration pass). */
void HC_COLD         hc_cfg_mgr_txn_begin(void);
void HC_COLD         hc_cfg_mgr_txn_put_u8(unsigned int off, unsigned char v);
unsigned int HC_COLD hc_cfg_mgr_txn_commit(unsigned int rpm);

/* The last transaction's validation result - HC_VAL_OK, the refusal mask, or
   HC_VAL_FAULT_NOT_STOPPED. hc_val_first_bad_offset still names the field. */
extern unsigned int  hc_cfg_txn_faults;

/* ------------------------------------------------------------ telemetry --
 * Small, and each one answers a question a tuner actually asks. */

/* Bit g set = apply group g has RPM_ZERO changes waiting for the engine to
   stop. Zero means DESIRED and ACTIVE agree on everything that can be
   applied. */
extern unsigned int  hc_cfg_dirty_groups;

/* BIT 15 MEANS "ALREADY REFUSED, AND NOTHING HAS CHANGED SINCE".
 *
 * A refused apply deliberately KEEPS its dirty groups so the tuner can fix
 * the problem and the same transaction lands. What it must not do is re-run
 * hc_validate() over the whole configuration on every main-loop pass while
 * it waits - which is what it did until V57, and which MEASURED 1364 -> 175
 * main-loop passes per second on the real ECU. The live Burn programs its
 * flash record one word per main-loop pass, so that is the whole runtime and
 * every Burn with it.
 *
 * The bit lives here rather than in a new variable because it costs no near
 * RAM - this target has 129 bytes free against a 192-byte reserve - and
 * because it is then VISIBLE: cfgDirtyGroups reading 0x8004 says "the trigger
 * group is staged and the ECU has stopped trying", which is exactly the state
 * a bench needs to be able to see. Groups occupy bits 0..10; the mask keeps
 * the two meanings apart. */
#define HC_CFG_DIRTY_BLOCKED  0x8000u
#define HC_CFG_DIRTY_GROUPS   0x7FFFu

/* The last validation result over DESIRED. HC_VAL_OK = 0. */
extern unsigned int  hc_cfg_validation;
/* 1 = the restored page failed hc_validate() at boot and the board
   defaults were seeded over it. Published, never silent. */
extern unsigned char hc_cfg_boot_fellback;

/* Non-zero when a RESTART_REQUIRED field differs between DESIRED and ACTIVE.
   The runtime is deliberately still using the old value. */
extern unsigned char hc_cfg_restart_pending;

/* Incremented on every accepted DESIRED write; lets a host see its edit land
   and lets a test tell "applied" from "applied twice". */
extern unsigned int  hc_cfg_desired_rev;

/* Incremented every time a group is copied into ACTIVE. */
extern unsigned int  hc_cfg_active_rev;

/* How many group applications have been refused by validation. A non-zero
   value with a non-zero hc_cfg_dirty_groups is the "your change is not
   running, and here is why" state. */
extern unsigned int  hc_cfg_apply_refused;

/* 1 when this boot had to migrate the stored page's universal block into the
   current schema - i.e. the ECU came up on a page written by an image that
   predates it. Published so "why are all my pin assignments gone" has an
   answer that is visible rather than deduced. */
extern unsigned char hc_cfg_migrated;

#endif /* HC_CONFIG_MANAGER_H */
