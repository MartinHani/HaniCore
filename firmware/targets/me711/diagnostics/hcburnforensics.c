/* V45 retained reset/Burn forensics.  Every write is external battery-backed
 * SRAM; this module has no flash command, no delay and no output side effect. */
#include "hctarget.h"
#include "hcconfig.h"
#include "hcts.h"
#include "hcburnforensics.h"

/* V45's 64-byte transaction diary was built to diagnose its reset-based
 * writer. V47 retains the independent RESETDIAG/NMI evidence, while its live
 * qualification telemetry is owned by hcnvm. Preserve the interface and old
 * OCH offsets as explicit unavailable values, but do not spend 1.3 KiB of the
 * single executable sector maintaining a duplicate diary. */
#if defined(TGT_LIVE_BURN_HYBRID_QUAL)
void hc_bf_boot_early(unsigned int raw) { if (raw) return; }
void hc_bf_boot_stage(unsigned int stage) { if (stage) return; }
void hc_bf_hcts_init(unsigned int burns, unsigned int writes)
{ if (burns || writes) return; }
void hc_bf_b_received(void) { }
void hc_bf_request_accepted(void) { }
void hc_bf_reply_armed(void) { }
void hc_bf_response_selected(unsigned char code) { if (code) return; }
void hc_bf_response_tx_entered(void) { }
void hc_bf_response_completed(void) { }
void hc_bf_stage(unsigned char stage) { if (stage) return; }
void hc_bf_fail(unsigned char reason) { if (reason) return; }
void hc_bf_nvm_snapshot(unsigned char state, unsigned char phase,
                        unsigned char result, unsigned char cell,
                        unsigned int pos, unsigned int attempts,
                        unsigned char error, unsigned char writer_result,
                        unsigned int retries, unsigned int fail_word,
                        unsigned int fail_exp, unsigned int fail_got,
                        unsigned int fail_got2, unsigned int poll_min,
                        unsigned int poll_max)
{ if (state || phase || result || cell || pos || attempts || error
      || writer_result || retries || fail_word || fail_exp || fail_got
      || fail_got2 || poll_min || poll_max) return; }
unsigned int hc_bf_u8(unsigned int off) { if (off) return 0u; return 0u; }
unsigned int hc_bf_u16(unsigned int off) { if (off) return 0u; return 0u; }
unsigned int hc_bf_flags(void) { return 0u; }
unsigned int hc_bf_boot_epoch(void) { return 0u; }
unsigned int hc_bf_burn_epoch(void) { return 0u; }
unsigned int hc_bf_stage_current(void) { return 0u; }
unsigned int hc_bf_stage_last(void) { return 0u; }
unsigned int hc_bf_stage_fail(void) { return 0u; }

#else

#define BF_BASE (TGT_EXTRAM_BASE + TGT_RAM_NVM_FORENSICS)
#define BF ((unsigned char huge *)BF_BASE)

/* NVM_CB 0x00..0x13, NVW 0x20..0x3f, RAM probe 0x40..0x4d, diary
 * 0x50..0x65.  The V45 record starts at 0xa0 and ends at 0xdf. */
#if (TGT_RAM_NVM_FORENSICS != (TGT_RAM_NVM + 0xA0uL))
#error "V45 forensic record must remain at the audited 38:68A0 address"
#endif
#if ((TGT_RAM_NVM_FORENSICS + HCBF_LEN) > (TGT_RAM_NVM + TGT_RAM_NVM_LIMIT))
#error "V45 forensic record exceeds TGT_RAM_NVM"
#endif
#if (TGT_RAM_NVM_FORENSICS < (TGT_RAM_NVM + 0x66uL))
#error "V45 forensic record overlaps an allocated NVM/probe/diary block"
#endif

static unsigned int bf16(unsigned int off)
{
    return (unsigned int)(((unsigned int)BF[off] << 8) | BF[off + 1u]);
}

