#!/usr/bin/env python3
r"""
me711_relay_pump_port_proof.py - the main relay and the fuel pump, as the
CONFIGURATION says, at the CPU PORT, in the linked image.

    py tests\firmware\outputs\me711_relay_pump_port_proof.py

WHAT V75 CHANGED, AND WHAT THIS HOLDS:

1. THE BOOT-TIME FAULT LATCH. Until V75 hcmain_me711.c handed both lifecycles
   `hc_safety_inhibits != 0` as their LATCHING fault input. That word carries
   NO_CRANK and NO_CYCLE - set whenever the engine is not synchronised - and
   hc_safety_init() seeds it to 0x3F. So on the first main-loop pass after
   every boot, the pump and the relay latched FAULT and nothing short of a
   reset could clear it: no prime, no pump while cranking, no AUTO relay.
   PART A runs the REAL main loop and reads the lifecycle states back. Against
   V74 (HANICORE_ME711_STEM=HaniCore_ME711_v74_bench_candidate) it FAILS.

2. CONFIGURED BEHAVIOUR, NOT ONE COMPILED POLICY. The prime is timed from
   CAL_FUELPUMP_PRIME_MS at several values and both boundaries; the relay's
   release delay from CFG_U_MAIN_RELAY_HOLD_MS at several values.

3. PERMISSION IS A LEVEL. An ON asked for before the output was permitted
   reaches the pin when permission arrives; a withdrawn permission releases
   the pin on that pass; an OFF is never refused.

4. THE RELAY IS BOUND to its configured cavity through the same resolution
   the pump uses, and releases every cavity it stops driving.

HOW. The page is armed mid-boot exactly as me711_armed_off_release_proof does
it, and the real compiled functions are CALLED through their own argument
registers. Pin state is DP2/P2 read out of the simulated SFRs. Permission is
withdrawn by clearing the three class-permission words hcsafety.c publishes -
the same words the HAL asks.

WHAT THIS DOES NOT PROVE: anything outside the CPU. The CJ920 stage at cavity
65 is unmeasured and its polarity is INFERRED; no relay or pump is connected.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_armed_off_release_proof as AOR   # noqa: E402
import me711_image as PI                      # noqa: E402

sym, gen_off, tgt_int = AOR.sym, AOR.gen_off, AOR.tgt_int

TRG_NO_SIGNAL, TRG_COUNTING, TRG_SYNC_CRANK, TRG_SYNC_FULL = 0, 1, 3, 4
FP_OFF, FP_PRIME, FP_CRANKING, FP_RUNNING, FP_STOPPED, FP_FAULT = range(6)
MR_INIT, MR_REQUEST, MR_RUNNING, MR_SHUTDOWN, MR_RELEASED, MR_FAULT = range(6)
FP_R = dict(IGNOFF=1, PRIMEDONE=2, STALL=4, CFG=8, FAULT=16, DISABLED=32,
            INHIBIT=64)
FP_FAULT_RUNTIME, FP_FAULT_CFG = 1, 2
PIN_NONE = 255

CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))


def has(name):
    try:
        sym(name)
        return True
    except SystemExit:
        return False


class Ecu(AOR.Rig):
    def __init__(self, img):
        super().__init__(img)
        self.ekp = 1 << tgt_int("TGT_EKP_PORT_BIT")
        # THE STAGE'S ACTIVE LEVEL, from the header the firmware compiles.
        # V76 MEASURED it LOW (logic analyzer on cavity 65); an image from
        # before that has no constant and is judged by its own claim, HIGH.
        try:
            self.ekp_act = bool(tgt_int("TGT_EKP_ACTIVE_HIGH"))
        except SystemExit:
            self.ekp_act = True

    # ---- the port ------------------------------------------------------
    def pin65(self):
        """(driven-as-output, level) of P2.12 = cavity 65."""
        dp2 = self.rig.mem.r16(0xFFC2)
        p2 = self.rig.mem.r16(0xFFC0)
        return bool(dp2 & self.ekp), bool(p2 & self.ekp)

    def active65(self):
        out, lvl = self.pin65()
        return out and lvl == self.ekp_act

    def latch_inactive65(self):
        """The P2.12 LATCH holds the stage's INACTIVE level. The HAL writes
        the latch and THEN drops the direction, so if the latch is at the
        ACTIVE level the release itself energises the stage - measured on
        V75: cavity 65 sank for 13-14 us on every release."""
        return self.pin65()[1] != self.ekp_act

    def release65_externally(self):
        """What the bench qualifier's exit path does: EKPD = 0."""
        a = 0xFFC2
        self.rig.mem.w16(a, self.rig.mem.r16(a) & ~self.ekp & 0xFFFF)

    # ---- the permission layer -------------------------------------------
    def permit(self, on):
        for n in ("hc_dbw_allowed", "hc_ignition_allowed",
                  "hc_injection_allowed"):
            self.rig.mem.w16(sym(n) & 0xFFFF, 1 if on else 0)

    # ---- config ---------------------------------------------------------
    def set8(self, name, v):
        self.call(sym("hc_cal_set_u8"), (gen_off(name), v))

    def set16(self, name, v):
        self.call(sym("hc_cal_set_u16"), (gen_off(name), v))

    # ---- pump -----------------------------------------------------------
    def fp_init(self):
        self.call(sym("hc_fuelpump_init"))

    def fp(self, ms, trig=TRG_NO_SIGNAL, fault=0, ign=1, rpm=0):
        self.call(sym("hc_fuelpump_service"), (ms, ign, rpm, trig, fault))
        return dict(st=self.call(sym("hc_fuelpump_state")) & 0xFF,
                    cmd=self.call(sym("hc_fuelpump_command")) & 0xFF,
                    rs=self.call(sym("hc_fuelpump_reason")),
                    left=self.call(sym("hc_fuelpump_prime_left")),
                    pin=self.active65())

    # ---- relay ----------------------------------------------------------
    def mr_init(self):
        self.call(sym("hc_main_relay_init"))

    def mr(self, ms, req=1, fault=0):
        self.call(sym("hc_main_relay_service"), (ms, req, fault))
        return dict(st=self.call(sym("hc_main_relay_get_state")) & 0xFF,
                    cmd=self.call(sym("hc_main_relay_get_command")) & 0xFF,
                    bound=self.call(sym("hc_main_relay_get_bound")) & 0xFF,
                    drv=self.call(sym("hc_hal_main_relay_driven")) & 0xFF,
                    inh=self.call(sym("hc_hal_main_relay_inhibited")) & 0xFF,
                    pin=self.active65())


