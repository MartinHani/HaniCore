/*
 * hcupd711.h - the app-side OBD updater (P3). READ hcnvm.h and
 * firmware/loader/hcloader.a66 FIRST: this is the running app's half of the
 * same contract the loader finishes.
 *
 * The flow (.scratch/firmware-update/spec.md section 11, P3):
 *
 *   host 'u'  STAGE_BEGIN  -> erase STAGING SA15..SA18 (sliced, admitted,
 *                            exactly as a store reclaim: fl_enter/live_admit)
 *   host 'w'  STAGE_WRITE  -> program one <=64-byte chunk into STAGING in
 *                            word order, folding it into the running CRC-32
 *                            (the frozen contract: the 32-byte image header at
 *                            offset 0x0200 is EXCLUDED)
 *   host 'x'  STAGE_SEAL   -> the running CRC must equal the host's; only then
 *                            is the staging header's 0x5AA5 seal programmed,
 *                            LAST, so a cut before it leaves unsealed staging
 *   host 'y'  COMMIT       -> write the battery-SRAM request 'UP'/'DT', read it
 *                            back (the 2.7T SRST lost-write rule), then SRST;
 *                            the loader copies STAGING over the APP and reseals
 *
 * Every command answers TS_OK whatever it did; the host reads the verdict
 * from the status channel (HC_UPD_OCH_*, below) between stop-and-wait steps.
 * The host keeps polling while the ECU erases and programs, so an updater
 * image keeps K-line receive live through its flash windows (hcnvm.c
 * HCNV_PECRX_MIN) and arms the admission deadline per step (upd_admit).
 * After an update that changed the page layout, the next Burn is numbered
 * above every committed record of ANY layout (hcnvm.c stage_step), so the
 * refused old records cannot hide the migrated tune.
 * Chunks stream: hc_upd_write() appends a chunk to the job being programmed
 * (strict order, UPD_BUF_CAP) so the host need not poll between chunks.
 * The driver serves the K-line between flash windows (hc_serial_boundary).
 * STAGING sectors 1..3 erase in the background while sector 0 is written.
 * '!b' moves the link to 250 kbaud for the transfer (TGT_S0BG_250000).
 * The CRC-32 is folded with hcserial711.c's nibble table (hc_crc32_update).
 * HC_UPD_OCH_PEND tells the host how full the job queue is (flow control).
 * While READY the driver keeps serving the link inside its pass budget.
 * A streamed job is compacted when it reaches UPD_BUF_CAP (hc_upd_write).
 *
 * NOTHING HERE CAN CORRUPT A RUNNING APP OR A STORED TUNE. STAGING (SA15..SA18)
 * is separate from the store (SA10..SA14) and from the APP (SA6..SA9). A failed
 * or interrupted staging is unsealed or short, which the loader's header/seal/
 * length check rejects - it runs the existing valid APP. A bad APP that somehow
 * got sealed is bootmode-recoverable. The blast radius is one scratch region.
 *
 * CODE PLACEMENT (the far/near split that keeps the release byte-identical and
 * fits the updater image). The relocatable staging programmer and ONE admitted
 * step helper (hc_nvm_stage_op) stay in hcnvm.c (NCODE) - the programmer must,
 * because fl_prepare_sel() copies it from the 0x84 segment, and the helper is
 * the only updater code that touches this file's proven flash machinery. The
 * state machine, the CRC-32 fold and the host command bodies live in the FCODE
 * host (hcdiag711.c), so the cold driver does not pressure NCODE. The driver
 * reaches the one helper through the hcfarbridge.h thunk, like every other far
 * module. The whole thing is behind HC_UPDATER, so a release build compiles not
 * one byte of it and hcnvm.c's proven store path is byte-identical.
 */
#ifndef HCUPD711_H
#define HCUPD711_H

#include "hctarget.h"

#if HC_UPDATER

/* ---- state, published to the host (a status read / identity) ------------- */
#define HC_UPD_ST_IDLE     0u  /* no update in progress                       */
#define HC_UPD_ST_ERASING  1u  /* erasing STAGING, a slice per main-loop pass */
#define HC_UPD_ST_READY    2u  /* STAGING blank; ready for chunks             */
#define HC_UPD_ST_WRITING  3u  /* programming a chunk, a word per fl_enter    */
#define HC_UPD_ST_SEALED   4u  /* CRC matched and the seal is programmed      */
#define HC_UPD_ST_COMMIT   5u  /* request written and read back; SRST next    */
#define HC_UPD_ST_FAILED   6u  /* gave up; STAGING is unsealed, APP untouched */

