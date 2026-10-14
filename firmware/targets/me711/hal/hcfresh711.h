#ifndef HCFRESH711_H
#define HCFRESH711_H

/* Target acquisition metadata, in the declared route SRAM region. Main ADC
   samples publish from the tick ISR; task readers use hcatomic.h for snapshots. */
#define ADC_META ((unsigned int huge *)(TGT_EXTRAM_BASE + TGT_RAM_ADC_META))
#define MAIN_LIVE ADC_META[32u]
#define ASIC_SAMPLE_MS ADC_META[33u]
#define ASIC_SAMPLE_LIVE ADC_META[34u]
#define MAIN_SEEN ADC_META[35u]
#define MAIN_BAD ADC_META[36u]
#define MAIN_ADC_STARTED ADC_META[37u]
#define HC_FRESH_OK        0u
#define HC_FRESH_NO_SOURCE 1u
#define HC_FRESH_NEVER     2u
#define HC_FRESH_STALE     3u
#define HC_FRESH_REJECTED  4u
unsigned char far hc_fresh_tps_why(void);
unsigned char far hc_fresh_reason(unsigned char sem);
unsigned char far hc_fresh_tps_pair(unsigned int *r1, unsigned int *r2,
                                    unsigned int *sample_ms);
/* the pedal pair brought to one sample time (main-CPU channels) */
void far hc_fresh_app_pair(unsigned int *r1, unsigned int *r2);

void far hc_fresh_init(void);
void far hc_fresh_service(void);
void far hc_hal_main_sample(unsigned char ch, unsigned int word,
                            unsigned char done, unsigned int ms);
unsigned int far hc_hal_ain_age(unsigned char sem);
unsigned int far hc_hal_asic_age(void);
unsigned int far hc_hal_main_seq(unsigned char sem);
void far hc_fresh_bind(unsigned char sem, unsigned char ch);
unsigned char far hc_fresh_bound(unsigned char sem);
unsigned int far hc_fresh_asic_an(unsigned char ch);
unsigned int far hc_fresh_ain(unsigned char sem);
unsigned char far hc_fresh_phys(unsigned char sem);
unsigned char far hc_fresh_ok(unsigned char sem);
#endif
