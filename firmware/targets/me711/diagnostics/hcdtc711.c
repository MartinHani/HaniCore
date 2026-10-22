/*
 * hcdtc711.c - diagnostic trouble codes on ME7.1.1: the fault PATHS
 * this image can actually detect, mapped onto the flags the modules already
 * keep, through the shared core (diagnostics/hcdtc.c). FCODE, hcfarbridge.h
 * first.
 *
 * A path fires only for hardware the configuration USES: a pedal fault on an
 * engine without DBW, or an IAT fault with no IAT cavity routed, is not a
 * trouble code (the engine flags say "no channel" for both - hcengine.h).
 *
 * Codes are SAE J2012 generic P0/P2 codes as DECIMAL digits (105 = P0105,
 * 2135 = P2135 - a TunerStudio readout then reads naturally), the closest
 * meaning; they are a
 * HaniCore choice, not the OEM's (the Porsche A2L names its fault paths -
 * CDK*, CLA* - but no code table for this ECU is in the repository).
 *
 * The MIL request is published (hc_dtc.mil, OCH 914 bit 0) and shown in
 * TunerStudio. It drives NO lamp yet: cavity 47 (MIL_S) is an ASIC output
 * (the W12 ME7.1.1 sheet: CJ920 from LUES2_PX70, fan stage 2 / MIL / SPOEKUE
 * variants) and has not been measured on this board (the maintainer's design notes).
 */
#include "hcfarbridge.h"
#include "hctarget.h"
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hc_config_manager.h"
#include "hctrigger.h"
#include "hcengine.h"
#include "hc_dbw.h"
#include "hcasic.h"
#include "hccel.h"
/* the lamp policy state, external SRAM (the far XRAM is full) */
#define CEL (*(hccel_t huge *)(TGT_EXTRAM_BASE + TGT_RAM_CEL))
typedef char hc_cel_fits[(sizeof(hccel_t) <= TGT_RAM_CEL_LIMIT) ? 1 : -1];
#include "hcsched_dry.h"
#include "hcio711.h"
#include "hcboost711.h"
#include "hclimp711.h"
#include "hcknock711.h"
#include "hcvvt711.h"
#include "hcengctl711.h"     /* the rail pressure sensor (HC_EC.inj_st) */
#include "hcdtc.h"
#include "hcdtc711.h"

#define STEP_MS   100u
#define EVT_HEAL  10000u            /* an event path stays active 10 s      */

enum {
    P_MAP, P_CLT, P_IAT, P_TPS1, P_TPS2, P_TPS_DIFF, P_APP1, P_APP2,
    P_APP_DIFF, P_BATT, P_ETB_MOTOR, P_ETB_DEV, P_CRANK, P_CAM, P_OVERBOOST,
    P_O2_1, P_O2_2, P_COIL, P_ASIC, P_CONFIG, P_HOT, P_ETB_LIMP,
    P_KNOCK1, P_KNOCK2, P_VVT1, P_VVT2, P_FUELP, P_N
};

static const hcdtc_def_t defs[P_N] = {
    { 105u, 1000u, 2000u, HCDTC_MIL},   /* MAP circuit                  */
    { 115u, 1000u, 2000u, HCDTC_MIL},   /* coolant temperature circuit  */
    { 110u, 1000u, 2000u, HCDTC_MIL},   /* intake air temperature       */
    { 120u,  500u, 2000u, HCDTC_MIL},   /* throttle position A          */
    { 220u,  500u, 2000u, HCDTC_MIL},   /* throttle position B          */
    {2135u,  500u, 2000u, HCDTC_MIL},   /* TPS A/B correlation          */
    {2120u,  500u, 2000u, HCDTC_MIL},   /* pedal D                      */
    {2125u,  500u, 2000u, HCDTC_MIL},   /* pedal E                      */
    {2138u,  500u, 2000u, HCDTC_MIL},   /* pedal D/E correlation        */
    { 560u, 5000u, 5000u, 0u},          /* system voltage - no MIL      */
    {2100u,    0u, 5000u, HCDTC_MIL},   /* throttle actuator motor (SF) */
    {2119u,    0u, 5000u, HCDTC_MIL},   /* throttle actuator range/perf */
    { 335u,    0u, EVT_HEAL, HCDTC_MIL},/* crank position: sync lost    */
    { 340u,    0u, EVT_HEAL, HCDTC_MIL},/* camshaft position: cycle lost*/
    { 234u,    0u, 5000u, HCDTC_MIL},   /* overboost (the fuel cut ran) */
    { 130u, 1000u, 5000u, HCDTC_MIL},   /* O2 bank 1 sensor 1           */
    { 150u, 1000u, 5000u, HCDTC_MIL},   /* O2 bank 2 sensor 1           */
    { 351u,    0u, EVT_HEAL, HCDTC_MIL},/* ignition coil: overdwell     */
    { 606u,    0u, EVT_HEAL, HCDTC_MIL},/* control module: ASIC link    */
    { 602u, 1000u, 1000u, HCDTC_MIL},   /* control module: page refused */
    { 217u,    0u, 5000u, HCDTC_MIL},   /* engine over temperature: the
                                           coolant rev limit cut fuel  */
    {2110u,    0u, 5000u, HCDTC_MIL},   /* throttle forced limited rpm */
    /* the knock sensor diagnosis (hcknock711.c): a reference outside
       the plausible range for the diagnosis count. Sensors 1/3 -> P0325,
       2/4 -> P0330 (bank 1 / bank 2 circuit). Latched by the strategy until
       a reset, so the path heals only after one. */
    { 325u,    0u, 5000u, HCDTC_MIL},   /* knock sensor 1 circuit       */
    { 330u,    0u, 5000u, HCDTC_MIL},   /* knock sensor 2 circuit       */
    /* cam phase control (hcvvt711.c): no feedback, stuck/slow, out
       of the authority, or enabled without a stage - cam 1 / cam 2 */
    {  11u,    0u, 5000u, HCDTC_MIL},   /* cam 1 timing performance     */
    {  21u,    0u, 5000u, HCDTC_MIL},   /* cam 2 timing performance     */
    /* the fuel rail pressure sensor the injector compensation reads
       (injPressMode 3, hcengctl711.c inj_pressure()): no valid reading -
       the compensation falls back to the fixed rail value meanwhile */
    { 190u, 1000u, 2000u, HCDTC_MIL},   /* fuel rail pressure sensor    */
};