static void bf_set16(unsigned int off, unsigned int v)
{
    BF[off] = (unsigned char)(v >> 8);
    BF[off + 1u] = (unsigned char)v;
}

static unsigned long bf32(unsigned int off)
{
    return ((unsigned long)BF[off] << 24) | ((unsigned long)BF[off + 1u] << 16)
           | ((unsigned long)BF[off + 2u] << 8) | (unsigned long)BF[off + 3u];
}

static void bf_set32(unsigned int off, unsigned long v)
{
    BF[off] = (unsigned char)(v >> 24);
    BF[off + 1u] = (unsigned char)(v >> 16);
    BF[off + 2u] = (unsigned char)(v >> 8);
    BF[off + 3u] = (unsigned char)v;
}

static unsigned int bf_sum(void)
{
    unsigned int i;
    unsigned int s = 0u;
    for (i = 0u; i < HCBF_LEN; i++) {
        if (i != HCBF_CHECKSUM && i != (HCBF_CHECKSUM + 1u)) {
            s = (unsigned int)(s + BF[i]);
        }
    }
    return s;
}

static unsigned char bf_valid(void)
{
    return (unsigned char)(bf32(HCBF_MAGIC) == HCBF_MAGIC_VALUE
                           && BF[HCBF_VERSION] == HCBF_VERSION_VALUE
                           && BF[HCBF_LENGTH] == HCBF_LEN
                           && bf16(HCBF_CHECKSUM) == bf_sum());
}

/* The OCH compositor reads this record 40 ms apart and must never turn a
 * diagnostic refresh into 64 external-SRAM reads per displayed field.  Full
 * checksum validation is intentionally reserved for earliest startup; normal
 * runtime access needs only a completed header. */
static unsigned char bf_present(void)
{
    return (unsigned char)(bf32(HCBF_MAGIC) == HCBF_MAGIC_VALUE
                           && BF[HCBF_VERSION] == HCBF_VERSION_VALUE
                           && BF[HCBF_LENGTH] == HCBF_LEN);
}

/* Seal only at observation boundaries.  It is never called by the SRAM flash
 * writer: pre/post writer calls happen with interrupts restored. */
static void bf_seal(void)
{
    bf_set16(HCBF_SEQUENCE, (unsigned int)(bf16(HCBF_SEQUENCE) + 1u));
    bf_set16(HCBF_CHECKSUM, 0u);
    bf_set16(HCBF_CHECKSUM, bf_sum());
}

static void bf_fresh(void)
{
    unsigned int i;
    for (i = 0u; i < HCBF_LEN; i++) {
        BF[i] = 0u;
    }
    bf_set32(HCBF_MAGIC, HCBF_MAGIC_VALUE);
    BF[HCBF_VERSION] = HCBF_VERSION_VALUE;
    BF[HCBF_LENGTH] = HCBF_LEN;
    BF[HCBF_FAIL_WORD] = 0xFFu;
    BF[HCBF_FAIL_WORD + 1u] = 0xFFu;
    bf_seal();
}

static void bf_flags(unsigned int set, unsigned int clear)
{
    bf_set16(HCBF_FLAGS, (unsigned int)((bf16(HCBF_FLAGS) | set) & ~clear));
}

