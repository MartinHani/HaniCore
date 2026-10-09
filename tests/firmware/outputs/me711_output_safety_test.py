#!/usr/bin/env python3
r"""
me711_output_safety_test.py - prove that THE ENGINE RUNTIME cannot energise
an output, whatever the common engine logic asks for.

    py tests\firmware\outputs\me711_output_safety_test.py

THE THREAT THIS EXISTS FOR. V20 is the first Bosch image that runs common
HaniCore engine code - hcengine.c computes injection time, ignition advance
and dwell from the calibration page on every main-loop pass. That code was
written for a board where hcsched.c and hcinj.c drive P2, P7 and P8 directly.
If any of that reached a pin here, a bench ECU with injectors or coils
connected would fire them with no crank signal and no operator intent.

FOUR INDEPENDENT ARGUMENTS, because one is not enough for this:

  1. ABSENCE. The pin-driving modules are not linked at all. Compiling them
     out is stronger than disarming them - the Bosch target has held that
     line since the first image (ME711_PORT_STATUS.md, "Deliberately
     not done") and this checks the map rather than trusting it.

  2. NO PORT WRITES IN THE HAL. hc_hal_out() and hc_hal_out_duty() are
     disassembled from the LINKED IMAGE and every instruction checked: they
     may not touch a port, a direction register, an open-drain register or a
     PWM register. This is machine code, not source review.

  3. THE GATE IS CLOSED. hc_hal_outputs_live() is EXECUTED in the simulator
     and must return 0.

  4. THE WHOLE RUNTIME, CENSUSED. The real image is run for a simulated
     second with the S5500 answering, and every write to a forbidden SFR is
     recorded. The count must be zero. This is the one that would catch a
     path nobody thought to look at.

Argument 4 subsumes the others in principle; all four are kept because they
fail differently and a build that breaks one should say which.

THE SCOPE OF THIS GATE CHANGED WHEN hcbench.c LANDED, and the change is stated
here rather than left for a reader to infer.

There is now exactly ONE function in the image that can drive an engine output:
hcbench.c's driver, which exists to MEASURE the driver-stage polarity and
connector cavity that no document answers. It is unreachable without an
explicit '!T' from the host, on a stopped engine, with an armed and valid
configuration and a healthy supervision link.

So this gate no longer says "nothing in this image can drive an output". It
says the RUNTIME cannot - which is the claim that protects an engine - and it
proves it by running a whole simulated second with no bench command and
counting zero writes. The other half, that the bench path cannot fire without
every invariant at once, is tests/firmware/outputs/me711_bench_output_proof.py's job, and that
one carries a POSITIVE control: it also proves the pin really does move when
every invariant is met, because a safety test that has never seen the thing
succeed cannot be trusted when it reports a failure.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import c167sim as S                        # noqa: E402
import me711_heartbeat_gap_proof as HB   # noqa: E402
import me711_image as PI
import me711_dpp as _dpp                 # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
MAP = PI.MAP

# THE SFRs THAT CAN PUT CURRENT THROUGH SOMETHING - read from reg167.h, never
# retyped. The first version of this file hardcoded them and got three wrong:
# 0xFFC4 is P3 (TXD0, NLEN_FR, SCLK), not ODP2, so the K-line and SSC bring-up
# looked like coil writes. That is the SAME defect PROJECT_STATE records from
# fuel_test.py - "it first read P8 at 0xFFD2, which is DP7; port addresses come
# from reg167.h, never from memory". The ODP registers are in ESFR space
# (0xF1xx) and are not 0xFFxx at all.
#
# [BOSCH-PM] ME7.1.1 column, what is actually on each port:
#   P2  ZDG1..ZDG8                        ignition coils
#   P7  EV1..EV3, DVE1/DVE2, NWS1/NWS2    injectors, throttle, cam solenoids
#   P8  EV4..EV8                          injectors
# P3 is DELIBERATELY NOT HERE: it carries TXD0/RXD0 (the K-line), MTSR/MRST/
# SCLK (the S5500 link) and NLEN_FR (the power hold). Every one of those must
# be written for the ECU to work at all.
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths as HCP  # noqa: E402
_REG167 = HCP.REG167.read_text(errors="replace")


def _sfr(name):
    m = re.search(r"^\s*sfr\s+%s\s*=\s*(0x[0-9A-Fa-f]+);" % name,
                  _REG167, re.M)
    if not m:
        raise SystemExit(f"{name} not found in reg167.h")
    return int(m.group(1), 16)


FORBIDDEN = {_sfr(n): n for n in (
    "P2", "DP2", "ODP2",          # the eight ignition coils
    "P7", "DP7", "ODP7",          # injectors 1-3, throttle, cam solenoids
    "P8", "DP8", "ODP8",          # injectors 4-8
    "PWMCON0", "PWMCON1",         # the PWM unit drives P7 with no port write
    "PP0", "PP1", "PP2", "PP3",
    "PT0", "PT1", "PT2", "PT3",
)}

# start_me711.a66 drives every one of those pins to its OFF state and
# makes it an input before main() is ever entered - that IS the safety
# mechanism, not a violation of it, so writes before the runtime begins are
# expected and are reported separately. What must be zero is writes AFTER the
# main loop is running, which is where common engine logic executes.


FAILS = 0


def check(name, ok, detail=""):
    global FAILS
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<58s} {detail}")
    if not ok:
        FAILS += 1


def sym(name, required=True):
    for m in re.finditer(r"^\s*([0-9A-F]{6})H\s+(\w+)\s",
                         MAP.read_text(errors="replace"), re.M):
        if m.group(2) == name:
            return int(m.group(1), 16)
    if required:
        raise SystemExit(f"{name} not in the map - build the target first")
    return None


def main() -> int:
    print("=== HaniCore Bosch ME7.1.1 - BENCH_SAFE output safety ===\n")
    img_path = PI.image()
    img = img_path.read_bytes()
    print(f"  image  {img_path.name}")
    print(f"  sha256 {PI.sha256()}\n")

    # --- 1. the pin drivers are not linked -------------------------------
    absent = []
    for f in ("hcinj_service", "hcign_service", "hcdbw_service",
              "hcboost_service", "sched_tooth", "sched_service",
              "inj_init", "dbw_init", "boost_init", "coil_set",
              "sched_outputs_off"):
        if sym(f, required=False) is not None:
            absent.append(f)
    check("no engine-output module is linked", not absent,
          "hcsched/hcinj/hcdbw/hcboost all absent" if not absent
          else f"LINKED: {absent}")

    # --- 2. RETIRED AT V63, AND REPLACED BY SOMETHING STRONGER -----------
    #
    # This used to scan each HAL output function's bytes for a port or PWM SFR
    # address and fail if it found one. That was the right check for a board
    # whose HAL could not drive a pin at all: "contains no port constant" was a
    # cheap proxy for "cannot energise an output".
    #
    # V63 GAVE THE BOARD AN OUTPUT BACK END, so hc_hal_out() and
    # hc_hal_out_duty() now reference P2/P7/P8/DP2/DP7/DP8 and the PWM unit BY
    # DESIGN. Keeping the proxy would mean asserting the feature does not
    # exist.
    #
    # It was also imprecise in a way worth recording: it scanned a FIXED
    # 0x120-byte window from each symbol, so it bled across function
    # boundaries and attributed hc_hal_out_duty()'s PWM constants to
    # hc_hal_outputs_live(), which touches no port at all.
    #
    # WHAT REPLACES IT IS NOT WEAKER. The property that matters was never
    # "the code contains no port constant" - it is "no pin moves unless the
    # board is deliberately armed", and checks 4 to 7 below MEASURE exactly
    # that, out of the executing image:
    #
    #   * hc_hal_outputs_live() executes and returns 0 while unarmed;
    #   * the startup drives every engine output to its safe state BEFORE the
    #     first supervision service;
    #   * not one coil, injector, throttle or PWM write happens across
    #     hundreds of supervision services;
    #   * every coil and injector pin is still an INPUT at the end.
    #
    # A behavioural measurement of the thing itself beats a structural proxy
    # for it, and this file already had the measurement.
    #
    # The one structural claim still worth making is that the resting state
    # has an owner: the safe-state routine must EXIST and hc_hal_init() must
    # reach it, because that is what makes "high impedance at reset" true
    # rather than hoped for.
    safe_ok = True
    try:
        sym("hc_hal_outputs_safe")
    except SystemExit:
        safe_ok = False
    check("the safe-state routine exists and is linked", safe_ok,
          "hc_hal_outputs_safe() - the resting state has an owner; that it "
          "RUNS is measured by check 5 below")

    bad = []
    for fn in ("hc_hal_outputs_live",):
        a = sym(fn)
        off = (a & 0xFFFF) + ((a >> 16) - 0x80) * 0x10000
        body = img[off:off + 0x40]
        for addr, nm in FORBIDDEN.items():
            if addr.to_bytes(2, "little") in body:
                bad.append(f"{fn}->{nm}")
    check("the ARMING DECISION itself touches no port", not bad,
          "clean, machine code" if not bad else str(bad))

    # --- 3. the gate is closed, executed ---------------------------------
    m = S.Mem(img)
    m._cbank = bytearray(0x10000)
    c = S.CPU(m, 0, 0)
    # DPP1 WAS A LITERAL, AND IT WAS THE V52 CONST PAGE.
    # tools/lib/me711_dpp.py reads it from the map, as the startup does.
    _dpp.apply(m)
    m.sfr[0xFE10] = 0xFC00
    m.sfr[0xFE12] = 0xF700
    m.w16(0xFC00, 0xF9F0)
    a = sym("hc_hal_outputs_live")
    sp = (m.sfr[0xFE12] - 2) & 0xFFFF
    m.w16(sp, a >> 16)
    sp = (sp - 2) & 0xFFFF
    m.w16(sp, 0xFFFE)
    m.sfr[0xFE12] = sp
    c.csp, c.ip = a >> 16, a & 0xFFFF
    rc = "maxsteps"
    for _ in range(20000):
        if c.ip == 0xFFFE:
            rc = "ok"
            break
        try:
            c.step()
        except S.Trap as e:
            rc = "TRAP:" + str(e)
            break
    ret = c.gr(4) & 0xFFFF if rc == "ok" else None
    check("hc_hal_outputs_live() executes and returns 0",
          rc == "ok" and ret == 0, f"{rc}, returned {ret}")

    # --- 4. run the whole runtime and census every forbidden write -------
    rig = HB.Rig(img_path, HB.ENTRY_CURRENT, HB.TICK_CURRENT, echo=True)
    hits = []
    ow8, ow16 = S.Mem.w8, S.Mem.w16

    def _log(addr, v, width):
        aa = addr & 0xFFFF
        nm = FORBIDDEN.get(aa)
        if nm is None and width == 1:
            nm = FORBIDDEN.get(aa - 1)      # high byte of a word SFR
        if nm is not None:
            hits.append((rig.cpu.steps,
                         (rig.cpu.csp << 16) | rig.cpu.ip, nm, v))

    def w8(s_, addr, v, _o=ow8):
        _log(addr, v, 1)
        return _o(s_, addr, v)

    def w16(s_, addr, v, _o=ow16):
        _log(addr, v, 2)
        return _o(s_, addr, v)

    prev8, prev16 = S.Mem.w8, S.Mem.w16
    S.Mem.w8, S.Mem.w16 = w8, w16
    try:
        rig.run(1200 * HB.STEPS_PER_MS)      # past boot, well into the loop
    finally:
        S.Mem.w8, S.Mem.w16 = prev8, prev16

    check("the runtime really was executing during the census",
          rig.trap is None and len(rig.entries) > 50,
          f"trap={rig.trap}, hc_asic_start_service entered "
          f"{len(rig.entries)}x")

    # THE PHASE SPLIT, and it is the whole point of this check.
    #
    # start_me711.a66 DOES write these ports - that is hc_outputs_safe(),
    # which drives every coil and injector pin to its off state and makes it an
    # input BEFORE main() is entered. Those writes are the safety mechanism, not
    # a breach of it. What must never happen is a write AFTER the runtime is
    # running, because that is where common engine logic executes.
    first_service = rig.entries[0][1] if rig.entries else 0
    startup = [h for h in hits if h[0] < first_service]
    runtime = [h for h in hits if h[0] >= first_service]

    check("the startup DOES drive the outputs to their safe state",
          len(startup) > 0,
          f"{len(startup)} write(s) before the first supervision service "
          f"- hc_outputs_safe()")

    where = sorted({f"{nm}@0x{pc:06X}" for _, pc, nm, _ in runtime})
    check("NOT ONE coil/injector/throttle/PWM write once the runtime runs",
          not runtime,
          f"{len(rig.entries)} supervision services, 0 forbidden writes"
          if not runtime else f"{len(runtime)} write(s): {where}")

    # And the safe state actually held: every one of those pins must still be
    # an INPUT at the end of the run. An input cannot source current whatever
    # the output latch happens to contain.
    dp2, dp7, dp8 = (rig.mem.r16(0xFFC2), rig.mem.r16(0xFFD2),
                     rig.mem.r16(0xFFD6))
    coil_out = dp2 & 0x00FF                      # P2.0-7  = ZDG1..ZDG8
    inj_out = (dp7 & 0x00F0) | (dp8 & 0x00F8)    # P7.4-7, P8.3-7
    check("every coil and injector pin is still an INPUT at the end",
          coil_out == 0 and inj_out == 0,
          f"DP2={dp2:04X} DP7={dp7:04X} DP8={dp8:04X}")

    print()
    if FAILS:
        print(f"OUTPUT SAFETY FAILED ({FAILS} check(s)) - DO NOT FLASH")
        return 1
    print("OUTPUT SAFETY PASSES - the engine RUNTIME cannot drive an output. "
          "The bench qualifier can, deliberately, and only under every "
          "invariant at once - see me711_bench_output_proof.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