def part_a_boot(e):
    """THE REAL MAIN LOOP, after boot. No service is called by hand here."""
    print("\n  --- A. after boot, the real main loop owns both lifecycles ---")
    st = e.call(sym("hc_fuelpump_state")) & 0xFF
    rs = e.call(sym("hc_fuelpump_reason"))
    check("pump is NOT latched FAULT after a normal boot", st != FP_FAULT,
          "state=%d reason=0x%04X (V74: 5 FAULT, from NO_CRANK)" % (st, rs))
    check("pump default mode OFF: state OFF, reason DISABLED",
          st == FP_OFF and rs == FP_R["DISABLED"],
          "state=%d reason=0x%04X" % (st, rs))
    mst = e.call(sym("hc_main_relay_get_state")) & 0xFF
    check("relay is NOT latched FAULT after a normal boot", mst != MR_FAULT,
          "state=%d (V74: 5 FAULT)" % mst)
    check("relay default mode OFF: RELEASED, command 0",
          mst == MR_RELEASED
          and (e.call(sym("hc_main_relay_get_command")) & 0xFF) == 0,
          "state=%d" % mst)
    check("power-on: cavity 65 is NOT driven", not e.active65(),
          "DP2/P2 bit 12 = %s" % (e.pin65(),))
    check("power-on: P2.12 latch at the INACTIVE level (%s)"
          % ("LOW" if e.ekp_act else "HIGH"), e.latch_inactive65(),
          "DP2/P2 bit 12 = %s" % (e.pin65(),))

    if not has("hc_hal_main_relay_driven"):
        return False          # an older image: part A is the whole question

    # AUTO selected by a page write, then the REAL loop runs on.
    e.set8("CFG_U_FUEL_PUMP_MODE", 1)
    e.set16("CAL_FUELPUMP_PRIME_MS", 3000)
    e.rig.run(300_000)
    st = e.call(sym("hc_fuelpump_state")) & 0xFF
    check("AUTO + armed: the real loop PRIMES and DRIVES the pin",
          st == FP_PRIME and e.active65(),
          "state=%d pin=%s left=%d ms" % (st, e.pin65(),
                                          e.call(sym("hc_fuelpump_prime_left"))))
    e.set8("CFG_U_FUEL_PUMP_MODE", 0)
    e.rig.run(100_000)
    check("mode back to OFF: the real loop RELEASES the pin",
          not e.pin65()[0], "DP2/P2 bit 12 = %s" % (e.pin65(),))
    check("...through the INACTIVE level: no release pulse at the cavity",
          e.latch_inactive65(), "DP2/P2 bit 12 = %s" % (e.pin65(),))

    # And the relay through the real loop: cavity 65, pump unrouted.
    e.set8("CFG_U_PIN_FUEL_PUMP", PIN_NONE)
    e.set8("CFG_U_PIN_MAIN_RELAY", 65)
    e.set8("CFG_MAIN_RELAY_MODE", 2)
    e.rig.run(300_000)
    mst = e.call(sym("hc_main_relay_get_state")) & 0xFF
    check("AUTO relay: the real loop REQUESTS (run_request = CPU alive)",
          mst in (MR_REQUEST, MR_RUNNING) and e.active65(),
          "state=%d pin=%s" % (mst, e.pin65()))
    e.set8("CFG_MAIN_RELAY_MODE", 0)
    e.rig.run(100_000)
    check("relay mode OFF: the real loop RELEASES cavity 65",
          not e.pin65()[0], "DP2/P2 bit 12 = %s" % (e.pin65(),))
    check("...through the INACTIVE level: no release pulse at the cavity",
          e.latch_inactive65(), "DP2/P2 bit 12 = %s" % (e.pin65(),))
    e.set8("CFG_U_PIN_MAIN_RELAY", PIN_NONE)
    e.set8("CFG_U_PIN_FUEL_PUMP", 65)
    return True