void hc_bf_boot_early(unsigned int raw_reset)
{
    unsigned int flags;
    if (!bf_present()) {
        bf_fresh();
    } else if (!bf_valid()) {
        /* A reset can interrupt the checksum seal itself.  The preceding
         * fields are still the only retained Burn evidence, so preserve them,
         * flag that the seal was repaired, and reseal after the boot snapshot
         * rather than erasing the very evidence V45 was built to keep. */
        bf_flags(HCBF_F_CHECKSUM_RECOVERED, 0u);
    }
    flags = bf16(HCBF_FLAGS);
    if ((flags & HCBF_F_ACTIVE) != 0u) {
        bf_flags((unsigned int)(HCBF_F_BOOT_DURING_BURN
                                 | HCBF_F_REPLY_PENDING_AT_BOOT), 0u);
    }
    bf_set16(HCBF_BOOT_EPOCH, (unsigned int)(bf16(HCBF_BOOT_EPOCH) + 1u));
    bf_set16(HCBF_RESET_RAW, raw_reset);
    BF[HCBF_BOOT_STAGE] = (unsigned char)hc_rst_get(RST_STAGE);
    BF[HCBF_PREV_STAGE] = (unsigned char)hc_rst_get(RST_PREV_STAGE);
    BF[HCBF_PREV_TRAP] = (unsigned char)hc_rst_get(RST_PREV_TRAP);
    bf_set16(HCBF_PREV_TRAP_MS, hc_rst_get(RST_PREV_TRAP_MS));
    bf_set16(HCBF_PREV_UPTIME, hc_rst_get(RST_PREV_MS));
    bf_set16(HCBF_PREV_LOOP, hc_rst_get(RST_PREV_LOOP));
    bf_set16(HCBF_PREV_WDT, hc_rst_get(RST_PREV_WDT_COUNT));
    bf_seal();
}

void hc_bf_boot_stage(unsigned int stage)
{
    if (bf_present()) {
        BF[HCBF_BOOT_STAGE] = (unsigned char)stage;
        bf_seal();
    }
}

void hc_bf_hcts_init(unsigned int burns, unsigned int writes)
{
    if (!bf_present()) return;
    bf_set16(HCBF_HCTS_INITS, (unsigned int)(bf16(HCBF_HCTS_INITS) + 1u));
    bf_set16(HCBF_HCTS_BOOT, bf16(HCBF_BOOT_EPOCH));
    BF[HCBF_BURNS_PRE] = (unsigned char)burns;
    BF[HCBF_WRITES_PRE] = (unsigned char)writes;
    bf_seal();
}

void hc_bf_b_received(void)
{
    if (!bf_present()) bf_fresh();
    bf_set16(HCBF_BURN_EPOCH, (unsigned int)(bf16(HCBF_BURN_EPOCH) + 1u));
    bf_set16(HCBF_FLAGS, (unsigned int)(HCBF_F_ACTIVE | HCBF_F_B_RECEIVED));
    BF[HCBF_STAGE] = HCBF_ST_B_PARSED;
    BF[HCBF_LAST_STAGE] = HCBF_ST_B_PARSED;
    BF[HCBF_FAIL_STAGE] = HCBF_ST_IDLE;
    BF[HCBF_FAILURE] = 0u;
    bf_seal();
}

void hc_bf_stage(unsigned char stage)
{
    if (!bf_present()) return;
    BF[HCBF_STAGE] = stage;
    if (stage > BF[HCBF_LAST_STAGE]) BF[HCBF_LAST_STAGE] = stage;
    /* Stage bytes deliberately do not reseal the whole 64-byte record.  The
     * adjacent boundary snapshot seals it outside the writer; if reset lands
     * between them boot records CHECKSUM_RECOVERED and preserves these bytes.
     * This avoids adding a 64-byte SRAM checksum pass for every programmed
     * word in an eight-word writer invocation. */
}

void hc_bf_request_accepted(void)
{
    bf_flags((unsigned int)(HCBF_F_REQUEST_OK | HCBF_F_PERSISTING), 0u);
    hc_bf_stage(HCBF_ST_REQUEST_OK);
}

void hc_bf_reply_armed(void)
{
    bf_flags(HCBF_F_REPLY_ARMED, 0u);
    bf_seal();
}