typedef char hc_dtc_fits[(sizeof(hcdtc_t) <= TGT_RAM_DTC_LIMIT) ? 1 : -1];
static unsigned char cel_driven;    /* the lamp stage is configured */
unsigned int   hc_dtc_list[8];      /* active 0..3, stored 4..7, per step */
unsigned char  hc_dtc_clear_req;
static unsigned int acc_ms;
static unsigned int last_sync, last_cycle, last_asic;
static unsigned char have_last;
/* THE MAIN LOOP PASSES tick_ms - THE UPTIME, not an elapsed time (every
   service here takes now_ms, like hc_fuelpump_service()). V97 first passed
   it as elapsed ms: the controllers stepped on every pass with a huge dt,
   which me711_boot_test caught as a 34 % slower main loop. */
static unsigned int last_ms;
static unsigned char have_ms;

static unsigned int elapsed(unsigned int now_ms)
{
    unsigned int d = have_ms ? (unsigned int)(now_ms - last_ms) : 0u;
    last_ms = now_ms;
    have_ms = 1u;
    return d;
}


void far hc_dtc_init(void)
{
    hccel_reset(&CEL);        /* a boot is a key-on edge */
    hcdtc_clear(&hc_dtc);
    hc_dtc_clear_req = 0u;
    acc_ms = 0u;
    have_ms = 0u;
    {
        unsigned char k;
        for (k = 0u; k < 8u; k++) hc_dtc_list[k] = 0u;
    }
    have_last = 0u;
}

static unsigned char routed(unsigned int pin_off)
{
    unsigned char p = hc_cal_u8(pin_off);
    return (unsigned char)(p != 0u && p != HC_PIN_NONE);
}

unsigned char far hc_dtc_n(void) { return (unsigned char)P_N; }

unsigned int far hc_dtc_code(unsigned char mask, unsigned char k)
{
    return hcdtc_code(&hc_dtc, defs, (unsigned char)P_N, mask, k);
}

