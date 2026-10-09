#!/usr/bin/env python3
r"""
me711_hall_crank_proof.py - a HALL crank is a real capability, not a VR one
with the label changed.

    py tests\firmware\trigger\me711_hall_crank_proof.py

WHY. The VR crank on cavity 82 is the only position input this ECU has ever
been PHYSICALLY qualified on (199/996/1984/2959 rpm, zero noise edges). A
universal standalone ECU has to take a Hall crank too, and "the capability bit
exists" is not the same claim as "the configuration validates AND the runtime
arms the right capture channel with the right edge". Those are three separate
layers and this gate walks all three, on the linked image.

WHAT IT ESTABLISHES, and the third one is the part nobody had checked:

  1. THE DESCRIPTOR distinguishes VR_IN from HALL_IN, and says which cavities
     have which. They are different circuits and the board does not pretend
     otherwise.
  2. THE VALIDATOR accepts a crank on either kind and refuses one on a cavity
     that has neither - so a Hall crank is a legal PAGE.
  3. THE RUNTIME RE-ROUTES THE CAPTURE. Moving pinCrank from 82 to 86 has to
     take the CRANK role off CC15 and put it on CC8, or the edit looks
     accepted while the ECU counts nothing. hctrig_me711.c's own comment says
     the roles had to go into the geometry signature for exactly this reason;
     this asserts the outcome rather than the intent.

AND IT RECORDS THE CONSTRAINT THAT FALLS OUT OF IT. On this board every
HALL_IN cavity is a CAM input (86 `PHA1_S`, 87 `PHA2_S`). So a Hall crank
COSTS A CAM: crank-on-86 leaves one cam input, and Hall-crank-plus-two-cams
does not fit this connector at all. That is a hardware fact worth failing a
gate over if the descriptor ever quietly changes.

NOT PHYSICALLY PROVEN. No Hall crank sensor has been connected to cavity 86 or
87 on this ECU. This is the SIMULATED half; the bench half is a signal into
that cavity and an rpm that follows it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_image as PI                      # noqa: E402
import me711_lkg_walkback_proof as LK         # noqa: E402  - the Boot harness

GEN_H = ROOT / "firmware/generated/hc_config_generated.h"
DESC = ROOT / "firmware/generated/hc_pin_desc_bosch_me711.c"

HC_PIN_NONE = 255
ROLE = {0: "NONE", 1: "CRANK", 2: "CAM1", 3: "CAM2"}

CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print("  [%s] %-54s %s" % ("PASS" if ok else "FAIL", name, detail))


def cap(name):
    m = re.search(r"#define\s+%s\s+(0x[0-9A-Fa-f]+)" % name,
                  GEN_H.read_text(errors="replace"))
    if not m:
        raise SystemExit("%s missing from hc_config_generated.h" % name)
    return int(m.group(1), 16)


def descriptor():
    """cavity -> capability word, out of the COMPILED-IN descriptor source."""
    rows = re.findall(
        r"\{\s*(0x[0-9A-Fa-f]+)u,\s*0x[0-9A-Fa-f]+u,\s*(\d)u,"
        r"\s*0x[0-9A-Fa-f]+u\s*\},\s*/\*\s*(\d+)\s",
        DESC.read_text(errors="replace"))
    return {int(pin): (int(caps, 16), int(rout)) for caps, rout, pin in rows}


def roles(m):
    return (ROLE.get(m & 0xF, "?"), ROLE.get((m >> 4) & 0xF, "?"),
            ROLE.get((m >> 8) & 0xF, "?"))


def main() -> int:
    VR, HALL = cap("HC_PINCAP_VR_IN"), cap("HC_PINCAP_HALL_IN")
    PC = LK.defn(GEN_H, "CFG_U_PIN_CRANK")
    C1 = LK.defn(GEN_H, "CFG_U_PIN_CAM1")
    C2 = LK.defn(GEN_H, "CFG_U_PIN_CAM2")

    print("=== HaniCore ME7.1.1 - a HALL crank is really supported ===\n")
    print("  image   %s\n" % PI.IMG.name)

    # ---------------------------------------------- 1. the descriptor layer
    d = descriptor()
    vr = sorted(p for p, (c, _) in d.items() if c & VR)
    hall = sorted(p for p, (c, _) in d.items() if c & HALL)
    check("the descriptor was parsed at all", len(d) >= 100,
          "%d cavities" % len(d))
    check("VR_IN and HALL_IN are different capabilities", VR != HALL,
          "VR=0x%04X HALL=0x%04X" % (VR, HALL))
    check("the board offers BOTH kinds of position input",
          bool(vr) and bool(hall),
          "VR on %s, HALL on %s" % (vr, hall))
    check("cavity 82 is the VR crank and is NOT Hall",
          82 in vr and 82 not in hall, "the physically qualified one")
    check("cavities 86/87 are HALL and are NOT VR",
          86 in hall and 87 in hall and 86 not in vr and 87 not in vr,
          "PHA1_S / PHA2_S")

    # THE CONSTRAINT. Every Hall cavity on this board is a cam input, so a
    # Hall crank costs a cam. If a future descriptor adds a Hall cavity that
    # is not 86/87 this check SHOULD fail and be re-read, not deleted.
    check("every HALL_IN cavity on this board is a CAM input",
          set(hall) == {86, 87},
          "%s - so a Hall crank costs a cam, and Hall+two cams does not fit"
          % hall)

    # ------------------------------------------------ 2. the validator layer
    def validate(crank, cam1, cam2):
        b = LK.Boot()
        b.call("hc_cfg_init")
        b.call("hc_cfg_mgr_init")
        for off, v in ((PC, crank), (C1, cam1), (C2, cam2)):
            b.mem.w8(b.addr(off), v & 0xFF)
        return b.call("hc_validate", (0,)), b

    v, _ = validate(82, 86, 87)
    check("the DEFAULT VR page validates", v == 0, "hc_validate = 0x%04X" % v)

    v, _ = validate(86, 87, HC_PIN_NONE)
    check("a HALL crank on cavity 86 validates", v == 0,
          "crank 86, cam1 87 -> 0x%04X" % v)

    v, _ = validate(87, 86, HC_PIN_NONE)
    check("a HALL crank on cavity 87 validates", v == 0,
          "crank 87, cam1 86 -> 0x%04X" % v)

    # NEGATIVE CONTROL. Cavity 29 is SRD_S/HFM_S on P5.0/AN0 - a real cavity
    # with no capture unit behind it. If this passed, the two above would mean
    # nothing.
    v, _ = validate(29, 86, HC_PIN_NONE)
    check("NEGATIVE CONTROL: a crank on a cavity with neither is REFUSED",
          v != 0, "crank 29 -> 0x%04X (PIN_CAP is 0x0020)" % v)

    # --------------------------------------------------- 3. the runtime layer
    def capture_map(crank, cam1, cam2):
        b = LK.Boot()
        b.call("hc_cfg_init")
        b.call("hc_cfg_mgr_init")
        for off, v in ((PC, crank), (C1, cam1), (C2, cam2)):
            b.mem.w8(b.addr(off), v & 0xFF)
        b.call("trg_init")
        b.call("trg_service")
        return b.mem.r16(LK.sym("trg_cfg_capture_map") & 0xFFFF)

    m = capture_map(82, 86, 87)
    cc15, cc8, cc9 = roles(m)
    # Cam 2 claims CC9 only while something uses it (a cam-2 sync mode, a
    # cam-2 pattern or the second VVT); the default page uses none.
    check("DEFAULT: the crank is on CC15, cam 1 on CC8, CC9 free",
          (cc15, cc8, cc9) == ("CRANK", "CAM1", "NONE"),
          "0x%04X  CC15=%s CC8=%s CC9=%s" % (m, cc15, cc8, cc9))

    m = capture_map(86, 87, HC_PIN_NONE)
    cc15, cc8, cc9 = roles(m)
    check("a HALL crank on 86 MOVES the crank capture to CC8",
          cc8 == "CRANK" and cc15 == "NONE",
          "0x%04X  CC15=%s CC8=%s CC9=%s" % (m, cc15, cc8, cc9))

    m = capture_map(87, 86, HC_PIN_NONE)
    cc15, cc8, cc9 = roles(m)
    check("a HALL crank on 87 MOVES the crank capture to CC9",
          cc9 == "CRANK" and cc15 == "NONE",
          "0x%04X  CC15=%s CC8=%s CC9=%s" % (m, cc15, cc8, cc9))

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("HALL CRANK PROOF FAILS.")
        return 1
    print("HALL CRANK PROOF PASSES - the descriptor separates VR from Hall, "
          "the validator accepts either, and the runtime arms the capture "
          "channel the configured cavity actually belongs to.")
    print("NOT PHYSICALLY PROVEN: no Hall crank sensor has been connected to "
          "cavity 86 or 87 on this ECU.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
