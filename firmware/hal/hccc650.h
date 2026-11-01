/*
 * hccc650.h - the CC650 bus ASIC (Bosch 30380) of the ME7.5 DC board
 * (4B0906018DC): init sequence, output shadows, run-on, knock band, safe
 * shutdown. SHARED CORE, SFR-FREE.
 *
 * The core never touches the bus. The target calls hccc650_next() and, when
 * it returns 1, performs exactly one byte write to 0x480000 + reg (page
 * 0x120, 8-bit bus); the core decides the order. Shadows are written WHOLE,
 * as the stock code does (MOVB RLx,shadow -> bus).
 *
 * Evidence: .scratch/me75-reverse/CC650_REGISTER_MAP.md, IO_MAP.md
 *   EXACT TARGET BINARY 4B0906018DC: boot sequence 0x096D3C, setup 0x070960,
 *   refresh 0x070ACC, shutdown 0x08CCE4 / fatal 0x024116, run-on 0x070392.
 *   Output bit meanings: the identical X505P code + its A2L names.
 */
#ifndef HCCC650_H
#define HCCC650_H

/* refreshed shadow registers, in the stock refresh order first */
#define HCCC650_SH_3A   0u      /* outputs: N249 N205 MIL EPC fan ...      */
#define HCCC650_SH_38   1u
#define HCCC650_SH_40   2u      /* bit 0 secondary air pump                */
#define HCCC650_SH_3E   3u
#define HCCC650_SH_46   4u      /* bit 0 CJ110 LA (calibration)            */
#define HCCC650_SH_44   5u      /* bit 2 run-on (keep-alive)               */
#define HCCC650_SH_30   6u      /* knock control (test pulse / zero test)  */
#define HCCC650_SH_34   7u      /* knock band (low nibble) + gain          */
#define HCCC650_N_SH    8u

/* logical outputs (polarity handled by the core) */
#define HCCC650_OUT_N249        0u  /* 0x3A.0, active LOW - diverter valve */
#define HCCC650_OUT_BRAKE_PUMP  1u  /* 0x3A.1, active LOW -> cavity 22     */
#define HCCC650_OUT_EPC         2u  /* 0x3A.2, active LOW -> cavity 48     */
#define HCCC650_OUT_MIL         3u  /* 0x3A.3, active LOW -> cavity 47     */
#define HCCC650_OUT_N205        4u  /* 0x3A.4, active LOW -> CJ420B -> 115 */
#define HCCC650_OUT_LDP         5u  /* 0x3A.5, active HIGH                 */
#define HCCC650_OUT_AC_CUT      6u  /* 0x3A.6, active HIGH                 */
#define HCCC650_OUT_FAN         7u  /* 0x3A.7, active HIGH                 */
#define HCCC650_OUT_SAP         8u  /* 0x40.0, active LOW -> cavity 66     */
#define HCCC650_OUT_LSU_CAL     9u  /* 0x46.0, active HIGH (CJ110 LA)      */
#define HCCC650_OUT_RUNON      10u  /* 0x44.2, active HIGH (keep-alive)    */
#define HCCC650_N_OUT          11u

/* phases */
#define HCCC650_PH_BOOT     0u  /* 02=00 26=4A 2A=FF 2B=FF 02=20           */
#define HCCC650_PH_SETUP    1u  /* the stock application setup             */
#define HCCC650_PH_RUN      2u  /* dirty shadows first, then round-robin    */
#define HCCC650_PH_SHUTDOWN 3u  /* 44=00 then 02=00                        */
#define HCCC650_PH_DEAD     4u  /* nothing more is written                 */

typedef struct {
    unsigned char sh[HCCC650_N_SH];
    unsigned char dirty;        /* bit per shadow                          */
    unsigned char phase;
    unsigned char cur;          /* sequence / round-robin cursor           */
    unsigned char setup_3e;     /* stock: 0xF1 or 0x01 by calibration       */
} hccc650_t;

/* setup_3e: the value the stock setup writes to 0x3E (0xF1 when the
   calibration byte at 0x8195C3 is 0xF0, else 0x01 - 4B0906018DC). */
void hccc650_init(hccc650_t *c, unsigned char setup_3e);

/* One bus write due? 1 = write *val to CC650 register *reg now. */
unsigned char hccc650_next(hccc650_t *c, unsigned char *reg, unsigned char *val);

/* Logical ON/OFF of an output; marks its shadow dirty only on a change. */
void hccc650_out(hccc650_t *c, unsigned char out, unsigned char on);

/* Knock evaluation: band code (0..15, ME711_KNOCK.md table: 14 kHz = 3)
   and gain step (0..7). */
void hccc650_knock(hccc650_t *c, unsigned char band, unsigned char gain);

/* Ordered power-down: run-on off, then the CC650 mode off. */
void hccc650_shutdown(hccc650_t *c);

/* Onboard ambient pressure from CC650 register 0x16 (8-bit): the stock law
   udsu_w = byte x 4, hPa = udsu_w x DSUGRAD 16221 / 13107 (4B0906018DC
   0x81BF66, DSUOFS 0) - here x (1 + 61/256), within 0.05 %. */
unsigned int hccc650_baro_hpa(unsigned char reg16);

#endif
