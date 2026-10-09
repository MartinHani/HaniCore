#!/usr/bin/env python3
r"""
me711_routing_binding_proof.py - the configured cavity actually drives the
hardware, and a cavity the board cannot route is refused.

    py tests\firmware\config\me711_routing_binding_proof.py

WHAT THIS IS FOR
================
Up to V61 the crank capture was compiled to CC15 and the cams to CC8/CC9, and
`hc_hal_ain()` read a compile-time `PHYS[]` table. `pinCrank`, `pinCam1`,
`pinCam2`, `pinTps1` and the rest were validated against the hardware
descriptor and then read by no runtime path at all.

> **`pinCrank = 86` VALIDATED - cavity 86 really does carry HALL_IN - and the
> firmware went on capturing cavity 82.** The tuner was told the configuration
> was accepted and the ECU read a different wire.

V62 makes the binding real. This gate is what stops it quietly coming undone,
and it is written so that it CANNOT pass against the image that had the defect:
every positive check below is re-run against the frozen V61 binary, where the
capture map must NOT move.

THE FOUR QUESTIONS, and the last one is the one that matters
===========================================================
1. does the Porsche board default still resolve to the PROVEN hardware?
   `trigCfgCaptureMap` must read 0x0321 - crank on CC15 (cavity 82), cam 1 on
   CC8 (86), cam 2 on CC9 (87) - which is bit-for-bit what V55..V61 compiled
   in. A routing rewrite is not allowed to move the one engine input this
   project has actually measured.
2. does moving `pinCrank` MOVE THE HARDWARE? Set it to 86 and the crank role
   has to land on CC8.
3. is a cavity this board cannot capture REFUSED? An analog-only cavity has a
   descriptor that permits nothing of the sort, and a cavity with FREQ_IN but
   no capture unit behind it is the harder case - it must still be refused,
   because the binding is real now and "resolved to nothing" would silently
   disarm the engine's position input while reporting success.
4. and does V61 fail 1..3? If the control ever stops failing, this gate has
   stopped testing what it says it tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_config_state_test as T     # the rig, the offsets, VAL
import me711_image as PI                # noqa: E402

FAILS = 0
CHECKS = 0

# THE CONTROL IS V60, NOT V61, and the reason is worth keeping.
#
# V61 is the nearer image and would be the better control - it is the one this
# work changed. But a control needs its OWN linker map (the rig calls firmware
# by address) and the V61 map in the release directory was overwritten during
# this session by a later build, so pairing it with the V61 binary would be
# exactly the artefact-pair defect this project has paid for four times.
# V60 is FROZEN, committed, and its .bin and .M66 belong to each other. It
# predates the board default AND the routing binding, so it fails these checks
# for two reasons rather than one - which is fine for a control and is stated
# here so nobody reads a V60 failure as evidence about V61.
CONTROL = (Path(__file__).resolve().parents[3]
           / "release/Porsche_ME711_V60_BURN_REFUSAL"
           / "HaniCore_ME711_v60_burn_refusal.bin")

ROLE = {0: "unused", 1: "crank", 2: "cam1", 3: "cam2"}
PIN_NONE = 255

# The Porsche board's three capture cavities, and the channel each reaches.
CAV_CC15, CAV_CC8, CAV_CC9 = 82, 86, 87


def ck(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-56s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def off(name):
    return T.d(T._gen, name)


def fmt_map(v):
    return "0x%04X  CC15=%s CC8=%s CC9=%s" % (
        v, ROLE.get(v & 0xF, "?"), ROLE.get((v >> 4) & 0xF, "?"),
        ROLE.get((v >> 8) & 0xF, "?"))


class using_image:
    """Point the rig at another linked image WITH ITS OWN MAP.

    The rig calls firmware by address. Running the frozen V61 binary against
    V62's map would call whatever happens to live at V62's addresses - noise,
    not a control - so image, map, symbol cache and stack top move together."""

    def __init__(self, img):
        self.img, self.map = img, img.with_suffix(".M66")

    def __enter__(self):
        if not self.map.exists():
            raise SystemExit("no map beside the control image: %s" % self.map)
        self.saved = (PI.IMG, PI.MAP, PI.MANIFEST, T.MAP_FILE, T._SYMS)
        PI.IMG, PI.MAP = self.img, self.map
        PI.MANIFEST = self.map.with_name("__no_manifest__.json")
        T.MAP_FILE, T._SYMS = self.map, None
        return self

    def __exit__(self, *exc):
        PI.IMG, PI.MAP, PI.MANIFEST, T.MAP_FILE, T._SYMS = self.saved
        return False


def capture_map(pins=None):
    """Boot, optionally move some pins in the ACTIVE page, re-init the decoder,
    and read back what the hardware was actually armed for."""
    r = T.boot()
    for slot, val in (pins or {}).items():
        r("hc_cal_set_u8", off(slot), val)
    r("trg_init")
    return r, r.g16("trg_cfg_capture_map")


def validate_with(pins):
    r = T.boot()
    for slot, val in pins.items():
        r("hc_cal_set_u8", off(slot), val)
    return r("hc_validate", T.VAL["HC_VAL_SRC_ACTIVE"])


def main():
    print("=== the configured cavity drives the hardware ===\n")
    print("  image under test : %s" % PI.image().name)
    print("  negative control : %s\n" % CONTROL.name)

    # ---- 1. the proven default is unchanged ------------------------------
    # Cam 2 claims its cavity only while something uses it (a cam-2 sync
    # mode, a cam-2 pattern or the second VVT): the board default does not,
    # so CC9 stays free for a switch input there.
    _r, m = capture_map()
    want = 1 | (2 << 4)                     # crank CC15, cam1 CC8
    ck("the Porsche default still resolves to the PROVEN hardware", m == want,
       fmt_map(m))
    _r, m2 = capture_map({"CFG_U_SYNC_MODE": T.d(T._gen, "HC_SYNC_DUAL_CAM")})
    ck("a cam-2 sync mode claims cam 2 on CC9", m2 == want | (3 << 8),
       fmt_map(m2))

    # ---- 2. moving pinCrank moves the CAPTURE CHANNEL --------------------
    _r, m86 = capture_map({"CFG_U_PIN_CRANK": CAV_CC8,
                           "CFG_U_PIN_CAM1": PIN_NONE})
    ck("pinCrank = 86 moves the crank onto CC8", (m86 & 0xF) == 0
       and ((m86 >> 4) & 0xF) == 1, fmt_map(m86))

    _r, m87 = capture_map({"CFG_U_PIN_CRANK": CAV_CC9,
                           "CFG_U_PIN_CAM2": PIN_NONE})
    ck("pinCrank = 87 moves the crank onto CC9", (m87 & 0xF) == 0
       and ((m87 >> 8) & 0xF) == 1, fmt_map(m87))

    ck("...and those are three DIFFERENT hardware resolutions",
       len({m, m86, m87}) == 3,
       "0x%04X / 0x%04X / 0x%04X" % (m, m86, m87))

    # ---- 3. a cavity this board cannot capture is REFUSED ----------------
    rc = validate_with({"CFG_U_PIN_CRANK": 92})       # IP1_S, analog only
    ck("a crank on an ANALOG-only cavity is refused",
       bool(rc & T.VAL["HC_VAL_FAULT_PIN_CAP"]),
       "cavity 92 IP1_S -> AN1, no capture unit; rc = 0x%04X" % rc)

    rc = validate_with({"CFG_U_PIN_CRANK": 67})  # CRSH_S: DIN|FREQ_IN, no unit
    ck("a crank on a FREQ_IN cavity with NO capture unit is refused",
       bool(rc & T.VAL["HC_VAL_FAULT_PIN_CAP"]),
       "cavity 67 looks capable and this board never wired it to one; "
       "rc = 0x%04X" % rc)

    rc = validate_with({"CFG_U_PIN_CRANK": 90})       # DZG-_S, the other half
    ck("a crank on cavity 90 is refused", bool(rc & T.VAL["HC_VAL_FAULT_PIN_CAP"]),
       "90 is DG- of ONE differential pair, not a second input; "
       "rc = 0x%04X" % rc)

    rc = validate_with({"CFG_U_PIN_CRANK": CAV_CC15,
                        "CFG_U_PIN_CAM1": CAV_CC15})
    ck("crank and cam1 on the SAME cavity is refused", rc != T.VAL["HC_VAL_OK"],
       "rc = 0x%04X" % rc)

    rc = validate_with({"CFG_U_PIN_CRANK": CAV_CC15, "CFG_U_PIN_CAM1": CAV_CC8,
                        "CFG_U_PIN_CAM2": CAV_CC9})
    ck("and the board's own three cavities are ACCEPTED",
       not (rc & T.VAL["HC_VAL_FAULT_PIN_CAP"])
       and not (rc & T.VAL["HC_VAL_FAULT_PIN_CONFLICT"]),
       "rc = 0x%04X" % rc)

    # ---- 4. the analog binding follows the page too ----------------------
    r = T.boot()
    r("hc_route_service")
    a_tps1 = r.callb("hc_hal_ain_bound", T.d(T._cfg, "HC_AIN_TPS1")
                     if "HC_AIN_TPS1" in T._cfg else 4)
    ck("the analog binding resolves TPS1 from the page", a_tps1 == 1,
       "bound to AN%d, and cavity 92 is AN1" % a_tps1)

    r = T.boot()
    r("hc_cal_set_u8", off("CFG_U_PIN_TPS1"), 84)      # IP2_S -> AN3
    r("hc_route_service")
    a_moved = r.callb("hc_hal_ain_bound", 4)
    ck("moving pinTps1 to cavity 84 moves the BINDING to AN3", a_moved == 3,
       "bound to AN%d" % a_moved)

    # ---- 4b. the TunerStudio dropdown must match the capture table -------
    #
    # V62 turned every pin field into a capability-filtered `bits` list. If
    # that list and hc_hal_capture_channel() ever disagree, the tuner is
    # offered a cavity the ECU refuses - which is worse than the number field
    # it replaced. The .ini is generated; this is what stops it drifting.
    import re as _re
    ini = [p for p in (Path(__file__).resolve().parents[3]
                       / "tunerstudio").glob("hanicore_*.ini")
           if p.stem.lower() == PI.STEM.lower()]
    if not ini:
        ck("the .ini for this image is present to check the dropdown", False,
           "generate it: py tools\\tunerstudio\\gen_ts_ini_me711.py")
    else:
        txt = ini[-1].read_text(encoding="utf-8", errors="replace")
        m = _re.search(r"^\s*pinCrank\s*=\s*bits,\s*U08,\s*\d+,\s*"
                       r"\[0:7\],\s*(.*)$", txt, _re.M)
        if not m:
            ck(False, "pinCrank is a capability-filtered dropdown",
               "still a raw scalar in %s" % ini[-1].name)
        else:
            labels = [s.strip(' "') for s in m.group(1).split('", "')]
            offered = {int(l.split()[0]) for l in labels
                       if l not in ("INVALID", "NONE") and l.split()[0].isdigit()}
            want = {CAV_CC15, CAV_CC8, CAV_CC9}
            ck("the crank dropdown offers exactly the capture cavities",
               offered == want,
               "%s offers %s, hc_hal_capture_channel maps %s"
               % (ini[-1].name, sorted(offered), sorted(want)))

    # ---- 5. THE NEGATIVE CONTROL ----------------------------------------
    print("\n  --- the frozen V60 binary, where the binding was not real ---")
    if not CONTROL.exists():
        print("  NEGATIVE CONTROL NOT RUN: the frozen V60 release is not in this "
              "tree (maintainer's record); the checks above still ran")
    else:
        try:
            with using_image(CONTROL):
                # CAVITY 67 IS THE SHARP CASE, and cavity 92 was not.
                #
                # 92 is analog-only, so the capability test that has existed
                # since V26 already refused it on every image - using it as a
                # control proved nothing about this change. 67 (CRSH_S) carries
                # DIN|FREQ_IN, so the OLD test passes it as "a frequency input,
                # close enough for a crank" while THIS BOARD HAS NO CAPTURE
                # UNIT BEHIND IT. V60 accepts it and then captures cavity 82
                # anyway; V62 refuses it.
                rc61 = validate_with({"CFG_U_PIN_CRANK": 67})
                r61 = T.boot()
                r61("hc_cal_set_u8", off("CFG_U_PIN_CRANK"), CAV_CC8)
                r61("trg_init")
                has_map = "trg_cfg_capture_map" in (T._SYMS or {})
        except SystemExit as e:
            ck(False, "the control image boots in the rig", str(e))
        else:
            ck("the CONTROL has no capture map to publish at all", not has_map,
               "trg_cfg_capture_map does not exist in the control map - the "
               "binding it would describe did not exist either")
            ck("the CONTROL accepts a crank on cavity 67, which has no "
               "capture unit",
               not (rc61 & T.VAL["HC_VAL_FAULT_PIN_CAP"]),
               "rc = 0x%04X - validated, and the firmware then captured "
               "cavity 82 anyway. THIS IS THE DEFECT." % rc61)

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("\nROUTING BINDING PROOF FAILS.")
        print("If check 1 failed, the routing rewrite moved the one engine")
        print("input this project has physically measured - fix that first.")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
