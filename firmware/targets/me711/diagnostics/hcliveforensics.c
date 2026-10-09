/* hcliveforensics.c - V49 retained, first-event live-Burn evidence. */
#include <reg167.h>
#include "hctarget.h"
#include "hcliveforensics.h"

/* ------------------------------------------------------------------------
 * TGT_BURN_DIAGNOSTICS - see hcasicdump.c for why this switch exists and
 * what an image without it gives up. 2130 bytes. Every function here is a
 * recorder; none of them decides anything, and hc_lf_active() returning 0
 * is exactly what "no forensic capture is running" already meant.
 * ---------------------------------------------------------------------- */
#if !defined(TGT_BURN_DIAGNOSTICS)

/* Generated from hcliveforensics.h. Recorders only. hc_lf_active()
   returning 0 is exactly what 'no capture is running' already meant. */

unsigned char hc_lf_fast_active;

void hc_lf_boot_early(unsigned int raw_reset, unsigned int boot_id)
{ if (raw_reset || boot_id) return; }
void hc_lf_arm(unsigned int request_ms, unsigned int windows, unsigned int entries, unsigned int successes, unsigned int failures)
{ if (request_ms || windows || entries || successes || failures) return; }
unsigned char hc_lf_active(void) { return 0u; }
void hc_lf_stage_done(unsigned int ms)
{ if (ms) return; }
void hc_lf_admit(unsigned int ms, unsigned int t7, unsigned int pos, unsigned int admission, unsigned int sscon, unsigned int pecc0, unsigned int pecc4, unsigned int port, unsigned int t8rel, unsigned int t8, unsigned int t0, unsigned int cc7)
{ if (ms || t7 || pos || admission || sscon || pecc0 || pecc4 || port || t8rel || t8 || t0 || cc7) return; }
void hc_lf_writer_return(unsigned int t7, unsigned int elapsed)
{ if (t7 || elapsed) return; }
void hc_lf_ir_after(unsigned int dropped, unsigned int pos)
{ if (dropped || pos) return; }
void hc_lf_restore(unsigned int restore_t7, unsigned int pos, unsigned int save_cc7, unsigned int save_t8, unsigned int save_tx, unsigned int save_rx, unsigned int save_err, unsigned int dur_cc7, unsigned int dur_t8, unsigned int dur_tx, unsigned int dur_rx, unsigned int dur_err, unsigned int writer_result)
{ if (restore_t7 || pos || save_cc7 || save_t8 || save_tx || save_rx || save_err || dur_cc7 || dur_t8 || dur_tx || dur_rx || dur_err || writer_result) return; }
void hc_lf_asic_launch(unsigned int ms, unsigned int t7, unsigned int tx1, unsigned int tx2, unsigned int tx3, unsigned int state, unsigned int run_tx)
{ if (ms || t7 || tx1 || tx2 || tx3 || state || run_tx) return; }
void hc_lf_asic_complete(unsigned int ms, unsigned int t7, unsigned int rx0, unsigned int rx1, unsigned int rx2, unsigned int rx3, unsigned int calc, unsigned int recv, unsigned int outcome, unsigned int state, unsigned int pec0, unsigned int pec4, unsigned int xfer_ms)
{ if (ms || t7 || rx0 || rx1 || rx2 || rx3 || calc || recv || outcome || state || pec0 || pec4 || xfer_ms) return; }
void hc_lf_um_before(unsigned int acc_hi, unsigned int acc_lo, unsigned int seed, unsigned int answer, unsigned int phase, unsigned int health, unsigned int expect, unsigned int answers, unsigned int input_word1)
{ if (acc_hi || acc_lo || seed || answer || phase || health || expect || answers || input_word1) return; }
void hc_lf_um_after(unsigned int acc_hi, unsigned int acc_lo, unsigned int seed, unsigned int answer)
{ if (acc_hi || acc_lo || seed || answer) return; }
void hc_lf_recover(unsigned int state, unsigned int result, unsigned int pos, unsigned int raw_reset)
{ if (state || result || pos || raw_reset) return; }
void hc_lf_durable(unsigned int ms, unsigned int pos)
{ if (ms || pos) return; }
unsigned char hc_lf_export_byte(unsigned int offset)
{
    if (offset) return 0u;
    return 0u;
}

