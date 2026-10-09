#!/usr/bin/env python3
r"""
me711_dbw_bench_proof.py - the throttle bridge bench mode, attacked.

    py tests\firmware\dbw\me711_dbw_bench_proof.py

WHY THIS IS ITS OWN GATE AND NOT A ROW IN THE INJECTOR ONE.

The DBW mode is the only thing in this firmware that can move something
mechanical. Everything else that hcbench.c drives is an electrical load that
sits still; a throttle motor is a motor, and the failure that matters is not
"nothing happened" but "it opened and stayed open". So it carries invariants
the other modes do not - the two TPS tracks must agree before it starts, the
bridge's own fault pin must be clean, the enable is asserted for the run and
dropped on every exit path, and the plate's position is watched on every
service pass against a band COMPILED IN rather than configured.

Each of those gets a negative control here, and the positive control matters
more than all of them: a gate that cannot see the bridge being driven proves
nothing when it sees it not being driven. That lesson is recorded in
me711_bench_output_proof.py and it cost six green gates against a stale image.

WHAT THE HARDWARE EVIDENCE IS. From the Ein-Ausgaenge sheet, device S8100:

    pin  3  IN1  <- DVE1    MAIN P7.2  / POUT2   CPU pin 21
    pin 19  IN2  <- DVE2    MAIN P7.7  / CC31    CPU pin 26
    pin 18  DI1  <- EGENFR  MAIN P2.11 / CC11    CPU pin 60
    pin 13  DI2  <- ED_RST  NOT A CPU PIN - the monitoring net
    pin  2  SF   -> SF      MAIN P3.15           CPU pin 81
    pins 6,7   OU1 -> connector cavity 117 (ESBM+)
    pins 14,15 OU2 -> connector cavity 118 (ESBM-)

ED_RST ON DI2 IS THE ONE TO REMEMBER: the monitoring hardware can disable
this bridge without asking the main CPU, so "commanded and nothing moved" is
a legitimate physical outcome and not necessarily a firmware fault.

AND THE PORTABILITY TRAP THIS GATE ALSO WATCHES. The 4B0906018DC hcdbw.c has
`sbit SF_PIN = P2 ^ 9`. On ME7.1.1 P2.9 is NWDG2 - the SECOND CAM INPUT.
Every bit number here comes from hctarget.h, and this gate checks that the
DBW mode never writes P3 or the cam capture bits.
"""
from __future__ import annotations

import binascii
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import c167sim as S                       # noqa: E402
import me711_bench_output_proof as BOP    # noqa: E402
import me711_heartbeat_gap_proof as HB    # noqa: E402
import me711_image as PI                  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
TGT = ROOT / "firmware/targets/me711"
HDR = TGT / "hctarget.h"
BENCH_C = TGT / "diagnostics/hcbench.c"
GEN_H = ROOT / "firmware/generated/hc_config_generated.h"

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-56s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def hdr_int(name):
    m = re.search(r"#define\s+%s\s+(\d+)" % name,
                  HDR.read_text(errors="replace"))
    if not m:
        raise SystemExit("%s is not in hctarget.h" % name)
    return int(m.group(1))


def gen_int(name):
    m = re.search(r"#define\s+%s\s+(\d+)u" % name,
                  GEN_H.read_text(errors="replace"))
    if not m:
        raise SystemExit("%s is not in hc_config_generated.h" % name)
    return int(m.group(1))


envelope = HB.envelope      # one definition: 16-bit length (see HB)


# ---------------------------------------------- WHERE A PAGE BYTE ACTUALLY IS
#
# THE PAGE IS IN TWO PLACES AND THE FIRST VERSION OF THIS GATE POKED ONLY ONE.
# hcconfig.c splits it: offsets below HC_CFG_CORE are mirrored into the near
# array `hc_cfg`, and everything at or above it lives in the battery-backed
# external SRAM at TGT_EXTRAM_BASE + TGT_RAM_CFG + HC_CFG_HDR_LEN + off. The
# universal block starts at 2502, so EVERY DBW field is in the second place.
#
# Poking the near array for a far offset writes over unrelated near variables
# and changes nothing the firmware reads - the run then refuses for a reason
# that looks like a firmware fault and is a rig fault. This project has three
# recorded incidents of exactly that shape, which is why the constants below
# are read from the headers instead of typed.
def _hdr_int(path, name):
    m = re.search(r"#define\s+%s\s+(0x[0-9A-Fa-f]+|\d+)" % name,
                  path.read_text(errors="replace"))
    if not m:
        raise SystemExit("%s is not in %s" % (name, path.name))
    return int(m.group(1), 0)


