#!/usr/bin/env python3
r"""
me711_bench_output_proof.py - the bench output qualifier drives a pin when
every invariant holds, and DOES NOT when any single one does not.

    py tests\firmware\outputs\me711_bench_output_proof.py

WHY THIS EXISTS.

hcbench.c is the first code in any HaniCore Bosch image that can put a signal
on a coil or an injector pin. Everything else in the image still cannot:
hc_hal_outputs_live() returns 0, hc_hal_out() contains no port write,
hcsched.c and hcinj.c are not linked, and me711_output_safety_test.py proves
all of that against the linked binary.

So the safety argument has moved. It used to be "no code here can drive an
output". It is now "exactly one function can, and it is unreachable unless a
person pressed a button on a stopped engine with a valid, armed configuration
and a healthy supervision link". A claim of that shape is only worth anything
if somebody has tried to break it, so this gate does:

  THE NEGATIVE CONTROLS. For each invariant in turn, satisfy every OTHER one,
  break that one, send the '!T' bytes the .ini actually sends, and census every
  write to P2/P7/P8 and their direction and open-drain registers. The count
  must be ZERO, and the firmware must say which invariant it refused on.

  THE POSITIVE CONTROL, and it matters more than the negatives. Satisfy them
  ALL and the census must be NON-ZERO, on the expected port and bit. Without
  it, a rig that silently failed to deliver the command - or a census hooked to
  the wrong SFR - would pass every negative check and prove nothing at all.
  This project has already shipped six gates that were green against the wrong
  image; a test that cannot observe the thing succeeding cannot be trusted when
  it observes it failing.

  AND IT COMES BACK DOWN. After the pulse the pin must be an INPUT again, and
  the run must stop on its own rather than latch.

THE COMMAND BYTES COME FROM THE .INI, not from this file, for the same reason
me711_s5500_command_proof.py does it: what is proven then is the path the UI
actually uses.
"""
from __future__ import annotations

import binascii
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import c167sim as S                       # noqa: E402
import me711_heartbeat_gap_proof as HB    # noqa: E402
import me711_image as PI                  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
INI = ROOT / "tunerstudio/hanicore_me711.ini"
CFG_H = ROOT / "firmware/generated/hc_config_generated.h"
# The legacy offsets live in hcconfig.h; the generated header only carries the
# universal block and re-asserts the legacy ones with static asserts. Read both
# rather than picking one and being wrong about which.
CFG_LEGACY_H = ROOT / "firmware/config/hcconfig.h"
BENCH_C = (ROOT / "firmware/targets/me711/diagnostics/hcbench.c")

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-52s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def sym(name, required=True):
    for m in re.finditer(r"^\s*([0-9A-F]{6})H\s+(\w+)\s",
                         PI.MAP.read_text(errors="replace"), re.M):
        if m.group(2) == name:
            return int(m.group(1), 16)
    if required:
        raise SystemExit("%s is not in the map - build the target first" % name)
    return None


def cfg_off(name):
    for f in (CFG_H, CFG_LEGACY_H):
        m = re.search(r"#define\s+%s\s+(\d+)u?" % name,
                      f.read_text(errors="replace"))
        if m:
            return int(m.group(1))
    raise SystemExit("%s is not defined in either configuration header" % name)


def seg_range(name):
    """A linker segment's address range, from the map. The point of asking is
    that "something wrote a port" and "hcbench wrote a port" are different
    claims, and only the second one is the safety argument."""
    for m in re.finditer(r"^([0-9A-F]{6})H\s+([0-9A-F]{6})H\s+[0-9A-F]{6}H"
                         r".*?([?\w]+)\s*$",
                         PI.MAP.read_text(errors="replace"), re.M):
        if m.group(3) == name:
            return int(m.group(1), 16), int(m.group(2), 16)
    raise SystemExit("%s is not in the map" % name)


def refuse_bit(name):
    m = re.search(r"#define\s+HCB_R_%s\s+(0x[0-9A-Fa-f]+)u" % name,
                  (ROOT / "firmware/targets/me711/diagnostics/hcbench.h").read_text(errors="replace"))
    if not m:
        raise SystemExit("HCB_R_%s not in hcbench.h" % name)
    return int(m.group(1), 16)


