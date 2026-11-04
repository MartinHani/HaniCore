/*
 * hccan.h - the VAG drivetrain CAN engine messages, no hardware (2026-11-03).
 *
 * Builds the 8-byte payloads the stock ME7 sends on the 500 kbit/s
 * drivetrain bus: Motor_1 (0x280), Motor_2 (0x288), Motor_3 (0x380),
 * Motor_5 (0x480). Bit layouts, scales and the mux / checksum rules:
 * .scratch/can-bus/VAG_PQ_MESSAGES.md section 2 (FR CAN 51.570, the 1.8T
 * ME7 Funktionsrahmen, cross-checked against opendbc vw_pq.dbc). Bits are
 * Intel (little-endian), byte n = bits 8n..8n+7.
 *
 * No SFR, no global: the target driver (hccan711.c) fills hccan_eng_t from
 * the engine state and hands the payloads to the CAN module. The host test
 * (tests/host/test_hccan_host.py) builds this file with gcc and decodes the
 * payloads with the DBC.
 *
 * Constant shifts only (Keil C166 V7.53 miscompiles some variable shifts).
 */
#ifndef HCCAN_H
#define HCCAN_H

#ifndef HCCAN_FAR
#define HCCAN_FAR
#endif

#define HCCAN_ID_MOTOR1  0x280u
#define HCCAN_ID_MOTOR2  0x288u
#define HCCAN_ID_MOTOR3  0x380u
#define HCCAN_ID_MOTOR5  0x480u
#define HCCAN_ID_MOTOR6  0x488u

/* the engine's state, in HaniCore's own units */
typedef struct {
    unsigned int  rpm;            /* rpm, 0 when stopped                     */
    unsigned int  clt_dc;         /* coolant, 0.1 C + 1000 C bias (x10)      */
    unsigned int  iat_dc;         /* intake air, same convention             */
    unsigned int  pedal_x10;      /* pedal (or throttle without DBW), 0.1 %  */
    unsigned int  tps_x10;        /* throttle, 0.1 %                         */
    unsigned int  rl_x10;         /* relative charge, 0.1 % (ME7 rl)         */
    unsigned int  idle_rpm;       /* idle target, rpm                        */
    unsigned int  vss_x10;        /* vehicle speed, 0.1 km/h (0 = none)      */
    unsigned char fan_pct;        /* radiator fan duty, %                    */
    unsigned int  flags;          /* HCCAN_F_*                               */
} hccan_eng_t;

#define HCCAN_F_IDLE       0x0001u  /* pedal released                     */
#define HCCAN_F_PEDAL_BAD  0x0002u
#define HCCAN_F_TPS_BAD    0x0004u
#define HCCAN_F_CLT_BAD    0x0008u
#define HCCAN_F_IAT_BAD    0x0010u
#define HCCAN_F_RUNNING    0x0020u  /* engine running, not cranking       */
#define HCCAN_F_STOPPED    0x0040u  /* rpm 0: the starter may engage      */
#define HCCAN_F_MIL        0x0080u
#define HCCAN_F_EPC        0x0100u
#define HCCAN_F_HOT        0x0200u  /* coolant over the lamp limit        */
#define HCCAN_F_CUT        0x0400u  /* a fuel cut is active: torque 0     */
#define HCCAN_F_TQ_BAD     0x0800u  /* torque model untrustworthy         */
#define HCCAN_F_NO_DBW     0x1000u  /* cable throttle                     */
#define HCCAN_F_DTC_STORED 0x2000u
#define HCCAN_F_BRAKE      0x4000u

/* the stock identity (Motor_2 / Motor_5 multiplex) */
typedef struct {
    unsigned char canvers;        /* CANVERS                                 */
    unsigned char fmotc;          /* engine code                             */
    unsigned char cwgc;           /* gearbox code                            */
    unsigned char mottyp;         /* engine type                             */
    unsigned int  mdnorm_nm;      /* 100 % torque                            */
    unsigned int  mdmax_nm;       /* maximum torque                          */
    unsigned int  nmdmax_rpm;     /* ... at                                  */
    unsigned int  kvnpz;          /* normalised consumption                  */
} hccan_vag_id_t;

/* what the multiplexes and the consumption counter remember */
typedef struct {
    unsigned char mux2;           /* Motor_2: code (bits 2..3) + repeat      */
    unsigned char mux5;           /* Motor_5: same                           */
    unsigned int  fuel_ul;        /* rolling consumption counter, ul, 15 bit */
    unsigned char fuel_ovf;       /* the counter has wrapped once            */
    unsigned char ctr6;           /* Motor_6 message counter 0..15           */
} hccan_vag_state_t;

void HCCAN_FAR hccan_vag_reset(hccan_vag_state_t *s);

/* indicated torque, 0.1 % of MDNORM, from the charge (first cut, spec
   issue 03: rl-based until the torque model of issue 04) */