CFG_H = ROOT / "firmware/config/hcconfig.h"
CFG_CORE = _hdr_int(CFG_H, "HC_CFG_CORE")
CFG_HDR_LEN = _hdr_int(CFG_H, "HC_CFG_HDR_LEN")
EXTRAM = _hdr_int(HDR, "TGT_EXTRAM_BASE")
RAM_CFG = _hdr_int(HDR, "TGT_RAM_CFG")


def page_addr(off):
    if off < CFG_CORE:
        return (BOP.HC_CFG & 0xFFFF) + off
    return EXTRAM + RAM_CFG + CFG_HDR_LEN + off


# ------------------------------------------------------------- the rig ----
#
# ONE CASE PER PROCESS, for the reason me711_bench_output_proof.py records at
# length: both rigs patch c167sim's Mem CLASS, and two of them in one
# interpreter can end up calling each other's handlers. A subprocess costs
# seconds and removes the question.
def run_case(pokes, cmd_name, steps):
    rig = HB.Rig(PI.image(), HB.ENTRY_CURRENT, HB.TICK_CURRENT, echo=False)
    hits = []
    ow8, ow16 = S.Mem.w8, S.Mem.w16
    done = [False]

    def _log(addr, v, width):
        aa = addr & 0xFFFF
        nm = BOP.FORBIDDEN.get(aa) or (BOP.FORBIDDEN.get(aa - 1)
                                       if width == 1 else None)
        if nm is not None:
            hits.append((rig.cpu.steps, (rig.cpu.csp << 16) | rig.cpu.ip,
                         nm, v))

    def w8(s_, a, v, _o=ow8):
        _log(a, v, 1)
        return _o(s_, a, v)

    def w16(s_, a, v, _o=ow16):
        _log(a, v, 2)
        out = _o(s_, a, v)
        # THE CONVERSION MUST END. The heartbeat rig answers ADST with a
        # tagged ADDAT but never sets ADCIR or clears ADST/ADBSY, and the HAL
        # waits for both (hc_hal_main_sample): no TPS sample was ever fresh,
        # so the DBW mode refused TPSPAIR - correctly - and the positive
        # control could not pass. Completed here as the C167 completes it.
        if (a & 0xFFFFFF) == 0xFFA0 and (v & 0x80):
            s_.sfr[0xFFA0] = v & ~0x180
            s_.sfr[0xFF98] = s_.sfr.get(0xFF98, 0) | 0x80
        return out

    # PAST BOOT, not a literal. V39's append-only store made hc_nvm_boot()
    # cost 1 187 437 instructions before the supervision link comes up, so
    # 1 400 000 poked the calibration page and sent the bench command while
    # the ECU was still scanning flash - and the gate reported that as
    # "NOTHING MOVED", which is a true statement about a question asked
    # too early. tools/lib/me711_image.py owns the number.
    arm_step = PI.BOOT_STEPS
    orig_step = rig.cpu.step

    def step2():
        if rig.cpu.steps >= arm_step and not done[0]:
            done[0] = True
            # KEY ON (KL15 status on P6.2), as on a bench with the ignition
            # switched on; a poke at offset -1 leaves the key OFF instead.
            if not any(off < 0 for off, _s, _v in pokes):
                rig.mem.sfr[0xFFCC] = rig.mem.sfr.get(0xFFCC, 0) | 0x0004
            for off, size, val in pokes:
                if off < 0:
                    continue
                at = page_addr(off)
                if size == 1:
                    rig.mem.w8(at, val & 0xFF)
                else:
                    # THE PAGE IS BIG-ENDIAN. hcconfig stores it that way so a
                    # TunerStudio 'W' is a straight byte copy; a rig that wrote
                    # it little-endian would set a tolerance of 0x0300 while
                    # meaning 3.
                    rig.mem.w8(at, (val >> 8) & 0xFF)
                    rig.mem.w8(at + 1, val & 0xFF)
        return orig_step()

    rig.cpu.step = step2
    cmd = (bytes.fromhex(cmd_name[4:]) if cmd_name.startswith("hex:")
           else BOP.ini_command(cmd_name))
    rig.queue_rx(arm_step + 400_000, envelope(cmd))

    prev8, prev16 = S.Mem.w8, S.Mem.w16
    S.Mem.w8, S.Mem.w16 = w8, w16
    try:
        rig.run(steps)
    finally:
        S.Mem.w8, S.Mem.w16 = prev8, prev16

    first = rig.entries[0][1] if rig.entries else 0
    after = [h for h in hits if h[0] >= max(first, arm_step)]
    return {
        "writes": [[w[1], w[2]] for w in after],
        "state": rig.mem.r16(BOP.sym("hcb_state") & 0xFFFF),
        "refuse": rig.mem.r16(BOP.sym("hcb_refuse") & 0xFFFF),
        "abort": rig.mem.r16(BOP.sym("hcb_abort") & 0xFFFF),
        "pulses": rig.mem.r16(BOP.sym("hcb_pulses") & 0xFFFF),
        "dp2": rig.mem.r16(0xFFC2),
        "dp7": rig.mem.r16(0xFFD2),
        "dp3": rig.mem.r16(0xFFC6),
        "dp8": rig.mem.r16(0xFFD6),
    }


