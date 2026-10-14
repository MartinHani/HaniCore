/*
 * hcio711.h - the Porsche ME7.1.1's NATIVE I/O that the main CPU reaches only
 * indirectly: the peripheral ASIC's output ports (N75/LDR, EVAP/TEV, the four
 * lambda heaters, NLEN_AS), the controlled key-off (run-on through the
 * CJ910's /EN2), the two CJ120 wideband interfaces on the shared SSC, and the
 * LSU 4.2 conversion. V79.
 *
 * FAR CODE, AND PURE ON PURPOSE. NCODE has ~660 bytes left, so this module is
 * compiled MEDIUM into FCODE. A far routine cannot make a near call into the
 * SMALL image (those return with RET), so it calls NOTHING outside itself:
 * every fact arrives as a parameter, every port it owns it touches itself,
 * and its TunerStudio words are written straight into the OCH block. Its
 * state is `static`, compiled RENAMECLASS(NDATA0=XNDATA0) into on-chip XRAM,
 * so near RAM does not move. 16-bit arithmetic only: Keil's long multiply
 * and divide helpers are near library code this module must not reach.
 *
 * EVIDENCE, per mechanism (details in the .c):
 *   ASIC port images   [BIN] 0x8BE2B6 builds runtime TX words 52..58 from
 *                      FDDC..FDE8 (normal path, table 0x816E80) or from the
 *                      shadow 0x8052..0x805E (0x8B1CE6); 0x8B17B0 seeds the
 *                      shadow from calibration; the register table at
 *                      0x828B1C maps shadow bytes to ASIC P6,P0,P1,P2,P3,P4,
 *                      P7/P8. The OEM's actuator test [BIN 0x88F766] switches
 *                      LDR by setting/clearing FDE8.2.
 *   run-on             NL = NLEN_FR OR NOT(NLEN_AS) (S5600, hcpower.c); the
 *                      OEM's idle P1 image 0x3DCF has NLEN_AS (P1L.3) = 1, and
 *                      its shutdown path [BIN 0x8B5074..5088] clears P3.12.
 *   CJ120              [BIN 0x8C0734] P8.x LOW around an SSC transfer with
 *                      SSCCON 0x4617 / SSCBR 0x13; commands 0x48 IDENT, 0x56
 *                      INIT_REG1 write, 0x6C INIT_REG1 read, 0x78 DIAG; the
 *                      OEM writes INIT_REG1 = 0x98 then 0x90 [0x88FCC8,
 *                      0x88FD58] - VL = 0, pump-current gain 8.
 */
#ifndef HCIO711_H
#define HCIO711_H

/* ---------------------------------------------------------- ASIC outputs */
#define HC_IO_LDR       0u   /* ASIC P7.2  N75 boost valve, cavity 104     */
#define HC_IO_TEV       1u   /* ASIC P7.3  EVAP purge, cavity 64           */
#define HC_IO_LSH2VK    2u   /* ASIC P7.4  heater, bank 2 pre-cat          */
#define HC_IO_LSH1HK    3u   /* ASIC P7.5  heater, bank 1 post-cat         */
#define HC_IO_LSH2HK    4u   /* ASIC P7.6  heater, bank 2 post-cat         */
#define HC_IO_LSH1VK    5u   /* ASIC P8.7  heater, bank 1 pre-cat, cav 5   */
#define HC_IO_MIL       6u   /* ASIC P7.0  check-engine lamp, cav 47  */
#define HC_IO_COUNT     7u
/* VIRTUAL test channels for the heater-drive bench experiment only -
   the S5500's own PWM units 0..3 (frame words 59..62 = PP0..PP3, 63..66 =
   PW0..PW3, S5500 IROM 0x1C2C). hc_io_test_start() may pulse one of them
   with the OEM period and a 100 % high output; nothing else ever drives
   them (the forced-OFF pair stays). */
#define HC_IO_TEST_PWM0 8u
/* CJ120 mode holds, both chips: +0 0xC8 cold (pump off), +1 RA, +2 LA,
   +3 pump on (0x88, PA = 0), +4 the calibration 0x9C, +5 the V79..V95 value 0x90 */
#define HC_IO_TEST_CJ0  16u
#define HC_IO_TEST_CJ_N 6u

#define HC_IO_WORD0     52u  /* first runtime TX word carrying an image    */
#define HC_IO_WORDS     7u

/* runtime TX words 59..66 are the ASIC's on-chip PWM registers - the
   ASIC copies them into PP0..PP3 (59..62) and PW0..PW3 (63..66) on EVERY
   runtime frame [ASIC IROM 0x202C-0x2050, sibling 7x00005d]; the OEM sources
   them from RAM 0xD2F4..0xD302 [BIN table 0x816E80 slots 55..62]. P7.0..P7.3
   are POUT0..3, so P7.2 = N75/LDR (cavity 104), P7.3 = EVAP (cavity 64).
   Edge-aligned C167 PWM drives its output HIGH while PT >= PW and the pin is
   the port latch XOR that output; the latch is 1 (idle image), the stages are
   active LOW - so PW = 0 is FULL ON and PW > PP is OFF. The OEM's own forced
   OFF is PP = 0xFFFE, PW = 0xFFFF [BIN 0x8C2EEA..0x8C2F00]. HaniCore sent 0 in
   all eight until V80, which is FULL ON if PWMCON1 enables the output.
   PWMCON1 comes from startup word 61, which the OEM builder hard-codes 0x0000
   (PEN0..3 = 0: outputs disabled, PROBABLE via the sibling IROM, where 0x1C62
   is its only write) - so these words are expected to be inert. They are sent
   as the OEM's OFF values anyway: that is safe under BOTH readings. */