unsigned int HCCAN_FAR hccan_torque_x10(const hccan_eng_t *e,
                                        const hccan_vag_id_t *id);

void HCCAN_FAR hccan_motor1(const hccan_eng_t *e, const hccan_vag_id_t *id,
                            unsigned char *d);
void HCCAN_FAR hccan_motor2(hccan_vag_state_t *s, const hccan_eng_t *e,
                            const hccan_vag_id_t *id, unsigned char *d);
void HCCAN_FAR hccan_motor3(const hccan_eng_t *e, unsigned char *d);
void HCCAN_FAR hccan_motor5(hccan_vag_state_t *s, const hccan_eng_t *e,
                            const hccan_vag_id_t *id, unsigned char *d);

/* Motor_6 (0x488, 10 ms, FR p1644): torque for the gearbox, altitude
   factor, counter + XOR checksum. baro_x10 = ambient pressure, 0.1 kPa
   (0 = unknown -> 1.0). */
void HCCAN_FAR hccan_motor6(hccan_vag_state_t *s, const hccan_eng_t *e,
                            const hccan_vag_id_t *id, unsigned int baro_x10,
                            unsigned char *d);

/* add injected fuel to the Motor_5 counter (ul, wraps at 15 bits) */
void HCCAN_FAR hccan_fuel_add(hccan_vag_state_t *s, unsigned int ul);

/* 0.75 C - 48 C per bit (Motor_2 coolant, Motor_3 intake air); 0xFF = fault */
unsigned char HCCAN_FAR hccan_temp_byte(unsigned int dc, unsigned char bad);

/* ------------------------------------------------- RECEIVE (2026-11-03) --
   What the other drivetrain units send, decoded from their 8 bytes. Bits:
   .scratch/can-bus/VAG_PQ_MESSAGES.md section 3 (opendbc vw_pq.dbc, the FR
   where it describes them). Speeds are 0.01 km/h on the bus, 0.1 km/h here. */
#define HCCAN_ID_BREMSE1   0x1A0u
#define HCCAN_ID_BREMSE3   0x4A0u
#define HCCAN_ID_GETRIEBE1 0x440u
#define HCCAN_ID_KOMBI1    0x320u
#define HCCAN_ID_KOMBI2    0x420u
#define HCCAN_ID_AIRBAG1   0x050u
#define HCCAN_ID_KLIMA1    0x5E0u

typedef struct {
    unsigned int  vss_x10;        /* vehicle speed, 0.1 km/h                */
    unsigned char brake;          /* brake light switch                     */
    unsigned char asr_req, msr_req, esp_off;  /* ESP/ASR switched off: 61  */
    unsigned char asr_slow, asr_fast, msr;    /* torque requests, 0.39 %MDI */
    unsigned char counter;
} hccan_bremse1_t;
void HCCAN_FAR hccan_rx_bremse1(const unsigned char *d, hccan_bremse1_t *o);

/* four wheel speeds FL FR RL RR, 0.1 km/h */
void HCCAN_FAR hccan_rx_bremse3(const unsigned char *d, unsigned int *w4);

typedef struct {
    unsigned char gear;           /* 0 N, 1..5, 6 = 1st, 7 R, 8 6th, 9 7th, 15 fault */
    unsigned char selector;       /* P/R/N/D/S/tip code                    */
    unsigned char tq_valid;       /* the torque request is valid (bit 7)   */
    unsigned char tq_req;         /* requested inner torque, 0.39 %MDI     */
    unsigned char ac_off, cooling, mil;
} hccan_getriebe1_t;
void HCCAN_FAR hccan_rx_getriebe1(const unsigned char *d, hccan_getriebe1_t *o);

typedef struct {
    unsigned int  vss_x10;        /* cluster speed, 0.1 km/h               */
    unsigned char fuel_l;         /* fuel level, litres                    */
    unsigned char fuel_low, oil_warn, clt_low;
} hccan_kombi1_t;
void HCCAN_FAR hccan_rx_kombi1(const unsigned char *d, hccan_kombi1_t *o);

/* Kombi_2: ambient 0.5 C - 50, oil temperature 1 C - 60 -> 0.1 C + 1000 C
   bias (HaniCore's temperature convention); 0 = not sent */
void HCCAN_FAR hccan_rx_kombi2(const unsigned char *d, unsigned int *amb_dc,
                               unsigned int *oil_dc);

/* Airbag_1: 1 = a crash the airbag ECU evaluated (bit 7, intensity >= 4) in
   a frame whose checksum holds (XOR of bytes 0..3 = 0, FR CSAIR); 0 = no
   crash; 2 = checksum wrong (ignored, never a crash) */
unsigned char HCCAN_FAR hccan_rx_airbag1(const unsigned char *d);