#else

#define LF_MAGIC0_VALUE 0x4843u
#define LF_MAGIC1_VALUE 0x4C46u
#define LF_VERSION_VALUE 0x0049u
#define LF_NMI_START_VALUE 0x4E31u
#define LF_NMI_DONE_VALUE  0x4E32u

extern unsigned char hc_umkom_phase;
extern unsigned char hc_umkom_health;
extern unsigned char hc_umkom_expect;
unsigned char hc_lf_fast_active;

static unsigned char lf_valid(void)
{
    return (unsigned char)(HC_LF_WORD(LF_MAGIC0) == LF_MAGIC0_VALUE
        && HC_LF_WORD(LF_MAGIC1) == LF_MAGIC1_VALUE
        && HC_LF_WORD(LF_VERSION) == LF_VERSION_VALUE
        && HC_LF_WORD(LF_LENGTH) == HC_LF_BYTES);
}

static unsigned int lf_integrity(void)
{
    unsigned int i;
    unsigned int v = 0x49A5u;
    for (i = 0u; i < HC_LF_WORDS; i++) {
        if (i != LF_INTEGRITY) {
            v = (unsigned int)((v << 1) | (v >> 15));
            v ^= HC_LF_WORD(i);
        }
    }
    return v;
}

static void lf_seal(void)
{
    HC_LF_WORD(LF_INTEGRITY) = 0u;
    HC_LF_WORD(LF_INTEGRITY) = lf_integrity();
}

static void lf_init(void)
{
    unsigned int i;
    for (i = 0u; i < HC_LF_WORDS; i++) HC_LF_WORD(i) = 0u;
    HC_LF_WORD(LF_MAGIC0) = LF_MAGIC0_VALUE;
    HC_LF_WORD(LF_MAGIC1) = LF_MAGIC1_VALUE;
    HC_LF_WORD(LF_VERSION) = LF_VERSION_VALUE;
    HC_LF_WORD(LF_LENGTH) = HC_LF_BYTES;
    HC_LF_WORD(LF_RELEASE_ID) = TGT_RELEASE_ID;
    HC_LF_WORD(LF_FLAGS) = LF_F_VALID;
}

void hc_lf_boot_early(unsigned int raw_reset, unsigned int boot_id)
{
    unsigned int f;
    if (!lf_valid() || (raw_reset & TGT_RESET_PONR) != 0u) lf_init();
    f = HC_LF_WORD(LF_FLAGS);
    if ((f & (LF_F_ARMED | LF_F_FROZEN)) == 0u)
        HC_LF_WORD(LF_BOOT_ID) = boot_id;
    /* A first boot after an NMI must add the associated hardware reset flags
       and seal even though assembly froze the record.  LF_F_BOOT_SEALED makes
       that one-time step idempotent if another reset lands before NVM boot
       recovery.  All later warm resets preserve the record byte for byte. */
    if ((f & LF_F_FROZEN) != 0u) {
        if ((f & LF_F_NMI_STARTED) != 0u
                && (f & LF_F_BOOT_SEALED) == 0u) {
            HC_LF_WORD(LF_RESET_RAW) = raw_reset;
            HC_LF_WORD(LF_FLAGS) = (unsigned int)(f | LF_F_BOOT_SEALED);
            lf_seal();
        }
        hc_lf_fast_active = 0u;
        return;
    }
    HC_LF_WORD(LF_RESET_RAW) = raw_reset;
    if ((f & (LF_F_NMI_STARTED | LF_F_DURABLE | LF_F_RECOVERED)) != 0u) {
        HC_LF_WORD(LF_FLAGS) = (unsigned int)(f | LF_F_FROZEN);
        lf_seal();
    }
    hc_lf_fast_active = (unsigned char)(((HC_LF_WORD(LF_FLAGS) & LF_F_ARMED) != 0u
        && (HC_LF_WORD(LF_FLAGS) & LF_F_FROZEN) == 0u) ? 1u : 0u);
    if (hc_lf_fast_active != 0u) {
        /* Resuming an armed epoch across a reset. T7 and hc_tick_ms both
           restarted, so the retained cadence anchors describe the previous
           run; leaving them would post one enormous first gap. */
        HC_LF_WORD(LF_TICK_LAST_T7) = (unsigned int)T7;
        HC_LF_WORD(LF_ASIC_LAST_LAUNCH_MS) = 0u;
    }
}