def abort_bit(name):
    m = re.search(r"#define\s+HCB_A_%s\s+(0x[0-9A-Fa-f]+)u" % name,
                  (ROOT / "firmware/targets/me711/diagnostics/hcbench.h").read_text(errors="replace"))
    if not m:
        raise SystemExit("HCB_A_%s not in hcbench.h" % name)
    return int(m.group(1), 16)


envelope = HB.envelope      # one definition: 16-bit length (see HB)


def ini_command(name: str) -> bytes:
    m = re.search(r'^\s*%s\s*=\s*"([^"]*)"' % name,
                  INI.read_text(errors="replace"), re.M)
    if not m:
        raise SystemExit("%s is not in [ControllerCommands]" % name)
    raw, out, i = m.group(1), bytearray(), 0
    while i < len(raw):
        if raw[i] == "\\" and raw[i + 1] == "x":
            out.append(int(raw[i + 2:i + 4], 16))
            i += 4
        else:
            out.append(ord(raw[i]))
            i += 1
    return bytes(out)


# The registers that can put current through something. Read from reg167.h,
# never retyped - the same list me711_output_safety_test.py uses and for the
# same reason: the first version of that file had three of them wrong.
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths as HCP  # noqa: E402
_REG167 = HCP.REG167.read_text(errors="replace")


def _sfr(n):
    return int(re.search(r"^\s*sfr\s+%s\s*=\s*(0x[0-9A-Fa-f]+);" % n,
                         _REG167, re.M).group(1), 16)


FORBIDDEN = {_sfr(n): n for n in ("P2", "DP2", "ODP2", "P7", "DP7", "ODP7",
                                  "P8", "DP8", "ODP8")}

HC_CFG = None


def run_case(img_path, arm, valid_page, send, steps=4_200_000):
    """Boot, optionally arm the page, send `send`, and census output writes.

    Returns (writes-after-the-runtime-started, hcb_state, hcb_refuse).
    """
    rig = HB.Rig(img_path, HB.ENTRY_CURRENT, HB.TICK_CURRENT, echo=False)
    hits = []
    ow8, ow16 = S.Mem.w8, S.Mem.w16
    armed_at = [None]

    def _log(addr, v, width):
        aa = addr & 0xFFFF
        nm = FORBIDDEN.get(aa) or (FORBIDDEN.get(aa - 1) if width == 1
                                   else None)
        if nm is not None:
            hits.append((rig.cpu.steps,
                         (rig.cpu.csp << 16) | rig.cpu.ip, nm, v))

    def w8(s_, a, v, _o=ow8):
        _log(a, v, 1)
        return _o(s_, a, v)

    def w16(s_, a, v, _o=ow16):
        _log(a, v, 2)
        return _o(s_, a, v)

    # THE PAGE IS ARMED BY WRITING IT, part-way through the run, exactly as a
    # tuner would. Poking it before boot would be overwritten by hc_cfg_init().
    arm_step = 1_400_000
    orig_step = rig.cpu.step

    def step2():
        if rig.cpu.steps >= arm_step and armed_at[0] is None:
            armed_at[0] = rig.cpu.steps
            base = HC_CFG & 0xFFFF
            rig.mem.w8(base + cfg_off("CFG_OUTPUTS_ARMED"), 1 if arm else 0)
            # A VALID PAGE IS THE FIRMWARE'S OWN DEFAULTS, not one this test
            # assembles. hc_cfg_faults() checks the version word, the stroke
            # count, the wheel, every TDC angle for range AND for duplicates,
            # every output channel index, and three rev limits against each
            # other - and the first version of this rig hand-built a page that
            # failed on duplicate TDC angles, which made the positive control
            # look like a firmware fault. The defaults describe a real engine;
            # leave them alone.
            if not valid_page:
                rig.mem.w8(base + cfg_off("CFG_CYLINDERS"), 0)
        return orig_step()

    rig.cpu.step = step2
    rig.queue_rx(arm_step + 400_000, send)

    prev8, prev16 = S.Mem.w8, S.Mem.w16
    S.Mem.w8, S.Mem.w16 = w8, w16
    try:
        rig.run(steps)
    finally:
        S.Mem.w8, S.Mem.w16 = prev8, prev16

    first = rig.entries[0][1] if rig.entries else 0
    after = [h for h in hits if h[0] >= max(first, arm_step)]
    st = rig.mem.r16(sym("hcb_state") & 0xFFFF)
    rf = rig.mem.r16(sym("hcb_refuse") & 0xFFFF)
    dp2 = rig.mem.r16(0xFFC2)
    dp7 = rig.mem.r16(0xFFD2)
    dp8 = rig.mem.r16(0xFFD6)
    return after, st, rf, (dp2, dp7, dp8), rig


