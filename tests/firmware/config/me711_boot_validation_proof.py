#!/usr/bin/env python3
"""A structurally perfect page that cannot run must not be booted into.

THE GAP THIS CLOSES. Everything that accepts a stored configuration on this
ECU asks the same kind of question:

    hc_cfg_init()   magic, version, size, checksum      "are these bytes intact"
    hc_nvm_boot()   magic, layout id, length, 2x CRC16  "are these bytes intact"

NONE of them asks whether the configuration DESCRIBES SOMETHING THAT CAN RUN.
So an ECU could come up on a byte-perfect page that hc_validate() would refuse
- a crank pin on a cavity with no capture unit, two position inputs on one
capture channel, a sequential strategy with no cycle to sequence against - and
say nothing. It would simply never run, and the reason was one apply away from
being visible the whole time.

V64 validates the restored page at boot and seeds the board defaults over it
when it does not hold up. The floor is safe because V61 made the board default
a RUNNABLE configuration rather than an inert one.

WHAT THIS GATE COVERS AND WHAT ITS NEIGHBOUR DOES. This one is about the
FLOOR: a page that cannot run is not booted into, and what replaces it is a
board default that can. The walk back through OLDER stored generations - the
other half, implemented at V65 - belongs to me711_lkg_walkback_proof, which
builds real records into real cells and boots them. Both are needed: the
walk-back finds a better answer when the store has one, and this floor is
what happens when it does not.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_heartbeat_gap_proof as HB    # noqa: E402
import me711_image as PI                  # noqa: E402

TGT = ROOT / "firmware/targets/me711"
CFG_H = ROOT / "firmware/config/hcconfig.h"
GEN_H = ROOT / "firmware/generated/hc_config_generated.h"

SENTINEL = 0x0002
CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))


def sym(name):
    for m in re.finditer(r"^\s*([0-9A-F]{6})H\s+(\w+)\s",
                         PI.MAP.read_text(errors="replace"), re.M):
        if m.group(2) == name:
            return int(m.group(1), 16)
    raise SystemExit("%s is not in the map - build the target first" % name)


def defn(path, name):
    m = re.search(r"#define\s+%s\s+(\d+)u?" % name, path.read_text(errors="replace"))
    if not m:
        raise SystemExit("%s is not in %s" % (name, path.name))
    return int(m.group(1))


class Rig:
    def __init__(self):
        self.r = HB.Rig(PI.image(), HB.ENTRY_CURRENT, HB.TICK_CURRENT, echo=False)
        self.r.run(600_000)
        self.cpu, self.mem = self.r.cpu, self.r.mem
        h = (TGT / "hctarget.h").read_text(errors="replace")
        self.extram = int(re.search(r"#define\s+TGT_EXTRAM_BASE\s+(0x[0-9A-Fa-f]+)", h).group(1), 16)
        self.ramcfg = int(re.search(r"#define\s+TGT_RAM_CFG\s+(0x[0-9A-Fa-f]+)", h).group(1), 16)
        self.core = defn(CFG_H, "HC_CFG_CORE")
        self.hdr = defn(CFG_H, "HC_CFG_HDR_LEN")

    def call(self, name, args=()):
        cpu = self.cpu
        addr = sym(name)
        saved = (cpu.csp, cpu.ip, cpu.m.sfr[0xFE12], cpu.ext)
        cpu.ext = None
        cpu.push(SENTINEL)
        cpu.csp = (addr >> 16) & 0xFF
        cpu.ip = addr & 0xFFFF
        for i, v in enumerate(args):
            cpu.sr(8 + i, v & 0xFFFF)
        for _ in range(3_000_000):
            if (cpu.ip & 0xFFFF) == SENTINEL:
                break
            cpu.step()
        else:
            raise SystemExit("%s did not return" % name)
        out = cpu.gr(4) & 0xFFFF
        cpu.csp, cpu.ip, cpu.m.sfr[0xFE12], cpu.ext = saved
        return out

    def addr(self, off):
        return ((sym("hc_cfg") & 0xFFFF) + off if off < self.core
                else self.extram + self.ramcfg + self.hdr + off)

    def set8(self, off, v):
        self.mem.w8(self.addr(off), v & 0xFF)

    def get8(self, off):
        return self.mem.r8(self.addr(off))

    def u8(self, name):
        return self.mem.r8(sym(name) & 0xFFFF)


def main() -> int:
    PIN_CRANK = defn(GEN_H, "CFG_U_PIN_CRANK")
    PIN_CAM1 = defn(GEN_H, "CFG_U_PIN_CAM1")
    print("=== HaniCore ME7.1.1 - a restored page is VALIDATED, not just "
          "checksummed ===\n")
    print("  image   %s\n" % PI.IMG.name)

    # ------------------------------------------------ 1. the healthy case
    r = Rig()
    r.call("hc_cfg_init")
    r.call("hc_cfg_mgr_init")
    fell = r.u8("hc_cfg_boot_fellback")
    crank = r.get8(PIN_CRANK)
    check("a healthy page boots WITHOUT falling back", fell == 0,
          "hc_cfg_boot_fellback = %d, pinCrank = %d" % (fell, crank))
    check("...and it is the board default that is live", crank == 82,
          "cavity 82 - DZG+, the proven crank input")
    ok = r.call("hc_validate", (0,))       # HC_VAL_SRC_ACTIVE
    check("...and that page validates", ok == 0, "hc_validate = 0x%04X" % ok)

    # -------------------------- 2. structurally perfect, semantically dead
    #
    # Cavity 29 is SRD_S/HFM_S on P5.0/AN0 - a real cavity, AIN|FREQ_IN, and
    # the analog block has no capture unit behind it. So this is a page that
    # every checksum in the system accepts and that hc_validate() refuses,
    # which is exactly the shape the boot check exists for.
    r2 = Rig()
    r2.call("hc_cfg_init")
    # SEED FIRST, THEN BREAK IT. migrate_active() reseeds any page whose magic
    # or schema does not match, and it runs BEFORE the validation - so setting
    # the bad pin on a fresh page would simply be overwritten and the test
    # would prove nothing. Running the init once leaves a page with the right
    # magic; the second init is then the boot of a STORED page, which is the
    # case this gate is about. Found by the gate reporting the fallback flag
    # as 0 while the pin had been repaired anyway.
    r2.call("hc_cfg_mgr_init")
    r2.set8(PIN_CRANK, 29)
    bad = r2.call("hc_validate", (0,))
    check("a crank on cavity 29 IS refused by the validator", bad != 0,
          "hc_validate = 0x%04X - no capture unit on P5.0/AN0" % bad)

    r2.call("hc_cfg_mgr_init")
    fell2 = r2.u8("hc_cfg_boot_fellback")
    crank2 = r2.get8(PIN_CRANK)
    check("booting it FALLS BACK rather than running it", fell2 == 1,
          "hc_cfg_boot_fellback = %d" % fell2)
    check("...to the board default, not to nothing", crank2 == 82,
          "pinCrank went %d -> %d" % (29, crank2))
    after = r2.call("hc_validate", (0,))
    check("...and what it fell back to actually validates", after == 0,
          "hc_validate = 0x%04X - a RUNNABLE floor, which is V61's doing"
          % after)

    # ------------------------------------- 3. the other refusal shape
    r3 = Rig()
    r3.call("hc_cfg_init")
    r3.call("hc_cfg_mgr_init")            # a seeded page, as above
    r3.set8(PIN_CAM1, 82)                 # cam 1 onto the crank's own cavity
    conflict = r3.call("hc_validate", (0,))
    check("two position inputs on one cavity is refused", conflict != 0,
          "hc_validate = 0x%04X" % conflict)
    r3.call("hc_cfg_mgr_init")
    check("...and that page is not booted into either",
          r3.u8("hc_cfg_boot_fellback") == 1 and r3.get8(PIN_CAM1) == 86,
          "pinCam1 back to 86")

    # ----------------------------------------- NEGATIVE CONTROL
    #
    # The flag must not simply always be 1. Case 1 already shows a clean boot
    # leaving it 0, and this states it as its own claim so a firmware that set
    # it unconditionally would fail here rather than look like it passed.
    check("NEGATIVE CONTROL - the fallback flag is not always set",
          fell == 0 and fell2 == 1,
          "clean boot 0, refused page 1 - the flag discriminates")

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        return 1
    print("BOOT VALIDATION PASSES - a page that cannot run is not booted into, "
          "and the floor it falls to is one that can. The generation walk-back "
          "above that floor is me711_lkg_walkback_proof's subject.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