def part_b_pump(e):
    print("\n  --- B. the pump, CONFIGURED prime times, at the pin ---")
    e.set8("CFG_U_PIN_FUEL_PUMP", 65)
    e.set8("CFG_U_PIN_MAIN_RELAY", PIN_NONE)
    e.permit(True)

    # The prime, at several configured values and both boundaries. The
    # expected duration is the configured value, clamped to 5000.
    for cfg_ms in (1, 250, 1500, 3000, 4999, 5000, 5001, 65535):
        want = min(cfg_ms, 5000)
        e.fp_init()
        e.set8("CFG_U_FUEL_PUMP_MODE", 1)
        e.set16("CAL_FUELPUMP_PRIME_MS", cfg_ms)
        t0 = 10_000
        a = e.fp(t0)
        b = e.fp(t0 + want - 1)
        c = e.fp(t0 + want)
        ok = (a["st"] == FP_PRIME and a["cmd"] == 1 and a["pin"]
              and a["left"] == want
              and b["cmd"] == 1 and b["pin"] and b["left"] == 1
              and c["st"] == FP_OFF and c["cmd"] == 0 and not c["pin"]
              and c["rs"] == FP_R["PRIMEDONE"] and not e.pin65()[0])
        check("prime %5d ms configured -> %4d ms at the pin" % (cfg_ms, want),
              ok, "start %s/%s  t-1 %s  t %s/released=%s"
              % (a["st"], a["left"], b["pin"], c["st"], not e.pin65()[0]))

    e.fp_init()
    e.set8("CFG_U_FUEL_PUMP_MODE", 1)
    e.set16("CAL_FUELPUMP_PRIME_MS", 0)
    a = e.fp(1000)
    check("prime 0 ms: no prime at all, reason DISABLED",
          a["st"] == FP_OFF and a["cmd"] == 0 and not a["pin"]
          and a["rs"] == FP_R["DISABLED"], str(a))

    # ---- the prime waits for permission --------------------------------
    e.fp_init()
    e.set8("CFG_U_FUEL_PUMP_MODE", 1)
    e.set16("CAL_FUELPUMP_PRIME_MS", 2000)
    e.permit(False)
    a = e.fp(1000)
    b = e.fp(9000)
    check("not permitted: PRIME held, request ON, reason INHIBIT, pin free",
          a["st"] == FP_PRIME and a["cmd"] == 1 and not a["pin"]
          and a["rs"] == FP_R["INHIBIT"] and not e.pin65()[0], str(a))
    check("...and the prime TIMER does not run until permitted",
          b["st"] == FP_PRIME and b["left"] == 2000, str(b))
    e.permit(True)
    c = e.fp(9500)
    d = e.fp(9500 + 1999)
    f = e.fp(9500 + 2000)
    check("permission arrives: the SAME request reaches the pin",
          c["pin"] and c["rs"] == 0, str(c))
    check("...and it runs the FULL configured 2000 ms from there",
          d["pin"] and f["st"] == FP_OFF and not f["pin"],
          "t+1999 pin=%s  t+2000 state=%d pin=%s" % (d["pin"], f["st"],
                                                     f["pin"]))

    # ---- disarm mid-prime releases; re-permit re-drives ------------------
    e.fp_init()
    e.set8("CFG_U_FUEL_PUMP_MODE", 1)
    e.set16("CAL_FUELPUMP_PRIME_MS", 3000)
    a = e.fp(0)
    e.permit(False)
    b = e.fp(500)
    b_dir = e.pin65()[0]            # the DIRECTION, read at that pass
    e.permit(True)
    c = e.fp(1000)
    check("permission withdrawn mid-prime: pin RELEASED that pass",
          a["pin"] and not b["pin"] and not b_dir
          and b["rs"] == FP_R["INHIBIT"] and b["cmd"] == 1,
          "before %s  after %s (output=%s) %s" % (a["pin"], b["pin"],
                                                  b_dir, b))
    check("...permission back inside the prime: pin driven again",
          c["pin"] and c["st"] == FP_PRIME, str(c))

    # ---- crank, run, stall, repeated ------------------------------------
    e.fp_init()
    e.set8("CFG_U_FUEL_PUMP_MODE", 1)
    e.set16("CAL_FUELPUMP_PRIME_MS", 1000)
    e.fp(0)
    e.fp(1000)                                      # prime done
    bad = []
    t = 2000
    for i in range(20):
        c = e.fp(t, TRG_COUNTING, rpm=150)
        r = e.fp(t + 100, TRG_SYNC_CRANK, rpm=800)
        s = e.fp(t + 200, TRG_NO_SIGNAL)
        if not (c["st"] == FP_CRANKING and c["pin"]
                and r["st"] == FP_RUNNING and r["pin"]
                and s["st"] == FP_STOPPED and not s["pin"]
                and s["rs"] == FP_R["STALL"] and not e.pin65()[0]):
            bad.append((i, c, r, s))
        t += 1000
    check("20 x crank -> run -> STALL: pin follows, released on the stall pass",
          not bad, "first failure %s" % (bad[0],) if bad else "")
    runs = e.call(sym("hc_fuelpump_runs"))
    check("...and the run counter counts transitions, not passes",
          runs == 1 + 20, "runs=%d (1 prime + 20 cranks)" % runs)
    s = e.fp(t + 5000, TRG_NO_SIGNAL)
    check("a stall never re-primes", s["cmd"] == 0 and not s["pin"], str(s))

    # ---- fault latches ----------------------------------------------------
    e.fp_init()
    e.set8("CFG_U_FUEL_PUMP_MODE", 1)
    e.set16("CAL_FUELPUMP_PRIME_MS", 1000)
    e.fp(0, TRG_SYNC_FULL)
    a = e.fp(10, TRG_SYNC_FULL, fault=FP_FAULT_CFG)
    b = e.fp(20, TRG_SYNC_FULL, fault=0)
    check("settled-page fault: OFF, pin released, reason CFG",
          a["st"] == FP_FAULT and not a["pin"] and a["rs"] == FP_R["CFG"],
          str(a))
    check("...and it LATCHES when the fault clears",
          b["st"] == FP_FAULT and not b["pin"], str(b))
    e.fp_init()
    e.set8("CFG_U_FUEL_PUMP_MODE", 1)
    a = e.fp(0, TRG_SYNC_FULL, fault=FP_FAULT_RUNTIME)
    check("runtime fault: reason FAULT", a["rs"] == FP_R["FAULT"], str(a))

    # ---- ignition off (a target that has the input) ---------------------
    e.fp_init()
    e.set8("CFG_U_FUEL_PUMP_MODE", 1)
    e.fp(0, TRG_SYNC_FULL)
    a = e.fp(10, TRG_NO_SIGNAL, ign=0)
    check("ignition off: OFF and released at once",
          a["st"] == FP_OFF and not a["pin"] and a["rs"] == FP_R["IGNOFF"],
          str(a))