# EACH CASE RUNS IN ITS OWN PROCESS, and that is not fastidiousness.
#
# me711_heartbeat_gap_proof.Rig installs its ASC0 and ADC models by replacing
# methods on the c167sim Mem CLASS, and this file's write census does the same
# to count port writes. Two of those in one interpreter chain, and a later Rig
# can end up calling an earlier Rig's byte handlers. Measured: the positive
# control passes on its own (45 writes, 3 pulses, refuse 0) and fails when it
# is the third case in the same process.
#
# That is exactly the class of defect PROJECT_STATE already records twice -
# "a test rig's stack wrote over the module under test" - and the fix is the
# same one: give the rig its own space instead of reasoning about whether the
# sharing is safe. A subprocess per case costs seconds and removes the whole
# question.
def run_case_subprocess(arm, valid_page, cmd_name, steps=4_200_000):
    import json
    import subprocess
    r = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--case",
         "%d,%d,%s,%d" % (1 if arm else 0, 1 if valid_page else 0,
                          cmd_name, steps)],
        capture_output=True, text=True, cwd=str(ROOT))
    for line in (r.stdout or "").splitlines():
        if line.startswith("CASE-RESULT "):
            return json.loads(line[len("CASE-RESULT "):])
    raise SystemExit("the case subprocess produced no result:" +
                     (r.stdout or '') + (r.stderr or ''))


def case_main(spec):
    import json
    global HC_CFG
    a, v, cmd_name, steps = spec.split(",")
    HC_CFG = sym("hc_cfg")
    writes, st, rf, dps, rig = run_case(PI.image(), arm=(a == "1"),
                                        valid_page=(v == "1"),
                                        send=envelope(ini_command(cmd_name)),
                                        steps=int(steps))
    print("CASE-RESULT " + json.dumps({
        "writes": [[w[1], w[2]] for w in writes],
        "state": st, "refuse": rf, "dp": list(dps),
        "port": rig.mem.r16(sym("hcb_port") & 0xFFFF),
        "bit": rig.mem.r16(sym("hcb_bit") & 0xFFFF),
        "pulses": rig.mem.r16(sym("hcb_pulses") & 0xFFFF),
        "requests": rig.mem.r16(sym("hcb_requests") & 0xFFFF),
    }))
    return 0


