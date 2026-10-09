#!/usr/bin/env python3
r"""me711_burn_session_proof.py - a request sent DURING a Burn must not turn
the ECU into a talker.

    py tests\firmware\persistence\me711_burn_session_proof.py

THE DEFECT, AND IT WAS FOUND ON THE REAL ECU
============================================
A Burn's TS_OK is DEFERRED until the flash commit resolves - seconds, not
milliseconds. It is the only reply in this protocol that is sent long after
its request, and that is the whole of the problem:

  * hcts_tx() drops exactly ONE ring byte per transmitted byte, as its own
    K-line echo. The wire is a single bidirectional line, so the echo is
    guaranteed; the accounting is exact ONLY while the ring holds nothing
    else.
  * Until V57, hcts_poll() returned without parsing anything while a reply
    was deferred. Anything the host sent in that window therefore sat in the
    ring AHEAD of the echo.
  * When the Burn finally answered, its seven reply bytes ate the first seven
    bytes of the host's request, and the reply's OWN echo was left in the ring
    to be parsed back out as a command.

MEASURED ON THE PORSCHE ME7.1.1, 2026-09-16, V56: one 11-byte output-channel
request sent 0.5 s into a 2.9 s Burn produced, 35 ms after the Burn's TS_OK,
an unsolicited `00 01 83 A6 B3 3D 17` - a length-1 frame carrying TS_BAD_CMD,
which is TS_RESPONSE_UNRECOGNIZED_COMMAND in TunerStudio's own protocol.
That is the reconnect.

WHY NO EXISTING GATE SAW IT
---------------------------
me711_burn_two_in_session_proof drives its rig with `echo=False`. The modelled K-line
does not loop transmit back into receive, so `echo_seen` self-calibrates to 0
on the first reply and the echo-drop path - the one that fails - never
executes at all. This gate runs the SAME transaction with `echo=True`.

THE CONTROL IS THE FROZEN V56 BINARY, and it is not optional: an experiment
that cannot reproduce the defect cannot claim to have measured its absence.
V56 must emit the spurious TS_BAD_CMD; the current image must not.
"""
from __future__ import annotations

import binascii
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_heartbeat_gap_proof as HB                          # noqa: E402
import me711_image as PI                                        # noqa: E402
import me711_ts_gap_proof as GAP                                # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
BINS = ROOT / "bins/hanicore"

# The control. A FROZEN artefact: it is the image the bench measured the
# defect on, so it is named by hash as well as by stem.
CONTROL_STEM = "HaniCore_ME711_v56_cam_absent_burn_fix"

TS_OK = 0x00
TS_BAD_CMD = 0x83

# The largest envelope this protocol can carry: the whole 4096-byte page plus
# its response code. Bounding the scan keeps a 16-bit length from turning every
# byte pair in a long stream into a candidate.
MAX_FRAME = 4097

# Where in the deferred window the host's request lands. The Burn takes
# seconds; anything past the first few milliseconds is inside it.
INJECT_MS = 120
BURN_LIMIT_MS = 9000

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-64s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


envelope = HB.envelope      # one definition: 16-bit length (see HB)


def frames(stream):
    """Every CRC-valid reply envelope in the stream, left to right.

    Non-overlapping and greedy from the earliest start, which is how a host
    reads the wire. A byte that is not the start of a valid frame is skipped,
    exactly as TunerStudio's own resynchronisation does.
    """
    out = []
    at = 0
    while at < len(stream) - 6:
        # THE LENGTH IS SIXTEEN BITS, AND THIS USED TO READ EIGHT.
        #
        # hcts_send_response() writes `(n+1) >> 8` then `(n+1) & 0xFF`, so a
        # reply longer than 255 bytes has a NON-ZERO high byte - and this
        # parser skipped any position whose first byte was not 0 and then took
        # the length from one byte. **Every output-channel and page reply this
        # firmware sends is bigger than that**, so a gate using this function
        # could not see one at all: it reported "no frame" for a reply that was
        # on the wire and perfectly formed.
        #
        # It never bit, because the two gates that used it looked only for a
        # 1-byte Burn reply and a 17-byte probe. V60 asked it for the 435-byte
        # channel block that carries the Burn's VERDICT and got silence - a
        # blind instrument reading as a firmware failure, which is the fifth
        # time this project has been caught by that shape.
        n = (stream[at] << 8) | stream[at + 1]
        if n == 0 or n > MAX_FRAME:
            at += 1
            continue
        end = at + 2 + n + 4
        if end > len(stream):
            at += 1
            continue
        payload = stream[at + 2:at + 2 + n]
        got = int.from_bytes(stream[at + 2 + n:end], "big")
        if got == (binascii.crc32(payload) & 0xFFFFFFFF):
            out.append((at, end, payload))
            at = end
        else:
            at += 1
    return out