void hc_bf_response_selected(unsigned char code)
{
    if (!bf_present()) return;
    /* HCBF_F_TS_BAD meant "the Burn answered TS_BAD_CMD", and from V60 a
       refused Burn answers TS_REFUSED == TS_OK instead, because TunerStudio
       ends the session on any code with bit 7 set (hcts.h). So the RESPONSE
       CODE no longer distinguishes a refusal, and this diary must not pretend
       it does: the reason is hc_bf_fail()'s own byte, which nvm_fail() records
       immediately before it answers. The 0x83 arm stays so a frozen V40..V59
       trace still reads the way it always did. */
    if (code == TS_BAD_CMD) bf_flags(HCBF_F_TS_BAD, HCBF_F_TS_OK);
    else if (code == TS_OK) bf_flags(HCBF_F_TS_OK, HCBF_F_TS_BAD);
    bf_seal();
}

void hc_bf_response_tx_entered(void)
{
    if (!bf_present()) return;
    bf_flags(HCBF_F_TX_ENTERED, 0u);
    if (BF[HCBF_FAILURE] == 0u) hc_bf_stage(HCBF_ST_TX_ENTERED);
    else bf_seal();
}

void hc_bf_response_completed(void)
{
    if (!bf_present()) return;
    bf_flags(HCBF_F_TX_COMPLETE, HCBF_F_ACTIVE);
    if (BF[HCBF_FAILURE] == 0u) hc_bf_stage(HCBF_ST_TX_COMPLETE);
    else bf_seal();
}

void hc_bf_fail(unsigned char reason)
{
    if (!bf_present()) return;
    BF[HCBF_FAIL_STAGE] = BF[HCBF_LAST_STAGE];
    BF[HCBF_FAILURE] = reason;
    bf_seal();
}

void hc_bf_nvm_snapshot(unsigned char state, unsigned char phase,
                        unsigned char result, unsigned char cell,
                        unsigned int pos, unsigned int attempts,
                        unsigned char error, unsigned char writer_result,
                        unsigned int retries, unsigned int fail_word,
                        unsigned int fail_exp, unsigned int fail_got,
                        unsigned int fail_got2, unsigned int poll_min,
                        unsigned int poll_max)
{
    if (!bf_present()) return;
    BF[HCBF_NVM_STATE] = state; BF[HCBF_NVM_PHASE] = phase;
    BF[HCBF_NVM_RESULT] = result; BF[HCBF_NVM_CELL] = cell;
    bf_set16(HCBF_NVM_POS, pos); bf_set16(HCBF_NVM_ATTEMPTS, attempts);
    BF[HCBF_NVM_ERROR] = error; BF[HCBF_WRITER_RESULT] = writer_result;
    bf_set16(HCBF_NVM_RETRIES, retries); bf_set16(HCBF_FAIL_WORD, fail_word);
    bf_set16(HCBF_FAIL_EXP, fail_exp); bf_set16(HCBF_FAIL_GOT, fail_got);
    bf_set16(HCBF_FAIL_GOT2, fail_got2); bf_set16(HCBF_POLL_MIN, poll_min);
    bf_set16(HCBF_POLL_MAX, poll_max);
    bf_seal();
}

unsigned int hc_bf_u8(unsigned int off) { return bf_present() && off < HCBF_LEN ? (unsigned int)BF[off] : 0u; }
unsigned int hc_bf_u16(unsigned int off) { return bf_present() && off + 1u < HCBF_LEN ? bf16(off) : 0u; }
unsigned int hc_bf_flags(void) { return hc_bf_u16(HCBF_FLAGS); }
unsigned int hc_bf_boot_epoch(void) { return hc_bf_u16(HCBF_BOOT_EPOCH); }
unsigned int hc_bf_burn_epoch(void) { return hc_bf_u16(HCBF_BURN_EPOCH); }
unsigned int hc_bf_stage_current(void) { return hc_bf_u8(HCBF_STAGE); }
unsigned int hc_bf_stage_last(void) { return hc_bf_u8(HCBF_LAST_STAGE); }
unsigned int hc_bf_stage_fail(void) { return hc_bf_u8(HCBF_FAIL_STAGE); }
#endif /* TGT_LIVE_BURN_HYBRID_QUAL */