/* ---- shared battery-SRAM layout (both the NCODE helper and the FCODE driver)
 * The control block sits ABOVE the loader's request words (0x386904/06, inside
 * TGT_RAM_SPARE_B) so the two never overlap. The chunk buffer reuses the store
 * record staging buffer (NVM_STAGE); an update and a Burn never run at once
 * (the store is gated off while an update owns the flash machinery). */
#define UPD_CB        (TGT_EXTRAM_BASE + TGT_RAM_SPARE_B + 0x10uL)
#define UPD_REQ0      (TGT_EXTRAM_BASE + TGT_RAM_SPARE_B + 0x04uL)  /* 0x386904 */
#define UPD_REQ1      (TGT_EXTRAM_BASE + TGT_RAM_SPARE_B + 0x06uL)  /* 0x386906 */
#define UPD_STAGEBUF  (TGT_EXTRAM_BASE + TGT_RAM_FLASHBUF)          /* ==NVM_STAGE */
#define UPD_REQ_UP    0x5055u   /* 'UP' */
#define UPD_REQ_DT    0x5444u   /* 'DT' */
#define UPD_MAGIC_VALUE 0x48435550uL   /* 'HCUP' */

#define U_MAGIC    0u   /* 4 : 'HCUP'                                        */
#define U_STATE    4u   /* 1 : HC_UPD_ST_*                                   */
#define U_ERROR    5u   /* 1 : HCNV_ERR_* of the last failure                */
#define U_SECTOR   6u   /* 1 : STAGING sector being erased, 0..3             */
#define U_PAYRES   7u   /* 1 : result of the last stage-payload fl_enter     */
#define U_DSEG     8u   /* 1 : dest segment of the chunk (0x8C..0x8F)        */
#define U_TRIES    9u   /* 1 : program attempts on the current word          */
#define U_ISSEAL  10u   /* 1 : the queued chunk is the final seal word       */
#define U_LASTRC  11u   /* 1 : HCNV_ERR_* the last '!u/w/x/y' command returned */
#define U_POS     12u   /* 2 : word index within the current chunk           */
#define U_CHUNKW  14u   /* 2 : words in the current chunk                    */
#define U_DOFF    16u   /* 2 : in-segment byte offset of the chunk           */
#define U_RECV    18u   /* 4 : bytes accepted into STAGING so far            */
#define U_CRC     22u   /* 4 : running CRC-32 register (pre final XOR)       */
#define U_SEQ     26u   /* 1 : count of updater commands handled (mod 256)   */
#define U_LASTCMD 27u   /* 1 : the last command letter ('u','w','x','y')     */
#define U_FAST    28u   /* 1 : '!b' asked for TGT_S0BG_250000 (switch pending) */
#define U_ERDONE  29u   /* 1 : STAGING sectors fully erased, 0..4 - the rest erase
                           in the background while chunks stream (Am29F800B: program
                           a non-erasing sector while an erase is suspended) */
#define U_LEN     30u

/* ---- hc_nvm_stage_op() dispatch: one admitted step the FCODE driver asks the
 * NCODE helper to take. The helper owns the relocation slot, the eraser and the
 * interrupt window; the driver owns everything else. */
#define HC_SOP_ERASE_BEGIN 0u  /* begin erasing the sector in U_SECTOR        */
#define HC_SOP_ERASE_SLICE 1u  /* one erase slice (self-advances sectors)     */
#define HC_SOP_PROG_SLICE  2u  /* one word of the current chunk               */
/* ... and what it returns: */
#define HC_SOP_DEFER  0u   /* not admitted this pass; nothing done           */
#define HC_SOP_OK     1u   /* progress; the caller may continue/return       */
#define HC_SOP_DONE   2u   /* the unit (whole erase / chunk) completed        */
#define HC_SOP_FAIL   3u   /* gave up                                        */

