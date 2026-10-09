/* hcliveforensics.h - V49 first-event live-Burn retained evidence. */
#ifndef HCLIVEFORENSICS_H
#define HCLIVEFORENSICS_H

#include "hctarget.h"

#define HC_LF_BYTES       344u
#define HC_LF_WORDS       172u
#define HC_LF_ADDR        (TGT_EXTRAM_BASE + TGT_RAM_LIVEFORENSICS)
#define HC_LF_WORD(i) \
    (((unsigned int volatile huge *)HC_LF_ADDR)[(unsigned int)(i)])

/* Header, words 0..15. */
#define LF_MAGIC0          0u
#define LF_MAGIC1          1u
#define LF_VERSION         2u
#define LF_LENGTH          3u
#define LF_FLAGS           4u
#define LF_EPOCH           5u
#define LF_RESET_RAW       6u
#define LF_REQUEST_MS      7u
#define LF_BASE_WINDOWS    8u
#define LF_BASE_ENTRIES    9u
#define LF_BASE_SUCCESS   10u
#define LF_BASE_FAIL      11u
#define LF_RELEASE_ID     12u
#define LF_RECOVERY       13u
#define LF_BOOT_ID        14u
#define LF_INTEGRITY      15u

#define LF_F_ARMED        0x0001u
#define LF_F_STAGED       0x0002u
#define LF_F_NMI_STARTED  0x0004u
#define LF_F_NMI_COMPLETE 0x0008u
#define LF_F_RECOVERED    0x0010u
#define LF_F_DURABLE      0x0020u
#define LF_F_FROZEN       0x0040u
#define LF_F_BOOT_SEALED  0x0080u
#define LF_F_VALID        0x8000u

/* Writer/admission, words 16..55. */
#define LF_STAGE_MS       16u
#define LF_FIRST_WR_MS    17u
#define LF_ADMIT_MS       18u
#define LF_ADMIT_T7       19u
#define LF_WINDOW_SEQ     20u
#define LF_CURSOR         21u
#define LF_WR_ENTRY       22u
#define LF_WR_RETURN      23u
#define LF_COMMAND_SEQ    24u
#define LF_VERIFY_SEQ     25u
#define LF_COMMAND_T7     26u
#define LF_VERIFY_T7      27u
#define LF_RETURN_T7      28u
#define LF_RESTORE_T7     29u
#define LF_SAVE_CC7IC     30u
#define LF_SAVE_T8IC      31u
#define LF_SAVE_SSCTIC    32u
#define LF_SAVE_SSCRIC    33u
#define LF_SAVE_SSCEIC    34u
#define LF_DUR_CC7IC      35u
#define LF_DUR_T8IC       36u
#define LF_DUR_SSCTIC     37u
#define LF_DUR_SSCRIC     38u
#define LF_DUR_SSCEIC     39u
#define LF_LOST_LAST      40u
#define LF_LOST_OR        41u
#define LF_FIRST_LOST_POS 42u
#define LF_FIRST_LOST_T7  43u
#define LF_ENTRY_SSCON    44u
#define LF_ENTRY_PECC0    45u
#define LF_ENTRY_PECC4    46u
#define LF_ENTRY_PORT     47u
#define LF_ENTRY_T8REL    48u
#define LF_ENTRY_T8       49u
#define LF_ENTRY_T0       50u
#define LF_ENTRY_CC7      51u
#define LF_MAX_WINDOW_T7  52u
#define LF_LAST_WINDOW_T7 53u
#define LF_ADMISSION      54u
#define LF_BOUNDARY_MARK  55u

/* Two 20-word supervision slots start at word 56. */
#define LF_ASIC_BASE      56u
#define LF_ASIC_WORDS     20u

/* NMI snapshot, words 96..143.  Assembly depends on these exact offsets. */
#define LF_NMI_BASE       96u
#define LF_NMI_STARTED    96u
#define LF_NMI_COMPLETE   97u

