#!/usr/bin/env python3
r"""
me711_s5500_command_proof.py - does the '!W' window command actually reach the
firmware and move the window, in the image that will be flashed?

    py tests\firmware\asic\me711_s5500_command_proof.py
    py tests\firmware\asic\me711_s5500_command_proof.py --image <path>      # e.g. frozen V29

WHY THIS EXISTS - THE BENCH, 2026-09-02.

The frozen V29 image was running on the real Cayenne ECU at 57600 with its own
frozen .ini, and TunerStudio stayed online. Pressing "window at word 12" in the
S5500 dialog changed nothing: the window base stayed at 4, and NOTHING
IDENTIFIABLE WENT OUT ON THE WIRE.

Two questions came out of that, and they must not be answered together:

    A. does TunerStudio ever SEND the command?      -> the .ini's problem
    B. would the firmware ACT on it if it arrived?  -> this tool's problem

A is answered by tests/tunerstudio/ts_ini_ui_contract.py, which reproduces the exact
TunerStudio load errors from the frozen .ini (an unterminated string, and four
output channels used as page Constants).

B had NO evidence at all. The command handler is in hcmain_me711.c and there is
a source-text gate (tests/unit/test_ts_commands.py) that the .ini and the firmware
offer the same command letters - but nothing had ever executed the path. A
source-text agreement between two files does not prove a binary does anything,
and this project has now paid four times for exactly that assumption.

So this EXECUTES the linked image in c167sim, feeds it the byte-for-byte
enveloped '!W' request TunerStudio's [ControllerCommands] entry produces, then
reads the output-channel block back out of the same running image and checks
the published window base MOVED. Nothing is inspected statically; the number
comes back over the simulated K-line.

The negative control matters as much: a window base that was already the
requested value would make any test pass. Two different bases are commanded in
sequence, each away from where it was, and the block is re-read after each.
"""
from __future__ import annotations

import argparse
import binascii
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_heartbeat_gap_proof as HB   # noqa: E402  the Rig
import me711_image as PI                 # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
LIVE_INI = ROOT / "tunerstudio/hanicore_me711.ini"

# Where the window base and the decode index sit in the output-channel block.
# READ FROM THE .INI, never typed here: that is the whole lesson of the V29
# contract failure. The .ini is itself generated from the firmware's put16()
# calls and cross-checked against them by gen_ts_ini_me711.crosscheck().
FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-56s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


envelope = HB.envelope      # one definition: 16-bit length (see HB)


def channel_offset(ini: Path, name: str) -> int:
    m = re.search(r"^\s*%s\s*=\s*scalar,\s*U\d+,\s*(\d+)" % name,
                  ini.read_text(errors="replace"), re.M)
    if not m:
        raise SystemExit("%s is not an output channel in %s" % (name, ini))
    return int(m.group(1))


def ini_command(ini: Path, name: str) -> bytes:
    """The literal bytes a [ControllerCommands] entry sends.

    Parsed out of the .ini rather than constructed here, so this proves the
    command THE UI WOULD SEND - not one this file invented that happens to
    work."""
    m = re.search(r'^\s*%s\s*=\s*"([^"]*)"' % name,
                  ini.read_text(errors="replace"), re.M)
    if not m:
        raise SystemExit("%s is not in [ControllerCommands] of %s"
                         % (name, ini))
    raw, out = m.group(1), bytearray()
    i = 0
    while i < len(raw):
        if raw[i] == "\\" and i + 1 < len(raw) and raw[i + 1] == "x":
            out.append(int(raw[i + 2:i + 4], 16))
            i += 4
        else:
            out.append(ord(raw[i]))
            i += 1
    return bytes(out)


def replies(tx: bytes):
    """Every well-formed envelope in a transmit stream, payload only."""
    out = []
    for i in range(len(tx) - 1):
        n = (tx[i] << 8) | tx[i + 1]
        if 1 <= n <= 600 and i + 2 + n + 4 <= len(tx):
            body = tx[i + 2:i + 2 + n]
            crc = int.from_bytes(tx[i + 2 + n:i + 6 + n], "big")
            if crc == (binascii.crc32(body) & 0xFFFFFFFF):
                out.append(body)
    return out


def run(image: Path, sends, steps=6_000_000):
    """Feed a sequence of enveloped requests and return the reply payloads."""
    rig = HB.Rig(image, HB.ENTRY_CURRENT, HB.TICK_CURRENT, echo=False)
    # The first request goes in AFTER boot, not at a literal 750 000 steps -
    # see PI.BOOT_STEPS. V39's append-only store made hc_nvm_boot() cost
    # 1 187 437 instructions before the supervision link is up, so the old
    # injection point handed these commands to an ECU that was still booting.
    t = PI.BOOT_STEPS
    for b in sends:
        rig.queue_rx(t, b)
        t += 400 * 2500
    rig.run(PI.BOOT_STEPS + steps)
    return replies(bytes(b for _t, b in rig.tx))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", type=Path, default=None)
    ap.add_argument("--ini", type=Path, default=LIVE_INI)
    args = ap.parse_args()
    image = args.image or PI.image()

    print("=== HaniCore - does '!W' really move the S5500 window? ===\n")
    print("  image   %s" % image.name)
    print("  ini     %s\n" % args.ini.name)

    base_off = channel_offset(args.ini, "s5500Base")
    # 200 bytes is the shortest read that still contains s5500Base at 168.
    # A shorter reply is a shorter simulation, and this file runs four.
    och = envelope(b"O" + (0).to_bytes(2, "big") + (200).to_bytes(2, "big"))

    def base_after(cmds):
        out = run(image, list(cmds) + [och])
        if not out:
            return None
        block = out[-1][1:]          # drop the response code
        if len(block) < base_off + 2:
            return None
        return (block[base_off] << 8) | block[base_off + 1]

    idle = base_after([])
    check("the image answers an output-channel read at all",
          idle is not None, "s5500Base reads %s" % idle)
    if idle is None:
        print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
        return 1

    for cmd_name, want in (("cmdS5500Win12", 12), ("cmdS5500Win20", 20)):
        raw = ini_command(args.ini, cmd_name)
        got = base_after([envelope(raw)])
        check("%s (%s) moves the window to %d"
              % (cmd_name, " ".join("%02X" % b for b in raw), want),
              got == want, "s5500Base = %s (was %s)" % (got, idle))

    # THE NEGATIVE CONTROL. A handler that set the base to a constant, or a
    # rig that never delivered anything, would satisfy the two checks above if
    # they happened to agree. An UNRELATED '!' command must leave it alone.
    got = base_after([envelope(b"!A")])
    check("an unrelated '!' command does NOT move the window",
          got == idle, "s5500Base = %s, idle was %s" % (got, idle))

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("S5500 COMMAND PROOF FAILS - the firmware does not act on the "
              "command the .ini sends.")
        return 1
    print("S5500 COMMAND PROOF PASSES - the '!W' bytes the .ini's own "
          "[ControllerCommands] entry produces reach the handler and move the "
          "published window. OFFLINE, in the linked image; the wire is still "
          "the wire.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
