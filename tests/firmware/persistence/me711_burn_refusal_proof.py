#!/usr/bin/env python3
r"""me711_burn_refusal_proof.py - a Burn that cannot be done is not an
unrecognised command.

    py tests\firmware\persistence\me711_burn_refusal_proof.py

THE DEFECT, AND IT WAS FOUND BY REAL TUNERSTUDIO ON THE REAL ECU
================================================================
`nvm_fail()` answered EVERY failed Burn with `TS_BAD_CMD` from V40 to V59.

`0x83` is TunerStudio's own `TS_RESPONSE_UNRECOGNIZED_COMMAND`
(rusEFI firmware/integration/ts_protocol.txt:62). It does not mean
"that did not work". It means "this controller does not implement the command
you sent", which is a statement about the PROTOCOL - so TunerStudio stops
believing its own idea of what the ECU can do, drops the session and runs the
signature handshake again. The page is still dirty and still invalid when it
comes back, so the next Burn says `0x83` again. **That is the reconnect loop
the operator saw.**

MEASURED ON THE PORSCHE ME7.1.1, 2026-09-16, V59, with nothing flashed and the
failing page preserved exactly as real TunerStudio left it - `syncMode = 1`
with `pinCrank` unassigned, which is the project's own A/B/A stimulus:

    TX 0001424ad0cf31                    the framed 'B'
    RX 0001424ad0cf31 000183a6b33d17     its echo, then TS_BAD_CMD in 22 ms

Four Burns, four identical replies, `rstBootCount` 4 -> 4, `rxResync`,
`rxHwOvr`, `rxOvf` and `rxEchoLost` all unmoved, and a clean signature straight
afterwards. **No reset. No lost byte. No parser residue. The response code was
the whole defect.** bench measurements

AND THE OBVIOUS FIX WAS ALSO WRONG. `TS_RESPONSE_OUT_OF_RANGE` (0x84) is what
rusEFI answers a Burn it cannot perform with (tunerstudio.cpp:540), so it
looked like the answer. It is not. Read out of TunerStudio MS 3.3.01 itself -
`TunerStudioMS.jar`, class `J/f`, method `b(byte[], byte[])`:

    int code = d(response);            // response[2]
    if ((code & 0x80) != 0x80) {
        return true;                   // ACCEPTED, and never looked at
    }
    ... one arm per code, 0x80 through 0x90, each naming and counting it ...
    return false;                      // EVERY one of them

**EVERY code with bit 7 set ends the session. There is no soft error code in
this protocol.** So a refusal cannot be spelled in a response code at all: the
reply acknowledges the REQUEST, and the OUTCOME is published in the channels
the .ini already carries - `nvmState`, `nvmError`, `cfgValidation`,
`cfgFirstBadOffset`, and the `nvmBurnFailed` / `nvmNotBurned` indicators.

THE INVARIANT THIS GATE ENFORCES IS THEREFORE THE GENERAL ONE: no legitimate
operation may put a bit-7 code on the wire. Not 0x83, not 0x84, not any of
them.

WHAT THIS GATE DRIVES
---------------------
The linked image, in c167sim, with the modelled K-line echoing exactly as the
wire does:

    W syncMode = 1  ->  W pinCrank = 0xFF  ->  B  ->  B  ->  B  ->  S

The page is then genuinely not runnable (`HC_VAL_FAULT_SYNC`, first bad offset
`CFG_U_PIN_CRANK`), so the Burn MUST be refused - that part is the safety
design and is not what changed. What changed is what the refusal is called.

THE CONTROL IS THE FROZEN V59 BINARY and it is not optional: a gate that
cannot reproduce the defect cannot claim to have measured its absence.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_burn_session_proof as BS                          # noqa: E402
import me711_heartbeat_gap_proof as HB                         # noqa: E402
import me711_image as PI                                       # noqa: E402
import me711_ts_gap_proof as GAP                               # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
BINS = ROOT / "bins/hanicore"
SHARED = ROOT / "firmware"

CONTROL_STEM = "HaniCore_ME711_v59_forensic_window"

TS_OK = 0x00
TS_BAD_CMD = 0x83
TS_OUT_OF_RANGE = 0x84
# What a Burn this ECU cannot perform answers with. TS_OK, because every
# alternative ends the session - see the header.
TS_REFUSED = TS_OK

def nvm_const(name):
    h = (ROOT / "firmware/targets/me711/nvm/hcnvm.h"
         ).read_text(errors="replace")
    m = re.search(r"^#define\s+%s\s+(\d+)u" % re.escape(name), h, re.M)
    if not m:
        raise SystemExit("%s is not in hcnvm.h" % name)
    return int(m.group(1))

def cfg_offset(name):
    """An offset out of the GENERATED config header, never typed here."""
    h = (SHARED / "generated/hc_config_generated.h").read_text(errors="replace")
    m = re.search(r"^#define\s+%s\s+(\d+)u" % re.escape(name), h, re.M)
    if not m:
        raise SystemExit("%s is not in hc_config_generated.h" % name)
    return int(m.group(1))

def val_fault(name):
    h = (SHARED / "config/hc_validation.h").read_text(errors="replace")
    m = re.search(r"^#define\s+%s\s+0x([0-9A-Fa-f]{4})u" % re.escape(name),
                  h, re.M)
    if not m:
        raise SystemExit("%s is not in hc_validation.h" % name)
    return int(m.group(1), 16)


BURN_LIMIT_MS = 9000
N_BURNS = 3

# THE CHANNELS THAT CARRY THE VERDICT, and their offsets come out of the .ini
# this build generated - never typed here. Reading only as far as the last one
# keeps the reply short enough to be modelled in reasonable time.
OCH_NAMES = ("nvmState", "nvmError", "cfgValidation", "cfgFirstBadOffset")


def _och_map():
    ini = (ROOT / "tunerstudio"
           / ("hanicore_me711_%s.ini"
              % PI.STEM.replace("HaniCore_ME711_", "")))
    if not ini.exists():
        ini = ROOT / "tunerstudio/hanicore_me711.ini"
    txt = ini.read_text(errors="replace")
    body = txt.split("[OutputChannels]", 1)[1]
    out = {}
    for n in OCH_NAMES:
        m = re.search(r"^\s*%s\s*=\s*scalar,\s*U16,\s*(\d+)" % n, body, re.M)
        if not m:
            raise SystemExit("%s is not an output channel in %s" % (n, ini.name))
        out[n] = int(m.group(1))
    return out


OCH_WANT = _och_map()
OCH_TAIL = max(OCH_WANT.values()) + 2
HCNV_ST_FAILED = nvm_const("HCNV_ST_FAILED")
HCNV_ERR_VALIDATE = nvm_const("HCNV_ERR_VALIDATE")

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-66s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def session(img, mapfile, label):
    """Make the page unrunnable, then Burn it three times, then ask who we are.

    Returns (per_burn_frames, signature_frames, trap)."""
    entry = BS.map_sym(mapfile, "hc_asic_start_service")
    tick = BS.map_sym(mapfile, "hc_tick_ms")

    probe = HB.Rig(img, entry, tick, echo=True,
                   steps_per_tick=HB.STEPS_PER_TICK)
    probe.run(GAP.BOOT_WARMUP_STEPS)
    if len(probe.entries) < 2:
        raise SystemExit("%s: warmup reached no supervision entries" % label)
    first, last = probe.entries[0], probe.entries[-1]
    per_ms = (last[1] - first[1]) / ((last[0] - first[0]) & 0xFFFF)

    def ms(n):
        return int(n * per_ms)

    rig = HB.Rig(img, entry, tick, echo=True,
                 steps_per_tick=HB.STEPS_PER_TICK)
    rig.run(GAP.BOOT_WARMUP_STEPS + ms(GAP.SETTLE_MS))

    def one(payload, limit_ms, want_len=1):
        """Send one framed request and collect everything that follows it."""
        start = len(rig.tx)
        sent = rig.cpu.steps + 1
        rig.queue_rx(sent, BS.envelope(payload))
        deadline = rig.cpu.steps + ms(limit_ms)
        while rig.cpu.steps < deadline and rig.trap is None:
            rig.run(min(ms(2), deadline - rig.cpu.steps))
            st = bytes(v for _t, v in rig.tx[start:])
            if [f for _a, _e, f in BS.frames(st) if len(f) >= want_len]:
                # AND THEN KEEP LISTENING. A gate that stops at the first
                # frame cannot see a second, unsolicited one - which is the
                # whole class of defect the V57 session proof exists for.
                rig.run(min(ms(300), max(1, deadline - rig.cpu.steps)))
                break
        st = bytes(v for _t, v in rig.tx[start:])
        return [f for _a, _e, f in BS.frames(st)]

    # THE EDIT. syncMode = CRANK_ONLY with no crank pin is a page that cannot
    # run, and it is a TRIGGER-group edit - the exact shape the operator made.
    one(b"W" + cfg_offset("CFG_U_SYNC_MODE").to_bytes(2, "big") + bytes([1]),
        800)
    one(b"W" + cfg_offset("CFG_U_PIN_CRANK").to_bytes(2, "big") + bytes([0xFF]),
        800)

    burns = [one(b"B", BURN_LIMIT_MS) for _ in range(N_BURNS)]

    # AND THEN ASK THE ECU WHAT IT THINKS HAPPENED. With the refusal no longer
    # in the response code, the channels ARE the verdict - so a gate that only
    # looked at the code could pass against an image that quietly SUCCEEDED,
    # which would prove nothing about a refusal at all.
    och = one(b"O" + (0).to_bytes(2, "big") + OCH_TAIL.to_bytes(2, "big"),
              3000, want_len=OCH_TAIL + 1)
    verdict = {}
    for f in och:
        if len(f) == OCH_TAIL + 1:
            blob = f[1:]
            for name, off in OCH_WANT.items():
                if off + 1 < len(blob):
                    verdict[name] = (blob[off] << 8) | blob[off + 1]
            break

    sig = one(b"S", 1500, want_len=2)
    return burns, sig, rig.trap, verdict


def report(label, burns, sig, trap, verdict, expect_code):
    check("%s: no trap and no reset across three refused Burns" % label,
          trap is None, str(trap))
    for i, fs in enumerate(burns, 1):
        codes = [f[0] for f in fs]
        print("      Burn %d frames: %s" % (
            i, ", ".join("%d:0x%02X" % (len(f), f[0]) for f in fs) or "(none)"))
        check("%s: Burn %d answers exactly ONE frame" % (label, i),
              len(fs) == 1, "%d frames" % len(fs))
        check("%s: Burn %d answers 0x%02X" % (label, i, expect_code),
              bool(fs) and fs[0][0] == expect_code,
              ("0x%02X" % codes[0]) if codes else "no reply")
    allcodes = [f[0] for fs in burns for f in fs] + [f[0] for f in sig]
    # THE GENERAL INVARIANT, and the specific one is a special case of it.
    # TunerStudio ends the session on EVERY code with bit 7 set, so naming
    # 0x83 alone would leave the next person free to pick 0x84.
    bad = [c for c in allcodes if c & 0x80]
    check("%s: no bit-7 response code anywhere - not one of them survives "
          "the session" % label, not bad,
          "codes " + " ".join("0x%02X" % c for c in allcodes))
    check("%s: and TS_BAD_CMD in particular is absent" % label,
          TS_BAD_CMD not in allcodes,
          "codes " + " ".join("0x%02X" % c for c in allcodes))
    check("%s: the session survives - the signature still answers" % label,
          bool(sig) and sig[0][0] == TS_OK and len(sig[0]) > 2,
          (sig[0][1:].decode("latin1", "replace") if sig else "no reply"))

    # NON-VACUITY. The Burn must actually have been REFUSED, and the ECU has
    # to be the one saying so.
    print("      verdict channels: %s"
          % ", ".join("%s=%d" % (k, verdict[k])
                      for k in OCH_NAMES if k in verdict) or "(none read)")
    check("%s: the ECU says the Burn FAILED - nvmState 6" % label,
          verdict.get("nvmState", -1) == HCNV_ST_FAILED,
          "nvmState %s" % verdict.get("nvmState"))
    check("%s: and names the reason - nvmError low byte 2, would not validate"
          % label, (verdict.get("nvmError", -1) & 0xFF) == HCNV_ERR_VALIDATE,
          "nvmError 0x%04X" % verdict.get("nvmError", 0))
    check("%s: and names the rule - cfgValidation HC_VAL_FAULT_SYNC" % label,
          verdict.get("cfgValidation", -1) == val_fault("HC_VAL_FAULT_SYNC"),
          "cfgValidation 0x%04X" % verdict.get("cfgValidation", 0))
    check("%s: and names the BYTE - cfgFirstBadOffset is pinCrank" % label,
          verdict.get("cfgFirstBadOffset", -1) == cfg_offset("CFG_U_PIN_CRANK"),
          "cfgFirstBadOffset %s" % verdict.get("cfgFirstBadOffset"))


def main():
    print("=== a refused Burn must not be called an unrecognised command ===\n")
    print("  CFG_U_SYNC_MODE  @%d" % cfg_offset("CFG_U_SYNC_MODE"))
    print("  CFG_U_PIN_CRANK  @%d" % cfg_offset("CFG_U_PIN_CRANK"))
    print("  the fault this raises is HC_VAL_FAULT_SYNC = 0x%04X\n"
          % val_fault("HC_VAL_FAULT_SYNC"))

    img = PI.image()
    print("  image   %s" % img.name)
    print("  sha256  %s" % PI.sha256())
    print("  control %s\n" % CONTROL_STEM)

    print("  --- the image under test ---")
    burns, sig, trap, verdict = session(img, PI.MAP, "current")
    report("current", burns, sig, trap, verdict, TS_REFUSED)

    print("\n  --- the control: the frozen V59 binary, same session ---")
    cimg = BINS / (CONTROL_STEM + ".bin")
    cmap = BINS / (CONTROL_STEM + ".M66")
    if not (cimg.exists() and cmap.exists()):
        check("the control binary is present", False,
              "%s missing - this gate cannot prove it measures anything"
              % cimg.name)
    else:
        cb, csig, ctrap, cverdict = session(cimg, cmap, "V59")
        ccodes = [f[0] for fs in cb for f in fs]
        print("      V59 Burn frames: %s"
              % ", ".join("0x%02X" % c for c in ccodes))
        check("V59 reproduces the defect - it calls a refused Burn 0x83",
              TS_BAD_CMD in ccodes,
              "codes " + " ".join("0x%02X" % c for c in ccodes))
        check("and the control did not simply crash instead",
              ctrap is None, str(ctrap))
        check("V59's parser was never the problem - its signature answers too",
              bool(csig) and csig[0][0] == TS_OK,
              "0x%02X" % csig[0][0] if csig else "no reply")

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("BURN REFUSAL PROOF FAILED")
        return 1
    print("BURN REFUSAL PROOF PASSES - a Burn this ECU cannot perform puts no "
          "bit-7\ncode on the wire, says so in its channels instead, and the "
          "session survives\nit three times over.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