def map_sym(map_path, name):
    for m in re.finditer(r"^\s*([0-9A-F]{6})H\s+(\w+)\s",
                         map_path.read_text(errors="replace"), re.M):
        if m.group(2) == name:
            return int(m.group(1), 16)
    raise SystemExit("%s not in %s" % (name, map_path.name))


def p3_offset():
    ini = ROOT / ("tunerstudio/hanicore_me711_%s.ini"
                  % PI.STEM.replace("HaniCore_ME711_", ""))
    if ini.exists():
        m = re.search(r"^\s*(\w*[Pp]3\w*|persistTestByte\w*)\s*=\s*scalar,"
                      r"\s*U08,\s*(\d+)", ini.read_text(errors="replace"),
                      re.M)
        if m:
            return int(m.group(2))
    return 2427


def transaction(img, mapfile, label, p3_off):
    """edit -> BURN, with one output-channel request injected mid-Burn.

    Returns (frames_after_the_burn_request, trap, burn_ms)."""
    entry = map_sym(mapfile, "hc_asic_start_service")
    tick = map_sym(mapfile, "hc_tick_ms")

    probe = HB.Rig(img, entry, tick, echo=True,
                   steps_per_tick=HB.STEPS_PER_TICK)
    probe.run(GAP.BOOT_WARMUP_STEPS)
    if len(probe.entries) < 2:
        raise SystemExit("%s: warmup reached no supervision entries" % label)
    first, last = probe.entries[0], probe.entries[-1]
    per_ms = (last[1] - first[1]) / ((last[0] - first[0]) & 0xFFFF)
    ms = lambda n: int(n * per_ms)                              # noqa: E731

    rig = HB.Rig(img, entry, tick, echo=True,
                 steps_per_tick=HB.STEPS_PER_TICK)
    rig.run(GAP.BOOT_WARMUP_STEPS + ms(GAP.SETTLE_MS))

    # An ordinary edit first, so the Burn has something to commit and so the
    # echo path is known to be alive before the interesting part.
    edit = envelope(b"W" + p3_off.to_bytes(2, "big") + bytes([0x5A]))
    rig.queue_rx(rig.cpu.steps + 1, edit)
    deadline = rig.cpu.steps + ms(800)
    base = len(rig.tx)
    while rig.cpu.steps < deadline and rig.trap is None:
        rig.run(min(ms(1), deadline - rig.cpu.steps))
        st = bytes(v for _t, v in rig.tx[base:])
        # the edit's own echo comes back first, then the reply
        if [f for _a, _e, f in frames(st) if len(f) == 1]:
            break

    # ---- the Burn, and the request that lands inside its window ----
    start = len(rig.tx)
    sent_at = rig.cpu.steps + 1
    rig.queue_rx(sent_at, envelope(b"B"))
    och = envelope(b"O" + (0).to_bytes(2, "big") + (16).to_bytes(2, "big"))
    rig.queue_rx(sent_at + ms(INJECT_MS), och)

    deadline = rig.cpu.steps + ms(BURN_LIMIT_MS)
    burn_ms = None
    while rig.cpu.steps < deadline and rig.trap is None:
        rig.run(min(ms(2), deadline - rig.cpu.steps))
        st = bytes(v for _t, v in rig.tx[start:])
        fs = frames(st)
        # The Burn's reply is a length-1 frame; the injected read answers with
        # 17 bytes. Stop once both a 1-byte and a 17-byte frame are on the
        # wire, or once the Burn has answered and 300 ms have passed with
        # nothing following it.
        one = [f for _a, _e, f in fs if len(f) == 1]
        big = [f for _a, _e, f in fs if len(f) == 17]
        if one and burn_ms is None:
            burn_ms = (rig.cpu.steps - sent_at) / per_ms
        if one and big:
            break
        if burn_ms is not None and (rig.cpu.steps - sent_at) / per_ms \
                > burn_ms + 300:
            break

    st = bytes(v for _t, v in rig.tx[start:])
    return frames(st), rig.trap, burn_ms


