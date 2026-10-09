#ifndef HCLOAD711_H
#define HCLOAD711_H
/* Task-owned load state; no acquisition or event work in this module. */
typedef struct {
    unsigned int model, role, policy, pressure, pressure_age, pressure_ok;
    unsigned int ambient, ambient_source, ambient_valid, ambient_age_s;
    unsigned int effective, ratio_x1000, blend_x1000, temperature, axis;
    unsigned int flags, last_ms, dt_ms, stopped_ms, ambient_rem_ms;
    unsigned int lean_ms, recovery_ms, lean_latched, lean_eligible, lambda;
    unsigned long ambient_age_ms, base_fuel_x100;
} hc_load_t;
#define HC_LOAD (*(hc_load_t huge *)(TGT_EXTRAM_BASE + TGT_RAM_LOAD))
#define HC_LOAD_BAD_MODEL 1u
#define HC_LOAD_PRESSURE_LOST 2u
#define HC_LOAD_AMBIENT_FALLBACK 4u
#define HC_LOAD_IAT_FALLBACK 8u
#define HC_LOAD_TASK_GAP 16u
void HC_COLD hc_load_init(void);
void HC_COLD hc_load_select(unsigned int rpm, unsigned int tps);
void HC_COLD hc_load_protect(unsigned int rpm, unsigned int target_lambda);
/* Decision core: production calls only with hc_io_lambda_protection().
   Linked tests inject eligibility here; no command exposes this helper. */
void HC_COLD hc_load_lean_step(unsigned int rpm,unsigned int target,unsigned int measurement);
void HC_COLD hc_load_publish(void);
#endif
