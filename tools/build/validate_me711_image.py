#!/usr/bin/env python3
r"""
validate_me711_image.py - prove the clean HaniCore Bosch image is
what it claims to be, before anybody puts it near an ECU.

    py tools\build\validate_me711_image.py

Ten checks, and the one that matters most is #6: a scan of every executable
target in every byte of HaniCore code, proving that nothing branches into the
896 KiB of Bosch application this build deleted. A single CALLS left pointing
at removed code is an ECU that boots, runs, and then jumps into blank flash.

Every check prints PASS or FAIL and the script exits non-zero if any failed.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

ROOT = Path(__file__).resolve().parents[2]
import me711_image as PI  # ONE source of truth for the image under test
IMG = PI.image()
MANIFEST = PI.MANIFEST
TARGET_DIR = ROOT / "firmware/targets/me711"
CONTRACT = TARGET_DIR / "boot_contract/me711_boot_contract.bin"

IMAGE_SIZE = 0x100000
CONTRACT_LEN = 0x20000
HEADER = 0x8000
PAGE = 0x2000
ISR_TABLE = 0x020000
from me711_nvm_geometry import GEO   # code sector comes from hctarget.h
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("build", Path(__file__).resolve().parents[2]
                                     / "tools/build/build_hanicore_me711.py")
build = _ilu.module_from_spec(_spec); _spec.loader.exec_module(build)
CODE_LO = GEO.code_base - 0x800000
CODE_HI = CODE_LO + GEO.code_size - 1
STORE_LO = GEO.file_base
STORE_HI = GEO.file_base + GEO.sectors * GEO.sector_size - 1

# WHERE THE FAR-BRANCH SCAN MAY LOOK, and why it is not CODE_LO..CODE_HI.
#
# 0x0E0000-0x0EFFFF is one 64 KiB erase sector and it holds THREE different
# things: the parked vector table, the executable classes ICODE and NCODE, and
# then NCONST - `const` data, which the C167 never executes.
#
# The far-branch scan is a LINEAR sweep for the JMPS (0xFA) and CALLS (0xDA)
# opcodes. Run over data it produces coincidences, and the more const data an
# image carries the more of them there are: V29's generated slot table put a
# 0xDA at file 0x0EE26C, which is the low byte of the offset field 0x04DA
# (= CAL_DBW_KP, 1242) of one hc_cfg_slots[] entry. Reported as "1 offender,
# segment outside the flash", it looked exactly like a branch into the removed
# Bosch application, and it is a lookup table.
#
# So the scan range is the EXECUTABLE classes only, read from the linker script
# rather than retyped - if a class moves, this moves with it. Const data still
# has to satisfy check 7 (everything outside the declared sections is 0xFF) and
# check 9 (the parked table), and nothing branches INTO it: the linker map
# types those sections DATA, and Keil places no entry point there.
LNP = TARGET_DIR / "linker_me711.lnp"


def _class_range(name):
    """Lowest start and highest end of a CLASSES(...) entry, as FILE offsets.

    The linker states CPU addresses (0x8Exxxx); the image file is
    0x800000-relative, which is the same convention CODE_LO already uses."""
    # COMMENTS ARE NOT THE SCRIPT. L166's comment character is ';', and V55's
    # note about the 64 KiB CGROUP limit quotes the linker's own error text -
    # "GROUP: NCODE (1)" - which this search matched before the real
    # declaration and then reported as "NCODE has no address window". A parser
    # that reads a file's comments as its content produces a failure that
    # points at the wrong file entirely.
    txt = "\n".join(l.split(";", 1)[0]
                    for l in LNP.read_text(errors="replace").splitlines())
    m = re.search(r"\b%s\s*\(([^)]*)\)" % name, txt)
    if not m:
        raise SystemExit("%s not found in %s - the far-branch scan cannot "
                         "guess its own range" % (name, LNP))
    windows = re.findall(r"0x([0-9A-Fa-f]+)\s*-\s*0x([0-9A-Fa-f]+)", m.group(1))
    if not windows:
        raise SystemExit("%s in %s has no address window" % (name, LNP))
    lo = min(int(a, 16) for a, _b in windows)
    hi = max(int(b, 16) for _a, b in windows)
    return lo - 0x800000, hi - 0x800000


_ic_lo, _ic_hi = _class_range("ICODE")
_nc_lo, _nc_hi = _class_range("NCODE")
EXEC_LO, EXEC_HI = min(_ic_lo, _nc_lo), max(_ic_hi, _nc_hi)

# The boot block's published service table: 60 `JMPS 00:xxxx` trampolines at
# 0x000220-0x00030F. A HaniCore CALLS into segment 0 is only legitimate if it
# lands on one of these - and this build makes none, which is itself checked.
SERVICE_LO, SERVICE_HI = 0x000220, 0x00030F

# THE ONE FAR BRANCH THAT LEAVES THE FLASH DEVICE ALTOGETHER, and it is the
# whole point of hcnvm.c: the calibration programmer is copied into the
# external SRAM and entered with `JMPS #038H,#06000H`, because it erases the
# device its original is stored in. Bosch Motorsport's MS 4 Sport relocates its
# own programmer for the same reason (to 0x38C000) and so does the other
# standalone ME7.4.4.
#
# The exception is deliberately NARROW: this exact segment and offset, and
# EXACTLY ONE site. An unbounded "segment 0x38 is fine" would let a later edit
# add a second jump out of code that nothing had argued for. The address is
# read from hctarget.h rather than written here - see
# feedback_one_place_for_shared_layout.
_TGT = (ROOT / "firmware/targets/me711/hctarget.h").read_text(
    errors="replace")


def _tgt(name):
    return int(re.search(r"#define\s+%s\s+(0x[0-9A-Fa-f]+)" % name,
                         _TGT).group(1), 16)


FLASHRT_SEG = _tgt("TGT_EXTRAM_BASE") >> 16
FLASHRT_OFF = _tgt("TGT_RAM_FLASHRT")

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<52s} {detail}")
    return ok


def u16(b, o):
    return b[o] | (b[o + 1] << 8)


def u32(b, o):
    return int.from_bytes(b[o:o + 4], "little")


def parse_ihex(path):
    """Parse and checksum Intel HEX into an address->byte dictionary."""
    upper = 0
    out = {}
    for lineno, raw in enumerate(path.read_text(errors="strict").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if not line.startswith(":"):
            raise ValueError(f"{path.name}:{lineno}: not an Intel HEX record")
        rec = bytes.fromhex(line[1:])
        if len(rec) < 5 or len(rec) != rec[0] + 5 or sum(rec) & 0xFF:
            raise ValueError(f"{path.name}:{lineno}: invalid length/checksum")
        n, addr, typ = rec[0], (rec[1] << 8) | rec[2], rec[3]
        body = rec[4:4 + n]
        if typ == 0:
            for i, value in enumerate(body):
                out[upper + addr + i] = value
        elif typ == 2:
            upper = int.from_bytes(body, "big") << 4
        elif typ == 4:
            upper = int.from_bytes(body, "big") << 16
        elif typ == 1:
            break
    return out


def map_symbol(path, name):
    text = path.read_text(errors="replace")
    m = re.search(rf"^\s*([0-9A-F]{{6}})H\s+{re.escape(name)}\b", text, re.M)
    return int(m.group(1), 16) if m else None


def program_page_sum(img):
    """THIS USED TO BE A SECOND COPY OF THE RANGES, and that is precisely the
    defect this file exists to catch elsewhere. It hardcoded 0x00000-0x0FFFF
    and 0x20000-0xFFFFF, so after V53 moved the boundary it disagreed with both
    the builder AND the ECU while looking like an independent opinion.

    The page list now comes from the image's own ROMSYS header, via the
    builder. The genuinely independent check is
    tests/firmware/build/me711_bootsum_coverage_proof.py, which does not model the ranges at
    all - it EXECUTES the Bosch boot block and records what it reads."""
    t = 0
    for base in build.bootsum_pages(img):
        t += u16(img, base) + u16(img, base + PAGE - 2)
    return t & 0xFFFFFFFF


# --------------------------------------------------------------- the scan --
LONG_COLS = {2, 3, 4, 5, 6, 7, 0xA}


def ilen(op):
    return 4 if (op & 0x0F) in LONG_COLS else 2


def scan_far_targets(img, lo, hi):
    """Every JMPS/CALLS in a byte range, as (site, segment, offset).

    A linear sweep, deliberately. Recursive descent would follow only reachable
    code and this check wants the opposite: if a `CALLS 0x82,...` is sitting in
    the image at all, somebody should know about it, reachable or not.
    """
    out = []
    off = lo
    while off <= hi - 3:
        op = img[off]
        if op in (0xFA, 0xDA):
            seg = img[off + 1]
            dst = u16(img, off + 2)
            out.append((off, op, seg, dst))
        off += ilen(op)
    return out


def main():
    print("=== HaniCore Bosch ME7.1.1 - clean image validation ===\n")
    if not IMG.exists():
        raise SystemExit(f"no image at {IMG} - run "
                         "tools/build/build_hanicore_me711.py")
    img = IMG.read_bytes()
    man = json.loads(MANIFEST.read_text())
    owned_boot = man.get("boot_region") == "hanicore_owned"
    if owned_boot:
        # The expected region is the generator's output for this image's own
        # entry pointer and header ranges; the sums are checked below.
        import me711_owned_boot as OWNED
        ref = bytearray(img)
        tbl = u32(img, HEADER + 0x08) + HEADER
        OWNED.compose(ref, man["entry_cpu"], u32(img, tbl + 0x10),
                      u32(img, tbl + 0x14), u32(img, HEADER + 0x14))
        contract = bytes(ref[:CONTRACT_LEN])
    else:
        contract = CONTRACT.read_bytes()
    WDTCON_SERVICE = int(man["watchdog_service_value"], 0)

    # 1 -------------------------------------------------------------------
    check("image is exactly 1 MiB", len(img) == IMAGE_SIZE, f"{len(img)} bytes")
    check("sha256 matches the manifest",
          hashlib.sha256(img).hexdigest().upper() == man["sha256"],
          man["sha256"][:16] + "...")
    # A frozen release gate must not depend on the current development source.
    # The manifest pins the value that was used for this exact binary; the
    # builder checked C/assembler consistency before writing that manifest.
    check("manifest identifies the selected build",
          man.get("build") == PI.EXPECTED_BUILD
          and man.get("watchdog_service_value") == "0x%04X" % WDTCON_SERVICE
          # V2 drives P6.4 on even boots on purpose, so the old
          # "all ASIC pins stay inputs" wording would be a false claim.
          and man.get("asic_mode")
              == "LIVE_STARTUP_HANDSHAKE_96W_THEN_118W_RUNTIME"
          and man.get("experiment", {}).get("engine_outputs", "")
              .startswith("COUNTING-ONLY BENCH_SAFE"),
          f"build {man.get('build')}, WDTCON "
          f"{man.get('watchdog_service_value')}, ASIC {man.get('asic_mode')}")

    # The frozen binary is accompanied by three different provenance forms:
    # the linker's M66 symbol map, its H86 payload, and the programmer HEX of
    # the complete 1 MiB image. Hash all three from the manifest, then prove
    # their content relationship instead of trusting matching timestamps.
    def provenance(field, hash_field):
        rel = man.get(field, "")
        path = ROOT / rel
        got = hashlib.sha256(path.read_bytes()).hexdigest().upper() if path.exists() else ""
        return path, bool(got and got == man.get(hash_field, "").upper())

    map_path, map_ok = provenance("linked_map", "linked_map_sha256")
    payload_hex, payload_ok = provenance("linked_payload_hex",
                                         "linked_payload_hex_sha256")
    programmer_hex, programmer_ok = provenance("programmer_hex",
                                               "programmer_hex_sha256")
    check("manifest pins the linked M66 map", map_ok,
          man.get("linked_map_sha256", "")[:16] + "...")
    check("manifest pins the linked H86 payload", payload_ok,
          man.get("linked_payload_hex_sha256", "")[:16] + "...")
    check("manifest pins the complete programmer HEX", programmer_ok,
          man.get("programmer_hex_sha256", "")[:16] + "...")

    symbols = {
        "?C_STARTUP": "entry_cpu", "main": "main_cpu",
        "asic_isolate": "asic_isolate_cpu", "asic_init": "asic_init_cpu",
        "asic_service": "asic_service_cpu",
        "hc_asic_start_service": "asic_start_service_cpu",
    }
    sym_bad = []
    if map_ok:
        for symbol, field in symbols.items():
            if map_symbol(map_path, symbol) != man.get(field):
                sym_bad.append((symbol, map_symbol(map_path, symbol), man.get(field)))
    check("M66 symbols equal the JSON lineage addresses",
          map_ok and not sym_bad,
          "6/6 agree" if map_ok and not sym_bad else str(sym_bad[:2]))

    try:
        final_records = parse_ihex(programmer_hex) if programmer_ok else {}
        rebuilt = bytearray(b"\xFF" * IMAGE_SIZE)
        in_range = all(0 <= a < IMAGE_SIZE for a in final_records)
        if in_range:
            for addr, value in final_records.items():
                rebuilt[addr] = value
        final_exact = in_range and bytes(rebuilt) == img
    except (OSError, ValueError) as exc:
        final_exact = False
        final_records = {}
    check("programmer HEX reconstructs the exact frozen BIN", final_exact,
          f"{len(final_records)} explicit bytes")

    try:
        linked_records = parse_ihex(payload_hex) if payload_ok else {}
        # The builder deliberately relocates the parked Keil vector table
        # from E0000..E01FF to the live second-level table at 020000, then
        # erases the parked copy. Every other linked payload byte must survive.
        linked_bad = []
        for address, value in linked_records.items():
            off = CODE_LO + address       # OH166 H86 is relative to E0000
            if CODE_LO <= off < CODE_LO + 0x200:
                continue                  # relocated vector table
            if off >= IMAGE_SIZE or img[off] != value:
                linked_bad.append((off, value,
                                   img[off] if off < IMAGE_SIZE else None))
    except (OSError, ValueError) as exc:
        linked_records, linked_bad = {}, [(0, 0, 0)]
    check("H86 payload equals BIN outside relocated vectors",
          payload_ok and bool(linked_records) and not linked_bad,
          f"{len(linked_records)} linked bytes" if not linked_bad
          else f"first mismatch {linked_bad[0]}")
    # The strings the bench guide tells the user to look for must actually be
    # in the image. DIAG_V12 trimmed the output deliberately - the previous
    # build spent 231 ms of a 255 ms run transmitting - so HCPREV is gone and
    # the banner is deliberately "FIX_10MS", not the full name: hcts_tx() is
    # baud-paced and blocking, so every extra character printed before the
    # ASIC section delays every exchange that follows by a real, measured
    # amount - see the long comment in hcmain_me711.c's banner(). "UMKOM_14"
    # is the same 8 characters long as frozen V11's "ECHO_V11" and V13's
    # "FIX_10MS", so this line costs exactly what theirs did.
    #
    # V17 removed "HCL T=" (alive_line()) and "NL=" (one of its fields)
    # DELIBERATELY and PERMANENTLY, not as a trim: alive_line() is the
    # ~127 ms blocking print that was starving hc_asic_start_service() and
    # causing the ~140 ms SWRST_SM V15's hardware log exposed (see
    # docs/ARCHITECTURE.md/§5h). The function no longer exists
    # in this build; the fields it used to carry are documented as a comment
    # at its former location for a future non-blocking replacement, not
    # shipped as bytes in the image. Do not add either string back to `want`.
    #
    # V23 removed every unsolicited boot line. The frozen manifest now pins
    # the only identity text that may be emitted, and only after a request.
    want = [man.get("signature", "").encode(),
            man.get("version_text", "").encode(), b"001"]
    missing = [w for w in want if w not in img]
    check("the solicited protocol identity strings are linked", not missing,
          "all present" if not missing else str(missing))
    forbidden = [w for w in (b"HCRST B=", b"HCSTEP ST=", b"ASIC=LIVE",
                             b"HC711 RELAY") if w in img]
    check("removed unsolicited boot strings are not linked", not forbidden,
          "none" if not forbidden else str(forbidden))

    # Instruction-level proof of the watchdog change. Every SRVWDT opcode in
    # the linked payload must be immediately dominated by one of the two
    # emitted WDTCON write sequences; a bare service is precisely the
    # regression this image exists to test.
    #
    # THE COUNT IS PINNED, and it is a named breakdown rather than a number, so
    # that a service appearing somewhere nobody argued for is a FAILURE and not
    # a quiet increment:
    #
    #     5   start_me711.a66
    #     1   hc_srvwdt(), the shared C helper
    #     2   hcnvm.c's RAM-resident flash programmer - one in the bounded
    #         program poll and one in the post-success settle interval. It
    #         cannot call hc_srvwdt(): it runs from the external SRAM and may
    #         not touch the flash device it is erasing, so it writes WDTCON and
    #         issues SRVWDT inline. The first version of that file used a BARE
    #         SRVWDT in all four and this check is what caught it.
    #
    # Raising this number is a decision. Make it visibly.
    code = img[CODE_LO:CODE_HI + 1]
    srvwdt = bytes.fromhex("A758A7A7")
    # The expected value is pinned by this image's manifest rather than the
    # mutable development header. This still catches a bare service or wrong
    # immediate in the binary and remains valid after a V21 source bump.
    _lo, _hi = WDTCON_SERVICE & 0xFF, (WDTCON_SERVICE >> 8) & 0xFF
    # MOV R12,#imm ; MOV WDTCON,R12      (the startup's form)
    startup_prefix = bytes((0xE6, 0xFC, _lo, _hi, 0xF6, 0xFC, 0xAE, 0xFF))
    # MOV WDTCON,#imm                    (the C helper's form)
    helper_prefix = bytes((0xE6, 0xD7, _lo, _hi))
    sites = []
    at = code.find(srvwdt)
    while at >= 0:
        sites.append(at)
        at = code.find(srvwdt, at + 1)
    protected = all((p >= len(startup_prefix)
                     and code[p - len(startup_prefix):p] == startup_prefix)
                    or (p >= len(helper_prefix)
                        and code[p - len(helper_prefix):p] == helper_prefix)
                    for p in sites)
    # THE COUNT IS AN INVENTORY, NOT THE SAFETY PROPERTY. `protected` is the
    # safety property: every SRVWDT in the image must be preceded by a WDTCON
    # write, because the C167CR manual asks for it (13.1) and a bare service is
    # the defect this check was written for. The count exists so that a service
    # appearing somewhere NEW has to be acknowledged rather than absorbed.
    #
    # 5 + 1 + 2 was "program-only persistence removed the two erase polling
    # loops". V53 reclaims the store, so hc_nvm_eraser() brings two back: one
    # in its erase-slice poll and one in its suspend-latency wait. Both are in
    # the relocated routine, where a bare SRVWDT would be especially bad - it
    # runs with the device busy and cannot call anything to recover.
    #
    # THE LAST +1 IS ACKNOWLEDGED, WHICH IS WHAT THIS COUNT IS FOR. The writer's
    # failure path now PROVES the part has come back to read-array mode before
    # it returns into flash, instead of writing FL_RESET and hoping - see
    # hc_nvm_payload()'s reset_and_return. That proof is a bounded poll, so it
    # is a poll that has to service the watchdog like every other one here.
    WDT_SITES = 5 + 1 + 2 + 2 + 1
    check("all emitted SRVWDT sites write WDTCON=0x%04X first" % WDTCON_SERVICE,
           len(sites) == WDT_SITES and protected,
           (f"{len(sites)} sites, all protected"
            if protected and len(sites) == WDT_SITES
           else f"{len(sites)} sites (expected {WDT_SITES}), all protected"
           if protected else f"{len(sites)} sites, bare service found"))

    def calla(addr):
        return bytes((0xCA, 0x00, addr & 0xFF, (addr >> 8) & 0xFF))

    main_off = man["main_cpu"] - 0x800000
    main_window = img[main_off:main_off + 0x300]
    isolate_call = calla(man["asic_isolate_cpu"])
    # asic_init is COMPILED OUT while the link is isolated, so there is no
    # V4 inverts this. Up to V3 the requirement was that asic_init could not
    # even be found in the map; now the handshake IS the experiment, so the
    # requirement is that both it and the state machine are linked - and that
    # the engine layer still is not.
    check("the ASIC handshake and live mode are consistent",
          man.get("asic_init_cpu") is not None
          and man.get("asic_mode", "").startswith("LIVE_"),
          f"asic_init 0x{man.get('asic_init_cpu', 0):06X}, "
          f"mode {man.get('asic_mode')}")

    # 2 -------------------------------------------------------------------
    # The boot contract, byte for byte, except the three fields the build owns.
    owned = set(range(HEADER + 0x00, HEADER + 0x04))     # entry far pointer
    owned |= set(range(HEADER + 0x38, HEADER + 0x40))    # the two sum records
    # V53: the build also owns the record's COVERAGE, because the boot block
    # reads it from here. header+0x14 is loop 2's limit; header+0x30/+0x34 are
    # the descriptor table's loop-1 limit and loop-2 start (the table sits at
    # header+0x20). Writing them makes the image state its whole contract
    # instead of inheriting two thirds of it from the donor.
    owned |= set(range(HEADER + 0x14, HEADER + 0x18))
    owned |= set(range(HEADER + 0x30, HEADER + 0x38))
    diffs = [i for i in range(CONTRACT_LEN)
             if img[i] != contract[i] and i not in owned]
    check("boot region is the HaniCore generator's output" if owned_boot
          else "boot contract retained byte for byte", not diffs,
          "unchanged" if not diffs
          else f"{len(diffs)} unexpected diffs, first 0x{diffs[0]:06X}")
    changed = sorted(i for i in owned if img[i] != contract[i])
    check("and the header fields the build owns DID change",
          owned_boot or len(changed) >= 2, f"{len(changed)} bytes at "
          + ",".join(f"0x{i:04X}" for i in changed[:6]))

    # 3 -------------------------------------------------------------------
    st_have = u32(img, HEADER + 0x38)
    st_want = (u16(img, 0x8000) + u16(img, 0xFFFE)) & 0xFFFFFFFF
    check("ROMSYS startup sum @0x008038", st_have == st_want,
          f"0x{st_have:08X}")
    pp_have = u32(img, HEADER + 0x3C)
    pp_want = program_page_sum(img)
    check("ROMSYS program-page sum @0x00803C", pp_have == pp_want,
          f"0x{pp_have:08X}")
    ppp = u32(img, HEADER + 0x10) - 0x800000
    par_have = u32(img, ppp)
    par_want = (u16(img, 0x10000) + u16(img, 0x1FFFE)) & 0xFFFFFFFF
    check(f"ROMSYS parameter-page sum @0x{ppp:06X}", par_have == par_want,
          f"0x{par_have:08X}")

    # 4 -------------------------------------------------------------------
    entry = (u16(img, HEADER + 2) << 16) | u16(img, HEADER + 0)
    entry_off = entry - 0x800000
    check("header entry points into the HaniCore code sector",
          CODE_LO <= entry_off <= CODE_HI, f"0x{entry:06X}")
    check("header entry equals the linked ?C_STARTUP",
          entry == man["entry_cpu"], f"0x{man['entry_cpu']:06X}")
    check("the entry is a real instruction, not blank flash",
          img[entry_off] != 0xFF,
          f"first byte 0x{img[entry_off]:02X}")

    # 5 -------------------------------------------------------------------
    bad = []
    for slot in range(1, 128):
        e = img[ISR_TABLE + slot * 4: ISR_TABLE + slot * 4 + 4]
        if e[0] != 0xFA:
            bad.append((slot, "not a JMPS"))
            continue
        t = ((e[1] << 16) | (e[2] | (e[3] << 8))) - 0x800000
        if not (CODE_LO <= t <= CODE_HI):
            bad.append((slot, f"0x{t + 0x800000:06X}"))
    check("every vector slot 1..127 lands in HaniCore code", not bad,
          "127 slots" if not bad else f"{len(bad)} bad, first {bad[0]}")
    # Slot 0 of the SECOND-level table is unreachable - the first-level reset
    # slot goes to the boot block's own stub and never here - but it must still
    # be an instruction rather than blank flash.
    s0 = img[ISR_TABLE:ISR_TABLE + 4]
    s0t = ((s0[1] << 16) | (s0[2] | (s0[3] << 8))) - 0x800000 if s0[0] == 0xFA else -1
    check("vector slot 0 is an instruction, not blank flash",
          s0[0] == 0xFA and CODE_LO <= s0t <= CODE_HI,
          s0.hex(" ").upper())

    # 6 -------------------------------------------------------------------
    # THE ONE THAT MATTERS. Nothing in HaniCore code may branch into the
    # removed application.
    targets = scan_far_targets(img, EXEC_LO, EXEC_HI)
    offenders = []
    relocated = []
    for site, op, seg, dst in targets:
        if seg == FLASHRT_SEG and dst == FLASHRT_OFF:
            relocated.append((site, op))   # see the check below
            continue
        if 0x81 <= seg <= 0x8F:
            t = (seg - 0x80) * 0x10000 + dst
        elif seg in (0x00, 0x80):
            t = dst
        else:
            offenders.append((site, seg, dst, "segment outside the flash"))
            continue
        if CODE_LO <= t <= CODE_HI:
            continue                       # our own code
        if SERVICE_LO <= t <= SERVICE_HI:
            continue                       # a documented boot-block service
        if img[t] == 0xFF and img[t + 1] == 0xFF:
            offenders.append((site, seg, dst, "into ERASED flash"))
        else:
            offenders.append((site, seg, dst, "outside HaniCore code"))
    # EXACTLY TWO, AND THE KINDS ARE CHECKED, NOT JUST THE COUNT.
    #
    # 0x38:6000 is TGT_RAM_FLASHRT, the external SRAM the calibration
    # programmer copies itself into. Two things in this firmware go there and
    # they are different instructions for different reasons:
    #
    #   CALLS hc_nvm_payload - the program-only writer. It returns only after
    #                           explicitly restoring read-array mode;
    #   CALLS hc_nvm_ramprobe - the SRAM execution probe. It RETURNS, which is
    #                           the whole point of it, so it must be a CALLS
    #                           and the routine must be `far`.
    #
    # Checking the opcodes rather than the count is what makes this a real
    # assertion: a JMPS where the probe should be would mean a probe that can
    # never come back, and a CALLS where the programmer should be would mean a
    # return into a device that is mid-erase.
    kinds = sorted(op for _site, op in relocated)
    check("exactly TWO far calls leave the flash device: the calibration "
          "programmer and the SRAM execution probe",
          kinds == [0xDA, 0xDA],
          "%d site(s) to 0x%02X:%04X, opcodes %s"
          % (len(relocated), FLASHRT_SEG, FLASHRT_OFF,
             " ".join("%02X" % k for k in kinds) or "none"))
    check("no JMPS/CALLS out of HaniCore code", not offenders,
          f"{len(targets)} far branches in ICODE+NCODE "
          f"(0x{EXEC_LO:06X}-0x{EXEC_HI:06X}), all internal" if not offenders
          else f"{len(offenders)} offenders, first at 0x{offenders[0][0]:06X}")
    for site, seg, dst, why in offenders[:10]:
        print(f"          0x{site:06X} -> {seg:02X}:{dst:04X}   {why}")

    # 6b - classify byte-pattern coincidences as well. Looking at EVERY byte
    # position is useful as an audit lead, but an unaligned 0xFA/0xDA inside an
    # immediate or another instruction is not an executable far branch. The
    # old validator incorrectly made the absence of all such coincidences a
    # release requirement; adding ordinary code eventually made that
    # impossible property fail. Cross-check every coincidence against the
    # instruction-boundary sweep above instead.
    suspects = []
    for off in range(CODE_LO, CODE_HI - 3):
        if img[off] not in (0xFA, 0xDA):
            continue
        seg = img[off + 1]
        if not (0x81 <= seg <= 0x8F):
            continue
        t = (seg - 0x80) * 0x10000 + u16(img, off + 2)
        if CODE_LO <= t <= CODE_HI:
            continue
        suspects.append((off, seg, t))
    decoded_sites = {site for site, _, _, _ in targets}
    aligned_suspects = [s for s in suspects if s[0] in decoded_sites]
    check("removed-space byte patterns are not instruction-aligned branches",
          not aligned_suspects,
          (f"{len(suspects)} unaligned coincidence(s), none executable"
           if suspects else "no coincidences"))
    for off, seg, t in aligned_suspects[:6]:
        print(f"          0x{off:06X}: FA/DA {seg:02X} -> 0x{t + 0x800000:06X}")

    # 6c - and confirm the scanner is not simply blind, by pointing it at the
    # OEM image, where it must find a great many.
    oem = hcpaths.OEM_READ
    if oem.exists():
        o = oem.read_bytes()
        # 0x0C0000 is where the OEM second-stage entry lives (0x8C09B8), so
        # it is definitely dense OEM code - a region that must produce far
        # branches if the scanner works at all.
        found = scan_far_targets(o, 0x0C0000, 0x0C4000)
        check("the far-branch scanner is not blind (OEM control)",
              len(found) > 10,
              f"{len(found)} far branches in 16 KiB of OEM code")

    # 7 -------------------------------------------------------------------
    # Not one byte of the removed application survives. Everything outside the
    # declared sections must be 0xFF.
    declared = []
    declared.append((0x000000, CONTRACT_LEN - 1))
    declared.append((ISR_TABLE, ISR_TABLE + 0x1FF))
    declared.append((CODE_LO, CODE_HI))
    declared.append((0x038004, 0x038007))
    stray = []
    for i in range(CONTRACT_LEN, IMAGE_SIZE):
        if img[i] == 0xFF:
            continue
        if any(lo <= i <= hi for lo, hi in declared):
            continue
        stray.append(i)
        if len(stray) > 8:
            break
    check("everything outside the declared sections is 0xFF", not stray,
          "clean" if not stray else f"{len(stray)}+ stray, first 0x{stray[0]:06X}")

    # 8 -------------------------------------------------------------------
    # V53: the single SA18 calibration sector is gone; the append-only store is
    # SA9..SA18 and it ships wholly blank so the first boot reads EMPTY rather
    # than a failed burn.
    store = img[STORE_LO:STORE_HI + 1]
    check("the persistence store ships blank",
          all(b == 0xFF for b in store),
          f"0x{STORE_LO:06X}-0x{STORE_HI:06X}, {GEO.cells} cells")

    # 8b ------------------------------------------------------------------
    # AND IT IS OUTSIDE THE BOOT RECORD. This is the property the whole V53
    # relayout exists for, and it is asserted against the page list the BUILD
    # derives from the header - the same list the boot block will walk.
    pages = build.bootsum_pages(img)
    check("no boot-checksummed page lies inside the store",
          not any(STORE_LO <= b <= STORE_HI for b in pages),
          f"{len(pages)} pages, top 0x{max(pages):06X}")
    check("every HaniCore code page IS boot-checksummed",
          all(b in pages for b in range(CODE_LO, CODE_HI + 1, PAGE)),
          f"0x{CODE_LO:06X}-0x{CODE_HI:06X}")

    # 9 -------------------------------------------------------------------
    park = img[CODE_LO:CODE_LO + 0x200]
    # 8c ------------------------------------------------------------------
    # EVERY ACCESS TO THE BATTERY-BACKED NVM CONTROL BLOCK MUST CARRY ITS
    # SEGMENT OVERRIDE, AND THIS IS NOT A STYLE RULE.
    #
    # The block lives at 0x386800 behind `huge` pointers, so Keil must emit an
    # EXTS #38h before each access. A BARE 16-bit operand like 0x6806 resolves
    # through DPP1 instead - which points at NCONST - so it reads a CONSTANT
    # BYTE rather than the control block, silently.
    #
    # THE FROZEN, FLASHED V52 BINARY HAS EXACTLY THIS DEFECT, twice, at
    # 0x8E1D6A and 0x8E1D78: both loads of cb_cell inside retry_target().
    # CELL_ADDR() expands its argument three times inside one 32-bit address
    # expression and Keil dropped the prefix on the duplicates - four of the
    # six cb_cell loads in the image were right and two were wrong.
    #
    # IT WAS INVISIBLE FOR FOUR RELEASES because retry_target() only runs when
    # a word fails to program, and no word ever has on this ECU: 88 physical
    # Burns, nvmRetries 0, nvmProgFlags 0. Under fault injection V52 read a
    # garbage cell index, and its two-sector CELL_ADDR clamped ANY index to a
    # MAPPED address, so it read the wrong word and limped on. V53's
    # ten-sector CELL_SEG turns the same garbage into segment 0xA5, which is
    # not mapped - and the Burn hung with no reply.
    #
    # So the class is: a wild read that the old geometry happened to absorb.
    # Reading the source cannot see it; this reads the LINKED IMAGE.
    #
    # The EXTS/EXTP coverage window matters - irang2 covers up to four
    # following instructions - and a checker that only looks one instruction
    # back reports nine false positives on a clean image. Ask for the window.
    _LONG = {2, 3, 4, 5, 6, 7, 0xA}
    _MEMOPS = {0xF2: "MOV Rw,mem", 0xF6: "MOV mem,Rw",
               0xF3: "MOVB Rb,mem", 0xF7: "MOVB mem,Rb"}
    _nvm_lo = int(re.search(r"#define\s+TGT_RAM_NVM\s+(0x[0-9A-Fa-f]+)",
                            (ROOT / "firmware/targets/me711/hctarget.h")
                            .read_text(errors="replace")).group(1), 16)
    _nvm_hi = _nvm_lo + 0xFF
    _bare, _i, _cover = [], CODE_LO, 0
    while _i < CODE_HI - 3:
        _op = img[_i]
        _n = 4 if (_op & 0x0F) in _LONG else 2
        if _op in _MEMOPS and _n == 4 and _cover == 0:
            _m = img[_i + 2] | (img[_i + 3] << 8)
            if _nvm_lo <= _m <= _nvm_hi:
                _bare.append((_i, _MEMOPS[_op], _m))
        if _op in (0xD7, 0xDC):
            _cover = ((img[_i + 1] >> 4) & 0x03) + 1
        elif _cover:
            _cover -= 1
        _i += _n
    check("every NVM control-block access carries its EXTS segment override",
          not _bare,
          f"{len(_bare)} bare access(es)" + (
              "" if not _bare
              else ", first " + f"0x{0x800000 + _bare[0][0]:06X} "
                   f"{_bare[0][1]} 0x{_bare[0][2]:04X}"))

    # AND THE CHECK MUST BE ABLE TO FAIL. Running it against the frozen V52
    # binary is NOT a control - CODE_LO/CODE_HI come from the current
    # hctarget.h, so it would scan the wrong 64 KiB of that image and report a
    # clean pass. That is precisely the "a mutation that no longer applies has
    # stopped testing anything" trap. So the control is self-contained: blind
    # one real EXTS prefix in a COPY of this image and require the scan to
    # notice.
    def _scan(buf):
        out, i, cov = [], CODE_LO, 0
        while i < CODE_HI - 3:
            o = buf[i]
            ln = 4 if (o & 0x0F) in _LONG else 2
            if o in _MEMOPS and ln == 4 and cov == 0:
                mm = buf[i + 2] | (buf[i + 3] << 8)
                if _nvm_lo <= mm <= _nvm_hi:
                    out.append(i)
            if o in (0xD7, 0xDC):
                cov = ((buf[i + 1] >> 4) & 0x03) + 1
            elif cov:
                cov -= 1
            i += ln
        return out

    _mut, _site = bytearray(img), None
    _i, _cov = CODE_LO, 0
    while _i < CODE_HI - 3 and _site is None:
        _o = _mut[_i]
        _ln = 4 if (_o & 0x0F) in _LONG else 2
        if _o == 0xD7 and _mut[_i + 2] == 0x38:
            _nx = _i + 4
            if _mut[_nx] in _MEMOPS:
                _mm = _mut[_nx + 2] | (_mut[_nx + 3] << 8)
                if _nvm_lo <= _mm <= _nvm_hi:
                    _site = _i
        _i += _ln
    if _site is not None:
        _mut[_site] = 0xCC          # NOP: the prefix is gone, the access is not
        check("control: blinding one EXTS prefix makes the scan fail",
              len(_scan(bytes(_mut))) > len(_bare),
              f"mutated 0x{0x800000 + _site:06X}, "
              f"{len(_scan(bytes(_mut)))} bare vs {len(_bare)}")
    else:
        check("control: an EXTS-prefixed NVM access exists to mutate",
              False, "none found - the scan would be vacuous")

    check("the parked vector table was blanked after relocation",
          all(b == 0xFF for b in park),
          "no stale second table")

    # 10 ------------------------------------------------------------------
    # The RAM map has to be free of overlaps, or two modules quietly share a
    # byte - which has already happened once on the other target.
    ram = [
        ("asic frame", 0x00E100, 236),
        ("system stack", 0x00F606, 0xFA),
        ("keil C data", 0x00F700, 0x700),
        ("cal page", 0x380000, 0x2000),
        ("och block", 0x382000, 0x400),
        ("reset log", 0x382400, 0x100),
        ("asic snapshot", 0x382500, 0x300),
    ]
    ram.sort(key=lambda r: r[1])
    clash = []
    for a, b in zip(ram, ram[1:]):
        if a[1] + a[2] > b[1]:
            clash.append((a[0], b[0]))
    check("no RAM region overlaps another", not clash,
          f"{len(ram)} regions" if not clash else str(clash))

    print()
    bad_n = sum(1 for _, ok, _ in results if not ok)
    print(f"{len(results) - bad_n}/{len(results)} checks pass")
    if bad_n:
        print("VALIDATION FAILED - do not flash")
        return 1
    print(f"VALIDATION PASSES (offline checks of {PI.EXPECTED_BUILD}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