def main():
    print("=== a request sent DURING a Burn must not make the ECU talk ===\n")
    p3_off = p3_offset()

    img = PI.image()
    print("  image   %s" % img.name)
    print("  sha256  %s" % PI.sha256())
    print("  control %s" % CONTROL_STEM)
    print("  the host's request lands %d ms into the deferred window\n"
          % INJECT_MS)

    # ------------------------------------------------ the image under test
    print("  --- the image under test ---")
    fs, trap, burn_ms = transaction(img, PI.MAP, "current", p3_off)
    check("no trap and no reset across the Burn", trap is None, str(trap))
    codes = [f[0] for _a, _e, f in fs]
    one = [f for _a, _e, f in fs if len(f) == 1]
    big = [f for _a, _e, f in fs if len(f) == 17]
    print("      frames after the B: %s"
          % ", ".join("%d:0x%02X" % (len(f), f[0]) for _a, _e, f in fs))
    check("the Burn itself answers TS_OK",
          bool(one) and one[0][0] == TS_OK,
          ("0x%02X" % one[0][0]) if one else "no reply"
          + ("" if burn_ms is None else " after %.0f ms" % burn_ms))
    check("the request sent during the Burn is ANSWERED, not eaten",
          bool(big) and big[0][0] == TS_OK,
          "%d-byte output-channel reply" % (len(big[0]) if big else 0))
    check("and the ECU emits NO unrecognised-command frame at all",
          TS_BAD_CMD not in codes,
          "codes " + " ".join("0x%02X" % c for c in codes))
    # THE GENERAL RULE, ADDED AT V60. TunerStudio ends the session on EVERY
    # response code with bit 7 set, not only on 0x83 - read out of
    # TunerStudioMS.jar, class J/f. A gate that names one code leaves the next
    # person free to pick another, which is exactly what happened when V60's
    # first fix reached for TS_OUT_OF_RANGE.
    check("and no bit-7 response code at all - the whole session-fatal class",
          not [c for c in codes if c & 0x80],
          "codes " + " ".join("0x%02X" % c for c in codes))
    check("the Burn's reply comes FIRST, in request order",
          bool(one) and bool(big)
          and [len(f) for _a, _e, f in fs].index(1)
          < [len(f) for _a, _e, f in fs].index(17),
          "order " + " ".join(str(len(f)) for _a, _e, f in fs))

    # --------------------------------------------------------- the control
    print("\n  --- the control: the frozen V56 binary, same transaction ---")
    cimg = BINS / (CONTROL_STEM + ".bin")
    cmap = BINS / (CONTROL_STEM + ".M66")
    if not (cimg.exists() and cmap.exists()):
        check("the control binary is present", False,
              "%s missing - this gate cannot prove it measures anything"
              % cimg.name)
    else:
        cfs, ctrap, _cms = transaction(cimg, cmap, "V56", p3_off)
        ccodes = [f[0] for _a, _e, f in cfs]
        print("      frames after the B: %s"
              % ", ".join("%d:0x%02X" % (len(f), f[0])
                          for _a, _e, f in cfs))
        check("V56 reproduces the defect - it answers its own reply back",
              TS_BAD_CMD in ccodes,
              "codes " + " ".join("0x%02X" % c for c in ccodes))
        check("and the control did not simply crash instead",
              ctrap is None, str(ctrap))

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("BURN SESSION PROOF FAILED")
        return 1
    print("BURN SESSION PROOF PASSES - a host may poll during a Burn and the "
          "ECU\nanswers it afterwards, in order, and says nothing it was not "
          "asked for.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
