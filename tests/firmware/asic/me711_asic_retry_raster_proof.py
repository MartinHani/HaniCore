#!/usr/bin/env python3
r"""me711_asic_retry_raster_proof.py - a bad S5500 reply must not make the
next frame late.

    py tests\firmware\asic\me711_asic_retry_raster_proof.py

THE DEFECT (car 2026-10-15, 487AC54F; .scratch/firmware-stability issue 01)
=========================================================================
Every runtime checksum error came with exactly one frame period > 11 ms
(12.0..12.9 ms) and one UMKOM mismatch: hcasicstart.c anchored the retry at
the moment the failure was SEEN (`next_attempt = ms`), so the next frame
started a whole period after detection = start + transfer + 10 ms. Late
frames are what reset MAIN on 2026-10-13. The OEM drops a bad reply and sends
the next frame on its own raster slot [BIN 0x8BEAB4 / 0x8BEAE8].

THE GATE runs the image on the modelled ECU, corrupts ONE runtime reply's
checksum and measures the start-to-start period from that frame to the next
(hc_asic_run_tx moving). It must be within the raster + 0.5 ms. THE CONTROL
is the frozen car image 487AC54F: it must show >= raster + 1 ms, or this gate
has not measured the thing it claims to. (The rig completes an exchange
inside the SSCTIC write, so the control's period is detection + 10 = about
11 ms here, where the real 1.9 ms transfer made it 12-13 ms on the car.)
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402
import me711_heartbeat_gap_proof as HB                          # noqa: E402
import me711_image as PI                                        # noqa: E402
import me711_ts_gap_proof as GAP                                # noqa: E402
import me711_burn_session_proof as BS                           # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
CONTROL = ROOT.parent / "evidence" / "BENCH_20261015_487AC54F" / "frozen"
CONTROL_SHA = "487AC54F"
RASTER_MS = 10.0

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-62s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


LAST_CAPTURE = {}


def capture(rig):
    """The bad-reply capture (TGT_RAM_ASICBAD, issue 02) as the firmware left
    it: (header words, frame words)."""
    base = HB._define("TGT_EXTRAM_BASE") + HB._define("TGT_RAM_ASICBAD")
    words = [rig.mem.r16(base + 2 * i) for i in range(16 + HB.WORDS_RUN)]
    return words[:16], words[16:]


def one_bad_reply(img, mapfile):
    """-> (period after the bad frame ms, worst period of the rest ms,
    checksum errors counted by the firmware, trap)."""
    entry = BS.map_sym(mapfile, "hc_asic_start_service")
    tick = BS.map_sym(mapfile, "hc_tick_ms")
    run_tx = BS.map_sym(mapfile, "hc_asic_run_tx")
    csum = BS.map_sym(mapfile, "hc_asic_run_csum_err")

    rig = HB.Rig(img, entry, tick, echo=True, run_tx_addr=run_tx,
                 steps_per_tick=HB.STEPS_PER_TICK)
    rig.corrupt_runtime, rig.corrupt_steps = 0, []
    rig.run(GAP.BOOT_WARMUP_STEPS)
    first, last = rig.entries[0], rig.entries[-1]
    per_ms = (last[1] - first[1]) / ((last[0] - first[0]) & 0xFFFF)
    rig.run(int(GAP.SETTLE_MS * per_ms))
    before = rig.mem.r16(csum)
    rig.corrupt_runtime = 1
    rig.run(int(60 * per_ms))
    errors = (rig.mem.r16(csum) - before) & 0xFFFF
    LAST_CAPTURE["hdr"], LAST_CAPTURE["frame"] = capture(rig)
    if not rig.corrupt_steps:
        return None, None, errors, rig.trap or "no runtime frame was corrupted"
    bad = rig.corrupt_steps[0]
    starts = [s for _t, s, _n in rig.run_tx_events]
    # hc_asic_run_tx counts a start just AFTER the SSCTIC write the rig
    # corrupted, so the bad frame is the first start at or after it
    at = min(i for i, s in enumerate(starts) if s >= bad)
    if at + 1 >= len(starts):
        return None, None, errors, rig.trap or "no frame after the bad one"
    after = (starts[at + 1] - starts[at]) / per_ms
    rest = [(b - a) / per_ms for a, b in zip(starts, starts[1:])
            if a != starts[at] and b > starts[0]]
    return after, (max(rest) if rest else None), errors, rig.trap


def main():
    print("=== a bad S5500 reply must not make the next frame late ===\n")
    img = PI.image()
    print("  image   %s  %s" % (img.name, PI.sha256()[:16]))
    after, rest, errors, trap = one_bad_reply(img, PI.MAP)
    check("no trap", trap is None, str(trap))
    check("the firmware counted the bad reply", errors == 1,
          "%d checksum error(s)" % errors)
    check("next frame <= raster + 0.5 ms after the bad one",
          after is not None and after <= RASTER_MS + 0.5,
          "%s ms" % ("-" if after is None else "%.2f" % after))
    check("and the raster around it holds (<= raster + 0.5 ms)",
          rest is not None and rest <= RASTER_MS + 0.5,
          "worst other %s ms" % ("-" if rest is None else "%.2f" % rest))

    hdr, frame = LAST_CAPTURE["hdr"], LAST_CAPTURE["frame"]
    n = HB.WORDS_RUN
    want_sum = sum(frame[:n - 1]) & 0xFFFF
    check("issue 02: one capture, the sums as the firmware saw them",
          hdr[15] == 0x4241 and hdr[0] == 1 and hdr[3] == want_sum
          and hdr[4] == (want_sum ^ 0x0101),
          "count %d calc %04X recv %04X (frame sums to %04X)"
          % (hdr[0], hdr[3], hdr[4], want_sum))
    check("issue 02: the whole rejected frame was copied out",
          hdr[9] == n and frame[0] == (0x7800 | 0x2E) and frame[n - 1] == hdr[4],
          "words %d, w0 %04X, last %04X" % (hdr[9], frame[0], frame[n - 1]))

    print("\n  --- control: the car image 487AC54F ---")
    cimg = CONTROL / "HaniCore_ME711_v102_dev.bin"
    cmap = CONTROL / "HaniCore_ME711_v102_dev.M66"
    if not (cimg.exists() and cmap.exists()):
        check("the control image is present", False, str(cimg))
    else:
        check("the control is the car image",
              hashlib.sha256(cimg.read_bytes()).hexdigest().upper()
              .startswith(CONTROL_SHA))
        cafter, _r, cerr, ctrap = one_bad_reply(cimg, cmap)
        check("the control's next frame is late (>= raster + 1 ms)",
              cafter is not None and cafter >= RASTER_MS + 1.0,
              "%s ms, %d error(s), trap %s"
              % ("-" if cafter is None else "%.2f" % cafter, cerr, ctrap))

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("ASIC RETRY RASTER PROOF FAILED")
        return 1
    print("ASIC RETRY RASTER PROOF PASSES - a bad reply keeps the raster.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
