#!/usr/bin/env python3
r"""
me711_loader_proof.py - the update loader (firmware/loader/hcloader.a66),
EXECUTED: boot decision, the STAGING -> APP copy, and a power cut at every
step of it.

    py tests\firmware\build\me711_loader_proof.py [--board <board>] [--cuts N]

The loader binary is bins/hanicore/HaniCore_loader_<board>.bin
(tools/build/build_loader.py). Each case composes a 1 MiB flash in memory -
SA5 = the loader, SA6.. = an "old" app, SA15.. = a "new" one, both with the
32-byte header at sector offset 0x200 - and runs c167sim from the loader's
entry, as the boot region hands over. An SRST is a reset: the CPU starts
again at the entry with flash and battery SRAM as they were; a POWER CUT
additionally aborts whatever the flash was doing (an interrupted erase
leaves its sector pre-programmed to 0x00, the model's own behaviour).

  L1  app sealed, no request       -> the app's entry, no flash write, < 1 ms
  L2  request + STAGING sealed     -> copy, SRST, the NEW app runs; APP is
                                      byte for byte STAGING; request cleared
  L3  app unsealed + STAGING sealed (no request: a cut copy) -> copied again
  L4  request, STAGING not sealed  -> request dropped, the OLD app runs
  L5  STAGING for ANOTHER board    -> not copied (CONTROL for the board code)
  L6  nothing valid                -> stops, writes nothing, watchdog off
  L7  a power cut at every Nth flash cycle of the copy -> every boot after
      it ends in the old app (cut before the first erase) or, after the
      retries, the new one - never an app that runs unsealed
  L8  no instruction ever fetched from the flash while it was busy
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402
import c167sim as S  # noqa: E402

BOARDS = {"porsche_me711": 1, "vag_me71_c4": 2, "audi_4f_v8": 3, "vag_me75_dc": 4,
          "vag_me75_bfb": 5}
BOARD = os.environ.get("HANICORE_BOARD", "porsche_me711")
if "--board" in sys.argv:
    BOARD = sys.argv[sys.argv.index("--board") + 1]
CUTS = int(sys.argv[sys.argv.index("--cuts") + 1]) if "--cuts" in sys.argv else 12
LOADER = ROOT / "bins/hanicore" / f"HaniCore_loader_{BOARD}.bin"
ENTRY = 0x820200
APP, STG, HDR = 0x030000, 0x0C0000, 0x200
APP_ENTRY = 0x830400
SEAL = 0x5AA5
REQ = 0x386904
STEPS_PER_MS = 2500

CHECKS = FAILS = 0


def check(name, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))


def app_image(tag: int, board: int, length: int = 0x1800, sealed=True) -> bytes:
    """An app: header, and at 0x830400 MOV R15,#tag / JMPR $ - which app
    reached its entry is read off R15."""
    a = bytearray(b"\xFF" * length)
    def w16(o, v):
        a[o:o + 2] = (v & 0xFFFF).to_bytes(2, "little")
    w16(HDR + 0, 0x4348); w16(HDR + 2, 0x5041); w16(HDR + 4, board)
    w16(HDR + 6, APP_ENTRY & 0xFFFF); w16(HDR + 8, APP_ENTRY >> 16)
    w16(HDR + 10, length & 0xFFFF); w16(HDR + 12, length >> 16)
    if sealed:
        w16(HDR + 30, SEAL)
    code = bytes((0xE6, 0xFF, tag & 0xFF, tag >> 8, 0x0D, 0xFF))  # MOV R15,#tag; JMPR $
    a[0x400:0x400 + len(code)] = code
    for i in range(0x600, length, 2):                # payload, never 0xFFFF
        w16(i, (i * 2654435761 + tag) & 0x7FFF)
    return bytes(a)


def flash(old=None, new=None):
    img = bytearray(b"\xFF" * 0x100000)
    img[0x20000:0x30000] = LOADER.read_bytes()
    if old:
        img[APP:APP + len(old)] = old
    if new:
        img[STG:STG + len(new)] = new
    return img


def power_cut(m):
    """Power gone: an outstanding erase or program is aborted where it was."""
    m.fl_erase_sector = None
    m.fl_suspended = False
    m.fl_busy = 0
    m.fl_state = 0


def boot(m, limit=3_000_000, cut_at=None):
    """Run from the loader's entry. Returns (how, steps, R15): 'app' when the
    app's entry loop is reached, 'srst', 'dead', 'cut' or 'limit'."""
    cpu = S.CPU(m, ENTRY >> 16, ENTRY & 0xFFFF)
    m.sfr[0xFE12] = 0xFC00                   # SP / STKOV / STKUN after reset
    m.sfr[0xFE14] = 0xFA00
    m.sfr[0xFE16] = 0xFC00
    m.sfr[0xFE10] = 0xFC00
    w0 = len(m.flash_writes)
    seen = {}
    for n in range(limit):
        pc = (cpu.csp << 16) | cpu.ip
        if pc == APP_ENTRY + 4:
            return "app", n, cpu.gr(15)
        if cut_at is not None and len(m.flash_writes) - w0 >= cut_at:
            power_cut(m)
            return "cut", n, None
        seen[pc] = seen.get(pc, 0) + 1
        if seen[pc] > 200000 and len(m.flash_writes) == w0:
            return "dead", n, None
        try:
            m.fetching = True
            cpu.step()
        except S.Trap as e:
            if "SRST" in str(e):
                return "srst", n, None
            return "trap " + str(e), n, None
        finally:
            m.fetching = False
    return "limit", limit, None


