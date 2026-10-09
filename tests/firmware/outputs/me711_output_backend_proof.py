#!/usr/bin/env python3
"""The V63 output back end, executed out of the linked image.

WHAT THIS GATE IS FOR. V63 gave this board the ability to drive a pin for the
first time. Three things have to be true of that and none of them is obvious
from reading the source:

  1. THE PIN TABLE AGREES WITH THE DESCRIPTOR. hchal_me711.c maps a cavity to
     a port bit; hw_descriptors.py maps the same cavity to the same port for
     the validator and the .ini. Two hand-written lists that must agree are
     two lists that eventually will not, so this compares them rather than
     trusting that they were typed the same way twice.

  2. ARMING ACTUALLY GATES. Not "the source says it returns 0" - the linked
     function, executed, with each of its three conditions removed on its own.

  3. THE RESTING STATE IS HIGH IMPEDANCE. The direction register, read out of
     the simulator after boot, because a resting LEVEL would be a guess about
     a polarity this repository has never established and a wrong guess is an
     injector held open by a parked ECU.

WHAT IT DOES NOT CLAIM. Nothing here is electrical proof. It proves the
firmware asks for the right pin under the right conditions; whether the stage
beyond that pin conducts on a high or a low is UNMEASURED, and is the one
thing a logic analyser at the cavity has to settle.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
sys.path.insert(0, str(ROOT / "tools" / "config_source"))

import me711_heartbeat_gap_proof as HB    # noqa: E402
import me711_image as PI                  # noqa: E402
import hw_descriptors as HW               # noqa: E402
from hanicore_config_schema import PinCap  # noqa: E402

TGT = ROOT / "firmware/targets/me711"
HAL_C = TGT / "hal/hchal_me711.c"
ROUTES_C = TGT / "hal/hcroutes711.c"
CFG_H = ROOT / "firmware/config/hcconfig.h"
GEN_H = ROOT / "firmware/generated/hc_config_generated.h"
HAL_H = ROOT / "firmware/hal/hchal.h"

SENTINEL = 0x0002
CHECKS = FAILS = 0

# C167 direction registers, from the User's Manual SFR map.
# reg167.h: P7 = 0xFFD0, DP7 = 0xFFD2, P8 = 0xFFD4, DP8 = 0xFFD6. Until V77
# this gate had port 7 and port 8 SWAPPED (DP7 = 0xFFD0, P7 = 0xFFD2, ...), so
# "every injector pin rests as an INPUT" read the LATCHES - and passed only
# because the old active-high assumption left them at 0. The moment the stages
# were latched HIGH = off (V77, the OEM's own key-on init) it read 0x0070/0x00FF
# and reported injectors driven that were inputs. group_off_release_proof and
# fuel_test.py record the same mistake, made and fixed there first.
DP2, DP7, DP8 = 0xFFC2, 0xFFD2, 0xFFD6
P2, P7, P8 = 0xFFC0, 0xFFD0, 0xFFD4


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


# ------------------------------------------------ 1. the table vs the descriptor
def parse_hal_table():
    """cavity -> (port, bit) as hcroutes711.c's hc_hal_port_of() states it."""
    src = ROUTES_C.read_text(errors="replace")
    body = src[src.index("hc_hal_port_of(unsigned char cav"):]
    body = body[:body.index("\n}")]
    out = {}
    for m in re.finditer(
            r"case\s+(\d+)u:\s*\*port\s*=\s*OP_P(\d)\s*;\s*\*bitno\s*=\s*(\d+)u", body):
        out[int(m.group(1))] = (int(m.group(2)), int(m.group(3)))
    return out


def descriptor_ports():
    """cavity -> (port, bit) for every output-capable cavity the board has."""
    d = HW.build_me711()
    want = PinCap.INJ_OUT | PinCap.IGN_OUT | PinCap.RELAY_OUT
    out = {}
    for n in range(1, HW.PIN_COUNT + 1):
        p = d.pin(n)
        if not (p.capabilities & want):
            continue
        m = re.match(r"P(\d)\.(\d+)", p.hal_resource or "")
        if m:
            out[n] = (int(m.group(1)), int(m.group(2)))
    return out


