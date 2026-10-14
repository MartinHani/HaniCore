#!/usr/bin/env python3
r"""
me711_burn_defer_proof.py - a Burn with the engine turning, on the LINKED
image (c167sim, the real hcts_cfg_burn / config manager / NVM request).

    py tests\firmware\persistence\me711_burn_defer_proof.py
    py tests\firmware\persistence\me711_burn_defer_proof.py --control   the
        2026-10-11 car image (EF8582E6): must FAIL

THE CAR (2026-10-11): TunerStudio Burns took 6.0 s (5 of 7) and one timed
out; the flash kept dbwEnable 0 while the battery-backed page said 1. Two
causes, both in the code:
  * a flash word is admitted only in a gap between crank teeth longer than
    TGT_LIVE_WORD_GUARD_US (~727 rpm on a 60-2): at idle no window ever
    opened, the Burn ran to TGT_LIVE_BURN_DEADLINE_MS and failed - after
    hc_cfg_commit() had re-sealed the standby page;
  * a driven throttle bridge is "outputs busy": with dbwEnable 1 the bridge
    holds the plate whenever the key is on and every window was refused,
    even with the engine stopped.

CASES
  D1 engine turning (1400 rpm, full sync): hcts_cfg_burn() answers TS_OK at
     once, starts NO flash transaction (NVM not STAGING/PENDING/ARMED/
     COMMITTING) and the Burn is owed (hc_cfg_mgr_burn_pending).
  D2 the owed Burn is due only after the engine has been stopped 500 ms,
     once; not while it turns.
  D3 engine stopped: hcts_cfg_burn() starts the flash transaction at once.
  D4 while that transaction runs with the engine stopped, the DBW closed
     loop is held off (hc_etbcal_burn_hold), so the bridge is not "busy".
SIMULATOR (function level on the linked image); the flash commit itself is
the persistence gates' (me711_nvm_proof, me711_burn_session_proof).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402

CONTROL_BINS = ROOT.parent / "evidence" / "OVERNIGHT_20261011" / "image_final"
if "--control" in sys.argv:
    env = dict(os.environ, HANICORE_ME711_BINS=str(CONTROL_BINS))
    r = subprocess.run([sys.executable, __file__], env=env)
    ok = r.returncode != 0
    print("\nCONTROL (EF8582E6, the 2026-10-11 car image): %s"
          % ("FAILS as it must" if ok else "PASSED - the gate cannot tell"))
    raise SystemExit(0 if ok else 1)

import me711_config_state_test as T      # noqa: E402
import me711_preset_apply_proof as AP    # noqa: E402

TRG_NO_SIGNAL, TRG_SYNC_FULL = 0, 4
NV_BUSY = {2, 3, 4, 7}       # PENDING, ARMED, COMMITTING, STAGING
FAILS = 0


def check(name, ok, detail=""):
    global FAILS
    FAILS += 0 if ok else 1
    print("  [%s] %-64s %s" % ("PASS" if ok else "FAIL", name, detail))


def has(name):
    try:
        T.sym(name)
        return True
    except BaseException:                 # T.sym exits on a missing symbol
        return False


def u8(v):
    """an unsigned char return: RL4 only (RH4 is whatever it was)"""
    return v & 0xFF


def engine(r, rpm, state):
    r.m.w16(T.sym("trg_rpm") & 0xFFFF, rpm)
    r.m.w8(T.sym("trg_state") & 0xFFFF, state)


def main() -> int:
    import me711_image as PI
    print("=== Burn with the engine turning - %s ===" % PI.image())
    r = T.boot()
    AP.press_apply(r, 3)
    AP.service(r)
    assert r("hc_cfg_mgr_commit_burn", 1, steps=60_000_000) == 0
    # the APPLY's page-refresh request (OCH 770, hctarget.h TGT_RAM_OCH)
    # holds every Burn for 1 s on purpose (preset_hold, rusEFI
    # popular_vehicle) - TunerStudio has re-read the page by now
    r.m.w8(0x380000 + 0x2000 + 770, 0)
    r.m.w8(0x380000 + 0x2000 + 771, 0)

    engine(r, 1400, TRG_SYNC_FULL)
    rc = r("hcts_cfg_burn", steps=60_000_000)
    nv = r("hc_nvm_state", steps=2_000_000)
    pend = u8(r("hc_cfg_mgr_burn_pending")) if has("hc_cfg_mgr_burn_pending") else 0
    check("D1 engine turning: TS_OK at once, no flash transaction, Burn owed",
          rc == 0 and nv not in NV_BUSY and pend == 1,
          "reply %s, NVM state %s, owed %s" % (rc, nv, pend))

    if has("hc_cfg_mgr_burn_due"):
        seq = [u8(r("hc_cfg_mgr_burn_due", 1000, 0)),     # still turning
               u8(r("hc_cfg_mgr_burn_due", 2000, 1)),     # stop first seen
               u8(r("hc_cfg_mgr_burn_due", 2300, 1)),     # 300 ms
               u8(r("hc_cfg_mgr_burn_due", 2600, 1)),     # 600 ms: due
               u8(r("hc_cfg_mgr_burn_due", 2700, 1))]     # once only
        pend2 = u8(r("hc_cfg_mgr_burn_pending"))
    else:
        seq, pend2 = None, None
    check("D2 owed Burn due once, 500 ms after the stop, never while turning",
          seq == [0, 0, 0, 1, 0] and pend2 == 0, "%s, owed after %s" % (seq, pend2))

    engine(r, 0, TRG_NO_SIGNAL)
    rc = r("hcts_cfg_burn", steps=60_000_000)
    nv = r("hc_nvm_state", steps=2_000_000)
    check("D3 engine stopped: the flash transaction starts at once",
          nv in NV_BUSY, "reply %s, NVM state %s" % (rc, nv))

    hold = u8(r("hc_etbcal_burn_hold")) if has("hc_etbcal_burn_hold") else 0
    check("D4 during it the DBW loop is held off (bridge not 'busy')",
          hold == 1, "burn hold %s" % hold)

    # D5: the owed flag lives in battery-backed SRAM (hctarget.h
    # TGT_RAM_BURNDEFER: wait u8, seen u8, stop_ms u16, magic u16). After a
    # battery loss it is random: a "1" there without the magic word must not
    # start an unrequested Burn at the next stop.
    if has("hc_cfg_mgr_burn_pending"):
        import re as _re
        hdr = (ROOT / "firmware/targets/me711/hctarget.h").read_text()
        base = int(_re.search(r"#define\s+TGT_EXTRAM_BASE\s+(0x[0-9A-Fa-f]+)",
                              hdr).group(1), 16)
        off = int(_re.search(r"#define\s+TGT_RAM_BURNDEFER\s+(0x[0-9A-Fa-f]+)",
                             hdr).group(1), 16)
        for i in range(8):
            r.m.w8(base + off + i, 0)
        r.m.w8(base + off, 1)                       # wait = 1, magic = 0
        r.m.w16(base + off + 4, 0x1234)             # a wrong magic
        p0 = u8(r("hc_cfg_mgr_burn_pending"))
        due = [u8(r("hc_cfg_mgr_burn_due", t, 1)) for t in (5000, 5600, 6200)]
        check("D5 random SRAM (wait 1, no magic) owes no Burn, never due",
              p0 == 0 and due == [0, 0, 0], "pending %s due %s" % (p0, due))
    print("\nPASS" if not FAILS else "\n%d FAIL" % FAILS)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