/* Anomaly summary, words 144..159. */
#define LF_ANOM_BASE     144u
#define LF_ASIC_LAST_LAUNCH_MS 144u
#define LF_ASIC_LAST_DONE_MS   145u
#define LF_ASIC_MAX_GAP_MS     146u
#define LF_ASIC_LAST_GAP_MS    147u
#define LF_ASIC_SEQ            148u
#define LF_ASIC_SLOT           149u
#define LF_FIRST_ANOMALY       150u
#define LF_SSC_ISR_T7          151u
#define LF_SSC_ISR_COUNT       152u
#define LF_SSC_ISR_PEC         153u
#define LF_TICK_LAST_T7        154u
#define LF_TICK_LAST_GAP       155u
#define LF_TICK_MAX_GAP        156u
/* The relocated writer owns LF_VERIFY_SEQ, so the writer's own result
   code needs a word of its own rather than sharing one with it. */
#define LF_WRITER_RESULT       157u
/* V50.  Words 158 and 159 were reserved and zero in V49, so adding them keeps
   HC_LF_BYTES at 344 and the whole TunerStudio wire layout byte-identical.
   LF_IR_DROPPED is the discriminator the V50 fix exists to drive to zero;
   LF_LOST_OR keeps its V49 meaning (a request AROSE while masked, which is
   legitimate).  See hcnvm.c's HCNV_IE_* note. */
#define LF_IR_DROPPED          158u
#define LF_IR_DROPPED_POS      159u

/* Private UMKOM state, words 160..171. */
#define LF_UM_BASE       160u

void HC_COLD hc_lf_boot_early(unsigned int raw_reset, unsigned int boot_id);
extern unsigned char hc_lf_fast_active;
void HC_COLD hc_lf_arm(unsigned int request_ms,
               unsigned int windows, unsigned int entries,
               unsigned int successes, unsigned int failures);
unsigned char HC_COLD hc_lf_active(void);
void HC_COLD hc_lf_stage_done(unsigned int ms);
void HC_COLD hc_lf_admit(unsigned int ms, unsigned int t7, unsigned int pos,
                 unsigned int admission, unsigned int sscon,
                 unsigned int pecc0, unsigned int pecc4, unsigned int port,
                 unsigned int t8rel, unsigned int t8,
                 unsigned int t0, unsigned int cc7);
void HC_COLD hc_lf_writer_return(unsigned int t7, unsigned int elapsed);
void HC_COLD hc_lf_ir_after(unsigned int dropped, unsigned int pos);
void HC_COLD hc_lf_restore(unsigned int restore_t7, unsigned int pos,
                   unsigned int save_cc7, unsigned int save_t8,
                   unsigned int save_tx, unsigned int save_rx,
                   unsigned int save_err, unsigned int dur_cc7,
                   unsigned int dur_t8, unsigned int dur_tx,
                   unsigned int dur_rx, unsigned int dur_err,
                   unsigned int writer_result);
void HC_COLD hc_lf_asic_launch(unsigned int ms, unsigned int t7,
                       unsigned int tx1, unsigned int tx2, unsigned int tx3,
                       unsigned int state, unsigned int run_tx);
void HC_COLD hc_lf_asic_complete(unsigned int ms, unsigned int t7,
                         unsigned int rx0, unsigned int rx1,
                         unsigned int rx2, unsigned int rx3,
                         unsigned int calc, unsigned int recv,
                         unsigned int outcome, unsigned int state,
                         unsigned int pec0, unsigned int pec4,
                         unsigned int xfer_ms);
void HC_COLD hc_lf_um_before(unsigned int acc_hi, unsigned int acc_lo,
                     unsigned int seed, unsigned int answer,
                     unsigned int phase, unsigned int health,
                     unsigned int expect, unsigned int answers,
                     unsigned int input_word1);
void HC_COLD hc_lf_um_after(unsigned int acc_hi, unsigned int acc_lo,
                    unsigned int seed, unsigned int answer);
void HC_COLD hc_lf_recover(unsigned int state, unsigned int result,
                   unsigned int pos, unsigned int raw_reset);
void HC_COLD hc_lf_durable(unsigned int ms, unsigned int pos);
unsigned char HC_COLD hc_lf_export_byte(unsigned int offset);

#endif