void far hc_dtc_service(unsigned int now_ms)
{
    unsigned int ms;
    unsigned int fail[2];
    unsigned int ff[HCDTC_FF_N];
    unsigned int e;
    unsigned int dbwf;
    unsigned char dbw_on;

    acc_ms += elapsed(now_ms);
    if (acc_ms < STEP_MS) return;
    ms = acc_ms;
    acc_ms = 0u;

    if (hc_dtc_clear_req) {                    /* '!D' - OBD mode 04 */
        /* CLEAR RESETS EVERY LATCHED FAULT (2026-10-15, owner): the codes
           AND the latches behind them, so a fixed fault does not wait for a
           key cycle - wideband, coil overdwell, knock sensor diagnosis,
           phasers, the oil protection cut. THE THROTTLE ONLY WITH THE ENGINE
           STOPPED: a cleared throttle fault re-enables the bridge, and that
           must not happen under way (the DLR key-on rule, hc_dbw_key()). A
           fault still present re-confirms after its set time. */
        hc_dtc_clear_req = 0u;
        hcdtc_clear(&hc_dtc);
        hc_io_wb_clear();                      /* a latched wideband re-arms */
        hc_ign_ovd_latch = 0u;
        hc_knock_clear_faults();
        hc_vvt_clear_faults();
        hc_limp.cut = (unsigned char)(hc_limp.cut & (0xFFu ^ HCLIMP_OIL));
        if (trg_rpm == 0u && trg_state == TRG_NO_SIGNAL) {
            hc_dbw_clear_faults();
        }
    }
    if (!have_last) {                          /* events count from here */
        last_sync = trg_synclost;
        last_cycle = trg_cycle_lost;
        last_asic = asic_timeouts;
        have_last = 1u;
    }

    e = eng_sensor_err;
    dbw_on = (unsigned char)(hc_cal_u8(CAL_DBW_ENABLE) == 1u);
    dbwf = dbw_on ? hc_dbw_faults() : 0u;
    fail[0] = 0u;
    fail[1] = 0u;
#define SETF(i, c) do { if (c) fail[(i) >> 4] |= (unsigned int)(1u << ((i) & 15)); } while (0)
    SETF(P_MAP, (e & ENG_ERR_MAP) && routed(CFG_U_PIN_MAP));
    SETF(P_CLT, (e & ENG_ERR_CLT) && routed(CFG_U_PIN_CLT));
    SETF(P_IAT, (e & ENG_ERR_IAT) && routed(CFG_U_PIN_IAT));
    SETF(P_TPS1, (e & ENG_ERR_TPS1) && routed(CFG_U_PIN_TPS1));
    SETF(P_TPS2, (e & ENG_ERR_TPS2) && dbw_on && routed(CFG_U_PIN_TPS2));
    SETF(P_TPS_DIFF, (e & ENG_ERR_TPS_DIFF) && dbw_on);
    SETF(P_APP1, (e & ENG_ERR_PEDAL1) && dbw_on && routed(CFG_U_PIN_APP1));
    SETF(P_APP2, (e & ENG_ERR_PEDAL2) && dbw_on && routed(CFG_U_PIN_APP2));
    SETF(P_APP_DIFF, (e & ENG_ERR_PED_DIFF) && dbw_on);
    SETF(P_BATT, e & ENG_ERR_BATT);
    SETF(P_ETB_MOTOR, dbwf & DBW_F_SF);
    SETF(P_ETB_DEV, dbwf & DBW_F_DEV);
    SETF(P_CRANK, trg_synclost != last_sync);
    SETF(P_CAM, trg_cycle_lost != last_cycle);
    SETF(P_OVERBOOST, hc_ldr.cut);
    SETF(P_O2_1, hc_io_wb_fault(0u) != 0u);
    SETF(P_O2_2, hc_io_wb_fault(1u) != 0u);
    SETF(P_COIL, hc_ign_ovd_latch != 0u);
    SETF(P_ASIC, asic_timeouts != last_asic);
    SETF(P_CONFIG, hc_cfg_validation != 0u);
    SETF(P_HOT, hc_limp.cut & HCLIMP_CLT);
    SETF(P_ETB_LIMP, hc_limp.cut & HCLIMP_ETB);
    SETF(P_KNOCK1, hc_knock_faults() & 0x05u);
    SETF(P_KNOCK2, hc_knock_faults() & 0x0Au);
    SETF(P_VVT1, hc_vvt_fault(0u) != VVT_F_NONE);
    SETF(P_VVT2, hc_vvt_fault(1u) != VVT_F_NONE);
    SETF(P_FUELP, (HC_EC.inj_st & EC_INJ_SENSOR) != 0u);
#undef SETF
    last_sync = trg_synclost;
    last_cycle = trg_cycle_lost;
    last_asic = asic_timeouts;

    ff[0] = trg_rpm;
    ff[1] = eng_clt_dc;
    ff[2] = eng_map_kpa_x10;
    ff[3] = eng_tps_x10;
    hcdtc_step(&hc_dtc, defs, (unsigned char)P_N, fail, ms, ff);
    /* the lists the telemetry publishes, once per step - not per main-loop
       pass (8 scans per pass cost the loop 16 %: me711_boot_test) */
    hcdtc_lists(&hc_dtc, defs, (unsigned char)P_N, &hc_dtc_list[0],
                &hc_dtc_list[4], 4u);
}

/* ------------------------------------------------ V97: the lamp policy --
   State in external SRAM (TGT_RAM_CEL): the far modules' XRAM is full. */

void far hc_cel_service(unsigned int now_ms, unsigned char key_on)
{
    unsigned char cmd;
    hccel_config(&CEL, hc_cal_u8(CFG_U_CEL_TEST_ENABLE),
                 hc_cal_u16(CFG_U_CEL_TEST_ON_MS),
                 hc_cal_u16(CFG_U_CEL_TEST_GAP_MS));
    cmd = hccel_step(&CEL, now_ms, key_on, (unsigned char)(hc_dtc.mil != 0u));
    /* THE LAMP ITSELF - only on the one stage that can (cavity 47,
       ASIC P7.0, validated in hc_validation.c), only when enabled, and only
       while no bench test owns the ASIC channel (hcio711.c gives the test
       priority). OFF is the resting state: the image bit stays SET. */
    cel_driven = (unsigned char)(hc_cal_u8(CFG_U_CEL_ENABLE) == 1u
                                 && hc_cal_u8(CFG_U_PIN_MIL) == TGT_MIL_CAV);
    hc_io_duty(HC_IO_MIL, (cel_driven && cmd) ? 1000u : 0u);
}

unsigned int far hc_cel_state(void)
{
    return (unsigned int)(CEL.mode | ((unsigned int)CEL.cmd << 8)
                          | ((hc_dtc.mil != 0u) ? 0x0200u : 0u)
                          | (cel_driven ? 0x0400u : 0u));
}