unsigned char hc_lf_active(void)
{
    unsigned int f;
    if (!lf_valid()) return 0u;
    f = HC_LF_WORD(LF_FLAGS);
    return (unsigned char)((f & LF_F_ARMED) != 0u
                           && (f & LF_F_FROZEN) == 0u);
}

void hc_lf_arm(unsigned int request_ms,
               unsigned int windows, unsigned int entries,
               unsigned int successes, unsigned int failures)
{
    unsigned int f;
    unsigned int i;
    if (!lf_valid()) lf_init();
    f = HC_LF_WORD(LF_FLAGS);
    if ((f & (LF_F_ARMED | LF_F_FROZEN)) != 0u) return;
    for (i = 16u; i < HC_LF_WORDS; i++) HC_LF_WORD(i) = 0u;
    HC_LF_WORD(LF_EPOCH) = (unsigned int)(HC_LF_WORD(LF_EPOCH) + 1u);
    HC_LF_WORD(LF_REQUEST_MS) = request_ms;
    HC_LF_WORD(LF_BASE_WINDOWS) = windows;
    HC_LF_WORD(LF_BASE_ENTRIES) = entries;
    HC_LF_WORD(LF_BASE_SUCCESS) = successes;
    HC_LF_WORD(LF_BASE_FAIL) = failures;
    HC_LF_WORD(LF_RELEASE_ID) = TGT_RELEASE_ID;
    HC_LF_WORD(LF_INTEGRITY) = 0u;
    HC_LF_WORD(LF_TICK_LAST_T7) = (unsigned int)T7;
    HC_LF_WORD(LF_FLAGS) = (unsigned int)(LF_F_VALID | LF_F_ARMED);
    hc_lf_fast_active = 1u;
}

void hc_lf_stage_done(unsigned int ms)
{
    if (!hc_lf_active()) return;
    HC_LF_WORD(LF_STAGE_MS) = ms;
    HC_LF_WORD(LF_FLAGS) |= LF_F_STAGED;
}

void hc_lf_admit(unsigned int ms, unsigned int t7, unsigned int pos,
                 unsigned int admission, unsigned int sscon,
                 unsigned int pecc0, unsigned int pecc4, unsigned int port,
                 unsigned int t8rel, unsigned int t8,
                 unsigned int t0, unsigned int cc7)
{
    if (!hc_lf_active()) return;
    if (HC_LF_WORD(LF_FIRST_WR_MS) == 0u) HC_LF_WORD(LF_FIRST_WR_MS) = ms;
    HC_LF_WORD(LF_ADMIT_MS) = ms;
    HC_LF_WORD(LF_ADMIT_T7) = t7;
    HC_LF_WORD(LF_CURSOR) = pos;
    HC_LF_WORD(LF_ADMISSION) = admission;
    HC_LF_WORD(LF_ENTRY_SSCON) = sscon;
    HC_LF_WORD(LF_ENTRY_PECC0) = pecc0;
    HC_LF_WORD(LF_ENTRY_PECC4) = pecc4;
    HC_LF_WORD(LF_ENTRY_PORT) = port;
    HC_LF_WORD(LF_ENTRY_T8REL) = t8rel;
    HC_LF_WORD(LF_ENTRY_T8) = t8;
    HC_LF_WORD(LF_ENTRY_T0) = t0;
    HC_LF_WORD(LF_ENTRY_CC7) = cc7;
    HC_LF_WORD(LF_WINDOW_SEQ)++;
}

/* V50.  `dropped` is the set of sources whose xxIR was pending before the
   restore and gone after it - i.e. destroyed by the restore.  On a correct
   build this stays 0 for the whole Burn; on V48/V49 it would have been 3.
   First position is kept the same way LF_FIRST_LOST_POS is, so a single event
   can be located in the transaction. */
