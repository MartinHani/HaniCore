/* V45 one-Burn reset forensic record.  This is deliberately target-local:
 * it observes a Bosch ME7.1.1 transaction and must not alter the shared
 * persistence protocol. */
#ifndef HCBURNFORENSICS_H
#define HCBURNFORENSICS_H

#define HCBF_LEN 64u

/* Offsets in the retained 38:68A0 record.  Multi-byte fields are big-endian.
 * The compact layout intentionally keeps the detailed ASIC/reset context in
 * the existing RESETDIAG record (published separately through OCH). */
#define HCBF_MAGIC       0u
#define HCBF_VERSION     4u
#define HCBF_LENGTH      5u
#define HCBF_SEQUENCE    6u
#define HCBF_CHECKSUM    8u
#define HCBF_FLAGS      10u
#define HCBF_BOOT_EPOCH 12u
#define HCBF_BURN_EPOCH 14u
#define HCBF_HCTS_INITS 16u
#define HCBF_HCTS_BOOT  18u
#define HCBF_BURNS_PRE  20u
#define HCBF_WRITES_PRE 21u
#define HCBF_RESET_RAW  22u
#define HCBF_BOOT_STAGE 24u
#define HCBF_PREV_STAGE 25u
#define HCBF_PREV_TRAP  26u
#define HCBF_RESERVED   27u
#define HCBF_PREV_TRAP_MS 28u
#define HCBF_PREV_UPTIME  30u
#define HCBF_PREV_LOOP    32u
#define HCBF_PREV_WDT     34u
#define HCBF_NVM_STATE    36u
#define HCBF_NVM_PHASE    37u
#define HCBF_NVM_RESULT   38u
#define HCBF_NVM_CELL     39u
#define HCBF_NVM_POS      40u
#define HCBF_NVM_ATTEMPTS 42u
#define HCBF_NVM_ERROR    44u
#define HCBF_WRITER_RESULT 45u
#define HCBF_NVM_RETRIES  46u
#define HCBF_FAIL_WORD    48u
#define HCBF_FAIL_EXP     50u
#define HCBF_FAIL_GOT     52u
#define HCBF_FAIL_GOT2    54u
#define HCBF_POLL_MIN     56u
#define HCBF_POLL_MAX     58u
#define HCBF_STAGE        60u
#define HCBF_LAST_STAGE   61u
#define HCBF_FAIL_STAGE   62u
#define HCBF_FAILURE      63u

#define HCBF_MAGIC_VALUE 0x48434246uL /* HCBF */
#define HCBF_VERSION_VALUE 1u

/* Flags are facts, not inferred outcomes. */
#define HCBF_F_ACTIVE       0x0001u
#define HCBF_F_B_RECEIVED   0x0002u
#define HCBF_F_REQUEST_OK   0x0004u
#define HCBF_F_REPLY_ARMED  0x0008u
#define HCBF_F_PERSISTING   0x0010u
#define HCBF_F_TS_OK        0x0020u
#define HCBF_F_TS_BAD       0x0040u
#define HCBF_F_TX_ENTERED   0x0080u
#define HCBF_F_TX_COMPLETE  0x0100u
#define HCBF_F_BOOT_DURING_BURN 0x0200u
#define HCBF_F_REPLY_PENDING_AT_BOOT 0x0400u
#define HCBF_F_CHECKSUM_RECOVERED    0x0800u /* reset interrupted a record update */

/* V45 trace states.  They name real boundaries, not writer internals. */
#define HCBF_ST_IDLE          0u
#define HCBF_ST_B_PARSED      1u
#define HCBF_ST_REQUEST_OK    2u
#define HCBF_ST_SNAPSHOT      3u
#define HCBF_ST_TARGET        4u
#define HCBF_ST_COMMITTING    5u
#define HCBF_ST_PREPARED      6u
#define HCBF_ST_WRITER_ENTER  7u
#define HCBF_ST_WRITER_RETURN 8u
#define HCBF_ST_PROGRESS      9u
#define HCBF_ST_RETRY        10u
#define HCBF_ST_DONE         11u
#define HCBF_ST_OK_PENDING   12u
#define HCBF_ST_TX_ENTERED   13u
#define HCBF_ST_TX_COMPLETE  14u

void hc_bf_boot_early(unsigned int raw_reset);
void hc_bf_boot_stage(unsigned int stage);
void hc_bf_hcts_init(unsigned int burns, unsigned int writes);
void hc_bf_b_received(void);
void hc_bf_request_accepted(void);
void hc_bf_reply_armed(void);
void hc_bf_response_selected(unsigned char code);
void hc_bf_response_tx_entered(void);
void hc_bf_response_completed(void);
void hc_bf_stage(unsigned char stage);
void hc_bf_fail(unsigned char reason);
void hc_bf_nvm_snapshot(unsigned char state, unsigned char phase,
                        unsigned char result, unsigned char cell,
                        unsigned int pos, unsigned int attempts,
                        unsigned char error, unsigned char writer_result,
                        unsigned int retries, unsigned int fail_word,
                        unsigned int fail_exp, unsigned int fail_got,
                        unsigned int fail_got2, unsigned int poll_min,
                        unsigned int poll_max);

unsigned int hc_bf_u8(unsigned int off);
unsigned int hc_bf_u16(unsigned int off);
unsigned int hc_bf_flags(void);
unsigned int hc_bf_boot_epoch(void);
unsigned int hc_bf_burn_epoch(void);
unsigned int hc_bf_stage_current(void);
unsigned int hc_bf_stage_last(void);
unsigned int hc_bf_stage_fail(void);

#endif