def part_c_relay(e):
    print("\n  --- C. the main relay, CONFIGURED, at the pin ---")
    e.permit(True)
    e.set8("CFG_U_PIN_FUEL_PUMP", PIN_NONE)
    e.fp_init()                       # the pump owns nothing now

    e.set8("CFG_U_PIN_MAIN_RELAY", PIN_NONE)
    e.mr_init()
    e.set8("CFG_MAIN_RELAY_MODE", 2)
    a = e.mr(0)
    check("unassigned cavity: request ON, bound 0, NOTHING driven",
          a["cmd"] == 1 and a["bound"] == 0 and not a["drv"]
          and not e.pin65()[0], str(a))

    e.set8("CFG_U_PIN_MAIN_RELAY", 65)
    e.mr_init()
    st = e.call(sym("hc_main_relay_get_state")) & 0xFF
    cmd = e.call(sym("hc_main_relay_get_command")) & 0xFF
    check("init: command 0, INIT, pin released",
          st == MR_INIT and cmd == 0 and not e.pin65()[0],
          "state=%d cmd=%d pin=%s" % (st, cmd, e.pin65()))
    e.set8("CFG_MAIN_RELAY_MODE", 2)
    a = e.mr(1000)
    b = e.mr(1199)
    c = e.mr(1200)
    check("AUTO on cavity 65: REQUEST, bound, pin DRIVEN at once",
          a["st"] == MR_REQUEST and a["bound"] == 1 and a["drv"]
          and a["pin"], str(a))
    check("...RUNNING after the 200 ms settle, not before",
          b["st"] == MR_REQUEST and c["st"] == MR_RUNNING and c["pin"],
          "t+199 %d  t+200 %d" % (b["st"], c["st"]))

    # The release delay, at several configured values.
    for hold in (0, 250, 1000, 60000):
        e.mr_init()
        e.set8("CFG_MAIN_RELAY_MODE", 2)
        e.set16("CFG_U_MAIN_RELAY_HOLD_MS", hold)
        e.mr(0)
        e.mr(500)                                    # RUNNING
        d = e.mr(1000, req=0)
        if hold == 0:
            ok = d["st"] == MR_RELEASED and not d["pin"] and not e.pin65()[0]
            det = "same pass: %s" % d
        else:
            x = e.mr(1000 + hold - 1, req=0)
            y = e.mr(1000 + hold, req=0)
            ok = (d["st"] == MR_SHUTDOWN and d["pin"] and x["pin"]
                  and y["st"] == MR_RELEASED and not y["pin"]
                  and not e.pin65()[0])
            det = "held %s..%s, released %s" % (d["pin"], x["pin"],
                                                not y["pin"])
        check("run request drops, hold %5d ms -> released after %d ms"
              % (hold, hold), ok, det)
    e.set16("CFG_U_MAIN_RELAY_HOLD_MS", 0)

    # Shutdown cancelled by the request coming back.
    e.mr_init()
    e.set8("CFG_MAIN_RELAY_MODE", 2)
    e.set16("CFG_U_MAIN_RELAY_HOLD_MS", 1000)
    e.mr(0); e.mr(500)
    e.mr(600, req=0)
    a = e.mr(700, req=1)
    check("request returns inside the hold: RUNNING, never released",
          a["st"] == MR_RUNNING and a["pin"], str(a))
    e.set16("CFG_U_MAIN_RELAY_HOLD_MS", 0)

    # Permission is a level.
    e.mr_init()
    e.set8("CFG_MAIN_RELAY_MODE", 2)
    e.mr(0)
    e.permit(False)
    a = e.mr(10)
    check("permission withdrawn: pin RELEASED, inhibited flag set",
          not a["pin"] and not e.pin65()[0] and a["inh"] == 1
          and a["cmd"] == 1, str(a))
    e.permit(True)
    b = e.mr(20)
    check("permission back: re-driven, flag clear",
          b["pin"] and b["inh"] == 0, str(b))

    # Somebody else released the pin: the level call re-drives it.
    e.release65_externally()
    c = e.mr(30)
    check("pin released behind the relay's back is re-driven next pass",
          c["pin"] and c["drv"], str(c))

    # The route moves while driven.
    e.set8("CFG_U_PIN_MAIN_RELAY", PIN_NONE)
    d = e.mr(40)
    check("route removed while driven: the OLD cavity is released",
          not e.pin65()[0] and not d["drv"], str(d))
    e.set8("CFG_U_PIN_MAIN_RELAY", 65)

    # Manual overrides.
    e.mr_init()
    e.set8("CFG_MAIN_RELAY_MODE", 1)
    a = e.mr(0, req=0)
    e.set8("CFG_MAIN_RELAY_MODE", 0)
    b = e.mr(10, req=1)
    check("mode ON drives regardless of the request; mode OFF releases",
          a["pin"] and not b["pin"] and not e.pin65()[0],
          "ON %s  OFF %s" % (a["pin"], b["pin"]))

    # Fault latches.
    e.mr_init()
    e.set8("CFG_MAIN_RELAY_MODE", 2)
    e.mr(0)
    a = e.mr(10, fault=1)
    b = e.mr(20, fault=0)
    check("fault: released at once, and LATCHED",
          a["st"] == MR_FAULT and not a["pin"] and b["st"] == MR_FAULT
          and not b["pin"] and not e.pin65()[0], "%s / %s" % (a, b))
    e.mr_init()
    a = e.mr(30)
    check("...only init clears it", a["st"] != MR_FAULT, str(a))

    # Repeated toggles.
    e.set8("CFG_MAIN_RELAY_MODE", 2)
    bad = []
    for i in range(20):
        on = e.mr(100 + i * 10, req=1)
        off = e.mr(105 + i * 10, req=0)
        if not (on["pin"] and not off["pin"] and not e.pin65()[0]):
            bad.append((i, on, off))
    check("20 x request on/off with hold 0: pin follows every time",
          not bad, "first failure %s" % (bad[0],) if bad else "")


