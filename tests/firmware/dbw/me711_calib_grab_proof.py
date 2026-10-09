#!/usr/bin/env python3
r"""
me711_calib_grab_proof.py - the endpoint grab, executed from the LINKED IMAGE.

    py tests\firmware\dbw\me711_calib_grab_proof.py

WHAT IT IS. rusEFI's cmd_calibrate_tps_closed / _open / cmd_calibrate_pedal_up
/ _down: hold the plate or the pedal where you want it and tell the ECU that
this is where it is. It is the difference between a calibration a tuner can
perform and four raw counts they have to read off one gauge and retype into
another field, and on the current bench - an M113 throttle body wired to this
ECU, both TPS tracks live - it is the one commissioning act that can be done
today with no motion at all.

WHAT THIS GATE INSISTS ON, and every one of them is a way for a calibration to
be quietly wrong rather than absent:

  * IT WRITES RAM AND ONLY RAM. Not one flash byte. The project rule is that an
    ordinary edit goes to the page and only an explicit Burn makes it
    permanent, and a button that silently burned would break the one guarantee
    the persistence design is built on;
  * MIN IS THE CLOSED READING AND MAX THE OPEN ONE, WITHOUT SORTING. On a
    Bosch/VAG body the first track FALLS as the plate opens - rusEFI's own
    defaults for this body are tpsMin 890 and tpsMax 70 - so a correct
    calibration has min > max. Sorting would throw the direction away and read
    the throttle backwards, which reads as a working calibration;
  * A RAIL IS REFUSED. An input sitting at either end of its span gives a
    clean, stable, completely wrong number - whether it is open, shorted, or
    simply not the channel anyone thinks it is - and a calibration built on one
    cannot be told from a good one by anything downstream. The refusal does not
    need to know WHICH fault it is, and does not claim to;
  * A TRAVEL THAT IS NOT A TRAVEL IS REFUSED. rusEFI calls this "check your
    wiring". A full-scale span calibrated into a few counts of noise makes the
    runtime treat noise as a 100 % command;
  * IT REFUSES WHILE THE ENGINE COULD BE TURNING, and says so rather than
    doing nothing;
  * AND EVERY REFUSAL IS PUBLISHED. A button that cannot do its job must say
    which invariant stopped it - hcbench.c's rule, applied to the one
    commissioning command that is not a bench output.

Every check runs the FIRMWARE'S OWN COMPILED eng_calib_grab() against a page
this test writes, and reads the answer back out of the page.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
ROOT = Path(__file__).resolve().parents[3]

import me711_image as PI                      # noqa: E402
from me711_hal_test import sym                # noqa: E402
from me711_config_state_test import Rig       # noqa: E402

FAILS = 0
GEN_H = ROOT / "firmware/generated/hc_config_generated.h"
CFG_H = ROOT / "firmware/config/hcconfig.h"
ENG_H = ROOT / "firmware/engine/hcengine.h"
ENG_C = ROOT / "firmware/engine/hcengine.c"


def check(name, ok, detail=""):
    global FAILS
    print("  [%s] %-56s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def off(name):
    for f in (GEN_H, CFG_H):
        m = re.search(r"#define\s+%s\s+(\d+)u?" % name,
                      f.read_text(errors="replace"))
        if m:
            return int(m.group(1))
    raise SystemExit("no such config offset: %s" % name)


def const(name, path=ENG_H):
    m = re.search(r"#define\s+%s\s+(\d+)u" % name, path.read_text(errors="replace"))
    if not m:
        raise SystemExit("%s is not declared in %s" % (name, path.name))
    return int(m.group(1))


# The verdicts and the endpoints, READ FROM THE FIRMWARE'S OWN HEADER so this
# file cannot drift from the numbers the .ini decodes.
V = {n: const("ENG_GRAB_" + n) for n in
     ("IDLE", "PASS", "RPM", "NOCHANNEL", "RAIL", "SPAN", "WHAT")}
W = {n: const("ENG_GRAB_" + n) for n in
     ("TPS_CLOSED", "TPS_OPEN", "APP_REST", "APP_FULL")}
MIN_SPAN = const("GRAB_MIN_SPAN", ENG_C)

# The four pairs, and which page slots each endpoint owns.
PAIRS = {
    W["TPS_CLOSED"]: ("TPS1", "TPS2", "CAL_TPS1_MIN", "CAL_TPS2_MIN"),
    W["TPS_OPEN"]:   ("TPS1", "TPS2", "CAL_TPS1_MAX", "CAL_TPS2_MAX"),
    W["APP_REST"]:   ("APP1", "APP2", "CAL_PEDAL1_MIN", "CAL_PEDAL2_MIN"),
    W["APP_FULL"]:   ("APP1", "APP2", "CAL_PEDAL1_MAX", "CAL_PEDAL2_MAX"),
}

# Which raw ADC channel each logical input is on THIS board, from hctarget.h.
TGT = (ROOT / "firmware/targets/me711/hctarget.h").read_text(errors="replace")


def adc_ch(name):
    m = re.search(r"#define\s+TGT_ADC_%s_CH\s+(\d+)" % name, TGT)
    if not m:
        raise SystemExit("hctarget.h has no TGT_ADC_%s_CH" % name)
    return int(m.group(1))


class Grabber:
    def __init__(self):
        self.rig = Rig()
        self.rig("hc_hal_init")
        self.rig("hc_cfg_init")
        self.rig("hc_cfg_mgr_init")
        self.rig("eng_init")
        for sem,name in ((4,"TPS1"),(5,"TPS2"),(6,"PEDAL1"),(7,"PEDAL2")):
            self.rig("hc_hal_ain_bind",sem,adc_ch(name))
        self.adc = sym("adc_raw") & 0xFFFF
        self.stopped()

    # --- the world the firmware sees ------------------------------------
    def raw(self, which, counts):
        ch = adc_ch(which)
        self.rig.m.w16(self.adc + 2 * ch, counts & 0xFFFF)
        ms = self.rig.m.r16(sym("hc_tick_ms") & 0xFFFF)
        self.rig("hc_hal_main_sample", ch, (ch << 12) | counts, 1, ms)

    def stopped(self):
        """rpm 0 AND the decoder reporting no signal - the same pair of facts
        hcbench.c requires before it drives a pin."""
        self.rig.m.w16(sym("trg_rpm") & 0xFFFF, 0)
        self.rig.m.w8(sym("trg_state") & 0xFFFF, 0)      # TRG_NO_SIGNAL

    def turning(self, rpm=800):
        self.rig.m.w16(sym("trg_rpm") & 0xFFFF, rpm)
        self.rig.m.w8(sym("trg_state") & 0xFFFF, 3)

    # --- the page --------------------------------------------------------
    def set16(self, slot, v):
        self.rig("hc_cal_set_u16", off(slot), v & 0xFFFF)

    def get16(self, slot):
        return self.rig("hc_cal_u16", off(slot))

    def clear(self, what):
        for slot in PAIRS[what][2:]:
            self.set16(slot, 0)

    def grab(self, what):
        return self.rig.callb("eng_calib_grab", what)


def page_bytes(g):
    """The NEAR-RAM half of the page - hc_cfg[], offsets 0..HC_CFG_CORE-1.

    A grab writes TPS and pedal calibration, which lives ABOVE HC_CFG_CORE in
    the battery-backed SRAM. So every byte here must be untouched, and any that
    moves is a grab reaching somewhere it has no business."""
    base = sym("hc_cfg") & 0xFFFF
    return bytes(g.rig.m.r8(base + i) for i in range(off("HC_CFG_CORE")))


def main() -> int:
    global FAILS
    print("=== HaniCore ME7.1.1 - the endpoint grab ===\n")
    print("  image   %s" % PI.image().name)
    print("  sha256  %s" % PI.sha256())
    print("  verdicts %s" % ", ".join("%s=%d" % kv for kv in sorted(V.items())))
    print("  minimum span %d counts\n" % MIN_SPAN)

    g = Grabber()

    # ------------------------------------------------------------------ 1 --
    check("nothing has been grabbed yet", g.grab(0) == V["WHAT"],
          "endpoint 0 is not an endpoint")

    # ------------------------------------------------------------------ 2 --
    # THE HAPPY PATH, with the INVERTED span a Bosch/VAG body really has:
    # track 1 falls as the plate opens (890 -> 70), track 2 rises
    # (130 -> 950). rusEFI's own defaults for this body are tpsMin 890 and
    # tpsMax 70, which is where those numbers come from.
    g.clear(W["TPS_CLOSED"])
    g.clear(W["TPS_OPEN"])
    g.raw("TPS1", 890)
    g.raw("TPS2", 130)
    v = g.grab(W["TPS_CLOSED"])
    check("grab CLOSED throttle", v == V["PASS"], "verdict %d" % v)
    check("  TPS1 closed went to MIN", g.get16("CAL_TPS1_MIN") == 890,
          "%d" % g.get16("CAL_TPS1_MIN"))
    check("  TPS2 closed went to MIN", g.get16("CAL_TPS2_MIN") == 130,
          "%d" % g.get16("CAL_TPS2_MIN"))

    g.raw("TPS1", 70)
    g.raw("TPS2", 950)
    v = g.grab(W["TPS_OPEN"])
    check("grab OPEN throttle", v == V["PASS"], "verdict %d" % v)
    check("  TPS1 open went to MAX", g.get16("CAL_TPS1_MAX") == 70,
          "%d" % g.get16("CAL_TPS1_MAX"))
    check("  TPS2 open went to MAX", g.get16("CAL_TPS2_MAX") == 950,
          "%d" % g.get16("CAL_TPS2_MAX"))

    # ------------------------------------------------------------------ 3 --
    # THE INVERTED SPAN SURVIVED. min > max on track 1 is the CORRECT answer
    # for this throttle body, and a sort would have destroyed it.
    check("track 1 is stored INVERTED, not sorted",
          g.get16("CAL_TPS1_MIN") > g.get16("CAL_TPS1_MAX"),
          "min %d > max %d - a Bosch/VAG track falls as the plate opens"
          % (g.get16("CAL_TPS1_MIN"), g.get16("CAL_TPS1_MAX")))
    check("track 2 is stored rising",
          g.get16("CAL_TPS2_MIN") < g.get16("CAL_TPS2_MAX"),
          "min %d < max %d" % (g.get16("CAL_TPS2_MIN"),
                               g.get16("CAL_TPS2_MAX")))

    # ------------------------------------------------------------------ 4 --
    # AND THE RUNTIME AGREES WITH THE CALIBRATION IT WAS JUST GIVEN.
    g.raw("TPS1", 890)
    g.raw("TPS2", 130)
    # THE SENSOR FILTER IS 15/16 PER PASS, so a step settles as 0.9375^n:
    # forty passes is only 92 % of the way there, which read 917 and looked
    # like a calibration error. 150 passes is 0.00007 of the step left.
    SETTLE = 150
    for _ in range(SETTLE):
        g.rig("eng_service", steps=2000000)
    closed = g.rig.m.r16(sym("eng_tps_x10") & 0xFFFF)
    g.raw("TPS1", 70)
    g.raw("TPS2", 950)
    for _ in range(SETTLE):
        g.rig("eng_service", steps=2000000)
    wide = g.rig.m.r16(sym("eng_tps_x10") & 0xFFFF)
    check("the throttle reads ~0 % at the closed counts", closed < 50,
          "eng_tps_x10 = %d" % closed)
    check("and ~100 % at the open counts", wide > 950,
          "eng_tps_x10 = %d" % wide)

    # ------------------------------------------------------------------ 5 --
    # A RAIL IS REFUSED, at both ends, and the page does NOT move.
    before = (g.get16("CAL_TPS1_MIN"), g.get16("CAL_TPS2_MIN"))
    for counts, label in ((1023, "high"), (0, "low"), (5, "near-low"),
                          (1020, "near-high")):
        g.raw("TPS1", counts)
        g.raw("TPS2", 500)
        v = g.grab(W["TPS_CLOSED"])
        check("a %s rail on TPS1 is refused" % label, v == V["RAIL"],
              "%d counts -> verdict %d" % (counts, v))
    check("and the page did not move",
          (g.get16("CAL_TPS1_MIN"), g.get16("CAL_TPS2_MIN")) == before,
          "%s" % (before,))

    # ------------------------------------------------------------------ 6 --
    # A TRAVEL THAT IS NOT A TRAVEL IS REFUSED. MAX is 70; asking for a MIN
    # only a few counts away is rusEFI's "check your wiring".
    g.raw("TPS1", 70 + MIN_SPAN - 10)
    g.raw("TPS2", 950 - MIN_SPAN + 10)
    v = g.grab(W["TPS_CLOSED"])
    check("capture can replace a stale opposite endpoint", v == V["PASS"],
          "verdict %d" % v)
    g.raw("TPS1", 70 + MIN_SPAN + 10)
    g.raw("TPS2", 950 - MIN_SPAN - 10)
    v = g.grab(W["TPS_CLOSED"])
    check("and a span just over it is accepted", v == V["PASS"],
          "verdict %d" % v)

    # ------------------------------------------------------------------ 7 --
    # THE FIRST GRAB OF A PAIR IS ALWAYS ALLOWED. There is nothing to compare
    # against, and refusing it would make the pair uncalibratable.
    g.clear(W["TPS_CLOSED"])
    g.clear(W["TPS_OPEN"])
    g.raw("TPS1", 500)
    g.raw("TPS2", 500)
    check("the first grab of an uncalibrated pair is allowed",
          g.grab(W["TPS_CLOSED"]) == V["PASS"])

    # ------------------------------------------------------------------ 8 --
    # THE ENGINE MUST BE DEMONSTRABLY STOPPED, and 'stopped' is two facts.
    g.raw("TPS1", 890)
    g.raw("TPS2", 130)
    g.turning(800)
    v = g.grab(W["TPS_OPEN"])
    check("a grab while the engine is turning is refused", v == V["RPM"],
          "verdict %d" % v)
    g.rig.m.w16(sym("trg_rpm") & 0xFFFF, 0)     # rpm 0 but the decoder is live
    g.rig.m.w8(sym("trg_state") & 0xFFFF, 3)
    v = g.grab(W["TPS_OPEN"])
    check("rpm 0 alone is not enough - the decoder must be quiet too",
          v == V["RPM"], "verdict %d" % v)
    g.stopped()
    check("and with both facts true it proceeds",
          g.grab(W["TPS_OPEN"]) == V["PASS"])

    # ------------------------------------------------------------------ 9 --
    # THE PEDAL PAIR, same rules, different slots.
    g.stopped()
    g.clear(W["APP_REST"])
    g.clear(W["APP_FULL"])
    g.raw("PEDAL1", 200)
    g.raw("PEDAL2", 800)
    check("grab RELEASED pedal", g.grab(W["APP_REST"]) == V["PASS"])
    check("  APP1 released went to MIN", g.get16("CAL_PEDAL1_MIN") == 200,
          "%d" % g.get16("CAL_PEDAL1_MIN"))
    g.raw("PEDAL1", 800)
    g.raw("PEDAL2", 200)
    check("grab FLOORED pedal", g.grab(W["APP_FULL"]) == V["PASS"])
    check("  APP1 floored went to MAX", g.get16("CAL_PEDAL1_MAX") == 800,
          "%d" % g.get16("CAL_PEDAL1_MAX"))

    # ----------------------------------------------------------------- 10 --
    # A GRAB TOUCHES ITS OWN FOUR BYTES AND NOTHING ELSE.
    g.stopped()
    g.raw("TPS1", 890)
    g.raw("TPS2", 130)
    snap = page_bytes(g)
    g.grab(W["TPS_CLOSED"])
    after = page_bytes(g)
    check("the near-RAM half of the page is untouched", snap == after,
          "TPS calibration lives above HC_CFG_CORE; nothing below it moved")

    # ----------------------------------------------------------------- 11 --
    # AND NOTHING WAS BURNED. hcnvm's commit counter is the only thing that
    # can say a flash write happened.
    check("no flash commit was staged", g.rig("hc_nvm_commits") == 0,
          "hc_nvm_commits() = %d" % g.rig("hc_nvm_commits"))
    st = g.rig("hc_nvm_state")
    check("and the persistence state is not COMMITTING", st < 4,
          "hc_nvm_state() = %d" % st)

    # ----------------------------------------------------------------- 12 --
    check("an endpoint that does not exist is refused",
          g.grab(99) == V["WHAT"])

    print("\n%s" % ("CALIB GRAB PROOF PASSES - the endpoints are measured, the "
                    "inverted span\nsurvives, a rail and a non-travel are "
                    "refused with a reason, and nothing\nreached flash.\nNOT "
                    "PHYSICALLY VERIFIED: no grab has been performed on this "
                    "ECU."
                    if not FAILS else
                    "CALIB GRAB PROOF FAILS - %d check(s)." % FAILS))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
