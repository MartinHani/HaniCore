#!/usr/bin/env python3
r"""me711_cam_absent_burn_proof.py - a cam nobody described cannot be missing.

    py tests\firmware\persistence\me711_cam_absent_burn_proof.py

THE FAILURE THIS GATE EXISTS FOR, MEASURED ON HARDWARE 2026-09-15
-----------------------------------------------------------------
V55 is the first HaniCore build whose crank has ever turned on this ECU. With
the bench generator at ~200 rpm and NO CAM CONNECTED, TunerStudio reported
`Burn page 0 failed` over and over, and after several of those the session went
sluggish and began reconnecting. A Burn at rpm 0 still worked.

The chain, and every link is in this repository:

    trg_service()  after five synced revolutions, sets trg_cam_error bits 2
                   and 3 - MISSING CAM - for BOTH banks, unconditionally.
                   Nothing clears them except trg_init().
        |
    hcnvm.c live_admit()  rejects EVERY flash window on `trg_cam_error != 0`,
                   but only while `rpm != 0 || trig_turning != 0`.
        |
    the Burn      never places a word, dies on its deadline, and the deferred
                   reply TunerStudio is waiting 8000 ms for never arrives.

**That clause had never been reachable.** Until V55 no crank signal had reached
this board, `trg_state` never passed TRG_COUNTING, and `trg_cam_error` was zero
for the entire life of the project - which is why every live-Burn gate in this
tree passes and always did. They all run with the decoder idle. That is the
vacuity the project rules warn about, and it took a real crank signal to expose it.

WHAT THIS GATE ASSERTS
----------------------
All of it by driving the LINKED IMAGE's own `trg_service()` and `crank_edge()`.

  1. **THE REGRESSION ITSELF.** Crank synced, many revolutions, no cam
     configured -> `trg_cam_error` MUST be 0, because that is the single
     precondition `live_admit()` needs from this file while the engine turns.
     This check FAILS against the V55 image as flashed.

  2. **THE DIAGNOSTIC SURVIVES.** A cam that IS configured - enabled, with
     references, and named by the sync mode - and then never arrives MUST
     still raise its missing bit. A fix that simply deleted the fault would
     pass check 1 and fail this one.

  3. **PER BANK.** An engine described as having one cam must not be told its
     second cam is missing. That was the second half of the defect.

  4. **IT CLEARS.** The bits latched for the whole power cycle. A cam that
     comes back must clear its own bit, and losing crank sync must clear both -
     "revolutions since the last cam edge" is meaningless without a revolution
     count.

  5. **AN UNDESCRIBED CAM EDGE IS NOT A WINDOW FAULT.** With no configured
     references there are no windows, so an arriving edge cannot be outside
     one. It is counted and reported, and it is not evidence of a fault.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_trigger_test as T                                   # noqa: E402
import me711_trigger_generic_proof as G                          # noqa: E402

FAIL = 0

# hcnvm.c live_admit(): while the engine turns, ANY non-zero trg_cam_error is
# an explicit reject. This is the number that matters, and it is why check 1
# asserts equality with zero rather than "no missing bits".
CAM_ERR_MASK_THAT_BLOCKS_A_BURN = 0xFFFF


def check(name, ok, detail=""):
    global FAIL
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<58} {detail}")
    FAIL += not ok


def spun(revs=12, **kw):
    """A 60-2 at 800 rpm, synced, with `revs` revolutions behind it."""
    w = G.Wheel(60, 2, 800, **kw)
    w.run(revs)
    return w


def main():
    print("=== a cam nobody described cannot be missing ===\n")

    # ---- 1. the regression, in the exact configuration the bench is in -----
    # camEnable is 1 by default in hcconfig.c, CFG_U_CAM_REFS is 0 in a freshly
    # flashed page, nothing is wired to NWDG1/NWDG2. Exactly the reference bench.
    w = spun(12, cam_refs=0, cam_enable=1, cam_sync_mode=0)
    rev = w.u16("trg_rev")
    err = w.u16("trg_cam_error")
    check("crank sync was actually reached, so this is not vacuous",
          w.u8("trg_state") >= 3 and rev > 4,
          f"state={w.u8('trg_state')} revs={rev}")
    check("NO cam configured, crank turning: camError is CLEAN",
          (err & CAM_ERR_MASK_THAT_BLOCKS_A_BURN) == 0,
          f"camError=0x{err:04X} after {rev} revolutions - live_admit() "
          f"rejects every flash window on any non-zero value")
    check("and no cam loss reason is standing either",
          w.u16("trg_cam_loss_reason") == 0,
          f"camSyncLossReason={w.u16('trg_cam_loss_reason')}")

    # ---- 2. the diagnostic still works when a cam IS described -------------
    # One reference, sync mode CAM1: the configuration says this engine HAS a
    # cam on bank 1. It never arrives, and that must still be a fault.
    w = spun(12, cam_refs=1, cam_ref_x10=0, cam_window_x10=1700,
             cam_sync_mode=2, cam_enable=1)
    err = w.u16("trg_cam_error")
    check("a DESCRIBED cam that never arrives still raises MISSING",
          (err & 4) != 0,
          f"camError=0x{err:04X}, bank 1 missing bit expected")
    check("and it is named",
          w.u16("trg_cam_loss_reason") == 7,
          f"camSyncLossReason={w.u16('trg_cam_loss_reason')}, want 7 "
          f"(TRG_LOSS_CAM_MISSING)")

    # ---- 3. per bank: one cam engine, one cam fault ------------------------
    check("an engine described with ONE cam is not told cam 2 is missing",
          (err & 8) == 0,
          f"camError=0x{err:04X}, bank 2 missing bit must be clear")

    # ---- 4. it clears --------------------------------------------------
    # 4a: the cam comes back.
    w.x.call("trg_test_cam_edge", 1)
    err2 = w.u16("trg_cam_error")
    check("a cam that returns clears its own missing bit",
          (err2 & 4) == 0,
          f"camError 0x{err:04X} -> 0x{err2:04X}")

    # 4b: losing crank sync clears both, because the revolution count that
    #     the fault is measured in has stopped meaning anything.
    w = spun(12, cam_refs=1, cam_ref_x10=0, cam_window_x10=1700,
             cam_sync_mode=2, cam_enable=1)
    check("the missing fault is standing before the signal stops",
          (w.u16("trg_cam_error") & 12) != 0,
          f"camError=0x{w.u16('trg_cam_error'):04X}")
    # Let the stall timeout run: service with no edges until NO_SIGNAL.
    t = w.t
    # CFG_TRIG_TIMEOUT_MS is 200 and T1 is 1.25 MHz, so the stall needs
    # 250000 ticks of no edges. Step in 5000s and give it plenty.
    for i in range(1, 140):
        w.service((t + i * 5000) & 0xFFFF)
        if w.u8("trg_state") == 0:
            break
    check("the crank stall was actually reached", w.u8("trg_state") == 0,
          f"state={w.u8('trg_state')}")
    check("losing crank sync clears the missing bits",
          (w.u16("trg_cam_error") & 12) == 0,
          f"camError=0x{w.u16('trg_cam_error'):04X}")

    # ---- 4c. AND THE RPM MUST ACTUALLY RETURN TO ZERO ---------------------
    # Measured on the bench 2026-09-15: generator stopped, syncState 0,
    # stallState 1, and rpm still reading 199 for ever, because trg_crank_period
    # was left standing and trg_service() recomputes the rpm from it on the way
    # out. rpm == 0 is the precondition for applying an RPM_ZERO configuration
    # edit, for every bounded bench output, and for hcnvm.c's live_admit() -
    # which is why one burst of crank signal disabled the Burn for the rest of
    # the power cycle even after the crank had stopped.
    w = spun(8, cam_refs=0, cam_enable=1, cam_sync_mode=0)
    check("the rpm is non-zero while the crank turns",
          w.u16("trg_rpm") > 0, f"rpm={w.u16('trg_rpm')}")
    t = w.t
    for i in range(1, 140):
        w.service((t + i * 5000) & 0xFFFF)
        if w.u8("trg_state") == 0:
            break
    check("the stall was reached", w.u8("trg_state") == 0,
          f"state={w.u8('trg_state')} stall={w.u16('trg_stall_state')}")
    # One more service call: the old code cleared trg_rpm inside the stall
    # branch and then put it straight back at the bottom of the SAME call.
    w.service((t + 141 * 5000) & 0xFFFF)
    check("and the rpm actually returns to ZERO and STAYS there",
          w.u16("trg_rpm") == 0 and w.u32("trg_crank_period") == 0,
          f"rpm={w.u16('trg_rpm')} crankPeriod={w.u32('trg_crank_period')}")

    # ---- 5. an undescribed cam edge is not a window fault ------------------
    w = spun(6, cam_refs=0, cam_enable=1, cam_sync_mode=0)
    before = w.u16("trg_cam1_edges")
    w.x.call("trg_test_cam_edge", 1)
    check("an edge on an undescribed cam is still COUNTED",
          w.u16("trg_cam1_edges") == before + 1,
          f"cam1Edges {before} -> {w.u16('trg_cam1_edges')}")
    check("but it is not a window fault - there are no windows",
          (w.u16("trg_cam_error") & 3) == 0
          and w.u16("trg_cam_loss_reason") == 0,
          f"camError=0x{w.u16('trg_cam_error'):04X} "
          f"reason={w.u16('trg_cam_loss_reason')}")
    check("and it did not cost the crank its sync",
          w.u8("trg_state") >= 3, f"state={w.u8('trg_state')}")

    # ---- 6. a described cam edge in the WRONG place is still a fault -------
    # The window rule must not have been softened along with the missing rule.
    w = spun(6, cam_refs=1, cam_ref_x10=0, cam_window_x10=50,
             cam_sync_mode=2, cam_enable=1)
    while not (900 <= w.u16("trg_engine_deg_x10") % 3600 <= 1100):
        w.wait_edge(w.p)
    w.x.call("trg_test_cam_edge", 1)
    check("a DESCRIBED cam edge outside every window is still a fault",
          (w.u16("trg_cam_error") & 1) == 1
          and w.u16("trg_cam_loss_reason") == 6,
          f"camError=0x{w.u16('trg_cam_error'):04X} "
          f"reason={w.u16('trg_cam_loss_reason')}")

    print("\nall checks pass" if not FAIL else f"\n{FAIL} failure(s)")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
