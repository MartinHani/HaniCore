#!/usr/bin/env python3
"""V42 resetless-Burn contract over the shipped ME7.1.1 sources and image.

This intentionally checks the failure mode V39 had: a TS_OK before a delayed
SRST. V40 holds that envelope, programs a bounded RAM-resident word chunk per
service pass, and releases the reply only after DONE is read back in read-array
mode.
"""
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[3]
N=(ROOT/'firmware/targets/me711/nvm/hcnvm.c').read_text()
M=(ROOT/'firmware/targets/me711/system/hcmain_me711.c').read_text()
T=(ROOT/'firmware/comms/hcts.c').read_text()
H=(ROOT/'firmware/comms/hcts.h').read_text()
checks=fails=0
def check(name, ok):
 global checks,fails; checks+=1; fails+=not ok; print(('PASS' if ok else 'FAIL'),name)
def between(s,a,b): return s[s.index(a):s.index(b)]
def main():
 payload=between(N,'void far hc_nvm_payload(void)','void far hc_nvm_payload_end(void)')
 # V47 passes live-admission facts into the same resetless transaction.
 # Match the function by name so this gate checks its behavior rather than
 # freezing an obsolete no-argument V40 signature.
 commit=between(N,'static void nvm_commit(','/* ================================================== boot-time selection')
 service=between(N,'void hc_nvm_service(','/* ================================================== what TunerStudio reads')
 check('successful RAM writer contains no CPU software reset','__asm { SRST }' not in payload)
 check('whole NVM implementation contains no successful-Burn SRST','__asm { SRST }' not in N)
 check('writer is far RAM code entered with CALLS','void far hc_nvm_payload' in payload and 'CALLS #038H, #06000H' in N)
 # V42 resets on every unresolved status path, including a chunk-entry read
 # disagreement. A stable pair of array reads is verification; a disagreement
 # is explicitly reset and returned to the main-loop retry path.
 check('writer resets and returns instead of commanding after an unsettled chunk entry','if (a != b)' in payload and '*unl1 = FL_RESET;' in payload and 'cb[CB_RESULT] = (unsigned char)HCNV_RES_RETRY;' in payload)
 # THE PROPERTY IS "EVERY UNBOUNDED LOOP LEAVES ON A NAMED ELAPSED-TICK
 # BOUND", NOT "THERE IS EXACTLY ONE OF THEM". This counted `for (;;)`
 # and required 1, so V54's bounded read-array settle loop - the one that
 # stops the writer returning into a device still driving status - failed a
 # gate whose point it satisfies. Count the BOUNDS instead.
 _inf = payload.count('for (;;) {')
 _bnd = len(re.findall(r'>=\s*\(unsigned int\)HCNV_\w+_TICKS\)', payload))
 check('writer advances a bounded record-word chunk per invocation','HCNV_PROG_CHUNK' in payload and 'words < HCNV_PROG_CHUNK' in payload and 'REC_TOTAL_WORDS; i++' not in payload)
 check('and every unbounded writer loop leaves on a named elapsed-tick bound', _inf >= 1 and _bnd == _inf)
 # The busy poll is bounded by the DATASHEET through T7, not by a loop count.
 # V40's 60000 iterations were ~30 ms of IEN-off against a 10 ms raster.
 check('busy poll is bounded by elapsed time, not by an iteration count','HCNV_POLL_TICKS' in payload and 'T7' in payload and '60000u' not in payload)
 check('busy poll remains watchdog-serviced','__asm { SRVWDT }' in payload)
 check('interrupt state is restored only after RAM writer returns','IEN = 0;' in N and 'IEN = ien;' in N)
 check('DONE is still recognised from the committed flash record','cell_scan(target) == HCNV_ERR_NONE' in commit and 'cell_last_gen_get() == cb_gen_get()' in commit)
 check('live completion rescans and selects flash source','nvm_scan();' in commit and 'nvm_select();' in commit)
 check('successful completion releases deferred TS_OK only after scan','hcts_finish_deferred_response(TS_OK);' in commit)
 check('no-op Burn releases its deferred TS_OK without consuming a cell','stage_matches_flash()' in N and 'hcts_finish_deferred_response(TS_OK);' in between(N,'if (stage_matches_flash())','cb_state = (unsigned char)HCNV_ST_PENDING'))
 check('Burn command defers its reply rather than reporting V39 early success','hcts_defer_response();' in M and 'if (deferred_response == 0u)' in T)
 check('while pending, later wire traffic cannot overtake Burn reply','if (deferred_response != 0u)' in T and 'hcts_rx_pump();' in T)
 check('runtime service invokes one bounded commit pass without reset','nvm_commit(now_ms, rpm, trig_turning, outputs_busy, page_stable);' in service and '__asm { SRST }' not in service)
 check('retry leaves the current commit pass before any re-entry','SRAMB(NVM_CB)[CB_RESULT] = 0xFFu;' in commit and 'hc_bf_stage(HCBF_ST_RETRY);\n            return;' in commit)
 check('retry target is read twice and must be NOR-compatible before reissue','static unsigned int retry_target(void)' in N and 'a = *p;\n    b = *p;' in N and '(unsigned int)(a & v) != v' in N)
 check('unexpected partial state is rejected, not blindly retried','HCNV_PF_UNSAFE' in N and 'return HCNV_ERR_PROGRAM;' in between(N,'static unsigned int retry_target(void)','/* ============================================================ the failure'))
 check('only a verified blank-or-compatible partial target reaches a retry command','NVM_RETRY_ISSUE' in commit and 'dg_set16((unsigned int)DG_RETRIES' in N)
 check('retry exhaustion is bounded and fails visibly','HCNV_PROG_TRIES' in N and 'HCNV_PF_GAVEUP' in commit and 'nvm_fail(' in commit)
 check('boot rejects a partially programmed live cell rather than resuming it','V47 never resumes a write during boot' in N and 'cb_state = (unsigned char)HCNV_ST_FAILED;' in N and 'cb_err = (unsigned char)HCNV_ERR_PROGRAM;' in N)
 check('no-op/full/interrupted semantics remain covered by append-only proof',(ROOT/'tests/firmware/persistence/me711_nvm_proof.py').exists())
 check('protocol exposes deferred reply API',all(x in H for x in ('hcts_defer_response','hcts_finish_deferred_response')))
 print(f'{checks-fails}/{checks} checks pass')
 return int(bool(fails))
if __name__=='__main__': raise SystemExit(main())
