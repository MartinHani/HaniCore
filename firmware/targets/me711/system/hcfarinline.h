/*
 * hcfarinline.h - CALL-FREE page reads for the FAR (FCODE) modules.
 *
 * Included by those modules AFTER hcconfig.h (a function-like macro defined
 * before it would rewrite hc_cal_u8's own prototype), only under
 * DEFINE(HC_FAR_BRIDGE).
 *
 * MEASURED, and why it exists. hc_validate() reads the page thousands of
 * times a pass. Through the hcfar_me711.c thunk every read is CALLS + CALLA +
 * RET + RETS, and c167sim put the worst S5500 service gap during an injector
 * ROUTING write at 8.29 ms on V81 against 6.00 ms on V80 (budget 10 ms); the
 * real ECU logged ~4 asicTimeouts per 12 such writes on V81
 * (tools/me711_pinwrite_gap_proof.py).
 *
 * These are EXACTLY hcconfig.c's hc_cal_u8()/hc_cal_u16(): the scalars from
 * near hc_cfg[], the tables straight out of the battery-backed SRAM page (the
 * same huge pointer hcio711.c's IO_PAGE is), zero past the end. The argument
 * is evaluated more than once, so it must have no side effects - none of the
 * call sites in these four modules does.
 */
#ifndef HCFARINLINE_H
#define HCFARINLINE_H

#define HCFB_PAGE ((unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_CFG \
                                          + HC_CFG_HDR_LEN))
#undef hc_cal_u8
#undef hc_cal_u16
#define hc_cal_u8(off)                                                     \
    (((unsigned int)(off) < HC_CFG_CORE) ? hc_cfg[(unsigned int)(off)]    \
     : (((unsigned int)(off) < HC_CFG_SIZE)                               \
        ? HCFB_PAGE[(unsigned int)(off)] : (unsigned char)0u))
#define hc_cal_u16(off)                                                    \
    ((unsigned int)(((unsigned int)hc_cal_u8(off) << 8)                   \
                    | (unsigned int)hc_cal_u8((unsigned int)(off) + 1u)))

/* VARIABLE OFFSETS. With a constant offset the macros above fold to one
   SRAM or near read; with a variable one they inline the whole three-way
   test, ~40 bytes per call site. These are the same reads behind one far
   call (hc_config_manager.c) - use them where the offset is computed
   (2026-10-14: far code space for the auxiliary functions). */
unsigned char far hc_cal_u8v(unsigned int off);
unsigned int  far hc_cal_u16v(unsigned int off);

#endif