def part_d_reset(e):
    print("\n  --- D. a reset, from a driven pin ---")
    e.permit(True)
    e.set8("CFG_U_PIN_MAIN_RELAY", 65)
    e.set8("CFG_MAIN_RELAY_MODE", 2)
    e.mr_init()
    e.mr(0)
    before = e.active65()
    # The boot order in hcmain_me711.c: hc_hal_init() FIRST, then the
    # lifecycles' own init.
    e.call(sym("hc_hal_init"))
    e.mr_init()
    e.fp_init()
    check("driven before, RELEASED after hc_hal_init + lifecycle init",
          before and not e.pin65()[0], "before %s after %s"
          % (before, e.pin65()))
    # A request left over from before the reset must not come back before
    # the page is re-read: init leaves the relay at INIT with command 0.
    check("lifecycles restart from INIT/OFF with command 0",
          (e.call(sym("hc_main_relay_get_command")) & 0xFF) == 0
          and (e.call(sym("hc_fuelpump_command")) & 0xFF) == 0)


def main() -> int:
    print("=== HaniCore ME7.1.1 V75 - main relay and fuel pump, configured, "
          "at the port ===\n")
    print("  image   %s" % PI.IMG.name)
    e = Ecu(PI.image())
    check("the page was armed during the run", e.armed_written)
    full = part_a_boot(e)
    if full:
        part_b_pump(e)
        part_c_relay(e)
        part_d_reset(e)
    else:
        print("\n  (image predates V75: only part A applies)")

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("V75 RELAY/PUMP PROOF FAILS")
        return 1
    print("V75 RELAY/PUMP PROOF PASSES - both lifecycles run from the page, "
          "at the CPU port.")
    print("NOT PHYSICALLY VERIFIED: the CJ920 stage at cavity 65 and its "
          "polarity are unmeasured; nothing is connected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
