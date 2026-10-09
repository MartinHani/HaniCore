/*
 * hcdtc.h - diagnostic trouble codes and the MIL request (V97, SFR-free,
 * host-tested). The target supplies a table of fault PATHS (code, debounce,
 * MIL class) and, every service pass, the raw condition of each path; this
 * core debounces, keeps history and says whether the MIL should be lit.
 *
 * Model: the OEM fault-path structure the Porsche A2L names for every path
 * (CD* codeword / CL* error class / TSF* error sum time / FFT* freeze frame,
 * e.g. CDKKRA01..FFTKRA01 for knock control at stop - SAME-FAMILY ECU
 * REFERENCE, labels only) reduced to what a standalone ECU needs, and
 * rusEFI's MIL semantics (lit while an error is ACTIVE - SOFTWARE
 * REFERENCE, malfunction_central / warning codes):
 *
 *   raw fail  --set_ms continuous-->  ACTIVE (+ STORED, count, freeze frame)
 *   ACTIVE    --heal_ms continuous clean-->  not active (STORED remains)
 *   MIL       = any ACTIVE path whose definition carries HCDTC_MIL
 *   clear     = everything, as an OBD mode 04: a still-present fault
 *               re-confirms after its set time
 *
 * A fail shorter than set_ms never confirms (the timer restarts on every
 * clean sample - an intermittent flicker is not a fault until it holds);
 * set_ms 0 confirms on the first failing sample (event paths: a sync loss).
 *
 * Storage is RAM: the history lives until a clear or a power loss. The OEM
 * keeps it in EEPROM; HaniCore's persistent store is the calibration record
 * and a DTC history there is a later decision (docs/ARCHITECTURE.md).
 */
#ifndef HCDTC_H
#define HCDTC_H

#ifdef __C166__
#define HCDTC_FAR far
#define HCDTC_MEM huge        /* the state lives in external SRAM */
#else
#define HCDTC_FAR
#define HCDTC_MEM
#endif

#define HCDTC_MAX   26u
#define HCDTC_MIL   0x01u          /* definition flag: lights the MIL       */

typedef struct {
    unsigned int  code;            /* the code, as the target numbers it   */
    unsigned int  set_ms;
    unsigned int  heal_ms;
    unsigned char flags;
} hcdtc_def_t;

#define HCDTC_S_FAIL    0x01u      /* the raw condition, last sample        */
#define HCDTC_S_ACTIVE  0x02u      /* confirmed and not healed              */
#define HCDTC_S_STORED  0x04u      /* confirmed since the last clear        */

typedef struct {
    unsigned int  t_ms;            /* set or heal timer                      */
    unsigned char st;
    unsigned char count;           /* confirmations, saturating 255         */
} hcdtc_path_t;

#define HCDTC_FF_N 4u

typedef struct {
    hcdtc_path_t  p[HCDTC_MAX];
    unsigned char mil;             /* 1 = the MIL is requested              */
    unsigned char n_active, n_stored;
    unsigned int  ff_code;         /* freeze frame: the FIRST confirmation  */
    unsigned int  ff[HCDTC_FF_N];  /*   since the clear (0 = none)          */
} hcdtc_t;

void HCDTC_FAR hcdtc_clear(hcdtc_t HCDTC_MEM *d);
/* n paths (<= HCDTC_MAX); fail[] one bit per path (bit i of word i/16);
   ff_now[] the freeze-frame values of this moment */
void HCDTC_FAR hcdtc_step(hcdtc_t HCDTC_MEM *d, const hcdtc_def_t *defs, unsigned char n,
                          const unsigned int *fail, unsigned int ms,
                          const unsigned int *ff_now);
/* the k-th code with any of the status bits in `mask`, 0 when none */
unsigned int HCDTC_FAR hcdtc_code(const hcdtc_t HCDTC_MEM *d, const hcdtc_def_t *defs,
                                  unsigned char n, unsigned char mask,
                                  unsigned char k);
/* THE PUBLISHED LISTS IN ONE PASS: the first `k_n` ACTIVE codes into act[]
   and the first `k_n` STORED codes into sto[], zero-filled. Equal to calling
   hcdtc_code() 2 x k_n times, at the cost of ONE walk of the paths - the
   eight separate scans cost a whole millisecond of the main loop on the
   C167 (me711_preset_gap_proof, V97). */
void HCDTC_FAR hcdtc_lists(const hcdtc_t HCDTC_MEM *d, const hcdtc_def_t *defs,
                           unsigned char n, unsigned int *act,
                           unsigned int *sto, unsigned char k_n);

#endif