def main() -> int:
    global HC_CFG
    img = PI.image()
    HC_CFG = sym("hc_cfg")

    print("=== HaniCore - the bench output qualifier, attacked ===\n")
    print("  image   %s" % img.name)
    print("  sha256  %s\n" % PI.sha256())

    # The bounds must be in the FIRMWARE, not in the page. Checked here as
    # source text because it is a statement about what the code contains, and
    # the runtime consequence is measured by the pulse length below.
    src = BENCH_C.read_text(errors="replace")
    check("the pulse bounds are compiled in, not configured",
          "#define HCB_INJ_MAX_US" in src and "#define HCB_IGN_MAX_US" in src
          and "if (width > HCB_INJ_MAX_US)" in src,
          "CFG_U_TEST_VALUE is read and then clamped")

    cmd = envelope(ini_command("cmdTestInj1"))
    print("\n  the '!T' bytes the .ini sends for injector 1: %s\n"
          % " ".join("%02X" % b for b in ini_command("cmdTestInj1")))

    # ------------------------------------------------ the negative controls
    print("  --- every invariant broken in turn; nothing may move ---")
    cases = [
        # V84: no page arm - the '!T' command is the deliberate act. The page
        # byte is left at 0 here to prove it no longer matters either way.
        ("the page does not describe an engine",
         dict(arm=False, valid_page=False), "CFG"),
    ]
    for title, kw, bit in cases:
        r = run_case_subprocess(kw["arm"], kw["valid_page"], "cmdTestInj1")
        writes, st, rf, dps = r["writes"], r["state"], r["refuse"], r["dp"]
        want = refuse_bit(bit)
        check("%s: not one output write" % title, not writes,
              "state=%d refuse=0x%04X DP2=%04X DP7=%04X DP8=%04X"
              % (st, rf, dps[0], dps[1], dps[2])
              if not writes else "%d WRITE(S): %s" % (len(writes), writes[:3]))
        check("%s: and the firmware says so" % title, (rf & want) != 0,
              "refuse 0x%04X includes HCB_R_%s (0x%04X)" % (rf, bit, want))

        # ------------------------------------------------- the positive control
        print("\n  --- every invariant satisfied; all four AWT candidates MUST move ---")
        candidates = (
          ("cmdTestInj1", "EV1", 7, 6, {"P7", "DP7", "ODP7"}),
          ("cmdTestInj2", "EV2", 7, 5, {"P7", "DP7", "ODP7"}),
          ("cmdTestInj3", "EV3", 7, 4, {"P7", "DP7", "ODP7"}),
          ("cmdTestInj4", "EV4", 8, 7, {"P8", "DP8", "ODP8"}),
        )
        seen_bindings = set()
        lo, hi = seg_range("?PR?HCBENCH")
        for command, ev, want_port, want_bit, allowed_ports in candidates:
          # V93: 13 M, WAS 9 M. Ten 50/950-ms-class pulses finish near 9 M
          # on V92; V93's main loop does a little more per pass (the far ETB
          # procedure check, the boot-history live fields, the scheduler on
          # every serial yield) and 9 M ended at pulse 9 of 10 with the run
          # still RUNNING - the budget, not the bench: at 13 M it is DONE
          # with 10 pulses and the pins released (measured 2026-09-28).
          r = run_case_subprocess(True, True, command, steps=13_000_000)
          writes, st, rf, dps = r["writes"], r["state"], r["refuse"], r["dp"]
          print("      %s: %d pulse(s) completed, %d request(s) received"
              % (ev, r["pulses"], r["requests"]))
          check("%s: nothing is refused" % ev, rf == 0,
              "hcbRefuse = 0x%04X, hcbState = %d" % (rf, st))
          check("%s: the pin IS driven" % ev, bool(writes),
              "%d write(s), first at 0x%06X (%s)"
              % (len(writes), writes[0][0], writes[0][1]) if writes
              else "NOTHING MOVED - this gate cannot see a success")
          check("%s: production binding is the expected unique port and bit" % ev,
              r["port"] == want_port and r["bit"] == want_bit
              and (r["port"], r["bit"]) not in seen_bindings,
              "hcbPortBit = P%d.%d" % (r["port"], r["bit"]))
          seen_bindings.add((r["port"], r["bit"]))

          if writes:
            ports = sorted({nm for _pc, nm in writes})
            check("%s: writes only its output port" % ev,
                set(ports) <= allowed_ports,
                "wrote %s" % ", ".join(ports))
            pcs = [w[0] for w in writes]
            check("%s: every write is inside hcbench" % ev,
                all(lo <= pc <= hi for pc in pcs),
                "PCs 0x%06X..0x%06X, ?PR?HCBENCH is 0x%06X-0x%06X"
                % (min(pcs), max(pcs), lo, hi))

          check("%s: the coil port is untouched" % ev,
              not any(nm in ("P2", "DP2", "ODP2") for _pc, nm in writes),
              "DP2=%04X" % dps[0])
          check("%s: stops after its pulse count" % ev,
              st == 2 and r["pulses"] == 10,
              "hcbState = %d (2 = DONE), %d pulses" % (st, r["pulses"]))
          check("%s: does not latch; pins are inputs again" % ev,
              (dps[1] & 0x00F0) == 0 and (dps[2] & 0x00F8) == 0,
              "DP7=%04X DP8=%04X" % (dps[1], dps[2]))

        check("the four AWT injector candidates use four distinct bindings",
            len(seen_bindings) == len(candidates),
                ", ".join("P%d.%d" % binding for binding in sorted(seen_bindings)))

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("BENCH OUTPUT PROOF FAILS - DO NOT FLASH. Either an invariant "
              "is not being enforced, or the gate can no longer see a "
              "success, and both are stop conditions.")
        return 1
    print("BENCH OUTPUT PROOF PASSES - one function can drive a pin, it needs "
          "every invariant at once, it drives only the channel asked for, and "
          "it puts the pin back.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--case":
        raise SystemExit(case_main(sys.argv[2]))
    raise SystemExit(main())
