/*
 * hchal_me711.h - what the Bosch HAL publishes ON TOP of the shared
 * hchal.h contract.
 *
 * Everything here exists for ONE job: closing the S5500 runtime-frame analog
 * mapping from the bench, using the NORMAL V20 image, without another flash
 * and without spraying 118 words down a 19200-baud K-line.
 *
 * The method: snapshot a 16-word window of the last ACCEPTED runtime frame,
 * decode it as if it were the C167 ADDAT block the STARTUP frame is
 * hardware-proven to carry, and publish both the raw words and the decode.
 * Move the window over the wire, sweep it across the frame, and read which
 * position produces sixteen self-consistent channel indices AND tracks a
 * sensor you heat with your hand.
 *
 * hc_s5500_idx and hc_s5500_plausible are the discriminator. In the ADDAT
 * format the top nibble of each word is the channel number, so at the correct
 * base every word i has (w >> 12) == i. At a wrong base that is essentially
 * never true sixteen times over - the V9 capture matched all sixteen.
 */
#ifndef HCHAL_ME711_H
#define HCHAL_ME711_H

#define HC_S5500_N   16u

/* The window, refreshed on the edge of hc_asic_run_ok. Accessors rather than
   arrays because the storage is in the external SRAM (TGT_RAM_S5500WIN) -
   near RAM on this part is 1792 bytes and the engine layer has to fit. */
unsigned int hc_s5500_raw(unsigned char i);   /* word i, exactly as received */
unsigned int hc_s5500_val(unsigned char i);   /* its low 10 bits             */

/* Bit i set = word i's top nibble equals i, i.e. it decodes as ADDAT channel
   i. All sixteen set is the V9 startup-frame signature. */
extern unsigned int  hc_s5500_idx;

extern unsigned char hc_s5500_base;       /* first frame word in the window  */
extern unsigned int  hc_s5500_snaps;      /* snapshots taken                 */
extern unsigned int  hc_s5500_plausible;  /* snapshots with ALL 16 matching  */

/* Move the window. Clamped so it can never read past the 118-word frame.
   Driven from hcts_target_cmd()'s '!' handler. */
void hc_hal_s5500_window(unsigned char base);
/* ASIC AN0..AN15 raw from the S5500 window, 0xFFFF unless tagged */
unsigned int hc_hal_asic_an(unsigned char ch);
/* Completion/tag/freshness for MAIN ADC; timestamp is conversion start. */
#include "hcfresh711.h"

/* MAIN_RELAY and FUEL_PUMP pin state, READ BACK from the port registers
  : 1 = the CPU pin is an output at the ACTIVE level right now. It says
   what this CPU is doing, not what the CJ920 stage or a relay does. */
unsigned char hc_hal_main_relay_driven(void);
unsigned char hc_hal_main_relay_inhibited(void);
unsigned char hc_hal_fuelpump_driven(void);


/* The bridge PWM frequency, from the page (0 = the board default). The HAL
 * applies it itself on the next duty write; hcetbcal.c also drives it
 * directly while it evaluates candidate frequencies. */
void hc_hal_dbw_pwm_hz(unsigned int hz);
unsigned int hc_hal_dbw_pwm_period(void);
unsigned int hc_hal_dbw_pwm_applied_hz(void);
void hc_hal_dbw_pwm_poll(void);

/* The tacho output, cavity 37 / P2.13 / CC13 (hcroutes711.c, far):
   init releases the pin, the main loop sets the frequency, the 1 ms tick
   re-arms the hardware compare. */
void far hc_tacho_init(void);
void far hc_tacho_service(void);
void far hc_tacho_tick(void);
unsigned char far hc_tacho_running(void);
void far hc_tacho_test(unsigned char rpm100);

#endif /* HCHAL_ME711_H */