def sub(pokes, cmd_name, steps=9_000_000):
    r = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--case",
         json.dumps({"pokes": pokes, "cmd": cmd_name, "steps": steps})],
        capture_output=True, text=True, cwd=str(ROOT))
    for line in (r.stdout or "").splitlines():
        if line.startswith("CASE-RESULT "):
            return json.loads(line[len("CASE-RESULT "):])
    raise SystemExit("the case subprocess produced no result:\n"
                     + (r.stdout or "") + (r.stderr or ""))


# THE RAW BENCH COMMAND, NOT THE TUNERSTUDIO BUTTON. The "Throttle bridge,
# direction A/B" buttons (cmdTestDbwA/B) are the ETB commissioning stop test
# (`!C\x04` / `!C\x05`, hcetbcal.c), which drives the bridge through the
# shared motor primitive and never enters hcbench. The hcbench DBW mode this
# gate attacks is `!T` + HC_TEST_DBW + channel, reachable only as a raw
# command; sending the button tested the wrong facility.
DBW_A = "hex:" + (b"!T" + bytes([gen_int("HC_TEST_DBW"), 1])).hex()


def main() -> int:
    BOP.HC_CFG = BOP.sym("hc_cfg")
    print("=== HaniCore ME7.1.1 - the throttle bridge bench mode ===\n")
    print("  image   %s" % PI.image().name)
    print("  sha256  %s\n" % PI.sha256())

    # ----------------------------------------------- the pins, from ONE place
    pins = {"PWM": (7, 2), "DIR": (7, 7), "EN": (2, 11), "SF": (3, 15)}
    for nm, (_port, bit) in pins.items():
        check("hctarget.h names the S8100 %s pin" % nm,
              hdr_int("TGT_DBW_%s_PORT_BIT" % nm) == bit,
              "TGT_DBW_%s_PORT_BIT = %d"
              % (nm, hdr_int("TGT_DBW_%s_PORT_BIT" % nm)))
    check("SF is NOT on P2.9 here", hdr_int("TGT_DBW_SF_PORT_BIT") == 15,
          "the ME7.5 board has it on P2.9, which on ME7.1.1 is NWDG2 - "
          "the second cam input")
    check("the connector cavities are recorded",
          hdr_int("TGT_DBW_CONN_PIN_P") == 117
          and hdr_int("TGT_DBW_CONN_PIN_M") == 118,
          "OU1 -> 117 ESBM+, OU2 -> 118 ESBM-")

    src = BENCH_C.read_text(errors="replace")
    check("the nudge width and the runaway band are compiled in",
          "#define HCB_DBW_MAX_US" in src and "#define HCB_DBW_TPS_BAND"
          in src and "hc_cal_u16(CFG_U_TPS_TOL_X10)" in src,
          "a page can set the TPS tolerance but not the runaway band")
    check("the enable is dropped on EVERY exit path",
          src.count("dbw_disarm()") >= 3,
          "%d call sites: the abort path, the completion path, and the "
          "function itself" % src.count("dbw_disarm()"))

    corr = BOP.cfg_off("CFG_U_TPS_CORR")
    tol = BOP.cfg_off("CFG_U_TPS_TOL_X10")
    sfm = BOP.cfg_off("CAL_DBW_SF_MODE")
    armed = BOP.cfg_off("CFG_OUTPUTS_ARMED")     # V84: retired, still written
    cyl = BOP.cfg_off("CFG_CYLINDERS")           # 0 = a page that cannot run
    SAME = gen_int("HC_TRACK_SAME")
    OPPOSITE = gen_int("HC_TRACK_OPPOSITE")
    SF_IGNORE = gen_int("HC_DBW_SF_IGNORE")
    SF_LOW_BAD = gen_int("HC_DBW_SF_LOW_IS_FAULT")

    # The modelled ADC in the rig answers 100 + 37*channel, so TPS1 (AN1) is
    # 137 and TPS2 (AN3) is 211. Under SAME with a wide tolerance they agree;
    # under OPPOSITE they must sum to full scale and do not. That is what
    # makes both directions of the pair check observable here.
    # CAL_DBW_SF_MODE IS A u16. It is declared `bits, U16` in the .ini and
    # hcbench.c reads it with hc_cal_u16(), so poking one byte would leave the
    # low half at whatever the defaults hold and the mode would be whatever
    # that happened to make. The FIRST version of this gate poked it as a byte
    # and its SF negative control could not fail - the same shape of rig fault
    # this project has recorded three times.
    ok_pair = [[corr, 1, SAME], [tol, 2, 1000], [sfm, 2, SF_IGNORE]]

    print("\n  --- every extra DBW invariant broken in turn ---")

    # V84: THERE IS NO PAGE ARM - the '!T' command is the deliberate act. The
    # invariant that still stands between a button and the bridge is a page
    # that describes a runnable engine, so that is the refusal tested here.
    r = sub([[armed, 1, 0], [cyl, 1, 0]] + ok_pair, DBW_A)
    check("invalid page: nothing moves", not r["writes"],
          "state=%d refuse=0x%04X" % (r["state"], r["refuse"]))
    check("  ... and HCB_R_CFG is set, never the retired HCB_R_ARMED",
          (r["refuse"] & BOP.refuse_bit("CFG")) != 0
          and (r["refuse"] & BOP.refuse_bit("ARMED")) == 0,
          "refuse 0x%04X" % r["refuse"])

    r = sub([[armed, 1, 1], [corr, 1, OPPOSITE], [tol, 2, 5],
             [sfm, 2, SF_IGNORE]], DBW_A)
    check("the TPS tracks disagree: nothing moves", not r["writes"],
          "state=%d refuse=0x%04X" % (r["state"], r["refuse"]))
    check("  ... and HCB_R_TPSPAIR is set",
          (r["refuse"] & BOP.refuse_bit("TPSPAIR")) != 0,
          "refuse 0x%04X - a throttle whose feedback is already "
          "inconsistent is not one you energise" % r["refuse"])

    # P3.15 READS 0 IN THE SIMULATOR, so declaring LOW a fault makes the
    # firmware see one. THAT IS A STATEMENT ABOUT THE DECISION LOGIC, NOT
    # ABOUT THE REAL PIN: what SF does on the actual bridge is unmeasured and
    # is one of the things stage A of the bench procedure exists to find out.
    r = sub([[armed, 1, 1], [corr, 1, SAME], [tol, 2, 1000],
             [sfm, 2, SF_LOW_BAD]], DBW_A)
    # V83: SF IS JUDGED AFTER THE ENABLE, NOT BEFORE IT. A CJ220 whose DI is
    # inactive reports SF LOW by design (the Bosch CJ220 datasheet rows 5, 9), so the
    # pre-run refusal this vector used to demand refused every run on a
    # working board. The property now: the bridge is enabled with both legs
    # LOW (free-wheel), SF is read after HCB_DBW_SF_SETTLE_MS, and a fault
    # there ABORTS the run before a single nudge pulse, leaving it released.
    en_bit = 1 << hdr_int("TGT_DBW_EN_PORT_BIT")
    check("the bridge reports a fault: no nudge is delivered",
          r["pulses"] == 0 and r["state"] == 4,
          "state=%d (4 = ABORTED) pulses=%d" % (r["state"], r["pulses"]))
    check("  ... the abort names the bridge flag and releases it",
          (r["abort"] & BOP.abort_bit("SF")) != 0
          and (r["dp2"] & en_bit) == 0,
          "abort 0x%04X DP2 0x%04X - P3.15 reads low and the page says low "
          "is a fault" % (r["abort"], r["dp2"]))

    # THE THROTTLE PERMISSION. With the key off the output class is not
    # permitted and the shared motor primitive refuses every enable; the run
    # used to report DONE having driven nothing. It must refuse, and say why.
    r = sub([[-1, 0, 0], [armed, 1, 1]] + ok_pair, DBW_A)
    check("key off: the throttle is not permitted, nothing moves",
          not r["writes"] and (r["refuse"] & BOP.refuse_bit("PERMIT")) != 0,
          "state=%d refuse=0x%04X" % (r["state"], r["refuse"]))

    # ------------------------------------------------- the positive control
    print("\n  --- every invariant satisfied; the bridge MUST be driven ---")
    r = sub([[armed, 1, 1]] + ok_pair, DBW_A)
    check("nothing is refused", r["refuse"] == 0,
          "hcbRefuse = 0x%04X, hcbState = %d" % (r["refuse"], r["state"]))
    check("the bridge IS driven", bool(r["writes"]),
          "%d write(s)" % len(r["writes"]) if r["writes"] else
          "NOTHING MOVED - this gate cannot see a success, so its negative "
          "results mean nothing")
    if r["writes"]:
        ports = sorted({nm for _pc, nm in r["writes"]})
        check("on P2 (the enable) AND P7 (the two legs), and nowhere else",
              set(ports) <= {"P2", "DP2", "ODP2", "P7", "DP7", "ODP7"}
              and any(p.endswith("P2") for p in ports)
              and any(p.endswith("P7") for p in ports),
              "wrote %s" % ", ".join(ports))
        check("the injector port P8 was never touched",
              not any(nm in ("P8", "DP8", "ODP8") for _pc, nm in r["writes"]),
              "EV4..EV8 live on P8 and have nothing to do with a throttle")
        # The run drives the bridge through the ONE motor primitive every DBW
        # owner uses (hcdbwmotor711.c, enable via the HAL), not a private copy.
        segs = [BOP.seg_range(n) for n in
                ("?PR?HCBENCH", "?PR?HCDBWMOTOR711", "?PR?HCHAL_ME711")]
        pcs = [w[0] for w in r["writes"]]
        check("every write is in hcbench or the shared motor primitive / HAL",
              all(any(lo <= pc <= hi for lo, hi in segs) for pc in pcs),
              "PCs 0x%06X..0x%06X" % (min(pcs), max(pcs)))

    en_bit = 1 << hdr_int("TGT_DBW_EN_PORT_BIT")
    pwm_bit = 1 << hdr_int("TGT_DBW_PWM_PORT_BIT")
    dir_bit = 1 << hdr_int("TGT_DBW_DIR_PORT_BIT")
    check("THE ENABLE IS NOT LEFT ASSERTED", (r["dp2"] & en_bit) == 0,
          "DP2 = 0x%04X, EGENFR (bit 11) is an input again - the one "
          "mistake in this module that could hold a throttle motor"
          % r["dp2"])
    check("and neither leg is left driven",
          (r["dp7"] & (pwm_bit | dir_bit)) == 0,
          "DP7 = 0x%04X" % r["dp7"])
    check("the fault pin was never made an output",
          (r["dp3"] & (1 << hdr_int("TGT_DBW_SF_PORT_BIT"))) == 0,
          "DP3 = 0x%04X, P3.15 stayed an input" % r["dp3"])
    check("the run stops on its own after its nudge count",
          r["state"] in (2, 4),
          "hcbState = %d (2 DONE / 4 ABORTED), %d pulse(s), abort 0x%04X"
          % (r["state"], r["pulses"], r["abort"]))

    # ================================================ the MAIN RELAY mode ==
    #
    # It drives the CONFIGURED cavity, so the vectors are about the cavity as
    # much as about the pulse. The three refusals are not variations on one
    # theme: unassigned, capable-but-unreachable and not-capable are different
    # failures and each has to be caught on its own.
    print("\n  --- the MAIN_RELAY mode, on the CONFIGURED cavity ---")
    relay_pin = BOP.cfg_off("CFG_U_PIN_MAIN_RELAY")
    PIN = BOP.refuse_bit("PIN")

    r = sub([[armed, 1, 1], [relay_pin, 1, 255]], "cmdTestRelay")
    check("an UNASSIGNED main relay cavity is refused", not r["writes"]
          and (r["refuse"] & PIN) != 0,
          "refuse=0x%04X state=%d" % (r["refuse"], r["state"]))

    # Cavity 46 is SLP: RELAY_OUT capable in the descriptor AND driven by the
    # peripheral ASIC's P1L.0, so this CPU cannot reach it. Capability is
    # necessary and not sufficient, and this is the vector that says so.
    r = sub([[armed, 1, 1], [relay_pin, 1, 46]], "cmdTestRelay")
    check("a relay-capable cavity this CPU cannot reach is refused",
          not r["writes"] and (r["refuse"] & PIN) != 0,
          "cavity 46 SLP is on the ASIC - refuse=0x%04X" % r["refuse"])

    # Cavity 92 is IP1_S, an analog input. Not relay capable at all.
    r = sub([[armed, 1, 1], [relay_pin, 1, 92]], "cmdTestRelay")
    check("a cavity with no RELAY_OUT capability is refused",
          not r["writes"] and (r["refuse"] & PIN) != 0,
          "cavity 92 is an analog input - refuse=0x%04X" % r["refuse"])

    # CAVITY 21 IS A POWER INPUT, AND IT USED TO BE THIS GATE'S POSITIVE
    # CONTROL. It is KL15 - the ignition-lock feed into the CJ910's enable pin
    # - settled by three agreeing sources, one of which is this ECU on the
    # bench: remove +12 V from cavity 21 while 3 and 62 stay powered and it
    # goes OFFLINE. The descriptor marks it SPECIAL_LOCKED and hcbench.c no
    # longer carries a port write for it, so it belongs with the other
    # refusals rather than among the successes.
    r = sub([[armed, 1, 1], [relay_pin, 1, 21]], "cmdTestRelay")
    check("cavity 21 - a POWER INPUT - is refused",
          not r["writes"] and (r["refuse"] & PIN) != 0,
          "KL15, not a relay output - refuse=0x%04X" % r["refuse"])

    # The only cavity this build can drive the logical relay on: EKPR, MAIN CPU
    # P2.12/CC12IO through a CJ920, both ME7.1.1 port-map columns agreeing.
    EKP_CAV = hdr_int("TGT_EKP_CONN_PIN")
    EKP_BIT = hdr_int("TGT_EKP_PORT_BIT")

    r = sub([[armed, 1, 0], [cyl, 1, 0], [relay_pin, 1, EKP_CAV]],
            "cmdTestRelay")
    check("invalid page: the relay does not move either",
          not r["writes"] and (r["refuse"] & BOP.refuse_bit("CFG")) != 0,
          "refuse=0x%04X" % r["refuse"])

    # ---------------------------------------------- the positive control --
    r = sub([[armed, 1, 1], [relay_pin, 1, EKP_CAV]], "cmdTestRelay",
            steps=14_000_000)
    check("cavity %d configured and armed: nothing is refused" % EKP_CAV,
          r["refuse"] == 0, "refuse=0x%04X state=%d" % (r["refuse"], r["state"]))
    check("and the relay output IS driven", bool(r["writes"]),
          "%d write(s)" % len(r["writes"]) if r["writes"] else
          "NOTHING MOVED - this gate cannot see a success, so its refusals "
          "mean nothing")
    if r["writes"]:
        ports = sorted({nm for _pc, nm in r["writes"]})
        check("on P2, where cavity %d lives, and nowhere else" % EKP_CAV,
              set(ports) <= {"P2", "DP2", "ODP2"},
              "wrote %s - cavity %d is P2.%d"
              % (", ".join(ports), EKP_CAV, EKP_BIT))
        lo, hi = BOP.seg_range("?PR?HCBENCH")
        pcs = [w[0] for w in r["writes"]]
        check("every write is inside hcbench's own code",
              all(lo <= pc <= hi for pc in pcs),
              "PCs 0x%06X..0x%06X" % (min(pcs), max(pcs)))
    check("THE RELAY PIN IS AN INPUT AGAIN AT THE END",
          (r["dp2"] & (1 << EKP_BIT)) == 0,
          "DP2 = 0x%04X, bit %d clear - a bench command that latched a relay "
          "would be the one thing this mode exists to avoid"
          % (r["dp2"], EKP_BIT))
    check("and the run stopped on its own",
          r["state"] in (2, 4),
          "hcbState=%d (2 DONE / 4 ABORTED), %d pulse(s), abort=0x%04X"
          % (r["state"], r["pulses"], r["abort"]))

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("DBW BENCH PROOF FAILS - DO NOT FLASH. Either an invariant is "
              "not enforced, the enable can be left asserted, or the gate "
              "can no longer see the bridge being driven.")
        return 1
    print("DBW BENCH PROOF PASSES - the bridge needs the TPS pair, the fault "
          "pin and every common invariant at once, it drives only the enable "
          "and the two legs, and it always drops the enable again.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--case":
        spec = json.loads(sys.argv[2])
        BOP.HC_CFG = BOP.sym("hc_cfg")
        print("CASE-RESULT " + json.dumps(
            run_case([tuple(p) for p in spec["pokes"]], spec["cmd"],
                     spec["steps"])))
        raise SystemExit(0)
    raise SystemExit(main())