typedef struct {
    unsigned char idle_up, compressor, ac_switch;
    unsigned int  load_x4;        /* compressor torque, 0.25 Nm            */
    unsigned char fan_x4;         /* fan request, 0.4 %                    */
} hccan_klima1_t;
void HCCAN_FAR hccan_rx_klima1(const unsigned char *d, hccan_klima1_t *o);


/* ------------------------------------- 2026-11-04: emulation, wideband,
   Haldex, OBD-II. Bits: opendbc vw_pq.dbc (Bremse_1 0x1A0, Bremse_3 0x4A0,
   Allrad_1 0x2C0); rusEFI wideband_can.h / AemXSeriesLambda.cpp (formats
   only - no code copied); ISO 15765-4 / SAE J1979 (OBD). */
#define HCCAN_ID_ALLRAD1   0x2C0u
#define HCCAN_ID_OBD_FUNC  0x7DFu
#define HCCAN_ID_OBD_REQ   0x7E0u
#define HCCAN_ID_OBD_RESP  0x7E8u
#define HCCAN_ID_WB_RUSEFI 0x190u     /* + 2 x index (data frame)           */
#define HCCAN_ID_WB_AEM    0x180u     /* 29-bit, + index                    */

/* ABS EMULATION (a car with NO ABS unit): Bremse_1 = vehicle speed, the
   brake bit, a counter; Bremse_3 = four wheel speeds (0.1 km/h in). */
void HCCAN_FAR hccan_tx_bremse1(unsigned int vss_x10, unsigned char brake,
                                unsigned char ctr, unsigned char *d);
void HCCAN_FAR hccan_tx_bremse3(const unsigned int *w4, unsigned char *d);

/* Allrad_1 (Haldex Gen1): the rear clutch's actual lock, 0.1 %, and its
   status bits (bit 0 clutch fault, 1 overtemperature, 2 tension fault,
   3 fully open, 4 limp, 5 warning lamp, 6 speed limit) */
void HCCAN_FAR hccan_rx_allrad1(const unsigned char *d, unsigned int *lock_x10,
                                unsigned char *status);

/* WIDEBAND over CAN: lambda x1000 (1000 = 1.000), 0 = not valid.
   rusEFI: data frame 0x190 + 2 x index, version >= 0xA0 not newer than
   HCCAN_WB_VERSION, valid byte bit 0, lambda little-endian x 0.0001.
   AEM X-series: lambda big-endian x 0.0001, byte 6 bit 7 valid, byte 7
   bit 6 fault. */
#define HCCAN_WB_VERSION  0xA0u
unsigned int HCCAN_FAR hccan_rx_wb_rusefi(const unsigned char *d);
unsigned int HCCAN_FAR hccan_rx_wb_aem(const unsigned char *d);

/* HALDEX CONTROL BY ABS EMULATION (plan 03): the rear axle is reported
   slower than the front by an offset; the offset that gives 0 % / 100 %
   lock at this rpm is the feed-forward, a PI on (wanted - actual) trims it.
   0.1 km/h offsets, 0.1 % locks; the integrator is 0.01 km/h. */
typedef struct {
    int integ_x100;               /* 0.01 km/h                             */
} hccan_hx_t;
void HCCAN_FAR hccan_hx_reset(hccan_hx_t *h);
unsigned int HCCAN_FAR hccan_hx_offset(hccan_hx_t *h, unsigned int want_x10,
                                       unsigned int act_x10,
                                       unsigned char act_ok,
                                       unsigned int no_x10, unsigned int full_x10,
                                       unsigned char kp100, unsigned char ki100,
                                       unsigned char deadband_pct,
                                       unsigned int dt_ms);

/* OBD-II mode 01: the live values a PID reads */
typedef struct {
    unsigned int rpm;             /* rpm                                   */
    unsigned int vss_x10;         /* 0.1 km/h, 0xFFFF = none               */
    unsigned int clt_dc, iat_dc;  /* 0.1 C + 1000 C                        */
    unsigned int map_x10;         /* 0.1 kPa                               */
    unsigned int baro_x10;        /* 0.1 kPa                               */
    unsigned int tps_x10;         /* 0.1 %                                 */
    int          adv_x10;         /* 0.1 deg BTDC                          */
    unsigned int load_x10;        /* 0.1 %                                 */
    unsigned int lam_x1000;       /* lambda x1000, 0 = none                */
    unsigned int vbat_mv;         /* battery, mV                           */
    unsigned int run_s;           /* seconds since start                   */
    unsigned char mil;            /* the lamp is on                        */
    unsigned char n_dtc;          /* stored codes                          */
} hccan_obd_t;
/* the mode 01 answer for one PID into out[] (after 0x41 and the PID);
   returns its data length, 0 = not supported */
unsigned char HCCAN_FAR hccan_obd_pid(unsigned char pid, const hccan_obd_t *o,
                                      unsigned char *out);

#endif