void hc_lf_ir_after(unsigned int dropped, unsigned int pos)
{
    if (!hc_lf_active()) return;
    if (dropped == 0u) return;
    HC_LF_WORD(LF_IR_DROPPED) |= dropped;
    if (HC_LF_WORD(LF_IR_DROPPED_POS) == 0u) {
        HC_LF_WORD(LF_IR_DROPPED_POS) = pos;
        HC_LF_WORD(LF_FIRST_ANOMALY) = 2u;
    }
}

void hc_lf_writer_return(unsigned int t7, unsigned int elapsed)
{
    if (!hc_lf_active()) return;
    HC_LF_WORD(LF_WR_RETURN)++;
    HC_LF_WORD(LF_RETURN_T7) = t7;
    HC_LF_WORD(LF_LAST_WINDOW_T7) = elapsed;
    if (elapsed > HC_LF_WORD(LF_MAX_WINDOW_T7))
        HC_LF_WORD(LF_MAX_WINDOW_T7) = elapsed;
}

static unsigned int lf_new_ir(unsigned int saved, unsigned int during,
                              unsigned int mask_value)
{
    return (unsigned int)(((saved & 0x0080u) == 0u
                           && (during & 0x0080u) != 0u) ? mask_value : 0u);
}

void hc_lf_restore(unsigned int restore_t7, unsigned int pos,
                   unsigned int save_cc7, unsigned int save_t8,
                   unsigned int save_tx, unsigned int save_rx,
                   unsigned int save_err, unsigned int dur_cc7,
                   unsigned int dur_t8, unsigned int dur_tx,
                   unsigned int dur_rx, unsigned int dur_err,
                   unsigned int writer_result)
{
    unsigned int lost;
    if (!hc_lf_active()) return;
    HC_LF_WORD(LF_RESTORE_T7) = restore_t7;
    HC_LF_WORD(LF_SAVE_CC7IC) = save_cc7;
    HC_LF_WORD(LF_SAVE_T8IC) = save_t8;
    HC_LF_WORD(LF_SAVE_SSCTIC) = save_tx;
    HC_LF_WORD(LF_SAVE_SSCRIC) = save_rx;
    HC_LF_WORD(LF_SAVE_SSCEIC) = save_err;
    HC_LF_WORD(LF_DUR_CC7IC) = dur_cc7;
    HC_LF_WORD(LF_DUR_T8IC) = dur_t8;
    HC_LF_WORD(LF_DUR_SSCTIC) = dur_tx;
    HC_LF_WORD(LF_DUR_SSCRIC) = dur_rx;
    HC_LF_WORD(LF_DUR_SSCEIC) = dur_err;
    lost = lf_new_ir(save_cc7, dur_cc7, 0x0001u)
         | lf_new_ir(save_t8, dur_t8, 0x0002u)
         | lf_new_ir(save_tx, dur_tx, 0x0004u)
         | lf_new_ir(save_rx, dur_rx, 0x0008u)
         | lf_new_ir(save_err, dur_err, 0x0010u);
    HC_LF_WORD(LF_LOST_LAST) = lost;
    /* LF_VERIFY_SEQ is C's own bookkeeping and is CORROBORATION, never the
       discriminator: a stamp that only exists after the CALLS returns cannot
       describe a reset that happened before it did. The writer-owned test is
       LF_VERIFY_T7 against LF_COMMAND_T7 - see hc_nvm_payload(). */
    HC_LF_WORD(LF_VERIFY_SEQ) = (writer_result == 0u) ? pos : 0u;
    HC_LF_WORD(LF_WRITER_RESULT) = writer_result;
    HC_LF_WORD(LF_LOST_OR) |= lost;
    if (lost != 0u && HC_LF_WORD(LF_FIRST_LOST_POS) == 0u) {
        HC_LF_WORD(LF_FIRST_LOST_POS) = pos;
        HC_LF_WORD(LF_FIRST_LOST_T7) = restore_t7;
        HC_LF_WORD(LF_FIRST_ANOMALY) = 1u;
    }
    HC_LF_WORD(LF_BOUNDARY_MARK)++;
}