def main() -> int:
    print("=== HaniCore ME7.1.1 - the V63 output back end, executed ===\n")
    print("  image   %s" % PI.IMG.name)

    hal = parse_hal_table()
    desc = descriptor_ports()
    check("the HAL pin table is not empty", len(hal) >= 15, "%d cavities" % len(hal))

    disagree = [c for c in sorted(set(hal) & set(desc)) if hal[c] != desc[c]]
    check("every cavity the HAL maps agrees with the descriptor", not disagree,
          "checked %d; %s" % (len(set(hal) & set(desc)),
                              "all agree" if not disagree else disagree))

    # V85: ZUE8 IS ROUTABLE. CC7 (the serial RX drain) is in COMPARE MODE 0,
    # which the C167 UM says leaves the pin and latch alone - so P2.7 is a
    # GPIO. Asserted from the SOURCE the claim depends on, so moving CC7 to a
    # pin-driving mode makes this gate fail rather than the K-line.
    hcts = (ROOT / "firmware/comms/hcts.c").read_text(errors="replace")
    check("ZUE8 / cavity 7 is routable to P2.7", hal.get(7) == (2, 7),
          "hal[7] = %s" % (hal.get(7),))
    check("...because CC7 is compare mode 0 (pin untouched, C167 UM)",
          "CCM1 = (unsigned int)((CCM1 & ~0xF000u) | 0x4000u)" in hcts,
          "CCM1[15:12] = 0x4 in hcts.c")

    # Every routable INJECTOR and COIL the descriptor offers is in the table,
    # except the one above - otherwise a cavity a tuner can select would
    # silently drive nothing. Scoped to what this table claims to cover.
    d = HW.build_me711()
    engine = {c for c in desc
              if d.pin(c).capabilities & (PinCap.INJ_OUT | PinCap.IGN_OUT)}
    missing = sorted(c for c in engine if c not in hal)
    check("no injector or coil cavity is missing from the HAL",
          not missing, "%d engine cavities; missing: %s"
          % (len(engine), missing or "none"))

    # THE RELAY CAVITIES ARE NOT IN THIS TABLE AND THAT IS NOT AN OVERSIGHT.
    #
    # The descriptor offers 4, 5, 18 and 22 as RELAY_OUT. Two of them cannot
    # be outputs at all: cavities 4 and 5 are P5.4/AN4 and P5.6/AN6, and PORT 5
    # ON THE C167 IS INPUT ONLY - it has no direction register and no output
    # latch, which is why the analog block lives there. Driving them is not a
    # thing the silicon can do, whatever the connector sheet calls the wire.
    #
    # 18 and 22 are real push-pull pins, but the main relay on this ECU is
    # cavity 23 and cavity 23 has NO main-CPU path at all - it is CJ910 pin 16
    # HR, and the only HR in the port map is the ASIC's P5.14, whose Bosch note
    # is "Port nur Input". hc_hal_main_relay_bound() returning 0 is the honest
    # answer and this table agreeing with it is the point.
    relay_only = sorted(c for c in desc if c not in engine and c not in hal)
    p5 = [c for c in relay_only if (desc[c][0] == 5)]
    # V85: cavities 4 and 5 are NOT relay cavities - the ME7.1.1 schematic's lower half
    # shows them as the LSU heater low sides (ASIC P7.4 / P8.7), locked in the
    # descriptor. V95: 18 and 22, the last two, are locked too - their CPU
    # pins are the CJ120 chip selects - so every relay-capable cavity with a
    # CPU port is now one this table drives (me711_output_binding_proof).
    check("no relay-capable CPU cavity is left out of the HAL table",
          not relay_only, "excluded: %s" % (relay_only or "none"))
    check("...and no PORT 5 cavity is offered as an output any more",
          not p5, "P5 is input-only on the C167; 4/5 are ASIC heater outputs")
    check("the fuel pump IS in the table, because it has a real CPU path",
          65 in hal and hal[65] == (2, 12), "cavity 65 -> P2.12/CC12IO")

    # --------------------------------------------------- 2. executed behaviour
    rig = HB.Rig(PI.image(), HB.ENTRY_CURRENT, HB.TICK_CURRENT, echo=False)
    rig.run(600_000)
    cpu, mem = rig.cpu, rig.mem

    def call(name, args=()):
        addr = sym(name)
        saved = (cpu.csp, cpu.ip, cpu.m.sfr[0xFE12], cpu.ext)
        cpu.ext = None
        cpu.push(SENTINEL)
        cpu.csp = (addr >> 16) & 0xFF
        cpu.ip = addr & 0xFFFF
        for i, v in enumerate(args):
            cpu.sr(8 + i, v & 0xFFFF)
        for _ in range(400_000):
            if (cpu.ip & 0xFFFF) == SENTINEL:
                break
            cpu.step()
        else:
            raise SystemExit("%s did not return" % name)
        out = cpu.gr(4) & 0xFFFF
        cpu.csp, cpu.ip, cpu.m.sfr[0xFE12], cpu.ext = saved
        return out

    CORE = defn(CFG_H, "HC_CFG_CORE")
    HDRL = defn(CFG_H, "HC_CFG_HDR_LEN")
    EXTRAM = int(re.search(r"#define\s+TGT_EXTRAM_BASE\s+(0x[0-9A-Fa-f]+)",
                           (TGT / "hctarget.h").read_text(errors="replace")).group(1), 16)
    RAM_CFG = int(re.search(r"#define\s+TGT_RAM_CFG\s+(0x[0-9A-Fa-f]+)",
                            (TGT / "hctarget.h").read_text(errors="replace")).group(1), 16)

    def page(off):
        return ((sym("hc_cfg") & 0xFFFF) + off if off < CORE
                else EXTRAM + RAM_CFG + HDRL + off)

    def set8(off, v):
        mem.w8(page(off), v & 0xFF)

    ARMED = defn(CFG_H, "CFG_OUTPUTS_ARMED")
    PIN_IGN = defn(GEN_H, "CFG_U_PIN_IGN")
    PIN_INJ = defn(GEN_H, "CFG_U_PIN_INJ")

    # THE RESTING STATE, read out of the direction registers after boot.
    call("hc_hal_outputs_safe")
    dp2, dp7, dp8 = mem.r16(DP2), mem.r16(DP7), mem.r16(DP8)
    ign_mask = 0x00FF          # P2.0..P2.7, all eight coils (V85: + ZUE8)
    inj7 = 0x0070              # P7.4..P7.6
    inj8 = 0x00F8              # P8.3..P8.7
    check("every coil pin rests as an INPUT", (dp2 & ign_mask) == 0,
          "DP2=0x%04X, coil bits 0x%04X clear" % (dp2, ign_mask))
    check("every injector pin rests as an INPUT",
          (dp7 & inj7) == 0 and (dp8 & inj8) == 0,
          "DP7=0x%04X DP8=0x%04X" % (dp7, dp8))
    check("the throttle bridge rests as an INPUT too",
          (dp7 & 0x0084) == 0 and (dp2 & 0x0800) == 0,
          "P7.2 P7.7 P2.11 all input")

    # ARMING. Route coil 1 to cavity 102 (P2.0) and injector 1 to 96 (P7.6).
    set8(PIN_IGN, 102)
    set8(PIN_INJ, 96)
    mem.w16(sym("hc_cfg_validation") & 0xFFFF, 0)
    # AS AN APPLY WOULD: bump hc_cfg_active_rev so the route cache re-reads.
    # Until V84 this gate got away without it because nothing resolved the
    # routes before its first ON; since V84 the boot sweep's OFF (ev_all_off)
    # really runs the release path and resolves the table at boot, which is
    # exactly the "a raw page poke does not re-route" property pinned below.
    _rev = sym("hc_cfg_active_rev") & 0xFFFF
    mem.w16(_rev, (mem.r16(_rev) + 1) & 0xFFFF)

    HC_OUT_IGN1 = 0
    HC_OUT_INJ1 = 8

    def drive(sem, on):
        call("hc_hal_out", (sem, on))

    # --- negative control A: not armed -----------------------------------
    set8(ARMED, 0)
    call("hc_safety_service", (1, 1, 1, 1, 0))
    drive(HC_OUT_IGN1, 1)
    check("NEGATIVE CONTROL - unarmed, the coil pin stays an input",
          (mem.r16(DP2) & 0x0001) == 0, "DP2.0=%d" % (mem.r16(DP2) & 1))

    # --- negative control B: armed but the page is refused ---------------
    set8(ARMED, 1)
    mem.w16(sym("hc_cfg_validation") & 0xFFFF, 0x0020)
    call("hc_safety_service", (1, 1, 1, 1, 1))
    drive(HC_OUT_IGN1, 1)
    check("NEGATIVE CONTROL - a REFUSED page cannot drive, even armed",
          (mem.r16(DP2) & 0x0001) == 0, "cfgValidation=0x0020")
    mem.w16(sym("hc_cfg_validation") & 0xFFFF, 0)

    # --- negative control C: no crank, a coil is an ANGLE ----------------
    call("hc_safety_service", (1, 1, 0, 0, 1))
    drive(HC_OUT_IGN1, 1)
    coil_off = (mem.r16(DP2) & 0x0001) == 0
    call("hc_hal_out", (18, 1))          # HC_OUT_THR_EN - a POSITION
    thr_on = (mem.r16(DP2) & 0x0800) != 0
    check("NEGATIVE CONTROL - no crank: the coil is refused", coil_off)
    check("...but the throttle enable is ALLOWED, because a plate is a position",
          thr_on, "this is what lets DBW help start an engine")

    # --- the positive case ------------------------------------------------
    call("hc_safety_service", (1, 1, 1, 1, 1))
    drive(HC_OUT_IGN1, 1)
    check("armed, valid and synchronised: the coil pin becomes an OUTPUT",
          (mem.r16(DP2) & 0x0001) != 0, "DP2.0 set")
    # THE ACTIVE LEVEL IS THE TARGET'S, read from hctarget.h rather than
    # assumed HIGH: V77 made coils and injectors active-LOW on the OEM's own
    # key-on port init.
    ign_act = defn(TGT / "hctarget.h", "TGT_IGN_ACTIVE_HIGH")
    inj_act = defn(TGT / "hctarget.h", "TGT_INJ_ACTIVE_HIGH")
    check("...and the routed cavity is the one that moved - 102 is P2.0",
          ((mem.r16(P2) & 0x0001) != 0) == (ign_act != 0),
          "P2.0 at the ACTIVE level (TGT_IGN_ACTIVE_HIGH=%d)" % ign_act)
    drive(HC_OUT_INJ1, 1)
    check("injector 1 routed to cavity 96 drives P7.6",
          (mem.r16(DP7) & 0x0040) != 0
          and ((mem.r16(P7) & 0x0040) != 0) == (inj_act != 0),
          "DP7.6 set, P7.6 at the ACTIVE level (TGT_INJ_ACTIVE_HIGH=%d)"
          % inj_act)

    # --- A RAW PAGE POKE DOES NOT RE-ROUTE, AND THAT IS THE DESIGN --------
    #
    # V63 resolves every hot semantic to a port bit ONCE and caches it against
    # hc_cfg_active_rev, because doing it per call cost 248 instructions of a
    # tooth. So a pin that is written into the page WITHOUT an apply does not
    # move anything - exactly as hctrig_me711.c does not re-read its geometry
    # until the config manager commits a transaction.
    #
    # This gate found that the moment the cache landed, by failing. It is
    # worth pinning in BOTH directions rather than just fixing.
    rev = sym("hc_cfg_active_rev") & 0xFFFF
    before = mem.r16(DP2)
    set8(PIN_IGN, 94)                    # ZUE3 -> P2.2, page only
    drive(HC_OUT_IGN1, 1)
    check("a page write with no apply does NOT move the routing",
          (mem.r16(DP2) & 0x0004) == 0,
          "DP2.2 still clear - the cache is keyed on hc_cfg_active_rev")

    # ...and an APPLY is what makes it take effect, which is what an operator
    # actually does.
    mem.w16(rev, (mem.r16(rev) + 1) & 0xFFFF)
    drive(HC_OUT_IGN1, 1)
    check("after an apply, coil 1 really is on cavity 94 / P2.2",
          (mem.r16(DP2) & 0x0004) != 0, "DP2.2 set - the cavity decides")

    # --- V85: ZUE8 on cavity 7 drives P2.7 ---------------------------------
    set8(PIN_IGN, 7)
    mem.w16(rev, (mem.r16(rev) + 1) & 0xFFFF)
    drive(HC_OUT_IGN1, 1)
    check("coil 1 routed to cavity 7 (ZUE8) drives P2.7",
          (mem.r16(DP2) & 0x0080) != 0, "DP2.7 set")
    drive(HC_OUT_IGN1, 0)

    # --- an unroutable cavity drives nothing ------------------------------
    before = mem.r16(DP2)
    set8(PIN_IGN, 67)                    # DIN|FREQ_IN, no output stage
    mem.w16(rev, (mem.r16(rev) + 1) & 0xFFFF)
    drive(HC_OUT_IGN1, 1)
    check("NEGATIVE CONTROL - cavity 67 drives no pin at all",
          mem.r16(DP2) == before, "DP2 unchanged at 0x%04X" % before)

    set8(PIN_IGN, 255)                   # HC_PIN_NONE
    mem.w16(rev, (mem.r16(rev) + 1) & 0xFFFF)
    before = mem.r16(DP2)
    drive(HC_OUT_IGN1, 1)
    check("NEGATIVE CONTROL - an unassigned pin drives nothing",
          mem.r16(DP2) == before, "DP2 unchanged")

    # --- everything back to safe ------------------------------------------
    set8(PIN_IGN, 102)
    mem.w16(rev, (mem.r16(rev) + 1) & 0xFFFF)
    drive(HC_OUT_IGN1, 1)
    call("hc_hal_outputs_safe")
    check("hc_hal_outputs_safe() puts every engine output back to INPUT",
          (mem.r16(DP2) & ign_mask) == 0 and (mem.r16(DP7) & inj7) == 0
          and (mem.r16(DP8) & inj8) == 0,
          "DP2=0x%04X DP7=0x%04X DP8=0x%04X"
          % (mem.r16(DP2), mem.r16(DP7), mem.r16(DP8)))

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        return 1
    print("OUTPUT BACKEND PROOF PASSES - the configured cavity decides which "
          "pin moves, three conditions gate it, and the resting state is high "
          "impedance. NOTHING HERE IS ELECTRICAL PROOF: the active polarity of "
          "each stage is still unmeasured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
