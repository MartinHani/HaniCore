#!/usr/bin/env python3
r"""me711_burn_raster_proof.py - a Burn must not make the S5500 frames late.

    py tests\firmware\persistence\me711_burn_raster_proof.py

THE DEFECT (car 2026-10-14, reproduced on the bench the same evening)
=====================================================================
Since 2026-10-13 the S5500 exchange is clocked by the 1 ms tick at its own
interrupt level (CC27). live_admit() claims the window for each flash word
(hc_nvm_word_owned()), and asic_start_transfer() refuses a start while the
claim is held. hcasicstart.c answered that refusal like an "SSC busy":
`next_attempt = ms` - the next try a WHOLE RASTER later. Every Burn therefore
produced frame periods of exactly 20 ms (car witness: 9.82..20.00 ms, four
> 15 ms), three refusals re-initialised the SSC, the S5500 reset MAIN (long
hardware reset 0x1C) and the Burn died with 0x0105 - nothing was ever
written to flash (store generation 8 all day, nvmCommits 0).

THE GATE runs edit -> Burn on the modelled ECU and takes every runtime frame
START (hc_asic_run_tx moving) during the Burn. The worst start-to-start
period must stay within the raster plus one tick, and the Burn must answer
TS_OK. THE CONTROL is the frozen car image 5248F4C9 (the image that failed in
the car): it must show a period of at least 1.5 rasters, or this gate has not
measured the thing it claims to.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402
import me711_heartbeat_gap_proof as HB                          # noqa: E402
import me711_image as PI                                        # noqa: E402
import me711_ts_gap_proof as GAP                                # noqa: E402
import me711_burn_session_proof as BS                           # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
CONTROL = (ROOT.parent / "evidence" / "CAR_20261013_RESETS"
           / "CAR_KIT_20261014_5248F4C9" / "bins" / "hanicore")
CONTROL_SHA = "5248F4C947AF549A7FAEB8A9E7113A1B03392720F6B59647F6162DFADCD7B641"
RASTER_MS = 10.0
BURN_LIMIT_MS = 9000

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-62s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def burn(img, mapfile, p3_off):
    """edit -> Burn. -> (worst frame period ms during the Burn, frames,
    Burn reply code or None, trap)."""
    entry = BS.map_sym(mapfile, "hc_asic_start_service")
    tick = BS.map_sym(mapfile, "hc_tick_ms")
    run_tx = BS.map_sym(mapfile, "hc_asic_run_tx")

    probe = HB.Rig(img, entry, tick, echo=True,
                   steps_per_tick=HB.STEPS_PER_TICK)
    probe.run(GAP.BOOT_WARMUP_STEPS)
    first, last = probe.entries[0], probe.entries[-1]
    per_ms = (last[1] - first[1]) / ((last[0] - first[0]) & 0xFFFF)
    ms = lambda n: int(n * per_ms)                              # noqa: E731

    rig = HB.Rig(img, entry, tick, echo=True, run_tx_addr=run_tx,
                 steps_per_tick=HB.STEPS_PER_TICK)
    rig.run(GAP.BOOT_WARMUP_STEPS + ms(GAP.SETTLE_MS))

    edit = BS.envelope(b"W" + p3_off.to_bytes(2, "big") + bytes([0x5A]))
    rig.queue_rx(rig.cpu.steps + 1, edit)
    deadline = rig.cpu.steps + ms(800)
    base = len(rig.tx)
    while rig.cpu.steps < deadline and rig.trap is None:
        rig.run(min(ms(1), deadline - rig.cpu.steps))
        st = bytes(v for _t, v in rig.tx[base:])
        if [f for _a, _e, f in BS.frames(st) if len(f) == 1]:
            break

    start = len(rig.tx)
    sent_at = rig.cpu.steps + 1
    rig.queue_rx(sent_at, BS.envelope(b"B"))
    deadline = rig.cpu.steps + ms(BURN_LIMIT_MS)
    code = None
    while rig.cpu.steps < deadline and rig.trap is None:
        rig.run(min(ms(2), deadline - rig.cpu.steps))
        one = [f for _a, _e, f in BS.frames(bytes(v for _t, v in rig.tx[start:]))
               if len(f) == 1]
        if one:
            code = one[0][0]
            break
    end_at = rig.cpu.steps
    starts = [s for _t, s, _n in rig.run_tx_events if sent_at <= s <= end_at]
    gaps = [(b - a) / per_ms for a, b in zip(starts, starts[1:])]
    return (max(gaps) if gaps else None), len(starts), code, rig.trap


def main():
    print("=== a Burn must not make the S5500 frames late ===\n")
    p3_off = BS.p3_offset()
    img = PI.image()
    print("  image   %s  %s" % (img.name, PI.sha256()[:16]))
    worst, n, code, trap = burn(img, PI.MAP, p3_off)
    check("no trap across the Burn", trap is None, str(trap))
    check("the Burn answers TS_OK", code == BS.TS_OK,
          "no reply" if code is None else "0x%02X" % code)
    check("runtime frames keep starting during the Burn", n >= 3,
          "%d frame starts" % n)
    check("worst frame period <= raster + 1 tick (%.0f ms)" % (RASTER_MS + 1),
          worst is not None and worst <= RASTER_MS + 1.0,
          "worst %s ms" % ("-" if worst is None else "%.2f" % worst))

    print("\n  --- control: the car image 5248F4C9 ---")
    cimg = CONTROL / "HaniCore_ME711_v102_dev.bin"
    cmap = CONTROL / "HaniCore_ME711_v102_dev.M66"
    if not (cimg.exists() and cmap.exists()):
        check("the control image is present", False, str(cimg))
    else:
        import hashlib
        check("the control is the car image",
              hashlib.sha256(cimg.read_bytes()).hexdigest().upper()
              == CONTROL_SHA)
        cw, cn, ccode, ctrap = burn(cimg, cmap, p3_off)
        check("the control skips a raster during its Burn (>= 15 ms)",
              cw is not None and cw >= 1.5 * RASTER_MS,
              "worst %s ms over %d starts, reply %s, trap %s"
              % ("-" if cw is None else "%.2f" % cw, cn,
                 "none" if ccode is None else "0x%02X" % ccode, ctrap))

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("BURN RASTER PROOF FAILED")
        return 1
    print("BURN RASTER PROOF PASSES - the S5500 keeps its raster through a Burn.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