def mem(img, request=False):
    m = S.Mem(bytes(img))
    m.fl_erase_work = 3000                  # quick erases; the shape matters
    if request:
        m.w16(REQ, 0x5055); m.w16(REQ + 2, 0x5444)
    return m


def app_bytes(m, n):
    return bytes(m.flash[APP:APP + n])


def run_until_app(m, max_boots=6):
    hows = []
    for _ in range(max_boots):
        how, n, tag = boot(m)
        hows.append(how)
        if how != "srst":
            return how, tag, hows, n
    return "too many resets", None, hows, 0


def main() -> int:
    if not LOADER.exists():
        print("SKIP: %s not built (tools/build/build_loader.py --board %s)" % (LOADER.name, BOARD))
        return 0
    code = BOARDS[BOARD]
    print("=== update loader, executed - %s (board code %d) ===\n" % (BOARD, code))
    old, new = app_image(0x0111, code), app_image(0x0222, code, 0x2400)

    m = mem(flash(old, new))
    how, n, tag = boot(m)
    check("L1 sealed app, no request: the app runs", how == "app" and tag == 0x0111,
          "%s, R15 0x%04X" % (how, tag or 0))
    check("L1 ...in under 1 ms, with no flash write",
          n < STEPS_PER_MS and not m.flash_writes, "%d steps, %d writes" % (n, len(m.flash_writes)))

    m = mem(flash(old, new), request=True)
    how, tag, hows, _ = run_until_app(m)
    check("L2 request + sealed STAGING: copy, SRST, the NEW app runs",
          how == "app" and tag == 0x0222 and hows[0] == "srst", "%s, boots %s" % (how, hows))
    check("L2 APP is STAGING byte for byte (with the seal)",
          app_bytes(m, len(new)) == new, "")
    check("L2 the request is cleared", m.r16(REQ) == 0, "0x%04X" % m.r16(REQ))
    check("L8 no fetch from busy flash during the copy", m.fl_fetch_while_busy == 0,
          "%d" % m.fl_fetch_while_busy)

    img = flash(app_image(0x0111, code, sealed=False), new)
    m = mem(img)
    how, tag, hows, _ = run_until_app(m)
    check("L3 unsealed app + sealed STAGING (a cut copy): copied again",
          how == "app" and tag == 0x0222, "%s, boots %s" % (how, hows))

    m = mem(flash(old, app_image(0x0222, code, sealed=False)), request=True)
    how, n, tag = boot(m)
    check("L4 request, STAGING not sealed: dropped, the OLD app runs",
          how == "app" and tag == 0x0111 and m.r16(REQ) == 0 and not m.flash_writes,
          "%s, request 0x%04X, writes %d" % (how, m.r16(REQ), len(m.flash_writes)))

    other = (code % 4) + 1
    m = mem(flash(old, app_image(0x0222, other)), request=True)
    how, n, tag = boot(m)
    check("L5 CONTROL: STAGING for board %d is not copied" % other,
          how == "app" and tag == 0x0111 and not m.flash_writes, "%s, R15 0x%04X" % (how, tag or 0))

    m = mem(flash(None, None))
    how, n, tag = boot(m)
    check("L6 nothing valid: stops, writes nothing", how == "dead" and not m.flash_writes, how)

    # L7: count the copy's flash cycles once, then cut at spread points
    m = mem(flash(old, new), request=True)
    w0 = len(m.flash_writes)
    boot(m)
    total = len(m.flash_writes) - w0
    bad = []
    for k in range(CUTS):
        at = 1 + (total - 1) * k // max(CUTS - 1, 1)
        m = mem(flash(old, new), request=True)
        how, n, tag = boot(m, cut_at=at)
        if how != "cut":
            bad.append((at, "no cut: " + how))
            continue
        how, tag, hows, _ = run_until_app(m)
        ok_old = how == "app" and tag == 0x0111 and app_bytes(m, len(old)) == old
        ok_new = how == "app" and tag == 0x0222 and app_bytes(m, len(new)) == new
        if not (ok_old or ok_new):
            bad.append((at, "%s tag %s boots %s" % (how, tag, hows)))
        if m.fl_fetch_while_busy:
            bad.append((at, "fetch while busy"))
    check("L7 a power cut at %d points of the %d-cycle copy: old or new app, never broken"
          % (CUTS, total), not bad, "%s" % (bad[:3] or "all recovered"))

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("LOADER PROOF FAILS")
        return 1
    print("LOADER PROOF PASSES - the boot decision, the copy and every cut recover.")
    print("NOT PHYSICALLY VERIFIED: no loader has run on an ECU.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