void hc_lf_asic_launch(unsigned int ms, unsigned int t7,
                       unsigned int tx1, unsigned int tx2, unsigned int tx3,
                       unsigned int state, unsigned int run_tx)
{
    unsigned int b, seq, gap;
    if (!hc_lf_active()) return;
    seq = (unsigned int)(HC_LF_WORD(LF_ASIC_SEQ) + 1u);
    HC_LF_WORD(LF_ASIC_SEQ) = seq;
    b = (unsigned int)(LF_ASIC_BASE
        + ((seq & 1u) != 0u ? LF_ASIC_WORDS : 0u));
    /* NO BASELINE, NO GAP. hc_lf_arm() zeroes this word and a boot that
       resumes an armed record clears it again, so the first launch of an
       epoch has nothing to subtract from. Measuring it anyway made the very
       first exchange report a gap of the whole uptime and left that number
       standing as LF_ASIC_MAX_GAP_MS - destroying the one field the
       interpretation table reads as cadence disruption. Zero means "no
       previous launch"; a real launch at tick 0 is recorded as 1. */
    gap = HC_LF_WORD(LF_ASIC_LAST_LAUNCH_MS);
    if (gap != 0u) {
        gap = (unsigned int)(ms - gap);
        HC_LF_WORD(LF_ASIC_LAST_GAP_MS) = gap;
        if (gap > HC_LF_WORD(LF_ASIC_MAX_GAP_MS))
            HC_LF_WORD(LF_ASIC_MAX_GAP_MS) = gap;
    }
    HC_LF_WORD(LF_ASIC_LAST_LAUNCH_MS) = (unsigned int)((ms != 0u) ? ms : 1u);
    HC_LF_WORD(LF_ASIC_SLOT) = b;
    HC_LF_WORD(b + 0u) = 0u;
    HC_LF_WORD(b + 1u) = seq;
    HC_LF_WORD(b + 2u) = ms;
    HC_LF_WORD(b + 3u) = t7;
    HC_LF_WORD(b + 6u) = tx1;
    HC_LF_WORD(b + 7u) = tx2;
    HC_LF_WORD(b + 8u) = tx3;
    HC_LF_WORD(b + 15u) = state;
    HC_LF_WORD(b + 16u) = (unsigned int)(((unsigned int)hc_umkom_phase << 12)
        | ((unsigned int)(hc_umkom_health & 0x0Fu) << 8)
        | (unsigned int)hc_umkom_expect);
    HC_LF_WORD(b + 17u) = run_tx;
    HC_LF_WORD(b + 0u) = 0xA100u;
}

void hc_lf_asic_complete(unsigned int ms, unsigned int t7,
                         unsigned int rx0, unsigned int rx1,
                         unsigned int rx2, unsigned int rx3,
                         unsigned int calc, unsigned int recv,
                         unsigned int outcome, unsigned int state,
                         unsigned int pec0, unsigned int pec4,
                         unsigned int xfer_ms)
{
    unsigned int b;
    if (!hc_lf_active()) return;
    b = HC_LF_WORD(LF_ASIC_SLOT);
    if (b != LF_ASIC_BASE && b != (LF_ASIC_BASE + LF_ASIC_WORDS)) return;
    HC_LF_WORD(b + 4u) = ms;
    HC_LF_WORD(b + 5u) = t7;
    HC_LF_WORD(b + 9u) = rx0;
    HC_LF_WORD(b + 10u) = rx1;
    HC_LF_WORD(b + 11u) = rx2;
    HC_LF_WORD(b + 12u) = rx3;
    HC_LF_WORD(b + 13u) = calc;
    HC_LF_WORD(b + 14u) = recv;
    HC_LF_WORD(b + 15u) = (unsigned int)((state << 8) | (outcome & 0xFFu));
    HC_LF_WORD(b + 16u) = (unsigned int)(((unsigned int)hc_umkom_phase << 12)
        | ((unsigned int)(hc_umkom_health & 0x0Fu) << 8)
        | (unsigned int)hc_umkom_expect);
    HC_LF_WORD(b + 18u) = (unsigned int)((pec0 << 8) | (pec4 & 0xFFu));
    HC_LF_WORD(b + 19u) = xfer_ms;
    HC_LF_WORD(LF_ASIC_LAST_DONE_MS) = ms;
    HC_LF_WORD(b + 0u) = 0xA200u;
    if (outcome != 0u && HC_LF_WORD(LF_FIRST_ANOMALY) == 0u)
        HC_LF_WORD(LF_FIRST_ANOMALY) = (unsigned int)(0x0100u | outcome);
}

