/*
 * hcvss711.h - vehicle speed input + gear detection (2026-11-04).
 * hcvss711.c; core firmware/sensors/hcvss.c; capture in hctrig_me711.c
 * (ROLE_VSS on a free cam capture, or CC14 on the VAG boards).
 * Live data OCH 1664..1671 (TGT_RAM_OCH3).
 */
#ifndef HCVSS711_H
#define HCVSS711_H

/* the capture interrupt's record (TGT_RAM_VSS): written at one level */
typedef struct {
    unsigned int n;               /* edges                                 */
    unsigned int ms;              /* hc_tick_ms of the last edge           */
} hc_vss_rec_t;

/* the capture setup the trigger module resolves (CCMOD nibble, IC word),
   kept in the last 4 bytes of TGT_RAM_VSS: near RAM is at its reserve */
#define HC_VSS_CCM (*(unsigned int huge *)(TGT_EXTRAM_BASE + TGT_RAM_VSS + 0x1CuL))

/* for the trigger module (task context): the cam capture channel the speed
   input takes (TGT_CAPCH_CC8 / CC9), 0xFF = none; and the VAG boards' own
   CC14 capture armed (1) or released (0) */
unsigned char far hc_vss_cam_channel(void);
void far hc_vss_arm(unsigned char on);

void far hc_vss_init(void);                    /* once at boot            */
void far hc_vss_service(unsigned int ms);      /* every main-loop pass    */
/* the vehicle speed, 0.1 km/h: the speed input when it is routed, else
   the CAN source (hccan711.c); 0xFFFF = none */
unsigned int  far hc_vss_x10(void);
unsigned int  far hc_vss_wire_x10(void);       /* the input alone          */
unsigned char far hc_vss_gear(void);           /* 0 = neutral / unknown    */

#endif