#define HC_IO_PWM_WORD0 59u
#define HC_IO_PWM_WORDS 8u

/* run-on states (hc_io_runon_service) */
#define HC_RO_RUN        0u  /* KL15 on                                    */
#define HC_RO_HOLD       1u  /* key off: run-on asserted, outputs safe,
                                waiting for persistence and the min hold   */
#define HC_RO_RELEASED   2u  /* veto restored: the CJ910 may drop us       */
#define HC_RO_TIMEOUT    3u  /* max run-on reached: released by force      */
#define HC_RO_OFF        4u  /* run-on not configured: key-off = power-off */
#define HC_RO_BOOTOFF    5u  /* BOOTED with KL15 already off - power
                                is never held (a reset during key-off must
                                not re-latch the ECU's own supply)         */

/* runon flags returned */
#define HC_RO_F_KEYOFF   0x01u   /* outputs must be safe                   */
#define HC_RO_F_HOLDING  0x02u   /* NLEN_FR is LOW (run-on requested)      */

extern unsigned char hc_io_cj_mask;   /* bit0/1: CJ120 #1/#2 in use */

void far hc_io_init(void);
/* One call per runtime ASIC frame, BEFORE the words are copied: advances the
   frame-synchronous PWM and composes the images. */
void far hc_io_frame(void);
unsigned int far hc_io_word(unsigned char i);        /* TX word 52 + i     */
unsigned int far hc_io_pwm_word(unsigned char i);    /* TX word 59 + i     */
void far hc_io_duty(unsigned char ch, unsigned int duty_x10);  /* 0..1000  */
void far hc_io_all_off(void);

/* The controlled key-off. kl15 is P6.2 as main read it; enabled is "the
   native main relay is configured" (mainRelayBound == 2); nvm_busy is 1
   while a Burn or an erase owns the store; min_hold_ms is the page's main
   relay hold. Returns HC_RO_F_*. */
unsigned char far hc_io_runon_service(unsigned int ms, unsigned char kl15,
                                      unsigned char enabled,
                                      unsigned char nvm_busy,
                                      unsigned int min_hold_ms,
                                      unsigned int batt_dv);

/* THE BOOT HISTORY (TGT_RAM_BOOTHIST, battery-backed). One call per
   boot, before the run-on service first runs: files a record of the reset
   that ended the PREVIOUS boot (raw WDTCON flags, its uptime and furthest
   stage from RESETDIAG, the run-on state it was in, the lowest battery it
   saw, KL15 as it last saw it and whether it held power) plus KL15 at THIS
   boot. hc_io_boothist_byte() serves the 168-byte ring through the extended
   output-channel window for the vehicle logger. */
void far hc_io_boothist_boot(unsigned int boots, unsigned int raw,
                             unsigned int prev_ms, unsigned int prev_stage,
                             unsigned char kl15);
unsigned char far hc_io_boothist_byte(unsigned int off);
#define HC_BH_HDR   8u
#define HC_BH_REC  10u
#define HC_BH_N    16u
#define HC_BH_BYTES (HC_BH_HDR + HC_BH_N * HC_BH_REC)

/* CJ120: one polled transaction if one is due. Called ONLY from the S5500
   state machine's idle window (hcasicstart.c), never while a PEC exchange is
   in flight. mask bit0/bit1 = device 1/2 enabled (lambda source INTERNAL). */
void far hc_io_cj120_slot(unsigned int ms, unsigned char mask);
/* 1 when hc_io_cj120_slot() would run a transaction now (2026-10-14: the
   S5500 exchange gives it priority over its own pre-build steps) */
unsigned char far hc_io_cj120_due(unsigned int ms, unsigned char mask);

/* Wideband + heater, once per main-loop pass. ua1/ua2 raw AN6/AN4 (CJ120
   UA); ur1/ur2 raw ASIC AN12/AN13 (CJ120 UR, the Ri signal), 0xFFFF when
   the ADC did not tag the slot; vbatt in 0.1 V; running = engine turning
   under sync. V96: calibration (RA+LA), closed-loop heater on Ri, pump
   current only when hot - see hcio711.c "THE CJ120 OPERATING MODE". */
void far hc_io_lambda_service(unsigned int ms, unsigned int ua1,
                              unsigned int ua2, unsigned int ur1,
                              unsigned int ur2, unsigned int vbatt_dv,
                              unsigned char running);

/* raw AN6/AN4 count -> lambda x1000 (LSU 4.2, clamped 0.700..2.000). */
unsigned int far hc_io_lambda_calc(unsigned int raw);

/* Bounded bench pulse on one ASIC output: on for on_ms, 3 times, 1 s apart.
   Refuses heaters (a heater is not pulsed unattended). */
unsigned char far hc_io_test_start(unsigned char ch, unsigned int on_ms,
                                   unsigned int ms);
void far hc_io_test_service(unsigned int ms);

/* TunerStudio words 734..757, written into the OCH block directly. */
unsigned char far hc_io_wb_fault(unsigned char bank);   /* V97 */
void          far hc_io_wb_clear(void);                 /* !D re-arms a latched fault */
unsigned int  far hc_io_lambda(unsigned char bank);     /* x1000, 0 = not fresh */
unsigned int far hc_io_lambda_protection(unsigned char bank);
/* the CC195 band code into the ASIC P1 image (0xFF = the idle image) */
void far hc_io_knock_band(unsigned char code);
void far hc_io_publish(unsigned int boost_req_x10, unsigned char part);

#endif