/* UPD_PASS_US bounds how long the WRITING driver keeps the main loop per pass,
 * exactly as HCNV_PASS_US bounds the store programmer (which is hcnvm.c-local).
 */
#define UPD_PASS_US   30000u  /* see below */
/* 30 ms, not the Burn's 2.5: an update runs only with the engine stopped and
 * the throttle bridge off (outputs_busy), and inside the pass the driver
 * yields (watchdog, tick services) and serves the K-line between flash
 * windows. With a short pass the rest of the main loop took ~88 % of the CPU
 * between passes and the programmer ran at ~4 KB/s (bench 2026-10-30,
 * rate_probe_6). T7 wraps at 87 ms (2.7T) / 52 ms (40 MHz): 30 ms is inside. */

/* UPD_BUF_CAP: how many bytes of streamed chunks one programming job may hold
 * (the staging buffer is TGT_RAM_FLASHBUF, 0x1400; the Burn never runs while
 * an update owns the flash machinery). */
#define UPD_BUF_CAP   4096u

/* ---- the ONE NCODE helper (hcnvm.c), reached from FCODE via the bridge ---- */
unsigned int hc_nvm_stage_op(unsigned int op, unsigned int now_ms,
                             unsigned int rpm, unsigned char trig_turning,
                             unsigned char outputs_busy,
                             unsigned char page_stable);

/* ---- the FCODE driver (hcdiag711.c) --------------------------------------
 * hc_upd_service() is the main-loop driver: one admitted erase/program slice
 * per pass, like a Burn. hc_upd_active() is 1 whenever an update owns the flash
 * machinery, so the main loop gates hc_nvm_service() off. hc_upd_boot_reset()
 * clears a stale control block at every app boot (it is battery-backed). */
void far hc_upd_service(unsigned int now_ms, unsigned int rpm,
                        unsigned char trig_turning, unsigned char outputs_busy,
                        unsigned char page_stable);
unsigned char far hc_upd_active(void);
void          far hc_upd_boot_reset(void);

/* ---- published: the updater STATUS CHANNEL (OCH 478..493, big-endian U16s,
 * written only by an HC_UPDATER image - in a release image these offsets are
 * the retired V45/V49 forensics, which nothing writes). Every '!' command
 * answers TS_OK whatever it did (the project rules), so the host reads its
 * verdict here: it polls this 16-byte range ('O' off=478 len=16) between
 * stop-and-wait steps. A command was HANDLED once updSeq moved; it was
 * ACCEPTED when updLastRc is 0; a chunk LANDED once updState is READY again
 * and updReceived counts it. */
#define HC_UPD_OCH          478u
#define HC_UPD_OCH_STATE    478u  /* HC_UPD_ST_*                               */
#define HC_UPD_OCH_ERROR    480u  /* HCNV_ERR_* of the last failure            */
#define HC_UPD_OCH_RECV     482u  /* 4: bytes accepted into STAGING (u32 BE)   */
#define HC_UPD_OCH_LAST     486u  /* (updSeq << 8) | updLastRc                 */
#define HC_UPD_OCH_CMD      488u  /* (erase sector << 8) | last command letter */
#define HC_UPD_OCH_MARK     490u  /* HC_UPD_OCH_MARKER: this image has it      */
#define HC_UPD_OCH_PEND     492u  /* bytes queued, not yet programmed (flow)   */
#define HC_UPD_OCH_ERDONE   494u  /* STAGING sectors erased so far (0..4)      */
#define HC_UPD_OCH_LEN      18u
#define HC_UPD_OCH_MARKER   0x5550u   /* 'UP' */

/* ---- published ---- */
unsigned int  far hc_upd_state(void);      /* HC_UPD_ST_*                     */
unsigned int  far hc_upd_error(void);      /* HCNV_ERR_* of the last failure  */
unsigned long far hc_upd_received(void);   /* bytes accepted into STAGING     */
unsigned int  far hc_upd_last(void);       /* (seq << 8) | last command rc    */
unsigned int  far hc_upd_lastcmd(void);    /* (erase sector << 8) | letter    */
unsigned char far hc_upd_busy(void);       /* 1 while an erase/program pends  */

#endif /* HC_UPDATER */
#endif /* HCUPD711_H */
