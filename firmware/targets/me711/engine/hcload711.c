/* Independent VE axis / density pressure / physical sensor role / ambient.
   rho=P_eff/(R*T), air=rho*Vd*VE, fuel=air/(stoich*lambda).
   The reported ratio is diagnostic ONLY; never multiplied into fuel again.
   MEDIUM/FCODE, task only; 32/16 quotients are bounded to 16 bits. */
#include "hcfarbridge.h"
#include "hctarget.h"
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hcfarinline.h"
#include "hcengine.h"
#include "hchal.h"
#include "hcfresh711.h"
#include "hcio711.h"
#include "hcdeadline711.h"
#include "hcload711.h"
#define L HC_LOAD
#define DIV(n,d) ((unsigned int)((unsigned long)(n)/(unsigned int)(d)))
extern unsigned int hc_tick_ms;
typedef char load_fits[(sizeof(hc_load_t)<=TGT_RAM_LOAD_LIMIT)?1:-1];
static unsigned int add(unsigned int a, unsigned int b) { return a > (unsigned int)(65535u-b)?65535u:a+b; }
static void put(unsigned int o,unsigned int v) {
    unsigned char huge *p=(unsigned char huge *)(TGT_EXTRAM_BASE+TGT_RAM_OCH2+o-1024u);
    p[0]=(unsigned char)(v>>8);p[1]=(unsigned char)v;
}
void hc_load_init(void) {
    unsigned char huge *p=(unsigned char huge *)&L;
    unsigned int i;
    for(i=0;i<sizeof(hc_load_t);i++) p[i]=0u;
    L.last_ms=hc_tick_ms;
}
void hc_load_select(unsigned int rpm,unsigned int tps) {
    unsigned int ref=hc_cal_u16(CFG_U_PRESSURE_REF),dt=(unsigned int)(hc_tick_ms-L.last_ms);
    unsigned int gauge,start,full,delta;
    unsigned char source=hc_cal_u8(CFG_U_BARO_SOURCE);
    L.last_ms=hc_tick_ms; L.dt_ms=dt; L.flags=0u;
    if(dt>250u) { L.flags|=HC_LOAD_TASK_GAP; L.lean_ms=L.recovery_ms=0u; }
    L.model=hc_cal_u8(CFG_U_FUEL_MODEL); L.role=hc_cal_u8(CFG_U_PRESSURE_ROLE); L.policy=hc_cal_u8(CFG_U_DENSITY_POLICY);
    L.pressure=eng_map_kpa_x10; L.pressure_age=hc_hal_ain_age(HC_AIN_MAP);
    L.pressure_ok=(unsigned int)(!(eng_sensor_err&ENG_ERR_MAP) && hc_hal_ain_ok(HC_AIN_MAP)
        && L.pressure_age<=hc_cal_u16(CFG_U_PRESSURE_TIMEOUT) && L.pressure>=100u && L.pressure<=5000u);
    if(ref<500u||ref>1200u) { ref=1013u; if(L.model) L.flags|=HC_LOAD_BAD_MODEL; }
    /* Fixed reference is usable but explicitly not a measured ambient value.
       Dedicated HOG has no qualified HAL transfer: selection falls back.
       A stopped capture is leased; age consumes once rather than revalidating
       after a 16-bit millisecond wrap. No averaging boosted running pressure. */
    if(source==1u && !rpm && L.role && L.pressure_ok && L.pressure>=500u && L.pressure<=1200u && dt<=250u) {
        L.stopped_ms=add(L.stopped_ms,dt);
        if(L.stopped_ms>=1000u) {
            L.ambient=L.pressure; L.ambient_valid=1u; L.ambient_source=1u; L.ambient_age_ms=0uL;
        }
    } else L.stopped_ms=0u;
    if(L.ambient_valid && L.ambient_source==1u) {
        if(L.ambient_age_ms<65535000uL) L.ambient_age_ms+=dt;
        if(L.ambient_age_ms>(unsigned long)hc_cal_u16(CFG_U_BARO_MAX_AGE)*1000u)
            L.ambient_valid=0u;
    }
    if(source!=1u || !L.ambient_valid) {
        L.ambient=ref; L.ambient_source=0u; L.ambient_valid=0u; L.flags|=HC_LOAD_AMBIENT_FALLBACK;
    }
    L.ambient_age_s=L.ambient_source==1u?DIV(L.ambient_age_ms,1000u):65535u;
    eng_baro_kpa_x10=L.ambient;
    L.effective=ref; L.axis=tps; L.temperature=2932u; L.blend_x1000=0u;
    if(hc_cal_u8(CFG_U_IAT_POLICY) && !(eng_sensor_err&ENG_ERR_IAT)) L.temperature=(unsigned int)(eng_iat_dc-10000u+2732u);
    else L.flags|=HC_LOAD_IAT_FALLBACK;
    if(L.model==1u) {
        if(L.policy!=0u) L.flags|=HC_LOAD_BAD_MODEL;
        if(hc_cal_u8(CFG_U_AMBIENT_CORR) && L.ambient_valid) L.effective=L.ambient;
    } else if(L.model==2u || L.model==3u) {
        if((L.model==2u && (L.role!=1u||L.policy!=1u))
            || (L.model==3u && (L.role!=2u||(L.policy!=1u&&L.policy!=2u)))) L.flags|=HC_LOAD_BAD_MODEL;
        if(!L.pressure_ok) { L.flags|=HC_LOAD_PRESSURE_LOST; L.effective=0u; }
        else if(L.policy==1u) { L.effective=L.pressure; L.blend_x1000=1000u; }
        else {
            gauge=L.pressure>L.ambient?L.pressure-L.ambient:0u;
            start=hc_cal_u16(CFG_U_BLEND_START);full=hc_cal_u16(CFG_U_BLEND_FULL);
            if(full<=start) L.flags|=HC_LOAD_BAD_MODEL;
            else {
                L.blend_x1000=gauge<=start?0u:gauge>=full?1000u:DIV((unsigned long)(gauge-start)*1000u,full-start);
                delta=L.pressure>L.ambient?L.pressure-L.ambient:0u;
                L.effective=L.ambient+DIV((unsigned long)delta*L.blend_x1000,1000u);
            }
        }
        if(L.model==2u) L.axis=L.pressure;
    } else if(L.model>3u) L.flags|=HC_LOAD_BAD_MODEL;
    if(L.flags&HC_LOAD_BAD_MODEL) { L.axis=65535u; L.effective=0u; }
    L.ratio_x1000=DIV((unsigned long)L.effective*1000u,ref);
}
void hc_load_lean_step(unsigned int rpm,unsigned int target,unsigned int measurement) {
    unsigned char loaded=(unsigned char)(rpm>=hc_cal_u16(CFG_U_LEAN_RPM)
        && eng_tps_x10>=hc_cal_u16(CFG_U_LEAN_TPS) && eng_rl_x10>=hc_cal_u16(CFG_U_LEAN_CHARGE));
    L.lambda=measurement;
    L.lean_eligible=(unsigned int)(hc_cal_u8(CFG_U_LEAN_ENABLE) && hc_cal_u8(CFG_U_LAMBDA_QUALIFIED)
        && measurement && !(L.flags&HC_LOAD_TASK_GAP) && L.dt_ms<=250u && !(eng_sensor_err&ENG_ERR_TPS1));
    if(!hc_cal_u8(CFG_U_LEAN_ENABLE)) L.lean_latched=L.lean_ms=L.recovery_ms=0u;
    else if(L.lean_eligible) {
        if(!L.lean_latched) {
            L.lean_ms=(loaded && measurement>target && measurement-target>=hc_cal_u16(CFG_U_LEAN_DEVIATION))?add(L.lean_ms,L.dt_ms):0u;
            if(L.lean_ms>=hc_cal_u16(CFG_U_LEAN_PERSIST)) L.lean_latched=1u;
        } else {
            L.recovery_ms=(!loaded && measurement<=target)?add(L.recovery_ms,L.dt_ms):0u;
            if(!rpm || L.recovery_ms>=hc_cal_u16(CFG_U_LEAN_RECOVERY)) L.lean_latched=L.lean_ms=L.recovery_ms=0u;
        }
    } else { L.lean_ms=L.recovery_ms=0u; } /* invalid cannot trigger or release */
}
void hc_load_protect(unsigned int rpm,unsigned int target) {
    unsigned int bits=0u,measurement=hc_io_lambda_protection(0u);
    if((L.model==2u||L.model==3u||hc_cal_u8(CFG_U_PRESSURE_GUARD))
        && L.role && (!L.pressure_ok || (L.flags&HC_LOAD_BAD_MODEL))
        && rpm>=hc_cal_u16(CFG_U_GUARD_RPM) && eng_tps_x10>=hc_cal_u16(CFG_U_GUARD_TPS)) bits|=ENG_CUT_LOAD;
    if(L.flags&HC_LOAD_BAD_MODEL) bits|=ENG_CUT_LOAD;
    hc_load_lean_step(rpm,target,measurement);
    if(L.lean_latched) bits|=ENG_CUT_LEAN;
    eng_fuelcut=(unsigned int)((eng_fuelcut&~(ENG_CUT_LOAD|ENG_CUT_LEAN))|bits);
    if(bits) hc_deadline_fuel_cut(); /* revoke pending and active ownership now */
}
void hc_load_publish(void) {
    unsigned int i;
    unsigned int huge *p=(unsigned int huge *)&L;
    unsigned int ref=hc_cal_u16(CFG_U_PRESSURE_REF);
    if(ref<500u || ref>1200u) ref=1013u;
    L.ratio_x1000=DIV((unsigned long)L.effective*1000u,ref);
    /* 1398..1447: 25 words, order is the public load diagnostic contract. */
    for(i=0;i<25u;i++) put((unsigned int)(1398u+2u*i),p[i]);
    put(1448u,(unsigned int)(L.base_fuel_x100>65535uL?65535uL:L.base_fuel_x100));
}