void hc_lf_um_before(unsigned int acc_hi, unsigned int acc_lo,
                     unsigned int seed, unsigned int answer,
                     unsigned int phase, unsigned int health,
                     unsigned int expect, unsigned int answers,
                     unsigned int input_word1)
{
    if (!hc_lf_active()) return;
    /* Invalidate the after-state first. An NMI during the responder must be
       reported as incomplete, never compared with stale preceding values. */
    HC_LF_WORD(LF_UM_BASE + 10u) = 0u;
    HC_LF_WORD(LF_UM_BASE + 0u) = acc_hi;
    HC_LF_WORD(LF_UM_BASE + 1u) = acc_lo;
    HC_LF_WORD(LF_UM_BASE + 2u) = seed;
    HC_LF_WORD(LF_UM_BASE + 3u) = answer;
    HC_LF_WORD(LF_UM_BASE + 4u) = (unsigned int)((phase << 8) | health);
    HC_LF_WORD(LF_UM_BASE + 5u) = expect;
    HC_LF_WORD(LF_UM_BASE + 6u) = answers;
    HC_LF_WORD(LF_UM_BASE + 7u) = input_word1;
}

void hc_lf_um_after(unsigned int acc_hi, unsigned int acc_lo,
                    unsigned int seed, unsigned int answer)
{
    if (!hc_lf_active()) return;
    HC_LF_WORD(LF_UM_BASE + 8u) = acc_hi;
    HC_LF_WORD(LF_UM_BASE + 9u) = acc_lo;
    HC_LF_WORD(LF_UM_BASE + 11u) = answer;
    /* Completeness marker last; seed itself occupies the low byte. */
    HC_LF_WORD(LF_UM_BASE + 10u) = (unsigned int)(0xA500u | (seed & 0x00FFu));
}

void hc_lf_recover(unsigned int state, unsigned int result,
                   unsigned int pos, unsigned int raw_reset)
{
    if (!lf_valid()) return;
    if ((HC_LF_WORD(LF_FLAGS) & LF_F_ARMED) == 0u) return;
    /* A completed or partial NMI snapshot is frozen at the first boundary.
       hc_nvm_boot() runs later and must not rewrite it as generic recovery. */
    if ((HC_LF_WORD(LF_FLAGS) & LF_F_FROZEN) != 0u) return;
    HC_LF_WORD(LF_RECOVERY) = (unsigned int)((state << 8) | (result & 0xFFu));
    HC_LF_WORD(LF_CURSOR) = pos;
    HC_LF_WORD(LF_RESET_RAW) = raw_reset;
    HC_LF_WORD(LF_FLAGS) |= (LF_F_RECOVERED | LF_F_FROZEN);
    hc_lf_fast_active = 0u;
    lf_seal();
}

void hc_lf_durable(unsigned int ms, unsigned int pos)
{
    if (!hc_lf_active()) return;
    HC_LF_WORD(LF_RECOVERY) = ms;
    HC_LF_WORD(LF_CURSOR) = pos;
    HC_LF_WORD(LF_FLAGS) |= (LF_F_DURABLE | LF_F_FROZEN);
    hc_lf_fast_active = 0u;
    lf_seal();
}

unsigned char hc_lf_export_byte(unsigned int offset)
{
    unsigned int w;
    if (offset >= HC_LF_BYTES || !lf_valid()) return 0u;
    w = HC_LF_WORD(offset >> 1);
    return (unsigned char)(((offset & 1u) == 0u) ? (w >> 8) : w);
}

#endif /* !TGT_BURN_DIAGNOSTICS */
