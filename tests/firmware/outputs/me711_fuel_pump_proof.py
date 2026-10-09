#!/usr/bin/env python3
r"""
me711_fuel_pump_proof.py - the fuel pump, twice: the lifecycle as the linked
image runs it, and the EKP pin as the bench qualifier drives it.

    py tests\firmware\outputs\me711_fuel_pump_proof.py

WHY THIS EXISTS.

Until 2026-09-02 hcbench.h said "no MAIN CPU port for [the fuel pump] appears
in the Bosch port sheet's ME7.1.1 columns". That was never true. EKP is MAIN
CPU P2.12 / CC12IO, CPU pin 61, "EKP-Ansteuerung", and BOTH ME7.1.1 columns
agree - it is row 68 of this repository's OWN generated
tools/config_source/data/me711_iomap.csv, and the row is regenerated from Bosch's
workbook by an OEM-firmware analysis script (not published). A subsystem was blocked for weeks on
evidence that was already checked in.

So this gate does two things that a comment cannot:

PART ONE - THE LIFECYCLE, EXECUTED. hc_fuelpump_service() is called in the
linked image, on the C167 simulator, through the whole key-on -> prime ->
crank -> run -> stall sequence, and the state and the command are read back
out of the firmware's own variables after each step. The transitions that
matter are asserted individually:

  * the prime is BOUNDED - it ends on its own with no engine
  * it happens ONCE PER KEY CYCLE, not once per stall
  * cranking and running both command the pump ON
  * A STALL COMMANDS IT OFF ON THE SAME PASS. This is the whole reason a
    fuel pump relay exists and it gets its own check.
  * a runtime fault commands OFF and LATCHES
  * ignition off commands OFF and re-arms the prime

PART TWO - THE PIN, ATTACKED. The same negative and positive controls
me711_bench_output_proof.py applies to an injector, applied to the '!T'
bytes the .ini sends for the fuel pump: with an invariant broken, not one
write to P2/DP2/ODP2; with all of them met, writes that land inside
hcbench's own code and nowhere else.

WHY IT CANNOT PASS VACUOUSLY. Part one asserts BOTH edges of every
transition - a stub that always answered OFF fails the cranking check, and
one that always answered ON fails the stall check. Part two has an explicit
positive control, for the reason recorded in me711_bench_output_proof: a
gate that cannot observe a success proves nothing when it observes a failure.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_bench_output_proof as BOP     # noqa: E402
import me711_heartbeat_gap_proof as HB     # noqa: E402
import me711_image as PI                   # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
SHARED = ROOT / "firmware"
IOMAP = ROOT / "tools/config_source/data/me711_iomap.csv"
HDR = ROOT / "firmware/targets/me711/hctarget.h"
FP_H = SHARED / "control/hcfuelpump.h"

SENTINEL = 0x0002

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-56s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def sym(name):
    for m in re.finditer(r"^\s*([0-9A-F]{6})H\s+(\w+)\s",
                         PI.MAP.read_text(errors="replace"), re.M):
        if m.group(2) == name:
            return int(m.group(1), 16)
    raise SystemExit("%s is not in the map - build the target first" % name)


def gen_off(name):
    """A page offset from the generated header - never a literal."""
    for f in (ROOT / "firmware/generated/hc_config_generated.h",
              ROOT / "firmware/config/hcconfig.h"):
        m = re.search(r"#define\s+%s\s+(\d+)u?" % name,
                      f.read_text(errors="replace"))
        if m:
            return int(m.group(1))
    raise SystemExit("%s is not defined" % name)


def fp_const(name):
    m = re.search(r"#define\s+%s\s+(0x[0-9A-Fa-f]+|\d+)u" % name,
                  FP_H.read_text(errors="replace"))
    if not m:
        raise SystemExit("%s is not in hcfuelpump.h" % name)
    return int(m.group(1), 0)


TRG_NO_SIGNAL = 0
TRG_COUNTING = 1
TRG_SYNC_FULL = 4


class Pump:
    """Drives the REAL compiled hc_fuelpump_service() in the linked image.

    Argument registers are read out of the compiler's own listing
    (build/hcfuelpump_code.lst): R8 now_ms, R9 ign_on, R10 rpm,
    R11 trig_state, R12 fault. The stack and register bank are the ones the
    real startup established - this project has three recorded incidents of a
    rig writing its own call frame over the module under test.
    """

    def __init__(self, img):
        self.rig = HB.Rig(img, HB.ENTRY_CURRENT, HB.TICK_CURRENT, echo=False)
        self.rig.run(600_000)
        self.cpu = self.rig.cpu
        self.svc = sym("hc_fuelpump_service")
        self.init = sym("hc_fuelpump_init")
        # THROUGH THE PUBLIC ACCESSORS, not through the statics. The module's
        # private variables are not in the linker map at all - and reading
        # them would test a layout rather than the interface the rest of the
        # firmware actually uses.
        self.f_state = sym("hc_fuelpump_state")
        self.f_cmd = sym("hc_fuelpump_command")
        self.f_reason = sym("hc_fuelpump_reason")

    def _call(self, addr, args=()):
        cpu = self.cpu
        # An EXTS/EXTP prefix may still be armed if the boot
        # stopped on one, and an injected call would run under a segment
        # override belonging to code we are not executing. See
        # me711_nvm_proof.Ecu.call().
        saved = (cpu.csp, cpu.ip, cpu.m.sfr[0xFE12], cpu.ext)
        cpu.ext = None
        cpu.push(SENTINEL)
        cpu.csp = (addr >> 16) & 0xFF
        cpu.ip = addr & 0xFFFF
        for i, v in enumerate(args):
            cpu.sr(8 + i, v & 0xFFFF)
        for _ in range(200_000):
            if (cpu.ip & 0xFFFF) == SENTINEL:
                break
            cpu.step()
        else:
            raise SystemExit("call to 0x%06X did not return" % addr)
        out = cpu.gr(4) & 0xFFFF
        cpu.csp, cpu.ip, cpu.m.sfr[0xFE12], cpu.ext = saved
        return out

    def reset(self):
        """Init, then SELECT AUTO EXPLICITLY.

        The mode defaults to OFF and that is deliberate: a page that has not
        been configured must not command a fuel pump. So every lifecycle
        vector below is a statement about AUTO, and the OFF default gets its
        own check rather than being assumed away."""
        self._call(self.init)
        self._call(sym("hc_cal_set_u8"),
                   (gen_off("CFG_U_FUEL_PUMP_MODE"), 1))

    def service(self, ms, ign, rpm, trig, fault):
        self._call(self.svc, (ms, ign, rpm, trig, fault))
        return (self._call(self.f_state) & 0xFF,
                self._call(self.f_cmd) & 0xFF,
                self._call(self.f_reason))


def part_one(img):
    print("  --- the lifecycle, executed in the linked image ---")
    p = Pump(img)

    # MODE OFF IS THE DEFAULT AND IT MUST REFUSE. Checked before anything
    # selects AUTO, so the default is proven rather than assumed.
    p._call(p.init)
    st, cmd, rs = p.service(1000, 1, 0, TRG_NO_SIGNAL, 0)
    check("the DEFAULT mode is OFF and never commands the pump",
          st == fp_const("FP_OFF") and cmd == 0,
          "state=%d command=%d reason=0x%04X - a page nobody configured must "
          "not run a fuel pump" % (st, cmd, rs))

    p.reset()

    st, cmd, _ = p.service(0, 0, 0, TRG_NO_SIGNAL, 0)
    check("before the key: OFF and the pump is not commanded",
          st == fp_const("FP_OFF") and cmd == 0,
          "state=%d command=%d" % (st, cmd))

    # ---- key on: the bounded prime -------------------------------------
    # V84: the permission is withheld FROM KEY-ON (see the HELD check below).
    for nm in ("hc_dbw_allowed", "hc_ignition_allowed", "hc_injection_allowed"):
        p.rig.mem.w16(sym(nm) & 0xFFFF, 0)
    st, cmd, _ = p.service(1000, 1, 0, TRG_NO_SIGNAL, 0)
    check("key on with no engine: PRIME, and the pump IS commanded",
          st == fp_const("FP_PRIME") and cmd == 1,
          "state=%d command=%d" % (st, cmd))

    # V75: THE PRIME IS THE CONFIGURED TIME AT THE PIN, so its timer starts
    # when the HAL first PERMITS the output. V84: there is no page arm any
    # more, so the rig WITHHOLDS THE PERMISSION explicitly - the ALWAYS-class
    # flag cleared, as an S5500 link loss, a refused page or a key-off does -
    # and the prime must be HELD - requested, refused, reason INHIBIT - and must
    # NOT quietly time out while nothing could reach the pin (that was the
    # pre-V75 behaviour: a prime spent entirely while the output was not yet
    # permitted). The timed end, at eight configured durations with the page
    # armed, is me711_relay_pump_port_proof part B.
    st, cmd, rs = p.service(1000 + 30_000, 1, 0, TRG_NO_SIGNAL, 0)
    check("not permitted: the prime is HELD, not spent where no pin can move",
          st == fp_const("FP_PRIME") and cmd == 1
          and rs == fp_const("FP_R_INHIBIT"),
          "state=%d command=%d reason=0x%04X" % (st, cmd, rs))

    # ---- cranking ------------------------------------------------------
    st, cmd, _ = p.service(40_000, 1, 120, TRG_COUNTING, 0)
    check("edges arriving without sync: CRANKING, pump ON",
          st == fp_const("FP_CRANKING") and cmd == 1,
          "state=%d command=%d" % (st, cmd))

    st, cmd, _ = p.service(41_000, 1, 800, TRG_SYNC_FULL, 0)
    check("synchronised: RUNNING, pump ON",
          st == fp_const("FP_RUNNING") and cmd == 1,
          "state=%d command=%d" % (st, cmd))

    # ---- THE ONE THAT MATTERS ------------------------------------------
    st, cmd, rs = p.service(41_050, 1, 0, TRG_NO_SIGNAL, 0)
    check("THE ENGINE STOPS: pump OFF on the SAME pass",
          st == fp_const("FP_STOPPED") and cmd == 0
          and (rs & fp_const("FP_R_STALL")) != 0,
          "state=%d command=%d reason=0x%04X - not after a timeout, not "
          "after a confirmation" % (st, cmd, rs))

    # ---- and no second prime -------------------------------------------
    st, cmd, _ = p.service(42_000, 1, 0, TRG_NO_SIGNAL, 0)
    check("a stall does NOT re-prime", cmd == 0,
          "state=%d command=%d - the second prime is the one that runs a "
          "pump into a leak nobody noticed the first time" % (st, cmd))

    # ---- a runtime fault latches ---------------------------------------
    st, cmd, rs = p.service(43_000, 1, 800, TRG_SYNC_FULL, 1)
    check("a runtime fault commands OFF",
          st == fp_const("FP_FAULT") and cmd == 0,
          "state=%d command=%d reason=0x%04X" % (st, cmd, rs))
    st, cmd, _ = p.service(44_000, 1, 800, TRG_SYNC_FULL, 0)
    check("and it LATCHES when the fault clears", cmd == 0,
          "state=%d command=%d - only hc_fuelpump_init() clears it"
          % (st, cmd))

    # ---- ignition off re-arms ------------------------------------------
    p.reset()
    p.service(0, 1, 0, TRG_NO_SIGNAL, 0)           # prime starts
    st, cmd, rs = p.service(100, 0, 0, TRG_NO_SIGNAL, 0)
    check("ignition off commands OFF immediately",
          st == fp_const("FP_OFF") and cmd == 0
          and (rs & fp_const("FP_R_IGNOFF")) != 0,
          "state=%d command=%d reason=0x%04X" % (st, cmd, rs))
    st, cmd, _ = p.service(200, 1, 0, TRG_NO_SIGNAL, 0)
    check("and a key cycle DOES re-arm the prime",
          st == fp_const("FP_PRIME") and cmd == 1,
          "state=%d command=%d" % (st, cmd))


def part_two():
    print("\n  --- the EKP pin, attacked ---")

    # The evidence, checked against the generated map rather than retyped.
    row = [ln for ln in IOMAP.read_text(errors="replace").splitlines()
           if ",EKP," in ln]
    check("Bosch's own port map still says EKP is on a MAIN CPU pin",
          len(row) == 1 and row[0].startswith("MAIN CPU,61,P2.12,")
          and "both ME7.1.1 columns agree" in row[0],
          row[0][:96] if row else "no EKP row in me711_iomap.csv")

    m = re.search(r"#define\s+TGT_EKP_PORT_BIT\s+(\d+)",
                  HDR.read_text(errors="replace"))
    check("and hctarget.h names the same bit",
          m is not None and int(m.group(1)) == 12,
          "TGT_EKP_PORT_BIT = %s, the map says P2.12"
          % (m.group(1) if m else "missing"))

    cmd = BOP.ini_command("cmdTestPump")
    print("      the '!T' bytes the .ini sends: %s"
          % " ".join("%02X" % b for b in cmd))

    # V84: no page arm. The refusal case is now an INVALID PAGE - the
    # invariant that still stands between a button and a pin.
    r = BOP.run_case_subprocess(False, False, "cmdTestPump")
    check("invalid page: not one write to any output port",
          not r["writes"],
          "state=%d refuse=0x%04X" % (r["state"], r["refuse"])
          if not r["writes"] else "%d WRITE(S)" % len(r["writes"]))
    check("and the firmware says which invariant it refused on",
          (r["refuse"] & BOP.refuse_bit("CFG")) != 0
          and (r["refuse"] & BOP.refuse_bit("ARMED")) == 0,
          "refuse 0x%04X includes HCB_R_CFG, never the retired HCB_R_ARMED"
          % r["refuse"])

    r = BOP.run_case_subprocess(True, True, "cmdTestPump", steps=9_000_000)
    check("with every invariant met, nothing is refused", r["refuse"] == 0,
          "hcbRefuse = 0x%04X, hcbState = %d" % (r["refuse"], r["state"]))
    check("with every invariant met, the EKP pin IS driven",
          bool(r["writes"]),
          "%d write(s), first %s" % (len(r["writes"]), r["writes"][0][1])
          if r["writes"] else
          "NOTHING MOVED - this gate cannot see a success, so its negative "
          "results mean nothing")
    if r["writes"]:
        ports = sorted({nm for _pc, nm in r["writes"]})
        # BOTH OF THESE CHANGED AT V63, AND NEITHER GOT WEAKER.
        #
        # Until V63 hcbench.c was the ONLY code on this board that could write
        # a port, so "every write is on P2" and "every write is inside
        # hcbench" were exact statements of "nothing else can drive a pin".
        #
        # V63 gave the board an output back end. hc_hal_outputs_safe() now
        # drives EVERY engine output to its inactive level and back to INPUT -
        # P2, P7 and P8 - and it runs at init and on every withdrawal of
        # arming. So a fuel-pump run legitimately writes DP7/P7 as well, from
        # inside hchal_me711.c rather than hcbench, and the old checks failed
        # on the safe-state routine doing exactly its job.
        #
        # THE PROPERTY WORTH ASSERTING IS NOT "ONLY P2" - it is that the only
        # port left DRIVEN at the end is the one being tested, and that every
        # write came from code entitled to make it. Both are checked below,
        # and the second is now a two-module allow-list rather than a
        # monopoly.
        allowed_ports = {"P2", "DP2", "ODP2", "P7", "DP7", "ODP7",
                         "P8", "DP8", "ODP8"}
        check("every port written is an engine-output port",
              set(ports) <= allowed_ports, "wrote %s" % ", ".join(ports))

        lo, hi = BOP.seg_range("?PR?HCBENCH")
        hlo, hhi = BOP.seg_range("?PR?HCHAL_ME711")
        pcs = [w[0] for w in r["writes"]]
        outside = [pc for pc in pcs
                   if not (lo <= pc <= hi or hlo <= pc <= hhi)]
        check("every write comes from hcbench or the HAL back end, and "
              "nowhere else", not outside,
              "hcbench 0x%06X-0x%06X, hal 0x%06X-0x%06X; %s"
              % (lo, hi, hlo, hhi,
                 "all accounted for" if not outside
                 else "STRAY: %s" % [hex(x) for x in outside[:4]]))

        # AND THE ONE THAT MATTERS MOST, which the old pair only implied:
        # nothing OTHER than the pump is left driven when the run is over.
        dp2, dp7, dp8 = r["dp"][0], r["dp"][1], r["dp"][2]
        coils = dp2 & 0x007F          # P2.0..P2.6, the seven routable coils
        inj = (dp7 & 0x0070) | (dp8 & 0x00F8)
        check("no coil or injector pin is left an OUTPUT by a pump run",
              coils == 0 and inj == 0,
              "DP2 coils=0x%04X DP7/DP8 injectors=0x%04X" % (coils, inj))
        check("the pin is an INPUT again at the end",
              (r["dp"][0] & (1 << 12)) == 0,
              "DP2 = 0x%04X, bit 12 clear" % r["dp"][0])


def main() -> int:
    global CHECKS, FAILS
    img = PI.image()
    BOP.HC_CFG = BOP.sym("hc_cfg")
    print("=== HaniCore ME7.1.1 - the fuel pump, lifecycle and pin ===\n")
    print("  image   %s" % img.name)
    print("  sha256  %s\n" % PI.sha256())

    part_one(img)
    part_two()

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("FUEL PUMP PROOF FAILS - either the lifecycle no longer stops "
              "the pump when the engine stops, or the bench path's "
              "invariants are not being enforced.")
        return 1
    print("FUEL PUMP PROOF PASSES - the pump stops when the engine stops, "
          "the prime is bounded and happens once per key cycle, a fault "
          "latches it off, and the EKP pin moves only under every bench "
          "invariant at once.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
